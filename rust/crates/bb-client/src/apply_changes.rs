//! Applying the server's change feed to the confirmed base (sync-v1 section 7).
//!
//! The confirmed base changes only here, one **whole** commit-ordered
//! transaction at a time (or, in a later slice, by activating a consistent
//! snapshot). A feed page is applied in a single local write transaction that
//!
//! 1. checks the response against the request fences and the stored server
//!    generation, so a late or foreign response changes nothing;
//! 2. checks the commit sequence: it must continue exactly where the confirmed
//!    base stopped (`watermark + 1`, then `+ 1` again for each transaction on the
//!    page). The scope counter is issued under the writer lock, so a jump means
//!    a transaction the device never saw: [`ApplyError::Gap`] says whether a
//!    refetch can repair it or a snapshot is required, and nothing is saved.
//!    Transactions at or below the watermark are duplicates and are skipped;
//! 3. installs every change of every transaction (a tombstone is a row, so a
//!    deletion stays final), refusing a record version that does not advance;
//! 4. matches each transaction's source command to the outbox: that command's
//!    result is now part of the confirmed base, so it is `completed`;
//! 5. replays the commands still pending over the new base
//!    ([`crate::replay::replay_in`]) and stores the cursor and watermark.
//!
//! All of it commits together or not at all, so a crash leaves either the old
//! base and cursor or the new ones, never a transaction half applied.
//!
//! A transaction too large for a page arrives as a manifest and byte pages
//! (sync-v1 section 11). The pages are verified one by one into staging
//! (`staging_bases`/`staging_pages`), which is never the active base; only the
//! completed, digest-checked stream is applied, by the same install, match,
//! replay and cursor code and in the same single transaction as an inline one.
//! The stream is decoded incrementally inside that transaction, one page and one
//! record in flight at a time, so a transaction of any size needs no more memory
//! than its largest record, and a failed check rolls everything back.
//!
//! A command receipt never writes after-images and never moves the cursor: see
//! [`crate::receipts`].

use crate::execute::{ExecuteContext, Sha256, edit_revision, record_from, sha256};
use crate::replay::{ReplayError, Replayed, replay_in};
use crate::storage::{Store, StoreError};
use bb_domain::calendar::UtcInstant;
use bb_protocol::feed::{
    BytePage, Change, ChangeStreamDecoder, ChangesPage, Operation, Transaction as FeedTransaction,
    TransferManifest, TransferPage,
};
use bb_protocol::wire::{CommandId, CommonResponse, Id, Instant, Wire};
use rusqlite::{OptionalExtension, Transaction, params};
use serde::{Deserialize, Serialize};

/// The largest decoded chunk of an oversized transaction (sync-v1 section 11).
const MAX_CHUNK_BYTES: usize = 1 << 20;

// ------------------------------------------------------------------------- errors

/// What the caller must do after a gap or a reset.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Recovery {
    /// Ask the feed again from the stored cursor: the page was stale or out of
    /// order, and the device is not known to be missing anything.
    Refetch,
    /// The feed itself skipped (or went backwards): rebuild the base from a
    /// snapshot. Pending work is preserved.
    Snapshot,
}

/// Why a staged oversized transaction could not be applied.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TransferFault {
    /// No such transfer is staged (never announced, abandoned or applied).
    Unknown,
    /// A page failed its index, size, continuation or digest check; it was not
    /// kept. Fetch it again.
    PageCorrupt { page_index: u64 },
    /// Pages are still missing. Fetch them; nothing was applied.
    Incomplete { missing: Vec<u64> },
    /// The transfer passed its expiry. The staging was discarded.
    Expired,
    /// The assembled stream does not match its manifest. The staging was
    /// discarded.
    Corrupt,
    /// A different manifest or page content for a transfer already staged. The
    /// staging was discarded.
    Conflict,
}

impl TransferFault {
    /// Whether the staged bytes are worthless and are dropped.
    pub(crate) fn discards(&self) -> bool {
        matches!(self, Self::Expired | Self::Corrupt | Self::Conflict)
    }
}

/// Why a feed page, a transfer or a receipt was not applied. Whatever it is,
/// nothing of it was saved (a discarded staging is the only thing removed).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ApplyError {
    Store(StoreError),
    /// The response belongs to an earlier request generation: ignore it.
    Stale,
    /// There is no confirmed base (or scope) yet: a snapshot is required first.
    NoBase,
    /// The response is for another scope.
    WrongScope,
    /// The server generation is not the one the base was built from: reset.
    GenerationChanged,
    /// The commit sequence does not continue the confirmed base.
    Gap {
        expected: u64,
        found: u64,
        recovery: Recovery,
    },
    /// The response breaks a rule of the contract.
    Malformed(&'static str),
    /// The server's data contradicts what the device already holds.
    Contradiction(&'static str),
    Transfer(TransferFault),
    /// The command is not in this workspace's outbox.
    UnknownCommand,
    /// The command was never sent, so no receipt can be for it.
    NeverSent,
    Replay(ReplayError),
}

impl ApplyError {
    /// The stable code the bindings carry across FFI.
    pub fn code(&self) -> &'static str {
        match self {
            Self::Store(error) => error.code(),
            Self::Stale => "STALE_RESPONSE",
            Self::NoBase => "SNAPSHOT_REQUIRED",
            Self::WrongScope => "WRONG_SCOPE",
            Self::GenerationChanged => "RESET_REQUIRED",
            Self::Gap { .. } => "FEED_GAP",
            Self::Malformed(_) => "INVALID_RESPONSE",
            Self::Contradiction(_) => "SYNC_CONTRADICTION",
            Self::Transfer(TransferFault::Expired) => "RESET_REQUIRED",
            Self::Transfer(TransferFault::Incomplete { .. }) => "TRANSFER_INCOMPLETE",
            Self::Transfer(_) => "TRANSFER_INVALID",
            Self::UnknownCommand => "UNKNOWN_COMMAND",
            Self::NeverSent => "COMMAND_NOT_SENT",
            Self::Replay(error) => error.code(),
        }
    }

    /// How to recover, for the errors that have a recovery.
    pub fn recovery(&self) -> Option<Recovery> {
        match self {
            Self::Gap { recovery, .. } => Some(*recovery),
            Self::NoBase
            | Self::GenerationChanged
            | Self::Contradiction(_)
            | Self::Transfer(TransferFault::Expired | TransferFault::Corrupt) => {
                Some(Recovery::Snapshot)
            }
            Self::Transfer(
                TransferFault::Incomplete { .. } | TransferFault::PageCorrupt { .. },
            ) => Some(Recovery::Refetch),
            _ => None,
        }
    }

    pub fn is_retryable(&self) -> bool {
        matches!(self, Self::Store(error) if error.is_retryable())
    }
}

