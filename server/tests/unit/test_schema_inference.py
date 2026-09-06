"""Initial unification and drift. Decisions D18 and D27.

The behaviour these tests pin down is the product's central claim: many documents that
disagree with each other become one coherent schema, and the user is interrupted only where
a machine genuinely cannot decide.
"""

from __future__ import annotations

import pytest
from app.config import Settings
from app.domain.fields import FieldSpec, FieldType
from app.llm.contracts import ExtractedField
from app.llm.fake import FakeClient
from app.schema import embeddings
from app.schema.drift import (
    MAX_AUTO_ADDED_PER_DOCUMENT,
    assess,
    merged_schema,
)
from app.schema.propose import collect_observations, propose_initial
from app.schema.similarity import AskReason


@pytest.fixture(autouse=True)
def _clear_embedding_cache() -> None:
    embeddings.clear_cache()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(llm_provider="fake", llm_fixture_dir=tmp_path)


@pytest.fixture
def client(settings: Settings) -> FakeClient:
    return FakeClient(settings)


def _record_vectors(settings: Settings, vectors: dict[str, list[float]]) -> None:
    """Record embedding fixtures, which is what makes the semantic path testable offline."""
    import json

    path = settings.llm_fixture_dir / "embed" / "labels.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(vectors), encoding="utf-8")


def field(key: str, label: str, value: str, field_type: FieldType) -> ExtractedField:
    return ExtractedField(
        key=key, label=label, value_text=value, value_type=field_type, confidence=0.6
    )


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


def test_the_same_key_across_documents_becomes_one_observation() -> None:
    observations = collect_observations(
        {
            "a.pdf": [field("vendor_name", "Vendor", "Acme", FieldType.STRING)],
            "b.pdf": [field("vendor_name", "Vendor", "Globex", FieldType.STRING)],
            "c.pdf": [field("vendor_name", "Supplier", "Initech", FieldType.STRING)],
        }
    )
    assert len(observations) == 1
    assert observations[0].coverage == 3
    assert observations[0].label == "Vendor", "the most common label wins"


def test_a_field_seen_as_both_number_and_currency_is_treated_as_currency() -> None:
    """The currency reading carries strictly more information, so it is the safe canonical
    choice: a currency column can hold a bare amount, but a number column loses the code."""
    observations = collect_observations(
        {
            "a.pdf": [field("amount", "Amount", "100", FieldType.NUMBER)],
            "b.pdf": [field("amount", "Amount", "$100", FieldType.CURRENCY)],
        }
    )
    assert observations[0].dominant_type is FieldType.CURRENCY


def test_observations_are_ordered_by_coverage() -> None:
    observations = collect_observations(
        {
            "a.pdf": [
                field("rare", "Rare", "x", FieldType.STRING),
                field("common", "Common", "x", FieldType.STRING),
            ],
            "b.pdf": [field("common", "Common", "y", FieldType.STRING)],
        }
    )
    assert [o.key for o in observations] == ["common", "rare"]


# ---------------------------------------------------------------------------
# Initial unification, decision D27
# ---------------------------------------------------------------------------


async def test_identical_keys_unify_into_one_field(
    client: FakeClient, settings: Settings
) -> None:
    proposal = await propose_initial(
        {
            "a.pdf": [field("vendor_name", "Vendor", "Acme", FieldType.STRING)],
            "b.pdf": [field("vendor_name", "Vendor", "Globex", FieldType.STRING)],
        },
        client=client,
        settings=settings,
    )
    assert [f.key for f in proposal.fields] == ["vendor_name"]
    assert proposal.coverage["vendor_name"] == 2
    assert proposal.kept_separate == []


async def test_a_case_and_separator_variant_unifies_without_asking(
    client: FakeClient, settings: Settings
) -> None:
    proposal = await propose_initial(
        {
            "a.pdf": [field("vendor_name", "Vendor Name", "Acme", FieldType.STRING)],
            "b.pdf": [field("VENDOR-NAME", "VENDOR NAME", "Globex", FieldType.STRING)],
        },
        client=client,
        settings=settings,
    )
    assert len(proposal.fields) == 1
    assert proposal.kept_separate == []


