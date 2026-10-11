"""Authentication endpoints.

BUILD_PROMPT 4.4.4: ``POST /api/auth/login``, ``/refresh``, ``/logout`` and ``GET /api/me``.

The router stays thin (4.4.1): it validates the request shape, calls ``app.services.auth`` and maps
the result onto a response model. Every decision lives in the service.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, client_identifier, rate_limit
from app.core.ratelimit import LOGIN_LIMIT, REFRESH_LIMIT
from app.core.settings import Settings
from app.db.models import Role, User
from app.db.session import get_db
from app.services.auth import authenticate, issue_tokens, refresh_tokens, sign_out
from app.services.dependencies import get_settings_dep

router = APIRouter(tags=["auth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    # A maximum length, because Argon2 hashes whatever it is given and a multi-megabyte password
    # would burn CPU on an unauthenticated endpoint. The minimum is not enforced here: rejecting a
    # short password at sign-in tells an attacker their guess was too short to be this account's.
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=4096)


class LogoutRequest(BaseModel):
    """The refresh token to revoke.

    Optional so that signing out still works when the client has already lost it; the endpoint
    always reports success.
    """

    refresh_token: str | None = Field(default=None, max_length=4096)


class UserResponse(BaseModel):
    id: str
    email: str
    role: Role
    active: bool

    @classmethod
    def of(cls, user: User) -> UserResponse:
        return cls(id=user.id, email=user.email, role=Role(user.role), active=user.active)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - the RFC 6750 scheme name, not a secret
    expires_in_seconds: int
    user: UserResponse


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/auth/login",
    response_model=TokenResponse,
    summary="Sign in",
    dependencies=[Depends(rate_limit(LOGIN_LIMIT))],
)
async def login(
    payload: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> TokenResponse:
    """Exchange an email and password for an access and refresh token pair.

    Rate limited to five attempts a minute per client address: enough for a person who mistypes,
    useless for a password spray.
    """
    user = await authenticate(
        session,
        settings,
        email=payload.email,
        password=payload.password,
        client=client_identifier(request),
    )
    tokens = issue_tokens(settings, user)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in_seconds=settings.access_token_minutes * 60,
        user=UserResponse.of(user),
    )


@router.post(
    "/auth/refresh",
    response_model=TokenResponse,
    summary="Exchange a refresh token for a new pair",
    dependencies=[Depends(rate_limit(REFRESH_LIMIT))],
)
async def refresh(
    payload: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> TokenResponse:
    """Rotate the token pair.

    The supplied refresh token is revoked as part of the exchange, so a leaked one cannot keep
    being used alongside the legitimate holder's.
    """
    user, tokens = await refresh_tokens(session, settings, refresh_token=payload.refresh_token)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in_seconds=settings.access_token_minutes * 60,
        user=UserResponse.of(user),
    )


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
)
async def logout(
    payload: LogoutRequest,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> None:
    """Revoke the caller's refresh token.

    Always succeeds. An expired or missing token is not an error: telling someone their attempt to
    sign out failed is both alarming and useless, since the outcome they wanted has happened.
    """
    await sign_out(session, settings, refresh_token=payload.refresh_token, user=user)


@router.get("/me", response_model=UserResponse, summary="The signed-in user")
async def me(user: CurrentUser) -> UserResponse:
    """Who the caller is.

    The frontend calls this on load to decide what to render, so it doubles as a token check: a
    401 here means sign in again, and the app needs that answer before drawing anything.
    """
    return UserResponse.of(user)
