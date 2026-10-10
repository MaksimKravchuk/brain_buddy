//! Import of the legacy `StoreDocument` JSON file into the Rust store
//! (spec 026 T041, contracts/runtime-ffi.md "Migration and packaging boundary").
//!
//! The Swift apps kept everything in one atomically replaced JSON file (the
//! confirmed base, the outbox, the issues, the account, the sync metadata and the
//! device-local Review state). The Rust runtime owns SQLite instead. This module
//! moves the one into the other without ever making the original less safe:
//!
//! 0. **Lock the document.** The importer takes the exclusive `flock` on the file's
//!    sibling `.<name>.lock`, the lock every writer of the legacy file (app, widget, App
//!    Intents, through `FileDocumentStore`) takes, from before the read to after the
//!    commit. No write can land in between, so the import never activates a snapshot
//!    older than the file, and a writer waits for the commit instead of losing its data.
//!    The wait is bounded by the store's busy timeout (`STORE_BUSY`, retryable).
//! 1. **Read and plan** (no side effect). The file is parsed with every field
//!    accounted for: a member this build does not know is a typed refusal, never a
//!    silent drop. Records become typed `bb_domain` records (so the rules' own
//!    validation judges them), identities keep their meaning with no heuristic
//!    merge, and every datum with no table of its own is carried verbatim.
//! 2. **Back up** the source bytes and a schema manifest (version, section counts
//!    and digests, no user text) beside the source, durably and idempotently.
//! 3. **Stage** the typed records as a change stream in the existing
//!    `staging_bases`/`staging_pages` tables, exactly the shape a snapshot uses.
//!    Nothing staged is ever the active base.
//! 4. **Activate and validate in one write transaction** under the exclusive
//!    migration lock: the staged stream is verified against its manifest and
//!    installed by the same code a snapshot uses; aliases, drafts and the local
//!    carriers are written; the visible projection is rebuilt by [`replay_in`];
//!    then counts, IDs, links, flags and every verbatim section are compared with
//!    the source *by independent means* (a second reading of the source against
//!    SQL aggregates over the rows, and full body equality). Only then is the
//!    activation marker flipped, in the same transaction. Any failure rolls the
//!    whole activation back and leaves the original untouched.
//!
//! **The marker** is the staging row `legacy-import-<digest>` reaching
//! `activated`; [`legacy_import_marker`] reads it. A store without it is not
//! imported, whatever else it holds.
//!
//! **What lands where.** Tasks, subtasks, comments, projects and tags are
//! `confirmed_records` (record version `0`, so the first feed or snapshot always
//! advances them). A server ID the legacy file proved becomes the record key and an
//! `identity_aliases` row for the old local ID; a record without one keeps its
//! local ID, shaped by [`legacy_record_key`]. Form drafts become `drafts` rows.
//! Everything else the legacy file held and the schema has no table for (the
//! outbox entries and issues, which `legacy_outbox` turns into queue rows; the
//! Review aggregate; the device-local Review state; the account and sync
//! metadata; per-task local facts) is kept verbatim in `drafts` rows whose
//! `editor_kind` starts with `legacy_`. They are durable and never replaced by
//! incoming data, and the source file's own backup is not what they rely on.
//!
//! The legacy outbox is **not** converted here: its entries are carried and
//! counted, and `import` reports how many are waiting for that slice.

use crate::apply_changes::{ApplyError, Promised, abandon_in, hex, install_change, stream_pages};
use crate::execute::{ExecuteContext, sha256};
use crate::locking::{LockMode, MigrationLock};
use crate::replay::{ReplayError, replay_in};
use crate::storage::{OpenOptions, Store, StoreError, StoreStatus};
use bb_domain::types::{ActorId, Comment, Policy, Project, Subtask, Tag, Task, ZoneName};
use bb_protocol::catalog::EntityType;
use bb_protocol::feed::{Change, Operation};
use bb_protocol::strict_json::reject_duplicate_keys;
use bb_protocol::wire::{Counter, Instant};
use rusqlite::{OptionalExtension, Transaction, params};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::fs::{self, File, OpenOptions as FileOptions, TryLockError};
use std::io::{self, Write};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant as Clock};

const ACTIVATION_PREFIX: &str = "legacy-import-";
const MARKER_SCHEMA: &str = "brainbuddy-legacy-import/v1";
const MANIFEST_SCHEMA: &str = "brainbuddy-legacy-source-manifest/v1";
const STAGING_SCHEMA: &str = "brainbuddy-legacy-import-staging/v1";
/// A staged page: small enough that one page never holds the write lock long.
const PAGE_BYTES: usize = 256 * 1024;
const ALIAS_PROVENANCE: &str = "legacy-import:server-id";
/// The author of a comment the legacy file left unattributed and no account owns.
const LOCAL_ACTOR: &str = "local";
/// Imported records start below every real record version, so the first feed or
/// snapshot change always advances them.
const IMPORTED_VERSION: u64 = 0;

/// The newest `StoreDocument.version` this build reads (`StoreDocument.currentVersion`).
pub const SUPPORTED_SOURCE_VERSION: i64 = 2;

const KIND_OUTBOX: &str = "legacy_outbox_entry";
const KIND_ISSUE: &str = "legacy_sync_issue";
const KIND_REVIEW: &str = "legacy_review_base";
const KIND_LOCAL: &str = "legacy_local_review";
const KIND_SYNC: &str = "legacy_sync_metadata";
const KIND_ACCOUNT: &str = "legacy_account";
const KIND_TASK_LOCAL: &str = "legacy_task_local";
const KIND_FORM: &str = "review_form_draft";

// ------------------------------------------------------------------------- public

/// What the file held, counted by the means any reader of the file has: the
/// counts a second implementation (the Swift decoder) can produce from the same
/// bytes, so the two can be compared before anything is switched.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceCounts {
    pub tasks: u64,
    pub subtasks: u64,
    pub comments: u64,
    pub projects: u64,
    pub tags: u64,
    /// Pending operations, carried for the legacy-outbox slice.
    pub outbox_entries: u64,
    /// Sync issues, carried for the legacy-outbox slice.
    pub issues: u64,
    pub review_sessions: u64,
    pub review_decisions: u64,
    pub review_receipts: u64,
    pub review_park_acks: u64,
    pub review_bulk_releases: u64,
    pub review_navigator_consents: u64,
    /// Unsaved Review form text (`local.formDrafts`).
    pub form_drafts: u64,
}

/// What an import needs.
#[derive(Clone, Debug)]
pub struct ImportRequest {
    /// The Rust store to import into, bound to its workspace.
    pub store: OpenOptions,
    /// The legacy JSON file. It is only read.
    pub source: PathBuf,
    /// Where the backup and the schema manifest go; beside the source by default.
    pub backup_dir: Option<PathBuf>,
    /// The instant of the import (RFC 3339): the time of rows the file gave none.
    pub now: Instant,
    /// The counts an independent reader took from the same file. A disagreement
    /// stops the import before it touches the store.
    pub expected: Option<SourceCounts>,
}

/// The durable record of a finished import: the activation marker.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ImportMarker {
    pub schema: String,
    pub source_sha256: String,
    pub source_bytes: u64,
    pub source_version: i64,
    pub source_generation: i64,
    /// File names, beside the source (or in the requested directory).
    pub backup_file: String,
    pub manifest_file: String,
    pub imported_at: String,
    pub counts: SourceCounts,
    /// Identity aliases written (a server ID the file proved for a local ID).
    pub aliases: u64,
    /// Tasks whose local-only facts (`lastOpenList`, `childrenSyncedAt`, the
    /// private part of a park) were kept.
    pub local_task_facts: u64,
}

/// The outcome of [`import_legacy_store`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ImportReport {
    /// The same source had already been imported: nothing was done.
    pub already_active: bool,
    pub marker: ImportMarker,
}

/// Where a write transaction of the import is, for the tests' failure injection.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ImportStage {
    /// Page `n` of the change stream was staged (inside that page's transaction).
    Staged(u64),
    /// The staged records, aliases and carriers are installed and the projection
    /// rebuilt; nothing is validated yet.
    Installed,
    /// Everything is validated; only the marker flip and the commit remain.
    Verified,
}

