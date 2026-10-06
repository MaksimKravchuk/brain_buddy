"""MCP wire-level acceptance for owner-scoped task management."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import allure
import httpx
import pytest
from anyio import to_thread
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.core.config import get_config
from app.repositories.feature_flag import FlagMode
from app.utils.time import utcnow

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Task MCP"),
    allure.story("Authenticated GPT task commands"),
]


@pytest.fixture
def mcp_client(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Iterator[TestClient]:
    monkeypatch.setenv("BRAIN_BUDDY_MCP_ENABLED", "1")
    monkeypatch.setenv("BRAIN_BUDDY_MCP_ALLOWED_HOSTS", "testserver")
    client: TestClient = request.getfixturevalue("api_client")
    flags = client.app.state.container.feature_flag_service
    assert flags.repository.read().flags["task_mcp"].mode is FlagMode.OFF
    flags.set_mode("task_mcp", FlagMode.ON, operator_id="test_operator")
    with client:
        yield client


def _headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("brainbuddy_session")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    }


def _rpc(
    client: TestClient, method: str, params: dict[str, Any] | None = None
) -> httpx.Response:
    return client.post(
        "/api/mcp/",
        headers=_headers(client),
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def _call(client: TestClient, name: str, **arguments: Any) -> dict[str, Any]:
    response = _rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert response.status_code == 200, response.text
    return dict(response.json()["result"])


def _create(client: TestClient, key: str = "create-one") -> dict[str, Any]:
    result = _call(client, "create_task", title="Купить молоко", idempotency_key=key)
    assert not result.get("isError"), result
    return dict(result["structuredContent"])


def test_022_FR_001_sdk_handshake_and_task_roundtrip(mcp_client: TestClient) -> None:
    """022-SC-001: The official client discovers tools and creates, reads and deletes."""

    async def send(request: httpx.Request) -> httpx.Response:
        response = await to_thread.run_sync(
            lambda: mcp_client.request(
                request.method,
                str(request.url),
                headers=dict(request.headers),
                content=request.content,
            )
        )
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )

    async def exercise() -> None:
        async with (
            httpx.AsyncClient(
                headers=_headers(mcp_client), transport=httpx.MockTransport(send)
            ) as http_client,
            streamable_http_client(
                "http://testserver/api/mcp/", http_client=http_client
            ) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "BrainBuddy Tasks"
            tools = (await session.list_tools()).tools
            assert {tool.name for tool in tools} == {
                "list_tasks",
                "get_task",
                "create_task",
                "delete_task",
            }
            annotations = {tool.name: tool.annotations for tool in tools}
            assert annotations["list_tasks"].readOnlyHint is True
            assert annotations["delete_task"].destructiveHint is True
            created = await session.call_tool(
                "create_task",
                {"title": "SDK task", "idempotency_key": "sdk-create"},
            )
            assert created.isError is False
            assert created.structuredContent is not None
            task = created.structuredContent
            read_task = await session.call_tool("get_task", {"task_id": task["id"]})
            assert read_task.structuredContent == task
            deleted = await session.call_tool(
                "delete_task",
                {
                    "task_id": task["id"],
                    "expected_revision": task["revision"],
                    "idempotency_key": "sdk-delete",
                },
            )
            assert deleted.isError is False
            assert deleted.structuredContent["state"] == "cancelled"
            active = await session.call_tool("list_tasks", {})
            assert active.structuredContent["items"] == []

    asyncio.run(exercise())
    assert mcp_client.get("/api/tasks").json()["items"] == []


def test_022_FR_002_create_replay_and_conflict(mcp_client: TestClient) -> None:
    """Identical mutation keys replay once and different arguments fail safely."""
    task = _create(mcp_client)
    assert _create(mcp_client) == task
    conflict = _call(
        mcp_client, "create_task", title="Other title", idempotency_key="create-one"
    )
    assert conflict["isError"] is True
    assert len(mcp_client.get("/api/tasks").json()["items"]) == 1
    assert mcp_client.get(f"/api/tasks/{task['id']}").json()["title"] == "Купить молоко"


def test_022_FR_003_delete_revision_replay_and_recovery(mcp_client: TestClient) -> None:
    """Deletion checks revisions, replays safely and preserves reversible cancellation."""
    task = _create(mcp_client)
    stale = _call(
        mcp_client,
        "delete_task",
        task_id=task["id"],
        expected_revision=2,
        idempotency_key="stale-delete",
    )
    assert stale["isError"] is True
    assert mcp_client.get(f"/api/tasks/{task['id']}").json()["state"] == "inbox"
    args = {
        "task_id": task["id"],
        "expected_revision": 1,
        "idempotency_key": "delete-one",
    }
    deleted = _call(mcp_client, "delete_task", **args)
    assert deleted["structuredContent"]["state"] == "cancelled"
    assert _call(mcp_client, "delete_task", **args) == deleted
    assert _call(mcp_client, "list_tasks")["structuredContent"]["items"] == []
    assert (
        _call(mcp_client, "list_tasks", include_cancelled=True)["structuredContent"][
            "items"
        ][0]["id"]
        == task["id"]
    )
    restored = mcp_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": "restore-one"},
        json={"action": "reopen", "to_state": "inbox", "expected_revision": 2},
    )
    assert restored.status_code == 200
    assert restored.json()["state"] == "inbox"


def test_022_FR_004_owner_isolation(mcp_client: TestClient) -> None:
    """022-SC-002: Two callers share an endpoint without sharing data or receipts."""
    task = _create(mcp_client)
    first_token = mcp_client.cookies.get("brainbuddy_session")
    container = mcp_client.app.state.container
    container.auth_service.seed_admin(
        email="other@example.com", password="OtherPass12345"
    )
    signed_in = mcp_client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "OtherPass12345"},
    )
    assert signed_in.status_code == 200
    assert _call(mcp_client, "list_tasks")["structuredContent"]["items"] == []
    assert _call(mcp_client, "get_task", task_id=task["id"])["isError"] is True
    assert (
        _call(
            mcp_client,
            "delete_task",
            task_id=task["id"],
            expected_revision=1,
            idempotency_key="delete-other",
        )["isError"]
        is True
    )
    other = _create(mcp_client)
    assert other["id"] != task["id"]
    assert _rpc(mcp_client, "tools/list").status_code == 200
    response = mcp_client.post(
        "/api/mcp/",
        headers={**_headers(mcp_client), "Authorization": f"Bearer {first_token}"},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_task", "arguments": {"task_id": task["id"]}},
        },
    )
    assert response.json()["result"]["structuredContent"]["state"] == "inbox"


@pytest.mark.parametrize("authorization", [None, "Bearer invalid", "Basic invalid"])
def test_022_FR_004_reject_missing_auth_and_cookie_only(
    mcp_client: TestClient, authorization: str | None
) -> None:
    """Browser cookies and invalid credentials cannot authenticate MCP requests."""
    headers = {"Accept": "application/json, text/event-stream"}
    if authorization:
        headers["Authorization"] = authorization
    response = mcp_client.post(
        "/api/mcp/",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer ")


def test_022_FR_004_revoke_and_expire_sessions(mcp_client: TestClient) -> None:
    """Logout and session expiry remove access to the MCP endpoint."""
    headers = _headers(mcp_client)
    token = mcp_client.cookies.get("brainbuddy_session")
    container = mcp_client.app.state.container
    session = container.session_repo.get(
        container.auth_service.hash_session_token(token)
    )
    assert session is not None
    container.session_repo.create(
        session.model_copy(update={"expires_at": utcnow() - timedelta(seconds=1)})
    )
    assert mcp_client.post("/api/mcp/", headers=headers, json={}).status_code == 401
    container.session_repo.create(session)
    assert _rpc(mcp_client, "tools/list").status_code == 200
    mcp_client.post("/api/auth/logout")
    assert mcp_client.post("/api/mcp/", headers=headers, json={}).status_code == 401


@pytest.mark.parametrize(
    "arguments",
    [
        {"title": "", "idempotency_key": "invalid"},
        {"title": "Valid", "idempotency_key": ""},
        {"title": "Valid", "idempotency_key": "invalid", "state": "waiting"},
        {"title": "Valid", "idempotency_key": "invalid", "due_date": "not-a-date"},
        {"title": "Valid", "idempotency_key": "invalid", "project_id": "foreign"},
    ],
)
def test_022_FR_005_validation(
    mcp_client: TestClient, arguments: dict[str, Any]
) -> None:
    """Invalid tool arguments never create a task."""
    assert _call(mcp_client, "create_task", **arguments)["isError"] is True
    assert mcp_client.get("/api/tasks").json()["items"] == []


def test_022_FR_005_search_pagination_and_task_fields(mcp_client: TestClient) -> None:
    """Native task fields and opaque list cursors remain usable through MCP."""
    for index in range(3):
        result = _call(
            mcp_client,
            "create_task",
            title=f"Поиск {index}",
            idempotency_key=f"search-{index}",
            details="Details",
            state="waiting",
            waiting_for="Supplier",
            due_date="2026-12-01",
            priority="high",
        )
        assert result["structuredContent"]["waiting_for"] == "Supplier"
        assert result["structuredContent"]["due_date"] == "2026-12-01"
    first = _call(mcp_client, "list_tasks", q="Поиск", state="waiting", limit=2)[
        "structuredContent"
    ]
    assert first["has_more"] is True
    second = _call(
        mcp_client,
        "list_tasks",
        q="Поиск",
        state="waiting",
        limit=2,
        cursor=first["next_cursor"],
    )["structuredContent"]
    assert second["has_more"] is False
    assert len({item["id"] for item in first["items"] + second["items"]}) == 3
    assert _call(mcp_client, "list_tasks", limit=201)["isError"] is True
    assert _call(mcp_client, "unknown_tool")["isError"] is True


def test_022_FR_006_host_origin_and_malformed_requests(mcp_client: TestClient) -> None:
    """The transport rejects unapproved hosts, browser origins and malformed RPC."""
    for extra in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"}):
        response = mcp_client.post(
            "/api/mcp/",
            headers={**_headers(mcp_client), **extra},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code in (403, 421)
    malformed = mcp_client.post(
        "/api/mcp/",
        headers={**_headers(mcp_client), "Content-Type": "application/json"},
        content="not json",
    )
    assert malformed.status_code == 400
    assert _rpc(mcp_client, "tools/list").status_code == 200


def test_022_FR_007_disabled_by_default(api_client: TestClient) -> None:
    """022-SC-003: An unchanged deployment has no MCP endpoint and keeps task routes."""
    assert api_client.post("/api/mcp/", json={}).status_code == 404
    container = api_client.app.state.container
    container.feature_flag_service.set_mode(
        "task_mcp", FlagMode.ON, operator_id="test_operator"
    )
    assert api_client.get("/api/auth/me").json()["feature_flags"]["task_mcp"] is False
    assert api_client.get("/api/tasks").status_code == 200


def test_022_FR_007_config_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only an explicit enable value opts into MCP and host names are trimmed."""
    monkeypatch.setenv("BRAIN_BUDDY_MCP_ENABLED", "true")
    monkeypatch.setenv("BRAIN_BUDDY_MCP_ALLOWED_HOSTS", "example.com, localhost:* ,")
    get_config.cache_clear()
    config = get_config()
    assert config.mcp_enabled is False
    assert config.mcp_allowed_hosts == ["example.com", "localhost:*"]
    get_config.cache_clear()


