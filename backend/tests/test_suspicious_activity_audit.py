"""Suspicious activity is audited (report 4.7.4, User Story 5, acceptance criterion 3; D-068).

"Given suspicious activity occurs, when it is detected, then the system logs the event for audit
purposes." Three things the backend already detected left no audit entry: a role guard refusing a
request, a spent refresh token coming back, and a sign-in limit engaging. Each is now an entry an
Admin can read, and the limit's entries are bounded so that hammering a limit cannot fill the log.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.ratelimit import RateLimit, RateLimitedError, RateLimiter
from app.db.models import AuditLog, Role
from tests.test_auth import make_user, sign_in
from tests.test_routers import auth, token_for


async def entries(db: AsyncSession, action: str) -> list[AuditLog]:
    return list((await db.scalars(select(AuditLog).where(AuditLog.action == action))).all())


class Clock:
    """The limiter's clock, moved by hand, so buckets refill only when a test says so."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    frozen = Clock()
    monkeypatch.setattr(ratelimit.time, "monotonic", frozen)
    return frozen


# ---------------------------------------------------------------------------
# The limiter marks one refusal a window for the audit
# ---------------------------------------------------------------------------


def test_one_refusal_a_window_is_marked_for_the_audit(clock: Clock) -> None:
    limiter = RateLimiter()
    limit = RateLimit(name="t", capacity=2, per_seconds=60.0)

    def refusal() -> RateLimitedError:
        with pytest.raises(RateLimitedError) as refused:
            limiter.check(limit, "caller")
        return refused.value

    limiter.check(limit, "caller")
    limiter.check(limit, "caller")
    first, second = refusal(), refusal()
    clock.now += 30
    limiter.check(limit, "caller")  # half a window refills one of the two attempts
    same_window = refusal()
    clock.now += 31
    limiter.check(limit, "caller")
    next_window = refusal()

    assert first.record, "the refusal that shows the limit engaged is recorded"
    assert not second.record, "the ones after it in the same window are not"
    assert first.status_code == 429 and first.limit is limit
    assert not same_window.record
    assert next_window.record, "a limit still engaging a window later is recorded again"


def test_another_caller_gets_its_own_record(clock: Clock) -> None:
    limiter = RateLimiter()
    limit = RateLimit(name="t", capacity=1, per_seconds=60.0)
    for caller in ("a", "b"):
        limiter.check(limit, caller)

    refusals = []
    for caller in ("a", "b"):
        with pytest.raises(RateLimitedError) as refused:
            limiter.check(limit, caller)
        refusals.append(refused.value.record)

    assert refusals == [True, True]


# ---------------------------------------------------------------------------
# Sign-in limits
# ---------------------------------------------------------------------------


async def test_a_sign_in_limit_engaging_is_audited_once_a_minute(
    client: AsyncClient, db: AsyncSession, clock: Clock
) -> None:
    await make_user(db, email="target@example.com")

    first = [
        (await sign_in(client, email="target@example.com", password="wrong")).status_code
        for _ in range(8)
    ]
    after_one_window = await entries(db, "auth.login.limited")
    clock.now += 61  # the bucket refills its five attempts, and a new window starts
    second = [
        (await sign_in(client, email="target@example.com", password="wrong")).status_code
        for _ in range(6)
    ]
    after_two_windows = await entries(db, "auth.login.limited")

    assert first == [401] * 5 + [429] * 3
    assert second == [401] * 5 + [429]
    assert len(after_one_window) == 1, "three refusals, one entry: the moment the limit engaged"
    entry = after_one_window[0]
    assert entry.target == "target@example.com"
    assert entry.actor_id is None, "a refused attempt is not attributed to the account it names"
    assert entry.details["limit"] == "login"
    assert entry.details["client"]
    assert len(after_two_windows) == 2


async def test_a_password_spray_is_audited_when_the_address_limit_engages(
    client: AsyncClient, db: AsyncSession, clock: Clock
) -> None:
    statuses = [
        (await sign_in(client, email=f"spray{i}@example.com", password="x")).status_code
        for i in range(32)
    ]

    limited = await entries(db, "auth.login.limited")
    assert statuses == [401] * 30 + [429] * 2
    assert [(entry.target, entry.details["limit"]) for entry in limited] == [
        ("spray30@example.com", "login-address")
    ]


async def test_a_successful_sign_in_is_not_audited_as_limited(
    client: AsyncClient, db: AsyncSession, clock: Clock
) -> None:
    await make_user(db)

    assert (await sign_in(client)).status_code == 200
    assert await entries(db, "auth.login.limited") == []


# ---------------------------------------------------------------------------
# A spent refresh token coming back
# ---------------------------------------------------------------------------


async def test_a_replayed_refresh_token_is_audited(client: AsyncClient, db: AsyncSession) -> None:
    user = await make_user(db)
    stolen = (await sign_in(client)).json()["refresh_token"]
    rotated = await client.post("/api/auth/refresh", json={"refresh_token": stolen})

    replay = await client.post("/api/auth/refresh", json={"refresh_token": stolen})

    assert rotated.status_code == 200
    assert replay.status_code == 401
    [entry] = await entries(db, "auth.session.reused")
    assert entry.actor_id == user.id
    assert entry.target == user.email
    assert entry.details["client"]


async def test_an_ordinary_refresh_is_not_audited_as_reused(
    client: AsyncClient, db: AsyncSession
) -> None:
    await make_user(db)
    token = (await sign_in(client)).json()["refresh_token"]

    assert (
        await client.post("/api/auth/refresh", json={"refresh_token": token})
    ).status_code == 200
    assert await entries(db, "auth.session.reused") == []


# ---------------------------------------------------------------------------
# Role guards
# ---------------------------------------------------------------------------


async def test_a_developer_refused_an_admin_endpoint_is_audited(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db, role=Role.DEVELOPER)

    response = await client.get("/api/admin/users", headers=auth(token))

    assert response.status_code == 403
    [entry] = await entries(db, "access.denied")
    assert entry.target == "GET /api/admin/users"
    assert entry.details == {"required_role": "ADMIN", "actual_role": "DEVELOPER"}
    assert entry.actor_id is not None


async def test_a_permitted_request_is_not_audited_as_denied(
    client: AsyncClient, db: AsyncSession
) -> None:
    token = await token_for(client, db, role=Role.ADMIN)

    assert (await client.get("/api/admin/users", headers=auth(token))).status_code == 200
    assert await entries(db, "access.denied") == []
