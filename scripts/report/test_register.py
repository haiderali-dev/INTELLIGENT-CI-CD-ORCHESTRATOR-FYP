"""Build the register of every test that ran, from one evidence campaign.

    python scripts/report/test_register.py .tmp/campaign/<commit> --gate <gate log> [--ci <runs.json>]

Reads what scripts/test_campaign.py kept (JUnit XML from every runner, the Lighthouse log, the
manifest) and the gate's own output, and writes:

- ``docs/testing/data/test-register.csv``: one row per test that ran;
- ``docs/testing/data/test-register-summary.csv``: one row per suite;
- ``docs/testing/annexure-b-test-register.md``: the same, as tables for the report.

Every row names the commit the test ran at. The phase is the one whose commit introduced the
test, found with ``git log -S`` and read from that commit's task id (T2.7 is Phase 2); a test added
after Phase 6 was merged is "Hardening". Nothing is estimated: a test is in the register because a
runner reported it.
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from xml.etree import ElementTree

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "docs" / "testing"
PHASE_6_MERGE = "31a725f"
# CSV rows end in LF, as the repository stores text; the csv module's default is CRLF.
LF = chr(10)
CI_URL = "https://github.com/haiderali-dev/INTELLIGENT-CI-CD-ORCHESTRATOR-FYP/actions/runs/{run}"
PHASE_NAMES = {
    "0": "Phase 0, repository foundation",
    "1": "Phase 1, infrastructure",
    "2": "Phase 2, plugin",
    "3": "Phase 3, backend foundation",
    "4": "Phase 4, AI core",
    "5": "Phase 5, the two assistants",
    "6": "Phase 6, frontend",
    "H": "Hardening of Phases 1 to 6",
}


@dataclass
class Row:
    suite: str
    level: str
    technique: str
    component: str
    file: str
    test: str
    description: str
    result: str
    seconds: float
    phase: str
    introduced_in: str
    ran_at: str
    ci: str


# --------------------------------------------------------------------------------------------------
# Git provenance
# --------------------------------------------------------------------------------------------------


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", check=True
    ).stdout


class Provenance:
    """Which commit introduced a test, and so which phase; cached, because it asks git a lot."""

    def __init__(self, cache: Path) -> None:
        self.cache_path = cache
        self.cache: dict[str, str] = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
        self.hardening = set(git("rev-list", f"{PHASE_6_MERGE}..HEAD").split())
        log = git("log", "--reverse", "--format=%H%x09%s").splitlines()
        self.order = [line.split("\t", 1)[0] for line in log]
        self.subject = dict(line.split("\t", 1) for line in log)

    def introduced(self, path: str, needle: str) -> str:
        key = f"{path}::{needle}"
        if key not in self.cache:
            found = git("log", "--reverse", "--format=%H", "-S", needle, "--", path).split()
            if not found:
                found = git("log", "--reverse", "--format=%H", "--diff-filter=A", "--", path).split()
            self.cache[key] = found[0] if found else ""
        return self.cache[key]

    def phase(self, commit: str) -> str:
        if not commit:
            return "?"
        if commit in self.hardening:
            return "H"
        # The task id names the phase; failing that, the phase a commit says it belongs to; failing
        # that, the nearest earlier commit that does.
        index = self.order.index(commit) if commit in self.order else -1
        for candidate in reversed(self.order[: index + 1]):
            subject = self.subject[candidate]
            task = re.search(r"\bT(\d)\.\d+", subject)
            if task:
                return task.group(1)
            named = re.search(r"\b[Pp]hase[- ](\d)\b", subject)
            if named:
                return named.group(1)
        return "0"

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self.cache, indent=1, sort_keys=True), encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# Descriptions from the source
# --------------------------------------------------------------------------------------------------

_DISPLAY = re.compile(r'@DisplayName\(\s*"((?:[^"\\]|\\.)*)"\s*\)')
_METHOD = re.compile(r"\bvoid\s+(\w+)\s*\(")


def java_display_names(source: Path) -> dict[str, str]:
    """method name -> @DisplayName, read from the test's own source."""
    names: dict[str, str] = {}
    pending = None
    for line in source.read_text(encoding="utf-8").splitlines():
        shown = _DISPLAY.search(line)
        if shown:
            pending = shown.group(1)
            continue
        method = _METHOD.search(line)
        if method and pending:
            names[method.group(1)] = pending
            pending = None
    return names


def python_tests(source: Path) -> dict[str, tuple[str, bool]]:
    """test function -> (first docstring line, whether it drives the HTTP API through `client`)."""
    tests: dict[str, tuple[str, bool]] = {}
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            doc = (ast.get_docstring(node) or "").strip().splitlines()
            arguments = {argument.arg for argument in node.args.args}
            tests[node.name] = (doc[0] if doc else "", bool(arguments & {"client", "ws_client"}))
    return tests


