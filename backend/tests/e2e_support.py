"""Shared setup for the end-to-end suite (T5.8): the real app, on the Compose stack.

What is real: the FastAPI app and every router, PostgreSQL (the stack's own server, in a database
of its own), ``jenkins-dev`` with its agents, the plugin, Git against GitHub, the run tracker, and
the deploys the chains make. What is not: the HTTP socket -- requests go through ``ASGITransport``,
which is the same app object without a port -- and, by default, the model.

**The model.** ``E2E_LLM`` chooses:

* ``replay`` (the default when no Groq key is set, as T5.8 says): recorded answers from
  ``app/ai/fixtures``, so the suite needs no key and no quota. A missing fixture falls back to the
  rules, which the tests catch: in replay mode every parse must come from a fixture.
* ``live`` (the default when a key is set): Groq directly, for a run against the model as it is.
* ``record``: Groq through ``RecordingProvider``, saving each answer as a fixture. Run once after
  any prompt or catalog change, then commit ``app/ai/fixtures``.

**The database** is ``orchestrator_e2e`` on the stack's PostgreSQL, dropped, recreated and migrated
with Alembic once per session -- the migrations, not ``create_all``, so the suite also proves the
schema the backend actually runs on.

Credentials come from ``.env`` (read, never printed), like the integration suite's.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import asyncpg
import httpx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.ai.cache import ResponseCache
from app.ai.factory import FIXTURES_DIR, build_intent_parser
from app.ai.providers import GroqProvider, LLMProvider, RecordingProvider, ReplayProvider
from app.ai.quota import QuotaTracker
from app.api.deps import get_intent_parser, get_planner
from app.core.security import hash_password
from app.core.settings import Environment, LlmMode, Settings, get_settings
from app.db import session as db_session
from app.db.models import Role, User
from app.generation.factory import build_planner
from app.main import create_app
from app.services.catalog import Catalog, catalog_path
from app.services.dependencies import (
    get_catalog,
    get_git_client,
    get_jenkins_client,
    get_plugin_client,
    get_settings_dep,
)
from app.services.git import CliGitClient
from app.services.jenkins import HttpJenkinsClient
from app.services.plugin import HttpPluginClient
from app.services.tracker import RunTracker
from app.ws.hub import Hub
from tests.test_integration_jenkins import read_env

BACKEND: Final = Path(__file__).resolve().parents[1]
REPO_ROOT: Final = BACKEND.parent
E2E_DATABASE: Final = "orchestrator_e2e"
PASSWORD: Final = "e2e-password-not-a-secret"
CHAIN_TIMEOUT_SECONDS: Final = 900.0
POLL_SECONDS: Final = 3.0


def llm_mode() -> str:
    """``E2E_LLM`` if set; otherwise live with a Groq key and replay without one.

    T5.8: "using replay fixtures when no Groq key is set". ``verify.py`` pins ``replay`` so the
    Phase 5 gate is deterministic and never spends quota.
    """
    configured = os.environ.get("E2E_LLM", "").strip().lower()
    mode = configured or ("live" if groq_key() else "replay")
    if mode not in {"replay", "record", "live"}:
        raise ValueError(f"E2E_LLM must be replay, record or live, not {mode!r}")
    return mode


def groq_key() -> str:
    """From the environment, else from .env. Never printed."""
    if os.environ.get("GROQ_API_KEY"):
        return os.environ["GROQ_API_KEY"]
    return read_env().get("GROQ_API_KEY", "")


def database_url(name: str = E2E_DATABASE) -> str:
    env = read_env()
    user = env.get("POSTGRES_USER", "orchestrator")
    return f"postgresql+asyncpg://{user}:{env['POSTGRES_PASSWORD']}@127.0.0.1:5432/{name}"


async def _admin(sql: str) -> None:
    env = read_env()
    connection = await asyncpg.connect(
        host="127.0.0.1",
        port=5432,
        user=env.get("POSTGRES_USER", "orchestrator"),
        password=env["POSTGRES_PASSWORD"],
        database=env.get("POSTGRES_DB", "orchestrator"),
    )
    try:
        await connection.execute(sql)
    finally:
        await connection.close()


def recreate_database() -> None:
    """Drop, create and migrate the e2e database. Raises if the stack's PostgreSQL is absent."""
    asyncio.run(_admin(f"DROP DATABASE IF EXISTS {E2E_DATABASE} WITH (FORCE)"))
    asyncio.run(_admin(f"CREATE DATABASE {E2E_DATABASE}"))
    env = {
        **os.environ,
        "ENVIRONMENT": "test",
        "DATABASE_URL": database_url(),
        # Settings refuse to start without these outside tests; the migration does not use them.
        "JWT_SECRET": "e2e-only-" + "x" * 40,
        "METRICS_TOKEN": "e2e-only-metrics-token",
    }
    done = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError("alembic upgrade head failed: " + done.stderr.strip()[-500:])


def settings_for_e2e() -> Settings:
    env = read_env()
    mode = llm_mode()
    return Settings(
        environment=Environment.TEST,
        database_url=database_url(),
        jenkins_url=env.get("JENKINS_URL_HOST", "http://localhost:8087"),
        jenkins_user=env["JENKINS_USER"],
        jenkins_token=env["JENKINS_TOKEN"],
        llm_mode=LlmMode.REPLAY if mode == "replay" else LlmMode.LIVE,
        groq_api_key=groq_key() if mode != "replay" else "",
    )


def provider_for(mode: str, key: str) -> LLMProvider:
    if mode == "replay":
        return ReplayProvider(FIXTURES_DIR)
    if mode == "record":
        return RecordingProvider(GroqProvider(key), FIXTURES_DIR)
    return GroqProvider(key)


