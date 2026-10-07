"""Jobs and runs.

BUILD_PROMPT 4.4.4: ``GET /api/jobs``, ``GET /api/runs``, ``GET /api/runs/{id}``,
``POST /api/runs/{id}/cancel`` and ``GET /api/runs/{id}/log``.

Reads are open to any signed-in user; cancelling needs DevOps. 4.5.5 does not name a role for
cancelling a run, but it does say a Developer may not cancel a running chain and that an Admin may,
so stopping someone else's build is not a Developer action. The guard is the narrowest reading of
that table rather than an invention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DevOpsUser
from app.db.models import Job, JobRun
from app.db.session import get_db
from app.services import runs as runs_service
from app.services.dependencies import get_jenkins_client
from app.services.jenkins import JenkinsClient

router = APIRouter(tags=["jobs"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class JobResponse(BaseModel):
    id: str
    jenkins_name: str
    job_type: str
    service_id: str | None
    priority_level: str
    depends_on: list[str]
    chain_position: int
    created_at: datetime

    @classmethod
    def of(cls, job: Job) -> JobResponse:
        return cls(
            id=job.id,
            jenkins_name=job.jenkins_name,
            job_type=job.job_type,
            service_id=job.service_id,
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/jobs", response_model=JobPage, summary="Jobs the orchestrator created")
async def list_jobs(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[str | None, Query(max_length=128)] = None,
    job_type: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int | None, Query(ge=1, le=runs_service.MAX_PAGE_SIZE)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
) -> JobPage:
    page = await runs_service.list_jobs(
        session, service=service, job_type=job_type, limit=limit, offset=offset
    )
    return JobPage(
        items=[JobResponse.of(job) for job in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/runs", response_model=RunPage, summary="Runs, newest first")
async def list_runs(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
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
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RunResponse:
    run = await runs_service.get_run(session, run_id)
    job = await runs_service.get_job(session, run.job_id)
    return RunResponse.of(run, job.jenkins_name)


@router.post("/runs/{run_id}/cancel", response_model=CancelResponse, summary="Cancel or stop a run")
async def cancel_run(
    run_id: str,
    user: DevOpsUser,
    session: Annotated[AsyncSession, Depends(get_db)],
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
    session: Annotated[AsyncSession, Depends(get_db)],
    jenkins: Annotated[JenkinsClient, Depends(get_jenkins_client)],
    start: Annotated[int, Query(ge=0, description="Byte offset to read from")] = 0,
) -> LogResponse:
    """A window of the log, with the offset to ask for next.

    Windowed rather than whole: the UI tails a running build, and returning the entire log on each
    poll would move the same megabyte over and over.
    """
    run = await runs_service.get_run(session, run_id)
    window = await runs_service.run_log(session, jenkins, run=run, start=start)
    return LogResponse(
        run_id=run.id,
        text=window.text,
        next_offset=window.next_offset,
        more_data=window.more_data,
    )
