"""Jobs and runs.

BUILD_PROMPT 4.4.4: ``GET /api/jobs``, ``GET /api/runs``, ``GET /api/runs/{id}``,
``POST /api/runs/{id}/cancel`` and ``GET /api/runs/{id}/log``; and T5.9's
``POST /api/runs/{id}/explain``.

Reads are open to any signed-in user; cancelling needs DevOps. 4.5.5 does not name a role for
cancelling a run, but it does say a Developer may not cancel a running chain and that an Admin may,
so stopping someone else's build is not a Developer action. The guard is the narrowest reading of
that table rather than an invention. Explaining a failure is a read of the same log, so it is open
to the same users.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ApiRateLimit,
    AssistantRateLimit,
    CurrentUser,
    DevOpsUser,
    get_failure_explainer,
)
from app.core.settings import Settings
from app.db.models import Job, JobRun
from app.db.session import get_db
from app.failures.analysis import EvidenceLine
from app.failures.explainer import FailureExplainer
from app.services import failures as failures_service
from app.services import runs as runs_service
from app.services.dependencies import get_jenkins_client, get_settings_dep
from app.services.jenkins import JenkinsClient

# Every route here carries the general per-user limit (security review, findings 5 and 10).
router = APIRouter(tags=["jobs"], dependencies=[ApiRateLimit])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class JobResponse(BaseModel):
    id: str
    jenkins_name: str
    job_type: str
    service_id: str | None
    # The service's catalog name, which the catalog and the chains use; ``service_id`` is a
    # database id no other endpoint returns (found in T6.7).
    service: str | None
    priority_level: str
    depends_on: list[str]
    chain_position: int
    created_at: datetime

    @classmethod
    def of(cls, job: Job, service: str | None = None) -> JobResponse:
        return cls(
            id=job.id,
            jenkins_name=job.jenkins_name,
            job_type=job.job_type,
            service_id=job.service_id,
            service=service,
            priority_level=job.priority_level,
            # Stored comma-separated to match the plugin property (D-011); split here so the API
            # is a list and the frontend never parses a string.
            depends_on=[name for name in job.depends_on.split(",") if name],
            chain_position=job.chain_position,
            created_at=job.created_at,
        )


class RunResponse(BaseModel):
    id: str
    job_id: str
    job_name: str | None
    build_number: int
    result: str
    queue_entered_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    queue_wait_ms: int | None
    queue_item_id: int | None

    @classmethod
    def of(cls, run: JobRun, job_name: str | None = None) -> RunResponse:
        return cls(
            id=run.id,
            job_id=run.job_id,
            job_name=job_name,
            build_number=run.build_number,
            result=run.result,
            queue_entered_at=run.queue_entered_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            duration_ms=run.duration_ms,
            queue_wait_ms=run.queue_wait_ms,
            queue_item_id=run.queue_item_id,
        )


class JobPage(BaseModel):
    items: list[JobResponse]
    total: int
    limit: int
    offset: int


class RunPage(BaseModel):
    items: list[RunResponse]
    total: int
    limit: int
    offset: int


class CancelResponse(BaseModel):
    run_id: str
    result: str
    action: str = Field(description="dequeued if it had not started, stopped if it was building")


class LogResponse(BaseModel):
    run_id: str
    text: str
    next_offset: int
    more_data: bool


class EvidenceLineResponse(BaseModel):
    line: int = Field(description="1-based line number in the build's whole log")
    text: str = Field(description="The line as printed, with secrets masked")

    @classmethod
    def of(cls, evidence: EvidenceLine) -> EvidenceLineResponse:
        return cls(line=evidence.number, text=evidence.text)


class FailureFacts(BaseModel):
    """What code found in the log. The explanation may word it; it never decides it."""

    category: str
    stage: str | None
    failed_tests: list[str]
    tests_failed: int | None
    tests_passed: int | None
    exit_code: int | None
    skipped_stages: list[str]
    evidence: list[EvidenceLineResponse]


class FailureWords(BaseModel):
    summary: str
    cause_found: bool
    evidence: list[EvidenceLineResponse] = Field(
        description="Lines that support the summary, each one checked to be in the log"
    )
    suggestions: list[str]
    source: str = Field(description="model, or rules when code wrote the explanation")
    provider: str
    model: str | None
    ai_fallback: bool
    fallback_reasons: list[str]
    prompt_version: str


class FailureLog(BaseModel):
    available: bool
    complete: bool = Field(description="False if Jenkins was still writing the log")
    lines: int
    truncated: bool = Field(description="True if only the end of a very long log was read")
    redactions: int = Field(description="How many values were masked as secrets")
    unavailable_reason: str | None


class RunFailureResponse(BaseModel):
    run_id: str
    job_name: str
    job_type: str
    build_number: int
    result: str
    url: str | None
    chain_id: str | None
    not_started: list[str] = Field(description="Chain jobs that never ran because of this failure")
    facts: FailureFacts
    explanation: FailureWords
    log: FailureLog

    @classmethod
    def of(cls, failure: failures_service.RunFailure) -> RunFailureResponse:
        analysis, words = failure.analysis, failure.explanation
        return cls(
            run_id=failure.run.id,
            job_name=failure.job.jenkins_name,
            job_type=failure.job.job_type,
            build_number=failure.run.build_number,
            result=failure.run.result,
            url=failure.url,
            chain_id=failure.chain.id if failure.chain is not None else None,
            not_started=list(failure.not_started),
            facts=FailureFacts(
                category=analysis.category.value,
                stage=analysis.stage,
                failed_tests=list(analysis.failed_tests),
                tests_failed=analysis.tests_failed,
                tests_passed=analysis.tests_passed,
                exit_code=analysis.exit_code,
                skipped_stages=list(analysis.skipped_stages),
                evidence=[EvidenceLineResponse.of(line) for line in analysis.evidence],
            ),
            explanation=FailureWords(
                summary=words.summary,
                cause_found=words.cause_found,
                evidence=[EvidenceLineResponse.of(line) for line in words.evidence],
                suggestions=list(words.suggestions),
                source=words.source.value,
                provider=words.provider,
                model=words.model,
                ai_fallback=words.ai_fallback,
                fallback_reasons=list(words.fallback_reasons),
                prompt_version=words.prompt_version,
            ),
            log=FailureLog(
                available=analysis.log_available,
                complete=analysis.log_complete,
                lines=analysis.lines,
                truncated=analysis.truncated,
                redactions=analysis.redactions,
                unavailable_reason=analysis.unavailable_reason,
            ),
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/jobs", response_model=JobPage, summary="Jobs the orchestrator created")
async def list_jobs(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
    service: Annotated[str | None, Query(max_length=128)] = None,
    job_type: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int | None, Query(ge=1, le=runs_service.MAX_PAGE_SIZE)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
) -> JobPage:
    page = await runs_service.list_jobs(
        session, service=service, job_type=job_type, limit=limit, offset=offset
    )
    names = await runs_service.service_names(session, page.items)
    return JobPage(
        items=[JobResponse.of(job, names.get(job.service_id or "")) for job in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/runs", response_model=RunPage, summary="Runs, newest first")
async def list_runs(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
    job_id: Annotated[str | None, Query(max_length=64)] = None,
    result: Annotated[str | None, Query(max_length=16)] = None,
    active: Annotated[bool, Query(description="Only runs that have not finished")] = False,
    limit: Annotated[int | None, Query(ge=1, le=runs_service.MAX_PAGE_SIZE)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
) -> RunPage:
    page = await runs_service.list_runs(
        session,
        job_id=job_id,
        result=result,
        active_only=active,
        limit=limit,
        offset=offset,
    )
    names = await runs_service.job_names_for(session, page.items)
    return RunPage(
        items=[RunResponse.of(run, names.get(run.job_id)) for run in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/runs/{run_id}", response_model=RunResponse, summary="One run")
async def get_run(
    run_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
) -> RunResponse:
    run = await runs_service.get_run(session, run_id)
    job = await runs_service.get_job(session, run.job_id)
    return RunResponse.of(run, job.jenkins_name)


@router.post("/runs/{run_id}/cancel", response_model=CancelResponse, summary="Cancel or stop a run")
async def cancel_run(
    run_id: str,
    user: DevOpsUser,
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
    jenkins: Annotated[JenkinsClient, Depends(get_jenkins_client)],
) -> CancelResponse:
    """Cancel a queued run, or stop a building one.

    Which of the two it is comes from the run's own state, not from the caller: Jenkins exposes
    them as different operations and guessing wrong gives a 404.
    """
    run = await runs_service.get_run(session, run_id)
    action = await runs_service.cancel_run(session, jenkins, run=run, actor=user)
    return CancelResponse(run_id=run.id, result=run.result, action=action)


@router.get("/runs/{run_id}/log", response_model=LogResponse, summary="Console output")
async def get_run_log(
    run_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
    jenkins: Annotated[JenkinsClient, Depends(get_jenkins_client)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    start: Annotated[int, Query(ge=0, description="Byte offset to read from")] = 0,
) -> LogResponse:
    """A window of the log, with the offset to ask for next, redacted.

    Windowed rather than whole: the UI tails a running build, and returning the entire log on each
    poll would move the same megabyte over and over.
    """
    run = await runs_service.get_run(session, run_id)
    window = await runs_service.run_log(
        session,
        jenkins,
        run=run,
        start=start,
        secrets=failures_service.known_secrets(settings),
    )
    return LogResponse(
        run_id=run.id,
        text=window.text,
        next_offset=window.next_offset,
        more_data=window.more_data,
    )


@router.post(
    "/runs/{run_id}/explain",
    response_model=RunFailureResponse,
    summary="Explain why a run failed",
    dependencies=[AssistantRateLimit],
)
async def explain_run_failure(
    run_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
    jenkins: Annotated[JenkinsClient, Depends(get_jenkins_client)],
    explainer: Annotated[FailureExplainer, Depends(get_failure_explainer)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> RunFailureResponse:
    """T5.9: why a failed run failed, in plain words, with the log lines that show it.

    Rate limited with the assistants: it calls the same model and spends the same quota (4.5.1).
    """
    failure = await failures_service.explain_run(
        session,
        jenkins,
        explainer,
        run_id=run_id,
        secrets=failures_service.known_secrets(settings),
    )
    return RunFailureResponse.of(failure)
