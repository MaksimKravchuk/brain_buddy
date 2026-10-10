"""In-process runner for the durable job ledger (spec 026 PR-64a).

One loop claims due jobs from :class:`JobRepository`, runs the adapter
registered for each job type while a heartbeat thread extends the lease, settles
the result under the claim's fence, and schedules the next occurrence of a
recurring job. The ledger lease is what makes a second runner -- another thread,
another process, a restart racing an old lease -- harmless: a job has one live
claimant and a result is accepted only under its current fence.

The worker owns nothing by itself. ``app.main`` builds one, registers the
adapters of the responsibilities it has handed over, and records each hand-over
in a :class:`SchedulerHandoff` so a responsibility has exactly one live owner.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from .domain import HEARTBEAT, LEASE, JobLease, JobOutcome
from .repository import JobRepository

logger = logging.getLogger(__name__)

IDLE_POLL_SECONDS = 1.0
#: How often the loop re-asserts that every recurring schedule has an occurrence.
#: This heals a schedule whose last occurrence ended without a successor
#: (cancelled mid-run, or closed as exhausted by a crash loop at claim time).
RECONCILE_SECONDS = 30.0
SHUTDOWN_GRACE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class JobContext:
    """What an adapter receives for one claimed run."""

    lease: JobLease
    _abandon: Callable[[], bool]

    def should_abandon(self) -> bool:
        """True when the effect must stop or not start.

        That is a stale fence, a cancellation, a lease whose expiry has passed, or
        this worker having given up on the job at shutdown.
        """

        return self._abandon()


class JobAdapter(Protocol):
    """A maintenance responsibility. The effect and its idempotency live here."""

    @property
    def job_type(self) -> str: ...

    @property
    def schedule_key(self) -> str:
        """Dedup identity of the recurring schedule (one active job per key)."""
        ...

    @property
    def cadence(self) -> timedelta | None:
        """Delay between occurrences, or ``None`` for a one-shot job."""
        ...

    def run(self, context: JobContext) -> JobOutcome:
        """Run once. Raise or report ``safe_error`` for a retryable failure and
        return ``JobOutcome(uncertain=True)`` when an external effect may or may
        not have happened."""
        ...


class JobRegistry:
    """Job type -> adapter. One adapter per type."""

    def __init__(self, adapters: Iterable[JobAdapter] = ()) -> None:
        self._adapters: dict[str, JobAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: JobAdapter) -> None:
        if adapter.job_type in self._adapters:
            raise ValueError(f"Job type already registered: {adapter.job_type}")
        self._adapters[adapter.job_type] = adapter

    def get(self, job_type: str) -> JobAdapter | None:
        return self._adapters.get(job_type)

    @property
    def types(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def as_mapping(self) -> Mapping[str, JobAdapter]:
        return dict(self._adapters)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobWorker:
    """Claim, run, heartbeat, settle, reschedule."""

    def __init__(
        self,
        ledger: JobRepository,
        registry: JobRegistry,
        *,
        now: Callable[[], datetime] = _utc_now,
        owner_id: str | None = None,
        lease_for: timedelta = LEASE,
        heartbeat_every: timedelta = HEARTBEAT,
        idle_poll_seconds: float = IDLE_POLL_SECONDS,
        reconcile_seconds: float = RECONCILE_SECONDS,
    ) -> None:
        if heartbeat_every >= lease_for:
            raise ValueError("The heartbeat must be shorter than the lease.")
        self.ledger = ledger
        self.registry = registry
        self.owner_id = owner_id or f"worker-{uuid.uuid4().hex[:12]}"
        self._now = now
        self._lease_for = lease_for
        self._heartbeat_every = heartbeat_every
        self._idle_poll = idle_poll_seconds
        self._reconcile_every = reconcile_seconds
        self._stop = threading.Event()
        self._wake_event = threading.Event()
        #: Set when shutdown gave up waiting: heartbeats stop so leases lapse.
        self._abandon_leases = threading.Event()
        #: Makes "is the worker stopping?" and "claim a job" one step, so a claim
        #: can never begin after ``shutdown`` has recorded the stop.
        self._claim_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # --- schedules -------------------------------------------------------------

    def ensure_schedules(self, *, due_now: bool = False) -> int:
        """Make sure each recurring adapter has one pending occurrence.

        Idempotent on the schedule key, so every boot and every runner may call
        it. With ``due_now`` a queued occurrence is pulled forward to now (the
        boot sweep expressed as an occurrence the lease protects). Returns the
        number of occurrences created.
        """

        moment = self._now()
        created = 0
        for adapter in self.registry.as_mapping().values():
            if adapter.cadence is None and not due_now:
                continue
            first = moment if due_now else moment + (adapter.cadence or timedelta())
            if self.ledger.ensure_scheduled(
                job_type=adapter.job_type,
                dedup_key=adapter.schedule_key,
                run_at=first,
                pull_forward=due_now,
            ):
                created += 1
        return created

    def wake(self, job_type: str | None = None) -> None:
        """External push: make a job type due now and rouse the loop.

        Never runs anything inline. A job that is already leased is left alone.
        """

        if job_type is not None:
            adapter = self.registry.get(job_type)
            if adapter is not None:
                self.ledger.ensure_scheduled(
                    job_type=job_type,
                    dedup_key=adapter.schedule_key,
                    run_at=self._now(),
                    pull_forward=True,
                )
        self._wake_event.set()

    # --- one pass --------------------------------------------------------------

    def run_once(self) -> bool:
        """Claim and run at most one due job. ``False`` when nothing is due."""

        types = self.registry.types
        with self._claim_lock:
            if self._stop.is_set():
                return False
            lease = self.ledger.claim_due(
                owner=self.owner_id,
                types=types,
                now=self._now(),
                lease_for=self._lease_for,
            )
        if lease is None:
            return False
        adapter = self.registry.get(lease.job_type)
        if adapter is None:  # pragma: no cover - claim_due filters by our types
            return False
        if self._stop.is_set():
            # Stop was requested while the claim was in flight: do not start an
            # effect during shutdown. Hand the unstarted claim back untouched.
            if not self.ledger.release(
                lease.job_id, fence=lease.fence, now=self._now()
            ):
                logger.warning(  # pragma: no cover - lease lost within microseconds
                    "job_release_fenced type=%s job=%s", lease.job_type, lease.job_id
                )
            return False
        stop_beat = threading.Event()
        beat = threading.Thread(
            target=self._heartbeat,
            args=(lease, stop_beat),
            name=f"job-heartbeat-{lease.job_type}",
            daemon=True,
        )
        beat.start()
        try:
            outcome = self._execute(adapter, lease)
        finally:
            stop_beat.set()
            beat.join(timeout=self._heartbeat_every.total_seconds() + 1.0)
        self._settle(adapter, lease, outcome)
        return True

    def _execute(self, adapter: JobAdapter, lease: JobLease) -> JobOutcome:
        context = JobContext(
            lease,
            lambda: self._lost(lease),
        )
        try:
            return adapter.run(context)
        except Exception as exc:  # noqa: BLE001 - one bad job must not end the loop
            # Only the exception type is recorded: messages can carry payloads.
            return JobOutcome(safe_error=type(exc).__name__)

    def _lost(self, lease: JobLease) -> bool:
        """True once this worker may no longer start or continue the effect.

        Either it gave up at shutdown (heartbeats stopped, so the lease is about
        to lapse for another runner) or the ledger says the claim is stale,
        cancelled or past its stored expiry -- the last is checked against the
        clock here because expiry is only recovered when someone else claims.
        """

        if self._abandon_leases.is_set():
            return True
        return self.ledger.should_abandon(
            lease.job_id, fence=lease.fence, now=self._now()
        )

    def _heartbeat(self, lease: JobLease, stop: threading.Event) -> None:
        interval = self._heartbeat_every.total_seconds()
        while not stop.wait(interval):
            if self._abandon_leases.is_set():
                return
            try:
                alive = self.ledger.heartbeat(
                    lease.job_id,
                    owner=self.owner_id,
                    fence=lease.fence,
                    until=self._now() + self._lease_for,
                )
            except Exception:  # noqa: BLE001 - ledger briefly busy; retry next beat
                logger.exception("job_heartbeat_error type=%s", lease.job_type)
                continue
            if not alive:
                # The effect's own should_abandon() / fenced settle refuses the
                # rest; nothing more to extend.
                logger.warning(
                    "job_lease_lost type=%s job=%s", lease.job_type, lease.job_id
                )
                return

    def _settle(
        self, adapter: JobAdapter, lease: JobLease, outcome: JobOutcome
    ) -> None:
        if outcome.uncertain:
            # No proof either way: parked for a person, never silently retried.
            # The parked job keeps the schedule identity, so no successor exists.
            if not self.ledger.mark_uncertain(
                lease.job_id, fence=lease.fence, safe_error=outcome.safe_error
            ):
                logger.warning(
                    "job_result_fenced type=%s job=%s", lease.job_type, lease.job_id
                )
            return
        if outcome.safe_error is not None:
            self._settle_failure(adapter, lease, outcome.safe_error)
            return
        if not self.ledger.complete(lease.job_id, fence=lease.fence):
            # Stale fence (another claimant owns it now) or cancelled mid-run.
            logger.warning(
                "job_result_fenced type=%s job=%s", lease.job_type, lease.job_id
            )
            return
        self._schedule_next(adapter)

    def _settle_failure(self, adapter: JobAdapter, lease: JobLease, error: str) -> None:
        logger.error(
            "job_failed type=%s job=%s error=%s", lease.job_type, lease.job_id, error
        )
        exhausted = self.ledger.fail(
            lease.job_id, fence=lease.fence, safe_error=error, now=self._now()
        )
        if exhausted:
            # Budget spent: the failure stays visible in the ledger and the
            # schedule carries on with a fresh occurrence.
            self._schedule_next(adapter)

    def _schedule_next(self, adapter: JobAdapter) -> None:
        if adapter.cadence is None:
            return
        self.ledger.ensure_scheduled(
            job_type=adapter.job_type,
            dedup_key=adapter.schedule_key,
            run_at=self._now() + adapter.cadence,
        )

    # --- the thread ------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Schedule recurring jobs and start the loop. ``False`` if running."""

        if self.running:
            return False
        self._stop.clear()
        self._abandon_leases.clear()
        self.ensure_schedules()
        self._thread = threading.Thread(
            target=self._loop, name="durable-job-worker", daemon=True
        )
        self._thread.start()
        return True

    def _loop(self) -> None:
        next_reconcile = time.monotonic() + self._reconcile_every
        while not self._stop.is_set():
            self._wake_event.clear()
            try:
                worked = self.run_once()
                if time.monotonic() >= next_reconcile:
                    next_reconcile = time.monotonic() + self._reconcile_every
                    self.ensure_schedules()
            except Exception:  # noqa: BLE001 - the ledger may be briefly busy
                logger.exception("job_worker_pass_failed")
                worked = False
            if not worked and not self._stop.is_set():
                self._wake_event.wait(self._idle_poll)

    def shutdown(self, timeout: float = SHUTDOWN_GRACE_SECONDS) -> bool:
        """Stop claiming and wait at most ``timeout`` for the running job.

        ``True`` on a clean stop. If the job outlives the grace, its heartbeat is
        stopped so the lease lapses and another runner can reclaim the job; a
        late result from this process is then refused by the fence.
        """

        with self._claim_lock:  # waits out a claim in flight; none starts after
            self._stop.set()
        self._wake_event.set()
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout=timeout)
        if thread.is_alive():
            self._abandon_leases.set()
            return False
        return True


