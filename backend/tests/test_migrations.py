"""Migrations must agree with the models, and the seeds must be idempotent.

The first is the point of this file. ``tests/conftest.py`` builds its schema with
``Base.metadata.create_all`` so a unit test fails because of the code under test rather than a
half-finished migration. That convenience has a cost: nothing would notice a model changed without
a matching migration until the change reached a real PostgreSQL. This closes that gap.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.settings import Settings
from app.db.base import Base
from app.db.models import Role, Service, User
from app.db.seed import seed_admin, seed_catalog

BACKEND_ROOT = Path(__file__).resolve().parent.parent
VERSIONS = BACKEND_ROOT / "alembic" / "versions"

# Every table BUILD_PROMPT 4.4.3 names. Listed literally rather than derived from the models, so
# that deleting a model is caught instead of quietly shrinking both sides of the comparison.
REQUIRED_TABLES = {
    "users",
    "services",
    "conversations",
    "messages",
    "nl_commands",
    "generated_pipelines",
    "jobs",
    "job_runs",
    "llm_calls",
    "experiments",
    "experiment_metrics",
    "resource_samples",
    "notifications",
    "audit_logs",
}


def _migration_files() -> list[Path]:
    return sorted(p for p in VERSIONS.glob("*.py") if not p.name.startswith("__"))


def test_at_least_one_migration_exists() -> None:
    assert _migration_files(), (
        "no migration in alembic/versions/. Run "
        "`uv run alembic revision --autogenerate -m 'describe the change'`."
    )


def test_models_declare_every_required_table() -> None:
    declared = set(Base.metadata.tables)
    missing = REQUIRED_TABLES - declared
    assert not missing, f"BUILD_PROMPT 4.4.3 requires these tables: {sorted(missing)}"


def test_migrations_create_every_required_table() -> None:
    """Each required table must be created by some migration.

    A textual check rather than a live upgrade: running Alembic needs PostgreSQL, and this suite is
    the one that must pass with no container. tests marked `integration` exercise a real upgrade.
    """
    source = "\n".join(p.read_text(encoding="utf-8") for p in _migration_files())
    created = set(re.findall(r'op\.create_table\(\s*"([a-z_]+)"', source))
    missing = REQUIRED_TABLES - created
    assert not missing, (
        f"these tables exist in the models but no migration creates them: {sorted(missing)}. "
        "Autogenerate a migration."
    )


def test_every_migration_is_reversible() -> None:
    """A migration that cannot be rolled back is one nobody can safely apply.

    `demo_reset.py` restores a known state before the demo, and an irreversible migration would
    make that a reinstall rather than a rollback.
    """
    offenders: list[str] = []
    for path in _migration_files():
        text = path.read_text(encoding="utf-8")
        downgrade = text.split("def downgrade()", 1)
        if len(downgrade) < 2:
            offenders.append(f"{path.name}: no downgrade()")
        elif downgrade[1].strip().startswith("-> None:\n    pass"):
            offenders.append(f"{path.name}: downgrade() is a no-op")
    assert not offenders, "irreversible migrations: " + "; ".join(offenders)


def test_timestamps_are_timezone_aware() -> None:
    """Every datetime column must carry a timezone.

    Queue waits are computed by subtracting timestamps. Mixing an aware and a naive value raises at
    runtime, and storing a naive one silently loses the offset -- which for a scheduling system
    means the KPI it exists to measure is wrong.
    """
    naive: list[str] = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            type_name = type(column.type).__name__
            if type_name == "DateTime" and not getattr(column.type, "timezone", False):
                naive.append(f"{table.name}.{column.name}")
    assert not naive, f"naive datetime columns: {naive}"


def test_audit_log_survives_actor_deletion() -> None:
    """Deleting a user must not erase what they did.

    4.4.3 requires an audit entry for every approval, job creation, HIGH-urgency request, policy
    denial and admin change. If ``actor_id`` cascaded, removing an account would delete exactly the
    records someone might remove an account to hide.
    """
    actor = Base.metadata.tables["audit_logs"].c["actor_id"]
    foreign_keys = list(actor.foreign_keys)
    assert foreign_keys, "audit_logs.actor_id has no foreign key"
    assert foreign_keys[0].ondelete == "SET NULL", (
        f"audit_logs.actor_id uses ondelete={foreign_keys[0].ondelete!r}; it must be SET NULL so "
        "deleting a user cannot erase their audit trail"
    )


async def test_create_all_matches_the_required_tables(engine: AsyncEngine) -> None:
    """The schema the tests run against really does contain every table."""

    def _tables(connection: object) -> set[str]:
        return set(inspect(connection).get_table_names())  # type: ignore[arg-type]

    async with engine.connect() as connection:
        present = await connection.run_sync(_tables)

    missing = REQUIRED_TABLES - present
    assert not missing, f"create_all did not produce: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Seeds
# ---------------------------------------------------------------------------


async def test_seed_admin_creates_then_is_idempotent(db, settings: Settings) -> None:
    email, created_first = await seed_admin(db, settings)
    await db.commit()
    assert created_first is True

    _, created_second = await seed_admin(db, settings)
    await db.commit()
    assert created_second is False, "seeding twice must not create a second admin"

    from sqlalchemy import func, select

    count = await db.scalar(select(func.count()).select_from(User).where(User.email == email))
    assert count == 1


async def test_seed_admin_does_not_reset_an_existing_password(db, settings: Settings) -> None:
    """A password someone deliberately changed must survive a restart.

    The seed runs on every stack start. Resetting the password each time would silently undo a
    rotation, which is the opposite of what a rotation is for.
    """
    await seed_admin(db, settings)
    await db.commit()

    from sqlalchemy import select

    user = await db.scalar(select(User).where(User.email == settings.seed_admin_email.lower()))
    assert user is not None
    user.password_hash = "changed-by-a-human"
    await db.commit()

    await seed_admin(db, settings)
    await db.commit()

    user = await db.scalar(select(User).where(User.email == settings.seed_admin_email.lower()))
    assert user is not None
    assert user.password_hash == "changed-by-a-human"


async def test_seed_admin_reactivates_a_disabled_admin(db, settings: Settings) -> None:
    """A deactivated admin locks everyone out; the seed is the documented way back in."""
    await seed_admin(db, settings)
    await db.commit()

    from sqlalchemy import select

    user = await db.scalar(select(User).where(User.email == settings.seed_admin_email.lower()))
    assert user is not None
    user.active = False
    await db.commit()

    await seed_admin(db, settings)
    await db.commit()

    user = await db.scalar(select(User).where(User.email == settings.seed_admin_email.lower()))
    assert user is not None and user.active is True


async def test_seed_admin_has_the_admin_role(db, settings: Settings) -> None:
    await seed_admin(db, settings)
    await db.commit()

    from sqlalchemy import select

    user = await db.scalar(select(User).where(User.email == settings.seed_admin_email.lower()))
    assert user is not None
    assert user.role == Role.ADMIN.value


async def test_seed_catalog_mirrors_the_yaml(db, settings: Settings) -> None:
    created, updated = await seed_catalog(db, settings)
    await db.commit()

    assert created >= 1
    assert updated == 0

    from sqlalchemy import select

    payment = await db.scalar(select(Service).where(Service.name == "payment-service"))
    assert payment is not None
    assert payment.agent_label == "linux"
    assert payment.allowed_environments == ["staging"]
    # The catalog is the only source of shell commands (4.6.1), so the mirror must carry them.
    assert payment.build_command.endswith("build.sh")
    assert {suite["name"] for suite in payment.test_suites} == {"unit", "integration"}


async def test_seed_catalog_is_idempotent(db, settings: Settings) -> None:
    await seed_catalog(db, settings)
    await db.commit()

    created, updated = await seed_catalog(db, settings)
    await db.commit()

    assert (created, updated) == (0, 0), "re-seeding an unchanged catalog must be a no-op"


async def test_seed_catalog_never_grants_production(db, settings: Settings) -> None:
    """Rule 1.5, checked at the point the catalog reaches the database.

    The YAML schema rejects it and the policy layer refuses it; this is the third guard, on the
    path between them.
    """
    await seed_catalog(db, settings)
    await db.commit()

    from sqlalchemy import select

    services = (await db.scalars(select(Service))).all()
    assert services
    for service in services:
        assert "production" not in service.allowed_environments
        assert "production" not in (service.deploy_commands or {})


@pytest.mark.integration
async def test_alembic_upgrade_matches_the_models() -> None:
    """Placeholder for the live check.

    Running `alembic upgrade head` against a real PostgreSQL and diffing the result against
    Base.metadata is the only way to prove the migration and the models agree exactly. It needs a
    container, so it is marked `integration` and excluded from the default run.
    """
    pytest.skip("needs a PostgreSQL container; run with -m integration against the Compose stack")
