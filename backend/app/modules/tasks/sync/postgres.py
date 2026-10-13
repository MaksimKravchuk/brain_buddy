"""PostgreSQL target for the Tasks / receipt / feed / job unit of work (spec 026 PR-55).

026-FR-005/006/014/015, 026-SC-002/007. This is the *dark* migration target: it
satisfies the same ports the SQLite adapters satisfy, and nothing registers it.
The container still builds the SQLite writer; ``postgres_cutover`` (PR-57) is the
only thing that may switch. It needs the optional ``postgres`` extra (psycopg 3).

How the guarantees map onto PostgreSQL:

* **One transaction.** :meth:`PostgresTaskUnitOfWork.begin` opens one connection
  and one transaction. Aggregate documents, receipts, the feed and job intents
  are written on it and commit once, or roll back together.
* **Owner lock and commit order.** The transaction takes
  ``pg_advisory_xact_lock`` for the owner. It is released only by commit or
  rollback, so a second writer of that owner waits for the whole commit and the
  per-owner ``commit_seq`` (allocated under the lock) is the commit order.
* **Fences.** A bound job is re-checked under that lock with ``FOR SHARE`` on its
  ledger row, so a cancel, heartbeat or reclaim (all ``UPDATE`` the row) waits
  until the unit commits: the fence cannot move between check and commit.
* **Read sets.** Rows are read and fingerprinted under the same owner lock, so a
  stale read set is detected by the shared ``OwnerUnitOfWork.verify``.
* **Generations** (server / feed / access / storage epoch) live in
  ``sync_scopes`` and are enforced by the shared ``CommandReceipts`` policy.

Only Tasks, Projects and Tags are stored here as owner-scoped documents; the
remaining aggregate tables arrive with the stopped-writer migration (PR-56).
"""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel

