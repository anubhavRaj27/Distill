"""Generating the per-workspace typed view that natural-language queries read.

Decision D4 stores field values tall (one row per record and field) in JSONB, which makes
schema changes cheap and human corrections first class. The cost is that the shape a model
needs to write SQL against, a flat table with typed columns, does not exist. This module
manufactures it as a view, regenerated whenever the schema version changes.

The view is also the **only** relation the read-only role can reach, which is what makes
decision D10's layered defence real: a Postgres view's access to its underlying tables is
checked against the view OWNER, not the caller, so ``distill_readonly`` can read this view
while holding no privilege at all on ``field_values``.

THREE THINGS HERE ARE SECURITY OR CORRECTNESS CRITICAL
-------------------------------------------------------
**Field keys are validated and quoted (review finding 8.1).** A field key becomes a column
name, and field keys originate from a Large Language Model proposal. Every key passes
``validate_field_key`` again here, even though the schema layer already validated it on the
way in, and is then quoted through the dialect. Two independent checks on an injection
vector is the right number.

**The grant happens in the same transaction as the create (review finding 8.2).** A newly
created view is owned by the application role and the read-only role has no privilege on it,
so without this the very first query after any schema change fails with a permission error
rather than returning rows.

**Casts are guarded by ``jsonb_typeof``, not applied blindly.** The schema is the user's to
change, so a field that was a string yesterday can be a number today while old rows still
hold the old shape. An unguarded ``::numeric`` would make the whole view raise on a single
stale row, taking every query down. Guarded, a wrong-shaped value reads as NULL, which is
both survivable and honest.
"""

from __future__ import annotations

from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.fields import FieldSpec, FieldType, validate_field_key
from app.logging import get_logger

logger = get_logger(__name__)

VIEW_PREFIX = "ws_"
VIEW_SUFFIX = "_records"

# Columns the view always has, independent of the schema. Field keys may not shadow these,
# which ``RESERVED_FIELD_KEYS`` in the domain layer enforces.
BASE_COLUMNS: tuple[str, ...] = ("record_id", "document_id", "document_name", "created_at")

CURRENCY_CODE_SUFFIX = "_currency"
"""A currency field becomes two columns: the amount under the field's own key, and its ISO
code under this suffix. Splitting them is what lets a model write ``SUM(total_due)`` while
keeping the code available, since summing across currencies is meaningless without it."""


def view_name(workspace_id: UUID) -> str:
    """The view name for a workspace.

    Hex rather than the hyphenated form, so the name needs no quoting to be valid, and the
    result is 43 characters, comfortably inside Postgres's 63 byte identifier limit.
    """
    return f"{VIEW_PREFIX}{workspace_id.hex}{VIEW_SUFFIX}"


def quote_identifier(name: str) -> str:
    """Quote an SQL identifier. Belt to ``validate_field_key``'s braces."""
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def readonly_role(settings: Settings) -> str:
    """The role generated SQL executes as, taken from its own connection string.

    Parsed rather than configured separately, so the role that is granted access and the
    role that connects cannot drift apart.
    """
    parsed = urlparse(str(settings.database_url_readonly).replace("+asyncpg", ""))
    role = parsed.username or "distill_readonly"
    # A role name reaches SQL as an identifier, and this one comes from configuration
    # rather than from a literal, so it is checked rather than trusted.
    if not role.replace("_", "").isalnum():
        raise ValueError(f"refusing to use {role!r} as a role name: unexpected characters")
    return role


def _column_expression(field: FieldSpec) -> list[tuple[str, str]]:
    """SQL expressions for one field. Returns ``(column_name, expression)`` pairs.

    Every expression wraps a ``CASE WHEN`` in an aggregate, which is the pivot: one row per
    record comes out of a ``GROUP BY`` over the tall value rows. The aggregate is ``MAX``
    for every type except boolean, where it is ``bool_or``, because Postgres has no
    ``max(boolean)``. Either is safe here because the unique constraint on
    ``(record_id, field_key)`` means at most one non-null value feeds each cell, so the
    aggregate is only ever choosing between one value and nulls.
    """
    key = validate_field_key(field.key)
    literal = key.replace("'", "''")
    guard = f"fv.field_key = '{literal}'"
    # `value #>> '{}'` extracts a JSONB scalar as text, which is the form every cast below
    # starts from.
    as_text = "fv.value #>> '{}'"

    match field.type:
        case FieldType.STRING | FieldType.ENUM:
            return [(key, f"MAX(CASE WHEN {guard} THEN {as_text} END)")]

        case FieldType.NUMBER:
            return [
                (
                    key,
                    f"MAX(CASE WHEN {guard} AND jsonb_typeof(fv.value) = 'number' "
                    f"THEN (fv.value)::text::numeric END)",
                )
            ]

        case FieldType.CURRENCY:
            return [
                (
                    key,
                    f"MAX(CASE WHEN {guard} AND jsonb_typeof(fv.value) = 'object' "
                    f"THEN (fv.value ->> 'amount')::numeric END)",
                ),
                (
                    f"{key}{CURRENCY_CODE_SUFFIX}",
                    f"MAX(CASE WHEN {guard} AND jsonb_typeof(fv.value) = 'object' "
                    f"THEN (fv.value ->> 'currency') END)",
                ),
            ]

        case FieldType.DATE:
            # The regular expression guard is not decoration: a stale string value from
            # before a type change would make an unguarded ::date raise for the whole view.
            return [
                (
                    key,
                    f"MAX(CASE WHEN {guard} AND jsonb_typeof(fv.value) = 'string' "
                    f"AND ({as_text}) ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$' "
                    f"THEN ({as_text})::date END)",
                )
            ]

        case FieldType.BOOLEAN:
            # bool_or, not MAX. Postgres has no max(boolean) — the aggregate simply does
            # not exist, so a boolean field made the whole view fail to create. bool_or
            # ignores nulls exactly as MAX does, so with at most one non-null value per
            # cell it returns that value, which is the same pivot semantics.
            return [
                (
                    key,
                    f"bool_or(CASE WHEN {guard} AND jsonb_typeof(fv.value) = 'boolean' "
                    f"THEN (fv.value)::text::boolean END)",
                )
            ]

        case FieldType.STRING_LIST:
            # Flattened to a comma-separated string rather than exposed as an array,
            # because a model writing SQL handles text far more reliably than it handles
            # Postgres array syntax, and the interface renders the chips from the record
            # payload anyway.
            return [
                (
                    key,

                    # built string. Every interpolation here is either a validated field key
                    # (`validate_field_key`, review finding 8.1) or a literal from this
                    # module. This is dynamic data definition language, which cannot be
                    # parameterised; the defence is validation plus quoting, not binding.
                    f"MAX(CASE WHEN {guard} AND jsonb_typeof(fv.value) = 'array' "  # noqa: S608
                    f"THEN (SELECT string_agg(element, ', ') "
                    f"FROM jsonb_array_elements_text(fv.value) AS element) END)",
                )
            ]


