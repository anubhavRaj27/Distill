"""The answer buffer and the stream processor. Decisions D32, D33, D34.

These two carry the streaming contract, and both fail in ways a user sees directly: a
buffer bug loses an answer, and a processor bug shows raw markers or an unresolved
placeholder in the middle of prose.

The processor tests deliberately feed text at hostile boundaries, including one character
at a time, because deltas arrive wherever the provider chooses to split them and a marker
can be cut anywhere.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from app.chat.buffer import MAX_BUFFERED_EVENTS, AnswerBuffer, BufferRegistry
from app.chat.citations import ResolvedCitation
from app.chat.events import AnswerStatusEvent, CitationEvent, TokenEvent
from app.chat.stream import StreamProcessor, format_figure
from app.domain.chat import AnswerStage
from app.domain.geometry import BBox

CHUNK_A = UUID("11111111-1111-1111-1111-111111111111")
CHUNK_B = UUID("22222222-2222-2222-2222-222222222222")


async def _resolver(chunk_id: UUID) -> ResolvedCitation | None:
    if chunk_id not in (CHUNK_A, CHUNK_B):
        return None
    return ResolvedCitation(
        chunk_id=chunk_id,
        document_id=uuid4(),
        filename="invoice.pdf",
        page_index=0,
        boxes=[BBox(x0=10, top=10, x1=50, bottom=22)],
        excerpt="Total Due: $12,480.50",
    )


async def _run(
    deltas: list[str],
    paths: dict[str, tuple[object, str | None]] | None = None,
) -> tuple[StreamProcessor, list[object]]:
    processor = StreamProcessor(
        resolve_citation=_resolver, result_paths=paths or {}, coalesce_ms=0
    )
    events: list[object] = []
    for delta in deltas:
        async for event in processor.feed(delta):
            events.append(event)
    async for event in processor.flush():
        events.append(event)
    return processor, events


# ---------------------------------------------------------------------------
# The buffer
# ---------------------------------------------------------------------------


async def test_a_follower_attached_before_anything_is_written_sees_everything() -> None:
    buffer = AnswerBuffer(message_id=uuid4())
    seen: list[str] = []

    async def follow() -> None:
        async for entry in buffer.follow(0):
            seen.append(str(entry.payload.get("type")))

    task = asyncio.create_task(follow())
    await asyncio.sleep(0)
    await buffer.append(AnswerStatusEvent(stage=AnswerStage.RETRIEVING))
    await buffer.append(TokenEvent(text="hello"))
    await buffer.close()
    await asyncio.wait_for(task, timeout=2)

    assert seen == ["status", "token"]


async def test_a_follower_attached_after_completion_replays_everything() -> None:
    """Generation does not wait for a listener (decision D32), so a client that connects
    late must still get the whole answer."""
    buffer = AnswerBuffer(message_id=uuid4())
    await buffer.append(TokenEvent(text="one"))
    await buffer.append(TokenEvent(text="two"))
    await buffer.close()

    replayed = [entry.seq async for entry in buffer.follow(0)]
    assert replayed == [1, 2]


async def test_resuming_from_a_sequence_number_skips_what_was_seen() -> None:
    buffer = AnswerBuffer(message_id=uuid4())
    for index in range(5):
        await buffer.append(TokenEvent(text=str(index)))
    await buffer.close()

    assert [entry.seq async for entry in buffer.follow(3)] == [4, 5]


async def test_a_follower_attached_mid_flight_loses_nothing() -> None:
    """Replay and live delivery are one loop, so there is no window between reading the
    log and subscribing to it."""
    buffer = AnswerBuffer(message_id=uuid4())
    await buffer.append(TokenEvent(text="before"))

    seen: list[str] = []

    async def follow() -> None:
        async for entry in buffer.follow(0):
            seen.append(str(entry.payload.get("text")))

    task = asyncio.create_task(follow())
    await asyncio.sleep(0)
    await buffer.append(TokenEvent(text="after"))
    await buffer.close()
    await asyncio.wait_for(task, timeout=2)

    assert seen == ["before", "after"]


async def test_sequence_numbers_start_at_one_and_are_contiguous() -> None:
    """They become Server-Sent Events ids, which the browser returns as Last-Event-ID."""
    buffer = AnswerBuffer(message_id=uuid4())
    for _ in range(4):
        await buffer.append(TokenEvent(text="x"))
    assert [entry.seq for entry in buffer.events] == [1, 2, 3, 4]


async def test_appending_after_close_is_refused_rather_than_corrupting_the_log() -> None:
    buffer = AnswerBuffer(message_id=uuid4())
    await buffer.append(TokenEvent(text="x"))
    await buffer.close()
    await buffer.append(TokenEvent(text="y"))
    assert len(buffer.events) == 1


async def test_the_buffer_is_bounded() -> None:
    """A model that streams forever is a bug; an unbounded buffer would make it a leak."""
    buffer = AnswerBuffer(message_id=uuid4())
    for _ in range(MAX_BUFFERED_EVENTS + 10):
        await buffer.append(TokenEvent(text="x"))
    assert len(buffer.events) == MAX_BUFFERED_EVENTS
    assert buffer.overflowed


def test_only_closed_buffers_are_swept() -> None:
    """Sweeping an in-flight answer would strand the client mid-stream."""
    registry = BufferRegistry()
    live = registry.create(uuid4())
    assert registry.sweep(0.0) == 0
    assert registry.size == 1
    assert live is registry.get(live.message_id)


async def test_a_closed_buffer_is_swept_after_its_grace_period() -> None:
    registry = BufferRegistry()
    buffer = registry.create(uuid4())
    await buffer.close()
    assert registry.sweep(0.0) == 1
    assert registry.size == 0


# ---------------------------------------------------------------------------
# Markers, at hostile boundaries
# ---------------------------------------------------------------------------


async def test_a_marker_split_across_three_deltas_still_resolves() -> None:
    processor, _events = await _run(
        ["Acme is top ", "[", f"^chunk:{CHUNK_A}", "]", " overall."]
    )
    assert processor.text == "Acme is top [^1] overall."
    assert len(processor.citations) == 1


async def test_a_marker_split_one_character_at_a_time_still_resolves() -> None:
    answer = f"Acme leads [^chunk:{CHUNK_A}]. Done."
    processor, _ = await _run(list(answer))
    assert processor.text == "Acme leads [^1]. Done."


async def test_the_citation_arrives_before_the_token_that_references_it() -> None:
    """Decision D33. The client must never render an unresolved footnote."""
    _, events = await _run([f"Claim [^chunk:{CHUNK_A}] here."])
    kinds = [type(event).__name__ for event in events]
    citation_at = kinds.index("CitationEvent")
    marker_at = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, TokenEvent) and "[^1]" in event.text
    )
    assert citation_at < marker_at


async def test_a_repeated_citation_reuses_its_number_and_emits_once() -> None:
    processor, events = await _run(
        [f"First [^chunk:{CHUNK_A}] then again [^chunk:{CHUNK_A}]."]
    )
    assert processor.text == "First [^1] then again [^1]."
    assert sum(1 for event in events if isinstance(event, CitationEvent)) == 1


async def test_two_different_chunks_get_consecutive_numbers() -> None:
    processor, _ = await _run(
        [f"One [^chunk:{CHUNK_A}] two [^chunk:{CHUNK_B}]."]
    )
    assert processor.text == "One [^1] two [^2]."
    assert [citation["n"] for citation in processor.citations] == [1, 2]


async def test_a_marker_naming_an_unknown_chunk_is_dropped() -> None:
    """A footnote pointing at nothing breaks the one promise this product makes, so it is
    removed rather than shown."""
    processor, _ = await _run([f"Claim [^chunk:{uuid4()}] here."])
    assert "[^" not in processor.text
    assert processor.citations == []


async def test_a_malformed_marker_is_dropped_not_rendered() -> None:
    processor, _ = await _run(["Claim [^chunk:not-a-uuid] here."])
    assert "not-a-uuid" not in processor.text


async def test_text_that_merely_looks_like_a_marker_survives() -> None:
    processor, _ = await _run(["An array [1, 2] and a brace {x} are fine."])
    assert processor.text == "An array [1, 2] and a brace {x} are fine."


async def test_a_citation_carries_boxes_for_the_highlight() -> None:
    _, events = await _run([f"Claim [^chunk:{CHUNK_A}]."])
    citation = next(event for event in events if isinstance(event, CitationEvent))
    assert citation.boxes, "requirement FR-22 needs a highlightable region"
    assert citation.page_index == 0
    assert citation.excerpt


# ---------------------------------------------------------------------------
# Placeholders, decision D34
# ---------------------------------------------------------------------------


async def test_a_placeholder_is_substituted_with_the_server_value() -> None:
    processor, _ = await _run(
        ["The total is {{result.total}} overall."],
        paths={"result.total": (15890.5, "USD")},
    )
    assert processor.text == "The total is 15,890.50 USD overall."


async def test_a_placeholder_split_across_deltas_is_substituted() -> None:
    processor, _ = await _run(
        ["Total ", "{{res", "ult.total", "}}", " end."],
        paths={"result.total": (42.0, None)},
    )
    assert processor.text == "Total 42 end."


async def test_an_unresolvable_placeholder_emits_nothing() -> None:
    """Showing the raw placeholder would expose internals; inventing a number is exactly
    what decision D26 forbids."""
    processor, _ = await _run(
        ["Total {{result.nope}} end."], paths={"result.total": (1.0, None)}
    )
    assert "{{" not in processor.text
    assert "nope" not in processor.text


async def test_a_count_is_not_given_a_currency() -> None:
    """Regression. One shared unit produced prose reading "across 5 USD documents"."""
    processor, _ = await _run(
        ["Across {{result.record_count}} documents totalling {{result.total}}."],
        paths={"result.record_count": (5.0, None), "result.total": (100.0, "USD")},
    )
    assert processor.text == "Across 5 documents totalling 100 USD."


async def test_an_unterminated_construct_is_emitted_literally_not_dropped() -> None:
    """Ugly but honest. Silently deleting the tail of an answer loses content the user was
    part way through reading."""
    processor, _ = await _run(["The total is {{result."])
    assert processor.text == "The total is {{result."


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (15890.5, "USD", "15,890.50 USD"),
        (15890.0, "USD", "15,890 USD"),
        (5.0, None, "5"),
        (0.5, None, "0.50"),
        (1234567.891, None, "1,234,567.89"),
        (True, None, "yes"),
        ("Acme", None, "Acme"),
        (None, "USD", ""),
    ],
)
def test_figure_formatting(value: object, unit: str | None, expected: str) -> None:
    """The prose must read the same number the chart shows, formatted the same way: a
    mismatch reads as a bug even when both are right."""
    assert format_figure(value, unit) == expected


# ---------------------------------------------------------------------------
# Coalescing
# ---------------------------------------------------------------------------


async def test_deltas_are_coalesced_into_fewer_token_events() -> None:
    """A fast model produces deltas quicker than a browser can usefully repaint."""
    processor = StreamProcessor(resolve_citation=_resolver, coalesce_ms=10_000)
    events: list[object] = []
    for word in ["one ", "two ", "three ", "four"]:
        async for event in processor.feed(word):
            events.append(event)
    assert events == [], "nothing should flush inside the coalescing window"

    async for event in processor.flush():
        events.append(event)
    assert len(events) == 1
    assert isinstance(events[0], TokenEvent)
    assert events[0].text == "one two three four"


async def test_the_reassembled_text_equals_what_the_user_saw() -> None:
    """``processor.text`` is what gets persisted, so it must match the token stream
    exactly or a refresh would show something different from the live answer."""
    answer = f"Acme leads [^chunk:{CHUNK_A}] with {{{{result.total}}}} total."
    processor, events = await _run(
        list(answer), paths={"result.total": (100.0, "USD")}
    )
    streamed = "".join(
        event.text for event in events if isinstance(event, TokenEvent)
    )
    assert streamed == processor.text


# ---------------------------------------------------------------------------
# Units after a substituted figure.
# ---------------------------------------------------------------------------


async def _prose(deltas: list[str], paths: dict[str, tuple[object, str | None]]) -> str:
    _, events = await _run(deltas, paths)
    return "".join(event.text for event in events if isinstance(event, TokenEvent))


async def test_a_unit_written_after_a_placeholder_is_not_doubled() -> None:
    """Observed on the first real run of the sample corpus: the answer read "16,752.90 USD
    USD". The placeholder expands to a formatted figure that already carries its currency,
    and the model writes the currency again anyway. The prompt now says not to; this makes
    it not matter, because a prompt is a request and this is a guarantee."""
    text = await _prose(
        ["The total is `{{result.total}}` USD for the quarter."],
        {"result.total": (16752.9, "USD")},
    )
    assert text == "The total is `16,752.90 USD` for the quarter."


async def test_the_duplicate_is_removed_across_a_delta_boundary() -> None:
    """The unit routinely arrives in the next delta, not the same one."""
    text = await _prose(
        ["Acme accounts for `{{result.rows.0.value}}`", " USD of the total."],
        {"result.rows.0.value": (8024.0, "USD")},
    )
    assert text == "Acme accounts for `8,024 USD` of the total."


async def test_a_unit_that_belongs_to_the_prose_survives() -> None:
    """Only a repeat immediately after the figure is dropped. A later mention is the
    model's own sentence and removing it would corrupt the answer."""
    text = await _prose(
        ["We paid `{{result.total}}`. Every invoice is issued in USD."],
        {"result.total": (1200.0, "USD")},
    )
    assert text == "We paid `1,200 USD`. Every invoice is issued in USD."


async def test_a_word_merely_starting_with_the_unit_is_untouched() -> None:
    text = await _prose(
        ["`{{result.total}}` USDollars is not a currency code."],
        {"result.total": (5.0, "USD")},
    )
    assert text == "`5 USD` USDollars is not a currency code."


async def test_the_duplicate_is_removed_when_it_sits_inside_the_backticks() -> None:
    """The shape actually observed: "`16,752.90 USD USD`", with the repeat inside the code
    span rather than after it."""
    text = await _prose(
        ["The total is `{{result.total}} USD` for the quarter."],
        {"result.total": (16752.9, "USD")},
    )
    assert text == "The total is `16,752.90 USD` for the quarter."


async def test_a_figure_with_no_unit_leaves_following_text_alone() -> None:
    """A record count has no unit, so nothing is armed and nothing is stripped."""
    text = await _prose(
        ["`{{result.record_count}}` USD invoices were counted."],
        {"result.record_count": (6, None)},
    )
    assert text == "`6` USD invoices were counted."