from app.exceptions import NotFoundError, RepositoryError
from app.modules.tasks.domain import ProjectDocument, TagDocument, TaskDocument
from app.modules.tasks.jobs.domain import (
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
from app.modules.tasks.jobs.execution import owner_write_lock
from app.modules.tasks.rust_adapter import RustCore

from .change_log import AtomicChangeLog, encode
from .receipts import CommandReceipts, ReceiptCommand, ScopeAuthority, StorageRow
from .unit_of_work import OwnerUnitOfWork, UnitOfWorkError

type PgConnection = psycopg.Connection[dict[str, Any]]

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS task_documents (owner_id TEXT NOT NULL, "
    "kind TEXT NOT NULL, doc_id TEXT NOT NULL, document TEXT NOT NULL, "
    "PRIMARY KEY(owner_id, kind, doc_id))",
    "CREATE TABLE IF NOT EXISTS sync_scopes (owner_id TEXT PRIMARY KEY, "
    "server_generation TEXT NOT NULL, feed_generation TEXT NOT NULL, "
    "access_generation TEXT NOT NULL, storage_epoch TEXT NOT NULL, "
    "admission_open BOOLEAN NOT NULL, commit_seq BIGINT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS sync_command_receipts (owner_id TEXT NOT NULL, "
    "command_id TEXT NOT NULL, writer_origin TEXT NOT NULL, "
    "fingerprint TEXT NOT NULL, metadata TEXT NOT NULL, result TEXT, "
    "created_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL, "
    "PRIMARY KEY(owner_id, command_id))",
    "CREATE TABLE IF NOT EXISTS sync_legacy_keys (owner_id TEXT NOT NULL, "
    "key_digest TEXT NOT NULL, command_id TEXT NOT NULL, "
    "PRIMARY KEY(owner_id, key_digest))",
    "CREATE TABLE IF NOT EXISTS sync_record_versions (owner_id TEXT NOT NULL, "
    "entity_type TEXT NOT NULL, record_key TEXT NOT NULL, "
    "record_version BIGINT NOT NULL, deleted BOOLEAN NOT NULL, "
    "PRIMARY KEY(owner_id, entity_type, record_key))",
    "CREATE TABLE IF NOT EXISTS sync_change_transactions (owner_id TEXT NOT NULL, "
    "commit_seq BIGINT NOT NULL, transaction_id TEXT NOT NULL, "
    "source_command_id TEXT NOT NULL, committed_at TIMESTAMPTZ NOT NULL, "
    "PRIMARY KEY(owner_id, commit_seq), UNIQUE(owner_id, transaction_id), "
    "UNIQUE(owner_id, source_command_id))",
    "CREATE TABLE IF NOT EXISTS sync_change_records (owner_id TEXT NOT NULL, "
    "commit_seq BIGINT NOT NULL, entity_type TEXT NOT NULL, "
    "record_key TEXT NOT NULL, record_version BIGINT NOT NULL, "
    "edit_revision TEXT, operation TEXT NOT NULL, value TEXT, "
    "source_expires_at TIMESTAMPTZ, "
    "PRIMARY KEY(owner_id, commit_seq, entity_type, record_key), "
    "FOREIGN KEY(owner_id, commit_seq) REFERENCES "
    "sync_change_transactions(owner_id, commit_seq) ON DELETE CASCADE)",
    "CREATE INDEX IF NOT EXISTS sync_receipt_expiry "
    "ON sync_command_receipts(owner_id, expires_at)",
    "CREATE INDEX IF NOT EXISTS sync_change_record_history "
    "ON sync_change_records(owner_id, entity_type, record_key)",
    "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, scope TEXT NOT NULL, "
    "job_type TEXT NOT NULL, dedup_key TEXT NOT NULL, payload_ref TEXT, "
    "run_at TIMESTAMPTZ NOT NULL, status TEXT NOT NULL, "
    "attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL, "
    "lease_owner TEXT, lease_until TIMESTAMPTZ, fence BIGINT NOT NULL DEFAULT 0, "
    "effect_id TEXT NOT NULL, last_error TEXT, correlation_id TEXT, "
    "cancel_requested BOOLEAN NOT NULL DEFAULT FALSE, "
    "created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_active_dedup ON jobs(scope, dedup_key) "
    "WHERE status IN ('queued', 'leased', 'reconciliation_required')",
    "CREATE INDEX IF NOT EXISTS idx_jobs_due ON jobs(status, run_at, id)",
    "CREATE TABLE IF NOT EXISTS job_fence_counter (id INTEGER PRIMARY KEY "
    "CHECK (id = 1), value BIGINT NOT NULL)",
    "INSERT INTO job_fence_counter (id, value) VALUES (1, 0) ON CONFLICT DO NOTHING",
)
_PURGE = (
    "DELETE FROM task_documents WHERE owner_id = %s",
    "DELETE FROM sync_change_records WHERE owner_id = %s",
    "DELETE FROM sync_change_transactions WHERE owner_id = %s",
    "DELETE FROM sync_legacy_keys WHERE owner_id = %s",
    "DELETE FROM sync_command_receipts WHERE owner_id = %s",
    "DELETE FROM sync_record_versions WHERE owner_id = %s",
    "DELETE FROM sync_scopes WHERE owner_id = %s",
    "DELETE FROM jobs WHERE scope = %s",
)
_ACTIVE_STATUS_VALUES = [status.value for status in ACTIVE_STATUSES]
# The connection of the unit open in this thread of control, if any.
_ACTIVE: ContextVar[PgConnection | None] = ContextVar("pg_task_unit", default=None)


def connect(dsn: str) -> PgConnection:
    return psycopg.connect(dsn, row_factory=dict_row)


def initialize(conn: PgConnection) -> None:
    for statement in _SCHEMA:
        conn.execute(statement)
    conn.commit()


def purge_owner(conn: PgConnection, owner_id: str) -> None:
    """Remove every Tasks, receipt, feed and owner-bound job row of one owner."""
    for statement in _PURGE:
        conn.execute(statement, (owner_id,))


@contextmanager
def _reader(dsn: str) -> Iterator[PgConnection]:
    """The open unit's connection, else a short read-only one."""
    active = _ACTIVE.get()
    if active is not None:
        yield active
        return
    with connect(dsn) as conn:
        yield conn


# --- aggregate documents ------------------------------------------------------


class PostgresTaskStore:
    """Owner-scoped Task, Project and Tag documents; writes join the open unit."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def save_task(
        self, unit: OwnerUnitOfWork[PgConnection], task: TaskDocument
    ) -> None:
        self._save(unit, "Task", task.owner_id, task.id, task)

    def save_project(
        self, unit: OwnerUnitOfWork[PgConnection], project: ProjectDocument
    ) -> None:
        self._save(unit, "Project", project.owner_id, project.id, project)

    def save_tag(self, unit: OwnerUnitOfWork[PgConnection], tag: TagDocument) -> None:
        self._save(unit, "Tag", tag.owner_id, tag.id, tag)

    def delete_task(
        self, unit: OwnerUnitOfWork[PgConnection], owner_id: str, task_id: str
    ) -> None:
        unit.record_write(owner_id, "Task", task_id)
        unit.connection.execute(
            "DELETE FROM task_documents WHERE owner_id = %s AND kind = 'Task' "
            "AND doc_id = %s",
            (owner_id, task_id),
        )

    def get_for_owner(self, task_id: str, *, owner_id: str) -> TaskDocument:
        return self._get("Task", TaskDocument, task_id, owner_id)

    def get_project_for_owner(
        self, project_id: str, *, owner_id: str
    ) -> ProjectDocument:
        return self._get("Project", ProjectDocument, project_id, owner_id)

    def get_tag_for_owner(self, tag_id: str, *, owner_id: str) -> TagDocument:
        return self._get("Tag", TagDocument, tag_id, owner_id)

    def _save(
        self,
        unit: OwnerUnitOfWork[PgConnection],
        kind: str,
        owner_id: str,
        doc_id: str,
        document: BaseModel,
    ) -> None:
        unit.record_write(owner_id, kind, doc_id)  # refuses another owner first
        unit.connection.execute(
            "INSERT INTO task_documents VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (owner_id, kind, doc_id) DO UPDATE SET document = EXCLUDED.document",
            (owner_id, kind, doc_id, document.model_dump_json()),
        )

    def _get[ModelT: BaseModel](
        self, kind: str, model: type[ModelT], doc_id: str, owner_id: str
    ) -> ModelT:
        with _reader(self._dsn) as conn:
            row = conn.execute(
                "SELECT document FROM task_documents WHERE owner_id = %s "
                "AND kind = %s AND doc_id = %s",
                (owner_id, kind, doc_id),
            ).fetchone()
        if row is None:
            raise NotFoundError(kind, doc_id)
        return model.model_validate_json(row["document"])


# --- job ledger -----------------------------------------------------------------


def _full_jitter(cap: float) -> float:
    return secrets.SystemRandom().uniform(0.0, cap)


class PostgresJobLedger:
    """Fenced job leases over the same database as the Tasks documents."""

    def __init__(
        self, dsn: str, *, jitter: Callable[[float], float] = _full_jitter
    ) -> None:
        self._dsn = dsn
        self._jitter = jitter

    @contextmanager
    def _tx(self) -> Iterator[PgConnection]:
        with connect(self._dsn) as conn:  # commits on success, rolls back on error
            yield conn

    def ensure_scheduled(
        self, *, job_type: str, dedup_key: str, run_at: datetime, **options: Any
    ) -> bool:
        with self._tx() as conn:
            return self.schedule_in(
                conn, job_type=job_type, dedup_key=dedup_key, run_at=run_at, **options
            )

    def schedule_in(
        self,
        conn: PgConnection,
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
        """Create the job unless one is active; the caller owns the transaction."""
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        now = datetime.now(UTC)
        existing = conn.execute(
            "SELECT id, status, run_at FROM jobs WHERE scope = %s AND dedup_key = %s "
            "AND status = ANY(%s) FOR UPDATE",
            (scope, dedup_key, _ACTIVE_STATUS_VALUES),
        ).fetchone()
        if existing is not None:
            if (
                pull_forward
                and existing["status"] == JobStatus.QUEUED
                and existing["run_at"] > run_at
            ):
                conn.execute(
                    "UPDATE jobs SET run_at = %s, updated_at = %s WHERE id = %s",
                    (run_at, now, existing["id"]),
                )
            return False
        inserted = conn.execute(
            "INSERT INTO jobs (id, scope, job_type, dedup_key, payload_ref, run_at, "
            "status, max_attempts, effect_id, correlation_id, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'queued', %s, %s, %s, %s, %s) "
            "ON CONFLICT (scope, dedup_key) "
            "WHERE status IN ('queued', 'leased', 'reconciliation_required') "
            "DO NOTHING",
            (
                uuid.uuid4().hex,
                scope,
                job_type,
                dedup_key,
                payload_ref,
                run_at,
                max_attempts,
                uuid.uuid4().hex,
                correlation_id,
                now,
                now,
            ),
        )
        return inserted.rowcount == 1

    def claim_due(
        self,
        *,
        owner: str,
        types: Sequence[str],
        now: datetime,
        lease_for: timedelta = LEASE,
    ) -> JobLease | None:
        """Lease the oldest due job of ``types`` under a fresh, monotonic fence."""
        if not types:
            return None
        wanted = list(types)
        with self._tx() as conn:
            self._recover_expired(conn, wanted, now)
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_type = ANY(%s) AND status = 'queued' "
                "AND run_at <= %s ORDER BY run_at, id LIMIT 1 FOR UPDATE SKIP LOCKED",
                (wanted, now),
            ).fetchone()
            if row is None:
                return None
            counter = conn.execute(
                "UPDATE job_fence_counter SET value = value + 1 "
                "WHERE id = 1 RETURNING value"
            ).fetchone()
            assert counter is not None
            fence = int(counter["value"])
            until = now + lease_for
            conn.execute(
                "UPDATE jobs SET status = 'leased', lease_owner = %s, lease_until = %s, "
                "fence = %s, attempts = attempts + 1, updated_at = %s WHERE id = %s",
                (owner, until, fence, now, row["id"]),
            )
            return JobLease(
                job_id=row["id"],
                job_type=row["job_type"],
                scope=row["scope"],
                dedup_key=row["dedup_key"],
                payload_ref=row["payload_ref"],
                owner=owner,
                fence=fence,
                lease_until=until,
                attempt=row["attempts"] + 1,
                max_attempts=row["max_attempts"],
                effect_id=row["effect_id"],
            )

    def _recover_expired(
        self, conn: PgConnection, wanted: list[str], now: datetime
    ) -> None:
        """Close cancelled/exhausted expired leases; requeue the rest with backoff."""
        conn.execute(
            "UPDATE jobs SET status = 'cancelled', lease_owner = NULL, "
            "lease_until = NULL, last_error = 'cancelled', updated_at = %s "
            "WHERE status = 'leased' AND lease_until <= %s AND cancel_requested "
            "AND job_type = ANY(%s)",
            (now, now, wanted),
        )
        conn.execute(
            "UPDATE jobs SET status = 'failed', lease_owner = NULL, "
            "lease_until = NULL, last_error = 'lease_expired', updated_at = %s "
            "WHERE status = 'leased' AND lease_until <= %s "
            "AND attempts >= max_attempts AND job_type = ANY(%s)",
            (now, now, wanted),
        )
        expired = conn.execute(
            "SELECT id, attempts FROM jobs WHERE status = 'leased' "
            "AND lease_until <= %s AND job_type = ANY(%s) FOR UPDATE",
            (now, wanted),
        ).fetchall()
        for row in expired:
            cap = BACKOFF_CAPS[min(max(row["attempts"], 1), len(BACKOFF_CAPS)) - 1]
            conn.execute(
                "UPDATE jobs SET status = 'queued', run_at = %s, lease_owner = NULL, "
                "lease_until = NULL, last_error = 'lease_expired', updated_at = %s "
                "WHERE id = %s",
                (now + timedelta(seconds=self._jitter(cap)), now, row["id"]),
            )

    def heartbeat(
        self, job_id: str, *, owner: str, fence: int, until: datetime
    ) -> bool:
        with self._tx() as conn:
            return (
                conn.execute(
                    "UPDATE jobs SET lease_until = GREATEST(lease_until, %s) "
                    "WHERE id = %s AND status = 'leased' AND lease_owner = %s "
                    "AND fence = %s",
                    (until, job_id, owner, fence),
                ).rowcount
                == 1
            )

    def complete(self, job_id: str, *, fence: int) -> bool:
        """Accept a result only under the current fence and without a cancel."""
        with self._tx() as conn:
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
        """Record a failed attempt; ``True`` when the retry budget is exhausted."""
        with self._tx() as conn:
            row = self._held(conn, job_id, fence)
            if row is None:
                return False
            if row["cancel_requested"]:
                self._settle(conn, job_id, JobStatus.CANCELLED, "cancelled")
                return False
            code = safe_error_code(safe_error) or "failed"
            if row["attempts"] >= row["max_attempts"]:
                self._settle(conn, job_id, JobStatus.FAILED, code)
                return True
            cap = BACKOFF_CAPS[min(row["attempts"], len(BACKOFF_CAPS)) - 1]
            conn.execute(
                "UPDATE jobs SET status = 'queued', run_at = %s, lease_owner = NULL, "
                "lease_until = NULL, last_error = %s, updated_at = %s WHERE id = %s",
                (now + timedelta(seconds=self._jitter(cap)), code, now, job_id),
            )
            return False

    def mark_uncertain(
        self, job_id: str, *, fence: int, safe_error: str | None = None
    ) -> bool:
        with self._tx() as conn:
            if self._held(conn, job_id, fence) is None:
                return False
            code = safe_error_code(safe_error) or "outcome_unknown"
            self._settle(conn, job_id, JobStatus.RECONCILIATION_REQUIRED, code)
            return True

    def cancel(self, job_id: str) -> JobStatus | None:
        """Cancel a job; a running one is asked to stop and refused at commit."""
        with self._tx() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE id = %s FOR UPDATE", (job_id,)
            ).fetchone()
            if row is None:
                return None
            status = JobStatus(row["status"])
            if status is JobStatus.LEASED:
                conn.execute(
                    "UPDATE jobs SET cancel_requested = TRUE, updated_at = %s "
                    "WHERE id = %s",
                    (datetime.now(UTC), job_id),
                )
                return status
            if status in (JobStatus.QUEUED, JobStatus.RECONCILIATION_REQUIRED):
                self._settle(conn, job_id, JobStatus.CANCELLED, "cancelled")
                return JobStatus.CANCELLED
            return status

    def should_abandon(self, job_id: str, *, fence: int, now: datetime) -> bool:
        """True when the effect must not start or continue.

        Inside an open unit the row is read ``FOR SHARE`` on the unit's own
        transaction: a cancel, heartbeat or reclaim then waits for the commit.
        """
        with _reader(self._dsn) as conn:
            row = conn.execute(
                "SELECT cancel_requested, lease_until FROM jobs WHERE id = %s "
                "AND status = 'leased' AND fence = %s FOR SHARE",
                (job_id, fence),
            ).fetchone()
        return row is None or bool(row["cancel_requested"]) or row["lease_until"] <= now

    def get(self, job_id: str) -> JobRecord | None:
        with _reader(self._dsn) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
        return None if row is None else self._record(row)

    def find_active(
        self, dedup_key: str, *, scope: str = SYSTEM_SCOPE
    ) -> JobRecord | None:
        with _reader(self._dsn) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE scope = %s AND dedup_key = %s "
                "AND status = ANY(%s)",
                (scope, dedup_key, _ACTIVE_STATUS_VALUES),
            ).fetchone()
        return None if row is None else self._record(row)

    @staticmethod
    def _held(conn: PgConnection, job_id: str, fence: int) -> dict[str, Any] | None:
        return conn.execute(
            "SELECT attempts, max_attempts, cancel_requested FROM jobs "
            "WHERE id = %s AND status = 'leased' AND fence = %s FOR UPDATE",
            (job_id, fence),
        ).fetchone()

    @staticmethod
    def _settle(
        conn: PgConnection, job_id: str, status: JobStatus, error: str | None
    ) -> None:
        conn.execute(
            "UPDATE jobs SET status = %s, lease_owner = NULL, lease_until = NULL, "
            "last_error = %s, updated_at = %s WHERE id = %s",
            (status.value, error, datetime.now(UTC), job_id),
        )

    @staticmethod
    def _record(row: dict[str, Any]) -> JobRecord:
        return JobRecord(
            job_id=row["id"],
            job_type=row["job_type"],
            scope=row["scope"],
            dedup_key=row["dedup_key"],
            payload_ref=row["payload_ref"],
            run_at=row["run_at"],
            status=JobStatus(row["status"]),
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            lease_owner=row["lease_owner"],
            lease_until=row["lease_until"],
            fence=row["fence"],
            effect_id=row["effect_id"],
            last_error=row["last_error"],
            correlation_id=row["correlation_id"],
            cancel_requested=row["cancel_requested"],
        )


# --- unit of work ---------------------------------------------------------------


class _PostgresUnit(OwnerUnitOfWork[PgConnection]):
    """The shared unit, with lifecycle hooks the PostgreSQL ``begin`` may call."""

    def finish(self) -> None:
        self._end()

    def publish_after_commit(self) -> None:
        self._run_after_commit()


class _OwnerAdvisoryLock:
    """The ``TaskWriterLock`` port: one owner's lock, held to commit/rollback."""

    def __init__(self, conn: PgConnection) -> None:
        self._conn = conn

    @contextmanager
    def command_lock(self, owner_id: str) -> Iterator[None]:
        self._conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"bb.tasks.owner:{owner_id}",),
        )
        yield


