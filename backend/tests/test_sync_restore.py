"""026-FR-005/010/011/015 and SC-002/SC-007: restore replays the control ledger."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import allure
import pytest

from app.modules.tasks import TaskRepository
from app.modules.tasks.jobs import JobRepository
from app.modules.tasks.rust_adapter import RustCore
from app.modules.tasks.sync.authority import IdentityScopeAuthority
from app.modules.tasks.sync.control_ledger import (
    HORIZON,
    ControlLedger,
    LedgerIncomplete,
)
from app.modules.tasks.sync.devices import DeviceEpochs
from app.modules.tasks.sync.receipts import (
    CommandRequest,
    ReceiptStore,
    SyncCommandError,
)
from app.modules.tasks.sync.restore import (
    INCIDENT,
    RestoreNotReady,
    reopen,
    restore_control_plane,
)
from app.modules.tasks.sync.unit_of_work import TaskUnitOfWork
from app.schemas.auth import User
from app.utils.time import utcnow
from tests.allure_evidence import attach_json, check_equal
from tests.conftest import TEST_USER_PASSWORD
from tests.test_account_deletion import _backdate_deletion, _container, _user_id

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Sync backup restore"),
    allure.story("Restore replays an independent deletion and revocation ledger"),
]
GONE, KEPT = "user_purged", "user_kept"
T0 = datetime(2026, 10, 12, 12, tzinfo=UTC)
COMMAND = "01900000-0000-4000-8000-000000000001"


class Users:
    def get_by_id(self, user_id: str) -> User | None:
        return User(id=user_id, email=f"{user_id}@example.test", created_at=T0)


class Sessions:
    """Records restore-time purge and session revocation instead of calling Identity."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir, self.revoked, self.purged = data_dir, [], []

    def purge_owner(self, owner_id: str) -> None:
        self.purged.append(owner_id)
        TaskRepository(self.data_dir).delete_all_for_owner(owner_id=owner_id)

    def revoke_sessions(self, owner_id: str) -> None:
        self.revoked.append(owner_id)


class World:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.repo = TaskRepository(data_dir)
        self.uow = TaskUnitOfWork(self.repo, JobRepository(self.repo.db_path))
        self.core = RustCore()
        self.receipts = ReceiptStore(self.core)
        self.ledger = ControlLedger(data_dir / "control.sqlite3", now=T0)
        self.devices = DeviceEpochs(self.receipts, self.ledger)
        self.authority = IdentityScopeAuthority(Users())
        self.effects: list[str] = []

    def register(self, owner: str, epoch: str = "epoch-1") -> dict:
        return self.devices.register(
            self.uow,
            owner,
            self.authority,
            device_id=f"device-{owner}",
            device_epoch=epoch,
            protocol_version="1",
            now=T0,
        )

    def request(self, owner: str, command_id: str, epoch: str = "epoch-1"):
        body = {
            "protocol_version": 1,
            "command_id": command_id,
            "scope_id": owner,
            "device_id": f"device-{owner}",
            "device_epoch": epoch,
            "local_sequence": "1",
            "type": "task.create",
            "command_version": 1,
            "entity_id": "task_first",
            "preconditions": [],
            "depends_on": [],
            "issued_at": T0.isoformat(),
            "payload": {"title": "Secret title"},
        }
        return CommandRequest.device(owner, json.dumps(body).encode())

    def run(self, owner: str, command_id: str = COMMAND, epoch: str = "epoch-1"):
        request = self.request(owner, command_id, epoch)
        with self.receipts.command(self.uow, request, self.authority, now=T0) as cmd:
            self.devices.admit_unseen(cmd)
            if cmd.replay is None:
                self.effects.append(command_id)  # the internal effect
                cmd.accept([], result={"ok": True})
            return cmd.replay

    def snapshot(self) -> Path:
        """A consistent task backup, as a separate file."""
        target = self.data_dir / "backup.sqlite3"
        with (
            closing(sqlite3.connect(self.repo.db_path)) as src,
            closing(sqlite3.connect(target)) as dst,
        ):
            src.backup(dst)
        return target

    def roll_back_to(self, backup: Path) -> None:
        """Disaster: the live task DB is replaced by the older backup, in place."""
        with (
            closing(sqlite3.connect(backup)) as src,
            closing(sqlite3.connect(self.repo.db_path)) as dst,
        ):
            src.backup(dst)

    def rows(self, sql: str, *args: object) -> list[tuple]:
        with closing(sqlite3.connect(self.repo.db_path)) as conn:
            return [tuple(r) for r in conn.execute(sql, args)]

    def close(self) -> None:
        self.core.close()


