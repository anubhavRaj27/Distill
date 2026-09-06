"""Serving the built interface from the API process.

One process, one origin. The client is a single-page application built by Vite into
``client/dist``; this hands those files out, and hands out ``index.html`` for anything that
looks like a client route. Implementation.md section 10 has always said the deployment works
this way, and the Vite dev proxy exists so that development matches it; this is the half
that was missing.

Two things are easy to get wrong here and both fail late.

**Route order.** The catch-all below matches everything, so it is registered after every
router and it refuses anything under the API prefix itself. Without that refusal, a typo in
an API path would return the HTML shell with a 200 instead of a JSON 404, and the client
would try to parse a web page as a workspace.

**Caching.** Vite fingerprints asset filenames, so those can be cached for a year and are.
``index.html`` names them and must never be cached, or a browser holding yesterday's shell
asks for assets that no longer exist after a deploy.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from starlette.status import HTTP_404_NOT_FOUND

from app.config import Settings
from app.logging import get_logger

logger = get_logger(__name__)

IMMUTABLE = "public, max-age=31536000, immutable"
NO_STORE = "no-cache, no-store, must-revalidate"


def mount_client(app: FastAPI, settings: Settings) -> None:
    """Serve ``client_dist_dir`` under the API, if it has been built.

    A checkout that has never run the client build is a normal state: the tests run in it
    and so does anyone working on the backend alone. Nothing is mounted in that case, and
    the log line says so once rather than the application failing to start.
    """
    root = settings.client_dist_dir.resolve()
    index = root / "index.html"
    if not index.is_file():
        logger.info("client.not_mounted", path=str(root))
        return

    # Everything the API owns. The prefix's first segment is reserved as well as the whole
    # prefix, so a request to /api/v2/anything is a 404 from the API rather than an HTML
    # page: a client asking a version that does not exist should be told so.
    api_prefix = settings.api_prefix.strip("/")
    reserved = {api_prefix, api_prefix.split("/", 1)[0], "healthz", "docs", "openapi.json"}

    @app.get("/{requested:path}", include_in_schema=False)
    async def serve_client(requested: str) -> FileResponse:
        head = requested.split("/", 1)[0]
        if head in reserved or requested in reserved:
            # An unmatched path that belongs to the API is a 404 from the API, not the
            # interface politely pretending the route exists.
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Not found")

        candidate = _resolve(root, requested)
        if candidate is not None:
            cache = IMMUTABLE if head == "assets" else NO_STORE
            return FileResponse(candidate, headers={"Cache-Control": cache})

        # Everything else is a client route: /w/{id}/chat, /w/{id}/data, and whatever is
        # added later. The shell is returned and the router in the browser takes it from
        # there, which is what makes a reload of any screen work.
        return FileResponse(index, headers={"Cache-Control": NO_STORE})

    logger.info("client.mounted", path=str(root))


def _resolve(root: Path, requested: str) -> Path | None:
    """The real file for a request path, or None if there is not one.

    The containment check is the point. ``requested`` is attacker-controlled and a path
    such as ``../../etc/passwd`` would otherwise resolve to a real file outside the build
    directory, which this process would then happily read out.
    """
    if not requested:
        return None
    candidate = (root / requested).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate
