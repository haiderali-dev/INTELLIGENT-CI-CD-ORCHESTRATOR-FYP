"""Chains: the run card and cancelling (T5.7).

4.6.4: "Cancelling a chain cancels queued members and stops the running one." 4.7.4's run card
shows "queue position, score bar and waiting reason, then stage progress, then result". Neither
has an endpoint in 4.4.4's table, which predates chains as a thing the API names; added and
recorded in docs/decisions.md D-047.

Chains are read by any signed-in user, like runs: the queue is shared, and a team member waiting
behind someone else's chain should be able to see what it is doing. Cancelling is for the person
who started it, or DevOps and Admin.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ApiRateLimit, CurrentUser
from app.db.models import Chain, ChainStatus
from app.db.session import get_db
from app.services import chains as service
from app.services.dependencies import get_jenkins_client, get_plugin_client
from app.services.jenkins import JenkinsClient
from app.services.plugin import PluginClient
from app.services.runs import clamp_page, count_rows

router = APIRouter(tags=["chains"])


class ChainSummary(BaseModel):
    id: str
    pipeline_id: str | None
    service: str
    job_type: str
    status: str
    jobs: list[str]
    position: int
    started_by: str | None
    started_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, chain: Chain) -> ChainSummary:
        return cls(
            id=chain.id,
            pipeline_id=chain.pipeline_id,
            service=chain.service,
            job_type=chain.job_type,
            status=chain.status,
            jobs=list(chain.jobs),
            position=chain.position,
            started_by=chain.started_by,
            started_at=chain.started_at,
            finished_at=chain.finished_at,
        )


class ChainPage(BaseModel):
    items: list[ChainSummary]
    total: int
    limit: int
    offset: int


@router.get("/chains", response_model=ChainPage, dependencies=[ApiRateLimit])
async def list_chains(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    service: str | None = None,
    active: bool = False,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int | None, Query(ge=0)] = None,
) -> ChainPage:
    resolved_limit, resolved_offset = clamp_page(limit, offset)
    statement = select(Chain)
    if service:
        statement = statement.where(Chain.service == service)
    if active:
        statement = statement.where(Chain.status == ChainStatus.RUNNING.value)
    total = await count_rows(session, statement)
    rows = (
        await session.scalars(
            statement.order_by(Chain.started_at.desc())
            .limit(resolved_limit)
            .offset(resolved_offset)
        )
    ).all()
    return ChainPage(
        items=[ChainSummary.of(chain) for chain in rows],
        total=total,
        limit=resolved_limit,
        offset=resolved_offset,
    )


@router.get("/chains/{chain_id}", dependencies=[ApiRateLimit])
async def get_chain(
    chain_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    jenkins: Annotated[JenkinsClient, Depends(get_jenkins_client)],
    plugin: Annotated[PluginClient, Depends(get_plugin_client)],
) -> dict[str, Any]:
    """The run card: each job's state and run, Pipeline stages, and the queue position."""
    chain = await service.get_chain(session, chain_id)
    return await service.run_card(session, chain, jenkins=jenkins, plugin=plugin)


@router.post("/chains/{chain_id}/cancel", dependencies=[ApiRateLimit])
async def cancel_chain(
    chain_id: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
    jenkins: Annotated[JenkinsClient, Depends(get_jenkins_client)],
) -> dict[str, Any]:
    chain = await service.get_chain(session, chain_id)
    return await service.cancel(session, jenkins=jenkins, chain=chain, actor=user)
