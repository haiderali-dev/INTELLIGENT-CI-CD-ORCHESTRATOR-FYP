"""Structured JSON logging with a request id on every line.

BUILD_PROMPT 4.4.1 asks for structured JSON logs carrying a request id. The id is held in a
``ContextVar`` rather than passed around, so a log call deep inside a service carries it without
every function signature growing a correlation parameter.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)

REQUEST_ID_HEADER = "X-Request-ID"


def get_request_id() -> str | None:
    """The current request's id, if there is one."""
    return _REQUEST_ID.get()


def set_request_id(request_id: str) -> None:
    _REQUEST_ID.set(request_id)


def _add_request_id(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    request_id = _REQUEST_ID.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(*, json_output: bool = True, level: int = logging.INFO) -> None:
    """Install structlog, routing stdlib logging through it too.

    Third-party libraries log through stdlib, and a mixture of JSON and plain lines is unparseable,
    so stdlib records are rendered by the same processors.
    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_request_id,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    # structlog logs through stdlib rather than writing directly. Two reasons: `add_logger_name`
    # reads `logger.name`, which only a stdlib logger has, so a PrintLogger crashes the logging
    # call itself the first time anything is logged with it; and routing both structlog and
    # third-party records through one handler means one renderer and one output stream instead of
    # two interleaving on stdout.
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Uvicorn's access log duplicates the request middleware below.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """A bound logger for a module."""
    return structlog.stdlib.get_logger(name)


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, logs one line per request, and echoes the id back.

    The id is taken from the inbound header when present so a trace can span the frontend and the
    backend, and generated otherwise.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        set_request_id(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)

        logger = get_logger("app.request")
        try:
            response = await call_next(request)
        except Exception:
            # The error handler renders the response; this only records that the request failed.
            logger.exception("request_failed", method=request.method, path=request.url.path)
            raise
        finally:
            structlog.contextvars.unbind_contextvars("request_id")

        response.headers[REQUEST_ID_HEADER] = request_id
        # Health checks are polled constantly and would drown the log.
        if request.url.path not in ("/api/health", "/api/health/live"):
            logger.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
            )
        return response
