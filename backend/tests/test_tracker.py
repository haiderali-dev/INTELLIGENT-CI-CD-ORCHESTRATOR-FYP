"""``RunTracker``.

The tests are driven one tick at a time against ``FakeJenkinsClient``, so they assert behaviour
rather than timing. The properties that matter: Jenkins being down must not kill the worker, a
plugin-measured queue wait must never be overwritten by a polled estimate, and the two writers of
``job_runs`` (this and the metrics endpoint) must converge on one row per build.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import Job, JobRun, RunResult
from app.services.jenkins import BuildInfo, FakeJenkinsClient, JenkinsError, QueueItem
from app.services.metrics import PendingQueueTimings, QueueTiming
from app.services.tracker import RunTracker, _result_of
from app.ws.hub import EventType, Hub, Topic

ITEM_ID = 7001
BUILD = 4
JOB_NAME = "payment-service-build"


@pytest.fixture
def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest.fixture
def hub() -> Hub:
    return Hub()


class StubJenkins(FakeJenkinsClient):
    """A fake that can be told exactly what to report, and when to fail."""

    def __init__(self) -> None:
        super().__init__()
        self.queue_items: dict[int, QueueItem] = {}
        self.builds: dict[tuple[str, int], BuildInfo] = {}
        self.queue_error: JenkinsError | None = None
        self.build_error: JenkinsError | None = None
        self.queue_calls = 0
        self.build_calls = 0

    async def queue_item(self, item_id: int) -> QueueItem:
        self.queue_calls += 1
        if self.queue_error is not None:
            raise self.queue_error
        if item_id not in self.queue_items:
            raise JenkinsError(f"no such queue item {item_id}")
        return self.queue_items[item_id]

    async def build(self, name: str, number: int) -> BuildInfo:
        self.build_calls += 1
        if self.build_error is not None:
            raise self.build_error
        if (name, number) not in self.builds:
            raise JenkinsError(f"no such build {name} #{number}")
        return self.builds[(name, number)]


@pytest.fixture
def jenkins() -> StubJenkins:
    return StubJenkins()


def tracker_for(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    pending: PendingQueueTimings | None = None,
) -> RunTracker:
    return RunTracker(session_factory=factory, jenkins=jenkins, hub=hub, pending_timings=pending)


async def make_job(db: AsyncSession, name: str = JOB_NAME) -> Job:
    job = Job(jenkins_name=name, job_type="FREESTYLE")
    db.add(job)
    await db.commit()
    return job


def queued(build_number: int | None = None, cancelled: bool = False) -> QueueItem:
    return QueueItem(
        id=ITEM_ID,
        blocked=False,
        buildable=build_number is None,
        stuck=False,
        why=None,
        cancelled=cancelled,
        build_number=build_number,
        job_name=JOB_NAME,
    )


def building(started_ms: int = 1_760_000_000_000) -> BuildInfo:
    return BuildInfo(
        number=BUILD, building=True, result=None, duration_ms=0, timestamp_ms=started_ms
    )


def finished(
    result: str = "SUCCESS", duration_ms: int = 30_000, started_ms: int = 1_760_000_000_000
) -> BuildInfo:
    return BuildInfo(
        number=BUILD,
        building=False,
        result=result,
        duration_ms=duration_ms,
        timestamp_ms=started_ms,
    )


async def events_of(hub: Hub, topics: set[Topic] | None = None) -> list[EventType]:
    """Drain one subscriber's queue into a list of event types."""
    subscriber = await hub.subscribe("t", "u", topics or set(Topic))
    out: list[EventType] = []
    while not subscriber.queue.empty():
        event = subscriber.queue.get_nowait()
        if event is not None:
            out.append(event.type)
    return out


# ---------------------------------------------------------------------------
# Queue item to build number
# ---------------------------------------------------------------------------


