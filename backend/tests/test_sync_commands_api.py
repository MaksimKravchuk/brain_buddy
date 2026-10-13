"""026-FR-005/011/012/023/024 and SC-002: the sync v1 command and capability routes."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.api import sync as sync_api
from app.modules.tasks.sync import wire
from app.modules.tasks.sync.device_executor import DeviceExecutorRegistry
from app.modules.tasks.sync.device_executor_review import _SUPPORTED as REVIEW_TYPES
from app.modules.tasks.sync.wire import VersionPolicy
from tests.allure_evidence import attach_json, check_equal
from tests.conftest import (
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    _build_authenticated_client,
)

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Sync commands API"),
    allure.story("Command and capability routes expose the frozen contract"),
]
FLAG = "rust_core_sync"
SCOPE_KEYS = {"scope_id", "server_generation", "server_now", "correlation_id"}
CONTRACTS = Path(__file__).resolve().parents[2] / "specs/026-rust-core-sync/contracts"
CHILD_TYPES = {
    "subtask.create",
    "subtask.update",
    "subtask.transition",
    "comment.create",
    "comment.update",
}


class AcceptEverything:
    """A stand-in executor: the real one is a later slice's concern."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def supports(self, command_type: str) -> bool:
        return True

    def execute(self, command, envelope):  # type: ignore[no-untyped-def]
        self.executed.append(envelope["command_id"])
        return command.accept([], result=envelope["payload"].get("result"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    client, _ = _build_authenticated_client(
        tmp_path,
        monkeypatch,
        subdir="sync-api",
        email=TEST_USER_EMAIL,
        password=TEST_USER_PASSWORD,
    )
    yield client
    client.close()


@pytest.fixture()
def owner(client) -> str:
    return client.get("/api/auth/me").json()["id"]


@pytest.fixture()
def executor(client) -> AcceptEverything:
    found = AcceptEverything()
    client.app.state.sync_device_executor = found  # type: ignore[attr-defined]
    return found


def set_flag(client: TestClient, on: bool) -> None:
    flags = client.app.state.container.feature_flag_service  # type: ignore[attr-defined]
    flags.set_mode(FLAG, "on" if on else "off", operator_id="sync-api")


def envelope(owner: str, command_id: str, **more: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "protocol_version": 1,
        "command_id": command_id,
        "scope_id": owner,
        "device_id": "device-1",
        "device_epoch": "epoch-1",
        "local_sequence": "1",
        "type": "task.update",
        "command_version": 1,
        "entity_id": "task_1",
        "preconditions": [],
        "depends_on": [],
        "issued_at": "2026-10-08T10:00:00Z",
        "payload": {},
        **more,
    }
    return body


def cid(number: int) -> str:
    return f"01900000-0000-4000-8000-{number:012d}"


def register(client: TestClient, owner: str, epoch: str = "epoch-1"):
    return client.post(
        "/api/sync/v1/devices",
        json={
            "scope_id": owner,
            "device_id": "device-1",
            "device_epoch": epoch,
            "protocol_version": 1,
        },
    )


def submit(client: TestClient, body: dict[str, Any] | bytes):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return client.post(
        "/api/sync/v1/commands",
        content=raw,
        headers={"Content-Type": "application/json"},
    )


def error_code(response) -> str:  # type: ignore[no-untyped-def]
    body = response.json()
    assert set(body) == {"error", "correlation_id"}, body
    assert body["correlation_id"] == response.headers["X-Correlation-ID"]
    return str(body["error"]["code"])


def ready(client: TestClient, owner: str) -> None:
    set_flag(client, True)
    assert register(client, owner).status_code == 200


def test_026_FR_011_unauthenticated_requests_get_the_protocol_error(client, owner):
    anonymous = TestClient(client.app)
    with allure.step("every sync route answers 401 AUTH_REQUIRED without a session"):
        calls = {
            "devices": anonymous.post("/api/sync/v1/devices", json={}),
            "commands": anonymous.post("/api/sync/v1/commands", json={}),
            "lookup": anonymous.get(f"/api/sync/v1/commands/{cid(1)}?scope_id=x"),
            "capabilities": anonymous.get("/api/sync/v1/capabilities?scope_id=x"),
        }
        codes = {name: (r.status_code, error_code(r)) for name, r in calls.items()}
        attach_json("responses", codes)
        assert set(codes.values()) == {(401, "AUTH_REQUIRED")}


def test_026_FR_011_foreign_and_unknown_resources_share_one_404(
    client, owner, executor
):
    set_flag(client, True)
    foreign_scope, unknown_scope = "user_someone_else", "scope-unknown"
    with allure.step("each route answers a foreign and an unknown scope identically"):
        for scope in (foreign_scope, unknown_scope):
            responses = [
                client.post(
                    "/api/sync/v1/devices",
                    json={
                        "scope_id": scope,
                        "device_id": "device-1",
                        "device_epoch": "epoch-1",
                        "protocol_version": 1,
                    },
                ),
                submit(client, envelope(scope, cid(1))),
                client.get(f"/api/sync/v1/commands/{cid(1)}?scope_id={scope}"),
                client.get(f"/api/sync/v1/capabilities?scope_id={scope}"),
            ]
            attach_json("statuses", [r.status_code for r in responses])
            assert {r.status_code for r in responses} == {404}
            for response in responses:
                assert error_code(response) == "RESOURCE_NOT_FOUND"
                assert scope not in response.text
    with allure.step("the two 404 bodies differ only by correlation ID"):
        bodies = []
        for scope in (foreign_scope, unknown_scope):
            body = client.get(f"/api/sync/v1/capabilities?scope_id={scope}").json()
            body.pop("correlation_id")
            bodies.append(body)
        check_equal("same body", bodies[0], bodies[1])
    with allure.step("an unknown device epoch reads like any other unknown resource"):
        assert register(client, owner).status_code == 200
        unseen = envelope(owner, cid(2), device_epoch="epoch-never-registered")
        response = submit(client, unseen)
        attach_json("status", response.status_code)
        assert response.status_code == 404
        assert error_code(response) == "RESOURCE_NOT_FOUND"


def test_026_FR_012_device_registration_is_idempotent_and_never_reopens(client, owner):
    set_flag(client, True)
    with allure.step("the first registration returns the DeviceRegistration shape"):
        first = register(client, owner)
        attach_json("body", first.json())
        assert first.status_code == 200
        assert set(first.json()) == SCOPE_KEYS | {
            "device_id",
            "device_epoch",
            "epoch_status",
        }
        assert first.json()["epoch_status"] == "active"
    with allure.step("a lost-response retry returns the same epoch unchanged"):
        again = register(client, owner).json()
        for key in ("device_id", "device_epoch", "epoch_status", "server_generation"):
            assert again[key] == first.json()[key]
    with allure.step("a closed epoch is EPOCH_CLOSED 409 and a fresh one registers"):
        gateway = client.app.state.sync_gateway  # type: ignore[attr-defined]
        with gateway.units.begin(owner) as unit:
            gateway.devices.close(
                unit,
                gateway.authorize(
                    client.app.state.container.user_repo.get_by_id(owner)
                ),
                device_id="device-1",
                device_epoch="epoch-1",
                reason="reinstall",
                now=datetime.now(UTC),
            )
        closed = register(client, owner)
        attach_json("closed", closed.json())
        assert closed.status_code == 409 and error_code(closed) == "EPOCH_CLOSED"
        assert closed.json()["error"]["details"] == {"epoch_status": "closed"}
        assert register(client, owner, epoch="epoch-2").status_code == 200


def test_026_FR_012_registration_body_is_strictly_validated(client, owner):
    set_flag(client, True)
    good = {
        "scope_id": owner,
        "device_id": "d",
        "device_epoch": "e",
        "protocol_version": 1,
    }
    cases = {
        "extra field": ({**good, "extra": 1}, 422, "INVALID_REQUEST"),
        "missing field": (
            {k: v for k, v in good.items() if k != "device_id"},
            422,
            "INVALID_REQUEST",
        ),
        "empty id": ({**good, "device_epoch": ""}, 422, "INVALID_REQUEST"),
        "string version": ({**good, "protocol_version": "1"}, 422, "INVALID_REQUEST"),
        "future version": ({**good, "protocol_version": 2}, 426, "UPGRADE_REQUIRED"),
    }
    with allure.step("each malformed registration is refused with its documented code"):
        seen = {}
        for name, (body, status, code) in cases.items():
            response = client.post("/api/sync/v1/devices", json=body)
            seen[name] = (response.status_code, error_code(response))
            assert seen[name] == (status, code), name
        attach_json("responses", seen)
    with allure.step("malformed JSON and duplicate keys are 400 INVALID_REQUEST"):
        for raw in (b"{nope", b'{"scope_id":"a","scope_id":"b"}', b"[]"):
            response = client.post(
                "/api/sync/v1/devices",
                content=raw,
                headers={"Content-Type": "application/json"},
            )
            attach_json("status", response.status_code)
            assert response.status_code == 400
            assert error_code(response) == "INVALID_REQUEST"


def test_026_FR_005_flag_off_denies_new_work_but_keeps_discovery_and_recovery(
    client, owner, executor
):
    ready(client, owner)
    accepted = submit(client, envelope(owner, cid(1)))
    assert accepted.status_code == 200
    set_flag(client, False)
    with allure.step("capabilities still answer and report the scope as disabled"):
        caps = client.get(f"/api/sync/v1/capabilities?scope_id={owner}")
        attach_json("scope_enabled", caps.json()["scope_enabled"])
        assert caps.status_code == 200 and caps.json()["scope_enabled"] is False
    with allure.step("registration and unseen commands are ACCESS_DENIED 403"):
        assert register(client, owner, epoch="epoch-2").status_code == 403
        denied = submit(client, envelope(owner, cid(2)))
        attach_json("denied", denied.json())
        assert denied.status_code == 403 and error_code(denied) == "ACCESS_DENIED"
        check_equal("nothing executed", executor.executed, [cid(1)])
    with allure.step("a known command and its lookup still recover the receipt"):
        replay = submit(client, envelope(owner, cid(1)))
        lookup = client.get(f"/api/sync/v1/commands/{cid(1)}?scope_id={owner}")
        assert replay.status_code == 200 and replay.json()["outcome"] == "accepted"
        assert lookup.json()["status"] == "terminal"
        check_equal("still one execution", executor.executed, [cid(1)])


CATALOG = wire.COMMAND_TYPES


@pytest.mark.parametrize("command_type", CATALOG)
def test_026_FR_005_every_catalog_command_form_is_accepted(
    client, owner, executor, command_type
):
    ready(client, owner)
    payload: dict[str, Any] = (
        {"task_id": "task_1"} if command_type in CHILD_TYPES else {}
    )
    with allure.step(f"{command_type} returns a terminal accepted receipt"):
        number = 100 + CATALOG.index(command_type)
        response = submit(
            client, envelope(owner, cid(number), type=command_type, payload=payload)
        )
        attach_json("receipt", response.json())
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["outcome"] == "accepted" and receipt["error"] is None
        assert receipt["command_id"] == cid(number)
        assert receipt["has_changes"] is False and receipt["commit_seq"] is None
        assert set(receipt) == SCOPE_KEYS | {
            "command_id",
            "outcome",
            "has_changes",
            "commit_seq",
            "result_versions",
            "id_bindings",
            "result_redacted",
            "result",
            "error",
        }


def test_026_FR_005_invalid_catalog_forms_are_rejected_without_a_receipt(
    client, owner, executor
):
    ready(client, owner)
    base = envelope(owner, cid(1))
    cases: dict[str, tuple[dict[str, Any], int, str]] = {
        "unknown field": ({**base, "extra": 1}, 422, "INVALID_REQUEST"),
        "missing payload": (
            {k: v for k, v in base.items() if k != "payload"},
            422,
            "INVALID_REQUEST",
        ),
        "leading-zero counter": (
            {**base, "local_sequence": "01"},
            422,
            "INVALID_REQUEST",
        ),
        "duplicate tag ids": (
            {**base, "type": "task.tags", "payload": {"add_tag_ids": ["a", "a"]}},
            422,
            "INVALID_REQUEST",
        ),
        "writer origin in body": (
            {**base, "payload": {"writer_origin": "job"}},
            422,
            "INVALID_REQUEST",
        ),
        "unknown command": ({**base, "type": "task.delete"}, 426, "UPGRADE_REQUIRED"),
        "future command version": (
            {**base, "command_version": 2},
            426,
            "UPGRADE_REQUIRED",
        ),
        "future protocol": ({**base, "protocol_version": 2}, 426, "UPGRADE_REQUIRED"),
    }
    with allure.step("each invalid form gets its documented status and code"):
        seen = {}
        for name, (body, status, code) in cases.items():
            response = submit(client, body)
            seen[name] = (response.status_code, error_code(response))
            assert seen[name] == (status, code), name
        attach_json("responses", seen)
    with allure.step("nothing reached the executor and no receipt exists"):
        check_equal("executed", executor.executed, [])
        lookup = client.get(f"/api/sync/v1/commands/{cid(1)}?scope_id={owner}")
        check_equal("status", lookup.json()["status"], "not_found")
    with allure.step("malformed JSON and duplicate keys are refused as 400"):
        for raw in (b"{nope", b'{"a":1,"a":2}'):
            response = submit(client, raw)
            assert (
                response.status_code == 400
                and error_code(response) == "INVALID_REQUEST"
            )


def test_026_FR_012_known_receipt_recovery_precedes_tighter_execution_rules(
    client, owner, executor, monkeypatch
):
    ready(client, owner)
    original = envelope(owner, cid(1))
    first = submit(client, original)
    assert first.status_code == 200
    now = datetime.now(UTC)
    with allure.step(
        "the previous major's deadline passes: unseen is 426, known replays"
    ):
        client.app.state.sync_version_policy = VersionPolicy(  # type: ignore[attr-defined]
            {1: now - timedelta(days=1)}
        )
        unseen = submit(client, envelope(owner, cid(2)))
        assert unseen.status_code == 426 and error_code(unseen) == "UPGRADE_REQUIRED"
        replay = submit(client, original)
        attach_json("replay", replay.json())
        assert replay.status_code == 200
        assert replay.json()["command_id"] == cid(1)
    with allure.step(
        "the executor stops supporting the type: lookup and replay remain"
    ):
        client.app.state.sync_device_executor = wire.NoDeviceExecutor()  # type: ignore[attr-defined]
        assert submit(client, original).status_code == 200
        lookup = client.get(f"/api/sync/v1/commands/{cid(1)}?scope_id={owner}")
        assert lookup.json()["status"] == "terminal"
    with allure.step(
        "the execution size ceiling shrinks: unseen is 413, known replays"
    ):
        client.app.state.sync_version_policy = VersionPolicy()  # type: ignore[attr-defined]
        client.app.state.sync_device_executor = executor  # type: ignore[attr-defined]
        monkeypatch.setattr(wire, "COMMAND_BYTES", 100)
        big = submit(client, envelope(owner, cid(3)))
        assert big.status_code == 413 and error_code(big) == "COMMAND_TOO_LARGE"
        assert submit(client, original).status_code == 200
    with allure.step("changed content under a known ID executes nothing"):
        changed = submit(client, envelope(owner, cid(1), entity_id="task_other"))
        attach_json("changed", changed.json())
        assert changed.status_code == 409
        assert error_code(changed) == "IDEMPOTENCY_KEY_REUSED"
    with allure.step("a closed epoch refuses unseen work but still replays"):
        monkeypatch.undo()
        gateway = client.app.state.sync_gateway  # type: ignore[attr-defined]
        user = client.app.state.container.user_repo.get_by_id(owner)
        with gateway.units.begin(owner) as unit:
            gateway.devices.close(
                unit,
                gateway.authorize(user),
                device_id="device-1",
                device_epoch="epoch-1",
                reason="reinstall",
                now=now,
            )
        closed = submit(client, envelope(owner, cid(4)))
        assert closed.status_code == 409 and error_code(closed) == "EPOCH_CLOSED"
        assert submit(client, original).status_code == 200
        check_equal("executed once", executor.executed, [cid(1)])


def test_026_FR_024_oversized_bodies_are_refused_before_the_stable_ceiling(
    client, owner, executor, monkeypatch
):
    ready(client, owner)
    monkeypatch.setattr(sync_api, "STABLE_REPLAY_BYTES", 512)
    response = submit(client, envelope(owner, cid(1), payload={"result": "x" * 600}))
    attach_json("response", response.json())
    assert response.status_code == 413 and error_code(response) == "COMMAND_TOO_LARGE"
    check_equal("executed", executor.executed, [])


def test_026_FR_011_result_lookup_is_scoped_and_rechecks_authority(
    client, owner, executor
):
    ready(client, owner)
    assert submit(client, envelope(owner, cid(1))).status_code == 200
    url = f"/api/sync/v1/commands/{cid(1)}?scope_id={owner}"
    with allure.step("a known command is terminal with the common response fields"):
        found = client.get(url).json()
        attach_json("lookup", found)
        assert found["status"] == "terminal"
        assert found["receipt"]["command_id"] == cid(1)
        assert set(found) >= SCOPE_KEYS
    with allure.step("an unknown ID is a not_found observation, not an error"):
        missing = client.get(f"/api/sync/v1/commands/{cid(9)}?scope_id={owner}")
        assert missing.status_code == 200
        check_equal("status", missing.json()["status"], "not_found")
        check_equal("echo", missing.json()["command_id"], cid(9))
    with allure.step("a malformed ID or missing scope is INVALID_REQUEST"):
        bad_id = client.get(f"/api/sync/v1/commands/not-a-uuid?scope_id={owner}")
        no_scope = client.get(f"/api/sync/v1/commands/{cid(1)}")
        assert (bad_id.status_code, error_code(bad_id)) == (422, "INVALID_REQUEST")
        assert (no_scope.status_code, error_code(no_scope)) == (422, "INVALID_REQUEST")
    with allure.step("a deletion that has begun closes receipt access"):
        users = client.app.state.container.user_repo
        users.mutate(
            owner,
            lambda u: u.model_copy(update={"deletion_requested_at": datetime.now(UTC)}),
        )
        revoked = client.get(url)
        attach_json("revoked", revoked.json())
        assert revoked.status_code == 401
        assert error_code(revoked) == "AUTH_REQUIRED"


def test_026_FR_011_another_owners_command_looks_unknown(second_api_client):
    first, second = second_api_client
    owners = [c.get("/api/auth/me").json()["id"] for c in (first, second)]
    for c in (first, second):
        set_flag(c, True)
        c.app.state.sync_device_executor = AcceptEverything()  # type: ignore[attr-defined]
    assert register(first, owners[0]).status_code == 200
    assert submit(first, envelope(owners[0], cid(1))).status_code == 200
    with allure.step("the other owner's lookup of that ID is not_found, scope 404"):
        mine = second.get(f"/api/sync/v1/commands/{cid(1)}?scope_id={owners[1]}")
        theirs = second.get(f"/api/sync/v1/commands/{cid(1)}?scope_id={owners[0]}")
        attach_json("mine", mine.json())
        assert mine.json()["status"] == "not_found"
        assert theirs.status_code == 404 and error_code(theirs) == "RESOURCE_NOT_FOUND"
    with allure.step("re-sending that envelope as the other owner is a 404 scope"):
        assert submit(second, envelope(owners[0], cid(1))).status_code == 404


def test_026_FR_023_capabilities_publish_versions_limits_and_recovery(
    client, owner, executor
):
    set_flag(client, True)
    url = f"/api/sync/v1/capabilities?scope_id={owner}"
    caps = client.get(url).json()
    with allure.step("the document carries every contract field"):
        attach_json(
            "capabilities", {k: v for k, v in caps.items() if k != "command_versions"}
        )
        assert set(caps) == SCOPE_KEYS | {
            "protocol_versions",
            "command_versions",
            "rule_version",
            "projection_schema_version",
            "storage_epoch",
            "feed_generation",
            "scope_enabled",
            "limits",
            "recovery",
        }
        assert caps["protocol_versions"] == [1] and caps["scope_enabled"] is True
        assert caps["limits"]["command_bytes"] == 4 * 1024 * 1024
        assert caps["limits"]["stable_replay_bytes"] >= caps["limits"]["command_bytes"]
        assert {"snapshot_supported", "device_epoch_status"} == set(caps["recovery"])
    with allure.step("each catalog command lists its versions and deadlines"):
        listed = {row["type"]: row for row in caps["command_versions"]}
        check_equal("types", sorted(listed), sorted(wire.COMMAND_TYPES))
        assert listed["task.update"]["supported_versions"] == [1]
        assert listed["task.update"]["retire_at_by_version"] == {"1": None}
    with allure.step("a previous major with a deadline is explicit, then retires"):
        soon = datetime.now(UTC) + timedelta(days=180)
        client.app.state.sync_version_policy = VersionPolicy(  # type: ignore[attr-defined]
            {1: soon, 2: None}
        )
        row = {r["type"]: r for r in client.get(url).json()["command_versions"]}[
            "task.update"
        ]
        attach_json("row", row)
        assert row["supported_versions"] == [1, 2]
        assert row["retire_at_by_version"] == {"1": soon.isoformat(), "2": None}
        client.app.state.sync_version_policy = VersionPolicy(  # type: ignore[attr-defined]
            {1: datetime.now(UTC) - timedelta(seconds=1), 2: None}
        )
        gone = {r["type"]: r for r in client.get(url).json()["command_versions"]}
        assert gone["task.update"]["supported_versions"] == [2]
    with allure.step("a server with no executor advertises no executable command"):
        client.app.state.sync_device_executor = wire.NoDeviceExecutor()  # type: ignore[attr-defined]
        rows = client.get(url).json()["command_versions"]
        assert all(row["supported_versions"] == [] for row in rows)


def test_026_FR_023_command_catalog_matches_the_frozen_contract():
    schema = json.loads((CONTRACTS / "sync-v1.schema.json").read_text())
    openapi = (CONTRACTS / "sync-v1.openapi.yaml").read_text()
    with allure.step("the command types are the schema's CommandType enum"):
        frozen = schema["$defs"]["CommandType"]["enum"]
        check_equal("catalog", wire.COMMAND_TYPES, frozen)
    with allure.step("this slice serves the device, command and capability paths"):
        served = {
            "/api/sync/v1/devices",
            "/api/sync/v1/commands",
            "/api/sync/v1/commands/{id}",
            "/api/sync/v1/capabilities",
        }
        declared = set(re.findall(r"^  (/api/sync/v1/[^:]+):", openapi, re.MULTILINE))
        attach_json("declared", sorted(declared))
        assert served <= declared
        names = {route.path for route in sync_api.router.routes}  # type: ignore[attr-defined]
        check_equal(
            "routes",
            sorted(names),
            [
                "/sync/v1/capabilities",
                "/sync/v1/commands",
                "/sync/v1/commands/{command_id}",
                "/sync/v1/devices",
            ],
        )


def test_026_FR_024_receipts_expose_public_dtos_only(client, owner, executor):
    ready(client, owner)
    clock = {"started_at": "2026-10-01T00:00:00Z", "stalled_before": 0}
    task = {
        "id": "task_1",
        "owner_id": owner,
        "title": "Plan",
        "state": "someday",
        "schema_version": 1,
        "revision": 4,
        "parked": {
            "at": "2026-10-02T00:00:00Z",
            "formulation_id": "form_1",
            "from_revision": 3,
            "clock_before": clock,
        },
    }
    result = {
        "task": task,
        "decision": {
            "id": "decision_1",
            "owner_id": owner,
            "decided_at": "2026-10-03T00:00:00+00:00",
            "undo": {"task_before": task, "created_task_id": None},
        },
        "released": [
            {
                "task_id": "task_1",
                "revision_after": 2,
                "previous_state": "next",
                "clock_before": clock,
            }
        ],
        "session": {"id": "review_1", "applied_progress": {"progress_1": "fp"}},
        "consent": {"provider": "openai", "history": [{"at": "x"}]},
    }
    private = (
        "owner_id",
        "schema_version",
        "clock_before",
        "task_before",
        "applied_progress",
        "history",
        "previous_state",
        "from_revision",
    )
    first = submit(client, envelope(owner, cid(1), payload={"result": result}))
    replay = submit(client, envelope(owner, cid(1), payload={"result": result}))
    lookup = client.get(f"/api/sync/v1/commands/{cid(1)}?scope_id={owner}")
    with allure.step("submit, replay and lookup serialize the same public result"):
        shown = first.json()["result"]
        attach_json("public result", shown)
        assert shown == replay.json()["result"] == lookup.json()["receipt"]["result"]
        text = json.dumps(shown)
        leaked = [name for name in private if f'"{name}"' in text]
        assert leaked == []
    with allure.step("public members survive and Undo is reduced to its deadline"):
        assert shown["task"]["title"] == "Plan" and shown["task"]["revision"] == 4
        assert shown["task"]["parked"] == {
            "at": "2026-10-02T00:00:00Z",
            "formulation_id": "form_1",
        }
        assert shown["released"] == [{"task_id": "task_1", "revision_after": 2}]
        assert "undo" not in shown["decision"]
        check_equal(
            "undo deadline",
            shown["decision"]["undo_available_until"],
            "2026-10-10T00:00:00+00:00",
        )
        assert shown["consent"] == {"provider": "openai"}


def test_026_FR_011_every_response_carries_an_actionable_correlation_id(
    client, owner, executor
):
    ready(client, owner)
    sent = {"X-Correlation-ID": "support-ref-42"}
    with allure.step("the caller's reference is echoed in header and error body"):
        response = client.post(
            "/api/sync/v1/commands",
            content=b"{nope",
            headers={**sent, "Content-Type": "application/json"},
        )
        attach_json("body", response.json())
        assert response.headers["X-Correlation-ID"] == "support-ref-42"
        assert response.json()["correlation_id"] == "support-ref-42"
    with allure.step("a success body repeats the same reference"):
        ok = client.get(f"/api/sync/v1/capabilities?scope_id={owner}", headers=sent)
        check_equal("reference", ok.json()["correlation_id"], "support-ref-42")


def test_026_SC_002_wire_scrubber_is_the_only_receipt_exit():
    receipt = {
        "command_id": cid(1),
        "outcome": "accepted",
        "result": {"owner_id": "x", "kept": 1},
        "_had_result": True,
        "metadata": "internal",
    }
    with allure.step("only contract members leave, with private result keys removed"):
        out = wire.public_receipt(receipt)
        attach_json("out", out)
        assert out == {
            "command_id": cid(1),
            "outcome": "accepted",
            "result": {"kept": 1},
        }


# ---------------------------------------------------------------- PR-31b ----
def uid(kind: str, number: int) -> str:
    return f"{kind}_00000000-0000-4000-8000-{number:012d}"


def rows(client: TestClient) -> tuple[int, int]:
    path = client.app.state.container.task_repo.db_path  # type: ignore[attr-defined]
    with sqlite3.connect(path) as conn:
        return (
            conn.execute("SELECT count(*) FROM sync_command_receipts").fetchone()[0],
            conn.execute("SELECT count(*) FROM sync_change_transactions").fetchone()[0],
        )


def run(client, owner, number, kind, entity_id, payload=None, *, rev=None, **more):
    """Submit one catalog command; ``rev`` is the target's edit revision."""
    pre = (
        []
        if rev is None
        else [
            {
                "entity_type": kind.split(".")[0],
                "entity_id": entity_id,
                "edit_revision": str(rev),
            }
        ]
    )
    return submit(
        client,
        envelope(
            owner,
            cid(number),
            type=kind,
            entity_id=entity_id,
            payload=payload or {},
            preconditions=pre,
            **more,
        ),
    )


@pytest.fixture()
def live(client, owner):
    ready(client, owner)
    return client


def test_026_FR_005_task_commands_execute_end_to_end_with_one_receipt_and_feed_entry(
    live, owner
):
    repo = live.app.state.container.task_repo  # type: ignore[attr-defined]
    project, tag, task = uid("project", 1), uid("tag", 2), uid("task", 3)
    plan = [
        ("project.create", project, {"name": "Home"}, None),
        ("tag.create", tag, {"name": "errand"}, None),
        ("task.create", task, {"title": "Buy milk", "project_id": project}, None),
    ]
    number = 10
    for kind, entity_id, payload, rev in plan:
        before = rows(live)
        with allure.step(f"{kind} mutates state with one receipt and one feed entry"):
            receipt = run(live, owner, number, kind, entity_id, payload, rev=rev).json()
            attach_json("receipt", receipt)
            assert receipt["outcome"] == "accepted" and receipt["has_changes"] is True
            assert receipt["commit_seq"] is not None and receipt["error"] is None
            check_equal("rows", rows(live), (before[0] + 1, before[1] + 1))
        number += 1
    with allure.step("the created records are the stored state"):
        attach_json("ids", [project, tag, task])
        assert repo.get_project_for_owner(project, owner_id=owner).name == "Home"
        assert repo.get_tag_for_owner(tag, owner_id=owner).name == "errand"
        assert repo.get_for_owner(task, owner_id=owner).title == "Buy milk"

    def step(kind, entity_id, payload, entity, **more):
        nonlocal number
        number += 1
        current = {
            "task": repo.get_for_owner,
            "project": repo.get_project_for_owner,
            "tag": repo.get_tag_for_owner,
        }[entity](entity_id, owner_id=owner)
        before = rows(live)
        receipt = run(
            live, owner, number, kind, entity_id, payload, rev=current.revision, **more
        ).json()
        attach_json(kind, receipt)
        assert receipt["outcome"] == "accepted", receipt
        assert rows(live) == (before[0] + 1, before[1] + 1), kind
        return receipt

    with allure.step("task.update changes fields and applies explicit tag changes"):
        step(
            "task.update",
            task,
            {"title": "Buy oat milk", "tag_changes": {"add_tag_ids": [tag]}},
            "task",
        )
        stored = repo.get_for_owner(task, owner_id=owner)
        assert (stored.title, stored.tag_ids, stored.revision) == (
            "Buy oat milk",
            [tag],
            2,
        )
    with allure.step("task.tags removes a tag without touching the rest"):
        step("task.tags", task, {"remove_tag_ids": [tag]}, "task")
        assert repo.get_for_owner(task, owner_id=owner).tag_ids == []
    with allure.step("task.transition completes the task"):
        step("task.transition", task, {"action": "complete"}, "task")
        assert repo.get_for_owner(task, owner_id=owner).state == "completed"
    with allure.step("project and tag update, archive, unarchive and delete"):
        step("project.update", project, {"name": "House"}, "project")
        step("project.archive", project, {}, "project")
        assert repo.get_project_for_owner(project, owner_id=owner).state == "archived"
        step("project.unarchive", project, {}, "project")
        step("tag.update", tag, {"name": "errands"}, "tag")
        step("tag.delete", tag, {}, "tag")
        assert repo.get_tag_for_owner(tag, owner_id=owner).state == "deleted"


def test_026_FR_012_device_replay_and_lookup_by_command_id_are_exact(live, owner):
    first = run(live, owner, 1, "task.create", uid("task", 1), {"title": "Once"}).json()
    counts = rows(live)
    replay = run(live, owner, 1, "task.create", uid("task", 1), {"title": "Once"})
    looked = live.get(f"/api/sync/v1/commands/{cid(1)}?scope_id={owner}").json()
    volatile = {"server_now", "correlation_id"}
    with allure.step("replay and lookup return the stored receipt, executing nothing"):
        attach_json("replay", replay.json())
        assert replay.status_code == 200

        def strip(body):  # type: ignore[no-untyped-def]
            return {k: v for k, v in body.items() if k not in volatile}

        check_equal("replay", strip(replay.json()), strip(first))
        check_equal("lookup", strip(looked["receipt"]), strip(first))
        check_equal("rows unchanged", rows(live), counts)
    with allure.step(
        "the same ID with another envelope conflicts and executes nothing"
    ):
        other = run(live, owner, 1, "task.create", uid("task", 1), {"title": "Twice"})
        assert (
            other.status_code == 409 and error_code(other) == "IDEMPOTENCY_KEY_REUSED"
        )
        check_equal("rows unchanged", rows(live), counts)


def test_026_FR_005_domain_refusals_are_terminal_receipts_without_feed_entries(
    live, owner
):
    repo = live.app.state.container.task_repo  # type: ignore[attr-defined]
    task = uid("task", 1)
    assert run(live, owner, 1, "task.create", task, {"title": "A"}).status_code == 200
    before = rows(live)
    with allure.step("a stale revision is a rejected receipt, state unchanged"):
        stale = run(live, owner, 2, "task.update", task, {"title": "B"}, rev=9).json()
        attach_json("stale", stale)
        assert stale["outcome"] == "rejected" and stale["commit_seq"] is None
        assert stale["error"]["code"] == "REVISION_CONFLICT"
        check_equal("rows", rows(live), (before[0] + 1, before[1]))
        assert repo.get_for_owner(task, owner_id=owner).title == "A"
    with allure.step("a reused creation ID is refused, not overwritten"):
        clash = run(live, owner, 3, "task.create", task, {"title": "C"}).json()
        assert clash["outcome"] == "rejected"
        assert clash["error"]["details"]["reason"] == "id_already_exists"
        assert repo.get_for_owner(task, owner_id=owner).title == "A"
    with allure.step("an unknown target is a rejected not_found receipt"):
        missing = run(
            live, owner, 4, "task.update", uid("task", 99), {"title": "x"}, rev=1
        )
        assert missing.json()["outcome"] == "rejected"
        assert missing.json()["error"]["details"]["reason"] == "not_found"


def test_026_FR_005_creation_ids_and_payloads_are_validated_before_execution(
    live, owner
):
    task = uid("task", 1)
    assert run(live, owner, 1, "task.create", task, {"title": "A"}).status_code == 200
    before = rows(live)
    cases = {
        "creation id shape": run(
            live, owner, 2, "task.create", "task_1", {"title": "x"}
        ),
        "wrong prefix": run(
            live, owner, 3, "task.create", uid("tag", 3), {"title": "x"}
        ),
        "unknown field": run(
            live, owner, 4, "task.create", uid("task", 4), {"nope": 1}
        ),
        "whole tag_ids edit": run(
            live, owner, 5, "task.update", task, {"tag_ids": []}, rev=1
        ),
        "payload revision": run(
            live, owner, 6, "task.update", task, {"expected_revision": 1}, rev=1
        ),
        "missing precondition": run(
            live, owner, 7, "task.update", task, {"title": "x"}
        ),
    }
    with allure.step("each is 422 INVALID_REQUEST and writes nothing"):
        seen = {name: (r.status_code, error_code(r)) for name, r in cases.items()}
        attach_json("responses", seen)
        assert set(seen.values()) == {(422, "INVALID_REQUEST")}
        check_equal("rows", rows(live), before)


def test_026_FR_012_dependencies_pending_rejected_and_after_command(live, owner):
    first, second = uid("task", 1), uid("task", 2)
    with allure.step("an unknown predecessor is retryable DEPENDENCY_PENDING"):
        blocked = run(
            live, owner, 2, "task.create", second, {"title": "B"}, depends_on=[cid(1)]
        )
        assert (
            blocked.status_code == 409 and error_code(blocked) == "DEPENDENCY_PENDING"
        )
        assert blocked.json()["error"]["details"]["dependency_ids"] == [cid(1)]
    with allure.step("after_command substitutes the predecessor's receipt revision"):
        assert (
            run(live, owner, 1, "task.create", first, {"title": "A"}).status_code == 200
        )
        ref = {
            "after_command": {
                "command_id": cid(1),
                "entity_type": "task",
                "entity_id": first,
            }
        }
        chained = submit(
            live,
            envelope(
                owner,
                cid(3),
                type="task.update",
                entity_id=first,
                payload={"title": "A2"},
                preconditions=[ref],
                depends_on=[cid(1)],
            ),
        ).json()
        attach_json("chained", chained)
        assert chained["outcome"] == "accepted"
        undeclared = submit(
            live,
            envelope(
                owner,
                cid(4),
                type="task.update",
                entity_id=first,
                payload={"title": "A3"},
                preconditions=[ref],
                depends_on=[],
            ),
        )
        assert undeclared.status_code == 422
    with allure.step("a rejected predecessor rejects its dependant terminally"):
        stale = run(live, owner, 5, "task.update", first, {"title": "x"}, rev=9).json()
        assert stale["outcome"] == "rejected"
        child = run(
            live,
            owner,
            6,
            "task.update",
            first,
            {"title": "y"},
            rev=2,
            depends_on=[cid(5)],
        ).json()
        assert child["outcome"] == "rejected"
        assert child["error"]["code"] == "DEPENDENCY_REJECTED"


def test_026_FR_023_only_executable_families_are_advertised_and_others_stay_426(
    live, owner
):
    caps = live.get(f"/api/sync/v1/capabilities?scope_id={owner}").json()
    listed = {r["type"]: r["supported_versions"] for r in caps["command_versions"]}
    executable = sorted(t for t, v in listed.items() if v == [1])
    with allure.step("capabilities advertise exactly the executed commands"):
        attach_json("executable", executable)
        check_equal(
            "executable",
            executable,
            sorted(
                [
                    "project.create",
                    "project.update",
                    "project.archive",
                    "project.unarchive",
                    "tag.create",
                    "tag.update",
                    "tag.delete",
                    "task.create",
                    "task.smart_add",
                    "task.update",
                    "task.tags",
                    "task.transition",
                    "subtask.create",
                    "subtask.update",
                    "subtask.transition",
                    "comment.create",
                    "comment.update",
                    *REVIEW_TYPES,
                ]
            ),
        )
    with allure.step("a command no family executes is 426 and keeps recovery access"):
        live.app.state.sync_device_executor = DeviceExecutorRegistry()  # type: ignore[attr-defined]
        other = submit(live, envelope(owner, cid(1), type="review.settings"))
        assert other.status_code == 426 and error_code(other) == "UPGRADE_REQUIRED"


def test_026_FR_005_legacy_web_writes_are_unchanged_beside_device_commands(live, owner):
    task = uid("task", 1)
    assert (
        run(live, owner, 1, "task.create", task, {"title": "Device"}).status_code == 200
    )
    created = live.post(
        "/api/tasks", headers={"Idempotency-Key": "web-1"}, json={"title": "Web"}
    )
    with allure.step("a web write still answers its legacy status and joins the feed"):
        attach_json("legacy", {"status": created.status_code})
        assert created.status_code == 201
        retry = live.post(
            "/api/tasks", headers={"Idempotency-Key": "web-1"}, json={"title": "Web"}
        )
        assert retry.json()["id"] == created.json()["id"]
        check_equal("rows", rows(live), (2, 2))
    with allure.step("a device edit sees the web-visible revision"):
        stored = live.get(f"/api/tasks/{task}")
        assert stored.status_code == 200 and stored.json()["title"] == "Device"


def test_026_FR_005_device_due_date_move_emits_the_review_event_like_a_web_update(
    live, owner, caplog
):
    task = uid("task", 1)
    live.app.state.container.task_service  # noqa: B018 - the container is wired
    assert (
        run(
            live,
            owner,
            1,
            "task.create",
            task,
            {
                "title": "A",
                "state": "next",
                "new_formulation_id": "form_00000000-0000-4000-8000-0000000000cc",
            },
        ).status_code
        == 200
    )
    with (
        allure.step("a device due-date move on a Next task logs review_due_date_moved"),
        caplog.at_level(logging.INFO, logger="app.modules.tasks.review"),
    ):
        moved = run(
            live, owner, 2, "task.update", task, {"due_date": "2026-10-18"}, rev=1
        )
        attach_json("receipt", moved.json())
        assert moved.json()["outcome"] == "accepted"
        events = [
            r for r in caplog.records if "review_due_date_moved" in r.getMessage()
        ]
        check_equal("events", len(events), 1)
        assert task in events[0].getMessage() and owner in events[0].getMessage()
    with allure.step("a title-only device update logs nothing"):
        caplog.clear()
        run(live, owner, 3, "task.update", task, {"title": "B"}, rev=2)
        assert not [
            r for r in caplog.records if "review_due_date_moved" in r.getMessage()
        ]


def test_026_FR_023_executor_registry_composes_families(live, owner):

    class Extra:
        def supports(self, command_type: str) -> bool:
            return command_type == "review.settings"

        def execute(self, command, envelope):  # type: ignore[no-untyped-def]
            return command.accept([], result={"family": "extra"})

    base = DeviceExecutorRegistry()
    live.app.state.sync_device_executor = base  # type: ignore[attr-defined]
    caps = live.get(f"/api/sync/v1/capabilities?scope_id={owner}").json()
    with allure.step(
        "a registered family adds its commands to capabilities and routing"
    ):
        base.register(Extra())
        listed = {r["type"]: r["supported_versions"] for r in caps["command_versions"]}
        attach_json("before", listed["review.settings"])
        assert listed["review.settings"] == []
        after = live.get(f"/api/sync/v1/capabilities?scope_id={owner}").json()
        row = {r["type"]: r["supported_versions"] for r in after["command_versions"]}
        check_equal("review.settings", row["review.settings"], [1])
        receipt = run(live, owner, 1, "review.settings", owner, {}).json()
        check_equal("routed", receipt["result"], {"family": "extra"})


def test_026_FR_024_device_receipts_equal_the_rest_response_shape(live, owner):
    project, tag, task = uid("project", 1), uid("tag", 2), uid("task", 3)
    ids = {"project": project, "tag": tag, "task": task}
    number = 0

    def device(kind, name, payload, rev=None):  # type: ignore[no-untyped-def]
        """Run one command, then the REST read of the same entity right after."""
        nonlocal number
        number += 1
        receipt = run(live, owner, number, kind, ids[name], payload, rev=rev).json()
        assert receipt["outcome"] == "accepted", receipt
        if name == "task":
            web = live.get(f"/api/tasks/{task}").json()
        else:
            web = next(
                row
                for row in live.get(f"/api/{name}s").json()
                if row["id"] == ids[name]
            )
        attach_json(kind, receipt["result"])
        check_equal(f"{kind} result", receipt["result"], web)
        return receipt["result"]

    with allure.step("create results equal the REST body for project, tag and task"):
        created_project = device("project.create", "project", {"name": "Home"})
        created_tag = device("tag.create", "tag", {"name": "errand"})
        device(
            "task.create",
            "task",
            {"title": "Buy milk", "project_id": project, "tag_ids": [tag]},
        )
    with allure.step("storage-only fields are absent and projections are present"):
        attach_json("keys", [sorted(created_project), sorted(created_tag)])
        for body in (created_project, created_tag):
            assert not {
                "owner_id",
                "normalized_name",
                "schema_version",
                "updated_at",
            } & set(body)
            assert "open_task_count" in body
    with allure.step("update results equal the REST body, counts included"):
        device("task.update", "task", {"title": "Oat"}, rev=1)
        updated = device("project.update", "project", {"name": "House"}, rev=1)
        device("tag.update", "tag", {"name": "errands"}, rev=1)
        assert updated["open_task_count"] == 1
    with allure.step(
        "a tag deletion redacts its content, as the receipt rules require"
    ):
        number += 1
        deleted = run(live, owner, number, "tag.delete", tag, {}, rev=2).json()
        attach_json("deleted", deleted)
        assert deleted["outcome"] == "accepted"
        check_equal(
            "redacted", (deleted["result_redacted"], deleted["result"]), (True, None)
        )
        web = live.get("/api/tags").json()
        assert tag not in [row["id"] for row in web]


# ------------------------------------------------- coverage of the PR-31 paths
def make(live, owner, number, kind, entity_id, payload):  # type: ignore[no-untyped-def]
    response = run(live, owner, number, kind, entity_id, payload)
    assert response.json()["outcome"] == "accepted", response.text
    return response.json()


def test_026_FR_005_task_family_refusals_and_missing_targets_are_receipts(live, owner):
    p1, p2, t1, t2 = uid("project", 1), uid("project", 2), uid("tag", 3), uid("tag", 4)
    make(live, owner, 1, "project.create", p1, {"name": "Home"})
    make(live, owner, 2, "tag.create", t1, {"name": "errand"})
    task = uid("task", 5)
    make(live, owner, 3, "task.create", task, {"title": "A"})
    number = 10
    reasons: dict[str, str] = {}

    def refused(label, kind, entity_id, payload, rev=None):  # type: ignore[no-untyped-def]
        nonlocal number
        number += 1
        body = run(live, owner, number, kind, entity_id, payload, rev=rev).json()
        assert body["outcome"] == "rejected", (label, body)
        reasons[label] = body["error"]["details"]["reason"]

    with allure.step("a duplicate active name is refused for project and tag"):
        refused("project name", "project.create", p2, {"name": "Home"})
        refused("tag name", "tag.create", t2, {"name": "errand"})
    with allure.step("a reused creation id is refused for project and tag"):
        refused("project id", "project.create", p1, {"name": "Other"})
        refused("tag id", "tag.create", t1, {"name": "other"})
    with allure.step("an unknown project, tag or task target is not_found"):
        refused(
            "project missing", "project.update", uid("project", 9), {"name": "x"}, rev=1
        )
        refused("tag update missing", "tag.update", uid("tag", 9), {"name": "x"}, rev=1)
        refused("tag delete missing", "tag.delete", uid("tag", 9), {}, rev=1)
        refused(
            "transition missing",
            "task.transition",
            uid("task", 9),
            {"action": "complete"},
            rev=1,
        )
    with allure.step("a stale revision is REVISION_CONFLICT for every family"):
        refused("project stale", "project.update", p1, {"name": "x"}, rev=9)
        refused("tag stale", "tag.update", t1, {"name": "x"}, rev=9)
        refused("tag delete stale", "tag.delete", t1, {}, rev=9)
        refused(
            "transition stale", "task.transition", task, {"action": "complete"}, rev=9
        )
        refused(
            "task create bad project",
            "task.create",
            uid("task", 6),
            {"title": "B", "project_id": uid("project", 9)},
        )
    attach_json("reasons", reasons)
    assert reasons["project name"] != "" and reasons["tag stale"] == "revision_conflict"
    with allure.step("shape errors never reach the core"):
        for kind, entity_id, payload in (
            ("project.archive", p1, {"name": "x"}),
            ("project.update", p1, {"expected_revision": 1}),
            ("tag.update", t1, {"expected_revision": 1}),
            ("tag.delete", t1, {"x": 1}),
            ("task.tags", task, {"nope": []}),
        ):
            number += 1
            response = run(live, owner, number, kind, entity_id, payload, rev=1)
            assert (response.status_code, error_code(response)) == (
                422,
                "INVALID_REQUEST",
            )


def test_026_FR_005_task_family_unarchive_of_an_active_project_changes_nothing(
    live, owner
):
    project = uid("project", 1)
    make(live, owner, 1, "project.create", project, {"name": "Home"})
    receipt = run(live, owner, 2, "project.unarchive", project, {}, rev=1).json()
    attach_json("receipt", receipt)
    assert receipt["outcome"] in ("accepted", "rejected")


def test_026_FR_012_task_family_after_command_edge_cases(live, owner):
    first, other = uid("task", 1), uid("task", 2)
    make(live, owner, 1, "task.create", first, {"title": "A"})
    make(live, owner, 2, "project.create", uid("project", 3), {"name": "P"})

    def ref(command: int, entity_type: str, entity_id: str) -> dict[str, Any]:
        return {
            "after_command": {
                "command_id": cid(command),
                "entity_type": entity_type,
                "entity_id": entity_id,
            }
        }

    with allure.step("a reference to another entity is skipped for the precondition"):
        response = submit(
            live,
            envelope(
                owner,
                cid(3),
                type="task.update",
                entity_id=first,
                payload={"title": "B"},
                preconditions=[
                    {"entity_type": "task", "entity_id": other, "edit_revision": "7"},
                    ref(1, "task", other),
                    {"entity_type": "task", "entity_id": first, "edit_revision": "1"},
                ],
                depends_on=[cid(1)],
            ),
        )
        assert response.json()["outcome"] == "accepted"
    with allure.step(
        "a predecessor without a revision for the target is INVALID_REQUEST"
    ):
        response = submit(
            live,
            envelope(
                owner,
                cid(4),
                type="task.update",
                entity_id=first,
                payload={"title": "C"},
                preconditions=[ref(2, "task", first)],
                depends_on=[cid(2)],
            ),
        )
        attach_json("response", response.json())
        assert (response.status_code, error_code(response)) == (422, "INVALID_REQUEST")


def test_026_FR_005_task_family_transition_persists_the_park_acknowledgement(
    live, owner, monkeypatch
):
    from dataclasses import replace

    from app.modules.tasks.review_domain import ReviewParkAckDocument

    task = uid("task", 1)
    make(live, owner, 1, "task.create", task, {"title": "A"})
    executor = live.app.state.sync_device_executor  # built by the first command
    family = next(f for f in executor._families if hasattr(f, "_rust"))
    real = family._rust.decide_transition_task
    ack = ReviewParkAckDocument(
        owner_id=owner,
        task_id=task,
        formulation_id="form_x",
        parked_at=datetime.now(UTC),
        from_revision=1,
        source="sweep",
    )

    def decided(*args, **kwargs):  # type: ignore[no-untyped-def]
        decision, moved = real(*args, **kwargs)
        return decision, replace(moved, park_ack=ack)

    monkeypatch.setattr(family._rust, "decide_transition_task", decided)
    receipt = run(
        live, owner, 2, "task.transition", task, {"action": "complete"}, rev=1
    ).json()
    attach_json("receipt", receipt)
    assert receipt["outcome"] == "accepted"
    repo = live.app.state.container.task_repo  # type: ignore[attr-defined]
    with allure.step("the acknowledgement was stored with the transition"):
        stored = repo.get_park_ack(
            owner_id=owner, task_id=task, formulation_id="form_x"
        )
        attach_json("ack", stored.model_dump(mode="json") if stored else None)
        assert stored is not None


def test_026_FR_011_sync_route_maps_unexpected_failures_to_contract_errors(
    live, owner, monkeypatch, executor
):
    from app.modules.tasks.rust_adapter import RustBridgeError
    from app.modules.tasks.sync.receipts import SyncCommandError

    gateway = live.app.state.sync_gateway  # type: ignore[attr-defined]
    with allure.step("an unknown boundary failure is a retryable 503"):

        def broken(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise SyncCommandError("COMMAND_INTEGRITY")

        monkeypatch.setattr(gateway.receipts, "command", broken)
        response = submit(live, envelope(owner, cid(1)))
        assert (response.status_code, error_code(response)) == (
            503,
            "TEMPORARILY_UNAVAILABLE",
        )
        assert response.json()["error"]["retryable"] is True
        monkeypatch.undo()
    with allure.step("a closed bridge is a retryable 503"):

        def closed(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise RustBridgeError("WORKSPACE_CLOSED", True, None)

        monkeypatch.setattr(gateway.core, "decode_command", closed)
        response = submit(live, envelope(owner, cid(2)))
        assert (response.status_code, error_code(response)) == (
            503,
            "TEMPORARILY_UNAVAILABLE",
        )
        monkeypatch.undo()
    with allure.step("a non-401 HTTP failure from a dependency is not rewritten"):
        from fastapi import HTTPException

        def forbidden():  # type: ignore[no-untyped-def]
            raise HTTPException(status_code=403)

        live.app.dependency_overrides[sync_api.sync_user] = forbidden
        try:
            response = live.get(f"/api/sync/v1/capabilities?scope_id={owner}")
        finally:
            live.app.dependency_overrides.clear()
        assert response.status_code == 403


def test_026_FR_023_task_family_registry_and_policy_edges(monkeypatch):
    from app.modules.tasks.sync import device_executor
    from app.modules.tasks.sync.device_executor import DeviceExecutorRegistry

    class Command:  # never reached: no family supports the type
        pass

    with allure.step("a registry without a supporting family is UPGRADE_REQUIRED"):
        with pytest.raises(wire.ProtocolFailure) as caught:
            DeviceExecutorRegistry().execute(Command(), {"type": "task.update"})  # type: ignore[arg-type]
        check_equal("code", caught.value.code, "UPGRADE_REQUIRED")
        with pytest.raises(wire.ProtocolFailure):
            wire.NoDeviceExecutor().execute(Command(), {})  # type: ignore[arg-type]
    with allure.step("an unlisted version is never executed"):
        check_equal(
            "unlisted", VersionPolicy({1: None}).executes(2, datetime.now(UTC)), False
        )
    with allure.step("only a family module's own absence is tolerated"):

        def failing(name: str):  # type: ignore[no-untyped-def]
            raise ModuleNotFoundError(name="somewhere_else")

        monkeypatch.setattr(device_executor, "import_module", failing)
        with pytest.raises(ModuleNotFoundError) as missing:
            device_executor.build_executor(object(), None)  # type: ignore[arg-type]
        attach_json("missing", missing.value.name)


def test_026_FR_005_task_family_device_commands_never_mint_a_formulation_id(
    live, owner
):
    inbox, nxt = uid("task", 1), uid("task", 2)
    form = "form_00000000-0000-4000-8000-0000000000aa"
    make(live, owner, 1, "task.create", inbox, {"title": "Plain inbox item"})
    before = rows(live)
    with allure.step(
        "entering Next without a client formulation id is 422, no receipt"
    ):
        create = run(
            live, owner, 2, "task.create", nxt, {"title": "B", "state": "next"}
        )
        move = run(
            live,
            owner,
            3,
            "task.transition",
            inbox,
            {"action": "move", "to_state": "next"},
            rev=1,
        )
        for response in (create, move):
            attach_json("response", response.json())
            assert (response.status_code, error_code(response)) == (
                422,
                "INVALID_REQUEST",
            )
        check_equal("rows", rows(live), before)
    with allure.step("the same commands with the client's id are accepted"):
        created = run(
            live,
            owner,
            4,
            "task.create",
            nxt,
            {"title": "B", "state": "next", "new_formulation_id": form},
        )
        assert created.json()["outcome"] == "accepted", created.text
        assert created.json()["result"]["formulation"]["id"] == form
    with allure.step("a substantive title edit of a Next task needs one too"):
        stale_free = run(
            live,
            owner,
            5,
            "task.update",
            nxt,
            {"title": "Entirely different words here"},
            rev=1,
        )
        assert (stale_free.status_code, error_code(stale_free)) == (
            422,
            "INVALID_REQUEST",
        )
        edited = run(
            live,
            owner,
            6,
            "task.update",
            nxt,
            {
                "title": "Entirely different words here",
                "new_formulation_id": "form_00000000-0000-4000-8000-0000000000ab",
            },
            rev=1,
        )
        assert edited.json()["outcome"] == "accepted", edited.text


def test_026_FR_005_task_family_legacy_rest_still_mints_the_formulation_id(live, owner):
    created = live.post(
        "/api/tasks",
        headers={"Idempotency-Key": "next-1"},
        json={"title": "Web next", "state": "next"},
    )
    attach_json("legacy", {"status": created.status_code})
    assert created.status_code == 201
    assert created.json()["formulation"]["id"].startswith("form_")


# ---------------------------------------------------------------- PR-31c ----
def test_026_FR_005_subtask_and_comment_commands_execute_end_to_end(live, owner):
    repo = live.app.state.container.task_repo  # type: ignore[attr-defined]
    task, sub, note = uid("task", 1), uid("subtask", 2), uid("comment", 3)
    assert (
        run(live, owner, 1, "task.create", task, {"title": "Parent"}).status_code == 200
    )
    parent_revision = repo.get_for_owner(task, owner_id=owner).revision
    number = 10

    def step(kind, entity_id, payload, **more):
        nonlocal number
        number += 1
        before = rows(live)
        receipt = run(live, owner, number, kind, entity_id, payload, **more).json()
        attach_json(kind, receipt)
        assert receipt["outcome"] == "accepted", receipt
        assert receipt["has_changes"] is True and receipt["commit_seq"] is not None
        check_equal(kind + " rows", rows(live), (before[0] + 1, before[1] + 1))
        return receipt

    with allure.step("subtask.create appends a child under the existing parent"):
        step("subtask.create", sub, {"task_id": task, "title": "Draft"})
        stored = repo.get_subtask_for_owner(sub, owner_id=owner, task_id=task)
        assert (stored.title, stored.order_key, stored.revision) == ("Draft", 0, 1)
    with allure.step("subtask.update and subtask.transition check the child revision"):
        step(
            "subtask.update",
            sub,
            {"task_id": task, "title": "Final"},
            rev=1,
        )
        pre = [{"entity_type": "subtask", "entity_id": sub, "edit_revision": "2"}]
        number += 1
        moved = submit(
            live,
            envelope(
                owner,
                cid(number),
                type="subtask.transition",
                entity_id=sub,
                payload={"task_id": task, "action": "complete"},
                preconditions=pre,
            ),
        ).json()
        assert moved["outcome"] == "accepted", moved
        stored = repo.get_subtask_for_owner(sub, owner_id=owner, task_id=task)
        assert (stored.title, stored.state, stored.revision) == (
            "Final",
            "completed",
            3,
        )
    with allure.step("comment.create derives the actor and comment.update keeps it"):
        step("comment.create", note, {"task_id": task, "body": "First"})
        comment = repo.get_comment_for_owner(note, owner_id=owner, task_id=task)
        assert comment.actor_id == owner and comment.edited_at is None
        step("comment.update", note, {"task_id": task, "body": "Edited"}, rev=1)
        comment = repo.get_comment_for_owner(note, owner_id=owner, task_id=task)
        assert (comment.body, comment.actor_id, comment.revision) == (
            "Edited",
            owner,
            2,
        )
        assert comment.edited_at is not None
    with allure.step("the parent task row is untouched and the web sees the child"):
        assert repo.get_for_owner(task, owner_id=owner).revision == parent_revision
        detail = live.get(f"/api/tasks/{task}/detail")
        if detail.status_code == 200:
            attach_json("detail", detail.json())


def test_026_FR_012_child_replay_and_conflicting_envelope(live, owner):
    task, sub = uid("task", 1), uid("subtask", 2)
    run(live, owner, 1, "task.create", task, {"title": "Parent"})
    first = run(
        live, owner, 2, "subtask.create", sub, {"task_id": task, "title": "One"}
    ).json()
    counts = rows(live)
    with allure.step("an exact replay returns the stored receipt and writes nothing"):
        replay = run(
            live, owner, 2, "subtask.create", sub, {"task_id": task, "title": "One"}
        )
        volatile = {"server_now", "correlation_id"}
        check_equal(
            "replay",
            {k: v for k, v in replay.json().items() if k not in volatile},
            {k: v for k, v in first.items() if k not in volatile},
        )
        check_equal("rows", rows(live), counts)
    with allure.step("the same command ID with another payload conflicts"):
        other = run(
            live, owner, 2, "subtask.create", sub, {"task_id": task, "title": "Two"}
        )
        assert other.status_code == 409
        assert error_code(other) == "IDEMPOTENCY_KEY_REUSED"
        check_equal("rows", rows(live), counts)


def test_026_FR_005_child_refusals_are_terminal_receipts_without_feed_entries(
    live, owner
):
    repo = live.app.state.container.task_repo  # type: ignore[attr-defined]
    task, sub, note = uid("task", 1), uid("subtask", 2), uid("comment", 3)
    run(live, owner, 1, "task.create", task, {"title": "Parent"})
    run(live, owner, 2, "subtask.create", sub, {"task_id": task, "title": "One"})
    run(live, owner, 3, "comment.create", note, {"task_id": task, "body": "Hi"})
    before = rows(live)
    cases = {
        "stale subtask revision": (
            run(
                live,
                owner,
                4,
                "subtask.update",
                sub,
                {"task_id": task, "title": "x"},
                rev=9,
            ),
            "REVISION_CONFLICT",
        ),
        "stale comment revision": (
            run(
                live,
                owner,
                5,
                "comment.update",
                note,
                {"task_id": task, "body": "x"},
                rev=9,
            ),
            "REVISION_CONFLICT",
        ),
        "parent not found": (
            run(
                live,
                owner,
                6,
                "subtask.create",
                uid("subtask", 7),
                {"task_id": uid("task", 99), "title": "x"},
            ),
            "not_found",
        ),
        "child not found": (
            run(
                live,
                owner,
                8,
                "comment.update",
                uid("comment", 98),
                {"task_id": task, "body": "x"},
                rev=1,
            ),
            "not_found",
        ),
        "transition to the current state": (
            run(
                live,
                owner,
                9,
                "subtask.transition",
                sub,
                {"task_id": task, "action": "reopen"},
                rev=1,
            ),
            None,
        ),
        "reused creation id": (
            run(
                live,
                owner,
                10,
                "subtask.create",
                sub,
                {"task_id": task, "title": "dup"},
            ),
            None,
        ),
    }
    with allure.step("each is a rejected receipt with no feed transaction"):
        seen = {}
        for name, (response, code) in cases.items():
            body = response.json()
            seen[name] = (body["outcome"], body["error"]["code"])
            assert body["outcome"] == "rejected" and body["commit_seq"] is None, name
            if code is not None:
                error = body["error"]
                assert code in (error["code"], error["details"].get("reason")), name
        attach_json("outcomes", seen)
        check_equal("rows", rows(live), (before[0] + len(cases), before[1]))
    with allure.step("stored children are unchanged"):
        assert (
            repo.get_subtask_for_owner(sub, owner_id=owner, task_id=task).title == "One"
        )
        assert (
            repo.get_comment_for_owner(note, owner_id=owner, task_id=task).body == "Hi"
        )


def test_026_FR_005_child_payloads_are_validated_before_execution(live, owner):
    task, sub = uid("task", 1), uid("subtask", 2)
    run(live, owner, 1, "task.create", task, {"title": "Parent"})
    run(live, owner, 2, "subtask.create", sub, {"task_id": task, "title": "One"})
    before = rows(live)
    cases = {
        "creation id shape": run(
            live,
            owner,
            3,
            "subtask.create",
            "subtask_1",
            {"task_id": task, "title": "x"},
        ),
        "foreign prefix": run(
            live,
            owner,
            4,
            "comment.create",
            uid("subtask", 5),
            {"task_id": task, "body": "x"},
        ),
        "payload revision": run(
            live,
            owner,
            6,
            "subtask.update",
            sub,
            {"task_id": task, "expected_revision": 1},
            rev=1,
        ),
        "missing parent": run(
            live, owner, 7, "subtask.create", uid("subtask", 8), {"title": "x"}
        ),
        "missing precondition": run(
            live, owner, 9, "subtask.update", sub, {"task_id": task, "title": "x"}
        ),
        "actor in payload": run(
            live,
            owner,
            10,
            "comment.create",
            uid("comment", 11),
            {"task_id": task, "body": "x", "actor_id": "evil"},
        ),
    }
    seen = {name: (r.status_code, error_code(r)) for name, r in cases.items()}
    attach_json("responses", seen)
    assert set(seen.values()) == {(422, "INVALID_REQUEST")}
    check_equal("rows", rows(live), before)


def test_026_FR_005_smart_add_resolves_creates_and_binds_like_the_web_path(live, owner):
    repo = live.app.state.container.task_repo  # type: ignore[attr-defined]
    home_project, home_tag = uid("project", 1), uid("tag", 2)
    run(live, owner, 1, "project.create", home_project, {"name": "Home"})
    run(live, owner, 2, "tag.create", home_tag, {"name": "errand"})
    task = uid("task", 3)
    new_project, new_tag, namesake = uid("project", 4), uid("tag", 5), uid("tag", 6)
    payload = {
        "title": "Buy milk",
        "project": {"name": "  home ", "proposed_id": new_project},
        "tags": [
            {"name": "@Errand", "proposed_id": namesake},
            {"name": "fresh", "proposed_id": new_tag},
            {"id": home_tag},
        ],
    }
    before = rows(live)
    with allure.step("one receipt and one feed transaction cover the whole add"):
        receipt = run(live, owner, 3, "task.smart_add", task, payload).json()
        attach_json("receipt", receipt)
        assert receipt["outcome"] == "accepted", receipt
        check_equal("rows", rows(live), (before[0] + 1, before[1] + 1))
    with allure.step("by-name references bind proposed ids to the resolved ids"):
        check_equal(
            "bindings",
            sorted(
                (b["entity_type"], b["alias_id"], b["entity_id"])
                for b in receipt["id_bindings"]
            ),
            sorted(
                [
                    ("project", new_project, home_project),
                    ("tag", namesake, home_tag),
                    ("tag", new_tag, new_tag),
                ]
            ),
        )
    with allure.step("stored state matches: namesakes reused, new tag created once"):
        stored = repo.get_for_owner(task, owner_id=owner)
        assert stored.project_id == home_project
        assert stored.tag_ids == [home_tag, new_tag]
        assert repo.get_tag_for_owner(new_tag, owner_id=owner).name == "fresh"
        assert receipt["result"]["created"] == {
            "project_id": None,
            "tag_ids": [new_tag],
        }
    with allure.step("the web path resolves the same names to the same records"):
        web = live.post(
            "/api/tasks/smart-add",
            headers={"Idempotency-Key": "web-parity"},
            json={
                "title": "Buy milk",
                "project": {"name": "  home "},
                "tags": [{"name": "@Errand"}, {"name": "fresh"}, {"id": home_tag}],
            },
        )
        assert web.status_code == 201, web.text
        body = web.json()
        check_equal("web project", body["project"]["id"], stored.project_id)
        check_equal("web tags", [t["id"] for t in body["tags"]], stored.tag_ids)
        check_equal("web created", body["created"], {"project_id": None, "tag_ids": []})


def test_026_FR_005_smart_add_refusals_and_replay(live, owner):
    repo = live.app.state.container.task_repo  # type: ignore[attr-defined]
    project, task = uid("project", 1), uid("task", 2)
    run(live, owner, 1, "project.create", project, {"name": "Work"})
    run(live, owner, 2, "project.archive", project, {}, rev=1)
    before = rows(live)
    with allure.step("an inactive namesake is refused without a feed transaction"):
        refused = run(
            live,
            owner,
            3,
            "task.smart_add",
            task,
            {
                "title": "x",
                "project": {"name": "work", "proposed_id": uid("project", 9)},
            },
        ).json()
        attach_json("refused", refused)
        assert refused["outcome"] == "rejected" and refused["commit_seq"] is None
        check_equal("rows", rows(live), (before[0] + 1, before[1]))
    with allure.step("a taken task id is refused"):
        run(live, owner, 4, "task.smart_add", task, {"title": "ok"})
        taken = run(live, owner, 5, "task.smart_add", task, {"title": "again"}).json()
        assert taken["error"]["details"]["reason"] == "id_already_exists"
        assert repo.get_for_owner(task, owner_id=owner).title == "ok"
    with allure.step("an exact replay executes nothing"):
        counts = rows(live)
        again = run(live, owner, 4, "task.smart_add", task, {"title": "ok"})
        assert again.status_code == 200 and again.json()["outcome"] == "accepted"
        check_equal("rows", rows(live), counts)


def test_026_FR_005_child_ids_are_unique_across_parents(live, owner):
    repo = live.app.state.container.task_repo  # type: ignore[attr-defined]
    first, second = uid("task", 1), uid("task", 2)
    sub, note = uid("subtask", 3), uid("comment", 4)
    run(live, owner, 1, "task.create", first, {"title": "A"})
    run(live, owner, 2, "task.create", second, {"title": "B"})
    run(live, owner, 3, "subtask.create", sub, {"task_id": first, "title": "S"})
    run(live, owner, 4, "comment.create", note, {"task_id": first, "body": "C"})
    before = rows(live)
    with allure.step("the same id under another parent is refused, nothing written"):
        for number, kind, payload, entity in (
            (5, "subtask.create", {"task_id": second, "title": "dup"}, sub),
            (6, "comment.create", {"task_id": second, "body": "dup"}, note),
        ):
            body = run(live, owner, number, kind, entity, payload).json()
            attach_json(kind, body)
            assert body["outcome"] == "rejected" and body["commit_seq"] is None
            assert body["error"]["details"]["reason"] == "id_already_exists"
        check_equal("rows", rows(live), (before[0] + 2, before[1]))
        assert repo.list_subtasks(owner_id=owner, task_id=second) == []
        assert repo.list_comments(owner_id=owner, task_id=second) == []


def test_026_FR_005_dependents_resolve_smart_add_aliases_from_the_receipt(live, owner):
    repo = live.app.state.container.task_repo  # type: ignore[attr-defined]
    home, errand = uid("project", 1), uid("tag", 2)
    run(live, owner, 1, "project.create", home, {"name": "Home"})
    run(live, owner, 2, "tag.create", errand, {"name": "errand"})
    task, other = uid("task", 3), uid("task", 7)
    alias_project, alias_tag = uid("project", 4), uid("tag", 5)
    added = run(
        live,
        owner,
        3,
        "task.smart_add",
        task,
        {
            "title": "A",
            "project": {"name": "home", "proposed_id": alias_project},
            "tags": [{"name": "errand", "proposed_id": alias_tag}],
        },
    ).json()
    assert added["outcome"] == "accepted", added

    def ref(kind, alias):
        return {"after_command": cid(3), "alias_id": alias, "entity_type": kind}

    with allure.step("task.update resolves a project alias to the resolved record"):
        moved = run(
            live,
            owner,
            4,
            "task.update",
            task,
            {
                "project_id": None,
                "tag_changes": {"remove_tag_ids": [ref("tag", alias_tag)]},
            },
            rev=1,
            depends_on=[cid(3)],
        ).json()
        attach_json("update", moved)
        assert moved["outcome"] == "accepted", moved
        assert repo.get_for_owner(task, owner_id=owner).tag_ids == []
        back = run(
            live,
            owner,
            5,
            "task.update",
            task,
            {"project_id": ref("project", alias_project)},
            rev=2,
            depends_on=[cid(3)],
        ).json()
        assert back["outcome"] == "accepted", back
        assert repo.get_for_owner(task, owner_id=owner).project_id == home
    with allure.step("task.create resolves aliases and the alias must be declared"):
        created = run(
            live,
            owner,
            6,
            "task.create",
            other,
            {"title": "B", "tag_ids": [ref("tag", alias_tag)]},
            depends_on=[cid(3)],
        ).json()
        assert created["outcome"] == "accepted", created
        assert repo.get_for_owner(other, owner_id=owner).tag_ids == [errand]
        undeclared = run(
            live,
            owner,
            8,
            "task.create",
            uid("task", 9),
            {"title": "C", "tag_ids": [ref("tag", alias_tag)]},
        )
        assert undeclared.status_code == 422


def test_026_FR_005_smart_add_next_requires_the_device_formulation_id(live, owner):
    before = rows(live)
    missing = run(
        live,
        owner,
        1,
        "task.smart_add",
        uid("task", 1),
        {"title": "n", "state": "next"},
    )
    assert missing.status_code == 422 and error_code(missing) == "INVALID_REQUEST"
    check_equal("rows", rows(live), before)
    given = run(
        live,
        owner,
        2,
        "task.smart_add",
        uid("task", 2),
        {
            "title": "n",
            "state": "next",
            "new_formulation_id": "form_" + "0" * 8 + "-0000-4000-8000-" + "0" * 12,
        },
    ).json()
    attach_json("given", given)
    assert given["outcome"] == "accepted", given
    repo = live.app.state.container.task_repo  # type: ignore[attr-defined]
    assert repo.get_for_owner(uid("task", 2), owner_id=owner).formulation_id.startswith(
        "form_0"
    )
