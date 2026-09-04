"""Chunking, embedding, and storing a document's passages. Implementation section 6.3.

Runs as the document's ``indexing`` stage, after values are persisted and before the
document is reported ``done``. That ordering is the point: a document is not answerable
until it is indexed, so making indexing part of reaching ``done`` means "in the table" and
"askable in chat" become the same moment. A user who sees a row appear and then gets "not in
these documents" for a question about it would be right to distrust the whole product.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Chunk as ChunkRow
from app.db.models import Document, FieldValueRow, Page, Record
from app.domain.document import ParsedPage
from app.domain.fields import FieldSpec
from app.llm.base import LLMClient
from app.logging import get_logger
from app.retrieval import chunking
from app.retrieval.embedding import LEXICAL_MODEL, embed_texts
from app.retrieval.search import vector_space_for

logger = get_logger(__name__)

EMBED_BATCH = 64
"""Chunks per embedding request. Implementation section 6.3 step 3."""


def _render_value(value: object) -> str:
    """A field value as the digest should read it.

    Currency is written with its code because "12480.5" and "12,480.50 USD" retrieve
    differently, and the code is part of the value anyway (decision D4's reasoning).
    """
    if value is None:
        return ""
    if isinstance(value, dict) and "amount" in value:
        code = value.get("currency") or ""
        return f"{value['amount']} {code}".strip()
    if isinstance(value, list):
        return ", ".join(str(entry) for entry in value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


async def _digest_values(
    session: AsyncSession, document_id: UUID, fields: list[FieldSpec]
) -> list[tuple[str, str]]:
    """The document's extracted record as ``(label, value)`` pairs, in schema order."""
    record = (
        await session.execute(select(Record).where(Record.document_id == document_id))
    ).scalar_one_or_none()
    if record is None:
        return []

    rows = {
        row.field_key: row
        for row in (
            await session.execute(
                select(FieldValueRow).where(FieldValueRow.record_id == record.id)
            )
        )
        .scalars()
        .all()
    }
    pairs: list[tuple[str, str]] = []
    for field in fields:
        row = rows.get(field.key)
        if row is None:
            continue
        rendered = _render_value(row.value)
        if rendered:
            pairs.append((field.label, rendered))
    return pairs


def _pages_from_rows(rows: list[Page]) -> list[ParsedPage]:
    from app.pipeline.persist import pages_from_rows

    return pages_from_rows(rows)


async def index_document(
    session: AsyncSession,
    document: Document,
    *,
    fields: list[FieldSpec],
    client: LLMClient,
    settings: Settings,
) -> int:
    """Chunk, embed, and store the document's passages. Returns the chunk count.

    Idempotent: existing chunks for the document are deleted first, so re-extraction
    re-indexes rather than accumulating duplicate passages that would compete with each
    other in retrieval.
    """
    await session.execute(delete(ChunkRow).where(ChunkRow.document_id == document.id))

    page_rows = list(
        (
            await session.execute(
                select(Page).where(Page.document_id == document.id).order_by(Page.index)
            )
        )
        .scalars()
        .all()
    )
    pages = _pages_from_rows(page_rows)

    chunks = chunking.chunk_pages(
        pages,
        target_words=settings.chunk_target_words,
        max_words=settings.chunk_max_words,
        overlap_lines=settings.chunk_overlap_lines,
    )

    digest = chunking.digest_chunk(
        ordinal=len(chunks),
        filename=document.filename,
        values=await _digest_values(session, document.id, fields),
    )
    if digest is not None:
        chunks.append(digest)

    if not chunks:
        logger.info("index.no_chunks", document_id=str(document.id))
        return 0

    # Stay in the space this workspace already uses, so the question and the chunks remain
    # comparable. See the note in retrieval/search.vector_space_for.
    existing_space = await vector_space_for(session, document.workspace_id)
    force_lexical = existing_space == LEXICAL_MODEL

    stored = 0
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        embedded = await embed_texts(
            client,
            [chunk.text for chunk in batch],
            model_name=settings.llm_embed_model,
            force_lexical=force_lexical,
        )
        for chunk, vector in zip(batch, embedded, strict=True):
            session.add(
                ChunkRow(
                    workspace_id=document.workspace_id,
                    document_id=document.id,
                    ordinal=chunk.ordinal,
                    page_index=chunk.page_index,
                    word_start=chunk.word_start,
                    word_end=chunk.word_end,
                    text=chunk.text,
                    token_estimate=chunk.token_estimate,
                    is_digest=chunk.is_digest,
                    embedding=vector.vector,
                    embedding_model=vector.model,
                )
            )
            stored += 1

    await session.flush()
    logger.info(
        "index.completed",
        document_id=str(document.id),
        chunks=stored,
        has_digest=digest is not None,
        space=existing_space or settings.llm_embed_model,
    )
    return stored
