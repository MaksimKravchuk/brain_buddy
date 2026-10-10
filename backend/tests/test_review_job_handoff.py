"""Review maintenance and auto-park as a durable job adapter (spec 026 PR-22).

026-FR-015, 026-FR-016, 026-FR-022 and 026-SC-007. The real ``ReviewService``,
SQLite task store and job ledger run under a fake clock; the adapter is driven
by the real ``JobWorker`` (a test-only runner -- no scheduler is started) and
directly with a hand-built ``JobContext``. The existing ``app.main`` scheduler
stays the only live owner: nothing here registers the adapter in the app.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import IdempotencyRecord
from app.modules.tasks.jobs import (
    JobLease,
    JobOutcome,
    JobRepository,
    JobStatus,
)
from app.modules.tasks.jobs.domain import SYSTEM_SCOPE
from app.modules.tasks.jobs.execution import (
    JobExecutionGate,
    ScopeRevokedError,
    StaleExecutorError,
    WriterOrigin,
    current_execution,
    current_writer_origin,
    owner_write_lock,
)
from app.modules.tasks.jobs.review_adapter import (
    DEFAULT_CADENCE,
    REVIEW_MAINTENANCE_JOB_TYPE,
    REVIEW_MAINTENANCE_SCHEDULE_KEY,
    STALE_EXECUTOR,
    ReviewJobAdapter,
)
from app.modules.tasks.jobs.worker import JobContext, JobRegistry, JobWorker
from app.modules.tasks.review_service import ReviewService
from app.schemas.auth import User

from .conftest import FrozenClock
from .test_review_auto_park import acknowledge, keep_alive
from .test_review_decisions_api import ReviewApi

DAY = timedelta(days=1)
LEASE = timedelta(seconds=60)
OLD_KEY = "expired-idempotency-key"


def _is_live(user: User | None) -> bool:
    """The container's scope authority: resolves and has not begun deletion."""

    return user is not None and user.deletion_requested_at is None


class WorkerCrash(BaseException):
    """A process death: not an ``Exception``, so no handler may swallow it."""


class RecordingAdapter:
    """The real adapter behind the registry, remembering every lease it ran."""

    def __init__(self, inner: ReviewJobAdapter) -> None:
        self.inner = inner
        self.leases: list[JobLease] = []

    @property
    def job_type(self) -> str:
        return self.inner.job_type

    @property
    def schedule_key(self) -> str:
        return self.inner.schedule_key

    @property
    def cadence(self) -> timedelta:
        return self.inner.cadence

    def run(self, context: JobContext) -> JobOutcome:
        self.leases.append(context.lease)
        return self.inner.run(context)


class Rig:
    """One owner-bearing app, a fenced ledger and the adapter under test."""

    def __init__(self, api: ReviewApi, clock: FrozenClock) -> None:
        self.api = api
        self.clock = clock
        container = api.container
        users = container.user_repo
        # Jitter pinned to its ceiling so a retry is due exactly one cap later.
        self.ledger = JobRepository(container.task_repo.db_path, jitter=lambda c: c)
        self.gate = JobExecutionGate(
            self.ledger,
            owner_current=lambda owner_id: _is_live(users.get_by_id(owner_id)),
            owner_exists=lambda owner_id: users.get_by_id(owner_id) is not None,
            now=clock,
        )
        self.adapter = ReviewJobAdapter(container.review_service, self.gate)
        self.tap = RecordingAdapter(self.adapter)

    @property
    def container(self) -> Container:
        return self.api.container

    @property
    def review(self) -> ReviewService:
        return self.container.review_service

    def worker(self, owner: str = "w1") -> JobWorker:
        return JobWorker(
            self.ledger, JobRegistry([self.tap]), now=self.clock, owner_id=owner
        )

    def schedule_due(self, worker: JobWorker) -> None:
        assert worker.ensure_schedules(due_now=True) == 1

    def occurrence(self):  # type: ignore[no-untyped-def]
        record = self.ledger.find_active(REVIEW_MAINTENANCE_SCHEDULE_KEY)
        assert record is not None
        return record

    def seed_due_tasks(self, count: int = 1) -> list[str]:
        """Activate the owner, create Next tasks, and let the formulation lapse."""

        assert acknowledge(self.api).status_code == 200
        ids = [self.api.create(f"Due {i}", state="next")["id"] for i in range(count)]
        self.clock.advance(days=22)
        keep_alive(self.container)
        return ids

    def seed_expired_idempotency(self, owner_id: str) -> None:
        self.container.task_repo.save_idempotency(
            owner_id=owner_id,
            record=IdempotencyRecord(
                key=OLD_KEY,
                command="demo",
                request_hash="h",
                resource_id="r",
                response_body={},
                created_at=self.clock() - 3 * DAY,
            ),
        )

    def has_expired_idempotency(self, owner_id: str) -> bool:
        repo = self.container.task_repo
        return repo.get_idempotency(owner_id=owner_id, key=OLD_KEY) is not None

    def state_of(self, task_id: str) -> str:
        return str(self.api.stored(task_id).state)


