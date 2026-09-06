"""Provider retry/recovery and stale-patch regression tests for Voice Brain Dump.

Covers AI-QA MUST-2 (persisted retryable/terminal provider state with resumable
checkpoint/recovery) and the PA-04/PA-05 stale-patch rebase/rejection rules from
``specs/002-async-voice-workflows/acceptance-tests.md`` (RC-01, RC-02, PA-04, PA-05).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from app.core.config import VoiceAudioLimits
from app.exceptions import (
    ConflictError,
    ProviderRetryableError,
    ProviderTerminalError,
    ValidationFailure,
)
from app.modules.tasks import TaskRepository, TaskService
from app.schemas.tasks import (
    BrainDumpOperationStartRequest,
    BrainDumpSealRequest,
    BrainDumpTranscriptAppendRequest,
    ExpectedRevisionRequest,
)
from app.utils.time import utcnow
from app.workflows.voice_brain_dump.domain import (
    BrainDumpConsent,
    BrainDumpOperationDocument,
    BrainDumpProposalDocument,
    BrainDumpProviderRunDocument,
    BrainDumpTranscriptSegmentDocument,
    ProposalPatch,
    ReconciledProposal,
    apply_proposal_patches,
)
from app.workflows.voice_brain_dump.providers import (
    DeterministicAccurateStt,
    DeterministicTextReconciler,
    ReconcileResult,
    ReconcileTextRequest,
    TextReconcilerPort,
)
from app.workflows.voice_brain_dump.repository import OperationRepository
from app.workflows.voice_brain_dump.service import (
    VoiceBrainDumpService,
    brain_dump_operation_is_committable,
    can_reconcile_brain_dump_preview,
    can_review_brain_dump_provisionally,
)
from app.workflows.voice_brain_dump.task_port import InProcessTaskPort

from .conftest import seed_provisional_proposals

OWNER = "user_recovery_owner"


def test_structural_lineage_requires_meaningful_textual_evidence() -> None:
    assert VoiceBrainDumpService._titles_form_split(
        "Buy oat milk and call the dentist",
        ["Buy oat milk", "Call the dentist"],
    )
    assert not VoiceBrainDumpService._titles_form_split(
        "Buy oat milk",
        ["Untranscribed sealed audio", "Call the dentist"],
    )
    assert not VoiceBrainDumpService._titles_form_split("and the", ["Call dentist"])

    assert VoiceBrainDumpService._titles_form_merge(
        ["Buy oat milk", "Call the dentist"],
        "Buy oat milk and call the dentist",
    )
    assert not VoiceBrainDumpService._titles_form_merge(
        ["Buy oat milk", "Call the dentist"],
        "Untranscribed sealed audio",
    )
    assert not VoiceBrainDumpService._titles_form_merge(["and the"], "Call dentist")
    assert VoiceBrainDumpService._title_content_words("The call to Anna") == {
        "call",
        "anna",
    }
    assert VoiceBrainDumpService._titles_refer_to_same_item("Call", "Call")
    assert not VoiceBrainDumpService._titles_refer_to_same_item("Call", "Email")


def _manifest_hash(audio: bytes) -> str:
    digest = hashlib.sha256(audio).hexdigest()
    payload = [{"chunk_number": 0, "sha256": digest, "size_bytes": len(audio)}]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _service(
    data_dir: Path,
    *,
    fail_plan: dict[str, list[str]] | None = None,
    max_operation_recoveries: int = 2,
    max_cumulative_cost_usd_per_operation: float = 1.00,
    provider_run_lease_seconds: float = 30.0,
    text_reconciler: TextReconcilerPort | None = None,
) -> VoiceBrainDumpService:
    task_service = TaskService(TaskRepository(data_dir))
    repository = OperationRepository(data_dir)
    accurate_stt = DeterministicAccurateStt(
        {"media_recovery": "почини BrainBuddy"},
        fail_plan=fail_plan,
        allow_text_fixture_audio=True,
    )
    return VoiceBrainDumpService(
        repository,
        task_port=InProcessTaskPort(task_service.create_native_inbox_task),
        accurate_stt=accurate_stt,
        text_reconciler=text_reconciler,
        audio_limits=VoiceAudioLimits(
            allowed_mime_types=frozenset({"audio/x-brain-buddy-test-text"})
        ),
        max_operation_recoveries=max_operation_recoveries,
        max_cumulative_cost_usd_per_operation=max_cumulative_cost_usd_per_operation,
        provider_run_lease_seconds=provider_run_lease_seconds,
    )


def _advance_persisted_provider_runs(
    service: VoiceBrainDumpService, operation_id: str
) -> BrainDumpOperationDocument:
    """Drive queued provider work explicitly; request commands never call providers."""

    for _ in range(3):
        if service.run_due_brain_dump_provider_runs() == 0:
            break
    return service.operation_repo.get_brain_dump_operation_for_owner(
        operation_id, owner_id=OWNER
    )


def _seal(
    service: VoiceBrainDumpService, *, audio: bytes = b"audio bytes"
) -> tuple[BrainDumpOperationDocument, TaskService]:
    operation = service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {
                "consent": {
                    "microphone": True,
                    "external_processing_allowed": True,
                    "provider": "openai",
                }
            }
        ),
        owner_id=OWNER,
        idempotency_key="recovery-start",
    )
    service.upload_brain_dump_audio_chunk(
        operation.id,
        0,
        audio,
        owner_id=OWNER,
        content_sha256=hashlib.sha256(audio).hexdigest(),
        content_type="audio/x-brain-buddy-test-text",
    )
    operation = service.get_brain_dump_operation(operation.id, owner_id=OWNER)
    return operation, service


def test_retryable_provider_failure_persists_checkpoint_and_retry_resumes_it(
    data_dir: Path,
) -> None:
    service = _service(data_dir, fail_plan={"media_recovery": ["retryable"]})
    operation, _ = _seal(service)
    # Force a deterministic media_ref so the fake fail plan keys match.
    operation = service.operation_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.operation_repo.save_brain_dump_operation(operation)

    sealed = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(
            expected_revision=operation.revision,
            expected_chunks=1,
            manifest_hash=_manifest_hash(b"audio bytes"),
        ),
        owner_id=OWNER,
        idempotency_key="recovery-seal-1",
    )

    sealed = _advance_persisted_provider_runs(service, sealed.id)
    assert sealed.status == "retryable_error"
    assert sealed.status_history[-1] == "retryable_error"
    last_run = sealed.provider_runs[-1]
    assert last_run.role == "accurate_stt"
    assert last_run.status == "retryable_error"
    assert last_run.checkpoint == "sealed"
    assert last_run.attempt == 1
    assert last_run.recovery_count == 0
    # RC-03: no canonical task exists while the operation is retryable.
    assert sealed.committed_task_ids == []

    retried = service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=sealed.revision),
        owner_id=OWNER,
        idempotency_key="recovery-retry-1",
    )

    retried = _advance_persisted_provider_runs(service, retried.id)
    assert retried.status == "awaiting_confirmation"
    resumed_run = next(
        run for run in reversed(retried.provider_runs) if run.role == "accurate_stt"
    )
    assert resumed_run.status == "succeeded"
    assert resumed_run.attempt == 2
    assert resumed_run.recovery_count == 1
    # Same sealed manifest/checkpoint is reused; no re-upload or re-seal needed.
    assert retried.sealed_manifest_hash == sealed.sealed_manifest_hash
    assert any(proposal.title for proposal in retried.proposals)


def test_operation_recovery_budget_terminally_exhausts_before_a_new_provider_call(
    data_dir: Path,
) -> None:
    service = _service(
        data_dir,
        fail_plan={"media_recovery": ["retryable", "retryable"]},
        max_operation_recoveries=1,
    )
    operation, _ = _seal(service)
    operation = service.operation_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    ).model_copy(update={"media_ref": "media_recovery"})
    service.operation_repo.save_brain_dump_operation(operation)

    failed = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(
            expected_revision=operation.revision,
            expected_chunks=1,
            manifest_hash=_manifest_hash(b"audio bytes"),
        ),
        owner_id=OWNER,
        idempotency_key="budget-seal",
    )
    failed = _advance_persisted_provider_runs(service, failed.id)
    assert failed.status == "retryable_error"

    exhausted = service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=failed.revision),
        owner_id=OWNER,
        idempotency_key="budget-retry",
    )

    exhausted = _advance_persisted_provider_runs(service, exhausted.id)
    assert exhausted.status == "terminal_error"
    assert (
        exhausted.provider_runs[-1].error_code == "OPERATION_RECOVERY_BUDGET_EXHAUSTED"
    )
    assert exhausted.provider_runs[-1].recovery_count == 1


def test_cumulative_cost_budget_blocks_the_next_attempt_without_calling_the_provider(
    data_dir: Path,
) -> None:
    """Item 6: cost admission is cumulative across retries/recovery attempts,
    not just per-call. Once prior persisted ``estimated_cost_usd`` already
    meets the operation-wide cap, the next accurate-STT attempt must be
    refused before the provider is ever invoked — no silent fallback."""

    service = _service(data_dir, max_cumulative_cost_usd_per_operation=1.0)
    operation, _ = _seal(service)
    operation = service.operation_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    now = utcnow()
    costly_prior_run = BrainDumpProviderRunDocument(
        id="provider_run_costly",
        role="accurate_stt",
        status="retryable_error",
        input_hash=hashlib.sha256(b"audio bytes").hexdigest(),
        checkpoint="sealed",
        attempt=1,
        recovery_count=0,
        estimated_cost_usd=1.0,
        created_at=now,
        updated_at=now,
    )
    seeded = operation.model_copy(
        update={
            "status": "retryable_error",
            "media_ref": "media_recovery",
            "sealed_manifest_hash": _manifest_hash(b"audio bytes"),
            "provider_runs": [costly_prior_run],
            "revision": operation.revision + 1,
        }
    )
    service.operation_repo.save_brain_dump_operation(seeded)

    blocked = service.retry_brain_dump_operation(
        seeded.id,
        ExpectedRevisionRequest(expected_revision=seeded.revision),
        owner_id=OWNER,
        idempotency_key="cost-budget-retry",
    )

    blocked = _advance_persisted_provider_runs(service, blocked.id)
    assert blocked.status == "terminal_error"
    assert blocked.provider_runs[-1].error_code == "OPERATION_COST_BUDGET_EXCEEDED"
    assert blocked.committed_task_ids == []
    # The provider port itself was never called: the budget is admitted
    # before any network attempt, not merely reported after a wasted call.
    assert cast(DeterministicAccurateStt, service.accurate_stt).calls == []


def test_due_provider_lease_sweep_honors_a_zero_claim_limit(data_dir: Path) -> None:
    """A periodic sweep with no claim budget must stop before it can inspect
    or retry an in-flight operation, preserving bounded background work."""

    service = _service(data_dir)
    operation, _ = _seal(service)
    service.operation_repo.list_in_flight_provider_run_operations = lambda: [operation]

    assert service.recover_due_provider_leases(limit=0) == 0


def test_seal_claims_a_lease_covering_the_configured_provider_timing(
    data_dir: Path,
) -> None:
    """F5: the persisted lease duration must come from the configured
    provider timeout/retry/backoff/margin -- not a fixed 30 seconds. A
    slow-provider configuration (long timeout, several retries) must claim a
    correspondingly long lease so a still-working call is never recovered
    early; a short configuration claims a short one."""

    slow_lease_seconds = 245.0
    service = _service(data_dir, provider_run_lease_seconds=slow_lease_seconds)

    captured: dict[str, object] = {}
    original_transcribe = service.accurate_stt.transcribe_sealed_audio

    def snapshot_claim_then_transcribe(request):
        persisted = service.operation_repo.get_brain_dump_operation_for_owner(
            request.operation_id, owner_id=OWNER
        )
        claimed_run = persisted.provider_runs[-1]
        captured["lease_duration"] = (
            claimed_run.lease_expires_at - claimed_run.created_at
        ).total_seconds()
        return original_transcribe(request)

    service.accurate_stt.transcribe_sealed_audio = snapshot_claim_then_transcribe  # type: ignore[method-assign]
    operation, _ = _seal(service)
    queued = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(
            expected_revision=operation.revision,
            expected_chunks=1,
            manifest_hash=_manifest_hash(b"audio bytes"),
        ),
        owner_id=OWNER,
        idempotency_key="slow-provider-seal",
    )
    _advance_persisted_provider_runs(service, queued.id)

    assert captured["lease_duration"] == pytest.approx(slow_lease_seconds)


def test_expired_lease_still_recovers_through_the_bounded_retry_path(
    data_dir: Path,
) -> None:
    """Once a configured (non-30s) lease genuinely expires, recovery still
    proceeds through the same owner-serialized, compare-and-set, bounded
    path -- the longer duration only changes *when* recovery is allowed, not
    whether it eventually happens."""

    service = _service(data_dir, provider_run_lease_seconds=245.0)
    operation, _ = _seal(service)
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.operation_repo.save_brain_dump_operation(operation)

    now = utcnow()
    claimed = operation.model_copy(
        update={
            "status": "accurate_transcribing",
            "sealed_manifest_hash": _manifest_hash(b"audio bytes"),
            "provider_runs": [
                BrainDumpProviderRunDocument(
                    id="provider_run_expired",
                    role="accurate_stt",
                    status="running",
                    input_hash=hashlib.sha256(b"audio bytes").hexdigest(),
                    checkpoint="sealed",
                    attempt=1,
                    recovery_count=0,
                    lease_owner="runner_expired",
                    # Already in the past relative to real wall-clock time,
                    # exactly like the process-death fixtures above -- this
                    # is what "genuinely expired" means for a persisted
                    # lease, independent of its configured duration.
                    lease_expires_at=now - timedelta(seconds=1),
                    created_at=now - timedelta(seconds=246),
                    updated_at=now - timedelta(seconds=246),
                )
            ],
            "revision": operation.revision + 1,
        }
    )
    service.operation_repo.save_brain_dump_operation(claimed)

    assert service.recover_due_provider_leases() == 1
    recovered = _advance_persisted_provider_runs(service, operation.id)
    assert recovered.status == "awaiting_confirmation"
    recovered_accurate = next(
        run for run in reversed(recovered.provider_runs) if run.role == "accurate_stt"
    )
    assert recovered_accurate.recovery_count == 1


def test_existing_chunk_upload_repairs_a_missing_atomic_file(data_dir: Path) -> None:
    service = _service(data_dir)
    operation, _ = _seal(service)
    audio = b"audio bytes"
    sha256 = hashlib.sha256(audio).hexdigest()
    chunk_path = service.operation_repo.brain_dump_audio_chunk_path(
        OWNER, operation.id, 0, sha256
    )
    chunk_path.unlink()

    repaired = service.upload_brain_dump_audio_chunk(
        operation.id,
        0,
        audio,
        owner_id=OWNER,
        content_sha256=sha256,
        content_type="audio/x-brain-buddy-test-text",
    )

    assert repaired.id == operation.id
    assert chunk_path.read_bytes() == audio


def test_process_death_during_provider_call_leaves_a_durable_claimed_checkpoint(
    data_dir: Path,
) -> None:
    audio = b"crash-safe audio"
    service = _service(data_dir)
    operation, _ = _seal(service, audio=audio)

    def crash_after_claim(_request: object) -> object:
        raise SystemExit("simulated process death")

    service.accurate_stt.transcribe_sealed_audio = crash_after_claim  # type: ignore[method-assign]

    queued = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(
            expected_revision=operation.revision,
            expected_chunks=1,
            manifest_hash=_manifest_hash(audio),
        ),
        owner_id=OWNER,
        idempotency_key="crash-safe-seal",
    )
    assert queued.provider_runs[-1].status == "pending"
    with pytest.raises(SystemExit, match="simulated process death"):
        service.run_due_brain_dump_provider_runs()

    persisted = OperationRepository(data_dir).get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    assert persisted.status == "accurate_transcribing"
    assert persisted.sealed_manifest_hash == _manifest_hash(audio)
    assert persisted.provider_runs[-1].status == "running"
    assert persisted.provider_runs[-1].checkpoint == "sealed"
    assert persisted.provider_runs[-1].lease_owner
    assert persisted.provider_runs[-1].lease_expires_at

    expired_run = persisted.provider_runs[-1].model_copy(
        update={"lease_expires_at": persisted.provider_runs[-1].created_at}
    )
    persisted = persisted.model_copy(
        update={"provider_runs": [*persisted.provider_runs[:-1], expired_run]}
    )
    service.operation_repo.save_brain_dump_operation(persisted)

    recovered_service = _service(data_dir)
    recovered = recovered_service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=persisted.revision),
        owner_id=OWNER,
        idempotency_key="recover-expired-provider-claim",
    )
    recovered = _advance_persisted_provider_runs(recovered_service, recovered.id)
    assert recovered.status == "awaiting_confirmation"
    recovered_accurate = next(
        run for run in reversed(recovered.provider_runs) if run.role == "accurate_stt"
    )
    assert recovered_accurate.attempt == 2
    assert recovered_accurate.recovery_count == 1


def test_process_death_during_retry_persists_the_new_attempt_claim(
    data_dir: Path,
) -> None:
    audio = b"retry crash-safe audio"
    service = _service(data_dir, fail_plan={"media_recovery": ["retryable"]})
    operation, _ = _seal(service, audio=audio)
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.operation_repo.save_brain_dump_operation(operation)
    retryable = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(
            expected_revision=operation.revision,
            expected_chunks=1,
            manifest_hash=_manifest_hash(audio),
        ),
        owner_id=OWNER,
        idempotency_key="retry-crash-safe-seal",
    )
    retryable = _advance_persisted_provider_runs(service, retryable.id)
    assert retryable.status == "retryable_error"

    def crash_after_retry_claim(_request: object) -> object:
        raise SystemExit("simulated retry process death")

    service.accurate_stt.transcribe_sealed_audio = crash_after_retry_claim  # type: ignore[method-assign]
    queued_retry = service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=retryable.revision),
        owner_id=OWNER,
        idempotency_key="retry-crash-safe-attempt",
    )
    assert queued_retry.provider_runs[-1].status == "pending"
    with pytest.raises(SystemExit, match="simulated retry process death"):
        service.run_due_brain_dump_provider_runs()

    persisted = OperationRepository(data_dir).get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    claimed_run = persisted.provider_runs[-1]
    assert persisted.status == "accurate_transcribing"
    assert claimed_run.status == "running"
    assert claimed_run.attempt == 2
    assert claimed_run.recovery_count == 1
    assert claimed_run.lease_owner
    assert claimed_run.lease_expires_at


def test_recovery_budget_exhausts_into_terminal_error_without_hot_loop(
    data_dir: Path,
) -> None:
    service = _service(
        data_dir, fail_plan={"media_recovery": ["retryable", "retryable", "retryable"]}
    )
    operation, _ = _seal(service)
    operation = service.operation_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.operation_repo.save_brain_dump_operation(operation)

    sealed = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(
            expected_revision=operation.revision,
            expected_chunks=1,
            manifest_hash=_manifest_hash(b"audio bytes"),
        ),
        owner_id=OWNER,
        idempotency_key="recovery-seal-budget",
    )
    sealed = _advance_persisted_provider_runs(service, sealed.id)
    assert sealed.status == "retryable_error"

    first_retry = service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=sealed.revision),
        owner_id=OWNER,
        idempotency_key="recovery-retry-budget-1",
    )
    first_retry = _advance_persisted_provider_runs(service, first_retry.id)
    assert first_retry.status == "retryable_error"
    assert first_retry.provider_runs[-1].attempt == 2

    second_retry = service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=first_retry.revision),
        owner_id=OWNER,
        idempotency_key="recovery-retry-budget-2",
    )
    # Attempt 3 hits the bounded recovery budget: terminal, not another retryable loop.
    second_retry = _advance_persisted_provider_runs(service, second_retry.id)
    assert second_retry.status == "terminal_error"
    assert second_retry.provider_runs[-1].status == "terminal_error"
    assert second_retry.committed_task_ids == []

    with pytest.raises(ValidationFailure, match="Only a retryable"):
        service.retry_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=second_retry.revision),
            owner_id=OWNER,
            idempotency_key="recovery-retry-after-terminal",
        )


def test_terminal_provider_failure_skips_retryable_state(data_dir: Path) -> None:
    service = _service(data_dir, fail_plan={"media_recovery": ["terminal"]})
    operation, _ = _seal(service)
    operation = service.operation_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.operation_repo.save_brain_dump_operation(operation)

    sealed = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(
            expected_revision=operation.revision,
            expected_chunks=1,
            manifest_hash=_manifest_hash(b"audio bytes"),
        ),
        owner_id=OWNER,
        idempotency_key="recovery-seal-terminal",
    )

    sealed = _advance_persisted_provider_runs(service, sealed.id)
    assert sealed.status == "terminal_error"
    assert sealed.provider_runs[-1].status == "terminal_error"
    assert sealed.committed_task_ids == []


def test_retry_requires_retryable_state(data_dir: Path) -> None:
    service = _service(data_dir)
    operation, _ = _seal(service)
    operation = service.operation_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )

    with pytest.raises(ValidationFailure, match="Only a retryable"):
        service.retry_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=operation.revision),
            owner_id=OWNER,
            idempotency_key="retry-not-eligible",
        )


def test_retry_replays_cached_idempotent_response(data_dir: Path) -> None:
    """A repeated retry with the same idempotency key returns the stored result
    without invoking the provider again (no duplicate accurate-STT call)."""

    service = _service(data_dir, fail_plan={"media_recovery": ["retryable"]})
    operation, _ = _seal(service)
    operation = service.operation_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.operation_repo.save_brain_dump_operation(operation)

    sealed = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(
            expected_revision=operation.revision,
            expected_chunks=1,
            manifest_hash=_manifest_hash(b"audio bytes"),
        ),
        owner_id=OWNER,
        idempotency_key="recovery-seal-replay",
    )
    sealed = _advance_persisted_provider_runs(service, sealed.id)
    assert sealed.status == "retryable_error"

    first = service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=sealed.revision),
        owner_id=OWNER,
        idempotency_key="recovery-retry-replay",
    )
    first = _advance_persisted_provider_runs(service, first.id)
    assert first.status == "awaiting_confirmation"
    accurate_stt = cast(DeterministicAccurateStt, service.accurate_stt)
    call_count_after_first = len(accurate_stt.calls)

    replayed = service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=sealed.revision),
        owner_id=OWNER,
        idempotency_key="recovery-retry-replay",
    )

    assert replayed == first
    assert len(accurate_stt.calls) == call_count_after_first


def test_retry_without_sealed_checkpoint_is_rejected(data_dir: Path) -> None:
    """A retryable-flagged operation with no provider-run checkpoint (should
    never happen through normal flow) fails closed rather than resuming
    from missing state."""

    service = _service(data_dir)
    operation, _ = _seal(service)
    operation = service.operation_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    broken = operation.model_copy(
        update={"status": "retryable_error", "sealed_manifest_hash": None}
    )
    service.operation_repo.save_brain_dump_operation(broken)

    with pytest.raises(ValidationFailure, match="no sealed checkpoint"):
        service.retry_brain_dump_operation(
            broken.id,
            ExpectedRevisionRequest(expected_revision=broken.revision),
            owner_id=OWNER,
            idempotency_key="retry-no-checkpoint",
        )


# --- PA-04 / PA-05: stale-base patch rebase and rejection (domain-level) ---


def test_disjoint_stale_patch_rebases_and_both_changes_survive() -> None:
    """PA-04: a stale patch touching a different field still applies cleanly."""

    base = ReconciledProposal(
        id="proposal_disjoint",
        title="Original title",
        source_segment_ids=["seg_1"],
        status="provisional",
    )
    concurrent_title_change = ProposalPatch.update(
        proposal_id="proposal_disjoint",
        title="Newer title",
        producer="reconciler",
    )
    stale_source_only_patch = ProposalPatch.update(
        proposal_id="proposal_disjoint",
        source_segment_ids=["seg_2"],
        producer="fast",
        base_revision=1,
    )

    projection = apply_proposal_patches(
        [base], [concurrent_title_change, stale_source_only_patch]
    )

    assert projection.active[0].title == "Newer title"
    assert projection.active[0].source_segment_ids == ["seg_2"]
    assert projection.active[0].conflicts == []


def test_conflicting_stale_title_patch_is_rejected_not_last_write_wins() -> None:
    """PA-05: a stale-base title change conflicts instead of overwriting."""

    base = ReconciledProposal(
        id="proposal_stale_title",
        title="Original title",
        source_segment_ids=["seg_1"],
        status="provisional",
    )
    concurrent_title_change = ProposalPatch.update(
        proposal_id="proposal_stale_title",
        title="Concurrent newer title",
        producer="reconciler",
    )
    stale_title_patch = ProposalPatch.update(
        proposal_id="proposal_stale_title",
        title="Stale computed title",
        producer="fast",
        base_revision=1,
    )

    projection = apply_proposal_patches(
        [base], [concurrent_title_change, stale_title_patch]
    )

    # No last-write-wins mutation: the newer concurrent title survives.
    assert projection.active[0].title == "Concurrent newer title"
    assert projection.active[0].status == "conflicted"
    assert projection.active[0].conflicts[-1].suggested_value == "Stale computed title"


# --- reconcile_preview: owner-chosen recovery from browser-preview text -------
# ADR-0002, 2026-09-05 amendment: ``terminal_error -> reconciling (preview text)
# -> awaiting_confirmation``. Owner-chosen, one shot per operation, visibly
# ``provisional_only``, under the reconciler and cumulative cost caps, no STT.

PREVIEW_STABLE_TEXTS = ("купить молоко", "позвонить стоматологу")
PREVIEW_INTERIM_TEXT = "позвонить стома"


class _ScriptedReconciler:
    """Reconciler double with a scripted outcome queue and a request log.

    Deliberately not a ``DeterministicTextReconciler``: the service then takes
    the production patch-projection branch, and ``requires_external_processing``
    keeps the consent checks real. A successful call adds one proposal per
    transcript segment it was given, titled from that segment's text.
    """

    provider_id = "openai"
    requires_external_processing = True
    max_cost_usd_per_operation = 0.5
    model: str | None = "scripted-reconciler-model"
    template_version: str | None = "scripted-reconciler-v1"

    def __init__(self, outcomes: list[str] | None = None) -> None:
        self.outcomes = list(outcomes or [])
        self.calls: list[ReconcileTextRequest] = []

    def reconcile(self, request: ReconcileTextRequest) -> ReconcileResult:
        self.calls.append(request)
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if outcome == "retryable":
            raise ProviderRetryableError(
                "RECONCILER_PROVIDER_RETRYABLE", estimated_cost_usd=0.02
            )
        if outcome == "terminal":
            raise ProviderTerminalError(
                "RECONCILER_PROVIDER_REJECTED", estimated_cost_usd=0.02
            )
        return ReconcileResult(
            input_hash=hashlib.sha256(
                "|".join(
                    segment.text for segment in request.transcript_segments
                ).encode("utf-8")
            ).hexdigest(),
            patches=[
                ProposalPatch.add(
                    proposal_id=f"proposal_preview_{index}",
                    title=segment.text[:1].upper() + segment.text[1:],
                    source_segment_ids=[segment.id],
                    producer="reconciler",
                )
                for index, segment in enumerate(request.transcript_segments, start=1)
            ],
            estimated_cost_usd=0.1,
        )


def _preview_service(
    data_dir: Path,
    *,
    reconciler: _ScriptedReconciler,
    fail_plan: dict[str, list[str]] | None = None,
    max_operation_recoveries: int = 2,
    max_cumulative_cost_usd_per_operation: float = 1.0,
) -> tuple[VoiceBrainDumpService, list[int]]:
    """A recovery-test service whose runner wake-ups are counted."""

    service = _service(
        data_dir,
        fail_plan=fail_plan or {"media_recovery": ["terminal"]},
        max_operation_recoveries=max_operation_recoveries,
        max_cumulative_cost_usd_per_operation=max_cumulative_cost_usd_per_operation,
        text_reconciler=reconciler,
    )
    wake_calls: list[int] = []
    service.runner_wake = lambda: wake_calls.append(1)
    return service, wake_calls


def _record_with_preview(service: VoiceBrainDumpService) -> BrainDumpOperationDocument:
    """Start, upload one chunk, and append browser-preview text (stable + interim)."""

    operation = service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {
                "consent": {
                    "microphone": True,
                    "external_processing_allowed": True,
                    "provider": "openai",
                    "language_hints": ["ru"],
                    "vocabulary": ["стоматолог"],
                }
            }
        ),
        owner_id=OWNER,
        idempotency_key="preview-start",
    )
    audio = b"audio bytes"
    service.upload_brain_dump_audio_chunk(
        operation.id,
        0,
        audio,
        owner_id=OWNER,
        content_sha256=hashlib.sha256(audio).hexdigest(),
        content_type="audio/x-brain-buddy-test-text",
    )
    appended = service.append_brain_dump_transcript(
        operation.id,
        BrainDumpTranscriptAppendRequest.model_validate(
            {
                "segments": [
                    {"sequence": 1, "text": PREVIEW_STABLE_TEXTS[0]},
                    {
                        "sequence": 2,
                        "text": PREVIEW_INTERIM_TEXT,
                        "stability": "interim",
                    },
                    {"sequence": 3, "text": PREVIEW_STABLE_TEXTS[1]},
                ]
            }
        ),
        owner_id=OWNER,
        idempotency_key="preview-append",
    )
    # Force a deterministic media_ref so the fake accurate-STT fail plan applies.
    forced = appended.model_copy(update={"media_ref": "media_recovery"})
    service.operation_repo.save_brain_dump_operation(forced)
    return forced


def _seal_and_advance(
    service: VoiceBrainDumpService, operation: BrainDumpOperationDocument, *, key: str
) -> BrainDumpOperationDocument:
    sealed = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(
            expected_revision=operation.revision,
            expected_chunks=1,
            manifest_hash=_manifest_hash(b"audio bytes"),
        ),
        owner_id=OWNER,
        idempotency_key=key,
    )
    return _advance_persisted_provider_runs(service, sealed.id)


def _terminal_stt_failure_with_preview(
    data_dir: Path,
    *,
    reconciler: _ScriptedReconciler,
    max_operation_recoveries: int = 2,
    max_cumulative_cost_usd_per_operation: float = 1.0,
) -> tuple[VoiceBrainDumpService, BrainDumpOperationDocument, list[int]]:
    """Record with browser preview, then fail accurate STT terminally: no proposals."""

    service, wake_calls = _preview_service(
        data_dir,
        reconciler=reconciler,
        max_operation_recoveries=max_operation_recoveries,
        max_cumulative_cost_usd_per_operation=max_cumulative_cost_usd_per_operation,
    )
    operation = _record_with_preview(service)
    failed = _seal_and_advance(service, operation, key="preview-seal")
    assert failed.status == "terminal_error"
    assert failed.provider_runs[-1].role == "accurate_stt"
    assert failed.provider_runs[-1].status == "terminal_error"
    assert failed.proposals == []
    return service, failed, wake_calls


def _stable_preview_ids(operation: BrainDumpOperationDocument) -> list[str]:
    return [
        segment.id
        for segment in operation.segments
        if segment.provider_role == "browser_preview" and segment.stability == "stable"
    ]


def _reconcile_preview(
    service: VoiceBrainDumpService, operation: BrainDumpOperationDocument, *, key: str
) -> BrainDumpOperationDocument:
    return service.reconcile_brain_dump_preview(
        operation.id,
        ExpectedRevisionRequest(expected_revision=operation.revision),
        owner_id=OWNER,
        idempotency_key=key,
    )


def _retry(
    service: VoiceBrainDumpService, operation: BrainDumpOperationDocument, *, key: str
) -> BrainDumpOperationDocument:
    return service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=operation.revision),
        owner_id=OWNER,
        idempotency_key=key,
    )


# -- the pure predicate, clause by clause --------------------------------------


def _matrix_segment(
    segment_id: str,
    sequence: int,
    text: str,
    *,
    now: datetime,
    stability: str = "stable",
    provider_role: str = "browser_preview",
    supersedes: tuple[str, ...] = (),
) -> BrainDumpTranscriptSegmentDocument:
    return BrainDumpTranscriptSegmentDocument.model_validate(
        {
            "id": segment_id,
            "sequence": sequence,
            "text": text,
            "stability": stability,
            "provider_role": provider_role,
            "supersedes_segment_ids": list(supersedes),
            "created_at": now,
        }
    )


def _matrix_run(
    *,
    now: datetime,
    run_id: str = "run_matrix",
    role: str = "accurate_stt",
    status: str = "terminal_error",
    checkpoint: str = "sealed",
    estimated_cost_usd: float = 0.0,
    reserved_cost_usd: float = 0.0,
) -> BrainDumpProviderRunDocument:
    return BrainDumpProviderRunDocument.model_validate(
        {
            "id": run_id,
            "role": role,
            "status": status,
            "input_hash": "0" * 64,
            "checkpoint": checkpoint,
            "attempt": 1,
            "recovery_count": 0,
            "estimated_cost_usd": estimated_cost_usd,
            "reserved_cost_usd": reserved_cost_usd,
            "created_at": now,
            "updated_at": now,
        }
    )


def _matrix_proposal(*, now: datetime, deleted: bool) -> BrainDumpProposalDocument:
    return BrainDumpProposalDocument(
        id="proposal_matrix",
        ordinal=1,
        title="Купить молоко",
        status="provisional",
        deleted=deleted,
        created_at=now,
        updated_at=now,
    )


def _matrix_consent(
    *, now: datetime, external_processing_allowed: bool = True, provider: str = "openai"
) -> BrainDumpConsent:
    return BrainDumpConsent(
        microphone=True,
        external_processing_allowed=external_processing_allowed,
        provider=provider,
        recorded_at=now,
    )


def _eligible_preview_operation(
    now: datetime, **overrides: object
) -> BrainDumpOperationDocument:
    """The minimal state in which ``reconcile_preview`` is offered."""

    return BrainDumpOperationDocument(
        id="brain_dump_preview_matrix",
        owner_id=OWNER,
        status="terminal_error",
        consent=_matrix_consent(now=now),
        segments=[_matrix_segment("segment_stable", 1, "купить молоко", now=now)],
        provider_runs=[_matrix_run(now=now)],
        status_history=["sealing", "accurate_transcribing", "terminal_error"],
        sealed_manifest_hash="1" * 64,
        created_at=now,
        updated_at=now,
    ).model_copy(update=overrides)


_PREVIEW_PREDICATE_CASES: list[
    tuple[str, Callable[[datetime], dict[str, object]], bool]
] = [
    ("eligible baseline", lambda now: {}, True),
    ("not a terminal failure", lambda now: {"status": "retryable_error"}, False),
    ("no provider run at all", lambda now: {"provider_runs": []}, False),
    (
        "last run is still retryable",
        lambda now: {"provider_runs": [_matrix_run(now=now, status="retryable_error")]},
        False,
    ),
    (
        "last run belongs to another role",
        lambda now: {
            "provider_runs": [
                _matrix_run(now=now).model_copy(update={"role": "fast_stt"})
            ]
        },
        False,
    ),
    (
        "terminal reconciler with the preview still standing",
        lambda now: {
            "provider_runs": [
                _matrix_run(
                    now=now,
                    run_id="run_stt",
                    status="succeeded",
                    checkpoint="accurate_transcribed",
                ),
                _matrix_run(
                    now=now,
                    run_id="run_reconciler",
                    role="reconciler",
                    checkpoint="accurate_transcribed",
                ),
            ]
        },
        True,
    ),
    (
        "a surviving proposal belongs to review_provisional",
        lambda now: {"proposals": [_matrix_proposal(now=now, deleted=False)]},
        False,
    ),
    (
        "a deleted proposal does not block",
        lambda now: {"proposals": [_matrix_proposal(now=now, deleted=True)]},
        True,
    ),
    (
        "only interim preview text",
        lambda now: {
            "segments": [
                _matrix_segment(
                    "segment_interim",
                    1,
                    "надо купить моло",
                    now=now,
                    stability="interim",
                )
            ]
        },
        False,
    ),
    (
        "only accurate text",
        lambda now: {
            "segments": [
                _matrix_segment(
                    "segment_accurate",
                    1,
                    "купить молоко",
                    now=now,
                    provider_role="accurate",
                )
            ]
        },
        False,
    ),
    (
        "preview superseded by an accurate utterance",
        lambda now: {
            "segments": [
                _matrix_segment("segment_stable", 1, "купить молоко", now=now),
                _matrix_segment(
                    "segment_accurate",
                    2,
                    "купить молоко",
                    now=now,
                    provider_role="accurate",
                    supersedes=("segment_stable",),
                ),
            ]
        },
        False,
    ),
    (
        "blank preview text",
        lambda now: {"segments": [_matrix_segment("segment_blank", 1, "   ", now=now)]},
        False,
    ),
    (
        "an earlier preview recovery already failed",
        lambda now: {
            "provider_runs": [
                _matrix_run(now=now, run_id="run_stt"),
                _matrix_run(
                    now=now,
                    run_id="run_preview",
                    role="reconciler",
                    checkpoint="preview_transcribed",
                ),
            ]
        },
        False,
    ),
    (
        "an earlier preview recovery anywhere in the history",
        lambda now: {
            "provider_runs": [
                _matrix_run(
                    now=now,
                    run_id="run_preview",
                    role="reconciler",
                    status="succeeded",
                    checkpoint="preview_reconciled",
                ),
                _matrix_run(now=now, run_id="run_stt"),
            ]
        },
        False,
    ),
    (
        "external processing not allowed",
        lambda now: {
            "consent": _matrix_consent(now=now, external_processing_allowed=False)
        },
        False,
    ),
    ("consent withdrawn", lambda now: {"consent_withdrawn_at": now}, False),
    (
        "consent names another provider",
        lambda now: {"consent": _matrix_consent(now=now, provider="deepgram")},
        False,
    ),
    (
        "cost cap leaves no room for the reconciler",
        lambda now: {"provider_runs": [_matrix_run(now=now, estimated_cost_usd=0.6)]},
        False,
    ),
    (
        "cost cap reached exactly is still admitted",
        lambda now: {"provider_runs": [_matrix_run(now=now, estimated_cost_usd=0.5)]},
        True,
    ),
    (
        "an unresolved reservation counts against the cap",
        lambda now: {
            "provider_runs": [
                _matrix_run(
                    now=now,
                    run_id="run_stuck",
                    role="reconciler",
                    status="running",
                    checkpoint="accurate_transcribed",
                    estimated_cost_usd=0.1,
                    reserved_cost_usd=0.5,
                ),
                _matrix_run(now=now),
            ]
        },
        False,
    ),
]


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [(build, expected) for _case, build, expected in _PREVIEW_PREDICATE_CASES],
    ids=[case for case, _build, _expected in _PREVIEW_PREDICATE_CASES],
)
def test_015_FR_009_preview_recovery_predicate_requires_every_clause(
    overrides: Callable[[datetime], dict[str, object]], expected: bool
) -> None:
    """015-FR-009: reconcile_preview is offered only while every clause holds."""

    operation = _eligible_preview_operation(utcnow(), **overrides(utcnow()))

    assert (
        can_reconcile_brain_dump_preview(
            operation,
            text_reconciler=_ScriptedReconciler(),
            max_cumulative_cost_usd=1.0,
        )
        is expected
    )


def test_preview_recovery_predicate_reads_the_service_configuration(
    data_dir: Path,
) -> None:
    """The service wrapper answers from its own reconciler ceiling and cost cap."""

    now = utcnow()
    spent = _eligible_preview_operation(
        now, provider_runs=[_matrix_run(now=now, estimated_cost_usd=0.6)]
    )
    generous = _service(
        data_dir,
        text_reconciler=_ScriptedReconciler(),
        max_cumulative_cost_usd_per_operation=1.5,
    )
    strict = _service(
        data_dir,
        text_reconciler=_ScriptedReconciler(),
        max_cumulative_cost_usd_per_operation=1.0,
    )

    assert generous.can_reconcile_preview(spent) is True
    assert strict.can_reconcile_preview(spent) is False


def test_preview_recovery_binds_consent_to_the_provider_only_when_it_is_external() -> (
    None
):
    """A provider mismatch matters only for a reconciler that ships text off-device."""

    now = utcnow()
    operation = _eligible_preview_operation(
        now, consent=_matrix_consent(now=now, provider="deepgram")
    )

    assert (
        can_reconcile_brain_dump_preview(
            operation,
            text_reconciler=DeterministicTextReconciler(),
            max_cumulative_cost_usd=1.0,
        )
        is True
    )
    assert (
        can_reconcile_brain_dump_preview(
            operation,
            text_reconciler=_ScriptedReconciler(),
            max_cumulative_cost_usd=1.0,
        )
        is False
    )


def test_preview_recovery_and_provisional_review_are_mutually_exclusive(
    data_dir: Path,
) -> None:
    """Surviving proposals route to review_provisional; none route to reconcile_preview."""

    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=_ScriptedReconciler()
    )
    assert can_review_brain_dump_provisionally(failed) is False
    assert service.can_reconcile_preview(failed) is True

    seeded = seed_provisional_proposals(
        service.operation_repo, failed, ["Купить молоко"], id_prefix="proposal_legacy"
    )
    assert can_review_brain_dump_provisionally(seeded) is True
    assert service.can_reconcile_preview(seeded) is False
    with pytest.raises(
        ValidationFailure, match="BRAIN_DUMP_PREVIEW_RECOVERY_UNAVAILABLE"
    ):
        _reconcile_preview(service, seeded, key="preview-while-reviewable")

    discarded = seeded.model_copy(
        update={
            "proposals": [
                proposal.model_copy(update={"deleted": True})
                for proposal in seeded.proposals
            ]
        }
    )
    assert can_review_brain_dump_provisionally(discarded) is False
    assert service.can_reconcile_preview(discarded) is True


# -- the command ---------------------------------------------------------------


def test_015_FR_009_reconcile_preview_queues_one_provisional_reconciler_run(
    data_dir: Path,
) -> None:
    """015-FR-009: the command persists a pending preview run, wakes the runner, replays idempotently."""

    reconciler = _ScriptedReconciler()
    service, failed, wake_calls = _terminal_stt_failure_with_preview(
        data_dir, reconciler=reconciler
    )
    wakes_before = len(wake_calls)

    queued = _reconcile_preview(service, failed, key="preview-reconcile")

    assert queued.status == "reconciling"
    assert queued.status_history == [*failed.status_history, "reconciling"]
    assert queued.revision == failed.revision + 1
    assert queued.provider_runs[:-1] == failed.provider_runs
    run = queued.provider_runs[-1]
    assert run.role == "reconciler"
    assert run.status == "pending"
    assert run.checkpoint == "preview_transcribed"
    assert run.attempt == 1
    assert run.recovery_count == 0
    assert run.reserved_cost_usd == 0.5
    assert run.estimated_cost_usd == 0.0
    assert (
        run.input_hash
        == hashlib.sha256("\n".join(PREVIEW_STABLE_TEXTS).encode("utf-8")).hexdigest()
    )
    assert len(wake_calls) == wakes_before + 1
    # The request handler never calls the provider; the runner does.
    assert reconciler.calls == []
    assert service.can_reconcile_preview(queued) is False

    replayed = _reconcile_preview(service, failed, key="preview-reconcile")
    assert replayed == queued
    assert len(wake_calls) == wakes_before + 1
    persisted = service.get_brain_dump_operation(failed.id, owner_id=OWNER)
    assert persisted.revision == queued.revision
    assert len(persisted.provider_runs) == len(failed.provider_runs) + 1

    with pytest.raises(ConflictError, match="newer changes"):
        _reconcile_preview(service, failed, key="preview-reconcile-stale")


def test_reconcile_preview_is_refused_outside_the_eligible_state(
    data_dir: Path,
) -> None:
    """A recording that never failed terminally cannot be recovered from preview."""

    service, _ = _preview_service(data_dir, reconciler=_ScriptedReconciler())
    recording = _record_with_preview(service)

    with pytest.raises(
        ValidationFailure, match="BRAIN_DUMP_PREVIEW_RECOVERY_UNAVAILABLE"
    ):
        _reconcile_preview(service, recording, key="preview-while-recording")
    assert (
        service.get_brain_dump_operation(recording.id, owner_id=OWNER).revision
        == recording.revision
    )


def test_reconcile_preview_is_refused_after_consent_withdrawal(data_dir: Path) -> None:
    """Withdrawn consent removes the preview recovery and refuses the command."""

    reconciler = _ScriptedReconciler()
    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=reconciler
    )
    assert service.can_reconcile_preview(failed) is True

    withdrawn = service.withdraw_brain_dump_consent(
        failed.id,
        ExpectedRevisionRequest(expected_revision=failed.revision),
        owner_id=OWNER,
        idempotency_key="preview-withdraw",
    )

    assert withdrawn.status == "terminal_error"
    assert withdrawn.consent.external_processing_allowed is False
    assert withdrawn.consent_withdrawn_at is not None
    assert withdrawn.segments, "the preview text is only scheduled for deletion"
    assert service.can_reconcile_preview(withdrawn) is False
    with pytest.raises(ValidationFailure, match="RECONCILER_CONSENT_REQUIRED"):
        _reconcile_preview(service, withdrawn, key="preview-after-withdrawal")
    assert service.run_due_brain_dump_provider_runs() == 0
    assert reconciler.calls == []


def test_reconcile_preview_is_refused_when_consent_names_another_reconciler(
    data_dir: Path,
) -> None:
    """A reconciler whose provider consent never named fails closed with its own code."""

    reconciler = _ScriptedReconciler()
    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=reconciler
    )
    reconciler.provider_id = "anthropic"

    assert service.can_reconcile_preview(failed) is False
    with pytest.raises(ValidationFailure, match="RECONCILER_CONSENT_PROVIDER_MISMATCH"):
        _reconcile_preview(service, failed, key="preview-provider-mismatch")

    reconciler.requires_external_processing = False
    assert service.can_reconcile_preview(failed) is True


def test_reconcile_preview_is_refused_when_the_cost_cap_has_no_room(
    data_dir: Path,
) -> None:
    """The reconciler's worst-case reservation must fit under the cumulative cap."""

    reconciler = _ScriptedReconciler()
    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=reconciler
    )
    costly = failed.model_copy(
        update={
            "provider_runs": [
                *failed.provider_runs[:-1],
                failed.provider_runs[-1].model_copy(update={"estimated_cost_usd": 0.6}),
            ]
        }
    )
    service.operation_repo.save_brain_dump_operation(costly)

    assert service.can_reconcile_preview(costly) is False
    with pytest.raises(ValidationFailure, match="OPERATION_COST_BUDGET_EXCEEDED"):
        _reconcile_preview(service, costly, key="preview-over-budget")
    assert service.run_due_brain_dump_provider_runs() == 0
    assert reconciler.calls == []

    at_cap = costly.model_copy(
        update={
            "provider_runs": [
                *costly.provider_runs[:-1],
                costly.provider_runs[-1].model_copy(update={"estimated_cost_usd": 0.5}),
            ]
        }
    )
    assert service.can_reconcile_preview(at_cap) is True