class PostgresTaskUnitOfWork:
    """Opens one owner-scoped PostgreSQL transaction over Tasks, feed and jobs."""

    def __init__(
        self, dsn: str, store: PostgresTaskStore, jobs: PostgresJobLedger
    ) -> None:
        self._dsn = dsn
        self._store = store
        self._jobs = jobs

    @contextmanager
    def begin(
        self, owner_id: str, *, cleanup: bool = False
    ) -> Iterator[OwnerUnitOfWork[PgConnection]]:
        """Hold ``owner_id``'s lock; commit once on exit, roll back on error."""
        if _ACTIVE.get() is not None:
            raise UnitOfWorkError(
                "A unit of work is already open on this thread; "
                "the owner lock is not re-entrant."
            )
        conn = connect(self._dsn)
        token = _ACTIVE.set(conn)
        try:
            with owner_write_lock(_OwnerAdvisoryLock(conn), owner_id, cleanup=cleanup):
                unit = _PostgresUnit(owner_id, self._store, self._jobs, conn)
                try:
                    yield unit
                finally:
                    unit.finish()
            conn.commit()
        except BaseException:
            # A killed backend has nothing left to roll back; keep the original error.
            with suppress(psycopg.Error):
                conn.rollback()
            raise
        finally:
            _ACTIVE.reset(token)
            conn.close()
        unit.publish_after_commit()


