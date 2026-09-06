"""The conversation: history, asking, streaming an answer, stopping, and suggestions.

The interesting route is the stream. It has three cases, and getting the third right is what
makes requirement FR-29 true rather than nearly true:

1. **A live buffer exists** — tail it from ``Last-Event-ID``. Normal streaming and normal
   reconnection are the same code path.
2. **No buffer, and the message is terminal** — the answer finished and its buffer was
   swept. Replay the persisted message as a single ``done`` event, which is exactly what a
   late client needs to render the final state.
3. **No buffer, and the message still says streaming** — the process restarted mid-answer.
   The generator is gone and will not come back, so the row is settled and reported rather
   than left as a stream that hangs until the client gives up.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Path, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from app.chat import service
from app.chat.buffer import buffers
from app.chat.events import AnswerStatusEvent, DoneEvent
from app.chat.suggestions import suggest
from app.db.models import ChatMessage
from app.deps import Config, CurrentWorkspace, Session
from app.domain.chat import AnswerStage, ChatStatus
from app.errors import NotFound
from app.insights.stats import field_statistics
from app.llm.registry import get_client
from app.logging import get_logger
from app.routers.events import STREAM_HEADERS, parse_last_event_id
from app.schema import versioning

router = APIRouter(prefix="/workspaces/{workspace_id}/chat", tags=["chat"])
logger = get_logger(__name__)

MAX_QUESTION_LENGTH = 2000
HEARTBEAT_SECONDS = 15


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("A question cannot be only whitespace.")
        return cleaned


class MessageResponse(BaseModel):
    id: UUID
    role: str
    status: str
    content: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    visual: dict[str, Any] | None = None
    surface: list[dict[str, Any]] | None = None
    error: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


class MessageList(BaseModel):
    messages: list[MessageResponse]


class AskResponse(BaseModel):
    """202. Generation has started; the answer arrives on the stream."""

    user_message: MessageResponse
    message_id: UUID
    stream_url: str = Field(
        description="Where to read the answer. Given rather than constructed by the client "
        "so the route can move without breaking it."
    )


@router.get("/messages", response_model=MessageList, summary="Conversation history")
async def list_messages(workspace: CurrentWorkspace, session: Session) -> MessageList:
    """Persisted state only. A streaming answer's text lives in its buffer until it
    finishes, so a message here that says ``streaming`` has empty content on purpose: the
    client opens its stream to get the rest."""
    rows = list(
        (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.workspace_id == workspace.id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        )
        .scalars()
        .all()
    )
    return MessageList(
        messages=[
            MessageResponse.model_validate(service.message_payload(row)) for row in rows
        ]
    )


@router.post(
    "/messages",
    response_model=AskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask a question",
)
async def ask(
    workspace: CurrentWorkspace,
    session: Session,
    settings: Config,
    body: AskRequest,
) -> AskResponse:
    user_message, assistant_message = await service.ask(
        session,
        workspace.id,
        body.question,
        client=get_client(),
        settings=settings,
    )
    return AskResponse(
        user_message=MessageResponse.model_validate(service.message_payload(user_message)),
        message_id=assistant_message.id,
        stream_url=(
            f"{settings.api_prefix}/workspaces/{workspace.id}"
            f"/chat/messages/{assistant_message.id}/stream"
        ),
    )


async def _require_message(
    session: Session, workspace_id: UUID, message_id: UUID
) -> ChatMessage:
    message = (
        await session.execute(
            select(ChatMessage).where(
                ChatMessage.id == message_id,
                ChatMessage.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if message is None:
        raise NotFound("That message is not in this workspace.")
    return message


@router.get(
    "/messages/{message_id}/stream",
    summary="The answer, streamed (Server-Sent Events)",
)
async def stream(
    workspace: CurrentWorkspace,
    session: Session,
    message_id: Annotated[UUID, Path()],
    request: Request,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> EventSourceResponse:
    message = await _require_message(session, workspace.id, message_id)
    after = parse_last_event_id(last_event_id)
    buffer = buffers.get(message_id)

    # Case 2 and 3: no live buffer. Resolved here, synchronously, so the client gets a
    # complete answer in one event instead of an open stream that never produces anything.
    if buffer is None:
        if message.status is ChatStatus.STREAMING:
            logger.warning(
                "chat.stream_orphaned",
                message_id=str(message_id),
                detail="the generating task did not survive a restart",
            )
            message.status = ChatStatus.STOPPED
            await session.flush()
        payload = service.message_payload(message)
        final = [
            {
                "id": "1",
                "event": "status",
                "data": json.dumps(
                    AnswerStatusEvent(
                        stage=(
                            AnswerStage.DONE
                            if message.status is ChatStatus.DONE
                            else AnswerStage.STOPPED
                        )
                    ).model_dump(mode="json")
                ),
            },
            {
                "id": "2",
                "event": "done",
                "data": json.dumps(DoneEvent(message=payload).model_dump(mode="json")),
            },
        ]

        async def replay() -> AsyncIterator[dict[str, str]]:
            for event in final:
                yield event

        return EventSourceResponse(replay(), headers=STREAM_HEADERS)

    async def publisher() -> AsyncIterator[dict[str, str]]:
        logger.info(
            "chat.stream_opened", message_id=str(message_id), resume_after=after
        )
        try:
            async for entry in buffer.follow(after):
                if await request.is_disconnected():
                    break
                yield {
                    # The sequence number IS the event id, so the browser sends it back as
                    # Last-Event-ID on reconnect with no client code involved.
                    "id": str(entry.seq),
                    "event": str(entry.payload.get("type", "message")),
                    "data": json.dumps(entry.payload),
                }
        finally:
            logger.info("chat.stream_closed", message_id=str(message_id))

    return EventSourceResponse(
        publisher(), headers=STREAM_HEADERS, ping=HEARTBEAT_SECONDS
    )


@router.post(
    "/messages/{message_id}/stop",
    response_model=MessageResponse,
    summary="Stop a streaming answer",
)
async def stop(
    workspace: CurrentWorkspace,
    session: Session,
    message_id: Annotated[UUID, Path()],
) -> MessageResponse:
    """Cancel generation. What already streamed is kept.

    Keeping the partial text is deliberate: the user read it, so deleting it would be
    surprising, and a stopped answer has often already said the useful part.
    """
    await _require_message(session, workspace.id, message_id)
    message = await service.stop(session, message_id)
    return MessageResponse.model_validate(service.message_payload(message))


class SuggestionsResponse(BaseModel):
    questions: list[str] = Field(default_factory=list)


@router.get(
    "/suggestions", response_model=SuggestionsResponse, summary="Suggested questions"
)
async def suggestions(
    workspace: CurrentWorkspace, session: Session, settings: Config
) -> SuggestionsResponse:
    fields = await versioning.current_fields(session, workspace.id)
    if not fields:
        return SuggestionsResponse(questions=[])

    stats = await field_statistics(session, workspace.id, fields)
    document_count = stats[0].total_records if stats else 0
    questions = await suggest(
        session,
        workspace.id,
        fields=fields,
        document_count=document_count,
        stats=stats,
        client=get_client(),
        settings=settings,
    )
    return SuggestionsResponse(questions=questions)