impl std::fmt::Display for ApplyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}

impl std::error::Error for ApplyError {}

impl From<StoreError> for ApplyError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}

impl From<rusqlite::Error> for ApplyError {
    fn from(error: rusqlite::Error) -> Self {
        Self::Store(error.into())
    }
}

impl From<ReplayError> for ApplyError {
    fn from(error: ReplayError) -> Self {
        match error {
            ReplayError::Store(error) => Self::Store(error),
            other => Self::Replay(other),
        }
    }
}

// -------------------------------------------------------------------- the base

/// The request generations a response was issued under (sync-v1 section 7). A
/// response is applied only while they are still the store's: the check runs
/// inside the applying transaction, so a restart or reset cannot slip between.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Fence {
    pub workspace_generation: u64,
    pub session_generation: u64,
    pub local_sync_generation: u64,
}

/// The fences as they stand now: what a request captures when it is sent.
///
/// # Errors
///
/// [`StoreError`] when the store cannot be read.
pub fn capture_fence(store: &mut Store) -> Result<Fence, StoreError> {
    store.read(|tx| {
        tx.query_row(
            "SELECT workspace_generation, session_generation, local_sync_generation
             FROM sync_meta",
            [],
            |row| {
                Ok(Fence {
                    workspace_generation: unsigned(row.get(0)?),
                    session_generation: unsigned(row.get(1)?),
                    local_sync_generation: unsigned(row.get(2)?),
                })
            },
        )
    })
}

pub(crate) fn unsigned(value: i64) -> u64 {
    u64::try_from(value).unwrap_or(0)
}

/// What a response is checked against.
pub(crate) struct Base {
    pub workspace_id: String,
    scope_id: Option<String>,
    server_generation: Option<String>,
    cursor: Option<String>,
    watermark: Option<u64>,
}

impl Base {
    /// The cursor and watermark of the confirmed base.
    pub(crate) fn feed(&self) -> Result<(&str, u64), ApplyError> {
        match (&self.cursor, self.watermark) {
            (Some(cursor), Some(watermark)) => Ok((cursor, watermark)),
            _ => Err(ApplyError::NoBase),
        }
    }

    pub(crate) fn watermark(&self) -> Option<u64> {
        self.watermark
    }

    pub(crate) fn scope_id(&self) -> Option<&str> {
        self.scope_id.as_deref()
    }

    pub(crate) fn server_generation(&self) -> Option<&str> {
        self.server_generation.as_deref()
    }
}

/// Reads the store's fences and base, refusing a response from an earlier
/// generation.
pub(crate) fn read_base(tx: &Transaction<'_>, fence: &Fence) -> Result<Base, ApplyError> {
    #[allow(clippy::type_complexity)]
    let row: (
        String,
        Option<String>,
        Option<String>,
        Option<String>,
        Option<String>,
        [i64; 3],
    ) = tx.query_row(
        "SELECT workspace_id, scope_id, server_generation, cursor, base_watermark,
                workspace_generation, session_generation, local_sync_generation
         FROM sync_meta",
        [],
        |row| {
            Ok((
                row.get(0)?,
                row.get(1)?,
                row.get(2)?,
                row.get(3)?,
                row.get(4)?,
                [row.get(5)?, row.get(6)?, row.get(7)?],
            ))
        },
    )?;
    let (workspace_id, scope_id, server_generation, cursor, watermark, generations) = row;
    let [workspace, session, local_sync] = generations.map(unsigned);
    if (workspace, session, local_sync)
        != (
            fence.workspace_generation,
            fence.session_generation,
            fence.local_sync_generation,
        )
    {
        return Err(ApplyError::Stale);
    }
    let watermark = watermark
        .map(|text| {
            bb_protocol::wire::Counter::parse(text)
                .ok()
                .and_then(|counter| counter.to_u64())
                .ok_or(ApplyError::Store(StoreError::Corrupt))
        })
        .transpose()?;
    Ok(Base {
        workspace_id,
        scope_id,
        server_generation,
        cursor,
        watermark,
    })
}

/// The response is for this scope and the generation the base was built from.
pub(crate) fn check_common(base: &Base, common: &CommonResponse) -> Result<(), ApplyError> {
    let (Some(scope), Some(generation)) = (&base.scope_id, &base.server_generation) else {
        return Err(ApplyError::NoBase);
    };
    if common.scope_id.as_str() != scope {
        return Err(ApplyError::WrongScope);
    }
    if common.server_generation.as_str() != generation {
        return Err(ApplyError::GenerationChanged);
    }
    Ok(())
}

// ----------------------------------------------------------------- the feed page

