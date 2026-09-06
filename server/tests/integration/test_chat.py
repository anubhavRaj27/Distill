"""The chat routes, against a real database.

The interesting cases are the ones that are not the happy path: a conversation that lists
persisted state only, an answer whose generator did not survive a restart, and stopping.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from app.chat import service
from app.chat.buffer import AnswerBuffer, buffers
from app.chat.events import TokenEvent
from app.db.models import ChatMessage
from app.domain.chat import ChatRole, ChatStatus
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _message(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    role: ChatRole = ChatRole.ASSISTANT,
    status: ChatStatus = ChatStatus.DONE,
    content: str = "",
) -> ChatMessage:
    message = ChatMessage(
        workspace_id=workspace_id,
        role=role,
        status=status,
        content=content,
        completed_at=datetime.now(UTC) if status.is_terminal else None,
    )
    db.add(message)
    await db.flush()
    return message


async def test_an_empty_conversation_returns_an_empty_list(
    client: AsyncClient, workspace: tuple[str, str], auth: dict[str, str]
) -> None:
    workspace_id, _ = workspace
    response = await client.get(f"/api/v1/workspaces/{workspace_id}/chat/messages", headers=auth)
    assert response.status_code == 200
    assert response.json()["messages"] == []


async def test_history_is_returned_oldest_first(
    client: AsyncClient,
    db: AsyncSession,
    workspace: tuple[str, str],
    auth: dict[str, str],
) -> None:
    workspace_id, _ = workspace
    await _message(db, uuid.UUID(workspace_id), role=ChatRole.USER, content="first")
    await _message(db, uuid.UUID(workspace_id), content="second")

    response = await client.get(
        f"/api/v1/workspaces/{workspace_id}/chat/messages", headers=auth
    )
    contents = [message["content"] for message in response.json()["messages"]]
    assert contents == ["first", "second"]


async def test_a_streaming_message_has_no_content_yet(
    client: AsyncClient,
    db: AsyncSession,
    workspace: tuple[str, str],
    auth: dict[str, str],
) -> None:
    """Decision D32: while an answer streams, its text lives in the buffer, not the row.
    Persisting every token would turn one question into hundreds of writes."""
    workspace_id, _ = workspace
    await _message(db, uuid.UUID(workspace_id), status=ChatStatus.STREAMING)

    response = await client.get(
        f"/api/v1/workspaces/{workspace_id}/chat/messages", headers=auth
    )
    message = response.json()["messages"][0]
    assert message["status"] == "streaming"
    assert message["content"] == ""


async def test_a_blank_question_is_refused(
    client: AsyncClient, workspace: tuple[str, str], auth: dict[str, str]
) -> None:
    workspace_id, _ = workspace
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/chat/messages",
        headers=auth,
        json={"question": "   \n  "},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_a_message_from_another_workspace_is_not_reachable(
    client: AsyncClient,
    db: AsyncSession,
    workspace: tuple[str, str],
    auth: dict[str, str],
) -> None:
    """The workspace token is the only access control there is (decision D7), so every
    route has to scope by it rather than trusting an identifier in the path."""
    workspace_id, _ = workspace

    # A real second workspace, not a random identifier: chat_messages has a foreign key,
    # so an invented workspace fails on insert rather than testing the scoping.
    from app.db.models import Workspace

    stranger = Workspace(token_hash=uuid.uuid4().hex * 2)
    db.add(stranger)
    await db.flush()
    other = await _message(db, stranger.id)

    response = await client.get(
        f"/api/v1/workspaces/{workspace_id}/chat/messages/{other.id}/stream",
        headers=auth,
    )
    assert response.status_code == 404


async def test_a_stream_for_a_finished_message_replays_it_as_one_done_event(
    client: AsyncClient,
    db: AsyncSession,
    workspace: tuple[str, str],
    auth: dict[str, str],
) -> None:
    """Case 2 of the stream route: the buffer was swept, so the persisted message is the
    record. A late client needs the final state, not an open stream."""
    workspace_id, _ = workspace
    message = await _message(db, uuid.UUID(workspace_id), content="The total is 100 USD.")

    response = await client.get(
        f"/api/v1/workspaces/{workspace_id}/chat/messages/{message.id}/stream",
        headers=auth,
    )
    assert response.status_code == 200
    body = response.text
    assert "event: done" in body
    assert "The total is 100 USD." in body


async def test_a_stream_for_an_orphaned_message_settles_the_row(
    client: AsyncClient,
    db: AsyncSession,
    workspace: tuple[str, str],
    auth: dict[str, str],
) -> None:
    """Case 3, and the one worth having. The row says streaming but no generator exists,
    which means a restart killed it. Leaving it pending would hang the client forever."""
    workspace_id, _ = workspace
    message = await _message(db, uuid.UUID(workspace_id), status=ChatStatus.STREAMING)
    buffers.discard(message.id)

    response = await client.get(
        f"/api/v1/workspaces/{workspace_id}/chat/messages/{message.id}/stream",
        headers=auth,
    )
    assert response.status_code == 200
    assert "event: done" in response.text

    await db.refresh(message)
    assert message.status is ChatStatus.STOPPED


async def test_stopping_a_message_with_no_live_task_settles_it(
    db: AsyncSession, workspace: tuple[str, str]
) -> None:
    """Same restart case, reached through the stop route instead of the stream."""
    workspace_id, _ = workspace
    message = await _message(db, uuid.UUID(workspace_id), status=ChatStatus.STREAMING)

    settled = await service.stop(db, message.id)
    assert settled.status is ChatStatus.STOPPED
    assert settled.completed_at is not None


async def test_stopping_an_already_finished_message_changes_nothing(
    db: AsyncSession, workspace: tuple[str, str]
) -> None:
    workspace_id, _ = workspace
    message = await _message(db, uuid.UUID(workspace_id), content="done already")

    settled = await service.stop(db, message.id)
    assert settled.status is ChatStatus.DONE
    assert settled.content == "done already"


async def test_partial_text_reassembles_only_the_token_events() -> None:
    """What a stopped answer persists. The user read this text, so deleting it would be
    surprising, and a stopped answer has often already said the useful part."""
    buffer = AnswerBuffer(message_id=uuid.uuid4())
    await buffer.append(TokenEvent(text="The total "))
    await buffer.append({"type": "citation", "n": 1})
    await buffer.append(TokenEvent(text="is 100 USD"))

    assert service._partial_text(buffer) == "The total is 100 USD"


async def test_suggestions_are_empty_before_any_schema_exists(
    client: AsyncClient, workspace: tuple[str, str], auth: dict[str, str]
) -> None:
    """A suggestion that returns "not in these documents" is worse than no suggestion,
    because the user trusted it on their first interaction."""
    workspace_id, _ = workspace
    response = await client.get(
        f"/api/v1/workspaces/{workspace_id}/chat/suggestions", headers=auth
    )
    assert response.status_code == 200
    assert response.json()["questions"] == []


async def test_history_turns_are_oldest_first_and_skip_failures(
    db: AsyncSession, workspace: tuple[str, str]
) -> None:
    """Context for follow-up questions (requirement FR-28). A failed turn carries no
    content worth sending, and would spend prompt budget on nothing."""
    workspace_id = uuid.UUID(workspace[0])
    await _message(db, workspace_id, role=ChatRole.USER, content="first question")
    await _message(db, workspace_id, content="first answer")
    await _message(
        db, workspace_id, status=ChatStatus.FAILED, content="broken"
    )

    turns = await service.history_turns(db, workspace_id, limit=4)
    contents = [content for _role, content in turns]
    assert contents == ["first question", "first answer"]
    assert "broken" not in contents


async def test_no_history_is_requested_when_the_limit_is_zero(
    db: AsyncSession, workspace: tuple[str, str]
) -> None:
    workspace_id = uuid.UUID(workspace[0])
    await _message(db, workspace_id, role=ChatRole.USER, content="q")
    assert await service.history_turns(db, workspace_id, limit=0) == []
