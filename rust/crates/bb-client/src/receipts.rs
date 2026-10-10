//! Applying command receipts (sync-v1 sections 5 and 7).
//!
//! A receipt settles the outbox command it names, and nothing else. Above all it
//! **never writes the confirmed base and never moves the cursor**: a late ACK
//! across a transaction the device has not seen could otherwise break the
//! consistency of several records at once. What a receipt does:
//!
//! * **Accepted, with changes**: the command no longer needs sending, but its
//!   intent and optimistic projection stay (`accepted_awaiting_feed`). It leaves
//!   the pending queue only in a transaction that proves its result is in the
//!   confirmed base: the feed transaction naming it as its source
//!   ([`crate::apply_changes`]), or a base whose watermark already reaches the
//!   receipt's `commit_seq`. An ACK is therefore never turned into a local
//!   conflict just because the feed has not caught up.
//! * **Accepted no-op** (no changes, no `commit_seq`): complete from the receipt
//!   itself, since there is no feed transaction to wait for.
//! * **Rejected**: terminal. The command becomes a `rejected` one with an issue
//!   that keeps its intent and text, everything built on it is held, and
//!   independent commands go on ([`crate::issues::record_rejection_in`]).
//!
//! Every outcome then replays the pending queue over the unchanged base. The
//! verified receipt is stored under its server generation, which is the only
//! generation it can prove anything for; a receipt of another generation is
//! refused. Applying the same receipt again changes nothing, and a receipt that
//! contradicts a stored one, or the command's state, is refused rather than
//! guessed at (026-FR-010).

use crate::apply_changes::{ApplyError, Fence, check_common, read_base};
use crate::execute::ExecuteContext;
use crate::issues::{IssueReason, record_rejection_in};
use crate::replay::{ReplayError, Replayed, replay_in};
use crate::storage::Store;
use bb_protocol::receipt::{CommandLookup, LookupStatus, Outcome, Receipt};
use bb_protocol::wire::{CommandId, Wire};
use rusqlite::{OptionalExtension, Transaction, params};

/// What a receipt did to its command.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Settlement {
    /// Accepted with changes, not yet in the confirmed base: waiting for its
    /// feed transaction.
    AwaitingFeed,
    /// Done: a no-op, or accepted and already covered by the confirmed base.
    Completed,
    /// Terminally rejected: the command is an issue now.
    Rejected,
    /// The receipt was already applied.
    Unchanged,
}

/// The result of applying one receipt.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Settled {
    pub command_id: CommandId,
    pub settlement: Settlement,
    /// The replay that followed, unless nothing changed.
    pub replayed: Option<Replayed>,
}

/// What a `GET commands/{id}` lookup came to.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Looked {
    /// Processing is unfinished at the server. An observation only.
    Pending(CommandId),
    /// No record at lookup time. Not proof the command never commits.
    NotFound(CommandId),
    Settled(Settled),
}

/// Applies a terminal receipt. See the module documentation.
///
/// # Errors
///
/// [`ApplyError`]; whatever it is, nothing was saved.
pub fn apply_receipt(
    store: &mut Store,
    context: &ExecuteContext,
    fence: &Fence,
    receipt: &Receipt,
) -> Result<Settled, ApplyError> {
    store.try_write(|tx| receipt_in(tx, context, fence, receipt))
}

/// Applies the answer of a receipt lookup: a terminal one like
/// [`apply_receipt`]; `pending` and `not_found` change nothing and license no
/// new command ID.
///
/// # Errors
///
/// As [`apply_receipt`].
pub fn apply_lookup(
    store: &mut Store,
    context: &ExecuteContext,
    fence: &Fence,
    lookup: &CommandLookup,
) -> Result<Looked, ApplyError> {
    match &lookup.status {
        LookupStatus::Terminal { receipt } => {
            apply_receipt(store, context, fence, receipt).map(Looked::Settled)
        }
        LookupStatus::Pending { command_id } => Ok(Looked::Pending(command_id.clone())),
        LookupStatus::NotFound { command_id } => Ok(Looked::NotFound(command_id.clone())),
    }
}