/// The points inside the write transaction where a test can fail or kill the
/// process to prove nothing partial survives.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ApplyStage {
    /// The changes are installed and their commands matched; replay is next.
    Installed,
    /// Replay, the cursor and the watermark are written; only the commit is left.
    Replayed,
}

/// What one applied page (or transfer) did.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Applied {
    /// Transactions installed by this call.
    pub transactions: u64,
    /// Transactions already in the base, skipped as duplicates.
    pub skipped: u64,
    /// Commands the transactions proved part of the confirmed base.
    pub completed: Vec<CommandId>,
    /// The cursor to ask the feed from next.
    pub cursor: String,
    /// The commit sequence the confirmed base now reaches.
    pub watermark: u64,
    /// The latest committed sequence the server reported.
    pub high_watermark: u64,
    /// Whether the server has further transactions to deliver.
    pub has_more: bool,
    /// The replay that followed, when anything was installed.
    pub replayed: Option<Replayed>,
}

/// The result of one feed page.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FeedStep {
    /// Applied (or recognised as a duplicate or an empty catch-up).
    Applied(Applied),
    /// The next transaction is too large for a page: fetch this transfer's
    /// byte pages, stage them with [`stage_transfer_page`], then call
    /// [`apply_transfer`].
    Transfer(Id),
}

/// Applies one `GET changes` page. See the module documentation.
///
/// # Errors
///
/// [`ApplyError`]; whatever it is, nothing of the page was saved.
pub fn apply_changes(
    store: &mut Store,
    context: &ExecuteContext,
    fence: &Fence,
    page: &ChangesPage,
) -> Result<FeedStep, ApplyError> {
    apply_changes_with(store, context, fence, page, |_, _| Ok(()))
}

