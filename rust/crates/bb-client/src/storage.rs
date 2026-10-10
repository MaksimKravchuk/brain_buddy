//! The local SQLite store: schema, migrations and the single-writer rules.
//!
//! One database file per workspace (account-less, or one per account), shared
//! by every process of the app through its App Group path. Durability is
//! WAL with `synchronous = FULL`, so a committed write survives a crash or
//! power loss. Each write is one `BEGIN IMMEDIATE` transaction: it holds
//! SQLite's cross-process write lock, waits for it at most the configured
//! busy timeout, and re-checks the schema version under that lock so a
//! process from an older build never writes into a newer schema.

use crate::locking::{LockMode, MigrationLock};
use rusqlite::{
    Connection, ErrorCode, OpenFlags, OptionalExtension, Transaction, TransactionBehavior,
};
use std::fmt;
use std::fs::{self, DirBuilder, Permissions};
use std::io;
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::time::Duration;

/// The schema version this build reads and writes (`PRAGMA user_version`).
pub const SCHEMA_VERSION: i64 = 2;

/// `MIGRATIONS[n]` moves the schema from version `n` to `n + 1`.
const MIGRATIONS: [&str; 2] = [SCHEMA_V1, SCHEMA_V2];

/// Why the store could not do what was asked. Every variant means nothing
/// of the failed operation was saved; only `Busy` is worth retrying as is.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum StoreError {
    /// `STORE_BUSY`: a bounded lock wait ran out.
    Busy,
    /// `STORE_FULL`: the disk or the database is full.
    Full,
    /// `STORE_CORRUPT`: the file is not a readable store. It is left as is.
    Corrupt,
    /// `STORE_UPGRADE_REQUIRED`: the schema was written by a newer build.
    UpgradeRequired { found: i64 },
    /// The file belongs to a different workspace. It is left as is.
    WorkspaceMismatch,
    /// Any other storage failure.
    Io(String),
}

impl StoreError {
    /// The stable code the bindings carry across FFI.
    pub fn code(&self) -> &'static str {
        match self {
            Self::Busy => "STORE_BUSY",
            Self::Full => "STORE_FULL",
            Self::Corrupt => "STORE_CORRUPT",
            Self::UpgradeRequired { .. } => "STORE_UPGRADE_REQUIRED",
            Self::WorkspaceMismatch => "WORKSPACE_MISMATCH",
            Self::Io(_) => "STORE_IO",
        }
    }

    pub fn is_retryable(&self) -> bool {
        matches!(self, Self::Busy)
    }
}

impl fmt::Display for StoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(detail) => write!(f, "{}: {detail}", self.code()),
            _ => f.write_str(self.code()),
        }
    }
}

impl std::error::Error for StoreError {}

impl From<rusqlite::Error> for StoreError {
    fn from(error: rusqlite::Error) -> Self {
        match error.sqlite_error_code() {
            Some(ErrorCode::DatabaseBusy | ErrorCode::DatabaseLocked) => Self::Busy,
            Some(ErrorCode::DiskFull) => Self::Full,
            Some(ErrorCode::DatabaseCorrupt | ErrorCode::NotADatabase) => Self::Corrupt,
            _ => Self::Io(error.to_string()),
        }
    }
}

impl From<io::Error> for StoreError {
    fn from(error: io::Error) -> Self {
        match error.kind() {
            io::ErrorKind::StorageFull => Self::Full,
            kind => Self::Io(kind.to_string()),
        }
    }
}

/// Whether an open store accepts writes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StoreStatus {
    Ready,
    /// A newer build's schema: readable for recovery, never written or
    /// migrated by this build.
    ReadOnlyRecovery {
        found: i64,
    },
}

/// Where the store lives and whose it is.
#[derive(Clone, Debug)]
pub struct OpenOptions {
    pub path: PathBuf,
    /// The workspace this file must belong to. A fresh file is bound to it.
    pub workspace_id: String,
    /// The bound on every lock wait. Running out is `StoreError::Busy`.
    pub busy_timeout: Duration,
}

