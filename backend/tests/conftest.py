"""Shared fixtures.

Every fixture here keeps the suite offline: SQLite in memory instead of PostgreSQL, and
``FakeJenkinsClient`` instead of a controller. That is what makes ``pytest -m "not live and not
e2e"`` runnable with no Docker, which matters because Docker is not available on the machine this
was built on.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.ratelimit import get_rate_limiter
from app.core.settings import Environment, LlmMode, Settings, get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import create_app
from app.services.auth import get_revoked_tokens
from app.services.dependencies import get_jenkins_client, get_settings_dep
from app.services.jenkins import FakeJenkinsClient
from app.services.metrics import get_pending_timings


@pytest.fixture(autouse=True)
def _reset_process_state() -> None:
    """Clear every piece of process-wide state between tests.

    Rate-limit buckets, the refresh-token denylist and parked queue timings all live in module
    globals by design (D-020, D-021, D-027), so without this they leak across tests. That is not
    hypothetical: the login limit is five a minute, so ``test_auth``'s rate-limit tests exhausted
    it for the whole suite and a later file's sign-in got a 429 it never asked about -- a failure
    that reproduced only in a full run and passed in isolation.

    Here rather than per file, so a new test file cannot reintroduce it by forgetting.
    """
    get_rate_limiter().reset()
    get_revoked_tokens().clear()
    get_pending_timings().clear()


@pytest.fixture
def settings() -> Settings:
    """Test settings: in-memory SQLite, fake LLM, generated secrets."""
    return Settings(
        environment=Environment.TEST,
        database_url="sqlite+aiosqlite:///:memory:",
        llm_mode=LlmMode.FAKE,
        jenkins_url="http://jenkins-dev:8080",
        jenkins_user="orchestrator-bot",
        jenkins_token="test-token",
        seed_admin_email="admin@example.com",
        seed_admin_password="test-admin-password",
    )


@pytest.fixture
async def engine(settings: Settings) -> AsyncGenerator[AsyncEngine]:
    """A fresh in-memory database per test, with the schema created from the models.

    ``create_all`` rather than running Alembic: a unit test should fail because of the code under
    test, not because a migration is mid-edit. ``tests/test_migrations.py`` checks separately that
    the migrations and the models agree.
    """
    test_engine = create_async_engine(
        settings.database_url, connect_args={"check_same_thread": False}
    )
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield test_engine
    await test_engine.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """A session bound to the test engine."""
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session


@pytest.fixture
def fake_jenkins() -> FakeJenkinsClient:
    return FakeJenkinsClient()


@pytest.fixture
def app(
    settings: Settings, engine: AsyncEngine, fake_jenkins: FakeJenkinsClient
) -> Generator[FastAPI]:
    """An application wired to the test database and the fake Jenkins."""
    db_session.configure(engine)
    get_settings.cache_clear()

    application = create_app(settings)
    application.dependency_overrides[get_settings_dep] = lambda: settings
    application.dependency_overrides[get_jenkins_client] = lambda: fake_jenkins

    yield application

    application.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient]:
    """An HTTP client speaking to the app in-process, with no socket involved."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
