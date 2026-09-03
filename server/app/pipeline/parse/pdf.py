"""PDF parsing: word geometry from pdfplumber, page images from pypdfium2.

The coordinate convention is pdfplumber's own, verified against a real fixture in
``tests/unit/test_pdf_geometry.py`` (decision D17), so word boxes are used as reported with
no transform. That test is what makes this module's ``BBox`` construction safe to read at a
glance rather than something to re-derive.

Pages with no text layer go through text recognition on the rendered image. The threshold is
configurable and defaults to five words, per implementation.md section 6.1: a scanned page
usually yields zero, and a handful of words is the signature of a page that is mostly an
image with a caption.
"""

from __future__ import annotations

import io
from collections.abc import Callable

import pdfplumber
import pypdfium2

from app.config import Settings
from app.domain.document import Line, ParsedDocument, ParsedPage, SourceFormat, Word
from app.domain.geometry import BBox
from app.errors import ParseFailed
from app.logging import get_logger
from app.pipeline.parse import ocr

logger = get_logger(__name__)

ProgressCallback = Callable[[str], None]
"""Called with a user-facing stage description, such as "scanned page detected, running
text recognition". This is what the progress list shows, so the wording is the user
experience for requirement 3.6."""


def _words_from_page(page: pdfplumber.page.Page) -> list[Word]:
    words: list[Word] = []
    for raw in page.extract_words(use_text_flow=False, keep_blank_chars=False):
        try:
            box = BBox(
                x0=float(raw["x0"]),
                top=float(raw["top"]),
                x1=float(raw["x1"]),
                bottom=float(raw["bottom"]),
            )
        except (KeyError, ValueError):
            continue
        text = str(raw.get("text", "")).strip()
        if text:
            words.append(Word(text=text, box=box))
    return words


def _lines_from_page(page: pdfplumber.page.Page) -> list[Line]:
    """Visual lines, using pdfplumber's own line grouping.

    Preferred over grouping words by vertical position ourselves: pdfplumber already
    accounts for varying font sizes and superscripts within a line, and reimplementing that
    would be a source of subtle differences between what we think a line is and what the
    document looks like.
    """
    lines: list[Line] = []
    try:
        extracted = page.extract_text_lines(layout=False)
    except Exception as exc:  # pragma: no cover - defensive, malformed content streams
        logger.info("pdf.line_extraction_failed", error=type(exc).__name__, detail=str(exc)[:120])
        return lines

    for raw in extracted:
        text = str(raw.get("text", "")).strip()
        if not text:
            continue
        try:
            box = BBox(
                x0=float(raw["x0"]),
                top=float(raw["top"]),
                x1=float(raw["x1"]),
                bottom=float(raw["bottom"]),
            )
        except (KeyError, ValueError):
            continue
        lines.append(Line(index=len(lines), text=text, box=box))
    return lines


def _render_page(document: pypdfium2.PdfDocument, index: int, dpi: int) -> tuple[bytes, float]:
    """Render one page to PNG. Returns the bytes and the pixels-per-point scale."""
    scale = dpi / 72.0
    image = document[index].render(scale=scale).to_pil()
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "PNG", optimize=True)
    return buffer.getvalue(), scale


