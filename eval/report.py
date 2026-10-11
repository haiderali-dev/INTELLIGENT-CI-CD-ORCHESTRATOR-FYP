"""``python -m eval report``: JSON and markdown for the Analytics page and the report.

BUILD_PROMPT 4.9: "``python -m eval report`` writes JSON and markdown for the Analytics page and the
report."

Only runs marked ``for_reporting`` -- over human-reviewed items alone -- appear in the comparison
table. A run that scored unreviewed drafts is listed separately under a heading that says why it
is excluded. Silently leaving it out would hide that it exists; silently including it would put
unchecked gold labels into a dissertation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval.runner import RESULTS_DIR


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


def render_markdown(runs: list[dict[str, Any]]) -> str:
    reportable = [run for run in runs if run["run"].get("for_reporting") and run["metrics"]["n"]]
    excluded = [run for run in runs if run not in reportable]

    lines = ["# Chatbot evaluation", ""]
    if not reportable:
        lines += [
            "No run is reportable yet. A run is reportable only when it scored human-reviewed "
            "items (BUILD_PROMPT 4.9: drafted items are excluded until a human clears "
            "`needs_review`).",
            "",
        ]
    else:
        lines += [
            "| Run | Parser | n | Action | Exact match | Behaviour | Clarify P / R | Refusal | "
            "Latency p50 / p95 (ms) | Tokens/cmd |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for run in reportable:
            m = run["metrics"]
            lines.append(
                f"| {run['name']} | {run['run']['parser']} | {m['n']} "
                f"| {_fmt(m['action_accuracy'])} | {_fmt(m['exact_match'])} "
                f"| {_fmt(m['behavior_accuracy'])} "
                f"| {_fmt(m['clarification']['precision'])} / {_fmt(m['clarification']['recall'])} "
                f"| {_fmt(m['refusal_rate'])} "
                f"| {_fmt(m['latency_ms']['median'], percent=False)} / "
                f"{_fmt(m['latency_ms']['p95'], percent=False)} "
                f"| {_fmt(m['tokens_per_command'], percent=False)} |"
            )
        lines += [
            "",
            "Field comparison: `extra_stages` as a set; `justification` leniently (both absent, or "
            "one contains the other). Action and field scores use each parser's own answer.",
            "",
        ]

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

    lines += [
        "## Not yet measured",
        "",
        "- Plan validity before and after repair (needs the Phase 5 planner).",
        "- End-to-end success on a 20-command sample against `jenkins-dev` (needs Phase 5).",
        "",
    ]
    return "\n".join(lines)


def write_report(results_dir: Path = RESULTS_DIR) -> tuple[Path, Path]:
    runs = collect(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / "report.json"
    md_path = results_dir / "report.md"
    json_path.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(runs), encoding="utf-8")
    return json_path, md_path
