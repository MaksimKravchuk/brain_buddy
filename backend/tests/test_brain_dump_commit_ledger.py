"""T033: frozen commit batch + durable per-action partial-commit ledger.

Before the first ``TaskPort`` write, ``commit`` persists a frozen snapshot of the
reviewed proposals with deterministic per-action child identity and a per-action
result record. A TaskPort fault after action N leaves the earlier canonical tasks
in place; a retry (same OR new outer key, and even a fresh process) consumes the
snapshot, skips recorded successes, and creates only the remaining actions -- no
duplicates. Edits/deletes during the partial failure are refused by the existing
state rules, so the frozen snapshot is authoritative.

Satisfies FR-015 / ADR-0002 §485-519 / ADR-0006 B-38.
"""

from __future__ import annotations

import pytest

from app.schemas.tasks import ExpectedRevisionRequest
from app.workflows.voice_brain_dump.service import VoiceBrainDumpService
from app.workflows.voice_brain_dump.task_port import InProcessTaskPort
from tests.test_brain_dump_operations_api import _start_operation, _upload_and_seal


class _FaultyTaskPort:
    """Wrap a real TaskPort and raise once, on the Nth cumulative call."""

    def __init__(self, inner, *, fail_on_call: int) -> None:
        self._inner = inner
        self._fail_on_call = fail_on_call
        self.calls = 0

    def create_native_inbox_task(self, **kwargs):
        self.calls += 1
        if self.calls == self._fail_on_call:
            raise RuntimeError("TASKPORT_FAULT: injected mid-batch failure")
        return self._inner.create_native_inbox_task(**kwargs)


def _drive_to_awaiting(api_client, key_prefix: str):
    """Return (operation dict, awaiting-confirmation body) with two reconciled
    proposals ready to commit through the deterministic pipeline."""

    operation = _start_operation(api_client, key=f"{key_prefix}-start")
    sealed = _upload_and_seal(
        api_client, operation, b"Pay VAT. Send invoice.", f"{key_prefix}-seal"
    )
    finished = sealed.json()
    assert finished["status"] == "awaiting_confirmation", finished
    assert len(finished["proposals"]) == 2
    return operation, finished


def _owner_id(api_client) -> str:
    return api_client.get("/api/auth/me").json()["id"]


def _inbox_titles(api_client) -> list[str]:
    items = api_client.get("/api/tasks", params={"state": "inbox"}).json()["items"]
    return sorted(item["title"] for item in items)


def test_successful_commit_records_a_completed_frozen_batch_ledger(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "ledger-ok")

    committed = service.commit_brain_dump_operation(
        operation["id"],
        ExpectedRevisionRequest(expected_revision=finished["revision"]),
        owner_id=owner_id,
        idempotency_key="ledger-ok-commit",
    )
    assert committed.status == "completed"
    assert committed.commit_batch is not None
    assert [action.status for action in committed.commit_batch.actions] == [
        "succeeded",
        "succeeded",
    ]
    assert all(action.task_id for action in committed.commit_batch.actions)
    assert len(committed.committed_task_ids) == 2
    assert len(committed.action_receipts) == 2
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]


def test_partial_failure_persists_frozen_ledger_and_earlier_task(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "ledger-partial")

    service.task_port = _FaultyTaskPort(service.task_port, fail_on_call=2)
    with pytest.raises(RuntimeError, match="TASKPORT_FAULT"):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key="ledger-partial-commit",
        )

    partial = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert partial.status == "committing"
    assert partial.commit_batch is not None
    statuses = sorted(action.status for action in partial.commit_batch.actions)
    assert statuses == ["pending", "succeeded"]
    # Exactly the first action's canonical task exists; the failed one did not.
    assert len(_inbox_titles(api_client)) == 1


