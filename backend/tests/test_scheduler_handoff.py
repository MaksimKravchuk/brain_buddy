"""The scheduler handoff: one durable worker owns each handed-off responsibility.

Spec 026 PR-64 (026-FR-014, 026-FR-015, 026-SC-007). The adapters of PR-22/23/24
are registered against the job ledger and the execution context by
``app.main._install_durable_scheduler`` behind the default-OFF
``BRAIN_BUDDY_DURABLE_SCHEDULER`` gate. The ledger is a real SQLite file, the
observer is the real ``AgentObserver`` and one fake clock drives every due time
and lease expiry; the ports behind the adapters are recorders, so a responsibility
that two owners ran would show up twice in the journal.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.core import get_config
from app.main import (
    _durable_scheduler_enabled,
    _install_durable_scheduler,
    _run_maintenance_sweep,
    _run_privacy_maintenance_sweep,
    _wake_job,
    create_app,
)
from app.modules.agents.observer import AgentObserver, SchedulerOverlapError
from app.modules.agents.service import AgentRelayService
from app.modules.tasks.jobs import JobRepository, JobStatus
from app.modules.tasks.jobs.agent_adapter import OBSERVE_JOB_TYPE, RECOVER_JOB_TYPE
from app.modules.tasks.jobs.execution import JobExecutionGate
from app.modules.tasks.jobs.privacy_adapter import (
    PRIVACY_JOB_TYPE,
    PRIVACY_SCHEDULE_KEY,
)
from app.modules.tasks.jobs.review_adapter import (
    REVIEW_MAINTENANCE_JOB_TYPE,
    REVIEW_MAINTENANCE_SCHEDULE_KEY,
)
from app.modules.tasks.jobs.voice_adapter import VOICE_JOB_TYPE, VOICE_SCHEDULE_KEY
from app.modules.tasks.jobs.worker import (
    DuplicateSchedulerOwnerError,
    JobWorker,
    Responsibility,
    SchedulerHandoff,
    SchedulerOwner,
)
from app.services.modern_auth_service import ModernAuthService

from .test_agent_observer import SynchronousExecutor

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
LEASE = timedelta(seconds=60)
OWNER = "user_handoff_a"
VOICE_INTERVAL = 60.0
PRIVACY_INTERVAL = 300.0

#: The ports the durable worker takes over, and the ones that never leave.
HANDED_OFF = (
    "review.sweep",
    "account.purge",
    "relay.retention",
    "crt.receipt_retention",
    "voice.recover_leases",
    "voice.advance_runs",
    "voice.resume_commits",
    "voice.purge_raw_audio",
    "voice.purge_working_artifacts",
)
STAYS_LEGACY = (
    "auth.cleanup_metadata",
    "auth.cleanup_backup",
    "auth.cli_cleanup",
    "crt.reconcile",
)


class Clock:
    def __init__(self) -> None:
        self.moment = T0

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += timedelta(seconds=seconds)


class WorkerCrash(BaseException):
    """A process death: not an ``Exception``, so no handler may swallow it."""


def _ports(journal: list[str], **names: str) -> SimpleNamespace:
    """A module's existing ports, each one recording its journal entry."""

    def make(entry: str) -> Callable[[], int]:
        def call() -> int:
            journal.append(entry)
            return 0

        return call

    return SimpleNamespace(**{method: make(entry) for method, entry in names.items()})


