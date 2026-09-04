"""Deciding what to do when a document has something the schema cannot record.

Decisions D23 and D24. Schema-guided extraction returns ``extra_fields``: salient values
that match no current field. That list is the system noticing a document has something to
say the schema cannot hold, which is the alternative to silently dropping it (requirement
FR-13).

Each extra field lands in one of decision D23's three zones:

* **auto-mapped** onto an existing field, no prompt, when the match is unambiguous
* **auto-added** as a new field, no prompt, when it clearly resembles nothing
* **asked about**, as a proposal card, for everything in between

An auto-applied change writes a ``schema_versions`` row and a ``schema.version`` event but
**not** a ``proposals`` row: ``schema_versions`` is the complete log of what happened to the
schema, and ``proposals`` stays strictly "questions that needed a human", so that "how many
decisions are outstanding" is a row count rather than a filtered one.

An auto-added field also enqueues backfill without offering. Requirement FR-14 says adding a
field "offers" backfill, and that stays true for a field the **user** added: they are
present, mid-decision, and the offer has somewhere to attach. An auto-added field has no
such moment by construction, since the entire point is that nothing interrupted the user.
Backfill only ever adds values and never touches human-verified rows, and its progress is
visible, so running it is the behaviour the user would have chosen anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from app.config import Settings
from app.domain.fields import FieldSpec, FieldType, validate_field_key
from app.llm.base import LLMClient
from app.llm.contracts import ExtractedField
from app.llm.heuristics import slugify_key
from app.logging import get_logger
from app.pipeline.score import default_weight
from app.schema import embeddings
from app.schema.similarity import Outcome, Thresholds, Verdict, classify

logger = get_logger(__name__)

MAX_AUTO_ADDED_PER_DOCUMENT = 8
"""How many fields one document may add to the schema unprompted.

A document that wants to add twenty columns is not drifting, it is a different kind of
document, and widening everyone else's table by twenty mostly-empty columns is not the
answer. Past this cap the remainder become proposal cards, so the user decides whether this
document belongs in this workspace at all.
"""


@dataclass
class DriftQuestion:
    """One extra field the user needs to decide about. Becomes a proposal card."""

    incoming_key: str
    incoming_label: str
    incoming_type: FieldType
    sample_value: str | None
    reason: str
    candidates: list[tuple[str, str, float]] = dataclass_field(default_factory=list)
    """``(field_key, field_label, score)``, best first, for the card's mapping choices."""


@dataclass
class DriftOutcome:
    """What to do with a document's extra fields."""

    mappings: dict[str, str] = dataclass_field(default_factory=dict)
    """Incoming key to the existing field key it auto-maps onto."""

    additions: list[FieldSpec] = dataclass_field(default_factory=list)
    questions: list[DriftQuestion] = dataclass_field(default_factory=list)
    notes: list[str] = dataclass_field(default_factory=list)
    """User-facing one-liners explaining each automatic decision."""

    @property
    def changes_the_schema(self) -> bool:
        return bool(self.mappings or self.additions)

    @property
    def summary(self) -> str:
        """One line for the schema history entry, and for the auto-apply note."""
        parts: list[str] = []
        if self.mappings:
            pairs = ", ".join(
                f"{source} to {target}" for source, target in sorted(self.mappings.items())
            )
            parts.append(f"mapped {pairs}")
        if self.additions:
            parts.append(
                "added " + ", ".join(sorted(field.key for field in self.additions))
            )
        if not parts:
            return "No schema change."
        return (parts[0][:1].upper() + parts[0][1:] + (
            "; " + "; ".join(parts[1:]) if len(parts) > 1 else ""
        ) + ".")


def _key_for(extra: ExtractedField) -> str | None:
    raw = extra.key or extra.label
    if not raw:
        return None
    try:
        return validate_field_key(raw)
    except ValueError:
        pass
    try:
        return slugify_key(raw)
    except ValueError:
        logger.info("drift.unusable_key", raw=raw[:60])
        return None


