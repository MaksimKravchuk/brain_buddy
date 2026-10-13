"""026-FR-005/006/011/012 and SC-002: server receipt crash and replay safety."""

from __future__ import annotations

import fcntl
import json
import os
import selectors
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import allure
import pytest

from app.exceptions import ConflictError, ValidationFailure
from app.modules.tasks import TaskRepository
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import TagDocument, TaskDocument
from app.modules.tasks.jobs import JobRepository
from app.modules.tasks.jobs.execution import JobExecutionGate, StaleExecutorError
from app.modules.tasks.repository import display_tag_name
from app.modules.tasks.rust_adapter import DomainRefusal, RustCore
from app.modules.tasks.rust_review_facade import encode_settings_private, encode_task
from app.modules.tasks.rust_task_facade import (
    _envelope,
    _inputs,
    _refused,
    encode_tag,
)
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


def test_026_FR_005_legacy_refusal_replay_keeps_original_tag_conflict(
    store, monkeypatch
):
    repo, uow, receipts = store
    tag_request = CommandRequest.legacy(
        OWNER,
        "legacy-tag-create",
        "create_tag",
        {"command_type": "tag.create", "body": {"name": "@Work"}},
        entity_id="tag_pending",
        route="create_tag",
    )
    existing = TagDocument(
        id="tag_existing",
        owner_id=OWNER,
        name="Work",
        created_at=NOW,
        updated_at=NOW,
    )
    repo.create_tag(existing)
    decision = receipts._core.decide(
        {"projects": {}, "tags": {existing.id: encode_tag(existing)}},
        _envelope(
            "tag.create",
            "tag_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d12",
            {"name": "@Work"},
            NOW,
            None,
        ),
        _inputs(NOW, OWNER),
    )
    assert decision.refusal is not None
    original = decision.refusal
    assert original.reason == "duplicate_tag_name"
    with receipts.command(uow, tag_request, authority, now=NOW) as cmd:
        rejected = cmd.reject(original)
    assert rejected["error"]["message"] == "Command rejected."
    assert "_legacy_refusal_v1" not in json.dumps(rejected)
    assert count(repo, "sync_command_receipts") == 1

    # The matching retry returns the original conflict after the live tag has
    # changed. It does not decide against the newer owner state.
    repo.save_tag(existing.model_copy(update={"name": "Renamed"}))
    with receipts.command(uow, tag_request, authority, now=NOW) as retry:
        assert retry.replay is not None
        assert retry.replay["outcome"] == "rejected"
        assert retry.replay_refusal == original
        with pytest.raises(SyncCommandError, match="COMMAND_ALREADY_TERMINAL"):
            retry.accept([])

    assert retry.replay_refusal is not None
    mapped = _refused(retry.replay_refusal, attempted_name=display_tag_name("@Work"))
    assert isinstance(mapped, ConflictError)
    assert (mapped.resource, mapped.identifier) == ("Tag", "Work")
    assert str(mapped) == "Tag 'Work' already exists."
    with uow.begin(OWNER) as unit:
        public_lookup = receipts.lookup(unit, retry.command_id, authority, now=NOW)
    assert public_lookup is not None
    assert "_legacy_refusal_v1" not in json.dumps(public_lookup)

    # Expiring the public result must not discard the minimal typed witness.
    with receipts.command(
        uow, tag_request, authority, now=NOW + timedelta(hours=25)
    ) as expired_retry:
        assert expired_retry.replay is not None
        assert expired_retry.replay["result_redacted"] is True
        assert expired_retry.replay_refusal == original

    with (
        pytest.raises(SyncCommandError, match="IDEMPOTENCY_KEY_REUSED"),
        receipts.command(
            uow,
            CommandRequest.legacy(
                OWNER,
                "legacy-tag-create",
                "create_tag",
                {"command_type": "tag.create", "body": {"name": "@Other"}},
                entity_id="tag_pending",
                route="create_tag",
            ),
            authority,
            now=NOW,
        ),
    ):
        pytest.fail("the changed tag body replayed a stored refusal")

    with sqlite3.connect(repo.db_path) as connection:
        row = connection.execute(
            "SELECT command_id, metadata FROM sync_command_receipts WHERE owner_id=?",
            (OWNER,),
        ).fetchone()
        assert row is not None
        metadata = json.loads(row[1])
        valid = metadata["_legacy_refusal_v1"]
        corrupt_witnesses = []
        for field, value in (
            ("reason", 7),
            ("field", 7),
            ("entity", {"type": "tag"}),
            ("entity", ["tag", ["Work", 7]]),
            ("current_revision", "not-a-revision"),
            ("current_revision", str(2**64)),
        ):
            corrupt = {**valid, field: value}
            corrupt_witnesses.append(corrupt)
        corrupt_witnesses.append([])
        corrupt_witnesses.append({})
        for witness in corrupt_witnesses:
            metadata["_legacy_refusal_v1"] = witness
            connection.execute(
                "UPDATE sync_command_receipts SET metadata=? "
                "WHERE owner_id=? AND command_id=?",
                (json.dumps(metadata), OWNER, row[0]),
            )
            connection.commit()
            with (
                pytest.raises(SyncCommandError, match="COMMAND_INTEGRITY"),
                receipts.command(uow, tag_request, authority, now=NOW),
            ):
                pytest.fail("a malformed private refusal witness was trusted")
        metadata.pop("_legacy_refusal_v1")
        connection.execute(
            "UPDATE sync_command_receipts SET metadata=? "
            "WHERE owner_id=? AND command_id=?",
            (json.dumps(metadata), OWNER, row[0]),
        )
        connection.commit()

    with receipts.command(uow, tag_request, authority, now=NOW) as no_witness_retry:
        assert no_witness_retry.replay is not None
        assert no_witness_retry.replay_refusal is None

    original_receipt_reader = receipts._receipt_row
    reads = 0

    def lose_private_row_after_lookup(unit, command_id):
        nonlocal reads
        reads += 1
        return original_receipt_reader(unit, command_id) if reads == 1 else None

    monkeypatch.setattr(receipts, "_receipt_row", lose_private_row_after_lookup)
    with (
        pytest.raises(SyncCommandError, match="COMMAND_INTEGRITY"),
        receipts.command(uow, tag_request, authority, now=NOW),
    ):
        pytest.fail("a receipt removed between lookup and witness read was trusted")
    monkeypatch.setattr(receipts, "_receipt_row", original_receipt_reader)

    no_key_request = device_request()
    with receipts.command(uow, no_key_request, authority, now=NOW) as cmd:
        cmd.reject(DomainRefusal("entity_deleted", None, None, None))
    with receipts.command(uow, no_key_request, authority, now=NOW) as no_key_retry:
        assert no_key_retry.replay is not None
        assert no_key_retry.replay_refusal is None


