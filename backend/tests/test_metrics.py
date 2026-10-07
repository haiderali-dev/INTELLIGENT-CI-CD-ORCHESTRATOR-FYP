"""Plugin metrics ingestion.

The caller is a background thread in the plugin, not a person, and it treats any non-2xx as a
failure and moves on. So the tests that matter are the ones proving this endpoint accepts what it
does not understand: an unknown kind, an unknown field, an untracked job. Each of those returning
422 would make the publisher log failures and drop events, and an experiment would finish with no
queue timings at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.db.models import Job, JobRun, RunResult
from app.services.metrics import (
    EventKind,
    PendingQueueTimings,
    QueueTiming,
    attach_pending_timings,
    get_pending_timings,
    ingest_event,
)

ITEM_ID = 4201
BUILD = 7
JOB_NAME = "payment-service-build"


@pytest.fixture
def token(settings: Settings) -> str:
    return settings.metrics_token


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_job(db: AsyncSession, name: str = JOB_NAME) -> Job:
    job = Job(jenkins_name=name, job_type="FREESTYLE")
    db.add(job)
    await db.commit()
    return job


async def make_run(
    db: AsyncSession, job: Job, *, build: int = BUILD, item_id: int | None = ITEM_ID
) -> JobRun:
    run = JobRun(
        job_id=job.id,
        build_number=build,
        queue_item_id=item_id,
        result=RunResult.RUNNING.value,
    )
    db.add(run)
    await db.commit()
    return run


def queue_entered(item_id: int = ITEM_ID, **extra: object) -> dict[str, object]:
    event: dict[str, object] = {
        "kind": "QUEUE_ENTERED",
        "timestamp": 1_760_000_000_000,
        "itemId": item_id,
        "jobName": JOB_NAME,
        "jobType": "FreeStyleProject",
        "isNodeBlock": False,
        "consumesExecutor": True,
        "inQueueSince": 1_760_000_000_000,
        "optimizerEnabled": True,
    }
    event.update(extra)
    return event


def queue_left(item_id: int = ITEM_ID, wait_ms: int = 12_500, **extra: object) -> dict[str, object]:
    """A QUEUE_LEFT event shaped like the plugin's.

    ``QueueMetricsRecorder.baseEvent`` puts ``inQueueSince`` and ``level`` on every queue event,
    and ``onLeft`` adds the sorter's score components when the item was scored. Leaving those out
    made an earlier version of this helper test a payload the plugin never sends.
    """
    event: dict[str, object] = {
        "kind": "QUEUE_LEFT",
        "timestamp": 1_760_000_012_500,
        "itemId": item_id,
        "jobName": JOB_NAME,
        "jobType": "FreeStyleProject",
        "isNodeBlock": False,
        "consumesExecutor": True,
        "level": "MEDIUM",
        "inQueueSince": 1_760_000_000_000,
        "optimizerEnabled": True,
        "waitMillis": wait_ms,
        "cancelled": False,
        "score": 0.65,
        "baseScore": 0.6,
        "agingBonus": 0.05,
        "urgencyFactor": 0.6,
        "dependencyFactor": 1.0,
        "executionTimeFactor": 0.25,
        "groupId": "payment-service",
        "groupSize": 2,
    }
    event.update(extra)
    return event


def build_completed(**extra: object) -> dict[str, object]:
    event: dict[str, object] = {
        "kind": "BUILD_COMPLETED",
        "timestamp": 1_760_000_042_500,
        "jobName": JOB_NAME,
        "buildNumber": BUILD,
        "jobType": "FreeStyleProject",
        "result": "SUCCESS",
        "durationMillis": 30_000,
        "startTimeMillis": 1_760_000_012_500,
        "agentLabel": "linux",
        "optimizerEnabled": True,
    }
    event.update(extra)
    return event


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


async def test_the_endpoint_needs_the_metrics_token(client: AsyncClient) -> None:
    response = await client.post("/api/metrics", json=queue_entered())

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


async def test_a_wrong_token_is_refused(client: AsyncClient) -> None:
    response = await client.post(
        "/api/metrics", json=queue_entered(), headers=headers("not-the-token")
    )

    assert response.status_code == 401


async def test_the_user_jwt_is_not_accepted_here(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    """The plugin has no user; a credential that works for both would be worse than either."""
    from app.core.security import hash_password
    from app.db.models import Role, User

    db.add(
        User(
            email="dev@example.com",
            password_hash=hash_password("pw-for-this-test"),
            role=Role.DEVELOPER.value,
            active=True,
        )
    )
    await db.commit()
    login = await client.post(
        "/api/auth/login", json={"email": "dev@example.com", "password": "pw-for-this-test"}
    )
    access = login.json()["access_token"]

    response = await client.post("/api/metrics", json=queue_entered(), headers=headers(access))

    assert response.status_code == 401


async def test_an_empty_bearer_is_refused(client: AsyncClient) -> None:
    """An empty configured token must not make every caller valid."""
    response = await client.post("/api/metrics", json=queue_entered(), headers=headers(""))

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# What must never be rejected
# ---------------------------------------------------------------------------


async def test_an_unknown_kind_is_accepted(client: AsyncClient, token: str) -> None:
    """A plugin newer than the backend must not have its events dropped."""
    response = await client.post(
        "/api/metrics",
        json={"kind": "SOMETHING_NEW", "timestamp": 1_760_000_000_000},
        headers=headers(token),
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": 1, "applied": 0, "parked": 0, "ignored": 1}


async def test_unknown_fields_are_accepted(
    client: AsyncClient, db: AsyncSession, token: str
) -> None:
    job = await make_job(db)
    await make_run(db, job)

    response = await client.post(
        "/api/metrics",
        json=build_completed(somethingTheBackendHasNeverSeen=42, another="value"),
        headers=headers(token),
    )

    assert response.status_code == 202
    assert response.json()["applied"] == 1


async def test_an_event_for_an_untracked_job_is_accepted(client: AsyncClient, token: str) -> None:
    """The experiment harness creates jobs straight against Jenkins; the plugin reports on them."""
    response = await client.post(
        "/api/metrics", json=build_completed(jobName="experiment-job-17"), headers=headers(token)
    )

    assert response.status_code == 202
    assert response.json()["ignored"] == 1


async def test_a_malformed_event_is_accepted_rather_than_rejected(
    client: AsyncClient, token: str
) -> None:
    """Missing jobName and buildNumber is not worth a 422 that stops the next hundred events."""
    response = await client.post(
        "/api/metrics", json={"kind": "BUILD_STARTED"}, headers=headers(token)
    )

    assert response.status_code == 202


# ---------------------------------------------------------------------------
# Queue timings: the reason the endpoint exists
# ---------------------------------------------------------------------------


async def test_a_queue_event_fills_the_wait_polling_would_miss(
    client: AsyncClient, db: AsyncSession, token: str
) -> None:
    """4.4.6: the plugin was inside the queue; RunTracker can only bracket between two polls."""
    job = await make_job(db)
    run = await make_run(db, job)

    response = await client.post("/api/metrics", json=queue_left(), headers=headers(token))

    assert response.status_code == 202
    assert response.json()["applied"] == 1
    await db.refresh(run)
    assert run.queue_wait_ms == 12_500
    assert run.queue_entered_at is not None


async def test_a_queue_event_arriving_before_its_run_is_parked(
    client: AsyncClient, db: AsyncSession, token: str
) -> None:
    """This is the normal order: the item is queued before any build number exists."""
    response = await client.post("/api/metrics", json=queue_left(), headers=headers(token))

    assert response.json() == {"accepted": 1, "applied": 0, "parked": 1, "ignored": 0}
    assert get_pending_timings().peek(ITEM_ID) is not None


async def test_a_parked_timing_attaches_when_the_run_appears(
    client: AsyncClient, db: AsyncSession, token: str
) -> None:
    """The join that makes the endpoint worth having."""
    await client.post("/api/metrics", json=queue_left(), headers=headers(token))

    job = await make_job(db)
    run = await make_run(db, job)
    await client.post("/api/metrics", json=build_completed(), headers=headers(token))

    await db.refresh(run)
    assert run.queue_wait_ms == 12_500
    assert get_pending_timings().peek(ITEM_ID) is None


async def test_run_tracker_can_attach_parked_timings_directly(db: AsyncSession) -> None:
    """``RunTracker`` calls this after creating runs, since the queue event always arrives first."""
    pending = PendingQueueTimings()
    pending.record(QueueTiming(item_id=ITEM_ID, job_name=JOB_NAME, wait_ms=9_000, recorded_at=0.0))
    job = await make_job(db)
    run = await make_run(db, job)

    attached = await attach_pending_timings(db, [run], pending=pending)
    await db.commit()

    assert attached == 1
    await db.refresh(run)
    assert run.queue_wait_ms == 9_000


async def test_entered_and_left_merge_into_one_timing(db: AsyncSession, token: str) -> None:
    """The two events arrive separately for the same item and must not overwrite each other."""
    pending = PendingQueueTimings()

    await ingest_event(db, queue_entered(), pending=pending)
    await ingest_event(db, queue_left(wait_ms=0), pending=pending)

    timing = pending.peek(ITEM_ID)
    assert timing is not None
    assert timing.entered_at is not None
    assert timing.left_at is not None


async def test_the_queue_entry_instant_is_derived_when_jenkins_did_not_report_it(
    db: AsyncSession,
) -> None:
    """Both numbers come from the same event, so the derived instant matches the stored wait."""
    pending = PendingQueueTimings()
    job = await make_job(db)
    run = await make_run(db, job)

    # inQueueSince absent, so queue_entered_at has to be derived from the measured span.
    event = queue_left()
    del event["inQueueSince"]
    await ingest_event(db, event, pending=pending)
    await db.commit()

    await db.refresh(run)
    assert run.queue_wait_ms == 12_500


async def test_a_node_block_queue_event_is_not_treated_as_a_run(db: AsyncSession) -> None:
    """4.3.9 records node blocks; their wait is already in the run's totalNodeBlockWaitMillis."""
    pending = PendingQueueTimings()

    result = await ingest_event(db, queue_left(isNodeBlock=True), pending=pending)

    assert result.accepted
    assert not result.applied
    assert len(pending) == 0


