"""The project's component catalog. Requirement A2-02.

One declarative table of the four custom components and their property contracts, mirrored
by Zod on the client. Declared here rather than hand-written into each builder so that
"what can the interface render" has a single answer, and so the catalog document the
validator uses and the messages the builder emits cannot drift apart.

Only these four plus the basic catalog's layout and text components ever render. An agent
naming anything else produces a component the client refuses, which is what makes
"the agent chooses the presentation" safe rather than an injection surface (requirement
A2-05).
"""

from __future__ import annotations

from typing import Any

CATALOG_ID = "distill.app:v2"
"""Identifies our catalog in ``createSurface``. Prefixed with a name we own, per the
protocol's recommendation, so it cannot collide with anyone else's."""

BASIC_CATALOG_ID = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"

# Layout and text come from the basic catalog rather than being reinvented. Section 7.6 of
# the v1 implementation document established that the basic catalog's layout components use
# inline styles and work, while its styled components ship broken CSS in the published
# tarball; these are the ones on the working side of that line.
BASIC_COMPONENTS: tuple[str, ...] = ("Column", "Row", "Text", "Card", "Divider")

# ---------------------------------------------------------------------------
# The custom components
# ---------------------------------------------------------------------------

_DYNAMIC_STRING = {"$ref": "common_types.json#/$defs/DynamicString"}
_DYNAMIC_NUMBER = {"$ref": "common_types.json#/$defs/DynamicNumber"}
_DATA_BINDING = {"$ref": "common_types.json#/$defs/DataBinding"}

CUSTOM_COMPONENTS: dict[str, dict[str, Any]] = {
    "Metric": {
        "description": (
            "A single figure with a label and optional unit. Used when a question has one "
            "number for an answer."
        ),
        "properties": {
            "value": _DYNAMIC_NUMBER,
            "label": _DYNAMIC_STRING,
            "unit": _DYNAMIC_STRING,
            "caveat": _DYNAMIC_STRING,
        },
        "required": ["value", "label"],
    },
    "BarChart": {
        "description": "Categorical comparison. Capped at thirty bars by the builder.",
        "properties": {
            "rows": _DATA_BINDING,
            "xKey": {"type": "string"},
            "yKey": {"type": "string"},
            "unit": _DYNAMIC_STRING,
            "caveat": _DYNAMIC_STRING,
        },
        "required": ["rows", "xKey", "yKey"],
    },
    "LineChart": {
        "description": "A time series. Used only when the query bucketed a date field.",
        "properties": {
            "rows": _DATA_BINDING,
            "xKey": {"type": "string"},
            "yKey": {"type": "string"},
            "unit": _DYNAMIC_STRING,
            "caveat": _DYNAMIC_STRING,
        },
        "required": ["rows", "xKey", "yKey"],
    },
    "ResultTable": {
        "description": (
            "Rows and columns. Cells carry record identifiers so provenance works inside "
            "agent-generated interface (requirement FR-43)."
        ),
        "properties": {
            "columns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "label": {"type": "string"},
                        "type": {"type": "string"},
                    },
                    "required": ["key", "label"],
                },
            },
            "rows": _DATA_BINDING,
            "unit": _DYNAMIC_STRING,
            "caveat": _DYNAMIC_STRING,
        },
        "required": ["columns", "rows"],
    },
}

MAX_COMPONENTS_PER_SURFACE = 40
"""Requirement A2-05's component cap. Our builder emits five or six; this exists so a
future generated surface cannot become a denial of service against the browser."""

MAX_STRING_LENGTH = 400
"""Requirement A2-05's length cap on agent-provided strings. Applied by the builder to
titles and captions, which are the only text a model contributes to a surface."""


def component_names() -> tuple[str, ...]:
    return tuple(CUSTOM_COMPONENTS) + BASIC_COMPONENTS


def catalog_document() -> dict[str, Any]:
    """Our catalog as a catalog.json-shaped document.

    Used by ``validate.py`` to resolve the ``catalog.json#/$defs/anyComponent`` reference
    that the protocol's message schema makes, so emitted messages are validated against
    the components this project actually ships rather than against the basic catalog.
    """
    components: dict[str, Any] = {}
    for name, spec in CUSTOM_COMPONENTS.items():
        properties = {
            "id": {"$ref": "common_types.json#/$defs/ComponentId"},
            "component": {"const": name},
            **spec["properties"],
        }
        components[name] = {
            "type": "object",
            "description": spec["description"],
            "properties": properties,
            "required": ["id", "component", *spec["required"]],
            "additionalProperties": False,
        }

    # The basic components we use, declared loosely: their real schemas live in the vendored
    # basic catalog, and duplicating them here would create exactly the drift this module
    # exists to prevent. The union below accepts either.
    for name in BASIC_COMPONENTS:
        components[name] = {
            "type": "object",
            "properties": {
                "id": {"$ref": "common_types.json#/$defs/ComponentId"},
                "component": {"const": name},
            },
            "required": ["id", "component"],
        }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://a2ui.org/specification/v0_9/catalog.json",
        "title": "Distill catalog",
        "catalogId": CATALOG_ID,
        "components": components,
        "functions": {},
        "$defs": {
            "anyComponent": {
                "oneOf": [{"$ref": f"#/components/{name}"} for name in components]
            },
            "theme": {"type": "object"},
        },
    }
