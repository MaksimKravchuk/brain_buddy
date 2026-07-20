"""Canonical proposal-patch/freeze/confirm contract tests (T056).

Covers: immutable action snapshots with no result fields, byte-stable
snapshots across the confirm write, receipt-derived per-action results,
deterministic ``H(operation_id, batch_id, action_id)`` child idempotency,
parent-key conflicts, partial-recovery after a simulated restart, owner
scoping, and "no Task exists before confirm".
"""

from __future__ import annotations

from app.utils.time import utcnow
from tests.test_brain_dump_operations_api import (
    _start_operation,
    _upload_and_seal,
)

_ACTION_SNAPSHOT_FIELDS = {
    "action_id",
    "proposal_id",
    "title",
    "target",
    "before_summary",
    "after_summary",
    "source_cue",
    "confidence",
    "warnings",
    "destination",
}


def _reconciled_operation(api_client, key: str, audio: bytes) -> dict[str, object]:
    operation = _start_operation(api_client, key=f"start-{key}")
    sealed = _upload_and_seal(api_client, operation, audio, f"seal-{key}")
    body = sealed.json()
    assert body["status"] == "awaiting_confirmation", body
    return body


def _freeze(api_client, operation: dict[str, object], key: str) -> dict[str, object]:
    proposal_ids = [p["id"] for p in operation["proposals"] if not p["deleted"]]
    response = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/proposal-batches",
        headers={"Idempotency-Key": key},
        json={
            "based_on_proposal_revision": operation["proposal_revision"],
            "expected_operation_revision": operation["revision"],
            "selected_proposal_ids": proposal_ids,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _confirm(
    api_client, operation: dict[str, object], batch: dict[str, object], key: str
):
    active_batch = batch["active_proposal_batch"]
    return api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/confirm",
        headers={"Idempotency-Key": key},
        json={
            "proposal_batch_id": active_batch["id"],
            "expected_batch_revision": active_batch["revision"],
            "expected_operation_revision": batch["revision"],
        },
    )


def test_frozen_batch_snapshot_has_no_result_or_task_fields(api_client) -> None:
    """Every immutable action snapshot exposes only review fields -- never a
    result status or Task ID."""

    operation = _reconciled_operation(
        api_client, "confirm-snapshot", b"Call the dentist."
    )
    frozen = _freeze(api_client, operation, "freeze-snapshot")
    active_batch = frozen["active_proposal_batch"]
    assert active_batch["status"] == "frozen"
    assert active_batch["snapshot"], "at least one action must be frozen"
    for action in active_batch["snapshot"]:
        assert set(action) == _ACTION_SNAPSHOT_FIELDS
        assert "result_task_id" not in action
        assert "status" not in action
    # Results are a separate projection, folded beside the snapshot.
    for result in active_batch["results"]:
        assert result["status"] == "pending"
        assert result["result_task_id"] is None


def test_no_task_exists_before_confirm(api_client) -> None:
    operation = _reconciled_operation(api_client, "confirm-no-task", b"Buy milk.")
    _freeze(api_client, operation, "freeze-no-task")

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert inbox["items"] == []


def test_confirm_creates_exactly_one_task_per_action_snapshot_stays_byte_stable(
    api_client,
) -> None:
    operation = _reconciled_operation(api_client, "confirm-once", b"Buy milk.")
    frozen = _freeze(api_client, operation, "freeze-once")
    snapshot_before = frozen["active_proposal_batch"]["snapshot"]

    confirmed = _confirm(api_client, operation, frozen, "confirm-once")
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "completed"
    committed_batch = body["committed_proposal_batch"]
    assert committed_batch["status"] == "committed"
    # The frozen action snapshot never changes shape/content after commit.
    assert committed_batch["snapshot"] == snapshot_before
    assert len(committed_batch["results"]) == len(snapshot_before)
    for result in committed_batch["results"]:
        assert result["status"] == "succeeded"
        assert result["result_task_id"]
    assert len(body["committed_task_ids"]) == len(snapshot_before)

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert [item["title"] for item in inbox["items"]] == ["Buy milk"]


def test_confirm_replay_with_same_idempotency_key_creates_no_duplicate_task(
    api_client,
) -> None:
    operation = _reconciled_operation(api_client, "confirm-replay", b"Buy milk.")
    frozen = _freeze(api_client, operation, "freeze-replay")

    first = _confirm(api_client, operation, frozen, "confirm-replay-key")
    assert first.status_code == 200, first.text
    second = _confirm(api_client, operation, frozen, "confirm-replay-key")
    assert second.status_code == 200, second.text
    assert first.json()["committed_task_ids"] == second.json()["committed_task_ids"]

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert len(inbox["items"]) == 1


