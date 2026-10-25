"""Generation: BUILD_PROMPT 4.4.4's ``POST /api/commands/{id}/generate``,
``GET /api/pipelines/{id}`` and ``POST /api/pipelines/{id}/approve``, ``/regenerate``, ``/explain``.

``approve`` takes the ``Idempotency-Key`` header (4.6.4: "Approval takes an idempotency key so a
double click cannot create two chains"). ``explain`` streams plain text.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompting import load_prompt
from app.ai.quota import get_quota_tracker
from app.api.deps import ApiRateLimit, AssistantRateLimit, CurrentUser, get_planner
from app.api.payloads import ProgressStep, ValidationReportRecord
from app.core.errors import ErrorCode, conflict
from app.core.settings import Settings
from app.db import session as db_session
from app.db.models import Conversation, GeneratedPipeline, LlmCall
from app.db.session import get_db
from app.generation.planner import Planner
from app.services import conversations as conversation_service
from app.services import generation as service
from app.services.catalog import Catalog
from app.services.dependencies import (
    get_catalog,
    get_git_client,
    get_jenkins_client,
    get_llm_provider,
    get_settings_dep,
)
from app.services.git import GitClient
from app.services.jenkins import JenkinsClient

router = APIRouter(tags=["generation"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class JobPreview(BaseModel):
    name: str
    position: int
    stage: dict[str, Any] | None
    commands: list[str]
    depends_on: str
    triggers: str | None
    config_xml: str


class PipelineResponse(BaseModel):
    id: str
    command_id: str
    conversation_id: str
    assistant: str
    job_type: str
    status: str
    spec_yaml: str
    jobs: list[JobPreview]
    jenkinsfile: str | None
    parameters: dict[str, str]
    progress: list[ProgressStep] = Field(
        description="4.7.4's progress line: the steps reached, a failed one last (D-058)"
    )
    validation: ValidationReportRecord | None = Field(
        description="The checklist (4.6.3), in order; null when nothing was rendered to check"
    )
    plan: dict[str, Any] | None = Field(description="How the plan was made, attempts and repairs")
    summary: str | None = Field(description="What approving will do, for the approval dialog")
    attempts: int
    approved_by: str | None
    approved_at: datetime | None
    approval: dict[str, Any] | None
    created_at: datetime

    @classmethod
    def of(cls, pipeline: GeneratedPipeline, conversation: Conversation) -> PipelineResponse:
        artifact = service.stored_artifact(pipeline)
        results = pipeline.validation_results or {}
        return cls(
            id=pipeline.id,
            command_id=pipeline.command_id,
            conversation_id=conversation.id,
            assistant=conversation.assistant.lower(),
            job_type=pipeline.job_type,
            status=pipeline.status,
            spec_yaml=pipeline.spec_yaml,
            jobs=[JobPreview(**job.to_record()) for job in (artifact.jobs if artifact else ())],
            jenkinsfile=artifact.jenkinsfile if artifact else None,
            parameters=artifact.parameters if artifact else {},
            progress=[ProgressStep.model_validate(step) for step in results.get("progress") or []],
            validation=(
                ValidationReportRecord.model_validate(results["report"])
                if results.get("report") is not None
                else None
            ),
            plan=results.get("plan"),
            summary=results.get("summary"),
            attempts=pipeline.attempts,
            approved_by=pipeline.approved_by,
            approved_at=pipeline.approved_at,
            approval=results.get("approval"),
            created_at=pipeline.created_at,
        )


class RegenerateRequest(BaseModel):
    spec_yaml: str | None = Field(
        default=None,
        max_length=20000,
        description="An edited spec to validate and render. Omit to plan again.",
    )


class ApprovalResponse(BaseModel):
    pipeline_id: str
    status: str
    replayed: bool = Field(description="True when this key was already used: nothing new started")
    result: dict[str, Any]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/commands/{command_id}/generate",
    response_model=PipelineResponse,
    status_code=201,
    dependencies=[AssistantRateLimit],
)
async def generate(
    command_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
    planner: Annotated[Planner, Depends(get_planner)],
    catalog: Annotated[Catalog, Depends(get_catalog)],
    git: Annotated[GitClient, Depends(get_git_client)],
    jenkins: Annotated[JenkinsClient, Depends(get_jenkins_client)],
) -> PipelineResponse:
    command, conversation = await conversation_service.get_command(
        session, user=user, command_id=command_id
    )
    pipeline = await service.generate(
        session,
        user=user,
        command=command,
        conversation=conversation,
        planner=planner,
        catalog=catalog,
        git=git,
        jenkins=jenkins,
    )
    return PipelineResponse.of(pipeline, conversation)


@router.get(
    "/pipelines/{pipeline_id}", response_model=PipelineResponse, dependencies=[ApiRateLimit]
)
async def get_pipeline(
    pipeline_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
) -> PipelineResponse:
    context = await service.get_pipeline(session, user=user, pipeline_id=pipeline_id)
    return PipelineResponse.of(context.pipeline, context.conversation)


@router.post(
    "/pipelines/{pipeline_id}/regenerate",
    response_model=PipelineResponse,
    status_code=201,
    dependencies=[AssistantRateLimit],
)
async def regenerate(
    pipeline_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
    planner: Annotated[Planner, Depends(get_planner)],
    catalog: Annotated[Catalog, Depends(get_catalog)],
    git: Annotated[GitClient, Depends(get_git_client)],
    jenkins: Annotated[JenkinsClient, Depends(get_jenkins_client)],
    body: RegenerateRequest | None = None,
) -> PipelineResponse:
    context = await service.get_pipeline(session, user=user, pipeline_id=pipeline_id)
    pipeline = await service.regenerate(
        session,
        user=user,
        context=context,
        planner=planner,
        catalog=catalog,
        git=git,
        jenkins=jenkins,
        spec_yaml=body.spec_yaml if body else None,
    )
    return PipelineResponse.of(pipeline, context.conversation)


@router.post("/pipelines/{pipeline_id}/explain", dependencies=[AssistantRateLimit])
async def explain(
    pipeline_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    catalog: Annotated[Catalog, Depends(get_catalog)],
) -> StreamingResponse:
    """A plain-English explanation of the plan, streamed as it is written (4.6.2 step 4)."""
    context = await service.get_pipeline(session, user=user, pipeline_id=pipeline_id)
    spec = service.stored_spec(context.pipeline)
    artifact = service.stored_artifact(context.pipeline)
    if spec is None or artifact is None:
        raise conflict(ErrorCode.VALIDATION_REJECTED, "This plan has nothing to explain yet.")
    provider, has_models = get_llm_provider(settings, catalog, "plan")
    # Fake mode explains in code: a fake model's sentence would be noise beside a real plan.
    models = settings.model_chain if has_models and provider.name != "fake" else []
    command_id = context.command.id
    version = load_prompt("explain_v1").version

    async def record(provider_name: str, model: str, latency_ms: int, outcome: str) -> None:
        # The request's session may already be closed while the response streams, so the call is
        # recorded with its own.
        async with db_session.get_session_factory()() as own:
            own.add(
                LlmCall(
                    command_id=command_id,
                    provider=provider_name,
                    model=model,
                    latency_ms=latency_ms,
                    prompt_version=version,
                    outcome=outcome,
                )
            )
            await own.commit()

    async def body() -> AsyncIterator[str]:
        async for chunk in service.explain_stream(
            spec,
            artifact,
            provider=provider,
            models=tuple(models),
            quota=get_quota_tracker(),
            record=record,
        ):
            yield chunk

    return StreamingResponse(body(), media_type="text/plain; charset=utf-8")


@router.post(
    "/pipelines/{pipeline_id}/approve",
    response_model=ApprovalResponse,
    dependencies=[AssistantRateLimit],
)
async def approve(
    pipeline_id: str,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
    catalog: Annotated[Catalog, Depends(get_catalog)],
    jenkins: Annotated[JenkinsClient, Depends(get_jenkins_client)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ApprovalResponse:
    context = await service.get_pipeline(session, user=user, pipeline_id=pipeline_id)
    approval = await service.approve(
        session,
        user=user,
        context=context,
        key=idempotency_key or "",
        catalog=catalog,
        jenkins=jenkins,
        tracker=getattr(request.app.state, "tracker", None),
    )
    return ApprovalResponse(
        pipeline_id=approval.pipeline.id,
        status=approval.pipeline.status,
        replayed=approval.replayed,
        result=approval.result,
    )
