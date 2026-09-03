"""The response shapes a model is asked to produce.

DELIBERATE DEVIATION FROM implementation.md SECTION 6.2 (decision D19)
-----------------------------------------------------------------------
The implementation document proposed building the schema-guided response model at runtime
with ``pydantic.create_model``, one typed attribute per schema field. Sift instead uses a
**flat, fixed response shape** for every extraction call: a list of ``ExtractedField``, with
the schema communicated in the PROMPT rather than in the response schema.

Three reasons, in order of weight.

1. **It removes review finding 8.7.** Gemini's structured-output support accepts a narrower
   subset of JSON Schema than pydantic can emit, and a dynamically generated model is
   exactly the thing most likely to wander outside it: nested objects, references, and
   unions all appear naturally. A fixed flat shape is verifiable once and then stops being
   a risk. This matters more than usual here, because the risk could not be tested without
   an API key.
2. **Provenance is per value, and nesting it is where the generated approach gets ugly.**
   Every value needs its own evidence quote, page number, confidence, and reasoning. With
   one attribute per field, each of those attributes has to become an object carrying five
   more, which is precisely the deep nesting reason 1 warns about. As a list, each entry
   carries its own provenance flatly.
3. **One response shape means one fixture shape**, so the fake provider and the recorded
   fixtures stay simple and stable.

``value_text`` IS ALWAYS A STRING, NEVER A UNION
------------------------------------------------
A field's value could be text, a number, a date, a boolean, or a list, and expressing that
as a union is both the least portable thing to put in a response schema and unnecessary. The
model is asked for the value **as the document writes it**, as text, plus its guess at the
type. Conversion into the stored representation is then done by ``app.domain.values``, which
is already written, already tested against real invoice formatting, and reports how much
interpretation each conversion required, which is what feeds confidence tier derivation.

So the model does what models are good at (find the value, say what kind of thing it is) and
deterministic code does what deterministic code is good at (parse "$12,480.50" into an
amount and a currency, and admit when a date was ambiguous).

What is given up: the guided call cannot rely on the response schema to force a value for
every field. That is handled by asking for it in the prompt and checking coverage
afterwards, which is a check worth having regardless, because a model can return a
structurally valid object full of nulls.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.fields import FieldType

MAX_QUOTE_LENGTH = 300
MAX_REASONING_LENGTH = 400
MAX_FIELDS_PER_DOCUMENT = 80
"""Caps on model output. Not paranoia: an unbounded list from a model is an unbounded
database write and an unbounded page of interface, and a document with eighty distinct
fields is a document this product has misunderstood."""


class ExtractedField(BaseModel):
    """One value a model found in a document, with its evidence."""

    key: str = Field(
        description="Machine name for the field, lowercase with underscores, such as "
        "vendor_name or invoice_total."
    )
    label: str = Field(
        default="",
        description="The field's name AS THE DOCUMENT WRITES IT, such as 'Supplier' or "
        "'Bill To'. Kept because it is the evidence for a later rename decision: knowing "
        "that this document said 'Supplier' is what lets drift detection recognise it as "
        "the same thing as another document's 'Vendor'.",
    )
    value_text: str | None = Field(
        default=None,
        description="The value exactly as written in the document, as text. Null means the "
        "field is genuinely absent from this document. Never a guess.",
    )
    value_type: FieldType = Field(
        default=FieldType.STRING, description="What kind of value this is."
    )
    evidence_quote: str | None = Field(
        default=None,
        max_length=MAX_QUOTE_LENGTH,
        description="A VERBATIM span from the document containing this value. This is the "
        "contract that makes provenance possible: a value whose quote cannot be located in "
        "the document has its confidence tier capped at low, which is how hallucinations "
        "are caught (decision D5).",
    )
    page_index: int = Field(
        default=0, ge=0, description="Zero-based page the value was found on."
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="How sure the model is. One input to the tier, never the tier itself.",
    )
    reasoning: str = Field(
        default="",
        max_length=MAX_REASONING_LENGTH,
        description="One short sentence on why this value was chosen. Shown to the user in "
        "the viewer beside the highlight (requirement FR-31).",
    )


class OpenExtraction(BaseModel):
    """Result of open extraction: every salient field, with no schema to follow.

    Used for the first batch of documents in a workspace, before any schema exists. Its
    output is what the initial schema proposal is inferred from.
    """

    document_kind: str = Field(
        default="",
        description="What sort of document this appears to be, such as 'invoice' or "
        "'bank statement'. Not used for extraction, but it is a strong signal for schema "
        "proposal: a bank statement having no vendor field is expected rather than a gap.",
    )
    fields: list[ExtractedField] = Field(
        default_factory=list, max_length=MAX_FIELDS_PER_DOCUMENT
    )


class GuidedExtraction(BaseModel):
    """Result of schema-guided extraction: fill the schema, and flag what did not fit."""

    values: list[ExtractedField] = Field(
        default_factory=list,
        max_length=MAX_FIELDS_PER_DOCUMENT,
        description="One entry per field in the current schema, in schema order. A field "
        "the document does not contain is still listed, with a null value_text.",
    )
    extra_fields: list[ExtractedField] = Field(
        default_factory=list,
        max_length=MAX_FIELDS_PER_DOCUMENT,
        description="Salient values that do not correspond to any current schema field. "
        "This list is what feeds schema drift detection (requirement FR-13): it is the "
        "system noticing that a document has something to say that the schema cannot "
        "record, which is the alternative to silently dropping it.",
    )
