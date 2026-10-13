"""T5.6: generate, regenerate, explain and approve, through the API.

Against the fake Jenkins and the fake-mode model, so the flow is tested without a controller. The
live path -- real jobs, real builds -- is the end-to-end suite's (T5.8).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, GeneratedPipeline, Job, LlmCall, Message, PipelineStatus, Role
from app.services.jenkins import FakeJenkinsClient, JenkinsError
from tests.test_assistants_api import new_chat, say
from tests.test_routers import auth, token_for

KEY = {"Idempotency-Key": "approve-0001"}


async def ready(
    client: AsyncClient,
    token: str,
    text: str = "Build payment-service from main",
    assistant: str = "freestyle",
) -> str:
    chat = await new_chat(client, token, assistant)
    body = await say(client, token, chat, text)
    assert body["command"]["disposition"] == "READY", body["assistant_message"]["content"]
    command_id: str = body["command"]["id"]
    return command_id


async def generated(client: AsyncClient, token: str, **kwargs: Any) -> dict[str, Any]:
    command = await ready(client, token, **kwargs)
    response = await client.post(f"/api/commands/{command}/generate", headers=auth(token))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


async def test_a_freestyle_request_generates_a_validated_chain(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db)

    body = await generated(client, token, text="build, test and deploy payment-service to staging")

    assert body["status"] == "VALIDATED"
    assert body["job_type"] == "FREESTYLE"
    assert [job["name"] for job in body["jobs"]] == [
        "fs-payment-service-build",
        "fs-payment-service-test-unit",
        "fs-payment-service-test-integration",
        "fs-payment-service-deploy-staging",
    ]
    assert [step["step"] for step in body["progress"]] == [
        "Understood",
        "Planned",
        "Rendered",
        "Validated",
    ]
    assert all(step["ok"] for step in body["progress"])
    assert body["validation"]["ok"] is True
    assert body["summary"] == (
        "Creates 4 jobs and starts fs-payment-service-build on main at MEDIUM priority"
    )
    assert body["plan"]["source"] == "model"
    assert "spec_yaml" in body and "assistant: freestyle" in body["spec_yaml"]

    calls = (
        await db.scalars(select(LlmCall).where(LlmCall.prompt_version.like("planner_v1@%")))
    ).all()
    assert calls, "the planner's calls are recorded in llm_calls too"
    messages = (await db.scalars(select(Message).where(Message.role == "ASSISTANT"))).all()
    assert any((m.payload or {}).get("kind") == "pipeline" for m in messages)


async def test_a_pipeline_request_generates_a_linted_jenkinsfile(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient
) -> None:
    token = await token_for(client, db)

    body = await generated(
        client, token, text="build, test and deploy auth-service to staging", assistant="pipeline"
    )

    assert body["status"] == "VALIDATED"
    assert body["job_type"] == "PIPELINE"
    assert [job["name"] for job in body["jobs"]] == ["pl-auth-service-build-test-deploy-staging"]
    assert "pipeline {" in body["jenkinsfile"]
    assert [call for call in fake_jenkins.calls if call[0] == "lint_jenkinsfile"]


async def test_a_request_still_waiting_on_a_question_cannot_generate(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db)
    chat = await new_chat(client, token)
    command = (await say(client, token, chat, "run the tests"))["command"]["id"]

    response = await client.post(f"/api/commands/{command}/generate", headers=auth(token))

    assert response.status_code == 409
    assert "not ready" in response.json()["error"]["message"]


async def test_a_status_request_generates_nothing(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db)
    command = await ready(client, token, "/status payment-service")

    response = await client.post(f"/api/commands/{command}/generate", headers=auth(token))

    assert response.status_code == 409


async def test_a_linter_rejection_is_shown_as_a_failed_step(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient
) -> None:
    fake_jenkins.lint_ok = False
    fake_jenkins.lint_message = "WorkflowScript: 1: Expected a stage"
    token = await token_for(client, db)

    body = await generated(
        client, token, text="deploy auth-service to staging", assistant="pipeline"
    )

    assert body["status"] == "INVALID"
    assert body["progress"][-1] == {
        "step": "Validated",
        "ok": False,
        "detail": "Declarative linter: The declarative linter rejected the Jenkinsfile: WorkflowScript: 1: Expected a stage",
    }
    assert body["summary"] is None


async def test_pipelines_are_private(client: AsyncClient, db: AsyncSession) -> None:
    owner = await token_for(client, db)
    other = await token_for(client, db, role=Role.ADMIN)
    pipeline = (await generated(client, owner))["id"]

    response = await client.get(f"/api/pipelines/{pipeline}", headers=auth(other))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PIPELINE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Regenerate
# ---------------------------------------------------------------------------


async def test_regenerating_supersedes_the_plan_before(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db)
    first = await generated(client, token)

    second = (
        await client.post(f"/api/pipelines/{first['id']}/regenerate", headers=auth(token))
    ).json()

    assert second["id"] != first["id"]
    assert second["status"] == "VALIDATED"
    old = await db.get(GeneratedPipeline, first["id"])
    await db.refresh(old)
    assert old is not None and old.status == PipelineStatus.CANCELLED.value


async def regenerate_with(
    client: AsyncClient, token: str, pipeline: dict[str, Any], yaml: str
) -> dict[str, Any]:
    response = await client.post(
        f"/api/pipelines/{pipeline['id']}/regenerate", headers=auth(token), json={"spec_yaml": yaml}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_an_edited_spec_is_validated_and_rendered(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db)
    first = await generated(client, token)
    yaml = "\n".join(
        line for line in first["spec_yaml"].splitlines() if not line.startswith("commit:")
    ).replace("branch: main", "branch: demo/failing-tests")

    body = await regenerate_with(client, token, first, yaml + "\n")

    assert body["status"] == "VALIDATED", body["validation"]
    assert body["plan"] is None
    assert body["parameters"] == {
        "BRANCH": "demo/failing-tests",
        "COMMIT": "refs/heads/demo/failing-tests",
    }


@pytest.mark.parametrize(
    ("change", "check"),
    [
        (("priority: MEDIUM", "priority: HIGH"), "policy_fields"),
        (("service: payment-service", "service: auth-service"), "policy_fields"),
        (("assistant: freestyle", "assistant: pipeline"), "policy_fields"),
        (("branch: main", "branch: [main"), "spec_schema"),
        (("template: build", "template: build\n    command: id"), "spec_schema"),
    ],
)
async def test_an_edit_outside_what_the_yaml_may_change_is_invalid(
    client: AsyncClient, db: AsyncSession, change: tuple[str, str], check: str
) -> None:
    """Policy-decided fields are locked; the schema still applies to a hand edit."""
    token = await token_for(client, db)
    first = await generated(client, token)
    assert change[0] in first["spec_yaml"]

    body = await regenerate_with(client, token, first, first["spec_yaml"].replace(*change))

    assert body["status"] == "INVALID"
    failed = [item for item in body["validation"]["checks"] if item["status"] == "failed"]
    assert failed[0]["name"] == check


async def test_an_edit_adding_a_production_deploy_is_invalid(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db)
    first = await generated(client, token)
    yaml = (
        first["spec_yaml"] + "  - name: Ship\n    template: deploy\n    environment: production\n"
    )

    body = await regenerate_with(client, token, first, yaml)

    assert body["status"] == "INVALID"
    environment = next(
        item for item in body["validation"]["checks"] if item["name"] == "environment"
    )
    assert environment["status"] == "failed"


# ---------------------------------------------------------------------------
# Explain
# ---------------------------------------------------------------------------


async def test_the_explanation_streams_in_plain_english(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db)
    pipeline = await generated(
        client, token, text="build, test and deploy payment-service to staging"
    )

    response = await client.post(f"/api/pipelines/{pipeline['id']}/explain", headers=auth(token))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    assert "fs-payment-service-build" in text
    assert "fs-payment-service-deploy-staging" in text
    assert "A failed job stops the chain" in text


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


async def test_approval_needs_an_idempotency_key(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db)
    pipeline = await generated(client, token)

    response = await client.post(f"/api/pipelines/{pipeline['id']}/approve", headers=auth(token))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BAD_REQUEST"


async def test_approval_creates_the_chain_last_first_and_starts_the_first_job(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient
) -> None:
    token = await token_for(client, db)
    pipeline = await generated(
        client, token, text="build, test and deploy payment-service to staging"
    )

    response = await client.post(
        f"/api/pipelines/{pipeline['id']}/approve", headers={**auth(token), **KEY}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "APPROVED"
    assert body["replayed"] is False
    assert body["result"]["first_job"] == "fs-payment-service-build"
    created = [target for action, target in fake_jenkins.calls if action == "create_job"]
    assert created == list(reversed(body["result"]["jobs"])), "last first, so each trigger resolves"
    triggered = [target for action, target in fake_jenkins.calls if action == "trigger"]
    assert triggered == ["fs-payment-service-build"]

    jobs = {job.jenkins_name: job for job in (await db.scalars(select(Job))).all()}
    assert jobs["fs-payment-service-test-unit"].depends_on == "fs-payment-service-build"
    assert jobs["fs-payment-service-deploy-staging"].chain_position == 3
    actions = [row.action for row in (await db.scalars(select(AuditLog))).all()]
    assert "pipeline.approved" in actions
    assert actions.count("job.saved") == 4


async def test_the_same_key_twice_starts_nothing_new(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient
) -> None:
    """4.6.4: a double click cannot create two chains."""
    token = await token_for(client, db)
    pipeline = await generated(client, token)
    path = f"/api/pipelines/{pipeline['id']}/approve"

    first = (await client.post(path, headers={**auth(token), **KEY})).json()
    second = (await client.post(path, headers={**auth(token), **KEY})).json()

    assert second["replayed"] is True
    assert second["result"] == first["result"]
    assert [a for a, _ in fake_jenkins.calls].count("trigger") == 1


async def test_a_second_approval_with_another_key_is_refused(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db)
    pipeline = await generated(client, token)
    path = f"/api/pipelines/{pipeline['id']}/approve"
    await client.post(path, headers={**auth(token), **KEY})

    response = await client.post(path, headers={**auth(token), "Idempotency-Key": "approve-0002"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ALREADY_APPROVED"


async def test_an_invalid_plan_cannot_be_approved(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient
) -> None:
    fake_jenkins.lint_ok = False
    token = await token_for(client, db)
    pipeline = await generated(
        client, token, text="deploy auth-service to staging", assistant="pipeline"
    )

    response = await client.post(
        f"/api/pipelines/{pipeline['id']}/approve", headers={**auth(token), **KEY}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VALIDATION_REJECTED"


async def test_a_jenkins_failure_undoes_the_approval(
    client: AsyncClient,
    db: AsyncSession,
    fake_jenkins: FakeJenkinsClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await token_for(client, db)
    pipeline = await generated(client, token)
    path = f"/api/pipelines/{pipeline['id']}/approve"

    async def refuse(name: str, params: dict[str, str] | None = None) -> int:
        raise JenkinsError("503 from Jenkins")

    monkeypatch.setattr(fake_jenkins, "trigger", refuse)
    failed = await client.post(path, headers={**auth(token), **KEY})
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "JENKINS_UNAVAILABLE"
    assert (await client.get(f"/api/pipelines/{pipeline['id']}", headers=auth(token))).json()[
        "status"
    ] == "VALIDATED"

    monkeypatch.undo()
    retried = await client.post(path, headers={**auth(token), **KEY})
    assert retried.status_code == 200
    assert retried.json()["replayed"] is False


async def test_an_approved_plan_cannot_be_regenerated(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db)
    pipeline = await generated(client, token)
    await client.post(f"/api/pipelines/{pipeline['id']}/approve", headers={**auth(token), **KEY})

    response = await client.post(f"/api/pipelines/{pipeline['id']}/regenerate", headers=auth(token))

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ALREADY_APPROVED"
