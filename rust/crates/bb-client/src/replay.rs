//! Replay: `visible = confirmed + replay(allowed pending)` (sync-v1 section 1).
//!
//! [`replay_in`] rebuilds the visible projection inside one write transaction:
//! it loads the confirmed base, then decides every pending command again, in
//! queue order, over the result of the ones before it. What each outcome means
//! is the guarantee of this module:
//!
//! * A command that still applies is projected, and its stored local result
//!   (the versions later commands build on) is refreshed.
//! * A command **never sent** that no longer applies (the record changed
//!   elsewhere, or was deleted) becomes a `rejected` command with an open issue
//!   that keeps its immutable envelope and the text the user wrote. It is not
//!   projected, so a deleted record is never resurrected (026-FR-007/008).
//! * A never-sent command that depends on a rejected or blocked one becomes
//!   `blocked_dependency`, with its own issue. It is held, not dropped, and no
//!   other command is touched: independent work keeps flowing.
//! * A command that may already have reached the server (`ever_sent`, or
//!   awaiting its feed) is never judged here. The server's receipt decides, so
//!   replay leaves it exactly as it is and simply does not project it, and what
//!   depends on it waits with it (026-FR-010: no outcome is guessed or rekeyed).
//! * A durably bound Undo missing precisely its server-private beforeimage is
//!   deferred even when never sent. Its descendants wait; no public restoration
//!   or result version is invented, and independent commands still project.
//!
//! The confirmed base is read as stored (`record_type`, `record_key`, and the
//! record's `value` as `body`); tombstones are what keeps deletion final.
//! Rule IDs derive from the command ID, so replaying does not change them.

use crate::execute::{
    ExecuteContext, ExecuteError, LocalResults, RULE_VERSION, bound_account, edit_revision, file,
    has_bindings, local_result, private_undo_missing, record_from, rule_ids,
};
use crate::issues::{self, IssueReason};
use crate::storage::{Store, StoreError};
use bb_domain::dispatch;
use bb_domain::types::{
    DomainChange, DomainError, ExecutionInputs, ReadSet, Reason, Record, WriterOrigin,
};
use bb_protocol::catalog::EntityType;
use bb_protocol::command::{CommandEnvelope, Decoded, decode_command};
use bb_protocol::wire::{CommandId, RecordKey};
use rusqlite::{Transaction, params};
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashMap, HashSet};

/// Why a replay or a rejection could not be saved; whatever it is, nothing was.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ReplayError {
    Store(StoreError),
    /// The command is not in this workspace's outbox.
    UnknownCommand,
    /// The command was already accepted by the server (or finished), so it
    /// cannot be rejected.
    NotRejectable {
        state: String,
    },
}

impl ReplayError {
    /// The stable code the bindings carry across FFI.
    pub fn code(&self) -> &'static str {
        match self {
            Self::Store(error) => error.code(),
            Self::UnknownCommand => "UNKNOWN_COMMAND",
            Self::NotRejectable { .. } => "COMMAND_NOT_REJECTABLE",
        }
    }
}

impl std::fmt::Display for ReplayError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}

impl std::error::Error for ReplayError {}

impl From<StoreError> for ReplayError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}

impl From<rusqlite::Error> for ReplayError {
    fn from(error: rusqlite::Error) -> Self {
        Self::Store(error.into())
    }
}

impl From<ExecuteError> for ReplayError {
    fn from(error: ExecuteError) -> Self {
        match error {
            ExecuteError::Store(error) => Self::Store(error),
            _ => Self::Store(StoreError::Corrupt),
        }
    }
}

fn corrupt<E>(_: E) -> ReplayError {
    StoreError::Corrupt.into()
}

/// What one replay did.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Replayed {
    /// Pending commands projected over the base.
    pub applied: Vec<CommandId>,
    /// Never-sent commands that no longer apply: now `rejected`, with an issue.
    pub rejected: Vec<CommandId>,
    /// Never-sent commands held behind a rejected one: now `blocked_dependency`.
    pub blocked: Vec<CommandId>,
    /// Possibly-sent commands, bound Undo missing private proof, and descendants
    /// left to the server's verdict without changing their immutable intents.
    pub deferred: Vec<CommandId>,
    pub projection_generation: u64,
}

/// Replays the pending queue over the confirmed base. See the module
/// documentation.
///
/// # Errors
///
/// [`ReplayError`]; whatever it is, nothing was saved.
pub fn replay(store: &mut Store, context: &ExecuteContext) -> Result<Replayed, ReplayError> {
    store.try_write(|tx| replay_in(tx, context))
}

