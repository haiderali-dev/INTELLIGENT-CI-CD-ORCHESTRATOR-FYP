"""T7.3: the KPIs, computed from hand-made event logs whose every number can be checked by hand.

The workload is three jobs on one executor: ``a`` (LOW, freestyle, 5 s), ``b`` (MEDIUM, freestyle,
10 s, after ``a``) and ``c`` (HIGH, a Pipeline, 8 s, after ``b``), all queued at t0. The log is what
the plugin records: queue entry and exit for every item, node blocks included, and each build's
start and end. It also holds an earlier build of the same jobs, as the plugin's ring does after a
warm-up, which must not leak into this run's figures.
"""

from __future__ import annotations

from typing import Any

import pytest

from experiment import kpis, records, workload
from experiment.records import RecordError

T0 = 1_000_000
HAND = workload.parse(
    {
        "name": "hand",
        "description": "three jobs, written out by hand",
        "prefix": "h-",
        "jobs": [
            {"name": "a", "type": "freestyle", "level": "LOW", "seconds": 5, "dependsOn": []},
            {
                "name": "b",
                "type": "freestyle",
                "level": "MEDIUM",
                "seconds": 10,
                "dependsOn": ["a"],
            },
            {"name": "c", "type": "pipeline", "level": "HIGH", "seconds": 8, "dependsOn": ["b"]},
        ],
    }
)


def queue(kind: str, item: int, job: str, since: int, at: int, **fields: Any) -> dict[str, Any]:
    event = {"kind": kind, "timestamp": at, "itemId": item, "jobName": job, "inQueueSince": since}
    event.update({"isNodeBlock": False, "consumesExecutor": True, "cancelled": False})
    if kind == "QUEUE_LEFT":
        event["waitMillis"] = at - since
    event.update(fields)
    return event


def build(
    kind: str, job: str, number: int, start: int, duration: int | None = None
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "kind": kind,
        "jobName": job,
        "buildNumber": number,
        "startTimeMillis": start,
    }
    event["timestamp"] = start if kind == "BUILD_STARTED" else start + (duration or 0)
    if kind == "BUILD_COMPLETED":
        event.update(durationMillis=duration, result="SUCCESS")
    return event


def warmup_leftovers() -> list[dict[str, Any]]:
    """An earlier build of a and c, still in the plugin's ring: none of it belongs to this run."""
    early = T0 - 100_000
    return [
        queue("QUEUE_LEFT", 50, "h-a", early, early + 9_000),
        build("BUILD_STARTED", "h-a", 1, early + 9_000),
        build("BUILD_COMPLETED", "h-a", 1, early + 9_000, 5_000),
        queue("QUEUE_LEFT", 52, "h-c", early + 20_000, early + 20_100, consumesExecutor=False),
        build("BUILD_STARTED", "h-c", 1, early + 20_100),
        queue("QUEUE_LEFT", 53, "h-c", early + 20_500, early + 30_500, isNodeBlock=True),
        build("BUILD_COMPLETED", "h-c", 1, early + 20_100, 18_000),
    ]


def run_log(c_starts_at: int = T0 + 16_600) -> list[dict[str, Any]]:
    """This run: a, then b, then c, each after its upstream finished, unless c is moved earlier."""
    return [
        *warmup_leftovers(),
        queue("QUEUE_ENTERED", 101, "h-a", T0, T0),
        queue("QUEUE_ENTERED", 102, "h-b", T0, T0),
        queue("QUEUE_ENTERED", 103, "h-c", T0, T0, consumesExecutor=False),
        queue("QUEUE_LEFT", 101, "h-a", T0, T0 + 1_000),
        build("BUILD_STARTED", "h-a", 2, T0 + 1_000),
        build("BUILD_COMPLETED", "h-a", 2, T0 + 1_000, 5_000),
        queue("QUEUE_LEFT", 102, "h-b", T0, T0 + 6_500),
        build("BUILD_STARTED", "h-b", 1, T0 + 6_500),
        build("BUILD_COMPLETED", "h-b", 1, T0 + 6_500, 10_000),
        # c's flyweight leaves the queue when the gate releases it; its node block then waits 200 ms.
        queue("QUEUE_LEFT", 103, "h-c", T0, c_starts_at, consumesExecutor=False),
        build("BUILD_STARTED", "h-c", 2, c_starts_at),
        queue("QUEUE_ENTERED", 104, "h-c", c_starts_at + 400, c_starts_at + 400, isNodeBlock=True),
        queue("QUEUE_LEFT", 104, "h-c", c_starts_at + 400, c_starts_at + 600, isNodeBlock=True),
        build("BUILD_COMPLETED", "h-c", 2, c_starts_at, 8_800),
    ]


BUILDS = {
    "h-a": {
        "number": 2,
        "queueId": 101,
        "timestamp": T0 + 1_000,
        "duration": 5_000,
        "result": "SUCCESS",
    },
    "h-b": {
        "number": 1,
        "queueId": 102,
        "timestamp": T0 + 6_500,
        "duration": 10_000,
        "result": "SUCCESS",
    },
    "h-c": {
        "number": 2,
        "queueId": 103,
        "timestamp": T0 + 16_600,
        "duration": 8_800,
        "result": "SUCCESS",
    },
}


def hand_records(log: list[dict[str, Any]] | None = None) -> dict[str, records.JobRecord]:
    found = records.records_from_events(HAND, run_log() if log is None else log, BUILDS)
    return {record.name: record for record in found}


