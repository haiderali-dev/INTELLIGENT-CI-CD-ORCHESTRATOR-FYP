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

from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

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
        # Rows end in LF, as the repository stores text; the csv module's default is CRLF.
        writer = csv.writer(handle, lineterminator=chr(10))
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
    # Merges are left out: the recovery merges into main (PRs 5 to 7) carried trees from before the
    # later phases, so counting them would show tests vanishing and returning. Every other commit's
    # tree holds all the work before it on its branch.
    for line in git("log", "--reverse", "--no-merges", "--date-order", "--format=%H%x09%cI").splitlines():
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
    if rows:
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


def complexity(campaign: Path, lizard_csv: Path | None) -> None:
    """Cyclomatic complexity per function (lizard), with each function's own branch coverage where
    the coverage tool reports one: per function for the backend (coverage.py) and per method for the
    plugin (JaCoCo); per file for the frontend, and marked so."""
    if lizard_csv is None or not lizard_csv.is_file():
        return
    functions = []
    with lizard_csv.open(encoding="utf-8", errors="replace") as handle:
        for row in csv.reader(handle):
            # lizard --csv: NLOC, CCN, token, PARAM, length, location, file, function, long_name, start, end
            file = row[6].replace("\\", "/")
            component = "Plugin" if file.startswith("plugin/") else "Backend" if file.startswith("backend/") else "Frontend"
            functions.append({"component": component, "file": file, "name": row[7], "start": int(row[9]),
                              "end": int(row[10]), "ccn": int(row[1]), "nloc": int(row[0])})

    backend_json = campaign / "backend" / "backend-e2e-coverage.json"
    if not backend_json.is_file():
        backend_json = campaign / "backend" / "backend-offline-coverage.json"
    backend = json.loads(backend_json.read_text(encoding="utf-8"))["files"] if backend_json.is_file() else {}
    backend = {name.replace("\\", "/"): data for name, data in backend.items()}
    jacoco: dict[tuple[str, str], list[tuple[int, int, int]]] = defaultdict(list)
    report = campaign / "plugin" / "jacoco.xml"
    if report.is_file():
        root = ElementTree.parse(report).getroot()  # noqa: S314 (JaCoCo's own report)
        for cls in root.iter("class"):
            simple = cls.get("name", "").split("/")[-1].split("$")[-1]
            for method in cls.iter("method"):
                counters = {c.get("type"): c for c in method.findall("counter")}
                branch = counters.get("BRANCH")
                missed, covered = (int(branch.get("missed")), int(branch.get("covered"))) if branch is not None else (0, 0)
                jacoco[(simple, method.get("name", ""))].append((int(method.get("line") or 0), missed, covered))
    frontend_summary = campaign / "frontend" / "coverage-summary.json"
    frontend = json.loads(frontend_summary.read_text(encoding="utf-8")) if frontend_summary.is_file() else {}
    frontend = {name.replace("\\", "/").split("/frontend/")[-1]: data for name, data in frontend.items()}

    def coverage_of(function: dict) -> tuple[str, str]:
        """(branch coverage %, how it was measured)."""
        if function["component"] == "Backend":
            data = backend.get(function["file"].removeprefix("backend/"))
            if data:
                for name, summary in data.get("functions", {}).items():
                    lines = set(summary.get("executed_lines", [])) | set(summary.get("missing_lines", []))
                    if name.split(".")[-1] == function["name"] and lines & set(range(function["start"], function["end"] + 1)):
                        s = summary["summary"]
                        if not s.get("num_branches"):
                            return "no branches", "function"
                        return f"{100 * s['covered_branches'] / s['num_branches']:.0f}", "function"
        if function["component"] == "Plugin":
            simple, _, method = function["name"].rpartition("::")
            candidates = jacoco.get((simple.split("::")[-1], method), [])
            if candidates:
                line, missed, covered = min(candidates, key=lambda c: abs(c[0] - function["start"]))
                if missed + covered == 0:
                    return "no branches", "method"
                return f"{100 * covered / (missed + covered):.0f}", "method"
        if function["component"] == "Frontend":
            data = frontend.get(function["file"].removeprefix("frontend/"))
            if data:
                return f"{data['branches']['pct']:.0f}", "file"
        return "not measured", "-"

    summary_rows = []
    top_rows = []
    all_rows = []
    for component in ("Plugin", "Backend", "Frontend"):
        group = [f for f in functions if f["component"] == component]
        if not group:
            continue
        values = [f["ccn"] for f in group]
        summary_rows.append([component, len(group), round(statistics.mean(values), 2), statistics.median(values),
                             max(values), sum(v > 10 for v in values), sum(v > 15 for v in values)])
        for function in sorted(group, key=lambda f: (-f["ccn"], f["file"])):
            percent, basis = coverage_of(function)
            row = [component, function["name"], f"{function['file']}:{function['start']}", function["ccn"],
                   function["nloc"], percent, basis]
            all_rows.append(row)
            if len([r for r in top_rows if r[0] == component]) < 10:
                top_rows.append(row)
    header = ["component", "function", "where", "ccn", "nloc", "branch_coverage_pct", "coverage_measured_per"]
    write_csv("complexity-summary.csv", ["component", "functions", "mean_ccn", "median_ccn", "max_ccn",
                                         "over_10", "over_15"], summary_rows)
    write_csv("complexity-top.csv", header, top_rows)
    write_csv("complexity-all.csv", header, all_rows)