/// [`replay`] inside the caller's write transaction, for the feed and receipt
/// application that must change the base and replay in one commit.
///
/// # Errors
///
/// As [`replay`].
pub fn replay_in(tx: &Transaction<'_>, context: &ExecuteContext) -> Result<Replayed, ReplayError> {
    let (workspace_id, generation): (String, i64) = tx.query_row(
        "SELECT workspace_id, projection_generation FROM sync_meta",
        [],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    let mut base = Projection::confirmed(tx, &workspace_id)?;
    let mut local_facts = crate::localfacts::load(tx, &workspace_id)?;
    crate::localfacts::reset_visible(&mut local_facts);
    let queue = load_queue(tx, &workspace_id)?;
    let mut results = LocalResults::new();
    for command in &queue {
        results.insert(&command.id, command.local_result.as_deref())?;
    }
    let edges = load_edges(tx, &workspace_id)?;
    // A command with a verified acceptance has its result from the receipt, which
    // replay keeps: the server's bindings are the truth the prediction is not.
    let proven = proven_results(tx, &workspace_id)?;
    // The effect of these is not (or not provably) in the confirmed base, and
    // their result may differ from the prediction. What builds on them cannot be
    // judged against the base yet: it waits rather than being rejected for a
    // reference the base cannot resolve until the feed lands or a receipt says.
    let unproven: HashSet<&str> = queue
        .iter()
        .filter(|command| match command.state.as_str() {
            "accepted_awaiting_feed" => true,
            "completed" => {
                !proven.contains(command.id.as_str())
                    && command.local_result.as_deref().is_some_and(has_bindings)
            }
            _ => false,
        })
        .map(|command| command.id.as_str())
        .collect();

    let mut report = Replayed::default();
    let mut held: HashMap<String, Held> = HashMap::new();
    for command in &queue {
        let id = command.id.as_str();
        if matches!(command.state.as_str(), "rejected" | "blocked_dependency") {
            held.insert(id.to_owned(), Held::Rejected);
            continue;
        }
        if !matches!(
            command.state.as_str(),
            "queued" | "sending" | "unknown" | "accepted_awaiting_feed"
        ) {
            continue; // completed: already part of the confirmed base
        }
        // Only a command the server has never seen may be judged locally.
        let judgeable = command.state == "queued"
            && !command.ever_sent
            && !edges
                .get(id)
                .into_iter()
                .flatten()
                .any(|dependency| unproven.contains(dependency.as_str()));
        let cause = edges
            .get(id)
            .into_iter()
            .flatten()
            .filter_map(|dependency| held.get(dependency))
            .max()
            .copied();
        if let Some(cause) = cause {
            if cause == Held::Rejected && judgeable {
                issues::open(
                    tx,
                    &workspace_id,
                    id,
                    &command.envelope,
                    &IssueReason::BlockedDependency,
                    context.now.as_str(),
                )?;
                set_state(tx, &workspace_id, id, "blocked_dependency")?;
                report.blocked.push(command.id.clone());
                held.insert(id.to_owned(), Held::Rejected);
            } else {
                report.deferred.push(command.id.clone());
                held.insert(id.to_owned(), Held::Deferred);
            }
            continue;
        }
        let Some(envelope) = decode(&command.envelope, &workspace_id)? else {
            // A version this build cannot run stays queued and untouched.
            report.deferred.push(command.id.clone());
            held.insert(id.to_owned(), Held::Deferred);
            continue;
        };
        match decide(&base, &results, &envelope, context) {
            Ok(changes) => {
                for change in &changes.changes {
                    crate::localfacts::project(
                        &mut local_facts,
                        &base.read_set,
                        change,
                        &command.id,
                    );
                    base.install(change, &command.id);
                }
                if !proven.contains(id) {
                    let stored = local_result(&changes);
                    if command.local_result.as_deref() != Some(stored.as_slice()) {
                        tx.execute(
                            "UPDATE outbox SET local_result = ?3
                             WHERE workspace_id = ?1 AND command_id = ?2",
                            params![workspace_id, id, stored],
                        )?;
                    }
                    results.insert(&command.id, Some(&stored))?;
                }
                report.applied.push(command.id.clone());
            }
            Err(ReplayDecisionError::PrivateMissing(_)) if bound_account(tx)? => {
                report.deferred.push(command.id.clone());
                held.insert(id.to_owned(), Held::Deferred);
            }
            Err(
                ReplayDecisionError::Refused(reason) | ReplayDecisionError::PrivateMissing(reason),
            ) if judgeable => {
                issues::open(
                    tx,
                    &workspace_id,
                    id,
                    &command.envelope,
                    &reason,
                    context.now.as_str(),
                )?;
                set_state(tx, &workspace_id, id, "rejected")?;
                report.rejected.push(command.id.clone());
                held.insert(id.to_owned(), Held::Rejected);
            }
            Err(_) => {
                report.deferred.push(command.id.clone());
                held.insert(id.to_owned(), Held::Deferred);
            }
        }
    }

    issues::refresh_dependents(tx, &workspace_id)?;
    crate::localfacts::prune(tx, &workspace_id, &mut local_facts)?;
    let writes =
        base.save(tx, &workspace_id)? + crate::localfacts::save(tx, &workspace_id, &local_facts)?;
    let generation = generation + i64::from(writes > 0);
    // The projection is whole now, whatever state the store was upgraded from.
    tx.execute(
        "UPDATE sync_meta SET projection_generation = ?1, projection_stale = 0",
        [generation],
    )?;
    report.projection_generation = u64::try_from(generation).map_err(corrupt)?;
    Ok(report)
}

/// The commands the server accepted (a verified receipt of the generation the
/// base is built from): their stored result is the receipt's.
fn proven_results(
    tx: &Transaction<'_>,
    workspace_id: &str,
) -> Result<HashSet<String>, ReplayError> {
    let mut statement = tx.prepare(
        "SELECT r.command_id FROM command_receipts r
         JOIN sync_meta m ON m.workspace_id = r.workspace_id
                         AND m.server_generation = r.server_generation
         WHERE r.workspace_id = ?1 AND r.outcome IN ('accepted', 'no_op')",
    )?;
    let rows = statement.query_map([workspace_id], |row| row.get::<_, String>(0))?;
    Ok(rows.collect::<Result<_, _>>()?)
}

/// Why a pending command is not projected. `Rejected` outranks `Deferred`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
enum Held {
    Deferred,
    Rejected,
}

fn set_state(
    tx: &Transaction<'_>,
    workspace_id: &str,
    command_id: &str,
    state: &str,
) -> rusqlite::Result<()> {
    tx.execute(
        "UPDATE outbox SET state = ?3 WHERE workspace_id = ?1 AND command_id = ?2",
        params![workspace_id, command_id, state],
    )?;
    Ok(())
}

// ------------------------------------------------------------------------- deciding

enum ReplayDecisionError {
    Refused(IssueReason),
    PrivateMissing(IssueReason),
}

fn decide(
    base: &Projection,
    results: &LocalResults,
    envelope: &CommandEnvelope,
    context: &ExecuteContext,
) -> Result<bb_domain::types::ChangeSet, ReplayDecisionError> {
    let stable = &envelope.envelope;
    // A deleted record stays deleted, whatever a late command says about it.
    if base.deleted(&[stable.entity_id.as_str().to_owned()]) {
        return Err(ReplayDecisionError::Refused(IssueReason::EntityDeleted));
    }
    let inputs = ExecutionInputs {
        rule_version: RULE_VERSION,
        // The intent's own instant: replay must not move the rules' clock.
        now: stable.issued_at.clone(),
        time_zone: context.time_zone.clone(),
        origin: WriterOrigin::Device,
        actor_id: context.actor_id.clone(),
        authoritative: false,
        allocated_ids: rule_ids(
            &stable.command_id,
            envelope.command_type,
            &stable.payload,
            &base.read_set,
        )
        .map_err(|_| {
            ReplayDecisionError::Refused(IssueReason::Validation("invalid_payload".to_owned()))
        })?,
        policy: context.policy.clone(),
    };
    dispatch::decide_envelope(&base.read_set, envelope, results, &inputs).map_err(|error| {
        if private_undo_missing(envelope.command_type, &stable.entity_id, &error) {
            ReplayDecisionError::PrivateMissing(classify(&error, base))
        } else {
            ReplayDecisionError::Refused(classify(&error, base))
        }
    })
}

/// The issue reason of a refusal. A refusal about a record the base holds a
/// tombstone for is a deletion conflict, whichever way the rule phrased it.
fn classify(error: &DomainError, base: &Projection) -> IssueReason {
    if error
        .entity
        .as_ref()
        .is_some_and(|(_, key)| base.deleted(key))
    {
        return IssueReason::EntityDeleted;
    }
    match error.reason {
        Reason::EntityDeleted => IssueReason::EntityDeleted,
        Reason::RevisionConflict => IssueReason::RevisionConflict,
        Reason::DependencyRejected => IssueReason::DependencyRejected,
        other => IssueReason::Validation(other.as_str().to_owned()),
    }
}

/// A stored envelope, typed. An account-less intent has no scope or device, so
/// the placeholders [`crate::execute`] typed it with are put back. `None` is a
/// command or version this build cannot run.
fn decode(bytes: &[u8], workspace_id: &str) -> Result<Option<CommandEnvelope>, ReplayError> {
    let mut value: Value = serde_json::from_slice(bytes).map_err(corrupt)?;
    if let Some(fields) = value.as_object_mut() {
        fields
            .entry("scope_id")
            .or_insert_with(|| json!(workspace_id));
        fields.entry("device_id").or_insert_with(|| json!("local"));
    }
    match decode_command(&value.to_string()).map_err(corrupt)? {
        Decoded::Executable(envelope) => Ok(Some(envelope)),
        Decoded::Unsupported { .. } => Ok(None),
    }
}

// ----------------------------------------------------------------------- the queue

struct Queued {
    id: CommandId,
    state: String,
    ever_sent: bool,
    envelope: Vec<u8>,
    local_result: Option<Vec<u8>>,
}

fn load_queue(tx: &Transaction<'_>, workspace_id: &str) -> Result<Vec<Queued>, ReplayError> {
    let mut statement = tx.prepare(
        "SELECT command_id, state, ever_sent, envelope, local_result FROM outbox
         WHERE workspace_id = ?1 ORDER BY local_seq",
    )?;
    let rows = statement.query_map([workspace_id], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get(1)?,
            row.get::<_, i64>(2)?,
            row.get(3)?,
            row.get(4)?,
        ))
    })?;
    let mut queue = Vec::new();
    for row in rows {
        let (id, state, ever_sent, envelope, local_result) = row?;
        queue.push(Queued {
            id: CommandId::parse(id).map_err(corrupt)?,
            state,
            ever_sent: ever_sent != 0,
            envelope,
            local_result,
        });
    }
    Ok(queue)
}

