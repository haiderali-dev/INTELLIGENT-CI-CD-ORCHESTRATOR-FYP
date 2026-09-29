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
# access. Five attempts a minute is generous for a human and useless for a password spray.
LOGIN_LIMIT = RateLimit(name="login", capacity=5, per_seconds=60.0)

# Refresh is called automatically by the frontend whenever an access token expires, so its limit
# has to accommodate several browser tabs without letting a stolen refresh token be farmed.
REFRESH_LIMIT = RateLimit(name="refresh", capacity=30, per_seconds=60.0)

# A general ceiling for authenticated traffic, high enough that normal use never reaches it.
API_LIMIT = RateLimit(name="api", capacity=300, per_seconds=60.0)


class RateLimiter:
    """Thread-safe token buckets keyed by (limit name, identifier)."""

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def check(self, limit: RateLimit, identifier: str) -> None:
        """Consume one token, or raise.

        Raises ``ApiError`` with 429 and a ``retry_after_seconds`` detail so the UI can say when to
        try again rather than only that something went wrong.
        """
        retry_after = self._consume(limit, identifier)
        if retry_after is None:
            return
        raise ApiError(
            ErrorCode.RATE_LIMITED,
            f"Too many attempts. Try again in {retry_after} second"
            f"{'s' if retry_after != 1 else ''}.",
            status_code=429,
            details={"retry_after_seconds": retry_after, "limit": limit.name},
        )

    def _consume(self, limit: RateLimit, identifier: str) -> int | None:
        """Take a token. Returns None on success, or the seconds to wait."""
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
            return max(1, int(deficit / limit.refill_per_second) + 1)

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