# --- feed and receipts ------------------------------------------------------------


class PostgresChangeLog(AtomicChangeLog[PgConnection]):
    """PostgreSQL storage hooks; the shared policy stays in AtomicChangeLog."""

    def _next_sequence(self, unit: OwnerUnitOfWork[PgConnection]) -> str:
        row = unit.connection.execute(
            "UPDATE sync_scopes SET commit_seq = commit_seq + 1 "
            "WHERE owner_id = %s RETURNING commit_seq",
            (unit.owner_id,),
        ).fetchone()
        if row is None:
            raise RepositoryError("RESET_REQUIRED")
        return str(row["commit_seq"])

    def _next_version(
        self,
        unit: OwnerUnitOfWork[PgConnection],
        entity_type: str,
        key: str,
        *,
        deleted: bool,
    ) -> str:
        row = unit.connection.execute(
            "INSERT INTO sync_record_versions VALUES (%s, %s, %s, 1, %s) "
            "ON CONFLICT (owner_id, entity_type, record_key) DO UPDATE SET "
            "record_version = sync_record_versions.record_version + 1, "
            "deleted = EXCLUDED.deleted RETURNING record_version",
            (unit.owner_id, entity_type, key, deleted),
        ).fetchone()
        assert row is not None
        return str(row["record_version"])

    def _insert_transaction(
        self,
        unit: OwnerUnitOfWork[PgConnection],
        transaction: dict[str, Any],
        *,
        now: datetime,
    ) -> None:
        unit.connection.execute(
            "INSERT INTO sync_change_transactions VALUES (%s, %s::bigint, %s, %s, %s)",
            (
                unit.owner_id,
                transaction["commit_seq"],
                transaction["transaction_id"],
                transaction["source_command_id"],
                now,
            ),
        )

    def _insert_change(
        self, unit: OwnerUnitOfWork[PgConnection], sequence: str, row: dict[str, Any]
    ) -> None:
        unit.connection.execute(
            "INSERT INTO sync_change_records VALUES "
            "(%s, %s::bigint, %s, %s, %s::bigint, %s, %s, %s, NULL)",
            (
                unit.owner_id,
                sequence,
                row["entity_type"],
                encode(row["record_key"]),
                row["record_version"],
                row.get("edit_revision"),
                row["operation"],
                encode(row["value"]) if row["value"] is not None else None,
            ),
        )

    def redact_record(
        self,
        unit: OwnerUnitOfWork[PgConnection],
        entity_type: str,
        record_key: list[str],
    ) -> None:
        """Redact receipts, null the record's feed values, invalidate the feed."""
        conn, owner = unit.connection, unit.owner_id
        last_command_id = ""
        while receipts := conn.execute(
            "SELECT command_id, metadata FROM sync_command_receipts "
            "WHERE owner_id = %s AND command_id > %s ORDER BY command_id LIMIT 64",
            (owner, last_command_id),
        ).fetchall():
            for receipt in receipts:
                metadata = json.loads(receipt["metadata"])
                metadata["result_redacted"] = True
                conn.execute(
                    "UPDATE sync_command_receipts SET metadata = %s, result = NULL "
                    "WHERE owner_id = %s AND command_id = %s",
                    (encode(metadata), owner, receipt["command_id"]),
                )
            last_command_id = receipts[-1]["command_id"]
        conn.execute(
            "UPDATE sync_change_records SET value = NULL WHERE owner_id = %s "
            "AND entity_type = %s AND record_key = %s",
            (owner, entity_type, encode(record_key)),
        )
        conn.execute(
            "UPDATE sync_scopes SET feed_generation = %s WHERE owner_id = %s",
            (str(uuid.uuid4()), owner),
        )

    def prune(self, unit: OwnerUnitOfWork[PgConnection], *, now: datetime) -> None:
        conn, owner = unit.connection, unit.owner_id
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL "
            "WHERE owner_id = %s AND expires_at <= %s",
            (owner, now),
        )
        conn.execute(
            "DELETE FROM sync_change_transactions "
            "WHERE owner_id = %s AND committed_at <= %s",
            (owner, now - timedelta(days=90)),
        )

    def _transactions(
        self, unit: OwnerUnitOfWork[PgConnection], *, after: str = "0"
    ) -> list[dict[str, Any]]:
        conn, owner = unit.connection, unit.owner_id
        headers = conn.execute(
            "SELECT * FROM sync_change_transactions WHERE owner_id = %s "
            "AND commit_seq > %s::bigint ORDER BY commit_seq",
            (owner, after),
        ).fetchall()
        result = []
        for header in headers:
            rows = conn.execute(
                "SELECT * FROM sync_change_records WHERE owner_id = %s "
                "AND commit_seq = %s ORDER BY entity_type, record_key",
                (owner, header["commit_seq"]),
            ).fetchall()
            if any(r["operation"] == "upsert" and r["value"] is None for r in rows):
                raise RepositoryError("RESET_REQUIRED")
            changes = [
                {
                    "entity_type": r["entity_type"],
                    "record_key": json.loads(r["record_key"]),
                    "record_version": str(r["record_version"]),
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
                    "commit_seq": str(header["commit_seq"]),
                    "source_command_id": header["source_command_id"],
                    "changes": changes,
                }
            )
        return result


