"""Where a value came from, in one shape for every document format.

DESIGN NOTE, and a deliberate simplification of implementation.md (decision D14)
--------------------------------------------------------------------------------
The implementation document proposed a different provenance unit per format: a bounding box
for PDFs and images, a paragraph index for DOCX, a cell range for spreadsheets, a line span
for plain text. That is four shapes, so it is four frontend rendering paths, four sets of
coordinate mathematics, and four ways to be subtly wrong.

Distill instead renders **every** format to a page image with a layout the backend controls, so
the backend always knows exactly where each line of text sits. Provenance is therefore
always a list of boxes over a page, in the single coordinate convention documented in
``app.domain.geometry``, for all seven supported formats.

The semantic locator is kept alongside as a display string, so a spreadsheet value still
tells the user "Sheet1!B7" and a DOCX value still says "paragraph 12". This satisfies
requirement FR-35 more directly than the original plan did, since the user gets both the
highlight and the address, and it costs one overlay implementation instead of four.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.geometry import BBox


class GroundingFailure(StrEnum):
    """Why a value could not be located in its document.

    Recorded rather than swallowed. A value that cannot be grounded has its tier capped at
    low (see ``app.pipeline.score``), and this is the reason the interface shows the user.
    An ungroundable value is the strongest hallucination signal we have: a value the model
    invented has no quote to find. See decision D5.
    """

    NO_QUOTE = "no_quote"  # the model returned a value but cited no evidence
    QUOTE_NOT_FOUND = "quote_not_found"  # cited evidence is not in the document
    PAGE_OUT_OF_RANGE = "page_out_of_range"  # cited a page the document does not have
    NO_TEXT_LAYER = "no_text_layer"  # the page has no locatable text, even after OCR


class Provenance(BaseModel):
    """The trail from a value back to the pixels it came from.

    An empty ``boxes`` list with a populated ``failure`` is a legitimate, fully described
    state: we have a value, we know the model's justification for it, and we are telling the
    user honestly that we could not find that justification in the document.
    """

    page_index: int | None = Field(
        default=None, description="Zero-based page the value was found on, if known."
    )
    boxes: list[BBox] = Field(
        default_factory=list,
        description="One box per visual line of the matched quote. Empty means grounding "
        "failed, in which case `failure` says why. Multiple boxes rather than one union "
        "box, because a quote that wraps must not highlight the content between its "
        "fragments (requirement FR-30).",
    )
    quote: str | None = Field(
        default=None,
        description="The verbatim span the model cited as evidence. Shown to the user in "
        "the viewer side card (requirement FR-31).",
    )
    reasoning: str | None = Field(
        default=None, description="The model's short justification for this value. FR-31."
    )
    match_score: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Fuzzy match score of the quote against the page text, 0 to 100. "
        "Feeds tier derivation.",
    )
    locator: str | None = Field(
        default=None,
        description="Human-readable address within the source, for formats where one is "
        "meaningful: 'Sheet1!B7', 'paragraph 12', 'line 48'. Display only, never parsed.",
    )
    failure: GroundingFailure | None = Field(
        default=None, description="Set if and only if `boxes` is empty."
    )

    @property
    def is_grounded(self) -> bool:
        return bool(self.boxes)
