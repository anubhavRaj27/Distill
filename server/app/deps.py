"""FastAPI dependencies: a database session, and the authenticated workspace.

The session dependency is where the event bus contract is honoured. Events staged during a
request are delivered only after the transaction commits, and discarded if it does not, so
a subscriber can never observe an event that was rolled back. See ``app.events.bus``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import parse_bearer, tokens_match
from app.config import Settings, get_settings
from app.db.models import Workspace
from app.db.session import get_sessionmaker
from app.errors import Unauthorised
from app.events.bus import bus
from app.logging import bind_context
from app.pipeline.worker import discard_submissions, flush_submissions
from app.types import WorkspaceId


async def get_session() -> AsyncIterator[AsyncSession]:
    """A transactional session for one request.

    Commits on success, rolls back on any exception, and flushes staged events only on the
    committed path.
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            bus.discard_staged(session)
            discard_submissions(session)
            raise
        else:
            await session.commit()
            # Order matters only in that BOTH must happen after the commit. An event
            # describing a row that was rolled back is a lie; a queued job for a row that
            # was rolled back is a dropped job with a confusing log line.
            bus.flush_after_commit(session)
            flush_submissions(session)


Session = Annotated[AsyncSession, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]

_UNAUTHORISED_MESSAGE = (
    "That workspace token is not valid. Workspaces are anonymous, so the token in your "
    "link is the only way in. If you have lost it, create a new workspace."
)


async def require_workspace(
    workspace_id: Annotated[WorkspaceId, Path()],
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
) -> Workspace:
    """Resolve and authorise the workspace named in the path.

    A wrong token and a nonexistent workspace produce the SAME error, on purpose: telling
    them apart would let anyone enumerate valid workspace identifiers. See ``app.auth``.
    """
    token = parse_bearer(authorization)
    if token is None:
        raise Unauthorised(_UNAUTHORISED_MESSAGE)

    workspace = (
        await session.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()

    # Compare even when the workspace is missing, so a missing workspace and a wrong token
    # take the same amount of time. Cheap, and it closes a timing side channel.
    stored_hash = workspace.token_hash if workspace is not None else "0" * 64
    if not tokens_match(token, stored_hash) or workspace is None:
        raise Unauthorised(_UNAUTHORISED_MESSAGE)

    bind_context(workspace_id=str(workspace.id))
    return workspace


CurrentWorkspace = Annotated[Workspace, Depends(require_workspace)]
