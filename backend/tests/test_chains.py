"""T5.7: the per-service chain lock, chain tracking, Pipeline stage tracking and cancelling.

Against the fake Jenkins, driven one tracker tick at a time. The fake's ``start_downstream`` does
what a downstream trigger does on a real controller -- starts the next job with an upstream cause
-- so the chain logic is exercised exactly as it will meet Jenkins. The live version, on real
agents with a really failing test, is the end-to-end suite's (T5.8).
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import AuditLog, Chain, ChainStatus, Role, RunResult, User
from app.services import chains
from app.services.jenkins import FakeJenkinsClient, StageInfo
from app.services.plugin import FakePluginClient, RankedItem, Ranking, ScoreComponents
from app.services.tracker import RunTracker
from app.ws.hub import Event, Hub
from tests.test_assistants_api import new_chat, say
from tests.test_generation_api import KEY, generated
from tests.test_routers import auth, token_for


class RecordingHub(Hub):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[Event] = []

    def publish(self, event: Event) -> int:
        self.events.append(event)
        return super().publish(event)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [dict(event.data) for event in self.events if event.type.value == kind]


@pytest.fixture
def hub() -> RecordingHub:
    return RecordingHub()


@pytest.fixture
def tracker(engine: AsyncEngine, fake_jenkins: FakeJenkinsClient, hub: RecordingHub) -> RunTracker:
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return RunTracker(session_factory=factory, jenkins=fake_jenkins, hub=hub)


async def approved(client: AsyncClient, token: str, **kwargs: Any) -> dict[str, Any]:
    pipeline = await generated(client, token, **kwargs)
    response = await client.post(
        f"/api/pipelines/{pipeline['id']}/approve", headers={**auth(token), **KEY}
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["result"]
    return result


async def chain_row(db: AsyncSession, chain_id: str) -> Chain:
    db.expire_all()
    chain = await db.get(Chain, chain_id)
    assert chain is not None
    return chain


BTD = "build, test and deploy auth-service to staging"


# ---------------------------------------------------------------------------
# The lock
# ---------------------------------------------------------------------------


async def user(db: AsyncSession, role: Role = Role.DEVELOPER) -> User:
    person = User(
        email=f"{role.value.lower()}-lock@example.com", password_hash="x", role=role.value
    )
    db.add(person)
    await db.flush()
    return person


async def test_one_running_chain_per_service(db: AsyncSession) -> None:
    developer = await user(db)
    first = await chains.claim(
        db,
        service="payment-service",
        job_type="FREESTYLE",
        jobs=["a"],
        parameters={},
        user=developer,
    )

    with pytest.raises(Exception) as raised:
        await chains.claim(
            db,
            service="payment-service",
            job_type="FREESTYLE",
            jobs=["b"],
            parameters={},
            user=developer,
        )

    assert getattr(raised.value, "code", None) is not None
    assert raised.value.details["chain_id"] == first.id  # type: ignore[attr-defined]
    assert raised.value.details["can_cancel"] is False  # type: ignore[attr-defined]
    other = await chains.claim(
        db, service="auth-service", job_type="FREESTYLE", jobs=["c"], parameters={}, user=developer
    )
    assert other.status == ChainStatus.RUNNING.value


async def test_an_admin_is_told_they_may_cancel_it(db: AsyncSession) -> None:
    admin = await user(db, Role.ADMIN)
    await chains.claim(
        db, service="payment-service", job_type="FREESTYLE", jobs=["a"], parameters={}, user=admin
    )

    with pytest.raises(Exception) as raised:
        await chains.claim(
            db,
            service="payment-service",
            job_type="FREESTYLE",
            jobs=["a"],
            parameters={},
            user=admin,
        )

    assert raised.value.details["can_cancel"] is True  # type: ignore[attr-defined]


async def test_an_expired_lock_no_longer_blocks(db: AsyncSession) -> None:
    """4.6.4: a 30-minute expiry. The stale chain is marked EXPIRED when the next one claims."""
    developer = await user(db)
    stale = await chains.claim(
        db,
        service="payment-service",
        job_type="FREESTYLE",
        jobs=["a"],
        parameters={},
        user=developer,
    )
    stale.lock_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.flush()

    assert await chains.running_chain(db, "payment-service") is None
    fresh = await chains.claim(
        db,
        service="payment-service",
        job_type="FREESTYLE",
        jobs=["a"],
        parameters={},
        user=developer,
    )

    assert stale.status == ChainStatus.EXPIRED.value
    assert fresh.status == ChainStatus.RUNNING.value
    assert (fresh.lock_expires_at - fresh.started_at) == timedelta(minutes=chains.LOCK_MINUTES)


async def test_a_new_request_while_its_chain_runs_is_refused(
    client: AsyncClient, db: AsyncSession
) -> None:
    """4.5.5: refused, with the running chain linked."""
    token = await token_for(client, db)
    started = await approved(client, token, text=BTD)
    chat = await new_chat(client, token)

    body = await say(client, token, chat, "build auth-service from main")

    assert body["command"]["status"] == "REFUSED"
    policy = body["command"]["record"]["policy"]
    assert any(reason["code"] == "CHAIN_ALREADY_RUNNING" for reason in policy["reasons"])
    assert started["chain_id"]


async def test_an_admin_is_offered_cancelling_the_running_chain(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db, role=Role.ADMIN)
    await approved(client, token, text=BTD)
    chat = await new_chat(client, token)

    body = await say(client, token, chat, "deploy auth-service to staging")

    assert body["command"]["record"]["policy"]["can_cancel_running"] is True


async def test_approval_is_refused_while_the_service_has_a_running_chain(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db, role=Role.DEVOPS)
    waiting = await generated(client, token, text="build auth-service from main")
    await approved(client, token, text=BTD)

    response = await client.post(
        f"/api/pipelines/{waiting['id']}/approve",
        headers={**auth(token), "Idempotency-Key": "second"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CHAIN_ALREADY_RUNNING"
    pipeline = (await client.get(f"/api/pipelines/{waiting['id']}", headers=auth(token))).json()
    assert pipeline["status"] == "VALIDATED", "a refused approval is not left half-approved"


# ---------------------------------------------------------------------------
# Tracking a freestyle chain
# ---------------------------------------------------------------------------


async def test_a_failed_test_stops_the_chain_before_deploy(
    client: AsyncClient,
    db: AsyncSession,
    fake_jenkins: FakeJenkinsClient,
    tracker: RunTracker,
    hub: RecordingHub,
) -> None:
    """The offline twin of Phase 5's acceptance: against a failing test, deploy never starts."""
    token = await token_for(client, db)
    result = await approved(client, token, text=BTD)
    build, test, deploy = result["jobs"]
    assert (build, test, deploy) == (
        "fs-auth-service-build",
        "fs-auth-service-test-unit",
        "fs-auth-service-deploy-staging",
    )

    fake_jenkins.complete_queue_item(result["queue_item_id"], result="SUCCESS")
    await tracker.tick()  # finds the first build through the chain's queue item
    await tracker.tick()  # reads its result; the test job has not started yet
    fake_jenkins.start_downstream(test, upstream=build, upstream_number=1)
    await tracker.tick()  # finds the test build through its upstream cause
    fake_jenkins.finish_build(test, 1, "FAILURE")
    await tracker.tick()  # reads the failure
    await tracker.tick()  # the chain stops

    chain = await chain_row(db, result["chain_id"])
    assert chain.status == ChainStatus.FAILURE.value
    runs = await chains.chain_runs(db, chain)
    assert set(runs) == {build, test}
    assert deploy not in runs, "the deploy job never started"
    assert not fake_jenkins.jobs[deploy].builds
    finished = hub.of("chain.finished")
    assert finished and finished[-1]["status"] == "FAILURE"


