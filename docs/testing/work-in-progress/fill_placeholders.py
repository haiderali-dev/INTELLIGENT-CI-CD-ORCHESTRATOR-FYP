"""Fill the chapter draft's data placeholders from the files the runs wrote.

    fill_placeholders.py <draft.md> <out.md> <campaign dir> <system dir> <values.json>

Every number comes from a file: the campaign's reports, the register the register builder wrote,
the load and recovery reports, the OpenAPI schema. values.json carries the few values read by hand
from a named log (gate, CI). A placeholder this script does not know is left for the hand.
"""

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

draft, out, campaign, system, values_file = (Path(a) for a in sys.argv[1:6])
REPO = Path(__file__).resolve().parents[0]
values = json.loads(values_file.read_text(encoding="utf-8"))
repo = Path(values["repo"])
DATA = repo / "docs" / "testing" / "data"
LF = chr(10)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def table(header: list[str], rows: list[list[object]], align: list[str] | None = None) -> str:
    align = align or ["---"] * len(header)
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(align) + " |"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return LF.join(lines)


def pct(covered: float, total: float) -> str:
    return f"{100 * covered / total:.1f}%" if total else "n/a"


# --- The register's suites ------------------------------------------------------------------------
summary = read_csv(DATA / "test-register-summary.csv")
by_suite = {row["suite"]: row for row in summary}


def suite(name: str) -> dict[str, str]:
    for key, row in by_suite.items():
        if key.startswith(name):
            return row
    raise KeyError(name)


def outcome(row: dict[str, str]) -> str:
    parts = [f"{row['passed']} passed"]
    for key in ("failed", "error", "skipped"):
        if int(row[key]):
            parts.append(f"{row[key]} {key}")
    return ", ".join(parts)


filled: dict[str, str] = dict(values["literal"])

# --- The gate run the chapter cites, read from its log ---------------------------------------------
gate_log = repo / values["gate_log"]
gate_lines = gate_log.read_text(encoding="utf-8", errors="replace").splitlines()
gate_run = re.match(r"gate-run-(\d+)-([0-9a-f]{7})", gate_log.name)
assert gate_run, f"not a gate log's name: {gate_log.name}"
assert any(line.strip() == "ALL CHECKS PASSED" for line in gate_lines) and not any(line.startswith("[FAIL]") for line in gate_lines), \
    f"{gate_log.name} did not pass, so the chapter cannot cite it"


def gate_detail(check: str) -> str:
    return gate_lines[gate_lines.index(f"[PASS] {check}") + 1].strip()


published = re.fullmatch(r"(\d+) published, (\d+) failed, (\d+) dropped", gate_detail("a live plugin event reaches the backend"))
gate_e2e = re.fullmatch(r"(\d+) passed", gate_detail("pytest -m e2e passes on the Compose stack"))
assert published and gate_e2e, "the gate log's metrics or end-to-end line has another form"
filled.update(
    GATE_RUN=gate_run.group(1), GATE_COMMIT=gate_run.group(2), GATE_E2E=gate_e2e.group(1),
    GATE_CHECKS=str(sum(1 for line in gate_lines if line.startswith("[PASS] "))),
    R_METRICS_CHECK=(f"Passed in gate run {gate_run.group(1)}: {published.group(1)} events published since jenkins-dev "
                     "started, " + ("none failed or dropped" if published.group(2) == published.group(3) == "0"
                                    else f"{published.group(2)} failed and {published.group(3)} dropped")),
)

# --- CI history and the Lighthouse audits ----------------------------------------------------------
ci_rows = read_csv(DATA / "ci-runs.csv")
ci = {conclusion: sum(1 for r in ci_rows if r["conclusion"] == conclusion) for conclusion in ("success", "failure", "cancelled")}
assert sum(ci.values()) == len(ci_rows), f"a CI conclusion outside success, failure and cancelled: {ci_rows}"
filled.update(CI_RUNS=str(len(ci_rows)), CI_PASS=str(ci["success"]), CI_FAIL=str(ci["failure"]), CI_CANCEL=str(ci["cancelled"]))
lighthouse = re.findall(r"^((?:freestyle|pipeline)-[\w-]+): (\d+)\s*$",
                        (campaign / "logs" / "lighthouse.log").read_text(encoding="utf-8", errors="replace"), re.M)
