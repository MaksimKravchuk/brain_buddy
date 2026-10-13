"""026-FR-005/010/011/012 and SC-002/SC-007: current authority and epoch fences."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import allure
import pytest
from fastapi.testclient import TestClient

from app.modules.tasks import TaskRepository
from app.modules.tasks.jobs import JobRepository
from app.modules.tasks.jobs.execution import JobExecutionGate
from app.modules.tasks.rust_adapter import RustCore
from app.modules.tasks.sync.authority import (
    IdentityScopeAuthority,
    not_found_response,
    require_scope,
)
from app.modules.tasks.sync.devices import DeviceEpochs
from app.modules.tasks.sync.receipts import (
    CommandRequest,
    ReceiptStore,
    SyncCommandError,
)
from app.modules.tasks.sync.unit_of_work import TaskUnitOfWork
from app.schemas.auth import User
from tests.allure_evidence import attach_json, check_equal
from tests.conftest import (
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    _build_authenticated_client,
)

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Sync authority and device epochs"),
    allure.story("Current authorization fences sync execution"),
]
OWNER = "user_authority"
OTHER = "user_other"
NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)
DEVICE = "device-1"
EPOCH = "epoch-1"


class Users:
    """The Identity read port the authority consults on every call."""

    def __init__(self) -> None:
        self.rows = {
            owner: User(id=owner, email=f"{owner}@example.test", created_at=NOW)
            for owner in (OWNER, OTHER)
        }

    def get_by_id(self, user_id: str) -> User | None:
        return self.rows.get(user_id)

    def revoke(self, owner: str) -> None:
        user = self.rows[owner]
        self.rows[owner] = user.model_copy(update={"deletion_requested_at": NOW})

    def rotate_credentials(self, owner: str) -> None:
        user = self.rows[owner]
        self.rows[owner] = user.model_copy(
            update={"auth_version": user.auth_version + 1}
        )


@pytest.fixture()
def world(data_dir: Path):
    repo = TaskRepository(data_dir)
    uow = TaskUnitOfWork(repo, JobRepository(repo.db_path))
    core = RustCore()
    receipts = ReceiptStore(core)
    users = Users()
    yield repo, uow, receipts, users, DeviceEpochs(receipts)
    core.close()


def device_request(owner=OWNER, command_id=None, device=DEVICE, epoch=EPOCH, **more):
    body = {
        "protocol_version": 1,
        "command_id": command_id or "01900000-0000-4000-8000-000000000001",
        "scope_id": owner,
        "device_id": device,
        "device_epoch": epoch,
        "local_sequence": "1",
        "type": "task.create",
        "command_version": 1,
        "entity_id": "task_first",
        "preconditions": [],
        "depends_on": [],
        "issued_at": NOW.isoformat(),
        "payload": {"title": "Secret title"},
        **more,
    }
    return CommandRequest.device(owner, json.dumps(body).encode())


def register(world, owner=OWNER, device=DEVICE, epoch=EPOCH):
    _, uow, _, users, devices = world
    return devices.register(
        uow,
        owner,
        IdentityScopeAuthority(users),
        device_id=device,
        device_epoch=epoch,
        protocol_version="1",
        now=NOW,
    )


def run_device(world, request, authority=None):
    """One device command: authority, receipt lookup, then the epoch fence."""
    _, uow, receipts, users, devices = world
    authority = authority or IdentityScopeAuthority(users)
    with receipts.command(uow, request, authority, now=NOW) as cmd:
        devices.admit_unseen(cmd)
        if cmd.replay is None:
            cmd.accept([], result={"ok": True})
        return cmd.replay


def count(repo, table):
    with sqlite3.connect(repo.db_path) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608


def test_026_FR_011_revoked_access_cannot_read_a_retained_receipt(world):
    _, uow, receipts, users, _ = world
    register(world)
    run_device(world, device_request())
    authority = IdentityScopeAuthority(users)
    with uow.begin(OWNER) as unit:
        assert receipts.lookup(
            unit, "01900000-0000-4000-8000-000000000001", authority, now=NOW
        )

    users.revoke(OWNER)

    with allure.step("lookup and replay both fail closed after revocation"):
        with uow.begin(OWNER) as unit, pytest.raises(SyncCommandError) as lookup:
            receipts.lookup(
                unit, "01900000-0000-4000-8000-000000000001", authority, now=NOW
            )
        assert lookup.value.code == "RESOURCE_NOT_FOUND"
        with pytest.raises(SyncCommandError) as replay:
            run_device(world, device_request())
        assert replay.value.code == "RESOURCE_NOT_FOUND"


def test_026_FR_011_a_bound_credential_stops_at_the_next_auth_version(world):
    _, uow, receipts, users, _ = world
    register(world)
    run_device(world, device_request())
    bound = IdentityScopeAuthority(users).bound_to(users.rows[OWNER].auth_version)
    users.rotate_credentials(OWNER)
    with uow.begin(OWNER) as unit, pytest.raises(SyncCommandError) as caught:
        receipts.lookup(unit, "01900000-0000-4000-8000-000000000001", bound, now=NOW)
    assert caught.value.code == "RESOURCE_NOT_FOUND"
    with (
        allure.step("unbound legacy writers keep working across a credential change"),
        uow.begin(OWNER) as unit,
    ):
        retained = receipts.lookup(
            unit,
            "01900000-0000-4000-8000-000000000001",
            IdentityScopeAuthority(users),
            now=NOW,
        )
        attach_json("outcome", retained and retained["outcome"])
        assert retained


def test_026_FR_011_generations_come_from_server_state_not_the_caller(world):
    repo, uow, receipts, users, _ = world
    authority = IdentityScopeAuthority(users)
    with uow.begin(OWNER) as unit:
        admitted = receipts.admit(unit, authority)
        stored = authority(unit)
    assert admitted.owner_id == OWNER and admitted.admission_open
    assert all(
        (
            admitted.server_generation,
            admitted.feed_generation,
            admitted.access_generation,
            admitted.storage_epoch,
        )
    )
    with allure.step("later calls return the generations the scope row holds"):
        check_equal("stored equals admitted", stored, admitted)
        check_equal("one scope row", count(repo, "sync_scopes"), 1)


def test_026_FR_010_forged_internal_origin_is_refused(world):
    _, uow, receipts, users, _ = world
    authority = IdentityScopeAuthority(users)
    forged = device_request(payload={"title": "x", "writer_origin": "job"})
    with (
        pytest.raises(SyncCommandError) as caught,
        receipts.command(uow, forged, authority, now=NOW),
    ):
        pytest.fail("a forged origin reached execution")
    assert caught.value.code == "TRUSTED_ORIGIN_REQUIRED"

    jobs = uow._jobs
    jobs.ensure_scheduled(
        job_type="authority.test", dedup_key="claimed", run_at=NOW, scope=OWNER
    )
    lease = jobs.claim_due(
        owner="worker",
        types=("authority.test",),
        now=NOW,
        lease_for=timedelta(minutes=1),
    )
    assert lease is not None
    gate = JobExecutionGate(
        jobs, owner_current=lambda owner: owner == OWNER, now=lambda: NOW
    )
    with (
        allure.step("a device envelope cannot run inside a job execution"),
        gate.executing(lease),
    ):
        with (
            pytest.raises(SyncCommandError) as inside,
            receipts.command(uow, device_request(), authority, now=NOW),
        ):
            pytest.fail("a device request ran as a job")
        attach_json("code", inside.value.code)
        assert inside.value.code == "TRUSTED_ORIGIN_REQUIRED"


def test_026_FR_012_closed_epoch_rejects_unseen_but_replays_known(world):
    repo, uow, _, users, devices = world
    register(world)
    first = run_device(world, device_request())
    assert first is None

    with uow.begin(OWNER) as unit:
        devices.close(
            unit,
            IdentityScopeAuthority(users),
            device_id=DEVICE,
            device_epoch=EPOCH,
            reason="reinstall",
            now=NOW,
        )

    with allure.step("the retained envelope still returns its receipt"):
        replay = run_device(world, device_request())
        attach_json("replay", replay and replay["outcome"])
        assert replay is not None and replay["outcome"] == "accepted"
    with allure.step("an unseen command from the closed epoch executes nothing"):
        before = count(repo, "sync_command_receipts")
        unseen = device_request(command_id="01900000-0000-4000-8000-000000000002")
        with pytest.raises(SyncCommandError) as caught:
            run_device(world, unseen)
        assert caught.value.code == "EPOCH_CLOSED"
        assert count(repo, "sync_command_receipts") == before
    with allure.step("revocation still beats the retained replay"):
        users.revoke(OWNER)
        with pytest.raises(SyncCommandError) as revoked:
            run_device(world, device_request())
        attach_json("code", revoked.value.code)
        assert revoked.value.code == "RESOURCE_NOT_FOUND"


def test_026_FR_012_lost_registration_response_is_idempotent_and_never_reopens(world):
    repo, uow, _, users, devices = world
    first = register(world)
    again = register(world)
    assert first["epoch_status"] == "active"
    for key in ("device_id", "device_epoch", "epoch_status", "server_generation"):
        assert again[key] == first[key]
    assert count(repo, "sync_device_epochs") == 1

    with uow.begin(OWNER) as unit:
        devices.close(
            unit,
            IdentityScopeAuthority(users),
            device_id=DEVICE,
            device_epoch=EPOCH,
            reason="reinstall",
            now=NOW,
        )
    with allure.step("registering the closed ID again is refused"):
        with pytest.raises(SyncCommandError) as caught:
            register(world)
        attach_json("code", caught.value.code)
        assert caught.value.code == "EPOCH_CLOSED"
    with allure.step("a fresh epoch registers beside it for the same device"):
        fresh = register(world, epoch="epoch-2")
        check_equal("fresh epoch is active", fresh["epoch_status"], "active")
        check_equal("both epochs retained", count(repo, "sync_device_epochs"), 2)


def test_026_FR_010_registration_requires_current_identity_access(world):
    repo, _, _, users, _ = world
    users.revoke(OWNER)
    with pytest.raises(SyncCommandError) as caught:
        register(world)
    assert caught.value.code == "RESOURCE_NOT_FOUND"
    assert count(repo, "sync_device_epochs") == 0


def test_026_FR_011_unknown_and_foreign_ids_share_one_owner_safe_404(world):
    _, uow, receipts, users, devices = world
    register(world)
    authority = IdentityScopeAuthority(users)

    def failure(action):
        with pytest.raises(SyncCommandError) as caught:
            action()
        return caught.value.code, str(caught.value)

    with allure.step("device: foreign owner's ID is the same as an unknown ID"):
        foreign_device = failure(lambda: run_device(world, device_request(owner=OTHER)))
        unknown_device = failure(
            lambda: run_device(world, device_request(owner=OTHER, device="device-nope"))
        )
        check_equal(
            "foreign device equals unknown device", foreign_device, unknown_device
        )
        assert foreign_device[0] == "RESOURCE_NOT_FOUND"
        with pytest.raises(SyncCommandError) as rebind:
            register(world, owner=OTHER)
        assert rebind.value.code == "RESOURCE_NOT_FOUND"
    with allure.step("scope: a foreign scope is the same as an unknown scope"):
        foreign_scope = failure(lambda: require_scope(OWNER, OTHER))
        unknown_scope = failure(lambda: require_scope(OWNER, "scope-unknown"))
        check_equal("foreign scope equals unknown scope", foreign_scope, unknown_scope)
    with allure.step("every kind of missing resource builds the identical response"):
        status, body = not_found_response()
        attach_json("owner-safe 404", {"status": status, "body": body})
        check_equal("stable body", not_found_response(), (status, body))
        assert status == 404
        assert set(body) == {"error", "message", "correlation_id"}
        assert body["error"] == "RESOURCE_NOT_FOUND"
    with allure.step("authorized scope: another owner's command looks unknown"):
        run_device(world, device_request())
        with uow.begin(OTHER) as unit:
            foreign_command = receipts.lookup(
                unit, "01900000-0000-4000-8000-000000000001", authority, now=NOW
            )
            unknown_command = receipts.lookup(
                unit, "01900000-0000-4000-8000-0000000000ff", authority, now=NOW
            )
        assert foreign_command is None and unknown_command is None


@pytest.fixture()
def flagged_client(tmp_path, monkeypatch):
    client, _ = _build_authenticated_client(
        tmp_path,
        monkeypatch,
        subdir="authority-wiring",
        email=TEST_USER_EMAIL,
        password=TEST_USER_PASSWORD,
    )
    yield client
    client.close()


def _sync_rows(client: TestClient) -> tuple[int, int]:
    path = client.app.state.container.task_repo.db_path  # type: ignore[attr-defined]
    with sqlite3.connect(path) as conn:
        return (
            conn.execute("SELECT count(*) FROM sync_command_receipts").fetchone()[0],
            conn.execute("SELECT count(*) FROM sync_change_transactions").fetchone()[0],
        )


def test_026_FR_005_production_app_publishes_receipt_and_feed_only_when_flag_on(
    flagged_client,
):
    flags = flagged_client.app.state.container.feature_flag_service  # type: ignore[attr-defined]
    with allure.step("flag OFF: a web write publishes neither receipt nor feed"):
        response = flagged_client.post(
            "/api/tasks", headers={"Idempotency-Key": "off-1"}, json={"title": "Off"}
        )
        assert response.status_code == 201, response.text
        assert _sync_rows(flagged_client) == (0, 0)
    with allure.step("flag ON: the real authority admits the writer"):
        flags.set_mode("rust_core_sync", "on", operator_id="authority")
        response = flagged_client.post(
            "/api/tasks", headers={"Idempotency-Key": "on-1"}, json={"title": "On"}
        )
        assert response.status_code == 201, response.text
        assert _sync_rows(flagged_client) == (1, 1)
    with allure.step("a same-key retry replays instead of writing again"):
        retry = flagged_client.post(
            "/api/tasks", headers={"Idempotency-Key": "on-1"}, json={"title": "On"}
        )
        assert retry.status_code in (200, 201)
        assert retry.json()["id"] == response.json()["id"]
        assert _sync_rows(flagged_client) == (1, 1)


def test_026_FR_012_a_malformed_or_stale_epoch_never_admits_a_new_command(world):
    _, uow, receipts, users, devices = world
    register(world)
    authority = IdentityScopeAuthority(users)
    with allure.step("an envelope without device fields is an invalid request"):
        with (
            pytest.raises(SyncCommandError) as missing,
            receipts.command(
                uow,
                device_request(command_id="01900000-0000-4000-8000-000000000003"),
                authority,
                now=NOW,
            ) as cmd,
        ):
            devices.admit_unseen(
                _Bare(cmd.replay, cmd.request, cmd.unit, cmd.authority, b"{}")
            )
        attach_json("code", missing.value.code)
        assert missing.value.code == "INVALID_REQUEST"
    with allure.step("a registration made under another server generation resets"):
        with uow.begin(OWNER) as unit:
            unit.connection.execute(
                "UPDATE sync_device_epochs SET server_generation = 'older'"
            )
        with pytest.raises(SyncCommandError) as stale:
            run_device(
                world,
                device_request(command_id="01900000-0000-4000-8000-000000000004"),
            )
        attach_json("code", stale.value.code)
        assert stale.value.code == "RESET_REQUIRED"
    with allure.step("registration refuses an empty identifier"):
        with pytest.raises(SyncCommandError) as empty:
            register(world, device="")
        attach_json("code", empty.value.code)
        assert empty.value.code == "INVALID_REQUEST"
    with allure.step("closing twice keeps the first reason"):
        with uow.begin(OWNER) as unit:
            for reason in ("first", "second"):
                devices.close(
                    unit,
                    authority,
                    device_id=DEVICE,
                    device_epoch=EPOCH,
                    reason=reason,
                    now=NOW,
                )
            kept = unit.connection.execute(
                "SELECT close_reason FROM sync_device_epochs"
            ).fetchone()[0]
        check_equal("close reason", kept, "first")


class _Bare:
    """The slice of a receipt command ``admit_unseen`` reads, with a bare wire."""

    def __init__(self, replay, request, unit, authority, wire):
        self.replay, self.unit, self.authority = replay, unit, authority
        self.request = type("Request", (), {"origin": request.origin, "wire": wire})()


def test_026_FR_005_unarchiving_an_unknown_project_is_not_found_with_the_flag_on(
    flagged_client,
):
    flags = flagged_client.app.state.container.feature_flag_service  # type: ignore[attr-defined]
    flags.set_mode("rust_core_sync", "on", operator_id="authority")
    with allure.step("the legacy 404 survives the receipt boundary"):
        response = flagged_client.post(
            "/api/projects/project_missing/unarchive",
            headers={"Idempotency-Key": "missing-1"},
            json={"expected_revision": 1},
        )
        attach_json("response", {"status": response.status_code})
        assert response.status_code == 404, response.text


def test_026_FR_010_deletion_begun_refuses_writes_but_admits_retention_cleanup(world):
    repo, uow, receipts, users, _ = world
    authority = IdentityScopeAuthority(users)
    users.revoke(OWNER)
    with allure.step("a normal write is refused before any mutation"):
        with (
            pytest.raises(SyncCommandError) as refused,
            receipts.command(
                uow,
                CommandRequest.legacy(OWNER, "k", "task.create", {}),
                authority,
                now=NOW,
            ),
        ):
            pytest.fail("a deleting owner reached execution")
        attach_json("code", refused.value.code)
        assert refused.value.code == "RESOURCE_NOT_FOUND"
        check_equal("no scope row", count(repo, "sync_scopes"), 0)
    with allure.step("a retention cleanup unit is admitted"):
        with uow.begin(OWNER, cleanup=True) as unit:
            admitted = receipts.admit(unit, authority)
        check_equal("cleanup admitted", admitted.owner_id, OWNER)
    with allure.step("receipts.command(cleanup=True) publishes for that owner"):
        retention = CommandRequest.legacy(OWNER, "retention", "task.create", {})
        with receipts.command(uow, retention, authority, now=NOW, cleanup=True) as cmd:
            published = cmd.accept([], result={"ok": True})
        check_equal("cleanup receipt", published["outcome"], "accepted")
        check_equal("receipt stored", count(repo, "sync_command_receipts"), 1)
    with allure.step("cleanup never admits an owner that does not exist"):
        users.rows.pop(OWNER)
        with (
            uow.begin(OWNER, cleanup=True) as unit,
            pytest.raises(SyncCommandError) as gone,
        ):
            receipts.admit(unit, authority)
        attach_json("code", gone.value.code)
        assert gone.value.code == "RESOURCE_NOT_FOUND"