/// Why nothing was imported. Whatever it is, the legacy file is as it was and the
/// store has no marker; no variant carries user text.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ImportError {
    /// `IMPORT_SOURCE_MISSING`.
    SourceMissing,
    /// `IMPORT_SOURCE_UNREADABLE`: not JSON, or not a `StoreDocument`.
    SourceUnreadable { field: &'static str },
    /// `IMPORT_SOURCE_UNSUPPORTED`: written by a newer build, or holding a member
    /// this build does not carry.
    SourceUnsupported {
        found: Option<i64>,
        field: Option<&'static str>,
    },
    /// `IMPORT_SOURCE_INCONSISTENT`: readable, but not importable without
    /// guessing (a dangling relation, a repeated identity, a value the rules
    /// refuse).
    SourceInconsistent { field: &'static str },
    /// `IMPORT_SOURCE_CHANGED`: the file changed while it was being imported.
    SourceChanged,
    /// `IMPORT_TARGET_IN_USE`: the store already holds data of its own.
    TargetInUse,
    /// `IMPORT_ALREADY_IMPORTED`: a different file was imported before. It is
    /// never merged.
    AlreadyImported,
    /// `IMPORT_VERIFICATION_FAILED`: the imported rows do not equal the source.
    VerificationFailed { check: &'static str },
    /// `IMPORT_STAGING_INVALID`: the staged stream failed its own checks.
    StagingInvalid,
    /// `IMPORT_SUPERSEDED`: another writer dropped the staging; run it again.
    Superseded,
    /// A storage failure (`STORE_FULL`, `STORE_CORRUPT`, `STORE_UPGRADE_REQUIRED`, ...).
    Store(StoreError),
}

impl ImportError {
    /// The stable code the bindings carry across FFI.
    pub fn code(&self) -> &'static str {
        match self {
            Self::SourceMissing => "IMPORT_SOURCE_MISSING",
            Self::SourceUnreadable { .. } => "IMPORT_SOURCE_UNREADABLE",
            Self::SourceUnsupported { .. } => "IMPORT_SOURCE_UNSUPPORTED",
            Self::SourceInconsistent { .. } => "IMPORT_SOURCE_INCONSISTENT",
            Self::SourceChanged => "IMPORT_SOURCE_CHANGED",
            Self::TargetInUse => "IMPORT_TARGET_IN_USE",
            Self::AlreadyImported => "IMPORT_ALREADY_IMPORTED",
            Self::VerificationFailed { .. } => "IMPORT_VERIFICATION_FAILED",
            Self::StagingInvalid => "IMPORT_STAGING_INVALID",
            Self::Superseded => "IMPORT_SUPERSEDED",
            Self::Store(error) => error.code(),
        }
    }

    /// Whether running the import again can succeed without any change.
    pub fn is_retryable(&self) -> bool {
        match self {
            Self::SourceChanged | Self::Superseded => true,
            Self::Store(error) => error.is_retryable(),
            _ => false,
        }
    }

    /// The static name of the section, rule or check concerned; never content.
    pub fn field(&self) -> Option<&'static str> {
        match self {
            Self::SourceUnreadable { field } | Self::SourceInconsistent { field } => Some(field),
            Self::SourceUnsupported { field, .. } => *field,
            Self::VerificationFailed { check } => Some(check),
            _ => None,
        }
    }
}

impl std::fmt::Display for ImportError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())?;
        match self.field() {
            Some(field) => write!(f, " ({field})"),
            None => Ok(()),
        }
    }
}

impl std::error::Error for ImportError {}

impl From<StoreError> for ImportError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}

impl From<rusqlite::Error> for ImportError {
    fn from(error: rusqlite::Error) -> Self {
        Self::Store(error.into())
    }
}

impl From<io::Error> for ImportError {
    fn from(error: io::Error) -> Self {
        Self::Store(error.into())
    }
}

impl From<ApplyError> for ImportError {
    fn from(error: ApplyError) -> Self {
        match error {
            ApplyError::Store(error) => Self::Store(error),
            _ => Self::StagingInvalid,
        }
    }
}

impl From<ReplayError> for ImportError {
    fn from(error: ReplayError) -> Self {
        match error {
            ReplayError::Store(error) => Self::Store(error),
            _ => Self::VerificationFailed { check: "replay" },
        }
    }
}

fn unreadable(field: &'static str) -> ImportError {
    ImportError::SourceUnreadable { field }
}

fn inconsistent(field: &'static str) -> ImportError {
    ImportError::SourceInconsistent { field }
}

/// The record key of a legacy record: the server ID the file proved, verbatim, or
/// else its local ID, which is kept as it is when it already has the shape the
/// rules accept for a new record (`<prefix>_<lowercase uuid>`), becomes that shape
/// when it is a bare lowercase UUID (the rule `RustIDTable` applies in Swift) and
/// otherwise crosses unchanged. Never a title, time or position.
pub fn legacy_record_key(entity: EntityType, local_id: &str, server_id: Option<&str>) -> String {
    if let Some(server) = server_id {
        return server.to_owned();
    }
    let prefix = entity.as_str();
    if is_client_shape(local_id, prefix) {
        return local_id.to_owned();
    }
    let wire = format!("{prefix}_{local_id}");
    if is_client_shape(&wire, prefix) {
        wire
    } else {
        local_id.to_owned()
    }
}

fn is_client_shape(value: &str, prefix: &str) -> bool {
    let Some(uuid) = value
        .strip_prefix(prefix)
        .and_then(|rest| rest.strip_prefix('_'))
    else {
        return false;
    };
    value.len() <= 64
        && uuid.len() == 36
        && uuid.bytes().enumerate().all(|(index, byte)| match index {
            8 | 13 | 18 | 23 => byte == b'-',
            _ => byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte),
        })
}

/// Imports the legacy file. See the module documentation.
///
/// # Errors
///
/// [`ImportError`]; whatever it is, the legacy file is untouched and the store
/// has no marker. Running again after a crash or a transient failure is safe.
pub fn import_legacy_store(request: &ImportRequest) -> Result<ImportReport, ImportError> {
    import_legacy_store_with(request, |_, _| Ok(()))
}

