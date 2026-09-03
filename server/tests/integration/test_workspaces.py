"""Workspace creation, authorisation, and the cold-start overview. Requirement FR-01."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_create_workspace_returns_a_token_once(client: AsyncClient) -> None:
    response = await client.post("/api/v1/workspaces", json={"label": "Acme finance"})
    assert response.status_code == 201
    body = response.json()
    assert body["token"]
    assert len(body["token"]) >= 40, "token must carry real entropy"
    assert "token_hash" not in body


async def test_overview_is_empty_but_complete_on_a_fresh_workspace(
    client: AsyncClient, workspace: tuple[str, str], auth: dict[str, str]
) -> None:
    """A cold start must be answerable in one request, even with nothing in it."""
    workspace_id, _ = workspace
    response = await client.get(f"/api/v1/workspaces/{workspace_id}", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] is None, "no schema has been agreed yet"
    assert body["fields"] == []
    assert body["documents"] == []
    assert body["record_count"] == 0
    assert body["last_event_seq"] == 0


async def test_a_wrong_token_is_rejected(
    client: AsyncClient, workspace: tuple[str, str]
) -> None:
    workspace_id, _ = workspace
    response = await client.get(
        f"/api/v1/workspaces/{workspace_id}", headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorised"


async def test_a_missing_workspace_is_indistinguishable_from_a_wrong_token(
    client: AsyncClient, workspace: tuple[str, str], auth: dict[str, str]
) -> None:
    """Telling these apart would let anyone enumerate workspace identifiers.

    The workspace token is the ONLY credential this product has (decision D8), so a valid
    identifier is most of the way to access. Both cases must return the same code and the
    same message.
    """
    workspace_id, _ = workspace
    missing = await client.get(
        "/api/v1/workspaces/00000000-0000-0000-0000-000000000000", headers=auth
    )
    wrong_token = await client.get(
        f"/api/v1/workspaces/{workspace_id}", headers={"Authorization": "Bearer wrong"}
    )
    assert missing.status_code == wrong_token.status_code == 401
    assert missing.json()["error"]["code"] == wrong_token.json()["error"]["code"]
    assert missing.json()["error"]["message"] == wrong_token.json()["error"]["message"]


@pytest.mark.parametrize(
    "header",
    [None, "", "Bearer", "Basic abc", "Bearer  ", "token abc"],
)
async def test_malformed_authorization_headers_are_rejected(
    client: AsyncClient, workspace: tuple[str, str], header: str | None
) -> None:
    workspace_id, _ = workspace
    headers = {} if header is None else {"Authorization": header}
    response = await client.get(f"/api/v1/workspaces/{workspace_id}", headers=headers)
    assert response.status_code == 401


async def test_every_error_carries_a_correlation_identifier(
    client: AsyncClient, workspace: tuple[str, str]
) -> None:
    """The identifier is what turns 'it broke' into a traceable report."""
    response = await client.get(
        f"/api/v1/workspaces/{workspace[0]}", headers={"Authorization": "Bearer wrong"}
    )
    assert response.json()["error"]["request_id"]
    assert response.headers["X-Request-ID"]


async def test_health_reports_the_process_identifier(client: AsyncClient) -> None:
    """Decision D9: exactly one API process, so this value must be visible."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["process_id"], int)
    assert "provider=fake" in body["llm"]["detail"]
    # The key itself must never appear anywhere in a health response.
    assert "api_key" not in response.text.lower()
