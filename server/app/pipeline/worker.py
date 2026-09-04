"""The in-process job queue. Decision D9.

An ``asyncio.Queue`` with a fixed pool of consumer tasks, rather than Redis with a separate
worker process. A single instance over five days does not need a broker, and a broker adds a
service to the one-command setup promise.

Three consequences of that choice, all handled here rather than left implicit:

* **The interface must run with exactly one worker process.** Two would split this queue and
  the event bus. Pinned in the Dockerfile, the compose file, and the Makefile, and
  ``/healthz`` reports the process identifier so a misconfiguration is visible rather than
  mysterious.
* **A restart interrupts in-flight work.** Decision D9 accepts this and notes that the
  per-document status model makes it resumable. ``resume_interrupted`` is that resumption:
  on boot, any document left mid-pipeline is re-queued.
* **Concurrency is bounded.** Extraction is a network call per document, so the limit exists
  to avoid hitting provider rate limits with a twenty file upload, not to protect the
  processor.

Retries live here rather than in ``process_document`` because the distinction that matters
is between a failure worth retrying (the provider was briefly unavailable) and one that is
not (the file is password protected). The first is the queue's business; the second is the
document's, and ``process_document`` has already recorded it.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy import select, update

from app.config import Settings
from app.db.models import Document
from app.db.session import session_scope
from app.domain.document import DocumentStatus
from app.llm.base import LLMClient
from app.logging import get_logger, logging_context, snapshot_context
from app.pipeline.process import process_document
from app.storage.base import Storage

logger = get_logger(__name__)

SHUTDOWN_GRACE_SECONDS = 10.0
"""How long to let in-flight documents finish on shutdown before abandoning them. They are
re-queued on the next boot either way, so this is a courtesy rather than a guarantee."""


class Worker:
    """Processes uploaded documents in the background."""

    def __init__(self, *, settings: Settings, client: LLMClient, storage: Storage) -> None:
        self._settings = settings
        self._client = client
        self._storage = storage
        self._queue: asyncio.Queue[UUID] = asyncio.Queue()
        self._consumers: list[asyncio.Task[None]] = []
        self._running = False

    # -- lifecycle ------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._consumers = [
            asyncio.create_task(self._consume(index), name=f"distill-worker-{index}")
            for index in range(self._settings.worker_concurrency)
        ]
        logger.info("worker.started", concurrency=self._settings.worker_concurrency)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            await asyncio.wait_for(self._queue.join(), timeout=SHUTDOWN_GRACE_SECONDS)
        except TimeoutError:
            logger.warning("worker.shutdown_timeout", pending=self._queue.qsize())
        for task in self._consumers:
            task.cancel()
        await asyncio.gather(*self._consumers, return_exceptions=True)
        self._consumers.clear()
        logger.info("worker.stopped")

    # -- submission -----------------------------------------------------

    def submit(self, document_id: UUID) -> None:
        """Queue a document immediately.

        Only safe when the document row is already committed. From inside a request, use
        ``submit_after_commit`` instead: see the note on that function, which exists because
        submitting mid-transaction is a real bug that this project already shipped once.
        """
        self._queue.put_nowait(document_id)
        logger.info("worker.queued", document_id=str(document_id), depth=self._queue.qsize())

    @property
    def depth(self) -> int:
        return self._queue.qsize()

    async def drain(self) -> None:
        """Wait for the queue to empty. For tests, and for the seed route's convenience."""
        await self._queue.join()

    # -- the loop -------------------------------------------------------

    async def _consume(self, index: int) -> None:
        context = snapshot_context()
        while True:
            document_id = await self._queue.get()
            try:
                with logging_context(request_id=context.get("request_id")):
                    await self._process_with_retries(document_id)
            except asyncio.CancelledError:
                # Re-raised so the task actually stops, but `finally` still runs, so the
                # queue's outstanding count stays correct and `join()` cannot hang.
                raise
            except Exception:
                # A consumer must never die of a single bad document. If it does, the pool
                # shrinks silently and uploads stop being processed with no error anywhere.
                logger.exception(
                    "worker.consumer_error", consumer=index, document_id=str(document_id)
                )
            finally:
                # Exactly once per `get()`, on every path. Anything cleverer here risks
                # either a hung `join()` or a ValueError from over-counting.
                self._queue.task_done()

    async def _process_with_retries(self, document_id: UUID) -> None:
        attempts = self._settings.llm_max_attempts
        for attempt in range(1, attempts + 1):
            async with session_scope() as session:
                await session.execute(
                    update(Document)
                    .where(Document.id == document_id)
                    .values(attempts=attempt)
                )

            await process_document(
                document_id,
                client=self._client,
                settings=self._settings,
                storage=self._storage,
            )

            async with session_scope() as session:
                document = await session.get(Document, document_id)
                if document is None or document.status is not DocumentStatus.FAILED:
                    return
                retryable = _is_retryable(document.failure_reason)

            if not retryable or attempt >= attempts:
                return

            delay = min(8.0, 0.5 * (2 ** (attempt - 1)))
            logger.info(
                "worker.retrying",
                document_id=str(document_id),
                attempt=attempt + 1,
                of=attempts,
                delay_seconds=delay,
            )
            await asyncio.sleep(delay)


