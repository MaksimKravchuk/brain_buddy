"""Canonical proposal-patch/freeze/confirm contract tests (T056).

Covers: immutable action snapshots with no result fields, byte-stable
snapshots across the confirm write, receipt-derived per-action results,
deterministic ``H(operation_id, batch_id, action_id)`` child idempotency,
parent-key conflicts, partial-recovery after a simulated restart, owner
scoping, "no Task exists before confirm", rejecting stale/cancelled/
superseded batches interleaved mid-confirm, a shared canonical/legacy
source-action identity, and terminal TaskPort failure handling.
"""

from __future__ import annotations

from app.exceptions import RepositoryError
from app.utils.time import utcnow
from app.workflows.voice_brain_dump.confirmation import brain_dump_source_action_key
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
    child_key = brain_dump_source_action_key(
        operation_id=operation["id"], proposal_id=action["proposal_id"]
    )
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


def test_confirm_appends_started_and_succeeded_attempts_for_every_action(
    api_client,
) -> None:
    """Each action's confirmation durably records an append-only ``started``
    attempt before its ``TaskPort`` call and a ``succeeded`` attempt after,
    in addition to the folded terminal receipt -- never only the folded
    projection."""

    operation = _reconciled_operation(api_client, "confirm-attempts", b"Buy milk.")
    frozen = _freeze(api_client, operation, "freeze-attempts")
    active_batch = frozen["active_proposal_batch"]

    confirmed = _confirm(api_client, operation, frozen, "confirm-attempts-key")
    assert confirmed.status_code == 200, confirmed.text

    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]
    stored = container.voice_operation_repo.get_brain_dump_operation_for_owner(
        operation["id"], owner_id=owner_id
    )
    attempts = [
        attempt
        for attempt in stored.action_receipt_attempts
        if attempt.batch_id == active_batch["id"]
    ]
    for action in active_batch["snapshot"]:
        action_attempts = sorted(
            (a for a in attempts if a.action_id == action["action_id"]),
            key=lambda a: a.sequence,
        )
        assert [a.status for a in action_attempts] == ["started", "succeeded"]
        assert action_attempts[0].task_id is None
        assert action_attempts[1].task_id is not None
        assert all(a.attempt == 1 for a in action_attempts)
        assert action_attempts[0].sequence < action_attempts[1].sequence


def test_confirm_reuses_task_created_before_crash_with_no_local_trace(
    api_client,
) -> None:
    """Model a total crash before any Voice-DB write for one action landed
    (no ``started`` attempt, no receipt) but *after* its ``TaskPort`` call
    durably created the Task under the deterministic child key. The retry
    must still resolve to that exact Task -- the permanent, owner-scoped
    ``H(operation,batch,action)`` uniqueness the Tasks module enforces is
    the backstop even when this operation's own append-only trail is
    entirely missing for that action."""

    operation = _reconciled_operation(api_client, "confirm-precreated", b"Buy milk.")
    frozen = _freeze(api_client, operation, "freeze-precreated")
    active_batch = frozen["active_proposal_batch"]
    action = active_batch["snapshot"][0]

    child_key = brain_dump_source_action_key(
        operation_id=operation["id"], proposal_id=action["proposal_id"]
    )
    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]
    pre_created_task = container.task_service.create_native_inbox_task(
        owner_id=owner_id,
        title=action["title"],
        source_capture_ids=[f"brain_dump:{operation['id']}:{action['proposal_id']}"],
        idempotency_key=child_key,
    )
    # No receipt and no attempt row was ever written for this action --
    # confirm still has to derive the exact same child key and reuse the
    # Task rather than creating a duplicate.

    confirmed = _confirm(api_client, operation, frozen, "confirm-precreated-key")
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["committed_task_ids"].count(pre_created_task.id) == 1
    assert len(body["committed_task_ids"]) == len(active_batch["snapshot"])

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    matching = [item for item in inbox["items"] if item["id"] == pre_created_task.id]
    assert len(matching) == 1


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


