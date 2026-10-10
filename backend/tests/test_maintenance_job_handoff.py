"""Voice and privacy maintenance as durable job adapters (spec 026 PR-23, T023).

026-FR-014, 026-FR-015, 026-FR-022 and 026-SC-007. The adapters prepare the
hand-off of two ``app.main`` scheduler responsibilities onto the job ledger
without changing what they do. These tests run the real SQLite ledger, the real
``JobWorker`` and the real execution gate against recording ports, then against
the container's real ports, and show that: the inventory names every cadence and
existing port; the adapters call those ports in the old order with the old
failure behaviour; retries and shutdown keep their accepted semantics; an
executor that lost its claim cannot write Tasks; GDPR purge needs no flag; and
nothing here starts a second scheduler (PR-64 owns the actual hand-off).
"""

from __future__ import annotations

import hashlib
import inspect
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.container import Container
from app.core.config import AgentRelaySettings
from app.main import _run_privacy_maintenance_sweep, _run_voice_maintenance_sweep
from app.modules.agents.service import AgentRelayService
from app.modules.tasks.jobs import JobRecord, JobRepository, JobStatus
from app.modules.tasks.jobs.domain import SYSTEM_SCOPE
from app.modules.tasks.jobs.execution import (
    JobExecutionGate,
    WriterOrigin,
    current_execution,
    current_writer_origin,
)
from app.modules.tasks.jobs.maintenance import ABANDONED, MaintenanceResponsibility
from app.modules.tasks.jobs.privacy_adapter import (
    PRIVACY_JOB_TYPE,
    PRIVACY_RESPONSIBILITY,
    PRIVACY_SCHEDULE_KEY,
    PrivacyMaintenanceAdapter,
)
from app.modules.tasks.jobs.voice_adapter import (
    VOICE_JOB_TYPE,
    VOICE_RESPONSIBILITY,
    VOICE_SCHEDULE_KEY,
    VoiceMaintenanceAdapter,
)
from app.modules.tasks.jobs.worker import JobRegistry, JobWorker
from app.repositories.crt_command import CrtCommandRepository
from app.repositories.feature_flag import FlagMode
from app.schemas.tasks import TaskCreateRequest
from app.services.account_service import AccountService
from app.utils.time import utcnow
from app.workflows.voice_brain_dump.service import VoiceBrainDumpService
from tests.test_account_deletion import (
    _backdate_deletion,
    _request_deletion,
    _user_id,
)
from tests.test_brain_dump_operations_api import _manifest_hash, _start_operation
from tests.test_crt_receipt_retention import _receipt_fixture

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
WAIT = 5.0
OWNER = "user_maintenance_a"

VOICE_METHODS = (
    "recover_due_provider_leases",
    "run_due_brain_dump_provider_runs",
    "recover_committing_operations",
    "purge_expired_raw_audio",
    "purge_expired_working_artifacts",
)
PRIVACY_METHODS = ("purge_due_accounts", "run_retention_sweep", "purge_expired")

_PORT_CLASSES = {
    "VoiceBrainDumpService": VoiceBrainDumpService,
    "AccountService": AccountService,
    "AgentRelayService": AgentRelayService,
    "CrtCommandRepository": CrtCommandRepository,
}


class Clock:
    def __init__(self) -> None:
        self.moment = T0

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += timedelta(seconds=seconds)


class Ports:
    """Recording stand-in for a module's existing ports.

    ``journal`` is shared, so the order of calls across ports is observable.
    ``raises`` fails a named method; ``hooks`` runs code inside a named method
    (before it may raise), which is where a test moves the world mid-step.
    """

    def __init__(
        self,
        journal: list[str],
        *,
        raises: dict[str, Exception] | None = None,
        hooks: dict[str, Callable[[], None]] | None = None,
    ) -> None:
        self.journal = journal
        self.raises = raises or {}
        self.hooks = hooks or {}

    def _call(self, name: str) -> int:
        self.journal.append(name)
        if name in self.hooks:
            self.hooks[name]()
        if name in self.raises:
            raise self.raises[name]
        return 1

    # Voice
    def recover_due_provider_leases(self) -> int:
        return self._call("recover_due_provider_leases")

    def run_due_brain_dump_provider_runs(self) -> int:
        return self._call("run_due_brain_dump_provider_runs")

    def recover_committing_operations(self) -> int:
        return self._call("recover_committing_operations")

    def purge_expired_raw_audio(self) -> int:
        return self._call("purge_expired_raw_audio")

    def purge_expired_working_artifacts(self) -> int:
        return self._call("purge_expired_working_artifacts")

    # Privacy
    def purge_due_accounts(self) -> int:
        return self._call("purge_due_accounts")

    def run_retention_sweep(self) -> int:
        return self._call("run_retention_sweep")

    def purge_expired(self) -> int:
        return self._call("purge_expired")


