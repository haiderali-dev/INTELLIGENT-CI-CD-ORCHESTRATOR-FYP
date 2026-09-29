"""Password hashing and JWT issuing.

Argon2 for passwords (BUILD_PROMPT 4.4.3) and HS256 JWTs with separate access and refresh
lifetimes (4.4.2).
"""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.errors import ErrorCode, unauthorized
from app.core.settings import Settings

_ALGORITHM: Final = "HS256"

# Argon2id at the library's defaults, which follow the RFC 9106 recommendations. Tuning these is a
# deployment decision, not a code one, and the defaults are appropriate for a project of this size.
_hasher = PasswordHasher()


class TokenType(StrEnum):
    """Access and refresh tokens are distinguished inside the token itself.

    Without this, a refresh token would be accepted as an access token. Refresh tokens are
    deliberately long-lived, so that confusion would hand out a 7-day access credential.
    """

    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(plain: str) -> str:
    """Hash a password for storage."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Check a password against a stored hash.

    Returns False rather than raising on a malformed hash, so a corrupt row cannot 500 the login
    endpoint and reveal that the row is corrupt.
    """
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(hashed: str) -> bool:
    """True when a stored hash used weaker parameters than the current settings."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except (InvalidHashError, ValueError):
        return False


def constant_time_equals(left: str, right: str) -> bool:
    """Compare two secrets without leaking their common prefix through timing.

    Used for the metrics bearer token, which the plugin sends on every event.
    """
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def create_token(
    settings: Settings,
    *,
    subject: str,
    token_type: TokenType,
    role: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Issue a signed token.

    Every token carries a ``jti`` so a specific one can be revoked at logout, and an ``iat`` so a
    password change can invalidate everything issued before it.
    """
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=settings.access_token_minutes)
        if token_type is TokenType.ACCESS
        else timedelta(days=settings.refresh_token_days)
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if role is not None:
        payload["role"] = role
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_token(settings: Settings, token: str, *, expected: TokenType) -> dict[str, Any]:
    """Verify a token and return its claims.

    Raises an ``ApiError`` distinguishing expiry from invalidity, because the frontend acts on the
    difference: an expired access token means refresh silently, an invalid one means sign in again.
    """
    try:
        claims: dict[str, Any] = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise unauthorized(ErrorCode.TOKEN_EXPIRED, "Your session has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise unauthorized(ErrorCode.TOKEN_INVALID, "Your session is not valid.") from exc

    if claims.get("type") != expected.value:
        raise unauthorized(
            ErrorCode.TOKEN_INVALID,
            f"Expected a {expected.value} token.",
            provided=str(claims.get("type")),
        )
    return claims
