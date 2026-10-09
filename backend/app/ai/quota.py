"""Per-model quota accounting.

BUILD_PROMPT 4.5.1: free-tier limits for ``openai/gpt-oss-120b`` are 30 requests a minute, 1,000 a
day, 8,000 tokens a minute and 200,000 tokens a day, counted per model. "Keep a daily counter per
model, and when a model is exhausted move down the chain."

Two sources of truth, deliberately combined:

* **Local counters** are what 4.5.1 asks for, and they work before the first response has arrived.
  But they only see this process: a restart forgets them, and the eval harness running alongside
  the backend spends the same quota without this process knowing.
* **The server's headers** are authoritative. Every Groq response carries
  ``x-ratelimit-remaining-requests`` and friends (confirmed live on 2026-10-09: ``limit-requests``
  1000 and ``limit-tokens`` 8000, matching 4.5.1). When the server says zero requests remain, that
  overrides whatever the local count believes.

Exhaustion is a time, not a flag. A model marked exhausted becomes available again when its reset
time passes, so a long-running backend recovers on its own the next day instead of falling back to
rules forever.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from app.ai.providers.groq import parse_duration


@dataclass(frozen=True)
class ModelLimits:
    requests_per_minute: int
    requests_per_day: int
    tokens_per_minute: int
    tokens_per_day: int


# 4.5.1's figures for gpt-oss-120b. Used for every model until that model's own headers arrive:
# the specification gives no numbers for the others, and assuming the 120b limits is the
# conservative choice -- the server corrects them on the first response anyway.
DEFAULT_LIMITS: Final = ModelLimits(
    requests_per_minute=30,
    requests_per_day=1000,
    tokens_per_minute=8000,
    tokens_per_day=200_000,
)

# Below this many tokens left in the minute, the next call is likely to be refused. One intent
# call with the full prompt and few-shot examples is roughly this size.
TOKEN_HEADROOM: Final = 1500


@dataclass(frozen=True)
class QuotaVerdict:
    """Whether a model may be called now, and if not, for how long it should rest."""

    allowed: bool
    wait_seconds: float = 0.0
    reason: str = ""


@dataclass
class _ModelUsage:
    day: str = ""
    requests_today: int = 0
    tokens_today: int = 0
    minute: deque[tuple[float, int]] = field(default_factory=deque)
    blocked_until: float = 0.0
    blocked_reason: str = ""
    server_remaining_requests: int | None = None
    server_remaining_tokens: int | None = None


class QuotaTracker:
    """Thread-safe per-model counters plus the server's own view."""

    def __init__(
        self,
        limits: dict[str, ModelLimits] | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._limits = dict(limits or {})
        self._clock = clock
        self._usage: dict[str, _ModelUsage] = {}
        self._lock = threading.Lock()

    def limits_for(self, model: str) -> ModelLimits:
        return self._limits.get(model, DEFAULT_LIMITS)

    def _state(self, model: str, now: float) -> _ModelUsage:
        usage = self._usage.setdefault(model, _ModelUsage())
        today = datetime.fromtimestamp(now, tz=UTC).date().isoformat()
        if usage.day != today:
            # A new UTC day resets the local daily counters. The server's own view is left alone:
            # Groq's daily bucket refills continuously rather than at midnight, so its headers stay
            # the better guide across the boundary.
            usage.day = today
            usage.requests_today = 0
            usage.tokens_today = 0
        while usage.minute and now - usage.minute[0][0] >= 60.0:
            usage.minute.popleft()
        return usage

    def check(self, model: str) -> QuotaVerdict:
        """May ``model`` be called right now?"""
        now = self._clock()
        with self._lock:
            usage = self._state(model, now)
            limits = self.limits_for(model)

            if usage.blocked_until > now:
                return QuotaVerdict(
                    allowed=False,
                    wait_seconds=usage.blocked_until - now,
                    reason=usage.blocked_reason or "rate limited",
                )

            if usage.requests_today >= limits.requests_per_day:
                return QuotaVerdict(
                    allowed=False,
                    wait_seconds=_seconds_to_midnight(now),
                    reason=f"daily request limit of {limits.requests_per_day} reached",
                )
            if usage.tokens_today >= limits.tokens_per_day:
                return QuotaVerdict(
                    allowed=False,
                    wait_seconds=_seconds_to_midnight(now),
                    reason=f"daily token limit of {limits.tokens_per_day} reached",
                )

            if len(usage.minute) >= limits.requests_per_minute:
                oldest = usage.minute[0][0]
                return QuotaVerdict(
                    allowed=False,
                    wait_seconds=max(0.0, 60.0 - (now - oldest)),
                    reason=f"{limits.requests_per_minute} requests a minute reached",
                )
            minute_tokens = sum(tokens for _, tokens in usage.minute)
            if minute_tokens + TOKEN_HEADROOM > limits.tokens_per_minute and usage.minute:
                oldest = usage.minute[0][0]
                return QuotaVerdict(
                    allowed=False,
                    wait_seconds=max(0.0, 60.0 - (now - oldest)),
                    reason=f"{limits.tokens_per_minute} tokens a minute nearly reached",
                )

            if usage.server_remaining_requests == 0:
                return QuotaVerdict(
                    allowed=False,
                    wait_seconds=max(0.0, usage.blocked_until - now),
                    reason="the server reports no requests remaining today",
                )
            return QuotaVerdict(allowed=True)

    def record(self, model: str, *, prompt_tokens: int, completion_tokens: int) -> None:
        """Count one completed call."""
        now = self._clock()
        tokens = max(0, prompt_tokens) + max(0, completion_tokens)
        with self._lock:
            usage = self._state(model, now)
            usage.requests_today += 1
            usage.tokens_today += tokens
            usage.minute.append((now, tokens))

    def observe(self, model: str, headers: dict[str, str]) -> None:
        """Take the server's word for what remains."""
        if not headers:
            return
        now = self._clock()
        with self._lock:
            usage = self._state(model, now)

            limit_requests = _int(headers.get("x-ratelimit-limit-requests"))
            limit_tokens = _int(headers.get("x-ratelimit-limit-tokens"))
            if limit_requests is not None or limit_tokens is not None:
                current = self.limits_for(model)
                self._limits[model] = ModelLimits(
                    requests_per_minute=current.requests_per_minute,
                    requests_per_day=limit_requests or current.requests_per_day,
                    tokens_per_minute=limit_tokens or current.tokens_per_minute,
                    tokens_per_day=current.tokens_per_day,
                )

            usage.server_remaining_requests = _int(headers.get("x-ratelimit-remaining-requests"))
            usage.server_remaining_tokens = _int(headers.get("x-ratelimit-remaining-tokens"))

            if usage.server_remaining_requests == 0:
                reset = parse_duration(headers.get("x-ratelimit-reset-requests")) or 3600.0
                usage.blocked_until = max(usage.blocked_until, now + reset)
                usage.blocked_reason = "the server reports no requests remaining"

    def block(self, model: str, seconds: float, reason: str) -> None:
        """Rest a model for ``seconds``, after a 429 or an exhausted quota."""
        now = self._clock()
        with self._lock:
            usage = self._state(model, now)
            usage.blocked_until = max(usage.blocked_until, now + max(0.0, seconds))
            usage.blocked_reason = reason

    def snapshot(self) -> dict[str, dict[str, object]]:
        """Per-model usage, for the health endpoint and the eval's quota guard."""
        now = self._clock()
        with self._lock:
            out: dict[str, dict[str, object]] = {}
            for model, usage in self._usage.items():
                self._state(model, now)
                out[model] = {
                    "requests_today": usage.requests_today,
                    "tokens_today": usage.tokens_today,
                    "requests_last_minute": len(usage.minute),
                    "server_remaining_requests": usage.server_remaining_requests,
                    "server_remaining_tokens": usage.server_remaining_tokens,
                    "blocked_seconds": max(0.0, round(usage.blocked_until - now, 1)),
                }
            return out

    def reset(self) -> None:
        with self._lock:
            self._usage.clear()


def _int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _seconds_to_midnight(now: float) -> float:
    moment = datetime.fromtimestamp(now, tz=UTC)
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return 86400.0 - (moment - midnight).total_seconds()


_tracker = QuotaTracker()


def get_quota_tracker() -> QuotaTracker:
    return _tracker