class Rig:
    """A container-shaped bundle of real ledger/observer and recorded ports."""

    def __init__(self, tmp_path: Path, clock: Clock) -> None:
        self.clock = clock
        self.journal: list[str] = []
        self.ledger = JobRepository(tmp_path / "tasks.sqlite3", jitter=lambda c: c)
        self.gate = JobExecutionGate(
            self.ledger, owner_current=lambda _owner: True, now=clock
        )
        self.service = MagicMock()
        self.service.agent_repo.interrupted_exchanges.return_value = []
        self.service.agent_repo.get_run.return_value = SimpleNamespace(
            exchange_state="settled"
        )
        self.observer = AgentObserver(
            self.service,
            exchange_executor=SynchronousExecutor(),
            clock=clock,
            observation_interval=timedelta(minutes=5),
        )
        j = self.journal
        self.voice = _ports(
            j,
            recover_due_provider_leases="voice.recover_leases",
            run_due_brain_dump_provider_runs="voice.advance_runs",
            recover_committing_operations="voice.resume_commits",
            purge_expired_raw_audio="voice.purge_raw_audio",
            purge_expired_working_artifacts="voice.purge_working_artifacts",
        )
        self.voice.runner_wake = lambda: j.append("voice.legacy_wake")
        self.container: Any = SimpleNamespace(
            review_service=_ports(j, run_maintenance_sweep="review.sweep"),
            account_service=_ports(j, purge_due_accounts="account.purge"),
            agent_relay_service=_ports(j, run_retention_sweep="relay.retention"),
            crt_command_repo=_ports(j, purge_expired="crt.receipt_retention"),
            crt_command_service=_ports(j, reconcile_pending_commands="crt.reconcile"),
            modern_auth_service=_ports(
                j, cleanup_expired_metadata="auth.cleanup_metadata"
            ),
            auth_migration=_ports(j, cleanup_expired_backup="auth.cleanup_backup"),
            cli_auth_service=_ports(j, cleanup="auth.cli_cleanup"),
            voice_brain_dump_service=self.voice,
            agent_observer=self.observer,
            job_repository=self.ledger,
            job_execution=self.gate,
        )

    def install(
        self,
        handoff: SchedulerHandoff,
        *,
        voice_interval: float = VOICE_INTERVAL,
    ) -> JobWorker | None:
        return _install_durable_scheduler(
            self.container,
            handoff,
            voice_interval_seconds=voice_interval,
            privacy_interval_seconds=PRIVACY_INTERVAL,
            now=self.clock,
        )

    def install_after_restart(self) -> JobWorker:
        """A second process: its own handoff, observer and worker, same ledger."""

        self.observer = AgentObserver(
            self.service,
            exchange_executor=SynchronousExecutor(),
            clock=self.clock,
            observation_interval=timedelta(minutes=5),
        )
        self.container.agent_observer = self.observer
        worker = self.install(_enabled())
        assert worker is not None
        return worker

    def drain(self, worker: JobWorker) -> int:
        ran = 0
        while worker.run_once():
            ran += 1
        return ran

    def active(self, key: str):  # type: ignore[no-untyped-def]
        record = self.ledger.find_active(key)
        assert record is not None
        return record

    def count(self) -> Counter[str]:
        return Counter(self.journal)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    built = Rig(tmp_path, Clock())
    yield built  # type: ignore[misc]
    built.observer.shutdown()


def _enabled() -> SchedulerHandoff:
    return SchedulerHandoff(enabled=True)


# --- the gate is default OFF ---------------------------------------------------


def test_026_SC_007_the_gate_is_off_unless_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BRAIN_BUDDY_DURABLE_SCHEDULER", raising=False)
    assert _durable_scheduler_enabled() is False
    for off in ("", "0", "false", "off", "no"):
        monkeypatch.setenv("BRAIN_BUDDY_DURABLE_SCHEDULER", off)
        assert _durable_scheduler_enabled() is False
    for on in ("1", "true", "YES", " on "):
        monkeypatch.setenv("BRAIN_BUDDY_DURABLE_SCHEDULER", on)
        assert _durable_scheduler_enabled() is True


