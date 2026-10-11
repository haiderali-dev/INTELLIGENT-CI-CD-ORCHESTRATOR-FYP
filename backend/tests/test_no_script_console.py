"""The Jenkins script console must never be reachable from our code.

BUILD_PROMPT rule 1.5 is explicit: "A test must fail if ``/scriptText`` appears under ``backend/``
or ``experiment/``." This is that test.

It is not hypothetical. Milestone 2's experiment harness posted Groovy to ``/scriptText``, which
means it ran with the power to execute arbitrary code on the controller, for the sake of creating a
few jobs that the REST API creates perfectly well. ``scripts/verify.py`` enforces the same rule
repository-wide from Phase 0; this keeps it enforced inside the backend's own suite, where a
developer adding a convenience call will see it fail before pushing.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent

# Matched as URL paths rather than bare words, so prose like "a description of the script" or an
# identifier such as `postscript` cannot produce a false positive.
SCRIPT_CONSOLE = re.compile(r"""/scriptText\b|/script(?=["'\s,)/?]|$)|\bdoScript\b""")

# Suffixes worth scanning. Prose cannot call an HTTP endpoint.
CODE_SUFFIXES = {".py", ".pyi", ".toml", ".cfg", ".ini", ".yaml", ".yml", ".json", ".sh", ".j2"}

# This file has to contain the pattern in order to search for it.
SELF = Path(__file__).resolve()


def _code_files(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in CODE_SUFFIXES
        and path.resolve() != SELF
        and ".venv" not in path.parts
        and "__pycache__" not in path.parts
        and "node_modules" not in path.parts
    ]


def _label(path: Path) -> str:
    """A readable path, falling back to the absolute one outside the repository.

    ``relative_to`` raises when given an unrelated path, which the self-test below deliberately
    does when it plants a violation in a temporary directory.
    """
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _offenders(root: Path) -> list[str]:
    found: list[str] = []
    for path in _code_files(root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if SCRIPT_CONSOLE.search(line):
                found.append(f"{_label(path)}:{number}: {line.strip()[:120]}")
    return found


def test_backend_never_calls_the_script_console() -> None:
    offenders = _offenders(BACKEND_ROOT)
    assert not offenders, (
        "The Jenkins script console must never be called from application code.\n"
        "Use the REST API instead; JenkinsClient has a method for everything the backend needs.\n"
        + "\n".join(offenders)
    )


def test_experiment_harness_never_calls_the_script_console() -> None:
    experiment = REPO_ROOT / "experiment"
    if not experiment.is_dir():
        # The harness arrives in Phase 7. Asserting its absence here would be a false pass, so the
        # check is skipped explicitly rather than quietly returning.
        import pytest

        pytest.skip("experiment/ does not exist yet; Phase 7 builds it")
    offenders = _offenders(experiment)
    assert not offenders, (
        "The experiment harness must use only the Jenkins REST API and the plugin's metrics "
        "endpoint. Milestone 2 used the script console here, which is exactly what rule 1.5 "
        "forbids.\n" + "\n".join(offenders)
    )


def test_the_guard_actually_detects_a_violation(tmp_path: Path) -> None:
    """A guard that cannot fail is not a guard.

    The Phase 2 equivalent of this check was, at one point, scanning only tracked files, so a live
    call in a new file passed. Proving the matcher fires on a real call is cheap insurance against
    the same class of mistake here.
    """
    planted = tmp_path / "probe.py"
    planted.write_text(
        "import httpx\n"
        "def run(base: str, script: str) -> str:\n"
        '    return httpx.post(f"{base}/scriptText", data={"script": script}).text\n',
        encoding="utf-8",
    )

    assert _offenders(tmp_path), "the matcher failed to detect a genuine /scriptText call"


def test_the_guard_does_not_flag_prose() -> None:
    """Documenting the prohibition must not trip the check that enforces it."""
    for benign in (
        "never call the script console",
        "a description of the transcript",
        "scriptable = True  # postscript",
        "See docs for the scripting policy.",
    ):
        assert not SCRIPT_CONSOLE.search(benign), f"false positive on: {benign}"
