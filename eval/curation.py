"""Building and checking a curated dataset: ``eval-v1`` (docs/decisions.md D-081).

``python -m eval build`` turns ``eval/datasets/eval-v1.source.yaml`` into ``eval-v1.jsonl`` and
``eval-v1.card.json``. The source holds what a person would want to read and correct: each message
and its gold label. The builder adds what is mechanical, so that no one has to do it by hand and
everyone gets it the same way:

* **ids** from each item's key, so an edit never renumbers the rest;
* **the splits**, 100 development and 150 test (4.9), stratified within each category by the gold
  action and behaviour, with the items an earlier phase had already seen pinned to development;
* **the ablation subset**, 75 test items stratified the same way (4.9);
* **the end-to-end sample**, 20 test items that can run against ``jenkins-dev`` unchanged: a real
  service, its default branch, and an action that creates jobs.

Every random choice comes from one seeded generator, so a rebuild is byte for byte the same, and
``verify.py`` checks that it is.

**The label checks are independent of the code under test.** ``expected_behavior`` applies the
rules of 4.5.4 and 4.5.5 as the card states them, from the catalog file alone, without importing
the backend's validator, clarifier or policy. A gold label that disagrees with them is refused. That
catches slips in the labels; it cannot show that a rule was read rightly in the first place, which
is why the card states every rule it applies.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml

from eval.dataset import (
    BEHAVIORS,
    CATEGORIES,
    INTENT_FIELDS,
    MACHINE_LABELER,
    ROLES,
)

SEED: Final = 20261024

# 4.9's mix over 250 items. Missing field (37.5) rounds up and prompt injection (12.5) down, so the
# total stays 250; development takes 40% of each category, rounded so that it totals 100.
CATEGORY_SPLITS: Final[dict[str, dict[str, int]]] = {
    "clear": {"dev": 40, "test": 60},
    "paraphrase_typos": {"dev": 20, "test": 30},
    "missing_field": {"dev": 15, "test": 23},
    "ambiguous": {"dev": 10, "test": 15},
    "unsafe_out_of_scope": {"dev": 10, "test": 15},
    "prompt_injection": {"dev": 5, "test": 7},
}
ABLATION_SIZE: Final = 75
E2E_PER_ACTION: Final = 5

ACTIONS: Final = (
    "BUILD",
    "TEST",
    "DEPLOY",
    "BUILD_TEST_DEPLOY",
    "STATUS",
    "RERUN",
    "CANCEL",
    "UNSUPPORTED",
)
GENERATING_ACTIONS: Final = ("BUILD", "TEST", "DEPLOY", "BUILD_TEST_DEPLOY")
RUN_ACTIONS: Final = ("STATUS", "RERUN", "CANCEL")
DEPLOY_ACTIONS: Final = ("DEPLOY", "BUILD_TEST_DEPLOY")
ENVIRONMENTS: Final = ("staging", "production")
URGENCIES: Final = ("HIGH", "MEDIUM", "LOW")
EXTRA_STAGES: Final = ("lint", "security_scan", "integration_tests", "smoke_test")
SOURCES: Final = (
    "authored",
    "bp-4.6.5",
    "phase-4-draft",
    "clinc150",
    "deepset-pi",
    "deepset-pi+",
)
# Where each source's text came from, under what licence, and how it is used. The card carries
# this, and the datasheet (eval-v1.card.md) gives the attribution the licences ask for.
SOURCE_INFO: Final[tuple[dict[str, str], ...]] = (
    {
        "id": "authored",
        "name": "Written for this dataset by Claude Code",
        "licence": "the project's own",
        "use": "most messages, and every gold label",
    },
    {
        "id": "bp-4.6.5",
        "name": "BUILD_PROMPT.md 4.6.5, the commands version 1 must handle",
        "licence": "the project's own",
        "use": "the nine commands verbatim; development split",
    },
    {
        "id": "phase-4-draft",
        "name": "eval/datasets/sample.jsonl, drafted in Phase 4",
        "licence": "the project's own",
        "use": "verbatim; development split, because Phase 4 had seen them",
    },
    {
        "id": "clinc150",
        "name": "CLINC150 (clinc/clinc_oos), out-of-scope queries, test split",
        "url": "https://huggingface.co/datasets/clinc/clinc_oos",
        "licence": "CC BY 3.0",
        "citation": (
            "Larson, S. et al. (2019) 'An Evaluation Dataset for Intent Classification and "
            "Out-of-Scope Prediction', Proceedings of EMNLP-IJCNLP 2019, pp. 1311-1316. "
            "doi:10.18653/v1/D19-1131"
        ),
        "use": "eight human-written everyday requests, verbatim, as out-of-scope items",
    },
    {
        "id": "deepset-pi",
        "name": "deepset/prompt-injections, label 1 (injection), train split",
        "url": "https://huggingface.co/datasets/deepset/prompt-injections",
        "licence": "Apache-2.0",
        "citation": "deepset (2023) prompt-injections [dataset]. Hugging Face.",
        "use": "five injection attempts verbatim as whole messages",
    },
    {
        "id": "deepset-pi+",
        "name": "deepset/prompt-injections payloads after an authored request",
        "url": "https://huggingface.co/datasets/deepset/prompt-injections",
        "licence": "Apache-2.0",
        "citation": "deepset (2023) prompt-injections [dataset]. Hugging Face.",
        "use": "two payloads, verbatim, appended to a CI/CD request",
    },
)

# The backend's own limits on a message and a revision, restated: a dataset item the guard or the
# validator would refuse outright measures the guard, not the parser.
MAX_TEXT: Final = 1000
_REF: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,254}$")
_SHA: Final = re.compile(r"^[0-9a-f]{7,40}$")
_CONTROL: Final = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_WORD: Final = re.compile(r"[a-z0-9]+")

# Two texts sharing this much of their vocabulary are near-duplicates. Across the splits that is
# leakage: tuning on one would also tune on the other.
NEAR_DUPLICATE: Final = 0.8


class CurationError(ValueError):
    """The source breaks a rule the card states; the message names the item and the rule."""


@dataclass(frozen=True)
class ServiceFacts:
    """What the label checks need from one catalog entry, read from the YAML itself."""

    name: str
    suites: tuple[str, ...]
    environments: tuple[str, ...]


@dataclass(frozen=True)
class SourceItem:
    key: str
    category: str
    role: str
    text: str
    gold: dict[str, Any]
    behavior: str
    notes: str
    source: str
    source_ref: str
    split: str | None
    labeled_by: str
    needs_review: bool

    @property
    def id(self) -> str:
        return f"ev1-{self.key}"

    @property
    def action(self) -> str:
        return str(self.gold["action"])


@dataclass
class BuildReport:
    items: list[dict[str, Any]]
    card: dict[str, Any]
    near_duplicates: list[tuple[str, str, float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def read_catalog(path: Path) -> dict[str, ServiceFacts]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    facts: dict[str, ServiceFacts] = {}
    for service in raw["services"]:
        facts[service["name"]] = ServiceFacts(
            name=service["name"],
            suites=tuple(suite["name"] for suite in service.get("test_suites", [])),
            environments=tuple(service.get("allowed_environments", [])),
        )
    return facts


def load_source(path: Path) -> list[SourceItem]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise CurationError(f"{path.name}: expected a version 1 source")
    defaults = raw.get("defaults", {})
    items: list[SourceItem] = []
    for category, entries in raw["categories"].items():
        if category not in CATEGORIES:
            raise CurationError(f"unknown category {category!r}")
        for entry in entries:
            key = str(entry["key"])
            labeled_by = str(entry.get("labeled_by", MACHINE_LABELER))
            items.append(
                SourceItem(
                    key=key,
                    category=category,
                    role=str(entry.get("role", defaults.get("role", "DEVELOPER"))),
                    text=str(entry["text"]),
                    gold=dict(entry["gold"]),
                    behavior=str(entry["behavior"]),
                    notes=str(entry.get("notes", "")),
                    source=str(entry.get("source", defaults.get("source", "authored"))),
                    source_ref=str(entry.get("source_ref", "")),
                    split=entry.get("split"),
                    labeled_by=labeled_by,
                    needs_review=bool(entry.get("needs_review", True)),
                )
            )
    return items


# ---------------------------------------------------------------------------
# The label rules (card section 4), applied independently of the backend
# ---------------------------------------------------------------------------


def expected_behavior(
    gold: dict[str, Any], role: str, services: dict[str, ServiceFacts]
) -> tuple[str, str]:
    """What 4.5.4 and 4.5.5 say the system must do with this intent, and why.

    The order is the card's rule 10: out of scope, then production, then what is missing or
    rejected, then the HIGH-urgency justification. Every item assumes the user has a previous run,
    as the runner does, so STATUS, RERUN and CANCEL never need a service.
    """
    action = gold["action"]
    if action == "UNSUPPORTED":
        return "REFUSE", "not a CI/CD request"
    environment = gold.get("environment")
    if action in DEPLOY_ACTIONS and environment == "production":
        return "REFUSE", "production is refused for every role (4.5.5)"
    if action in RUN_ACTIONS:
        return "GENERATE", "a service or the user's previous run is enough (4.5.4)"

    service = gold.get("service")
    if service is None:
        return "CLARIFY", "no service (4.5.4)"
    facts = services[service]
    suite = gold.get("test_suite")
    if suite is not None and suite not in facts.suites:
        return "CLARIFY", f"{service} has no {suite} suite (4.5.3 step 3)"
    if action == "TEST" and suite is None and len(facts.suites) > 1:
        return "CLARIFY", f"{service} has {len(facts.suites)} suites and none is named (4.5.4)"
    if action in DEPLOY_ACTIONS and environment is None:
        return "CLARIFY", "no environment (4.5.4)"
    if environment is not None and environment not in facts.environments:
        return "CLARIFY", f"{service} cannot be deployed to {environment} (4.5.3 step 3)"
    if gold.get("urgency") == "HIGH" and role == "DEVELOPER" and not gold.get("justification"):
        return "CLARIFY", "a Developer's HIGH needs a justification (4.5.5)"
    return "GENERATE", "complete"


def check_gold(item: SourceItem, services: dict[str, ServiceFacts]) -> list[str]:
    """Every way this item's gold intent breaks the schema (4.5.2) or the card's rules."""
    gold = item.gold
    problems: list[str] = []
    unknown = set(gold) - set(INTENT_FIELDS)
    if unknown:
        problems.append(f"unknown fields {sorted(unknown)}")
    action = gold.get("action")
    if action not in ACTIONS:
        problems.append(f"action {action!r} is not one of {ACTIONS}")
        return problems
    if action == "UNSUPPORTED" and set(gold) != {"action"}:
        problems.append("an UNSUPPORTED intent sets no other field")

    service = gold.get("service")
    if service is not None and service not in services:
        problems.append(f"service {service!r} is not in the catalog; a name outside it is null")
    suites = {suite for facts in services.values() for suite in facts.suites}
    suite = gold.get("test_suite")
    if suite is not None and suite not in suites:
        problems.append(f"test_suite {suite!r} is no catalog suite; it would be null")
    environment = gold.get("environment")
    if environment is not None and environment not in ENVIRONMENTS:
        problems.append(f"environment {environment!r} is not staging or production")
    urgency = gold.get("urgency")
    if urgency is not None and urgency not in URGENCIES:
        problems.append(f"urgency {urgency!r} is not one of {URGENCIES}")
    justification = gold.get("justification")
    if justification is not None:
        if not isinstance(justification, str) or not justification.strip():
            problems.append("justification must be text")
        elif urgency is None:
            problems.append("a justification is a reason for urgency, so urgency must be set")
        elif justification.casefold() not in item.text.casefold():
            problems.append("a justification is copied in the user's words (Appendix E)")
    stages = gold.get("extra_stages", [])
    if not isinstance(stages, list) or len(set(stages)) != len(stages):
        problems.append("extra_stages must be a list without repeats")
    elif not set(stages) <= set(EXTRA_STAGES):
        problems.append(f"extra_stages must come from {EXTRA_STAGES}")
    commit = gold.get("commit")
    if commit is not None and commit != "latest" and not _SHA.match(str(commit)):
        problems.append(f"commit {commit!r} is neither 'latest' nor a 7-40 digit SHA")
    branch = gold.get("branch")
    if branch is not None:
        if not _REF.match(str(branch)):
            problems.append(f"branch {branch!r} is not a valid ref")
        elif str(branch) not in item.text:
            problems.append("a branch is copied exactly as written (card, rule 4)")
    return problems


def check_item(item: SourceItem, services: dict[str, ServiceFacts]) -> list[str]:
    problems = check_gold(item, services)
    if item.role not in ROLES:
        problems.append(f"role {item.role!r} is not one of {ROLES}")
    if item.behavior not in BEHAVIORS:
        problems.append(f"behavior {item.behavior!r} is not one of {BEHAVIORS}")
    if item.source not in SOURCES:
        problems.append(f"source {item.source!r} is not one of {SOURCES}")
    if item.source != "authored" and not item.source_ref:
        problems.append("an item from elsewhere says where it came from (source_ref)")
    if item.split is not None and item.split not in ("dev", "test"):
        problems.append(f"split {item.split!r} is not dev or test")
    if item.labeled_by == MACHINE_LABELER and not item.needs_review:
        problems.append("an item Claude Code labelled cannot claim a person reviewed it")
    if not item.text.strip() or len(item.text) > MAX_TEXT:
        problems.append(f"text must be 1 to {MAX_TEXT} characters")
    if _CONTROL.search(item.text):
        problems.append("text holds a control character")
    if not problems:
        expected, why = expected_behavior(item.gold, item.role, services)
        if expected != item.behavior:
            problems.append(f"behavior is {item.behavior}, but the rules give {expected}: {why}")
    return problems


# ---------------------------------------------------------------------------
# Text overlap
# ---------------------------------------------------------------------------


def normalise(text: str) -> str:
    return " ".join(text.casefold().split())


def words(text: str) -> frozenset[str]:
    return frozenset(_WORD.findall(text.casefold()))


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def near_duplicates(
    texts: dict[str, str], *, threshold: float = NEAR_DUPLICATE
) -> list[tuple[str, str, float]]:
    """Pairs of ids whose texts share at least ``threshold`` of their words, most similar first."""
    vocab = {key: words(text) for key, text in texts.items()}
    keys = sorted(vocab)
    pairs = []
    for index, left in enumerate(keys):
        for right in keys[index + 1 :]:
            score = jaccard(vocab[left], vocab[right])
            if score >= threshold:
                pairs.append((left, right, round(score, 3)))
    return sorted(pairs, key=lambda pair: (-pair[2], pair[0], pair[1]))


# ---------------------------------------------------------------------------
# Splits and subsets
# ---------------------------------------------------------------------------


def allocate(sizes: dict[Any, int], total: int) -> dict[Any, int]:
    """Largest-remainder allocation of ``total`` in proportion to ``sizes``, ties in key order."""
    whole = sum(sizes.values())
    if total > whole:
        raise CurationError(f"cannot take {total} from {whole}")
    if whole == 0:
        return dict.fromkeys(sizes, 0)
    exact = {key: total * size / whole for key, size in sizes.items()}
    shares = {key: int(value) for key, value in exact.items()}
    order = sorted(sizes, key=lambda key: (-(exact[key] - shares[key]), str(key)))
    for key in order[: total - sum(shares.values())]:
        shares[key] += 1
    return shares


def _stratum(item: SourceItem) -> tuple[str, str]:
    return (item.action, item.behavior)


def _sample(rng: random.Random, members: list[SourceItem], count: int) -> list[SourceItem]:
    """``count`` members, chosen within each (action, behaviour) stratum in proportion."""
    strata: dict[tuple[str, str], list[SourceItem]] = defaultdict(list)
    for item in sorted(members, key=lambda item: item.key):
        strata[_stratum(item)].append(item)
    quotas = allocate({stratum: len(group) for stratum, group in strata.items()}, count)
    chosen: list[SourceItem] = []
    for stratum in sorted(strata):
        chosen.extend(rng.sample(strata[stratum], quotas[stratum]))
    return chosen


def assign_splits(items: list[SourceItem], rng: random.Random) -> dict[str, str]:
    """Each item's split. Pinned items keep theirs; the rest fill each category's quotas."""
    splits: dict[str, str] = {}
    for category in CATEGORIES:
        members = [item for item in items if item.category == category]
        wanted = CATEGORY_SPLITS[category]
        if len(members) != wanted["dev"] + wanted["test"]:
            raise CurationError(
                f"{category} has {len(members)} items; 4.9's mix needs "
                f"{wanted['dev'] + wanted['test']}"
            )
        pinned_dev = [item for item in members if item.split == "dev"]
        pinned_test = [item for item in members if item.split == "test"]
        free = [item for item in members if item.split is None]
        need = wanted["dev"] - len(pinned_dev)
        if need < 0 or len(pinned_test) > wanted["test"]:
            raise CurationError(f"{category}: more items are pinned to a split than it holds")
        dev = {item.key for item in _sample(rng, free, need)}
        for item in members:
            splits[item.key] = item.split or ("dev" if item.key in dev else "test")
    return splits


def select_ablation(test_items: list[SourceItem], rng: random.Random) -> set[str]:
    """4.9's 75-item stratified subset: by category, then by action and behaviour within one."""
    by_category: dict[str, list[SourceItem]] = defaultdict(list)
    for item in test_items:
        by_category[item.category].append(item)
    quotas = allocate(
        {category: len(by_category[category]) for category in CATEGORIES}, ABLATION_SIZE
    )
    chosen: set[str] = set()
    for category in CATEGORIES:
        chosen.update(item.key for item in _sample(rng, by_category[category], quotas[category]))
    return chosen


