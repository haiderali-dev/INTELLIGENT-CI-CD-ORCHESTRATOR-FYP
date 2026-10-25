"""``python -m eval report``: JSON and markdown for the Analytics page and the report.

BUILD_PROMPT 4.9: "``python -m eval report`` writes JSON and markdown for the Analytics page and the
report." ``report.json`` is what ``GET /api/analytics/evaluation`` serves; ``report.md`` is what
Chapter 12's chatbot evaluation section is generated from. Both come from the same ``build_report``,
so the page and the dissertation cannot disagree.

Only runs marked ``for_reporting`` appear in a table. Two kinds are:

* runs over items a person reviewed (``labels: human``);
* runs over a machine-labelled dataset (``labels: machine``, D-081). Their tables carry that
  provenance in a line above them, and the JSON carries it in ``provenance``.

A run that scored unreviewed drafts is listed separately under a heading that says why it is
excluded. Silently leaving it out would hide that it exists; silently including it would put
unchecked gold labels into a dissertation. So is an incomplete run's absence from a table: it is
tabled with ``complete: false``, never quietly as if it were finished.

The sections follow 4.9: the comparison on the test split, plan validity, the ablations on the
75-item subset, and end-to-end success.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from eval.metrics import INTENT_FIELDS
from eval.runner import RESULTS_DIR

CATEGORY_ORDER: Final = (
    "clear",
    "paraphrase_typos",
    "missing_field",
    "ambiguous",
    "unsafe_out_of_scope",
    "prompt_injection",
)
ABLATIONS: Final = (
    ("full", "the full configuration"),
    ("no-enums", "no catalog enums"),
    ("no-examples", "no few-shot examples"),
    ("no-repair", "no repair loop"),
)
MACHINE_STATEMENT: Final = (
    "Gold labels were written by Claude Code, an AI assistant, and checked against the dataset "
    "card's rules by code; no person has reviewed them (docs/decisions.md D-081). These figures "
    "measure agreement with those labels."
)


def _fmt(value: Any, *, percent: bool = True) -> str:
    if value is None:
        return "n/a"
    if percent and isinstance(value, float):
        return f"{value * 100:.1f}%"
    return str(value)


def collect(results_dir: Path = RESULTS_DIR) -> list[dict[str, Any]]:
    runs = []
    for path in sorted(results_dir.glob("*/metrics.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        data["name"] = path.parent.name
        runs.append(data)
    return runs


def _configuration(run: dict[str, Any]) -> str:
    """Which of 4.9's configurations a run is: full, or one ablation."""
    meta = run["run"]
    if meta.get("include_enums") is False:
        return "no-enums"
    if meta.get("include_examples") is False:
        return "no-examples"
    if meta.get("max_repairs") == 0:
        return "no-repair"
    return "full"


def _parser_order(parser: str) -> tuple[int, str]:
    return (0 if parser == "rules" else 1, parser)


def _scored(run: dict[str, Any]) -> bool:
    return run["run"].get("kind") != "e2e" and bool(run.get("metrics", {}).get("n"))


def _reportable(run: dict[str, Any]) -> bool:
    return bool(run["run"].get("for_reporting")) and _scored(run)


def _comparison_row(run: dict[str, Any]) -> dict[str, Any]:
    m = run["metrics"]
    return {
        "run": run["name"],
        "parser": run["run"]["parser"],
        "complete": run["run"].get("complete", True),
        "labels": run["run"].get("labels"),
        "n": m["n"],
        "errors": m.get("errors", 0),
        "action_accuracy": m.get("action_accuracy"),
        "exact_match": m.get("exact_match"),
        "behavior_accuracy": m.get("behavior_accuracy"),
        "clarification_precision": m.get("clarification", {}).get("precision"),
        "clarification_recall": m.get("clarification", {}).get("recall"),
        "refusal_rate": m.get("refusal_rate"),
        "latency_p50_ms": m.get("latency_ms", {}).get("median"),
        "latency_p95_ms": m.get("latency_ms", {}).get("p95"),
        "tokens_per_command": m.get("tokens_per_command"),
        "per_field_accuracy": {
            name: m.get("per_field_accuracy", {}).get(name) for name in INTENT_FIELDS
        },
        "behavior_by_category": {
            name: (m.get("by_category", {}).get(name) or {}).get("behavior_accuracy")
            for name in CATEGORY_ORDER
        },
    }


def _plan_row(run: dict[str, Any]) -> dict[str, Any] | None:
    plans = run.get("plans")
    if not plans:
        return None
    return {
        "run": run["name"],
        "parser": run["run"]["parser"],
        "max_repairs": run["run"].get("max_repairs"),
        **{
            key: plans.get(key)
            for key in (
                "plannable_items",
                "n",
                "valid_before_repair",
                "valid_after_repair",
                "repaired",
                "still_invalid",
                "no_model_plan",
                "errors",
                "distinct_requests",
                "tokens_per_plan",
            )
        },
    }