/// `command -> the commands it depends on`.
fn load_edges(
    tx: &Transaction<'_>,
    workspace_id: &str,
) -> Result<HashMap<String, Vec<String>>, ReplayError> {
    let mut statement = tx.prepare(
        "SELECT command_id, depends_on FROM outbox_dependencies WHERE workspace_id = ?1",
    )?;
    let mut edges: HashMap<String, Vec<String>> = HashMap::new();
    for row in statement.query_map([workspace_id], |row| Ok((row.get(0)?, row.get(1)?)))? {
        let (command, dependency) = row?;
        edges.entry(command).or_default().push(dependency);
    }
    Ok(edges)
}

// ------------------------------------------------------------------- the projection

/// One visible row: what `visible_records` stores.
#[derive(Clone, Debug, PartialEq, Eq)]
struct Row {
    revision: Option<String>,
    source: Option<String>,
    body: Vec<u8>,
}

/// The base being replayed over: the records as the rules read them, the rows
/// to store, and the keys the confirmed base holds a tombstone for.
struct Projection {
    read_set: ReadSet,
    /// By `(record_type, record_key)`.
    rows: BTreeMap<(String, String), Row>,
    tombstones: HashSet<String>,
}

impl Projection {
    fn confirmed(tx: &Transaction<'_>, workspace_id: &str) -> Result<Self, ReplayError> {
        let mut projection = Self {
            read_set: ReadSet::default(),
            rows: BTreeMap::new(),
            tombstones: HashSet::new(),
        };
        let mut statement = tx.prepare(
            "SELECT record_type, record_key, edit_revision, tombstone, body
             FROM confirmed_records WHERE workspace_id = ?1",
        )?;
        let mut rows = statement.query([workspace_id])?;
        while let Some(row) = rows.next()? {
            let (kind, key): (String, String) = (row.get(0)?, row.get(1)?);
            let tombstone: i64 = row.get(3)?;
            let body: Option<Vec<u8>> = row.get(4)?;
            match (tombstone, body) {
                (0, Some(body)) => {
                    file(&mut projection.read_set, record_from(&kind, &body)?);
                    projection.rows.insert(
                        (kind, key),
                        Row {
                            revision: row.get(2)?,
                            source: None,
                            body,
                        },
                    );
                }
                (1, None) => {
                    projection.tombstones.insert(key);
                }
                _ => return Err(corrupt(())),
            }
        }
        Ok(projection)
    }

