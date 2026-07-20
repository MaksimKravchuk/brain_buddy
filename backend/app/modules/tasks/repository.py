"""SQLite persistence for records owned by the native task module."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import ClassVar, TypeVar
from uuid import uuid4

from pydantic import BaseModel

from app.exceptions import (
    ConflictError,
    NotFoundError,
    RepositoryError,
    StorageUnavailableError,
)
from app.repositories.base import BaseRepository
from app.utils.time import utcnow

from .domain import (
    BrainDumpOperationDocument,
    IdempotencyRecord,
    ProjectDocument,
    TagDocument,
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)

ModelT = TypeVar("ModelT", bound=BaseModel)

IDEMPOTENCY_RETENTION = timedelta(hours=24)
"""How long replayed command results stay addressable by their key."""


@contextmanager
def _sqlite_guard(resource: str, identifier: str) -> Iterator[None]:
    """Translate raw ``sqlite3`` failures into the app's domain exceptions."""

    try:
        yield
    except sqlite3.IntegrityError as exc:
        raise ConflictError(
            resource,
            identifier,
            f"{resource} '{identifier}' conflicts with existing records.",
        ) from exc
    except sqlite3.OperationalError as exc:
        raise StorageUnavailableError(
            "Task storage is temporarily unavailable; retry the request."
        ) from exc
    except sqlite3.Error as exc:
        raise RepositoryError(
            f"Task storage failed while writing {resource} '{identifier}'."
        ) from exc


def normalize_task_name(value: str, *, strip_tag_prefix: bool = False) -> str:
    """Normalize project/tag names for owner-scoped uniqueness."""

    normalized = unicodedata.normalize("NFKC", value).strip()
    if strip_tag_prefix and normalized.startswith("@"):
        normalized = normalized[1:].strip()
    return " ".join(normalized.split()).casefold()


def display_tag_name(value: str) -> str:
    display = unicodedata.normalize("NFKC", value).strip()
    if display.startswith("@"):
        display = display[1:].strip()
    return " ".join(display.split())


def display_project_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())


