"""The per-workspace view, exercised against a real Postgres.

Two things can only be verified here rather than by inspecting the generated string: that
the statement Postgres accepts is the one we think we are writing, and that the read-only
role can actually read the result. The second is review finding 8.2, whose symptom is a
permission error on the user's first question after any schema change.
"""

from __future__ import annotations

import uuid

import pytest
from app.config import Settings, get_settings
from app.db.models import Document, FieldValueRow, Record, SchemaVersion, Workspace
from app.domain.document import DocumentStatus, SourceFormat
from app.domain.fields import FieldSpec, FieldType, Tier, ValueStatus
from app.schema import view as view_module
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

FIELDS = [
    FieldSpec(key="vendor_name", label="Vendor", type=FieldType.STRING),
    FieldSpec(
        key="total_due", label="Total Due", type=FieldType.CURRENCY, currency_default="USD"
    ),
    FieldSpec(key="issue_date", label="Issue Date", type=FieldType.DATE),
    FieldSpec(key="paid", label="Paid", type=FieldType.BOOLEAN),
    FieldSpec(key="line_items", label="Line Items", type=FieldType.STRING_LIST),
    FieldSpec(key="quantity", label="Quantity", type=FieldType.NUMBER),
]


async def _seed(db: AsyncSession, values: dict[str, object]) -> tuple[Workspace, Record]:
    workspace = Workspace(token_hash=uuid.uuid4().hex * 2)
    db.add(workspace)
    await db.flush()

    version = SchemaVersion(
        workspace_id=workspace.id,
        version=1,
        fields=[field.model_dump(mode="json") for field in FIELDS],
    )
    document = Document(
        workspace_id=workspace.id,
        filename="invoice.pdf",
        mime="application/pdf",
        source_format=SourceFormat.PDF,
        size_bytes=1234,
        content_hash="a" * 64,
        storage_key="k",
        status=DocumentStatus.DONE,
    )
    db.add_all([version, document])
    await db.flush()

    record = Record(
        workspace_id=workspace.id,
        document_id=document.id,
        schema_version_id=version.id,
    )
    db.add(record)
    await db.flush()

    for key, value in values.items():
        field = next(f for f in FIELDS if f.key == key)
        db.add(
            FieldValueRow(
                record_id=record.id,
                field_key=key,
                value=value,
                value_type=field.type,
                tier=Tier.HIGH,
                status=ValueStatus.MODEL,
            )
        )
    await db.flush()
    return workspace, record


async def test_the_view_is_created_and_returns_one_row_per_record(
    db: AsyncSession, settings: Settings
) -> None:
    workspace, record = await _seed(
        db,
        {
            "vendor_name": "Northwind Traders",
            "total_due": {"amount": 12480.5, "currency": "USD"},
            "issue_date": "2026-03-14",
            "paid": True,
            "line_items": ["subscription", "support"],
            "quantity": 3,
        },
    )
    await view_module.regenerate(db, workspace.id, FIELDS, settings)

    name = view_module.view_name(workspace.id)
    rows = (await db.execute(text(f'SELECT * FROM "{name}"'))).mappings().all()

    assert len(rows) == 1
    row = rows[0]
    assert row["record_id"] == record.id
    assert row["document_name"] == "invoice.pdf"
    assert row["vendor_name"] == "Northwind Traders"
    assert float(row["total_due"]) == pytest.approx(12480.5)
    assert row["total_due_currency"] == "USD"
    assert row["issue_date"].isoformat() == "2026-03-14"
    assert row["paid"] is True
    assert row["line_items"] == "subscription, support"
    assert float(row["quantity"]) == pytest.approx(3.0)


async def test_every_column_arrives_with_the_sql_type_the_prompt_promises(
    db: AsyncSession, settings: Settings
) -> None:
    """The natural-language-to-SQL prompt is given ``describe_columns``. If the real view
    disagrees with it, the model writes SQL against a table that does not exist."""
    workspace, _record = await _seed(db, {"vendor_name": "Acme"})
    await view_module.regenerate(db, workspace.id, FIELDS, settings)

    name = view_module.view_name(workspace.id)
    actual = {
        row["column_name"]: row["data_type"]
        for row in (
            await db.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = :name"
                ),
                {"name": name},
            )
        )
        .mappings()
        .all()
    }
    expected_sql_type = {
        "text": {"text", "character varying"},
        "numeric": {"numeric"},
        "date": {"date"},
        "boolean": {"boolean"},
        "uuid": {"uuid"},
        "timestamptz": {"timestamp with time zone"},
    }
    for column, promised in view_module.describe_columns(FIELDS):
        assert column in actual, f"{column} is promised to the model but not in the view"
        assert actual[column] in expected_sql_type[promised], (
            f"{column} is {actual[column]} but the model is told {promised}"
        )


async def test_the_readonly_role_can_read_the_view_immediately_after_a_schema_change(
    db: AsyncSession, settings: Settings
) -> None:
    """Review finding 8.2. Without the grant in the same transaction, the first query
    after any schema change fails with a permission error."""
    workspace, _record = await _seed(db, {"vendor_name": "Acme"})
    await view_module.regenerate(db, workspace.id, FIELDS, settings)

    name = view_module.view_name(workspace.id)
    role = view_module.readonly_role(settings)
    granted = (
        await db.execute(
            text(
                "SELECT has_table_privilege(:role, :name, 'SELECT') AS ok"
            ),
            {"role": role, "name": name},
        )
    ).scalar_one()
    assert granted is True, f"{role} cannot read {name}"