    fn deleted(&self, key: &[String]) -> bool {
        self.tombstones.contains(&json!(key).to_string())
    }

    /// Makes `change`, written by a pending command, part of what later
    /// commands read and of what is stored.
    fn install(&mut self, change: &DomainChange, command: &CommandId) {
        let kind = change.entity_type().as_str().to_owned();
        let key = json!(change.record_key()).to_string();
        match change {
            DomainChange::Upsert(record) => {
                self.rows.insert(
                    (kind, key),
                    Row {
                        revision: edit_revision(record).map(|c| c.as_str().to_owned()),
                        source: Some(command.as_str().to_owned()),
                        body: json!(record)["value"].take().to_string().into_bytes(),
                    },
                );
                file(&mut self.read_set, record.clone());
            }
            DomainChange::Tombstone {
                entity_type,
                record_key,
            } => {
                self.rows.remove(&(kind, key));
                remove(&mut self.read_set, *entity_type, record_key);
            }
        }
    }

    /// Stores the rows that differ from `visible_records`; returns how many.
    fn save(&self, tx: &Transaction<'_>, workspace_id: &str) -> rusqlite::Result<usize> {
        let mut stored: HashMap<(String, String), Row> = HashMap::new();
        {
            let mut statement = tx.prepare(
                "SELECT record_type, record_key, edit_revision, source_command_id, body
                 FROM visible_records WHERE workspace_id = ?1",
            )?;
            let mut rows = statement.query([workspace_id])?;
            while let Some(row) = rows.next()? {
                stored.insert(
                    (row.get(0)?, row.get(1)?),
                    Row {
                        revision: row.get(2)?,
                        source: row.get(3)?,
                        body: row.get(4)?,
                    },
                );
            }
        }
        let mut writes = 0;
        for (kind, key) in stored.keys().filter(|key| !self.rows.contains_key(*key)) {
            tx.execute(
                "DELETE FROM visible_records
                 WHERE workspace_id = ?1 AND record_type = ?2 AND record_key = ?3",
                params![workspace_id, kind, key],
            )?;
            writes += 1;
        }
        for ((kind, key), row) in &self.rows {
            if stored.get(&(kind.clone(), key.clone())) != Some(row) {
                tx.execute(
                    "INSERT OR REPLACE INTO visible_records (workspace_id, record_type,
                        record_key, edit_revision, source_command_id, body)
                     VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                    params![workspace_id, kind, key, row.revision, row.source, row.body],
                )?;
                writes += 1;
            }
        }
        Ok(writes)
    }
}

