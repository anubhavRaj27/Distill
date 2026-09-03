"""The coordinate convention, as an executable assertion. See decision D17.

This is deliberately the first test in the project. The entire provenance feature, which is
the product's central trust claim, rests on the backend and the browser agreeing about where
the origin of a page is. Section 8.3 of implementation.md ASSUMED that pdfplumber already
flips the PDF format's bottom-left origin. It does, and this file is why we know rather than
hope. If a future pdfplumber release changes it, this test fails in one second instead of
highlights silently drifting to the wrong part of the page in a demo.
"""

from __future__ import annotations

import io

import pdfplumber
import pypdfium2
import pytest
from app.domain.geometry import BBox

from tests.fixtures.pdfs import LETTER_HEIGHT_PT, LETTER_WIDTH_PT, single_word_pdf


def test_page_dimensions_are_reported_in_points() -> None:
    data, _ = single_word_pdf()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[0]
        assert (page.width, page.height) == (LETTER_WIDTH_PT, LETTER_HEIGHT_PT)


def test_pdfplumber_top_is_measured_from_the_top_of_the_page() -> None:
    """The load-bearing assertion. `top` grows downward from the top edge."""
    baseline_from_bottom = 700.0
    font_size = 24.0
    data, placed = single_word_pdf(
        baseline_from_bottom_pt=baseline_from_bottom, font_size_pt=font_size
    )

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()

    assert len(words) == 1, "fixture must contain exactly one word"
    word = words[0]
    assert word["text"] == placed.text

    # Horizontal: x0 is measured from the left edge, and matches where we drew it.
    assert word["x0"] == pytest.approx(placed.x_left_pt, abs=0.01)

    # Vertical: the glyph box spans one font size, and its TOP edge sits
    # (page height - baseline - ascent) below the top of the page. Helvetica's cap
    # geometry puts the drawn extent within a font-size band of the baseline, so the
    # decisive check is that `top` is near the TOP of the page (~93pt) and nowhere near
    # the value it would have if the origin were at the bottom (~700pt).
    expected_top_approx = placed.baseline_from_top_pt - font_size
    assert word["top"] == pytest.approx(expected_top_approx, abs=font_size)
    assert word["top"] < LETTER_HEIGHT_PT / 2, (
        "the word was drawn in the TOP half of the page, so `top` must be small. "
        f"Got top={word['top']}, which suggests a bottom-left origin."
    )
    assert word["bottom"] > word["top"], "`bottom` must be below `top` in this convention"
    assert word["bottom"] - word["top"] == pytest.approx(font_size, abs=0.01)


def test_top_and_bottom_are_the_flip_of_the_raw_pdf_y_values() -> None:
    """`top == page.height - y1`. This is the identity the convention rests on."""
    data, _ = single_word_pdf()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[0]
        char = page.chars[0]
        assert char["top"] == pytest.approx(page.height - char["y1"], abs=0.01)
        assert char["bottom"] == pytest.approx(page.height - char["y0"], abs=0.01)


def test_a_word_box_is_a_valid_bbox_in_our_convention() -> None:
    """pdfplumber's output maps onto BBox with no transform at all."""
    data, _ = single_word_pdf()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        word = pdf.pages[0].extract_words()[0]

    box = BBox(x0=word["x0"], top=word["top"], x1=word["x1"], bottom=word["bottom"])
    assert box.width > 0 and box.height > 0
    assert 0 <= box.x0 < box.x1 <= LETTER_WIDTH_PT
    assert 0 <= box.top < box.bottom <= LETTER_HEIGHT_PT


@pytest.mark.parametrize("dpi", [72, 96, 144, 200])
def test_render_pixel_size_is_exactly_points_times_scale(dpi: int) -> None:
    """The overlay scale is a single uniform factor, with no rounding drift to correct.

    This is what lets the viewer compute `scale = rendered_width_px / page_width_pt` and
    trust it, rather than tracking dots per inch through the interface.
    """
    data, _ = single_word_pdf()
    document = pypdfium2.PdfDocument(io.BytesIO(data))
    page = document[0]

    assert page.get_width() == pytest.approx(LETTER_WIDTH_PT)
    assert page.get_height() == pytest.approx(LETTER_HEIGHT_PT)

    scale = dpi / 72.0
    image = page.render(scale=scale).to_pil()

    assert image.width == round(LETTER_WIDTH_PT * scale)
    assert image.height == round(LETTER_HEIGHT_PT * scale)
    # And the round trip a viewer performs recovers the original scale.
    assert image.width / page.get_width() == pytest.approx(scale, rel=1e-6)


def test_scaling_a_box_to_rendered_pixels_keeps_it_inside_the_image() -> None:
    """End to end: word box in points, page rendered, box scaled, still on the page."""
    data, _ = single_word_pdf()
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page = pdf.pages[0]
        word = page.extract_words()[0]
        box = BBox(x0=word["x0"], top=word["top"], x1=word["x1"], bottom=word["bottom"])
        width_pt = page.width

    image = pypdfium2.PdfDocument(io.BytesIO(data))[0].render(scale=2.0).to_pil()
    scale = image.width / width_pt
    scaled = box.scaled(scale)

    assert 0 <= scaled.x0 < scaled.x1 <= image.width
    assert 0 <= scaled.top < scaled.bottom <= image.height