def m2_runs() -> list[list[object]]:
    """Every stored Milestone 2 run, recomputed from its raw result file (legacy/, read only): the
    same waits as docs/m2-baseline.md, plus the dependency edges each run broke, which it never
    measured. An edge is broken when a job started before a job it depends on had finished."""
    folder = REPO_ROOT / "legacy" / "m2-poc" / "experiment"
    spec = {job["name"]: job for job in json.loads((folder / "scripts" / "jobs.json").read_text(encoding="utf-8"))}
    edges = [(up, job["name"]) for job in spec.values() for up in job["dependsOn"]]
    rows = []
    for label, name in (("Baseline (stock Jenkins, FIFO)", "baseline-results.json"),
                        ("Plugin, run 1", "plugin-results.json"), ("Plugin, run 2", "plugin-results-run2.json"),
                        ("Plugin, run 3", "plugin-results-run3.json"), ("Plugin, run 4 (the report's)", "plugin-results-run4.json")):
        result = json.loads((folder / "results" / name).read_text(encoding="utf-8"))
        t0 = result["t0"]
        # The baseline's leftover 31st job is not in the workload (docs/m2-baseline.md 4.2).
        runs = {job["name"]: ((job["startTime"] - t0) / 1000, (job["startTime"] - t0 + job["duration"]) / 1000)
                for job in result["jobs"] if job["name"] in spec}
        waits = {level: [runs[n][0] for n in runs if spec[n]["priority"] == level] for level in ("HIGH", "MEDIUM", "LOW")}
        broken = sum(1 for up, down in edges if up in runs and down in runs and runs[down][0] < runs[up][1])
        rows.append([label, name, len(runs), round(max(end for _, end in runs.values()), 2),
                     round(statistics.mean(start for start, _ in runs.values()), 2),
                     *(round(statistics.mean(waits[level]), 2) for level in ("HIGH", "MEDIUM", "LOW")), broken, len(edges)])
    write_csv("m2-runs.csv", ["run", "file", "jobs", "makespan_s", "mean_wait_s", "high_mean_s", "medium_mean_s",
                              "low_mean_s", "dependency_violations", "dependency_edges"], rows)
    return rows


