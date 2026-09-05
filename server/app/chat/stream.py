"""Transforming raw model output into the answer stream. Decisions D45 and D46.

The model writes two things the user must never see raw:

* ``[^chunk:<uuid>]`` citation markers, which become numbered footnotes
* ``{{result.total}}`` placeholders, which become server-computed figures

Both are rewritten here, before anything reaches the buffer.

WHY THIS IS A STATE MACHINE AND NOT A REGULAR EXPRESSION
---------------------------------------------------------
Deltas arrive at whatever boundaries the provider chooses, so a marker can be split
anywhere: ``[^chunk:ab`` in one delta and ``cd]`` in the next, or even ``[`` and ``^``
separately. Running a pattern over each delta independently would emit half a marker as
prose and then the other half, which the user would see. So text is held back from an
unmatched opener until its closer arrives, and only provably safe text is emitted.

The same applies to a trailing lone ``[`` or ``{``: it might be the start of an opener, so
it is held for one more delta rather than emitted and regretted.

ORDERING, WHICH IS PART OF THE CONTRACT
----------------------------------------
When a marker resolves, the text before it is flushed as a token FIRST, then the
``citation`` event, then the rewritten ``[^n]``. The client therefore always knows what
footnote 3 is before it has to render a reference to it (decision D45), and never displays
an unresolved marker.

A DROPPED MARKER IS PREFERRED TO A WRONG ONE
---------------------------------------------
A marker naming a chunk that was not retrieved is dropped silently rather than shown. The
model occasionally invents an identifier, and a footnote pointing at nothing is worse than
no footnote: it is a broken promise about provenance, which is the one thing this product
is claiming.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.chat.citations import ResolvedCitation
from app.chat.events import CitationEvent, TokenEvent
from app.logging import get_logger

logger = get_logger(__name__)

MARKER_OPEN = "[^"
PLACEHOLDER_OPEN = "{{"
PLACEHOLDER_CLOSE = "}}"

_MARKER = re.compile(r"\[\^chunk:([0-9a-fA-F-]{8,40})\]")
_MARKER_PREFIX = "[^chunk:"
_PARTIAL_TAIL = ("[", "{")

CitationResolver = Callable[[UUID], Awaitable[ResolvedCitation | None]]


def format_figure(value: Any, unit: str | None) -> str:
    """Render a computed figure for prose. Decision D46.

    Thousands separators and two decimal places for money, no decimals for whole numbers,
    and the currency code appended when one is known. The point is that the user reads the
    same number the chart shows, formatted the same way, because a mismatch between the
    prose and the chart reads as a bug even when both are right.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        number = float(value)
        if number.is_integer() and abs(number) < 1e15:
            rendered = f"{int(number):,}"
        else:
            rendered = f"{number:,.2f}"
        return f"{rendered} {unit}".strip() if unit else rendered
    return str(value)


_UNIT_LEAD = r"[\s`\"'*)\]]*"
"""Closing markup that can sit between a substituted figure and the model's repeat of its
unit. Models write both "`12.00 USD` USD" and "`12.00 USD USD`", so the backtick has to be
stepped over and then put back."""


def _drop_leading_unit(text: str, unit: str) -> str:
    """Remove one leading repeat of ``unit`` from ``text``, keeping any markup before it.

    Only at a word boundary, and only the first occurrence, so a later "USD" in the model's
    own sentence survives and a word merely starting with the unit is untouched.
    """
    match = re.match(rf"(?P<lead>{_UNIT_LEAD}){re.escape(unit)}\b", text, re.IGNORECASE)
    if not match:
        return text
    lead = match.group("lead")
    remainder = text[match.end() :]
    if lead.strip():
        # Markup such as a closing backtick belongs to the figure, so keep it and drop only
        # the duplicated unit.
        return f"{lead.strip()}{remainder}"
    # Keep one space when the duplicate was preceded by one and a word follows, so
    # "12.00 USD USD per unit" does not close up into "12.00 USDper unit".
    if text[:1].isspace() and remainder[:1].isalnum():
        return f" {remainder}"
    return remainder