async def test_a_passing_chain_runs_every_job_and_succeeds(
    client: AsyncClient,
    db: AsyncSession,
    fake_jenkins: FakeJenkinsClient,
    tracker: RunTracker,
    hub: RecordingHub,
) -> None:
    token = await token_for(client, db)
    result = await approved(client, token, text=BTD)
    jobs = result["jobs"]

    fake_jenkins.complete_queue_item(result["queue_item_id"], result="SUCCESS")
    await tracker.tick()
    await tracker.tick()
    for upstream, job in itertools.pairwise(jobs):
        number = fake_jenkins.start_downstream(job, upstream=upstream, upstream_number=1).number
        await tracker.tick()
        fake_jenkins.finish_build(job, number, "SUCCESS")
        await tracker.tick()
    await tracker.tick()

    chain = await chain_row(db, result["chain_id"])
    assert chain.status == ChainStatus.SUCCESS.value
    assert chain.position == len(jobs) - 1
    assert set(await chains.chain_runs(db, chain)) == set(jobs)
    assert [event["position"] for event in hub.of("chain.updated")] == [0, 1, 2]
    assert await chains.running_chain(db, "auth-service") is None, "the lock is released"


async def test_a_restarted_backend_finds_the_first_build_again(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, engine: AsyncEngine
) -> None:
    """Nothing about a chain lives only in memory: a fresh tracker picks it up from the row."""
    token = await token_for(client, db)
    result = await approved(client, token, text=BTD)
    fake_jenkins.complete_queue_item(result["queue_item_id"], result="SUCCESS")

    fresh = RunTracker(
        session_factory=async_sessionmaker(bind=engine, expire_on_commit=False),
        jenkins=fake_jenkins,
        hub=Hub(),
    )
    await fresh.tick()

    chain = await chain_row(db, result["chain_id"])
    assert set(await chains.chain_runs(db, chain)) == {result["first_job"]}


