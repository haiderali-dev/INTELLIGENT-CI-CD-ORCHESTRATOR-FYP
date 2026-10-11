"""Authentication: sign in, refresh, sign out, current user, role guards and rate limits.

The tests that matter most here are the ones about what the API refuses to reveal. An auth endpoint
that is merely functional is easy; one that does not leak which accounts exist, does not let a
signed-out token keep working, and does not let a deactivated account finish its session takes
deliberate effort, and each of those properties has a test below.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DevOpsUser
from app.core.security import TokenType, create_token, hash_password
from app.core.settings import Settings
from app.db.models import AuditLog, Role, User

PASSWORD = "correct-horse-battery-staple"


async def make_user(
    db: AsyncSession,
    *,
    email: str = "dev@example.com",
    role: Role = Role.DEVELOPER,
    active: bool = True,
) -> User:
    user = User(email=email, password_hash=hash_password(PASSWORD), role=role.value, active=active)
    db.add(user)
    await db.commit()
    return user


async def sign_in(client: AsyncClient, email: str = "dev@example.com", password: str = PASSWORD):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------
# Sign in
# ---------------------------------------------------------------------------


async def test_login_returns_a_token_pair_and_the_user(
    client: AsyncClient, db: AsyncSession
) -> None:
    await make_user(db)

    response = await sign_in(client)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["access_token"] != body["refresh_token"]
    assert body["expires_in_seconds"] == 15 * 60
    assert body["user"]["email"] == "dev@example.com"
    assert body["user"]["role"] == Role.DEVELOPER.value
    assert "password" not in str(body) and "hash" not in str(body)


async def test_login_is_case_insensitive_on_email(client: AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="dev@example.com")

    assert (await sign_in(client, email="DEV@Example.COM")).status_code == 200


async def test_wrong_password_and_unknown_account_are_indistinguishable(
    client: AsyncClient, db: AsyncSession
) -> None:
    """The login endpoint must not be an account-existence oracle.

    If a wrong password and a missing account gave different answers, the endpoint would enumerate
    valid email addresses for anyone who asked politely enough.
    """
    await make_user(db, email="real@example.com")

    wrong_password = await sign_in(client, email="real@example.com", password="nope")
    no_such_user = await sign_in(client, email="ghost@example.com", password="nope")

    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json() == no_such_user.json()


async def test_a_disabled_account_is_told_so(client: AsyncClient, db: AsyncSession) -> None:
    """Deliberately distinct from a bad password.

    The caller has already proved they know the credentials, so this reveals nothing new, and
    "wrong password" would send them round in circles resetting a password that works.
    """
    await make_user(db, email="gone@example.com", active=False)

    response = await sign_in(client, email="gone@example.com")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"


async def test_login_records_success_and_failure_in_the_audit_log(
    client: AsyncClient, db: AsyncSession
) -> None:
    """4.4.3 requires an audit entry for every policy denial; a refused sign-in is one."""
    await make_user(db, email="audited@example.com")

    await sign_in(client, email="audited@example.com")
    await sign_in(client, email="audited@example.com", password="wrong")

    actions = list(await db.scalars(select(AuditLog.action)))
    assert "auth.login" in actions
    assert "auth.login.failed" in actions


async def test_audit_entry_never_stores_the_password(client: AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="secret@example.com")
    await sign_in(client, email="secret@example.com", password="hunter2-should-not-appear")

    for entry in await db.scalars(select(AuditLog)):
        assert "hunter2" not in str(entry.details)


async def test_malformed_login_uses_the_one_error_shape(client: AsyncClient) -> None:
    response = await client.post("/api/auth/login", json={"email": "not-an-email"})

    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "VALIDATION_FAILED"


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------


async def test_me_returns_the_signed_in_user(client: AsyncClient, db: AsyncSession) -> None:
    await make_user(db)
    token = (await sign_in(client)).json()["access_token"]

    response = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["email"] == "dev@example.com"


@pytest.mark.parametrize(
    ("header", "expected_code"),
    [
        (None, "NOT_AUTHENTICATED"),
        ("Bearer not-a-token", "TOKEN_INVALID"),
        ("Bearer ", "NOT_AUTHENTICATED"),
    ],
)
async def test_me_rejects_missing_or_invalid_tokens(
    client: AsyncClient, header: str | None, expected_code: str
) -> None:
    headers = {"Authorization": header} if header else {}
    response = await client.get("/api/me", headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == expected_code


async def test_a_refresh_token_is_not_accepted_as_an_access_token(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Without the type claim this would hand out a seven-day access credential."""
    await make_user(db)
    refresh = (await sign_in(client)).json()["refresh_token"]

    response = await client.get("/api/me", headers={"Authorization": f"Bearer {refresh}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_INVALID"


async def test_an_expired_token_is_distinguishable_from_an_invalid_one(
    client: AsyncClient, db: AsyncSession, settings: Settings
) -> None:
    """The frontend acts on the difference: expired means refresh, invalid means sign in again."""
    user = await make_user(db)
    expired_settings = settings.model_copy(update={"access_token_minutes": 1})
    token = create_token(
        expired_settings, subject=user.id, token_type=TokenType.ACCESS, role=user.role
    )
    # Move the clock past expiry by signing a token that was already old.
    import jwt

    claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    claims["exp"] = claims["iat"] - 1
    stale = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")

    response = await client.get("/api/me", headers={"Authorization": f"Bearer {stale}"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


async def test_deactivating_an_account_ends_the_session_immediately(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A valid token must stop working the moment the account is disabled.

    The user is re-read on every request precisely so this holds. Trusting the token's claims
    instead would leave a deactivated account working for up to fifteen more minutes -- which is
    exactly the window in which somebody deactivates an account.
    """
    user = await make_user(db)
    token = (await sign_in(client)).json()["access_token"]
    assert (
        await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    ).status_code == 200

    user.active = False
    await db.commit()

    response = await client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


async def test_refresh_returns_a_new_working_pair(client: AsyncClient, db: AsyncSession) -> None:
    await make_user(db)
    first = (await sign_in(client)).json()

    response = await client.post(
        "/api/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )

    assert response.status_code == 200
    second = response.json()
    assert second["refresh_token"] != first["refresh_token"], "the refresh token must rotate"
    check = await client.get(
        "/api/me", headers={"Authorization": f"Bearer {second['access_token']}"}
    )
    assert check.status_code == 200


async def test_a_used_refresh_token_cannot_be_reused(client: AsyncClient, db: AsyncSession) -> None:
    """Rotation is the point: a leaked refresh token must not stay usable alongside the real one."""
    await make_user(db)
    original = (await sign_in(client)).json()["refresh_token"]

    assert (
        await client.post("/api/auth/refresh", json={"refresh_token": original})
    ).status_code == 200
    replay = await client.post("/api/auth/refresh", json={"refresh_token": original})

    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "TOKEN_INVALID"


async def test_an_access_token_is_not_accepted_for_refresh(
    client: AsyncClient, db: AsyncSession
) -> None:
    await make_user(db)
    access = (await sign_in(client)).json()["access_token"]

    response = await client.post("/api/auth/refresh", json={"refresh_token": access})

    assert response.status_code == 401


async def test_refresh_reflects_a_role_change(client: AsyncClient, db: AsyncSession) -> None:
    """The role is re-read on refresh, so a promotion or demotion takes effect within 15 minutes
    rather than lasting the refresh token's full seven days."""
    user = await make_user(db, role=Role.DEVELOPER)
    refresh = (await sign_in(client)).json()["refresh_token"]

    user.role = Role.ADMIN.value
    await db.commit()

    body = (await client.post("/api/auth/refresh", json={"refresh_token": refresh})).json()
    assert body["user"]["role"] == Role.ADMIN.value


async def test_refresh_refuses_a_deactivated_account(client: AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    refresh = (await sign_in(client)).json()["refresh_token"]

    user.active = False
    await db.commit()

    response = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"


# ---------------------------------------------------------------------------
# Sign out
# ---------------------------------------------------------------------------


async def test_logout_revokes_the_refresh_token(client: AsyncClient, db: AsyncSession) -> None:
    await make_user(db)
    tokens = (await sign_in(client)).json()
    auth = {"Authorization": f"Bearer {tokens['access_token']}"}

    logout = await client.post(
        "/api/auth/logout", json={"refresh_token": tokens["refresh_token"]}, headers=auth
    )
    assert logout.status_code == 204

    reuse = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reuse.status_code == 401, "a signed-out refresh token must not work"


async def test_logout_succeeds_without_a_refresh_token(
    client: AsyncClient, db: AsyncSession
) -> None:
    """Signing out must always appear to succeed; the outcome the user wanted has happened."""
    await make_user(db)
    access = (await sign_in(client)).json()["access_token"]

    response = await client.post(
        "/api/auth/logout", json={}, headers={"Authorization": f"Bearer {access}"}
    )
    assert response.status_code == 204


async def test_logout_tolerates_a_garbage_refresh_token(
    client: AsyncClient, db: AsyncSession
) -> None:
    await make_user(db)
    access = (await sign_in(client)).json()["access_token"]

    response = await client.post(
        "/api/auth/logout",
        json={"refresh_token": "not-a-jwt"},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert response.status_code == 204


async def test_logout_requires_authentication(client: AsyncClient) -> None:
    assert (await client.post("/api/auth/logout", json={})).status_code == 401


async def test_logout_is_audited(client: AsyncClient, db: AsyncSession) -> None:
    await make_user(db)
    tokens = (await sign_in(client)).json()
    await client.post(
        "/api/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    count = await db.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.action == "auth.logout")
    )
    assert count == 1


# ---------------------------------------------------------------------------
# Role guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("actual", "required", "allowed"),
    [
        (Role.DEVELOPER, Role.DEVELOPER, True),
        (Role.DEVELOPER, Role.DEVOPS, False),
        (Role.DEVELOPER, Role.ADMIN, False),
        (Role.DEVOPS, Role.DEVELOPER, True),
        (Role.DEVOPS, Role.DEVOPS, True),
        (Role.DEVOPS, Role.ADMIN, False),
        (Role.ADMIN, Role.DEVELOPER, True),
        (Role.ADMIN, Role.DEVOPS, True),
        (Role.ADMIN, Role.ADMIN, True),
    ],
)
def test_roles_are_cumulative(actual: Role, required: Role, allowed: bool) -> None:
    """4.5.5's policy table is cumulative: anything a developer may do, DevOps may do too."""
    from app.services.auth import role_allows

    assert role_allows(actual, required) is allowed


async def test_a_role_guard_names_the_role_needed(
    app: FastAPI, client: AsyncClient, db: AsyncSession
) -> None:
    """ "You need DevOps for this" tells someone what to ask for; "forbidden" does not.

    ``DevOpsUser`` is imported at module scope on purpose. This module uses postponed annotations,
    so FastAPI resolves the endpoint's hints against module globals; a function-local import leaves
    the name unresolvable and the parameter is then read as a query string one, giving 422.
    """

    @app.get("/api/_test/devops-only")
    async def _devops_only(user: DevOpsUser) -> dict[str, str]:  # pragma: no cover - test route
        return {"ok": user.email}

    await make_user(db, role=Role.DEVELOPER)
    token = (await sign_in(client)).json()["access_token"]

    response = await client.get(
        "/api/_test/devops-only", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "FORBIDDEN"
    assert error["details"]["required_role"] == Role.DEVOPS.value
    assert error["details"]["actual_role"] == Role.DEVELOPER.value


# ---------------------------------------------------------------------------
# Rate limits
# ---------------------------------------------------------------------------


async def test_login_is_rate_limited(client: AsyncClient, db: AsyncSession) -> None:
    """Five attempts a minute: generous for a person, useless for a password spray."""
    await make_user(db, email="target@example.com")

    statuses = [
        (await sign_in(client, email="target@example.com", password="wrong")).status_code
        for _ in range(7)
    ]

    assert statuses[:5] == [401] * 5, f"the first five should be ordinary failures, got {statuses}"
    assert 429 in statuses[5:], f"the limit should engage after five attempts, got {statuses}"


async def test_rate_limit_says_when_to_retry(client: AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="target@example.com")
    for _ in range(6):
        await sign_in(client, email="target@example.com", password="wrong")

    response = await sign_in(client, email="target@example.com", password="wrong")

    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert error["details"]["retry_after_seconds"] >= 1
    assert error["details"]["limit"] == "login"


async def test_the_limit_counts_attempts_not_failures(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A successful sign-in consumes a token too.

    Otherwise an attacker with one valid account could reset the bucket at will and brute-force
    another from the same address indefinitely.
    """
    await make_user(db, email="good@example.com")

    for _ in range(5):
        await sign_in(client, email="good@example.com")

    assert (await sign_in(client, email="good@example.com")).status_code == 429