def test_026_FR_005_rust_revision_refusal_replay_keeps_original_revision(store):
    repo, uow, receipts = store
    task = TaskDocument(
        id="task_revision",
        owner_id=OWNER,
        title="Original title",
        state="inbox",
        order_key=0,
        created_at=NOW,
        updated_at=NOW,
        revision=4,
    )
    repo.create(task)
    decision = receipts._core.decide(
        {"tasks": {task.id: encode_task(task)}},
        _envelope(
            "task.update",
            task.id,
            {"details": "attempted update"},
            NOW,
            ("task", task.id, 3),
        ),
        _inputs(NOW, OWNER),
    )
    assert decision.refusal is not None
    original = decision.refusal
    assert original.reason == "revision_conflict"
    assert original.entity == ("task", [task.id])
    assert original.current_revision == 4

    stale_request = CommandRequest.legacy(
        OWNER,
        "stale-task-update",
        "update_task:task_revision",
        {
            "command_type": "task.update",
            "body": {"details": "attempted update", "expected_revision": 3},
        },
        entity_id=task.id,
        route="update_task",
    )
    with receipts.command(uow, stale_request, authority, now=NOW) as cmd:
        cmd.reject(original)

    repo.save(task.model_copy(update={"revision": 5, "title": "Newer title"}))
    with receipts.command(
        uow, stale_request, authority, now=NOW + timedelta(hours=25)
    ) as retry:
        assert retry.replay is not None
        assert retry.replay["result_redacted"] is True
        assert retry.replay_refusal == original
        assert retry.replay_refusal.current_revision == 4
        assert retry.replay_refusal.entity == ("task", [task.id])

    with uow.begin(OWNER) as unit:
        public_lookup = receipts.lookup(unit, retry.command_id, authority, now=NOW)
    assert public_lookup is not None
    assert "_legacy_refusal_v1" not in json.dumps(public_lookup)


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
        assert child.stdout is not None
        # Exercise the descriptor range reached by the full backend suite.
        with (
            os.fdopen(fcntl.fcntl(child.stdout, fcntl.F_DUPFD, 1024)) as ready_stdout,
            selectors.DefaultSelector() as selector,
        ):
            selector.register(ready_stdout, selectors.EVENT_READ)
            assert selector.select(timeout=20), "child never reached the crash boundary"
            assert ready_stdout.readline().strip() == "ready"
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


