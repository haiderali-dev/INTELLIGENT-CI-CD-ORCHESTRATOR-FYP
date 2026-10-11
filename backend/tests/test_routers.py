"""Jobs, runs, queue, services, analytics and admin.

The tests worth having here are about the decisions, not the plumbing: that cancelling picks the
right Jenkins operation from the run's own state, that an unavailable plugin is a 200 saying so
rather than a 500, that statistics report null where nothing was measured, and that the admin
surface audits its own use and cannot be used to lock out the last administrator.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import ROLE_ORDER
from app.core.security import hash_password
from app.db.models import (
    AuditLog,
    Experiment,
    ExperimentMetric,
    Job,
    JobRun,
    Role,
    RunResult,
    User,
)
from app.services.auth import role_allows
from app.services.jenkins import FakeJenkinsClient, JenkinsError
from app.services.plugin import FakePluginClient, RankedItem, Ranking, ScoreComponents

PASSWORD = "correct-horse-battery-staple"


async def make_user(
    db: AsyncSession, *, email: str = "dev@example.com", role: Role = Role.DEVELOPER
) -> User:
    user = User(email=email, password_hash=hash_password(PASSWORD), role=role.value, active=True)
    db.add(user)
    await db.commit()
    return user


async def token_for(
    client: AsyncClient, db: AsyncSession, *, role: Role = Role.DEVELOPER, email: str | None = None
) -> str:
    address = email or f"{role.value.lower()}@example.com"
    await make_user(db, email=address, role=role)
    response = await client.post("/api/auth/login", json={"email": address, "password": PASSWORD})
    assert response.status_code == 200, response.text
    token: str = response.json()["access_token"]
    return token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_job(db: AsyncSession, name: str = "payment-service-build") -> Job:
    job = Job(jenkins_name=name, job_type="FREESTYLE", priority_level="HIGH")
    db.add(job)
    await db.commit()
    return job


async def make_run(
    db: AsyncSession,
    job: Job,
    *,
    build: int = 1,
    result: str = RunResult.RUNNING.value,
    queue_item_id: int | None = None,
    queue_wait_ms: int | None = None,
    duration_ms: int | None = None,
) -> JobRun:
    run = JobRun(
        job_id=job.id,
        build_number=build,
        result=result,
        queue_item_id=queue_item_id,
        queue_wait_ms=queue_wait_ms,
        duration_ms=duration_ms,
    )
    db.add(run)
    await db.commit()
    return run


# ---------------------------------------------------------------------------
# Authentication is required everywhere
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/jobs"),
        ("get", "/api/runs"),
        ("get", "/api/queue"),
        ("get", "/api/services"),
        ("get", "/api/analytics/runs"),
        ("get", "/api/analytics/experiments"),
        ("get", "/api/admin/users"),
        ("get", "/api/admin/audit"),
        ("get", "/api/admin/policy"),
    ],
)
async def test_every_endpoint_needs_a_token(client: AsyncClient, method: str, path: str) -> None:
    response = await getattr(client, method)(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


# ---------------------------------------------------------------------------
# Jobs and runs
# ---------------------------------------------------------------------------


async def test_jobs_are_listed_with_dependencies_as_a_list(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Stored comma-separated to match the plugin property (D-011); the API must not leak that."""
    token = await token_for(client, db)
    job = await make_job(db)
    job.depends_on = "a-job,b-job"
    await db.commit()

    response = await client.get("/api/jobs", headers=auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["depends_on"] == ["a-job", "b-job"]


async def test_a_job_with_no_dependencies_is_an_empty_list_not_one_empty_string(
    client: AsyncClient, db: AsyncSession
) -> None:
    """``"".split(",")`` is ``[""]``, which would render as a dependency on a nameless job."""
    token = await token_for(client, db)
    await make_job(db)

    response = await client.get("/api/jobs", headers=auth(token))

    assert response.json()["items"][0]["depends_on"] == []


async def test_runs_carry_their_job_name(client: AsyncClient, db: AsyncSession) -> None:
    """Otherwise the Runs page needs one request per row to say what ran."""
    token = await token_for(client, db)
    job = await make_job(db)
    await make_run(db, job)

    response = await client.get("/api/runs", headers=auth(token))

    assert response.json()["items"][0]["job_name"] == "payment-service-build"


async def test_active_runs_can_be_asked_for_without_knowing_the_sentinel(
    client: AsyncClient, db: AsyncSession
) -> None:
    """ "What is happening now" should not require knowing that RUNNING means unfinished."""
    token = await token_for(client, db)
    job = await make_job(db)
    await make_run(db, job, build=1, result=RunResult.SUCCESS.value)
    await make_run(db, job, build=2, result=RunResult.RUNNING.value)

    response = await client.get("/api/runs?active=true", headers=auth(token))

    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["build_number"] == 2


async def test_the_page_size_is_capped(client: AsyncClient, db: AsyncSession) -> None:
    """An unbounded limit would let one request ask for every run ever recorded."""
    token = await token_for(client, db)

    response = await client.get("/api/runs?limit=100000", headers=auth(token))

    assert response.status_code == 422


async def test_an_unknown_run_is_a_clean_404(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db)

    response = await client.get("/api/runs/no-such-run", headers=auth(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_NOT_FOUND"


# ---------------------------------------------------------------------------
# Cancelling
# ---------------------------------------------------------------------------


async def test_cancelling_needs_devops(client: AsyncClient, db: AsyncSession) -> None:
    """4.5.5 says a Developer may not cancel a running chain, so stopping a build is not theirs."""
    token = await token_for(client, db, role=Role.DEVELOPER)
    job = await make_job(db)
    run = await make_run(db, job)

    response = await client.post(f"/api/runs/{run.id}/cancel", headers=auth(token))

    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_role"] == "DEVOPS"


async def test_a_queued_run_is_dequeued_not_stopped(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient
) -> None:
    """Jenkins exposes these separately; guessing wrong gives a 404."""
    token = await token_for(client, db, role=Role.DEVOPS)
    job = await make_job(db)
    run = await make_run(db, job, build=0, queue_item_id=4242)
    cancelled: list[int] = []

    async def cancel_queue_item(item_id: int) -> None:
        cancelled.append(item_id)

    fake_jenkins.cancel_queue_item = cancel_queue_item  # type: ignore[assignment]

    response = await client.post(f"/api/runs/{run.id}/cancel", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["action"] == "dequeued"
    assert cancelled == [4242]


async def test_a_building_run_is_stopped_not_dequeued(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient
) -> None:
    token = await token_for(client, db, role=Role.DEVOPS)
    job = await make_job(db)
    run = await make_run(db, job, build=7)
    stopped: list[tuple[str, int]] = []

    async def stop_build(name: str, number: int) -> None:
        stopped.append((name, number))

    fake_jenkins.stop_build = stop_build  # type: ignore[assignment]

    response = await client.post(f"/api/runs/{run.id}/cancel", headers=auth(token))

    assert response.json()["action"] == "stopped"
    assert stopped == [("payment-service-build", 7)]


async def test_cancelling_a_finished_run_is_refused_rather_than_a_no_op(
    client: AsyncClient, db: AsyncSession
) -> None:
    """ "Cancelled" and "it had already failed" lead to different next actions."""
    token = await token_for(client, db, role=Role.DEVOPS)
    job = await make_job(db)
    run = await make_run(db, job, result=RunResult.FAILURE.value)

    response = await client.post(f"/api/runs/{run.id}/cancel", headers=auth(token))

    assert response.status_code == 409
    assert "already finished" in response.json()["error"]["message"]


async def test_cancelling_writes_an_audit_entry(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient
) -> None:
    """Stopping someone else's build is exactly a "who did that?" question (4.4.3)."""
    token = await token_for(client, db, role=Role.DEVOPS)
    job = await make_job(db)
    run = await make_run(db, job, build=7)

    async def stop_build(name: str, number: int) -> None:
        return None

    fake_jenkins.stop_build = stop_build  # type: ignore[assignment]
    await client.post(f"/api/runs/{run.id}/cancel", headers=auth(token))

    entries = (await db.scalars(select(AuditLog).where(AuditLog.action == "run.cancelled"))).all()
    assert len(entries) == 1
    assert entries[0].target == "payment-service-build#7"


async def test_a_jenkins_refusal_is_reported_as_a_conflict(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient
) -> None:
    """It may have finished between the page loading and the click."""
    token = await token_for(client, db, role=Role.DEVOPS)
    job = await make_job(db)
    run = await make_run(db, job, build=7)

    async def stop_build(name: str, number: int) -> None:
        raise JenkinsError("gone")

    fake_jenkins.stop_build = stop_build  # type: ignore[assignment]

    response = await client.post(f"/api/runs/{run.id}/cancel", headers=auth(token))

    assert response.status_code == 409
    await db.refresh(run)
    # Not marked aborted: Jenkins never agreed to abort it.
    assert run.result == RunResult.RUNNING.value


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


async def test_a_run_without_a_build_number_has_an_empty_log(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The UI opens the log view as soon as a run appears, before Jenkins assigns a number."""
    token = await token_for(client, db)
    job = await make_job(db)
    run = await make_run(db, job, build=0)

    response = await client.get(f"/api/runs/{run.id}/log", headers=auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == ""
    assert body["more_data"] is True


async def test_the_log_returns_an_offset_to_continue_from(
    client: AsyncClient, db: AsyncSession, fake_jenkins: FakeJenkinsClient
) -> None:
    """Windowed, so tailing a long build does not move the same megabyte each poll."""
    token = await token_for(client, db)
    job = await make_job(db)
    run = await make_run(db, job, build=3, result=RunResult.SUCCESS.value)

    async def console_text(name: str, number: int, start: int = 0) -> str:
        return "hello world"[start:]

    fake_jenkins.console_text = console_text  # type: ignore[assignment]

    response = await client.get(f"/api/runs/{run.id}/log?start=6", headers=auth(token))

    body = response.json()
    assert body["text"] == "world"
    assert body["next_offset"] == 11
    assert body["more_data"] is False


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


async def test_the_queue_reports_the_plugin_ranking(
    client: AsyncClient, db: AsyncSession, fake_plugin: FakePluginClient
) -> None:
    token = await token_for(client, db)
    fake_plugin.ranking_result = Ranking(
        available=True,
        optimizer_enabled=True,
        weights={"urgency": 0.5, "dependency": 0.3, "executionTime": 0.2},
        items=(
            RankedItem(
                rank=1,
                item_id=11,
                job_name="payment-service-build",
                level="HIGH",
                score=0.667,
                components=ScoreComponents(
                    urgency=1.0, dependency=0.5, execution_time=0.335, base_score=0.667
                ),
                wait_seconds=3.0,
                group_id="payment-service",
            ),
        ),
    )

    response = await client.get("/api/queue", headers=auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["queue_length"] == 1
    assert body["items"][0]["components"]["urgency"] == 1.0
    assert body["weights"]["urgency"] == 0.5


async def test_a_missing_plugin_is_a_200_not_a_500(
    client: AsyncClient, db: AsyncSession, fake_plugin: FakePluginClient
) -> None:
    """jenkins-baseline runs without the plugin on purpose; the page must still render."""
    token = await token_for(client, db)
    fake_plugin.set_unavailable("the plugin is not installed on this controller")

    response = await client.get("/api/queue", headers=auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["items"] == []
    assert "not installed" in body["unavailable_reason"]


async def test_an_empty_queue_is_distinct_from_an_unreadable_one(
    client: AsyncClient, db: AsyncSession, fake_plugin: FakePluginClient
) -> None:
    """ "Nothing queued" and "cannot tell" are different answers."""
    token = await token_for(client, db)
    fake_plugin.ranking_result = Ranking(available=True, optimizer_enabled=True, items=())

    body = (await client.get("/api/queue", headers=auth(token))).json()

    assert body["available"] is True
    assert body["queue_length"] == 0


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


async def test_services_come_from_the_catalog_with_their_enums(
    client: AsyncClient, db: AsyncSession
) -> None:
    """4.5.2 builds the intent schema from these, so the pickers cannot drift from the model."""
    token = await token_for(client, db)

    response = await client.get("/api/services", headers=auth(token))

    assert response.status_code == 200
    body = response.json()
    assert {service["name"] for service in body["items"]} >= {
        "payment-service",
        "auth-service",
    }
    assert "unit" in body["suite_names"]
    assert body["environments"] == ["staging"]


async def test_the_service_response_never_includes_a_shell_command(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The commands are the one security-relevant part of the catalog and nothing in the UI runs
    them, so handing them out would widen the blast radius of a stolen read-only token."""
    token = await token_for(client, db)

    body = (await client.get("/api/services", headers=auth(token))).json()

    serialised = str(body)
    assert "./scripts/build.sh" not in serialised
    assert "command" not in serialised


async def test_branches_come_from_the_live_remote(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db)

    response = await client.get("/api/services/payment-service/branches", headers=auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert "main" in body["branches"]
    assert "demo/failing-tests" in body["branches"]


async def test_an_unreachable_repository_is_reported_not_raised(
    client: AsyncClient, db: AsyncSession, fake_git: object
) -> None:
    """The two sample repositories are not pushed yet; a picker that errors is less useful."""
    from app.services.git import GitError

    token = await token_for(client, db)
    fake_git.fail_with = GitError("repository not found")  # type: ignore[attr-defined]

    response = await client.get("/api/services/payment-service/branches", headers=auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["branches"] == []
    assert body["default_branch"] == "main"


async def test_an_unknown_service_is_a_404(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db)

    response = await client.get("/api/services/nope/branches", headers=auth(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SERVICE_NOT_FOUND"


async def test_resync_needs_admin(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db, role=Role.DEVOPS)

    response = await client.post("/api/services/resync", headers=auth(token))

    assert response.status_code == 403


async def test_resync_mirrors_the_catalog_into_the_table(
    client: AsyncClient, db: AsyncSession
) -> None:
    """One direction only, file to table: the YAML stays the source of truth (4.6.1)."""
    token = await token_for(client, db, role=Role.ADMIN)

    response = await client.post("/api/services/resync", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["created"] >= 2

    again = await client.post("/api/services/resync", headers=auth(token))
    assert again.json() == {"created": 0, "updated": 0}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


async def test_statistics_report_null_where_nothing_was_measured(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Zero is a measurement; null is the absence of one, and a chart must not draw them alike."""
    token = await token_for(client, db)

    body = (await client.get("/api/analytics/runs", headers=auth(token))).json()

    assert body["total_runs"] == 0
    assert body["mean_queue_wait_ms"] is None
    assert body["mean_duration_ms"] is None
    assert body["success_rate"] is None


async def test_a_zero_queue_wait_is_not_treated_as_missing(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A build that started immediately really waited 0 ms, and that is data."""
    token = await token_for(client, db)
    job = await make_job(db)
    await make_run(db, job, result=RunResult.SUCCESS.value, queue_wait_ms=0)

    body = (await client.get("/api/analytics/runs", headers=auth(token))).json()

    assert body["mean_queue_wait_ms"] == 0.0
    assert body["runs_with_queue_wait"] == 1


async def test_the_success_rate_ignores_runs_still_building(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Counting them would make reliability appear to drop whenever a build starts."""
    token = await token_for(client, db)
    job = await make_job(db)
    await make_run(db, job, build=1, result=RunResult.SUCCESS.value)
    await make_run(db, job, build=2, result=RunResult.FAILURE.value)
    await make_run(db, job, build=3, result=RunResult.RUNNING.value)

    body = (await client.get("/api/analytics/runs", headers=auth(token))).json()

    assert body["running"] == 1
    assert body["success_rate"] == 0.5


async def test_durations_average_only_over_finished_runs(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A running build's duration is not a duration yet."""
    token = await token_for(client, db)
    job = await make_job(db)
    await make_run(db, job, build=1, result=RunResult.SUCCESS.value, duration_ms=1000)
    await make_run(db, job, build=2, result=RunResult.RUNNING.value, duration_ms=999_999)

    body = (await client.get("/api/analytics/runs", headers=auth(token))).json()

    assert body["mean_duration_ms"] == 1000.0


async def test_experiment_metrics_are_returned_as_stored(
    client: AsyncClient, db: AsyncSession
) -> None:
    """4.4.3: no aggregate is stored, and these rows are what the harness computed."""
    token = await token_for(client, db)
    experiment = Experiment(label="run-1", mode="optimized", workload="mixed-30")
    db.add(experiment)
    await db.commit()
    db.add(
        ExperimentMetric(
            experiment_id=experiment.id,
            name="mean_wait",
            band="HIGH",
            value=12.5,
            unit="s",
            std_dev=1.5,
            sample_size=9,
        )
    )
    await db.commit()

    response = await client.get(f"/api/analytics/experiments/{experiment.id}", headers=auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["label"] == "run-1"
    assert body["metrics"][0]["value"] == 12.5
    assert body["metrics"][0]["std_dev"] == 1.5
    assert body["metrics"][0]["sample_size"] == 9


async def test_experiments_can_be_filtered_by_mode(client: AsyncClient, db: AsyncSession) -> None:
    """The report compares baseline against optimized, so that filter is the common case."""
    token = await token_for(client, db)
    db.add(Experiment(label="a", mode="baseline", workload="mixed-30"))
    db.add(Experiment(label="b", mode="optimized", workload="mixed-30"))
    await db.commit()

    body = (
        await client.get("/api/analytics/experiments?mode=optimized", headers=auth(token))
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["label"] == "b"


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


async def test_admin_endpoints_refuse_devops(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db, role=Role.DEVOPS)

    response = await client.get("/api/admin/users", headers=auth(token))

    assert response.status_code == 403
    assert response.json()["error"]["details"]["required_role"] == "ADMIN"


async def test_creating_a_user_writes_an_audit_entry(client: AsyncClient, db: AsyncSession) -> None:
    """4.4.3 requires an entry for admin changes; an unaudited admin surface is the worst place."""
    token = await token_for(client, db, role=Role.ADMIN)

    response = await client.post(
        "/api/admin/users",
        json={
            "email": "New.Person@Example.com",
            "password": "a-long-enough-password",
            "role": "DEVOPS",
        },
        headers=auth(token),
    )

    assert response.status_code == 201
    assert response.json()["email"] == "new.person@example.com"
    entries = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "admin.user.created"))
    ).all()
    assert len(entries) == 1


async def test_a_short_password_is_refused_at_creation(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A floor here, unlike at sign-in: this is the moment a password is chosen."""
    token = await token_for(client, db, role=Role.ADMIN)

    response = await client.post(
        "/api/admin/users",
        json={"email": "x@example.com", "password": "short"},
        headers=auth(token),
    )

    assert response.status_code == 422


async def test_a_duplicate_email_is_a_conflict(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db, role=Role.ADMIN, email="admin@example.com")

    response = await client.post(
        "/api/admin/users",
        json={"email": "admin@example.com", "password": "a-long-enough-password"},
        headers=auth(token),
    )

    assert response.status_code == 409


async def test_an_admin_cannot_deactivate_themselves(client: AsyncClient, db: AsyncSession) -> None:
    """The last admin locking themselves out leaves no way to grant the role back."""
    token = await token_for(client, db, role=Role.ADMIN, email="admin@example.com")
    admin = await db.scalar(select(User).where(User.email == "admin@example.com"))
    assert admin is not None

    response = await client.patch(
        f"/api/admin/users/{admin.id}", json={"active": False}, headers=auth(token)
    )

    assert response.status_code == 409
    assert "your own administrator access" in response.json()["error"]["message"]


async def test_an_admin_cannot_demote_themselves(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db, role=Role.ADMIN, email="admin@example.com")
    admin = await db.scalar(select(User).where(User.email == "admin@example.com"))
    assert admin is not None

    response = await client.patch(
        f"/api/admin/users/{admin.id}", json={"role": "DEVELOPER"}, headers=auth(token)
    )

    assert response.status_code == 409


async def test_an_admin_can_deactivate_someone_else(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db, role=Role.ADMIN, email="admin@example.com")
    other = await make_user(db, email="other@example.com")

    response = await client.patch(
        f"/api/admin/users/{other.id}", json={"active": False}, headers=auth(token)
    )

    assert response.status_code == 200
    assert response.json()["active"] is False


async def test_an_unchanged_update_writes_no_audit_entry(
    client: AsyncClient, db: AsyncSession
) -> None:
    """An audit log full of no-ops is one nobody reads."""
    token = await token_for(client, db, role=Role.ADMIN, email="admin@example.com")
    other = await make_user(db, email="other@example.com")

    await client.patch(
        f"/api/admin/users/{other.id}", json={"role": "DEVELOPER"}, headers=auth(token)
    )

    entries = (
        await db.scalars(select(AuditLog).where(AuditLog.action == "admin.user.updated"))
    ).all()
    assert entries == []


async def test_the_audit_log_names_the_actor(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db, role=Role.ADMIN, email="admin@example.com")
    await client.post(
        "/api/admin/users",
        json={"email": "someone@example.com", "password": "a-long-enough-password"},
        headers=auth(token),
    )

    body = (await client.get("/api/admin/audit", headers=auth(token))).json()

    created = [entry for entry in body["items"] if entry["action"] == "admin.user.created"]
    assert created
    assert created[0]["actor_email"] == "admin@example.com"


async def test_the_audit_log_can_be_filtered_by_action(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db, role=Role.ADMIN, email="admin@example.com")

    body = (await client.get("/api/admin/audit?action=auth.login", headers=auth(token))).json()

    assert body["total"] >= 1
    assert {entry["action"] for entry in body["items"]} == {"auth.login"}


async def test_there_is_no_way_to_delete_an_audit_entry(
    client: AsyncClient, db: AsyncSession
) -> None:
    """An append-only record that can be pruned through the API records nothing."""
    token = await token_for(client, db, role=Role.ADMIN, email="admin@example.com")
    entry = await db.scalar(select(AuditLog))
    assert entry is not None

    response = await client.delete(f"/api/admin/audit/{entry.id}", headers=auth(token))

    assert response.status_code in (404, 405)


async def test_the_policy_endpoint_reports_the_rules_and_the_quota(
    client: AsyncClient, db: AsyncSession, settings: object
) -> None:
    token = await token_for(client, db, role=Role.ADMIN)

    body = (await client.get("/api/admin/policy", headers=auth(token))).json()

    assert body["production_enabled"] is False
    assert body["editable"] is False
    assert body["high_urgency_daily_quota"] == settings.high_urgency_daily_quota  # type: ignore[attr-defined]
    assert len(body["rules"]) == 5
    production = [rule for rule in body["rules"] if "production" in rule["rule"].lower()]
    assert all("Refused" in rule["admin"] for rule in production)


async def test_the_policy_endpoint_is_read_only(client: AsyncClient, db: AsyncSession) -> None:
    """4.4.3 has no table for policy, so there is nowhere to persist an override (D-032)."""
    token = await token_for(client, db, role=Role.ADMIN)

    response = await client.patch(
        "/api/admin/policy", json={"high_urgency_daily_quota": 99}, headers=auth(token)
    )

    assert response.status_code in (404, 405)


async def test_the_reported_role_order_matches_what_the_guards_enforce(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Otherwise the Admin page's dropdown could disagree with the API."""
    token = await token_for(client, db, role=Role.ADMIN)

    body = (await client.get("/api/admin/roles", headers=auth(token))).json()

    assert body == [role.value for role in ROLE_ORDER]
    for index in range(len(ROLE_ORDER) - 1):
        assert role_allows(ROLE_ORDER[index + 1], ROLE_ORDER[index])
        assert not role_allows(ROLE_ORDER[index], ROLE_ORDER[index + 1])


# ---------------------------------------------------------------------------
# Deactivation ends access everywhere
# ---------------------------------------------------------------------------


async def test_a_deactivated_user_loses_access_to_every_endpoint(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The user is re-read on every request, so a 15-minute token does not outlive the account."""
    token = await token_for(client, db, email="dev@example.com")
    user = await db.scalar(select(User).where(User.email == "dev@example.com"))
    assert user is not None
    user.active = False
    await db.commit()

    for path in ("/api/jobs", "/api/runs", "/api/queue", "/api/services"):
        response = await client.get(path, headers=auth(token))
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"