# ---------------------------------------------------------------------------
# Tracking a Pipeline's stages
# ---------------------------------------------------------------------------


async def test_pipeline_stages_are_published_when_they_change(
    client: AsyncClient,
    db: AsyncSession,
    fake_jenkins: FakeJenkinsClient,
    tracker: RunTracker,
    hub: RecordingHub,
) -> None:
    token = await token_for(client, db)
    result = await approved(client, token, text=BTD, assistant="pipeline")
    name = result["first_job"]
    # Approval queued the build; put it on an executor, running, with two stages so far.
    item = fake_jenkins.queue[result["queue_item_id"]]
    build = fake_jenkins.start_downstream(name, upstream="none", upstream_number=0)
    fake_jenkins.queue[item.id] = type(item)(
        id=item.id,
        blocked=False,
        buildable=False,
        stuck=False,
        why=None,
        build_number=build.number,
        job_name=name,
    )
    fake_jenkins.jobs[name].stages[build.number] = (
        StageInfo("Checkout", "SUCCESS", 900),
        StageInfo("Build", "IN_PROGRESS", 300),
    )

    await tracker.tick()  # records the run
    await tracker.tick()  # publishes the stages
    await tracker.tick()  # nothing changed: nothing published
    fake_jenkins.jobs[name].stages[build.number] = (
        StageInfo("Checkout", "SUCCESS", 900),
        StageInfo("Build", "SUCCESS", 500),
        StageInfo("Unit tests", "IN_PROGRESS", 100),
    )
    await tracker.tick()

    published = hub.of("chain.stages")
    assert [[stage["status"] for stage in event["stages"]] for event in published] == [
        ["SUCCESS", "IN_PROGRESS"],
        ["SUCCESS", "SUCCESS", "IN_PROGRESS"],
    ]


# ---------------------------------------------------------------------------
# The run card and cancelling
# ---------------------------------------------------------------------------


async def test_the_run_card_shows_jobs_queue_position_and_score(
    client: AsyncClient, db: AsyncSession, fake_plugin: FakePluginClient
) -> None:
    token = await token_for(client, db)
    result = await approved(client, token, text=BTD)
    fake_plugin.ranking_result = Ranking(
        available=True,
        items=(
            RankedItem(
                rank=2,
                item_id=result["queue_item_id"],
                job_name=result["first_job"],
                level="MEDIUM",
                score=0.61,
                components=ScoreComponents(
                    urgency=0.6,
                    dependency=0.5,
                    execution_time=0.4,
                    aging_bonus=0.05,
                    base_score=0.53,
                    own_score=0.58,
                ),
                blocked_reason="Waiting for an executor",
            ),
        ),
        weights={"urgency": 0.5, "dependency": 0.3, "executionTime": 0.2},
    )

    card = (await client.get(f"/api/chains/{result['chain_id']}", headers=auth(token))).json()

    assert card["status"] == "RUNNING"
    assert [job["name"] for job in card["jobs"]] == result["jobs"]
    assert card["jobs"][0]["state"] == "queued"
    assert card["jobs"][1]["state"] == "waiting"
    assert card["queue"]["rank"] == 2
    assert card["queue"]["waiting_reason"] == "Waiting for an executor"
    # The score bar's data, with the inherited score (0.61 above its own 0.58) recognisable.
    assert card["queue"]["components"] == {
        "urgency": 0.6,
        "dependency": 0.5,
        "execution_time": 0.4,
        "aging_bonus": 0.05,
        "base_score": 0.53,
        "own_score": 0.58,
    }
    assert card["queue"]["weights"] == {"urgency": 0.5, "dependency": 0.3, "executionTime": 0.2}