def runnable_end_to_end(item: SourceItem) -> bool:
    """Whether the item can run against jenkins-dev as it stands: a real service on its default
    branch, an action that creates jobs, and a request the pipeline should carry out."""
    gold = item.gold
    return (
        item.behavior == "GENERATE"
        and item.action in GENERATING_ACTIONS
        and gold.get("service") is not None
        and gold.get("branch") in (None, "main")
        and gold.get("commit") in (None, "latest")
    )


def select_e2e(test_items: list[SourceItem], rng: random.Random) -> dict[str, str]:
    """20 runnable test items, five per job-creating action, each with the assistant to use.

    The assistants alternate within each action, starting from a different one for each action,
    so that each assistant gets ten.
    """
    chosen: dict[str, str] = {}
    assistants = ("freestyle", "pipeline")
    for number, action in enumerate(GENERATING_ACTIONS):
        eligible = sorted(
            (item for item in test_items if item.action == action and runnable_end_to_end(item)),
            key=lambda item: item.key,
        )
        if len(eligible) < E2E_PER_ACTION:
            raise CurationError(f"only {len(eligible)} runnable {action} items in the test split")
        picked = sorted(rng.sample(eligible, E2E_PER_ACTION), key=lambda item: item.key)
        for position, item in enumerate(picked):
            chosen[item.key] = assistants[(position + number) % 2]
    return chosen


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_jsonl(items: list[dict[str, Any]]) -> bytes:
    """One item a line, keys in a fixed order, LF endings, UTF-8: the same bytes on every OS."""
    lines = [json.dumps(item, ensure_ascii=False) for item in items]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build(
    source_path: Path,
    catalog_path: Path,
    *,
    example_texts: list[str],
    sources: tuple[dict[str, str], ...] = SOURCE_INFO,
    seed: int = SEED,
) -> BuildReport:
    items = load_source(source_path)
    services = read_catalog(catalog_path)

    problems: list[str] = []
    seen_keys: set[str] = set()
    seen_texts: dict[str, str] = {}
    examples = {normalise(text) for text in example_texts}
    for item in items:
        if item.key in seen_keys:
            problems.append(f"{item.key}: duplicate key")
        seen_keys.add(item.key)
        text = normalise(item.text)
        if text in seen_texts:
            problems.append(f"{item.key}: same text as {seen_texts[text]}")
        seen_texts[text] = item.key
        if text in examples:
            problems.append(f"{item.key}: repeats a few-shot example in the prompt")
        problems.extend(f"{item.key}: {problem}" for problem in check_item(item, services))
    if problems:
        raise CurationError("the source breaks the card's rules:\n  " + "\n  ".join(problems))

    # Seeded for a reproducible sample, which is the point; nothing here is a secret.
    rng = random.Random(seed)  # noqa: S311
    splits = assign_splits(items, rng)
    test_items = [item for item in items if splits[item.key] == "test"]
    ablation = select_ablation(test_items, rng)
    e2e = select_e2e(test_items, rng)

    rows: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda item: item.id):
        row: dict[str, Any] = {
            "id": item.id,
            "text": item.text,
            "category": item.category,
            "role": item.role,
            "gold_intent": item.gold,
            "gold_behavior": item.behavior,
            "notes": item.notes,
            "labeled_by": item.labeled_by,
            "needs_review": item.needs_review,
            "split": splits[item.key],
            "source": item.source,
            "source_ref": item.source_ref,
            "ablation": item.key in ablation,
            "e2e": item.key in e2e,
        }
        if item.key in e2e:
            row["assistant"] = e2e[item.key]
        rows.append(row)

    # Near-duplicates across the splits are leakage: tuning on the development twin tunes on the
    # test one. They are refused. Two items that must both stay can be pinned to one split.
    split_of = {row["id"]: row["split"] for row in rows}
    pairs = [
        pair
        for pair in near_duplicates(
            {row["id"]: row["text"] for row in rows}, threshold=NEAR_DUPLICATE
        )
        if split_of[pair[0]] != split_of[pair[1]]
    ]
    if pairs:
        listed = "\n  ".join(
            f"{left} and {right} share {score:.0%} of their words" for left, right, score in pairs
        )
        raise CurationError(
            "near-duplicates fall in different splits; reword one, or pin both to one split:\n  "
            + listed
        )
    example_pairs = []
    for row in rows:
        for example in example_texts:
            score = jaccard(words(row["text"]), words(example))
            if score >= NEAR_DUPLICATE:
                example_pairs.append(
                    {"id": row["id"], "example": example, "jaccard": round(score, 3)}
                )

    data = render_jsonl(rows)
    card = _card(rows, data, source_path, seed, sources, pairs, example_pairs)
    return BuildReport(items=rows, card=card, near_duplicates=pairs)


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[key]) for row in rows).items()))


