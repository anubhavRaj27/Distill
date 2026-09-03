"""A parsed document, normalised so that everything downstream is format-agnostic.

The seven parsers in ``app.pipeline.parse`` all produce a ``ParsedDocument``. Extraction,
grounding, and scoring know nothing about PDFs, spreadsheets, or images. That boundary is
what keeps the pipeline testable and what makes adding a format a change in exactly one
place.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.geometry import BBox


class SourceFormat(StrEnum):
    """Formats Sift can parse. Requirement FR-02."""

    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"
    TEXT = "text"


class DocumentStatus(StrEnum):
    """Where a document is in the pipeline. Rendered directly as the progress list.

    The observability requirement and the user experience are the same feature here: the
    progress list in the interface IS this state machine, so every state has to be a state
    a person would want to see, and every transition publishes an event.

    Transitions::

        uploaded -> parsed -> extracting -> awaiting_schema -> done
             |         |          |               |
             +---------+----------+---------------+--> failed

    ``awaiting_schema`` is the state review finding 8.5 introduced. A document in the very
    first batch finishes open extraction before the workspace has a schema, so it cannot
    produce records yet. Without this state the interface would have to show it as either
    still working (a lie) or done (also a lie, since no row appeared).
    """

    UPLOADED = "uploaded"
    PARSED = "parsed"
    EXTRACTING = "extracting"
    AWAITING_SCHEMA = "awaiting_schema"
    DONE = "done"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Whether no further work will happen without a new instruction."""
        return self in (DocumentStatus.DONE, DocumentStatus.FAILED)


class Word(BaseModel):
    """One word with its box, in top-left-origin page points."""

    model_config = {"frozen": True}

    text: str
    box: BBox


class Line(BaseModel):
    """One visual line of text.

    Lines carry the ``locator`` that becomes ``Provenance.locator``, which is how a
    spreadsheet cell address or a DOCX paragraph number survives into the interface after
    the format has been normalised away.
    """

    index: int
    text: str
    box: BBox
    locator: str | None = None


class ParsedPage(BaseModel):
    """One page. For non-paginated formats, a page is whatever unit the parser chose.

    A spreadsheet sheet is a page. A DOCX or text file is split into pages by how much
    fits on a rendered sheet, so the viewer always has something page-shaped to show.
    """

    index: int = Field(ge=0)
    width_pt: float = Field(gt=0, description="Page width in points. The overlay divisor.")
    height_pt: float = Field(gt=0)
    words: list[Word] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    image_key: str | None = Field(
        default=None, description="Storage key of the rendered page image, if rendered."
    )
    ocr_applied: bool = Field(
        default=False,
        description="Whether word boxes came from Optical Character Recognition rather "
        "than an embedded text layer. Surfaced to the user, because OCR word boxes are "
        "less precise and the user deserves to know which highlights are approximate.",
    )
    locator: str | None = Field(
        default=None, description="Page-level address, such as a spreadsheet sheet name."
    )

    @property
    def text(self) -> str:
        """The page as plain text, one line per line. What the model is shown."""
        return "\n".join(line.text for line in self.lines)


class ParsedDocument(BaseModel):
    """The normalised output of every parser."""

    source_format: SourceFormat
    pages: list[ParsedPage]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def total_words(self) -> int:
        return sum(len(page.words) for page in self.pages)

    @property
    def has_text(self) -> bool:
        """Whether anything at all was extracted. False means every strategy failed."""
        return self.total_words > 0
