"""Generate, regenerate, explain and approve (T5.6). BUILD_PROMPT 4.6.2 steps 1 to 5, and 4.6.4.

1. **Plan** -- the planner (T5.2), from the confirmed intent.
2. **Render** -- the templates (T5.3).
3. **Validate** -- the validators (T5.4). Plan errors were already repaired inside the planner.
4. **Preview** -- the stored row: spec YAML, rendered jobs, checklist, explanation on request.
5. **Approve** -- "a confirmation dialog, then create or update the jobs, set priority, trigger, and
   write ``generated_pipelines``, ``jobs`` and the audit log."

Every attempt is a ``generated_pipelines`` row, valid or not, because the preview's progress line
("Understood, Planned, Rendered, Validated, each showing a check or the exact error", 4.7.4)
needs a failed step to be something the user can read, not an error page. A regenerate supersedes
the rows before it: they are cancelled, so an outdated plan cannot be approved by mistake.

**Approval is idempotent, and a double click cannot start two chains (4.6.4).** The pipeline row is
locked, marked approved with the key and committed *before* Jenkins is touched. A second request
with the same key gets the first one's result back. Any other second request finds the row approved
and is refused. If Jenkins fails before the chain starts, the approval is undone, so the user can
try again rather than being left with an approved plan that never ran.

**Jobs are created last first.** Jenkins drops a downstream trigger that names a job that does not
exist yet (D-044), so the chain is saved from its end back to its start.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.intent import GENERATING_ACTIONS, Intent, Urgency
from app.ai.prompting import load_prompt
from app.ai.providers.base import ChatMessage, LLMProvider, ProviderError
from app.ai.quota import QuotaTracker
from app.core.errors import ApiError, ErrorCode, conflict, not_found, unavailable
from app.core.logging import get_logger
from app.db.models import (
    AuditLog,
    ChainStatus,
    CommandStatus,
    Conversation,
    GeneratedPipeline,
    Job,
    JobType,
    LlmCall,
    Message,
    MessageRole,
    NlCommand,
    PipelineStatus,
    Service,
    User,
)
from app.generation.planner import Planner, PlannerError, PlanOutcome, PlanRequest
from app.generation.render import RenderedArtifact, RenderError, render
from app.generation.spec import Assistant, GenerationSpec
from app.generation.validate import (
    Check,
    CheckStatus,
    ValidationReport,
    parse_spec,
    validator_for,
)
from app.services import chains
from app.services.catalog import Catalog
from app.services.conversations import get_command, intent_summary, refuse_once_run
from app.services.git import GitClient
from app.services.jenkins import JenkinsClient, JenkinsError, JobAlreadyExistsError
from app.services.tracker import RunTracker

logger = get_logger(__name__)

PIPELINE_APPROVED_AUDIT_ACTION: Final = "pipeline.approved"
JOB_SAVED_AUDIT_ACTION: Final = "job.saved"
MAX_IDEMPOTENCY_KEY: Final = 64

_ASSISTANTS: Final = {"FREESTYLE": Assistant.FREESTYLE, "PIPELINE": Assistant.PIPELINE}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineContext:
    pipeline: GeneratedPipeline
    command: NlCommand
    conversation: Conversation


async def get_pipeline(session: AsyncSession, *, user: User, pipeline_id: str) -> PipelineContext:
    """A pipeline, its command and its conversation, if the conversation is this user's."""
    pipeline = await session.get(GeneratedPipeline, pipeline_id)
    if pipeline is None:
        raise not_found(ErrorCode.PIPELINE_NOT_FOUND, "No such pipeline.", pipeline_id=pipeline_id)
    try:
        command, conversation = await get_command(
            session, user=user, command_id=pipeline.command_id
        )
    except ApiError as exc:
        raise not_found(
            ErrorCode.PIPELINE_NOT_FOUND, "No such pipeline.", pipeline_id=pipeline_id
        ) from exc
    return PipelineContext(pipeline=pipeline, command=command, conversation=conversation)


def stored_artifact(pipeline: GeneratedPipeline) -> RenderedArtifact | None:
    if not pipeline.rendered_artifact:
        return None
    return RenderedArtifact.from_json(pipeline.rendered_artifact)


def stored_spec(pipeline: GeneratedPipeline) -> GenerationSpec | None:
    parsed = parse_spec(pipeline.spec_yaml) if pipeline.spec_yaml else None
    return parsed if isinstance(parsed, GenerationSpec) else None


