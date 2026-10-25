"""The backend the browser flows run against (T6.8): the real app in fake mode, and nothing outside.

BUILD_PROMPT 4.7.6 runs the Playwright flows "against the backend with ``LLM_MODE=fake``". The
Playwright configuration (``frontend/playwright.config.ts``) starts this module as a process of its
own, so the flows talk to a real server over HTTP and a WebSocket, through the Vite dev server's
proxy, exactly as the app does on a developer's machine.

**What is real:** the FastAPI app with every router, the policy and the generators, the run tracker,
the WebSocket hub, the rate limits, sign-in and token rotation, and the app's own seeders.

**What is not:**

* **The model**, in fake mode: answers come from the rule parser, as if from the model. It is
  wrapped so a flow can switch it off and see the rule parser answer with ``ai_fallback`` set, as
  it would with Groq unreachable.
* **Jenkins, its plugin and Git** are the in-memory stand-ins the backend's own tests use
  (``FakeJenkinsClient``, ``FakePluginClient``, ``FakeGitClient``). So no Jenkins, network or
  credential is needed, and CI can run the flows, as CI runs nothing that needs a Jenkins.
* **The database** is SQLite in a temporary directory, made fresh for each run from the models.

**The accounts** (an Admin and a Developer) come from the environment the Playwright configuration
sets, with passwords made up for each run. Every setting that could hold a secret is set here, so
a ``.env`` file in the working directory is never the source of one.

**The control routes** under ``/__e2e`` exist on this process's app only, never in the application:
a flow sets the plugin's ranking through them, switches the model off and on, and releases the
per-service chain locks its approvals took.

Run from ``backend/``: ``uv run --no-sync python browser_backend.py``.
"""

from __future__ import annotations

import asyncio
import atexit
import os
import secrets
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Any

PORT = int(os.environ.get("E2E_BACKEND_PORT", "8799"))
FRONTEND_ORIGIN = os.environ.get("E2E_FRONTEND_ORIGIN", "http://localhost:5174")


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"{name} is not set. The Playwright configuration sets it for each run.")
    return value


ADMIN_EMAIL = _required("E2E_ADMIN_EMAIL")
ADMIN_PASSWORD = _required("E2E_ADMIN_PASSWORD")
DEVELOPER_EMAIL = _required("E2E_DEVELOPER_EMAIL")
DEVELOPER_PASSWORD = _required("E2E_DEVELOPER_PASSWORD")

WORKDIR = Path(tempfile.mkdtemp(prefix="orchestrator-browser-"))
atexit.register(shutil.rmtree, WORKDIR, ignore_errors=True)
CATALOG_SOURCE = Path(__file__).resolve().parent.parent / "catalog" / "services.yaml"
for name in ("services.yaml", "services.schema.json"):
    shutil.copy2(CATALOG_SOURCE.with_name(name), WORKDIR / name)


def _archived_evaluation() -> str:
    """The archived evaluation report, so the Analytics page shows the same figures on every
    machine and in CI, never whatever a local eval/results happens to hold."""
    archive = Path(__file__).resolve().parent.parent / "docs" / "evaluation"
    reports = sorted(archive.glob("*/report/report.json"))
    return str(reports[-1] if reports else WORKDIR / "no-evaluation-report.json")


# Before anything from `app` is imported, so the settings every module reads are these. Each one
# that could carry a secret is set, which keeps a local .env from supplying it.
os.environ.update(
    {
        "ENVIRONMENT": "dev",
        "DATABASE_URL": f"sqlite+aiosqlite:///{(WORKDIR / 'browser.db').as_posix()}",
        "LLM_MODE": "fake",
        "GROQ_API_KEY": "",
        "JENKINS_URL": "http://jenkins.invalid:8080",
        "JENKINS_USER": "browser-flows",
        "JENKINS_TOKEN": "not-a-token",
        "JWT_SECRET": secrets.token_urlsafe(32),
        "METRICS_TOKEN": secrets.token_urlsafe(16),
        "SEED_ADMIN_EMAIL": ADMIN_EMAIL,
        "SEED_ADMIN_PASSWORD": ADMIN_PASSWORD,
        "FRONTEND_ORIGIN": FRONTEND_ORIGIN,
        "EVALUATION_REPORT_PATH": _archived_evaluation(),
        "CATALOG_PATH": str(WORKDIR / "services.yaml"),
    }
)

