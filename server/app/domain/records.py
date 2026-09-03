"""A record: one document's worth of extracted values, shaped for the wire.

One document produces one record. The record is what becomes a row in the data table, and
it carries every field value with its provenance, confidence tier, and status, because the
table renders all of that per cell (requirements FR-21 and FR-22).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.fields import FieldValue


class Record(BaseModel):
    """One row of the unified table."""

    id: UUID
    document_id: UUID
    document_name: str = Field(description="Original filename. Shown as the row's identity.")
    schema_version: int
    values: dict[str, FieldValue] = Field(
        default_factory=dict,
        description="Keyed by field key. A field absent from this mapping was never "
        "extracted for this document, which is different from a field present with a "
        "null value, which means the document genuinely does not contain it.",
    )
    created_at: datetime
    updated_at: datetime


class RecordPage(BaseModel):
    """A cursor-paged slice of records."""

    records: list[Record]
    next_cursor: str | None = Field(
        default=None, description="Opaque. Pass back as `cursor` for the next page."
    )
    total: int = Field(description="Total records in the workspace, for the row count.")