/// [`import_legacy_store`] with a hook that runs inside each write transaction of
/// the import at its [`ImportStage`]. An `Err` from the hook rolls that
/// transaction back (a full disk, in a test); a hook that kills the process
/// leaves an uncommitted transaction for SQLite to discard.
///
/// # Errors
///
/// As [`import_legacy_store`].
pub fn import_legacy_store_with(
    request: &ImportRequest,
    mut hook: impl FnMut(ImportStage, &Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<ImportReport, ImportError> {
    // A missing file needs no lock (and leaves no lock file behind).
    if let Err(error) = fs::metadata(&request.source) {
        return Err(if error.kind() == io::ErrorKind::NotFound {
            ImportError::SourceMissing
        } else {
            error.into()
        });
    }
    // The document lock first, and held to the end (it is dropped last): the app, the
    // widget and the App Intents write `store.json` under this same lock, so from the
    // read below to the commit no writer can interleave and leave the import with a
    // snapshot older than the file.
    let _document = DocumentLock::acquire(&request.source, request.store.busy_timeout)?;
    let bytes = read_source(&request.source)?;
    let digest = hex(&sha256(&bytes));
    let plan = parse(&bytes, &request.now)?;
    if let Some(expected) = &request.expected
        && *expected != plan.counts
    {
        // A file rewritten between the two readings is a different, retryable story.
        return Err(match read_source(&request.source) {
            Ok(again) if hex(&sha256(&again)) != digest => ImportError::SourceChanged,
            _ => ImportError::VerificationFailed {
                check: "expected_counts",
            },
        });
    }

    let mut store = Store::open(&request.store)?;
    if let StoreStatus::ReadOnlyRecovery { found } = store.status() {
        return Err(StoreError::UpgradeRequired { found }.into());
    }
    let workspace = request.store.workspace_id.as_str();
    let timeout = request.store.busy_timeout;
    let _lock = MigrationLock::acquire(&request.store.path, LockMode::Exclusive, timeout)
        .map_err(StoreError::from)?
        .ok_or(StoreError::Busy)?;

    let id = activation_id(&digest);
    if let Some(done) = store.read(|tx| read_marker(tx, workspace))? {
        return if done.0 == id {
            Ok(ImportReport {
                already_active: true,
                marker: done.1,
            })
        } else {
            Err(ImportError::AlreadyImported)
        };
    }
    store.read(ensure_untouched)??;

    let backup = write_backup(request, &bytes, &plan)?;
    let result = stage_and_activate(&mut store, request, &plan, &backup, &id, &mut hook);
    if result.is_err() {
        // The staged bytes are worthless now; the active store was never touched.
        let _ = store.write(|tx| abandon_in(tx, workspace, &id));
    }
    result.map(|marker| ImportReport {
        already_active: false,
        marker,
    })
}

/// The marker of a finished import, if the store has one.
///
/// # Errors
///
/// [`StoreError`] when the store cannot be read.
pub fn legacy_import_marker(store: &mut Store) -> Result<Option<ImportMarker>, StoreError> {
    let workspace: String = store
        .read(|tx| tx.query_row("SELECT workspace_id FROM sync_meta", [], |row| row.get(0)))?;
    Ok(store
        .read(|tx| read_marker(tx, &workspace))?
        .map(|(_, marker)| marker))
}

// ------------------------------------------------------------------ the source file

/// The advisory lock every writer of the legacy file takes: an exclusive `flock` on the
/// sibling `.<name>.lock` file, exactly as Swift's `DocumentFile.lock()` does (readers take
/// none, because every write replaces the file's inode). `flock` belongs to the open file
/// description, so this excludes the app, a widget and an App Intent in other processes
/// and Swift's own handles in this one. Dropping it closes the file, which releases it.
#[derive(Debug)]
struct DocumentLock {
    _file: File,
}

impl DocumentLock {
    fn path_for(source: &Path) -> PathBuf {
        let name = source
            .file_name()
            .map(|n| n.to_string_lossy())
            .unwrap_or_default();
        source.with_file_name(format!(".{name}.lock"))
    }

    /// Waits at most `timeout`; running out is a retryable `STORE_BUSY`, never a stale read.
    fn acquire(source: &Path, timeout: Duration) -> Result<Self, ImportError> {
        let path = Self::path_for(source);
        let deadline = Clock::now() + timeout;
        loop {
            let file = FileOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .mode(0o600)
                .open(&path)?;
            loop {
                match file.try_lock() {
                    Ok(()) => break,
                    Err(TryLockError::WouldBlock) if Clock::now() < deadline => {
                        std::thread::sleep(Duration::from_millis(5));
                    }
                    Err(TryLockError::WouldBlock) => return Err(StoreError::Busy.into()),
                    Err(TryLockError::Error(error)) => return Err(error.into()),
                }
            }
            // A writer that removes the store removes the lock file while holding it
            // (`FileDocumentStore.destroy`); a lock on an unlinked file excludes no one.
            let held = file.metadata()?;
            match fs::metadata(&path) {
                Ok(current) if (current.dev(), current.ino()) == (held.dev(), held.ino()) => {
                    return Ok(Self { _file: file });
                }
                Ok(_) => {}
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                Err(error) => return Err(error.into()),
            }
        }
    }
}

fn read_source(path: &Path) -> Result<Vec<u8>, ImportError> {
    match fs::read(path) {
        Ok(bytes) => Ok(bytes),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Err(ImportError::SourceMissing),
        Err(error) => Err(error.into()),
    }
}

fn activation_id(digest: &str) -> String {
    format!("{ACTIVATION_PREFIX}{}", &digest[..32])
}

// ------------------------------------------------------------------ reading fields

/// An object whose members are taken one by one: whatever is left over is a
/// member this build does not know, which is refused instead of dropped.
struct Fields {
    section: &'static str,
    map: Map<String, Value>,
}

impl Fields {
    fn new(value: Value, section: &'static str) -> Result<Self, ImportError> {
        match value {
            Value::Object(map) => Ok(Self { section, map }),
            _ => Err(unreadable(section)),
        }
    }

    /// The member, or `None` when absent or `null` (Swift omits an unset optional).
    fn take(&mut self, key: &str) -> Option<Value> {
        match self.map.remove(key) {
            Some(Value::Null) | None => None,
            other => other,
        }
    }

    fn required(&mut self, key: &str) -> Result<Value, ImportError> {
        self.take(key).ok_or(unreadable(self.section))
    }

    fn text(&mut self, key: &str) -> Result<String, ImportError> {
        match self.required(key)? {
            Value::String(text) => Ok(text),
            _ => Err(unreadable(self.section)),
        }
    }

    fn opt_text(&mut self, key: &str) -> Result<Option<String>, ImportError> {
        match self.take(key) {
            None => Ok(None),
            Some(Value::String(text)) => Ok(Some(text)),
            Some(_) => Err(unreadable(self.section)),
        }
    }

    fn int(&mut self, key: &str) -> Result<i64, ImportError> {
        self.required(key)?.as_i64().ok_or(unreadable(self.section))
    }

    fn opt_int(&mut self, key: &str) -> Result<Option<i64>, ImportError> {
        match self.take(key) {
            None => Ok(None),
            Some(value) => value.as_i64().map(Some).ok_or(unreadable(self.section)),
        }
    }

    fn flag(&mut self, key: &str) -> Result<bool, ImportError> {
        match self.take(key) {
            None => Ok(false),
            Some(Value::Bool(flag)) => Ok(flag),
            Some(_) => Err(unreadable(self.section)),
        }
    }

    fn array(&mut self, key: &str) -> Result<Vec<Value>, ImportError> {
        match self.required(key)? {
            Value::Array(items) => Ok(items),
            _ => Err(unreadable(self.section)),
        }
    }

    fn texts(&mut self, key: &str) -> Result<Vec<String>, ImportError> {
        self.array(key)?
            .into_iter()
            .map(|item| match item {
                Value::String(text) => Ok(text),
                _ => Err(unreadable(self.section)),
            })
            .collect()
    }

    fn object(&mut self, key: &str) -> Result<Map<String, Value>, ImportError> {
        match self.required(key)? {
            Value::Object(map) => Ok(map),
            _ => Err(unreadable(self.section)),
        }
    }

    fn finish(self) -> Result<(), ImportError> {
        if self.map.is_empty() {
            Ok(())
        } else {
            Err(ImportError::SourceUnsupported {
                found: None,
                field: Some(self.section),
            })
        }
    }
}

// ---------------------------------------------------------------------- the plan

/// A server ID the file proved for a local ID.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
struct Alias {
    entity_type: String,
    old_local_id: String,
    server_id: String,
}

/// A row of `drafts` that carries a datum the schema has no table for.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
struct Carrier {
    draft_id: String,
    editor_kind: String,
    record_type: Option<String>,
    record_key: Option<String>,
    fields: Value,
    updated_at: String,
}

/// The readings of the source and of the rows that must agree: counts per record
/// type, per state, per relation and flag, and a digest of every verbatim section.
/// The source side is taken from the raw JSON and the store side from SQL, so the
/// two share no code with the builder that wrote the rows.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
struct Facts {
    records: BTreeMap<String, u64>,
    task_states: BTreeMap<String, u64>,
    subtask_states: BTreeMap<String, u64>,
    project_states: BTreeMap<String, u64>,
    tag_states: BTreeMap<String, u64>,
    tasks_with_project: u64,
    tag_links: u64,
    parked_tasks: u64,
    clocked_tasks: u64,
    lossless_archives: u64,
    edited_comments: u64,
    sections: BTreeMap<String, String>,
}

impl Facts {
    /// The first reading on which `self` and `other` disagree.
    fn first_difference(&self, other: &Self) -> Option<&'static str> {
        let checks: [(&'static str, bool); 12] = [
            ("record_counts", self.records == other.records),
            ("task_states", self.task_states == other.task_states),
            (
                "subtask_states",
                self.subtask_states == other.subtask_states,
            ),
            (
                "project_states",
                self.project_states == other.project_states,
            ),
            ("tag_states", self.tag_states == other.tag_states),
            (
                "task_project_links",
                self.tasks_with_project == other.tasks_with_project,
            ),
            ("task_tag_links", self.tag_links == other.tag_links),
            ("parked_tasks", self.parked_tasks == other.parked_tasks),
            ("clocked_tasks", self.clocked_tasks == other.clocked_tasks),
            (
                "lossless_archives",
                self.lossless_archives == other.lossless_archives,
            ),
            (
                "edited_comments",
                self.edited_comments == other.edited_comments,
            ),
            ("verbatim_sections", self.sections == other.sections),
        ];
        checks
            .into_iter()
            .find_map(|(name, equal)| (!equal).then_some(name))
    }
}

struct Plan {
    source_sha256: String,
    source_bytes: u64,
    version: i64,
    generation: i64,
    changes: Vec<Change>,
    aliases: Vec<Alias>,
    carriers: Vec<Carrier>,
    account_id: Option<String>,
    counts: SourceCounts,
    local_task_facts: u64,
    facts: Facts,
}

fn digest_of(value: &Value) -> String {
    hex(&sha256(value.to_string().as_bytes()))
}

fn as_object<'a>(
    value: &'a Value,
    key: &str,
    section: &'static str,
) -> Result<Option<&'a Map<String, Value>>, ImportError> {
    match value.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Object(map)) => Ok(Some(map)),
        Some(_) => Err(unreadable(section)),
    }
}

fn len_of(value: Option<&Map<String, Value>>, key: &str) -> Result<u64, ImportError> {
    match value.and_then(|map| map.get(key)) {
        None | Some(Value::Null) => Ok(0),
        Some(Value::Object(map)) => Ok(map.len() as u64),
        Some(Value::Array(items)) => Ok(items.len() as u64),
        Some(_) => Err(unreadable("review")),
    }
}

fn count_states(
    entries: &[&Value],
    key: &str,
    section: &'static str,
) -> Result<BTreeMap<String, u64>, ImportError> {
    let mut counts = BTreeMap::new();
    for entry in entries {
        let state = entry
            .get(key)
            .and_then(Value::as_str)
            .ok_or(unreadable(section))?;
        *counts.entry(state.to_owned()).or_insert(0) += 1;
    }
    Ok(counts)
}

fn present(entry: &Value, key: &str) -> bool {
    !matches!(entry.get(key), None | Some(Value::Null))
}

