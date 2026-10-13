"""T5.9: ``POST /api/runs/{id}/explain``, through the API, on chains run against the fake Jenkins.

The failed build's log is the real auth-service log from jenkins-dev (``tests/data/failure_logs``),
so the endpoint is exercised on the text it will meet. The live version, with a real failing test
on real agents and the model answering, is the end-to-end suite's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.ai.providers import FakeProvider
from app.ai.quota import QuotaTracker
from app.api.deps import get_failure_explainer
from app.core.settings import Settings
from app.db.models import GeneratedPipeline, LlmCall
from app.failures.explainer import fake_failure_responder
from app.failures.factory import build_failure_explainer
from app.services import failures as failures_service
from app.services.catalog import Catalog
from app.services.generation import stored_spec
from app.services.jenkins import ConsoleChunk, FakeJenkinsClient, JenkinsError, StageInfo
from app.services.tracker import RunTracker
from app.ws.hub import Hub
from tests.test_chains import BTD, approved
from tests.test_routers import auth, token_for

LOGS = Path(__file__).parent / "data" / "failure_logs"
AUTH_LOG = (LOGS / "auth-service-test-unit.log").read_text(encoding="utf-8")
BUILD, TEST, DEPLOY = (
    "fs-auth-service-build",
    "fs-auth-service-test-unit",
    "fs-auth-service-deploy-staging",
)


@pytest.fixture
def tracker(engine: AsyncEngine, fake_jenkins: FakeJenkinsClient) -> RunTracker:
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return RunTracker(session_factory=factory, jenkins=fake_jenkins, hub=Hub())


async def failed_chain(
    client: AsyncClient,
    db: AsyncSession,
    fake_jenkins: FakeJenkinsClient,
    tracker: RunTracker,
    *,
    log_text: str = AUTH_LOG,
) -> tuple[str, dict[str, Any]]:
    """auth-service's build, test and deploy, with the test job failed. Returns a token and card."""
    token = await token_for(client, db)
    result = await approved(client, token, text=BTD)
    assert result["jobs"] == [BUILD, TEST, DEPLOY]
    fake_jenkins.complete_queue_item(result["queue_item_id"], result="SUCCESS")
    await tracker.tick()
    await tracker.tick()
    fake_jenkins.start_downstream(TEST, upstream=BUILD, upstream_number=1)
    await tracker.tick()
    fake_jenkins.finish_build(TEST, 1, "FAILURE")
    fake_jenkins.jobs[TEST].logs[1] = log_text
    await tracker.tick()
    await tracker.tick()
    card = (await client.get(f"/api/chains/{result['chain_id']}", headers=auth(token))).json()
    assert card["status"] == "FAILURE", card
    return token, card


async def explain(client: AsyncClient, token: str, run_id: str) -> Response:
    return await client.post(f"/api/runs/{run_id}/explain", headers=auth(token))


def use_provider(
    app: FastAPI, settings: Settings, catalog: Catalog, provider: FakeProvider
) -> None:
    app.dependency_overrides[get_failure_explainer] = lambda: build_failure_explainer(
        settings, catalog=catalog, provider=provider, quota=QuotaTracker()
    )


# ---------------------------------------------------------------------------
# A failed test job
# ---------------------------------------------------------------------------