def _patch_service_task_port(api_client, wrapper_factory):
    """Temporarily wrap ``task_port.create_native_inbox_task`` and return a
    restore callable. ``wrapper_factory(real_create)`` builds the wrapper."""

    service = api_client.app.state.container.voice_brain_dump_service
    real_create = service.task_port.create_native_inbox_task
    service.task_port.create_native_inbox_task = wrapper_factory(real_create)

    def restore() -> None:
        service.task_port.create_native_inbox_task = real_create

    return service, restore


def test_confirm_rejects_action_after_interleaved_cancel(api_client) -> None:
    """A cancel that lands between one action's ``TaskPort`` call and the
    next action's confirmation must stop the batch from completing: no
    later action may create a Task, and cancelled must never turn into
    completed."""

    operation = _reconciled_operation(
        api_client, "confirm-interleave-cancel", b"Buy milk. Call the dentist."
    )
    frozen = _freeze(api_client, operation, "freeze-interleave-cancel")
    active_batch = frozen["active_proposal_batch"]
    assert len(active_batch["snapshot"]) == 2

    calls = {"n": 0}

    def wrapper_factory(real_create):
        def wrapped(**kwargs):
            calls["n"] += 1
            result = real_create(**kwargs)
            if calls["n"] == 1:
                current = api_client.get(
                    f"/api/brain-dump-operations/{operation['id']}"
                ).json()
                cancelled = api_client.post(
                    f"/api/brain-dump-operations/{operation['id']}/commands/cancel",
                    headers={"Idempotency-Key": "interleave-cancel"},
                    json={"expected_revision": current["revision"]},
                )
                assert cancelled.status_code == 200, cancelled.text
            return result

        return wrapped

    _, restore = _patch_service_task_port(api_client, wrapper_factory)
    try:
        confirmed = _confirm(api_client, operation, frozen, "confirm-interleave-cancel")
    finally:
        restore()

    assert confirmed.status_code >= 400, confirmed.text
    assert calls["n"] == 1, "the second action must never reach TaskPort"

    final = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert final["status"] == "cancelled"

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert len(inbox["items"]) == 1


def test_confirm_rejects_action_after_interleaved_proposal_patch_supersedes_batch(
    api_client,
) -> None:
    """A proposal patch (which supersedes the active frozen batch) landing
    mid-confirm must stop later actions from creating Tasks against the now
    stale batch."""

    operation = _reconciled_operation(
        api_client, "confirm-interleave-patch", b"Buy milk. Call the dentist."
    )
    frozen = _freeze(api_client, operation, "freeze-interleave-patch")
    active_batch = frozen["active_proposal_batch"]
    assert len(active_batch["snapshot"]) == 2
    other_proposal = next(p for p in operation["proposals"] if not p["deleted"])

    calls = {"n": 0}

    def wrapper_factory(real_create):
        def wrapped(**kwargs):
            calls["n"] += 1
            result = real_create(**kwargs)
            if calls["n"] == 1:
                current = api_client.get(
                    f"/api/brain-dump-operations/{operation['id']}"
                ).json()
                current_proposal = next(
                    p for p in current["proposals"] if p["id"] == other_proposal["id"]
                )
                patched = api_client.post(
                    f"/api/brain-dump-operations/{operation['id']}/proposals/"
                    f"{other_proposal['id']}/patches",
                    headers={"Idempotency-Key": "interleave-patch"},
                    json={
                        "operation": "update",
                        "title": "Buy milk and eggs",
                        "base_proposal_revision": current_proposal["revision"],
                        "expected_operation_revision": current["revision"],
                    },
                )
                assert patched.status_code == 200, patched.text
            return result

        return wrapped

    _, restore = _patch_service_task_port(api_client, wrapper_factory)
    try:
        confirmed = _confirm(api_client, operation, frozen, "confirm-interleave-patch")
    finally:
        restore()

    assert confirmed.status_code >= 400, confirmed.text
    assert calls["n"] == 1, "the second action must never reach TaskPort"

    final = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert final["status"] != "completed"
    # The batch this confirm targeted must never reach "committed".
    assert final.get("committed_proposal_batch") is None or (
        final["committed_proposal_batch"]["id"] != active_batch["id"]
    )

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert len(inbox["items"]) == 1


