"""Delta feed pages over whole commit-ordered transactions (spec 026 PR-32).

sync-v1 sections 6 and 11. A page holds only complete transactions: a logical
transaction is never split, reordered or partially exposed. Inline pages target
1 MiB and 100 transactions with a 4 MiB hard limit; a transaction beyond the
hard limit is announced by a transfer manifest instead (:mod:`.transfers`). There
is no changed-record ceiling: a 500-item bulk release or an archive that touches
thousands of tasks is one transaction however many records it carries.

The cursor is an opaque token bound to the owner, the access generation and the
feed generation. It carries no authority: every page re-admits the owner first.
Anything the feed can no longer prove -- another generation, a pruned
position, a cursor ahead of the scope (restore), redacted or expired content --
is ``RESET_REQUIRED``, never an empty or partial page.

Framework-free; the stored values are the already-public projections written by
the common transaction (:mod:`.change_log`).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection
from typing import Any

from .receipts import ScopeAuthority
from .transfers import TransferRef, TransferStore, canonical_json
from .unit_of_work import OwnerUnitOfWork
from .wire import LIMITS, ProtocolFailure, common

INLINE_TARGET_BYTES: int = LIMITS["inline_page_target_bytes"]
INLINE_HARD_BYTES: int = LIMITS["inline_page_hard_bytes"]
MAX_PAGE_TRANSACTIONS: int = LIMITS["inline_page_transactions"]
# The response envelope (cursors, common fields, brackets) shares the hard limit.
ENVELOPE_ALLOWANCE = 4096
_READ_BATCH = 8


def _reset(reason: str) -> ProtocolFailure:
    return ProtocolFailure("RESET_REQUIRED", details={"reset_reason": reason})


@dataclass(frozen=True, slots=True)
class Cursor:
    owner_id: str
    access_generation: str
    feed_generation: str
    commit_seq: str


def encode_cursor(current: ScopeAuthority, commit_seq: str) -> str:
    """The opaque cursor naming the position after ``commit_seq``."""
    body = {
        "v": 1,
        "o": current.owner_id,
        "a": current.access_generation,
        "f": current.feed_generation,
        "s": commit_seq,
    }
    raw = json.dumps(body, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def decode_cursor(token: str) -> Cursor:
    try:
        body = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        fields = (body["o"], body["a"], body["f"], body["s"])
        valid = (
            body["v"] == 1
            and all(isinstance(field, str) and field for field in fields)
            and (fields[3] == "0" or fields[3].isdecimal() and fields[3][0] != "0")
        )
    except ValueError, KeyError, TypeError:
        valid = False
    if not valid:
        raise ProtocolFailure("INVALID_REQUEST")
    return Cursor(*fields)


class Feed:
    """SQLite read port of the retained transaction log (``change_log`` tables)."""

    @staticmethod
    def high_watermark(unit: OwnerUnitOfWork[Connection]) -> str:
        row = unit.connection.execute(
            "SELECT commit_seq FROM sync_scopes WHERE owner_id = ?", (unit.owner_id,)
        ).fetchone()
        return str(row["commit_seq"]) if row else "0"

    @staticmethod
    def after(
        unit: OwnerUnitOfWork[Connection], seq: str, limit: int, *, now: datetime
    ) -> list[dict[str, Any]]:
        """Up to ``limit`` complete transactions after ``seq`` in commit order."""
        conn, owner = unit.connection, unit.owner_id
        headers = conn.execute(
            "SELECT * FROM sync_change_transactions WHERE owner_id = ? "
            "AND (length(commit_seq) > ? OR (length(commit_seq) = ? AND commit_seq > ?)) "
            "ORDER BY length(commit_seq),commit_seq LIMIT ?",
            (owner, len(seq), len(seq), seq, limit),
        ).fetchall()
        return [Feed._transaction(unit, header, now) for header in headers]

    @staticmethod
    def _transaction(
        unit: OwnerUnitOfWork[Connection], header: Any, now: datetime
    ) -> dict[str, Any]:
        rows = unit.connection.execute(
            "SELECT * FROM sync_change_records WHERE owner_id = ? AND commit_seq = ? "
            "ORDER BY entity_type, record_key",
            (unit.owner_id, header["commit_seq"]),
        ).fetchall()
        changes = []
        for row in rows:
            expired = (
                row["source_expires_at"] is not None
                and datetime.fromisoformat(row["source_expires_at"]) <= now
            )
            if row["operation"] == "upsert" and (row["value"] is None or expired):
                # Redacted or expired content: the transaction cannot be served.
                raise _reset("content_expired")
            changes.append(
                {
                    "entity_type": row["entity_type"],
                    "record_key": json.loads(row["record_key"]),
                    "record_version": row["record_version"],
                    **(
                        {"edit_revision": row["edit_revision"]}
                        if row["edit_revision"]
                        else {}
                    ),
                    "operation": row["operation"],
                    "value": json.loads(row["value"]) if row["value"] else None,
                }
            )
        return {
            "transaction_id": header["transaction_id"],
            "commit_seq": header["commit_seq"],
            "source_command_id": header["source_command_id"],
            "changes": changes,
        }


@dataclass(slots=True)
class _Page:
    transactions: list[dict[str, Any]]
    size: int = 0
    position: str = "0"
    manifest: dict[str, Any] | None = None


def read_changes(  # noqa: PLR0913 - the one feed read
    unit: OwnerUnitOfWork[Connection],
    current: ScopeAuthority,
    token: str,
    limit: int,
    *,
    now: datetime,
    feed: Feed,
    transfers: TransferStore,
) -> dict[str, Any]:
    """The ``ChangesPage`` after ``token``; ``current`` is freshly admitted."""
    cursor = decode_cursor(token)
    if (
        cursor.owner_id != current.owner_id
        or cursor.access_generation != current.access_generation
        or cursor.feed_generation != current.feed_generation
    ):
        raise _reset("feed_changed")
    high = feed.high_watermark(unit)
    if int(cursor.commit_seq) > int(high):
        raise _reset("restore")
    page = _Page([], position=cursor.commit_seq)
    limit = max(1, min(limit, MAX_PAGE_TRANSACTIONS))
    while _fill(unit, current, page, high, limit, now, feed, transfers):
        pass
    return {
        "from_cursor": token,
        "transactions": page.transactions,
        "has_more": page.manifest is not None or int(page.position) < int(high),
        "next_cursor": (
            token
            if page.position == cursor.commit_seq
            else encode_cursor(current, page.position)
        ),
        "high_watermark": high,
        **({"transaction_manifest": page.manifest} if page.manifest else {}),
        **common(current, now),
    }


def _fill(  # noqa: PLR0913 - one read step of read_changes
    unit: OwnerUnitOfWork[Connection],
    current: ScopeAuthority,
    page: _Page,
    high: str,
    limit: int,
    now: datetime,
    feed: Feed,
    transfers: TransferStore,
) -> bool:
    """Read one batch into ``page``; ``True`` while more may still fit."""
    if len(page.transactions) >= limit or int(page.position) >= int(high):
        return False
    batch = feed.after(unit, page.position, _READ_BATCH, now=now)
    if not batch:
        # The scope is ahead of what the feed retains: the position was pruned.
        raise _reset("cursor_expired")
    for transaction in batch:
        if int(transaction["commit_seq"]) != int(page.position) + 1:
            raise _reset("cursor_expired")
        size = len(canonical_json(transaction).encode())
        if size + ENVELOPE_ALLOWANCE > INLINE_HARD_BYTES:
            if not page.transactions:
                page.manifest = transfers.manifest(
                    unit,
                    current,
                    TransferRef(
                        transaction["transaction_id"],
                        transaction["commit_seq"],
                        transaction["source_command_id"],
                        encode_cursor(current, transaction["commit_seq"]),
                    ),
                    transaction["changes"],
                    now=now,
                )
            return False
        if page.transactions and page.size + size > INLINE_TARGET_BYTES:
            return False
        page.transactions.append(transaction)
        page.size += size
        page.position = transaction["commit_seq"]
        if len(page.transactions) >= limit:
            return False
    return True
