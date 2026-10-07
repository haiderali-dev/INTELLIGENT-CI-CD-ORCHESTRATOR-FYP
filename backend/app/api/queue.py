"""``GET /api/queue``.

BUILD_PROMPT 4.4.4 lists it; 4.3.10 is where the data comes from. The plugin's ranking endpoint is
the only place the score components, group id, topological rank and blocked reason exist — none of
them are derivable from Jenkins' own queue API, because the plugin computes them.

The endpoint answers 200 even when the plugin cannot be read, with ``available: false`` and a
reason. ``jenkins-baseline`` runs without the plugin on purpose, and a Queue page that 500s on that
controller would be worse than one that says the ranking is unavailable: the second is a fact about
the environment, the first looks like a broken backend.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.services.dependencies import get_plugin_client
from app.services.plugin import PluginClient, RankedItem


class ScoreComponentsResponse(BaseModel):
    """Algorithm 1 broken out, so the UI can explain a rank instead of only showing it."""

    urgency: float
    dependency: float
    execution_time: float
    aging_bonus: float
    base_score: float


class QueueItemResponse(BaseModel):
    rank: int
    item_id: int
    job_name: str
    job_type: str
    level: str
    score: float
    components: ScoreComponentsResponse
    estimate_seconds: float | None
    wait_seconds: float
    group_id: str | None
    topological_rank: int | None
    blocked_reason: str | None
    unresolved_dependencies: list[str]

    @classmethod
    def of(cls, item: RankedItem) -> QueueItemResponse:
        return cls(
            rank=item.rank,
            item_id=item.item_id,
            job_name=item.job_name,
            job_type=item.job_type,
            level=item.level,
            score=item.score,
            components=ScoreComponentsResponse(
                urgency=item.components.urgency,
                dependency=item.components.dependency,
                execution_time=item.components.execution_time,
                aging_bonus=item.components.aging_bonus,
                base_score=item.components.base_score,
            ),
            estimate_seconds=item.estimate_seconds,
            wait_seconds=item.wait_seconds,
            group_id=item.group_id,
            topological_rank=item.topological_rank,
            blocked_reason=item.blocked_reason,
            unresolved_dependencies=list(item.unresolved_dependencies),
        )


class QueueResponse(BaseModel):
    available: bool = Field(
        description="False when the plugin could not be read; items is then empty"
    )
    optimizer_enabled: bool
    queue_length: int
    weights: dict[str, float]
    items: list[QueueItemResponse]
    unavailable_reason: str | None = None


router = APIRouter(tags=["queue"])


@router.get("/queue", response_model=QueueResponse, summary="The prioritised build queue")
async def get_queue(
    user: CurrentUser,
    plugin: Annotated[PluginClient, Depends(get_plugin_client)],
) -> QueueResponse:
    """The plugin's ranking of the buildable queue.

    ``available: false`` with a reason rather than an error status: the caller's request was fine,
    and the only controller-dependent fact is whether the plugin is there to ask.
    """
    ranking = await plugin.ranking()
    return QueueResponse(
        available=ranking.available,
        optimizer_enabled=ranking.optimizer_enabled,
        queue_length=ranking.queue_length,
        weights=ranking.weights,
        items=[QueueItemResponse.of(item) for item in ranking.items],
        unavailable_reason=ranking.unavailable_reason,
    )
