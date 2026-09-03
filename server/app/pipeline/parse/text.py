"""Plain text parsing. Lines are laid out onto rendered pages, one line per line."""

from __future__ import annotations

from app.config import Settings
from app.domain.document import ParsedDocument, SourceFormat
from app.errors import ParseFailed
from app.logging import get_logger
from app.pipeline.parse.pdf import ProgressCallback
from app.pipeline.parse.render import RenderLine, render_pages

logger = get_logger(__name__)

MAX_LINES = 20_000


def parse(
    data: bytes, settings: Settings, on_progress: ProgressCallback | None = None
) -> tuple[ParsedDocument, list[bytes]]:
    report = on_progress or (lambda _detail: None)
    report("reading text")

    text: str | None = None
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise ParseFailed("We could not read the text encoding of this file.")

    raw_lines = text.splitlines()[:MAX_LINES]
    # Line numbers come from the ORIGINAL file, before blank lines are dropped, so a
    # locator of "line 12" matches what the user sees in their own editor.
    lines = [
        RenderLine(line.rstrip(), f"line {number}")
        for number, line in enumerate(raw_lines, start=1)
        if line.strip()
    ]
    if not lines:
        raise ParseFailed("This file is empty.")

    report("laying out pages")
    rendered = render_pages(lines, dpi=settings.page_render_dpi)
    parsed = ParsedDocument(
        source_format=SourceFormat.TEXT, pages=[page for page, _png in rendered]
    )
    logger.info("text.parsed", lines=len(lines), pages=parsed.page_count)
    return parsed, [png for _page, png in rendered]
