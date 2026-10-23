"""``report``: Chapter 12's table, a CSV of every run, and its charts (T7.4).

Runs are grouped by their condition (group, workload, executors, history and order) and, within
it, by arm. Each figure is the mean across repetitions with its standard deviation, and n is
printed beside it: three repetitions is a small sample (Part 4.8.4). Scheduling efficiency is
report Appendix F's (baseline - optimized) / baseline x 100, with the observe-only arm as the
baseline. Milestone 2's runs are listed in a section of their own and never enter a v2 aggregate
(T7.5).
"""

from __future__ import annotations

import csv
import io
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from experiment import m2, results, svg

REPORT_DIR: Final = results.RESULTS_DIR / "report"
#: The arm every other is compared with: the plugin installed, ordering nothing.
CONTROL: Final = "observe-only"
ARM_ORDER: Final = ("observe-only", "optimized", "aging-off", "stock")
GROUP_ORDER: Final = ("main", "cold-start", "random-order", "aging-ablation", "sanity", "smoke")
PM: Final = "\N{PLUS-MINUS SIGN}"

Getter = Callable[[dict[str, Any]], float | None]


def _band(level: str) -> Getter:
    return lambda k: k["wait_s"]["by_level"][level]["mean"]


def _nested(*path: str) -> Getter:
    def get(k: dict[str, Any]) -> float | None:
        value: Any = k
        for part in path:
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value if isinstance(value, int | float) else None

    return get


#: (key, header, how to read it from a run's KPIs), in table order.
METRICS: Final[tuple[tuple[str, str, Getter], ...]] = (
    ("wait_mean", "Mean wait (s)", _nested("wait_s", "mean")),
    ("wait_high", "HIGH mean wait (s)", _band("HIGH")),
    ("wait_medium", "MEDIUM mean wait (s)", _band("MEDIUM")),
    ("wait_low", "LOW mean wait (s)", _band("LOW")),
    ("wait_low_max", "Longest LOW wait (s)", _nested("max_low_wait_s")),
    ("wait_max", "Longest wait (s)", _nested("wait_s", "max")),
    ("completion_mean", "Mean completion (s)", _nested("completion_s", "mean")),
    ("makespan", "Makespan (s)", _nested("makespan_s")),
    ("throughput", "Throughput (jobs/min)", _nested("throughput_per_min")),
    ("utilization", "Executor utilisation", _nested("utilization")),
    ("violations", "Dependency violations", _nested("dependency_violations")),
    ("overhead", "Scheduler overhead, median (ms)", _nested("scheduler_overhead_ms", "median")),
    ("node_first", "First node-block wait (s)", _nested("node_block_wait_s", "first", "mean")),
    ("node_total", "All node-block waits (s)", _nested("node_block_wait_s", "total", "mean")),
)
TABLE_COLUMNS: Final = (
    "wait_mean",
    "wait_high",
    "wait_medium",
    "wait_low",
    "wait_low_max",
    "makespan",
    "throughput",
    "utilization",
    "violations",
    "overhead",
)
#: The figures scheduling efficiency is computed for.
EFFICIENCY: Final = ("wait_mean", "wait_high", "makespan")


@dataclass(frozen=True, order=True)
class Condition:
    """What a run measured, apart from the arm: the unit repetitions are averaged over."""

    rank: int
    group: str
    workload: str
    executors: int
    history: str
    order: str

    def label(self) -> str:
        return (
            f"{self.group}: {self.workload}, {self.executors} executor"
            f"{'s' if self.executors != 1 else ''}, {self.history} history, {self.order} order"
        )

    def short(self) -> str:
        seed = "" if self.order == "fixed" else f" {self.order}"
        return f"{self.workload} {self.executors}x{seed}"


@dataclass(frozen=True)
class Stat:
    mean: float
    sd: float | None
    n: int

    def text(self, digits: int = 2) -> str:
        if self.sd is None:
            return f"{self.mean:.{digits}f}"
        return f"{self.mean:.{digits}f} {PM} {self.sd:.{digits}f}"


Aggregates = dict[Condition, dict[str, dict[str, Stat | None]]]


def condition_of(analysis: dict[str, Any]) -> Condition:
    c = analysis["condition"]
    rank = GROUP_ORDER.index(c["group"]) if c["group"] in GROUP_ORDER else len(GROUP_ORDER)
    return Condition(rank, c["group"], c["workload"], int(c["executors"]), c["history"], c["order"])