# -- the runner ---------------------------------------------------------------


def test_015_FR_009_runner_reconciles_exactly_the_stable_unsuperseded_preview_text(
    data_dir: Path,
) -> None:
    """015-FR-009: the reconciler receives only stable preview text and the result is provisional_only."""

    reconciler = _ScriptedReconciler()
    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=reconciler
    )
    stt = cast(DeterministicAccurateStt, service.accurate_stt)
    stt_calls_before = len(stt.calls)
    stable_ids = _stable_preview_ids(failed)
    assert len(stable_ids) == 2
    assert len(failed.segments) == 3

    queued = _reconcile_preview(service, failed, key="preview-run")
    recovered = _advance_persisted_provider_runs(service, queued.id)

    assert len(reconciler.calls) == 1
    request = reconciler.calls[0]
    assert request.operation_id == failed.id
    assert [hypothesis.id for hypothesis in request.transcript_segments] == stable_ids
    assert [hypothesis.text for hypothesis in request.transcript_segments] == list(
        PREVIEW_STABLE_TEXTS
    )
    assert {hypothesis.provider_role for hypothesis in request.transcript_segments} == {
        "browser_preview"
    }
    assert {hypothesis.stability for hypothesis in request.transcript_segments} == {
        "stable"
    }
    assert request.active_proposals == []
    assert request.language_hints == ["ru"]
    assert request.vocabulary == ["стоматолог"]
    # No audio was read and no STT call was made.
    assert len(stt.calls) == stt_calls_before

    assert recovered.status == "awaiting_confirmation"
    assert recovered.status_history[-1] == "awaiting_confirmation"
    assert recovered.reconciliation_quality == "provisional_only"
    assert recovered.manual_review is True
    assert recovered.segments == failed.segments
    run = recovered.provider_runs[-1]
    assert run.id == queued.provider_runs[-1].id
    assert run.role == "reconciler"
    assert run.status == "succeeded"
    assert run.checkpoint == "preview_reconciled"
    assert run.attempt == 1
    assert run.recovery_count == 0
    assert run.provider == "openai"
    assert run.model == "scripted-reconciler-model"
    assert run.template_version == "scripted-reconciler-v1"
    assert run.estimated_cost_usd == 0.1
    assert run.consumed_cost_usd == 0.1
    assert run.reserved_cost_usd == 0.0
    assert run.lease_owner is None
    assert [proposal.title for proposal in recovered.proposals] == [
        "Купить молоко",
        "Позвонить стоматологу",
    ]
    assert [proposal.source_segment_ids for proposal in recovered.proposals] == [
        [stable_ids[0]],
        [stable_ids[1]],
    ]
    assert {proposal.status for proposal in recovered.proposals} == {"reconciled"}
    assert recovered.raw_audio_expires_at == run.updated_at + timedelta(days=1)
    assert brain_dump_operation_is_committable(recovered) is True
    assert service.can_reconcile_preview(recovered) is False
    assert can_review_brain_dump_provisionally(recovered) is False


