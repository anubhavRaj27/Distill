"""Per-field statistics. Implementation section 6.5, decision D29.

Used for two things, and the second is why the shape matters: suggested questions
(requirement FR-25) and the dashboard planner (FR-30). Both hand these numbers to a model
and ask it to propose something worth looking at.

That is the point of computing them at all. A planner given only field names proposes
plausible-sounding panels over columns almost no document filled in, and the result is a
dashboard of empty charts. A planner given coverage and ranges proposes panels grounded in
what the data actually contains, and its rationale can cite a real number.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.fields import FieldSpec, FieldType
from app.insights.evaluate import label_of, load_records, numeric_of
from app.logging import get_logger

logger = get_logger(__name__)

TOP_VALUES = 5


@dataclass
class FieldStats:
    key: str
    label: str
    type: str
    present: int = 0
    total_records: int = 0
    distinct: int = 0
    numeric_min: float | None = None
    numeric_max: float | None = None
    numeric_sum: float | None = None
    date_min: str | None = None
    date_max: str | None = None
    top_values: list[tuple[str, int]] = dataclass_field(default_factory=list)
    currencies: list[str] = dataclass_field(default_factory=list)

    @property
    def coverage(self) -> float:
        """Fraction of records that have this field. The planner's most useful signal."""
        return self.present / self.total_records if self.total_records else 0.0

    @property
    def is_groupable(self) -> bool:
        """Whether grouping by this produces a useful axis.

        A field where every value is distinct (an invoice number) makes one bar per
        document, and a field with one value makes one bar. Neither is a chart.
        """
        return 2 <= self.distinct <= 30

    def describe(self) -> str:
        """One line for a prompt."""
        parts = [
            f"`{self.key}` ({self.type})",
            f"present in {self.present}/{self.total_records} documents "
            f"({self.coverage:.0%})",
            f"{self.distinct} distinct values",
        ]
        if self.numeric_min is not None:
            parts.append(
                f"range {self.numeric_min:,.2f} to {self.numeric_max:,.2f}, "
                f"sum {self.numeric_sum:,.2f}"
            )
        if self.currencies:
            parts.append(f"currencies {', '.join(self.currencies)}")
        if self.date_min:
            parts.append(f"dates {self.date_min} to {self.date_max}")
        if self.top_values:
            top = ", ".join(f"{value} ({count})" for value, count in self.top_values[:3])
            parts.append(f"most common: {top}")
        return " — ".join(parts)


async def field_statistics(
    session: AsyncSession, workspace_id: UUID, fields: list[FieldSpec]
) -> list[FieldStats]:
    """Compute statistics for every field in the schema."""
    records = await load_records(session, workspace_id)
    total = len(records)

    stats: list[FieldStats] = []
    for field in fields:
        entry = FieldStats(
            key=field.key, label=field.label, type=field.type.value, total_records=total
        )
        labels: list[str] = []
        numbers: list[float] = []
        dates: list[str] = []
        currencies: set[str] = set()

        for record in records:
            stored = record.values.get(field.key)
            if stored is None or stored[0] is None:
                continue
            entry.present += 1
            value, value_type = stored

            labels.append(label_of(value, value_type))
            number = numeric_of(value, value_type)
            if number is not None:
                numbers.append(number)
            if field.type is FieldType.DATE and isinstance(value, str):
                dates.append(value[:10])
            if isinstance(value, dict) and value.get("currency"):
                currencies.add(str(value["currency"]))

        entry.distinct = len(set(labels))
        entry.top_values = Counter(labels).most_common(TOP_VALUES)
        entry.currencies = sorted(currencies)
        if numbers:
            entry.numeric_min = min(numbers)
            entry.numeric_max = max(numbers)
            entry.numeric_sum = sum(numbers)
        if dates:
            entry.date_min = min(dates)
            entry.date_max = max(dates)
        stats.append(entry)

    logger.info(
        "stats.computed", workspace_id=str(workspace_id), fields=len(stats), records=total
    )
    return stats


def render_stats(stats: list[FieldStats]) -> str:
    """Statistics as prompt text, widest coverage first.

    Ordered by coverage so a model reading top-down sees the fields most documents actually
    have, which is what it should be proposing panels over.
    """
    if not stats:
        return "[no fields yet]"
    ordered = sorted(stats, key=lambda entry: -entry.coverage)
    return "\n".join(f"- {entry.describe()}" for entry in ordered)
