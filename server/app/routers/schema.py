"""The user's field schema: reading it, editing it, its history, and its proposals.

Every mutation routes through ``app.schema.versioning.apply``, so an edit a user makes and
a change the system made automatically produce the same kind of row and are equally
reversible. That equivalence is what makes decision D23's confidence-gated auto-apply
defensible rather than a shortcut.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.models import Proposal
from app.deps import Config, CurrentWorkspace, Session
from app.domain.fields import FieldSpec, SchemaChangeAuthor
from app.errors import InvalidSchemaChange, NotFound
from app.logging import get_logger
from app.schema import versioning

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["schema"])
logger = get_logger(__name__)


class SchemaResponse(BaseModel):
    version: int | None
    fields: list[FieldSpec] = Field(default_factory=list)


@router.get("/schema", response_model=SchemaResponse, summary="The current schema")
async def get_schema(workspace: CurrentWorkspace, session: Session) -> SchemaResponse:
    schema = await versioning.current_schema(session, workspace.id)
    if schema is None:
        return SchemaResponse(version=None, fields=[])
    return SchemaResponse(version=schema.version, fields=list(schema.fields))


class SchemaVersionSummary(BaseModel):
    version: int
    created_by: SchemaChangeAuthor
    change_summary: str | None
    created_at: datetime
    field_count: int
    is_current: bool


class SchemaHistory(BaseModel):
    versions: list[SchemaVersionSummary]


@router.get(
    "/schema/versions", response_model=SchemaHistory, summary="Schema history"
)
async def schema_history(workspace: CurrentWorkspace, session: Session) -> SchemaHistory:
    """Requirement FR-15. Marks which entries the system applied without asking."""
    rows = await versioning.history(session, workspace.id)
    newest = rows[0].version if rows else None
    return SchemaHistory(
        versions=[
            SchemaVersionSummary(
                version=row.version,
                created_by=row.created_by,
                change_summary=row.change_summary,
                created_at=row.created_at,
                field_count=len(row.fields),
                is_current=row.version == newest,
            )
            for row in rows
        ]
    )


class UpdateSchemaRequest(BaseModel):
    """The complete new field list. Requirement FR-11.

    A whole list rather than a patch, deliberately: renames, retypes, removals, and
    reorderings all become one shape, and the server never has to infer intent from a
    sequence of operations.
    """

    fields: list[FieldSpec] = Field(min_length=1)
    summary: str | None = Field(
        default=None, max_length=280, description="What you changed, for the history view."
    )


@router.patch("/schema", response_model=SchemaResponse, summary="Edit the schema")
async def update_schema(
    workspace: CurrentWorkspace,
    session: Session,
    settings: Config,
    body: UpdateSchemaRequest,
) -> SchemaResponse:
    row = await versioning.apply(
        session,
        workspace.id,
        body.fields,
        author=SchemaChangeAuthor.USER,
        summary=body.summary or "You edited the schema.",
        settings=settings,
    )
    return SchemaResponse(
        version=row.version, fields=[FieldSpec.model_validate(f) for f in row.fields]
    )


class RevertRequest(BaseModel):
    version: int = Field(ge=1)


@router.post("/schema/revert", response_model=SchemaResponse, summary="Revert the schema")
async def revert_schema(
    workspace: CurrentWorkspace,
    session: Session,
    settings: Config,
    body: RevertRequest,
) -> SchemaResponse:
    """Requirement FR-15's one-click revert.

    Applies the old fields as a NEW version rather than deleting rows, so the history keeps
    both the mistake and the correction.
    """
    row = await versioning.revert(session, workspace.id, body.version, settings=settings)
    return SchemaResponse(
        version=row.version, fields=[FieldSpec.model_validate(f) for f in row.fields]
    )


class ProposalSummary(BaseModel):
    id: UUID
    kind: str
    status: str
    document_id: UUID | None
    payload: dict[str, object]
    created_at: datetime


class ProposalList(BaseModel):
    proposals: list[ProposalSummary]


@router.get(
    "/proposals", response_model=ProposalList, summary="Outstanding schema questions"
)
async def list_proposals(
    workspace: CurrentWorkspace,
    session: Session,
    include_resolved: bool = False,
) -> ProposalList:
    """Only questions that needed a human live here. Decision D23.

    An automatically applied change writes a ``schema_versions`` row and no proposal, so
    "how many decisions are outstanding" is a row count rather than a filtered one.
    """
    query = select(Proposal).where(Proposal.workspace_id == workspace.id)
    if not include_resolved:
        query = query.where(Proposal.status == "pending")
    rows = list((await session.execute(query.order_by(Proposal.created_at))).scalars().all())
    return ProposalList(
        proposals=[
            ProposalSummary(
                id=row.id,
                kind=row.kind,
                status=row.status,
                document_id=row.document_id,
                payload=row.payload,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


class ResolveProposalRequest(BaseModel):
    """The user's decision on a proposal card. Requirement FR-13's three actions."""

    action: Literal["map", "add", "ignore", "merge"]
    target_key: str | None = Field(
        default=None,
        description="For 'map', the existing field to map onto. For 'merge', the field to "
        "merge into.",
    )
    field: FieldSpec | None = Field(
        default=None, description="For 'add', the field to create, so the user can rename "
        "or retype it before it lands."
    )


@router.post(
    "/proposals/{proposal_id}/resolve",
    response_model=SchemaResponse,
    summary="Decide a schema question",
)
async def resolve_proposal(
    workspace: CurrentWorkspace,
    session: Session,
    settings: Config,
    body: ResolveProposalRequest,
    proposal_id: Annotated[UUID, Path()],
) -> SchemaResponse:
    from datetime import UTC

    proposal = (
        await session.execute(
            select(Proposal).where(
                Proposal.id == proposal_id, Proposal.workspace_id == workspace.id
            )
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise NotFound("That proposal is not in this workspace.")
    if proposal.status != "pending":
        raise InvalidSchemaChange("That question has already been answered.")

    fields = await versioning.current_fields(session, workspace.id)
    by_key = {field.key: field for field in fields}
    summary: str

    if body.action == "ignore":
        proposal.status = "dismissed"
        proposal.resolved_at = datetime.now(UTC)
        await session.flush()
        schema = await versioning.current_schema(session, workspace.id)
        return SchemaResponse(
            version=schema.version if schema else None,
            fields=list(schema.fields) if schema else [],
        )

    if body.action == "map":
        incoming = str(proposal.payload.get("incoming_key", ""))
        if not body.target_key or body.target_key not in by_key:
            raise InvalidSchemaChange("Choose an existing field to map onto.")
        target = by_key[body.target_key]
        if incoming and incoming not in target.source_keys:
            target.source_keys.append(incoming)
        summary = f"You mapped {incoming or 'that field'} onto {target.label}."

    elif body.action == "add":
        spec = body.field
        if spec is None:
            payload = proposal.payload
            spec = FieldSpec(
                key=str(payload.get("incoming_key", "")),
                label=str(payload.get("incoming_label") or payload.get("incoming_key", "")),
                type=payload.get("incoming_type", "string"),  # type: ignore[arg-type]
            )
        if spec.key in by_key:
            raise InvalidSchemaChange(f"{spec.key!r} is already a field in your schema.")
        fields = [*fields, spec]
        summary = f"You added {spec.label} as a new field."

    else:  # merge, from an initial_schema question
        left = str(proposal.payload.get("left_key", ""))
        target_key = body.target_key or str(proposal.payload.get("right_key", ""))
        if left not in by_key or target_key not in by_key:
            raise InvalidSchemaChange("Both fields must still exist to merge them.")
        target = by_key[target_key]
        source = by_key[left]
        for alias in [source.key, *source.source_keys]:
            if alias not in target.source_keys:
                target.source_keys.append(alias)
        fields = [field for field in fields if field.key != left]
        summary = f"You merged {source.label} into {target.label}."

    proposal.status = "applied"
    proposal.resolved_at = datetime.now(UTC)

    row = await versioning.apply(
        session,
        workspace.id,
        fields,
        author=SchemaChangeAuthor.USER,
        summary=summary,
        settings=settings,
    )
    logger.info(
        "schema.proposal_resolved",
        proposal_id=str(proposal_id),
        action=body.action,
        version=row.version,
    )
    return SchemaResponse(
        version=row.version, fields=[FieldSpec.model_validate(f) for f in row.fields]
    )