@pytest.fixture
def rig(api_client: TestClient, frozen_clock: FrozenClock) -> Rig:
    review_api = ReviewApi(api_client, frozen_clock)
    review_api.flag("on")
    return Rig(review_api, frozen_clock)


@pytest.fixture
def two_owner_rig(
    second_api_client: tuple[TestClient, TestClient], frozen_clock: FrozenClock
) -> tuple[Rig, ReviewApi]:
    first, second = second_api_client
    return Rig(ReviewApi(first, frozen_clock), frozen_clock), ReviewApi(
        second, frozen_clock
    )


# --- schedule identity ------------------------------------------------------


def test_026_FR_015_schedule_identity_is_persisted_and_survives_a_restart(
    rig: Rig,
) -> None:
    """The ledger holds one stable schedule row that a restart re-asserts, not duplicates."""

    assert rig.adapter.job_type == REVIEW_MAINTENANCE_JOB_TYPE
    assert rig.adapter.cadence == DEFAULT_CADENCE == timedelta(seconds=60)

    assert rig.worker().ensure_schedules() == 1
    first = rig.occurrence()
    assert (first.job_type, first.scope) == (REVIEW_MAINTENANCE_JOB_TYPE, SYSTEM_SCOPE)
    assert first.dedup_key == REVIEW_MAINTENANCE_SCHEDULE_KEY
    assert first.status is JobStatus.QUEUED
    assert first.run_at == rig.clock() + DEFAULT_CADENCE

    # A restart: new connection, new adapter, new worker -- same identity.
    reopened = JobRepository(rig.container.task_repo.db_path)
    restarted = JobWorker(
        reopened,
        JobRegistry([ReviewJobAdapter(rig.review, rig.gate)]),
        now=rig.clock,
        owner_id="w-after-restart",
    )
    assert restarted.ensure_schedules() == 0
    assert reopened.find_active(REVIEW_MAINTENANCE_SCHEDULE_KEY).job_id == first.job_id  # type: ignore[union-attr]

    # The boot sweep is the same occurrence pulled forward, never a second one.
    assert restarted.ensure_schedules(due_now=True) == 0
    pulled = reopened.find_active(REVIEW_MAINTENANCE_SCHEDULE_KEY)
    assert pulled is not None and pulled.job_id == first.job_id
    assert pulled.run_at == rig.clock()


def test_026_FR_015_cadence_must_be_positive(rig: Rig) -> None:
    with pytest.raises(ValueError, match="positive"):
        ReviewJobAdapter(rig.review, rig.gate, cadence=timedelta())
    assert ReviewJobAdapter(
        rig.review, rig.gate, cadence=timedelta(minutes=5)
    ).cadence == timedelta(minutes=5)


def test_026_FR_015_no_second_scheduler_is_active_before_the_handoff(
    rig: Rig,
) -> None:
    """Building the app leaves the existing scheduler the only owner: the ledger
    holds no Review occurrence and no durable worker thread is running."""

    assert (
        rig.container.job_repository.find_active(REVIEW_MAINTENANCE_SCHEDULE_KEY)
        is None
    )
    assert not [t for t in threading.enumerate() if t.name == "durable-job-worker"]


# --- the effect runs through the existing port, under the lease -------------


