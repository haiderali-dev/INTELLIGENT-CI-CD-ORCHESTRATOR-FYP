"""Where a run's files go, and ``results/latest.json`` (Part 4.8.3).

Each run gets its own folder, ``results/<UTC time>-<group>-<workload>-<arm>-<N>x-r<repetition>/``:

- ``run.json``: what was run and on what (Part 4.8.3: the plugin version, Jenkins version, executor
  count, workload digest and the configuration in force), and the order the jobs were queued in;
- ``events.jsonl``: the plugin's events recorded during the run, as it reported them;
- ``builds.json``: each job's build in the run, as Jenkins' REST API reports it;
- ``health.jsonl``: the plugin's health, sampled through the run (the scheduler's overhead);
- ``analysis.json``: the KPIs, written by ``analyze``.

The folders are local (``.gitignore``). ``results/latest.json`` is tracked: it names the latest
analysed run and holds its KPIs, and is written after everything it summarises.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Final

RESULTS_DIR: Final = Path(__file__).resolve().parent / "results"
LATEST: Final = "latest.json"
RAW_FILES: Final = ("run.json", "events.jsonl", "builds.json", "health.jsonl")


def run_folder_name(
    started: datetime, group: str, workload: str, arm: str, executors: int, repetition: int
) -> str:
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{group}-{workload}-{arm}-{executors}x-r{repetition}"


def write_json(path: Path, data: Any) -> None:
    """Indented JSON with LF line endings, as the repository stores text."""
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)
    path.write_text(lines, encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def run_folders(results_dir: Path = RESULTS_DIR) -> list[Path]:
    """Every run folder, oldest first (their names start with the time)."""
    if not results_dir.is_dir():
        return []
    return sorted(path for path in results_dir.iterdir() if (path / "run.json").is_file())


def update_latest(run_dir: Path, analysis: dict[str, Any]) -> Path:
    """Point ``latest.json`` at this run, with its KPIs. Written last, after the raw files."""
    latest = run_dir.parent / LATEST
    condition, kpis = analysis["condition"], analysis["kpis"]
    write_json(
        latest,
        {
            "run": run_dir.name,
            "analyzedAt": analysis["analyzedAt"],
            "condition": condition,
            "jobs": kpis["jobs"],
            "succeeded": kpis["succeeded"],
            "dependencyViolations": kpis["dependency_violations"],
            "meanWaitSeconds": kpis["wait_s"]["mean"],
            "makespanSeconds": kpis["makespan_s"],
            "kpis": kpis,
        },
    )
    return latest