async def test_a_queue_item_becomes_a_run_once_jenkins_assigns_a_number(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """The queue item id is the only link between "I asked" and "this build is mine"."""
    job = await make_job(db)
    tracker = tracker_for(factory, jenkins, hub)
    tracker.track(queue_item_id=ITEM_ID, job_id=job.id, job_name=JOB_NAME)
    jenkins.queue_items[ITEM_ID] = queued(build_number=BUILD)
    jenkins.builds[(JOB_NAME, BUILD)] = building()

    await tracker.tick()

    run = await db.scalar(select(JobRun).where(JobRun.job_id == job.id))
    assert run is not None
    assert run.build_number == BUILD
    assert run.queue_item_id == ITEM_ID
    assert tracker.pending_triggers == 0


async def test_an_unassigned_queue_item_stays_pending(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    job = await make_job(db)
    tracker = tracker_for(factory, jenkins, hub)
    tracker.track(queue_item_id=ITEM_ID, job_id=job.id, job_name=JOB_NAME)
    jenkins.queue_items[ITEM_ID] = queued(build_number=None)

    await tracker.tick()

    assert tracker.pending_triggers == 1
    assert await db.scalar(select(JobRun)) is None


async def test_a_cancelled_queue_item_is_forgotten(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """A cancelled trigger never becomes a build; polling it forever would be a slow leak."""
    job = await make_job(db)
    tracker = tracker_for(factory, jenkins, hub)
    tracker.track(queue_item_id=ITEM_ID, job_id=job.id, job_name=JOB_NAME)
    jenkins.queue_items[ITEM_ID] = queued(cancelled=True)

    await tracker.tick()

    assert tracker.pending_triggers == 0
    assert await db.scalar(select(JobRun)) is None


async def test_a_trigger_that_never_resolves_is_abandoned(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """Jenkins forgets cancelled items quickly; without a bound this would poll forever."""
    job = await make_job(db)
    tracker = tracker_for(factory, jenkins, hub)
    tracker.track(queue_item_id=ITEM_ID, job_id=job.id, job_name=JOB_NAME)
    tracker._triggers[ITEM_ID].triggered_at = datetime.now(UTC) - timedelta(hours=2)
    jenkins.queue_items[ITEM_ID] = queued(build_number=None)

    await tracker.tick()

    assert tracker.pending_triggers == 0


async def test_a_queue_item_jenkins_has_forgotten_is_eventually_abandoned(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """The error path needs the same bound as the unassigned path, or it leaks instead."""
    job = await make_job(db)
    tracker = tracker_for(factory, jenkins, hub)
    tracker.track(queue_item_id=ITEM_ID, job_id=job.id, job_name=JOB_NAME)
    tracker._triggers[ITEM_ID].triggered_at = datetime.now(UTC) - timedelta(hours=2)
    # No entry in jenkins.queue_items, so queue_item raises.

    await tracker.tick()

    assert tracker.pending_triggers == 0


# ---------------------------------------------------------------------------
# Advancing runs
# ---------------------------------------------------------------------------


async def test_a_finished_build_records_its_result_and_duration(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    job = await make_job(db)
    db.add(JobRun(job_id=job.id, build_number=BUILD, result=RunResult.RUNNING.value))
    await db.commit()
    jenkins.builds[(JOB_NAME, BUILD)] = finished()

    await tracker_for(factory, jenkins, hub).tick()

    run = await db.scalar(select(JobRun).where(JobRun.job_id == job.id))
    assert run is not None
    await db.refresh(run)
    assert run.result == RunResult.SUCCESS.value
    assert run.duration_ms == 30_000
    assert run.finished_at is not None


async def test_an_unrecognised_result_does_not_become_a_fake_outcome() -> None:
    """Recording an unknown result as SUCCESS would corrupt every success-rate figure."""
    assert _result_of(finished(result="WEIRD")) == RunResult.RUNNING.value
    assert _result_of(finished(result="success")) == RunResult.SUCCESS.value
    assert _result_of(building()) == RunResult.RUNNING.value


async def test_a_finished_run_is_not_polled_again(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """Only RUNNING rows are selected; otherwise every past run would be polled forever."""
    job = await make_job(db)
    db.add(JobRun(job_id=job.id, build_number=BUILD, result=RunResult.SUCCESS.value))
    await db.commit()

    await tracker_for(factory, jenkins, hub).tick()

    assert jenkins.build_calls == 0


async def test_a_run_whose_job_row_is_gone_is_skipped(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """Without the name there is nothing to poll; it must not raise mid-tick."""
    job = await make_job(db)
    db.add(JobRun(job_id=job.id, build_number=BUILD, result=RunResult.RUNNING.value))
    await db.commit()
    await db.delete(job)
    await db.commit()

    await tracker_for(factory, jenkins, hub).tick()  # must not raise


# ---------------------------------------------------------------------------
# Queue waits: the plugin wins
# ---------------------------------------------------------------------------


async def test_a_polled_wait_never_overwrites_a_plugin_measured_one(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """4.4.6: the plugin was inside the queue; this is two timestamps either side of a poll."""
    job = await make_job(db)
    entered = datetime.fromtimestamp(1_760_000_000, tz=UTC)
    db.add(
        JobRun(
            job_id=job.id,
            build_number=BUILD,
            result=RunResult.RUNNING.value,
            queue_entered_at=entered,
            queue_wait_ms=1234,  # measured by the plugin
        )
    )
    await db.commit()
    jenkins.builds[(JOB_NAME, BUILD)] = finished(started_ms=1_760_000_030_000)

    await tracker_for(factory, jenkins, hub).tick()

    run = await db.scalar(select(JobRun).where(JobRun.job_id == job.id))
    assert run is not None
    await db.refresh(run)
    assert run.queue_wait_ms == 1234


async def test_a_wait_is_derived_when_the_plugin_reported_none(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """On a controller without the plugin, a coarse wait beats no wait at all."""
    job = await make_job(db)
    db.add(
        JobRun(
            job_id=job.id,
            build_number=BUILD,
            result=RunResult.RUNNING.value,
            queue_entered_at=datetime.fromtimestamp(1_760_000_000, tz=UTC),
        )
    )
    await db.commit()
    jenkins.builds[(JOB_NAME, BUILD)] = finished(started_ms=1_760_000_030_000)

    await tracker_for(factory, jenkins, hub).tick()

    run = await db.scalar(select(JobRun).where(JobRun.job_id == job.id))
    assert run is not None
    await db.refresh(run)
    assert run.queue_wait_ms == 30_000


async def test_a_parked_plugin_timing_is_attached_once_the_run_exists(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """The queue event always arrives before the run, so the tracker has to pick it up."""
    job = await make_job(db)
    pending = PendingQueueTimings()
    pending.record(QueueTiming(item_id=ITEM_ID, job_name=JOB_NAME, wait_ms=4321))

    tracker = tracker_for(factory, jenkins, hub, pending)
    tracker.track(queue_item_id=ITEM_ID, job_id=job.id, job_name=JOB_NAME)
    jenkins.queue_items[ITEM_ID] = queued(build_number=BUILD)
    jenkins.builds[(JOB_NAME, BUILD)] = building()

    await tracker.tick()

    run = await db.scalar(select(JobRun).where(JobRun.job_id == job.id))
    assert run is not None
    await db.refresh(run)
    assert run.queue_wait_ms == 4321
    assert len(pending) == 0


async def test_the_tracker_adopts_a_run_the_metrics_endpoint_created(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """Both write (job, build); a blind insert would hit the unique constraint instead of merging."""
    job = await make_job(db)
    db.add(JobRun(job_id=job.id, build_number=BUILD, result=RunResult.RUNNING.value))
    await db.commit()

    tracker = tracker_for(factory, jenkins, hub)
    tracker.track(queue_item_id=ITEM_ID, job_id=job.id, job_name=JOB_NAME)
    jenkins.queue_items[ITEM_ID] = queued(build_number=BUILD)
    jenkins.builds[(JOB_NAME, BUILD)] = building()

    await tracker.tick()

    runs = (await db.scalars(select(JobRun).where(JobRun.job_id == job.id))).all()
    assert len(runs) == 1
    await db.refresh(runs[0])
    assert runs[0].queue_item_id == ITEM_ID


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


async def test_jenkins_being_down_does_not_kill_the_worker(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """A tracker that dies stops writing run history and says nothing about it."""
    job = await make_job(db)
    db.add(JobRun(job_id=job.id, build_number=BUILD, result=RunResult.RUNNING.value))
    await db.commit()
    jenkins.build_error = JenkinsError("connection refused")

    tracker = tracker_for(factory, jenkins, hub)
    await tracker.tick()
    await tracker.tick()

    assert tracker.ticks == 2
    run = await db.scalar(select(JobRun).where(JobRun.job_id == job.id))
    assert run is not None
    await db.refresh(run)
    assert run.result == RunResult.RUNNING.value


async def test_a_failing_tick_is_counted_and_the_loop_continues(
    factory: async_sessionmaker[AsyncSession], jenkins: StubJenkins, hub: Hub
) -> None:
    """An unexpected exception must not end the worker either."""
    tracker = tracker_for(factory, jenkins, hub)
    calls = {"n": 0}

    async def exploding_tick() -> None:
        calls["n"] += 1
        raise RuntimeError("boom")

    tracker.tick = exploding_tick  # type: ignore[method-assign]
    tracker._poll_seconds = 0.01
    tracker.start()
    await asyncio.sleep(0.08)
    await tracker.stop()

    assert calls["n"] >= 2
    assert tracker.errors >= 2


async def test_start_is_idempotent(
    factory: async_sessionmaker[AsyncSession], jenkins: StubJenkins, hub: Hub
) -> None:
    """Two tasks polling the same runs would double every poll."""
    tracker = tracker_for(factory, jenkins, hub)
    tracker._poll_seconds = 5.0
    tracker.start()
    first = tracker._task
    tracker.start()

    assert tracker._task is first
    await tracker.stop()


async def test_stop_is_safe_before_start(
    factory: async_sessionmaker[AsyncSession], jenkins: StubJenkins, hub: Hub
) -> None:
    await tracker_for(factory, jenkins, hub).stop()


async def test_stopping_interrupts_the_sleep(
    factory: async_sessionmaker[AsyncSession], jenkins: StubJenkins, hub: Hub
) -> None:
    """Shutdown must be immediate, not up to one interval late."""
    tracker = tracker_for(factory, jenkins, hub)
    tracker._poll_seconds = 30.0
    tracker.start()
    await asyncio.sleep(0.02)

    await asyncio.wait_for(tracker.stop(), timeout=2.0)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


async def test_tracking_a_trigger_publishes_a_queued_event(
    factory: async_sessionmaker[AsyncSession], jenkins: StubJenkins, hub: Hub
) -> None:
    subscriber = await hub.subscribe("s", "u", {Topic.RUNS})
    tracker_for(factory, jenkins, hub).track(queue_item_id=ITEM_ID, job_id="j", job_name=JOB_NAME)

    event = subscriber.queue.get_nowait()
    assert event is not None
    assert event.type is EventType.RUN_QUEUED
    assert event.data["queueItemId"] == ITEM_ID


async def test_a_resolved_build_publishes_run_started(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    job = await make_job(db)
    subscriber = await hub.subscribe("s", "u", set(Topic))
    tracker = tracker_for(factory, jenkins, hub)
    tracker.track(queue_item_id=ITEM_ID, job_id=job.id, job_name=JOB_NAME)
    jenkins.queue_items[ITEM_ID] = queued(build_number=BUILD)
    jenkins.builds[(JOB_NAME, BUILD)] = building()

    await tracker.tick()

    kinds = []
    while not subscriber.queue.empty():
        event = subscriber.queue.get_nowait()
        if event is not None:
            kinds.append(event.type)
    assert EventType.RUN_STARTED in kinds


async def test_a_finished_build_publishes_run_finished(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    hub: Hub,
    db: AsyncSession,
) -> None:
    """The Runs page needs to know the difference between progress and completion."""
    job = await make_job(db)
    db.add(JobRun(job_id=job.id, build_number=BUILD, result=RunResult.RUNNING.value))
    await db.commit()
    jenkins.builds[(JOB_NAME, BUILD)] = finished()
    subscriber = await hub.subscribe("s", "u", {Topic.RUNS})

    await tracker_for(factory, jenkins, hub).tick()

    kinds = []
    while not subscriber.queue.empty():
        event = subscriber.queue.get_nowait()
        if event is not None:
            kinds.append(event.type)
    assert EventType.RUN_FINISHED in kinds


async def test_a_quiet_tick_publishes_nothing(
    factory: async_sessionmaker[AsyncSession], jenkins: StubJenkins, hub: Hub
) -> None:
    """Otherwise every browser re-renders three times a second for no reason."""
    subscriber = await hub.subscribe("s", "u", set(Topic))

    await tracker_for(factory, jenkins, hub).tick()

    assert subscriber.queue.empty()


async def test_publishing_failures_do_not_stop_a_run_being_recorded(
    factory: async_sessionmaker[AsyncSession],
    jenkins: StubJenkins,
    db: AsyncSession,
) -> None:
    """The hub's problems must not become the tracker's."""

    class BrokenHub(Hub):
        def publish(self, event: object) -> int:  # type: ignore[override]
            raise RuntimeError("hub is broken")

    job = await make_job(db)
    db.add(JobRun(job_id=job.id, build_number=BUILD, result=RunResult.RUNNING.value))
    await db.commit()
    jenkins.builds[(JOB_NAME, BUILD)] = finished()

    await tracker_for(factory, jenkins, BrokenHub()).tick()

    run = await db.scalar(select(JobRun).where(JobRun.job_id == job.id))
    assert run is not None
    await db.refresh(run)
    assert run.result == RunResult.SUCCESS.value
