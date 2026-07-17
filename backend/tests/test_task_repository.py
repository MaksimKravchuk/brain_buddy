"""Robustness regression tests for the task module's SQLite persistence.

Covers idempotency-record retention and O(1) write-path lookups, translation
of raw ``sqlite3`` errors into domain exceptions, connection lifecycle during
repository construction, and the serialized legacy-JSON brain dump backfill.
"""

from __future__ import annotations

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
    BrainDumpOperationDocument,
    IdempotencyRecord,
    TaskDocument,
    TaskSubtaskDocument,
)
from app.modules.tasks.repository import IDEMPOTENCY_RETENTION
from app.schemas.tasks import BrainDumpOperationStartRequest, TaskCreateRequest
from app.utils.time import utcnow

OWNER = "user_repo_owner"


@pytest.fixture()
def repository(data_dir: Path) -> TaskRepository:
    return TaskRepository(data_dir)


@pytest.fixture()
def service(repository: TaskRepository) -> TaskService:
    return TaskService(repository)


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
    service: TaskService, *, key: str = "brain-dump-start"
) -> BrainDumpOperationDocument:
    return service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": False}}
        ),
        owner_id=OWNER,
        idempotency_key=key,
    )


def _delete_brain_dump_row(repository: TaskRepository, operation_id: str) -> None:
    conn = sqlite3.connect(repository.db_path)
    try:
        conn.execute(
            "DELETE FROM brain_dump_operations WHERE owner_id = ? AND id = ?",
            (OWNER, operation_id),
        )
        conn.commit()
    finally:
        conn.close()


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
    service: TaskService, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = _start_brain_dump(service, key="backfill-lock")
    repo = service.task_repo
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
    service: TaskService,
) -> None:
    operation = _start_brain_dump(service, key="backfill-nested")
    repo = service.task_repo
    _delete_brain_dump_row(repo, operation.id)

    with repo.command_lock(OWNER):
        restored = repo.get_brain_dump_operation_for_owner(operation.id, owner_id=OWNER)

    assert restored == operation


def test_brain_dump_backfill_does_not_clobber_concurrent_write(
    service: TaskService, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = _start_brain_dump(service, key="backfill-race")
    repo = service.task_repo
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
