"""``ReplayProvider`` and ``RecordingProvider``: recorded answers, served by prompt hash.

BUILD_PROMPT 4.5.1: "``ReplayProvider`` serves recorded fixtures by prompt hash." T5.8 relies on it:
the end-to-end tests run "using replay fixtures when no Groq key is set", so a fixture recorded once
against the real model lets every later run reproduce that exact answer with no key and no quota.

The hash covers the model, the system prompt, the messages and the schema -- everything that can
change the answer. Change any of them (a prompt edit, a new catalog service that alters the enum)
and the old fixture no longer matches. That is intended: a fixture that kept matching after the
prompt changed would replay an answer the current prompt might never produce. A miss raises
``ReplayMissError``, and the chain falls back to the rule parser with ``ai_fallback`` set, so a
stale fixture set shows up as fallbacks rather than as silently wrong answers.

File reads and writes run through ``asyncio.to_thread``. These methods execute inside request
handling, and a synchronous read would stall every other request on the event loop for as long as
the disk takes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ai.providers.base import (
    ChatMessage,
    LLMProvider,
    ParsedResult,
    ReplayMissError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


def prompt_hash(
    *, model: str, system: str, messages: list[ChatMessage], schema: dict[str, Any]
) -> str:
    """A stable hash of everything that determines an answer.

    ``sort_keys`` so that two semantically identical schemas built in a different key order hash
    the same; the schema builder does not promise an order.
    """
    canonical = json.dumps(
        {
            "model": model,
            "system": system,
            "messages": [message.as_dict() for message in messages],
            "schema": schema,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _FailingStream:
    """An async iterator that raises on first use.

    Lets ``stream_text`` refuse without being written as a generator whose only ``yield`` sits
    after a ``raise`` -- which is dead code the type checker rightly reports.
    """

    def __init__(self, error: Exception) -> None:
        self._error = error

    def __aiter__(self) -> _FailingStream:
        return self

    async def __anext__(self) -> str:
        raise self._error


class _Unreadable:
    """Marks "a fixture file exists but cannot be used", as distinct from "there is no file"."""


_UNREADABLE = _Unreadable()


def read_fixture(path: Path) -> dict[str, Any] | _Unreadable | None:
    """Load a fixture. None when there is none. Synchronous; call it via ``to_thread``."""
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _UNREADABLE
    return loaded if isinstance(loaded, dict) else _UNREADABLE


def write_fixture(path: Path, payload: dict[str, Any]) -> None:
    """Write a fixture. Synchronous; call it via ``to_thread``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class ReplayProvider(LLMProvider):
    """Answers only from fixtures on disk."""

    name = "replay"

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    @property
    def directory(self) -> Path:
        return self._directory

    def fixture_path(self, digest: str) -> Path:
        # Two-character fan-out keeps any one directory small once the eval has recorded hundreds.
        return self._directory / digest[:2] / f"{digest}.json"

    async def complete_json(
        self,
        *,
        schema: dict[str, Any],
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> ParsedResult:
        digest = prompt_hash(model=model, system=system, messages=messages, schema=schema)
        fixture = await asyncio.to_thread(read_fixture, self.fixture_path(digest))
        if fixture is None:
            raise ReplayMissError(f"{model}: no fixture for prompt {digest[:12]}")
        if isinstance(fixture, _Unreadable):
            raise ReplayMissError(f"{model}: fixture {digest[:12]} is unreadable")

        data = fixture.get("data")
        if not isinstance(data, dict):
            raise ReplayMissError(f"{model}: fixture {digest[:12]} has no data object")

        return ParsedResult(
            data=data,
            provider=self.name,
            model=str(fixture.get("model", model)),
            prompt_tokens=int(fixture.get("prompt_tokens", 0)),
            completion_tokens=int(fixture.get("completion_tokens", 0)),
            latency_ms=0,
        )

    def stream_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> AsyncIterator[str]:
        # Streams are not recorded: an explanation is prose for a person, and replaying one would
        # only test that a file can be read.
        return _FailingStream(ReplayMissError(f"{model}: streamed text is not replayable"))


class RecordingProvider(LLMProvider):
    """Calls a real provider and saves each answer as a replay fixture.

    Used to build the fixture set T5.8 replays. Only successful answers are saved: recording a
    failure would make the replay fail the same way forever.
    """

    def __init__(self, inner: LLMProvider, directory: Path) -> None:
        self._inner = inner
        self._replay = ReplayProvider(directory)
        self.name = inner.name

    async def complete_json(
        self,
        *,
        schema: dict[str, Any],
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> ParsedResult:
        result = await self._inner.complete_json(
            schema=schema,
            system=system,
            messages=messages,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        digest = prompt_hash(model=model, system=system, messages=messages, schema=schema)
        await asyncio.to_thread(
            write_fixture,
            self._replay.fixture_path(digest),
            {
                "prompt_hash": digest,
                "model": result.model,
                "data": result.data,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "recorded_at": datetime.now(UTC).isoformat(),
            },
        )
        logger.info("llm_fixture_recorded", model=model, prompt_hash=digest[:12])
        return result

    def stream_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> AsyncIterator[str]:
        return self._inner.stream_text(
            system=system, messages=messages, model=model, reasoning_effort=reasoning_effort
        )

    async def aclose(self) -> None:
        await self._inner.aclose()
