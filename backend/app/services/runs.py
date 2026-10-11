"""Jobs and runs: listing, reading, cancelling and log tailing.

BUILD_PROMPT 4.4.4 fixes the endpoints; this module holds the logic so the routers stay thin
(4.4.1).

Two things here are less obvious than they look.

**Cancelling is two different operations.** A run that has not started yet is a queue item and is
cancelled through the queue; a run that is building is stopped through the build. Jenkins exposes
these separately and a caller that guesses wrong gets a 404, so the decision is made here from what
the row says.

**The log is read in windows, not whole.** A long build produces megabytes, and the UI tails it
while it runs. ``console_text`` takes a byte offset, so the API returns a window plus the next
offset and lets the client ask again; returning the whole log on every poll would move the same
megabyte repeatedly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode, conflict, not_found
from app.core.logging import get_logger
from app.db.models import AuditLog, Job, JobRun, RunResult, Service, User
from app.services.jenkins import JenkinsClient, JenkinsError

logger = get_logger(__name__)

# One page of a log. Large enough that a short build arrives in one request, small enough that a
# poll during a long build stays cheap.
LOG_WINDOW_BYTES: Final = 64 * 1024

MAX_PAGE_SIZE: Final = 200
DEFAULT_PAGE_SIZE: Final = 50


@dataclass(frozen=True)
class Page[T]:
    """One page of results, with the total so the UI can show "showing 50 of 312"."""

    items: tuple[T, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class LogWindow:
    text: str
    next_offset: int
    more_data: bool


def clamp_page(limit: int | None, offset: int | None) -> tuple[int, int]:
    """Keep paging within bounds.

    An unbounded ``limit`` would let one request ask for every run ever recorded, which is a slow
    query and a large response for a page that shows twenty rows.
    """
    resolved_limit = DEFAULT_PAGE_SIZE if limit is None else limit
    return max(1, min(resolved_limit, MAX_PAGE_SIZE)), max(0, offset or 0)


async def _count(session: AsyncSession, statement: Select[Any]) -> int:
    """Total rows the statement would return, for the "showing 50 of 312" line.

    ``order_by(None)`` first: an ORDER BY inside a COUNT subquery is work the database does and
    then discards, and PostgreSQL rejects it outright in some wrapped forms.
    """
    subquery = statement.order_by(None).subquery()
    total = await session.scalar(select(func.count()).select_from(subquery))
    return int(total or 0)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


async def list_jobs(
    session: AsyncSession,
    *,
    service: str | None = None,
    job_type: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> Page[Job]:
    """Jobs the orchestrator created, newest first."""
    resolved_limit, resolved_offset = clamp_page(limit, offset)

    statement = select(Job)
    if service:
        statement = statement.join(Service, Job.service_id == Service.id).where(
            Service.name == service
        )
    if job_type:
        statement = statement.where(Job.job_type == job_type.upper())

    total = await _count(session, statement)
    rows = (
        await session.scalars(
            statement.order_by(Job.created_at.desc()).limit(resolved_limit).offset(resolved_offset)
        )
    ).all()
    return Page(items=tuple(rows), total=total, limit=resolved_limit, offset=resolved_offset)


async def get_job(session: AsyncSession, job_id: str) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise not_found(ErrorCode.JOB_NOT_FOUND, "No such job.", job_id=job_id)
    return job


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


async def list_runs(
    session: AsyncSession,
    *,
    job_id: str | None = None,
    result: str | None = None,
    active_only: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> Page[JobRun]:
    """Runs, newest first.

    ``active_only`` is a separate flag rather than ``result=RUNNING`` because "what is happening
    now" is the dashboard's first question and should not depend on knowing that RUNNING is the
    sentinel for an unfinished run.
    """
    resolved_limit, resolved_offset = clamp_page(limit, offset)

    statement = select(JobRun)
    if job_id:
        statement = statement.where(JobRun.job_id == job_id)
    if active_only:
        statement = statement.where(JobRun.result == RunResult.RUNNING.value)
    elif result:
        statement = statement.where(JobRun.result == result.upper())

    total = await _count(session, statement)
    rows = (
        await session.scalars(
            statement.order_by(JobRun.created_at.desc())
            .limit(resolved_limit)
            .offset(resolved_offset)
        )
    ).all()
    return Page(items=tuple(rows), total=total, limit=resolved_limit, offset=resolved_offset)


async def get_run(session: AsyncSession, run_id: str) -> JobRun:
    run = await session.get(JobRun, run_id)
    if run is None:
        raise not_found(ErrorCode.RUN_NOT_FOUND, "No such run.", run_id=run_id)
    return run


async def job_names_for(session: AsyncSession, runs: tuple[JobRun, ...]) -> dict[str, str]:
    """Jenkins names for a page of runs, in one query rather than one per row."""
    job_ids = {run.job_id for run in runs}
    if not job_ids:
        return {}
    rows = (await session.scalars(select(Job).where(Job.id.in_(job_ids)))).all()
    return {job.id: job.jenkins_name for job in rows}


# ---------------------------------------------------------------------------
# Cancelling
# ---------------------------------------------------------------------------


async def cancel_run(
    session: AsyncSession,
    jenkins: JenkinsClient,
    *,
    run: JobRun,
    actor: User,
) -> str:
    """Cancel a queued run or stop a building one. Returns what was done.

    Already-finished runs are refused rather than silently accepted: "cancelled" and "it had
    already failed" lead to different next actions, and reporting success for a no-op hides which
    happened.
    """
    if run.result != RunResult.RUNNING.value:
        raise conflict(
            ErrorCode.VALIDATION_FAILED,
            f"This run already finished with {run.result}; there is nothing to cancel.",
            run_id=run.id,
            result=run.result,
        )

    job = await get_job(session, run.job_id)

    # A run with no build number has not left the queue, so the queue item is what to cancel.
    try:
        if run.build_number <= 0 and run.queue_item_id is not None:
            await jenkins.cancel_queue_item(run.queue_item_id)
            action = "dequeued"
        else:
            await jenkins.stop_build(job.jenkins_name, run.build_number)
            action = "stopped"
    except JenkinsError as exc:
        logger.warning("cancel_failed", run_id=run.id, job=job.jenkins_name, error=str(exc)[:200])
        raise conflict(
            ErrorCode.JENKINS_UNAVAILABLE,
            "Jenkins would not cancel this run. It may have finished in the meantime.",
            run_id=run.id,
        ) from exc

    run.result = RunResult.ABORTED.value
    run.finished_at = datetime.now(UTC)

    # 4.4.3 requires an audit entry for anything worth asking "who did that?" about, and
    # cancelling someone else's build is exactly that.
    session.add(
        AuditLog(
            actor_id=actor.id,
            action="run.cancelled",
            target=f"{job.jenkins_name}#{run.build_number}",
            details={"runId": run.id, "action": action, "role": actor.role},
        )
    )
    logger.info("run_cancelled", run_id=run.id, job=job.jenkins_name, action=action)
    return action


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


async def run_log(
    session: AsyncSession,
    jenkins: JenkinsClient,
    *,
    run: JobRun,
    start: int = 0,
) -> LogWindow:
    """A window of a run's console output, starting at a byte offset.

    A run that never got a build number has no log yet; that is reported as an empty window rather
    than an error, because the UI opens the log view as soon as a run appears.
    """
    if run.build_number <= 0:
        return LogWindow(text="", next_offset=0, more_data=run.result == RunResult.RUNNING.value)

    job = await get_job(session, run.job_id)
    offset = max(0, start)

    try:
        text = await jenkins.console_text(job.jenkins_name, run.build_number, offset)
    except JenkinsError as exc:
        raise conflict(
            ErrorCode.JENKINS_UNAVAILABLE,
            "The log could not be read from Jenkins just now.",
            run_id=run.id,
        ) from exc

    window = text[:LOG_WINDOW_BYTES]
    return LogWindow(
        text=window,
        next_offset=offset + len(window.encode("utf-8", "replace")),
        # More to come either because this window was truncated, or because the build is still
        # producing output.
        more_data=len(text) > LOG_WINDOW_BYTES or run.result == RunResult.RUNNING.value,
    )
