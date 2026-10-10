"""Transaction-bound scope counters, public final changes and deletion versions.

026-FR-006: this module never opens a connection or commits. Version metadata
has no domain payload; the feed is an expiring replication log, not an aggregate.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime, timedelta
from sqlite3 import Connection
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.exceptions import RepositoryError
from app.modules.tasks.rust_adapter import RustCore

if TYPE_CHECKING:
    from .unit_of_work import OwnerUnitOfWork

SYNC_TABLES = (
    "sync_change_records",
    "sync_change_transactions",
    "sync_legacy_keys",
    "sync_command_receipts",
    "sync_record_versions",
    "sync_scopes",
)

# Use individual statements: executescript would commit an open SQLite unit.
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS sync_scopes (owner_id TEXT PRIMARY KEY, "
    "server_generation TEXT NOT NULL, feed_generation TEXT NOT NULL, "
    "access_generation TEXT NOT NULL, storage_epoch TEXT NOT NULL, "
    "admission_open INTEGER NOT NULL, commit_seq TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS sync_command_receipts (owner_id TEXT NOT NULL, "
    "command_id TEXT NOT NULL, writer_origin TEXT NOT NULL, fingerprint TEXT NOT NULL, "
    "metadata TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL, "
    "PRIMARY KEY(owner_id, command_id))",
    "CREATE TABLE IF NOT EXISTS sync_legacy_keys (owner_id TEXT NOT NULL, "
    "key_digest TEXT NOT NULL, command_id TEXT NOT NULL, PRIMARY KEY(owner_id,key_digest))",
    "CREATE TABLE IF NOT EXISTS sync_record_versions (owner_id TEXT NOT NULL, "
    "entity_type TEXT NOT NULL, record_key TEXT NOT NULL, record_version TEXT NOT NULL, "
    "deleted INTEGER NOT NULL, PRIMARY KEY(owner_id,entity_type,record_key))",
    "CREATE TABLE IF NOT EXISTS sync_change_transactions (owner_id TEXT NOT NULL, "
    "commit_seq TEXT NOT NULL, transaction_id TEXT NOT NULL, source_command_id TEXT NOT NULL, "
    "committed_at TEXT NOT NULL, PRIMARY KEY(owner_id,commit_seq), "
    "UNIQUE(owner_id,transaction_id), UNIQUE(owner_id,source_command_id))",
    "CREATE TABLE IF NOT EXISTS sync_change_records (owner_id TEXT NOT NULL, "
    "commit_seq TEXT NOT NULL, entity_type TEXT NOT NULL, record_key TEXT NOT NULL, "
    "record_version TEXT NOT NULL, edit_revision TEXT, operation TEXT NOT NULL, "
    "value TEXT, source_expires_at TEXT, "
    "PRIMARY KEY(owner_id,commit_seq,entity_type,record_key), "
    "FOREIGN KEY(owner_id,commit_seq) REFERENCES sync_change_transactions(owner_id,commit_seq) "
    "ON DELETE CASCADE)",
    "CREATE INDEX IF NOT EXISTS sync_receipt_expiry ON sync_command_receipts(owner_id,expires_at)",
    "CREATE INDEX IF NOT EXISTS sync_change_record_history ON sync_change_records(owner_id,entity_type,record_key)",
)


def initialize(conn: Connection) -> None:
    for statement in _SCHEMA:
        conn.execute(statement)


def purge_owner(conn: Connection, owner_id: str) -> None:
    for table in SYNC_TABLES:
        conn.execute(
            f"DELETE FROM {table} WHERE owner_id = ?",  # noqa: S608 -- fixed internal table tuple
            (owner_id,),
        )
    # A bare TaskRepository can exist before the job adapter initializes its
    # table. When present, owner-bound intents are part of this same purge.
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
    ).fetchone():
        conn.execute("DELETE FROM jobs WHERE scope = ?", (owner_id,))


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class AtomicChangeLog[ConnectionT](ABC):
    def __init__(self, core: RustCore) -> None:
        self._core = core

    def append(
        self,
        unit: OwnerUnitOfWork[ConnectionT],
        command_id: str,
        changes: Sequence[dict[str, Any]],
        *,
        now: datetime,
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Project Rust-decided changes, publish final keys, allocate commit order."""
        prepared = json.loads(
            self._core.persistence("changes", encode(changes).encode())
        )
        final = {
            (row["entity_type"], encode(row["record_key"])): row for row in prepared
        }
        if not final:
            return None, []
        sequence = self._next_sequence(unit)
        public, versions = [], []
        for (entity_type, key), row in final.items():
            version = self._next_version(
                unit, entity_type, key, deleted=row["operation"] == "tombstone"
            )
            value = row.get("value")
            change = {**row, "value": value, "record_version": version}
            if value is not None and "revision" in value:
                change["edit_revision"] = value["revision"]
            public.append(change)
            versions.append(
                {
                    k: change[k]
                    for k in (
                        "entity_type",
                        "record_key",
                        "record_version",
                        "edit_revision",
                    )
                    if k in change
                }
            )
        transaction = json.loads(
            self._core.persistence(
                "transaction",
                encode(
                    {
                        "transaction_id": str(uuid4()),
                        "commit_seq": sequence,
                        "source_command_id": command_id,
                        "changes": public,
                    }
                ).encode(),
            )
        )
        self._insert_transaction(unit, transaction, now=now)
        for row in transaction["changes"]:
            self._insert_change(unit, sequence, row)
            if row["operation"] == "tombstone":
                self.redact_record(unit, row["entity_type"], row["record_key"])
        return sequence, versions

    @abstractmethod
    def _next_sequence(self, unit: OwnerUnitOfWork[ConnectionT]) -> str:
        raise NotImplementedError

    @abstractmethod
    def _next_version(
        self,
        unit: OwnerUnitOfWork[ConnectionT],
        entity_type: str,
        key: str,
        *,
        deleted: bool,
    ) -> str:
        raise NotImplementedError

    @abstractmethod
    def _insert_transaction(
        self,
        unit: OwnerUnitOfWork[ConnectionT],
        transaction: dict[str, Any],
        *,
        now: datetime,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def _insert_change(
        self, unit: OwnerUnitOfWork[ConnectionT], sequence: str, row: dict[str, Any]
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def redact_record(
        self,
        unit: OwnerUnitOfWork[ConnectionT],
        entity_type: str,
        record_key: list[str],
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def prune(self, unit: OwnerUnitOfWork[ConnectionT], *, now: datetime) -> None:
        raise NotImplementedError

    @abstractmethod
    def _transactions(
        self, unit: OwnerUnitOfWork[ConnectionT], *, after: str = "0"
    ) -> list[dict[str, Any]]:
        raise NotImplementedError


class ChangeLog(AtomicChangeLog[Connection]):
    """SQLite storage hooks; the shared policy stays in AtomicChangeLog."""

    def _next_sequence(self, unit: OwnerUnitOfWork[Connection]) -> str:
        conn, owner = unit.connection, unit.owner_id
        scope = conn.execute(
            "SELECT commit_seq FROM sync_scopes WHERE owner_id = ?", (owner,)
        ).fetchone()
        sequence = str(int(scope["commit_seq"]) + 1)
        conn.execute(
            "UPDATE sync_scopes SET commit_seq = ? WHERE owner_id = ?",
            (sequence, owner),
        )
        return sequence

    def _next_version(
        self,
        unit: OwnerUnitOfWork[Connection],
        entity_type: str,
        key: str,
        *,
        deleted: bool,
    ) -> str:
        conn, owner = unit.connection, unit.owner_id
        prior = conn.execute(
            "SELECT record_version FROM sync_record_versions WHERE owner_id = ? AND entity_type = ? AND record_key = ?",
            (owner, entity_type, key),
        ).fetchone()
        version = str(int(prior["record_version"]) + 1 if prior else 1)
        conn.execute(
            "INSERT INTO sync_record_versions VALUES (?,?,?,?,?) ON CONFLICT(owner_id,entity_type,record_key) DO UPDATE SET record_version=excluded.record_version,deleted=excluded.deleted",
            (owner, entity_type, key, version, int(deleted)),
        )
        return version

    def _insert_transaction(
        self,
        unit: OwnerUnitOfWork[Connection],
        transaction: dict[str, Any],
        *,
        now: datetime,
    ) -> None:
        unit.connection.execute(
            "INSERT INTO sync_change_transactions VALUES (?,?,?,?,?)",
            (
                unit.owner_id,
                transaction["commit_seq"],
                transaction["transaction_id"],
                transaction["source_command_id"],
                now.isoformat(),
            ),
        )

    def _insert_change(
        self, unit: OwnerUnitOfWork[Connection], sequence: str, row: dict[str, Any]
    ) -> None:
        unit.connection.execute(
            "INSERT INTO sync_change_records VALUES (?,?,?,?,?,?,?,?,?)",
            (
                unit.owner_id,
                sequence,
                row["entity_type"],
                encode(row["record_key"]),
                row["record_version"],
                row.get("edit_revision"),
                row["operation"],
                encode(row["value"]) if row["value"] is not None else None,
                None,
            ),
        )

    def redact_record(
        self,
        unit: OwnerUnitOfWork[Connection],
        entity_type: str,
        record_key: list[str],
    ) -> None:
        """Deleted content cannot remain readable through history or receipts.

        Redact entire owner receipt results conservatively: results may embed
        related text without a direct result-version reference. Protected IDs,
        outcomes and aliases remain. A delta consumer must reset after redaction.
        """
        conn, owner = unit.connection, unit.owner_id
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL WHERE owner_id = ?",
            (owner,),
        )
        # Removing an old upsert would make that transaction incomplete. Invalidate
        # the feed generation instead; later transports must require a new base.
        conn.execute(
            "UPDATE sync_change_records SET value = NULL WHERE owner_id = ? "
            "AND entity_type = ? AND record_key = ?",
            (owner, entity_type, encode(record_key)),
        )
        conn.execute(
            "UPDATE sync_scopes SET feed_generation = ? WHERE owner_id = ?",
            (str(uuid4()), owner),
        )

    def prune(self, unit: OwnerUnitOfWork[Connection], *, now: datetime) -> None:
        """Remove expired copies; keep the content-free final deletion versions."""
        conn, owner = unit.connection, unit.owner_id
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL WHERE owner_id = ? AND expires_at <= ?",
            (owner, now.isoformat()),
        )
        conn.execute(
            "DELETE FROM sync_change_transactions WHERE owner_id = ? AND committed_at <= ?",
            (owner, (now - timedelta(days=90)).isoformat()),
        )

    def _transactions(
        self, unit: OwnerUnitOfWork[Connection], *, after: str = "0"
    ) -> list[dict[str, Any]]:
        """Internal store port; transport authority/cursors belong to later slices."""
        conn, owner = unit.connection, unit.owner_id
        headers = conn.execute(
            "SELECT * FROM sync_change_transactions WHERE owner_id = ? "
            "AND (length(commit_seq) > ? OR (length(commit_seq) = ? AND commit_seq > ?)) "
            "ORDER BY length(commit_seq),commit_seq",
            (owner, len(after), len(after), after),
        ).fetchall()
        result = []
        for header in headers:
            rows = conn.execute(
                "SELECT * FROM sync_change_records WHERE owner_id = ? AND commit_seq = ?",
                (owner, header["commit_seq"]),
            ).fetchall()
            if any(r["operation"] == "upsert" and r["value"] is None for r in rows):
                raise RepositoryError("RESET_REQUIRED")
            changes = [
                {
                    "entity_type": r["entity_type"],
                    "record_key": json.loads(r["record_key"]),
                    "record_version": r["record_version"],
                    "operation": r["operation"],
                    "value": json.loads(r["value"]) if r["value"] else None,
                    **(
                        {"edit_revision": r["edit_revision"]}
                        if r["edit_revision"]
                        else {}
                    ),
                }
                for r in rows
            ]
            result.append(
                {
                    "transaction_id": header["transaction_id"],
                    "commit_seq": header["commit_seq"],
                    "source_command_id": header["source_command_id"],
                    "changes": changes,
                }
            )
        return result
