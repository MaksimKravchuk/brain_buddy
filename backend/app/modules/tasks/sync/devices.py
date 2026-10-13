"""Device ownership and immutable intake-epoch registration (spec 026 PR-30).

026-FR-010/012: a device is bound to one owner on first registration and cannot
be rebound; an epoch ID is registered idempotently, never reopened once closed,
and only an *unseen* device command is gated on it. A known command is replayed
by the receipt store before this fence runs, so closure never hides an outcome.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from sqlite3 import Connection
from typing import Any

from app.core.logging import get_correlation_id

from .authority import require_owned
from .control_ledger import ControlLedger
from .receipts import (
    Authority,
    CommandReceipts,
    CommandUnits,
    ReceiptCommand,
    SyncCommandError,
)
from .unit_of_work import OwnerUnitOfWork

ACTIVE = "active"
CLOSED = "closed"
GENERATION_CHANGED = "generation_changed"
_MAX_ID = 128


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_ID:
        raise SyncCommandError("INVALID_REQUEST")
    return value


class DeviceEpochs:
    """Registration, closure and the unseen-command epoch fence."""

    def __init__(
        self,
        receipts: CommandReceipts[Connection],
        ledger: ControlLedger | None = None,
    ) -> None:
        self._receipts = receipts
        self._ledger = ledger

    def register(  # noqa: PLR0913 - the registration body's fields
        self,
        uow: CommandUnits[Connection],
        owner_id: str,
        authorize: Authority[Connection],
        *,
        device_id: str,
        device_epoch: str,
        protocol_version: str,
        now: datetime,
    ) -> dict[str, Any]:
        """Confirm ``device_epoch`` for the owner; a repeat returns it unchanged."""
        device_id, device_epoch = _identifier(device_id), _identifier(device_epoch)
        _identifier(protocol_version)
        stamp = now.astimezone(UTC).isoformat()
        stale = False
        with uow.begin(owner_id) as unit:
            current = self._receipts.admit(unit, authorize)
            conn = unit.connection
            bound = conn.execute(
                "SELECT owner_id FROM sync_devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            if bound is None:
                conn.execute(
                    "INSERT INTO sync_devices VALUES (?,?,?)",
                    (device_id, owner_id, stamp),
                )
            else:
                require_owned(owner_id, bound["owner_id"])
            epoch = conn.execute(
                "SELECT status, server_generation FROM sync_device_epochs "
                "WHERE device_id = ? AND device_epoch = ?",
                (device_id, device_epoch),
            ).fetchone()
            if epoch is None:
                if self._ledger is not None:
                    # Outside the task DB, so a restore older than this
                    # registration can still close the epoch.
                    self._ledger.record_epoch(
                        owner_id, device_id, device_epoch, now=now
                    )
                conn.execute(
                    "INSERT INTO sync_device_epochs VALUES (?,?,?,?,?,?,NULL,NULL)",
                    (
                        device_id,
                        device_epoch,
                        owner_id,
                        ACTIVE,
                        current.server_generation,
                        stamp,
                    ),
                )
            elif epoch["status"] != ACTIVE:
                raise SyncCommandError("EPOCH_CLOSED")
            elif epoch["server_generation"] != current.server_generation:
                # Registered before a restore/generation change: it keeps
                # answering RESET_REQUIRED, so retire it and make the client
                # move to a fresh epoch instead of looping on this one.
                conn.execute(
                    "UPDATE sync_device_epochs SET status = ?, closed_at = ?, "
                    "close_reason = ? WHERE device_id = ? AND device_epoch = ?",
                    (CLOSED, stamp, GENERATION_CHANGED, device_id, device_epoch),
                )
                stale = True
            if not stale:
                return {
                    "device_id": device_id,
                    "device_epoch": device_epoch,
                    "epoch_status": ACTIVE,
                    "scope_id": owner_id,
                    "server_generation": current.server_generation,
                    "server_now": stamp,
                    "correlation_id": get_correlation_id(),
                }
        # Raised after the unit committed, so the closure above persists.
        raise SyncCommandError("EPOCH_CLOSED")

    def close(  # noqa: PLR0913 - the closure's fields
        self,
        unit: OwnerUnitOfWork[Connection],
        authorize: Authority[Connection],
        *,
        device_id: str,
        device_epoch: str,
        reason: str,
        now: datetime,
    ) -> None:
        """Close an epoch of this owner's device; closing again keeps the first."""
        self._receipts.admit(unit, authorize)
        row = self._epoch(unit, device_id, device_epoch)
        if row["status"] == ACTIVE:
            unit.connection.execute(
                "UPDATE sync_device_epochs SET status = ?, closed_at = ?, "
                "close_reason = ? WHERE device_id = ? AND device_epoch = ?",
                (
                    CLOSED,
                    now.astimezone(UTC).isoformat(),
                    reason,
                    device_id,
                    device_epoch,
                ),
            )

    def admit_unseen(self, command: ReceiptCommand[Connection]) -> None:
        """Gate a *miss* from a device on its active epoch; replays pass untouched."""
        if command.replay is not None or command.request.origin != "device":
            return
        try:
            envelope = json.loads(command.request.wire)
            device_id = _identifier(envelope["device_id"])
            device_epoch = _identifier(envelope["device_epoch"])
        except KeyError, TypeError, ValueError:
            raise SyncCommandError("INVALID_REQUEST") from None
        row = self._epoch(command.unit, device_id, device_epoch)
        if row["status"] != ACTIVE:
            raise SyncCommandError("EPOCH_CLOSED")
        if row["server_generation"] != command.authority.server_generation:
            raise SyncCommandError("RESET_REQUIRED")

    @staticmethod
    def _epoch(
        unit: OwnerUnitOfWork[Connection], device_id: str, device_epoch: str
    ) -> Any:
        """The owner's epoch row; unknown and foreign IDs raise the same 404."""
        row = unit.connection.execute(
            "SELECT * FROM sync_device_epochs "
            "WHERE device_id = ? AND device_epoch = ?",
            (device_id, device_epoch),
        ).fetchone()
        require_owned(unit.owner_id, None if row is None else row["owner_id"])
        return row
