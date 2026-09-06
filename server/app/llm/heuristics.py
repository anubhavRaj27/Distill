"""Deterministic extraction from document text, with no model involved.

This is what the fake provider uses when it has no recorded response to replay, and it is
the reason Distill is fully demonstrable with no API key (decision D11).

It is a heuristic and it says so. Two properties make it worth having rather than a stub.

**Its evidence quotes are verbatim from the parsed page.** So grounding really runs, really
finds the words, and really produces highlight boxes. The offline mode exercises the trust
machinery end to end instead of bypassing it, which means the review queue, the confidence
tiers, and the provenance viewer can all be developed and demonstrated before a key exists.

**Its confidence values are modest on purpose.** A regular expression that found
``Total Due: $12,480.50`` deserves about 0.55, not 0.95. Tiers therefore land in medium and
low, the review queue fills up, and the interface shows an honest picture of a system that
is guessing rather than a falsely confident one.

Two shapes are recognised, which between them cover the sample corpus:

* ``Label: value`` lines, which is how invoices, receipts, and purchase orders read
* pipe-delimited rows under a header row, which is what the spreadsheet and comma-separated
  parsers render, so tabular documents work too
"""

from __future__ import annotations

import re

from app.domain.document import ParsedDocument, ParsedPage
from app.domain.fields import FieldType, validate_field_key
from app.llm.contracts import ExtractedField, OpenExtraction

# "Supplier: Northwind Traders" or "Invoice Number - INV-2026-0042".
# The label is bounded to 40 characters so a long prose sentence containing a colon is not
# mistaken for a field.
# The separator class covers a colon, an en dash (\u2013), and an em dash (\u2014), because
# documents use all three between a label and its value. Written as escapes rather than
# literal characters so the two dashes are unambiguous to a reader and to the linter.
_LABEL_VALUE = re.compile(
    r"^\s*(?P<label>[A-Za-z][A-Za-z0-9 /&._'()-]{1,40}?)"
    r"\s*[:\u2013\u2014]\s*"
    r"(?P<value>\S.*?)\s*$"
)
_TABLE_ROW = re.compile(r"\s\|\s")

_CURRENCY_MARKER = re.compile(r"[$€£¥₹]|\b(?:USD|EUR|GBP|INR|JPY|AUD|CAD|SGD|CHF)\b", re.I)
_NUMBER_ONLY = re.compile(r"^[-+(]?\s*\d[\d,\s]*(?:\.\d+)?\s*\)?-?$")
_MONTH_NAMES = (
    "jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august"
    "|sep|sept|september|oct|october|nov|november|dec|december"
)
# The textual branch requires an actual MONTH NAME, not any three-to-nine letter word.
# Without that, "Net 30" reads as a date, which then coerces to a failure and drags a
# perfectly good payment-terms field down to the low tier for no reason.
_DATE_LIKE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}"
    r"|\d{4}[/.\-]\d{1,2}[/.\-]\d{1,2}"
    rf"|(?:\d{{1,2}}\s+)?(?:{_MONTH_NAMES})\.?\s+(?:\d{{1,2}},?\s+)?\d{{2,4}})$",
    re.IGNORECASE,
)
_BOOLEAN_WORDS = {"yes", "no", "true", "false", "paid", "unpaid", "y", "n"}

# Labels that are structure rather than data. A line reading "Description: ..." is prose,
# and "Notes: ..." is commentary, so neither becomes a queryable column by default.
_IGNORED_LABELS = {"description", "notes", "note", "comments", "comment", "terms", "remarks"}

OFFLINE_CONFIDENCE_LABELLED = 0.55
OFFLINE_CONFIDENCE_TABULAR = 0.5
MAX_VALUE_LENGTH = 160
TABLE_ROWS_CONSIDERED = 5
"""How many data rows to consider when choosing the most populated one."""


def slugify_key(label: str) -> str:
    """A field key from a document's own label text.

    Guaranteed to satisfy ``validate_field_key``, because that function is the gate a field
    key must pass before it can reach a generated view (review finding 8.1), and producing
    something it would reject would simply move the failure later.
    """
    lowered = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    if not lowered:
        lowered = "field"
    if not lowered[0].isalpha():
        lowered = f"f_{lowered}"
    candidate = lowered[:47].rstrip("_") or "field"
    try:
        return validate_field_key(candidate)
    except ValueError:
        # Reserved word, or otherwise refused. Suffixing keeps the user's wording visible
        # while making the key legal.
        return validate_field_key(f"{candidate[:42]}_value")


def infer_type(value: str) -> FieldType:
    """Guess a field type from how the value is written."""
    text = value.strip()
    if not text:
        return FieldType.STRING
    if _CURRENCY_MARKER.search(text) and re.search(r"\d", text):
        return FieldType.CURRENCY
    if _DATE_LIKE.match(text):
        return FieldType.DATE
    if _NUMBER_ONLY.match(text):
        return FieldType.NUMBER
    if text.lower() in _BOOLEAN_WORDS:
        return FieldType.BOOLEAN
    return FieldType.STRING