async def test_a_semantic_rename_unifies_when_vectors_are_recorded(
    settings: Settings,
) -> None:
    """Decision D27's demo path: ``Supplier`` and ``Vendor`` merging automatically.

    This is also the test that proves recorded vectors are what make the offline path
    behave like the online one (decision D11).
    """
    _record_vectors(
        settings,
        {"Vendor": [1.0, 0.0, 0.0], "Supplier": [0.999, 0.01, 0.0], "Total Due": [0.0, 0.0, 1.0]},
    )
    client = FakeClient(settings)

    proposal = await propose_initial(
        {
            "a.pdf": [field("vendor", "Vendor", "Acme", FieldType.STRING)],
            "b.pdf": [field("supplier", "Supplier", "Globex", FieldType.STRING)],
        },
        client=client,
        settings=settings,
    )
    assert len(proposal.fields) == 1, "Supplier and Vendor are one field"
    unified = proposal.fields[0]
    assert "supplier" in unified.source_keys, (
        "the absorbed spelling must be recorded, or the rename is re-proposed forever"
    )


async def test_an_uncertain_pair_stays_split_and_is_recorded(
    client: FakeClient, settings: Settings
) -> None:
    """Decision D27. A wrong merge commingles two fields' values and unpicking it
    needs per-value provenance; a wrong split is a lossless move, so prefer the cheaper
    undo. v2 no longer ASKS about it: both fields exist and the near-miss is recorded so
    the change summary can explain it."""
    proposal = await propose_initial(
        {
            "a.pdf": [field("invoice_number", "Invoice Number", "INV-1", FieldType.STRING)],
            "b.pdf": [field("invoice_no", "Invoice No", "INV-2", FieldType.STRING)],
        },
        client=client,
        settings=settings,
    )
    assert len(proposal.fields) == 2, "uncertain unification must NOT merge"
    assert len(proposal.kept_separate) == 1
    entry = proposal.kept_separate[0]
    assert {entry.left_key, entry.right_key} == {"invoice_number", "invoice_no"}
    # The summary is the only account the user gets of how the schema formed, so it has to
    # name the pair rather than merely counting it.
    assert "Invoice No" in proposal.summary and "Invoice Number" in proposal.summary


async def test_unrelated_fields_are_not_recorded_as_near_misses(
    client: FakeClient, settings: Settings
) -> None:
    """Regression. Treating 'nothing resembles this, and we had no vector to confirm it' as
    a judgment call described nearly every field in the batch as a near-miss, pairing
    unrelated things like ``vendor`` with ``invoice_no``. In v2 that noise would land in the
    change summary, which is the user's only explanation, so it matters more not less."""
    proposal = await propose_initial(
        {
            "a.pdf": [
                field("vendor_name", "Vendor", "Acme", FieldType.STRING),
                field("total_due", "Total Due", "$1", FieldType.CURRENCY),
                field("issue_date", "Issue Date", "2026-01-01", FieldType.DATE),
                field("payment_terms", "Payment Terms", "Net 30", FieldType.STRING),
            ]
        },
        client=client,
        settings=settings,
    )
    assert len(proposal.fields) == 4
    noted = [(entry.left_key, entry.right_key) for entry in proposal.kept_separate]
    assert proposal.kept_separate == [], f"unrelated fields must not be paired; got {noted}"


async def test_currency_and_date_fields_get_a_higher_review_weight(
    client: FakeClient, settings: Settings
) -> None:
    """The review queue orders by weight times uncertainty, and money is what a finance
    operations person is actually accountable for."""
    proposal = await propose_initial(
        {
            "a.pdf": [
                field("total_due", "Total Due", "$1", FieldType.CURRENCY),
                field("note", "Note", "hello", FieldType.STRING),
            ]
        },
        client=client,
        settings=settings,
    )
    weights = {f.key: f.weight for f in proposal.fields}
    assert weights["total_due"] > weights["note"]


