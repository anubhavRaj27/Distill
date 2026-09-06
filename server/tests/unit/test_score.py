"""Tier derivation, the never-lose-a-correction merge, and review ordering.

The merge tests are the important ones. Principle 4 of requirements.md ("never lose a human
correction") and requirement FR-34 are promises to the user, and this is one of the two
places they are kept, the other being a SQL filter in the persistence layer.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.domain.fields import FieldSpec, FieldType, FieldValue, Tier, ValueStatus
from app.domain.geometry import BBox
from app.domain.provenance import GroundingFailure, Provenance
from app.pipeline.score import (
    default_weight,
    impact,
    merge_with_existing,
    score,
)

GROUNDED = Provenance(
    page_index=0, boxes=[BBox(x0=10, top=10, x1=50, bottom=22)], quote="q", match_score=100.0
)
UNGROUNDED = Provenance(
    page_index=0, quote="q", match_score=50.0, failure=GroundingFailure.QUOTE_NOT_FOUND
)
NO_QUOTE = Provenance(page_index=0, failure=GroundingFailure.NO_QUOTE)

CURRENCY = FieldSpec(
    key="total_due", label="Total Due", type=FieldType.CURRENCY, currency_default="USD"
)
DATE = FieldSpec(key="issue_date", label="Issue Date", type=FieldType.DATE)
STRING = FieldSpec(key="vendor_name", label="Vendor", type=FieldType.STRING)


# ---------------------------------------------------------------------------
# The tier table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "spec", "provenance", "confidence", "expected", "why"),
    [
        ("$12,480.50", CURRENCY, GROUNDED, 0.95, Tier.HIGH, "grounded, sure, unambiguous"),
        ("EUR 3,410.00", CURRENCY, GROUNDED, 0.90, Tier.HIGH, "explicit currency code"),
        ("2026-03-14", DATE, GROUNDED, 0.95, Tier.HIGH, "canonical date"),
        ("14 March 2026", DATE, GROUNDED, 0.95, Tier.HIGH, "unambiguous reformat"),
        ("Acme Ltd", STRING, GROUNDED, 0.70, Tier.MEDIUM, "mid confidence"),
        ("Acme Ltd", STRING, GROUNDED, 0.40, Tier.LOW, "low confidence"),
        ("Acme Ltd", STRING, UNGROUNDED, 0.98, Tier.LOW, "sure but uncorroborated"),
        ("Acme Ltd", STRING, NO_QUOTE, 0.98, Tier.LOW, "no evidence offered"),
        ("03/04/2026", DATE, GROUNDED, 0.99, Tier.LOW, "ambiguous day and month"),
        ("12480.50", CURRENCY, GROUNDED, 0.99, Tier.LOW, "currency assumed"),
        ("Net 30", DATE, GROUNDED, 0.99, Tier.LOW, "not representable as a date"),
    ],
)
def test_tier_derivation(
    raw: str,
    spec: FieldSpec,
    provenance: Provenance,
    confidence: float,
    expected: Tier,
    why: str,
) -> None:
    result = score(
        raw_value_text=raw, spec=spec, provenance=provenance, model_confidence=confidence
    )
    assert result.tier is expected, f"{why}: expected {expected}, got {result.tier}"


def test_a_confident_ungrounded_value_can_never_be_high() -> None:
    """The hallucination guard. 'Confident and uncorroborated' is the shape of an
    invented value, so grounding caps rather than merely adjusts."""
    for confidence in (0.86, 0.95, 1.0):
        result = score(
            raw_value_text="Acme Ltd",
            spec=STRING,
            provenance=UNGROUNDED,
            model_confidence=confidence,
        )
        assert result.tier is Tier.LOW


def test_a_genuinely_absent_field_is_not_a_review_item() -> None:
    """A field the document does not contain is a fact, not a low-confidence guess.

    Tiering it low would fill the review queue with values that have nothing to review,
    which is how a review queue gets ignored.
    """
    result = score(
        raw_value_text=None, spec=CURRENCY, provenance=GROUNDED, model_confidence=0.9
    )
    assert result.value is None
    assert result.tier is Tier.HIGH
    assert result.usable


def test_an_uncoercible_value_produces_no_value_but_keeps_the_explanation() -> None:
    result = score(
        raw_value_text="Net 30", spec=DATE, provenance=GROUNDED, model_confidence=0.99
    )
    assert result.value is None
    assert not result.usable
    assert result.coercion_error is not None
    assert result.provenance.reasoning is not None
    assert "Net 30" in result.provenance.reasoning, (
        "the user must be able to see what the document actually said"
    )


def test_a_grounding_failure_is_explained_in_words_a_user_can_act_on() -> None:
    for provenance in (UNGROUNDED, NO_QUOTE):
        result = score(
            raw_value_text="Acme Ltd",
            spec=STRING,
            provenance=provenance,
            model_confidence=0.9,
        )
        reasoning = result.provenance.reasoning or ""
        assert reasoning
        assert "quote_not_found" not in reasoning, "no internal state names in user text"
        assert "None" not in reasoning


def test_a_missing_model_confidence_is_treated_as_the_middle_not_as_certainty() -> None:
    result = score(
        raw_value_text="Acme Ltd", spec=STRING, provenance=GROUNDED, model_confidence=None
    )
    assert result.confidence == pytest.approx(0.5)
    assert result.tier is Tier.LOW


# ---------------------------------------------------------------------------
# Never lose a human correction
# ---------------------------------------------------------------------------


def _human(value: object, status: ValueStatus = ValueStatus.HUMAN_VERIFIED) -> FieldValue:
    return FieldValue(
        field_key="vendor_name",
        value=value,
        value_type=FieldType.STRING,
        confidence=1.0,
        tier=Tier.VERIFIED,
        status=status,
        provenance=Provenance(page_index=0, quote="what the human saw"),
    )


def test_re_extraction_never_overwrites_a_human_value() -> None:
    """Principle 4 of requirements.md, and requirement FR-34."""
    human = _human("Northwind Traders Pvt Ltd")
    fresh = score(
        raw_value_text="Northwind Trading Company",
        spec=STRING,
        provenance=GROUNDED,
        model_confidence=0.99,
    )
    merged = merge_with_existing(scored=fresh, spec=STRING, existing=human)

    assert merged.value == "Northwind Traders Pvt Ltd", "the human's value survives"
    assert merged.status is ValueStatus.HUMAN_VERIFIED


def test_a_disagreeing_model_answer_is_kept_beside_the_human_one() -> None:
    """Decision D13. A flag alone would say a disagreement exists without saying what it
    is, which the user cannot act on."""
    human = _human("Northwind Traders Pvt Ltd")
    fresh = score(
        raw_value_text="Northwind Trading Company",
        spec=STRING,
        provenance=GROUNDED,
        model_confidence=0.99,
    )
    merged = merge_with_existing(scored=fresh, spec=STRING, existing=human)

    assert merged.tier is Tier.CONFLICT
    assert merged.model_value == "Northwind Trading Company"
    assert merged.model_value_at is not None


def test_the_human_provenance_is_not_overwritten_by_a_disagreeing_run() -> None:
    """What the human verified is the record. A model that now disagrees does not get to
    rewrite the reasoning attached to their decision."""
    human = _human("Northwind Traders Pvt Ltd")
    fresh = score(
        raw_value_text="Someone Else", spec=STRING, provenance=GROUNDED, model_confidence=0.9
    )
    merged = merge_with_existing(scored=fresh, spec=STRING, existing=human)
    assert merged.provenance is not None
    assert merged.provenance.quote == "what the human saw"


def test_a_model_that_comes_to_agree_clears_the_conflict() -> None:
    """Worth recording: it clears a stale conflict and raises confidence in the run."""
    human = _human("Northwind Traders Pvt Ltd")
    human = human.model_copy(
        update={
            "tier": Tier.CONFLICT,
            "model_value": "Old Wrong Answer",
            "model_value_at": datetime.now(UTC),
        }
    )
    fresh = score(
        raw_value_text="northwind traders pvt ltd",  # same value, different casing
        spec=STRING,
        provenance=GROUNDED,
        model_confidence=0.95,
    )
    merged = merge_with_existing(scored=fresh, spec=STRING, existing=human)

    assert merged.tier is Tier.VERIFIED
    assert merged.model_value is None


def test_a_not_present_marking_is_also_protected() -> None:
    """A human asserting 'this document does not contain that' is a correction too, and
    a model finding something must not silently overturn it."""
    marked = _human(None, status=ValueStatus.NOT_PRESENT)
    fresh = score(
        raw_value_text="Acme Ltd", spec=STRING, provenance=GROUNDED, model_confidence=0.99
    )
    merged = merge_with_existing(scored=fresh, spec=STRING, existing=marked)

    assert merged.value is None
    assert merged.status is ValueStatus.NOT_PRESENT
    assert merged.tier is Tier.CONFLICT
    assert merged.model_value == "Acme Ltd"


def test_a_model_owned_value_is_replaced_freely() -> None:
    """The guarantee protects HUMAN values. A previous model guess has no such standing."""
    previous = FieldValue(
        field_key="vendor_name",
        value="Old Guess",
        value_type=FieldType.STRING,
        tier=Tier.LOW,
        status=ValueStatus.MODEL,
    )
    fresh = score(
        raw_value_text="Better Answer", spec=STRING, provenance=GROUNDED, model_confidence=0.9
    )
    merged = merge_with_existing(scored=fresh, spec=STRING, existing=previous)
    assert merged.value == "Better Answer"
    assert merged.status is ValueStatus.MODEL


@pytest.mark.parametrize(
    ("left", "right", "should_conflict"),
    [
        (12480.5, 12480.50, False),
        ({"amount": 100.0, "currency": "USD"}, {"amount": 100.0, "currency": "USD"}, False),
        ({"amount": 100.0, "currency": "USD"}, {"amount": 100.0, "currency": "EUR"}, True),
        ("Acme Ltd", " acme ltd ", False),
        ("Acme Ltd", "Acme Limited", True),
        (None, None, False),
        (None, "something", True),
        (True, True, False),
        (True, False, True),
    ],
)
def test_trivial_differences_do_not_raise_a_conflict(
    left: object, right: object, should_conflict: bool
) -> None:
    """12480.5 and 12480.50 are the same amount. Flagging that trains the user to ignore
    conflicts, which loses more than missing one."""
    from app.pipeline.score import _values_differ

    assert _values_differ(left, right) is should_conflict


# ---------------------------------------------------------------------------
# Review ordering
# ---------------------------------------------------------------------------


def test_money_outranks_a_note_at_the_same_confidence() -> None:
    low_currency = FieldValue(
        field_key="total_due",
        value={"amount": 1.0, "currency": "USD"},
        value_type=FieldType.CURRENCY,
        confidence=0.4,
        tier=Tier.LOW,
    )
    low_string = FieldValue(
        field_key="vendor_name",
        value="x",
        value_type=FieldType.STRING,
        confidence=0.4,
        tier=Tier.LOW,
    )
    money = CURRENCY.model_copy(update={"weight": default_weight(FieldType.CURRENCY)})
    text = STRING.model_copy(update={"weight": default_weight(FieldType.STRING)})
    assert impact(money, low_currency) > impact(text, low_string)


def test_a_conflict_outranks_a_low_confidence_value_of_the_same_weight() -> None:
    """A conflict is the one case where the system KNOWS something is wrong."""
    conflict = FieldValue(
        field_key="vendor_name",
        value="a",
        value_type=FieldType.STRING,
        confidence=0.8,
        tier=Tier.CONFLICT,
    )
    low = FieldValue(
        field_key="vendor_name",
        value="a",
        value_type=FieldType.STRING,
        confidence=0.4,
        tier=Tier.LOW,
    )
    assert impact(STRING, conflict) > impact(STRING, low)


def test_a_verified_value_has_no_impact() -> None:
    """There is nothing left to review, so it must not appear in the queue at all."""
    verified = FieldValue(
        field_key="vendor_name",
        value="a",
        value_type=FieldType.STRING,
        confidence=0.1,
        tier=Tier.VERIFIED,
        status=ValueStatus.HUMAN_VERIFIED,
    )
    assert impact(STRING, verified) == 0.0


def test_higher_confidence_means_lower_impact() -> None:
    def at(confidence: float) -> float:
        return impact(
            STRING,
            FieldValue(
                field_key="vendor_name",
                value="a",
                value_type=FieldType.STRING,
                confidence=confidence,
                tier=Tier.MEDIUM,
            ),
        )

    assert at(0.9) < at(0.7) < at(0.3)
