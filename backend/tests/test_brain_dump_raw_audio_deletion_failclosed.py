"""Raw-audio deletion must fail closed (final0729 review).

The architecture-consistency review found raw-audio deletion fail-open: the
repository suppressed every filesystem error, after which the retention,
withdrawal, and explicit-delete paths cleared the audio metadata and reported
success -- leaving bytes on disk with no retry state while the API claimed the
audio was gone.

These tests pin the fail-closed contract: a failed deletion never clears the
metadata that makes the bytes findable (``raw_audio_present`` stays honestly
True), the operation stays eligible for the retention sweep, and the sweep
retries until absence is confirmed before any metadata is cleared -- including
partial-directory failures.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path

from app.workflows.voice_brain_dump import repository as repository_module
from tests.test_brain_dump_operations_api import _start_operation, _upload_and_seal


class _ControllableRmtree:
    """Stand-in for ``shutil.rmtree`` whose failure mode is toggled per test."""

    def __init__(self, real) -> None:
        self._real = real
        self.mode = "fail"  # "fail" | "partial" | "ok"

    def __call__(self, path, *args, **kwargs):
        directory = Path(path)
        if self.mode == "ok":
            return self._real(path, *args, **kwargs)
        if self.mode == "partial" and directory.exists():
            # Delete all but one media file: a real partial-directory failure.
            for leftover in sorted(directory.glob("*.bin"))[1:]:
                leftover.unlink()
            return None
        # "fail": suppress the delete entirely, leaving every byte on disk.
        return None


def _reconciled_with_audio(api_client, key_prefix: str):
    """Drive one operation to awaiting_confirmation with raw audio on disk."""

    operation = _start_operation(api_client, key=f"{key_prefix}-start")
    audio = b"private raw audio that must actually be deleted"
    sealed = _upload_and_seal(api_client, operation, audio, f"{key_prefix}-seal").json()
    assert sealed["status"] == "awaiting_confirmation"
    assert sealed["raw_audio_present"] is True
    return operation, sealed, audio


def _chunk_path(api_client, operation, audio: bytes) -> Path:
    owner_id = api_client.get("/api/auth/me").json()["id"]
    repository = api_client.app.state.container.voice_operation_repo
    return repository.brain_dump_audio_chunk_path(
        owner_id, operation["id"], 0, hashlib.sha256(audio).hexdigest()
    )


def _make_expired(api_client, operation_id: str) -> None:
    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]
    persisted = container.voice_brain_dump_service.get_brain_dump_operation(
        operation_id, owner_id=owner_id
    )
    assert persisted.raw_audio_expires_at is not None
    container.voice_operation_repo.save_brain_dump_operation(
        persisted.model_copy(
            update={
                "raw_audio_expires_at": persisted.raw_audio_expires_at
                - timedelta(days=2)
            }
        )
    )


def test_retention_sweep_deletion_failure_retains_metadata_then_retries(
    api_client, monkeypatch
) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    operation, _sealed, audio = _reconciled_with_audio(api_client, "sweep-failclosed")
    chunk_path = _chunk_path(api_client, operation, audio)
    assert chunk_path.exists()
    _make_expired(api_client, operation["id"])

    rmtree = _ControllableRmtree(repository_module.shutil.rmtree)
    monkeypatch.setattr(repository_module.shutil, "rmtree", rmtree)

    # A failed deletion must purge nothing and clear no metadata.
    assert service.purge_expired_raw_audio() == 0
    reloaded = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert reloaded["raw_audio_present"] is True
    assert reloaded["audio_chunks"], "metadata must survive a failed deletion"
    assert reloaded["media_ref"] is not None
    assert chunk_path.exists(), "bytes must remain findable, not orphaned"

    # The operation is still sweep-eligible: a later sweep that succeeds clears
    # the metadata only after absence is confirmed on disk.
    rmtree.mode = "ok"
    assert service.purge_expired_raw_audio() == 1
    swept = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert swept["raw_audio_present"] is False
    assert swept["audio_chunks"] == []
    assert swept["media_ref"] is None
    assert not chunk_path.exists()


def test_partial_directory_deletion_is_treated_as_failure(
    api_client, monkeypatch
) -> None:
    """One surviving media file means the deletion failed: keep the metadata."""

    service = api_client.app.state.container.voice_brain_dump_service
    operation = _start_operation(api_client, key="partial-failclosed-start")
    audio_a = b"first private chunk"
    audio_b = b"second private chunk that survives the partial failure"
    for index, audio in enumerate((audio_a, audio_b)):
        uploaded = api_client.put(
            f"/api/brain-dump-operations/{operation['id']}/audio/{index}",
            content=audio,
            headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
        )
        assert uploaded.status_code == 200, uploaded.text
    revision = uploaded.json()["revision"]

    rmtree = _ControllableRmtree(repository_module.shutil.rmtree)
    rmtree.mode = "partial"
    monkeypatch.setattr(repository_module.shutil, "rmtree", rmtree)

    # Cancel deletes raw audio; a partial failure must not report success.
    cancelled = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/cancel",
        headers={"Idempotency-Key": "partial-failclosed-cancel"},
        json={"expected_revision": revision},
    )
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["status"] == "cancelled"
    assert body["raw_audio_present"] is True, "partial deletion is not success"
    assert body["audio_chunks"], "metadata retained until every byte is gone"

    # The retention sweep retries and, once deletion fully succeeds, clears it.
    rmtree.mode = "ok"
    assert service.purge_expired_raw_audio() == 1
    swept = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert swept["raw_audio_present"] is False
    assert swept["audio_chunks"] == []


def test_explicit_delete_failure_is_fail_closed_and_retried(
    api_client, monkeypatch
) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    operation, sealed, audio = _reconciled_with_audio(api_client, "explicit-failclosed")
    chunk_path = _chunk_path(api_client, operation, audio)

    rmtree = _ControllableRmtree(repository_module.shutil.rmtree)
    monkeypatch.setattr(repository_module.shutil, "rmtree", rmtree)

    deleted = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/delete_raw_audio",
        headers={"Idempotency-Key": "explicit-failclosed-delete"},
        json={"expected_revision": sealed["revision"]},
    )
    # The command does not lie: the audio is still present because it is on disk.
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["raw_audio_present"] is True
    assert deleted.json()["audio_chunks"]
    assert chunk_path.exists()

    # The operation is now due; a successful retention sweep confirms absence.
    rmtree.mode = "ok"
    assert service.purge_expired_raw_audio() == 1
    swept = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert swept["raw_audio_present"] is False
    assert not chunk_path.exists()


def test_withdrawal_deletion_failure_keeps_audio_findable(
    api_client, monkeypatch
) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    operation, sealed, audio = _reconciled_with_audio(api_client, "withdraw-failclosed")
    chunk_path = _chunk_path(api_client, operation, audio)

    rmtree = _ControllableRmtree(repository_module.shutil.rmtree)
    monkeypatch.setattr(repository_module.shutil, "rmtree", rmtree)

    withdrawn = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/withdraw_consent",
        headers={"Idempotency-Key": "withdraw-failclosed-consent"},
        json={"expected_revision": sealed["revision"]},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    body = withdrawn.json()
    # Consent is still withdrawn (that effect must not be lost) ...
    assert body["consent"]["external_processing_allowed"] is False
    # ... but the audio is NOT falsely reported gone while bytes remain on disk.
    assert body["raw_audio_present"] is True
    assert body["audio_chunks"]
    assert chunk_path.exists()

    rmtree.mode = "ok"
    assert service.purge_expired_raw_audio() == 1
    swept = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert swept["raw_audio_present"] is False
    assert not chunk_path.exists()


def test_repository_delete_reports_verified_absence(api_client) -> None:
    """The repository returns True only when no raw-audio bytes remain."""

    operation, _sealed, audio = _reconciled_with_audio(api_client, "repo-verify")
    owner_id = api_client.get("/api/auth/me").json()["id"]
    repository = api_client.app.state.container.voice_operation_repo
    chunks = [(0, hashlib.sha256(audio).hexdigest())]

    deleted = repository.delete_brain_dump_audio_chunks(
        owner_id=owner_id, operation_id=operation["id"], chunks=chunks
    )
    assert deleted is True
    # A no-op delete of already-absent media is still a verified success.
    again = repository.delete_brain_dump_audio_chunks(
        owner_id=owner_id, operation_id=operation["id"], chunks=chunks
    )
    assert again is True
