"""Versioned prompts: loading, versioning and rendering.

BUILD_PROMPT 4.5.6: "Versioned markdown in ``backend/app/ai/prompts/``, with the version stored on
every call."

The version is the file's name plus the first eight hex digits of its SHA-256, for example
``intent_v1@3fa2c9d1``. The name alone would not do: an edit to ``intent_v1.md`` made without
renaming it would produce answers recorded under the same version as before, and the evaluation
could not tell the two prompts apart. The hash makes every distinct prompt a distinct version.

Rendering substitutes ``{{catalog}}``, ``{{role}}`` and ``{{history}}`` in a single pass. The
history is the user's own text, so it is an injection surface twice over: as instructions to the
model (handled by the prompt's rules and by delimiting it as data), and as template syntax. A
single pass means a history line containing ``{{role}}`` is inserted literally and never expanded.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final

from app.ai.providers.base import ChatMessage

PROMPTS_DIR: Final = Path(__file__).resolve().parent / "prompts"

EXAMPLES_HEADING: Final = "## Examples"

# How much conversation reaches the prompt. Every token is paid on every call against an 8,000
# token-a-minute budget, and older turns rarely change what the newest message means.
HISTORY_TURNS: Final = 6
HISTORY_CHARS_PER_TURN: Final = 300

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.S)
_EXAMPLE = re.compile(
    r"^### (?P<title>.+?)\n+User: (?P<user>.+?)\n+Intent: (?P<intent>\{.*?\})\s*$",
    re.M | re.S,
)


class PromptError(RuntimeError):
    """A prompt file is malformed, or rendering was given the wrong values."""


@dataclass(frozen=True)
class FewShot:
    title: str
    user: str
    intent: dict[str, Any]


@dataclass(frozen=True)
class RenderedPrompt:
    """What goes to the provider: a system prompt and the few-shot turns before the user's."""

    system: str
    examples: tuple[ChatMessage, ...]
    version: str

    def messages_for(self, text: str) -> list[ChatMessage]:
        """The few-shot turns followed by the user's actual message."""
        return [*self.examples, ChatMessage(role="user", content=text)]


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: str
    system_template: str
    examples: tuple[FewShot, ...]

    @property
    def placeholders(self) -> frozenset[str]:
        return frozenset(_PLACEHOLDER.findall(self.system_template))

    def render(
        self,
        *,
        catalog: str,
        role: str,
        history: list[tuple[str, str]] | None = None,
        include_examples: bool = True,
    ) -> RenderedPrompt:
        """Fill the placeholders and build the few-shot turns.

        ``include_examples=False`` is 4.9's "no few-shot examples" ablation.
        """
        values = {"catalog": catalog, "role": role, "history": render_history(history)}

        missing = self.placeholders - values.keys()
        if missing:
            raise PromptError(f"{self.name} uses placeholders with no value: {sorted(missing)}")

        # One pass, through a function: the substituted text is never scanned again, so template
        # syntax inside a user's history stays literal.
        system = _PLACEHOLDER.sub(lambda match: values[match.group(1)], self.system_template)

        turns: list[ChatMessage] = []
        if include_examples:
            for example in self.examples:
                turns.append(ChatMessage(role="user", content=example.user))
                turns.append(
                    ChatMessage(
                        role="assistant",
                        content=json.dumps(example.intent, separators=(",", ":")),
                    )
                )
        return RenderedPrompt(system=system, examples=tuple(turns), version=self.version)


def render_history(history: list[tuple[str, str]] | None) -> str:
    """Recent turns as a delimited, bounded block of data.

    Each turn is flattened to one line and truncated, and the block is fenced so the model sees
    where the user's own words start and stop. The prompt's rule that quoted text is data then has
    a clear boundary to apply to.
    """
    if not history:
        return "(none)"
    lines = []
    for role, content in history[-HISTORY_TURNS:]:
        flattened = " ".join(content.split())
        if len(flattened) > HISTORY_CHARS_PER_TURN:
            flattened = flattened[: HISTORY_CHARS_PER_TURN - 1] + "…"
        speaker = "assistant" if role == "assistant" else "user"
        lines.append(f"{speaker}: {flattened}")
    return "<history>\n" + "\n".join(lines) + "\n</history>"


def parse_prompt(name: str, text: str) -> PromptTemplate:
    """Split a prompt file into its system template and its examples."""
    version = f"{name}@{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]}"
    body = _COMMENT.sub("", text, count=1)

    system_part, heading, examples_part = body.partition(EXAMPLES_HEADING)
    system = system_part.strip()
    if not system:
        raise PromptError(f"{name} has no system prompt")

    examples: list[FewShot] = []
    if heading:
        for match in _EXAMPLE.finditer(examples_part):
            raw = match.group("intent")
            try:
                intent = json.loads(raw)
            except ValueError as exc:
                raise PromptError(
                    f"{name}: example {match.group('title')!r} is not valid JSON"
                ) from exc
            examples.append(
                FewShot(
                    title=match.group("title").strip(),
                    user=match.group("user").strip(),
                    intent=intent,
                )
            )
        declared = examples_part.count("\n### ")
        if declared != len(examples):
            # A malformed example would otherwise be dropped silently, and the prompt would carry
            # one fewer example than its author believes.
            raise PromptError(
                f"{name}: {declared} example headings but {len(examples)} parsed; check the format"
            )

    return PromptTemplate(
        name=name, version=version, system_template=system, examples=tuple(examples)
    )


@cache
def load_prompt(name: str = "intent_v1") -> PromptTemplate:
    """Load a prompt by name, once per process."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise PromptError(f"no prompt named {name!r} in {PROMPTS_DIR}")
    return parse_prompt(name, path.read_text(encoding="utf-8"))