def test_preview_reconciled_run_never_satisfies_the_canonical_accurate_gate(
    data_dir: Path,
) -> None:
    """Only manual_review makes a preview recovery committable; it is never accurate."""

    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=_ScriptedReconciler()
    )
    recovered = _advance_persisted_provider_runs(
        service, _reconcile_preview(service, failed, key="preview-gate").id
    )
    assert recovered.status == "awaiting_confirmation"
    assert not any(run.checkpoint == "reconciled" for run in recovered.provider_runs)
    assert VoiceBrainDumpService._has_frozen_reconciled_batch(recovered) is False

    # Even a hostile relabelling of the operation cannot open the canonical
    # path: no run ever froze at ``reconciled``.
    relabelled = recovered.model_copy(
        update={"manual_review": False, "reconciliation_quality": "accurate"}
    )
    assert brain_dump_operation_is_committable(relabelled) is False
    service.operation_repo.save_brain_dump_operation(relabelled)
    with pytest.raises(ValidationFailure, match="BRAIN_DUMP_NOT_RECONCILED"):
        service.commit_brain_dump_operation(
            relabelled.id,
            ExpectedRevisionRequest(expected_revision=relabelled.revision),
            owner_id=OWNER,
            idempotency_key="preview-hostile-commit",
        )


def test_015_FR_009_preview_recovery_commit_creates_inbox_tasks_with_provisional_receipts(
    data_dir: Path,
) -> None:
    """015-FR-009: committing a preview recovery creates inbox tasks whose receipts say provisional_only."""

    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=_ScriptedReconciler()
    )
    recovered = _advance_persisted_provider_runs(
        service, _reconcile_preview(service, failed, key="preview-commit-run").id
    )
    preview_run = recovered.provider_runs[-1]
    stable_ids = _stable_preview_ids(recovered)

    committed = service.commit_brain_dump_operation(
        recovered.id,
        ExpectedRevisionRequest(expected_revision=recovered.revision),
        owner_id=OWNER,
        idempotency_key="preview-commit",
    )

    assert committed.status == "completed"
    assert len(committed.committed_task_ids) == 2
    assert [receipt.proposal_id for receipt in committed.action_receipts] == [
        "proposal_preview_1",
        "proposal_preview_2",
    ]
    for receipt, segment_id in zip(committed.action_receipts, stable_ids, strict=True):
        assert receipt.reconciliation_quality == "provisional_only"
        assert receipt.reconciliation_run_id == preview_run.id
        assert receipt.reconciliation_provider == "openai"
        assert receipt.reconciliation_model == "scripted-reconciler-model"
        assert receipt.reconciliation_template_version == "scripted-reconciler-v1"
        assert receipt.source_segment_ids == [segment_id]
    task_service = TaskService(TaskRepository(data_dir))
    tasks = [
        task_service.get_task(task_id, owner_id=OWNER)
        for task_id in committed.committed_task_ids
    ]
    assert [task.title for task in tasks] == ["Купить молоко", "Позвонить стоматологу"]
    assert {task.state for task in tasks} == {"inbox"}


