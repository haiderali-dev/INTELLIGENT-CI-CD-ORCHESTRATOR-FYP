"""Chains: the per-service lock, tracking, the run card, cancelling, and run commands (T5.7).

BUILD_PROMPT 4.6.4: "A per-service lock with a 30-minute expiry blocks a second chain while one is
running. Freestyle chains trigger only their first job; later jobs come from downstream triggers.
Cancelling a chain cancels queued members and stops the running one."

**The lock is a row.** A ``chains`` row with status RUNNING is the lock, and a partial unique index
allows one per service (D-047), so two approvals racing for the same service cannot both win even
if both checked first. After 30 minutes a running chain no longer blocks: the next claim marks it
EXPIRED and takes the lock.

**Tracking reads the database, not memory.** Each tick looks at every RUNNING chain and decides
from its stored runs what happens next:

* The newest run is still building: wait. The run tracker updates its result.
* It succeeded and is not the last job: find the next job's build through its ``UpstreamCause``,
  which the downstream trigger recorded, and record it as the chain's next run. Not there yet
  means it is still queued: look again next tick.
* It succeeded and is the last: the chain succeeded.
* Anything else: the chain stopped there. A failed test means the deploy job never starts, which
  is what the failing-branch acceptance check asserts.

Because the state is in the database, a backend restart loses nothing: a chain whose first build
was never recorded is found again through the queue item stored on the chain.

**Stage tracking** for a Pipeline comes from the stage view (``wfapi/describe``), read on demand for
the run card and polled by the tracker so stage changes reach the WebSocket.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.policy import RunningChain
from app.core.errors import ApiError, ErrorCode, conflict, forbidden, not_found
from app.core.logging import get_logger
from app.db.models import (
    AuditLog,
    Chain,
    ChainStatus,
    Job,
    JobRun,
    Role,
    RunResult,
    User,
)
from app.services.auth import role_allows
from app.services.jenkins import JenkinsClient, JenkinsError, StageInfo
from app.services.plugin import PluginClient

logger = get_logger(__name__)

# 4.6.4: "a per-service lock with a 30-minute expiry".
LOCK_MINUTES: Final = 30

# How many running chains one tick advances; the rest wait for the next tick.
MAX_CHAINS_PER_TICK: Final = 50

CHAIN_CANCELLED_AUDIT_ACTION: Final = "chain.cancelled"
CHAIN_RERUN_AUDIT_ACTION: Final = "chain.rerun"
# The policy layer's own action for this refusal (app/ai/policy.py), so both are counted together.
CHAIN_RUNNING_AUDIT_ACTION: Final = "policy.chain_running"
CANCEL_REFUSED_AUDIT_ACTION: Final = "chain.cancel_refused"

# The results T5.9 can explain: a build that ran and did not pass.
FAILED_RESULTS: Final = frozenset({RunResult.FAILURE.value, RunResult.UNSTABLE.value})


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite drops the offset on a round trip; treat a naive timestamp as UTC."""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=UTC)


def _iso(moment: datetime | None) -> str | None:
    aware = _aware(moment)
    return aware.isoformat() if aware is not None else None


# ---------------------------------------------------------------------------
# The lock
# ---------------------------------------------------------------------------


async def _running_row(session: AsyncSession, service: str, *, lock: bool = False) -> Chain | None:
    statement = select(Chain).where(
        Chain.service == service, Chain.status == ChainStatus.RUNNING.value
    )
    if lock:
        statement = statement.with_for_update()
    return (await session.scalars(statement.order_by(Chain.started_at.desc()).limit(1))).first()


def _lock_held(chain: Chain) -> bool:
    expires = _aware(chain.lock_expires_at)
    return expires is not None and expires > _now()


async def running_chain(session: AsyncSession, service: str) -> RunningChain | None:
    """The chain holding the service's lock, for the policy (4.5.5). An expired one does not."""
    chain = await _running_row(session, service)
    if chain is None or not _lock_held(chain):
        return None
    return RunningChain(service=service, chain_id=chain.id, started_by=chain.started_by)


