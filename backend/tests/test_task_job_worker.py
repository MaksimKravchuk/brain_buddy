"""Durable job worker: scheduling, leasing, settling, wake and shutdown.

Spec 026 PR-64a (026-FR-014, 026-FR-015, 026-SC-007). The ledger is the real
SQLite file; adapters are fakes whose effect is a counter, so a double run is
visible. A fake clock drives every due time and lease expiry.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.container import Container
from app.modules.tasks.jobs import JobOutcome, JobRepository, JobStatus
from app.modules.tasks.jobs.domain import BACKOFF_CAPS
from app.modules.tasks.jobs.worker import JobContext, JobRegistry, JobWorker

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LEASE = timedelta(seconds=60)
WAIT = 5.0


class Clock:
    def __init__(self) -> None:
        self.moment = T0

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += timedelta(seconds=seconds)


class FakeAdapter:
    """Counts runs; ``script`` is consumed one entry per run, then ``ok``."""

    def __init__(
        self,
        job_type: str = "maintenance.demo",
        *,
        cadence: timedelta | None = timedelta(minutes=1),
        script: tuple[str, ...] = (),
        block: bool = False,
    ) -> None:
        self.job_type = job_type
        self.schedule_key = f"schedule:{job_type}"
        self.cadence = cadence
        self.script = list(script)
        self.block = block
        self.runs = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.abandoned_while_running: bool | None = None

    def run(self, context: JobContext) -> JobOutcome:
        self.runs += 1
        self.entered.set()
        if self.block:
            self.release.wait(timeout=WAIT)
            self.abandoned_while_running = context.should_abandon()
        step = self.script.pop(0) if self.script else "ok"
        if step == "raise":
            raise RuntimeError("secret payload detail")
        if step == "error":
            return JobOutcome(safe_error="provider_down")
        if step == "uncertain":
            return JobOutcome(uncertain=True, safe_error="timeout")
        return JobOutcome()


@pytest.fixture()
def db_path(data_dir: Path) -> Path:
    return data_dir / "tasks.sqlite3"


@pytest.fixture()
def ledger(db_path: Path) -> JobRepository:
    # Full jitter pinned to its ceiling so backoff is exact.
    return JobRepository(db_path, jitter=lambda cap: cap)


@pytest.fixture()
def clock() -> Clock:
    return Clock()


def _worker(
    ledger: JobRepository,
    clock: Clock,
    *adapters: FakeAdapter,
    owner: str = "w1",
    **kwargs: object,
) -> JobWorker:
    return JobWorker(
        ledger,
        JobRegistry(adapters),
        now=clock,
        owner_id=owner,
        **kwargs,  # type: ignore[arg-type]
    )


def _wait_for(condition: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {what}")


def _active(ledger: JobRepository, adapter: FakeAdapter):  # type: ignore[no-untyped-def]
    return ledger.find_active(adapter.schedule_key)


# --- registry and construction ---------------------------------------------


def test_026_FR_015_registry_refuses_a_second_adapter_for_one_type() -> None:
    """A job type has exactly one registered adapter."""
    registry = JobRegistry([FakeAdapter("a")])
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeAdapter("a"))
    assert registry.types == ("a",)
    assert registry.get("missing") is None


def test_026_FR_015_heartbeat_must_be_shorter_than_the_lease(
    ledger: JobRepository, clock: Clock
) -> None:
    """A heartbeat as long as the lease could never keep it alive."""
    with pytest.raises(ValueError, match="shorter"):
        _worker(
            ledger,
            clock,
            FakeAdapter(),
            lease_for=timedelta(seconds=10),
            heartbeat_every=timedelta(seconds=10),
        )


# --- scheduling and single execution ---------------------------------------


def test_026_FR_015_boot_scheduling_is_idempotent_and_not_early(
    ledger: JobRepository, clock: Clock
) -> None:
    """Boot creates one pending occurrence per recurring adapter, one cadence out."""
    adapter = FakeAdapter()
    one_shot = FakeAdapter("maintenance.once", cadence=None)
    worker = _worker(ledger, clock, adapter, one_shot)

    assert worker.ensure_schedules() == 1  # the one-shot is not scheduled
    assert worker.ensure_schedules() == 0
    assert _worker(ledger, clock, adapter, owner="w2").ensure_schedules() == 0

    record = _active(ledger, adapter)
    assert record is not None and record.status is JobStatus.QUEUED
    assert record.run_at == T0 + timedelta(minutes=1)
    assert worker.run_once() is False
    assert adapter.runs == 0
    assert _active(ledger, one_shot) is None


def test_026_FR_015_due_now_boot_makes_the_occurrence_due_and_runs_it_once(
    ledger: JobRepository, clock: Clock
) -> None:
    """Each due job runs exactly once per occurrence, then waits its cadence."""
    first, second = FakeAdapter("a"), FakeAdapter("b")
    worker = _worker(ledger, clock, first, second)
    worker.ensure_schedules()
    worker.ensure_schedules(due_now=True)  # pulls the queued occurrences forward

    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is False
    assert (first.runs, second.runs) == (1, 1)

    # The next occurrence is one cadence after the finished run.
    clock.advance(59)
    assert worker.run_once() is False
    clock.advance(2)
    assert worker.run_once() is True and worker.run_once() is True
    assert (first.runs, second.runs) == (2, 2)


def test_026_FR_015_one_shot_job_is_not_rescheduled(
    ledger: JobRepository, clock: Clock
) -> None:
    """A job without a cadence runs once and leaves no successor."""
    adapter = FakeAdapter("maintenance.once", cadence=None)
    worker = _worker(ledger, clock, adapter)
    worker.ensure_schedules(due_now=True)

    assert worker.run_once() is True
    clock.advance(3600)
    assert worker.run_once() is False
    assert _active(ledger, adapter) is None
    assert adapter.runs == 1


# --- retry, backoff, exhaustion --------------------------------------------


def test_026_FR_015_failure_retries_with_bounded_backoff_then_succeeds(
    ledger: JobRepository, clock: Clock
) -> None:
    """A failed attempt returns to the queue after backoff and is retried."""
    adapter = FakeAdapter(script=("raise", "error", "ok"))
    worker = _worker(ledger, clock, adapter)
    worker.ensure_schedules(due_now=True)

    assert worker.run_once() is True  # raises
    record = _active(ledger, adapter)
    assert record is not None and record.status is JobStatus.QUEUED
    # The exception text (which may carry payloads) is never stored.
    assert record.last_error == "RuntimeError"
    assert record.run_at == clock() + timedelta(seconds=BACKOFF_CAPS[0])

    clock.advance(BACKOFF_CAPS[0] - 0.5)
    assert worker.run_once() is False  # still backing off
    clock.advance(0.5)
    assert worker.run_once() is True  # reports safe_error
    record = _active(ledger, adapter)
    assert record is not None and record.last_error == "provider_down"
    assert record.run_at == clock() + timedelta(seconds=BACKOFF_CAPS[1])

    clock.advance(BACKOFF_CAPS[1])
    assert worker.run_once() is True  # succeeds
    assert adapter.runs == 3
    record = _active(ledger, adapter)
    assert record is not None and record.attempts == 0
    assert record.run_at == clock() + adapter.cadence  # type: ignore[operator]


def test_026_FR_015_exhausted_retries_end_failed_and_the_schedule_continues(
    ledger: JobRepository, clock: Clock
) -> None:
    """After the attempt budget the failure stays visible and a new one is queued."""
    adapter = FakeAdapter(script=("raise",) * 5)
    worker = _worker(ledger, clock, adapter)
    worker.ensure_schedules(due_now=True)
    first = _active(ledger, adapter)
    assert first is not None

    for _ in range(5):
        clock.advance(max(BACKOFF_CAPS) + 1)
        assert worker.run_once() is True
    assert adapter.runs == 5

    failed = ledger.get(first.job_id)
    assert failed is not None and failed.status is JobStatus.FAILED
    successor = _active(ledger, adapter)
    assert successor is not None and successor.job_id != first.job_id
    assert successor.run_at == clock() + adapter.cadence  # type: ignore[operator]

    clock.advance(61)
    assert worker.run_once() is True  # the schedule still works
    assert adapter.runs == 6


# --- uncertain outcomes -----------------------------------------------------


def test_026_SC_007_uncertain_outcome_is_parked_and_never_retried(
    ledger: JobRepository, clock: Clock
) -> None:
    """An effect with unknown outcome waits for a person; nothing runs it again."""
    adapter = FakeAdapter(script=("uncertain",))
    worker = _worker(ledger, clock, adapter)
    worker.ensure_schedules(due_now=True)
    first = _active(ledger, adapter)
    assert first is not None

    assert worker.run_once() is True
    parked = ledger.get(first.job_id)
    assert parked is not None
    assert parked.status is JobStatus.RECONCILIATION_REQUIRED
    assert parked.last_error == "timeout"

    clock.advance(24 * 3600)
    assert worker.run_once() is False
    # Not rescheduled either: the parked job still holds the schedule identity.
    assert worker.ensure_schedules() == 0 and worker.ensure_schedules(due_now=True) == 0
    assert worker.run_once() is False
    assert adapter.runs == 1

    # Only an explicit decision releases it, with a fresh attempt budget.
    assert ledger.resolve_reconciliation(first.job_id, decision="retry", run_at=T0)
    clock.advance(1)
    assert worker.run_once() is True
    assert adapter.runs == 2


# --- fencing, leases, two workers ------------------------------------------


def test_026_SC_007_stale_holder_is_fenced_after_reclaim(
    ledger: JobRepository, clock: Clock
) -> None:
    """A loses its lease, B reclaims; A's late result is refused."""
    a_adapter = FakeAdapter(block=True)
    b_adapter = FakeAdapter()
    worker_a = _worker(ledger, clock, a_adapter, owner="a")
    worker_b = _worker(ledger, clock, b_adapter, owner="b")
    worker_a.ensure_schedules(due_now=True)
    job = _active(ledger, a_adapter)
    assert job is not None

    runner = threading.Thread(target=worker_a.run_once)
    runner.start()
    assert a_adapter.entered.wait(WAIT)
    assert worker_b.run_once() is False  # lease still live

    clock.advance(LEASE.total_seconds() + 1)  # A's heartbeat never fired
    assert worker_b.run_once() is False  # expired lease requeued behind backoff
    clock.advance(1)  # pinned full jitter: 1s cap after one attempt
    assert worker_b.run_once() is True
    assert b_adapter.runs == 1

    a_adapter.release.set()
    runner.join(WAIT)
    assert not runner.is_alive()

    # A was told to stop, its settle changed nothing, and nothing ran twice.
    assert a_adapter.abandoned_while_running is True
    settled = ledger.get(job.job_id)
    assert settled is not None and settled.status is JobStatus.SUCCEEDED
    assert a_adapter.runs == 1 and b_adapter.runs == 1
    successor = _active(ledger, b_adapter)
    assert successor is not None and successor.status is JobStatus.QUEUED
    assert successor.job_id != job.job_id


