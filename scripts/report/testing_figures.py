"""The testing chapter's data tables and figures, from the evidence campaign and the repository.

    python scripts/report/testing_figures.py .tmp/campaign/<commit> --ci <runs.json>

Writes the data behind every figure to ``docs/testing/data/`` (each chart's table twin) and the
figures to ``docs/testing/figures/``. Every number comes from a file a run wrote, from git, or from
Milestone 2's result files under ``legacy/`` (read only).

Colours follow the data-visualisation method the project's DESIGN.md used: the categorical slots
in their fixed order (never more than four on one chart), status colours only where a colour means
passed or failed and always with a label, thin marks and hairline grids, one value axis per chart.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "docs" / "testing" / "data"
FIGURES = REPO_ROOT / "docs" / "testing" / "figures"

# The reference palette's light-mode categorical slots, in order, and its chrome (dataviz method).
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE, INK, SECONDARY, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
GOOD, CRITICAL, WARNING = "#0ca30c", "#d03b3b", "#fab219"


def style() -> None:
    plt.rcParams.update({
        "font.family": ["Segoe UI", "DejaVu Sans"],
        "font.size": 9,
        "axes.facecolor": SURFACE,
        "figure.facecolor": SURFACE,
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.labelcolor": SECONDARY,
        "axes.titlesize": 10,
        "axes.titleweight": "bold",
        "axes.titlecolor": INK,
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": SECONDARY,
        "ytick.labelcolor": SECONDARY,
        "legend.frameon": False,
        "legend.fontsize": 8,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
    })


def save(figure: plt.Figure, name: str) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    figure.savefig(FIGURES / f"{name}.png")
    plt.close(figure)
    print(f"figure {name}.png")


def write_csv(name: str, header: list[str], rows: list[list[object]]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with (DATA / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"data {name}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


# ---------------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------------


def test_growth() -> list[list[object]]:
    """Test definitions in each component's source at every commit: definitions, not executions."""

    def count(commit: str, pattern: str, *paths: str) -> int:
        out = subprocess.run(
            ["git", "grep", "-c", "-E", pattern, commit, "--", *paths],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        ).stdout
        return sum(int(line.rsplit(":", 1)[1]) for line in out.splitlines() if line.strip())

    rows = []
    for line in git("log", "--reverse", "--format=%H%x09%cs").splitlines():
        commit, date = line.split("\t")
        rows.append([
            commit[:7],
            date,
            count(commit, r"^\s*@(Test|ParameterizedTest)\b", "plugin/src/test/java",
                  ":(exclude)plugin/src/test/java/io/jenkins/plugins/queueoptimizer/experiment"),
            count(commit, r"^\s*(async )?def test_", "backend/tests"),
            count(commit, r"^\s*(it|test)\(", "frontend/src", "frontend/e2e"),
            count(commit, r"^\s*(async )?def test_|^\s*test\(", "sample-services"),
        ])
    write_csv("test-growth.csv", ["commit", "date", "plugin", "backend", "frontend", "sample_services"], rows)
    return rows


def coverage(campaign: Path) -> list[list[object]]:
    rows = []
    jacoco = campaign / "plugin" / "jacoco.csv"
    if jacoco.is_file():
        data = read_csv(jacoco)
        total = {key: sum(int(row[key]) for row in data) for key in data[0] if key.endswith(("MISSED", "COVERED"))}
        pct = lambda kind: 100 * total[f"{kind}_COVERED"] / (total[f"{kind}_COVERED"] + total[f"{kind}_MISSED"])  # noqa: E731
        rows.append(["Plugin (JaCoCo, unit and integration tests)", round(pct("LINE"), 1), round(pct("BRANCH"), 1)])
    for name, label in (
        ("backend-offline-coverage.json", "Backend (coverage.py, offline suite)"),
        ("backend-e2e-coverage.json", "Backend (coverage.py, offline, integration and end-to-end)"),
    ):
        path = campaign / "backend" / name
        if path.is_file():
            totals = json.loads(path.read_text(encoding="utf-8"))["totals"]
            statements = 100 * totals["covered_lines"] / max(1, totals["num_statements"])
            branches = 100 * totals["covered_branches"] / max(1, totals["num_branches"])
            rows.append([label, round(statements, 1), round(branches, 1)])
    summary = campaign / "frontend" / "coverage-summary.json"
    if summary.is_file():
        total = json.loads(summary.read_text(encoding="utf-8"))["total"]
        rows.append(["Frontend (V8, unit and component tests)", total["statements"]["pct"], total["branches"]["pct"]])
    write_csv("coverage-summary.csv", ["component", "statements_or_lines_pct", "branches_pct"], rows)
    return rows