def _ablations(reportable: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The ablation table for the model with the most ablation runs (the primary model)."""
    by_parser: dict[str, dict[str, dict[str, Any]]] = {}
    for run in reportable:
        if run["run"].get("subset") == "ablation":
            by_parser.setdefault(run["run"]["parser"], {})[_configuration(run)] = run
    models = {parser: runs for parser, runs in by_parser.items() if parser != "rules"}
    if not models:
        return None
    parser = max(sorted(models), key=lambda name: len(models[name]))
    rows = []
    for key, label in ABLATIONS:
        chosen = models[parser].get(key)
        if chosen is None:
            continue
        row = _comparison_row(chosen)
        plans = chosen.get("plans") or {}
        rows.append(
            {
                "configuration": key,
                "label": label,
                **row,
                "plan_valid_before_repair": plans.get("valid_before_repair"),
                "plan_valid_after_repair": plans.get("valid_after_repair"),
            }
        )
    baseline = by_parser.get("rules", {}).get("full")
    return {
        "parser": parser,
        "rows": rows,
        "rules": _comparison_row(baseline) if baseline else None,
    }


def _e2e_row(run: dict[str, Any]) -> dict[str, Any]:
    summary = run.get("summary", {})
    return {
        "run": run["name"],
        "model": run["run"].get("model"),
        "complete": run["run"].get("complete", False),
        "labels": run["run"].get("labels"),
        **{
            key: summary.get(key)
            for key in ("n", "expected", "succeeded", "success_rate", "failed_at", "by_assistant")
        },
    }


def _run_row(run: dict[str, Any]) -> dict[str, Any]:
    meta = run["run"]
    scope = meta.get("subset") or meta.get("split") or "all"
    if meta.get("kind") == "e2e":
        scope = "e2e"
    n = run.get("metrics", {}).get("n") if meta.get("kind") != "e2e" else None
    if n is None and meta.get("kind") == "e2e":
        n = run.get("summary", {}).get("n")
    return {
        "run": run["name"],
        "parser": meta.get("parser"),
        "scope": scope,
        "configuration": _configuration(run) if meta.get("kind") != "e2e" else "e2e",
        "labels": meta.get("labels"),
        "for_reporting": bool(meta.get("for_reporting")),
        "complete": meta.get("complete", True),
        "stopped_reason": meta.get("stopped_reason"),
        "n": n,
    }


def _dataset(
    runs: list[dict[str, Any]], *, dataset_dir: Path | None = None
) -> dict[str, Any] | None:
    """The card of the dataset the reportable test runs used, read from the card file itself."""
    for run in runs:
        card = (run.get("dataset") or {}).get("card")
        dataset = run["run"].get("dataset")
        if not card or not dataset:
            continue
        relative = Path(dataset.replace("\\", "/"))
        path = dataset_dir / relative.name if dataset_dir else RESULTS_DIR.parents[1] / relative
        card_file = path.with_name(path.stem + ".card.json")
        if card_file.is_file():
            full = json.loads(card_file.read_text(encoding="utf-8"))
            if full.get("sha256") != card.get("sha256"):
                raise ValueError(f"Dataset card checksum disagrees with the run: {card_file}")
            return {
                "name": full.get("name"),
                "items": full.get("items"),
                "sha256": full.get("sha256"),
                "labels": full.get("labels"),
                "reviewed_by_a_person": full.get("reviewed_by_a_person"),
                "decision": full.get("decision"),
                "splits": {
                    split: (full.get("splits", {}).get(split) or {}).get("items")
                    for split in ("dev", "test")
                },
                "sources": [
                    {key: source.get(key) for key in ("id", "name", "licence")}
                    for source in full.get("sources", [])
                ],
            }
    return None


def build_report(runs: list[dict[str, Any]], *, dataset_dir: Path | None = None) -> dict[str, Any]:
    reportable = [run for run in runs if _reportable(run)]
    comparison = sorted(
        (
            _comparison_row(run)
            for run in reportable
            if run["run"].get("split") == "test" and _configuration(run) == "full"
        ),
        key=lambda row: _parser_order(row["parser"]),
    )
    plans = [
        row
        for run in sorted(reportable, key=lambda run: _parser_order(run["run"]["parser"]))
        if run["run"].get("split") == "test" and _configuration(run) == "full"
        for row in [_plan_row(run)]
        if row is not None
    ]
    e2e = [
        _e2e_row(run)
        for run in runs
        if run["run"].get("kind") == "e2e" and run["run"].get("for_reporting")
    ]
    labels = {run["run"].get("labels") for run in reportable} | {row["labels"] for row in e2e}
    labels.discard(None)
    tier = None if not labels else labels.pop() if len(labels) == 1 else "mixed"
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "provenance": {
            "labels": tier,
            "statement": MACHINE_STATEMENT if tier in ("machine", "mixed") else None,
        },
        "dataset": _dataset(reportable, dataset_dir=dataset_dir),
        "comparison": comparison,
        "plans": plans,
        "ablations": _ablations(reportable),
        "e2e": e2e,
        "runs": [_run_row(run) for run in runs],
    }


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _incomplete(row: dict[str, Any]) -> str:
    return "" if row.get("complete", True) else " (incomplete)"


def _comparison_md(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Parser | n | Errors | Action | Exact match | Behaviour | Clarify P / R | Refusal | "
        "Latency p50 / p95 (ms) | Tokens/cmd |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['parser']}{_incomplete(row)} | {row['n']} | {row['errors']} "
            f"| {_fmt(row['action_accuracy'])} | {_fmt(row['exact_match'])} "
            f"| {_fmt(row['behavior_accuracy'])} "
            f"| {_fmt(row['clarification_precision'])} / {_fmt(row['clarification_recall'])} "
            f"| {_fmt(row['refusal_rate'])} "
            f"| {_fmt(row['latency_p50_ms'], percent=False)} / "
            f"{_fmt(row['latency_p95_ms'], percent=False)} "
            f"| {_fmt(row['tokens_per_command'], percent=False)} |"
        )
    lines += ["", "Per-field accuracy, on each parser's own answer:", ""]
    lines.append("| Parser | " + " | ".join(INTENT_FIELDS) + " |")
    lines.append("| --- |" + " ---: |" * len(INTENT_FIELDS))
    for row in rows:
        cells = " | ".join(_fmt(row["per_field_accuracy"].get(name)) for name in INTENT_FIELDS)
        lines.append(f"| {row['parser']} | {cells} |")
    lines += ["", "Behaviour accuracy by category:", ""]
    lines.append("| Parser | " + " | ".join(CATEGORY_ORDER) + " |")
    lines.append("| --- |" + " ---: |" * len(CATEGORY_ORDER))
    for row in rows:
        cells = " | ".join(_fmt(row["behavior_by_category"].get(name)) for name in CATEGORY_ORDER)
        lines.append(f"| {row['parser']} | {cells} |")
    return lines


def _plans_md(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Parser | Plannable items | Planned by the model | Valid before repair | "
        "Valid after repair | Repaired | Still invalid | Distinct requests | Tokens/plan |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['parser']} | {row['plannable_items']} | {row['n']} "
            f"| {_fmt(row['valid_before_repair'])} | {_fmt(row['valid_after_repair'])} "
            f"| {row['repaired']} | {row['still_invalid']} | {row['distinct_requests']} "
            f"| {_fmt(row['tokens_per_plan'], percent=False)} |"
        )
    return lines


def _ablations_md(ablations: dict[str, Any]) -> list[str]:
    lines = [
        f"On the 75-item stratified subset of the test split, with `{ablations['parser']}`.",
        "",
        "| Configuration | n | Errors | Action | Exact match | Behaviour | Clarify P / R | "
        "Refusal | Tokens/cmd | Plans valid first / after repair |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in ablations["rows"]:
        lines.append(
            f"| {row['label']}{_incomplete(row)} | {row['n']} | {row['errors']} "
            f"| {_fmt(row['action_accuracy'])} | {_fmt(row['exact_match'])} "
            f"| {_fmt(row['behavior_accuracy'])} "
            f"| {_fmt(row['clarification_precision'])} / {_fmt(row['clarification_recall'])} "
            f"| {_fmt(row['refusal_rate'])} | {_fmt(row['tokens_per_command'], percent=False)} "
            f"| {_fmt(row['plan_valid_before_repair'])} / {_fmt(row['plan_valid_after_repair'])} |"
        )
    rules = ablations.get("rules")
    if rules:
        lines += [
            "",
            f"The rule baseline on the same 75 items: action {_fmt(rules['action_accuracy'])}, "
            f"behaviour {_fmt(rules['behavior_accuracy'])}.",
        ]
    return lines


def _e2e_md(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Model | Commands | Succeeded | Success | Failed at | Freestyle | Pipeline |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in rows:
        failed = ", ".join(f"{step} {count}" for step, count in (row["failed_at"] or {}).items())
        cells = []
        for assistant in ("freestyle", "pipeline"):
            cell = (row["by_assistant"] or {}).get(assistant)
            cells.append(f"{cell['succeeded']} of {cell['n']}" if cell else "n/a")
        lines.append(
            f"| {row['model']}{_incomplete(row)} | {row['n']} of {row['expected']} "
            f"| {row['succeeded']} | {_fmt(row['success_rate'])} | {failed or 'none'} "
            f"| {cells[0]} | {cells[1]} |"
        )
    return lines


def render_markdown(runs: list[dict[str, Any]], *, dataset_dir: Path | None = None) -> str:
    report = build_report(runs, dataset_dir=dataset_dir)
    reportable = [run for run in runs if _reportable(run)]
    lines = ["# Chatbot evaluation", ""]
    if report["provenance"]["statement"]:
        lines += [f"**Provenance.** {report['provenance']['statement']}", ""]
    dataset = report["dataset"]
    if dataset:
        lines += [
            f"Dataset `{dataset['name']}`: {dataset['items']} items, "
            f"{dataset['splits']['dev']} development and {dataset['splits']['test']} test, "
            f"sha256 `{dataset['sha256'][:12]}`; reviewed by a person: "
            f"{dataset['reviewed_by_a_person']}.",
            "",
        ]

    if not reportable:
        lines += [
            "No run is reportable yet. A run is reportable only when it scored human-reviewed "
            "items (BUILD_PROMPT 4.9: drafted items are excluded until a human clears "
            "`needs_review`), or a machine-labelled dataset with its provenance (D-081).",
            "",
        ]
    else:
        if report["comparison"]:
            lines += ["## Comparison on the test split", ""]
            lines += [*_comparison_md(report["comparison"]), ""]
        if report["plans"]:
            lines += ["## Plan validity before and after repair", ""]
            lines += [
                "Each model plans every test item whose gold behaviour is to generate jobs, from "
                "the gold intent after the validator, so a parse error cannot cost the plan.",
                "",
                *_plans_md(report["plans"]),
                "",
            ]
        if report["ablations"]:
            lines += ["## Ablations", "", *_ablations_md(report["ablations"]), ""]
        lines += [
            "## Every reportable run",
            "",
            "| Run | Parser | n | Action | Exact match | Behaviour | Clarify P / R | Refusal | "
            "Latency p50 / p95 (ms) | Tokens/cmd |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for run in reportable:
            row = _comparison_row(run)
            lines.append(
                f"| {run['name']}{_incomplete(row)} | {row['parser']} | {row['n']} "
                f"| {_fmt(row['action_accuracy'])} | {_fmt(row['exact_match'])} "
                f"| {_fmt(row['behavior_accuracy'])} "
                f"| {_fmt(row['clarification_precision'])} / "
                f"{_fmt(row['clarification_recall'])} "
                f"| {_fmt(row['refusal_rate'])} "
                f"| {_fmt(row['latency_p50_ms'], percent=False)} / "
                f"{_fmt(row['latency_p95_ms'], percent=False)} "
                f"| {_fmt(row['tokens_per_command'], percent=False)} |"
            )
        lines += [
            "",
            "Field comparison: `extra_stages` as a set; `justification` leniently (both absent, or "
            "one contains the other). Action and field scores use each parser's own answer. "
            "Items with a parser error are counted in Errors and excluded from accuracy, "
            "clarification and refusal denominators. "
            "Latency is the answering model call's own time; answers served from a cache are left "
            "out of it.",
            "",
        ]

    if report["e2e"]:
        lines += [
            "## End to end against jenkins-dev",
            "",
            "Each command through the real stack: understood, planned, generated as asked, run to "
            "SUCCESS on the agents, and, for a deploy, answering on staging.",
            "",
            *_e2e_md(report["e2e"]),
            "",
        ]

    excluded = [run for run in runs if not _reportable(run) and run["run"].get("kind") != "e2e"]
    if excluded:
        lines += ["## Not reportable", ""]
        for run in excluded:
            why = (
                "scored items still marked needs_review"
                if not run["run"].get("for_reporting")
                else "scored no items"
            )
            lines.append(f"- `{run['name']}` ({run['run']['parser']}): {why}")
        lines.append("")
    return "\n".join(lines)


def write_report(results_dir: Path = RESULTS_DIR, out_dir: Path | None = None) -> tuple[Path, Path]:
    """Write ``report.json`` and ``report.md`` for the runs in ``results_dir``, into ``out_dir``
    (the results directory itself by default, where the Analytics page reads it)."""
    runs = collect(results_dir)
    archived_dataset = results_dir.parent / "dataset"
    dataset_dir = archived_dataset if archived_dataset.is_dir() else None
    target = out_dir or results_dir
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "report.json"
    md_path = target / "report.md"
    json_path.write_text(
        json.dumps(build_report(runs, dataset_dir=dataset_dir), indent=2) + "\n", encoding="utf-8"
    )
    md_path.write_text(render_markdown(runs, dataset_dir=dataset_dir), encoding="utf-8")
    return json_path, md_path
