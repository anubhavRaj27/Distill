"""The user's field schema: what a field is, what a value is, and how confident we are.

The three enumerations here (``FieldType``, ``Tier``, ``ValueStatus``) are the shared
vocabulary between the extraction pipeline, the database, the interface, and the tests. They
are defined once, here, and every other module imports them.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, Field, model_validator

from app.domain.provenance import Provenance

# ---------------------------------------------------------------------------
# Field keys
# ---------------------------------------------------------------------------

# A field key becomes a COLUMN NAME in a generated per-workspace view, and field keys
# originate from a Large Language Model proposal. A key containing a quotation mark or a
# semicolon would therefore be a data definition language injection executed with the
# application role's privileges. See review finding 8.1 in docs/backend-plan.md.
#
# Keys are validated here, at the domain boundary, so that no code path can construct an
# invalid one. The view generator validates again and additionally quotes through the
# dialect, because two independent checks on an injection vector is the right number.
#
# Length 47 keeps "ws_" + 32 hex characters + "_" + key well inside Postgres's 63 byte
# identifier limit even in the longest generated name.
FIELD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,46}$")

# Names the generated view already uses for its own columns. A field may not shadow them,
# because the pivot would produce two columns of the same name.
RESERVED_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "record_id",
        "document_id",
        "document_name",
        "created_at",
        "updated_at",
        # SQL keywords that are legal when quoted but confuse a model writing queries
        # against this view, which is the one reader we cannot debug.
        "select",
        "from",
        "where",
        "group",
        "order",
        "table",
        "user",
        "default",
        "null",
        "true",
        "false",
    }
)


class InvalidFieldKey(ValueError):
    """A proposed field key is not usable as a column name."""


def validate_field_key(key: str) -> str:
    """Return ``key`` if it is a legal field key, else raise ``InvalidFieldKey``.

    Deliberately strict. A rejected key is a proposal the user is asked to rename, which is
    a small annoyance. An accepted bad key is a security hole.
    """
    if not FIELD_KEY_PATTERN.match(key):
        raise InvalidFieldKey(
            f"{key!r} is not a valid field key. A key must start with a lowercase letter "
            f"and contain only lowercase letters, digits, and underscores, up to 47 "
            f"characters."
        )
    if key in RESERVED_FIELD_KEYS:
        raise InvalidFieldKey(f"{key!r} is reserved and cannot be used as a field key.")
    return key


# ---------------------------------------------------------------------------
# Types, tiers, statuses
# ---------------------------------------------------------------------------


class FieldType(StrEnum):
    """The supported field types. Requirement FR-12.

    The stored representation of each is documented in ``app.domain.values``, which is the
    only module that converts between a raw model output and one of these.
    """

    STRING = "string"
    NUMBER = "number"
    CURRENCY = "currency"  # {"amount": float, "currency": "ISO 4217 code"}
    DATE = "date"  # ISO 8601 date string, "YYYY-MM-DD"
    BOOLEAN = "boolean"
    ENUM = "enum"  # one of FieldSpec.enum_values
    STRING_LIST = "string_list"


class Tier(StrEnum):
    """How much a value should be trusted. Always DERIVED, never asked of the model.

    See decision D5 and the table in implementation.md section 6.4. The derivation lives in
    ``app.pipeline.score`` and nowhere else.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    CONFLICT = "conflict"  # two runs disagree, or the model disagrees with a human
    VERIFIED = "verified"  # a human edited or accepted this


class ValueStatus(StrEnum):
    """Where a value came from. Drives the never-lose-a-correction guarantee.

    Every write path a model can reach filters on ``status <> 'human_verified'``. This is
    enforced in SQL rather than by convention, which is what makes principle 4 of
    requirements.md a guarantee instead of an intention.
    """

    MODEL = "model"
    HUMAN_VERIFIED = "human_verified"
    NOT_PRESENT = "not_present"  # a human asserted this field is absent from this document


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class FieldSpec(BaseModel):
    """One field in a workspace's schema, as the user has agreed to it."""

    key: str = Field(description="Column name in the generated view. Machine identifier.")
    label: str = Field(description="What the interface shows a person.")
    type: FieldType
    description: str = Field(
        default="",
        description="What this field means. Sent to the model during schema-guided "
        "extraction, and used for similarity matching during drift detection.",
    )
    enum_values: list[str] | None = Field(
        default=None, description="Permitted values, for FieldType.ENUM only."
    )
    currency_default: str | None = Field(
        default=None,
        description="ISO 4217 code assumed when a document states an amount with no "
        "currency marker, for FieldType.CURRENCY only.",
    )
    source_keys: list[str] = Field(
        default_factory=list,
        description="The raw keys from open extraction that were unified into this field. "
        "Kept so the user can see WHY a field exists, and so drift detection knows which "
        "aliases have already been resolved.",
    )
    weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Review priority multiplier. The review queue orders by "
        "weight * (1 - confidence), so a wrong total matters more than a wrong note. "
        "Currency and date fields default higher, set in app.schema.propose.",
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        validate_field_key(self.key)
        if self.type is FieldType.ENUM and not self.enum_values:
            raise ValueError(f"field {self.key!r} is an enum but declares no enum_values")
        if self.type is not FieldType.ENUM and self.enum_values:
            raise ValueError(f"field {self.key!r} declares enum_values but is {self.type}")
        if self.type is not FieldType.CURRENCY and self.currency_default:
            raise ValueError(f"field {self.key!r} declares a currency default but is {self.type}")
        return self


class WorkspaceSchema(BaseModel):
    """A complete, versioned field schema."""

    version: int = Field(ge=1)
    fields: list[FieldSpec]

    @model_validator(mode="after")
    def _unique_keys(self) -> Self:
        keys = [f.key for f in self.fields]
        duplicates = {k for k in keys if keys.count(k) > 1}
        if duplicates:
            raise ValueError(f"duplicate field keys in schema: {sorted(duplicates)}")
        return self

    def by_key(self, key: str) -> FieldSpec | None:
        return next((f for f in self.fields if f.key == key), None)


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


class CurrencyAmount(BaseModel):
    """A monetary value. Never a bare number, because the code is part of the value.

    Requirement FR-21 formats currency with its code, and a cross-document query like
    "total spend by vendor" is meaningless if two documents used different currencies and
    the codes were dropped at extraction time.
    """

    model_config = {"frozen": True}

    amount: float
    currency: str = Field(min_length=3, max_length=3, description="ISO 4217 code, uppercase.")


class FieldValue(BaseModel):
    """One extracted or corrected value, with everything needed to trust it."""

    field_key: str
    value: Any | None = Field(
        default=None,
        description="The value, in the stored representation for its type. Null means the "
        "field is genuinely absent from this document, not that extraction failed.",
    )
    value_type: FieldType
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="The model's self-report. Never the tier."
    )
    tier: Tier
    status: ValueStatus = ValueStatus.MODEL
    provenance: Provenance | None = None

    # Decision D16: when re-extraction disagrees with a human-verified value, the human
    # value stays in `value` and the model's answer is retained here, so the interface can
    # show both candidates and let the user decide. A boolean flag alone would tell the
    # user a disagreement exists without telling them what it is, which is unactionable.
    model_value: Any | None = None
    model_value_at: datetime | None = None

    @property
    def is_human_owned(self) -> bool:
        """Whether a model is forbidden from overwriting this value."""
        return self.status in (ValueStatus.HUMAN_VERIFIED, ValueStatus.NOT_PRESENT)
