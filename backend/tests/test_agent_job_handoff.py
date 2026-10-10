"""The agent relay's observation and recovery as durable ledger jobs.

Spec 026 PR-24 (026-FR-014, 026-FR-015, 026-FR-021, 026-SC-007). The real
``AgentObserver``, ``AgentRelayService``, SQLite job ledger and ``JobWorker`` run
with a scripted A2A wire and one fake clock, so a lease can be made to lapse in
the middle of a read. The existing scheduler thread is never started by the
adapters: this slice proves them, and that they cannot overlap that thread.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.container import Container
from app.modules.agents.a2a.client import A2A_TIMEOUT, A2AResult
from app.modules.agents.observer import AgentObserver, SchedulerOverlapError
from app.modules.agents.repository import AgentRepository
from app.modules.agents.secrets import SecretBox
from app.modules.agents.service import AgentRelayService
from app.modules.tasks.jobs import JobLease, JobOutcome, JobRepository, JobStatus
from app.modules.tasks.jobs.agent_adapter import (
    RECOVER_JOB_TYPE,
    AgentObservationAdapter,
    AgentRecoveryAdapter,
)
from app.modules.tasks.jobs.execution import (
    JobExecutionGate,
    StaleExecutorError,
    WriterOrigin,
    current_writer_origin,
)
from app.modules.tasks.jobs.worker import JobContext, JobRegistry, JobWorker
from app.schemas.tasks import TaskCreateRequest

from .a2a_fakes import FakeA2AClient, FakeCardFetcher
from .test_agent_observer import (
    OTHER_OWNER,
    OWNER,
    PUSH_BASE,
    Clock,
    DeferredExecutor,
    SynchronousExecutor,
    agent_task,
    connect_ready,
    dispatched,
    observed_task,
    queue_handoff,
    task_snapshot,
)

LEASE = timedelta(seconds=60)


class Authority:
    """The Identity side of scope authority: the owners still current."""

    def __init__(self, *owners: str) -> None:
        self.live = set(owners)

    def __call__(self, owner_id: str) -> bool:
        return owner_id in self.live


@dataclass
class Rig:
    container: Container
    service: AgentRelayService
    repo: AgentRepository
    clock: Clock
    a2a: FakeA2AClient
    gate: JobExecutionGate
    authority: Authority
    observers: list[AgentObserver] = field(default_factory=list)

    @property
    def jobs(self) -> JobRepository:
        return self.container.job_repository

    def make_observer(self, **pools: Any) -> AgentObserver:
        """Built after the hand-offs under test: it binds the service's pumps."""

        observer = AgentObserver(
            self.service,
            exchange_executor=SynchronousExecutor(),
            observation_executor=pools.get("observation", SynchronousExecutor()),
            control_executor=SynchronousExecutor(),
            clock=self.clock,
            observation_interval=timedelta(hours=1),
        )
        self.observers.append(observer)
        return observer

    def observation(self, observer: AgentObserver | None = None) -> Any:
        return AgentObservationAdapter(observer or self.make_observer(), self.gate)

    def recovery(self, observer: AgentObserver | None = None) -> AgentRecoveryAdapter:
        return AgentRecoveryAdapter(
            observer or self.make_observer(), self.gate, self.jobs, now=self.clock
        )

    def worker(self, *adapters: Any) -> JobWorker:
        return JobWorker(
            self.jobs, JobRegistry(adapters), now=self.clock, owner_id="w1"
        )

    def claim(self, adapter: Any) -> JobLease:
        self.jobs.ensure_scheduled(
            job_type=adapter.job_type,
            dedup_key=adapter.schedule_key,
            run_at=self.clock(),
        )
        lease = self.jobs.claim_due(
            owner="w1", types=(adapter.job_type,), now=self.clock(), lease_for=LEASE
        )
        assert lease is not None
        return lease

    def context(self, lease: JobLease) -> JobContext:
        return JobContext(
            lease,
            lambda: self.jobs.should_abandon(
                lease.job_id, fence=lease.fence, now=self.clock()
            ),
        )

    def run(self, adapter: Any) -> JobOutcome:
        outcome: JobOutcome = adapter.run(self.context(self.claim(adapter)))
        return outcome

    def create_task(self) -> str:
        return self.container.task_service.create_task(
            TaskCreateRequest(title="Written by a job"),
            owner_id=OWNER,
            idempotency_key="key-agent-job",
        ).id

    def titles(self) -> list[str]:
        return [
            task.title
            for task in self.container.task_repo.list_for_owner(owner_id=OWNER)
        ]

    def due(self) -> None:
        self.clock.advance(timedelta(seconds=61))

    def open_exchange(self, key: str, *, owner_id: str = OWNER) -> str:
        """A hand-off whose exchange had started when the process died."""

        connection_id = connect_ready(
            self.service,
            owner_id=owner_id,
            address=f"https://{key}.example.com",
            key=f"{key}-create",
        )
        run_id = queue_handoff(
            self.service, connection_id, owner_id=owner_id, key=f"{key}-dispatch"
        )
        started = self.repo.start_exchange(
            self.repo.get_run(run_id, owner_id=owner_id),
            expected_version=0,
            started_at=self.clock(),
            deadline_at=self.clock() + timedelta(minutes=5),
        )
        assert started is not None
        self.a2a.calls.clear()  # the connection test probe is not under test
        return run_id

    def lookup_job_id(self, run_id: str, *, owner_id: str = OWNER) -> str:
        record = self.jobs.find_active(f"{RECOVER_JOB_TYPE}:{run_id}", scope=owner_id)
        assert record is not None
        assert record.payload_ref == run_id
        return record.job_id

    def exchange_of(self, run_id: str, *, owner_id: str = OWNER) -> str:
        return self.repo.get_run(run_id, owner_id=owner_id).exchange_state


