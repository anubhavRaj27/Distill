"""Query specifications, their evaluation, and the A2UI surfaces built from them.

This is decision D37's test file: the rule that every displayed number is computed by the
server and bound by path, never typed by the model. The tests that matter most are the ones
asserting what the model **cannot** do, and the one asserting that a total spanning two
currencies is reported with a caveat rather than silently summed.
"""

from __future__ import annotations

import json

import pytest
from app.a2ui.build import MAX_BARS, build_surface, resolve_kind, result_paths
from app.a2ui.catalog import CATALOG_ID, MAX_STRING_LENGTH, component_names
from app.a2ui.validate import InvalidSurface, validate_surface
from app.domain.chat import VisualKind
from app.domain.fields import FieldType
from app.insights.evaluate import (
    MISSING_LABEL,
    QueryResult,
    ResultColumn,
    ResultRow,
    _matches,
    label_of,
    numeric_of,
)
from app.insights.queryspec import DataQuery, Filter, Visual
from pydantic import ValidationError

COLUMNS = [
    ResultColumn("label", "Vendor", "string"),
    ResultColumn("value", "Total Due", "currency"),
]


def visual(kind: VisualKind, **query_kwargs: object) -> Visual:
    """Build a Visual without the model-facing validators, for shape tests."""
    return Visual.model_construct(
        kind=kind,
        title="Total by vendor",
        query=DataQuery(**query_kwargs),  # type: ignore[arg-type]
        unit_hint=None,
    )


def result(rows: list[ResultRow], **kwargs: object) -> QueryResult:
    return QueryResult(columns=COLUMNS, rows=rows, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# What the model is not allowed to ask for
# ---------------------------------------------------------------------------


def test_an_aggregate_other_than_count_needs_a_measure() -> None:
    with pytest.raises(ValidationError) as raised:
        DataQuery(aggregate="sum")
    assert "measure_field" in str(raised.value)


def test_bucketing_needs_something_to_bucket() -> None:
    with pytest.raises(ValidationError):
        DataQuery(bucket="month")


def test_a_metric_cannot_be_built_over_a_grouped_query() -> None:
    """A metric shows one figure. Over a grouped query it would show one group and hide
    the rest, which is a wrong answer rather than a cramped one."""
    with pytest.raises(ValidationError):
        Visual(kind=VisualKind.METRIC, title="x", query=DataQuery(group_by="vendor_name"))


def test_a_line_chart_needs_an_ordered_axis() -> None:
    with pytest.raises(ValidationError):
        Visual(kind=VisualKind.LINE, title="x", query=DataQuery(group_by="issue_date"))


def test_a_filter_needs_a_value_unless_it_tests_presence() -> None:
    with pytest.raises(ValidationError):
        Filter(field="total_due", op="gt")
    Filter(field="total_due", op="missing")
    Filter(field="total_due", op="present")


def test_the_row_limit_is_capped() -> None:
    with pytest.raises(ValidationError):
        DataQuery(limit=5000)


# ---------------------------------------------------------------------------
# Reading stored values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "field_type", "expected"),
    [
        ({"amount": 12480.5, "currency": "USD"}, FieldType.CURRENCY, 12480.5),
        (42.0, FieldType.NUMBER, 42.0),
        (True, FieldType.BOOLEAN, 1.0),
        (False, FieldType.BOOLEAN, 0.0),
        ("Acme", FieldType.STRING, None),
        (None, FieldType.CURRENCY, None),
        ("2026-03-14", FieldType.DATE, None),
    ],
)
def test_numeric_extraction(value: object, field_type: FieldType, expected: float | None) -> None:
    assert numeric_of(value, field_type) == expected


def test_a_missing_group_value_is_labelled_not_dropped() -> None:
    """'Eleven invoices have no purchase order number' is usually the interesting answer,
    so the absent group is named rather than hidden."""
    assert label_of(None, FieldType.STRING) == MISSING_LABEL


@pytest.mark.parametrize(
    ("iso", "bucket", "expected"),
    [
        ("2026-03-14", "month", "2026-03"),
        ("2026-03-14", "quarter", "2026-Q1"),
        ("2026-11-02", "quarter", "2026-Q4"),
        ("2026-03-14", "year", "2026"),
        ("2026-03-14", "none", "2026-03-14"),
    ],
)
def test_date_bucket_labels_sort_chronologically_as_strings(
    iso: str, bucket: str, expected: str
) -> None:
    """Deliberate: a plain lexicographic sort puts a time series in date order, so the
    line chart needs no separate ordering key."""
    assert label_of(iso, FieldType.DATE, bucket) == expected


