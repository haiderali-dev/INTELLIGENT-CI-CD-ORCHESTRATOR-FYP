"""Shared FastAPI dependencies: the current user, role guards and rate limiting.

Every protected route in the backend goes through ``CurrentUser`` or one of the role guards below,
so authorisation is declared in the signature rather than checked in the body. A route that forgets
the check is then visibly different from one that has it, instead of silently open.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode, forbidden, unauthorized
from app.core.ratelimit import API_LIMIT, RateLimit, RateLimiter, get_rate_limiter
from app.core.settings import Settings
from app.db.models import Role, User
from app.db.session import get_db
from app.services.auth import load_user_from_access_token, role_allows
from app.services.dependencies import get_settings_dep

# auto_error=False so a missing header produces this module's error shape rather than FastAPI's
# bare {"detail": ...}, which would be the one response in the API not matching 4.4.1.
_bearer = HTTPBearer(auto_error=False, description="Access token from POST /api/auth/login")


def client_identifier(request: Request) -> str:
    """Who to rate-limit.

    The direct peer address. X-Forwarded-For is deliberately ignored: it is caller-supplied, so
    trusting it lets anyone reset their own limit by varying a header. If this ever runs behind a
    real proxy, that proxy must be trusted explicitly rather than by default.
    """
    return request.client.host if request.client else "unknown"


def rate_limit(limit: RateLimit) -> Callable[..., None]:
    """Build a dependency enforcing one named limit, keyed by client address."""

    def _check(
        request: Request,
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    ) -> None:
        limiter.check(limit, client_identifier(request))

    return _check


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> User:
    """The signed-in user, or 401."""
    if credentials is None or not credentials.credentials:
        raise unauthorized(ErrorCode.NOT_AUTHENTICATED, "Sign in to continue.")
    return await load_user_from_access_token(session, settings, credentials.credentials)


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(minimum: Role) -> Callable[..., Awaitable[User]]:
    """Require at least ``minimum``.

    The message names the role needed rather than only refusing, because "you need DevOps for this"
    tells someone what to ask for and "forbidden" does not.
    """

    async def _guard(user: CurrentUser) -> User:
        if not role_allows(Role(user.role), minimum):
            raise forbidden(
                ErrorCode.FORBIDDEN,
                f"This action needs the {minimum.value} role. Yours is {user.role}.",
                required_role=minimum.value,
                actual_role=user.role,
            )
        return user

    return _guard


# Named aliases so a route reads as a sentence: `user: DevOpsUser`.
DeveloperUser = Annotated[User, Depends(require_role(Role.DEVELOPER))]
DevOpsUser = Annotated[User, Depends(require_role(Role.DEVOPS))]
AdminUser = Annotated[User, Depends(require_role(Role.ADMIN))]

# The general ceiling for authenticated traffic.
ApiRateLimit = Depends(rate_limit(API_LIMIT))
