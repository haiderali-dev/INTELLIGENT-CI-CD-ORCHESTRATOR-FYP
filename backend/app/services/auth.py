"""Authentication: sign in, refresh, sign out, and the audit trail behind them.

BUILD_PROMPT 4.4.4 fixes the endpoints; this module holds the logic so the router stays thin
(4.4.1). Argon2 hashing and JWT issuing live in ``app.core.security``.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode, unauthorized
from app.core.logging import get_logger
from app.core.security import (
    TokenType,
    create_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.core.settings import Settings
from app.db.models import AuditLog, Role, User

logger = get_logger(__name__)


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - the RFC 6750 scheme name, not a secret


class RevokedTokens:
    """Refresh tokens invalidated by signing out, held by ``jti`` until they would expire anyway.

    Part 4.4.3 lists no table for sessions or tokens, so this is deliberately in memory rather than
    inventing one. Two consequences, both accepted and recorded in docs/decisions.md D-021:

    * a backend restart forgets the denylist, so a refresh token revoked before a restart works
      again afterwards;
    * with more than one backend instance, a sign-out on one would not be seen by the others.

    The exposure is bounded by design. Access tokens last 15 minutes and are never checked against
    this list -- checking them would mean a database or shared-cache lookup on every single request
    to shorten a 15-minute window. What sign-out actually has to stop is a *refresh* token being
    reused for seven days, and that is what this does.
    """

    def __init__(self) -> None:
        self._revoked: dict[str, float] = {}
        self._lock = threading.Lock()

    def revoke(self, jti: str, expires_at: float) -> None:
        with self._lock:
            self._purge()
            self._revoked[jti] = expires_at

    def is_revoked(self, jti: str) -> bool:
        with self._lock:
            self._purge()
            return jti in self._revoked

    def _purge(self) -> None:
        """Drop entries whose token has expired; the JWT check rejects those anyway."""
        now = time.time()
        for jti in [jti for jti, expiry in self._revoked.items() if expiry < now]:
            del self._revoked[jti]

    def clear(self) -> None:
        with self._lock:
            self._revoked.clear()


_revoked = RevokedTokens()


def get_revoked_tokens() -> RevokedTokens:
    return _revoked


async def _audit(
    session: AsyncSession,
    *,
    actor_id: str | None,
    action: str,
    target: str,
    durable: bool = False,
    **details: Any,
) -> None:
    """Record a security-relevant event.

    4.4.3 requires an audit entry for every policy denial, and a refused sign-in is one. Successful
    sign-ins are recorded too: "who was using this account, and when" is unanswerable afterwards
    without them, and that is the first question asked when something looks wrong.

    ``durable`` commits the entry immediately. It is needed whenever the caller is about to raise:
    ``get_db`` rolls the session back on any exception, so an entry merely added before a refusal
    would be discarded along with it -- and the denials are exactly the entries 4.4.3 asks for. The
    commit is safe here because a refused sign-in has written nothing else worth undoing.
    """
    session.add(AuditLog(actor_id=actor_id, action=action, target=target, details=details))
    if durable:
        await session.commit()


async def authenticate(
    session: AsyncSession, settings: Settings, *, email: str, password: str, client: str
) -> User:
    """Verify credentials and return the user.

    Every failure returns the same error. Distinguishing "no such account" from "wrong password"
    turns the login endpoint into an account-existence oracle, which is how a list of real email
    addresses gets built.
    """
    normalised = email.strip().lower()
    user = await session.scalar(select(User).where(User.email == normalised))

    generic = unauthorized(ErrorCode.INVALID_CREDENTIALS, "That email or password is not correct.")

    if user is None:
        # Hash anyway. Returning early would make a missing account measurably faster to reject
        # than a wrong password, which leaks exactly what the shared message hides.
        hash_password(password)
        await _audit(
            session,
            actor_id=None,
            action="auth.login.failed",
            target=normalised,
            reason="no_user",
            client=client,
            durable=True,
        )
        logger.info("login_failed", reason="no_user", client=client)
        raise generic

    if not verify_password(password, user.password_hash):
        await _audit(
            session,
            actor_id=user.id,
            action="auth.login.failed",
            target=normalised,
            reason="bad_password",
            client=client,
            durable=True,
        )
        logger.info("login_failed", reason="bad_password", user_id=user.id, client=client)
        raise generic

    if not user.active:
        # A distinct message here is deliberate: the credentials were right, and telling someone
        # their account is disabled is actionable where "wrong password" would send them in
        # circles. It reveals nothing they did not already prove they know.
        await _audit(
            session,
            actor_id=user.id,
            action="auth.login.denied",
            target=normalised,
            reason="inactive",
            client=client,
            durable=True,
        )
        raise unauthorized(
            ErrorCode.ACCOUNT_DISABLED,
            "This account is disabled. Ask an administrator to re-enable it.",
        )

    # Argon2 parameters get stronger over time; rehash on a successful sign-in, which is the only
    # moment the plaintext is available.
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        logger.info("password_rehashed", user_id=user.id)

    await _audit(session, actor_id=user.id, action="auth.login", target=normalised, client=client)
    logger.info("login", user_id=user.id, role=user.role, client=client)
    return user


def issue_tokens(settings: Settings, user: User) -> TokenPair:
    """Mint an access and a refresh token for a user.

    The role is carried in the access token so a role check needs no database round trip. It is
    deliberately absent from the refresh token: a refresh re-reads the user, so a role change takes
    effect at the next refresh rather than lasting for the refresh token's whole seven days.
    """
    return TokenPair(
        access_token=create_token(
            settings, subject=user.id, token_type=TokenType.ACCESS, role=user.role
        ),
        refresh_token=create_token(settings, subject=user.id, token_type=TokenType.REFRESH),
    )


async def refresh_tokens(
    session: AsyncSession, settings: Settings, *, refresh_token: str
) -> tuple[User, TokenPair]:
    """Exchange a refresh token for a new pair.

    The old refresh token is revoked as part of the exchange. Without that rotation a leaked
    refresh token stays usable for its full lifetime even while the legitimate holder keeps using
    theirs, and nothing distinguishes the two.
    """
    claims = decode_token(settings, refresh_token, expected=TokenType.REFRESH)
    jti = str(claims.get("jti", ""))

    if _revoked.is_revoked(jti):
        raise unauthorized(
            ErrorCode.TOKEN_INVALID, "This session has been signed out. Please sign in again."
        )

    user = await session.get(User, str(claims.get("sub", "")))
    if user is None:
        raise unauthorized(ErrorCode.TOKEN_INVALID, "This session is no longer valid.")
    if not user.active:
        raise unauthorized(
            ErrorCode.ACCOUNT_DISABLED,
            "This account is disabled. Ask an administrator to re-enable it.",
        )

    _revoked.revoke(jti, float(claims.get("exp", 0)))
    logger.info("token_refreshed", user_id=user.id)
    return user, issue_tokens(settings, user)


async def sign_out(
    session: AsyncSession, settings: Settings, *, refresh_token: str | None, user: User
) -> None:
    """Revoke the caller's refresh token.

    A missing or already-invalid token is not an error. Sign-out must always appear to succeed, or
    a user whose token expired mid-session is told their attempt to leave failed.
    """
    if refresh_token:
        try:
            claims = decode_token(settings, refresh_token, expected=TokenType.REFRESH)
            _revoked.revoke(str(claims.get("jti", "")), float(claims.get("exp", 0)))
        except Exception:  # any unusable token is already harmless
            logger.info("signout_token_unusable", user_id=user.id)

    await _audit(session, actor_id=user.id, action="auth.logout", target=user.email)
    logger.info("logout", user_id=user.id)


async def load_user_from_access_token(
    session: AsyncSession, settings: Settings, token: str
) -> User:
    """Resolve an access token to its user.

    The user is re-read on every request rather than trusted from the token. A token is valid for
    15 minutes; without this, deactivating an account would leave it working for the remainder,
    which is precisely the window in which someone deactivates an account.
    """
    claims = decode_token(settings, token, expected=TokenType.ACCESS)
    user = await session.get(User, str(claims.get("sub", "")))
    if user is None:
        raise unauthorized(ErrorCode.TOKEN_INVALID, "This session is no longer valid.")
    if not user.active:
        raise unauthorized(
            ErrorCode.ACCOUNT_DISABLED,
            "This account is disabled. Ask an administrator to re-enable it.",
        )
    return user


def role_allows(actual: Role, required: Role) -> bool:
    """Roles are ordered: ADMIN can do anything DEVOPS can, and DEVOPS anything DEVELOPER can.

    An ordering rather than a set membership test, because 4.5.5's policy table is cumulative --
    every row a developer may do, DevOps may do too.
    """
    order = {Role.DEVELOPER: 0, Role.DEVOPS: 1, Role.ADMIN: 2}
    return order[actual] >= order[required]