@dataclass
class Stack:
    client: AsyncClient
    settings: Settings
    jenkins: HttpJenkinsClient
    tracker: RunTracker
    mode: str


# One quota for the whole session, so recording against Groq is paced across tests. The provider is
# not shared: each test runs on its own event loop, and a client whose pooled connections belong to
# a closed loop fails with "Event loop is closed" on its next request -- which the first recording
# run hit, and which made the chain fall back to the second model for no reason of its own.
_QUOTA = QuotaTracker()


async def stack() -> AsyncGenerator[Stack]:
    settings = settings_for_e2e()
    mode = llm_mode()
    if mode != "replay" and not settings.groq_api_key:
        raise RuntimeError(f"E2E_LLM={mode} needs GROQ_API_KEY")
    provider: LLMProvider = provider_for(mode, settings.groq_api_key)
    quota = _QUOTA

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    db_session.configure(engine)
    get_settings.cache_clear()
    catalog = Catalog(catalog_path(settings))
    jenkins = HttpJenkinsClient(settings)
    plugin = HttpPluginClient(settings)
    git = CliGitClient()
    cache = ResponseCache()

    app = create_app(settings)
    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_jenkins_client] = lambda: jenkins
    app.dependency_overrides[get_plugin_client] = lambda: plugin
    app.dependency_overrides[get_git_client] = lambda: git
    app.dependency_overrides[get_catalog] = lambda: catalog
    app.dependency_overrides[get_intent_parser] = lambda: build_intent_parser(
        settings,
        catalog=catalog,
        git=git,
        provider=provider,
        has_models=True,
        quota=quota,
        cache=cache,
        max_wait=65.0,
    )
    app.dependency_overrides[get_planner] = lambda: build_planner(
        settings, catalog=catalog, provider=provider, has_models=True, quota=quota, max_wait=65.0
    )

    # The lifespan does not run under ASGITransport, so the tracker is started here, exactly as
    # the lifespan would start it, and handed to the app the same way.
    tracker = RunTracker(
        session_factory=db_session.get_session_factory(),
        jenkins=jenkins,
        hub=Hub(),
        poll_seconds=2.0,
    )
    app.state.tracker = tracker
    tracker.start()
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e", timeout=120.0)
    try:
        yield Stack(client=client, settings=settings, jenkins=jenkins, tracker=tracker, mode=mode)
    finally:
        await tracker.stop()
        await client.aclose()
        await jenkins.aclose()
        await plugin.aclose()
        await git.aclose()
        await provider.aclose()
        app.dependency_overrides.clear()
        await engine.dispose()
        get_settings.cache_clear()


async def sign_in(stack: Stack, role: Role = Role.DEVELOPER) -> dict[str, str]:
    """A user of this role, created on first use, and their bearer header."""
    email = f"e2e-{role.value.lower()}@example.com"
    async with db_session.get_session_factory()() as session:
        existing = (await session.scalars(select(User).where(User.email == email))).first()
        if existing is None:
            session.add(
                User(
                    email=email, password_hash=hash_password(PASSWORD), role=role.value, active=True
                )
            )
            await session.commit()
    response = await stack.client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def say(stack: Stack, headers: dict[str, str], chat: str, text: str) -> dict[str, Any]:
    response = await stack.client.post(
        f"/api/conversations/{chat}/messages", headers=headers, json={"text": text}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    if stack.mode == "replay" and body["command"] is not None:
        # Every parse in replay mode must come from a fixture; a fallback to the rules would mean
        # the fixture set is stale and the test was not exercising the recorded model at all.
        assert body["command"]["parser"] == "LLM", (
            f"no replay fixture for {text!r}: re-record with E2E_LLM=record"
        )
    return body


async def new_chat(stack: Stack, headers: dict[str, str], assistant: str = "freestyle") -> str:
    response = await stack.client.post(
        f"/api/assistants/{assistant}/conversations", headers=headers
    )
    response.raise_for_status()
    chat: str = response.json()["id"]
    return chat


async def generate(stack: Stack, headers: dict[str, str], command_id: str) -> dict[str, Any]:
    response = await stack.client.post(f"/api/commands/{command_id}/generate", headers=headers)
    assert response.status_code == 201, response.text
    pipeline: dict[str, Any] = response.json()
    if stack.mode == "replay" and pipeline["plan"] is not None:
        assert pipeline["plan"]["source"] == "model", "no replay fixture for the plan"
    return pipeline


async def approve(stack: Stack, headers: dict[str, str], pipeline_id: str) -> dict[str, Any]:
    response = await stack.client.post(
        f"/api/pipelines/{pipeline_id}/approve",
        headers={**headers, "Idempotency-Key": f"e2e-{pipeline_id}"},
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["result"]
    return result


async def wait_for_chain(stack: Stack, headers: dict[str, str], chain_id: str) -> dict[str, Any]:
    """Poll the run card until the chain finishes. The tracker does the work in the background."""
    deadline = asyncio.get_running_loop().time() + CHAIN_TIMEOUT_SECONDS
    card: dict[str, Any] = {}
    while asyncio.get_running_loop().time() < deadline:
        response = await stack.client.get(f"/api/chains/{chain_id}", headers=headers)
        response.raise_for_status()
        card = response.json()
        if card["status"] != "RUNNING":
            return card
        await asyncio.sleep(POLL_SECONDS)
    raise AssertionError(
        f"chain {chain_id} still running after {CHAIN_TIMEOUT_SECONDS:.0f}s: {card}"
    )


def service_url(service: str, path: str) -> httpx.Response:
    """A request to a deployed staging service, from the host."""
    port = {"payment-service": 9001, "auth-service": 9002}[service]
    return httpx.get(f"http://localhost:{port}{path}", timeout=10.0)
