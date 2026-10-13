"""Immutable byte transfers of oversized feed transactions (spec 026 PR-32).

sync-v1 section 11: a transaction above the 4 MiB inline hard limit is
materialized once as the RFC 8785 canonical JSON ``Change`` array and served as
consecutive decoded-byte chunks of at most 1 MiB. A chunk may cross a record
boundary: it is staged bytes, never parsed or applied on its own, so a domain
commit is never split. A transfer is owner-, feed-generation- and
access-generation-bound; expiry, a generation change, or deletion redaction of
its content (``ChangeLog.redact_record`` drops the pages) make it
``RESET_REQUIRED``.

Framework-free; SQLite storage like :class:`~.change_log.ChangeLog`. It never
opens a connection or commits: the caller's owner unit does.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from sqlite3 import Connection
from typing import Any
from uuid import uuid4

from .authority import resource_not_found
from .receipts import ScopeAuthority
from .unit_of_work import OwnerUnitOfWork
from .wire import LIMITS, ProtocolFailure, common

TRANSFER_PAGE_BYTES: int = LIMITS["transfer_page_bytes"]
TRANSFER_TTL = timedelta(seconds=LIMITS["transfer_ttl_seconds"])
# Expired metadata stays (so a late page request reads RESET_REQUIRED, not 404)
# for as long as the feed itself can be replayed.
_METADATA_RETENTION = timedelta(days=LIMITS["feed_retention_days"])
_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n"}
_ESCAPES |= {"\r": "\\r", "\t": "\\t"}
_MAX_EXPONENT_DIGITS = 21


def _instant(value: datetime) -> str:
    # Fixed width so stored instants also order correctly as text.
    return value.isoformat(timespec="microseconds")


def _string(value: str) -> str:
    return (
        '"'
        + "".join(
            _ESCAPES.get(c) or (f"\\u{ord(c):04x}" if ord(c) < 0x20 else c)
            for c in value
        )
        + '"'
    )


def _number(value: float) -> str:
    """ECMAScript ``Number::toString``, as RFC 8785 section 3.2.2.3 requires."""
    if not math.isfinite(value):
        raise ValueError("a non-finite number has no canonical JSON form")
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    parts = Decimal(repr(abs(value))).normalize().as_tuple()
    digits = "".join(map(str, parts.digits))
    count, point = len(digits), len(digits) + int(parts.exponent)
    if count <= point <= _MAX_EXPONENT_DIGITS:
        body = digits + "0" * (point - count)
    elif 0 < point <= _MAX_EXPONENT_DIGITS:
        body = digits[:point] + "." + digits[point:]
    elif -6 < point <= 0:
        body = "0." + "0" * -point + digits
    else:
        exponent = point - 1
        mantissa = digits[0] + ("." + digits[1:] if count > 1 else "")
        body = f"{mantissa}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"
    return sign + body


def canonical_json(value: Any) -> str:
    """RFC 8785 JSON Canonicalization Scheme text of ``value``."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, Mapping):
        # Members sort by UTF-16 code units, not by code point.
        members = sorted(value.items(), key=lambda item: item[0].encode("utf-16-be"))
        return (
            "{"
            + ",".join(f"{_string(k)}:{canonical_json(v)}" for k, v in members)
            + "}"
        )
    if isinstance(value, Sequence):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    raise TypeError(f"{type(value).__name__} is not JSON")


def change_stream(changes: Sequence[Mapping[str, Any]]) -> bytes:
    """The canonical Change-array bytes a transfer serves."""
    return canonical_json(list(changes)).encode()


def chunks(stream: bytes, size: int = TRANSFER_PAGE_BYTES) -> list[bytes]:
    """Consecutive decoded-byte chunks; they may split inside any record."""
    return [stream[start : start + size] for start in range(0, len(stream), size)] or [
        b""
    ]


