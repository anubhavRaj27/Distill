"""Coercion tests. Real document formatting, not synthetic happy paths.

Every case here is a way a real invoice, receipt, or statement actually writes a value.
The `Interpretation` assertions matter as much as the values: they are what drives the
"minor normalisation applied" row of the tier table, so getting the value right while
reporting the wrong amount of interpretation would silently mis-tier the result.
"""

from __future__ import annotations

import pytest
from app.domain.fields import FieldSpec, FieldType
from app.domain.values import Interpretation, coerce


def spec(field_type: FieldType, **kwargs: object) -> FieldSpec:
    return FieldSpec(key="f", label="F", type=field_type, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Absence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field_type", list(FieldType))
def test_none_is_absence_not_failure(field_type: FieldType) -> None:
    """The model is told to return null rather than guess, so null must not be an error."""
    kwargs = {"enum_values": ["a"]} if field_type is FieldType.ENUM else {}
    result = coerce(None, spec(field_type, **kwargs))
    assert result.ok
    assert result.value is None
    assert result.error is None


@pytest.mark.parametrize("field_type", [FieldType.STRING, FieldType.NUMBER, FieldType.DATE])
def test_blank_string_is_absence(field_type: FieldType) -> None:
    assert coerce("   ", spec(field_type)).value is None


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected", "interpretation"),
    [
        (42, 42.0, Interpretation.EXACT),
        (42.5, 42.5, Interpretation.EXACT),
        ("42", 42.0, Interpretation.EXACT),
        ("12,480.50", 12480.50, Interpretation.NORMALISED),
        ("  17 ", 17.0, Interpretation.NORMALISED),
        ("(1,234.00)", -1234.00, Interpretation.NORMALISED),
        ("1234.00-", -1234.00, Interpretation.NORMALISED),
        ("-5", -5.0, Interpretation.EXACT),
        (".5", 0.5, Interpretation.EXACT),
    ],
)
def test_numbers(raw: object, expected: float, interpretation: Interpretation) -> None:
    result = coerce(raw, spec(FieldType.NUMBER))
    assert result.value == pytest.approx(expected)
    assert result.interpretation is interpretation


def test_boolean_is_not_a_number() -> None:
    """`bool` is a subclass of `int` in Python, so this needs an explicit guard."""
    result = coerce(True, spec(FieldType.NUMBER))
    assert not result.ok


def test_unreadable_number_fails_loudly() -> None:
    result = coerce("not a number", spec(FieldType.NUMBER))
    assert not result.ok
    assert result.error is not None


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------


def test_currency_object_is_the_canonical_form() -> None:
    result = coerce({"amount": 12480.5, "currency": "usd"}, spec(FieldType.CURRENCY))
    assert result.value == {"amount": 12480.5, "currency": "USD"}
    assert result.interpretation is Interpretation.EXACT


@pytest.mark.parametrize(
    ("raw", "amount", "code"),
    [
        ("$12,480.50", 12480.50, "USD"),
        ("€1.500", 1.500, "EUR"),
        ("£99", 99.0, "GBP"),
        ("₹1,20,000", 120000.0, "INR"),
        ("12480.50 USD", 12480.50, "USD"),
        ("EUR 340", 340.0, "EUR"),
        ("Rs. 4,500", 4500.0, "INR"),
    ],
)
def test_currency_from_a_string_with_a_marker(raw: str, amount: float, code: str) -> None:
    result = coerce(raw, spec(FieldType.CURRENCY))
    assert result.ok, result.error
    assert result.value == {"amount": pytest.approx(amount), "currency": code}
    assert result.interpretation is Interpretation.NORMALISED


def test_bare_amount_uses_the_field_default_and_says_so() -> None:
    """An inferred currency must be reported as inferred, and explained to the user."""
    result = coerce("12,480.50", spec(FieldType.CURRENCY, currency_default="USD"))
    assert result.value == {"amount": pytest.approx(12480.50), "currency": "USD"}
    assert result.interpretation is Interpretation.INFERRED
    assert result.note is not None and "USD" in result.note


def test_bare_amount_with_no_default_is_a_failure_not_a_guess() -> None:
    """Guessing a currency silently is exactly the failure this project exists to avoid."""
    result = coerce("12480.50", spec(FieldType.CURRENCY))
    assert not result.ok
    assert result.error is not None and "currency" in result.error


