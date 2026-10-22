"""Annexure A of the testing chapter: the evidence, rendered from the files the runs wrote.

    python scripts/report/testing_annexure.py .tmp/campaign/<commit> --gate <gate log> [--system .tmp/system]

Every table here is read from a file a run produced: the campaign's manifest and reports, the gate's
log, the CI history, the experiments' CSVs, the load and recovery reports, and the defect log. The
chapter cites these tables; nothing in them is typed by hand except the equivalence argument for
each surviving mutant, which is reasoning about code, and is marked as such.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "docs" / "testing"
DATA = DOCS / "data"
CI_URL = "https://github.com/haiderali-dev/INTELLIGENT-CI-CD-ORCHESTRATOR-FYP/actions/runs/{run}"

# Why each surviving mutant is equivalent: reasoning about the code, not a measurement (D-069).
EQUIVALENT = {
    ("PriorityScoreCalculator", "agingBonus"): "A wait of exactly 0 earns 0 either way: with `< 0`, it goes on to compute 0 intervals.",
    ("PriorityScoreCalculator", "dependencyFactor"): "A group of one scores 0 either way, and the largest group is never smaller than any group.",
    ("PriorityScoreCalculator", "applyGroupInheritance"): "A group of one, or a member already at the group's best, gives an identical result.",
    ("PriorityScoreCalculator", "scoreAll"): "`anyKnown` only matters when an estimate is absent, and then the factor is 0.5 anyway.",
    ("UnionFind", "union"): "Union by rank decides which root goes under the other; any choice joins the same elements. Only the trees' height changes.",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def table(header: list[str], rows: list[list[object]], align: list[str] | None = None) -> list[str]:
    align = align or ["---"] * len(header)
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(align) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in row) + " |")
    return lines + [""]


def section_environment(manifest: dict) -> list[str]:
    machine = manifest["machine"]
    lines = ["## A.1 The test environment", ""]
    lines += table(["Item", "Value"], [
        ["Commit", f"`{manifest['commit'][:7]}` (`{manifest['commit']}`)"],
        ["Branch", manifest["branch"]],
        ["Campaign manifest written", manifest["written"]],
        ["Machine", f"Windows 11 Pro, {machine['processors']} logical processors"],
        ["Python running the campaign", machine["python"]],
        ["Versions of every tool", "`docs/versions.md`; Table 8.2"],
    ])
    return lines


def section_campaign(manifest: dict) -> list[str]:
    lines = ["## A.2 The evidence campaign, step by step", "",
             "Each step's command, start time, duration and exit code, from `manifest.json`. Logs and "
             "reports were kept under `.tmp/campaign/<commit>/`; the per-test results are Annexure B.", ""]
    rows = []
    for step in manifest["steps"]:
        rows.append([step["name"], f"`{' '.join(Path(part).name if '/' in part or '\\\\' in part else part for part in step['command'])[:110]}`",
                     step["started"].replace("T", " ").replace("+00:00", " UTC"), step["seconds"], step["exit_code"], step.get("note", "")])
    lines += table(["Step", "Command", "Started", "Seconds", "Exit", "Note"], rows, ["---", "---", "---", "---:", "---:", "---"])
    return lines


def section_gate(gate: Path) -> list[str]:
    text = gate.read_text(encoding="utf-8", errors="replace")
    lines = ["## A.3 The acceptance gate", ""]
    head = text.splitlines()[0] if text else ""
    summary = [line for line in text.splitlines() if line.strip() in ("ALL CHECKS PASSED",) or line.endswith("CHECKS FAILED")]
    lines += [f"`python scripts/verify.py --phase 6`: {head.strip()}. Result: **{summary[-1] if summary else 'not finished'}**.", ""]
    rows, phase = [], "0"
    all_lines = text.splitlines()
    for index, line in enumerate(all_lines):
        heading = re.match(r"-- phase (\d) -", line)
        if heading:
            phase = heading.group(1)
        verdict = re.match(r"\[(PASS|FAIL)\] (.+)$", line)
        if verdict:
            detail = all_lines[index + 1].strip() if index + 1 < len(all_lines) else ""
            rows.append([phase, verdict.group(2), verdict.group(1), detail])
    lines += table(["Phase", "Check", "Result", "What it reported"], rows)
    return lines


def section_ci() -> list[str]:
    path = DATA / "ci-runs.csv"
    if not path.is_file():
        return []
    rows = read_csv(path)
    counts = Counter(row["conclusion"] for row in rows)
    lines = ["## A.4 Continuous integration", "",
             f"{len(rows)} runs of `.github/workflows/ci.yml` between {rows[0]['date']} and {rows[-1]['date']}: "
             f"{counts['success']} passed, {counts['failure']} failed, {counts['cancelled']} cancelled by a newer push. "
             "Each failure is in the defect log (A.10).", ""]
    lines += table(["Run", "Date", "Branch", "Commit", "Event", "Result"],
                   [[f"[{row['run']}]({CI_URL.format(run=row['run'])})", row["date"], row["branch"], f"`{row['commit']}`",
                     row["event"], row["conclusion"]] for row in rows])
    return lines


def section_coverage(campaign: Path) -> list[str]:
    lines = ["## A.5 Coverage by module", ""]
    summary = DATA / "coverage-summary.csv"
    if summary.is_file():
        lines += table(["Component", "Statements or lines (%)", "Branches (%)"],
                       [[r["component"], r["statements_or_lines_pct"], r["branches_pct"]] for r in read_csv(summary)])
    jacoco = campaign / "plugin" / "jacoco.csv"
    if jacoco.is_file():
        rows = []
        for row in read_csv(jacoco):
            lm, lc = int(row["LINE_MISSED"]), int(row["LINE_COVERED"])
            bm, bc = int(row["BRANCH_MISSED"]), int(row["BRANCH_COVERED"])
            rows.append([f"{row['PACKAGE'].replace('io.jenkins.plugins.queueoptimizer.', '')}.{row['CLASS']}",
                         lc + lm, f"{100 * lc / (lc + lm):.1f}" if lc + lm else "-", bc + bm,
                         f"{100 * bc / (bc + bm):.1f}" if bc + bm else "-"])
        lines += ["### The plugin (JaCoCo, unit and integration tests)", ""]
        lines += table(["Class", "Lines", "Lines covered (%)", "Branches", "Branches covered (%)"], sorted(rows),
                       ["---", "---:", "---:", "---:", "---:"])
    for name, title in (("backend-offline-coverage.json", "The backend, offline suite"),
                        ("backend-e2e-coverage.json", "The backend, offline, integration and end-to-end suites together")):
        path = campaign / "backend" / name
        if not path.is_file():
            continue
        files = json.loads(path.read_text(encoding="utf-8"))["files"]
        rows = []
        for file, data in sorted(files.items()):
            s = data["summary"]
            rows.append([f"`{file.replace(chr(92), '/')}`", s["num_statements"], f"{s['percent_covered']:.1f}",
                         s.get("num_branches", 0), s.get("covered_branches", 0)])
        lines += [f"### {title} (coverage.py, statements and branches)", ""]
        lines += table(["Module", "Statements", "Covered (%)", "Branches", "Branches covered"], rows,
                       ["---", "---:", "---:", "---:", "---:"])
    frontend = campaign / "frontend" / "coverage-summary.json"
    if frontend.is_file():
        data = json.loads(frontend.read_text(encoding="utf-8"))
        rows = []
        for file, value in sorted(data.items()):
            if file == "total":
                continue
            short = file.replace("\\", "/").split("/frontend/")[-1]
            rows.append([f"`{short}`", value["statements"]["total"], value["statements"]["pct"], value["branches"]["total"], value["branches"]["pct"]])
        lines += ["### The frontend (V8, unit and component tests)", ""]
        lines += table(["File", "Statements", "Covered (%)", "Branches", "Branches covered (%)"], rows,
                       ["---", "---:", "---:", "---:", "---:"])
    return lines


def section_mutation(campaign: Path) -> list[str]:
    report = campaign / "plugin-mutation" / "mutations.xml"
    if not report.is_file():
        return []
    root = ElementTree.parse(report).getroot()  # noqa: S314 (PIT's own report)
    mutants = list(root.iter("mutation"))
    counts = Counter(m.get("status") for m in mutants)
    killed = counts["KILLED"] + counts["TIMED_OUT"] + counts["MEMORY_ERROR"]
    lines = ["## A.6 Mutation testing", "",
             f"PIT, through the plugin's `mutation` profile: {len(mutants)} mutants, {killed} killed "
             f"({counts['KILLED']} by a failing assertion, {counts['TIMED_OUT']} by a timeout, "
             f"{counts['MEMORY_ERROR']} by exhausting memory), {counts['SURVIVED']} survived, "
             f"{counts['NO_COVERAGE']} not covered by any test.", ""]
    by_class = DATA / "mutation-by-class.csv"
    if by_class.is_file():
        lines += table(["Class", "Mutants", "Killed", "Survived", "No coverage"],
                       [[r["class"], r["mutants"], r["killed"], r["survived"], r["no_coverage"]] for r in read_csv(by_class)],
                       ["---", "---:", "---:", "---:", "---:"])
    survivors = []
    for mutant in mutants:
        if mutant.get("status") != "SURVIVED":
            continue
        cls = mutant.findtext("mutatedClass", "").split(".")[-1]
        method = mutant.findtext("mutatedMethod", "")
        survivors.append([cls, method, mutant.findtext("lineNumber"), mutant.findtext("mutator", "").split(".")[-1],
                          mutant.findtext("description"), EQUIVALENT.get((cls, method), "**Not yet classified**")])
    lines += ["### Every surviving mutant, and why it is equivalent", "",
              "The last column is reasoning about the code (D-069), not a measurement.", ""]
    lines += table(["Class", "Method", "Line", "Mutator", "Change", "Why no test can tell it apart"], survivors)
    return lines


def section_experiments() -> list[str]:
    folder = DATA / "experiments"
    lines = ["## A.7 Experiment data", ""]
    for name, title in (
        ("scheduler-overhead-jenkins.csv", "E1a: inside Jenkins (milliseconds, median and 90th percentile of 25 runs)"),
        ("scheduler-overhead-algorithm.csv", "E1b: the algorithm alone (microseconds, median and 90th percentile of 101 runs)"),
        ("simulation-m2-calibration.csv", "E2: calibration on Milestone 2's measured FIFO run"),
        ("simulation-m2-summary.csv", "E2: Milestone 2's workload, measured and simulated (seconds)"),
    ):
        path = folder / name
        if not path.is_file():
            continue
        rows = read_csv(path)
        lines += [f"### {title}", f"Source: `docs/testing/data/experiments/{name}`.", ""]
        lines += table(list(rows[0].keys()), [list(row.values()) for row in rows])
        about = folder / name.replace(".csv", ".environment.txt")
        if about.is_file():
            lines += ["Measured on: " + "; ".join(about.read_text(encoding="utf-8").split()), ""]
    summary = DATA / "sustained-load-summary.csv"
    if summary.is_file():
        rows = read_csv(summary)
        lines += ["### E3: two hours of sustained load (means of 10 seeds, seconds)",
                  "Per-seed rows: `docs/testing/data/experiments/simulation-sustained-load.csv`.", ""]
        lines += table(list(rows[0].keys()), [list(row.values()) for row in rows])
    return lines


def section_system(system: Path | None) -> list[str]:
    lines = ["## A.8 Load and recovery tests", ""]
    if system is None:
        return lines + ["Not run.", ""]
    load = system / "load-test.json"
    if load.is_file():
        report = json.loads(load.read_text(encoding="utf-8"))
        rows = []
        for level in report["levels"]:
            rows.append([f"{level['users']} users, paced", level["all"]["requests"], level["throughput_rps"],
                         level["all"]["p50_ms"], level["all"]["p95_ms"], level["all"]["max_ms"],
                         ", ".join(f"{k}: {v}" for k, v in sorted(level["all"]["statuses"].items()))])
        stress = report["stress"]
        rows.append([f"1 user, {stress['threads']} threads at once", stress["all"]["requests"], stress["throughput_rps"],
                     stress["all"]["p50_ms"], stress["all"]["p95_ms"], stress["all"]["max_ms"],
                     ", ".join(f"{k}: {v}" for k, v in sorted(stress["all"]["statuses"].items()))])
        lines += ["### Load and stress (`scripts/system_load_test.py`)", ""]
        lines += table(["Run", "Requests", "Per second", "p50 (ms)", "p95 (ms)", "Max (ms)", "Statuses"], rows,
                       ["---", "---:", "---:", "---:", "---:", "---:", "---"])
        per_endpoint = []
        for level in report["levels"]:
            for endpoint, stats in level.items():
                if endpoint.startswith("/api/"):
                    per_endpoint.append([level["users"], f"`{endpoint}`", stats["requests"], stats["p50_ms"], stats["p95_ms"], stats["max_ms"]])
        lines += table(["Users", "Endpoint", "Requests", "p50 (ms)", "p95 (ms)", "Max (ms)"], per_endpoint,
                       ["---:", "---", "---:", "---:", "---:", "---:"])
    recovery = system / "recovery-test.json"
    if recovery.is_file():
        steps = json.loads(recovery.read_text(encoding="utf-8"))["steps"]
        lines += ["### Recovery (`scripts/recovery_test.py`)", ""]
        for step in steps:
            lines += [f"**{step['restarted']}**: " + "; ".join(f"{k.replace('_', ' ')} {v}" for k, v in step.items() if k != "restarted"), ""]
    return lines


def section_screenshots() -> list[str]:
    shots = sorted((REPO_ROOT / "docs" / "screenshots").glob("*.png"))
    lines = ["## A.9 Screenshots", "",
             f"{len(shots)} screenshots, made by Playwright from the production build (T6.9, retaken 2026-10-20), "
             "every screen at 1440 and 390 pixels in the light and dark themes. Selected screens:", ""]
    for name in ("queue-1440-light", "jobs-and-runs-1440-light", "pipeline-assistant-1440-dark", "admin-390-light"):
        if (REPO_ROOT / "docs" / "screenshots" / f"{name}.png").is_file():
            lines += [f"![{name}](../screenshots/{name}.png)", ""]
    lines += table(["File"], [[f"`docs/screenshots/{shot.name}`"] for shot in shots])
    return lines


def section_lighthouse(campaign: Path) -> list[str]:
    log = campaign / "logs" / "lighthouse.log"
    if not log.is_file():
        return []
    scores = re.findall(r"^((?:freestyle|pipeline)-[\w-]+): (\d+)\s*$", log.read_text(encoding="utf-8", errors="replace"), re.M)
    lines = ["### Lighthouse accessibility, both assistant pages", ""]
    lines += table(["Page, state, width, theme", "Accessibility score"], [[page, score] for page, score in scores], ["---", "---:"])
    return lines


def section_defects() -> list[str]:
    rows = read_csv(DATA / "defects.csv")
    lines = ["## A.10 Defect log", "",
             f"{len(rows)} defects found by testing, review or analysis, each with its evidence and the commit "
             "that fixed it. Source: `docs/testing/data/defects.csv`.", ""]
    lines += table(["ID", "Found", "Phase", "Defect", "Found by", "Evidence", "Record", "Fixed in"],
                   [[r["id"], r["found"], r["phase"], r["defect"], r["found_by"], r["evidence"], r["record"], r["fixed_in"]] for r in rows])
    return lines


def section_security() -> list[str]:
    return ["## A.11 Security reviews", "",
            "- `docs/security-review-phases-3-5-6.md`: the independent review of Phases 3, 5 and 6 (2026-10-18). "
            "15 findings (2 Medium, 7 Low, 6 Info), each with its fix and regression test, and the residual risks accepted.",
            "- `docs/security-review-phase-5.md`: the review of Phase 5 (2026-10-13). Not independent, as it records. "
            "Six findings and one found by a finding's own tests.", ""]


def section_dependency_scans(campaign: Path) -> list[str]:
    """Known vulnerabilities in the dependencies: pip-audit's reports for the backend (D-071) and
    npm audit's, which the campaign's frontend-audit step keeps as its log."""
    lines = ["## A.12 Known-vulnerability scans of the dependencies", ""]
    rows = []
    for label, name in (("Backend, before D-071", "pip-audit-backend-before.json"),
                        ("Backend, after D-071", "pip-audit-backend-after.json")):
        path = DOCS / "evidence" / name
        if path.is_file():
            report = json.loads(path.read_text(encoding="utf-8"))
            found = [f"{dep['name']} {dep['version']}: {vuln['id']}" for dep in report["dependencies"] for vuln in dep.get("vulns", [])]
            rows.append([label, "pip-audit 2.10.1", len(report["dependencies"]), len(found), "; ".join(found) or "none",
                         f"`docs/testing/evidence/{name}`"])
    log = campaign / "logs" / "frontend-audit.log"
    if log.is_file():
        text = log.read_text(encoding="utf-8", errors="replace").split("--- stderr ---")[0]
        try:
            audit = json.loads(text)
            meta = audit.get("metadata", {})
            counts = meta.get("vulnerabilities", {})
            total = sum(v for k, v in counts.items() if k != "total") if counts else 0
            packages = meta.get("dependencies", {}).get("total", "")
            rows.append(["Frontend, production and tools", "npm audit", packages, total,
                         ", ".join(f"{k} {v}" for k, v in counts.items() if v and k != "total") or "none",
                         "the campaign's `logs/frontend-audit.log`"])
        except json.JSONDecodeError:
            rows.append(["Frontend", "npm audit", "", "", "its report did not parse", "the campaign's log"])
    lines += table(["Scope", "Tool", "Packages", "Known vulnerabilities", "Which", "Report"], rows)
    lines += ["", "The plugin bundles no third-party library: its `.hpi` holds only its own jar.", ""]
    return lines


def section_complexity() -> list[str]:
    summary, top = DATA / "complexity-summary.csv", DATA / "complexity-top.csv"
    if not summary.is_file() or not top.is_file():
        return []
    lines = ["## A.13 Cyclomatic complexity", "",
             "Measured with lizard 1.24.1 over each component's own code, tests excluded. Branch coverage is "
             "per function for the backend (coverage.py) and per method for the plugin (JaCoCo); the frontend's is "
             "per file, as V8 reports it. Sources: `docs/testing/data/complexity-*.csv`.", ""]
    lines += table(["Component", "Functions", "Mean", "Median", "Highest", "Over 10", "Over 15"],
                   [[r["component"], r["functions"], r["mean_ccn"], r["median_ccn"], r["max_ccn"], r["over_10"], r["over_15"]]
                    for r in read_csv(summary)])
    lines += ["", "The ten most complex functions of each component:", ""]
    lines += table(["Component", "Function", "Where", "CCN", "Lines", "Branches covered (%)", "Measured per"],
                   [[r["component"], f"`{r['function']}`", f"`{r['where']}`", r["ccn"], r["nloc"],
                     r["branch_coverage_pct"], r["coverage_measured_per"]] for r in read_csv(top)])
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--gate", type=Path, required=True)
    parser.add_argument("--system", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.campaign / "manifest.json").read_text(encoding="utf-8"))

    lines = ["# Annexure A: test evidence", "",
             f"The evidence behind Chapter 8, generated by `scripts/report/testing_annexure.py` from the evidence "
             f"campaign at commit `{manifest['commit'][:7]}`, the gate's log and the files listed in each section. "
             "Annexure B lists every test that ran.", ""]
    for section in (section_environment(manifest), section_campaign(manifest), section_gate(args.gate), section_ci(),
                    section_coverage(args.campaign), section_mutation(args.campaign), section_experiments(),
                    section_system(args.system), section_screenshots(), section_lighthouse(args.campaign),
                    section_defects(), section_security(), section_dependency_scans(args.campaign),
                    section_complexity()):
        lines += section
    # newline: LF, as the repository stores text; text mode on Windows would write CRLF.
    (DOCS / "annexure-a-evidence.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {DOCS / 'annexure-a-evidence.md'} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
