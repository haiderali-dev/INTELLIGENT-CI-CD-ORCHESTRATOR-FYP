#!/usr/bin/env python3
"""Validate catalog/services.yaml.

BUILD_PROMPT task T1.8 fixes the four checks:

1. the file matches its JSON Schema;
2. each repository answers ``git ls-remote``;
3. each agent label exists on ``jenkins-dev``;
4. ``production`` appears in no ``allowed_environments``.

The catalog is the only place a shell command enters the system -- the LLM never writes one
(4.6.1) -- so its contents are checked rather than trusted. A malformed entry here would be
interpolated straight into a Jenkins ``config.xml``.

Checks 2 and 3 need the network and a running controller. They are reported as SKIPPED with the
reason when unavailable, and ``--strict`` turns a skip into a failure for CI.

Usage:
    python scripts/validate_catalog.py
    python scripts/validate_catalog.py --strict      # skips become failures
    python scripts/validate_catalog.py --offline     # schema and policy checks only
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG = REPO_ROOT / "catalog" / "services.yaml"
SCHEMA = REPO_ROOT / "catalog" / "services.schema.json"
ENV_FILE = REPO_ROOT / ".env"

FORBIDDEN_ENVIRONMENT = "production"


@dataclass
class Outcome:
    name: str
    ok: bool
    skipped: bool
    message: str


def passed(name: str, message: str) -> Outcome:
    return Outcome(name, True, False, message)


def failed(name: str, message: str) -> Outcome:
    return Outcome(name, False, False, message)


def skipped(name: str, message: str) -> Outcome:
    return Outcome(name, True, True, message)


def read_env() -> dict[str, str]:
    if not ENV_FILE.is_file():
        return {}
    return dict(
        re.findall(r"^([A-Z_][A-Z0-9_]*)=(.*)$", ENV_FILE.read_text(encoding="utf-8"), re.M)
    )


# ---------------------------------------------------------------------------
# 1. Schema
# ---------------------------------------------------------------------------


def load_catalog() -> tuple[dict[str, Any] | None, Outcome]:
    if not CATALOG.is_file():
        return None, failed("catalog exists", f"{CATALOG.relative_to(REPO_ROOT)} is missing")
    try:
        import yaml
    except ImportError:
        return None, failed("catalog parses", "PyYAML is not installed")
    try:
        document = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, failed("catalog parses", str(exc).splitlines()[0])
    if not isinstance(document, dict):
        return None, failed("catalog parses", "the top level is not a mapping")
    return document, passed("catalog parses", f"{len(document.get('services', []))} services")


def check_schema(document: dict[str, Any]) -> Outcome:
    if not SCHEMA.is_file():
        return failed("matches the JSON Schema", "catalog/services.schema.json is missing")
    try:
        import jsonschema
    except ImportError:
        return skipped("matches the JSON Schema", "jsonschema is not installed")

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    if errors:
        lines = [
            f"{'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}"
            for error in errors[:5]
        ]
        return failed("matches the JSON Schema", "; ".join(lines))
    return passed("matches the JSON Schema", "valid")


# ---------------------------------------------------------------------------
# 2. Repositories reachable
# ---------------------------------------------------------------------------


def check_repositories(document: dict[str, Any], *, offline: bool) -> list[Outcome]:
    if offline:
        return [skipped("repositories answer git ls-remote", "--offline")]

    results: list[Outcome] = []
    for service in document.get("services", []):
        name, repo = service.get("name", "?"), service.get("repo", "")
        try:
            completed = subprocess.run(
                ["git", "ls-remote", "--heads", repo],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
                # Never let git block on a credential prompt: in CI that hangs the build.
                #
                # The full environment is inherited, not replaced. An earlier version passed only
                # PATH, which on Windows drops SystemRoot and makes every clone fail with
                # "getaddrinfo() thread failed to start" -- a resolver error that looks like the
                # repository is unreachable rather than like a broken subprocess environment.
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append(failed(f"repo reachable: {name}", f"{type(exc).__name__}"))
            continue

        if completed.returncode == 0:
            branches = [
                line.split("refs/heads/")[-1]
                for line in completed.stdout.splitlines()
                if "refs/heads/" in line
            ]
            default = service.get("default_branch", "main")
            if default not in branches:
                results.append(
                    failed(
                        f"repo reachable: {name}",
                        f"reachable, but default_branch '{default}' is not among {branches[:5]}",
                    )
                )
            else:
                results.append(passed(f"repo reachable: {name}", f"{len(branches)} branches"))
        else:
            # Not yet created is the expected state until the Needs human item is done, so the
            # message says what to do rather than just reporting a git error.
            results.append(
                failed(
                    f"repo reachable: {name}",
                    f"git ls-remote failed for {repo}. Create and push the repository, or correct "
                    f"the URL. ({completed.stderr.strip().splitlines()[-1][:120] if completed.stderr.strip() else 'no output'})",
                )
            )
    return results


# ---------------------------------------------------------------------------
# 3. Agent labels exist on jenkins-dev
# ---------------------------------------------------------------------------


def jenkins_labels() -> tuple[set[str] | None, str]:
    env = read_env()
    user, token = env.get("JENKINS_USER", "orchestrator-bot"), env.get("JENKINS_TOKEN", "")
    if not token:
        return None, "JENKINS_TOKEN is empty; run scripts/bootstrap.py"

    # /computer/api/json, not /api/json. The root endpoint reports only the controller's own
    # labels, so querying it made every agent label look absent and reported 'linux is on no node'
    # while both agents were online and carrying it.
    url = "http://localhost:8087/computer/api/json?tree=computer[displayName,offline,assignedLabels[name]]"
    request = urllib.request.Request(url)
    request.add_header(
        "Authorization", "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode("ascii")
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return None, f"jenkins-dev returned {exc.code}"
    except Exception as exc:
        return None, f"jenkins-dev unreachable ({type(exc).__name__})"

    labels: set[str] = set()
    for computer in payload.get("computer", []):
        # An offline node's label is not a place a job can actually be scheduled, so it does not
        # count: that is the whole point of the check.
        if computer.get("offline"):
            continue
        for entry in computer.get("assignedLabels", []):
            if name := entry.get("name"):
                labels.add(name)
    return labels, ""


def check_agent_labels(document: dict[str, Any], *, offline: bool) -> list[Outcome]:
    if offline:
        return [skipped("agent labels exist on jenkins-dev", "--offline")]

    labels, problem = jenkins_labels()
    if labels is None:
        return [skipped("agent labels exist on jenkins-dev", problem)]

    results: list[Outcome] = []
    for service in document.get("services", []):
        name, label = service.get("name", "?"), service.get("agent_label", "")
        if label in labels:
            results.append(passed(f"agent label: {name}", f"'{label}' exists"))
        else:
            # A job pinned to a label no node offers sits in the queue forever, which looks like a
            # scheduler bug rather than a configuration error.
            results.append(
                failed(
                    f"agent label: {name}",
                    f"'{label}' is on no node. Available: {sorted(labels)}",
                )
            )
    return results


# ---------------------------------------------------------------------------
# 4. Production appears nowhere
# ---------------------------------------------------------------------------


def check_no_production(document: dict[str, Any]) -> Outcome:
    """Rule 1.5: the scope is staging only, and the code refuses production.

    Checked here as well as in the schema and the policy layer. Three independent places, because
    a single guard on the one thing the project must never do is one edit away from being gone.
    """
    offenders: list[str] = []
    for service in document.get("services", []):
        name = service.get("name", "?")
        if FORBIDDEN_ENVIRONMENT in (service.get("allowed_environments") or []):
            offenders.append(f"{name}.allowed_environments")
        if FORBIDDEN_ENVIRONMENT in (service.get("deploy") or {}):
            offenders.append(f"{name}.deploy")
    if offenders:
        return failed(
            "production appears in no environment",
            "found in: " + ", ".join(offenders) + ". The scope is staging only (rule 1.5).",
        )
    return passed("production appears in no environment", "staging only")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="schema and policy checks only")
    parser.add_argument("--strict", action="store_true", help="treat a skipped check as a failure")
    args = parser.parse_args()

    document, parse_outcome = load_catalog()
    outcomes = [parse_outcome]
    if document is not None:
        outcomes.append(check_schema(document))
        outcomes.append(check_no_production(document))
        outcomes.extend(check_repositories(document, offline=args.offline))
        outcomes.extend(check_agent_labels(document, offline=args.offline))

    print(f"validate_catalog.py   ({len(outcomes)} checks)\n")
    failures = skips = 0
    for outcome in outcomes:
        if outcome.skipped:
            mark, skips = "SKIP", skips + 1
        elif outcome.ok:
            mark = "PASS"
        else:
            mark, failures = "FAIL", failures + 1
        print(f"[{mark}] {outcome.name}\n       {outcome.message}")

    print()
    if failures:
        print(f"{failures} CHECK(S) FAILED" + (f", {skips} skipped" if skips else ""))
        return 1
    if skips and args.strict:
        print(f"{skips} CHECK(S) SKIPPED and --strict was given")
        return 1
    if skips:
        print(f"ALL CHECKS PASSED, {skips} skipped")
        return 0
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
