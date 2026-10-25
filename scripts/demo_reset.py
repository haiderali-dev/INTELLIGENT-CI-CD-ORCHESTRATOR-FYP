"""Snapshot and restore the demo's known state: the jenkins-dev home and the database (T8.5).

    python scripts/demo_reset.py snapshot [--name demo]
    python scripts/demo_reset.py restore [--name demo] --yes
    python scripts/demo_reset.py list

BUILD_PROMPT 4.10: "snapshots and restores the jenkins-dev home and the database, so a demo always
starts from a known state with warm build history." docs/demo-script.md says when to run each.

- **snapshot** dumps the database with `pg_dump` while everything runs, then stops `jenkins-dev`
  for about a minute to archive its home, so no build or config write is caught half done, and
  starts it again. The archive leaves out `war/`, which Jenkins unpacks again on every start. A
  manifest records the files' checksums and what they hold: the jobs and the database's row
  counts.
- **restore** checks the snapshot against its manifest *before* touching anything. Then it stops
  the backend and `jenkins-dev` and puts the database back in one transaction. It replaces the home
  with the archive, starts both, waits for them to be healthy, and checks that the jobs and the row
  counts are the snapshot's.

Snapshots go to `.demo/snapshots/<name>/`, which is git-ignored: they hold password hashes and
Jenkins' own secrets. Nothing here reads `.env`. The database's credentials stay inside its
container, and the Jenkins home is handled through its Docker volume, never through the API. No
Docker volume is ever removed: a restore replaces the contents of `jenkins-dev`'s home only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = REPO_ROOT / ".demo" / "snapshots"
HOME_VOLUME = "orchestrator_jenkins-dev-home"
HELPER_IMAGE = "orchestrator-jenkins-dev:latest"
HOME_ARCHIVE = "jenkins-dev-home.tar.gz"
DATABASE_DUMP = "orchestrator.dump"
MANIFEST = "manifest.json"
JENKINS_URL = "http://127.0.0.1:8087/login"
BACKEND_URL = "http://127.0.0.1:8000/api/health/live"
TABLES = (
    "users",
    "conversations",
    "messages",
    "nl_commands",
    "generated_pipelines",
    "jobs",
    "job_runs",
    "chains",
    "audit_logs",
    "llm_calls",
)


class ResetError(RuntimeError):
    """A step failed; the message says which, and nothing after it ran."""


def say(message: str) -> None:
    print(f"{datetime.now().strftime('%H:%M:%S')} {message}", flush=True)


def run(command: list[str], *, input_bytes: bytes | None = None, timeout: int = 600) -> bytes:
    """Run a command with the inherited environment (CLAUDE.md: never a minimal one)."""
    result = subprocess.run(  # noqa: S603 - fixed commands, no shell
        command,
        cwd=REPO_ROOT,
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()[-600:]
        raise ResetError(f"`{' '.join(command[:4])} ...` failed: {detail}")
    return result.stdout


def compose(*args: str, input_bytes: bytes | None = None, timeout: int = 600) -> bytes:
    return run(["docker", "compose", *args], input_bytes=input_bytes, timeout=timeout)


def psql(sql: str) -> str:
    """One query in the postgres container, with the credentials its environment holds."""
    out = compose(
        "exec",
        "-T",
        "postgres",
        "sh",
        "-c",
        f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "{sql}"',
    )
    return out.decode("utf-8").strip()


def row_counts() -> dict[str, int]:
    present = set(psql("select tablename from pg_tables where schemaname = 'public'").split())
    return {table: int(psql(f"select count(*) from {table}")) for table in TABLES if table in present}


def home_command(snapshot: Path, script: str, *, readonly_home: bool) -> list[str]:
    """A throwaway container with the home volume at /data and the snapshot folder at /backup."""
    return [
        "docker",
        "run",
        "--rm",
        "-u",
        "0",
        "--entrypoint",
        "sh",
        "--mount",
        f"type=volume,source={HOME_VOLUME},target=/data" + (",readonly" if readonly_home else ""),
        "--mount",
        f"type=bind,source={snapshot},target=/backup",
        HELPER_IMAGE,
        "-c",
        script,
    ]


def wait_healthy(url: str, what: str, timeout: float = 300.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - localhost
                if response.status < 500:
                    say(f"{what} is up")
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(3)
    raise ResetError(f"{what} did not come up within {timeout:.0f} s")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def jobs_in_home() -> list[str]:
    """The jobs in the running controller's home, from the filesystem rather than the API."""
    out = run(["docker", "exec", "orchestrator-jenkins-dev", "ls", "-1", "/var/jenkins_home/jobs"])
    return sorted(line for line in out.decode("utf-8").split() if line)


def jobs_in_archive(archive: Path) -> list[str]:
    out = run(["tar", "-tzf", str(archive)], timeout=300)
    names = set()
    for line in out.decode("utf-8").splitlines():
        parts = line.removeprefix("./").split("/")
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "config.xml":
            names.add(parts[1])
    return sorted(names)


