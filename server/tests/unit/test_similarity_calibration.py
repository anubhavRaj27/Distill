"""The embedding thresholds, checked against cosines measured from a real model.

Decision D66. On September 5, 2026 twelve synonym pairs and twelve unrelated pairs of field
labels were embedded with gemini-embedding-001 and scored. The numbers below are from that
run, not invented, and they are the reason the thresholds moved: unrelated labels score
0.764 to 0.827 under this model and synonyms 0.822 to 0.982, a band nothing like the 0.4 to
0.7 the old defaults assumed.

Vectors here are two-dimensional unit vectors placed at an exact angle, so a pair's cosine
is whatever this file says it is. That keeps the calibration checkable with no key and no
network, which is the same trick decision D13 relies on everywhere else.
"""

from __future__ import annotations

import math

from app.domain.fields import FieldSpec, FieldType
from app.schema.similarity import Outcome, Thresholds, classify

MEASURED_UNRELATED_CEILING = 0.827
"""Highest cosine observed between two labels a person would NOT merge: Payment Terms
versus Currency."""

MEASURED_SYNONYM_FLOOR = 0.822
"""Lowest cosine observed between two labels a person WOULD merge: Bill To versus
Customer. It sits below the unrelated ceiling, which is why no threshold separates every
case and why the ask zone exists."""


def at_cosine(similarity: float) -> list[float]:
    """A unit vector whose cosine with ``[1.0, 0.0]`` is exactly ``similarity``."""
    angle = math.acos(max(-1.0, min(1.0, similarity)))
    return [math.cos(angle), math.sin(angle)]


INCOMING = [1.0, 0.0]


def field(key: str, label: str, kind: FieldType = FieldType.CURRENCY) -> FieldSpec:
    return FieldSpec(
        key=key, label=label, type=kind, description="", source_keys=[key], weight=1.0
    )


def verdict(incoming_label: str, candidates: dict[str, tuple[str, float]], **kinds: object):
    """Classify ``incoming_label`` against candidates given as ``key: (label, cosine)``."""
    schema = [
        field(key, label, kinds.get(key, FieldType.CURRENCY))  # type: ignore[arg-type]
        for key, (label, _) in candidates.items()
    ]
    return classify(
        incoming_key="incoming",
        incoming_label=incoming_label,
        incoming_type=FieldType.CURRENCY,
        schema=schema,
        incoming_vector=INCOMING,
        schema_vectors={
            key: at_cosine(score) for key, (_, score) in candidates.items()
        },
        thresholds=Thresholds(),
    )


def test_a_measured_synonym_now_maps_where_it_used_to_be_asked() -> None:
    """`Grand total` against `Total due` scored 0.926. The old 0.95 threshold asked about
    it, so a corpus using both phrasings grew two columns for one fact."""
    result = verdict(
        "Grand total",
        {"total_amount": ("Total due", 0.926), "invoice_no": ("Invoice number", 0.805)},
        invoice_no=FieldType.STRING,
    )
    assert result.outcome is Outcome.AUTO_MAP
    assert result.target_key == "total_amount"


def test_two_plausible_totals_are_still_asked_about() -> None:
    """The case that survives calibration, and should. In the live run `Grand total` scored
    0.926 against `Total due` and 0.901 against `Subtotal`: the margin does not hold, and
    folding a grand total into a subtotal is exactly the wrong merge D24 refuses to risk.
    Two columns and a question beat one wrong column."""
    result = verdict(
        "Grand total",
        {"total_amount": ("Total due", 0.926), "subtotal": ("Subtotal", 0.901)},
    )
    assert result.outcome is Outcome.ASK
    assert result.target_key is None


def test_the_worst_unrelated_pair_measured_does_not_map() -> None:
    """`Payment Terms` versus `Currency` at 0.827 is the highest score any unrelated pair
    reached. The threshold has to sit above it, or drift merges two different facts."""
    result = verdict(
        "Currency",
        {"payment_terms": ("Payment Terms", MEASURED_UNRELATED_CEILING)},
        payment_terms=FieldType.STRING,
    )
    assert result.outcome is not Outcome.AUTO_MAP


def test_a_clearly_novel_field_can_be_added_without_asking() -> None:
    """This branch was unreachable before calibration. With the ceiling at 0.30, no field's
    best match ever fell below it, so `auto add` was dead code that every test passed."""
    result = verdict(
        "Shipment weight",
        {"vendor": ("Vendor", 0.74), "due": ("Due date", 0.71)},
        vendor=FieldType.STRING,
        due=FieldType.DATE,
    )
    assert result.outcome is Outcome.AUTO_ADD


def test_the_two_classes_overlap_and_the_thresholds_admit_it() -> None:
    """A guard on the calibration itself. The synonym floor sits BELOW the unrelated
    ceiling, so no single number separates every case; anyone tempted to tune one threshold
    until every pair behaves has to change these measurements to do it."""
    assert MEASURED_SYNONYM_FLOOR < MEASURED_UNRELATED_CEILING
    thresholds = Thresholds()
    assert thresholds.embedding_auto_map > MEASURED_UNRELATED_CEILING
    assert thresholds.novelty_ceiling_embedding <= 0.80