# ---------------------------------------------------------------------------
# Generating
# ---------------------------------------------------------------------------


def ready_intent(command: NlCommand) -> tuple[Intent, str | None, str | None]:
    """The confirmed intent and what its branch and commit resolved to. 409 if not ready."""
    record = command.parsed_intent or {}
    if record.get("disposition") != "READY":
        raise conflict(
            ErrorCode.VALIDATION_FAILED,
            "This request is not ready to generate. Answer its question or edit it first.",
            command_id=command.id,
            disposition=record.get("disposition"),
        )
    intent = Intent.model_validate(record.get("intent") or {})
    if intent.action not in GENERATING_ACTIONS:
        raise conflict(
            ErrorCode.VALIDATION_FAILED,
            f"{intent.action.value} does not create a job, so there is nothing to generate.",
            command_id=command.id,
        )
    resolved = record.get("resolved") or {}
    return intent, resolved.get("branch"), resolved.get("commit")


@dataclass
class _Attempt:
    """What one generation produced, step by step, before it is stored."""

    spec: GenerationSpec | None = None
    plan: PlanOutcome | None = None
    artifact: RenderedArtifact | None = None
    report: ValidationReport | None = None
    render_error: str | None = None
    edited: bool = False


async def generate(
    session: AsyncSession,
    *,
    user: User,
    command: NlCommand,
    conversation: Conversation,
    planner: Planner,
    catalog: Catalog,
    git: GitClient,
    jenkins: JenkinsClient,
) -> GeneratedPipeline:
    """Plan, render, validate and store (4.6.2 steps 1 to 3)."""
    intent, branch, commit = ready_intent(command)
    await refuse_once_run(session, command.id)
    # Choosing Generate is the user confirming the intent card: 4.4.3's CONFIRMED status.
    command.status = CommandStatus.CONFIRMED.value
    assistant = _ASSISTANTS[conversation.assistant]
    try:
        plan = await planner.plan(
            PlanRequest(
                intent=intent, assistant=assistant, resolved_branch=branch, resolved_commit=commit
            )
        )
    except PlannerError as exc:
        raise conflict(ErrorCode.SPEC_INVALID, str(exc), command_id=command.id) from exc
    attempt = _Attempt(spec=plan.spec, plan=plan)
    await _render_and_validate(attempt, intent=intent, catalog=catalog, git=git, jenkins=jenkins)
    return await _store(
        session,
        user=user,
        command=command,
        conversation=conversation,
        intent=intent,
        attempt=attempt,
        jenkins=jenkins,
    )


async def regenerate(
    session: AsyncSession,
    *,
    user: User,
    context: PipelineContext,
    planner: Planner,
    catalog: Catalog,
    git: GitClient,
    jenkins: JenkinsClient,
    spec_yaml: str | None,
) -> GeneratedPipeline:
    """Plan again, or apply an edited spec (4.6.2 step 4: "editable YAML re-validated on every
    edit"). The rows before it are cancelled."""
    pipeline = context.pipeline
    if pipeline.status == PipelineStatus.APPROVED.value:
        raise conflict(
            ErrorCode.ALREADY_APPROVED,
            "This plan was already approved and run. Send a new message to change it.",
            pipeline_id=pipeline.id,
        )
    await refuse_once_run(session, pipeline.command_id)
    if spec_yaml is None:
        fresh = await generate(
            session,
            user=user,
            command=context.command,
            conversation=context.conversation,
            planner=planner,
            catalog=catalog,
            git=git,
            jenkins=jenkins,
        )
    else:
        intent, _, _ = ready_intent(context.command)
        attempt = _Attempt(edited=True)
        parsed = parse_spec(spec_yaml)
        if isinstance(parsed, ValidationReport):
            attempt.report = parsed
        else:
            attempt.spec = parsed
            locked = _locked_fields(parsed, intent, context.conversation)
            if locked is not None:
                attempt.report = ValidationReport(checks=(locked,))
            else:
                await _render_and_validate(
                    attempt, intent=intent, catalog=catalog, git=git, jenkins=jenkins
                )
        fresh = await _store(
            session,
            user=user,
            command=context.command,
            conversation=context.conversation,
            intent=intent,
            attempt=attempt,
            jenkins=jenkins,
            spec_yaml=spec_yaml,
        )
    await session.execute(
        update(GeneratedPipeline)
        .where(
            GeneratedPipeline.command_id == context.command.id,
            GeneratedPipeline.id != fresh.id,
            GeneratedPipeline.status.in_(
                [
                    PipelineStatus.DRAFT.value,
                    PipelineStatus.VALIDATED.value,
                    PipelineStatus.INVALID.value,
                ]
            ),
        )
        .values(status=PipelineStatus.CANCELLED.value)
    )
    return fresh