def test_preview_recovery_retryable_failure_retries_over_preview_text_not_audio(
    data_dir: Path,
) -> None:
    """A retryable preview failure re-queues a preview run, even once raw audio is gone."""

    reconciler = _ScriptedReconciler(outcomes=["retryable", "ok"])
    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=reconciler
    )
    stt = cast(DeterministicAccurateStt, service.accurate_stt)
    stt_calls_before = len(stt.calls)

    queued = _reconcile_preview(service, failed, key="preview-retryable")
    retryable = _advance_persisted_provider_runs(service, queued.id)

    assert retryable.status == "retryable_error"
    assert retryable.status_history[-2:] == ["reconciling", "retryable_error"]
    failed_run = retryable.provider_runs[-1]
    assert failed_run.role == "reconciler"
    assert failed_run.status == "retryable_error"
    assert failed_run.checkpoint == "preview_transcribed"
    assert failed_run.attempt == 1
    assert failed_run.recovery_count == 0
    assert failed_run.error_code == "RECONCILER_PROVIDER_RETRYABLE"
    assert failed_run.estimated_cost_usd == 0.02
    assert failed_run.reserved_cost_usd == 0.0
    assert service.can_reconcile_preview(retryable) is False

    # The owner deletes raw audio in between: the preview retry needs none of it.
    audio_deleted = service.delete_brain_dump_raw_audio(
        retryable.id,
        ExpectedRevisionRequest(expected_revision=retryable.revision),
        owner_id=OWNER,
        idempotency_key="preview-delete-audio",
    )
    assert audio_deleted.sealed_manifest_hash is None
    assert audio_deleted.audio_chunks == []

    retried = _retry(service, audio_deleted, key="preview-retry")

    assert retried.status == "reconciling"
    retry_run = retried.provider_runs[-1]
    assert retry_run.role == "reconciler"
    assert retry_run.status == "pending"
    assert retry_run.checkpoint == "preview_transcribed"
    assert retry_run.attempt == 2
    assert retry_run.recovery_count == 1
    assert retry_run.input_hash == failed_run.input_hash
    assert retry_run.reserved_cost_usd == 0.5

    recovered = _advance_persisted_provider_runs(service, retried.id)

    assert recovered.status == "awaiting_confirmation"
    assert recovered.reconciliation_quality == "provisional_only"
    assert recovered.manual_review is True
    assert recovered.provider_runs[-1].checkpoint == "preview_reconciled"
    assert recovered.provider_runs[-1].attempt == 2
    assert recovered.provider_runs[-1].recovery_count == 1
    assert len(reconciler.calls) == 2
    assert [
        [hypothesis.id for hypothesis in call.transcript_segments]
        for call in reconciler.calls
    ] == [_stable_preview_ids(failed)] * 2
    assert len(stt.calls) == stt_calls_before


