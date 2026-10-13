"""Explaining why a run failed (T5.9): the run, its chain and its log, brought to the explainer.

This module does the IO. What the log shows is worked out by ``app.failures.analysis``, and how it
is put into words, and checked, by ``app.failures.explainer``.

What a failure stopped is read from the database, not from the log: a freestyle chain's later jobs
are "did not start" exactly when the chain has no run for them, which is the Phase 5 acceptance
("the freestyle deploy job never starts") stated by the explanation itself.
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode, conflict
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.models import Chain, GeneratedPipeline, Job, JobRun, LlmCall, RunResult, Service
from app.failures.analysis import PIPELINE, FailureAnalysis, analyse, unavailable
from app.failures.explainer import FailureContext, FailureExplainer, FailureExplanation
from app.services import chains as chains_service
from app.services import runs as runs_service
from app.services.generation import stored_artifact, stored_spec
from app.services.jenkins import JenkinsClient, JenkinsError, JobNotFoundError

logger = get_logger(__name__)

# Jenkins can report a build finished a moment before it closes the log (D-039). An explanation is
# asked for after the failure, so a short wait for X-More-Data to clear is nearly always enough.
LOG_SETTLE_ATTEMPTS: Final = 5
LOG_SETTLE_SECONDS: Final = 1.0

_NOT_FAILED: Final = {
    RunResult.SUCCESS.value: "This run succeeded, so there is no failure to explain.",
    RunResult.RUNNING.value: "This run has not finished. Ask again if it fails.",
    RunResult.ABORTED.value: "This run was cancelled, so there is no failure to explain.",
    RunResult.NOT_BUILT.value: "This run never built, so there is no failure to explain.",
}

# Stage view statuses (wfapi/describe).
_FAILED_STAGE: Final = frozenset({"FAILED", "UNSTABLE"})
_SKIPPED_STAGE: Final = frozenset({"NOT_EXECUTED", "SKIPPED", "NOT_BUILT"})


def known_secrets(settings: Settings) -> tuple[str, ...]:
    """The configured secrets. Every log is searched for them by value before anything reads it."""
    values = (settings.jenkins_token, settings.groq_api_key, settings.jwt_secret)
    return tuple(value for value in (*values, settings.metrics_token) if value)


@dataclass(frozen=True)
class RunFailure:
    run: JobRun
    job: Job
    chain: Chain | None
    url: str | None
    not_started: tuple[str, ...]
    analysis: FailureAnalysis
    explanation: FailureExplanation


async def explain_run(
    session: AsyncSession,
    jenkins: JenkinsClient,
    explainer: FailureExplainer,
    *,
    run_id: str,
    secrets: tuple[str, ...] = (),
    settle_seconds: float = LOG_SETTLE_SECONDS,
) -> RunFailure:
    run = await runs_service.get_run(session, run_id)
    if run.result not in chains_service.FAILED_RESULTS:
        raise conflict(
            ErrorCode.RUN_NOT_FAILED,
            _NOT_FAILED.get(run.result, "Only a failed run can be explained."),
            run_id=run.id,
            result=run.result,
        )
    job = await runs_service.get_job(session, run.job_id)
    chain = await session.get(Chain, run.chain_id) if run.chain_id else None
    pipeline = (
        await session.get(GeneratedPipeline, chain.pipeline_id)
        if chain is not None and chain.pipeline_id
        else None
    )
    service = await session.get(Service, job.service_id) if job.service_id else None

    stage, template, skipped_in_view = await _failed_stage(jenkins, job, run, pipeline)
    not_started = (
        await chains_service.not_started_after(session, chain, job.jenkins_name)
        if chain is not None
        else ()
    )
    analysis = await _read_and_analyse(
        jenkins,
        job,
        run,
        stage=stage,
        template=template,
        secrets=secrets,
        settle_seconds=settle_seconds,
    )
    if skipped_in_view:
        # The log names the stages Declarative skipped; the stage view may name more.
        analysis = dataclasses.replace(
            analysis,
            skipped_stages=tuple(dict.fromkeys((*analysis.skipped_stages, *skipped_in_view))),
        )

    explanation = await explainer.explain(
        analysis,
        FailureContext(
            job_name=job.jenkins_name,
            job_type=job.job_type,
            result=run.result,
            service=service.name if service is not None else None,
            not_started=not_started,
        ),
    )

    # 4.5.1: every call is recorded, with the prompt version (4.5.6). The command is the one the
    # run's chain was generated from, when there is one.
    for call in explanation.calls:
        session.add(
            LlmCall(
                command_id=pipeline.command_id if pipeline is not None else None,
                provider=call.provider,
                model=call.model,
                latency_ms=call.latency_ms,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                fallback_used=call.fallback_used,
                cached=call.cached,
                prompt_version=explanation.prompt_version,
                outcome=call.outcome,
            )
        )
    if explanation.calls:
        await session.commit()

    logger.info(
        "run_failure_explained",
        run_id=run.id,
        category=analysis.category.value,
        source=explanation.source.value,
        rejected=explanation.rejected,
        redactions=analysis.redactions,
    )
    return RunFailure(
        run=run,
        job=job,
        chain=chain,
        url=await chains_service.build_url(jenkins, job.jenkins_name, run),
        not_started=not_started,
        analysis=analysis,
        explanation=explanation,
    )


async def _failed_stage(
    jenkins: JenkinsClient, job: Job, run: JobRun, pipeline: GeneratedPipeline | None
) -> tuple[str | None, str | None, tuple[str, ...]]:
    """The failed stage's name and template, and the stages the stage view says never ran.

    A freestyle chain job is one stage, named in the artifact it was rendered from. A Pipeline run
    has many, and the stage view says which one failed.
    """
    if job.job_type != PIPELINE:
        artifact = stored_artifact(pipeline) if pipeline is not None else None
        rendered = (
            next((item for item in artifact.jobs if item.name == job.jenkins_name), None)
            if artifact is not None
            else None
        )
        if rendered is None or rendered.stage is None:
            return None, None, ()
        return rendered.stage.name, rendered.stage.template, ()

    if run.build_number <= 0:
        return None, None, ()
    try:
        stages = await jenkins.pipeline_stages(job.jenkins_name, run.build_number)
    except JenkinsError:
        return None, None, ()
    failed = next((i for i, stage in enumerate(stages) if stage.status in _FAILED_STAGE), None)
    if failed is None:
        return None, None, ()
    name = stages[failed].name
    spec = stored_spec(pipeline) if pipeline is not None else None
    template = (
        next((stage.template for stage in spec.stages if stage.name == name), None)
        if spec is not None
        else None
    )
    skipped = tuple(stage.name for stage in stages[failed + 1 :] if stage.status in _SKIPPED_STAGE)
    return name, template, skipped


async def _read_and_analyse(
    jenkins: JenkinsClient,
    job: Job,
    run: JobRun,
    *,
    stage: str | None,
    template: str | None,
    secrets: tuple[str, ...],
    settle_seconds: float,
) -> FailureAnalysis:
    """The whole log, analysed; or, when Jenkins no longer has it, an analysis that says so.

    Jenkins being unreachable is different from the log being gone: the first is worth retrying,
    so it is an error rather than an explanation that the cause cannot be shown.
    """
    if run.build_number <= 0:
        return unavailable("the run never started as a Jenkins build", stage=stage)
    try:
        chunk = await jenkins.console_window(job.jenkins_name, run.build_number, 0)
        for _ in range(LOG_SETTLE_ATTEMPTS - 1):
            if not chunk.more_data:
                break
            await asyncio.sleep(settle_seconds)
            chunk = await jenkins.console_window(job.jenkins_name, run.build_number, 0)
    except JobNotFoundError:
        return unavailable("Jenkins no longer has this build", stage=stage)
    except JenkinsError as exc:
        raise conflict(
            ErrorCode.JENKINS_UNAVAILABLE,
            "The log could not be read from Jenkins just now. Try again in a moment.",
            run_id=run.id,
        ) from exc
    return analyse(
        chunk.text,
        job_type=job.job_type,
        stage=stage,
        stage_template=template,
        known_secrets=secrets,
        complete=not chunk.more_data,
    )
