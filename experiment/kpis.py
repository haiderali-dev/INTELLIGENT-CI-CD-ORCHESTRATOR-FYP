"""A run's KPIs, from its job records: report Appendix F's, and those Part 4.8.4 adds for v2.

Appendix F: queue waiting time (mean and maximum, overall and per band), completion time, makespan,
throughput and executor utilisation. Scheduling efficiency compares two arms, so ``report``
computes it. New in v2: dependency violations, the longest LOW wait, the scheduler's overhead per
cycle, and for Pipeline jobs the first node block's wait and the sum of all of them.

Times are reported in seconds, to the millisecond, and overheads in milliseconds.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from typing import Any

from experiment.records import JobRecord
from experiment.workload import LEVELS


def run_kpis(
    records: Sequence[JobRecord],
    edges: Iterable[tuple[str, str]],
    executors: int,
    health: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Every KPI of one run. ``edges`` are the workload's (upstream, downstream) pairs."""
    if not records:
        raise ValueError("a run with no jobs has no KPIs")
    if executors < 1:
        raise ValueError("a run needs at least one executor")
    by_name = {record.name: record for record in records}
    makespan_ms = max(r.finished_ms for r in records) - min(r.submitted_ms for r in records)
    waits = [r.wait_ms for r in records]
    low = [r.wait_ms for r in records if r.level == "LOW"]
    # A downstream starts when its work takes an executor: for a Pipeline, its first node block,
    # since the run itself starts the moment its flyweight leaves the queue (D-015).
    violated = [
        [up, down]
        for up, down in edges
        if up in by_name
        and down in by_name
        and by_name[down].work_started_ms < by_name[up].finished_ms
    ]
    busy_ms = sum(r.busy_ms for r in records)
    return {
        "jobs": len(records),
        "succeeded": sum(1 for r in records if r.result == "SUCCESS"),
        "wait_s": {
            **_mean_max(waits),
            "by_level": {
                level: _mean_max([r.wait_ms for r in records if r.level == level])
                for level in reversed(LEVELS)
            },
        },
        "completion_s": _mean_max([r.completion_ms for r in records]),
        "makespan_s": _seconds(makespan_ms),
        "throughput_per_min": round(len(records) * 60_000 / makespan_ms, 3)
        if makespan_ms
        else None,
        "utilization": round(busy_ms / (executors * makespan_ms), 4) if makespan_ms else None,
        "dependency_violations": len(violated),
        "violated_edges": violated,
        "max_low_wait_s": _seconds(max(low)) if low else None,
        "node_block_wait_s": _node_blocks(records),
        "scheduler_overhead_ms": scheduler_overhead(health),
    }


def scheduler_overhead(health: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """The sorter's duration per cycle, from the health samples taken during the run.

    Each sample reports the last sort's duration, so a sort sampled twice appears twice in a row;
    repeats are dropped. Zeros are dropped too: before the first sort the field reads 0.
    """
    values: list[float] = []
    for sample in health:
        value = sample.get("lastSortDurationMillis")
        if isinstance(value, int | float) and value > 0 and (not values or values[-1] != value):
            values.append(float(value))
    if not values:
        return None
    # Inclusive: the default, exclusive method extrapolates past the largest value on a small
    # sample, and a 95th percentile above the maximum means nothing for a duration.
    p95 = (
        statistics.quantiles(values, n=20, method="inclusive")[18] if len(values) > 1 else values[0]
    )
    return {
        "samples": len(values),
        "median": round(statistics.median(values), 4),
        "p95": round(p95, 4),
        "max": round(max(values), 4),
    }


def _node_blocks(records: Sequence[JobRecord]) -> dict[str, Any] | None:
    pipelines = [r for r in records if r.job_type == "pipeline"]
    if not pipelines:
        return None
    first = [r.first_node_block_wait_ms or 0 for r in pipelines]
    total = [r.total_node_block_wait_ms or 0 for r in pipelines]
    return {
        "pipeline_jobs": len(pipelines),
        "first": _mean_max(first),
        "total": _mean_max(total),
    }


def _mean_max(values_ms: Sequence[int]) -> dict[str, Any]:
    if not values_ms:
        return {"jobs": 0, "mean": None, "max": None}
    return {
        "jobs": len(values_ms),
        "mean": _seconds(statistics.fmean(values_ms)),
        "max": _seconds(max(values_ms)),
    }


def _seconds(millis: float) -> float:
    return round(millis / 1000, 3)
