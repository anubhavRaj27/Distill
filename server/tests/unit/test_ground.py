"""Grounding. The trust story lives or dies here.

The cases below are the ones implementation.md section 6.3 names, plus the one that matters
most: a hallucinated value must NOT ground. That is the mechanism by which a value a model
invented gets caught and pushed into the low tier (decision D5), so a test suite that only
checked successful matches would be checking the easy half.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from app.domain.document import Line, ParsedPage, SourceFormat, Word
from app.domain.geometry import BBox
from app.domain.provenance import GroundingFailure
from app.pipeline.ground import ground, normalise_quote, normalise_token
from app.pipeline.parse.router import parse

from tests.fixtures.pdfs import invoice_like_pdf


@pytest.fixture(scope="module")
def invoice_pages() -> list[ParsedPage]:
    document, _images = parse(invoice_like_pdf(), SourceFormat.PDF, Settings(llm_provider="fake"))
    return document.pages


def _page(text: str, index: int = 0, locator: str | None = None) -> ParsedPage:
    """A synthetic page laying words out on one line, ten points wide each."""
    words = [
        Word(text=token, box=BBox(x0=10.0 + i * 30, top=100.0, x1=35.0 + i * 30, bottom=112.0))
        for i, token in enumerate(text.split())
    ]
    line = Line(index=0, text=text, box=BBox(x0=10.0, top=100.0, x1=600.0, bottom=112.0),
                locator=locator)
    return ParsedPage(
        index=index, width_pt=612.0, height_pt=792.0, words=words, lines=[line], locator=locator
    )


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Total", "total"),
        ("$12,480.50", "12480.50"),
        ("₹1,20,000", "1,20000"),
        ("(Vendor)", "vendor"),
        ("INV-2026-0042", "inv-2026-0042"),
        ("50%", "50%"),
        (":", ""),
        ("...", ""),
    ],
)
def test_token_normalisation(raw: str, expected: str) -> None:
    assert normalise_token(raw) == expected


def test_quote_normalisation_collapses_whitespace_and_drops_empty_tokens() -> None:
    assert normalise_quote("  Total   Due :  $12,480.50 ") == "total due 12480.50"


# ---------------------------------------------------------------------------
# The cases implementation.md section 6.3 names
# ---------------------------------------------------------------------------


def test_an_exact_quote_grounds_with_a_perfect_score(invoice_pages: list[ParsedPage]) -> None:
    provenance = ground(
        quote="Supplier: Northwind Traders Pvt Ltd", page_index=0, pages=invoice_pages
    )
    assert provenance.is_grounded
    assert provenance.match_score == pytest.approx(100.0)
    assert provenance.page_index == 0
    assert provenance.failure is None


@pytest.mark.parametrize(
    "quote",
    [
        "TOTAL DUE: $12,480.50",  # different casing
        "total due 12480.50",  # no symbol, no separator
        "Total  Due:   $12,480.50",  # different spacing
        "12,480.50",  # the value alone
    ],
)
def test_formatting_differences_still_ground(
    quote: str, invoice_pages: list[ParsedPage]
) -> None:
    """The most common near-miss in financial documents, and it must not read as a
    hallucination."""
    provenance = ground(quote=quote, page_index=0, pages=invoice_pages)
    assert provenance.is_grounded, f"{quote!r} should have grounded"
    assert provenance.match_score is not None and provenance.match_score >= 85


def test_a_hallucinated_value_does_not_ground(invoice_pages: list[ParsedPage]) -> None:
    """The point of the whole module. An invented value has no quote to find."""
    provenance = ground(
        quote="Supplier: Acme Corporation Limited", page_index=0, pages=invoice_pages
    )
    assert not provenance.is_grounded
    assert provenance.failure is GroundingFailure.QUOTE_NOT_FOUND
    assert provenance.boxes == []
    # The value and the model's justification survive, so the interface can still explain
    # itself rather than showing an empty cell.
    assert provenance.quote is not None


def test_an_off_by_one_page_citation_is_recovered_and_recorded(
    invoice_pages: list[ParsedPage],
) -> None:
    """Models are routinely off by one at a page break. Finding it on the neighbouring
    page is far better than reporting a hallucination, and the CORRECTED page must be
    returned or the viewer would open the wrong one."""
    provenance = ground(
        quote="Purchase Order Number: PO-99814", page_index=0, pages=invoice_pages
    )
    assert provenance.is_grounded
    assert provenance.page_index == 1, "the corrected page, not the cited one"


def test_a_quote_that_wraps_produces_one_box_per_line(
    invoice_pages: list[ParsedPage],
) -> None:
    """Requirement FR-30 asks for the EXACT region. One tall box spanning both fragments
    would highlight the unrelated content between them."""
    provenance = ground(
        quote="annual platform subscription covering the period April 2026 through March 2027",
        page_index=0,
        pages=invoice_pages,
    )
    assert provenance.is_grounded
    assert len(provenance.boxes) == 2, "two visual lines means two rectangles"
    first, second = provenance.boxes
    assert first.bottom <= second.top + 1.0, "boxes must be ordered top to bottom"


def test_a_page_index_beyond_the_document_still_searches_the_rest(
    invoice_pages: list[ParsedPage],
) -> None:
    provenance = ground(
        quote="Invoice Number: INV-2026-0042", page_index=99, pages=invoice_pages
    )
    assert provenance.is_grounded
    assert provenance.page_index == 0


def test_a_page_index_beyond_the_document_with_no_match_reports_the_page_problem() -> None:
    provenance = ground(quote="nothing like this text", page_index=42, pages=[_page("alpha beta")])
    assert not provenance.is_grounded
    assert provenance.failure is GroundingFailure.PAGE_OUT_OF_RANGE


def test_an_empty_quote_is_reported_as_missing_evidence() -> None:
    for quote in (None, "", "   "):
        provenance = ground(quote=quote, page_index=0, pages=[_page("alpha beta")])
        assert provenance.failure is GroundingFailure.NO_QUOTE


def test_a_document_with_no_text_layer_says_so() -> None:
    """Distinguished from 'quote not found' on purpose: the user's next action differs.

    No text layer means the document needs a better scan. Quote not found means the value
    is suspect.
    """
    empty = ParsedPage(index=0, width_pt=612, height_pt=792, words=[], lines=[])
    provenance = ground(quote="anything", page_index=0, pages=[empty])
    assert provenance.failure is GroundingFailure.NO_TEXT_LAYER


# ---------------------------------------------------------------------------
# Geometry of the result
# ---------------------------------------------------------------------------


def test_the_box_covers_the_matched_words_and_nothing_more() -> None:
    page = _page("alpha bravo charlie delta echo")
    provenance = ground(quote="charlie delta", page_index=0, pages=[page])
    assert provenance.is_grounded
    assert len(provenance.boxes) == 1
    box = provenance.boxes[0]

    charlie = next(word for word in page.words if word.text == "charlie")
    delta = next(word for word in page.words if word.text == "delta")
    alpha = next(word for word in page.words if word.text == "alpha")

    assert box.x0 == pytest.approx(charlie.box.x0)
    assert box.x1 == pytest.approx(delta.box.x1)
    assert box.x0 > alpha.box.x1, "the box must not reach back to unmatched words"


def test_boxes_stay_inside_the_page(invoice_pages: list[ParsedPage]) -> None:
    provenance = ground(quote="Total Due: $12,480.50", page_index=0, pages=invoice_pages)
    page = invoice_pages[provenance.page_index or 0]
    for box in provenance.boxes:
        assert 0 <= box.x0 < box.x1 <= page.width_pt
        assert 0 <= box.top < box.bottom <= page.height_pt


def test_a_locator_is_carried_through_for_formats_that_have_one() -> None:
    """A spreadsheet value must still be able to say 'Invoices!row 2'."""
    page = _page("Acme Industrial | AI-9001 | 1250.75", locator="Invoices!row 2")
    provenance = ground(quote="AI-9001", page_index=0, pages=[page])
    assert provenance.is_grounded
    assert provenance.locator == "Invoices!row 2"


def test_the_threshold_is_respected() -> None:
    """A caller raising the bar must actually get a stricter result."""
    page = _page("alpha bravo charlie")
    loose = ground(quote="alpha bravo charlei", page_index=0, pages=[page], min_score=50)
    strict = ground(quote="alpha bravo charlei", page_index=0, pages=[page], min_score=100)
    assert loose.is_grounded
    assert not strict.is_grounded


def test_a_quote_longer_than_the_page_does_not_crash() -> None:
    """The library treats the shorter string as the needle, so the reported range can
    exceed the page string's bounds and must be clamped."""
    page = _page("short")
    provenance = ground(quote="a very much longer quote " * 20, page_index=0, pages=[page])
    assert provenance.failure is not None or provenance.is_grounded


def test_grounding_never_raises() -> None:
    """Contract. A grounding failure is a described state, not an exception, because the
    pipeline must continue and report honestly rather than fail the document."""
    weird = [
        ParsedPage(index=0, width_pt=1, height_pt=1, words=[], lines=[]),
        _page("actual words here", index=1),
    ]
    for quote in (None, "", "\x00\x00", "🙂🙂🙂", "a" * 5000):
        ground(quote=quote, page_index=0, pages=weird)
        ground(quote=quote, page_index=-5, pages=weird)
        ground(quote=quote, page_index=0, pages=[])
