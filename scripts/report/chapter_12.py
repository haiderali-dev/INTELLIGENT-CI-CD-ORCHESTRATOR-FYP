"""Generate Chapter 12's tables from the archived run files, into the chapter itself.

    python scripts/report/chapter_12.py           # rewrite every generated table in the chapter
    python scripts/report/chapter_12.py --check   # exit 1 if any table is not what the files give

BUILD_PROMPT Part 6: "Table 12.1, Appendix C and the chatbot evaluation tables are generated from
files, never typed." The chapter's prose is written by hand. Each table sits between two markers,

    <!-- chapter_12.py: table-12-1 -->
    ...
    <!-- /chapter_12.py -->

and this script replaces what is between them, nothing else.

The experiment's figures are recomputed from the archived runs' `analysis.json` files with the
experiment package's own aggregation (`experiment/report.py`), so the chapter cannot disagree with
`table_12_1.md`:

- the matrix, `docs/experiment/matrix-2026-10-24/runs/`;
- the re-run after DF-48's fix, `docs/experiment/gate-fix-rerun-2026-10-24/runs/`;
- Milestone 2's runs, recomputed from `legacy/m2-poc/` (read only) by `experiment/m2.py`.

The chatbot evaluation's tables come from the archived `report.json` that `python -m eval report`
wrote, in the newest folder of `docs/evaluation/`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from experiment import m2  # noqa: E402
from experiment.report import (  # noqa: E402
    CONTROL,
    Aggregates,
    Condition,
    Stat,
    aggregate,
    efficiency,
    load_analyses,
)

CHAPTER = REPO_ROOT / "docs" / "report" / "chapter-12-achievements-and-results.md"
MATRIX = REPO_ROOT / "docs" / "experiment" / "matrix-2026-10-24" / "runs"
RERUN = REPO_ROOT / "docs" / "experiment" / "gate-fix-rerun-2026-10-24" / "runs"
EVALUATION = REPO_ROOT / "docs" / "evaluation"
PM = "\N{PLUS-MINUS SIGN}"
BLOCK = re.compile(
    r"(<!-- chapter_12\.py: (?P<name>[a-z0-9-]+) -->\n)(?P<body>.*?)(<!-- /chapter_12\.py -->)",
    re.S,
)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def num(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def stat_text(value: Stat | None, digits: int = 1, scale: float = 1.0) -> str:
    if value is None:
        return "n/a"
    if value.sd is None:
        return f"{value.mean * scale:.{digits}f}"
    return f"{value.mean * scale:.{digits}f} {PM} {value.sd * scale:.{digits}f}"


def change(control: Stat | None, arm: Stat | None) -> str:
    value = efficiency(control, arm)
    return "n/a" if value is None else f"{value:+.1f}%"


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


# ---------------------------------------------------------------------------
# The experiment
# ---------------------------------------------------------------------------


def experiment_aggregates() -> tuple[Aggregates, list[dict[str, Any]], list[dict[str, Any]]]:
    matrix, _ = load_analyses(sorted(path for path in MATRIX.iterdir() if path.is_dir()))
    rerun, _ = load_analyses(sorted(path for path in RERUN.iterdir() if path.is_dir()))
    return aggregate(matrix), matrix, rerun


def find(aggregates: Aggregates, group: str, workload: str, executors: int, order: str = "fixed"):
    for cond, arms in aggregates.items():
        if (cond.group, cond.workload, cond.executors, cond.order) == (
            group,
            workload,
            executors,
            order,
        ):
            return cond, arms
    raise SystemExit(f"no {group} {workload} {executors}x {order} condition in the archive")


def table_12_1(aggregates: Aggregates) -> str:
    _, arms = find(aggregates, "main", "freestyle-30", 1)
    base, opt = arms[CONTROL], arms["optimized"]
    rows = (
        ("Average queue waiting time (s)", "wait_mean", 1.0, 1),
        ("Maximum queue waiting time (s)", "wait_max", 1.0, 1),
        ("Average build completion time (s)", "completion_mean", 1.0, 1),
        ("Average waiting time of High priority jobs (s)", "wait_high", 1.0, 1),
        ("Average waiting time of Medium priority jobs (s)", "wait_medium", 1.0, 1),
        ("Average waiting time of Low priority jobs (s)", "wait_low", 1.0, 1),
        ("Longest wait of a Low priority job (s)", "wait_low_max", 1.0, 1),
        ("Makespan (s)", "makespan", 1.0, 1),
        ("Throughput (jobs per hour)", "throughput", 60.0, 1),
        ("Average executor utilization (%)", "utilization", 100.0, 1),
        ("Dependency violations", "violations", 1.0, 1),
    )
    lines = [
        "| KPI | Baseline (observe-only) | Optimized (our plugin) | Change (%) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, key, scale, digits in rows:
        lines.append(
            f"| {label} | {stat_text(base[key], digits, scale)} | "
            f"{stat_text(opt[key], digits, scale)} | {change(base[key], opt[key])} |"
        )
    lines.append(
        f"| Scheduler overhead per cycle, median (ms) | not applicable | "
        f"{stat_text(opt['overhead'], 2)} | |"
    )
    n = opt["wait_mean"].n if opt["wait_mean"] else 0
    lines += [
        "",
        f"Mean {PM} standard deviation over {n} repetitions of each arm. Change is report Appendix "
        "F's (baseline - optimized) / baseline x 100: positive when the optimized arm's figure is "
        "lower, which is better for waits and makespan and worse for throughput and utilization.",
    ]
    return "\n".join(lines)


def table_12_2(aggregates: Aggregates) -> str:
    lines = [
        "| Condition | n | Mean wait, observe-only / optimized (s) | Change | HIGH wait change | "
        "LOW wait, observe-only / optimized (s) | Makespan change | Violations, observe-only / "
        "optimized |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cond, arms in aggregates.items():
        if cond.group not in ("main", "cold-start", "random-order") or "optimized" not in arms:
            continue
        base, opt = arms[CONTROL], arms["optimized"]
        n = opt["wait_mean"].n if opt["wait_mean"] else 0
        label = f"{cond.group}: {cond.short()}"
        lines.append(
            f"| {label} | {n} | {num(base['wait_mean'].mean)} / {num(opt['wait_mean'].mean)} "
            f"| {change(base['wait_mean'], opt['wait_mean'])} "
            f"| {change(base['wait_high'], opt['wait_high'])} "
            f"| {num(base['wait_low'].mean)} / {num(opt['wait_low'].mean)} "
            f"| {change(base['makespan'], opt['makespan'])} "
            f"| {num(base['violations'].mean, 2)} / {num(opt['violations'].mean, 2)} |"
        )
    lines += [
        "",
        "Means over the repetitions (3 for main and cold start, 1 per seed for random order). "
        "Change is Appendix F's scheduling efficiency, positive when the optimized arm did better. "
        "The violations are the matrix's, on plugin build `cd6b1e3`; Table 12.4 has the re-run "
        "after DF-48's fix.",
    ]
    return "\n".join(lines)


def table_12_3(aggregates: Aggregates) -> str:
    lines = [
        "| Condition | n | First node-block wait, observe-only (s) | Optimized (s) | Change |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for cond, arms in aggregates.items():
        if cond.group != "main" or "optimized" not in arms or arms[CONTROL]["node_first"] is None:
            continue
        base, opt = arms[CONTROL]["node_first"], arms["optimized"]["node_first"]
        lines.append(
            f"| {cond.short()} | {opt.n if opt else 0} | {stat_text(base)} | {stat_text(opt)} "
            f"| {change(base, opt)} |"
        )
    lines += [
        "",
        "A Pipeline's wait is its first node block's: the run itself leaves the queue within "
        "milliseconds (D-015). Every Pipeline in these workloads has one node block, so the sum "
        "of all node-block waits equals the first.",
    ]
    return "\n".join(lines)


def _violations(analyses: list[dict[str, Any]], group: str, workload: str, order: str) -> list[str]:
    found = []
    for analysis in sorted(analyses, key=lambda a: (a["condition"]["repetition"], a["run"])):
        c = analysis["condition"]
        if (c["group"], c["workload"], c["arm"], c["order"]) == (group, workload, "optimized", order):
            found.append(str(analysis["kpis"]["dependency_violations"]))
    return found


def table_12_4(matrix: list[dict[str, Any]], rerun: list[dict[str, Any]]) -> str:
    rows = (
        ("pipeline-30, 3 executors, fixed order", "main", "main-rerun", "pipeline-30", "fixed"),
        ("Random order, seed 1", "random-order", "random-order-rerun", "mixed-30", "seed 1"),
        ("Random order, seed 2", "random-order", "random-order-rerun", "mixed-30", "seed 2"),
    )
    lines = [
        "| Optimized arm, 3 executors | Matrix, plugin `cd6b1e3` | Re-run, plugin `c01e744` |",
        "| --- | ---: | ---: |",
    ]
    for label, group, rerun_group, workload, order in rows:
        before = [
            v
            for analysis in matrix
            for v in [str(analysis["kpis"]["dependency_violations"])]
            if analysis["condition"]["group"] == group
            and analysis["condition"]["workload"] == workload
            and analysis["condition"]["arm"] == "optimized"
            and analysis["condition"]["order"] == order
            and int(analysis["condition"]["executors"]) == 3
        ]
        after = _violations(rerun, rerun_group, workload, order)
        lines.append(f"| {label} | {', '.join(before) or 'n/a'} | {', '.join(after) or 'n/a'} |")
    lines += [
        "",
        "Violations per run: a downstream job starting its work before its upstream finished. On "
        "pipeline-30 the three violations were one edge, held by the fix (D-080). The three left in "
        "random order are freestyle downstreams that took an idle executor before their upstream "
        "had been queued at all, which no gate inside the queue can prevent.",
    ]
    return "\n".join(lines)


def table_12_5(aggregates: Aggregates) -> str:
    _, arms = find(aggregates, "aging-ablation", "freestyle-30", 1)
    on, off = arms["optimized"], arms["aging-off"]
    rows = (
        ("Mean wait (s)", "wait_mean"),
        ("HIGH mean wait (s)", "wait_high"),
        ("LOW mean wait (s)", "wait_low"),
        ("Longest LOW wait (s)", "wait_low_max"),
        ("Makespan (s)", "makespan"),
    )
    lines = ["| KPI | Aging on | Aging off | Difference |", "| --- | ---: | ---: | ---: |"]
    for label, key in rows:
        difference = (
            None if on[key] is None or off[key] is None else off[key].mean - on[key].mean
        )
        lines.append(
            f"| {label} | {stat_text(on[key])} | {stat_text(off[key])} | "
            f"{'n/a' if difference is None else f'{difference:+.1f}'} |"
        )
    lines += ["", f"Mean {PM} standard deviation over 3 repetitions of each arm."]
    return "\n".join(lines)


def table_12_6(aggregates: Aggregates) -> str:
    _, main = find(aggregates, "main", "freestyle-30", 1)
    _, sanity = find(aggregates, "sanity", "freestyle-30", 1)
    observe, stock = main[CONTROL], sanity["stock"]
    rows = (
        ("Mean wait (s)", "wait_mean"),
        ("HIGH mean wait (s)", "wait_high"),
        ("LOW mean wait (s)", "wait_low"),
        ("Makespan (s)", "makespan"),
        ("Dependency violations", "violations"),
    )
    lines = [
        "| KPI | Stock Jenkins (n = 1) | Observe-only (n = 3) | Difference |",
        "| --- | ---: | ---: | ---: |",
    ]
    for label, key in rows:
        relative = efficiency(observe[key], stock[key])
        lines.append(
            f"| {label} | {stat_text(stock[key])} | {stat_text(observe[key])} | "
            f"{'n/a' if relative is None else f'{-relative:+.1f}%'} |"
        )
    lines += [
        "",
        "Difference is stock against observe-only. The stock run's waits start at the harness's "
        "trigger request, because it has no plugin to report queue entry (D-078).",
    ]
    return "\n".join(lines)


def table_12_7(aggregates: Aggregates) -> str:
    _, arms = find(aggregates, "main", "freestyle-30", 1)
    lines = [
        "| Series | Mean wait (s) | HIGH mean wait (s) | LOW mean wait (s) | Makespan (s) | "
        "Dependency violations |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in m2.import_m2():
        k = run["kpis"]
        levels = k["wait_s"]["by_level"]
        lines.append(
            f"| {run['series']}, {run['run']} | {k['wait_s']['mean']:.1f} | "
            f"{levels['HIGH']['mean']:.1f} | {levels['LOW']['mean']:.1f} | "
            f"{k['makespan_s']:.1f} | {k['dependency_violations']} |"
        )
    for arm, label in ((CONTROL, "v2 observe-only, mean of 3"), ("optimized", "v2 optimized, mean of 3")):
        stats = arms[arm]
        lines.append(
            f"| {label} | {num(stats['wait_mean'].mean)} | {num(stats['wait_high'].mean)} | "
            f"{num(stats['wait_low'].mean)} | {num(stats['makespan'].mean)} | "
            f"{num(stats['violations'].mean, 0)} |"
        )
    lines += [
        "",
        'Milestone 2\'s runs are recomputed from its own result files and labelled "M2 dispatcher '
        'v1"; they are never averaged with version 2 (Part 4.8.4). One executor, freestyle-30.',
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The chatbot evaluation
# ---------------------------------------------------------------------------


def evaluation_report() -> dict[str, Any] | None:
    folders = sorted(
        path.parent
        for path in EVALUATION.glob("*/report/report.json")
        if path.parent.parent.joinpath("runs").is_dir()
    )
    if not folders:
        return None
    report: dict[str, Any] = json.loads((folders[-1] / "report.json").read_text(encoding="utf-8"))
    report["_archive"] = folders[-1].parent.name
    return report


def parser_name(parser: str) -> str:
    return "Rule baseline" if parser == "rules" else parser.removeprefix("groq:")


PENDING = "The evaluation archive is not in `docs/evaluation/` yet; this table is generated from it."


def table_12_8(report: dict[str, Any] | None) -> str:
    if report is None:
        return PENDING
    lines = [
        "| Parser | Items | Action | Exact match | Response | Clarification precision / recall | "
        "Refusal rate | Latency p50 / p95 (ms) | Tokens per command |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["comparison"]:
        errors = f" ({row['errors']} unanswered)" if row["errors"] else ""
        latency = (
            "under 1 / under 1"
            if row["parser"] == "rules" and (row["latency_p95_ms"] or 0) < 1
            else f"{row['latency_p50_ms']} / {row['latency_p95_ms']}"
        )
        lines.append(
            f"| {parser_name(row['parser'])} | {row['n']}{errors} | {pct(row['action_accuracy'])} "
            f"| {pct(row['exact_match'])} | {pct(row['behavior_accuracy'])} "
            f"| {pct(row['clarification_precision'])} / {pct(row['clarification_recall'])} "
            f"| {pct(row['refusal_rate'])} | {latency} | {num(row['tokens_per_command'], 0)} |"
        )
    lines += [
        "",
        f"The test split of eval-v1, 150 items (archive `{report['_archive']}`). Gold labels by "
        "Claude Code, not reviewed by a person (D-081). Response is whether the pipeline "
        "generated, asked or refused as the gold label says.",
    ]
    return "\n".join(lines)


FIELDS = (
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
CATEGORIES = (
    ("clear", "Clear"),
    ("paraphrase_typos", "Paraphrase and typos"),
    ("missing_field", "Missing field"),
    ("ambiguous", "Ambiguous"),
    ("unsafe_out_of_scope", "Unsafe or out of scope"),
    ("prompt_injection", "Prompt injection"),
)


def table_12_9(report: dict[str, Any] | None) -> str:
    if report is None:
        return PENDING
    rows = report["comparison"]
    lines = [
        "| Field | " + " | ".join(parser_name(row["parser"]) for row in rows) + " |",
        "| --- |" + " ---: |" * len(rows),
    ]
    for field in FIELDS:
        cells = " | ".join(pct(row["per_field_accuracy"].get(field)) for row in rows)
        lines.append(f"| `{field}` | {cells} |")
    lines.append("")
    lines.append("| Category (response accuracy) | " + " | ".join(parser_name(r["parser"]) for r in rows) + " |")
    lines.append("| --- |" + " ---: |" * len(rows))
    for key, label in CATEGORIES:
        cells = " | ".join(pct(row["behavior_by_category"].get(key)) for row in rows)
        lines.append(f"| {label} | {cells} |")
    return "\n".join(lines)


def table_12_10(report: dict[str, Any] | None) -> str:
    if report is None:
        return PENDING
    lines = [
        "| Model | Items planned | Valid first time | Valid after repair | Repaired | Still "
        "invalid | Distinct requests | Tokens per plan |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["plans"]:
        lines.append(
            f"| {parser_name(row['parser'])} | {row['n']} of {row['plannable_items']} "
            f"| {pct(row['valid_before_repair'])} | {pct(row['valid_after_repair'])} "
            f"| {row['repaired']} | {row['still_invalid']} | {row['distinct_requests']} "
            f"| {num(row['tokens_per_plan'], 0)} |"
        )
    return "\n".join(lines)


def table_12_11(report: dict[str, Any] | None) -> str:
    if report is None or not report.get("ablations"):
        return PENDING
    ablations = report["ablations"]
    lines = [
        "| Configuration | Items | Action | Exact match | Response | Refusal rate | Tokens per "
        "command | Plans valid first / after repair |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in ablations["rows"]:
        lines.append(
            f"| {row['label'][0].upper() + row['label'][1:]} | {row['n']} "
            f"| {pct(row['action_accuracy'])} | {pct(row['exact_match'])} "
            f"| {pct(row['behavior_accuracy'])} | {pct(row['refusal_rate'])} "
            f"| {num(row['tokens_per_command'], 0)} "
            f"| {pct(row['plan_valid_before_repair'])} / {pct(row['plan_valid_after_repair'])} |"
        )
    rules = ablations.get("rules")
    if rules:
        lines.append(
            f"| Rule baseline, for reference | {rules['n']} | {pct(rules['action_accuracy'])} "
            f"| {pct(rules['exact_match'])} | {pct(rules['behavior_accuracy'])} "
            f"| {pct(rules['refusal_rate'])} | 0 | n/a |"
        )
    lines += [
        "",
        f"The 75-item stratified subset of the test split, with {parser_name(ablations['parser'])}. "
        "The no-repair row's plans are the full configuration's first attempts, so its first-time "
        "validity equals the full row's and its after-repair validity is the same figure.",
    ]
    return "\n".join(lines)


def table_12_12(report: dict[str, Any] | None) -> str:
    if report is None or not report.get("e2e"):
        return PENDING
    lines = [
        "| Model | Commands | Succeeded | Freestyle | Pipeline | Failed at |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["e2e"]:
        cells = []
        for assistant in ("freestyle", "pipeline"):
            cell = (row.get("by_assistant") or {}).get(assistant)
            cells.append(f"{cell['succeeded']} of {cell['n']}" if cell else "n/a")
        failed = ", ".join(f"{step}: {count}" for step, count in (row["failed_at"] or {}).items())
        lines.append(
            f"| {row['model']} | {row['n']} | {row['succeeded']} ({pct(row['success_rate'])}) "
            f"| {cells[0]} | {cells[1]} | {failed or 'none'} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def tables() -> dict[str, str]:
    aggregates, matrix, rerun = experiment_aggregates()
    report = evaluation_report()
    return {
        "table-12-1": table_12_1(aggregates),
        "table-12-2": table_12_2(aggregates),
        "table-12-3": table_12_3(aggregates),
        "table-12-4": table_12_4(matrix, rerun),
        "table-12-5": table_12_5(aggregates),
        "table-12-6": table_12_6(aggregates),
        "table-12-7": table_12_7(aggregates),
        "table-12-8": table_12_8(report),
        "table-12-9": table_12_9(report),
        "table-12-10": table_12_10(report),
        "table-12-11": table_12_11(report),
        "table-12-12": table_12_12(report),
    }


def regenerate(text: str, generated: dict[str, str]) -> tuple[str, list[str]]:
    unknown: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in generated:
            unknown.append(name)
            return match.group(0)
        return f"{match.group(1)}{generated[name]}\n{match.group(4)}"

    return BLOCK.sub(replace, text), unknown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if a table is stale")
    args = parser.parse_args(argv)
    text = CHAPTER.read_text(encoding="utf-8")
    generated = tables()
    updated, unknown = regenerate(text, generated)
    present = {match.group("name") for match in BLOCK.finditer(text)}
    missing = sorted(set(generated) - present)
    if unknown or missing:
        print(f"unknown blocks {unknown}; blocks missing from the chapter {missing}")
        return 1
    if args.check:
        stale = updated != text
        print(f"{len(present)} generated tables; {'stale' if stale else 'current'}")
        return 1 if stale else 0
    CHAPTER.write_text(updated, encoding="utf-8", newline="\n")
    print(f"wrote {len(present)} tables into {CHAPTER.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
