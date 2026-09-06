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
    storage_backend: Literal["local", "postgres"] = Field(
        default="local",
        description="Where originals and rendered page images live. `local` is a directory "
        "and is what development uses. `postgres` puts the bytes in the `blobs` table, "
        "which is what a deployment on a free tier needs: those containers have no disk "
        "that survives a restart, so a local store would empty itself on every redeploy "
        "and take the source viewer with it. Decision D45.",
    )
    storage_dir: Path = Field(
        default=Path("./var/storage"),
        description="Where the `local` backend keeps its files. Ignored by `postgres`.",
    )
    max_upload_mb: int = Field(
        default=20,
        ge=1,
        description="Per-file limit. Requirement FR-03. Enforced by counting bytes while "
        "streaming, never by trusting the declared Content-Length.",
    )
    max_files_per_upload: int = Field(default=25, ge=1)

    # -- Large Language Model. See decision D11. ----------------------------
    llm_provider: Literal["gemini", "fake"] = Field(
        default="fake",
        description="Defaults to `fake` on purpose: a checkout with no API key must still "
        "boot, run its tests, and serve the interface. Set to `gemini` to make real calls.",
    )
    gemini_api_key: str | None = None
    llm_extract_model: str = Field(
        default="gemini-3.5-flash-lite",
        description="Extraction and schema inference. Lite, and not by preference: every "
        "non-lite Gemini model this key can reach allows 20 requests PER DAY on the free "
        "tier, which one pass over a ten-document corpus exhausts. Measured on the sample "
        "corpus, Lite extracted all six invoices to the letter. Extraction keeps the "
        "model's default reasoning effort, unlike the interactive calls: see "
        "llm_fast_thinking_level and decisions D42 and D43.",
    )
    llm_fast_model: str = Field(
        default="gemini-3.5-flash-lite",
        description="The fast tier, used for chat planning, chat answering, dashboard "
        "planning, and suggestions. Renamed from llm_query_model in v2: there is no "
        "natural-language-to-SQL step any more (decision D24), and a name describing a "
        "removed feature is worse than no name. Latency here is felt directly, "
        "because the user is watching an answer stream, and the Lite model is here for "
        "exactly that reason: measured on September 5, 2026 it began a chat answer in "
        "about 0.8 seconds against about 9 for gemini-3.5-flash on the same question. "
        "Decision D42.",
    )
    llm_embed_model: str = Field(
        default="gemini-embedding-001",
        description="Embedding model for retrieval (decision D25) and schema drift "
        "matching (decision D18). Verified callable on September 5, 2026.",
    )
    llm_embed_dimensions: int = Field(
        default=768,
        ge=64,
        description="Output width requested from the embedding model. "
        "gemini-embedding-001 returns 3072 by default, which is four times the storage "
        "and four times the per-question arithmetic for a corpus this size, where 768 "
        "loses very little. Changing this changes the vector space, which is why "
        "`embed_space` carries it: chunks embedded at one width are not comparable with a "
        "question embedded at another, and the space label makes that visible instead of "
        "silent.",
    )
    llm_fast_thinking_level: Literal["low", "high"] | None = Field(
        default="low",
        description="Reasoning effort for the calls a user waits on: chat planning, chat "
        "answering, dashboard planning, suggestions. Decision D42. Measured on "
        "September 5, 2026, a Gemini 3 Flash model answered a structured call in about "
        "two seconds at `low` and about twenty-five at its default, which is the "
        "difference between meeting requirement FR-26 and missing it by a factor of "
        "eight. The "
        "accuracy-critical extraction calls are unaffected: they never pass a thinking "
        "level, so they keep the model's own default. None omits the setting entirely, "
        "which is what a Gemini 2.x model needs, since `thinking_level` is a 3.x field.",
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
    # -- Retrieval and chat. Decisions D24, D25, D32, D33. ------------------
    chunk_target_words: int = Field(
        default=110,
        ge=20,
        description="Aim for passages of about this many words. Chunk size IS highlight "
        "size, because a citation highlights the whole chunk's word span (decision D33), "
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
        description="Read by the seed route through samples/manifest.json. In a "
        "container the samples are copied in alongside the application, so this is set "
        "explicitly there rather than being relative to the checkout layout.",
    )

    client_dist_dir: Path = Field(
        default=Path("../client/dist"),
        description="The built interface, served by this process so that development and "
        "production are the same single-origin configuration (implementation.md section "
        "10). Absent in a checkout that has not run `npm run build`, in which case nothing "
        "is mounted and the API serves itself alone.",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_url(cls, value: object) -> object:
        """Accept the connection string a hosting provider hands out, unedited.

        Railway, Neon, Render and every other managed Postgres publish a URL for the
        standard synchronous client: ``postgres://`` or ``postgresql://``, often with
        ``?sslmode=require`` on the end. This application talks asyncpg, which needs the
        ``postgresql+asyncpg://`` scheme and rejects ``sslmode`` outright as an unknown
        keyword.

        Rewriting it here rather than asking a person to do it by hand removes what would
        otherwise be the single most likely deployment failure, and the one with the worst
        diagnostics: it surfaces on the first connection, inside a container, as a driver
        error with nothing pointing at the paste that caused it. ``DATABASE_URL`` can now be
        wired straight from the provider's own variable.

        The TLS intent is preserved rather than dropped. ``sslmode=require`` becomes
        asyncpg's ``ssl=require``, so a provider that insists on TLS still gets it, and a
        deployment does not silently downgrade to plaintext because a parameter was in the
        wrong dialect.
        """
        if not isinstance(value, str) or not value:
            return value

        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit(value)
        scheme = parts.scheme
        if scheme in ("postgres", "postgresql"):
            scheme = "postgresql+asyncpg"
        elif "+" in scheme and not scheme.endswith("+asyncpg"):
            # A URL naming a different driver is left alone: someone asking for psycopg
            # means it, and quietly swapping their driver is worse than failing.
            return value

        query = []
        for key, item in parse_qsl(parts.query, keep_blank_values=True):
            if key == "sslmode":
                # verify-ca and verify-full both need a certificate store this application
                # does not configure, so they become plain `require`: encrypted, unverified,
                # which is what the driver would do with `require` anyway.
                query.append(("ssl", "require" if item != "disable" else "disable"))
            elif key == "channel_binding":
                # Neon adds it; asyncpg has no such keyword.
                continue
            else:
                query.append((key, item))

        return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

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
    def embed_space(self) -> str:
        """The vector space label recorded on every chunk and label vector.

        Model identifier plus requested width, because two vectors from the same model at
        different widths cannot be compared and a bare model name would hide that. A
        workspace indexed before a width change keeps its own label, so retrieval skips
        those chunks loudly (``search`` logs the mismatch) rather than scoring them at a
        meaningless zero.
        """
        return f"{self.llm_embed_model}@{self.llm_embed_dimensions}"

    @property
    def llm_configured(self) -> bool:
        """Whether real model calls are possible. Reported by /healthz, never the key."""
        return self.llm_provider != "fake" and bool(self.gemini_api_key)

    def sync_database_url(self) -> str:
        """The same connection for a synchronous driver. See ``app.db.urls``."""
        from app.db.urls import to_sync

        return to_sync(str(self.database_url))


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
