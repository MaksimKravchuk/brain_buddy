"""Account purge and receipt retention as a durable job (spec 026 PR-23, T023).

Prepares the hand-off of the privacy half of ``app.main``'s
``privacy-maintenance-sweep`` (``_run_privacy_maintenance_sweep``): hard-delete
accounts past their grace period, expire relayed external-agent content, and
redact expired CRT command receipts. The adapter calls the same three existing
ports in the same order and keeps the old isolation: a failure in one step never
starves a later one.

GDPR erasure is always on. Nothing here reads a feature flag, so a rollout flag
(``rust_core_sync``, voice exposure, weekly review) being OFF can neither pause
the purge nor the retention. Account purge is also a separate job from voice
maintenance, so a broken voice pipeline cannot starve erasure.

This module activates nothing. The existing scheduler stays the only live owner
until PR-64 registers the adapter and removes the old steps in one change.

What this adapter deliberately does not take, because it is not a privacy-retention
port of this slice and its ownership is unchanged:

* authentication metadata, migration backup and CLI grant cleanup, and the
  authentication delivery thread (Identity owns them);
* CRT pending-command reconciliation (CRT owns command recovery; only the
  receipt retention port is invoked here);
* the weekly-review maintenance sweep (PR-22, the Review adapter).

Each step is a call into another module with its own recovery contract (the
purge writes a durable deletion marker before it erases, then re-runs after a
crash; the retention sweeps are idempotent). A crash between steps is therefore
recovered by running the job again. The steps are not, and are not claimed to be,
one Tasks transaction.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final, Protocol

from .domain import JobOutcome
from .execution import JobExecutionGate
from .maintenance import (
    MaintenanceResponsibility,
    MaintenanceStep,
    require_positive,
    run_maintenance_steps,
)
from .worker import JobContext

PRIVACY_JOB_TYPE: Final = "privacy.maintenance"
PRIVACY_SCHEDULE_KEY: Final = "schedule:privacy.maintenance"
#: ``app.main`` reads the live cadence from ``config.agent_relay`` (default 60 s,
#: clamped to 1..3600 seconds by the config model).
PRIVACY_CADENCE_SOURCE: Final = "BRAIN_BUDDY_AGENT_RETENTION_SWEEP_INTERVAL_SECONDS"
PRIVACY_DEFAULT_CADENCE: Final = timedelta(seconds=60)

PRIVACY_RESPONSIBILITY: Final = MaintenanceResponsibility(
    job_type=PRIVACY_JOB_TYPE,
    schedule_key=PRIVACY_SCHEDULE_KEY,
    cadence_source=PRIVACY_CADENCE_SOURCE,
    default_cadence=PRIVACY_DEFAULT_CADENCE,
    steps=(
        MaintenanceStep("account_purge", "AccountService.purge_due_accounts"),
        MaintenanceStep("relay_retention", "AgentRelayService.run_retention_sweep"),
        MaintenanceStep("crt_receipt_retention", "CrtCommandRepository.purge_expired"),
    ),
    failure_mode="isolate",
    left_with_legacy=(
        "ModernAuthService.cleanup_expired_metadata",
        "AuthMigration.cleanup_expired_backup",
        "CliAuthService.cleanup",
        "CrtCommandService.reconcile_pending_commands",
        "ReviewService.run_maintenance_sweep",
    ),
)


class AccountPurgePort(Protocol):
    def purge_due_accounts(self) -> int: ...


class RelayRetentionPort(Protocol):
    def run_retention_sweep(self) -> int: ...


class ReceiptRetentionPort(Protocol):
    def purge_expired(self) -> int: ...


class PrivacyMaintenanceAdapter:
    """``JobAdapter`` for account purge and relay/CRT receipt retention."""

    job_type: str = PRIVACY_JOB_TYPE
    schedule_key: str = PRIVACY_SCHEDULE_KEY

    def __init__(
        self,
        accounts: AccountPurgePort,
        relay: RelayRetentionPort,
        receipts: ReceiptRetentionPort,
        gate: JobExecutionGate,
        *,
        cadence: timedelta = PRIVACY_DEFAULT_CADENCE,
    ) -> None:
        self._accounts = accounts
        self._relay = relay
        self._receipts = receipts
        self._gate = gate
        self._cadence = require_positive(cadence)

    @property
    def cadence(self) -> timedelta:
        return self._cadence

    def run(self, context: JobContext) -> JobOutcome:
        ports = {
            "account_purge": self._accounts.purge_due_accounts,
            "relay_retention": self._relay.run_retention_sweep,
            "crt_receipt_retention": self._receipts.purge_expired,
        }
        return run_maintenance_steps(
            context,
            self._gate,
            [(step.name, ports[step.name]) for step in PRIVACY_RESPONSIBILITY.steps],
            isolate_failures=True,
        )


__all__ = [
    "PRIVACY_CADENCE_SOURCE",
    "PRIVACY_DEFAULT_CADENCE",
    "PRIVACY_JOB_TYPE",
    "PRIVACY_RESPONSIBILITY",
    "PRIVACY_SCHEDULE_KEY",
    "AccountPurgePort",
    "PrivacyMaintenanceAdapter",
    "ReceiptRetentionPort",
    "RelayRetentionPort",
]