/// [`apply_changes`] with a hook that runs inside the transaction at each
/// [`ApplyStage`]. An `Err` from the hook rolls the page back; a hook that
/// kills the process leaves an uncommitted transaction for SQLite to discard.
///
/// # Errors
///
/// As [`apply_changes`].
pub fn apply_changes_with(
    store: &mut Store,
    context: &ExecuteContext,
    fence: &Fence,
    page: &ChangesPage,
    mut hook: impl FnMut(ApplyStage, &Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<FeedStep, ApplyError> {
    store.try_write(|tx| page_in(tx, context, fence, page, &mut hook))
}

fn gap(expected: u64, found: u64, cursor_matches: bool) -> ApplyError {
    ApplyError::Gap {
        expected,
        found,
        recovery: if cursor_matches {
            Recovery::Snapshot
        } else {
            Recovery::Refetch
        },
    }
}

fn counter(counter: &bb_protocol::wire::Counter, what: &'static str) -> Result<u64, ApplyError> {
    counter.to_u64().ok_or(ApplyError::Malformed(what))
}

fn page_in(
    tx: &Transaction<'_>,
    context: &ExecuteContext,
    fence: &Fence,
    page: &ChangesPage,
    hook: &mut impl FnMut(ApplyStage, &Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<FeedStep, ApplyError> {
    let base = read_base(tx, fence)?;
    check_common(&base, &page.common)?;
    page.validate()
        .map_err(|_| ApplyError::Malformed("changes page"))?;
    let (cursor, watermark) = base.feed()?;
    let cursor_matches = page.from_cursor == cursor;
    let high = counter(&page.high_watermark, "high_watermark")?;
    let unchanged = |skipped: u64| {
        FeedStep::Applied(Applied {
            transactions: 0,
            skipped,
            completed: Vec::new(),
            cursor: cursor.to_owned(),
            watermark,
            high_watermark: high,
            has_more: page.has_more,
            replayed: None,
        })
    };

    if let Some(manifest) = &page.transaction_manifest {
        // The manifest names the immediate next transaction.
        let seq = counter(&manifest.commit_seq, "commit_seq")?;
        if seq <= watermark {
            return Ok(unchanged(1)); // already applied: a late duplicate
        }
        if seq != watermark + 1 {
            return Err(gap(watermark + 1, seq, cursor_matches));
        }
        if high < seq {
            return Err(ApplyError::Malformed("high_watermark behind the manifest"));
        }
        return Ok(FeedStep::Transfer(stage_manifest(
            tx,
            context,
            &base,
            manifest,
            &page.common.server_now,
        )?));
    }

    // Duplicates are the prefix at or below the watermark; the rest must
    // continue the base one sequence at a time.
    let (mut next, mut skipped) = (watermark + 1, 0);
    let mut fresh: Vec<&FeedTransaction> = Vec::new();
    for transaction in &page.transactions {
        let seq = counter(&transaction.commit_seq, "commit_seq")?;
        if fresh.is_empty() && seq <= watermark {
            skipped += 1;
        } else if seq == next {
            fresh.push(transaction);
            next += 1;
        } else {
            return Err(gap(next, seq, cursor_matches));
        }
    }
    let last = next - 1;

    if fresh.is_empty() {
        if skipped > 0 || !cursor_matches {
            return Ok(unchanged(skipped)); // stale or duplicate: never moves the base
        }
        // A valid empty page at the stored cursor confirms catch-up, and only
        // when the server agrees there is nothing beyond it.
        if page.has_more {
            return Err(ApplyError::Malformed("an empty page that has more"));
        }
        if high != watermark {
            return Err(gap(watermark + 1, high, true));
        }
        tx.execute(
            "UPDATE sync_meta SET last_success_at = ?1",
            [context.now.as_str()],
        )?;
        return Ok(unchanged(0));
    }
    if high < last {
        return Err(ApplyError::Malformed("high_watermark behind the page"));
    }
    if !page.has_more && high != last {
        return Err(gap(last + 1, high, cursor_matches));
    }

    let mut completed = Vec::new();
    for transaction in &fresh {
        completed.extend(install_in(tx, &base.workspace_id, transaction)?);
    }
    hook(ApplyStage::Installed, tx)?;
    let replayed = finish_in(tx, context, &page.next_cursor, last)?;
    hook(ApplyStage::Replayed, tx)?;
    Ok(FeedStep::Applied(Applied {
        transactions: u64::try_from(fresh.len()).unwrap_or(u64::MAX),
        skipped,
        completed,
        cursor: page.next_cursor.clone(),
        watermark: last,
        high_watermark: high,
        has_more: page.has_more,
        replayed: Some(replayed),
    }))
}

/// Replays the pending queue over the new base and stores the cursor.
pub(crate) fn finish_in(
    tx: &Transaction<'_>,
    context: &ExecuteContext,
    cursor: &str,
    watermark: u64,
) -> Result<Replayed, ApplyError> {
    tx.execute(
        "UPDATE sync_meta SET cursor = ?1, base_watermark = ?2, last_success_at = ?3",
        params![cursor, watermark.to_string(), context.now.as_str()],
    )?;
    Ok(replay_in(tx, context)?)
}

// -------------------------------------------------------------- one transaction

/// Installs one whole transaction and settles its source command; returns the
/// commands it completed.
fn install_in(
    tx: &Transaction<'_>,
    workspace_id: &str,
    transaction: &FeedTransaction,
) -> Result<Vec<CommandId>, ApplyError> {
    transaction
        .validate()
        .map_err(|_| ApplyError::Malformed("transaction"))?;
    for change in &transaction.changes {
        install_change(tx, workspace_id, change)?;
    }
    complete_source(tx, workspace_id, &transaction.source_command_id)
}

/// A canonical decimal counter is newer by length, then by digits.
fn newer(candidate: &str, stored: &str) -> bool {
    (candidate.len(), candidate) > (stored.len(), stored)
}

pub(crate) fn install_change(
    tx: &Transaction<'_>,
    workspace_id: &str,
    change: &Change,
) -> Result<(), ApplyError> {
    let kind = change.entity_type.as_str();
    let key = serde_json::to_string(&change.record_key)
        .map_err(|_| ApplyError::Malformed("record_key"))?;
    let stored: Option<String> = tx
        .query_row(
            "SELECT record_version FROM confirmed_records
             WHERE workspace_id = ?1 AND record_type = ?2 AND record_key = ?3",
            params![workspace_id, kind, key],
            |row| row.get(0),
        )
        .optional()?;
    if let Some(stored) = stored
        && !newer(change.record_version.as_str(), &stored)
    {
        return Err(ApplyError::Contradiction(
            "a record version did not advance",
        ));
    }
    let (revision, body) = match (change.operation, &change.value) {
        (Operation::Upsert, Some(value)) => {
            let body =
                serde_json::to_vec(value).map_err(|_| ApplyError::Malformed("after-image"))?;
            let record = record_from(kind, &body)
                .map_err(|_| ApplyError::Malformed("after-image does not fit its type"))?;
            if record.record_key() != change.record_key {
                return Err(ApplyError::Malformed("record_key does not match its image"));
            }
            let revision = match (&change.edit_revision, edit_revision(&record)) {
                (Some(stated), Some(held)) if *stated != held => {
                    return Err(ApplyError::Malformed("edit_revision does not match"));
                }
                (stated, held) => stated.clone().or(held),
            };
            (revision, Some(body))
        }
        (Operation::Tombstone, None) => (change.edit_revision.clone(), None),
        _ => {
            return Err(ApplyError::Malformed(
                "change value does not fit its operation",
            ));
        }
    };
    tx.execute(
        "INSERT OR REPLACE INTO confirmed_records (workspace_id, record_type, record_key,
            record_version, edit_revision, tombstone, body)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        params![
            workspace_id,
            kind,
            key,
            change.record_version.as_str(),
            revision.as_ref().map(bb_protocol::wire::Counter::as_str),
            i64::from(body.is_none()),
            body,
        ],
    )?;
    Ok(())
}

/// The transaction is the server's proof that the command's result is part of
/// the confirmed base, whether or not its receipt ever arrived.
fn complete_source(
    tx: &Transaction<'_>,
    workspace_id: &str,
    command: &CommandId,
) -> Result<Vec<CommandId>, ApplyError> {
    let state: Option<String> = tx
        .query_row(
            "SELECT state FROM outbox WHERE workspace_id = ?1 AND command_id = ?2",
            params![workspace_id, command.as_str()],
            |row| row.get(0),
        )
        .optional()?;
    match state.as_deref() {
        // Another device, a legacy writer or a job; or already settled.
        None | Some("completed") => Ok(Vec::new()),
        Some("rejected" | "blocked_dependency") => Err(ApplyError::Contradiction(
            "the feed applied a command the device holds as rejected",
        )),
        Some(_) => {
            tx.execute(
                "UPDATE outbox SET state = 'completed'
                 WHERE workspace_id = ?1 AND command_id = ?2",
                params![workspace_id, command.as_str()],
            )?;
            Ok(vec![command.clone()])
        }
    }
}

// --------------------------------------------------------------- oversized transfers

/// How far the pages of a staged transfer have come.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TransferProgress {
    pub transfer_id: Id,
    pub received: u64,
    pub total: u64,
}

impl TransferProgress {
    pub fn is_complete(&self) -> bool {
        self.received == self.total
    }
}

fn micros(instant: &Instant) -> Result<i64, ApplyError> {
    UtcInstant::parse_rfc3339(instant.as_str())
        .map(UtcInstant::unix_micros)
        .map_err(|_| ApplyError::Malformed("instant"))
}

/// How much of a staged object's lifetime has been used.
///
/// `expires_at` is a **server** instant, so it is never compared with the device
/// wall clock: a clock that runs ahead would refuse every fresh object and one
/// that runs behind would keep an expired one alive. The lifetime that remained
/// when staging began (`expires_at` minus the server time the same response
/// carried) is spent by elapsed time instead. Elapsed time is the local clock's
/// forward movement since the last look (a clock that jumps back adds nothing, so
/// it never extends the lifetime and is never trusted to shorten it), raised to
/// the server time of any later response when one is at hand. It is kept in the
/// staging row so it survives a restart.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub(crate) struct Lifetime {
    server_begin: i64,
    elapsed: i64,
    last_local: i64,
}

impl Lifetime {
    pub(crate) fn begin(server_now: &Instant, local_now: &Instant) -> Result<Self, ApplyError> {
        Ok(Self {
            server_begin: micros(server_now)?,
            elapsed: 0,
            last_local: micros(local_now)?,
        })
    }

    /// Accounts for the time since the last look and says whether `expires_at` is
    /// reached. `server_now` is the server time of the response being handled,
    /// when there is one. The caller saves the staging again when this is false.
    pub(crate) fn used_up(
        &mut self,
        expires_at: &Instant,
        local_now: &Instant,
        server_now: Option<&Instant>,
    ) -> Result<bool, ApplyError> {
        let local = micros(local_now)?;
        self.elapsed = self
            .elapsed
            .saturating_add((local - self.last_local).max(0));
        self.last_local = local;
        if let Some(server_now) = server_now {
            self.elapsed = self.elapsed.max(micros(server_now)? - self.server_begin);
        }
        Ok(self.elapsed >= micros(expires_at)? - self.server_begin)
    }
}

/// What is kept of an oversized transaction being staged.
#[derive(Serialize, Deserialize)]
struct StagedTransfer {
    lifetime: Lifetime,
    manifest: TransferManifest,
}

/// Saves a staging's side record (manifest, fence, lifetime) after it changed.
pub(crate) fn persist_staged(
    tx: &Transaction<'_>,
    workspace_id: &str,
    activation_id: &str,
    staged: &impl Serialize,
) -> Result<(), ApplyError> {
    let bytes = serde_json::to_vec(staged).map_err(|_| ApplyError::Malformed("staging"))?;
    tx.execute(
        "UPDATE staging_bases SET manifest = ?3
         WHERE workspace_id = ?1 AND activation_id = ?2",
        params![workspace_id, activation_id, bytes],
    )?;
    Ok(())
}

/// Records the manifest of the next transaction, once. Any other transfer still
/// being staged is for a transaction the server no longer offers: it is dropped.
fn stage_manifest(
    tx: &Transaction<'_>,
    context: &ExecuteContext,
    base: &Base,
    manifest: &TransferManifest,
    server_now: &Instant,
) -> Result<Id, ApplyError> {
    let bytes = serde_json::to_vec(manifest).map_err(|_| ApplyError::Malformed("manifest"))?;
    let digest = sha256(&bytes);
    let workspace_id = base.workspace_id.as_str();
    let id = manifest.transfer_id.as_str();
    let existing: Option<(Vec<u8>, String, Vec<u8>)> = tx
        .query_row(
            "SELECT manifest_digest, state, manifest FROM staging_bases
             WHERE workspace_id = ?1 AND activation_id = ?2",
            params![workspace_id, id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()?;
    match existing {
        Some((stored, _, _)) if stored != digest => {
            return Err(ApplyError::Transfer(TransferFault::Conflict));
        }
        Some((_, state, _)) if state == "activated" => return Ok(manifest.transfer_id.clone()),
        Some((_, state, kept)) if state != "abandoned" => {
            let mut staged: StagedTransfer =
                serde_json::from_slice(&kept).map_err(|_| StoreError::Corrupt)?;
            if staged
                .lifetime
                .used_up(&manifest.expires_at, &context.now, Some(server_now))?
            {
                return Err(ApplyError::Transfer(TransferFault::Expired));
            }
            persist_staged(tx, workspace_id, id, &staged)?;
            return Ok(manifest.transfer_id.clone());
        }
        _ => {}
    }
    let mut lifetime = Lifetime::begin(server_now, &context.now)?;
    if lifetime.used_up(&manifest.expires_at, &context.now, None)? {
        return Err(ApplyError::Transfer(TransferFault::Expired));
    }
    let staged = serde_json::to_vec(&StagedTransfer {
        lifetime,
        manifest: manifest.clone(),
    })
    .map_err(|_| ApplyError::Malformed("manifest"))?;
    let others: Vec<String> = {
        let mut statement = tx.prepare(
            "SELECT activation_id FROM staging_bases
             WHERE workspace_id = ?1 AND kind = 'transaction' AND activation_id <> ?2
               AND state IN ('receiving', 'complete')",
        )?;
        let rows = statement.query_map(params![workspace_id, id], |row| row.get(0))?;
        rows.collect::<Result<_, _>>()?
    };
    for other in others {
        abandon_in(tx, workspace_id, &other)?;
    }
    let total =
        i64::try_from(manifest.page_count).map_err(|_| ApplyError::Malformed("page_count"))?;
    tx.execute(
        "INSERT OR REPLACE INTO staging_bases (workspace_id, activation_id, kind,
            target_generation, target_watermark, manifest, manifest_digest, total_pages,
            state, created_at)
         VALUES (?1, ?2, 'transaction', ?3, ?4, ?5, ?6, ?7, 'receiving', ?8)",
        params![
            workspace_id,
            id,
            base.server_generation.as_deref().unwrap_or_default(),
            manifest.commit_seq.as_str(),
            staged,
            digest.as_slice(),
            total,
            context.now.as_str(),
        ],
    )?;
    Ok(manifest.transfer_id.clone())
}

pub(crate) fn abandon_in(
    tx: &Transaction<'_>,
    workspace_id: &str,
    id: &str,
) -> rusqlite::Result<()> {
    tx.execute(
        "DELETE FROM staging_pages WHERE workspace_id = ?1 AND activation_id = ?2",
        params![workspace_id, id],
    )?;
    tx.execute(
        "UPDATE staging_bases SET state = 'abandoned'
         WHERE workspace_id = ?1 AND activation_id = ?2 AND state <> 'activated'",
        params![workspace_id, id],
    )?;
    Ok(())
}

/// Drops a staged transfer, e.g. after the server answered `RESET_REQUIRED`
/// for it. Live work is untouched.
///
/// # Errors
///
/// [`StoreError`] when the store cannot be written.
pub fn abandon_transfer(store: &mut Store, transfer_id: &Id) -> Result<(), StoreError> {
    store.write(|tx| {
        let workspace_id: String =
            tx.query_row("SELECT workspace_id FROM sync_meta", [], |row| row.get(0))?;
        abandon_in(tx, &workspace_id, transfer_id.as_str())
    })
}

/// Runs `body`; a fault that makes the staged bytes worthless then drops the
/// staging in a transaction of its own, since `body`'s own rolled back.
fn discarding<T>(
    store: &mut Store,
    transfer_id: &Id,
    body: impl FnOnce(&Transaction<'_>) -> Result<T, ApplyError>,
) -> Result<T, ApplyError> {
    let result = store.try_write(body);
    if let Err(ApplyError::Transfer(fault)) = &result
        && fault.discards()
    {
        abandon_transfer(store, transfer_id)?;
    }
    result
}

struct Staged {
    transfer: StagedTransfer,
    state: String,
}

fn load_staged(tx: &Transaction<'_>, base: &Base, transfer_id: &Id) -> Result<Staged, ApplyError> {
    let row: Option<(Vec<u8>, String, String)> = tx
        .query_row(
            "SELECT manifest, state, target_generation FROM staging_bases
             WHERE workspace_id = ?1 AND activation_id = ?2 AND kind = 'transaction'",
            params![base.workspace_id, transfer_id.as_str()],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()?;
    let Some((manifest, state, generation)) = row else {
        return Err(ApplyError::Transfer(TransferFault::Unknown));
    };
    if state == "abandoned" {
        return Err(ApplyError::Transfer(TransferFault::Unknown));
    }
    if base.server_generation.as_deref() != Some(generation.as_str()) {
        return Err(ApplyError::GenerationChanged);
    }
    let transfer = serde_json::from_slice(&manifest).map_err(|_| StoreError::Corrupt)?;
    Ok(Staged { transfer, state })
}

/// Verifies one byte page of a staged transfer and keeps it. A page that fails
/// its checks is refused and not kept; a repeated page is accepted once.
///
/// # Errors
///
/// [`ApplyError::Transfer`] for a corrupt, conflicting or expired page.
pub fn stage_transfer_page(
    store: &mut Store,
    context: &ExecuteContext,
    fence: &Fence,
    page: &TransferPage,
) -> Result<TransferProgress, ApplyError> {
    discarding(store, &page.transfer_id, |tx| {
        let base = read_base(tx, fence)?;
        check_common(&base, &page.page.common)?;
        page.validate()
            .map_err(|_| ApplyError::Malformed("transfer page"))?;
        let mut staged = load_staged(tx, &base, &page.transfer_id)?;
        if staged.state == "activated" {
            return Err(ApplyError::Transfer(TransferFault::Unknown));
        }
        let manifest = &staged.transfer.manifest;
        if staged.transfer.lifetime.used_up(
            &manifest.expires_at,
            &context.now,
            Some(&page.page.common.server_now),
        )? {
            return Err(ApplyError::Transfer(TransferFault::Expired));
        }
        let total = manifest.page_count;
        let received = stage_page(
            tx,
            &base.workspace_id,
            page.transfer_id.as_str(),
            total,
            &page.page,
        )?;
        persist_staged(
            tx,
            &base.workspace_id,
            page.transfer_id.as_str(),
            &staged.transfer,
        )?;
        Ok(TransferProgress {
            transfer_id: page.transfer_id.clone(),
            received,
            total,
        })
    })
}

/// Verifies one byte page against a staged manifest's page count and keeps it;
/// returns how many pages are staged now. Shared by oversized transactions and
/// snapshots, whose pages are the same bounded byte chunks (sync-v1 section 11).
/// The page is refused, not kept, when its index, size, continuation flag or
/// digest is wrong; a repeated page is kept once; a different page for a kept
/// index is a conflict. The staging becomes `complete` with its last page.
pub(crate) fn stage_page(
    tx: &Transaction<'_>,
    workspace_id: &str,
    activation_id: &str,
    total: u64,
    page: &BytePage,
) -> Result<u64, ApplyError> {
    let index = page.page_index;
    let corrupt = ApplyError::Transfer(TransferFault::PageCorrupt { page_index: index });
    let bytes = base64_decode(&page.payload_base64).ok_or(corrupt.clone())?;
    let digest = sha256(&bytes);
    if index >= total
        || bytes.len() > MAX_CHUNK_BYTES
        || page.has_more != (index + 1 < total)
        || !page.page_sha256.eq_ignore_ascii_case(&hex(&digest))
    {
        return Err(corrupt);
    }
    let key = i64::try_from(index).map_err(|_| corrupt.clone())?;
    let kept: Option<Vec<u8>> = tx
        .query_row(
            "SELECT page_digest FROM staging_pages
             WHERE workspace_id = ?1 AND activation_id = ?2 AND page_index = ?3",
            params![workspace_id, activation_id, key],
            |row| row.get(0),
        )
        .optional()?;
    match kept {
        Some(kept) if kept != digest => {
            return Err(ApplyError::Transfer(TransferFault::Conflict));
        }
        Some(_) => {}
        None => {
            tx.execute(
                "INSERT INTO staging_pages (workspace_id, activation_id, page_index,
                    page_digest, body)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
                params![workspace_id, activation_id, key, digest.as_slice(), bytes],
            )?;
        }
    }
    let received: i64 = tx.query_row(
        "SELECT COUNT(*) FROM staging_pages WHERE workspace_id = ?1 AND activation_id = ?2",
        params![workspace_id, activation_id],
        |row| row.get(0),
    )?;
    let received = unsigned(received);
    if received == total {
        tx.execute(
            "UPDATE staging_bases SET state = 'complete'
             WHERE workspace_id = ?1 AND activation_id = ?2",
            params![workspace_id, activation_id],
        )?;
    }
    Ok(received)
}

/// Applies a fully staged oversized transaction: the stream is checked against
/// the manifest (page indices, counts, bytes and digests), decoded, and then
/// installed, matched, replayed and cursored in one transaction, exactly like an
/// inline one. Until it commits, nothing of it is visible.
///
/// # Errors
///
/// [`ApplyError::Transfer`] with [`TransferFault::Incomplete`] while pages are
/// missing (nothing is lost; fetch them), or a fault that discards the staging.
pub fn apply_transfer(
    store: &mut Store,
    context: &ExecuteContext,
    fence: &Fence,
    transfer_id: &Id,
) -> Result<Applied, ApplyError> {
    apply_transfer_with(store, context, fence, transfer_id, |_, _| Ok(()))
}

/// [`apply_transfer`] with the test hook of [`apply_changes_with`].
///
/// # Errors
///
/// As [`apply_transfer`].
pub fn apply_transfer_with(
    store: &mut Store,
    context: &ExecuteContext,
    fence: &Fence,
    transfer_id: &Id,
    mut hook: impl FnMut(ApplyStage, &Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<Applied, ApplyError> {
    discarding(store, transfer_id, |tx| {
        transfer_in(tx, context, fence, transfer_id, &mut hook)
    })
}

fn transfer_in(
    tx: &Transaction<'_>,
    context: &ExecuteContext,
    fence: &Fence,
    transfer_id: &Id,
    hook: &mut impl FnMut(ApplyStage, &Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<Applied, ApplyError> {
    let base = read_base(tx, fence)?;
    let mut staged = load_staged(tx, &base, transfer_id)?;
    let (cursor, watermark) = base.feed()?;
    let manifest = &staged.transfer.manifest;
    let seq = counter(&manifest.commit_seq, "commit_seq")?;
    if staged.state == "activated" || seq <= watermark {
        return Ok(Applied {
            transactions: 0,
            skipped: 1,
            completed: Vec::new(),
            cursor: cursor.to_owned(),
            watermark,
            high_watermark: watermark,
            has_more: false,
            replayed: None,
        });
    }
    if seq != watermark + 1 {
        return Err(gap(watermark + 1, seq, true));
    }
    if staged
        .transfer
        .lifetime
        .used_up(&manifest.expires_at, &context.now, None)?
    {
        return Err(ApplyError::Transfer(TransferFault::Expired));
    }

    let completed = install_stream(tx, &base, transfer_id, manifest)?;
    hook(ApplyStage::Installed, tx)?;
    let replayed = finish_in(tx, context, &manifest.after_cursor, seq)?;
    tx.execute(
        "UPDATE staging_bases SET state = 'activated'
         WHERE workspace_id = ?1 AND activation_id = ?2",
        params![base.workspace_id, transfer_id.as_str()],
    )?;
    tx.execute(
        "DELETE FROM staging_pages WHERE workspace_id = ?1 AND activation_id = ?2",
        params![base.workspace_id, transfer_id.as_str()],
    )?;
    hook(ApplyStage::Replayed, tx)?;
    Ok(Applied {
        transactions: 1,
        skipped: 0,
        completed,
        cursor: manifest.after_cursor.clone(),
        watermark: seq,
        high_watermark: seq,
        has_more: true,
        replayed: Some(replayed),
    })
}

/// Installs the staged transaction page by page, inside the caller's write
/// transaction (see [`stream_pages`] for the checks). Returns the commands the
/// transaction completed.
fn install_stream(
    tx: &Transaction<'_>,
    base: &Base,
    transfer_id: &Id,
    manifest: &TransferManifest,
) -> Result<Vec<CommandId>, ApplyError> {
    stream_pages(
        tx,
        &base.workspace_id,
        transfer_id.as_str(),
        &Promised {
            page_count: manifest.page_count,
            record_count: manifest.record_count,
            total_bytes: manifest.total_bytes,
            sha256: &manifest.sha256,
        },
        |change| install_change(tx, &base.workspace_id, change),
    )?;
    complete_source(tx, &base.workspace_id, &manifest.source_command_id)
}

/// What a manifest promises of the stream its pages make up.
pub(crate) struct Promised<'a> {
    pub page_count: u64,
    pub record_count: u64,
    pub total_bytes: u64,
    pub sha256: &'a str,
}

/// Reads the staged pages of a transfer or snapshot in order and hands each
/// change to `install` as soon as it is complete. Memory is one page plus the
/// record being assembled across a page boundary: the page indices, page
/// digests, byte count, whole-stream digest and record count the manifest
/// promises are checked as the bytes go by. Any disagreement is `Corrupt`; the
/// caller's transaction then rolls back, so nothing of a stream that fails its
/// checks is ever visible. Missing pages are `Incomplete` and lose nothing.
pub(crate) fn stream_pages(
    tx: &Transaction<'_>,
    workspace_id: &str,
    activation_id: &str,
    promised: &Promised<'_>,
    mut install: impl FnMut(&Change) -> Result<(), ApplyError>,
) -> Result<(), ApplyError> {
    let corrupt = || ApplyError::Transfer(TransferFault::Corrupt);
    let present: std::collections::BTreeSet<u64> = {
        let mut statement = tx.prepare(
            "SELECT page_index FROM staging_pages WHERE workspace_id = ?1 AND activation_id = ?2",
        )?;
        let rows = statement.query_map(params![workspace_id, activation_id], |row| {
            row.get::<_, i64>(0)
        })?;
        let mut present = std::collections::BTreeSet::new();
        for row in rows {
            present.insert(u64::try_from(row?).map_err(|_| corrupt())?);
        }
        present
    };
    let missing: Vec<u64> = (0..promised.page_count)
        .filter(|index| !present.contains(index))
        .collect();
    if !missing.is_empty() {
        return Err(ApplyError::Transfer(TransferFault::Incomplete { missing }));
    }
    if u64::try_from(present.len()).ok() != Some(promised.page_count) {
        return Err(corrupt());
    }

    let mut decoder = ChangeStreamDecoder::new();
    let mut digest = Sha256::new();
    let mut bytes = 0_u64;
    for index in 0..promised.page_count {
        let (page_digest, body): (Vec<u8>, Vec<u8>) = tx.query_row(
            "SELECT page_digest, body FROM staging_pages
             WHERE workspace_id = ?1 AND activation_id = ?2 AND page_index = ?3",
            params![
                workspace_id,
                activation_id,
                i64::try_from(index).map_err(|_| corrupt())?
            ],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )?;
        bytes += u64::try_from(body.len()).map_err(|_| corrupt())?;
        if sha256(&body).as_slice() != page_digest.as_slice() || bytes > promised.total_bytes {
            return Err(corrupt());
        }
        digest.update(&body);
        for change in decoder.push(&body).map_err(|_| corrupt())? {
            install(&change)?;
        }
    }
    let records = decoder.finish().map_err(|_| corrupt())?;
    if records != promised.record_count
        || bytes != promised.total_bytes
        || !promised.sha256.eq_ignore_ascii_case(&hex(&digest.finish()))
    {
        return Err(corrupt());
    }
    Ok(())
}

// ----------------------------------------------------------------------- encoding

pub(crate) fn hex(digest: &[u8; 32]) -> String {
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// The SHA-256 of `data` as lowercase hex: the form of the digests in transfer
/// and snapshot manifests and pages, which are integrity checks and never
/// logged.
pub fn sha256_hex(data: &[u8]) -> String {
    hex(&sha256(data))
}

/// Standard base64 with padding; any other character, a misplaced `=` or
/// nonzero padding bits is refused.
pub(crate) fn base64_decode(text: &str) -> Option<Vec<u8>> {
    let (quads, tail) = text.as_bytes().as_chunks::<4>();
    if !tail.is_empty() {
        return None;
    }
    let sextet = |byte: u8| -> Option<u32> {
        Some(u32::from(match byte {
            b'A'..=b'Z' => byte - b'A',
            b'a'..=b'z' => byte - b'a' + 26,
            b'0'..=b'9' => byte - b'0' + 52,
            b'+' => 62,
            b'/' => 63,
            _ => return None,
        }))
    };
    let mut out = Vec::with_capacity(quads.len() * 3);
    for (index, quad) in quads.iter().enumerate() {
        let padding = if index + 1 == quads.len() {
            quad.iter().rev().take_while(|byte| **byte == b'=').count()
        } else {
            0
        };
        if padding > 2 {
            return None;
        }
        let mut bits = 0_u32;
        for byte in &quad[..4 - padding] {
            bits = (bits << 6) | sextet(*byte)?;
        }
        bits <<= 6 * padding;
        let triple = bits.to_be_bytes();
        if triple[4 - padding..].iter().any(|byte| *byte != 0) {
            return None; // padding bits must be zero
        }
        out.extend_from_slice(&triple[1..4 - padding]);
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::{base64_decode, newer};

    #[test]
    fn apply_changes_026_fr_004_base64_decodes_the_standard_alphabet_strictly() {
        assert_eq!(base64_decode(""), Some(Vec::new()));
        assert_eq!(base64_decode("Zg=="), Some(b"f".to_vec()));
        assert_eq!(base64_decode("Zm8="), Some(b"fo".to_vec()));
        assert_eq!(base64_decode("Zm9v"), Some(b"foo".to_vec()));
        assert_eq!(base64_decode("Zm9vYg=="), Some(b"foob".to_vec()));
        assert_eq!(base64_decode("+/8="), Some(vec![0xfb, 0xff]));
        // Not padded, wrong alphabet, interior padding, nonzero padding bits.
        assert_eq!(base64_decode("Zg"), None);
        assert_eq!(base64_decode("-_8="), None);
        assert_eq!(base64_decode("Zg==Zm9v"), None);
        assert_eq!(base64_decode("Zh=="), None);
        assert_eq!(base64_decode("Zm9 "), None);
    }

    #[test]
    fn apply_changes_026_fr_004_counters_compare_by_length_then_digits() {
        assert!(newer("10", "9"));
        assert!(newer("2", "1"));
        assert!(!newer("9", "9"));
        assert!(!newer("9", "10"));
    }
}
