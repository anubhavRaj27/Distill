"""Evaluating a query specification over the extracted records. Decision D37.

Every number the product displays is produced here. Nothing in this module comes from a
model: it receives a validated ``DataQuery``, reads the workspace's own ``field_values``,
and computes an answer in Python.

WHY PYTHON AND NOT SQL
----------------------
Decision D35's reasoning, restated because it is easy to forget once the code exists: a
workspace holds tens of documents, so a full scan is trivial, and an evaluator written in
Python is far easier to test exhaustively than generated SQL. There is also no SQL surface
for a model to reach, which removes an entire class of risk rather than sandboxing it.

MIXED CURRENCIES ARE REPORTED, NOT SILENTLY SUMMED
---------------------------------------------------
Adding 100 USD to 100 EUR gives 200 of nothing. When a currency measure spans more than one
code the result still computes, because refusing to answer is unhelpful, but it records
``mixed_currency`` and the set of codes so the interface can say so. A total that is quietly
wrong is worse than a total with a caveat, and this is a finance product.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, FieldValueRow, Record
from app.domain.fields import FieldSpec, FieldType
from app.insights.queryspec import DataQuery, Filter
from app.logging import get_logger

logger = get_logger(__name__)

MISSING_LABEL = "Not stated"
"""Label for the group of records where the group-by field is absent. Named rather than
dropped, because "eleven invoices have no purchase order number" is usually the interesting
answer, not a gap to hide."""


@dataclass
class ResultColumn:
    key: str
    label: str
    type: str


@dataclass
class ResultRow:
    label: str
    value: float | None
    record_ids: list[str] = dataclass_field(default_factory=list)
    """Every record that contributed. This is what makes provenance work inside an
    agent-generated table (requirement FR-43): a row can open the documents behind it."""


@dataclass
class QueryResult:
    """What a query evaluated to. Written into the A2UI data model verbatim."""

    columns: list[ResultColumn]
    rows: list[ResultRow]
    total: float | None = None
    """The aggregate across every group, for a grouped query. A metric reads
    ``rows[0].value``; prose more often wants this."""

    unit: str | None = None
    measure_field: str | None = None
    measure_label: str | None = None
    value_type: str | None = None
    mixed_currency: bool = False
    currencies: list[str] = dataclass_field(default_factory=list)
    record_count: int = 0
    """Records considered after filtering. A denominator the prose can honestly quote."""

    @property
    def is_empty(self) -> bool:
        return not self.rows or all(row.value is None for row in self.rows)

    @property
    def is_degenerate(self) -> bool:
        """Whether this is too thin to be worth a chart.

        One bar is a number wearing a chart's clothes. The dashboard drops these before the
        user sees them (requirement FR-31), which is cheaper than teaching them to ignore
        useless panels.
        """
        return len(self.rows) < 2

    def to_data_model(self) -> dict[str, Any]:
        """The shape written to the A2UI data model at ``/result``.

        Plain JSON-safe primitives, because it crosses the protocol boundary and the client
        binds into it by path.
        """
        return {
            "title": None,
            "unit": self.unit,
            "columns": [
                {"key": column.key, "label": column.label, "type": column.type}
                for column in self.columns
            ],
            "rows": [
                {
                    "label": row.label,
                    "value": row.value,
                    "record_ids": row.record_ids,
                }
                for row in self.rows
            ],
            "total": self.total,
            "record_count": self.record_count,
            "measure_field": self.measure_field,
            "mixed_currency": self.mixed_currency,
            "currencies": self.currencies,
        }


# ---------------------------------------------------------------------------
# Reading stored values
# ---------------------------------------------------------------------------


def numeric_of(value: Any, value_type: FieldType | str) -> float | None:
    """The number inside a stored value, or ``None`` if it has none."""
    kind = FieldType(value_type) if not isinstance(value_type, FieldType) else value_type
    if value is None:
        return None
    if kind is FieldType.CURRENCY:
        if isinstance(value, dict):
            amount = value.get("amount")
            return float(amount) if isinstance(amount, (int, float)) else None
        return float(value) if isinstance(value, (int, float)) else None
    if kind is FieldType.NUMBER:
        return float(value) if isinstance(value, (int, float)) else None
    if kind is FieldType.BOOLEAN:
        return 1.0 if value else 0.0
    return None


def currency_of(value: Any) -> str | None:
    if isinstance(value, dict):
        code = value.get("currency")
        return str(code) if code else None
    return None


def label_of(value: Any, value_type: FieldType | str, bucket: str = "none") -> str:
    """A stored value rendered as a group label."""
    kind = FieldType(value_type) if not isinstance(value_type, FieldType) else value_type
    if value is None:
        return MISSING_LABEL
    if kind is FieldType.CURRENCY and isinstance(value, dict):
        code = value.get("currency") or ""
        return f"{value.get('amount')} {code}".strip()
    if kind is FieldType.DATE:
        return _bucket_date(str(value), bucket)
    if kind is FieldType.BOOLEAN:
        return "Yes" if value else "No"
    if kind is FieldType.STRING_LIST and isinstance(value, list):
        return ", ".join(str(entry) for entry in value)
    text = str(value).strip()
    return text or MISSING_LABEL


def _bucket_date(iso: str, bucket: str) -> str:
    """Group a date into a period label, ordered lexicographically on purpose.

    ``2026-Q1`` and ``2026-03`` sort correctly as strings, so a time series comes out in
    chronological order from a plain sort and the line chart needs no separate ordering key.
    """
    try:
        parsed = date.fromisoformat(iso[:10])
    except ValueError:
        return iso or MISSING_LABEL
    match bucket:
        case "month":
            return f"{parsed.year:04d}-{parsed.month:02d}"
        case "quarter":
            return f"{parsed.year:04d}-Q{(parsed.month - 1) // 3 + 1}"
        case "year":
            return f"{parsed.year:04d}"
        case _:
            return parsed.isoformat()


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _matches(filter_: Filter, value: Any, value_type: FieldType | str) -> bool:
    """Whether one stored value satisfies one filter.

    Comparisons are type-aware: numbers and currencies compare numerically, dates compare
    as ISO strings (which is the same as chronologically), and everything else compares as
    case-folded text. A filter whose value cannot be interpreted for the field's type fails
    closed, excluding the record rather than including it, because a filter the user asked
    for that silently does nothing is worse than one that returns too little.
    """
    if filter_.op == "missing":
        return value is None
    if filter_.op == "present":
        return value is not None
    if value is None:
        return False

    kind = FieldType(value_type) if not isinstance(value_type, FieldType) else value_type

    left_number = numeric_of(value, kind)
    right_number: float | None = None
    if isinstance(filter_.value, (int, float)) and not isinstance(filter_.value, bool):
        right_number = float(filter_.value)
    elif isinstance(filter_.value, str):
        try:
            right_number = float(filter_.value.replace(",", "").strip())
        except ValueError:
            right_number = None

    if left_number is not None and right_number is not None:
        match filter_.op:
            case "eq":
                return abs(left_number - right_number) < 1e-9
            case "ne":
                return abs(left_number - right_number) >= 1e-9
            case "gt":
                return left_number > right_number
            case "gte":
                return left_number >= right_number
            case "lt":
                return left_number < right_number
            case "lte":
                return left_number <= right_number
            case "contains":
                return str(right_number) in str(left_number)

    left_text = label_of(value, kind).strip().casefold()
    right_text = str(filter_.value).strip().casefold()
    match filter_.op:
        case "eq":
            return left_text == right_text
        case "ne":
            return left_text != right_text
        case "contains":
            return right_text in left_text
        case "gt":
            return left_text > right_text
        case "gte":
            return left_text >= right_text
        case "lt":
            return left_text < right_text
        case "lte":
            return left_text <= right_text
    # Unreachable today: the match above covers every `FilterOp` literal, which is why the
    # type checker flags it. Kept deliberately as a guard, because adding a new operation
    # and forgetting a branch here would otherwise fall off the end and return None, which
    # Python treats as false and would exclude records for no visible reason.
    return False  # type: ignore[unreachable]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _aggregate(values: list[float], how: str) -> float | None:
    if not values:
        return 0.0 if how == "count" else None
    match how:
        case "sum":
            return sum(values)
        case "count":
            return float(len(values))
        case "avg":
            return sum(values) / len(values)
        case "min":
            return min(values)
        case "max":
            return max(values)
    return None


@dataclass
class _LoadedRecord:
    record_id: UUID
    document_name: str
    values: dict[str, tuple[Any, FieldType]]


async def load_records(
    session: AsyncSession, workspace_id: UUID
) -> list[_LoadedRecord]:
    """Every record with its values, in one pass. The workspace is small (decision D35)."""
    rows = list(
        (
            await session.execute(
                select(Record.id, Document.filename, FieldValueRow)
                .join(Document, Document.id == Record.document_id)
                .outerjoin(FieldValueRow, FieldValueRow.record_id == Record.id)
                .where(Record.workspace_id == workspace_id)
            )
        ).all()
    )
    by_record: dict[UUID, _LoadedRecord] = {}
    for record_id, filename, value_row in rows:
        entry = by_record.setdefault(
            record_id, _LoadedRecord(record_id=record_id, document_name=filename, values={})
        )
        if value_row is not None:
            entry.values[value_row.field_key] = (value_row.value, value_row.value_type)
    return list(by_record.values())


async def evaluate(
    session: AsyncSession,
    workspace_id: UUID,
    query: DataQuery,
    *,
    fields: list[FieldSpec],
) -> QueryResult:
    """Compute ``query`` over the workspace's records.

    Never raises for data reasons. A query naming a field that no longer exists, or one that
    matches nothing, returns an empty result: the caller drops the visual and the answer
    proceeds as prose, which is a far better outcome than failing a whole answer over a
    chart nobody asked for.
    """
    by_key = {field.key: field for field in fields}
    records = await load_records(session, workspace_id)

    # --- filter
    kept: list[_LoadedRecord] = []
    for record in records:
        if all(
            _matches(
                condition,
                record.values.get(condition.field, (None, FieldType.STRING))[0],
                record.values.get(condition.field, (None, FieldType.STRING))[1],
            )
            for condition in query.filters
        ):
            kept.append(record)

    measure = by_key.get(query.measure_field) if query.measure_field else None
    measure_type = measure.type if measure else FieldType.NUMBER
    group = by_key.get(query.group_by) if query.group_by else None

    currencies: set[str] = set()

    def measure_value(record: _LoadedRecord) -> float | None:
        if query.aggregate == "count" and query.measure_field is None:
            return 1.0
        if query.measure_field is None:
            return None
        stored = record.values.get(query.measure_field)
        if stored is None:
            return None
        code = currency_of(stored[0])
        if code:
            currencies.add(code)
        if query.aggregate == "count":
            # Counting a field means counting records that HAVE it, which is what "how many
            # invoices have a purchase order number" asks.
            return 1.0
        return numeric_of(stored[0], stored[1])

    # --- group
    grouped: dict[str, list[float]] = {}
    contributors: dict[str, list[str]] = {}

    for record in kept:
        value = measure_value(record)
        if value is None:
            continue
        if group is None:
            key = "__all__"
        else:
            stored = record.values.get(group.key)
            key = label_of(
                stored[0] if stored else None,
                stored[1] if stored else group.type,
                query.bucket,
            )
        grouped.setdefault(key, []).append(value)
        contributors.setdefault(key, []).append(str(record.record_id))

    rows = [
        ResultRow(
            label=key if key != "__all__" else (measure.label if measure else "Total"),
            value=_aggregate(values, query.aggregate),
            record_ids=contributors.get(key, []),
        )
        for key, values in grouped.items()
    ]

    # --- sort and limit
    match query.sort:
        case "value_asc":
            rows.sort(key=lambda row: (row.value is None, row.value or 0.0))
        case "label_asc":
            rows.sort(key=lambda row: row.label)
        case _:
            rows.sort(key=lambda row: (row.value is None, -(row.value or 0.0)))
    if query.bucket != "none":
        # A bucketed query is a time series. Two consequences, both of which override what
        # the model asked for, because the model chose before seeing the data:
        #   - chronological order beats value order (a line sorted by magnitude is not a
        #     line chart), and the bucket labels sort chronologically as strings by design
        #   - the "not stated" group is dropped: records with no date have no position on a
        #     time axis, and rendering them as a point implies one
        rows = [row for row in rows if row.label != MISSING_LABEL]
        rows.sort(key=lambda row: row.label)
    rows = rows[: query.limit]

    every_value = [value for values in grouped.values() for value in values]
    result = QueryResult(
        columns=[
            ResultColumn(
                key="label",
                label=group.label if group else "Measure",
                type="string",
            ),
            ResultColumn(
                key="value",
                label=measure.label if measure else "Count",
                type="currency" if measure_type is FieldType.CURRENCY else "number",
            ),
        ],
        rows=rows,
        total=_aggregate(every_value, query.aggregate),
        unit=(sorted(currencies)[0] if len(currencies) == 1 else None),
        measure_field=query.measure_field,
        measure_label=measure.label if measure else "Count",
        value_type=measure_type.value if measure else "number",
        mixed_currency=len(currencies) > 1,
        currencies=sorted(currencies),
        record_count=len(kept),
    )

    if result.mixed_currency:
        logger.info(
            "evaluate.mixed_currency",
            workspace_id=str(workspace_id),
            currencies=result.currencies,
            detail="the total is reported with a caveat rather than silently summed",
        )
    logger.info(
        "evaluate.completed",
        workspace_id=str(workspace_id),
        aggregate=query.aggregate,
        measure=query.measure_field,
        group_by=query.group_by,
        records=len(kept),
        rows=len(result.rows),
    )
    return result