def test_026_SC_007_with_the_gate_off_the_legacy_loops_stay_the_sole_owners(
    rig: Rig,
) -> None:
    """Nothing is registered, assigned or woken; every duty runs on the old path."""

    legacy_wake = rig.voice.runner_wake
    handoff = SchedulerHandoff()
    assert rig.install(handoff) is None
    handoff.assign_remaining_to_legacy()

    assert all(handoff.owner(r) is SchedulerOwner.LEGACY for r in Responsibility)
    with pytest.raises(DuplicateSchedulerOwnerError, match="not enabled"):
        SchedulerHandoff().assign(Responsibility.VOICE_SWEEP, SchedulerOwner.DURABLE)
    for key in (
        VOICE_SCHEDULE_KEY,
        PRIVACY_SCHEDULE_KEY,
        REVIEW_MAINTENANCE_SCHEDULE_KEY,
    ):
        assert rig.ledger.find_active(key) is None
    assert rig.voice.runner_wake is legacy_wake

    _run_maintenance_sweep(rig.container, handoff)

    assert set(rig.journal) >= set(HANDED_OFF) | set(STAYS_LEGACY)
    assert rig.observer.start() is True  # not delegated: the thread is its owner
    rig.observer.shutdown()


def test_026_SC_007_the_app_stays_on_the_legacy_loops_when_the_gate_is_on_in_tests(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path
) -> None:
    """Test apps run no background maintenance, so no hand-over can happen there."""

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_DURABLE_SCHEDULER", "1")
    get_config.cache_clear()
    try:
        app = create_app()
        assert app.state.durable_worker is None
        assert app.state.scheduler_handoff.enabled is False
        assert all(
            app.state.scheduler_handoff.owner(r) is SchedulerOwner.LEGACY
            for r in Responsibility
        )
        assert not [t for t in threading.enumerate() if t.name == "durable-job-worker"]
    finally:
        get_config.cache_clear()


# --- registration and a single owner --------------------------------------------


def test_026_FR_014_every_handed_off_responsibility_gets_exactly_one_owner(
    rig: Rig,
) -> None:
    """Gate on: the worker owns all five; auth and CRT reconcile never leave."""

    handoff = _enabled()
    worker = rig.install(handoff)
    assert worker is not None
    handoff.assign_remaining_to_legacy()

    assert all(handoff.durable(r) for r in Responsibility)
    assert set(worker.registry.types) == {
        REVIEW_MAINTENANCE_JOB_TYPE,
        PRIVACY_JOB_TYPE,
        VOICE_JOB_TYPE,
        OBSERVE_JOB_TYPE,
        RECOVER_JOB_TYPE,
    }
    # Auth delivery/cleanup and CRT reconciliation are not responsibilities here.
    assert not {r.value for r in Responsibility} & {"auth", "crt_reconcile"}

    # Legacy startup sweep plus one tick of the legacy loop: only what stays.
    _run_maintenance_sweep(rig.container, handoff)
    _run_privacy_maintenance_sweep(rig.container, handoff)
    assert set(rig.journal) == set(STAYS_LEGACY)
    assert rig.count()["crt.reconcile"] == 2

    # The worker's boot occurrences are the only run of every handed-off port.
    assert worker.ensure_schedules(due_now=True) == 5
    assert rig.drain(worker) == 5
    counts = rig.count()
    assert {port: counts[port] for port in HANDED_OFF} == dict.fromkeys(HANDED_OFF, 1)
    assert all(counts[port] == 2 for port in STAYS_LEGACY)


def test_026_FR_015_adapters_use_the_legacy_cadences(rig: Rig) -> None:
    worker = rig.install(_enabled())
    assert worker is not None
    registry = worker.registry
    assert registry.get(VOICE_JOB_TYPE).cadence == timedelta(  # type: ignore[union-attr]
        seconds=VOICE_INTERVAL
    )
    for job_type in (PRIVACY_JOB_TYPE, REVIEW_MAINTENANCE_JOB_TYPE):
        assert registry.get(job_type).cadence == timedelta(  # type: ignore[union-attr]
            seconds=PRIVACY_INTERVAL
        )
    assert registry.get(OBSERVE_JOB_TYPE).cadence == timedelta(minutes=5)  # type: ignore[union-attr]
    assert registry.get(RECOVER_JOB_TYPE).cadence is None  # type: ignore[union-attr]


