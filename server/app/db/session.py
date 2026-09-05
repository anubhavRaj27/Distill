"""The database engine and session factory.

v1 had a second, deliberately weaker engine here: generated SQL ran as a ``SELECT``-only
role against a per-workspace view, with a statement timeout, as the innermost layer of
decision D10's defence. v2 removed the natural-language-to-SQL feature entirely (decision
D35), so there is no longer any model-authored SQL to sandbox, and the second engine went
with the feature rather than being kept "just in case".

What replaced it is not a weaker guarantee but a stronger one: query specifications are
evaluated in Python over the workspace's own records (``app/insights/evaluate.py``). The
model emits a structured ``DataQuery``, never a string that reaches a database. There is no
SQL surface to attack, so there is nothing to sandbox.
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
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def create_app_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        str(settings.database_url),
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=5,
        pool_pre_ping=True,
    )


def init_engines(settings: Settings | None = None) -> None:
    """Create the engine and the session factory. Called from the application lifespan."""
    global _engine, _sessionmaker
    settings = settings or get_settings()
    _engine = create_app_engine(settings)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    logger.info("db.engine_ready", pool_size=settings.db_pool_size)


async def dispose_engines() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("init_engines() has not been called")
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("init_engines() has not been called")
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """A transactional session, committed on success and rolled back on any exception.

    Used by background work, which has no request to hang a dependency off.

    It stages and flushes events exactly as the request dependency in ``app.deps`` does, and
    that is not an optional extra here: **document processing runs entirely in background
    sessions**, so without the flush every event the pipeline publishes is written to
    ``workspace_events`` and delivered to nobody. The progress strip then sits on whatever
    the upload request published and never moves, while a page refresh shows the finished
    state, because a refresh replays from the table. That was the live behaviour until
    September 6, 2026. See decision D70.
    """
    # Imported here, not at module scope: ``app.pipeline.worker`` imports this module for
    # ``session_scope`` itself, so a top-level import would close the circle.
    from app.events.bus import bus
    from app.pipeline.worker import discard_submissions, flush_submissions

    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            bus.discard_staged(session)
            discard_submissions(session)
            raise
        else:
            # After the commit, both, for the reasons given in ``app.deps``: an event about
            # a rolled-back row is a lie, and a job queued for one is a dropped job.
            bus.flush_after_commit(session)
            flush_submissions(session)
