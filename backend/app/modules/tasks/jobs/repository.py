"""SQLite job ledger sharing the Tasks database (spec 026 PR-20).

Every mutation runs inside ``BEGIN IMMEDIATE`` on its own connection, so the
database write lock -- not a Python lock -- is what serializes claimers. That
makes the ledger safe across threads *and* processes: two workers can never both
hold the same job, and a result is accepted only under the fence issued by the
claim that produced it.

The ledger records and arbitrates; it runs no effect. Nothing in this module
knows about any particular maintenance responsibility.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from app.repositories.sqlite import SQLiteRepositorySupport

from .domain import (
    ACTIVE_STATUSES,
    BACKOFF_CAPS,
    LEASE,
    MAX_ATTEMPTS,
    SYSTEM_SCOPE,
    JobLease,
    JobRecord,
    JobStatus,
    safe_error_code,
)

_STORAGE_BUSY = "Job storage is temporarily unavailable; retry the request."

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    job_type TEXT NOT NULL,
    dedup_key TEXT NOT NULL,
    payload_ref TEXT,
    run_at INTEGER NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL,
    lease_owner TEXT,
    lease_until INTEGER,
    fence INTEGER NOT NULL DEFAULT 0,
    effect_id TEXT NOT NULL,
    last_error TEXT,
    correlation_id TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_active_dedup
    ON jobs(scope, dedup_key)
    WHERE status IN ('queued', 'leased', 'reconciliation_required');
CREATE INDEX IF NOT EXISTS idx_jobs_due ON jobs(status, run_at, id);
CREATE TABLE IF NOT EXISTS job_fence_counter (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO job_fence_counter (id, value) VALUES (1, 0);
"""

_COLUMNS = (
    "id, scope, job_type, dedup_key, payload_ref, run_at, status, attempts, "
    "max_attempts, lease_owner, lease_until, fence, effect_id, last_error, "
    "correlation_id, cancel_requested"
)

Decision = Literal["succeeded", "failed", "retry"]


def _full_jitter(cap: float) -> float:
    return secrets.SystemRandom().uniform(0.0, cap)


def _to_us(moment: datetime) -> int:
    if moment.tzinfo is None:
        raise ValueError("Job times must be timezone-aware.")
    delta = moment.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return delta // timedelta(microseconds=1)


def _from_us(value: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value)


