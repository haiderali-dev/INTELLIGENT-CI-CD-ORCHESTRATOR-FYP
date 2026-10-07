"""FastAPI application factory.

A factory rather than a module-level ``app`` so tests can build an instance with their own settings
instead of mutating a global one.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, health, metrics
from app.core.errors import register_exception_handlers
from app.core.logging import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    configure_logging,
    get_logger,
)
from app.core.settings import Environment, Settings, get_settings
from app.db import session as db_session
from app.services.dependencies import close_clients, get_jenkins_client
from app.services.metrics import get_pending_timings
from app.services.tracker import RunTracker
from app.ws import routes as ws_routes
from app.ws.hub import get_hub

logger = get_logger(__name__)

API_PREFIX = "/api"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Start and stop the process-wide resources."""
    settings: Settings = app.state.settings
    logger.info(
        "startup",
        environment=settings.environment.value,
        llm_mode=settings.llm_mode.value,
        jenkins_url=settings.jenkins_url,
    )
    tracker: RunTracker | None = None
    # Not in tests: a background task polling Jenkins would make every test's timing depend on a
    # worker it did not ask for, and the tests that want one construct it themselves.
    if settings.environment is not Environment.TEST:
        tracker = RunTracker(
            session_factory=db_session.get_session_factory(),
            jenkins=get_jenkins_client(),
            hub=get_hub(),
            pending_timings=get_pending_timings(),
        )
        tracker.start()
    app.state.tracker = tracker

    try:
        yield
    finally:
        if tracker is not None:
            await tracker.stop()
        await get_hub().close()
        await close_clients()
        await db_session.dispose()
        logger.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    Production deployment is out of scope for this project, and the code refuses it rather than
    merely omitting it (BUILD_PROMPT rule 1.5). Refusing at construction is the only place the
    refusal cannot be bypassed by a later request.
    """
    settings = settings or get_settings()

    if settings.environment is Environment.PRODUCTION:
        raise RuntimeError(
            "This project is scoped to staging environments only. "
            "Production deployment is refused by policy; see BUILD_PROMPT rule 1.5."
        )

    configure_logging(
        json_output=settings.environment is not Environment.DEV,
        level=logging.INFO,
    )

    app = FastAPI(
        title="Intelligent CI/CD Orchestrator",
        description=(
            "Two AI assistants turn plain English into Jenkins jobs; a Jenkins plugin orders the "
            "build queue. Staging environments only."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Order matters: the request-id middleware must wrap CORS so a rejected pre-flight is still
    # logged with an id.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(metrics.router)
    app.include_router(api)
    # WS /ws sits at the root, not under /api: 4.4.4 lists it that way, and it is a different
    # protocol rather than another REST resource.
    app.include_router(ws_routes.router)

    return app


# Deliberately no module-level `app`. Constructing one at import time means importing this module
# for any reason -- a test, mypy, a tooling script -- requires a complete valid configuration, and
# the fail-fast settings check then turns a missing JWT_SECRET into a collection error rather than a
# clear startup message. Uvicorn is pointed at the factory instead:
#
#     uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000
