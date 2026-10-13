"""026-FR-005/011: every sync v1 route is mounted in the production app (PR-63).

Endpoint behaviour and its detailed tests belong to the owning PRs (31, 32, 33,
58). This suite only proves what mounting adds on the real ``create_app``:
reachability at the contract path, one shared authorization, the capability-OFF
split between new work and recovery, hidden legacy OpenAPI, and shutdown that
ends open hint streams.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any

import allure
import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.core.config import get_config
from tests.allure_evidence import attach_json, check_equal
from tests.conftest import (
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    _build_authenticated_client,
)

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Sync routes"),
    allure.story("The production app serves every sync v1 route"),
]

FLAG = "rust_core_sync"
GRACE_SECONDS = 2
UNKNOWN = {"scope_id": "scope-unknown"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    client, _ = _build_authenticated_client(
        tmp_path,
        monkeypatch,
        subdir="sync-routes",
        email=TEST_USER_EMAIL,
        password=TEST_USER_PASSWORD,
    )
    set_flag(client, True)
    yield client
    client.close()
    get_config.cache_clear()


@pytest.fixture()
def owner(client) -> str:
    return str(client.get("/api/auth/me").json()["id"])


def set_flag(client: TestClient, on: bool) -> None:
    flags = client.app.state.container.feature_flag_service  # type: ignore[attr-defined]
    flags.set_mode(FLAG, "on" if on else "off", operator_id="sync-routes")


def error_code(response: Any) -> str:
    body = response.json()
    assert set(body) == {"error", "correlation_id"}, body
    return str(body["error"]["code"])


def calls(client: TestClient, scope: str) -> dict[str, Any]:
    """One request per sync route that is scoped by a ``scope_id``."""
    q = {"scope_id": scope}
    return {
        "capabilities": client.get("/api/sync/v1/capabilities", params=q),
        "changes": client.get("/api/sync/v1/changes", params={**q, "cursor": "e30"}),
        "snapshot_create": client.post(
            "/api/sync/v1/snapshots",
            json={**q, "projection_schema_version": "1"},
        ),
        "snapshot_page": client.get(
            "/api/sync/v1/snapshots/snap-x", params={**q, "page_token": "t"}
        ),
        "hints": client.get("/api/sync/v1/hints", params=q),
    }


def test_026_FR_011_every_sync_route_is_mounted_at_its_contract_path(client, owner):
    with allure.step("each contract path answers with the protocol error shape"):
        # A route the app does not serve gives the framework 404 (``detail``); a
        # mounted one answers through ``SyncRoute`` with ``error`` and a
        # correlation id, here for a scope the owner does not hold.
        responses = {
            **calls(client, "scope-unknown"),
            "devices": client.post("/api/sync/v1/devices", json={}),
            "commands": client.post("/api/sync/v1/commands", json={}),
            "lookup": client.get(
                "/api/sync/v1/commands/x", params={"scope_id": "scope-unknown"}
            ),
            "transfer": client.get(
                "/api/sync/v1/transactions/x", params={"page_token": "t"}
            ),
        }
        shapes = {
            name: (r.status_code, sorted(r.json())) for name, r in responses.items()
        }
        attach_json("shapes", shapes)
        for name, (_, keys) in shapes.items():
            assert keys == ["correlation_id", "error"], (name, shapes[name])
    with allure.step("a successful route answers 200 on the same app"):
        caps = client.get("/api/sync/v1/capabilities", params={"scope_id": owner})
        assert caps.status_code == 200
    with allure.step("sync routes stay out of the legacy OpenAPI document"):
        paths = client.get("/api/openapi.json").json()["paths"]
        assert not [p for p in paths if "/sync/" in p]


def test_026_FR_011_every_route_requires_the_session(client, owner):
    anonymous = TestClient(client.app)
    with allure.step("each route answers 401 AUTH_REQUIRED without a session"):
        codes = {
            name: (r.status_code, error_code(r))
            for name, r in calls(anonymous, owner).items()
        }
        attach_json("responses", codes)
        assert set(codes.values()) == {(401, "AUTH_REQUIRED")}, codes
    with allure.step("a transfer route also needs the session"):
        r = anonymous.get("/api/sync/v1/transactions/x", params={"page_token": "t"})
        assert (r.status_code, error_code(r)) == (401, "AUTH_REQUIRED")


def test_026_FR_011_foreign_and_unknown_scope_are_one_404_on_every_route(client):
    with allure.step("a foreign and an unknown scope read the same on every route"):
        foreign = calls(client, "user_someone_else")
        unknown = calls(client, UNKNOWN["scope_id"])
        for name in foreign:
            a, b = foreign[name], unknown[name]
            attach_json(name, [a.status_code, b.status_code])
            assert (a.status_code, error_code(a)) == (404, "RESOURCE_NOT_FOUND"), name
            assert "user_someone_else" not in a.text
            body_a, body_b = a.json(), b.json()
            body_a.pop("correlation_id")
            body_b.pop("correlation_id")
            check_equal(name, body_a, body_b)


def test_026_FR_005_flag_off_denies_new_work_on_every_route_but_keeps_discovery(
    client, owner
):
    set_flag(client, False)
    with allure.step("capabilities still answer and report the scope as disabled"):
        caps = client.get("/api/sync/v1/capabilities", params={"scope_id": owner})
        assert caps.status_code == 200 and caps.json()["scope_enabled"] is False
    with allure.step("feed, snapshots and hints are ACCESS_DENIED 403"):
        responses = calls(client, owner)
        responses.pop("capabilities")
        codes = {n: (r.status_code, error_code(r)) for n, r in responses.items()}
        attach_json("responses", codes)
        assert set(codes.values()) == {(403, "ACCESS_DENIED")}, codes
    with allure.step("turning the flag back on restores service"):
        set_flag(client, True)
        r = client.get("/api/sync/v1/hints", params={"scope_id": "scope-unknown"})
        assert r.status_code == 404


def test_026_FR_023_shutdown_closes_open_hint_streams_promptly(client, owner):
    cookie = "; ".join(f"{c.name}={c.value}" for c in client.cookies.jar)
    server = uvicorn.Server(
        uvicorn.Config(
            client.app,
            host="127.0.0.1",
            port=0,
            log_level="warning",
            timeout_graceful_shutdown=GRACE_SECONDS,
        )
    )
    serving = threading.Thread(target=server.run, daemon=True)
    serving.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "server did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    closed = threading.Event()
    first = threading.Event()
    ended = threading.Event()
    seen: list[int] = []

    def reader() -> None:
        try:
            with (
                httpx.Client(timeout=httpx.Timeout(30.0)) as http,
                http.stream(
                    "GET",
                    f"http://127.0.0.1:{port}/api/sync/v1/hints",
                    params={"scope_id": owner},
                    headers={"Cookie": cookie},
                ) as stream,
            ):
                seen.append(stream.status_code)
                for line in stream.iter_lines():
                    if line.startswith("event:"):
                        first.set()
        except httpx.HTTPError:
            pass
        finally:
            ended.set()

    threading.Thread(target=reader, daemon=True).start()
    try:
        with allure.step("a hint stream is open and has delivered its initial event"):
            assert first.wait(10), seen
            assert seen == [200]
            # The first hints request builds the hub; observe its shutdown call.
            hub = client.app.state.sync_hint_hub  # type: ignore[attr-defined]
            real_close = hub.close

            def spy_close() -> None:
                closed.set()
                real_close()

            hub.close = spy_close
        with allure.step("shutdown ends the stream and the server within a bound"):
            # uvicorn drains connections before the lifespan shutdown runs, so an
            # open SSE stream only ends once the production grace bound expires.
            dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
            text = dockerfile.read_text()
            flag = re.search(r'"--timeout-graceful-shutdown",\s*"(\d+)"', text)
            assert flag is not None and 0 < int(flag.group(1)) <= 30
            started = time.monotonic()
            server.should_exit = True
            serving.join(10)
            elapsed = time.monotonic() - started
            attach_json("shutdown_seconds", round(elapsed, 2))
            assert not serving.is_alive(), "uvicorn is held by the open stream"
            assert elapsed < GRACE_SECONDS + 5
            assert closed.is_set(), "shutdown did not close the hint hub"
            assert ended.wait(5)
    finally:
        server.should_exit = True
        serving.join(5)