class JobRepository(SQLiteRepositorySupport):
    """Durable, fenced job leases over the Tasks SQLite file."""

    def __init__(
        self,
        db_path: Path,
        *,
        jitter: Callable[[float], float] = _full_jitter,
    ) -> None:
        self.db_path = db_path
        self._jitter = jitter
        with self._owned_connection() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with (
            self._owned_connection() as conn,
            self.sqlite_guard("Job", "ledger", _STORAGE_BUSY, _STORAGE_BUSY),
        ):
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            conn.commit()

    # --- scheduling ----------------------------------------------------------

    def ensure_scheduled(
        self,
        *,
        job_type: str,
        dedup_key: str,
        run_at: datetime,
        scope: str = SYSTEM_SCOPE,
        payload_ref: str | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        correlation_id: str | None = None,
        pull_forward: bool = False,
    ) -> bool:
        """Create the job unless one is already active for ``(scope, dedup_key)``.

        Returns ``True`` only when a row was created. With ``pull_forward`` an
        existing *queued* job due later is moved earlier; a leased or
        reconciliation-pending job is never touched.
        """

        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        run_us = _to_us(run_at)
        now_us = _to_us(datetime.now(UTC))
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT id, status, run_at FROM jobs WHERE scope = ? "
                "AND dedup_key = ? AND status IN (?, ?, ?)",
                (scope, dedup_key, *(s.value for s in ACTIVE_STATUSES)),
            ).fetchone()
            if existing is not None:
                if (
                    pull_forward
                    and existing["status"] == JobStatus.QUEUED
                    and existing["run_at"] > run_us
                ):
                    conn.execute(
                        "UPDATE jobs SET run_at = ?, updated_at = ? WHERE id = ?",
                        (run_us, now_us, existing["id"]),
                    )
                return False
            conn.execute(
                "INSERT INTO jobs (id, scope, job_type, dedup_key, payload_ref, "
                "run_at, status, max_attempts, effect_id, correlation_id, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    uuid.uuid4().hex,
                    scope,
                    job_type,
                    dedup_key,
                    payload_ref,
                    run_us,
                    JobStatus.QUEUED.value,
                    max_attempts,
                    uuid.uuid4().hex,
                    correlation_id,
                    now_us,
                    now_us,
                ),
            )
        return True

    # --- leasing -------------------------------------------------------------

    def claim_due(
        self,
        *,
        owner: str,
        types: Sequence[str],
        now: datetime,
        lease_for: timedelta = LEASE,
    ) -> JobLease | None:
        """Atomically lease the oldest due job of ``types``, or return ``None``.

        A job whose lease expired is reclaimable, unless it already used its
        attempt budget: then it is closed as ``failed`` so a job that crashes its
        worker every time cannot loop forever.
        """

        if not types:
            return None
        now_us = _to_us(now)
        wanted = json.dumps(list(types))
        with self._transaction() as conn:
            self._close_expired(conn, wanted, now_us)
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM jobs "  # noqa: S608 - module constant only
                "WHERE job_type IN (SELECT value FROM json_each(?)) AND "
                "((status = 'queued' AND run_at <= ?) OR "
                "(status = 'leased' AND lease_until <= ?)) "
                "ORDER BY run_at, id LIMIT 1",
                (wanted, now_us, now_us),
            ).fetchone()
            if row is None:
                return None
            fence = conn.execute(
                "UPDATE job_fence_counter SET value = value + 1 "
                "WHERE id = 1 RETURNING value"
            ).fetchone()["value"]
            until_us = _to_us(now + lease_for)
            conn.execute(
                "UPDATE jobs SET status = 'leased', lease_owner = ?, "
                "lease_until = ?, fence = ?, attempts = attempts + 1, "
                "updated_at = ? WHERE id = ?",
                (owner, until_us, fence, now_us, row["id"]),
            )
            return JobLease(
                job_id=row["id"],
                job_type=row["job_type"],
                scope=row["scope"],
                dedup_key=row["dedup_key"],
                payload_ref=row["payload_ref"],
                owner=owner,
                fence=fence,
                lease_until=_from_us(until_us),
                attempt=row["attempts"] + 1,
                max_attempts=row["max_attempts"],
                effect_id=row["effect_id"],
            )

    @staticmethod
    def _close_expired(conn: sqlite3.Connection, wanted: str, now_us: int) -> None:
        """Close expired leases that must not be reclaimed (cancelled/exhausted)."""

        conn.execute(
            "UPDATE jobs SET status = 'cancelled', lease_owner = NULL, "
            "lease_until = NULL, last_error = 'cancelled', updated_at = ? "
            "WHERE status = 'leased' AND lease_until <= ? AND cancel_requested = 1 "
            "AND job_type IN (SELECT value FROM json_each(?))",
            (now_us, now_us, wanted),
        )
        conn.execute(
            "UPDATE jobs SET status = 'failed', lease_owner = NULL, "
            "lease_until = NULL, last_error = 'lease_expired', updated_at = ? "
            "WHERE status = 'leased' AND lease_until <= ? "
            "AND attempts >= max_attempts "
            "AND job_type IN (SELECT value FROM json_each(?))",
            (now_us, now_us, wanted),
        )

    def heartbeat(
        self, job_id: str, *, owner: str, fence: int, until: datetime
    ) -> bool:
        """Extend the lease of the current claim. ``False`` once it is lost."""

        with self._transaction() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET lease_until = MAX(lease_until, ?) "
                "WHERE id = ? AND status = 'leased' AND lease_owner = ? "
                "AND fence = ?",
                (_to_us(until), job_id, owner, fence),
            )
            return cursor.rowcount == 1

    # --- settling ------------------------------------------------------------

    def complete(self, job_id: str, *, fence: int) -> bool:
        """Accept a result only under the current fence.

        ``False`` means the result was refused: stale fence, or cancellation was
        requested while the job ran (the job is then closed as ``cancelled``).
        """

        with self._transaction() as conn:
            row = self._held(conn, job_id, fence)
            if row is None:
                return False
            if row["cancel_requested"]:
                self._settle(conn, job_id, JobStatus.CANCELLED, "cancelled")
                return False
            self._settle(conn, job_id, JobStatus.SUCCEEDED, None)
            return True

    def fail(
        self, job_id: str, *, fence: int, safe_error: str | None, now: datetime
    ) -> bool:
        """Record a failed attempt; ``True`` when the retry budget is exhausted.

        Under budget the job returns to ``queued`` after full-jitter backoff.
        A stale fence changes nothing and reports ``False``.
        """

        with self._transaction() as conn:
            row = self._held(conn, job_id, fence)
            if row is None:
                return False
            code = safe_error_code(safe_error) or "failed"
            if row["cancel_requested"]:
                self._settle(conn, job_id, JobStatus.CANCELLED, "cancelled")
                return False
            if row["attempts"] >= row["max_attempts"]:
                self._settle(conn, job_id, JobStatus.FAILED, code)
                return True
            caps = BACKOFF_CAPS
            cap = caps[min(row["attempts"], len(caps)) - 1]
            retry_at = now + timedelta(seconds=self._jitter(cap))
            conn.execute(
                "UPDATE jobs SET status = 'queued', run_at = ?, lease_owner = NULL, "
                "lease_until = NULL, last_error = ?, updated_at = ? WHERE id = ?",
                (_to_us(retry_at), code, _to_us(now), job_id),
            )
            return False

    def mark_uncertain(
        self, job_id: str, *, fence: int, safe_error: str | None = None
    ) -> bool:
        """Park a job whose external outcome is unknown. Never retried by itself."""

        with self._transaction() as conn:
            if self._held(conn, job_id, fence) is None:
                return False
            self._settle(
                conn,
                job_id,
                JobStatus.RECONCILIATION_REQUIRED,
                safe_error_code(safe_error) or "outcome_unknown",
            )
            return True

    def resolve_reconciliation(
        self,
        job_id: str,
        *,
        decision: Decision,
        run_at: datetime | None = None,
    ) -> bool:
        """Record the human/lookup decision for an uncertain job.

        ``retry`` re-queues it with a fresh attempt budget (``run_at`` required);
        the durable effect id is kept so the external service can deduplicate.
        """

        if decision == "retry" and run_at is None:
            raise ValueError("A retry decision needs run_at.")
        now_us = _to_us(datetime.now(UTC))
        with self._transaction() as conn:
            if run_at is not None and decision == "retry":
                sql = (
                    "UPDATE jobs SET status = 'queued', attempts = 0, run_at = ?, "
                    "last_error = NULL, updated_at = ? "
                    "WHERE id = ? AND status = ?"
                )
                args: tuple[object, ...] = (
                    _to_us(run_at),
                    now_us,
                    job_id,
                    JobStatus.RECONCILIATION_REQUIRED.value,
                )
            else:
                sql = (
                    "UPDATE jobs SET status = ?, updated_at = ? "
                    "WHERE id = ? AND status = ?"
                )
                args = (
                    JobStatus(decision).value,
                    now_us,
                    job_id,
                    JobStatus.RECONCILIATION_REQUIRED.value,
                )
            return conn.execute(sql, args).rowcount == 1

    def cancel(self, job_id: str) -> JobStatus | None:
        """Cancel a job; a running one is asked to stop and refused at commit."""

        now_us = _to_us(datetime.now(UTC))
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            status = JobStatus(row["status"])
            if status is JobStatus.LEASED:
                conn.execute(
                    "UPDATE jobs SET cancel_requested = 1, updated_at = ? "
                    "WHERE id = ?",
                    (now_us, job_id),
                )
                return status
            if status in (JobStatus.QUEUED, JobStatus.RECONCILIATION_REQUIRED):
                self._settle(conn, job_id, JobStatus.CANCELLED, "cancelled")
                return JobStatus.CANCELLED
            return status

    def should_abandon(self, job_id: str, *, fence: int) -> bool:
        """True when the effect must not start: stale fence or cancellation."""

        with self._owned_connection() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM jobs WHERE id = ? "
                "AND status = 'leased' AND fence = ?",
                (job_id, fence),
            ).fetchone()
        return row is None or bool(row["cancel_requested"])

    # --- reads ---------------------------------------------------------------

    def get(self, job_id: str) -> JobRecord | None:
        with self._owned_connection() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM jobs "  # noqa: S608 - module constant only
                "WHERE id = ?",
                (job_id,),
            ).fetchone()
        return None if row is None else self._record(row)

    def find_active(
        self, dedup_key: str, *, scope: str = SYSTEM_SCOPE
    ) -> JobRecord | None:
        with self._owned_connection() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM jobs "  # noqa: S608 - module constant only
                "WHERE scope = ? AND dedup_key = ? AND status IN (?, ?, ?)",
                (scope, dedup_key, *(s.value for s in ACTIVE_STATUSES)),
            ).fetchone()
        return None if row is None else self._record(row)

    # --- helpers -------------------------------------------------------------

    @staticmethod
    def _held(conn: sqlite3.Connection, job_id: str, fence: int) -> sqlite3.Row | None:
        row: sqlite3.Row | None = conn.execute(
            "SELECT attempts, max_attempts, cancel_requested FROM jobs "
            "WHERE id = ? AND status = 'leased' AND fence = ?",
            (job_id, fence),
        ).fetchone()
        return row

    @staticmethod
    def _settle(
        conn: sqlite3.Connection,
        job_id: str,
        status: JobStatus,
        error: str | None,
    ) -> None:
        conn.execute(
            "UPDATE jobs SET status = ?, lease_owner = NULL, lease_until = NULL, "
            "last_error = ?, updated_at = ? WHERE id = ?",
            (status.value, error, _to_us(datetime.now(UTC)), job_id),
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["id"],
            job_type=row["job_type"],
            scope=row["scope"],
            dedup_key=row["dedup_key"],
            payload_ref=row["payload_ref"],
            run_at=_from_us(row["run_at"]),
            status=JobStatus(row["status"]),
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            lease_owner=row["lease_owner"],
            lease_until=(
                None if row["lease_until"] is None else _from_us(row["lease_until"])
            ),
            fence=row["fence"],
            effect_id=row["effect_id"],
            last_error=row["last_error"],
            correlation_id=row["correlation_id"],
            cancel_requested=bool(row["cancel_requested"]),
        )


__all__ = ["JobRepository"]
