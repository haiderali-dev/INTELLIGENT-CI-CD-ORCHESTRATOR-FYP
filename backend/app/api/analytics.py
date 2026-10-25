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

The chatbot evaluation (4.4.4's "evaluation results") is the evaluation harness's report file,
served as written (``app/services/evaluation.py``): it is computed by ``python -m eval report``,
not from rows here, and its provenance -- who wrote the gold labels -- travels with it.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ApiRateLimit, CurrentUser
from app.core.errors import ErrorCode, not_found
from app.core.settings import Settings
from app.db.models import Experiment, ExperimentMetric, JobRun, RunResult
from app.db.session import get_db
from app.services.dependencies import get_settings_dep
from app.services.evaluation import read_report
from app.services.runs import MAX_PAGE_SIZE, clamp_page

# Every route here carries the general per-user limit (security review, findings 5 and 10).
router = APIRouter(tags=["analytics"], dependencies=[ApiRateLimit])


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
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
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
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
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
    session: Annotated[AsyncSession, Depends(get_db, scope="function")],
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


# ---------------------------------------------------------------------------
# The chatbot evaluation (T8.2)
# ---------------------------------------------------------------------------


class EvaluationProvenance(BaseModel):
    labels: str | None = Field(description="human, machine (D-081) or mixed: who wrote the labels")
    statement: str | None = Field(description="What the labels' provenance means; show it")


class EvaluationSource(BaseModel):
    id: str
    name: str
    licence: str


class EvaluationDataset(BaseModel):
    name: str
    items: int
    sha256: str
    labels: str | None
    reviewed_by_a_person: int
    decision: str | None
    splits: dict[str, int | None]
    sources: list[EvaluationSource]


class EvaluationComparisonRow(BaseModel):
    """One parser's figures on one set of items; every rate is 0 to 1, or null if not measured."""

    run: str
    parser: str
    complete: bool
    labels: str | None
    n: int
    errors: int
    action_accuracy: float | None
    exact_match: float | None
    behavior_accuracy: float | None
    clarification_precision: float | None
    clarification_recall: float | None
    refusal_rate: float | None
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    tokens_per_command: float | None
    per_field_accuracy: dict[str, float | None]
    behavior_by_category: dict[str, float | None]


class EvaluationAblationRow(EvaluationComparisonRow):
    configuration: str
    label: str
    plan_valid_before_repair: float | None
    plan_valid_after_repair: float | None


class EvaluationAblations(BaseModel):
    parser: str
    rows: list[EvaluationAblationRow]
    rules: EvaluationComparisonRow | None


class EvaluationPlanRow(BaseModel):
    run: str
    parser: str
    max_repairs: int | None
    plannable_items: int
    n: int
    valid_before_repair: float | None
    valid_after_repair: float | None
    repaired: int
    still_invalid: int
    no_model_plan: int
    errors: int
    distinct_requests: int
    tokens_per_plan: float | None


class EvaluationAssistantCell(BaseModel):
    n: int
    succeeded: int


class EvaluationEndToEndRow(BaseModel):
    run: str
    model: str | None
    complete: bool
    labels: str | None
    n: int | None
    expected: int | None
    succeeded: int | None
    success_rate: float | None
    failed_at: dict[str, int] | None
    by_assistant: dict[str, EvaluationAssistantCell] | None


class EvaluationRun(BaseModel):
    run: str
    parser: str | None
    scope: str
    configuration: str
    labels: str | None
    for_reporting: bool
    complete: bool
    stopped_reason: str | None
    n: int | None


class EvaluationResponse(BaseModel):
    """``eval/results/report.json`` as ``python -m eval report`` wrote it, or why there is none.

    Every field is required, so the generated client types say exactly what arrives.
    """

    available: bool
    detail: str | None = Field(description="Why nothing is available, when not")
    generated_at: datetime | None
    provenance: EvaluationProvenance | None
    dataset: EvaluationDataset | None
    comparison: list[EvaluationComparisonRow] = Field(description="The test split, 4.9's parsers")
    plans: list[EvaluationPlanRow]
    ablations: EvaluationAblations | None
    e2e: list[EvaluationEndToEndRow]
    runs: list[EvaluationRun] = Field(description="Every run, reportable or not")

    @classmethod
    def unavailable(cls, detail: str | None) -> EvaluationResponse:
        return cls(
            available=False,
            detail=detail,
            generated_at=None,
            provenance=None,
            dataset=None,
            comparison=[],
            plans=[],
            ablations=None,
            e2e=[],
            runs=[],
        )


@router.get(
    "/analytics/evaluation", response_model=EvaluationResponse, summary="Chatbot evaluation"
)
async def evaluation(
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> EvaluationResponse:
    """The evaluation report, as the harness wrote it. Read from disk on request, never cached,
    so a regenerated report shows at once."""
    data, reason = await asyncio.to_thread(read_report, settings)
    if data is None:
        return EvaluationResponse.unavailable(reason)
    try:
        return EvaluationResponse.model_validate({**data, "available": True, "detail": None})
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return EvaluationResponse.unavailable(
            f"The evaluation report does not match its schema at {where}: {first['msg']}."
        )