async def claim(
    session: AsyncSession,
    *,
    service: str,
    job_type: str,
    jobs: list[str],
    parameters: dict[str, str],
    user: User,
    pipeline_id: str | None = None,
    position: int = 0,
) -> Chain:
    """Take the service's lock with a new RUNNING chain, or refuse while another holds it."""
    existing = await _running_row(session, service, lock=True)
    if existing is not None:
        if _lock_held(existing):
            can_cancel = Role(user.role) is Role.ADMIN
            # A policy denial (4.5.5), audited in the shape app/ai/policy.py uses for the same
            # refusal at parse time, so the two are counted together; "at" tells them apart.
            session.add(
                AuditLog(
                    actor_id=user.id,
                    action=CHAIN_RUNNING_AUDIT_ACTION,
                    target=service,
                    details={"role": user.role, "chain_id": existing.id, "at": "approval"},
                )
            )
            raise conflict(
                ErrorCode.CHAIN_ALREADY_RUNNING,
                f"A chain is already running for {service}. "
                + (
                    "Cancel it first to start this one." if can_cancel else "Wait for it to finish."
                ),
                chain_id=existing.id,
                can_cancel=can_cancel,
            )
        existing.status = ChainStatus.EXPIRED.value
        existing.finished_at = _now()
        logger.info("chain_lock_expired", chain_id=existing.id, service=service)
        await session.flush()

    started = _now()
    chain = Chain(
        pipeline_id=pipeline_id,
        service=service,
        job_type=job_type,
        status=ChainStatus.RUNNING.value,
        jobs=list(jobs),
        position=position,
        parameters=dict(parameters),
        started_by=user.id,
        started_at=started,
        lock_expires_at=started + timedelta(minutes=LOCK_MINUTES),
    )
    session.add(chain)
    await session.flush()
    return chain


def finish(chain: Chain, status: ChainStatus) -> None:
    chain.status = status.value
    chain.finished_at = _now()


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainEvent:
    """Something to publish: a chain moved on or finished."""

    chain_id: str
    status: str
    position: int
    job: str | None = None
    build_number: int | None = None


async def _job(session: AsyncSession, name: str) -> Job | None:
    return (await session.scalars(select(Job).where(Job.jenkins_name == name))).first()


async def _record_run(
    session: AsyncSession, *, chain: Chain, job: Job, build_number: int, queue_item_id: int | None
) -> JobRun:
    """The run for (job, build), created or claimed for this chain. Idempotent."""
    run = (
        await session.scalars(
            select(JobRun).where(JobRun.job_id == job.id, JobRun.build_number == build_number)
        )
    ).first()
    if run is None:
        run = JobRun(
            job_id=job.id,
            build_number=build_number,
            queue_item_id=queue_item_id,
            chain_id=chain.id,
            result=RunResult.RUNNING.value,
        )
        session.add(run)
        await session.flush()
    elif run.chain_id is None:
        run.chain_id = chain.id
    return run


async def chain_runs(session: AsyncSession, chain: Chain) -> dict[str, JobRun]:
    """The chain's runs, by job name. One run per job per chain."""
    rows = (
        await session.execute(
            select(JobRun, Job.jenkins_name)
            .join(Job, JobRun.job_id == Job.id)
            .where(JobRun.chain_id == chain.id)
            .order_by(JobRun.created_at)
        )
    ).all()
    return {name: run for run, name in rows}


async def not_started_after(session: AsyncSession, chain: Chain, job_name: str) -> tuple[str, ...]:
    """The chain's jobs after ``job_name`` that never ran: what a failure there stopped.

    Read from the chain's own runs, so a deploy is listed only if it truly has no run -- which is
    the Phase 5 acceptance itself, "the freestyle deploy job never starts", seen from the database.
    """
    if job_name not in chain.jobs:
        return ()
    runs = await chain_runs(session, chain)
    later = chain.jobs[chain.jobs.index(job_name) + 1 :]
    return tuple(name for name in later if name not in runs)


async def advance_all(session: AsyncSession, jenkins: JenkinsClient) -> list[ChainEvent]:
    """One tick's worth of chain decisions."""
    chains = (
        await session.scalars(
            select(Chain)
            .where(Chain.status == ChainStatus.RUNNING.value)
            .order_by(Chain.started_at)
            .limit(MAX_CHAINS_PER_TICK)
        )
    ).all()
    events: list[ChainEvent] = []
    for chain in chains:
        try:
            event = await advance(session, jenkins, chain)
        except JenkinsError as exc:
            logger.info("chain_advance_unavailable", chain_id=chain.id, error=str(exc)[:200])
            continue
        if event is not None:
            events.append(event)
    return events


