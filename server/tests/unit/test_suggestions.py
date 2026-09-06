"""The suggested questions, and the one of them that has to draw a chart. Decision D78.

Suggested questions are how most people meet this product's charts: nobody types "total
amount by vendor" into a blank box on their first visit. The model, asked for three good
questions, reliably offered a sum, a lookup and a superlative — three answers in prose, and
a product that appeared to have no charts in it at all.
"""

from __future__ import annotations

from app.chat.suggestions import breakdown_question, with_breakdown
from app.insights.stats import FieldStats


def stat(key: str, label: str, kind: str, **overrides: object) -> FieldStats:
    values: dict[str, object] = {
        "key": key,
        "label": label,
        "type": kind,
        "present": 10,
        "total_records": 10,
        "distinct": 5,
    }
    values.update(overrides)
    return FieldStats(**values)  # type: ignore[arg-type]


SAMPLE_STATS = [
    stat("invoice_total", "Total due", "currency", numeric_sum=16752.9, distinct=6),
    stat("vendor_name", "Seller", "string", distinct=5),
    stat("payment_terms", "Payment terms", "string", distinct=4),
]


def test_a_breakdown_is_built_from_a_measure_and_a_category() -> None:
    question = breakdown_question(SAMPLE_STATS)
    assert question == "What is the total due by vendor?"


def test_the_measure_keeps_the_documents_own_wording() -> None:
    """"Total total due" reads as a bug, so a label already saying "total" keeps it."""
    assert breakdown_question(SAMPLE_STATS) is not None
    assert "total total" not in (breakdown_question(SAMPLE_STATS) or "")


def test_a_party_field_is_preferred_over_any_other_category() -> None:
    """A chart of five vendors says something; a chart of four payment terms says less."""
    reordered = [SAMPLE_STATS[0], SAMPLE_STATS[2], SAMPLE_STATS[1]]
    assert "vendor" in (breakdown_question(reordered) or "")


def test_the_counterparty_wins_over_the_customer() -> None:
    """Observed live: the first version offered "the total due by bill to" — ungrammatical,
    and a breakdown of a pile of invoices addressed to one company by that one company."""
    both = [
        stat("invoice_total", "Total due", "currency", numeric_sum=16752.9, distinct=6),
        stat("customer_name", "Bill to", "string", distinct=2),
        stat("vendor_name", "Seller", "string", distinct=5),
    ]
    assert breakdown_question(both) == "What is the total due by vendor?"


def test_the_category_is_named_from_the_key_not_the_documents_label() -> None:
    """Labels are whatever the document printed. "By bill to" is not a sentence."""
    odd_labels = [
        stat("invoice_total", "Total due", "currency", numeric_sum=100.0),
        stat("vendor_name", "MERCHANT", "string", distinct=3),
    ]
    assert breakdown_question(odd_labels) == "What is the total due by vendor?"


def test_a_field_almost_nobody_filled_in_is_not_offered() -> None:
    thin = [
        stat("invoice_total", "Total due", "currency", numeric_sum=100.0),
        stat("vendor_name", "Seller", "string", present=1, total_records=10, distinct=1),
    ]
    assert breakdown_question(thin) is None


def test_a_category_with_a_value_per_document_is_not_offered() -> None:
    """Forty distinct invoice numbers is a picket fence, not a chart."""
    identifiers = [
        stat("invoice_total", "Total due", "currency", numeric_sum=100.0),
        stat("invoice_number", "Invoice number", "string", distinct=40),
    ]
    assert breakdown_question(identifiers) is None


def test_nothing_is_invented_when_there_is_nothing_to_total() -> None:
    prose_only = [stat("governing_law", "Governing law", "string", distinct=2)]
    assert breakdown_question(prose_only) is None
    assert with_breakdown(["What does the contract say?"], prose_only) == [
        "What does the contract say?"
    ]


def test_the_generated_question_goes_first_and_the_list_stays_at_three() -> None:
    model_questions = [
        "What is the total sum of all invoice totals?",
        "What are the payment terms for Globex Corporation?",
        "Which vendor has the highest invoice total?",
    ]
    result = with_breakdown(model_questions, SAMPLE_STATS)
    assert result[0] == "What is the total due by vendor?"
    assert len(result) == 3


def test_a_model_that_already_offered_a_breakdown_is_left_alone() -> None:
    """The guarantee is a backstop, not a house style. If the model did the job, it stands."""
    good = ["Total amount by vendor?", "What are the payment terms?", "Who signed the contract?"]
    assert with_breakdown(good, SAMPLE_STATS) == good
