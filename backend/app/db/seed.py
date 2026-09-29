"""Seed the database with the admin user and the service catalog.

BUILD_PROMPT task T3.2. Both seeds are idempotent: running them twice is a no-op, and running them
after a catalog edit updates the changed rows rather than duplicating them. That matters because
this runs on every stack start and after every demo reset.

The catalog rows are a *mirror*, not a source of truth. ``catalog/services.yaml`` remains
authoritative (4.6.1: the model never writes shell commands, they come from the catalog); this
table exists so the API can join against it and the Admin page can show when each entry was last
checked.

Usage:
    python -m app.db.seed              # admin and catalog
    python -m app.db.seed --admin      # admin only
    python -m app.db.seed --catalog    # catalog only
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.core.settings import Settings, get_settings
from app.db.models import Role, Service, User
from app.db.session import create_engine

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


async def seed_admin(session: AsyncSession, settings: Settings) -> tuple[str, bool]:
    """Create the seed admin if absent. Returns (email, created).

    An existing admin's password is deliberately NOT reset. This runs on every stack start, and
    silently reverting a password someone deliberately changed would be both surprising and a way
    to reintroduce a credential that was rotated for a reason.
    """
    email = settings.seed_admin_email.strip().lower()
    if not settings.seed_admin_password:
        raise SystemExit("SEED_ADMIN_PASSWORD is not set; nothing to seed")

    existing = await session.scalar(select(User).where(User.email == email))
    if existing is not None:
        # Re-activate rather than skip entirely: a deactivated admin locks everyone out, and the
        # seed is the documented way back in.
        if not existing.active:
            existing.active = True
            logger.info("seed_admin_reactivated", email=email)
        return email, False

    session.add(
        User(
            email=email,
            password_hash=hash_password(settings.seed_admin_password),
            role=Role.ADMIN.value,
            active=True,
        )
    )
    logger.info("seed_admin_created", email=email)
    return email, True


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def _catalog_path(settings: Settings) -> Path:
    """Resolve the catalog path against the repository root when it is relative.

    The backend runs from ``backend/`` on a developer machine and from ``/app`` in the container,
    where the catalog is mounted at ``/app/catalog``. Both must work without a conditional in the
    settings.
    """
    configured = Path(settings.catalog_path)
    if configured.is_absolute():
        return configured
    for base in (Path.cwd(), Path.cwd().parent, Path(__file__).resolve().parents[3]):
        candidate = base / configured
        if candidate.is_file():
            return candidate
    return configured


def load_catalog(settings: Settings) -> list[dict[str, Any]]:
    path = _catalog_path(settings)
    if not path.is_file():
        raise SystemExit(f"catalog not found at {path}. Set CATALOG_PATH or check the mount.")
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    services: list[dict[str, Any]] = document.get("services", []) if document else []
    if not services:
        raise SystemExit(f"{path} declares no services")
    return services


async def seed_catalog(session: AsyncSession, settings: Settings) -> tuple[int, int]:
    """Mirror the catalog into ``services``. Returns (created, updated).

    Rows for services no longer in the YAML are left alone rather than deleted: ``jobs.service_id``
    references them, and deleting a row would orphan the history of every job that ever built that
    service. Retiring a service is a deliberate admin action, not a side effect of editing a file.
    """
    entries = load_catalog(settings)
    created = updated = 0

    for entry in entries:
        name = entry["name"]
        existing = await session.scalar(select(Service).where(Service.name == name))

        fields = {
            "repo_url": entry["repo"],
            "default_branch": entry.get("default_branch", "main"),
            "agent_label": entry.get("agent_label", "linux"),
            "build_command": entry["build_command"],
            "test_suites": entry.get("test_suites", []),
            "deploy_commands": entry.get("deploy", {}),
            "allowed_environments": entry.get("allowed_environments", []),
            "extra_stages": entry.get("extra_stages", {}),
        }

        if existing is None:
            session.add(Service(name=name, **fields))
            created += 1
            logger.info("seed_service_created", service=name)
            continue

        changed = [key for key, value in fields.items() if getattr(existing, key) != value]
        if changed:
            for key, value in fields.items():
                setattr(existing, key, value)
            updated += 1
            logger.info("seed_service_updated", service=name, fields=changed)

    return created, updated


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run(*, admin: bool = True, catalog: bool = True) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with factory() as session:
            if admin:
                email, was_created = await seed_admin(session, settings)
                print(f"admin   : {email} ({'created' if was_created else 'already present'})")
            if catalog:
                created, updated = await seed_catalog(session, settings)
                print(f"catalog : {created} created, {updated} updated")
            await session.commit()
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admin", action="store_true", help="seed the admin user only")
    parser.add_argument("--catalog", action="store_true", help="seed the catalog only")
    args = parser.parse_args()

    # Neither flag means both, which is what the container entrypoint wants.
    both = not (args.admin or args.catalog)
    configure_logging(json_output=False)
    return asyncio.run(run(admin=args.admin or both, catalog=args.catalog or both))


if __name__ == "__main__":
    sys.exit(main())
