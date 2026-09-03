"""Grounding: from a model's quoted evidence back to the pixels it came from.

This module is the load-bearing part of the trust story. Requirement FR-30 promises that
every value on screen traces to a highlighted region of its source in one click, and this is
where that region is computed.

It is also the strongest hallucination detector in the system, and that is not a side
effect. A value a model invented has no quote to find. So a grounding failure is not merely
a missing highlight, it is evidence about the value itself, which is why a failure caps the
confidence tier at low (decision D5) rather than being logged and forgotten.

HOW IT WORKS
------------
The implementation document proposed a sliding fuzzy window over the page's word sequence.
This uses ``rapidfuzz.fuzz.partial_ratio_alignment`` instead, which returns the best-matching
character range directly. Better on both counts that matter: the matched span is exact
rather than rounded to a window size, and there is one call instead of a loop over window
positions and sizes.

The page is normalised into a single string with a character-offset-to-word map, so the
character range the alignment reports converts back into a set of ``Word`` objects, and from
there into boxes.

NORMALISATION
-------------
Both sides are folded before comparison: lowercased, currency symbols removed, thousands
separators removed, whitespace collapsed. That is what lets a model's ``$12,480.50`` match a
document's ``12,480.50`` or ``12480.50``, which is the single most common near-miss in
financial documents, and what stops a formatting difference from reading as a hallucination.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.domain.document import ParsedPage, Word
from app.domain.geometry import BBox, group_into_lines
from app.domain.provenance import GroundingFailure, Provenance
from app.logging import get_logger

logger = get_logger(__name__)

_CURRENCY_SYMBOLS = re.compile(r"[$€£¥₹₩]")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_PUNCTUATION_EDGES = re.compile(r"^[^\w\d]+|[^\w\d%]+$")
_WHITESPACE = re.compile(r"\s+")

MAX_PAGE_DISTANCE = 1
"""How far either side of the cited page to look. Models are routinely off by one at a page
break, which implementation.md section 6.3 calls out, and being wrong about which page a
value is on is a much smaller error than not finding it at all."""


def normalise_token(text: str) -> str:
    """Fold one word for comparison. May return an empty string, meaning "ignore this"."""
    folded = _CURRENCY_SYMBOLS.sub("", text.lower())
    folded = _THOUSANDS.sub("", folded)
    folded = _PUNCTUATION_EDGES.sub("", folded)
    return folded.strip()


def normalise_quote(quote: str) -> str:
    """Fold a whole quote into the same space as a normalised page."""
    tokens = [normalise_token(token) for token in _WHITESPACE.split(quote.strip())]
    return " ".join(token for token in tokens if token)


@dataclass
class NormalisedPage:
    """A page folded into one comparable string, with the map back to its words."""

    text: str = ""
    spans: list[tuple[int, int, Word]] = field(default_factory=list)
    """``(character_start, character_end, word)``, in reading order."""

    def words_in_range(self, start: int, end: int) -> list[Word]:
        """Every word whose characters overlap ``[start, end)``."""
        return [
            word
            for span_start, span_end, word in self.spans
            if span_start < end and start < span_end
        ]


def normalise_page(page: ParsedPage) -> NormalisedPage:
    """Fold ``page`` for matching. Words that normalise away are skipped entirely."""
    result = NormalisedPage()
    pieces: list[str] = []
    cursor = 0
    for word in page.words:
        token = normalise_token(word.text)
        if not token:
            continue
        if pieces:
            cursor += 1  # the joining space
        pieces.append(token)
        result.spans.append((cursor, cursor + len(token), word))
        cursor += len(token)
    result.text = " ".join(pieces)
    return result


@dataclass
class Match:
    """A located quote."""

    page_index: int
    score: float
    boxes: list[BBox]
    matched_text: str


def _match_on_page(
    quote_normalised: str, page: ParsedPage, cache: dict[int, NormalisedPage]
) -> Match | None:
    normalised = cache.get(page.index)
    if normalised is None:
        normalised = normalise_page(page)
        cache[page.index] = normalised

    if not normalised.text or not quote_normalised:
        return None

    alignment = fuzz.partial_ratio_alignment(quote_normalised, normalised.text)
    if alignment is None:  # pragma: no cover - only for empty inputs, guarded above
        return None

    # Clamp defensively. When the quote is longer than the page text, the library treats
    # the shorter string as the needle, and the reported range can then exceed the page
    # string's bounds. Clamping keeps the word lookup correct instead of silently empty.
    start = max(0, min(alignment.dest_start, len(normalised.text)))
    end = max(start, min(alignment.dest_end, len(normalised.text)))

    matched_words = normalised.words_in_range(start, end)
    if not matched_words:
        return None

    return Match(
        page_index=page.index,
        score=float(alignment.score),
        # One box per visual line, never one box spanning several. A quote that wraps must
        # not highlight the unrelated content sitting between its fragments (FR-30).
        boxes=group_into_lines([word.box for word in matched_words]),
        matched_text=normalised.text[start:end],
    )


def _pages_to_try(cited: int, pages: list[ParsedPage]) -> list[ParsedPage]:
    """Search order: the cited page, then its neighbours, then everything else.

    Ordered rather than exhaustive-then-best because the cited page is by far the most
    likely and because a value that also appears on another page (a total repeated in a
    footer) should be highlighted where the model said it saw it.
    """
    by_index = {page.index: page for page in pages}
    order: list[ParsedPage] = []
    seen: set[int] = set()

    for candidate in [cited, *range(cited - MAX_PAGE_DISTANCE, cited + MAX_PAGE_DISTANCE + 1)]:
        page = by_index.get(candidate)
        if page is not None and candidate not in seen:
            seen.add(candidate)
            order.append(page)

    for page in pages:
        if page.index not in seen:
            order.append(page)
    return order


def ground(
    *,
    quote: str | None,
    page_index: int,
    pages: list[ParsedPage],
    reasoning: str = "",
    min_score: float = 85.0,
) -> Provenance:
    """Locate ``quote`` in ``pages`` and return provenance for it.

    Always returns a ``Provenance``, never raises. An unlocated quote is a fully described
    state, not an error: the value, the model's justification, and the reason we could not
    corroborate it are all still reported, which is what lets the interface tell the user
    the truth rather than showing an empty highlight.
    """
    if not quote or not quote.strip():
        return Provenance(
            page_index=page_index if any(page.index == page_index for page in pages) else None,
            quote=quote,
            reasoning=reasoning,
            failure=GroundingFailure.NO_QUOTE,
        )

    if not pages or not any(page.words for page in pages):
        return Provenance(
            page_index=None,
            quote=quote,
            reasoning=reasoning,
            failure=GroundingFailure.NO_TEXT_LAYER,
        )

    cited_exists = any(page.index == page_index for page in pages)
    quote_normalised = normalise_quote(quote)

    cache: dict[int, NormalisedPage] = {}
    best: Match | None = None

    for page in _pages_to_try(page_index, pages):
        match = _match_on_page(quote_normalised, page, cache)
        if match is None:
            continue
        if best is None or match.score > best.score:
            best = match
        if best.score >= 99.5:
            break  # an exact match will not be improved on

    if best is None or best.score < min_score:
        logger.info(
            "ground.not_found",
            cited_page=page_index,
            best_score=round(best.score, 1) if best else None,
            quote=quote[:80],
        )
        return Provenance(
            page_index=page_index if cited_exists else None,
            quote=quote,
            reasoning=reasoning,
            match_score=round(best.score, 1) if best else None,
            failure=(
                GroundingFailure.PAGE_OUT_OF_RANGE
                if not cited_exists
                else GroundingFailure.QUOTE_NOT_FOUND
            ),
        )

    page = next(candidate for candidate in pages if candidate.index == best.page_index)
    locator = page.locator or next(
        (
            line.locator
            for line in page.lines
            if line.locator and line.box.vertically_overlaps(best.boxes[0], tolerance=1.0)
        ),
        None,
    )

    if best.page_index != page_index:
        logger.info(
            "ground.found_on_different_page",
            cited_page=page_index,
            found_page=best.page_index,
            score=round(best.score, 1),
        )

    return Provenance(
        page_index=best.page_index,
        boxes=best.boxes,
        quote=quote,
        reasoning=reasoning,
        match_score=round(best.score, 1),
        locator=locator,
    )
