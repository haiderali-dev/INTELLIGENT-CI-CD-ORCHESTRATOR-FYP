"""``RunTracker``: the background worker that follows builds from queue to result.

BUILD_PROMPT 4.4.5: "polls in-flight runs every 3 seconds, maps queue item ids to build numbers,
writes ``job_runs``, and publishes WebSocket events."

Why polling at all, when the plugin already posts metrics? Because the plugin is not the system of
record and must not be. It reports only on the controller it is installed on, only while it is
installed, and only for events it happens to observe; ``jenkins-baseline`` runs without it on
purpose. Polling establishes the run history, and plugin metrics refine the timings polling cannot
see precisely (4.4.6). Either source alone leaves a hole: metrics alone would lose every run on a
controller without the plugin, and polling alone would put a three-second error bar on the queue
waits the whole report is built from.

Three properties the implementation has to hold:

* **Jenkins being down is not fatal.** The tracker logs and retries on the next tick. A worker that
  dies on the first ``JenkinsError`` would stop tracking silently and nothing would notice until
  someone read a run that never finished.
* **One tick cannot run twice.** Each tick is awaited to completion before the next is scheduled,
  so a slow Jenkins stretches the interval instead of stacking concurrent polls on the same run.
* **A tick never leaves half a run written.** Each tick uses one session and commits once.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.db.models import Job, JobRun, RunResult
from app.services.jenkins import BuildInfo, JenkinsClient, JenkinsError
from app.services.metrics import PendingQueueTimings, attach_pending_timings
from app.ws.hub import Event, EventType, Hub

logger = get_logger(__name__)

# 4.4.5 fixes the interval.
POLL_SECONDS: Final = 3.0

# A queue item that never resolves to a build is given up on. Jenkins forgets cancelled items
# quickly, and without a bound a cancelled trigger would be polled until the process restarted.
QUEUE_ITEM_TIMEOUT_SECONDS: Final = 1800.0

# How many runs one tick will poll. A bound so that a backlog cannot turn a three-second tick into
# a minute-long one; the remainder is picked up on the next tick.
MAX_RUNS_PER_TICK: Final = 50


@dataclass
class PendingTrigger:
    """A triggered build whose number Jenkins has not assigned yet."""

    queue_item_id: int
    job_id: str
    job_name: str
    triggered_at: datetime


def _result_of(build: BuildInfo) -> str:
    """Map a Jenkins result onto ``RunResult``.

    An unrecognised result becomes RUNNING rather than a guess: recording an unknown outcome as
    SUCCESS would quietly corrupt every success-rate figure in the report.
    """
    if build.building:
        return RunResult.RUNNING.value
    raw = (build.result or "").upper()
    return raw if raw in set(RunResult) else RunResult.RUNNING.value


def _aware(moment: datetime | None) -> datetime | None:
    """Treat a naive timestamp as UTC.

    SQLite drops the offset on round trip, so a value read back is naive while the same value just
    assigned is aware. Comparing the two raises, which is a crash in the tick rather than a bug in
    the data.
    """
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=UTC)


class RunTracker:
    """Follows triggered builds until they finish.

    Constructed with its collaborators rather than reaching for globals, so a test can drive it one
    tick at a time against a fake Jenkins with no event loop of its own.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        jenkins: JenkinsClient,
        hub: Hub,
        pending_timings: PendingQueueTimings | None = None,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._jenkins = jenkins
        self._hub = hub
        self._pending_timings = pending_timings
        self._poll_seconds = poll_seconds
        self._triggers: dict[int, PendingTrigger] = {}
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self.ticks = 0
        self.errors = 0

    # --- Lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Begin ticking. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run_forever(), name="run-tracker")
        logger.info("tracker_started", interval_seconds=self._poll_seconds)

    async def stop(self) -> None:
        """Stop ticking and wait for the current tick to finish."""
        self._stopping.set()
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        logger.info("tracker_stopped", ticks=self.ticks, errors=self.errors)

    async def _run_forever(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never let a tick kill the worker. A tracker that dies stops writing run history
                # and says nothing about it.
                self.errors += 1
                logger.exception("tracker_tick_failed", ticks=self.ticks)
            # Sleep in a way that a stop interrupts, so shutdown is immediate rather than up to
            # one interval late.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=self._poll_seconds)

    # --- Registration -----------------------------------------------------

    def track(self, *, queue_item_id: int, job_id: str, job_name: str) -> None:
        """Follow a build that has just been triggered.

        Called by whatever triggered it, with the queue item id Jenkins returned. That id is the
        only link between "I asked for a build" and "this build number is mine" -- Jenkins does not
        otherwise tell a caller which build its request became.
        """
        self._triggers[queue_item_id] = PendingTrigger(
            queue_item_id=queue_item_id,
            job_id=job_id,
            job_name=job_name,
            triggered_at=datetime.now(UTC),
        )
        self._publish(
            EventType.RUN_QUEUED,
            {"jobName": job_name, "queueItemId": queue_item_id},
        )

    @property
    def pending_triggers(self) -> int:
        return len(self._triggers)

    # --- One tick ---------------------------------------------------------

    async def tick(self) -> None:
        """Resolve queue items, then advance in-flight runs. One session, one commit."""
        self.ticks += 1
        async with self._session_factory() as session:
            resolved = await self._resolve_queue_items(session)
            advanced = await self._advance_runs(session)
            if self._pending_timings is not None or resolved:
                await self._attach_timings(session)
            await session.commit()

        if resolved or advanced:
            logger.info("tracker_tick", resolved=resolved, advanced=advanced)
            self._publish(EventType.QUEUE_CHANGED, {"resolved": resolved, "advanced": advanced})

    async def _resolve_queue_items(self, session: AsyncSession) -> int:
        """Turn queue item ids into ``job_runs`` rows once Jenkins assigns build numbers."""
        resolved = 0
        now = datetime.now(UTC)

        for trigger in list(self._triggers.values()):
            age = (now - trigger.triggered_at).total_seconds()
            try:
                item = await self._jenkins.queue_item(trigger.queue_item_id)
            except JenkinsError as exc:
                logger.info(
                    "tracker_queue_item_unavailable",
                    queue_item_id=trigger.queue_item_id,
                    error=str(exc)[:200],
                )
                if age > QUEUE_ITEM_TIMEOUT_SECONDS:
                    self._triggers.pop(trigger.queue_item_id, None)
                continue

            if item.cancelled:
                self._triggers.pop(trigger.queue_item_id, None)
                logger.info("tracker_trigger_cancelled", queue_item_id=trigger.queue_item_id)
                continue

            if item.build_number is None:
                if age > QUEUE_ITEM_TIMEOUT_SECONDS:
                    self._triggers.pop(trigger.queue_item_id, None)
                    logger.warning(
                        "tracker_trigger_abandoned",
                        queue_item_id=trigger.queue_item_id,
                        job=trigger.job_name,
                        age_seconds=int(age),
                    )
                continue

            run = await self._upsert_run(
                session,
                job_id=trigger.job_id,
                build_number=item.build_number,
                queue_item_id=trigger.queue_item_id,
            )
            self._triggers.pop(trigger.queue_item_id, None)
            resolved += 1
            self._publish(
                EventType.RUN_STARTED,
                {
                    "runId": run.id,
                    "jobName": trigger.job_name,
                    "buildNumber": item.build_number,
                    "queueItemId": trigger.queue_item_id,
                },
            )

        return resolved

    async def _upsert_run(
        self, session: AsyncSession, *, job_id: str, build_number: int, queue_item_id: int
    ) -> JobRun:
        """Find or create the run for a build number.

        An upsert because a plugin ``BUILD_STARTED`` event may have created the row already --
        both sources write the same (job, build) pair, and the unique constraint on it means a
        blind insert would fail rather than merge.
        """
        run = await session.scalar(
            select(JobRun).where(JobRun.job_id == job_id, JobRun.build_number == build_number)
        )
        if run is None:
            run = JobRun(
                job_id=job_id,
                build_number=build_number,
                queue_item_id=queue_item_id,
                result=RunResult.RUNNING.value,
            )
            session.add(run)
            await session.flush()
        elif run.queue_item_id is None:
            # The metrics path created it without a queue item id; supplying it is what lets a
            # parked queue timing find this run.
            run.queue_item_id = queue_item_id
        return run

    async def _advance_runs(self, session: AsyncSession) -> int:
        """Poll every run still marked RUNNING and record what Jenkins says."""
        runs = (
            await session.scalars(
                select(JobRun)
                .where(JobRun.result == RunResult.RUNNING.value)
                .order_by(JobRun.created_at)
                .limit(MAX_RUNS_PER_TICK)
            )
        ).all()
        if not runs:
            return 0

        advanced = 0
        job_names = await self._job_names(session, [run.job_id for run in runs])

        for run in runs:
            name = job_names.get(run.job_id)
            if name is None:
                continue
            try:
                build = await self._jenkins.build(name, run.build_number)
            except JenkinsError as exc:
                logger.info(
                    "tracker_build_unavailable",
                    job=name,
                    build=run.build_number,
                    error=str(exc)[:200],
                )
                continue

            if self._apply_build(run, build):
                advanced += 1
                finished = run.result != RunResult.RUNNING.value
                self._publish(
                    EventType.RUN_FINISHED if finished else EventType.RUN_UPDATED,
                    {
                        "runId": run.id,
                        "jobName": name,
                        "buildNumber": run.build_number,
                        "result": run.result,
                        "durationMs": run.duration_ms,
                        "queueWaitMs": run.queue_wait_ms,
                    },
                )

        return advanced

    async def _job_names(self, session: AsyncSession, job_ids: list[str]) -> dict[str, str]:
        """Job names for a set of ids, in one query rather than one per run."""
        if not job_ids:
            return {}
        rows = (await session.scalars(select(Job).where(Job.id.in_(set(job_ids))))).all()
        return {job.id: job.jenkins_name for job in rows}

    def _apply_build(self, run: JobRun, build: BuildInfo) -> bool:
        """Copy what Jenkins reports onto a run. Returns whether anything changed."""
        changed = False

        started = _millis(build.timestamp_ms)
        if started is not None and _aware(run.started_at) != started:
            run.started_at = started
            changed = True

        result = _result_of(build)
        if result != run.result:
            run.result = result
            changed = True

        if not build.building:
            if build.duration_ms > 0 and run.duration_ms != build.duration_ms:
                run.duration_ms = build.duration_ms
                changed = True
            finished = _finished_at(build)
            if finished is not None and _aware(run.finished_at) != finished:
                run.finished_at = finished
                changed = True

        # Only fill the wait when nothing better is known. The plugin measured it from inside the
        # queue; this is the difference between two timestamps either side of a three-second poll,
        # so it must never overwrite a plugin value (4.4.6).
        if run.queue_wait_ms is None:
            entered = _aware(run.queue_entered_at)
            started_at = _aware(run.started_at)
            if entered is not None and started_at is not None and started_at >= entered:
                run.queue_wait_ms = int((started_at - entered).total_seconds() * 1000)
                changed = True

        return changed

    async def _attach_timings(self, session: AsyncSession) -> None:
        """Give parked plugin timings the runs they were waiting for."""
        if self._pending_timings is None:
            return
        item_ids = self._pending_timings.item_ids()
        if not item_ids:
            return
        runs = (
            await session.scalars(select(JobRun).where(JobRun.queue_item_id.in_(item_ids)))
        ).all()
        attached = await attach_pending_timings(session, list(runs), pending=self._pending_timings)
        if attached:
            logger.info("tracker_attached_timings", count=attached)

    # --- Publishing -------------------------------------------------------

    def _publish(self, event_type: EventType, data: dict[str, object]) -> None:
        """Publish without letting the hub's problems become the tracker's.

        ``Hub.publish`` is non-blocking and swallows slow clients, but a bug there must still not
        stop a run from being recorded, so this is belt and braces.
        """
        try:
            self._hub.publish(Event(type=event_type, data=dict(data)))
        except Exception:
            # `event_type=`, not `event=`: structlog reserves `event` for the message itself, so
            # passing it raises TypeError *inside the handler* -- turning a swallowed hub fault
            # into a crashed tick, on the one path that exists to prevent exactly that.
            logger.exception("tracker_publish_failed", event_type=str(event_type))


def _millis(value: int) -> datetime | None:
    """A Jenkins millisecond timestamp as aware UTC, treating 0 as unset."""
    if value <= 0:
        return None
    return datetime.fromtimestamp(value / 1000.0, tz=UTC)


def _finished_at(build: BuildInfo) -> datetime | None:
    """When a finished build ended: its start plus its duration."""
    started = _millis(build.timestamp_ms)
    if started is None or build.duration_ms <= 0:
        return None
    return _millis(build.timestamp_ms + build.duration_ms)
