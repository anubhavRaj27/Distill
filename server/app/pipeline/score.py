"""Deriving how much a value should be trusted, and how much a mistake would matter.

The tier is DERIVED and never asked of the model (decision D5). The reasoning: whether a
quoted piece of evidence can actually be found in the document is a far stronger signal than
a number the model produced about its own certainty, and grounding failure is the mechanism
that catches invented values.

This module implements the table in implementation.md section 6.4, with one refinement to
the "minor normalisation applied" row. ``app.domain.values`` distinguishes four degrees of
interpretation, and the line that matters is **reformatting versus judgement**:

===================== ================== ==========================================
Interpretation        Tier ceiling       Example
===================== ================== ==========================================
EXACT                 none               the model returned "2026-03-14"
NORMALISED            none               "$12,480.50" read as 12480.50 USD
INFERRED              low                "03/04/2026" read as day before month
FAILED                low, value null    "Net 30" offered as a date
===================== ================== ==========================================

Why NORMALISED does not reduce the tier, though the document's table suggests it might.
Recognising a currency symbol, dropping thousands separators, and reading "14 March 2026"
as an ISO date are all UNAMBIGUOUS reformattings: there is exactly one thing the document
can mean. Capping them would put essentially every real invoice amount and date into
medium, because that is how invoices are written. The high tier would become unreachable
for precisely the field types that matter most, and the review queue would fill with values
nobody needs to look at, which trains a user to stop looking. A tier only means something
if it is sometimes clean.

Why INFERRED is capped at low, rather than the medium the document's table suggests. An
inference is a place where the system made a judgement a reasonable person might make
differently: which component of "03/04/2026" is the day, or which currency an unlabelled
amount is in. On an invoice those are expensive to get wrong and cheap to confirm, so they
belong in the review queue. Note that the document's own example for that row, "date format
inferred", is an INFERRED case in this taxonomy rather than a NORMALISED one, so this is
closer to the document's intent than to a departure from it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.domain.fields import FieldSpec, FieldType, FieldValue, Tier, ValueStatus
from app.domain.provenance import Provenance
from app.domain.values import Coerced, Interpretation, coerce
from app.logging import get_logger

logger = get_logger(__name__)

HIGH_CONFIDENCE = 0.85
MEDIUM_CONFIDENCE = 0.6

DEFAULT_WEIGHTS: dict[FieldType, float] = {
    FieldType.CURRENCY: 2.0,
    FieldType.DATE: 1.5,
    FieldType.NUMBER: 1.3,
    FieldType.STRING: 1.0,
    FieldType.ENUM: 1.0,
    FieldType.BOOLEAN: 0.8,
    FieldType.STRING_LIST: 0.8,
}
"""Default review weight per type. Money first, then dates, because those are the values a
finance operations person is actually held to account for. The user can adjust weights
later; that is out of the five day slice, so the defaults have to be sensible on their own.
"""

_TIER_ORDER: dict[Tier, int] = {
    Tier.LOW: 0,
    Tier.MEDIUM: 1,
    Tier.HIGH: 2,
}


def _cap(tier: Tier, ceiling: Tier) -> Tier:
    """Return the lower of two tiers, by trust order."""
    if _TIER_ORDER.get(tier, 0) <= _TIER_ORDER.get(ceiling, 0):
        return tier
    return ceiling


_INTERPRETATION_CEILING: dict[Interpretation, Tier] = {
    # HIGH here means "no ceiling": the tier is decided by confidence and grounding alone.
    Interpretation.EXACT: Tier.HIGH,
    Interpretation.NORMALISED: Tier.HIGH,
    # These two are judgement calls, so they cap. See the module docstring.
    Interpretation.INFERRED: Tier.LOW,
    Interpretation.FAILED: Tier.LOW,
}


@dataclass
class Scored:
    """A value, its tier, and everything needed to explain both to a user."""

    value: Any | None
    tier: Tier
    confidence: float | None
    provenance: Provenance
    coercion_error: str | None = None

    @property
    def usable(self) -> bool:
        """Whether this produced a value at all, as opposed to only an explanation."""
        return self.coercion_error is None


def score(
    *,
    raw_value_text: str | None,
    spec: FieldSpec,
    provenance: Provenance,
    model_confidence: float | None,
) -> Scored:
    """Coerce a raw value and derive its confidence tier.

    Every explanation the system produced along the way (why a date was read one way, why a
    quote could not be found) is folded into ``provenance.reasoning``, because the viewer
    shows that text and it is the user's only window into the system's thinking.
    """
    coerced: Coerced = coerce(raw_value_text, spec)
    confidence = model_confidence if model_confidence is not None else 0.5

    notes: list[str] = []
    if provenance.reasoning:
        notes.append(provenance.reasoning)

    # 1. Start from the model's own confidence.
    if confidence >= HIGH_CONFIDENCE:
        tier = Tier.HIGH
    elif confidence >= MEDIUM_CONFIDENCE:
        tier = Tier.MEDIUM
    else:
        tier = Tier.LOW

    # 2. Grounding is the strongest signal, so it caps rather than adjusts. An ungrounded
    #    value cannot be high or medium however sure the model claims to be, because
    #    "confident and uncorroborated" is exactly the shape of a hallucination.
    if not provenance.is_grounded:
        tier = Tier.LOW
        if provenance.failure is not None:
            notes.append(_failure_explanation(provenance))

    # 3. How much interpretation the value needed.
    ceiling = _INTERPRETATION_CEILING[coerced.interpretation]
    tier = _cap(tier, ceiling)
    if coerced.note:
        notes.append(coerced.note)

    # 4. A value that could not be represented as its declared type is not a value.
    if coerced.interpretation is Interpretation.FAILED:
        notes.append(
            f"This did not read as {spec.type.value}: {coerced.error}. "
            f"The original text was {raw_value_text!r}."
        )

    # 5. An absent value carries no risk, so it is not a review item. A field the document
    #    genuinely does not contain is a fact, not a low-confidence guess, and tiering it
    #    low would fill the review queue with nothing to review.
    if coerced.value is None and coerced.interpretation is Interpretation.EXACT:
        tier = Tier.HIGH

    return Scored(
        value=coerced.value,
        tier=tier,
        confidence=confidence,
        provenance=provenance.model_copy(update={"reasoning": " ".join(notes).strip() or None}),
        coercion_error=coerced.error,
    )


def _failure_explanation(provenance: Provenance) -> str:
    """Why a value could not be corroborated, written for the user.

    These strings appear in the viewer beside the value, so they say what the user should
    conclude rather than naming an internal state.
    """
    from app.domain.provenance import GroundingFailure

    match provenance.failure:
        case GroundingFailure.NO_QUOTE:
            return (
                "We could not check this value, because no supporting text was quoted "
                "for it. Treat it as unverified."
            )
        case GroundingFailure.QUOTE_NOT_FOUND:
            return (
                "We could not find the quoted text in this document, so this value may "
                "be wrong. Worth checking against the source."
            )
        case GroundingFailure.PAGE_OUT_OF_RANGE:
            return (
                "The quoted text referred to a page this document does not have, so this "
                "value could not be verified."
            )
        case GroundingFailure.NO_TEXT_LAYER:
            return (
                "This page has no readable text, so the value could not be located in it. "
                "A clearer scan would let us verify it."
            )
        case _:
            return "This value could not be verified against the document."


# ---------------------------------------------------------------------------
# Merging with what is already stored
# ---------------------------------------------------------------------------


def merge_with_existing(
    *, scored: Scored, spec: FieldSpec, existing: FieldValue | None
) -> FieldValue:
    """Combine a freshly scored value with whatever is already stored for that field.

    THIS FUNCTION IS THE NEVER-LOSE-A-CORRECTION GUARANTEE (principle 4 of
    requirements.md, requirement FR-34). If the stored value is human-owned, the human's
    value is kept, and a disagreeing model answer is recorded ALONGSIDE it in
    ``model_value`` with the tier set to conflict.

    Keeping both is what makes the conflict actionable rather than merely alarming
    (decision D16): the interface can show the user the two candidates and let them decide,
    instead of telling them a disagreement exists without saying what it is.

    Note that this is belt to the database's braces. The persistence layer also filters
    ``status <> 'human_verified'`` on every model write path, so the guarantee does not rest
    on this function being called correctly.
    """
    if existing is not None and existing.is_human_owned:
        model_answer = scored.value
        disagrees = _values_differ(existing.value, model_answer)

        if not disagrees:
            # The model now agrees with the human. Worth recording, because it upgrades the
            # user's confidence in the rest of the run, and it clears a stale conflict.
            return existing.model_copy(
                update={
                    "tier": Tier.VERIFIED,
                    "model_value": None,
                    "model_value_at": None,
                    "provenance": scored.provenance or existing.provenance,
                }
            )

        logger.info(
            "score.model_disagrees_with_human",
            field_key=spec.key,
            kept="human",
        )
        return existing.model_copy(
            update={
                "tier": Tier.CONFLICT,
                "model_value": model_answer,
                "model_value_at": datetime.now(UTC),
                # The human's own provenance is kept: it is the record of what they
                # verified. The model's new reasoning is not allowed to overwrite it.
            }
        )

    return FieldValue(
        field_key=spec.key,
        value=scored.value,
        value_type=spec.type,
        confidence=scored.confidence,
        tier=scored.tier,
        status=ValueStatus.MODEL,
        provenance=scored.provenance,
    )


def _values_differ(left: Any, right: Any) -> bool:
    """Whether two stored values are meaningfully different.

    Numeric comparison is tolerant, because 12480.5 and 12480.50 are the same amount and
    flagging that as a conflict would train the user to ignore conflicts, which is worse
    than missing one.
    """
    if left is None and right is None:
        return False
    if left is None or right is None:
        return True
    if isinstance(left, dict) and isinstance(right, dict):
        keys = set(left) | set(right)
        return any(_values_differ(left.get(key), right.get(key)) for key in keys)
    if isinstance(left, bool) or isinstance(right, bool):
        return bool(left) is not bool(right)
    if isinstance(left, int | float) and isinstance(right, int | float):
        return abs(float(left) - float(right)) > 1e-9
    if isinstance(left, str) and isinstance(right, str):
        return left.strip().casefold() != right.strip().casefold()
    return left != right


# ---------------------------------------------------------------------------
# Review ordering
# ---------------------------------------------------------------------------


def impact(spec: FieldSpec, value: FieldValue) -> float:
    """How much a mistake in this value would matter. The review queue orders by this.

    ``weight * (1 - confidence)`` from implementation.md section 6.4, with two additions
    that follow from what the tiers mean:

    * a conflict outranks everything at the same weight, because it is the one case where
      the system KNOWS something is wrong rather than suspecting it
    * a value already verified by a human has zero impact, because there is nothing left
      to review
    """
    if value.status is ValueStatus.HUMAN_VERIFIED or value.tier is Tier.VERIFIED:
        return 0.0

    weight = spec.weight if spec.weight > 0 else DEFAULT_WEIGHTS.get(spec.type, 1.0)
    confidence = value.confidence if value.confidence is not None else 0.5

    base = weight * (1.0 - confidence)
    if value.tier is Tier.CONFLICT:
        return base + weight  # a known disagreement, not a suspicion
    if value.tier is Tier.LOW:
        return base * 1.5
    return base


def default_weight(field_type: FieldType) -> float:
    return DEFAULT_WEIGHTS.get(field_type, 1.0)
