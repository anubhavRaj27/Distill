"""Filesystem storage. The deployment is one container with an attached volume."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

from app.storage.base import Storage, validate_key

CHUNK_SIZE = 64 * 1024


class LocalStorage(Storage):
    """Objects as files under a root directory."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        # Belt and braces. `validate_key` already rejects traversal, and this asserts the
        # resolved path is still inside the root in case a symlink in the root points out.
        if not path.is_relative_to(self.root):
            raise ValueError(f"resolved path for {key!r} escapes the storage root")
        return path

    def put_bytes(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary name and rename, so a crash mid-write never leaves a
        # half-written object that later reads as a corrupt document.
        temporary = path.with_suffix(path.suffix + ".partial")
        temporary.write_bytes(data)
        temporary.replace(path)
        return key

    def put_file(self, key: str, source: Path, *, move: bool = False) -> str:
        """Store an existing file. ``move`` avoids copying a large upload twice."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(source), path)
        else:
            shutil.copyfile(source, path)
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def open_stream(self, key: str) -> Iterator[bytes]:
        with self._path(key).open("rb") as handle:
            while chunk := handle.read(CHUNK_SIZE):
                yield chunk

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def size(self, key: str) -> int:
        return self._path(key).stat().st_size

    def local_path(self, key: str) -> Path | None:
        return self._path(key)

    def delete_prefix(self, prefix: str) -> None:
        """Remove everything under a key prefix. Used when a document is deleted."""
        path = self._path(prefix)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# Key layout, in one place
# ---------------------------------------------------------------------------
#
# Keys are hierarchical so that deleting a document is a prefix delete, and so that a
# human browsing the volume can tell what they are looking at. UUIDs are written without
# hyphens because `validate_key` permits hyphens but the flat form is shorter and reads
# less ambiguously in a path.


def document_prefix(workspace_id: UUID, document_id: UUID) -> str:
    return f"ws-{workspace_id.hex}/doc-{document_id.hex}"


def original_key(workspace_id: UUID, document_id: UUID, extension: str) -> str:
    suffix = extension.lstrip(".").lower() or "bin"
    return f"{document_prefix(workspace_id, document_id)}/original.{suffix}"


def page_image_key(workspace_id: UUID, document_id: UUID, page_index: int) -> str:
    return f"{document_prefix(workspace_id, document_id)}/pages/{page_index:04d}.png"
