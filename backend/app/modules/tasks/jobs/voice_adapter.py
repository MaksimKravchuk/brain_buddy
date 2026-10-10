"""Voice recovery and retention as a durable job (spec 026 PR-23, T023).

Prepares the hand-off of the ``voice-operation-sweep`` responsibility that
``app.main`` runs today (``_run_voice_maintenance_sweep``). The adapter calls the
same five ports on the Voice brain-dump service, in the same order, with the
same failure behaviour: the first failed step ends the sweep and the next
occurrence tries again. It adds only what the ledger provides -- a durable
schedule identity, a lease with a fence, and bounded retry.

This module activates nothing. The existing scheduler stays the only live owner
until PR-64 registers the adapter and removes the old loop in one step.

Voice operations commit confirmed actions to Tasks through the Voice task port.
Those effects keep Voice's own recovery contract (deterministic per-action keys
plus the owner-serialized Tasks idempotency), so a crash between steps, or a
lease that lapses mid-step, is recovered by running the sweep again. The sweep
is never presented as one Tasks transaction. Because the Tasks writer lock
re-checks the bound claim, an executor that lost its lease cannot create a task.
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

VOICE_JOB_TYPE: Final = "voice.maintenance"
VOICE_SCHEDULE_KEY: Final = "schedule:voice.maintenance"
#: ``app.main`` reads the live cadence from this variable (default 60 seconds).
#: Zero disables the old thread; the owner of the handoff then registers nothing.
VOICE_CADENCE_SOURCE: Final = "BRAIN_BUDDY_VOICE_SWEEP_INTERVAL_SECONDS"
VOICE_DEFAULT_CADENCE: Final = timedelta(seconds=60)

_SERVICE: Final = "VoiceBrainDumpService"

#: In the order the old sweep runs them: reclaim, advance, resume, then purge.
VOICE_RESPONSIBILITY: Final = MaintenanceResponsibility(
    job_type=VOICE_JOB_TYPE,
    schedule_key=VOICE_SCHEDULE_KEY,
    cadence_source=VOICE_CADENCE_SOURCE,
    default_cadence=VOICE_DEFAULT_CADENCE,
    steps=(
        MaintenanceStep("recover_leases", f"{_SERVICE}.recover_due_provider_leases"),
        MaintenanceStep(
            "advance_provider_runs", f"{_SERVICE}.run_due_brain_dump_provider_runs"
        ),
        MaintenanceStep("resume_commits", f"{_SERVICE}.recover_committing_operations"),
        MaintenanceStep("purge_raw_audio", f"{_SERVICE}.purge_expired_raw_audio"),
        MaintenanceStep(
            "purge_working_artifacts", f"{_SERVICE}.purge_expired_working_artifacts"
        ),
    ),
    failure_mode="abort",
)


class VoiceMaintenancePort(Protocol):
    """The Voice service surface the old sweep already calls. Nothing new."""

    def recover_due_provider_leases(self) -> int: ...

    def run_due_brain_dump_provider_runs(self) -> int: ...

    def recover_committing_operations(self) -> int: ...

    def purge_expired_raw_audio(self) -> int: ...

    def purge_expired_working_artifacts(self) -> int: ...


class VoiceMaintenanceAdapter:
    """``JobAdapter`` for the voice recovery and retention sweep."""

    job_type: str = VOICE_JOB_TYPE
    schedule_key: str = VOICE_SCHEDULE_KEY

    def __init__(
        self,
        voice: VoiceMaintenancePort,
        gate: JobExecutionGate,
        *,
        cadence: timedelta = VOICE_DEFAULT_CADENCE,
    ) -> None:
        self._voice = voice
        self._gate = gate
        self._cadence = require_positive(cadence)

    @property
    def cadence(self) -> timedelta:
        return self._cadence

    def run(self, context: JobContext) -> JobOutcome:
        voice = self._voice
        ports = {
            "recover_leases": voice.recover_due_provider_leases,
            "advance_provider_runs": voice.run_due_brain_dump_provider_runs,
            "resume_commits": voice.recover_committing_operations,
            "purge_raw_audio": voice.purge_expired_raw_audio,
            "purge_working_artifacts": voice.purge_expired_working_artifacts,
        }
        return run_maintenance_steps(
            context,
            self._gate,
            [(step.name, ports[step.name]) for step in VOICE_RESPONSIBILITY.steps],
            isolate_failures=False,
        )


__all__ = [
    "VOICE_CADENCE_SOURCE",
    "VOICE_DEFAULT_CADENCE",
    "VOICE_JOB_TYPE",
    "VOICE_RESPONSIBILITY",
    "VOICE_SCHEDULE_KEY",
    "VoiceMaintenanceAdapter",
    "VoiceMaintenancePort",
]