def mutation(campaign: Path) -> list[list[object]]:
    report = campaign / "plugin-mutation" / "mutations.xml"
    if not report.is_file():
        return []
    per_class: dict[str, Counter[str]] = defaultdict(Counter)
    root = ElementTree.parse(report).getroot()  # noqa: S314 (PIT's own report)
    for item in root.iter("mutation"):
        name = item.findtext("mutatedClass", "").split(".")[-1].split("$")[0]
        per_class[name][item.get("status", "")] += 1
    rows = []
    for name, counts in sorted(per_class.items()):
        killed = counts["KILLED"] + counts["TIMED_OUT"] + counts["MEMORY_ERROR"]
        rows.append([name, sum(counts.values()), killed, counts["SURVIVED"], counts["NO_COVERAGE"]])
    write_csv("mutation-by-class.csv", ["class", "mutants", "killed", "survived", "no_coverage"], rows)
    return rows


def ci_history(ci: Path | None) -> list[list[object]]:
    if ci is None or not ci.is_file():
        return []
    runs = json.loads(ci.read_text(encoding="utf-8"))
    rows = [
        [run["databaseId"], run["createdAt"][:10], run["headBranch"], run["headSha"][:7], run["event"],
         run.get("conclusion") or run.get("status"), run["displayTitle"]]
        for run in sorted(runs, key=lambda run: run["createdAt"])
    ]
    write_csv("ci-runs.csv", ["run", "date", "branch", "commit", "event", "conclusion", "title"], rows)
    return rows


def copy_experiments(campaign: Path) -> None:
    folder = campaign / "plugin-experiments"
    target = DATA / "experiments"
    target.mkdir(parents=True, exist_ok=True)
    for source in sorted(folder.glob("*")) if folder.is_dir() else []:
        (target / source.name).write_bytes(source.read_bytes())
        print(f"data experiments/{source.name}")


# ---------------------------------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------------------------------


def figure_suites() -> None:
    rows = read_csv(DATA / "test-register-summary.csv")
    rows.sort(key=lambda row: int(row["tests"]))
    figure, axis = plt.subplots(figsize=(6.5, 0.32 * len(rows) + 0.9))
    names = [row["suite"] for row in rows]
    counts = [int(row["tests"]) for row in rows]
    bars = axis.barh(names, counts, color=SLOTS[0], height=0.6, edgecolor=SURFACE, linewidth=1.5)
    for bar, row in zip(bars, rows, strict=True):
        failed = int(row["failed"]) + int(row["error"])
        note = f"{row['tests']}" + (f"  ({row['skipped']} skipped)" if int(row["skipped"]) else "")
        note += f"  {failed} failed" if failed else ""
        axis.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, "  " + note, va="center", color=SECONDARY, fontsize=8)
    axis.set_xscale("log")
    axis.set_xlabel("Tests that ran (log scale)")
    axis.grid(axis="y", visible=False)
    axis.set_title("Every suite, one campaign: tests that ran per suite")
    save(figure, "f01-tests-per-suite")


def figure_growth() -> None:
    rows = read_csv(DATA / "test-growth.csv")
    figure, axis = plt.subplots(figsize=(6.5, 3.2))
    x = list(range(len(rows)))
    for slot, (key, label) in enumerate((("backend", "Backend"), ("frontend", "Frontend"), ("plugin", "Plugin"))):
        values = [int(row[key]) for row in rows]
        axis.plot(x, values, color=SLOTS[slot], linewidth=2, label=label)
        axis.annotate(f"{label} {values[-1]}", (x[-1], values[-1]), xytext=(4, 0), textcoords="offset points",
                      va="center", color=SECONDARY, fontsize=8)
    ticks = [index for index in range(len(rows)) if index == 0 or rows[index]["date"] != rows[index - 1]["date"]]
    axis.set_xticks(ticks, [rows[index]["date"][5:] for index in ticks], rotation=0, fontsize=7)
    axis.set_xlim(0, len(rows) + 8)
    axis.set_ylabel("Test functions in the source")
    axis.set_xlabel("Commits, oldest to newest (labelled with the first commit of each day)")
    axis.legend(loc="upper left")
    axis.grid(axis="x", visible=False)
    axis.set_title("Test functions defined, commit by commit")
    save(figure, "f02-test-growth")


