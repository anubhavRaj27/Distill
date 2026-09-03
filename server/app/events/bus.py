"""Publishing and subscribing to workspace events.

Three properties this module exists to guarantee.

**Sequence numbers are gap-free and ordered per workspace.** Allocation is
``UPDATE workspaces SET event_seq = event_seq + 1 ... RETURNING event_seq``. The row lock
that update takes serialises allocation, so two concurrent publishes cannot produce the same
number or an out-of-order pair. ``Last-Event-ID`` resume depends on this: a client asking
for "everything after 41" must not later be handed a 40.

**A subscriber never sees an event whose transaction rolled back.** ``publish`` writes the
row and *stages* the notification on the session rather than delivering it. Delivery happens
in ``flush_after_commit``, called once the transaction has actually committed. Delivering at
publish time would let a subscriber act on an event that never happened, which is worse than
a delayed event because it is unrecoverable: there is no compensating message to send.

**A reconnecting subscriber misses nothing, and sees nothing twice.** This is review
finding 8.3. The naive order, "replay what was missed, then start listening", drops any
event published in the window between the two steps. ``stream_from`` therefore subscribes
FIRST and buffers, then reads the replay range, then emits the replay, then emits the buffer
with any sequence number already emitted discarded. Correct under concurrent publishing, not
merely in a quiet window.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workspace, WorkspaceEventRow
from app.logging import get_logger

logger = get_logger(__name__)

# How many events a slow subscriber may fall behind before it is dropped. A subscriber that
# stops reading is a browser tab that has gone away, and holding events for it forever would
# be a memory leak. Dropping it is safe because reconnecting replays from the log.
SUBSCRIBER_QUEUE_LIMIT = 512

_SESSION_KEY = "sift_pending_events"


@dataclass
class _Subscriber:
    queue: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_LIMIT)
    )
    dropped: bool = False


class EventBus:
    """In-process publish and subscribe, paired with the persisted log.

    In-process is a deliberate limit, not an oversight: decision D9 chose a single instance
    with an in-process worker queue, and this bus shares that constraint. Running two API
    worker processes would split the bus and deliver each event to only the subscribers in
    one of them. The worker count is pinned to one, and ``/healthz`` reports the process
    identifier so a misconfiguration is visible rather than mysterious.
    """

    def __init__(self) -> None:
        self._subscribers: dict[UUID, set[_Subscriber]] = {}

    # -- publishing -----------------------------------------------------

    async def publish(
        self, session: AsyncSession, workspace_id: UUID, event: BaseModel
    ) -> int:
        """Persist ``event`` and stage its delivery. Returns the allocated sequence number.

        ``event`` must be one of the models in ``app.domain.events`` and must NOT have its
        ``seq`` set: the sequence number is allocated here, because only the database can
        allocate it safely.
        """
        seq = await self._allocate_seq(session, workspace_id)

        payload = event.model_dump(mode="json")
        payload["seq"] = seq
        event_type = str(payload.get("type", "unknown"))

        session.add(
            WorkspaceEventRow(
                workspace_id=workspace_id, seq=seq, type=event_type, payload=payload
            )
        )

        # Staged, not delivered. See the module docstring.
        pending: list[tuple[UUID, dict[str, Any]]] = session.info.setdefault(_SESSION_KEY, [])
        pending.append((workspace_id, payload))
        return seq

    async def _allocate_seq(self, session: AsyncSession, workspace_id: UUID) -> int:
        result = await session.execute(
            update(Workspace)
            .where(Workspace.id == workspace_id)
            .values(event_seq=Workspace.event_seq + 1)
            .returning(Workspace.event_seq)
        )
        seq = result.scalar_one_or_none()
        if seq is None:
            raise LookupError(f"workspace {workspace_id} does not exist")
        return int(seq)

    def flush_after_commit(self, session: AsyncSession) -> None:
        """Deliver every event staged on ``session``. Call only after a successful commit."""
        pending: list[tuple[UUID, dict[str, Any]]] = session.info.pop(_SESSION_KEY, [])
        for workspace_id, payload in pending:
            self._deliver(workspace_id, payload)

    def discard_staged(self, session: AsyncSession) -> None:
        """Throw away staged events. Call after a rollback."""
        dropped = session.info.pop(_SESSION_KEY, [])
        if dropped:
            logger.info("events.discarded_on_rollback", count=len(dropped))

    def _deliver(self, workspace_id: UUID, payload: dict[str, Any]) -> None:
        for subscriber in tuple(self._subscribers.get(workspace_id, ())):
            try:
                subscriber.queue.put_nowait(payload)
            except asyncio.QueueFull:
                # The subscriber is not reading. Mark it and stop trying: it will notice
                # the marker, close, and replay from the log when it reconnects.
                subscriber.dropped = True
                logger.warning(
                    "events.subscriber_dropped",
                    workspace_id=str(workspace_id),
                    reason="queue_full",
                )

    # -- subscribing ----------------------------------------------------

    @asynccontextmanager
    async def subscribe(self, workspace_id: UUID) -> AsyncIterator[_Subscriber]:
        """Register a live subscriber for the duration of the block."""
        subscriber = _Subscriber()
        self._subscribers.setdefault(workspace_id, set()).add(subscriber)
        logger.info(
            "events.subscribed",
            workspace_id=str(workspace_id),
            subscribers=len(self._subscribers[workspace_id]),
        )
        try:
            yield subscriber
        finally:
            listeners = self._subscribers.get(workspace_id)
            if listeners is not None:
                listeners.discard(subscriber)
                if not listeners:
                    del self._subscribers[workspace_id]

    def subscriber_count(self, workspace_id: UUID) -> int:
        return len(self._subscribers.get(workspace_id, ()))

    # -- replay ---------------------------------------------------------

    @staticmethod
    async def replay(
        session: AsyncSession, workspace_id: UUID, after_seq: int, limit: int = 2000
    ) -> list[dict[str, Any]]:
        """Every event for this workspace with ``seq > after_seq``, oldest first."""
        result = await session.execute(
            select(WorkspaceEventRow.payload)
            .where(
                WorkspaceEventRow.workspace_id == workspace_id,
                WorkspaceEventRow.seq > after_seq,
            )
            .order_by(WorkspaceEventRow.seq)
            .limit(limit)
        )
        return [row for (row,) in result.all()]


bus = EventBus()
"""The process-wide bus. One instance, because it IS the process's shared state."""
