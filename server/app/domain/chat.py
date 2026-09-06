"""Chat and dashboard vocabulary.

Kept in the domain layer because the chat service, the routers, the database models, and
the per-message stream all need to agree on these, and there is exactly one right place for
a shared enumeration.
"""

from __future__ import annotations

from enum import StrEnum


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatStatus(StrEnum):
    """The lifecycle of an assistant message.

    ``STREAMING`` is a persisted state, not just an in-memory one, and that is deliberate
    (decision D32): generation continues on the server whether or not a client is
    listening, so a refresh mid-answer has to find a row that says "this is still being
    written" rather than nothing at all.
    """

    STREAMING = "streaming"
    DONE = "done"
    STOPPED = "stopped"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self is not ChatStatus.STREAMING


class AnswerStage(StrEnum):
    """Coarse progress of one answer, shown while the user waits."""

    RETRIEVING = "retrieving"
    READING = "reading"
    PLANNING = "planning"
    ANSWERING = "answering"
    DONE = "done"
    STOPPED = "stopped"
    FAILED = "failed"


class DashboardStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class VisualKind(StrEnum):
    """What shape the agent chose for a result. Requirement A2-02's catalog."""

    METRIC = "metric"
    BAR = "bar"
    LINE = "line"
    TABLE = "table"
