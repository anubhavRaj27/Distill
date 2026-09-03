"""Engines and sessions. There are deliberately two engines, with different powers.

The application engine connects as ``sift``, owns the schema, and can write.

The **read-only** engine connects as ``sift_readonly`` and exists for exactly one purpose:
executing SQL that a Large Language Model wrote. It carries three restrictions applied at
connection time rather than per query, so no code path can forget them:

* ``default_transaction_read_only=on`` makes every transaction on it read-only at the server
* ``statement_timeout`` caps runtime, so a generated cartesian product cannot hold a
  connection open indefinitely
* the role itself holds ``SELECT`` and nothing else, and cannot reach the tables beneath the
  per-workspace views (verified in ``scripts/bootstrap_db.sql``)

Together with the ``sqlglot`` allow-list and the injected row limit, that is the layered
defence decision D10 describes. Note that the role CAN read ``pg_catalog``, which is
standard Postgres and not restrictable without more machinery than it is worth. The
allow-list is the layer that handles it, by rejecting any relation other than this
workspace's view.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings, get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_readonly_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def create_app_engine(settings: Settings) -> AsyncEngine:
    """The read and write engine, connecting as the schema owner."""
    return create_async_engine(
        str(settings.database_url),
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=5,
        pool_pre_ping=True,
    )


def create_readonly_engine(settings: Settings) -> AsyncEngine:
    """The engine generated SQL runs on. See the module docstring for why it is separate."""
    return create_async_engine(
        str(settings.database_url_readonly),
        echo=settings.db_echo,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={
            "server_settings": {
                "statement_timeout": str(settings.query_timeout_ms),
                "default_transaction_read_only": "on",
                "application_name": "sift-generated-sql",
            }
        },
    )


def init_engines(settings: Settings | None = None) -> None:
    """Create the engines and the session factory. Called from the application lifespan."""
    global _engine, _readonly_engine, _sessionmaker
    settings = settings or get_settings()
    _engine = create_app_engine(settings)
    _readonly_engine = create_readonly_engine(settings)
    _sessionmaker = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        autoflush=False,
    )
    logger.info("db.engines_ready", pool_size=settings.db_pool_size)


async def dispose_engines() -> None:
    """Close both pools. Called on shutdown."""
    global _engine, _readonly_engine, _sessionmaker
    for engine in (_engine, _readonly_engine):
        if engine is not None:
            await engine.dispose()
    _engine = _readonly_engine = None
    _sessionmaker = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("init_engines() has not been called")
    return _engine


def get_readonly_engine() -> AsyncEngine:
    if _readonly_engine is None:
        raise RuntimeError("init_engines() has not been called")
    return _readonly_engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("init_engines() has not been called")
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A transactional session, committed on success and rolled back on any exception.

    Used by background work, which has no request to hang a dependency off. Route handlers
    use the ``Session`` dependency in ``app.deps`` instead, which shares this behaviour.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