assert len(lighthouse) == 16, f"expected 16 Lighthouse audits, found {len(lighthouse)}"
filled["LIGHTHOUSE_MIN"] = str(min(int(score) for _, score in lighthouse))

for key, name in (("PLUGIN_IT", "Plugin integration tests"), ("BACKEND_INT", "Backend integration tests"),
                  ("BACKEND_LIVE", "Backend live tests"), ("BACKEND_E2E", "Backend end-to-end tests"),
                  ("FLOWS", "Browser flows"), ("STACK", "System tests on the running stack")):
    row = suite(name)
    filled[f"N_{key}"] = row["tests"]
    filled[f"R_{key}"] = outcome(row)

rows = []
totals = [0, 0, 0, 0, 0, 0.0]
for row in summary:
    numbers = [int(row["tests"]), int(row["passed"]), int(row["failed"]), int(row["error"]), int(row["skipped"]), float(row["seconds"])]
    totals = [a + b for a, b in zip(totals, numbers, strict=True)]
    rows.append([row["suite"], row["level"], row["tests"], row["passed"], int(row["failed"]) + int(row["error"]),
                 row["skipped"], f"{float(row['seconds']):,.0f}", "yes" if row["ci"] else "no"])
rows.append(["**All**", "", f"**{totals[0]:,}**", f"**{totals[1]:,}**", f"**{totals[2] + totals[3]}**", f"**{totals[4]}**",
             f"**{totals[5]:,.0f}**", ""])
filled["SUITES_TABLE"] = (
    "**Table {T:suites}: Every suite in the register** (the evidence campaign at `" + values["literal"]["COMMIT"]
    + "`, and the gate's checks from gate run " + filled["GATE_RUN"] + " at `" + filled["GATE_COMMIT"]
    + "`; every test, with its file, phase, commit and CI link, is in Annexure B)" + LF + LF
    + table(["Suite", "Level", "Tests", "Passed", "Failed", "Skipped", "Seconds", "Also in CI"], rows,
            ["---", "---", "---:", "---:", "---:", "---:", "---:", "---"]))
filled["N_SUITES"] = str(len(summary))
filled["TOTAL_TESTS"] = f"{totals[0]:,}"
filled["TOTAL_PASSED"] = f"{totals[1]:,}"
filled["TOTAL_SKIPPED"] = str(totals[4])
filled["TOTAL_FAILED"] = str(totals[2] + totals[3])

register = read_csv(DATA / "test-register.csv")
review = [r for r in register if r["file"].replace("\\", "/").endswith("test_security_review_fixes.py")]
filled["REVIEW_TESTS"] = str(len(review))

