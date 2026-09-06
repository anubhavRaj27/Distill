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
is built on, and why the event log is a table rather than in-memory state (decision D12).
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.fields import FieldValue, SchemaChangeAuthor
from app.domain.records import Record


class BaseEvent(BaseModel):
    """Fields every event carries."""

    seq: int = Field(description="Per-workspace monotonic sequence number. The event id.")


class DocumentStatusEvent(BaseEvent):
    """A document moved through the pipeline. Drives the processing strip."""

    type: Literal["document.status"] = "document.status"
    document_id: UUID
    filename: str
    status: str = Field(
        description="One of uploaded, parsing, extracting, indexing, done, failed. A "
        "string rather than the internal enum because the internal state machine has one "
        "more state than the contract exposes: see DocumentStatus.for_wire."
    )
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


class SchemaUpdatedEvent(BaseEvent):
    """The workspace schema changed. The interface refetches the schema and the table.

    Replaces v1's ``schema.version`` and ``schema.proposal``. In v2 there are no schema
    questions to answer (decision D27), so an event announcing a change is all the client
    needs: it never has to render a decision.

    ``summary`` is user-facing prose, and it is the ONLY explanation the user gets for a
    change the system made without asking. That is the trade decision D27 makes, so the
    wording carries real weight: "kept 'Supplier' as a separate field because it was too
    close to call against 'Vendor'" is the whole audit trail.
    """

    type: Literal["schema.updated"] = "schema.updated"
    version: int
    summary: str
    added_field_keys: list[str] = Field(default_factory=list)
    removed_field_keys: list[str] = Field(default_factory=list)
    applied_by: SchemaChangeAuthor = Field(
        description="Whether the system changed the schema unprompted, or the user "
        "renamed or merged a field."
    )


class ChatProgressEvent(BaseEvent):
    """Coarse chat state on the WORKSPACE stream. Decision D32.

    Deliberately coarse. The tokens of an answer travel on the per-message stream and are
    never written to ``workspace_events``: persisting every token would turn one question
    into hundreds of durable rows for no benefit, since the finished message is persisted
    in full anyway.

    What this event is for is a second browser tab, or a client that has the workspace
    stream open but not the answer stream, seeing that the conversation is moving.
    """

    type: Literal["chat.progress"] = "chat.progress"
    message_id: UUID
    stage: Literal["retrieving", "reading", "building", "done", "failed"]
    detail: str | None = None


class DashboardStatusEvent(BaseEvent):
    """The dashboard is being generated, is ready, or has gone stale. FR-33."""

    type: Literal["dashboard.status"] = "dashboard.status"
    status: Literal["pending", "ready", "failed"]
    stale: bool = Field(
        description="Set when documents were added or values corrected since generation, "
        "so the interface can offer to regenerate rather than silently showing old panels."
    )
    panel_count: int = 0


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
    | SchemaUpdatedEvent
    | ChatProgressEvent
    | DashboardStatusEvent
    | DocumentDeletedEvent
    | HeartbeatEvent,
    Field(discriminator="type"),
]
"""Every message that can arrive on the workspace event stream."""
