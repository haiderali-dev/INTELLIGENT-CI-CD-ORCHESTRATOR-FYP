"""The response cache.

BUILD_PROMPT 4.5.1: "Identical normalized commands within 10 minutes are served from a cache."

What "identical" has to mean is the design decision here. The command text alone is not enough:

* the same words from a Developer and an Admin can parse differently, because the role is in the
  prompt;
* the same words after a catalog change must not return an answer built against the old enums --
  a newly added service would be unreachable for ten minutes;
* the same words with different conversation history can mean different things ("the same again");
* the same words under a new prompt version must not replay the old prompt's answer.

So the key is the normalised text *plus* the role, a fingerprint of the catalog, the prompt version
and the normalised history. That keeps the cache correct while still catching what it is for:
someone pressing enter twice, the demo repeating a command, an eval rerun.

Only model answers are cached. A rule-parser fallback is not: if Groq was briefly unreachable,
caching the weaker answer would pin it for ten minutes after the model came back.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

TTL_SECONDS: Final = 600.0

# Bounded so a burst of distinct commands cannot grow memory without limit; least recently used
# entries go first.
CAPACITY: Final = 1000

_WHITESPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Case and whitespace folded, nothing else.

    Punctuation is kept on purpose: "deploy to staging" and "deploy to staging?" are near enough to
    share an answer, but stripping punctuation would also fold "feature/refund" into something
    else, and branch names are exactly where a wrong match would hurt.
    """
    return _WHITESPACE.sub(" ", text).strip().casefold()


def cache_key(
    *,
    text: str,
    role: str,
    catalog_fingerprint: str,
    prompt_version: str,
    history: list[str] | None = None,
    model_chain: tuple[str, ...] = (),
) -> str:
    material = json.dumps(
        {
            "text": normalise(text),
            "role": role,
            "catalog": catalog_fingerprint,
            "prompt": prompt_version,
            "history": [normalise(item) for item in (history or [])],
            "chain": list(model_chain),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CachedAnswer:
    data: dict[str, Any]
    provider: str
    model: str
    ai_fallback: bool
    stored_at: float


class ResponseCache:
    """A thread-safe LRU with a time-to-live."""

    def __init__(
        self,
        *,
        ttl_seconds: float = TTL_SECONDS,
        capacity: int = CAPACITY,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._capacity = capacity
        self._clock = clock
        self._entries: OrderedDict[str, CachedAnswer] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> CachedAnswer | None:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            if now - entry.stored_at >= self._ttl:
                del self._entries[key]
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return entry

    def put(
        self, key: str, *, data: dict[str, Any], provider: str, model: str, ai_fallback: bool
    ) -> None:
        with self._lock:
            self._entries[key] = CachedAnswer(
                data=dict(data),
                provider=provider,
                model=model,
                ai_fallback=ai_fallback,
                stored_at=self._clock(),
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = 0
            self.misses = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_cache = ResponseCache()


def get_response_cache() -> ResponseCache:
    return _cache
