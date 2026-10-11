"""``ModelChain``: try each model in turn, then the rule parser.

BUILD_PROMPT 4.5.1: "``ModelChain`` walks ``LLM_MODEL_CHAIN``, then the rule parser. Retry on 429 or
5xx after honoring ``retry-after``, at most twice per model. Every call is recorded in
``llm_calls``. ... when a model is exhausted move down the chain and set ``ai_fallback`` on the
response."

How each failure is handled is fixed by its type (``app.ai.providers.base``):

=====================  ============================================================
``RateLimitedError``        short wait: sleep it out and retry the same model;
                       long wait or exhausted: rest the model and move on now
``ProviderUnavailableError`` retry the same model with backoff, up to the retry budget
``InvalidResponseError``    move on: at temperature 0 the same prompt repeats the answer
``ProviderRejectedError``   move on: a 4xx fails the same way every time
``ReplayMissError``         move on: there is no fixture to find on a second look
=====================  ============================================================

"Honoring retry-after" is read as "do not call that model before then", not "make the user wait
however long it says". A daily quota's retry-after is hours; sitting in a request for that while a
smaller model and the rule parser are available would be honoring the header and failing the user.

``ai_fallback`` is true whenever the answer did not come from the *first* model -- the second model
answering is already a degradation the UI should be able to show, not only the rule parser.

The chain never touches the database. It returns one ``CallRecord`` per attempt and the caller
persists them, which keeps the chain testable without a session and lets the evaluation harness use
it without writing rows.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from app.ai.cache import ResponseCache
from app.ai.providers.base import (
    ChatMessage,
    LLMProvider,
    ProviderError,
    ProviderUnavailableError,
    RateLimitedError,
)
from app.ai.quota import QuotaTracker
from app.core.logging import get_logger

logger = get_logger(__name__)

# 4.5.1: "at most twice per model".
RETRIES_PER_MODEL: Final = 2

# The longest a user's request will sit waiting for a rate limit to clear. Past this the model is
# rested and the next one tried. The eval harness raises it, because there a wait is cheap and a
# fallback would contaminate the comparison between models.
INTERACTIVE_MAX_WAIT: Final = 10.0

# Backoff for a 5xx or timeout that came without a retry-after.
BASE_BACKOFF: Final = 0.5

# How long a model rests after an exhausted quota with no reset time given.
DEFAULT_REST_SECONDS: Final = 3600.0


@dataclass(frozen=True)
class CallRecord:
    """One attempt, in the shape of an ``llm_calls`` row."""

    provider: str
    model: str
    outcome: str
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    fallback_used: bool = False
    cached: bool = False
    detail: str = ""


@dataclass(frozen=True)
class ChainResult:
    data: dict[str, Any]
    parser: Literal["llm", "rules"]
    provider: str
    model: str | None
    ai_fallback: bool
    cached: bool = False
    fallback_reasons: tuple[str, ...] = ()
    calls: tuple[CallRecord, ...] = field(default_factory=tuple)

    @property
    def prompt_tokens(self) -> int:
        return sum(call.prompt_tokens for call in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(call.completion_tokens for call in self.calls)


RulesFallback = Callable[[], dict[str, Any]]
Sleeper = Callable[[float], Awaitable[None]]


class ModelChain:
    def __init__(
        self,
        provider: LLMProvider,
        models: tuple[str, ...] | list[str],
        *,
        quota: QuotaTracker,
        cache: ResponseCache | None = None,
        retries_per_model: int = RETRIES_PER_MODEL,
        max_wait: float = INTERACTIVE_MAX_WAIT,
        reasoning_effort: str = "low",
        sleep: Sleeper = asyncio.sleep,
    ) -> None:
        self._provider = provider
        self._models = tuple(model.strip() for model in models if model.strip())
        self._quota = quota
        self._cache = cache
        self._retries = max(0, retries_per_model)
        self._max_wait = max_wait
        self._effort = reasoning_effort
        self._sleep = sleep

    @property
    def models(self) -> tuple[str, ...]:
        return self._models

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    async def complete(
        self,
        *,
        schema: dict[str, Any],
        system: str,
        messages: list[ChatMessage],
        rules_fallback: RulesFallback,
        cache_key: str | None = None,
    ) -> ChainResult:
        if cache_key is not None and self._cache is not None:
            hit = self._cache.get(cache_key)
            if hit is not None:
                logger.info("llm_cache_hit", model=hit.model)
                return ChainResult(
                    data=hit.data,
                    parser="llm",
                    provider=hit.provider,
                    model=hit.model,
                    ai_fallback=hit.ai_fallback,
                    cached=True,
                    # A cache hit is still a call in the 4.5.1 sense; it is what the evaluation's
                    # tokens-per-command figure has to count as zero.
                    calls=(
                        CallRecord(
                            provider=hit.provider,
                            model=hit.model,
                            outcome="cached",
                            cached=True,
                            fallback_used=hit.ai_fallback,
                        ),
                    ),
                )

        calls: list[CallRecord] = []
        reasons: list[str] = []

        for index, model in enumerate(self._models):
            answered = await self._try_model(
                index=index,
                model=model,
                schema=schema,
                system=system,
                messages=messages,
                calls=calls,
                reasons=reasons,
            )
            if answered is None:
                continue

            ai_fallback = index > 0
            if cache_key is not None and self._cache is not None:
                self._cache.put(
                    cache_key,
                    data=answered.data,
                    provider=answered.provider,
                    model=answered.model,
                    ai_fallback=ai_fallback,
                )
            return ChainResult(
                data=answered.data,
                parser="llm",
                provider=answered.provider,
                model=answered.model,
                ai_fallback=ai_fallback,
                fallback_reasons=tuple(reasons),
                calls=tuple(calls),
            )

        # Every model failed or was resting. The rule parser always answers.
        logger.warning("llm_chain_exhausted", reasons=reasons or ["no models configured"])
        return ChainResult(
            data=rules_fallback(),
            parser="rules",
            provider="rules",
            model=None,
            ai_fallback=True,
            fallback_reasons=tuple(reasons or ["no models configured"]),
            calls=tuple(calls),
        )

    async def _try_model(
        self,
        *,
        index: int,
        model: str,
        schema: dict[str, Any],
        system: str,
        messages: list[ChatMessage],
        calls: list[CallRecord],
        reasons: list[str],
    ) -> _Answer | None:
        """Call one model with its retry budget. Returns the answer, or None to move on."""
        verdict = self._quota.check(model)
        if not verdict.allowed:
            if verdict.wait_seconds <= self._max_wait:
                await self._sleep(verdict.wait_seconds)
            else:
                reasons.append(f"{model}: {verdict.reason}")
                calls.append(
                    CallRecord(
                        provider=self._provider.name,
                        model=model,
                        outcome="skipped",
                        fallback_used=index > 0,
                        detail=verdict.reason,
                    )
                )
                return None

        attempt = 0
        while True:
            try:
                result = await self._provider.complete_json(
                    schema=schema,
                    system=system,
                    messages=messages,
                    model=model,
                    reasoning_effort=self._effort,
                )
            except RateLimitedError as exc:
                calls.append(self._failure(model, exc, index))
                wait = exc.retry_after
                if exc.exhausted or (wait is not None and wait > self._max_wait):
                    self._quota.block(model, wait or DEFAULT_REST_SECONDS, "rate limited")
                    reasons.append(f"{model}: rate limited for {_describe(wait)}")
                    return None
                if attempt >= self._retries:
                    reasons.append(f"{model}: still rate limited after {attempt + 1} attempts")
                    return None
                await self._sleep(wait if wait is not None else _backoff(attempt))
                attempt += 1
                continue
            except ProviderUnavailableError as exc:
                calls.append(self._failure(model, exc, index))
                if attempt >= self._retries:
                    reasons.append(f"{model}: unavailable after {attempt + 1} attempts")
                    return None
                await self._sleep(_backoff(attempt))
                attempt += 1
                continue
            except ProviderError as exc:
                # Invalid answers, rejections and replay misses: not worth a second identical call.
                calls.append(self._failure(model, exc, index))
                reasons.append(f"{model}: {exc.outcome}")
                return None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A bug in a provider must not become an error page; the rule parser can still
                # answer. Logged with its traceback so the bug is not hidden either.
                logger.exception("llm_provider_crashed", model=model)
                calls.append(
                    CallRecord(
                        provider=self._provider.name,
                        model=model,
                        outcome="error",
                        fallback_used=index > 0,
                        detail=type(exc).__name__,
                    )
                )
                reasons.append(f"{model}: {type(exc).__name__}")
                return None

            self._quota.record(
                model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
            self._quota.observe(model, result.rate_limit)
            calls.append(
                CallRecord(
                    provider=result.provider,
                    model=result.model,
                    outcome="ok",
                    latency_ms=result.latency_ms,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    fallback_used=index > 0,
                )
            )
            return _Answer(data=result.data, provider=result.provider, model=result.model)

    def _failure(self, model: str, exc: ProviderError, index: int) -> CallRecord:
        return CallRecord(
            provider=self._provider.name,
            model=model,
            outcome=exc.outcome,
            latency_ms=exc.latency_ms,
            fallback_used=index > 0,
            detail=str(exc)[:200],
        )


@dataclass(frozen=True)
class _Answer:
    data: dict[str, Any]
    provider: str
    model: str


def _backoff(attempt: int) -> float:
    """Exponential with jitter, so concurrent requests do not retry in lockstep."""
    return float(BASE_BACKOFF * (2.0**attempt) * (0.75 + random.random() * 0.5))  # noqa: S311


def _describe(seconds: float | None) -> str:
    if seconds is None:
        return "an unknown time"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} h"
    if seconds >= 60:
        return f"{seconds / 60:.0f} min"
    return f"{seconds:.0f} s"
