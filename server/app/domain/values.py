"""Turning what a model said into a typed value, and reporting how much work that took.

Two things make this module more than a parser.

First, it is the ONLY place that converts a raw model output into a stored value. Every
type's stored representation is defined here and nowhere else, so "how is currency stored"
has exactly one answer.

Second, it reports **how much interpretation was required**, not just the result. A value
that arrived as a clean ISO date is more trustworthy than the same date recovered from
"14/03/26", and the tier derivation in ``app.pipeline.score`` uses that difference. This is
the "minor normalisation applied" row of the tier table in implementation.md section 6.4.
Without this signal, that row could not be implemented.

Stored representations
----------------------
=============== ==========================================================
FieldType       Stored as
=============== ==========================================================
STRING          str
NUMBER          float
CURRENCY        {"amount": float, "currency": "USD"}
DATE            "YYYY-MM-DD"
BOOLEAN         bool
ENUM            str, exactly one of FieldSpec.enum_values
STRING_LIST     list[str]
=============== ==========================================================

``None`` always means "genuinely absent from this document", never "we failed". A failure is
an ``error``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from app.domain.fields import CurrencyAmount, FieldSpec, FieldType


class Interpretation(StrEnum):
    """How much work it took to get from the raw value to the typed one."""

    EXACT = "exact"  # arrived already in the stored representation
    NORMALISED = "normalised"  # unambiguous cleanup: stripped a symbol, trimmed, cast
    INFERRED = "inferred"  # a genuine judgement call, such as an ambiguous date order
    FAILED = "failed"  # could not be represented as this type at all


@dataclass(frozen=True)
class Coerced:
    """The result of coercing one raw value."""

    value: Any | None
    interpretation: Interpretation
    error: str | None = None
    note: str | None = None
    """Human-readable explanation of an inference, shown to the user beside the value."""

    @property
    def ok(self) -> bool:
        return self.interpretation is not Interpretation.FAILED


# ---------------------------------------------------------------------------
# Currency
# ---------------------------------------------------------------------------

# Deliberately small. A symbol we do not know becomes an explicit failure the user is asked
# about, which is better than guessing wrong about money.
_CURRENCY_SYMBOLS: dict[str, str] = {
    "$": "USD",
    "US$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "Rs.": "INR",
    "Rs": "INR",
    "₩": "KRW",
    "CHF": "CHF",
    "A$": "AUD",
    "C$": "CAD",
    "S$": "SGD",
}

_ISO_4217 = re.compile(r"\b([A-Z]{3})\b")
# A number with optional sign, optional thousands separators, optional decimals.
_NUMBER = re.compile(r"[-+]?\d[\d,\s]*(?:\.\d+)?|[-+]?\.\d+")
# Trailing minus and parenthesised negatives, both common in financial documents.
_PARENTHESISED = re.compile(r"^\(\s*(.+?)\s*\)$")


def _parse_number(raw: str) -> tuple[float, Interpretation] | None:
    """Pull a number out of a string, tolerating the ways documents write them."""
    text = raw.strip()
    if not text:
        return None

    negative = False
    parenthesised = _PARENTHESISED.match(text)
    if parenthesised:  # "(1,234.00)" means -1234.00 in accounting notation
        text = parenthesised.group(1)
        negative = True
    if text.endswith("-"):  # "1234.00-" is a trailing-minus negative
        text = text[:-1]
        negative = True

    match = _NUMBER.search(text)
    if not match:
        return None

    digits = match.group(0).replace(",", "").replace(" ", "")
    try:
        number = float(digits)
    except ValueError:
        return None
    if negative:
        number = -abs(number)

    # Exact only if the ENTIRE raw string was the number, with no surrounding
    # whitespace, no thousands separators, and no sign notation to undo. Comparing
    # against `raw` rather than `raw.strip()` is the point: comparing against the
    # stripped value would make stripping undetectable.
    exact = match.group(0) == raw and "," not in raw and not negative
    return number, (Interpretation.EXACT if exact else Interpretation.NORMALISED)


def _coerce_currency(raw: Any, spec: FieldSpec) -> Coerced:
    if isinstance(raw, dict):
        amount_raw = raw.get("amount")
        code_raw = raw.get("currency") or raw.get("code")
        if amount_raw is None:
            return Coerced(None, Interpretation.FAILED, error="currency object has no amount")
        parsed = (
            (float(amount_raw), Interpretation.EXACT)
            if isinstance(amount_raw, (int, float)) and not isinstance(amount_raw, bool)
            else _parse_number(str(amount_raw))
        )
        if parsed is None:
            return Coerced(None, Interpretation.FAILED, error=f"unreadable amount {amount_raw!r}")
        amount, interpretation = parsed

        if isinstance(code_raw, str) and len(code_raw.strip()) == 3:
            code = code_raw.strip().upper()
        elif spec.currency_default:
            code = spec.currency_default
            interpretation = Interpretation.INFERRED
            return Coerced(
                CurrencyAmount(amount=amount, currency=code).model_dump(),
                interpretation,
                note=f"no currency stated, assumed {code} from the field default",
            )
        else:
            return Coerced(
                None,
                Interpretation.FAILED,
                error="amount has no currency code and the field has no default",
            )
        return Coerced(CurrencyAmount(amount=amount, currency=code).model_dump(), interpretation)

    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if not spec.currency_default:
            return Coerced(
                None,
                Interpretation.FAILED,
                error="a bare number cannot be a currency without a field default code",
            )
        return Coerced(
            CurrencyAmount(amount=float(raw), currency=spec.currency_default).model_dump(),
            Interpretation.INFERRED,
            note=f"no currency stated, assumed {spec.currency_default} from the field default",
        )

    if not isinstance(raw, str):
        return Coerced(None, Interpretation.FAILED, error=f"cannot read {type(raw).__name__}")

    text = raw.strip()
    parsed = _parse_number(text)
    if parsed is None:
        return Coerced(None, Interpretation.FAILED, error=f"no amount found in {raw!r}")
    amount, interpretation = parsed

    # Prefer an explicit three letter code, then a symbol, then the field default.
    remainder = _NUMBER.sub("", text).strip()
    code: str | None = None
    note: str | None = None
    iso = _ISO_4217.search(remainder.upper())
    if iso:
        code = iso.group(1)
        interpretation = Interpretation.NORMALISED
    else:
        for symbol, mapped in sorted(_CURRENCY_SYMBOLS.items(), key=lambda kv: -len(kv[0])):
            if symbol in remainder:
                code = mapped
                interpretation = Interpretation.NORMALISED
                break
    if code is None:
        if not spec.currency_default:
            return Coerced(
                None,
                Interpretation.FAILED,
                error=f"no currency code or recognised symbol in {raw!r}, and no field default",
            )
        code = spec.currency_default
        interpretation = Interpretation.INFERRED
        note = f"no currency marker in {raw!r}, assumed {code} from the field default"

    return Coerced(
        CurrencyAmount(amount=amount, currency=code).model_dump(), interpretation, note=note
    )


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_MONTHS = {
    name.lower(): number
    for number, names in {
        1: ("jan", "january"),
        2: ("feb", "february"),
        3: ("mar", "march"),
        4: ("apr", "april"),
        5: ("may",),
        6: ("jun", "june"),
        7: ("jul", "july"),
        8: ("aug", "august"),
        9: ("sep", "sept", "september"),
        10: ("oct", "october"),
        11: ("nov", "november"),
        12: ("dec", "december"),
    }.items()
    for name in names
}

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_NUMERIC_DATE = re.compile(r"^(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4})$")
_TEXT_DATE = re.compile(
    r"^(?:(\d{1,2})\s+)?([A-Za-z]{3,9})\.?\s+(?:(\d{1,2}),?\s+)?(\d{2,4})$",
)


def _two_digit_year(year: int) -> int:
    """Expand a two digit year. Explicit rule, so the behaviour is testable."""
    return 2000 + year if year < 70 else 1900 + year


def _coerce_date(raw: Any) -> Coerced:
    if isinstance(raw, date):
        return Coerced(raw.isoformat(), Interpretation.EXACT)
    if not isinstance(raw, str):
        return Coerced(None, Interpretation.FAILED, error=f"cannot read {type(raw).__name__}")

    text = raw.strip()
    if not text:
        return Coerced(None, Interpretation.FAILED, error="empty date")

    if iso := _ISO_DATE.match(text):
        year, month, day = (int(part) for part in iso.groups())
        try:
            return Coerced(date(year, month, day).isoformat(), Interpretation.EXACT)
        except ValueError as exc:
            return Coerced(None, Interpretation.FAILED, error=str(exc))

    if numeric := _NUMERIC_DATE.match(text):
        first, second, third = (int(part) for part in numeric.groups())
        # `ambiguous` is an explicit flag, NOT a substring test on an explanatory string.
        # The earlier version tested `"ambiguous" in why`, which was true for the string
        # "unambiguous" as well, and so reported every clear date as a guess.
        ambiguous = False

        if first > 31:
            # A leading component above 31 can only be a year.
            year, month, day = first, second, third
        elif third > 31 or len(numeric.group(3)) == 4:
            year = third if third > 99 else _two_digit_year(third)
            if first > 12 and second <= 12:
                month, day = second, first  # 25/03/2026: the 25 must be the day
            elif second > 12 and first <= 12:
                month, day = first, second  # 03/25/2026: the 25 must be the day
            else:
                # Both components are 12 or below, so the order is genuinely undecidable
                # from the value alone. Choose day-first, the majority convention
                # worldwide, and SAY SO, so the user can correct it in one click.
                # Guessing silently is the exact failure mode this project exists to
                # avoid, so the choice is surfaced rather than buried.
                month, day, ambiguous = second, first, True
        else:
            year = _two_digit_year(third)
            month, day, ambiguous = second, first, True

        try:
            resolved = date(year, month, day)
        except ValueError as exc:
            return Coerced(None, Interpretation.FAILED, error=f"{raw!r}: {exc}")
        if ambiguous:
            return Coerced(
                resolved.isoformat(),
                Interpretation.INFERRED,
                note=f"{raw!r} does not say which component is the day, read as "
                f"day before month",
            )
        return Coerced(resolved.isoformat(), Interpretation.NORMALISED)

    if textual := _TEXT_DATE.match(text):
        day_before, month_name, day_after, year_raw = textual.groups()
        month = _MONTHS.get(month_name.lower())
        if month is None:
            return Coerced(None, Interpretation.FAILED, error=f"unknown month {month_name!r}")
        day_str = day_before or day_after
        if day_str is None:
            return Coerced(None, Interpretation.FAILED, error=f"no day of month in {raw!r}")
        year = int(year_raw)
        if year < 100:
            year = _two_digit_year(year)
        try:
            return Coerced(
                date(year, month, int(day_str)).isoformat(), Interpretation.NORMALISED
            )
        except ValueError as exc:
            return Coerced(None, Interpretation.FAILED, error=f"{raw!r}: {exc}")

    return Coerced(None, Interpretation.FAILED, error=f"unrecognised date format: {raw!r}")


# ---------------------------------------------------------------------------
# Everything else
# ---------------------------------------------------------------------------

_TRUE = {"true", "yes", "y", "1", "paid", "on", "checked", "✓", "x"}
_FALSE = {"false", "no", "n", "0", "unpaid", "off", "unchecked", ""}


def _coerce_boolean(raw: Any) -> Coerced:
    if isinstance(raw, bool):
        return Coerced(raw, Interpretation.EXACT)
    if isinstance(raw, (int, float)):
        return Coerced(bool(raw), Interpretation.NORMALISED)
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in _TRUE:
            return Coerced(True, Interpretation.NORMALISED)
        if text in _FALSE:
            return Coerced(False, Interpretation.NORMALISED)
    return Coerced(None, Interpretation.FAILED, error=f"not a boolean: {raw!r}")


def _coerce_enum(raw: Any, spec: FieldSpec) -> Coerced:
    permitted = spec.enum_values or []
    if not isinstance(raw, str):
        return Coerced(None, Interpretation.FAILED, error=f"enum value must be text, got {raw!r}")
    text = raw.strip()
    if text in permitted:
        return Coerced(text, Interpretation.EXACT)
    folded = {value.casefold(): value for value in permitted}
    if text.casefold() in folded:
        return Coerced(folded[text.casefold()], Interpretation.NORMALISED)
    return Coerced(
        None,
        Interpretation.FAILED,
        error=f"{raw!r} is not one of the permitted values {permitted}",
    )


def _coerce_string_list(raw: Any) -> Coerced:
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
        return Coerced(items, Interpretation.EXACT if items == raw else Interpretation.NORMALISED)
    if isinstance(raw, str):
        parts = [part.strip() for part in re.split(r"[,;\n]", raw) if part.strip()]
        if not parts:
            return Coerced(None, Interpretation.FAILED, error="empty list")
        return Coerced(parts, Interpretation.NORMALISED)
    return Coerced(None, Interpretation.FAILED, error=f"not a list: {raw!r}")


def _coerce_number(raw: Any) -> Coerced:
    if isinstance(raw, bool):
        return Coerced(None, Interpretation.FAILED, error="a boolean is not a number")
    if isinstance(raw, (int, float)):
        return Coerced(float(raw), Interpretation.EXACT)
    if isinstance(raw, str):
        parsed = _parse_number(raw)
        if parsed is None:
            return Coerced(None, Interpretation.FAILED, error=f"no number in {raw!r}")
        return Coerced(parsed[0], parsed[1])
    return Coerced(None, Interpretation.FAILED, error=f"not a number: {raw!r}")


def _coerce_string(raw: Any) -> Coerced:
    if isinstance(raw, str):
        trimmed = " ".join(raw.split())
        return Coerced(
            trimmed, Interpretation.EXACT if trimmed == raw else Interpretation.NORMALISED
        )
    if isinstance(raw, (int, float, bool)):
        return Coerced(str(raw), Interpretation.NORMALISED)
    if isinstance(raw, list):
        return Coerced(", ".join(str(item) for item in raw), Interpretation.NORMALISED)
    return Coerced(None, Interpretation.FAILED, error=f"cannot read {type(raw).__name__}")


def coerce(raw: Any, spec: FieldSpec) -> Coerced:
    """Coerce ``raw`` into the stored representation for ``spec.type``.

    ``None`` passes through as an absent value, which is a legitimate answer and not a
    failure: the model is instructed to return null rather than guess.
    """
    if raw is None:
        return Coerced(None, Interpretation.EXACT)
    if isinstance(raw, str) and not raw.strip():
        return Coerced(None, Interpretation.EXACT)

    match spec.type:
        case FieldType.STRING:
            return _coerce_string(raw)
        case FieldType.NUMBER:
            return _coerce_number(raw)
        case FieldType.CURRENCY:
            return _coerce_currency(raw, spec)
        case FieldType.DATE:
            return _coerce_date(raw)
        case FieldType.BOOLEAN:
            return _coerce_boolean(raw)
        case FieldType.ENUM:
            return _coerce_enum(raw, spec)
        case FieldType.STRING_LIST:
            return _coerce_string_list(raw)
