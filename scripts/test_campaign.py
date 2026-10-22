"""Run every test suite in the repository once, at one commit, and keep what each one reports.

The testing chapter's register of every test (scripts/report/test_register.py) is built from what
this writes, so every number in it comes from a run that happened, at a commit that is named:

    python scripts/test_campaign.py                 # everything the machine can run
    python scripts/test_campaign.py --only backend-offline frontend-unit

Each step saves its machine-readable report (JUnit XML, coverage, PIT, CSV) and its full output
under ``.tmp/campaign/<commit>/`` (gitignored), and ``manifest.json`` records, for every step, the
command, when it ran, how long it took and how it ended. A step that cannot run here (no stack, no
model key) says so in the manifest rather than disappearing.

Steps that need the Compose stack (integration, e2e, the stack's system tests) expect it to be up,
as ``verify.py`` does. Nothing here reads ``.env``: the suites read their own settings, exactly as
when they are run by hand or by the gate.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN = REPO_ROOT / "plugin"
BACKEND = REPO_ROOT / "backend"
FRONTEND = REPO_ROOT / "frontend"
PAYMENT = REPO_ROOT / "sample-services" / "payment-service"
AUTH = REPO_ROOT / "sample-services" / "auth-service"
UV = REPO_ROOT / ".venv-tools" / ("Scripts/uv.exe" if os.name == "nt" else "bin/uv")
WINDOWS = os.name == "nt"


@dataclass
class Step:
    name: str
    command: list[str]
    started: str = ""
    seconds: float = 0.0
    exit_code: int | None = None
    log: str = ""
    artifacts: list[str] = field(default_factory=list)
    note: str = ""


def tool(name: str) -> str:
    """The executable for a tool, with Windows' .cmd shims where npm and Maven use them."""
    if WINDOWS and name in ("mvn", "npm", "npx"):
        return f"{name}.cmd"
    return name


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


class Campaign:
    def __init__(self, out: Path, commit: str) -> None:
        self.out = out
        self.commit = commit
        self.steps: list[Step] = []
        out.mkdir(parents=True, exist_ok=True)
        (out / "logs").mkdir(exist_ok=True)

    def run(
        self,
        name: str,
        command: list[str],
        cwd: Path,
        *,
        env: dict[str, str] | None = None,
        timeout: int = 3600,
        collect: Callable[[], list[str]] | None = None,
    ) -> Step:
        step = Step(name=name, command=command)
        # Never a minimal environment: dropping SystemRoot breaks DNS on Windows (CLAUDE.md).
        environment = {**os.environ, **(env or {})}
        step.started = datetime.now(UTC).isoformat(timespec="seconds")
        log = self.out / "logs" / f"{name}.log"
        print(f"== {name}: {' '.join(command)}", flush=True)
        began = time.monotonic()
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            step.exit_code = result.returncode
            log.write_text(result.stdout + "\n--- stderr ---\n" + result.stderr, encoding="utf-8")
        except subprocess.TimeoutExpired as expired:
            step.exit_code = -1
            step.note = f"timed out after {timeout} s"
            log.write_text(str(expired), encoding="utf-8")
        except FileNotFoundError as missing:
            step.exit_code = -2
            step.note = f"could not start: {missing}"
            log.write_text(str(missing), encoding="utf-8")
        step.seconds = round(time.monotonic() - began, 1)
        step.log = str(log.relative_to(self.out))
        if collect is not None:
            step.artifacts = collect()
        print(f"   exit {step.exit_code} in {step.seconds} s {step.note}", flush=True)
        self.steps.append(step)
        self.write_manifest()
        return step

    def keep(self, sources: list[Path], folder: str) -> list[str]:
        """Copy reports into the campaign folder, returning their paths inside it."""
        target = self.out / folder
        target.mkdir(parents=True, exist_ok=True)
        kept = []
        for source in sources:
            if source.is_file():
                shutil.copy2(source, target / source.name)
                kept.append(f"{folder}/{source.name}")
            elif source.is_dir():
                shutil.copytree(source, target / source.name, dirs_exist_ok=True)
                kept.append(f"{folder}/{source.name}/")
        return kept

    def write_manifest(self) -> None:
        """Write the manifest, keeping the steps an earlier run at the same commit recorded.

        A campaign may be run in parts (`--only`), for example to give the machine's memory back
        between the browser steps. A part replaces the record of any step it runs again and keeps
        the rest, so the manifest always holds the latest run of every step at this commit."""
        path = self.out / "manifest.json"
        steps = {step.name: asdict(step) for step in self.steps}
        if path.is_file():
            earlier = json.loads(path.read_text(encoding="utf-8"))
            if earlier.get("commit") == self.commit:
                kept = [step for step in earlier.get("steps", []) if step["name"] not in steps]
                steps = {step["name"]: step for step in kept} | steps
        manifest = {
            "commit": self.commit,
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "written": datetime.now(UTC).isoformat(timespec="seconds"),
            "machine": {
                "os": f"{os.name} {sys.platform}",
                "python": sys.version.split()[0],
                "processors": os.cpu_count(),
            },
            "steps": list(steps.values()),
        }
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------------------------------
# The steps
# ---------------------------------------------------------------------------------------------------


