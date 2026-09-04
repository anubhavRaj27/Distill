"""Initial unification and drift. Decisions D23, D24, and D25.

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
# Initial unification, decision D25
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
    assert proposal.questions == []


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
    assert proposal.questions == []


async def test_a_semantic_rename_unifies_when_vectors_are_recorded(
    settings: Settings,
) -> None:
    """Decision D25's demo path: ``Supplier`` and ``Vendor`` merging automatically.

    This is also the test that proves recorded vectors are what make the offline path
    behave like the online one (decision D13).
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


async def test_an_uncertain_pair_stays_split_and_asks(
    client: FakeClient, settings: Settings
) -> None:
    """Decision D25's core rule. A wrong merge commingles two fields' values and unpicking
    it needs per-value provenance; a wrong split is a lossless move. Prefer the cheaper
    undo."""
    proposal = await propose_initial(
        {
            "a.pdf": [field("invoice_number", "Invoice Number", "INV-1", FieldType.STRING)],
            "b.pdf": [field("invoice_no", "Invoice No", "INV-2", FieldType.STRING)],
        },
        client=client,
        settings=settings,
    )
    assert len(proposal.fields) == 2, "uncertain unification must NOT merge"
    assert len(proposal.questions) == 1
    question = proposal.questions[0]
    assert {question.left_key, question.right_key} == {"invoice_number", "invoice_no"}


async def test_unrelated_fields_do_not_generate_merge_questions(
    client: FakeClient, settings: Settings
) -> None:
    """The regression test for a real defect: treating 'nothing resembles this, and we had
    no vector to confirm it' as a judgment call produced a merge question for nearly every
    field in the batch, pairing unrelated things like ``vendor`` with ``invoice_no``."""
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
    asked = [(question.left_key, question.right_key) for question in proposal.questions]
    assert proposal.questions == [], f"unrelated fields must not ask; got {asked}"


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
# Drift, decisions D23 and D24
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
    assert outcome.questions == []


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
    assert outcome.questions == []

    widened = merged_schema(SCHEMA, outcome)
    assert "shipping_weight" in {f.key for f in widened}
    assert len(widened) == len(SCHEMA) + 1


async def test_an_unconfirmable_field_asks_rather_than_adding_a_duplicate_column(
    client: FakeClient, settings: Settings
) -> None:
    """With no vector we cannot rule out a semantic rename, and a wrong auto-add creates a
    duplicate column holding half the values. Asking is the safe direction."""
    outcome = await assess(
        [field("shipping_weight", "Shipping Weight", "42", FieldType.NUMBER)],
        SCHEMA,
        client=client,
        settings=settings,
    )
    assert outcome.additions == []
    assert [q.incoming_key for q in outcome.questions] == ["shipping_weight"]


async def test_a_question_carries_ranked_candidates_for_the_card(
    client: FakeClient, settings: Settings
) -> None:
    """The proposal card offers 'map to existing', so it needs the options and their
    scores, not just the fact that a decision is needed."""
    outcome = await assess(
        [field("shipping_weight", "Shipping Weight", "42", FieldType.NUMBER)],
        SCHEMA,
        client=client,
        settings=settings,
    )
    question = outcome.questions[0]
    assert question.candidates
    assert len(question.candidates[0]) == 3
    scores = [score for _key, _label, score in question.candidates]
    assert scores == sorted(scores, reverse=True), "best candidate first"
    assert question.sample_value == "42", "the card shows the user the value in question"


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
    assert len(outcome.questions) == MAX_AUTO_ADDED_PER_DOCUMENT
    assert "more than" in outcome.questions[0].reason


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
    """Decision D24 budgets a label-keyed cache. Without it, a batch of eight documents
    pays for the schema's vectors eight times."""
    _record_vectors(settings, {"Vendor": [1.0, 0.0]})
    client = FakeClient(settings)
    calls: list[int] = []
    original = client.embed

    async def counting(texts):
        calls.append(len(texts))
        return await original(texts)

    client.embed = counting  # type: ignore[method-assign]

    for _ in range(3):
        await assess(
            [field("supplier", "Supplier", "Acme", FieldType.STRING)],
            SCHEMA,
            client=client,
            settings=settings,
        )
    assert len(calls) == 1, f"embedded on every pass instead of caching: {calls}"