fn receipt_in(
    tx: &Transaction<'_>,
    context: &ExecuteContext,
    fence: &Fence,
    receipt: &Receipt,
) -> Result<Settled, ApplyError> {
    let base = read_base(tx, fence)?;
    check_common(&base, &receipt.common)?;
    receipt
        .validate()
        .map_err(|_| ApplyError::Malformed("receipt"))?;
    // A retryable error is not terminal: the command must be tried again.
    if receipt.error.as_ref().is_some_and(|error| error.retryable) {
        return Err(ApplyError::Malformed(
            "a terminal receipt that is retryable",
        ));
    }
    let workspace_id = base.workspace_id.as_str();
    let command = receipt.command_id.as_str();
    let row: Option<(String, i64)> = tx
        .query_row(
            "SELECT state, ever_sent FROM outbox WHERE workspace_id = ?1 AND command_id = ?2",
            params![workspace_id, command],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    let Some((state, ever_sent)) = row else {
        return Err(ApplyError::UnknownCommand);
    };
    let ever_sent = ever_sent != 0;
    let kind = match (receipt.outcome, receipt.has_changes) {
        (Outcome::Rejected, _) => "rejected",
        (Outcome::Accepted, true) => "accepted",
        (Outcome::Accepted, false) => "no_op",
    };
    store_receipt(tx, workspace_id, receipt, kind, context)?;

    // A receipt can only be for a command that was sent.
    if !ever_sent && matches!(state.as_str(), "queued" | "blocked_dependency") {
        return Err(ApplyError::NeverSent);
    }
    let settled = |settlement, replayed| Settled {
        command_id: receipt.command_id.clone(),
        settlement,
        replayed,
    };
    let set_state = |state: &str| {
        tx.execute(
            "UPDATE outbox SET state = ?3 WHERE workspace_id = ?1 AND command_id = ?2",
            params![workspace_id, command, state],
        )
    };
    match (kind, state.as_str()) {
        ("rejected", "rejected") | ("accepted" | "no_op", "completed") => {
            Ok(settled(Settlement::Unchanged, None))
        }
        ("rejected", _) => {
            let reason = receipt
                .error
                .as_ref()
                .map_or(IssueReason::Validation("rejected".to_owned()), |error| {
                    IssueReason::from_code(&error.code)
                });
            match record_rejection_in(tx, context, &receipt.command_id, &reason) {
                Ok(replayed) => Ok(settled(Settlement::Rejected, Some(replayed))),
                Err(ReplayError::NotRejectable { .. }) => Err(ApplyError::Contradiction(
                    "a rejection for a command the server accepted",
                )),
                Err(error) => Err(error.into()),
            }
        }
        (_, "rejected") => Err(ApplyError::Contradiction(
            "an acceptance for a command the server rejected",
        )),
        (kind, _) => {
            let covered = match receipt.commit_seq.as_ref() {
                Some(seq) => {
                    let seq = seq.to_u64().ok_or(ApplyError::Malformed("commit_seq"))?;
                    base.watermark().is_some_and(|watermark| seq <= watermark)
                }
                None => true, // a no-op has no feed transaction to wait for
            };
            let done = kind == "no_op" || covered;
            set_state(if done {
                "completed"
            } else {
                "accepted_awaiting_feed"
            })?;
            let replayed = replay_in(tx, context)?;
            Ok(settled(
                if done {
                    Settlement::Completed
                } else {
                    Settlement::AwaitingFeed
                },
                Some(replayed),
            ))
        }
    }
}

/// Keeps the verified receipt under its server generation. A stored one with
/// another outcome or sequence is a contradiction; the same one is kept as is.
fn store_receipt(
    tx: &Transaction<'_>,
    workspace_id: &str,
    receipt: &Receipt,
    kind: &str,
    context: &ExecuteContext,
) -> Result<(), ApplyError> {
    let generation = receipt.common.server_generation.as_str();
    let commit_seq = receipt.commit_seq.as_ref().map(|seq| seq.as_str());
    let stored: Option<(String, Option<String>)> = tx
        .query_row(
            "SELECT outcome, commit_seq FROM command_receipts
             WHERE workspace_id = ?1 AND command_id = ?2 AND server_generation = ?3",
            params![workspace_id, receipt.command_id.as_str(), generation],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    if let Some((outcome, seq)) = stored {
        return if outcome == kind && seq.as_deref() == commit_seq {
            Ok(())
        } else {
            Err(ApplyError::Contradiction(
                "a receipt differs from the stored one",
            ))
        };
    }
    let bytes = serde_json::to_vec(receipt).map_err(|_| ApplyError::Malformed("receipt"))?;
    tx.execute(
        "INSERT INTO command_receipts (workspace_id, command_id, server_generation, outcome,
            commit_seq, receipt, verified_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        params![
            workspace_id,
            receipt.command_id.as_str(),
            generation,
            kind,
            commit_seq,
            bytes,
            context.now.as_str(),
        ],
    )?;
    Ok(())
}
