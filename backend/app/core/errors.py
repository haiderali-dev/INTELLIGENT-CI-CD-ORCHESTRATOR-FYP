"""One error shape for the whole API.

BUILD_PROMPT 4.4.1 fixes the wire format:

    {"error": {"code": "SERVICE_NOT_FOUND", "message": "No service named payments.", "details": {}}}

Having exactly one shape is what lets the frontend render any failure without special-casing, and
what lets the error copy rules in 4.7.5 ("say what happened and how to fix it") be enforced in one
place rather than at every call site.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class ErrorCode(StrEnum):
    """Every error code the API can return.

    An enum rather than free strings so the frontend can switch on them exhaustively and so a typo
    in a code is a type error rather than an unhandled case in the UI.
    """

    # Request and validation
    VALIDATION_FAILED = "VALIDATION_FAILED"
    BAD_REQUEST = "BAD_REQUEST"
    MESSAGE_TOO_LONG = "MESSAGE_TOO_LONG"

    # Auth
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    # The two suppressions below: these are error codes the frontend switches on, not secrets.
    TOKEN_EXPIRED = "TOKEN_EXPIRED"  # noqa: S105
    TOKEN_INVALID = "TOKEN_INVALID"  # noqa: S105
    FORBIDDEN = "FORBIDDEN"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"

    # Domain
    SERVICE_NOT_FOUND = "SERVICE_NOT_FOUND"
    BRANCH_NOT_FOUND = "BRANCH_NOT_FOUND"
    COMMIT_NOT_FOUND = "COMMIT_NOT_FOUND"
    SUITE_NOT_FOUND = "SUITE_NOT_FOUND"
    ENVIRONMENT_NOT_ALLOWED = "ENVIRONMENT_NOT_ALLOWED"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
    PIPELINE_NOT_FOUND = "PIPELINE_NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    USER_NOT_FOUND = "USER_NOT_FOUND"

    # Policy
    PRODUCTION_REFUSED = "PRODUCTION_REFUSED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    JUSTIFICATION_REQUIRED = "JUSTIFICATION_REQUIRED"
    CUSTOM_STEPS_REFUSED = "CUSTOM_STEPS_REFUSED"
    CHAIN_ALREADY_RUNNING = "CHAIN_ALREADY_RUNNING"
    RATE_LIMITED = "RATE_LIMITED"

    # Generation
    SPEC_INVALID = "SPEC_INVALID"
    RENDER_FAILED = "RENDER_FAILED"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    ALREADY_APPROVED = "ALREADY_APPROVED"

    # Upstream
    JENKINS_UNAVAILABLE = "JENKINS_UNAVAILABLE"
    GIT_UNAVAILABLE = "GIT_UNAVAILABLE"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"

    # Catch-all
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiError(Exception):
    """An error with a code, a human message and optional structured details.

    Raised from services; turned into the wire format by the handler below. Services never build
    responses themselves, which keeps routers thin as 4.4.1 requires.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details: dict[str, Any] = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details,
            }
        }


# --- Convenience constructors for the cases that recur -------------------------


def not_found(code: ErrorCode, message: str, **details: Any) -> ApiError:
    return ApiError(code, message, status_code=status.HTTP_404_NOT_FOUND, details=details)


def forbidden(code: ErrorCode, message: str, **details: Any) -> ApiError:
    return ApiError(code, message, status_code=status.HTTP_403_FORBIDDEN, details=details)


def unauthorized(code: ErrorCode, message: str, **details: Any) -> ApiError:
    return ApiError(code, message, status_code=status.HTTP_401_UNAUTHORIZED, details=details)


def conflict(code: ErrorCode, message: str, **details: Any) -> ApiError:
    return ApiError(code, message, status_code=status.HTTP_409_CONFLICT, details=details)


def unavailable(code: ErrorCode, message: str, **details: Any) -> ApiError:
    return ApiError(code, message, status_code=status.HTTP_503_SERVICE_UNAVAILABLE, details=details)


def _json(error: ApiError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content=error.to_payload())


def register_exception_handlers(app: FastAPI) -> None:
    """Route every failure through the one error shape.

    Without the last handler, an unexpected exception would return FastAPI's default HTML or a bare
    ``{"detail": ...}``, and the frontend would have two failure shapes to handle instead of one.
    """

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        # Expected failures are informational; they are the API working as designed.
        logger.info("api_error", code=exc.code.value, message=exc.message, details=exc.details)
        return _json(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Flatten Pydantic's errors into something a form can highlight per field.
        fields = {
            ".".join(str(part) for part in err["loc"][1:]) or "body": err["msg"]
            for err in exc.errors()
        }
        return _json(
            ApiError(
                ErrorCode.VALIDATION_FAILED,
                "Some fields need attention.",
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"fields": fields},
            )
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            status.HTTP_401_UNAUTHORIZED: ErrorCode.NOT_AUTHENTICATED,
            status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
            status.HTTP_404_NOT_FOUND: ErrorCode.BAD_REQUEST,
            status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
        }.get(exc.status_code, ErrorCode.BAD_REQUEST)
        return _json(ApiError(code, str(exc.detail), status_code=exc.status_code))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return none of it: an internal message can carry a connection string.
        logger.exception(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=type(exc).__name__,
        )
        return _json(
            ApiError(
                ErrorCode.INTERNAL_ERROR,
                "Something went wrong on our side. The failure has been logged.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        )
