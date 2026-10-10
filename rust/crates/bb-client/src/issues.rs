//! Sync issues: rejected intents kept for the user, and how they are resolved.
//!
//! A terminal rejection (a server receipt, or [`crate::replay`] finding that a
//! never-sent command no longer applies) never deletes the intent. The command
//! stays in the outbox as `rejected` with its immutable envelope, and a
//! `sync_issues` row keeps the user's text, the revision they were shown and
//! the commands held behind it (`blocked_dependency`, each with an issue of its
//! own). The current record is read from the confirmed base when an issue is
//! shown, so a deletion is shown as a deletion.
//!
//! Resolution is explicit and atomic ([`resolve_issue`], the `resolve_issue` call
//! of runtime-ffi.md):
//!
//! * **Keep my version** queues a *new* command (new ID, `supersedes_command_id`
//!   set) against the revision the user was shown. If the record changed again,
//!   nothing is saved ([`IssueError::ChangedAgain`]); there is no force write,
//!   and a record deleted elsewhere is never recreated.
//! * **Use the current version / keep deleted** dismisses the intent. The issue
//!   keeps its text and intent for recovery and export.
//! * Every action held behind the issue gets an explicit choice: keep for later
//!   (still held, still an issue), review and retry (a new command the caller
//!   approved against the shown version, in the approved dependency chain), or
//!   confirmed discard. Nothing is decided by omission.
//! * Only commands the server provably rejected, or never sent, are replaced or
//!   discarded. An unknown outcome is reconciled first, never rekeyed.
//!
//! The decision a user is making, including approvals and discard
//! confirmations, is a [`DecisionDraft`]. It is stored as a draft, restored
//! after a restart, never submitted by itself, and loses its retry approvals
//! when the record changed since it was shown.

use crate::execute::{
    ExecuteContext, ExecuteError, ExecuteRequest, IdSource, execute_in, shown_key,
};
use crate::replay::{ReplayError, Replayed, replay_in};
use crate::storage::{Store, StoreError};
use bb_domain::types::Reason;
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::Precondition;
use bb_protocol::wire::{CommandId, Id};
use rusqlite::{OptionalExtension, Transaction, params};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, HashMap, HashSet};

/// The payload members that hold text the user wrote.
const TEXT_FIELDS: [&str; 7] = [
    "title",
    "details",
    "waiting_for",
    "name",
    "desired_outcome",
    "body",
    "reason_text",
];

// ------------------------------------------------------------------------ the types

/// Why a command became an issue. The code is the receipt error code, or the
/// canonical validation reason.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum IssueReason {
    /// The record's edit revision is not the one the user was shown.
    RevisionConflict,
    /// The record was deleted elsewhere. It is never recreated.
    EntityDeleted,
    /// A command this one builds on was rejected.
    DependencyRejected,
    /// Held, not dropped, behind a rejected command.
    BlockedDependency,
    /// The rules refuse it for another canonical reason.
    Validation(String),
}

impl IssueReason {
    pub fn code(&self) -> String {
        match self {
            Self::RevisionConflict => "REVISION_CONFLICT".to_owned(),
            Self::EntityDeleted => "ENTITY_DELETED".to_owned(),
            Self::DependencyRejected => "DEPENDENCY_REJECTED".to_owned(),
            Self::BlockedDependency => "BLOCKED_DEPENDENCY".to_owned(),
            Self::Validation(reason) => reason.clone(),
        }
    }

