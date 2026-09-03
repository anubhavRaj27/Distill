"""The storage boundary: original files and rendered page images.

A protocol rather than direct filesystem calls, for one concrete reason. The deployment
target is a single container with an attached volume, and the natural next step is object
storage. Keeping the interface to six methods means that move is one new class rather than
a search for every ``open()`` in the codebase.

KEY SAFETY
----------
Keys are built by this application, never supplied by a client, but they are built FROM
client-supplied data (filenames), so they are validated anyway. ``validate_key`` rejects
absolute paths, parent traversal, and anything outside a small character set. A filename of
``../../../etc/passwd`` therefore cannot escape the storage root even though nothing in the
current code path would send one, because "nothing currently sends one" is a property of
today's code and not of the storage layer.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

# Keys are slash-separated segments of safe characters. No leading slash, no dot segments.
_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class UnsafeStorageKey(ValueError):
    """A storage key that could escape the storage root, or is otherwise malformed."""


def validate_key(key: str) -> str:
    """Return ``key`` if it is safe to join onto a storage root, else raise."""
    if not key or key.startswith("/") or key.endswith("/"):
        raise UnsafeStorageKey(f"{key!r} must be a relative path with no trailing slash")
    segments = key.split("/")
    if len(segments) > 8:
        raise UnsafeStorageKey(f"{key!r} has too many segments")
    for segment in segments:
        if segment in (".", "..") or not _KEY_SEGMENT.match(segment):
            raise UnsafeStorageKey(f"{key!r} contains an unsafe segment {segment!r}")
    return key


@runtime_checkable
class Storage(Protocol):
    """Everything the application needs from a blob store."""

    def put_bytes(self, key: str, data: bytes) -> str:
        """Write ``data`` at ``key``. Returns the key."""
        ...

    def get_bytes(self, key: str) -> bytes:
        """Read the whole object. Only for objects known to be small, such as page images."""
        ...

    def open_stream(self, key: str) -> Iterator[bytes]:
        """Yield the object in chunks, for streaming a response."""
        ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def size(self, key: str) -> int: ...

    def local_path(self, key: str) -> Path | None:
        """A filesystem path, when the backend has one.

        Returns ``None`` for backends that do not, so a caller needing a real path (some
        parsing libraries insist on one) knows to fall back to a temporary file rather than
        receiving a path that does not exist.
        """
        ...


async def stream_range(
    storage: Storage, key: str, start: int, end: int, chunk_size: int = 64 * 1024
) -> AsyncIterator[bytes]:
    """Yield bytes ``start`` to ``end`` inclusive.

    Byte ranges exist for the document viewer: pdf.js fetches a PDF in ranges so it can
    render page one of a large document without downloading all of it.
    """
    remaining = end - start + 1
    position = 0
    for chunk in storage.open_stream(key):
        chunk_end = position + len(chunk)
        if chunk_end > start and remaining > 0:
            offset = max(0, start - position)
            piece = chunk[offset : offset + remaining]
            remaining -= len(piece)
            yield piece
        position = chunk_end
        if remaining <= 0:
            return
