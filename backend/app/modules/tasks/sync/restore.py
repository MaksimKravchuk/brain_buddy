"""Restore of a task backup with access closed (spec 026 PR-52).

026-FR-005/010/011/015: a restored image is never served until every later
purge and revocation in the control ledger is replayed, uncertain sessions are
revoked, the server/feed generations are new and every device epoch is closed.
If completeness cannot be proven, access stays closed. Losing confirmed commits
is an incident: the report never reads as an ordinary successful reset, and
external effects (provider calls, mail) are reconciled separately before
``reopen``. A receipt already lost cannot provide exactly-once retroactively;
surviving client intents continue only under a new epoch.

RPO <= 24 h / RTO <= 4 h are verified on the reference workload in the pilot;
see ``specs/026-rust-core-sync/recovery.md``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .control_ledger import (
    CLOSED,
    EPOCH,
    PURGE,
    REPLAYED,
    REVOKE_SESSIONS,
    ControlEntry,
    ControlLedger,
)

INCIDENT = "INCIDENT_RECONCILIATION_REQUIRED"
RESTORE_CLOSE_REASON = "restore"


class RestoreEffects(Protocol):
    """The two owner-wide actions a replayed decision needs."""

    def purge_owner(self, owner_id: str) -> None: ...

    def revoke_sessions(self, owner_id: str) -> None: ...


class RestoreNotReady(Exception):
    """``reopen`` was asked before replay finished or effects were reconciled."""


@dataclass(frozen=True, slots=True)
class RestoreReport:
    outcome: str
    purged: tuple[str, ...]
    revoked: tuple[str, ...]
    closed_epochs: int


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _owners(decisions: list[ControlEntry], kind: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(e.owner_id for e in decisions if e.kind == kind and e.owner_id)
    )


def restore_control_plane(
    db_path: Path,
    ledger: ControlLedger,
    effects: RestoreEffects,
    *,
    backup_taken_at: datetime,
    now: datetime,
    mint: Callable[[], str] = lambda: str(uuid4()),
) -> RestoreReport:
    """Make a freshly restored task DB safe; leaves access closed.

    Idempotent: a crash anywhere keeps access closed and a rerun finishes.
    Raises ``LedgerIncomplete`` (access still closed) when the history after
    ``backup_taken_at`` cannot be proven complete.
    """
    with closing(_connect(db_path)) as conn, conn:
        conn.execute("UPDATE sync_scopes SET admission_open = 0")
    ledger.set_state(CLOSED)
    decisions = ledger.prove_complete(backup_taken_at)
    purged = _owners(decisions, PURGE)
    revoked = _owners(decisions, REVOKE_SESSIONS)
    for owner_id in purged:
        effects.purge_owner(owner_id)
    with closing(_connect(db_path)) as conn, conn:
        owners = [r[0] for r in conn.execute("SELECT owner_id FROM sync_scopes")]
    # Every session the image could know about is uncertain: sign in again.
    for owner_id in dict.fromkeys([*revoked, *owners]):
        effects.revoke_sessions(owner_id)
    stamp = now.astimezone(UTC).isoformat()
    with closing(_connect(db_path)) as conn, conn:
        for owner_id in owners:
            conn.execute(
                "UPDATE sync_scopes SET server_generation = ?, "
                "feed_generation = ?, access_generation = ? WHERE owner_id = ?",
                (mint(), mint(), mint(), owner_id),
            )
        # An epoch registered after the restore point has no row in this image:
        # carry it as closed, so the device reads EPOCH_CLOSED, never a 404.
        for entry in decisions:
            if entry.kind != EPOCH or entry.owner_id in purged or not entry.detail:
                continue
            device_id, device_epoch = json.loads(entry.detail)
            conn.execute(
                "INSERT OR IGNORE INTO sync_devices VALUES (?,?,?)",
                (device_id, entry.owner_id, stamp),
            )
            conn.execute(
                "INSERT OR IGNORE INTO sync_device_epochs VALUES (?,?,?,?,?,?,?,?)",
                (
                    device_id,
                    device_epoch,
                    entry.owner_id,
                    "closed",
                    RESTORE_CLOSE_REASON,
                    stamp,
                    stamp,
                    RESTORE_CLOSE_REASON,
                ),
            )
        closed = conn.execute(
            "UPDATE sync_device_epochs SET status = 'closed', closed_at = ?, "
            "close_reason = ? WHERE status = 'active'",
            (stamp, RESTORE_CLOSE_REASON),
        ).rowcount
    ledger.set_state(REPLAYED)
    return RestoreReport(INCIDENT, purged, revoked, closed)


def reopen(
    db_path: Path, ledger: ControlLedger, *, external_effects_reconciled: bool
) -> None:
    """Admit owners again, only after replay and external-effect reconciliation."""
    if ledger.state() != REPLAYED or not external_effects_reconciled:
        raise RestoreNotReady("restore is not replayed and reconciled")
    with closing(_connect(db_path)) as conn, conn:
        conn.execute("UPDATE sync_scopes SET admission_open = 1")
    ledger.set_state(None)