    pub fn from_code(code: &str) -> Self {
        match code {
            "REVISION_CONFLICT" => Self::RevisionConflict,
            "ENTITY_DELETED" => Self::EntityDeleted,
            "DEPENDENCY_REJECTED" => Self::DependencyRejected,
            "BLOCKED_DEPENDENCY" => Self::BlockedDependency,
            other => Self::Validation(other.to_owned()),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum IssueState {
    Open,
    /// The intent was dropped by an explicit choice.
    Dismissed,
    /// A new command took its place.
    Replaced,
    /// The server's data proved the outcome.
    Reconciled,
}

impl IssueState {
    fn parse(text: &str) -> Option<Self> {
        Some(match text {
            "open" => Self::Open,
            "dismissed" => Self::Dismissed,
            "replaced" => Self::Replaced,
            "reconciled" => Self::Reconciled,
            _ => return None,
        })
    }
}

/// One saved issue.
#[derive(Clone, Debug, PartialEq)]
pub struct Issue {
    pub issue_id: String,
    pub command_id: CommandId,
    pub reason: IssueReason,
    /// The immutable envelope of the rejected intent.
    pub local_intent: Value,
    /// The text the user wrote, by payload member.
    pub local_text: Option<Value>,
    /// The edit revision the user was shown when they made the change.
    pub shown_base_revision: Option<String>,
    /// The actions held behind this one, in queue order.
    pub dependent_ids: Vec<CommandId>,
    pub state: IssueState,
    pub created_at: String,
    pub resolved_at: Option<String>,
}

/// The record as the confirmed base holds it now.
#[derive(Clone, Debug, PartialEq)]
pub struct CurrentRecord {
    pub entity_type: String,
    pub record_version: String,
    pub edit_revision: Option<String>,
    pub deleted: bool,
    /// `None` for a tombstone.
    pub record: Option<Value>,
}

/// An issue with the data a resolution screen compares it with.
#[derive(Clone, Debug, PartialEq)]
pub struct IssueView {
    pub issue: Issue,
    pub current: Option<CurrentRecord>,
}

/// Why an issue operation was refused; whatever it is, nothing was saved.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum IssueError {
    Store(StoreError),
    UnknownIssue,
    AlreadyResolved,
    /// The command may have reached the server: reconcile it first.
    NotResolvable,
    /// A record deleted elsewhere is not recreated by a replacement.
    EntityDeleted,
    /// The record changed after the user was shown it: review both again.
    ChangedAgain,
    InvalidChoice(&'static str),
    /// A held action has no explicit choice.
    DependentChoiceRequired(CommandId),
    UnknownDependent(CommandId),
    DiscardNotConfirmed(CommandId),
    /// A replacement must be a new command: its ID is already in the queue.
    ReplacementIdReused(CommandId),
    Execute(ExecuteError),
}

impl IssueError {
    /// The stable code the bindings carry across FFI.
    pub fn code(&self) -> &'static str {
        match self {
            Self::Store(error) => error.code(),
            Self::UnknownIssue => "UNKNOWN_ISSUE",
            Self::AlreadyResolved => "ISSUE_ALREADY_RESOLVED",
            Self::NotResolvable => "ISSUE_NOT_RESOLVABLE",
            Self::EntityDeleted => "ENTITY_DELETED",
            Self::ChangedAgain => "REVISION_CONFLICT",
            Self::InvalidChoice(_) => "INVALID_CHOICE",
            Self::DependentChoiceRequired(_) => "DEPENDENT_CHOICE_REQUIRED",
            Self::UnknownDependent(_) => "UNKNOWN_DEPENDENT",
            Self::DiscardNotConfirmed(_) => "DISCARD_NOT_CONFIRMED",
            Self::ReplacementIdReused(_) => "REPLACEMENT_ID_REUSED",
            Self::Execute(error) => error.code(),
        }
    }
}

impl std::fmt::Display for IssueError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}

impl std::error::Error for IssueError {}

impl From<StoreError> for IssueError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}

impl From<rusqlite::Error> for IssueError {
    fn from(error: rusqlite::Error) -> Self {
        Self::Store(error.into())
    }
}

fn corrupt<E>(_: E) -> IssueError {
    StoreError::Corrupt.into()
}

// ------------------------------------------------------------------ opening an issue

/// Saves the issue for a command, once. The immutable envelope and the user's
/// text are copied into it, so they outlive any later queue change.
pub(crate) fn open(
    tx: &Transaction<'_>,
    workspace_id: &str,
    command_id: &str,
    envelope: &[u8],
    reason: &IssueReason,
    now: &str,
) -> rusqlite::Result<()> {
    let intent: Value = serde_json::from_slice(envelope).unwrap_or(Value::Null);
    let mut text = Map::new();
    for field in TEXT_FIELDS {
        match intent.pointer(&format!("/payload/{field}")) {
            Some(value) if value.is_string() => drop(text.insert(field.to_owned(), value.clone())),
            _ => {}
        }
    }
    let target = intent.get("entity_id").and_then(Value::as_str);
    let shown = intent
        .get("preconditions")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .find(|p| p.get("entity_id").and_then(Value::as_str) == target)
        .and_then(|p| p.get("edit_revision"))
        .and_then(Value::as_str);
    tx.execute(
        "INSERT OR IGNORE INTO sync_issues (workspace_id, issue_id, command_id, reason,
            local_intent, local_text, shown_base_revision, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
        params![
            workspace_id,
            format!("issue_{command_id}"),
            command_id,
            reason.code(),
            envelope,
            (!text.is_empty()).then(|| Value::Object(text).to_string()),
            shown,
            now,
        ],
    )?;
    Ok(())
}

