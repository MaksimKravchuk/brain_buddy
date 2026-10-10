"""026-FR-005/006/011/012 and SC-002: server receipt crash and replay safety."""

from __future__ import annotations

import json
import select
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import allure
import pytest

from app.exceptions import ValidationFailure
from app.modules.tasks import TaskRepository
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import TaskDocument
from app.modules.tasks.jobs import JobRepository
from app.modules.tasks.jobs.execution import JobExecutionGate, StaleExecutorError
from app.modules.tasks.rust_adapter import DomainRefusal, RustCore
from app.modules.tasks.rust_review_facade import encode_settings_private, encode_task
from app.modules.tasks.sync.receipts import (
    CommandRequest,
    ReceiptStore,
    ScopeAuthority,
    SyncCommandError,
)
from app.modules.tasks.sync.unit_of_work import JobIntent, TaskUnitOfWork

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Durable task synchronization"),
    allure.story("Atomic server receipts and recovery"),
]
OWNER = "user_receipts"
NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


@pytest.fixture()
def store(data_dir: Path):
    repo = TaskRepository(data_dir)
    return (
        repo,
        TaskUnitOfWork(repo, JobRepository(repo.db_path)),
        ReceiptStore(RustCore()),
    )


def authority(unit):
    return ScopeAuthority(unit.owner_id, "server-1", "feed-1", "access-1", "sqlite-1")


def request(key="key", title="Secret title", command="task.create"):
    return CommandRequest.legacy(OWNER, key, command, {"title": title})


def write(repo, command):
    task = TaskDocument(
        id="task_first",
        owner_id=OWNER,
        title="Secret title",
        state="inbox",
        order_key=0,
        created_at=NOW,
        updated_at=NOW,
    )
    repo.create(task)
    settings = rd.ReviewSettingsDocument(owner_id=OWNER, last_effective_sweep_at=NOW)
    repo.save_review_settings(settings)
    command.unit.schedule(JobIntent("receipt.test", "job-1", NOW, scope=OWNER))
    return [
        {"operation": "upsert", "entity_type": "task", "value": encode_task(task)},
        {
            "operation": "upsert",
            "entity_type": "review_settings",
            "value": encode_settings_private(settings),
        },
    ]


def count(repo, table):
    with sqlite3.connect(repo.db_path) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608


def stored_result(unit, owner):
    return unit.connection.execute(
        "SELECT result FROM sync_command_receipts WHERE owner_id=?", (owner,)
    ).fetchone()["result"]


def test_026_FR_005_lost_response_reopens_and_replays_without_a_second_effect(store):
    repo, uow, receipts = store
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        result = cmd.accept(write(repo, cmd), result={"title": "Secret title"})
    with receipts.command(uow, request(), authority, now=NOW) as retry:
        assert retry.replay == result
    assert count(repo, "tasks") == count(repo, "jobs") == 1
    assert count(repo, "sync_change_transactions") == 1
    assert result["commit_seq"] == "1"


def test_026_FR_006_a_receipt_failure_rolls_back_domain_feed_and_jobs(
    store, monkeypatch
):
    repo, uow, receipts = store

    def fail(*args, **kwargs):
        raise RuntimeError("receipt storage fault")

    monkeypatch.setattr(receipts, "_insert", fail)
    with (
        pytest.raises(RuntimeError, match="storage fault"),
        receipts.command(uow, request(), authority, now=NOW) as cmd,
    ):
        cmd.accept(write(repo, cmd))
    for table in (
        "tasks",
        "jobs",
        "sync_change_transactions",
        "sync_record_versions",
        "sync_scopes",
    ):
        assert count(repo, table) == 0


def test_026_FR_005_the_same_legacy_key_cannot_change_route_or_body(store):
    _, uow, receipts = store
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        cmd.accept([])
    for changed in (request(title="changed"), request(command="task.update")):
        with (
            pytest.raises(SyncCommandError, match="IDEMPOTENCY_KEY_REUSED"),
            receipts.command(uow, changed, authority, now=NOW),
        ):
            pytest.fail("conflicting command executed")


