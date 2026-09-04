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
    """Formats Distill can parse. Requirement FR-02."""

    PDF = "pdf"
    IMAGE = "image"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"
    TEXT = "text"


class DocumentStatus(StrEnum):
    """Where a document is in the pipeline. Rendered directly as the processing strip.

    The observability requirement and the user experience are the same feature here: the
    strip in the interface IS this state machine, so every state has to be one a person
    would want to see, and every transition publishes an event.

    Transitions::

        uploaded -> parsing -> extracting -> indexing -> done
             |          |           |            |
             +----------+-----------+------------+--> failed

    ``indexing`` is where a document is chunked and embedded. It matters that it is a
    visible stage rather than a silent tail of extraction: a document is not askable until
    it is indexed, so ``done`` means "in the table AND in the chat", which is the promise
    section 6.3 of the implementation document makes.

    AWAITING_SCHEMA IS INTERNAL AND IS NOT PART OF THE WIRE VOCABULARY
    ------------------------------------------------------------------
    A document in the very first batch finishes open extraction before the workspace has a
    schema, so it cannot produce records yet. The worker needs to tell that apart from a
    document still mid-model-call, so the distinction is a real database status.

    It is deliberately **not** one of the six statuses in the interface contract
    (implementation.md section 5.1). On the wire it is reported as ``extracting`` with a
    ``stage_detail`` of "waiting for the rest of the batch", which is honest (the document
    is still inside the extraction phase) and keeps the client's state machine to the six
    states the contract names. ``for_wire`` is that mapping, in one place.
    """

    UPLOADED = "uploaded"
    PARSING = "parsing"
    EXTRACTING = "extracting"
    AWAITING_SCHEMA = "awaiting_schema"
    INDEXING = "indexing"
    DONE = "done"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        """Whether no further work will happen without a new instruction."""
        return self in (DocumentStatus.DONE, DocumentStatus.FAILED)

    @property
    def for_wire(self) -> str:
        """The status as the interface contract names it. See the class docstring."""
        if self is DocumentStatus.AWAITING_SCHEMA:
            return DocumentStatus.EXTRACTING.value
        return self.value


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
