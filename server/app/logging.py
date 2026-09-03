"""Structured logging, and the correlation identifier that makes a bug report traceable.

Every log line and every error response carries the same ``request_id``. The interface shows
it in error toasts with a copy button, so a user saying "it broke" becomes a user saying
"it broke, request 0f3a9c", which is the difference between a guess and a grep. This is the
observability requirement in section 5 of requirements.md.

The identifier lives in a ``ContextVar``, so it follows a request across every ``await``
without being threaded through function signatures. Background worker tasks copy it in
explicitly, because a task outlives the request that queued it and would otherwise log
under an identifier that has already been reset.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_workspace_id: ContextVar[str | None] = ContextVar("workspace_id", default=None)
_document_id: ContextVar[str | None] = ContextVar("document_id", default=None)

_CONTEXT_VARS = {
    "request_id": _request_id,
    "workspace_id": _workspace_id,
    "document_id": _document_id,
}


def new_request_id() -> str:
    """A short identifier. Twelve hex characters: readable aloud, ample for one deployment."""
    return uuid.uuid4().hex[:12]


def current_request_id() -> str | None:
    return _request_id.get()


def bind_context(**values: str | None) -> None:
    """Attach identifiers to every subsequent log line in this context."""
    for key, value in values.items():
        variable = _CONTEXT_VARS.get(key)
        if variable is not None:
            variable.set(value)


def snapshot_context() -> dict[str, str | None]:
    """Capture the current identifiers, so a background task can carry them forward."""
    return {key: variable.get() for key, variable in _CONTEXT_VARS.items()}


@contextmanager
def logging_context(**values: str | None) -> Iterator[None]:
    """Bind identifiers for a block, then restore what was there before.

    Used by the worker: a queued document processes long after its upload request has
    returned, and must log under the identifiers of that upload rather than under whatever
    request happens to be in flight.
    """
    tokens = [
        (variable, variable.set(values[key]))
        for key, variable in _CONTEXT_VARS.items()
        if key in values
    ]
    try:
        yield
    finally:
        for variable, token in reversed(tokens):
            variable.reset(token)


def _add_context(
    _logger: object, _method: str, event: structlog.types.EventDict
) -> structlog.types.EventDict:
    """structlog processor: merge the context variables into every event."""
    for key, variable in _CONTEXT_VARS.items():
        value = variable.get()
        if value is not None:
            event.setdefault(key, value)
    return event


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    """Configure structlog and route the standard library through it.

    Called once, from the application factory. Third-party libraries log through the
    standard library, so routing it here means uvicorn and SQLAlchemy lines carry the same
    correlation identifier as ours.
    """
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_context,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Quiet the libraries that are chatty by default without being informative.
    logging.basicConfig(level=level.upper(), stream=sys.stderr, format="%(message)s")
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """A bound logger. Use the module's ``__name__``."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]


class CorrelationIdMiddleware:
    """Assign or adopt a request identifier, and echo it back on the response.

    A client that sends ``X-Request-ID`` keeps its own value, which lets the frontend
    generate the identifier before a request leaves the browser and so report an
    identifier even for a request that never arrived.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.decode().lower(): value.decode() for key, value in scope.get("headers", [])}
        incoming = headers.get(REQUEST_ID_HEADER.lower())
        request_id = incoming if incoming and len(incoming) <= 64 else new_request_id()

        with logging_context(request_id=request_id, workspace_id=None, document_id=None):

            async def send_with_header(message: Any) -> None:
                if message["type"] == "http.response.start":
                    message.setdefault("headers", [])
                    message["headers"].append(
                        (REQUEST_ID_HEADER.encode(), request_id.encode())
                    )
                await send(message)

            await self.app(scope, receive, send_with_header)


async def access_log_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """One structured line per request, with the route, status, and duration."""
    import time

    logger = get_logger("app.access")
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request.failed",
            method=request.method,
            path=request.url.path,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise
    logger.info(
        "request.completed",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return response