/// Reads the source's counts and facts straight from the raw JSON, sharing
/// nothing with the builder.
fn read_facts(root: &Value) -> Result<(SourceCounts, Facts), ImportError> {
    let base = root.get("base").ok_or(unreadable("document"))?;
    let section = |key: &str, name: &'static str| -> Result<Vec<&Value>, ImportError> {
        match base.get(key) {
            Some(Value::Object(map)) => Ok(map.values().collect()),
            _ => Err(unreadable(name)),
        }
    };
    let tasks = section("tasks", "tasks")?;
    let projects = section("projects", "projects")?;
    let tags = section("tags", "tags")?;
    let children = |key: &str| -> Result<Vec<&Value>, ImportError> {
        let mut found = Vec::new();
        for task in &tasks {
            match task.get(key) {
                Some(Value::Array(items)) => found.extend(items.iter()),
                _ => return Err(unreadable("task")),
            }
        }
        Ok(found)
    };
    let subtasks = children("subtasks")?;
    let comments = children("comments")?;
    let review = as_object(base, "review", "review")?;
    let top = |key: &str| -> Result<Vec<Value>, ImportError> {
        match root.get(key) {
            None | Some(Value::Null) => Ok(Vec::new()),
            Some(Value::Array(items)) => Ok(items.clone()),
            Some(_) => Err(unreadable("document")),
        }
    };
    let outbox = top("outbox")?;
    let issues = top("issues")?;
    let local = as_object(root, "local", "local")?;
    let mut local_rest = local.cloned().unwrap_or_default();
    let forms = match local_rest.remove("formDrafts") {
        None | Some(Value::Null) => Map::new(),
        Some(Value::Object(map)) => map,
        Some(_) => return Err(unreadable("local")),
    };

    let counts = SourceCounts {
        tasks: tasks.len() as u64,
        subtasks: subtasks.len() as u64,
        comments: comments.len() as u64,
        projects: projects.len() as u64,
        tags: tags.len() as u64,
        outbox_entries: outbox.len() as u64,
        issues: issues.len() as u64,
        review_sessions: len_of(review, "sessions")?,
        review_decisions: len_of(review, "decisions")?,
        review_receipts: len_of(review, "receipts")?,
        review_park_acks: len_of(review, "parkAcks")?,
        review_bulk_releases: len_of(review, "bulkReleases")?,
        review_navigator_consents: len_of(review, "navigatorConsents")?,
        form_drafts: forms.len() as u64,
    };

    let mut tag_links = 0_u64;
    for task in &tasks {
        match task.get("tagIDs") {
            Some(Value::Array(items)) => tag_links += items.len() as u64,
            _ => return Err(unreadable("task")),
        }
    }
    let records: BTreeMap<String, u64> = [
        ("task", counts.tasks),
        ("subtask", counts.subtasks),
        ("comment", counts.comments),
        ("project", counts.projects),
        ("tag", counts.tags),
    ]
    .into_iter()
    .filter(|(_, count)| *count > 0)
    .map(|(name, count)| (name.to_owned(), count))
    .collect();
    let flagged = |entries: &[&Value], key: &str| {
        entries
            .iter()
            .filter(|entry| entry.get(key).and_then(Value::as_bool) == Some(true))
            .count() as u64
    };
    let sections: BTreeMap<String, String> = [
        ("outbox", Value::Array(outbox.clone())),
        ("issues", Value::Array(issues.clone())),
        ("review", Value::Object(review.cloned().unwrap_or_default())),
        ("local", Value::Object(local_rest)),
        ("form_drafts", Value::Object(forms)),
        (
            "sync",
            Value::Object(
                as_object(root, "sync", "sync")?
                    .cloned()
                    .unwrap_or_default(),
            ),
        ),
        (
            "account",
            root.get("account").cloned().unwrap_or(Value::Null),
        ),
    ]
    .into_iter()
    .map(|(name, value)| (name.to_owned(), digest_of(&value)))
    .collect();

    let facts = Facts {
        records,
        task_states: count_states(&tasks, "state", "task")?,
        subtask_states: count_states(&subtasks, "state", "subtask")?,
        project_states: count_states(&projects, "state", "project")?,
        tag_states: count_states(&tags, "state", "tag")?,
        tasks_with_project: tasks
            .iter()
            .filter(|task| present(task, "projectID"))
            .count() as u64,
        tag_links,
        parked_tasks: tasks.iter().filter(|task| present(task, "parked")).count() as u64,
        clocked_tasks: tasks
            .iter()
            .filter(|task| present(task, "formulation"))
            .count() as u64,
        lossless_archives: flagged(&projects, "archivedBeforeLossless"),
        edited_comments: comments
            .iter()
            .filter(|comment| present(comment, "editedAt"))
            .count() as u64,
        sections,
    };
    Ok((counts, facts))
}

/// Reads the whole file into a [`Plan`]: nothing is written anywhere.
fn parse(bytes: &[u8], now: &Instant) -> Result<Plan, ImportError> {
    let text = std::str::from_utf8(bytes).map_err(|_| unreadable("encoding"))?;
    reject_duplicate_keys(text).map_err(|_| unreadable("json"))?;
    let root: Value = serde_json::from_str(text).map_err(|_| unreadable("json"))?;
    let version = root
        .get("version")
        .and_then(Value::as_i64)
        .ok_or(unreadable("version"))?;
    if version < 1 {
        return Err(unreadable("version"));
    }
    if version > SUPPORTED_SOURCE_VERSION {
        return Err(ImportError::SourceUnsupported {
            found: Some(version),
            field: Some("version"),
        });
    }
    let (counts, facts) = read_facts(&root)?;

    let mut document = Fields::new(root, "document")?;
    let _ = document.int("version")?;
    let generation = document.int("generation")?;
    let mut base = Fields::new(document.required("base")?, "base")?;
    let tasks = base.object("tasks")?;
    let projects = base.object("projects")?;
    let tags = base.object("tags")?;
    // Version 1 documents have no `review`, and a document may omit `local`.
    let review = match base.take("review") {
        None => Map::new(),
        Some(Value::Object(map)) => map,
        Some(_) => return Err(unreadable("review")),
    };
    base.finish()?;
    let outbox = optional_array(&mut document, "outbox")?;
    let issues = optional_array(&mut document, "issues")?;
    let account = document.take("account");
    let sync = optional_object(&mut document, "sync")?;
    let mut local = optional_object(&mut document, "local")?;
    document.finish()?;
    let forms = match local.remove("formDrafts") {
        None | Some(Value::Null) => Map::new(),
        Some(Value::Object(map)) => map,
        Some(_) => return Err(unreadable("local")),
    };

    let account_id = match &account {
        None => None,
        Some(Value::Object(map)) => match map.get("id") {
            Some(Value::String(id)) if !id.is_empty() => Some(id.clone()),
            _ => return Err(unreadable("account")),
        },
        Some(_) => return Err(unreadable("account")),
    };
    let mut builder = Builder::new(account_id.clone(), now.as_str().to_owned());
    builder.records(tasks, projects, tags)?;

    let at = now.as_str();
    builder.verbatim("legacy-review-base", KIND_REVIEW, Value::Object(review), at);
    builder.verbatim("legacy-local-review", KIND_LOCAL, Value::Object(local), at);
    builder.verbatim("legacy-sync-metadata", KIND_SYNC, Value::Object(sync), at);
    if let Some(account) = account {
        builder.verbatim("legacy-account", KIND_ACCOUNT, account, at);
    }
    for (key, form) in forms {
        let saved = form
            .get("savedAt")
            .and_then(Value::as_str)
            .ok_or(unreadable("local"))?
            .to_owned();
        builder.carriers.push(Carrier {
            draft_id: format!("legacy-form:{key}"),
            editor_kind: KIND_FORM.to_owned(),
            record_type: Some("review_form".to_owned()),
            record_key: Some(key),
            fields: form,
            updated_at: saved,
        });
    }
    for (index, entry) in outbox.into_iter().enumerate() {
        let id = entry
            .get("id")
            .and_then(Value::as_str)
            .ok_or(unreadable("outbox"))?
            .to_owned();
        let issued = entry
            .get("issuedAt")
            .and_then(Value::as_str)
            .unwrap_or(at)
            .to_owned();
        builder.carriers.push(Carrier {
            draft_id: format!("legacy-outbox:{index:08}"),
            editor_kind: KIND_OUTBOX.to_owned(),
            record_type: Some("pending_operation".to_owned()),
            record_key: Some(id),
            fields: entry,
            updated_at: issued,
        });
    }
    for (index, entry) in issues.into_iter().enumerate() {
        let occurred = entry
            .get("occurredAt")
            .and_then(Value::as_str)
            .unwrap_or(at)
            .to_owned();
        if !entry.is_object() {
            return Err(unreadable("issues"));
        }
        builder.carriers.push(Carrier {
            draft_id: format!("legacy-issue:{index:08}"),
            editor_kind: KIND_ISSUE.to_owned(),
            record_type: Some("sync_issue".to_owned()),
            record_key: None,
            fields: entry,
            updated_at: occurred,
        });
    }

    let local_task_facts = builder.local_task_facts;
    Ok(Plan {
        source_sha256: hex(&sha256(bytes)),
        source_bytes: bytes.len() as u64,
        version,
        generation,
        changes: builder.changes,
        aliases: builder.aliases,
        carriers: builder.carriers,
        account_id,
        counts,
        local_task_facts,
        facts,
    })
}

fn optional_array(document: &mut Fields, key: &str) -> Result<Vec<Value>, ImportError> {
    match document.take(key) {
        None => Ok(Vec::new()),
        Some(Value::Array(items)) => Ok(items),
        Some(_) => Err(unreadable("document")),
    }
}

fn optional_object(document: &mut Fields, key: &str) -> Result<Map<String, Value>, ImportError> {
    match document.take(key) {
        None => Ok(Map::new()),
        Some(Value::Object(map)) => Ok(map),
        Some(_) => Err(unreadable("document")),
    }
}

// ----------------------------------------------------------------- the record builder

/// Local ID to record key, for the three kinds a record can refer to.
#[derive(Default)]
struct Keys {
    tasks: BTreeMap<String, String>,
    projects: BTreeMap<String, String>,
    tags: BTreeMap<String, String>,
}

