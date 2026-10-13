//! The account link and the account copy's removal (spec 026, T044, FR-003, FR-011).
//!
//! Two lifecycle steps of a workspace, each one write transaction under the store's own lock, so
//! a widget or App Intent in another process either lands before the check (and is counted) or
//! after it (and meets the result):
//!
//! * [`link_account_with`] binds an account-less (or still unchosen) workspace to the account
//!   that signed in. The merge of account-less work into an account is a constructed import of
//!   new owner-bound commands (data-model "Local durable records"), which does not exist yet; so
//!   a workspace that holds any local work is **not** linked and nothing changes
//!   ([`LinkOutcome::LocalWorkNotMerged`]). The work is never dropped and never relabelled.
//!   The scope and device are bound by the sync session at its first start, as for an imported
//!   account, and the link bumps the workspace generation so every answer to a request issued
//!   before it is fenced out.
//! * [`remove_account_copy_with`] removes the account's local copy. The caller named what it
//!   showed (how many unsent changes, at which projection generation, which open issues); under
//!   the lock the same facts are read again and the copy is removed only when no more was queued
//!   since. The workspace's identity row is kept (it is immutable) and reset to a fresh,
//!   unchosen workspace, so a stray writer that still holds the old file finds an empty store,
//!   not the account's data; the host deletes the file afterwards.

use crate::{ExecuteError, Store, StoreError};
use bb_domain::types::{DomainError, Reason};
use bb_protocol::wire::Id;
use rusqlite::{Transaction, params};
use std::collections::BTreeSet;

fn invalid(field: &str) -> ExecuteError {
    DomainError::field(Reason::InvalidValue, field).into()
}

/// What linking did.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LinkOutcome {
    /// The workspace is the account's now.
    Linked,
    /// It already was (a retry after a lost answer, or an imported account's store).
    AlreadyLinked,
    /// Another account owns it: nothing changed, and its work is never moved.
    OtherAccount,
    /// The workspace holds local work that no constructed import carries into an account yet.
    /// Nothing changed.
    LocalWorkNotMerged { records: u64, queued: u64 },
}

/// Binds the workspace to `account`. `before_commit` runs right before the commit of a change
/// (or of a retry that changes nothing) and may refuse it, which is how a Cancel that came first
/// wins.
///
/// # Errors
///
/// [`ExecuteError`] when the store cannot be written, is in a state that cannot be linked
/// (`linking`), or `before_commit` refuses.
pub fn link_account_with(
    store: &mut Store,
    account: &Id,
    before_commit: impl FnOnce() -> Result<(), ExecuteError>,
) -> Result<LinkOutcome, ExecuteError> {
    store.try_write(|tx| {
        let (state, held, scope, device): (String, Option<String>, Option<String>, Option<String>) =
            tx.query_row(
                "SELECT account_link_state, account_id, scope_id, device_id FROM sync_meta",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
            .map_err(StoreError::from)?;
        match state.as_str() {
            "linked" if held.as_deref() == Some(account.as_str()) => {
                before_commit()?;
                return Ok(LinkOutcome::AlreadyLinked);
            }
            "linked" => return Ok(LinkOutcome::OtherAccount),
            "unchosen" | "account_less" => {}
            _ => return Err(invalid("account_link_state")),
        }
        if held.is_some() || scope.is_some() || device.is_some() {
            return Err(StoreError::Corrupt.into());
        }
        let (records, queued) = local_work(tx)?;
        if records > 0 || queued > 0 {
            return Ok(LinkOutcome::LocalWorkNotMerged { records, queued });
        }
        tx.execute(
            "UPDATE sync_meta SET account_id = ?1, account_link_state = 'linked',
                workspace_generation = workspace_generation + 1",
            [account.as_str()],
        )
        .map_err(StoreError::from)?;
        before_commit()?;
        Ok(LinkOutcome::Linked)
    })
}

/// Records of the workspace, and commands that are still to be sent (or decided).
fn local_work(tx: &Transaction<'_>) -> Result<(u64, u64), StoreError> {
    let (records, queued): (i64, i64) = tx.query_row(
        "SELECT MAX((SELECT COUNT(*) FROM visible_records), (SELECT COUNT(*) FROM confirmed_records)),
                (SELECT COUNT(*) FROM outbox WHERE state <> 'completed')",
        [],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    Ok((
        u64::try_from(records).map_err(|_| StoreError::Corrupt)?,
        u64::try_from(queued).map_err(|_| StoreError::Corrupt)?,
    ))
}

/// What a sign-out confirmation named; see [`remove_account_copy_with`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RemovalCheck {
    /// No more unsent commands than this may be in the store.
    pub max_unsent: u64,
    /// The projection generation the unsent work was named at; required to be the current one
    /// whenever any is left, because every local write moves it.
    pub generation: u64,
    /// The open issues the person saw. An open issue that is not here was not seen.
    pub issue_ids: BTreeSet<String>,
}

/// What removing did.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RemovalOutcome {
    /// The copy is gone; the workspace is a fresh unchosen one.
    Removed,
    /// More was queued (or an issue opened) since the confirmation: nothing was removed.
    Changed { unsent: u64, open_issues: u64 },
}

