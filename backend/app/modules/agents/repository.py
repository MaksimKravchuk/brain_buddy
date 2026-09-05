"""SQLite persistence for the external-agent relay module.

Deliberately SQLite-only: unlike the task module this repository writes no JSON
mirror, because these rows carry sealed connector credentials and relayed user
content, and a second plaintext-path copy would widen both the retention surface
(FR-015) and the blast radius of a disk leak.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar, TypeVar
from weakref import WeakValueDictionary

from pydantic import BaseModel, ValidationError

from app.core.logging import get_correlation_id
from app.exceptions import (
    ConflictError,
    NotFoundError,
    RepositoryError,
    StorageUnavailableError,
)
from app.repositories.base import BaseRepository
from app.utils.time import utcnow

from .domain import (
    A2A_SCHEMA_VERSION,
    TERMINAL_REPORTED_STATES,
    AgentAuditEntryDocument,
    AgentConnectionDocument,
    AgentIdempotencyRecord,
    AgentRunCommandDocument,
    AgentRunDocument,
    AgentRunEventDocument,
    project_run_for_access,
)
from .headers import validate_auth_header_name
from .secrets import fingerprint_key_id, key_id_from_sealed

ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class LiveIdempotencyKeys:
    """Readable key ids and the count of live rows that cannot be parsed."""

    key_ids: frozenset[str]
    unreadable: int


IDEMPOTENCY_RETENTION = timedelta(hours=24)
"""How long a replayed relay command stays addressable by its key."""

AUDIT_RETENTION = timedelta(days=90)
"""Upper bound on audit metadata (FR-015). Content retention is far shorter."""

"""How long a consumed event ID blocks a replay; matches content retention."""

A2A_WIRE_MIGRATION = "a2a_wire_contract_v1"
"""Ledger name of the one-way migration off the bespoke relay wire (SC-010)."""

DUE_OBSERVATION_BATCH = 200

logger = logging.getLogger(__name__)

#: Every column of the content tier (data-model.md §8). The sweep's
#: selection predicate re-derives from these rather than trusting
#: `content_expired`, so a value written *after* an expiry — by a late
#: observation, or by a partial pass — is picked up and erased on the next
#: run instead of surviving because a flag already says it is gone.
CONTENT_TIER_RUN_FIELDS: tuple[str, ...] = (
    "manifest",
    "progress_text",
    "question_text",
    "result_text",
    "result_link",
    "failure_reason",
    "blocked_reason",
    "result_availability",
)

#: SQL that is true when any content column still holds a value. Built
#: from the tuple above so the two cannot drift apart.
_CONTENT_PRESENT_SQL = " OR ".join(
    (
        *(
            f"json_extract(runs.payload, '$.{field}') IS NOT NULL"
            for field in CONTENT_TIER_RUN_FIELDS
        ),
        "json_array_length("
        "coalesce(json_extract(runs.payload, '$.artifacts_summary'), '[]')"
        ") > 0",
    )
)

#: The one query that selects a run whose content tier is due. Assembled from
#: the constants above rather than written out, so adding a content column
#: cannot leave the predicate behind and quietly stop erasing it.
_DUE_CONTENT_QUERY = f"""
    SELECT owner_id, id, payload FROM agent_runs AS runs
    WHERE dispatched_at IS NOT NULL
        AND content_expires_at <= ?
        AND (
            content_expired = 0
            OR ({_CONTENT_PRESENT_SQL})
            OR EXISTS (
                SELECT 1 FROM agent_run_events AS events
                WHERE events.owner_id = runs.owner_id
                    AND events.run_id = runs.id
                    AND json_extract(events.payload, '$.summary') IS NOT NULL
            )
            OR EXISTS (
                SELECT 1 FROM agent_run_commands AS commands
                WHERE commands.owner_id = runs.owner_id
                    AND commands.run_id = runs.id
                    AND json_extract(commands.payload, '$.body') IS NOT NULL
            )
        )
"""  # noqa: S608 - interpolates module constants only, never a caller's value


#: Every identifier-tier column (data-model.md §8). Not the run id: the
#: conversation identifier *is* the run id, it lives in a callback URL the
#: agent keeps and in a row no sweep deletes, so nulling it would erase
#: nothing anyone holds. `docs/data-retention.md` says so rather than
#: implying otherwise.
IDENTIFIER_TIER_RUN_FIELDS: tuple[str, ...] = (
    "message_id",
    "agent_task_id",
    "interface_url",
    "card_fingerprint",
    "push_token_fingerprint",
)

#: How long a dispatched run keeps the identifiers an agent could act on.
IDENTIFIER_RETENTION = timedelta(days=90)
"""Upper bound on the runs one scheduler pass may claim.

A backlog — an outage, a restart, a clock jump — must not turn into one
unbounded query and one unbounded storm of submits. The pass takes what its
bounded pools can actually work on and leaves the rest for the next tick, which
is a delay rather than an incident.
"""

_TERMINAL_STATES: tuple[str, ...] = tuple(sorted(TERMINAL_REPORTED_STATES))
_TERMINAL_PLACEHOLDERS = ", ".join("?" for _ in _TERMINAL_STATES)


def _decoded_payload(raw: str) -> dict[str, Any] | None:
    """One stored payload as a mapping, or ``None`` when it is not one.

    Three startup migrations walk raw rows, and each has to survive a payload
    that is not JSON or not an object — a row a different image, or a partial
    write, left behind. Deciding that once means a corrupt row is skipped the
    same way everywhere, instead of aborting whichever pass happens to reach it
    first and taking every healthy row's migration down with it.

    The annotation says what the column is declared to hold; ``TypeError`` is
    caught because SQLite's typing is a suggestion, not a guarantee.
    """

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _bumped_revision(payload: Mapping[str, Any]) -> int:
    """The next revision for a row a migration rewrites.

    A migration changes a record behind the owner's back, so the revision has
    to move: a client still holding the old one must not be able to apply an
    update against a row that changed underneath it. The coercion is for a
    corrupt value — these rows are being rewritten precisely because they may
    be — and 1 is the floor the document model itself enforces.
    """

    try:
        current = int(payload.get("revision", 1))
    except (TypeError, ValueError, OverflowError):
        current = 1
    return min(max(current, 1), 2_147_483_646) + 1


@contextmanager
def _sqlite_guard(resource: str, identifier: str) -> Iterator[None]:
    """Translate raw ``sqlite3`` failures into the app's domain exceptions."""

    try:
        yield
    except sqlite3.IntegrityError as exc:
        raise ConflictError(
            resource,
            identifier,
            f"{resource} '{identifier}' conflicts with existing records.",
        ) from exc
    except sqlite3.OperationalError as exc:
        raise StorageUnavailableError(
            "Agent storage is temporarily unavailable; retry the request."
        ) from exc
    except sqlite3.Error as exc:
        raise RepositoryError(
            f"Agent storage failed while writing {resource} '{identifier}'."
        ) from exc


