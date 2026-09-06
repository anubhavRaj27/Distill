"""Upload, seed, original file streaming, page images, and re-extraction.

REVIEW FINDING 8.8: THE SIZE LIMIT IS ENFORCED BY COUNTING, NOT BY TRUSTING
---------------------------------------------------------------------------
``Content-Length`` is a claim the client makes and can understate, so the limit is enforced
by counting bytes while spooling and aborting the moment it is passed.

Being precise about what that does and does not protect, because the original note here
overclaimed. Starlette parses the multipart body **before** the handler runs, so by this
point the bytes have already been received and buffered to Starlette's own temporary file.
What the counting prevents is an oversized file being **stored** and **processed**, which is
what costs disk and model tokens. Bounding what is *received* is a job for the reverse proxy
or the ASGI server's body limit, which is the only layer that can refuse a request before
reading it, and it is configured there rather than pretended at here.

BLOCKING FILE INPUT AND OUTPUT IS OFF-THREAD
--------------------------------------------
Writes, reads, and unlinks go through ``anyio.to_thread.run_sync``. This is not lint
appeasement: a twenty megabyte synchronous write on the event loop stalls every other
request in the process, and in this application that includes the Server-Sent Events
heartbeats that tell every connected browser the backend is alive. A single process
(decision D9) makes that a real consequence rather than a theoretical one.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from datetime import datetime
from functools import partial
from pathlib import Path
from uuid import UUID

from anyio import to_thread
from fastapi import APIRouter, File, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import Settings
from app.db.models import Document, Page
from app.deps import Config, CurrentWorkspace, Session
from app.domain.document import DocumentStatus, SourceFormat
from app.domain.events import DocumentStatusEvent
from app.errors import DocumentNotFound, FileTooLarge, NotFound, UnsupportedFileType
from app.events.bus import bus
from app.insights import dashboard as dashboard_module
from app.logging import get_logger
from app.pipeline.process import content_hash
from app.pipeline.sniff import HEAD_BYTES, SUPPORTED_EXTENSIONS, sniff
from app.pipeline.worker import submit_after_commit
from app.storage.base import Storage
from app.storage.factory import make_storage
from app.storage.local import original_key
from app.types import DocumentId, WorkspaceId

router = APIRouter(prefix="/workspaces/{workspace_id}/documents", tags=["documents"])
logger = get_logger(__name__)

STREAM_CHUNK = 1024 * 1024
"""One megabyte per chunk. Larger than a typical network read on purpose: each chunk costs
one thread hop for its write, so bigger chunks mean fewer hops for the same bytes."""


class UploadedDocument(BaseModel):
    id: UUID
    filename: str
    status: DocumentStatus
    size_bytes: int
    source_format: SourceFormat
    detected_mime: str
    note: str | None = Field(
        default=None,
        description="Set when the file's contents disagree with its extension. The content "
        "decides which parser runs; this explains what we concluded.",
    )
    duplicate_of: UUID | None = Field(
        default=None,
        description="Set when this exact file is already in the workspace. The upload is "
        "accepted and points at the existing document rather than processing it twice.",
    )


class RejectedUpload(BaseModel):
    filename: str
    code: str
    message: str


class UploadResponse(BaseModel):
    """Partial success is the normal case, so accepted and rejected come back together.

    One unreadable file in a drop of twelve must not fail the other eleven, which is
    guarantee 3 in the backend plan and requirement 3.6.
    """

    accepted: list[UploadedDocument] = Field(default_factory=list)
    rejected: list[RejectedUpload] = Field(default_factory=list)


def _storage(settings: Settings) -> Storage:
    """The configured store. Which one it is lives in `app.storage.factory`, not here."""
    return make_storage(settings)


async def _remove(path: Path) -> None:
    await to_thread.run_sync(lambda: path.unlink(missing_ok=True))


async def _spool(upload: UploadFile, limit: int) -> tuple[Path, int, bytes]:
    """Stream an upload to a temporary file, counting bytes. Returns path, size, and head.

    Raises ``FileTooLarge`` as soon as the count exceeds the limit, so an oversized file is
    never stored and never processed.
    """
    handle = await to_thread.run_sync(
        lambda: tempfile.NamedTemporaryFile(delete=False, suffix=".upload")
    )
    path = Path(handle.name)
    size = 0
    head = b""
    try:
        while chunk := await upload.read(STREAM_CHUNK):
            size += len(chunk)
            if size > limit:
                raise FileTooLarge(
                    f"{upload.filename!r} is larger than the {limit // (1024 * 1024)} MB "
                    f"limit.",
                    limit_mb=limit // (1024 * 1024),
                )
            if len(head) < HEAD_BYTES:
                head += chunk[: HEAD_BYTES - len(head)]
            await to_thread.run_sync(handle.write, chunk)
    except BaseException:
        await to_thread.run_sync(handle.close)
        await _remove(path)
        raise
    await to_thread.run_sync(handle.close)
    return path, size, head


@router.post("", response_model=UploadResponse, summary="Upload one or more documents")
async def upload(
    workspace: CurrentWorkspace,
    session: Session,
    settings: Config,
    files: list[UploadFile] = File(description="One or more documents."),  # noqa: B008
) -> UploadResponse:
    if len(files) > settings.max_files_per_upload:
        raise FileTooLarge(
            f"That is {len(files)} files. Please upload at most "
            f"{settings.max_files_per_upload} at a time.",
            limit=settings.max_files_per_upload,
        )

    storage = _storage(settings)
    response = UploadResponse()

    for upload_file in files:
        filename = upload_file.filename or "untitled"
        try:
            path, size, head = await _spool(upload_file, settings.max_upload_bytes)
        except FileTooLarge as exc:
            response.rejected.append(
                RejectedUpload(filename=filename, code=exc.code, message=exc.message)
            )
            continue

        try:
            if size == 0:
                raise UnsupportedFileType(
                    f"{filename!r} is empty.", supported=list(SUPPORTED_EXTENSIONS)
                )
            sniffed = sniff(head, filename)

            data = await to_thread.run_sync(path.read_bytes)
            digest = content_hash(data)

            existing = (
                await session.execute(
                    select(Document).where(
                        Document.workspace_id == workspace.id,
                        Document.content_hash == digest,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                # Accepted rather than rejected: re-dropping a file is a normal thing to do
                # and the honest answer is "you already have this", not an error.
                response.accepted.append(
                    UploadedDocument(
                        id=existing.id,
                        filename=existing.filename,
                        status=existing.status,
                        size_bytes=existing.size_bytes,
                        source_format=existing.source_format,
                        detected_mime=existing.mime,
                        note=f"This file is already in your workspace as {existing.filename!r}.",
                        duplicate_of=existing.id,
                    )
                )
                continue

            document = Document(
                workspace_id=workspace.id,
                filename=filename,
                mime=sniffed.mime,
                source_format=sniffed.source_format,
                size_bytes=size,
                content_hash=digest,
                storage_key="",
                status=DocumentStatus.UPLOADED,
                stage_detail=sniffed.note,
            )
            session.add(document)
            await session.flush()

            key = original_key(workspace.id, document.id, sniffed.source_format.value)
            # `partial`, not a lambda: a lambda would capture the loop variables by
            # reference. It happens to be correct here because the await is immediate, but
            # it is one refactor away from storing the wrong file under the wrong key.
            await to_thread.run_sync(partial(storage.put_file, key, path, move=True))
            document.storage_key = key
            await session.flush()

            await bus.publish(
                session,
                workspace.id,
                DocumentStatusEvent(
                    seq=0,
                    document_id=document.id,
                    filename=filename,
                    status=DocumentStatus.UPLOADED,
                    stage_detail=sniffed.note or "queued",
                ),
            )
            submit_after_commit(session, document.id)

            response.accepted.append(
                UploadedDocument(
                    id=document.id,
                    filename=filename,
                    status=document.status,
                    size_bytes=size,
                    source_format=sniffed.source_format,
                    detected_mime=sniffed.mime,
                    note=sniffed.note,
                )
            )
        except UnsupportedFileType as exc:
            response.rejected.append(
                RejectedUpload(filename=filename, code=exc.code, message=exc.message)
            )
        finally:
            await _remove(path)

    if any(entry.duplicate_of is None for entry in response.accepted):
        # New content invalidates the panels. Marked rather than regenerated: see
        # app.insights.dashboard.mark_stale for why that choice is the user's.
        await dashboard_module.mark_stale(session, workspace.id, reason="documents added")

    logger.info(
        "documents.uploaded",
        accepted=len(response.accepted),
        rejected=len(response.rejected),
    )
    return response


class SeedResponse(BaseModel):
    loaded: list[UploadedDocument] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    message: str


@router.post("/seed", response_model=SeedResponse, summary="Load the sample documents")
async def seed(
    workspace: CurrentWorkspace, session: Session, settings: Config
) -> SeedResponse:
    """Load the curated sample set. Requirement FR-05, decision D15.

    Reads ``samples/manifest.json`` rather than hard-coding filenames, so dropping files
    into ``samples/`` is the only step needed to change the demo corpus.
    """
    import json

    directory = settings.samples_dir
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        return SeedResponse(
            loaded=[],
            missing=[],
            message=(
                f"No sample documents are installed. Add files to {directory} and list them "
                f"in manifest.json to enable the one-click demo."
            ),
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest.get("documents", manifest if isinstance(manifest, list) else [])
    except (json.JSONDecodeError, AttributeError):
        return SeedResponse(
            loaded=[], missing=[], message=f"{manifest_path} is not valid JSON."
        )

    storage = _storage(settings)
    loaded: list[UploadedDocument] = []
    missing: list[str] = []

    for entry in entries:
        name = entry if isinstance(entry, str) else entry.get("file", "")
        source = directory / name
        if not name or not source.is_file():
            missing.append(name or "(unnamed entry)")
            continue

        data = await to_thread.run_sync(source.read_bytes)
        digest = content_hash(data)
        already = (
            await session.execute(
                select(Document).where(
                    Document.workspace_id == workspace.id, Document.content_hash == digest
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            continue

        try:
            sniffed = sniff(data[:HEAD_BYTES], name)
        except UnsupportedFileType:
            missing.append(name)
            continue

        document = Document(
            workspace_id=workspace.id,
            filename=name,
            mime=sniffed.mime,
            source_format=sniffed.source_format,
            size_bytes=len(data),
            content_hash=digest,
            storage_key="",
            status=DocumentStatus.UPLOADED,
        )
        session.add(document)
        await session.flush()
        key = original_key(workspace.id, document.id, sniffed.source_format.value)
        await to_thread.run_sync(partial(storage.put_bytes, key, data))
        document.storage_key = key
        await session.flush()

        await bus.publish(
            session,
            workspace.id,
            DocumentStatusEvent(
                seq=0,
                document_id=document.id,
                filename=name,
                status=DocumentStatus.UPLOADED,
                stage_detail="queued",
            ),
        )
        submit_after_commit(session, document.id)
        loaded.append(
            UploadedDocument(
                id=document.id,
                filename=name,
                status=document.status,
                size_bytes=len(data),
                source_format=sniffed.source_format,
                detected_mime=sniffed.mime,
            )
        )

    return SeedResponse(
        loaded=loaded,
        missing=missing,
        message=f"Loading {len(loaded)} sample documents."
        if loaded
        else "The sample documents are already in this workspace.",
    )


async def _require_document(
    session: Session, workspace_id: UUID, document_id: UUID
) -> Document:
    document = (
        await session.execute(
            select(Document).where(
                Document.id == document_id, Document.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()
    if document is None:
        raise DocumentNotFound("That document is not in this workspace.")
    return document


class DocumentDetail(BaseModel):
    id: UUID
    filename: str
    mime: str
    source_format: SourceFormat
    size_bytes: int
    status: DocumentStatus
    stage_detail: str | None
    failure_reason: str | None
    page_count: int | None
    attempts: int
    created_at: datetime
    pages: list[dict[str, object]] = Field(
        default_factory=list,
        description="Per-page dimensions IN POINTS plus the image path. The viewer divides "
        "the width it actually rendered by `width_pt` to get its overlay scale, so it "
        "never needs to know about dots per inch.",
    )


@router.get("/{document_id}", response_model=DocumentDetail, summary="One document")
async def get_document(
    workspace: CurrentWorkspace,
    session: Session,
    document_id: DocumentId,
) -> DocumentDetail:
    document = await _require_document(session, workspace.id, document_id)
    pages = (
        (
            await session.execute(
                select(Page).where(Page.document_id == document.id).order_by(Page.index)
            )
        )
        .scalars()
        .all()
    )
    return DocumentDetail(
        id=document.id,
        filename=document.filename,
        mime=document.mime,
        source_format=document.source_format,
        size_bytes=document.size_bytes,
        status=document.status,
        stage_detail=document.stage_detail,
        failure_reason=document.failure_reason,
        page_count=document.page_count,
        attempts=document.attempts,
        created_at=document.created_at,
        pages=[
            {
                "index": page.index,
                "width_pt": page.width_pt,
                "height_pt": page.height_pt,
                "ocr_applied": page.ocr_applied,
                "locator": page.locator,
                "image_url": (
                    f"/api/v1/workspaces/{workspace.id}/documents/{document.id}"
                    f"/pages/{page.index}/image"
                ),
            }
            for page in pages
        ],
    )


@router.get("/{document_id}/file", summary="The original file, with byte-range support")
async def original_file(
    workspace: CurrentWorkspace,
    session: Session,
    settings: Config,
    document_id: DocumentId,
    request: Request,
) -> Response:
    """Stream the original. Range requests are supported because pdf.js relies on them.

    Without ranges, opening page one of a fifty megabyte scan downloads all fifty
    megabytes first, which is the difference between a viewer that feels instant and one
    that does not.
    """
    document = await _require_document(session, workspace.id, document_id)
    storage = _storage(settings)
    if not storage.exists(document.storage_key):
        raise DocumentNotFound("The stored copy of this document is missing.")

    total = storage.size(document.storage_key)
    range_header = request.headers.get("range")
    common = {
        "Content-Disposition": f'inline; filename="{document.filename}"',
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
    }

    if range_header and range_header.startswith("bytes="):
        raw = range_header.removeprefix("bytes=").split(",")[0].strip()
        start_text, _, end_text = raw.partition("-")
        try:
            start = int(start_text) if start_text else 0
            end = int(end_text) if end_text else total - 1
        except ValueError:
            start, end = 0, total - 1
        start = max(0, min(start, total - 1))
        end = max(start, min(end, total - 1))

        from app.storage.base import stream_range

        return StreamingResponse(
            stream_range(storage, document.storage_key, start, end),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=document.mime,
            headers={
                **common,
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Content-Length": str(end - start + 1),
            },
        )

    async def whole() -> AsyncIterator[bytes]:
        for chunk in storage.open_stream(document.storage_key):
            yield chunk

    return StreamingResponse(
        whole(),
        media_type=document.mime,
        headers={**common, "Content-Length": str(total)},
    )


@router.get("/{document_id}/pages/{page_index}/image", summary="A rendered page image")
async def page_image(
    workspace: CurrentWorkspace,
    session: Session,
    settings: Config,
    document_id: DocumentId,
    page_index: int,
) -> Response:
    document = await _require_document(session, workspace.id, document_id)
    page = (
        await session.execute(
            select(Page).where(Page.document_id == document.id, Page.index == page_index)
        )
    ).scalar_one_or_none()
    if page is None or not page.image_key:
        raise NotFound("That page has not been rendered.")

    storage = _storage(settings)
    if not storage.exists(page.image_key):
        raise NotFound("That page image is missing.")
    return Response(
        content=await to_thread.run_sync(lambda: storage.get_bytes(page.image_key)),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400"},
    )


class ReextractResponse(BaseModel):
    document_id: UUID
    message: str


@router.post(
    "/{document_id}/reextract",
    response_model=ReextractResponse,
    summary="Re-run extraction, preserving human corrections",
)
async def reextract(
    workspace: CurrentWorkspace,
    session: Session,
    document_id: DocumentId,
) -> ReextractResponse:
    """Re-run the pipeline for one document. Requirement FR-34.

    Human-verified values survive by construction: the write path filters them out and a
    disagreeing model answer is recorded beside the human's rather than over it. See
    ``app.pipeline.persist`` and decision D16.
    """
    document = await _require_document(session, workspace.id, document_id)
    document.failure_reason = None
    document.attempts = 0
    await bus.publish(
        session,
        workspace.id,
        DocumentStatusEvent(
            seq=0,
            document_id=document.id,
            filename=document.filename,
            status=DocumentStatus.UPLOADED,
            stage_detail="queued for re-extraction",
        ),
    )
    document.status = DocumentStatus.UPLOADED
    await session.flush()
    submit_after_commit(session, document.id)
    return ReextractResponse(
        document_id=document.id,
        message="Re-extracting. Values you have edited or confirmed will be kept.",
    )


@router.delete(
    "/{document_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a document"
)
async def delete_document(
    workspace: CurrentWorkspace,
    session: Session,
    settings: Config,
    document_id: DocumentId,
    workspace_id: WorkspaceId,
) -> Response:
    from app.domain.events import DocumentDeletedEvent
    from app.storage.local import document_prefix

    document = await _require_document(session, workspace.id, document_id)
    storage = _storage(settings)
    await to_thread.run_sync(
        lambda: storage.delete_prefix(document_prefix(workspace.id, document.id))
    )
    await session.delete(document)
    await bus.publish(
        session, workspace.id, DocumentDeletedEvent(seq=0, document_id=document_id)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