def _locked_fields(
    spec: GenerationSpec, intent: Intent, conversation: Conversation
) -> Check | None:
    """The fields policy decided on cannot be changed by editing the YAML.

    The service, the assistant and the priority were checked by policy when the request was
    confirmed -- a HIGH priority against the user's quota and justification (4.5.5). Changing them
    in the YAML would skip that, so it is refused with a pointer to where it can be done.
    """
    problems = []
    if spec.service != intent.service:
        problems.append(f"the service must stay {intent.service}")
    if spec.assistant is not _ASSISTANTS[conversation.assistant]:
        problems.append(f"the assistant must stay {_ASSISTANTS[conversation.assistant].value}")
    expected = intent.urgency or Urgency.MEDIUM
    if spec.priority is not expected:
        problems.append(f"the priority must stay {expected.value}")
    if not problems:
        return None
    return Check(
        "policy_fields",
        "Fields decided by policy",
        CheckStatus.FAILED,
        "; ".join(problems) + ". Edit the request itself to change these.",
        "input",
    )


async def _render_and_validate(
    attempt: _Attempt,
    *,
    intent: Intent,
    catalog: Catalog,
    git: GitClient,
    jenkins: JenkinsClient,
) -> None:
    spec = attempt.spec
    if spec is None:
        return
    service = catalog.get(spec.service)
    if service is None:
        attempt.report = ValidationReport(
            checks=(
                Check(
                    "catalog_and_git",
                    "Service, branch, commit and suites",
                    CheckStatus.FAILED,
                    f"There is no service called {spec.service!r} in the catalog.",
                    "input",
                ),
            )
        )
        return
    validator = validator_for(spec, catalog, git, jenkins)
    try:
        attempt.artifact = render(spec, service, action=intent.action)
    except RenderError as exc:
        # The spec checks still run, in 4.6.3's order, so the checklist names the real problem --
        # "production is refused" reads better than "no command for that stage". The artifact
        # check carries the render error, since there is no artifact to check.
        attempt.render_error = str(exc)
        empty = RenderedArtifact(
            job_type=JobType.PIPELINE
            if spec.assistant is Assistant.PIPELINE
            else JobType.FREESTYLE,
            jobs=(),
            parameters=spec.revision.parameters(),
        )
        report = await validator.validate(spec, empty)
        attempt.report = ValidationReport(
            checks=tuple(
                Check(check.name, check.label, CheckStatus.FAILED, str(exc), "template")
                if check.name == "artifact"
                else check
                for check in report.checks
            )
        )
        return
    attempt.report = await validator.validate(spec, attempt.artifact)


async def _store(
    session: AsyncSession,
    *,
    user: User,
    command: NlCommand,
    conversation: Conversation,
    intent: Intent,
    attempt: _Attempt,
    jenkins: JenkinsClient,
    spec_yaml: str | None = None,
) -> GeneratedPipeline:
    valid = attempt.report is not None and attempt.report.ok and attempt.artifact is not None
    existing = await _existing_jobs(jenkins, attempt.artifact) if valid else []
    summary = (
        approval_summary(attempt.spec, attempt.artifact, existing)
        if valid and attempt.spec is not None and attempt.artifact is not None
        else None
    )
    job_type = "PIPELINE" if conversation.assistant == "PIPELINE" else "FREESTYLE"
    pipeline = GeneratedPipeline(
        command_id=command.id,
        job_type=job_type,
        spec_yaml=attempt.spec.to_yaml() if attempt.spec is not None else (spec_yaml or ""),
        rendered_artifact=attempt.artifact.to_json() if attempt.artifact is not None else "",
        validation_results={
            "action": intent.action.value,
            "source": "edit" if attempt.edited else "plan",
            "progress": _progress(intent, attempt),
            "plan": attempt.plan.to_record() if attempt.plan is not None else None,
            "report": attempt.report.to_record() if attempt.report is not None else None,
            "render_error": attempt.render_error,
            "existing_jobs": existing,
            "summary": summary,
        },
        attempts=len(attempt.plan.attempts) if attempt.plan is not None else 1,
        status=(PipelineStatus.VALIDATED if valid else PipelineStatus.INVALID).value,
    )
    session.add(pipeline)
    await session.flush()

    if attempt.plan is not None:
        for call in attempt.plan.calls:
            session.add(
                LlmCall(
                    command_id=command.id,
                    provider=call.provider,
                    model=call.model,
                    latency_ms=call.latency_ms,
                    prompt_tokens=call.prompt_tokens,
                    completion_tokens=call.completion_tokens,
                    fallback_used=call.fallback_used,
                    cached=call.cached,
                    prompt_version=attempt.plan.prompt_version,
                    outcome=call.outcome,
                )
            )

    content = (
        f"Generated and validated: {summary}"
        if valid and summary
        else "The plan did not pass validation. The checklist shows what to fix."
    )
    session.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT.value,
            content=content,
            payload={"kind": "pipeline", "pipeline_id": pipeline.id, "status": pipeline.status},
        )
    )
    await session.flush()
    logger.info(
        "pipeline_generated",
        pipeline_id=pipeline.id,
        command_id=command.id,
        status=pipeline.status,
        source="edit" if attempt.edited else "plan",
    )
    return pipeline


