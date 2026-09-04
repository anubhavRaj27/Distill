"""The Server-Sent Events vocabulary. One source of truth, shared with the frontend.

These models are exported into the OpenAPI document, so the frontend's generated client
gets them as types and an exhaustive switch over ``type`` is checkable by the compiler. That
is the whole reason this is a discriminated union rather than a loose dictionary: adding an
event here becomes a compile error in the frontend until it is handled, instead of a silently
ignored message.

The frontend applies these events to its query cache directly rather than refetching, which
is what stops the table flickering while eight documents stream in (implementation.md
section 5.1).

Every event carries a per-workspace monotonic ``seq``. That is what ``Last-Event-ID`` resume
is built on, and why the event log is a table rather than in-memory state (decision D14).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.document import DocumentStatus
from app.domain.fields import FieldValue, SchemaChangeAuthor
from app.domain.records import Record


class BaseEvent(BaseModel):
    """Fields every event carries."""

    seq: int = Field(description="Per-workspace monotonic sequence number. The event id.")


class DocumentStatusEvent(BaseEvent):
    """A document moved through the pipeline. Drives the progress list."""

    type: Literal["document.status"] = "document.status"
    document_id: UUID
    filename: str
    status: DocumentStatus
    stage_detail: str | None = Field(
        default=None,
        description="Human-readable sub-state, such as 'scanned image detected, running "
        "text recognition'. Shown beneath the stage name.",
    )
    failure_reason: str | None = Field(
        default=None,
        description="Why it failed, written for the user. Requirement 3.6 asks for a "
        "specific and actionable message, never a stack trace or a raw library error.",
    )
    attempt: int | None = Field(
        default=None, description="Which retry this is, so the interface can say '2 of 3'."
    )
    page_count: int | None = None


class RecordUpsertEvent(BaseEvent):
    """A record appeared or changed wholesale. Streamed as each document completes."""

    type: Literal["record.upsert"] = "record.upsert"
    record: Record


class FieldUpdatedEvent(BaseEvent):
    """A single value changed. Used for corrections and backfill, to avoid resending a row."""

    type: Literal["field.updated"] = "field.updated"
    record_id: UUID
    field_key: str
    value: FieldValue


class SchemaProposalEvent(BaseEvent):
    """The system is asking the user to decide something about the schema.

    ``surface`` is a list of Agent-to-User Interface messages. The frontend feeds them
    straight to its renderer, so the backend decides the shape of the card and the frontend
    decides how it looks (requirement A2-02).
    """

    type: Literal["schema.proposal"] = "schema.proposal"
    proposal_id: UUID
    kind: Literal["initial_schema", "drift"]
    document_id: UUID | None = Field(
        default=None, description="The document that triggered a drift proposal."
    )
    surface: list[dict[str, object]]


class SchemaVersionEvent(BaseEvent):
    """A new schema version was applied. The frontend refetches the schema and the view."""

    type: Literal["schema.version"] = "schema.version"
    version: int
    added_field_keys: list[str] = Field(default_factory=list)
    removed_field_keys: list[str] = Field(default_factory=list)
    renamed: dict[str, str] = Field(
        default_factory=dict, description="Old key to new key, for renames."
    )
    applied_by: SchemaChangeAuthor = Field(
        description="Whether the system applied this without asking, or the user decided "
        "it. Decisions D23 and D24. This is not a detail: an auto-applied change arrives "
        "with no interaction behind it, so the interface owes the user a visible note in "
        "the moment and a marked entry in schema history. Reversibility is what makes "
        "auto-apply trustworthy, and it is worth nothing if the change is invisible."
    )
    change_summary: str | None = Field(
        default=None,
        description="One line describing what changed, written for a person, such as "
        "\"mapped 'Supplier' to vendor_name\". Rendered in schema history and in the "
        "auto-apply note.",
    )


class BackfillProgressEvent(BaseEvent):
    """Progress of filling a newly added field across existing documents. FR-14."""

    type: Literal["backfill.progress"] = "backfill.progress"
    field_keys: list[str]
    done: int
    total: int


class DocumentDeletedEvent(BaseEvent):
    """A document and its record were removed."""

    type: Literal["document.deleted"] = "document.deleted"
    document_id: UUID


class HeartbeatEvent(BaseEvent):
    """Sent every 15 seconds.

    Two jobs. It keeps intermediaries from deciding an idle stream is dead, and it is the
    frontend's evidence that the connection is genuinely alive rather than merely open,
    which is what the "backend unreachable" banner in requirement 3.6 keys off.
    """

    type: Literal["heartbeat"] = "heartbeat"


WorkspaceEvent = Annotated[
    DocumentStatusEvent
    | RecordUpsertEvent
    | FieldUpdatedEvent
    | SchemaProposalEvent
    | SchemaVersionEvent
    | BackfillProgressEvent
    | DocumentDeletedEvent
    | HeartbeatEvent,
    Field(discriminator="type"),
]
"""Every message that can arrive on the workspace event stream."""


# Events on the per-query stream, which is a separate short-lived connection.


class QuerySqlEvent(BaseModel):
    """The generated SQL, sent before execution so the user sees it immediately. FR-41."""

    type: Literal["query.sql"] = "query.sql"
    sql: str
    explanation: str


class QuerySurfaceEvent(BaseModel):
    """One Agent-to-User Interface message for the result surface."""

    type: Literal["query.surface"] = "query.surface"
    message: dict[str, object]


class QueryDoneEvent(BaseModel):
    """The query finished. Carries the numbers the interface reports."""

    type: Literal["query.done"] = "query.done"
    row_count: int
    duration_ms: float
    truncated: bool = Field(
        default=False,
        description="Whether the row limit was reached, so the interface can say the "
        "result is partial instead of implying it is complete.",
    )


class QueryErrorEvent(BaseModel):
    """The query could not be answered, with a message explaining what was tried. FR-40."""

    type: Literal["query.error"] = "query.error"
    code: str
    message: str
    attempted_sql: str | None = None
    missing_fields: list[str] = Field(
        default_factory=list,
        description="Fields the question needs that the schema does not have, so the "
        "interface can offer to add them (requirement 3.5 step 4).",
    )


QueryEvent = Annotated[
    QuerySqlEvent | QuerySurfaceEvent | QueryDoneEvent | QueryErrorEvent,
    Field(discriminator="type"),
]