def test_confirm_parent_idempotency_key_conflict_returns_409(api_client) -> None:
    operation = _reconciled_operation(api_client, "confirm-conflict", b"Buy milk.")
    frozen = _freeze(api_client, operation, "freeze-conflict")
    active_batch = frozen["active_proposal_batch"]

    first = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/confirm",
        headers={"Idempotency-Key": "confirm-conflict-key"},
        json={
            "proposal_batch_id": active_batch["id"],
            "expected_batch_revision": active_batch["revision"],
            "expected_operation_revision": frozen["revision"],
        },
    )
    assert first.status_code == 200, first.text

    conflicting = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/confirm",
        headers={"Idempotency-Key": "confirm-conflict-key"},
        json={
            "proposal_batch_id": active_batch["id"],
            "expected_batch_revision": active_batch["revision"],
            # A different request hash under the same key must conflict.
            "expected_operation_revision": frozen["revision"] + 999,
        },
    )
    assert conflicting.status_code == 409, conflicting.text


def test_confirm_survives_partial_recovery_without_duplicate_tasks(api_client) -> None:
    """Simulate a crash after one action's Task/receipt was durably
    persisted but before the write completed for the rest of the batch."""

    operation = _reconciled_operation(api_client, "confirm-partial", b"Buy milk.")
    frozen = _freeze(api_client, operation, "freeze-partial")
    active_batch = frozen["active_proposal_batch"]
    action = active_batch["snapshot"][0]

    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]
    repo = container.voice_operation_repo
    stored = repo.get_brain_dump_operation_for_owner(operation["id"], owner_id=owner_id)

    # Pre-create the Task via the same TaskPort/child-key derivation the
    # confirm command itself would use, modelling a durable write that
    # completed just before a process crash.
    import hashlib

    child_key = hashlib.sha256(
        f"{operation['id']}:{active_batch['id']}:{action['action_id']}".encode()
    ).hexdigest()
    from app.workflows.voice_brain_dump.domain import BrainDumpActionReceiptDocument

    task = container.task_service.create_native_inbox_task(
        owner_id=owner_id,
        title=action["title"],
        source_capture_ids=[f"brain_dump:{operation['id']}:{action['proposal_id']}"],
        idempotency_key=child_key,
    )
    partial_receipt = BrainDumpActionReceiptDocument(
        id=f"receipt:{operation['id']}:{active_batch['id']}:{action['action_id']}",
        proposal_id=action["proposal_id"],
        task_id=task.id,
        child_idempotency_key=child_key,
        batch_id=active_batch["id"],
        action_id=action["action_id"],
        outcome="succeeded",
        confirmed_at=utcnow(),
    )
    repo.save_brain_dump_operation(
        stored.model_copy(
            update={
                "action_receipts": [*stored.action_receipts, partial_receipt],
                "revision": stored.revision + 1,
            }
        )
    )
    refreshed = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()

    confirmed = _confirm(api_client, operation, refreshed, "confirm-partial-recovery")
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert len(body["committed_task_ids"]) == len(active_batch["snapshot"])
    # The pre-seeded task ID is reused, not duplicated.
    assert task.id in body["committed_task_ids"]

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert len(inbox["items"]) == len(active_batch["snapshot"])


def test_owner_cannot_freeze_or_confirm_another_owners_operation(
    second_api_client,
) -> None:
    client_a, client_b = second_api_client
    operation = _reconciled_operation(client_a, "confirm-owner", b"Buy milk.")

    frozen_as_b = client_b.post(
        f"/api/brain-dump-operations/{operation['id']}/proposal-batches",
        headers={"Idempotency-Key": "freeze-owner-b"},
        json={
            "based_on_proposal_revision": operation["proposal_revision"],
            "expected_operation_revision": operation["revision"],
            "selected_proposal_ids": [operation["proposals"][0]["id"]],
        },
    )
    assert frozen_as_b.status_code == 404, frozen_as_b.text

    frozen = _freeze(client_a, operation, "freeze-owner-a")
    active_batch = frozen["active_proposal_batch"]
    confirm_as_b = client_b.post(
        f"/api/brain-dump-operations/{operation['id']}/confirm",
        headers={"Idempotency-Key": "confirm-owner-b"},
        json={
            "proposal_batch_id": active_batch["id"],
            "expected_batch_revision": active_batch["revision"],
            "expected_operation_revision": frozen["revision"],
        },
    )
    assert confirm_as_b.status_code == 404, confirm_as_b.text