/// Removes the record a tombstone names from what the rules read.
pub(crate) fn remove(read_set: &mut ReadSet, entity_type: EntityType, key: &RecordKey) {
    let id = key.first().map_or("", String::as_str);
    let keyed = |record: Record| record.record_key() == *key;
    match entity_type {
        EntityType::Task => read_set.tasks.retain(|k, _| k.as_str() != id),
        EntityType::Project => read_set.projects.retain(|k, _| k.as_str() != id),
        EntityType::Tag => read_set.tags.retain(|k, _| k.as_str() != id),
        EntityType::Subtask => read_set.subtasks.retain(|k, _| k.as_str() != id),
        EntityType::Comment => read_set.comments.retain(|k, _| k.as_str() != id),
        EntityType::ReviewSettings => read_set.settings = None,
        EntityType::ReviewSession => read_set.sessions.retain(|k, _| k.as_str() != id),
        EntityType::ReviewDecisionQueue => {
            read_set.decision_queues.retain(|k, _| k.as_str() != id);
        }
        EntityType::ReviewDecision => read_set.decisions.retain(|k, _| k.as_str() != id),
        EntityType::ReviewReceipt => read_set
            .receipts
            .retain(|r| !keyed(Record::ReviewReceipt(r.clone()))),
        EntityType::ReviewParkAck => read_set
            .park_acks
            .retain(|r| !keyed(Record::ReviewParkAck(r.clone()))),
        EntityType::ReviewBulkRelease => read_set.bulk_releases.retain(|k, _| k.as_str() != id),
        EntityType::ReviewNavigatorConsent => read_set
            .consents
            .retain(|r| !keyed(Record::ReviewNavigatorConsent(r.clone()))),
    }
}
