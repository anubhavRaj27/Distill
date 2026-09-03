"""The offline mode: heuristics plus the fake provider.

This suite matters more than its subject sounds. The offline mode is how the pipeline, the
confidence tiers, the review queue, and the provenance viewer are all developed and
demonstrated before a Gemini key exists (decision D13), so if it stops producing realistic
output, everything downstream stops being verifiable.
"""

from __future__ import annotations

import json

import pytest
from app.config import Settings
from app.domain.document import SourceFormat
from app.domain.fields import FieldSpec, FieldType, validate_field_key
from app.llm.base import CallKind, LLMRequest
from app.llm.contracts import GuidedExtraction, OpenExtraction
from app.llm.fake import FakeClient, fixture_key_for_document, write_fixture
from app.llm.heuristics import extract_offline, infer_type, slugify_key
from app.pipeline.parse.router import parse

from tests.fixtures.documents import (
    CSV_STATEMENT,
    TXT_RECEIPT,
    docx_invoice,
    xlsx_ledger,
)
from tests.fixtures.pdfs import invoice_like_pdf


@pytest.fixture(scope="module")
def parse_settings() -> Settings:
    return Settings(llm_provider="fake")


def _parsed(data: bytes, source_format: SourceFormat, settings: Settings):
    document, _images = parse(data, source_format, settings)
    return document


# ---------------------------------------------------------------------------
# Key generation, which feeds a generated view and so must always be safe
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Supplier", "supplier"),
        ("Invoice Number", "invoice_number"),
        ("Total Due", "total_due"),
        ("Bill-To Name", "bill_to_name"),
        ("Amount (USD)", "amount_usd"),
        ("VAT %", "vat"),
        ("  spaced  out  ", "spaced_out"),
    ],
)
def test_labels_become_readable_keys(label: str, expected: str) -> None:
    assert slugify_key(label) == expected


@pytest.mark.parametrize(
    "label",
    [
        "Select",
        "record_id",
        "created_at",
        '"; DROP TABLE field_values --',
        "123",
        "",
        "table",
        "x" * 200,
    ],
)
def test_every_generated_key_passes_the_injection_guard(label: str) -> None:
    """Review finding 8.1: a field key becomes a column name in a generated view.

    Keys come from document labels, so a label containing a quotation mark or a reserved
    word must never produce a key that the view generator would accept.
    """
    validate_field_key(slugify_key(label))


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("$12,480.50", FieldType.CURRENCY),
        ("EUR 3,410.00", FieldType.CURRENCY),
        ("1250.75", FieldType.NUMBER),
        ("2026-03-14", FieldType.DATE),
        ("14 March 2026", FieldType.DATE),
        ("03/04/2026", FieldType.DATE),
        ("Paid", FieldType.BOOLEAN),
        ("Northwind Traders Pvt Ltd", FieldType.STRING),
        ("Net 30", FieldType.STRING),
        ("Smarch 30", FieldType.STRING),
    ],
)
def test_value_types_are_inferred_from_how_the_value_is_written(
    value: str, expected: FieldType
) -> None:
    assert infer_type(value) is expected


def test_net_30_is_not_a_date() -> None:
    """Regression. The textual-date pattern originally accepted any word plus a number,
    so payment terms read as a date, failed coercion, and dragged a good field to low."""
    assert infer_type("Net 30") is FieldType.STRING


# ---------------------------------------------------------------------------
# Open extraction
# ---------------------------------------------------------------------------


def test_open_extraction_finds_labelled_fields_in_a_pdf(parse_settings: Settings) -> None:
    result = extract_offline(_parsed(invoice_like_pdf(), SourceFormat.PDF, parse_settings))
    keys = {field.key for field in result.fields}
    assert {"supplier", "invoice_number", "issue_date", "total_due"} <= keys
    assert result.document_kind == "invoice"


def test_document_kind_uses_the_heading_not_a_passing_mention(
    parse_settings: Settings,
) -> None:
    """Regression. The fixture invoice cites a purchase order number on page two, which
    first-match scoring classified as a purchase order."""
    result = extract_offline(_parsed(invoice_like_pdf(), SourceFormat.PDF, parse_settings))
    assert result.document_kind == "invoice"


def test_a_bank_statement_is_recognised_as_one(parse_settings: Settings) -> None:
    """The document that cannot be forced into an invoice schema. It is the whole point."""
    result = extract_offline(_parsed(CSV_STATEMENT, SourceFormat.CSV, parse_settings))
    assert result.document_kind == "bank statement"
    assert "supplier" not in {field.key for field in result.fields}
    assert "vendor" not in {field.key for field in result.fields}


