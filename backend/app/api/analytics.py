"""Analytics: experiments, their metrics, and run statistics.

BUILD_PROMPT 4.4.4 groups "Experiments, evaluation results" under analytics. 4.4.3's note on
``job_runs`` is the constraint that shapes this module: "No aggregate is stored. Report section
5.14 makes the same point: a metric that cannot be recomputed from raw rows is one nobody can
defend."

So nothing here invents a figure. ``experiment_metrics`` rows are returned as the experiment
harness computed and stored them, and the run statistics are computed from ``job_runs`` on request.
Where a value cannot be computed honestly — a percentile over no rows, a mean over runs whose
``queue_wait_ms`` is null — the field is null rather than zero. Zero is a measurement; null is the
absence of one, and a chart that draws them the same way is lying.

Reads are open to any signed-in user. 4.4.4 does not restrict analytics, and the data is about the
build system rather than about people.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.errors import ErrorCode, not_found
from app.db.models import Experiment, ExperimentMetric, JobRun, RunResult
from app.db.session import get_db
from app.services.runs import MAX_PAGE_SIZE, clamp_page

router = APIRouter(tags=["analytics"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MetricResponse(BaseModel):
    name: str
    band: str
    value: float
    unit: str
    std_dev: float | None
    sample_size: int


class ExperimentResponse(BaseModel):
    id: str
    label: str
    mode: str
    workload: str
    executors: int
    repetition: int
    plugin_version: str | None
    jenkins_version: str | None
    workload_hash: str | None
    configuration: dict[str, Any]
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    @classmethod
    def of(cls, experiment: Experiment) -> ExperimentResponse:
        return cls(
            id=experiment.id,
            label=experiment.label,
            mode=experiment.mode,
            workload=experiment.workload,
            executors=experiment.executors,
            repetition=experiment.repetition,
            plugin_version=experiment.plugin_version,
            jenkins_version=experiment.jenkins_version,
            workload_hash=experiment.workload_hash,
            configuration=experiment.configuration or {},
            started_at=experiment.started_at,
            finished_at=experiment.finished_at,
            created_at=experiment.created_at,
        )


class ExperimentDetailResponse(ExperimentResponse):
    metrics: list[MetricResponse]


class ExperimentPage(BaseModel):
    items: list[ExperimentResponse]
    total: int
    limit: int
    offset: int


class RunStatsResponse(BaseModel):
    """Computed from ``job_runs`` on request, never from a stored aggregate.

    Every average is null when there is nothing to average over. A queue wait of 0 ms means a build
    started immediately; null means nobody measured it.
    """

    total_runs: int
    by_result: dict[str, int]
    running: int
    mean_duration_ms: float | None
    mean_queue_wait_ms: float | None
    max_queue_wait_ms: int | None
    runs_with_queue_wait: int
    success_rate: float | None


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


@router.get("/analytics/experiments", response_model=ExperimentPage, summary="Experiment runs")
async def list_experiments(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    mode: Annotated[str | None, Query(max_length=32)] = None,
    label: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int | None, Query(ge=1, le=MAX_PAGE_SIZE)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
) -> ExperimentPage:
    resolved_limit, resolved_offset = clamp_page(limit, offset)

    statement = select(Experiment)
    if mode:
        statement = statement.where(Experiment.mode == mode)
    if label:
        statement = statement.where(Experiment.label == label)

    total = int(
        await session.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
        or 0
    )
    rows = (
        await session.scalars(
            statement.order_by(Experiment.created_at.desc())
            .limit(resolved_limit)
            .offset(resolved_offset)
        )
    ).all()
    return ExperimentPage(
        items=[ExperimentResponse.of(experiment) for experiment in rows],
        total=total,
        limit=resolved_limit,
        offset=resolved_offset,
    )


@router.get(
    "/analytics/experiments/{experiment_id}",
    response_model=ExperimentDetailResponse,
    summary="One experiment with its metrics",
)
async def get_experiment(
    experiment_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ExperimentDetailResponse:
    experiment = await session.get(Experiment, experiment_id)
    if experiment is None:
        raise not_found(
            ErrorCode.VALIDATION_FAILED, "No such experiment.", experiment_id=experiment_id
        )

    metrics = (
        await session.scalars(
            select(ExperimentMetric)
            .where(ExperimentMetric.experiment_id == experiment_id)
            .order_by(ExperimentMetric.name, ExperimentMetric.band)
        )
    ).all()

    base = ExperimentResponse.of(experiment)
    return ExperimentDetailResponse(
        **base.model_dump(),
        metrics=[
            MetricResponse(
                name=metric.name,
                band=metric.band,
                value=metric.value,
                unit=metric.unit,
                std_dev=metric.std_dev,
                sample_size=metric.sample_size,
            )
            for metric in metrics
        ],
    )


# ---------------------------------------------------------------------------
# Run statistics
# ---------------------------------------------------------------------------


@router.get("/analytics/runs", response_model=RunStatsResponse, summary="Run statistics")
async def run_statistics(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RunStatsResponse:
    """Counts and averages over ``job_runs``, computed now.

    Deliberately recomputed rather than cached. 4.4.3: a metric that cannot be derived from the raw
    rows is one nobody can defend, and a cached figure is one more thing that can disagree with
    them.
    """
    counts = (
        await session.execute(select(JobRun.result, func.count()).group_by(JobRun.result))
    ).all()
    by_result = {str(result): int(count) for result, count in counts}
    total = sum(by_result.values())
    running = by_result.get(RunResult.RUNNING.value, 0)

    # Averages over finished runs only; a running build's duration is not a duration yet.
    finished = select(JobRun).where(JobRun.result != RunResult.RUNNING.value).subquery()
    mean_duration = await session.scalar(
        select(func.avg(finished.c.duration_ms)).where(finished.c.duration_ms.is_not(None))
    )

    mean_wait = await session.scalar(
        select(func.avg(JobRun.queue_wait_ms)).where(JobRun.queue_wait_ms.is_not(None))
    )
    max_wait = await session.scalar(
        select(func.max(JobRun.queue_wait_ms)).where(JobRun.queue_wait_ms.is_not(None))
    )
    measured = int(
        await session.scalar(
            select(func.count()).select_from(JobRun).where(JobRun.queue_wait_ms.is_not(None))
        )
        or 0
    )

    # Success rate over *settled* runs only. Counting running builds in the denominator would make
    # the figure drop every time a build starts, which is not a change in reliability.
    settled = total - running
    successes = by_result.get(RunResult.SUCCESS.value, 0)

    return RunStatsResponse(
        total_runs=total,
        by_result=by_result,
        running=running,
        mean_duration_ms=float(mean_duration) if mean_duration is not None else None,
        mean_queue_wait_ms=float(mean_wait) if mean_wait is not None else None,
        max_queue_wait_ms=int(max_wait) if max_wait is not None else None,
        runs_with_queue_wait=measured,
        success_rate=(successes / settled) if settled > 0 else None,
    )