# --------------------------------------------------------------------------------------------------
# Runners' reports
# --------------------------------------------------------------------------------------------------


def cases(report: Path) -> list[tuple[ElementTree.Element, ElementTree.Element | None]]:
    """Every <testcase> with its <testsuite>, from any runner's JUnit XML."""
    root = ElementTree.parse(report).getroot()  # noqa: S314 (reports written by our own runners)
    found = []
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        return [(case, None) for case in root.iter("testcase")]
    seen: set[int] = set()
    for suite in suites:
        for case in suite.findall("testcase"):
            if id(case) not in seen:
                seen.add(id(case))
                found.append((case, suite))
    for case in root.iter("testcase"):
        if id(case) not in seen:
            found.append((case, None))
    return found


def outcome(case: ElementTree.Element) -> str:
    if case.find("failure") is not None:
        return "failed"
    if case.find("error") is not None:
        return "error"
    if case.find("skipped") is not None:
        return "skipped"
    return "passed"


def seconds(case: ElementTree.Element) -> float:
    try:
        return round(float(case.get("time") or 0), 3)
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------------------------------
# The register
# --------------------------------------------------------------------------------------------------


class Register:
    def __init__(self, campaign: Path, provenance: Provenance, ci: dict[str, str]) -> None:
        self.campaign = campaign
        self.provenance = provenance
        self.ci = ci
        manifest = json.loads((campaign / "manifest.json").read_text(encoding="utf-8"))
        self.commit = manifest["commit"][:7]
        self.steps = {step["name"]: step for step in manifest["steps"]}
        self.rows: list[Row] = []

    def add(self, *, suite: str, level: str, technique: str, component: str, file: str, test: str,
            needle: str, description: str, result: str, time: float, ci_job: str | None) -> None:
        introduced = self.provenance.introduced(file, needle)
        self.rows.append(Row(
            suite=suite,
            level=level,
            technique=technique,
            component=component,
            file=file,
            test=test,
            description=description,
            result=result,
            seconds=time,
            phase=self.provenance.phase(introduced),
            introduced_in=introduced[:7],
            ran_at=self.commit,
            ci=self.ci.get(ci_job, "") if ci_job else "",
        ))

    def plugin(self) -> None:
        for folder, suite, level, technique in (
            ("plugin/surefire-reports", "Plugin unit tests (JUnit 5)", "Unit", "White-box"),
            ("plugin/failsafe-reports", "Plugin integration tests (JenkinsRule)", "Integration", "Black-box"),
        ):
            for report in sorted((self.campaign / folder).glob("TEST-*.xml")):
                for case, _ in cases(report):
                    classname = case.get("classname", "")
                    if classname.endswith(".InjectedTest"):
                        # Generated by maven-hpi-plugin into every plugin's build since T2.1: it
                        # loads the plugin in Jenkins and checks its property files. It has no source
                        # in the repository, so its phase is the build's.
                        self.rows.append(Row(
                            suite=suite, level=level, technique="Black-box", component="Plugin",
                            file="(generated by maven-hpi-plugin)", test=f"InjectedTest.{case.get('name')}",
                            description="Jenkins test harness check, generated", result=outcome(case),
                            seconds=seconds(case), phase="2", introduced_in="", ran_at=self.commit,
                            ci=self.ci.get("Plugin", ""),
                        ))
                        continue
                    top = classname.split("$")[0]
                    file = "plugin/src/test/java/" + top.replace(".", "/") + ".java"
                    method = re.sub(r"[\[(].*$", "", case.get("name", ""))
                    source = REPO_ROOT / file
                    shown = java_display_names(source).get(method, "") if source.is_file() else ""
                    self.add(
                        suite=suite, level=level, technique=technique, component="Plugin", file=file,
                        test=f"{classname.split('.')[-1]}.{case.get('name')}", needle=method,
                        description=shown, result=outcome(case), time=seconds(case), ci_job="Plugin",
                    )

    def backend(self) -> None:
        for name, suite, level, ci_job in (
            ("backend-offline", "Backend tests (pytest, offline)", "Unit and component", "Backend"),
            ("backend-integration", "Backend integration tests (real Jenkins, PostgreSQL, Git)", "Integration", None),
            ("backend-e2e", "Backend end-to-end tests (real Jenkins)", "System", None),
            ("backend-live", "Backend live tests (real model provider)", "Integration", None),
        ):
            report = self.campaign / "backend" / f"{name}.xml"
            if not report.is_file():
                continue
            described: dict[str, dict[str, tuple[str, bool]]] = {}
            for case, _ in cases(report):
                module = case.get("classname", "")
                file = "backend/" + module.replace(".", "/") + ".py"
                function = re.sub(r"\[.*$", "", case.get("name", ""))
                if file not in described:
                    source = REPO_ROOT / file
                    described[file] = python_tests(source) if source.is_file() else {}
                doc, through_api = described[file].get(function, ("", False))
                acceptance = file.endswith("test_acceptance_user_stories.py")
                self.add(
                    suite=suite,
                    level="Acceptance" if acceptance else level,
                    technique="Black-box" if (through_api or level != "Unit and component") else "White-box",
                    component="Backend", file=file, test=case.get("name", ""), needle=function,
                    description=doc, result=outcome(case), time=seconds(case), ci_job=ci_job,
                )

    def frontend(self) -> None:
        report = self.campaign / "frontend" / "unit.xml"
        if report.is_file():
            for case, _ in cases(report):
                file = "frontend/" + case.get("classname", "").replace("\\", "/")
                title = case.get("name", "")
                self.add(
                    suite="Frontend unit and component tests (Vitest)", level="Unit and component",
                    technique="Black-box" if file.endswith(".tsx") else "White-box",
                    component="Frontend", file=file, test=title, needle=title.split(" > ")[-1],
                    description="", result=outcome(case), time=seconds(case), ci_job="Frontend",
                )
        for name, suite, level, ci_job in (
            ("browser-flows", "Browser flows (Playwright, backend in fake mode)", "System", "Browser flows"),
            ("lighthouse", "Accessibility audits (Lighthouse in Playwright)", "System", "Browser flows"),
            ("stack", "System tests on the running stack (Playwright)", "System", None),
        ):
            report = self.campaign / "frontend" / f"{name}.xml"
            if not report.is_file():
                continue
            for case, suite_element in cases(report):
                spec = case.get("classname") or (suite_element.get("name") if suite_element is not None else "")
                file = "frontend/e2e/" + Path(spec.replace("\\", "/")).name
                title = case.get("name", "")
                self.add(
                    suite=suite, level=level, technique="Black-box", component="Frontend", file=file,
                    test=title, needle=title.split(" › ")[-1], description="", result=outcome(case),
                    time=seconds(case), ci_job=ci_job,
                )

    def lighthouse_audits(self) -> None:
        """The 16 audit scores the Lighthouse test logs, each a row of its own."""
        step = self.steps.get("lighthouse")
        if not step:
            return
        log = (self.campaign / step["log"]).read_text(encoding="utf-8", errors="replace")
        for page, score in re.findall(r"^((?:freestyle|pipeline)-[\w-]+): (\d+)\s*$", log, re.M):
            self.add(
                suite="Accessibility audits (Lighthouse in Playwright)", level="System",
                technique="Black-box", component="Frontend", file="frontend/e2e/lighthouse.spec.ts",
                test=f"audit {page}", needle="both assistant pages score 95 or more for accessibility",
                description=f"Lighthouse accessibility score {score} (95 required)",
                result="passed" if int(score) >= 95 else "failed", time=0.0, ci_job="Browser flows",
            )

    def sample_services(self) -> None:
        for name, folder in (("payment-service", "tests"), ("auth-service", "test")):
            report = self.campaign / "sample-services" / f"{name}.xml"
            if not report.is_file():
                continue
            for case, _ in cases(report):
                if name == "payment-service":
                    file = f"sample-services/{name}/" + case.get("classname", "").replace(".", "/") + ".py"
                else:
                    file = f"sample-services/{name}/{folder}/unit.test.js"
                title = case.get("name", "")
                self.add(
                    suite="Sample services' own tests", level="Unit and integration",
                    technique="Black-box", component="Sample services", file=file, test=title,
                    needle=re.sub(r"\[.*$", "", title), description="", result=outcome(case),
                    time=seconds(case), ci_job=None,
                )

    def gate(self, log: Path) -> None:
        phase = "0"
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        for index, line in enumerate(lines):
            heading = re.match(r"-- phase (\d) -", line)
            if heading:
                phase = heading.group(1)
                continue
            verdict = re.match(r"\[(PASS|FAIL)\] (.+)$", line)
            if verdict:
                message = lines[index + 1].strip() if index + 1 < len(lines) else ""
                self.add(
                    suite="Phase acceptance gate (scripts/verify.py)", level="Acceptance",
                    technique="Black-box", component="Whole system", file="scripts/verify.py",
                    test=f"phase {phase}: {verdict.group(2)}", needle=verdict.group(2),
                    description=message, result="passed" if verdict.group(1) == "PASS" else "failed",
                    time=0.0, ci_job="Phase checks" if phase == "0" else None,
                )
                # The gate's phase is the check's own, not the commit that added it.
                self.rows[-1].phase = phase