async def test_the_readonly_role_still_cannot_reach_the_tables_underneath(
    db: AsyncSession, settings: Settings
) -> None:
    """Decision D10's core claim. The view is reachable; ``field_values`` is not."""
    workspace, _record = await _seed(db, {"vendor_name": "Acme"})
    await view_module.regenerate(db, workspace.id, FIELDS, settings)

    role = view_module.readonly_role(settings)
    for table in ("field_values", "records", "documents", "workspaces"):
        allowed = (
            await db.execute(
                text("SELECT has_table_privilege(:role, :table, 'SELECT') AS ok"),
                {"role": role, "table": table},
            )
        ).scalar_one()
        assert allowed is False, f"{role} must not be able to read {table}"


async def test_a_value_left_over_from_a_previous_type_reads_as_null_not_an_error(
    db: AsyncSession, settings: Settings
) -> None:
    """The schema is the user's to change, so a field that was a string yesterday can be a
    number today while old rows hold the old shape. Unguarded casts would make one stale
    row raise for the entire view, taking every query down."""
    workspace, _record = await _seed(db, {"vendor_name": "Acme"})

    # A string sitting in a field the schema now calls a number, a date, and a currency.
    stale = [("quantity", FieldType.NUMBER), ("issue_date", FieldType.DATE)]
    for key, field_type in stale:
        db.add(
            FieldValueRow(
                record_id=_record_id(await _only_record(db, workspace.id)),
                field_key=key,
                value="not a number at all",
                value_type=field_type,
                tier=Tier.LOW,
                status=ValueStatus.MODEL,
            )
        )
    await db.flush()
    await view_module.regenerate(db, workspace.id, FIELDS, settings)

    name = view_module.view_name(workspace.id)
    rows = (await db.execute(text(f'SELECT * FROM "{name}"'))).mappings().all()
    assert len(rows) == 1
    assert rows[0]["quantity"] is None
    assert rows[0]["issue_date"] is None
    assert rows[0]["vendor_name"] == "Acme", "the good columns still work"


async def _only_record(db: AsyncSession, workspace_id: uuid.UUID) -> Record:
    from sqlalchemy import select

    return (
        await db.execute(select(Record).where(Record.workspace_id == workspace_id))
    ).scalar_one()


def _record_id(record: Record) -> uuid.UUID:
    return record.id


async def test_regenerating_after_a_rename_succeeds(
    db: AsyncSession, settings: Settings
) -> None:
    """DROP then CREATE rather than CREATE OR REPLACE. Replace refuses to change a view's
    column names, so it would work until the first rename and then start failing."""
    workspace, _record = await _seed(db, {"vendor_name": "Acme"})
    await view_module.regenerate(db, workspace.id, FIELDS, settings)

    renamed = [
        FieldSpec(key="supplier_name", label="Supplier", type=FieldType.STRING),
        *FIELDS[1:],
    ]
    await view_module.regenerate(db, workspace.id, renamed, settings)

    name = view_module.view_name(workspace.id)
    columns = {
        row[0]
        for row in (
            await db.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :n"),
                {"n": name},
            )
        ).all()
    }
    assert "supplier_name" in columns
    assert "vendor_name" not in columns


async def test_two_workspaces_do_not_see_each_other(
    db: AsyncSession, settings: Settings
) -> None:
    """The workspace filter is baked into the view definition, so isolation does not depend
    on every generated query remembering a WHERE clause."""
    first, _ = await _seed(db, {"vendor_name": "First Co"})
    second, _ = await _seed(db, {"vendor_name": "Second Co"})
    await view_module.regenerate(db, first.id, FIELDS, settings)
    await view_module.regenerate(db, second.id, FIELDS, settings)

    for workspace, expected in ((first, "First Co"), (second, "Second Co")):
        name = view_module.view_name(workspace.id)
        rows = (await db.execute(text(f'SELECT vendor_name FROM "{name}"'))).all()
        assert [row[0] for row in rows] == [expected]


def test_the_view_name_fits_postgres_identifier_limits() -> None:
    name = view_module.view_name(uuid.uuid4())
    assert len(name) < 63
    assert name.replace("_", "").isalnum()


def test_a_malicious_field_key_never_reaches_sql() -> None:
    """Review finding 8.1, at the last line of defence rather than the first."""
    from app.domain.fields import InvalidFieldKey

    for key in ('x"; DROP TABLE field_values --', "record_id", "Vendor Name", ""):
        with pytest.raises((InvalidFieldKey, ValueError)):
            view_module.build_view_sql(
                uuid.uuid4(),
                [FieldSpec.model_construct(key=key, label="x", type=FieldType.STRING)],
            )


def test_settings_fixture_role_matches_the_connection_it_will_use() -> None:
    settings = get_settings()
    assert view_module.readonly_role(settings) in str(settings.database_url_readonly)
