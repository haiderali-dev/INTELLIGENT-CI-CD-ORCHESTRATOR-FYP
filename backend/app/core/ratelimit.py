"""In-process rate limiting.

BUILD_PROMPT 4.4.4 requires rate limits on the auth endpoints. This is a token bucket rather than a
fixed window: a fixed window lets a caller spend its whole allowance at the end of one window and
again at the start of the next, so a "5 per minute" limit permits 10 attempts in two seconds across
the boundary. For a login endpoint that is most of the protection gone.

Deliberately in-process. The project runs one backend container (docker-compose.yml), so a shared
store would add Redis for no benefit the experiment measures -- and the report's Appendix E lists
Redis as a dependency the version 2 stack does not have. The limitation is real and recorded: with
more than one backend instance each would keep its own buckets and the effective limit would
multiply. See docs/decisions.md D-020.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.core.errors import ApiError, ErrorCode


@dataclass
class _Bucket:
    """A token bucket. Tokens refill continuously at ``rate`` per second."""

    tokens: float
    updated_at: float
    # When this bucket last handed out a refusal to be recorded (``RateLimitedError.record``).
    reported_at: float | None = None


@dataclass
class RateLimit:
    """A named limit: ``capacity`` requests, refilling over ``per_seconds``."""

    name: str
    capacity: int
    per_seconds: float

    @property
    def refill_per_second(self) -> float:
        return self.capacity / self.per_seconds


# Sign-in is the endpoint worth protecting hardest: it is the only one that turns a guess into
# access. Five attempts a minute per account from one address is generous for a human and useless
# for guessing one password. It is keyed by address and account, because keyed by address alone
# five wrong passwords from anyone behind a shared proxy locked everyone out (independent security
# review, finding 7). LOGIN_ADDRESS_LIMIT then caps an address across all accounts, which is what
# stops a password spray.
LOGIN_LIMIT = RateLimit(name="login", capacity=5, per_seconds=60.0)
LOGIN_ADDRESS_LIMIT = RateLimit(name="login-address", capacity=30, per_seconds=60.0)

# Refresh is called automatically by the frontend whenever an access token expires, so its limit
# has to accommodate several browser tabs without letting a stolen refresh token be farmed.
REFRESH_LIMIT = RateLimit(name="refresh", capacity=30, per_seconds=60.0)

# A general ceiling for authenticated traffic, high enough that normal use never reaches it.
API_LIMIT = RateLimit(name="api", capacity=300, per_seconds=60.0)

# Assistant messages and generation call the model. Groq allows 30 requests a minute per model
# (4.5.1), shared by everyone, so one client sending faster than one message every three seconds
# is draining the whole team's quota rather than chatting.
ASSISTANT_LIMIT = RateLimit(name="assistant", capacity=20, per_seconds=60.0)

# Every limit, with what it is counted against, as the Admin page shows them (4.7.3).
RATE_LIMITS: tuple[tuple[RateLimit, str], ...] = (
    (LOGIN_LIMIT, "sign-in, per address and account"),
    (LOGIN_ADDRESS_LIMIT, "sign-in, per address across accounts"),
    (REFRESH_LIMIT, "session renewal, per address"),
    (API_LIMIT, "every signed-in request, per user"),
    (ASSISTANT_LIMIT, "assistant messages, generation and explanations, per user"),
)


class RateLimitedError(ApiError):
    """A request refused by a limit: 429, with how long to wait.

    ``record`` is true for at most one refusal per caller per limit window, the one worth writing
    to the audit log (D-068). Recording every refusal would let a caller who keeps hammering a
    limit fill the log one row per request; one a window still shows that the limit engaged, for
    whom, and that it kept engaging.
    """

    def __init__(self, limit: RateLimit, retry_after: int, *, record: bool) -> None:
        super().__init__(
            ErrorCode.RATE_LIMITED,
            f"Too many attempts. Try again in {retry_after} second"
            f"{'s' if retry_after != 1 else ''}.",
            status_code=429,
            details={"retry_after_seconds": retry_after, "limit": limit.name},
        )
        self.limit = limit
        self.record = record


class RateLimiter:
    """Thread-safe token buckets keyed by (limit name, identifier)."""

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def check(self, limit: RateLimit, identifier: str) -> None:
        """Consume one token, or raise.

        Raises ``RateLimitedError``, a 429 with a ``retry_after_seconds`` detail so the UI can say
        when to try again rather than only that something went wrong.
        """
        refused = self._consume(limit, identifier)
        if refused is None:
            return
        retry_after, record = refused
        raise RateLimitedError(limit, retry_after, record=record)

    def _consume(self, limit: RateLimit, identifier: str) -> tuple[int, bool] | None:
        """Take a token. Returns None on success, or the seconds to wait and whether this refusal
        is the one of its window to record."""
        now = time.monotonic()
        key = (limit.name, identifier)

        with self._lock:
            self._sweep(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                # A new caller starts full, minus the request being made now.
                self._buckets[key] = _Bucket(tokens=limit.capacity - 1.0, updated_at=now)
                return None

            elapsed = now - bucket.updated_at
            bucket.tokens = min(limit.capacity, bucket.tokens + elapsed * limit.refill_per_second)
            bucket.updated_at = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return None

            # Round up: telling someone to retry in 0 seconds when they cannot is worse than
            # telling them 1.
            deficit = 1.0 - bucket.tokens
            retry_after = max(1, int(deficit / limit.refill_per_second) + 1)
            record = bucket.reported_at is None or now - bucket.reported_at >= limit.per_seconds
            if record:
                bucket.reported_at = now
            return retry_after, record

    def _sweep(self, now: float) -> None:
        """Drop buckets that have fully refilled, so the map cannot grow without bound.

        Without this, every distinct client IP that ever signed in would occupy memory forever,
        which is a slow leak that only shows up in a long-running deployment.
        """
        if now - self._last_sweep < 60.0:
            return
        self._last_sweep = now
        stale = [
            key
            for key, bucket in self._buckets.items()
            # Ten minutes idle is far longer than any configured window, so the bucket is certainly
            # full again and holds no information.
            if now - bucket.updated_at > 600.0
        ]
        for key in stale:
            del self._buckets[key]

    def reset(self) -> None:
        """Forget every bucket. For tests."""
        with self._lock:
            self._buckets.clear()


_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    """The process-wide limiter, as a dependency so tests can reset it."""
    return _limiter
