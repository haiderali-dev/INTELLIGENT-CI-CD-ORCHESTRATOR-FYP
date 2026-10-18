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

from app.ai.clarify import ClarificationService
from app.ai.factory import build_intent_parser
from app.ai.parser import IntentParser
from app.core.errors import ApiError, ErrorCode, forbidden, unauthorized
from app.core.ratelimit import (
    API_LIMIT,
    ASSISTANT_LIMIT,
    RateLimit,
    RateLimiter,
    get_rate_limiter,
)
from app.core.security import TokenType, decode_token
from app.core.settings import Settings
from app.db.models import Role, User
from app.db.session import get_db
from app.failures.explainer import FailureExplainer
from app.failures.factory import build_failure_explainer
from app.generation.factory import build_planner
from app.generation.planner import Planner
from app.services.auth import load_user_from_access_token, role_allows
from app.services.catalog import Catalog
from app.services.dependencies import (
    get_catalog,
    get_git_client,
    get_llm_provider,
    get_settings_dep,
)
from app.services.git import GitClient

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


def caller_identifier(request: Request, settings: Settings) -> str:
    """Who to rate-limit for signed-in traffic: the user a valid access token names, else the
    address.

    Keying by address alone put everyone behind one proxy in one bucket. Through the dev server's
    /api proxy every user arrives from 127.0.0.1, so one person's assistant calls starved everyone
    (independent security review, finding 7). The token is only verified here, not looked up:
    ``CurrentUser`` still decides whether the request is allowed at all.
    """
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token:
        try:
            claims = decode_token(settings, token.strip(), expected=TokenType.ACCESS)
        except ApiError:
            pass
        else:
            return f"user:{claims.get('sub', '')}"
    return f"address:{client_identifier(request)}"


def rate_limit(limit: RateLimit, *, per_user: bool = False) -> Callable[..., None]:
    """Build a dependency enforcing one named limit, keyed by client address, or by the signed-in
    user when ``per_user`` is set."""

    def _check(
        request: Request,
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
        settings: Annotated[Settings, Depends(get_settings_dep)],
    ) -> None:
        key = caller_identifier(request, settings) if per_user else client_identifier(request)
        limiter.check(limit, key)

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


def get_intent_parser(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    catalog: Annotated[Catalog, Depends(get_catalog)],
    git: Annotated[GitClient, Depends(get_git_client)],
) -> IntentParser:
    """An intent parser around the process-wide provider, quota and cache (4.5)."""
    provider, has_models = get_llm_provider(settings, catalog, "intent")
    return build_intent_parser(
        settings, catalog=catalog, git=git, provider=provider, has_models=has_models
    )


def get_planner(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    catalog: Annotated[Catalog, Depends(get_catalog)],
) -> Planner:
    """A planner around the same provider and quota as the intent parser (T5.2)."""
    provider, has_models = get_llm_provider(settings, catalog, "plan")
    return build_planner(settings, catalog=catalog, provider=provider, has_models=has_models)


def get_failure_explainer(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    catalog: Annotated[Catalog, Depends(get_catalog)],
) -> FailureExplainer:
    """An explainer around the same provider and quota as the parser and planner (T5.9)."""
    provider, has_models = get_llm_provider(settings, catalog, "failure")
    return build_failure_explainer(
        settings, catalog=catalog, provider=provider, has_models=has_models
    )


def get_clarifier(catalog: Annotated[Catalog, Depends(get_catalog)]) -> ClarificationService:
    return ClarificationService(catalog)


# Named aliases so a route reads as a sentence: `user: DevOpsUser`.
DeveloperUser = Annotated[User, Depends(require_role(Role.DEVELOPER))]
DevOpsUser = Annotated[User, Depends(require_role(Role.DEVOPS))]
AdminUser = Annotated[User, Depends(require_role(Role.ADMIN))]

# The general ceiling for authenticated traffic, per user.
ApiRateLimit = Depends(rate_limit(API_LIMIT, per_user=True))
# Messages and generation call the model, which has a quota of its own (4.5.1). Per user too.
AssistantRateLimit = Depends(rate_limit(ASSISTANT_LIMIT, per_user=True))
