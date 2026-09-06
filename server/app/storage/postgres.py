"""Blob storage in Postgres. Decision D86.

The free hosting tiers this is deployed on give a container no disk that survives a restart,
so ``LocalStorage`` on a deployed instance means the originals and the page images quietly
disappear on the next redeploy while their rows stay behind. Every value on screen is
supposed to trace back to a highlighted region of its source document, which is the fourth
non-negotiable in ``CLAUDE.md``; a store that empties itself breaks precisely that, and
breaks it silently.

Putting the bytes in the database instead makes the container stateless, which is what makes
a free tier usable at all: there is exactly one thing holding state, and it is the one thing
that is managed and backed up.

**Synchronous, deliberately.** The ``Storage`` protocol is synchronous because most of its
callers already run inside ``to_thread.run_sync``, and the application's own engine is
asyncpg, which cannot be used from a synchronous method. So this opens a small second engine
on the psycopg driver rather than contorting either side. Two or three connections is
plenty: this is not on the hot path of anything except the document viewer.

**Not a scaling plan.** Bytes in a relational database is the right shape for a demo corpus
measured in megabytes and the wrong shape for anything larger. The ``Storage`` protocol is
where a third implementation goes when that day comes.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, text

from app.db.urls import to_sync
from app.storage.base import Storage, validate_key

CHUNK_SIZE = 64 * 1024


class PostgresStorage(Storage):
    """Objects as rows in the ``blobs`` table."""

    def __init__(self, database_url: str, *, pool_size: int = 3) -> None:
        self._database_url = to_sync(database_url)
        self._pool_size = pool_size
        self._engine: Engine | None = None
        self._lock = threading.Lock()

    @property
    def engine(self) -> Engine:
        """Created on first use, so constructing the store never opens a connection.

        Boot order depends on it: the application builds its storage inside the lifespan,
        before it has any reason to believe the database is reachable, and a health check
        that reports "storage: no" is a great deal more useful than a container that will
        not start.
        """
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    self._engine = create_engine(
                        self._database_url,
                        pool_size=self._pool_size,
                        max_overflow=2,
                        pool_pre_ping=True,
                        future=True,
                    )
        return self._engine

    # -- Writing -------------------------------------------------------------

    def put_bytes(self, key: str, data: bytes) -> str:
        key = validate_key(key)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO blobs (key, data, size_bytes) VALUES (:key, :data, :size) "
                    "ON CONFLICT (key) DO UPDATE SET data = EXCLUDED.data, "
                    "size_bytes = EXCLUDED.size_bytes"
                ),
                {"key": key, "data": data, "size": len(data)},
            )
        return key

    def put_file(self, key: str, source: Path, *, move: bool = False) -> str:
        """Store a file from disk. ``move`` deletes the source once it is safely stored.

        Read whole rather than streamed in, because a value has to be handed to the driver
        in one piece anyway and uploads are capped at ``max_upload_mb``.
        """
        self.put_bytes(key, source.read_bytes())
        if move:
            source.unlink(missing_ok=True)
        return key

    # -- Reading -------------------------------------------------------------

    def get_bytes(self, key: str) -> bytes:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT data FROM blobs WHERE key = :key"), {"key": validate_key(key)}
            ).first()
        if row is None:
            raise FileNotFoundError(key)
        return bytes(row[0])

    def open_stream(self, key: str) -> Iterator[bytes]:
        """Yield the object in chunks, cut by the database rather than in memory.

        ``substring`` on a bytea does the slicing server-side, so streaming a 20 MB original
        to the viewer costs 64 KB of process memory rather than 20 MB.
        """
        total = self.size(key)
        position = 0
        while position < total:
            chunk = self.read_range(key, position, min(position + CHUNK_SIZE, total) - 1)
            if not chunk:
                return
            position += len(chunk)
            yield chunk

    def read_range(self, key: str, start: int, end: int) -> bytes:
        """Bytes ``start`` to ``end`` inclusive. See ``base.stream_range``."""
        length = end - start + 1
        if length <= 0:
            return b""
        with self.engine.connect() as connection:
            row = connection.execute(
                # Postgres substring is one-based, so the offset is start + 1.
                text(
                    "SELECT substring(data from :offset for :length) FROM blobs "
                    "WHERE key = :key"
                ),
                {"key": validate_key(key), "offset": start + 1, "length": length},
            ).first()
        if row is None:
            raise FileNotFoundError(key)
        return bytes(row[0])

    def exists(self, key: str) -> bool:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    text("SELECT 1 FROM blobs WHERE key = :key"), {"key": validate_key(key)}
                ).first()
                is not None
            )

    def size(self, key: str) -> int:
        with self.engine.connect() as connection:
            row = connection.execute(
                text("SELECT size_bytes FROM blobs WHERE key = :key"),
                {"key": validate_key(key)},
            ).first()
        if row is None:
            raise FileNotFoundError(key)
        return int(row[0])

    # -- Removing ------------------------------------------------------------

    def delete(self, key: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM blobs WHERE key = :key"), {"key": validate_key(key)}
            )

    def delete_prefix(self, prefix: str) -> None:
        """Everything under a document's prefix, in one statement.

        Compared with ``left`` rather than matched with ``LIKE``. Keys are validated, but
        ``validate_key`` permits underscores, and an underscore inside a LIKE pattern is a
        single-character wildcard: a prefix delete written that way would match keys it was
        never asked about. ``left`` has no pattern language to get wrong.
        """
        prefix = validate_key(prefix)
        below = f"{prefix}/"
        with self.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM blobs WHERE key = :key OR left(key, :width) = :below"),
                {"key": prefix, "width": len(below), "below": below},
            )

    # -- The one thing a database cannot offer -------------------------------

    def local_path(self, key: str) -> Path | None:
        """None, always. Nothing in the application asks for a real path; see the protocol."""
        return None

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
