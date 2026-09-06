"""Three questions worth asking, generated from the workspace. Requirement FR-25.

Shown when the conversation is empty, which is the moment a chat-first product is most
likely to lose someone: a blank composer and a blinking cursor is an invitation to think of
something, and thinking of something is work.

Generated from the actual schema and statistics rather than being hard-coded, because a
suggestion that returns "not in these documents" is worse than no suggestion. The user
trusted it, and the product broke that trust on its very first interaction.
"""

from __future__ import annotations

import re
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Chunk
from app.domain.fields import FieldSpec
from app.insights.stats import FieldStats, render_stats
from app.llm import prompts
from app.llm.base import CallKind, LLMClient, LLMRequest
from app.logging import get_logger

logger = get_logger(__name__)

MAX_DIGESTS_IN_PROMPT = 3


class SuggestedQuestions(BaseModel):
    questions: list[str] = Field(default_factory=list, max_length=6)

    @property
    def top_three(self) -> list[str]:
        cleaned = [" ".join(question.split())[:120] for question in self.questions]
        return [question for question in cleaned if question][:3]


async def suggest(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    fields: list[FieldSpec],
    document_count: int,
    stats: list[FieldStats],
    client: LLMClient,
    settings: Settings,
) -> list[str]:
    """Three questions this workspace can actually answer, one of which draws a chart.

    Never raises. A failure here costs the user three chips they would not have missed, so
    an empty list is the right degradation; failing the whole Chat screen is not.

    **One suggestion is guaranteed to be a breakdown.** Asking the prompt for one is a
    request; this is the guarantee. Suggested questions are how most people meet this
    product's charts — nobody types "total amount by vendor" into a blank box on their first
    visit — so a set where none of them draws a chart hides the visual half of the product.
    That is what was happening: the model reliably offered a sum, a lookup and a
    superlative, all of which answer in prose. See decision D78.
    """
    if not fields:
        return []

    digests = list(
        (
            await session.execute(
                select(Chunk.text)
                .where(Chunk.workspace_id == workspace_id, Chunk.is_digest.is_(True))
                .limit(MAX_DIGESTS_IN_PROMPT)
            )
        )
        .scalars()
        .all()
    )

    prompt = prompts.render(
        "suggest_questions",
        document_count=document_count,
        stats=render_stats(stats),
        digests="\n\n".join(digests) or "[no extracted records yet]",
    )
    request = LLMRequest(
        kind=CallKind.SUGGEST_QUESTIONS,
        prompt=prompt,
        response_model=SuggestedQuestions,
        fixture_key=f"suggestions-{workspace_id.hex[:12]}-{len(fields)}",
        context={"schema": [field.model_dump(mode="json") for field in fields]},
    )
    try:
        response = await client.structured(request)
    except Exception as exc:
        logger.info("chat.suggestions_failed", error=type(exc).__name__)
        return []

    value = response.value
    assert isinstance(value, SuggestedQuestions)
    questions = with_breakdown(value.top_three, stats)
    logger.info("chat.suggestions_ready", count=len(questions))
    return questions


BREAKDOWN_PATTERN = re.compile(r"\bby\s+[a-z]", re.IGNORECASE)
"""A question that splits a measure across a category says "by" and then a field. Crude, and
crude is right: the cost of a false positive is one suggestion that would have been fine
anyway, and the cost of a false negative is a suggestion replaced by an equally good one."""

MAX_BREAKDOWN_CATEGORIES = 12
"""Above this a bar chart is a picket fence. The evaluator caps the rows anyway; this stops
a suggestion promising a chart of forty invoice numbers."""


def breakdown_question(stats: list[FieldStats]) -> str | None:
    """A question of the shape that draws a chart, from fields that can actually answer it.

    Built from the statistics rather than from the schema, so the measure is one that has
    numbers in it and the category is one with several values in it. A question naming a
    field that nine documents left empty is worse than no question at all.
    """
    measures = [
        stat
        for stat in stats
        if stat.type == "currency" and stat.numeric_sum is not None and stat.coverage >= 0.3
    ]
    categories = [
        stat
        for stat in stats
        if stat.type in ("string", "enum")
        and 2 <= stat.distinct <= MAX_BREAKDOWN_CATEGORIES
        and stat.coverage >= 0.3
    ]
    if not measures or not categories:
        return None

    measure = max(measures, key=lambda stat: stat.coverage)
    category = max(categories, key=_category_rank)
    return f"What is the {_total_phrase(measure)} by {_category_phrase(category)}?"


def with_breakdown(questions: list[str], stats: list[FieldStats]) -> list[str]:
    """Ensure one suggestion is a breakdown, keeping the list at three.

    The generated one goes first: it is the one worth clicking, and it is the only one whose
    answer shows what this product does with numbers rather than describing it.
    """
    if any(BREAKDOWN_PATTERN.search(question) for question in questions):
        return questions

    generated = breakdown_question(stats)
    if generated is None:
        return questions
    return [generated, *questions][:3]


def _total_phrase(stat: FieldStats) -> str:
    """The measure, named as the documents name it. "Total total due" reads as a bug."""
    label = (stat.label or stat.key.replace("_", " ")).lower()
    return label if label.startswith("total") else f"total {label}"


COUNTERPARTY_WORDS = ("vendor", "supplier", "seller", "merchant")
"""Who the money went to. The most legible breakdown a collection of invoices has."""

OTHER_PARTY_WORDS = ("customer", "client", "buyer", "party")
"""Also a party, and usually a worse chart: in a pile of invoices addressed to one company,
the customer is the same value every time."""


def _category_rank(stat: FieldStats) -> tuple[int, int, float]:
    """Sort key for choosing what to break the measure down by, best last.

    Counterparty first, then any other party, then anything else; ties broken by how many
    distinct values there are, because a chart of five bars says more than a chart of two.
    """
    if any(word in stat.key for word in COUNTERPARTY_WORDS):
        rank = 2
    elif any(word in stat.key for word in OTHER_PARTY_WORDS):
        rank = 1
    else:
        rank = 0
    return (rank, stat.distinct, stat.coverage)


def _category_phrase(stat: FieldStats) -> str:
    """The category, named from the KEY rather than the label.

    Labels are whatever the document happened to print — "Bill to", "MERCHANT", "Seller" —
    and "the total due by bill to" is not a sentence. Keys are already normalised nouns, so
    `vendor_name` becomes "vendor" and `payment_terms` becomes "payment terms".
    """
    key = stat.key.lower()
    for suffix in ("_name", "_id", "_number"):
        if key.endswith(suffix):
            key = key[: -len(suffix)]
    return key.replace("_", " ")