def _progress(intent: Intent, attempt: _Attempt) -> list[dict[str, Any]]:
    """4.7.4's progress line: Understood, Planned, Rendered, Validated."""
    steps: list[dict[str, Any]] = [
        {"step": "Understood", "ok": True, "detail": intent_summary(intent)}
    ]
    if attempt.edited:
        planned_ok = attempt.spec is not None
        detail = "edited spec parsed" if planned_ok else _first_failure(attempt.report)
    else:
        plan = attempt.plan
        planned_ok = plan is not None
        detail = (
            f"{'model ' + (plan.model or '') if plan.source == 'model' else 'default plan'}"
            f", {plan.repairs} repair(s)"
            if plan is not None
            else "no plan"
        )
    steps.append({"step": "Planned", "ok": planned_ok, "detail": detail})
    if not planned_ok:
        return steps
    if attempt.artifact is None:
        failure = attempt.render_error or _first_failure(attempt.report)
        steps.append({"step": "Rendered", "ok": False, "detail": failure})
        return steps
    steps.append({"step": "Rendered", "ok": True, "detail": f"{len(attempt.artifact.jobs)} job(s)"})
    report = attempt.report
    steps.append(
        {
            "step": "Validated",
            "ok": bool(report and report.ok),
            "detail": "all checks passed" if report and report.ok else _first_failure(report),
        }
    )
    return steps


def _first_failure(report: ValidationReport | None) -> str:
    if report is None or not report.failures:
        return "not validated"
    failure = report.failures[0]
    return f"{failure.label}: {failure.message}"


async def _existing_jobs(jenkins: JenkinsClient, artifact: RenderedArtifact | None) -> list[str]:
    if artifact is None:
        return []
    found = []
    for job in artifact.jobs:
        try:
            if await jenkins.job_exists(job.name):
                found.append(job.name)
        except JenkinsError:
            continue
    return found


def approval_summary(spec: GenerationSpec, artifact: RenderedArtifact, existing: list[str]) -> str:
    """4.7.4: "Creates 3 jobs and starts fs-payment-service-build on main at HIGH priority"."""
    total = len(artifact.jobs)
    updated = sum(1 for job in artifact.jobs if job.name in existing)
    created = total - updated

    def jobs(count: int) -> str:
        return f"{count} job{'s' if count != 1 else ''}"

    if updated == 0:
        verb = f"Creates {jobs(created)}"
    elif created == 0:
        verb = f"Updates {jobs(updated)}"
    else:
        verb = f"Creates {jobs(created)}, updates {updated},"
    revision = spec.revision
    where = revision.branch + (f" at {revision.commit[:7]}" if revision.commit else "")
    return (
        f"{verb} and starts {artifact.first_job.name} on {where} at {spec.priority.value} priority"
    )


# ---------------------------------------------------------------------------
# Approving
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Approval:
    pipeline: GeneratedPipeline
    result: dict[str, Any]
    replayed: bool = False


