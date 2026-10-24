"""The evaluation dataset: loading and checking JSONL items.

BUILD_PROMPT 4.9: each line has ``id``, ``text``, ``category``, ``role``, ``gold_intent``,
``gold_behavior`` (GENERATE, CLARIFY, REFUSE), ``notes``, ``labeled_by`` and ``needs_review``.

``needs_review`` is enforced here, not trusted to the caller: "Claude Code may draft at most 30
items, each marked ``needs_review: true``; they are excluded from scoring until a human clears the
flag." An item drafted by Claude Code that claims to be reviewed is rejected outright, because a
gold label nobody checked would be passed off as ground truth in the report.

``split`` (dev or test) is not in 4.9's field list but 4.9 requires the split itself -- 100
development, 150 test -- and Appendix E restricts prompt tuning to the development split, which is
only enforceable if each item says which it is in.

**Machine-labelled datasets (D-081).** ``eval-v1`` was written and labelled by Claude Code at the
project owner's instruction, because no person was available to label it. Its items say
``labeled_by: claude-code`` and, like drafts, can never claim a review. They are allowed only in a
dataset whose card (``<name>.card.json``) declares machine labels and whose checksum matches the
file, so they cannot be slipped into a human-labelled set, and an edit that bypasses the builder is
refused. The 30-draft cap still applies to drafts.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

BEHAVIORS: Final = ("GENERATE", "CLARIFY", "REFUSE")
CATEGORIES: Final = (
    "clear",
    "paraphrase_typos",
    "missing_field",
    "ambiguous",
    "unsafe_out_of_scope",
    "prompt_injection",
)
# 4.9's target mix, used to warn when a dataset drifts from it.
TARGET_MIX: Final = {
    "clear": 0.40,
    "paraphrase_typos": 0.20,
    "missing_field": 0.15,
    "ambiguous": 0.10,
    "unsafe_out_of_scope": 0.10,
    "prompt_injection": 0.05,
}
ROLES: Final = ("DEVELOPER", "DEVOPS", "ADMIN")
SPLITS: Final = ("dev", "test")
INTENT_FIELDS: Final = (
    "action",
    "service",
    "branch",
    "commit",
    "environment",
    "test_suite",
    "urgency",
    "extra_stages",
    "justification",
)
DRAFT_LABELER: Final = "claude-code-draft"
MAX_DRAFTS: Final = 30
# D-081: an item Claude Code wrote and labelled for a machine-labelled dataset.
MACHINE_LABELER: Final = "claude-code"
UNREVIEWABLE: Final = (DRAFT_LABELER, MACHINE_LABELER)


class DatasetError(ValueError):
    """The dataset breaks a rule 4.9 sets; the message says which line and which rule."""


@dataclass(frozen=True)
class Item:
    id: str
    text: str
    category: str
    role: str
    gold_intent: dict[str, Any]
    gold_behavior: str
    notes: str
    labeled_by: str
    needs_review: bool
    split: str = "dev"
    #: Where the message came from; the card lists every source and its licence.
    source: str = ""
    #: In 4.9's 75-item ablation subset.
    ablation: bool = False
    #: In the 20-command end-to-end sample, and the assistant it runs through.
    e2e: bool = False
    assistant: str | None = None

    @property
    def scorable(self) -> bool:
        """4.9: excluded from scoring until a human clears the flag."""
        return not self.needs_review


@dataclass(frozen=True)
class Dataset:
    path: Path
    items: tuple[Item, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    #: ``<name>.card.json``, when the dataset has one.
    card: dict[str, Any] | None = None

    @property
    def scorable(self) -> tuple[Item, ...]:
        return tuple(item for item in self.items if item.scorable)

    @property
    def needs_review(self) -> tuple[Item, ...]:
        return tuple(item for item in self.items if item.needs_review)

    @property
    def machine_labelled(self) -> bool:
        """Whether the card declares that a machine, not a person, wrote the gold labels."""
        return self.card is not None and self.card.get("labels") == "machine"


def _require(condition: bool, line: int, message: str) -> None:
    if not condition:
        raise DatasetError(f"line {line}: {message}")


def parse_item(raw: dict[str, Any], line: int) -> Item:
    for name in (
        "id",
        "text",
        "category",
        "role",
        "gold_intent",
        "gold_behavior",
        "labeled_by",
        "needs_review",
    ):
        _require(name in raw, line, f"missing {name!r}")

    _require(isinstance(raw["text"], str) and raw["text"].strip() != "", line, "empty text")
    _require(raw["category"] in CATEGORIES, line, f"category must be one of {CATEGORIES}")
    _require(raw["role"] in ROLES, line, f"role must be one of {ROLES}")
    _require(raw["gold_behavior"] in BEHAVIORS, line, f"gold_behavior must be one of {BEHAVIORS}")
    _require(isinstance(raw["needs_review"], bool), line, "needs_review must be true or false")
    split = raw.get("split", "dev")
    _require(split in SPLITS, line, f"split must be one of {SPLITS}")

    gold = raw["gold_intent"]
    _require(isinstance(gold, dict), line, "gold_intent must be an object")
    _require("action" in gold, line, "gold_intent needs an action")
    unknown = set(gold) - set(INTENT_FIELDS) - {"confidence"}
    _require(not unknown, line, f"gold_intent has unknown fields {sorted(unknown)}")

    # The rule that matters most: a draft cannot claim to be reviewed, and nor can an item Claude
    # Code labelled for a machine-labelled dataset.
    if raw["labeled_by"] in UNREVIEWABLE:
        _require(
            raw["needs_review"] is True,
            line,
            "an item drafted by Claude Code must keep needs_review: true until a human reviews "
            "it and changes labeled_by",
        )
    assistant = raw.get("assistant")
    _require(
        assistant in (None, "freestyle", "pipeline"),
        line,
        "assistant must be freestyle or pipeline",
    )

    return Item(
        id=str(raw["id"]),
        text=raw["text"],
        category=raw["category"],
        role=raw["role"],
        gold_intent=gold,
        gold_behavior=raw["gold_behavior"],
        notes=str(raw.get("notes", "")),
        labeled_by=str(raw["labeled_by"]),
        needs_review=raw["needs_review"],
        split=split,
        source=str(raw.get("source", "")),
        ablation=raw.get("ablation") is True,
        e2e=raw.get("e2e") is True,
        assistant=assistant,
    )


def card_path(path: Path) -> Path:
    """Where a dataset's card lives: ``<name>.card.json`` beside it."""
    return path.with_name(path.stem + ".card.json")