@dataclass
class Rig:
    container: Container
    ledger: JobRepository
    clock: Clock
    gate: JobExecutionGate
    journal: list[str]

    def voice(self, **kwargs: object) -> VoiceMaintenanceAdapter:
        ports = Ports(self.journal, **kwargs)  # type: ignore[arg-type]
        return VoiceMaintenanceAdapter(ports, self.gate)

    def privacy(self, **kwargs: object) -> PrivacyMaintenanceAdapter:
        ports = Ports(self.journal, **kwargs)  # type: ignore[arg-type]
        return PrivacyMaintenanceAdapter(ports, ports, ports, self.gate)

    def worker(self, *adapters: object, **kwargs: object) -> JobWorker:
        return JobWorker(
            self.ledger,
            JobRegistry(adapters),  # type: ignore[arg-type]
            now=self.clock,
            owner_id="w1",
            **kwargs,  # type: ignore[arg-type]
        )

    def active(self, schedule_key: str) -> JobRecord:
        record = self.ledger.find_active(schedule_key)
        assert record is not None
        return record

    def task_titles(self, owner_id: str = OWNER) -> list[str]:
        repo = self.container.task_repo
        return [task.title for task in repo.list_for_owner(owner_id=owner_id)]

    def create_task(self, title: str) -> None:
        self.container.task_service.create_task(
            TaskCreateRequest(title=title),
            owner_id=OWNER,
            idempotency_key=f"key-{title}",
        )


@pytest.fixture()
def rig(container: Container) -> Rig:
    # Full jitter pinned to its ceiling so backoff is exact.
    ledger = JobRepository(container.job_repository.db_path, jitter=lambda cap: cap)
    clock = Clock()
    gate = JobExecutionGate(ledger, owner_current=lambda _owner: True, now=clock)
    return Rig(container, ledger, clock, gate, [])


def _real_worker(container: Container, *adapters: object) -> JobWorker:
    return JobWorker(
        container.job_repository,
        JobRegistry(adapters),  # type: ignore[arg-type]
        owner_id="real-w",
    )


# --- the adapter inventory -----------------------------------------------------


def _responsibilities() -> tuple[MaintenanceResponsibility, ...]:
    return (VOICE_RESPONSIBILITY, PRIVACY_RESPONSIBILITY)


def test_026_FR_014_inventory_names_every_step_as_an_existing_port() -> None:
    """Every inventoried port is a real method callable with no arguments."""

    for responsibility in _responsibilities():
        assert responsibility.steps
        for step in responsibility.steps:
            owner, method = step.port.split(".")
            target = getattr(_PORT_CLASSES[owner], method)
            required = [
                name
                for name, parameter in inspect.signature(target).parameters.items()
                if name != "self" and parameter.default is inspect.Parameter.empty
            ]
            assert required == [], f"{step.port} needs {required}"


def test_026_FR_014_inventory_lists_the_ports_the_old_sweeps_call_in_order() -> None:
    """The adapter order is the order the live sweeps call the same ports."""

    voice_journal: list[str] = []
    voice_container = SimpleNamespace(voice_brain_dump_service=Ports(voice_journal))
    _run_voice_maintenance_sweep(voice_container)  # type: ignore[arg-type]
    assert voice_journal == list(VOICE_METHODS)
    assert [s.port.split(".")[1] for s in VOICE_RESPONSIBILITY.steps] == voice_journal

    privacy_journal: list[str] = []
    ports = Ports(privacy_journal)
    privacy_container = SimpleNamespace(
        account_service=ports,
        agent_relay_service=ports,
        crt_command_repo=ports,
        modern_auth_service=MagicMock(),
        auth_migration=MagicMock(),
        cli_auth_service=MagicMock(),
        crt_command_service=MagicMock(),
        review_service=MagicMock(),
    )
    _run_privacy_maintenance_sweep(privacy_container)  # type: ignore[arg-type]
    assert privacy_journal == list(PRIVACY_METHODS)
    assert [
        s.port.split(".")[1] for s in PRIVACY_RESPONSIBILITY.steps
    ] == privacy_journal