@pytest.fixture()
def world(data_dir: Path):
    found = World(data_dir)
    yield found
    found.close()


def seeded(world: World) -> Path:
    """Two owners with a device and one executed command each, then a backup."""
    for owner in (GONE, KEPT):
        world.register(owner)
        world.run(owner, COMMAND)
    return world.snapshot()


def test_026_FR_012_an_epoch_from_before_a_generation_change_cannot_loop(world):
    world.register(KEPT)
    with world.uow.begin(KEPT) as unit:
        unit.connection.execute("UPDATE sync_scopes SET server_generation = 'g2'")
    with allure.step("the old epoch's command answers RESET_REQUIRED"):
        with pytest.raises(SyncCommandError) as reset:
            world.run(KEPT, "01900000-0000-4000-8000-000000000002")
        check_equal("code", reset.value.code, "RESET_REQUIRED")
    with allure.step("registering it again is EPOCH_CLOSED, not active forever"):
        with pytest.raises(SyncCommandError) as closed:
            world.register(KEPT)
        check_equal("code", closed.value.code, "EPOCH_CLOSED")
        status = world.rows("SELECT status, close_reason FROM sync_device_epochs")
        check_equal("persisted closure", status, [("closed", "generation_changed")])
    with allure.step("a fresh epoch registers and executes"):
        check_equal("fresh", world.register(KEPT, "epoch-2")["epoch_status"], "active")
        world.run(KEPT, "01900000-0000-4000-8000-000000000003", "epoch-2")
        check_equal("effects", world.effects, ["01900000-0000-4000-8000-000000000003"])


def test_026_FR_015_restore_does_not_resurrect_a_purged_account(world):
    backup = seeded(world)
    effects = Sessions(world.data_dir)
    with allure.step("the purge is recorded, then the DB rolls back to the backup"):
        world.ledger.record_purge(GONE, now=T0 + timedelta(hours=1))
        TaskRepository(world.data_dir).delete_all_for_owner(owner_id=GONE)
        world.roll_back_to(backup)
        check_equal(
            "backup resurrected it", len(world.rows("SELECT * FROM sync_scopes")), 2
        )
    report = restore_control_plane(
        world.repo.db_path,
        world.ledger,
        effects,
        backup_taken_at=T0,
        now=T0 + timedelta(hours=2),
    )
    with allure.step("the purged owner is gone and nothing else is served"):
        owners = [r[0] for r in world.rows("SELECT owner_id FROM sync_scopes")]
        attach_json("report", report.outcome)
        check_equal("owners", owners, [KEPT])
        check_equal("purged", report.purged, (GONE,))
        check_equal(
            "devices", world.rows("SELECT owner_id FROM sync_devices"), [(KEPT,)]
        )
        check_equal(
            "closed", world.rows("SELECT admission_open FROM sync_scopes"), [(0,)]
        )


def test_026_FR_011_restore_replays_revocations_and_revokes_uncertain_sessions(world):
    backup = seeded(world)
    effects = Sessions(world.data_dir)
    world.ledger.record_revocation(KEPT, 3, now=T0 + timedelta(hours=1))
    world.roll_back_to(backup)
    report = restore_control_plane(
        world.repo.db_path,
        world.ledger,
        effects,
        backup_taken_at=T0,
        now=T0 + timedelta(hours=2),
    )
    with allure.step("every owner of the image must sign in again"):
        attach_json("revoked", sorted(effects.revoked))
        assert {GONE, KEPT} <= set(effects.revoked)
        check_equal("recorded revocation", report.revoked, (KEPT,))
    with allure.step("restored scopes get new generations and closed epochs"):
        check_equal("epochs", report.closed_epochs, 2)
        check_equal(
            "all closed",
            world.rows("SELECT DISTINCT status, close_reason FROM sync_device_epochs"),
            [("closed", "restore")],
        )