async def test_cancelling_stops_the_running_job_and_dequeues_the_rest(
    client: AsyncClient,
    db: AsyncSession,
    fake_jenkins: FakeJenkinsClient,
    tracker: RunTracker,
) -> None:
    """4.6.4: cancelling a chain cancels queued members and stops the running one."""
    token = await token_for(client, db)
    result = await approved(client, token, text=BTD)
    fake_jenkins.complete_queue_item(result["queue_item_id"], result="SUCCESS")
    await tracker.tick()
    await tracker.tick()
    build, test, _ = result["jobs"]
    fake_jenkins.start_downstream(test, upstream=build, upstream_number=1)
    await tracker.tick()
    queued = await fake_jenkins.trigger(build)  # something of the chain's still waiting

    response = await client.post(f"/api/chains/{result['chain_id']}/cancel", headers=auth(token))

    assert response.status_code == 200, response.text
    assert response.json()["stopped"] == [f"{test}#1"]
    assert ("cancel_queue_item", str(queued)) in fake_jenkins.calls
    chain = await chain_row(db, result["chain_id"])
    assert chain.status == ChainStatus.ABORTED.value
    assert (await db.scalars(select(AuditLog).where(AuditLog.action == "chain.cancelled"))).first()


async def test_only_the_starter_or_devops_may_cancel(client: AsyncClient, db: AsyncSession) -> None:
    owner = await token_for(client, db)
    stranger = await token_for(client, db, email="someone@example.com")
    devops = await token_for(client, db, role=Role.DEVOPS)
    result = await approved(client, owner, text=BTD)
    path = f"/api/chains/{result['chain_id']}/cancel"

    assert (await client.post(path, headers=auth(stranger))).status_code == 403
    assert (await client.post(path, headers=auth(devops))).status_code == 200
    assert (await client.post(path, headers=auth(owner))).status_code == 409, "already finished"


# ---------------------------------------------------------------------------
# Status and re-run through the assistant
# ---------------------------------------------------------------------------


async def test_status_shows_the_latest_run_card(client: AsyncClient, db: AsyncSession) -> None:
    """4.6.5: "What's the status of my last deploy?" -- the latest run card, no generation."""
    token = await token_for(client, db)
    result = await approved(client, token, text=BTD)
    chat = await new_chat(client, token)

    body = await say(client, token, chat, "What's the status of my last deploy?")

    payload = body["assistant_message"]["payload"]
    assert payload["kind"] == "status"
    assert payload["chain"]["id"] == result["chain_id"]
    assert "auth-service chain is running" in body["assistant_message"]["content"]


