"""Regression coverage for persisted voice-operation ownership and recovery paths."""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from shutil import rmtree

import pytest

from app.core.config import VoiceAudioLimits
from app.exceptions import NotFoundError, RepositoryError
from app.modules.tasks import TaskRepository, TaskService
from app.schemas.tasks import BrainDumpOperationStartRequest
from app.utils.time import utcnow
from app.workflows.voice_brain_dump.domain import IdempotencyRecord
from app.workflows.voice_brain_dump.repository import (
    IDEMPOTENCY_RETENTION,
    OperationRepository,
)
from app.workflows.voice_brain_dump.service import VoiceBrainDumpService
from app.workflows.voice_brain_dump.task_port import InProcessTaskPort

OWNER = "voice_coverage_owner"


def _service(data_dir: Path) -> VoiceBrainDumpService:
    task_service = TaskService(TaskRepository(data_dir))
    return VoiceBrainDumpService(
        OperationRepository(data_dir),
        audio_limits=VoiceAudioLimits(
            allowed_mime_types=frozenset({"audio/x-brain-buddy-test-text"})
        ),
        task_port=InProcessTaskPort(task_service.create_native_inbox_task),
    )


def _start(
    service: VoiceBrainDumpService,
    *,
    key: str,
    external_processing_allowed: bool = False,
):
    return service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {
                "consent": {
                    "microphone": True,
                    "external_processing_allowed": external_processing_allowed,
                    "provider": "openai" if external_processing_allowed else None,
                }
            }
        ),
        owner_id=OWNER,
        idempotency_key=key,
    )


