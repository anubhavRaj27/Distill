"""Orchestrating one answer, from question to persisted message. Decision D44.

The shape here is the decision: ``ask`` writes the user's message, creates the assistant
message as ``streaming``, spawns a background task, and returns immediately with a stream
URL. The task runs to completion whether or not anyone connects.

That is what makes three separate requirements fall out of one design (FR-29): a closed tab
does not cancel generation, a dropped connection resumes from the buffer, and a refresh
mid-answer finds a row that says "still being written" rather than nothing.

STAGE ORDER IS THE CONTRACT
----------------------------
``retrieving`` → ``sources`` → ``reading`` → ``planning`` → ``visual`` or
``visual_skipped`` → ``answering`` → tokens and citations → ``done``.

The visual always precedes the first token, so the client reserves the card's space before
prose starts moving underneath it (decision D47).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2ui.build import build_surface, result_paths
from app.chat import answer as answer_module
from app.chat.buffer import AnswerBuffer, buffers
from app.chat.citations import resolve_chunk
from app.chat.events import (
    AnswerErrorEvent,
    AnswerStatusEvent,
    DoneEvent,
    SourceRef,
    SourcesEvent,
    VisualEvent,
    VisualSkippedEvent,
)
from app.chat.stream import StreamProcessor
from app.config import Settings
from app.db.models import ChatMessage
from app.db.session import session_scope
from app.domain.chat import AnswerStage, ChatRole, ChatStatus
from app.domain.events import ChatProgressEvent
from app.errors import LLMUnavailable, NotFound
from app.events.bus import bus
from app.insights.evaluate import evaluate
from app.llm.base import LLMClient
from app.logging import current_request_id, get_logger, logging_context
from app.retrieval.search import search
from app.schema import versioning

logger = get_logger(__name__)

_tasks: dict[UUID, asyncio.Task[None]] = {}
"""In-flight generation tasks, so ``stop`` can cancel one. In-process, consistent with the
single-process constraint decision D9 imposes."""


def message_payload(message: ChatMessage) -> dict[str, Any]:
    """The wire shape of a persisted message."""
    return {
        "id": str(message.id),
        "role": message.role.value,
        "status": message.status.value,
        "content": message.content,
        "sources": message.sources or [],
        "citations": message.citations or [],
        "visual": message.visual,
        "surface": message.surface,
        "error": message.error,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "completed_at": (
            message.completed_at.isoformat() if message.completed_at else None
        ),
    }


async def history_turns(
    session: AsyncSession, workspace_id: UUID, limit: int
) -> list[tuple[str, str]]:
    """The last few turns, oldest first, for follow-up questions. Requirement FR-28."""
    if limit <= 0:
        return []
    rows = list(
        (
            await session.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.workspace_id == workspace_id,
                    ChatMessage.status != ChatStatus.FAILED,
                )
                # `id` as a tiebreak so that two messages sharing a timestamp still
                # order deterministically rather than however the scan happened to run.
                .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
                .limit(limit * 2)
            )
        )
        .scalars()
        .all()
    )
    return [
        (message.role.value, message.content)
        for message in reversed(rows)
        if message.content
    ]


async def ask(
    session: AsyncSession,
    workspace_id: UUID,
    question: str,
    *,
    client: LLMClient,
    settings: Settings,
) -> tuple[ChatMessage, ChatMessage]:
    """Persist the question, create the pending answer, and start generating.

    Returns ``(user_message, assistant_message)``. The caller returns 202 with the stream
    URL; nothing here waits on the model.
    """
    user_message = ChatMessage(
        workspace_id=workspace_id,
        role=ChatRole.USER,
        status=ChatStatus.DONE,
        content=question.strip(),
        completed_at=datetime.now(UTC),
    )
    assistant_message = ChatMessage(
        workspace_id=workspace_id,
        role=ChatRole.ASSISTANT,
        status=ChatStatus.STREAMING,
        content="",
    )
    session.add_all([user_message, assistant_message])
    await session.flush()

    buffers.create(assistant_message.id)
    await bus.publish(
        session,
        workspace_id,
        ChatProgressEvent(
            seq=0, message_id=assistant_message.id, stage="retrieving"
        ),
    )

    # Captured now, because the request context is gone by the time the task runs and the
    # correlation identifier is what ties the task's logs to the question that started it.
    request_id = current_request_id()
    question_text = user_message.content
    message_id = assistant_message.id

    async def runner() -> None:
        with logging_context(request_id=request_id, workspace_id=str(workspace_id)):
            await _generate(
                workspace_id=workspace_id,
                message_id=message_id,
                question=question_text,
                client=client,
                settings=settings,
            )

    # Started after the response is sent, not inline: the route must return within
    # milliseconds so the client can open the stream and see "retrieving" immediately.
    task = asyncio.create_task(runner(), name=f"answer-{message_id}")
    _tasks[message_id] = task
    task.add_done_callback(lambda _: _tasks.pop(message_id, None))

    logger.info("chat.asked", message_id=str(message_id), question=question_text[:120])
    return user_message, assistant_message


async def _generate(
    *,
    workspace_id: UUID,
    message_id: UUID,
    question: str,
    client: LLMClient,
    settings: Settings,
) -> None:
    """The background task. Writes events into the buffer and persists the result."""
    buffer = buffers.get(message_id)
    if buffer is None:  # pragma: no cover - created by `ask` immediately before
        return

    try:
        # -- retrieve
        await buffer.append(AnswerStatusEvent(stage=AnswerStage.RETRIEVING))
        async with session_scope() as session:
            fields = await versioning.current_fields(session, workspace_id)
            passages = await search(
                session, workspace_id, question, client=client, settings=settings
            )
            history = await history_turns(
                session, workspace_id, settings.chat_history_turns
            )
            sources = [
                SourceRef(
                    chunk_id=passage.chunk_id,
                    document_id=passage.document_id,
                    filename=passage.filename,
                    page_index=passage.page_index,
                    is_digest=passage.is_digest,
                )
                for passage in passages
            ]

        await buffer.append(SourcesEvent(sources=sources))
        document_count = len({source.document_id for source in sources})
        await buffer.append(
            AnswerStatusEvent(
                stage=AnswerStage.READING,
                detail=(
                    f"{len(sources)} passages from {document_count} documents"
                    if sources
                    else "no relevant passages found"
                ),
            )
        )

        # -- plan
        await buffer.append(AnswerStatusEvent(stage=AnswerStage.PLANNING))
        plan = await answer_module.plan_answer(
            question=question,
            passages=passages,
            fields=fields,
            history=history,
            client=client,
            settings=settings,
            fixture_key=f"plan-{message_id.hex[:12]}",
        )

        # -- evaluate and build the visual, BEFORE any prose (decision D47)
        evaluated = None
        surface: list[dict[str, Any]] | None = None
        visual_kind = None
        if plan.visual is None:
            await buffer.append(VisualSkippedEvent(reason="none_planned"))
        else:
            try:
                async with session_scope() as session:
                    evaluated = await evaluate(
                        session, workspace_id, plan.visual.query, fields=fields
                    )
            except Exception as exc:
                logger.warning(
                    "chat.visual_evaluation_failed", error=type(exc).__name__
                )
                await buffer.append(VisualSkippedEvent(reason="evaluation_failed"))
                evaluated = None
            else:
                if evaluated.is_empty:
                    await buffer.append(VisualSkippedEvent(reason="empty_result"))
                    evaluated = None
                else:
                    surface, visual_kind = build_surface(plan.visual, evaluated)
                    await buffer.append(
                        VisualEvent(
                            kind=visual_kind,
                            title=plan.visual.title,
                            surface=surface,
                        )
                    )

        # -- answer
        await buffer.append(AnswerStatusEvent(stage=AnswerStage.ANSWERING))

        async def resolver(chunk_id: UUID) -> Any:
            async with session_scope() as session:
                return await resolve_chunk(session, chunk_id)

        processor = StreamProcessor(
            resolve_citation=resolver,
            result_paths=(
                result_paths(evaluated, plan.visual.unit_hint if plan.visual else None)
                if evaluated
                else {}
            ),
            coalesce_ms=settings.chat_token_coalesce_ms,
        )

        deltas = answer_module.stream_answer(
            question=question,
            passages=passages,
            fields=fields,
            history=history,
            plan=plan,
            result=evaluated,
            client=client,
            settings=settings,
            fixture_key=f"answer-{message_id.hex[:12]}",
        )
        async for delta in deltas:
            async for event in processor.feed(delta):
                await buffer.append(event)
        async for event in processor.flush():
            await buffer.append(event)

        await _finish(
            workspace_id=workspace_id,
            message_id=message_id,
            buffer=buffer,
            status=ChatStatus.DONE,
            content=processor.text,
            sources=[source.model_dump(mode="json") for source in sources],
            citations=processor.citations,
            visual=plan.visual.model_dump(mode="json") if plan.visual else None,
            surface=surface,
        )

    except asyncio.CancelledError:
        # The user pressed stop. What streamed is kept: they read it, so deleting it would
        # be surprising, and it may well have answered them.
        logger.info("chat.stopped", message_id=str(message_id))
        await _finish(
            workspace_id=workspace_id,
            message_id=message_id,
            buffer=buffer,
            status=ChatStatus.STOPPED,
            content=_partial_text(buffer),
        )
        raise
    except LLMUnavailable as exc:
        await _fail(workspace_id, message_id, buffer, exc.message)
    except Exception as exc:
        logger.exception("chat.generation_failed", error_type=type(exc).__name__)
        await _fail(
            workspace_id,
            message_id,
            buffer,
            "Something went wrong while answering. Your documents are unaffected.",
        )


def _partial_text(buffer: AnswerBuffer) -> str:
    """Reassemble what has been streamed, for a stopped answer."""
    return "".join(
        str(entry.payload.get("text", ""))
        for entry in buffer.events
        if entry.payload.get("type") == "token"
    )


async def _finish(
    *,
    workspace_id: UUID,
    message_id: UUID,
    buffer: AnswerBuffer,
    status: ChatStatus,
    content: str,
    sources: list[dict[str, Any]] | None = None,
    citations: list[dict[str, Any]] | None = None,
    visual: dict[str, Any] | None = None,
    surface: list[dict[str, Any]] | None = None,
) -> None:
    """Persist the message, emit ``done``, and close the buffer."""
    async with session_scope() as session:
        message = await session.get(ChatMessage, message_id)
        if message is None:  # pragma: no cover - deleted mid-answer
            await buffer.close()
            return
        message.status = status
        message.content = content
        message.completed_at = datetime.now(UTC)
        if sources is not None:
            message.sources = sources
        if citations is not None:
            message.citations = citations
        if visual is not None:
            message.visual = visual
        if surface is not None:
            message.surface = surface
        await session.flush()
        payload = message_payload(message)

        await bus.publish(
            session,
            workspace_id,
            ChatProgressEvent(
                seq=0,
                message_id=message_id,
                stage="done" if status is ChatStatus.DONE else "failed",
            ),
        )

    await buffer.append(
        AnswerStatusEvent(
            stage=AnswerStage.DONE if status is ChatStatus.DONE else AnswerStage.STOPPED
        )
    )
    await buffer.append(DoneEvent(message=payload))
    await buffer.close()
    logger.info(
        "chat.finished",
        message_id=str(message_id),
        status=status.value,
        characters=len(content),
        citations=len(citations or []),
    )


async def _fail(
    workspace_id: UUID, message_id: UUID, buffer: AnswerBuffer, reason: str
) -> None:
    async with session_scope() as session:
        message = await session.get(ChatMessage, message_id)
        if message is not None:
            message.status = ChatStatus.FAILED
            message.error = reason
            message.content = _partial_text(buffer)
            message.completed_at = datetime.now(UTC)
            await session.flush()
        await bus.publish(
            session,
            workspace_id,
            ChatProgressEvent(seq=0, message_id=message_id, stage="failed"),
        )
    await buffer.append(AnswerStatusEvent(stage=AnswerStage.FAILED, detail=reason))
    await buffer.append(
        AnswerErrorEvent(message=reason, correlation_id=current_request_id())
    )
    await buffer.close()


async def stop(session: AsyncSession, message_id: UUID) -> ChatMessage:
    """Cancel generation. What has streamed is persisted with ``status = stopped``."""
    message = await session.get(ChatMessage, message_id)
    if message is None:
        raise NotFound("That message does not exist.")

    task = _tasks.get(message_id)
    if task is not None and not task.done():
        task.cancel()
        # The task persists its own partial answer in its cancellation handler, which is
        # the only place that knows what actually reached the user.
        return message

    if message.status is ChatStatus.STREAMING:
        # No task, but the row says streaming: a restart killed the generator. Settle the
        # row rather than leaving it pending forever.
        message.status = ChatStatus.STOPPED
        message.completed_at = datetime.now(UTC)
        await session.flush()
    return message