def _is_tabular_page(page: ParsedPage) -> bool:
    """Whether a page looks like rendered rows and columns."""
    rows = [line.text for line in page.lines if line.text.strip()]
    if len(rows) < 2:
        return False
    delimited = sum(1 for row in rows if _TABLE_ROW.search(row))
    return delimited >= max(2, len(rows) // 2)


def _fields_from_labelled_lines(page: ParsedPage) -> list[ExtractedField]:
    found: list[ExtractedField] = []
    for line in page.lines:
        match = _LABEL_VALUE.match(line.text)
        if not match:
            continue
        label = match.group("label").strip()
        value = match.group("value").strip()
        if not value or len(value) > MAX_VALUE_LENGTH:
            continue
        if label.lower() in _IGNORED_LABELS:
            continue
        # A "value" that is itself several words of prose with no digits is usually a
        # sentence rather than a field. Vendor names are the exception worth allowing, so
        # the cut-off is generous.
        if len(value.split()) > 8 and not re.search(r"\d", value):
            continue

        found.append(
            ExtractedField(
                key=slugify_key(label),
                label=label,
                value_text=value,
                value_type=infer_type(value),
                # The quote is the WHOLE line, verbatim. That is what makes grounding
                # genuinely succeed offline and produce a real highlight.
                evidence_quote=line.text.strip()[:300],
                page_index=page.index,
                confidence=OFFLINE_CONFIDENCE_LABELLED,
                reasoning=(
                    f"Offline heuristic: the line reads {line.text.strip()[:80]!r}, so "
                    f"{label!r} was read as a field."
                ),
            )
        )
    return found


def _fields_from_table(page: ParsedPage) -> list[ExtractedField]:
    """Read a rendered table: first row is the header, the next row supplies the values.

    ONE data row is used, chosen as the most populated of the first few. A document
    rendered as a table with many rows is a ledger, and one record per document (the model
    in ``app.db.models``) means a ledger's later rows cannot become separate records. Using
    the fullest early row gives the user something real to look at, and the rest of the
    sheet remains searchable through the raw page text. This is a documented limit of the
    OFFLINE mode, not of the product: a real model call reads the whole sheet.
    """
    rows = [line for line in page.lines if line.text.strip()]
    if len(rows) < 2:
        return []

    headers = [cell.strip() for cell in rows[0].text.split(" | ")]
    if len(headers) < 2:
        return []

    # Pick the most POPULATED of the first few data rows, not simply the first. A bank
    # statement's opening row has no debit, credit, or description, so taking row two
    # blindly yielded two fields from a five column sheet and made the document look far
    # emptier than it is.
    candidates = rows[1 : 1 + TABLE_ROWS_CONSIDERED]
    if not candidates:
        return []
    chosen = max(
        candidates,
        key=lambda line: sum(1 for cell in line.text.split(" | ") if cell.strip()),
    )
    values = [cell.strip() for cell in chosen.text.split(" | ")]

    found: list[ExtractedField] = []
    used: set[str] = set()
    for header, value in zip(headers, values, strict=False):
        if not header or not value or len(value) > MAX_VALUE_LENGTH:
            continue
        if header.lower() in _IGNORED_LABELS:
            continue
        key = slugify_key(header)
        if key in used:
            continue
        used.add(key)
        found.append(
            ExtractedField(
                key=key,
                label=header,
                value_text=value,
                value_type=infer_type(value),
                evidence_quote=chosen.text.strip()[:300],
                page_index=page.index,
                confidence=OFFLINE_CONFIDENCE_TABULAR,
                reasoning=(
                    f"Offline heuristic: column {header!r} of the first data row on "
                    f"{page.locator or f'page {page.index + 1}'}."
                ),
            )
        )
    return found


_KIND_MARKERS: tuple[tuple[str, str], ...] = (
    ("purchase order", "purchase order"),
    ("bank statement", "bank statement"),
    ("statement of account", "bank statement"),
    ("opening balance", "bank statement"),
    ("credit note", "credit note"),
    ("tax invoice", "invoice"),
    ("invoice", "invoice"),
    ("receipt", "receipt"),
    ("quotation", "quotation"),
)

HEADING_CHARACTERS = 200
"""How much of the first page counts as the heading. A document states its own type at the
top, so a marker there is far stronger evidence than the same words buried in a field label
further down."""

HEADING_WEIGHT = 10


def _guess_document_kind(document: ParsedDocument) -> str:
    """Score each candidate kind, weighting the heading heavily.

    Scoring rather than first-match, because first-match got this wrong in an obvious way:
    an invoice that happens to cite a purchase order number on page two was classified as a
    purchase order. A document announces what it is at the top, so that is where the
    evidence is.
    """
    if not document.pages:
        return "document"

    full_text = " ".join(page.text for page in document.pages).lower()
    heading = document.pages[0].text[:HEADING_CHARACTERS].lower()

    scores: dict[str, int] = {}
    for marker, kind in _KIND_MARKERS:
        score = full_text.count(marker) + HEADING_WEIGHT * heading.count(marker)
        if score:
            scores[kind] = scores.get(kind, 0) + score

    if not scores:
        return "document"
    return max(scores.items(), key=lambda entry: entry[1])[0]


def extract_offline(document: ParsedDocument) -> OpenExtraction:
    """Extract fields from ``document`` with no model call.

    Deduplicates by key, keeping the first occurrence, because a value repeated in a header
    and a footer is one field rather than two.
    """
    collected: list[ExtractedField] = []
    seen: set[str] = set()

    for page in document.pages:
        page_fields = (
            _fields_from_table(page) if _is_tabular_page(page) else []
        ) + _fields_from_labelled_lines(page)
        for field in page_fields:
            if field.key in seen:
                continue
            seen.add(field.key)
            collected.append(field)

    return OpenExtraction(document_kind=_guess_document_kind(document), fields=collected)
