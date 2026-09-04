"""Workspace creation and overview. Requirement FR-01."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth import hash_token, mint_token
from app.db.models import DashboardRow, Document, Record, SchemaVersion, Workspace
from app.deps import CurrentWorkspace, Session
from app.domain.document import DocumentStatus
from app.domain.fields import FieldSpec
from app.logging import bind_context, get_logger

router = APIRouter(prefix="/workspaces", tags=["workspaces"])
logger = get_logger(__name__)


class CreateWorkspaceRequest(BaseModel):
    label: str | None = Field(default=None, max_length=120)


class CreateWorkspaceResponse(BaseModel):
    id: UUID
    token: str = Field(
        description="Bearer token for every subsequent request. Returned ONCE and never "
        "recoverable: only its hash is stored. Anyone holding it has full access to this "
        "workspace, which is the accepted tradeoff of having no accounts (decision D8)."
    )
    created_at: datetime


class DocumentSummary(BaseModel):
    id: UUID
    filename: str
    status: DocumentStatus
    stage_detail: str | None = None
    failure_reason: str | None = None
    page_count: int | None = None
    size_bytes: int
    created_at: datetime


class WorkspaceOverview(BaseModel):
    """Everything the interface needs for a cold start, in one request."""

    id: UUID
    label: str | None
    created_at: datetime
    schema_version: int | None = Field(
        default=None, description="Null when no schema has been agreed yet."
    )
    fields: list[FieldSpec] = Field(default_factory=list)
    documents: list[DocumentSummary] = Field(default_factory=list)
    record_count: int = 0
    dashboard_status: str | None = Field(
        default=None,
        description="pending, ready, or failed. Null when no dashboard row exists yet.",
    )
    dashboard_stale: bool = False
    dashboard_panel_count: int = 0
    last_event_seq: int = Field(
        default=0,
        description="The newest event sequence number. The interface opens its event "
        "stream with this as Last-Event-ID, so a cold start streams only what happens "
        "NEXT rather than replaying the entire history it has just loaded.",
    )


@router.post(
    "",
    response_model=CreateWorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an anonymous workspace",
)
async def create_workspace(
    body: CreateWorkspaceRequest, session: Session
) -> CreateWorkspaceResponse:
    token = mint_token()
    workspace = Workspace(token_hash=hash_token(token), label=body.label)
    session.add(workspace)
    await session.flush()

    bind_context(workspace_id=str(workspace.id))
    logger.info("workspace.created")

    return CreateWorkspaceResponse(
        id=workspace.id, token=token, created_at=workspace.created_at
    )


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceOverview,
    summary="Schema, documents, and counts for a cold start",
)
async def get_workspace(workspace: CurrentWorkspace, session: Session) -> WorkspaceOverview:
    current = (
        await session.execute(
            select(SchemaVersion)
            .where(SchemaVersion.workspace_id == workspace.id)
            .order_by(SchemaVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    documents = (
        (
            await session.execute(
                select(Document)
                .where(Document.workspace_id == workspace.id)
                .order_by(Document.created_at)
            )
        )
        .scalars()
        .all()
    )

    record_count = (
        await session.execute(
            select(func.count()).select_from(Record).where(Record.workspace_id == workspace.id)
        )
    ).scalar_one()

    dashboard = (
        await session.execute(
            select(DashboardRow).where(DashboardRow.workspace_id == workspace.id)
        )
    ).scalar_one_or_none()

    return WorkspaceOverview(
        id=workspace.id,
        label=workspace.label,
        created_at=workspace.created_at,
        schema_version=current.version if current else None,
        fields=[FieldSpec.model_validate(field) for field in (current.fields if current else [])],
        documents=[
            DocumentSummary(
                id=document.id,
                filename=document.filename,
                status=document.status,
                stage_detail=document.stage_detail,
                failure_reason=document.failure_reason,
                page_count=document.page_count,
                size_bytes=document.size_bytes,
                created_at=document.created_at,
            )
            for document in documents
        ],
        record_count=int(record_count),
        dashboard_status=dashboard.status.value if dashboard else None,
        dashboard_stale=bool(dashboard.stale) if dashboard else False,
        dashboard_panel_count=len(dashboard.panels or []) if dashboard else 0,
        last_event_seq=workspace.event_seq,
    )
