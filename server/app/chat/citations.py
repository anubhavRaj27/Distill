"""Resolving a cited chunk to a highlightable region. Decision D45, requirement FR-22.

A citation is chunk-level. The model writes ``[^chunk:<id>]`` and the chunk IS the citation,
so there is no quote to locate and no fuzzy matching involved: the chunk already recorded
which words of which page it covers, and the highlight is those words' boxes grouped into
visual lines.

That is the whole reason chunks are kept small (decision D45): chunk size is highlight size.

DIGEST CHUNKS ARE THE INTERESTING CASE
---------------------------------------
A records digest has no page and no word span. It is the document's extracted values
rendered as ``label: value`` lines, and it exists so that a question phrased in the schema's
vocabulary retrieves the record even when the page text uses different words.

When the model cites one, "every citation lights up on a page" still has to hold. So the
digest resolves through the underlying ``field_values`` provenance: the page where most of
the document's grounded values were found, and the boxes of those values. Clicking it
highlights where the extracted data actually came from, which is a truthful and useful
answer to "where did this come from".

What it cannot do is single out which field the model had in mind, because the marker does
not say. Highlighting all of them is the honest generalisation rather than a guess at one.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Document, FieldValueRow, Page, Record
from app.domain.geometry import BBox, group_into_lines
from app.domain.provenance import Provenance
from app.logging import get_logger
from app.pipeline.persist import pages_from_rows

logger = get_logger(__name__)

MAX_BOXES = 40
"""Highlight rectangles per citation. A digest for a wide schema could otherwise light up
most of a page, which reads as noise rather than as provenance."""

EXCERPT_LENGTH = 240


@dataclass
class ResolvedCitation:
    """Everything the client needs to open the source and light up the passage."""

    chunk_id: UUID
    document_id: UUID
    filename: str
    page_index: int | None
    boxes: list[BBox]
    excerpt: str

    def to_payload(self, n: int) -> dict[str, object]:
        return {
            "n": n,
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "filename": self.filename,
            "page_index": self.page_index,
            "boxes": [box.model_dump() for box in self.boxes],
            "excerpt": self.excerpt,
        }


def _excerpt(text: str) -> str:
    flattened = " ".join(text.split())
    if len(flattened) <= EXCERPT_LENGTH:
        return flattened
    return flattened[: EXCERPT_LENGTH - 1].rstrip() + "…"


async def _digest_provenance(
    session: AsyncSession, document_id: UUID
) -> tuple[int | None, list[BBox]]:
    """Where a document's extracted values were found, for a digest citation."""
    record = (
        await session.execute(select(Record).where(Record.document_id == document_id))
    ).scalar_one_or_none()
    if record is None:
        return None, []

    rows = list(
        (
            await session.execute(
                select(FieldValueRow).where(FieldValueRow.record_id == record.id)
            )
        )
        .scalars()
        .all()
    )

    by_page: dict[int, list[BBox]] = defaultdict(list)
    for row in rows:
        if not row.provenance:
            continue
        try:
            provenance = Provenance.model_validate(row.provenance)
        except ValueError:
            continue
        if provenance.page_index is None or not provenance.boxes:
            continue
        by_page[provenance.page_index].extend(provenance.boxes)

    if not by_page:
        return None, []

    # The page carrying the most grounded values is the one worth opening.
    page_index = max(by_page, key=lambda index: len(by_page[index]))
    return page_index, group_into_lines(by_page[page_index])[:MAX_BOXES]


async def resolve_chunk(
    session: AsyncSession, chunk_id: UUID
) -> ResolvedCitation | None:
    """Resolve one chunk to a citation, or ``None`` if it no longer exists.

    Returns ``None`` rather than raising: a chunk can legitimately disappear between
    retrieval and citation if the document was deleted mid-answer, and dropping the
    footnote is a far better outcome than failing an answer that was otherwise fine.
    """
    row = (
        await session.execute(
            select(Chunk, Document.filename)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id == chunk_id)
        )
    ).one_or_none()
    if row is None:
        logger.info("chat.citation_chunk_missing", chunk_id=str(chunk_id))
        return None

    chunk, filename = row

    if chunk.is_digest:
        page_index, boxes = await _digest_provenance(session, chunk.document_id)
        return ResolvedCitation(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            filename=filename,
            page_index=page_index,
            boxes=boxes,
            excerpt=_excerpt(chunk.text),
        )

    boxes: list[BBox] = []
    if chunk.page_index is not None and chunk.word_start is not None:
        page_rows = list(
            (
                await session.execute(
                    select(Page).where(
                        Page.document_id == chunk.document_id,
                        Page.index == chunk.page_index,
                    )
                )
            )
            .scalars()
            .all()
        )
        pages = pages_from_rows(page_rows)
        if pages:
            words = pages[0].words[chunk.word_start : chunk.word_end or None]
            if words:
                boxes = group_into_lines([word.box for word in words])[:MAX_BOXES]

    if not boxes:
        logger.info(
            "chat.citation_without_boxes",
            chunk_id=str(chunk.id),
            page_index=chunk.page_index,
            detail="the viewer opens the page without a highlight",
        )

    return ResolvedCitation(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        filename=filename,
        page_index=chunk.page_index,
        boxes=boxes,
        excerpt=_excerpt(chunk.text),
    )
