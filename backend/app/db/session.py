"""Async engine, session factory and the FastAPI dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the engine for this configuration.

    SQLite needs different arguments from PostgreSQL: no pool sizing, and ``check_same_thread``
    relaxed so the test client's threads can share one in-memory database.
    """
    kwargs: dict[str, Any] = {"echo": False, "future": True}
    if settings.is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs |= {
            "pool_size": 10,
            "max_overflow": 5,
            # Recycle before the typical idle timeout so a long-idle connection is not handed out
            # after the server has already dropped it.
            "pool_recycle": 1800,
            "pool_pre_ping": True,
        }
    return create_async_engine(settings.database_url, **kwargs)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings())
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


def configure(engine: AsyncEngine) -> None:
    """Point the module at a specific engine. Used by tests and by the seed scripts."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


async def dispose() -> None:
    """Close the pool on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding a session that commits on success and rolls back on error.

    Commit-on-success rather than per-service commits: a request that fails halfway must not leave
    half its writes behind, and a router cannot forget to roll back.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
