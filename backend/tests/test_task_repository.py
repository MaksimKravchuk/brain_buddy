"""Robustness regression tests for the task module's SQLite persistence.

Covers idempotency-record retention and O(1) write-path lookups, translation
of raw ``sqlite3`` errors into domain exceptions, connection lifecycle during
repository construction, and the serialized legacy-JSON brain dump backfill.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest

from app.exceptions import (
    ConflictError,
    RepositoryError,
    StorageUnavailableError,
)
from app.modules.tasks import TaskRepository, TaskService
from app.modules.tasks.domain import (
    IdempotencyRecord,
    TaskDocument,
    TaskSubtaskDocument,
)
from app.modules.tasks.repository import IDEMPOTENCY_RETENTION
from app.schemas.tasks import BrainDumpOperationStartRequest, TaskCreateRequest
from app.utils.time import utcnow
from app.workflows.voice_brain_dump.domain import BrainDumpOperationDocument
from app.workflows.voice_brain_dump.repository import OperationRepository
from app.workflows.voice_brain_dump.service import VoiceBrainDumpService
from app.workflows.voice_brain_dump.task_port import InProcessTaskPort

OWNER = "user_repo_owner"


@pytest.fixture()
def repository(data_dir: Path) -> TaskRepository:
    return TaskRepository(data_dir)


@pytest.fixture()
def service(repository: TaskRepository) -> TaskService:
    return TaskService(repository)


@pytest.fixture()
def voice_repository(data_dir: Path) -> OperationRepository:
    return OperationRepository(data_dir)


@pytest.fixture()
def voice_service(
    voice_repository: OperationRepository, service: TaskService
) -> VoiceBrainDumpService:
    return VoiceBrainDumpService(
        voice_repository,
        task_port=InProcessTaskPort(service.create_native_inbox_task),
    )


def _make_task(
    service: TaskService, *, title: str = "Robustness task", key: str = "t"
) -> TaskDocument:
    return service.create_task(
        TaskCreateRequest(title=title), owner_id=OWNER, idempotency_key=key
    )


def _task_doc(task_id: str = "task_direct") -> TaskDocument:
    now = utcnow()
    return TaskDocument(
        id=task_id,
        owner_id=OWNER,
        title="Directly built task",
        state="inbox",
        order_key=0,
        created_at=now,
        updated_at=now,
    )


def _start_brain_dump(
    voice_service: VoiceBrainDumpService, *, key: str = "brain-dump-start"
) -> BrainDumpOperationDocument:
    return voice_service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": False}}
        ),
        owner_id=OWNER,
        idempotency_key=key,
    )


def _delete_brain_dump_row(repository: OperationRepository, operation_id: str) -> None:
    conn = sqlite3.connect(repository.db_path)
    try:
        conn.execute(
            "DELETE FROM brain_dump_operations WHERE owner_id = ? AND id = ?",
            (OWNER, operation_id),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_brain_dump_payload(
    repository: OperationRepository, payload: dict[str, object]
) -> None:
    conn = sqlite3.connect(repository.db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO brain_dump_operations
                (owner_id, id, status, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                payload["owner_id"],
                payload["id"],
                payload["status"],
                payload["updated_at"],
                json.dumps(payload),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _legacy_brain_dump_payload(*, status: str) -> dict[str, object]:
    now = utcnow().isoformat()
    return {
        "id": f"brain_dump_legacy_{status}",
        "owner_id": OWNER,
        "kind": "voice_brain_dump",
        "status": status,
        "consent": {
            "microphone": True,
            "external_processing_allowed": False,
            "recorded_at": now,
            "provider": None,
        },
        "segments": [
            {
                "id": "segment_legacy",
                "sequence": 1,
                "text": "Buy milk. Call Anna.",
                "stability": "stable",
                "created_at": now,
            }
        ],
        "proposals": [
            {
                "id": "proposal_edited",
                "ordinal": 1,
                "title": "Buy oat milk",
                "status": "user_edited",
                "source_segment_ids": ["segment_legacy"],
                "deleted": False,
                "user_edited": True,
                "created_at": now,
                "updated_at": now,
                "revision": 2,
            },
            {
                "id": "proposal_deleted",
                "ordinal": 2,
                "title": "Call Anna",
                "status": "provisional",
                "source_segment_ids": ["segment_legacy"],
                "deleted": True,
                "user_edited": False,
                "created_at": now,
                "updated_at": now,
                "revision": 2,
            },
        ],
        "committed_task_ids": ["task_legacy"] if status == "completed" else [],
        "created_at": now,
        "updated_at": now,
        "schema_version": 1,
        "revision": 4,
    }


# --- finding 1: O(1) idempotency lookup + retention -------------------------


def test_writes_do_not_scan_full_idempotency_history(
    service: TaskService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_task(service, key="seed-history")

    def fail_scan(**kwargs: object) -> list[IdempotencyRecord]:
        raise AssertionError("write path must not scan all idempotency records")

    monkeypatch.setattr(service.task_repo, "list_idempotency_for_owner", fail_scan)

    created = _make_task(service, key="fresh-key", title="No scan")
    replayed = _make_task(service, key="fresh-key", title="No scan")

    assert replayed == created


def test_stale_idempotency_records_are_purged_on_write(service: TaskService) -> None:
    repo = service.task_repo
    task = _make_task(service, key="fresh-record")
    stale = IdempotencyRecord(
        key="stale-record",
        command="create_task",
        request_hash="hash",
        resource_id=task.id,
        response_body=task.model_dump(mode="json"),
        created_at=utcnow() - IDEMPOTENCY_RETENTION - timedelta(minutes=1),
    )
    repo.save_idempotency(owner_id=OWNER, record=stale)
    assert repo.get_idempotency(owner_id=OWNER, key="stale-record") is not None

    _make_task(service, key="purge-trigger", title="Trigger purge")

    assert repo.get_idempotency(owner_id=OWNER, key="stale-record") is None
    assert not repo.idempotency_path(OWNER, "stale-record").exists()
    assert repo.get_idempotency(owner_id=OWNER, key="fresh-record") is not None
    assert repo.get_idempotency(owner_id=OWNER, key="purge-trigger") is not None


def test_same_key_replay_and_mismatch_semantics_survive(service: TaskService) -> None:
    created = _make_task(service, key="replay-contract", title="Same payload")

    replayed = _make_task(service, key="replay-contract", title="Same payload")
    assert replayed == created

    with pytest.raises(ConflictError):
        _make_task(service, key="replay-contract", title="Different payload")


def test_native_inbox_task_creation_survives_generic_idempotency_expiry(
    service: TaskService,
) -> None:
    """A Voice confirm retry's deterministic ``H(operation,batch,action)``
    child key must resolve to the exact same Task even after the generic,
    time-bounded ``IdempotencyRecord`` for that key has expired and been
    purged. The permanent ``native_inbox_task_sources`` row -- not the 24h
    generic record -- is what makes ``create_native_inbox_task`` exact-once
    across a crash-then-late-retry window (ADR-0002 confirmation contract)."""

    repo = service.task_repo
    key = "brain_dump_action_child_key"
    created = service.create_native_inbox_task(
        owner_id=OWNER,
        title="Call the dentist",
        source_capture_ids=["brain_dump:op_x:proposal_y"],
        idempotency_key=key,
    )

    stale_record = repo.get_idempotency(owner_id=OWNER, key=key)
    assert stale_record is not None
    repo.save_idempotency(
        owner_id=OWNER,
        record=stale_record.model_copy(
            update={
                "created_at": utcnow() - IDEMPOTENCY_RETENTION - timedelta(minutes=1)
            }
        ),
    )
    repo.purge_expired_idempotency(owner_id=OWNER, now=utcnow())
    assert repo.get_idempotency(owner_id=OWNER, key=key) is None

    retried = service.create_native_inbox_task(
        owner_id=OWNER,
        title="Call the dentist",
        source_capture_ids=["brain_dump:op_x:proposal_y"],
        idempotency_key=key,
    )

    assert retried.id == created.id
    assert len(repo.list_for_owner(owner_id=OWNER)) == 1
    assert (
        repo.get_native_inbox_task_source(owner_id=OWNER, source_key=key)
        == created.id
    )


def test_native_inbox_task_source_conflict_maps_to_domain_error(
    service: TaskService,
) -> None:
    """A concurrent duplicate insert into the permanent source table (a
    genuine race between two confirm retries) surfaces as ``ConflictError``,
    never a silently-overwritten task pointer."""

    repo = service.task_repo
    created = service.create_native_inbox_task(
        owner_id=OWNER,
        title="Buy milk",
        source_capture_ids=["brain_dump:op_x:proposal_z"],
        idempotency_key="race-key",
    )
    with pytest.raises(ConflictError):
        repo.save_native_inbox_task_source(
            owner_id=OWNER,
            source_key="race-key",
            task_id="task_other",
            created_at=utcnow(),
        )
    assert (
        repo.get_native_inbox_task_source(owner_id=OWNER, source_key="race-key")
        == created.id
    )


# --- finding 2: sqlite3 errors map to domain exceptions ---------------------


def test_duplicate_subtask_insert_maps_to_conflict(service: TaskService) -> None:
    task = _make_task(service, key="subtask-parent")
    now = utcnow()
    subtask = TaskSubtaskDocument(
        id="subtask_dup",
        owner_id=OWNER,
        task_id=task.id,
        title="Duplicate insert",
        order_key=0,
        created_at=now,
        updated_at=now,
    )
    service.task_repo.create_subtask(subtask)

    with pytest.raises(ConflictError):
        service.task_repo.create_subtask(subtask)


def test_foreign_key_violation_maps_to_conflict(service: TaskService) -> None:
    task = _make_task(service, key="fk-parent")
    dangling = task.model_copy(update={"project_id": "project_missing"})

    with pytest.raises(ConflictError):
        service.task_repo.save(dangling)


def test_operational_error_maps_to_storage_unavailable(
    repository: TaskRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(
        self: TaskRepository, conn: sqlite3.Connection, task: TaskDocument
    ) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(TaskRepository, "_upsert_task", locked)

    with pytest.raises(StorageUnavailableError):
        repository.save(_task_doc())


def test_other_sqlite_errors_map_to_repository_error(
    repository: TaskRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def corrupted(
        self: TaskRepository, conn: sqlite3.Connection, task: TaskDocument
    ) -> None:
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(TaskRepository, "_upsert_task", corrupted)

    with pytest.raises(RepositoryError) as excinfo:
        repository.save(_task_doc())
    assert not isinstance(excinfo.value, StorageUnavailableError)


def test_api_maps_locked_database_to_503_contract_response(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(
        self: TaskRepository, conn: sqlite3.Connection, task: TaskDocument
    ) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(TaskRepository, "_upsert_task", locked)

    response = api_client.post(
        "/api/tasks",
        headers={"Idempotency-Key": "locked-write"},
        json={"title": "Locked write"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["message"]
    assert response.headers.get("X-Correlation-ID")


def test_api_maps_integrity_error_to_409_contract_response(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def violated(
        self: TaskRepository, conn: sqlite3.Connection, task: TaskDocument
    ) -> None:
        raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")

    monkeypatch.setattr(TaskRepository, "_upsert_task", violated)

    response = api_client.post(
        "/api/tasks",
        headers={"Idempotency-Key": "integrity-write"},
        json={"title": "Conflicting write"},
    )

    assert response.status_code == 409
    assert response.json()["message"]


# --- finding 3: no leaked connections during construction -------------------


def test_repository_construction_closes_every_connection(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[sqlite3.Connection] = []
    original_connect = TaskRepository._connect

    def tracking_connect(self: TaskRepository) -> sqlite3.Connection:
        conn = original_connect(self)
        created.append(conn)
        return conn

    monkeypatch.setattr(TaskRepository, "_connect", tracking_connect)

    TaskRepository(data_dir)

    assert created, "expected construction to open at least one connection"
    for conn in created:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


# --- finding 4: legacy brain dump backfill is serialized --------------------


def test_brain_dump_backfill_runs_under_command_lock(
    voice_service: VoiceBrainDumpService, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = _start_brain_dump(voice_service, key="backfill-lock")
    repo = voice_service.operation_repo
    _delete_brain_dump_row(repo, operation.id)

    locks: list[str] = []
    original_lock = repo.command_lock

    @contextmanager
    def spying_lock(owner_id: str) -> Iterator[None]:
        locks.append(owner_id)
        with original_lock(owner_id):
            yield

    monkeypatch.setattr(repo, "command_lock", spying_lock)

    restored = repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER)

    assert restored == operation
    assert locks == [OWNER]

    # The backfill persisted into SQLite: reads no longer need the JSON file.
    repo.brain_dump_operation_path(OWNER, operation.id).unlink()
    assert (
        repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER)
        == operation
    )


def test_brain_dump_backfill_inside_active_command_does_not_deadlock(
    voice_service: VoiceBrainDumpService,
) -> None:
    operation = _start_brain_dump(voice_service, key="backfill-nested")
    repo = voice_service.operation_repo
    _delete_brain_dump_row(repo, operation.id)

    with repo.command_lock(OWNER):
        restored = repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER)

    assert restored == operation


def test_brain_dump_backfill_does_not_clobber_concurrent_write(
    voice_service: VoiceBrainDumpService, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = _start_brain_dump(voice_service, key="backfill-race")
    repo = voice_service.operation_repo
    newer = operation.model_copy(
        update={
            "status": "paused",
            "updated_at": utcnow(),
            "revision": operation.revision + 1,
        }
    )
    _delete_brain_dump_row(repo, operation.id)

    original_lock = repo.command_lock

    @contextmanager
    def racing_lock(owner_id: str) -> Iterator[None]:
        with original_lock(owner_id):
            # A concurrent writer lands the newer revision before the backfill
            # re-checks under the lock.
            repo.save_brain_dump_operation(newer)
            yield

    monkeypatch.setattr(repo, "command_lock", racing_lock)

    result = repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER)

    assert result == newer
    assert (
        repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER) == newer
    )


def test_active_schema_v1_operation_is_imported_once_as_legacy_preview_only(
    voice_repository: OperationRepository,
) -> None:
    payload = _legacy_brain_dump_payload(status="awaiting_confirmation")
    repository = voice_repository
    _insert_brain_dump_payload(repository, payload)

    migrated = repository.get_brain_dump_operation_for_owner(
        str(payload["id"]), owner_id=OWNER
    )

    assert migrated.schema_version == 2
    assert migrated.legacy_import == "legacy_preview_only"
    assert migrated.reconciliation_quality == "provisional_only"
    assert [segment.provider_role for segment in migrated.segments] == [
        "browser_preview"
    ]
    assert migrated.proposals[0].locked_fields == ["title"]
    assert migrated.proposals[1].deleted is True
    assert [patch.operation for patch in migrated.proposal_patches] == [
        "add",
        "add",
        "remove",
    ]
    assert [patch.producer for patch in migrated.proposal_patches] == [
        "user",
        "user",
        "user",
    ]

    first_patch_ids = [patch.id for patch in migrated.proposal_patches]
    loaded_again = repository.get_brain_dump_operation_for_owner(
        str(payload["id"]), owner_id=OWNER
    )
    assert [patch.id for patch in loaded_again.proposal_patches] == first_patch_ids

    with sqlite3.connect(repository.db_path) as conn:
        stored = json.loads(
            conn.execute(
                "SELECT payload FROM brain_dump_operations WHERE owner_id = ? AND id = ?",
                (OWNER, payload["id"]),
            ).fetchone()[0]
        )
    assert stored["schema_version"] == 2
    assert stored["legacy_import"] == "legacy_preview_only"


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_terminal_schema_v1_operation_remains_readable_and_immutable(
    voice_repository: OperationRepository, status: str
) -> None:
    repository = voice_repository
    payload = _legacy_brain_dump_payload(status=status)
    _insert_brain_dump_payload(repository, payload)

    loaded = repository.get_brain_dump_operation_for_owner(
        str(payload["id"]), owner_id=OWNER
    )

    assert loaded.schema_version == 1
    assert loaded.status == status
    assert loaded.legacy_import is None
    assert [proposal.id for proposal in loaded.proposals] == [
        "proposal_edited",
        "proposal_deleted",
    ]
    with sqlite3.connect(repository.db_path) as conn:
        stored = json.loads(
            conn.execute(
                "SELECT payload FROM brain_dump_operations WHERE owner_id = ? AND id = ?",
                (OWNER, payload["id"]),
            ).fetchone()[0]
        )
    assert stored == payload


def test_missing_schema_version_dispatches_as_legacy_v1(
    voice_repository: OperationRepository,
) -> None:
    repository = voice_repository
    payload = _legacy_brain_dump_payload(status="recording")
    payload.pop("schema_version")
    _insert_brain_dump_payload(repository, payload)

    migrated = repository.get_brain_dump_operation_for_owner(
        str(payload["id"]), owner_id=OWNER
    )

    assert migrated.schema_version == 2
    assert migrated.legacy_import == "legacy_preview_only"
    assert migrated.reconciliation_quality == "provisional_only"


def test_unknown_brain_dump_schema_version_fails_closed(
    voice_repository: OperationRepository,
) -> None:
    repository = voice_repository
    payload = _legacy_brain_dump_payload(status="recording")
    payload["schema_version"] = 99
    _insert_brain_dump_payload(repository, payload)

    with pytest.raises(RepositoryError, match="unsupported schema version 99"):
        repository.get_brain_dump_operation_for_owner(
            str(payload["id"]), owner_id=OWNER
        )


def test_purge_expired_raw_audio_does_not_mutate_terminal_schema_v1_record(
    voice_repository: OperationRepository, voice_service: VoiceBrainDumpService
) -> None:
    """Blocker 7b: a terminal schema-v1 operation is a byte-immutable
    historical record. The raw-audio retention sweep must never rewrite it
    even when it looks old and still carries audio chunks."""

    old = utcnow() - timedelta(days=400)
    payload = _legacy_brain_dump_payload(status="completed")
    payload["updated_at"] = old.isoformat()
    payload["audio_chunks"] = [
        {
            "chunk_number": 0,
            "sha256": "a" * 64,
            "size_bytes": 10,
            "received_at": old.isoformat(),
        }
    ]
    repository = voice_repository
    _insert_brain_dump_payload(repository, payload)

    purged = voice_service.purge_expired_raw_audio()

    assert purged == 0
    with sqlite3.connect(repository.db_path) as conn:
        stored = json.loads(
            conn.execute(
                "SELECT payload FROM brain_dump_operations WHERE owner_id = ? AND id = ?",
                (OWNER, payload["id"]),
            ).fetchone()[0]
        )
    assert stored == payload


def test_purge_expired_working_artifacts_does_not_mutate_terminal_schema_v1_record(
    voice_repository: OperationRepository, voice_service: VoiceBrainDumpService
) -> None:
    """Blocker 7b: a terminal schema-v1 operation's segments/proposals must
    survive the working-artifact retention sweep byte-for-byte."""

    old = utcnow() - timedelta(days=400)
    payload = _legacy_brain_dump_payload(status="completed")
    payload["updated_at"] = old.isoformat()
    repository = voice_repository
    _insert_brain_dump_payload(repository, payload)

    purged = voice_service.purge_expired_working_artifacts()

    assert purged == 0
    with sqlite3.connect(repository.db_path) as conn:
        stored = json.loads(
            conn.execute(
                "SELECT payload FROM brain_dump_operations WHERE owner_id = ? AND id = ?",
                (OWNER, payload["id"]),
            ).fetchone()[0]
        )
    assert stored == payload
