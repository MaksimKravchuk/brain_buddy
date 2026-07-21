"""Canonical raw-audio retention and delete-now tests (T059).

Covers: owner scoping, idempotent replay, persistence/physical chunk
cleanup across a simulated process restart, preserved Tasks/action
receipts/non-audio provenance after delete-now, and durable
``deletion_pending`` before any physical unlink -- with the startup sweep
converging a crash between the two phases -- for delete-now, consent
withdrawal, and cancel.
"""

from __future__ import annotations

import hashlib

import pytest

from app.schemas.tasks import BrainDumpConsentDecisionRequest, ExpectedRevisionRequest
from app.workflows.voice_brain_dump.repository import OperationRepository
from tests.test_brain_dump_operations_api import _start_operation, _upload_and_seal


def _reconciled_operation(api_client, key: str, audio: bytes) -> dict[str, object]:
    operation = _start_operation(api_client, key=f"start-{key}")
    sealed = _upload_and_seal(api_client, operation, audio, f"seal-{key}")
    body = sealed.json()
    assert body["status"] == "awaiting_confirmation", body
    return body


def _delete_now(api_client, operation: dict[str, object], key: str):
    return api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/audio/delete",
        headers={"Idempotency-Key": key},
        json={"expected_operation_revision": operation["revision"]},
    )


def test_raw_audio_is_retained_and_delete_now_available_after_reconciliation(
    api_client,
) -> None:
    operation = _reconciled_operation(api_client, "retention-projection", b"Buy milk.")
    raw_audio = operation["raw_audio"]
    assert raw_audio["state"] == "retained"
    assert raw_audio["retained_until"] is not None
    assert raw_audio["delete_now_available"] is True
    assert raw_audio["deleted_at"] is None


def test_delete_now_is_owner_scoped(second_api_client) -> None:
    client_a, client_b = second_api_client
    operation = _reconciled_operation(client_a, "retention-owner", b"Buy milk.")

    as_b = _delete_now(client_b, operation, "delete-owner-b")
    assert as_b.status_code == 404, as_b.text

    as_a = _delete_now(client_a, operation, "delete-owner-a")
    assert as_a.status_code == 200, as_a.text


def test_delete_now_is_idempotent_on_replay(api_client) -> None:
    operation = _reconciled_operation(api_client, "retention-replay", b"Buy milk.")

    first = _delete_now(api_client, operation, "delete-replay-key")
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["raw_audio"]["state"] == "deleted"
    assert first_body["raw_audio"]["deleted_at"] is not None

    second = _delete_now(api_client, operation, "delete-replay-key")
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert (
        second_body["raw_audio"]["deleted_at"] == first_body["raw_audio"]["deleted_at"]
    )
    assert second_body["revision"] == first_body["revision"]

    # A fresh parent key after the operation is already deleted converges to
    # the same terminal projection instead of requiring the original key.
    new_key = _delete_now(api_client, second_body, "delete-replay-after-terminal")
    assert new_key.status_code == 200, new_key.text
    assert new_key.json()["raw_audio"]["state"] == "deleted"


def test_delete_now_refuses_recording_operation_before_review_stage(api_client) -> None:
    """Delete-now is intentionally unavailable while recording remains active."""

    operation = _start_operation(api_client, key="start-delete-recording-guard")
    audio = b"recording audio"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text

    deleted = _delete_now(api_client, uploaded.json(), "delete-recording-guard")
    assert deleted.status_code == 400, deleted.text
    assert "AUDIO_DELETE_NOT_AVAILABLE" in deleted.text


def test_delete_now_physically_removes_chunks_and_survives_restart(
    api_client,
) -> None:
    audio = b"Buy milk."
    operation = _reconciled_operation(api_client, "retention-restart", audio)
    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container

    chunk_path = container.voice_operation_repo.brain_dump_audio_chunk_path(
        owner_id, operation["id"], 0, hashlib.sha256(audio).hexdigest()
    )
    assert chunk_path.exists()

    deleted = _delete_now(api_client, operation, "delete-restart")
    assert deleted.status_code == 200, deleted.text
    assert not chunk_path.exists()

    # Simulate a process restart: a brand-new repository instance pointed at
    # the same data directory must observe the same persisted deleted state,
    # not an in-memory-only result.
    restarted_repo = OperationRepository(container.voice_operation_repo.root)
    reloaded = restarted_repo.get_brain_dump_operation_for_owner(
        operation["id"], owner_id=owner_id
    )
    assert reloaded.raw_audio_state == "deleted"
    assert reloaded.raw_audio_deleted_at is not None
    assert reloaded.audio_chunks == []
    assert reloaded.media_ref is None

    replay_after_restart = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/audio/delete",
        headers={"Idempotency-Key": "delete-restart"},
        json={"expected_operation_revision": operation["revision"]},
    )
    assert replay_after_restart.status_code == 200, replay_after_restart.text
    assert replay_after_restart.json()["raw_audio"]["state"] == "deleted"


