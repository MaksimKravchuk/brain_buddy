"""T040: frozen commit_batch plaintext titles must not outlive retention.

The frozen commit ledger (``BrainDumpCommitBatchDocument``) captures each
reviewed proposal's title in plaintext so a partial commit can resume. The
recorded provenance decision (ADR-0002) keeps exact derived text only during the
working-artifact retention window; afterwards the audit trail is IDs/hashes only.

These tests pin that the working-artifact sweep reduces commit_batch titles to
their SHA-256 (matching the action receipt's ``confirmed_title_sha256``) once a
terminal operation is past its window, while the resume-critical ledger data
(child idempotency keys + per-action results) and the committed provenance
survive -- and that titles are retained while the window is still open.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from app.schemas.tasks import ExpectedRevisionRequest
from tests.test_brain_dump_commit_ledger import (
    _drive_to_awaiting,
    _inbox_titles,
    _owner_id,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _commit(api_client, key_prefix: str):
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, key_prefix)
    committed = service.commit_brain_dump_operation(
        operation["id"],
        ExpectedRevisionRequest(expected_revision=finished["revision"]),
        owner_id=owner_id,
        idempotency_key=f"{key_prefix}-commit",
    )
    assert committed.status == "completed"
    return service, owner_id, operation["id"], committed


def _expire_working_artifacts(service, owner_id: str, operation_id: str) -> None:
    persisted = service.get_brain_dump_operation(operation_id, owner_id=owner_id)
    assert persisted.working_artifacts_expires_at is not None
    service.operation_repo.save_brain_dump_operation(
        persisted.model_copy(
            update={
                "working_artifacts_expires_at": persisted.working_artifacts_expires_at
                - timedelta(days=14)
            }
        )
    )


def test_sweep_reduces_commit_batch_titles_to_hashes_after_window(api_client) -> None:
    service, owner_id, operation_id, committed = _commit(api_client, "title-purge")

    # Precondition: the frozen ledger holds the plaintext titles.
    assert committed.commit_batch is not None
    plaintext = {action.title for action in committed.commit_batch.actions}
    assert plaintext == {"Pay VAT", "Send invoice"}
    original_child_keys = {
        action.proposal_id: action.child_idempotency_key
        for action in committed.commit_batch.actions
    }
    original_task_ids = {
        action.proposal_id: action.task_id for action in committed.commit_batch.actions
    }

    _expire_working_artifacts(service, owner_id, operation_id)
    assert service.purge_expired_working_artifacts() >= 1

    swept = service.get_brain_dump_operation(operation_id, owner_id=owner_id)
    assert swept.commit_batch is not None
    # Titles are now hashes -- no plaintext survives the window. Each reduced
    # title is the SHA-256 of the original and equals the receipt's hash.
    expected_hashes = {_sha256("Pay VAT"), _sha256("Send invoice")}
    receipt_hashes = {
        receipt.proposal_id: receipt.confirmed_title_sha256
        for receipt in swept.action_receipts
    }
    for action in swept.commit_batch.actions:
        assert action.title in expected_hashes
        assert action.title == receipt_hashes[action.proposal_id]
    # Resume-critical ledger data and committed provenance are untouched.
    for action in swept.commit_batch.actions:
        assert action.status == "succeeded"
        assert action.child_idempotency_key == original_child_keys[action.proposal_id]
        assert action.task_id == original_task_ids[action.proposal_id]
    assert sorted(swept.committed_task_ids) == sorted(original_task_ids.values())
    assert len(swept.action_receipts) == 2
    # Raw working text is gone; the canonical tasks are untouched in their store.
    assert swept.segments == []
    assert swept.proposals == []
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]


def test_commit_idempotency_holds_after_titles_are_purged(api_client) -> None:
    """A replay after the titles are reduced still creates no duplicate task."""

    service, owner_id, operation_id, committed = _commit(api_client, "title-purge-idem")
    _expire_working_artifacts(service, owner_id, operation_id)
    service.purge_expired_working_artifacts()

    # Replaying the commit (new outer key, op already completed) is a no-op.
    replay = service.commit_brain_dump_operation(
        operation_id,
        ExpectedRevisionRequest(expected_revision=committed.revision),
        owner_id=owner_id,
        idempotency_key="title-purge-idem-replay",
    )
    assert replay.status == "completed"
    assert replay.committed_task_ids == committed.committed_task_ids
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]


def test_titles_are_retained_before_the_window_closes(api_client) -> None:
    """Within the retention window the sweep leaves commit_batch titles intact."""

    service, owner_id, operation_id, _committed = _commit(api_client, "title-window")
    # No expiry manipulation: the window is still open.
    service.purge_expired_working_artifacts()
    still = service.get_brain_dump_operation(operation_id, owner_id=owner_id)
    assert still.commit_batch is not None
    assert {action.title for action in still.commit_batch.actions} == {
        "Pay VAT",
        "Send invoice",
    }