def load_analyses(folders: Sequence[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    """The analyses of every analysed run, and the names of runs without one (incomplete)."""
    analyses, skipped = [], []
    for folder in folders:
        path = folder / "analysis.json"
        if path.is_file():
            analyses.append(results.read_json(path))
        else:
            skipped.append(folder.name)
    return analyses, skipped


def stat(values: Sequence[float]) -> Stat | None:
    if not values:
        return None
    sd = statistics.stdev(values) if len(values) > 1 else None
    return Stat(mean=statistics.fmean(values), sd=sd, n=len(values))


def aggregate(analyses: Sequence[dict[str, Any]]) -> Aggregates:
    """Mean and standard deviation of every metric, per condition and arm."""
    grouped: dict[Condition, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for analysis in analyses:
        grouped[condition_of(analysis)][analysis["condition"]["arm"]].append(analysis["kpis"])
    aggregates: Aggregates = {}
    for cond in sorted(grouped):
        aggregates[cond] = {}
        for arm in sorted(grouped[cond], key=_arm_rank):
            runs = grouped[cond][arm]
            aggregates[cond][arm] = {
                key: stat([v for v in (get(k) for k in runs) if v is not None])
                for key, _, get in METRICS
            }
    return aggregates


def efficiency(control: Stat | None, arm: Stat | None) -> float | None:
    """Appendix F's scheduling efficiency, in percent; positive when the arm waits less."""
    if control is None or arm is None or control.mean == 0:
        return None
    return (control.mean - arm.mean) / control.mean * 100


def table_md(
    aggregates: Aggregates,
    m2_runs: Sequence[dict[str, Any]],
    runs: int,
    skipped: Sequence[str],
    generated: datetime,
) -> str:
    """``table_12_1.md``: one table per condition, then Milestone 2's runs on their own."""
    headers = {key: header for key, header, _ in METRICS}
    lines = [
        "# Table 12.1: Experiment v2",
        "",
        f"Generated by `python -m experiment report` on {generated:%Y-%m-%d %H:%M} UTC from {runs} "
        "analysed run(s) in `experiment/results/`. Each figure is the mean across repetitions "
        f"with its standard deviation ({PM}), and n is the number of repetitions. Three "
        "repetitions is a small sample: a difference smaller than about two standard deviations "
        "is not established (Part 4.8.4).",
        "",
        "Scheduling efficiency is (baseline - arm) / baseline x 100 against the observe-only arm, "
        "the plugin installed but ordering nothing (report Appendix F); a positive value means the "
        "arm did better.",
    ]
    if skipped:
        lines += ["", f"Not included, because they did not complete: {', '.join(skipped)}."]
    for cond, arms in aggregates.items():
        lines += ["", f"## {cond.label()}", ""]
        columns = [c for c in TABLE_COLUMNS if any(arms[a][c] is not None for a in arms)]
        node = any(arms[a]["node_first"] is not None for a in arms)
        if node:
            columns += ["node_first", "node_total"]
        lines.append("| Arm | n | " + " | ".join(headers[c] for c in columns) + " |")
        lines.append("| --- | ---: | " + " | ".join("---:" for _ in columns) + " |")
        for arm, stats in arms.items():
            n = max((s.n for s in stats.values() if s is not None), default=0)
            cells = [_cell(stats[c], c) for c in columns]
            lines.append(f"| {arm} | {n} | " + " | ".join(cells) + " |")
        if CONTROL in arms and len(arms) > 1:
            lines.append("")
            for arm in arms:
                if arm == CONTROL:
                    continue
                parts = []
                for key in EFFICIENCY:
                    value = efficiency(arms[CONTROL][key], arms[arm][key])
                    if value is not None:
                        parts.append(f"{headers[key].split(' (')[0].lower()} {value:+.1f}%")
                lines.append(
                    f"Scheduling efficiency of {arm} against observe-only: {', '.join(parts)}."
                )
    lines += [
        "",
        f'## Milestone 2, from its own result files: the series "{m2.SERIES}" and its control',
        "",
        "Recomputed with the same code from `legacy/m2-poc/experiment/results/` (read only), one "
        "executor, history as Milestone 2 left it. These runs are not part of any v2 figure above.",
        "",
        "| Series | Run | Mean wait (s) | HIGH mean wait (s) | MEDIUM mean wait (s) "
        "| LOW mean wait (s) | Longest LOW wait (s) | Makespan (s) | Dependency violations |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in m2_runs:
        k = run["kpis"]
        lines.append(
            f"| {run['series']} | {run['run']} | {k['wait_s']['mean']:.2f} | "
            + " | ".join(
                f"{k['wait_s']['by_level'][b]['mean']:.2f}" for b in ("HIGH", "MEDIUM", "LOW")
            )
            + f" | {k['max_low_wait_s']:.2f} | {k['makespan_s']:.2f}"
            + f" | {k['dependency_violations']} |"
        )
    return "\n".join(lines) + "\n"


def runs_csv(analyses: Sequence[dict[str, Any]]) -> str:
    """One row per run: its condition, then every metric."""
    fields = [
        "run",
        "group",
        "workload",
        "executors",
        "history",
        "order",
        "arm",
        "repetition",
        "controller",
        "jenkinsVersion",
        "pluginVersion",
        "pluginBuild",
    ]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(fields + [key for key, _, _ in METRICS])
    for analysis in sorted(analyses, key=lambda a: a["run"]):
        c = analysis["condition"]
        row = [analysis["run"], *(c.get(f) for f in fields[1:])]
        writer.writerow(row + [get(analysis["kpis"]) for _, _, get in METRICS])
    return out.getvalue()


def charts(aggregates: Aggregates, m2_runs: Sequence[dict[str, Any]]) -> dict[str, str]:
    """Chapter 12's charts, as SVG: file name to content."""
    out: dict[str, str] = {}
    bands = ("HIGH", "MEDIUM", "LOW")
    for cond, arms in aggregates.items():
        name = f"waits-{cond.group}-{cond.workload}-{cond.executors}x" + (
            "" if cond.order == "fixed" else "-" + cond.order.replace(" ", "")
        )
        out[f"{name}.svg"] = svg.grouped_bars(
            f"Mean wait by band: {cond.short()} ({cond.group})",
            bands,
            [
                svg.Series(
                    arm,
                    [_mean(stats[f"wait_{b.lower()}"]) for b in bands],
                    [_sd(stats[f"wait_{b.lower()}"]) for b in bands],
                )
                for arm, stats in arms.items()
            ],
            "Seconds",
        )
    conditions = list(aggregates)
    arms_seen = [a for a in ARM_ORDER if any(a in aggregates[c] for c in conditions)]
    if conditions:
        for key, title, unit in (
            ("makespan", "Makespan by condition", "Seconds"),
            ("wait_low_max", "Longest LOW wait by condition", "Seconds"),
            ("violations", "Dependency violations by condition", "Edges broken"),
        ):
            out[f"{key.replace('_', '-')}.svg"] = svg.grouped_bars(
                title,
                [c.short() for c in conditions],
                [
                    svg.Series(
                        arm,
                        [_mean(aggregates[c].get(arm, {}).get(key)) for c in conditions],
                        [_sd(aggregates[c].get(arm, {}).get(key)) for c in conditions],
                    )
                    for arm in arms_seen
                ],
                unit,
            )
    if m2_runs:
        out["m2-runs.svg"] = svg.grouped_bars(
            f"Milestone 2's runs, recomputed: mean wait by band ({m2.SERIES} and its control)",
            [run["run"].split(" (")[0] for run in m2_runs],
            [
                svg.Series(b, [run["kpis"]["wait_s"]["by_level"][b]["mean"] for run in m2_runs])
                for b in bands
            ],
            "Seconds",
        )
    return out


def write_report(folders: Sequence[Path], out_dir: Path = REPORT_DIR) -> list[Path]:
    """Write ``table_12_1.md``, ``runs.csv`` and the charts; return what was written."""
    analyses, skipped = load_analyses(folders)
    aggregates = aggregate(analyses)
    m2_runs = m2.import_m2()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    table = out_dir / "table_12_1.md"
    table.write_text(
        table_md(aggregates, m2_runs, len(analyses), skipped, datetime.now(UTC)),
        encoding="utf-8",
        newline="\n",
    )
    written.append(table)
    csv_path = out_dir / "runs.csv"
    csv_path.write_text(runs_csv(analyses), encoding="utf-8", newline="\n")
    written.append(csv_path)
    for name, content in charts(aggregates, m2_runs).items():
        path = out_dir / name
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def _arm_rank(arm: str) -> int:
    return ARM_ORDER.index(arm) if arm in ARM_ORDER else len(ARM_ORDER)


def _cell(value: Stat | None, key: str) -> str:
    if value is None:
        return "-"
    digits = 0 if key == "violations" and value.sd is None else (4 if key == "utilization" else 2)
    return value.text(digits)


def _mean(value: Stat | None) -> float | None:
    return None if value is None else value.mean


def _sd(value: Stat | None) -> float | None:
    return None if value is None else value.sd
