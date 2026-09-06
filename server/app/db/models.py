"""The database schema. Implementation.md section 4, plus decisions D12 and D13.

Two shape decisions carry most of the weight.

**One row per (record, field), not one row per record.** ``field_values`` is tall rather
than wide. That makes provenance, confidence, and human-verified status per-VALUE columns
rather than nested inside a blob, which in turn makes the guarantee in principle 4 of
requirements.md ("never lose a human correction") a single ``WHERE`` clause that the database
enforces, instead of application logic that a future code path could forget. See decision D4.

**Enumerations are stored as constrained text, not as native Postgres enum types.** A native
enum needs ``ALTER TYPE`` to add a value, which is a migration for what is often a one-line
product change. ``Enum(..., native_enum=False)`` gives a ``VARCHAR`` with a ``CHECK``
constraint: the same validation at the database boundary, without the migration cost.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.domain.chat import ChatRole, ChatStatus, DashboardStatus
from app.domain.document import DocumentStatus, SourceFormat
from app.domain.fields import FieldType, SchemaChangeAuthor, Tier, ValueStatus


class Base(DeclarativeBase):
    """Declarative base. ``type_annotation_map`` keeps column types out of every model."""

    # ClassVar, because this is configuration read by the declarative machinery, not a
    # mapped column. Without the annotation, SQLAlchemy would try to map it and ruff would
    # correctly flag a mutable class attribute.
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        datetime: DateTime(timezone=True),
    }


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


def _enum(python_enum: type, name: str) -> Enum:
    """A VARCHAR column with a CHECK constraint listing the permitted values.

    ``create_constraint=True`` is NOT the default. SQLAlchemy changed it to False in 1.4,
    so ``native_enum=False`` alone produces a plain VARCHAR with no validation at all,
    which would leave the database accepting any string in a tier or status column. Passing
    it explicitly is what makes the constraint real.
    """
    return Enum(
        python_enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
        length=32,
    )


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------


class Workspace(Base):
    """An anonymous workspace. The only unit of access control. See decision D7."""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = _uuid_pk()

    # Only the hash is stored. A leaked database therefore does not hand over access to
    # every workspace, which matters more here than usual because the token IS the only
    # credential (decision D7).
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Per-workspace monotonic event counter, allocated with
    # `UPDATE workspaces SET event_seq = event_seq + 1 ... RETURNING event_seq`.
    # The row lock that update takes is what makes the sequence gap-free and correctly
    # ordered under concurrency, which `Last-Event-ID` resume depends on. A global
    # bigserial would be monotonic but not per-workspace, so a client resuming would have
    # to reason about identifiers belonging to workspaces it cannot see.
    event_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    created_at: Mapped[datetime] = _created_at()

    documents: Mapped[list[Document]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Documents and pages
# ---------------------------------------------------------------------------


class Document(Base):
    """One uploaded file, and its position in the pipeline."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_workspace_created", "workspace_id", "created_at"),
        Index("ix_documents_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )

    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime: Mapped[str] = mapped_column(String(128), nullable=False)
    source_format: Mapped[SourceFormat] = mapped_column(
        _enum(SourceFormat, "source_format"), nullable=False
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # SHA-256 of the file contents. Two jobs: it deduplicates a re-upload of the same file,
    # and it is the key the fake Large Language Model provider uses to find a recorded
    # response, which is what makes the test suite stable across prompt edits
    # (review finding 8.6).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)

    status: Mapped[DocumentStatus] = mapped_column(
        _enum(DocumentStatus, "document_status"),
        nullable=False,
        default=DocumentStatus.UPLOADED,
    )
    stage_detail: Mapped[str | None] = mapped_column(String(256), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    workspace: Mapped[Workspace] = relationship(back_populates="documents")
    pages: Mapped[list[Page]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Page.index"
    )
    record: Mapped[Record | None] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )


class Page(Base):
    """One page of a parsed document, with its text layer and word geometry.

    ``text_layer`` holds the words and lines as produced by the parser, in the coordinate
    convention documented in ``app.domain.geometry``. Grounding reads it, so keeping it
    means re-grounding a value after a prompt change never needs the original file reparsed.
    """

    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "index", name="uq_pages_document_index"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )

    index: Mapped[int] = mapped_column(Integer, nullable=False)
    width_pt: Mapped[float] = mapped_column(Float, nullable=False)
    height_pt: Mapped[float] = mapped_column(Float, nullable=False)

    image_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ocr_applied: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    locator: Mapped[str | None] = mapped_column(String(128), nullable=True)

    text_layer: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    document: Mapped[Document] = relationship(back_populates="pages")


class DocumentExtraction(Base):
    """The raw output of one extraction run, kept before it becomes field values.

    Needed because of review finding 8.5: a document in the first batch finishes OPEN
    extraction before the workspace has any schema, so there is nowhere yet to put its
    values. The raw output is parked here until the schema proposal is accepted, and then
    mapped into ``field_values`` without re-calling the model, which saves both a round trip
    and the money.
    """

    __tablename__ = "document_extractions"
    __table_args__ = (
        Index("ix_extractions_document_kind", "document_id", "kind"),
        CheckConstraint("kind IN ('open', 'guided', 'backfill')", name="ck_extraction_kind"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# Schema versions
# ---------------------------------------------------------------------------


class SchemaVersion(Base):
    """An immutable snapshot of the workspace's field schema.

    Versions are never edited, only superseded, and ``parent_id`` records what each was
    derived from. That is what makes the history view and one-click revert (FR-15) a read
    rather than a reconstruction.
    """

    __tablename__ = "schema_versions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "version", name="uq_schema_versions_ws_version"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    # [{key, label, type, description, enum_values?, currency_default?, source_keys, weight}]
    fields: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)

    # Constrained, not a bare VARCHAR. Decision D27 makes this column the difference
    # between "the system changed your schema without asking" and "you changed it", which
    # the history view renders and the user's trust rests on. A value outside the vocabulary
    # would be a silently mislabelled audit entry, so the database refuses it.
    created_by: Mapped[SchemaChangeAuthor] = mapped_column(
        _enum(SchemaChangeAuthor, "schema_change_author"),
        nullable=False,
        server_default=SchemaChangeAuthor.MODEL_AUTO.value,
    )
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("schema_versions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# Records and values
# ---------------------------------------------------------------------------


class Record(Base):
    """One document's worth of extracted values. One row of the unified table."""

    __tablename__ = "records"
    __table_args__ = (
        # One record per document. Re-extraction updates values in place rather than
        # creating a second row, which is what lets a human correction survive it.
        UniqueConstraint("document_id", name="uq_records_document"),
        Index("ix_records_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    schema_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schema_versions.id", ondelete="RESTRICT"), nullable=False
    )

    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    document: Mapped[Document] = relationship(back_populates="record")
    values: Mapped[list[FieldValueRow]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )


class FieldValueRow(Base):
    """One extracted or corrected value. The unit the never-lose guarantee protects.

    Table name is ``field_values``; the class is ``FieldValueRow`` so it does not collide
    with the wire model ``app.domain.fields.FieldValue``.
    """

    __tablename__ = "field_values"
    __table_args__ = (
        UniqueConstraint("record_id", "field_key", name="uq_field_values_record_field"),
        # Partial index over the rows a model must never touch. Every model write path
        # filters `status <> 'human_verified'`, and this makes that filter cheap.
        Index(
            "ix_field_values_human_owned",
            "record_id",
            postgresql_where="status IN ('human_verified', 'not_present')",
        ),
        Index("ix_field_values_tier", "tier"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # JSONB rather than a typed column, because a value's type is whatever the schema says
    # today and the schema is the user's to change. See decision D4.
    #
    # Typed `Any`, not `dict`: a JSONB column legitimately holds a bare string for a STRING
    # field, a number for NUMBER, a bool for BOOLEAN, a list for STRING_LIST, and an object
    # only for CURRENCY. The stored representation per type is documented in
    # `app.domain.values`.
    value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    value_type: Mapped[FieldType] = mapped_column(_enum(FieldType, "field_type"), nullable=False)

    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    tier: Mapped[Tier] = mapped_column(_enum(Tier, "value_tier"), nullable=False)
    status: Mapped[ValueStatus] = mapped_column(
        _enum(ValueStatus, "value_status"), nullable=False, default=ValueStatus.MODEL
    )

    # {page_index, boxes, quote, reasoning, match_score, locator, failure}
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Decision D13. When re-extraction disagrees with a human-verified value, the human's
    # value stays in `value` and the model's answer is kept here, so the interface can show
    # both and let the user decide rather than merely warning that a disagreement exists.
    model_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    model_value_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    model_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = _updated_at()

    record: Mapped[Record] = relationship(back_populates="values")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class WorkspaceEventRow(Base):
    """The persisted event log. Decision D12.

    This exists so that ``Last-Event-ID`` resume is implementable at all: a client that
    reconnects needs to be told what it missed, and that is impossible if the log lived only
    in the memory of the connection that dropped.
    """

    __tablename__ = "workspace_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "seq", name="uq_workspace_events_ws_seq"),
        Index("ix_workspace_events_ws_seq", "workspace_id", "seq"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created_at()


# ---------------------------------------------------------------------------
# Retrieval, chat, and the dashboard (v2)
# ---------------------------------------------------------------------------


class Chunk(Base):
    """One retrievable passage of a document. Decisions D24 and D33.

    ``word_start`` and ``word_end`` index into the page's ``text_layer`` word list, which is
    what lets a chat citation resolve to highlight boxes **without re-parsing the original
    file**. The word geometry was already stored for grounding, so a citation costs a slice
    rather than a parse.

    Chunk size IS highlight size, because a citation highlights the whole chunk's word span
    (decision D33). That is why passages are kept to roughly 80 to 160 words: a 500 word
    chunk would light up half a page and tell the user nothing.

    ``page_index`` is null for the per-document **records digest**, a synthetic chunk whose
    text is the extracted record rendered as ``label: value`` lines. It exists so a question
    phrased in the schema's vocabulary retrieves the record even when the page text uses
    different words. It has no boxes; a citation to one resolves through the underlying
    field value's provenance instead.
    """

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_chunks_document_ordinal"),
        Index("ix_chunks_document", "document_id"),
        Index("ix_chunks_workspace", "workspace_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Denormalised from documents on purpose: retrieval scans every chunk in a workspace on
    # every question, and doing that through a join to documents is a needless cost on the
    # hottest read in the product.
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )

    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="Null for the records digest, which has no page."
    )
    word_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_digest: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    # JSONB rather than a vector column. Decision D25: a workspace of 25 documents is about
    # a thousand vectors, which an in-process cosine scans in single-digit milliseconds, and
    # this avoids making pgvector part of the one-command setup.
    embedding: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = _created_at()


class ChatMessage(Base):
    """One turn of the conversation. Decision D32.

    ``content`` is written once, at the end of generation or on stop. While an answer is
    streaming its text lives in the in-memory answer buffer, not here: persisting every
    token would turn one question into hundreds of writes, and the buffer is what a
    reconnecting client resumes from anyway.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_messages_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[ChatRole] = mapped_column(_enum(ChatRole, "chat_role"), nullable=False)
    status: Mapped[ChatStatus] = mapped_column(
        _enum(ChatStatus, "chat_status"), nullable=False, default=ChatStatus.DONE
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    # The passages retrieved for this answer: [{chunk_id, document_id, filename, page_index}]
    sources: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    # [{n, chunk_id, document_id, filename, page_index, boxes, excerpt}]
    citations: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    # The `Visual` the model chose: a query specification, never numbers (decision D26).
    visual: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # The A2UI message array built from evaluating that specification.
    surface: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    model_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamped in PYTHON, not by the server, and that is a correctness fix rather than a
    # preference. Postgres `now()` returns the TRANSACTION start time, so every row written
    # in one transaction shares it. `ask` creates the question and its pending answer in a
    # single transaction, so with a server default the two tie and the conversation has no
    # defined order: history could render the answer above the question.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DashboardRow(Base):
    """The agent-generated dashboard. One row per workspace. FR-30 to FR-34.

    Table name ``dashboards``; the class is ``DashboardRow`` so it does not collide with the
    domain model that describes a dashboard on the wire.
    """

    __tablename__ = "dashboards"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_dashboards_workspace"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[DashboardStatus] = mapped_column(
        _enum(DashboardStatus, "dashboard_status"),
        nullable=False,
        default=DashboardStatus.PENDING,
    )
    # Marked rather than regenerated automatically: regeneration is a model call, and doing
    # one per uploaded document would spend tokens the user did not ask to spend.
    stale: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    # [{title, kind, rationale, query, surface}]
    panels: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    model_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


# ---------------------------------------------------------------------------
# Blobs
# ---------------------------------------------------------------------------


class Blob(Base):
    """An original document or a rendered page image, when storage is the database.

    Only written by ``app.storage.postgres``, which is one of two implementations of the
    storage boundary and the one a free deployment uses, because the container it runs in
    has no disk that survives a restart. See decision D45.

    No foreign key to a document. Keys are hierarchical strings built by
    ``app.storage.local``, deletion is a prefix delete, and the storage layer deliberately
    knows nothing about what a key refers to; a column pointing at ``documents`` would put
    that knowledge in the schema and make the store answerable to a model it does not use.
    """

    __tablename__ = "blobs"

    key: Mapped[str] = mapped_column(String(1024), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

