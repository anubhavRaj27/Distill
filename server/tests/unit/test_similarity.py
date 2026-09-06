"""Field matching. Decisions D18, D18, and D27.

This suite is where the confidence-gated auto-apply policy is held honest. Two properties
matter more than the rest:

* an **ambiguous** match must reach the user, because a wrong auto-merge commingles two
  fields' values under one column and unpicking it means knowing which source key produced
  each value (decision D27)
* all **three** zones must actually be reachable. An earlier calibration made auto-add
  impossible, which meant a third of the drift gate was not implemented while the code read
  as though it were. The zone-reachability tests exist so that cannot recur silently.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from app.domain.fields import FieldSpec, FieldType
from app.schema.similarity import (
    Outcome,
    Signal,
    Thresholds,
    classify,
    cosine,
    string_similarity,
    types_compatible,
)

VENDOR = FieldSpec(
    key="vendor_name", label="Vendor", type=FieldType.STRING, source_keys=["supplier_co"]
)
SUPPLIER_ID = FieldSpec(key="supplier_id", label="Supplier ID", type=FieldType.STRING)
TOTAL = FieldSpec(
    key="total_due", label="Total Due", type=FieldType.CURRENCY, currency_default="USD"
)
ISSUE_DATE = FieldSpec(key="issue_date", label="Issue Date", type=FieldType.DATE)
SCHEMA = [VENDOR, SUPPLIER_ID, TOTAL, ISSUE_DATE]

# Five dimensions on purpose, so the fifth axis is free for a genuinely novel field to be
# orthogonal to every existing one. A four-dimensional set left no spare axis, which made
# the "novel" vector in an earlier version of this file parallel to `issue_date` and scored
# it as a perfect match.
VECTORS = {
    "vendor_name": [1.0, 0.0, 0.0, 0.0, 0.0],
    "supplier_id": [0.6, 0.8, 0.0, 0.0, 0.0],
    "total_due": [0.0, 0.0, 1.0, 0.0, 0.0],
    "issue_date": [0.0, 0.0, 0.0, 1.0, 0.0],
}
NOVEL_VECTOR = [0.0, 0.0, 0.0, 0.0, 1.0]
"""Orthogonal to every field above, which is what "resembles nothing" means here."""

# Two fields that genuinely sit close together in meaning space, for the margin rule. The
# main set cannot express this: `vendor_name` and `supplier_id` are 0.6 apart, so no single
# incoming vector can score above the auto-map bar against both.
CROWDED_VECTORS = {
    "vendor_name": [1.0, 0.0, 0.0, 0.0, 0.0],
    "supplier_id": [0.98, 0.199, 0.0, 0.0, 0.0],
    "total_due": [0.0, 0.0, 1.0, 0.0, 0.0],
    "issue_date": [0.0, 0.0, 0.0, 1.0, 0.0],
}
T = Thresholds()


# ---------------------------------------------------------------------------
# Cosine
# ---------------------------------------------------------------------------


def test_cosine_of_identical_vectors_is_one() -> None:
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_of_orthogonal_vectors_is_zero() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_is_clamped_and_never_negative() -> None:
    """A negative cosine and a zero cosine both mean 'unrelated' here, and letting
    negatives through would make score comparisons misleading."""
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == 0.0


@pytest.mark.parametrize(
    ("left", "right"),
    [([], [1.0]), ([1.0], []), ([1.0, 2.0], [1.0]), ([0.0, 0.0], [1.0, 1.0])],
)
def test_cosine_returns_zero_rather_than_raising_on_unusable_input(
    left: list[float], right: list[float]
) -> None:
    """Mismatched dimensions mean two different embedding models were used. The honest
    answer is 'no usable signal', which routes to a card rather than crashing a document."""
    assert cosine(left, right) == 0.0


# ---------------------------------------------------------------------------
# String similarity: decision D18's correctness fix
# ---------------------------------------------------------------------------


def test_supplier_does_not_score_as_supplier_id() -> None:
    """THE regression test for decision D18.

    With the filler-word fold this scored 1.00, because both fold to "supplier", which
    cleared the 0.90 auto-map bar and would have silently merged a company name into an
    identifier column with no card and no user involvement.
    """
    score = string_similarity("Supplier", "Supplier ID")
    assert score < T.string_auto_map, f"scored {score:.2f}, must stay below the auto-map bar"


def test_case_and_separator_variants_score_at_the_top() -> None:
    for variant in ("vendor_name", "Vendor Name", "VENDOR-NAME", "  vendor   name  "):
        assert string_similarity(variant, "vendor_name") == pytest.approx(1.0)


def test_word_order_does_not_matter_in_a_label() -> None:
    assert string_similarity("Due Total", "Total Due") == pytest.approx(1.0)


def test_a_semantic_rename_scores_low_on_string_which_is_the_whole_point() -> None:
    """Direct evidence for decision D18's refusal to average the two signals: on a rename
    the string signal is not weak, it is actively misleading."""
    assert string_similarity("Supplier", "vendor_name") < 0.5
    assert string_similarity("Amount", "Total Due") < 0.5


def test_an_empty_label_scores_zero_rather_than_matching_everything() -> None:
    assert string_similarity("", "vendor_name") == 0.0
    assert string_similarity("!!!", "vendor_name") == 0.0


# ---------------------------------------------------------------------------
# Type compatibility
# ---------------------------------------------------------------------------


def test_the_same_type_is_compatible() -> None:
    assert types_compatible(FieldType.STRING, VENDOR)
    assert types_compatible(FieldType.CURRENCY, TOTAL)


def test_a_bare_number_may_enter_a_currency_field_that_has_a_default_code() -> None:
    assert types_compatible(FieldType.NUMBER, TOTAL)


def test_a_bare_number_may_not_enter_a_currency_field_with_no_default() -> None:
    no_default = FieldSpec(key="amount", label="Amount", type=FieldType.CURRENCY)
    with pytest.raises(ValueError):
        # A currency field with no default is legal; the point is the conversion is not
        # defined, so guard the compatibility answer rather than the construction.
        FieldSpec(key="amount", label="Amount", type=FieldType.CURRENCY, enum_values=["x"])
    assert not types_compatible(FieldType.NUMBER, no_default)


def test_nothing_is_silently_compatible_with_a_string_field() -> None:
    """Stringification always 'works', which would make a string field a magnet that
    swallows dates and amounts and destroys their queryability."""
    assert not types_compatible(FieldType.DATE, VENDOR)
    assert not types_compatible(FieldType.CURRENCY, VENDOR)
    assert not types_compatible(FieldType.NUMBER, VENDOR)


def test_currency_into_number_is_refused_because_it_drops_the_code() -> None:
    number_field = FieldSpec(key="qty", label="Quantity", type=FieldType.NUMBER)
    assert not types_compatible(FieldType.CURRENCY, number_field)


def test_a_string_into_an_enum_is_refused_because_validity_is_not_yet_knowable() -> None:
    enum_field = FieldSpec(
        key="status", label="Status", type=FieldType.ENUM, enum_values=["Paid", "Unpaid"]
    )
    assert not types_compatible(FieldType.STRING, enum_field)


# ---------------------------------------------------------------------------
# Zone 1: auto-map
# ---------------------------------------------------------------------------


def test_an_exact_name_match_auto_maps() -> None:
    verdict = classify(
        incoming_key="VENDOR-NAME",
        incoming_label="Vendor Name",
        incoming_type=FieldType.STRING,
        schema=SCHEMA,
        thresholds=T,
    )
    assert verdict.outcome is Outcome.AUTO_MAP
    assert verdict.target_key == "vendor_name"


def test_a_mapping_the_user_already_approved_auto_maps_without_asking_again() -> None:
    """``source_keys`` records an accepted decision. Re-proposing it on every subsequent
    document is the opposite of what requirement FR-13 promises."""
    verdict = classify(
        incoming_key="supplier_co",
        incoming_label="Supplier Co",
        incoming_type=FieldType.STRING,
        schema=SCHEMA,
        thresholds=T,
    )
    assert verdict.outcome is Outcome.AUTO_MAP
    assert verdict.target_key == "vendor_name"
    assert Signal.ALIAS in (verdict.best.fired if verdict.best else set())


def test_a_semantic_rename_auto_maps_when_the_embedding_is_decisive() -> None:
    """The demo path in decision D27: ``Supplier`` merging into ``vendor_name``."""
    verdict = classify(
        incoming_key="supplier",
        incoming_label="Supplier",
        incoming_type=FieldType.STRING,
        schema=SCHEMA,
        incoming_vector=[0.99, 0.05, 0.0, 0.0, 0.0],
        schema_vectors=VECTORS,
        thresholds=T,
    )
    assert verdict.outcome is Outcome.AUTO_MAP
    assert verdict.target_key == "vendor_name"


def test_the_reason_for_an_auto_map_is_written_for_a_person() -> None:
    """It appears in schema history, which is the audit trail that makes auto-apply
    defensible (decision D27), so it cannot read like an internal state dump."""
    verdict = classify(
        incoming_key="vendor_name",
        incoming_label="Vendor Name",
        incoming_type=FieldType.STRING,
        schema=SCHEMA,
        thresholds=T,
    )
    assert verdict.reason
    assert "auto_map" not in verdict.reason
    assert "Vendor" in verdict.reason


# ---------------------------------------------------------------------------
# The margin rule
# ---------------------------------------------------------------------------


def test_two_nearly_equal_candidates_go_to_the_user() -> None:
    """Decision D18's central example. A high absolute score is not evidence of an
    unambiguous match when a second field scores nearly as high."""
    verdict = classify(
        incoming_key="supplier",
        incoming_label="Supplier",
        incoming_type=FieldType.STRING,
        schema=SCHEMA,
        incoming_vector=[1.0, 0.0, 0.0, 0.0, 0.0],
        schema_vectors=CROWDED_VECTORS,
        thresholds=T,
    )
    assert verdict.outcome is Outcome.ASK
    assert verdict.target_key is None


def test_the_ask_reason_names_both_competing_candidates() -> None:
    verdict = classify(
        incoming_key="supplier",
        incoming_label="Supplier",
        incoming_type=FieldType.STRING,
        schema=SCHEMA,
        incoming_vector=[1.0, 0.0, 0.0, 0.0, 0.0],
        schema_vectors=CROWDED_VECTORS,
        thresholds=T,
    )
    assert "Vendor" in verdict.reason
    assert "Supplier ID" in verdict.reason, "the user needs to see what it is competing with"


def test_a_single_field_schema_needs_no_margin() -> None:
    """With one candidate there is nothing to be confused with."""
    verdict = classify(
        incoming_key="vendor_name",
        incoming_label="Vendor",
        incoming_type=FieldType.STRING,
        schema=[VENDOR],
        thresholds=T,
    )
    assert verdict.outcome is Outcome.AUTO_MAP


# ---------------------------------------------------------------------------
# Type mismatch
# ---------------------------------------------------------------------------


def test_a_perfect_name_match_with_an_incompatible_type_still_asks() -> None:
    verdict = classify(
        incoming_key="total_due",
        incoming_label="Total Due",
        incoming_type=FieldType.STRING,
        schema=SCHEMA,
        thresholds=T,
    )
    assert verdict.outcome is Outcome.ASK
    assert "types do not line up" in verdict.reason
    assert "currency" in verdict.reason


# ---------------------------------------------------------------------------
# Zone 2: auto-add, and its dependence on having vectors
# ---------------------------------------------------------------------------


def test_a_clearly_novel_field_auto_adds_when_both_signals_agree() -> None:
    verdict = classify(
        incoming_key="shipping_weight",
        incoming_label="Shipping Weight",
        incoming_type=FieldType.NUMBER,
        schema=SCHEMA,
        incoming_vector=NOVEL_VECTOR,
        schema_vectors=VECTORS,
        thresholds=T,
    )
    assert verdict.outcome is Outcome.AUTO_ADD
    assert verdict.target_key is None


def test_a_missing_embedding_blocks_auto_add_and_asks_instead() -> None:
    """Novelty is a claim about ABSENCE, so both signals must support it.

    String similarity alone cannot: a semantic rename scores about 0.2, so with no vector a
    rename would look 'clearly novel' and be auto-added as a duplicate column. Asking is
    the safe direction.
    """
    verdict = classify(
        incoming_key="shipping_weight",
        incoming_label="Shipping Weight",
        incoming_type=FieldType.NUMBER,
        schema=SCHEMA,
        thresholds=T,
    )
    assert verdict.outcome is Outcome.ASK
    assert "meaning-based" in verdict.reason


def test_an_empty_schema_auto_adds() -> None:
    verdict = classify(
        incoming_key="anything",
        incoming_label="Anything",
        incoming_type=FieldType.STRING,
        schema=[],
        thresholds=T,
    )
    assert verdict.outcome is Outcome.AUTO_ADD


# ---------------------------------------------------------------------------
# Zone reachability. Decision D18's regression guard.
# ---------------------------------------------------------------------------


def test_all_three_zones_are_reachable_at_the_configured_thresholds() -> None:
    """An earlier calibration made auto-add impossible, so a third of the drift gate was
    unimplemented while the code read as though it were. This asserts the shipped
    configuration can actually produce all three outcomes."""
    configured = Thresholds.from_settings(Settings(llm_provider="fake"))

    outcomes = {
        classify(
            incoming_key="vendor_name",
            incoming_label="Vendor Name",
            incoming_type=FieldType.STRING,
            schema=SCHEMA,
            thresholds=configured,
        ).outcome,
        classify(
            incoming_key="shipping_weight",
            incoming_label="Shipping Weight",
            incoming_type=FieldType.NUMBER,
            schema=SCHEMA,
            incoming_vector=NOVEL_VECTOR,
            schema_vectors=VECTORS,
            thresholds=configured,
        ).outcome,
        classify(
            incoming_key="supplier",
            incoming_label="Supplier",
            incoming_type=FieldType.STRING,
            schema=SCHEMA,
            incoming_vector=[1.0, 0.0, 0.0, 0.0, 0.0],
            schema_vectors=CROWDED_VECTORS,
            thresholds=configured,
        ).outcome,
    }
    assert outcomes == {Outcome.AUTO_MAP, Outcome.AUTO_ADD, Outcome.ASK}


def test_unrelated_fixture_corpus_labels_never_reach_the_auto_map_bar() -> None:
    """Decision D18's measurement, as a standing assertion. The highest string similarity
    between two genuinely different labels in the corpus is 0.59."""
    different_pairs = [
        ("Currency", "Reference"),
        ("Invoice Number", "Purchase Order Number"),
        ("Invoice No", "Vendor"),
        ("Date", "Debit"),
        ("Amount", "Payment Terms"),
        ("Balance", "Total Due"),
    ]
    for left, right in different_pairs:
        score = string_similarity(left, right)
        assert score < T.string_auto_map, f"{left!r} vs {right!r} scored {score:.2f}"


def test_classify_never_raises() -> None:
    """An undecidable case must be an ASK, which is always safe, not an exception that
    fails the document."""
    for key, label, vector in [
        ("", "", None),
        ("!!!", "???", []),
        ("x" * 500, "y" * 500, [0.0]),
        ("vendor_name", "Vendor", [float("nan")]),
    ]:
        classify(
            incoming_key=key,
            incoming_label=label,
            incoming_type=FieldType.STRING,
            schema=SCHEMA,
            incoming_vector=vector,
            schema_vectors=VECTORS,
            thresholds=T,
        )