/// The queue's dependency graph, for finding what is held behind a command.
struct Graph {
    /// `command -> the commands that depend on it`.
    children: HashMap<String, Vec<String>>,
    /// `command -> (state, local sequence)`.
    states: HashMap<String, (String, i64)>,
}

impl Graph {
    fn load(tx: &Transaction<'_>, workspace_id: &str) -> rusqlite::Result<Self> {
        let mut graph = Self {
            children: HashMap::new(),
            states: HashMap::new(),
        };
        let mut edges = tx.prepare(
            "SELECT depends_on, command_id FROM outbox_dependencies WHERE workspace_id = ?1",
        )?;
        for edge in edges.query_map([workspace_id], |row| Ok((row.get(0)?, row.get(1)?)))? {
            let (parent, child): (String, String) = edge?;
            graph.children.entry(parent).or_default().push(child);
        }
        let mut states =
            tx.prepare("SELECT command_id, state, local_seq FROM outbox WHERE workspace_id = ?1")?;
        for row in states.query_map([workspace_id], |row| {
            Ok((row.get(0)?, (row.get(1)?, row.get(2)?)))
        })? {
            let (command, state) = row?;
            graph.states.insert(command, state);
        }
        Ok(graph)
    }

    /// The actions still held behind `root`, directly or through others, in
    /// queue order.
    fn held_behind(&self, root: &str) -> Vec<String> {
        let (mut seen, mut stack) = (HashSet::new(), vec![root]);
        let mut held: Vec<(i64, &str)> = Vec::new();
        while let Some(command) = stack.pop() {
            for child in self.children.get(command).into_iter().flatten() {
                if seen.insert(child.as_str()) {
                    stack.push(child);
                    if let Some((state, sequence)) = self.states.get(child)
                        && state == "blocked_dependency"
                    {
                        held.push((*sequence, child));
                    }
                }
            }
        }
        held.sort_unstable();
        held.into_iter().map(|(_, id)| id.to_owned()).collect()
    }
}

/// Refreshes the held-action list of every open issue.
pub(crate) fn refresh_dependents(tx: &Transaction<'_>, workspace_id: &str) -> rusqlite::Result<()> {
    let graph = Graph::load(tx, workspace_id)?;
    let open: Vec<(String, String, String)> = {
        let mut statement = tx.prepare(
            "SELECT issue_id, command_id, dependent_ids FROM sync_issues
             WHERE workspace_id = ?1 AND resolution = 'open'",
        )?;
        let rows = statement.query_map([workspace_id], |row| {
            Ok((row.get(0)?, row.get(1)?, row.get(2)?))
        })?;
        rows.collect::<Result<_, _>>()?
    };
    for (issue_id, command_id, stored) in open {
        let held = json!(graph.held_behind(&command_id)).to_string();
        if held != stored {
            tx.execute(
                "UPDATE sync_issues SET dependent_ids = ?3
                 WHERE workspace_id = ?1 AND issue_id = ?2",
                params![workspace_id, issue_id, held],
            )?;
        }
    }
    Ok(())
}

// --------------------------------------------------------------------- a rejection

/// Records a terminal rejection of a queued command (a rejected receipt, as
/// the receipt application of a later slice calls it): the command becomes
/// `rejected` with an open issue, everything built on it is held, and the
/// visible projection is rebuilt without it. Independent commands are not
/// touched. Repeating it changes nothing.
///
/// # Errors
///
/// [`ReplayError::NotRejectable`] for a command the server already accepted.
pub fn record_rejection(
    store: &mut Store,
    context: &ExecuteContext,
    command_id: &CommandId,
    reason: &IssueReason,
) -> Result<Replayed, ReplayError> {
    store.try_write(|tx| record_rejection_in(tx, context, command_id, reason))
}

