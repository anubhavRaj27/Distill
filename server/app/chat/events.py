"""The per-message answer stream vocabulary. Implementation section 5.2, decision D44.

A separate stream from the workspace event stream, and separate on purpose: an answer
produces hundreds of token events, and writing those into the durable ``workspace_events``
log would turn one question into hundreds of rows for no benefit, since the finished message
is persisted in full anyway.

ORDERING IS PART OF THE CONTRACT, NOT AN ACCIDENT
--------------------------------------------------
* ``visual`` or ``visual_skipped`` always precedes the first ``token``, so the client can
  reserve the card's space before prose starts moving underneath it (decision D47).
* a ``citation`` arrives before the token containing its marker's closing bracket, so the
  client never has to render an unresolved footnote and then rewrite it (decision D45).
* ``done`` carries the whole persisted message, so a client that reconnected late can
  replace its local state wholesale instead of trying to reconcile a partial buffer.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.chat import AnswerStage, VisualKind
from app.domain.geometry import BBox


class AnswerStatusEvent(BaseModel):
    type: Literal["status"] = "status"
    stage: AnswerStage
    detail: str | None = None


class SourceRef(BaseModel):
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_index: int | None = None
    is_digest: bool = False


class SourcesEvent(BaseModel):
    """The passages the answer is allowed to draw on.

    Sent early and deliberately: it is the first thing on screen after "retrieving", so the
    user sees which documents are being read before any prose exists. That turns the wait
    into progress rather than a spinner.
    """

    type: Literal["sources"] = "sources"
    sources: list[SourceRef]


class VisualEvent(BaseModel):
    type: Literal["visual"] = "visual"
    kind: VisualKind
    title: str
    surface: list[dict[str, Any]] = Field(
        description="A complete A2UI message array, sent once. Never streamed in pieces: "
        "a half-built surface is not renderable, so there is nothing to gain from it "
        "(decision D47)."
    )


class VisualSkippedEvent(BaseModel):
    """Why there is no chart. Sent so the client can stop reserving space for one."""

    type: Literal["visual_skipped"] = "visual_skipped"
    reason: Literal[
        "none_planned", "empty_result", "degenerate_result", "evaluation_failed"
    ]


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str = Field(
        description="A prose delta with markers already rewritten to [^n] and placeholders "
        "already substituted. The client renders it verbatim."
    )


class CitationEvent(BaseModel):
    """A footnote, resolved to a highlightable region. Requirement FR-22."""

    type: Literal["citation"] = "citation"
    n: int = Field(ge=1, description="The footnote number as it appears in the prose.")
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_index: int | None = None
    boxes: list[BBox] = Field(
        default_factory=list,
        description="Highlight rectangles in page points, one per visual line. Empty only "
        "when the cited passage has no geometry at all.",
    )
    excerpt: str = ""


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    message: dict[str, Any] = Field(
        description="The persisted message, authoritative. A late client replaces its "
        "local state with this rather than reconciling."
    )


class AnswerErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    correlation_id: str | None = None


AnswerEvent = Annotated[
    AnswerStatusEvent
    | SourcesEvent
    | VisualEvent
    | VisualSkippedEvent
    | TokenEvent
    | CitationEvent
    | DoneEvent
    | AnswerErrorEvent,
    Field(discriminator="type"),
]
