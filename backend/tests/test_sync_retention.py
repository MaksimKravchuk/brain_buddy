"""026-FR-005/008/016/022 and SC-002: absolute source expiry and independent cleanup.

Every sync copy of source content -- receipt response, feed after-image, snapshot
page, oversized-transaction transfer -- ends at the source's own deadline: reads
fail closed at it, and a scheduled sweep that needs no owner activity, no feature
flag and no current authority removes or redacts the copy. Content-free dedup
metadata and typed Smart Add ``id_bindings`` outlive the response until purge.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import allure
import pytest

from app.container import Container
from app.modules.tasks.jobs import JobRepository
from app.modules.tasks.jobs.execution import JobExecutionGate, StaleExecutorError
from app.modules.tasks.jobs.privacy_adapter import (
    PRIVACY_SCHEDULE_KEY,
    SYNC_RETENTION_STEP,
    PrivacyMaintenanceAdapter,
)
from app.modules.tasks.sync import snapshots
from app.modules.tasks.sync.retention import (
    SyncRetention,
    expire_value,
    source_expiry,
    sync_owner_ids,
)
from tests.allure_evidence import attach_json, check_equal
from tests.conftest import (
    TEST_USER_EMAIL,
    TEST_USER_PASSWORD,
    FrozenClock,
    _build_authenticated_client,
)

from .test_maintenance_job_handoff import Clock, Ports, Rig
from .test_sync_commands_api import cid, ready, rows, run, set_flag, uid
from .test_sync_delta import cursor_at, error_code, pull
from .test_sync_review_projection import Synced
from .test_sync_snapshots import Snap

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Sync retention"),
    allure.story("Every sync copy ends at its source deadline"),
]
SECRET = "Retention secret title"


@pytest.fixture()
def live(tmp_path, monkeypatch):
    """A signed-in client with the sync flag on and a registered device."""
    client, _ = _build_authenticated_client(
        tmp_path,
        monkeypatch,
        subdir="sync-retention",
        email=TEST_USER_EMAIL,
        password=TEST_USER_PASSWORD,
    )
    owner_id = client.get("/api/auth/me").json()["id"]
    ready(client, owner_id)
    yield client
    client.close()


@pytest.fixture()
def rig(container: Container) -> Rig:
    # Full jitter pinned to its ceiling so backoff is exact.
    ledger = JobRepository(container.job_repository.db_path, jitter=lambda cap: cap)
    clock = Clock()
    gate = JobExecutionGate(ledger, owner_current=lambda _owner: True, now=clock)
    return Rig(container, ledger, clock, gate, [])


@pytest.fixture()
def owner(live) -> str:
    return str(live.get("/api/auth/me").json()["id"])


@pytest.fixture
def snap(api_client, frozen_clock: FrozenClock) -> Snap:
    container = api_client.app.state.container
    handler = container.task_service._legacy_tag_handler
    synced = Synced(api_client, frozen_clock)
    # Every writer must publish through the receipt boundary, as in production.
    container.task_service._legacy_tag_handler = handler
    return Snap(synced)


def gateway_of(client: Any) -> Any:
    return client.app.state.sync_gateway


def sweeper(client: Any, owner: str, at: datetime) -> SyncRetention:
    gateway = gateway_of(client)
    return SyncRetention(
        gateway.units,
        gateway.receipts.change_log,
        lambda: sync_owner_ids(gateway.units._repo.db_path),
        clock=lambda: at,
    )


@contextmanager
def db(client: Any) -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(client.app.state.container.task_repo.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        with conn:
            yield conn


def receipt_rows(client: Any) -> list[sqlite3.Row]:
    with db(client) as conn:
        return conn.execute(
            "SELECT * FROM sync_command_receipts ORDER BY command_id"
        ).fetchall()


def later(client: Any, hours: float) -> datetime:
    """Move the gateway clock ``hours`` ahead of now; returns that instant."""
    gateway = gateway_of(client)
    moment = datetime.now(UTC) + timedelta(hours=hours)
    client.app.state.sync_gateway = dataclasses.replace(gateway, clock=lambda: moment)
    return moment


# ------------------------------------------------------------ pure policy ----
def test_026_FR_016_only_a_review_decision_with_an_undo_window_has_a_deadline() -> None:
    now = datetime(2026, 10, 10, tzinfo=UTC)
    decision = {"id": "d", "undo_available_until": "2026-10-17T00:00:00+00:00"}
    with allure.step("the Undo window is the decision's source deadline"):
        check_equal(
            "deadline",
            source_expiry("review_decision", decision),
            decision["undo_available_until"],
        )
        check_equal("task", source_expiry("task", {"title": "x"}), None)
        check_equal("no window", source_expiry("review_decision", {"id": "d"}), None)
    with allure.step("only an elapsed window is redacted, and only that field"):
        check_equal("future", expire_value("review_decision", decision, now), None)
        check_equal(
            "elapsed",
            expire_value("review_decision", decision, now + timedelta(days=8)),
            {"id": "d"},
        )


# --------------------------------------------------------------- receipts ----
def test_026_FR_005_receipt_content_is_redacted_at_24_hours_for_an_inactive_owner(
    live, owner
) -> None:
    created = run(
        live, owner, 1, "task.create", uid("task", 1), {"title": SECRET}
    ).json()
    assert created["outcome"] == "accepted", created
    with allure.step("a receipt inside its 24 hours keeps its response"):
        sweeper(live, owner, later(live, 23)).run_retention_sweep()
        check_equal(
            "stored", [r["result"] is not None for r in receipt_rows(live)], [True]
        )
    with allure.step("the owner is inactive and the rollout flag is OFF"):
        set_flag(live, False)
        with db(live) as conn:
            conn.execute("UPDATE sync_scopes SET admission_open = 0")
    with allure.step("the sweep redacts the response without owner activity"):
        cleaned = sweeper(live, owner, later(live, 25)).run_retention_sweep()
        attach_json("cleaned", cleaned)
        assert cleaned >= 1
        [row] = receipt_rows(live)
        metadata = json.loads(row["metadata"])
        check_equal("result", row["result"], None)
        check_equal("flagged", metadata["result_redacted"], True)
        assert SECRET not in json.dumps([dict(r) for r in receipt_rows(live)])
    with allure.step("minimal dedup metadata stays until purge"):
        check_equal("fingerprint kept", bool(row["fingerprint"]), True)
        check_equal("outcome kept", metadata["outcome"], "accepted")
        check_equal("commit_seq kept", metadata["commit_seq"], created["commit_seq"])
        check_equal(
            "versions kept", metadata["result_versions"], created["result_versions"]
        )


def test_026_FR_005_a_swept_receipt_replays_without_a_second_effect(
    live, owner
) -> None:
    task = uid("task", 1)
    run(live, owner, 1, "task.create", task, {"title": SECRET})
    before = rows(live)
    sweeper(live, owner, later(live, 25)).run_retention_sweep()
    with allure.step("the same command id reads redacted and writes nothing"):
        again = run(live, owner, 1, "task.create", task, {"title": SECRET}).json()
        attach_json("replay", again)
        check_equal("redacted", again["result_redacted"], True)
        check_equal("no result", again["result"], None)
        check_equal("rows", rows(live), before)
    with allure.step("a repeat sweep has nothing left to do"):
        check_equal(
            "idempotent", sweeper(live, owner, later(live, 26)).run_retention_sweep(), 0
        )


def test_026_SC_002_lost_smart_add_ack_after_24_hours_resolves_the_retained_alias(
    live, owner
) -> None:
    home, errand, task = uid("project", 1), uid("tag", 2), uid("task", 3)
    alias_project = uid("project", 4)
    run(live, owner, 1, "project.create", home, {"name": "Home"})
    run(live, owner, 2, "tag.create", errand, {"name": "errand"})
    added = run(
        live,
        owner,
        3,
        "task.smart_add",
        task,
        {"title": SECRET, "project": {"name": "home", "proposed_id": alias_project}},
    ).json()
    assert added["outcome"] == "accepted", added
    expected = [b for b in added["id_bindings"] if b["alias_id"] == alias_project]
    assert expected and expected[0]["entity_id"] == home
    with allure.step("names and membership change, then 24 hours pass offline"):
        renamed = run(live, owner, 4, "project.update", home, {"name": "House"}, rev=1)
        assert renamed.json()["outcome"] == "accepted", renamed.text
        sweeper(live, owner, later(live, 25)).run_retention_sweep()
        [smart] = [
            r
            for r in receipt_rows(live)
            if json.loads(r["metadata"]).get("id_bindings")
        ]
        check_equal("response gone", smart["result"], None)
    with allure.step("the retained binding resolves the immutable alias, not the name"):
        moved = run(
            live,
            owner,
            5,
            "task.update",
            task,
            {
                "project_id": {
                    "after_command": cid(3),
                    "alias_id": alias_project,
                    "entity_type": "project",
                }
            },
            rev=1,
            depends_on=[cid(3)],
        ).json()
        attach_json("moved", moved)
        check_equal("accepted", moved["outcome"], "accepted")
        repo = live.app.state.container.task_repo
        check_equal(
            "project", repo.get_for_owner(task, owner_id=owner).project_id, home
        )
    with allure.step(
        "the redacted lookup still reports the typed content-free bindings"
    ):
        lookup = live.get(
            f"/api/sync/v1/commands/{cid(3)}", params={"scope_id": owner}
        ).json()["receipt"]
        check_equal("bindings", lookup["id_bindings"], added["id_bindings"])
        check_equal("redacted", lookup["result_redacted"], True)


def test_026_FR_005_capture_commit_record_keeps_its_scoped_exception(
    live, owner
) -> None:
    service = live.app.state.container.task_service
    repo = live.app.state.container.task_repo
    key = "capture-child-key"
    first = service.create_native_inbox_task(
        owner_id=owner, title=SECRET, source_capture_ids=[], idempotency_key=key
    )
    with allure.step("the sweep long after 24 hours leaves Capture's record alone"):
        sweeper(live, owner, later(live, 24 * 40)).run_retention_sweep()
        record = repo.get_idempotency(owner_id=owner, key=key)
        assert record is not None
        check_equal("kept", record.resource_id, first.id)
    with allure.step("its replay is still the original task, with no new one"):
        again = service.create_native_inbox_task(
            owner_id=owner, title=SECRET, source_capture_ids=[], idempotency_key=key
        )
        check_equal("same task", again.id, first.id)


# ---------------------------------------------------- Review content, feed ----
def decide(snap: Snap, key: str = "retention-decision") -> dict[str, Any]:
    api, clock = snap.synced.api, snap.clock
    snap.synced.grants_enabled()
    waiting = api.create("waiting card", state="waiting", waiting_for="Ann")
    clock.advance(days=40)
    session = api.start_raw().json()["id"]
    api.progress_raw(session, snapshot_decision_queue=True, current_step="decisions")
    waiting = api.task(waiting["id"])
    response = api.decide_raw(
        waiting,
        "follow_up",
        title="Call Ann",
        session_id=session,
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 200, response.text
    return {"task": waiting, "session": session, "decision": response.json()}


@contextmanager
def db_of(snap: Snap) -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(snap.synced.repo.db_path)) as conn, conn:
        yield conn


def feed(snap: Snap) -> list[sqlite3.Row]:
    with closing(sqlite3.connect(snap.synced.repo.db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM sync_change_records WHERE entity_type = 'review_decision' "
            "ORDER BY length(commit_seq), commit_seq"
        ).fetchall()


def sweep_for(snap: Snap, at: datetime | None = None) -> int:
    gateway = snap.client.app.state.sync_gateway
    return SyncRetention(
        gateway.units,
        gateway.receipts.change_log,
        lambda: sync_owner_ids(gateway.units._repo.db_path),
        clock=snap.clock if at is None else (lambda: at),
    ).run_retention_sweep()


def live_undo_windows(snap: Snap) -> list[str]:
    """Every non-null Undo window still readable in any retained feed payload."""
    with closing(sqlite3.connect(snap.synced.repo.db_path)) as conn:
        values = conn.execute(
            "SELECT value FROM sync_change_records WHERE value IS NOT NULL"
        ).fetchall()
    return [
        v["undo_available_until"]
        for (raw,) in values
        if (v := json.loads(raw)).get("undo_available_until") is not None
    ]


def test_026_FR_016_the_feed_stamps_the_seven_day_review_deadline(snap: Snap) -> None:
    decide(snap)
    with allure.step("the decision change carries its absolute source deadline"):
        [row] = feed(snap)
        value = json.loads(row["value"])
        attach_json("row", dict(row))
        check_equal("deadline", row["source_expires_at"], value["undo_available_until"])


def test_026_FR_016_an_unswept_feed_read_after_the_deadline_fails_closed(
    snap: Snap,
) -> None:
    decide(snap)
    gateway = snap.client.app.state.sync_gateway
    start = cursor_at(gateway, snap.owner)
    snap.clock.advance(days=7, hours=1)
    with allure.step("a delta read across the deadline resets instead of leaking"):
        response = pull(snap.client, snap.owner, start)
        check_equal("status", response.status_code, 409)
        check_equal("code", error_code(response), "RESET_REQUIRED")
        check_equal(
            "reason",
            response.json()["error"]["details"]["reset_reason"],
            "content_expired",
        )


def test_026_FR_016_the_sweep_redacts_the_feed_and_publishes_a_retention_change(
    snap: Snap,
) -> None:
    decide(snap)
    gateway = snap.client.app.state.sync_gateway
    before = cursor_at(gateway, snap.owner, snap.manifest()["watermark"])
    snap.clock.advance(days=7, hours=1)
    with allure.step("the owner is inactive and both flags are OFF"):
        snap.synced.rust("off")
        snap.synced.api.flag("off")
        with db_of(snap) as conn:
            conn.execute("UPDATE sync_scopes SET admission_open = 0")
        transactions = _count(snap, "sync_change_transactions")
    with allure.step("one sweep redacts every retained copy of the field"):
        check_equal("copies handled", sweep_for(snap) >= 2, True)
        rows_ = feed(snap)
        check_equal("two versions", len(rows_), 2)
        check_equal(
            "no deadlines left", [r["source_expires_at"] for r in rows_], [None, None]
        )
        check_equal("windows", live_undo_windows(snap), [])
    with allure.step("the redaction is one canonical change, not a feed reset"):
        check_equal(
            "one transaction",
            _count(snap, "sync_change_transactions"),
            transactions + 1,
        )
        check_equal(
            "version",
            [r["record_version"] for r in rows_],
            ["1", "2"],
        )
    with allure.step("a second sweep does nothing"):
        check_equal("idempotent", sweep_for(snap), 0)
        check_equal(
            "no new transaction",
            _count(snap, "sync_change_transactions"),
            transactions + 1,
        )
    with allure.step("a cursor from before the sweep keeps working"):
        snap.synced.rust("on")
        snap.synced.api.flag("on")
        with db_of(snap) as conn:
            conn.execute("UPDATE sync_scopes SET admission_open = 1")
        response = pull(snap.client, snap.owner, before)
        check_equal("status", response.status_code, 200)
        served = [
            c["value"].get("undo_available_until")
            for t in response.json()["transactions"]
            for c in t["changes"]
            if c["entity_type"] == "review_decision"
        ]
        check_equal("served", served, [None])


def _count(snap: Snap, table: str) -> int:
    with closing(sqlite3.connect(snap.synced.repo.db_path)) as conn:
        return int(
            conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        )  # noqa: S608


def test_026_SC_002_a_snapshot_paginated_across_the_deadline_never_serves_expired_content(
    snap: Snap, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshots, "TRANSFER_PAGE_BYTES", 256)
    decide(snap)
    snap.clock.advance(days=6, hours=23, minutes=50)
    manifest = snap.manifest()
    check_equal("pages", manifest["page_count"] > 1, True)
    first = snap.page(manifest["snapshot_id"], manifest["first_page_token"])
    with allure.step("a page inside the deadline is served"):
        check_equal("first", first.status_code, 200)
    with allure.step("the deadline passes and the sweep runs between pages"):
        snap.clock.advance(minutes=11)
        sweep_for(snap)
        check_equal("pages gone", _count(snap, "sync_snapshot_pages"), 0)
        token = first.json()["next_page_token"]
        response = snap.page(manifest["snapshot_id"], token)
        check_equal("status", response.status_code, 409)
        check_equal("code", error_code(response), "RESET_REQUIRED")
    with allure.step("a fresh snapshot carries the decision without the Undo window"):
        changes = snap.changes(snap.manifest())
        decision = next(c for c in changes if c["entity_type"] == "review_decision")
        check_equal("window", decision["value"].get("undo_available_until"), None)


def test_026_FR_016_redaction_invalidates_longer_lived_snapshots_and_transfers(
    snap: Snap,
) -> None:
    decided = decide(snap)
    manifest = snap.manifest()
    sequence = str(feed(snap)[0]["commit_seq"])
    with db_of(snap) as conn:
        # Copies that outlive the source deadline: only invalidation can end them.
        conn.execute("UPDATE sync_snapshots SET expires_at = '9999-01-01'")
        owner = snap.owner
        conn.execute(
            "INSERT INTO sync_transfers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                owner,
                "t1",
                sequence,
                "tx",
                "cmd",
                "f",
                "a",
                1,
                1,
                1,
                "x",
                "c",
                "9999-01-01",
            ),
        )
        conn.execute(
            "INSERT INTO sync_transfer_pages VALUES (?,?,?,?,?)",
            (owner, "t1", 0, b"expired payload", "p"),
        )
    snap.clock.advance(days=7, hours=1)
    sweep_for(snap)
    with allure.step("their pages are gone and a late page reads RESET_REQUIRED"):
        check_equal("snapshot pages", _count(snap, "sync_snapshot_pages"), 0)
        check_equal("transfer pages", _count(snap, "sync_transfer_pages"), 0)
        response = snap.page(manifest["snapshot_id"], manifest["first_page_token"])
        check_equal("code", error_code(response), "RESET_REQUIRED")
    attach_json("decision", decided["decision"]["decision"]["id"])


def test_026_FR_022_lifecycle_expired_snapshots_and_transfers_are_swept(
    snap: Snap,
) -> None:
    snap.manifest()
    snap.clock.advance(hours=2)
    with allure.step("a TTL-expired snapshot loses its pages with no owner traffic"):
        check_equal("held", _count(snap, "sync_snapshot_pages") > 0, True)
        sweep_for(snap)
        check_equal("pages", _count(snap, "sync_snapshot_pages"), 0)
        check_equal("metadata", _count(snap, "sync_snapshots"), 1)
    with allure.step("its metadata ages out with the feed horizon"):
        snap.clock.advance(days=91)
        sweep_for(snap)
        check_equal("metadata", _count(snap, "sync_snapshots"), 0)


def test_026_FR_008_legacy_matching_record_replay_survives_receipt_redaction(
    snap: Snap,
) -> None:
    decided = decide(snap, key="legacy-replay-key")
    waiting, session = decided["task"], decided["session"]
    snap.clock.advance(hours=25)
    sweep_for(snap)
    with allure.step("the new-protocol receipt content is gone"):
        with db_of(snap) as conn:
            results = conn.execute(
                "SELECT result FROM sync_command_receipts"
            ).fetchall()
        check_equal("redacted", [r[0] for r in results if r[0] is not None], [])
    with allure.step("the same decision retried under the old key still succeeds"):
        again = snap.synced.api.decide_raw(
            waiting,
            "follow_up",
            title="Call Ann",
            session_id=session,
            headers={"Idempotency-Key": "legacy-replay-key"},
        )
        attach_json("status", again.status_code)
        check_equal("status", again.status_code, 200)
        check_equal(
            "same decision",
            again.json()["decision"]["id"],
            decided["decision"]["decision"]["id"],
        )


# ------------------------------------------------------------- job wiring ----
class SyncPort:
    def __init__(self, journal: list[str], raises: Exception | None = None) -> None:
        self.journal, self.raises = journal, raises

    def run_retention_sweep(self) -> int:
        self.journal.append("sync_retention")
        if self.raises:
            raise self.raises
        return 1


def test_026_FR_022_the_privacy_job_runs_sync_retention_after_its_legacy_steps(
    rig: Rig,
) -> None:
    ports = Ports(rig.journal)
    adapter = PrivacyMaintenanceAdapter(
        ports, ports, ports, rig.gate, sync_retention=SyncPort(rig.journal)
    )
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    with allure.step("the new step runs last, on the same durable schedule"):
        assert worker.run_once() is True
        check_equal(
            "journal",
            rig.journal,
            [
                "purge_due_accounts",
                "run_retention_sweep",
                "purge_expired",
                "sync_retention",
            ],
        )
        check_equal("step", SYNC_RETENTION_STEP.name, "sync_retention")
        rig.active(PRIVACY_SCHEDULE_KEY)


def test_026_FR_022_sync_retention_and_the_account_purge_never_starve_each_other(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "secret-sync-content-9921"
    ports = Ports(rig.journal, raises={"purge_due_accounts": RuntimeError(secret)})
    adapter = PrivacyMaintenanceAdapter(
        ports,
        ports,
        ports,
        rig.gate,
        sync_retention=SyncPort(rig.journal, RuntimeError(secret)),
    )
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    with caplog.at_level(logging.DEBUG):
        worker.run_once()
    with allure.step("each failing step still let the others run"):
        check_equal(
            "journal",
            rig.journal,
            [
                "purge_due_accounts",
                "run_retention_sweep",
                "purge_expired",
                "sync_retention",
            ],
        )
    with allure.step("logs carry the step and exception type only"):
        check_equal("secret", secret in caplog.text, False)
        check_equal("step", "step=sync_retention" in caplog.text, True)


def test_026_FR_022_the_sweep_runs_for_a_deleted_pending_owner_inside_a_job(
    live, owner
) -> None:
    run(live, owner, 1, "task.create", uid("task", 1), {"title": SECRET})
    gateway = gateway_of(live)
    container = live.app.state.container
    moment = datetime.now(UTC) + timedelta(hours=25)
    ledger = JobRepository(container.job_repository.db_path, jitter=lambda cap: cap)
    clock = Clock()
    # The owner no longer passes the ordinary check but still exists.
    gate = JobExecutionGate(
        ledger,
        owner_current=lambda _owner: False,
        owner_exists=lambda _owner: True,
        now=clock,
    )
    idle = Ports([])
    adapter = PrivacyMaintenanceAdapter(
        idle,
        idle,
        idle,
        gate,
        sync_retention=SyncRetention(
            gateway.units,
            gateway.receipts.change_log,
            lambda: [owner],
            clock=lambda: moment,
        ),
    )
    worker = Rig(container, ledger, clock, gate, []).worker(adapter)
    worker.ensure_schedules(due_now=True)
    with allure.step("the cleanup unit is still authorized and redacts"):
        assert worker.run_once() is True
        check_equal("redacted", [r["result"] for r in receipt_rows(live)], [None])


# ------------------------------------------------------------ robustness ----
class FailingUnits:
    def __init__(self, failing: dict[str, Exception]) -> None:
        self.failing, self.opened = failing, []

    @contextmanager
    def begin(self, owner_id: str, *, cleanup: bool = False) -> Iterator[object]:
        self.opened.append((owner_id, cleanup))
        if owner_id in self.failing:
            raise self.failing[owner_id]
        yield object()


def test_026_FR_022_one_failing_owner_never_starves_the_rest_or_logs_content(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "owner-content-5531"
    units = FailingUnits({"a": RuntimeError(secret)})
    sweep = SyncRetention(units, None, lambda: ["b", "a", "b"])  # type: ignore[arg-type]
    swept: list[str] = []
    monkeypatch.setattr(
        SyncRetention, "sweep", lambda self, unit, *, now: swept.append("b") or 1
    )
    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(RuntimeError, match="incomplete"),
    ):
        sweep.run_retention_sweep()
    with allure.step(
        "every owner is visited once, in cleanup mode, and logs hold no text"
    ):
        check_equal("opened", units.opened, [("a", True), ("b", True)])
        check_equal("swept", swept, ["b"])
        check_equal("secret", secret in caplog.text, False)
        check_equal("type", "error=RuntimeError" in caplog.text, True)


def test_026_FR_022_a_lost_lease_stops_the_sweep_at_once() -> None:
    stale = StaleExecutorError("job", 3)
    units = FailingUnits({"a": stale})
    sweep = SyncRetention(units, None, lambda: ["a", "b"])  # type: ignore[arg-type]
    with pytest.raises(StaleExecutorError):
        sweep.run_retention_sweep()
    check_equal("only the first owner", units.opened, [("a", True)])


def test_026_FR_022_owner_discovery_tolerates_a_store_without_sync_tables(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty.sqlite3"
    sqlite3.connect(empty).close()
    with allure.step("no sync table means nothing to sweep"):
        check_equal("owners", sync_owner_ids(empty), [])


def test_026_FR_016_a_superseded_decision_copy_is_redacted_without_a_second_change(
    snap: Snap,
) -> None:
    decided = decide(snap)
    decision_id = decided["decision"]["decision"]["id"]
    task = snap.synced.api.task(decided["task"]["id"])
    undone = snap.synced.api.undo_raw(decision_id, task["revision"])
    assert undone.status_code == 200, undone.text
    snap.clock.advance(days=7, hours=1)
    transactions = _count(snap, "sync_change_transactions")
    with allure.step("the older copy is redacted; the newer record is already clean"):
        check_equal("handled", sweep_for(snap) >= 1, True)
        check_equal("windows", live_undo_windows(snap), [])
        check_equal(
            "no extra transaction",
            _count(snap, "sync_change_transactions"),
            transactions,
        )


# ------------------------------------------------- production wiring ----
def test_026_FR_022_the_production_privacy_job_includes_and_runs_sync_retention(
    live, owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app import main

    container = live.app.state.container
    run(live, owner, 1, "task.create", uid("task", 1), {"title": SECRET})
    registered: list[Any] = []
    monkeypatch.setattr(
        main.JobRegistry, "register", lambda self, adapter: registered.append(adapter)
    )
    handoff = main.SchedulerHandoff(enabled=True)
    main._install_durable_scheduler(
        container, handoff, voice_interval_seconds=0, privacy_interval_seconds=60
    )
    [privacy] = [a for a in registered if isinstance(a, PrivacyMaintenanceAdapter)]
    with allure.step("the registered adapter carries the container's sync retention"):
        check_equal("port", privacy._sync_retention is container.sync_retention, True)
    with allure.step("the legacy loop runs it too and redacts an expired receipt"):
        moment = datetime.now(UTC) + timedelta(hours=25)
        monkeypatch.setattr(container.sync_retention, "_clock", lambda: moment)
        main._run_privacy_maintenance_sweep(container)
        check_equal("redacted", [r["result"] for r in receipt_rows(live)], [None])