def build_view_sql(workspace_id: UUID, fields: list[FieldSpec]) -> str:
    """The ``CREATE VIEW`` statement for a workspace's current schema."""
    name = quote_identifier(view_name(workspace_id))

    selected: list[str] = [
        "r.id AS record_id",
        "r.document_id AS document_id",
        "d.filename AS document_name",
        "r.created_at AS created_at",
    ]

    seen: set[str] = set(BASE_COLUMNS)
    for field in fields:
        for column, expression in _column_expression(field):
            if column in seen:
                # Two fields cannot produce the same column. Reachable through the currency
                # suffix: a field literally named ``total_due_currency`` alongside a
                # currency field ``total_due``. Skipping the later one keeps the view
                # buildable; the schema layer is what should have refused the collision.
                logger.warning(
                    "view.column_collision", workspace_id=str(workspace_id), column=column
                )
                continue
            seen.add(column)
            selected.append(f"{expression} AS {quote_identifier(column)}")

    body = ",\n       ".join(selected)
    return (
        f"CREATE VIEW {name} AS\n"
        f"SELECT {body}\n"
        f"  FROM records r\n"
        f"  JOIN documents d ON d.id = r.document_id\n"
        f"  LEFT JOIN field_values fv ON fv.record_id = r.id\n"
        f" WHERE r.workspace_id = '{workspace_id}'::uuid\n"
        f" GROUP BY r.id, r.document_id, d.filename, r.created_at"
    )


def build_drop_sql(workspace_id: UUID) -> str:
    return f"DROP VIEW IF EXISTS {quote_identifier(view_name(workspace_id))}"


def build_grant_sql(workspace_id: UUID, role: str) -> str:
    return f"GRANT SELECT ON {quote_identifier(view_name(workspace_id))} TO {role}"


async def regenerate(
    session: AsyncSession, workspace_id: UUID, fields: list[FieldSpec], settings: Settings
) -> str:
    """Drop and recreate the workspace view, and grant it, in one transaction.

    DROP then CREATE rather than ``CREATE OR REPLACE``: replace refuses to change a view's
    column names, types, or order, which is exactly what a schema change does. Replace would
    work until the first rename and then start failing.

    The grant is part of the same transaction (review finding 8.2). Splitting them would
    leave a window, or a failure path, in which the view exists and the read-only role
    cannot see it, and the symptom would be a permission error on the user's next question.
    """
    role = readonly_role(settings)
    await session.execute(text(build_drop_sql(workspace_id)))
    await session.execute(text(build_view_sql(workspace_id, fields)))
    await session.execute(text(build_grant_sql(workspace_id, role)))
    name = view_name(workspace_id)
    logger.info(
        "view.regenerated",
        workspace_id=str(workspace_id),
        view=name,
        fields=len(fields),
        granted_to=role,
    )
    return name


def describe_columns(fields: list[FieldSpec]) -> list[tuple[str, str]]:
    """The view's columns and their SQL types, for the natural-language-to-SQL prompt.

    The model is shown this rather than being asked to infer it, so what it writes SQL
    against is exactly what exists.
    """
    described: list[tuple[str, str]] = [
        ("record_id", "uuid"),
        ("document_id", "uuid"),
        ("document_name", "text"),
        ("created_at", "timestamptz"),
    ]
    sql_types = {
        FieldType.STRING: "text",
        FieldType.ENUM: "text",
        FieldType.NUMBER: "numeric",
        FieldType.CURRENCY: "numeric",
        FieldType.DATE: "date",
        FieldType.BOOLEAN: "boolean",
        FieldType.STRING_LIST: "text",
    }
    for field in fields:
        described.append((field.key, sql_types[field.type]))
        if field.type is FieldType.CURRENCY:
            described.append((f"{field.key}{CURRENCY_CODE_SUFFIX}", "text"))
    return described