assert "2026-02" < "2026-03" < "2026-11", "the ordering property this relies on"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op", "filter_value", "stored", "matches"),
    [
        ("gt", 1000, {"amount": 12480.5, "currency": "USD"}, True),
        ("gt", 20000, {"amount": 12480.5, "currency": "USD"}, False),
        ("lte", 12480.5, {"amount": 12480.5, "currency": "USD"}, True),
        ("eq", "Acme Ltd", "acme ltd", True),
        ("contains", "acme", "Acme Industrial", True),
        ("ne", "Acme", "Globex", True),
    ],
)
def test_filters_compare_by_type(
    op: str, filter_value: object, stored: object, matches: bool
) -> None:
    field_type = FieldType.CURRENCY if isinstance(stored, dict) else FieldType.STRING
    condition = Filter(field="f", op=op, value=filter_value)  # type: ignore[arg-type]
    assert _matches(condition, stored, field_type) is matches


def test_missing_and_present_do_not_need_a_value() -> None:
    assert _matches(Filter(field="f", op="missing"), None, FieldType.STRING) is True
    assert _matches(Filter(field="f", op="present"), None, FieldType.STRING) is False
    assert _matches(Filter(field="f", op="present"), "x", FieldType.STRING) is True


def test_an_uninterpretable_filter_excludes_rather_than_includes() -> None:
    """Fails closed. A filter the user asked for that silently does nothing is worse than
    one that returns too little, because the second is visible."""
    condition = Filter(field="f", op="gt", value="not a number")
    assert _matches(condition, {"amount": 5.0, "currency": "USD"}, FieldType.CURRENCY) is False


# ---------------------------------------------------------------------------
# The presentation override
# ---------------------------------------------------------------------------


def test_a_single_row_becomes_a_metric_whatever_was_asked_for() -> None:
    single = result([ResultRow("Total", 15890.5, ["r1"])])
    for requested in (VisualKind.BAR, VisualKind.LINE, VisualKind.METRIC):
        assert resolve_kind(requested, single) is VisualKind.METRIC


def test_a_table_of_one_row_stays_a_table() -> None:
    """A one row table is still a legible table, so this override does not apply to it."""
    single = result([ResultRow("Total", 1.0, [])])
    assert resolve_kind(VisualKind.TABLE, single) is VisualKind.TABLE


def test_a_metric_over_several_rows_becomes_a_bar_chart() -> None:
    """The model chose before the query ran. Showing rows[0] as 'the' figure would hide
    every other row, which is a wrong answer rather than a cramped one."""
    many = result([ResultRow(f"v{i}", float(i), []) for i in range(4)])
    assert resolve_kind(VisualKind.METRIC, many) is VisualKind.BAR


def test_too_many_bars_becomes_a_table() -> None:
    wide = result([ResultRow(f"v{i}", float(i), []) for i in range(MAX_BARS + 5)])
    assert resolve_kind(VisualKind.BAR, wide) is VisualKind.TABLE
    assert resolve_kind(VisualKind.LINE, wide) is VisualKind.TABLE


# ---------------------------------------------------------------------------
# The surfaces
# ---------------------------------------------------------------------------

TWO_ROWS = [ResultRow("Northwind", 12480.5, ["r1"]), ResultRow("Contoso", 3410.0, ["r2"])]


@pytest.mark.parametrize("kind", list(VisualKind))
def test_every_visual_kind_builds_a_valid_surface(kind: VisualKind) -> None:
    """Requirement A2-03, validated against the vendored v0.9 schema."""
    rows = TWO_ROWS if kind is not VisualKind.METRIC else [TWO_ROWS[0]]
    messages, _used = build_surface(visual(kind), result(rows, total=15890.5))
    validate_surface(messages)


def test_the_surface_is_create_then_data_then_components() -> None:
    messages, _ = build_surface(visual(VisualKind.BAR), result(TWO_ROWS))
    assert list(messages[0]) == ["version", "createSurface"]
    assert "updateDataModel" in messages[1]
    assert "updateComponents" in messages[2]
    assert messages[0]["createSurface"]["catalogId"] == CATALOG_ID


def test_the_numbers_live_in_the_data_model_and_the_component_only_binds() -> None:
    """Decision D37, as a structural assertion.

    A number appearing inline in a component would mean something other than the evaluator
    produced it. The component may only carry a path.
    """
    messages, _ = build_surface(visual(VisualKind.BAR), result(TWO_ROWS, total=15890.5))
    data = messages[1]["updateDataModel"]["value"]
    assert data["rows"][0]["value"] == 12480.5

    components = json.dumps(messages[2]["updateComponents"]["components"])
    assert "12480.5" not in components, "a figure leaked into the component tree"
    assert '"path": "/result/rows"' in components


def test_a_metric_binds_the_value_by_path() -> None:
    messages, _ = build_surface(
        visual(VisualKind.METRIC), result([ResultRow("Total Due", 15890.5, [])])
    )
    metric = next(
        component
        for component in messages[2]["updateComponents"]["components"]
        if component["id"] == "visual"
    )
    assert metric["component"] == "Metric"
    assert metric["value"] == {"path": "/result/rows/0/value"}


def test_table_rows_carry_record_identifiers_for_provenance() -> None:
    """Requirement FR-43: provenance has to work inside agent-generated interface."""
    messages, _ = build_surface(visual(VisualKind.TABLE), result(TWO_ROWS))
    rows = messages[1]["updateDataModel"]["value"]["rows"]
    assert rows[0]["record_ids"] == ["r1"]