def test_canonical_confirm_and_legacy_commit_share_source_action_identity(
    api_client,
) -> None:
    """A crash after canonical Task persistence but before this operation's
    own receipt/attempt write, followed by a legacy ``/commit`` retry, must
    resolve to the exact same Task instead of creating a duplicate for the
    same proposal."""

    operation = _reconciled_operation(
        api_client, "confirm-shared-identity", b"Buy milk."
    )
    frozen = _freeze(api_client, operation, "freeze-shared-identity")
    active_batch = frozen["active_proposal_batch"]
    action = active_batch["snapshot"][0]

    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]

    # Simulate canonical confirm having durably created the Task through
    # TaskPort's permanent child key, before a crash lost this operation's
    # own started/succeeded attempt and receipt rows entirely.
    child_key = brain_dump_source_action_key(
        operation_id=operation["id"], proposal_id=action["proposal_id"]
    )
    pre_created_task = container.task_service.create_native_inbox_task(
        owner_id=owner_id,
        title=action["title"],
        source_capture_ids=[f"brain_dump:{operation['id']}:{action['proposal_id']}"],
        idempotency_key=child_key,
    )

    committed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-shared-identity"},
        json={"expected_revision": frozen["revision"]},
    )
    assert committed.status_code == 200, committed.text
    body = committed.json()
    assert body["committed_task_ids"] == [pre_created_task.id]

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    matching = [item for item in inbox["items"] if item["id"] == pre_created_task.id]
    assert len(matching) == 1


def test_confirm_records_terminal_failure_without_masking_partial_success(
    api_client,
) -> None:
    """A ``TaskPort`` failure for one action must append a terminal failed
    attempt/receipt, leave that action's folded result non-pending, and
    still record the other, independent action's success -- never silently
    dropped, never retried into a duplicate."""

    operation = _reconciled_operation(
        api_client, "confirm-partial-failure", b"Buy milk. Call the dentist."
    )
    frozen = _freeze(api_client, operation, "freeze-partial-failure")
    active_batch = frozen["active_proposal_batch"]
    assert len(active_batch["snapshot"]) == 2

    calls = {"n": 0}

    def wrapper_factory(real_create):
        def wrapped(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RepositoryError("Simulated permanent TaskPort failure.")
            return real_create(**kwargs)

        return wrapped

    _, restore = _patch_service_task_port(api_client, wrapper_factory)
    try:
        confirmed = _confirm(api_client, operation, frozen, "confirm-partial-failure")
    finally:
        restore()

    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    # A partial failure must not silently look like full success.
    assert body["status"] != "completed"

    # The batch response projection must reflect the mixed outcome.
    active_response = body["active_proposal_batch"]
    assert active_response is not None
    assert active_response["id"] == active_batch["id"]
    assert active_response["status"] == "failed"
    statuses = sorted(result["status"] for result in active_response["results"])
    assert statuses == ["failed", "succeeded"]
    succeeded_result = next(
        r for r in active_response["results"] if r["status"] == "succeeded"
    )
    failed_result = next(
        r for r in active_response["results"] if r["status"] == "failed"
    )
    assert succeeded_result["result_task_id"] is not None
    assert failed_result["result_task_id"] is None

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert len(inbox["items"]) == 1

    # Idempotent replay of the exact same command returns the same result
    # rather than re-attempting the failed action or creating a duplicate.
    replay = _confirm(api_client, operation, frozen, "confirm-partial-failure")
    assert replay.status_code == 200, replay.text
    assert replay.json()["committed_task_ids"] == body["committed_task_ids"]
    inbox_after_replay = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert len(inbox_after_replay["items"]) == 1
