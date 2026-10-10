//! Snapshot bootstrap and recovery (sync-v1 sections 6, 7 and 11).
//!
//! A snapshot rebuilds the confirmed base when the feed cannot: first
//! bootstrap, a gap, an expired cursor, a changed server generation. It is
//! downloaded into staging (`staging_bases`/`staging_pages`, the same tables
//! and page checks an oversized transaction uses), which is **never** the base
//! the app reads: until activation the old confirmed records, visible
//! projection, cursor and queue are exactly as they were, whatever happens to
//! the download (a restart, an expiry, a corrupt page, a reset).
//!
//! Activation is one write transaction, so it holds SQLite's cross-process
//! writer lock for as long as it takes. Inside it:
//!
//! 1. the staged stream is verified against the manifest (every page index,
//!    the byte count, the SHA-256 and the record count) and the manifest must
//!    still be unexpired and, in the same server generation, not older than the
//!    base the device already holds. Expiry is the server's TTL spent by elapsed
//!    time ([`crate::apply_changes::Lifetime`]), never the device wall clock
//!    compared with a server instant;
//! 2. the confirmed records are replaced by the snapshot's, tombstones
//!    included, and the generation, cursor and watermark become the manifest's;
//! 3. commands the server accepted (`accepted_awaiting_feed`) leave the queue
//!    only when a receipt **of the snapshot's server generation** has a
//!    `commit_seq` at or below the snapshot watermark. A newer receipt keeps
//!    waiting for the feed; a command with no receipt of that generation (its
//!    acceptance was a different generation's, which proves nothing after a
//!    restore) becomes `unknown`;
//! 4. the pending queue is replayed over the new base.
//!
//! Nothing is copied when the download starts. The queue, the issues, the
//! drafts and the intake epoch are read **live**, inside the transaction, so
//! an edit saved while pages were downloading (by this process, a widget or
//! an intent) is replayed over the snapshot and never replaced by an earlier
//! copy. Activation never touches the intake epoch or the local sequence.
//!
//! The snapshot proves nothing about a command the device sent and has no
//! receipt for: its absence from the stream is not an outcome. The activation
//! reports every such command in [`Activated::lookups`] and the caller must
//! look each one up (`GET commands/{id}`), never guess.

use crate::apply_changes::{
    ApplyError, ApplyStage, Base, Fence, Lifetime, Promised, Recovery, TransferFault, abandon_in,
    abandon_transfer, finish_in, install_change, persist_staged, read_base, stage_page,
    stream_pages, unsigned,
};
use crate::execute::{ExecuteContext, sha256};
use crate::replay::Replayed;
use crate::storage::{Store, StoreError};
use bb_protocol::feed::{SnapshotManifest, SnapshotPage};
use bb_protocol::wire::{CommandId, CommonResponse, Counter, Id, Wire};
use rusqlite::{OptionalExtension, Transaction, params};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

/// What is kept of a snapshot being staged: the manifest, how much of its
/// server-set lifetime is used up ([`Lifetime`]: never judged against the device
/// wall clock), and the request generations it was started under. A reset
/// changes those, and then the download belongs to a request the runtime
/// cancelled.
#[derive(Serialize, Deserialize)]
struct StagedSnapshot {
    fence: [u64; 3],
    lifetime: Lifetime,
    manifest: SnapshotManifest,
}

fn fence_of(fence: &Fence) -> [u64; 3] {
    [
        fence.workspace_generation,
        fence.session_generation,
        fence.local_sync_generation,
    ]
}

/// How far the pages of a staged snapshot have come.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SnapshotProgress {
    pub snapshot_id: Id,
    pub received: u64,
    pub total: u64,
}

impl SnapshotProgress {
    pub fn is_complete(&self) -> bool {
        self.received == self.total
    }
}