/// An open handle on one workspace's store.
#[derive(Debug)]
pub struct Store {
    conn: Connection,
    status: StoreStatus,
}

impl Store {
    /// Opens the store, creating and migrating it when needed. A file from
    /// a newer build opens read-only; an unreadable file or one bound to
    /// another workspace is an error and is never modified.
    pub fn open(options: &OpenOptions) -> Result<Self, StoreError> {
        let path = &options.path;
        if let Some(directory) = path.parent() {
            DirBuilder::new()
                .recursive(true)
                .mode(0o700)
                .create(directory)?;
        }
        // A store that does not exist yet is bootstrapped by exactly one
        // process: switching a fresh file to WAL needs SQLite's exclusive
        // lock, which concurrent first openers would otherwise race for and
        // lose with an immediate BUSY that no busy timeout retries.
        if is_uninitialised(path)? {
            let exclusive =
                MigrationLock::acquire(path, LockMode::Exclusive, options.busy_timeout)?;
            let _exclusive = exclusive.ok_or(StoreError::Busy)?;
            if is_uninitialised(path)? {
                create_owner_only(path)?;
                let mut conn = connect(options, false)?;
                migrate(&mut conn, &options.workspace_id)?;
            }
        }
        let shared = MigrationLock::acquire(path, LockMode::Shared, options.busy_timeout)?;
        let shared = shared.ok_or(StoreError::Busy)?;
        create_owner_only(path)?;
        let mut conn = connect(options, false)?;
        let found = user_version(&conn)?;
        let status = if found > SCHEMA_VERSION {
            drop(conn);
            conn = connect(options, true)?;
            StoreStatus::ReadOnlyRecovery { found }
        } else {
            if found < SCHEMA_VERSION {
                drop(shared);
                let exclusive =
                    MigrationLock::acquire(path, LockMode::Exclusive, options.busy_timeout)?;
                let _exclusive = exclusive.ok_or(StoreError::Busy)?;
                migrate(&mut conn, &options.workspace_id)?;
            }
            StoreStatus::Ready
        };
        let bound: Option<String> = conn
            .query_row("SELECT workspace_id FROM sync_meta", [], |row| row.get(0))
            .optional()?;
        match bound {
            Some(bound) if bound == options.workspace_id => Ok(Self { conn, status }),
            Some(_) => Err(StoreError::WorkspaceMismatch),
            None => Err(StoreError::Corrupt),
        }
    }

    pub fn status(&self) -> StoreStatus {
        self.status
    }