# ---------------------------------------------------------------------------
# Run events
# ---------------------------------------------------------------------------


async def test_build_completed_records_the_result_and_duration(
    client: AsyncClient, db: AsyncSession, token: str
) -> None:
    job = await make_job(db)
    run = await make_run(db, job)

    await client.post("/api/metrics", json=build_completed(), headers=headers(token))

    await db.refresh(run)
    assert run.result == RunResult.SUCCESS.value
    assert run.duration_ms == 30_000
    assert run.finished_at is not None
    assert run.started_at is not None


async def test_an_unrecognised_result_does_not_become_a_fake_outcome(
    client: AsyncClient, db: AsyncSession, token: str
) -> None:
    """Recording "WEIRD" as SUCCESS would quietly corrupt every success-rate figure."""
    job = await make_job(db)
    run = await make_run(db, job)

    await client.post("/api/metrics", json=build_completed(result="WEIRD"), headers=headers(token))

    await db.refresh(run)
    assert run.result == RunResult.RUNNING.value


async def test_build_started_creates_a_run_when_none_exists(
    client: AsyncClient, db: AsyncSession, token: str
) -> None:
    """A build triggered outside the orchestrator still belongs in the history of a tracked job."""
    job = await make_job(db)

    await client.post(
        "/api/metrics",
        json={
            "kind": "BUILD_STARTED",
            "timestamp": 1_760_000_012_500,
            "jobName": JOB_NAME,
            "buildNumber": 99,
            "startTimeMillis": 1_760_000_012_500,
        },
        headers=headers(token),
    )

    run = await db.scalar(select(JobRun).where(JobRun.job_id == job.id, JobRun.build_number == 99))
    assert run is not None
    assert run.started_at is not None