def test_026_FR_014_inventory_names_each_cadence_where_it_is_read_today() -> None:
    """The cadence source is the live setting and the default matches it."""

    main_source = Path(inspect.getsourcefile(_run_voice_maintenance_sweep) or "")
    text = main_source.read_text(encoding="utf-8")
    config_text = Path(inspect.getsourcefile(AgentRelaySettings) or "").read_text(
        encoding="utf-8"
    )

    assert VOICE_RESPONSIBILITY.cadence_source == (
        "BRAIN_BUDDY_VOICE_SWEEP_INTERVAL_SECONDS"
    )
    assert re.search(
        rf'os\.getenv\(\s*"{VOICE_RESPONSIBILITY.cadence_source}",\s*"60"', text
    )
    assert VOICE_RESPONSIBILITY.default_cadence == timedelta(seconds=60)

    assert PRIVACY_RESPONSIBILITY.cadence_source in config_text
    default = AgentRelaySettings.model_fields["retention_sweep_interval_seconds"]
    assert timedelta(seconds=default.default) == (
        PRIVACY_RESPONSIBILITY.default_cadence
    )


def test_026_FR_014_privacy_inventory_leaves_auth_crt_and_review_with_their_owners() -> (
    None
):
    """Auth cleanup, CRT reconciliation and Review sweep stay on the old loop."""

    text = Path(inspect.getsourcefile(_run_voice_maintenance_sweep) or "").read_text(
        encoding="utf-8"
    )
    assert PRIVACY_RESPONSIBILITY.left_with_legacy
    for port in PRIVACY_RESPONSIBILITY.left_with_legacy:
        assert port.split(".")[1] in text, f"{port} is no longer in the old sweep"
    taken = {step.port for step in PRIVACY_RESPONSIBILITY.steps}
    assert taken.isdisjoint(PRIVACY_RESPONSIBILITY.left_with_legacy)
    assert VOICE_RESPONSIBILITY.left_with_legacy == ()


def test_026_FR_015_adapters_have_distinct_durable_schedule_identities(
    rig: Rig,
) -> None:
    """Each responsibility has its own job type and dedup key, created once."""

    voice, privacy = rig.voice(), rig.privacy()
    assert (voice.job_type, voice.schedule_key) == (VOICE_JOB_TYPE, VOICE_SCHEDULE_KEY)
    assert (privacy.job_type, privacy.schedule_key) == (
        PRIVACY_JOB_TYPE,
        PRIVACY_SCHEDULE_KEY,
    )
    assert len({voice.job_type, privacy.job_type}) == 2
    assert len({voice.schedule_key, privacy.schedule_key}) == 2

    worker = rig.worker(voice, privacy)
    assert worker.ensure_schedules() == 2
    assert worker.ensure_schedules() == 0  # idempotent: a restart adds nothing
    assert worker.running is False

    for adapter in (voice, privacy):
        record = rig.active(adapter.schedule_key)
        assert record.job_type == adapter.job_type
        assert record.scope == SYSTEM_SCOPE
        assert record.status is JobStatus.QUEUED
        assert record.run_at == T0 + adapter.cadence


def test_026_FR_015_a_recurring_cadence_must_be_positive(rig: Rig) -> None:
    """A zero cadence is refused instead of becoming a hot loop."""

    ports = Ports(rig.journal)
    with pytest.raises(ValueError, match="positive"):
        VoiceMaintenanceAdapter(ports, rig.gate, cadence=timedelta(0))
    with pytest.raises(ValueError, match="positive"):
        PrivacyMaintenanceAdapter(
            ports, ports, ports, rig.gate, cadence=timedelta(seconds=-1)
        )
    assert VoiceMaintenanceAdapter(
        ports, rig.gate, cadence=timedelta(seconds=7)
    ).cadence == timedelta(seconds=7)