/// What activating a snapshot did.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Activated {
    pub snapshot_id: Id,
    /// The server generation the confirmed base now belongs to.
    pub server_generation: String,
    /// The cursor to read deltas from next.
    pub cursor: String,
    /// The commit sequence the confirmed base now reaches.
    pub watermark: u64,
    /// Records in the snapshot (tombstones included).
    pub records: u64,
    /// Accepted commands the snapshot proved part of the confirmed base.
    pub completed: Vec<CommandId>,
    /// Commands that may have reached the server and have no outcome yet:
    /// look each one up. Never resend one under a new ID.
    pub lookups: Vec<CommandId>,
    /// The replay that followed; `None` when the snapshot was already active.
    pub replayed: Option<Replayed>,
    /// The call found the snapshot already activated and changed nothing.
    pub already_active: bool,
}

// ------------------------------------------------------------------------ staging

fn counter(counter: &Counter, what: &'static str) -> Result<u64, ApplyError> {
    counter.to_u64().ok_or(ApplyError::Malformed(what))
}

/// The response is for the scope this workspace syncs. Unlike a feed page, a
/// snapshot may belong to a **new** server generation: it is what rebuilds the
/// base after one, so its generation is the target, not a thing to match.
fn check_scope(base: &Base, common: &CommonResponse) -> Result<(), ApplyError> {
    match base.scope_id() {
        Some(scope) if scope == common.scope_id.as_str() => Ok(()),
        _ => Err(ApplyError::WrongScope),
    }
}

/// A snapshot older than the base the device already holds, in the same
/// generation, must not replace it: that would take the base backwards. The
/// feed from the stored cursor is the way forward.
fn check_not_older(base: &Base, generation: &str, watermark: u64) -> Result<(), ApplyError> {
    if let (Some(held_generation), Some(held)) = (base.server_generation(), base.watermark())
        && held_generation == generation
        && watermark < held
    {
        return Err(ApplyError::Gap {
            expected: held,
            found: watermark,
            recovery: Recovery::Refetch,
        });
    }
    Ok(())
}