def test_026_FR_014_a_zero_voice_cadence_registers_no_voice_adapter(rig: Rig) -> None:
    """The old thread is disabled at 0; the startup pass keeps its old owner."""

    handoff = _enabled()
    worker = rig.install(handoff, voice_interval=0)
    assert worker is not None
    handoff.assign_remaining_to_legacy()

    assert VOICE_JOB_TYPE not in worker.registry.types
    assert handoff.owner(Responsibility.VOICE_SWEEP) is SchedulerOwner.LEGACY
    assert handoff.durable(Responsibility.PRIVACY_RETENTION)

    _run_maintenance_sweep(rig.container, handoff)

    assert rig.count()["voice.recover_leases"] == 1
    assert rig.count()["account.purge"] == 0


def test_026_SC_007_a_second_owner_for_a_responsibility_is_refused(rig: Rig) -> None:
    handoff = _enabled()
    assert rig.install(handoff) is not None

    with pytest.raises(DuplicateSchedulerOwnerError, match="review_sweep"):
        handoff.assign(Responsibility.REVIEW_SWEEP, SchedulerOwner.LEGACY)
    with pytest.raises(DuplicateSchedulerOwnerError, match="already owned"):
        rig.install(handoff)  # a second worker for the same duties

    legacy = _enabled()
    legacy.assign(Responsibility.AGENT_OBSERVATION, SchedulerOwner.LEGACY)
    with pytest.raises(DuplicateSchedulerOwnerError, match="agent_observation"):
        legacy.assign(Responsibility.AGENT_OBSERVATION, SchedulerOwner.DURABLE)


def test_026_SC_007_the_observer_thread_and_the_worker_cannot_both_observe(
    rig: Rig,
) -> None:
    """Handing over delegates scheduling for good, and refuses a live thread."""

    running = AgentObserver(
        rig.service,
        exchange_executor=SynchronousExecutor(),
        clock=rig.clock,
    )
    try:
        assert running.start() is True
        rig.container.agent_observer = running
        with pytest.raises(SchedulerOverlapError):
            rig.install(_enabled())
    finally:
        running.shutdown()
        rig.container.agent_observer = rig.observer

    handoff = _enabled()
    assert rig.install(handoff) is not None
    assert rig.observer.start() is False
    assert rig.observer.scheduler_thread is None


def test_026_FR_015_two_workers_cannot_hold_the_same_job_at_once(rig: Rig) -> None:
    first = rig.install(_enabled())
    assert first is not None
    first.ensure_schedules(due_now=True)
    second = JobWorker(rig.ledger, first.registry, now=rig.clock, owner_id="other")

    claimed = rig.ledger.claim_due(
        owner="holder",
        types=(REVIEW_MAINTENANCE_JOB_TYPE,),
        now=rig.clock(),
        lease_for=LEASE,
    )
    assert claimed is not None

    # Another process asking now gets the other four jobs, never the leased one.
    assert rig.drain(second) == 4
    assert "review.sweep" not in rig.journal
    assert rig.active(REVIEW_MAINTENANCE_SCHEDULE_KEY).lease_owner == "holder"


# --- restart and lease expiry ----------------------------------------------------


def test_026_SC_007_a_restart_reasserts_the_same_schedule_not_a_second_one(
    rig: Rig,
) -> None:
    worker = rig.install(_enabled())
    assert worker is not None
    assert worker.ensure_schedules(due_now=True) == 5
    before = {
        key: rig.active(key).job_id
        for key in (
            VOICE_SCHEDULE_KEY,
            PRIVACY_SCHEDULE_KEY,
            REVIEW_MAINTENANCE_SCHEDULE_KEY,
        )
    }

    # A new process on the same ledger: new handoff, adapters and worker.
    restarted = rig.install_after_restart()
    assert restarted.ensure_schedules(due_now=True) == 0
    assert {key: rig.active(key).job_id for key in before} == before


