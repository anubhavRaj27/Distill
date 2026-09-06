"""Finding the passages that answer a question. Decisions D24 and D25.

Cosine similarity computed in process over every chunk in the workspace. A workspace of 25
documents at roughly 40 passages each is about a thousand vectors, which is scanned in
single-digit milliseconds, so this avoids making pgvector part of the one-command setup
(decision D25).

TWO THINGS THIS DOES BEYOND RANKING
------------------------------------
**It embeds the question in the space the chunks actually live in.** A workspace indexed
without an API key holds lexical vectors; one indexed with a key holds Gemini vectors.
Embedding the question the wrong way would produce cosines that are pure noise, and the
symptom would be a chat that retrieves confidently and wrongly rather than one that
obviously fails. ``vector_space_for`` reads the workspace's own chunks to decide.

**It always includes the records digest of every document it retrieved from.** The digest is
the extracted record written in the schema's vocabulary, so pulling it in means a question
that matched a page can still be answered with the structured values from that same
document, and the model can cite either. Without this, "what did we pay Acme" could retrieve
the page that names Acme and then have no access to the amount the pipeline already parsed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Chunk, Document
from app.llm.base import LLMClient
from app.logging import get_logger
from app.retrieval.embedding import LEXICAL_MODEL, cosine, embed_texts, lexical_tokens

logger = get_logger(__name__)


@dataclass
class RetrievedChunk:
    """One passage offered to the model, with everything a citation will need."""

    chunk_id: UUID
    document_id: UUID
    filename: str
    page_index: int | None
    word_start: int | None
    word_end: int | None
    text: str
    score: float
    is_digest: bool

    def as_source(self) -> dict[str, object]:
        """The shape the ``sources`` event and the persisted message use."""
        return {
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "filename": self.filename,
            "page_index": self.page_index,
            "is_digest": self.is_digest,
        }


async def vector_space_for(session: AsyncSession, workspace_id: UUID) -> str | None:
    """Which embedding model this workspace's chunks were indexed with.

    Returns the most common one, or ``None`` when the workspace has no chunks. Most common
    rather than strictly one, because a workspace can legitimately be mixed: indexed
    offline, then a key added, then more documents uploaded. Ranking within the majority
    space and scoring the minority at zero is a graceful outcome; embedding the question in
    a space almost nothing lives in is not.
    """
    models = list(
        (
            await session.execute(
                select(Chunk.embedding_model).where(
                    Chunk.workspace_id == workspace_id, Chunk.embedding_model.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    if not models:
        return None
    return Counter(models).most_common(1)[0][0]


async def search(
    session: AsyncSession,
    workspace_id: UUID,
    question: str,
    *,
    client: LLMClient,
    settings: Settings,
) -> list[RetrievedChunk]:
    """Retrieve the passages most likely to answer ``question``."""
    space = await vector_space_for(session, workspace_id)
    if space is None:
        logger.info("search.no_chunks", workspace_id=str(workspace_id))
        return []

    embedded = await embed_texts(
        client,
        [question],
        model_name=settings.embed_space,
        task="query",
        force_lexical=space == LEXICAL_MODEL,
    )
    query_vector = embedded[0].vector

    if space != LEXICAL_MODEL and space != settings.embed_space:
        # The workspace was indexed in a different space from the one this question was
        # just embedded in, which happens when a model or a width is changed after
        # indexing. Every cosine below will be zero and the chat would answer "not in
        # these documents" about documents that plainly say it, so say so out loud.
        logger.warning(
            "search.space_mismatch",
            workspace_id=str(workspace_id),
            indexed_space=space,
            current_space=settings.embed_space,
            detail="re-index this workspace, or restore the previous LLM_EMBED_* settings",
        )

    rows = list(
        (
            await session.execute(
                select(Chunk, Document.filename)
                .join(Document, Document.id == Chunk.document_id)
                .where(Chunk.workspace_id == workspace_id)
            )
        ).all()
    )

    question_tokens = set(lexical_tokens(question))
    scored: list[RetrievedChunk] = []
    for chunk, filename in rows:
        if not chunk.embedding or chunk.embedding_model != space:
            continue
        score = cosine(query_vector, chunk.embedding)
        # A small lexical bonus, which is open question 1 in the requirements answered as a
        # Should. Embeddings handle identifiers like "INV-2026-0042" poorly because they
        # are not words, and an exact token hit on one is strong evidence. Capped low so it
        # nudges the ranking rather than dominating it.
        if question_tokens:
            overlap = question_tokens & set(lexical_tokens(chunk.text))
            score += min(0.1, 0.02 * len(overlap))
        scored.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                filename=filename,
                page_index=chunk.page_index,
                word_start=chunk.word_start,
                word_end=chunk.word_end,
                text=chunk.text,
                score=min(1.0, score),
                is_digest=chunk.is_digest,
            )
        )

    scored.sort(key=lambda entry: entry.score, reverse=True)
    top = [
        entry
        for entry in scored[: settings.chat_top_k]
        if entry.score >= settings.chat_min_similarity
    ]

    # Pull in the digest of every document represented, so the structured values are
    # available alongside the prose the question matched.
    chosen_ids = {entry.chunk_id for entry in top}
    documents = {entry.document_id for entry in top}
    for entry in scored:
        if (
            entry.is_digest
            and entry.document_id in documents
            and entry.chunk_id not in chosen_ids
        ):
            top.append(entry)
            chosen_ids.add(entry.chunk_id)

    logger.info(
        "search.completed",
        workspace_id=str(workspace_id),
        candidates=len(scored),
        returned=len(top),
        space=space,
        best=round(top[0].score, 3) if top else None,
    )
    return top
