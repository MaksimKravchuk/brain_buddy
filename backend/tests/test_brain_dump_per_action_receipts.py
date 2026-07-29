"""Item 2: action receipts are durable per-action, not only after the batch.

Canonical task creation is per-action durable, so its immutable receipt/source
link must be too. Each action's receipt is written in the same phase as its
ledger result, idempotent by the deterministic receipt id, so a crash (or a
hard-maximum cancellation) after action N leaves N created tasks each with its
receipt -- never a created task pointing at a workflow reference with no receipt.
"""

from __future__ import annotations

import pytest

from app.schemas.tasks import ExpectedRevisionRequest
from tests.test_brain_dump_commit_ledger import (
    _drive_to_awaiting,
    _FaultyTaskPort,
    _inbox_titles,
    _owner_id,
)


def test_partial_failure_leaves_a_receipt_for_each_created_task(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "receipt-partial")

    service.task_port = _FaultyTaskPort(service.task_port, fail_on_call=2)
    with pytest.raises(RuntimeError, match="TASKPORT_FAULT"):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key="receipt-partial-commit",
        )

    partial = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert partial.status == "committing"
    succeeded = [a for a in partial.commit_batch.actions if a.status == "succeeded"]
    assert len(succeeded) == 1
    # The one created task already has its durable receipt, mid-partial-failure.
    assert len(partial.action_receipts) == 1
    receipt = partial.action_receipts[0]
    assert receipt.id == f"receipt:{operation['id']}:{succeeded[0].proposal_id}"
    assert receipt.task_id == succeeded[0].task_id
    assert receipt.source_operation_id == operation["id"]

    # Resume completes the batch: one receipt per action, no duplicates.
    resumed = service.commit_brain_dump_operation(
        operation["id"],
        ExpectedRevisionRequest(expected_revision=partial.revision),
        owner_id=owner_id,
        idempotency_key="receipt-partial-resume",
    )
    assert resumed.status == "completed"
    assert len(resumed.action_receipts) == 2
    receipt_ids = [r.id for r in resumed.action_receipts]
    assert len(set(receipt_ids)) == 2
    assert {r.task_id for r in resumed.action_receipts} == set(
        resumed.committed_task_ids
    )
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]


def test_hard_max_cancelled_commit_keeps_receipts_for_created_tasks(api_client) -> None:
    """A committing op hard-cancelled at its deadline still has a resolvable
    receipt for every task it created before the cancel."""

    from datetime import timedelta

    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "receipt-hardmax")

    service.task_port = _FaultyTaskPort(service.task_port, fail_on_call=2)
    with pytest.raises(RuntimeError):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key="receipt-hardmax-commit",
        )

    persisted = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    anchor = persisted.working_artifacts_expires_at or persisted.updated_at
    service.operation_repo.save_brain_dump_operation(
        persisted.model_copy(
            update={"working_artifacts_expires_at": anchor - timedelta(days=14)}
        )
    )
    assert service.purge_expired_working_artifacts() >= 1

    finalized = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert finalized.status == "cancelled"
    # Every preserved (created) task has a resolvable receipt.
    assert finalized.committed_task_ids
    receipt_task_ids = {r.task_id for r in finalized.action_receipts}
    for task_id in finalized.committed_task_ids:
        assert task_id in receipt_task_ids