async def advance(session: AsyncSession, jenkins: JenkinsClient, chain: Chain) -> ChainEvent | None:
    """Decide what happens next for one chain. Returns an event when something changed."""
    runs = await chain_runs(session, chain)
    if not runs:
        return await _find_first_build(session, jenkins, chain)

    current_name = chain.jobs[chain.position]
    current = runs.get(current_name)
    if current is None:
        return None
    if current.result == RunResult.RUNNING.value:
        return None
    if current.result != RunResult.SUCCESS.value:
        # A failed, unstable or aborted job stops the chain: its SUCCESS-only trigger never fires.
        status = (
            ChainStatus.ABORTED
            if current.result == RunResult.ABORTED.value
            else ChainStatus.FAILURE
        )
        finish(chain, status)
        return ChainEvent(
            chain.id, chain.status, chain.position, current_name, current.build_number
        )
    if chain.position + 1 >= len(chain.jobs):
        finish(chain, ChainStatus.SUCCESS)
        return ChainEvent(
            chain.id, chain.status, chain.position, current_name, current.build_number
        )

    next_name = chain.jobs[chain.position + 1]
    number = await jenkins.downstream_build(
        next_name, upstream=current_name, upstream_number=current.build_number
    )
    if number is None:
        return None  # still queued, or the trigger has not fired yet
    job = await _job(session, next_name)
    if job is None:
        logger.warning("chain_job_missing", chain_id=chain.id, job=next_name)
        return None
    await _record_run(session, chain=chain, job=job, build_number=number, queue_item_id=None)
    chain.position += 1
    return ChainEvent(chain.id, chain.status, chain.position, next_name, number)


async def _find_first_build(
    session: AsyncSession, jenkins: JenkinsClient, chain: Chain
) -> ChainEvent | None:
    """The first job's build, found through the queue item stored on the chain."""
    if chain.queue_item_id is None:
        return None
    item = await jenkins.queue_item(chain.queue_item_id)
    if item.cancelled:
        finish(chain, ChainStatus.ABORTED)
        return ChainEvent(chain.id, chain.status, chain.position)
    if item.build_number is None:
        return None
    name = chain.jobs[chain.position]
    job = await _job(session, name)
    if job is None:
        return None
    await _record_run(
        session, chain=chain, job=job, build_number=item.build_number, queue_item_id=item.id
    )
    return ChainEvent(chain.id, chain.status, chain.position, name, item.build_number)


# ---------------------------------------------------------------------------
# The run card
# ---------------------------------------------------------------------------


async def get_chain(session: AsyncSession, chain_id: str) -> Chain:
    chain = await session.get(Chain, chain_id)
    if chain is None:
        raise not_found(ErrorCode.RUN_NOT_FOUND, "No such chain.", chain_id=chain_id)
    return chain


def _run_view(run: JobRun | None, url: str | None = None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "build_number": run.build_number,
        "result": run.result,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "duration_ms": run.duration_ms,
        "queue_wait_ms": run.queue_wait_ms,
        # 4.7.4: the run card ends with "result with duration and a Jenkins link". The URL is the
        # one Jenkins itself reports, so it follows the controller's configured root URL.
        "url": url,
    }


async def build_url(jenkins: JenkinsClient | None, name: str, run: JobRun) -> str | None:
    """The URL Jenkins reports for ``run``'s build, or None when it cannot say."""
    if jenkins is None or run.build_number <= 0:
        return None
    try:
        return (await jenkins.build(name, run.build_number)).url or None
    except JenkinsError:
        return None