def test_026_SC_007_a_crashed_owner_blocks_others_until_the_lease_lapses(
    rig: Rig,
) -> None:
    """One live owner across a crash: the effect restarts once, the stale one is fenced."""

    rig.container.review_service = SimpleNamespace(
        run_maintenance_sweep=_crash_once(rig.journal)
    )
    worker = rig.install(_enabled())
    assert worker is not None
    worker.ensure_schedules(due_now=True)
    job = rig.active(REVIEW_MAINTENANCE_SCHEDULE_KEY)
    only_review = JobWorker(
        rig.ledger,
        _only(worker, REVIEW_MAINTENANCE_JOB_TYPE),
        now=rig.clock,
        owner_id="w-before-crash",
    )
    with pytest.raises(WorkerCrash):
        only_review.run_once()
    crashed = rig.active(REVIEW_MAINTENANCE_SCHEDULE_KEY)
    assert crashed.status is JobStatus.LEASED and crashed.fence == 1

    # The restarted process finds the lease live and does not run the effect.
    survivor = JobWorker(
        rig.ledger,
        _only(worker, REVIEW_MAINTENANCE_JOB_TYPE),
        now=rig.clock,
        owner_id="w-after-restart",
    )
    rig.clock.advance(LEASE.total_seconds() - 1)
    assert survivor.run_once() is False

    rig.clock.advance(2)  # the lease has lapsed: requeued behind the first backoff
    assert survivor.run_once() is False
    rig.clock.advance(1)  # jitter is pinned to its 1 s ceiling in this ledger
    assert survivor.run_once() is True
    settled = rig.ledger.get(job.job_id)
    assert settled is not None and settled.status is JobStatus.SUCCEEDED
    assert settled.fence == 2
    assert rig.count()["review.sweep"] == 1  # the crashed attempt never finished

    # The old claimant's late result is refused by the fence and changes nothing.
    assert rig.ledger.complete(job.job_id, fence=1) is False
    successor = rig.active(REVIEW_MAINTENANCE_SCHEDULE_KEY)
    assert successor.job_id != job.job_id and successor.status is JobStatus.QUEUED


def test_026_FR_015_boot_recovery_marks_interrupted_exchanges_through_the_ledger(
    rig: Rig,
) -> None:
    """With the worker owning recovery, the boot sweep records a lookup job per run."""

    rig.service.agent_repo.interrupted_exchanges.return_value = [
        (OWNER, "run_1", "started")
    ]
    worker = rig.install(_enabled())
    assert worker is not None
    worker.ensure_schedules(due_now=True)

    assert rig.drain(worker) == 6  # five boot occurrences plus one lookup
    rig.service.mark_exchange_interrupted.assert_called_once_with(
        "run_1", owner_id=OWNER
    )
    rig.service.resolve_interrupted_exchange.assert_called_once_with(
        "run_1", owner_id=OWNER
    )
    lookups = rig.ledger.find_active(f"{RECOVER_JOB_TYPE}:run_1", scope=OWNER)
    assert lookups is None  # settled, not left behind


# --- wake and the push paths ----------------------------------------------------


def test_026_FR_015_pushes_make_the_owning_job_due_without_running_it(
    rig: Rig,
) -> None:
    worker = rig.install(_enabled())
    assert worker is not None
    worker.ensure_schedules()
    voice_job = rig.active(VOICE_SCHEDULE_KEY)
    assert voice_job.run_at > rig.clock()

    rig.container.voice_brain_dump_service.runner_wake()
    rig.observer.wake_listener()  # type: ignore[misc]

    assert rig.active(VOICE_SCHEDULE_KEY).run_at == rig.clock()
    assert rig.active(VOICE_SCHEDULE_KEY).job_id == voice_job.job_id
    assert rig.ledger.find_active("agent.observe:schedule").run_at == rig.clock()  # type: ignore[union-attr]
    assert "voice.legacy_wake" not in rig.journal
    assert "voice.recover_leases" not in rig.journal  # nothing ran inline