def test_preview_recovery_expired_lease_recovers_over_preview_text(
    data_dir: Path,
) -> None:
    """A preview run whose lease expired is reclaimed through retry as a preview run."""

    reconciler = _ScriptedReconciler()
    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=reconciler
    )
    queued = _reconcile_preview(service, failed, key="preview-lease")
    now = utcnow()
    stuck = queued.model_copy(
        update={
            "provider_runs": [
                *queued.provider_runs[:-1],
                queued.provider_runs[-1].model_copy(
                    update={
                        "status": "running",
                        "lease_owner": "runner_dead",
                        "lease_expires_at": now - timedelta(seconds=1),
                    }
                ),
            ]
        }
    )
    service.operation_repo.save_brain_dump_operation(stuck)

    assert service.recover_due_provider_leases() == 1
    reclaimed = service.get_brain_dump_operation(failed.id, owner_id=OWNER)
    assert reclaimed.status == "reconciling"
    assert reclaimed.provider_runs[-1].checkpoint == "preview_transcribed"
    assert reclaimed.provider_runs[-1].status == "pending"
    assert reclaimed.provider_runs[-1].recovery_count == 1

    recovered = _advance_persisted_provider_runs(service, failed.id)
    assert recovered.status == "awaiting_confirmation"
    assert recovered.provider_runs[-1].checkpoint == "preview_reconciled"
    assert len(reconciler.calls) == 1


