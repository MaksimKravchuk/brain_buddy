"""SQLite persistence for records owned by the native task module."""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import ClassVar, TypeVar

from pydantic import BaseModel

from app.exceptions import (
    ConflictError,
    NotFoundError,
    RepositoryError,
)
from app.repositories.base import BaseRepository
from app.repositories.sqlite import SQLiteRepositorySupport
from app.utils.idempotency import idempotency_key_digest
from app.utils.time import utcnow

from .domain import (
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


class TaskRepository(SQLiteRepositorySupport, BaseRepository):
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

        with super()._command_lock(
            owner_id,
            lock=self._process_lock,
            thread_state=self._thread_state,
            resource="Task command",
            operational_message="Task storage is temporarily unavailable; retry the request.",
            repository_message=f"Task storage failed while writing Task command '{owner_id}'.",
        ):
            yield

    @contextmanager
    def _sqlite_guard(self, resource: str, identifier: str) -> Iterator[None]:
        with super().sqlite_guard(
            resource,
            identifier,
            "Task storage is temporarily unavailable; retry the request.",
            f"Task storage failed while writing {resource} '{identifier}'.",
        ):
            yield

    def _initialize_database(self) -> None:
        with self._owned_connection() as conn:
            conn.executescript("""
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
                CREATE INDEX IF NOT EXISTS idx_idempotency_owner_created
                    ON idempotency_records(owner_id, created_at);
                """)

    def _migrate_legacy_json_once(self) -> None:
        with self._owned_connection() as conn:
            seen = conn.execute(
                "SELECT 1 FROM migration_ledger WHERE id = ?", ("legacy-json-v1",)
            ).fetchone()
            if seen is not None:
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                counts = {"projects": 0, "tags": 0, "tasks": 0}
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
                            "state": (
                                "deleted" if tag.state == "archived" else tag.state
                            ),
                        }
                    )
                    self._upsert_tag(conn, tag)
                    counts["tags"] += 1
                for path in self.resolve("tasks").glob("*/*.json"):
                    task = self.load_model(path, TaskDocument)
                    task = task.model_copy(update={"tag_ids": task.tag_ids})
                    self._upsert_task(conn, task)
                    counts["tasks"] += 1
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

    def project_path(self, owner_id: str, project_id: str) -> Path:
        return self.resolve("projects", owner_id, f"{project_id}.json")

    def context_path(self, owner_id: str, context_id: str) -> Path:
        return self.resolve("contexts", owner_id, f"{context_id}.json")

    def task_path(self, owner_id: str, task_id: str) -> Path:
        return self.resolve("tasks", owner_id, f"{task_id}.json")

    def idempotency_path(self, owner_id: str, key: str) -> Path:
        key_hash = idempotency_key_digest(key)
        return self.resolve("task-commands", owner_id, f"{key_hash}.json")

    @staticmethod
    def _payload(model: BaseModel) -> str:
        return json.dumps(
            model.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    def _model(row: sqlite3.Row, model_cls: type[ModelT]) -> ModelT:
        return model_cls.model_validate(json.loads(row["payload"]))

    def _upsert_project(
        self, conn: sqlite3.Connection, project: ProjectDocument
    ) -> None:
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
        BaseRepository.dump_model(
            self.project_path(project.owner_id, project.id), project
        )

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

    def create_project(self, project: ProjectDocument) -> None:
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Project", project.id),
        ):
            if self._exists(conn, "projects", project.owner_id, project.id):
                raise ConflictError("Project", project.id)
            self._upsert_project(conn, project)

    def save_project(self, project: ProjectDocument) -> None:
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Project", project.id),
        ):
            self._upsert_project(conn, project)

    def create_tag(self, tag: TagDocument) -> None:
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Tag", tag.id),
        ):
            if self._exists(conn, "tags", tag.owner_id, tag.id):
                raise ConflictError("Tag", tag.id)
            self._upsert_tag(conn, tag)

    def save_tag(self, tag: TagDocument) -> None:
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Tag", tag.id),
        ):
            self._upsert_tag(conn, tag)

    def get_project_for_owner(
        self, project_id: str, *, owner_id: str
    ) -> ProjectDocument:
        return self._get(
            "projects", ProjectDocument, "Project", project_id, owner_id=owner_id
        )

    def get_tag_for_owner(self, tag_id: str, *, owner_id: str) -> TagDocument:
        return self._get("tags", TagDocument, "Tag", tag_id, owner_id=owner_id)

    def list_projects_for_owner(self, *, owner_id: str) -> list[ProjectDocument]:
        return self._list("projects", ProjectDocument, owner_id=owner_id)

    def list_tags_for_owner(self, *, owner_id: str) -> list[TagDocument]:
        return self._list("tags", TagDocument, owner_id=owner_id)

    def create(self, task: TaskDocument) -> None:
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Task", task.id),
        ):
            if self._exists(conn, "tasks", task.owner_id, task.id):
                raise ConflictError("Task", task.id)
            self._upsert_task(conn, task)

    def save(self, task: TaskDocument) -> None:
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Task", task.id),
        ):
            self._upsert_task(conn, task)

    def get_for_owner(self, task_id: str, *, owner_id: str) -> TaskDocument:
        return self._get("tasks", TaskDocument, "Task", task_id, owner_id=owner_id)

    def list_for_owner(self, *, owner_id: str) -> list[TaskDocument]:
        return self._list("tasks", TaskDocument, owner_id=owner_id)

    def create_subtask(self, subtask: TaskSubtaskDocument) -> None:
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Task subtask", subtask.id),
        ):
            conn.execute(
                "INSERT INTO subtasks (owner_id, task_id, id, payload) VALUES (?, ?, ?, ?)",
                (subtask.owner_id, subtask.task_id, subtask.id, self._payload(subtask)),
            )
        BaseRepository.dump_model(
            self.subtask_path(subtask.owner_id, subtask.task_id, subtask.id), subtask
        )

    def save_subtask(self, subtask: TaskSubtaskDocument) -> None:
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Task subtask", subtask.id),
        ):
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
        with self._connection(self._thread_state) as conn:
            rows = conn.execute(
                "SELECT payload FROM subtasks WHERE owner_id = ? AND task_id = ?",
                (owner_id, task_id),
            ).fetchall()
        return [
            TaskSubtaskDocument.model_validate(json.loads(row["payload"]))
            for row in rows
        ]

    def get_subtask_for_owner(
        self, subtask_id: str, *, owner_id: str, task_id: str
    ) -> TaskSubtaskDocument:
        with self._connection(self._thread_state) as conn:
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
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Task comment", comment.id),
        ):
            conn.execute(
                "INSERT INTO comments (owner_id, task_id, id, payload) VALUES (?, ?, ?, ?)",
                (comment.owner_id, comment.task_id, comment.id, self._payload(comment)),
            )
        BaseRepository.dump_model(
            self.comment_path(comment.owner_id, comment.task_id, comment.id), comment
        )

    def save_comment(self, comment: TaskCommentDocument) -> None:
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Task comment", comment.id),
        ):
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
        with self._connection(self._thread_state) as conn:
            rows = conn.execute(
                "SELECT payload FROM comments WHERE owner_id = ? AND task_id = ?",
                (owner_id, task_id),
            ).fetchall()
        return [
            TaskCommentDocument.model_validate(json.loads(row["payload"]))
            for row in rows
        ]

    def get_comment_for_owner(
        self, comment_id: str, *, owner_id: str, task_id: str
    ) -> TaskCommentDocument:
        with self._connection(self._thread_state) as conn:
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
        key_hash = idempotency_key_digest(key)
        with self._connection(self._thread_state) as conn:
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
        key_hash = idempotency_key_digest(record.key)
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Idempotency-Key", record.key),
        ):
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
        """Drop idempotency records past retention so history stays bounded.

        ``create_native_inbox_task`` records are exempt: a brain-dump commit
        action's deterministic child key is the durable "at most one task"
        dedup record, and an unresolved ``committing`` batch can outlive the
        generic 24h retention. Purging it early could let a later resume mint a
        duplicate canonical task, so those identities are retained for the
        (unbounded) lifetime of their frozen batch rather than by wall clock.
        """

        cutoff = (now - IDEMPOTENCY_RETENTION).isoformat()
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Idempotency-Key", owner_id),
        ):
            rows = conn.execute(
                """
                SELECT key FROM idempotency_records
                WHERE owner_id = ? AND created_at < ?
                    AND command != 'create_native_inbox_task'
                """,
                (owner_id, cutoff),
            ).fetchall()
            if not rows:
                return 0
            conn.execute(
                """
                DELETE FROM idempotency_records
                WHERE owner_id = ? AND created_at < ?
                    AND command != 'create_native_inbox_task'
                """,
                (owner_id, cutoff),
            )
        for row in rows:
            self.idempotency_path(owner_id, row["key"]).unlink(missing_ok=True)
        return len(rows)

    def list_idempotency_for_owner(self, *, owner_id: str) -> list[IdempotencyRecord]:
        with self._connection(self._thread_state) as conn:
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

    def delete_all_for_owner(self, *, owner_id: str) -> None:
        """Erase every record and JSON mirror belonging to one owner.

        GDPR account-purge support. Runs under ``command_lock`` so it
        serializes with normal commands; both the SQLite deletes and the
        mirror-directory removals are idempotent, so an interrupted purge can
        simply run again. Table order respects the RESTRICT foreign keys
        (tasks before tags/projects).
        """

        with self.command_lock(owner_id), self._connection(self._thread_state) as conn:
            for table in (
                "task_tags",
                "subtasks",
                "comments",
                "tasks",
                "tags",
                "projects",
                "idempotency_records",
            ):
                # noqa justification: `table` is bound by the literal tuple
                # directly above, never by caller input. The owner filter is
                # parameterised. If `table` ever becomes caller-controlled,
                # this suppression must go.
                conn.execute(
                    f"DELETE FROM {table} WHERE owner_id = ?",  # noqa: S608
                    (owner_id,),
                )
        for dirname in (
            "tasks",
            "projects",
            "contexts",
            "task-subtasks",
            "task-comments",
            "task-commands",
        ):
            shutil.rmtree(self.resolve(dirname, owner_id), ignore_errors=True)

    def next_order_key(self, *, owner_id: str, state: str) -> int:
        with self._connection(self._thread_state) as conn:
            value = conn.execute(
                "SELECT MAX(order_key) FROM tasks WHERE owner_id = ? AND state = ?",
                (owner_id, state),
            ).fetchone()[0]
        return (value if value is not None else -1) + 1

    # The three helpers below interpolate `table` into SQL. Every caller passes
    # a string literal naming one of this module's own tables -- SQLite cannot
    # parameterise a table name -- and the owner and id filters are always
    # bound. The suppressions are valid only while `table` stays internal; if a
    # caller ever forwards request data into it, they must be removed rather
    # than carried forward.
    def _exists(
        self, conn: sqlite3.Connection, table: str, owner_id: str, record_id: str
    ) -> bool:
        return (
            conn.execute(
                f"SELECT 1 FROM {table} WHERE owner_id = ? AND id = ?",  # noqa: S608
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
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard(resource, record_id),
        ):
            row = conn.execute(
                f"SELECT payload FROM {table} WHERE owner_id = ? AND id = ?",  # noqa: S608
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
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard(table, owner_id),
        ):
            rows = conn.execute(
                f"SELECT payload FROM {table} WHERE owner_id = ?",  # noqa: S608
                (owner_id,),
            ).fetchall()
        return [model_cls.model_validate(json.loads(row["payload"])) for row in rows]
