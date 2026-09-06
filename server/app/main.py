"""The application factory, middleware stack, and lifespan.

Middleware order matters and is not arbitrary, so it is written out here rather than left
to be inferred:

1. ``CorrelationIdMiddleware`` is outermost, so a request has an identifier before anything
   else can fail and produce a log line or an error body without one.
2. ``SelectiveGZipMiddleware`` next, so compression sees the final body but never touches a
   streaming path.
3. CORS after that. In production the interface is served by this same process, so there is
   no cross-origin surface at all; the configured origins exist for Vite's development
   server.
4. The access log innermost of the custom layers, so its duration measurement covers route
   handling rather than middleware overhead.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db.session import dispose_engines, init_engines
from app.errors import register_exception_handlers
from app.llm.registry import init_client, reset_client
from app.logging import (
    CorrelationIdMiddleware,
    access_log_middleware,
    configure_logging,
    get_logger,
)
from app.middleware import SelectiveGZipMiddleware
from app.pipeline.worker import init_worker, reset_worker, resume_interrupted
from app.routers import (
    chat,
    dashboard,
    documents,
    events,
    health,
    records,
    schema,
    workspaces,
)
from app.storage.factory import make_storage, reset_storage_cache
from app.web import mount_client

logger = get_logger(__name__)

DESCRIPTION = """
Distill turns unstructured and semi-structured documents into clean, structured data that can
be searched and queried.

The interesting problems are not extraction from a single document, which modern language
models largely solve, but **unification** (turning many mutually disagreeing documents into
one coherent, queryable schema) and **trust** (making every extracted value traceable to
where it came from, and cheap for a person to correct).

Authentication is a workspace bearer token, issued once at workspace creation. There are no
accounts.
""".strip()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    logger.info(
        "app.starting",
        environment=settings.environment,
        llm_provider=settings.llm_provider,
        llm_configured=settings.llm_configured,
    )
    init_engines(settings)

    client = init_client(settings)
    storage = make_storage(settings)
    worker = init_worker(settings=settings, client=client, storage=storage)
    await worker.start()

    # Decision D8 accepts that a restart interrupts in-flight extractions, on the grounds
    # that the per-document status model makes them resumable. This is that resumption, and
    # it runs on every boot rather than being a manual recovery step.
    resumed = await resume_interrupted(worker)
    if resumed:
        logger.info("app.resumed_documents", count=resumed)

    try:
        yield
    finally:
        logger.info("app.stopping")
        await worker.stop()
        await dispose_engines()
        reset_storage_cache()
        reset_worker()
        reset_client()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="Distill",
        version="0.1.0",
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    # Order is significant. See the module docstring.
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(SelectiveGZipMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        # So the browser can read the correlation identifier and show it in an error toast.
        expose_headers=["X-Request-ID"],
    )
    app.middleware("http")(access_log_middleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    for module in (workspaces, documents, records, schema, events, chat, dashboard):
        app.include_router(module.router, prefix=settings.api_prefix)

    # Last, so that every route above wins the match. See `mount_client`.
    mount_client(app, settings)

    return app


def export_openapi(destination: Path | None = None) -> dict[str, Any]:
    """Write the OpenAPI document to disk, for the frontend's type generation.

    The frontend generates its client from this file, so it is a build artefact rather than
    something anyone edits. Run via ``make openapi``.
    """
    document = create_app().openapi()
    if destination is not None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


app = create_app()