def test_preview_recovery_retry_budget_exhausts_terminally_and_is_not_offered_again(
    data_dir: Path,
) -> None:
    """The preview run has its own bounded retry budget; exhausting it is terminal."""

    reconciler = _ScriptedReconciler(outcomes=["retryable", "retryable", "retryable"])
    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=reconciler, max_operation_recoveries=2
    )

    first = _advance_persisted_provider_runs(
        service, _reconcile_preview(service, failed, key="preview-budget").id
    )
    assert first.status == "retryable_error"
    second = _advance_persisted_provider_runs(
        service, _retry(service, first, key="preview-budget-retry-1").id
    )
    assert second.status == "retryable_error"
    assert second.provider_runs[-1].attempt == 2
    assert second.provider_runs[-1].recovery_count == 1

    exhausted = _retry(service, second, key="preview-budget-retry-2")

    assert exhausted.status == "terminal_error"
    run = exhausted.provider_runs[-1]
    assert run.role == "reconciler"
    assert run.status == "terminal_error"
    assert run.checkpoint == "preview_transcribed"
    assert run.attempt == 3
    assert run.recovery_count == 2
    assert run.error_code == "OPERATION_RECOVERY_BUDGET_EXHAUSTED"
    assert len(reconciler.calls) == 2
    assert service.can_reconcile_preview(exhausted) is False
    assert can_review_brain_dump_provisionally(exhausted) is False
    with pytest.raises(
        ValidationFailure, match="BRAIN_DUMP_PREVIEW_RECOVERY_UNAVAILABLE"
    ):
        _reconcile_preview(service, exhausted, key="preview-second-shot")
    with pytest.raises(ValidationFailure, match="Only a retryable"):
        _retry(service, exhausted, key="preview-retry-after-terminal")