def test_026_FR_010_restore_is_an_incident_and_access_reopens_only_after_reconcile(
    world,
):
    backup = seeded(world)
    world.run(KEPT, "01900000-0000-4000-8000-000000000009")  # a confirmed commit
    before = world.rows("SELECT server_generation, feed_generation FROM sync_scopes")
    world.roll_back_to(backup)  # ...lost by the rollback
    report = restore_control_plane(
        world.repo.db_path,
        world.ledger,
        Sessions(world.data_dir),
        backup_taken_at=T0,
        now=T0 + timedelta(hours=2),
    )
    with allure.step("never an ordinary successful reset"):
        check_equal("outcome", report.outcome, INCIDENT)
        after = world.rows("SELECT server_generation, feed_generation FROM sync_scopes")
        assert all(a != b for a, b in zip(after[0], before[0], strict=True))
    with allure.step("closed access refuses a read until reconciled"):
        with pytest.raises(SyncCommandError) as closed, world.uow.begin(KEPT) as unit:
            world.receipts.admit(unit, world.authority)
        check_equal("code", closed.value.code, "RESOURCE_NOT_FOUND")
        with pytest.raises(RestoreNotReady):
            reopen(world.repo.db_path, world.ledger, external_effects_reconciled=False)
    with allure.step("after reconciliation the owner is admitted with new generations"):
        reopen(world.repo.db_path, world.ledger, external_effects_reconciled=True)
        with world.uow.begin(KEPT) as unit:
            admitted = world.receipts.admit(unit, world.authority)
        assert admitted.server_generation != before[0][0]


def test_026_FR_005_restored_receipts_never_repeat_an_internal_effect(world):
    backup = seeded(world)
    world.roll_back_to(backup)
    restore_control_plane(
        world.repo.db_path,
        world.ledger,
        Sessions(world.data_dir),
        backup_taken_at=T0,
        now=T0 + timedelta(hours=2),
    )
    reopen(world.repo.db_path, world.ledger, external_effects_reconciled=True)
    with allure.step("the retained receipt replays; the effect ran once"):
        replay = world.run(KEPT, COMMAND)
        attach_json("replay", replay and replay["outcome"])
        assert replay is not None
        check_equal("effects", world.effects.count(COMMAND), 2)  # seeded x2 owners
        check_equal("kept owner executed once", len(world.effects), 2)


def test_026_FR_015_unprovable_completeness_keeps_access_closed(world):
    backup = seeded(world)
    effects = Sessions(world.data_dir)
    for moment in (1, 2, 3):
        world.ledger.record_revocation(KEPT, moment, now=T0 + timedelta(hours=moment))
    world.roll_back_to(backup)
    with allure.step("a backup older than the ledger is unprovable"):
        with pytest.raises(LedgerIncomplete) as early:
            restore_control_plane(
                world.repo.db_path,
                world.ledger,
                effects,
                backup_taken_at=T0 - timedelta(days=1),
                now=T0 + timedelta(days=1),
            )
        attach_json("reason", str(early.value))
    with allure.step("a hole in the control sequence is unprovable"):
        with closing(sqlite3.connect(world.data_dir / "control.sqlite3")) as conn:
            conn.execute("DELETE FROM control_entries WHERE seq = 2")
            conn.commit()
        with pytest.raises(LedgerIncomplete) as hole:
            restore_control_plane(
                world.repo.db_path,
                world.ledger,
                effects,
                backup_taken_at=T0,
                now=T0 + timedelta(days=1),
            )
        attach_json("reason", str(hole.value))
    with allure.step("nothing was served or applied while unproven"):
        check_equal(
            "open scopes",
            world.rows("SELECT admission_open FROM sync_scopes"),
            [(0,), (0,)],
        )
        check_equal("no effects", (effects.purged, effects.revoked), ([], []))


def test_026_FR_015_purge_completion_retires_points_and_erases_the_marker(world):
    world.ledger.record_purge(GONE, now=T0)
    world.ledger.record_purge(GONE, now=T0)
    check_equal("one marker", len(world.ledger.entries()), 1)

    def failing(owner_id: str) -> None:
        raise OSError("backup artifact not removable")

    with allure.step("a failed artifact cleanup keeps purge incomplete"):
        with pytest.raises(OSError):
            world.ledger.complete_purge(GONE, failing)
        check_equal("marker kept", [e.owner_id for e in world.ledger.entries()], [GONE])
    with allure.step("completion erases every owner-linked byte"):
        retired: list[str] = []
        world.ledger.complete_purge(GONE, retired.append)
        check_equal("retired", retired, [GONE])
        assert GONE.encode() not in (world.data_dir / "control.sqlite3").read_bytes()
        check_equal(
            "tombstone only", [e.owner_id for e in world.ledger.entries()], [None]
        )


