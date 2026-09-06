"""Generating the dashboard. Requirements FR-30 to FR-34, decision D40.

The agent decides what is worth showing; the server decides whether it was right.

**Why the agent proposes rather than a template.** A fixed dashboard has to assume a schema,
and this product infers the schema per workspace from whatever was uploaded. A template that
knows about vendors and totals is useless for research papers or property listings, which
requirement 1.4 says must get the same experience. So the panels come from a model reading
the schema and the field statistics.

**Why the server vets.** The agent proposes before anything is computed, so it is guessing
at the shape of data it has not seen. Requirement FR-31 says every panel's query is evaluated
and the dead ones dropped **before anything is shown**, and the vetting rules below are the
cheapest possible way to keep a first impression honest: an empty chart, a single bar, or a
metric over a field two documents filled in all read as "this product is broken" rather than
"this collection is thin".

**Why it is persisted and marked stale rather than regenerated.** Regeneration is a model
call. Doing one per upload would spend the user's tokens on a dashboard they may not be
looking at, so a change marks it stale and the user decides (FR-33).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.a2ui.build import build_surface, new_surface_id
from app.config import Settings
from app.db.models import DashboardRow
from app.domain.chat import DashboardStatus, VisualKind
from app.domain.events import DashboardStatusEvent
from app.domain.fields import FieldSpec
from app.events.bus import bus
from app.insights.evaluate import evaluate
from app.insights.queryspec import Visual
from app.insights.stats import FieldStats, field_statistics, render_stats
from app.llm import prompts
from app.llm.base import CallKind, LLMClient, LLMRequest
from app.logging import get_logger

logger = get_logger(__name__)

MIN_COVERAGE_FOR_METRIC = 1 / 3
"""A metric over a field a third of documents filled in is a number with no denominator.
Implementation section 6.7 names this threshold."""

MIN_SAMPLE_FOR_IDENTITY = 5
"""How many documents must carry a field before "every value is distinct" is evidence that
it is an identifier rather than evidence of a small sample."""

MAX_RATIONALE_LENGTH = 240


class Panel(BaseModel):
    """One proposed panel: a visual plus the reason it is worth a slot."""

    visual: Visual
    rationale: str = Field(
        default="",
        description="One sentence citing a statistic. Shown under the panel, because a "
        "dashboard nobody asked for owes the reader an explanation of why it is here."
        "\n\n"
        "Deliberately NOT length-capped here. A `max_length` on a response model REJECTS "
        "rather than truncates, so one verbose rationale would fail validation for the "
        "whole `DashboardPlan` and lose every panel with it. The rationale is decorative; "
        "the panel is not. It is truncated when the panel is built instead.",
    )


class DashboardPlan(BaseModel):
    panels: list[Panel] = Field(default_factory=list, max_length=12)


@dataclass
class BuiltPanel:
    """A panel that survived vetting, with its evaluated surface."""

    title: str
    kind: VisualKind
    rationale: str
    query: dict[str, Any]
    surface: list[dict[str, Any]]

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "kind": self.kind.value,
            "rationale": self.rationale,
            "query": self.query,
            "surface": self.surface,
        }


def vet(
    visual: Visual, result: Any, stats: dict[str, FieldStats]
) -> str | None:
    """Why this panel should not be shown, or ``None`` if it should. Requirement FR-31."""
    if result.is_empty:
        return "the query returned nothing"

    if visual.kind in (VisualKind.BAR, VisualKind.LINE) and len(result.rows) < 2:
        # One bar is a number wearing a chart's clothes. The chat path resolves this by
        # rendering a metric instead; on a dashboard the slot is better given to something
        # else, because the planner had six chances and used one badly.
        return "a chart of one row is a metric, not a chart"

    if visual.kind is VisualKind.METRIC and visual.query.measure_field:
        entry = stats.get(visual.query.measure_field)
        if entry is not None and entry.coverage < MIN_COVERAGE_FOR_METRIC:
            return (
                f"{visual.query.measure_field} is only present in "
                f"{entry.coverage:.0%} of documents"
            )

    if visual.query.group_by:
        entry = stats.get(visual.query.group_by)
        if entry is not None and entry.distinct > 30:
            return f"{visual.query.group_by} has {entry.distinct} distinct values"
        if (
            entry is not None
            and entry.present >= MIN_SAMPLE_FOR_IDENTITY
            and entry.distinct == entry.present
        ):
            # Every document that has this field has a DIFFERENT value, which is what an
            # identifier looks like: an invoice number, a reference. Grouping by it makes
            # one bar per document, so it is a bar code rather than a comparison.
            #
            # The ratio rather than an absolute distinct count, because a 25 document
            # corpus gives an invoice number 25 distinct values, which sails past any
            # threshold while being just as useless.
            #
            # The minimum sample matters just as much, and was learned the hard way: with
            # only two documents carrying a field, "every value is distinct" is what a
            # small sample looks like, not what an identifier looks like. Without the floor
            # this rule threw away perfectly good panels grouped by supplier.
            return (
                f"{visual.query.group_by} has a distinct value for every document, so it "
                f"is an identifier rather than a category"
            )

    return None


async def _plan(
    *,
    fields: list[FieldSpec],
    stats: list[FieldStats],
    document_count: int,
    client: LLMClient,
    settings: Settings,
    workspace_id: UUID,
) -> DashboardPlan:
    prompt = prompts.render(
        "plan_dashboard",
        document_count=document_count,
        schema="\n".join(
            f"- `{field.key}` ({field.type.value})"
            + (f" — {field.description}" if field.description else "")
            for field in fields
        ),
        stats=render_stats(stats),
        max_panels=settings.dashboard_max_panels,
    )
    request = LLMRequest(
        kind=CallKind.PLAN_DASHBOARD,
        prompt=prompt,
        response_model=DashboardPlan,
        # Keyed on the schema version and document count, so a workspace that has not
        # changed replays the same plan rather than paying for a new one.
        fixture_key=f"dashboard-{workspace_id.hex[:12]}-{len(fields)}-{document_count}",
        context={
            "schema": [field.model_dump(mode="json") for field in fields],
            "stats": [
                {
                    "key": entry.key,
                    "label": entry.label,
                    "type": entry.type,
                    "coverage": entry.coverage,
                    "distinct": entry.distinct,
                    "groupable": entry.is_groupable,
                    "currencies": entry.currencies,
                }
                for entry in stats
            ],
            "document_count": document_count,
        },
    )
    response = await client.structured(request)
    plan = response.value
    assert isinstance(plan, DashboardPlan)
    logger.info(
        "dashboard.planned",
        proposed=len(plan.panels),
        model=response.usage.model,
        latency_ms=round(response.usage.latency_ms, 1),
    )
    return plan


async def get_or_create(session: AsyncSession, workspace_id: UUID) -> DashboardRow:
    row = (
        await session.execute(
            select(DashboardRow).where(DashboardRow.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = DashboardRow(workspace_id=workspace_id, status=DashboardStatus.PENDING)
        session.add(row)
        await session.flush()
    return row


async def mark_stale(session: AsyncSession, workspace_id: UUID, *, reason: str) -> None:
    """Flag the dashboard as out of date. Requirement FR-33.

    Called when documents are added, a value is corrected, or fields are merged. Marking
    rather than regenerating is the point: regeneration is a model call, and spending one
    per upload on a screen the user may not be looking at is not theirs to spend.

    A dashboard that has never been generated is left alone: "stale" on an empty dashboard
    would ask the user to refresh something that does not exist.
    """
    row = (
        await session.execute(
            select(DashboardRow).where(DashboardRow.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    if row is None or row.status is not DashboardStatus.READY or row.stale:
        return

    row.stale = True
    await session.flush()
    await bus.publish(
        session,
        workspace_id,
        DashboardStatusEvent(
            seq=0,
            status="ready",
            stale=True,
            panel_count=len(row.panels or []),
        ),
    )
    logger.info("dashboard.marked_stale", workspace_id=str(workspace_id), reason=reason)


async def generate(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    fields: list[FieldSpec],
    client: LLMClient,
    settings: Settings,
) -> DashboardRow:
    """Plan, evaluate, vet, and persist the dashboard.

    Never raises for content reasons. A workspace with no schema, a planner that proposes
    nothing usable, or a model failure all end with a persisted row the interface can
    render honestly, because a broken dashboard must not take the Data screen down with it.
    """
    row = await get_or_create(session, workspace_id)

    if not fields:
        row.status = DashboardStatus.READY
        row.panels = []
        row.stale = False
        row.generated_at = datetime.now(UTC)
        await session.flush()
        return row

    stats = await field_statistics(session, workspace_id, fields)
    stats_by_key = {entry.key: entry for entry in stats}
    document_count = stats[0].total_records if stats else 0

    try:
        plan = await _plan(
            fields=fields,
            stats=stats,
            document_count=document_count,
            client=client,
            settings=settings,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        logger.warning("dashboard.planning_failed", error=type(exc).__name__)
        row.status = DashboardStatus.FAILED
        row.error = (
            "We could not put a dashboard together for this collection. The table and "
            "chat are unaffected."
        )
        row.stale = False
        await session.flush()
        await bus.publish(
            session,
            workspace_id,
            DashboardStatusEvent(seq=0, status="failed", stale=False),
        )
        return row

    built: list[BuiltPanel] = []
    dropped: list[tuple[str, str]] = []

    for panel in plan.panels[: settings.dashboard_max_panels]:
        try:
            result = await evaluate(session, workspace_id, panel.visual.query, fields=fields)
        except Exception as exc:
            dropped.append((panel.visual.title, f"evaluation failed: {type(exc).__name__}"))
            continue

        reason = vet(panel.visual, result, stats_by_key)
        if reason is not None:
            dropped.append((panel.visual.title, reason))
            continue

        # No heading inside the surface: the panel card renders this same title above it.
        surface, kind = build_surface(
            panel.visual,
            result,
            surface_id=new_surface_id("panel"),
            include_title=False,
        )
        built.append(
            BuiltPanel(
                title=panel.visual.title,
                kind=kind,
                rationale=" ".join(panel.rationale.split())[:MAX_RATIONALE_LENGTH],
                query=panel.visual.query.model_dump(mode="json"),
                surface=surface,
            )
        )

    row.status = DashboardStatus.READY
    row.panels = [panel.to_json() for panel in built]
    row.stale = False
    row.error = None
    row.generated_at = datetime.now(UTC)
    await session.flush()

    await bus.publish(
        session,
        workspace_id,
        DashboardStatusEvent(
            seq=0, status="ready", stale=False, panel_count=len(built)
        ),
    )
    logger.info(
        "dashboard.generated",
        workspace_id=str(workspace_id),
        kept=len(built),
        dropped=len(dropped),
        drop_reasons=[reason for _title, reason in dropped],
    )
    return row
