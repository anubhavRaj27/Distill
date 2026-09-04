"""Every environment variable this server reads, declared once, with a type and a default.

There is deliberately no ``os.environ`` access anywhere else in the codebase. A setting that
is not declared here does not exist, which is what makes the deployment surface reviewable:
the list below IS the list of things an operator can configure.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, read from the environment and from a local ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Runtime ------------------------------------------------------------
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = Field(
        default=False,
        description="Structured JSON logs. Off in development for readability, on in "
        "production so lines are machine-parseable.",
    )
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        description="Vite's development server. In production the interface is served by "
        "this same process, so there is no cross-origin surface at all.",
    )

    # -- Database -----------------------------------------------------------
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://distill:distill@localhost:5432/distill"),
        description="Connection for the application role, which owns the schema.",
    )
    database_url_readonly: PostgresDsn = Field(
        default=PostgresDsn(
            "postgresql+asyncpg://distill_readonly:distill_readonly@localhost:5432/distill"
        ),
        description="Connection for generated SQL only. This role holds SELECT and nothing "
        "else, and can reach per-workspace views but not the tables beneath them. "
        "See decision D10 and scripts/bootstrap_db.sql.",
    )
    db_echo: bool = False
    db_pool_size: int = Field(default=10, ge=1)

    # -- Storage ------------------------------------------------------------
    storage_dir: Path = Field(
        default=Path("./var/storage"),
        description="Originals and rendered page images. A local volume in the container.",
    )
    max_upload_mb: int = Field(
        default=20,
        ge=1,
        description="Per-file limit. Requirement FR-03. Enforced by counting bytes while "
        "streaming, never by trusting the declared Content-Length.",
    )
    max_files_per_upload: int = Field(default=25, ge=1)

    # -- Large Language Model. See decision D13. ----------------------------
    llm_provider: Literal["gemini", "fake"] = Field(
        default="fake",
        description="Defaults to `fake` on purpose: a checkout with no API key must still "
        "boot, run its tests, and serve the interface. Set to `gemini` to make real calls.",
    )
    gemini_api_key: str | None = None
    llm_extract_model: str = Field(
        default="gemini-2.5-pro",
        description="Extraction and schema inference. The accuracy-critical calls, so the "
        "stronger tier. Model identifiers are configuration, not code, because the "
        "provider is not finalised. Unverified until a key exists.",
    )
    llm_query_model: str = Field(
        default="gemini-2.5-flash",
        description="Natural language to SQL. Short and tightly constrained, so the faster "
        "tier, because query latency is felt directly by the user.",
    )
    llm_embed_model: str = Field(
        default="gemini-embedding-001",
        description="Embedding model for schema drift matching (decision D24). "
        "Configuration rather than code, like the other model identifiers, and unverified "
        "until a key exists.",
    )
    llm_timeout_seconds: float = Field(default=90.0, gt=0)
    llm_max_attempts: int = Field(
        default=3, ge=1, description="Validation retries before a document is failed."
    )
    llm_fixture_dir: Path = Field(
        default=Path("./tests/fixtures/llm"),
        description="Where the fake provider reads recorded responses from, and where it "
        "writes new ones when recording against a real key.",
    )
    llm_record: bool = Field(
        default=False,
        description="With a real key present, capture every interaction to the fixture "
        "directory so the deterministic test suite can replay it.",
    )

    # -- Pipeline -----------------------------------------------------------
    worker_concurrency: int = Field(
        default=4, ge=1, description="Documents processed at once by the in-process queue."
    )
    page_render_dpi: int = Field(default=144, ge=72, le=400)
    tesseract_cmd: str | None = Field(
        default=None,
        description="Path to the tesseract binary. Left unset, pytesseract searches PATH. "
        "Set it when the binary is installed somewhere PATH does not reach, which is the "
        "usual situation for a process started by a service manager rather than a shell.",
    )
    ocr_enabled: bool = Field(
        default=True,
        description="Turning this off makes scanned pages fail with a clear message "
        "instead of attempting text recognition. Useful for a deployment with no "
        "tesseract binary available.",
    )
    ocr_min_words_per_page: int = Field(
        default=5,
        ge=0,
        description="A page with fewer words than this is treated as a scan and sent "
        "through Optical Character Recognition. From implementation.md section 6.1.",
    )
    grounding_min_score: float = Field(
        default=85.0,
        ge=0,
        le=100,
        description="RapidFuzz partial ratio below which a quote is not considered found. "
        "From implementation.md section 6.3.",
    )
    schema_proposal_debounce_seconds: float = Field(
        default=0.5,
        ge=0,
        description="How long the worker waits after the last document finishes before "
        "proposing an initial schema, so a staggered upload is treated as one batch. "
        "See review finding 8.5.",
    )

    # -- Schema drift matching. See decisions D23 and D24. -------------------
    # These four decide when the system changes a schema without asking. They are a first
    # pass, deliberately not tuned against real data yet, and they are configuration rather
    # than constants precisely because the sample corpus is expected to move them.
    drift_string_automap_min: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="String similarity at or above which a field auto-maps to an existing "
        "one with no prompt. Catches formatting and typo variants such as 'Vendor Name' "
        "against 'vendor_name'.",
    )
    drift_embedding_automap_min: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Embedding cosine at or above which a field auto-maps with no prompt. "
        "Catches semantic renames such as 'Supplier' against 'vendor_name', which string "
        "similarity scores near zero.",
    )
    drift_candidate_margin_min: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="How far the best candidate must beat the runner-up before an "
        "auto-map is allowed. A high score is not evidence of an unambiguous match when a "
        "second field scores nearly as high; that case belongs to a human.",
    )
    drift_novel_max: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description="A field whose best score on BOTH signals is below this against every "
        "existing field is treated as clearly novel and added with no prompt. Both signals "
        "must agree, because this is a claim about the absence of a match.",
    )
    llm_embed_model: str = Field(
        default="gemini-embedding-001",
        description="Model used for drift matching embeddings. Configuration, not code, "
        "for the same reason the extraction models are.",
    )

    # -- Schema drift matching. See decisions D23 and D24. -------------------
    # These four numbers ARE the policy for when the user is interrupted. They are a first
    # pass, not tuned against real data: D24 says that if the sample corpus shows them
    # producing wrong auto-applies, the numbers move, not the mechanism. That is why they
    # are configuration and not constants.
    drift_string_auto_map: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="String similarity at or above which a match is unambiguous enough to "
        "auto-map without asking.",
    )
    drift_embedding_auto_map: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Embedding cosine at or above which a semantic match is unambiguous "
        "enough to auto-map. Higher than the string bar because a cosine is dense: "
        "unrelated business terms routinely score 0.7 against each other.",
    )
    drift_auto_map_margin: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description="How far the best candidate must beat the runner-up to count as "
        "unambiguous. Without this, `Supplier` scoring 0.96 against vendor_name and 0.94 "
        "against supplier_id would auto-map on a coin flip instead of asking.",
    )
    # A field is "clearly novel" only if it scores below the ceiling against EVERY existing
    # field on BOTH signals. Declaring a field new is a claim about the absence of a match,
    # so both signals must agree. There are two ceilings rather than D24's single shared
    # one because a character ratio and a cosine are not comparable numbers. See D27.
    drift_novelty_ceiling_string: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Measured, not guessed: across the fixture corpus the highest string "
        "similarity between two genuinely DIFFERENT field labels is 0.59 "
        "('Currency' versus 'Reference'), so anything at or below 0.65 carries no evidence "
        "of a real match. Re-measure when the real sample corpus lands.",
    )
    drift_novelty_ceiling_embedding: float = Field(
        default=0.30,
        ge=0.0,
        le=1.0,
        description="THE ONE NUMBER STILL UNMEASURED, because it needs a live embedding "
        "model. High-dimensional text embeddings routinely score unrelated business terms "
        "at 0.4 to 0.7, so this is probably too strict and auto-add may rarely fire once "
        "vectors are live. Measure the cosine distribution over unrelated field pairs as "
        "soon as a key exists, and set this above its upper range. Erring strict only "
        "produces extra proposal cards, never a wrong merge.",
    )

    # -- Query safety. See decision D10. ------------------------------------
    query_row_limit: int = Field(default=500, ge=1)
    query_timeout_ms: int = Field(default=5000, ge=100)

    # -- Samples ------------------------------------------------------------
    samples_dir: Path = Field(
        default=Path("../samples"),
        description="Read by the seed route through samples/manifest.json. See D15.",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma separated list, because that is how env vars carry lists."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _gemini_needs_a_key(self) -> Self:
        if self.llm_provider == "gemini" and not self.gemini_api_key:
            raise ValueError(
                "LLM_PROVIDER is 'gemini' but GEMINI_API_KEY is not set. Either provide a "
                "key or leave LLM_PROVIDER as 'fake', which runs the full pipeline against "
                "recorded fixtures."
            )
        return self

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def llm_configured(self) -> bool:
        """Whether real model calls are possible. Reported by /healthz, never the key."""
        return self.llm_provider != "fake" and bool(self.gemini_api_key)

    def sync_database_url(self, readonly: bool = False) -> str:
        """The same connection as a synchronous URL, which Alembic requires."""
        url = str(self.database_url_readonly if readonly else self.database_url)
        return url.replace("+asyncpg", "+psycopg2").replace("postgresql+psycopg2", "postgresql")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The single settings instance. Cached, so the environment is read exactly once."""
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings. For tests that need to vary the environment."""
    get_settings.cache_clear()


def is_pytest_run() -> bool:
    """Whether this process is a test run. Used only to pick safe defaults."""
    return "PYTEST_CURRENT_TEST" in os.environ