async def run_card(
    session: AsyncSession,
    chain: Chain,
    *,
    jenkins: JenkinsClient | None = None,
    plugin: PluginClient | None = None,
) -> dict[str, Any]:
    """4.7.4's run card: queue position, score and waiting reason, stage progress, the result."""
    runs = await chain_runs(session, chain)
    queued: set[str] = set()
    if jenkins is not None and chain.status == ChainStatus.RUNNING.value:
        try:
            queued = {item.job_name or "" for item in await jenkins.queued_items()}
        except JenkinsError:
            queued = set()

    jobs = []
    for position, name in enumerate(chain.jobs):
        run = runs.get(name)
        if run is not None:
            state = run.result.lower()
        elif name in queued:
            state = "queued"
        elif chain.status == ChainStatus.RUNNING.value and position >= chain.position:
            state = "waiting"
        else:
            state = "not_started"
        url = await build_url(jenkins, name, run) if run is not None else None
        jobs.append(
            {"name": name, "position": position, "state": state, "run": _run_view(run, url)}
        )

    stages: list[dict[str, Any]] = []
    if chain.job_type == "PIPELINE" and jenkins is not None:
        run = runs.get(chain.jobs[0])
        if run is not None:
            try:
                stages = [
                    _stage_view(stage)
                    for stage in await jenkins.pipeline_stages(chain.jobs[0], run.build_number)
                ]
            except JenkinsError:
                stages = []

    queue = None
    if plugin is not None and chain.status == ChainStatus.RUNNING.value:
        ranking = await plugin.ranking()
        names = set(chain.jobs)
        for item in ranking.items:
            if item.job_name in names:
                queue = {
                    "job": item.job_name,
                    "rank": item.rank,
                    "score": item.score,
                    "level": item.level,
                    "components": {
                        "urgency": item.components.urgency,
                        "dependency": item.components.dependency,
                        "execution_time": item.components.execution_time,
                        "aging_bonus": item.components.aging_bonus,
                    },
                    "waiting_reason": item.blocked_reason,
                    "wait_seconds": item.wait_seconds,
                }
                break

    total = sum(run.duration_ms or 0 for run in runs.values())
    # T5.9: the run "Explain failure" explains -- the first job in chain order that failed.
    failed = next(
        (runs[name] for name in chain.jobs if name in runs and runs[name].result in FAILED_RESULTS),
        None,
    )
    return {
        "id": chain.id,
        "pipeline_id": chain.pipeline_id,
        "service": chain.service,
        "job_type": chain.job_type,
        "status": chain.status,
        "position": chain.position,
        "parameters": chain.parameters,
        "started_at": _iso(chain.started_at),
        "finished_at": _iso(chain.finished_at),
        "lock_expires_at": _iso(chain.lock_expires_at),
        "duration_ms": total or None,
        "jobs": jobs,
        "stages": stages,
        "queue": queue,
        "failed_run_id": failed.id if failed is not None else None,
    }


def _stage_view(stage: StageInfo) -> dict[str, Any]:
    return {"name": stage.name, "status": stage.status, "duration_ms": stage.duration_ms}


async def latest_chain(
    session: AsyncSession, *, user: User, service: str | None = None
) -> Chain | None:
    """The user's most recent chain, for "What's the status of my last deploy?" (4.6.5)."""
    statement = select(Chain).where(Chain.started_by == user.id)
    if service is not None:
        statement = statement.where(Chain.service == service)
    return (await session.scalars(statement.order_by(Chain.started_at.desc()).limit(1))).first()


# ---------------------------------------------------------------------------
# Cancelling
# ---------------------------------------------------------------------------


async def cancel(
    session: AsyncSession, *, jenkins: JenkinsClient, chain: Chain, actor: User
) -> dict[str, Any]:
    """4.6.4: "Cancelling a chain cancels queued members and stops the running one."

    The person who started the chain may cancel it, and so may DevOps and Admin (4.5.5's Admin
    "may cancel the running chain first").
    """
    if chain.started_by != actor.id and not role_allows(Role(actor.role), Role.DEVOPS):
        # A denial, audited and committed before the refusal rolls the session back (D-022):
        # nothing else has been written by this request.
        session.add(
            AuditLog(
                actor_id=actor.id,
                action=CANCEL_REFUSED_AUDIT_ACTION,
                target=f"chain:{chain.id}",
                details={"role": actor.role, "service": chain.service},
            )
        )
        await session.commit()
        raise forbidden(
            ErrorCode.FORBIDDEN,
            "Only the person who started this chain, or DevOps and Admin, can cancel it.",
        )
    if chain.status != ChainStatus.RUNNING.value:
        raise conflict(
            ErrorCode.VALIDATION_FAILED,
            f"This chain already finished with {chain.status}; there is nothing to cancel.",
            chain_id=chain.id,
        )

    dequeued: list[str] = []
    stopped: list[str] = []
    try:
        names = set(chain.jobs)
        for item in await jenkins.queued_items():
            if item.job_name in names:
                await jenkins.cancel_queue_item(item.id)
                dequeued.append(item.job_name or "")
        if chain.queue_item_id is not None and not await chain_runs(session, chain):
            await jenkins.cancel_queue_item(chain.queue_item_id)
        for name, run in (await chain_runs(session, chain)).items():
            if run.result == RunResult.RUNNING.value and run.build_number > 0:
                await jenkins.stop_build(name, run.build_number)
                stopped.append(f"{name}#{run.build_number}")
    except JenkinsError as exc:
        raise ApiError(
            ErrorCode.JENKINS_UNAVAILABLE,
            "Jenkins did not accept the cancellation. Try again when it answers.",
            status_code=503,
            details={"chain_id": chain.id},
        ) from exc

    finish(chain, ChainStatus.ABORTED)
    result = {"chain_id": chain.id, "dequeued": dequeued, "stopped": stopped}
    session.add(
        AuditLog(
            actor_id=actor.id,
            action=CHAIN_CANCELLED_AUDIT_ACTION,
            target=f"chain:{chain.id}",
            details={**result, "service": chain.service, "role": actor.role},
        )
    )
    await session.flush()
    logger.info("chain_cancelled", **result)
    return result


