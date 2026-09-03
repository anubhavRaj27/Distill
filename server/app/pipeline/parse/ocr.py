"""Optical Character Recognition for pages with no text layer.

Reached only when a page yields fewer than a configured number of words, which is the
signal that a page is a scan rather than a digital document (implementation.md 6.1).

Two things are worth stating plainly about this path.

**The word boxes are approximate.** Text recognition infers character positions from pixels,
so a highlight over a recognised word is close rather than exact. ``ParsedPage.ocr_applied``
records that this happened, and it is surfaced to the user, because a user comparing a
highlight against a scan deserves to know which highlights are estimates.

**A missing tesseract binary degrades rather than crashes.** The page is marked as having
no locatable text and processing continues. A deployment without the binary should produce a
clear message on affected documents, not a failed upload.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from app.domain.document import Line, Word
from app.domain.geometry import BBox
from app.logging import get_logger

logger = get_logger(__name__)

MIN_CONFIDENCE = 30.0
"""Recognition confidence below which a word is discarded. Tesseract emits speculative
low-confidence fragments on noisy scans, and a box around noise is worse than no box."""


class OcrUnavailable(RuntimeError):
    """The tesseract binary could not be found or run."""


@dataclass(frozen=True)
class OcrResult:
    words: list[Word]
    lines: list[Line]


def configure(tesseract_cmd: str | None) -> None:
    """Point pytesseract at an explicit binary, if one was configured."""
    if tesseract_cmd:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def available() -> bool:
    """Whether text recognition can actually run in this process."""
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception as exc:
        logger.info("ocr.unavailable", error=type(exc).__name__, detail=str(exc)[:200])
        return False
    return True


def recognise(image: Image.Image, *, scale: float) -> OcrResult:
    """Recognise text in ``image``, returning boxes in page POINTS.

    ``scale`` is pixels per point for the supplied image, so the caller controls the
    coordinate space and this function always returns the project's convention. Tesseract
    reports pixels, so dividing here is what keeps ``app.domain.geometry``'s promise that
    every box in the system is in the same units.
    """
    import pytesseract
    from pytesseract import Output

    try:
        data = pytesseract.image_to_data(image, output_type=Output.DICT)
    except Exception as exc:  # pragma: no cover - requires a broken tesseract install
        raise OcrUnavailable(str(exc)) from exc

    words: list[Word] = []
    # Tesseract groups words with block, paragraph, and line numbers. Grouping by that
    # triple reconstructs visual lines, which is what grounding needs in order to emit one
    # highlight rectangle per line of a wrapped quote.
    grouped: dict[tuple[int, int, int], list[Word]] = {}

    count = len(data.get("text", []))
    for index in range(count):
        text = str(data["text"][index]).strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1.0
        if confidence < MIN_CONFIDENCE:
            continue

        left = float(data["left"][index])
        top = float(data["top"][index])
        width = float(data["width"][index])
        height = float(data["height"][index])
        if width <= 0 or height <= 0:
            continue

        word = Word(
            text=text,
            box=BBox(
                x0=left / scale,
                top=top / scale,
                x1=(left + width) / scale,
                bottom=(top + height) / scale,
            ),
        )
        words.append(word)
        key = (
            int(data.get("block_num", [0] * count)[index]),
            int(data.get("par_num", [0] * count)[index]),
            int(data.get("line_num", [0] * count)[index]),
        )
        grouped.setdefault(key, []).append(word)

    lines: list[Line] = []
    for key in sorted(grouped, key=lambda group: min(w.box.top for w in grouped[group])):
        members = sorted(grouped[key], key=lambda word: word.box.x0)
        box = members[0].box
        for member in members[1:]:
            box = box.union(member.box)
        lines.append(
            Line(
                index=len(lines),
                text=" ".join(member.text for member in members),
                box=box,
            )
        )

    logger.info("ocr.completed", words=len(words), lines=len(lines))
    return OcrResult(words=words, lines=lines)