/// [`record_rejection`] inside the caller's write transaction.
///
/// # Errors
///
/// As [`record_rejection`].
pub fn record_rejection_in(
    tx: &Transaction<'_>,
    context: &ExecuteContext,
    command_id: &CommandId,
    reason: &IssueReason,
) -> Result<Replayed, ReplayError> {
    let row: Option<(String, String, Vec<u8>)> = tx
        .query_row(
            "SELECT workspace_id, state, envelope FROM outbox WHERE command_id = ?1",
            [command_id.as_str()],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .optional()?;
    let Some((workspace_id, state, envelope)) = row else {
        return Err(ReplayError::UnknownCommand);
    };
    match state.as_str() {
        "queued" | "sending" | "unknown" => {
            open(
                tx,
                &workspace_id,
                command_id.as_str(),
                &envelope,
                reason,
                context.now.as_str(),
            )?;
            tx.execute(
                "UPDATE outbox SET state = 'rejected' WHERE workspace_id = ?1 AND command_id = ?2",
                params![workspace_id, command_id.as_str()],
            )?;
        }
        "rejected" => {}
        _ => return Err(ReplayError::NotRejectable { state }),
    }
    replay_in(tx, context)
}

// ----------------------------------------------------------------------- reading

type RawIssue = (
    String,
    String,
    String,
    Vec<u8>,
    Option<String>,
    Option<String>,
    String,
    String,
    String,
    Option<String>,
);

fn select_issues(
    tx: &Transaction<'_>,
    workspace_id: &str,
    filter: &str,
    argument: &str,
) -> Result<Vec<Issue>, IssueError> {
    let mut statement = tx.prepare(&format!(
        "SELECT i.issue_id, i.command_id, i.reason, i.local_intent, i.local_text,
                i.shown_base_revision, i.dependent_ids, i.resolution, i.created_at, i.resolved_at
         FROM sync_issues i
         LEFT JOIN outbox o ON o.workspace_id = i.workspace_id AND o.command_id = i.command_id
         WHERE i.workspace_id = ?1 AND {filter}
         ORDER BY o.local_seq, i.issue_id"
    ))?;
    let rows = statement.query_map(params![workspace_id, argument], |row| {
        Ok((
            row.get(0)?,
            row.get(1)?,
            row.get(2)?,
            row.get(3)?,
            row.get(4)?,
            row.get(5)?,
            row.get(6)?,
            row.get(7)?,
            row.get(8)?,
            row.get(9)?,
        ))
    })?;
    let mut issues = Vec::new();
    for row in rows {
        let raw: RawIssue = row?;
        let dependents: Vec<String> = serde_json::from_str(&raw.6).map_err(corrupt)?;
        issues.push(Issue {
            issue_id: raw.0,
            command_id: CommandId::parse(raw.1).map_err(corrupt)?,
            reason: IssueReason::from_code(&raw.2),
            local_intent: serde_json::from_slice(&raw.3).map_err(corrupt)?,
            local_text: raw
                .4
                .map(|text| serde_json::from_str(&text).map_err(corrupt))
                .transpose()?,
            shown_base_revision: raw.5,
            dependent_ids: dependents
                .into_iter()
                .map(|id| CommandId::parse(id).map_err(corrupt))
                .collect::<Result<_, _>>()?,
            state: IssueState::parse(&raw.7).ok_or_else(|| corrupt(()))?,
            created_at: raw.8,
            resolved_at: raw.9,
        });
    }
    Ok(issues)
}

type RawCurrent = (String, String, Option<String>, i64, Option<Vec<u8>>);

/// The record type and key an intent's target is stored under. The Review
/// settings are a singleton under the empty key, whatever scope ID the command
/// names; the type comes from the precondition on the target (or the command
/// itself). Records of different types can share a key (a Review session and
/// its decision queue are both `[session_id]`), so a known type narrows the
/// lookup.
fn target_key(intent: &Value) -> Option<(Option<EntityType>, String)> {
    let target = intent.get("entity_id")?.as_str()?;
    let checked = |precondition: &&Value| {
        let named = precondition.get("after_command").unwrap_or(precondition);
        named.get("entity_id").and_then(Value::as_str) == Some(target)
    };
    let entity_type = intent
        .get("preconditions")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .find(checked)
        .and_then(|precondition| {
            let named = precondition.get("after_command").unwrap_or(precondition);
            EntityType::from_wire(named.get("entity_type")?.as_str()?)
        })
        .or_else(|| {
            (intent.get("type")?.as_str()? == "review.settings")
                .then_some(EntityType::ReviewSettings)
        });
    Some((
        entity_type,
        shown_key(entity_type.unwrap_or(EntityType::Task), target),
    ))
}

/// The record the confirmed base holds for a target now.
fn current_of(
    tx: &Transaction<'_>,
    workspace_id: &str,
    issue: &Issue,
) -> Result<Option<CurrentRecord>, IssueError> {
    let Some((entity_type, key)) = target_key(&issue.local_intent) else {
        return Ok(None);
    };
    let row: Option<RawCurrent> = tx
        .query_row(
            "SELECT record_type, record_version, edit_revision, tombstone, body
             FROM confirmed_records
             WHERE workspace_id = ?1 AND record_key = ?2
               AND (?3 IS NULL OR record_type = ?3)",
            params![workspace_id, key, entity_type.map(EntityType::as_str)],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                ))
            },
        )
        .optional()?;
    row.map(
        |(entity_type, record_version, edit_revision, tombstone, body)| {
            Ok(CurrentRecord {
                entity_type,
                record_version,
                edit_revision,
                deleted: tombstone != 0,
                record: body
                    .map(|bytes| serde_json::from_slice(&bytes).map_err(corrupt))
                    .transpose()?,
            })
        },
    )
    .transpose()
}

