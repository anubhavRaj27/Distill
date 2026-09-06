"""Which store this process uses, decided and built in one place.

There were two places constructing a ``LocalStorage`` directly, the lifespan and the
documents router, which is two places to forget when a second backend appears. See decision
D45.

**Cached, and that is not an optimisation.** The documents router builds a store per
request. A directory does not care, but ``PostgresStorage`` owns a connection pool, so a
fresh instance per request would open a fresh pool per request and exhaust a free tier's
connection limit within a page of the document viewer. One store per process, for the life
of the process.
"""

from __future__ import annotations

import threading

from app.config import Settings
from app.storage.base import Storage
from app.storage.local import LocalStorage
from app.storage.postgres import PostgresStorage

_lock = threading.Lock()
_store: Storage | None = None
_built_from: tuple[str, str] | None = None


def make_storage(settings: Settings) -> Storage:
    """The configured store, built once.

    ``local`` is the default and is what development uses: a directory is easier to look
    inside than a table. ``postgres`` is for a deployment whose container has no disk that
    outlives a restart, which is every free tier worth using.
    """
    global _store, _built_from

    # The identity of the store, so a test that reconfigures settings gets the store its
    # settings asked for rather than the one the previous test left behind.
    key = (settings.storage_backend, str(settings.database_url or settings.storage_dir))

    if _store is not None and _built_from == key:
        return _store

    with _lock:
        if _store is not None and _built_from == key:
            return _store
        _dispose(_store)
        _store = _build(settings)
        _built_from = key
        return _store


def reset_storage_cache() -> None:
    """Drop the cached store. For tests, and for a lifespan shutting down cleanly."""
    global _store, _built_from
    with _lock:
        _dispose(_store)
        _store = None
        _built_from = None


def _build(settings: Settings) -> Storage:
    if settings.storage_backend == "postgres":
        return PostgresStorage(str(settings.database_url))

    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return LocalStorage(settings.storage_dir)


def _dispose(store: Storage | None) -> None:
    """Give a store the chance to close what it holds. Only one of them holds anything."""
    closer = getattr(store, "dispose", None)
    if closer is not None:
        closer()
