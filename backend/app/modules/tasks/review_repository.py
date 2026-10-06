"""SQL for the weekly-review tables, composed into ``TaskRepository``.

Spec 020 (data-model E2 – E9, research R1): the review records live in the
Tasks module's ``tasks.sqlite3`` so a decision and its task change commit in
one transaction under one owner lock. This mixin shares ``TaskRepository``'s
connection, command lock and ``migration_ledger``; it writes no JSON mirror.
Every table is keyed by ``owner_id`` first and every read filters by owner, so
another owner's record reads as absent.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from pydantic import BaseModel

from app.repositories.sqlite import SQLiteRepositorySupport

from .domain import TaskDocument
from .review_domain import (
    REVIEW_TABLES,
    NavigatorConsentDocument,
    NavigatorUsageDocument,
    ReviewBulkReleaseDocument,
    ReviewDecisionDocument,
    ReviewParkAckDocument,
    ReviewReceiptDocument,
    ReviewSessionDocument,
    ReviewSettingsDocument,
)

_Model = TypeVar("_Model", bound=BaseModel)

REVIEW_LEDGER_ID = "review-v1"

_REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_settings (
    owner_id TEXT NOT NULL PRIMARY KEY,
    revision INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_sessions (
    owner_id TEXT NOT NULL,
    id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (owner_id, id)
);
CREATE INDEX IF NOT EXISTS idx_review_sessions_owner_status
    ON review_sessions(owner_id, status, started_at);
CREATE TABLE IF NOT EXISTS review_decisions (
    owner_id TEXT NOT NULL,
    id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    session_id TEXT,
    decided_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (owner_id, id)
);
CREATE INDEX IF NOT EXISTS idx_review_decisions_owner_task
    ON review_decisions(owner_id, task_id);
CREATE INDEX IF NOT EXISTS idx_review_decisions_owner_session
    ON review_decisions(owner_id, session_id);
CREATE TABLE IF NOT EXISTS review_receipts (
    owner_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (owner_id, task_id, kind)
);
CREATE TABLE IF NOT EXISTS review_park_acks (
    owner_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    formulation_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (owner_id, task_id, formulation_id)
);
CREATE TABLE IF NOT EXISTS review_bulk_releases (
    owner_id TEXT NOT NULL,
    id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (owner_id, id)
);
CREATE TABLE IF NOT EXISTS navigator_consents (
    owner_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (owner_id, provider)
);
CREATE TABLE IF NOT EXISTS navigator_usage (
    owner_id TEXT NOT NULL,
    day TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (owner_id, day)
);
"""


def _dump(model: BaseModel) -> str:
    return json.dumps(
        model.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )


