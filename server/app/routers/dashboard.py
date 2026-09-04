"""The agent-generated dashboard. Requirements FR-30 to FR-34.

Two routes, and the asymmetry between them is the design. Reading is cheap and always
available; generating costs a model call and therefore only happens when the first batch
finishes or when the user asks. In between, a change marks the dashboard stale and the
interface offers to regenerate rather than deciding for them (FR-33).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.deps import Config, CurrentWorkspace, Session
from app.insights import dashboard as dashboard_module
from app.llm.registry import get_client
from app.logging import get_logger
from app.schema import versioning

router = APIRouter(prefix="/workspaces/{workspace_id}/dashboard", tags=["dashboard"])
logger = get_logger(__name__)


class PanelResponse(BaseModel):
    title: str
    kind: str
    rationale: str = ""
    query: dict[str, Any] = Field(default_factory=dict)
    surface: list[dict[str, Any]] = Field(
        default_factory=list,
        description="A complete A2UI message array. The numbers live in its "
        "updateDataModel message and were computed by the server (decision D37).",
    )


class DashboardResponse(BaseModel):
    status: str
    stale: bool = Field(
        description="Documents were added or values corrected since generation. The "
        "interface offers to regenerate rather than doing it unasked, because "
        "regeneration is a model call."
    )
    panels: list[PanelResponse] = Field(default_factory=list)
    generated_at: str | None = None
    error: str | None = None


def _to_response(row: Any) -> DashboardResponse:
    return DashboardResponse(
        status=row.status.value,
        stale=bool(row.stale),
        panels=[PanelResponse.model_validate(panel) for panel in (row.panels or [])],
        generated_at=row.generated_at.isoformat() if row.generated_at else None,
        error=row.error,
    )


@router.get("", response_model=DashboardResponse, summary="The current dashboard")
async def get_dashboard(
    workspace: CurrentWorkspace, session: Session
) -> DashboardResponse:
    """Persisted panels. Requirement FR-34: a refresh never re-runs generation."""
    row = await dashboard_module.get_or_create(session, workspace.id)
    return _to_response(row)


@router.post(
    "/generate",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Regenerate the dashboard",
)
async def generate(
    workspace: CurrentWorkspace, session: Session, settings: Config
) -> DashboardResponse:
    """Plan, evaluate, vet, and persist.

    Synchronous, unlike a chat answer. A dashboard is one structured call and a handful of
    in-process evaluations, so it completes in about a second on the fast tier, and the
    user pressed a button and is watching. Streaming it would add a second connection to
    reason about for no gain the user could perceive.
    """
    fields = await versioning.current_fields(session, workspace.id)
    row = await dashboard_module.generate(
        session,
        workspace.id,
        fields=fields,
        client=get_client(),
        settings=settings,
    )
    return _to_response(row)