def _token(parts: Mapping[str, Any]) -> str:
    raw = json.dumps(parts, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def page_token(transfer_id: str, index: int) -> str:
    """Resume token bound to the immutable object and page index."""
    return _token({"v": 1, "t": transfer_id, "i": index})


def parse_page_token(token: str, transfer_id: str) -> int:
    """The page index of ``token``; a token of another transfer is malformed."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        body = json.loads(raw)
        index = body["i"]
        valid = (
            body["v"] == 1
            and body["t"] == transfer_id
            and type(index) is int
            and index >= 0
        )
    except ValueError, KeyError, TypeError:
        valid = False
    if not valid:
        raise ProtocolFailure("INVALID_REQUEST")
    return int(index)


@dataclass(frozen=True, slots=True)
class TransferRef:
    """What the transaction being materialized is, besides its changes."""

    transaction_id: str
    commit_seq: str
    source_command_id: str
    after_cursor: str


class TransferStore:
    """Owner-scoped transfer rows (``sync_transfers``/``sync_transfer_pages``)."""

    def manifest(
        self,
        unit: OwnerUnitOfWork[Connection],
        current: ScopeAuthority,
        ref: TransferRef,
        changes: Sequence[Mapping[str, Any]],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        """The manifest of ``ref``'s transfer; materialized once, reused after."""
        conn, owner = unit.connection, unit.owner_id
        self._expire(conn, owner, now)
        found = conn.execute(
            "SELECT * FROM sync_transfers WHERE owner_id = ? AND commit_seq = ? "
            "AND feed_generation = ? AND access_generation = ? AND expires_at > ? "
            "AND EXISTS (SELECT 1 FROM sync_transfer_pages p WHERE "
            "p.owner_id = sync_transfers.owner_id "
            "AND p.transfer_id = sync_transfers.transfer_id) "
            "ORDER BY expires_at DESC LIMIT 1",
            (
                owner,
                ref.commit_seq,
                current.feed_generation,
                current.access_generation,
                _instant(now),
            ),
        ).fetchone()
        if found is None:
            found = self._materialize(unit, current, ref, changes, now=now)
        return {
            "transfer_id": found["transfer_id"],
            "transaction_id": found["transaction_id"],
            "commit_seq": found["commit_seq"],
            "source_command_id": found["source_command_id"],
            "page_count": found["page_count"],
            "record_count": found["record_count"],
            "total_bytes": found["total_bytes"],
            "sha256": found["sha256"],
            "expires_at": found["expires_at"],
            "first_page_token": page_token(found["transfer_id"], 0),
            "after_cursor": ref.after_cursor,
        }

    def _materialize(
        self,
        unit: OwnerUnitOfWork[Connection],
        current: ScopeAuthority,
        ref: TransferRef,
        changes: Sequence[Mapping[str, Any]],
        *,
        now: datetime,
    ) -> Mapping[str, Any]:
        conn, owner = unit.connection, unit.owner_id
        stream = change_stream(changes)
        pages = chunks(stream)
        transfer_id = str(uuid4())
        row = {
            "owner_id": owner,
            "transfer_id": transfer_id,
            "commit_seq": ref.commit_seq,
            "transaction_id": ref.transaction_id,
            "source_command_id": ref.source_command_id,
            "feed_generation": current.feed_generation,
            "access_generation": current.access_generation,
            "page_count": len(pages),
            "record_count": len(changes),
            "total_bytes": len(stream),
            "sha256": hashlib.sha256(stream).hexdigest(),
            "created_at": _instant(now),
            "expires_at": _instant(now + TRANSFER_TTL),
        }
        conn.execute(
            f"INSERT INTO sync_transfers ({','.join(row)}) "  # noqa: S608 -- fixed keys
            f"VALUES ({','.join('?' * len(row))})",
            tuple(row.values()),
        )
        conn.executemany(
            "INSERT INTO sync_transfer_pages VALUES (?,?,?,?,?)",
            [
                (owner, transfer_id, index, page, hashlib.sha256(page).hexdigest())
                for index, page in enumerate(pages)
            ],
        )
        return row

    def page(
        self,
        unit: OwnerUnitOfWork[Connection],
        current: ScopeAuthority,
        transfer_id: str,
        token: str,
        *,
        now: datetime,
    ) -> dict[str, Any]:
        """One byte page; foreign and unknown IDs read the same."""
        conn, owner = unit.connection, unit.owner_id
        row = conn.execute(
            "SELECT * FROM sync_transfers WHERE owner_id = ? AND transfer_id = ?",
            (owner, transfer_id),
        ).fetchone()
        if row is None:
            raise resource_not_found()
        index = parse_page_token(token, transfer_id)
        if index >= row["page_count"]:
            raise ProtocolFailure("INVALID_REQUEST")
        if row["feed_generation"] != current.feed_generation:
            raise ProtocolFailure(
                "RESET_REQUIRED", details={"reset_reason": "feed_changed"}
            )
        if self._content_expired(conn, owner, row, now):
            raise ProtocolFailure(
                "RESET_REQUIRED", details={"reset_reason": "content_expired"}
            )
        stored = conn.execute(
            "SELECT payload, page_sha256 FROM sync_transfer_pages "
            "WHERE owner_id = ? AND transfer_id = ? AND page_index = ?",
            (owner, transfer_id, index),
        ).fetchone()
        if (
            row["access_generation"] != current.access_generation
            or row["expires_at"] <= _instant(now)
            or stored is None
        ):
            raise ProtocolFailure(
                "RESET_REQUIRED", details={"reset_reason": "transfer_expired"}
            )
        last = index + 1 == row["page_count"]
        return {
            "transfer_id": transfer_id,
            "page_index": index,
            "payload_base64": base64.b64encode(stored["payload"]).decode(),
            "page_sha256": stored["page_sha256"],
            "has_more": not last,
            "next_page_token": None if last else page_token(transfer_id, index + 1),
            **common(current, now),
        }

    @staticmethod
    def _expire(conn: Connection, owner: str, now: datetime) -> None:
        """Content of an expired transfer is unavailable; metadata ages out."""
        conn.execute(
            "DELETE FROM sync_transfer_pages WHERE owner_id = ? AND transfer_id IN "
            "(SELECT transfer_id FROM sync_transfers WHERE owner_id = ? "
            "AND expires_at <= ?)",
            (owner, owner, _instant(now)),
        )
        conn.execute(
            "DELETE FROM sync_transfers WHERE owner_id = ? AND expires_at <= ?",
            (owner, _instant(now - _METADATA_RETENTION)),
        )

    @staticmethod
    def _content_expired(
        conn: Connection, owner: str, transfer: Any, now: datetime
    ) -> bool:
        """Any record past its absolute retention, or gone, voids the copy.

        The deadline is read from the feed on every fetch, not frozen at
        materialization, so a later-assigned expiry also applies.
        """
        rows = conn.execute(
            "SELECT source_expires_at FROM sync_change_records "
            "WHERE owner_id = ? AND commit_seq = ?",
            (owner, transfer["commit_seq"]),
        ).fetchall()
        return len(rows) != transfer["record_count"] or any(
            row["source_expires_at"] is not None
            and datetime.fromisoformat(row["source_expires_at"]) <= now
            for row in rows
        )
