#!/usr/bin/env python3
"""Phase acceptance checks for the Intelligent CI/CD Orchestrator.

One script, one exit code, no hidden state. `python scripts/verify.py --phase N` runs every
check for phases 0 to N, prints one line per check, and finishes with ALL CHECKS PASSED or
"<n> CHECKS FAILED". Exit code 0 or 1.

A check is a plain function taking no arguments and returning a Result: a name, a boolean and
a message. Nothing here may mutate the repository, start a container or write a file outside
the scratch directory. Checks must be safe to run in any order, any number of times.

Adding a check: write the function, decorate it with @check(phase, "name"), done. The registry
is ordered by phase then by registration order.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Highest phase this script knows about. Bumped as phases land.
MAX_PHASE = 8


@dataclass(frozen=True)
class Result:
    """The outcome of one check."""

    ok: bool
    message: str


CheckFn = Callable[[], Result]


@dataclass(frozen=True)
class Check:
    """A registered check, with the phase that owns it."""

    phase: int
    name: str
    fn: CheckFn


_REGISTRY: list[Check] = []


def check(phase: int, name: str) -> Callable[[CheckFn], CheckFn]:
    """Register a check under a phase. Registration order is preserved."""

    def decorator(fn: CheckFn) -> CheckFn:
        _REGISTRY.append(Check(phase=phase, name=name, fn=fn))
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ok(message: str) -> Result:
    return Result(ok=True, message=message)


def fail(message: str) -> Result:
    return Result(ok=False, message=message)


def run(args: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its output. Never raises on a non-zero exit."""
    return subprocess.run(
        args,
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return run(["git", *args])


def have(tool: str) -> bool:
    """True when a tool is callable. Used to skip checks that need absent tooling."""
    probe = "--version"
    try:
        return run([tool, probe], timeout=30).returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Phase 0: repository foundation
# ---------------------------------------------------------------------------

# From BUILD_PROMPT.md Part 4.1. Every one of these must exist for later phases
# to have somewhere to put their work.
SKELETON = [
    "plugin",
    "jenkins/controller",
    "jenkins/agent",
    "jenkins/casc",
    "jenkins/reference-configs",
    "backend/app/api",
    "backend/app/core",
    "backend/app/db",
    "backend/app/services",
    "backend/app/ai/prompts",
    "backend/app/generation",
    "backend/app/ws",
    "backend/tests",
    "frontend",
    "sample-services/payment-service",
    "sample-services/auth-service",
    "catalog",
    "experiment",
    "eval",
    "scripts/report",
    "docs",
    "legacy/m2-poc",
]


@check(0, "skeleton folders exist")
def check_skeleton() -> Result:
    missing = [d for d in SKELETON if not (REPO_ROOT / d).is_dir()]
    if missing:
        return fail(f"{len(missing)} missing: {', '.join(missing)}")
    return ok(f"all {len(SKELETON)} present")


@check(0, "root documents exist")
def check_root_docs() -> Result:
    required = [
        "BUILD_PROMPT.md",
        "CLAUDE.md",
        "PROGRESS.md",
        "PLAN.md",
        "README.md",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
        ".env.example",
    ]
    missing = [f for f in required if not (REPO_ROOT / f).is_file()]
    if missing:
        return fail(f"missing: {', '.join(missing)}")
    return ok(f"all {len(required)} present")


@check(0, "tracking documents exist")
def check_tracking_docs() -> Result:
    required = [
        "docs/decisions.md",
        "docs/report-updates.md",
        "docs/versions.md",
        "docs/m2-baseline.md",
    ]
    missing = [f for f in required if not (REPO_ROOT / f).is_file()]
    if missing:
        return fail(f"missing: {', '.join(missing)}")
    return ok(f"all {len(required)} present")


@check(0, "legacy/m2-poc present")
def check_legacy_present() -> Result:
    legacy = REPO_ROOT / "legacy" / "m2-poc"
    markers = [
        legacy / "dynamic-queue-optimizer" / "pom.xml",
        legacy / "experiment" / "scripts" / "analyze.py",
        legacy / "experiment" / "results" / "comparison.json",
    ]
    missing = [str(m.relative_to(REPO_ROOT)) for m in markers if not m.is_file()]
    if missing:
        return fail(f"missing: {', '.join(missing)}")
    return ok("plugin sources, harness and results all present")


@check(0, "legacy/m2-poc unmodified against m2-final")
def check_legacy_frozen() -> Result:
    """The frozen copy must be byte-identical to the tag. Rule 1.5 forbids editing it."""
    tags = git("tag", "--list", "m2-final")
    if tags.returncode != 0:
        return fail("git unavailable or not a repository")
    if not tags.stdout.strip():
        return fail("tag m2-final does not exist; create it on the commit that froze Milestone 2")

    diff = git("diff", "--stat", "m2-final", "--", "legacy")
    if diff.returncode != 0:
        return fail(f"git diff failed: {diff.stderr.strip()}")
    if diff.stdout.strip():
        changed = [ln for ln in diff.stdout.strip().splitlines() if ln.strip()]
        return fail(f"legacy/ differs from m2-final in {len(changed) - 1} file(s); revert them")

    untracked = git("ls-files", "--others", "--exclude-standard", "legacy")
    if untracked.stdout.strip():
        n = len(untracked.stdout.strip().splitlines())
        return fail(f"{n} untracked file(s) under legacy/; nothing may be added there")

    return ok("byte-identical to the tag, nothing added")


# Patterns that must never be tracked by Git. Keys are what to report.
SECRET_PATTERNS: dict[str, str] = {
    ".env file": r"(^|/)\.env$",
    ".env.local file": r"(^|/)\.env\.local$",
    ".secrets directory": r"(^|/)\.secrets/",
    "Jenkins secret.key": r"(^|/)secret\.key",
    "Jenkins secrets store": r"(^|/)secrets/",
    "private key": r"\.(pem|p12|pfx)$",
    "Jenkins identity key": r"identity\.key\.enc$",
}


@check(0, "no secrets tracked by Git")
def check_no_secrets() -> Result:
    listing = git("ls-files")
    if listing.returncode != 0:
        return fail("git unavailable or not a repository")
    tracked = listing.stdout.splitlines()

    found: list[str] = []
    for label, pattern in SECRET_PATTERNS.items():
        hits = [f for f in tracked if re.search(pattern, f)]
        if hits:
            found.append(f"{label} ({len(hits)}): {hits[0]}")
    if found:
        return fail("; ".join(found))
    return ok(f"{len(tracked)} tracked files, none matching {len(SECRET_PATTERNS)} secret patterns")


@check(0, ".gitattributes sets LF for the required types")
def check_gitattributes() -> Result:
    path = REPO_ROOT / ".gitattributes"
    if not path.is_file():
        return fail(".gitattributes is missing")
    text = path.read_text(encoding="utf-8")

    # These run inside Linux containers; CRLF breaks a shebang and breaks `sh`.
    required = ["*.sh", "*.py", "*.groovy", "Jenkinsfile", "*.yaml", "*.yml", "Dockerfile"]
    missing = []
    for pattern in required:
        # The pattern must appear on a line that also pins eol=lf.
        if not any(
            line.split()[0] == pattern and "eol=lf" in line
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ):
            missing.append(pattern)
    if missing:
        return fail(f"no eol=lf rule for: {', '.join(missing)}")
    return ok(f"all {len(required)} types pinned to LF")


@check(0, "legacy/ is exempt from line-ending normalisation")
def check_legacy_not_normalised() -> Result:
    """Without this, `* text=auto eol=lf` would rewrite files rule 1.5 forbids modifying."""
    path = REPO_ROOT / ".gitattributes"
    if not path.is_file():
        return fail(".gitattributes is missing")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        parts = stripped.split()
        if parts[0] in ("legacy/**", "legacy/*", "/legacy/**") and "-text" in parts[1:]:
            return ok(f"`{stripped}` keeps the frozen copy byte for byte")
    return fail("no `legacy/** -text` rule; normalisation would modify the frozen copy")


EXPECTED_CI_JOBS = {"plugin", "backend", "frontend"}


def _scan_yaml_mapping_keys(text: str, indent: int, under: str | None = None) -> list[str]:
    """Collect `key:` names at one indent depth, without a YAML parser.

    Used only as a fallback when PyYAML is unavailable. It understands the subset the CI
    workflow is written in: block mappings, `#` comments and blank lines. It deliberately
    does not try to handle flow collections, anchors or multi-line scalars, and it skips
    block scalar bodies (`|`, `>`) so that shell lines inside a `run:` are never mistaken
    for keys.
    """
    keys: list[str] = []
    in_section = under is None
    section_indent = -1
    block_scalar_indent: int | None = None

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        current = len(raw) - len(raw.lstrip())

        # Inside a `|` or `>` body, ignore everything more indented than its key.
        if block_scalar_indent is not None:
            if current > block_scalar_indent:
                continue
            block_scalar_indent = None

        stripped = raw.strip()
        if re.match(r"^[A-Za-z_][\w.-]*\s*:\s*[|>][-+]?\s*$", stripped):
            block_scalar_indent = current
            continue

        if under is not None:
            if current == 0:
                # A new top-level key ends the section we were reading.
                in_section = stripped.split(":")[0].strip() == under
                section_indent = current
                continue
            if not in_section:
                continue
            if current <= section_indent:
                continue

        if current != indent:
            continue
        match = re.match(r"^([A-Za-z_][\w.-]*)\s*:", stripped)
        if match:
            keys.append(match.group(1))
    return keys


@check(0, "CI workflow parses")
def check_ci_workflow() -> Result:
    path = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    if not path.is_file():
        return fail(".github/workflows/ci.yml is missing")
    text = path.read_text(encoding="utf-8")

    try:
        import yaml
    except ImportError:
        # PyYAML is the preferred path and CI installs it. Locally it may be absent, and a
        # phase gate must not fail because an unrelated package could not be downloaded.
        # This fallback checks structure rather than full syntax, and says so.
        top = _scan_yaml_mapping_keys(text, indent=0)
        if "jobs" not in top:
            return fail("no top-level `jobs` key")
        if "on" not in top:
            return fail("no top-level `on` key")
        jobs = _scan_yaml_mapping_keys(text, indent=2, under="jobs")
        missing = EXPECTED_CI_JOBS - set(jobs)
        if missing:
            return fail(f"missing job(s): {', '.join(sorted(missing))}")
        return ok(
            f"{len(jobs)} jobs: {', '.join(jobs)} "
            "(structure only; install PyYAML for a full parse)"
        )

    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        first = str(exc).splitlines()[0]
        return fail(f"invalid YAML: {first}")
    if not isinstance(doc, dict):
        return fail("top level is not a mapping")
    # YAML 1.1 reads a bare `on` as the boolean True, so accept either spelling.
    if "jobs" not in doc:
        return fail("no `jobs` key")
    if "on" not in doc and True not in doc:
        return fail("no `on` key")
    jobs = doc["jobs"]
    if not isinstance(jobs, dict) or not jobs:
        return fail("`jobs` is empty")
    missing = EXPECTED_CI_JOBS - set(jobs)
    if missing:
        return fail(f"missing job(s): {', '.join(sorted(missing))}")
    return ok(f"{len(jobs)} jobs: {', '.join(jobs)}")


@check(0, "M2 baseline figures match the legacy result files")
def check_m2_baseline_figures() -> Result:
    """Guards docs/m2-baseline.md against drifting from the files it describes.

    Recomputes the two headline Milestone 2 figures straight from the frozen result files and
    compares them with what the document claims. This is the same principle as
    AppendixCExampleTest: a number in a document that is not derived from data will eventually
    be wrong, and nobody will notice.
    """
    results = REPO_ROOT / "legacy" / "m2-poc" / "experiment" / "results"
    baseline_path = results / "baseline-results.json"
    plugin_path = results / "plugin-results-run4.json"
    spec_path = REPO_ROOT / "legacy" / "m2-poc" / "experiment" / "scripts" / "jobs.json"
    for p in (baseline_path, plugin_path, spec_path):
        if not p.is_file():
            return fail(f"missing {p.relative_to(REPO_ROOT)}")

    spec = {j["name"]: j for j in json.loads(spec_path.read_text(encoding="utf-8"))}

    def high_band_mean_wait(run_path: Path) -> float:
        run = json.loads(run_path.read_text(encoding="utf-8"))
        t0 = run["t0"]
        waits = [
            (j["startTime"] - t0) / 1000.0
            for j in run["jobs"]
            if j["name"] in spec
            and spec[j["name"]]["priority"] == "HIGH"
            and j.get("startTime") is not None
        ]
        if not waits:
            raise ValueError(f"no HIGH-band jobs with a start time in {run_path.name}")
        return sum(waits) / len(waits)

    try:
        got_baseline = high_band_mean_wait(baseline_path)
        got_plugin = high_band_mean_wait(plugin_path)
    except (KeyError, ValueError) as exc:
        return fail(f"could not recompute: {exc}")

    doc = REPO_ROOT / "docs" / "m2-baseline.md"
    if not doc.is_file():
        return fail("docs/m2-baseline.md is missing")
    text = doc.read_text(encoding="utf-8")

    for label, value in (("baseline", got_baseline), ("plugin", got_plugin)):
        if f"{value:.2f}" not in text:
            return fail(
                f"recomputed HIGH-band {label} wait is {value:.2f} s "
                f"but that figure does not appear in docs/m2-baseline.md"
            )
    return ok(f"HIGH-band wait {got_baseline:.2f} s -> {got_plugin:.2f} s, as documented")


@check(0, "no /scriptText outside legacy/")
def check_no_script_console() -> Result:
    """Rule 1.5: the Jenkins script console is never called from our own code.

    Enforced from Phase 0 so it can never be introduced in the first place. Milestone 2's
    harness used it, which is why legacy/ is excluded rather than cleaned.
    """
    listing = git("ls-files")
    if listing.returncode != 0:
        return fail("git unavailable or not a repository")

    offenders: list[str] = []
    for rel in listing.stdout.splitlines():
        if rel.startswith("legacy/") or rel in ("BUILD_PROMPT.md", "CLAUDE.md"):
            continue
        if rel.startswith("docs/") or rel == "scripts/verify.py":
            continue
        path = REPO_ROOT / rel
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "/scriptText" in body or "/script " in body:
            offenders.append(rel)
    if offenders:
        return fail(f"script console referenced in: {', '.join(offenders[:5])}")
    return ok("no reference in application, experiment or test code")


# ---------------------------------------------------------------------------
# Phases 1 to 8
#
# Each phase's checks are added by that phase's final task, so that a check and
# the thing it verifies land in the same commit. Until then the phase reports
# that it has no checks yet, and --phase N for an unimplemented N fails loudly
# rather than passing vacuously.
# ---------------------------------------------------------------------------

IMPLEMENTED_PHASES = {0}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="verify.py",
        description="Run every acceptance check for phases 0 to N.",
    )
    parser.add_argument(
        "--phase",
        type=int,
        required=True,
        metavar="N",
        help=f"run the checks for phases 0 to N (0-{MAX_PHASE})",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the checks that would run, then exit",
    )
    args = parser.parse_args()

    if not 0 <= args.phase <= MAX_PHASE:
        print(f"error: --phase must be between 0 and {MAX_PHASE}", file=sys.stderr)
        return 2

    unimplemented = sorted(p for p in range(args.phase + 1) if p not in IMPLEMENTED_PHASES)
    selected = [c for c in _REGISTRY if c.phase <= args.phase]

    if args.list:
        for c in selected:
            print(f"phase {c.phase}  {c.name}")
        print(f"\n{len(selected)} checks for phases 0 to {args.phase}")
        return 0

    print(f"verify.py --phase {args.phase}   ({len(selected)} checks)\n")

    failed = 0
    current_phase = -1
    for c in selected:
        if c.phase != current_phase:
            current_phase = c.phase
            print(f"-- phase {current_phase} " + "-" * (58 - len(str(current_phase))))
        try:
            result = c.fn()
        except Exception as exc:  # a check that crashes is a check that failed
            result = fail(f"check raised {type(exc).__name__}: {exc}")
        mark = "PASS" if result.ok else "FAIL"
        print(f"[{mark}] {c.name}\n       {result.message}")
        if not result.ok:
            failed += 1

    print()
    if unimplemented:
        listed = ", ".join(str(p) for p in unimplemented)
        print(f"{len(unimplemented)} PHASE(S) HAVE NO CHECKS YET: {listed}")
        print("A phase with no checks cannot pass. Add them in that phase's final task.")
        return 1
    if failed:
        print(f"{failed} CHECKS FAILED")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
