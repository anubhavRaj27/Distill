"""Liveness and readiness.

Reports what an operator needs in order to tell a broken deployment from a working one:
whether the database answers, whether storage is writable, and whether a Large Language
Model key is present. **Never the key itself**, and never any part of it.

``process_id`` is here because of decision D8. The worker queue and the event bus are both
in-process, so the API must run with exactly one worker process. Reporting the process
identifier turns "two workers are running and half the events vanish" from a mystifying
intermittent bug into something visible in one request.
"""

from __future__ import annotations

import os
from typing import Literal

from anyio import to_thread
from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.config import get_settings
from app.db.session import get_engine
from app.logging import get_logger
from app.storage.factory import make_storage

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


class CheckResult(BaseModel):
    ok: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    environment: str
    process_id: int = Field(
        description="Operating system process identifier. The in-process worker queue and "
        "event bus require exactly one API process, so seeing this value change between "
        "requests means the deployment is misconfigured. See decision D8."
    )
    database: CheckResult
    storage: CheckResult
    llm: CheckResult


@router.get("/healthz", response_model=HealthResponse, summary="Liveness and readiness")
async def healthz() -> HealthResponse:
    settings = get_settings()

    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        database = CheckResult(ok=True)
    except Exception as exc:
        logger.warning("health.database_failed", error=str(exc))
        database = CheckResult(ok=False, detail=type(exc).__name__)

    try:
        # Through the configured store rather than at the directory it may or may not have.
        # The check is a real write and a real delete, because "the directory exists" and
        # "this deployment can store a document" are different claims, and the second one
        # is what an operator is asking.
        store = make_storage(settings)
        probe = "healthz/probe.bin"
        await to_thread.run_sync(lambda: store.put_bytes(probe, b"ok"))
        await to_thread.run_sync(lambda: store.delete(probe))
        storage = CheckResult(ok=True, detail=settings.storage_backend)
    except Exception as exc:
        logger.warning("health.storage_failed", error=str(exc))
        storage = CheckResult(ok=False, detail=type(exc).__name__)

    # A `fake` provider is a fully supported configuration, not a degraded one: the whole
    # pipeline runs against recorded fixtures. So this check reports what is configured
    # without calling it a failure. See decision D11.
    llm = CheckResult(
        ok=True,
        detail=(
            f"provider={settings.llm_provider}"
            + (
                f" extract={settings.llm_extract_model} fast={settings.llm_fast_model}"
                f" embed={settings.embed_space}"
                if settings.llm_configured
                else " (no API key present, running on recorded fixtures)"
            )
        ),
    )

    return HealthResponse(
        status="ok" if database.ok and storage.ok else "degraded",
        environment=settings.environment,
        process_id=os.getpid(),
        database=database,
        storage=storage,
        llm=llm,
    )
