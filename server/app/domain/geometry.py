"""Page geometry, and the one coordinate convention this project uses everywhere.

THE CONVENTION
--------------
Every bounding box in Distill, in the database, over the wire, and in the browser, is
expressed in **PDF points with a top-left origin and y increasing downward**:

    (x0, top, x1, bottom)      0 <= x0 < x1 <= page.width_pt
                               0 <= top < bottom <= page.height_pt

This is not an arbitrary choice, it is the convention pdfplumber already reports, so
adopting it means zero transforms anywhere in the pipeline. It was verified against a real
PDF rather than assumed. See decision D17 and ``tests/unit/test_pdf_geometry.py``, which
asserts it against a generated fixture with known coordinates.

Concretely, for a 612 x 792 point page with a glyph whose PDF-native (bottom-left origin)
extent is y0=695.03, y1=719.03, pdfplumber reports ``top=72.97`` and ``bottom=96.97``,
because ``top == page.height_pt - y1``. The raw ``y0``/``y1`` are never used downstream.

RENDERING
---------
A page rendered at ``dpi`` produces an image of exactly ``width_pt * dpi / 72`` pixels
(verified: 612 x 792 points at 144 dots per inch renders to 1224 x 1584 pixels, exactly).
So a viewer that has drawn the page at some pixel width converts a box to screen space with
a single uniform scale::

    scale = rendered_width_px / page.width_pt
    screen_box = box.scaled(scale)

This is also why the frontend needs no knowledge of dots per inch: it divides the width it
actually drew by the width in points that the interface gave it.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field, model_validator


class BBox(BaseModel):
    """An axis-aligned box in top-left-origin page points. See the module docstring."""

    model_config = {"frozen": True}

    x0: float = Field(description="Left edge, points from the left of the page.")
    top: float = Field(description="Top edge, points from the TOP of the page.")
    x1: float = Field(description="Right edge, points from the left of the page.")
    bottom: float = Field(description="Bottom edge, points from the TOP of the page.")

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.x1 < self.x0:
            raise ValueError(f"BBox x1 ({self.x1}) is left of x0 ({self.x0})")
        if self.bottom < self.top:
            raise ValueError(f"BBox bottom ({self.bottom}) is above top ({self.top})")
        return self

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top

    def union(self, other: BBox) -> BBox:
        """Smallest box containing both. Used to merge the word boxes of a matched quote."""
        return BBox(
            x0=min(self.x0, other.x0),
            top=min(self.top, other.top),
            x1=max(self.x1, other.x1),
            bottom=max(self.bottom, other.bottom),
        )

    def scaled(self, scale: float) -> BBox:
        """Uniformly scale, for converting points to rendered pixels."""
        return BBox(
            x0=self.x0 * scale,
            top=self.top * scale,
            x1=self.x1 * scale,
            bottom=self.bottom * scale,
        )

    def vertically_overlaps(self, other: BBox, tolerance: float = 0.5) -> bool:
        """Whether two boxes share a horizontal band, i.e. sit on the same visual line.

        Used by grounding to decide when a matched quote has wrapped across lines and so
        needs one rectangle per line rather than one box spanning both (which would draw a
        highlight over everything in between).
        """
        return (self.top - tolerance) < other.bottom and (other.top - tolerance) < self.bottom


def union_all(boxes: list[BBox]) -> BBox:
    """Union of a non-empty list of boxes."""
    if not boxes:
        raise ValueError("union_all requires at least one box")
    result = boxes[0]
    for box in boxes[1:]:
        result = result.union(box)
    return result


def group_into_lines(boxes: list[BBox], tolerance: float = 0.5) -> list[BBox]:
    """Collapse boxes into one union box per visual line, ordered top to bottom.

    A quote that wraps mid-sentence must highlight as two rectangles, not one tall box, or
    the highlight covers unrelated content between the two fragments. Requirement FR-30
    depends on the highlight being the *exact* region.
    """
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda b: (b.top, b.x0))
    lines: list[list[BBox]] = [[ordered[0]]]
    for box in ordered[1:]:
        if any(box.vertically_overlaps(member, tolerance) for member in lines[-1]):
            lines[-1].append(box)
        else:
            lines.append([box])
    return [union_all(line) for line in lines]
