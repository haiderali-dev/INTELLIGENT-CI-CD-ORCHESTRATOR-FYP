"""Successful responses must follow commit, including at the ASGI response-start boundary.

ASGITransport buffers the entire response and dependency cleanup before returning to its caller.
Observing response.start directly exposes races that an ordinary in-process API test misses.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_type_hints

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.types import Message, Receive, Scope, Send

from app.api import generation
from app.db import session as db_session


class CommitFailedSession(AsyncSession):
    """A transaction whose commit fails after the handler has constructed its response."""

    async def commit(self) -> None:
        raise RuntimeError("commit failed")


@pytest.mark.parametrize("commit_fails", [False, True])
async def test_transaction_finishes_before_the_response_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, commit_fails: bool
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'visibility.db'}")
    factory = async_sessionmaker(
        engine,
        class_=CommitFailedSession if commit_fails else AsyncSession,
        expire_on_commit=False,
    )
    reader = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db_session, "get_session_factory", lambda: factory)

    async def write(session: AsyncSession) -> dict[str, int]:
        await session.execute(text("INSERT INTO writes (value) VALUES (1)"))
        return {"value": 1}

    write.__annotations__["session"] = get_type_hints(generation.generate, include_extras=True)[
        "session"
    ]
    application = FastAPI()
    application.post("/write", status_code=201)(write)
    observed: list[tuple[int, int]] = []

    async def observe_response(scope: Scope, receive: Receive, send: Send) -> None:
        async def observe(message: Message) -> None:
            if message["type"] == "http.response.start":
                async with reader() as session:
                    count = await session.scalar(text("SELECT COUNT(*) FROM writes"))
                observed.append((message["status"], int(count or 0)))
            await send(message)

        await application(scope, receive, observe)

    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE writes (value INTEGER NOT NULL)"))
        transport = ASGITransport(app=observe_response, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/write")
        assert response.status_code == (500 if commit_fails else 201)
        assert observed == [(500, 0) if commit_fails else (201, 1)]
    finally:
        await engine.dispose()


def test_every_request_session_finishes_before_the_response(app: FastAPI) -> None:
    late = []
    checked = 0
    routes = list(app.routes)
    while routes:
        route = routes.pop()
        included = getattr(route, "original_router", None)
        if included is not None:
            routes.extend(included.routes)
        if not isinstance(route, APIRoute):
            continue
        pending = [route.dependant]
        while pending:
            dependency = pending.pop()
            if dependency.call is db_session.get_db:
                checked += 1
                if dependency.scope != "function":
                    late.append(f"{route.path}: {dependency.name}")
            pending.extend(dependency.dependencies)
    assert checked > 0
    assert not late, late
