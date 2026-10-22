"""The API gaps the frontend's pages ran into in Phase 6 (PROGRESS.md, "Found in T6.3" and "Found in
T6.7"), closed in the hardening of 2026-10-18: an Admin's password reset, the rate limits for the
Admin page, chain filters on the server, and a job's service by name."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import API_LIMIT, LOGIN_LIMIT
from app.db.models import AuditLog, Chain, Job, Role, Service
from tests.test_auth import PASSWORD, make_user, sign_in
from tests.test_routers import auth, token_for

NEW_PASSWORD = "a-brand-new-long-password"


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


async def test_an_admin_resets_a_password_and_the_old_sessions_end(
    client: AsyncClient, db: AsyncSession
) -> None:
    user = await make_user(db, email="forgetful@example.com")
    old = (await sign_in(client, email="forgetful@example.com")).json()
    admin = await token_for(client, db, role=Role.ADMIN, email="boss@example.com")

    reset = await client.post(
        f"/api/admin/users/{user.id}/password",
        headers=auth(admin),
        json={"password": NEW_PASSWORD},
    )

    assert reset.status_code == 200, reset.text
    assert reset.json()["email"] == "forgetful@example.com"
    me = await client.get("/api/me", headers=auth(old["access_token"]))
    assert me.status_code == 401, "the access token from before the reset is refused"
    renewed = await client.post("/api/auth/refresh", json={"refresh_token": old["refresh_token"]})
    assert renewed.status_code == 401, "and so is the refresh token"
    assert (await sign_in(client, email="forgetful@example.com")).status_code == 401
    fresh = await sign_in(client, email="forgetful@example.com", password=NEW_PASSWORD)
    assert fresh.status_code == 200
    assert (
        await client.get("/api/me", headers=auth(fresh.json()["access_token"]))
    ).status_code == 200, "a session started after the reset works"

    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "admin.user.password_reset"))
    assert entry is not None and entry.target == "forgetful@example.com"
    assert NEW_PASSWORD not in str(entry.details)


async def test_only_an_admin_resets_passwords_and_only_to_a_long_one(
    client: AsyncClient, db: AsyncSession
) -> None:
    user = await make_user(db, email="someone@example.com")
    developer = await token_for(client, db, role=Role.DEVELOPER, email="dev2@example.com")
    admin = await token_for(client, db, role=Role.ADMIN, email="boss@example.com")
    path = f"/api/admin/users/{user.id}/password"

    refused = await client.post(path, headers=auth(developer), json={"password": NEW_PASSWORD})
    short = await client.post(path, headers=auth(admin), json={"password": "short"})
    missing = await client.post(
        "/api/admin/users/no-such-user/password",
        headers=auth(admin),
        json={"password": NEW_PASSWORD},
    )

    assert refused.status_code == 403
    assert short.status_code == 422
    assert missing.status_code == 404
    assert (
        await sign_in(client, email="someone@example.com", password=PASSWORD)
    ).status_code == 200


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------


async def test_the_admin_page_reads_the_limits_the_backend_enforces(
    client: AsyncClient, db: AsyncSession
) -> None:
    admin = await token_for(client, db, role=Role.ADMIN, email="boss@example.com")
    developer = await token_for(client, db, role=Role.DEVELOPER, email="dev2@example.com")

    limits = (await client.get("/api/admin/limits", headers=auth(admin))).json()

    by_name = {limit["name"]: limit for limit in limits}
    assert by_name["login"]["capacity"] == LOGIN_LIMIT.capacity
    assert by_name["api"]["capacity"] == API_LIMIT.capacity
    assert all(limit["applies_to"] for limit in limits)
    assert (await client.get("/api/admin/limits", headers=auth(developer))).status_code == 403


# ---------------------------------------------------------------------------
# Chain filters and a job's service
# ---------------------------------------------------------------------------


async def test_chains_are_filtered_by_assistant_and_status_on_the_server(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db)
    for service, job_type, status in [
        ("payment-service", "FREESTYLE", "FAILURE"),
        ("payment-service", "FREESTYLE", "SUCCESS"),
        ("auth-service", "PIPELINE", "FAILURE"),
    ]:
        db.add(Chain(service=service, job_type=job_type, status=status, jobs=["a"]))
    await db.commit()

    def query(params: str) -> list[tuple[str, str]]:
        return [(c["job_type"], c["status"]) for c in page[params]["items"]]

    page = {
        params: (await client.get(f"/api/chains?{params}", headers=auth(token))).json()
        for params in ("job_type=FREESTYLE", "status=FAILURE", "job_type=PIPELINE&status=FAILURE")
    }

    assert sorted(query("job_type=FREESTYLE")) == [
        ("FREESTYLE", "FAILURE"),
        ("FREESTYLE", "SUCCESS"),
    ]
    assert sorted(query("status=FAILURE")) == [("FREESTYLE", "FAILURE"), ("PIPELINE", "FAILURE")]
    assert query("job_type=PIPELINE&status=FAILURE") == [("PIPELINE", "FAILURE")]
    assert page["status=FAILURE"]["total"] == 2
    bad = await client.get("/api/chains?status=NOPE", headers=auth(token))
    assert bad.status_code == 422


async def test_a_job_names_its_service(client: AsyncClient, db: AsyncSession) -> None:
    token = await token_for(client, db)
    service = Service(
        name="payment-service", repo_url="https://example.com/p.git", build_command="./build.sh"
    )
    db.add(service)
    await db.flush()
    db.add(
        Job(jenkins_name="fs-payment-service-build", job_type="FREESTYLE", service_id=service.id)
    )
    db.add(Job(jenkins_name="orphan", job_type="FREESTYLE"))
    await db.commit()

    items = (await client.get("/api/jobs", headers=auth(token))).json()["items"]

    assert {item["jenkins_name"]: item["service"] for item in items} == {
        "fs-payment-service-build": "payment-service",
        "orphan": None,
    }