async def approve(
    session: AsyncSession,
    *,
    user: User,
    context: PipelineContext,
    key: str,
    catalog: Catalog,
    jenkins: JenkinsClient,
    tracker: RunTracker | None,
) -> Approval:
    """Create or update the jobs and start the first one, exactly once per idempotency key.

    The service's chain lock (T5.7) is claimed in the same commit as the approval, so a chain
    already running for the service refuses this one before anything reaches Jenkins.
    """
    key = key.strip()
    if not key or len(key) > MAX_IDEMPOTENCY_KEY:
        raise conflict(
            ErrorCode.BAD_REQUEST,
            f"An Idempotency-Key header of 1 to {MAX_IDEMPOTENCY_KEY} characters is required.",
        )
    pipeline = await _lock(session, context.pipeline.id)

    if pipeline.status == PipelineStatus.APPROVED.value:
        if pipeline.idempotency_key == key:
            return Approval(
                pipeline, dict((pipeline.validation_results or {}).get("approval") or {}), True
            )
        raise conflict(
            ErrorCode.ALREADY_APPROVED,
            "This plan was already approved; its chain is running or has run.",
            pipeline_id=pipeline.id,
        )
    await refuse_once_run(session, pipeline.command_id, besides=pipeline.id)
    other = await session.scalar(
        select(GeneratedPipeline.id).where(
            GeneratedPipeline.idempotency_key == key, GeneratedPipeline.id != pipeline.id
        )
    )
    if other is not None:
        raise conflict(
            ErrorCode.BAD_REQUEST, "That idempotency key was already used for another plan."
        )
    if pipeline.status != PipelineStatus.VALIDATED.value:
        raise conflict(
            ErrorCode.VALIDATION_REJECTED,
            "Only a plan that passed validation can be approved.",
            pipeline_id=pipeline.id,
            status=pipeline.status,
        )
    spec = stored_spec(pipeline)
    artifact = stored_artifact(pipeline)
    if spec is None or artifact is None:
        raise conflict(ErrorCode.VALIDATION_REJECTED, "This plan has nothing to run.")

    # The chain lock: refuses while this service's chain is running (4.6.4).
    try:
        chain = await chains.claim(
            session,
            service=spec.service,
            job_type=artifact.job_type.value,
            jobs=[job.name for job in artifact.jobs],
            parameters=artifact.parameters,
            user=user,
            pipeline_id=pipeline.id,
        )
    except ApiError:
        # The refusal is a policy denial, which 4.4.3 says to audit, and get_db rolls the session
        # back on any exception. Nothing else has been written yet, so committing keeps only the
        # audit entry claim() added (the D-022 pattern).
        await session.commit()
        raise

    # Claim the approval and commit it with the chain before Jenkins is touched, so a concurrent
    # second request sees both. The unique key, and the one-running-chain-per-service index, make
    # a race lose cleanly in the database.
    pipeline.status = PipelineStatus.APPROVED.value
    pipeline.idempotency_key = key
    pipeline.approved_by = user.id
    pipeline.approved_at = datetime.now(UTC)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if await chains.running_chain(session, spec.service) is not None:
            raise conflict(
                ErrorCode.CHAIN_ALREADY_RUNNING,
                f"A chain started for {spec.service} a moment ago. Wait for it to finish.",
            ) from exc
        raise conflict(
            ErrorCode.ALREADY_APPROVED, "This plan was approved by another request."
        ) from exc

    try:
        await _save_jobs(jenkins, artifact)
        queue_item_id = await jenkins.trigger(artifact.first_job.name, artifact.parameters)
    except JenkinsError as exc:
        chains.finish(chain, ChainStatus.ABORTED)
        await _undo_approval(session, pipeline)
        logger.warning("approval_failed", pipeline_id=pipeline.id, error=str(exc)[:200])
        raise unavailable(
            ErrorCode.JENKINS_UNAVAILABLE,
            "Jenkins did not accept the jobs, so nothing was started. Try again when it answers.",
            pipeline_id=pipeline.id,
        ) from exc

    jobs = await _upsert_jobs(session, artifact=artifact, spec=spec, user=user, catalog=catalog)
    first = jobs[0]
    chain.queue_item_id = queue_item_id
    if tracker is not None:
        tracker.track(
            queue_item_id=queue_item_id,
            job_id=first.id,
            job_name=first.jenkins_name,
            chain_id=chain.id,
        )

    result: dict[str, Any] = {
        "chain_id": chain.id,
        "jobs": [job.jenkins_name for job in jobs],
        "first_job": first.jenkins_name,
        "queue_item_id": queue_item_id,
        "parameters": artifact.parameters,
        "priority": spec.priority.value,
        "approved_at": (pipeline.approved_at or datetime.now(UTC)).isoformat(),
    }
    pipeline.validation_results = {**(pipeline.validation_results or {}), "approval": result}

    session.add(
        AuditLog(
            actor_id=user.id,
            action=PIPELINE_APPROVED_AUDIT_ACTION,
            target=f"pipeline:{pipeline.id}",
            details={"command_id": context.command.id, **result},
        )
    )
    for job in artifact.jobs:
        session.add(
            AuditLog(
                actor_id=user.id,
                action=JOB_SAVED_AUDIT_ACTION,
                target=job.name,
                details={"pipeline_id": pipeline.id, "position": job.position},
            )
        )
    session.add(
        Message(
            conversation_id=context.conversation.id,
            role=MessageRole.ASSISTANT.value,
            content=f"Run started: {first.jenkins_name} is queued.",
            payload={"kind": "run", "pipeline_id": pipeline.id, **result},
        )
    )
    await session.flush()
    logger.info("pipeline_approved", pipeline_id=pipeline.id, first_job=first.jenkins_name)
    return Approval(pipeline, result)


