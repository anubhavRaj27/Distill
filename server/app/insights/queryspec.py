"""What the model is allowed to ask for. Decision D37.

The single most important property of this module is what it makes **impossible**. A model
cannot return a number to display, cannot return code, and cannot return SQL. It returns a
declarative specification over the workspace's own fields, and
``app.insights.evaluate`` computes the answer from the extracted records.

That is the data-binding rule from product principle 3, and the reason for it is specific
rather than doctrinal: a language model asked to total a column will produce a plausible
total, and a plausible total is indistinguishable from a correct one until someone checks.
In a product whose entire claim is that every figure on screen can be traced, a figure the
model typed is the one thing that cannot be.

The shape is deliberately narrow. It expresses "aggregate this field, grouped by that one,
filtered like so", which covers the questions a person actually asks of a pile of invoices,
and nothing more. A richer specification would be a query language, and a query language the
model writes is the thing decision D35 removed.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.domain.chat import VisualKind

Aggregate = Literal["sum", "count", "avg", "min", "max"]
Bucket = Literal["none", "month", "quarter", "year"]
FilterOp = Literal[
    "eq", "ne", "gt", "gte", "lt", "lte", "contains", "missing", "present"
]
SortOrder = Literal["value_desc", "value_asc", "label_asc"]

MAX_LIMIT = 50
"""Rows one query may return. A bar chart past thirty bars is unreadable and a table past
fifty is a spreadsheet, so this is a presentation limit as much as a cost one."""


class Filter(BaseModel):
    """One condition on a field."""

    field: str = Field(description="Field key from the workspace schema.")
    op: FilterOp = "eq"
    value: Any | None = Field(
        default=None,
        description="Compared against the field's stored value, using the same type-aware "
        "parsing the extraction pipeline used. Ignored for 'missing' and 'present'.",
    )

    @model_validator(mode="after")
    def _value_required_unless_presence(self) -> Self:
        if self.op not in ("missing", "present") and self.value is None:
            raise ValueError(f"filter on {self.field!r} with op {self.op!r} needs a value")
        return self


class DataQuery(BaseModel):
    """An aggregation over the workspace's records."""

    aggregate: Aggregate = "count"
    measure_field: str | None = Field(
        default=None,
        description="The field to aggregate. Null means count records, which is the only "
        "aggregate that needs no measure.",
    )
    group_by: str | None = Field(
        default=None, description="Field key to group by. Null produces a single total."
    )
    bucket: Bucket = Field(
        default="none",
        description="Date bucketing for a date group_by. Anything other than 'none' makes "
        "the result a time series, which is what a line chart wants.",
    )
    filters: list[Filter] = Field(default_factory=list, max_length=8)
    sort: SortOrder = "value_desc"
    limit: int = Field(default=20, ge=1, le=MAX_LIMIT)

    @model_validator(mode="after")
    def _measure_required_for_real_aggregates(self) -> Self:
        if self.aggregate != "count" and not self.measure_field:
            raise ValueError(
                f"aggregate {self.aggregate!r} needs a measure_field; only 'count' can "
                f"work without one"
            )
        if self.bucket != "none" and not self.group_by:
            raise ValueError("bucket needs a group_by field to bucket")
        return self

    @property
    def is_single_value(self) -> bool:
        """Whether this can only produce one row, which is what a metric renders."""
        return self.group_by is None


class Visual(BaseModel):
    """The model's choice of what to show, and what to compute for it.

    ``kind`` is the agent's presentation call (product principle 4), but it is a *proposal*:
    ``app.a2ui.build`` overrides it when the evaluated data contradicts it, because a bar
    chart of one bar and a line chart of ungrouped data are worse than the shapes they
    should have been.
    """

    kind: VisualKind
    title: str = Field(max_length=120)
    query: DataQuery
    unit_hint: str | None = Field(
        default=None,
        max_length=16,
        description="Currency code or unit the server should format the values with, when "
        "the model knows it from the schema. The server still formats; this only says how.",
    )

    @model_validator(mode="after")
    def _kind_matches_the_query_shape(self) -> Self:
        if self.kind is VisualKind.LINE and self.query.bucket == "none":
            # A line chart implies an ordered axis. Without bucketing there is nothing to
            # order by, so this is a mistake worth catching at the boundary.
            raise ValueError("a line visual needs a bucketed date group_by")
        if self.kind is VisualKind.METRIC and not self.query.is_single_value:
            raise ValueError("a metric visual needs a query that produces a single value")
        return self
