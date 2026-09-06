"""Test fixtures.

Two choices here shape every test in the suite.

**Migrations run, rather than ``create_all``.** The test database is built by
``alembic upgrade head``, the same path production uses. Building it from the models
instead would be marginally faster and would silently tolerate a migration that had drifted
from the models, which is precisely the failure a test database exists to catch.

**Each test runs inside a transaction that is rolled back.** The session is bound to a
connection with an already-open transaction and ``join_transaction_mode="create_savepoint"``,
so a ``commit()`` inside the code under test commits a savepoint and is visible to the rest
of that test, while the outer transaction is discarded afterwards. Tests are therefore
isolated without truncating tables between them, and code that commits is exercised as
written rather than in a special no-commit mode.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from app.config import Settings, get_settings, reset_settings_cache
from app.db import session as session_module
from app.events.bus import bus
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

SERVER_ROOT = Path(__file__).resolve().parent.parent
TEST_DATABASE = "distill_test"


@pytest.fixture(scope="session", autouse=True)
def settings() -> Iterator[Settings]:
    """Session-wide settings, installed through the environment.

    Deliberately configured by setting environment variables and clearing the cache, rather
    than by monkeypatching ``get_settings``. Every module in the application resolves
    settings by calling the cached getter, so this makes them all agree without any module
    needing to know it is under test, and it exercises the real configuration parsing path
    instead of bypassing it.
    """
    reset_settings_cache()
    overrides = {
        "ENVIRONMENT": "test",
        "LOG_LEVEL": "WARNING",
        "DATABASE_URL": f"postgresql+asyncpg://distill:distill@localhost:5432/{TEST_DATABASE}",
        "DATABASE_URL_READONLY": (
            f"postgresql+asyncpg://distill_readonly:distill_readonly@localhost:5432/{TEST_DATABASE}"
        ),
        "STORAGE_DIR": str(SERVER_ROOT / "var" / "test-storage"),
        # Nothing built, on purpose. A checkout with a client build lying around would
        # otherwise mount it and turn every "unknown path" assertion in the API suite into
        # an assertion about an HTML shell. `test_web.py` covers the mount deliberately.
        "CLIENT_DIST_DIR": str(SERVER_ROOT / "var" / "no-client-build"),
        "LLM_PROVIDER": "fake",
        "SCHEMA_PROPOSAL_DEBOUNCE_SECONDS": "0",
    }
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    reset_settings_cache()
    try:
        yield get_settings()
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_settings_cache()


@pytest.fixture(scope="session")
def _migrate(settings: Settings) -> None:
    """Bring the test database to head, once per session.

    Deliberately NOT ``autouse``. It is pulled in by ``db`` below, so a test that never asks
    for a session never starts Postgres talking. That keeps the pure-logic suite — value
    coercion, page geometry, format sniffing, rendering — runnable with no database at all,
    which is what makes `pytest tests/unit` a thing a contributor can run on a fresh clone
    before setting anything up. Coupling those to a migration they have no use for was
    costing the fast tests their independence for nothing.
    """
    config = AlembicConfig(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "app" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", str(settings.database_url))
    command.upgrade(config, "head")


@pytest.fixture
async def db(settings: Settings, _migrate: None) -> AsyncIterator[AsyncSession]:
    """A session inside a transaction that is rolled back when the test ends."""
    engine = create_async_engine(str(settings.database_url), poolclass=None)
    async with engine.connect() as connection:
        await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            autoflush=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await connection.rollback()
    await engine.dispose()


@pytest.fixture
async def client(settings: Settings, db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """An HTTP client against the real application, sharing the test's transaction.

    ``get_session`` is overridden so that route handlers use the same rolled-back session
    the test does. The override still commits and still flushes staged events, so the event
    bus contract in ``app.events.bus`` is exercised exactly as it is in production.
    """
    from app.deps import get_session
    from app.main import create_app

    session_module.init_engines(settings)
    application = create_app(settings)

    async def _override() -> AsyncIterator[AsyncSession]:
        try:
            yield db
        except Exception:
            await db.rollback()
            bus.discard_staged(db)
            raise
        else:
            await db.commit()
            bus.flush_after_commit(db)

    application.dependency_overrides[get_session] = _override

    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http

    application.dependency_overrides.clear()
    await session_module.dispose_engines()


@pytest.fixture
async def workspace(client: AsyncClient) -> tuple[str, str]:
    """A created workspace, as ``(workspace_id, token)``."""
    response = await client.post("/api/v1/workspaces", json={"label": "test"})
    assert response.status_code == 201, response.text
    body = response.json()
    return body["id"], body["token"]


@pytest.fixture
def auth(workspace: tuple[str, str]) -> dict[str, str]:
    """Authorization header for the fixture workspace."""
    return {"Authorization": f"Bearer {workspace[1]}"}
