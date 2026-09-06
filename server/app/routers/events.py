"""The workspace event stream. Requirement FR-04, decision D12, review finding 8.3.

Server-Sent Events rather than WebSockets (decision D6): the traffic is one-directional,
and resumption after a dropped connection comes free through ``Last-Event-ID``.

FOUR THINGS HERE EXIST TO STOP STREAMING FROM SILENTLY NOT STREAMING
---------------------------------------------------------------------
This is the part of the system most likely to look broken while being technically correct,
so each mitigation is deliberate:

* ``X-Accel-Buffering: no`` tells a reverse proxy not to buffer the response. Without it,
  nginx holds the whole stream and delivers it when the connection closes, which looks
  exactly like a backend that produced nothing for a minute and then everything at once.
* Compression is bypassed for this path in ``app.middleware``, for the same reason: a
  compressor has to buffer in order to compress.
* A heartbeat every 15 seconds keeps intermediaries from timing out an idle stream, and
  gives the interface positive evidence the connection is alive rather than merely open.
* The database session is released before the long-lived generator starts. Holding a
  pooled connection for the life of an event stream would exhaust the pool with a handful
  of open browser tabs, which is a failure that only appears once more than one person
  looks at the product.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Request
from sse_starlette.sse import EventSourceResponse

from app.db.session import session_scope
from app.deps import CurrentWorkspace
from app.events.bus import bus
from app.events.stream import HEARTBEAT_SECONDS, stream_from
from app.logging import get_logger

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["events"])
logger = get_logger(__name__)

STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def parse_last_event_id(raw: str | None) -> int:
    """The sequence number a client already has, or 0.

    Tolerant on purpose: a malformed header means "start from the beginning", which is
    always safe because every event is idempotent when applied to the interface's cache.
    """
    if not raw:
        return 0
    try:
        return max(0, int(raw.strip()))
    except (TypeError, ValueError):
        logger.info("events.bad_last_event_id", value=raw[:40])
        return 0


@router.get("/events", summary="Live workspace events (Server-Sent Events)")
async def events(
    workspace: CurrentWorkspace,
    request: Request,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    workspace_id: UUID = workspace.id
    after = parse_last_event_id(last_event_id)

    async def replay_reader(target: UUID, after_seq: int) -> list[dict[str, Any]]:
        """Read the missed range in its own short-lived session."""
        async with session_scope() as session:
            return await bus.replay(session, target, after_seq)

    async def publisher() -> AsyncIterator[dict[str, str]]:
        logger.info(
            "events.stream_opened", workspace_id=str(workspace_id), resume_after=after
        )
        try:
            async for payload in stream_from(
                workspace_id, after, replay_reader, heartbeat_seconds=HEARTBEAT_SECONDS
            ):
                if await request.is_disconnected():
                    break
                yield {
                    # The event id IS the sequence number, which is what makes the browser
                    # send it back as Last-Event-ID on reconnect without any client code.
                    "id": str(payload.get("seq", "")),
                    "event": str(payload.get("type", "message")),
                    "data": json.dumps(payload),
                }
        finally:
            logger.info("events.stream_closed", workspace_id=str(workspace_id))

    return EventSourceResponse(
        publisher(),
        headers=STREAM_HEADERS,
        ping=int(HEARTBEAT_SECONDS),
    )
