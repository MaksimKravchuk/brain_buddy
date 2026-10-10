"""Durable job adapter for Review maintenance and auto-park (spec 026 PR-22).

Today ``app.main`` runs the weekly-review sweep from its privacy maintenance
thread (spec 020, http section 9). This adapter expresses that same
responsibility as a job the ledger can lease, so a lost worker, a retry or a
restart cannot run it twice or let a stale process write after its lease is gone
(026-FR-015, 026-SC-007).

It adds no effect of its own. The work is ``ReviewService.run_maintenance_sweep``
-- retention for every owner holding review rows, then the exposure part
(sweep-gap floor, clock repair, auto-park) -- reached through the compatible
port, so accepted ADR-0027 semantics are untouched (026-FR-016). Each owner
write already takes the task writer lock and, inside it, re-checks the bound
fence and scope (PR-21); this adapter only binds the claimed lease around the
run. Retention keeps running whatever the ``weekly_review`` flag says and
whether or not the owner is active, because the sweep itself never gates it.

The adapter is not registered anywhere. The existing ``app.main`` scheduler
remains the only live owner until PR-64 registers it and removes that
responsibility there.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from .domain import JobOutcome
from .execution import JobExecutionGate, StaleExecutorError
from .worker import JobContext

if TYPE_CHECKING:
    from app.modules.tasks.review_service import ReviewSweepResult

#: Persisted with every occurrence: the ledger's ``job_type`` and the dedup key
#: of the one recurring schedule. Both are stable identities, never derived from
#: an owner, a payload or a clock.
REVIEW_MAINTENANCE_JOB_TYPE = "tasks.review_maintenance"
REVIEW_MAINTENANCE_SCHEDULE_KEY = "tasks.review_maintenance:sweep"

#: The loop that runs the sweep today ticks every 60 s; the sweep-gap floor
#: (SC-006) depends on it running well inside 24 h.
DEFAULT_CADENCE = timedelta(seconds=60)

#: Safe error code for a run that lost its claim before or during the sweep.
STALE_EXECUTOR = "stale_executor"


class ReviewMaintenancePort(Protocol):
    """The existing Review sweep (``ReviewService.run_maintenance_sweep``)."""

    def run_maintenance_sweep(self) -> ReviewSweepResult: ...


class ReviewJobAdapter:
    """Runs the Review sweep under the claimed lease and fence."""

    job_type = REVIEW_MAINTENANCE_JOB_TYPE
    schedule_key = REVIEW_MAINTENANCE_SCHEDULE_KEY

    def __init__(
        self,
        review: ReviewMaintenancePort,
        gate: JobExecutionGate,
        *,
        cadence: timedelta = DEFAULT_CADENCE,
    ) -> None:
        if cadence <= timedelta():
            raise ValueError("The cadence must be positive.")
        self._review = review
        self._gate = gate
        self._cadence = cadence

    @property
    def cadence(self) -> timedelta:
        return self._cadence

    def run(self, context: JobContext) -> JobOutcome:
        """One sweep. Idempotent, so a retry after a crash repeats no effect:
        a park carries a deterministic key, retention only removes what is
        already past its bound, and the sweep-gap floor only ever raises."""

        if context.should_abandon():
            return JobOutcome(safe_error=STALE_EXECUTOR)
        try:
            with self._gate.executing(context.lease):
                self._review.run_maintenance_sweep()
        except StaleExecutorError:
            # Another claimant owns the job now (or it was cancelled). The
            # sweep stopped at the first refused write; nothing to retry here.
            return JobOutcome(safe_error=STALE_EXECUTOR)
        # Any other failure propagates: the worker records its type only (the
        # message could carry task content) and the ledger retries with backoff.
        return JobOutcome()


__all__ = [
    "DEFAULT_CADENCE",
    "REVIEW_MAINTENANCE_JOB_TYPE",
    "REVIEW_MAINTENANCE_SCHEDULE_KEY",
    "STALE_EXECUTOR",
    "ReviewJobAdapter",
    "ReviewMaintenancePort",
]