class TaskRepository(BaseRepository):
    """Store task-module records in one owner-isolated SQLite database."""

    _thread_state: ClassVar[threading.local] = threading.local()
    _process_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.db_path = self.resolve("tasks.sqlite3")
        self._initialize_database()
        self._migrate_legacy_json_once()

    @contextmanager
    def command_lock(self, owner_id: str) -> Iterator[None]:
        """Serialize owner-scoped commands and wrap writes in one transaction."""

        # Owner serialization is global for SQLite's single writer.
        with self._process_lock:
            conn = self._connect()
            previous = getattr(self._thread_state, "conn", None)
            self._thread_state.conn = conn
            try:
                with _sqlite_guard("Task command", owner_id):
                    conn.execute("BEGIN IMMEDIATE")
                    yield
                    conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                self._thread_state.conn = previous
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def _owned_connection(self) -> Iterator[sqlite3.Connection]:
        """Open a private connection and always close it on exit."""

        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        active = getattr(self._thread_state, "conn", None)
        if active is not None:
            yield active
            return
        with self._owned_connection() as conn:
            yield conn

    def _initialize_database(self) -> None:
        with self._owned_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE TABLE IF NOT EXISTS tags (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    project_id TEXT,
                    order_key INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id),
                    FOREIGN KEY (owner_id, project_id)
                        REFERENCES projects(owner_id, id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS task_tags (
                    owner_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    tag_id TEXT NOT NULL,
                    PRIMARY KEY (owner_id, task_id, tag_id),
                    FOREIGN KEY (owner_id, task_id)
                        REFERENCES tasks(owner_id, id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (owner_id, tag_id)
                        REFERENCES tags(owner_id, id)
                        ON UPDATE RESTRICT ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS subtasks (
                    owner_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, task_id, id),
                    FOREIGN KEY (owner_id, task_id)
                        REFERENCES tasks(owner_id, id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS comments (
                    owner_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, task_id, id),
                    FOREIGN KEY (owner_id, task_id)
                        REFERENCES tasks(owner_id, id)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS brain_dump_operations (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    owner_id TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    key TEXT NOT NULL,
                    command TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    response_body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (owner_id, key_hash)
                );
                CREATE TABLE IF NOT EXISTS migration_ledger (
                    id TEXT PRIMARY KEY,
                    migrated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_owner_state
                    ON tasks(owner_id, state, order_key, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_task_tags_owner_tag
                    ON task_tags(owner_id, tag_id, task_id);
                CREATE INDEX IF NOT EXISTS idx_brain_dump_operations_owner_status
                    ON brain_dump_operations(owner_id, status, updated_at, id);
                CREATE INDEX IF NOT EXISTS idx_idempotency_owner_created
                    ON idempotency_records(owner_id, created_at);
                """
            )

    def _migrate_legacy_json_once(self) -> None:
        with self._owned_connection() as conn:
            seen = conn.execute(
                "SELECT 1 FROM migration_ledger WHERE id = ?", ("legacy-json-v1",)
            ).fetchone()
            if seen is not None:
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                counts = {"projects": 0, "tags": 0, "tasks": 0, "brain_dump_operations": 0}
                for path in self.resolve("projects").glob("*/*.json"):
                    project = self.load_model(path, ProjectDocument)
                    project = project.model_copy(
                        update={
                            "name": display_project_name(project.name),
                            "normalized_name": project.normalized_name
                            or normalize_task_name(project.name),
                        }
                    )
                    self._upsert_project(conn, project)
                    counts["projects"] += 1
                for path in self.resolve("contexts").glob("*/*.json"):
                    tag = self.load_model(path, TagDocument)
                    tag = tag.model_copy(
                        update={
                            "name": display_tag_name(tag.name),
                            "normalized_name": tag.normalized_name
                            or normalize_task_name(tag.name, strip_tag_prefix=True),
                            "state": "deleted" if tag.state == "archived" else tag.state,
                        }
                    )
                    self._upsert_tag(conn, tag)
                    counts["tags"] += 1
                for path in self.resolve("tasks").glob("*/*.json"):
                    task = self.load_model(path, TaskDocument)
                    task = task.model_copy(update={"tag_ids": task.tag_ids})
                    self._upsert_task(conn, task)
                    counts["tasks"] += 1
                for path in self.resolve("brain-dump-operations").glob("*/*.json"):
                    operation = self.load_model(path, BrainDumpOperationDocument)
                    self._upsert_brain_dump_operation(conn, operation)
                    counts["brain_dump_operations"] += 1
                conn.execute(
                    "INSERT INTO migration_ledger (id, migrated_at, payload) VALUES (?, ?, ?)",
                    (
                        "legacy-json-v1",
                        utcnow().isoformat(),
                        json.dumps(counts, sort_keys=True),
                    ),
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    # Compatibility path helpers retained for focused legacy tests.
    def subtask_path(self, owner_id: str, task_id: str, subtask_id: str) -> Path:
        return self.resolve("task-subtasks", owner_id, task_id, f"{subtask_id}.json")

    def comment_path(self, owner_id: str, task_id: str, comment_id: str) -> Path:
        return self.resolve("task-comments", owner_id, task_id, f"{comment_id}.json")

    def brain_dump_operation_path(self, owner_id: str, operation_id: str) -> Path:
        return self.resolve("brain-dump-operations", owner_id, f"{operation_id}.json")

    def brain_dump_audio_chunk_path(
        self, owner_id: str, operation_id: str, chunk_number: int, sha256: str
    ) -> Path:
        return self.resolve(
            "brain-dump-media", owner_id, operation_id, f"{chunk_number:06d}-{sha256}.bin"
        )

    def brain_dump_audio_operation_path(self, owner_id: str, operation_id: str) -> Path:
        return self.resolve("brain-dump-media", owner_id, operation_id)

    def project_path(self, owner_id: str, project_id: str) -> Path:
        return self.resolve("projects", owner_id, f"{project_id}.json")

    def context_path(self, owner_id: str, context_id: str) -> Path:
        return self.resolve("contexts", owner_id, f"{context_id}.json")

    def task_path(self, owner_id: str, task_id: str) -> Path:
        return self.resolve("tasks", owner_id, f"{task_id}.json")

    def idempotency_path(self, owner_id: str, key: str) -> Path:
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.resolve("task-commands", owner_id, f"{key_hash}.json")

    @staticmethod
    def _payload(model: BaseModel) -> str:
        return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _model(row: sqlite3.Row, model_cls: type[ModelT]) -> ModelT:
        return model_cls.model_validate(json.loads(row["payload"]))

    def _upsert_project(self, conn: sqlite3.Connection, project: ProjectDocument) -> None:
        conn.execute(
            """
            INSERT INTO projects (owner_id, id, normalized_name, state, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET
                normalized_name = excluded.normalized_name,
                state = excluded.state,
                payload = excluded.payload
            """,
            (
                project.owner_id,
                project.id,
                project.normalized_name,
                project.state,
                self._payload(project),
            ),
        )
        BaseRepository.dump_model(self.project_path(project.owner_id, project.id), project)

    def _upsert_tag(self, conn: sqlite3.Connection, tag: TagDocument) -> None:
        conn.execute(
            """
            INSERT INTO tags (owner_id, id, normalized_name, state, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET
                normalized_name = excluded.normalized_name,
                state = excluded.state,
                payload = excluded.payload
            """,
            (tag.owner_id, tag.id, tag.normalized_name, tag.state, self._payload(tag)),
        )
        BaseRepository.dump_model(self.context_path(tag.owner_id, tag.id), tag)

    def _upsert_task(self, conn: sqlite3.Connection, task: TaskDocument) -> None:
        conn.execute(
            """
            INSERT INTO tasks
                (owner_id, id, state, project_id, order_key, created_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET
                state = excluded.state,
                project_id = excluded.project_id,
                order_key = excluded.order_key,
                created_at = excluded.created_at,
                payload = excluded.payload
            """,
            (
                task.owner_id,
                task.id,
                task.state,
                task.project_id,
                task.order_key,
                task.created_at.isoformat(),
                self._payload(task),
            ),
        )
        conn.execute(
            "DELETE FROM task_tags WHERE owner_id = ? AND task_id = ?",
            (task.owner_id, task.id),
        )
        conn.executemany(
            "INSERT INTO task_tags (owner_id, task_id, tag_id) VALUES (?, ?, ?)",
            [(task.owner_id, task.id, tag_id) for tag_id in task.tag_ids],
        )
        BaseRepository.dump_model(self.task_path(task.owner_id, task.id), task)

    def _upsert_brain_dump_operation(
        self, conn: sqlite3.Connection, operation: BrainDumpOperationDocument
    ) -> None:
        conn.execute(
            """
            INSERT INTO brain_dump_operations
                (owner_id, id, status, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at,
                payload = excluded.payload
            """,
            (
                operation.owner_id,
                operation.id,
                operation.status,
                operation.updated_at.isoformat(),
                self._payload(operation),
            ),
        )
        BaseRepository.dump_model(
            self.brain_dump_operation_path(operation.owner_id, operation.id), operation
        )

    def create_project(self, project: ProjectDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Project", project.id):
            if self._exists(conn, "projects", project.owner_id, project.id):
                raise ConflictError("Project", project.id)
            self._upsert_project(conn, project)

    def save_project(self, project: ProjectDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Project", project.id):
            self._upsert_project(conn, project)

    def create_tag(self, tag: TagDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Tag", tag.id):
            if self._exists(conn, "tags", tag.owner_id, tag.id):
                raise ConflictError("Tag", tag.id)
            self._upsert_tag(conn, tag)

    def save_tag(self, tag: TagDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Tag", tag.id):
            self._upsert_tag(conn, tag)

    def get_project_for_owner(
        self, project_id: str, *, owner_id: str
    ) -> ProjectDocument:
        return self._get("projects", ProjectDocument, "Project", project_id, owner_id=owner_id)

    def get_tag_for_owner(self, tag_id: str, *, owner_id: str) -> TagDocument:
        return self._get("tags", TagDocument, "Tag", tag_id, owner_id=owner_id)

    def list_projects_for_owner(self, *, owner_id: str) -> list[ProjectDocument]:
        return self._list("projects", ProjectDocument, owner_id=owner_id)

    def list_tags_for_owner(self, *, owner_id: str) -> list[TagDocument]:
        return self._list("tags", TagDocument, owner_id=owner_id)

    def create(self, task: TaskDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Task", task.id):
            if self._exists(conn, "tasks", task.owner_id, task.id):
                raise ConflictError("Task", task.id)
            self._upsert_task(conn, task)

    def save(self, task: TaskDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Task", task.id):
            self._upsert_task(conn, task)

    def get_for_owner(self, task_id: str, *, owner_id: str) -> TaskDocument:
        return self._get("tasks", TaskDocument, "Task", task_id, owner_id=owner_id)

    def list_for_owner(self, *, owner_id: str) -> list[TaskDocument]:
        return self._list("tasks", TaskDocument, owner_id=owner_id)

    def save_brain_dump_operation(self, operation: BrainDumpOperationDocument) -> None:
        with (
            self._connection() as conn,
            _sqlite_guard("Brain dump operation", operation.id),
        ):
            self._upsert_brain_dump_operation(conn, operation)

    def save_brain_dump_audio_chunk(
        self, *, owner_id: str, operation_id: str, chunk_number: int, sha256: str, content: bytes
    ) -> None:
        path = self.brain_dump_audio_chunk_path(owner_id, operation_id, chunk_number, sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        staging_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            staging_path.write_bytes(content)
            os.replace(staging_path, path)
        finally:
            staging_path.unlink(missing_ok=True)

    def load_brain_dump_audio_chunks(
        self, *, owner_id: str, operation_id: str, chunks: list[tuple[int, str]]
    ) -> bytes:
        parts: list[bytes] = []
        for chunk_number, sha256 in sorted(chunks):
            path = self.brain_dump_audio_chunk_path(owner_id, operation_id, chunk_number, sha256)
            if not path.exists():
                raise NotFoundError("Brain dump audio chunk", f"{operation_id}:{chunk_number}")
            parts.append(path.read_bytes())
        return b"".join(parts)

    def delete_brain_dump_audio_chunks(
        self, *, owner_id: str, operation_id: str, chunks: list[tuple[int, str]]
    ) -> None:
        del chunks
        shutil.rmtree(
            self.brain_dump_audio_operation_path(owner_id, operation_id), ignore_errors=True
        )

    def list_expired_raw_audio_operations(
        self,
    ) -> list[BrainDumpOperationDocument]:
        # "awaiting_confirmation" is included alongside the terminal statuses
        # because raw audio's retention clock starts at successful
        # reconciliation, not only at operation completion/cancellation/
        # failure — an operation left awaiting confirmation and never
        # committed must still have its raw audio purged on schedule.
        #
        # No SQL column tracks the artifact-specific ``raw_audio_expires_at``
        # anchor (it lives inside the JSON payload), so this returns every
        # candidate in an eligible status; the caller compares each
        # document's own anchor against the current time to decide whether
        # it is actually due, exactly like the provider-lease sweep does for
        # ``lease_expires_at``.
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM brain_dump_operations
                """
            ).fetchall()
        return [
            BrainDumpOperationDocument.model_validate(json.loads(row["payload"]))
            for row in rows
        ]

    def list_in_flight_provider_run_operations(
        self,
    ) -> list[BrainDumpOperationDocument]:
        """Operations whose latest provider run may hold a due/expired lease.

        No SQL column tracks ``lease_expires_at`` directly (it lives inside
        the JSON payload), so this returns every ``accurate_transcribing``/
        ``reconciling`` operation across all owners; the caller inspects each
        document's last provider run to decide whether its lease is actually
        due before claiming it.
        """

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM brain_dump_operations
                WHERE status IN ('accurate_transcribing', 'reconciling')
                """
            ).fetchall()
        return [
            BrainDumpOperationDocument.model_validate(json.loads(row["payload"]))
            for row in rows
        ]

    def list_expired_working_artifact_operations(
        self, *, before: datetime
    ) -> list[BrainDumpOperationDocument]:
        """Operations whose uncommitted transcript/proposal working data may
        be purged: anything that never reached ``completed`` (so committed
        provenance behind an already-created ``TaskDocument`` is never
        touched), including abandoned ``recording``/``awaiting_confirmation``
        operations no one ever finished or discarded."""

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM brain_dump_operations
                WHERE updated_at < ?
                """,
                (before.isoformat(),),
            ).fetchall()
        return [
            BrainDumpOperationDocument.model_validate(json.loads(row["payload"]))
            for row in rows
        ]

    def list_brain_dump_operations(self) -> list[BrainDumpOperationDocument]:
        with self._connection() as conn:
            rows = conn.execute("SELECT payload FROM brain_dump_operations").fetchall()
        return [
            BrainDumpOperationDocument.model_validate(json.loads(row["payload"]))
            for row in rows
        ]

    def purge_brain_dump_media_orphans(self) -> int:
        """Remove untracked media and interrupted atomic-write temp files.

        Runs under the same global command lock used to serialize owner
        writes (audio-chunk uploads included), and re-reads the "known
        media" snapshot from the database only after acquiring it. Without
        this, a chunk durably uploaded between an outside caller listing
        operations and this sweep scanning the filesystem would look
        orphaned -- and get deleted moments after being written -- because
        the snapshot and the filesystem scan were not atomic with respect
        to a concurrent upload.
        """

        with self.command_lock("system:media-orphan-sweep"):
            operations = self.list_brain_dump_operations()
            expected = {
                (operation.owner_id, operation.id): {
                    f"{chunk.chunk_number:06d}-{chunk.sha256}.bin"
                    for chunk in operation.audio_chunks
                }
                for operation in operations
            }
            root = self.resolve("brain-dump-media")
            if not root.exists():
                return 0
            removed = 0
            for owner_path in root.iterdir():
                if not owner_path.is_dir():
                    owner_path.unlink(missing_ok=True)
                    removed += 1
                    continue
                for operation_path in owner_path.iterdir():
                    if not operation_path.is_dir():
                        operation_path.unlink(missing_ok=True)
                        removed += 1
                        continue
                    known = expected.get((owner_path.name, operation_path.name))
                    if known is None:
                        shutil.rmtree(operation_path, ignore_errors=True)
                        removed += 1
                        continue
                    for media_path in operation_path.iterdir():
                        if media_path.name not in known:
                            media_path.unlink(missing_ok=True)
                            removed += 1
            return removed

    def get_brain_dump_operation_for_owner(
        self, operation_id: str, *, owner_id: str
    ) -> BrainDumpOperationDocument:
        operation = self._load_brain_dump_operation(operation_id, owner_id=owner_id)
        if operation is not None:
            return operation

        path = self.brain_dump_operation_path(owner_id, operation_id)
        if not path.exists():
            raise NotFoundError("Brain dump operation", operation_id)
        legacy = self.load_model(path, BrainDumpOperationDocument)
        if getattr(self._thread_state, "conn", None) is not None:
            # Already inside this thread's serialized command transaction.
            self.save_brain_dump_operation(legacy)
            return legacy
        with self.command_lock(owner_id):
            # Re-check under the lock so a concurrent write is never clobbered
            # by the stale legacy JSON snapshot.
            current = self._load_brain_dump_operation(operation_id, owner_id=owner_id)
            if current is not None:
                return current
            self.save_brain_dump_operation(legacy)
            return legacy

    def _load_brain_dump_operation(
        self, operation_id: str, *, owner_id: str
    ) -> BrainDumpOperationDocument | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT payload FROM brain_dump_operations
                WHERE owner_id = ? AND id = ?
                """,
                (owner_id, operation_id),
            ).fetchone()
        if row is None:
            return None
        return BrainDumpOperationDocument.model_validate(json.loads(row["payload"]))

    def create_subtask(self, subtask: TaskSubtaskDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Task subtask", subtask.id):
            conn.execute(
                "INSERT INTO subtasks (owner_id, task_id, id, payload) VALUES (?, ?, ?, ?)",
                (subtask.owner_id, subtask.task_id, subtask.id, self._payload(subtask)),
            )
        BaseRepository.dump_model(
            self.subtask_path(subtask.owner_id, subtask.task_id, subtask.id), subtask
        )

    def save_subtask(self, subtask: TaskSubtaskDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Task subtask", subtask.id):
            conn.execute(
                """
                UPDATE subtasks SET payload = ?
                WHERE owner_id = ? AND task_id = ? AND id = ?
                """,
                (self._payload(subtask), subtask.owner_id, subtask.task_id, subtask.id),
            )
        BaseRepository.dump_model(
            self.subtask_path(subtask.owner_id, subtask.task_id, subtask.id), subtask
        )

    def list_subtasks(
        self, *, owner_id: str, task_id: str
    ) -> list[TaskSubtaskDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM subtasks WHERE owner_id = ? AND task_id = ?",
                (owner_id, task_id),
            ).fetchall()
        return [TaskSubtaskDocument.model_validate(json.loads(row["payload"])) for row in rows]

    def get_subtask_for_owner(
        self, subtask_id: str, *, owner_id: str, task_id: str
    ) -> TaskSubtaskDocument:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT payload FROM subtasks
                WHERE owner_id = ? AND task_id = ? AND id = ?
                """,
                (owner_id, task_id, subtask_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Task subtask", subtask_id)
        return TaskSubtaskDocument.model_validate(json.loads(row["payload"]))

    def create_comment(self, comment: TaskCommentDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Task comment", comment.id):
            conn.execute(
                "INSERT INTO comments (owner_id, task_id, id, payload) VALUES (?, ?, ?, ?)",
                (comment.owner_id, comment.task_id, comment.id, self._payload(comment)),
            )
        BaseRepository.dump_model(
            self.comment_path(comment.owner_id, comment.task_id, comment.id), comment
        )

    def save_comment(self, comment: TaskCommentDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Task comment", comment.id):
            conn.execute(
                """
                UPDATE comments SET payload = ?
                WHERE owner_id = ? AND task_id = ? AND id = ?
                """,
                (self._payload(comment), comment.owner_id, comment.task_id, comment.id),
            )
        BaseRepository.dump_model(
            self.comment_path(comment.owner_id, comment.task_id, comment.id), comment
        )

    def list_comments(
        self, *, owner_id: str, task_id: str
    ) -> list[TaskCommentDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM comments WHERE owner_id = ? AND task_id = ?",
                (owner_id, task_id),
            ).fetchall()
        return [TaskCommentDocument.model_validate(json.loads(row["payload"])) for row in rows]

    def get_comment_for_owner(
        self, comment_id: str, *, owner_id: str, task_id: str
    ) -> TaskCommentDocument:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT payload FROM comments
                WHERE owner_id = ? AND task_id = ? AND id = ?
                """,
                (owner_id, task_id, comment_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Task comment", comment_id)
        return TaskCommentDocument.model_validate(json.loads(row["payload"]))

    def get_idempotency(self, *, owner_id: str, key: str) -> IdempotencyRecord | None:
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT key, command, request_hash, resource_id, response_body, created_at
                FROM idempotency_records WHERE owner_id = ? AND key_hash = ?
                """,
                (owner_id, key_hash),
            ).fetchone()
        if row is None:
            return None
        return IdempotencyRecord(
            key=row["key"],
            command=row["command"],
            request_hash=row["request_hash"],
            resource_id=row["resource_id"],
            response_body=json.loads(row["response_body"]),
            created_at=row["created_at"],
        )

    def save_idempotency(self, *, owner_id: str, record: IdempotencyRecord) -> None:
        key_hash = hashlib.sha256(record.key.encode("utf-8")).hexdigest()
        with self._connection() as conn, _sqlite_guard("Idempotency-Key", record.key):
            conn.execute(
                """
                INSERT OR REPLACE INTO idempotency_records
                    (owner_id, key_hash, key, command, request_hash, resource_id,
                     response_body, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_id,
                    key_hash,
                    record.key,
                    record.command,
                    record.request_hash,
                    record.resource_id,
                    json.dumps(record.response_body, sort_keys=True),
                    record.created_at.isoformat(),
                ),
            )
        BaseRepository.dump_model(self.idempotency_path(owner_id, record.key), record)

    def purge_expired_idempotency(self, *, owner_id: str, now: datetime) -> int:
        """Drop idempotency records past retention so history stays bounded."""

        cutoff = (now - IDEMPOTENCY_RETENTION).isoformat()
        with self._connection() as conn, _sqlite_guard("Idempotency-Key", owner_id):
            rows = conn.execute(
                """
                SELECT key FROM idempotency_records
                WHERE owner_id = ? AND created_at < ?
                """,
                (owner_id, cutoff),
            ).fetchall()
            if not rows:
                return 0
            conn.execute(
                "DELETE FROM idempotency_records WHERE owner_id = ? AND created_at < ?",
                (owner_id, cutoff),
            )
        for row in rows:
            self.idempotency_path(owner_id, row["key"]).unlink(missing_ok=True)
        return len(rows)

    def list_idempotency_for_owner(self, *, owner_id: str) -> list[IdempotencyRecord]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT key, command, request_hash, resource_id, response_body, created_at
                FROM idempotency_records WHERE owner_id = ?
                """,
                (owner_id,),
            ).fetchall()
        return [
            IdempotencyRecord(
                key=row["key"],
                command=row["command"],
                request_hash=row["request_hash"],
                resource_id=row["resource_id"],
                response_body=json.loads(row["response_body"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def next_order_key(self, *, owner_id: str, state: str) -> int:
        with self._connection() as conn:
            value = conn.execute(
                "SELECT MAX(order_key) FROM tasks WHERE owner_id = ? AND state = ?",
                (owner_id, state),
            ).fetchone()[0]
        return (value if value is not None else -1) + 1

    def _exists(
        self, conn: sqlite3.Connection, table: str, owner_id: str, record_id: str
    ) -> bool:
        return (
            conn.execute(
                f"SELECT 1 FROM {table} WHERE owner_id = ? AND id = ?",
                (owner_id, record_id),
            ).fetchone()
            is not None
        )

    def _get(
        self,
        table: str,
        model_cls: type[ModelT],
        resource: str,
        record_id: str,
        *,
        owner_id: str,
    ) -> ModelT:
        with self._connection() as conn, _sqlite_guard(resource, record_id):
            row = conn.execute(
                f"SELECT payload FROM {table} WHERE owner_id = ? AND id = ?",
                (owner_id, record_id),
            ).fetchone()
        if row is None:
            raise NotFoundError(resource, record_id)
        try:
            return model_cls.model_validate(json.loads(row["payload"]))
        except (TypeError, json.JSONDecodeError) as exc:  # pragma: no cover
            raise RepositoryError(f"Invalid {resource} payload") from exc

    def _list(
        self, table: str, model_cls: type[ModelT], *, owner_id: str
    ) -> list[ModelT]:
        with self._connection() as conn, _sqlite_guard(table, owner_id):
            rows = conn.execute(
                f"SELECT payload FROM {table} WHERE owner_id = ?", (owner_id,)
            ).fetchall()
        return [model_cls.model_validate(json.loads(row["payload"])) for row in rows]