# --- no second scheduler -----------------------------------------------------------


def test_026_SC_007_the_existing_scheduler_remains_the_only_live_owner(
    api_client,
) -> None:
    """Building the app registers nothing: no worker, no maintenance schedule."""

    import app.main as main_module

    container: Container = api_client.app.state.container
    for key in (VOICE_SCHEDULE_KEY, PRIVACY_SCHEDULE_KEY):
        assert container.job_repository.find_active(key) is None
    assert not hasattr(container, "job_worker")

    text = Path(inspect.getsourcefile(main_module) or "").read_text(encoding="utf-8")
    # PR-64 registers the adapters in ``app.main`` behind the default-OFF gate,
    # so this app (gate off) still owns nothing durable; the gated hand-over is
    # proved in ``test_scheduler_handoff``.
    assert api_client.app.state.durable_worker is None
    for live in ("voice-operation-sweep", "privacy-maintenance-sweep", "auth-delivery"):
        assert live in text


# --- running through the worker ----------------------------------------------------


def test_026_FR_014_voice_job_runs_the_ports_once_in_order_and_reschedules(
    rig: Rig,
) -> None:
    """A successful run settles the occurrence and queues the next at the cadence."""

    adapter = rig.voice()
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    first = rig.active(VOICE_SCHEDULE_KEY)

    assert worker.run_once() is True

    assert rig.journal == list(VOICE_METHODS)
    done = rig.ledger.get(first.job_id)
    assert done is not None and done.status is JobStatus.SUCCEEDED
    nxt = rig.active(VOICE_SCHEDULE_KEY)
    assert nxt.job_id != first.job_id
    assert nxt.run_at == T0 + adapter.cadence


def test_026_FR_015_voice_failure_ends_the_sweep_and_the_retry_runs_it_again(
    rig: Rig,
) -> None:
    """The first failed step skips the rest, as the old sweep did; retry resumes."""

    failure = RuntimeError("secret operation detail")
    ports_raises = {"run_due_brain_dump_provider_runs": failure}
    adapter = rig.voice(raises=ports_raises)
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    job = rig.active(VOICE_SCHEDULE_KEY)

    assert worker.run_once() is True

    assert rig.journal == list(VOICE_METHODS[:2])  # nothing after the failure
    parked = rig.ledger.get(job.job_id)
    assert parked is not None
    assert parked.status is JobStatus.QUEUED and parked.attempts == 1
    assert parked.last_error == "failed.advance_provider_runs"
    assert "secret" not in (parked.last_error or "")
    assert parked.run_at == T0 + timedelta(seconds=1)

    ports_raises.clear()  # the provider is back
    rig.clock.advance(1)
    assert worker.run_once() is True

    # Not one transaction: step 1's effect was never rolled back; the retry
    # simply runs the idempotent sweep again from the start.
    assert rig.journal == [*VOICE_METHODS[:2], *VOICE_METHODS]
    final = rig.ledger.get(job.job_id)
    assert final is not None and final.status is JobStatus.SUCCEEDED


def test_026_FR_015_privacy_failure_never_starves_the_later_steps(rig: Rig) -> None:
    """A failed account purge still runs relay and receipt retention."""

    raises = {"purge_due_accounts": RuntimeError("corrupt flag document")}
    adapter = rig.privacy(raises=raises)
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    job = rig.active(PRIVACY_SCHEDULE_KEY)

    assert worker.run_once() is True

    assert rig.journal == list(PRIVACY_METHODS)
    queued = rig.ledger.get(job.job_id)
    assert queued is not None and queued.status is JobStatus.QUEUED
    assert queued.last_error == "failed.account_purge"

    raises.clear()
    rig.clock.advance(1)
    assert worker.run_once() is True
    done = rig.ledger.get(job.job_id)
    assert done is not None and done.status is JobStatus.SUCCEEDED
    assert rig.journal == [*PRIVACY_METHODS, *PRIVACY_METHODS]


