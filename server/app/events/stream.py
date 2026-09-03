"""Turning the bus into a resumable stream. Review finding 8.3 lives here.

The ordering in ``stream_from`` is the whole point of this module and is easy to get wrong,
so it is written out explicitly:

1. **Subscribe first.** From this instant, every newly published event lands in our buffer.
2. **Then** read the replay range from the database.
3. Emit the replay.
4. Emit the buffer, skipping any sequence number the replay already covered.
5. Continue emitting live events.

Doing (2) before (1), which reads more naturally, loses every event published between the
end of the read and the start of the subscription. That window is small, and it is exactly
the window a reconnect after a burst of activity lands in, so it is the case that matters.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from app.events.bus import bus
from app.logging import get_logger

logger = get_logger(__name__)

HEARTBEAT_SECONDS = 15.0
"""Frequency of the keep-alive. Intermediaries drop idle streams, and the frontend uses the
heartbeat as evidence the connection is alive rather than merely open."""


async def stream_from(
    workspace_id: UUID,
    after_seq: int,
    replay_reader: Any,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> AsyncIterator[dict[str, Any]]:
    """Yield event payloads for ``workspace_id``, resuming after ``after_seq``.

    ``replay_reader`` is an awaitable callable ``(workspace_id, after_seq) -> list[payload]``.
    It is injected rather than importing a session here so that this ordering logic can be
    unit tested without a database, which is what makes review finding 8.3 testable at all.
    """
    async with bus.subscribe(workspace_id) as subscriber:
        # Step 1 already happened: subscribing is what the context manager did.
        # Step 2: read what was missed. Anything published from here on is in the queue.
        replayed = await replay_reader(workspace_id, after_seq)

        emitted_max = after_seq
        for payload in replayed:
            emitted_max = max(emitted_max, int(payload.get("seq", 0)))
            yield payload

        # Step 4 and 5: the queue, then live traffic. The `seq <= emitted_max` skip is what
        # makes delivery exactly-once when an event landed in BOTH the replay and the queue.
        while True:
            if subscriber.dropped:
                logger.warning("stream.closing_dropped_subscriber", workspace_id=str(workspace_id))
                return
            try:
                payload = await asyncio.wait_for(
                    subscriber.queue.get(), timeout=heartbeat_seconds
                )
            except TimeoutError:
                yield {"type": "heartbeat", "seq": emitted_max}
                continue

            seq = int(payload.get("seq", 0))
            if seq <= emitted_max:
                continue  # already delivered by the replay
            emitted_max = seq
            yield payload
