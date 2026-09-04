"""The user's field schema: reading it, renaming a field, merging two fields.

v2 removed the schema history view, one-click revert, and the proposal routes with the
review loop they belonged to (decisions D34 and D38). ``schema_versions`` rows are still
written on every change and are still immutable, because they remain the store of the
current schema and a real audit trail in the database. They are simply not a screen.

What is left is the two operations a user actually wants, and one of them carries weight
beyond its size: **merge** is the resolution path for every uncertain split that decision
D38 produces. "When unsure, keep the fields apart" is only a reasonable default because
undoing it is one action that loses nothing, and this is that action.
"""

from __future__ import annotations

from typing import Self

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from app.deps import CurrentWorkspace, Session
from app.domain.fields import FieldSpec
from app.errors import InvalidSchemaChange
from app.insights import dashboard as dashboard_module
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


class RenameOperation(BaseModel):
    from_key: str = Field(alias="from")
    to_key: str = Field(alias="to")
    label: str | None = Field(
        default=None, description="New display label. Defaults to keeping the current one."
    )

    model_config = {"populate_by_name": True}


class MergeOperation(BaseModel):
    from_key: str = Field(alias="from", description="The field to absorb. It disappears.")
    into_key: str = Field(alias="into", description="The field that survives.")

    model_config = {"populate_by_name": True}


class UpdateSchemaRequest(BaseModel):
    """One operation per request. Requirement FR-15.

    Deliberately not "here is the whole new field list". A whole-list edit makes every
    change look the same to the server, which then has to infer what the user meant by
    diffing, and a rename is indistinguishable from a delete plus an add. That matters
    because a merge has to MOVE values and a rename must not, so the distinction cannot be
    left to inference.
    """

    rename: RenameOperation | None = None
    merge: MergeOperation | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if bool(self.rename) == bool(self.merge):
            raise ValueError("Provide exactly one of 'rename' or 'merge'.")
        return self


@router.patch("/schema", response_model=SchemaResponse, summary="Rename or merge a field")
async def update_schema(
    workspace: CurrentWorkspace, session: Session, body: UpdateSchemaRequest
) -> SchemaResponse:
    if body.rename is not None:
        row = await versioning.rename_field(
            session,
            workspace.id,
            from_key=body.rename.from_key,
            to_key=body.rename.to_key,
            new_label=body.rename.label,
        )
    elif body.merge is not None:
        row = await versioning.merge_fields(
            session,
            workspace.id,
            from_key=body.merge.from_key,
            into_key=body.merge.into_key,
        )
    else:  # pragma: no cover - the validator guarantees one of the two
        raise InvalidSchemaChange("Provide exactly one of 'rename' or 'merge'.")

    # A merge moves values between columns and a rename changes what a panel is titled,
    # so either can make the dashboard wrong rather than merely dated.
    await dashboard_module.mark_stale(session, workspace.id, reason="schema edited")
    logger.info("schema.updated_by_user", workspace_id=str(workspace.id), version=row.version)
    return SchemaResponse(
        version=row.version, fields=[FieldSpec.model_validate(f) for f in row.fields]
    )
