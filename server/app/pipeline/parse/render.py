"""Rendering text onto pages we lay out ourselves, so we know where every word is.

This is the machinery behind decision D18. A DOCX file, a spreadsheet, and a text file have
no pages and no coordinates, so the implementation document proposed a different provenance
unit for each. Instead, Sift lays those formats out onto page-shaped sheets, records the
box of every word while doing so, and renders a matching image. Provenance is then a box
over a page for **every** format, and there is exactly one highlight implementation.

Why the measurement is exact rather than approximate: the boxes are computed with the same
font, at the same pixel size, at the same pixel positions that the renderer then draws at.
The layout is not predicted, it is recorded.

The font is Pillow's bundled default, obtained through ``ImageFont.load_default(size=...)``,
deliberately rather than a system font. A system font would make the layout depend on the
host, so a box measured on a development machine could be wrong in the container. The
bundled font makes the geometry identical everywhere, which is what lets the fixture tests
mean anything.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from app.domain.document import Line, ParsedPage, Word
from app.domain.geometry import BBox

_WORD = re.compile(r"\S+")


@dataclass(frozen=True)
class PageLayout:
    """A page of text, measured in points. Defaults are US Letter with generous margins."""

    width_pt: float = 612.0
    height_pt: float = 792.0
    margin_pt: float = 54.0
    font_size_pt: float = 10.0
    line_height_pt: float = 14.0

    @property
    def usable_width_pt(self) -> float:
        return self.width_pt - 2 * self.margin_pt

    @property
    def lines_per_page(self) -> int:
        usable = self.height_pt - 2 * self.margin_pt
        return max(1, int(usable // self.line_height_pt))


DEFAULT_LAYOUT = PageLayout()


@dataclass(frozen=True)
class RenderLine:
    """One line of text to place, with the address it came from.

    ``locator`` is what survives the format being normalised away, so a spreadsheet value
    can still tell the user "Invoices!row 3" and a Word value "paragraph 12".
    """

    text: str
    locator: str | None = None


@lru_cache(maxsize=16)
def _font(pixel_size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=pixel_size)


def _pixel_font_size(layout: PageLayout, scale: float) -> int:
    """Font size in pixels. Rounded once, here, so measurement and drawing agree."""
    return max(6, round(layout.font_size_pt * scale))


def measure_words(
    text: str, *, x0_px: float, top_px: float, font: ImageFont.FreeTypeFont, scale: float
) -> list[Word]:
    """Word boxes for one rendered line, converted from pixels back to points.

    Positions are measured by the width of the text PREFIX up to each word, rather than by
    summing word widths plus a space width. That is what makes runs of multiple spaces and
    any kerning between characters come out right, because it asks the font the same
    question the renderer will ask.
    """
    ascent, descent = font.getmetrics()
    words: list[Word] = []
    for match in _WORD.finditer(text):
        start_px = x0_px + font.getlength(text[: match.start()])
        end_px = x0_px + font.getlength(text[: match.end()])
        words.append(
            Word(
                text=match.group(0),
                box=BBox(
                    x0=start_px / scale,
                    top=top_px / scale,
                    x1=end_px / scale,
                    bottom=(top_px + ascent + descent) / scale,
                ),
            )
        )
    return words


def wrap(
    lines: list[RenderLine], layout: PageLayout = DEFAULT_LAYOUT, dpi: int = 144
) -> list[RenderLine]:
    """Break lines that are wider than the usable width, keeping each part's locator.

    Wrapping is done by measurement rather than by character count, because character
    counts are wrong for any font that is not monospaced, and a mis-wrapped line means a
    highlight box that does not contain the text it points at.
    """
    scale = dpi / 72.0
    font = _font(_pixel_font_size(layout, scale))
    limit_px = layout.usable_width_pt * scale

    wrapped: list[RenderLine] = []
    for line in lines:
        if not line.text.strip():
            wrapped.append(line)
            continue
        if font.getlength(line.text) <= limit_px:
            wrapped.append(line)
            continue

        current: list[str] = []
        for word in line.text.split():
            candidate = " ".join([*current, word])
            if current and font.getlength(candidate) > limit_px:
                wrapped.append(RenderLine(" ".join(current), line.locator))
                current = [word]
            else:
                current.append(word)
        if current:
            wrapped.append(RenderLine(" ".join(current), line.locator))
    return wrapped


def render_pages(
    lines: list[RenderLine],
    *,
    layout: PageLayout = DEFAULT_LAYOUT,
    dpi: int = 144,
    wrap_lines: bool = True,
) -> list[tuple[ParsedPage, bytes]]:
    """Lay ``lines`` onto pages and render each. Returns pages paired with PNG bytes.

    The returned ``ParsedPage`` carries word and line boxes in points, matching the
    rendered image exactly at ``scale = image_width / page.width_pt``.
    """
    if wrap_lines:
        lines = wrap(lines, layout, dpi)
    if not lines:
        lines = [RenderLine("")]

    scale = dpi / 72.0
    font = _font(_pixel_font_size(layout, scale))
    ascent, descent = font.getmetrics()

    image_width = round(layout.width_pt * scale)
    image_height = round(layout.height_pt * scale)
    margin_px = layout.margin_pt * scale
    line_height_px = layout.line_height_pt * scale

    per_page = layout.lines_per_page
    chunks = [lines[start : start + per_page] for start in range(0, len(lines), per_page)]

    rendered: list[tuple[ParsedPage, bytes]] = []
    for page_index, chunk in enumerate(chunks):
        image = Image.new("RGB", (image_width, image_height), "white")
        draw = ImageDraw.Draw(image)

        page_words: list[Word] = []
        page_lines: list[Line] = []

        for row, line in enumerate(chunk):
            top_px = margin_px + row * line_height_px
            # Drawn at exactly the position that was measured. Pillow's default "la" anchor
            # places the ascender top at this y, which is why the box bottom below is
            # top + ascent + descent.
            draw.text((margin_px, top_px), line.text, fill="black", font=font)

            words = measure_words(
                line.text, x0_px=margin_px, top_px=top_px, font=font, scale=scale
            )
            page_words.extend(words)

            line_box = BBox(
                x0=margin_px / scale,
                top=top_px / scale,
                x1=(margin_px + font.getlength(line.text)) / scale
                if line.text
                else margin_px / scale + 1.0,
                bottom=(top_px + ascent + descent) / scale,
            )
            page_lines.append(
                Line(
                    index=len(page_lines),
                    text=line.text,
                    box=line_box,
                    locator=line.locator,
                )
            )

        buffer = io.BytesIO()
        image.save(buffer, "PNG", optimize=True)

        rendered.append(
            (
                ParsedPage(
                    index=page_index,
                    width_pt=layout.width_pt,
                    height_pt=layout.height_pt,
                    words=page_words,
                    lines=page_lines,
                ),
                buffer.getvalue(),
            )
        )

    return rendered
