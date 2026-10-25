"""Load the archived experiment runs into the backend's database, for the Analytics page.

    python scripts/import_experiments.py

BUILD_PROMPT 4.7.3 puts on the Analytics page "the M2 series, experiment v2 results, chatbot
evaluation", and 4.4.3 keeps `experiments` and `experiment_metrics` "as the report designs them,
for the Analytics page". The harness writes run folders, not rows, so this fills the tables:

- every run of `docs/experiment/matrix-2026-10-24/runs/` and of the re-run after DF-48's fix,
  `docs/experiment/gate-fix-rerun-2026-10-24/runs/`, one `experiments` row each, labelled by its
  group, with its arm, workload, executors, repetition, versions and configuration;
- Milestone 2's five runs, recomputed from `legacy/m2-poc/` (read only) by `experiment/m2.py`,
  labelled "M2 dispatcher v1" and "M2 stock Jenkins" and never mixed into version 2's rows (Part
  4.8.4);
- for each run, its KPIs as `experiment_metrics` rows, exactly as `analysis.json` holds them. No
  figure is computed here, so the page shows what the harness measured.

Each row's id is derived from its run's name, so importing again replaces those rows and touches
nothing else. The rows are written inside the backend container, through the app's own models, so
nothing here reads `.env` or needs the database's password.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from experiment import m2  # noqa: E402

ARCHIVES = (
    REPO_ROOT / "docs" / "experiment" / "matrix-2026-10-24",
    REPO_ROOT / "docs" / "experiment" / "gate-fix-rerun-2026-10-24",
)

# Run inside the backend container by `python -`, with the rows base64-encoded in DATA.
WRITE = """
import asyncio, base64, json
from datetime import datetime
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker
from app.core.settings import get_settings
from app.db.models import Experiment, ExperimentMetric
from app.db.session import create_engine

DATA = json.loads(base64.b64decode("{payload}").decode("utf-8"))

def when(value):
    return datetime.fromisoformat(value) if value else None

async def main():
    engine = create_engine(get_settings())
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        ids = [row["id"] for row in DATA]
        await session.execute(delete(ExperimentMetric).where(ExperimentMetric.experiment_id.in_(ids)))
        await session.execute(delete(Experiment).where(Experiment.id.in_(ids)))
        for row in DATA:
            experiment = Experiment(
                id=row["id"], label=row["label"], mode=row["mode"], workload=row["workload"],
                executors=row["executors"], repetition=row["repetition"],
                plugin_version=row["plugin_version"], jenkins_version=row["jenkins_version"],
                workload_hash=row["workload_hash"], configuration=row["configuration"],
                started_at=when(row["started_at"]), finished_at=when(row["finished_at"]),
            )
            # The page lists experiments newest first, so a run is dated when it finished.
            if row["finished_at"]:
                experiment.created_at = when(row["finished_at"])
            session.add(experiment)
            for name, band, value, unit in row["metrics"]:
                session.add(ExperimentMetric(
                    experiment_id=row["id"], name=name, band=band, value=value, unit=unit,
                    std_dev=None, sample_size=1,
                ))
        await session.commit()
    await engine.dispose()
    print("imported", len(DATA), "experiments,", sum(len(r["metrics"]) for r in DATA), "metrics")

asyncio.run(main())
"""


def row_id(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]


def metrics(kpis: dict[str, Any]) -> list[tuple[str, str, float, str]]:
    """The KPIs as (name, band, value, unit), only those the run measured."""
    wait = kpis["wait_s"]
    rows: list[tuple[str, str, float, str]] = [("wait_mean", "", wait["mean"], "s")]
    rows += [
        ("wait_mean", band, wait["by_level"][band]["mean"], "s")
        for band in ("HIGH", "MEDIUM", "LOW")
        if wait["by_level"].get(band, {}).get("mean") is not None
    ]
    optional = (
        ("wait_max", wait.get("max"), "s"),
        ("max_low_wait", kpis.get("max_low_wait_s"), "s"),
        ("completion_mean", (kpis.get("completion_s") or {}).get("mean"), "s"),
        ("makespan", kpis.get("makespan_s"), "s"),
        ("throughput", kpis.get("throughput_per_min"), "jobs/min"),
        ("utilization", kpis.get("utilization"), "ratio"),
        ("dependency_violations", kpis.get("dependency_violations"), "count"),
        ("scheduler_overhead_median", (kpis.get("scheduler_overhead_ms") or {}).get("median"), "ms"),
        ("node_block_wait_first", ((kpis.get("node_block_wait_s") or {}).get("first") or {}).get("mean"), "s"),
    )
    rows += [(name, "", float(value), unit) for name, value, unit in optional if value is not None]
    return rows


def v2_rows() -> list[dict[str, Any]]:
    rows = []
    for archive in ARCHIVES:
        for folder in sorted(path for path in (archive / "runs").iterdir() if path.is_dir()):
            run = json.loads((folder / "run.json").read_text(encoding="utf-8"))
            analysis = json.loads((folder / "analysis.json").read_text(encoding="utf-8"))
            build = run.get("pluginBuild")
            rows.append(
                {
                    "id": row_id(f"v2/{folder.name}"),
                    "label": f"v2 {run['group']}",
                    "mode": run["arm"],
                    "workload": run["workload"]["name"],
                    "executors": int(run["executors"]),
                    "repetition": int(run["repetition"]),
                    "plugin_version": (
                        f"{run['pluginVersion']} ({build[:7]})" if run.get("pluginVersion") else None
                    ),
                    "jenkins_version": run.get("jenkinsVersion"),
                    "workload_hash": run["workload"]["digest"][:64],
                    "configuration": {
                        **(run.get("configuration") or {}),
                        "order": analysis["condition"]["order"],
                        "history": run["history"]["kind"],
                        "run": folder.name,
                        "archive": archive.relative_to(REPO_ROOT).as_posix(),
                    },
                    "started_at": run.get("startedAt"),
                    "finished_at": run.get("finishedAt"),
                    "metrics": metrics(analysis["kpis"]),
                }
            )
    return rows


def m2_rows() -> list[dict[str, Any]]:
    rows = []
    for number, run in enumerate(m2.import_m2(), start=1):
        rows.append(
            {
                "id": row_id(f"m2/{run['series']}/{run['run']}"),
                "label": run["series"],
                "mode": "m2-stock" if run["series"] == m2.STOCK_SERIES else "m2-dispatcher-v1",
                "workload": "freestyle-30",
                "executors": 1,
                "repetition": number,
                "plugin_version": None,
                "jenkins_version": None,
                "workload_hash": None,
                "configuration": {"run": run["run"], "source": "legacy/m2-poc/experiment/results"},
                "started_at": None,
                "finished_at": None,
                "metrics": metrics(run["kpis"]),
            }
        )
    return rows


def main() -> int:
    rows = v2_rows() + m2_rows()
    payload = base64.b64encode(json.dumps(rows).encode("utf-8")).decode("ascii")
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "-w", "/app", "backend", "python", "-"],
        input=WRITE.replace("{payload}", payload),
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        print(f"error: the backend container refused: {result.stderr.strip()[-600:]}", file=sys.stderr)
        return 1
    print(result.stdout.strip().splitlines()[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