fn reading<T>(
    store: &mut Store,
    body: impl FnOnce(&Transaction<'_>, &str) -> Result<T, IssueError>,
) -> Result<T, IssueError> {
    store.read(|tx| {
        let workspace_id: String =
            tx.query_row("SELECT workspace_id FROM sync_meta", [], |row| row.get(0))?;
        Ok(body(tx, &workspace_id))
    })?
}

fn view(tx: &Transaction<'_>, workspace_id: &str, issue: Issue) -> Result<IssueView, IssueError> {
    let current = current_of(tx, workspace_id, &issue)?;
    Ok(IssueView { issue, current })
}

/// Every open issue, in queue order, with the record it conflicts with.
///
/// # Errors
///
/// [`IssueError::Store`] only.
pub fn open_issues(store: &mut Store) -> Result<Vec<IssueView>, IssueError> {
    reading(store, |tx, workspace_id| {
        select_issues(tx, workspace_id, "i.resolution = ?2", "open")?
            .into_iter()
            .map(|issue| view(tx, workspace_id, issue))
            .collect()
    })
}

/// One issue, open or resolved.
///
/// # Errors
///
/// [`IssueError::Store`] only.
pub fn issue(store: &mut Store, issue_id: &str) -> Result<Option<IssueView>, IssueError> {
    reading(store, |tx, workspace_id| {
        select_issues(tx, workspace_id, "i.issue_id = ?2", issue_id)?
            .into_iter()
            .next()
            .map(|issue| view(tx, workspace_id, issue))
            .transpose()
    })
}

// -------------------------------------------------------------------- resolving

/// A new command that takes the place of a rejected or held one: a new ID,
/// the revisions the user was shown (or an `after_command` on another
/// replacement), and the approved dependency chain.
#[derive(Clone, Debug)]
pub struct Replacement {
    pub command_id: CommandId,
    pub shown: Vec<Precondition>,
    pub depends_on: Vec<CommandId>,
}

/// What to do with the rejected intent itself.
#[derive(Clone, Debug)]
pub enum Choice {
    /// Use the current version, or keep the item deleted. The intent is
    /// dropped by this explicit choice and stays in the issue.
    UseCurrent,
    /// Keep my version: queue it again against the shown version.
    KeepMine(Replacement),
}

/// What to do with an action held behind the issue.
#[derive(Clone, Debug)]
pub enum DependentChoice {
    /// Still held, still an issue, even after the issue it waited for is gone.
    KeepForLater,
    /// The user reviewed and approved a replacement.
    Retry(Replacement),
    /// Dropped. `confirmed` is true only after the user confirmed the named list.
    Discard { confirmed: bool },
}

#[derive(Clone, Debug)]
pub struct ResolveRequest {
    pub issue_id: String,
    pub choice: Choice,
    /// A choice for every action currently held behind the issue.
    pub dependents: Vec<(CommandId, DependentChoice)>,
    /// The instant, zone and policy the replacements are decided with.
    pub context: ExecuteContext,
}

/// What a resolution did.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Resolved {
    /// `(old, new)` for every command replaced.
    pub replaced: Vec<(CommandId, CommandId)>,
    pub discarded: Vec<CommandId>,
    pub kept: Vec<CommandId>,
    /// True when this answers a retry of an already stored resolution.
    pub repeated: bool,
}

