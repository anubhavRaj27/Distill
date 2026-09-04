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
    llm_fast_model: str = Field(
        default="gemini-2.5-flash",
        description="The fast tier, used for chat planning, chat answering, dashboard "
        "planning, and suggestions. Renamed from llm_query_model in v2: there is no "
        "natural-language-to-SQL step any more (decision D35), and a name describing a "
        "removed feature is worse than no name. Latency here is felt directly, "
        "because the user is watching an answer stream.",
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
    # -- Retrieval and chat. Decisions D35, D36, D44, D45. ------------------
    chunk_target_words: int = Field(
        default=110,
        ge=20,
        description="Aim for passages of about this many words. Chunk size IS highlight "
        "size, because a citation highlights the whole chunk's word span (decision D45), "
        "so this is a readability decision as much as a retrieval one: a 500 word chunk "
        "would light up half a page and tell the user nothing.",
    )
    chunk_max_words: int = Field(default=160, ge=40)
    chunk_overlap_lines: int = Field(
        default=1,
        ge=0,
        description="Lines repeated between neighbouring chunks, so a fact stated across a "
        "chunk boundary is still wholly present in one of them.",
    )
    chat_top_k: int = Field(
        default=8,
        ge=1,
        le=40,
        description="Passages given to the model per question.",
    )
    chat_min_similarity: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Cosine floor for a retrieved passage. Low on purpose: the cost of one "
        "irrelevant passage in the prompt is small, and the cost of missing the passage "
        "that held the answer is a wrong 'not in these documents'.",
    )
    chat_history_turns: int = Field(
        default=4, ge=0, description="Recent turns sent as context, so follow-ups work."
    )
    chat_token_coalesce_ms: int = Field(
        default=40,
        ge=0,
        description="Prose deltas are batched to at most one event per this interval, so a "
        "fast model does not produce thousands of tiny frames the browser must render.",
    )
    answer_buffer_grace_seconds: float = Field(
        default=60.0,
        ge=0,
        description="How long a finished answer's buffer is kept so a late reconnect can "
        "still replay it rather than being told to refetch.",
    )
    dashboard_max_panels: int = Field(default=6, ge=1, le=12)

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

    def sync_database_url(self) -> str:
        """The same connection as a synchronous URL, which Alembic requires."""
        return (
            str(self.database_url)
            .replace("+asyncpg", "+psycopg2")
            .replace("postgresql+psycopg2", "postgresql")
        )


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
