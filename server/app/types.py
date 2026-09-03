"""Shared type aliases used in route signatures."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Path

WorkspaceId = Annotated[UUID, Path(description="Workspace identifier.")]
DocumentId = Annotated[UUID, Path(description="Document identifier.")]
RecordId = Annotated[UUID, Path(description="Record identifier.")]