/// Removes the account's local copy when it still is what `check` named. See the module
/// documentation.
///
/// # Errors
///
/// [`ExecuteError`] when the store cannot be written or `before_commit` refuses.
pub fn remove_account_copy_with(
    store: &mut Store,
    check: &RemovalCheck,
    before_commit: impl FnOnce() -> Result<(), ExecuteError>,
) -> Result<RemovalOutcome, ExecuteError> {
    store.try_write(|tx| {
        let (unsent, generation): (i64, i64) = tx
            .query_row(
                "SELECT (SELECT COUNT(*) FROM outbox WHERE state NOT IN ('completed', 'rejected')),
                        projection_generation FROM sync_meta",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
            .map_err(StoreError::from)?;
        let unsent = u64::try_from(unsent).map_err(|_| StoreError::Corrupt)?;
        let generation = u64::try_from(generation).map_err(|_| StoreError::Corrupt)?;
        let issues = open_issue_ids(tx)?;
        let admitted = unsent <= check.max_unsent
            && (unsent == 0 || generation == check.generation)
            && issues.is_subset(&check.issue_ids);
        if !admitted {
            return Ok(RemovalOutcome::Changed {
                unsent,
                open_issues: issues.len() as u64,
            });
        }
        wipe(tx)?;
        before_commit()?;
        Ok(RemovalOutcome::Removed)
    })
}

fn open_issue_ids(tx: &Transaction<'_>) -> Result<BTreeSet<String>, StoreError> {
    let mut statement = tx.prepare("SELECT issue_id FROM sync_issues WHERE resolution = 'open'")?;
    let rows = statement.query_map([], |row| row.get::<_, String>(0))?;
    Ok(rows.collect::<Result<_, _>>()?)
}

/// Every row of every table but the identity row, then the identity row back to a fresh
/// workspace. The generations only grow, so an answer to a request of the removed copy is stale.
fn wipe(tx: &Transaction<'_>) -> Result<(), StoreError> {
    let tables: Vec<String> = {
        let mut statement = tx.prepare(
            "SELECT name FROM sqlite_master
             WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name <> 'sync_meta'",
        )?;
        let rows = statement.query_map([], |row| row.get::<_, String>(0))?;
        rows.collect::<Result<_, _>>()?
    };
    // Rows reference each other; the references are checked at commit, when none are left.
    tx.execute_batch("PRAGMA defer_foreign_keys = ON")?;
    for table in &tables {
        // Names come from this store's own schema.
        if !table.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
            return Err(StoreError::Corrupt);
        }
        tx.execute(&format!("DELETE FROM \"{table}\""), [])?;
    }
    tx.execute(
        "UPDATE sync_meta SET account_id = NULL, scope_id = NULL, device_id = NULL,
            workspace_generation = workspace_generation + 1,
            session_generation = session_generation + 1,
            local_sync_generation = local_sync_generation + 1,
            server_generation = NULL, device_epoch = NULL, device_epoch_state = 'none',
            account_link_state = 'unchosen', link_checkpoint = NULL, next_local_seq = 1,
            cursor = NULL, base_watermark = NULL,
            projection_generation = projection_generation + 1, last_success_at = NULL,
            projection_stale = 0",
        params![],
    )?;
    Ok(())
}