def test_026_FR_011_current_authority_is_required_even_for_a_known_receipt(store):
    _, uow, receipts = store
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        cmd.accept([])

    def revoked(unit):
        raise SyncCommandError("RESOURCE_NOT_FOUND")

    with (
        pytest.raises(SyncCommandError, match="RESOURCE_NOT_FOUND"),
        receipts.command(uow, request(), revoked, now=NOW),
    ):
        pytest.fail("revoked caller received a receipt")


def test_026_FR_006_noop_and_rejection_have_no_sequence_or_feed(store):
    repo, uow, receipts = store
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        noop = cmd.accept([])
    with receipts.command(uow, request("rejected"), authority, now=NOW) as cmd:
        rejected = cmd.reject(DomainRefusal("entity_deleted", None, None, None))
    assert noop["commit_seq"] is rejected["commit_seq"] is None
    assert count(repo, "sync_change_transactions") == 0


def test_026_FR_006_an_unfinished_command_cannot_commit_domain_writes(store):
    repo, uow, receipts = store
    with (
        pytest.raises(SyncCommandError, match="COMMAND_UNFINISHED"),
        receipts.command(uow, request(), authority, now=NOW) as cmd,
    ):
        write(repo, cmd)
    assert count(repo, "tasks") == count(repo, "jobs") == 0


def test_026_FR_005_receipt_expiry_redacts_content_but_keeps_the_outcome(store):
    repo, uow, receipts = store
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        cmd.accept(write(repo, cmd), result={"title": "Secret title"})
    with receipts.command(
        uow, request(), authority, now=NOW + timedelta(days=1)
    ) as cmd:
        assert cmd.replay["result"] is None
        assert cmd.replay["result_redacted"] is True
        assert cmd.replay["commit_seq"] == "1"
    assert count(repo, "sync_command_receipts") == 1


def test_026_FR_022_owner_purge_removes_all_new_protected_rows(store):
    repo, uow, receipts = store
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        cmd.accept(write(repo, cmd))
    repo.delete_all_for_owner(owner_id=OWNER)
    for table in (
        "jobs",
        "sync_scopes",
        "sync_command_receipts",
        "sync_legacy_keys",
        "sync_record_versions",
        "sync_change_transactions",
        "sync_change_records",
    ):
        assert count(repo, table) == 0


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_026_SC_002_process_kill_on_both_sides_of_commit_preserves_one_effect(
    data_dir, boundary
):
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
from test_sync_receipts import *
repo = TaskRepository(Path(sys.argv[1]))
uow = TaskUnitOfWork(repo, JobRepository(repo.db_path))
receipts = ReceiptStore(RustCore())
with receipts.command(uow, request(), authority, now=NOW) as cmd:
    cmd.accept(write(repo, cmd), result={"title": "Secret title"})
    if sys.argv[2] == "before":
        print("ready", flush=True)
        sys.stdin.readline()
if sys.argv[2] == "after":
    print("ready", flush=True)
    sys.stdin.readline()
