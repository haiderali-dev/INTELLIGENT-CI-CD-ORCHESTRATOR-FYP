"""``FakeProvider``: deterministic answers for tests.

BUILD_PROMPT 4.5.1: "``FakeProvider`` returns deterministic answers for tests."

Two ways to drive it. A script -- a list of answers and exceptions consumed in order -- is what a
test about the *chain* wants: "the first model is rate limited, the second answers". A responder
function is what ``LLM_MODE=fake`` wants for the whole demo: a sensible answer to any message with
no network and no key. The factory wires the rule parser in as that responder, so a fake-mode demo
behaves plausibly without pretending to be a model in the evaluation (the eval never uses fake).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from app.ai.providers.base import ChatMessage, LLMProvider, ParsedResult, ProviderError

Responder = Callable[[str, list[ChatMessage], dict[str, Any], str], dict[str, Any]]


def _unsupported(
    system: str, messages: list[ChatMessage], schema: dict[str, Any], model: str
) -> dict[str, Any]:
    return {
        "action": "UNSUPPORTED",
        "service": None,
        "branch": None,
        "commit": None,
        "environment": None,
        "test_suite": None,
        "urgency": None,
        "extra_stages": [],
        "justification": None,
        "confidence": 0.0,
    }


@dataclass
class FakeCall:
    model: str
    system: str
    messages: list[ChatMessage]
    schema: dict[str, Any]


@dataclass
class FakeProvider(LLMProvider):
    """Scripted or computed answers, and a record of every call made."""

    script: list[dict[str, Any] | ProviderError] = field(default_factory=list)
    responder: Responder = _unsupported
    # Per-model scripts take precedence, for chain tests that need model A to fail and B to answer.
    per_model: dict[str, list[dict[str, Any] | ProviderError]] = field(default_factory=dict)
    prompt_tokens: int = 100
    completion_tokens: int = 20
    calls: list[FakeCall] = field(default_factory=list)
    name: str = "fake"

    async def complete_json(
        self,
        *,
        schema: dict[str, Any],
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> ParsedResult:
        self.calls.append(
            FakeCall(model=model, system=system, messages=list(messages), schema=schema)
        )

        queue = self.per_model.get(model)
        if queue:
            step = queue.pop(0)
        elif self.script:
            step = self.script.pop(0)
        else:
            step = self.responder(system, messages, schema, model)

        if isinstance(step, ProviderError):
            raise step
        return ParsedResult(
            data=dict(step),
            provider=self.name,
            model=model,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            latency_ms=1,
        )

    async def stream_text(
        self,
        *,
        system: str,
        messages: list[ChatMessage],
        model: str,
        reasoning_effort: str = "low",
    ) -> AsyncIterator[str]:
        for word in ("This", " is", " a", " fake", " explanation."):
            yield word

    def calls_to(self, model: str) -> int:
        return sum(1 for call in self.calls if call.model == model)