def test_preview_recovery_terminal_failure_leaves_only_cancel(data_dir: Path) -> None:
    """A terminal preview failure is a dead end: no second shot, cancel still works."""

    reconciler = _ScriptedReconciler(outcomes=["terminal"])
    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=reconciler
    )

    ended = _advance_persisted_provider_runs(
        service, _reconcile_preview(service, failed, key="preview-terminal").id
    )

    assert ended.status == "terminal_error"
    assert ended.status_history[-2:] == ["reconciling", "terminal_error"]
    run = ended.provider_runs[-1]
    assert run.role == "reconciler"
    assert run.status == "terminal_error"
    assert run.checkpoint == "preview_transcribed"
    assert run.error_code == "RECONCILER_PROVIDER_REJECTED"
    assert ended.proposals == []
    assert ended.reconciliation_quality == "none"
    assert service.can_reconcile_preview(ended) is False
    assert can_review_brain_dump_provisionally(ended) is False
    assert brain_dump_operation_is_committable(ended) is False
    with pytest.raises(
        ValidationFailure, match="BRAIN_DUMP_PREVIEW_RECOVERY_UNAVAILABLE"
    ):
        _reconcile_preview(service, ended, key="preview-after-terminal")

    cancelled = service.transition_brain_dump_operation(
        ended.id,
        ExpectedRevisionRequest(expected_revision=ended.revision),
        owner_id=OWNER,
        idempotency_key="preview-cancel",
        action="cancel",
    )
    assert cancelled.status == "cancelled"
    assert len(reconciler.calls) == 1


