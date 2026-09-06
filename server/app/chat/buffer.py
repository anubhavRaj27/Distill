"""The in-memory answer buffer. Decision D32.

THE PROBLEM THIS SOLVES
-----------------------
Generation must not depend on anyone listening. If the browser tab closes mid-answer, the
model call should still finish and the message should still be persisted, because the user
will come back and expect their answer to be there. Equally, a client that reconnects
should resume from where it dropped rather than from the beginning or not at all.

So the generating task writes events into a buffer and never learns whether a stream is
attached. The route tails the buffer. Those are the two halves of decision D32, and keeping
them ignorant of each other is what makes both properties fall out for free.

Events carry a monotonic sequence number starting at 1, which becomes the Server-Sent
Events ``id``, which the browser sends back as ``Last-Event-ID`` on reconnect. No client
code is needed for resume to work.

The buffer is held for a grace period after completion so a late reconnect can still replay
it. After that the persisted message is the record, and a reconnecting client is served a
single ``done`` event from the database instead.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.logging import get_logger

logger = get_logger(__name__)

MAX_BUFFERED_EVENTS = 4000
"""A ceiling on one answer. A model that streams forever is a bug, and an unbounded buffer
would turn it into a memory leak rather than a visible failure."""


@dataclass
class BufferedEvent:
    seq: int
    payload: dict[str, Any]


@dataclass
class AnswerBuffer:
    """Events for one in-flight answer, tailed by zero or more streams."""

    message_id: UUID
    events: list[BufferedEvent] = field(default_factory=list)
    closed: bool = False
    closed_at: float | None = None
    overflowed: bool = False
    _condition: asyncio.Condition = field(default_factory=asyncio.Condition)

    @property
    def next_seq(self) -> int:
        return len(self.events) + 1

    async def append(self, event: BaseModel | dict[str, Any]) -> int:
        """Add an event and wake every follower. Returns its sequence number."""
        payload = event.model_dump(mode="json") if isinstance(event, BaseModel) else event
        async with self._condition:
            if self.closed:
                logger.warning(
                    "chat.append_after_close", message_id=str(self.message_id)
                )
                return len(self.events)
            if len(self.events) >= MAX_BUFFERED_EVENTS:
                if not self.overflowed:
                    self.overflowed = True
                    logger.error(
                        "chat.buffer_overflow",
                        message_id=str(self.message_id),
                        limit=MAX_BUFFERED_EVENTS,
                    )
                return len(self.events)
            entry = BufferedEvent(seq=self.next_seq, payload=payload)
            self.events.append(entry)
            self._condition.notify_all()
            return entry.seq

    async def close(self) -> None:
        """Mark generation finished and release every follower."""
        async with self._condition:
            self.closed = True
            self.closed_at = time.monotonic()
            self._condition.notify_all()

    async def follow(self, after_seq: int = 0) -> AsyncIterator[BufferedEvent]:
        """Yield events after ``after_seq``, then wait for more until the buffer closes.

        Replay and live delivery are the same loop rather than two phases, which is what
        makes this immune to the race that a separate "replay then subscribe" would have:
        the list IS the log, so there is no window between reading it and listening.
        """
        cursor = after_seq
        while True:
            async with self._condition:
                while cursor >= len(self.events) and not self.closed:
                    await self._condition.wait()
                pending = self.events[cursor:]
                finished = self.closed and cursor + len(pending) >= len(self.events)
            for entry in pending:
                cursor = entry.seq
                yield entry
            if finished:
                return


class BufferRegistry:
    """Every in-flight and recently finished answer buffer.

    In-process, consistent with the single-process constraint decision D8 already imposes.
    A second API process would not see another's buffers, which is why the worker count is
    pinned to one and ``/healthz`` reports the process identifier.
    """

    def __init__(self) -> None:
        self._buffers: dict[UUID, AnswerBuffer] = {}

    def create(self, message_id: UUID) -> AnswerBuffer:
        buffer = AnswerBuffer(message_id=message_id)
        self._buffers[message_id] = buffer
        return buffer

    def get(self, message_id: UUID) -> AnswerBuffer | None:
        return self._buffers.get(message_id)

    def discard(self, message_id: UUID) -> None:
        self._buffers.pop(message_id, None)

    def sweep(self, grace_seconds: float) -> int:
        """Drop buffers closed longer ago than the grace period. Returns how many."""
        now = time.monotonic()
        stale = [
            message_id
            for message_id, buffer in self._buffers.items()
            if buffer.closed
            and buffer.closed_at is not None
            and now - buffer.closed_at > grace_seconds
        ]
        for message_id in stale:
            del self._buffers[message_id]
        if stale:
            logger.info("chat.buffers_swept", count=len(stale))
        return len(stale)

    @property
    def size(self) -> int:
        return len(self._buffers)


buffers = BufferRegistry()
"""The process-wide registry. One instance, because it IS the process's shared state."""
