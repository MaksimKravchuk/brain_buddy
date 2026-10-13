"""026-FR-005/006/014/015 and 026-SC-002/007 on the PostgreSQL target (PR-55).

The rollback, owner-lock, read-set, receipt, feed and fence fixtures of
``test_sync_unit_of_work`` and ``test_sync_receipts`` run here against a real,
isolated PostgreSQL instance through ``sync.postgres``. SQLite stays the only
active writer; nothing in the application builds these adapters.

The server is chosen in this order:

1. ``BRAIN_BUDDY_TEST_POSTGRES_DSN`` -- an already running server (a CI service
   container). Each test gets its own schema, so one server serves the suite.
2. Otherwise a throwaway ``postgres:17`` container is started with docker on a
   random loopback port and removed at the end of the session.

With neither available the fixture *fails* the tests; it never skips them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from app.exceptions import ConflictError, RepositoryError
from app.modules.tasks import review_domain as rd
from app.modules.tasks.jobs.domain import JobStatus
from app.modules.tasks.jobs.execution import (
    JobExecutionGate,
    ScopeRevokedError,
    StaleExecutorError,
)
from app.modules.tasks.rust_adapter import DomainRefusal, RustCore
from app.modules.tasks.rust_review_facade import encode_settings_private, encode_task
from app.modules.tasks.sync import postgres as pg
from app.modules.tasks.sync.receipts import (
    CommandRequest,
    ScopeAuthority,
    SyncCommandError,
)
from app.modules.tasks.sync.unit_of_work import (
    JobIntent,
    ReadSet,
    ReadSetChangedError,
    UnitOfWorkError,
)
from tests.test_sync_receipts import OWNER as RCPT
from tests.test_sync_receipts import request
from tests.test_sync_unit_of_work import (
    JOB_TYPE,
    OTHER,
    OWNER,
    T0,
    intent,
    make_project,
    make_tag,
    make_task,
)

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
DSN_ENV = "BRAIN_BUDDY_TEST_POSTGRES_DSN"
_PASSWORD = "bb-test-only"


# --- an isolated PostgreSQL instance ----------------------------------------------


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    docker = shutil.which("docker")
    if docker is None:
        pytest.fail(
            f"No PostgreSQL for the sync target: set {DSN_ENV} or install docker."
        )
    return subprocess.run(  # noqa: S603 - resolved docker binary, fixed test argv
        [docker, *args], capture_output=True, text=True, check=False
    )


def _start_container() -> tuple[str, str]:
    started = _docker(
        *("run", "-d", "--rm", "-p", "127.0.0.1::5432"),
        *("-e", f"POSTGRES_PASSWORD={_PASSWORD}", "postgres:17"),
    )
    if started.returncode != 0:
        pytest.fail(f"docker could not start postgres:17: {started.stderr.strip()}")
    container = started.stdout.strip()
    mapping = _docker("port", container, "5432/tcp")
    port = mapping.stdout.splitlines()[0].rsplit(":", 1)[1]
    return container, f"postgresql://postgres:{_PASSWORD}@127.0.0.1:{port}/postgres"


def _wait_ready(dsn: str) -> None:
    deadline = time.monotonic() + 90
    while True:
        try:
            with psycopg.connect(dsn, connect_timeout=2):
                return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


@pytest.fixture(scope="session")
def base_dsn() -> Iterator[str]:
    configured = os.environ.get(DSN_ENV)
    if configured:
        _wait_ready(configured)
        yield configured
        return
    container, dsn = _start_container()
    try:
        _wait_ready(dsn)
        yield dsn
    finally:
        _docker("rm", "-f", container)


@dataclass
class Target:
    dsn: str
    store: pg.PostgresTaskStore
    jobs: pg.PostgresJobLedger
    uow: pg.PostgresTaskUnitOfWork
    receipts: pg.PostgresReceiptStore

    def count(self, table: str) -> int:
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert row is not None
        return int(row[0])


@pytest.fixture()
def target(base_dsn: str) -> Iterator[Target]:
    schema = f"t_{uuid.uuid4().hex}"
    with psycopg.connect(base_dsn, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
    dsn = make_conninfo(base_dsn, options=f"-c search_path={schema}")
    with pg.connect(dsn) as conn:
        pg.initialize(conn)
    store, jobs = pg.PostgresTaskStore(dsn), pg.PostgresJobLedger(dsn)
    core = RustCore()
    try:
        yield Target(
            dsn,
            store,
            jobs,
            pg.PostgresTaskUnitOfWork(dsn, store, jobs),
            pg.PostgresReceiptStore(core),
        )
    finally:
        core.close()
        with psycopg.connect(base_dsn, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA "{schema}" CASCADE')


def authority(unit):
    return ScopeAuthority(unit.owner_id, "server-1", "feed-1", "access-1", "pg-1")


def write_aggregate(t: Target, unit) -> None:
    t.store.save_project(unit, make_project("p1"))
    t.store.save_tag(unit, make_tag("g1"))
    task = make_task("t1").model_copy(update={"project_id": "p1", "tag_ids": ["g1"]})
    t.store.save_task(unit, task)
    assert unit.schedule(intent()) is True


def aggregate_counts(t: Target) -> dict[str, int]:
    return {n: t.count(n) for n in ("task_documents", "jobs")}


def command_write(t: Target, cmd) -> list[dict]:
    task = make_task("task_first", owner=RCPT, title="Secret title")
    t.store.save_task(cmd.unit, task)
    settings = rd.ReviewSettingsDocument(owner_id=RCPT, last_effective_sweep_at=NOW)
    cmd.unit.schedule(JobIntent("receipt.test", "job-1", NOW, scope=RCPT))
    return [
        {"operation": "upsert", "entity_type": "task", "value": encode_task(task)},
        {
            "operation": "upsert",
            "entity_type": "review_settings",
            "value": encode_settings_private(settings),
        },
    ]


def tombstone() -> list[dict]:
    return [
        {
            "operation": "tombstone",
            "entity_type": "task",
            "record_key": ["task_first"],
        }
    ]


# --- one commit, one rollback (unit of work) --------------------------------------


def test_026_FR_006_pg_a_failure_rolls_back_documents_and_job_intents(
    target: Target,
) -> None:
    before = aggregate_counts(target)
    with pytest.raises(RuntimeError, match="boom"), target.uow.begin(OWNER) as unit:
        write_aggregate(target, unit)
        assert aggregate_counts(target) == before  # invisible from another session
        raise RuntimeError("boom")
    assert aggregate_counts(target) == before


def test_026_SC_002_pg_every_write_and_job_intent_shares_one_commit(
    target: Target,
) -> None:
    with target.uow.begin(OWNER) as unit:
        write_aggregate(target, unit)
        assert [(w.resource, w.record_id) for w in unit.writes] == [
            ("Project", "p1"),
            ("Tag", "g1"),
            ("Task", "t1"),
        ]
        assert aggregate_counts(target) == {"task_documents": 0, "jobs": 0}
    assert aggregate_counts(target) == {"task_documents": 3, "jobs": 1}
    with pg.connect(target.dsn) as conn:  # xmin names the writing transaction
        writers = conn.execute(
            "SELECT xmin::text AS x FROM task_documents "
            "UNION SELECT xmin::text FROM jobs"
        ).fetchall()
    assert len(writers) == 1


def test_026_FR_015_pg_replaying_the_same_intent_creates_one_job(
    target: Target,
) -> None:
    with target.uow.begin(OWNER) as unit:
        assert unit.schedule(intent("uow:dedup")) is True
        assert unit.schedule(intent("uow:dedup")) is False
        assert unit.intents == (intent("uow:dedup"),)
    assert target.jobs.find_active("uow:dedup", scope=OWNER) is not None
    assert target.count("jobs") == 1


def test_026_FR_006_pg_after_commit_actions_run_only_after_a_commit(
    target: Target,
) -> None:
    ran: list[str] = []
    with pytest.raises(RuntimeError), target.uow.begin(OWNER) as unit:
        unit.after_commit(lambda: ran.append("rolled-back"))
        raise RuntimeError("abort")
    with target.uow.begin(OWNER) as unit:
        unit.after_commit(lambda: ran.append("committed"))
        assert ran == []
    assert ran == ["committed"]


def test_026_FR_006_pg_a_second_writer_waits_for_the_commit_and_sees_all_of_it(
    target: Target,
) -> None:
    inside, attempting = threading.Event(), threading.Event()
    seen: list[tuple[int, bool]] = []

    def second_writer() -> None:
        inside.wait()
        attempting.set()
        with target.uow.begin(OWNER):  # blocks on the owner lock until the commit
            seen.append(
                (
                    target.store.get_for_owner("t1", owner_id=OWNER) is not None,
                    target.jobs.find_active("uow:one", scope=OWNER) is not None,
                )
            )

    worker = threading.Thread(target=second_writer)
    worker.start()
    try:
        with target.uow.begin(OWNER) as unit:
            inside.set()
            attempting.wait()
            time.sleep(0.3)
            assert seen == []  # still waiting on the lock this unit holds
            write_aggregate(target, unit)
    finally:
        worker.join(timeout=30)
    assert not worker.is_alive()
    assert seen == [(True, True)]


def test_026_FR_015_pg_owner_locks_are_per_owner_and_not_reentrant(
    target: Target,
) -> None:
    with target.uow.begin(OWNER):
        with (
            pytest.raises(UnitOfWorkError, match="already open"),
            target.uow.begin(OWNER),
        ):
            pass  # pragma: no cover - refused before the body runs
        done = threading.Event()

        def other_owner() -> None:
            with target.uow.begin(OTHER):
                done.set()

        worker = threading.Thread(target=other_owner)
        worker.start()
        assert done.wait(timeout=10)  # another owner is not blocked by OWNER's lock
        worker.join(timeout=10)
    with target.uow.begin(OWNER):  # the refused attempt left no state behind
        pass


def test_026_FR_006_pg_a_unit_that_has_ended_accepts_no_more_work(
    target: Target,
) -> None:
    with target.uow.begin(OWNER) as unit:
        pass
    with pytest.raises(UnitOfWorkError, match="ended"):
        unit.schedule(intent())
    with pytest.raises(UnitOfWorkError, match="ended"):
        unit.load(tasks=("t1",))


# --- boundaries and read sets -----------------------------------------------------


def test_026_FR_014_pg_a_write_for_another_owner_is_refused_inside_the_unit(
    target: Target,
) -> None:
    with pytest.raises(UnitOfWorkError, match="owner"), target.uow.begin(OWNER) as unit:
        target.store.save_task(unit, make_task("mine"))
        target.store.save_task(unit, make_task("theirs", owner=OTHER))
    assert target.count("task_documents") == 0


def test_026_FR_014_pg_a_job_intent_may_not_reach_another_owners_scope(
    target: Target,
) -> None:
    with pytest.raises(UnitOfWorkError, match="scope"), target.uow.begin(OWNER) as unit:
        unit.schedule(intent("uow:foreign", scope=OTHER))
    with target.uow.begin(OWNER) as unit:
        assert unit.schedule(intent("uow:system", scope="system")) is True


def test_026_FR_006_pg_a_read_set_loaded_under_the_lock_is_owner_scoped(
    target: Target,
) -> None:
    with target.uow.begin(OWNER) as unit:
        target.store.save_project(unit, make_project("p1"))
        target.store.save_tag(unit, make_tag("g1"))
        target.store.save_task(unit, make_task("t1"))
    with target.uow.begin(OTHER) as unit:
        target.store.save_task(unit, make_task("theirs", owner=OTHER))
    with target.uow.begin(OWNER) as unit:
        read_set = unit.load(
            tasks=("t1", "theirs", "t1"), projects=("p1", "nope"), tags=("g1",)
        )
    assert read_set.owner_id == OWNER
    assert read_set.tasks["t1"] is not None
    assert read_set.tasks["theirs"] is None  # another owner's task reads as absent
    assert read_set.projects["nope"] is None and read_set.tags["g1"] is not None


def test_026_FR_006_pg_a_stale_read_set_is_refused_and_nothing_is_written(
    target: Target,
) -> None:
    with target.uow.begin(OWNER) as unit:
        target.store.save_task(unit, make_task("t1"))
    with target.uow.begin(OWNER) as unit:
        read_set = unit.load(tasks=("t1", "later"))
        unit.verify(read_set)  # unchanged inside the same unit: fine
    with target.uow.begin(OWNER) as unit:
        target.store.save_task(unit, make_task("t1", title="Changed elsewhere"))
    before = aggregate_counts(target)

    with pytest.raises(ReadSetChangedError) as stale, target.uow.begin(OWNER) as unit:
        unit.verify(read_set)
        target.store.save_project(unit, make_project("never"))  # pragma: no cover
    assert isinstance(stale.value, ConflictError) and stale.value.identifier == "t1"
    assert aggregate_counts(target) == before

    with target.uow.begin(OWNER) as unit:
        target.store.save_task(unit, make_task("later"))
    absent = ReadSet(OWNER, {"later": None}, {}, {}, {("Task", "later"): None})
    with pytest.raises(ReadSetChangedError) as created, target.uow.begin(OWNER) as unit:
        unit.verify(unit.load(tasks=("t1",)))
        unit.verify(absent)
    assert created.value.identifier == "later"


def test_026_FR_006_pg_a_read_set_cannot_be_verified_for_another_owner(
    target: Target,
) -> None:
    with target.uow.begin(OTHER) as unit:
        foreign = unit.load(tasks=("x",))
    with (
        pytest.raises(UnitOfWorkError, match="another owner"),
        target.uow.begin(OWNER) as unit,
    ):
        unit.verify(foreign)


# --- lease / fence authority ------------------------------------------------------


def claim(t: Target, key: str = "uow:claim"):
    t.jobs.ensure_scheduled(job_type=JOB_TYPE, dedup_key=key, run_at=T0)
    lease = t.jobs.claim_due(
        owner="w1", types=(JOB_TYPE,), now=T0, lease_for=timedelta(seconds=60)
    )
    assert lease is not None
    return lease


def gate_for(t: Target, *, current=lambda o: o == OWNER, exists=None):
    return JobExecutionGate(
        t.jobs, owner_current=current, owner_exists=exists, now=lambda: T0
    )


def test_026_SC_007_pg_a_stale_executor_cannot_open_a_unit_or_leave_an_intent(
    target: Target,
) -> None:
    lease = claim(target)
    target.jobs.cancel(lease.job_id)
    before = aggregate_counts(target)
    with (
        gate_for(target).executing(lease),
        pytest.raises(StaleExecutorError),
        target.uow.begin(OWNER) as unit,
    ):
        write_aggregate(target, unit)  # pragma: no cover
    assert aggregate_counts(target) == before


def test_026_SC_007_pg_a_revoked_scope_cannot_open_a_unit(target: Target) -> None:
    lease = claim(target)
    with (
        gate_for(target).executing(lease),
        pytest.raises(ScopeRevokedError),
        target.uow.begin(OTHER),
    ):
        pass  # pragma: no cover


def test_026_SC_007_pg_a_current_executor_commits_inside_the_unit(
    target: Target,
) -> None:
    lease = claim(target)
    with gate_for(target).executing(lease), target.uow.begin(OWNER) as unit:
        target.store.save_task(unit, make_task("by-job"))
        unit.schedule(intent("uow:follow-up"))
    assert target.store.get_for_owner("by-job", owner_id=OWNER).id == "by-job"
    assert target.jobs.find_active("uow:follow-up", scope=OWNER) is not None


def test_026_SC_007_pg_cleanup_units_need_only_an_existing_owner(
    target: Target,
) -> None:
    lease = claim(target)
    gate = gate_for(target, current=lambda _o: False, exists=lambda _o: True)
    with gate.executing(lease):
        with pytest.raises(ScopeRevokedError), target.uow.begin(OWNER):
            pass  # pragma: no cover
        with target.uow.begin(OWNER, cleanup=True) as unit:
            assert unit.owner_id == OWNER


def test_026_SC_007_pg_a_cancel_cannot_move_the_fence_before_the_unit_commits(
    target: Target,
) -> None:
    lease = claim(target)
    cancelled = threading.Event()

    def cancel() -> None:
        target.jobs.cancel(lease.job_id)
        cancelled.set()

    with gate_for(target).executing(lease), target.uow.begin(OWNER) as unit:
        canceller = threading.Thread(target=cancel)
        canceller.start()
        assert not cancelled.wait(timeout=0.5)  # blocked by the unit's FOR SHARE
        target.store.save_task(unit, make_task("fenced"))
    canceller.join(timeout=10)
    assert cancelled.is_set()
    assert target.store.get_for_owner("fenced", owner_id=OWNER).id == "fenced"
    record = target.jobs.get(lease.job_id)
    assert record is not None and record.cancel_requested


def test_026_FR_015_pg_job_leases_use_monotonic_fences_and_refuse_stale_results(
    target: Target,
) -> None:
    first = claim(target, "uow:a")
    target.jobs.ensure_scheduled(job_type=JOB_TYPE, dedup_key="uow:b", run_at=T0)
    second = target.jobs.claim_due(owner="w2", types=(JOB_TYPE,), now=T0)
    assert second is not None and second.fence > first.fence
    assert not target.jobs.heartbeat(
        first.job_id, owner="w1", fence=first.fence + 99, until=T0 + timedelta(hours=1)
    )
    assert target.jobs.heartbeat(
        first.job_id, owner="w1", fence=first.fence, until=T0 + timedelta(hours=1)
    )
    assert not target.jobs.complete(first.job_id, fence=first.fence + 99)
    assert target.jobs.complete(first.job_id, fence=first.fence)
    assert target.jobs.should_abandon(first.job_id, fence=first.fence, now=T0)


def test_026_FR_015_pg_an_expired_lease_is_reclaimed_under_a_new_fence(
    target: Target,
) -> None:
    lease = claim(target)
    later = T0 + timedelta(hours=1)
    assert target.jobs.should_abandon(lease.job_id, fence=lease.fence, now=later)
    # The first claim settles the expired lease and backs the job off; it is
    # claimable once that backoff has passed.
    assert target.jobs.claim_due(owner="w2", types=(JOB_TYPE,), now=later) is None
    again = target.jobs.claim_due(
        owner="w2", types=(JOB_TYPE,), now=later + timedelta(hours=1)
    )
    assert again is not None and again.job_id == lease.job_id
    assert again.fence > lease.fence and again.attempt == 2
    assert not target.jobs.complete(lease.job_id, fence=lease.fence)  # stale holder


# --- receipts, feed, generations --------------------------------------------------


def test_026_FR_005_pg_lost_response_replays_without_a_second_effect(
    target: Target,
) -> None:
    t = target
    with t.receipts.command(t.uow, request(), authority, now=NOW) as cmd:
        result = cmd.accept(command_write(t, cmd), result={"title": "Secret title"})
    with t.receipts.command(t.uow, request(), authority, now=NOW) as retry:
        assert retry.replay == result
    assert t.count("task_documents") == t.count("jobs") == 1
    assert t.count("sync_change_transactions") == 1
    assert result["commit_seq"] == "1"


def test_026_FR_006_pg_a_receipt_failure_rolls_back_domain_feed_and_jobs(
    target: Target, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = target

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("receipt storage fault")

    monkeypatch.setattr(t.receipts, "_insert", fail)
    with (
        pytest.raises(RuntimeError, match="storage fault"),
        t.receipts.command(t.uow, request(), authority, now=NOW) as cmd,
    ):
        cmd.accept(command_write(t, cmd))
    for table in (
        "task_documents",
        "jobs",
        "sync_change_transactions",
        "sync_record_versions",
        "sync_scopes",
    ):
        assert t.count(table) == 0


def test_026_FR_005_pg_the_same_legacy_key_cannot_change_route_or_body(
    target: Target,
) -> None:
    t = target
    with t.receipts.command(t.uow, request(), authority, now=NOW) as cmd:
        cmd.accept([])
    for changed in (request(title="changed"), request(command="task.update")):
        with (
            pytest.raises(SyncCommandError, match="IDEMPOTENCY_KEY_REUSED"),
            t.receipts.command(t.uow, changed, authority, now=NOW),
        ):
            pytest.fail("conflicting command executed")


def test_026_FR_011_pg_current_authority_is_required_even_for_a_known_receipt(
    target: Target,
) -> None:
    t = target
    with t.receipts.command(t.uow, request(), authority, now=NOW) as cmd:
        cmd.accept([])

    def revoked(_unit):
        raise SyncCommandError("RESOURCE_NOT_FOUND")

    with (
        pytest.raises(SyncCommandError, match="RESOURCE_NOT_FOUND"),
        t.receipts.command(t.uow, request(), revoked, now=NOW),
    ):
        pytest.fail("revoked caller received a receipt")


def test_026_FR_011_pg_a_restored_generation_blocks_a_retained_outcome(
    target: Target,
) -> None:
    t = target
    with t.receipts.command(t.uow, request(), authority, now=NOW) as cmd:
        cmd.accept([])

    def restored(unit):
        return ScopeAuthority(unit.owner_id, "restored", "feed-r", "access-1", "pg-1")

    with (
        pytest.raises(SyncCommandError, match="RESET_REQUIRED"),
        t.receipts.command(t.uow, request(), restored, now=NOW),
    ):
        pytest.fail("old authority admitted restored work")


def test_026_FR_006_pg_noop_and_rejection_have_no_sequence_or_feed(
    target: Target,
) -> None:
    t = target
    with t.receipts.command(t.uow, request(), authority, now=NOW) as cmd:
        noop = cmd.accept([])
    with t.receipts.command(t.uow, request("rejected"), authority, now=NOW) as cmd:
        rejected = cmd.reject(DomainRefusal("entity_deleted", None, None, None))
    assert noop["commit_seq"] is rejected["commit_seq"] is None
    assert t.count("sync_change_transactions") == 0


def test_026_FR_006_pg_an_unfinished_command_cannot_commit_domain_writes(
    target: Target,
) -> None:
    t = target
    with (
        pytest.raises(SyncCommandError, match="COMMAND_UNFINISHED"),
        t.receipts.command(t.uow, request(), authority, now=NOW) as cmd,
    ):
        command_write(t, cmd)
    assert t.count("task_documents") == t.count("jobs") == 0


def test_026_FR_005_pg_receipt_expiry_redacts_content_but_keeps_the_outcome(
    target: Target,
) -> None:
    t = target
    with t.receipts.command(t.uow, request(), authority, now=NOW) as cmd:
        cmd.accept(command_write(t, cmd), result={"title": "Secret title"})
    later = NOW + timedelta(days=1)
    with t.receipts.command(t.uow, request(), authority, now=later) as cmd:
        assert cmd.replay["result"] is None
        assert cmd.replay["result_redacted"] is True
        assert cmd.replay["commit_seq"] == "1"
    assert t.count("sync_command_receipts") == 1


def test_026_FR_005_pg_legacy_refusal_replay_keeps_the_original_witness(
    target: Target,
) -> None:
    t = target
    refusal = DomainRefusal("revision_conflict", "title", ("task", ["task_a"]), 4)
    with t.receipts.command(t.uow, request("stale"), authority, now=NOW) as cmd:
        rejected = cmd.reject(refusal)
    assert rejected["error"]["message"] == "Command rejected."
    assert "_legacy_refusal_v1" not in json.dumps(rejected)
    expired = NOW + timedelta(hours=25)
    with t.receipts.command(t.uow, request("stale"), authority, now=expired) as retry:
        assert retry.replay is not None and retry.replay["result_redacted"] is True
        assert retry.replay_refusal == refusal
        with pytest.raises(SyncCommandError, match="COMMAND_ALREADY_TERMINAL"):
            retry.accept([])
    with t.uow.begin(RCPT) as unit:
        public = t.receipts.lookup(unit, retry.command_id, authority, now=NOW)
    assert public is not None and "_legacy_refusal_v1" not in json.dumps(public)


def test_026_FR_006_pg_repeated_rows_publish_the_final_image_and_keep_versions(
    target: Target,
) -> None:
    t = target
    with t.receipts.command(t.uow, request(), authority, now=NOW) as cmd:
        changes = command_write(t, cmd)
        final = {**changes[0], "value": {**changes[0]["value"], "details": "final"}}
        receipt = cmd.accept([*changes, final])
    assert receipt["result_versions"][0]["record_version"] == "1"
    with t.uow.begin(RCPT) as unit:
        tx = t.receipts.transactions(unit, authority, feed_generation="feed-1")
    assert len(tx[0]["changes"]) == 2
    task = next(r for r in tx[0]["changes"] if r["entity_type"] == "task")
    assert task["value"]["details"] == "final"
    with t.receipts.command(
        t.uow, request("delete", command="task.undo"), authority, now=NOW
    ) as cmd:
        t.store.delete_task(cmd.unit, RCPT, "task_first")
        deleted = cmd.accept(tombstone())
    assert deleted["result_versions"][0]["record_version"] == "2"
    after = NOW + timedelta(days=91)
    with t.uow.begin(RCPT) as unit:
        t.receipts.change_log.prune(unit, now=after)
    with t.receipts.command(
        t.uow, request("new", command="task.create"), authority, now=after
    ) as cmd:
        created = cmd.accept(command_write(t, cmd))
    assert created["result_versions"][0]["record_version"] == "3"


def test_026_FR_022_pg_deletion_redacts_receipts_and_requires_a_feed_reset(
    target: Target,
) -> None:
    t = target
    with t.receipts.command(t.uow, request(), authority, now=NOW) as cmd:
        accepted = cmd.accept(command_write(t, cmd), result={"title": "Secret title"})
    with t.receipts.command(
        t.uow, request("delete", command="task.undo"), authority, now=NOW
    ) as cmd:
        t.store.delete_task(cmd.unit, RCPT, "task_first")
        deleted = cmd.accept(tombstone(), result={"title": "Secret title"})
    assert deleted["result"] is None
    with t.receipts.command(t.uow, request(), authority, now=NOW) as cmd:
        assert cmd.replay["command_id"] == accepted["command_id"]
        assert cmd.replay["result"] is None and cmd.replay["result_redacted"]
    with (
        pytest.raises(SyncCommandError, match="RESET_REQUIRED"),
        t.uow.begin(RCPT) as unit,
    ):
        t.receipts.transactions(unit, authority, feed_generation="feed-1")


def test_026_FR_022_pg_redaction_pages_over_every_receipt_of_only_one_owner(
    target: Target,
) -> None:
    t = target
    binding = {"entity_type": "tag", "alias_id": "tag_a", "entity_id": "tag_a"}
    for index in range(70):  # more than one redaction page of 64
        with t.receipts.command(
            t.uow, request(f"batch-{index}"), authority, now=NOW
        ) as cmd:
            cmd.accept([], id_bindings=[binding])
    other = CommandRequest.legacy("user_other", "other", "tag.create", {"name": "O"})
    with t.receipts.command(t.uow, other, authority, now=NOW) as cmd:
        kept = cmd.accept([], id_bindings=[binding])
    with t.uow.begin(RCPT) as unit:
        t.receipts.change_log.redact_record(unit, "tag", ["tag_a"])
    with t.uow.begin(RCPT) as unit:
        rows = unit.connection.execute(
            "SELECT metadata, result FROM sync_command_receipts WHERE owner_id = %s",
            (RCPT,),
        ).fetchall()
    assert len(rows) == 70
    assert all(json.loads(r["metadata"])["result_redacted"] for r in rows)
    with t.uow.begin("user_other") as unit:
        public = t.receipts.lookup(unit, kept["command_id"], authority, now=NOW)
    assert public is not None and public["result_redacted"] is False


def test_026_SC_007_pg_a_job_request_needs_current_binding_and_a_live_fence(
    target: Target,
) -> None:
    t = target
    t.jobs.ensure_scheduled(
        job_type="receipt.test", dedup_key="claimed", run_at=NOW, scope=RCPT
    )
    lease = t.jobs.claim_due(
        owner="worker", types=("receipt.test",), now=NOW, lease_for=timedelta(minutes=1)
    )
    assert lease is not None
    gate = JobExecutionGate(t.jobs, owner_current=lambda o: o == RCPT, now=lambda: NOW)
    with gate.executing(lease):
        job_request = CommandRequest.job(RCPT, "task.create", {"title": "safe"})
        with t.receipts.command(t.uow, job_request, authority, now=NOW) as cmd:
            cmd.accept([])
    with (
        pytest.raises(SyncCommandError, match="TRUSTED_ORIGIN_REQUIRED"),
        t.receipts.command(t.uow, job_request, authority, now=NOW),
    ):
        pytest.fail("constructor-time provenance bypassed live binding")
    t.jobs.cancel(lease.job_id)
    with (
        gate.executing(lease),
        pytest.raises(StaleExecutorError),
        t.receipts.command(t.uow, job_request, authority, now=NOW),
    ):
        pytest.fail("retained receipt bypassed current job fence")
    assert t.count("sync_command_receipts") == 1


def test_026_SC_002_pg_commit_order_is_the_per_owner_sequence_order(
    target: Target,
) -> None:
    t = target
    first_inside, second_waiting = threading.Event(), threading.Event()
    order: list[str] = []

    def second() -> None:
        first_inside.wait()
        second_waiting.set()
        with t.receipts.command(t.uow, request("second"), authority, now=NOW) as cmd:
            order.append("second")
            cmd.accept([{**command_write(t, cmd)[0]}])

    worker = threading.Thread(target=second)
    worker.start()
    try:
        with t.receipts.command(t.uow, request("first"), authority, now=NOW) as cmd:
            first_inside.set()
            second_waiting.wait()
            time.sleep(0.3)
            assert order == []  # the second command is held behind the first
            order.append("first")
            first = cmd.accept(command_write(t, cmd)[:1])
    finally:
        worker.join(timeout=30)
    assert order == ["first", "second"]
    with t.uow.begin(RCPT) as unit:
        feed = t.receipts.transactions(unit, authority, feed_generation="feed-1")
        assert [tx["commit_seq"] for tx in feed] == ["1", "2"]
        assert feed[0]["source_command_id"] == first["command_id"]
        later = t.receipts.transactions(
            unit, authority, after="1", feed_generation="feed-1"
        )
    assert [tx["commit_seq"] for tx in later] == ["2"]


def test_026_SC_002_pg_a_killed_backend_before_commit_leaves_no_effect(
    target: Target,
) -> None:
    t = target
    with (
        pytest.raises(psycopg.OperationalError),
        t.receipts.command(t.uow, request(), authority, now=NOW) as cmd,
    ):
        changes = command_write(t, cmd)
        with psycopg.connect(t.dsn, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(%s)",
                (cmd.unit.connection.info.backend_pid,),
            )
        cmd.accept(changes)
    for table in ("task_documents", "jobs", "sync_change_transactions", "sync_scopes"):
        assert t.count(table) == 0
    with t.receipts.command(t.uow, request(), authority, now=NOW) as retry:
        assert retry.replay is None  # the effect never happened, so it runs once now
        result = retry.accept(command_write(t, retry))
    assert result["commit_seq"] == "1" and t.count("task_documents") == 1


def test_026_FR_022_pg_owner_purge_removes_every_protected_row(
    target: Target,
) -> None:
    t = target
    with t.receipts.command(t.uow, request(), authority, now=NOW) as cmd:
        cmd.accept(command_write(t, cmd))
    with pg.connect(t.dsn) as conn:
        pg.purge_owner(conn, RCPT)
    for table in (
        "task_documents",
        "jobs",
        "sync_scopes",
        "sync_command_receipts",
        "sync_legacy_keys",
        "sync_record_versions",
        "sync_change_transactions",
        "sync_change_records",
    ):
        assert t.count(table) == 0


def test_026_FR_015_pg_job_ledger_settles_retries_and_cancels_only_under_the_fence(
    target: Target,
) -> None:
    jobs = target.jobs
    with pytest.raises(ValueError, match="max_attempts"):
        jobs.ensure_scheduled(
            job_type=JOB_TYPE, dedup_key="bad", run_at=T0, max_attempts=0
        )
    assert jobs.claim_due(owner="w", types=(), now=T0) is None
    assert jobs.cancel("missing") is None and jobs.get("missing") is None

    # A queued intent is pulled forward; a cancelled one frees its identity.
    late = T0 + timedelta(hours=2)
    assert jobs.ensure_scheduled(job_type=JOB_TYPE, dedup_key="pf", run_at=late)
    assert not jobs.ensure_scheduled(
        job_type=JOB_TYPE, dedup_key="pf", run_at=T0, pull_forward=True
    )
    pulled = jobs.find_active("pf")
    assert pulled is not None and pulled.run_at == T0
    assert jobs.cancel(pulled.job_id) is JobStatus.CANCELLED
    assert jobs.find_active("pf") is None

    # A failed attempt backs off and retries; the exhausted one closes as failed.
    jobs.ensure_scheduled(
        job_type=JOB_TYPE, dedup_key="retry", run_at=T0, max_attempts=2
    )
    first = jobs.claim_due(owner="w", types=(JOB_TYPE,), now=T0)
    assert first is not None
    assert not jobs.fail(first.job_id, fence=first.fence, safe_error="boom!", now=T0)
    assert not jobs.fail(first.job_id, fence=first.fence, safe_error=None, now=T0)
    later = T0 + timedelta(minutes=1)
    second = jobs.claim_due(owner="w", types=(JOB_TYPE,), now=later)
    assert second is not None and second.attempt == 2
    assert jobs.fail(second.job_id, fence=second.fence, safe_error=None, now=T0)
    closed = jobs.get(second.job_id)
    assert closed is not None and closed.status is JobStatus.FAILED

    # An unknown outcome is parked and never claimed again.
    jobs.ensure_scheduled(job_type=JOB_TYPE, dedup_key="unsure", run_at=T0)
    unsure = jobs.claim_due(owner="w", types=(JOB_TYPE,), now=T0)
    assert unsure is not None
    assert not jobs.mark_uncertain(unsure.job_id, fence=unsure.fence + 99)
    assert jobs.mark_uncertain(unsure.job_id, fence=unsure.fence)
    parked = jobs.find_active("unsure")
    assert parked is not None and parked.status is JobStatus.RECONCILIATION_REQUIRED
    assert jobs.cancel(unsure.job_id) is JobStatus.CANCELLED
    assert jobs.cancel(unsure.job_id) is JobStatus.CANCELLED  # already closed

    # A running job that is cancelled has its result refused.
    running = claim(target, "running")
    assert jobs.cancel(running.job_id) is JobStatus.LEASED
    assert not jobs.complete(running.job_id, fence=running.fence)
    cancelled = jobs.get(running.job_id)
    assert cancelled is not None and cancelled.status is JobStatus.CANCELLED
    again = claim(target, "running-fail")
    jobs.cancel(again.job_id)
    assert not jobs.fail(again.job_id, fence=again.fence, safe_error=None, now=T0)


def test_026_FR_006_pg_feed_without_a_scope_or_with_redacted_values_is_refused(
    target: Target,
) -> None:
    t = target
    with (
        t.uow.begin(RCPT) as unit,
        pytest.raises(RepositoryError, match="RESET_REQUIRED"),
    ):
        t.receipts.change_log._next_sequence(unit)
    with t.receipts.command(t.uow, request(), authority, now=NOW) as cmd:
        cmd.accept(command_write(t, cmd))
    with t.uow.begin(RCPT) as unit:
        t.receipts.change_log.redact_record(unit, "task", ["task_first"])
        with pytest.raises(RepositoryError, match="RESET_REQUIRED"):
            t.receipts.change_log._transactions(unit)