class AgentRepository(BaseRepository):
    """Store relay records in one owner-isolated SQLite database."""

    _thread_state: ClassVar[threading.local] = threading.local()
    _process_lock: ClassVar[threading.RLock] = threading.RLock()
    _operation_locks_guard: ClassVar[threading.Lock] = threading.Lock()
    _operation_locks: ClassVar[WeakValueDictionary[tuple[str, str, str], Any]] = (
        WeakValueDictionary()
    )

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.db_path = self.resolve("agents.sqlite3")
        self._initialize_database()

    def has_any_relay_data(self) -> bool:
        """Whether any relay-owned table contains a durable record."""

        with self._connection() as conn:
            row = conn.execute("""
                SELECT 1 FROM agent_connections LIMIT 1
                """).fetchone()
            if row is not None:
                return True
            for query in (
                "SELECT 1 FROM agent_runs LIMIT 1",
                "SELECT 1 FROM agent_run_events LIMIT 1",
                "SELECT 1 FROM agent_run_commands LIMIT 1",
                "SELECT 1 FROM agent_audit LIMIT 1",
                "SELECT 1 FROM agent_idempotency LIMIT 1",
            ):
                if conn.execute(query).fetchone() is not None:
                    return True
        return False

    # --- connection plumbing ------------------------------------------------

    @contextmanager
    def operation_lock(
        self, owner_id: str, operation_fingerprint: str
    ) -> Iterator[None]:
        """Serialize one idempotent intent without holding a database writer."""

        coordinate = (str(self.db_path), owner_id, operation_fingerprint)
        with self._operation_locks_guard:
            lock = self._operation_locks.get(coordinate)
            if lock is None:
                lock = threading.RLock()
                self._operation_locks[coordinate] = lock
        with lock:
            yield

    @contextmanager
    def command_lock(self, owner_id: str) -> Iterator[None]:
        """Serialize owner-scoped commands and wrap writes in one transaction."""

        with self._process_lock:
            conn = self._connect()
            previous = getattr(self._thread_state, "conn", None)
            self._thread_state.conn = conn
            try:
                with _sqlite_guard("Agent command", owner_id):
                    conn.execute("BEGIN IMMEDIATE")
                    yield
                    conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                self._thread_state.conn = previous
                conn.close()

    def commit_checkpoint(self) -> None:
        """Durably land what the open command has written so far.

        A command that is about to leave the process has to have its
        reservation on disk *first*: if the call is lost mid-flight the agent
        may already hold that command ID, and a rolled-back reservation would
        let the retry mint a second one for the same intent. The owner's
        process lock is still held across the seam, so no other command of
        theirs can interleave here.
        """

        conn = getattr(self._thread_state, "conn", None)
        if conn is None:
            return
        with _sqlite_guard("Agent command", "checkpoint"):
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def _owned_connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        active = getattr(self._thread_state, "conn", None)
        if active is not None:
            yield active
            return
        with self._owned_connection() as conn:
            yield conn

    def _initialize_database(self) -> None:
        with self._owned_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agent_connections (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    connection_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    dispatched_at TEXT,
                    manifest_token TEXT,
                    content_expires_at TEXT NOT NULL,
                    content_expired INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runs_task
                    ON agent_runs(owner_id, task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_expiry
                    ON agent_runs(content_expired, content_expires_at);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_token
                    ON agent_runs(owner_id, manifest_token);
                CREATE TABLE IF NOT EXISTS agent_run_events (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    run_version INTEGER NOT NULL,
                    received_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, run_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_events_run
                    ON agent_run_events(owner_id, run_id, run_version);
                CREATE TABLE IF NOT EXISTS agent_run_commands (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_commands_run
                    ON agent_run_commands(owner_id, run_id, created_at);
                DROP TABLE IF EXISTS agent_event_ids;
                CREATE TABLE IF NOT EXISTS agent_audit (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_audit_created
                    ON agent_audit(created_at);
                -- The bounded-cardinality ledger behind `append_bounded_audit`.
                -- A real unique key rather than a read-then-write, so two
                -- workers racing the same class still write exactly one row.
                CREATE TABLE IF NOT EXISTS agent_audit_buckets (
                    owner_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    day TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (owner_id, action, bucket, day)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_audit_buckets_created
                    ON agent_audit_buckets(created_at);
                CREATE TABLE IF NOT EXISTS agent_idempotency (
                    owner_id TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    command TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    command_id TEXT,
                    completed INTEGER NOT NULL DEFAULT 1,
                    response_body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (owner_id, key_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_idempotency_created
                    ON agent_idempotency(created_at);
                """)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS agent_schema_migrations ("
                "name TEXT PRIMARY KEY)"
            )
            migration_name = "delivery_attempted_backfill_v1"
            migrated = conn.execute(
                "SELECT 1 FROM agent_schema_migrations WHERE name = ?",
                (migration_name,),
            ).fetchone()
            if migrated is None:
                # Keep ALTER, conservative legacy backfill, and the durable marker
                # in one SQLite transaction. If startup stops anywhere in this
                # block, the entire migration rolls back and the next startup
                # retries it rather than authorizing an ambiguous redelivery.
                conn.execute("BEGIN IMMEDIATE")
                try:
                    columns = {
                        row["name"]
                        for row in conn.execute("PRAGMA table_info(agent_idempotency)")
                    }
                    if "delivery_attempted" not in columns:
                        conn.execute(
                            "ALTER TABLE agent_idempotency "
                            "ADD COLUMN delivery_attempted "
                            "INTEGER NOT NULL DEFAULT 0"
                        )
                        columns.add("delivery_attempted")
                    if {
                        "completed",
                        "command_id",
                        "delivery_attempted",
                    }.issubset(columns):
                        conn.execute(
                            "UPDATE agent_idempotency "
                            "SET delivery_attempted = 1 "
                            "WHERE completed = 0 AND command_id IS NOT NULL "
                            "AND delivery_attempted = 0"
                        )
                    conn.execute(
                        "INSERT INTO agent_schema_migrations(name) VALUES (?)",
                        (migration_name,),
                    )
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    raise
            self._migrate_a2a_wire_contract(conn)
            self._migrate_legacy_invalid_connections(conn)
            # Deliberately outside the ledger and run on *every* startup: a
            # wire-less row can be created during a 007-image interlude between
            # two 014 boots, and it would otherwise sit unreadable until someone
            # noticed. Idempotent, exactly like
            # `_migrate_legacy_invalid_connections` above.
            self._supersede_bespoke_connections(conn)

    # --- the A2A wire migration (spec 014, FR-012, SC-010) -----------------

    _A2A_MIGRATION = A2A_WIRE_MIGRATION

    #: Columns the observer's scheduler and restart recovery read. They are real
    #: columns rather than JSON lookups because the due-work query runs across
    #: every owner on a schedule: scanning JSON would make the observer's cost
    #: grow with total history instead of with work actually due.
    _A2A_RUN_COLUMNS: ClassVar[dict[str, str]] = {
        "agent_task_id": "TEXT",
        "context_id": "TEXT",
        "next_observation_at": "TEXT",
        "exchange_state": "TEXT",
        "identifiers_expire_at": "TEXT",
    }

    def _migrate_a2a_wire_contract(self, conn: sqlite3.Connection) -> None:
        """Add the A2A run columns, once, under a durable ledger row.

        The ledger also records how many bespoke connections the *first* pass
        superseded. `docs/external-agent-relay-release.md` asks for that count
        before deploy so the "no production records" assumption is evidence
        rather than trust, and a number nobody wrote down is not evidence.
        """

        existing = conn.execute(
            "SELECT 1 FROM agent_schema_migrations WHERE name = ?",
            (self._A2A_MIGRATION,),
        ).fetchone()
        if existing is not None:
            return

        conn.execute("BEGIN IMMEDIATE")
        try:
            self._ensure_migration_ledger_columns(conn)
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(agent_runs)")
            }
            for name, sql_type in self._A2A_RUN_COLUMNS.items():
                if name not in columns:
                    conn.execute(
                        f"ALTER TABLE agent_runs ADD COLUMN {name} {sql_type}"  # noqa: S608 - names are module constants
                    )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_runs_observation "
                "ON agent_runs(next_observation_at)"
            )
            superseded = self._rewrite_bespoke_connections(conn)
            conn.execute(
                "INSERT INTO agent_schema_migrations(name, rewritten_rows, applied_at) "
                "VALUES (?, ?, ?)",
                (self._A2A_MIGRATION, superseded, utcnow().isoformat()),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    @staticmethod
    def _ensure_migration_ledger_columns(conn: sqlite3.Connection) -> None:
        """Widen the ledger so a migration can record what it actually did."""

        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(agent_schema_migrations)")
        }
        if "rewritten_rows" not in columns:
            conn.execute(
                "ALTER TABLE agent_schema_migrations ADD COLUMN rewritten_rows INTEGER"
            )
        if "applied_at" not in columns:
            conn.execute(
                "ALTER TABLE agent_schema_migrations ADD COLUMN applied_at TEXT"
            )

    def _supersede_bespoke_connections(self, conn: sqlite3.Connection) -> int:
        """Run the rewrite below in a transaction of its own.

        The ledgered migration calls the inner pass directly, inside its own
        ``BEGIN IMMEDIATE``, because the ALTER, the rewrite and the ledger row
        have to land or roll back together. Every later startup calls this
        wrapper instead. Splitting the two makes "who owns the transaction" a
        fact about the call site rather than a flag the body has to keep
        re-deciding.
        """

        conn.execute("BEGIN IMMEDIATE")
        try:
            rewritten = self._rewrite_bespoke_connections(conn)
            conn.commit()
            return rewritten
        except BaseException:
            conn.rollback()
            raise

    def _rewrite_bespoke_connections(self, conn: sqlite3.Connection) -> int:
        """Disconnect every connection that predates the A2A wire contract.

        A pre-014 record was configured against a wire this build no longer
        speaks: its credential is scoped to an endpoint BrainBuddy will never
        call again, and its inbound signing secret authorises a route that no
        longer exists. Leaving it "ready" would offer the owner a hand-off that
        cannot work; silently deleting it would erase a connection they
        configured. So it becomes **disconnected** with a reason that says why
        (D-01-S21), its credential and inbound secret are destroyed, and its
        in-flight runs are stamped so they stop pretending to be live.

        Idempotent by construction — it selects on the absence of
        ``wire == "a2a"`` and writes that key — so a second startup rewrites
        nothing and the count it returns is zero. The caller owns the
        transaction; nothing here is durable until that caller commits.
        """

        rows = conn.execute(
            "SELECT owner_id, id, payload FROM agent_connections"
        ).fetchall()
        now = utcnow()
        rewritten = 0
        for row in rows:
            payload = _decoded_payload(row["payload"])
            # An unreadable row is the quarantine migration's job. Taking it
            # here would supersede and quarantine the same row on one startup
            # and lose which of the two actually happened to it.
            if payload is None or payload.get("wire") == "a2a":
                continue
            self._write_superseded_connection(conn, row, payload, now=now)
            rewritten += 1
            self._migration_boundary("wire_superseded")
        return rewritten

    def _write_superseded_connection(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        payload: dict[str, Any],
        *,
        now: datetime,
    ) -> None:
        owner_id = str(row["owner_id"])
        connection_id = str(row["id"])
        payload.update(
            wire="a2a",
            status="disconnected",
            disconnect_reason="superseded_wire_contract",
            disconnected_at=now.isoformat(),
            credential=None,
            last_contact_at=None,
            scope_verified_at=None,
            first_dispatch_at=None,
            schema_version=A2A_SCHEMA_VERSION,
            revision=_bumped_revision(payload),
            updated_at=now.isoformat(),
        )
        # Dropped rather than nulled: the key itself is 007's, and the field no
        # longer exists on the 014 model.
        payload.pop("inbound_secret", None)

        conn.execute(
            "UPDATE agent_connections SET status = ?, payload = ? "
            "WHERE owner_id = ? AND id = ?",
            (
                "disconnected",
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                owner_id,
                connection_id,
            ),
        )
        self._stamp_runs_of_superseded_connection(
            conn, owner_id=owner_id, connection_id=connection_id, now=now
        )
        self._append_audit_row(
            conn,
            AgentAuditEntryDocument(
                id=f"a2a-supersede-{connection_id}",
                owner_id=owner_id,
                action="wire_superseded",
                outcome="disconnected",
                connection_id=connection_id,
                created_at=now,
            ),
        )

    def _stamp_runs_of_superseded_connection(
        self,
        conn: sqlite3.Connection,
        *,
        owner_id: str,
        connection_id: str,
        now: datetime,
    ) -> None:
        """Stop a superseded connection's live runs from claiming to be live.

        A dispatched, non-terminal run on a connection BrainBuddy can no longer
        reach will never receive another observation. Left alone it would sit at
        "running" forever, which is the exact false claim the honesty rules
        exist to prevent. Stamping it lets the surfaces say the connection was
        disconnected while keeping the bounded history the user already has.
        """

        rows = conn.execute(
            "SELECT id, payload FROM agent_runs "
            "WHERE owner_id = ? AND connection_id = ? AND dispatched_at IS NOT NULL",
            (owner_id, connection_id),
        ).fetchall()
        for row in rows:
            payload = _decoded_payload(row["payload"])
            if payload is None:
                continue
            if payload.get("reported_state") in TERMINAL_REPORTED_STATES:
                continue
            if payload.get("connection_disconnected_at"):
                continue
            payload["connection_disconnected_at"] = now.isoformat()
            payload["next_observation_at"] = None
            payload["updated_at"] = now.isoformat()
            conn.execute(
                "UPDATE agent_runs SET payload = ?, next_observation_at = NULL "
                "WHERE owner_id = ? AND id = ?",
                (
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    owner_id,
                    str(row["id"]),
                ),
            )

    def _append_audit_row(
        self, conn: sqlite3.Connection, entry: AgentAuditEntryDocument
    ) -> None:
        """Write one audit row on a caller-owned connection.

        ``INSERT OR REPLACE`` with a deterministic id keeps the rewrite
        idempotent: a re-run writes the same row rather than a second one.
        """

        conn.execute(
            "INSERT OR REPLACE INTO agent_audit (owner_id, id, created_at, payload) "
            "VALUES (?, ?, ?, ?)",
            (
                entry.owner_id,
                entry.id,
                entry.created_at.isoformat(),
                self._payload(entry),
            ),
        )

    def migration_rewrite_count(self, name: str) -> int | None:
        """How many rows a ledgered migration rewrote, or ``None`` if unrun."""

        with self._connection() as conn:
            row = conn.execute(
                "SELECT rewritten_rows FROM agent_schema_migrations WHERE name = ?",
                (name,),
            ).fetchone()
        return None if row is None else row["rewritten_rows"]

    def _migration_boundary(self, stage: str) -> None:
        """Deterministic interleaving/failure-injection seam for atomicity tests."""

    @staticmethod
    def _quarantine_record(
        owner_id: str, connection_id: str
    ) -> AgentConnectionDocument:
        """The secret-free record an unreadable legacy row is replaced with.

        Deliberately a pure function of the row's coordinates: two startups that
        both decide to quarantine the same row write byte-identical payloads, so
        a redundant repair is invisible rather than a spurious change.
        """

        quarantine_time = datetime(1970, 1, 1, tzinfo=UTC)
        return AgentConnectionDocument(
            id=connection_id,
            owner_id=owner_id,
            name="Connection requires reconfiguration",
            endpoint_url="https://reconfigure.invalid/",
            status="untested",
            last_test_error_code="legacy_invalid_connection_requires_reconfiguration",
            created_at=quarantine_time,
            updated_at=quarantine_time,
        )

    @staticmethod
    def _migrate_legacy_invalid_header_connections(
        conn: sqlite3.Connection,
    ) -> None:
        """Repair legacy header-only failures without consuming corrupt rows."""

        rows = conn.execute(
            "SELECT owner_id, id, payload FROM agent_connections"
        ).fetchall()
        for row in rows:
            payload = _decoded_payload(row["payload"])
            if payload is None:
                continue
            if "auth_header_name" not in payload:
                # A bearer connection under the A2A wire stores no header name at
                # all (data-model.md §1). Absence is the healthy shape, not the
                # legacy failure this repair exists for — treating it as one
                # would reset every 014 bearer connection on every startup.
                continue
            raw_header = payload.get("auth_header_name")
            if isinstance(raw_header, str):
                try:
                    validate_auth_header_name(raw_header)
                except ValueError:
                    pass
                else:
                    continue
            legacy_revision = _bumped_revision(payload)
            payload.pop("auth_header_name", None)
            payload.update(
                credential=None,
                capabilities={"streaming": False, "push_notifications": False},
                status="untested",
                last_test_error_code=(
                    "legacy_invalid_auth_header_requires_reconfiguration"
                ),
                last_contact_at=None,
                last_tested_at=None,
                scope_verified_at=None,
                first_dispatch_at=None,
                revision=legacy_revision,
                updated_at=datetime.now(UTC).isoformat(),
            )
            conn.execute(
                "UPDATE agent_connections SET status = ?, payload = ? "
                "WHERE owner_id = ? AND id = ?",
                (
                    "untested",
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    row["owner_id"],
                    row["id"],
                ),
            )

    def _migrate_legacy_invalid_connections(self, conn: sqlite3.Connection) -> None:
        """Replace unreadable legacy rows with a secret-free remediation record.

        Discovery, the quarantine verdict, and the write all happen inside one
        ``BEGIN IMMEDIATE``. Reading first and writing second would leave a
        window in which another startup repairs or replaces a row: this one
        would still be holding the verdict it formed against the payload that
        row *used* to have, and would overwrite a healthy connection with a
        quarantine stub. Taking the write lock before the SELECT makes the
        snapshot the migration reasons about the same one it mutates.

        Nothing survives a failure: the transaction rolls back whole, so a
        startup that dies mid-scan leaves the legacy rows exactly as they were.
        Re-running is safe and reaches the same verdict, because the scan
        re-reads under its own lock and the quarantine record is deterministic.
        """

        self._migration_boundary("before_transaction")
        conn.execute("BEGIN IMMEDIATE")
        try:
            self._migrate_legacy_invalid_header_connections(conn)
            rows = conn.execute(
                "SELECT owner_id, id, payload FROM agent_connections"
            ).fetchall()
            for row in rows:
                try:
                    AgentConnectionDocument.model_validate(json.loads(row["payload"]))
                except (TypeError, ValueError):
                    pass
                else:
                    continue
                quarantine = self._quarantine_record(
                    str(row["owner_id"]), str(row["id"])
                )
                conn.execute(
                    "UPDATE agent_connections SET status = ?, payload = ? "
                    "WHERE owner_id = ? AND id = ?",
                    (
                        quarantine.status,
                        self._connection_payload(quarantine),
                        row["owner_id"],
                        row["id"],
                    ),
                )
                self._migration_boundary("quarantined")
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

    @staticmethod
    def _payload(model: BaseModel) -> str:
        return json.dumps(
            model.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    def _model(row: sqlite3.Row, model_cls: type[ModelT]) -> ModelT:
        try:
            return model_cls.model_validate(json.loads(row["payload"]))
        except (TypeError, ValueError) as exc:  # pragma: no cover - corrupt row
            raise RepositoryError("Invalid agent-relay payload") from exc

    # --- connections --------------------------------------------------------

    def create_connection(self, connection: AgentConnectionDocument) -> None:
        with (
            self._connection() as conn,
            _sqlite_guard("Agent connection", connection.id),
        ):
            existing = conn.execute(
                "SELECT 1 FROM agent_connections WHERE owner_id = ? AND id = ?",
                (connection.owner_id, connection.id),
            ).fetchone()
            if existing is not None:
                raise ConflictError("Agent connection", connection.id)
            self._upsert_connection(conn, connection)

    def save_connection(self, connection: AgentConnectionDocument) -> None:
        with (
            self._connection() as conn,
            _sqlite_guard("Agent connection", connection.id),
        ):
            self._upsert_connection(conn, connection)

    def _connection_payload(self, connection: AgentConnectionDocument) -> str:
        """Serialize a connection, refusing anything its own type forbids.

        ``model_copy(update=...)`` and ``model_construct`` are how ordinary
        service code builds a revised document, and neither re-runs the field
        validators — so an ``endpoint_url`` carrying a query string can reach
        this layer even though ``AgentConnectionDocument`` rejects one. Storage
        is the last boundary before that URL becomes a row and, through
        ``export_owner_data``, a line in a GDPR export, so the exact JSON about
        to be written is re-validated rather than trusted. Validating the
        serialized bytes rather than the object means what is checked is
        precisely what would be stored.
        """

        payload = self._payload(connection)
        try:
            AgentConnectionDocument.model_validate(json.loads(payload))
        except ValidationError:
            pass
        else:
            return payload
        # Raised clear of the handler on purpose. A pydantic error quotes the
        # value it rejected, and the value here is the thing being kept out of
        # storage; chaining it would put the query secret in the traceback of an
        # exception that is allowed to be logged.
        raise RepositoryError("Agent connection is not persistable.")

    def _upsert_connection(
        self, conn: sqlite3.Connection, connection: AgentConnectionDocument
    ) -> None:
        payload = self._connection_payload(connection)
        conn.execute(
            """
            INSERT INTO agent_connections (owner_id, id, status, created_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET
                status = excluded.status,
                payload = excluded.payload
            """,
            (
                connection.owner_id,
                connection.id,
                connection.status,
                connection.created_at.isoformat(),
                payload,
            ),
        )

    def get_connection(
        self, connection_id: str, *, owner_id: str
    ) -> AgentConnectionDocument:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM agent_connections WHERE owner_id = ? AND id = ?",
                (owner_id, connection_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Agent connection", connection_id)
        return self._model(row, AgentConnectionDocument)

    def list_connections(self, *, owner_id: str) -> list[AgentConnectionDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_connections
                WHERE owner_id = ? ORDER BY created_at ASC, id ASC
                """,
                (owner_id,),
            ).fetchall()
        return [self._model(row, AgentConnectionDocument) for row in rows]

    # --- runs ---------------------------------------------------------------

    def create_run(self, run: AgentRunDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Agent run", run.id):
            existing = conn.execute(
                "SELECT 1 FROM agent_runs WHERE owner_id = ? AND id = ?",
                (run.owner_id, run.id),
            ).fetchone()
            if existing is not None:
                raise ConflictError("Agent run", run.id)
            self._upsert_run(conn, run)

    def save_run(self, run: AgentRunDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Agent run", run.id):
            self._upsert_run(conn, run)

    def _upsert_run(self, conn: sqlite3.Connection, run: AgentRunDocument) -> None:
        conn.execute(
            """
            INSERT INTO agent_runs
                (owner_id, id, connection_id, task_id, created_at, dispatched_at,
                 manifest_token, content_expires_at, content_expired,
                 agent_task_id, context_id, next_observation_at, exchange_state,
                 identifiers_expire_at, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET
                dispatched_at = excluded.dispatched_at,
                manifest_token = excluded.manifest_token,
                content_expires_at = excluded.content_expires_at,
                content_expired = excluded.content_expired,
                agent_task_id = excluded.agent_task_id,
                context_id = excluded.context_id,
                next_observation_at = excluded.next_observation_at,
                exchange_state = excluded.exchange_state,
                identifiers_expire_at = excluded.identifiers_expire_at,
                payload = excluded.payload
            """,
            (
                run.owner_id,
                run.id,
                run.connection_id,
                run.task_id,
                run.created_at.isoformat(),
                run.dispatched_at.isoformat() if run.dispatched_at else None,
                run.manifest.token if run.manifest else None,
                run.content_expires_at.isoformat(),
                int(run.content_expired),
                *self._a2a_run_columns(run),
                self._payload(run),
            ),
        )

    @staticmethod
    def _a2a_run_columns(run: AgentRunDocument) -> tuple[str | None, ...]:
        """The five payload values the scheduler must read without parsing JSON.

        Mirrored out of the payload rather than owned by the columns: the
        document stays the single source of truth, and a column is only ever a
        projection of it, so a row can never disagree with itself about what the
        run is.
        """

        return (
            run.agent_task_id,
            run.context_id,
            run.next_observation_at.isoformat() if run.next_observation_at else None,
            run.exchange_state,
            (
                run.identifiers_expire_at.isoformat()
                if run.identifiers_expire_at
                else None
            ),
        )

    def update_run_if_version(
        self, run: AgentRunDocument, *, expected_version: int
    ) -> bool:
        """Write a run only if nothing moved under the worker that read it.

        Two properties, both of which a plain ``save_run`` would lose.

        **Compare-and-set.** An observer worker reads the run, spends seconds or
        minutes on a network call, and applies the answer afterwards. Without
        ``run_version`` in the ``WHERE`` clause a slow observation returning
        after a fast one would overwrite newer truth with older — the run would
        appear to move backwards, which reads to the user as the agent having
        un-completed their work.

        **No resurrection.** This is an ``UPDATE``, never an upsert, so it can
        only change a row that is still there. A worker that started before an
        account purge finishes after it and writes nothing, rather than
        re-creating a row the user asked to be erased (FR-016).

        Returns whether the write applied.
        """

        with self._connection() as conn, _sqlite_guard("Agent run", run.id):
            cursor = conn.execute(
                """
                UPDATE agent_runs SET
                    dispatched_at = ?,
                    manifest_token = ?,
                    content_expires_at = ?,
                    content_expired = ?,
                    agent_task_id = ?,
                    context_id = ?,
                    next_observation_at = ?,
                    exchange_state = ?,
                    identifiers_expire_at = ?,
                    payload = ?
                WHERE owner_id = ? AND id = ?
                  AND json_extract(payload, '$.run_version') = ?
                """,
                (
                    run.dispatched_at.isoformat() if run.dispatched_at else None,
                    run.manifest.token if run.manifest else None,
                    run.content_expires_at.isoformat(),
                    int(run.content_expired),
                    *self._a2a_run_columns(run),
                    self._payload(run),
                    run.owner_id,
                    run.id,
                    expected_version,
                ),
            )
            return cursor.rowcount == 1

    def due_observations(
        self, *, now: datetime, limit: int = DUE_OBSERVATION_BATCH
    ) -> list[tuple[str, str]]:
        """Owner/run pairs whose next scheduled observation has come due.

        One pass, every owner: the observer is a process-wide scheduler, not a
        per-request path, so filtering by owner here would mean one query per
        owner and a queue whose head could starve the tail.

        The three exclusions are the honesty rules in SQL. A terminal run has
        nothing left to observe; a disconnected one has no credential to ask
        with; an undispatched one was never handed over. Each of them is
        *supposed* to carry ``next_observation_at = NULL`` already, so these
        conditions are the second lock: a row that missed the invariant costs a
        skipped candidate here instead of an endless poll against an agent that
        has nothing to say.
        """

        with self._connection() as conn:
            rows = conn.execute(
                f"""
                SELECT owner_id, id FROM agent_runs
                WHERE next_observation_at IS NOT NULL
                  AND next_observation_at <= ?
                  AND dispatched_at IS NOT NULL
                  AND json_extract(payload, '$.connection_disconnected_at') IS NULL
                  AND (
                      json_extract(payload, '$.reported_state') IS NULL
                      OR json_extract(payload, '$.reported_state')
                         NOT IN ({_TERMINAL_PLACEHOLDERS})
                  )
                ORDER BY next_observation_at ASC, id ASC
                LIMIT ?
                """,  # noqa: S608 - placeholders only, from a module constant
                (now.isoformat(), *_TERMINAL_STATES, limit),
            ).fetchall()
        return [(str(row["owner_id"]), str(row["id"])) for row in rows]

    def start_exchange(
        self,
        run: AgentRunDocument,
        *,
        expected_version: int,
        started_at: datetime,
        deadline_at: datetime,
        from_states: tuple[str, ...] = ("queued",),
    ) -> AgentRunDocument | None:
        """Move one exchange `queued → open`, and spend the first-dispatch trigger.

        Two writes that must not come apart, so they share a transaction.

        The run's `exchange_started_at` is what makes **Queued** and **Sent**
        different claims, and the connection's `first_dispatch_at` is the spent
        marker of FR-004's re-authentication trigger. Both mean the same thing —
        *content has now left BrainBuddy for this destination* — so stamping one
        without the other would let a queued hand-off that never went out either
        render as sent or skip the password on its retry.

        Compare-and-set on `run_version`, so a second worker, a replayed
        confirmation and the observer's recovery cannot each open the same
        exchange. Returns the started run, or `None` when someone else won.

        ``from_states`` widens the same transition for **Check again**: a resend
        opens an exchange that a restart interrupted, or one that closed without
        evidence, and it has to win the same single-writer race a first send
        does.
        """

        opened = run.model_copy(
            update={
                "exchange_state": "open",
                "exchange_started_at": started_at,
                "exchange_deadline_at": deadline_at,
                "updated_at": max(run.updated_at, started_at),
                "revision": run.revision + 1,
            }
        )
        with self._connection() as conn, _sqlite_guard("Agent run", run.id):
            cursor = conn.execute(
                """
                UPDATE agent_runs SET
                    dispatched_at = ?,
                    manifest_token = ?,
                    content_expires_at = ?,
                    content_expired = ?,
                    agent_task_id = ?,
                    context_id = ?,
                    next_observation_at = ?,
                    exchange_state = ?,
                    identifiers_expire_at = ?,
                    payload = ?
                WHERE owner_id = ? AND id = ?
                  AND json_extract(payload, '$.run_version') = ?
                  AND exchange_state IN ({states})
                """.format(states=",".join("?" * len(from_states))),
                (
                    opened.dispatched_at.isoformat() if opened.dispatched_at else None,
                    opened.manifest.token if opened.manifest else None,
                    opened.content_expires_at.isoformat(),
                    int(opened.content_expired),
                    *self._a2a_run_columns(opened),
                    self._payload(opened),
                    opened.owner_id,
                    opened.id,
                    expected_version,
                    *from_states,
                ),
            )
            if cursor.rowcount != 1:
                return None
            row = conn.execute(
                "SELECT payload FROM agent_connections WHERE owner_id = ? AND id = ?",
                (opened.owner_id, opened.connection_id),
            ).fetchone()
            payload = _decoded_payload(row["payload"]) if row is not None else None
            if payload is not None and payload.get("first_dispatch_at") is None:
                payload["first_dispatch_at"] = started_at.isoformat()
                payload["updated_at"] = started_at.isoformat()
                payload["revision"] = _bumped_revision(payload)
                conn.execute(
                    "UPDATE agent_connections SET payload = ? "
                    "WHERE owner_id = ? AND id = ?",
                    (
                        json.dumps(payload, sort_keys=True, separators=(",", ":")),
                        opened.owner_id,
                        opened.connection_id,
                    ),
                )
        return opened

    def acknowledge_duplicate_risk(
        self, connection_id: str, *, owner_id: str, at: datetime
    ) -> None:
        """Stamp the one-time best-effort acknowledgement, once.

        Under the caller's `command_lock`, and conditional on the stamp still
        being absent, so two confirmations racing on one connection record the
        first acknowledgement rather than the later one (AC-026).
        """

        with (
            self._connection() as conn,
            _sqlite_guard("Agent connection", connection_id),
        ):
            row = conn.execute(
                "SELECT payload FROM agent_connections WHERE owner_id = ? AND id = ?",
                (owner_id, connection_id),
            ).fetchone()
            payload = _decoded_payload(row["payload"]) if row is not None else None
            if (
                payload is None
                or payload.get("best_effort_acknowledged_at") is not None
            ):
                return
            payload["best_effort_acknowledged_at"] = at.isoformat()
            payload["updated_at"] = at.isoformat()
            payload["revision"] = _bumped_revision(payload)
            conn.execute(
                "UPDATE agent_connections SET payload = ? WHERE owner_id = ? AND id = ?",
                (
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    owner_id,
                    connection_id,
                ),
            )

    def queued_exchanges(self) -> list[tuple[str, str, str]]:
        """Every exchange still waiting for a worker: owner, run, connection.

        Ordered oldest first so a drain is fair within an owner; fairness
        *across* owners is the caller's business, because only it knows which
        connections already hold workers.
        """

        with self._connection() as conn:
            rows = conn.execute("""
                SELECT owner_id, id, connection_id FROM agent_runs
                WHERE exchange_state = 'queued'
                ORDER BY created_at ASC, id ASC
                """).fetchall()
        return [
            (str(row["owner_id"]), str(row["id"]), str(row["connection_id"]))
            for row in rows
        ]

    def open_exchange_count(self, connection_id: str, *, owner_id: str) -> int:
        """How many exchanges this connection is holding open right now.

        The bound that stops one hostile or broken agent from consuming the
        shared pool for every owner. Counted from the durable rows rather than
        from an in-process tally, so a restart cannot lose track of it.
        """

        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS held FROM agent_runs "
                "WHERE owner_id = ? AND connection_id = ? AND exchange_state = 'open'",
                (owner_id, connection_id),
            ).fetchone()
        return int(row["held"]) if row is not None else 0

    def interrupted_exchanges(self) -> list[tuple[str, str, str]]:
        """Every exchange a restart left mid-flight: owner, run, state.

        One pass over every owner, at boot, before any request is served. A
        queued exchange and an open one need opposite treatment — one provably
        never left, the other may already be at the agent — so the state comes
        back with the row rather than being guessed from it (AC-032).
        """

        with self._connection() as conn:
            rows = conn.execute("""
                SELECT owner_id, id, exchange_state FROM agent_runs
                WHERE exchange_state IN ('queued', 'open')
                ORDER BY created_at ASC, id ASC
                """).fetchall()
        return [
            (str(row["owner_id"]), str(row["id"]), str(row["exchange_state"]))
            for row in rows
        ]

    def find_run_by_manifest_token(
        self, token: str, *, owner_id: str
    ) -> AgentRunDocument | None:
        """Resolve the reservation a confirmation names, if it still exists."""

        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT payload FROM agent_runs
                WHERE owner_id = ? AND manifest_token = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (owner_id, token),
            ).fetchone()
        return None if row is None else self._model(row, AgentRunDocument)

    def find_connection_anywhere(
        self, connection_id: str
    ) -> AgentConnectionDocument | None:
        """Look a connection up without an owner, for inbound event routing.

        Inbound events arrive unauthenticated as a user; the connection is what
        identifies the owner, and the signature is what proves the caller may
        act as it. Every downstream read is then re-scoped to that owner.
        """

        with self._connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM agent_connections WHERE id = ? LIMIT 2",
                (connection_id,),
            ).fetchall()
        if len(rows) != 1:
            return None
        return self._model(rows[0], AgentConnectionDocument)

    def prune_undispatched_runs(self, *, before: datetime) -> int:
        """Drop abandoned review reservations so they cannot accumulate."""

        with self._connection() as conn, _sqlite_guard("Agent run", "reservations"):
            cursor = conn.execute(
                """
                DELETE FROM agent_runs
                WHERE dispatched_at IS NULL AND created_at < ?
                """,
                (before.isoformat(),),
            )
            return int(cursor.rowcount or 0)

    def owner_of_run(self, run_id: str) -> str | None:
        """Who owns this run, without a session to say so.

        The one place a run is looked up without an owner, and it exists for
        exactly two callers with no session between them: the push callback,
        which is called by the agent, and the observer's wake queue. It answers
        with an owner id and nothing else, so a caller that guesses a run id
        learns only what it already guessed.
        """

        with self._connection() as conn:
            row = conn.execute(
                "SELECT owner_id FROM agent_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return None if row is None else str(row["owner_id"])

    def get_run(self, run_id: str, *, owner_id: str) -> AgentRunDocument:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM agent_runs WHERE owner_id = ? AND id = ?",
                (owner_id, run_id),
            ).fetchone()
        if row is None:
            raise NotFoundError("Agent run", run_id)
        return self._model(row, AgentRunDocument)

    def list_runs_for_task(
        self, task_id: str, *, owner_id: str
    ) -> list[AgentRunDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_runs
                WHERE owner_id = ? AND task_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (owner_id, task_id),
            ).fetchall()
        return [self._model(row, AgentRunDocument) for row in rows]

    def list_runs_for_owner(self, *, owner_id: str) -> list[AgentRunDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_runs
                WHERE owner_id = ? ORDER BY created_at DESC, id DESC
                """,
                (owner_id,),
            ).fetchall()
        return [self._model(row, AgentRunDocument) for row in rows]

    def latest_runs_by_task(
        self, *, owner_id: str, task_ids: Sequence[str]
    ) -> dict[str, AgentRunDocument]:
        """The newest run per task, for the compact Task surface (FR-010)."""

        unique = list(dict.fromkeys(task_ids))
        if not unique:
            return {}
        latest: dict[str, AgentRunDocument] = {}
        with self._connection() as conn:
            for task_id in unique:
                row = conn.execute(
                    """
                    SELECT task_id, payload FROM agent_runs
                    WHERE owner_id = ? AND dispatched_at IS NOT NULL
                        AND task_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (owner_id, task_id),
                ).fetchone()
                if row is not None:
                    latest[row["task_id"]] = self._model(row, AgentRunDocument)
        return latest

    # --- events -------------------------------------------------------------

    def append_event(self, event: AgentRunEventDocument) -> None:
        with (
            self._content_insert_transaction(event.owner_id) as conn,
            _sqlite_guard("Agent event", event.id),
        ):
            event = event.model_copy(
                update={
                    "summary": self._retained_content(
                        conn, event.owner_id, event.run_id, event.summary
                    )
                }
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_run_events
                    (owner_id, id, run_id, run_version, received_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.owner_id,
                    event.id,
                    event.run_id,
                    event.run_version,
                    event.received_at.isoformat(),
                    self._payload(event),
                ),
            )

    def list_events(self, run_id: str, *, owner_id: str) -> list[AgentRunEventDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_run_events
                WHERE owner_id = ? AND run_id = ?
                ORDER BY run_version ASC, received_at ASC, id ASC
                """,
                (owner_id, run_id),
            ).fetchall()
        return [self._model(row, AgentRunEventDocument) for row in rows]

    # --- commands -----------------------------------------------------------

    def save_command(self, command: AgentRunCommandDocument) -> None:
        with (
            self._content_insert_transaction(command.owner_id) as conn,
            _sqlite_guard("Agent command", command.id),
        ):
            command = command.model_copy(
                update={
                    "body": self._retained_content(
                        conn, command.owner_id, command.run_id, command.body
                    )
                }
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_run_commands
                    (owner_id, id, run_id, created_at, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    command.owner_id,
                    command.id,
                    command.run_id,
                    command.created_at.isoformat(),
                    self._payload(command),
                ),
            )

    def get_command(
        self, command_id: str, *, owner_id: str
    ) -> AgentRunCommandDocument | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM agent_run_commands WHERE owner_id = ? AND id = ?",
                (owner_id, command_id),
            ).fetchone()
        return None if row is None else self._model(row, AgentRunCommandDocument)

    def list_commands(
        self, run_id: str, *, owner_id: str
    ) -> list[AgentRunCommandDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_run_commands
                WHERE owner_id = ? AND run_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (owner_id, run_id),
            ).fetchall()
        return [self._model(row, AgentRunCommandDocument) for row in rows]

    @contextmanager
    def _content_insert_transaction(
        self, owner_id: str
    ) -> Iterator[sqlite3.Connection]:
        """Serialize a child-content insert with retention's expiry transaction."""

        active = getattr(self._thread_state, "conn", None)
        if active is not None:
            yield active
            return
        with self._process_lock, self._owned_connection() as conn:
            try:
                with _sqlite_guard("Agent content", owner_id):
                    conn.execute("BEGIN IMMEDIATE")
                    yield conn
                    conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def _retained_content(
        conn: sqlite3.Connection,
        owner_id: str,
        run_id: str,
        content: str | None,
    ) -> str | None:
        row = conn.execute(
            "SELECT content_expired FROM agent_runs WHERE owner_id = ? AND id = ?",
            (owner_id, run_id),
        ).fetchone()
        if row is not None and bool(row["content_expired"]):
            return None
        return content

    # --- audit --------------------------------------------------------------

    def append_audit(self, entry: AgentAuditEntryDocument) -> None:
        with self._connection() as conn, _sqlite_guard("Agent audit", entry.id):
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_audit (owner_id, id, created_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    entry.owner_id,
                    entry.id,
                    entry.created_at.isoformat(),
                    self._payload(entry),
                ),
            )

    def append_bounded_audit(
        self, entry: AgentAuditEntryDocument, *, bucket: str, day: str
    ) -> bool:
        """Write one audit row per (owner, action, bucket, UTC day), or none.

        The observer polls every sixty seconds and a hostile caller can post to
        the push route as fast as the limiter allows, so an unbounded audit row
        per event is a retention problem wearing an accountability costume: it
        would grow without bound, and the ninetieth row of a day tells the owner
        nothing the first did not. The deduplication key is a real unique index
        rather than a read-then-write, so two workers racing the same class
        still produce exactly one row.

        Returns whether this call is the one that wrote it.
        """

        with self._connection() as conn, _sqlite_guard("Agent audit", entry.id):
            claimed = conn.execute(
                """
                INSERT OR IGNORE INTO agent_audit_buckets
                    (owner_id, action, bucket, day, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    entry.owner_id,
                    entry.action,
                    bucket,
                    day,
                    entry.created_at.isoformat(),
                ),
            )
            if claimed.rowcount != 1:
                return False
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_audit (owner_id, id, created_at, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    entry.owner_id,
                    entry.id,
                    entry.created_at.isoformat(),
                    self._payload(entry),
                ),
            )
            return True

    def list_audit(self, *, owner_id: str) -> list[AgentAuditEntryDocument]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM agent_audit
                WHERE owner_id = ? ORDER BY created_at DESC, id DESC
                """,
                (owner_id,),
            ).fetchall()
        return [self._model(row, AgentAuditEntryDocument) for row in rows]

    def purge_expired_audit(self, *, now: datetime) -> int:
        cutoff = (now - AUDIT_RETENTION).isoformat()
        with self._connection() as conn, _sqlite_guard("Agent audit", "retention"):
            cursor = conn.execute(
                "DELETE FROM agent_audit WHERE created_at < ?", (cutoff,)
            )
            # The bucket ledger goes with the rows it bounded. Keeping it would
            # make a purged day still suppress a new row for the same class,
            # which is the one way this table could cost an owner evidence.
            conn.execute(
                "DELETE FROM agent_audit_buckets WHERE created_at < ?", (cutoff,)
            )
            return int(cursor.rowcount or 0)

    def export_owner_data(
        self, *, owner_id: str, now: datetime
    ) -> dict[str, list[dict[str, Any]]]:
        """Return portable owner content without relay secrets or replay receipts."""

        # A sealed credential is useless without the key ring, but a
        # *fingerprint* is a verifier: anyone holding the export and a candidate
        # token could confirm a match. None of them is content the user asked
        # for, so none of them travels (data-model §8, SC-007).
        connection_excludes = {"credential", "inbound_secret", "card_fingerprint"}
        run_excludes = {"push_token_fingerprint", "card_fingerprint"}
        with self._connection() as conn:
            connection_rows = conn.execute(
                "SELECT payload FROM agent_connections WHERE owner_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (owner_id,),
            ).fetchall()
            run_rows = conn.execute(
                "SELECT payload FROM agent_runs WHERE owner_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (owner_id,),
            ).fetchall()
            event_rows = conn.execute(
                "SELECT payload FROM agent_run_events WHERE owner_id = ? "
                "ORDER BY received_at ASC, id ASC",
                (owner_id,),
            ).fetchall()
            command_rows = conn.execute(
                "SELECT payload FROM agent_run_commands WHERE owner_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (owner_id,),
            ).fetchall()
            audit_rows = conn.execute(
                "SELECT payload FROM agent_audit WHERE owner_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (owner_id,),
            ).fetchall()

        runs = [self._model(row, AgentRunDocument) for row in run_rows]
        redacted_run_ids = {
            run.id
            for run in runs
            if run.content_expired or run.content_expires_at <= now
        }
        projected_runs = [project_run_for_access(run, now=now) for run in runs]
        events = [self._model(row, AgentRunEventDocument) for row in event_rows]
        commands = [self._model(row, AgentRunCommandDocument) for row in command_rows]
        audit_cutoff = now - AUDIT_RETENTION

        return {
            "connections": [
                self._model(row, AgentConnectionDocument).model_dump(
                    mode="json", exclude=connection_excludes
                )
                for row in connection_rows
            ],
            "runs": [
                run.model_dump(mode="json", exclude=run_excludes)
                for run in projected_runs
            ],
            "events": [
                (
                    event.model_copy(update={"summary": None})
                    if event.run_id in redacted_run_ids
                    else event
                ).model_dump(mode="json")
                for event in events
            ],
            "commands": [
                (
                    command.model_copy(update={"body": None})
                    if command.run_id in redacted_run_ids
                    else command
                ).model_dump(mode="json")
                for command in commands
            ],
            "audit": [
                entry.model_dump(mode="json")
                for row in audit_rows
                if (entry := self._model(row, AgentAuditEntryDocument)).created_at
                > audit_cutoff
            ],
        }

    # --- retention ----------------------------------------------------------

    def _retention_mutation_boundary(self, boundary: str) -> None:
        """Deterministic failure-injection seam for atomicity tests."""

    def expire_due_content(self, *, now: datetime) -> int:
        """Atomically erase expired run, event, and command content.

        The selection predicate re-derives from the content columns themselves
        rather than trusting ``content_expired``: a value written after an
        expiry — by a late observation, or by a pass that was interrupted — is
        picked up on the next run instead of surviving because a flag already
        claims it is gone.

        A row whose payload cannot be parsed is skipped and logged rather than
        aborting the transaction. Aborting would make one broken row a
        permanent retention failure for every other owner on the instance,
        which is both the worst outcome available here and the hardest to
        notice.
        """

        stamp = now.isoformat()
        with self._process_lock, self._owned_connection() as conn:
            try:
                with _sqlite_guard("Agent run", "retention"):
                    conn.execute("BEGIN IMMEDIATE")
                    rows = conn.execute(
                        _DUE_CONTENT_QUERY,  # noqa: S608 - built from constants
                        (stamp,),
                    ).fetchall()
                    if not rows:
                        conn.commit()
                        return 0
                    expired = 0
                    for row in rows:
                        run = self._parsed_run_or_skipped(row)
                        if run is None:
                            continue
                        if not run.content_expired or self._holds_content(run):
                            redacted = run.model_copy(
                                update={
                                    **dict.fromkeys(CONTENT_TIER_RUN_FIELDS),
                                    "artifacts_summary": [],
                                    "content_expired": True,
                                    "updated_at": now,
                                    "revision": run.revision + 1,
                                }
                            )
                            self._upsert_run(conn, redacted)
                            self._retention_mutation_boundary("run")
                            expired += 1

                        event_rows = conn.execute(
                            """
                            SELECT payload FROM agent_run_events
                            WHERE owner_id = ? AND run_id = ?
                            """,
                            (run.owner_id, run.id),
                        ).fetchall()
                        for event_row in event_rows:
                            event = self._model(event_row, AgentRunEventDocument)
                            if event.summary is None:
                                continue
                            conn.execute(
                                """
                                UPDATE agent_run_events SET payload = ?
                                WHERE owner_id = ? AND run_id = ? AND id = ?
                                """,
                                (
                                    self._payload(
                                        event.model_copy(update={"summary": None})
                                    ),
                                    run.owner_id,
                                    run.id,
                                    event.id,
                                ),
                            )
                            self._retention_mutation_boundary("event")

                        command_rows = conn.execute(
                            """
                            SELECT payload FROM agent_run_commands
                            WHERE owner_id = ? AND run_id = ?
                            """,
                            (run.owner_id, run.id),
                        ).fetchall()
                        for command_row in command_rows:
                            command = self._model(command_row, AgentRunCommandDocument)
                            if command.body is None:
                                continue
                            conn.execute(
                                """
                                UPDATE agent_run_commands SET payload = ?
                                WHERE owner_id = ? AND run_id = ? AND id = ?
                                """,
                                (
                                    self._payload(
                                        command.model_copy(update={"body": None})
                                    ),
                                    run.owner_id,
                                    run.id,
                                    command.id,
                                ),
                            )
                            self._retention_mutation_boundary("command")
                    conn.commit()
                    return expired
            except BaseException:
                conn.rollback()
                raise

    def _parsed_run_or_skipped(self, row: sqlite3.Row) -> AgentRunDocument | None:
        """One run document, or ``None`` with a coarse warning.

        The sweep must never abort on a row it cannot read: one unparseable
        payload would otherwise become a permanent retention failure for every
        other owner on the instance. The log line names the ids and the
        correlation id and carries no content — a retention failure that leaked
        the very text it failed to erase would be the worst possible version of
        this bug.
        """

        try:
            return self._model(row, AgentRunDocument)
        except (ValidationError, RepositoryError):
            logger.warning(
                "agent_retention_skipped_unparseable_row owner_id=%s run_id=%s "
                "correlation_id=%s",
                row["owner_id"],
                row["id"],
                get_correlation_id(),
            )
            return None

    @staticmethod
    def _holds_content(run: AgentRunDocument) -> bool:
        """Whether an already-expired run still has content to erase."""

        return bool(run.artifacts_summary) or any(
            getattr(run, field) is not None for field in CONTENT_TIER_RUN_FIELDS
        )

    def expire_due_identifier_runs(self, *, now: datetime) -> list[tuple[str, str]]:
        """The runs this pass expired, as (run id, owner id).

        Returned rather than counted so the caller can write one audit row per
        run: "the identifiers were erased" is a fact about a *run*, and an
        aggregate would leave the owner's trail unable to say which.
        """

        return self._expire_due_identifiers(now=now)

    def expire_due_identifiers(self, *, now: datetime) -> int:
        """Null the identifiers an agent could still act on, and drop the events.

        Ninety days from dispatch, and deliberately *not* the run id: the
        conversation identifier is the run's own id, it is embedded in a
        callback URL the agent keeps and in a row no sweep deletes, so nulling
        it here would erase nothing anyone holds while implying it had. The run
        row and its id stay until the account is purged, and
        `docs/data-retention.md` says exactly that.
        """

        return len(self._expire_due_identifiers(now=now))

    def _expire_due_identifiers(self, *, now: datetime) -> list[tuple[str, str]]:
        cutoff = (now - IDENTIFIER_RETENTION).isoformat()
        expired: list[tuple[str, str]] = []
        with self._process_lock, self._owned_connection() as conn:
            try:
                with _sqlite_guard("Agent run", "retention"):
                    conn.execute("BEGIN IMMEDIATE")
                    rows = conn.execute(
                        """
                        SELECT owner_id, id, payload FROM agent_runs
                        WHERE dispatched_at IS NOT NULL
                            AND dispatched_at <= ?
                            AND json_extract(payload, '$.identifiers_expired') IS NOT 1
                        """,
                        (cutoff,),
                    ).fetchall()
                    for row in rows:
                        run = self._parsed_run_or_skipped(row)
                        if run is None:
                            continue
                        self._upsert_run(
                            conn,
                            run.model_copy(
                                update={
                                    **dict.fromkeys(IDENTIFIER_TIER_RUN_FIELDS),
                                    "identifiers_expired": True,
                                    "identifiers_expire_at": run.identifiers_expire_at
                                    or now,
                                    # Nothing left to observe with.
                                    "next_observation_at": None,
                                    "updated_at": now,
                                    "revision": run.revision + 1,
                                }
                            ),
                        )
                        conn.execute(
                            "DELETE FROM agent_run_events "
                            "WHERE owner_id = ? AND run_id = ?",
                            (run.owner_id, run.id),
                        )
                        conn.execute(
                            """
                            UPDATE agent_run_commands
                            SET payload = json_set(
                                payload, '$.agent_task_id_after', json('null')
                            )
                            WHERE owner_id = ? AND run_id = ?
                            """,
                            (run.owner_id, run.id),
                        )
                        expired.append((run.id, run.owner_id))
                    conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return expired

    # --- idempotency --------------------------------------------------------

    def get_idempotency(
        self, *, owner_id: str, key_hashes: Sequence[str]
    ) -> AgentIdempotencyRecord | None:
        """Find the record stored under any of ``key_hashes``, newest key first.

        The caller passes one candidate per configured relay key, so a record
        written before a rotation — or written by an instance whose ring differs
        from this one's — is still found while its key remains configured. The
        raw key never reaches this layer at all.
        """

        candidates = list(key_hashes)
        if not candidates:
            return None
        with self._connection() as conn:
            for candidate in candidates:
                row = conn.execute(
                    """
                    SELECT key_hash, command, request_hash, resource_id, command_id,
                           delivery_attempted, completed, response_body, created_at
                    FROM agent_idempotency
                    WHERE owner_id = ? AND key_hash = ?
                    """,
                    (owner_id, candidate),
                ).fetchone()
                if row is not None:
                    return AgentIdempotencyRecord(
                        key_hash=row["key_hash"],
                        command=row["command"],
                        request_hash=row["request_hash"],
                        resource_id=row["resource_id"],
                        command_id=row["command_id"],
                        delivery_attempted=bool(row["delivery_attempted"]),
                        completed=bool(row["completed"]),
                        response_body=json.loads(row["response_body"]),
                        created_at=row["created_at"],
                    )
        return None

    def save_idempotency(
        self, *, owner_id: str, record: AgentIdempotencyRecord
    ) -> None:
        # The guard's identifier is deliberately the resource, not the key or
        # its hash: it can end up in an error message and a log line.
        with (
            self._connection() as conn,
            _sqlite_guard("Idempotency-Key", record.resource_id),
        ):
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_idempotency
                    (owner_id, key_hash, command, request_hash, resource_id,
                     command_id, delivery_attempted, completed, response_body, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_id,
                    record.key_hash,
                    record.command,
                    record.request_hash,
                    record.resource_id,
                    record.command_id,
                    int(record.delivery_attempted),
                    int(record.completed),
                    json.dumps(record.response_body, sort_keys=True),
                    record.created_at.isoformat(),
                ),
            )

    def live_sealed_key_ids(
        self, *, now: datetime, owner_id: str | None = None
    ) -> LiveIdempotencyKeys:
        """Key ids referenced by every live sealed value owned by ``owner_id``.

        Connection credentials live until disconnect, replacement or deletion.
        This reads key labels from stored envelopes; it never opens ciphertext
        or exposes malformed stored values.
        """

        cutoff = (now - IDEMPOTENCY_RETENTION).isoformat()
        with self._connection() as conn:
            if owner_id is None:
                connection_rows = conn.execute(
                    "SELECT payload FROM agent_connections"
                ).fetchall()
                receipt_rows = conn.execute(
                    "SELECT key_hash, response_body FROM agent_idempotency "
                    "WHERE created_at >= ?",
                    (cutoff,),
                ).fetchall()
            else:
                connection_rows = conn.execute(
                    "SELECT payload FROM agent_connections WHERE owner_id = ?",
                    (owner_id,),
                ).fetchall()
                receipt_rows = conn.execute(
                    "SELECT key_hash, response_body FROM agent_idempotency "
                    "WHERE owner_id = ? AND created_at >= ?",
                    (owner_id, cutoff),
                ).fetchall()

        key_ids: set[str] = set()
        unreadable = 0
        for row in connection_rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                unreadable += 1
                continue
            if not isinstance(payload, dict):
                unreadable += 1
                continue
            sealed = payload.get("credential")
            if sealed is not None:
                key_id = key_id_from_sealed(sealed)
                if key_id is None:
                    unreadable += 1
                else:
                    key_ids.add(key_id)

        for row in receipt_rows:
            fingerprint_id = fingerprint_key_id(str(row["key_hash"]))
            if fingerprint_id is None:
                unreadable += 1
            else:
                key_ids.add(fingerprint_id)

        return LiveIdempotencyKeys(frozenset(key_ids), unreadable)

    def live_idempotency_key_ids(
        self, *, owner_id: str, now: datetime
    ) -> LiveIdempotencyKeys:
        """Which relay key ids this owner's unexpired records are stored under.

        A ``key_hash`` is ``<key_id>:<mac>``, and the key id half is a
        configuration label rather than a secret — the same label already sits
        in cleartext on every sealed credential. Reading it back is what lets
        the service notice that a key was retired while records only findable
        under it are still within retention, instead of silently missing them.
        """

        cutoff = (now - IDEMPOTENCY_RETENTION).isoformat()
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT key_hash FROM agent_idempotency "
                "WHERE owner_id = ? AND created_at >= ?",
                (owner_id, cutoff),
            ).fetchall()
        key_ids: set[str] = set()
        unreadable = 0
        for row in rows:
            key_id = fingerprint_key_id(str(row["key_hash"]))
            if key_id is None:
                unreadable += 1
            else:
                key_ids.add(key_id)
        return LiveIdempotencyKeys(frozenset(key_ids), unreadable)

    def purge_expired_idempotency(self, *, owner_id: str, now: datetime) -> int:
        cutoff = (now - IDEMPOTENCY_RETENTION).isoformat()
        with self._connection() as conn, _sqlite_guard("Idempotency-Key", owner_id):
            cursor = conn.execute(
                "DELETE FROM agent_idempotency WHERE owner_id = ? AND created_at < ?",
                (owner_id, cutoff),
            )
            return int(cursor.rowcount or 0)

    def purge_all_expired_idempotency(self, *, now: datetime) -> int:
        """Drop every expired reservation, for every owner.

        The per-owner form only runs when that owner makes a request, so an
        account that goes quiet would keep its rows forever. Retention is a
        promise about the data, not about the traffic, so the sweep is global.
        """

        cutoff = (now - IDEMPOTENCY_RETENTION).isoformat()
        with self._connection() as conn, _sqlite_guard("Idempotency-Key", "retention"):
            cursor = conn.execute(
                "DELETE FROM agent_idempotency WHERE created_at < ?", (cutoff,)
            )
            return int(cursor.rowcount or 0)

    # --- purge --------------------------------------------------------------

    def delete_all_for_owner(self, *, owner_id: str) -> None:
        """Erase every relay record belonging to one owner. Idempotent."""

        with self.command_lock(owner_id), self._connection() as conn:
            conn.execute("DELETE FROM agent_run_events WHERE owner_id = ?", (owner_id,))
            conn.execute(
                "DELETE FROM agent_run_commands WHERE owner_id = ?", (owner_id,)
            )
            conn.execute("DELETE FROM agent_runs WHERE owner_id = ?", (owner_id,))
            conn.execute(
                "DELETE FROM agent_connections WHERE owner_id = ?", (owner_id,)
            )
            conn.execute("DELETE FROM agent_audit WHERE owner_id = ?", (owner_id,))
            conn.execute(
                "DELETE FROM agent_audit_buckets WHERE owner_id = ?", (owner_id,)
            )
            conn.execute(
                "DELETE FROM agent_idempotency WHERE owner_id = ?", (owner_id,)
            )


__all__ = [
    "A2A_WIRE_MIGRATION",
    "AUDIT_RETENTION",
    "DUE_OBSERVATION_BATCH",
    "IDEMPOTENCY_RETENTION",
    "AgentRepository",
]
