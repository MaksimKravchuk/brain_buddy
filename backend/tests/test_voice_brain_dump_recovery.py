"""Provider retry/recovery and stale-patch regression tests for Voice Brain Dump.

Covers AI-QA MUST-2 (persisted retryable/terminal provider state with resumable
checkpoint/recovery) and the PA-04/PA-05 stale-patch rebase/rejection rules from
``specs/002-async-voice-workflows/acceptance-tests.md`` (RC-01, RC-02, PA-04, PA-05).
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from app.exceptions import ValidationFailure
from app.modules.tasks import TaskRepository, TaskService
from app.modules.tasks.domain import (
    BrainDumpOperationDocument,
    BrainDumpProviderRunDocument,
)
from app.schemas.tasks import (
    BrainDumpOperationStartRequest,
    BrainDumpSealRequest,
    ExpectedRevisionRequest,
)
from app.utils.time import utcnow
from app.workflows.voice_brain_dump.domain import (
    ProposalPatch,
    ReconciledProposal,
    apply_proposal_patches,
)
from app.workflows.voice_brain_dump.providers import DeterministicAccurateStt

OWNER = "user_recovery_owner"


def test_structural_lineage_requires_meaningful_textual_evidence() -> None:
    assert TaskService._titles_form_split(
        "Buy oat milk and call the dentist",
        ["Buy oat milk", "Call the dentist"],
    )
    assert not TaskService._titles_form_split(
        "Buy oat milk",
        ["Untranscribed sealed audio", "Call the dentist"],
    )
    assert not TaskService._titles_form_split("and the", ["Call dentist"])

    assert TaskService._titles_form_merge(
        ["Buy oat milk", "Call the dentist"],
        "Buy oat milk and call the dentist",
    )
    assert not TaskService._titles_form_merge(
        ["Buy oat milk", "Call the dentist"],
        "Untranscribed sealed audio",
    )
    assert not TaskService._titles_form_merge(["and the"], "Call dentist")
    assert TaskService._title_content_words("The call to Anna") == {"call", "anna"}
    assert TaskService._extract_task_titles("купить хлеб и молоко") == [
        "Купить хлеб и молоко"
    ]
    assert TaskService._titles_refer_to_same_item("Call", "Call")
    assert not TaskService._titles_refer_to_same_item("Call", "Email")


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
) -> TaskService:
    repository = TaskRepository(data_dir)
    accurate_stt = DeterministicAccurateStt(
        {"media_recovery": "почини BrainBuddy"},
        fail_plan=fail_plan,
        allow_text_fixture_audio=True,
    )
    return TaskService(
        repository,
        accurate_stt=accurate_stt,
        max_operation_recoveries=max_operation_recoveries,
        max_cumulative_cost_usd_per_operation=max_cumulative_cost_usd_per_operation,
        provider_run_lease_seconds=provider_run_lease_seconds,
    )


def _advance_persisted_provider_runs(
    service: TaskService, operation_id: str
) -> BrainDumpOperationDocument:
    """Drive queued provider work explicitly; request commands never call providers."""

    for _ in range(3):
        if service.run_due_brain_dump_provider_runs() == 0:
            break
    return service.task_repo.get_brain_dump_operation_for_owner(
        operation_id, owner_id=OWNER
    )


def _seal(
    service: TaskService, *, audio: bytes = b"audio bytes"
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
    )
    operation = service.get_brain_dump_operation(operation.id, owner_id=OWNER)
    return operation, service


def test_retryable_provider_failure_persists_checkpoint_and_retry_resumes_it(
    data_dir: Path,
) -> None:
    service = _service(data_dir, fail_plan={"media_recovery": ["retryable"]})
    operation, _ = _seal(service)
    # Force a deterministic media_ref so the fake fail plan keys match.
    operation = service.task_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.task_repo.save_brain_dump_operation(operation)

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
    operation = service.task_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    ).model_copy(update={"media_ref": "media_recovery"})
    service.task_repo.save_brain_dump_operation(operation)

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
    assert exhausted.provider_runs[-1].error_code == "OPERATION_RECOVERY_BUDGET_EXHAUSTED"
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
    operation = service.task_repo.get_brain_dump_operation_for_owner(
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
    service.task_repo.save_brain_dump_operation(seeded)

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
    service.task_repo.list_in_flight_provider_run_operations = lambda: [operation]

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
        persisted = service.task_repo.get_brain_dump_operation_for_owner(
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
    service.task_repo.save_brain_dump_operation(operation)

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
    service.task_repo.save_brain_dump_operation(claimed)

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
    chunk_path = service.task_repo.brain_dump_audio_chunk_path(
        OWNER, operation.id, 0, sha256
    )
    chunk_path.unlink()

    repaired = service.upload_brain_dump_audio_chunk(
        operation.id,
        0,
        audio,
        owner_id=OWNER,
        content_sha256=sha256,
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

    persisted = TaskRepository(data_dir).get_brain_dump_operation_for_owner(
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
    service.task_repo.save_brain_dump_operation(persisted)

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
    service.task_repo.save_brain_dump_operation(operation)
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

    persisted = TaskRepository(data_dir).get_brain_dump_operation_for_owner(
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
    operation = service.task_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.task_repo.save_brain_dump_operation(operation)

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
    operation = service.task_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.task_repo.save_brain_dump_operation(operation)

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
    operation = service.task_repo.get_brain_dump_operation_for_owner(
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
    operation = service.task_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.task_repo.save_brain_dump_operation(operation)

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
    operation = service.task_repo.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    broken = operation.model_copy(
        update={"status": "retryable_error", "sealed_manifest_hash": None}
    )
    service.task_repo.save_brain_dump_operation(broken)

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
