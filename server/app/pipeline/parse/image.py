"""Image parsing: text recognition over the whole picture.

COORDINATE CHOICE
-----------------
An image has no notion of points, so Sift treats **one pixel as one point** for images:
``width_pt = image.width``. That keeps the single convention in ``app.domain.geometry``
intact (a box is always in page points, and the viewer's scale is always
``rendered_width_px / width_pt``) without inventing a dots-per-inch value the file does not
carry. A viewer showing the image at natural size gets a scale of exactly 1, and zooming
works through the same multiplication as every other format.
"""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

from app.config import Settings
from app.domain.document import ParsedDocument, ParsedPage, SourceFormat
from app.errors import ParseFailed
from app.logging import get_logger
from app.pipeline.parse import ocr
from app.pipeline.parse.pdf import ProgressCallback

logger = get_logger(__name__)

MAX_PIXELS = 40_000_000
"""Refuse absurd images before decoding them. A decompression bomb is a small file that
expands to gigabytes in memory, and the size limit on the upload does not catch it."""


def parse(
    data: bytes, settings: Settings, on_progress: ProgressCallback | None = None
) -> tuple[ParsedDocument, list[bytes]]:
    report = on_progress or (lambda _detail: None)

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except UnidentifiedImageError as exc:
        raise ParseFailed("We could not read this image file. It may be corrupt.") from exc
    except Image.DecompressionBombError as exc:
        raise ParseFailed(
            "This image is too large to process safely. Please reduce its dimensions."
        ) from exc
    except Exception as exc:
        raise ParseFailed(
            "We could not read this image file.", library_error=type(exc).__name__
        ) from exc

    if image.width * image.height > MAX_PIXELS:
        raise ParseFailed(
            f"This image is {image.width} by {image.height} pixels, which is too large to "
            f"process. Please reduce its dimensions and upload again."
        )

    rgb = image.convert("RGB")
    buffer = io.BytesIO()
    rgb.save(buffer, "PNG", optimize=True)
    png = buffer.getvalue()

    words: list = []
    lines: list = []
    ocr_applied = False

    if not settings.ocr_enabled:
        report("text recognition is turned off on this server")
    else:
        ocr.configure(settings.tesseract_cmd)
        if not ocr.available():
            report("text recognition is not available on this server")
        else:
            report("reading text from image")
            recognised = ocr.recognise(rgb, scale=1.0)
            words, lines = recognised.words, recognised.lines
            ocr_applied = bool(words)

    parsed = ParsedDocument(
        source_format=SourceFormat.IMAGE,
        pages=[
            ParsedPage(
                index=0,
                width_pt=float(rgb.width),
                height_pt=float(rgb.height),
                words=words,
                lines=lines,
                ocr_applied=ocr_applied,
            )
        ],
    )

    if not parsed.has_text:
        raise ParseFailed(
            "We could not find any readable text in this image. Sift reads typed text in "
            "scans and photographs, but not handwriting."
        )

    logger.info("image.parsed", words=parsed.total_words, size=f"{rgb.width}x{rgb.height}")
    return parsed, [png]