"""
    child = subprocess.Popen(  # noqa: S603 -- current interpreter, literal child program and pytest-owned paths
        [
            sys.executable,
            "-c",
            script,
            str(data_dir),
            boundary,
            str(Path(__file__).parent),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert select.select([child.stdout], [], [], 20)[
            0
        ], "child never reached the crash boundary"
        assert child.stdout.readline().strip() == "ready"
        child.kill()
        child.communicate(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)
    repo = TaskRepository(data_dir)
    uow, receipts = TaskUnitOfWork(repo, JobRepository(repo.db_path)), ReceiptStore(
        RustCore()
    )
    expected = int(boundary == "after")
    for table in (
        "tasks",
        "review_settings",
        "jobs",
        "sync_command_receipts",
        "sync_change_transactions",
    ):
        assert count(repo, table) == expected
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        if boundary == "before":
            assert cmd.replay is None
            result = cmd.accept(write(repo, cmd))
        else:
            result = cmd.replay
    assert result["commit_seq"] == "1"
    assert count(repo, "tasks") == count(repo, "jobs") == 1


def device_request(**updates):
    body = {
        "protocol_version": 1,
        "command_id": "01900000-0000-4000-8000-000000000001",
        "scope_id": OWNER,
        "device_id": "device-1",
        "device_epoch": "epoch-1",
        "local_sequence": "1",
        "type": "retired.command",
        "command_version": 999,
        "entity_id": "task_first",
        "preconditions": [],
        "depends_on": [],
        "issued_at": NOW.isoformat(),
        "payload": {"previous_schema_field": "retained"},
        **updates,
    }
    return CommandRequest.device(OWNER, json.dumps(body).encode())


def test_026_FR_012_known_retired_envelope_is_replayed_before_current_validation(store):
    _, uow, receipts = store
    old = device_request()
    with receipts.command(uow, old, authority, now=NOW) as cmd:
        cmd.accept([])
    epoch_active, executable_version = False, 1

    def ingress(envelope):
        with receipts.command(uow, envelope, authority, now=NOW) as cmd:
            if cmd.replay is not None:
                return cmd.replay
            if not epoch_active:
                raise SyncCommandError("EPOCH_CLOSED")
            if executable_version != 999:
                raise SyncCommandError("UPGRADE_REQUIRED")
            pytest.fail("retired command executed")

    assert ingress(old)["outcome"] == "accepted"
    unseen = device_request(command_id="01900000-0000-4000-8000-000000000002")
    with pytest.raises(SyncCommandError, match="EPOCH_CLOSED"):
        ingress(unseen)
    epoch_active = True
    with pytest.raises(SyncCommandError, match="UPGRADE_REQUIRED"):
        ingress(unseen)


def test_026_FR_005_jcs_python_boundary_preserves_published_utf16_and_numbers():
    with RustCore() as core:
        wire = '{"דּ":7,"😀":6,"€":5,"ö":4,"\\u0080":3,"1":2,"\\r":1,"numbers":[-0.0,1e30,4.50,2e-3]}'
        expected = '{"\\r":1,"1":2,"numbers":[0,1e+30,4.5,0.002],"\u0080":3,"ö":4,"€":5,"😀":6,"דּ":7}'
        assert core.persistence("canonical", wire.encode()) == expected.encode()


def test_026_FR_006_repeated_rows_publish_final_after_image_and_keep_deletion_version(
    store,
):
    repo, uow, receipts = store
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        changes = write(repo, cmd)
        final = repo.get_for_owner("task_first", owner_id=OWNER).model_copy(
            update={"details": "final"}
        )
        repo.save(final)
        changes.append(
            {**changes[0], "value": {**changes[0]["value"], "details": "final"}}
        )
        receipt = cmd.accept(changes)
    assert receipt["result_versions"][0]["record_version"] == "1"
    with uow.begin(OWNER) as unit:
        tx = receipts.transactions(unit, authority, feed_generation="feed-1")
        assert len(tx[0]["changes"]) == 2
        task = next(row for row in tx[0]["changes"] if row["entity_type"] == "task")
        assert task["value"]["details"] == "final"
    with receipts.command(
        uow, request("delete", command="task.undo"), authority, now=NOW
    ) as cmd:
        repo.delete_task_record(OWNER, "task_first")
        deleted = cmd.accept(
            [
                {
                    "operation": "tombstone",
                    "entity_type": "task",
                    "record_key": ["task_first"],
                }
            ]
        )
    assert deleted["result_versions"][0]["record_version"] == "2"
    with uow.begin(OWNER) as unit:
        receipts.change_log.prune(unit, now=NOW + timedelta(days=91))
    with receipts.command(
        uow,
        request("new", command="task.create"),
        authority,
        now=NOW + timedelta(days=91),
    ) as cmd:
        created = cmd.accept(write(repo, cmd))
    assert created["result_versions"][0]["record_version"] == "3"


def test_026_FR_006_caught_finalization_failure_cannot_be_retried_or_committed(store):
    repo, uow, receipts = store
    with (
        pytest.raises(SyncCommandError, match="COMMAND_FINALIZATION_FAILED"),
        receipts.command(uow, request(), authority, now=NOW) as cmd,
    ):
        changes = write(repo, cmd)
        with pytest.raises(ValidationFailure):
            cmd.accept(
                changes,
                id_bindings=[
                    {"entity_type": "wrong", "alias_id": "a", "entity_id": "b"}
                ],
            )
        with pytest.raises(SyncCommandError, match="COMMAND_FINALIZATION_FAILED"):
            cmd.accept(changes)
    for table in (
        "tasks",
        "review_settings",
        "jobs",
        "sync_change_transactions",
        "sync_command_receipts",
        "sync_record_versions",
    ):
        assert count(repo, table) == 0


def test_026_FR_005_pull_forward_cannot_mutate_a_job_behind_replay_or_noop(store):
    repo, uow, receipts = store
    with uow.begin(OWNER) as unit:
        unit.schedule(JobIntent("receipt.test", "existing", NOW, scope=OWNER))
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        cmd.accept([])
    with (
        pytest.raises(SyncCommandError, match="WRITE_AFTER_TERMINAL"),
        receipts.command(uow, request(), authority, now=NOW) as cmd,
    ):
        assert (
            cmd.unit.schedule(
                JobIntent(
                    "receipt.test",
                    "existing",
                    NOW - timedelta(hours=1),
                    scope=OWNER,
                    pull_forward=True,
                )
            )
            is False
        )
    with (
        pytest.raises(SyncCommandError, match="NOOP_HAS_WRITES"),
        receipts.command(uow, request("noop"), authority, now=NOW) as cmd,
    ):
        cmd.unit.schedule(
            JobIntent(
                "receipt.test",
                "existing",
                NOW - timedelta(hours=1),
                scope=OWNER,
                pull_forward=True,
            )
        )
        cmd.accept([])
    assert uow._jobs.find_active("existing", scope=OWNER).run_at == NOW


def test_026_FR_005_target_and_semantic_route_are_conflicts_not_replay_namespaces(
    store,
):
    _, uow, receipts = store
    original = CommandRequest.legacy(
        OWNER,
        "same",
        "task.update",
        {"title": "same"},
        entity_id="task_a",
        route="task.update",
    )
    with receipts.command(uow, original, authority, now=NOW) as cmd:
        cmd.accept([])
    changed = CommandRequest.legacy(
        OWNER,
        "same",
        "task.update",
        {"title": "same"},
        entity_id="task_b",
        route="task.update",
    )
    with (
        pytest.raises(SyncCommandError, match="IDEMPOTENCY_KEY_REUSED"),
        receipts.command(uow, changed, authority, now=NOW),
    ):
        pytest.fail("target change evaded the owner/key lookup")


def test_026_FR_022_retained_aliases_survive_content_expiry_and_private_clocks_never_publish(
    store,
):
    repo, uow, receipts = store
    binding = {
        "entity_type": "tag",
        "alias_id": "tag_alias",
        "entity_id": "tag_original",
    }
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        cmd.accept(
            write(repo, cmd), result={"title": "Secret title"}, id_bindings=[binding]
        )
    with receipts.command(
        uow, request(), authority, now=NOW + timedelta(days=30)
    ) as cmd:
        assert cmd.replay["result"] is None
        assert cmd.replay["id_bindings"] == [binding]
    with uow.begin(OWNER) as unit:
        receipts.change_log.prune(unit, now=NOW + timedelta(days=30))
        tx = receipts.transactions(unit, authority, feed_generation="feed-1")
        settings = next(
            change["value"]
            for change in tx[0]["changes"]
            if change["entity_type"] == "review_settings"
        )
        assert "private" not in settings
        assert stored_result(unit, OWNER) is None


def test_026_FR_011_restore_or_revocation_generation_blocks_retained_outcome(store):
    _, uow, receipts = store
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        cmd.accept([])

    def restored(unit):
        return ScopeAuthority(
            unit.owner_id, "server-restored", "feed-restored", "access-1", "sqlite-1"
        )

    with (
        pytest.raises(SyncCommandError, match="RESET_REQUIRED"),
        receipts.command(uow, request(), restored, now=NOW),
    ):
        pytest.fail("old authority admitted restored work")


def test_026_SC_007_job_request_needs_current_binding_and_live_fence(store):
    repo, uow, receipts = store
    jobs = uow._jobs
    jobs.ensure_scheduled(
        job_type="receipt.test", dedup_key="claimed", run_at=NOW, scope=OWNER
    )
    lease = jobs.claim_due(
        owner="worker",
        types=("receipt.test",),
        now=NOW,
        lease_for=timedelta(minutes=1),
    )
    assert lease is not None
    gate = JobExecutionGate(
        jobs, owner_current=lambda owner: owner == OWNER, now=lambda: NOW
    )
    with gate.executing(lease):
        job_request = CommandRequest.job(OWNER, "task.create", {"title": "safe"})
        with receipts.command(uow, job_request, authority, now=NOW) as cmd:
            cmd.accept([])
    with (
        pytest.raises(SyncCommandError, match="TRUSTED_ORIGIN_REQUIRED"),
        receipts.command(uow, job_request, authority, now=NOW),
    ):
        pytest.fail("constructor-time provenance bypassed live binding")
    jobs.cancel(lease.job_id)
    with (
        gate.executing(lease),
        pytest.raises(StaleExecutorError),
        receipts.command(uow, job_request, authority, now=NOW),
    ):
        pytest.fail("retained receipt bypassed current job fence")
    assert count(repo, "sync_command_receipts") == 1


def test_026_FR_022_deletion_redacts_receipt_and_requires_feed_reset(store):
    repo, uow, receipts = store
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        accepted = cmd.accept(write(repo, cmd), result={"title": "Secret title"})
    with receipts.command(
        uow, request("delete", command="task.undo"), authority, now=NOW
    ) as cmd:
        repo.delete_task_record(OWNER, "task_first")
        deleted = cmd.accept(
            [
                {
                    "operation": "tombstone",
                    "entity_type": "task",
                    "record_key": ["task_first"],
                }
            ],
            result={"title": "Secret title"},
        )
    assert deleted["result"] is None
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        assert cmd.replay["command_id"] == accepted["command_id"]
        assert cmd.replay["result"] is None
        assert cmd.replay["result_redacted"]
    with (
        pytest.raises(SyncCommandError, match="RESET_REQUIRED"),
        uow.begin(OWNER) as unit,
    ):
        receipts.transactions(unit, authority, feed_generation="feed-1")


def test_026_FR_022_refusal_keeps_only_server_owned_diagnostics(store):
    repo, uow, receipts = store
    with receipts.command(uow, request("seed"), authority, now=NOW) as cmd:
        accepted = cmd.accept(write(repo, cmd))
    current = [accepted["result_versions"][0]]
    with receipts.command(uow, request("conflict"), authority, now=NOW) as cmd:
        rejected = cmd.reject(
            DomainRefusal(
                "revision_conflict", "Secret title", ("task", ["task_first"]), 0
            ),
            current_versions=current,
        )
    assert rejected["error"]["message"] == "Command rejected."
    assert "Secret title" not in json.dumps(rejected)
    assert rejected["error"]["details"]["current_versions"] == current