# --- Coverage --------------------------------------------------------------------------------------
offline = json.loads((campaign / "backend" / "backend-offline-coverage.json").read_text(encoding="utf-8"))["totals"]
cumulative = json.loads((campaign / "backend" / "backend-live-coverage.json").read_text(encoding="utf-8"))
files = len(cumulative["files"])
total = cumulative["totals"]
frontend = json.loads((campaign / "frontend" / "coverage-summary.json").read_text(encoding="utf-8"))["total"]
filled["BACKEND_STATEMENTS"] = f"{offline['num_statements']:,}"
filled["BACKEND_MODULES"] = str(files)
filled["FRONTEND_STATEMENTS"] = f"{frontend['statements']['total']:,}"
filled["BACKEND_COVERAGE_ALL"] = pct(total["covered_lines"], total["num_statements"])
filled["FRONTEND_COVERAGE"] = f"{frontend['statements']['pct']:.1f}%"
offline_suite = suite("Backend tests")
frontend_suite = suite("Frontend unit")
filled["COVERAGE_ROWS_BACKEND_FRONTEND"] = LF.join([
    f"| Backend, offline suite | {offline_suite['tests']} tests (coverage.py, greenlet-aware) | "
    f"{pct(offline['covered_lines'], offline['num_statements'])} ({offline['covered_lines']:,} of {offline['num_statements']:,} statements) | "
    f"{pct(offline['covered_branches'], offline['num_branches'])} ({offline['covered_branches']:,} of {offline['num_branches']:,}) |",
    f"| Backend, all four suites | the offline suite plus integration, end-to-end and live | "
    f"{pct(total['covered_lines'], total['num_statements'])} ({total['covered_lines']:,} of {total['num_statements']:,}) | "
    f"{pct(total['covered_branches'], total['num_branches'])} ({total['covered_branches']:,} of {total['num_branches']:,}) |",
    f"| Frontend | {frontend_suite['tests']} unit and component tests (V8) | "
    f"{frontend['statements']['pct']:.1f}% ({frontend['statements']['covered']:,} of {frontend['statements']['total']:,} statements) | "
    f"{frontend['branches']['pct']:.1f}% ({frontend['branches']['covered']:,} of {frontend['branches']['total']:,}) |",
])

# --- Complexity -------------------------------------------------------------------------------------
complexity_rows = read_csv(DATA / "complexity-summary.csv")
top = read_csv(DATA / "complexity-top.csv")
parts = [table(["Component", "Functions", "Mean CCN", "Median", "Highest", "Over 10", "Over 15"],
               [[r["component"], r["functions"], r["mean_ccn"], r["median_ccn"], r["max_ccn"], r["over_10"], r["over_15"]]
                for r in complexity_rows], ["---", "---:", "---:", "---:", "---:", "---:", "---:"])]
heads = []
for component in ("Plugin", "Backend", "Frontend"):
    for r in [r for r in top if r["component"] == component][:5]:
        where = r["where"].rsplit("/", 1)[-1]
        heads.append([component, f"`{r['function'].split('::')[-1]}` (`{where}`)", r["ccn"],
                      r["branch_coverage_pct"] + ("" if not r["branch_coverage_pct"][:1].isdigit() else "%"),
                      r["coverage_measured_per"]])
filled["COMPLEXITY_TABLE"] = (
    LF + "**Table {T:complexity}: Cyclomatic complexity by component** (lizard 1.24.1, the components' "
    "own code; Annexure A.13)" + LF + LF + parts[0] + LF + LF
    + "**Table {T:complexitytop}: The five most complex functions of each component, and their branch coverage**"
    + LF + LF + table(["Component", "Function", "CCN", "Branches covered", "Coverage measured per"], heads,
                      ["---", "---", "---:", "---:", "---"]))

# --- Load and recovery --------------------------------------------------------------------------------
load = json.loads((system / "load-test.json").read_text(encoding="utf-8")) if (system / "load-test.json").is_file() else None
rows = []
if load is None:
    load = {"levels": [], "stress": None}
for level in load["levels"]:
    stats = level["all"]
    rows.append([f"{level['users']} user{'s' if level['users'] > 1 else ''}, 3 a second each, 30 s", stats["requests"],
                 level["throughput_rps"], stats["p50_ms"], stats["p95_ms"], stats["max_ms"],
                 ", ".join(f"{k}: {v}" for k, v in sorted(stats["statuses"].items()))])
stress = load["stress"]
if stress:
    rows.append([f"Stress: {stress['requests']} requests at once, {stress['threads']} threads", stress["all"]["requests"],
                 stress["throughput_rps"], stress["all"]["p50_ms"], stress["all"]["p95_ms"], stress["all"]["max_ms"],
                 ", ".join(f"{k}: {v}" for k, v in sorted(stress["all"]["statuses"].items()))])