async def assess(
    extra_fields: list[ExtractedField],
    schema: list[FieldSpec],
    *,
    client: LLMClient,
    settings: Settings,
) -> DriftOutcome:
    """Sort a document's extra fields into decision D23's three zones.

    Never raises for content reasons. An extra field that cannot be turned into a legal
    field key is dropped with a log line rather than failing the document, because losing
    one speculative field is a far smaller harm than failing a document that extracted
    correctly otherwise.
    """
    outcome = DriftOutcome()
    if not extra_fields:
        return outcome

    thresholds = Thresholds.from_settings(settings)

    # One embedding pass for the schema and for this document's extras together, so a
    # document with six extras costs one call rather than six.
    schema_texts = {field.key: embeddings.field_embedding_text(field) for field in schema}
    usable: list[tuple[str, ExtractedField]] = []
    for extra in extra_fields:
        key = _key_for(extra)
        if key is not None:
            usable.append((key, extra))

    incoming_texts = {
        key: embeddings.embedding_text(extra.label or key, "", key) for key, extra in usable
    }
    resolved = await embeddings.vectors_for(
        client, [*schema_texts.values(), *incoming_texts.values()]
    )
    schema_vectors = {key: resolved.get(text) for key, text in schema_texts.items()}

    # A field auto-added earlier in this same document must be visible to the fields after
    # it, or a document mentioning the same new thing twice would add it twice.
    working_schema = list(schema)

    for key, extra in usable:
        if key in {field.key for field in working_schema}:
            # Already present, which happens when an earlier extra added it. Map onto it.
            outcome.mappings[key] = key
            continue

        verdict = classify(
            incoming_key=key,
            incoming_label=extra.label or key,
            incoming_type=extra.value_type,
            schema=working_schema,
            incoming_vector=resolved.get(incoming_texts[key]),
            schema_vectors=schema_vectors,
            thresholds=thresholds,
        )

        if verdict.outcome is Outcome.AUTO_MAP and verdict.target_key:
            outcome.mappings[key] = verdict.target_key
            outcome.notes.append(verdict.reason)
            logger.info("drift.auto_mapped", source=key, target=verdict.target_key)
            continue

        if verdict.outcome is Outcome.AUTO_ADD:
            if len(outcome.additions) >= MAX_AUTO_ADDED_PER_DOCUMENT:
                outcome.questions.append(_question(key, extra, verdict, capped=True))
                logger.info("drift.addition_capped", source=key)
                continue
            spec = FieldSpec(
                key=key,
                label=extra.label or key,
                type=extra.value_type,
                description=(
                    f"First seen in a document as {extra.label!r}."
                    if extra.label
                    else ""
                ),
                source_keys=[key],
                weight=default_weight(extra.value_type),
                currency_default=(
                    "USD" if extra.value_type is FieldType.CURRENCY else None
                ),
            )
            outcome.additions.append(spec)
            working_schema.append(spec)
            schema_vectors[spec.key] = resolved.get(incoming_texts[key])
            outcome.notes.append(verdict.reason)
            logger.info("drift.auto_added", field=key)
            continue

        outcome.questions.append(_question(key, extra, verdict))
        logger.info(
            "drift.asked",
            source=key,
            why=verdict.ask_reason.value if verdict.ask_reason else None,
        )

    return outcome


def _question(
    key: str, extra: ExtractedField, verdict: Verdict, *, capped: bool = False
) -> DriftQuestion:
    reason = verdict.reason
    if capped:
        reason = (
            f"This document wanted to add more than {MAX_AUTO_ADDED_PER_DOCUMENT} new "
            f"fields, so the rest are here for you to decide on."
        )
    return DriftQuestion(
        incoming_key=key,
        incoming_label=extra.label or key,
        incoming_type=extra.value_type,
        sample_value=extra.value_text,
        reason=reason,
        candidates=[
            (signals.field_key, signals.field_label, round(signals.headline, 3))
            for signals in verdict.ranked[:3]
        ],
    )


def merged_schema(schema: list[FieldSpec], outcome: DriftOutcome) -> list[FieldSpec]:
    """The new field list after applying ``outcome``'s automatic decisions.

    An auto-mapped source key is recorded in the target's ``source_keys``. That is what
    makes the mapping stick: the next document using that spelling matches by alias, costs
    no embedding call, and is never re-proposed.
    """
    by_key = {field.key: field.model_copy(deep=True) for field in schema}

    for source, target in outcome.mappings.items():
        field = by_key.get(target)
        if field is None or source == target:
            continue
        if source not in field.source_keys:
            field.source_keys.append(source)

    return [*by_key.values(), *outcome.additions]