def test_retry_after_partial_failure_completes_remainder_only(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "ledger-retry")

    service.task_port = _FaultyTaskPort(service.task_port, fail_on_call=2)
    with pytest.raises(RuntimeError):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key="ledger-retry-commit",
        )
    partial = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)

    # Retry with a NEW outer key: the fault has healed (call 3 != fail_on 2).
    resumed = service.commit_brain_dump_operation(
        operation["id"],
        ExpectedRevisionRequest(expected_revision=partial.revision),
        owner_id=owner_id,
        idempotency_key="ledger-retry-commit-2",
    )
    assert resumed.status == "completed"
    assert len(resumed.committed_task_ids) == 2
    assert len(set(resumed.committed_task_ids)) == 2  # unique task ids, no dup
    assert len(resumed.action_receipts) == 2
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]


def test_retry_after_partial_failure_with_same_outer_key(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "ledger-samekey")

    payload = ExpectedRevisionRequest(expected_revision=finished["revision"])
    service.task_port = _FaultyTaskPort(service.task_port, fail_on_call=2)
    with pytest.raises(RuntimeError):
        service.commit_brain_dump_operation(
            operation["id"], payload, owner_id=owner_id, idempotency_key="same-key"
        )

    # Same outer Idempotency-Key: the failed attempt stored no result, so the
    # retry re-enters and resumes the frozen ledger to completion.
    resumed = service.commit_brain_dump_operation(
        operation["id"], payload, owner_id=owner_id, idempotency_key="same-key"
    )
    assert resumed.status == "completed"
    assert len(resumed.committed_task_ids) == 2
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]

    # A further replay under the same key is now a pure idempotent read.
    replay = service.commit_brain_dump_operation(
        operation["id"], payload, owner_id=owner_id, idempotency_key="same-key"
    )
    assert replay.committed_task_ids == resumed.committed_task_ids
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]


def test_restart_between_actions_resumes_from_persisted_ledger(api_client) -> None:
    """A fresh service instance (simulating a process restart) resumes commit
    purely from the durably persisted frozen ledger."""

    container = api_client.app.state.container
    service = container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "ledger-restart")

    service.task_port = _FaultyTaskPort(service.task_port, fail_on_call=2)
    with pytest.raises(RuntimeError):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key="ledger-restart-commit",
        )
    partial = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert partial.status == "committing"

    # Rebuild the service over the SAME persisted repositories -- no in-memory
    # ledger carried over -- and resume.
    fresh = VoiceBrainDumpService(
        container.voice_operation_repo,
        task_port=InProcessTaskPort(container.task_service.create_native_inbox_task),
        allowed_external_provider_categories=frozenset({"openai"}),
    )
    resumed = fresh.commit_brain_dump_operation(
        operation["id"],
        ExpectedRevisionRequest(expected_revision=partial.revision),
        owner_id=owner_id,
        idempotency_key="ledger-restart-resume",
    )
    assert resumed.status == "completed"
    assert len(resumed.committed_task_ids) == 2
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]


def test_proposal_edit_is_refused_during_partial_failure(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "ledger-editlock")
    pending_proposal_id = finished["proposals"][1]["id"]

    service.task_port = _FaultyTaskPort(service.task_port, fail_on_call=2)
    with pytest.raises(RuntimeError):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key="ledger-editlock-commit",
        )
    partial = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)

    # Editing/deleting a proposal while the batch is frozen mid-commit is refused
    # by the existing state rules, so nothing can diverge from the snapshot.
    edit = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{pending_proposal_id}",
        headers={"Idempotency-Key": "ledger-editlock-edit"},
        json={"expected_revision": partial.revision, "title": "Rewritten title"},
    )
    assert edit.status_code in {400, 409, 422}, edit.text

    # The remaining action still commits with its frozen title, not the edit.
    resumed = service.commit_brain_dump_operation(
        operation["id"],
        ExpectedRevisionRequest(expected_revision=partial.revision),
        owner_id=owner_id,
        idempotency_key="ledger-editlock-resume",
    )
    assert resumed.status == "completed"
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]
