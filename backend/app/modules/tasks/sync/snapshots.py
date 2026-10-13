"""Stable owner-scoped snapshots at one watermark (spec 026 PR-33).

sync-v1 sections 6 and 11. A snapshot is the complete public state of the
Tasks and native Review aggregate -- tasks, projects, tags, subtasks, comments
and every public Review projection -- plus the final version of each deleted
record, materialized once at the scope's committed ``commit_seq`` (the
watermark) and served as the same immutable RFC 8785 canonical byte chunks and
digests as an oversized transaction transfer (:mod:`.transfers`).

One watermark, no partial base: materialization runs inside the owner's unit of
work, which holds the owner's writer lock, so a writer commits wholly before it
(and is in the base) or wholly after it (and is the first delta past the
watermark). The scope counter is re-read at the end as a fence. After that the
object is immutable; anything that could make it incomplete or stale -- expiry
(the contract TTL, never beyond the earliest source content expiry), a feed or
access generation change, deletion redaction dropping its pages, a corrupt page
-- is ``RESET_REQUIRED``, never a shorter answer. A token never authorizes: the
caller re-admits the owner for every page.

Framework-free; SQLite storage like :class:`~.transfers.TransferStore`. It never
opens a connection or commits: the caller's owner unit does.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta
from sqlite3 import Connection
from typing import Any
from uuid import uuid4

from app.modules.tasks.domain import TaskCommentDocument, TaskSubtaskDocument
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.rust_adapter import RustCore
from app.modules.tasks.rust_task_facade import (
    encode_project,
    encode_tag,
    encode_task,
)

from .authority import resource_not_found
from .change_log import encode
from .delta import encode_cursor
from .receipts import ScopeAuthority
from .review_projection import ReviewProjection
from .transfers import (
    TRANSFER_PAGE_BYTES,
    change_stream,
    chunks,
    page_token,
    parse_page_token,
)
from .unit_of_work import OwnerUnitOfWork
from .wire import LIMITS, ProtocolFailure, common

Json = dict[str, Any]

SNAPSHOT_TTL = timedelta(seconds=LIMITS["snapshot_ttl_seconds"])
# Expired metadata stays (a late page request reads RESET_REQUIRED, not 404) for
# as long as the feed itself can be replayed.
_METADATA_RETENTION = timedelta(days=LIMITS["feed_retention_days"])
# Live snapshots one owner may hold; the oldest lose their pages first.
MAX_LIVE_SNAPSHOTS = 4


def _instant(value: datetime) -> str:
    # Fixed width so stored instants also order correctly as text.
    return value.isoformat(timespec="microseconds")


def _reset(reason: str) -> ProtocolFailure:
    return ProtocolFailure("RESET_REQUIRED", details={"reset_reason": reason})


def encode_subtask(subtask: TaskSubtaskDocument) -> Json:
    """A stored subtask as its public row (the same shape the feed publishes)."""
    return {
        "id": subtask.id,
        "task_id": subtask.task_id,
        "title": subtask.title,
        "state": subtask.state,
        "order_key": str(subtask.order_key),
        "revision": str(subtask.revision),
    }


def encode_comment(comment: TaskCommentDocument) -> Json:
    """A stored comment as its public row (the same shape the feed publishes)."""
    return {
        "id": comment.id,
        "task_id": comment.task_id,
        "body": comment.body,
        "actor_id": comment.actor_id,
        "created_at": comment.created_at.isoformat().replace("+00:00", "Z"),
        "edited_at": (
            comment.edited_at.isoformat().replace("+00:00", "Z")
            if comment.edited_at is not None
            else None
        ),
        "revision": str(comment.revision),
    }


def _upsert(entity_type: str, value: Json) -> Json:
    return {"operation": "upsert", "entity_type": entity_type, "value": value}


class SnapshotStore:
    """Owner-scoped snapshot rows (``sync_snapshots``/``sync_snapshot_pages``)."""

    def __init__(self, repo: TaskRepository, core: RustCore) -> None:
        self._repo = repo
        self._core = core

    # ------------------------------------------------------------- creation
    def create(
        self,
        unit: OwnerUnitOfWork[Connection],
        current: ScopeAuthority,
        *,
        now: datetime,
    ) -> Json:
        """Materialize the owner's base at the committed watermark."""
        conn, owner = unit.connection, unit.owner_id
        self._expire(conn, owner, now)
        watermark = self._watermark(conn, owner)
        changes = self._changes(unit)
        if self._watermark(conn, owner) != watermark:
            # Unreachable under the owner lock; never serve a base we cannot prove.
            raise ProtocolFailure("TEMPORARILY_UNAVAILABLE")
        stream = change_stream(changes)
        pages = chunks(stream, TRANSFER_PAGE_BYTES)
        snapshot_id = str(uuid4())
        expires = min(
            [now + SNAPSHOT_TTL, *self._source_expiries(changes, now)],
        )
        row = {
            "owner_id": owner,
            "snapshot_id": snapshot_id,
            "watermark": watermark,
            "feed_generation": current.feed_generation,
            "access_generation": current.access_generation,
            "page_count": len(pages),
            "record_count": len(changes),
            "total_bytes": len(stream),
            "sha256": hashlib.sha256(stream).hexdigest(),
            "created_at": _instant(now),
            "expires_at": _instant(expires),
        }
        conn.execute(
            f"INSERT INTO sync_snapshots ({','.join(row)}) "  # noqa: S608 -- fixed keys
            f"VALUES ({','.join('?' * len(row))})",
            tuple(row.values()),
        )
        conn.executemany(
            "INSERT INTO sync_snapshot_pages VALUES (?,?,?,?,?)",
            [
                (owner, snapshot_id, index, page, hashlib.sha256(page).hexdigest())
                for index, page in enumerate(pages)
            ],
        )
        self._evict_surplus(conn, owner, now)
        return {
            "snapshot_id": snapshot_id,
            "watermark": watermark,
            "cursor": encode_cursor(current, watermark),
            "page_count": row["page_count"],
            "record_count": row["record_count"],
            "total_bytes": row["total_bytes"],
            "sha256": row["sha256"],
            "expires_at": row["expires_at"],
            "first_page_token": page_token(snapshot_id, 0),
            **common(current, now),
        }

    @staticmethod
    def _watermark(conn: Connection, owner: str) -> str:
        row = conn.execute(
            "SELECT commit_seq FROM sync_scopes WHERE owner_id = ?", (owner,)
        ).fetchone()
        return str(row["commit_seq"]) if row else "0"

    def _changes(self, unit: OwnerUnitOfWork[Connection]) -> list[Json]:
        """Current public upserts and final deletion versions, deterministically."""
        conn, owner = unit.connection, unit.owner_id
        versions = {
            (row["entity_type"], row["record_key"]): row
            for row in conn.execute(
                "SELECT entity_type, record_key, record_version, deleted "
                "FROM sync_record_versions WHERE owner_id = ?",
                (owner,),
            ).fetchall()
        }
        changes: dict[tuple[str, str], Json] = {}
        for row in self._public_records(owner):
            key = (row["entity_type"], encode(row["record_key"]))
            version = versions.get(key)
            if version is None:
                # Written before sync recorded versions: start its history here
                # so the next change continues from this version.
                conn.execute(
                    "INSERT INTO sync_record_versions VALUES (?,?,?,?,?)",
                    (owner, key[0], key[1], "1", 0),
                )
            change = {
                **row,
                "record_version": "1" if version is None else version["record_version"],
            }
            value = row["value"]
            if "revision" in value:
                change["edit_revision"] = value["revision"]
            changes[key] = change
        for key, version in versions.items():
            if version["deleted"] and key not in changes:
                changes[key] = {
                    "entity_type": key[0],
                    "record_key": json.loads(key[1]),
                    "record_version": version["record_version"],
                    "operation": "tombstone",
                    "value": None,
                }
        return [changes[key] for key in sorted(changes)]

    def _public_records(self, owner: str) -> list[Json]:
        repo = self._repo
        records: list[Json] = []
        for task in repo.list_for_owner(owner_id=owner):
            records.append(_upsert("task", encode_task(task)))
            records.extend(
                _upsert("subtask", encode_subtask(child))
                for child in repo.list_subtasks(owner_id=owner, task_id=task.id)
            )
            records.extend(
                _upsert("comment", encode_comment(child))
                for child in repo.list_comments(owner_id=owner, task_id=task.id)
            )
        records.extend(
            _upsert("project", encode_project(project))
            for project in repo.list_projects_for_owner(owner_id=owner)
        )
        records.extend(
            _upsert("tag", encode_tag(tag))
            for tag in repo.list_tags_for_owner(owner_id=owner)
        )
        projection = ReviewProjection(repo, self._core)
        records.extend(projection.snapshot(owner))
        # The feed's own codec normalizes keys, counters and child projections.
        return projection.public(records)

    @staticmethod
    def _source_expiries(changes: list[Json], now: datetime) -> list[datetime]:
        """The next absolute deadline of any content a Review decision carries."""
        deadlines = []
        for change in changes:
            if change["entity_type"] != "review_decision" or change["value"] is None:
                continue
            until = change["value"].get("undo_available_until")
            if until is not None:
                deadline = datetime.fromisoformat(until)
                if deadline > now:
                    deadlines.append(deadline)
        return deadlines

    # --------------------------------------------------------------- paging
    def page(
        self,
        unit: OwnerUnitOfWork[Connection],
        current: ScopeAuthority,
        snapshot_id: str,
        token: str,
        *,
        now: datetime,
    ) -> Json:
        """One byte page; foreign and unknown IDs read the same."""
        conn, owner = unit.connection, unit.owner_id
        row = conn.execute(
            "SELECT * FROM sync_snapshots WHERE owner_id = ? AND snapshot_id = ?",
            (owner, snapshot_id),
        ).fetchone()
        if row is None:
            raise resource_not_found()
        index = parse_page_token(token, snapshot_id)
        if index >= row["page_count"]:
            raise ProtocolFailure("INVALID_REQUEST")
        if row["feed_generation"] != current.feed_generation:
            raise _reset("feed_changed")
        if self._content_expired(conn, owner, row, now):
            raise _reset("content_expired")
        stored = conn.execute(
            "SELECT payload, page_sha256 FROM sync_snapshot_pages "
            "WHERE owner_id = ? AND snapshot_id = ? AND page_index = ?",
            (owner, snapshot_id, index),
        ).fetchone()
        if (
            row["access_generation"] != current.access_generation
            or row["expires_at"] <= _instant(now)
            or stored is None
            or self._stored_pages(conn, owner, snapshot_id) != row["page_count"]
            or hashlib.sha256(stored["payload"]).hexdigest() != stored["page_sha256"]
        ):
            raise _reset("snapshot_expired")
        last = index + 1 == row["page_count"]
        return {
            "snapshot_id": snapshot_id,
            "watermark": row["watermark"],
            "page_index": index,
            "payload_base64": base64.b64encode(stored["payload"]).decode(),
            "page_sha256": stored["page_sha256"],
            "has_more": not last,
            "next_page_token": None if last else page_token(snapshot_id, index + 1),
            **common(current, now),
        }

    @staticmethod
    def _content_expired(
        conn: Connection, owner: str, snapshot: Any, now: datetime
    ) -> bool:
        """A record whose current feed copy is past its absolute retention voids it.

        Read from the feed on every fetch, not frozen at materialization, so a
        deadline assigned later also applies. A superseding change (for example
        the canonical retention change) clears the record again.
        """
        rows = conn.execute(
            "SELECT source_expires_at FROM sync_change_records r "
            "WHERE r.owner_id = ? AND r.operation = 'upsert' "
            "AND r.source_expires_at IS NOT NULL "
            "AND CAST(r.commit_seq AS INTEGER) <= CAST(? AS INTEGER) "
            "AND NOT EXISTS (SELECT 1 FROM sync_change_records n "
            "WHERE n.owner_id = r.owner_id AND n.entity_type = r.entity_type "
            "AND n.record_key = r.record_key "
            "AND CAST(n.commit_seq AS INTEGER) > CAST(r.commit_seq AS INTEGER) "
            "AND CAST(n.commit_seq AS INTEGER) <= CAST(? AS INTEGER))",
            (owner, snapshot["watermark"], snapshot["watermark"]),
        ).fetchall()
        return any(
            datetime.fromisoformat(row["source_expires_at"]) <= now for row in rows
        )

    @staticmethod
    def _stored_pages(conn: Connection, owner: str, snapshot_id: str) -> int:
        """Pages still held; a partly dropped object is never served."""
        found = conn.execute(
            "SELECT count(*) AS n FROM sync_snapshot_pages "
            "WHERE owner_id = ? AND snapshot_id = ?",
            (owner, snapshot_id),
        ).fetchone()
        return int(found["n"])

    # ------------------------------------------------------------ lifecycle
    @staticmethod
    def _expire(conn: Connection, owner: str, now: datetime) -> None:
        """Content of an expired snapshot is unavailable; metadata ages out."""
        conn.execute(
            "DELETE FROM sync_snapshot_pages WHERE owner_id = ? AND snapshot_id IN "
            "(SELECT snapshot_id FROM sync_snapshots WHERE owner_id = ? "
            "AND expires_at <= ?)",
            (owner, owner, _instant(now)),
        )
        conn.execute(
            "DELETE FROM sync_snapshots WHERE owner_id = ? AND expires_at <= ?",
            (owner, _instant(now - _METADATA_RETENTION)),
        )

    @staticmethod
    def _evict_surplus(conn: Connection, owner: str, now: datetime) -> None:
        """Bound stored copies: the oldest live snapshots lose their pages."""
        conn.execute(
            "DELETE FROM sync_snapshot_pages WHERE owner_id = ? AND snapshot_id IN "
            "(SELECT snapshot_id FROM sync_snapshots WHERE owner_id = ? "
            "AND expires_at > ? ORDER BY created_at DESC, rowid DESC "
            "LIMIT -1 OFFSET ?)",
            (owner, owner, _instant(now), MAX_LIVE_SNAPSHOTS),
        )
