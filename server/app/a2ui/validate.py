"""Validating emitted messages against the real v0.9 JSON Schema. Requirement A2-03.

The schemas under ``schema/`` are vendored verbatim from ``@a2ui/web_core@0.10.7``, so this
checks our output against the actual specification rather than against our reading of it.
That distinction earns its keep: the protocol requires a ``version`` discriminator and
exactly one message key per object, and both are easy to get subtly wrong from prose.

The protocol's message schema refers to ``catalog.json#/$defs/anyComponent``, which is
resolved to **our** catalog (``app.a2ui.catalog``). So a message naming a component this
project does not ship fails validation here, in a test, rather than rendering as nothing in
a browser.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from app.a2ui.catalog import catalog_document
from app.logging import get_logger

logger = get_logger(__name__)

SCHEMA_DIR = Path(__file__).parent / "schema"
BASE = "https://a2ui.org/specification/v0_9/"


class InvalidSurface(ValueError):
    """An emitted message array does not satisfy the protocol schema."""


def _load(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    return loaded


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    """A validator for one server-to-client message, with our catalog resolved in."""
    message_schema = _load("server_to_client.json")
    registry: Registry[Any] = Registry().with_resources(
        [
            (BASE + "common_types.json", Resource.from_contents(_load("common_types.json"))),
            # The protocol asks for "the catalog"; ours is the one we ship.
            (BASE + "catalog.json", Resource.from_contents(catalog_document())),
            (BASE + "server_to_client.json", Resource.from_contents(message_schema)),
        ]
    )
    return Draft202012Validator(message_schema, registry=registry)


def validate_message(message: dict[str, Any]) -> None:
    """Raise ``InvalidSurface`` if ``message`` is not a legal v0.9 message."""
    errors = sorted(_validator().iter_errors(message), key=lambda error: error.path)
    if errors:
        first = errors[0]
        raise InvalidSurface(
            f"{'/'.join(str(part) for part in first.path) or '(root)'}: {first.message}"
        )


def validate_surface(messages: list[dict[str, Any]]) -> None:
    """Validate a whole surface: every message, plus the ordering rules the spec states.

    The per-message schema cannot express these, so they are checked here:

    * ``createSurface`` comes first, because the spec says components and data for a
      surface follow its creation
    * every message names the same surface
    * exactly one component carries ``id: "root"``, which is what the renderer mounts
    """
    if not messages:
        raise InvalidSurface("a surface needs at least one message")

    for message in messages:
        validate_message(message)

    first = messages[0]
    if "createSurface" not in first:
        raise InvalidSurface("the first message must be createSurface")

    surface_ids = {
        body["surfaceId"]
        for message in messages
        for key, body in message.items()
        if key != "version" and isinstance(body, dict) and "surfaceId" in body
    }
    if len(surface_ids) != 1:
        raise InvalidSurface(f"messages span several surfaces: {sorted(surface_ids)}")

    roots = [
        component
        for message in messages
        if "updateComponents" in message
        for component in message["updateComponents"]["components"]
        if component.get("id") == "root"
    ]
    if len(roots) != 1:
        raise InvalidSurface(f"a surface needs exactly one root component, found {len(roots)}")


def is_valid(messages: list[dict[str, Any]]) -> bool:
    """Whether a surface validates. Logged rather than raised, for a runtime guard."""
    try:
        validate_surface(messages)
    except InvalidSurface as exc:
        logger.warning("a2ui.invalid_surface", detail=str(exc))
        return False
    return True
