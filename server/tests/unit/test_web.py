"""Serving the built interface from the API process. Decision D45, and the half of
implementation.md section 10 that had never been written.

The single-page application needs two things from a server that a static host gives for
free and a router-mounted API does not: an unknown path has to come back as the shell so
that reloading `/w/{id}/data` works, and an unknown API path has to keep coming back as a
404 so that a typo does not arrive at the client as a page pretending to be JSON.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.config import Settings
from app.web import _resolve, mount_client
from fastapi import FastAPI
from starlette.testclient import TestClient


def build(tmp_path: Path) -> tuple[TestClient, Path]:
    """An application with one API route and a pretend Vite build behind it."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Distill</title>", encoding="utf-8")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")

    app = FastAPI()

    @app.get("/api/v1/records")
    async def records() -> dict[str, str]:
        return {"records": "here"}

    settings = Settings(client_dist_dir=dist)
    mount_client(app, settings)
    return TestClient(app), dist


def test_a_client_route_gets_the_shell(tmp_path: Path) -> None:
    """The reload case. `/w/{id}/data` is a route in the browser and nowhere else."""
    client, _ = build(tmp_path)

    response = client.get("/w/33333333-3333-4333-8333-333333333333/data")

    assert response.status_code == 200
    assert "<title>Distill</title>" in response.text


def test_the_api_still_answers_and_still_404s(tmp_path: Path) -> None:
    """The trap this exists to avoid: a mistyped API path returning the HTML shell with a
    200, which reaches the client as a parse error instead of as a missing route."""
    client, _ = build(tmp_path)

    assert client.get("/api/v1/records").json() == {"records": "here"}

    missing = client.get("/api/v1/no-such-thing")
    assert missing.status_code == 404
    assert "<title>" not in missing.text


def test_real_files_are_served_and_hashed_assets_are_cached_hard(tmp_path: Path) -> None:
    client, _ = build(tmp_path)

    asset = client.get("/assets/app-abc123.js")
    assert asset.status_code == 200
    assert asset.text == "console.log(1)"
    assert "immutable" in asset.headers["cache-control"]

    # Not fingerprinted, so not cacheable: it is replaced in place by the next build.
    assert "no-store" in client.get("/favicon.svg").headers["cache-control"]
    assert "no-store" in client.get("/").headers["cache-control"]


def test_nothing_is_mounted_without_a_build(tmp_path: Path) -> None:
    """A backend-only checkout is a normal state, and it must still start."""
    app = FastAPI()
    mount_client(app, Settings(client_dist_dir=tmp_path / "never-built"))

    assert TestClient(app).get("/anything").status_code == 404


@pytest.mark.parametrize(
    "requested",
    ["../secret.txt", "assets/../../secret.txt", "/etc/passwd", "assets/../../../etc/hosts"],
)
def test_a_path_cannot_climb_out_of_the_build_directory(tmp_path: Path, requested: str) -> None:
    """`requested` comes from the URL. Resolving it naively hands out any file this process
    can read, which on a container is most of them."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("not yours", encoding="utf-8")

    assert _resolve(dist, requested.lstrip("/")) is None
