"""Turning the one configured connection string into the driver a caller needs.

The application is asyncpg throughout, with one exception: blob storage in the database is
synchronous, because the ``Storage`` protocol is (decision D86). So the same URL has to be
expressed twice, and the two drivers disagree about more than the scheme.

The disagreement that matters is TLS. asyncpg, through SQLAlchemy, takes ``ssl=require``.
psycopg is libpq underneath and takes ``sslmode=require``; handed ``ssl`` it fails on an
unknown keyword. A managed Postgres that insists on TLS is the normal case rather than the
exotic one, so getting this wrong breaks the deployed configuration and nothing local.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ASYNC_DRIVER = "postgresql+asyncpg"
SYNC_DRIVER = "postgresql+psycopg"


def to_sync(url: str) -> str:
    """The same connection, for the synchronous psycopg driver."""
    parts = urlsplit(url)
    scheme = SYNC_DRIVER if parts.scheme == ASYNC_DRIVER else parts.scheme
    query = [
        ("sslmode", value) if key == "ssl" else (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
