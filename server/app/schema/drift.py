"""Deciding what to do when a document has something the schema cannot record.

Decisions D18 and **D27**. Schema-guided extraction returns ``extra_fields``: salient
values that match no current field. That list is the system noticing a document has
something to say the schema cannot hold, which is the alternative to silently dropping it
(requirement FR-11).

WHAT V2 CHANGED, AND WHY IT IS NOT A LOWERING OF STANDARDS
-----------------------------------------------------------
v1 sorted extra fields into three zones and put the uncertain ones in front of the user as a
proposal card. v2 keeps the classifier exactly as it was and changes only what happens to
the uncertain zone: it **auto-adds as a separate field**, and records why in the schema
change summary.

The reasoning is decision D23's, that schema administration is not the job a finance
operations person came to do, plus decision D27's asymmetry argument, which still holds and
now does all the work: **a wrong split is a cheap merge later, a wrong merge is expensive to
unpick.** Splitting on uncertainty leaves two clean columns and the user can merge them from
the column menu in one action, with values and provenance moving intact. Merging on
uncertainty commingles two fields' values and unpicking it needs per-value provenance.

So the classifier's three outcomes now map to two actions:

===================== =========================================================
Classification        Action
===================== =========================================================
Unambiguous match     auto-map onto the existing field
Clearly novel         auto-add as a new field
Uncertain (any of     auto-add as a **separate** field, with the reason recorded
D27's ask reasons)    in ``change_summary``
===================== =========================================================

Nothing is dropped and nothing interrupts. The audit trail is the change summary, which is
the only explanation the user will get, so its wording matters.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from app.config import Settings
from app.domain.fields import FieldSpec, FieldType, inferred_type, validate_field_key
from app.llm.base import LLMClient
from app.llm.contracts import ExtractedField
from app.llm.heuristics import slugify_key
from app.logging import get_logger
from app.pipeline.score import default_weight
from app.schema import embeddings
from app.schema.similarity import AskReason, Outcome, Thresholds, classify

logger = get_logger(__name__)

MAX_AUTO_ADDED_PER_DOCUMENT = 8
"""How many fields one document may add to the schema unprompted.