def test_026_FR_015_a_failed_wake_never_fails_the_request_that_made_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    worker = MagicMock()
    worker.wake.side_effect = RuntimeError("ledger busy")

    _wake_job(worker, VOICE_JOB_TYPE)()

    worker.wake.assert_called_once_with(VOICE_JOB_TYPE)
    assert "wake deferred" in caplog.text


# --- the whole application ----------------------------------------------------------


def test_026_SC_007_the_application_boots_with_one_durable_owner_per_responsibility(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path
) -> None:
    """Gate on with background maintenance: the worker runs retention once and the
    legacy privacy loop keeps only auth cleanup and CRT reconciliation."""

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv(
        "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
    )
    monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAGS", "external_agent_relay=off")
    monkeypatch.delenv("BRAIN_BUDDY_AGENT_RELAY_KEYS", raising=False)
    monkeypatch.setenv("BRAIN_BUDDY_DURABLE_SCHEDULER", "1")
    monkeypatch.setenv("BRAIN_BUDDY_AGENT_RETENTION_SWEEP_INTERVAL_SECONDS", "3600")
    monkeypatch.setattr(main_module, "_VOICE_SWEEP_INTERVAL_SECONDS", 3600)
    get_config.cache_clear()
    # Patched on the classes: the worker's boot occurrence starts inside
    # ``create_app`` and must not run the real port first.
    retention_runs: list[int] = []
    retention_ran = threading.Event()
    legacy_ticked = threading.Event()

    def retention(self: AgentRelayService) -> int:
        retention_runs.append(1)
        retention_ran.set()
        return 0

    def auth_cleanup(self: ModernAuthService) -> None:
        legacy_ticked.set()

    monkeypatch.setattr(AgentRelayService, "run_retention_sweep", retention)
    monkeypatch.setattr(ModernAuthService, "cleanup_expired_metadata", auth_cleanup)
    real_start = main_module._start_privacy_maintenance_thread

    def start_privacy(container, stop_event, *, interval_seconds, **kwargs):  # type: ignore[no-untyped-def]
        assert interval_seconds == 3600
        return real_start(container, stop_event, interval_seconds=0.01, **kwargs)

    monkeypatch.setattr(main_module, "_start_privacy_maintenance_thread", start_privacy)
    try:
        app = create_app()
        container = app.state.container
        handoff = app.state.scheduler_handoff
        assert all(handoff.durable(r) for r in Responsibility)
        with TestClient(app):
            assert app.state.durable_worker.running
            assert app.state.voice_sweep_thread is None
            assert container.agent_observer.start() is False
            assert retention_ran.wait(timeout=5), "the worker never ran retention"
            assert legacy_ticked.wait(timeout=5), "the legacy loop lost auth cleanup"
        assert not app.state.durable_worker.running
        assert retention_runs == [1]
    finally:
        get_config.cache_clear()


# --- helpers that need the rig ------------------------------------------------------


def _crash_once(journal: list[str]) -> Callable[[], int]:
    """A sweep whose first run dies mid-effect; a completed run is journaled."""

    state = {"crashed": False}

    def sweep() -> int:
        if not state["crashed"]:
            state["crashed"] = True
            raise WorkerCrash
        journal.append("review.sweep")
        return 0

    return sweep


def _only(worker: JobWorker, job_type: str):  # type: ignore[no-untyped-def]
    from app.modules.tasks.jobs.worker import JobRegistry

    adapter = worker.registry.get(job_type)
    assert adapter is not None
    return JobRegistry([adapter])
