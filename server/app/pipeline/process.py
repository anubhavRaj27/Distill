"""The per-document pipeline, end to end.

    uploaded -> parsed -> extracting -> (awaiting_schema) -> done
                                                          -> failed

Every transition publishes an event, so the progress list in the interface is a direct
rendering of this state machine rather than a separate thing that has to be kept in step.

REVIEW FINDING 8.5: WHEN DOES THE FIRST SCHEMA GET PROPOSED
------------------------------------------------------------
"Propose from the first batch" is not implementable as written, because a batch is not
defined: uploading three files and then five more leaves it ambiguous, and the worker would
race to propose a schema from whichever document finished first.

The rule implemented here: a document that finishes open extraction with no schema in the
workspace parks its raw output and moves to ``awaiting_schema``. The proposal fires when no
document in the workspace is still working, debounced to absorb staggered uploads, under a
per-workspace lock so two documents finishing together cannot both propose. Once the schema
exists, every parked document is mapped onto it **without another model call**, because the
open extraction already read those documents and paying twice for the same reading would be
both slow and wasteful.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections import defaultdict
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Document, DocumentExtraction, Page, Proposal, Record
from app.db.session import session_scope
from app.domain.document import DocumentStatus, ParsedDocument
from app.domain.events import DocumentStatusEvent, SchemaProposalEvent
from app.domain.fields import FieldSpec, SchemaChangeAuthor
from app.errors import DistillError, LLMUnavailable, ParseFailed
from app.events.bus import bus
from app.llm.base import LLMClient
from app.llm.contracts import ExtractedField, OpenExtraction
from app.logging import get_logger, logging_context
from app.pipeline import extract as extract_module
from app.pipeline import persist as persist_module
from app.pipeline.parse.router import parse as parse_document
from app.schema import drift as drift_module
from app.schema import propose as propose_module
from app.schema import versioning
from app.storage.base import Storage
from app.storage.local import LocalStorage, page_image_key

logger = get_logger(__name__)

_proposal_locks: dict[UUID, asyncio.Lock] = defaultdict(asyncio.Lock)
"""One lock per workspace, so two documents finishing at once cannot both propose a schema.

