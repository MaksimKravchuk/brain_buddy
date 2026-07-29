"""SQLite persistence for AsyncOperation records owned by this workflow.

ADR-0001/0002: the voice Brain Dump operation substrate (records, media,
idempotency) is private to this application-workflow boundary. It is stored
in its own SQLite database (``voice_operations.sqlite3``), separate from
``tasks.sqlite3``, so Tasks never owns operation persistence and neither
module's writer contends with the other's.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from app.exceptions import (
    ConflictError,
    NotFoundError,
    RepositoryError,
    StorageUnavailableError,
)
from app.repositories.base import BaseRepository
from app.utils.time import utcnow

from .domain import (
    BrainDumpOperationDocument,
    BrainDumpProposalPatchDocument,
    IdempotencyRecord,
)

IDEMPOTENCY_RETENTION = timedelta(hours=24)
"""How long replayed command results stay addressable by their key."""

_BRAIN_DUMP_SCHEMA_VERSION = 2
_LEGACY_TERMINAL_STATUSES = frozenset({"completed", "cancelled"})


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
            "Voice operation storage is temporarily unavailable; retry the request."
        ) from exc
    except sqlite3.Error as exc:
        raise RepositoryError(
            f"Voice operation storage failed while writing {resource} '{identifier}'."
        ) from exc


class OperationRepository(BaseRepository):
    """Store voice Brain Dump AsyncOperation records in their own database."""

    _thread_state: threading.local = threading.local()
    _process_lock: threading.RLock = threading.RLock()

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.db_path = self.resolve("voice_operations.sqlite3")
        self._initialize_database()
        self._migrate_legacy_json_once()

    @contextmanager
    def command_lock(self, owner_id: str) -> Iterator[None]:
        """Serialize owner-scoped commands and wrap writes in one transaction."""

        # Owner serialization is global for SQLite's single writer. This lock
        # is private to this repository's own database, so it never contends
        # with TaskRepository.command_lock.
        with self._process_lock:
            conn = self._connect()
            previous = getattr(self._thread_state, "conn", None)
            self._thread_state.conn = conn
            try:
                with _sqlite_guard("Voice operation command", owner_id):
                    conn.execute("BEGIN IMMEDIATE")
                    yield
                    conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                self._thread_state.conn = previous
                conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def _owned_connection(self) -> Iterator[sqlite3.Connection]:
        """Open a private connection and always close it on exit."""

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
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS brain_dump_operations (
                    owner_id TEXT NOT NULL,
                    id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (owner_id, id)
                );
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    owner_id TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    key TEXT NOT NULL,
                    command TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    response_body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (owner_id, key_hash)
                );
                CREATE TABLE IF NOT EXISTS migration_ledger (
                    id TEXT PRIMARY KEY,
                    migrated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_brain_dump_operations_owner_status
                    ON brain_dump_operations(owner_id, status, updated_at, id);
                CREATE INDEX IF NOT EXISTS idx_idempotency_owner_created
                    ON idempotency_records(owner_id, created_at);
                """
            )

    def _migrate_legacy_json_once(self) -> None:
        with self._owned_connection() as conn:
            seen = conn.execute(
                "SELECT 1 FROM migration_ledger WHERE id = ?", ("legacy-json-v1",)
            ).fetchone()
            if seen is not None:
                return
            conn.execute("BEGIN IMMEDIATE")
            try:
                counts = {"brain_dump_operations": 0}
                for path in self.resolve("brain-dump-operations").glob("*/*.json"):
                    operation, _ = self._decode_brain_dump_operation(
                        json.loads(path.read_text(encoding="utf-8"))
                    )
                    self._upsert_brain_dump_operation(conn, operation)
                    counts["brain_dump_operations"] += 1
                conn.execute(
                    "INSERT INTO migration_ledger (id, migrated_at, payload) VALUES (?, ?, ?)",
                    (
                        "legacy-json-v1",
                        utcnow().isoformat(),
                        json.dumps(counts, sort_keys=True),
                    ),
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    # Compatibility path helpers retained for focused legacy tests.
    def brain_dump_operation_path(self, owner_id: str, operation_id: str) -> Path:
        return self.resolve("brain-dump-operations", owner_id, f"{operation_id}.json")

    def brain_dump_audio_chunk_path(
        self, owner_id: str, operation_id: str, chunk_number: int, sha256: str
    ) -> Path:
        return self.resolve(
            "brain-dump-media", owner_id, operation_id, f"{chunk_number:06d}-{sha256}.bin"
        )

    def brain_dump_audio_operation_path(self, owner_id: str, operation_id: str) -> Path:
        return self.resolve("brain-dump-media", owner_id, operation_id)

    def idempotency_path(self, owner_id: str, key: str) -> Path:
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.resolve("voice-operation-commands", owner_id, f"{key_hash}.json")

    @staticmethod
    def _payload(model: BrainDumpOperationDocument) -> str:
        return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _legacy_patch_id(operation_id: str, proposal_id: str, operation: str) -> str:
        digest = hashlib.sha256(
            f"{operation_id}:{proposal_id}:{operation}".encode()
        ).hexdigest()[:24]
        return f"proposal_patch_legacy_{digest}"

    @classmethod
    def _decode_brain_dump_operation(
        cls, payload: dict[str, object]
    ) -> tuple[BrainDumpOperationDocument, bool]:
        """Dispatch persisted operation payloads by explicit schema version."""

        raw_version = payload.get("schema_version", 1)
        if not isinstance(raw_version, int) or isinstance(raw_version, bool):
            raise RepositoryError("Brain dump operation schema version must be an integer.")
        if raw_version not in {1, _BRAIN_DUMP_SCHEMA_VERSION}:
            raise RepositoryError(
                f"Brain dump operation has unsupported schema version {raw_version}."
            )
        if raw_version == _BRAIN_DUMP_SCHEMA_VERSION:
            return BrainDumpOperationDocument.model_validate(payload), False

        legacy = BrainDumpOperationDocument.model_validate(
            {**payload, "schema_version": 1}
        )
        if legacy.status in _LEGACY_TERMINAL_STATUSES:
            return legacy, False

        proposals = []
        patches: list[BrainDumpProposalPatchDocument] = []
        sequence = 0
        for proposal in legacy.proposals:
            locked_fields = list(proposal.locked_fields)
            if proposal.user_edited and "title" not in locked_fields:
                locked_fields.append("title")
            proposals.append(
                proposal.model_copy(
                    update={
                        "locked_fields": locked_fields,
                        "status": (
                            "user_edited" if proposal.user_edited else "provisional"
                        ),
                    }
                )
            )
            sequence += 1
            patches.append(
                BrainDumpProposalPatchDocument(
                    id=cls._legacy_patch_id(legacy.id, proposal.id, "add"),
                    sequence=sequence,
                    operation="add",
                    proposal_id=proposal.id,
                    producer="user",
                    title=proposal.title,
                    source_segment_ids=proposal.source_segment_ids,
                    locked_fields=locked_fields,
                    created_at=legacy.updated_at,
                )
            )
            if proposal.deleted:
                sequence += 1
                patches.append(
                    BrainDumpProposalPatchDocument(
                        id=cls._legacy_patch_id(legacy.id, proposal.id, "remove"),
                        sequence=sequence,
                        operation="remove",
                        proposal_id=proposal.id,
                        producer="user",
                        source_segment_ids=proposal.source_segment_ids,
                        created_at=legacy.updated_at,
                    )
                )

        migrated = legacy.model_copy(
            update={
                "segments": [
                    segment.model_copy(update={"provider_role": "browser_preview"})
                    for segment in legacy.segments
                ],
                "proposals": proposals,
                "provider_runs": [],
                "proposal_patches": patches,
                "reconciliation_quality": "provisional_only",
                "legacy_import": "legacy_preview_only",
                "schema_version": _BRAIN_DUMP_SCHEMA_VERSION,
                "revision": legacy.revision + 1,
            }
        )
        return migrated, True

    def _upsert_brain_dump_operation(
        self, conn: sqlite3.Connection, operation: BrainDumpOperationDocument
    ) -> None:
        conn.execute(
            """
            INSERT INTO brain_dump_operations
                (owner_id, id, status, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(owner_id, id) DO UPDATE SET
                status = excluded.status,
                updated_at = excluded.updated_at,
                payload = excluded.payload
            """,
            (
                operation.owner_id,
                operation.id,
                operation.status,
                operation.updated_at.isoformat(),
                self._payload(operation),
            ),
        )
        BaseRepository.dump_model(
            self.brain_dump_operation_path(operation.owner_id, operation.id), operation
        )

    def save_brain_dump_operation(self, operation: BrainDumpOperationDocument) -> None:
        with (
            self._connection() as conn,
            _sqlite_guard("Brain dump operation", operation.id),
        ):
            self._upsert_brain_dump_operation(conn, operation)

    def save_brain_dump_audio_chunk(
        self, *, owner_id: str, operation_id: str, chunk_number: int, sha256: str, content: bytes
    ) -> None:
        path = self.brain_dump_audio_chunk_path(owner_id, operation_id, chunk_number, sha256)
        path.parent.mkdir(parents=True, exist_ok=True)
        staging_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            staging_path.write_bytes(content)
            os.replace(staging_path, path)
        finally:
            staging_path.unlink(missing_ok=True)

    def load_brain_dump_audio_chunks(
        self, *, owner_id: str, operation_id: str, chunks: list[tuple[int, str]]
    ) -> bytes:
        parts: list[bytes] = []
        for chunk_number, sha256 in sorted(chunks):
            path = self.brain_dump_audio_chunk_path(owner_id, operation_id, chunk_number, sha256)
            if not path.exists():
                raise NotFoundError("Brain dump audio chunk", f"{operation_id}:{chunk_number}")
            parts.append(path.read_bytes())
        return b"".join(parts)

    def delete_brain_dump_audio_chunks(
        self, *, owner_id: str, operation_id: str, chunks: list[tuple[int, str]]
    ) -> bool:
        """Delete an operation's raw-audio media and verify no bytes remain.

        Returns ``True`` only when the operation's media directory is confirmed
        gone (so the caller may safely clear the metadata that makes it
        findable). A permission/IO error -- including a partial failure that
        removes some files but leaves the directory -- returns ``False`` without
        raising, so the caller keeps the audio fail-closed and the retention
        sweep retries until absence is confirmed.
        """

        del chunks
        operation_dir = self.brain_dump_audio_operation_path(owner_id, operation_id)
        shutil.rmtree(operation_dir, ignore_errors=True)
        return not operation_dir.exists()

    def list_expired_raw_audio_operations(
        self,
    ) -> list[BrainDumpOperationDocument]:
        # "awaiting_confirmation" is included alongside the terminal statuses
        # because raw audio's retention clock starts at successful
        # reconciliation, not only at operation completion/cancellation/
        # failure — an operation left awaiting confirmation and never
        # committed must still have its raw audio purged on schedule.
        #
        # No SQL column tracks the artifact-specific ``raw_audio_expires_at``
        # anchor (it lives inside the JSON payload), so this returns every
        # candidate in an eligible status; the caller compares each
        # document's own anchor against the current time to decide whether
        # it is actually due, exactly like the provider-lease sweep does for
        # ``lease_expires_at``.
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM brain_dump_operations
                """
            ).fetchall()
        return [
            self._decode_brain_dump_operation(json.loads(row["payload"]))[0]
            for row in rows
        ]

    def list_in_flight_provider_run_operations(
        self,
    ) -> list[BrainDumpOperationDocument]:
        """Operations whose latest provider run may hold a due/expired lease.

        No SQL column tracks ``lease_expires_at`` directly (it lives inside
        the JSON payload), so this returns every ``accurate_transcribing``/
        ``reconciling`` operation across all owners; the caller inspects each
        document's last provider run to decide whether its lease is actually
        due before claiming it.
        """

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM brain_dump_operations
                WHERE status IN ('accurate_transcribing', 'reconciling')
                """
            ).fetchall()
        return [
            self._decode_brain_dump_operation(json.loads(row["payload"]))[0]
            for row in rows
        ]

    def list_committing_operations(self) -> list[BrainDumpOperationDocument]:
        """Operations frozen mid-commit (``committing``) that may need resuming.

        A crash between the frozen batch and finalize leaves an operation here
        with a durable partial ledger; the caller resumes each through the
        owner-serialized, deterministic-child-key commit path.
        """

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM brain_dump_operations
                WHERE status = 'committing'
                """
            ).fetchall()
        return [
            self._decode_brain_dump_operation(json.loads(row["payload"]))[0]
            for row in rows
        ]

    def list_expired_working_artifact_operations(
        self, *, before: datetime
    ) -> list[BrainDumpOperationDocument]:
        """Operations whose uncommitted transcript/proposal working data may
        be purged: anything that never reached ``completed`` (so committed
        provenance behind an already-created ``TaskDocument`` is never
        touched), including abandoned ``recording``/``awaiting_confirmation``
        operations no one ever finished or discarded."""

        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM brain_dump_operations
                WHERE updated_at < ?
                """,
                (before.isoformat(),),
            ).fetchall()
        return [
            self._decode_brain_dump_operation(json.loads(row["payload"]))[0]
            for row in rows
        ]

    def list_brain_dump_operations(self) -> list[BrainDumpOperationDocument]:
        with self._connection() as conn:
            rows = conn.execute("SELECT payload FROM brain_dump_operations").fetchall()
        return [
            self._decode_brain_dump_operation(json.loads(row["payload"]))[0]
            for row in rows
        ]

    def purge_brain_dump_media_orphans(self) -> int:
        """Remove untracked media and interrupted atomic-write temp files.

        Runs under the same global command lock used to serialize owner
        writes (audio-chunk uploads included), and re-reads the "known
        media" snapshot from the database only after acquiring it. Without
        this, a chunk durably uploaded between an outside caller listing
        operations and this sweep scanning the filesystem would look
        orphaned -- and get deleted moments after being written -- because
        the snapshot and the filesystem scan were not atomic with respect
        to a concurrent upload.
        """

        with self.command_lock("system:media-orphan-sweep"):
            operations = self.list_brain_dump_operations()
            expected = {
                (operation.owner_id, operation.id): {
                    f"{chunk.chunk_number:06d}-{chunk.sha256}.bin"
                    for chunk in operation.audio_chunks
                }
                for operation in operations
            }
            root = self.resolve("brain-dump-media")
            if not root.exists():
                return 0
            removed = 0
            for owner_path in root.iterdir():
                if not owner_path.is_dir():
                    owner_path.unlink(missing_ok=True)
                    removed += 1
                    continue
                for operation_path in owner_path.iterdir():
                    if not operation_path.is_dir():
                        operation_path.unlink(missing_ok=True)
                        removed += 1
                        continue
                    known = expected.get((owner_path.name, operation_path.name))
                    if known is None:
                        shutil.rmtree(operation_path, ignore_errors=True)
                        removed += 1
                        continue
                    for media_path in operation_path.iterdir():
                        if media_path.name not in known:
                            media_path.unlink(missing_ok=True)
                            removed += 1
            return removed

    def get_brain_dump_operation_for_owner(
        self, operation_id: str, *, owner_id: str
    ) -> BrainDumpOperationDocument:
        loaded = self._load_brain_dump_operation(operation_id, owner_id=owner_id)
        if loaded is not None:
            operation, migrated = loaded
            if not migrated:
                return operation
            if getattr(self._thread_state, "conn", None) is not None:
                self.save_brain_dump_operation(operation)
                return operation
            with self.command_lock(owner_id):
                current = self._load_brain_dump_operation(
                    operation_id, owner_id=owner_id
                )
                if current is None:
                    raise NotFoundError("Brain dump operation", operation_id)
                current_operation, current_migrated = current
                if current_migrated:
                    self.save_brain_dump_operation(current_operation)
                return current_operation

        path = self.brain_dump_operation_path(owner_id, operation_id)
        if not path.exists():
            raise NotFoundError("Brain dump operation", operation_id)
        legacy, _ = self._decode_brain_dump_operation(
            json.loads(path.read_text(encoding="utf-8"))
        )
        if getattr(self._thread_state, "conn", None) is not None:
            # Already inside this thread's serialized command transaction.
            self.save_brain_dump_operation(legacy)
            return legacy
        with self.command_lock(owner_id):
            # Re-check under the lock so a concurrent write is never clobbered
            # by the stale legacy JSON snapshot.
            current = self._load_brain_dump_operation(operation_id, owner_id=owner_id)
            if current is not None:
                return current[0]
            self.save_brain_dump_operation(legacy)
            return legacy

    def _load_brain_dump_operation(
        self, operation_id: str, *, owner_id: str
    ) -> tuple[BrainDumpOperationDocument, bool] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT payload FROM brain_dump_operations
                WHERE owner_id = ? AND id = ?
                """,
                (owner_id, operation_id),
            ).fetchone()
        if row is None:
            return None
        return self._decode_brain_dump_operation(json.loads(row["payload"]))

    def get_idempotency(self, *, owner_id: str, key: str) -> IdempotencyRecord | None:
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT key, command, request_hash, resource_id, response_body, created_at
                FROM idempotency_records WHERE owner_id = ? AND key_hash = ?
                """,
                (owner_id, key_hash),
            ).fetchone()
        if row is None:
            return None
        return IdempotencyRecord(
            key=row["key"],
            command=row["command"],
            request_hash=row["request_hash"],
            resource_id=row["resource_id"],
            response_body=json.loads(row["response_body"]),
            created_at=row["created_at"],
        )

    def save_idempotency(self, *, owner_id: str, record: IdempotencyRecord) -> None:
        key_hash = hashlib.sha256(record.key.encode("utf-8")).hexdigest()
        with self._connection() as conn, _sqlite_guard("Idempotency-Key", record.key):
            conn.execute(
                """
                INSERT OR REPLACE INTO idempotency_records
                    (owner_id, key_hash, key, command, request_hash, resource_id,
                     response_body, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    owner_id,
                    key_hash,
                    record.key,
                    record.command,
                    record.request_hash,
                    record.resource_id,
                    json.dumps(record.response_body, sort_keys=True),
                    record.created_at.isoformat(),
                ),
            )
        BaseRepository.dump_model(self.idempotency_path(owner_id, record.key), record)

    def scrub_idempotency_snapshots(
        self, *, owner_id: str, operation_id: str, response_body: dict[str, object]
    ) -> int:
        """Redact an operation's text-bearing snapshots from its command log.

        Every voice command records the full operation as its replay result, so
        transcript/proposal text lives in the idempotency records too -- a
        plaintext copy outside the operation table. When the working-artifact
        purge clears an operation's text, this overwrites every command record
        for that operation (SQLite row + JSON sidecar) with the already-redacted
        snapshot, so no text outlives the retention window. Replay stays coherent
        (an old key returns the current text-free operation) and the redacted
        snapshot carries the operation's post-purge revision, so reconciling it
        never resurrects text.
        """

        payload = json.dumps(response_body, sort_keys=True)
        with self._connection() as conn, _sqlite_guard("Idempotency-Key", operation_id):
            rows = conn.execute(
                """
                SELECT key, command, request_hash, created_at
                FROM idempotency_records
                WHERE owner_id = ? AND resource_id = ?
                """,
                (owner_id, operation_id),
            ).fetchall()
            if not rows:
                return 0
            conn.execute(
                """
                UPDATE idempotency_records SET response_body = ?
                WHERE owner_id = ? AND resource_id = ?
                """,
                (payload, owner_id, operation_id),
            )
        for row in rows:
            BaseRepository.dump_model(
                self.idempotency_path(owner_id, row["key"]),
                IdempotencyRecord(
                    key=row["key"],
                    command=row["command"],
                    request_hash=row["request_hash"],
                    resource_id=operation_id,
                    response_body=response_body,
                    created_at=row["created_at"],
                ),
            )
        return len(rows)

    def purge_expired_idempotency(self, *, owner_id: str, now: datetime) -> int:
        """Drop idempotency records past retention so history stays bounded."""

        cutoff = (now - IDEMPOTENCY_RETENTION).isoformat()
        with self._connection() as conn, _sqlite_guard("Idempotency-Key", owner_id):
            rows = conn.execute(
                """
                SELECT key FROM idempotency_records
                WHERE owner_id = ? AND created_at < ?
                """,
                (owner_id, cutoff),
            ).fetchall()
            if not rows:
                return 0
            conn.execute(
                "DELETE FROM idempotency_records WHERE owner_id = ? AND created_at < ?",
                (owner_id, cutoff),
            )
        for row in rows:
            self.idempotency_path(owner_id, row["key"]).unlink(missing_ok=True)
        return len(rows)

    def list_idempotency_for_owner(self, *, owner_id: str) -> list[IdempotencyRecord]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT key, command, request_hash, resource_id, response_body, created_at
                FROM idempotency_records WHERE owner_id = ?
                """,
                (owner_id,),
            ).fetchall()
        return [
            IdempotencyRecord(
                key=row["key"],
                command=row["command"],
                request_hash=row["request_hash"],
                resource_id=row["resource_id"],
                response_body=json.loads(row["response_body"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]
