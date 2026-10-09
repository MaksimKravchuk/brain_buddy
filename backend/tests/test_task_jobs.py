"""Durable job ledger: leases, fencing, retry budgets and uncertain outcomes.

Spec 026 PR-20 (026-FR-015, 026-FR-022, 026-SC-007). Every test runs against the
real SQLite file, with a fresh ``JobRepository`` where restart matters, because
the guarantees under test are the ones the database transaction provides.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.container import Container
from app.modules.tasks.jobs import JobRepository, JobStatus

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LEASE = timedelta(seconds=60)
TYPE = "maintenance.demo"
KEY = "demo:schedule"


@pytest.fixture()
def db_path(data_dir: Path) -> Path:
    return data_dir / "tasks.sqlite3"


@pytest.fixture()
def jobs(db_path: Path) -> JobRepository:
    # Full jitter pinned to its ceiling so backoff is exact in assertions.
    return JobRepository(db_path, jitter=lambda cap: cap)


def _schedule(
    jobs: JobRepository, *, key: str = KEY, run_at: datetime = T0, **kwargs: object
) -> bool:
    return jobs.ensure_scheduled(
        job_type=TYPE,
        dedup_key=key,
        run_at=run_at,
        **kwargs,  # type: ignore[arg-type]
    )


def _claim(jobs: JobRepository, now: datetime = T0, owner: str = "w1"):
    return jobs.claim_due(owner=owner, types=(TYPE,), now=now, lease_for=LEASE)


# --- scheduling and dedup ---------------------------------------------------


def test_026_FR_015_dedup_key_schedules_one_active_job(jobs: JobRepository) -> None:
    assert _schedule(jobs) is True
    assert _schedule(jobs) is False
    first = jobs.find_active(KEY)
    assert first is not None and first.status is JobStatus.QUEUED

    lease = _claim(jobs)
    assert lease is not None
    # A running job still occupies its identity.
    assert _schedule(jobs) is False

    assert jobs.complete(lease.job_id, fence=lease.fence) is True
    # Once settled, the next occurrence of the same schedule may be created.
    assert _schedule(jobs, run_at=T0 + timedelta(hours=1)) is True
    second = jobs.find_active(KEY)
    assert second is not None and second.job_id != first.job_id


def test_026_FR_015_dedup_is_scoped(jobs: JobRepository) -> None:
    assert _schedule(jobs, scope="a") is True
    assert _schedule(jobs, scope="b") is True
    assert _schedule(jobs, scope="a") is False


def test_026_FR_015_pull_forward_only_moves_queued_jobs_earlier(
    jobs: JobRepository,
) -> None:
    later = T0 + timedelta(hours=1)
    _schedule(jobs, run_at=later)

    assert (
        _schedule(jobs, run_at=later + timedelta(hours=1), pull_forward=True) is False
    )
    record = jobs.find_active(KEY)
    assert record is not None and record.run_at == later  # never pushed later

    assert _schedule(jobs, run_at=T0, pull_forward=True) is False
    record = jobs.find_active(KEY)
    assert record is not None and record.run_at == T0
    lease = _claim(jobs)
    assert lease is not None

    # A leased job is not rescheduled underneath its owner.
    _schedule(jobs, run_at=T0 - timedelta(hours=1), pull_forward=True)
    record = jobs.get(lease.job_id)
    assert record is not None and record.run_at == T0


def test_026_FR_015_claim_respects_due_time_and_types(jobs: JobRepository) -> None:
    _schedule(jobs, run_at=T0 + timedelta(seconds=10))
    assert _claim(jobs, T0) is None
    assert jobs.claim_due(owner="w", types=(), now=T0 + timedelta(hours=1)) is None
    assert (
        jobs.claim_due(owner="w", types=("other",), now=T0 + timedelta(hours=1)) is None
    )
    assert _claim(jobs, T0 + timedelta(seconds=10)) is not None


def test_026_FR_015_claims_oldest_due_job_first(jobs: JobRepository) -> None:
    _schedule(jobs, key="late", run_at=T0 + timedelta(seconds=5))
    _schedule(jobs, key="early", run_at=T0)
    first = _claim(jobs, T0 + timedelta(minutes=1))
    second = _claim(jobs, T0 + timedelta(minutes=1))
    assert first is not None and second is not None
    assert (first.dedup_key, second.dedup_key) == ("early", "late")


# --- lease, expiry, reclaim -------------------------------------------------


def test_026_FR_015_expired_lease_is_reclaimed_with_a_new_fence(
    jobs: JobRepository,
) -> None:
    _schedule(jobs, payload_ref="payload-1")
    first = _claim(jobs, T0, owner="crashed")
    assert first is not None
    assert (first.attempt, first.owner, first.payload_ref) == (
        1,
        "crashed",
        "payload-1",
    )

    # Inside the lease nobody else can take it.
    assert _claim(jobs, T0 + timedelta(seconds=59), owner="w2") is None

    # At expiry the lease returns to the queue behind full-jitter backoff
    # (cap 1s after one attempt) rather than being re-leased in the same call.
    assert _claim(jobs, T0 + timedelta(seconds=60), owner="w2") is None
    requeued = jobs.get(first.job_id)
    assert requeued is not None
    assert (requeued.status, requeued.lease_owner, requeued.last_error) == (
        JobStatus.QUEUED,
        None,
        "lease_expired",
    )
    second = _claim(jobs, T0 + timedelta(seconds=61), owner="w2")
    assert second is not None
    assert second.job_id == first.job_id
    assert second.fence > first.fence
    assert second.attempt == 2
    # Retry and reclaim never replace the durable effect id.
    assert second.effect_id == first.effect_id


def test_026_FR_015_heartbeat_extends_only_the_current_claim(
    jobs: JobRepository,
) -> None:
    _schedule(jobs)
    lease = _claim(jobs, T0, owner="w1")
    assert lease is not None

    assert jobs.heartbeat(
        lease.job_id, owner="w1", fence=lease.fence, until=T0 + timedelta(seconds=120)
    )
    assert _claim(jobs, T0 + timedelta(seconds=61), owner="w2") is None
    # A heartbeat never shortens a lease.
    assert jobs.heartbeat(
        lease.job_id, owner="w1", fence=lease.fence, until=T0 + timedelta(seconds=10)
    )
    assert _claim(jobs, T0 + timedelta(seconds=119), owner="w2") is None

    assert _claim(jobs, T0 + timedelta(seconds=120), owner="w2") is None
    taken = _claim(jobs, T0 + timedelta(seconds=121), owner="w2")
    assert taken is not None
    assert not jobs.heartbeat(
        lease.job_id, owner="w1", fence=lease.fence, until=T0 + timedelta(hours=1)
    )
    assert not jobs.heartbeat(
        lease.job_id, owner="w2", fence=lease.fence, until=T0 + timedelta(hours=1)
    )


def test_026_FR_015_fence_is_monotonic_across_jobs(jobs: JobRepository) -> None:
    _schedule(jobs, key="a")
    _schedule(jobs, key="b")
    fences = [
        lease.fence for lease in (_claim(jobs), _claim(jobs)) if lease is not None
    ]
    assert len(fences) == 2 and fences[0] < fences[1]


# --- stale fences -----------------------------------------------------------


def test_026_SC_007_stale_executor_cannot_settle_after_reclaim(
    jobs: JobRepository,
) -> None:
    _schedule(jobs)
    stale = _claim(jobs, T0, owner="slow")
    assert stale is not None
    assert _claim(jobs, T0 + LEASE, owner="fast") is None  # requeued, backing off
    current = _claim(jobs, T0 + LEASE + timedelta(seconds=1), owner="fast")
    assert current is not None

    assert jobs.complete(stale.job_id, fence=stale.fence) is False
    assert jobs.fail(stale.job_id, fence=stale.fence, safe_error="x", now=T0) is False
    assert jobs.mark_uncertain(stale.job_id, fence=stale.fence) is False
    assert jobs.should_abandon(stale.job_id, fence=stale.fence) is True
    record = jobs.get(stale.job_id)
    # Nothing the stale holder did changed the live claim.
    assert record is not None
    assert (record.status, record.lease_owner, record.fence) == (
        JobStatus.LEASED,
        "fast",
        current.fence,
    )

    assert jobs.should_abandon(current.job_id, fence=current.fence) is False
    assert jobs.complete(current.job_id, fence=current.fence) is True
    # A result cannot be accepted twice, nor a settled job failed afterwards.
    assert jobs.complete(current.job_id, fence=current.fence) is False
    assert (
        jobs.fail(current.job_id, fence=current.fence, safe_error="x", now=T0) is False
    )


def test_026_SC_007_unknown_job_and_wrong_fence_are_refused(
    jobs: JobRepository,
) -> None:
    _schedule(jobs)
    lease = _claim(jobs)
    assert lease is not None
    assert jobs.complete("missing", fence=lease.fence) is False
    assert jobs.complete(lease.job_id, fence=lease.fence + 1) is False
    assert jobs.should_abandon("missing", fence=1) is True
    assert jobs.get("missing") is None


# --- retry budget -----------------------------------------------------------


def test_026_FR_015_retries_back_off_then_report_exhaustion(
    jobs: JobRepository,
) -> None:
    _schedule(jobs, max_attempts=5)
    now = T0
    delays: list[float] = []
    exhausted: list[bool] = []
    for _ in range(5):
        lease = _claim(jobs, now)
        assert lease is not None
        exhausted.append(
            jobs.fail(lease.job_id, fence=lease.fence, safe_error="Boom", now=now)
        )
        record = jobs.get(lease.job_id)
        assert record is not None
        if not exhausted[-1]:
            assert record.status is JobStatus.QUEUED
            delays.append((record.run_at - now).total_seconds())
            # Not claimable before its backoff has passed.
            assert _claim(jobs, now) is None
            now = record.run_at

    # plan section 7: full-jitter caps 1, 5, 30, 120 then the fifth attempt ends it.
    assert delays == [1.0, 5.0, 30.0, 120.0]
    assert exhausted == [False, False, False, False, True]
    final = jobs.find_active(KEY)
    assert final is None
    assert _claim(jobs, now + timedelta(days=1)) is None


def test_026_FR_015_exhausted_job_is_visible_as_failed_with_safe_error(
    jobs: JobRepository,
) -> None:
    _schedule(jobs, max_attempts=1)
    lease = _claim(jobs)
    assert lease is not None
    assert jobs.fail(
        lease.job_id,
        fence=lease.fence,
        safe_error="Boom: /home/user/secret text\nline",
        now=T0,
    )
    record = jobs.get(lease.job_id)
    assert record is not None
    assert record.status is JobStatus.FAILED
    assert record.last_error == "Boom:__home_user_secret_text_line"
    assert record.lease_owner is None
    # The schedule identity is free again for an idempotent maintenance job.
    assert _schedule(jobs, run_at=T0 + timedelta(hours=1)) is True


def test_026_FR_015_default_jitter_stays_within_the_cap(db_path: Path) -> None:
    jobs = JobRepository(db_path)
    _schedule(jobs)
    lease = _claim(jobs)
    assert lease is not None
    jobs.fail(lease.job_id, fence=lease.fence, safe_error=None, now=T0)
    record = jobs.get(lease.job_id)
    assert record is not None
    assert timedelta(0) <= record.run_at - T0 <= timedelta(seconds=1)
    assert record.last_error == "failed"


def test_026_FR_015_crash_loop_closes_after_the_attempt_budget(
    jobs: JobRepository,
) -> None:
    _schedule(jobs, max_attempts=2)
    assert _claim(jobs, T0) is not None  # worker dies without settling
    now = T0 + LEASE
    assert _claim(jobs, now) is None  # expired: requeued behind a 1s backoff
    now += timedelta(seconds=1)
    assert _claim(jobs, now) is not None  # second attempt, worker dies again
    now += LEASE
    assert _claim(jobs, now) is None  # budget used: closed, not requeued
    assert jobs.find_active(KEY) is None
    assert _schedule(jobs, run_at=now) is True  # the ledger is not wedged
    record = jobs.find_active(KEY)
    assert record is not None and record.status is JobStatus.QUEUED


def test_026_FR_015_ledger_survives_a_restart(db_path: Path) -> None:
    first = JobRepository(db_path)
    first.ensure_scheduled(job_type=TYPE, dedup_key=KEY, run_at=T0)
    lease = first.claim_due(owner="before", types=(TYPE,), now=T0, lease_for=LEASE)
    assert lease is not None

    reopened = JobRepository(db_path)
    record = reopened.find_active(KEY)
    assert record is not None
    assert (record.status, record.lease_owner, record.fence, record.attempts) == (
        JobStatus.LEASED,
        "before",
        lease.fence,
        1,
    )
    assert reopened.ensure_scheduled(job_type=TYPE, dedup_key=KEY, run_at=T0) is False
    assert (
        reopened.claim_due(
            owner="after", types=(TYPE,), now=T0 + LEASE, lease_for=LEASE
        )
        is None
    )
    # Default full jitter stays within the 1s cap after one attempt.
    reclaimed = reopened.claim_due(
        owner="after",
        types=(TYPE,),
        now=T0 + LEASE + timedelta(seconds=1),
        lease_for=LEASE,
    )
    assert reclaimed is not None and reclaimed.fence > lease.fence
    # The pre-restart claim can no longer settle.
    assert reopened.complete(lease.job_id, fence=lease.fence) is False


# --- uncertain outcomes -----------------------------------------------------


def test_026_SC_007_uncertain_outcome_is_never_retried_automatically(
    jobs: JobRepository,
) -> None:
    _schedule(jobs)
    lease = _claim(jobs)
    assert lease is not None
    assert jobs.mark_uncertain(lease.job_id, fence=lease.fence, safe_error=None)

    record = jobs.get(lease.job_id)
    assert record is not None
    assert record.status is JobStatus.RECONCILIATION_REQUIRED
    assert record.last_error == "outcome_unknown"
    assert record.lease_owner is None

    far_future = T0 + timedelta(days=365)
    assert _claim(jobs, far_future) is None
    # The identity stays occupied: no sibling occurrence repeats the effect.
    assert _schedule(jobs, run_at=far_future) is False
    # A late settle from the old claim changes nothing.
    assert jobs.complete(lease.job_id, fence=lease.fence) is False
    assert jobs.fail(lease.job_id, fence=lease.fence, safe_error="x", now=T0) is False
    after = jobs.get(lease.job_id)
    assert after is not None and after.status is JobStatus.RECONCILIATION_REQUIRED


def test_026_SC_007_only_an_explicit_decision_resolves_an_uncertain_job(
    jobs: JobRepository,
) -> None:
    _schedule(jobs)
    lease = _claim(jobs)
    assert lease is not None
    jobs.mark_uncertain(lease.job_id, fence=lease.fence, safe_error="timeout")

    with pytest.raises(ValueError, match="run_at"):
        jobs.resolve_reconciliation(lease.job_id, decision="retry")
    assert jobs.resolve_reconciliation(
        lease.job_id, decision="retry", run_at=T0 + timedelta(minutes=5)
    )
    retried = _claim(jobs, T0 + timedelta(minutes=5))
    assert retried is not None
    assert retried.effect_id == lease.effect_id  # same idempotency identity
    assert retried.attempt == 1  # fresh budget by decision
    # Only a reconciliation-pending job can be resolved.
    assert not jobs.resolve_reconciliation(lease.job_id, decision="succeeded")


@pytest.mark.parametrize(
    ("decision", "expected"),
    [("succeeded", JobStatus.SUCCEEDED), ("failed", JobStatus.FAILED)],
)
def test_026_SC_007_uncertain_job_can_be_closed_by_lookup(
    jobs: JobRepository, decision: str, expected: JobStatus
) -> None:
    _schedule(jobs)
    lease = _claim(jobs)
    assert lease is not None
    jobs.mark_uncertain(lease.job_id, fence=lease.fence)
    assert jobs.resolve_reconciliation(lease.job_id, decision=decision)  # type: ignore[arg-type]
    record = jobs.get(lease.job_id)
    assert record is not None and record.status is expected


# --- cancellation -----------------------------------------------------------


def test_026_FR_015_cancel_stops_queued_and_refuses_running_results(
    jobs: JobRepository,
) -> None:
    assert jobs.cancel("missing") is None
    _schedule(jobs, key="queued")
    queued = jobs.find_active("queued")
    assert queued is not None
    assert jobs.cancel(queued.job_id) is JobStatus.CANCELLED
    assert _claim(jobs) is None

    _schedule(jobs, key="running")
    lease = _claim(jobs)
    assert lease is not None
    assert jobs.cancel(lease.job_id) is JobStatus.LEASED
    assert jobs.should_abandon(lease.job_id, fence=lease.fence) is True
    assert jobs.complete(lease.job_id, fence=lease.fence) is False
    record = jobs.get(lease.job_id)
    assert record is not None and record.status is JobStatus.CANCELLED
    assert jobs.cancel(lease.job_id) is JobStatus.CANCELLED  # terminal: unchanged


def test_026_FR_015_cancel_wins_over_failure_and_expired_lease(
    jobs: JobRepository,
) -> None:
    _schedule(jobs, key="fails")
    failing = _claim(jobs)
    assert failing is not None
    jobs.cancel(failing.job_id)
    assert (
        jobs.fail(failing.job_id, fence=failing.fence, safe_error="x", now=T0) is False
    )
    record = jobs.get(failing.job_id)
    assert record is not None and record.status is JobStatus.CANCELLED

    _schedule(jobs, key="crashes")
    crashed = _claim(jobs)
    assert crashed is not None
    jobs.cancel(crashed.job_id)
    assert _claim(jobs, T0 + LEASE) is None
    record = jobs.get(crashed.job_id)
    assert record is not None and record.status is JobStatus.CANCELLED

    _schedule(jobs, key="uncertain")
    parked = _claim(jobs)
    assert parked is not None
    jobs.mark_uncertain(parked.job_id, fence=parked.fence)
    assert jobs.cancel(parked.job_id) is JobStatus.CANCELLED


# --- input validation -------------------------------------------------------


def test_026_FR_015_times_must_be_timezone_aware(jobs: JobRepository) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _schedule(jobs, run_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="at least 1"):
        _schedule(jobs, max_attempts=0)


# --- concurrency ------------------------------------------------------------


def test_026_SC_007_threads_racing_for_one_job_yield_one_owner(
    db_path: Path,
) -> None:
    JobRepository(db_path).ensure_scheduled(job_type=TYPE, dedup_key=KEY, run_at=T0)
    barrier = threading.Barrier(8)
    won: list[str] = []
    errors: list[BaseException] = []

    def contend(name: str) -> None:
        try:
            repo = JobRepository(db_path)
            barrier.wait()
            lease = repo.claim_due(owner=name, types=(TYPE,), now=T0, lease_for=LEASE)
            if lease is not None:
                won.append(name)
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion
            errors.append(exc)

    threads = [threading.Thread(target=contend, args=(f"t{i}",)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(won) == 1


def test_026_SC_007_threads_never_double_schedule_a_dedup_key(db_path: Path) -> None:
    JobRepository(db_path)
    barrier = threading.Barrier(8)
    created: list[bool] = []

    def contend() -> None:
        repo = JobRepository(db_path)
        barrier.wait()
        created.append(repo.ensure_scheduled(job_type=TYPE, dedup_key=KEY, run_at=T0))

    threads = [threading.Thread(target=contend) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert created.count(True) == 1 and len(created) == 8


_CLAIMER = textwrap.dedent("""
    import sys
    from datetime import UTC, datetime, timedelta
    from pathlib import Path

    from app.modules.tasks.jobs import JobRepository

    repo = JobRepository(Path(sys.argv[1]))
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    while True:
        lease = repo.claim_due(
            owner=sys.argv[2],
            types=("maintenance.demo",),
            now=now,
            lease_for=timedelta(seconds=60),
        )
        if lease is None:
            break
        print(lease.job_id, lease.fence, flush=True)
    """)


def test_026_SC_007_processes_never_both_own_a_job(db_path: Path) -> None:
    repo = JobRepository(db_path)
    total = 12
    for index in range(total):
        repo.ensure_scheduled(job_type=TYPE, dedup_key=f"job-{index}", run_at=T0)

    backend_root = Path(__file__).resolve().parents[1]
    procs = [
        subprocess.Popen(  # noqa: S603 - fixed argv, our own interpreter
            [sys.executable, "-c", _CLAIMER, str(db_path), f"proc-{i}"],
            cwd=backend_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for i in range(4)
    ]
    claimed: list[tuple[str, int]] = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
        for line in out.splitlines():
            job_id, fence = line.split()
            claimed.append((job_id, int(fence)))

    job_ids = [job_id for job_id, _ in claimed]
    assert len(job_ids) == total
    assert len(set(job_ids)) == total  # no job handed to two processes
    fences = [fence for _, fence in claimed]
    assert len(set(fences)) == total  # every claim got a distinct fence


# --- wiring -----------------------------------------------------------------


def test_026_FR_015_container_wires_the_ledger_onto_the_tasks_database(
    container: Container,
) -> None:
    assert isinstance(container.job_repository, JobRepository)
    assert container.job_repository.db_path == container.task_repo.db_path
    assert container.job_repository.ensure_scheduled(
        job_type=TYPE, dedup_key=KEY, run_at=T0
    )


def test_026_FR_015_leases_that_expire_together_are_dispersed(db_path: Path) -> None:
    caps: list[float] = []
    delays = iter([0.25, 0.75])

    def jitter(cap: float) -> float:
        caps.append(cap)
        return next(delays)

    jobs = JobRepository(db_path, jitter=jitter)
    _schedule(jobs, key="a")
    _schedule(jobs, key="b")
    assert _claim(jobs, T0, owner="crashed") is not None
    assert _claim(jobs, T0, owner="crashed") is not None

    # Both leases lapse at once; neither is re-leased in that same call.
    assert _claim(jobs, T0 + LEASE, owner="w2") is None
    assert caps == [1, 1]
    first = _claim(jobs, T0 + LEASE + timedelta(seconds=0.5), owner="w2")
    assert first is not None
    assert _claim(jobs, T0 + LEASE + timedelta(seconds=0.5), owner="w3") is None
    assert _claim(jobs, T0 + LEASE + timedelta(seconds=0.75), owner="w3") is not None
