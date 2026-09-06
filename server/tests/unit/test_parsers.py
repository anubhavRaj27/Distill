"""The parsers, and the contract they all share.

The point of this file is the parametrised contract test: every format, whatever it is,
produces the same shape with geometry in the same coordinate space. That contract is what
lets extraction, grounding, and scoring know nothing about file formats, so it is worth
asserting once over all of them rather than separately per parser.
"""

from __future__ import annotations

import io

import pytest
from app.config import Settings
from app.domain.document import ParsedDocument, SourceFormat
from app.errors import ParseFailed
from app.pipeline.parse.router import parse
from PIL import Image

from tests.fixtures.documents import (
    CSV_STATEMENT,
    TXT_RECEIPT,
    docx_invoice,
    png_receipt,
    xlsx_ledger,
)
from tests.fixtures.pdfs import blank_pdf, invoice_like_pdf, password_protected_pdf


@pytest.fixture(scope="module")
def parse_settings() -> Settings:
    return Settings(llm_provider="fake")


ALL_FORMATS = [
    pytest.param(invoice_like_pdf, SourceFormat.PDF, id="pdf"),
    pytest.param(docx_invoice, SourceFormat.DOCX, id="docx"),
    pytest.param(xlsx_ledger, SourceFormat.XLSX, id="xlsx"),
    pytest.param(lambda: CSV_STATEMENT, SourceFormat.CSV, id="csv"),
    pytest.param(lambda: TXT_RECEIPT, SourceFormat.TEXT, id="txt"),
    pytest.param(png_receipt, SourceFormat.IMAGE, id="png"),
]


# ---------------------------------------------------------------------------
# The shared contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("factory", "source_format"), ALL_FORMATS)
def test_every_parser_produces_pages_words_and_an_image_per_page(
    factory: object, source_format: SourceFormat, parse_settings: Settings
) -> None:
    document, images = parse(factory(), source_format, parse_settings)  # type: ignore[operator]
    assert document.source_format is source_format
    assert document.page_count >= 1
    assert len(images) == document.page_count, "one image per page, always"
    assert document.has_text


@pytest.mark.parametrize(("factory", "source_format"), ALL_FORMATS)
def test_every_word_box_is_inside_its_page(
    factory: object, source_format: SourceFormat, parse_settings: Settings
) -> None:
    """The single coordinate convention, asserted for every format. Decision D14."""
    document, _images = parse(factory(), source_format, parse_settings)  # type: ignore[operator]
    for page in document.pages:
        for word in page.words:
            assert 0 <= word.box.x0 < word.box.x1 <= page.width_pt + 0.5
            assert 0 <= word.box.top < word.box.bottom <= page.height_pt + 0.5


@pytest.mark.parametrize(("factory", "source_format"), ALL_FORMATS)
def test_the_rendered_image_relates_to_the_page_by_a_single_uniform_scale(
    factory: object, source_format: SourceFormat, parse_settings: Settings
) -> None:
    """What lets the viewer compute one scale factor and trust it for both axes."""
    document, images = parse(factory(), source_format, parse_settings)  # type: ignore[operator]
    for page, png in zip(document.pages, images, strict=True):
        image = Image.open(io.BytesIO(png))
        horizontal = image.width / page.width_pt
        vertical = image.height / page.height_pt
        assert horizontal == pytest.approx(vertical, rel=0.01), (
            "non-uniform scale would need two factors in the overlay maths"
        )


@pytest.mark.parametrize(("factory", "source_format"), ALL_FORMATS)
def test_page_indices_are_contiguous_from_zero(
    factory: object, source_format: SourceFormat, parse_settings: Settings
) -> None:
    document, _images = parse(factory(), source_format, parse_settings)  # type: ignore[operator]
    assert [page.index for page in document.pages] == list(range(document.page_count))


# ---------------------------------------------------------------------------
# Per-format behaviour worth asserting on its own
# ---------------------------------------------------------------------------


def test_pdf_extracts_real_text_and_keeps_pages_separate(parse_settings: Settings) -> None:
    document, _images = parse(invoice_like_pdf(), SourceFormat.PDF, parse_settings)
    assert document.page_count == 2
    first = document.pages[0].text
    assert "Northwind Traders" in first
    assert "12,480.50" in first
    # The purchase order number is on page two, and must not leak into page one, or a
    # model citing page one for it would be wrongly treated as correct.
    assert "PO-99814" not in first
    assert "PO-99814" in document.pages[1].text


def test_a_scanned_pdf_routes_through_text_recognition(parse_settings: Settings) -> None:
    """A page with no text layer must be reported to the user, then fail specifically."""
    stages: list[str] = []
    with pytest.raises(ParseFailed) as raised:
        parse(blank_pdf(), SourceFormat.PDF, parse_settings, stages.append)
    assert any("text recognition" in stage for stage in stages)
    assert "text recognition" in str(raised.value)