def test_026_FR_015_revocations_expire_with_the_restore_horizon_but_purge_markers_do_not(
    world,
):
    world.ledger.record_purge(GONE, now=T0)
    world.ledger.record_revocation(KEPT, 2, now=T0 + timedelta(hours=1))
    later = T0 + HORIZON + timedelta(hours=1)
    with allure.step("the aged revocation is retired, the open purge is kept"):
        check_equal("pruned", world.ledger.prune(later), 1)
        kinds = [(e.kind, e.owner_id) for e in world.ledger.entries()]
        check_equal("kept", kinds, [("purge", GONE), ("retired", None)])
    with allure.step("a backup older than the retired decision is now unprovable"):
        with pytest.raises(LedgerIncomplete) as early:
            world.ledger.prove_complete(T0 + timedelta(minutes=30))
        attach_json("reason", str(early.value))
        assert world.ledger.prove_complete(later)


def test_026_FR_015_account_deletion_and_purge_feed_the_control_ledger(
    api_client, tmp_path
):
    container = _container(api_client)
    ledger = ControlLedger(tmp_path / "account-control.sqlite3", now=utcnow())
    retired: list[str] = []
    container.account_service.attach_control_ledger(ledger, retired.append)
    user_id = _user_id(api_client)
    api_client.post(
        "/api/account/delete", json={"current_password": TEST_USER_PASSWORD}
    )
    with allure.step("deletion request records a session revocation"):
        kinds = [(e.kind, e.owner_id) for e in ledger.entries()]
        check_equal("revocation", kinds, [("revoke_sessions", user_id)])
    _backdate_deletion(api_client, user_id, days=30)
    container.account_service.purge_account(user_id)
    with allure.step("purge retired restore points and erased the owner marker"):
        check_equal("retired", retired, [user_id])
        owners = [e.owner_id for e in ledger.entries() if e.kind == "purge"]
        check_equal("no purge marker left", owners, [])
        assert container.user_repo.get_by_id(user_id) is None


def test_026_FR_015_failed_restore_point_cleanup_keeps_the_account_purge_open(
    api_client, tmp_path
):
    container = _container(api_client)
    ledger = ControlLedger(tmp_path / "account-control.sqlite3", now=utcnow())

    def failing(owner_id: str) -> None:
        raise OSError("artifact still present")

    container.account_service.attach_control_ledger(ledger, failing)
    user_id = _user_id(api_client)
    api_client.post(
        "/api/account/delete", json={"current_password": TEST_USER_PASSWORD}
    )
    _backdate_deletion(api_client, user_id, days=30)
    with allure.step("purge fails and the account stays for a retry"):
        with pytest.raises(OSError):
            container.account_service.purge_account(user_id)
        check_equal(
            "marker kept",
            [e.owner_id for e in ledger.entries() if e.kind == "purge"],
            [user_id],
        )
        assert container.user_repo.get_by_id(user_id) is not None


def test_026_FR_010_an_epoch_registered_after_the_restore_point_reads_closed_not_404(
    world,
):
    backup = world.snapshot()
    world.register(KEPT)
    world.roll_back_to(backup)
    with allure.step("the image has no row for the epoch"):
        check_equal("rows", world.rows("SELECT * FROM sync_device_epochs"), [])
    restore_control_plane(
        world.repo.db_path,
        world.ledger,
        Sessions(world.data_dir),
        backup_taken_at=T0,
        now=T0 + timedelta(hours=2),
    )
    reopen(world.repo.db_path, world.ledger, external_effects_reconciled=True)
    with allure.step(
        "the device's next send is EPOCH_CLOSED, never RESOURCE_NOT_FOUND"
    ):
        with pytest.raises(SyncCommandError) as sent:
            world.run(KEPT, "01900000-0000-4000-8000-000000000005")
        check_equal("code", sent.value.code, "EPOCH_CLOSED")
        check_equal("no effect", world.effects, [])
    with allure.step("registering it again is closed too; a fresh epoch works"):
        with pytest.raises(SyncCommandError) as again:
            world.register(KEPT)
        check_equal("code", again.value.code, "EPOCH_CLOSED")
        check_equal("fresh", world.register(KEPT, "epoch-2")["epoch_status"], "active")