/// Runs `body`; a fault that makes the staged bytes worthless then drops the
/// staging in a transaction of its own, since `body`'s own rolled back. The
/// active base is never touched by it.
fn guarded<T>(
    store: &mut Store,
    snapshot_id: &Id,
    body: impl FnOnce(&Transaction<'_>) -> Result<T, ApplyError>,
) -> Result<T, ApplyError> {
    let result = store.try_write(body);
    if let Err(error) = &result {
        let worthless = match error {
            ApplyError::Transfer(fault) => fault.discards(),
            ApplyError::GenerationChanged | ApplyError::Gap { .. } => true,
            _ => false,
        };
        if worthless {
            abandon_transfer(store, snapshot_id)?;
        }
    }
    result
}

fn pages_staged(tx: &Transaction<'_>, workspace_id: &str, id: &str) -> Result<u64, ApplyError> {
    let received: i64 = tx.query_row(
        "SELECT COUNT(*) FROM staging_pages WHERE workspace_id = ?1 AND activation_id = ?2",
        params![workspace_id, id],
        |row| row.get(0),
    )?;
    Ok(unsigned(received))
}

/// Records the manifest of a snapshot to download, once; announcing it again
/// (after a restart, say) reports how far the staging has come. A download
/// still in progress for another snapshot is for a request the runtime has
/// replaced: it is dropped, and the live work is untouched.
///
/// # Errors
///
/// [`ApplyError`]; whatever it is, nothing of the active base changed. An
/// expired manifest is [`TransferFault::Expired`]; one older than the base in
/// its generation is [`ApplyError::Gap`] (refetch the feed).
pub fn begin_snapshot(
    store: &mut Store,
    context: &ExecuteContext,
    fence: &Fence,
    manifest: &SnapshotManifest,
) -> Result<SnapshotProgress, ApplyError> {
    guarded(store, &manifest.snapshot_id, |tx| {
        begin_in(tx, context, fence, manifest)
    })
}

fn begin_in(
    tx: &Transaction<'_>,
    context: &ExecuteContext,
    fence: &Fence,
    manifest: &SnapshotManifest,
) -> Result<SnapshotProgress, ApplyError> {
    let base = read_base(tx, fence)?;
    manifest
        .validate()
        .map_err(|_| ApplyError::Malformed("snapshot manifest"))?;
    check_scope(&base, &manifest.common)?;
    let watermark = counter(&manifest.watermark, "watermark")?;
    let target = manifest.common.server_generation.as_str();
    let workspace_id = base.workspace_id.as_str();
    let id = manifest.snapshot_id.as_str();
    let progress = |received| SnapshotProgress {
        snapshot_id: manifest.snapshot_id.clone(),
        received,
        total: manifest.page_count,
    };

    let bytes =
        serde_json::to_vec(manifest).map_err(|_| ApplyError::Malformed("snapshot manifest"))?;
    let digest = sha256(&bytes);
    let existing: Option<(String, Vec<u8>, String, Vec<u8>)> = tx
        .query_row(
            "SELECT kind, manifest_digest, state, manifest FROM staging_bases
             WHERE workspace_id = ?1 AND activation_id = ?2",
            params![workspace_id, id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
        )
        .optional()?;
    if let Some((kind, stored, state, _)) = &existing {
        if kind != "snapshot" {
            return Err(ApplyError::Malformed("an activation ID already in use"));
        }
        if state != "abandoned" && *stored != digest {
            return Err(ApplyError::Transfer(TransferFault::Conflict));
        }
        if state == "activated" {
            return Ok(progress(manifest.page_count));
        }
    }
    check_not_older(&base, target, watermark)?;
    if let Some((_, _, state, staged)) = &existing
        && state != "abandoned"
        && let Ok(mut staged) = serde_json::from_slice::<StagedSnapshot>(staged)
        && staged.fence == fence_of(fence)
    {
        // Announced again: the lifetime keeps running from the first time.
        if staged.lifetime.used_up(
            &manifest.expires_at,
            &context.now,
            Some(&manifest.common.server_now),
        )? {
            return Err(ApplyError::Transfer(TransferFault::Expired));
        }
        persist_staged(tx, workspace_id, id, &staged)?;
        return Ok(progress(pages_staged(tx, workspace_id, id)?));
    }
    let mut lifetime = Lifetime::begin(&manifest.common.server_now, &context.now)?;
    if lifetime.used_up(&manifest.expires_at, &context.now, None)? {
        return Err(ApplyError::Transfer(TransferFault::Expired));
    }

    // A new download supersedes every other one in progress.
    abandon_other_snapshots(tx, workspace_id, id)?;
    abandon_in(tx, workspace_id, id)?;
    let staged = serde_json::to_vec(&StagedSnapshot {
        fence: fence_of(fence),
        lifetime,
        manifest: manifest.clone(),
    })
    .map_err(|_| ApplyError::Malformed("snapshot manifest"))?;
    let total =
        i64::try_from(manifest.page_count).map_err(|_| ApplyError::Malformed("page_count"))?;
    tx.execute(
        "INSERT OR REPLACE INTO staging_bases (workspace_id, activation_id, kind,
            target_generation, target_watermark, manifest, manifest_digest, total_pages,
            state, created_at)
         VALUES (?1, ?2, 'snapshot', ?3, ?4, ?5, ?6, ?7, 'receiving', ?8)",
        params![
            workspace_id,
            id,
            target,
            manifest.watermark.as_str(),
            staged,
            digest.as_slice(),
            total,
            context.now.as_str(),
        ],
    )?;
    Ok(progress(0))
}

/// Drops every snapshot still downloading except `keep`.
fn abandon_other_snapshots(
    tx: &Transaction<'_>,
    workspace_id: &str,
    keep: &str,
) -> Result<(), ApplyError> {
    let others: Vec<String> = {
        let mut statement = tx.prepare(
            "SELECT activation_id FROM staging_bases
             WHERE workspace_id = ?1 AND activation_id <> ?2 AND kind = 'snapshot'
               AND state IN ('receiving', 'complete')",
        )?;
        let rows = statement.query_map(params![workspace_id, keep], |row| row.get(0))?;
        rows.collect::<Result<_, _>>()?
    };
    for other in others {
        abandon_in(tx, workspace_id, &other)?;
    }
    Ok(())
}

struct Staged {
    snapshot: StagedSnapshot,
    state: String,
}

fn load_staged(
    tx: &Transaction<'_>,
    workspace_id: &str,
    snapshot_id: &Id,
    fence: &Fence,
) -> Result<Staged, ApplyError> {
    let row: Option<(Vec<u8>, String)> = tx
        .query_row(
            "SELECT manifest, state FROM staging_bases
             WHERE workspace_id = ?1 AND activation_id = ?2 AND kind = 'snapshot'",
            params![workspace_id, snapshot_id.as_str()],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    let Some((bytes, state)) = row else {
        return Err(ApplyError::Transfer(TransferFault::Unknown));
    };
    if state == "abandoned" {
        return Err(ApplyError::Transfer(TransferFault::Unknown));
    }
    let snapshot: StagedSnapshot =
        serde_json::from_slice(&bytes).map_err(|_| StoreError::Corrupt)?;
    // Started under earlier request generations: a reset cancelled it.
    if snapshot.fence != fence_of(fence) {
        return Err(ApplyError::Stale);
    }
    Ok(Staged { snapshot, state })
}

/// Verifies one byte page of a staged snapshot and keeps it. A page that fails
/// its checks (index, size, continuation, digest, snapshot, watermark,
/// generation) is refused and not kept; a repeated page is accepted once.
///
/// # Errors
///
/// [`ApplyError::Transfer`] for a corrupt, conflicting or expired page;
/// [`ApplyError::GenerationChanged`] for a page of another server generation.
/// Faults that make the staging worthless drop it; the active base is never
/// touched.
pub fn stage_snapshot_page(
    store: &mut Store,
    context: &ExecuteContext,
    fence: &Fence,
    page: &SnapshotPage,
) -> Result<SnapshotProgress, ApplyError> {
    guarded(store, &page.snapshot_id, |tx| {
        let base = read_base(tx, fence)?;
        page.validate()
            .map_err(|_| ApplyError::Malformed("snapshot page"))?;
        check_scope(&base, &page.page.common)?;
        let mut staged = load_staged(tx, &base.workspace_id, &page.snapshot_id, fence)?;
        let manifest = &staged.snapshot.manifest;
        if staged.state == "activated" {
            return Err(ApplyError::Transfer(TransferFault::Unknown));
        }
        if page.page.common.server_generation != manifest.common.server_generation {
            return Err(ApplyError::GenerationChanged);
        }
        // Every page refers to the one version the manifest announced.
        if page.watermark != manifest.watermark {
            return Err(ApplyError::Transfer(TransferFault::Conflict));
        }
        if staged.snapshot.lifetime.used_up(
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
            page.snapshot_id.as_str(),
            total,
            &page.page,
        )?;
        persist_staged(
            tx,
            &base.workspace_id,
            page.snapshot_id.as_str(),
            &staged.snapshot,
        )?;
        Ok(SnapshotProgress {
            snapshot_id: page.snapshot_id.clone(),
            received,
            total,
        })
    })
}

/// Drops a staged snapshot, e.g. after the server answered `RESET_REQUIRED` for
/// it. The active base and every piece of live work are untouched.
///
/// # Errors
///
/// [`StoreError`] when the store cannot be written.
pub fn abandon_snapshot(store: &mut Store, snapshot_id: &Id) -> Result<(), StoreError> {
    abandon_transfer(store, snapshot_id)
}

// ---------------------------------------------------------------------- activation

/// Activates a fully staged snapshot. See the module documentation.
///
/// # Errors
///
/// [`ApplyError::Transfer`] with [`TransferFault::Incomplete`] while pages are
/// missing (nothing is lost; fetch them), a fault that discards the staging
/// (`Expired` and `Corrupt` ask for a new snapshot), or [`ApplyError::Gap`]
/// when the device already holds a newer base of that generation. Whatever it
/// is, the active base, cursor and queue are as they were.
pub fn activate_snapshot(
    store: &mut Store,
    context: &ExecuteContext,
    fence: &Fence,
    snapshot_id: &Id,
) -> Result<Activated, ApplyError> {
    activate_snapshot_with(store, context, fence, snapshot_id, |_, _| Ok(()))
}

/// [`activate_snapshot`] with a hook that runs inside the transaction at each
/// [`ApplyStage`]: `Installed` once the base is replaced and the accepted
/// commands settled, `Replayed` once the replay, cursor and watermark are
/// written. An `Err` from the hook rolls the activation back; a hook that kills
/// the process leaves an uncommitted transaction for SQLite to discard.
///
/// # Errors
///
/// As [`activate_snapshot`].
pub fn activate_snapshot_with(
    store: &mut Store,
    context: &ExecuteContext,
    fence: &Fence,
    snapshot_id: &Id,
    mut hook: impl FnMut(ApplyStage, &Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<Activated, ApplyError> {
    guarded(store, snapshot_id, |tx| {
        activate_in(tx, context, fence, snapshot_id, &mut hook)
    })
}

fn activate_in(
    tx: &Transaction<'_>,
    context: &ExecuteContext,
    fence: &Fence,
    snapshot_id: &Id,
    hook: &mut impl FnMut(ApplyStage, &Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<Activated, ApplyError> {
    let base = read_base(tx, fence)?;
    let workspace_id = base.workspace_id.as_str();
    let mut staged = load_staged(tx, workspace_id, snapshot_id, fence)?;
    let manifest = &staged.snapshot.manifest;
    check_scope(&base, &manifest.common)?;
    let target = manifest.common.server_generation.as_str();
    let watermark = counter(&manifest.watermark, "watermark")?;

    if staged.state == "activated" {
        let (cursor, held) = base.feed()?;
        return Ok(Activated {
            snapshot_id: snapshot_id.clone(),
            server_generation: base.server_generation().unwrap_or(target).to_owned(),
            cursor: cursor.to_owned(),
            watermark: held,
            records: manifest.record_count,
            completed: Vec::new(),
            lookups: lookups_in(tx, workspace_id)?,
            replayed: None,
            already_active: true,
        });
    }
    if staged
        .snapshot
        .lifetime
        .used_up(&manifest.expires_at, &context.now, None)?
    {
        return Err(ApplyError::Transfer(TransferFault::Expired));
    }
    check_not_older(&base, target, watermark)?;

    let local_before = crate::localfacts::snapshot_before(tx, workspace_id)?;
    let same_generation = base.server_generation() == Some(target);

    // Replace the base while streaming the staged pages: each page and the
    // whole stream is checked against the manifest as it goes by, and any
    // disagreement (or a missing page) rolls this transaction back, old base
    // included.
    tx.execute(
        "DELETE FROM confirmed_records WHERE workspace_id = ?1",
        [workspace_id],
    )?;
    let mut keys = HashSet::new();
    stream_pages(
        tx,
        workspace_id,
        snapshot_id.as_str(),
        &Promised {
            page_count: manifest.page_count,
            record_count: manifest.record_count,
            total_bytes: manifest.total_bytes,
            sha256: &manifest.sha256,
        },
        |change| {
            // A key twice has no single final image.
            if !keys.insert((change.entity_type, change.record_key.clone())) {
                return Err(ApplyError::Transfer(TransferFault::Corrupt));
            }
            install_change(tx, workspace_id, change)
        },
    )?;
    crate::localfacts::snapshot_after(
        tx,
        workspace_id,
        local_before,
        same_generation,
        target,
        watermark,
    )?;
    tx.execute("UPDATE sync_meta SET server_generation = ?1", [target])?;
    let completed = settle_accepted(tx, workspace_id, target, watermark)?;
    hook(ApplyStage::Installed, tx)?;

    // The queue, issues, drafts and intake epoch are read here, live.
    let replayed = finish_in(tx, context, &manifest.cursor, watermark)?;
    tx.execute(
        "UPDATE staging_bases SET state = 'activated'
         WHERE workspace_id = ?1 AND activation_id = ?2",
        params![workspace_id, snapshot_id.as_str()],
    )?;
    tx.execute(
        "DELETE FROM staging_pages WHERE workspace_id = ?1 AND activation_id = ?2",
        params![workspace_id, snapshot_id.as_str()],
    )?;
    let lookups = lookups_in(tx, workspace_id)?;
    hook(ApplyStage::Replayed, tx)?;
    Ok(Activated {
        snapshot_id: snapshot_id.clone(),
        server_generation: target.to_owned(),
        cursor: manifest.cursor.clone(),
        watermark,
        records: manifest.record_count,
        completed,
        lookups,
        replayed: Some(replayed),
        already_active: false,
    })
}

/// Settles the commands the device holds as accepted, by the only proof that
/// counts: a receipt of **the snapshot's** server generation whose `commit_seq`
/// the snapshot's watermark reaches.
///
/// * proven: `completed`, since the snapshot holds their result;
/// * a receipt of that generation beyond the watermark: still
///   `accepted_awaiting_feed`, for a later delta;
/// * no receipt of that generation: the acceptance was another generation's, so
///   it proves nothing here. The command becomes `unknown` (still sent, still
///   pending, never judged locally) and is looked up.
fn settle_accepted(
    tx: &Transaction<'_>,
    workspace_id: &str,
    generation: &str,
    watermark: u64,
) -> Result<Vec<CommandId>, ApplyError> {
    let accepted: Vec<(String, Option<String>)> = {
        let mut statement = tx.prepare(
            "SELECT o.command_id, r.commit_seq FROM outbox o
             LEFT JOIN command_receipts r
               ON r.workspace_id = o.workspace_id AND r.command_id = o.command_id
              AND r.server_generation = ?2 AND r.outcome = 'accepted'
             WHERE o.workspace_id = ?1 AND o.state = 'accepted_awaiting_feed'
             ORDER BY o.local_seq",
        )?;
        let rows = statement.query_map(params![workspace_id, generation], |row| {
            Ok((row.get(0)?, row.get(1)?))
        })?;
        rows.collect::<Result<_, _>>()?
    };
    let mut completed = Vec::new();
    for (command, seq) in accepted {
        let proven = match seq {
            Some(seq) => {
                let seq = Counter::parse(seq)
                    .ok()
                    .and_then(|seq| seq.to_u64())
                    .ok_or(StoreError::Corrupt)?;
                if seq > watermark {
                    continue; // accepted in this generation; its delta is yet to come
                }
                true
            }
            None => false,
        };
        let state = if proven { "completed" } else { "unknown" };
        tx.execute(
            "UPDATE outbox SET state = ?3 WHERE workspace_id = ?1 AND command_id = ?2",
            params![workspace_id, command, state],
        )?;
        if proven {
            completed.push(CommandId::parse(command).map_err(|_| StoreError::Corrupt)?);
        }
    }
    Ok(completed)
}

/// The commands whose outcome nothing in the store proves: they may have
/// reached the server and are neither finished, nor rejected, nor accepted with
/// a receipt of the current generation. In queue order.
fn lookups_in(tx: &Transaction<'_>, workspace_id: &str) -> Result<Vec<CommandId>, ApplyError> {
    let mut statement = tx.prepare(
        "SELECT command_id FROM outbox
         WHERE workspace_id = ?1 AND ever_sent = 1
           AND state IN ('queued', 'sending', 'unknown')
         ORDER BY local_seq",
    )?;
    let rows = statement.query_map([workspace_id], |row| row.get::<_, String>(0))?;
    let mut lookups = Vec::new();
    for row in rows {
        lookups.push(CommandId::parse(row?).map_err(|_| StoreError::Corrupt)?);
    }
    Ok(lookups)
}
