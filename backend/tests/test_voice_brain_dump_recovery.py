"""Provider retry/recovery and stale-patch regression tests for Voice Brain Dump.

Covers AI-QA MUST-2 (persisted retryable/terminal provider state with resumable
checkpoint/recovery) and the PA-04/PA-05 stale-patch rebase/rejection rules from
``specs/002-async-voice-workflows/acceptance-tests.md`` (RC-01, RC-02, PA-04, PA-05).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

import pytest

from app.exceptions import ValidationFailure
from app.modules.tasks import TaskRepository, TaskService
from app.modules.tasks.domain import BrainDumpOperationDocument
from app.schemas.tasks import (
    BrainDumpOperationStartRequest,
    BrainDumpSealRequest,
    ExpectedRevisionRequest,
)
from app.workflows.voice_brain_dump.domain import (
    ProposalPatch,
    ReconciledProposal,
    apply_proposal_patches,
)
from app.workflows.voice_brain_dump.providers import DeterministicAccurateStt

OWNER = "user_recovery_owner"


def _service(data_dir: Path, *, fail_plan: dict[str, list[str]] | None = None) -> TaskService:
    repository = TaskRepository(data_dir)
    accurate_stt = DeterministicAccurateStt(
        {"media_recovery": "почини BrainBuddy"}, fail_plan=fail_plan
    )
    return TaskService(repository, accurate_stt=accurate_stt)


def _seal(
    service: TaskService, *, audio: bytes = b"audio bytes"
) -> tuple[BrainDumpOperationDocument, TaskService]:
    operation = service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": False}}
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
    operation = service.task_repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER)
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.task_repo.save_brain_dump_operation(operation)

    sealed = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(expected_revision=operation.revision, expected_chunks=1),
        owner_id=OWNER,
        idempotency_key="recovery-seal-1",
    )

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

    assert retried.status == "awaiting_confirmation"
    resumed_run = retried.provider_runs[-1]
    assert resumed_run.status == "succeeded"
    assert resumed_run.attempt == 2
    assert resumed_run.recovery_count == 1
    # Same sealed manifest/checkpoint is reused; no re-upload or re-seal needed.
    assert retried.sealed_manifest_hash == sealed.sealed_manifest_hash
    assert any(proposal.title for proposal in retried.proposals)


def test_recovery_budget_exhausts_into_terminal_error_without_hot_loop(
    data_dir: Path,
) -> None:
    service = _service(
        data_dir, fail_plan={"media_recovery": ["retryable", "retryable", "retryable"]}
    )
    operation, _ = _seal(service)
    operation = service.task_repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER)
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.task_repo.save_brain_dump_operation(operation)

    sealed = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(expected_revision=operation.revision, expected_chunks=1),
        owner_id=OWNER,
        idempotency_key="recovery-seal-budget",
    )
    assert sealed.status == "retryable_error"

    first_retry = service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=sealed.revision),
        owner_id=OWNER,
        idempotency_key="recovery-retry-budget-1",
    )
    assert first_retry.status == "retryable_error"
    assert first_retry.provider_runs[-1].attempt == 2

    second_retry = service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=first_retry.revision),
        owner_id=OWNER,
        idempotency_key="recovery-retry-budget-2",
    )
    # Attempt 3 hits the bounded recovery budget: terminal, not another retryable loop.
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
    operation = service.task_repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER)
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.task_repo.save_brain_dump_operation(operation)

    sealed = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(expected_revision=operation.revision, expected_chunks=1),
        owner_id=OWNER,
        idempotency_key="recovery-seal-terminal",
    )

    assert sealed.status == "terminal_error"
    assert sealed.provider_runs[-1].status == "terminal_error"
    assert sealed.committed_task_ids == []


def test_retry_requires_retryable_state(data_dir: Path) -> None:
    service = _service(data_dir)
    operation, _ = _seal(service)
    operation = service.task_repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER)

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
    operation = service.task_repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER)
    operation = operation.model_copy(update={"media_ref": "media_recovery"})
    service.task_repo.save_brain_dump_operation(operation)

    sealed = service.seal_brain_dump_operation(
        operation.id,
        BrainDumpSealRequest(expected_revision=operation.revision, expected_chunks=1),
        owner_id=OWNER,
        idempotency_key="recovery-seal-replay",
    )
    assert sealed.status == "retryable_error"

    first = service.retry_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=sealed.revision),
        owner_id=OWNER,
        idempotency_key="recovery-retry-replay",
    )
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
    operation = service.task_repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER)
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