def _replace_operation_payload(
    repository: OperationRepository, payload: dict[str, object]
) -> None:
    with sqlite3.connect(repository.db_path) as conn:
        conn.execute(
            "DELETE FROM brain_dump_operations WHERE owner_id = ? AND id = ?",
            (OWNER, payload["id"]),
        )
        conn.execute(
            """
            INSERT INTO brain_dump_operations (owner_id, id, status, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                OWNER,
                payload["id"],
                payload["status"],
                payload["updated_at"],
                json.dumps(payload),
            ),
        )


def _legacy_payload(service: VoiceBrainDumpService, *, key: str) -> dict[str, object]:
    operation = _start(service, key=key)
    payload = operation.model_dump(mode="json")
    payload["schema_version"] = 1
    return payload


def test_startup_migrates_legacy_voice_json_before_loading_owner_operation(
    data_dir: Path,
) -> None:
    """A v1 JSON operation present before SQLite startup is imported once and
    exposed as the v2 preview-only projection required by the workflow contract."""

    legacy_data_dir = data_dir / "legacy-startup"
    bootstrap_service = _service(legacy_data_dir)
    payload = _legacy_payload(bootstrap_service, key="legacy-startup")
    operation_path = (
        legacy_data_dir / "brain-dump-operations" / OWNER / f"{payload['id']}.json"
    )
    operation_path.write_text(json.dumps(payload), encoding="utf-8")
    bootstrap_service.operation_repo.db_path.unlink()

    repository = OperationRepository(legacy_data_dir)
    migrated = repository.get_brain_dump_operation_for_owner(
        str(payload["id"]), owner_id=OWNER
    )

    assert migrated.schema_version == 2
    assert migrated.legacy_import == "legacy_preview_only"
    with sqlite3.connect(repository.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM migration_ledger").fetchone()[0] == 1


def test_voice_operation_repository_rejects_boolean_schema_version(
    data_dir: Path,
) -> None:
    """A JSON boolean cannot masquerade as a supported schema-version integer."""

    service = _service(data_dir)
    repository = service.operation_repo
    payload = _legacy_payload(service, key="boolean-schema-version")
    payload["schema_version"] = True
    _replace_operation_payload(repository, payload)

    with pytest.raises(RepositoryError, match="schema version must be an integer"):
        repository.get_brain_dump_operation_for_owner(
            str(payload["id"]), owner_id=OWNER
        )


def test_voice_operation_repository_rejects_absent_owner_scoped_audio(
    data_dir: Path,
) -> None:
    """Audio assembly fails closed rather than reading a similarly named chunk
    from another operation or owner path."""

    repository = OperationRepository(data_dir)

    with pytest.raises(NotFoundError, match="Brain dump audio chunk"):
        repository.load_brain_dump_audio_chunks(
            owner_id=OWNER,
            operation_id="operation-with-no-audio",
            chunks=[(0, "a" * 64)],
        )


def test_voice_operation_repository_purges_only_untracked_media(data_dir: Path) -> None:
    """The media orphan sweep preserves an owned recorded chunk while deleting
    loose files, an unknown operation directory, and untracked media."""

    service = _service(data_dir)
    repository = service.operation_repo
    operation = _start(service, key="orphan-media", external_processing_allowed=True)
    content = b"known-owner-audio"
    service.upload_brain_dump_audio_chunk(
        operation.id,
        0,
        content,
        owner_id=OWNER,
        content_sha256=sha256(content).hexdigest(),
        content_type="audio/x-brain-buddy-test-text",
    )
    persisted = repository.get_brain_dump_operation_for_owner(
        operation.id, owner_id=OWNER
    )
    known_chunk = persisted.audio_chunks[0]
    known_path = repository.brain_dump_audio_chunk_path(
        OWNER, operation.id, known_chunk.chunk_number, known_chunk.sha256
    )
    root = repository.resolve("brain-dump-media")
    owner_path = root / OWNER
    (root / "stray-owner-file").write_bytes(b"stray")
    (owner_path / "stray-operation-file").write_bytes(b"stray")
    unknown_operation = owner_path / "operation-not-in-database"
    unknown_operation.mkdir()
    (unknown_operation / "chunk.bin").write_bytes(b"stray")
    (known_path.parent / "untracked.bin").write_bytes(b"stray")

    assert repository.purge_brain_dump_media_orphans() == 4
    assert known_path.read_bytes() == content
    assert not (root / "stray-owner-file").exists()
    assert not (owner_path / "stray-operation-file").exists()
    assert not unknown_operation.exists()
    assert not (known_path.parent / "untracked.bin").exists()

    rmtree(root)
    assert repository.purge_brain_dump_media_orphans() == 0


def test_voice_operation_repository_purges_stale_idempotency_rows_and_files(
    data_dir: Path,
) -> None:
    """Retention removes matching owner-scoped SQLite and compatibility records,
    while an owner without history remains a no-op."""

    repository = OperationRepository(data_dir)
    now = utcnow()
    assert repository.purge_expired_idempotency(owner_id=OWNER, now=now) == 0
    stale = IdempotencyRecord(
        key="voice-stale-idempotency",
        command="voice_command",
        request_hash="request",
        resource_id="operation",
        response_body={"safe": True},
        created_at=now - IDEMPOTENCY_RETENTION - timedelta(seconds=1),
    )
    repository.save_idempotency(owner_id=OWNER, record=stale)
    compatibility_path = repository.idempotency_path(OWNER, stale.key)
    assert compatibility_path.exists()

    assert repository.purge_expired_idempotency(owner_id=OWNER, now=now) == 1
    assert repository.get_idempotency(owner_id=OWNER, key=stale.key) is None
    assert not compatibility_path.exists()


def test_migration_reader_uses_concurrently_persisted_v2_record(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reader waiting on the owner lock returns the concurrent v2 migration
    instead of overwriting it with its stale v1 decode."""

    service = _service(data_dir)
    repository = service.operation_repo
    payload = _legacy_payload(service, key="concurrent-migration")
    _replace_operation_payload(repository, payload)
    migrated, requires_persist = repository._decode_brain_dump_operation(payload)
    assert requires_persist is True
    original_load = repository._load_brain_dump_operation
    calls = 0

    def load_with_concurrent_migration(operation_id: str, *, owner_id: str):
        nonlocal calls
        calls += 1
        if calls == 2:
            repository.save_brain_dump_operation(migrated)
        return original_load(operation_id, owner_id=owner_id)

    monkeypatch.setattr(
        repository, "_load_brain_dump_operation", load_with_concurrent_migration
    )

    assert (
        repository.get_brain_dump_operation_for_owner(
            str(payload["id"]), owner_id=OWNER
        )
        == migrated
    )


def test_active_owner_transaction_persists_legacy_migration_without_relocking(
    data_dir: Path,
) -> None:
    """A command already holding the owner transaction can materialize its v1
    read directly, avoiding a nested lock while retaining the migrated v2 record."""

    service = _service(data_dir)
    repository = service.operation_repo
    payload = _legacy_payload(service, key="nested-migration")
    _replace_operation_payload(repository, payload)

    with repository.command_lock(OWNER):
        migrated = repository.get_brain_dump_operation_for_owner(
            str(payload["id"]), owner_id=OWNER
        )

    assert migrated.schema_version == 2
    assert migrated.legacy_import == "legacy_preview_only"


def test_migration_reader_reports_concurrent_operation_delete(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A delete between migration reads becomes not-found and never recreates
    the operation from an obsolete owner-scoped JSON snapshot."""

    service = _service(data_dir)
    repository = service.operation_repo
    payload = _legacy_payload(service, key="concurrent-delete")
    operation_id = str(payload["id"])
    _replace_operation_payload(repository, payload)
    original_load = repository._load_brain_dump_operation
    calls = 0

    def load_with_concurrent_delete(current_id: str, *, owner_id: str):
        nonlocal calls
        calls += 1
        if calls == 2:
            # A concurrent owner-serialized delete has already removed the row
            # before this reader's locked re-check executes.
            return None
        return original_load(current_id, owner_id=owner_id)

    monkeypatch.setattr(
        repository, "_load_brain_dump_operation", load_with_concurrent_delete
    )

    with pytest.raises(NotFoundError, match="Brain dump operation"):
        repository.get_brain_dump_operation_for_owner(operation_id, owner_id=OWNER)
