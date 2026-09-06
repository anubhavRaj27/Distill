"""Turning an evaluated result into A2UI messages. Requirement A2-03, decision D37.

The shape of every surface is the same three messages:

* ``createSurface``   names the surface and our catalog
* ``updateDataModel`` writes the **server-computed** result at ``/result``
* ``updateComponents`` emits components whose properties are *path bindings* into it

That middle message is the entire point. The model chose ``BarChart`` and said the series
lives at ``/result/rows``; the server put real rows there. No number in a rendered surface
ever passed through the model, which is what makes "the agent chooses the presentation" safe
to allow.

THE AGENT'S CHOICE OF KIND IS A PROPOSAL, NOT AN INSTRUCTION
-------------------------------------------------------------
``resolve_kind`` overrides the requested kind when the evaluated data contradicts it. This
is not second-guessing for its own sake: the model chooses before the query has been
evaluated, so it is guessing at the shape of data it has not seen. A bar chart of one bar
and a line chart with nothing to order by are worse than the shapes they should have been,
and the server is the first thing in the pipeline that actually knows.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.a2ui.catalog import (
    CATALOG_ID,
    MAX_COMPONENTS_PER_SURFACE,
    MAX_STRING_LENGTH,
)
from app.domain.chat import VisualKind
from app.insights.evaluate import QueryResult
from app.insights.queryspec import Visual
from app.logging import get_logger

logger = get_logger(__name__)

VERSION = "v0.9"
RESULT_PATH = "/result"
MAX_BARS = 30
"""Past thirty bars a chart is a smear. The result becomes a table instead, which is what
the reader wanted from a long list anyway."""


def _text(value: str | None) -> str:
    """Cap and flatten a model-provided string. Requirement A2-05.

    Newlines are stripped as well as length capped: a title with newlines in it can break
    out of the layout the client intended, and there is no legitimate reason for one.
    """
    if not value:
        return ""
    return " ".join(str(value).split())[:MAX_STRING_LENGTH]


def new_surface_id(prefix: str = "surface") -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def resolve_kind(requested: VisualKind, result: QueryResult) -> VisualKind:
    """The kind actually rendered, given what the data turned out to look like."""
    row_count = len(result.rows)

    if row_count <= 1:
        # One row is a single figure. Charting it draws one bar against no comparison.
        if requested is not VisualKind.TABLE:
            return VisualKind.METRIC
        return requested

    if requested is VisualKind.METRIC and row_count > 1:
        # The model expected one number and got a distribution. A bar chart is the honest
        # rendering; showing rows[0] as "the" metric would hide the other rows entirely.
        return VisualKind.BAR

    if requested in (VisualKind.BAR, VisualKind.LINE) and row_count > MAX_BARS:
        return VisualKind.TABLE

    return requested


def _caveat(result: QueryResult) -> str:
    """A one-line warning rendered with the visual, or empty.

    Mixed currencies are the case that matters: the total is arithmetically real and
    semantically meaningless, so it is shown WITH the caveat rather than hidden or silently
    summed. In a finance product a quietly wrong total is the worst available outcome.
    """
    if result.mixed_currency:
        codes = ", ".join(result.currencies)
        return (
            f"Values span more than one currency ({codes}), so the total is not "
            f"directly comparable."
        )
    return ""


def build_surface(
    visual: Visual,
    result: QueryResult,
    *,
    surface_id: str | None = None,
    include_title: bool = True,
) -> tuple[list[dict[str, Any]], VisualKind]:
    """Build the message array for one visual. Returns the messages and the kind used.

    ``include_title`` exists for the dashboard. A chat visual arrives in a stream of prose
    and has to name itself, so it carries its own heading. A dashboard panel is already a
    titled card, and the panel's title IS ``visual.title`` — the same string — so drawing it
    inside the surface as well printed every panel's name twice, one line under the other.
    The title stays in the data model either way; only the component that renders it goes.
    """
    surface = surface_id or new_surface_id()
    kind = resolve_kind(visual.kind, result)
    if kind is not visual.kind:
        logger.info(
            "a2ui.kind_overridden",
            requested=visual.kind.value,
            used=kind.value,
            rows=len(result.rows),
        )

    data = result.to_data_model()
    data["title"] = _text(visual.title)
    unit = visual.unit_hint or result.unit
    data["unit"] = unit

    messages: list[dict[str, Any]] = [
        {
            "version": VERSION,
            "createSurface": {"surfaceId": surface, "catalogId": CATALOG_ID},
        },
        {
            "version": VERSION,
            "updateDataModel": {
                "surfaceId": surface,
                "path": RESULT_PATH,
                "value": data,
            },
        },
    ]

    children = ["title", "visual"] if include_title else ["visual"]
    components: list[dict[str, Any]] = [
        {"id": "root", "component": "Column", "children": list(children)},
        _visual_component(kind, result, unit),
    ]
    if include_title:
        components.insert(
            1,
            {
                "id": "title",
                "component": "Text",
                "text": {"path": f"{RESULT_PATH}/title"},
                "variant": "h3",
            },
        )

    caveat = _caveat(result)
    if caveat:
        components[0]["children"] = [*children, "caveat"]
        components.append(
            {
                "id": "caveat",
                "component": "Text",
                "text": _text(caveat),
                "variant": "caption",
            }
        )

    if len(components) > MAX_COMPONENTS_PER_SURFACE:  # pragma: no cover - we emit four
        raise ValueError("surface exceeds the component cap")

    messages.append(
        {
            "version": VERSION,
            "updateComponents": {"surfaceId": surface, "components": components},
        }
    )
    return messages, kind


def _visual_component(
    kind: VisualKind, result: QueryResult, unit: str | None
) -> dict[str, Any]:
    """The one component that renders the data, bound by path."""
    match kind:
        case VisualKind.METRIC:
            return {
                "id": "visual",
                "component": "Metric",
                # Bound, not inlined. The number is in the data model the server wrote.
                "value": {"path": f"{RESULT_PATH}/rows/0/value"},
                "label": {"path": f"{RESULT_PATH}/rows/0/label"},
                **({"unit": unit} if unit else {}),
            }
        case VisualKind.BAR:
            return {
                "id": "visual",
                "component": "BarChart",
                "rows": {"path": f"{RESULT_PATH}/rows"},
                "xKey": "label",
                "yKey": "value",
                **({"unit": unit} if unit else {}),
            }
        case VisualKind.LINE:
            return {
                "id": "visual",
                "component": "LineChart",
                "rows": {"path": f"{RESULT_PATH}/rows"},
                "xKey": "label",
                "yKey": "value",
                **({"unit": unit} if unit else {}),
            }
        case VisualKind.TABLE:
            return {
                "id": "visual",
                "component": "ResultTable",
                "columns": [
                    {"key": column.key, "label": column.label, "type": column.type}
                    for column in result.columns
                ],
                "rows": {"path": f"{RESULT_PATH}/rows"},
                **({"unit": unit} if unit else {}),
            }


def result_paths(
    result: QueryResult, unit: str | None = None
) -> dict[str, tuple[Any, str | None]]:
    """Every path a prose placeholder may refer to, with the unit that applies to it.

    Decision D46. Built here rather than in the stream processor because this module owns
    the shape of the data model, so it is the only place that can enumerate the paths
    without guessing.

    THE UNIT IS PER PATH, NOT PER RESULT, and that is a correctness matter rather than
    tidiness. A single result carries a monetary total AND a record count, and applying one
    unit to the whole thing produced prose reading "across 5 USD documents". Only the
    measure values are denominated in the unit; counts and labels are not.
    """
    measure_unit = unit or result.unit
    is_money = result.value_type == "currency"
    value_unit = measure_unit if is_money else None

    paths: dict[str, tuple[Any, str | None]] = {
        "result.total": (result.total, value_unit),
        # A count is a count in every currency.
        "result.record_count": (float(result.record_count), None),
        "result.unit": (measure_unit, None),
    }
    for index, row in enumerate(result.rows):
        paths[f"result.rows.{index}.value"] = (row.value, value_unit)
        paths[f"result.rows.{index}.label"] = (row.label, None)
    return paths