In-process, which is consistent with the single-process constraint decision D9 already
imposes and which ``/healthz`` reports so a misconfiguration is visible.
"""


async def set_status(
    session: AsyncSession,
    document: Document,
    status: DocumentStatus,
    *,
    detail: str | None = None,
    failure: str | None = None,
    attempt: int | None = None,
) -> None:
    """Move a document and announce it. The two always happen together, on purpose."""
    document.status = status
    document.stage_detail = detail
    if failure is not None:
        document.failure_reason = failure
    await session.flush()
    await bus.publish(
        session,
        document.workspace_id,
        DocumentStatusEvent(
            seq=0,
            document_id=document.id,
            filename=document.filename,
            status=status,
            stage_detail=detail,
            failure_reason=document.failure_reason,
            attempt=attempt,
            page_count=document.page_count,
        ),
    )


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _store_pages(
    session: AsyncSession,
    document: Document,
    parsed: ParsedDocument,
    images: list[bytes],
    storage: Storage,
) -> None:
    """Persist page geometry and rendered images.

    The text layer is stored because grounding needs word boxes later, when re-extracting
    or backfilling, and re-parsing the original then would be slow and could produce
    different geometry than the values were originally grounded against.
    """
    existing = (
        (await session.execute(select(Page).where(Page.document_id == document.id)))
        .scalars()
        .all()
    )
    for row in existing:
        await session.delete(row)
    await session.flush()

    for page, image in zip(parsed.pages, images, strict=True):
        key = page_image_key(document.workspace_id, document.id, page.index)
        if isinstance(storage, LocalStorage):
            storage.put_bytes(key, image)
        else:  # pragma: no cover - only one backend exists today
            storage.put_bytes(key, image)
        session.add(
            Page(
                document_id=document.id,
                index=page.index,
                width_pt=page.width_pt,
                height_pt=page.height_pt,
                image_key=key,
                ocr_applied=page.ocr_applied,
                locator=page.locator,
                text_layer={
                    "words": [word.model_dump(mode="json") for word in page.words],
                    "lines": [line.model_dump(mode="json") for line in page.lines],
                },
            )
        )
    document.page_count = parsed.page_count
    await session.flush()


def map_onto_schema(
    fields: list[FieldSpec], extracted: list[ExtractedField]
) -> list[ExtractedField]:
    """Rename open-extraction keys onto schema keys, using the aliases the schema recorded.

    This is what lets a parked open extraction become field values without a second model
    call. ``source_keys`` on each field records every raw key that unified into it, which is
    exactly the lookup table needed here.
    """
    alias_to_field: dict[str, str] = {}
    for field in fields:
        alias_to_field[field.key.lower()] = field.key
        alias_to_field[field.label.lower()] = field.key
        for alias in field.source_keys:
            alias_to_field[alias.lower()] = field.key

    mapped: list[ExtractedField] = []
    claimed: set[str] = set()
    for entry in extracted:
        target = alias_to_field.get((entry.key or "").lower()) or alias_to_field.get(
            (entry.label or "").lower()
        )
        if target is None or target in claimed:
            continue
        claimed.add(target)
        spec = next(field for field in fields if field.key == target)
        mapped.append(entry.model_copy(update={"key": target, "value_type": spec.type}))
    return mapped


async def _ensure_record(
    session: AsyncSession, document: Document, schema_version_id: UUID
) -> Record:
    record = (
        await session.execute(select(Record).where(Record.document_id == document.id))
    ).scalar_one_or_none()
    if record is None:
        record = Record(
            workspace_id=document.workspace_id,
            document_id=document.id,
            schema_version_id=schema_version_id,
        )
        session.add(record)
        await session.flush()
    else:
        record.schema_version_id = schema_version_id
    return record


async def _parked_open_extraction(
    session: AsyncSession, document_id: UUID
) -> OpenExtraction | None:
    row = (
        await session.execute(
            select(DocumentExtraction)
            .where(
                DocumentExtraction.document_id == document_id,
                DocumentExtraction.kind == "open",
            )
            .order_by(DocumentExtraction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return OpenExtraction.model_validate(row.payload) if row else None


# ---------------------------------------------------------------------------
# The stages
# ---------------------------------------------------------------------------


async def _parse_stage(
    session: AsyncSession, document: Document, storage: Storage, settings: Settings
) -> ParsedDocument:
    data = storage.get_bytes(document.storage_key)

    stages: list[str] = []

    def report(detail: str) -> None:
        stages.append(detail)

    parsed, images = parse_document(data, document.source_format, settings, report)
    await _store_pages(session, document, parsed, images, storage)
    await set_status(
        session,
        document,
        DocumentStatus.PARSED,
        detail=stages[-1] if stages else f"read {parsed.page_count} pages",
    )
    return parsed


async def _extract_and_store(
    session: AsyncSession,
    document: Document,
    parsed: ParsedDocument,
    client: LLMClient,
    settings: Settings,
) -> None:
    """Run the right extraction mode, and either park the result or write values."""
    fields = await versioning.current_fields(session, document.workspace_id)

    if not fields:
        # No schema yet. Open extraction, parked until the batch settles.
        await set_status(
            session, document, DocumentStatus.EXTRACTING, detail="finding fields"
        )
        result = await extract_module.open_extract(
            parsed,
            filename=document.filename,
            content_hash=document.content_hash,
            client=client,
            settings=settings,
        )
        session.add(
            DocumentExtraction(
                document_id=document.id,
                kind="open",
                payload=result.model_dump(mode="json"),
                model_name=settings.llm_extract_model,
            )
        )
        await set_status(
            session,
            document,
            DocumentStatus.AWAITING_SCHEMA,
            detail=f"found {len(result.fields)} fields, waiting for the rest of the batch",
        )
        return

    await set_status(
        session, document, DocumentStatus.EXTRACTING, detail="filling your schema"
    )
    version_row = await versioning.current_version(session, document.workspace_id)
    assert version_row is not None
    guided = await extract_module.guided_extract(
        parsed,
        filename=document.filename,
        content_hash=document.content_hash,
        fields=fields,
        schema_version=version_row.version,
        client=client,
        settings=settings,
    )
    session.add(
        DocumentExtraction(
            document_id=document.id,
            kind="guided",
            schema_version=version_row.version,
            payload=guided.model_dump(mode="json"),
            model_name=settings.llm_extract_model,
        )
    )

    # Drift, before writing values, so an auto-mapped extra lands in the right column on
    # this very document rather than only on the next one.
    outcome = await drift_module.assess(
        guided.extra_fields, fields, client=client, settings=settings
    )
    if outcome.changes_the_schema:
        widened = drift_module.merged_schema(fields, outcome)
        await versioning.apply(
            session,
            document.workspace_id,
            widened,
            author=SchemaChangeAuthor.MODEL_AUTO,
            summary=outcome.summary,
            settings=settings,
        )
        fields = widened
        version_row = await versioning.current_version(session, document.workspace_id)
        assert version_row is not None

    for question in outcome.questions:
        session.add(
            Proposal(
                workspace_id=document.workspace_id,
                document_id=document.id,
                kind="drift",
                payload={
                    "incoming_key": question.incoming_key,
                    "incoming_label": question.incoming_label,
                    "incoming_type": question.incoming_type.value,
                    "sample_value": question.sample_value,
                    "reason": question.reason,
                    "candidates": [
                        {"key": key, "label": label, "score": score}
                        for key, label, score in question.candidates
                    ],
                },
            )
        )
    await session.flush()

    # Values for the schema fields, plus any extra that auto-mapped onto one.
    remapped: list[ExtractedField] = list(guided.values)
    for extra in guided.extra_fields:
        target = outcome.mappings.get(extra.key)
        if target:
            spec = next((f for f in fields if f.key == target), None)
            if spec is not None:
                remapped.append(
                    extra.model_copy(update={"key": target, "value_type": spec.type})
                )
        elif extra.key in {field.key for field in outcome.additions}:
            remapped.append(extra)

    record = await _ensure_record(session, document, version_row.id)
    await persist_module.persist_values(
        session,
        workspace_id=document.workspace_id,
        record=record,
        document=document,
        pages=persist_module.pages_from_rows(
            list(
                (
                    await session.execute(select(Page).where(Page.document_id == document.id))
                )
                .scalars()
                .all()
            )
        ),
        extracted=remapped,
        fields=fields,
        settings=settings,
        publish_events=False,
    )
    await persist_module.publish_record(
        session, document.workspace_id, record, document, version_row.version
    )
    await set_status(session, document, DocumentStatus.DONE, detail=None)


async def process_document(
    document_id: UUID, *, client: LLMClient, settings: Settings, storage: Storage
) -> None:
    """Run one document through the whole pipeline.

    Failures are contained: a document that cannot be read is marked failed with a reason
    written for the user, and every other document in the collection is unaffected. That is
    guarantee 3 in the backend plan, and requirement 3.6.
    """
    async with session_scope() as session:
        document = await session.get(Document, document_id)
        if document is None:
            logger.warning("process.document_missing", document_id=str(document_id))
            return
        workspace_id = document.workspace_id
        filename = document.filename

    with logging_context(workspace_id=str(workspace_id), document_id=str(document_id)):
        try:
            async with session_scope() as session:
                document = await session.get(Document, document_id)
                assert document is not None
                parsed = await _parse_stage(session, document, storage, settings)
                await _extract_and_store(session, document, parsed, client, settings)
        except ParseFailed as exc:
            await _mark_failed(document_id, exc.message)
            return
        except LLMUnavailable as exc:
            await _mark_failed(document_id, exc.message)
            return
        except DistillError as exc:
            await _mark_failed(document_id, exc.message)
            return
        except Exception as exc:
            logger.exception("process.unexpected_failure", error_type=type(exc).__name__)
            await _mark_failed(
                document_id,
                "Something went wrong while processing this file. The rest of your "
                "documents were not affected.",
            )
            return

        logger.info("process.completed", filename=filename)

    await maybe_propose_initial_schema(workspace_id, client=client, settings=settings)


async def _mark_failed(document_id: UUID, reason: str) -> None:
    """Record a failure in its own transaction, since the original one is rolled back."""
    async with session_scope() as session:
        document = await session.get(Document, document_id)
        if document is None:
            return
        await set_status(
            session, document, DocumentStatus.FAILED, detail=None, failure=reason
        )
    logger.info("process.failed", document_id=str(document_id), reason=reason[:120])


# ---------------------------------------------------------------------------
# The initial schema proposal. Review finding 8.5.
# ---------------------------------------------------------------------------

_BUSY_STATUSES = (
    DocumentStatus.UPLOADED,
    DocumentStatus.PARSED,
    DocumentStatus.EXTRACTING,
)


async def maybe_propose_initial_schema(
    workspace_id: UUID, *, client: LLMClient, settings: Settings
) -> None:
    """Propose and apply the first schema, if the batch has settled.

    Held under a per-workspace lock, so two documents finishing at the same instant produce
    one schema rather than two competing ones.
    """
    async with _proposal_locks[workspace_id]:
        await asyncio.sleep(settings.schema_proposal_debounce_seconds)

        async with session_scope() as session:
            if await versioning.current_version(session, workspace_id) is not None:
                return  # another document already established the schema

            busy = (
                await session.execute(
                    select(func.count())
                    .select_from(Document)
                    .where(
                        Document.workspace_id == workspace_id,
                        Document.status.in_(_BUSY_STATUSES),
                    )
                )
            ).scalar_one()
            if busy:
                return  # still working; whichever document finishes last will get here

            waiting = list(
                (
                    await session.execute(
                        select(Document).where(
                            Document.workspace_id == workspace_id,
                            Document.status == DocumentStatus.AWAITING_SCHEMA,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not waiting:
                return

            extractions: dict[str, list[ExtractedField]] = {}
            parked: dict[str, OpenExtraction] = {}
            for document in waiting:
                result = await _parked_open_extraction(session, document.id)
                if result is None:
                    continue
                extractions[str(document.id)] = result.fields
                parked[str(document.id)] = result

            proposal = await propose_module.propose_initial(
                extractions, client=client, settings=settings
            )
            if not proposal.fields:
                for document in waiting:
                    await set_status(
                        session,
                        document,
                        DocumentStatus.FAILED,
                        failure="We could not find any structured fields in this document.",
                    )
                return

            version_row = await versioning.apply(
                session,
                workspace_id,
                proposal.fields,
                author=SchemaChangeAuthor.MODEL_AUTO,
                summary=proposal.summary,
                settings=settings,
            )

            # Decision D25: uncertain unification stays split, and asks. Non-blocking, so
            # the table is already usable while the question waits in the review surface.
            if proposal.questions:
                row = Proposal(
                    workspace_id=workspace_id,
                    kind="initial_schema",
                    payload={
                        "questions": [
                            {
                                "left_key": question.left_key,
                                "right_key": question.right_key,
                                "reason": question.reason,
                            }
                            for question in proposal.questions
                        ]
                    },
                )
                session.add(row)
                await session.flush()
                await bus.publish(
                    session,
                    workspace_id,
                    SchemaProposalEvent(
                        seq=0, proposal_id=row.id, kind="initial_schema", surface=[]
                    ),
                )

            # Map every parked extraction onto the new schema, with no second model call.
            for document in waiting:
                result = parked.get(str(document.id))
                if result is None:
                    await set_status(
                        session,
                        document,
                        DocumentStatus.FAILED,
                        failure="We lost this document's extraction. Try re-uploading it.",
                    )
                    continue
                mapped = map_onto_schema(proposal.fields, result.fields)
                record = await _ensure_record(session, document, version_row.id)
                pages = persist_module.pages_from_rows(
                    list(
                        (
                            await session.execute(
                                select(Page).where(Page.document_id == document.id)
                            )
                        )
                        .scalars()
                        .all()
                    )
                )
                await persist_module.persist_values(
                    session,
                    workspace_id=workspace_id,
                    record=record,
                    document=document,
                    pages=pages,
                    extracted=mapped,
                    fields=proposal.fields,
                    settings=settings,
                    publish_events=False,
                )
                await persist_module.publish_record(
                    session, workspace_id, record, document, version_row.version
                )
                await set_status(session, document, DocumentStatus.DONE)

            logger.info(
                "process.initial_schema_applied",
                workspace_id=str(workspace_id),
                fields=len(proposal.fields),
                documents=len(waiting),
                questions=len(proposal.questions),
            )