async def test_an_empty_batch_produces_an_empty_proposal_rather_than_failing(
    client: FakeClient, settings: Settings
) -> None:
    proposal = await propose_initial({}, client=client, settings=settings)
    assert proposal.fields == []


async def test_a_currency_field_is_given_a_default_code(
    client: FakeClient, settings: Settings
) -> None:
    """Without a default, every bare amount in every later document fails coercion and
    lands in the low tier for a reason the user cannot act on."""
    proposal = await propose_initial(
        {"a.pdf": [field("total_due", "Total Due", "$1", FieldType.CURRENCY)]},
        client=client,
        settings=settings,
    )
    assert proposal.fields[0].currency_default == "USD"


# ---------------------------------------------------------------------------
# Drift, decisions D27 and D18
# ---------------------------------------------------------------------------

SCHEMA = [
    FieldSpec(
        key="vendor_name", label="Vendor", type=FieldType.STRING, source_keys=["supplier"]
    ),
    FieldSpec(key="invoice_number", label="Invoice Number", type=FieldType.STRING),
    FieldSpec(
        key="total_due", label="Total Due", type=FieldType.CURRENCY, currency_default="USD"
    ),
]


async def test_no_extra_fields_means_no_schema_change(
    client: FakeClient, settings: Settings
) -> None:
    outcome = await assess([], SCHEMA, client=client, settings=settings)
    assert not outcome.changes_the_schema
    assert outcome.summary == "No schema change."


async def test_an_already_approved_alias_auto_maps_and_never_asks_again(
    client: FakeClient, settings: Settings
) -> None:
    """``source_keys`` records a decision the user already made. Re-asking is the opposite
    of what requirement FR-13 promises."""
    outcome = await assess(
        [field("supplier", "Supplier", "Acme", FieldType.STRING)],
        SCHEMA,
        client=client,
        settings=settings,
    )
    assert outcome.mappings == {"supplier": "vendor_name"}
    assert outcome.separations == []


async def test_an_exact_name_match_auto_maps(client: FakeClient, settings: Settings) -> None:
    outcome = await assess(
        [field("TOTAL-DUE", "Total Due", "$5", FieldType.CURRENCY)],
        SCHEMA,
        client=client,
        settings=settings,
    )
    assert outcome.mappings.get("total_due") == "total_due"


async def test_a_clearly_novel_field_auto_adds_and_enters_the_schema(
    settings: Settings,
) -> None:
    _record_vectors(
        settings,
        {
            "Vendor": [1.0, 0.0, 0.0, 0.0],
            "Invoice Number": [0.0, 1.0, 0.0, 0.0],
            "Total Due": [0.0, 0.0, 1.0, 0.0],
            "Shipping Weight": [0.0, 0.0, 0.0, 1.0],
        },
    )
    client = FakeClient(settings)
    outcome = await assess(
        [field("shipping_weight", "Shipping Weight", "42", FieldType.NUMBER)],
        SCHEMA,
        client=client,
        settings=settings,
    )
    assert [f.key for f in outcome.additions] == ["shipping_weight"]
    assert outcome.separations == [], "a clearly novel field is not a near-miss"

    widened = merged_schema(SCHEMA, outcome)
    assert "shipping_weight" in {f.key for f in widened}
    assert len(widened) == len(SCHEMA) + 1


