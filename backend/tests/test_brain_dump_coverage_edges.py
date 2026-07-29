"""Branch-coverage edge legs for the voice hardening rounds.

Targeted tests for error/edge branch arms in the newest voice code -- the commit
saga recovery driver, the working-artifact purge/scrub, the runner gate, and
idempotency conflict handling -- that the happy-path tests do not exercise.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.exceptions import ConflictError
from app.schemas.tasks import ExpectedRevisionRequest
from tests.test_brain_dump_commit_ledger import (
    _drive_to_awaiting,
    _FaultyTaskPort,
    _owner_id,
)
from tests.test_brain_dump_operations_api import _manifest_hash, _start_operation


def _stuck_committing(api_client, key_prefix: str):
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, key_prefix)
    service.task_port = _FaultyTaskPort(service.task_port, fail_on_call=2)
    with pytest.raises(RuntimeError, match="TASKPORT_FAULT"):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key=f"{key_prefix}-commit",
        )
    return service, owner_id, operation["id"]


def test_recover_committing_respects_limit(api_client) -> None:
    service, _owner_id_, _op = _stuck_committing(api_client, "edge-limit")
    # limit=0: the loop breaks before advancing any candidate.
    assert service.recover_committing_operations(limit=0) == 0


def test_recover_committing_skips_uncommittable_operation(api_client) -> None:
    service, owner_id, op_id = _stuck_committing(api_client, "edge-uncommittable")
    # A committing operation whose frozen batch is gone can no longer begin a
    # commit: begin-commit raises and the driver treats it as a safe no-op.
    persisted = service.get_brain_dump_operation(op_id, owner_id=owner_id)
    service.operation_repo.save_brain_dump_operation(
        persisted.model_copy(update={"commit_batch": None})
    )
    service.task_port = service.task_port._inner  # heal the injected fault
    assert service.recover_committing_operations() == 0
    assert (
        service.get_brain_dump_operation(op_id, owner_id=owner_id).status
        == "committing"
    )


def test_purge_finalizes_committing_op_that_has_no_segments(api_client) -> None:
    service, owner_id, op_id = _stuck_committing(api_client, "edge-noseg")
    persisted = service.get_brain_dump_operation(op_id, owner_id=owner_id)
    anchor = persisted.working_artifacts_expires_at or persisted.updated_at
    service.operation_repo.save_brain_dump_operation(
        persisted.model_copy(
            update={
                "segments": [],
                "working_artifacts_expires_at": anchor - timedelta(days=14),
            }
        )
    )
    assert service.purge_expired_working_artifacts() >= 1
    finalized = service.get_brain_dump_operation(op_id, owner_id=owner_id)
    assert finalized.status == "cancelled"
    assert finalized.segment_content_hashes == []


def test_purge_hashes_segment_without_a_precomputed_hash(api_client) -> None:
    import hashlib

    service, owner_id, op_id = _stuck_committing(api_client, "edge-fallbackhash")
    persisted = service.get_brain_dump_operation(op_id, owner_id=owner_id)
    assert persisted.segments
    # Simulate a pre-existing segment written before content_sha256 existed.
    stripped = [
        s.model_copy(update={"content_sha256": None}) for s in persisted.segments
    ]
    anchor = persisted.working_artifacts_expires_at or persisted.updated_at
    service.operation_repo.save_brain_dump_operation(
        persisted.model_copy(
            update={
                "segments": stripped,
                "working_artifacts_expires_at": anchor - timedelta(days=14),
            }
        )
    )
    assert service.purge_expired_working_artifacts() >= 1
    swept = service.get_brain_dump_operation(op_id, owner_id=owner_id)
    survived = {h.id: h.content_sha256 for h in swept.segment_content_hashes}
    expected = {
        s.id: hashlib.sha256(s.text.encode("utf-8")).hexdigest() for s in stripped
    }
    assert survived == expected


def test_commit_idempotency_key_conflicts_on_divergent_request(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "edge-idem-conflict")
    service.commit_brain_dump_operation(
        operation["id"],
        ExpectedRevisionRequest(expected_revision=finished["revision"]),
        owner_id=owner_id,
        idempotency_key="edge-idem-conflict-key",
    )
    # Same key, different request body (expected_revision) -> conflict.
    with pytest.raises(ConflictError):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"] + 999),
            owner_id=owner_id,
            idempotency_key="edge-idem-conflict-key",
        )


def test_runner_skips_in_flight_operation_without_provider_runs(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation = _start_operation(api_client, key="edge-norun")
    persisted = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    service.operation_repo.save_brain_dump_operation(
        persisted.model_copy(
            update={"status": "accurate_transcribing", "provider_runs": []}
        )
    )
    assert service.run_due_brain_dump_provider_runs() == 0


def test_runner_skips_provider_run_that_is_not_due(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation = _start_operation(
        api_client, key="edge-notdue", external_processing_allowed=True
    )
    import hashlib

    audio = b"queued but already settled"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "edge-notdue-seal"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    persisted = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    settled_run = persisted.provider_runs[-1].model_copy(update={"status": "succeeded"})
    service.operation_repo.save_brain_dump_operation(
        persisted.model_copy(
            update={"status": "reconciling", "provider_runs": [settled_run]}
        )
    )
    # The last run is neither pending nor an expired lease: nothing is advanced.
    assert service.run_due_brain_dump_provider_runs() == 0


def test_finalize_backfills_a_missing_action_receipt(api_client) -> None:
    service, owner_id, op_id = _stuck_committing(api_client, "edge-backfill")
    # Drop the receipt written per-action so finalize must backfill it on resume.
    persisted = service.get_brain_dump_operation(op_id, owner_id=owner_id)
    assert persisted.action_receipts, "precondition: action 1 wrote a receipt"
    service.operation_repo.save_brain_dump_operation(
        persisted.model_copy(update={"action_receipts": []})
    )
    service.task_port = service.task_port._inner  # heal the injected fault
    resumed = service.commit_brain_dump_operation(
        op_id,
        ExpectedRevisionRequest(expected_revision=persisted.revision + 1),
        owner_id=owner_id,
        idempotency_key="edge-backfill-resume",
    )
    assert resumed.status == "completed"
    assert len(resumed.action_receipts) == 2


def test_voice_idempotency_repair_recreates_then_updates_operation(api_client) -> None:
    from app.utils.time import utcnow
    from app.workflows.voice_brain_dump.domain import IdempotencyRecord

    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, _finished = _drive_to_awaiting(api_client, "edge-voice-repair")
    real = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    ghost = real.model_copy(update={"id": "brain_dump_ghost"})

    def _store(key: str, doc) -> None:
        service.operation_repo.save_idempotency(
            owner_id=owner_id,
            record=IdempotencyRecord(
                key=key,
                command="brain_dump_start",
                request_hash="request-hash",
                resource_id=doc.id,
                response_body=doc.model_dump(mode="json"),
                created_at=utcnow(),
            ),
        )

    # Missing operation is recreated from the recorded snapshot.
    _store("edge-voice-ghost", ghost)
    service._reconcile_idempotent_result(owner_id=owner_id, key="edge-voice-ghost")
    assert service.get_brain_dump_operation("brain_dump_ghost", owner_id=owner_id)

    # A newer recorded snapshot is saved over the current operation.
    newer = ghost.model_copy(update={"revision": ghost.revision + 5})
    _store("edge-voice-ghost-2", newer)
    service._reconcile_idempotent_result(owner_id=owner_id, key="edge-voice-ghost-2")
    assert (
        service.get_brain_dump_operation("brain_dump_ghost", owner_id=owner_id).revision
        == newer.revision
    )


def test_review_provisional_rejects_a_non_reviewable_operation(api_client) -> None:
    from app.exceptions import ValidationFailure

    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "edge-review")
    # An awaiting-confirmation operation is not a terminal provisional failure.
    with pytest.raises(ValidationFailure):
        service.review_brain_dump_provisionally(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key="edge-review-key",
        )


def _upload_one_chunk(api_client, operation_id: str, audio: bytes):
    import hashlib

    return api_client.put(
        f"/api/brain-dump-operations/{operation_id}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )


def test_seal_rejects_manifest_over_a_lowered_chunk_count(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    operation = _start_operation(
        api_client, key="edge-seal-count", external_processing_allowed=True
    )
    audio = b"chunk under the original ceiling"
    uploaded = _upload_one_chunk(api_client, operation["id"], audio)
    # Defense in depth: a manifest assembled under a since-lowered ceiling.
    service.audio_limits = service.audio_limits.model_copy(
        update={"max_chunk_count": 0}
    )
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "edge-seal-count-seal"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 400
    assert "AUDIO_CHUNK_COUNT_EXCEEDED" in sealed.text


def test_seal_rejects_manifest_over_a_lowered_byte_ceiling(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    operation = _start_operation(
        api_client, key="edge-seal-bytes", external_processing_allowed=True
    )
    audio = b"chunk under the original byte ceiling"
    uploaded = _upload_one_chunk(api_client, operation["id"], audio)
    service.audio_limits = service.audio_limits.model_copy(
        update={"max_total_bytes": 0}
    )
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "edge-seal-bytes-seal"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 400
    assert "AUDIO_TOTAL_BYTES_EXCEEDED" in sealed.text