def test_022_FR_007_selected_cohort_gates_discovery_and_mutations(
    mcp_client: TestClient,
) -> None:
    """Only the selected account can discover and mutate; removal applies immediately."""
    container = mcp_client.app.state.container
    flags = container.feature_flag_service
    user_id = mcp_client.get("/api/auth/me").json()["id"]
    flags.set_mode("task_mcp", FlagMode.OFF, operator_id="test_operator")
    assert _rpc(mcp_client, "tools/list").status_code == 403
    flags.set_mode("task_mcp", FlagMode.SELECTED_USERS, operator_id="test_operator")
    assert _rpc(mcp_client, "tools/list").status_code == 403
    denied = _rpc(
        mcp_client,
        "tools/call",
        {
            "name": "create_task",
            "arguments": {"title": "Denied", "idempotency_key": "denied"},
        },
    )
    assert denied.status_code == 403
    assert mcp_client.get("/api/tasks").json()["items"] == []
    flags.add_selected_user("task_mcp", account_id=user_id, operator_id="test_operator")
    assert mcp_client.get("/api/auth/me").json()["feature_flags"]["task_mcp"] is True
    task = _create(mcp_client)
    flags.remove_selected_user(
        "task_mcp", account_id=user_id, operator_id="test_operator"
    )
    assert _rpc(mcp_client, "tools/list").status_code == 403
    assert mcp_client.get("/api/auth/me").json()["feature_flags"]["task_mcp"] is False
    assert mcp_client.get(f"/api/tasks/{task['id']}").json()["state"] == "inbox"