@pytest.fixture()
def rig(container: Container, tmp_path: Path) -> Generator[Rig]:
    clock = Clock(datetime(2026, 8, 9, 12, 0, tzinfo=UTC))
    a2a = FakeA2AClient()
    repo = AgentRepository(tmp_path / "agents")
    service = AgentRelayService(
        repo,
        secret_box=SecretBox(OrderedDict({"v1": b"\x07" * 32})),
        task_snapshot=task_snapshot,
        push_base_url=PUSH_BASE,
        card_fetcher=FakeCardFetcher(),
        a2a_client=a2a,
        resolver=lambda host, port: ["93.184.216.34"],
        now=clock,
    )
    authority = Authority(OWNER, OTHER_OWNER)
    gate = JobExecutionGate(
        container.job_repository, owner_current=authority, now=clock
    )
    built = Rig(container, service, repo, clock, a2a, gate, authority)
    yield built
    for observer in built.observers:
        observer.shutdown()


def working(task_id: str, run_id: str) -> A2AResult:
    return A2AResult(ok=True, correlation_id="c", task=observed_task(task_id, run_id))


# --- the observation job -----------------------------------------------------


def test_026_FR_015_observation_runs_as_a_recurring_ledger_job(rig: Rig) -> None:
    run_id = dispatched(rig.service, rig.a2a, rig.clock)
    rig.a2a.script("GetTask", working("t1", run_id))
    adapter = rig.observation()
    worker = rig.worker(adapter)
    assert worker.ensure_schedules() == 1
    rig.due()
    rig.clock.advance(adapter.cadence)

    assert worker.run_once()

    assert rig.repo.get_run(run_id, owner_id=OWNER).last_observed_at == rig.clock()
    assert len(rig.a2a.calls_to("GetTask")) == 1
    queued = rig.jobs.find_active(adapter.schedule_key)
    assert queued is not None
    assert queued.status is JobStatus.QUEUED
    assert queued.run_at > rig.clock()


def test_026_FR_015_unreachable_agent_is_the_runs_state_not_a_failed_job(
    rig: Rig,
) -> None:
    run_id = dispatched(rig.service, rig.a2a, rig.clock)
    rig.a2a.script(
        "GetTask",
        A2AResult(ok=False, correlation_id="c", error_code="a2a_unreachable"),
    )
    rig.due()

    outcome = rig.run(rig.observation())

    assert outcome == JobOutcome()
    run = rig.repo.get_run(run_id, owner_id=OWNER)
    assert run.next_observation_at is not None
    assert run.next_observation_at > rig.clock()