def figure_m2() -> None:
    rows = read_csv(DATA / "m2-runs.csv")
    figure, (waits, broken) = plt.subplots(1, 2, figsize=(6.5, 3.0), gridspec_kw={"width_ratios": [2.2, 1]})
    labels = ["FIFO", "Run 1", "Run 2", "Run 3", "Run 4"]
    width = 0.26
    for slot, (key, band) in enumerate((("high_mean_s", "HIGH"), ("medium_mean_s", "MEDIUM"), ("low_mean_s", "LOW"))):
        waits.bar([index + (slot - 1) * width for index in range(len(rows))], [float(row[key]) for row in rows], width,
                  color=SLOTS[slot], label=band, edgecolor=SURFACE, linewidth=1.2)
    waits.set_xticks(range(len(rows)), labels)
    waits.set_ylabel("Mean wait (s)")
    waits.set_ylim(0, max(float(row[key]) for row in rows for key in ("high_mean_s", "medium_mean_s", "low_mean_s")) * 1.18)
    waits.legend(loc="upper left", ncols=3, fontsize=7)
    waits.grid(axis="x", visible=False)
    waits.set_title("Waits by band")
    values = [int(row["dependency_violations"]) for row in rows]
    bars = broken.bar(labels, values, color=SLOTS[0], width=0.6, edgecolor=SURFACE, linewidth=1.2)
    for bar, value in zip(bars, values, strict=True):
        broken.text(bar.get_x() + bar.get_width() / 2, value, f"{value}", ha="center", va="bottom", fontsize=8, color=SECONDARY)
    broken.set_ylabel(f"Edges broken (of {rows[0]['dependency_edges']})")
    broken.yaxis.set_major_locator(MaxNLocator(integer=True))
    broken.grid(axis="x", visible=False)
    broken.set_title("Dependency order broken")
    broken.tick_params(axis="x", labelsize=7)
    figure.suptitle("Milestone 2's measured runs, recomputed from its result files", x=0.01, ha="left", fontsize=10,
                    fontweight="bold", color=INK)
    figure.tight_layout()
    save(figure, "f12-m2-runs")


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
    when = [datetime.fromisoformat(row["date"]) for row in rows]
    for slot, (key, label) in enumerate((("backend", "Backend"), ("frontend", "Frontend"), ("plugin", "Plugin"))):
        values = [int(row[key]) for row in rows]
        axis.step(when, values, where="post", color=SLOTS[slot], linewidth=2, label=label)
        axis.annotate(f"{label} {values[-1]}", (when[-1], values[-1]), xytext=(4, 0), textcoords="offset points",
                      va="center", color=SECONDARY, fontsize=8)
    axis.xaxis.set_major_locator(mdates.DayLocator(interval=3))
    axis.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    axis.set_xlim(when[0], when[-1] + (when[-1] - when[0]) * 0.12)
    axis.set_ylabel("Test functions in the source")
    axis.set_xlabel("Commit date (merge commits left out)")
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


# How each defect was found, folded from defects.csv's free-text level into the techniques of
# Pressman and Maxim's strategy (chapter 8.2), in the order the chapter discusses them.
TECHNIQUES = (
    ("Unit", "Unit testing"),
    ("Integration", "Integration testing"),
    ("System", "System testing"),
    ("Acceptance", "Acceptance testing"),
    ("Regression", "Regression (CI and gates)"),
    ("Coverage", "Coverage analysis"),
    ("", "Review and inspection"),
)


def technique(level: str) -> str:
    return next(name for prefix, name in TECHNIQUES if level.startswith(prefix))


def defects() -> list[list[object]]:
    rows = read_csv(DATA / "defects.csv")
    found = Counter(technique(row["level"]) for row in rows)
    phases = Counter(row["phase"] for row in rows)
    # Every phase 0 to 6, a phase with none included, then any defect that spans phases.
    order = [str(n) for n in range(7)] + sorted(p for p in phases if not p.isdigit())
    summary = [["technique", name, found[name]] for _, name in TECHNIQUES]
    summary += [["phase", phase, phases[phase]] for phase in order]
    write_csv("defects-summary.csv", ["by", "group", "defects"], summary)
    return summary