    /// Runs `body` in one write transaction holding the cross-process write
    /// lock. `body` must re-read what it depends on: another process may
    /// have written since this handle last looked. `Ok` means committed and
    /// durable; any error means nothing `body` did was saved.
    pub fn write<T>(
        &mut self,
        body: impl FnOnce(&Transaction<'_>) -> rusqlite::Result<T>,
    ) -> Result<T, StoreError> {
        self.try_write(|transaction| body(transaction).map_err(StoreError::from))
    }

    /// [`Store::write`] for a body with its own error type: an `Err` rolls the
    /// transaction back, so a refusal decided mid-way leaves nothing behind.
    pub fn try_write<T, E: From<StoreError>>(
        &mut self,
        body: impl FnOnce(&Transaction<'_>) -> Result<T, E>,
    ) -> Result<T, E> {
        if let StoreStatus::ReadOnlyRecovery { found } = self.status {
            return Err(StoreError::UpgradeRequired { found }.into());
        }
        let transaction = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(StoreError::from)?;
        let found = user_version(&transaction)?;
        if found != SCHEMA_VERSION {
            return Err(StoreError::UpgradeRequired { found }.into());
        }
        let value = body(&transaction)?;
        transaction.commit().map_err(StoreError::from)?;
        Ok(value)
    }

    /// Runs `body` against one consistent snapshot of the store.
    pub fn read<T>(
        &mut self,
        body: impl FnOnce(&Transaction<'_>) -> rusqlite::Result<T>,
    ) -> Result<T, StoreError> {
        let transaction = self.conn.transaction()?;
        Ok(body(&transaction)?)
    }

    /// Closes the handle once SQLite has released it.
    pub fn close(self) -> Result<(), StoreError> {
        self.conn.close().map_err(|(_, error)| error.into())
    }
}

fn connect(options: &OpenOptions, read_only: bool) -> Result<Connection, StoreError> {
    let flags = if read_only {
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX
    } else {
        OpenFlags::default()
    };
    let conn = Connection::open_with_flags(&options.path, flags)?;
    conn.busy_timeout(options.busy_timeout)?;
    if !read_only {
        conn.pragma_update(None, "journal_mode", "WAL")?;
    }
    conn.pragma_update(None, "synchronous", "FULL")?;
    conn.pragma_update(None, "foreign_keys", true)?;
    // On Apple platforms fsync reaches only the drive cache.
    #[cfg(target_vendor = "apple")]
    conn.pragma_update(None, "fullfsync", true)?;
    #[cfg(target_vendor = "apple")]
    conn.pragma_update(None, "checkpoint_fullfsync", true)?;
    Ok(conn)
}

/// True when the store file is missing or empty, i.e. SQLite has never
/// written its header.
fn is_uninitialised(path: &Path) -> Result<bool, StoreError> {
    match fs::metadata(path) {
        Ok(metadata) => Ok(metadata.len() == 0),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(true),
        Err(error) => Err(error.into()),
    }
}

/// Creates the file owner-only before SQLite opens it, so the WAL and shared
/// memory files SQLite derives from it are never group/world readable.
fn create_owner_only(path: &Path) -> Result<(), StoreError> {
    fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(false)
        .mode(0o600)
        .open(path)?;
    fs::set_permissions(path, Permissions::from_mode(0o600))?;
    Ok(())
}

fn user_version(conn: &Connection) -> Result<i64, StoreError> {
    Ok(conn.query_row("PRAGMA user_version", [], |row| row.get(0))?)
}

/// Brings the schema to `SCHEMA_VERSION` in one exclusive transaction. Call
/// with the exclusive migration lock held.
fn migrate(conn: &mut Connection, workspace_id: &str) -> Result<(), StoreError> {
    let transaction = conn.transaction_with_behavior(TransactionBehavior::Exclusive)?;
    // Re-read under the lock: another process may have migrated meanwhile.
    let found = user_version(&transaction)?;
    if found > SCHEMA_VERSION {
        return Err(StoreError::UpgradeRequired { found });
    }
    for (from, sql) in MIGRATIONS.iter().enumerate().skip(found as usize) {
        transaction.execute_batch(sql)?;
        transaction.pragma_update(None, "user_version", from as i64 + 1)?;
    }
    if found == 0 {
        transaction.execute(
            "INSERT INTO sync_meta (workspace_id) VALUES (?1)",
            [workspace_id],
        )?;
    }
    transaction.commit()?;
    Ok(())
}

/// Version 1: the tables of data-model.md "Local durable records". Counters
/// that travel as decimal strings on the wire are stored as TEXT.
const SCHEMA_V1: &str = "
CREATE TABLE sync_meta (
    workspace_id TEXT PRIMARY KEY NOT NULL,
    singleton INTEGER NOT NULL DEFAULT 1 UNIQUE CHECK (singleton = 1),
    storage_epoch INTEGER NOT NULL DEFAULT 1,
    account_id TEXT,
    scope_id TEXT,
    device_id TEXT,
    workspace_generation INTEGER NOT NULL DEFAULT 0,
    session_generation INTEGER NOT NULL DEFAULT 0,
    local_sync_generation INTEGER NOT NULL DEFAULT 0,
    server_generation TEXT,
    device_epoch TEXT,
    device_epoch_state TEXT NOT NULL DEFAULT 'none' CHECK (device_epoch_state IN
        ('none', 'pending_registration', 'active', 'closed')),
    -- Account-less work is never sent until the explicit link choice is
    -- recorded; the checkpoint names the local records an import included so
    -- a crash cannot create a second import.
    account_link_state TEXT NOT NULL DEFAULT 'unchosen' CHECK (account_link_state IN
        ('unchosen', 'account_less', 'linking', 'linked')),
    link_checkpoint BLOB,
    next_local_seq INTEGER NOT NULL DEFAULT 1 CHECK (next_local_seq > 0),
    cursor TEXT,
    base_watermark TEXT,
    projection_generation INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT
) STRICT;
CREATE TRIGGER sync_meta_identity_fixed BEFORE UPDATE OF workspace_id ON sync_meta
BEGIN SELECT RAISE(ABORT, 'workspace identity is immutable'); END;
CREATE TRIGGER sync_meta_kept BEFORE DELETE ON sync_meta
BEGIN SELECT RAISE(ABORT, 'workspace identity is immutable'); END;

CREATE TABLE confirmed_records (
    workspace_id TEXT NOT NULL REFERENCES sync_meta (workspace_id),
    record_type TEXT NOT NULL,
    record_key TEXT NOT NULL,
    record_version TEXT NOT NULL,
    edit_revision TEXT,
    tombstone INTEGER NOT NULL DEFAULT 0 CHECK (tombstone IN (0, 1)),
    body BLOB CHECK (tombstone = 1 OR body IS NOT NULL),
    PRIMARY KEY (workspace_id, record_type, record_key)
) STRICT, WITHOUT ROWID;

CREATE TABLE outbox (
    workspace_id TEXT NOT NULL REFERENCES sync_meta (workspace_id),
    command_id TEXT NOT NULL,
    device_epoch TEXT NOT NULL,
    local_seq INTEGER NOT NULL,
    envelope BLOB NOT NULL,
    envelope_digest BLOB NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'sending', 'unknown',
        'accepted_awaiting_feed', 'rejected', 'blocked_dependency', 'completed')),
    ever_sent INTEGER NOT NULL DEFAULT 0 CHECK (ever_sent IN (0, 1)),
    attempts INTEGER NOT NULL DEFAULT 0,
    first_sent_at TEXT,
    last_attempt_at TEXT,
    next_attempt_at TEXT,
    superseded_by TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, command_id),
    UNIQUE (workspace_id, local_seq)
) STRICT;
CREATE INDEX outbox_runnable ON outbox (workspace_id, state, local_seq);
CREATE TRIGGER outbox_envelope_immutable
BEFORE UPDATE OF command_id, device_epoch, local_seq, envelope, envelope_digest ON outbox
BEGIN SELECT RAISE(ABORT, 'outbox envelopes are immutable'); END;
CREATE TRIGGER outbox_ever_sent_sticky BEFORE UPDATE OF ever_sent ON outbox
WHEN OLD.ever_sent = 1 AND NEW.ever_sent = 0
BEGIN SELECT RAISE(ABORT, 'ever_sent cannot be cleared'); END;

