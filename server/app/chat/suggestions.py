"""Three questions worth asking, generated from the workspace. Requirement FR-25.

Shown when the conversation is empty, which is the moment a chat-first product is most
likely to lose someone: a blank composer and a blinking cursor is an invitation to think of
something, and thinking of something is work.

Generated from the actual schema and statistics rather than being hard-coded, because a
suggestion that returns "not in these documents" is worse than no suggestion. The user
trusted it, and the product broke that trust on its very first interaction.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Chunk
from app.domain.fields import FieldSpec
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
    stats_text: str,
    client: LLMClient,
    settings: Settings,
) -> list[str]:
    """Three questions this workspace can actually answer.

    Never raises. A failure here costs the user three chips they would not have missed, so
    an empty list is the right degradation; failing the whole Chat screen is not.
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
        stats=stats_text,
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
    questions = value.top_three
    logger.info("chat.suggestions_ready", count=len(questions))
    return questions
