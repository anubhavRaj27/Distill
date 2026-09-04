"""Reading and applying schema versions.

Every schema change goes through ``apply``, whether the system made it or the user did, so
one code path owns validation, persistence, and the announcement.

WHAT V2 REMOVED FROM THIS MODULE
---------------------------------
* **The per-workspace SQL view.** v1 regenerated a pivoted, typed view on every schema
  change so that generated SQL had a flat table to read. Decision D35 removed the
  natural-language-to-SQL feature, and query specifications are now evaluated in Python over
  ``field_values`` directly (``app/insights/evaluate.py``), so the view had no reader left.
* **Revert.** v1 offered one-click revert because the system was asking the user to make
  schema decisions and those decisions needed undoing. v2 asks nothing (decision D38), so
  there is nothing to reverse. ``schema_versions`` rows are still written and still
  immutable, because they remain the store of the current schema and a genuine audit trail
  in the database; they are simply no longer surfaced as a history view.

What stayed is the part that carries weight: versions are append-only, each records who
applied it and a human-readable summary, and applying one publishes
``schema.updated``. With no confirmation step, that summary is the entire explanation a user
ever gets for a change they did not initiate, which is why ``apply`` refuses to accept an
empty one.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SchemaVersion
from app.domain.events import SchemaUpdatedEvent
from app.domain.fields import FieldSpec, SchemaChangeAuthor, WorkspaceSchema
from app.errors import InvalidSchemaChange
from app.events.bus import bus
from app.logging import get_logger

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

    before = {field.key for field in (
        [FieldSpec.model_validate(f) for f in previous.fields] if previous else []
    )}
    after = {field.key for field in validated.fields}
    await bus.publish(
        session,
        workspace_id,
        SchemaUpdatedEvent(
            seq=0,
            version=next_number,
            summary=summary,
            added_field_keys=sorted(after - before),
            removed_field_keys=sorted(before - after),
            applied_by=author,
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


async def rename_field(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    from_key: str,
    to_key: str,
    new_label: str | None = None,
) -> SchemaVersion:
    """Rename a field. Requirement FR-15.

    The field's ``source_keys`` gain the old key, so a later document that still uses the
    original wording matches by alias and is not treated as a new field.

    Values are NOT rewritten. ``field_values.field_key`` keeps the old key and the schema's
    ``source_keys`` carries the mapping, which is deliberate: rewriting a column of values
    to chase a label change would touch every row, including human-verified ones, for a
    change that is purely presentational.
    """
    fields = await current_fields(session, workspace_id)
    by_key = {field.key: field for field in fields}
    if from_key not in by_key:
        raise InvalidSchemaChange(f"{from_key!r} is not a field in this workspace.")
    if to_key != from_key and to_key in by_key:
        raise InvalidSchemaChange(f"{to_key!r} is already a field in this workspace.")

    updated: list[FieldSpec] = []
    for field in fields:
        if field.key != from_key:
            updated.append(field)
            continue
        aliases = list(field.source_keys)
        if from_key not in aliases:
            aliases.append(from_key)
        updated.append(
            field.model_copy(
                update={
                    "key": to_key,
                    "label": new_label or field.label,
                    "source_keys": aliases,
                }
            )
        )

    label = new_label or by_key[from_key].label
    return await apply(
        session,
        workspace_id,
        updated,
        author=SchemaChangeAuthor.USER,
        summary=f"You renamed {by_key[from_key].label!r} to {label!r}.",
    )


async def merge_fields(
    session: AsyncSession, workspace_id: UUID, *, from_key: str, into_key: str
) -> SchemaVersion:
    """Merge one field into another, moving values and provenance. Requirement FR-15.

    This is the resolution path for every uncertain split decision D38 produces, which is
    what makes "when unsure, keep them apart" an acceptable default rather than a way of
    dumping work on the user: the undo is one action and it loses nothing.

    Values move by rewriting ``field_values.field_key``, which carries the provenance,
    confidence, tier, and human-verified status with them untouched. Where BOTH fields have
    a value for the same record, the target's value wins unless it is model-owned and the
    source's is human-verified, because a human's answer outranks a model's regardless of
    which column it happens to sit in.
    """

    from app.db.models import FieldValueRow, Record
    from app.domain.fields import ValueStatus

    fields = await current_fields(session, workspace_id)
    by_key = {field.key: field for field in fields}
    if from_key not in by_key or into_key not in by_key:
        raise InvalidSchemaChange("Both fields must exist in order to merge them.")
    if from_key == into_key:
        raise InvalidSchemaChange("A field cannot be merged into itself.")

    source, target = by_key[from_key], by_key[into_key]
    if source.type is not target.type:
        raise InvalidSchemaChange(
            f"{source.label!r} holds {source.type.value} values and {target.label!r} holds "
            f"{target.type.value}, so merging them would change what the values mean.",
            from_type=source.type.value,
            into_type=target.type.value,
        )

    record_ids = (
        (await session.execute(select(Record.id).where(Record.workspace_id == workspace_id)))
        .scalars()
        .all()
    )

    rows = list(
        (
            await session.execute(
                select(FieldValueRow).where(
                    FieldValueRow.record_id.in_(record_ids),
                    FieldValueRow.field_key.in_([from_key, into_key]),
                )
            )
        )
        .scalars()
        .all()
    )
    by_record: dict[UUID, dict[str, FieldValueRow]] = {}
    for row in rows:
        by_record.setdefault(row.record_id, {})[row.field_key] = row

    moved = 0
    for values in by_record.values():
        incoming = values.get(from_key)
        if incoming is None:
            continue
        existing = values.get(into_key)

        if existing is None:
            incoming.field_key = into_key
            moved += 1
            continue

        target_is_human = existing.status in (
            ValueStatus.HUMAN_VERIFIED,
            ValueStatus.NOT_PRESENT,
        )
        source_is_human = incoming.status in (
            ValueStatus.HUMAN_VERIFIED,
            ValueStatus.NOT_PRESENT,
        )
        if source_is_human and not target_is_human:
            # A human's answer outranks a model's, whichever column it sat in.
            await session.delete(existing)
            await session.flush()
            incoming.field_key = into_key
            moved += 1
        else:
            await session.delete(incoming)

    await session.flush()

    remaining = [field for field in fields if field.key != from_key]
    merged_target = next(field for field in remaining if field.key == into_key)
    aliases = list(merged_target.source_keys)
    for alias in [source.key, *source.source_keys]:
        if alias not in aliases:
            aliases.append(alias)
    remaining = [
        merged_target.model_copy(update={"source_keys": aliases})
        if field.key == into_key
        else field
        for field in remaining
    ]

    logger.info(
        "schema.merged", workspace_id=str(workspace_id), source=from_key, into=into_key, moved=moved
    )
    return await apply(
        session,
        workspace_id,
        remaining,
        author=SchemaChangeAuthor.USER,
        summary=f"You merged {source.label!r} into {target.label!r}, moving {moved} values.",
    )
