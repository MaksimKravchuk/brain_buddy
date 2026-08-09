"""SQLite persistence for the external-agent relay module.

Deliberately SQLite-only: unlike the task module this repository writes no JSON
mirror, because these rows carry sealed connector credentials and relayed user
content, and a second plaintext-path copy would widen both the retention surface
(FR-015) and the blast radius of a disk leak.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import ClassVar, TypeVar

from pydantic import BaseModel

from app.exceptions import (
    ConflictError,
    NotFoundError,
    RepositoryError,
    StorageUnavailableError,
)
from app.repositories.base import BaseRepository

from .domain import (
    AgentAuditEntryDocument,
    AgentConnectionDocument,
    AgentIdempotencyRecord,
    AgentRunCommandDocument,
    AgentRunDocument,
    AgentRunEventDocument,
)

ModelT = TypeVar("ModelT", bound=BaseModel)

IDEMPOTENCY_RETENTION = timedelta(hours=24)
"""How long a replayed relay command stays addressable by its key."""

AUDIT_RETENTION = timedelta(days=90)
"""Upper bound on audit metadata (FR-015). Content retention is far shorter."""

EVENT_ID_RETENTION = timedelta(days=30)
"""How long a consumed event ID blocks a replay; matches content retention."""


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
            "Agent storage is temporarily unavailable; retry the request."
        ) from exc
    except sqlite3.Error as exc:
        raise RepositoryError(
            f"Agent storage failed while writing {resource} '{identifier}'."
        ) from exc


class AgentRepository(BaseRepository):
    """Store relay records in one owner-isolated SQLite database."""

    _thread_state: ClassVar[threading.local] = threading.local()
    _process_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.db_path = self.resolve("agents.sqlite3")
        self._initialize_database()

    # --- connection plumbing ------------------------------------------------

    @contextmanager
    def command_lock(self, owner_id: str) -> Iterator[None]:
        """Serialize owner-scoped commands and wrap writes in one transaction."""

        with self._process_lock:
            conn = self._connect()
            previous = getattr(self._thread_state, "conn", None)
            self._thread_state.conn = conn
            try:
                with _sqlite_guard("Agent command", owner_id):
                    conn.execute("BEGIN IMMEDIATE")
                    yield
                    conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                self._thread_state.conn = previous
                conn.close()

    def commit_checkpoint(self) -> None:
        """Durably land what the open command has written so far.

        A command that is about to leave the process has to have its
        reservation on disk *first*: if the call is lost mid-flight the agent
        may already hold that command ID, and a rolled-back reservation would
        let the retry mint a second one for the same intent. The owner's
        process lock is still held across the seam, so no other command of
        theirs can interleave here.
        """

        conn = getattr(self._thread_state, "conn", None)
        if conn is None:
            return
        with _sqlite_guard("Agent command", "checkpoint"):
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def _owned_connection(self) -> Iterator[sqlite3.Connection]:
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
                CREATE TABLE IF NOT EXISTS agent_connections (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    dispatched_at TEXT,
                    manifest_token TEXT,
                    content_expires_at TEXT NOT NULL,
                    content_expired INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runs_task
                    ON agent_runs(owner_id, task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_expiry
                    ON agent_runs(content_expired, content_expires_at);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_token
                    ON agent_runs(owner_id, manifest_token);
                CREATE TABLE IF NOT EXISTS agent_run_events (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    run_version INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, run_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_events_run
                    ON agent_run_events(owner_id, run_id, run_version);
                CREATE TABLE IF NOT EXISTS agent_run_commands (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_commands_run
                    ON agent_run_commands(owner_id, run_id, created_at);
                CREATE TABLE IF NOT EXISTS agent_event_ids (
                    owner_id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    consumed_at TEXT NOT NULL,
                    PRIMARY KEY (owner_id, connection_id, event_id)
                );
                CREATE TABLE IF NOT EXISTS agent_audit (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_audit_created
                    ON agent_audit(created_at);
                CREATE TABLE IF NOT EXISTS agent_idempotency (
                    owner_id TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    command TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    command_id TEXT,
                    completed INTEGER NOT NULL DEFAULT 1,
                    response_body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (owner_id, key_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_idempotency_created
                    ON agent_idempotency(created_at);
                """
            )

    @staticmethod
    def _payload(model: BaseModel) -> str:
        return json.dumps(
            model.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    def _model(row: sqlite3.Row, model_cls: type[ModelT]) -> ModelT:
        try:
            return model_cls.model_validate(json.loads(row["payload"]))
        except (TypeError, ValueError) as exc:  # pragma: no cover - corrupt row
            raise RepositoryError("Invalid agent-relay payload") from exc

    # --- connections --------------------------------------------------------

    def create_connection(self, connection: AgentConnectionDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Agent connection", connection.id):
            existing = conn.execute(
                "SELECT 1 FROM agent_connections WHERE owner_id = ? AND id = ?",
                (connection.owner_id, connection.id),
            ).fetchone()
            if existing is not None:
                raise ConflictError("Agent connection", connection.id)
            self._upsert_connection(conn, connection)

    def save_connection(self, connection: AgentConnectionDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Agent connection", connection.id):
            self._upsert_connection(conn, connection)

    def _upsert_connection(
        self, conn: sqlite3.Connection, connection: AgentConnectionDocument
    ) -> None:
        conn.execute(
            """
            INSERT INTO agent_connections (owner_id, id, status, created_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET
                status = excluded.status,
                payload = excluded.payload
            """,
            (
                connection.owner_id,
                connection.id,
                connection.status,
                connection.created_at.isoformat(),
                self._payload(connection),
            ),
        )

    def get_connection(
        self, connection_id: str, *, owner_id: str
    ) -> AgentConnectionDocument:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM agent_connections WHERE owner_id = ? AND id = ?",
                (owner_id, connection_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Agent connection", connection_id)
        return self._model(row, AgentConnectionDocument)

    def list_connections(self, *, owner_id: str) -> list[AgentConnectionDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_connections
                WHERE owner_id = ? ORDER BY created_at ASC, id ASC
                """,
                (owner_id,),
            ).fetchall()
        return [self._model(row, AgentConnectionDocument) for row in rows]

    # --- runs ---------------------------------------------------------------

    def create_run(self, run: AgentRunDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Agent run", run.id):
            existing = conn.execute(
                "SELECT 1 FROM agent_runs WHERE owner_id = ? AND id = ?",
                (run.owner_id, run.id),
            ).fetchone()
            if existing is not None:
                raise ConflictError("Agent run", run.id)
            self._upsert_run(conn, run)

    def save_run(self, run: AgentRunDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Agent run", run.id):
            self._upsert_run(conn, run)

    def _upsert_run(self, conn: sqlite3.Connection, run: AgentRunDocument) -> None:
        conn.execute(
            """
            INSERT INTO agent_runs
                (owner_id, id, connection_id, task_id, created_at, dispatched_at,
                 manifest_token, content_expires_at, content_expired, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET
                dispatched_at = excluded.dispatched_at,
                manifest_token = excluded.manifest_token,
                content_expires_at = excluded.content_expires_at,
                content_expired = excluded.content_expired,
                payload = excluded.payload
            """,
            (
                run.owner_id,
                run.id,
                run.connection_id,
                run.task_id,
                run.created_at.isoformat(),
                run.dispatched_at.isoformat() if run.dispatched_at else None,
                run.manifest.token if run.manifest else None,
                run.content_expires_at.isoformat(),
                int(run.content_expired),
                self._payload(run),
            ),
        )

    def find_run_by_manifest_token(
        self, token: str, *, owner_id: str
    ) -> AgentRunDocument | None:
        """Resolve the reservation a confirmation names, if it still exists."""

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT payload FROM agent_runs
                WHERE owner_id = ? AND manifest_token = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (owner_id, token),
            ).fetchone()
        return None if row is None else self._model(row, AgentRunDocument)

    def find_connection_anywhere(
        self, connection_id: str
    ) -> AgentConnectionDocument | None:
        """Look a connection up without an owner, for inbound event routing.

        Inbound events arrive unauthenticated as a user; the connection is what
        identifies the owner, and the signature is what proves the caller may
        act as it. Every downstream read is then re-scoped to that owner.
        """

        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM agent_connections WHERE id = ?", (connection_id,)
            ).fetchone()
        return None if row is None else self._model(row, AgentConnectionDocument)

    def prune_undispatched_runs(self, *, before: datetime) -> int:
        """Drop abandoned review reservations so they cannot accumulate."""

        with self._connection() as conn, _sqlite_guard("Agent run", "reservations"):
            cursor = conn.execute(
                """
                DELETE FROM agent_runs
                WHERE dispatched_at IS NULL AND created_at < ?
                """,
                (before.isoformat(),),
            )
            return int(cursor.rowcount or 0)

    def get_run(self, run_id: str, *, owner_id: str) -> AgentRunDocument:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM agent_runs WHERE owner_id = ? AND id = ?",
                (owner_id, run_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Agent run", run_id)
        return self._model(row, AgentRunDocument)

    def list_runs_for_task(self, task_id: str, *, owner_id: str) -> list[AgentRunDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_runs
                WHERE owner_id = ? AND task_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (owner_id, task_id),
            ).fetchall()
        return [self._model(row, AgentRunDocument) for row in rows]

    def list_runs_for_owner(self, *, owner_id: str) -> list[AgentRunDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_runs
                WHERE owner_id = ? ORDER BY created_at DESC, id DESC
                """,
                (owner_id,),
            ).fetchall()
        return [self._model(row, AgentRunDocument) for row in rows]

    def latest_runs_by_task(
        self, *, owner_id: str, task_ids: Sequence[str]
    ) -> dict[str, AgentRunDocument]:
        """The newest run per task, for the compact Task surface (FR-010)."""

        unique = list(dict.fromkeys(task_ids))
        if not unique:
            return {}
        latest: dict[str, AgentRunDocument] = {}
        placeholders = ",".join("?" for _ in unique)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT task_id, payload FROM agent_runs
                WHERE owner_id = ? AND dispatched_at IS NOT NULL
                    AND task_id IN ({placeholders})
                ORDER BY created_at ASC, id ASC
                """,
                (owner_id, *unique),
            ).fetchall()
        for row in rows:
            # Ascending order means the last write per task wins.
            latest[row["task_id"]] = self._model(row, AgentRunDocument)
        return latest

    # --- events -------------------------------------------------------------

    def consume_event_id(
        self, *, owner_id: str, connection_id: str, event_id: str, now: datetime
    ) -> bool:
        """Atomically claim one replay identifier. ``False`` means duplicate.

        Executed as a single conditional INSERT so two concurrent deliveries of
        the same event can never both proceed to mutate the projection (FR-009).
        """

        with self._connection() as conn, _sqlite_guard("Agent event", event_id):
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO agent_event_ids
                    (owner_id, connection_id, event_id, consumed_at)
                VALUES (?, ?, ?, ?)
                """,
                (owner_id, connection_id, event_id, now.isoformat()),
            )
            return cursor.rowcount == 1

    def append_event(self, event: AgentRunEventDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Agent event", event.id):
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_run_events
                    (owner_id, id, run_id, run_version, received_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.owner_id,
                    event.id,
                    event.run_id,
                    event.run_version,
                    event.received_at.isoformat(),
                    self._payload(event),
                ),
            )

    def list_events(self, run_id: str, *, owner_id: str) -> list[AgentRunEventDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_run_events
                WHERE owner_id = ? AND run_id = ?
                ORDER BY run_version ASC, received_at ASC, id ASC
                """,
                (owner_id, run_id),
            ).fetchall()
        return [self._model(row, AgentRunEventDocument) for row in rows]

    # --- commands -----------------------------------------------------------

    def save_command(self, command: AgentRunCommandDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Agent command", command.id):
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_run_commands
                    (owner_id, id, run_id, created_at, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    command.owner_id,
                    command.id,
                    command.run_id,
                    command.created_at.isoformat(),
                    self._payload(command),
                ),
            )

    def get_command(
        self, command_id: str, *, owner_id: str
    ) -> AgentRunCommandDocument | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM agent_run_commands WHERE owner_id = ? AND id = ?",
                (owner_id, command_id),
            ).fetchone()
        return None if row is None else self._model(row, AgentRunCommandDocument)

    def list_commands(
        self, run_id: str, *, owner_id: str
    ) -> list[AgentRunCommandDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_run_commands
                WHERE owner_id = ? AND run_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (owner_id, run_id),
            ).fetchall()
        return [self._model(row, AgentRunCommandDocument) for row in rows]

    # --- audit --------------------------------------------------------------

    def append_audit(self, entry: AgentAuditEntryDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Agent audit", entry.id):
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_audit (owner_id, id, created_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    entry.owner_id,
                    entry.id,
                    entry.created_at.isoformat(),
                    self._payload(entry),
                ),
            )

    def list_audit(self, *, owner_id: str) -> list[AgentAuditEntryDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_audit
                WHERE owner_id = ? ORDER BY created_at DESC, id DESC
                """,
                (owner_id,),
            ).fetchall()
        return [self._model(row, AgentAuditEntryDocument) for row in rows]

    def purge_expired_audit(self, *, now: datetime) -> int:
        cutoff = (now - AUDIT_RETENTION).isoformat()
        with self._connection() as conn, _sqlite_guard("Agent audit", "retention"):
            cursor = conn.execute(
                "DELETE FROM agent_audit WHERE created_at < ?", (cutoff,)
            )
            return int(cursor.rowcount or 0)

    # --- retention ----------------------------------------------------------

    def expire_due_content(self, *, now: datetime) -> int:
        """Erase relayed content past its retention, keeping the run readable.

        Age is measured from the authoritative creation stamp recorded at
        dispatch and never reset by a read (FR-015). The run row itself
        survives so the Task can still show *that* a hand-off happened.
        """

        stamp = now.isoformat()
        with self._connection() as conn, _sqlite_guard("Agent run", "retention"):
            rows = conn.execute(
                """
                SELECT payload FROM agent_runs
                WHERE content_expired = 0 AND dispatched_at IS NOT NULL
                    AND content_expires_at <= ?
                """,
                (stamp,),
            ).fetchall()
            if not rows:
                return 0
            for row in rows:
                run = self._model(row, AgentRunDocument)
                redacted = run.model_copy(
                    update={
                        "manifest": None,
                        "progress_text": None,
                        "question_text": None,
                        "result_text": None,
                        "result_link": None,
                        "failure_reason": None,
                        "content_expired": True,
                        "updated_at": now,
                        "revision": run.revision + 1,
                    }
                )
                self._upsert_run(conn, redacted)
                event_rows = conn.execute(
                    """
                    SELECT payload FROM agent_run_events
                    WHERE owner_id = ? AND run_id = ?
                    """,
                    (run.owner_id, run.id),
                ).fetchall()
                for event_row in event_rows:
                    event = self._model(event_row, AgentRunEventDocument)
                    if event.summary is None:
                        continue
                    conn.execute(
                        """
                        UPDATE agent_run_events SET payload = ?
                        WHERE owner_id = ? AND run_id = ? AND id = ?
                        """,
                        (
                            self._payload(event.model_copy(update={"summary": None})),
                            run.owner_id,
                            run.id,
                            event.id,
                        ),
                    )
                for command in self.list_commands(run.id, owner_id=run.owner_id):
                    if command.body is None:
                        continue
                    conn.execute(
                        """
                        UPDATE agent_run_commands SET payload = ?
                        WHERE owner_id = ? AND run_id = ? AND id = ?
                        """,
                        (
                            self._payload(command.model_copy(update={"body": None})),
                            run.owner_id,
                            run.id,
                            command.id,
                        ),
                    )
            return len(rows)

    def purge_expired_event_ids(self, *, now: datetime) -> int:
        cutoff = (now - EVENT_ID_RETENTION).isoformat()
        with self._connection() as conn, _sqlite_guard("Agent event", "retention"):
            cursor = conn.execute(
                "DELETE FROM agent_event_ids WHERE consumed_at < ?", (cutoff,)
            )
            return int(cursor.rowcount or 0)

    # --- idempotency --------------------------------------------------------

    def get_idempotency(
        self, *, owner_id: str, key_hashes: Sequence[str]
    ) -> AgentIdempotencyRecord | None:
        """Find the record stored under any of ``key_hashes``, newest key first.

        The caller passes one candidate per configured relay key, so a record
        written before a rotation is still found while its key remains
        configured. The raw key never reaches this layer at all.
        """

        candidates = list(key_hashes)
        if not candidates:
            return None
        placeholders = ",".join("?" for _ in candidates)
        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT key_hash, command, request_hash, resource_id, command_id,
                       completed, response_body, created_at
                FROM agent_idempotency
                WHERE owner_id = ? AND key_hash IN ({placeholders})
                """,
                (owner_id, *candidates),
            ).fetchall()
        by_hash = {row["key_hash"]: row for row in rows}
        for candidate in candidates:
            row = by_hash.get(candidate)
            if row is None:
                continue
            return AgentIdempotencyRecord(
                key_hash=row["key_hash"],
                command=row["command"],
                request_hash=row["request_hash"],
                resource_id=row["resource_id"],
                command_id=row["command_id"],
                completed=bool(row["completed"]),
                response_body=json.loads(row["response_body"]),
                created_at=row["created_at"],
            )
        return None

    def save_idempotency(self, *, owner_id: str, record: AgentIdempotencyRecord) -> None:
        # The guard's identifier is deliberately the resource, not the key or
        # its hash: it can end up in an error message and a log line.
        with self._connection() as conn, _sqlite_guard(
            "Idempotency-Key", record.resource_id
        ):
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_idempotency
                    (owner_id, key_hash, command, request_hash, resource_id,
                     command_id, completed, response_body, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_id,
                    record.key_hash,
                    record.command,
                    record.request_hash,
                    record.resource_id,
                    record.command_id,
                    int(record.completed),
                    json.dumps(record.response_body, sort_keys=True),
                    record.created_at.isoformat(),
                ),
            )

    def purge_expired_idempotency(self, *, owner_id: str, now: datetime) -> int:
        cutoff = (now - IDEMPOTENCY_RETENTION).isoformat()
        with self._connection() as conn, _sqlite_guard("Idempotency-Key", owner_id):
            cursor = conn.execute(
                "DELETE FROM agent_idempotency WHERE owner_id = ? AND created_at < ?",
                (owner_id, cutoff),
            )
            return int(cursor.rowcount or 0)

    def purge_all_expired_idempotency(self, *, now: datetime) -> int:
        """Drop every expired reservation, for every owner.

        The per-owner form only runs when that owner makes a request, so an
        account that goes quiet would keep its rows forever. Retention is a
        promise about the data, not about the traffic, so the sweep is global.
        """

        cutoff = (now - IDEMPOTENCY_RETENTION).isoformat()
        with self._connection() as conn, _sqlite_guard("Idempotency-Key", "retention"):
            cursor = conn.execute(
                "DELETE FROM agent_idempotency WHERE created_at < ?", (cutoff,)
            )
            return int(cursor.rowcount or 0)

    # --- purge --------------------------------------------------------------

    def delete_all_for_owner(self, *, owner_id: str) -> None:
        """Erase every relay record belonging to one owner. Idempotent."""

        with self.command_lock(owner_id), self._connection() as conn:
            for table in (
                "agent_run_events",
                "agent_run_commands",
                "agent_runs",
                "agent_event_ids",
                "agent_connections",
                "agent_audit",
                "agent_idempotency",
            ):
                conn.execute(f"DELETE FROM {table} WHERE owner_id = ?", (owner_id,))


__all__ = [
    "AUDIT_RETENTION",
    "EVENT_ID_RETENTION",
    "IDEMPOTENCY_RETENTION",
    "AgentRepository",
]