def test_every_evidence_quote_appears_verbatim_in_the_document(
    parse_settings: Settings,
) -> None:
    """The property that makes offline provenance real rather than stubbed.

    If a quote is not literally present in the page text, grounding cannot locate it, and
    the whole trust story would be a mock in offline mode.
    """
    for data, source_format in [
        (invoice_like_pdf(), SourceFormat.PDF),
        (docx_invoice(), SourceFormat.DOCX),
        (xlsx_ledger(), SourceFormat.XLSX),
        (CSV_STATEMENT, SourceFormat.CSV),
        (TXT_RECEIPT, SourceFormat.TEXT),
    ]:
        document = _parsed(data, source_format, parse_settings)
        page_text = {page.index: page.text for page in document.pages}
        for field in extract_offline(document).fields:
            assert field.evidence_quote
            assert field.evidence_quote in page_text[field.page_index], (
                f"quote {field.evidence_quote!r} is not on page {field.page_index}"
            )


def test_offline_confidence_is_modest_so_tiers_are_honest(
    parse_settings: Settings,
) -> None:
    """A regular expression does not deserve 0.95. Tiers must land in medium and low."""
    for field in extract_offline(
        _parsed(invoice_like_pdf(), SourceFormat.PDF, parse_settings)
    ).fields:
        assert 0.3 <= field.confidence <= 0.7


def test_prose_labels_are_not_turned_into_columns(parse_settings: Settings) -> None:
    """'Description:' and 'Notes:' are commentary, not queryable fields."""
    result = extract_offline(_parsed(invoice_like_pdf(), SourceFormat.PDF, parse_settings))
    keys = {field.key for field in result.fields}
    assert "description" not in keys
    assert "notes" not in keys


def test_a_tabular_document_reads_its_columns_as_fields(parse_settings: Settings) -> None:
    result = extract_offline(_parsed(xlsx_ledger(), SourceFormat.XLSX, parse_settings))
    keys = {field.key for field in result.fields}
    assert {"vendor", "invoice_no", "amount"} <= keys


def test_the_most_populated_early_row_is_used_not_simply_the_first(
    parse_settings: Settings,
) -> None:
    """Regression. The bank statement's opening row has no debit and no description, so
    always taking row two made a five column sheet look nearly empty."""
    result = extract_offline(_parsed(CSV_STATEMENT, SourceFormat.CSV, parse_settings))
    assert len(result.fields) >= 3


# ---------------------------------------------------------------------------
# The fake provider
# ---------------------------------------------------------------------------

SCHEMA = [
    FieldSpec(
        key="vendor_name",
        label="Vendor",
        type=FieldType.STRING,
        source_keys=["supplier"],
        description="Who issued the document",
    ),
    FieldSpec(key="invoice_number", label="Invoice Number", type=FieldType.STRING),
    FieldSpec(key="issue_date", label="Issue Date", type=FieldType.DATE),
    FieldSpec(
        key="total_due", label="Total Due", type=FieldType.CURRENCY, currency_default="USD"
    ),
]


def _guided_request(document: object) -> LLMRequest:
    return LLMRequest(
        kind=CallKind.GUIDED_EXTRACT,
        prompt="ignored offline",
        response_model=GuidedExtraction,
        fixture_key="none",
        context={"document": document, "schema": SCHEMA},
    )


async def test_guided_extraction_fills_the_schema_for_a_matching_document(
    parse_settings: Settings,
) -> None:
    client = FakeClient(parse_settings)
    document = _parsed(invoice_like_pdf(), SourceFormat.PDF, parse_settings)
    result = (await client.structured(_guided_request(document))).value
    assert isinstance(result, GuidedExtraction)

    values = {value.key: value.value_text for value in result.values}
    assert set(values) == {field.key for field in SCHEMA}, "every schema field is reported"
    assert values["vendor_name"] == "Northwind Traders Pvt Ltd"
    assert values["total_due"] == "$12,480.50"


async def test_an_approved_alias_keeps_working_on_later_documents(
    parse_settings: Settings,
) -> None:
    """``source_keys`` records a mapping the user already accepted.

    Without honouring it, the same rename would be re-proposed on every document, which is
    the opposite of what requirement FR-13 promises.
    """
    client = FakeClient(parse_settings)
    document = _parsed(invoice_like_pdf(), SourceFormat.PDF, parse_settings)
    result = (await client.structured(_guided_request(document))).value
    vendor = next(value for value in result.values if value.key == "vendor_name")
    assert vendor.value_text == "Northwind Traders Pvt Ltd"
    assert "supplier" not in {extra.key for extra in result.extra_fields}