CREATE TABLE outbox_dependencies (
    workspace_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    depends_on TEXT NOT NULL,
    PRIMARY KEY (workspace_id, command_id, depends_on),
    FOREIGN KEY (workspace_id, command_id) REFERENCES outbox (workspace_id, command_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX outbox_dependents ON outbox_dependencies (workspace_id, depends_on);

CREATE TABLE command_receipts (
    workspace_id TEXT NOT NULL REFERENCES sync_meta (workspace_id),
    command_id TEXT NOT NULL,
    server_generation TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'no_op', 'rejected')),
    commit_seq TEXT,
    receipt BLOB NOT NULL,
    verified_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, command_id, server_generation)
) STRICT, WITHOUT ROWID;

CREATE TABLE sync_issues (
    workspace_id TEXT NOT NULL REFERENCES sync_meta (workspace_id),
    issue_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    local_intent BLOB NOT NULL,
    local_text TEXT,
    shown_base_revision TEXT,
    dependent_ids TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(dependent_ids)),
    resolution TEXT NOT NULL DEFAULT 'open'
        CHECK (resolution IN ('open', 'dismissed', 'replaced', 'reconciled')),
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    PRIMARY KEY (workspace_id, issue_id)
) STRICT;
CREATE INDEX sync_issues_by_command ON sync_issues (workspace_id, command_id);