async def test_an_unconfirmable_field_is_added_separately_and_the_reason_recorded(
    client: FakeClient, settings: Settings
) -> None:
    """Decision D27. With no vector we cannot rule out a semantic rename, so the field is
    added on its own rather than merged into a candidate.

    v1 asked the user about this. v2 does not ask anyone anything, so the honest outcome is
    the safe action plus an accurate note: the change summary must say we could not check
    for a meaning-based match, not that the match was "too close to call", because those
    are different situations and only one of them is true here.
    """
    outcome = await assess(
        [field("shipping_weight", "Shipping Weight", "42", FieldType.NUMBER)],
        SCHEMA,
        client=client,
        settings=settings,
    )
    assert [f.key for f in outcome.additions] == ["shipping_weight"]
    assert [s.field_key for s in outcome.separations] == ["shipping_weight"]
    assert outcome.separations[0].why is AskReason.UNCONFIRMED_NOVELTY
    assert "meaning-based" in outcome.summary
    assert "too close to call" not in outcome.summary


async def test_a_separation_records_the_field_it_was_nearly_merged_with(
    client: FakeClient, settings: Settings
) -> None:
    """The interface offers a merge for exactly these pairs (requirement FR-15), so the
    nearest candidate has to be recorded rather than only the fact of a near-miss."""
    outcome = await assess(
        [field("supplier_co", "Supplier Co", "Acme", FieldType.STRING)],
        SCHEMA,
        client=client,
        settings=settings,
    )
    assert outcome.separations
    separation = outcome.separations[0]
    assert separation.field_key == "supplier_co"
    assert separation.nearest_key in {field_spec.key for field_spec in SCHEMA}
    assert 0.0 < separation.score <= 1.0
    assert separation.explanation


async def test_a_document_cannot_widen_the_schema_without_limit(
    settings: Settings,
) -> None:
    """A document wanting twenty new columns is a different kind of document, and widening
    everyone else's table by twenty mostly-empty columns is not the answer."""
    # Genuinely unrelated names, not "Novel Field 1..N". Numbered variants of one name are
    # near-identical on string similarity, so they correctly auto-map onto each other and
    # would never reach the cap: the test would pass or fail for the wrong reason.
    novel_labels = [
        "Shipping Weight", "Carrier", "Tracking Code", "Pallet Count",
        "Customs Value", "Incoterms", "Port Of Loading", "Vessel Name",
        "Container Seal", "Gross Tonnage", "Insurance Policy", "Broker Licence",
        "Duty Rate", "Origin Country", "Harmonised Code", "Warehouse Bay",
    ]
    assert len(novel_labels) == MAX_AUTO_ADDED_PER_DOCUMENT * 2

    width = 3 + len(novel_labels)
    vectors: dict[str, list[float]] = {}
    for index, label in enumerate(["Vendor", "Invoice Number", "Total Due", *novel_labels]):
        vector = [0.0] * width
        vector[index] = 1.0
        vectors[label] = vector

    extras = [
        field(label.lower().replace(" ", "_"), label, "x", FieldType.STRING)
        for label in novel_labels
    ]
    _record_vectors(settings, vectors)
    client = FakeClient(settings)

    outcome = await assess(extras, SCHEMA, client=client, settings=settings)
    assert len(outcome.additions) == MAX_AUTO_ADDED_PER_DOCUMENT
    # With no proposal card to park them in, the overflow is refused and SAID so, rather
    # than silently widening every other document's table.
    assert len(outcome.dropped) == MAX_AUTO_ADDED_PER_DOCUMENT
    assert "left out" in outcome.summary


async def test_the_same_new_field_mentioned_twice_is_added_once(
    settings: Settings,
) -> None:
    """A field auto-added earlier in the same document must be visible to later extras, or
    a document mentioning it twice widens the schema twice."""
    _record_vectors(
        settings,
        {
            "Vendor": [1.0, 0.0, 0.0, 0.0],
            "Invoice Number": [0.0, 1.0, 0.0, 0.0],
            "Total Due": [0.0, 0.0, 1.0, 0.0],
            "Shipping Weight": [0.0, 0.0, 0.0, 1.0],
        },
    )
    client = FakeClient(settings)
    outcome = await assess(
        [
            field("shipping_weight", "Shipping Weight", "42", FieldType.NUMBER),
            field("shipping_weight", "Shipping Weight", "42", FieldType.NUMBER),
        ],
        SCHEMA,
        client=client,
        settings=settings,
    )
    assert len([f for f in outcome.additions if f.key == "shipping_weight"]) == 1


