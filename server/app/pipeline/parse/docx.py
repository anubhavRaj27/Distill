"""Word document parsing.

Paragraphs and table rows become lines, in document order, and are laid out onto rendered
pages by ``app.pipeline.parse.render``. So a DOCX value gets a real highlight box like every
other format, and its ``locator`` still says "paragraph 12" (decision D18).

Document order matters and is not what ``python-docx`` gives by default: ``paragraphs`` and
``tables`` are separate collections, so reading them in sequence would place every table
after every paragraph regardless of where it actually appeared. The body's XML children are
walked instead, which preserves the order a reader would see.
"""

from __future__ import annotations

import io

from docx import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.config import Settings
from app.domain.document import ParsedDocument, SourceFormat
from app.errors import ParseFailed
from app.logging import get_logger
from app.pipeline.parse.pdf import ProgressCallback
from app.pipeline.parse.render import RenderLine, render_pages

logger = get_logger(__name__)


def _body_lines(document: DocxDocument) -> list[RenderLine]:
    lines: list[RenderLine] = []
    paragraph_number = 0
    table_number = 0

    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]

        if tag == "p":
            paragraph_number += 1
            text = Paragraph(child, document).text.strip()
            if text:
                lines.append(RenderLine(text, f"paragraph {paragraph_number}"))

        elif tag == "tbl":
            table_number += 1
            table = Table(child, document)
            for row_number, row in enumerate(table.rows, start=1):
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    lines.append(
                        RenderLine(
                            " | ".join(cells),
                            f"table {table_number}, row {row_number}",
                        )
                    )

    return lines


def parse(
    data: bytes, settings: Settings, on_progress: ProgressCallback | None = None
) -> tuple[ParsedDocument, list[bytes]]:
    report = on_progress or (lambda _detail: None)
    report("reading document text")

    try:
        document = DocxDocument(io.BytesIO(data))
    except Exception as exc:
        raise ParseFailed(
            "We could not read this Word document. It may be corrupt, or saved in the "
            "older .doc format, which Sift does not support.",
            library_error=type(exc).__name__,
        ) from exc

    lines = _body_lines(document)
    if not lines:
        raise ParseFailed("This Word document appears to be empty.")

    report("laying out pages")
    rendered = render_pages(lines, dpi=settings.page_render_dpi)

    parsed = ParsedDocument(
        source_format=SourceFormat.DOCX, pages=[page for page, _png in rendered]
    )
    logger.info("docx.parsed", pages=parsed.page_count, words=parsed.total_words)
    return parsed, [png for _page, png in rendered]
