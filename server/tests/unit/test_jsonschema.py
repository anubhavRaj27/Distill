"""The provider schema subset. This test IS the mitigation for review finding 8.7.

The finding was that a response schema which validates locally can still be rejected by
Gemini, and that the risk could not be verified without an API key. Converting to the subset
ourselves turns that into something checkable offline: if a response model ever grows a
construct providers do not accept, this file fails rather than the demo.
"""

from __future__ import annotations

import json

import pytest
from app.llm.contracts import ExtractedField, GuidedExtraction, OpenExtraction
from app.llm.jsonschema import (
    MAX_DEPTH,
    UnsupportedSchema,
    to_provider_schema,
    unsupported_keywords,
)
from pydantic import BaseModel, Field, create_model

RESPONSE_MODELS = [OpenExtraction, GuidedExtraction, ExtractedField]


@pytest.mark.parametrize("model", RESPONSE_MODELS, ids=lambda m: m.__name__)
def test_every_response_model_converts_into_the_provider_subset(
    model: type[BaseModel],
) -> None:
    converted = to_provider_schema(model.model_json_schema())
    text = json.dumps(converted)
    assert "$defs" not in text, "definitions must be inlined"
    assert "$ref" not in text, "references must be resolved"
    assert "anyOf" not in text, "nullable unions must be collapsed"
    assert "oneOf" not in text
    assert unsupported_keywords(converted) == set()


@pytest.mark.parametrize("model", RESPONSE_MODELS, ids=lambda m: m.__name__)
def test_converted_schemas_stay_within_the_depth_limit(model: type[BaseModel]) -> None:
    """Deep nesting is where provider support becomes unreliable."""
    converted = to_provider_schema(model.model_json_schema())

    def depth(node: object) -> int:
        if isinstance(node, dict):
            return 1 + max((depth(value) for value in node.values()), default=0)
        if isinstance(node, list):
            return 1 + max((depth(entry) for entry in node), default=0)
        return 0

    assert depth(converted) <= MAX_DEPTH * 3


def test_nullable_fields_become_nullable_rather_than_a_union() -> None:
    converted = to_provider_schema(ExtractedField.model_json_schema())
    value_text = converted["properties"]["value_text"]
    assert value_text["type"] == "string"
    assert value_text["nullable"] is True


def test_enums_survive_conversion() -> None:
    """`value_type` is an enum, and the model needs to see the permitted values."""
    converted = to_provider_schema(ExtractedField.model_json_schema())
    value_type = converted["properties"]["value_type"]
    assert value_type["type"] == "string"
    assert "currency" in value_type["enum"]
    assert "string_list" in value_type["enum"]


def test_property_order_is_preserved_and_declared() -> None:
    """Order is not decorative: providers generate fields in the order given.

    Evidence before value is deliberate. A model that commits to a value and then invents
    a quote to justify it grounds worse than one that finds the quote first.
    """
    converted = to_provider_schema(ExtractedField.model_json_schema())
    order = converted["propertyOrdering"]
    assert order == list(converted["properties"])
    assert order.index("evidence_quote") < order.index("confidence")


def test_a_union_of_two_real_types_is_rejected_loudly() -> None:
    """The design constraint that keeps everything else inside the subset.

    ``app.llm.contracts`` sends every value as text precisely so this never happens. If a
    future response model reaches for a real union, it fails here with an explanation
    rather than at request time with a provider error.
    """

    class Bad(BaseModel):
        value: int | str = Field(default=0)

    with pytest.raises(UnsupportedSchema) as raised:
        to_provider_schema(Bad.model_json_schema())
    assert "app.domain.values" in str(raised.value), (
        "the error must point at the supported alternative"
    )


def test_a_schema_nested_past_the_limit_is_rejected() -> None:
    """Built from MAX_DEPTH rather than hard-coded, so tuning the limit cannot silently
    turn this test into one that passes for the wrong reason."""
    current: type[BaseModel] = create_model("Leaf", value=(str, ""))
    for level in range(MAX_DEPTH + 2):
        current = create_model(f"Level{level}", child=(current, ...))

    with pytest.raises(UnsupportedSchema) as raised:
        to_provider_schema(current.model_json_schema())
    assert "nests deeper" in str(raised.value)


def test_a_schema_at_the_depth_limit_is_accepted() -> None:
    """The boundary in the other direction, so the limit is a limit and not a trap."""
    current: type[BaseModel] = create_model("Leaf", value=(str, ""))
    for level in range(MAX_DEPTH - 3):
        current = create_model(f"Ok{level}", child=(current, ...))
    to_provider_schema(current.model_json_schema())


def test_a_dangling_reference_is_reported_rather_than_ignored() -> None:
    with pytest.raises(UnsupportedSchema):
        to_provider_schema({"type": "object", "properties": {"a": {"$ref": "#/$defs/Gone"}}})


def test_a_reference_site_description_survives_inlining() -> None:
    """pydantic puts a documented nested field's description at the reference, not the
    definition, so inlining must not drop it."""
    schema = {
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/Thing", "description": "at the ref site"}},
        "$defs": {"Thing": {"type": "object", "properties": {"b": {"type": "string"}}}},
    }
    converted = to_provider_schema(schema)
    assert converted["properties"]["a"]["description"] == "at the ref site"
