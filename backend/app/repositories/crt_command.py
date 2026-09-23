"""Durable idempotency receipts for CRT mutation commands."""

from __future__ import annotations

import fcntl
import json
import shutil
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import ClassVar

from app.exceptions import ConflictError, RepositoryError
from app.repositories.base import BaseRepository
from app.repositories.sqlite import SQLiteRepositorySupport
from app.utils.time import utcnow

CRT_COMMAND_RETENTION = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class CrtCommandReceipt:
    """A persisted owner/route-scoped command receipt."""

    owner_id: str
    key_digest: str
    command: str
    normalized_route: str
    request_hash: str
    state: str
    resource_id: str
    base_revision: int | None
    target_revision: int | None
    response_status: int | None
    response_json: str | None
    created_at: datetime
    committed_at: datetime | None
    expires_at: datetime
    pending_target_snapshot: str | None = None


class CrtCommandRepository(SQLiteRepositorySupport, BaseRepository):
    """Store CRT command state separately from the canonical tree aggregate."""

    _thread_state: ClassVar[threading.local] = threading.local()
    _process_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.db_path = self.resolve("crt_commands.sqlite3")
        self._initialize_database()

    @contextmanager
    def command_lock(self, owner_id: str) -> Iterator[None]:
        """Serialize durable receipt/tree commands across workers."""

        # Pending must be durable before the file-backed tree write begins.
        # The tree/index and SQLite receipt cannot share a transaction. One
        # non-owner-derived advisory lock avoids retaining an account fingerprint
        # after purge and still closes cross-worker check/write races.
        _ = owner_id
        with self._process_lock:
            lock_path = self.resolve(".crt-command.lock")
            with lock_path.open("a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _initialize_database(self) -> None:
        legacy_lock_dir = self.resolve(".crt-command-locks")
        if legacy_lock_dir.exists():
            with suppress(FileNotFoundError):
                shutil.rmtree(legacy_lock_dir)
        with self._owned_connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS crt_command_receipts (
                    owner_id TEXT NOT NULL,
                    key_digest TEXT NOT NULL,
                    command TEXT NOT NULL,
                    normalized_route TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('pending', 'committed', 'expired')),
                    resource_id TEXT NOT NULL,
                    base_revision INTEGER,
                    target_revision INTEGER,
                    response_status INTEGER,
                    response_json TEXT,
                    created_at TEXT NOT NULL,
                    committed_at TEXT,
                    expires_at TEXT NOT NULL,
                    pending_target_snapshot TEXT,
                    PRIMARY KEY (owner_id, key_digest)
                );
                CREATE INDEX IF NOT EXISTS idx_crt_command_expiry
                    ON crt_command_receipts (expires_at);
                """)
            # Commands recheck the live account under the owner lock. Remove
            # the superseded guard table so purge retains no owner identifier.
            connection.execute("DROP TABLE IF EXISTS crt_purged_owners")
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(crt_command_receipts)"
                ).fetchall()
            }
            table_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' "
                "AND name = 'crt_command_receipts'"
            ).fetchone()[0]
            needs_pending_snapshot = "pending_target_snapshot" not in columns
            needs_expired_state = "'expired'" not in table_sql
            if needs_pending_snapshot or needs_expired_state:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    if needs_pending_snapshot:
                        connection.execute(
                            "ALTER TABLE crt_command_receipts "
                            "ADD COLUMN pending_target_snapshot TEXT"
                        )
                    if needs_expired_state:
                        self._migrate_expired_state(connection)
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

    @staticmethod
    def _migrate_expired_state(connection: sqlite3.Connection) -> None:
        """Rebuild the pre-tombstone table while preserving receipt history."""

        connection.execute("DROP INDEX IF EXISTS idx_crt_command_expiry")
        connection.execute(
            "ALTER TABLE crt_command_receipts RENAME TO crt_command_receipts_legacy"
        )
        connection.execute("""
            CREATE TABLE crt_command_receipts (
                owner_id TEXT NOT NULL,
                key_digest TEXT NOT NULL,
                command TEXT NOT NULL,
                normalized_route TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('pending', 'committed', 'expired')),
                resource_id TEXT NOT NULL,
                base_revision INTEGER,
                target_revision INTEGER,
                response_status INTEGER,
                response_json TEXT,
                created_at TEXT NOT NULL,
                committed_at TEXT,
                expires_at TEXT NOT NULL,
                pending_target_snapshot TEXT,
                PRIMARY KEY (owner_id, key_digest)
            )
            """)
        connection.execute("""
            INSERT INTO crt_command_receipts (
                owner_id, key_digest, command, normalized_route, request_hash,
                state, resource_id, base_revision, target_revision, response_status,
                response_json, created_at, committed_at, expires_at,
                pending_target_snapshot
            )
            SELECT owner_id, key_digest, command, normalized_route, request_hash,
                   state, resource_id, base_revision, target_revision, response_status,
                   response_json, created_at, committed_at, expires_at,
                   pending_target_snapshot
              FROM crt_command_receipts_legacy
            """)
        connection.execute("DROP TABLE crt_command_receipts_legacy")
        connection.execute(
            "CREATE INDEX idx_crt_command_expiry "
            "ON crt_command_receipts (expires_at)"
        )

    def get(self, *, owner_id: str, key_digest: str) -> CrtCommandReceipt | None:
        with self._connection(self._thread_state) as connection:
            row = connection.execute(
                """
                SELECT owner_id, key_digest, command, normalized_route, request_hash,
                       state, resource_id, base_revision, target_revision,
                       response_status, response_json, created_at, committed_at,
                       expires_at, pending_target_snapshot
                  FROM crt_command_receipts
                 WHERE owner_id = ? AND key_digest = ?
                """,
                (owner_id, key_digest),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_pending(self) -> list[CrtCommandReceipt]:
        """Return pending commands for crash reconciliation at startup."""

        with self._connection(self._thread_state) as connection:
            rows = connection.execute("""
                SELECT owner_id, key_digest, command, normalized_route, request_hash,
                       state, resource_id, base_revision, target_revision,
                       response_status, response_json, created_at, committed_at,
                       expires_at, pending_target_snapshot
                  FROM crt_command_receipts
                 WHERE state = 'pending'
                 ORDER BY created_at
                """).fetchall()
        pending: list[CrtCommandReceipt] = []
        for row in rows:
            try:
                pending.append(self._from_row(row))
            except (TypeError, ValueError):
                # Leave malformed rows pending for an operator/forward fix;
                # one bad row must not block independent reconciliation.
                continue
        return pending

    def get_pending_for_resource(
        self, *, owner_id: str, resource_id: str, exclude_key_digest: str
    ) -> CrtCommandReceipt | None:
        """Return another pending command that owns the resource guard."""

        with self._connection(self._thread_state) as connection:
            row = connection.execute(
                """
                SELECT owner_id, key_digest, command, normalized_route, request_hash,
                       state, resource_id, base_revision, target_revision,
                       response_status, response_json, created_at, committed_at,
                       expires_at, pending_target_snapshot
                  FROM crt_command_receipts
                 WHERE owner_id = ? AND resource_id = ? AND key_digest <> ?
                   AND state = 'pending'
                 ORDER BY created_at
                 LIMIT 1
                """,
                (owner_id, resource_id, exclude_key_digest),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def insert_pending(self, receipt: CrtCommandReceipt) -> None:
        if receipt.state != "pending":
            raise ValueError("CRT pending receipts must have pending state")
        try:
            with self._connection(self._thread_state) as connection:
                connection.execute(
                    """
                    INSERT INTO crt_command_receipts (
                        owner_id, key_digest, command, normalized_route,
                        request_hash, state, resource_id, base_revision,
                        target_revision, response_status, response_json,
                        created_at, committed_at, expires_at, pending_target_snapshot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL, ?, ?)
                    """,
                    (
                        receipt.owner_id,
                        receipt.key_digest,
                        receipt.command,
                        receipt.normalized_route,
                        receipt.request_hash,
                        receipt.state,
                        receipt.resource_id,
                        receipt.base_revision,
                        receipt.target_revision,
                        receipt.created_at.isoformat(),
                        receipt.expires_at.isoformat(),
                        receipt.pending_target_snapshot,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("CRT command", receipt.key_digest) from exc
        except sqlite3.Error as exc:
            raise RepositoryError(
                "CRT command storage failed while creating receipt."
            ) from exc

    def commit(
        self,
        *,
        owner_id: str,
        key_digest: str,
        response_status: int,
        response_json: str,
        committed_at: datetime | None = None,
    ) -> CrtCommandReceipt:
        committed = committed_at or utcnow()
        expires = committed + CRT_COMMAND_RETENTION
        with self._connection(self._thread_state) as connection:
            cursor = connection.execute(
                """
                UPDATE crt_command_receipts
                   SET state = 'committed', response_status = ?, response_json = ?,
                       committed_at = ?, expires_at = ?, pending_target_snapshot = NULL
                 WHERE owner_id = ? AND key_digest = ? AND state = 'pending'
                """,
                (
                    response_status,
                    response_json,
                    committed.isoformat(),
                    expires.isoformat(),
                    owner_id,
                    key_digest,
                ),
            )
            if cursor.rowcount != 1:
                raise ConflictError(
                    "CRT command", key_digest, "CRT command receipt is not pending."
                )
        receipt = self.get(owner_id=owner_id, key_digest=key_digest)
        if receipt is None:  # pragma: no cover - guarded by the update above
            raise RepositoryError("CRT command receipt disappeared after commit.")
        return receipt

    def purge_expired(self, *, now: datetime | None = None) -> int:
        cutoff = (now or utcnow()).isoformat()
        with self._process_lock, self._owned_connection() as connection:
            cursor = connection.execute(
                """
                UPDATE crt_command_receipts
                   SET state = 'expired', response_status = NULL,
                       response_json = NULL, pending_target_snapshot = NULL
                 WHERE state = 'committed' AND expires_at <= ?
                """,
                (cutoff,),
            )
            return cursor.rowcount

    def delete_for_tree_except(
        self, *, owner_id: str, resource_id: str, key_digest: str
    ) -> None:
        """Remove content-bearing receipts before retaining a delete tombstone."""

        with self._connection(self._thread_state) as connection:
            connection.execute(
                """
                UPDATE crt_command_receipts
                   SET state = 'expired', response_status = NULL,
                       response_json = NULL, pending_target_snapshot = NULL
                 WHERE owner_id = ? AND resource_id = ? AND key_digest <> ?
                """,
                (owner_id, resource_id, key_digest),
            )

    def delete_all_for_owner_locked(self, *, owner_id: str) -> None:
        """Delete owner receipts while the caller holds ``command_lock``."""

        with self._owned_connection() as connection:
            connection.execute(
                "DELETE FROM crt_command_receipts WHERE owner_id = ?",
                (owner_id,),
            )

    def delete_all_for_owner(self, *, owner_id: str) -> None:
        """Erase every CRT receipt belonging to an account.

        Account purge shares the process guard with command processing so a
        receipt cannot be committed while its owner is being erased. The
        delete is idempotent, allowing a crash-safe purge retry.
        """

        with self.command_lock(owner_id):
            self.delete_all_for_owner_locked(owner_id=owner_id)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> CrtCommandReceipt:
        return CrtCommandReceipt(
            owner_id=row["owner_id"],
            key_digest=row["key_digest"],
            command=row["command"],
            normalized_route=row["normalized_route"],
            request_hash=row["request_hash"],
            state=row["state"],
            resource_id=row["resource_id"],
            base_revision=row["base_revision"],
            target_revision=row["target_revision"],
            response_status=row["response_status"],
            response_json=row["response_json"],
            created_at=datetime.fromisoformat(row["created_at"]),
            committed_at=(
                datetime.fromisoformat(row["committed_at"])
                if row["committed_at"]
                else None
            ),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            pending_target_snapshot=row["pending_target_snapshot"],
        )

    @staticmethod
    def encode_response(payload: dict[str, object]) -> str:
        """Encode a canonical response without retaining request content."""

        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


__all__ = ["CRT_COMMAND_RETENTION", "CrtCommandReceipt", "CrtCommandRepository"]