def snapshot(name: str) -> int:
    folder = SNAPSHOTS / name
    folder.mkdir(parents=True, exist_ok=True)
    say(f"snapshot {name}: dumping the database")
    dump = compose(
        "exec", "-T", "postgres", "sh", "-c", 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc'
    )
    (folder / DATABASE_DUMP).write_bytes(dump)
    counts = row_counts()

    say("stopping jenkins-dev to archive its home")
    compose("stop", "jenkins-dev")
    try:
        run(
            home_command(
                folder,
                f"tar -czf /backup/{HOME_ARCHIVE} --exclude=./war -C /data .",
                readonly_home=True,
            ),
            timeout=900,
        )
    finally:
        say("starting jenkins-dev")
        compose("start", "jenkins-dev")
    wait_healthy(JENKINS_URL, "jenkins-dev")

    archive = folder / HOME_ARCHIVE
    manifest = {
        "name": name,
        "created_at": datetime.now(UTC).isoformat(),
        "commit": run(["git", "rev-parse", "--short", "HEAD"]).decode().strip(),
        "files": {
            HOME_ARCHIVE: {"sha256": sha256(archive), "bytes": archive.stat().st_size},
            DATABASE_DUMP: {
                "sha256": sha256(folder / DATABASE_DUMP),
                "bytes": (folder / DATABASE_DUMP).stat().st_size,
            },
        },
        "jobs": jobs_in_archive(archive),
        "rows": counts,
    }
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    say(
        f"snapshot {name}: {len(manifest['jobs'])} jobs, "
        f"{sum(counts.values())} rows in {len(counts)} tables, in {folder.relative_to(REPO_ROOT)}"
    )
    return 0


def load_manifest(name: str) -> tuple[Path, dict[str, Any]]:
    folder = SNAPSHOTS / name
    path = folder / MANIFEST
    if not path.is_file():
        raise ResetError(f"no snapshot called {name!r}: take one with `demo_reset.py snapshot`")
    manifest: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    for file, facts in manifest["files"].items():
        if not (folder / file).is_file() or sha256(folder / file) != facts["sha256"]:
            raise ResetError(f"{file} is missing or does not match the manifest; nothing was changed")
    return folder, manifest


def restore(name: str) -> int:
    folder, manifest = load_manifest(name)
    say(f"restore {name}: the snapshot of {manifest['created_at']} checks out")

    say("stopping the backend and jenkins-dev")
    compose("stop", "backend", "jenkins-dev")
    try:
        say("restoring the database")
        compose(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-c",
            'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner '
            "--single-transaction",
            input_bytes=(folder / DATABASE_DUMP).read_bytes(),
        )
        say("restoring jenkins-dev's home")
        run(
            home_command(
                folder,
                # Everything but war/, which the archive leaves out and Jenkins unpacks itself.
                "find /data -mindepth 1 -maxdepth 1 ! -name war -exec rm -rf {} + "
                f"&& tar -xzf /backup/{HOME_ARCHIVE} -C /data",
                readonly_home=False,
            ),
            timeout=900,
        )
    finally:
        say("starting jenkins-dev and the backend")
        compose("start", "jenkins-dev", "backend")
    wait_healthy(JENKINS_URL, "jenkins-dev")
    wait_healthy(BACKEND_URL, "the backend")

    problems = []
    if jobs_in_home() != manifest["jobs"]:
        problems.append("the jobs differ from the snapshot's")
    counts = row_counts()
    if counts != manifest["rows"]:
        problems.append(f"the row counts differ: {counts} against {manifest['rows']}")
    if problems:
        raise ResetError("the restore did not reach the snapshot's state: " + "; ".join(problems))
    say(
        f"restored {name}: {len(manifest['jobs'])} jobs and {sum(counts.values())} rows, "
        "as the snapshot had them"
    )
    return 0


def list_snapshots() -> int:
    for path in sorted(SNAPSHOTS.glob(f"*/{MANIFEST}")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        size = sum(facts["bytes"] for facts in manifest["files"].values())
        print(
            f"{manifest['name']}: {manifest['created_at']} at {manifest['commit']}, "
            f"{len(manifest['jobs'])} jobs, {size / 1e6:.0f} MB"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("snapshot", "restore"):
        sub = commands.add_parser(name)
        sub.add_argument("--name", default="demo")
        if name == "restore":
            sub.add_argument(
                "--yes", action="store_true", help="replace jenkins-dev's home and the database"
            )
    commands.add_parser("list")
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            return snapshot(args.name)
        if args.command == "restore":
            if not args.yes:
                print(
                    "restore replaces jenkins-dev's home and the database with the snapshot's; "
                    "rerun with --yes to go ahead",
                    file=sys.stderr,
                )
                return 2
            return restore(args.name)
        return list_snapshots()
    except ResetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