async def test_rerun_starts_the_last_failed_test_job_again(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    """4.6.5: "Rerun the failed payment-service tests" -- re-trigger the last failed test job."""
    token = await token_for(client, db)
    result = await approved(client, token, text=BTD)
    build, test, deploy = result["jobs"]
    fake_jenkins.complete_queue_item(result["queue_item_id"], result="SUCCESS")
    await tracker.tick()
    await tracker.tick()
    fake_jenkins.start_downstream(test, upstream=build, upstream_number=1)
    await tracker.tick()
    fake_jenkins.finish_build(test, 1, "FAILURE")
    await tracker.tick()
    await tracker.tick()
    chat = await new_chat(client, token)

    body = await say(client, token, chat, "Rerun the failed auth-service tests")

    payload = body["assistant_message"]["payload"]
    assert payload["kind"] == "run", body["assistant_message"]["content"]
    assert payload["first_job"] == test
    assert payload["jobs"] == [test, deploy], (
        "a passing re-run carries on to deploy, as Jenkins will"
    )
    assert [target for action, target in fake_jenkins.calls if action == "trigger"][-1] == test
    rerun = await chain_row(db, payload["chain_id"])
    assert rerun.parameters == result["parameters"]
    assert rerun.status == ChainStatus.RUNNING.value


async def test_rerun_with_nothing_failed_says_so(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db)
    chat = await new_chat(client, token)

    body = await say(client, token, chat, "Rerun the failed payment-service tests")

    assert body["command"]["record"]["intent"]["action"] == "RERUN"
    assert body["assistant_message"]["content"] == "There is no failed test job to re-run."
    assert body["assistant_message"]["payload"]["kind"] == "rerun"


def test_every_chain_status_is_known() -> None:
    assert {status.value for status in ChainStatus} == {
        "RUNNING",
        "SUCCESS",
        "FAILURE",
        "ABORTED",
        "EXPIRED",
    }
    assert RunResult.FAILURE.value == "FAILURE"


@pytest.mark.parametrize(
    ("name", "service", "expected"),
    [
        ("fs-payment-service-test-unit", "payment-service", True),
        ("fs-payment-service-test-integration", "payment-service", True),
        ("fs-payment-service-deploy-staging", "payment-service", False),
        ("fs-payment-service-build", "payment-service", False),
        ("pl-payment-service-test", "payment-service", True),
        ("pl-payment-service-build-test-deploy-staging", "payment-service", True),
        ("pl-payment-service-deploy-staging", "payment-service", False),
        # A service whose own name contains "-test-": reading the whole name made its deploy job
        # look like a test job, so "rerun the failed tests" could re-run a deploy.
        ("fs-load-test-service-deploy-staging", "load-test-service", False),
        ("pl-load-test-service-deploy-staging", "load-test-service", False),
        ("fs-load-test-service-test-unit", "load-test-service", True),
        ("fs-auth-service-test-unit", "payment-service", False),
    ],
)
def test_a_test_job_is_recognised_after_its_service_s_name(
    name: str, service: str, expected: bool
) -> None:
    assert chains.is_test_job(name, service) is expected


async def test_app_starts_with_the_chain_routes(app: FastAPI) -> None:
    paths = set(app.openapi()["paths"])
    assert {"/api/chains", "/api/chains/{chain_id}", "/api/chains/{chain_id}/cancel"} <= paths


# ---------------------------------------------------------------------------
# Denials are audited, even though the refused request is rolled back (4.4.3)
# ---------------------------------------------------------------------------


async def audit_actions(db: AsyncSession) -> list[str]:
    db.expire_all()
    return [row.action for row in (await db.scalars(select(AuditLog))).all()]


async def test_an_approval_refused_by_the_lock_is_audited(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db, role=Role.DEVOPS)
    waiting = await generated(client, token, text="build auth-service from main")
    await approved(client, token, text=BTD)

    response = await client.post(
        f"/api/pipelines/{waiting['id']}/approve",
        headers={**auth(token), "Idempotency-Key": "late"},
    )

    assert response.status_code == 409
    assert "policy.chain_running" in await audit_actions(db)
    # From the approval itself, not the parse: no chain was running when either was parsed.
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "policy.chain_running"))
    assert row is not None
    assert row.target == "auth-service"
    assert row.details["at"] == "approval"
    assert row.details["chain_id"]


async def test_a_refused_cancel_is_audited(client: AsyncClient, db: AsyncSession) -> None:
    owner = await token_for(client, db)
    stranger = await token_for(client, db, email="someone-else@example.com")
    result = await approved(client, owner, text=BTD)

    response = await client.post(f"/api/chains/{result['chain_id']}/cancel", headers=auth(stranger))

    assert response.status_code == 403
    assert "chain.cancel_refused" in await audit_actions(db)
    chain = await chain_row(db, result["chain_id"])
    assert chain.status == ChainStatus.RUNNING.value, "the refusal changed nothing else"


async def test_the_run_card_links_each_build_in_jenkins(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    """4.7.4: the run card ends with "result with duration and a Jenkins link"."""
    token = await token_for(client, db)
    result = await approved(client, token, text=BTD)
    fake_jenkins.complete_queue_item(result["queue_item_id"], result="SUCCESS")
    await tracker.tick()
    await tracker.tick()

    card = (await client.get(f"/api/chains/{result['chain_id']}", headers=auth(token))).json()

    first = card["jobs"][0]["run"]
    assert first["url"] == FakeJenkinsClient.build_url(result["first_job"], first["build_number"])
    assert first["duration_ms"] == 1234
    assert card["jobs"][1]["run"] is None