import uvicorn  # noqa: E402
from fastapi import APIRouter, Body, Depends, FastAPI  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.ai.factory import build_intent_parser  # noqa: E402
from app.ai.parser import IntentParser  # noqa: E402
from app.ai.providers import ChatMessage, FakeProvider, ProviderRejectedError  # noqa: E402
from app.ai.rules import RuleBasedParser  # noqa: E402
from app.api.deps import get_intent_parser  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.settings import LlmMode, Settings, get_settings  # noqa: E402
from app.db import session as db_session  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Chain, ChainStatus, Role, User  # noqa: E402
from app.db.seed import seed_admin, seed_catalog  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import chains as chain_service  # noqa: E402
from app.services.catalog import Catalog  # noqa: E402
from app.services.dependencies import (  # noqa: E402
    get_catalog,
    get_git_client,
    get_settings_dep,
    set_git_client,
    set_jenkins_client,
    set_plugin_client,
)
from app.services.git import FakeGitClient, GitClient  # noqa: E402
from app.services.jenkins import FakeJenkinsClient  # noqa: E402
from app.services.plugin import FakePluginClient, Ranking, parse_ranking  # noqa: E402

# The repositories the catalog names, as the backend tests' Git stand-in has them.
BRANCHES = {
    "main": "3f786850e387550fdab836ed7e6dc881de23001b",
    "demo/failing-tests": "89e6c98d92887913cadf06b2adb97f26cde4849b",
}


class SwitchableModel:
    """Fake mode's model, which a flow can switch off: then every call fails, as Groq's would."""

    def __init__(self, catalog: Catalog) -> None:
        self._rules = RuleBasedParser(catalog)
        self.answering = True
        self.provider = FakeProvider(responder=self._respond)

    def _respond(
        self, system: str, messages: list[ChatMessage], schema: dict[str, Any], model: str
    ) -> dict[str, Any]:
        if not self.answering:
            raise ProviderRejectedError("the browser flows switched the model off")
        # Fake mode's own answer (app/ai/factory.py): the rule parser's reading, as the model's.
        return self._rules.parse_intent(messages[-1].content).to_card()


async def prepare(settings: Settings) -> None:
    """A fresh schema, the catalog, the seed Admin and a Developer, with the app's own seeders."""
    engine = create_async_engine(settings.database_url, connect_args={"check_same_thread": False})
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    db_session.configure(engine)
    async with db_session.get_session_factory()() as session:
        await seed_catalog(session, settings)
        await seed_admin(session, settings)
        session.add(
            User(
                email=DEVELOPER_EMAIL.strip().lower(),
                password_hash=hash_password(DEVELOPER_PASSWORD),
                role=Role.DEVELOPER.value,
                active=True,
            )
        )
        await session.commit()