def figure_phase() -> None:
    rows = read_csv(DATA / "test-register.csv")
    order = ["0", "1", "2", "3", "4", "5", "6", "H"]
    counts = Counter(row["phase"] for row in rows)
    labels = [p if p != "H" else "Hardening" for p in order if counts[p]]
    values = [counts[p] for p in order if counts[p]]
    figure, axis = plt.subplots(figsize=(6.5, 2.8))
    bars = axis.bar(labels, values, color=SLOTS[0], width=0.6, edgecolor=SURFACE, linewidth=1.5)
    for bar in bars:
        axis.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{int(bar.get_height())}",
                  ha="center", va="bottom", color=SECONDARY, fontsize=8)
    axis.set_xlabel("Phase whose commit introduced the test")
    axis.set_ylabel("Tests that ran")
    axis.grid(axis="x", visible=False)
    axis.set_title("Where the tests came from")
    save(figure, "f03-tests-by-phase")


def figure_coverage() -> None:
    rows = read_csv(DATA / "coverage-summary.csv")
    figure, axis = plt.subplots(figsize=(6.5, 0.5 * len(rows) + 1.2))
    names = [row["component"] for row in rows]
    y = list(range(len(rows)))
    height = 0.36
    statements = [float(row["statements_or_lines_pct"]) for row in rows]
    branches = [float(row["branches_pct"]) for row in rows]
    axis.barh([v + height / 2 for v in y], statements, height, color=SLOTS[0], label="Statements (lines for the plugin)",
              edgecolor=SURFACE, linewidth=1.5)
    axis.barh([v - height / 2 for v in y], branches, height, color=SLOTS[1], label="Branches", edgecolor=SURFACE, linewidth=1.5)
    for v, s, b in zip(y, statements, branches, strict=True):
        axis.text(s + 0.5, v + height / 2, f"{s:.1f}%", va="center", fontsize=8, color=SECONDARY)
        axis.text(b + 0.5, v - height / 2, f"{b:.1f}%", va="center", fontsize=8, color=SECONDARY)
    axis.set_yticks(y, names)
    axis.set_xlim(0, 110)
    axis.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.0f}%"))
    axis.legend(loc="lower right")
    axis.grid(axis="y", visible=False)
    axis.set_title("Structural coverage by component")
    save(figure, "f04-coverage")


def figure_mutation() -> None:
    rows = read_csv(DATA / "mutation-by-class.csv")
    rows.sort(key=lambda row: int(row["mutants"]))
    figure, axis = plt.subplots(figsize=(6.5, 0.36 * len(rows) + 1.0))
    names = [row["class"] for row in rows]
    killed = [int(row["killed"]) for row in rows]
    survived = [int(row["survived"]) for row in rows]
    axis.barh(names, killed, color=SLOTS[0], height=0.6, label="Killed (detected by a test)", edgecolor=SURFACE, linewidth=1.5)
    axis.barh(names, survived, left=killed, color=SLOTS[1], height=0.6, label="Survived (equivalent, see D-069)",
              edgecolor=SURFACE, linewidth=1.5)
    for index, (k, s) in enumerate(zip(killed, survived, strict=True)):
        axis.text(k + s, index, f"  {k}/{k + s}", va="center", fontsize=8, color=SECONDARY)
    axis.set_xlabel("Mutants")
    axis.legend(loc="lower right")
    axis.grid(axis="y", visible=False)
    axis.set_title("Mutation testing of the plugin's algorithms (PIT)")
    save(figure, "f05-mutation")


