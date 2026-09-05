"""The event bus and the resumable stream. Decision D14 and review finding 8.3.

Two of these are regression tests for bugs that reached a running server, and both were
invisible to the rest of the suite because nothing had opened a stream yet:

* ``_Subscriber`` was a plain dataclass, so it was unhashable and could not enter the
  registry ``set``. Every stream failed on connect while still returning valid
  ``text/event-stream`` headers, so the symptom was a stream that connected and then
  delivered nothing at all.
* the worker was handed document identifiers before the upload transaction committed, so
  consumers looked for rows that did not exist yet and silently dropped the work.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from app.events.bus import SUBSCRIBER_QUEUE_LIMIT, EventBus, _Subscriber
from app.events.stream import stream_from


def test_a_subscriber_can_go_in_a_set() -> None:
    """Regression. A plain ``@dataclass`` generates ``__eq__``, which sets ``__hash__`` to
    None, and the registry is a set. This failed every event stream on connect."""
    first, second = _Subscriber(), _Subscriber()
    registry = {first, second}
    assert len(registry) == 2, "two subscribers are two tabs, even with equal contents"
    assert hash(first) != hash(second)


async def test_subscribe_registers_and_deregisters() -> None:
    bus = EventBus()
    workspace = uuid4()
    assert bus.subscriber_count(workspace) == 0
    async with bus.subscribe(workspace):
        assert bus.subscriber_count(workspace) == 1
    assert bus.subscriber_count(workspace) == 0


async def test_a_subscriber_receives_a_delivered_event() -> None:
    bus = EventBus()
    workspace = uuid4()
    async with bus.subscribe(workspace) as subscriber:
        bus._deliver(workspace, {"seq": 1, "type": "heartbeat"})
        assert subscriber.queue.get_nowait()["seq"] == 1


async def test_a_subscriber_that_stops_reading_is_dropped_rather_than_leaking() -> None:
    """A subscriber that stops reading is a browser tab that went away. Holding events for
    it forever would be a memory leak; dropping it is safe because reconnecting replays."""
    bus = EventBus()
    workspace = uuid4()
    async with bus.subscribe(workspace) as subscriber:
        for index in range(SUBSCRIBER_QUEUE_LIMIT + 5):
            bus._deliver(workspace, {"seq": index, "type": "heartbeat"})
        assert subscriber.dropped is True


# ---------------------------------------------------------------------------
# Review finding 8.3: exactly-once delivery across a reconnect
# ---------------------------------------------------------------------------


async def _collect(
    generator: Any, count: int, deadline_seconds: float = 2.0
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []

    async def pump() -> None:
        async for payload in generator:
            if payload.get("type") == "heartbeat":
                continue
            collected.append(payload)
            if len(collected) >= count:
                return

    await asyncio.wait_for(pump(), timeout=deadline_seconds)
    return collected


async def test_replayed_events_are_delivered_in_order() -> None:
    workspace = uuid4()
    history = [{"seq": seq, "type": "document.status"} for seq in (1, 2, 3)]

    async def replay(_workspace: Any, after: int) -> list[dict[str, Any]]:
        return [event for event in history if event["seq"] > after]

    stream = stream_from(workspace, 0, replay, heartbeat_seconds=5.0)
    assert [event["seq"] for event in await _collect(stream, 3)] == [1, 2, 3]


async def test_resume_skips_what_the_client_already_has() -> None:
    workspace = uuid4()
    history = [{"seq": seq, "type": "document.status"} for seq in (1, 2, 3, 4, 5)]

    async def replay(_workspace: Any, after: int) -> list[dict[str, Any]]:
        return [event for event in history if event["seq"] > after]

    stream = stream_from(workspace, 3, replay, heartbeat_seconds=5.0)
    assert [event["seq"] for event in await _collect(stream, 2)] == [4, 5]


async def test_an_event_published_during_the_replay_read_is_not_lost() -> None:
    """THE finding-8.3 test.

    The naive order, "read what was missed, then start listening", loses anything published
    between those two steps. Here the replay reader publishes while it is running, which is
    exactly that window, and the event must still arrive.
    """
    from app.events.bus import bus as global_bus

    workspace = uuid4()
    history = [{"seq": 1, "type": "document.status"}]

    async def replay_and_publish(_workspace: Any, after: int) -> list[dict[str, Any]]:
        # Published while the replay is in flight. Because `stream_from` subscribed FIRST,
        # this lands in the live buffer rather than falling through the gap.
        global_bus._deliver(workspace, {"seq": 2, "type": "record.upsert"})
        return [event for event in history if event["seq"] > after]

    stream = stream_from(workspace, 0, replay_and_publish, heartbeat_seconds=5.0)
    assert [event["seq"] for event in await _collect(stream, 2)] == [1, 2]


async def test_an_event_in_both_the_replay_and_the_live_queue_is_delivered_once() -> None:
    """The other half of exactly-once. Overlap is expected, duplication is not."""
    from app.events.bus import bus as global_bus

    workspace = uuid4()

    async def replay_with_overlap(_workspace: Any, after: int) -> list[dict[str, Any]]:
        # seq 1 is in the log AND gets delivered live, which is what happens when a publish
        # commits just as a client reconnects.
        global_bus._deliver(workspace, {"seq": 1, "type": "document.status"})
        global_bus._deliver(workspace, {"seq": 2, "type": "record.upsert"})
        return [{"seq": 1, "type": "document.status"}]

    stream = stream_from(workspace, 0, replay_with_overlap, heartbeat_seconds=5.0)
    received = await _collect(stream, 2)
    assert [event["seq"] for event in received] == [1, 2]
    assert len({event["seq"] for event in received}) == 2, "seq 1 must not arrive twice"


async def test_an_idle_stream_emits_a_heartbeat() -> None:
    """Intermediaries drop idle streams, and the interface uses the heartbeat as evidence
    the connection is alive rather than merely open."""
    workspace = uuid4()

    async def replay(_workspace: Any, _after: int) -> list[dict[str, Any]]:
        return []

    stream = stream_from(workspace, 0, replay, heartbeat_seconds=0.05)
    first = await asyncio.wait_for(anext(stream), timeout=2.0)
    assert first["type"] == "heartbeat"


# ---------------------------------------------------------------------------
# Worker submission ordering
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.info: dict[str, Any] = {}


def test_submissions_are_staged_not_queued_immediately() -> None:
    """Regression. Queueing inside the transaction let consumers load a row that had not
    been committed, so five of six uploads were silently dropped."""
    from app.pipeline.worker import _SESSION_KEY, submit_after_commit

    session = _FakeSession()
    first, second = uuid4(), uuid4()
    submit_after_commit(session, first)
    submit_after_commit(session, second)
    assert session.info[_SESSION_KEY] == [first, second]


def test_discarding_staged_submissions_leaves_nothing_queued() -> None:
    """A rolled-back upload must not be processed."""
    from app.pipeline.worker import _SESSION_KEY, discard_submissions, submit_after_commit

    session = _FakeSession()
    submit_after_commit(session, uuid4())
    discard_submissions(session)
    assert session.info.get(_SESSION_KEY) in (None, [])


async def test_flushing_submissions_queues_them_on_the_worker() -> None:
    import tempfile
    from pathlib import Path

    from app.config import Settings
    from app.llm.fake import FakeClient
    from app.pipeline import worker as worker_module
    from app.storage.local import LocalStorage

    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(llm_provider="fake")
        instance = worker_module.init_worker(
            settings=settings,
            client=FakeClient(settings),
            storage=LocalStorage(Path(directory)),
        )
        try:
            session = _FakeSession()
            worker_module.submit_after_commit(session, uuid4())
            worker_module.submit_after_commit(session, uuid4())
            assert instance.depth == 0, "nothing queued before the commit"

            worker_module.flush_submissions(session)
            assert instance.depth == 2, "both queued after the commit"
        finally:
            worker_module.reset_worker()


@pytest.mark.parametrize(
    ("reason", "retryable"),
    [
        ("We are being rate limited by the model provider. Please try again shortly.", True),
        ("The model did not respond in time. This usually clears up on a retry.", True),
        (
            "We could not read this file: it appears to be password protected. "
            "Remove the password and upload it again.",
            False,
        ),
        ("This Word document appears to be empty.", False),
        (None, False),
    ],
)
def test_only_transient_failures_are_retried(reason: str | None, retryable: bool) -> None:
    """Retrying a password-protected file three times wastes the user's time and then
    reports the same thing. Retrying a rate limit usually works."""
    from app.pipeline.worker import _is_retryable

    assert _is_retryable(reason) is retryable


# ---------------------------------------------------------------------------
# Background sessions deliver what they stage. Decision D70.
# ---------------------------------------------------------------------------


class _FakeAsyncSession:
    """Enough of an AsyncSession for ``session_scope``: info, commit, rollback."""

    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def __aenter__(self) -> _FakeAsyncSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


def _install_fake_sessionmaker(monkeypatch: Any, session: _FakeAsyncSession) -> None:
    from app.db import session as session_module

    monkeypatch.setattr(session_module, "get_sessionmaker", lambda: lambda: session)


async def test_a_background_session_delivers_the_events_it_staged(
    monkeypatch: Any,
) -> None:
    """Regression, and the one that cost the demo its opening minute.

    Document processing runs entirely in ``session_scope``, which committed without ever
    flushing the bus. Every pipeline event reached ``workspace_events`` and no live
    subscriber, so the progress strip showed the upload request's own event and then sat
    still for the whole run while the work actually finished. A refresh looked fine, because
    a refresh replays from the table, which is what kept it hidden.
    """
    from app.db.session import session_scope
    from app.events.bus import _SESSION_KEY, bus

    workspace = uuid4()
    fake = _FakeAsyncSession()
    _install_fake_sessionmaker(monkeypatch, fake)

    async with bus.subscribe(workspace) as subscriber:
        async with session_scope() as session:
            session.info.setdefault(_SESSION_KEY, []).append(
                (workspace, {"seq": 7, "type": "document.status", "status": "done"})
            )
            assert subscriber.queue.empty(), "nothing may be delivered before the commit"

        assert fake.committed
        assert subscriber.queue.get_nowait()["seq"] == 7


async def test_a_background_session_that_fails_delivers_nothing(monkeypatch: Any) -> None:
    """The other half, and the reason delivery waits for the commit at all: an event about
    a row that was rolled back is a lie no later message can correct."""
    from app.db.session import session_scope
    from app.events.bus import _SESSION_KEY, bus

    workspace = uuid4()
    fake = _FakeAsyncSession()
    _install_fake_sessionmaker(monkeypatch, fake)

    async with bus.subscribe(workspace) as subscriber:
        with pytest.raises(RuntimeError):
            async with session_scope() as session:
                session.info.setdefault(_SESSION_KEY, []).append(
                    (workspace, {"seq": 8, "type": "document.status"})
                )
                raise RuntimeError("the transaction failed")

        assert fake.rolled_back
        assert subscriber.queue.empty()
        assert not fake.info.get(_SESSION_KEY), "staged events must not survive a rollback"
