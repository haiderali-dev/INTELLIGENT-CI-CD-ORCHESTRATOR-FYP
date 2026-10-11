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
"""

from __future__ import annotations

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

    @property
    def scorable(self) -> bool:
        """4.9: excluded from scoring until a human clears the flag."""
        return not self.needs_review


@dataclass(frozen=True)
class Dataset:
    path: Path
    items: tuple[Item, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def scorable(self) -> tuple[Item, ...]:
        return tuple(item for item in self.items if item.scorable)

    @property
    def needs_review(self) -> tuple[Item, ...]:
        return tuple(item for item in self.items if item.needs_review)


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

    # The rule that matters most: a draft cannot claim to be reviewed.
    if raw["labeled_by"] == DRAFT_LABELER:
        _require(
            raw["needs_review"] is True,
            line,
            "an item drafted by Claude Code must keep needs_review: true until a human reviews "
            "it and changes labeled_by",
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
    )


def load_dataset(path: Path) -> Dataset:
    if not path.is_file():
        raise DatasetError(f"{path} does not exist")

    items: list[Item] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
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

    return Dataset(path=path, items=tuple(items), warnings=tuple(_mix_warnings(items)))


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