async def test_unmatched_values_become_drift_candidates(parse_settings: Settings) -> None:
    """Requirement FR-13: a document with something to say the schema cannot record must
    surface it, not drop it."""
    client = FakeClient(parse_settings)
    document = _parsed(invoice_like_pdf(), SourceFormat.PDF, parse_settings)
    result = (await client.structured(_guided_request(document))).value
    extras = {extra.key for extra in result.extra_fields}
    assert "purchase_order_number" in extras
    assert "payment_terms" in extras


async def test_a_document_that_fits_nothing_reports_absence_rather_than_guessing(
    parse_settings: Settings,
) -> None:
    """The bank statement. Every schema field null, and its own fields offered as drift."""
    client = FakeClient(parse_settings)
    document = _parsed(CSV_STATEMENT, SourceFormat.CSV, parse_settings)
    result = (await client.structured(_guided_request(document))).value

    assert all(value.value_text is None for value in result.values), (
        "an invoice schema must not be force-fitted onto a bank statement"
    )
    assert result.extra_fields, "its own fields must be offered instead"


async def test_the_schema_decides_the_type_not_the_document(
    parse_settings: Settings,
) -> None:
    """A field the user agreed is a currency stays a currency."""
    client = FakeClient(parse_settings)
    document = _parsed(xlsx_ledger(), SourceFormat.XLSX, parse_settings)
    result = (await client.structured(_guided_request(document))).value
    for value in result.values:
        expected = next(field.type for field in SCHEMA if field.key == value.key)
        assert value.value_type is expected


async def test_a_recorded_fixture_is_replayed_in_preference_to_synthesising(
    parse_settings: Settings, tmp_path: object
) -> None:
    settings = parse_settings.model_copy(update={"llm_fixture_dir": tmp_path})
    client = FakeClient(settings)
    recorded = OpenExtraction(document_kind="recorded", fields=[])
    write_fixture(client.fixture_path(CallKind.OPEN_EXTRACT, "abc123"), recorded)

    request = LLMRequest(
        kind=CallKind.OPEN_EXTRACT,
        prompt="",
        response_model=OpenExtraction,
        fixture_key="abc123",
        context={},
    )
    result = (await client.structured(request)).value
    assert isinstance(result, OpenExtraction)
    assert result.document_kind == "recorded"


async def test_a_corrupt_fixture_names_the_file_rather_than_failing_obscurely(
    parse_settings: Settings, tmp_path: object
) -> None:
    from app.errors import LLMInvalidOutput

    settings = parse_settings.model_copy(update={"llm_fixture_dir": tmp_path})
    client = FakeClient(settings)
    path = client.fixture_path(CallKind.OPEN_EXTRACT, "broken")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fields": "not a list"}), encoding="utf-8")

    request = LLMRequest(
        kind=CallKind.OPEN_EXTRACT,
        prompt="",
        response_model=OpenExtraction,
        fixture_key="broken",
        context={},
    )
    with pytest.raises(LLMInvalidOutput) as raised:
        await client.structured(request)
    assert "broken.json" in str(raised.value)


async def test_a_call_kind_with_no_offline_answer_says_what_to_do(
    parse_settings: Settings,
) -> None:
    """Better than returning an empty result, which would look like a working extraction
    that found nothing."""
    from app.errors import LLMUnavailable

    client = FakeClient(parse_settings)
    request = LLMRequest(
        kind=CallKind.NL2SQL,
        prompt="",
        response_model=OpenExtraction,
        fixture_key="missing",
        context={},
    )
    with pytest.raises(LLMUnavailable) as raised:
        await client.structured(request)
    assert "GEMINI_API_KEY" in str(raised.value)


def test_fixture_keys_are_content_derived_not_prompt_derived() -> None:
    """Review finding 8.6. Editing a prompt must not invalidate every fixture."""
    first = fixture_key_for_document("a" * 64, CallKind.GUIDED_EXTRACT, 1)
    same = fixture_key_for_document("a" * 64, CallKind.GUIDED_EXTRACT, 1)
    other_document = fixture_key_for_document("b" * 64, CallKind.GUIDED_EXTRACT, 1)
    other_version = fixture_key_for_document("a" * 64, CallKind.GUIDED_EXTRACT, 2)

    assert first == same
    assert first != other_document, "a different document needs a different fixture"
    assert first != other_version, "a schema change needs a different fixture"
