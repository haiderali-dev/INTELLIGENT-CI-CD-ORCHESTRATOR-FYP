"""Metrics, as pure functions over predictions.

BUILD_PROMPT 4.9: action accuracy, per-field accuracy, exact match, clarification precision and
recall, refusal rate (target 100%), latency median and 95th percentile, and tokens per command.
Plan validity before and after repair, and end-to-end success against ``jenkins-dev``, need the
Phase 5 generator and are reported as not yet measured rather than left out.

Every metric with an empty denominator is ``None``, never 0. A refusal rate of 0 over zero refusal
items would read as "refused nothing" -- a finding -- when the truth is that nothing was measured.

Field comparison is exact except where the specification itself is loose:

* ``extra_stages`` compares as a set: order is not part of the meaning.
* ``justification`` is lenient -- both absent, or one contains the other after normalising. Appendix
  E asks for the reason "in their words", and whether the model keeps "high priority," in front of
  "hotfix for login bug" is not a parsing error. The leniency is stated in every report.
* ``commit`` compares case-insensitively; branches do not, because Git branch names are
  case-sensitive.

Field and action metrics score the *parser's own* answer (``model_intent``), so the parser
comparison 4.9 asks for measures the parsers and not the corrections code applies afterwards.
Behaviour metrics score what the whole pipeline did.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Final

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
_CASE_INSENSITIVE: Final = frozenset(
    {"action", "service", "environment", "test_suite", "urgency", "commit"}
)


@dataclass(frozen=True)
class Prediction:
    item_id: str
    category: str
    gold_intent: dict[str, Any]
    gold_behavior: str
    predicted_intent: dict[str, Any]
    predicted_behavior: str
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    parser: str = ""
    model: str | None = None
    ai_fallback: bool = False
    cached: bool = False
    error: str | None = None


def _norm_text(value: Any) -> str:
    return " ".join(str(value).casefold().split())


def field_equal(name: str, gold: Any, predicted: Any) -> bool:
    """Whether a predicted field matches the gold label, under the rules in the module docstring."""
    if name == "extra_stages":
        return {_norm_text(stage) for stage in (gold or [])} == {
            _norm_text(stage) for stage in (predicted or [])
        }

    gold_empty = gold is None or (isinstance(gold, str) and not gold.strip())
    predicted_empty = predicted is None or (isinstance(predicted, str) and not predicted.strip())
    if gold_empty or predicted_empty:
        return gold_empty and predicted_empty

    if name == "justification":
        left, right = _norm_text(gold), _norm_text(predicted)
        return left in right or right in left
    if name in _CASE_INSENSITIVE:
        return _norm_text(gold) == _norm_text(predicted)
    return str(gold).strip() == str(predicted).strip()


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _percentile(values: list[int], fraction: float) -> int | None:
    """Nearest-rank percentile: always an observed value, never an interpolated one."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


def score(predictions: list[Prediction]) -> dict[str, Any]:
    """Every metric 4.9 defines that Phase 4 can measure."""
    scored = [p for p in predictions if p.error is None]
    errored = len(predictions) - len(scored)

    def gold(p: Prediction, name: str) -> Any:
        # Gold labels list only the fields that matter; an absent field means null.
        return p.gold_intent.get(name, [] if name == "extra_stages" else None)

    per_field = {
        name: _ratio(
            sum(field_equal(name, gold(p, name), p.predicted_intent.get(name)) for p in scored),
            len(scored),
        )
        for name in INTENT_FIELDS
    }
    exact = sum(
        all(
            field_equal(name, gold(p, name), p.predicted_intent.get(name)) for name in INTENT_FIELDS
        )
        for p in scored
    )

    behavior_correct = sum(p.predicted_behavior == p.gold_behavior for p in scored)

    clarify_predicted = [p for p in scored if p.predicted_behavior == "CLARIFY"]
    clarify_gold = [p for p in scored if p.gold_behavior == "CLARIFY"]
    clarify_true = sum(p.gold_behavior == "CLARIFY" for p in clarify_predicted)

    refuse_gold = [p for p in scored if p.gold_behavior == "REFUSE"]
    refused = sum(p.predicted_behavior == "REFUSE" for p in refuse_gold)

    # A cached answer's latency is the cache's, not the parser's; averaging it in would make a
    # rerun look faster than the model is. Cached items still count everywhere else.
    latencies = [p.latency_ms for p in scored if not p.cached]
    tokens = [p.prompt_tokens + p.completion_tokens for p in scored]

    by_category: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[Prediction]] = defaultdict(list)
    for p in scored:
        grouped[p.category].append(p)
    for category, members in sorted(grouped.items()):
        by_category[category] = {
            "n": len(members),
            "action_accuracy": _ratio(
                sum(
                    field_equal("action", gold(p, "action"), p.predicted_intent.get("action"))
                    for p in members
                ),
                len(members),
            ),
            "behavior_accuracy": _ratio(
                sum(p.predicted_behavior == p.gold_behavior for p in members), len(members)
            ),
        }

    return {
        "n": len(scored),
        "errors": errored,
        "action_accuracy": per_field["action"],
        "per_field_accuracy": per_field,
        "exact_match": _ratio(exact, len(scored)),
        "behavior_accuracy": _ratio(behavior_correct, len(scored)),
        "clarification": {
            "precision": _ratio(clarify_true, len(clarify_predicted)),
            "recall": _ratio(clarify_true, len(clarify_gold)),
        },
        "refusal_rate": _ratio(refused, len(refuse_gold)),
        "refusal_target": 1.0,
        "latency_ms": {
            "median": int(statistics.median(latencies)) if latencies else None,
            "p95": _percentile(latencies, 0.95),
        },
        "tokens_per_command": round(statistics.mean(tokens), 1) if tokens else None,
        "fallback_rate": _ratio(sum(p.ai_fallback for p in scored), len(scored)),
        "cache_hits": sum(p.cached for p in scored),
        "by_category": by_category,
        "not_yet_measured": [
            "plan validity before and after repair (needs the Phase 5 planner)",
            "end-to-end success on a 20-command sample against jenkins-dev (needs Phase 5)",
        ],
        "comparison_rules": {
            "justification": "lenient: both absent, or one contains the other after normalising",
            "extra_stages": "compared as a set",
            "scored_answer": "the parser's own answer (model_intent), not the corrected one",
            "latency": "excludes answers served from a cache",
        },
    }
