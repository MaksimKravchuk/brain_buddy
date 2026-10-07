"""Identity's authoritative SQLite store and shared transaction lifecycle."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.exceptions import RepositoryError
from app.utils.file_ops import ensure_directory

from .sqlite import SQLiteRepositorySupport

AUTH_SCHEMA_EPOCH = 1

_SCHEMA = """
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL DEFAULT '',
    email_verified_at TEXT,
    auth_version INTEGER NOT NULL DEFAULT 0 CHECK(auth_version >= 0),
    created_at TEXT NOT NULL,
    deletion_requested_at TEXT,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
);
CREATE TABLE auth_identity_bindings (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    issuer TEXT NOT NULL,
    namespace TEXT NOT NULL,
    subject TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    email TEXT,
    email_verified INTEGER NOT NULL DEFAULT 0,
    is_private_email INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
    UNIQUE(provider, issuer, namespace, subject),
    UNIQUE(user_id, provider),
    UNIQUE(id, user_id)
);
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    auth_version INTEGER NOT NULL DEFAULT 0 CHECK(auth_version >= 0),
    auth_method TEXT NOT NULL DEFAULT 'password',
    confirmed_at TEXT,
    provider_binding_id TEXT,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    UNIQUE(token_hash, user_id),
    FOREIGN KEY(provider_binding_id, user_id)
        REFERENCES auth_identity_bindings(id, user_id) ON DELETE CASCADE
);
CREATE INDEX sessions_user ON sessions(user_id);
CREATE INDEX sessions_expiry ON sessions(expires_at);
CREATE TABLE auth_attempts (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    auth_version INTEGER NOT NULL DEFAULT 0 CHECK(auth_version >= 0),
    session_hash TEXT,
    provider TEXT NOT NULL,
    intent TEXT NOT NULL,
    action TEXT,
    channel TEXT NOT NULL,
    client_challenge TEXT NOT NULL,
    state_hash TEXT UNIQUE,
    nonce_hash TEXT,
    binder_hash TEXT,
    audience TEXT,
    redirect_label TEXT,
    status TEXT NOT NULL DEFAULT 'started',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    lease_id TEXT,
    lease_expires_at TEXT,
    sealed_payload TEXT,
    key_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
    FOREIGN KEY(session_hash, user_id)
        REFERENCES sessions(token_hash, user_id) ON DELETE CASCADE
);
CREATE INDEX auth_attempts_owner ON auth_attempts(user_id);
CREATE INDEX auth_attempts_expiry ON auth_attempts(expires_at);
CREATE TABLE auth_handoffs (
    digest TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES auth_attempts(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    consumed_at TEXT
);
CREATE INDEX auth_handoffs_expiry ON auth_handoffs(expires_at);
CREATE TABLE auth_challenges (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    auth_version INTEGER NOT NULL DEFAULT 0 CHECK(auth_version >= 0),
    session_hash TEXT,
    purpose TEXT NOT NULL,
    destination TEXT NOT NULL,
    action TEXT,
    attempt_id TEXT REFERENCES auth_attempts(id) ON DELETE CASCADE,
    client_challenge TEXT NOT NULL,
    code_hmac TEXT,
    key_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    eligible INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    resend_at TEXT,
    failures INTEGER NOT NULL DEFAULT 0 CHECK(failures >= 0),
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
    FOREIGN KEY(session_hash, user_id)
        REFERENCES sessions(token_hash, user_id) ON DELETE CASCADE
);
CREATE INDEX auth_challenges_owner ON auth_challenges(user_id);
CREATE INDEX auth_challenges_expiry ON auth_challenges(expires_at);
CREATE TABLE auth_mail_jobs (
    id TEXT PRIMARY KEY,
    challenge_id TEXT NOT NULL REFERENCES auth_challenges(id) ON DELETE CASCADE,
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    lease_id TEXT,
    leased_at TEXT,
    sealed_payload TEXT,
    key_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json))
);
CREATE INDEX auth_mail_jobs_dispatch ON auth_mail_jobs(status, expires_at);
CREATE TABLE auth_proofs (
    digest TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    auth_version INTEGER NOT NULL DEFAULT 0 CHECK(auth_version >= 0),
    session_hash TEXT,
    client_challenge TEXT,
    purpose TEXT NOT NULL,
    action TEXT,
    provider_binding_id TEXT,
    generation INTEGER,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
    FOREIGN KEY(session_hash, user_id)
        REFERENCES sessions(token_hash, user_id) ON DELETE CASCADE,
    FOREIGN KEY(provider_binding_id, user_id)
        REFERENCES auth_identity_bindings(id, user_id) ON DELETE CASCADE
);
CREATE INDEX auth_proofs_owner ON auth_proofs(user_id);
CREATE INDEX auth_proofs_expiry ON auth_proofs(expires_at);
CREATE TABLE auth_budgets (
    scope TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    key_id TEXT NOT NULL,
    window_started_at TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0 CHECK(count >= 0),
    resend_at TEXT,
    expires_at TEXT NOT NULL,
    PRIMARY KEY(scope, fingerprint, key_id, window_started_at)
);
CREATE INDEX auth_budgets_expiry ON auth_budgets(expires_at);
CREATE TABLE auth_apple_grants (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    binding_id TEXT NOT NULL,
    issuing_client TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation >= 1),
    sealed_payload TEXT NOT NULL,
    key_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    UNIQUE(binding_id, issuing_client, generation),
    FOREIGN KEY(binding_id, user_id)
        REFERENCES auth_identity_bindings(id, user_id) ON DELETE CASCADE
);
CREATE TABLE auth_apple_cleanup_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    binding_id TEXT NOT NULL,
    issuing_client TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation >= 1),
    sealed_payload TEXT,
    key_id TEXT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0 AND attempts <= 5),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    next_attempt_at TEXT,
    lease_id TEXT,
    lease_expires_at TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(payload_json)),
    FOREIGN KEY(binding_id, user_id)
        REFERENCES auth_identity_bindings(id, user_id) ON DELETE CASCADE
);
CREATE INDEX auth_apple_jobs_dispatch
    ON auth_apple_cleanup_jobs(status, next_attempt_at, expires_at);