@pytest.mark.parametrize("kind", ["voice", "privacy"])
def test_026_FR_022_a_failing_step_never_logs_its_exception_message(
    rig: Rig, caplog: pytest.LogCaptureFixture, kind: str
) -> None:
    """A port's exception text may hold user content: logs carry type and step only."""

    secret = "secret-user-content-7731"
    failing = "recover_due_provider_leases" if kind == "voice" else "purge_due_accounts"
    raises = {failing: RuntimeError(secret)}
    adapter = (
        rig.voice(raises=raises) if kind == "voice" else rig.privacy(raises=raises)
    )
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)

    with caplog.at_level("DEBUG"):
        worker.run_once()

    assert caplog.records
    for record in caplog.records:
        assert secret not in record.getMessage()
        assert secret not in repr(record.args)
        assert record.exc_info is None and record.exc_text is None
    step = "recover_leases" if kind == "voice" else "account_purge"
    ours = [
        r.getMessage() for r in caplog.records if "maintenance_step" in r.getMessage()
    ]
    assert len(ours) == 1
    assert f"step={step}" in ours[0] and "error=RuntimeError" in ours[0]
    assert f"job={adapter.job_type}" in ours[0]


def test_026_FR_015_every_failed_privacy_step_is_named_in_the_safe_error(
    rig: Rig,
) -> None:
    """Two failures are both reported, by name only."""

    adapter = rig.privacy(
        raises={
            "purge_due_accounts": RuntimeError("a"),
            "purge_expired": RuntimeError("b"),
        }
    )
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    job = rig.active(PRIVACY_SCHEDULE_KEY)

    worker.run_once()

    record = rig.ledger.get(job.job_id)
    assert record is not None
    assert record.last_error == "failed.account_purge.crt_receipt_retention"
    assert rig.journal == list(PRIVACY_METHODS)


def test_026_FR_015_exhausted_retries_keep_the_schedule_and_every_isolated_step(
    rig: Rig,
) -> None:
    """A step that always fails ends the occurrence as failed; the schedule goes on."""

    adapter = rig.privacy(raises={"run_retention_sweep": RuntimeError("down")})
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    first = rig.active(PRIVACY_SCHEDULE_KEY)

    for _attempt in range(5):
        assert worker.run_once() is True
        rig.clock.advance(301)  # past the largest backoff ceiling

    ended = rig.ledger.get(first.job_id)
    assert ended is not None and ended.status is JobStatus.FAILED
    assert ended.last_error == "failed.relay_retention"
    assert rig.active(PRIVACY_SCHEDULE_KEY).job_id != first.job_id
    # The healthy steps ran on every attempt: only the broken one was retried.
    assert rig.journal.count("purge_due_accounts") == 5
    assert rig.journal.count("purge_expired") == 5


def test_026_FR_015_a_failing_voice_job_does_not_starve_account_purge(
    rig: Rig,
) -> None:
    """Voice and privacy are separate jobs: a broken voice pipeline never blocks GDPR."""

    voice = rig.voice(raises={"recover_due_provider_leases": RuntimeError("boom")})
    privacy = rig.privacy()
    worker = rig.worker(voice, privacy)
    worker.ensure_schedules(due_now=True)

    assert worker.run_once() is True
    assert worker.run_once() is True

    assert "purge_due_accounts" in rig.journal
    assert rig.journal.count("recover_due_provider_leases") == 1
    assert rig.journal.count("purge_expired_raw_audio") == 0
    voice_record = rig.active(VOICE_SCHEDULE_KEY)
    assert voice_record.status is JobStatus.QUEUED
    assert voice_record.last_error == "failed.recover_leases"


@pytest.mark.parametrize("failing", VOICE_METHODS)
def test_026_FR_014_voice_failure_behaviour_matches_the_old_sweep(
    rig: Rig, failing: str
) -> None:
    """Old sweep and adapter stop at the same step, whichever step fails."""

    legacy_journal: list[str] = []
    legacy = Ports(legacy_journal, raises={failing: RuntimeError("x")})
    _run_voice_maintenance_sweep(
        SimpleNamespace(voice_brain_dump_service=legacy)  # type: ignore[arg-type]
    )

    adapter = rig.voice(raises={failing: RuntimeError("x")})
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    worker.run_once()

    assert rig.journal == legacy_journal
    assert rig.journal[-1] == failing


