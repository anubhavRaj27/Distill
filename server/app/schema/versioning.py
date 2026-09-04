"""Reading, applying, and reverting schema versions.

Every schema change goes through ``apply``, automatic or user-decided alike, which is what
makes decision D23's confidence-gated auto-apply defensible: the audit trail and the revert
path cover 100% of changes rather than only the ones a human confirmed. Reversibility, not
a confirmation click, is the trust mechanism in the auto-apply zones.

Three invariants this module maintains:

* **Versions are immutable.** Nothing edits a ``schema_versions`` row. A change writes a new
  one with ``parent_id`` pointing at what it came from, so history is a read rather than a
  reconstruction (requirement FR-15).
* **A revert is a new version, not a deletion.** Reverting to version 2 from version 5
  writes version 6 carrying version 2's fields. The trail of what happened stays intact,
  including the mistake, which is the point of an audit trail.
* **The view is regenerated in the same transaction as the version row.** A committed
  version whose view still has the old columns would make every subsequent query wrong in a
  way nothing would flag.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import SchemaVersion
from app.domain.events import SchemaVersionEvent
from app.domain.fields import FieldSpec, SchemaChangeAuthor, WorkspaceSchema
from app.errors import InvalidSchemaChange
from app.events.bus import bus
from app.logging import get_logger
from app.schema import view as view_module

logger = get_logger(__name__)


async def current_version(session: AsyncSession, workspace_id: UUID) -> SchemaVersion | None:
    """The newest schema version row, or ``None`` if the workspace has no schema yet."""
    return (
        await session.execute(
            select(SchemaVersion)
            .where(SchemaVersion.workspace_id == workspace_id)
            .order_by(SchemaVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def current_schema(session: AsyncSession, workspace_id: UUID) -> WorkspaceSchema | None:
    row = await current_version(session, workspace_id)
    if row is None:
        return None
    return WorkspaceSchema(
        version=row.version,
        fields=[FieldSpec.model_validate(field) for field in row.fields],
    )


async def current_fields(session: AsyncSession, workspace_id: UUID) -> list[FieldSpec]:
    """The current fields, or an empty list. Convenience for the many callers who want it."""
    schema = await current_schema(session, workspace_id)
    return list(schema.fields) if schema else []


async def history(session: AsyncSession, workspace_id: UUID) -> list[SchemaVersion]:
    """Every version, newest first. Requirement FR-15."""
    return list(
        (
            await session.execute(
                select(SchemaVersion)
                .where(SchemaVersion.workspace_id == workspace_id)
                .order_by(SchemaVersion.version.desc())
            )
        )
        .scalars()
        .all()
    )


async def apply(
    session: AsyncSession,
    workspace_id: UUID,
    fields: list[FieldSpec],
    *,
    author: SchemaChangeAuthor,
    summary: str,
    settings: Settings,
) -> SchemaVersion:
    """Write a new schema version, regenerate the view, and publish the event.

    ``author`` distinguishes "the system changed your schema without asking" from "you
    changed it", which the history view renders and decision D23's whole design rests on.
    ``summary`` is user-facing prose explaining the change, and for an automatic change it
    is the only explanation the user will ever get, so it is not optional.
    """
    if not fields:
        raise InvalidSchemaChange(
            "A schema needs at least one field. Removing every field would leave a table "
            "with nothing in it."
        )

    keys = [field.key for field in fields]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise InvalidSchemaChange(
            f"Two fields cannot share the same name: {', '.join(duplicates)}.",
            duplicate_keys=duplicates,
        )

    # Validated by constructing the model, which runs every FieldSpec invariant including
    # the field-key guard from review finding 8.1.
    previous = await current_version(session, workspace_id)
    next_number = (previous.version + 1) if previous else 1
    validated = WorkspaceSchema(version=next_number, fields=fields)

    row = SchemaVersion(
        workspace_id=workspace_id,
        version=next_number,
        fields=[field.model_dump(mode="json") for field in validated.fields],
        created_by=author,
        change_summary=summary,
        parent_id=previous.id if previous else None,
    )
    session.add(row)
    await session.flush()

    await view_module.regenerate(session, workspace_id, list(validated.fields), settings)

    before = {field.key for field in (
        [FieldSpec.model_validate(f) for f in previous.fields] if previous else []
    )}
    after = {field.key for field in validated.fields}
    await bus.publish(
        session,
        workspace_id,
        SchemaVersionEvent(
            seq=0,
            version=next_number,
            added_field_keys=sorted(after - before),
            removed_field_keys=sorted(before - after),
            applied_by=author,
            change_summary=summary,
        ),
    )

    logger.info(
        "schema.applied",
        workspace_id=str(workspace_id),
        version=next_number,
        author=author.value,
        added=sorted(after - before),
        removed=sorted(before - after),
    )
    return row


async def revert(
    session: AsyncSession, workspace_id: UUID, to_version: int, *, settings: Settings
) -> SchemaVersion:
    """Revert to ``to_version`` by applying its fields as a NEW version.

    Never rewinds by deleting rows. Version 2 restored from version 5 becomes version 6, so
    the history keeps the mistake and the correction, which is what an audit trail is for.
    """
    target = (
        await session.execute(
            select(SchemaVersion).where(
                SchemaVersion.workspace_id == workspace_id,
                SchemaVersion.version == to_version,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise InvalidSchemaChange(
            f"There is no schema version {to_version} in this workspace.",
            requested_version=to_version,
        )

    latest = await current_version(session, workspace_id)
    if latest is not None and latest.version == to_version:
        raise InvalidSchemaChange(
            f"Version {to_version} is already the current schema, so there is nothing to "
            f"revert."
        )

    return await apply(
        session,
        workspace_id,
        [FieldSpec.model_validate(field) for field in target.fields],
        author=SchemaChangeAuthor.USER,
        summary=f"Reverted to version {to_version}.",
        settings=settings,
    )