CREATE TABLE drafts (
    workspace_id TEXT NOT NULL REFERENCES sync_meta (workspace_id),
    draft_id TEXT NOT NULL,
    editor_kind TEXT NOT NULL,
    record_type TEXT,
    record_key TEXT,
    fields BLOB NOT NULL,
    base_revision TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, draft_id)
) STRICT;

CREATE TABLE identity_aliases (
    workspace_id TEXT NOT NULL REFERENCES sync_meta (workspace_id),
    entity_type TEXT NOT NULL,
    old_local_id TEXT NOT NULL,
    server_id TEXT NOT NULL,
    provenance TEXT NOT NULL,
    PRIMARY KEY (workspace_id, entity_type, old_local_id)
) STRICT, WITHOUT ROWID;
CREATE TRIGGER identity_aliases_proven_once
BEFORE UPDATE OF workspace_id, entity_type, old_local_id, server_id ON identity_aliases
BEGIN SELECT RAISE(ABORT, 'a proven alias is immutable'); END;

-- A snapshot or oversized transaction being downloaded. Never the active
-- base: activation copies it into confirmed_records under the write lock.
CREATE TABLE staging_bases (
    workspace_id TEXT NOT NULL REFERENCES sync_meta (workspace_id),
    activation_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('snapshot', 'transaction')),
    target_generation TEXT NOT NULL,
    target_watermark TEXT NOT NULL,
    manifest BLOB NOT NULL,
    manifest_digest BLOB NOT NULL,
    total_pages INTEGER NOT NULL CHECK (total_pages >= 0),
    state TEXT NOT NULL DEFAULT 'receiving' CHECK (state IN
        ('receiving', 'complete', 'activated', 'abandoned')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, activation_id)
) STRICT;
-- The received-page bitmap is the set of rows here.
CREATE TABLE staging_pages (
    workspace_id TEXT NOT NULL,
    activation_id TEXT NOT NULL,
    page_index INTEGER NOT NULL CHECK (page_index >= 0),
    page_digest BLOB NOT NULL,
    body BLOB NOT NULL,
    PRIMARY KEY (workspace_id, activation_id, page_index),
    FOREIGN KEY (workspace_id, activation_id)
        REFERENCES staging_bases (workspace_id, activation_id) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;
";

/// Version 2: the visible projection and the local result of a command.
///
/// `visible_records` is `confirmed + replay(pending)` made durable, so one
/// transaction can save a command and what it changed; it is rebuildable from
/// `confirmed_records` and the outbox. `source_command_id` names the queued
/// command that last wrote a row, which is how a later gesture finds the
/// immutable identity it depends on. `outbox.projection_generation` and
/// `local_result` keep what `execute` answered, so a retry after an unknown
/// local completion returns the same answer. `outbox.envelope_digest` holds the
/// SHA-256 of the caller's request, which that retry is compared with.
const SCHEMA_V2: &str = "
ALTER TABLE outbox ADD COLUMN projection_generation INTEGER;
ALTER TABLE outbox ADD COLUMN local_result BLOB;

CREATE TABLE visible_records (
    workspace_id TEXT NOT NULL REFERENCES sync_meta (workspace_id),
    record_type TEXT NOT NULL,
    record_key TEXT NOT NULL,
    edit_revision TEXT,
    source_command_id TEXT,
    body BLOB NOT NULL,
    PRIMARY KEY (workspace_id, record_type, record_key)
) STRICT, WITHOUT ROWID;
CREATE INDEX visible_by_key ON visible_records (workspace_id, record_key);

-- A store upgraded with confirmed rows or queued work has no projection yet:
-- the next write rebuilds it (replay) before deciding against it.
ALTER TABLE sync_meta ADD COLUMN projection_stale INTEGER NOT NULL DEFAULT 0;
UPDATE sync_meta SET projection_stale = 1
WHERE EXISTS (SELECT 1 FROM confirmed_records) OR EXISTS (SELECT 1 FROM outbox);
";