/// Resolves one issue in one transaction. See the module documentation.
///
/// # Errors
///
/// [`IssueError`]; whatever it is, nothing was saved.
pub fn resolve_issue(
    store: &mut Store,
    ids: &mut impl IdSource,
    request: &ResolveRequest,
) -> Result<Resolved, IssueError> {
    store.try_write(|tx| {
        let workspace_id: String =
            tx.query_row("SELECT workspace_id FROM sync_meta", [], |row| row.get(0))?;
        resolve_in(tx, ids, &workspace_id, request)
    })
}

fn resolve_in(
    tx: &Transaction<'_>,
    ids: &mut impl IdSource,
    workspace_id: &str,
    request: &ResolveRequest,
) -> Result<Resolved, IssueError> {
    let issue = select_issues(tx, workspace_id, "i.issue_id = ?2", &request.issue_id)?
        .into_iter()
        .next()
        .ok_or(IssueError::UnknownIssue)?;
    let command = issue.command_id.as_str();
    if issue.state != IssueState::Open {
        let replacement = replacement_of(tx, workspace_id, command)?;
        return match (&request.choice, issue.state, replacement) {
            (Choice::KeepMine(r), IssueState::Replaced, Some(done)) if done == r.command_id => {
                Ok(Resolved {
                    replaced: vec![(issue.command_id, done)],
                    repeated: true,
                    ..Resolved::default()
                })
            }
            (Choice::UseCurrent, IssueState::Dismissed, _) => Ok(Resolved {
                repeated: true,
                ..Resolved::default()
            }),
            _ => Err(IssueError::AlreadyResolved),
        };
    }
    // Only a rejection the server gave, or a command never sent, may be
    // replaced or dropped: an uncertain outcome is reconciled first.
    ensure_resolvable(tx, workspace_id, command)?;

    let held = Graph::load(tx, workspace_id)?.held_behind(command);
    let mut choices: BTreeMap<&str, &DependentChoice> = BTreeMap::new();
    for (id, choice) in &request.dependents {
        if !held.iter().any(|held| held == id.as_str()) {
            return Err(IssueError::UnknownDependent(id.clone()));
        }
        if choices.insert(id.as_str(), choice).is_some() {
            return Err(IssueError::InvalidChoice("duplicate dependent choice"));
        }
        if matches!(choice, DependentChoice::Discard { confirmed: false }) {
            return Err(IssueError::DiscardNotConfirmed(id.clone()));
        }
    }
    let mut resolved = Resolved::default();
    let now = request.context.now.as_str();

    match &request.choice {
        Choice::UseCurrent => close(tx, workspace_id, command, "dismissed", None, now)?,
        Choice::KeepMine(replacement) => {
            if issue.reason == IssueReason::EntityDeleted {
                return Err(IssueError::EntityDeleted);
            }
            replace(
                tx,
                ids,
                workspace_id,
                command,
                replacement,
                &request.context,
            )?;
            resolved
                .replaced
                .push((issue.command_id.clone(), replacement.command_id.clone()));
        }
    }
    // Held actions in queue order: a retry may build on an earlier replacement.
    for id in &held {
        let Some(choice) = choices.get(id.as_str()) else {
            return Err(IssueError::DependentChoiceRequired(
                CommandId::parse(id.clone()).map_err(corrupt)?,
            ));
        };
        let command_id = CommandId::parse(id.clone()).map_err(corrupt)?;
        match choice {
            DependentChoice::KeepForLater => resolved.kept.push(command_id),
            DependentChoice::Retry(replacement) => {
                replace(tx, ids, workspace_id, id, replacement, &request.context)?;
                resolved
                    .replaced
                    .push((command_id, replacement.command_id.clone()));
            }
            DependentChoice::Discard { .. } => {
                close(tx, workspace_id, id, "dismissed", None, now)?;
                resolved.discarded.push(command_id);
            }
        }
    }
    tx.execute(
        "DELETE FROM drafts WHERE workspace_id = ?1 AND draft_id = ?2",
        params![workspace_id, draft_id(&request.issue_id)],
    )?;
    refresh_dependents(tx, workspace_id)?;
    Ok(resolved)
}

