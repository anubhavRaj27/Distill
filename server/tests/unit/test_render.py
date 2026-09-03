"""The page renderer, verified against the pixels it actually drew.

The strongest available check on a coordinate system is not "the numbers look plausible",
it is "the box contains the ink". These tests crop the rendered image to a reported word box
and assert there are dark pixels inside it, and none in a region no word claims. That makes
the geometry in ``app.pipeline.parse.render`` verified rather than asserted.
"""

from __future__ import annotations

import io
import itertools

import pytest
from app.pipeline.parse.render import (
    DEFAULT_LAYOUT,
    PageLayout,
    RenderLine,
    render_pages,
    wrap,
)
from PIL import Image


def _dark_pixel_count(image: Image.Image, box: tuple[int, int, int, int]) -> int:
    crop = image.crop(box).convert("L")
    return sum(1 for value in crop.get_flattened_data() if value < 128)


def test_a_rendered_page_matches_its_declared_point_size() -> None:
    page, png = render_pages([RenderLine("Total Due: $12,480.50")], dpi=144)[0]
    image = Image.open(io.BytesIO(png))
    assert image.width == round(page.width_pt * 2.0)
    assert image.height == round(page.height_pt * 2.0)


@pytest.mark.parametrize("dpi", [72, 144, 200])
def test_every_word_box_contains_the_ink_of_its_word(dpi: int) -> None:
    """The load-bearing assertion for decision D18's single coordinate convention."""
    page, png = render_pages(
        [RenderLine("Supplier: Northwind Traders"), RenderLine("Total: 12480.50")], dpi=dpi
    )[0]
    image = Image.open(io.BytesIO(png))
    scale = image.width / page.width_pt

    assert page.words, "the fixture must produce words"
    for word in page.words:
        pixels = word.box.scaled(scale)
        box = (
            int(pixels.x0),
            int(pixels.top),
            max(int(pixels.x1), int(pixels.x0) + 1),
            max(int(pixels.bottom), int(pixels.top) + 1),
        )
        assert _dark_pixel_count(image, box) > 0, f"no ink inside the box for {word.text!r}"


def test_a_region_no_word_claims_is_blank() -> None:
    """Guards against boxes that pass by being enormous."""
    _page, png = render_pages([RenderLine("Short line")], dpi=144)[0]
    image = Image.open(io.BytesIO(png))
    bottom_right = (
        int(image.width * 0.75),
        int(image.height * 0.75),
        image.width,
        image.height,
    )
    assert _dark_pixel_count(image, bottom_right) == 0


def test_word_boxes_on_one_line_do_not_overlap_and_run_left_to_right() -> None:
    page, _png = render_pages([RenderLine("alpha beta gamma delta")], dpi=144)[0]
    boxes = [word.box for word in page.words]
    assert [word.text for word in page.words] == ["alpha", "beta", "gamma", "delta"]
    for earlier, later in itertools.pairwise(boxes):
        assert earlier.x1 <= later.x0, "word boxes must not overlap horizontally"


def test_multiple_spaces_do_not_shift_word_positions() -> None:
    """Prefix measurement, not width summation, is what makes this work."""
    page, png = render_pages([RenderLine("alpha      omega")], dpi=144)[0]
    image = Image.open(io.BytesIO(png))
    scale = image.width / page.width_pt
    omega = next(word for word in page.words if word.text == "omega")
    pixels = omega.box.scaled(scale)
    assert (
        _dark_pixel_count(
            image, (int(pixels.x0), int(pixels.top), int(pixels.x1), int(pixels.bottom))
        )
        > 0
    )


def test_long_lines_wrap_and_each_part_keeps_its_locator() -> None:
    """A wrapped paragraph must still say which paragraph it came from."""
    long_line = RenderLine(" ".join(["word"] * 300), "paragraph 7")
    wrapped = wrap([long_line], DEFAULT_LAYOUT, dpi=144)
    assert len(wrapped) > 1
    assert all(part.locator == "paragraph 7" for part in wrapped)


def test_wrapped_lines_fit_within_the_usable_width() -> None:
    page, _png = render_pages([RenderLine(" ".join(["measurable"] * 80))], dpi=144)[0]
    limit = DEFAULT_LAYOUT.width_pt - DEFAULT_LAYOUT.margin_pt
    for line in page.lines:
        assert line.box.x1 <= limit + 0.5, "a line ran past the right margin"


def test_content_longer_than_one_page_produces_several_pages() -> None:
    layout = PageLayout()
    lines = [RenderLine(f"row {number}") for number in range(layout.lines_per_page * 2 + 3)]
    rendered = render_pages(lines, layout=layout, dpi=96)
    assert len(rendered) == 3
    assert [page.index for page, _png in rendered] == [0, 1, 2]


def test_blank_input_still_produces_a_page() -> None:
    """A parser must never hand back zero pages: the viewer needs something to show."""
    rendered = render_pages([], dpi=144)
    assert len(rendered) == 1
    assert rendered[0][0].words == []
