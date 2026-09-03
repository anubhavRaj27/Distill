"""Converting a pydantic JSON Schema into the subset providers actually accept.

WHY THIS MODULE EXISTS
----------------------
Review finding 8.7 flagged that a response schema which validates locally can still be
rejected by a provider, because Gemini's structured output accepts a narrow subset of JSON
Schema (roughly OpenAPI 3.0's schema object) rather than the full specification. Two
constructs pydantic emits routinely are outside it:

* ``$defs`` with ``$ref`` pointers, which pydantic uses for any nested model
* ``anyOf: [{type: X}, {type: "null"}]``, which is how pydantic expresses ``X | None``

The finding also noted that the risk could not be verified without an API key, which made
it the worst kind of risk: real, unfixable-by-testing, and discovered at demo time.

This module closes it. References are inlined, nullable unions are collapsed to a single
type with ``nullable: true``, and unsupported keywords are dropped. The result is asserted
against the documented subset in ``tests/unit/test_jsonschema.py``, which needs no key. The
risk becomes a passing test rather than a hope about someone else's converter.

A union between two NON-null types cannot be represented in this subset and raises, rather
than being silently mangled into something that would fail at request time. That is why
``app.llm.contracts`` sends every value as text: it is the design choice that keeps the
response shape inside this subset by construction.
"""

from __future__ import annotations

from typing import Any

SUPPORTED_KEYWORDS: frozenset[str] = frozenset(
    {
        "type",
        "format",
        "description",
        "nullable",
        "enum",
        "items",
        "properties",
        "required",
        "propertyOrdering",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "title",
    }
)
"""Keywords the provider subset understands. Everything else is dropped, because sending an
unrecognised keyword is at best ignored and at worst a rejected request."""

SUPPORTED_TYPES: frozenset[str] = frozenset(
    {"string", "number", "integer", "boolean", "array", "object"}
)

MAX_DEPTH = 6
"""Nesting limit. Deep schemas are where provider support gets unreliable, so exceeding it
is a design error to catch in a test rather than a runtime surprise."""


class UnsupportedSchema(ValueError):
    """A schema cannot be expressed in the provider subset."""


def _resolve_ref(ref: str, definitions: dict[str, Any]) -> dict[str, Any]:
    if not ref.startswith("#/$defs/"):
        raise UnsupportedSchema(f"cannot resolve reference {ref!r}")
    name = ref.removeprefix("#/$defs/")
    if name not in definitions:
        raise UnsupportedSchema(f"reference {ref!r} points at a missing definition")
    return definitions[name]


def _collapse_nullable(node: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Turn ``anyOf: [X, null]`` into ``(X, nullable=True)``.

    Also handles the single-member and all-null degenerate cases pydantic can produce.
    A union of two real types is rejected: see the module docstring.
    """
    options = node.get("anyOf") or node.get("oneOf")
    if not options:
        return node, False

    non_null = [option for option in options if option.get("type") != "null"]
    nullable = len(non_null) < len(options)

    if not non_null:
        raise UnsupportedSchema("a schema whose only permitted type is null is meaningless")
    if len(non_null) > 1:
        raise UnsupportedSchema(
            "a union between two non-null types cannot be expressed in the provider "
            f"schema subset: {[option.get('type') for option in non_null]}. Send the value "
            "as text and convert it with app.domain.values instead."
        )

    merged = dict(non_null[0])
    # Keywords that lived on the union wrapper rather than on its member, such as the
    # description and the default, belong on the collapsed node.
    for keyword in ("description", "title"):
        if keyword in node and keyword not in merged:
            merged[keyword] = node[keyword]
    return merged, nullable


def _convert(node: Any, definitions: dict[str, Any], depth: int) -> Any:
    if depth > MAX_DEPTH:
        raise UnsupportedSchema(
            f"schema nests deeper than {MAX_DEPTH} levels, which providers handle "
            f"unreliably. Flatten the response model."
        )
    if not isinstance(node, dict):
        return node

    if "$ref" in node:
        resolved = _resolve_ref(node["$ref"], definitions)
        # Keep a description written at the reference site, which pydantic puts there for
        # a documented nested field.
        merged = {**resolved}
        if "description" in node:
            merged["description"] = node["description"]
        return _convert(merged, definitions, depth)

    node, nullable = _collapse_nullable(node)

    result: dict[str, Any] = {}

    node_type = node.get("type")
    if isinstance(node_type, list):
        # ``type: [X, "null"]`` is the other spelling of a nullable union.
        real = [entry for entry in node_type if entry != "null"]
        if len(real) != 1:
            raise UnsupportedSchema(f"cannot express type list {node_type!r}")
        nullable = nullable or len(real) < len(node_type)
        node_type = real[0]

    if node_type is not None:
        if node_type not in SUPPORTED_TYPES:
            raise UnsupportedSchema(f"type {node_type!r} is not in the provider subset")
        result["type"] = node_type
    elif "enum" in node:
        result["type"] = "string"

    for keyword in ("description", "enum", "format", "minItems", "maxItems"):
        if keyword in node:
            result[keyword] = node[keyword]

    if nullable:
        result["nullable"] = True

    if "items" in node:
        result["items"] = _convert(node["items"], definitions, depth + 1)

    if "properties" in node:
        properties: dict[str, Any] = {}
        for name, value in node["properties"].items():
            properties[name] = _convert(value, definitions, depth + 1)
        result["properties"] = properties
        # Property order is not decorative. Providers generate fields in the order given,
        # and an extraction that emits its evidence quote before its value tends to be
        # better grounded than one that commits to a value first.
        result["propertyOrdering"] = list(properties)
        required = [name for name in node.get("required", []) if name in properties]
        if required:
            result["required"] = required

    return result


def to_provider_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a pydantic JSON Schema into the provider subset.

    Raises ``UnsupportedSchema`` rather than emitting something a provider would reject.
    """
    definitions = schema.get("$defs", {})
    converted = _convert({k: v for k, v in schema.items() if k != "$defs"}, definitions, 0)
    if not isinstance(converted, dict):  # pragma: no cover - a top-level schema is an object
        raise UnsupportedSchema("the top level of a response schema must be an object")
    return converted


def unsupported_keywords(schema: dict[str, Any]) -> set[str]:
    """Every keyword in ``schema`` that is outside the supported set. For tests."""
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key not in SUPPORTED_KEYWORDS:
                    found.add(key)
                if key in ("properties",) and isinstance(value, dict):
                    for child in value.values():
                        walk(child)
                else:
                    walk(value)
        elif isinstance(node, list):
            for entry in node:
                walk(entry)

    walk(schema)
    return found