# Phrases from the user-facing failure messages that mean "the provider had a bad moment",
# as opposed to "this file cannot be read". Matching on the message rather than the
# exception type because `process_document` deliberately converts exceptions into messages
# before recording them, so that the user never sees a class name.
_RETRYABLE_MARKERS: tuple[str, ...] = (
    "rate limit",
    "try again shortly",
    "did not respond in time",
    "something went wrong on our side",
    "something went wrong while processing",
)


def _is_retryable(failure_reason: str | None) -> bool:
    if not failure_reason:
        return False
    lowered = failure_reason.lower()
    return any(marker in lowered for marker in _RETRYABLE_MARKERS)


async def resume_interrupted(worker: Worker) -> int:
    """Re-queue documents left mid-pipeline by a restart. Decision D9's accepted risk.

    A document stuck in ``uploaded``, ``parsing``, ``extracting``, or ``indexing`` had a
    process die under it. ``awaiting_schema`` is deliberately excluded: that is a legitimate
    resting state, not an interruption, and re-queueing it would re-run an extraction that
    already succeeded.
    """
    interrupted = (
        DocumentStatus.UPLOADED,
        DocumentStatus.PARSING,
        DocumentStatus.EXTRACTING,
        DocumentStatus.INDEXING,
    )
    async with session_scope() as session:
        rows = list(
            (
                await session.execute(
                    select(Document.id).where(Document.status.in_(interrupted))
                )
            )
            .scalars()
            .all()
        )
    for document_id in rows:
        worker.submit(document_id)
    if rows:
        logger.info("worker.resumed_interrupted", count=len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# Submitting from inside a transaction
# ---------------------------------------------------------------------------

_SESSION_KEY = "distill_pending_submissions"


def submit_after_commit(session: Any, document_id: UUID) -> None:
    """Queue a document once the current transaction commits.

    WHY THIS EXISTS. The upload route creates a ``documents`` row and queues it for
    processing, and the obvious code, calling ``submit`` directly, is wrong: the row is not
    committed until the request finishes, while the consumer pool picks the identifier up
    within microseconds and opens its OWN session to load it. The row is not there yet, so
    the consumer logs "document missing" and drops the job.

    That is not a theoretical race. Uploading six files reproduced it immediately: five
    were dropped and one survived by winning the race with the commit. It presents as
    documents stuck in ``uploaded`` forever with nothing in the log but a warning, which is
    a genuinely hard bug to find from the symptom.

    The event bus already had this problem and solves it the same way, by staging on the
    session and flushing after commit (see ``app.events.bus``). This mirrors it, so both
    "tell the world" and "start the work" happen strictly after the world is true.
    """
    pending: list[UUID] = session.info.setdefault(_SESSION_KEY, [])
    pending.append(document_id)


def flush_submissions(session: Any) -> None:
    """Queue everything staged on ``session``. Call only after a successful commit."""
    pending: list[UUID] = session.info.pop(_SESSION_KEY, [])
    if not pending:
        return
    worker = get_worker()
    for document_id in pending:
        worker.submit(document_id)


def discard_submissions(session: Any) -> None:
    """Drop staged submissions. Call after a rollback, so nothing is processed."""
    dropped = session.info.pop(_SESSION_KEY, [])
    if dropped:
        logger.info("worker.submissions_discarded_on_rollback", count=len(dropped))


_worker: Worker | None = None


def init_worker(*, settings: Settings, client: LLMClient, storage: Storage) -> Worker:
    global _worker
    _worker = Worker(settings=settings, client=client, storage=storage)
    return _worker


def get_worker() -> Worker:
    if _worker is None:
        raise RuntimeError("init_worker() has not been called")
    return _worker


def reset_worker() -> None:
    global _worker
    _worker = None