async def _lock(session: AsyncSession, pipeline_id: str) -> GeneratedPipeline:
    """The pipeline row, locked for this transaction where the database supports it."""
    row = await session.scalar(
        select(GeneratedPipeline)
        .where(GeneratedPipeline.id == pipeline_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise not_found(ErrorCode.PIPELINE_NOT_FOUND, "No such pipeline.", pipeline_id=pipeline_id)
    return row


async def _undo_approval(session: AsyncSession, pipeline: GeneratedPipeline) -> None:
    pipeline.status = PipelineStatus.VALIDATED.value
    pipeline.idempotency_key = None
    pipeline.approved_by = None
    pipeline.approved_at = None
    await session.commit()


async def _save_jobs(jenkins: JenkinsClient, artifact: RenderedArtifact) -> None:
    """Create or update every job, last first, so each trigger names a job that exists."""
    for job in reversed(artifact.jobs):
        if await jenkins.job_exists(job.name):
            await jenkins.update_job(job.name, job.config_xml)
            continue
        try:
            await jenkins.create_job(job.name, job.config_xml)
        except JobAlreadyExistsError:
            await jenkins.update_job(job.name, job.config_xml)


async def _upsert_jobs(
    session: AsyncSession,
    *,
    artifact: RenderedArtifact,
    spec: GenerationSpec,
    user: User,
    catalog: Catalog,
) -> list[Job]:
    """One ``jobs`` row per Jenkins job, created or brought up to date."""
    service_id = await session.scalar(select(Service.id).where(Service.name == spec.service))
    jobs: list[Job] = []
    for rendered in artifact.jobs:
        job = await session.scalar(select(Job).where(Job.jenkins_name == rendered.name))
        if job is None:
            job = Job(jenkins_name=rendered.name, created_by=user.id)
            session.add(job)
        job.job_type = artifact.job_type.value
        job.service_id = service_id
        job.priority_level = spec.priority.value
        job.depends_on = rendered.depends_on
        job.chain_position = rendered.position
        jobs.append(job)
    await session.flush()
    return jobs


# ---------------------------------------------------------------------------
# Explaining
# ---------------------------------------------------------------------------


def explanation_input(spec: GenerationSpec, artifact: RenderedArtifact) -> dict[str, Any]:
    """What the explanation is about. No free text from the user: the justification is left out."""
    revision = spec.revision
    return {
        "assistant": "freestyle chain" if spec.assistant is Assistant.FREESTYLE else "Pipeline job",
        "service": spec.service,
        "branch": revision.branch,
        "commit": revision.commit,
        "priority": spec.priority.value,
        "jobs": [
            {
                "name": job.name,
                "stage": job.stage.name if job.stage is not None else None,
                "commands": list(job.commands),
                "starts_next": job.triggers,
            }
            for job in artifact.jobs
        ],
        "stages": [stage.name for stage in spec.stages],
    }


def plain_explanation(spec: GenerationSpec, artifact: RenderedArtifact) -> str:
    """The explanation written by code, used when no model can answer."""
    revision = spec.revision
    where = revision.branch + (f" at commit {revision.commit[:7]}" if revision.commit else "")
    if spec.assistant is Assistant.FREESTYLE:
        steps = []
        for index, job in enumerate(artifact.jobs):
            lead = "First" if index == 0 else "If that succeeds,"
            steps.append(f"{lead} {job.name} runs {' then '.join(job.commands)}.")
        return (
            f"This creates a chain of {len(artifact.jobs)} freestyle job(s) for {spec.service} "
            f"on {where} at {spec.priority.value} priority. "
            + " ".join(steps)
            + " A failed job stops the chain, so nothing after it runs."
        )
    commands = ", ".join(
        f"{stage.name} ({command})"
        for stage, command in zip(spec.stages, artifact.first_job.commands, strict=True)
    )
    return (
        f"This creates one Pipeline job, {artifact.first_job.name}, for {spec.service} on {where} "
        f"at {spec.priority.value} priority. Its stages run in order in one workspace: {commands}. "
        "A failed stage stops the run, so nothing after it runs."
    )


ExplainRecorder = Callable[[str, str, int, str], Awaitable[None]]


# What a plan's explanation may not say, sentence by sentence (independent security review, finding
# 14). Its input includes stage names a user can edit, so its output gets T5.9's treatment:
# nothing about production, and nothing shaped like a command. Backticks are allowed here, unlike
# in T5.9's suggestions: an explanation quotes job names in them.
_PRODUCTION_WORD = re.compile(r"(?i)\bprod(?:uction)?\b")
_SHELL_LIKE = re.compile(
    r"&&|\|\||\s\|\s|^\s*\$ |(?:^|\s)(?:sudo|rm|curl|wget|bash|sh|chmod|kubectl)\s+-?\w"
)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n")
LEFT_OUT: Final = "[A sentence about production or a command was left out.]"


def _screen_sentence(sentence: str) -> str:
    if _PRODUCTION_WORD.search(sentence) or _SHELL_LIKE.search(sentence):
        return LEFT_OUT
    return sentence


async def screened(chunks: AsyncIterator[str]) -> AsyncIterator[str]:
    """Pass a model's stream on a sentence at a time, each one screened.

    Held back until a sentence ends, since a word that decides the screen can arrive split across
    two chunks. What remains when the stream ends is screened and sent too.
    """
    pending = ""
    try:
        async for chunk in chunks:
            pending += chunk
            breaks = list(_SENTENCE_BREAK.finditer(pending))
            if not breaks:
                continue
            cut = breaks[-1].end()
            ready, pending = pending[:cut], pending[cut:]
            out: list[str] = []
            start = 0
            for found in _SENTENCE_BREAK.finditer(ready):
                out.append(_screen_sentence(ready[start : found.start()]) + found.group())
                start = found.end()
            yield "".join(out)
    except Exception:
        # A model that fails partway keeps what it said (explain_stream marks it cut short), so
        # what was held back goes out, screened, before the failure does.
        if pending:
            yield _screen_sentence(pending)
        raise
    if pending:
        yield _screen_sentence(pending)


async def explain_stream(
    spec: GenerationSpec,
    artifact: RenderedArtifact,
    *,
    provider: LLMProvider,
    models: tuple[str, ...],
    quota: QuotaTracker,
    record: ExplainRecorder | None = None,
) -> AsyncIterator[str]:
    """Stream the explanation: the first model that answers, else the code's own (4.6.2 step 4).

    A model that fails before its first word is passed over for the next; one that fails partway
    leaves what it said, marked as cut short, rather than starting again in a different voice.
    """
    prompt = load_prompt("explain_v1")
    rendered = prompt.render(catalog="", role="")
    message = ChatMessage(
        role="user", content=json.dumps(explanation_input(spec, artifact), separators=(",", ":"))
    )
    for model in models:
        if not quota.check(model).allowed:
            continue
        started = time.monotonic()
        said = False
        try:
            async for chunk in screened(
                provider.stream_text(system=rendered.system, messages=[message], model=model)
            ):
                said = True
                yield chunk
        except ProviderError as exc:
            latency = int((time.monotonic() - started) * 1000)
            if record is not None:
                await record(provider.name, model, latency, exc.outcome)
            if said:
                yield " [The explanation was cut short.]"
                return
            continue
        if said:
            if record is not None:
                await record(provider.name, model, int((time.monotonic() - started) * 1000), "ok")
            return
    yield plain_explanation(spec, artifact)