def test_delete_now_preserves_tasks_receipts_and_non_audio_provenance(
    api_client,
) -> None:
    operation = _reconciled_operation(api_client, "retention-provenance", b"Buy milk.")
    proposal_ids = [p["id"] for p in operation["proposals"] if not p["deleted"]]

    frozen = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/proposal-batches",
        headers={"Idempotency-Key": "freeze-retention-provenance"},
        json={
            "based_on_proposal_revision": operation["proposal_revision"],
            "expected_operation_revision": operation["revision"],
            "selected_proposal_ids": proposal_ids,
        },
    )
    assert frozen.status_code == 201, frozen.text
    frozen_body = frozen.json()
    active_batch = frozen_body["active_proposal_batch"]

    confirmed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/confirm",
        headers={"Idempotency-Key": "confirm-retention-provenance"},
        json={
            "proposal_batch_id": active_batch["id"],
            "expected_batch_revision": active_batch["revision"],
            "expected_operation_revision": frozen_body["revision"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_body = confirmed.json()
    committed_task_ids = confirmed_body["committed_task_ids"]
    action_receipts = confirmed_body["action_receipts"]
    assert committed_task_ids
    assert action_receipts

    deleted = _delete_now(api_client, confirmed_body, "delete-after-confirm")
    assert deleted.status_code == 200, deleted.text
    deleted_body = deleted.json()

    assert deleted_body["raw_audio"]["state"] == "deleted"
    assert deleted_body["audio_chunks"] == []
    assert deleted_body["media_ref"] is None
    # Confirmed Tasks, receipts, and the committed batch's action snapshot
    # are non-audio provenance and must never be removed by audio delete.
    assert deleted_body["committed_task_ids"] == committed_task_ids
    assert deleted_body["action_receipts"] == action_receipts
    assert (
        deleted_body["committed_proposal_batch"]["snapshot"] == active_batch["snapshot"]
    )

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert [item["title"] for item in inbox["items"]] == ["Buy milk"]


def test_accurate_reconciliation_unavailable_once_raw_audio_is_gone(
    api_client,
) -> None:
    """Once raw audio is pending deletion or deleted, a retry can no longer
    read the sealed original audio accurate STT requires -- the projection
    must say so even though this operation was never a legacy import."""

    operation = _reconciled_operation(
        api_client, "retention-availability", b"Buy milk."
    )
    assert operation["accurate_reconciliation_available"] is True

    deleted = _delete_now(api_client, operation, "delete-availability")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["accurate_reconciliation_available"] is False


def test_startup_sweep_drains_operation_stranded_in_deletion_pending(
    api_client,
) -> None:
    """A crash between the two persisted phases of raw-audio deletion (state
    written as ``deletion_pending``, physical cleanup/terminal ``deleted``
    never persisted) must not require a fresh user ``audio/delete`` call --
    the same sweep that recovers provider leases drains it to ``deleted``."""

    operation = _reconciled_operation(api_client, "retention-drain", b"Buy milk.")
    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    voice_service = container.voice_brain_dump_service

    stranded = voice_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    pending = stranded.model_copy(
        update={
            "raw_audio_state": "deletion_pending",
            "revision": stranded.revision + 1,
        }
    )
    container.voice_operation_repo.save_brain_dump_operation(pending)
    chunk_path = container.voice_operation_repo.brain_dump_audio_chunk_path(
        owner_id, operation["id"], 0, hashlib.sha256(b"Buy milk.").hexdigest()
    )
    assert chunk_path.exists()

    drained = voice_service.drain_pending_raw_audio_deletions()
    assert drained == 1
    assert not chunk_path.exists()

    recovered = voice_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    assert recovered.raw_audio_state == "deleted"
    assert recovered.raw_audio_deleted_at is not None

    # Idempotent: nothing left to drain on a second pass.
    assert voice_service.drain_pending_raw_audio_deletions() == 0


def test_startup_sweep_skips_a_pending_scan_entry_already_completed(
    api_client, monkeypatch
) -> None:
    """The sweep rechecks state under the owner lock so a stale scan row
    cannot cause a second physical deletion after another worker completed it."""

    operation = _reconciled_operation(api_client, "retention-drain-stale", b"Buy tea.")
    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    voice_service = container.voice_brain_dump_service
    current = voice_service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    stale_scan_entry = current.model_copy(update={"raw_audio_state": "deletion_pending"})
    monkeypatch.setattr(
        container.voice_operation_repo,
        "list_deletion_pending_raw_audio_operations",
        lambda: [stale_scan_entry],
    )

    assert voice_service.drain_pending_raw_audio_deletions() == 0
    assert (
        voice_service.get_brain_dump_operation(operation["id"], owner_id=owner_id).raw_audio_state
        == "retained"
    )


def _crash_before_unlink(monkeypatch, container):
    """Simulate a process crash after ``deletion_pending`` is durably
    committed (phase 1) but before the physical unlink runs (phase 2):
    raise before the real ``delete_brain_dump_audio_chunks`` ever executes,
    so no bytes are removed yet."""

    real_delete = container.voice_operation_repo.delete_brain_dump_audio_chunks

    def crashing_delete(*args, **kwargs):
        raise RuntimeError("simulated crash before physical unlink")

    monkeypatch.setattr(
        container.voice_operation_repo,
        "delete_brain_dump_audio_chunks",
        crashing_delete,
    )
    return real_delete


def test_consent_withdrawal_persists_deletion_pending_before_unlink_and_sweep_converges(
    api_client, monkeypatch
) -> None:
    """Consent withdrawal must durably commit ``deletion_pending`` before any
    physical unlink. A crash between that commit and the unlink must leave
    the chunk bytes intact and the record accurately ``deletion_pending``
    (never a state/bytes mismatch); the startup sweep then converges it to
    ``deleted`` without a fresh user command."""

    audio = b"Buy milk."
    operation = _reconciled_operation(api_client, "withdraw-crash", audio)
    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    voice_service = container.voice_brain_dump_service
    chunk_path = container.voice_operation_repo.brain_dump_audio_chunk_path(
        owner_id, operation["id"], 0, hashlib.sha256(audio).hexdigest()
    )
    assert chunk_path.exists()

    _crash_before_unlink(monkeypatch, container)
    with pytest.raises(RuntimeError):
        voice_service.record_brain_dump_consent_decision(
            operation["id"],
            BrainDumpConsentDecisionRequest(
                decision="withdraw",
                expected_operation_revision=operation["revision"],
            ),
            owner_id=owner_id,
            idempotency_key="withdraw-crash-key",
        )
    monkeypatch.undo()

    # Phase 1 landed durably; physical bytes are untouched because the
    # crash happened before the unlink -- never "state says deleted while
    # bytes still linger" or "bytes gone while state still says retained".
    stranded = voice_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    assert stranded.raw_audio_state == "deletion_pending"
    assert stranded.consent.status == "withdrawn"
    assert chunk_path.exists()

    drained = voice_service.drain_pending_raw_audio_deletions()
    assert drained == 1
    assert not chunk_path.exists()
    recovered = voice_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    assert recovered.raw_audio_state == "deleted"
    assert recovered.raw_audio_deleted_at is not None


def test_cancel_persists_deletion_pending_before_unlink_and_sweep_converges(
    api_client, monkeypatch
) -> None:
    """Cancelling an operation with retained audio must durably commit
    ``deletion_pending`` before any physical unlink, exactly like delete-now
    and consent withdrawal. A crash between the two phases must not lose or
    strand the audio outside the sweep's reach."""

    audio = b"Buy milk."
    operation = _reconciled_operation(api_client, "cancel-crash", audio)
    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    voice_service = container.voice_brain_dump_service
    chunk_path = container.voice_operation_repo.brain_dump_audio_chunk_path(
        owner_id, operation["id"], 0, hashlib.sha256(audio).hexdigest()
    )
    assert chunk_path.exists()

    _crash_before_unlink(monkeypatch, container)
    with pytest.raises(RuntimeError):
        voice_service.transition_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=operation["revision"]),
            owner_id=owner_id,
            idempotency_key="cancel-crash-key",
            action="cancel",
        )
    monkeypatch.undo()

    stranded = voice_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    assert stranded.status == "cancelled"
    assert stranded.raw_audio_state == "deletion_pending"
    assert chunk_path.exists()

    drained = voice_service.drain_pending_raw_audio_deletions()
    assert drained == 1
    assert not chunk_path.exists()
    recovered = voice_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    assert recovered.raw_audio_state == "deleted"