def test_a_password_protected_pdf_says_so_specifically(parse_settings: Settings) -> None:
    """Requirement 3.6 names this case, because the fix is entirely in the user's hands.

    This test earns its place. Both libraries report an encrypted PDF with an EMPTY
    message, and the only usable signal is the exception class name, so the obvious
    implementation (match "password" in ``str(exc)``) silently produces the generic
    "may be corrupt" message and sends the user looking for a problem that is not there.
    """
    with pytest.raises(ParseFailed) as raised:
        parse(password_protected_pdf(), SourceFormat.PDF, parse_settings)
    message = str(raised.value)
    assert "password protected" in message
    assert "upload it again" in message, "the message must say what to do next"


def test_corrupt_bytes_produce_a_readable_message_not_a_stack_trace(
    parse_settings: Settings,
) -> None:
    with pytest.raises(ParseFailed) as raised:
        parse(b"%PDF-1.4 then nothing but noise" + b"\x00" * 200, SourceFormat.PDF, parse_settings)
    message = str(raised.value)
    assert "PdfiumError" not in message
    assert "Traceback" not in message
    assert message[0].isupper() and message.endswith(".")


def test_docx_preserves_paragraph_locators(parse_settings: Settings) -> None:
    document, _images = parse(docx_invoice(), SourceFormat.DOCX, parse_settings)
    locators = [line.locator for page in document.pages for line in page.lines]
    assert any(locator and locator.startswith("paragraph") for locator in locators)
    assert "Contoso Supplies" in document.pages[0].text


def test_xlsx_makes_one_page_group_per_sheet_with_cell_addresses(
    parse_settings: Settings,
) -> None:
    document, _images = parse(xlsx_ledger(), SourceFormat.XLSX, parse_settings)
    sheet_names = {page.locator for page in document.pages}
    assert sheet_names == {"Invoices", "Notes"}
    locators = [line.locator for page in document.pages for line in page.lines]
    assert "Invoices!row 2" in locators


def test_xlsx_dates_and_whole_numbers_are_rendered_as_a_person_writes_them(
    parse_settings: Settings,
) -> None:
    """The rendered page is both what the model reads and what the user sees highlighted."""
    document, _images = parse(xlsx_ledger(), SourceFormat.XLSX, parse_settings)
    text = "\n".join(page.text for page in document.pages)
    assert "2026-01-15" in text
    assert "1250.75" in text
    assert "00:00:00" not in text, "a date must not render with a time component"


def test_csv_rows_become_lines_with_row_numbers(parse_settings: Settings) -> None:
    document, _images = parse(CSV_STATEMENT, SourceFormat.CSV, parse_settings)
    locators = [line.locator for page in document.pages for line in page.lines]
    assert locators[0] == "Data!row 1"
    assert "ACME INDUSTRIAL" in document.pages[0].text


def test_text_line_numbers_match_the_original_file_including_blank_lines(
    parse_settings: Settings,
) -> None:
    """A locator of 'line 12' must match the user's own editor, so blanks still count."""
    document, _images = parse(TXT_RECEIPT, SourceFormat.TEXT, parse_settings)
    locators = [line.locator for page in document.pages for line in page.lines]
    # TXT_RECEIPT has a blank line 3, so the second non-blank line is line 2 and the
    # third is line 4.
    assert locators[:3] == ["line 1", "line 2", "line 4"]


def test_an_image_treats_one_pixel_as_one_point(parse_settings: Settings) -> None:
    document, images = parse(png_receipt(width=600, height=320), SourceFormat.IMAGE, parse_settings)
    page = document.pages[0]
    assert (page.width_pt, page.height_pt) == (600.0, 320.0)
    assert page.ocr_applied is True
    image = Image.open(io.BytesIO(images[0]))
    assert image.width / page.width_pt == pytest.approx(1.0)


def test_an_empty_text_file_fails_with_a_readable_message(parse_settings: Settings) -> None:
    with pytest.raises(ParseFailed) as raised:
        parse(b"   \n\n  \n", SourceFormat.TEXT, parse_settings)
    assert "empty" in str(raised.value).lower()


def test_progress_is_reported_for_the_user(parse_settings: Settings) -> None:
    """The progress list in the interface IS this callback, so it must be populated."""
    stages: list[str] = []
    parse(invoice_like_pdf(), SourceFormat.PDF, parse_settings, stages.append)
    assert stages
    assert all(stage and stage[0].islower() for stage in stages), (
        "stage text is shown mid-sentence in the interface, so it starts lowercase"
    )


def test_a_parsed_document_is_serialisable(parse_settings: Settings) -> None:
    """Pages are persisted as JSONB, so the whole shape must round-trip."""
    document, _images = parse(CSV_STATEMENT, SourceFormat.CSV, parse_settings)
    restored = ParsedDocument.model_validate(document.model_dump(mode="json"))
    assert restored.total_words == document.total_words
    assert restored.pages[0].words[0].box == document.pages[0].words[0].box