def test_a_mixed_currency_total_is_shown_with_a_caveat() -> None:
    """Arithmetically real, semantically meaningless. Shown WITH the warning rather than
    hidden or silently summed, because a quietly wrong total is the worst outcome here."""
    mixed = result(TWO_ROWS, total=15890.5, mixed_currency=True, currencies=["EUR", "USD"])
    messages, _ = build_surface(visual(VisualKind.BAR), mixed)
    components = messages[2]["updateComponents"]["components"]
    caveat = next(component for component in components if component["id"] == "caveat")
    assert "EUR" in caveat["text"] and "USD" in caveat["text"]
    assert "root" in {component["id"] for component in components}
    root = next(component for component in components if component["id"] == "root")
    assert "caveat" in root["children"], "the caveat must actually be mounted"


def test_a_single_currency_result_has_no_caveat() -> None:
    clean = result(TWO_ROWS, total=15890.5, unit="USD")
    messages, _ = build_surface(visual(VisualKind.BAR), clean)
    ids = {c["id"] for c in messages[2]["updateComponents"]["components"]}
    assert "caveat" not in ids


def test_an_agent_supplied_title_is_capped_and_flattened() -> None:
    """Requirement A2-05. A title with newlines can break the layout the client intended,
    and there is no legitimate reason for one."""
    nasty = Visual.model_construct(
        kind=VisualKind.BAR,
        title="line one\nline two\n" + "x" * 900,
        query=DataQuery(),
        unit_hint=None,
    )
    messages, _ = build_surface(nasty, result(TWO_ROWS))
    title = messages[1]["updateDataModel"]["value"]["title"]
    assert "\n" not in title
    assert len(title) <= MAX_STRING_LENGTH


# ---------------------------------------------------------------------------
# Validation, and the catalog boundary
# ---------------------------------------------------------------------------


def test_a_component_outside_the_catalog_is_refused() -> None:
    """The security property behind "the agent chooses the presentation"."""
    messages = [
        {"version": "v0.9", "createSurface": {"surfaceId": "s", "catalogId": CATALOG_ID}},
        {
            "version": "v0.9",
            "updateComponents": {
                "surfaceId": "s",
                "components": [{"id": "root", "component": "ScriptTag", "src": "evil.js"}],
            },
        },
    ]
    with pytest.raises(InvalidSurface):
        validate_surface(messages)


def test_a_message_without_a_version_is_refused() -> None:
    with pytest.raises(InvalidSurface):
        validate_surface([{"createSurface": {"surfaceId": "s", "catalogId": CATALOG_ID}}])


def test_a_surface_needs_exactly_one_root() -> None:
    base = {"version": "v0.9", "createSurface": {"surfaceId": "s", "catalogId": CATALOG_ID}}
    with pytest.raises(InvalidSurface):
        validate_surface(
            [
                base,
                {
                    "version": "v0.9",
                    "updateComponents": {
                        "surfaceId": "s",
                        "components": [{"id": "a", "component": "Text"}],
                    },
                },
            ]
        )


def test_messages_may_not_span_two_surfaces() -> None:
    with pytest.raises(InvalidSurface):
        validate_surface(
            [
                {
                    "version": "v0.9",
                    "createSurface": {"surfaceId": "one", "catalogId": CATALOG_ID},
                },
                {"version": "v0.9", "updateDataModel": {"surfaceId": "two", "value": {}}},
            ]
        )


def test_the_catalog_lists_exactly_the_components_we_ship() -> None:
    names = component_names()
    assert {"Metric", "BarChart", "LineChart", "ResultTable"} <= set(names)
    assert "ScriptTag" not in names


# ---------------------------------------------------------------------------
# Placeholder paths, decision D46
# ---------------------------------------------------------------------------


def test_placeholder_paths_cover_the_figures_prose_may_quote() -> None:
    paths = result_paths(
        result(TWO_ROWS, total=15890.5, unit="USD", value_type="currency")
    )
    assert paths["result.total"] == (15890.5, "USD")
    assert paths["result.rows.0.value"] == (12480.5, "USD")
    assert paths["result.rows.1.label"] == ("Contoso", None)


def test_a_count_carries_no_currency_unit() -> None:
    """Regression. One shared unit produced prose reading "across 5 USD documents"."""
    paths = result_paths(
        result(TWO_ROWS, total=15890.5, unit="USD", value_type="currency", record_count=5)
    )
    assert paths["result.record_count"] == (5.0, None)
    assert paths["result.rows.0.label"][1] is None


def test_a_non_currency_measure_gets_no_unit() -> None:
    paths = result_paths(result(TWO_ROWS, total=6.0, value_type="number"))
    assert paths["result.total"][1] is None


def test_placeholder_paths_are_flat_strings_not_nested() -> None:
    """The stream processor matches ``{{result.total}}`` textually, so a nested structure
    would need parsing it does not do."""
    for key in result_paths(result(TWO_ROWS)):
        assert isinstance(key, str)
        assert key.startswith("result.")