def test_delete_now_persists_deletion_pending_before_unlink_and_sweep_converges(
    api_client, monkeypatch
) -> None:
    """The explicit delete-now command must also leave a durably-committed
    ``deletion_pending`` record if the physical unlink itself crashes, so
    the sweep -- not a repeated user call -- is what converges it."""

    audio = b"Buy milk."
    operation = _reconciled_operation(api_client, "delete-now-crash", audio)
    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    voice_service = container.voice_brain_dump_service
    chunk_path = container.voice_operation_repo.brain_dump_audio_chunk_path(
        owner_id, operation["id"], 0, hashlib.sha256(audio).hexdigest()
    )
    assert chunk_path.exists()

    _crash_before_unlink(monkeypatch, container)
    with pytest.raises(RuntimeError):
        voice_service.delete_brain_dump_raw_audio(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=operation["revision"]),
            owner_id=owner_id,
            idempotency_key="delete-now-crash-key",
        )
    monkeypatch.undo()

    stranded = voice_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    assert stranded.raw_audio_state == "deletion_pending"
    assert chunk_path.exists()

    drained = voice_service.drain_pending_raw_audio_deletions()
    assert drained == 1
    assert not chunk_path.exists()
    recovered = voice_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    assert recovered.raw_audio_state == "deleted"
