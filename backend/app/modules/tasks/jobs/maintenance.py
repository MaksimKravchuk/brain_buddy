"""Shared shape of the maintenance job adapters (spec 026 PR-23).

The voice and privacy adapters move an *existing* scheduler responsibility onto
the durable ledger without changing what the responsibility does. Each runs a
fixed, ordered list of calls on ports that already exist; this module holds the
two things they share: the inventory vocabulary that names every cadence and
port, and one runner that executes those calls under the claim's execution
context.

The runner is not a transaction. The ports belong to other modules (Voice,
Identity, the external-agent relay, CRT), each with its own recovery contract:
deterministic child keys, durable markers written before the destructive step,
idempotent sweeps. A crash between two calls is therefore recovered by running
the job again, never by pretending the calls were one atomic Tasks write.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from .domain import JobOutcome
from .execution import ExecutionRefused, JobExecutionGate, StaleExecutorError
from .worker import JobContext

logger = logging.getLogger(__name__)

#: Safe error codes. They name a condition only; nothing here carries content.
ABANDONED = "abandoned"
STALE_EXECUTOR = "stale_executor"
FAILED_PREFIX = "failed"


@dataclass(frozen=True, slots=True)
class MaintenanceStep:
    """One call the adapter makes, and the existing port that owns the effect."""

    name: str
    port: str


@dataclass(frozen=True, slots=True)
class MaintenanceResponsibility:
    """The inventory entry of one handed-off scheduler responsibility.

    ``cadence_source`` names where the live cadence is read today, so the
    handoff keeps the operator-visible setting instead of inventing a second
    one. ``left_with_legacy`` lists what the old loop does next to these steps
    that this adapter deliberately does not take.
    """

    job_type: str
    schedule_key: str
    cadence_source: str
    default_cadence: timedelta
    steps: tuple[MaintenanceStep, ...]
    #: ``abort``: the first failed step skips the rest (as the old sweep did).
    #: ``isolate``: every step runs and a failure never starves a later one.
    failure_mode: Literal["abort", "isolate"]
    left_with_legacy: tuple[str, ...] = ()


def require_positive(cadence: timedelta) -> timedelta:
    """A recurring responsibility needs a positive cadence."""

    if cadence <= timedelta(0):
        raise ValueError("A maintenance cadence must be positive.")
    return cadence


def _attempt(name: str, call: Callable[[], int], results: dict[str, int]) -> bool:
    """Run one step; ``True`` when it succeeded. A stale claim re-raises."""

    try:
        results[name] = call()
    except StaleExecutorError:
        raise
    except ExecutionRefused as refused:
        # Scope authority for one owner went away mid-run; log the type only.
        logger.warning(
            "maintenance_step_refused step=%s error=%s", name, type(refused).__name__
        )
        return False
    except Exception:  # noqa: BLE001 - one bad step must not end the job
        logger.exception("Maintenance step %s failed", name)
        return False
    return True


def run_maintenance_steps(
    context: JobContext,
    gate: JobExecutionGate,
    calls: Sequence[tuple[str, Callable[[], int]]],
    *,
    isolate_failures: bool,
) -> JobOutcome:
    """Run ``calls`` in order under the claim's execution context.

    Before each step the claim is re-asserted: a lost lease, a cancellation or a
    shutdown stops the job *between* steps, never inside one, and reports the
    skipped work as a retryable failure so the ledger keeps the occurrence. A
    stale claim stops everything at once. Otherwise a failed step is logged and
    reported by name; whether it also skips the later steps is the
    responsibility's accepted behaviour (``isolate_failures``).
    """

    results: dict[str, int] = {}
    failed: list[str] = []
    with gate.executing(context.lease):
        for name, call in calls:
            if context.should_abandon():
                return JobOutcome(safe_error=ABANDONED)
            try:
                succeeded = _attempt(name, call, results)
            except StaleExecutorError:
                logger.warning("maintenance_stale_executor step=%s", name)
                return JobOutcome(safe_error=STALE_EXECUTOR)
            if succeeded:
                continue
            failed.append(name)
            if not isolate_failures:
                break
    if any(results.values()):
        logger.info("Maintenance job %s: %s", context.lease.job_type, results)
    if failed:
        return JobOutcome(safe_error=".".join((FAILED_PREFIX, *failed)))
    return JobOutcome()


__all__ = [
    "ABANDONED",
    "FAILED_PREFIX",
    "STALE_EXECUTOR",
    "MaintenanceResponsibility",
    "MaintenanceStep",
    "require_positive",
    "run_maintenance_steps",
]
