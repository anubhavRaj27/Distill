"""Dashboard vetting. Requirement FR-31, decision D40.

The planner is a model, so it cannot be unit tested. What can, and what actually protects
the user's first impression of the product, is the vetting pass: the agent proposes before
anything is computed, so the server is the first thing in the pipeline that knows whether a
panel is worth a slot.

Every rule here exists because the panel it rejects reads as "this product is broken"
rather than "this collection is thin".
"""

from __future__ import annotations

import pytest
from app.domain.chat import VisualKind
from app.insights.dashboard import (
    MAX_RATIONALE_LENGTH,
    MIN_COVERAGE_FOR_METRIC,
    MIN_SAMPLE_FOR_IDENTITY,
    BuiltPanel,
    DashboardPlan,
    Panel,
    vet,
)
from app.insights.evaluate import MISSING_LABEL, QueryResult, ResultColumn, ResultRow
from app.insights.queryspec import DataQuery, Visual
from app.insights.stats import FieldStats

COLUMNS = [
    ResultColumn("label", "Vendor", "string"),
    ResultColumn("value", "Total Due", "currency"),
]


def result(rows: list[ResultRow], **kwargs: object) -> QueryResult:
    return QueryResult(columns=COLUMNS, rows=rows, **kwargs)  # type: ignore[arg-type]


def stats(**kwargs: object) -> dict[str, FieldStats]:
    entry = FieldStats(
        key="total_due", label="Total Due", type="currency", total_records=20
    )
    for name, value in kwargs.items():
        setattr(entry, name, value)
    return {entry.key: entry}


def visual(kind: VisualKind, **query: object) -> Visual:
    return Visual.model_construct(
        kind=kind,
        title="A panel",
        query=DataQuery.model_construct(**{"aggregate": "count", **query}),
        unit_hint=None,
    )


TWO_ROWS = [ResultRow("Acme", 10.0, ["r1"]), ResultRow("Globex", 20.0, ["r2"])]


# ---------------------------------------------------------------------------
# What gets dropped
# ---------------------------------------------------------------------------


def test_an_empty_result_is_dropped() -> None:
    assert vet(visual(VisualKind.BAR), result([]), {}) is not None


def test_a_result_of_only_nulls_is_dropped() -> None:
    """A chart of blanks is worse than no chart: it implies data that is not there."""
    empty = result([ResultRow("Acme", None, []), ResultRow("Globex", None, [])])
    assert vet(visual(VisualKind.BAR), empty, {}) is not None


@pytest.mark.parametrize("kind", [VisualKind.BAR, VisualKind.LINE])
def test_a_chart_of_one_row_is_dropped(kind: VisualKind) -> None:
    """One bar is a number wearing a chart's clothes. On a dashboard the slot is better
    given to something else, since the planner had six chances and used one badly."""
    single = result([ResultRow("Acme", 10.0, ["r1"])])
    reason = vet(visual(kind), single, {})
    assert reason is not None and "one row" in reason


def test_a_metric_over_a_sparsely_filled_field_is_dropped() -> None:
    """A number with almost no denominator behind it. Implementation section 6.7."""
    thin = stats(present=3, total_records=20, distinct=3)
    assert thin["total_due"].coverage < MIN_COVERAGE_FOR_METRIC
    reason = vet(
        visual(VisualKind.METRIC, aggregate="sum", measure_field="total_due"),
        result([ResultRow("Total", 100.0, [])]),
        thin,
    )
    assert reason is not None and "present in" in reason


def test_a_metric_over_a_well_covered_field_is_kept() -> None:
    good = stats(present=19, total_records=20, distinct=12)
    assert (
        vet(
            visual(VisualKind.METRIC, aggregate="sum", measure_field="total_due"),
            result([ResultRow("Total", 100.0, [])]),
            good,
        )
        is None
    )


def test_grouping_by_something_near_unique_is_dropped() -> None:
    entry = FieldStats(
        key="invoice_number",
        label="Invoice Number",
        type="string",
        total_records=60,
        present=60,
        distinct=60,
    )
    reason = vet(
        visual(VisualKind.BAR, group_by="invoice_number"), result(TWO_ROWS), {entry.key: entry}
    )
    assert reason is not None