# ---------------------------------------------------------------------------
# Re-running the last failed test job
# ---------------------------------------------------------------------------


def _is_test_job(name: str) -> bool:
    return "-test-" in name or name.endswith("-test")


async def last_failed_test(
    session: AsyncSession, *, service: str | None
) -> tuple[JobRun, Job, Chain | None] | None:
    """4.6.5: "Re-trigger the last failed test job"."""
    statement = (
        select(JobRun, Job)
        .join(Job, JobRun.job_id == Job.id)
        .where(JobRun.result.in_([RunResult.FAILURE.value, RunResult.UNSTABLE.value]))
        .order_by(JobRun.created_at.desc())
        .limit(50)
    )
    for run, job in (await session.execute(statement)).all():
        if not _is_test_job(job.jenkins_name):
            continue
        if service is not None and not job.jenkins_name.startswith(
            (f"fs-{service}-", f"pl-{service}-")
        ):
            continue
        chain = await session.get(Chain, run.chain_id) if run.chain_id else None
        return run, job, chain
    return None


def _defaults_from_config(config_xml: str) -> dict[str, str]:
    """A job's parameter defaults, read from Jenkins, for a re-run with no chain to copy from."""
    root = ElementTree.fromstring(config_xml)  # noqa: S314 (Jenkins's own config of our own job)
    return {
        definition.findtext("name") or "": definition.findtext("defaultValue") or ""
        for definition in root.iter("hudson.model.StringParameterDefinition")
    }


async def rerun(
    session: AsyncSession,
    *,
    jenkins: JenkinsClient,
    user: User,
    run: JobRun,
    job: Job,
    previous: Chain | None,
    service: str,
) -> tuple[Chain, int]:
    """Start the failed test job again, as a new chain from that job onward.

    From that job onward because that is what Jenkins will do: if the tests pass this time, the
    job's downstream trigger starts the next job, so the chain the user sees is the rest of the
    original one.
    """
    if previous is not None and job.jenkins_name in previous.jobs:
        start = previous.jobs.index(job.jenkins_name)
        jobs = previous.jobs[start:]
        parameters = dict(previous.parameters)
    else:
        jobs = [job.jenkins_name]
        parameters = _defaults_from_config(await jenkins.get_config_xml(job.jenkins_name))
    chain = await claim(
        session,
        service=service,
        job_type=job.job_type,
        jobs=jobs,
        parameters=parameters,
        user=user,
        pipeline_id=previous.pipeline_id if previous is not None else None,
    )
    try:
        queue_item_id = await jenkins.trigger(job.jenkins_name, parameters or None)
    except JenkinsError as exc:
        finish(chain, ChainStatus.ABORTED)
        await session.flush()
        raise ApiError(
            ErrorCode.JENKINS_UNAVAILABLE,
            "Jenkins did not start the re-run. Try again when it answers.",
            status_code=503,
        ) from exc
    chain.queue_item_id = queue_item_id
    session.add(
        AuditLog(
            actor_id=user.id,
            action=CHAIN_RERUN_AUDIT_ACTION,
            target=job.jenkins_name,
            details={"chain_id": chain.id, "failed_build": run.build_number, "jobs": jobs},
        )
    )
    await session.flush()
    return chain, queue_item_id
