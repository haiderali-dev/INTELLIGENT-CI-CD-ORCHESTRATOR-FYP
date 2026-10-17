"""D-058: the typed payloads describe exactly what the producers write.

Real flows run through the API against the fake Jenkins: every kind of reply, a generated and an
approved pipeline, a failed test re-run, a status with a live run card, cancelling. Then everything
they stored is read back from the database and checked. Each item must validate into the model its
kind names, and dump back unchanged. A producer that adds, drops or renames a field fails here
before any client sees it, and so does a kind the union does not know.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.payloads import (
    ApprovedRunReply,
    CancelReply,
    HelpReply,
    IntentRecord,
    IntentReply,
    MessagePayload,
    NothingToRerunReply,
    ParsedHelpReply,
    PipelineReply,
    ProgressStep,
    QuestionReply,
    RefusalReply,
    RerunStartedReply,
    RunCard,
    StatusReply,
    ValidationReportRecord,
)
from app.db.models import GeneratedPipeline, Message, NlCommand
from app.services.jenkins import FakeJenkinsClient
from app.services.tracker import RunTracker
from app.ws.hub import Hub
from tests.test_assistants_api import new_chat, say
from tests.test_chains import BTD, approved
from tests.test_routers import auth, token_for

PAYLOAD: TypeAdapter[MessagePayload] = TypeAdapter(MessagePayload)


@pytest.fixture
def tracker(engine: AsyncEngine, fake_jenkins: FakeJenkinsClient) -> RunTracker:
    """The run tracker on the test database, driven one tick at a time."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    return RunTracker(session_factory=factory, jenkins=fake_jenkins, hub=Hub())


EVERY_KIND = {
    IntentReply,
    QuestionReply,
    RefusalReply,
    ParsedHelpReply,
    HelpReply,
    StatusReply,
    NothingToRerunReply,
    RerunStartedReply,
    ApprovedRunReply,
    CancelReply,
    PipelineReply,
}


def unchanged(model: BaseModel, stored: dict[str, Any]) -> None:
    """Nothing the producer wrote was dropped, renamed or altered on the way through."""
    assert model.model_dump(mode="json", exclude_unset=True) == stored, type(model).__name__


async def stored(db: AsyncSession, model: type[Any]) -> list[Any]:
    db.expire_all()
    return list((await db.scalars(select(model))).all())


async def run_every_flow(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> str:
    """Produces every kind of payload there is. Returns the approved chain's id."""
    token = await token_for(client, db)
    chat = await new_chat(client, token)

    await say(client, token, chat, "/help")
    await say(client, token, chat, "Deploy payment-service to production")
    await say(client, token, chat, "Rerun the failed payment-service tests")
    await say(client, token, chat, "What's the status of my last deploy?")
    await say(client, token, chat, "Cancel the payment-service chain")
    # Two answers that never name a service spend the clarification rounds; the third reply is
    # the parser's own help card.
    lost = await new_chat(client, token)
    await say(client, token, lost, "run the tests")
    await say(client, token, lost, "the one that matters")
    await say(client, token, lost, "you know which")

    # Generated, approved, and running: intent, pipeline and run replies.
    result = await approved(client, token, text=BTD)
    await say(client, token, chat, "What's the status of my last deploy?")

    # The test job fails, then is re-run; then that re-run's chain is cancelled.
    build, test, _ = result["jobs"]
    fake_jenkins.complete_queue_item(result["queue_item_id"], result="SUCCESS")
    await tracker.tick()
    await tracker.tick()
    fake_jenkins.start_downstream(test, upstream=build, upstream_number=1)
    await tracker.tick()
    fake_jenkins.finish_build(test, 1, "FAILURE")
    await tracker.tick()
    await tracker.tick()
    await say(client, token, chat, "Rerun the failed auth-service tests")
    await say(client, token, chat, "Cancel the auth-service chain")
    chain_id: str = result["chain_id"]
    return chain_id


async def test_every_message_payload_round_trips_and_every_kind_appears(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    await run_every_flow(client, db, fake_jenkins, tracker)

    seen: set[type[Any]] = set()
    for message in await stored(db, Message):
        if message.payload is None:
            continue
        model = PAYLOAD.validate_python(message.payload)
        unchanged(model, message.payload)
        seen.add(type(model))

    assert seen == EVERY_KIND, f"never produced: {sorted(k.__name__ for k in EVERY_KIND - seen)}"


async def test_every_intent_record_round_trips(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    await run_every_flow(client, db, fake_jenkins, tracker)

    commands = await stored(db, NlCommand)
    assert len(commands) >= 10
    dispositions = set()
    for command in commands:
        record = IntentRecord.model_validate(command.parsed_intent)
        unchanged(record, command.parsed_intent)
        dispositions.add(record.disposition.value)

    assert dispositions >= {"READY", "NEEDS_CLARIFICATION", "REFUSED", "HELP"}


async def test_every_progress_line_and_checklist_round_trips(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    await run_every_flow(client, db, fake_jenkins, tracker)

    pipelines = await stored(db, GeneratedPipeline)
    assert pipelines
    for pipeline in pipelines:
        results = pipeline.validation_results or {}
        steps = [ProgressStep.model_validate(step) for step in results["progress"]]
        for model, raw in zip(steps, results["progress"], strict=True):
            unchanged(model, raw)
        assert [step.step for step in steps] == ["Understood", "Planned", "Rendered", "Validated"]
        report = ValidationReportRecord.model_validate(results["report"])
        unchanged(report, results["report"])
        assert report.ok and report.checks


async def test_the_run_card_endpoint_serves_the_typed_card(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient, tracker: RunTracker
) -> None:
    chain_id = await run_every_flow(client, db, fake_jenkins, tracker)
    token = await token_for(client, db, email="reader@example.com")

    response = await client.get(f"/api/chains/{chain_id}", headers=auth(token))

    assert response.status_code == 200, response.text
    card = RunCard.model_validate(response.json())
    assert card.id == chain_id
    assert [job.state for job in card.jobs][:2] == ["success", "failure"]


def test_a_run_card_stored_before_d057_still_reads() -> None:
    """A status message keeps the card as it was. One stored before the ranking fix has no
    base_score, own_score or weights; it reads as not inherited and with no weights, so the bar
    says its parts cannot be shown instead of drawing wrong ones."""
    old_queue = {
        "job": "fs-auth-service-build",
        "rank": 1,
        "score": 0.6,
        "level": "MEDIUM",
        "components": {
            "urgency": 0.0,
            "dependency": 0.0,
            "execution_time": 0.0,
            "aging_bonus": 0.0,
        },
        "waiting_reason": None,
        "wait_seconds": 3.0,
    }
    card = RunCard.model_validate(
        {
            "id": "c1",
            "pipeline_id": None,
            "service": "auth-service",
            "job_type": "FREESTYLE",
            "status": "RUNNING",
            "position": 0,
            "parameters": {},
            "started_at": None,
            "finished_at": None,
            "lock_expires_at": None,
            "duration_ms": None,
            "jobs": [],
            "stages": [],
            "queue": old_queue,
            "failed_run_id": None,
        }
    )

    assert card.queue is not None
    assert card.queue.weights == {}
    assert card.queue.components.own_score == 0.6
    assert card.queue.components.base_score == 0.6
