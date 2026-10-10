"""Job command authority at the compatible task and Review write ports.

Spec 026 PR-21 (026-FR-011, 026-FR-014, 026-FR-015, 026-SC-007). A background
writer reaches the task store through the same ports as every other writer; what
differs is its authority. These tests run the real ``TaskService``,
``ReviewService`` and SQLite ledger, claim real leases, and show that a stale
executor or a revoked scope cannot create a mutation, that the check happens
under the task writer lock, and that a caller can never choose its own origin.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.container import Container
from app.exceptions import ValidationFailure
from app.modules.tasks import review_domain as rd
from app.modules.tasks.domain import IdempotencyRecord
from app.modules.tasks.jobs import JobLease, JobRepository
from app.modules.tasks.jobs.domain import SYSTEM_SCOPE
from app.modules.tasks.jobs.execution import (
    ForgedWriterOriginError,
    JobExecutionGate,
    ScopeRevokedError,
    StaleExecutorError,
    WriterOrigin,
    current_execution,
    current_writer_origin,
)
from app.modules.tasks.review_service import ReviewService
from app.schemas.review import ExplainerAcknowledgeRequest
from app.schemas.tasks import TaskCreateRequest
from app.utils.time import utcnow

OWNER_A = "user_authority_a"
OWNER_B = "user_authority_b"
TYPE = "maintenance.authority"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LEASE = timedelta(seconds=60)


class Clock:
    def __init__(self) -> None:
        self.moment = T0

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += timedelta(seconds=seconds)


class Authority:
    """The Identity side of scope authority: the owners that are still current."""

    def __init__(self, *owners: str) -> None:
        self.live = set(owners)

    def __call__(self, owner_id: str) -> bool:
        return owner_id in self.live


@dataclass
class Rig:
    container: Container
    gate: JobExecutionGate
    authority: Authority
    clock: Clock

    @property
    def jobs(self) -> JobRepository:
        return self.container.job_repository

    def claim(
        self, *, key: str = "authority:schedule", scope: str = SYSTEM_SCOPE
    ) -> JobLease:
        self.jobs.ensure_scheduled(job_type=TYPE, dedup_key=key, run_at=T0, scope=scope)
        lease = self.jobs.claim_due(
            owner="w1", types=(TYPE,), now=self.clock(), lease_for=LEASE
        )
        assert lease is not None
        return lease

    def reclaim_by_another_worker(self) -> JobLease:
        """Let the lease lapse, then have a second worker claim the same job."""

        self.clock.advance(LEASE.total_seconds() + 10)
        # The first call recovers the expired lease into a short full-jitter
        # backoff (at most one second after the first attempt); the second claims.
        self.jobs.claim_due(owner="w2", types=(TYPE,), now=self.clock())
        self.clock.advance(2)
        lease = self.jobs.claim_due(
            owner="w2", types=(TYPE,), now=self.clock(), lease_for=LEASE
        )
        assert lease is not None
        return lease

    def task_titles(self, owner_id: str) -> list[str]:
        repo = self.container.task_repo
        return [task.title for task in repo.list_for_owner(owner_id=owner_id)]

    def create(self, owner_id: str, title: str = "Job made") -> str:
        return self.container.task_service.create_task(
            TaskCreateRequest(title=title),
            owner_id=owner_id,
            idempotency_key=f"key-{title}-{owner_id}",
        ).id


@pytest.fixture()
def rig(container: Container) -> Rig:
    authority = Authority(OWNER_A, OWNER_B)
    clock = Clock()
    gate = JobExecutionGate(
        container.job_repository, owner_current=authority, now=clock
    )
    return Rig(container, gate, authority, clock)


# --- the compatible task port ------------------------------------------------


def test_026_FR_014_writer_without_an_execution_context_is_unchanged(
    rig: Rig,
) -> None:
    assert current_execution() is None
    assert current_writer_origin() is WriterOrigin.LEGACY

    rig.create(OWNER_A)

    assert rig.task_titles(OWNER_A) == ["Job made"]


def test_026_FR_014_current_executor_writes_through_serialized_write(
    rig: Rig,
) -> None:
    lease = rig.claim()

    with rig.gate.executing(lease) as execution:
        assert current_execution() is execution
        assert current_writer_origin() is WriterOrigin.JOB
        rig.create(OWNER_A)

    assert current_execution() is None
    assert rig.task_titles(OWNER_A) == ["Job made"]


def test_026_FR_014_binding_is_released_when_the_job_body_raises(rig: Rig) -> None:
    lease = rig.claim()

    with pytest.raises(RuntimeError), rig.gate.executing(lease):
        raise RuntimeError("adapter failure")

    assert current_execution() is None
    assert current_writer_origin() is WriterOrigin.LEGACY


def test_026_SC_007_stale_executor_cannot_create_a_mutation_after_reclaim(
    rig: Rig,
) -> None:
    old = rig.claim()
    new = rig.reclaim_by_another_worker()
    assert new.fence > old.fence

    with rig.gate.executing(old), pytest.raises(StaleExecutorError):
        rig.create(OWNER_A, "Stale write")
    assert rig.task_titles(OWNER_A) == []

    with rig.gate.executing(new):
        rig.create(OWNER_A, "Current write")
    assert rig.task_titles(OWNER_A) == ["Current write"]


def test_026_FR_015_executor_past_its_stored_lease_expiry_cannot_write(
    rig: Rig,
) -> None:
    lease = rig.claim()
    rig.clock.advance(LEASE.total_seconds() + 1)

    with rig.gate.executing(lease), pytest.raises(StaleExecutorError):
        rig.create(OWNER_A)

    assert rig.task_titles(OWNER_A) == []


def test_026_FR_015_cancelled_job_cannot_write(rig: Rig) -> None:
    lease = rig.claim()
    rig.jobs.cancel(lease.job_id)

    with rig.gate.executing(lease), pytest.raises(StaleExecutorError):
        rig.create(OWNER_A)

    assert rig.task_titles(OWNER_A) == []


def test_026_FR_015_stale_executor_cannot_replay_an_earlier_result(
    rig: Rig,
) -> None:
    lease = rig.claim()
    with rig.gate.executing(lease):
        first = rig.create(OWNER_A)
    rig.jobs.cancel(lease.job_id)

    # Authority is checked before the idempotency lookup, so even a replay of a
    # stored outcome is refused to an executor that no longer holds the job.
    with rig.gate.executing(lease), pytest.raises(StaleExecutorError):
        assert rig.create(OWNER_A) == first


def test_026_FR_015_fence_and_scope_are_rechecked_under_the_writer_lock(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    repo = rig.container.task_repo
    real_lock = repo.command_lock

    def traced_lock(owner_id: str):  # type: ignore[no-untyped-def]
        class _Held:
            def __enter__(self) -> None:
                self._cm = real_lock(owner_id)
                self._cm.__enter__()
                events.append("lock")

            def __exit__(self, *exc: object) -> object:
                events.append("unlock")
                return self._cm.__exit__(*exc)

        return _Held()

    class TracedLedger:
        def should_abandon(self, job_id: str, *, fence: int, now: datetime) -> bool:
            events.append("fence")
            return rig.jobs.should_abandon(job_id, fence=fence, now=now)

    def traced_authority(owner_id: str) -> bool:
        events.append("scope")
        return rig.authority(owner_id)

    gate = JobExecutionGate(
        TracedLedger(), owner_current=traced_authority, now=rig.clock
    )
    monkeypatch.setattr(repo, "command_lock", traced_lock)
    lease = rig.claim()

    with gate.executing(lease):
        events.clear()
        rig.create(OWNER_A)

    assert events == ["lock", "fence", "scope", "unlock"]


# --- scope authority ---------------------------------------------------------


def test_026_FR_011_revoked_scope_cannot_create_a_mutation(rig: Rig) -> None:
    lease = rig.claim()
    rig.authority.live.discard(OWNER_A)

    with rig.gate.executing(lease), pytest.raises(ScopeRevokedError):
        rig.create(OWNER_A)

    assert rig.task_titles(OWNER_A) == []


def test_026_FR_011_scope_revoked_between_commands_stops_the_next_write(
    rig: Rig,
) -> None:
    lease = rig.claim()

    with rig.gate.executing(lease):
        rig.create(OWNER_A, "Before revoke")
        rig.authority.live.discard(OWNER_A)
        with pytest.raises(ScopeRevokedError):
            rig.create(OWNER_A, "After revoke")
        rig.create(OWNER_B, "Other owner still current")

    assert rig.task_titles(OWNER_A) == ["Before revoke"]
    assert rig.task_titles(OWNER_B) == ["Other owner still current"]


def test_026_FR_011_owner_scoped_job_cannot_write_another_owners_data(
    rig: Rig,
) -> None:
    lease = rig.claim(key="owner-a:job", scope=OWNER_A)

    with rig.gate.executing(lease):
        rig.create(OWNER_A, "Own data")
        with pytest.raises(ScopeRevokedError):
            rig.create(OWNER_B, "Foreign data")

    assert rig.task_titles(OWNER_A) == ["Own data"]
    assert rig.task_titles(OWNER_B) == []


def test_026_FR_011_stale_fence_is_reported_before_scope(rig: Rig) -> None:
    lease = rig.claim()
    rig.jobs.cancel(lease.job_id)
    rig.authority.live.clear()

    with rig.gate.executing(lease), pytest.raises(StaleExecutorError):
        rig.create(OWNER_A)


def test_026_FR_011_container_resolves_scope_authority_from_identity(
    container: Container,
) -> None:
    from app.schemas.auth import User

    container.user_repo.create(
        User(id=OWNER_A, email="authority-a@example.com", created_at=utcnow())
    )
    jobs = container.job_repository
    jobs.ensure_scheduled(job_type=TYPE, dedup_key="wired", run_at=utcnow())
    lease = jobs.claim_due(owner="w1", types=(TYPE,), now=utcnow(), lease_for=LEASE)
    assert lease is not None

    with container.job_execution.executing(lease):
        container.task_service.create_task(
            TaskCreateRequest(title="Wired"),
            owner_id=OWNER_A,
            idempotency_key="wired-1",
        )
        container.user_repo.delete(OWNER_A)
        with pytest.raises(ScopeRevokedError):
            container.task_service.create_task(
                TaskCreateRequest(title="Revoked"),
                owner_id=OWNER_A,
                idempotency_key="wired-2",
            )

    titles = [t.title for t in container.task_repo.list_for_owner(owner_id=OWNER_A)]
    assert titles == ["Wired"]


# --- the Review application ports -------------------------------------------


def _ack(rig: Rig, owner_id: str = OWNER_A) -> rd.ReviewSettingsDocument:
    return rig.container.review_service.acknowledge_explainer(
        ExplainerAcknowledgeRequest(),
        owner_id=owner_id,
        idempotency_key=f"ack-{owner_id}",
    )


def test_026_FR_014_review_serialized_port_refuses_stale_and_revoked_writers(
    rig: Rig,
) -> None:
    lease = rig.claim()
    repo = rig.container.task_repo

    rig.jobs.cancel(lease.job_id)
    with rig.gate.executing(lease), pytest.raises(StaleExecutorError):
        _ack(rig)
    assert repo.get_review_settings(OWNER_A) is None

    live = rig.claim(key="second")
    rig.authority.live.discard(OWNER_A)
    with rig.gate.executing(live), pytest.raises(ScopeRevokedError):
        _ack(rig)
    assert repo.get_review_settings(OWNER_A) is None


def _sweeping_review(rig: Rig) -> ReviewService:
    return ReviewService(rig.container.task_service, is_exposed=lambda _owner: True)


def _activate(rig: Rig, *owners: str) -> None:
    for owner_id in owners:
        rig.container.task_repo.save_review_settings(
            rd.ReviewSettingsDocument(owner_id=owner_id, activated_at=T0)
        )


def _last_sweeps(rig: Rig, *owners: str) -> list[datetime | None]:
    repo = rig.container.task_repo
    settings = [repo.get_review_settings(owner_id) for owner_id in owners]
    return [None if item is None else item.last_effective_sweep_at for item in settings]


def test_026_SC_007_stale_executor_aborts_the_auto_park_sweep_without_writes(
    rig: Rig,
) -> None:
    _activate(rig, OWNER_A, OWNER_B)
    review = _sweeping_review(rig)
    lease = rig.claim()
    rig.jobs.cancel(lease.job_id)

    with rig.gate.executing(lease), pytest.raises(StaleExecutorError):
        review.run_auto_park_sweep(T0)

    assert _last_sweeps(rig, OWNER_A, OWNER_B) == [None, None]


def test_026_SC_007_current_executor_runs_the_auto_park_sweep(rig: Rig) -> None:
    _activate(rig, OWNER_A, OWNER_B)
    review = _sweeping_review(rig)
    lease = rig.claim()

    with rig.gate.executing(lease):
        owners, *_ = review.run_auto_park_sweep(T0)

    assert owners == 2
    assert _last_sweeps(rig, OWNER_A, OWNER_B) == [T0, T0]


def test_026_FR_011_revoked_owner_is_skipped_while_other_owners_are_swept(
    rig: Rig,
) -> None:
    _activate(rig, OWNER_A, OWNER_B)
    review = _sweeping_review(rig)
    rig.authority.live.discard(OWNER_A)
    lease = rig.claim()

    with rig.gate.executing(lease):
        review.run_auto_park_sweep(T0)

    assert _last_sweeps(rig, OWNER_A, OWNER_B) == [None, T0]


def test_026_SC_007_stale_executor_cannot_run_review_retention(rig: Rig) -> None:
    repo = rig.container.task_repo
    review = _sweeping_review(rig)
    old = T0 - timedelta(days=3)
    repo.save_idempotency(
        owner_id=OWNER_A,
        record=IdempotencyRecord(
            key="expired-key",
            command="demo",
            request_hash="h",
            resource_id="r",
            response_body={},
            created_at=old,
        ),
    )
    lease = rig.claim()
    rig.jobs.cancel(lease.job_id)

    with rig.gate.executing(lease), pytest.raises(StaleExecutorError):
        review.run_review_retention(T0)

    assert repo.get_idempotency(owner_id=OWNER_A, key="expired-key") is not None

    live = rig.claim(key="retention-current")
    with rig.gate.executing(live):
        review.run_review_retention(T0)
    assert repo.get_idempotency(owner_id=OWNER_A, key="expired-key") is None


def test_026_SC_007_stale_executor_cannot_close_idle_review_sessions(
    rig: Rig,
) -> None:
    repo = rig.container.task_repo
    repo.save_review_session(
        rd.ReviewSessionDocument(
            id="review_000000000001",
            owner_id=OWNER_A,
            mode="quick",
            entry="list",
            origin="web",
            status="open",
            started_at=T0 - timedelta(days=10),
            last_activity_at=T0 - timedelta(days=10),
        )
    )
    lease = rig.claim()
    rig.jobs.cancel(lease.job_id)
    flow = rig.container.review_flow_service

    with rig.gate.executing(lease), pytest.raises(StaleExecutorError):
        flow.close_idle_sessions(OWNER_A, T0)
    assert repo.get_review_session(OWNER_A, "review_000000000001").status == "open"

    live = rig.claim(key="idle-current")
    with rig.gate.executing(live):
        assert flow.close_idle_sessions(OWNER_A, T0) == 1


# --- internal effect identity -----------------------------------------------


def test_026_FR_015_effect_identity_is_stable_across_retries_and_fences(
    rig: Rig,
) -> None:
    first = rig.claim()
    execution_one = rig.gate.begin(first)
    second = rig.reclaim_by_another_worker()
    execution_two = rig.gate.begin(second)

    assert (second.fence, second.attempt) != (first.fence, first.attempt)
    assert execution_one.effect_identity == execution_two.effect_identity
    assert execution_one.fence != execution_two.fence
    # Domain separated: never the raw ledger id a client could echo back.
    assert execution_one.effect_identity != first.effect_id
    assert first.effect_id not in execution_one.effect_identity


def test_026_FR_015_effect_identity_differs_per_job(rig: Rig) -> None:
    one = rig.gate.begin(rig.claim(key="job-one"))
    two = rig.gate.begin(rig.claim(key="job-two"))

    assert one.effect_identity != two.effect_identity


def test_026_FR_015_effect_identity_is_fixed_once_derived(rig: Rig) -> None:
    execution = rig.gate.begin(rig.claim())

    with pytest.raises(AttributeError):
        execution.effect_identity = "elsewhere"  # type: ignore[misc]
    assert execution.writer_origin is WriterOrigin.JOB


# --- writer origin is server derived ----------------------------------------


@pytest.mark.parametrize("claimed", ["job", "legacy", "device", ""])
def test_026_FR_014_caller_supplied_writer_origin_is_rejected_before_the_lock(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, claimed: str
) -> None:
    repo = rig.container.task_repo

    def forbidden_lock(owner_id: str):  # type: ignore[no-untyped-def]
        raise AssertionError("the lock must not be taken for a forged origin")

    monkeypatch.setattr(repo, "command_lock", forbidden_lock)

    with pytest.raises(ForgedWriterOriginError):
        rig.container.task_service.create_task_result(
            TaskCreateRequest(title="Forged"),
            owner_id=OWNER_A,
            idempotency_key="forged",
            writer_origin=claimed,  # type: ignore[call-arg]
        )


def test_026_FR_014_forged_origin_cannot_borrow_a_current_job_authority(
    rig: Rig,
) -> None:
    lease = rig.claim()

    with rig.gate.executing(lease), pytest.raises(ValidationFailure):
        rig.container.review_service.acknowledge_explainer(
            ExplainerAcknowledgeRequest(),
            owner_id=OWNER_A,
            idempotency_key="ack-forged",
            writer_origin="job",  # type: ignore[call-arg]
        )

    assert rig.container.task_repo.get_review_settings(OWNER_A) is None


def test_026_FR_014_origin_is_not_a_parameter_of_the_execution_api() -> None:
    for member in (JobExecutionGate.begin, JobExecutionGate.executing):
        assert "writer_origin" not in inspect.signature(member).parameters
        assert "origin" not in inspect.signature(member).parameters


def test_026_FR_014_http_writer_origin_in_a_body_grants_nothing(
    api_client,  # type: ignore[no-untyped-def]
) -> None:
    response = api_client.post(
        "/api/tasks",
        json={"title": "Forged over HTTP", "writer_origin": "job"},
        headers={"Idempotency-Key": "http-forged"},
    )

    assert 400 <= response.status_code < 500
    listing = api_client.get("/api/tasks")
    assert listing.status_code == 200
    assert "Forged over HTTP" not in listing.text
