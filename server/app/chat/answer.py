"""The two model calls behind one answer. Implementation section 6.4.

**Plan** is structured and cheap: it decides whether the documents can answer the question
at all, and whether a visual would help. It returns a query specification, never numbers
(decision D26).

**Answer** is streamed text: it writes the prose, citing passages with markers and referring
to computed figures by placeholder. Both run on the fast tier, because the user is watching
(requirement FR-26 asks for a first prose token within three seconds).

Between the two, the server evaluates the plan's query and builds the A2UI surface, so the
chart is on screen before the prose starts arriving beneath it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic import BaseModel, Field

from app.config import Settings
from app.domain.fields import FieldSpec
from app.insights.evaluate import QueryResult
from app.insights.queryspec import Visual
from app.llm import prompts
from app.llm.base import CallKind, LLMClient, LLMRequest
from app.logging import get_logger
from app.retrieval.search import RetrievedChunk

logger = get_logger(__name__)

MAX_PASSAGE_CHARACTERS = 1400
"""Per passage in the prompt. A digest is short; a page chunk is bounded by chunking, so
this is a backstop against one pathological chunk crowding out the rest."""


class ChatPlan(BaseModel):
    """What the planner decided. Implementation section 6.4 step 2."""

    answerable: bool = True
    not_answerable_reason: str | None = Field(default=None, max_length=300)
    visual: Visual | None = None


def render_passages(passages: list[RetrievedChunk]) -> str:
    """The retrieved passages, tagged so the model can cite them.

    The tag carries the chunk identifier because that identifier is what a citation marker
    must contain. Giving the model the document name and page as well is what lets it write
    prose that reads naturally ("the Northwind invoice says...") while still citing
    machine-resolvable references.
    """
    if not passages:
        return "[no passages were retrieved for this question]"
    blocks: list[str] = []
    for passage in passages:
        where = (
            "extracted fields"
            if passage.is_digest
            else f"page {(passage.page_index or 0) + 1}"
        )
        text = " ".join(passage.text.split())[:MAX_PASSAGE_CHARACTERS]
        blocks.append(
            f'[chunk:{passage.chunk_id}] document "{passage.filename}", {where}\n{text}'
        )
    return "\n\n".join(blocks)


def render_schema(fields: list[FieldSpec]) -> str:
    if not fields:
        return "[no fields have been extracted yet]"
    lines = []
    for field in fields:
        note = f" — {field.description}" if field.description else ""
        currency = (
            f" (amounts are {field.currency_default})" if field.currency_default else ""
        )
        lines.append(f"- `{field.key}` ({field.type.value}){currency}{note}")
    return "\n".join(lines)


def render_history(turns: list[tuple[str, str]]) -> str:
    """Recent turns, so a follow-up like "now only Q2" resolves. Requirement FR-28."""
    if not turns:
        return "[this is the first question in the conversation]"
    return "\n".join(f"{role}: {' '.join(content.split())[:400]}" for role, content in turns)


def render_result(result: QueryResult | None, visual: Visual | None) -> str:
    """The evaluated result, with the paths the prose may quote from.

    Shown as paths rather than only as a table because decision D34 requires the model to
    refer to figures by placeholder. Listing the exact paths it may use is what makes that
    instruction followable rather than aspirational.
    """
    if result is None or visual is None:
        return ""

    lines = [
        "# The computed result",
        "",
        f"A {visual.kind.value} titled {visual.title!r} has already been placed above your",
        "answer. These are the figures it shows, and the placeholder for each. Refer to a",
        "figure by its placeholder; never retype the number. A placeholder expands to the",
        "formatted figure INCLUDING its currency or unit, so do not write the unit after",
        "one: `{{result.total}}` alone, never `{{result.total}}` USD.",
        "",
        f"- `{{{{result.total}}}}` = {result.total}",
        f"- `{{{{result.record_count}}}}` = {result.record_count} documents matched",
    ]
    for index, row in enumerate(result.rows[:12]):
        lines.append(
            f"- `{{{{result.rows.{index}.value}}}}` = {row.value} "
            f"(for {row.label!r}, path `{{{{result.rows.{index}.label}}}}`)"
        )
    if result.mixed_currency:
        lines.append("")
        lines.append(
            f"Note: values span {', '.join(result.currencies)}, so the total is not "
            f"directly comparable. Say so if you quote it."
        )
    return "\n".join(lines)


async def plan_answer(
    *,
    question: str,
    passages: list[RetrievedChunk],
    fields: list[FieldSpec],
    history: list[tuple[str, str]],
    client: LLMClient,
    settings: Settings,
    fixture_key: str,
) -> ChatPlan:
    """Decide answerability and whether a visual helps."""
    prompt = prompts.render(
        "chat_plan",
        schema=render_schema(fields),
        passages=render_passages(passages),
        history=render_history(history),
        question=question,
    )
    request = LLMRequest(
        kind=CallKind.CHAT_PLAN,
        prompt=prompt,
        response_model=ChatPlan,
        fixture_key=fixture_key,
        context={
            "question": question,
            "passages": [
                {"chunk_id": str(p.chunk_id), "text": p.text, "is_digest": p.is_digest}
                for p in passages
            ],
            "schema": [field.model_dump(mode="json") for field in fields],
        },
    )
    response = await client.structured(request)
    result = response.value
    assert isinstance(result, ChatPlan)
    logger.info(
        "chat.planned",
        answerable=result.answerable,
        visual=result.visual.kind.value if result.visual else None,
        model=response.usage.model,
        latency_ms=round(response.usage.latency_ms, 1),
    )
    return result


def stream_answer(
    *,
    question: str,
    passages: list[RetrievedChunk],
    fields: list[FieldSpec],
    history: list[tuple[str, str]],
    plan: ChatPlan,
    result: QueryResult | None,
    client: LLMClient,
    settings: Settings,
    fixture_key: str,
) -> AsyncIterator[str]:
    """Stream the prose. Returns the provider's raw deltas, markers and all."""
    prompt = prompts.render(
        "chat_answer",
        schema=render_schema(fields),
        passages=render_passages(passages),
        history=render_history(history),
        result_section=render_result(result, plan.visual),
        question=question,
    )
    request = LLMRequest(
        kind=CallKind.CHAT_ANSWER,
        prompt=prompt,
        response_model=ChatPlan,  # unused for a streamed call; the protocol wants a model
        fixture_key=fixture_key,
        context={
            "question": question,
            "passages": [
                {"chunk_id": str(p.chunk_id), "text": p.text, "is_digest": p.is_digest}
                for p in passages
            ],
            "result": result.to_data_model() if result else None,
            "document_count": len({p.document_id for p in passages}),
        },
    )
    return client.stream_text(request)