def test_026_FR_015_operator_cli_replays_then_reopens(data_dir, monkeypatch):
    from typer.testing import CliRunner

    from app.cli import app as cli_app
    from app.core import get_config

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    runner = CliRunner()
    command = "sync-restore-control-plane"
    taken = (utcnow() + timedelta(minutes=1)).isoformat()
    with allure.step("refuses without the stopped-writers acknowledgement"):
        refused = runner.invoke(cli_app, [command, "--backup-taken-at", taken])
        check_equal("exit", refused.exit_code, 2)
    with allure.step("an unprovable backup keeps access closed"):
        old = runner.invoke(
            cli_app,
            [
                command,
                "--writers-stopped",
                "--backup-taken-at",
                "2020-01-01T00:00:00+00:00",
            ],
        )
        check_equal("exit", old.exit_code, 1)
    with allure.step("a provable restore reports the incident, reopen needs reconcile"):
        done = runner.invoke(
            cli_app, [command, "--writers-stopped", "--backup-taken-at", taken]
        )
        attach_json("stdout", done.stdout)
        check_equal("exit", done.exit_code, 0)
        assert INCIDENT in done.stdout
        early = runner.invoke(cli_app, [command, "--writers-stopped", "--reopen"])
        check_equal("reopen refused", early.exit_code, 1)
        final = runner.invoke(
            cli_app,
            [command, "--writers-stopped", "--reopen", "--external-effects-reconciled"],
        )
        check_equal("reopened", final.exit_code, 0)
    get_config.cache_clear()


def test_026_FR_015_prune_retires_a_purge_marker_only_when_the_account_is_gone(world):
    world.ledger.record_purge(GONE, now=T0)
    world.ledger.record_purge(KEPT, now=T0)
    later = T0 + HORIZON + timedelta(hours=1)
    with allure.step("a marker inside the horizon is kept"):
        world.ledger.prune(T0 + timedelta(days=1), keep_owner=lambda _: False)
        check_equal("kept", len(world.ledger.entries()), 2)
    with allure.step("past the horizon only the vanished account's marker retires"):
        world.ledger.prune(later, keep_owner=lambda owner: owner == KEPT)
        kinds = [(e.kind, e.owner_id) for e in world.ledger.entries()]
        check_equal("kinds", kinds, [("retired", None), ("purge", KEPT)])


def test_026_FR_015_production_container_records_into_its_own_ledger(api_client):
    container = _container(api_client)
    user_id = _user_id(api_client)
    api_client.post(
        "/api/account/delete", json={"current_password": TEST_USER_PASSWORD}
    )
    with allure.step("the container's ledger saw the revocation"):
        kinds = [(e.kind, e.owner_id) for e in container.control_ledger.entries()]
        attach_json("entries", kinds)
        assert ("revoke_sessions", user_id) in kinds


def test_026_FR_015_pruned_purge_marker_still_makes_an_earlier_backup_unprovable(
    world,
):
    world.ledger.record_revocation(GONE, 2, now=T0 + timedelta(hours=1))
    world.ledger.record_purge(GONE, now=T0 + timedelta(hours=3))
    backup = T0 + timedelta(hours=2)  # after the revocation, before the purge
    world.ledger.prune(T0 + HORIZON + timedelta(days=1), keep_owner=lambda _: False)
    with allure.step("a backup that still holds the account is not provable"):
        with pytest.raises(LedgerIncomplete) as early:
            world.ledger.prove_complete(backup)
        attach_json("reason", str(early.value))
    with allure.step("a backup taken after the purge is"):
        decisions = world.ledger.prove_complete(T0 + timedelta(hours=4))
        attach_json("decisions", decisions)
        assert decisions == []


@pytest.mark.parametrize("edge", ["first", "last", "only"])
def test_026_FR_015_losing_an_edge_entry_makes_completeness_unprovable(world, edge):
    world.ledger.record_purge(GONE, now=T0 + timedelta(hours=1))
    if edge != "only":
        world.ledger.record_revocation(KEPT, 2, now=T0 + timedelta(hours=2))
        world.ledger.record_purge(KEPT, now=T0 + timedelta(hours=3))
    keep_seq = {"first": "MIN", "last": "MAX", "only": "MAX"}[edge]
    with closing(sqlite3.connect(world.data_dir / "control.sqlite3")) as conn:
        conn.execute(
            f"DELETE FROM control_entries WHERE seq = "  # noqa: S608
            f"(SELECT {keep_seq}(seq) FROM control_entries)"
        )
        conn.commit()
    with allure.step("the missing edge is detected"):
        with pytest.raises(LedgerIncomplete) as lost:
            world.ledger.prove_complete(T0 + timedelta(minutes=1))
        attach_json("reason", str(lost.value))
