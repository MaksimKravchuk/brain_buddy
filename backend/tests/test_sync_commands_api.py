"""026-FR-005/011/012/023/024 and SC-002: the sync v1 command and capability routes."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import allure
import pytest
from fastapi.testclient import TestClient

from app.api import sync as sync_api
from app.modules.tasks.sync import wire
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