class Responsibility(StrEnum):
    """Every ``app.main`` scheduler responsibility that may move to the ledger.

    Auth delivery, auth metadata cleanup and CRT command reconciliation are not
    listed: they keep their existing owners.
    """

    REVIEW_SWEEP = "review_sweep"
    VOICE_SWEEP = "voice_sweep"
    PRIVACY_RETENTION = "privacy_retention"
    AGENT_OBSERVATION = "agent_observation"
    AGENT_RECOVERY = "agent_recovery"


class SchedulerOwner(StrEnum):
    LEGACY = "legacy"
    DURABLE = "durable"


class DuplicateSchedulerOwnerError(RuntimeError):
    """A responsibility already has an owner; a second one is refused."""


class SchedulerHandoff:
    """Who owns each handed-off responsibility for this process's lifetime.

    Default OFF: with ``enabled`` false the durable worker can own nothing and
    the legacy loops stay the only owners, exactly as before the handoff. Each
    responsibility is assigned once, at boot; a second assignment (to either
    owner) raises, so a legacy loop and the worker can never both be live.
    """

    def __init__(self, *, enabled: bool = False) -> None:
        self.enabled = enabled
        self._owners: dict[Responsibility, SchedulerOwner] = {}

    def assign(self, responsibility: Responsibility, owner: SchedulerOwner) -> None:
        if responsibility in self._owners:
            raise DuplicateSchedulerOwnerError(
                f"{responsibility.value} is already owned by "
                f"{self._owners[responsibility].value}."
            )
        if owner is SchedulerOwner.DURABLE and not self.enabled:
            raise DuplicateSchedulerOwnerError("The durable handoff is not enabled.")
        self._owners[responsibility] = owner

    def assign_remaining_to_legacy(self) -> None:
        for responsibility in Responsibility:
            self._owners.setdefault(responsibility, SchedulerOwner.LEGACY)

    def owner(self, responsibility: Responsibility) -> SchedulerOwner | None:
        return self._owners.get(responsibility)

    def durable(self, responsibility: Responsibility) -> bool:
        return self._owners.get(responsibility) is SchedulerOwner.DURABLE


__all__ = [
    "DuplicateSchedulerOwnerError",
    "JobAdapter",
    "JobContext",
    "JobRegistry",
    "JobWorker",
    "Responsibility",
    "SchedulerHandoff",
    "SchedulerOwner",
]
