"""Generated PDF fixtures with coordinates known in advance.

Fixtures are generated rather than committed as binaries so that the expected coordinates
live in code, next to the assertions that use them. A committed binary would leave the
reader trusting a magic number in a test.

reportlab draws in the PDF format's native space: origin bottom-left, y increasing UPWARD.
Distill's convention is top-left origin, y increasing downward (see ``app.domain.geometry``).
The conversion is therefore ``top = page_height - y_from_bottom``, and these helpers expose
both numbers so a test can assert the conversion rather than restate it.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

LETTER_WIDTH_PT, LETTER_HEIGHT_PT = letter  # 612.0 x 792.0


@dataclass(frozen=True)
class PlacedWord:
    """A word drawn at a known place, with both coordinate conventions recorded."""

    text: str
    x_left_pt: float
    baseline_from_bottom_pt: float
    font_size_pt: float

    @property
    def baseline_from_top_pt(self) -> float:
        return LETTER_HEIGHT_PT - self.baseline_from_bottom_pt


def single_word_pdf(
    text: str = "ANCHOR",
    x_left_pt: float = 100.0,
    baseline_from_bottom_pt: float = 700.0,
    font_size_pt: float = 24.0,
) -> tuple[bytes, PlacedWord]:
    """A one-page PDF containing exactly one word at a known position."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.setFont("Helvetica", font_size_pt)
    pdf.drawString(x_left_pt, baseline_from_bottom_pt, text)
    pdf.showPage()
    pdf.save()
    placed = PlacedWord(
        text=text,
        x_left_pt=x_left_pt,
        baseline_from_bottom_pt=baseline_from_bottom_pt,
        font_size_pt=font_size_pt,
    )
    return buffer.getvalue(), placed


def invoice_like_pdf() -> bytes:
    """A two-page document with invoice-shaped content, including a wrapped line.

    Used by grounding tests: it contains a quote that wraps, a currency amount with a
    thousands separator, and a value on page two that a model would plausibly cite as
    page one, which is the off-by-one case implementation.md section 6.3 calls out.
    """
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(72, 720, "INVOICE")
    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 690, "Supplier: Northwind Traders Pvt Ltd")
    pdf.drawString(72, 674, "Invoice Number: INV-2026-0042")
    pdf.drawString(72, 658, "Issue Date: 14 March 2026")
    pdf.drawString(72, 642, "Total Due: $12,480.50")
    # A description long enough to wrap, drawn as two lines, so a quote spanning both
    # must produce two highlight rectangles rather than one tall box.
    pdf.drawString(72, 610, "Description: annual platform subscription covering the")
    pdf.drawString(72, 596, "period April 2026 through March 2027, billed in advance.")
    pdf.showPage()

    pdf.setFont("Helvetica", 11)
    pdf.drawString(72, 720, "Purchase Order Number: PO-99814")
    pdf.drawString(72, 704, "Payment Terms: Net 30")
    pdf.showPage()

    pdf.save()
    return buffer.getvalue()


def password_protected_pdf() -> bytes:
    """An encrypted PDF, for the case requirement 3.6 names explicitly.

    Worth having as a real fixture rather than a mocked exception: the libraries report
    this failure in a surprising way (an empty message, with the only usable signal in the
    exception CLASS name), and a mock would have encoded the wrong assumption.
    """
    from reportlab.lib import pdfencrypt

    encryption = pdfencrypt.StandardEncryption(
        userPassword="user-secret", ownerPassword="owner-secret"
    )
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter, encrypt=encryption)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 700, "Confidential invoice")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def blank_pdf(pages: int = 1) -> bytes:
    """A PDF with no text at all, which must be routed down the OCR path."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    for _ in range(pages):
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