@pytest.mark.parametrize("failing", PRIVACY_METHODS)
def test_026_FR_014_privacy_failure_behaviour_matches_the_old_sweep(
    rig: Rig, failing: str
) -> None:
    """Old sweep and adapter both run every privacy step despite one failing."""

    legacy_journal: list[str] = []
    ports = Ports(legacy_journal, raises={failing: RuntimeError("x")})
    _run_privacy_maintenance_sweep(
        SimpleNamespace(  # type: ignore[arg-type]
            account_service=ports,
            agent_relay_service=ports,
            crt_command_repo=ports,
            modern_auth_service=MagicMock(),
            auth_migration=MagicMock(),
            cli_auth_service=MagicMock(),
            crt_command_service=MagicMock(),
            review_service=MagicMock(),
        )
    )

    adapter = rig.privacy(raises={failing: RuntimeError("x")})
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    worker.run_once()

    assert rig.journal == legacy_journal == list(PRIVACY_METHODS)


# --- the execution context and the fence -------------------------------------------


def test_026_FR_014_ports_run_inside_the_bound_job_execution(rig: Rig) -> None:
    """A voice task commit is a job-origin write under this claim's identity."""

    seen: dict[str, object] = {}

    def commit_a_task() -> None:
        execution = current_execution()
        seen["origin"] = current_writer_origin()
        seen["job_type"] = None if execution is None else execution.job_type
        seen["scope"] = None if execution is None else execution.scope
        rig.create_task("Voice made")

    adapter = rig.voice(hooks={"recover_committing_operations": commit_a_task})
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)

    worker.run_once()

    assert seen == {
        "origin": WriterOrigin.JOB,
        "job_type": VOICE_JOB_TYPE,
        "scope": SYSTEM_SCOPE,
    }
    assert rig.task_titles() == ["Voice made"]
    assert current_execution() is None
    assert current_writer_origin() is WriterOrigin.LEGACY


def test_026_SC_007_a_claim_lost_mid_step_cannot_create_a_task(rig: Rig) -> None:
    """Cancelled during a step, the Tasks write is refused and later steps never run."""

    job_id = {"value": ""}

    def lose_claim_then_write() -> None:
        rig.ledger.cancel(job_id["value"])  # an operator cancels mid-flight
        rig.create_task("Must not exist")

    adapter = rig.voice(
        hooks={"run_due_brain_dump_provider_runs": lose_claim_then_write}
    )
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    job_id["value"] = rig.active(VOICE_SCHEDULE_KEY).job_id

    worker.run_once()

    assert rig.task_titles() == []
    assert rig.journal == list(VOICE_METHODS[:2])
    record = rig.ledger.get(job_id["value"])
    assert record is not None and record.status is JobStatus.CANCELLED


def test_026_SC_007_an_expired_lease_cannot_authorize_a_task_write(rig: Rig) -> None:
    """Past its stored expiry the executor is refused, with no heartbeat to save it."""

    def outlive_the_lease() -> None:
        rig.clock.advance(61)
        rig.create_task("Late write")

    adapter = rig.voice(hooks={"recover_due_provider_leases": outlive_the_lease})
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)

    worker.run_once()

    assert rig.task_titles() == []
    assert rig.journal == ["recover_due_provider_leases"]


# --- shutdown ----------------------------------------------------------------------


def test_026_SC_007_shutdown_stops_between_steps_and_keeps_the_occurrence(
    rig: Rig,
) -> None:
    """Shutdown lets the running step finish, starts no further step, and retries."""

    entered, release = threading.Event(), threading.Event()

    def hold_first_step() -> None:
        entered.set()
        release.wait(WAIT)

    adapter = rig.voice(hooks={"recover_due_provider_leases": hold_first_step})
    worker = rig.worker(adapter, idle_poll_seconds=0.01)
    worker.ensure_schedules(due_now=True)
    job = rig.active(VOICE_SCHEDULE_KEY)
    worker.start()
    assert entered.wait(WAIT)

    assert worker.shutdown(timeout=0.1) is False  # the step outlived the grace
    release.set()
    deadline = time.monotonic() + WAIT
    while worker.running and time.monotonic() < deadline:
        time.sleep(0.01)

    assert worker.running is False
    assert rig.journal == ["recover_due_provider_leases"]  # nothing after the stop
    record = rig.ledger.get(job.job_id)
    assert record is not None
    assert record.status is JobStatus.QUEUED  # not succeeded: work was skipped
    assert record.last_error == ABANDONED