def test_026_FR_016_sweep_runs_under_the_claimed_fence_with_unchanged_effects(
    rig: Rig, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto-park through the job equals the legacy sweep and binds lease and fence."""

    (task_id,) = rig.seed_due_tasks()
    before = rig.api.stored(task_id)
    seen: list[tuple[str, int, WriterOrigin]] = []
    real = rig.review.run_maintenance_sweep

    def spy():  # type: ignore[no-untyped-def]
        execution = current_execution()
        assert execution is not None
        seen.append((execution.job_id, execution.fence, current_writer_origin()))
        return real()

    monkeypatch.setattr(rig.review, "run_maintenance_sweep", spy)
    worker = rig.worker()
    rig.schedule_due(worker)
    claimed = rig.occurrence()

    with caplog.at_level(logging.INFO, logger="app.modules.tasks.review"):
        assert worker.run_once() is True

    settled = rig.ledger.get(claimed.job_id)
    assert settled is not None and settled.status is JobStatus.SUCCEEDED
    ((job_id, fence, origin),) = seen
    assert (job_id, fence, origin) == (settled.job_id, settled.fence, WriterOrigin.JOB)
    assert current_execution() is None  # the binding ended with the run

    parked = rig.api.stored(task_id)
    assert parked.state == "someday"
    assert parked.revision == before.revision + 1
    assert parked.parked is not None
    assert parked.parked.formulation_id == before.formulation_id
    acks = rig.container.task_repo.list_park_acks(rig.api.owner_id)
    assert [(a.task_id, a.source) for a in acks] == [(task_id, "sweep")]
    lines = [r.getMessage() for r in caplog.records]
    assert any(line.startswith("review_sweep owners=1 parked=1") for line in lines)

    nxt = rig.occurrence()
    assert nxt.job_id != claimed.job_id
    assert nxt.status is JobStatus.QUEUED
    assert nxt.run_at == rig.clock() + DEFAULT_CADENCE


# --- crash and retry --------------------------------------------------------


def test_026_SC_007_failed_sweep_retries_without_repeating_or_leaking(
    rig: Rig, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure after retention is retried; retention is not redone, the park lands once."""

    (task_id,) = rig.seed_due_tasks()
    rig.seed_expired_idempotency(rig.api.owner_id)
    real = rig.review.run_auto_park_sweep
    calls: list[int] = []

    def flaky(now):  # type: ignore[no-untyped-def]
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("SENTINEL-TASK-TITLE")
        return real(now)

    monkeypatch.setattr(rig.review, "run_auto_park_sweep", flaky)
    worker = rig.worker()
    rig.schedule_due(worker)

    with caplog.at_level(logging.DEBUG):
        assert worker.run_once() is True
        retry = rig.occurrence()
        assert (retry.status, retry.attempts) == (JobStatus.QUEUED, 1)
        assert retry.last_error == "RuntimeError"
        # Retention had already committed; the exposure part had not started.
        assert not rig.has_expired_idempotency(rig.api.owner_id)
        assert rig.state_of(task_id) == "next"

        rig.clock.advance(seconds=2)  # past the pinned 1 s backoff
        assert worker.run_once() is True

    assert rig.state_of(task_id) == "someday"
    assert len(rig.container.task_repo.list_park_acks(rig.api.owner_id)) == 1
    assert len(calls) == 2
    assert "SENTINEL-TASK-TITLE" not in caplog.text
    assert "SENTINEL-TASK-TITLE" not in (retry.last_error or "")


def test_026_SC_007_lost_worker_is_reclaimed_and_its_late_writes_are_refused(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A worker dies between batches; the next claimant parks each task exactly once."""

    # One task per owner-locked batch (each batch is one transaction), so the
    # death lands after the first batch committed and before the second began.
    monkeypatch.setattr("app.modules.tasks.review_service.SWEEP_BATCH", 1)
    first_id, second_id = rig.seed_due_tasks(2)
    revisions = {t: rig.api.stored(t).revision for t in (first_id, second_id)}
    real = rig.review._sweep_park
    parks: list[int] = []

    def dies_on_second(task, *, owner_id):  # type: ignore[no-untyped-def]
        parks.append(1)
        if len(parks) == 2:
            raise WorkerCrash()
        return real(task, owner_id=owner_id)

    monkeypatch.setattr(rig.review, "_sweep_park", dies_on_second)
    w1 = rig.worker("w1")
    rig.schedule_due(w1)
    with pytest.raises(WorkerCrash):
        w1.run_once()

    crashed = rig.occurrence()
    assert (crashed.status, crashed.lease_owner) == (JobStatus.LEASED, "w1")
    parked_now = {t for t in (first_id, second_id) if rig.state_of(t) == "someday"}
    assert len(parked_now) == 1  # the partial effect that must not repeat
    (old_lease,) = rig.tap.leases

    rig.clock.advance(LEASE + timedelta(seconds=1))
    w2 = rig.worker("w2")
    assert w2.run_once() is False  # recovers the lapsed lease into its backoff
    stale = rig.occurrence()
    assert (stale.status, stale.fence) == (JobStatus.QUEUED, old_lease.fence)

    # The dead worker wakes up holding its old claim: refused at the first write.
    settings_before = rig.container.task_repo.get_review_settings(rig.api.owner_id)
    zombie = rig.adapter.run(JobContext(old_lease, lambda: False))
    assert zombie == JobOutcome(safe_error=STALE_EXECUTOR)
    assert {t for t in (first_id, second_id) if rig.state_of(t) == "someday"} == (
        parked_now
    )
    assert (
        rig.container.task_repo.get_review_settings(rig.api.owner_id) == settings_before
    )

    rig.clock.advance(seconds=2)
    assert w2.run_once() is True
    done = rig.ledger.get(stale.job_id)
    assert done is not None and done.status is JobStatus.SUCCEEDED
    assert done.fence > old_lease.fence
    assert done.attempts == 2

    for task_id in (first_id, second_id):
        assert rig.state_of(task_id) == "someday"
        assert rig.api.stored(task_id).revision == revisions[task_id] + 1
    acks = rig.container.task_repo.list_park_acks(rig.api.owner_id)
    assert sorted(a.task_id for a in acks) == sorted([first_id, second_id])


def test_026_SC_007_a_lost_claim_does_nothing_before_the_first_write(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A context that already knows it lost the job starts no effect at all."""

    (task_id,) = rig.seed_due_tasks()
    calls: list[int] = []
    monkeypatch.setattr(rig.review, "run_maintenance_sweep", lambda: calls.append(1))
    worker = rig.worker()
    rig.schedule_due(worker)
    lease = rig.ledger.claim_due(
        owner="w1", types=(REVIEW_MAINTENANCE_JOB_TYPE,), now=rig.clock()
    )
    assert lease is not None

    outcome = rig.adapter.run(JobContext(lease, lambda: True))

    assert outcome == JobOutcome(safe_error=STALE_EXECUTOR)
    assert calls == []
    assert rig.state_of(task_id) == "next"


def test_026_SC_007_cancelled_job_is_refused_at_the_write_port_mid_run(
    rig: Rig,
) -> None:
    """Cancellation reaches the sweep through the fence recheck under the lock."""

    (task_id,) = rig.seed_due_tasks()
    rig.seed_expired_idempotency(rig.api.owner_id)
    worker = rig.worker()
    rig.schedule_due(worker)
    lease = rig.ledger.claim_due(
        owner="w1", types=(REVIEW_MAINTENANCE_JOB_TYPE,), now=rig.clock()
    )
    assert lease is not None
    assert rig.ledger.cancel(lease.job_id) is JobStatus.LEASED

    # The cancel flag is not visible to this context; only the port can refuse.
    outcome = rig.adapter.run(JobContext(lease, lambda: False))

    assert outcome == JobOutcome(safe_error=STALE_EXECUTOR)
    assert rig.state_of(task_id) == "next"
    assert rig.has_expired_idempotency(rig.api.owner_id)


# --- retention is independent of the flag and of owner activity -------------


def _seed_retention_rows(rig: Rig, owner_id: str) -> None:
    rig.seed_expired_idempotency(owner_id)
    for days_ago in (36, 34):
        rig.container.task_repo.save_navigator_usage(
            rd.NavigatorUsageDocument(
                owner_id=owner_id,
                day=(rig.clock() - days_ago * DAY).date(),
                calls=1,
            )
        )


def test_026_FR_022_retention_runs_with_the_flag_off_for_inactive_owners(
    two_owner_rig: tuple[Rig, ReviewApi],
) -> None:
    """Flag OFF: both owners lose expired rows; exposure (auto-park) stays gated."""

    rig, idle = two_owner_rig
    (task_id,) = rig.seed_due_tasks()  # the first owner activated Review
    _seed_retention_rows(rig, rig.api.owner_id)
    _seed_retention_rows(rig, idle.owner_id)  # never activated, long absent
    rig.api.flag("off")
    worker = rig.worker()
    rig.schedule_due(worker)

    assert worker.run_once() is True

    repo = rig.container.task_repo
    kept_day = (rig.clock() - 34 * DAY).date()
    for owner_id in (rig.api.owner_id, idle.owner_id):
        assert not rig.has_expired_idempotency(owner_id)
        assert [u.day for u in repo.list_navigator_usage(owner_id)] == [kept_day]
    assert repo.get_review_settings(idle.owner_id) is None  # nothing created
    assert rig.state_of(task_id) == "next"  # the flag still gates exposure
    settled = rig.ledger.find_active(REVIEW_MAINTENANCE_SCHEDULE_KEY)
    assert settled is not None and settled.status is JobStatus.QUEUED


def test_026_SC_007_a_removed_owner_is_not_written_while_others_are_swept(
    two_owner_rig: tuple[Rig, ReviewApi],
) -> None:
    """Scope authority holds for retention too: a purged owner is skipped, the run succeeds."""

    rig, gone = two_owner_rig
    rig.seed_expired_idempotency(rig.api.owner_id)
    rig.seed_expired_idempotency(gone.owner_id)
    rig.container.user_repo.delete(gone.owner_id)
    worker = rig.worker()
    rig.schedule_due(worker)
    claimed = rig.occurrence()

    assert worker.run_once() is True

    assert not rig.has_expired_idempotency(rig.api.owner_id)
    assert rig.has_expired_idempotency(gone.owner_id)
    settled = rig.ledger.get(claimed.job_id)
    assert settled is not None and settled.status is JobStatus.SUCCEEDED


def test_026_FR_022_retention_cleans_a_deletion_pending_owner_but_never_parks_it(
    two_owner_rig: tuple[Rig, ReviewApi],
) -> None:
    """Grace period: expired rows still go on schedule, while exposure stays revoked."""

    rig, pending = two_owner_rig
    rig.api.flag("on")
    assert acknowledge(rig.api).status_code == 200
    assert acknowledge(pending).status_code == 200
    live_task = rig.api.create("Live", state="next")["id"]
    pending_task = pending.create("Pending", state="next")["id"]
    rig.clock.advance(days=22)
    keep_alive(rig.container)
    _seed_retention_rows(rig, rig.api.owner_id)
    _seed_retention_rows(rig, pending.owner_id)
    rig.container.user_repo.mutate(
        pending.owner_id,
        lambda fresh: fresh.model_copy(update={"deletion_requested_at": rig.clock()}),
    )
    worker = rig.worker()
    rig.schedule_due(worker)

    assert worker.run_once() is True

    repo = rig.container.task_repo
    kept_day = (rig.clock() - 34 * DAY).date()
    for owner_id in (rig.api.owner_id, pending.owner_id):
        assert not rig.has_expired_idempotency(owner_id)
        assert [u.day for u in repo.list_navigator_usage(owner_id)] == [kept_day]
    assert rig.state_of(live_task) == "someday"
    assert pending.stored(pending_task).state == "next"
    assert repo.list_park_acks(pending.owner_id) == []


def test_026_FR_022_cleanup_authority_still_needs_the_fence_and_the_scope(
    rig: Rig,
) -> None:
    """Cleanup widens only the owner check: stale, cancelled or out-of-scope is refused."""

    repo = rig.container.task_repo
    owner_id = rig.api.owner_id
    pending = rig.container.user_repo
    pending.mutate(
        owner_id,
        lambda fresh: fresh.model_copy(update={"deletion_requested_at": rig.clock()}),
    )
    worker = rig.worker()
    rig.schedule_due(worker)
    lease = rig.ledger.claim_due(
        owner="w1", types=(REVIEW_MAINTENANCE_JOB_TYPE,), now=rig.clock()
    )
    assert lease is not None

    with rig.gate.executing(lease):
        with owner_write_lock(repo, owner_id, cleanup=True):
            pass  # pending deletion: cleanup is allowed ...
        with pytest.raises(ScopeRevokedError), owner_write_lock(repo, owner_id):
            pass  # ... any other write is not
        with (
            pytest.raises(ScopeRevokedError),
            owner_write_lock(repo, "user_other", cleanup=True),
        ):
            pass  # an owner that does not exist is never cleaned up

    rig.ledger.cancel(lease.job_id)
    with (
        rig.gate.executing(lease),
        pytest.raises(StaleExecutorError),
        owner_write_lock(repo, owner_id, cleanup=True),
    ):
        pass
