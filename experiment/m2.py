"""T7.5: Milestone 2's measured runs, imported as their own series, "M2 dispatcher v1".

Part 4.8.4: import the Milestone 2 numbers as a labelled series and never mix them into v2
aggregates. They come from its raw result files in ``legacy/`` (read only), recomputed with the
same KPI code as a v2 run, not from its stored ``comparison.json``, which disagrees with its own
inputs (DF-01, ``docs/m2-baseline.md``).

Milestone 2 queued all 30 jobs at its ``t0`` and recorded each build's start and duration, so a
job's wait is its start minus ``t0``, as its own analysis defined it. It ran on one executor. Its
stock-Jenkins control is kept apart as "M2 stock Jenkins", so that "M2 dispatcher v1" means only
the plugin it measured.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from experiment.jenkins import REPO_ROOT
from experiment.kpis import run_kpis
from experiment.records import JobRecord
from experiment.workload import Workload, load

M2_RESULTS: Final = REPO_ROOT / "legacy" / "m2-poc" / "experiment" / "results"
SERIES: Final = "M2 dispatcher v1"
STOCK_SERIES: Final = "M2 stock Jenkins"
#: (series, run label, result file): every run Milestone 2 kept.
RUNS: Final = (
    (STOCK_SERIES, "stock Jenkins (FIFO)", "baseline-results.json"),
    (SERIES, "run 1", "plugin-results.json"),
    (SERIES, "run 2", "plugin-results-run2.json"),
    (SERIES, "run 3", "plugin-results-run3.json"),
    (SERIES, "run 4 (the report's)", "plugin-results-run4.json"),
)


def m2_records(result: dict[str, Any], jobs: Workload) -> list[JobRecord]:
    """One record per workload job from a Milestone 2 result file.

    The baseline file holds a 31st job that is not in the workload (``docs/m2-baseline.md`` 4.2);
    jobs outside the workload are ignored.
    """
    t0 = int(result["t0"])
    by_name = {str(job["name"]): job for job in result["jobs"]}
    records = []
    for spec in jobs.jobs:
        job = by_name.get(spec.name)
        if job is None:
            raise ValueError(f"Milestone 2 result {result.get('label')}: no build of {spec.name}")
        start = int(job["startTime"])
        records.append(
            JobRecord(
                name=spec.name,
                job_type="freestyle",
                level=spec.level,
                submitted_ms=t0,
                started_ms=start,
                work_started_ms=start,
                finished_ms=start + int(job["duration"]),
                result=str(job.get("result") or "UNKNOWN"),
            )
        )
    return records


def import_m2(results_dir: Path = M2_RESULTS) -> list[dict[str, Any]]:
    """Every Milestone 2 run, with its KPIs, labelled with its series."""
    jobs = load("freestyle-30")
    imported = []
    for series, label, filename in RUNS:
        result = json.loads((results_dir / filename).read_text(encoding="utf-8"))
        records = m2_records(result, jobs)
        imported.append(
            {
                "series": series,
                "run": label,
                "file": f"legacy/m2-poc/experiment/results/{filename}",
                "kpis": run_kpis(records, jobs.edges, executors=1),
            }
        )
    return imported