def test_026_SC_007_a_cancelled_job_stops_between_privacy_steps(rig: Rig) -> None:
    """A cancellation is honoured at the next step boundary, never mid-step."""

    job_id = {"value": ""}
    adapter = rig.privacy(
        hooks={"purge_due_accounts": lambda: rig.ledger.cancel(job_id["value"])}
    )
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    job_id["value"] = rig.active(PRIVACY_SCHEDULE_KEY).job_id

    worker.run_once()

    assert rig.journal == ["purge_due_accounts"]  # that step finished
    record = rig.ledger.get(job_id["value"])
    assert record is not None and record.status is JobStatus.CANCELLED


def test_026_SC_007_an_abandoned_claim_starts_no_step_at_all(rig: Rig) -> None:
    """If the claim is already lost when the job begins, no port is called."""

    adapter = rig.voice()
    worker = rig.worker(adapter)
    worker.ensure_schedules(due_now=True)
    job = rig.active(VOICE_SCHEDULE_KEY)
    original = rig.ledger.claim_due

    def claim_then_cancel(**kwargs):  # type: ignore[no-untyped-def]
        lease = original(**kwargs)
        assert lease is not None
        rig.ledger.cancel(lease.job_id)
        return lease

    rig.ledger.claim_due = claim_then_cancel  # type: ignore[method-assign]
    worker.run_once()

    assert rig.journal == []
    record = rig.ledger.get(job.job_id)
    assert record is not None and record.status is JobStatus.CANCELLED


# --- the container's real ports ----------------------------------------------------


def _turn_every_rollout_flag_off(container: Container) -> None:
    for flag in ("voice_brain_dump", "weekly_review", "rust_core_sync"):
        container.feature_flag_service.set_mode(
            flag, FlagMode.OFF, operator_id="test_operator"
        )


def test_026_FR_022_due_account_purge_runs_with_every_rollout_flag_off(
    api_client,
) -> None:
    """GDPR purge is always on: the adapter reads no flag and erases the account."""

    container: Container = api_client.app.state.container
    owner = _user_id(api_client)
    _request_deletion(api_client)
    _backdate_deletion(api_client, owner, days=15)
    _turn_every_rollout_flag_off(container)
    adapter = PrivacyMaintenanceAdapter(
        container.account_service,
        container.agent_relay_service,
        container.crt_command_repo,
        container.job_execution,
    )
    worker = _real_worker(container, adapter)
    worker.ensure_schedules(due_now=True)

    assert worker.run_once() is True

    assert container.user_repo.get_by_id(owner) is None
    record = container.job_repository.find_active(PRIVACY_SCHEDULE_KEY)
    assert record is not None and record.status is JobStatus.QUEUED  # next occurrence


def test_026_FR_022_a_job_task_write_for_a_deleting_owner_is_refused_but_purge_runs(
    api_client,
) -> None:
    """Deletion pending revokes job-gated Tasks writes; the purge port needs none."""

    container: Container = api_client.app.state.container
    owner = _user_id(api_client)
    _request_deletion(api_client)
    _backdate_deletion(api_client, owner, days=15)
    journal: list[str] = []

    def write_for_the_deleting_owner() -> None:
        container.task_service.create_task(
            TaskCreateRequest(title="Recreated after deletion"),
            owner_id=owner,
            idempotency_key="deleting-owner-write",
        )

    voice = VoiceMaintenanceAdapter(
        Ports(
            journal,
            hooks={"recover_committing_operations": write_for_the_deleting_owner},
        ),
        container.job_execution,
    )
    privacy = PrivacyMaintenanceAdapter(
        container.account_service,
        container.agent_relay_service,
        container.crt_command_repo,
        container.job_execution,
    )
    voice_worker = _real_worker(container, voice)
    privacy_worker = _real_worker(container, privacy)
    voice_worker.ensure_schedules(due_now=True)
    privacy_worker.ensure_schedules(due_now=True)

    assert voice_worker.run_once() is True  # the write is refused
    voice_record = container.job_repository.find_active(VOICE_SCHEDULE_KEY)
    assert voice_record is not None and voice_record.last_error == (
        "failed.resume_commits"
    )
    assert journal == list(VOICE_METHODS[:3])
    assert container.task_repo.list_for_owner(owner_id=owner) == []

    assert privacy_worker.run_once() is True  # purge through its own ports
    assert container.user_repo.get_by_id(owner) is None