CREATE TABLE auth_apple_notification_receipts (
    digest TEXT PRIMARY KEY,
    namespace TEXT NOT NULL,
    event TEXT NOT NULL,
    subject_fingerprint TEXT NOT NULL,
    generation INTEGER,
    event_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX auth_apple_receipts_expiry ON auth_apple_notification_receipts(expires_at);
CREATE TABLE auth_migration_ledger (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    schema_epoch INTEGER NOT NULL,
    import_committed INTEGER NOT NULL DEFAULT 0 CHECK(import_committed IN (0, 1)),
    cleanup_complete INTEGER NOT NULL DEFAULT 0 CHECK(cleanup_complete IN (0, 1)),
    imported_at TEXT,
    cleanup_completed_at TEXT,
    counts_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(counts_json)),
    validation_digest TEXT,
    backup_path TEXT,
    backup_expires_at TEXT
);
"""


class AuthStore(SQLiteRepositorySupport):
    """Own auth schema and reuse one connection for nested facade operations."""

    def __init__(self, root: Path, *, require_ready: bool = True) -> None:
        self.root = ensure_directory(root)
        self.db_path = self.root / "auth.sqlite3"
        self._write_lock = threading.RLock()
        self._thread_state = threading.local()
        exists = self.db_path.exists()
        legacy = any(
            directory.exists() and any(directory.iterdir())
            for directory in (self.root / "users", self.root / "sessions")
        )
        if not exists and legacy and require_ready:
            raise RepositoryError("Explicit authentication migration is required.")
        if not exists:
            self._initialize(cleanup_complete=not legacy)
        if require_ready:
            self.check_ready()

    def _connect(self) -> sqlite3.Connection:
        connection = super()._connect()
        connection.execute("PRAGMA secure_delete = ON")
        return connection

    def _initialize(self, *, cleanup_complete: bool) -> None:
        with self.connection() as connection:
            try:
                connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
                connection.execute(
                    "INSERT INTO auth_migration_ledger(id,schema_epoch,cleanup_complete) VALUES(1,?,?)",
                    (AUTH_SCHEMA_EPOCH, int(cleanup_complete)),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def check_ready(self) -> None:
        """Block readiness until the authoritative migration cleanup completes."""
        with self.connection() as connection:
            ledger = connection.execute(
                "SELECT schema_epoch,cleanup_complete FROM auth_migration_ledger WHERE id=1"
            ).fetchone()
            if ledger is None or ledger["schema_epoch"] != AUTH_SCHEMA_EPOCH:
                raise RepositoryError("Unsupported authentication storage epoch.")
            if not ledger["cleanup_complete"]:
                raise RepositoryError("Authentication migration cleanup is incomplete.")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Pin a connection for this scope, reusing any surrounding scope."""
        active = getattr(self._thread_state, "conn", None)
        if active is not None:
            yield active
            return
        with self.sqlite_guard("Identity", "storage"):
            connection = self._connect()
            self._thread_state.conn = connection
            try:
                yield connection
            finally:
                self._thread_state.conn = None
                connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize writes and commit only the outermost complete operation."""
        with self._write_lock, self.connection() as connection:
            if connection.in_transaction:
                try:
                    yield connection
                except BaseException:
                    self._thread_state.rollback_only = True
                    raise
                return
            self._thread_state.rollback_only = False
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                if self._thread_state.rollback_only:
                    raise RepositoryError("Authentication transaction was aborted.")
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                self._thread_state.rollback_only = False

    def checkpoint(self) -> bool:
        """Attempt WAL truncation after credential cleanup; callers retry if busy."""
        with self.connection() as connection:
            if connection.in_transaction:
                return False
            result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            return bool(result is not None and result[0] == 0)


__all__ = ["AUTH_SCHEMA_EPOCH", "AuthStore"]