def control_router(
    model: SwitchableModel, plugin: FakePluginClient, jenkins: FakeJenkinsClient
) -> APIRouter:
    """What a flow may change between its steps. Only this process mounts it."""
    router = APIRouter(prefix="/__e2e", tags=["browser flows"])

    @router.post("/model")
    async def switch_model(answering: Annotated[bool, Body(embed=True)]) -> dict[str, bool]:
        model.answering = answering
        return {"answering": model.answering}

    @router.post("/ranking")
    async def set_ranking(body: Annotated[dict[str, Any], Body()]) -> dict[str, int]:
        """The plugin's ranking, in the plugin's own format (`/dynamic-queue/api/json`).

        `{"unavailable_reason": ...}` instead makes the plugin unreadable, as on a controller
        without it, with the reason the real client gives.
        """
        reason = body.get("unavailable_reason")
        if isinstance(reason, str):
            plugin.set_unavailable(reason)
            return {"items": 0}
        plugin.ranking_result = parse_ranking(body)
        return {"items": len(plugin.ranking_result.items)}

    @router.post("/builds")
    async def finish_builds(result: Annotated[str, Body(embed=True)]) -> dict[str, int]:
        """Every queued build starts and ends with `result`, as Jenkins would report it.

        A FAILURE gets the real jenkins-dev log of the intentional failing unit test
        (tests/data/failure_logs), so Explain failure has something true to read. The run tracker
        picks the builds up on its next poll, as it does from a real Jenkins.
        """
        failing_log = (
            Path(__file__).parent
            / "tests"
            / "data"
            / "failure_logs"
            / "payment-service-test-unit.log"
        ).read_text(encoding="utf-8")
        finished = 0
        for item in list(jenkins.queue.values()):
            if item.cancelled or item.build_number is not None:
                continue
            info = jenkins.complete_queue_item(item.id, result=result)
            if result == "FAILURE":
                jenkins.jobs[item.job_name or ""].logs[info.number] = failing_log
            finished += 1
        return {"finished": finished}

    @router.post("/reset")
    async def reset() -> dict[str, int]:
        """Cancel every running chain, as an Admin would, so the next flow may start its own."""
        model.answering = True
        plugin.ranking_result = Ranking(available=True, optimizer_enabled=True)
        cancelled = 0
        async with db_session.get_session_factory()() as session:
            admin = await session.scalar(select(User).where(User.role == Role.ADMIN.value))
            running = (
                await session.scalars(
                    select(Chain).where(Chain.status == ChainStatus.RUNNING.value)
                )
            ).all()
            for chain in running:
                if admin is not None:
                    await chain_service.cancel(session, jenkins=jenkins, chain=chain, actor=admin)
                    cancelled += 1
            await session.commit()
        return {"cancelled": cancelled}

    @router.post("/catalog/reset")
    async def reset_catalog() -> dict[str, bool]:
        """Restore this browser run's private catalog; never modify the repository catalog."""
        shutil.copy2(CATALOG_SOURCE, WORKDIR / "services.yaml")
        get_catalog().reload()
        return {"restored": True}

    return router


def build() -> FastAPI:
    get_settings.cache_clear()
    settings = get_settings()
    if settings.llm_mode is not LlmMode.FAKE or not settings.database_url.startswith("sqlite"):
        sys.exit("refusing to start: the browser backend runs only in fake mode on SQLite")

    asyncio.run(prepare(settings))

    jenkins = FakeJenkinsClient()
    plugin = FakePluginClient()
    git = FakeGitClient()
    for name in ("payment-service", "auth-service"):
        for branch, sha in BRANCHES.items():
            git.add_branch(f"https://github.com/haiderali-dev/{name}.git", branch, sha)
    set_jenkins_client(jenkins)
    set_plugin_client(plugin)
    set_git_client(git)

    model = SwitchableModel(get_catalog())

    def intent_parser(
        settings: Annotated[Settings, Depends(get_settings_dep)],
        catalog: Annotated[Catalog, Depends(get_catalog)],
        git: Annotated[GitClient, Depends(get_git_client)],
    ) -> IntentParser:
        return build_intent_parser(
            settings, catalog=catalog, git=git, provider=model.provider, has_models=True
        )

    app = create_app(settings)
    app.dependency_overrides[get_intent_parser] = intent_parser
    app.include_router(control_router(model, plugin, jenkins))
    return app


if __name__ == "__main__":
    uvicorn.run(build(), host="127.0.0.1", port=PORT, log_level="warning")