def test_026_FR_022_redaction_marks_binding_only_receipts_without_changing_identity(
    store,
):
    repo, uow, receipts = store
    tag_binding = {
        "entity_type": "tag",
        "alias_id": "tag_redacted",
        "entity_id": "tag_redacted",
    }
    second_binding = {
        "entity_type": "tag",
        "alias_id": "tag_redacted_2",
        "entity_id": "tag_redacted_2",
    }
    with receipts.command(uow, request(), authority, now=NOW) as cmd:
        accepted = cmd.accept(write(repo, cmd), id_bindings=[tag_binding])
    owner_bindings = {accepted["command_id"]: tag_binding}
    for index in range(1, 100):
        binding = {
            "entity_type": "tag",
            "alias_id": f"tag_redacted_{index}",
            "entity_id": f"tag_redacted_{index}",
        }
        with receipts.command(
            uow, request(f"redaction-batch-{index}"), authority, now=NOW
        ) as cmd:
            accepted_batch_item = cmd.accept([], id_bindings=[binding])
        owner_bindings[accepted_batch_item["command_id"]] = binding
    other_request = CommandRequest.legacy(
        "user_receipts_other", "other", "tag.create", {"name": "Other"}
    )
    with receipts.command(uow, other_request, authority, now=NOW) as cmd:
        other = cmd.accept([], id_bindings=[second_binding])
    with sqlite3.connect(repo.db_path) as conn:
        conn.row_factory = sqlite3.Row
        before = {
            row["command_id"]: json.loads(row["metadata"])
            for row in conn.execute(
                "SELECT command_id, metadata FROM sync_command_receipts "
                "WHERE owner_id = ?",
                (OWNER,),
            )
        }
        other_before = conn.execute(
            "SELECT metadata, result FROM sync_command_receipts "
            "WHERE owner_id = ? AND command_id = ?",
            ("user_receipts_other", other["command_id"]),
        ).fetchone()
        assert set(before) == set(owner_bindings)
        assert len(before) == 100
        assert all(row["_had_result"] is False for row in before.values())
        assert all(row["result_redacted"] is False for row in before.values())

    with uow.begin(OWNER) as unit:
        receipts.change_log.redact_record(unit, "tag", ["tag_redacted"])

    with sqlite3.connect(repo.db_path) as conn:
        conn.row_factory = sqlite3.Row
        after = {
            row["command_id"]: json.loads(row["metadata"])
            for row in conn.execute(
                "SELECT command_id, metadata FROM sync_command_receipts "
                "WHERE owner_id = ?",
                (OWNER,),
            )
        }
        owner_results = [
            row["result"]
            for row in conn.execute(
                "SELECT result FROM sync_command_receipts WHERE owner_id = ?",
                (OWNER,),
            )
        ]
        other_after = conn.execute(
            "SELECT metadata, result FROM sync_command_receipts "
            "WHERE owner_id = ? AND command_id = ?",
            ("user_receipts_other", other["command_id"]),
        ).fetchone()
    assert after == {
        command_id: {**metadata, "result_redacted": True}
        for command_id, metadata in before.items()
    }
    assert len(owner_results) == 100 and set(owner_results) == {None}
    assert other_after["metadata"] == other_before["metadata"]
    assert other_after["result"] == other_before["result"]

    with uow.begin(OWNER) as unit:
        public = receipts.lookup(
            unit,
            accepted["command_id"],
            authority,
            now=NOW + timedelta(hours=1),
        )
    assert public is not None
    assert public["result"] is None and public["result_redacted"] is True
    assert public["id_bindings"] == [tag_binding]
    assert "_had_result" not in public and "_legacy_refusal_v1" not in public
    with uow.begin("user_receipts_other") as unit:
        other_public = receipts.lookup(
            unit,
            other["command_id"],
            authority,
            now=NOW + timedelta(hours=1),
        )
    assert other_public is not None
    assert other_public["result_redacted"] is False
    assert other_public["id_bindings"] == [second_binding]


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


