"""Alembic environment.

Two things this does differently from the stock template, both deliberate:

1. The URL comes from the application's ``Settings``, never from ``alembic.ini``. Migrations and
   the running application therefore cannot disagree about which database they are pointed at, and
   no credential is committed.
2. It runs the async engine properly. SQLAlchemy 2 with ``asyncpg`` cannot be driven by Alembic's
   synchronous ``run_migrations``; the connection is bridged with ``run_sync``.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.settings import get_settings

# Importing the models is what populates Base.metadata. Without it autogenerate compares the live
# database against an empty metadata and cheerfully proposes dropping every table.
from app.db import models  # noqa: F401
from app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """The URL from Settings, with the password left in place for the driver.

    Read through Settings rather than the environment directly so the same validation applies: a
    malformed URL fails here with the same message the application would give.
    """
    return get_settings().database_url


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Ignore anything Alembic did not create.

    Without this, autogenerate proposes dropping tables created by other tooling that happens to
    share the database. Nothing does today, but a migration that drops an unknown table is not a
    failure mode worth leaving open.
    """
    if type_ == "table" and reflected and compare_to is None:
        known = set(Base.metadata.tables)
        return name in known
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    Useful for review: `alembic upgrade head --sql` shows exactly what would run against
    production-shaped data before anything touches a database.
    """
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # compare_type catches a column whose Python type changed but whose name did not, which is
        # exactly the change a review is most likely to miss.
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect and migrate."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()

    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
