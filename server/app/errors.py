"""One error shape for the whole interface, and no raw exception ever reaching a client.

Every failure response has the same body::

    {"error": {"code": "document_not_found",
               "message": "That document is not in this workspace.",
               "detail": {...},
               "request_id": "0f3a9c1b2d4e"}}

Three properties are deliberate.

``code`` is a stable machine string, so the frontend can branch on a failure without
matching on prose. ``message`` is written for a person and says what to do next, because
requirement 3.6 of requirements.md asks for specific and actionable messages rather than
raw database errors. ``request_id`` is present on every error, which is what turns "it broke"
into a traceable report.

Any exception that is not a ``DistillError`` becomes a 500 with the code ``internal_error`` and
a deliberately uninformative message, while the real exception is logged in full with the
same identifier. Leaking an internal message to a client is both an information disclosure
and a worse user experience than a clear "something went wrong, here is the reference".
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging import current_request_id, get_logger

logger = get_logger(__name__)


class DistillError(Exception):
    """Base for every failure this application raises on purpose.

    Subclasses set ``code`` and ``http_status``. The message is written for the user.
    """

    code: str = "error"
    http_status: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail:
            body["detail"] = self.detail
        body["request_id"] = current_request_id()
        return {"error": body}


# ---------------------------------------------------------------------------
# Client errors
# ---------------------------------------------------------------------------


class NotFound(DistillError):
    code = "not_found"
    http_status = status.HTTP_404_NOT_FOUND


class WorkspaceNotFound(NotFound):
    code = "workspace_not_found"


class DocumentNotFound(NotFound):
    code = "document_not_found"


class RecordNotFound(NotFound):
    code = "record_not_found"


class FieldNotInSchema(DistillError):
    code = "field_not_in_schema"
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT


class Unauthorised(DistillError):
    """Deliberately says nothing about whether the workspace exists.

    Distinguishing "no such workspace" from "wrong token" would let anyone enumerate
    workspace identifiers, and workspace identifiers are the only access control this
    product has (decision D8).
    """

    code = "unauthorised"
    http_status = status.HTTP_401_UNAUTHORIZED


class UnsupportedFileType(DistillError):
    """Requirement FR-03: reject inline, and say what IS supported."""

    code = "unsupported_file_type"
    http_status = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE


class FileTooLarge(DistillError):
    code = "file_too_large"
    http_status = status.HTTP_413_CONTENT_TOO_LARGE


class InvalidSchemaChange(DistillError):
    code = "invalid_schema_change"
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT


class InvalidValue(DistillError):
    """A human correction that does not satisfy its field's type. Requirement FR-23."""

    code = "invalid_value"
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT


class QueryRejected(DistillError):
    """Generated SQL failed the guard. See decision D10."""

    code = "query_rejected"
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT


# ---------------------------------------------------------------------------
# Server and upstream errors
# ---------------------------------------------------------------------------


class ParseFailed(DistillError):
    """A document could not be read. Carries a reason written for the user.

    The reason text is what appears next to the failed row in the progress list, so the
    wording here IS the user experience for section 3.6 of requirements.md.
    """

    code = "parse_failed"
    http_status = status.HTTP_422_UNPROCESSABLE_CONTENT


class LLMUnavailable(DistillError):
    code = "llm_unavailable"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE


class LLMInvalidOutput(DistillError):
    """The model returned something that could not be validated after every retry."""

    code = "llm_invalid_output"
    http_status = status.HTTP_502_BAD_GATEWAY


class NotConfigured(DistillError):
    code = "not_configured"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers so that no route can return an unshaped error."""

    @app.exception_handler(DistillError)
    async def _distill(_request: Request, exc: DistillError) -> JSONResponse:
        # Client mistakes are not warnings. Only 5xx is our problem.
        log = logger.warning if exc.http_status >= 500 else logger.info
        log("request.error", code=exc.code, status=exc.http_status, message=exc.message)
        return JSONResponse(status_code=exc.http_status, content=exc.to_body())

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        """Reshape framework errors, such as a 404 on an unknown path, into our envelope."""
        code = {
            status.HTTP_404_NOT_FOUND: "not_found",
            status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
        }.get(exc.status_code, "http_error")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": code,
                    "message": str(exc.detail),
                    "request_id": current_request_id(),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        """Pydantic validation failures, with the field errors kept in ``detail``.

        ``errors`` can contain non-serialisable values such as exception instances, so it
        is passed through pydantic's JSON-safe encoder rather than handed to json directly.
        """
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "The request body or parameters are not valid.",
                    "detail": {"errors": _jsonable(exc.errors())},
                    "request_id": current_request_id(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        """The backstop. Log everything, tell the client nothing but the reference."""
        logger.exception("request.unhandled", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Something went wrong on our side. "
                    "Quote the request reference if you report this.",
                    "request_id": current_request_id(),
                }
            },
        )


def _jsonable(value: Any) -> Any:
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(value)