def test_026_SC_007_heartbeat_keeps_a_long_job_from_being_reclaimed(
    ledger: JobRepository, clock: Clock
) -> None:
    """While the heartbeat is alive the lease slides forward and B cannot claim."""
    adapter = FakeAdapter(block=True)
    worker_a = _worker(
        ledger, clock, adapter, owner="a", heartbeat_every=timedelta(milliseconds=10)
    )
    worker_b = _worker(ledger, clock, FakeAdapter(), owner="b")
    worker_a.ensure_schedules(due_now=True)
    job = _active(ledger, adapter)
    assert job is not None

    runner = threading.Thread(target=worker_a.run_once)
    runner.start()
    assert adapter.entered.wait(WAIT)
    clock.advance(LEASE.total_seconds() + 1)

    def extended() -> bool:
        record = ledger.get(job.job_id)
        return record is not None and record.lease_until == clock() + LEASE

    _wait_for(extended, "the heartbeat to extend the lease")
    assert worker_b.run_once() is False

    adapter.release.set()
    runner.join(WAIT)
    record = ledger.get(job.job_id)
    assert record is not None and record.status is JobStatus.SUCCEEDED


def test_026_SC_007_two_workers_never_run_the_same_job(
    ledger: JobRepository, clock: Clock
) -> None:
    """Racing runners over a shared ledger run each due job exactly once."""
    types = [f"maintenance.t{i}" for i in range(6)]
    adapters_a = [FakeAdapter(t) for t in types]
    adapters_b = [FakeAdapter(t) for t in types]
    worker_a = _worker(ledger, clock, *adapters_a, owner="a")
    worker_b = _worker(ledger, clock, *adapters_b, owner="b")
    worker_a.ensure_schedules(due_now=True)

    barrier = threading.Barrier(2)

    def drain(worker: JobWorker) -> None:
        barrier.wait(WAIT)
        while worker.run_once():
            pass

    threads = [threading.Thread(target=drain, args=(w,)) for w in (worker_a, worker_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT)

    for first, second in zip(adapters_a, adapters_b, strict=True):
        assert first.runs + second.runs == 1


def test_026_SC_007_workers_share_the_container_ledger(container: Container) -> None:
    """The wired Container.job_repository is a valid ledger for the worker."""
    clock = Clock()
    adapter = FakeAdapter()
    worker = _worker(container.job_repository, clock, adapter)
    worker.ensure_schedules(due_now=True)
    assert worker.run_once() is True
    assert adapter.runs == 1


# --- wake -------------------------------------------------------------------


def test_026_FR_014_wake_pulls_the_occurrence_forward_without_running_inline(
    ledger: JobRepository, clock: Clock
) -> None:
    """A wake makes a type due now; the loop, not the caller, runs it."""
    adapter = FakeAdapter()
    other = FakeAdapter("maintenance.other")
    worker = _worker(ledger, clock, adapter, other)
    worker.ensure_schedules()
    assert worker.run_once() is False

    worker.wake("maintenance.demo")
    worker.wake("not.registered")  # ignored
    assert adapter.runs == 0

    assert worker.run_once() is True
    assert (adapter.runs, other.runs) == (1, 0)
    assert worker.run_once() is False


def test_026_FR_014_wake_does_not_disturb_a_running_job(
    ledger: JobRepository, clock: Clock
) -> None:
    """Waking a leased type neither duplicates nor re-runs it."""
    adapter = FakeAdapter(block=True)
    worker = _worker(ledger, clock, adapter)
    worker.ensure_schedules(due_now=True)
    runner = threading.Thread(target=worker.run_once)
    runner.start()
    assert adapter.entered.wait(WAIT)

    worker.wake(adapter.job_type)
    assert _worker(ledger, clock, adapter, owner="w2").run_once() is False

    adapter.release.set()
    runner.join(WAIT)
    assert adapter.runs == 1


def test_026_FR_014_wake_rouses_an_idle_loop(ledger: JobRepository) -> None:
    """A started loop that is idle for a long poll runs a woken job promptly."""
    adapter = FakeAdapter(cadence=timedelta(hours=1))
    worker = JobWorker(
        ledger, JobRegistry([adapter]), idle_poll_seconds=60.0, owner_id="loop"
    )
    assert worker.start() is True
    assert worker.start() is False  # one loop per worker
    try:
        time.sleep(0.1)
        assert adapter.runs == 0
        worker.wake(adapter.job_type)
        assert adapter.entered.wait(WAIT)
    finally:
        assert worker.shutdown(timeout=WAIT) is True
    assert adapter.runs == 1
    assert worker.running is False


# --- loop resilience and shutdown ------------------------------------------


def test_026_FR_015_loop_survives_a_failing_job_and_a_failing_pass(
    ledger: JobRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bad job or a briefly unavailable ledger does not end the loop."""
    bad = FakeAdapter("maintenance.bad", script=("raise",))
    good = FakeAdapter("maintenance.good", cadence=timedelta(hours=1))
    worker = JobWorker(
        ledger,
        JobRegistry([bad, good]),
        idle_poll_seconds=0.01,
        reconcile_seconds=0.01,
        owner_id="loop",
    )
    real = ledger.claim_due
    calls = {"n": 0}

    def flaky(**kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database is locked")
        return real(**kwargs)

    monkeypatch.setattr(ledger, "claim_due", flaky)
    worker.start()
    try:
        worker.wake(bad.job_type)
        worker.wake(good.job_type)
        assert good.entered.wait(WAIT)
        assert bad.entered.wait(WAIT)
    finally:
        assert worker.shutdown(timeout=WAIT) is True
    assert calls["n"] > 1


def test_026_SC_007_shutdown_is_bounded_and_leaves_the_lease_reclaimable(
    ledger: JobRepository, clock: Clock
) -> None:
    """Shutdown returns within its grace even mid-job; the lease then lapses."""
    adapter = FakeAdapter(block=True)
    worker = _worker(
        ledger,
        clock,
        adapter,
        owner="old",
        idle_poll_seconds=0.01,
        heartbeat_every=timedelta(milliseconds=10),
    )
    worker.ensure_schedules(due_now=True)
    job = _active(ledger, adapter)
    assert job is not None
    worker.start()
    assert adapter.entered.wait(WAIT)

    started = time.monotonic()
    assert worker.shutdown(timeout=0.2) is False  # job outlived the grace
    assert time.monotonic() - started < 2.0
    assert worker.running is True  # a thread cannot be killed; it is abandoned

    # Heartbeats stop, so the lease no longer slides forward.
    time.sleep(0.1)
    frozen = ledger.get(job.job_id)
    assert frozen is not None and frozen.status is JobStatus.LEASED
    clock.advance(30)
    time.sleep(0.1)
    again = ledger.get(job.job_id)
    assert again is not None and again.lease_until == frozen.lease_until

    # Past the lease, a new runner reclaims it; the old result is then fenced.
    clock.advance(LEASE.total_seconds())
    successor = FakeAdapter()
    new_runner = _worker(ledger, clock, successor, owner="new")
    assert new_runner.run_once() is False  # expired lease requeued behind backoff
    clock.advance(1)  # pinned full jitter: 1s cap after one attempt
    assert new_runner.run_once() is True
    adapter.release.set()
    _wait_for(lambda: not worker.running, "the abandoned loop to exit")
    assert adapter.abandoned_while_running is True
    assert successor.runs == 1
    final = ledger.get(job.job_id)
    assert final is not None and final.status is JobStatus.SUCCEEDED


def test_026_SC_007_idle_shutdown_is_prompt_and_restartable(
    ledger: JobRepository,
) -> None:
    """An idle worker stops at once, and the same object can start again."""
    adapter = FakeAdapter(cadence=timedelta(hours=1))
    worker = JobWorker(
        ledger, JobRegistry([adapter]), idle_poll_seconds=60.0, owner_id="idle"
    )
    assert worker.shutdown() is True  # never started

    worker.start()
    started = time.monotonic()
    assert worker.shutdown(timeout=WAIT) is True
    assert time.monotonic() - started < 2.0
    assert worker.running is False

    assert worker.start() is True
    assert worker.shutdown(timeout=WAIT) is True
