"""Splitting a parsed document into retrievable passages. Decision D45.

CHUNK SIZE IS HIGHLIGHT SIZE
----------------------------
A chat citation highlights the whole chunk's word span, so how big a chunk is decides how
much of the page lights up when a user clicks a citation. That is the reason passages are
kept to roughly 110 words rather than the 500 or so a pure retrieval-quality argument would
suggest: a chunk covering half a page technically "contains the answer" while showing the
user nothing useful.

WORD RANGES, NOT TEXT OFFSETS
-----------------------------
Each chunk records ``word_start`` and ``word_end`` as indices into the page's word list.
Decision D18 already gave every supported format words with boxes, so a citation resolves to
highlight rectangles by slicing that list and grouping the boxes into lines. No re-parsing,
no character-offset arithmetic, and no format-specific branch.

Assigning words to lines is the one fiddly part, and it is done by walking both lists in
reading order with a moving cursor rather than by geometric containment. Both parsers emit
words and lines in reading order, so a cursor is exact and cheap, whereas containment tests
get confused by superscripts and by lines whose boxes overlap slightly.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.document import ParsedPage
from app.logging import get_logger

logger = get_logger(__name__)

MIN_CHUNK_WORDS = 25
"""Below this a passage is merged into its neighbour. A six word chunk retrieves badly (too
little context to embed) and highlights uselessly, so it is not worth being its own row."""


@dataclass
class Chunk:
    """One passage, ready to embed and store."""

    ordinal: int
    text: str
    page_index: int | None
    word_start: int | None
    word_end: int | None
    is_digest: bool = False
    locator: str | None = None

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def token_estimate(self) -> int:
        """Rough token count. Words times four thirds is close enough for batching."""
        return max(1, (self.word_count * 4) // 3)


@dataclass
class _LineSpan:
    """One line of a page, with the range of words it occupies."""

    text: str
    word_start: int
    word_end: int
    locator: str | None = None

    @property
    def word_count(self) -> int:
        return self.word_end - self.word_start


def line_word_spans(page: ParsedPage) -> list[_LineSpan]:
    """Map each line to its half-open range of word indices.

    Walks words and lines together in reading order. A word is assigned to the current line
    while it vertically overlaps it, and the cursor advances when it stops. Words that match
    no line (rare, and usually a stray mark picked up by text recognition) are skipped
    rather than forced into a neighbour, so a highlight never claims to cover something it
    does not.
    """
    spans: list[_LineSpan] = []
    if not page.lines:
        return spans

    line_index = 0
    start: int | None = None

    for word_index, word in enumerate(page.words):
        # Advance past any line this word is already below.
        while line_index < len(page.lines) and not page.lines[line_index].box.vertically_overlaps(
            word.box, tolerance=1.0
        ):
            if start is not None:
                spans.append(
                    _LineSpan(
                        text=page.lines[line_index].text,
                        word_start=start,
                        word_end=word_index,
                        locator=page.lines[line_index].locator,
                    )
                )
                start = None
            line_index += 1

        if line_index >= len(page.lines):
            break
        if start is None:
            start = word_index

    if start is not None and line_index < len(page.lines):
        spans.append(
            _LineSpan(
                text=page.lines[line_index].text,
                word_start=start,
                word_end=len(page.words),
                locator=page.lines[line_index].locator,
            )
        )

    # Any trailing lines that got no words still deserve to be retrievable: their text was
    # extracted, it just has no geometry. They chunk with a null span and cite to the page.
    for remaining in range(line_index + 1, len(page.lines)):
        line = page.lines[remaining]
        if line.text.strip():
            spans.append(
                _LineSpan(text=line.text, word_start=-1, word_end=-1, locator=line.locator)
            )
    return spans


def chunk_page(
    page: ParsedPage,
    *,
    start_ordinal: int,
    target_words: int,
    max_words: int,
    overlap_lines: int,
) -> list[Chunk]:
    """Split one page into passages at line boundaries."""
    spans = line_word_spans(page)
    if not spans:
        return []

    chunks: list[Chunk] = []
    current: list[_LineSpan] = []
    ordinal = start_ordinal

    def flush() -> None:
        nonlocal current, ordinal
        if not current:
            return
        text = "\n".join(span.text for span in current).strip()
        if not text:
            current = []
            return
        located = [span for span in current if span.word_start >= 0]
        chunks.append(
            Chunk(
                ordinal=ordinal,
                text=text,
                page_index=page.index,
                word_start=located[0].word_start if located else None,
                word_end=located[-1].word_end if located else None,
                locator=page.locator or (current[0].locator if current else None),
            )
        )
        ordinal += 1
        # Carry the last line or two forward, so a fact stated across a boundary is wholly
        # present in at least one chunk rather than split down the middle of both.
        current = current[-overlap_lines:] if overlap_lines else []

    for span in spans:
        words_so_far = sum(entry.word_count or len(entry.text.split()) for entry in current)
        span_words = span.word_count or len(span.text.split())

        if current and words_so_far + span_words > max_words:
            flush()
        current.append(span)
        if sum(
            entry.word_count or len(entry.text.split()) for entry in current
        ) >= target_words:
            flush()

    # The overlap carry-forward can leave a tail identical to the previous chunk's end.
    # Emitting it would store a duplicate passage that competes with its own source in
    # retrieval, so it is only flushed when it has something new in it.
    if current:
        tail = "\n".join(span.text for span in current).strip()
        previous = chunks[-1].text if chunks else ""
        if tail and tail not in previous:
            flush()

    return chunks


def chunk_pages(
    pages: list[ParsedPage],
    *,
    target_words: int,
    max_words: int,
    overlap_lines: int,
) -> list[Chunk]:
    """Split every page of a document.

    Takes pages rather than a ``ParsedDocument`` because both callers have pages: the
    indexer rehydrates them from stored geometry, and the tests parse a fixture. Requiring
    the wrapper meant the indexer had to fabricate one, which is a worse shape than a list.
    """
    chunks: list[Chunk] = []
    for page in pages:
        chunks.extend(
            chunk_page(
                page,
                start_ordinal=len(chunks),
                target_words=target_words,
                max_words=max_words,
                overlap_lines=overlap_lines,
            )
        )

    merged = _merge_runts(chunks)
    logger.info(
        "chunking.completed",
        pages=len(pages),
        chunks=len(merged),
        words=sum(chunk.word_count for chunk in merged),
    )
    return merged


def _merge_runts(chunks: list[Chunk]) -> list[Chunk]:
    """Fold tiny chunks into the previous one on the same page."""
    if not chunks:
        return chunks
    merged: list[Chunk] = []
    for chunk in chunks:
        if (
            merged
            and chunk.word_count < MIN_CHUNK_WORDS
            and merged[-1].page_index == chunk.page_index
            and not chunk.is_digest
        ):
            previous = merged[-1]
            previous.text = f"{previous.text}\n{chunk.text}".strip()
            if chunk.word_end is not None:
                previous.word_end = chunk.word_end
                if previous.word_start is None:
                    previous.word_start = chunk.word_start
            continue
        merged.append(chunk)
    for ordinal, chunk in enumerate(merged):
        chunk.ordinal = ordinal
    return merged


def digest_chunk(
    *, ordinal: int, filename: str, values: list[tuple[str, str]]
) -> Chunk | None:
    """The per-document records digest. Implementation section 6.3 step 2.

    A synthetic passage whose text is the extracted record rendered as ``label: value``
    lines. It exists because a question phrased in the schema's vocabulary ("what is the
    total due") may share no words with the page that produced the value ("BALANCE
    PAYABLE"), and the digest is written in the schema's vocabulary by construction.

    It has no page and no word span. A citation to it resolves through the underlying field
    value's own provenance instead, which is what keeps "every citation lights up on a page"
    true for structured facts as well as quoted ones.
    """
    lines = [f"{label}: {value}" for label, value in values if value]
    if not lines:
        return None
    return Chunk(
        ordinal=ordinal,
        text=f"Extracted fields for {filename}:\n" + "\n".join(lines),
        page_index=None,
        word_start=None,
        word_end=None,
        is_digest=True,
    )
