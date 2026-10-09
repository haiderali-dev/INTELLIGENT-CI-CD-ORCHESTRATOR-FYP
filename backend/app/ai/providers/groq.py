"""Groq through the official ``openai`` SDK.

BUILD_PROMPT 4.5.1: "``GroqProvider`` uses the official ``openai`` Python SDK pointed at Groq's
OpenAI-compatible base URL, with ``response_format`` set to a strict JSON schema."

Verified against the live API on 2026-10-09 before this was written, rather than assumed: strict
schemas (including enums that admit null) are honoured by ``openai/gpt-oss-120b``, usage comes back
with reasoning tokens counted inside ``completion_tokens``, and every response carries
``x-ratelimit-*`` headers giving the server's own view of the remaining quota.

``max_retries=0`` on the SDK client is deliberate. The SDK would otherwise retry 429s and 5xx on its
own, invisibly, which would both double-count against the quota and hide exactly the failures
``ModelChain`` needs to see to decide whether to move down the chain.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from typing import Any, Final

import openai
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared import ReasoningEffort

from app.ai.providers.base import (
    ChatMessage,
    InvalidResponseError,
    LLMProvider,
    ParsedResult,
    ProviderRejectedError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

GROQ_BASE_URL: Final = "https://api.groq.com/openai/v1"
TIMEOUT_SECONDS: Final = 30.0

# Reasoning tokens count against this, so it is generous relative to the ~60-token JSON answer.
# A truncated answer is reported as InvalidResponseError rather than parsed, which is the reason
# for the margin: a cut-off object is worse than none.
MAX_COMPLETION_TOKENS: Final = 1024

# A retry-after longer than this is treated as exhaustion rather than a pause: nobody waits a
# minute for an intent card while a smaller model and the rule parser are available.
LONG_WAIT_SECONDS: Final = 20.0

_RATE_HEADERS: Final = (
    "x-ratelimit-limit-requests",
    "x-ratelimit-limit-tokens",
    "x-ratelimit-remaining-requests",
    "x-ratelimit-remaining-tokens",
    "x-ratelimit-reset-requests",
    "x-ratelimit-reset-tokens",
    "retry-after",
)

_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")


def parse_duration(text: str | None) -> float | None:
    """Seconds from a Groq duration such as ``1m26.4s``, ``4.282s``, ``2h3m`` or ``500ms``.

    Also accepts a bare number of seconds, which is what ``retry-after`` normally carries.
    """
    if not text:
        return None
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        pass
    total = 0.0
    matched = False
    for amount, unit in _DURATION_PART.findall(text):
        matched = True
        value = float(amount)
        total += {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}[unit] * value
    return total if matched else None


def rate_headers(headers: Any) -> dict[str, str]:
    """The rate-limit headers, lower-cased, from an httpx-style header mapping."""
    if headers is None:
        return {}
    found: dict[str, str] = {}
    for name in _RATE_HEADERS:
        value = headers.get(name)
        if value is not None:
            found[name] = str(value)
    return found


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = GROQ_BASE_URL,
        timeout: float = TIMEOUT_SECONDS,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        if not api_key and client is None:
            raise ValueError(
                "GroqProvider needs GROQ_API_KEY; use LLM_MODE=fake or replay without one"
            )
        self._client = client or openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0
        )

    async def complete_json(
        self,
        *,
        schema: dict[str, Any],
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> ParsedResult:
        started = time.perf_counter()
        try:
            raw = await self._client.chat.completions.with_raw_response.create(
                model=model,
                messages=_messages(system, messages),
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "intent", "schema": schema, "strict": True},
                },
                reasoning_effort=_effort(reasoning_effort),
                temperature=0,
                max_completion_tokens=MAX_COMPLETION_TOKENS,
            )
        except openai.RateLimitError as exc:
            raise _rate_limited(exc, model, _elapsed(started)) from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise ProviderUnavailableError(
                f"{model}: {type(exc).__name__}", latency_ms=_elapsed(started)
            ) from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ProviderUnavailableError(
                    f"{model}: HTTP {exc.status_code}", latency_ms=_elapsed(started)
                ) from exc
            # 400 here usually means the schema or a parameter was rejected; 401/403 a bad key.
            # Neither improves on retry. The message is kept short and free of the request body.
            raise ProviderRejectedError(
                f"{model}: HTTP {exc.status_code} {_short(exc)}", latency_ms=_elapsed(started)
            ) from exc

        latency = _elapsed(started)
        completion = raw.parse()
        choice = completion.choices[0] if completion.choices else None
        if choice is None:
            raise InvalidResponseError(f"{model}: no choices returned", latency_ms=latency)
        if choice.finish_reason == "length":
            raise InvalidResponseError(
                f"{model}: answer truncated at {MAX_COMPLETION_TOKENS} tokens", latency_ms=latency
            )

        content = choice.message.content or ""
        try:
            data = json.loads(content)
        except ValueError as exc:
            raise InvalidResponseError(f"{model}: answer is not JSON", latency_ms=latency) from exc
        if not isinstance(data, dict):
            raise InvalidResponseError(f"{model}: answer is not a JSON object", latency_ms=latency)

        usage = completion.usage
        return ParsedResult(
            data=data,
            provider=self.name,
            model=completion.model or model,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            latency_ms=latency,
            rate_limit=rate_headers(raw.headers),
        )

    async def stream_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=model,
                messages=_messages(system, messages),
                reasoning_effort=_effort(reasoning_effort),
                temperature=0.2,
                stream=True,
            )
        except openai.RateLimitError as exc:
            raise _rate_limited(exc, model, 0) from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise ProviderUnavailableError(f"{model}: {type(exc).__name__}") from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ProviderUnavailableError(f"{model}: HTTP {exc.status_code}") from exc
            raise ProviderRejectedError(f"{model}: HTTP {exc.status_code} {_short(exc)}") from exc

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def aclose(self) -> None:
        await self._client.close()


def _messages(system: str, messages: list[ChatMessage]) -> list[ChatCompletionMessageParam]:
    """The SDK's typed message params.

    Built explicitly rather than as plain dicts: the SDK's overloads are typed per role, so a
    ``list[dict[str, str]]`` matches none of them and the type checker cannot see that the call is
    right. Anything other than an assistant turn is sent as the user's, because only those two
    roles ever come from a conversation.
    """
    built: list[ChatCompletionMessageParam] = [{"role": "system", "content": system}]
    for message in messages:
        if message.role == "assistant":
            built.append({"role": "assistant", "content": message.content})
        else:
            built.append({"role": "user", "content": message.content})
    return built


def _effort(value: str) -> ReasoningEffort:
    """Validate the effort level, defaulting to low.

    gpt-oss accepts low, medium and high. An unknown value would be a 400 from the API, which the
    chain treats as a rejection and moves past -- so it is corrected here rather than spending a
    call to discover it.
    """
    if value in ("low", "medium", "high"):
        return value  # type: ignore[return-value]
    return "low"


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _short(exc: openai.APIStatusError) -> str:
    """A bounded, body-free description of an API error, safe to log."""
    message = getattr(exc, "message", "") or ""
    return message[:160]


def _rate_limited(exc: openai.RateLimitError, model: str, latency: int) -> RateLimitedError:
    """Turn a 429 into a decision: pause briefly, or treat the model as spent.

    Exhaustion is read from the headers when they say so -- no requests remaining -- and otherwise
    inferred from a wait too long to sit through inside a request.
    """
    headers = rate_headers(getattr(exc.response, "headers", None))
    retry_after = parse_duration(headers.get("retry-after"))
    remaining = headers.get("x-ratelimit-remaining-requests")
    exhausted = remaining == "0" or (retry_after is not None and retry_after > LONG_WAIT_SECONDS)
    if exhausted and retry_after is None:
        retry_after = parse_duration(headers.get("x-ratelimit-reset-requests"))
    logger.info(
        "llm_rate_limited",
        model=model,
        retry_after=retry_after,
        exhausted=exhausted,
        remaining_requests=remaining,
    )
    return RateLimitedError(
        f"{model}: rate limited", retry_after=retry_after, exhausted=exhausted, latency_ms=latency
    )