def figure_defects() -> None:
    rows = read_csv(DATA / "defects-summary.csv")
    found = [row for row in rows if row["by"] == "technique" and int(row["defects"])]
    phases = [row for row in rows if row["by"] == "phase"]
    figure, (left, right) = plt.subplots(1, 2, figsize=(6.5, 3.0), gridspec_kw={"width_ratios": [1.5, 1]})
    names = [row["group"] for row in found][::-1]
    values = [int(row["defects"]) for row in found][::-1]
    bars = left.barh(names, values, color=SLOTS[0], height=0.6, edgecolor=SURFACE, linewidth=1.2)
    for bar, value in zip(bars, values, strict=True):
        left.text(value, bar.get_y() + bar.get_height() / 2, f" {value}", va="center", fontsize=8, color=SECONDARY)
    left.set_xlabel("Defects")
    left.grid(axis="y", visible=False)
    left.set_title("How each was found")
    labels = [row["group"].replace("-", " to ") for row in phases]
    counts = [int(row["defects"]) for row in phases]
    bars = right.bar(labels, counts, color=SLOTS[0], width=0.6, edgecolor=SURFACE, linewidth=1.2)
    for bar, value in zip(bars, counts, strict=True):
        right.text(bar.get_x() + bar.get_width() / 2, value, f"{value}", ha="center", va="bottom", fontsize=8,
                   color=SECONDARY)
    right.set_xlabel("Phase of the defective work")
    right.yaxis.set_major_locator(MaxNLocator(integer=True))
    right.grid(axis="x", visible=False)
    right.set_title("Where it was")
    right.tick_params(axis="x", labelsize=7)
    figure.suptitle(f"The {sum(counts)} defects testing and review found", x=0.01, ha="left", fontsize=10,
                    fontweight="bold", color=INK)
    figure.tight_layout()
    save(figure, "f13-defects")


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


def figure_complexity() -> None:
    rows = [r for r in read_csv(DATA / "complexity-all.csv")
            if r["component"] in ("Plugin", "Backend") and r["branch_coverage_pct"].isdigit()]
    figure, axis = plt.subplots(figsize=(6.5, 3.4))
    for slot, component in enumerate(("Backend", "Plugin")):
        group = [r for r in rows if r["component"] == component]
        axis.scatter([int(r["ccn"]) for r in group], [int(r["branch_coverage_pct"]) for r in group], s=18,
                     color=SLOTS[slot], edgecolors=SURFACE, linewidths=0.8, label=f"{component} ({len(group)} functions with branches)",
                     alpha=0.85, zorder=3)
    risky = [r for r in rows if int(r["ccn"]) > 10 and int(r["branch_coverage_pct"]) < 80]
    for r in risky:
        axis.annotate(r["function"].split("::")[-1], (int(r["ccn"]), int(r["branch_coverage_pct"])), xytext=(4, -3),
                      textcoords="offset points", fontsize=7, color=SECONDARY)
    axis.axvline(10, color=AXIS, linewidth=0.8, zorder=1)
    axis.set_xlabel("Cyclomatic complexity of the function (lizard)")
    axis.set_ylabel("Its branches covered (%)")
    axis.set_ylim(-3, 105)
    axis.legend(loc="lower right")
    axis.set_title("Complexity against branch coverage, per function")
    save(figure, "f11-complexity-coverage")


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
    axis.legend(loc="upper right")
    axis.grid(axis="x", visible=False)
    total = Counter(row["conclusion"] for row in rows)
    axis.set_title(f"Continuous integration: {len(rows)} runs ({total['success']} passed, {total['failure']} failed)")
    save(figure, "f10-ci-history")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--ci", type=Path)
    parser.add_argument("--complexity", type=Path, help="lizard's --csv output for the three components' main code")
    args = parser.parse_args()
    style()

    test_growth()
    coverage(args.campaign)
    mutation(args.campaign)
    ci_history(args.ci)
    complexity(args.campaign, args.complexity)
    m2_runs()
    defects()
    copy_experiments(args.campaign)

    for draw in (figure_suites, figure_growth, figure_phase, figure_coverage, figure_mutation, figure_overhead,
                 figure_simulation, figure_sustained, figure_ci, figure_complexity, figure_m2, figure_defects):
        try:
            draw()
        except (FileNotFoundError, StopIteration, KeyError, ValueError) as missing:
            print(f"skipped {draw.__name__}: {missing!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
