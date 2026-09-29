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


IMPLEMENTED_PHASES = {0, 1, 2}


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
