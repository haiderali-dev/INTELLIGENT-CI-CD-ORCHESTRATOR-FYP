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
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def run(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its output. Never raises on a non-zero exit.

    ``env`` is laid over the inherited environment, never in place of it: a subprocess given a
    minimal environment loses ``SystemRoot`` on Windows and with it DNS (CLAUDE.md).
    """
    return subprocess.run(
        args,
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
        # Tools print UTF-8, and Windows' default code page cannot decode all of it: Vitest's U+276F
        # (byte 0x9d) crashed the reader and failed a gate run with no output (2026-10-16).
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env={**os.environ, **env} if env else None,
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


# "flows" since T6.8: 4.7.6's browser flows, against the backend in fake mode.
EXPECTED_CI_JOBS = {"plugin", "backend", "frontend", "flows"}


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


# Executable or deployable file types. Prose cannot call an HTTP endpoint, so markdown and
# the report are out of scope: the rule is about code, and documenting the prohibition must
# not trip the check that enforces it.
CODE_SUFFIXES = frozenset(
    {
        ".py", ".java", ".groovy", ".kt", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
        ".sh", ".bash", ".ps1", ".rb", ".go", ".yaml", ".yml", ".xml", ".json", ".toml",
        ".cfg", ".ini", ".jelly", ".sql", ".tmpl", ".j2", ".dockerfile",
    }
)
CODE_FILENAMES = frozenset({"Jenkinsfile", "Dockerfile", "Makefile"})

# Jenkins script console endpoints, matched as URL paths rather than as bare words, so that
# a word like "description" or a sentence about scripts cannot produce a false positive.
SCRIPT_CONSOLE_RE = re.compile(r"""/scriptText\b|/script(?=["'\s,)/?]|$)|\bdoScript\b""")

# The guards themselves. Each must contain the pattern in order to look for it, so each is
# exempt from its own rule. Nothing else belongs in this set.
SCRIPT_CONSOLE_GUARD_FILES = frozenset(
    {"scripts/verify.py", "backend/tests/test_no_script_console.py"}
)


def _is_code_file(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if name in CODE_FILENAMES:
        return True
    suffix = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    return suffix in CODE_SUFFIXES


@check(0, "no Jenkins script console call in our code")
def check_no_script_console() -> Result:
    """Rule 1.5: the Jenkins script console is never called from our own code.

    Enforced from Phase 0, not Phase 3, so it can never be introduced in the first place.
    Milestone 2's harness posted Groovy to /scriptText, which is why legacy/ is excluded here
    rather than cleaned: it is frozen evidence, not live code.

    Scope is code and configuration only. Two files are excluded, both for the same reason: a
    guard cannot search for a pattern without containing it. This script is one; the backend's
    own equivalent test is the other.
    """
    tracked = git("ls-files")
    if tracked.returncode != 0:
        return fail("git unavailable or not a repository")
    # Untracked-but-not-ignored files count too. A guard that sees only committed code
    # misses exactly the code about to be committed, which is when it matters most.
    untracked = git("ls-files", "--others", "--exclude-standard")

    scanned = 0
    offenders: list[str] = []
    candidates = sorted(set(tracked.stdout.splitlines()) | set(untracked.stdout.splitlines()))
    for rel in candidates:
        if rel.startswith("legacy/") or rel in SCRIPT_CONSOLE_GUARD_FILES:
            continue
        if not _is_code_file(rel):
            continue
        path = REPO_ROOT / rel
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        if SCRIPT_CONSOLE_RE.search(body):
            offenders.append(rel)
    if offenders:
        return fail(f"script console referenced in: {', '.join(offenders[:5])}")
    return ok(f"{scanned} code files scanned, no reference")


# ---------------------------------------------------------------------------
# Phases 1 to 8
#
# Each phase's checks are added by that phase's final task, so that a check and
# the thing it verifies land in the same commit. Until then the phase reports
# that it has no checks yet, and --phase N for an unimplemented N fails loudly
# rather than passing vacuously.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Phase 2: plugin
#
# The checks here that need a running Jenkins live in T2.14 and are blocked on
# Docker. Everything below is static or local, so it runs today.
# ---------------------------------------------------------------------------

# From BUILD_PROMPT Part 4.3.10. Every one of these must exist as a test class.
REQUIRED_PLUGIN_TESTS = [
    "AppendixCExampleTest",
    "ScoreComponentTest",
    "AgingTest",
    "UnionFindKahnTest",
    "SimilarityEstimatorTest",
    "PriorityJobHeapTest",
    "SchedulerOverheadTest",
    "FreestylePriorityIT",
    "PipelinePriorityIT",
    "MultiExecutorIT",
    "DependencyGateIT",
    "MissingUpstreamIT",
    "DeclarativeOptionsIT",
    "ObserveOnlyIT",
    "CacheEvictionRegressionIT",
    "ConfigAsCodeIT",
    "ApiJsonIT",
]


@check(2, "every test named in Part 4.3.10 exists")
def check_required_plugin_tests() -> Result:
    """A named test that does not exist is a requirement nobody noticed was unmet."""
    test_root = REPO_ROOT / "plugin" / "src" / "test" / "java"
    if not test_root.is_dir():
        return fail("plugin/src/test/java does not exist")

    present = {path.stem for path in test_root.rglob("*.java")}
    missing = [name for name in REQUIRED_PLUGIN_TESTS if name not in present]
    if missing:
        return fail(f"{len(missing)} missing: {', '.join(missing)}")
    return ok(f"all {len(REQUIRED_PLUGIN_TESTS)} present")


@check(2, "integration tests are bound to the Maven lifecycle")
def check_failsafe_bound() -> Result:
    """Guards the specific hollow-green this project hit.

    Surefire matches *Test only. Without Failsafe bound, `mvn verify` reports BUILD SUCCESS over
    the unit tests while silently skipping every *IT class, and the phase's acceptance criterion
    passes vacuously.
    """
    pom = REPO_ROOT / "plugin" / "pom.xml"
    if not pom.is_file():
        return fail("plugin/pom.xml does not exist")
    text = pom.read_text(encoding="utf-8")

    if "maven-failsafe-plugin" not in text:
        return fail("maven-failsafe-plugin is not declared; `mvn verify` would skip every *IT")
    if "<goal>integration-test</goal>" not in text:
        return fail("Failsafe is declared but its integration-test goal is not bound")
    if "<goal>verify</goal>" not in text:
        return fail("Failsafe's verify goal is not bound, so a failing IT would not fail the build")
    return ok("integration-test and verify goals both bound")


@check(2, "the scoring formula matches the report")
def check_scoring_constants() -> Result:
    """The one thing Milestone 2 got wrong that nothing detected.

    A static guard, complementing AppendixCExampleTest: the published weights and urgency values
    must appear in the source. Cheap, and it fails on a careless edit even before the tests run.
    """
    calculator = (
        REPO_ROOT
        / "plugin/src/main/java/io/jenkins/plugins/queueoptimizer/scoring/PriorityScoreCalculator.java"
    )
    level = REPO_ROOT / "plugin/src/main/java/io/jenkins/plugins/queueoptimizer/model/PriorityLevel.java"
    for path in (calculator, level):
        if not path.is_file():
            return fail(f"missing {path.relative_to(REPO_ROOT)}")

    level_text = level.read_text(encoding="utf-8")
    for name, value in (("HIGH", "1.0"), ("MEDIUM", "0.6"), ("LOW", "0.3")):
        if f"{name}({value})" not in level_text:
            return fail(f"PriorityLevel.{name} is not {value}; the report's U values are 1.0/0.6/0.3")

    calc_text = calculator.read_text(encoding="utf-8")
    if "withReportDefaults" not in calc_text:
        return fail("PriorityScoreCalculator has no withReportDefaults factory")
    if "0.5, 0.3, 0.2, 0.05, 5, 0.15" not in calc_text:
        return fail(
            "the report defaults (0.5 U, 0.3 D, 0.2 T, aging 0.05 per 5 min capped 0.15) "
            "are not the ones withReportDefaults uses"
        )
    return ok("U = 1.0/0.6/0.3 and weights 0.5/0.3/0.2 with aging 0.05 per 5 min, cap 0.15")


@check(2, "plugin artifact was built")
def check_hpi_built() -> Result:
    hpi = list((REPO_ROOT / "plugin" / "target").glob("*.hpi")) if (REPO_ROOT / "plugin" / "target").is_dir() else []
    if not hpi:
        return fail("no .hpi under plugin/target/; run `cd plugin && mvn -B verify`")
    size_kb = hpi[0].stat().st_size // 1024
    return ok(f"{hpi[0].name} ({size_kb} KB)")


# ---------------------------------------------------------------------------
# Phase 1: infrastructure
#
# Split deliberately into checks that need only the repository and checks that
# need a Docker daemon. The first group runs today; the second reports the exact
# missing prerequisite rather than a generic failure, because "Docker is not
# installed" and "Jenkins rejected the bot token" need different fixes.
# ---------------------------------------------------------------------------

DOCKER_FILES = [
    "docker-compose.yml",
    ".dockerignore",
    "jenkins/controller/Dockerfile",
    "jenkins/controller/plugins.txt",
    "jenkins/agent/Dockerfile",
    "jenkins/casc/dev.yaml",
    "jenkins/casc/experiment-baseline.yaml",
    "jenkins/casc/experiment-plugin.yaml",
    "backend/Dockerfile",
]

# Secrets that must never be silently defaulted by Compose.
COMPOSE_REQUIRED_SECRETS = [
    "JENKINS_ADMIN_PASSWORD",
    "JENKINS_BOT_PASSWORD",
    "METRICS_TOKEN",
    "POSTGRES_PASSWORD",
    "JWT_SECRET",
    "SEED_ADMIN_PASSWORD",
]

CASC_FILES = ("dev.yaml", "experiment-baseline.yaml", "experiment-plugin.yaml")


def _load_yaml(path: Path) -> tuple[Any, str | None]:
    """Parse a YAML file, returning (document, error-message)."""
    try:
        import yaml
    except ImportError:
        return None, "PyYAML is not installed; run `python -m pip install pyyaml`"
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc).splitlines()[0]}"


@check(1, "Docker and Compose files exist")
def check_docker_files_exist() -> Result:
    missing = [f for f in DOCKER_FILES if not (REPO_ROOT / f).is_file()]
    if missing:
        return fail(f"{len(missing)} missing: {', '.join(missing)}")
    return ok(f"all {len(DOCKER_FILES)} present")


@check(1, "docker-compose.yml is valid and matches Part 4.2.3")
def check_compose_shape() -> Result:
    path = REPO_ROOT / "docker-compose.yml"
    if not path.is_file():
        return fail("docker-compose.yml does not exist")
    doc, error = _load_yaml(path)
    if error:
        return fail(error)
    if not isinstance(doc, dict) or "services" not in doc:
        return fail("no `services` mapping")

    services = doc["services"]
    profiled = {name for name, node in services.items() if node.get("profiles")}
    default = set(services) - profiled
    problems: list[str] = []

    for name in ("postgres", "jenkins-dev", "agent-1", "agent-2", "backend"):
        if name not in default:
            problems.append(f"{name} is not a default service")
    for name in ("jenkins-baseline", "jenkins-plugin"):
        if name not in profiled:
            problems.append(f"{name} should sit behind the experiment profile")

    published = {
        name: " ".join(str(p) for p in node.get("ports", [])) for name, node in services.items()
    }
    for name, port in (
        ("jenkins-dev", "8087"),
        ("backend", "8000"),
        ("jenkins-baseline", "8085"),
        ("jenkins-plugin", "8086"),
    ):
        if port not in published.get(name, ""):
            problems.append(f"{name} does not publish {port}")

    for name in ("postgres", "jenkins-dev", "backend"):
        if "healthcheck" not in services.get(name, {}):
            problems.append(f"{name} has no healthcheck")

    backend_deps = services.get("backend", {}).get("depends_on", {})
    if not (
        isinstance(backend_deps, dict)
        and backend_deps.get("postgres", {}).get("condition") == "service_healthy"
    ):
        problems.append("backend does not wait for postgres to be healthy")

    for volume in ("postgres-data", "jenkins-dev-home"):
        if volume not in (doc.get("volumes") or {}):
            problems.append(f"named volume {volume} is missing")

    if problems:
        return fail("; ".join(problems))
    return ok(f"{len(services)} services, {len(default)} default, {len(profiled)} profiled")


@check(1, "Compose refuses to start rather than defaulting a secret")
def check_compose_secret_guards() -> Result:
    """A defaulted password is worse than a failed start: it starts, and it is insecure."""
    path = REPO_ROOT / "docker-compose.yml"
    if not path.is_file():
        return fail("docker-compose.yml does not exist")
    text = path.read_text(encoding="utf-8")

    unguarded = [name for name in COMPOSE_REQUIRED_SECRETS if "${" + name + ":?" not in text]
    if unguarded:
        return fail("not using the fail-loud form: " + ", ".join(unguarded))
    return ok(f"all {len(COMPOSE_REQUIRED_SECRETS)} secrets fail loudly when unset")


@check(1, "JCasC files are valid and the two arms differ only in optimizerEnabled")
def check_casc_files() -> Result:
    casc = REPO_ROOT / "jenkins" / "casc"
    docs: dict[str, Any] = {}
    for name in CASC_FILES:
        path = casc / name
        if not path.is_file():
            return fail(f"missing jenkins/casc/{name}")
        doc, error = _load_yaml(path)
        if error:
            return fail(f"{name}: {error}")
        docs[name] = doc

    dev = docs["dev.yaml"]
    if dev.get("jenkins", {}).get("numExecutors") != 0:
        return fail("dev.yaml must set numExecutors: 0; the controller runs zero builds")

    entries = dev["jenkins"]["authorizationStrategy"]["globalMatrix"]["entries"]
    bot = next(
        (
            e["user"]["permissions"]
            for e in entries
            if e.get("user", {}).get("name") == "orchestrator-bot"
        ),
        None,
    )
    if bot is None:
        return fail("dev.yaml grants the orchestrator-bot no permissions")
    if "Overall/Administer" in bot:
        return fail("the bot must not hold Overall/Administer; it is a least-privilege account")

    baseline = docs["experiment-baseline.yaml"]["unclassified"]["dynamicQueueOptimizer"]
    plugin = docs["experiment-plugin.yaml"]["unclassified"]["dynamicQueueOptimizer"]
    if baseline.get("optimizerEnabled") is not False:
        return fail("the baseline arm must set optimizerEnabled: false")
    if plugin.get("optimizerEnabled") is not True:
        return fail("the plugin arm must set optimizerEnabled: true")

    differing = {k for k in set(baseline) | set(plugin) if baseline.get(k) != plugin.get(k)}
    extra = differing - {"optimizerEnabled"}
    if extra:
        return fail(
            "the two arms must differ only in optimizerEnabled, but also differ in: "
            + ", ".join(sorted(extra))
        )
    return ok("dev plus two arms differing only in optimizerEnabled")


@check(1, "JCasC sets no floating-point optimizer field (D-017)")
def check_casc_avoids_floats() -> Result:
    """JCasC silently drops this configuration's double fields, so setting one would lie.

    See docs/decisions.md D-017 and D-019. The code defaults are the report's Appendix D values,
    so omitting them is correct; setting them would produce a file that disagrees with the
    running system.
    """
    problems: list[str] = []
    for name in CASC_FILES:
        path = REPO_ROOT / "jenkins" / "casc" / name
        if not path.is_file():
            return fail(f"missing jenkins/casc/{name}")
        doc, error = _load_yaml(path)
        if error:
            return fail(f"{name}: {error}")
        block = doc.get("unclassified", {}).get("dynamicQueueOptimizer", {})
        floats = sorted(k for k, v in block.items() if isinstance(v, float))
        if floats:
            problems.append(f"{name} sets {', '.join(floats)}")
    if problems:
        return fail("; ".join(problems) + " -- JCasC drops these silently (D-017)")
    return ok("no float fields set; the code defaults are the report's values")


@check(1, "the controller image installs the built plugin")
def check_controller_installs_plugin() -> Result:
    dockerfile = REPO_ROOT / "jenkins" / "controller" / "Dockerfile"
    if not dockerfile.is_file():
        return fail("jenkins/controller/Dockerfile does not exist")
    text = dockerfile.read_text(encoding="utf-8")
    if "dynamic-queue-optimizer.hpi" not in text:
        return fail("the Dockerfile does not copy the plugin into the reference directory")
    if "/usr/share/jenkins/ref/plugins/" not in text:
        return fail("the plugin must be copied into /usr/share/jenkins/ref/plugins/")

    hpi = REPO_ROOT / "plugin" / "target" / "dynamic-queue-optimizer.hpi"
    if not hpi.is_file():
        return fail("plugin/target/*.hpi is missing; run `cd plugin && mvn -B verify` first")
    return ok(f"COPY present and the .hpi exists ({hpi.stat().st_size // 1024} KB)")


@check(1, "controller plugins are pinned")
def check_plugins_pinned() -> Result:
    path = REPO_ROOT / "jenkins" / "controller" / "plugins.txt"
    if not path.is_file():
        return fail("jenkins/controller/plugins.txt does not exist")

    entries = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    unpinned = [e for e in entries if ":" not in e]
    if unpinned:
        return fail("not pinned to a version: " + ", ".join(unpinned))

    names = {e.split(":", 1)[0] for e in entries}
    required = {
        "configuration-as-code",
        "workflow-aggregator",
        "pipeline-model-definition",
        "pipeline-stage-view",
        "git",
        "ssh-slaves",
        "matrix-auth",
        "credentials-binding",
        "timestamper",
        "ws-cleanup",
        "structs",
    }
    missing = required - names
    if missing:
        return fail("Part 4.2.1 requires: " + ", ".join(sorted(missing)))
    return ok(f"{len(entries)} plugins, all pinned")


@check(1, "Docker is available")
def check_docker_available() -> Result:
    """The prerequisite every remaining Phase 1 check depends on.

    Its own check so the output distinguishes "Docker is missing" from "Docker is here and
    something in the stack is wrong". Those need completely different fixes.
    """
    if not have("docker"):
        return fail(
            "the docker CLI is not on PATH. Install Docker Desktop, which needs Administrator: "
            "`winget install --id Docker.DockerDesktop --source winget`, then reboot and launch it. "
            "Every check below needs a running daemon."
        )
    info = run(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=60)
    if info.returncode != 0:
        return fail(
            "the CLI is installed but the daemon is not responding; start Docker Desktop. "
            + info.stderr.strip()[:160]
        )
    return ok(f"daemon {info.stdout.strip()}")


@check(1, "docker compose config validates")
def check_compose_config() -> Result:
    if not have("docker"):
        return fail("blocked: Docker is not installed (see the check above)")
    if not (REPO_ROOT / ".env").is_file():
        return fail(
            "no .env file. Copy .env.example and fill it in; Compose cannot resolve the required "
            "secrets without it."
        )
    result = run(["docker", "compose", "config", "--quiet"], timeout=120)
    if result.returncode != 0:
        return fail(result.stderr.strip()[:300] or "docker compose config failed")
    return ok("the merged configuration is valid")


# ---------------------------------------------------------------------------
# Phase 1 and 2, live: these need a running stack. Each one reports the exact
# missing prerequisite rather than a generic failure.
# ---------------------------------------------------------------------------


def _env_file() -> dict[str, str]:
    """Parse .env. Values are used, never printed."""
    path = REPO_ROOT / ".env"
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def _jenkins_get(path: str, user: str, secret: str, timeout: int = 30) -> tuple[int, str]:
    """One authenticated GET against the dev controller."""
    import base64
    import urllib.error
    import urllib.request

    url = "http://localhost:8087" + path
    request = urllib.request.Request(url)
    token = base64.b64encode(f"{user}:{secret}".encode()).decode("ascii")
    request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def _jenkins_trigger(job: str, params: dict[str, str], user: str, secret: str) -> int:
    """Trigger a build on the dev controller. Returns the HTTP status (201 on success).

    Fetches a crumb first and keeps one cookie jar for both requests: Jenkins binds the crumb to
    the HTTP session, so a crumb fetched without the session cookie is refused (see bootstrap.py).
    """
    import base64
    import http.cookiejar
    import urllib.error
    import urllib.parse
    import urllib.request

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    auth = "Basic " + base64.b64encode(f"{user}:{secret}".encode()).decode("ascii")
    try:
        crumb_request = urllib.request.Request("http://localhost:8087/crumbIssuer/api/json")
        crumb_request.add_header("Authorization", auth)
        with opener.open(crumb_request, timeout=30) as response:
            crumb = json.loads(response.read().decode("utf-8"))
        path = f"/job/{job}/buildWithParameters" if params else f"/job/{job}/build"
        request = urllib.request.Request(
            "http://localhost:8087" + path,
            data=urllib.parse.urlencode(params).encode() if params else b"",
        )
        request.add_header("Authorization", auth)
        request.add_header(crumb["crumbRequestField"], crumb["crumb"])
        with opener.open(request, timeout=30) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0


def _bot_credentials() -> tuple[str, str] | str:
    """The bot user and token, or a message explaining what is missing."""
    env = _env_file()
    if not env:
        return "no .env file; copy .env.example and run scripts/bootstrap.py"
    user = env.get("JENKINS_USER", "orchestrator-bot")
    token = env.get("JENKINS_TOKEN", "")
    if not token:
        return "JENKINS_TOKEN is empty; run `python scripts/bootstrap.py --token-only`"
    return user, token


@check(1, "jenkins-dev answers with the bot token")
def check_jenkins_bot_token() -> Result:
    credentials = _bot_credentials()
    if isinstance(credentials, str):
        return fail(credentials)
    user, token = credentials

    status, body = _jenkins_get("/api/json?tree=numExecutors", user, token)
    if status == 0:
        return fail(f"jenkins-dev unreachable at localhost:8087 ({body[:120]}). Is the stack up?")
    if status != 200:
        return fail(f"GET /api/json returned {status} for {user}")
    return ok(f"authenticated as {user}")


@check(1, "controller runs zero executors")
def check_controller_zero_executors() -> Result:
    credentials = _bot_credentials()
    if isinstance(credentials, str):
        return fail(credentials)
    user, token = credentials

    status, body = _jenkins_get("/api/json?tree=numExecutors", user, token)
    if status != 200:
        return fail(f"GET /api/json returned {status}")
    try:
        count = json.loads(body).get("numExecutors")
    except ValueError:
        return fail("could not parse the controller's /api/json")
    if count != 0:
        return fail(f"the controller reports {count} executors; Part 4.2.2 requires 0")
    return ok("0, so all work goes to the labelled agents")


@check(1, "both agents are online")
def check_agents_online() -> Result:
    credentials = _bot_credentials()
    if isinstance(credentials, str):
        return fail(credentials)
    user, token = credentials

    status, body = _jenkins_get(
        "/computer/api/json?tree=computer[displayName,offline,numExecutors,assignedLabels[name]]",
        user,
        token,
    )
    if status != 200:
        return fail(f"GET /computer/api/json returned {status}")
    try:
        computers = json.loads(body)["computer"]
    except (ValueError, KeyError):
        return fail("could not parse /computer/api/json")

    agents = [c for c in computers if c.get("displayName") != "Built-In Node"]
    if not agents:
        return fail("no agents are configured")
    offline = [c["displayName"] for c in agents if c.get("offline")]
    if offline:
        return fail(
            f"offline: {', '.join(offline)}. Check the launch log at "
            "http://localhost:8087/computer/<name>/log"
        )
    linux = [
        c["displayName"]
        for c in agents
        if any(label.get("name") == "linux" for label in c.get("assignedLabels", []))
    ]
    if not linux:
        return fail("no online agent carries the `linux` label the catalog targets")
    total = sum(c.get("numExecutors", 0) for c in agents)
    return ok(f"{len(agents)} agents online, {total} executors, linux on {', '.join(linux)}")


@check(2, "the ranking endpoint answers with the bot token")
def check_ranking_endpoint() -> Result:
    """BUILD_PROMPT's Phase 2 acceptance, and the install half of T2.14."""
    credentials = _bot_credentials()
    if isinstance(credentials, str):
        return fail(credentials)
    user, token = credentials

    status, body = _jenkins_get("/dynamic-queue/api/json", user, token)
    if status == 0:
        return fail(f"jenkins-dev unreachable ({body[:120]})")
    if status == 404:
        return fail(
            "404: the plugin is not installed on jenkins-dev. Rebuild the controller image after "
            "`cd plugin && mvn -B verify`."
        )
    if status != 200:
        return fail(f"GET /dynamic-queue/api/json returned {status}")

    try:
        payload = json.loads(body)
        config = payload["configuration"]
    except (ValueError, KeyError):
        return fail("the response is not the documented shape")

    # The running plugin must be using the report's published formula, not merely be present.
    expected = {
        "weightUrgency": 0.5,
        "weightDependency": 0.3,
        "weightExecutionTime": 0.2,
        "agingBonusPerInterval": 0.05,
        "agingCap": 0.15,
        "similarityThreshold": 0.35,
        "recencyLambdaPerDay": 0.1,
    }
    wrong = [
        f"{name}={config.get(name)} (want {value})"
        for name, value in expected.items()
        if abs(float(config.get(name, -1)) - value) > 1e-6
    ]
    if wrong:
        return fail("the running configuration is not the report's: " + ", ".join(wrong))
    if not config.get("optimizerEnabled"):
        return fail("optimizerEnabled is false on jenkins-dev")
    return ok(f"200, queueLength={payload.get('queueLength')}, weights 0.5/0.3/0.2, aging 0.05 cap 0.15")


@check(2, "the plugin health and metrics endpoints answer")
def check_plugin_side_endpoints() -> Result:
    credentials = _bot_credentials()
    if isinstance(credentials, str):
        return fail(credentials)
    user, token = credentials

    for path in ("/dynamic-queue/health", "/dynamic-queue/metrics/recent?limit=1"):
        status, _ = _jenkins_get(path, user, token)
        if status != 200:
            return fail(f"GET {path} returned {status}")
    return ok("both answer 200")


# ---------------------------------------------------------------------------
# Phase 1: sample services, catalog and reference configs (T1.6 to T1.9)
# ---------------------------------------------------------------------------

SAMPLE_SERVICES = {
    "payment-service": ["deploy.sh", "Dockerfile", "scripts/build.sh", "scripts/test.sh", "app/main.py"],
    "auth-service": ["deploy.sh", "Dockerfile", "scripts/build.sh", "scripts/test.sh", "src/app.js"],
}

REFERENCE_CONFIGS = [
    "freestyle-build-test-deploy.config.xml",
    "pipeline-build-test-deploy.config.xml",
    "freestyle-downstream.config.xml",
]


@check(1, "sample services are present and complete")
def check_sample_services() -> Result:
    problems: list[str] = []
    for service, files in SAMPLE_SERVICES.items():
        root = REPO_ROOT / "sample-services" / service
        if not root.is_dir():
            problems.append(f"{service} is missing")
            continue
        for relative in files:
            if not (root / relative).is_file():
                problems.append(f"{service}/{relative}")
    if problems:
        return fail("missing: " + ", ".join(problems))
    return ok(f"{len(SAMPLE_SERVICES)} services with build, test, deploy and a Dockerfile")


@check(1, "deploy scripts refuse production")
def check_deploy_refuses_production() -> Result:
    """Rule 1.5 enforced at the one place that could actually reach a production host.

    The policy layer refuses production too, but a deploy script is executable on its own from any
    agent, so the refusal has to live in the script rather than only upstream of it.
    """
    problems: list[str] = []
    for service in SAMPLE_SERVICES:
        script = REPO_ROOT / "sample-services" / service / "deploy.sh"
        if not script.is_file():
            problems.append(f"{service}: no deploy.sh")
            continue
        text = script.read_text(encoding="utf-8")
        if "production)" not in text:
            problems.append(f"{service}: no explicit production branch")
        elif "refused" not in text.lower():
            problems.append(f"{service}: production branch does not refuse")
    if problems:
        return fail("; ".join(problems))
    return ok("both refuse production explicitly")


@check(1, "shell scripts use LF endings")
def check_shell_line_endings() -> Result:
    """A CRLF shebang fails on a Linux agent with 'bad interpreter: /bin/sh^M'.

    .gitattributes pins these to LF, but that only governs what Git stores; this checks the files
    on disk, which is what gets copied into a container.
    """
    offenders: list[str] = []
    for script in (REPO_ROOT / "sample-services").rglob("*.sh"):
        if b"\r\n" in script.read_bytes():
            offenders.append(str(script.relative_to(REPO_ROOT)))
    if offenders:
        return fail("CRLF found in: " + ", ".join(offenders))
    return ok("all sample-service shell scripts are LF")


@check(1, "catalog validates")
def check_catalog() -> Result:
    """Delegates to scripts/validate_catalog.py so there is one implementation of the rules.

    Run with --offline: the repository-reachability check needs GitHub, and a phase gate should not
    depend on network conditions. validate_catalog.py is run without --offline separately.
    """
    script = REPO_ROOT / "scripts" / "validate_catalog.py"
    if not script.is_file():
        return fail("scripts/validate_catalog.py does not exist")
    if not (REPO_ROOT / "catalog" / "services.yaml").is_file():
        return fail("catalog/services.yaml does not exist")

    result = run([sys.executable, str(script), "--offline"], timeout=120)
    if result.returncode != 0:
        tail = [line for line in result.stdout.splitlines() if line.startswith("[FAIL]")]
        return fail("; ".join(tail[:3]) or result.stdout.strip()[-200:])
    return ok("schema, production policy and structure all valid")


@check(1, "reference configs were exported from Jenkins")
def check_reference_configs() -> Result:
    """Rule 1.4: Jenkins XML templates are derived from these, never written from memory.

    The `plugin="name@version"` stamps are the evidence: Jenkins adds them on save, so their
    presence distinguishes a genuine export from hand-written XML that merely looks right.
    """
    directory = REPO_ROOT / "jenkins" / "reference-configs"
    missing = [name for name in REFERENCE_CONFIGS if not (directory / name).is_file()]
    if missing:
        return fail(
            f"{len(missing)} missing: {', '.join(missing)}. "
            "Run `python scripts/export_reference_configs.py` against a running jenkins-dev."
        )

    freestyle = (directory / "freestyle-build-test-deploy.config.xml").read_text(encoding="utf-8")
    if "plugin=" not in freestyle or "@" not in freestyle:
        return fail(
            "no plugin version stamps: this looks hand-written rather than exported from Jenkins"
        )

    # The elements Part 4.6.3 says a freestyle job needs, so a template built from this file has
    # something real to copy for each.
    required = {
        "Git SCM": "hudson.plugins.git.GitSCM",
        "branch/commit parameters": "ParametersDefinitionProperty",
        "agent label": "<assignedNode>",
        "shell steps": "hudson.tasks.Shell",
        "priority property": "JobPriorityProperty",
        "archiving": "ArtifactArchiver",
        "downstream trigger": "hudson.tasks.BuildTrigger",
    }
    absent = [label for label, needle in required.items() if needle not in freestyle]
    if absent:
        return fail("the freestyle reference lacks: " + ", ".join(absent))

    pipeline = (directory / "pipeline-build-test-deploy.config.xml").read_text(encoding="utf-8")
    if "CpsFlowDefinition" not in pipeline:
        return fail("the Pipeline reference is not a CpsFlowDefinition")
    if "<sandbox>true</sandbox>" not in pipeline:
        return fail("the Pipeline reference is not sandboxed; 4.6.3 requires a sandboxed script")
    if "dynamicQueuePriority" not in pipeline:
        return fail("the Pipeline reference does not use the dynamicQueuePriority option")

    return ok(f"{len(REFERENCE_CONFIGS)} configs, all carrying Jenkins' own plugin version stamps")


# ---------------------------------------------------------------------------
# Phase 3: backend
#
# Only the parts T3.2 delivers are checked here. The rest of Phase 3's checks
# arrive with T3.9.
# ---------------------------------------------------------------------------

# Every table BUILD_PROMPT 4.4.3 names.
REQUIRED_TABLES = [
    "users",
    "services",
    "conversations",
    "messages",
    "nl_commands",
    "generated_pipelines",
    "jobs",
    "job_runs",
    "llm_calls",
    "experiments",
    "experiment_metrics",
    "resource_samples",
    "notifications",
    "audit_logs",
]


@check(3, "Alembic is configured and has a migration")
def check_alembic_present() -> Result:
    backend = REPO_ROOT / "backend"
    missing = [
        str(p.relative_to(REPO_ROOT))
        for p in (backend / "alembic.ini", backend / "alembic" / "env.py")
        if not p.is_file()
    ]
    if missing:
        return fail("missing: " + ", ".join(missing))

    versions = backend / "alembic" / "versions"
    migrations = sorted(p for p in versions.glob("*.py") if not p.name.startswith("__"))
    if not migrations:
        return fail(
            "no migration in backend/alembic/versions/. Run "
            "`uv run alembic revision --autogenerate -m 'initial schema'`."
        )
    return ok(f"{len(migrations)} migration(s), newest {migrations[-1].name}")


@check(3, "migrations create every table in Part 4.4.3")
def check_migrations_cover_the_schema() -> Result:
    versions = REPO_ROOT / "backend" / "alembic" / "versions"
    if not versions.is_dir():
        return fail("backend/alembic/versions/ does not exist")

    source = "\n".join(
        p.read_text(encoding="utf-8")
        for p in versions.glob("*.py")
        if not p.name.startswith("__")
    )
    created = set(re.findall(r'op\.create_table\(\s*"([a-z_]+)"', source))
    missing = [name for name in REQUIRED_TABLES if name not in created]
    if missing:
        return fail(f"{len(missing)} not created by any migration: {', '.join(missing)}")
    return ok(f"all {len(REQUIRED_TABLES)} tables")


@check(3, "every migration is reversible")
def check_migrations_reversible() -> Result:
    """A migration that cannot be rolled back is one nobody can safely apply.

    demo_reset.py restores a known state before the demo; an irreversible migration turns that
    from a rollback into a reinstall.
    """
    versions = REPO_ROOT / "backend" / "alembic" / "versions"
    if not versions.is_dir():
        return fail("backend/alembic/versions/ does not exist")

    offenders: list[str] = []
    for path in versions.glob("*.py"):
        if path.name.startswith("__"):
            continue
        text = path.read_text(encoding="utf-8")
        parts = text.split("def downgrade()", 1)
        if len(parts) < 2:
            offenders.append(f"{path.name}: no downgrade()")
        elif "op." not in parts[1]:
            offenders.append(f"{path.name}: downgrade() does nothing")
    if offenders:
        return fail("; ".join(offenders))
    return ok("all downgrade cleanly")


@check(3, "seed scripts exist and are idempotent by construction")
def check_seed_scripts() -> Result:
    seed = REPO_ROOT / "backend" / "app" / "db" / "seed.py"
    if not seed.is_file():
        return fail("backend/app/db/seed.py does not exist")
    text = seed.read_text(encoding="utf-8")

    problems: list[str] = []
    if "def seed_admin" not in text:
        problems.append("no seed_admin")
    if "def seed_catalog" not in text:
        problems.append("no seed_catalog")
    # Both seeds must look before they write, or a restart duplicates rows.
    if text.count("select(") < 2:
        problems.append("a seed writes without checking for an existing row first")
    if problems:
        return fail("; ".join(problems))
    return ok("seed_admin and seed_catalog, both checking before writing")


@check(3, "the backend image ships its migrations")
def check_backend_image_has_migrations() -> Result:
    """Without these, `docker compose exec backend alembic upgrade head` cannot work."""
    dockerfile = REPO_ROOT / "backend" / "Dockerfile"
    if not dockerfile.is_file():
        return fail("backend/Dockerfile does not exist")
    text = dockerfile.read_text(encoding="utf-8")
    missing = [
        need
        for need in ("alembic.ini", "alembic ./alembic", "app ./app")
        if f"COPY --chown=orchestrator:orchestrator {need}" not in text
    ]
    if missing:
        return fail("the image does not copy: " + ", ".join(missing))
    return ok("alembic.ini, alembic/ and app/ all copied")


@check(3, "backend quality bars pass")
def check_backend_quality_bars() -> Result:
    """ruff, ruff format, mypy and the offline pytest run, exactly as 1.6 lists them."""
    backend = REPO_ROOT / "backend"
    if not (backend / "pyproject.toml").is_file():
        return fail("backend/pyproject.toml does not exist")

    uv = REPO_ROOT / ".venv-tools" / "Scripts" / "uv.exe"
    if not uv.is_file():
        uv_name = "uv"
        if not have(uv_name):
            return fail("uv is not installed; see docs/decisions.md D-010")
        runner = [uv_name]
    else:
        runner = [str(uv)]

    # `python -m <tool>` rather than `uv run <tool>`. The latter resolves to the console-script
    # .exe shim in .venv/Scripts, and a Windows Application Control policy can block those while
    # the packages themselves import fine -- which failed this check with "Application Control
    # policy has blocked this file" even though every tool worked. The module form has no shim.
    # `--no-sync` on every stage. Without it, uv re-resolves the project whenever pyproject.toml
    # has changed, and on this machine a Windows Application Control policy blocks the temporary
    # interpreter uv builds with -- so an unrelated dependency edit made every quality bar fail
    # with "Application Control policy has blocked this file" instead of a lint error.
    stages = (
        ("ruff check", [*runner, "run", "--no-sync", "python", "-m", "ruff", "check", "."]),
        ("ruff format --check", [*runner, "run", "--no-sync", "python", "-m", "ruff", "format", "--check", "."]),
        ("mypy app", [*runner, "run", "--no-sync", "python", "-m", "mypy", "app"]),
        (
            "pytest",
            # `integration` is excluded here deliberately: its marker says "Opt in with
            # -m integration", and including it made this bar trigger real Jenkins builds
            # and take a minute. The acceptance check below runs them instead.
            [
                *runner,
                "run",
                "--no-sync",
                "python",
                "-m",
                "pytest",
                "-m",
                "not live and not e2e and not integration",
                "-q",
            ],
        ),
    )
    for label, command in stages:
        result = run(command, cwd=backend, timeout=600)
        if result.returncode != 0:
            tail = (result.stdout + result.stderr).strip().splitlines()
            return fail(f"{label} failed: " + " / ".join(tail[-2:])[:200])
    return ok("ruff, ruff format, mypy and pytest all clean")


@check(3, "the auth endpoints and role guards exist")
def check_auth_surface() -> Result:
    """Part 4.4.4's four endpoints, plus the three role guards 4.5.5's policy table needs.

    Read from the source rather than by importing the app, so the check needs no database and no
    settings: a gate that only runs when the stack is up is a gate that stops being run.
    """
    api = REPO_ROOT / "backend" / "app" / "api" / "auth.py"
    deps = REPO_ROOT / "backend" / "app" / "api" / "deps.py"
    service = REPO_ROOT / "backend" / "app" / "services" / "auth.py"
    for path in (api, deps, service):
        if not path.is_file():
            return fail(f"{path.relative_to(REPO_ROOT).as_posix()} does not exist")

    api_text = api.read_text(encoding="utf-8")
    routes = ('"/auth/login"', '"/auth/refresh"', '"/auth/logout"', '"/me"')
    missing = [route.strip('"') for route in routes if route not in api_text]
    if missing:
        return fail("no route for: " + ", ".join(missing))

    deps_text = deps.read_text(encoding="utf-8")
    guards = ("DeveloperUser", "DevOpsUser", "AdminUser")
    absent = [guard for guard in guards if f"{guard} = " not in deps_text]
    if absent:
        return fail("no role guard for: " + ", ".join(absent))

    service_text = service.read_text(encoding="utf-8")
    if "durable=True" not in service_text:
        return fail("refused sign-ins do not commit their audit entry; see D-022")
    if 'action="auth.login.failed"' not in service_text:
        return fail("failed sign-ins are not audited, which 4.4.3 requires")

    main_text = (REPO_ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    if "auth" not in main_text:
        return fail("the auth router is not wired into the app")

    return ok("login, refresh, logout and /api/me, with three role guards")


@check(3, "the auth endpoints are rate limited")
def check_auth_rate_limits() -> Result:
    """4.4.4 requires rate limits on the auth endpoints."""
    limits = REPO_ROOT / "backend" / "app" / "core" / "ratelimit.py"
    if not limits.is_file():
        return fail("backend/app/core/ratelimit.py does not exist")
    text = limits.read_text(encoding="utf-8")
    for name in ("LOGIN_LIMIT", "REFRESH_LIMIT", "API_LIMIT"):
        if f"{name} = RateLimit(" not in text:
            return fail(f"{name} is not defined")

    api_text = (REPO_ROOT / "backend" / "app" / "api" / "auth.py").read_text(encoding="utf-8")
    if "rate_limit(LOGIN_LIMIT)" not in api_text:
        return fail("the login endpoint is not rate limited")
    if "rate_limit(REFRESH_LIMIT)" not in api_text:
        return fail("the refresh endpoint is not rate limited")
    return ok("login 5/min, refresh 30/min, general 300/min")


@check(3, "the catalog loads through one schema-validated loader")
def check_catalog_loader() -> Result:
    """4.6.1 makes the catalog the only source of shell commands, so it is validated, not trusted.

    Also checks that nothing parses the YAML on its own. A second loader means the seed can accept
    a document the API rejects, and the bad catalog then reaches the database.
    """
    module = REPO_ROOT / "backend" / "app" / "services" / "catalog.py"
    if not module.is_file():
        return fail("backend/app/services/catalog.py does not exist")

    text = module.read_text(encoding="utf-8")
    if "jsonschema.validate" not in text:
        return fail("the catalog is loaded without being validated against its schema")
    if "yaml.safe_load" not in text:
        return fail("the catalog must be read with yaml.safe_load, never yaml.load")

    backend_app = REPO_ROOT / "backend" / "app"
    # YAML documents that are not the catalog, each with the reason it is parsed. Listed by path,
    # so a new parser anywhere else still fails, and a listed file that starts reading the catalog
    # fails too (below).
    other_documents = {
        "backend/app/generation/spec.py": "the generation spec the user edits in the preview (4.6.1)",
    }
    strays = []
    for path in backend_app.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if path == module or "yaml.safe_load" not in source:
            continue
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative not in other_documents:
            strays.append(relative)
        elif "services.yaml" in source or "catalog_path" in source:
            return fail(f"{relative} may parse YAML only for {other_documents[relative]}, but it "
                        "reads the catalog file")
    if strays:
        return fail("a second catalog parser exists in: " + ", ".join(strays))

    return ok("one loader, schema-validated, safe_load only")


@check(3, "git refs are validated before reaching git")
def check_git_ref_guard() -> Result:
    """Branch and commit values arrive from a chat message by way of an LLM.

    An argument list is not enough on its own: git reads a leading ``-`` as an option, and
    ``--upload-pack=<command>`` makes ls-remote execute that command. The ref pattern is what stops
    it, so this check fails if the pattern stops rejecting option-shaped refs.
    """
    module = REPO_ROOT / "backend" / "app" / "services" / "git.py"
    if not module.is_file():
        return fail("backend/app/services/git.py does not exist")

    text = module.read_text(encoding="utf-8")
    if "shell=True" in text:
        return fail("git is invoked through a shell")
    if "REF_PATTERN" not in text or "is_safe_ref" not in text:
        return fail("there is no ref validation")

    # Read the pattern out of the source and exercise it, rather than importing the module: the
    # gate must run without the backend's dependencies installed.
    found = re.search(r'REF_PATTERN: Final = re\.compile\(r"([^"]+)"\)', text)
    if found is None:
        return fail("REF_PATTERN is not a literal regex; this check cannot verify it")
    pattern = re.compile(found.group(1))

    hostile = ("--upload-pack=touch /tmp/x", "-u", "--exec=sh", "main;rm -rf /", "main$(id)")
    accepted = [ref for ref in hostile if pattern.match(ref)]
    if accepted:
        return fail("REF_PATTERN accepts: " + ", ".join(accepted))

    ordinary = ("main", "develop", "demo/failing-tests", "release-1.2")
    rejected = [ref for ref in ordinary if not pattern.match(ref)]
    if rejected:
        return fail("REF_PATTERN rejects ordinary branches: " + ", ".join(rejected))

    return ok("option-shaped refs rejected, ordinary branches accepted, no shell")


@check(3, "the metrics endpoint exists and accepts what it cannot parse")
def check_metrics_endpoint_shape() -> Result:
    """4.4.5's ``POST /api/metrics``, and the properties D-027 depends on.

    The publisher counts any non-2xx as a failure and never retries, so a strict endpoint loses
    data silently. These are source checks because the gate must run with the stack down.
    """
    api = REPO_ROOT / "backend" / "app" / "api" / "metrics.py"
    service = REPO_ROOT / "backend" / "app" / "services" / "metrics.py"
    for path in (api, service):
        if not path.is_file():
            return fail(f"{path.relative_to(REPO_ROOT).as_posix()} does not exist")

    api_text = api.read_text(encoding="utf-8")
    if '"/metrics"' not in api_text:
        return fail("no /metrics route")
    if 'extra": "allow"' not in api_text and "extra='allow'" not in api_text:
        return fail("the event model rejects unknown fields; see D-027")
    if "compare_digest" not in api_text:
        return fail("the metrics token is not compared in constant time")
    if "require_metrics_token" not in api_text:
        return fail("the endpoint is not gated on METRICS_TOKEN")

    service_text = service.read_text(encoding="utf-8")
    for kind in ("QUEUE_ENTERED", "QUEUE_LEFT", "BUILD_STARTED", "BUILD_COMPLETED"):
        if kind not in service_text:
            return fail(f"the ingester does not handle {kind}")
    if "PendingQueueTimings" not in service_text:
        return fail("queue timings are not parked; see D-027")

    main_text = (REPO_ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    if "metrics" not in main_text:
        return fail("the metrics router is not wired into the app")

    return ok("gated, constant-time, open to unknown fields, all four kinds handled")


@check(3, "the plugin publishes metrics over HTTP/1.1")
def check_publisher_http_version() -> Result:
    """Guards D-026, which disabled the whole metrics pipeline.

    Java's HttpClient defaults to HTTP/2 and negotiates it over cleartext with ``Upgrade: h2c``,
    which uvicorn does not implement: every event came back 422 and the only symptom was a
    counter nobody was watching.
    """
    publisher = (
        REPO_ROOT
        / "plugin"
        / "src"
        / "main"
        / "java"
        / "io"
        / "jenkins"
        / "plugins"
        / "queueoptimizer"
        / "metrics"
        / "MetricsPublisher.java"
    )
    if not publisher.is_file():
        return fail("MetricsPublisher.java does not exist")

    text = publisher.read_text(encoding="utf-8")
    if "HttpClient.Version.HTTP_1_1" not in text:
        return fail("the publisher does not pin HTTP/1.1; uvicorn rejects Java's h2c upgrade")

    test = (
        REPO_ROOT
        / "plugin"
        / "src"
        / "test"
        / "java"
        / "io"
        / "jenkins"
        / "plugins"
        / "queueoptimizer"
        / "metrics"
        / "MetricsPublisherHttpVersionTest.java"
    )
    if not test.is_file():
        return fail("MetricsPublisherHttpVersionTest.java is missing; the pin is unguarded")

    return ok("pinned to HTTP/1.1 and asserted by a test")


@check(3, "the controller reinstalls the plugin under test on start")
def check_plugin_reinstall_entrypoint() -> Result:
    """Guards D-028.

    The plugin is always 2.0.0-SNAPSHOT, so Jenkins never treats an image copy as newer and a
    persistent home keeps the .hpi from its first boot. A fix can then appear not to work.
    """
    script = REPO_ROOT / "jenkins" / "controller" / "install-plugin-under-test.sh"
    if not script.is_file():
        return fail("jenkins/controller/install-plugin-under-test.sh does not exist")

    text = script.read_text(encoding="utf-8")
    if ".pinned" not in text:
        return fail("the script does not remove the .pinned marker, so the stale plugin wins")
    if "jenkins.sh" not in text:
        return fail("the script does not hand over to the stock entrypoint")

    dockerfile = (REPO_ROOT / "jenkins" / "controller" / "Dockerfile").read_text(encoding="utf-8")
    if "install-plugin-under-test.sh" not in dockerfile:
        return fail("the Dockerfile does not use the reinstall entrypoint")
    if "ENTRYPOINT" not in dockerfile:
        return fail("the Dockerfile sets no ENTRYPOINT, so the script never runs")

    return ok("entrypoint replaces the plugin and execs jenkins.sh")


@check(3, "a live plugin event reaches the backend")
def check_metrics_delivered_live() -> Result:
    """The end-to-end check that would have caught D-026 on the day it was written.

    Reads the plugin's own counters. A non-zero failure count means the backend is refusing what
    the plugin sends, which is invisible from either side alone.

    Self-sufficient: the counters live in memory and reset when the controller restarts, so on a
    fresh controller nothing has been published yet. This check used to fail in exactly that state
    and pass on the next run -- only because a *later* check had triggered builds in between,
    which made the gate depend on its own ordering. Now, if nothing has been published, it triggers
    a build itself and waits for the events.
    """
    credentials = _bot_credentials()
    if isinstance(credentials, str):
        return fail(credentials)
    user, token = credentials

    def read_health() -> dict[str, Any] | str:
        status, body = _jenkins_get("/dynamic-queue/health", user, token)
        if status != 200:
            return f"GET /dynamic-queue/health returned {status}"
        try:
            parsed: dict[str, Any] = json.loads(body)
        except ValueError:
            return "the health endpoint did not return JSON"
        return parsed

    health = read_health()
    if isinstance(health, str):
        return fail(health)

    if not health.get("metricsEnabled", False):
        return fail("metrics are disabled on this controller")
    if not health.get("metricsPublishable", False):
        return fail("metricsBackendUrl or metricsToken is not configured; see JCasC")

    triggered = ""
    if not int(health.get("publishedMetricCount", 0)) and not int(health.get("failedMetricCount", 0)):
        # The integration suite's job exists once that suite has run; the reference job exists
        # once the reference configs were exported (T1.9). Either produces all four event kinds,
        # even when its checkout fails on an unpushed repository.
        params = {"BRANCH": "main", "COMMIT": "", "SUCCESS": "true"}
        for job in ("it-freestyle-create-trigger-read", "reference-freestyle-payment-service"):
            if _jenkins_trigger(job, params, user, token) == 201:
                triggered = job
                break
        if not triggered:
            return fail(
                "no events published yet, and no known job could be triggered to produce some; "
                "run the Phase 3 integration tests first"
            )
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            time.sleep(3)
            latest = read_health()
            if isinstance(latest, str):
                return fail(latest)
            health = latest
            if int(health.get("publishedMetricCount", 0)) >= 4 or int(
                health.get("failedMetricCount", 0)
            ):
                break

    failed = int(health.get("failedMetricCount", 0))
    published = int(health.get("publishedMetricCount", 0))
    dropped = int(health.get("droppedMetricCount", 0))

    if failed:
        return fail(
            f"the backend refused {failed} event(s) ({published} published). "
            "Check POST /api/metrics; see docs/decisions.md D-026"
        )
    if dropped:
        return fail(f"the publisher dropped {dropped} event(s); its queue overflowed")
    if not published:
        return fail(f"triggered {triggered} but no event was published within two minutes")

    source = f" after triggering {triggered}" if triggered else ""
    return ok(f"{published} published, 0 failed, 0 dropped{source}")


@check(3, "the WebSocket never takes its token from the URL")
def check_ws_token_not_in_url() -> Result:
    """Guards D-029.

    A browser cannot set headers on a WebSocket, so the usual workaround is ``/ws?token=...``.
    That writes the access token into proxy access logs, browser history and any Referer sent
    onward. The socket authenticates with its first frame instead, and this fails if that changes.
    """
    routes = REPO_ROOT / "backend" / "app" / "ws" / "routes.py"
    hub = REPO_ROOT / "backend" / "app" / "ws" / "hub.py"
    for path in (routes, hub):
        if not path.is_file():
            return fail(f"{path.relative_to(REPO_ROOT).as_posix()} does not exist")

    text = routes.read_text(encoding="utf-8")
    if 'websocket("/ws")' not in text:
        return fail("there is no /ws route")

    # query_params would mean the token, or something else trusted, is being read from the URL.
    if "query_params" in text:
        return fail("the socket reads the query string; the token must stay in the first frame")
    if "_authenticate" not in text or '"auth"' not in text:
        return fail("there is no auth-frame handshake")
    if "AUTH_TIMEOUT_SECONDS" not in text:
        return fail("an unauthenticated socket is never timed out")

    main_text = (REPO_ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    if "ws_routes" not in main_text:
        return fail("the /ws route is not wired into the app")

    return ok("auth by first frame, timed out, nothing read from the query string")


@check(3, "publishing to the hub cannot block the tracker")
def check_hub_never_blocks() -> Result:
    """The tracker publishes from inside its tick.

    If a browser on a bad connection could apply backpressure, one slow client would slow down
    recording run history for everyone. ``publish`` is therefore synchronous and drops.
    """
    hub = REPO_ROOT / "backend" / "app" / "ws" / "hub.py"
    if not hub.is_file():
        return fail("backend/app/ws/hub.py does not exist")

    text = hub.read_text(encoding="utf-8")
    if "async def publish" in text:
        return fail("publish is a coroutine; it could suspend on a slow client")
    if "put_nowait" not in text:
        return fail("publish does not use put_nowait, so it can block")
    # Line-anchored: the word "await" also appears in publish's docstring, explaining why there
    # isn't one. Matching that was this check's first bug.
    body = text.split("def publish")[1].split("\n    def ")[0]
    if re.search(r"^\s+await ", body, re.M):
        return fail("publish awaits something; it must not be able to suspend")
    if "QUEUE_CAPACITY" not in text:
        return fail("subscriber queues are unbounded")

    return ok("synchronous, bounded, drops the oldest event")


@check(3, "the tracker polls on the interval 4.4.5 fixes")
def check_tracker_interval() -> Result:
    """4.4.5: "polls in-flight runs every 3 seconds"."""
    tracker = REPO_ROOT / "backend" / "app" / "services" / "tracker.py"
    if not tracker.is_file():
        return fail("backend/app/services/tracker.py does not exist")

    text = tracker.read_text(encoding="utf-8")
    found = re.search(r"POLL_SECONDS: Final = ([0-9.]+)", text)
    if found is None:
        return fail("POLL_SECONDS is not declared")
    if abs(float(found.group(1)) - 3.0) > 1e-9:
        return fail(f"POLL_SECONDS is {found.group(1)}; 4.4.5 fixes it at 3 seconds")

    if "MAX_RUNS_PER_TICK" not in text:
        return fail("a tick is unbounded; a backlog would stretch the interval")
    if "QUEUE_ITEM_TIMEOUT_SECONDS" not in text:
        return fail("a queue item that never resolves would be polled forever")

    return ok("3 second interval, bounded tick, abandoned triggers time out")


@check(3, "a polled queue wait never overwrites a plugin-measured one")
def check_plugin_wait_wins() -> Result:
    """4.4.6 exists because polling cannot see the queue precisely.

    The plugin measured the wait from inside the queue; the tracker can only subtract two
    timestamps either side of a three-second poll. If the coarse value could overwrite the exact
    one, every waiting-time figure in the report would silently gain a three-second error bar.
    """
    tracker = REPO_ROOT / "backend" / "app" / "services" / "tracker.py"
    if not tracker.is_file():
        return fail("backend/app/services/tracker.py does not exist")

    text = tracker.read_text(encoding="utf-8")
    if "if run.queue_wait_ms is None:" not in text:
        return fail(
            "the tracker does not guard queue_wait_ms; a polled estimate could overwrite the "
            "plugin's measurement (4.4.6)"
        )
    return ok("the tracker fills queue_wait_ms only when it is unset")


@check(3, "Part 4.4.4's endpoints are all registered")
def check_api_surface() -> Result:
    """Every path 4.4.4 lists for Phase 3, read from the source.

    A source check rather than an import, so the gate runs without the backend's dependencies
    installed and without a database.
    """
    api_dir = REPO_ROOT / "backend" / "app" / "api"
    if not api_dir.is_dir():
        return fail("backend/app/api/ does not exist")

    sources = {
        path.name: path.read_text(encoding="utf-8") for path in api_dir.glob("*.py")
    }
    combined = "\n".join(sources.values())

    required = {
        "/auth/login": "auth.py",
        "/auth/refresh": "auth.py",
        "/auth/logout": "auth.py",
        "/me": "auth.py",
        "/metrics": "metrics.py",
        "/jobs": "jobs.py",
        "/runs": "jobs.py",
        "/runs/{run_id}/cancel": "jobs.py",
        "/runs/{run_id}/log": "jobs.py",
        "/queue": "queue.py",
        "/services": "services.py",
        "/services/{name}/branches": "services.py",
        "/admin/users": "admin.py",
        "/admin/audit": "admin.py",
        "/admin/policy": "admin.py",
        "/analytics/experiments": "analytics.py",
        "/analytics/runs": "analytics.py",
    }
    missing = [route for route in required if f'"{route}"' not in combined]
    if missing:
        return fail("no route for: " + ", ".join(sorted(missing)))

    main_text = (REPO_ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    not_wired = [
        module
        for module in ("jobs", "queue", "services", "analytics", "admin")
        if f"{module}.router" not in main_text
    ]
    if not_wired:
        return fail("routers not wired into the app: " + ", ".join(not_wired))

    return ok(f"{len(required)} routes across {len(sources)} router modules")


@check(3, "mutating endpoints carry a role guard")
def check_role_guards_on_mutations() -> Result:
    """4.5.5's table is cumulative, so every write needs a guard above the weakest role.

    A route that forgets its guard is silently open, and that is invisible in a passing test suite
    unless something looks for it. This looks for it.
    """
    api_dir = REPO_ROOT / "backend" / "app" / "api"
    guards = ("DeveloperUser", "DevOpsUser", "AdminUser")

    # (file, route) pairs that change state and must be guarded above a plain signed-in user.
    expected = {
        ("jobs.py", "/runs/{run_id}/cancel"): "DevOpsUser",
        ("services.py", "/services/resync"): "AdminUser",
        ("admin.py", "/admin/users"): "AdminUser",
        ("admin.py", "/admin/users/{user_id}"): "AdminUser",
    }

    for (filename, route), required in expected.items():
        path = api_dir / filename
        if not path.is_file():
            return fail(f"backend/app/api/{filename} does not exist")
        text = path.read_text(encoding="utf-8")
        if f'"{route}"' not in text:
            return fail(f"{filename} has no route {route}")
        # The handler follows its decorator; find the guard within the next few lines.
        after = text.split(f'"{route}"', 1)[1][:1200]
        if required not in after:
            present = [guard for guard in guards if guard in after]
            return fail(
                f"{route} needs {required}; found {present or 'no role guard'}"
            )

    admin_text = (api_dir / "admin.py").read_text(encoding="utf-8")
    if "admin: AdminUser" not in admin_text:
        return fail("the admin router does not require the Admin role")

    return ok("cancel needs DevOps; resync and every admin route need Admin")


@check(3, "the queue endpoint degrades when the plugin is absent")
def check_queue_degrades() -> Result:
    """jenkins-baseline runs without the plugin on purpose.

    A Queue page that 500s there would look like a broken backend rather than a fact about the
    controller, and the baseline arm of the experiment runs on exactly that controller.
    """
    path = REPO_ROOT / "backend" / "app" / "api" / "queue.py"
    if not path.is_file():
        return fail("backend/app/api/queue.py does not exist")

    text = path.read_text(encoding="utf-8")
    if "available" not in text or "unavailable_reason" not in text:
        return fail("the response cannot express an unreadable plugin")

    plugin = (REPO_ROOT / "backend" / "app" / "services" / "plugin.py").read_text(
        encoding="utf-8"
    )
    if "droppedMetricCount" not in plugin:
        return fail(
            "plugin health reads the wrong field name for dropped metrics; it would always "
            "report zero. See docs/decisions.md D-026"
        )
    return ok("reports availability and a reason instead of failing")


@check(3, "integration tests create, trigger and read a freestyle and a Pipeline job")
def check_phase3_integration() -> Result:
    """Phase 3's third acceptance clause, run for real.

    Excluded from the quality-bar check above so that bar stays fast, and gated here so the clause
    is actually verified rather than assumed. The tests skip themselves when jenkins-dev is
    unreachable; a skip is reported as a failure of *this* check, because an acceptance clause that
    silently passes when it could not run is worse than no check.
    """
    backend = REPO_ROOT / "backend"
    suite = backend / "tests" / "test_integration_jenkins.py"
    if not suite.is_file():
        return fail("backend/tests/test_integration_jenkins.py does not exist")

    text = suite.read_text(encoding="utf-8")
    for needed in ("freestyle", "flow-definition", "console_text", "lint_jenkinsfile"):
        if needed not in text:
            return fail(f"the integration suite does not cover {needed}")

    uv = REPO_ROOT / ".venv-tools" / "Scripts" / "uv.exe"
    runner = [str(uv)] if uv.is_file() else (["uv"] if have("uv") else [])
    if not runner:
        return fail("uv is not installed; see docs/decisions.md D-010")

    result = run(
        [
            *runner,
            "run",
            "--no-sync",
            "python",
            "-m",
            "pytest",
            "tests/test_integration_jenkins.py",
            "-m",
            "integration",
            # No -q: pyproject's addopts already has it, and a second one suppresses the
            # "N passed" summary this check reads.
        ],
        cwd=backend,
        timeout=900,
    )
    output = (result.stdout + result.stderr).strip()

    if result.returncode != 0:
        tail = [line for line in output.splitlines() if line.strip()][-3:]
        return fail("integration tests failed: " + " / ".join(tail)[:300])

    passed = re.search(r"(\d+) passed", output)
    skipped = re.search(r"(\d+) skipped", output)
    if skipped and int(skipped.group(1)) and not (passed and int(passed.group(1))):
        return fail(
            "the integration tests all skipped; is the stack up and is JENKINS_TOKEN set?"
        )
    if not passed:
        return fail("pytest reported no passing integration tests")

    return ok(f"{passed.group(1)} passed against the live controller")


# ---------------------------------------------------------------------------
# Phase 4: AI core
# ---------------------------------------------------------------------------


def _uv_runner() -> list[str] | None:
    """The uv command, preferring the project-local copy (D-010)."""
    uv = REPO_ROOT / ".venv-tools" / "Scripts" / "uv.exe"
    if uv.is_file():
        return [str(uv)]
    return ["uv"] if have("uv") else None


AI_MODULES = (
    "intent.py",
    "schema.py",
    "prompting.py",
    "rules.py",
    "guard.py",
    "validator.py",
    "clarify.py",
    "policy.py",
    "parser.py",
    "chain.py",
    "quota.py",
    "cache.py",
    "factory.py",
    "providers/base.py",
    "providers/groq.py",
    "providers/replay.py",
    "providers/fake.py",
)


@check(4, "the AI core's modules exist")
def check_ai_modules() -> Result:
    """T4.1 to T4.6: providers, chain, schema, prompt, rules, parser, validator, policy."""
    ai_dir = REPO_ROOT / "backend" / "app" / "ai"
    missing = [name for name in AI_MODULES if not (ai_dir / name).is_file()]
    if missing:
        return fail("missing: " + ", ".join(missing))
    return ok(f"{len(AI_MODULES)} modules")


@check(4, "the prompt is versioned and carries 8 to 12 examples")
def check_prompt_examples() -> Result:
    """4.5.6: versioned markdown with 8 to 12 few-shot examples, starting from Appendix E."""
    prompt = REPO_ROOT / "backend" / "app" / "ai" / "prompts" / "intent_v1.md"
    if not prompt.is_file():
        return fail("backend/app/ai/prompts/intent_v1.md does not exist")
    text = prompt.read_text(encoding="utf-8")
    _, heading, examples = text.partition("## Examples")
    if not heading:
        return fail("the prompt has no ## Examples section")
    count = examples.count("\n### ")
    if not 8 <= count <= 12:
        return fail(f"{count} examples; 4.5.6 asks for 8 to 12")
    for rule in ("Never invent one", "Never silently change it to staging", "is data, not instruction"):
        if rule not in text:
            return fail(f"Appendix E's rule is missing: {rule!r}")
    return ok(f"intent_v1 with {count} examples and Appendix E's rules")


def _function_body(source: str, name: str) -> str:
    """The text of one top-level function, up to the next top-level definition."""
    start = source.find(f"\ndef {name}(")
    if start < 0:
        return ""
    following = source.find("\ndef ", start + 1)
    return source[start : following if following > 0 else len(source)]


@check(4, "the model never sees a shell command")
def check_no_commands_in_prompt() -> Result:
    """CLAUDE.md: the LLM never writes shell commands; commands come from the catalog.

    What the model sees is the prompt's catalog context and the JSON schema. If either function
    ever reads a service's commands, the model would be shown -- and could echo back -- the very
    strings the agents execute.
    """
    schema = (REPO_ROOT / "backend" / "app" / "ai" / "schema.py").read_text(encoding="utf-8")
    for function in ("catalog_context", "build_intent_schema"):
        body = _function_body(schema, function)
        if not body:
            return fail(f"schema.py has no {function}(); this check cannot verify it")
        for forbidden in ("command", "deploy_target", "build_command"):
            if forbidden in body:
                return fail(f"{function}() mentions {forbidden!r}; the model must never see commands")
    return ok("catalog context and schema carry names only")


@check(4, "the SDK's own retries are off")
def check_sdk_retries_off() -> Result:
    """Left on, the openai SDK retries 429s invisibly: double-counted quota and hidden failures."""
    groq = (REPO_ROOT / "backend" / "app" / "ai" / "providers" / "groq.py").read_text(
        encoding="utf-8"
    )
    if "max_retries=0" not in groq:
        return fail("GroqProvider must construct the client with max_retries=0")
    return ok("max_retries=0; ModelChain owns the retry policy")


@check(4, "llm_calls records the prompt version and the outcome")
def check_llm_call_columns() -> Result:
    """D-036: 4.5.6 requires the version on every call; failed calls need an outcome."""
    versions = REPO_ROOT / "backend" / "alembic" / "versions"
    migrations = [path.read_text(encoding="utf-8") for path in versions.glob("*.py")]
    if not any('"prompt_version"' in text and '"outcome"' in text for text in migrations):
        return fail("no migration adds llm_calls.prompt_version and llm_calls.outcome")
    return ok("migration 8c2f4d1e7a90 present")


@check(4, "drafted evaluation items stay capped and unreviewed")
def check_eval_drafts() -> Result:
    """4.9: Claude Code may draft at most 30 items, each needs_review until a human clears it."""
    sample = REPO_ROOT / "eval" / "datasets" / "sample.jsonl"
    if not sample.is_file():
        return fail("eval/datasets/sample.jsonl does not exist")
    drafts = 0
    for number, line in enumerate(sample.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("labeled_by") == "claude-code-draft":
            drafts += 1
            if item.get("needs_review") is not True:
                return fail(f"line {number}: a Claude Code draft is marked reviewed")
    if drafts > 30:
        return fail(f"{drafts} drafted items; 4.9 allows at most 30")
    return ok(f"{drafts} drafts, all awaiting human review")


@check(4, "AI unit and policy tests pass")
def check_ai_tests() -> Result:
    """Acceptance clause 1, run on its own so a failure names the AI suite."""
    runner = _uv_runner()
    if runner is None:
        return fail("uv is not installed; see docs/decisions.md D-010")
    tests = sorted(
        str(path.relative_to(REPO_ROOT / "backend"))
        for path in (REPO_ROOT / "backend" / "tests").glob("test_ai_*.py")
        if path.name != "test_ai_live.py"
    )
    result = run(
        [*runner, "run", "--no-sync", "python", "-m", "pytest", *tests, "-p", "no:cacheprovider"],
        cwd=REPO_ROOT / "backend",
        timeout=600,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        tail = [line for line in output.splitlines() if line.strip()][-2:]
        return fail("AI tests failed: " + " / ".join(tail)[:240])
    passed = re.search(r"(\d+) passed", output)
    return ok(f"{passed.group(1) if passed else '?'} passed across {len(tests)} AI test files")


@check(4, "with Groq unreachable the rule parser answers with ai_fallback")
def check_ai_fallback() -> Result:
    """Acceptance clause 2, verbatim, through the real factory."""
    runner = _uv_runner()
    if runner is None:
        return fail("uv is not installed; see docs/decisions.md D-010")
    tests = [
        "tests/test_ai_parser.py::test_with_groq_unreachable_the_rules_answer_and_ai_fallback_is_set",
        "tests/test_ai_parser.py::test_live_mode_without_a_key_degrades_to_rules_instead_of_failing",
    ]
    result = run(
        [*runner, "run", "--no-sync", "python", "-m", "pytest", *tests, "-p", "no:cacheprovider"],
        cwd=REPO_ROOT / "backend",
        timeout=300,
    )
    if result.returncode != 0:
        tail = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()][-2:]
        return fail("fallback tests failed: " + " / ".join(tail)[:240])
    return ok("unreachable and keyless Groq both fall back to rules with ai_fallback: true")


@check(4, "the evaluation command writes a metrics file")
def check_eval_run() -> Result:
    """Acceptance clause 3: python -m eval run --parser rules --file eval/datasets/sample.jsonl."""
    runner = _uv_runner()
    if runner is None:
        return fail("uv is not installed; see docs/decisions.md D-010")
    metrics = REPO_ROOT / "eval" / "results" / "sample__rules" / "metrics.json"
    result = run(
        [
            *runner,
            "run",
            "--no-sync",
            "--project",
            "backend",
            "python",
            "-m",
            "eval",
            "run",
            "--parser",
            "rules",
            "--file",
            "eval/datasets/sample.jsonl",
            "--fresh",
        ],
        cwd=REPO_ROOT,
        timeout=300,
    )
    if result.returncode != 0 or not metrics.is_file():
        tail = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()][-2:]
        return fail("python -m eval run failed: " + " / ".join(tail)[:240])
    data = json.loads(metrics.read_text(encoding="utf-8"))
    scored = data["metrics"]["n"]
    excluded = data["dataset"]["excluded_needs_review"]
    return ok(f"metrics.json written; {scored} scored, {excluded} excluded pending review")


@check(4, "the evaluation package passes ruff and strict mypy")
def check_eval_quality() -> Result:
    """Its numbers go into the report, so it meets the backend's bar (eval/ruff.toml extends it)."""
    runner = _uv_runner()
    if runner is None:
        return fail("uv is not installed; see docs/decisions.md D-010")
    backend = REPO_ROOT / "backend"
    stages = (
        ("ruff check", ["python", "-m", "ruff", "check", "../eval"]),
        ("ruff format --check", ["python", "-m", "ruff", "format", "--check", "../eval"]),
        ("mypy", ["python", "-m", "mypy", "../eval", "--config-file", "pyproject.toml"]),
    )
    for label, command in stages:
        result = run([*runner, "run", "--no-sync", *command], cwd=backend, timeout=300)
        if result.returncode != 0:
            tail = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()][-2:]
            return fail(f"{label} failed on eval/: " + " / ".join(tail)[:200])
    return ok("ruff, ruff format and strict mypy clean")


# ---------------------------------------------------------------------------
# Phase 5: the assistants
# ---------------------------------------------------------------------------


def _pytest(arguments: list[str], *, timeout: int, env: dict[str, str] | None = None) -> tuple[
    subprocess.CompletedProcess[str] | None, str
]:
    """Run pytest in backend/ through uv. Returns the process and its output, or None and why."""
    runner = _uv_runner()
    if runner is None:
        return None, "uv is not installed; see docs/decisions.md D-010"
    result = run(
        # No -q: pyproject's addopts already has it, and a second one suppresses the summary.
        [*runner, "run", "--no-sync", "python", "-m", "pytest", *arguments],
        cwd=REPO_ROOT / "backend",
        timeout=timeout,
        env=env,
    )
    return result, (result.stdout + result.stderr).strip()


def _keep_output(what: str, output: str) -> str:
    """Save a failed check's whole pytest output, and return where it went.

    A failing summary line names the test but not the assertion, and an end-to-end failure on a
    live stack cannot be re-run to the same state: on 2026-10-13 one failed before Jenkins was
    reached, and nothing kept the reason. ``.tmp/`` is gitignored.
    """
    folder = REPO_ROOT / ".tmp" / "verify"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (re.sub(r"[^a-z0-9]+", "-", what.lower()).strip("-") + ".log")
    path.write_text(output, encoding="utf-8")
    return str(path.relative_to(REPO_ROOT))


def _all_passed(result: subprocess.CompletedProcess[str] | None, output: str, what: str) -> Result:
    """Passed only if pytest exited 0, something passed, and nothing was skipped.

    A skip is a failure here: an acceptance clause that passes because it could not run is worse
    than no check (the same rule as Phase 3's integration check).
    """
    if result is None:
        return fail(output)
    if result.returncode != 0:
        tail = [line for line in output.splitlines() if line.strip()][-3:]
        saved = _keep_output(what, output)
        return fail(f"{what} failed: " + " / ".join(tail)[:300] + f" (full output: {saved})")
    passed = re.search(r"(\d+) passed", output)
    skipped = re.search(r"(\d+) skipped", output)
    if skipped and int(skipped.group(1)):
        return fail(f"{what}: {skipped.group(1)} skipped; is the stack up and is .env complete?")
    if not passed:
        return fail(f"{what}: pytest reported nothing passing")
    return ok(f"{passed.group(1)} passed")


@check(5, "golden template tests pass, and the templates derive from the reference configs")
def check_golden_templates() -> Result:
    """Appendix D, Phase 5: "Golden template tests". The same file proves the derivation: the
    reference job's own values render what Jenkins exported (rule 1.4)."""
    golden = REPO_ROOT / "backend" / "tests" / "golden"
    if not golden.is_dir() or not any(golden.rglob("*.config.xml")):
        return fail("backend/tests/golden/ holds no golden config.xml files")
    # UPDATE_GOLDEN would rewrite the files instead of comparing them; never let it leak in.
    result, output = _pytest(
        ["tests/test_generation_render.py"], timeout=600, env={"UPDATE_GOLDEN": "0"}
    )
    return _all_passed(result, output, "the golden template tests")


@check(5, "the linter integration test passes against jenkins-dev")
def check_linter_integration() -> Result:
    """Appendix D, Phase 5: "linter integration test". Every Jenkinsfile the generator can produce
    is put through jenkins-dev's declarative linter, and a broken one must be refused."""
    result, output = _pytest(
        ["tests/test_integration_generation.py", "-m", "integration"], timeout=900
    )
    return _all_passed(result, output, "the linter integration test")


# The failing-branch test is its own check below; leaving it out here keeps the two independent
# without running the longest chain twice.
E2E_SELECTION = "not failing_branch"


@check(5, "pytest -m e2e passes on the Compose stack")
def check_e2e() -> Result:
    """Appendix D, Phase 5: "pytest -m e2e". Every 4.6.5 command, through the real app, real
    Jenkins and real agents. Replay fixtures, so the gate never spends model quota (T5.8)."""
    result, output = _pytest(
        ["tests/test_e2e_assistants.py", "-m", "e2e", "-k", E2E_SELECTION],
        timeout=3600,
        env={"E2E_LLM": "replay"},
    )
    return _all_passed(result, output, "the end-to-end tests")


@check(5, "the failing-branch chain stops before deploy")
def check_failing_branch() -> Result:
    """Appendix D, Phase 5, and Phase 5's acceptance: "against demo/failing-tests the freestyle
    deploy job never starts". Generated, approved and run through the assistant -- not the
    hand-built chain of scripts/accept_failing_tests.py."""
    result, output = _pytest(
        ["tests/test_e2e_assistants.py", "-m", "e2e", "-k", "failing_branch"],
        timeout=1800,
        env={"E2E_LLM": "replay"},
    )
    verdict = _all_passed(result, output, "the failing-branch chain")
    if verdict.ok:
        return ok("test failed on demo/failing-tests and the deploy job never started")
    return verdict


FAILURE_TESTS = (
    "tests/test_failures_redact.py",
    "tests/test_failures_analysis.py",
    "tests/test_failures_explainer.py",
    "tests/test_failures_api.py",
    "tests/test_integration_failures.py",
)


@check(5, "Explain failure (T5.9): redaction, analysis, checks, endpoint and a live failing job")
def check_explain_failure() -> Result:
    """T5.9 is a stretch task with no Appendix D line of its own, so this is its gate. The
    analysis is tested on logs captured from jenkins-dev, and once more on a job it runs there
    twice: the two real logs must give the model the same prompt, or a recording never replays.
    Explaining real failures through the API is in the end-to-end check above."""
    result, output = _pytest(
        [*FAILURE_TESTS, "-m", "not live and not e2e"],
        timeout=900,
    )
    return _all_passed(result, output, "the Explain failure tests")


# ---------------------------------------------------------------------------
# Phase 6: frontend
# ---------------------------------------------------------------------------

DESIGN_DOC = REPO_ROOT / "frontend" / "DESIGN.md"

# Part 4.7.2's list, plus the review it asks for, as `##` headings.
DESIGN_SECTIONS = (
    "Subject and audience",
    "Palette",
    "Type",
    "Layout",
    "Principles",
    "Review against the generic traits",
)
DESIGN_SCREENS = ("Assistant workspace", "Queue", "Overview")
DESIGN_NEUTRALS = ("Ground", "Panel", "Ink", "Graphite")
SCORE_FACTORS = ("Urgency", "Dependency", "Execution time", "Aging")
BUILD_STATE_ROWS = ("Succeeded", "Failed", "Unstable")
# One word from each of the four traits 4.7.2 lists. The review must address all four.
GENERIC_TRAITS = ("cream", "card", "gradient", "monospace")

# WCAG 2.2 AA (4.7.5), and the dataviz floors the score bar was chosen by.
TEXT_CONTRAST = 4.5
GRAPHIC_CONTRAST = 3.0
NORMAL_DELTA_E = 15.0
CVD_DELTA_E = 8.0

_HEX = re.compile(r"`(#[0-9a-fA-F]{6})`")

# Machado, Oliveira and Fernandes (2009) at severity 1.0, applied to linear RGB. The CVD floor
# above is calibrated to this model, so it is part of the check, not a detail of it.
_CVD_MATRICES = {
    "protan": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deutan": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
}


def _md_section(text: str, title: str, level: int) -> str:
    """The body under the heading `title` (optionally numbered, as in "## 2. Palette") up to the
    next heading of the same or a higher level. Lines inside code fences are never headings: the
    wireframes are full of `#` and `|`. Empty when the heading is missing."""
    lines = text.splitlines()
    heading = re.compile(rf"^{'#' * level} (?:\d+\. )?{re.escape(title)}\s*$")
    in_fence = False
    start: int | None = None
    body: list[str] = []
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
        is_heading = not in_fence and re.match(r"^(#{1,6}) ", line)
        if start is None:
            if not in_fence and heading.match(line):
                start = len(body)
            continue
        if is_heading and len(is_heading.group(1)) <= level:
            break
        body.append(line)
    return "\n".join(body) if start is not None else ""


def _md_table(section: str) -> list[list[str]]:
    """Cells of the first table in `section`, without its header and divider rows."""
    rows: list[list[str]] = []
    for line in section.splitlines():
        if line.startswith("|"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif rows:
            break
    return rows[2:]


def _linear_rgb(colour: str) -> tuple[float, float, float]:
    r, g, b = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return tuple(  # type: ignore[return-value]
        c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)
    )


def _contrast(a: str, b: str) -> float:
    """WCAG 2.x contrast ratio."""

    def luminance(colour: str) -> float:
        r, g, b_ = _linear_rgb(colour)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_

    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _oklab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = rgb
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def _delta_e(a: str, b: str, deficiency: str | None = None) -> float:
    """OKLab distance x100, after simulating `deficiency` when one is given."""

    def lab(colour: str) -> tuple[float, float, float]:
        rgb = _linear_rgb(colour)
        if deficiency:
            matrix = _CVD_MATRICES[deficiency]
            rgb = tuple(  # type: ignore[assignment]
                min(1.0, max(0.0, sum(row[j] * rgb[j] for j in range(3)))) for row in matrix
            )
        return _oklab(rgb)

    return 100 * math.dist(lab(a), lab(b))


def _cvd_delta_e(a: str, b: str) -> float:
    return min(_delta_e(a, b, "protan"), _delta_e(a, b, "deutan"))


def design_doc_problems(text: str) -> tuple[list[str], str]:
    """Everything wrong with a DESIGN.md, and a one-line summary when nothing is.

    Pure, so it can be tested on edited copies of the document. The colours are read from the
    document's own tables and every floor is recomputed from them."""
    problems: list[str] = []
    for title in DESIGN_SECTIONS:
        if not _md_section(text, title, 2).strip():
            problems.append(f"no '## {title}' section")

    subject = _md_section(text, "Subject and audience", 2).lower()
    if subject and not ("four-person" in subject and "live demo" in subject):
        problems.append("the subject is not 4.7.2's: a four-person team, a live demo")

    palette = _md_section(text, "Palette", 2)
    named: dict[str, tuple[str, str]] = {}
    roles: dict[str, str] = {}
    for row in _md_table(_md_section(palette, "Named values", 3)):
        hexes = _HEX.findall(" ".join(row[1:3]))
        if len(row) >= 4 and len(hexes) == 2:
            named[row[0]] = (hexes[0], hexes[1])
            roles[row[0]] = row[3]
    if not 4 <= len(named) <= 6:
        problems.append(f"{len(named)} named colours with light and dark values; 4.7.2 asks for 4 to 6")
    absent = [name for name in DESIGN_NEUTRALS if name not in named]
    if absent:
        problems.append(f"no named {', '.join(absent)}, so contrast cannot be measured")
        return problems, ""

    factors: list[tuple[str, tuple[str, str]]] = []
    for row in _md_table(_md_section(palette, "Score bar colours", 3)):
        hexes = _HEX.findall(" ".join(row[2:4]))
        if len(hexes) == 2:
            factors.append((row[0], (hexes[0], hexes[1])))
    if tuple(name for name, _ in factors) != SCORE_FACTORS:
        problems.append(
            f"score bar colours are {[name for name, _ in factors]}, "
            f"expected {list(SCORE_FACTORS)} in that order"
        )

    states: dict[str, tuple[str, str]] = {}
    for row in _md_table(_md_section(palette, "Build-state colours", 3)):
        hexes = _HEX.findall(" ".join(row[2:4]))
        if len(hexes) == 2:
            states[row[0]] = (hexes[0], hexes[1])
    absent = [state for state in BUILD_STATE_ROWS if state not in states]
    if absent:
        problems.append(f"no build-state colour for {', '.join(absent)}")

    accents = [name for name, role in roles.items() if "Assistant" in role]
    if len(accents) != 2:
        problems.append(f"{len(accents)} assistant accents; 4.7.4 needs one for each of the two")

    worst_text = (math.inf, "")
    worst_normal = worst_cvd = math.inf
    for index, mode in enumerate(("light", "dark")):
        colour = {name: pair[index] for name, pair in named.items()}
        surfaces = {"Panel": colour["Panel"], "Ground": colour["Ground"]}

        text_pairs = [(fg, surface) for fg in ("Ink", "Graphite") for surface in surfaces]
        for fg, surface in text_pairs:
            ratio = _contrast(colour[fg], surfaces[surface])
            worst_text = min(worst_text, (ratio, f"{fg} on {surface}, {mode}"))
            if ratio < TEXT_CONTRAST:
                problems.append(f"{fg} on {surface} ({mode}) is {ratio:.2f}:1, text needs 4.5:1")
        ratio = _contrast(colour["Panel"], colour["Ink"])
        if ratio < TEXT_CONTRAST:
            problems.append(f"the primary button label ({mode}) is {ratio:.2f}:1")

        graphics = {name: colour[name] for name in accents}
        graphics.update({state: pair[index] for state, pair in states.items()})
        graphics.update({name: pair[index] for name, pair in factors})
        for name, value in graphics.items():
            for surface, background in surfaces.items():
                ratio = _contrast(value, background)
                if ratio < GRAPHIC_CONTRAST:
                    problems.append(
                        f"{name} on {surface} ({mode}) is {ratio:.2f}:1, a graphic needs 3:1"
                    )

        for (left, a), (right, b) in zip(factors, factors[1:]):
            normal, cvd = _delta_e(a[index], b[index]), _cvd_delta_e(a[index], b[index])
            worst_normal, worst_cvd = min(worst_normal, normal), min(worst_cvd, cvd)
            if normal < NORMAL_DELTA_E or cvd < CVD_DELTA_E:
                problems.append(
                    f"score bar neighbours {left} and {right} ({mode}) are {normal:.1f} apart, "
                    f"{cvd:.1f} under CVD; the floors are 15 and 8"
                )

        # Status colours are reserved for build states (4.7.5): no factor may pass for one.
        for name, pair in factors:
            for state, state_pair in states.items():
                normal = _delta_e(pair[index], state_pair[index])
                if normal < NORMAL_DELTA_E:
                    problems.append(
                        f"{name} and {state} ({mode}) are only {normal:.1f} apart in normal vision"
                    )

        if len(accents) == 2:
            a, b = colour[accents[0]], colour[accents[1]]
            normal, cvd = _delta_e(a, b), _cvd_delta_e(a, b)
            if normal < NORMAL_DELTA_E or cvd < CVD_DELTA_E:
                problems.append(
                    f"the assistant accents ({mode}) are {normal:.1f} apart, {cvd:.1f} under CVD"
                )

    type_section = _md_section(text, "Type", 2)
    measures = [int(width) for width in re.findall(r"\b(\d+)ch\b", type_section)]
    if not measures or max(measures) >= 80:
        problems.append("Type states no line length under 80 characters")
    if len(_md_table(type_section)) < 3:
        problems.append("Type has no scale table")

    layout = _md_section(text, "Layout", 2)
    for screen in DESIGN_SCREENS:
        body = _md_section(layout, screen, 3).strip()
        if "```text" not in body:
            problems.append(f"Layout has no wireframe for {screen}")
        elif body.startswith("```"):
            problems.append(f"Layout's {screen} has no one-sentence description")

    principles = _md_section(text, "Principles", 2)
    count = len(re.findall(r"^\d+\. ", principles, flags=re.MULTILINE))
    if not 3 <= count <= 5:
        problems.append(f"{count} principles; 4.7.2 asks for three to five")
    if "score bar" not in principles.lower():
        problems.append("no principle names the score bar, the memorable element")

    review = _md_section(text, "Review against the generic traits", 2).lower()
    if review:
        unaddressed = [trait for trait in GENERIC_TRAITS if trait not in review]
        if unaddressed:
            problems.append(f"the review does not address: {', '.join(unaddressed)}")
        if "changed" not in review:
            problems.append("the review does not say what changed")

    summary = (
        f"{len(named)} named colours, {len(factors)} score bar and {len(states)} build-state "
        f"colours; worst text contrast {worst_text[0]:.2f}:1 ({worst_text[1]}); score bar "
        f"neighbours at least {worst_normal:.1f} apart, {worst_cvd:.1f} under CVD; "
        f"{count} principles; wireframes for {', '.join(DESIGN_SCREENS)}"
    )
    return problems, summary


@check(6, "DESIGN.md has every part 4.7.2 asks for, and its colours pass the floors it states")
def check_design_doc() -> Result:
    """T6.1. The structure is Part 4.7.2's list. The colour floors are WCAG 2.2 AA (4.7.5) and the
    dataviz rules the score bar was chosen by. All of it is recomputed from the document's own
    tables, so an edited colour that was not re-measured fails here."""
    if not DESIGN_DOC.is_file():
        return fail("frontend/DESIGN.md is missing (T6.1)")
    problems, summary = design_doc_problems(DESIGN_DOC.read_text(encoding="utf-8"))
    if problems:
        return fail("; ".join(problems))
    return ok(summary)


FRONTEND = REPO_ROOT / "frontend"
OPENAPI_COPY = FRONTEND / "openapi.json"
API_TYPES = FRONTEND / "src" / "api" / "schema.d.ts"
WS_HUB = REPO_ROOT / "backend" / "app" / "ws" / "hub.py"
WS_PROTOCOL = FRONTEND / "src" / "ws" / "events.ts"
# 1.6's quality bars, in the order CI's frontend job runs them.
FRONTEND_BARS = ("lint", "typecheck", "test", "build")
_ANSI_CODES = re.compile(r"\x1b\[[0-9;]*m")


def _npm() -> list[str] | None:
    """npm, or None. On Windows it is a `.cmd` shim, which is only found by its full name."""
    name = "npm.cmd" if os.name == "nt" else "npm"
    return [name] if have(name) else None


def _frontend_ready() -> tuple[list[str] | None, str]:
    npm = _npm()
    if npm is None:
        return None, "npm is not installed"
    if not (FRONTEND / "package.json").is_file():
        return None, "frontend/package.json is missing (T6.2)"
    if not (FRONTEND / "node_modules").is_dir():
        # Never installed here: that needs the network and could change what is being checked.
        return None, "frontend/node_modules is missing; run `npm ci` in frontend/ first"
    return npm, ""


@check(6, "the frontend passes lint, typecheck, test and build")
def check_frontend_quality_bars() -> Result:
    """T6.2 and 1.6: the four scripts CI's frontend job runs, run the same way. A skipped test is a
    failure, as everywhere in this file."""
    npm, why = _frontend_ready()
    if npm is None:
        return fail(why)
    tests = ""
    for script in FRONTEND_BARS:
        result = run([*npm, "run", script], cwd=FRONTEND, timeout=900)
        output = _ANSI_CODES.sub("", result.stdout + result.stderr).strip()
        if result.returncode != 0:
            tail = [line for line in output.splitlines() if line.strip()][-3:]
            saved = _keep_output(f"frontend {script}", output)
            return fail(f"npm run {script} failed: " + " / ".join(tail)[:300] + f" ({saved})")
        if script == "test":
            passed = re.search(r"Tests\s+(\d+) passed", output)
            skipped = re.search(r"(\d+) skipped", output)
            if not passed:
                return fail("npm run test reported nothing passing")
            if skipped and int(skipped.group(1)):
                return fail(f"npm run test: {skipped.group(1)} skipped")
            tests = passed.group(1)
    return ok(f"lint, typecheck and build clean; {tests} tests passed")


@check(6, "the browser flows of 4.7.6 pass against the backend in fake mode")
def check_browser_flows() -> Result:
    """T6.8: Playwright, in the installed Google Chrome, against `backend/browser_backend.py` (the
    real app with LLM_MODE=fake and in-memory stand-ins for Jenkins, its plugin and Git) and the
    built app. The Playwright configuration starts both and makes up the accounts, so this check
    needs no other check first, no Docker and no credential. A skipped or flaky flow is a failure,
    as everywhere in this file."""
    npm, why = _frontend_ready()
    if npm is None:
        return fail(why)
    runner = _uv_runner()
    if runner is None:
        return fail("uv is not installed; see docs/decisions.md D-010")
    result = run(
        [*npm, "exec", "--", "playwright", "test"],
        cwd=FRONTEND,
        timeout=1800,
        env={"E2E_UV": runner[0]},
    )
    output = _ANSI_CODES.sub("", result.stdout + result.stderr).strip()
    if result.returncode != 0:
        tail = [line for line in output.splitlines() if line.strip()][-3:]
        saved = _keep_output("browser flows", output)
        return fail("npx playwright test failed: " + " / ".join(tail)[:300] + f" ({saved})")
    for outcome in ("skipped", "flaky", "did not run"):
        found = re.search(rf"(\d+) {outcome}", output)
        if found and int(found.group(1)):
            return fail(f"npx playwright test: {found.group(1)} {outcome}")
    passed = re.search(r"(\d+) passed", output)
    if not passed:
        return fail("npx playwright test reported nothing passing")
    return ok(f"{passed.group(1)} flows passed in Chrome, against the backend in fake mode")


# 4.7.3's nine screens, and the Admin page as a Developer finds it (T6.9).
SCREENSHOT_SCREENS = (
    "sign-in",
    "overview",
    "freestyle-assistant",
    "pipeline-assistant",
    "queue",
    "jobs-and-runs",
    "analytics",
    "service-catalog",
    "admin",
    "admin-as-developer",
)


@check(6, "screenshots are present for every screen, in both themes at 1440 and 390 px")
def check_screenshots() -> Result:
    """T6.9 and Part 7's Phase 6 row: `docs/screenshots/<screen>-<width>-<theme>.png` for each
    screen. Each must be a PNG whose width is the one its name gives, so a stray or renamed file
    cannot stand in for one. They are made with `SCREENSHOTS=1 npx playwright test --project=
    screenshots` in frontend/."""
    folder = REPO_ROOT / "docs" / "screenshots"
    missing: list[str] = []
    wrong: list[str] = []
    for screen in SCREENSHOT_SCREENS:
        for width in (1440, 390):
            for theme in ("light", "dark"):
                name = f"{screen}-{width}-{theme}.png"
                path = folder / name
                if not path.is_file():
                    missing.append(name)
                    continue
                head = path.read_bytes()[:24]
                if head[:8] != b"\x89PNG\r\n\x1a\n" or int.from_bytes(head[16:20], "big") != width:
                    wrong.append(name)
    if missing:
        return fail(f"{len(missing)} missing, such as {', '.join(missing[:3])}")
    if wrong:
        return fail(f"not a PNG of the width its name gives: {', '.join(wrong[:3])}")
    count = len(SCREENSHOT_SCREENS) * 4
    return ok(f"{count} screenshots: {len(SCREENSHOT_SCREENS)} screens, 1440 and 390 px, light and dark")


@check(6, "the frontend's API types are generated from the backend's current OpenAPI schema")
def check_api_types_current() -> Result:
    """4.7.1: "API types are generated from the backend OpenAPI schema; never hand-write them."

    Two links, each regenerated into the scratch folder and compared byte for byte, never written
    over the committed file: the backend's schema, exported from the app object, against
    `frontend/openapi.json`; and the types `openapi-typescript` makes from that copy against
    `src/api/schema.d.ts`. An API change that skipped either regeneration fails here.
    """
    runner = _uv_runner()
    if runner is None:
        return fail("uv is not installed; see docs/decisions.md D-010")
    npm, why = _frontend_ready()
    if npm is None:
        return fail(why)
    for path in (OPENAPI_COPY, API_TYPES):
        if not path.is_file():
            return fail(f"{path.relative_to(REPO_ROOT).as_posix()} is missing (T6.2)")
    scratch = REPO_ROOT / ".tmp" / "verify"
    scratch.mkdir(parents=True, exist_ok=True)

    exported = scratch / "openapi.json"
    result = run(
        [*runner, "run", "--no-sync", "python", "-m", "app.openapi_export", str(exported)],
        cwd=REPO_ROOT / "backend",
        timeout=300,
    )
    if result.returncode != 0:
        return fail("the schema export failed: " + (result.stderr or result.stdout).strip()[-300:])
    if exported.read_bytes() != OPENAPI_COPY.read_bytes():
        return fail(
            "frontend/openapi.json is not the backend's current schema: in backend/ run "
            "`uv run --no-sync python -m app.openapi_export ../frontend/openapi.json`, then "
            "`npm run generate:api` in frontend/"
        )

    regenerated = scratch / "schema.d.ts"
    result = run(
        [*npm, "exec", "--", "openapi-typescript", "openapi.json", "--output", str(regenerated)],
        cwd=FRONTEND,
        timeout=300,
    )
    if result.returncode != 0:
        return fail("openapi-typescript failed: " + (result.stderr or result.stdout).strip()[-300:])
    if regenerated.read_bytes() != API_TYPES.read_bytes():
        return fail("src/api/schema.d.ts is not generated from openapi.json: run `npm run generate:api`")
    paths = len(json.loads(OPENAPI_COPY.read_text(encoding="utf-8"))["paths"])
    return ok(f"openapi.json is the backend's schema ({paths} paths), and schema.d.ts is its output")


def _python_enum_values(source: str, name: str) -> list[str]:
    match = re.search(rf"^class {name}\(StrEnum\):\n(.*?)(?=^\S)", source, re.MULTILINE | re.DOTALL)
    if not match:
        return []
    return re.findall(r'^\s+[A-Z_]+ = "([^"]+)"$', match.group(1), re.MULTILINE)


def _ts_const_values(source: str, name: str) -> list[str]:
    match = re.search(rf"export const {name} = \[(.*?)\] as const", source, re.DOTALL)
    return re.findall(r'"([^"]+)"', match.group(1)) if match else []


@check(6, "the frontend's WebSocket event and topic names are the backend's")
def check_ws_protocol_names() -> Result:
    """WebSocket messages are not in the OpenAPI schema, so `src/ws/events.ts` names them by hand.
    This keeps those names equal to the backend's `EventType` and `Topic` enums, in both
    directions: an event the frontend cannot parse is dropped silently."""
    for path in (WS_HUB, WS_PROTOCOL):
        if not path.is_file():
            return fail(f"{path.relative_to(REPO_ROOT).as_posix()} is missing")
    hub = WS_HUB.read_text(encoding="utf-8")
    protocol = WS_PROTOCOL.read_text(encoding="utf-8")
    problems = []
    for enum, constant in (("EventType", "LIVE_EVENT_TYPES"), ("Topic", "LIVE_TOPICS")):
        backend = set(_python_enum_values(hub, enum))
        frontend = set(_ts_const_values(protocol, constant))
        if not backend or not frontend:
            problems.append(f"could not read {enum} or {constant}")
        elif backend != frontend:
            only_backend = ", ".join(sorted(backend - frontend)) or "none"
            only_frontend = ", ".join(sorted(frontend - backend)) or "none"
            problems.append(
                f"{enum}: only in the backend {only_backend}; only in the frontend {only_frontend}"
            )
    if problems:
        return fail("; ".join(problems))
    events = len(_python_enum_values(hub, "EventType"))
    topics = len(_python_enum_values(hub, "Topic"))
    return ok(f"{events} event types and {topics} topics, the same on both sides")


IMPLEMENTED_PHASES = {0, 1, 2, 3, 4, 5, 6}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    # A check's message can quote a tool's UTF-8 output. Printed to a file or a pipe on Windows,
    # stdout's default code page cannot encode all of it, and a failing check's message crashed a
    # gate run before the checks after it had run (2026-10-16).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
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
    # Sorted by phase, stably, so checks registered later still print under their own heading.
    # Grouping on phase *changes* alone printed "-- phase 1 --" twice once Phase 1 checks were
    # added below the Phase 2 block.
    selected = sorted(
        (c for c in _REGISTRY if c.phase <= args.phase), key=lambda c: c.phase
    )

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
