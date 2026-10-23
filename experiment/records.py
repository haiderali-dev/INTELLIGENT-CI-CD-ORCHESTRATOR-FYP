"""From a run's raw events to one record per job: queued, started, given an executor, ended.

The plugin's events are the source (``/dynamic-queue/metrics/recent``). Each workload job built
once in the run, and its events are found by the build Jenkins reports for it:

- its own queue item is the one whose id is the build's ``queueId``, which gives when the job
  entered the queue;
- its build's start and end come from BUILD_STARTED and BUILD_COMPLETED;
- a Pipeline's node blocks are its queue items flagged ``isNodeBlock`` that entered the queue after
  its build started. The first one to leave the queue is when an executor took the work.

The plugin's own ``firstNodeBlockWaitMillis`` is not used: it is recomputed here from the raw
events, as every KPI is, so a reader can check each figure against the rows it came from.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from experiment.workload import Workload


class RecordError(ValueError):
    """The events cannot account for a job's build: a run to repeat, not to analyse."""


@dataclass(frozen=True)
class JobRecord:
    """One job's build in one run. Times are epoch milliseconds from the controller's clock."""

    name: str
    job_type: str
    level: str
    submitted_ms: int
    started_ms: int
    work_started_ms: int
    finished_ms: int
    result: str
    node_blocks: int = 0
    first_node_block_wait_ms: int | None = None
    total_node_block_wait_ms: int | None = None

    @property
    def wait_ms(self) -> int:
        """Queued until an executor took the work, including any time the gate held the job."""
        return self.work_started_ms - self.submitted_ms

    @property
    def completion_ms(self) -> int:
        """Queued until the build ended."""
        return self.finished_ms - self.submitted_ms

    @property
    def busy_ms(self) -> int:
        """How long the job held an executor."""
        return self.finished_ms - self.work_started_ms

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.update(wait_ms=self.wait_ms, completion_ms=self.completion_ms, busy_ms=self.busy_ms)
        return data


def records_from_events(
    workload: Workload,
    events: list[dict[str, Any]],
    builds: dict[str, dict[str, Any]],
    triggered_ms: dict[str, int] | None = None,
) -> list[JobRecord]:
    """One record per workload job, in workload order.

    ``builds`` maps each job's Jenkins name to the build Jenkins reports for this run (``number``,
    ``queueId``, ``timestamp``, ``duration``, ``result``). ``triggered_ms`` is when the harness
    queued each job, used only if the plugin recorded no entry for its queue item.
    """
    return [
        _record(workload, spec.name, events, builds, triggered_ms or {}) for spec in workload.jobs
    ]


def _record(
    workload: Workload,
    name: str,
    events: list[dict[str, Any]],
    builds: dict[str, dict[str, Any]],
    triggered_ms: dict[str, int],
) -> JobRecord:
    spec = workload.job(name)
    jenkins_name = workload.jenkins_name(name)
    build = builds.get(jenkins_name)
    if build is None:
        raise RecordError(f"{jenkins_name}: no build in this run")
    number, queue_id = int(build["number"]), int(build.get("queueId") or -1)

    started = _build_event(events, "BUILD_STARTED", jenkins_name, number)
    completed = _build_event(events, "BUILD_COMPLETED", jenkins_name, number)
    started_ms = int(started["startTimeMillis"]) if started else int(build["timestamp"])
    if completed is None and build.get("building"):
        raise RecordError(f"{jenkins_name} #{number}: still building")
    duration_ms = int(completed["durationMillis"]) if completed else int(build["duration"])
    result = str(completed["result"]) if completed else str(build.get("result") or "UNKNOWN")

    own = [e for e in events if e.get("itemId") == queue_id and e.get("jobName") == jenkins_name]
    since = [int(e["inQueueSince"]) for e in own if e.get("inQueueSince") is not None]
    if since:
        submitted_ms = min(since)
    elif jenkins_name in triggered_ms:
        submitted_ms = triggered_ms[jenkins_name]
    else:
        raise RecordError(f"{jenkins_name} #{number}: no record of its queue item {queue_id}")

    if spec.job_type == "freestyle":
        return JobRecord(
            name=name,
            job_type=spec.job_type,
            level=spec.level,
            submitted_ms=submitted_ms,
            started_ms=started_ms,
            work_started_ms=started_ms,
            finished_ms=started_ms + duration_ms,
            result=result,
        )

    blocks = sorted(
        (
            e
            for e in events
            if e.get("kind") == "QUEUE_LEFT"
            and e.get("jobName") == jenkins_name
            and e.get("isNodeBlock") is True
            and e.get("consumesExecutor") is not False
            and e.get("cancelled") is not True
            and int(e.get("inQueueSince") or 0) >= started_ms
        ),
        key=lambda e: int(e["timestamp"]),
    )
    if not blocks:
        raise RecordError(f"{jenkins_name} #{number}: a Pipeline with no recorded node block")
    waits = [int(e["waitMillis"]) for e in blocks]
    return JobRecord(
        name=name,
        job_type=spec.job_type,
        level=spec.level,
        submitted_ms=submitted_ms,
        started_ms=started_ms,
        work_started_ms=int(blocks[0]["timestamp"]),
        finished_ms=started_ms + duration_ms,
        result=result,
        node_blocks=len(blocks),
        first_node_block_wait_ms=waits[0],
        total_node_block_wait_ms=sum(waits),
    )


def _build_event(
    events: list[dict[str, Any]], kind: str, jenkins_name: str, number: int
) -> dict[str, Any] | None:
    for event in events:
        if (
            event.get("kind") == kind
            and event.get("jobName") == jenkins_name
            and event.get("buildNumber") == number
        ):
            return event
    return None