def test_each_job_is_found_by_its_build_not_by_the_earlier_one_in_the_ring() -> None:
    found = hand_records()
    assert (found["a"].submitted_ms, found["a"].started_ms, found["a"].finished_ms) == (
        T0,
        T0 + 1_000,
        T0 + 6_000,
    )
    assert (found["b"].wait_ms, found["b"].completion_ms) == (6_500, 16_500)


def test_a_pipelines_wait_ends_when_its_node_block_gets_an_executor() -> None:
    c = hand_records()["c"]
    assert c.started_ms == T0 + 16_600
    assert c.work_started_ms == T0 + 17_200
    assert c.wait_ms == 17_200
    assert (c.node_blocks, c.first_node_block_wait_ms, c.total_node_block_wait_ms) == (1, 200, 200)
    assert c.busy_ms == 8_200


def test_the_kpis_of_the_hand_made_run() -> None:
    result = kpis.run_kpis(list(hand_records().values()), HAND.edges, executors=1)
    assert result["jobs"] == 3
    assert result["succeeded"] == 3
    assert result["wait_s"]["mean"] == 8.233
    assert result["wait_s"]["max"] == 17.2
    assert result["wait_s"]["by_level"] == {
        "HIGH": {"jobs": 1, "mean": 17.2, "max": 17.2},
        "MEDIUM": {"jobs": 1, "mean": 6.5, "max": 6.5},
        "LOW": {"jobs": 1, "mean": 1.0, "max": 1.0},
    }
    assert result["completion_s"] == {"jobs": 3, "mean": 15.967, "max": 25.4}
    assert result["makespan_s"] == 25.4
    assert result["throughput_per_min"] == 7.087
    assert result["utilization"] == 0.9134
    assert result["max_low_wait_s"] == 1.0
    assert result["dependency_violations"] == 0
    assert result["violated_edges"] == []
    assert result["node_block_wait_s"] == {
        "pipeline_jobs": 1,
        "first": {"jobs": 1, "mean": 0.2, "max": 0.2},
        "total": {"jobs": 1, "mean": 0.2, "max": 0.2},
    }


def test_a_downstream_started_before_its_upstream_finished_is_a_violation() -> None:
    early = records.records_from_events(HAND, run_log(c_starts_at=T0 + 12_000), BUILDS)
    result = kpis.run_kpis(early, HAND.edges, executors=1)
    assert result["dependency_violations"] == 1
    assert result["violated_edges"] == [["b", "c"]]


def test_utilization_divides_by_every_executor() -> None:
    result = kpis.run_kpis(list(hand_records().values()), HAND.edges, executors=2)
    assert result["utilization"] == round(23_200 / (2 * 25_400), 4)


def test_the_scheduler_overhead_drops_repeats_and_zeros() -> None:
    samples = [{"lastSortDurationMillis": v} for v in (0.0, 0.4, 0.4, 0.6, 0.5)]
    assert kpis.scheduler_overhead(samples) == {
        "samples": 3,
        "median": 0.5,
        "p95": 0.59,
        "max": 0.6,
    }
    assert kpis.scheduler_overhead([{"lastSortDurationMillis": 0.0}]) is None
    assert kpis.scheduler_overhead([]) is None


def test_a_freestyle_only_run_has_no_node_block_figures() -> None:
    only_freestyle = [r for r in hand_records().values() if r.job_type == "freestyle"]
    assert kpis.run_kpis(only_freestyle, [], executors=1)["node_block_wait_s"] is None


def test_a_job_without_a_build_in_the_run_is_an_error() -> None:
    builds = {name: data for name, data in BUILDS.items() if name != "h-b"}
    with pytest.raises(RecordError, match="h-b: no build"):
        records.records_from_events(HAND, run_log(), builds)


def test_a_pipeline_without_a_node_block_is_an_error() -> None:
    log = [e for e in run_log() if e.get("itemId") != 104]
    with pytest.raises(RecordError, match="no recorded node block"):
        hand_records(log)


def test_a_build_still_running_is_an_error() -> None:
    log = [e for e in run_log() if not (e["kind"] == "BUILD_COMPLETED" and e["jobName"] == "h-b")]
    builds = {**BUILDS, "h-b": {**BUILDS["h-b"], "building": True}}
    with pytest.raises(RecordError, match="still building"):
        records.records_from_events(HAND, log, builds)


def test_without_its_queue_events_a_job_is_dated_from_when_it_was_triggered() -> None:
    log = [e for e in run_log() if e.get("itemId") != 102]
    found = records.records_from_events(HAND, log, BUILDS, triggered_ms={"h-b": T0 + 50})
    assert next(r for r in found if r.name == "b").submitted_ms == T0 + 50
    with pytest.raises(RecordError, match="no record of its queue item"):
        records.records_from_events(HAND, log, BUILDS)


def test_a_run_without_jobs_or_executors_has_no_kpis() -> None:
    with pytest.raises(ValueError, match="no jobs"):
        kpis.run_kpis([], [], executors=1)
    with pytest.raises(ValueError, match="executor"):
        kpis.run_kpis(list(hand_records().values()), [], executors=0)


def test_a_record_lists_its_derived_times() -> None:
    data = hand_records()["c"].as_dict()
    assert (data["wait_ms"], data["completion_ms"], data["busy_ms"]) == (17_200, 25_400, 8_200)
