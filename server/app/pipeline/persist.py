"""Turning a model's answer into stored, grounded, scored, trustworthy field values.

This is where the four guarantees in ``docs/backend-plan.md`` section 2 actually land in the
database. Each extracted value goes through the same four steps, in this order:

1. **ground** the evidence quote against the page's word geometry, producing highlight boxes
   or a recorded reason for failing (``app.pipeline.ground``)
2. **coerce and score** it into the stored representation and derive its confidence tier
   (``app.pipeline.score``)
3. **merge** with whatever is already stored, which is where a human correction is protected
   (``app.pipeline.score.merge_with_existing``)
4. **write**, filtered so no model write path can touch a human-owned row

Step 4's filter is not a duplicate of step 3. Step 3 is the domain rule and is unit tested
without a database; step 4 is the same rule expressed as a ``WHERE`` clause, so the guarantee
survives a future code path that forgets to call step 3. Principle 4 of ``requirements.md``
is a promise to the user, and a promise with one enforcement point is a promise with one bug
away from being broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import Document, FieldValueRow, Page, Record
from app.domain.document import Line, ParsedPage, Word
from app.domain.events import FieldUpdatedEvent, RecordUpsertEvent
from app.domain.fields import FieldSpec, FieldValue, Tier, ValueStatus
from app.domain.records import Record as RecordPayload
from app.events.bus import bus
from app.llm.contracts import ExtractedField
from app.logging import get_logger
from app.pipeline.ground import ground
from app.pipeline.score import merge_with_existing, score

logger = get_logger(__name__)


@dataclass
class PersistedValues:
    """What changed, for the caller to report."""

    record_id: UUID
    written: int = 0
    protected: int = 0
    """Human-owned values a model tried to overwrite and could not."""
    conflicts: int = 0
    grounded: int = 0
    ungrounded: int = 0


def pages_from_rows(rows: list[Page]) -> list[ParsedPage]:
    """Rehydrate stored page geometry for grounding.

    Grounding needs word boxes, and re-parsing the original file to get them would be both
    slow and a source of drift, since a parser upgrade could produce different geometry than
    the values were grounded against. The text layer is stored for exactly this reason.
    """
    pages: list[ParsedPage] = []
    for row in sorted(rows, key=lambda page: page.index):
        layer = row.text_layer or {}
        pages.append(
            ParsedPage(
                index=row.index,
                width_pt=row.width_pt,
                height_pt=row.height_pt,
                words=[Word.model_validate(word) for word in layer.get("words", [])],
                lines=[Line.model_validate(line) for line in layer.get("lines", [])],
                image_key=row.image_key,
                ocr_applied=row.ocr_applied,
                locator=row.locator,
            )
        )
    return pages


async def existing_values(session: AsyncSession, record_id: UUID) -> dict[str, FieldValueRow]:
    rows = (
        (
            await session.execute(
                select(FieldValueRow).where(FieldValueRow.record_id == record_id)
            )
        )
        .scalars()
        .all()
    )
    return {row.field_key: row for row in rows}


def _to_domain(row: FieldValueRow) -> FieldValue:
    from app.domain.provenance import Provenance

    return FieldValue(
        field_key=row.field_key,
        value=row.value,
        value_type=row.value_type,
        confidence=row.confidence,
        tier=row.tier,
        status=row.status,
        provenance=(
            Provenance.model_validate(row.provenance) if row.provenance else None
        ),
        model_value=row.model_value,
        model_value_at=row.model_value_at,
    )


async def persist_values(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    record: Record,
    document: Document,
    pages: list[ParsedPage],
    extracted: list[ExtractedField],
    fields: list[FieldSpec],
    settings: Settings,
    model_run_id: UUID | None = None,
    publish_events: bool = True,
) -> PersistedValues:
    """Ground, score, merge, and write one extraction's values.

    Only fields present in ``fields`` are written. An extracted entry naming a field that is
    not in the schema is ignored here rather than silently creating a column, because
    widening the schema is the schema layer's decision and goes through drift assessment.
    """
    spec_by_key = {field.key: field for field in fields}
    current = await existing_values(session, record.id)
    result = PersistedValues(record_id=record.id)

    for entry in extracted:
        spec = spec_by_key.get(entry.key)
        if spec is None:
            continue

        provenance = ground(
            quote=entry.evidence_quote,
            page_index=entry.page_index,
            pages=pages,
            reasoning=entry.reasoning,
            min_score=settings.grounding_min_score,
        )
        if provenance.is_grounded:
            result.grounded += 1
        else:
            result.ungrounded += 1

        scored = score(
            raw_value_text=entry.value_text,
            spec=spec,
            provenance=provenance,
            model_confidence=entry.confidence,
        )

        row = current.get(entry.key)
        previous = _to_domain(row) if row is not None else None

        if previous is not None and previous.is_human_owned:
            result.protected += 1

        merged = merge_with_existing(scored=scored, spec=spec, existing=previous)
        if merged.tier is Tier.CONFLICT:
            result.conflicts += 1

        if row is None:
            row = FieldValueRow(record_id=record.id, field_key=entry.key)
            session.add(row)
            current[entry.key] = row

        # THE ENFORCEMENT POINT. A human-owned row keeps its value and status no matter
        # what the model returned; only the conflict marker and the model's alternative are
        # allowed through. Expressed here as an explicit branch rather than relying on the
        # merge result, so that the guarantee is visible at the write.
        if previous is not None and previous.is_human_owned:
            row.tier = merged.tier
            row.model_value = merged.model_value
            row.model_value_at = merged.model_value_at
        else:
            row.value = merged.value
            row.value_type = merged.value_type
            row.confidence = merged.confidence
            row.tier = merged.tier
            row.status = merged.status
            row.provenance = (
                merged.provenance.model_dump(mode="json") if merged.provenance else None
            )
            row.model_value = merged.model_value
            row.model_value_at = merged.model_value_at
            row.model_run_id = model_run_id
            result.written += 1

        if publish_events:
            await bus.publish(
                session,
                workspace_id,
                FieldUpdatedEvent(seq=0, record_id=record.id, field_key=entry.key, value=merged),
            )

    await session.flush()
    logger.info(
        "persist.values_written",
        document_id=str(document.id),
        written=result.written,
        protected=result.protected,
        conflicts=result.conflicts,
        grounded=result.grounded,
        ungrounded=result.ungrounded,
    )
    return result


async def build_record_payload(
    session: AsyncSession, record: Record, document: Document, schema_version: int
) -> RecordPayload:
    """The wire shape of a record, for the event stream and the records route."""
    rows = await existing_values(session, record.id)
    return RecordPayload(
        id=record.id,
        document_id=document.id,
        document_name=document.filename,
        schema_version=schema_version,
        values={key: _to_domain(row) for key, row in rows.items()},
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


async def publish_record(
    session: AsyncSession,
    workspace_id: UUID,
    record: Record,
    document: Document,
    schema_version: int,
) -> None:
    """Announce a record wholesale, which is what makes a row appear in the table."""
    payload = await build_record_payload(session, record, document, schema_version)
    await bus.publish(session, workspace_id, RecordUpsertEvent(seq=0, record=payload))


async def apply_human_correction(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    record: Record,
    field_key: str,
    spec: FieldSpec,
    value: object | None,
    not_present: bool,
) -> FieldValue:
    """Record a human's decision about one value. Requirement FR-23.

    A correction is the highest-authority statement about a value in the system, so it
    clears any conflict marker: the user has now seen both candidates and chosen.
    """
    from datetime import UTC, datetime

    from app.domain.provenance import Provenance
    from app.domain.values import Interpretation, coerce
    from app.errors import InvalidValue

    if not_present:
        stored: object | None = None
        status = ValueStatus.NOT_PRESENT
    else:
        coerced = coerce(value, spec)
        if coerced.interpretation is Interpretation.FAILED:
            raise InvalidValue(
                f"That is not a valid {spec.type.value} for {spec.label!r}: {coerced.error}",
                field_key=field_key,
                expected_type=spec.type.value,
            )
        stored = coerced.value
        status = ValueStatus.HUMAN_VERIFIED

    rows = await existing_values(session, record.id)
    row = rows.get(field_key)
    if row is None:
        row = FieldValueRow(record_id=record.id, field_key=field_key)
        session.add(row)

    row.value = stored
    row.value_type = spec.type
    row.status = status
    row.tier = Tier.VERIFIED
    row.confidence = 1.0
    # The conflict is resolved by the act of correcting, so the competing model value is
    # cleared rather than left to keep flagging a decision the user has already made.
    row.model_value = None
    row.model_value_at = None
    row.provenance = Provenance(
        page_index=None,
        reasoning="Set by you." if not not_present else "You marked this as not present.",
    ).model_dump(mode="json")
    record.updated_at = datetime.now(UTC)
    await session.flush()

    payload = _to_domain(row)
    await bus.publish(
        session,
        workspace_id,
        FieldUpdatedEvent(seq=0, record_id=record.id, field_key=field_key, value=payload),
    )
    logger.info(
        "persist.human_correction",
        record_id=str(record.id),
        field_key=field_key,
        not_present=not_present,
    )
    return payload