# --------------------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------------------


def code(text: str) -> str:
    """Text as a Markdown code span, whatever backticks it holds (a test's parameters can)."""
    fence = "`" * (max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def write(register: Register) -> None:
    data = OUT / "data"
    data.mkdir(parents=True, exist_ok=True)
    with (data / "test-register.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[f.name for f in fields(Row)], lineterminator=LF)
        writer.writeheader()
        for row in register.rows:
            writer.writerow(asdict(row))

    by_suite: dict[str, list[Row]] = defaultdict(list)
    for row in register.rows:
        by_suite[row.suite].append(row)
    with (data / "test-register-summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator=LF)
        writer.writerow(["suite", "level", "tests", "passed", "failed", "error", "skipped", "seconds", "ran_at", "ci"])
        for suite, rows in by_suite.items():
            counts = Counter(row.result for row in rows)
            writer.writerow([
                suite, rows[0].level if len({r.level for r in rows}) == 1 else "mixed", len(rows),
                counts["passed"], counts["failed"], counts["error"], counts["skipped"],
                round(sum(row.seconds for row in rows), 1), register.commit, rows[0].ci,
            ])

    lines = [
        "# Annexure B: register of every test that ran",
        "",
        f"Generated by `scripts/report/test_register.py` from the evidence campaign at commit "
        f"`{register.commit}` and the gate's log. One row per test a runner reported; the same rows "
        "are in `data/test-register.csv`. *Test* is the name the runner reported, as the chapter cites "
        "it, and *What it checks* the test's own description where it has one. *Added in* is the commit "
        "that introduced the test and *Phase* that commit's phase (H: the hardening of Phases 1 to 6). "
        "Every result is from the campaign's commit; under each suite is the CI run that also ran it, "
        "where CI runs that suite.",
        "",
    ]
    for suite, rows in by_suite.items():
        counts = Counter(row.result for row in rows)
        verdict = ", ".join(f"{count} {result}" for result, count in counts.most_common())
        lines += [f"## {suite}", "", f"{len(rows)} tests: {verdict}. Ran at `{register.commit}`."]
        if rows[0].ci:
            link = re.fullmatch(r"(CI run \d+) \((https://\S+)\)", rows[0].ci)
            lines.append(f"Also run by CI on every push: {f'[{link.group(1)}]({link.group(2)})' if link else rows[0].ci}.")
        lines += ["", "| # | Test | What it checks | File | Phase | Added in | Result | Time (s) |",
                  "| ---: | --- | --- | --- | :---: | --- | --- | ---: |"]
        for number, row in enumerate(rows, start=1):
            test, description = (cell.replace("|", "\\|") for cell in (row.test, row.description))
            added = code(row.introduced_in) if row.introduced_in else "-"
            lines.append(
                f"| {number} | {code(test)} | {description} | {code(row.file)} | {row.phase} | {added} | {row.result} | {row.seconds:g} |"
            )
        lines.append("")
    (OUT / "annexure-b-test-register.md").write_text(LF.join(lines) + LF, encoding="utf-8", newline=LF)


def ci_links(path: Path | None, commit: str) -> dict[str, str]:
    """CI job name -> link to the run for this commit, if CI passed it."""
    if path is None or not path.is_file():
        return {}
    runs = json.loads(path.read_text(encoding="utf-8"))
    links = {}
    for run in runs:
        if run.get("headSha", "").startswith(commit) and run.get("conclusion") == "success":
            url = CI_URL.format(run=run["databaseId"])
            for job in ("Plugin", "Backend", "Frontend", "Browser flows", "Phase checks"):
                links.setdefault(job, f"CI run {run['databaseId']} ({url})")
    return links


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--gate", type=Path, required=True, help="the full gate's output")
    parser.add_argument("--ci", type=Path, help="`gh run list --json ...` output")
    args = parser.parse_args()

    manifest = json.loads((args.campaign / "manifest.json").read_text(encoding="utf-8"))
    provenance = Provenance(REPO_ROOT / ".tmp" / "register-provenance.json")
    register = Register(args.campaign, provenance, ci_links(args.ci, manifest["commit"][:7]))
    register.plugin()
    register.backend()
    register.frontend()
    register.lighthouse_audits()
    register.sample_services()
    register.gate(args.gate)
    provenance.save()
    write(register)

    counts = Counter(row.result for row in register.rows)
    print(f"{len(register.rows)} rows at {register.commit}: {dict(counts)}")
    unknown = sum(1 for row in register.rows if row.phase == "?")
    print(f"rows without a phase: {unknown}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
