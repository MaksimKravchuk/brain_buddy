"""Absolute source expiry and independent retention for every sync copy (PR-50).

sync-v1 sections 5 and 6. A receipt, a feed after-image, a snapshot page and an
oversized-transaction transfer are copies of source content; none of them
extends the source's own deadline. Two rules apply together:

* **Reads fail closed** at the deadline (receipt lookup, delta, transfers and
  snapshots each check it themselves). This module supplies the deadline policy
  (:func:`source_expiry`) the feed stamps on a change, so there is something to
  check.
* **Cleanup runs on its own** (:class:`SyncRetention`): per owner, in a
  ``cleanup`` unit, with no authority or feature flag read, so an inactive
  owner, a deleted-pending owner and a flag-OFF rollout are all swept.

What expires, and what deliberately does not:

* an ordinary receipt's response content, 24 hours after commit. The content-free
  record -- fingerprint, outcome, ``commit_seq``, ``result_versions`` and the
  typed ``id_bindings`` -- stays until account purge, so a lost Smart Add ACK
  after the deadline still resolves its dependent alias from the retained
  binding, never from mutable names or membership;
* a Review decision's Undo content, seven days after the decision. The decision
  record survives; the expiring field is redacted from every retained feed
  payload and the redaction is published as an ordinary feed change;
* materialized snapshots and transfers holding a redacted record lose their pages
  (a late page reads ``RESET_REQUIRED``); they are never edited in place.

Not touched here: the legacy idempotency table, whose ``create_native_inbox_task``
commit record is Capture's until-purge replay source, and the separate CRT
receipt store. Neither is extended or shortened by this module.

Framework-free SQLite storage; it never opens its own write connection or commits:
the owner unit does.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection, OperationalError, connect
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid5

from app.modules.tasks.jobs.execution import StaleExecutorError

if TYPE_CHECKING:
    from pathlib import Path

    from .change_log import ChangeLog
    from .receipts import CommandUnits
    from .unit_of_work import OwnerUnitOfWork

logger = logging.getLogger(__name__)

#: The public Review decision field that is the advisory seven-day Undo window.
UNDO_FIELD: Final = "undo_available_until"
#: Entity types whose expiring content is one field a snapshot omits once elapsed.
FIELD_EXPIRY_ENTITIES: Final = frozenset({"review_decision"})
_NAMESPACE: Final = UUID("9c5d3a4e-6b1f-5c52-8d0a-026000000050")
_FEED_RETENTION: Final = timedelta(days=90)

type Json = dict[str, Any]


def instant(value: datetime) -> str:
    """A fixed-width instant, so stored values also order correctly as text."""
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def source_expiry(entity_type: str, value: Mapping[str, Any] | None) -> str | None:
    """The absolute deadline of the content a feed change carries, if any."""
    if entity_type == "review_decision" and value is not None:
        until = value.get(UNDO_FIELD)
        if isinstance(until, str):
            return until
    return None


def expire_value(
    entity_type: str, value: Mapping[str, Any], now: datetime
) -> Json | None:
    """``value`` without its expired content; ``None`` when nothing expired."""
    deadline = source_expiry(entity_type, value)
    if deadline is None or datetime.fromisoformat(deadline) > now:
        return None
    return {key: item for key, item in value.items() if key != UNDO_FIELD}


def redact_expired_receipts(conn: Connection, owner: str, now: datetime) -> int:
    """Drop response content of receipts past their expiry; keep the metadata.

    The content-free envelope (fingerprint, outcome, ``commit_seq``,
    ``result_versions``, ``id_bindings`` and the private typed refusal witness)
    is untouched; only the stored ``result`` goes and the receipt says so.
    """
    rows = conn.execute(
        "SELECT command_id, expires_at FROM sync_command_receipts "
        "WHERE owner_id = ? AND result IS NOT NULL",
        (owner,),
    ).fetchall()
    due = [
        r["command_id"] for r in rows if datetime.fromisoformat(r["expires_at"]) <= now
    ]
    for command_id in due:
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL, "
            "metadata = json_set(metadata, '$.result_redacted', json('true')) "
            "WHERE owner_id = ? AND command_id = ?",
            (owner, command_id),
        )
    return len(due)


def _drop_expired_objects(conn: Connection, owner: str, now: datetime) -> int:
    """Pages of expired snapshots/transfers go at once; metadata ages out later."""
    dropped = 0
    for table, pages, key in (
        ("sync_transfers", "sync_transfer_pages", "transfer_id"),
        ("sync_snapshots", "sync_snapshot_pages", "snapshot_id"),
    ):
        dropped += conn.execute(
            f"DELETE FROM {pages} WHERE owner_id = ? AND {key} IN "  # noqa: S608 -- fixed names
            f"(SELECT {key} FROM {table} WHERE owner_id = ? AND expires_at <= ?)",
            (owner, owner, instant(now)),
        ).rowcount
        conn.execute(
            f"DELETE FROM {table} WHERE owner_id = ? AND expires_at <= ?",  # noqa: S608
            (owner, instant(now - _FEED_RETENTION)),
        )
    return dropped


def _invalidate_copies(conn: Connection, owner: str, sequences: set[int]) -> int:
    """Remove materialized copies of redacted feed rows: transfers of those
    commits and every snapshot whose watermark includes the earliest of them."""
    dropped = 0
    for row in conn.execute(
        "SELECT transfer_id, commit_seq FROM sync_transfers WHERE owner_id = ?",
        (owner,),
    ).fetchall():
        if int(row["commit_seq"]) in sequences:
            dropped += conn.execute(
                "DELETE FROM sync_transfer_pages WHERE owner_id = ? AND transfer_id = ?",
                (owner, row["transfer_id"]),
            ).rowcount
    for row in conn.execute(
        "SELECT snapshot_id, watermark FROM sync_snapshots WHERE owner_id = ?",
        (owner,),
    ).fetchall():
        if int(row["watermark"]) >= min(sequences):
            dropped += conn.execute(
                "DELETE FROM sync_snapshot_pages WHERE owner_id = ? AND snapshot_id = ?",
                (owner, row["snapshot_id"]),
            ).rowcount
    return dropped


def sync_owner_ids(db_path: Path) -> list[str]:
    """Every owner holding sync state, whether or not it is still active."""
    conn = connect(db_path)
    try:
        return [row[0] for row in conn.execute("SELECT owner_id FROM sync_scopes")]
    except OperationalError:  # no sync table yet: nothing to sweep
        return []
    finally:
        conn.close()


class SyncRetention:
    """The scheduled cleanup port the durable privacy job calls (``int`` copies)."""

    def __init__(
        self,
        units: CommandUnits[Connection],
        change_log: ChangeLog,
        owners: Callable[[], Iterable[str]],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._units = units
        self._change_log = change_log
        self._owners = owners
        self._clock = clock

    def run_retention_sweep(self) -> int:
        """Sweep every owner; one failing owner never starves the rest."""
        now = self._clock().astimezone(UTC)
        total, failed = 0, 0
        for owner in sorted(set(self._owners())):
            try:
                with self._units.begin(owner, cleanup=True) as unit:
                    total += self.sweep(unit, now=now)
            except StaleExecutorError:
                raise
            except Exception as error:  # noqa: BLE001 - one owner must not end the job
                failed += 1
                logger.error(
                    "sync_retention_owner_failed error=%s", type(error).__name__
                )
        if failed:
            raise RuntimeError("sync retention incomplete")
        return total

    def sweep(self, unit: OwnerUnitOfWork[Connection], *, now: datetime) -> int:
        """One owner, inside the caller's unit. Needs no authority or flag."""
        conn, owner = unit.connection, unit.owner_id
        count = redact_expired_receipts(conn, owner, now)
        count += self._redact_feed(unit, now)
        count += _drop_expired_objects(conn, owner, now)
        self._change_log.prune(unit, now=now)
        return count

    def _redact_feed(self, unit: OwnerUnitOfWork[Connection], now: datetime) -> int:
        """Redact expired fields from retained after-images and publish them."""
        conn, owner = unit.connection, unit.owner_id
        due = [
            row
            for row in conn.execute(
                "SELECT commit_seq, entity_type, record_key, value, source_expires_at "
                "FROM sync_change_records WHERE owner_id = ? "
                "AND source_expires_at IS NOT NULL",
                (owner,),
            ).fetchall()
            if datetime.fromisoformat(row["source_expires_at"]) <= now
        ]
        if not due:
            return 0
        published: dict[tuple[str, str], tuple[int, Json]] = {}
        for row in due:
            key = (row["entity_type"], row["record_key"])
            redacted: Json | None = None
            if row["value"] is not None:
                redacted = expire_value(
                    row["entity_type"], json.loads(row["value"]), now
                )
            stored = row["value"] if redacted is None else _encode(redacted)
            conn.execute(
                "UPDATE sync_change_records SET value = ?, source_expires_at = NULL "
                "WHERE owner_id = ? AND commit_seq = ? AND entity_type = ? "
                "AND record_key = ?",
                (stored, owner, row["commit_seq"], *key),
            )
            if redacted is not None:
                seq = int(row["commit_seq"])
                if key not in published or published[key][0] < seq:
                    published[key] = (seq, redacted)
        dropped = _invalidate_copies(conn, owner, {int(r["commit_seq"]) for r in due})
        return len(due) + dropped + self._publish(unit, published, now)

    def _publish(
        self,
        unit: OwnerUnitOfWork[Connection],
        redacted: Mapping[tuple[str, str], tuple[int, Json]],
        now: datetime,
    ) -> int:
        """Emit the canonical retention change for each record's latest version."""
        conn, owner = unit.connection, unit.owner_id
        changes: list[Json] = []
        for (entity_type, key), (seq, value) in sorted(redacted.items()):
            newest = conn.execute(
                "SELECT max(CAST(commit_seq AS INTEGER)) AS newest "
                "FROM sync_change_records WHERE owner_id = ? "
                "AND entity_type = ? AND record_key = ?",
                (owner, entity_type, key),
            ).fetchone()["newest"]
            if int(newest) == seq:  # a later change already supersedes this one
                changes.append(
                    {"operation": "upsert", "entity_type": entity_type, "value": value}
                )
        if not changes:
            return 0
        identity = uuid5(
            _NAMESPACE,
            _encode([owner, [[s, k] for k, (s, _) in sorted(redacted.items())]]),
        )
        self._change_log.append(unit, str(identity), changes, now=now)
        return len(changes)


def _encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


__all__ = [
    "FIELD_EXPIRY_ENTITIES",
    "UNDO_FIELD",
    "SyncRetention",
    "expire_value",
    "instant",
    "redact_expired_receipts",
    "source_expiry",
    "sync_owner_ids",
]