struct Builder {
    actor: String,
    now: String,
    keys: Keys,
    seen: HashSet<(&'static str, String)>,
    changes: Vec<Change>,
    aliases: Vec<Alias>,
    carriers: Vec<Carrier>,
    local_task_facts: u64,
}

fn server_revision(revision: Option<i64>) -> Result<u64, ImportError> {
    match revision {
        None => Ok(0),
        Some(value) => u64::try_from(value).map_err(|_| inconsistent("revision")),
    }
}

/// Checks `value` against the rules' own record type and refuses any change the
/// typed form would make: an import never edits what it carries.
fn typed(entity: EntityType, value: Map<String, Value>) -> Result<Map<String, Value>, ImportError> {
    let original = Value::Object(value);
    let canonical = match entity {
        EntityType::Task => canonical::<Task>(&original),
        EntityType::Project => canonical::<Project>(&original),
        EntityType::Tag => canonical::<Tag>(&original),
        EntityType::Subtask => canonical::<Subtask>(&original),
        EntityType::Comment => canonical::<Comment>(&original),
        _ => None,
    };
    match (canonical, original) {
        (Some(canonical), Value::Object(map)) if canonical == Value::Object(map.clone()) => Ok(map),
        _ => Err(inconsistent("record")),
    }
}

fn canonical<T: serde::de::DeserializeOwned + Serialize>(value: &Value) -> Option<Value> {
    let record: T = serde_json::from_value(value.clone()).ok()?;
    serde_json::to_value(record).ok()
}

impl Builder {
    fn new(account_id: Option<String>, now: String) -> Self {
        Self {
            actor: account_id.unwrap_or_else(|| LOCAL_ACTOR.to_owned()),
            now,
            keys: Keys::default(),
            seen: HashSet::new(),
            changes: Vec::new(),
            aliases: Vec::new(),
            carriers: Vec::new(),
            local_task_facts: 0,
        }
    }

    fn verbatim(&mut self, draft_id: &str, kind: &str, fields: Value, updated_at: &str) {
        self.carriers.push(Carrier {
            draft_id: draft_id.to_owned(),
            editor_kind: kind.to_owned(),
            record_type: None,
            record_key: None,
            fields,
            updated_at: updated_at.to_owned(),
        });
    }

    /// Reserves `(entity, key)`: a key claimed twice would make two records one.
    fn claim(&mut self, entity: EntityType, key: &str) -> Result<(), ImportError> {
        if self.seen.insert((entity.as_str(), key.to_owned())) {
            Ok(())
        } else {
            Err(inconsistent("duplicate_identity"))
        }
    }

    /// Records a proven server ID for a local one.
    fn alias(&mut self, entity: EntityType, local: &str, server: Option<&str>) {
        if let Some(server) = server
            && server != local
        {
            self.aliases.push(Alias {
                entity_type: entity.as_str().to_owned(),
                old_local_id: local.to_owned(),
                server_id: server.to_owned(),
            });
        }
    }

    fn push(
        &mut self,
        entity: EntityType,
        key: &str,
        revision: u64,
        value: Map<String, Value>,
    ) -> Result<(), ImportError> {
        self.claim(entity, key)?;
        let value = typed(entity, value)?;
        self.changes.push(Change {
            entity_type: entity,
            record_key: vec![key.to_owned()],
            record_version: Counter::from(IMPORTED_VERSION),
            edit_revision: Some(Counter::from(revision)),
            operation: Operation::Upsert,
            value: Some(value),
        });
        Ok(())
    }

    /// First pass: every identity, so a relation can be resolved by identity alone.
    fn index(
        entries: &Map<String, Value>,
        entity: EntityType,
        section: &'static str,
    ) -> Result<BTreeMap<String, String>, ImportError> {
        let mut keys = BTreeMap::new();
        for (map_key, entry) in entries {
            let id = entry
                .get("id")
                .and_then(Value::as_str)
                .ok_or(unreadable(section))?;
            if id != map_key {
                return Err(inconsistent(section));
            }
            let server = match entry.get("serverID") {
                None | Some(Value::Null) => None,
                Some(Value::String(server)) if !server.is_empty() => Some(server.as_str()),
                Some(_) => return Err(inconsistent(section)),
            };
            keys.insert(id.to_owned(), legacy_record_key(entity, id, server));
        }
        Ok(keys)
    }

    fn records(
        &mut self,
        tasks: Map<String, Value>,
        projects: Map<String, Value>,
        tags: Map<String, Value>,
    ) -> Result<(), ImportError> {
        self.keys.tasks = Self::index(&tasks, EntityType::Task, "task")?;
        self.keys.projects = Self::index(&projects, EntityType::Project, "project")?;
        self.keys.tags = Self::index(&tags, EntityType::Tag, "tag")?;
        for project in projects.into_values() {
            self.project(project)?;
        }
        for tag in tags.into_values() {
            self.tag(tag)?;
        }
        for task in tasks.into_values() {
            self.task(task)?;
        }
        Ok(())
    }

    fn project(&mut self, value: Value) -> Result<(), ImportError> {
        let mut f = Fields::new(value, "project")?;
        let id = f.text("id")?;
        let server = f.opt_text("serverID")?;
        let revision = server_revision(f.opt_int("serverRevision")?)?;
        let key = self.keys.projects[&id].clone();
        let name = f.text("name")?;
        let color = f.opt_text("color")?;
        let state = f.text("state")?;
        let created = f.text("createdAt")?;
        let outcome = f.opt_text("desiredOutcome")?;
        let archived = f.opt_text("archivedAt")?;
        let lossless = f.flag("archivedBeforeLossless")?;
        f.finish()?;
        let body = json!({
            "id": key, "name": name, "color": color, "state": state,
            "revision": revision.to_string(), "desired_outcome": outcome,
            "archived_at": archived, "archived_before_lossless": lossless, "created_at": created,
        });
        let Value::Object(body) = body else {
            return Err(unreadable("project"));
        };
        self.alias(EntityType::Project, &id, server.as_deref());
        self.push(EntityType::Project, &key, revision, body)
    }

    fn tag(&mut self, value: Value) -> Result<(), ImportError> {
        let mut f = Fields::new(value, "tag")?;
        let id = f.text("id")?;
        let server = f.opt_text("serverID")?;
        let revision = server_revision(f.opt_int("serverRevision")?)?;
        let key = self.keys.tags[&id].clone();
        let name = f.text("name")?;
        let state = f.text("state")?;
        let created = f.text("createdAt")?;
        f.finish()?;
        let body = json!({
            "id": key, "name": name, "state": state, "revision": revision.to_string(),
            "created_at": created,
        });
        let Value::Object(body) = body else {
            return Err(unreadable("tag"));
        };
        self.alias(EntityType::Tag, &id, server.as_deref());
        self.push(EntityType::Tag, &key, revision, body)
    }

    fn task(&mut self, value: Value) -> Result<(), ImportError> {
        let mut f = Fields::new(value, "task")?;
        let id = f.text("id")?;
        let server = f.opt_text("serverID")?;
        let revision = server_revision(f.opt_int("serverRevision")?)?;
        let key = self.keys.tasks[&id].clone();
        let title = f.text("title")?;
        let details = f.opt_text("details")?;
        let state = f.text("state")?;
        let last_open_list = f.opt_text("lastOpenList")?;
        let project = match f.opt_text("projectID")? {
            None => Value::Null,
            Some(local) => json!(
                self.keys
                    .projects
                    .get(&local)
                    .ok_or(inconsistent("task_project"))?
            ),
        };
        let mut tag_keys = Vec::new();
        for local in f.texts("tagIDs")? {
            tag_keys.push(
                self.keys
                    .tags
                    .get(&local)
                    .ok_or(inconsistent("task_tag"))?
                    .clone(),
            );
        }
        let due = f.opt_text("dueDate")?;
        let priority = f.text("priority")?;
        let waiting_for = f.opt_text("waitingFor")?;
        let waiting_since = f.opt_text("waitingSince")?;
        let completed = f.opt_text("completedAt")?;
        let cancelled = f.opt_text("cancelledAt")?;
        let order_key = u64::try_from(f.int("orderKey")?).map_err(|_| inconsistent("order_key"))?;
        let created = f.text("createdAt")?;
        let updated = f.text("updatedAt")?;
        let subtasks = f.array("subtasks")?;
        let comments = f.array("comments")?;
        let children_synced = f.opt_text("childrenSyncedAt")?;
        let formulation = f.take("formulation");
        let stalled = f.opt_int("consecutiveStalledFormulations")?.unwrap_or(0);
        let parked = f.take("parked");
        f.finish()?;

        let clock = formulation.map(clock_wire).transpose()?;
        let park = parked.map(park_wire).transpose()?;
        let body = json!({
            "id": key, "title": title, "details": details, "state": state, "project_id": project,
            "tag_ids": tag_keys, "due_date": due, "priority": priority, "waiting_for": waiting_for,
            "waiting_since": waiting_since, "order_key": order_key.to_string(),
            "source_capture_ids": [], "created_at": created, "updated_at": updated,
            "completed_at": completed, "cancelled_at": cancelled, "revision": revision.to_string(),
            "consecutive_stalled_formulations": stalled, "formulation": clock,
            "parked": park.as_ref().map(|park| &park.public),
        });
        let Value::Object(body) = body else {
            return Err(unreadable("task"));
        };
        self.alias(EntityType::Task, &id, server.as_deref());
        self.push(EntityType::Task, &key, revision, body)?;

        let mut local = Map::new();
        if let Some(list) = last_open_list {
            local.insert("lastOpenList".to_owned(), json!(list));
        }
        if let Some(synced) = children_synced {
            local.insert("childrenSyncedAt".to_owned(), json!(synced));
        }
        if let Some(verbatim) = park.and_then(|park| park.verbatim) {
            local.insert("parked".to_owned(), verbatim);
        }
        if !local.is_empty() {
            self.local_task_facts += 1;
            let at = self.now.clone();
            self.carriers.push(Carrier {
                draft_id: format!("legacy-task-local:{key}"),
                editor_kind: KIND_TASK_LOCAL.to_owned(),
                record_type: Some("task".to_owned()),
                record_key: Some(json!([key]).to_string()),
                fields: Value::Object(local),
                updated_at: at,
            });
        }
        for subtask in subtasks {
            self.subtask(subtask, &key)?;
        }
        for comment in comments {
            self.comment(comment, &key)?;
        }
        Ok(())
    }

