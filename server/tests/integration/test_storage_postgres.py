"""Blob storage in the database. Decision D86.

Against the real test database, because the whole point of this backend is what Postgres
does with a bytea: the substring reads, the upsert, and the prefix delete are all SQL, and
a fake would only assert that the strings were written the way they were written.

It manages its own rows rather than joining the suite's rolled-back transaction. It has to:
the store opens its own synchronous engine and commits through it, which is exactly the
behaviour under test.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from app.config import Settings
from app.storage.base import validate_key
from app.storage.local import document_prefix, original_key, page_image_key
from app.storage.postgres import PostgresStorage

pytestmark = pytest.mark.anyio


@pytest.fixture
def store(settings: Settings, _migrate: None) -> Iterator[PostgresStorage]:
    storage = PostgresStorage(str(settings.database_url))
    try:
        yield storage
    finally:
        storage.dispose()


@pytest.fixture
def keys() -> tuple[str, str, str]:
    workspace, document = uuid4(), uuid4()
    return (
        document_prefix(workspace, document),
        original_key(workspace, document, "pdf"),
        page_image_key(workspace, document, 0),
    )


def test_a_document_survives_the_round_trip(
    store: PostgresStorage, keys: tuple[str, str, str]
) -> None:
    prefix, original, _page = keys
    data = b"%PDF-1.7\n" + bytes(range(256)) * 40

    try:
        assert store.put_bytes(original, data) == original
        assert store.exists(original)
        assert store.size(original) == len(data)
        assert store.get_bytes(original) == data
    finally:
        store.delete_prefix(prefix)


def test_a_range_is_read_by_the_database_not_by_walking(
    store: PostgresStorage, keys: tuple[str, str, str]
) -> None:
    """What the document viewer does: pdf.js asks for the middle of a file and should not
    pay for everything before it."""
    prefix, original, _page = keys
    data = bytes(range(256)) * 100

    try:
        store.put_bytes(original, data)

        assert store.read_range(original, 0, 9) == data[0:10]
        assert store.read_range(original, 5000, 5099) == data[5000:5100]
        # Past the end is short, not an error, which is what a Range at the tail relies on.
        assert store.read_range(original, len(data) - 5, len(data) + 100) == data[-5:]
        assert store.read_range(original, 10, 9) == b""
    finally:
        store.delete_prefix(prefix)


def test_a_stream_arrives_whole_and_in_pieces(
    store: PostgresStorage, keys: tuple[str, str, str]
) -> None:
    prefix, original, _page = keys
    data = b"x" * (64 * 1024 * 2 + 17)

    try:
        store.put_bytes(original, data)
        chunks = list(store.open_stream(original))

        assert b"".join(chunks) == data
        assert len(chunks) > 1, "streaming in one piece defeats the point of streaming"
    finally:
        store.delete_prefix(prefix)


def test_writing_the_same_key_twice_replaces_it(
    store: PostgresStorage, keys: tuple[str, str, str]
) -> None:
    """Re-extraction re-renders pages onto the keys they already occupy."""
    prefix, _original, page = keys

    try:
        store.put_bytes(page, b"first")
        store.put_bytes(page, b"second, longer")

        assert store.get_bytes(page) == b"second, longer"
        assert store.size(page) == len(b"second, longer")
    finally:
        store.delete_prefix(prefix)


def test_deleting_a_document_takes_its_pages_with_it(
    store: PostgresStorage, keys: tuple[str, str, str]
) -> None:
    prefix, original, page = keys
    neighbour = f"{prefix}-other/original.pdf"

    try:
        store.put_bytes(original, b"a")
        store.put_bytes(page, b"b")
        store.put_bytes(neighbour, b"c")

        store.delete_prefix(prefix)

        assert not store.exists(original)
        assert not store.exists(page)
        # The neighbour shares the prefix as a STRING and not as a path. A prefix delete
        # that matched it would take a different document's original with it.
        assert store.exists(neighbour)
    finally:
        store.delete(neighbour)


def test_a_missing_key_says_so(store: PostgresStorage, keys: tuple[str, str, str]) -> None:
    """Rather than an empty document, which would read as a file with nothing in it."""
    _prefix, original, _page = keys

    with pytest.raises(FileNotFoundError):
        store.get_bytes(original)
    with pytest.raises(FileNotFoundError):
        store.size(original)
    assert not store.exists(original)
    # Deleting what is not there is not an error: document deletion is retried.
    store.delete(original)


def test_it_offers_no_filesystem_path(store: PostgresStorage) -> None:
    """The protocol's contract for a backend that has no files. Nothing in the application
    asks for one, and returning a path that does not exist would be worse than None."""
    assert store.local_path(validate_key("ws-abc/doc-def/original.pdf")) is None