def plugin_tests(c: Campaign) -> None:
    # Unit and JenkinsRule integration tests, with JaCoCo through the parent POM's profile. From
    # clean: Surefire and Failsafe never empty their report folders, so an earlier partial run's
    # reports would otherwise be counted as this run's.
    c.run(
        "plugin",
        [tool("mvn"), "-B", "-ntp", "clean", "verify", "-P", "enable-jacoco"],
        PLUGIN,
        timeout=3600,
        collect=lambda: c.keep(
            [
                PLUGIN / "target" / "surefire-reports",
                PLUGIN / "target" / "failsafe-reports",
                PLUGIN / "target" / "site" / "jacoco" / "jacoco.xml",
                PLUGIN / "target" / "site" / "jacoco" / "jacoco.csv",
            ],
            "plugin",
        ),
    )


def plugin_mutation(c: Campaign) -> None:
    c.run(
        "plugin-mutation",
        [tool("mvn"), "-B", "-ntp", "-P", "mutation", "test-compile", "org.pitest:pitest-maven:mutationCoverage"],
        PLUGIN,
        timeout=3600,
        collect=lambda: c.keep([PLUGIN / "target" / "pit-reports" / "mutations.xml"], "plugin-mutation"),
    )


def plugin_experiments(c: Campaign) -> None:
    # Not instrumented: the overhead experiment measures time.
    shutil.rmtree(PLUGIN / "target" / "experiments", ignore_errors=True)
    c.run(
        "plugin-experiments",
        [
            tool("mvn"),
            "-B",
            "-ntp",
            "verify",
            "-Dtest=QueueSimulationExperiment",
            "-Dit.test=SchedulerOverheadExperiment",
            "-Dsurefire.failIfNoSpecifiedTests=false",
            "-Dfailsafe.failIfNoSpecifiedTests=false",
        ],
        PLUGIN,
        timeout=3600,
        collect=lambda: c.keep(
            sorted((PLUGIN / "target" / "experiments").glob("*")) if (PLUGIN / "target" / "experiments").is_dir() else [],
            "plugin-experiments",
        ),
    )


def backend(c: Campaign, marker: str, name: str, *, append: bool, timeout: int = 3600) -> None:
    junit = c.out / "backend" / f"{name}.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)
    coverage = c.out / "backend" / f"{name}-coverage.json"
    command = [
        str(UV), "run", "--no-sync", "python", "-m", "pytest",
        "-m", marker,
        "-p", "no:cacheprovider",
        f"--junitxml={junit}",
        "--cov=app",
        f"--cov-report=json:{coverage}",
    ]
    if append:
        command.append("--cov-append")
    c.run(name, command, BACKEND, timeout=timeout, collect=lambda: [f"backend/{junit.name}", f"backend/{coverage.name}"])


def frontend_unit(c: Campaign) -> None:
    junit = c.out / "frontend" / "unit.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)
    c.run(
        "frontend-unit",
        [
            tool("npx"), "vitest", "run", "--coverage",
            "--reporter=default", "--reporter=junit", f"--outputFile.junit={junit}",
        ],
        FRONTEND,
        collect=lambda: ["frontend/unit.xml", *c.keep([FRONTEND / "coverage" / "coverage-summary.json"], "frontend")],
    )