def test_026_FR_005_device_command_id_with_a_different_envelope_conflicts(store):
    repo, uow, receipts = store
    with receipts.command(uow, device_request(), authority, now=NOW) as cmd:
        cmd.accept(write(repo, cmd))
    for changed in (
        device_request(payload={"previous_schema_field": "other"}),
        device_request(entity_id="task_other"),
    ):
        with (
            pytest.raises(SyncCommandError, match="IDEMPOTENCY_KEY_REUSED"),
            receipts.command(uow, changed, authority, now=NOW),
        ):
            pytest.fail("conflicting device command executed")
    assert count(repo, "tasks") == count(repo, "sync_change_transactions") == 1


def test_026_FR_006_each_scope_commit_takes_the_next_sequence_with_its_records(store):
    repo, uow, receipts = store
    sequences: dict[str, list[str]] = {OWNER: [], "user_other": []}
    for owner, key in (
        (OWNER, "a1"),
        ("user_other", "b1"),
        (OWNER, "a2"),
        ("user_other", "b2"),
        ("user_other", "b3"),
    ):
        envelope = CommandRequest.legacy(owner, key, "task.create", {"title": key})
        with receipts.command(uow, envelope, authority, now=NOW) as cmd:
            task = TaskDocument(
                id=f"task_{key}",
                owner_id=owner,
                title="t",
                state="inbox",
                order_key=0,
                created_at=NOW,
                updated_at=NOW,
            )
            repo.create(task)
            change = {
                "operation": "upsert",
                "entity_type": "task",
                "value": encode_task(task),
            }
            sequences[owner].append(cmd.accept([change])["commit_seq"])
    assert sequences == {OWNER: ["1", "2"], "user_other": ["1", "2", "3"]}
    with sqlite3.connect(repo.db_path) as conn:
        joined = conn.execute(
            "SELECT t.owner_id, t.commit_seq, r.record_key FROM "
            "sync_change_transactions t JOIN sync_change_records r "
            "ON r.owner_id = t.owner_id AND r.commit_seq = t.commit_seq "
            "ORDER BY t.owner_id, length(t.commit_seq), t.commit_seq"
        ).fetchall()
        orphans = conn.execute(
            "SELECT count(*) FROM sync_change_records r WHERE NOT EXISTS ("
            "SELECT 1 FROM sync_change_transactions t "
            "WHERE t.owner_id = r.owner_id AND t.commit_seq = r.commit_seq)"
        ).fetchone()[0]
    assert orphans == 0
    assert [(o, c, json.loads(k)[0]) for o, c, k in joined] == [
        ("user_other", "1", "task_b1"),
        ("user_other", "2", "task_b2"),
        ("user_other", "3", "task_b3"),
        (OWNER, "1", "task_a1"),
        (OWNER, "2", "task_a2"),
    ]
