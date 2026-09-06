"""The connection string a hosting provider gives you, and the two drivers that read it.

This is the deployment failure most worth a test, because it happens once, remotely, and
says nothing useful when it does: a URL pasted from Railway or Neon reaches asyncpg in the
wrong dialect and the container dies on its first connection.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from app.db.urls import to_sync


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # Railway, which publishes the libpq form with no TLS parameter.
        (
            "postgresql://postgres:secret@postgres.railway.internal:5432/railway",
            "postgresql+asyncpg://postgres:secret@postgres.railway.internal:5432/railway",
        ),
        # Heroku's older scheme, still what several providers emit.
        ("postgres://u:p@host:5432/db", "postgresql+asyncpg://u:p@host:5432/db"),
        # Neon: TLS demanded, plus a parameter asyncpg has never heard of.
        (
            "postgresql://u:p@ep-cool.neon.tech/db?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@ep-cool.neon.tech/db?ssl=require",
        ),
        # Already correct, and left exactly alone.
        (
            "postgresql+asyncpg://distill:distill@localhost:5432/distill",
            "postgresql+asyncpg://distill:distill@localhost:5432/distill",
        ),
    ],
)
def test_a_provider_url_is_accepted_as_given(given: str, expected: str) -> None:
    assert str(Settings(database_url=given).database_url) == expected


def test_a_url_naming_another_driver_is_left_alone() -> None:
    """Someone who asked for psycopg meant it. Swapping their driver quietly would be a
    worse outcome than the error they get if they were wrong."""
    given = "postgresql+psycopg://u:p@host/db"
    assert str(Settings(database_url=given).database_url) == given


def test_tls_intent_survives_the_rewrite() -> None:
    """`sslmode=require` dropped rather than translated would be a deployment that silently
    stopped encrypting, which is the kind of quiet downgrade nobody notices."""
    settings = Settings(database_url="postgresql://u:p@host/db?sslmode=verify-full")

    assert "ssl=require" in str(settings.database_url)
    # And the synchronous side gets it back in libpq's spelling, which is the one psycopg
    # understands; handed `ssl` it fails on an unknown keyword.
    assert "sslmode=require" in settings.sync_database_url()


def test_the_synchronous_url_changes_only_the_driver() -> None:
    async_url = "postgresql+asyncpg://u:p@host:5432/db"

    assert to_sync(async_url) == "postgresql+psycopg://u:p@host:5432/db"
