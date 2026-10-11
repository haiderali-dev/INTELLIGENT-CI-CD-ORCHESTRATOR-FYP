"""Ingestion of plugin metric events.

BUILD_PROMPT 4.4.6: "Plugin metrics arriving at ``POST /api/metrics`` fill queue timings that
polling can miss." That is the whole purpose of this module. ``RunTracker`` polls every three
seconds, so it sees that a build started but not the moment its item entered the queue -- and
``queue_wait_ms`` is what every waiting-time KPI in the report derives from. The plugin observes
both moments exactly and posts them here.

The plugin's contract, from ``MetricsPublisher``: one event per request, as a JSON object with
``kind`` and ``timestamp`` plus a flat set of fields, authenticated with a bearer token. Any 2xx
counts as delivered; anything else increments its failure counter. Two consequences:

* unknown fields and unknown kinds are accepted, not rejected. The plugin and the backend are
  versioned separately, and a 422 on a field the plugin added would make the publisher log failures
  and drop the events, losing the data the endpoint exists to collect;
* an event for a job the backend has never heard of is accepted and counted, not an error. The
  experiment harness creates jobs directly against Jenkins, and the plugin reports on those too.

``timestamp`` is the plugin's own wall clock. It is trusted for ordering within one controller,
which is all it is used for; nothing here compares it against the backend's clock.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import Job, JobRun, RunResult

logger = get_logger(__name__)


class EventKind(StrEnum):
    """``MetricEvent.Kind`` in the plugin. Anything else is accepted and ignored."""

    QUEUE_ENTERED = "QUEUE_ENTERED"
    QUEUE_LEFT = "QUEUE_LEFT"
    BUILD_STARTED = "BUILD_STARTED"
    BUILD_COMPLETED = "BUILD_COMPLETED"


# How long an unmatched queue timing is held. A queue event arrives the instant the item is queued;
# the matching job_runs row cannot exist until RunTracker has polled and Jenkins has assigned a
# build number. Thirty minutes covers a long queue wait without holding anything indefinitely.
PENDING_TTL_SECONDS: Final = 1800.0

# A bound, so a controller producing events for jobs this backend does not track cannot grow this
# map without limit. Oldest entries go first.
PENDING_CAPACITY: Final = 2000


@dataclass
class QueueTiming:
    """What the plugin saw about one queue item, before it can be attached to a run."""

    item_id: int
    job_name: str
    entered_at: datetime | None = None
    left_at: datetime | None = None
    wait_ms: int | None = None
    recorded_at: float = 0.0


@dataclass(frozen=True)
class IngestResult:
    """What ingesting one event did, so the endpoint can report it without a second query."""

    accepted: bool
    kind: str
    applied: bool = False
    parked: bool = False
    detail: str = ""


class PendingQueueTimings:
    """Queue timings waiting for a run to attach to, keyed by Jenkins queue item id.

    In memory rather than a table: 4.4.3 lists no table for queue items, and these entries are
    useful for minutes. The cost of losing them on restart is one run with a null
    ``queue_wait_ms``, which the analytics queries already treat as missing rather than as zero.
    """

    def __init__(
        self, *, capacity: int = PENDING_CAPACITY, ttl_seconds: float = PENDING_TTL_SECONDS
    ) -> None:
        self._entries: dict[int, QueueTiming] = {}
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def record(self, timing: QueueTiming) -> None:
        """Store or merge a timing, evicting the oldest when full."""
        now = time.monotonic()
        with self._lock:
            self._expire(now)
            existing = self._entries.get(timing.item_id)
            if existing is None:
                if len(self._entries) >= self._capacity:
                    oldest = min(self._entries.values(), key=lambda entry: entry.recorded_at)
                    del self._entries[oldest.item_id]
                timing.recorded_at = now
                self._entries[timing.item_id] = timing
                return
            # Merge: QUEUE_ENTERED and QUEUE_LEFT arrive separately for the same item.
            existing.entered_at = timing.entered_at or existing.entered_at
            existing.left_at = timing.left_at or existing.left_at
            existing.wait_ms = timing.wait_ms if timing.wait_ms is not None else existing.wait_ms
            existing.job_name = timing.job_name or existing.job_name
            existing.recorded_at = now

    def take(self, item_id: int) -> QueueTiming | None:
        """Remove and return the timing for an item, if it is held."""
        with self._lock:
            self._expire(time.monotonic())
            return self._entries.pop(item_id, None)

    def peek(self, item_id: int) -> QueueTiming | None:
        with self._lock:
            return self._entries.get(item_id)

    def item_ids(self) -> tuple[int, ...]:
        with self._lock:
            self._expire(time.monotonic())
            return tuple(self._entries)

    def _expire(self, now: float) -> None:
        # `>=`, so a ttl of zero means "hold nothing" rather than "hold forever". That makes the
        # expiry testable without a sleep, and no real ttl is affected by the boundary.
        stale = [
            item_id
            for item_id, entry in self._entries.items()
            if entry.recorded_at and now - entry.recorded_at >= self._ttl
        ]
        for item_id in stale:
            del self._entries[item_id]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_pending = PendingQueueTimings()


def get_pending_timings() -> PendingQueueTimings:
    """The process-wide store, as a provider so tests can reset it."""
    return _pending


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------


def _millis_to_datetime(value: Any) -> datetime | None:
    """A plugin millisecond timestamp as an aware UTC datetime.

    Zero and negative values become None. Jenkins reports 0 for "not set" in several places, and
    storing 1970 would make a chart's x-axis span fifty years.
    """
    number = _as_int(value)
    if number is None or number <= 0:
        return None
    return datetime.fromtimestamp(number / 1000.0, tz=UTC)


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


async def ingest_event(
    session: AsyncSession, event: dict[str, Any], *, pending: PendingQueueTimings | None = None
) -> IngestResult:
    """Apply one plugin event. Never raises for anything about the event's content.

    The publisher treats a non-2xx as a failure and moves on, so a bad event must not become an
    error response: the next hundred good events would be posted into the same failing endpoint.
    What is wrong with an event is logged and counted here instead.
    """
    # `pending or _pending` would be wrong here: this class defines __len__, so an *empty* store
    # is falsy and the injected one would be silently replaced by the global. Inject on identity.
    store = _pending if pending is None else pending
    kind = _as_str(event.get("kind")).upper()

    if kind not in set(EventKind):
        # A kind this backend does not know is accepted. The plugin may add one before the backend
        # learns it, and refusing would make the publisher drop every event of that kind.
        logger.info("metric_event_unknown_kind", kind=kind or "(missing)")
        return IngestResult(accepted=True, kind=kind, detail="unknown kind, recorded no change")

    if kind in (EventKind.QUEUE_ENTERED, EventKind.QUEUE_LEFT):
        return await _ingest_queue_event(session, event, kind=EventKind(kind), pending=store)
    return await _ingest_run_event(session, event, kind=EventKind(kind), pending=store)


async def _ingest_queue_event(
    session: AsyncSession,
    event: dict[str, Any],
    *,
    kind: EventKind,
    pending: PendingQueueTimings,
) -> IngestResult:
    """Record a queue entry or exit, attaching it to a run when one exists yet."""
    item_id = _as_int(event.get("itemId"))
    if item_id is None:
        logger.info("metric_event_without_item_id", kind=str(kind))
        return IngestResult(accepted=True, kind=str(kind), detail="no itemId")

    # Node blocks are recorded by the plugin (4.3.9 requires it) but are not themselves runs; the
    # wait they represent is already in the run event's totalNodeBlockWaitMillis.
    if bool(event.get("isNodeBlock")):
        return IngestResult(accepted=True, kind=str(kind), detail="node block, not a run")

    timing = QueueTiming(item_id=item_id, job_name=_as_str(event.get("jobName")))
    if kind is EventKind.QUEUE_ENTERED:
        timing.entered_at = _millis_to_datetime(event.get("inQueueSince") or event.get("timestamp"))
    else:
        timing.left_at = _millis_to_datetime(event.get("timestamp"))
        timing.wait_ms = _as_int(event.get("waitMillis"))
        # Jenkins' own record of when the item was queued, which the plugin forwards on every
        # queue event. Preferred over arithmetic because it is the authoritative value.
        timing.entered_at = _millis_to_datetime(event.get("inQueueSince"))
        if timing.entered_at is None and timing.left_at is not None and timing.wait_ms is not None:
            # Fall back to the span the plugin measured itself. Both numbers come from the same
            # event, so the derived instant is consistent with the wait that is stored beside it.
            timing.entered_at = _millis_to_datetime(
                int(timing.left_at.timestamp() * 1000) - timing.wait_ms
            )

    run = await session.scalar(select(JobRun).where(JobRun.queue_item_id == item_id))
    if run is None:
        pending.record(timing)
        return IngestResult(
            accepted=True, kind=str(kind), parked=True, detail="no run for this queue item yet"
        )

    applied = _apply_timing(run, timing)
    return IngestResult(accepted=True, kind=str(kind), applied=applied)


def _apply_timing(run: JobRun, timing: QueueTiming) -> bool:
    """Copy a timing onto a run. Returns whether anything changed.

    Plugin values win over anything polling inferred: the plugin was inside the queue when it
    happened, and RunTracker can only bracket the moment between two polls.
    """
    changed = False
    if timing.entered_at is not None and run.queue_entered_at != timing.entered_at:
        run.queue_entered_at = timing.entered_at
        changed = True
    if timing.wait_ms is not None and run.queue_wait_ms != timing.wait_ms:
        run.queue_wait_ms = timing.wait_ms
        changed = True
    # Derive the wait when the plugin reported both ends but not the span itself.
    if run.queue_wait_ms is None and timing.entered_at and timing.left_at:
        run.queue_wait_ms = int((timing.left_at - timing.entered_at).total_seconds() * 1000)
        changed = True
    return changed


async def _ingest_run_event(
    session: AsyncSession,
    event: dict[str, Any],
    *,
    kind: EventKind,
    pending: PendingQueueTimings,
) -> IngestResult:
    """Record a build start or completion against its run."""
    job_name = _as_str(event.get("jobName"))
    build_number = _as_int(event.get("buildNumber"))
    if not job_name or build_number is None:
        logger.info("metric_run_event_incomplete", kind=str(kind), job=job_name)
        return IngestResult(accepted=True, kind=str(kind), detail="no jobName or buildNumber")

    job = await session.scalar(select(Job).where(Job.jenkins_name == job_name))
    if job is None:
        # Expected for experiment jobs, which the harness creates directly against Jenkins.
        logger.info("metric_event_untracked_job", kind=str(kind), job=job_name)
        return IngestResult(accepted=True, kind=str(kind), detail="job not tracked here")

    run = await session.scalar(
        select(JobRun).where(JobRun.job_id == job.id, JobRun.build_number == build_number)
    )
    if run is None:
        run = JobRun(job_id=job.id, build_number=build_number, result=RunResult.RUNNING.value)
        session.add(run)

    if kind is EventKind.BUILD_STARTED:
        run.started_at = _millis_to_datetime(event.get("startTimeMillis") or event.get("timestamp"))
        if run.result == "":
            run.result = RunResult.RUNNING.value
    else:
        run.finished_at = _millis_to_datetime(event.get("timestamp"))
        run.started_at = run.started_at or _millis_to_datetime(event.get("startTimeMillis"))
        duration = _as_int(event.get("durationMillis"))
        if duration is not None and duration >= 0:
            run.duration_ms = duration
        result = _as_str(event.get("result")).upper()
        run.result = result if result in set(RunResult) else RunResult.RUNNING.value

    # A queue timing parked before this run existed can now be attached. This is the join that
    # makes the endpoint worth having: the queue event always arrives first.
    applied_timing = await _attach_pending(session, run, pending)

    return IngestResult(accepted=True, kind=str(kind), applied=True, detail=applied_timing)


async def _attach_pending(session: AsyncSession, run: JobRun, pending: PendingQueueTimings) -> str:
    """Attach a parked queue timing to a run, if one is held for its queue item."""
    if run.queue_item_id is None:
        return ""
    timing = pending.take(run.queue_item_id)
    if timing is None:
        return ""
    if _apply_timing(run, timing):
        return "attached a parked queue timing"
    return ""


async def attach_pending_timings(
    session: AsyncSession, runs: list[JobRun], *, pending: PendingQueueTimings | None = None
) -> int:
    """Attach parked timings to runs that now exist. Returns how many were attached.

    Called by ``RunTracker`` after it creates runs, because the queue event for a run always
    arrives before the run itself does.
    """
    store = _pending if pending is None else pending
    attached = 0
    for run in runs:
        if run.queue_item_id is None:
            continue
        timing = store.take(run.queue_item_id)
        if timing is not None and _apply_timing(run, timing):
            attached += 1
    return attached