class ReviewRepositoryMixin(SQLiteRepositorySupport):
    """Review-table persistence for ``TaskRepository`` (single SQLite file)."""

    if TYPE_CHECKING:  # pragma: no cover - provided by TaskRepository
        _thread_state: ClassVar[threading.local]

        def _sqlite_guard(
            self, resource: str, identifier: str
        ) -> AbstractContextManager[None]: ...

        def task_path(self, owner_id: str, task_id: str) -> Path: ...

    # ------------------------------------------------------------ schema
    @staticmethod
    def _initialize_review_tables(conn: sqlite3.Connection, now: datetime) -> None:
        conn.executescript(_REVIEW_SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO migration_ledger (id, migrated_at, payload) "
            "VALUES (?, ?, ?)",
            (
                REVIEW_LEDGER_ID,
                now.isoformat(),
                json.dumps({"tables": list(REVIEW_TABLES)}, sort_keys=True),
            ),
        )

    @staticmethod
    def _delete_review_rows(conn: sqlite3.Connection, owner_id: str) -> None:
        for table in REVIEW_TABLES:
            # `table` comes from the literal REVIEW_TABLES tuple, never from
            # caller input; the owner filter is bound.
            conn.execute(
                f"DELETE FROM {table} WHERE owner_id = ?",  # noqa: S608
                (owner_id,),
            )

    # ------------------------------------------------------------ helpers
    def _review_execute(self, resource: str, sql: str, params: tuple[Any, ...]) -> None:
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard(resource, str(params[0])),
        ):
            conn.execute(sql, params)

    def _review_rows(
        self, resource: str, sql: str, params: tuple[Any, ...]
    ) -> list[sqlite3.Row]:
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard(resource, str(params[0]) if params else "*"),
        ):
            return list(conn.execute(sql, params).fetchall())

    def _review_one(
        self, model: type[_Model], resource: str, sql: str, params: tuple[Any, ...]
    ) -> _Model | None:
        rows = self._review_rows(resource, sql, params)
        if not rows:
            return None
        return model.model_validate(json.loads(rows[0]["payload"]))

    def _review_all(
        self, model: type[_Model], resource: str, sql: str, params: tuple[Any, ...]
    ) -> list[_Model]:
        return [
            model.model_validate(json.loads(row["payload"]))
            for row in self._review_rows(resource, sql, params)
        ]

    # ------------------------------------------------------------ E2
    def get_review_settings(self, owner_id: str) -> ReviewSettingsDocument | None:
        return self._review_one(
            ReviewSettingsDocument,
            "Review settings",
            "SELECT payload FROM review_settings WHERE owner_id = ?",
            (owner_id,),
        )

    def save_review_settings(self, settings: ReviewSettingsDocument) -> None:
        self._review_execute(
            "Review settings",
            """
            INSERT INTO review_settings (owner_id, revision, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(owner_id) DO UPDATE SET
                revision = excluded.revision, payload = excluded.payload
            """,
            (settings.owner_id, settings.revision, _dump(settings)),
        )

    def list_review_settings(self) -> list[ReviewSettingsDocument]:
        """Every owner's settings row (the sweep selects activated owners)."""

        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Review settings", "*"),
        ):
            rows = conn.execute(
                "SELECT payload FROM review_settings ORDER BY owner_id"
            ).fetchall()
        return [
            ReviewSettingsDocument.model_validate(json.loads(row["payload"]))
            for row in rows
        ]

    # ------------------------------------------------------------ E3
    def get_review_session(
        self, owner_id: str, session_id: str
    ) -> ReviewSessionDocument | None:
        return self._review_one(
            ReviewSessionDocument,
            "Review session",
            "SELECT payload FROM review_sessions WHERE owner_id = ? AND id = ?",
            (owner_id, session_id),
        )

    def save_review_session(self, session: ReviewSessionDocument) -> None:
        self._review_execute(
            "Review session",
            """
            INSERT INTO review_sessions (owner_id, id, status, started_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET
                status = excluded.status, payload = excluded.payload
            """,
            (
                session.owner_id,
                session.id,
                session.status,
                session.started_at.isoformat(),
                _dump(session),
            ),
        )

    def list_review_sessions(self, owner_id: str) -> list[ReviewSessionDocument]:
        return self._review_all(
            ReviewSessionDocument,
            "Review session",
            "SELECT payload FROM review_sessions WHERE owner_id = ? "
            "ORDER BY started_at, id",
            (owner_id,),
        )

    # ------------------------------------------------------------ E4
    def get_review_decision(
        self, owner_id: str, decision_id: str
    ) -> ReviewDecisionDocument | None:
        return self._review_one(
            ReviewDecisionDocument,
            "Review decision",
            "SELECT payload FROM review_decisions WHERE owner_id = ? AND id = ?",
            (owner_id, decision_id),
        )

    def save_review_decision(self, decision: ReviewDecisionDocument) -> None:
        self._review_execute(
            "Review decision",
            """
            INSERT INTO review_decisions
                (owner_id, id, task_id, session_id, decided_at, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET
                session_id = excluded.session_id, payload = excluded.payload
            """,
            (
                decision.owner_id,
                decision.id,
                decision.task_id,
                decision.session_id,
                decision.decided_at.isoformat(),
                _dump(decision),
            ),
        )

    def delete_review_decision(self, owner_id: str, decision_id: str) -> None:
        self._review_execute(
            "Review decision",
            "DELETE FROM review_decisions WHERE owner_id = ? AND id = ?",
            (owner_id, decision_id),
        )

    def list_review_decisions(
        self, owner_id: str, *, decided_before: datetime | None = None
    ) -> list[ReviewDecisionDocument]:
        if decided_before is None:
            return self._review_all(
                ReviewDecisionDocument,
                "Review decision",
                "SELECT payload FROM review_decisions WHERE owner_id = ? "
                "ORDER BY decided_at, id",
                (owner_id,),
            )
        return self._review_all(
            ReviewDecisionDocument,
            "Review decision",
            "SELECT payload FROM review_decisions WHERE owner_id = ? "
            "AND decided_at < ? ORDER BY decided_at, id",
            (owner_id, decided_before.isoformat()),
        )

    # ------------------------------------------------------------ E5
    def get_review_receipt(
        self, owner_id: str, task_id: str, kind: str
    ) -> ReviewReceiptDocument | None:
        return self._review_one(
            ReviewReceiptDocument,
            "Review receipt",
            "SELECT payload FROM review_receipts "
            "WHERE owner_id = ? AND task_id = ? AND kind = ?",
            (owner_id, task_id, kind),
        )

    def save_review_receipt(self, receipt: ReviewReceiptDocument) -> None:
        self._review_execute(
            "Review receipt",
            """
            INSERT INTO review_receipts (owner_id, task_id, kind, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(owner_id, task_id, kind) DO UPDATE SET
                payload = excluded.payload
            """,
            (receipt.owner_id, receipt.task_id, receipt.kind, _dump(receipt)),
        )

    def delete_review_receipt(self, owner_id: str, task_id: str, kind: str) -> None:
        self._review_execute(
            "Review receipt",
            "DELETE FROM review_receipts "
            "WHERE owner_id = ? AND task_id = ? AND kind = ?",
            (owner_id, task_id, kind),
        )

    def list_review_receipts(self, owner_id: str) -> list[ReviewReceiptDocument]:
        return self._review_all(
            ReviewReceiptDocument,
            "Review receipt",
            "SELECT payload FROM review_receipts WHERE owner_id = ? "
            "ORDER BY task_id, kind",
            (owner_id,),
        )

    # ------------------------------------------------------------ E6
    def get_park_ack(
        self, owner_id: str, task_id: str, formulation_id: str
    ) -> ReviewParkAckDocument | None:
        return self._review_one(
            ReviewParkAckDocument,
            "Park acknowledgement",
            "SELECT payload FROM review_park_acks "
            "WHERE owner_id = ? AND task_id = ? AND formulation_id = ?",
            (owner_id, task_id, formulation_id),
        )

    def save_park_ack(self, ack: ReviewParkAckDocument) -> None:
        self._review_execute(
            "Park acknowledgement",
            """
            INSERT INTO review_park_acks (owner_id, task_id, formulation_id, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(owner_id, task_id, formulation_id) DO UPDATE SET
                payload = excluded.payload
            """,
            (ack.owner_id, ack.task_id, ack.formulation_id, _dump(ack)),
        )

    def list_park_acks(self, owner_id: str) -> list[ReviewParkAckDocument]:
        return self._review_all(
            ReviewParkAckDocument,
            "Park acknowledgement",
            "SELECT payload FROM review_park_acks WHERE owner_id = ? "
            "ORDER BY task_id, formulation_id",
            (owner_id,),
        )

    # ------------------------------------------------------------ E7
    def get_bulk_release(
        self, owner_id: str, bulk_id: str
    ) -> ReviewBulkReleaseDocument | None:
        return self._review_one(
            ReviewBulkReleaseDocument,
            "Bulk release",
            "SELECT payload FROM review_bulk_releases WHERE owner_id = ? AND id = ?",
            (owner_id, bulk_id),
        )

    def save_bulk_release(self, release: ReviewBulkReleaseDocument) -> None:
        self._review_execute(
            "Bulk release",
            """
            INSERT INTO review_bulk_releases (owner_id, id, created_at, payload)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET payload = excluded.payload
            """,
            (
                release.owner_id,
                release.id,
                release.created_at.isoformat(),
                _dump(release),
            ),
        )

    def list_bulk_releases(
        self, owner_id: str, *, created_before: datetime | None = None
    ) -> list[ReviewBulkReleaseDocument]:
        if created_before is None:
            return self._review_all(
                ReviewBulkReleaseDocument,
                "Bulk release",
                "SELECT payload FROM review_bulk_releases WHERE owner_id = ? "
                "ORDER BY created_at, id",
                (owner_id,),
            )
        return self._review_all(
            ReviewBulkReleaseDocument,
            "Bulk release",
            "SELECT payload FROM review_bulk_releases WHERE owner_id = ? "
            "AND created_at < ? ORDER BY created_at, id",
            (owner_id, created_before.isoformat()),
        )

    # ------------------------------------------------------------ E8, E9
    def save_navigator_consent(self, consent: NavigatorConsentDocument) -> None:
        self._review_execute(
            "Navigator consent",
            """
            INSERT INTO navigator_consents (owner_id, provider, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(owner_id, provider) DO UPDATE SET payload = excluded.payload
            """,
            (consent.owner_id, consent.provider, _dump(consent)),
        )

    def list_navigator_consents(self, owner_id: str) -> list[NavigatorConsentDocument]:
        return self._review_all(
            NavigatorConsentDocument,
            "Navigator consent",
            "SELECT payload FROM navigator_consents WHERE owner_id = ? "
            "ORDER BY provider",
            (owner_id,),
        )

    def save_navigator_usage(self, usage: NavigatorUsageDocument) -> None:
        self._review_execute(
            "Navigator usage",
            """
            INSERT INTO navigator_usage (owner_id, day, payload) VALUES (?, ?, ?)
            ON CONFLICT(owner_id, day) DO UPDATE SET payload = excluded.payload
            """,
            (usage.owner_id, usage.day.isoformat(), _dump(usage)),
        )

    def list_navigator_usage(self, owner_id: str) -> list[NavigatorUsageDocument]:
        return self._review_all(
            NavigatorUsageDocument,
            "Navigator usage",
            "SELECT payload FROM navigator_usage WHERE owner_id = ? ORDER BY day",
            (owner_id,),
        )

    def delete_navigator_usage_before(self, owner_id: str, day: date) -> int:
        """Delete the owner's usage rows of days before ``day``; returns how many."""

        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Navigator usage", owner_id),
        ):
            cursor = conn.execute(
                "DELETE FROM navigator_usage WHERE owner_id = ? AND day < ?",
                (owner_id, day.isoformat()),
            )
            return int(cursor.rowcount)

    # ------------------------------------------------------------ sweep reads
    def review_owner_ids(self) -> set[str]:
        """Owners holding any review row (the retention part of the sweep)."""

        owners: set[str] = set()
        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Review owners", "*"),
        ):
            for table in REVIEW_TABLES:
                rows = conn.execute(
                    f"SELECT DISTINCT owner_id FROM {table}"  # noqa: S608
                ).fetchall()
                owners.update(row["owner_id"] for row in rows)
        return owners

    def list_next_tasks(self, owner_id: str) -> list[TaskDocument]:
        """The owner's Next tasks: the sweep's candidate query (http §9)."""

        with (
            self._connection(self._thread_state) as conn,
            self._sqlite_guard("Task", owner_id),
        ):
            rows = conn.execute(
                "SELECT payload FROM tasks WHERE owner_id = ? AND state = 'next' "
                "ORDER BY order_key, id",
                (owner_id,),
            ).fetchall()
        return [TaskDocument.model_validate(json.loads(row["payload"])) for row in rows]

    def delete_task_record(self, owner_id: str, task_id: str) -> None:
        """Remove a task created by a decision that is being undone (FR-048).

        Its tag links, subtasks and comments go with it (``ON DELETE CASCADE``),
        and so does its JSON mirror.
        """

        self._review_execute(
            "Task",
            "DELETE FROM tasks WHERE owner_id = ? AND id = ?",
            (owner_id, task_id),
        )
        self.task_path(owner_id, task_id).unlink(missing_ok=True)

    def iter_review_export(self, owner_id: str) -> Iterator[tuple[str, list[Any]]]:
        """``(file name, records)`` for every exported review table (FR-043)."""

        def dumped(models: list[_Model]) -> list[Any]:
            return [model.model_dump(mode="json") for model in models]

        settings = self.get_review_settings(owner_id)
        yield "settings.json", [] if settings is None else dumped([settings])
        yield "sessions.json", dumped(self.list_review_sessions(owner_id))
        yield "decisions.json", dumped(self.list_review_decisions(owner_id))
        yield "receipts.json", dumped(self.list_review_receipts(owner_id))
        yield "park_acknowledgements.json", dumped(self.list_park_acks(owner_id))
        yield "bulk_releases.json", dumped(self.list_bulk_releases(owner_id))
        yield "navigator_consents.json", dumped(self.list_navigator_consents(owner_id))


__all__ = ["REVIEW_LEDGER_ID", "ReviewRepositoryMixin"]