def test_unknown_currency_symbol_fails_rather_than_defaulting_to_dollars() -> None:
    result = coerce("₿0.05", spec(FieldType.CURRENCY))
    assert not result.ok


def test_parenthesised_currency_is_negative() -> None:
    result = coerce("($1,234.00)", spec(FieldType.CURRENCY))
    assert result.ok, result.error
    assert result.value == {"amount": pytest.approx(-1234.0), "currency": "USD"}


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected", "interpretation"),
    [
        ("2026-03-14", "2026-03-14", Interpretation.EXACT),
        ("14 March 2026", "2026-03-14", Interpretation.NORMALISED),
        ("March 14, 2026", "2026-03-14", Interpretation.NORMALISED),
        ("Mar 14 2026", "2026-03-14", Interpretation.NORMALISED),
        ("14 Mar 26", "2026-03-14", Interpretation.NORMALISED),
        ("2026/03/14", "2026-03-14", Interpretation.NORMALISED),
        ("25/03/2026", "2026-03-25", Interpretation.NORMALISED),  # 25 > 12, day first
        ("03/25/2026", "2026-03-25", Interpretation.NORMALISED),  # 25 > 12, month first
    ],
)
def test_dates(raw: str, expected: str, interpretation: Interpretation) -> None:
    result = coerce(raw, spec(FieldType.DATE))
    assert result.ok, result.error
    assert result.value == expected
    assert result.interpretation is interpretation


def test_ambiguous_date_is_inferred_and_explained() -> None:
    """03/04/2026 could be either order. We choose one AND tell the user we guessed."""
    result = coerce("03/04/2026", spec(FieldType.DATE))
    assert result.ok
    assert result.value == "2026-04-03", "day-first is the documented choice"
    assert result.interpretation is Interpretation.INFERRED
    # The note must name the input and explain the choice, so the user can see WHY the
    # value reads as it does. Asserting on behaviour rather than on exact prose, so
    # rewording the message does not fail the suite.
    assert result.note is not None
    assert "03/04/2026" in result.note
    assert "day" in result.note


def test_impossible_date_fails() -> None:
    assert not coerce("2026-02-30", spec(FieldType.DATE)).ok
    assert not coerce("32/01/2026", spec(FieldType.DATE)).ok


def test_unknown_month_name_fails() -> None:
    assert not coerce("14 Smarch 2026", spec(FieldType.DATE)).ok


# ---------------------------------------------------------------------------
# Booleans, enums, lists, strings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(True, True), ("Yes", True), ("PAID", True), ("no", False), ("0", False), (1, True)],
)
def test_booleans(raw: object, expected: bool) -> None:
    result = coerce(raw, spec(FieldType.BOOLEAN))
    assert result.ok, result.error
    assert result.value is expected


def test_enum_matches_case_insensitively_but_stores_the_canonical_casing() -> None:
    field = spec(FieldType.ENUM, enum_values=["Paid", "Unpaid", "Overdue"])
    assert coerce("Paid", field).value == "Paid"
    exact = coerce("Paid", field)
    assert exact.interpretation is Interpretation.EXACT
    folded = coerce("overdue", field)
    assert folded.value == "Overdue"
    assert folded.interpretation is Interpretation.NORMALISED


def test_enum_rejects_a_value_outside_the_permitted_set() -> None:
    field = spec(FieldType.ENUM, enum_values=["Paid", "Unpaid"])
    result = coerce("Partially paid", field)
    assert not result.ok
    assert result.error is not None and "permitted" in result.error


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["a", "b"], ["a", "b"]),
        ("a, b, c", ["a", "b", "c"]),
        ("a; b", ["a", "b"]),
        ("a\nb", ["a", "b"]),
        ([" a ", "", "b"], ["a", "b"]),
    ],
)
def test_string_lists(raw: object, expected: list[str]) -> None:
    result = coerce(raw, spec(FieldType.STRING_LIST))
    assert result.ok, result.error
    assert result.value == expected


def test_string_collapses_whitespace() -> None:
    result = coerce("Northwind   Traders\n Pvt Ltd", spec(FieldType.STRING))
    assert result.value == "Northwind Traders Pvt Ltd"
    assert result.interpretation is Interpretation.NORMALISED
