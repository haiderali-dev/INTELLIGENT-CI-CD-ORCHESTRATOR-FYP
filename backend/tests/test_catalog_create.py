"""Admin registration persists the catalog, without granting read-only roles write access."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import Settings
from app.db.models import AuditLog, Role, Service
from app.services.catalog import Catalog, catalog_path, load_document
from tests.test_routers import auth, token_for


@pytest.fixture
def catalog(settings: Settings, tmp_path: Path) -> Catalog:
    source = catalog_path(settings)
    for name in ("services.yaml", "services.schema.json"):
        shutil.copy2(source.with_name(name), tmp_path / name)
    settings.catalog_path = tmp_path / "services.yaml"
    return Catalog(settings.catalog_path)


@pytest.fixture
def entry() -> dict[str, Any]:
    return {
        "name": "orders-service",
        "repo": "https://github.com/team/orders-service.git",
        "default_branch": "main",
        "agent_label": "linux",
        "build_command": "./scripts/build.sh",
        "test_suites": [
            {"name": "unit", "command": "./scripts/test.sh unit", "approx_seconds": 12}
        ],
        "deploy": {"staging": {"command": "./deploy.sh staging", "url": "http://localhost:9003"}},
        "allowed_environments": ["staging"],
        "extra_stages": {"lint": "./scripts/lint.sh"},
    }


async def test_registration_updates_file_database_and_live_choices_and_is_audited(
    client: AsyncClient,
    db: AsyncSession,
    catalog: Catalog,
    entry: dict[str, Any],
) -> None:
    token = await token_for(client, db, role=Role.ADMIN)
    before = catalog.path.read_text(encoding="utf-8").rstrip()
    response = await client.post("/api/services", headers=auth(token), json=entry)
    assert response.status_code == 201, response.text
    assert response.json()["name"] == entry["name"]
    assert "build_command" not in response.json()
    assert catalog.path.read_text(encoding="utf-8").startswith(before)
    assert load_document(catalog.path)["services"][-1] == entry
    assert Catalog(catalog.path).require(entry["name"]).build_command == entry["build_command"]
    service = await db.scalar(select(Service).where(Service.name == entry["name"]))
    assert service is not None and service.repo_url == entry["repo"]
    audit = await db.scalar(select(AuditLog).where(AuditLog.action == "catalog.service.created"))
    assert audit is not None and audit.target == entry["name"] and audit.actor_id
    choices = await client.get("/api/services", headers=auth(token))
    assert entry["name"] in {service["name"] for service in choices.json()["items"]}
    assert entry["name"] in catalog.service_names()


@pytest.mark.parametrize("role", [None, Role.DEVELOPER, Role.DEVOPS])
async def test_registration_requires_admin(
    client: AsyncClient,
    db: AsyncSession,
    catalog: Catalog,
    entry: dict[str, Any],
    role: Role | None,
) -> None:
    before = catalog.path.read_bytes()
    headers = auth(await token_for(client, db, role=role)) if role else {}
    response = await client.post("/api/services", headers=headers, json=entry)
    assert response.status_code == (403 if role else 401)
    assert catalog.path.read_bytes() == before


@pytest.mark.parametrize("case", ["duplicate", "parallel-duplicate"])
async def test_duplicate_names_do_not_overwrite_existing_services(
    client: AsyncClient,
    db: AsyncSession,
    catalog: Catalog,
    entry: dict[str, Any],
    case: str,
) -> None:
    token = await token_for(client, db, role=Role.ADMIN)
    if case == "duplicate":
        entry["name"] = "payment-service"
        before = catalog.path.read_bytes()
        response = await client.post("/api/services", headers=auth(token), json=entry)
        assert response.status_code == 409
        assert "name" in response.json()["error"]["details"]["fields"]
        assert catalog.path.read_bytes() == before
    else:
        responses = await asyncio.gather(
            *(client.post("/api/services", headers=auth(token), json=entry) for _ in range(2))
        )
        assert sorted(response.status_code for response in responses) == [201, 409]
        assert [service["name"] for service in load_document(catalog.path)["services"]].count(
            entry["name"]
        ) == 1


@pytest.mark.parametrize(
    "case",
    ["name", "url", "branch", "command", "production", "extra", "duplicate-suite", "duration"],
)
async def test_invalid_service_never_changes_the_catalog(
    client: AsyncClient,
    db: AsyncSession,
    catalog: Catalog,
    entry: dict[str, Any],
    case: str,
) -> None:
    token = await token_for(client, db, role=Role.ADMIN)
    if case == "name":
        entry["name"] = "../escape"
    elif case == "url":
        entry["repo"] = "ext::untrusted.git"
    elif case == "branch":
        entry["default_branch"] = "--upload-pack=bad"
    elif case == "command":
        entry["build_command"] = "./build.sh; untrusted"
    elif case == "production":
        entry["allowed_environments"] = ["production"]
        entry["deploy"]["production"] = entry["deploy"].pop("staging")
    elif case == "extra":
        entry["extra_stages"] = {"arbitrary": "./build.sh"}
    elif case == "duplicate-suite":
        entry["test_suites"] *= 2
    else:
        entry["test_suites"][0]["approx_seconds"] = 0
    before = catalog.path.read_bytes()
    response = await client.post("/api/services", headers=auth(token), json=entry)
    assert response.status_code == 422, response.text
    assert catalog.path.read_bytes() == before


async def test_registration_and_resync_can_run_together(
    client: AsyncClient,
    db: AsyncSession,
    catalog: Catalog,
    entry: dict[str, Any],
) -> None:
    token = await token_for(client, db, role=Role.ADMIN)
    created, resynced = await asyncio.gather(
        client.post("/api/services", headers=auth(token), json=entry),
        client.post("/api/services/resync", headers=auth(token)),
    )
    assert created.status_code == 201, created.text
    assert resynced.status_code == 200, resynced.text
    assert Catalog(catalog.path).require(entry["name"]).repo == entry["repo"]
    assert await db.scalar(select(Service).where(Service.name == entry["name"])) is not None


async def test_database_failure_restores_the_file_and_leaves_no_live_entry(
    client: AsyncClient,
    db: AsyncSession,
    catalog: Catalog,
    entry: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await token_for(client, db, role=Role.ADMIN)
    original_commit = AsyncSession.commit

    async def failed_commit(session: AsyncSession) -> None:
        if any(
            isinstance(row, AuditLog) and row.action == "catalog.service.created"
            for row in session.new
        ):
            raise RuntimeError("injected database commit failure")
        await original_commit(session)

    monkeypatch.setattr(AsyncSession, "commit", failed_commit)
    before = catalog.path.read_bytes()
    with pytest.raises(RuntimeError, match="injected database commit failure"):
        await client.post("/api/services", headers=auth(token), json=entry)
    assert catalog.path.read_bytes() == before
    assert catalog.get(entry["name"]) is None
    assert await db.scalar(select(Service).where(Service.name == entry["name"])) is None


async def test_unwritable_catalog_returns_an_actionable_error_without_a_db_entry(
    client: AsyncClient,
    db: AsyncSession,
    catalog: Catalog,
    entry: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = await token_for(client, db, role=Role.ADMIN)

    def denied(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("read-only mount")

    monkeypatch.setattr(catalog, "_replace", denied)
    response = await client.post("/api/services", headers=auth(token), json=entry)
    assert response.status_code == 503
    assert "writable" in response.json()["error"]["message"]
    assert await db.scalar(select(Service).where(Service.name == entry["name"])) is None