if rows:
    filled["LOAD_TABLE"] = (
    "**Table {T:load}: Load and stress, through the stack's own frontend** (`scripts/system_load_test.py`; "
    "Annexure A.8)" + LF + LF
    + table(["Load", "Requests", "Per second", "Median (ms)", "95th percentile (ms)", "Longest (ms)", "Statuses"], rows,
            ["---", "---:", "---:", "---:", "---:", "---:", "---"]))

recovery_file = system / "recovery-test.json"
recovery = json.loads(recovery_file.read_text(encoding="utf-8")) if recovery_file.is_file() else {"steps": []}
rows = []
for step in recovery["steps"]:
    name = step["restarted"]
    if name == "postgres":
        meanwhile = "database reported down" if step["reported_down_after_restart"] else "database not seen down (back first)"
        back = step["database_up_again_after_s"]
        after = f"signed-in request: {step['signed_in_request_after']}"
    elif name == "backend":
        meanwhile = "-"
        back = step["live_again_after_s"]
        after = f"runs stored: {step['runs_before']} before, {step['runs_after']} after"
    else:
        meanwhile = (f"Jenkins reported {step['jenkins_reported_while_restarting']}; the queue API answered "
                     f"{step['queue_api_while_restarting']}" + (", ranking unavailable" if step["queue_said_unavailable"] else ""))
        back = step["jenkins_up_again_after_s"]
        after = f"both agents online after {step['agents_online_after_s']} s"
    rows.append([{"postgres": "PostgreSQL", "backend": "The backend", "jenkins-dev": "jenkins-dev"}[name],
                 step["restart_command_s"], meanwhile, back, after, "passed" if step["passed"] else "**failed**"])
if rows:
    filled["RECOVERY_TABLE"] = (
    "**Table {T:recovery}: Recovery, one dependency restarted at a time** (`scripts/recovery_test.py`; seconds; "
    "Annexure A.8)" + LF + LF
    + table(["Restarted", "Restart took", "Meanwhile", "Back after", "Then", "Result"], rows,
            ["---", "---:", "---", "---:", "---", "---"]))

# --- Apply ---------------------------------------------------------------------------------------------
text = draft.read_text(encoding="utf-8")
used = set()
for key, value in filled.items():
    marker = "[[" + key + "]]"
    if marker in text:
        text = text.replace(marker, str(value))
        used.add(key)

# The traceability result is the citation check's own output, run on the chapter as filled so far.
if "[[TRACEABILITY_RESULT]]" in text:
    out.write_text(text, encoding="utf-8", newline=LF)
    check = subprocess.run([sys.executable, str(repo / "scripts" / "report" / "check_citations.py"), str(out)],
                           capture_output=True, text=True, check=False)
    found = re.search(r"(\d+) test names, (\d+) test files, (\d+) titles and (\d+) components cited; "
                      r"(\d+) of (\d+) ran and passed in the register \((\d+) tests\); (\d+) of (\d+) stated counts right",
                      check.stdout)
    if check.returncode != 0 or not found:
        sys.exit("the citation check failed:" + LF + check.stdout + check.stderr)
    names, files, titles, components, passed, cited, _, right, stated = found.groups()
    text = text.replace("[[TRACEABILITY_RESULT]]", (
        "Every requirement in Table {T:matrix} has at least one test, and every test the chapter names ran and "
        "passed in the evidence campaign. `scripts/report/check_citations.py` checks this against Annexure B's "
        f"register: it found all {cited} tests the chapter cites ({names} by name, {files} by file, {titles} by "
        f"title and {components} by the component they test), every one of them passed, and the {stated} test "
        "counts the chapter states are right."))
    used.add("TRACEABILITY_RESULT")
out.write_text(text, encoding="utf-8", newline=LF)
left = sorted(set(re.findall(r"\[\[([A-Z0-9_]+)\]\]", text)))
print("filled:", sorted(used))
print("left for the hand:", left)
