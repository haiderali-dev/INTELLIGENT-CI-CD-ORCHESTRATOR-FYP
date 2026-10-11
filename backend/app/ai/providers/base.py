"""The provider interface.

BUILD_PROMPT 4.5.1: ``LLMProvider`` exposes ``complete_json(schema, system, messages, model,
reasoning_effort) -> ParsedResult`` and ``stream_text(...)``.

The error types are the important part of this module. ``ModelChain`` decides what to do next
purely from which one it caught -- wait and retry the same model, move to the next model now, or
give up on models entirely -- so each type stands for one decision, not one HTTP status.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "user" | "assistant"
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ParsedResult:
    """One successful structured completion."""

    data: dict[str, Any]
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    # The server's own view of remaining quota, when it sends one. Authoritative over local
    # counting, which can only see this process's calls.
    rate_limit: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Errors: one per decision the chain has to make
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """A call failed. Base class; the subclass says what to do about it."""

    #: Whether the same model is worth calling again shortly.
    retryable: bool = False
    #: The ``llm_calls.outcome`` this failure is recorded as.
    outcome: str = "error"

    def __init__(self, message: str, *, latency_ms: int = 0) -> None:
        super().__init__(message)
        self.latency_ms = latency_ms


class RateLimitedError(ProviderError):
    """429. Retry after ``retry_after`` seconds -- or, if that is long, move on.

    ``exhausted`` marks a daily limit rather than a per-minute one. The difference decides
    whether waiting is reasonable inside a user's request: seconds yes, hours no.
    """

    retryable = True
    outcome = "rate_limited"

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        exhausted: bool = False,
        latency_ms: int = 0,
    ) -> None:
        super().__init__(message, latency_ms=latency_ms)
        self.retry_after = retry_after
        self.exhausted = exhausted


class ProviderUnavailableError(ProviderError):
    """5xx, a timeout, or no connection. Worth retrying the same model."""

    retryable = True
    outcome = "unavailable"


class InvalidResponseError(ProviderError):
    """The call succeeded but the answer is unusable: not JSON, truncated, or refused.

    Not retried on the same model. With temperature 0 the same prompt tends to produce the same
    unusable answer, so the retry budget is better spent on the next model.
    """

    outcome = "invalid"


class ProviderRejectedError(ProviderError):
    """4xx other than 429: bad credentials, a bad request. Retrying will fail the same way."""

    outcome = "rejected"


class ReplayMissError(ProviderError):
    """``ReplayProvider`` has no fixture for this prompt."""

    outcome = "replay_miss"


# ---------------------------------------------------------------------------
# The interface
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Something that can turn a prompt into a schema-shaped JSON object."""

    #: Recorded in ``llm_calls.provider``.
    name: str = "provider"

    @abstractmethod
    async def complete_json(
        self,
        *,
        schema: dict[str, Any],
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> ParsedResult:
        """Return an object that satisfies ``schema``, or raise a ``ProviderError``."""

    @abstractmethod
    def stream_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> AsyncIterator[str]:
        """Yield text as it is produced. Used for the streamed explanation in Phase 5."""

    async def aclose(self) -> None:
        return None
