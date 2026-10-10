"""Durable jobs for the agent relay's background responsibilities (spec 026 PR-24).

``AgentObserver`` owns two things on a clock: the periodic observation pass and
the lookups that settle exchanges a restart interrupted. This module runs both
as ledger jobs so a lease, a fence and a bounded retry stand behind them
(026-FR-015) instead of a daemon thread. It adds no scheduler: the adapters only
describe their cadence, and PR-64 registers them and removes the thread.

Nothing about the A2A rules moves here. The adapters call the observer, which
calls the service, so lookup, backoff, suspension and adoption behave exactly as
before. What the job adds is authority and honesty about outcomes:

- **One owner.** Constructing an adapter calls ``delegate_scheduling`` on the
  observer, so its own thread can no longer start; its pass also refuses to run
  beside a live thread. Within a process, claiming a run is shared with the old
  path, so one run is never read twice at once.
- **Fence.** The body runs inside ``JobExecutionGate.executing``. The relay has
  no Task write port (026-FR-021: an AgentRun never edits its Task), so today
  that binding guards nothing it can reach; it makes a future or accidental Task
  write through ``serialized_write`` or Review fail once the lease is lost. The
  observation pass also stops starting reads when ``should_abandon`` turns true.
- **Uncertainty.** A lookup that leaves the exchange interrupted proves nothing
  about whether the agent received the message, so the job is
  ``reconciliation_required``, never a success and never an endless retry.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol

from app.utils.time import utcnow

from .domain import JobOutcome
from .execution import ExecutionRefused, JobExecution, JobExecutionGate
from .repository import JobRepository
from .worker import JobContext

OBSERVE_JOB_TYPE = "agent.observe"
RECOVER_JOB_TYPE = "agent.recover"
_AUTHORITY_LOST = "authority_lost"
_DELIVERY_UNPROVEN = "delivery_unproven"


class ObservationResult(Protocol):
    """What a finished pass reports; ``complete`` is false only if it was cut short.

    A structural type on purpose: the Tasks module may not import the relay's
    A2A client, so it names the one fact it needs rather than the relay's class.
    """

    @property
    def complete(self) -> bool: ...


class AgentObserverPort(Protocol):
    """The slice of ``AgentObserver`` the jobs drive."""

    observation_interval: timedelta

    def delegate_scheduling(self) -> None: ...

    def observe_due(
        self, now: datetime | None = ..., *, keep_going: Callable[[], bool] | None = ...
    ) -> ObservationResult: ...

    def mark_interrupted_exchanges(
        self, *, before_marking: Callable[[str, str], None] | None = ...
    ) -> list[tuple[str, str]]: ...

    def resolve_interrupted_exchange(
        self,
        owner_id: str,
        run_id: str,
        *,
        keep_going: Callable[[], bool] | None = ...,
    ) -> bool: ...


class AgentObservationAdapter:
    """The periodic observation pass as a recurring system job."""

    job_type = OBSERVE_JOB_TYPE
    schedule_key = "agent.observe:schedule"

    def __init__(
        self,
        observer: AgentObserverPort,
        gate: JobExecutionGate,
        *,
        cadence: timedelta | None = None,
    ) -> None:
        observer.delegate_scheduling()
        self._observer = observer
        self._gate = gate
        self.cadence: timedelta | None = cadence or observer.observation_interval

    def run(self, context: JobContext) -> JobOutcome:
        with self._gate.executing(context.lease):
            result = self._observer.observe_due(
                keep_going=lambda: not context.should_abandon()
            )
        # Agents that cannot be reached are recorded by the run's own state
        # machine; only a pass cut short by lost authority is a job failure.
        if result.complete:
            return JobOutcome()
        return JobOutcome(safe_error=_AUTHORITY_LOST)


class AgentRecoveryAdapter:
    """Restart recovery: a boot sweep, then one lookup job per interrupted run.

    The sweep (no payload) marks what a restart interrupted and records a lookup
    job for each open exchange *before* marking it. A lookup job (scope = the
    run's owner, payload = the run id) is one ``ListTasks``. Per-run jobs keep an
    unproven exchange visible on its own, without parking recovery for everyone.
    """

    job_type = RECOVER_JOB_TYPE
    schedule_key = "agent.recover:boot"
    cadence: timedelta | None = None

    def __init__(
        self,
        observer: AgentObserverPort,
        gate: JobExecutionGate,
        ledger: JobRepository,
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._observer = observer
        self._gate = gate
        self._ledger = ledger
        self._now = now
        self._boot_swept = False

    def run(self, context: JobContext) -> JobOutcome:
        with self._gate.executing(context.lease) as execution:
            run_id = context.lease.payload_ref
            if run_id is None:
                return self._sweep(context)
            return self._lookup(context, execution, run_id)

    def _lookup(
        self, context: JobContext, execution: JobExecution, run_id: str
    ) -> JobOutcome:
        owner_id = context.lease.scope

        def authorized() -> bool:
            try:
                self._gate.authorize(execution, owner_id)
            except ExecutionRefused:
                return False
            return not context.should_abandon()

        try:
            self._gate.authorize(execution, owner_id)
        except ExecutionRefused as refused:
            return JobOutcome(safe_error=type(refused).__name__)
        try:
            settled = self._observer.resolve_interrupted_exchange(
                owner_id, run_id, keep_going=authorized
            )
        except Exception:
            # Authority lost during the lookup: its result was discarded before
            # any write. Anything else is a real failure for the worker to record.
            if authorized():
                raise
            return JobOutcome(safe_error=_AUTHORITY_LOST)
        if settled:
            return JobOutcome()
        return JobOutcome(uncertain=True, safe_error=_DELIVERY_UNPROVEN)

    def _sweep(self, context: JobContext) -> JobOutcome:
        if context.should_abandon():
            return JobOutcome(safe_error=_AUTHORITY_LOST)
        if self._boot_swept:
            # Marking already ran at boot, before any request was served. A job
            # claimed later would also catch exchanges the live process opened.
            return JobOutcome()
        self._mark_and_record()
        return JobOutcome()

    def boot_sweep(self) -> None:
        """Mark what a restart interrupted, now, on the caller's thread.

        Recording and marking are the same as the job's sweep, but this must run
        at boot before the app serves a request: ``interrupted_exchanges`` has no
        boot cutoff, so a sweep run later would settle exchanges the live process
        has just opened. Afterwards the ``agent.recover:boot`` occurrence is a
        no-op and only the per-run lookup jobs it recorded do any work.
        """

        self._mark_and_record()
        self._boot_swept = True

    def _mark_and_record(self) -> None:
        def record_lookup(owner_id: str, run_id: str) -> None:
            self._ledger.ensure_scheduled(
                job_type=self.job_type,
                dedup_key=f"{self.job_type}:{run_id}",
                run_at=self._now(),
                scope=owner_id,
                payload_ref=run_id,
            )

        self._observer.mark_interrupted_exchanges(before_marking=record_lookup)


__all__ = [
    "OBSERVE_JOB_TYPE",
    "RECOVER_JOB_TYPE",
    "AgentObservationAdapter",
    "AgentObserverPort",
    "AgentRecoveryAdapter",
    "ObservationResult",
]