fn replacement_of(
    tx: &Transaction<'_>,
    workspace_id: &str,
    command_id: &str,
) -> Result<Option<CommandId>, IssueError> {
    let stored: Option<Option<String>> = tx
        .query_row(
            "SELECT superseded_by FROM outbox WHERE workspace_id = ?1 AND command_id = ?2",
            params![workspace_id, command_id],
            |row| row.get(0),
        )
        .optional()?;
    stored
        .flatten()
        .map(|id| CommandId::parse(id).map_err(corrupt))
        .transpose()
}

fn ensure_resolvable(
    tx: &Transaction<'_>,
    workspace_id: &str,
    command_id: &str,
) -> Result<(), IssueError> {
    let row: Option<(String, i64)> = tx
        .query_row(
            "SELECT state, ever_sent FROM outbox WHERE workspace_id = ?1 AND command_id = ?2",
            params![workspace_id, command_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    match row {
        Some((state, _)) if state == "rejected" => Ok(()),
        Some((state, 0)) if state == "blocked_dependency" => Ok(()),
        _ => Err(IssueError::NotResolvable),
    }
}

/// Ends a command's part in the queue: it stays as a terminal `rejected` row,
/// pointing at its replacement when it has one, and its issue is resolved.
fn close(
    tx: &Transaction<'_>,
    workspace_id: &str,
    command_id: &str,
    resolution: &str,
    superseded_by: Option<&CommandId>,
    now: &str,
) -> Result<(), IssueError> {
    tx.execute(
        "UPDATE outbox SET state = 'rejected', superseded_by = ?3
         WHERE workspace_id = ?1 AND command_id = ?2",
        params![
            workspace_id,
            command_id,
            superseded_by.map(CommandId::as_str)
        ],
    )?;
    tx.execute(
        "UPDATE sync_issues SET resolution = ?3, resolved_at = ?4
         WHERE workspace_id = ?1 AND command_id = ?2 AND resolution = 'open'",
        params![workspace_id, command_id, resolution, now],
    )?;
    Ok(())
}

/// Queues `replacement` in place of `old`: the same command and target, a new
/// identity, decided against the version the caller approved.
fn replace(
    tx: &Transaction<'_>,
    ids: &mut impl IdSource,
    workspace_id: &str,
    old: &str,
    replacement: &Replacement,
    context: &ExecuteContext,
) -> Result<(), IssueError> {
    ensure_resolvable(tx, workspace_id, old)?;
    let reused: Option<i64> = tx
        .query_row(
            "SELECT 1 FROM outbox WHERE workspace_id = ?1 AND command_id = ?2",
            params![workspace_id, replacement.command_id.as_str()],
            |row| row.get(0),
        )
        .optional()?;
    if reused.is_some() {
        return Err(IssueError::ReplacementIdReused(
            replacement.command_id.clone(),
        ));
    }
    for dependency in &replacement.depends_on {
        let state: Option<String> = tx
            .query_row(
                "SELECT state FROM outbox WHERE workspace_id = ?1 AND command_id = ?2",
                params![workspace_id, dependency.as_str()],
                |row| row.get(0),
            )
            .optional()?;
        if matches!(
            state.as_deref(),
            None | Some("rejected" | "blocked_dependency")
        ) {
            return Err(IssueError::InvalidChoice(
                "a replacement depends on a rejected command",
            ));
        }
    }
    let envelope: Vec<u8> = tx.query_row(
        "SELECT envelope FROM outbox WHERE workspace_id = ?1 AND command_id = ?2",
        params![workspace_id, old],
        |row| row.get(0),
    )?;
    // An account-less intent has no scope or device, so it is read as JSON.
    let stored: Value = serde_json::from_slice(&envelope).map_err(corrupt)?;
    let text = |member: &str| stored.get(member).and_then(Value::as_str);
    let command_type = text("type")
        .and_then(CommandType::from_wire)
        .ok_or(IssueError::NotResolvable)?;
    let payload = stored
        .get("payload")
        .and_then(Value::as_object)
        .ok_or_else(|| corrupt(()))?;
    let old_id = CommandId::parse(old).map_err(corrupt)?;
    let request = ExecuteRequest {
        command_id: replacement.command_id.clone(),
        command_type,
        entity_id: Some(Id::parse(text("entity_id").ok_or_else(|| corrupt(()))?).map_err(corrupt)?),
        payload: payload.clone(),
        preconditions: replacement.shown.clone(),
        depends_on: replacement.depends_on.clone(),
        admission_tokens: Vec::new(),
        context: context.clone(),
    };
    let queued = execute_in(tx, ids, &request, &old_id).map_err(|error| match error {
        ExecuteError::Refused(refusal) if refusal.reason == Reason::RevisionConflict => {
            IssueError::ChangedAgain
        }
        ExecuteError::Store(error) => IssueError::Store(error),
        other => IssueError::Execute(other),
    })?;
    // Closing the old command is only honest if a new one was written.
    if queued.replayed {
        return Err(IssueError::ReplacementIdReused(
            replacement.command_id.clone(),
        ));
    }
    close(
        tx,
        workspace_id,
        old,
        "replaced",
        Some(&replacement.command_id),
        context.now.as_str(),
    )
}

// ----------------------------------------------------------------------- drafts

/// What a dependent action's row on the resolution screen currently says.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DraftAction {
    KeepForLater,
    ReviewAndRetry,
    Discard,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DependentDraft {
    pub action: DraftAction,
    /// The retry preview was approved against `shown_revision`.
    pub approved: bool,
    /// The discard list (M-02/D-02 state .12) was confirmed.
    pub discard_confirmed: bool,
}

/// The unsent state of the resolution screen: the version choice, and for each
/// held action its preserve / re-approve / discard choice.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct DecisionDraft {
    /// The edit revision of the current record the user was shown.
    pub shown_revision: Option<String>,
    /// The version radio: `Some(true)` keep mine, `Some(false)` use current.
    pub keep_mine: Option<bool>,
    /// By held command ID.
    pub dependents: BTreeMap<String, DependentDraft>,
}

/// A restored draft.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LoadedDraft {
    pub draft: DecisionDraft,
    /// The record changed after the draft was made: retry approvals were
    /// cleared and the user must review both versions again.
    pub changed_again: bool,
}

