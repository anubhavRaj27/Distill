"""Reading records, and recording human corrections."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db.models import FieldValueRow, Record
from app.deps import CurrentWorkspace, Session
from app.domain.fields import FieldValue
from app.domain.records import Record as RecordPayload
from app.domain.records import RecordPage
from app.errors import FieldNotInSchema, RecordNotFound
from app.logging import get_logger
from app.pipeline.persist import apply_human_correction
from app.schema import versioning
from app.types import RecordId

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["records"])
logger = get_logger(__name__)

MAX_PAGE_SIZE = 200


def _encode_cursor(created_at: datetime, record_id: UUID) -> str:
    """An opaque cursor over ``(created_at, id)``.

    Keyed on the sort tuple rather than an offset, so inserting a record while a client is
    paging does not make it skip or repeat a row. ``id`` breaks ties, because two documents
    uploaded in the same batch can share a timestamp.
    """
    return base64.urlsafe_b64encode(
        f"{created_at.isoformat()}|{record_id}".encode()
    ).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        timestamp, _, identifier = raw.partition("|")
        return datetime.fromisoformat(timestamp), UUID(identifier)
    except (ValueError, TypeError):
        # A malformed cursor is treated as no cursor. It can only come from a client bug or
        # a hand-edited link, and starting from the beginning is friendlier than an error.
        logger.info("records.bad_cursor", cursor=cursor[:40])
        return None


def _to_value(row: FieldValueRow) -> FieldValue:
    from app.domain.provenance import Provenance

    return FieldValue(
        field_key=row.field_key,
        value=row.value,
        value_type=row.value_type,
        confidence=row.confidence,
        tier=row.tier,
        status=row.status,
        provenance=Provenance.model_validate(row.provenance) if row.provenance else None,
        model_value=row.model_value,
        model_value_at=row.model_value_at,
    )


@router.get("/records", response_model=RecordPage, summary="Records, cursor paged")
async def list_records(
    workspace: CurrentWorkspace,
    session: Session,
    cursor: Annotated[str | None, Query(description="From a previous page.")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
) -> RecordPage:
    schema = await versioning.current_schema(session, workspace.id)
    version = schema.version if schema else 0

    query = (
        select(Record)
        .where(Record.workspace_id == workspace.id)
        .options(selectinload(Record.values), selectinload(Record.document))
        .order_by(Record.created_at, Record.id)
        .limit(limit + 1)
    )
    decoded = _decode_cursor(cursor) if cursor else None
    if decoded is not None:
        created_at, record_id = decoded
        query = query.where(
            func.row(Record.created_at, Record.id) > func.row(created_at, record_id)
        )

    rows = list((await session.execute(query)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    total = (
        await session.execute(
            select(func.count()).select_from(Record).where(Record.workspace_id == workspace.id)
        )
    ).scalar_one()

    return RecordPage(
        records=[
            RecordPayload(
                id=row.id,
                document_id=row.document_id,
                document_name=row.document.filename,
                schema_version=version,
                values={value.field_key: _to_value(value) for value in row.values},
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ],
        next_cursor=(
            _encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
        ),
        total=int(total),
    )


class CorrectionRequest(BaseModel):
    """Either a value, or an assertion that the field is absent from this document."""

    value: Any | None = None
    not_present: bool = Field(
        default=False,
        description="The user asserts this document does not contain this field. A "
        "correction in its own right, and protected from re-extraction the same way an "
        "edited value is.",
    )

    @model_validator(mode="after")
    def _one_or_the_other(self) -> CorrectionRequest:
        if self.not_present and self.value is not None:
            raise ValueError("A field cannot be both absent and have a value.")
        return self


@router.patch(
    "/records/{record_id}/fields/{field_key}",
    response_model=FieldValue,
    summary="Correct one value",
)
async def correct_field(
    workspace: CurrentWorkspace,
    session: Session,
    record_id: RecordId,
    field_key: str,
    body: CorrectionRequest,
) -> FieldValue:
    """Record a human decision about one value. Requirements FR-23 and FR-34.

    From this point the value is immune to re-extraction: the write path filters
    human-owned rows, and a later model answer that disagrees is stored beside it rather
    than over it (decision D16).
    """
    record = (
        await session.execute(
            select(Record).where(
                Record.id == record_id, Record.workspace_id == workspace.id
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise RecordNotFound("That record is not in this workspace.")

    fields = await versioning.current_fields(session, workspace.id)
    spec = next((field for field in fields if field.key == field_key), None)
    if spec is None:
        raise FieldNotInSchema(
            f"{field_key!r} is not a field in this workspace's schema.",
            field_key=field_key,
            available=[field.key for field in fields],
        )

    return await apply_human_correction(
        session,
        workspace_id=workspace.id,
        record=record,
        field_key=field_key,
        spec=spec,
        value=body.value,
        not_present=body.not_present,
    )

# The review queue and its keyboard flow were removed in v2 (decision D42). A second screen
# dedicated to checking cells competes with the chat for the user's attention, and the
# confidence tier is already visible on every cell in the table (requirement FR-14), which
# is where a person is actually looking. The scoring function it used, `score.impact`,
# stays: it still orders nothing, but it is the tested expression of "which of these
# uncertain values would matter most", and the table can sort by it.