def test_preview_recovery_is_offered_after_the_accurate_lane_exhausted_its_budget(
    data_dir: Path,
) -> None:
    """The preview recovery is a separate budget: it opens after STT recoveries ran out."""

    reconciler = _ScriptedReconciler()
    service, _ = _preview_service(
        data_dir,
        reconciler=reconciler,
        fail_plan={"media_recovery": ["retryable", "retryable", "retryable"]},
        max_operation_recoveries=2,
    )
    operation = _record_with_preview(service)
    sealed = _seal_and_advance(service, operation, key="preview-stt-budget-seal")
    assert sealed.status == "retryable_error"
    retried = _advance_persisted_provider_runs(
        service, _retry(service, sealed, key="preview-stt-budget-retry-1").id
    )
    assert retried.status == "retryable_error"
    exhausted = _retry(service, retried, key="preview-stt-budget-retry-2")
    assert exhausted.status == "terminal_error"
    assert exhausted.provider_runs[-1].role == "accurate_stt"
    assert exhausted.provider_runs[-1].recovery_count == 2
    assert (
        exhausted.provider_runs[-1].error_code == "OPERATION_RECOVERY_BUDGET_EXHAUSTED"
    )

    assert service.can_reconcile_preview(exhausted) is True
    queued = _reconcile_preview(service, exhausted, key="preview-after-stt-budget")

    assert queued.provider_runs[-1].checkpoint == "preview_transcribed"
    assert queued.provider_runs[-1].attempt == 1
    assert queued.provider_runs[-1].recovery_count == 0
    recovered = _advance_persisted_provider_runs(service, queued.id)
    assert recovered.status == "awaiting_confirmation"
    assert recovered.reconciliation_quality == "provisional_only"


def test_preview_recovery_runner_fails_closed_when_the_preview_text_is_gone(
    data_dir: Path,
) -> None:
    """A claimed preview run with no stable preview text left never calls the provider."""

    reconciler = _ScriptedReconciler()
    service, failed, _ = _terminal_stt_failure_with_preview(
        data_dir, reconciler=reconciler
    )
    queued = _reconcile_preview(service, failed, key="preview-text-gone")
    service.operation_repo.save_brain_dump_operation(
        queued.model_copy(update={"segments": []})
    )

    with pytest.raises(ValidationFailure, match="no browser-preview transcript"):
        service.run_due_brain_dump_provider_runs()
    assert reconciler.calls == []
