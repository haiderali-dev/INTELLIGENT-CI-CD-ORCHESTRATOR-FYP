"""Metrics ingestion.

BUILD_PROMPT 4.4.5 lists ``POST /api/metrics`` with "plugin events, bearer ``METRICS_TOKEN``". The
caller is the plugin's ``MetricsPublisher``, not a person, which changes what a good response is:

* the publisher runs one background thread and treats any non-2xx as a failure, so this endpoint
  accepts anything shaped like an event and reports problems in its body rather than in its status.
  A 422 on an unrecognised field would make the plugin log failures and drop events, which is how
  an experiment ends up with no queue timings and nobody notices until the analysis;
* it must be fast. The publisher's queue holds 1000 events and drops beyond that, so a slow
  endpoint turns into lost data rather than backpressure.

Authentication is the bearer ``METRICS_TOKEN``, compared in constant time. It is deliberately not
the user JWT: the plugin has no user, and giving it one would mean a credential that can also drive
the API.
"""

from __future__ import annotations

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode, unauthorized
from app.core.logging import get_logger
from app.core.settings import Settings
from app.db.session import get_db
from app.services.dependencies import get_settings_dep
from app.services.metrics import ingest_event

logger = get_logger(__name__)
router = APIRouter(tags=["metrics"])

_bearer = HTTPBearer(auto_error=False, description="METRICS_TOKEN, as the plugin sends it")

# The plugin posts one event per request and its queue holds 1000, so a burst during an experiment
# is bounded by the plugin itself. A batch is accepted too, for the experiment harness replaying
# recorded events.
MAX_BATCH = 1000


class MetricEventRequest(BaseModel):
    """One plugin event.

    ``extra="allow"`` is the point: the plugin's ``MetricEvent`` carries a flat, open set of fields
    that differs per kind and grows with the plugin. The service reads the fields it knows and
    ignores the rest, so a plugin newer than the backend still delivers its data.
    """

    model_config = {"extra": "allow"}

    kind: str = Field(default="", max_length=64)
    timestamp: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


class MetricBatchRequest(BaseModel):
    events: list[MetricEventRequest] = Field(default_factory=list, max_length=MAX_BATCH)


class IngestResponse(BaseModel):
    """What happened, in the body rather than the status code.

    ``applied`` and ``parked`` are reported so the plugin's own logs and the experiment harness can
    tell "stored" from "accepted but matched nothing", which a 200 alone cannot express.
    """

    accepted: int
    applied: int = 0
    parked: int = 0
    ignored: int = 0


async def require_metrics_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> None:
    """Check the bearer token in constant time.

    ``compare_digest`` rather than ``==``: the token is long-lived and shared, and a short-circuit
    comparison leaks its prefix to anyone who can time the endpoint.
    """
    supplied = credentials.credentials if credentials else ""
    expected = settings.metrics_token
    if not expected or not supplied or not secrets.compare_digest(supplied, expected):
        client = request.client.host if request.client else "unknown"
        logger.warning("metrics_token_refused", client=client)
        raise unauthorized(
            ErrorCode.NOT_AUTHENTICATED, "A valid METRICS_TOKEN is required for this endpoint."
        )


@router.post(
    "/metrics",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest plugin metric events",
    dependencies=[Depends(require_metrics_token)],
)
async def post_metrics(
    payload: MetricEventRequest | MetricBatchRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IngestResponse:
    """Accept one event, or a batch of them.

    202 rather than 200: the event has been recorded, but what it means for a run may depend on a
    row that does not exist yet, and saying "accepted" is the honest description of that.
    """
    events = payload.events if isinstance(payload, MetricBatchRequest) else [payload]

    applied = parked = ignored = 0
    for event in events:
        result = await ingest_event(session, event.as_dict())
        if result.applied:
            applied += 1
        elif result.parked:
            parked += 1
        else:
            ignored += 1

    return IngestResponse(accepted=len(events), applied=applied, parked=parked, ignored=ignored)
