"""Health endpoints.

BUILD_PROMPT's Phase 3 acceptance is that ``GET /api/health`` reports database, Jenkins and LLM
provider. Each dependency is probed concurrently and reported separately, because "the backend is
unhealthy" is not actionable while "Jenkins is unreachable at this URL" is.
"""

from __future__ import annotations

import asyncio
import time
from enum import StrEnum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.settings import LlmMode, Settings
from app.db.session import get_db
from app.services.dependencies import get_jenkins_client, get_settings_dep
from app.services.jenkins import JenkinsClient

router = APIRouter(tags=["system"])
logger = get_logger(__name__)

# A health probe must answer quickly even when a dependency hangs, or an orchestration platform
# cannot tell "slow" from "down".
PROBE_TIMEOUT_SECONDS = 5.0


class ComponentStatus(StrEnum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"
    # A dependency that is deliberately not in use, such as the LLM in fake mode. Reported
    # separately so it never looks like a failure.
    DISABLED = "disabled"


class ComponentHealth(BaseModel):
    status: ComponentStatus
    detail: str
    latency_ms: int | None = None


class HealthResponse(BaseModel):
    status: ComponentStatus
    version: str
    environment: str
    components: dict[str, ComponentHealth]


async def _probe(name: str, coro: Any) -> tuple[str, ComponentHealth]:
    """Run one probe with a timeout, converting any failure into a reported status."""
    started = time.perf_counter()
    try:
        detail = await asyncio.wait_for(coro, timeout=PROBE_TIMEOUT_SECONDS)
        elapsed = int((time.perf_counter() - started) * 1000)
        return name, ComponentHealth(status=ComponentStatus.UP, detail=detail, latency_ms=elapsed)
    except TimeoutError:
        elapsed = int((time.perf_counter() - started) * 1000)
        return name, ComponentHealth(
            status=ComponentStatus.DOWN,
            detail=f"did not respond within {PROBE_TIMEOUT_SECONDS:.0f}s",
            latency_ms=elapsed,
        )
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        logger.warning("health_probe_failed", component=name, error=type(exc).__name__)
        # The type and message, not a traceback: this response is world-readable to anyone who can
        # reach the endpoint.
        return name, ComponentHealth(
            status=ComponentStatus.DOWN,
            detail=f"{type(exc).__name__}: {exc}"[:200],
            latency_ms=elapsed,
        )


async def _check_database(session: AsyncSession) -> str:
    await session.execute(text("SELECT 1"))
    return "reachable"


async def _check_jenkins(client: JenkinsClient) -> str:
    version = await client.version()
    return f"Jenkins {version}"


async def _check_llm(settings: Settings) -> str:
    """Report the provider without spending quota.

    Deliberately does not call the model. A health endpoint polled every few seconds would burn the
    free tier's 1,000 daily requests within an hour, so this reports configuration and reachability
    intent rather than making a completion call.
    """
    if settings.llm_mode is LlmMode.FAKE:
        return "fake provider; no network calls"
    if settings.llm_mode is LlmMode.REPLAY:
        return "replay provider; serving recorded fixtures"
    if not settings.groq_api_key:
        raise RuntimeError("LLM_MODE=live but GROQ_API_KEY is empty")
    return f"live; chain {' -> '.join(settings.model_chain)}"


@router.get("/health/live", summary="Liveness probe")
async def liveness() -> dict[str, str]:
    """Is the process up? Deliberately has no dependencies.

    Separate from ``/health`` so a container orchestrator does not restart a healthy backend just
    because PostgreSQL is briefly unavailable.
    """
    return {"status": "ok"}


@router.get("/health", response_model=HealthResponse, summary="Dependency health")
async def health(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    jenkins: Annotated[JenkinsClient, Depends(get_jenkins_client)],
) -> HealthResponse:
    """Probe every dependency concurrently and report each one.

    Returns 503 when a component the system cannot work without is down, so an automated check can
    act on the status code alone.
    """
    results = await asyncio.gather(
        _probe("database", _check_database(session)),
        _probe("jenkins", _check_jenkins(jenkins)),
        _probe("llm", _check_llm(settings)),
    )
    components = dict(results)

    if settings.llm_mode is not LlmMode.LIVE:
        components["llm"].status = ComponentStatus.DISABLED

    # The database is required. Jenkins being down degrades the system rather than killing it: the
    # assistants cannot create jobs, but sign-in, history and analytics all still work.
    if components["database"].status is ComponentStatus.DOWN:
        overall = ComponentStatus.DOWN
    elif components["jenkins"].status is ComponentStatus.DOWN:
        overall = ComponentStatus.DEGRADED
    else:
        overall = ComponentStatus.UP

    if overall is ComponentStatus.DOWN:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=overall,
        version="0.1.0",
        environment=settings.environment.value,
        components=components,
    )