def _card(
    rows: list[dict[str, Any]],
    data: bytes,
    source_path: Path,
    seed: int,
    sources: tuple[dict[str, str], ...],
    pairs: list[tuple[str, str, float]],
    example_pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    by_split: dict[str, dict[str, int]] = {}
    for split in ("dev", "test"):
        members = [row for row in rows if row["split"] == split]
        by_split[split] = {
            "items": len(members),
            **{f"category:{name}": count for name, count in _counts(members, "category").items()},
            **{
                f"behavior:{name}": count
                for name, count in _counts(members, "gold_behavior").items()
            },
        }
    return {
        "name": "eval-v1",
        "version": 1,
        "labels": "machine",
        "labelled_by": MACHINE_LABELER,
        "reviewed_by_a_person": sum(not row["needs_review"] for row in rows),
        "decision": "D-081",
        "datasheet": "eval/datasets/eval-v1.card.md",
        "items": len(rows),
        "sha256": sha256(data),
        "source": source_path.name,
        "source_sha256": sha256(source_path.read_bytes()),
        "seed": seed,
        "categories": _counts(rows, "category"),
        "behaviors": _counts(rows, "gold_behavior"),
        "roles": _counts(rows, "role"),
        "sources_used": _counts(rows, "source"),
        "actions": dict(sorted(Counter(row["gold_intent"]["action"] for row in rows).items())),
        "splits": by_split,
        "ablation": sum(row["ablation"] for row in rows),
        "e2e": sum(row["e2e"] for row in rows),
        "near_duplicates_across_splits": [list(pair) for pair in pairs],
        "near_few_shot_examples": example_pairs,
        "sources": list(sources),
    }


def render_card(card: dict[str, Any]) -> bytes:
    return (json.dumps(card, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write(report: BuildReport, jsonl_path: Path) -> Path:
    """Write the JSONL and its card beside it, both with LF endings."""
    jsonl_path.write_bytes(render_jsonl(report.items))
    card_path = jsonl_path.with_name(jsonl_path.stem + ".card.json")
    card_path.write_bytes(render_card(report.card))
    return card_path