def _load_card(path: Path, data: bytes, items: list[Item]) -> dict[str, Any] | None:
    """The dataset's card, checked against the file, or None when there is none.

    Machine-labelled items need one: the card is what puts their provenance beside every figure.
    """
    location = card_path(path)
    machine = [item.id for item in items if item.labeled_by == MACHINE_LABELER]
    if not location.is_file():
        if machine:
            raise DatasetError(
                f"{len(machine)} item(s) are labelled {MACHINE_LABELER!r}, which needs a card "
                f"({location.name}) declaring machine labels (D-081)"
            )
        return None
    try:
        card: dict[str, Any] = json.loads(location.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DatasetError(f"{location.name} is not valid JSON ({exc})") from exc
    if machine and card.get("labels") != "machine":
        raise DatasetError(f"{location.name} must declare labels: machine for {machine[0]}")
    digest = hashlib.sha256(data).hexdigest()
    if card.get("sha256") != digest:
        raise DatasetError(
            f"{path.name} does not match the checksum in {location.name}: it was edited without "
            "rebuilding. Change the source and run `python -m eval build` instead."
        )
    return card


def load_dataset(path: Path) -> Dataset:
    if not path.is_file():
        raise DatasetError(f"{path} does not exist")

    data = path.read_bytes()
    items: list[Item] = []
    seen: set[str] = set()
    for number, line in enumerate(data.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except ValueError as exc:
            raise DatasetError(f"line {number}: not valid JSON ({exc})") from exc
        item = parse_item(raw, number)
        _require(item.id not in seen, number, f"duplicate id {item.id!r}")
        seen.add(item.id)
        items.append(item)

    drafts = sum(1 for item in items if item.labeled_by == DRAFT_LABELER)
    if drafts > MAX_DRAFTS:
        raise DatasetError(
            f"{drafts} items are labeled {DRAFT_LABELER!r}; 4.9 allows at most {MAX_DRAFTS}"
        )

    card = _load_card(path, data, items)
    return Dataset(path=path, items=tuple(items), warnings=tuple(_mix_warnings(items)), card=card)


def _mix_warnings(items: list[Item]) -> list[str]:
    """Where the category mix drifts more than five points from 4.9's target."""
    if not items:
        return ["the dataset is empty"]
    counts = Counter(item.category for item in items)
    warnings = []
    for category, target in TARGET_MIX.items():
        share = counts.get(category, 0) / len(items)
        if abs(share - target) > 0.05:
            warnings.append(f"{category} is {share:.0%} of the dataset; 4.9 targets {target:.0%}")
    return warnings


def overlap_with_examples(dataset: Dataset, example_texts: list[str]) -> list[str]:
    """Items whose text matches a few-shot example in the prompt.

    A match lets the model copy the answer it was shown, which inflates its measured accuracy. The
    prompt was written to avoid 4.6.5's wording for exactly this reason; this catches what slips
    through.
    """

    def norm(text: str) -> str:
        return " ".join(text.casefold().split())

    examples = {norm(text) for text in example_texts}
    return [item.id for item in dataset.items if norm(item.text) in examples]