def figure_overhead() -> None:
    jenkins = read_csv(DATA / "experiments" / "scheduler-overhead-jenkins.csv")
    algorithm = read_csv(DATA / "experiments" / "scheduler-overhead-algorithm.csv")
    figure, (left, right) = plt.subplots(1, 2, figsize=(6.5, 3.0))
    n = [int(row["queued"]) for row in jenkins]
    for slot, (key, label) in enumerate((
        ("maintain_off_ms_median", "Queue maintenance, optimizer off"),
        ("maintain_on_ms_median", "Queue maintenance, optimizer on"),
        ("sort_cold_ms_median", "Scoring pass, empty cache"),
        ("sort_cached_ms_median", "Scoring pass, cached"),
    )):
        left.plot(n, [float(row[key]) for row in jenkins], color=SLOTS[slot], linewidth=2, marker="o", markersize=4, label=label)
    left.set_xscale("log")
    left.set_yscale("log")
    left.set_xlabel("Items in the Jenkins queue")
    left.set_ylabel("Median time (ms, log scale)")
    left.set_title("E1a: inside Jenkins")
    left.legend(loc="upper left", fontsize=7)
    sizes = [int(row["queued"]) for row in algorithm]
    micros = [float(row["score_sort_heap_us_median"]) for row in algorithm]
    right.plot(sizes, micros, color=SLOTS[0], linewidth=2, marker="o", markersize=4, label="Score, sort and heap")
    reference = [micros[-1] * size / sizes[-1] for size in sizes]
    right.plot(sizes, reference, color=MUTED, linewidth=1, label="Linear growth, for reference")
    right.set_xscale("log")
    right.set_yscale("log")
    right.set_xlabel("Items scored")
    right.set_ylabel("Median time (µs, log scale)")
    right.set_title("E1b: the algorithm alone")
    right.legend(loc="upper left", fontsize=7)
    figure.tight_layout()
    save(figure, "f06-scheduler-overhead")


def band_bars(axis: plt.Axes, rows: list[dict[str, str]], policies: list[tuple[str, str]], title: str) -> None:
    bands = [("high_mean_s", "HIGH"), ("medium_mean_s", "MEDIUM"), ("low_mean_s", "LOW")]
    width = 0.8 / len(policies)
    for slot, (policy, label) in enumerate(policies):
        row = next(r for r in rows if r["policy"] == policy)
        values = [float(row[key]) for key, _ in bands]
        positions = [index - 0.4 + width * (slot + 0.5) for index in range(len(bands))]
        axis.bar(positions, values, width, color=SLOTS[slot], label=label, edgecolor=SURFACE, linewidth=1.5)
    axis.set_xticks(range(len(bands)), [name for _, name in bands])
    axis.set_ylabel("Mean wait (s)")
    axis.grid(axis="x", visible=False)
    axis.set_title(title)


def figure_simulation() -> None:
    rows = read_csv(DATA / "experiments" / "simulation-m2-summary.csv")
    measured = [r for r in rows if r["source"] == "measured"]
    simulated_fifo = next(r for r in rows if r["policy"] == "FIFO" and r["executors"] == "1")
    replay = next(r for r in rows if r["policy"] == "REPLAY_M2_PLUGIN_ORDER")

    figure, axis = plt.subplots(figsize=(6.5, 2.9))
    bands = [("high_mean_s", "HIGH"), ("medium_mean_s", "MEDIUM"), ("low_mean_s", "LOW")]
    pairs = [
        (next(r for r in measured if r["policy"] == "M2_BASELINE_FIFO"), simulated_fifo, "FIFO"),
        (next(r for r in measured if r["policy"] == "M2_PLUGIN_RUN4"), replay, "M2 plugin order"),
    ]
    width = 0.2
    position = 0
    ticks, labels = [], []
    for real, model, name in pairs:
        for key, band in bands:
            axis.bar(position - width / 2, float(real[key]), width, color=SLOTS[0], edgecolor=SURFACE, linewidth=1.5,
                     label="Measured on Jenkins (Milestone 2)" if position == 0 else None)
            axis.bar(position + width / 2, float(model[key]), width, color=SLOTS[1], edgecolor=SURFACE, linewidth=1.5,
                     label="Simulated" if position == 0 else None)
            ticks.append(position)
            labels.append(f"{band}\n{name}")
            position += 1
        position += 0.5
    axis.set_xticks(ticks, labels, fontsize=7)
    axis.set_ylabel("Mean wait (s)")
    axis.legend(loc="upper center")
    axis.grid(axis="x", visible=False)
    axis.set_title("E2: the simulator against Milestone 2's measured runs")
    save(figure, "f07-simulator-validation")

    figure, (one, three) = plt.subplots(1, 2, figsize=(6.5, 3.0), sharey=False)
    policies = [("FIFO", "FIFO, no gate (stock Jenkins)"), ("URGENCY", "Static urgency, gated"),
                ("OPTIMIZER", "Version 2 optimizer, gated")]
    known = [r for r in rows if r["source"] == "simulated" and r["estimates"] in ("known", "-")]
    band_bars(one, [r for r in known if r["executors"] == "1"], policies, "One executor")
    band_bars(three, [r for r in known if r["executors"] == "3"], policies, "Three executors")
    one.legend(loc="upper left", fontsize=7)
    figure.suptitle("E2: Milestone 2's workload under three policies (simulated)", x=0.01, ha="left",
                    fontsize=10, fontweight="bold", color=INK)
    figure.tight_layout()
    save(figure, "f08-policies-m2-workload")


