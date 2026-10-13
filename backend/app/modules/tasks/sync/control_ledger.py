"""Durable deletion and revocation decisions kept outside the task backups (026 PR-52).

026-FR-010/011/015: a restored task image must not resurrect a purged account or a
revoked session, so those decisions live in their own SQLite file, which a task
backup or WAL restore never rolls back. An entry holds only an owner ID, a kind and
a generation: no content. It lives while an affected restore point can still be
recovered (``HORIZON``). A purge marker is the one owner-linked entry that outlives
the horizon: it is erased only by ``complete_purge``, after the restore points that
could contain the account are retired. Erasing leaves a content-free tombstone so
the sequence stays gapless, which is what lets a restore prove completeness.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

HORIZON = timedelta(days=7)
PURGE = "purge"
REVOKE_SESSIONS = "revoke_sessions"
EPOCH = "epoch"
RETIRED = "retired"
CLOSED = "closed"
REPLAYED = "replayed"
_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS control_entries (seq INTEGER PRIMARY KEY "
    "AUTOINCREMENT, kind TEXT NOT NULL, owner_id TEXT, auth_version INTEGER, "
    "recorded_at TEXT NOT NULL, detail TEXT)",
    "CREATE TABLE IF NOT EXISTS control_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)


class LedgerIncomplete(Exception):
    """Completeness of the control history cannot be proven: stay closed."""


@dataclass(frozen=True, slots=True)
class ControlEntry:
    seq: int
    kind: str
    owner_id: str | None
    auth_version: int | None
    recorded_at: datetime
    detail: str | None = None


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


class ControlLedger:
    """Append-only, gapless control history in its own file."""

    def __init__(self, path: Path, *, now: datetime) -> None:
        self._path = path
        with self._open() as conn:
            for statement in _SCHEMA:
                conn.execute(statement)
            # Coverage starts when the ledger first existed: an older backup
            # predates any decision this file could have kept.
            conn.execute(
                "INSERT OR IGNORE INTO control_meta VALUES ('covered_from', ?)",
                (_stamp(now),),
            )

    @contextmanager
    def _open(self) -> Iterator[sqlite3.Connection]:
        """One immediate transaction: commit on success, roll back on error."""
        conn = sqlite3.connect(self._path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA synchronous = FULL")
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    def record_purge(self, owner_id: str, *, now: datetime) -> None:
        """Mark the owner purged before any destructive step; a repeat is a no-op."""
        with self._open() as conn:
            known = conn.execute(
                "SELECT 1 FROM control_entries WHERE kind = ? AND owner_id = ?",
                (PURGE, owner_id),
            ).fetchone()
            if known is None:
                self._append(conn, PURGE, owner_id, None, now)

    def record_revocation(
        self, owner_id: str, auth_version: int | None, *, now: datetime
    ) -> None:
        """Mark every session of the owner revoked as of ``auth_version``."""
        with self._open() as conn:
            self._append(conn, REVOKE_SESSIONS, owner_id, auth_version, now)

    @staticmethod
    def _append(
        conn: sqlite3.Connection,
        kind: str,
        owner_id: str | None,
        auth_version: int | None,
        now: datetime,
        detail: str | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO control_entries(kind, owner_id, auth_version, recorded_at, "
            "detail) VALUES (?,?,?,?,?)",
            (kind, owner_id, auth_version, _stamp(now), detail),
        )

    def record_epoch(
        self, owner_id: str, device_id: str, device_epoch: str, *, now: datetime
    ) -> None:
        """Remember a registered epoch so a restore older than it can close it."""
        with self._open() as conn:
            self._append(
                conn, EPOCH, owner_id, None, now, json.dumps([device_id, device_epoch])
            )

    def complete_purge(self, owner_id: str, retire: Callable[[str], None]) -> None:
        """Retire the owner's restore points, then erase the owner-linked marker.

        ``retire`` removes the backup/WAL/transfer artifacts that could still hold
        the account. If it raises, the marker stays and the purge is incomplete.
        """
        retire(owner_id)
        with self._open() as conn:
            conn.execute(
                "UPDATE control_entries SET kind = ?, owner_id = NULL, "
                "auth_version = NULL, detail = NULL "
                "WHERE kind IN (?, ?) AND owner_id = ?",
                (RETIRED, PURGE, EPOCH, owner_id),
            )

    def prune(
        self, now: datetime, *, keep_owner: Callable[[str], bool] = lambda _: True
    ) -> int:
        """Retire entries whose restore points are gone; advance coverage.

        Platform snapshots cannot be deleted by the app; they expire within
        ``HORIZON``. A purge marker therefore retires here once it is older than
        the horizon *and* ``keep_owner`` says the account is gone. The default
        keeps every marker.
        """
        cutoff = _stamp(now - HORIZON)
        with self._open() as conn:
            for row in conn.execute(
                "SELECT DISTINCT owner_id FROM control_entries "
                "WHERE kind = ? AND recorded_at <= ?",
                (PURGE, cutoff),
            ).fetchall():
                if not keep_owner(row["owner_id"]):
                    conn.execute(
                        "UPDATE control_entries SET kind = ?, owner_id = NULL, "
                        "auth_version = NULL, detail = NULL "
                        "WHERE kind IN (?, ?) AND owner_id = ?",
                        (RETIRED, PURGE, EPOCH, row["owner_id"]),
                    )
            stale = conn.execute(
                "SELECT max(recorded_at) FROM control_entries "
                "WHERE kind IN (?, ?) AND recorded_at <= ?",
                (REVOKE_SESSIONS, EPOCH, cutoff),
            ).fetchone()[0]
            if stale is None:
                return 0
            count = conn.execute(
                "UPDATE control_entries SET kind = ?, owner_id = NULL, "
                "auth_version = NULL, detail = NULL "
                "WHERE kind IN (?, ?) AND recorded_at <= ?",
                (RETIRED, REVOKE_SESSIONS, EPOCH, cutoff),
            ).rowcount
            conn.execute(
                "UPDATE control_meta SET value = max(value, ?) "
                "WHERE key = 'covered_from'",
                (stale,),
            )
            return count

    def entries(self) -> list[ControlEntry]:
        with self._open() as conn:
            return [
                ControlEntry(
                    row["seq"],
                    row["kind"],
                    row["owner_id"],
                    row["auth_version"],
                    datetime.fromisoformat(row["recorded_at"]),
                    row["detail"],
                )
                for row in conn.execute("SELECT * FROM control_entries ORDER BY seq")
            ]

    def prove_complete(self, backup_taken_at: datetime) -> list[ControlEntry]:
        """Every decision after the backup, or ``LedgerIncomplete``.

        The proof uses only this file and the backup's timestamp, never the
        restored image: the ledger must have existed and not yet retired anything
        newer than the backup, and its sequence must have no hole.
        """
        with self._open() as conn:
            covered = conn.execute(
                "SELECT value FROM control_meta WHERE key = 'covered_from'"
            ).fetchone()
        entries = self.entries()
        if covered is None or backup_taken_at.astimezone(UTC) < datetime.fromisoformat(
            covered["value"]
        ):
            raise LedgerIncomplete("backup predates ledger coverage")
        if entries and [entry.seq for entry in entries] != list(
            range(entries[0].seq, entries[0].seq + len(entries))
        ):
            raise LedgerIncomplete("control sequence has a gap")
        return [e for e in entries if e.owner_id is not None]

    def state(self) -> str | None:
        with self._open() as conn:
            row = conn.execute(
                "SELECT value FROM control_meta WHERE key = 'restore_state'"
            ).fetchone()
        return None if row is None else str(row["value"])

    def set_state(self, state: str | None) -> None:
        with self._open() as conn:
            if state is None:
                conn.execute("DELETE FROM control_meta WHERE key = 'restore_state'")
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO control_meta VALUES ('restore_state', ?)",
                    (state,),
                )