def parse(
    data: bytes, settings: Settings, on_progress: ProgressCallback | None = None
) -> tuple[ParsedDocument, list[bytes]]:
    """Parse a PDF. Returns the normalised document and one PNG per page.

    Raises ``ParseFailed`` with a message written for the user. The wording matters: it is
    what appears next to the failed row in the interface, and requirement 3.6 asks for
    something specific and actionable rather than a library error.
    """
    report = on_progress or (lambda _detail: None)

    try:
        plumber = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:
        raise _readable_failure(exc) from exc

    try:
        pdfium = pypdfium2.PdfDocument(io.BytesIO(data))
    except Exception as exc:
        plumber.close()
        raise _readable_failure(exc) from exc

    ocr.configure(settings.tesseract_cmd)
    ocr_ready: bool | None = None

    pages: list[ParsedPage] = []
    images: list[bytes] = []

    try:
        total = len(plumber.pages)
        if total == 0:
            raise ParseFailed("This PDF has no pages.")

        for index, plumber_page in enumerate(plumber.pages):
            report(f"reading page {index + 1} of {total}")

            words = _words_from_page(plumber_page)
            lines = _lines_from_page(plumber_page)
            png, scale = _render_page(pdfium, index, settings.page_render_dpi)
            ocr_applied = False

            if len(words) < settings.ocr_min_words_per_page:
                if not settings.ocr_enabled:
                    report(f"page {index + 1} has no text layer and text recognition is off")
                else:
                    if ocr_ready is None:
                        ocr_ready = ocr.available()
                    if not ocr_ready:
                        report(
                            f"page {index + 1} looks scanned, but text recognition is "
                            f"not available on this server"
                        )
                    else:
                        report(
                            f"scanned page detected ({index + 1} of {total}), "
                            f"running text recognition"
                        )
                        from PIL import Image

                        recognised = ocr.recognise(
                            Image.open(io.BytesIO(png)), scale=scale
                        )
                        if recognised.words:
                            words = recognised.words
                            lines = recognised.lines
                            ocr_applied = True

            pages.append(
                ParsedPage(
                    index=index,
                    width_pt=float(plumber_page.width),
                    height_pt=float(plumber_page.height),
                    words=words,
                    lines=lines,
                    ocr_applied=ocr_applied,
                )
            )
            images.append(png)
    finally:
        plumber.close()

    parsed = ParsedDocument(source_format=SourceFormat.PDF, pages=pages)
    if not parsed.has_text:
        raise ParseFailed(
            "We could not find any text in this PDF, even after running text recognition. "
            "If it is a photograph or a handwritten document, Sift cannot read it yet."
        )

    logger.info(
        "pdf.parsed",
        pages=len(pages),
        words=parsed.total_words,
        ocr_pages=sum(1 for page in pages if page.ocr_applied),
    )
    return parsed, images


def _describe_exception_chain(exc: BaseException) -> str:
    """A lowercase searchable string covering the whole exception chain.

    Type names are included, and that is the point rather than a nicety. pdfplumber wraps
    a password failure as ``PdfminerException`` whose message is the EMPTY STRING, with
    ``pdfminer.pdfdocument.PDFPasswordIncorrect`` as its cause, whose message is also
    empty. Matching on ``str(exc)`` alone therefore misses the single most common
    unreadable-PDF case entirely, which requirement 3.6 names by name. The only usable
    signal is the class name, so the class names go in.
    """
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(type(current).__module__)
        parts.append(type(current).__name__)
        parts.append(str(current))
        parts.append(repr(getattr(current, "args", ())))
        following = current.__cause__ or current.__context__
        current = following
    return " ".join(parts).lower()


def _readable_failure(exc: Exception) -> ParseFailed:
    """Turn a library exception into something a person can act on.

    Requirement 3.6 names the password-protected case specifically, because it is common
    and because the fix is entirely in the user's hands: a message saying "remove the
    password and upload it again" is actionable, and "PdfiumError: 4" is not.
    """
    text = _describe_exception_chain(exc)
    if "password" in text or "encrypt" in text or "decrypt" in text:
        return ParseFailed(
            "We could not read this file: it appears to be password protected. "
            "Remove the password and upload it again."
        )
    if "eof" in text or "damaged" in text or "startxref" in text or "corrupt" in text:
        return ParseFailed(
            "We could not read this file: it looks damaged or incomplete. "
            "Try re-exporting or re-downloading it."
        )
    return ParseFailed(
        "We could not read this file as a PDF. It may be corrupt or use an unusual format.",
        library_error=type(exc).__name__,
    )