fn draft_id(issue_id: &str) -> String {
    format!("resolve_{issue_id}")
}

/// Saves the unsent decision for an open issue. It is never submitted by this.
///
/// # Errors
///
/// [`IssueError::UnknownIssue`] for an issue that is not open.
pub fn save_draft(
    store: &mut Store,
    issue_id: &str,
    draft: &DecisionDraft,
    now: &str,
) -> Result<(), IssueError> {
    store.try_write(|tx| {
        let workspace_id: String =
            tx.query_row("SELECT workspace_id FROM sync_meta", [], |row| row.get(0))?;
        let open = select_issues(tx, &workspace_id, "i.issue_id = ?2", issue_id)?
            .into_iter()
            .any(|issue| issue.state == IssueState::Open);
        if !open {
            return Err(IssueError::UnknownIssue);
        }
        tx.execute(
            "INSERT OR REPLACE INTO drafts (workspace_id, draft_id, editor_kind, record_type,
                record_key, fields, base_revision, updated_at)
             VALUES (?1, ?2, 'issue_resolution', 'sync_issue', ?3, ?4, ?5, ?6)",
            params![
                workspace_id,
                draft_id(issue_id),
                issue_id,
                json!(draft).to_string().into_bytes(),
                draft.shown_revision,
                now,
            ],
        )?;
        Ok(())
    })
}

/// Restores the unsent decision for an issue, as it was left.
///
/// # Errors
///
/// [`IssueError::Store`] only.
pub fn load_draft(store: &mut Store, issue_id: &str) -> Result<Option<LoadedDraft>, IssueError> {
    reading(store, |tx, workspace_id| {
        let stored: Option<Vec<u8>> = tx
            .query_row(
                "SELECT fields FROM drafts WHERE workspace_id = ?1 AND draft_id = ?2",
                params![workspace_id, draft_id(issue_id)],
                |row| row.get(0),
            )
            .optional()?;
        let Some(stored) = stored else {
            return Ok(None);
        };
        let mut draft: DecisionDraft = serde_json::from_slice(&stored).map_err(corrupt)?;
        let current = select_issues(tx, workspace_id, "i.issue_id = ?2", issue_id)?
            .into_iter()
            .next()
            .map(|issue| current_of(tx, workspace_id, &issue))
            .transpose()?
            .flatten();
        let now_shown = current.and_then(|record| record.edit_revision);
        let changed_again = draft.shown_revision.is_some() && draft.shown_revision != now_shown;
        if changed_again {
            for dependent in draft.dependents.values_mut() {
                dependent.approved = false;
            }
        }
        Ok(Some(LoadedDraft {
            draft,
            changed_again,
        }))
    })
}