    fn subtask(&mut self, value: Value, task_key: &str) -> Result<(), ImportError> {
        let mut f = Fields::new(value, "subtask")?;
        let id = f.text("id")?;
        let server = f.opt_text("serverID")?;
        let revision = server_revision(f.opt_int("serverRevision")?)?;
        let key = legacy_record_key(EntityType::Subtask, &id, server.as_deref());
        let title = f.text("title")?;
        let state = f.text("state")?;
        let order_key = u64::try_from(f.int("orderKey")?).map_err(|_| inconsistent("order_key"))?;
        f.finish()?;
        let body = json!({
            "id": key, "task_id": task_key, "title": title, "state": state,
            "order_key": order_key.to_string(), "revision": revision.to_string(),
        });
        let Value::Object(body) = body else {
            return Err(unreadable("subtask"));
        };
        self.alias(EntityType::Subtask, &id, server.as_deref());
        self.push(EntityType::Subtask, &key, revision, body)
    }

    fn comment(&mut self, value: Value, task_key: &str) -> Result<(), ImportError> {
        let mut f = Fields::new(value, "comment")?;
        let id = f.text("id")?;
        let server = f.opt_text("serverID")?;
        let revision = server_revision(f.opt_int("serverRevision")?)?;
        let key = legacy_record_key(EntityType::Comment, &id, server.as_deref());
        let text = f.text("body")?;
        let author = f
            .opt_text("authorID")?
            .unwrap_or_else(|| self.actor.clone());
        let created = f.text("createdAt")?;
        let edited = f.opt_text("editedAt")?;
        f.finish()?;
        let body = json!({
            "id": key, "task_id": task_key, "body": text, "actor_id": author,
            "created_at": created, "edited_at": edited, "revision": revision.to_string(),
        });
        let Value::Object(body) = body else {
            return Err(unreadable("comment"));
        };
        self.alias(EntityType::Comment, &id, server.as_deref());
        self.push(EntityType::Comment, &key, revision, body)
    }
}

/// The wire form of a formulation clock.
fn clock_wire(value: Value) -> Result<Value, ImportError> {
    let mut f = Fields::new(value, "formulation")?;
    let id = f.text("id")?;
    let started = f.text("startedAt")?;
    let extended = f.opt_text("extendedAt")?;
    let reason = f.opt_text("extensionReason")?;
    let floor = f.opt_text("parkFloorAt")?;
    f.finish()?;
    Ok(json!({
        "id": id, "started_at": started, "extended_at": extended,
        "extension_reason": reason, "park_floor_at": floor,
    }))
}

/// A park marker as the file held it.
struct Park {
    /// The public marker the task record carries.
    public: Value,
    /// The marker verbatim, kept as a local fact when it has a private part (the
    /// revision and the clock before it, which only this device knows).
    verbatim: Option<Value>,
}

fn park_wire(marker: Value) -> Result<Park, ImportError> {
    let raw = marker.clone();
    let mut f = Fields::new(marker, "parked")?;
    let at = f.text("at")?;
    let formulation = f.text("formulationID")?;
    let from_revision = f.opt_int("fromRevision")?;
    let clock_before = f.take("clockBefore");
    let stalled_before = f.opt_int("stalledBefore")?.unwrap_or(0);
    f.finish()?;
    let has_clock = clock_before.is_some();
    if let Some(clock) = clock_before {
        clock_wire(clock)?;
    }
    let private = from_revision.is_some() || has_clock || stalled_before != 0;
    Ok(Park {
        public: json!({"at": at, "formulation_id": formulation}),
        verbatim: private.then_some(raw),
    })
}

// ------------------------------------------------------------------------ the backup

/// What the backup step wrote.
struct Backup {
    backup_file: String,
    manifest_file: String,
}

fn write_backup(request: &ImportRequest, bytes: &[u8], plan: &Plan) -> Result<Backup, ImportError> {
    let digest = plan.source_sha256.as_str();
    let directory = match &request.backup_dir {
        Some(directory) => directory.clone(),
        None => request
            .source
            .parent()
            .map_or_else(|| PathBuf::from("."), Path::to_path_buf),
    };
    fs::create_dir_all(&directory)?;
    let stem = request
        .source
        .file_stem()
        .map_or_else(|| "store".to_owned(), |s| s.to_string_lossy().into_owned());
    let short = &digest[..16];
    let backup_file = format!("{stem}.pre-rust-{short}.json");
    let manifest_file = format!("{stem}.pre-rust-{short}.manifest.json");
    let manifest = json!({
        "schema": MANIFEST_SCHEMA,
        "source_version": plan.version,
        "source_generation": plan.generation,
        "source_bytes": bytes.len(),
        "source_sha256": digest,
        "backup_file": backup_file,
        "counts": plan.counts,
        "sections": plan.facts.sections,
        "records": plan.facts.records,
    });
    write_durably(&directory.join(&backup_file), bytes)?;
    write_durably(
        &directory.join(&manifest_file),
        serde_json::to_vec_pretty(&manifest)
            .map_err(|_| ImportError::StagingInvalid)?
            .as_slice(),
    )?;
    Ok(Backup {
        backup_file,
        manifest_file,
    })
}

/// Writes `bytes` to `path` owner-only through a temporary file that is flushed
/// before it is renamed over `path`, and flushes the directory. A file already
/// holding exactly these bytes is left alone.
fn write_durably(path: &Path, bytes: &[u8]) -> Result<(), ImportError> {
    if fs::read(path).is_ok_and(|held| held == bytes) {
        return Ok(());
    }
    let directory = path.parent().ok_or(StoreError::Io("path".to_owned()))?;
    let name = path
        .file_name()
        .map_or_else(String::new, |n| n.to_string_lossy().into_owned());
    let temporary = directory.join(format!(".{name}.{}.tmp", std::process::id()));
    let written = (|| -> io::Result<()> {
        let mut file = FileOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(0o600)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        fs::rename(&temporary, path)?;
        File::open(directory)?.sync_all()
    })();
    if written.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    Ok(written?)
}

// ------------------------------------------------------------- staging and activation

/// What is staged beside the change stream: the manifest the activation reads back.
#[derive(Serialize, Deserialize)]
struct Staged {
    schema: String,
    source_sha256: String,
    source_bytes: u64,
    source_version: i64,
    source_generation: i64,
    backup_file: String,
    manifest_file: String,
    imported_at: String,
    stream_pages: u64,
    stream_records: u64,
    stream_bytes: u64,
    stream_sha256: String,
    counts: SourceCounts,
    account_id: Option<String>,
    aliases: Vec<Alias>,
    carriers: Vec<Carrier>,
    local_task_facts: u64,
    facts: Facts,
}

fn stage_and_activate(
    store: &mut Store,
    request: &ImportRequest,
    plan: &Plan,
    backup: &Backup,
    id: &str,
    hook: &mut impl FnMut(ImportStage, &Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<ImportMarker, ImportError> {
    let workspace = request.store.workspace_id.as_str();
    let stream = serde_json::to_vec(&plan.changes).map_err(|_| ImportError::StagingInvalid)?;
    // A stream is never empty (`[]` at least), so there is always a first page.
    let pages: Vec<&[u8]> = stream.chunks(PAGE_BYTES).collect();
    let staged = Staged {
        schema: STAGING_SCHEMA.to_owned(),
        source_sha256: plan.source_sha256.clone(),
        source_bytes: plan.source_bytes,
        source_version: plan.version,
        source_generation: plan.generation,
        backup_file: backup.backup_file.clone(),
        manifest_file: backup.manifest_file.clone(),
        imported_at: request.now.as_str().to_owned(),
        stream_pages: pages.len() as u64,
        stream_records: plan.changes.len() as u64,
        stream_bytes: stream.len() as u64,
        stream_sha256: hex(&sha256(&stream)),
        counts: plan.counts,
        account_id: plan.account_id.clone(),
        aliases: plan.aliases.clone(),
        carriers: plan.carriers.clone(),
        local_task_facts: plan.local_task_facts,
        facts: plan.facts.clone(),
    };
    let manifest = serde_json::to_vec(&staged).map_err(|_| ImportError::StagingInvalid)?;

    // Begin: an earlier attempt that never finished is replaced, its pages with it.
    store.try_write(|tx| -> Result<(), ImportError> {
        tx.execute(
            "DELETE FROM staging_bases
             WHERE workspace_id = ?1 AND activation_id = ?2 AND state <> 'activated'",
            params![workspace, id],
        )?;
        tx.execute(
            "INSERT INTO staging_bases (workspace_id, activation_id, kind, target_generation,
                target_watermark, manifest, manifest_digest, total_pages, state, created_at)
             VALUES (?1, ?2, 'snapshot', '0', '0', ?3, ?4, ?5, 'receiving', ?6)",
            params![
                workspace,
                id,
                manifest,
                sha256(&manifest).as_slice(),
                i64::try_from(pages.len()).map_err(|_| ImportError::StagingInvalid)?,
                request.now.as_str(),
            ],
        )?;
        Ok(())
    })?;
    for (index, page) in pages.iter().enumerate() {
        store.try_write(|tx| -> Result<(), ImportError> {
            tx.execute(
                "INSERT INTO staging_pages (workspace_id, activation_id, page_index, page_digest,
                    body) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![
                    workspace,
                    id,
                    i64::try_from(index).map_err(|_| ImportError::StagingInvalid)?,
                    sha256(page).as_slice(),
                    page
                ],
            )?;
            hook(ImportStage::Staged(index as u64), tx)?;
            Ok(())
        })?;
    }
    store.try_write(|tx| -> Result<(), ImportError> {
        tx.execute(
            "UPDATE staging_bases SET state = 'complete'
             WHERE workspace_id = ?1 AND activation_id = ?2",
            params![workspace, id],
        )?;
        Ok(())
    })?;

    store.try_write(|tx| activate(tx, request, plan, id, hook))
}

fn activate(
    tx: &Transaction<'_>,
    request: &ImportRequest,
    plan: &Plan,
    id: &str,
    hook: &mut impl FnMut(ImportStage, &Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<ImportMarker, ImportError> {
    let workspace = request.store.workspace_id.as_str();
    let row: Option<(Vec<u8>, Vec<u8>, String)> = tx
        .query_row(
            "SELECT manifest, manifest_digest, state FROM staging_bases
             WHERE workspace_id = ?1 AND activation_id = ?2",
            params![workspace, id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()?;
    let Some((manifest, manifest_digest, state)) = row else {
        return Err(ImportError::Superseded);
    };
    if state != "complete" {
        return Err(ImportError::Superseded);
    }
    if sha256(&manifest).as_slice() != manifest_digest.as_slice() {
        return Err(ImportError::StagingInvalid);
    }
    let staged: Staged =
        serde_json::from_slice(&manifest).map_err(|_| ImportError::StagingInvalid)?;
    if staged.schema != STAGING_SCHEMA {
        return Err(ImportError::StagingInvalid);
    }
    // The file must still be the one staged: a writer that changed it since is a
    // writer whose data this import would lose.
    if hex(&sha256(&read_source(&request.source)?)) != staged.source_sha256 {
        return Err(ImportError::SourceChanged);
    }
    if read_marker(tx, workspace)?.is_some() {
        return Err(ImportError::AlreadyImported);
    }
    ensure_untouched(tx)??;

    // The staged stream is verified against its manifest and installed by the code
    // a snapshot uses; any disagreement rolls this whole transaction back.
    stream_pages(
        tx,
        workspace,
        id,
        &Promised {
            page_count: staged.stream_pages,
            record_count: staged.stream_records,
            total_bytes: staged.stream_bytes,
            sha256: &staged.stream_sha256,
        },
        |change| install_change(tx, workspace, change),
    )?;
    for alias in &staged.aliases {
        tx.execute(
            "INSERT INTO identity_aliases (workspace_id, entity_type, old_local_id, server_id,
                provenance) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                workspace,
                alias.entity_type,
                alias.old_local_id,
                alias.server_id,
                ALIAS_PROVENANCE
            ],
        )?;
    }
    for carrier in &staged.carriers {
        tx.execute(
            "INSERT INTO drafts (workspace_id, draft_id, editor_kind, record_type, record_key,
                fields, base_revision, updated_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, NULL, ?7)",
            params![
                workspace,
                carrier.draft_id,
                carrier.editor_kind,
                carrier.record_type,
                carrier.record_key,
                carrier.fields.to_string().into_bytes(),
                carrier.updated_at
            ],
        )?;
    }
    if let Some(account) = &staged.account_id {
        tx.execute(
            "UPDATE sync_meta SET account_id = ?1, account_link_state = 'linked'",
            [account],
        )?;
    }
    let replayed = replay_in(tx, &context(&staged)?)?;
    hook(ImportStage::Installed, tx)?;

    verify(tx, workspace, plan, &staged, &replayed)?;
    hook(ImportStage::Verified, tx)?;

    let marker = ImportMarker {
        schema: MARKER_SCHEMA.to_owned(),
        source_sha256: staged.source_sha256,
        source_bytes: staged.source_bytes,
        source_version: staged.source_version,
        source_generation: staged.source_generation,
        backup_file: staged.backup_file,
        manifest_file: staged.manifest_file,
        imported_at: staged.imported_at,
        counts: staged.counts,
        aliases: staged.aliases.len() as u64,
        local_task_facts: staged.local_task_facts,
    };
    let bytes = serde_json::to_vec(&marker).map_err(|_| ImportError::StagingInvalid)?;
    tx.execute(
        "UPDATE staging_bases SET state = 'activated', manifest = ?3, manifest_digest = ?4
         WHERE workspace_id = ?1 AND activation_id = ?2",
        params![workspace, id, bytes, sha256(&bytes).as_slice()],
    )?;
    tx.execute(
        "DELETE FROM staging_pages WHERE workspace_id = ?1 AND activation_id = ?2",
        params![workspace, id],
    )?;
    Ok(marker)
}

/// The context the projection is rebuilt with. No command is decided (the queue is
/// empty), so only the shape matters.
fn context(staged: &Staged) -> Result<ExecuteContext, ImportError> {
    let actor = staged.account_id.as_deref().unwrap_or(LOCAL_ACTOR);
    Ok(ExecuteContext {
        now: Instant::parse(staged.imported_at.as_str())
            .map_err(|_| ImportError::StagingInvalid)?,
        time_zone: ZoneName::new("UTC").map_err(|_| ImportError::StagingInvalid)?,
        actor_id: ActorId::parse(actor).map_err(|_| ImportError::StagingInvalid)?,
        policy: Policy {
            weekly_review: false,
            navigator_provider: None,
            navigator_available: false,
            consent_text_version: 1,
        },
    })
}

/// The marker row of a finished import: its activation ID and the marker.
fn read_marker(
    tx: &Transaction<'_>,
    workspace: &str,
) -> rusqlite::Result<Option<(String, ImportMarker)>> {
    let row: Option<(String, Vec<u8>)> = tx
        .query_row(
            "SELECT activation_id, manifest FROM staging_bases
             WHERE workspace_id = ?1 AND activation_id LIKE 'legacy-import-%'
               AND state = 'activated'",
            [workspace],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    Ok(row.and_then(|(id, bytes)| {
        serde_json::from_slice::<ImportMarker>(&bytes)
            .ok()
            .map(|marker| (id, marker))
    }))
}

/// The store must hold nothing of its own: an import never merges into live data.
fn ensure_untouched(tx: &Transaction<'_>) -> rusqlite::Result<Result<(), ImportError>> {
    let rows: i64 = tx.query_row(
        "SELECT (SELECT COUNT(*) FROM confirmed_records) + (SELECT COUNT(*) FROM visible_records)
              + (SELECT COUNT(*) FROM outbox) + (SELECT COUNT(*) FROM command_receipts)
              + (SELECT COUNT(*) FROM sync_issues) + (SELECT COUNT(*) FROM drafts)
              + (SELECT COUNT(*) FROM identity_aliases)",
        [],
        |row| row.get(0),
    )?;
    let bound: i64 = tx.query_row(
        "SELECT account_id IS NOT NULL OR scope_id IS NOT NULL OR device_id IS NOT NULL
             OR server_generation IS NOT NULL OR cursor IS NOT NULL OR base_watermark IS NOT NULL
             OR device_epoch_state <> 'none' OR next_local_seq <> 1
             OR account_link_state <> 'unchosen'
         FROM sync_meta",
        [],
        |row| row.get(0),
    )?;
    Ok(if rows == 0 && bound == 0 {
        Ok(())
    } else {
        Err(ImportError::TargetInUse)
    })
}

// ------------------------------------------------------------------------ validation

fn failed(check: &'static str) -> ImportError {
    ImportError::VerificationFailed { check }
}

/// Compares the rows with the source before the marker is flipped. Every reading
/// of the store is taken from SQL or from the rows themselves.
fn verify(
    tx: &Transaction<'_>,
    workspace: &str,
    plan: &Plan,
    staged: &Staged,
    replayed: &crate::replay::Replayed,
) -> Result<(), ImportError> {
    // The reference counts, IDs, links and flags, source against store.
    let live = live_facts(tx, workspace)?;
    if let Some(check) = plan.facts.first_difference(&live) {
        return Err(failed(check));
    }
    if staged.facts != plan.facts {
        return Err(failed("staged_facts"));
    }

    // Every record is, field for field, what the file's record becomes.
    let mut expected: BTreeMap<(String, String), &Map<String, Value>> = BTreeMap::new();
    for change in &plan.changes {
        let Some(value) = &change.value else {
            return Err(failed("records"));
        };
        let key = serde_json::to_string(&change.record_key).map_err(|_| failed("records"))?;
        expected.insert((change.entity_type.as_str().to_owned(), key), value);
    }
    let mut keys: BTreeMap<&str, BTreeSet<String>> = BTreeMap::new();
    let mut rows = 0_usize;
    let mut statement = tx.prepare(
        "SELECT record_type, record_key, record_version, tombstone, body FROM confirmed_records
         WHERE workspace_id = ?1",
    )?;
    let mut cursor = statement.query([workspace])?;
    let mut links: Vec<(String, Vec<String>, Vec<String>)> = Vec::new();
    while let Some(row) = cursor.next()? {
        let (kind, key, version, tombstone, body): (String, String, String, i64, Vec<u8>) = (
            row.get(0)?,
            row.get(1)?,
            row.get(2)?,
            row.get(3)?,
            row.get(4)?,
        );
        rows += 1;
        let value: Value = serde_json::from_slice(&body).map_err(|_| failed("records"))?;
        let want = expected.get(&(kind.clone(), key.clone()));
        if tombstone != 0 || version != IMPORTED_VERSION.to_string() {
            return Err(failed("records"));
        }
        if want.is_none_or(|want| Value::Object((*want).clone()) != value) {
            return Err(failed("records"));
        }
        let id = value
            .get("id")
            .and_then(Value::as_str)
            .ok_or(failed("records"))?
            .to_owned();
        let known = match kind.as_str() {
            "task" => "task",
            "project" => "project",
            "tag" => "tag",
            "subtask" => "subtask",
            "comment" => "comment",
            _ => return Err(failed("records")),
        };
        keys.entry(known).or_default().insert(id.clone());
        let strings = |field: &str| -> Vec<String> {
            value
                .get(field)
                .and_then(Value::as_array)
                .map(|items| {
                    items
                        .iter()
                        .filter_map(|item| item.as_str().map(str::to_owned))
                        .collect()
                })
                .unwrap_or_default()
        };
        let single = |field: &str| -> Vec<String> {
            value
                .get(field)
                .and_then(Value::as_str)
                .map(|item| vec![item.to_owned()])
                .unwrap_or_default()
        };
        match known {
            "task" => links.push((
                "project".to_owned(),
                single("project_id"),
                strings("tag_ids"),
            )),
            "subtask" | "comment" => links.push(("task".to_owned(), single("task_id"), Vec::new())),
            _ => {}
        }
    }
    if rows != expected.len() {
        return Err(failed("records"));
    }
    // Every relation points at a record that exists.
    let empty = BTreeSet::new();
    let among = |kind: &str| keys.get(kind).unwrap_or(&empty);
    for (target, first, tags) in &links {
        if first.iter().any(|key| !among(target).contains(key))
            || tags.iter().any(|key| !among("tag").contains(key))
        {
            return Err(failed("relations"));
        }
    }

    // The aliases are exactly the ones the file proved.
    let mut stored: Vec<Alias> = Vec::new();
    {
        let mut statement = tx.prepare(
            "SELECT entity_type, old_local_id, server_id FROM identity_aliases
             WHERE workspace_id = ?1 AND provenance = ?2",
        )?;
        let found = statement.query_map(params![workspace, ALIAS_PROVENANCE], |row| {
            Ok(Alias {
                entity_type: row.get(0)?,
                old_local_id: row.get(1)?,
                server_id: row.get(2)?,
            })
        })?;
        for alias in found {
            stored.push(alias?);
        }
    }
    let mut wanted = plan.aliases.clone();
    for list in [&mut stored, &mut wanted] {
        list.sort_by(|a, b| {
            (&a.entity_type, &a.old_local_id).cmp(&(&b.entity_type, &b.old_local_id))
        });
    }
    let total: i64 = tx.query_row(
        "SELECT COUNT(*) FROM identity_aliases WHERE workspace_id = ?1",
        [workspace],
        |row| row.get(0),
    )?;
    if stored != wanted || usize::try_from(total).ok() != Some(wanted.len()) {
        return Err(failed("aliases"));
    }

    // The carriers hold exactly what the file's verbatim sections held (their
    // digests are part of the facts above) and one row per local fact.
    let carried: i64 = tx.query_row(
        "SELECT COUNT(*) FROM drafts WHERE workspace_id = ?1",
        [workspace],
        |row| row.get(0),
    )?;
    if usize::try_from(carried).ok() != Some(plan.carriers.len()) {
        return Err(failed("carriers"));
    }

    // The projection is the base: nothing is queued, nothing was rejected.
    let visible: i64 = tx.query_row(
        "SELECT COUNT(*) FROM visible_records WHERE workspace_id = ?1",
        [workspace],
        |row| row.get(0),
    )?;
    if usize::try_from(visible).ok() != Some(plan.changes.len())
        || !replayed.applied.is_empty()
        || !replayed.rejected.is_empty()
        || !replayed.blocked.is_empty()
        || !replayed.deferred.is_empty()
    {
        return Err(failed("replay"));
    }
    let stale: i64 = tx.query_row("SELECT projection_stale FROM sync_meta", [], |row| {
        row.get(0)
    })?;
    if stale != 0 {
        return Err(failed("replay"));
    }
    let broken: i64 = tx.query_row("SELECT COUNT(*) FROM pragma_foreign_key_check", [], |row| {
        row.get(0)
    })?;
    if broken != 0 {
        return Err(failed("foreign_keys"));
    }
    Ok(())
}

fn grouped(
    tx: &Transaction<'_>,
    sql: &str,
    workspace: &str,
) -> rusqlite::Result<BTreeMap<String, u64>> {
    let mut statement = tx.prepare(sql)?;
    let rows = statement.query_map([workspace], |row| {
        Ok((row.get::<_, Option<String>>(0)?, row.get::<_, i64>(1)?))
    })?;
    let mut counts = BTreeMap::new();
    for row in rows {
        let (name, count) = row?;
        counts.insert(name.unwrap_or_default(), u64::try_from(count).unwrap_or(0));
    }
    Ok(counts)
}

fn scalar(tx: &Transaction<'_>, sql: &str, workspace: &str) -> rusqlite::Result<u64> {
    let value: i64 = tx.query_row(sql, [workspace], |row| row.get(0))?;
    Ok(u64::try_from(value).unwrap_or(0))
}

/// The store side of [`Facts`]: SQL aggregates over the rows, and the verbatim
/// sections rebuilt from their carriers.
fn live_facts(tx: &Transaction<'_>, workspace: &str) -> Result<Facts, ImportError> {
    let states = |kind: &str| {
        grouped(
            tx,
            &format!(
                "SELECT json_extract(CAST(body AS TEXT), '$.state'), COUNT(*) FROM confirmed_records
                 WHERE workspace_id = ?1 AND record_type = '{kind}' AND tombstone = 0
                 GROUP BY 1"
            ),
            workspace,
        )
    };
    let on_tasks = |expression: &str| {
        scalar(
            tx,
            &format!(
                "SELECT COALESCE({expression}, 0) FROM confirmed_records
                 WHERE workspace_id = ?1 AND record_type = 'task' AND tombstone = 0"
            ),
            workspace,
        )
    };
    let on_kind = |kind: &str, condition: &str| {
        scalar(
            tx,
            &format!(
                "SELECT COUNT(*) FROM confirmed_records
                 WHERE workspace_id = ?1 AND record_type = '{kind}' AND tombstone = 0
                   AND {condition}"
            ),
            workspace,
        )
    };
    let carried = |kind: &str| -> rusqlite::Result<Vec<Value>> {
        let mut statement = tx.prepare(
            "SELECT fields FROM drafts WHERE workspace_id = ?1 AND editor_kind = ?2
             ORDER BY draft_id",
        )?;
        let rows = statement.query_map(params![workspace, kind], |row| row.get::<_, Vec<u8>>(0))?;
        let mut found = Vec::new();
        for row in rows {
            found.push(serde_json::from_slice(&row?).map_err(|error| {
                rusqlite::Error::FromSqlConversionFailure(
                    0,
                    rusqlite::types::Type::Blob,
                    Box::new(error),
                )
            })?);
        }
        Ok(found)
    };
    let single = |kind: &str| -> rusqlite::Result<Value> {
        Ok(carried(kind)?.into_iter().next().unwrap_or(Value::Null))
    };
    let forms = {
        let mut statement = tx.prepare(
            "SELECT record_key, fields FROM drafts WHERE workspace_id = ?1 AND editor_kind = ?2",
        )?;
        let rows = statement.query_map(params![workspace, KIND_FORM], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
        })?;
        let mut map = Map::new();
        for row in rows {
            let (key, body) = row?;
            map.insert(
                key,
                serde_json::from_slice(&body).map_err(|_| failed("carriers"))?,
            );
        }
        Value::Object(map)
    };
    let sections: BTreeMap<String, String> = [
        ("outbox", Value::Array(carried(KIND_OUTBOX)?)),
        ("issues", Value::Array(carried(KIND_ISSUE)?)),
        ("review", single(KIND_REVIEW)?),
        ("local", single(KIND_LOCAL)?),
        ("form_drafts", forms),
        ("sync", single(KIND_SYNC)?),
        ("account", single(KIND_ACCOUNT)?),
    ]
    .into_iter()
    .map(|(name, value)| (name.to_owned(), digest_of(&value)))
    .collect();

    Ok(Facts {
        records: grouped(
            tx,
            "SELECT record_type, COUNT(*) FROM confirmed_records
             WHERE workspace_id = ?1 AND tombstone = 0 GROUP BY 1",
            workspace,
        )?,
        task_states: states("task")?,
        subtask_states: states("subtask")?,
        project_states: states("project")?,
        tag_states: states("tag")?,
        tasks_with_project: on_kind(
            "task",
            "json_extract(CAST(body AS TEXT), '$.project_id') IS NOT NULL",
        )?,
        tag_links: on_tasks("SUM(json_array_length(CAST(body AS TEXT), '$.tag_ids'))")?,
        parked_tasks: on_kind(
            "task",
            "json_type(CAST(body AS TEXT), '$.parked') = 'object'",
        )?,
        clocked_tasks: on_kind(
            "task",
            "json_type(CAST(body AS TEXT), '$.formulation') = 'object'",
        )?,
        lossless_archives: on_kind(
            "project",
            "json_extract(CAST(body AS TEXT), '$.archived_before_lossless') = 1",
        )?,
        edited_comments: on_kind(
            "comment",
            "json_extract(CAST(body AS TEXT), '$.edited_at') IS NOT NULL",
        )?,
        sections,
    })
}