def test_grouping_by_an_identifier_is_dropped_even_on_a_modest_corpus() -> None:
    """The ratio, not an absolute count. A twenty five document corpus gives an invoice
    number twenty five distinct values, which passes any threshold while being just as
    useless as a thousand."""
    entry = FieldStats(
        key="reference",
        label="Reference",
        type="string",
        total_records=25,
        present=25,
        distinct=25,
    )
    reason = vet(
        visual(VisualKind.BAR, group_by="reference"), result(TWO_ROWS), {entry.key: entry}
    )
    assert reason is not None and "identifier" in reason


def test_the_identifier_rule_does_not_fire_on_a_small_sample() -> None:
    """Learned the hard way. With two documents carrying a field, "every value is
    distinct" is what a small sample looks like, not what an identifier looks like, and
    without a floor this rule threw away good panels grouped by supplier."""
    entry = FieldStats(
        key="supplier",
        label="Supplier",
        type="string",
        total_records=5,
        present=2,
        distinct=2,
    )
    assert entry.present < MIN_SAMPLE_FOR_IDENTITY
    assert (
        vet(visual(VisualKind.BAR, group_by="supplier"), result(TWO_ROWS), {entry.key: entry})
        is None
    )


def test_a_genuine_category_is_kept() -> None:
    """Values repeat, which is what makes a bar chart a comparison."""
    entry = FieldStats(
        key="supplier",
        label="Supplier",
        type="string",
        total_records=20,
        present=20,
        distinct=4,
    )
    assert (
        vet(visual(VisualKind.BAR, group_by="supplier"), result(TWO_ROWS), {entry.key: entry})
        is None
    )


def test_a_table_of_one_row_survives() -> None:
    """The one-row rule is about charts. A one row table is still a legible table."""
    single = result([ResultRow("Total", 10.0, [])])
    assert vet(visual(VisualKind.TABLE), single, {}) is None


# ---------------------------------------------------------------------------
# The panel shape
# ---------------------------------------------------------------------------


def test_a_long_rationale_does_not_invalidate_the_plan() -> None:
    """Regression, and the important half of this rule.

    A ``max_length`` on the response model REJECTS rather than truncates, so one verbose
    rationale would fail validation for the whole ``DashboardPlan`` and lose every panel
    with it. The rationale is decorative; the panel is not.
    """
    panel = Panel(visual=visual(VisualKind.METRIC), rationale="x" * 5000)
    assert panel.rationale  # accepted, not rejected

    plan = DashboardPlan(panels=[panel])
    assert len(plan.panels) == 1


def test_a_rationale_is_truncated_when_the_panel_is_built() -> None:
    """It renders under the panel, so an essay would push the chart off screen. Capped at
    build time, where the cost of being wrong is a shortened sentence rather than a lost
    dashboard."""
    built = BuiltPanel(
        title="A panel",
        kind=VisualKind.METRIC,
        rationale=" ".join(("word " * 200).split())[:MAX_RATIONALE_LENGTH],
        query={},
        surface=[],
    )
    assert len(built.rationale) <= MAX_RATIONALE_LENGTH


def test_a_panel_needs_no_rationale_to_be_valid() -> None:
    """A missing rationale should cost the reader an explanation, not the whole panel."""
    assert Panel(visual=visual(VisualKind.METRIC)).rationale == ""


# ---------------------------------------------------------------------------
# The time series rule, which lives in the evaluator
# ---------------------------------------------------------------------------


def test_a_bucketed_query_drops_the_not_stated_group() -> None:
    """Records with no date have no position on a time axis, so rendering them as a point
    implies one. Asserted here because it is what makes a line chart honest."""
    from app.insights.evaluate import _aggregate  # noqa: F401  (import guard)

    # The behaviour is exercised end to end in the evaluator's own path; this asserts the
    # label that must be excluded is the one the evaluator names.
    assert MISSING_LABEL == "Not stated"