async def test_a_second_event_for_the_same_build_updates_one_row(
    client: AsyncClient, db: AsyncSession, token: str
) -> None:
    """The plugin may redeliver; two rows for one build would double every count."""
    job = await make_job(db)

    for _ in range(3):
        await client.post("/api/metrics", json=build_completed(), headers=headers(token))

    runs = (await db.scalars(select(JobRun).where(JobRun.job_id == job.id))).all()
    assert len(runs) == 1


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


async def test_a_zero_timestamp_does_not_become_1970(
    client: AsyncClient, db: AsyncSession, token: str
) -> None:
    """Jenkins reports 0 for "not set"; storing it would stretch a chart's axis over fifty years."""
    job = await make_job(db)
    run = await make_run(db, job)

    await client.post(
        "/api/metrics",
        json=build_completed(startTimeMillis=0, timestamp=0),
        headers=headers(token),
    )

    await db.refresh(run)
    assert run.started_at is None
    assert run.finished_at is None


async def test_timestamps_are_stored_as_aware_utc(
    client: AsyncClient, db: AsyncSession, token: str
) -> None:
    job = await make_job(db)
    run = await make_run(db, job)

    await client.post("/api/metrics", json=build_completed(), headers=headers(token))

    await db.refresh(run)
    assert run.finished_at is not None
    stored = run.finished_at
    if stored.tzinfo is None:  # SQLite drops the offset; the value must still be the UTC instant
        stored = stored.replace(tzinfo=UTC)
    assert stored == datetime.fromtimestamp(1_760_000_042.5, tz=UTC)


# ---------------------------------------------------------------------------
# Batches and bounds
# ---------------------------------------------------------------------------


async def test_a_batch_is_accepted(client: AsyncClient, db: AsyncSession, token: str) -> None:
    """For the experiment harness replaying recorded events."""
    job = await make_job(db)
    await make_run(db, job)

    response = await client.post(
        "/api/metrics",
        json={"events": [queue_left(), build_completed()]},
        headers=headers(token),
    )

    assert response.status_code == 202
    assert response.json()["accepted"] == 2


async def test_the_parked_store_is_bounded(db: AsyncSession) -> None:
    """A controller reporting jobs this backend does not track must not grow the map forever."""
    pending = PendingQueueTimings(capacity=5)

    for item_id in range(50):
        await ingest_event(db, queue_left(item_id=item_id), pending=pending)

    assert len(pending) == 5


async def test_parked_timings_expire(db: AsyncSession) -> None:
    pending = PendingQueueTimings(ttl_seconds=0.0)
    await ingest_event(db, queue_left(), pending=pending)

    assert pending.take(ITEM_ID) is None


def test_every_plugin_event_kind_is_handled() -> None:
    """The plugin's ``MetricEvent.Kind`` has four values; all four must be known here."""
    assert {kind.value for kind in EventKind} == {
        "QUEUE_ENTERED",
        "QUEUE_LEFT",
        "BUILD_STARTED",
        "BUILD_COMPLETED",
    }