def test_022_FR_007_degraded_rollout_fails_closed(mcp_client: TestClient) -> None:
    """An unreadable rollout inventory blocks MCP while native tasks remain usable."""
    container = mcp_client.app.state.container
    task = _create(mcp_client)
    with sqlite3.connect(container.feature_flag_repo.db_path) as connection:
        connection.execute(
            "DELETE FROM feature_flags WHERE flag = ?", ("voice_brain_dump",)
        )
    assert _rpc(mcp_client, "tools/list").status_code == 403
    assert mcp_client.get("/api/auth/me").json()["feature_flags"]["task_mcp"] is False
    assert mcp_client.get(f"/api/tasks/{task['id']}").status_code == 200


def test_022_FR_007_rollout_rechecked_before_mutation(
    mcp_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Revocation between HTTP authentication and command execution cannot create a task."""
    container = mcp_client.app.state.container
    get_user = container.auth_service.get_user_for_token
    checks = 0

    def revoke_in_worker(token: str) -> Any:
        nonlocal checks
        checks += 1
        if checks == 2:
            container.feature_flag_service.set_mode(
                "task_mcp", FlagMode.OFF, operator_id="test_operator"
            )
        return get_user(token)

    monkeypatch.setattr(container.auth_service, "get_user_for_token", revoke_in_worker)
    result = _call(
        mcp_client, "create_task", title="Blocked", idempotency_key="blocked"
    )
    assert result["isError"] is True
    assert "unavailable for this account" in str(result)
    assert mcp_client.get("/api/tasks").json()["items"] == []


def test_022_FR_006_safe_failure_and_logs(
    mcp_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected storage errors return a safe error without logging task content."""

    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("secret diagnostic payload")

    monkeypatch.setattr(
        mcp_client.app.state.container.task_service, "create_task", broken
    )
    result = _call(
        mcp_client, "create_task", title="private task title", idempotency_key="broken"
    )
    assert result["isError"] is True
    assert "secret diagnostic payload" not in str(result)
    assert "mcp_tool_failed" in caplog.text
    assert "private task title" not in caplog.text
    assert "secret diagnostic payload" not in caplog.text
