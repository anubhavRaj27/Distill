"""One entry point for parsing, dispatching on the sniffed format.

Everything downstream of here is format-agnostic: extraction, grounding, and scoring see a
``ParsedDocument`` and never learn what kind of file produced it. Adding a format is a new
module plus one line in the mapping below.
"""

from __future__ import annotations

from collections.abc import Callable

from app.config import Settings
from app.domain.document import ParsedDocument, SourceFormat
from app.errors import ParseFailed, UnsupportedFileType
from app.logging import get_logger
from app.pipeline.parse import docx, image, pdf, sheet, text
from app.pipeline.parse.pdf import ProgressCallback

logger = get_logger(__name__)

Parser = Callable[
    [bytes, Settings, ProgressCallback | None], tuple[ParsedDocument, list[bytes]]
]

_PARSERS: dict[SourceFormat, Parser] = {
    SourceFormat.PDF: pdf.parse,
    SourceFormat.IMAGE: image.parse,
    SourceFormat.DOCX: docx.parse,
    SourceFormat.XLSX: sheet.parse_xlsx,
    SourceFormat.CSV: sheet.parse_csv,
    SourceFormat.TEXT: text.parse,
}


def parse(
    data: bytes,
    source_format: SourceFormat,
    settings: Settings,
    on_progress: ProgressCallback | None = None,
) -> tuple[ParsedDocument, list[bytes]]:
    """Parse ``data`` as ``source_format``. Returns the document and one image per page."""
    parser = _PARSERS.get(source_format)
    if parser is None:  # pragma: no cover - unreachable while the mapping is complete
        raise UnsupportedFileType(f"Sift has no parser for {source_format.value}.")

    try:
        return parser(data, settings, on_progress)
    except (ParseFailed, UnsupportedFileType):
        raise
    except Exception as exc:
        # A parser raising something unexpected must still produce a message the user can
        # read, and must not take down the rest of the batch.
        logger.exception("parse.unexpected_failure", source_format=source_format.value)
        raise ParseFailed(
            "Something went wrong while reading this file. The rest of your documents were "
            "not affected.",
            library_error=type(exc).__name__,
        ) from exc