A document that wants to add twenty columns is not drifting, it is a different kind of
document, and widening everyone else's table by twenty mostly-empty columns is not the
answer. Past this cap the remainder become proposal cards, so the user decides whether this
document belongs in this workspace at all.
"""


@dataclass
class DriftSeparation:
    """An extra field kept as its own column because the match was too close to call.

    Not a pending question (decision D27). The field is already in the schema by the time
    this is reported; this records the near-miss so the change summary can explain it and
    so the interface can hint that a merge is available.
    """

    field_key: str
    field_label: str
    nearest_key: str | None
    nearest_label: str | None
    score: float
    reason: str
    why: AskReason | None = None
    """Which kind of uncertainty this was, so the summary can describe it accurately."""

    @property
    def explanation(self) -> str:
        """One clause for the change summary, phrased for the actual reason.

        Worth the branch. An earlier version described every separation as "too close to
        call", which was plainly wrong for an unconfirmed-novelty case scoring 38%: nothing
        resembled the field, we simply had no vector to prove it. Since this text is the
        only account the user ever gets of an unprompted schema change, a description that
        misstates the cause is worse than a vague one.
        """
        near = self.nearest_label
        match self.why:
            case AskReason.COMPETING_CANDIDATES:
                return (
                    f"kept {self.field_label!r} separate: it matched {near!r} at "
                    f"{self.score:.0%} but another field scored almost the same"
                )
            case AskReason.BORDERLINE:
                return (
                    f"kept {self.field_label!r} separate from {near!r}: at "
                    f"{self.score:.0%} the match was too close to call"
                )
            case AskReason.TYPE_MISMATCH:
                return (
                    f"kept {self.field_label!r} separate from {near!r}: the names line up "
                    f"but the types do not"
                )
            case AskReason.UNCONFIRMED_NOVELTY:
                return (
                    f"added {self.field_label!r} as a new field: nothing in the schema "
                    f"resembled it, though we could not check it for a meaning-based match"
                )
            case _:
                return f"kept {self.field_label!r} as a separate field"


@dataclass
class DriftOutcome:
    """What to do with a document's extra fields."""

    mappings: dict[str, str] = dataclass_field(default_factory=dict)
    """Incoming key to the existing field key it auto-maps onto."""

    additions: list[FieldSpec] = dataclass_field(default_factory=list)
    separations: list[DriftSeparation] = dataclass_field(default_factory=list)
    """Fields kept separate on an uncertain match. A subset of ``additions``."""

    dropped: list[str] = dataclass_field(default_factory=list)
    """Extra fields refused because this document hit the per-document widening cap."""

    notes: list[str] = dataclass_field(default_factory=list)
    """User-facing one-liners explaining each automatic decision."""

    @property
    def real_mappings(self) -> dict[str, str]:
        """Mappings that actually move a value to a DIFFERENT field.

        ``assess`` records a self-map when an extra field carries the same key as an
        existing schema field, which happens whenever the model reports a schema field in
        ``extra_fields`` by mistake. That routes the value correctly but changes nothing, so
        it must not count as a schema change or appear in the summary as
        "mapped total_due to total_due".
        """
        return {
            source: target for source, target in self.mappings.items() if source != target
        }

    @property
    def changes_the_schema(self) -> bool:
        return bool(self.real_mappings or self.additions)

    @property
    def summary(self) -> str:
        """The change summary. This is the ENTIRE audit trail for an unprompted change.

        Decision D27 removed the proposal card, so nothing else will ever tell the user why
        their schema grew a column that looks like one they already had. The near-miss is
        named explicitly for that reason.
        """
        parts: list[str] = []
        real = self.real_mappings
        if real:
            pairs = ", ".join(f"{source} to {target}" for source, target in sorted(real.items()))
            parts.append(f"mapped {pairs}")

        separated = {separation.field_key for separation in self.separations}
        plain = sorted(
            field.key for field in self.additions if field.key not in separated
        )
        if plain:
            parts.append("added " + ", ".join(plain))

        parts.extend(separation.explanation for separation in self.separations)

        if self.dropped:
            parts.append(
                f"left out {', '.join(sorted(self.dropped))} because this document "
                f"would have added more than {MAX_AUTO_ADDED_PER_DOCUMENT} new fields"
            )

        if not parts:
            return "No schema change."
        joined = "; ".join(parts)
        return joined[:1].upper() + joined[1:] + "."


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
    """Sort a document's extra fields into decision D27's three zones.

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

        # AUTO_ADD and ASK now take the SAME action (decision D27). They differ only in
        # what gets recorded: an uncertain match is noted as a separation so the change
        # summary can explain the near-miss and the interface can offer a merge.
        if verdict.outcome in (Outcome.AUTO_ADD, Outcome.ASK):
            if len(outcome.additions) >= MAX_AUTO_ADDED_PER_DOCUMENT:
                # With no proposal card to fall back on, the honest move is to refuse and
                # say so, rather than widening every other document's table.
                outcome.dropped.append(key)
                logger.info("drift.addition_capped", source=key)
                continue
            spec = FieldSpec(
                key=key,
                label=extra.label or key,
                type=inferred_type(extra.value_type),
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

            if verdict.outcome is Outcome.ASK:
                nearest = verdict.best
                outcome.separations.append(
                    DriftSeparation(
                        field_key=spec.key,
                        field_label=spec.label,
                        nearest_key=nearest.field_key if nearest else None,
                        nearest_label=nearest.field_label if nearest else None,
                        score=nearest.headline if nearest else 0.0,
                        reason=verdict.reason,
                        why=verdict.ask_reason,
                    )
                )
                logger.info(
                    "drift.kept_separate",
                    field=key,
                    nearest=nearest.field_key if nearest else None,
                    why=verdict.ask_reason.value if verdict.ask_reason else None,
                )
            else:
                logger.info("drift.auto_added", field=key)
            continue

    return outcome


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
