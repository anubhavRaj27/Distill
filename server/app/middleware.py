"""Middleware that needed more than a line of configuration.

``SelectiveGZipMiddleware`` exists because compression and Server-Sent Events are mutually
exclusive, and the failure is silent. A compression middleware buffers a response in order
to compress it, so an event stream arrives as one lump when the stream finally closes rather
than as events arrive. The user sees a spinner and then everything at once, which looks like
a slow backend and is actually a middleware ordering bug.

Starlette's ``GZipMiddleware`` has no path exclusion, so this wraps it and routes streaming
paths around it entirely. Combined with ``X-Accel-Buffering: no`` on the responses
themselves (which tells a reverse proxy the same thing), that is both halves of the problem
the implementation document flags in section 7.6.
"""

from __future__ import annotations

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

STREAMING_PATH_MARKERS: tuple[str, ...] = ("/events", "/query", "/actions")
"""Path fragments that stream. Compression is bypassed for anything containing one."""


class SelectiveGZipMiddleware:
    """Compress everything except streaming responses."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        minimum_size: int = 1000,
        exclude_markers: tuple[str, ...] = STREAMING_PATH_MARKERS,
    ) -> None:
        self._plain = app
        self._compressed = GZipMiddleware(app, minimum_size=minimum_size)
        self._exclude_markers = exclude_markers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path: str = scope.get("path", "")
            if any(marker in path for marker in self._exclude_markers):
                await self._plain(scope, receive, send)
                return
        await self._compressed(scope, receive, send)