def test_026_FR_022_accounts_inside_the_grace_period_are_left_alone(
    api_client,
) -> None:
    """The adapter changes when purge runs, not who is due."""

    container: Container = api_client.app.state.container
    owner = _user_id(api_client)
    _request_deletion(api_client)
    adapter = PrivacyMaintenanceAdapter(
        container.account_service,
        container.agent_relay_service,
        container.crt_command_repo,
        container.job_execution,
    )
    worker = _real_worker(container, adapter)
    worker.ensure_schedules(due_now=True)

    assert worker.run_once() is True

    assert container.user_repo.get_by_id(owner) is not None


def test_026_FR_022_expired_crt_receipts_are_redacted_through_the_job(
    container: Container,
) -> None:
    """The CRT receipt retention port runs through the adapter; fresh ones stay."""

    now = utcnow()
    for digest, age in (("expired", 31), ("fresh", 29)):
        receipt = _receipt_fixture(
            owner_id="owner-a",
            key_digest=digest,
            committed_at=now - timedelta(days=age),
        )
        container.crt_command_repo.insert_pending(receipt)
        container.crt_command_repo.commit(
            owner_id="owner-a",
            key_digest=digest,
            response_status=201,
            response_json='{"id":"tree"}',
            committed_at=receipt.created_at,
        )
    adapter = PrivacyMaintenanceAdapter(
        container.account_service,
        container.agent_relay_service,
        container.crt_command_repo,
        container.job_execution,
    )
    worker = _real_worker(container, adapter)
    worker.ensure_schedules(due_now=True)

    assert worker.run_once() is True

    expired = container.crt_command_repo.get(owner_id="owner-a", key_digest="expired")
    fresh = container.crt_command_repo.get(owner_id="owner-a", key_digest="fresh")
    assert expired is not None and expired.state == "expired"
    assert expired.response_json is None
    assert fresh is not None and fresh.state == "committed"


def test_026_FR_015_voice_job_keeps_provider_work_paused_for_a_flag_off_owner(
    api_client,
) -> None:
    """The real Voice service still pauses a flag-off owner's provider run."""

    container: Container = api_client.app.state.container
    service = container.voice_brain_dump_service
    operation = _start_operation(
        api_client, key="handoff-start", external_processing_allowed=True
    )
    audio = b"queued provider needs this audio"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "handoff-seal"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 200, sealed.text
    service.voice_enabled_for_owner = lambda _owner_id: False  # type: ignore[method-assign]
    adapter = VoiceMaintenanceAdapter(service, container.job_execution)
    worker = _real_worker(container, adapter)
    worker.ensure_schedules(due_now=True)

    assert worker.run_once() is True

    still = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert still["provider_runs"][-1]["status"] == "pending"
    record = container.job_repository.find_active(VOICE_SCHEDULE_KEY)
    assert record is not None and record.attempts == 0  # a fresh occurrence queued


def test_026_FR_014_container_ports_satisfy_the_adapter_constructors(
    container: Container,
) -> None:
    """The container's services build both adapters with no extra wiring."""

    voice = VoiceMaintenanceAdapter(
        container.voice_brain_dump_service, container.job_execution
    )
    privacy = PrivacyMaintenanceAdapter(
        container.account_service,
        container.agent_relay_service,
        container.crt_command_repo,
        container.job_execution,
    )
    registry = JobRegistry((voice, privacy))
    assert registry.types == (VOICE_JOB_TYPE, PRIVACY_JOB_TYPE)