class PostgresReceiptStore(CommandReceipts[PgConnection]):
    """PostgreSQL storage hooks; the shared policy stays in CommandReceipts."""

    def __init__(self, core: RustCore) -> None:
        super().__init__(core, PostgresChangeLog(core))

    def _scope_row(self, unit: OwnerUnitOfWork[PgConnection]) -> StorageRow | None:
        return unit.connection.execute(
            "SELECT * FROM sync_scopes WHERE owner_id = %s", (unit.owner_id,)
        ).fetchone()

    def _insert_scope(
        self, unit: OwnerUnitOfWork[PgConnection], current: ScopeAuthority
    ) -> None:
        unit.connection.execute(
            "INSERT INTO sync_scopes VALUES (%s, %s, %s, %s, %s, TRUE, 0)",
            (
                unit.owner_id,
                current.server_generation,
                current.feed_generation,
                current.access_generation,
                current.storage_epoch,
            ),
        )

    def _legacy_command_id(
        self, unit: OwnerUnitOfWork[PgConnection], key_digest: str
    ) -> str | None:
        row = unit.connection.execute(
            "SELECT command_id FROM sync_legacy_keys "
            "WHERE owner_id = %s AND key_digest = %s",
            (unit.owner_id, key_digest),
        ).fetchone()
        return None if row is None else str(row["command_id"])

    def _receipt_row(
        self, unit: OwnerUnitOfWork[PgConnection], command_id: str
    ) -> StorageRow | None:
        row = unit.connection.execute(
            "SELECT * FROM sync_command_receipts WHERE owner_id = %s AND command_id = %s",
            (unit.owner_id, command_id),
        ).fetchone()
        if row is None:
            return None
        # The shared policy reads timestamps as ISO-8601 text.
        return {
            **row,
            "created_at": row["created_at"].isoformat(),
            "expires_at": row["expires_at"].isoformat(),
        }

    def _redact_result(
        self, unit: OwnerUnitOfWork[PgConnection], command_id: str
    ) -> None:
        unit.connection.execute(
            "UPDATE sync_command_receipts SET result = NULL "
            "WHERE owner_id = %s AND command_id = %s",
            (unit.owner_id, command_id),
        )

    def _write_receipt(
        self,
        command: ReceiptCommand[PgConnection],
        metadata: dict[str, Any],
        result: dict[str, Any] | None,
        *,
        expires_at: datetime,
    ) -> None:
        conn, owner = command.unit.connection, command.unit.owner_id
        conn.execute(
            "INSERT INTO sync_command_receipts VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                owner,
                command.command_id,
                command.request.origin,
                command.fingerprint,
                encode(metadata),
                encode(result) if result is not None else None,
                command.now,
                expires_at,
            ),
        )
        if command.request.key_digest is not None:
            conn.execute(
                "INSERT INTO sync_legacy_keys VALUES (%s, %s, %s)",
                (owner, command.request.key_digest, command.command_id),
            )


__all__ = [
    "PgConnection",
    "PostgresChangeLog",
    "PostgresJobLedger",
    "PostgresReceiptStore",
    "PostgresTaskStore",
    "PostgresTaskUnitOfWork",
    "connect",
    "initialize",
    "purge_owner",
]