async def test_an_auto_mapped_source_key_is_recorded_as_an_alias(
    client: FakeClient, settings: Settings
) -> None:
    """The mechanism that stops the same rename being re-proposed on every document."""
    outcome = await assess(
        [field("supplier", "Supplier", "Acme", FieldType.STRING)],
        SCHEMA,
        client=client,
        settings=settings,
    )
    widened = merged_schema(SCHEMA, outcome)
    vendor = next(f for f in widened if f.key == "vendor_name")
    assert "supplier" in vendor.source_keys


async def test_the_summary_reads_as_a_sentence_for_schema_history(
    settings: Settings,
) -> None:
    """It is the only explanation the user gets for an automatic change, so it cannot read
    like a debug dump."""
    outcome = await assess(
        [field("supplier", "Supplier", "Acme", FieldType.STRING)],
        SCHEMA,
        client=FakeClient(settings),
        settings=settings,
    )
    assert outcome.summary[0].isupper()
    assert outcome.summary.endswith(".")
    assert "auto_map" not in outcome.summary


async def test_an_unusable_field_key_is_dropped_not_fatal(
    client: FakeClient, settings: Settings
) -> None:
    """Losing one speculative field is far cheaper than failing a document that extracted
    correctly otherwise."""
    outcome = await assess(
        [
            ExtractedField(key="", label="", value_text="x", value_type=FieldType.STRING),
            field("supplier", "Supplier", "Acme", FieldType.STRING),
        ],
        SCHEMA,
        client=client,
        settings=settings,
    )
    assert outcome.mappings == {"supplier": "vendor_name"}


# ---------------------------------------------------------------------------
# The embedding cache
# ---------------------------------------------------------------------------


async def test_schema_labels_are_embedded_once_not_once_per_document(
    settings: Settings,
) -> None:
    """Decision D18 budgets a label-keyed cache. Without it, a batch of eight documents
    pays for the schema's vectors eight times."""
    _record_vectors(settings, {"Vendor": [1.0, 0.0]})
    client = FakeClient(settings)
    calls: list[int] = []
    original = client.embed

    async def counting(texts, *, task="similarity"):
        calls.append(len(texts))
        return await original(texts, task=task)

    client.embed = counting  # type: ignore[method-assign]

    for _ in range(3):
        await assess(
            [field("supplier", "Supplier", "Acme", FieldType.STRING)],
            SCHEMA,
            client=client,
            settings=settings,
        )
    assert len(calls) == 1, f"embedded on every pass instead of caching: {calls}"


# ---------------------------------------------------------------------------
# The enum that stopped a batch.
# ---------------------------------------------------------------------------


async def test_a_field_the_model_called_an_enum_does_not_stop_the_batch(
    client: FakeClient, settings: Settings
) -> None:
    """Observed live on the sample corpus, and total: schema inference runs once for the
    first batch, so one field typed this way left ten documents stuck at "0 of 10 ready"
    forever, with a `ValidationError` in the log and nothing on screen.

    A model reading ten documents that all say "USD" reasonably calls the column an
    enumeration, and the extraction contract gives it no way to say what the permitted
    values are. `FieldSpec` refuses to hold an enum with no values, correctly."""
    proposal = await propose_initial(
        {
            "doc-1": [field("currency", "Currency", "USD", FieldType.ENUM)],
            "doc-2": [field("currency", "Currency", "USD", FieldType.ENUM)],
        },
        client=client,
        settings=settings,
    )

    currency = next(spec for spec in proposal.fields if spec.key == "currency")
    # A string, which accepts the eleventh document saying "EUR". An enum built from what
    # happened to turn up would reject it, and rejecting real data is the one thing this
    # product must not do.
    assert currency.type is FieldType.STRING
    assert currency.enum_values is None