def playwright(c: Campaign, name: str, arguments: list[str], env: dict[str, str] | None = None, *, timeout: int = 3600) -> None:
    junit = c.out / "frontend" / f"{name}.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)
    c.run(
        name,
        [tool("npx"), "playwright", "test", *arguments, "--reporter=line,junit"],
        FRONTEND,
        env={"PLAYWRIGHT_JUNIT_OUTPUT_NAME": str(junit), **(env or {})},
        timeout=timeout,
        collect=lambda: [f"frontend/{junit.name}"],
    )


def stack_system(c: Campaign) -> None:
    junit = c.out / "frontend" / "stack.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)
    c.run(
        "stack-system",
        [sys.executable, str(REPO_ROOT / "scripts" / "stack_system_test.py"), "--reporter=line,junit"],
        REPO_ROOT,
        env={"PLAYWRIGHT_JUNIT_OUTPUT_NAME": str(junit)},
        timeout=1800,
        collect=lambda: ["frontend/stack.xml"],
    )


def sample_services(c: Campaign) -> None:
    folder = c.out / "sample-services"
    folder.mkdir(parents=True, exist_ok=True)
    python = PAYMENT / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
    c.run(
        "payment-service",
        [str(python), "-m", "pytest", "tests", "-p", "no:cacheprovider", f"--junitxml={folder / 'payment-service.xml'}"],
        PAYMENT,
        timeout=900,
        collect=lambda: ["sample-services/payment-service.xml"],
    )
    tests = sorted(str(path.relative_to(AUTH)) for path in (AUTH / "test").glob("*.test.js"))
    c.run(
        "auth-service",
        [
            "node", "--test",
            "--test-reporter=spec", "--test-reporter-destination=stdout",
            "--test-reporter=junit", f"--test-reporter-destination={folder / 'auth-service.xml'}",
            *tests,
        ],
        AUTH,
        timeout=600,
        collect=lambda: ["sample-services/auth-service.xml"],
    )


def npm_audit(c: Campaign) -> None:
    # Known vulnerabilities in the frontend's dependencies, its tools included. The JSON report is
    # the step's log; npm exits non-zero when it finds any.
    c.run("frontend-audit", [tool("npm"), "audit", "--json"], FRONTEND, timeout=300)


STEPS: dict[str, Callable[[Campaign], None]] = {
    "plugin": plugin_tests,
    "plugin-mutation": plugin_mutation,
    "plugin-experiments": plugin_experiments,
    "backend-offline": lambda c: backend(c, "not live and not e2e and not integration", "backend-offline", append=False),
    "backend-integration": lambda c: backend(c, "integration", "backend-integration", append=True),
    "backend-e2e": lambda c: backend(c, "e2e", "backend-e2e", append=True, timeout=7200),
    "backend-live": lambda c: backend(c, "live", "backend-live", append=True),
    "frontend-unit": frontend_unit,
    "browser-flows": lambda c: playwright(c, "browser-flows", []),
    "lighthouse": lambda c: playwright(c, "lighthouse", ["--project=lighthouse"], {"LIGHTHOUSE": "1"}),
    "stack-system": stack_system,
    "sample-services": sample_services,
    "frontend-audit": npm_audit,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", choices=sorted(STEPS), help="run only these steps")
    parser.add_argument("--allow-dirty", action="store_true", help="run on uncommitted changes")
    args = parser.parse_args()

    if git("status", "--porcelain") and not args.allow_dirty:
        print("The working tree has uncommitted changes. Results must belong to a commit:")
        print("commit first, or pass --allow-dirty for a trial run.")
        return 2
    commit = git("rev-parse", "HEAD")
    campaign = Campaign(REPO_ROOT / ".tmp" / "campaign" / commit[:7], commit)
    for name in args.only or list(STEPS):
        STEPS[name](campaign)

    failed = [step for step in campaign.steps if step.exit_code != 0]
    print(f"\n{len(campaign.steps)} steps at {commit[:7]}; {len(failed)} did not exit 0:")
    for step in failed:
        print(f"  {step.name}: exit {step.exit_code} {step.note} (see {step.log})")
    print(f"manifest: {campaign.out / 'manifest.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