async def test_the_run_card_names_the_failed_run(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    _, card = await failed_chain(client, db, fake_jenkins, tracker)

    jobs = {job["name"]: job for job in card["jobs"]}
    assert card["failed_run_id"] == jobs[TEST]["run"]["id"]
    assert jobs[DEPLOY]["run"] is None


async def test_a_failed_test_job_is_explained_from_its_log(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    token, card = await failed_chain(client, db, fake_jenkins, tracker)

    response = await explain(client, token, card["failed_run_id"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["job_name"], body["build_number"], body["result"]) == (TEST, 1, "FAILURE")
    assert body["url"] == FakeJenkinsClient.build_url(TEST, 1)
    assert body["chain_id"] == card["id"]
    assert body["not_started"] == [DEPLOY], "the deploy never started, read from the database"

    facts = body["facts"]
    assert facts["category"] == "test_failure"
    assert facts["stage"], "the failed job's stage, from the artifact it was rendered from"
    assert facts["failed_tests"] == ["demo/failing-tests: this test fails on purpose"]
    assert (facts["tests_failed"], facts["tests_passed"]) == (1, 7)

    words = body["explanation"]
    assert words["source"] == "model" and words["provider"] == "fake"  # LLM_MODE=fake
    assert words["cause_found"]
    printed = AUTH_LOG.split("\n")
    for line in [*words["evidence"], *facts["evidence"]]:
        assert printed[line["line"] - 1].rstrip() == line["text"], "every quoted line is real"
    assert body["log"] == {
        "available": True,
        "complete": True,
        "lines": 74,
        "truncated": False,
        "redactions": 0,
        "unavailable_reason": None,
    }


async def test_every_model_call_is_recorded_with_its_prompt_version(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    token, card = await failed_chain(client, db, fake_jenkins, tracker)

    body = (await explain(client, token, card["failed_run_id"])).json()

    rows = (
        await db.scalars(select(LlmCall).where(LlmCall.prompt_version.like("failure_v1@%")))
    ).all()
    pipeline = await db.get(GeneratedPipeline, card["pipeline_id"])
    assert pipeline is not None
    assert len(rows) == 1
    assert rows[0].command_id == pipeline.command_id, "tied to the command the chain came from"
    assert rows[0].prompt_version == body["explanation"]["prompt_version"]


async def test_an_answer_the_log_does_not_support_is_replaced_by_the_code_s_own(
    app: FastAPI,
    client: AsyncClient,
    db: AsyncSession,
    fake_jenkins: FakeJenkinsClient,
    tracker: RunTracker,
    settings: Settings,
    catalog: Catalog,
) -> None:
    invented = {
        "cause_found": True,
        "summary": "The database was down.",
        "evidence": ["psycopg.OperationalError: connection to server refused"],
        "suggestions": [],
    }
    use_provider(app, settings, catalog, FakeProvider(script=[invented]))
    token, card = await failed_chain(client, db, fake_jenkins, tracker)

    words = (await explain(client, token, card["failed_run_id"])).json()["explanation"]

    assert words["source"] == "rules"
    assert "rejected: evidence_not_in_log" in words["fallback_reasons"]
    assert words["ai_fallback"]
    assert words["summary"].startswith("1 of 8 tests failed")
    assert "database" not in words["summary"].lower()


async def test_secrets_in_the_log_reach_neither_the_model_nor_the_response(
    app: FastAPI,
    client: AsyncClient,
    db: AsyncSession,
    fake_jenkins: FakeJenkinsClient,
    tracker: RunTracker,
    settings: Settings,
    catalog: Catalog,
) -> None:
    groq_key = "gsk_" + "k" * 40
    leaky = AUTH_LOG.replace(
        "+ ./scripts/test.sh unit",
        "+ ./scripts/test.sh unit\n"
        f"+ export GROQ_API_KEY={groq_key}\n"
        f"+ curl -u orchestrator-bot:{settings.jenkins_token} http://jenkins-dev:8080/api\n"
        "+ git clone https://bot:hunter2hunter2@github.com/org/repo.git",
    )
    provider = FakeProvider(responder=fake_failure_responder)
    use_provider(app, settings, catalog, provider)
    token, card = await failed_chain(client, db, fake_jenkins, tracker, log_text=leaky)

    response = await explain(client, token, card["failed_run_id"])

    assert response.status_code == 200
    sent = "\n".join(message.content for call in provider.calls for message in call.messages)
    assert provider.calls, "the model was asked"
    for secret in (groq_key, settings.jenkins_token, "hunter2hunter2"):
        assert secret not in sent, "never sent to the provider"
        assert secret not in response.text, "never sent back"
    assert response.json()["log"]["redactions"] >= 3


# ---------------------------------------------------------------------------
# What cannot be explained, and what goes wrong
# ---------------------------------------------------------------------------


async def test_only_a_failed_run_can_be_explained(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    token, card = await failed_chain(client, db, fake_jenkins, tracker)
    passed = next(job for job in card["jobs"] if job["name"] == BUILD)["run"]["id"]

    response = await explain(client, token, passed)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "RUN_NOT_FAILED"
    assert "succeeded" in error["message"]


async def test_an_unknown_run_is_not_found(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db)

    response = await explain(client, token, "no-such-run")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"


async def test_explaining_needs_a_signed_in_user(client: AsyncClient) -> None:
    response = await client.post("/api/runs/anything/explain")

    assert response.status_code == 401


async def test_a_log_jenkins_no_longer_has_is_said_plainly(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    token, card = await failed_chain(client, db, fake_jenkins, tracker)
    del fake_jenkins.jobs[TEST]  # rotated away, or the job deleted

    response = await explain(client, token, card["failed_run_id"])

    assert response.status_code == 200
    body = response.json()
    assert body["log"]["available"] is False
    assert body["log"]["unavailable_reason"] == "Jenkins no longer has this build"
    assert body["explanation"]["source"] == "rules"
    assert not body["explanation"]["cause_found"]
    assert "cannot be read" in body["explanation"]["summary"]
    assert body["not_started"] == [DEPLOY], "what the failure stopped is still known"
    calls = (
        await db.scalars(select(LlmCall).where(LlmCall.prompt_version.like("failure_v1@%")))
    ).all()
    assert calls == [], "nothing to ground an answer in, so no model is asked"


async def test_an_unreachable_jenkins_is_an_error_worth_retrying(
    client: AsyncClient,
    db: AsyncSession,
    fake_jenkins: FakeJenkinsClient,
    tracker: RunTracker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token, card = await failed_chain(client, db, fake_jenkins, tracker)

    async def down(*_: object, **__: object) -> ConsoleChunk:
        raise JenkinsError("connection refused")

    monkeypatch.setattr(fake_jenkins, "console_window", down)

    response = await explain(client, token, card["failed_run_id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "JENKINS_UNAVAILABLE"
    assert "Try again" in error["message"]


async def test_a_log_still_being_written_is_explained_and_marked_incomplete(
    client: AsyncClient,
    db: AsyncSession,
    fake_jenkins: FakeJenkinsClient,
    tracker: RunTracker,
    settings: Settings,
    catalog: Catalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, card = await failed_chain(client, db, fake_jenkins, tracker)
    reads: list[int] = []

    async def still_writing(*_: object, **__: object) -> ConsoleChunk:
        reads.append(1)
        return ConsoleChunk(text=AUTH_LOG, more_data=True)

    monkeypatch.setattr(fake_jenkins, "console_window", still_writing)
    explainer = build_failure_explainer(settings, catalog=catalog, quota=QuotaTracker())

    failure = await failures_service.explain_run(
        db, fake_jenkins, explainer, run_id=card["failed_run_id"], settle_seconds=0
    )

    assert len(reads) == failures_service.LOG_SETTLE_ATTEMPTS, "it waited for the log to close"
    assert failure.analysis.log_complete is False
    assert failure.analysis.category.value == "test_failure"


async def test_explaining_shares_the_assistants_rate_limit(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    """Each explanation can call the model, which has a quota of its own (4.5.1)."""
    token, card = await failed_chain(client, db, fake_jenkins, tracker)

    statuses = [
        (await explain(client, token, card["failed_run_id"])).status_code for _ in range(25)
    ]

    assert 200 in statuses
    assert statuses[-1] == 429


# ---------------------------------------------------------------------------
# A failed Pipeline stage
# ---------------------------------------------------------------------------


def pipeline_log(name: str, stages: list[str]) -> str:
    build, tests, deploy = stages
    return (
        "Started by user Orchestrator Backend\n[Pipeline] Start of Pipeline\n[Pipeline] node\n"
        f"Running on agent-1 in /home/jenkins/agent/workspace/{name}\n[Pipeline] {{\n"
        f"[Pipeline] stage\n[Pipeline] {{ ({build})\n[Pipeline] sh\n+ ./scripts/build.sh\n"
        "[build] auth-service\n[build] ok\n[Pipeline] }\n[Pipeline] // stage\n"
        f"[Pipeline] stage\n[Pipeline] {{ ({tests})\n[Pipeline] sh\n+ ./scripts/test.sh unit\n"
        "✖ demo/failing-tests: this test fails on purpose (1.4ms)\n"
        "  AssertionError [ERR_ASSERTION]: intentional failure\n"
        "\N{INFORMATION SOURCE} pass 7\n\N{INFORMATION SOURCE} fail 1\n"
        "[Pipeline] }\n[Pipeline] // stage\n"
        f"[Pipeline] stage\n[Pipeline] {{ ({deploy})\n"
        f'Stage "{deploy}" skipped due to earlier failure(s)\n'
        "[Pipeline] }\n[Pipeline] // stage\n[Pipeline] }\n[Pipeline] // node\n"
        "[Pipeline] End of Pipeline\nERROR: script returned exit code 1\nFinished: FAILURE\n"
    )


async def test_a_failed_pipeline_stage_is_named_with_the_stages_it_stopped(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    token = await token_for(client, db)
    result = await approved(client, token, text=BTD, assistant="pipeline")
    name = result["first_job"]
    running = (await client.get(f"/api/chains/{result['chain_id']}", headers=auth(token))).json()
    pipeline = await db.get(GeneratedPipeline, running["pipeline_id"])
    assert pipeline is not None
    spec = stored_spec(pipeline)
    assert spec is not None
    stages = [stage.name for stage in spec.stages]
    assert len(stages) == 3

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
        StageInfo(stages[0], "SUCCESS", 900),
        StageInfo(stages[1], "FAILED", 4000),
        StageInfo(stages[2], "NOT_EXECUTED", 0),
    )
    fake_jenkins.jobs[name].logs[build.number] = pipeline_log(name, stages)
    await tracker.tick()
    fake_jenkins.finish_build(name, build.number, "FAILURE")
    await tracker.tick()
    await tracker.tick()
    card = (await client.get(f"/api/chains/{result['chain_id']}", headers=auth(token))).json()
    assert card["status"] == "FAILURE"

    body = (await explain(client, token, card["failed_run_id"])).json()

    assert body["job_type"] == "PIPELINE"
    assert body["facts"]["stage"] == stages[1]
    assert body["facts"]["skipped_stages"] == [stages[2]]
    assert body["facts"]["category"] == "test_failure"
    assert body["facts"]["exit_code"] == 1
    assert body["not_started"] == [], "a Pipeline is one job; what it skipped are stages"
