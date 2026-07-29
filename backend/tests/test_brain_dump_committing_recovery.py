"""T041: a crashed mid-commit operation is auto-resumed to completion.

An operation that faults mid-commit stays in ``committing`` with a durable
partial ledger. Nothing drove its resumption, so it needed a manual retry. The
recovery driver resumes it through the same owner-serialized, deterministic
child-key commit path a client retry uses -- safe by construction: no action is
created twice. It is wired into the periodic voice sweep alongside the existing
provider-lease recovery and retention purges.
"""

from __future__ import annotations

from app.main import _run_voice_sweep
from app.schemas.tasks import ExpectedRevisionRequest
from tests.test_brain_dump_commit_ledger import (
    _drive_to_awaiting,
    _FaultyTaskPort,
    _inbox_titles,
    _owner_id,
)


def _crash_mid_commit(api_client, key_prefix: str):
    """Leave one operation stuck in ``committing`` with a partial ledger."""

    import pytest

    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, key_prefix)

    real_port = service.task_port
    service.task_port = _FaultyTaskPort(real_port, fail_on_call=2)
    with pytest.raises(RuntimeError, match="TASKPORT_FAULT"):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key=f"{key_prefix}-commit",
        )
    service.task_port = real_port  # heal the fault before recovery runs

    partial = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert partial.status == "committing"
    assert sorted(a.status for a in partial.commit_batch.actions) == [
        "pending",
        "succeeded",
    ]
    assert len(_inbox_titles(api_client)) == 1
    return service, owner_id, operation["id"]


def test_recovery_driver_resumes_committing_to_completion(api_client) -> None:
    service, owner_id, operation_id = _crash_mid_commit(api_client, "recover-commit")

    recovered = service.recover_committing_operations()
    assert recovered == 1

    completed = service.get_brain_dump_operation(operation_id, owner_id=owner_id)
    assert completed.status == "completed"
    assert len(completed.committed_task_ids) == 2
    assert len(set(completed.committed_task_ids)) == 2  # no duplicate action
    assert len(completed.action_receipts) == 2
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]

    # A second recovery pass is a no-op: nothing is left committing.
    assert service.recover_committing_operations() == 0


def test_recovery_driver_ignores_non_committing_operations(api_client) -> None:
    """An operation still in review is never swept into a commit."""

    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, _finished = _drive_to_awaiting(api_client, "recover-noop")

    assert service.recover_committing_operations() == 0
    still = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert still.status == "awaiting_confirmation"
    assert _inbox_titles(api_client) == []


def test_periodic_sweep_drives_committing_recovery(api_client) -> None:
    """The wired-in sweep resumes a stuck commit without any manual retry."""

    container = api_client.app.state.container
    service, owner_id, operation_id = _crash_mid_commit(api_client, "recover-sweep")

    _run_voice_sweep(container)

    completed = service.get_brain_dump_operation(operation_id, owner_id=owner_id)
    assert completed.status == "completed"
    assert sorted(a.status for a in completed.commit_batch.actions) == [
        "succeeded",
        "succeeded",
    ]
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]
