"""Content sniffing. The security requirement is that extension never decides."""

from __future__ import annotations

import io
import zipfile

import pytest
from app.domain.document import SourceFormat
from app.errors import UnsupportedFileType
from app.pipeline.sniff import sniff

from tests.fixtures.documents import (
    CSV_STATEMENT,
    PROSE_TXT,
    TXT_RECEIPT,
    docx_invoice,
    png_receipt,
    xlsx_ledger,
)
from tests.fixtures.pdfs import invoice_like_pdf


@pytest.mark.parametrize(
    ("data_factory", "filename", "expected"),
    [
        (invoice_like_pdf, "invoice.pdf", SourceFormat.PDF),
        (docx_invoice, "invoice.docx", SourceFormat.DOCX),
        (xlsx_ledger, "ledger.xlsx", SourceFormat.XLSX),
        (png_receipt, "receipt.png", SourceFormat.IMAGE),
        (lambda: CSV_STATEMENT, "statement.csv", SourceFormat.CSV),
        (lambda: TXT_RECEIPT, "receipt.txt", SourceFormat.TEXT),
    ],
)
def test_every_supported_format_is_identified(
    data_factory: object, filename: str, expected: SourceFormat
) -> None:
    result = sniff(data_factory(), filename)  # type: ignore[operator]
    assert result.source_format is expected
    assert not result.extension_disagreed


def test_content_wins_over_a_lying_extension() -> None:
    """The security property: a PDF named .txt is still parsed as a PDF, and vice versa."""
    result = sniff(invoice_like_pdf(), "totally_a_text_file.txt")
    assert result.source_format is SourceFormat.PDF
    assert result.extension_disagreed
    assert result.note is not None and "pdf" in result.note


def test_an_executable_is_rejected_however_it_is_named() -> None:
    executable = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 512
    with pytest.raises(UnsupportedFileType) as raised:
        sniff(executable, "invoice.pdf")
    # The message must tell the user what IS supported, per requirement FR-03.
    assert "pdf" in raised.value.detail["supported"]


def test_a_plain_archive_is_rejected_but_an_office_archive_is_not() -> None:
    """Both are zip files. Only the Office ones are supported."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "nothing useful")
    with pytest.raises(UnsupportedFileType):
        sniff(buffer.getvalue(), "archive.zip")

    assert sniff(docx_invoice(), "x.docx").source_format is SourceFormat.DOCX
    assert sniff(xlsx_ledger(), "x.xlsx").source_format is SourceFormat.XLSX


def test_prose_with_commas_is_not_mistaken_for_a_spreadsheet() -> None:
    """A comma is not a delimiter. Structural consistency is the test."""
    assert sniff(PROSE_TXT, "notes.txt").source_format is SourceFormat.TEXT


def test_tab_separated_data_is_recognised_as_tabular_despite_the_name() -> None:
    """A spreadsheet export saved as .txt still has columns, so it is read as tabular."""
    tabular = b"vendor\tamount\tdate\nAcme\t100\t2026-01-01\nBeta\t50\t2026-02-02\n"
    assert sniff(tabular, "export.txt").source_format is SourceFormat.CSV


def test_a_csv_named_file_with_no_columns_falls_back_to_text_rather_than_failing() -> None:
    """Deliberate kindness: a misnamed prose file is read, not rejected.

    Rejecting would buy no safety, because routing already happens by content, and would
    fail a real and common user mistake for nothing. See the module docstring for sniff.
    """
    result = sniff(PROSE_TXT, "notes.csv")
    assert result.source_format is SourceFormat.TEXT
    assert result.extension_disagreed


def test_a_single_line_of_text_is_not_tabular() -> None:
    """One line cannot establish a consistent column count."""
    assert sniff(b"vendor,amount\n", "x.txt").source_format is SourceFormat.TEXT


def test_utf16_text_is_decoded() -> None:
    """Windows exports are frequently UTF-16, and must not read as binary."""
    data = "Invoice total is 40 pounds.\nThank you.\n".encode("utf-16")
    assert sniff(data, "note.txt").source_format is SourceFormat.TEXT