def test_026_FR_021_observation_reads_the_agent_and_never_sends_or_edits_a_task(
    rig: Rig,
) -> None:
    run_id = dispatched(rig.service, rig.a2a, rig.clock)
    rig.a2a.script("GetTask", working("t1", run_id))
    before = rig.titles()
    rig.due()

    rig.run(rig.observation())

    assert len(rig.a2a.calls_to("GetTask")) == 1
    assert rig.a2a.calls_to("SendMessage") == []
    assert rig.titles() == before


def test_026_FR_014_the_pass_runs_bound_to_the_job_execution_context(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    dispatched(rig.service, rig.a2a, rig.clock)
    rig.due()
    seen: list[WriterOrigin] = []
    read = rig.service.read_agent_task

    def spy(run: Any) -> A2AResult | None:
        seen.append(current_writer_origin())
        return read(run)

    monkeypatch.setattr(rig.service, "read_agent_task", spy)

    rig.run(rig.observation())

    assert seen == [WriterOrigin.JOB]
    assert current_writer_origin() is WriterOrigin.LEGACY


def test_026_FR_014_expired_lease_cannot_authorize_a_task_write_from_the_pass(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = dispatched(rig.service, rig.a2a, rig.clock)
    rig.a2a.script("GetTask", working("t1", run_id))
    rig.due()
    refusals: list[Exception] = []
    read = rig.service.read_agent_task

    def read_after_the_lease_lapses(run: Any) -> A2AResult | None:
        rig.clock.advance(LEASE + timedelta(seconds=1))
        try:
            rig.create_task()
        except StaleExecutorError as refused:
            refusals.append(refused)
        return read(run)

    monkeypatch.setattr(rig.service, "read_agent_task", read_after_the_lease_lapses)

    rig.run(rig.observation())

    assert len(refusals) == 1
    assert rig.titles() == []


def test_026_SC_007_lost_lease_stops_the_pass_and_leaves_the_rest_due(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection_id = connect_ready(rig.service, key="idem-shared")
    first = dispatched(
        rig.service, rig.a2a, rig.clock, connection_id=connection_id, key="idem-a"
    )
    second = dispatched(
        rig.service,
        rig.a2a,
        rig.clock,
        connection_id=connection_id,
        task_id="task_2",
        key="idem-b",
    )
    rig.a2a.script("GetTask", working("t1", first))
    rig.due()
    before = {
        run_id: rig.repo.get_run(run_id, owner_id=OWNER) for run_id in (first, second)
    }
    read = rig.service.read_agent_task

    def read_then_lose_the_lease(run: Any) -> A2AResult | None:
        result = read(run)
        rig.clock.advance(LEASE + timedelta(seconds=1))
        return result

    monkeypatch.setattr(rig.service, "read_agent_task", read_then_lose_the_lease)
    observer = rig.make_observer()

    outcome = rig.run(rig.observation(observer))

    assert outcome == JobOutcome(safe_error="authority_lost")
    assert len(rig.a2a.calls_to("GetTask")) == 1
    unread = [
        run_id
        for run_id, run in before.items()
        if rig.repo.get_run(run_id, owner_id=OWNER) == run
    ]
    assert len(unread) == 1
    # Nothing was consumed: the next owner of the schedule still finds it due.
    assert observer.observe_due().claimed == 1


def test_026_SC_007_a_stopped_pass_keeps_a_pushed_wake_for_the_next_one(
    rig: Rig,
) -> None:
    run_id = dispatched(rig.service, rig.a2a, rig.clock)  # not yet due
    observer = rig.make_observer()
    observer.wake(run_id)

    stopped = observer.observe_due(keep_going=lambda: False)

    assert (stopped.claimed, stopped.handled) == (1, 0)
    assert rig.a2a.calls_to("GetTask") == []
    assert observer.observe_due().handled == 1


# --- one owner at a time -----------------------------------------------------


def test_026_SC_007_a_running_scheduler_thread_blocks_the_handoff(rig: Rig) -> None:
    observer = rig.make_observer()
    assert observer.start() is True

    with pytest.raises(SchedulerOverlapError):
        AgentObservationAdapter(observer, rig.gate)
    with pytest.raises(SchedulerOverlapError):
        observer.observe_due()


def test_026_SC_007_a_delegated_observer_never_starts_its_own_thread(
    rig: Rig,
) -> None:
    observer = rig.make_observer()
    rig.observation(observer)

    assert observer.start() is False
    assert observer.scheduler_thread is None


def test_026_SC_007_old_and_new_passes_never_read_one_run_twice(rig: Rig) -> None:
    run_id = dispatched(rig.service, rig.a2a, rig.clock)
    rig.a2a.script("GetTask", working("t1", run_id))
    deferred = DeferredExecutor()
    observer = rig.make_observer(observation=deferred)
    rig.due()

    assert observer.run_once() == 1  # the old path holds the run, read pending
    overlapping = observer.observe_due()
    assert (overlapping.claimed, overlapping.handled) == (0, 0)
    assert rig.a2a.calls_to("GetTask") == []

    deferred.run_pending()
    assert len(rig.a2a.calls_to("GetTask")) == 1


def test_026_FR_015_a_verified_push_wake_reaches_the_durable_owner(rig: Rig) -> None:
    run_id = dispatched(rig.service, rig.a2a, rig.clock)
    observer = rig.make_observer()
    woken: list[str] = []
    observer.wake_listener = lambda: woken.append("wake")

    observer.wake(run_id)

    assert woken == ["wake"]


# --- the recovery jobs -------------------------------------------------------


def test_026_FR_015_the_sweep_records_one_lookup_job_per_open_exchange(
    rig: Rig,
) -> None:
    mine = rig.open_exchange("exchange-a")
    theirs = rig.open_exchange("exchange-b", owner_id=OTHER_OWNER)
    never_left = queue_handoff(
        rig.service,
        connect_ready(rig.service, address="https://exchange-c.example.com", key="c"),
        key="idem-queued",
    )
    rig.a2a.calls.clear()
    adapter = rig.recovery()
    worker = rig.worker(adapter)
    assert worker.ensure_schedules(due_now=True) == 1

    assert worker.run_once()

    for run_id, owner_id in ((mine, OWNER), (theirs, OTHER_OWNER)):
        assert rig.exchange_of(run_id, owner_id=owner_id) == "interrupted"
        rig.lookup_job_id(run_id, owner_id=owner_id)
    assert rig.exchange_of(never_left) == "closed"
    assert rig.jobs.find_active(f"{RECOVER_JOB_TYPE}:{never_left}") is None
    # Marking is pure state: no byte went to any agent during the sweep.
    assert rig.a2a.calls == []


def test_026_FR_021_a_lookup_that_finds_the_task_settles_the_run_without_a_send(
    rig: Rig,
) -> None:
    run_id = rig.open_exchange("exchange-a")
    worker = rig.worker(rig.recovery())
    worker.ensure_schedules(due_now=True)
    worker.run_once()
    job_id = rig.lookup_job_id(run_id)
    rig.a2a.script(
        "ListTasks",
        A2AResult(ok=True, correlation_id="c", tasks=(agent_task("t-found", run_id),)),
    )

    assert worker.run_once()

    run = rig.repo.get_run(run_id, owner_id=OWNER)
    assert (run.exchange_state, run.dispatch_state) == ("closed", "sent")
    assert run.agent_task_id == "t-found"
    record = rig.jobs.get(job_id)
    assert record is not None
    assert record.status is JobStatus.SUCCEEDED
    assert rig.a2a.calls_to("SendMessage") == []


@pytest.mark.parametrize(
    "answer",
    [
        A2AResult(ok=True, correlation_id="c"),
        A2AResult(ok=False, correlation_id="c", error_code=A2A_TIMEOUT),
    ],
    ids=["agent-has-no-such-task", "lookup-timed-out"],
)
def test_026_SC_007_a_lookup_without_proof_is_parked_never_reported_as_success(
    rig: Rig, answer: A2AResult
) -> None:
    run_id = rig.open_exchange("exchange-a")
    worker = rig.worker(rig.recovery())
    worker.ensure_schedules(due_now=True)
    worker.run_once()
    job_id = rig.lookup_job_id(run_id)
    rig.a2a.script("ListTasks", answer)

    assert worker.run_once()

    record = rig.jobs.get(job_id)
    assert record is not None
    assert record.status is JobStatus.RECONCILIATION_REQUIRED
    assert record.last_error == "delivery_unproven"
    run = rig.repo.get_run(run_id, owner_id=OWNER)
    assert run.exchange_state == "interrupted"
    assert run.dispatch_state == "delivery_unconfirmed"
    # Not retried by itself, and never resent: only a decision moves it.
    rig.clock.advance(timedelta(hours=1))
    assert worker.run_once() is False
    assert len(rig.a2a.calls_to("ListTasks")) == 1
    assert rig.a2a.calls_to("SendMessage") == []


def test_026_SC_007_a_parked_lookup_ends_only_when_a_later_lookup_proves_it(
    rig: Rig,
) -> None:
    run_id = rig.open_exchange("exchange-a")
    worker = rig.worker(rig.recovery())
    worker.ensure_schedules(due_now=True)
    worker.run_once()
    job_id = rig.lookup_job_id(run_id)
    rig.a2a.script("ListTasks", A2AResult(ok=True, correlation_id="c"))
    worker.run_once()
    rig.a2a.script(
        "ListTasks",
        A2AResult(ok=True, correlation_id="c", tasks=(agent_task("t-found", run_id),)),
    )

    assert rig.jobs.resolve_reconciliation(job_id, decision="retry", run_at=rig.clock())
    assert worker.run_once()

    record = rig.jobs.get(job_id)
    assert record is not None
    assert record.status is JobStatus.SUCCEEDED
    assert rig.exchange_of(run_id) == "closed"


def test_026_SC_007_the_sweep_survives_a_crash_between_recording_and_marking(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = rig.open_exchange("exchange-a")
    worker = rig.worker(rig.recovery())
    worker.ensure_schedules(due_now=True)
    mark = rig.service.mark_exchange_interrupted
    monkeypatch.setattr(
        rig.service,
        "mark_exchange_interrupted",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("process died")),
    )

    assert worker.run_once()

    # The lookup was recorded first, so the exchange is not orphaned.
    rig.lookup_job_id(run_id)
    assert rig.exchange_of(run_id) == "open"

    monkeypatch.setattr(rig.service, "mark_exchange_interrupted", mark)
    rig.clock.advance(timedelta(seconds=5))
    # The recorded lookup is due first and finds nothing marked yet, so it ends
    # without a request; the retried sweep then marks and records it again.
    assert worker.run_once()
    assert worker.run_once()

    assert rig.exchange_of(run_id) == "interrupted"
    rig.lookup_job_id(run_id)
    assert rig.a2a.calls == []


def test_026_FR_015_a_lookup_for_a_revoked_owner_is_refused_before_any_request(
    rig: Rig,
) -> None:
    run_id = rig.open_exchange("exchange-a")
    worker = rig.worker(rig.recovery())
    worker.ensure_schedules(due_now=True)
    worker.run_once()
    job_id = rig.lookup_job_id(run_id)
    rig.authority.live.discard(OWNER)

    assert worker.run_once()

    assert rig.a2a.calls_to("ListTasks") == []
    record = rig.jobs.get(job_id)
    assert record is not None
    assert record.last_error == "ScopeRevokedError"
    assert rig.exchange_of(run_id) == "interrupted"


def test_026_FR_015_a_stale_executor_makes_no_lookup(rig: Rig) -> None:
    run_id = rig.open_exchange("exchange-a")
    adapter = rig.recovery()
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    worker.run_once()
    lease = rig.jobs.claim_due(
        owner="w1", types=(RECOVER_JOB_TYPE,), now=rig.clock(), lease_for=LEASE
    )
    assert lease is not None
    assert lease.payload_ref == run_id
    rig.clock.advance(LEASE + timedelta(seconds=1))

    outcome = adapter.run(rig.context(lease))

    assert outcome == JobOutcome(safe_error="StaleExecutorError")
    assert rig.a2a.calls_to("ListTasks") == []