@dataclass
class StreamProcessor:
    """Rewrites one answer's token stream. Single use, one per message."""

    resolve_citation: CitationResolver
    result_paths: dict[str, tuple[Any, str | None]] = field(default_factory=dict)
    """Path to ``(value, unit)``. The unit is per path because a single result holds both a
    monetary total and a record count, and one shared unit produced "across 5 USD
    documents"."""

    coalesce_ms: int = 40

    _pending: str = ""
    _outbox: str = ""
    _emitted_unit: str | None = None
    """The unit on the figure just substituted, until the next staged text is checked for a
    duplicate of it. See ``_stage``."""
    _last_emit: float = field(default_factory=time.monotonic)
    _numbers: dict[str, int] = field(default_factory=dict)
    _citations: list[dict[str, Any]] = field(default_factory=list)
    _text: list[str] = field(default_factory=list)
    _unresolved_placeholders: int = 0
    _dropped_markers: int = 0

    # -- what the caller keeps afterwards -------------------------------

    @property
    def text(self) -> str:
        """The answer as the user saw it, for persistence."""
        return "".join(self._text)

    @property
    def citations(self) -> list[dict[str, Any]]:
        """Resolved citations in footnote order, for persistence."""
        return list(self._citations)

    # -- the machine ----------------------------------------------------

    async def feed(self, delta: str) -> AsyncIterator[TokenEvent | CitationEvent]:
        """Consume one raw delta, yielding whatever is now safe to send."""
        self._pending += delta

        while True:
            marker_at = self._pending.find(MARKER_OPEN)
            placeholder_at = self._pending.find(PLACEHOLDER_OPEN)
            candidates = [index for index in (marker_at, placeholder_at) if index >= 0]

            if not candidates:
                # No opener anywhere. Emit everything except a possible partial opener.
                hold = 1 if self._pending.endswith(_PARTIAL_TAIL) else 0
                if hold:
                    self._stage(self._pending[:-hold])
                    self._pending = self._pending[-hold:]
                else:
                    self._stage(self._pending)
                    self._pending = ""
                break

            opener_at = min(candidates)
            self._stage(self._pending[:opener_at])
            self._pending = self._pending[opener_at:]

            if self._pending.startswith(MARKER_OPEN):
                close_at = self._pending.find("]")
                if close_at < 0:
                    break  # incomplete marker, wait for more
                raw = self._pending[: close_at + 1]
                self._pending = self._pending[close_at + 1 :]
                async for event in self._resolve_marker(raw):
                    yield event
                continue

            close_at = self._pending.find(PLACEHOLDER_CLOSE)
            if close_at < 0:
                break  # incomplete placeholder, wait for more
            raw = self._pending[: close_at + len(PLACEHOLDER_CLOSE)]
            self._pending = self._pending[close_at + len(PLACEHOLDER_CLOSE) :]
            figure, unit = self._substitute(raw)
            self._stage(figure)
            # Armed AFTER staging the figure, or the guard in ``_stage`` would strip the
            # unit off the figure itself rather than off the model's repeat of it.
            self._emitted_unit = unit

        for event in self._maybe_flush():
            yield event

    async def flush(self) -> AsyncIterator[TokenEvent | CitationEvent]:
        """Emit everything held. Called once when the model stream ends.

        Anything still pending here is an unterminated marker or placeholder, which means
        the model stopped mid-construct. It is emitted as literal text rather than dropped:
        the user seeing a stray ``{{result.`` is ugly but honest, whereas silently deleting
        the tail of an answer loses content.
        """
        if self._pending:
            logger.info(
                "chat.unterminated_construct",
                tail=self._pending[:40],
                detail="emitted as literal text rather than discarded",
            )
            self._stage(self._pending)
            self._pending = ""
        if self._outbox:
            yield self._emit_outbox()
        if self._unresolved_placeholders or self._dropped_markers:
            logger.info(
                "chat.stream_finished_with_gaps",
                unresolved_placeholders=self._unresolved_placeholders,
                dropped_markers=self._dropped_markers,
            )

    # -- internals ------------------------------------------------------

    def _stage(self, text: str) -> None:
        if not text:
            return
        if self._emitted_unit:
            # A substituted figure already carries its currency, and models write the unit
            # again anyway: "`{{result.total}}` USD" becomes "16,752.90 USD USD". The prompt
            # asks them not to; this makes it not matter. Decision D68.
            stripped = _drop_leading_unit(text, self._emitted_unit)
            if stripped != text:
                self._emitted_unit = None
                text = stripped
            elif not re.fullmatch(_UNIT_LEAD, text):
                # Real prose followed, so the model did not repeat itself. Anything that is
                # only closing markup or whitespace stays armed: a code span's backtick
                # routinely arrives in one delta and the repeated unit in the next.
                self._emitted_unit = None
            if not text:
                return
        self._outbox += text

    def _emit_outbox(self) -> TokenEvent:
        text = self._outbox
        self._outbox = ""
        self._last_emit = time.monotonic()
        self._text.append(text)
        return TokenEvent(text=text)

    def _maybe_flush(self) -> list[TokenEvent]:
        """Emit the outbox if the coalescing interval has elapsed.

        Batching exists because a fast model produces deltas far quicker than a browser can
        usefully repaint, and thousands of one-word frames make the page janky rather than
        lively.
        """
        if not self._outbox:
            return []
        if (time.monotonic() - self._last_emit) * 1000 < self.coalesce_ms:
            return []
        return [self._emit_outbox()]

    async def _resolve_marker(
        self, raw: str
    ) -> AsyncIterator[TokenEvent | CitationEvent]:
        match = _MARKER.fullmatch(raw)
        if match is None:
            if raw.startswith(_MARKER_PREFIX):
                # Meant as a citation and malformed. Dropped, not emitted: rendering
                # "[^chunk:not-a-uuid]" into the prose shows the user our internal syntax,
                # which is worse than a missing footnote.
                self._dropped_markers += 1
                logger.info("chat.malformed_marker_dropped", raw=raw[:60])
                return
            # Any other "[^..." is just text, such as a footnote a document itself used.
            self._stage(raw)
            return

        chunk_ref = match.group(1)
        existing = self._numbers.get(chunk_ref)
        if existing is not None:
            # A repeated citation reuses its number and needs no second event.
            self._stage(f"[^{existing}]")
            return

        try:
            chunk_id = UUID(chunk_ref)
        except ValueError:
            self._dropped_markers += 1
            return

        resolved = await self.resolve_citation(chunk_id)
        if resolved is None:
            # An invented or vanished chunk. Dropped, because a footnote pointing at
            # nothing breaks the one promise this product makes.
            self._dropped_markers += 1
            logger.info("chat.marker_dropped", chunk_id=chunk_ref)
            return

        number = len(self._numbers) + 1
        self._numbers[chunk_ref] = number

        # The text before the marker goes out FIRST, then the citation, then the reference.
        if self._outbox:
            yield self._emit_outbox()

        payload = resolved.to_payload(number)
        self._citations.append(payload)
        yield CitationEvent.model_validate(payload)
        self._stage(f"[^{number}]")

    def _substitute(self, raw: str) -> tuple[str, str | None]:
        """Replace ``{{path}}`` with the server-computed value. Decision D46.

        Returns the rendered figure and the unit it already carries, if any, so the caller
        can suppress the model writing that unit again. See ``_stage`` and decision D68.
        """
        path = raw[len(PLACEHOLDER_OPEN) : -len(PLACEHOLDER_CLOSE)].strip()
        entry = self.result_paths.get(path)
        if entry is None:
            # Emitting nothing is deliberate. Showing the raw placeholder would expose
            # internals, and inventing a number is the exact thing decision D37 forbids.
            self._unresolved_placeholders += 1
            logger.info("chat.placeholder_unresolved", path=path)
            return "", None
        value, unit = entry
        figure = format_figure(value, unit)
        return figure, (unit if unit and figure.endswith(unit) else None)