def figure_sustained() -> None:
    rows = read_csv(DATA / "experiments" / "simulation-sustained-load.csv")
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["policy"], row["utilisation"])].append(row)
    utilisations = sorted({row["utilisation"] for row in rows}, key=float)
    policies = [("FIFO", "FIFO"), ("URGENCY", "Static urgency"), ("OPTIMIZER", "Optimizer, with aging"),
                ("OPTIMIZER_NO_AGING", "Optimizer, aging off")]
    table = []
    figure, (high, low) = plt.subplots(1, 2, figsize=(6.5, 3.0))
    for slot, (policy, label) in enumerate(policies):
        for axis, key in ((high, "high_mean_s"), (low, "low_max_s")):
            means = [statistics.mean(float(r[key]) for r in grouped[(policy, u)]) for u in utilisations]
            spread = [statistics.stdev(float(r[key]) for r in grouped[(policy, u)]) for u in utilisations]
            axis.errorbar([float(u) for u in utilisations], means, yerr=spread, color=SLOTS[slot], linewidth=2 if slot != 3 else 1,
                          marker="o", markersize=4, capsize=2, label=label, linestyle="-")
        for u in utilisations:
            group = grouped[(policy, u)]
            table.append([policy, u, len(group)] + [
                round(statistics.mean(float(r[k]) for r in group), 1)
                for k in ("high_mean_s", "medium_mean_s", "low_mean_s", "low_p95_s", "low_max_s")
            ])
    high.set_title("HIGH band: mean wait")
    high.set_xlabel("Utilisation of the executor")
    high.set_ylabel("Seconds (mean of 10 seeds, ±1 sd)")
    low.set_title("LOW band: longest wait")
    low.set_xlabel("Utilisation of the executor")
    low.legend(loc="upper left", fontsize=7)
    figure.suptitle("E3: two hours of sustained load (simulated)", x=0.01, ha="left", fontsize=10, fontweight="bold", color=INK)
    figure.tight_layout()
    save(figure, "f09-sustained-load")
    write_csv("sustained-load-summary.csv",
              ["policy", "utilisation", "seeds", "high_mean_s", "medium_mean_s", "low_mean_s", "low_p95_s", "low_max_s"], table)


def figure_ci() -> None:
    rows = read_csv(DATA / "ci-runs.csv")
    by_day: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        by_day[row["date"]][row["conclusion"]] += 1
    days = sorted(by_day)
    figure, axis = plt.subplots(figsize=(6.5, 2.8))
    bottom = [0] * len(days)
    # Green and red fail the colour-vision check (deutan ΔE 4.1), so a failure is also hatched and
    # labelled with its count: print allows texture, and hue never carries the meaning alone.
    for conclusion, color, hatch, label in (("success", GOOD, "", "Passed"), ("failure", CRITICAL, "////", "Failed"),
                                            ("cancelled", MUTED, "", "Cancelled by a newer push")):
        values = [by_day[day][conclusion] for day in days]
        bars = axis.bar([day[5:] for day in days], values, bottom=bottom, color=color, width=0.6, label=label,
                        edgecolor=SURFACE, linewidth=1.5, hatch=hatch)
        if conclusion == "failure":
            for bar, value in zip(bars, values, strict=True):
                if value:
                    axis.text(bar.get_x() + bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                              f"{value} failed", va="center", fontsize=7, color=SECONDARY)
        bottom = [b + v for b, v in zip(bottom, values, strict=True)]
    axis.set_ylabel("CI runs")
    axis.legend(loc="upper left")
    axis.grid(axis="x", visible=False)
    total = Counter(row["conclusion"] for row in rows)
    axis.set_title(f"Continuous integration: {len(rows)} runs ({total['success']} passed, {total['failure']} failed)")
    save(figure, "f10-ci-history")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--ci", type=Path)
    args = parser.parse_args()
    style()

    test_growth()
    coverage(args.campaign)
    mutation(args.campaign)
    ci_history(args.ci)
    copy_experiments(args.campaign)

    for draw in (figure_suites, figure_growth, figure_phase, figure_coverage, figure_mutation, figure_overhead,
                 figure_simulation, figure_sustained, figure_ci):
        try:
            draw()
        except (FileNotFoundError, StopIteration, KeyError, ValueError) as missing:
            print(f"skipped {draw.__name__}: {missing!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
