//! Local execute: one gesture becomes an immutable queued intent and the
//! visible projection it changes, in one write transaction.
//!
//! [`execute`] runs under the store's cross-process write lock, so every read
//! below is a reread of what other processes may have written since this
//! handle last looked. In that one transaction it
//!
//! 1. answers a retry of a known command ID from the stored result, or refuses
//!    the ID when the content changed (026-FR-005);
//! 2. reads the visible projection into a [`bb_domain`] read set and wires
//!    the command to the immutable identities it builds on: a shown revision
//!    that a queued command produced becomes `after_command`, and every
//!    entity a queued command created or last wrote that this one touches
//!    becomes a `depends_on` entry (never a title or time guess);
//! 3. allocates the entity and rule IDs the request did not bring, allocates
//!    the intake epoch with the first command, and decides through
//!    [`bb_domain::dispatch::decide_envelope`];
//! 4. stores the envelope in the outbox, the dependency edges, the changed
//!    visible records and the new sequence and projection generation.
//!
//! Any refusal or storage error rolls the whole transaction back, so a gesture
//! is never half saved, and `Ok` is returned only after the commit is durable
//! (026-FR-001). Nothing here needs a registered account: an account-less
//! workspace queues its intents without a scope or device, and an epoch that
//! is still `pending_registration` is reused by the app, the widget and App
//! Intents until registration (sync-v1 section 5).

use crate::replay::{ReplayError, replay_in};
use crate::storage::{Store, StoreError};
use bb_domain::dispatch;
use bb_domain::types::{
    ActorId, AliasRef, Binding, ChangeOutcome, ChangeSet, Dependencies, DomainChange, DomainError,
    ExecutionInputs, Policy, ReadSet, Reason, Record, WriterOrigin, ZoneName,
};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{
    AfterCommandPrecondition, CommandRef, Decoded, Precondition, StableEnvelope, decode_command,
};
use bb_protocol::wire::{CommandId, Counter, Id, Instant, OpenObject, PROTOCOL_VERSION, RecordKey};
use rusqlite::{OptionalExtension, Transaction, params};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::io::{self, Read};

/// The rule version the local projection is decided with.
pub(crate) const RULE_VERSION: u32 = 1;

// ---------------------------------------------------------------------- the request

/// The trusted facts a gesture is decided with; the platform supplies them.
#[derive(Clone, Debug)]
pub struct ExecuteContext {
    /// The device instant: the intent's `issued_at` and the rules' `now`.
    pub now: Instant,
    pub time_zone: ZoneName,
    pub actor_id: ActorId,
    /// OS capability facts; never read from a payload.
    pub policy: Policy,
}

/// One gesture. `command_id` is chosen by the caller and kept across retries.
#[derive(Clone, Debug)]
pub struct ExecuteRequest {
    pub command_id: CommandId,
    pub command_type: CommandType,
    /// The target. A creation may omit it: the runtime allocates the ID.
    pub entity_id: Option<Id>,
    pub payload: OpenObject,
    /// The revisions the user was shown.
    pub preconditions: Vec<Precondition>,
    pub depends_on: Vec<CommandId>,
    pub context: ExecuteContext,
}

/// `status` of the success answer: durable on this device, not yet confirmed.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LocalStatus {
    LocallySaved,
}

/// The success answer of `execute` (runtime-ffi.md).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Executed {
    pub command_id: CommandId,
    /// The target, including an ID the runtime allocated.
    pub entity_id: Id,
    pub local_sequence: u64,
    pub projection_generation: u64,
    pub status: LocalStatus,
    /// True when this answers a retry from the stored result.
    pub replayed: bool,
}

/// Why nothing was saved.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ExecuteError {
    /// The store could not do it; only `STORE_BUSY` is worth retrying as is.
    Store(StoreError),
    /// The rules (or the request's shape) refused the command.
    Refused(DomainError),
    /// `IDEMPOTENCY_KEY_REUSED`: the ID is known with different content.
    CommandIdReused,
}

impl ExecuteError {
    /// The stable code the bindings carry across FFI.
    pub fn code(&self) -> &'static str {
        match self {
            Self::Store(error) => error.code(),
            Self::Refused(_) => "VALIDATION_FAILED",
            Self::CommandIdReused => "IDEMPOTENCY_KEY_REUSED",
        }
    }

    pub fn is_retryable(&self) -> bool {
        matches!(self, Self::Store(error) if error.is_retryable())
    }
}

impl std::fmt::Display for ExecuteError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Store(error) => error.fmt(f),
            // The reason and field names carry no user text.
            Self::Refused(error) => write!(f, "{}: {}", self.code(), error.reason.as_str()),
            Self::CommandIdReused => f.write_str(self.code()),
        }
    }
}

impl std::error::Error for ExecuteError {}

impl From<StoreError> for ExecuteError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}

impl From<rusqlite::Error> for ExecuteError {
    fn from(error: rusqlite::Error) -> Self {
        Self::Store(error.into())
    }
}

impl From<io::Error> for ExecuteError {
    fn from(error: io::Error) -> Self {
        Self::Store(error.into())
    }
}

impl From<DomainError> for ExecuteError {
    fn from(error: DomainError) -> Self {
        Self::Refused(error)
    }
}

fn refuse(reason: Reason, field: &str) -> ExecuteError {
    DomainError::field(reason, field).into()
}

pub(crate) fn corrupt<E>(_: E) -> ExecuteError {
    StoreError::Corrupt.into()
}

// ------------------------------------------------------------------ id allocation

/// Where new UUIDs come from. The runtime asks for them only inside the write
/// transaction; tests substitute a counter.
pub trait IdSource {
    fn uuid(&mut self) -> io::Result<String>;
}

/// Version 4 UUIDs from the operating system's random source.
#[derive(Clone, Copy, Debug, Default)]
pub struct RandomIds;

impl IdSource for RandomIds {
    fn uuid(&mut self) -> io::Result<String> {
        let mut bytes = [0u8; 16];
        std::fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
        Ok(uuid_from(bytes))
    }
}

/// Formats 16 bytes as a version 4 UUID.
fn uuid_from(mut bytes: [u8; 16]) -> String {
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    let hex: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        &hex[..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..]
    )
}

fn prefixed(ids: &mut impl IdSource, prefix: &str) -> Result<Id, ExecuteError> {
    Id::parse(format!("{prefix}_{}", ids.uuid()?)).map_err(corrupt)
}

/// The prefix of the ID a creation allocates for its target.
fn new_entity_prefix(command_type: CommandType) -> Option<&'static str> {
    Some(match command_type {
        CommandType::ProjectCreate => "project",
        CommandType::TagCreate => "tag",
        CommandType::TaskCreate | CommandType::TaskSmartAdd => "task",
        CommandType::SubtaskCreate => "subtask",
        CommandType::CommentCreate => "comment",
        CommandType::ReviewSessionStart => "review",
        CommandType::ReviewBulkRelease => "bulk",
        _ => return None,
    })
}

/// The IDs a rule mints beyond the request's own, in the order it consumes
/// them (`ExecutionInputs::allocated_ids`). They derive from the command ID, so
/// replaying a queued command over a changed base mints the same IDs again and
/// the projection does not churn.
pub(crate) fn rule_ids(
    command_id: &CommandId,
    command_type: CommandType,
    payload: &OpenObject,
    read_set: &ReadSet,
) -> Result<Vec<Id>, ExecuteError> {
    let mut kinds = vec!["form"];
    match command_type {
        CommandType::ReviewDecide
            if payload.get("type").and_then(Value::as_str) == Some("follow_up")
                && !payload.contains_key("follow_up_task_id") =>
        {
            kinds.insert(0, "task");
        }
        // Activation starts a clock, with its own formulation, on every Next
        // task that has none.
        CommandType::ReviewExplainerAck => {
            let clockless = read_set
                .tasks
                .values()
                .filter(|task| task.state == bb_domain::types::TaskState::Next)
                .filter(|task| task.formulation.is_none())
                .count();
            kinds = vec!["form"; clockless];
        }
        _ => {}
    }
    kinds
        .into_iter()
        .enumerate()
        .map(|(index, kind)| {
            let digest = sha256(format!("{}:{index}", command_id.as_str()).as_bytes());
            let (seed, _) = digest.as_chunks::<16>();
            let uuid = uuid_from(seed.first().copied().unwrap_or_default());
            Id::parse(format!("{kind}_{uuid}")).map_err(corrupt)
        })
        .collect()
}

// ------------------------------------------------------------------ test seam

/// The points inside the write transaction where a test can fail or kill the
/// process to prove nothing partial survives.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Stage {
    /// The outbox row and its dependency edges are written.
    IntentStored,
    /// The visible projection and the counters are written; only the commit is left.
    ProjectionStored,
}

// ------------------------------------------------------------------------ execute

/// Saves one gesture. See the module documentation.
///
/// # Errors
///
/// [`ExecuteError`]; whatever it is, nothing of the gesture was saved.
pub fn execute(
    store: &mut Store,
    ids: &mut impl IdSource,
    request: &ExecuteRequest,
) -> Result<Executed, ExecuteError> {
    execute_with(store, ids, request, |_, _| Ok(()))
}

/// [`execute`] with a hook that runs inside the transaction at each [`Stage`].
/// An `Err` from the hook rolls the gesture back; a hook that kills the process
/// leaves an uncommitted transaction for SQLite's recovery to discard.
///
/// # Errors
///
/// As [`execute`].
pub fn execute_with(
    store: &mut Store,
    ids: &mut impl IdSource,
    request: &ExecuteRequest,
    mut hook: impl FnMut(Stage, &Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<Executed, ExecuteError> {
    store.try_write(|tx| run(tx, ids, request, None, &mut hook))
}

/// [`execute`] inside a transaction the caller already holds, for a command
/// that replaces `supersedes` (an explicit resolution of a sync issue).
pub(crate) fn execute_in(
    tx: &Transaction<'_>,
    ids: &mut impl IdSource,
    request: &ExecuteRequest,
    supersedes: &CommandId,
) -> Result<Executed, ExecuteError> {
    run(tx, ids, request, Some(supersedes), &mut |_, _| Ok(()))
}

struct Meta {
    workspace_id: String,
    scope_id: Option<String>,
    device_id: Option<String>,
    device_epoch: Option<String>,
    epoch_state: String,
    next_local_seq: i64,
    projection_generation: i64,
    /// The store was upgraded from a schema without the visible projection and
    /// nothing has rebuilt it yet.
    projection_stale: bool,
}

/// SQLite integers are signed; the counters stored in them never are.
pub(crate) fn unsigned(value: i64) -> Result<u64, ExecuteError> {
    u64::try_from(value).map_err(corrupt)
}

fn read_meta(tx: &Transaction<'_>) -> Result<Meta, ExecuteError> {
    Ok(tx.query_row(
        "SELECT workspace_id, scope_id, device_id, device_epoch, device_epoch_state,
                next_local_seq, projection_generation, projection_stale FROM sync_meta",
        [],
        |row| {
            Ok(Meta {
                workspace_id: row.get(0)?,
                scope_id: row.get(1)?,
                device_id: row.get(2)?,
                device_epoch: row.get(3)?,
                epoch_state: row.get(4)?,
                next_local_seq: row.get(5)?,
                projection_generation: row.get(6)?,
                projection_stale: row.get::<_, i64>(7)? != 0,
            })
        },
    )?)
}

fn run(
    tx: &Transaction<'_>,
    ids: &mut impl IdSource,
    request: &ExecuteRequest,
    supersedes: Option<&CommandId>,
    hook: &mut impl FnMut(Stage, &Transaction<'_>) -> rusqlite::Result<()>,
) -> Result<Executed, ExecuteError> {
    let mut meta = read_meta(tx)?;
    if meta.projection_stale {
        // An upgraded store holds confirmed rows and queued work but no visible
        // projection yet: build it before deciding anything against it.
        replay_in(tx, &request.context).map_err(|error| match error {
            ReplayError::Store(error) => ExecuteError::Store(error),
            _ => ExecuteError::Store(StoreError::Corrupt),
        })?;
        meta = read_meta(tx)?;
    }
    let digest = sha256(request_canonical(request).as_bytes());
    if let Some(known) = known_command(tx, &meta.workspace_id, &request.command_id)? {
        return if known.digest == digest {
            known.answer(&request.command_id, meta.projection_generation)
        } else {
            Err(ExecuteError::CommandIdReused)
        };
    }

    let visible = load_visible(tx, &meta.workspace_id)?;
    let entity_id = match (&request.entity_id, new_entity_prefix(request.command_type)) {
        (Some(id), _) => id.clone(),
        (None, Some(prefix)) => prefixed(ids, prefix)?,
        (None, None) => return Err(refuse(Reason::InvalidPayload, "entity_id")),
    };
    let (preconditions, depends_on) = wire(request, &entity_id, &visible.pending);
    let results = load_dependencies(tx, &meta.workspace_id, &depends_on)?;

    let (epoch, new_epoch) = match &meta.device_epoch {
        Some(epoch) if matches!(meta.epoch_state.as_str(), "pending_registration" | "active") => {
            (epoch.clone(), false)
        }
        _ => (ids.uuid()?, true),
    };
    let mut stable = StableEnvelope {
        protocol_version: PROTOCOL_VERSION,
        command_id: request.command_id.clone(),
        scope_id: placeholder(meta.scope_id.as_deref(), &meta.workspace_id)?,
        device_id: placeholder(meta.device_id.as_deref(), "local")?,
        device_epoch: Id::parse(epoch.clone()).map_err(corrupt)?,
        local_sequence: Counter::from(unsigned(meta.next_local_seq)?),
        command_type: request.command_type.as_str().to_owned(),
        command_version: 1,
        entity_id: entity_id.clone(),
        preconditions: preconditions
            .iter()
            .map(|precondition| json!(precondition))
            .collect(),
        depends_on: depends_on.clone(),
        issued_at: request.context.now.clone(),
        supersedes_command_id: supersedes.cloned(),
        payload: request.payload.clone(),
    };
    let envelope = match decode_command(&json!(stable).to_string()) {
        Ok(Decoded::Executable(envelope)) => envelope,
        Ok(Decoded::Unsupported { .. }) => {
            return Err(refuse(Reason::UnsupportedCommandVersion, "command_version"));
        }
        Err(error) => {
            return Err(match error {
                bb_protocol::wire::CodecError::Invalid(rule) => {
                    refuse(Reason::InvalidPayload, rule)
                }
                _ => DomainError::new(Reason::InvalidPayload).into(),
            });
        }
    };

    let inputs = ExecutionInputs {
        rule_version: RULE_VERSION,
        now: request.context.now.clone(),
        time_zone: request.context.time_zone.clone(),
        origin: WriterOrigin::Device,
        actor_id: request.context.actor_id.clone(),
        authoritative: false,
        allocated_ids: rule_ids(
            &request.command_id,
            request.command_type,
            &request.payload,
            &visible.read_set,
        )?,
        policy: request.context.policy.clone(),
    };
    let changes = dispatch::decide_envelope(&visible.read_set, &envelope, &results, &inputs)?;

    // What the rules resolved (a Smart Add name matched onto a queued project,
    // the tasks an archive touched) is a dependency on the command that wrote
    // it, found by identity: the exact key of each record the command changes
    // and the typed references those records hold.
    for change in &changes.changes {
        let key = json!(change.record_key()).to_string();
        depend_on_key(
            &mut stable.depends_on,
            &visible.pending,
            Some(change.entity_type()),
            &key,
        );
        if let DomainChange::Upsert(record) = change {
            for reference in record_references(record) {
                depend_on_key(
                    &mut stable.depends_on,
                    &visible.pending,
                    None,
                    &key_json(reference),
                );
            }
        }
    }
    let depends_on = stable.depends_on.clone();

    // Decided: from here on only writes, all inside this transaction.
    let projection_generation =
        meta.projection_generation + i64::from(changes.outcome == ChangeOutcome::Applied);
    let local_result = local_result(&changes);
    if new_epoch {
        tx.execute(
            "UPDATE sync_meta SET device_epoch = ?1, device_epoch_state = 'pending_registration'",
            [&epoch],
        )?;
    }
    tx.execute(
        "INSERT INTO outbox (workspace_id, command_id, device_epoch, local_seq, envelope,
            envelope_digest, created_at, projection_generation, local_result)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
        params![
            meta.workspace_id,
            request.command_id.as_str(),
            epoch,
            meta.next_local_seq,
            stored_envelope(&stable, &meta),
            digest.as_slice(),
            request.context.now.as_str(),
            projection_generation,
            local_result,
        ],
    )?;
    for dependency in &depends_on {
        tx.execute(
            "INSERT INTO outbox_dependencies (workspace_id, command_id, depends_on)
             VALUES (?1, ?2, ?3)",
            params![
                meta.workspace_id,
                request.command_id.as_str(),
                dependency.as_str()
            ],
        )?;
    }
    hook(Stage::IntentStored, tx)?;
    for change in &changes.changes {
        apply(tx, &meta.workspace_id, &request.command_id, change)?;
    }
    tx.execute(
        "UPDATE sync_meta SET next_local_seq = ?1, projection_generation = ?2",
        params![meta.next_local_seq + 1, projection_generation],
    )?;
    hook(Stage::ProjectionStored, tx)?;
    Ok(Executed {
        command_id: request.command_id.clone(),
        entity_id,
        local_sequence: unsigned(meta.next_local_seq)?,
        projection_generation: unsigned(projection_generation)?,
        status: LocalStatus::LocallySaved,
        replayed: false,
    })
}

/// A scope or device the workspace does not have yet only types the command
/// for the rules; [`stored_envelope`] drops it again.
fn placeholder(known: Option<&str>, fallback: &str) -> Result<Id, ExecuteError> {
    Id::parse(known.unwrap_or(fallback)).map_err(corrupt)
}

/// The immutable intent. An account-less workspace has no scope or device, and
/// its intents are never given a fictitious one: they are not server envelopes.
fn stored_envelope(stable: &StableEnvelope, meta: &Meta) -> Vec<u8> {
    let mut value = json!(stable);
    if let Some(fields) = value.as_object_mut() {
        if meta.scope_id.is_none() {
            fields.remove("scope_id");
        }
        if meta.device_id.is_none() {
            fields.remove("device_id");
        }
    }
    value.to_string().into_bytes()
}

// ------------------------------------------------------------------------- retries

/// The canonical form of the gesture a retry is compared with: everything the
/// caller decides, and nothing the runtime assigns (sequence, epoch, instants).
fn request_canonical(request: &ExecuteRequest) -> String {
    let mut depends_on: Vec<&str> = request.depends_on.iter().map(CommandId::as_str).collect();
    depends_on.sort_unstable();
    json!({
        "type": request.command_type.as_str(),
        "entity_id": request.entity_id.as_ref().map(Id::as_str),
        "preconditions": request.preconditions,
        "depends_on": depends_on,
        "payload": request.payload,
    })
    .to_string()
}

struct Known {
    digest: Vec<u8>,
    local_sequence: i64,
    projection_generation: Option<i64>,
    envelope: Vec<u8>,
}

impl Known {
    fn answer(
        &self,
        command_id: &CommandId,
        current_generation: i64,
    ) -> Result<Executed, ExecuteError> {
        // A stored envelope always names its target.
        let envelope: Value = serde_json::from_slice(&self.envelope).map_err(corrupt)?;
        let entity_id = envelope
            .get("entity_id")
            .and_then(Value::as_str)
            .ok_or_else(|| corrupt(()))?;
        Ok(Executed {
            command_id: command_id.clone(),
            entity_id: Id::parse(entity_id).map_err(corrupt)?,
            local_sequence: unsigned(self.local_sequence)?,
            projection_generation: unsigned(
                self.projection_generation.unwrap_or(current_generation),
            )?,
            status: LocalStatus::LocallySaved,
            replayed: true,
        })
    }
}

fn known_command(
    tx: &Transaction<'_>,
    workspace_id: &str,
    command_id: &CommandId,
) -> Result<Option<Known>, ExecuteError> {
    Ok(tx
        .query_row(
            "SELECT envelope_digest, local_seq, projection_generation, envelope
             FROM outbox WHERE workspace_id = ?1 AND command_id = ?2",
            params![workspace_id, command_id.as_str()],
            |row| {
                Ok(Known {
                    digest: row.get(0)?,
                    local_sequence: row.get(1)?,
                    projection_generation: row.get(2)?,
                    envelope: row.get(3)?,
                })
            },
        )
        .optional()?)
}

// ---------------------------------------------------------------- the visible state

/// A queued command's claim on a visible record: it last wrote it.
struct Pending {
    entity_type: EntityType,
    edit_revision: Option<Counter>,
    command: CommandId,
}

struct Visible {
    read_set: ReadSet,
    /// By record key (a JSON array of components), for the records a queued
    /// command last wrote.
    pending: HashMap<String, Vec<Pending>>,
}

fn key_json(id: &str) -> String {
    json!([id]).to_string()
}

/// Rereads the whole visible projection under the write lock. A command that
/// has finished (`completed`) no longer owns a record.
fn load_visible(tx: &Transaction<'_>, workspace_id: &str) -> Result<Visible, ExecuteError> {
    let mut statement = tx.prepare(
        "SELECT v.record_type, v.record_key, v.edit_revision, v.body,
                CASE WHEN o.state IS NOT NULL AND o.state <> 'completed'
                     THEN v.source_command_id END
         FROM visible_records v
         LEFT JOIN outbox o ON o.workspace_id = v.workspace_id
                           AND o.command_id = v.source_command_id
         WHERE v.workspace_id = ?1",
    )?;
    let mut rows = statement.query([workspace_id])?;
    let mut visible = Visible {
        read_set: ReadSet::default(),
        pending: HashMap::new(),
    };
    while let Some(row) = rows.next()? {
        let kind: String = row.get(0)?;
        let key: String = row.get(1)?;
        let revision: Option<String> = row.get(2)?;
        let body: Vec<u8> = row.get(3)?;
        let source: Option<String> = row.get(4)?;
        let entity_type = EntityType::from_wire(&kind).ok_or_else(|| corrupt(()))?;
        file(&mut visible.read_set, record_from(&kind, &body)?);
        if let Some(command) = source {
            visible.pending.entry(key).or_default().push(Pending {
                entity_type,
                edit_revision: revision.and_then(|text| Counter::parse(text).ok()),
                command: CommandId::parse(command).map_err(corrupt)?,
            });
        }
    }
    Ok(visible)
}

/// A stored record: `kind` is its wire entity type and `body` its `value`.
pub(crate) fn record_from(kind: &str, body: &[u8]) -> Result<Record, ExecuteError> {
    // `Record` is adjacently tagged; the stored body is its `value`.
    let mut tagged = format!(r#"{{"entity_type":"{kind}","value":"#).into_bytes();
    tagged.extend_from_slice(body);
    tagged.push(b'}');
    serde_json::from_slice(&tagged).map_err(corrupt)
}

pub(crate) fn file(read_set: &mut ReadSet, record: Record) {
    match record {
        Record::Task(r) => drop(read_set.tasks.insert(r.id.clone(), r)),
        Record::Project(r) => drop(read_set.projects.insert(r.id.clone(), r)),
        Record::Tag(r) => drop(read_set.tags.insert(r.id.clone(), r)),
        Record::Subtask(r) => drop(read_set.subtasks.insert(r.id.clone(), r)),
        Record::Comment(r) => drop(read_set.comments.insert(r.id.clone(), r)),
        Record::ReviewSettings(r) => read_set.settings = Some(r),
        Record::ReviewSession(r) => drop(read_set.sessions.insert(r.id.clone(), r)),
        Record::ReviewDecisionQueue(r) => {
            drop(read_set.decision_queues.insert(r.session_id.clone(), r));
        }
        Record::ReviewDecision(r) => drop(read_set.decisions.insert(r.id.clone(), r)),
        // The list collections hold one entry per record key, so filing a
        // record replaces the entry it supersedes instead of sitting beside it.
        Record::ReviewReceipt(r) => {
            read_set.receipts.retain(|held| {
                (&held.task_id, held.kind.as_str()) != (&r.task_id, r.kind.as_str())
            });
            read_set.receipts.push(r);
        }
        Record::ReviewParkAck(r) => {
            read_set.park_acks.retain(|held| {
                (&held.task_id, &held.formulation_id) != (&r.task_id, &r.formulation_id)
            });
            read_set.park_acks.push(r);
        }
        Record::ReviewBulkRelease(r) => drop(read_set.bulk_releases.insert(r.id.clone(), r)),
        Record::ReviewNavigatorConsent(r) => {
            read_set.consents.retain(|held| held.provider != r.provider);
            read_set.consents.push(r);
        }
    }
}

/// The revision a record's own edit concurrency is checked against; the
/// Review projections without one have none.
pub(crate) fn edit_revision(record: &Record) -> Option<Counter> {
    match record {
        Record::Task(r) => Some(r.revision.clone()),
        Record::Project(r) => Some(r.revision.clone()),
        Record::Tag(r) => Some(r.revision.clone()),
        Record::Subtask(r) => Some(r.revision.clone()),
        Record::Comment(r) => Some(r.revision.clone()),
        Record::ReviewSettings(r) => Some(r.revision.clone()),
        Record::ReviewSession(r) => Some(r.revision.clone()),
        _ => None,
    }
}

fn apply(
    tx: &Transaction<'_>,
    workspace_id: &str,
    command_id: &CommandId,
    change: &DomainChange,
) -> Result<(), ExecuteError> {
    match change {
        DomainChange::Upsert(record) => {
            let body = json!(record)["value"].take().to_string().into_bytes();
            tx.execute(
                "INSERT OR REPLACE INTO visible_records (workspace_id, record_type, record_key,
                    edit_revision, source_command_id, body)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
                params![
                    workspace_id,
                    record.entity_type().as_str(),
                    json!(record.record_key()).to_string(),
                    edit_revision(record).as_ref().map(Counter::as_str),
                    command_id.as_str(),
                    body,
                ],
            )?;
        }
        DomainChange::Tombstone {
            entity_type,
            record_key,
        } => {
            tx.execute(
                "DELETE FROM visible_records
                 WHERE workspace_id = ?1 AND record_type = ?2 AND record_key = ?3",
                params![
                    workspace_id,
                    entity_type.as_str(),
                    json!(record_key).to_string()
                ],
            )?;
        }
    }
    Ok(())
}

// ------------------------------------------------------------------- dependencies

fn push_unique(list: &mut Vec<CommandId>, id: &CommandId) {
    if !list.contains(id) {
        list.push(id.clone());
    }
}

/// Adds the queued command that last wrote the record at `key` (of
/// `entity_type`, when known).
fn depend_on_key(
    depends_on: &mut Vec<CommandId>,
    pending: &HashMap<String, Vec<Pending>>,
    entity_type: Option<EntityType>,
    key: &str,
) {
    for queued in pending.get(key).into_iter().flatten() {
        if entity_type.is_none_or(|kind| queued.entity_type == kind) {
            push_unique(depends_on, &queued.command);
        }
    }
}

/// The record key a shown revision of `entity_type` is stored under: the
/// Review settings are a singleton with the empty key, every other record with
/// an edit revision is keyed by its ID.
pub(crate) fn shown_key(entity_type: EntityType, id: &str) -> String {
    if entity_type == EntityType::ReviewSettings {
        json!(RecordKey::new()).to_string()
    } else {
        key_json(id)
    }
}

/// The payload members that name another entity. Only these are references:
/// every other string is user text or a new value, and may equal any ID
/// without depending on it.
const REFERENCE_FIELDS: [&str; 7] = [
    "project_id",
    "tag_ids",
    "add_tag_ids",
    "remove_tag_ids",
    "task_id",
    "session_id",
    "id",
];

/// The IDs a payload references and the commands its alias objects name.
fn references<'a>(
    value: &'a Value,
    field: Option<&str>,
    ids: &mut Vec<&'a str>,
    after: &mut Vec<&'a str>,
) {
    match value {
        Value::String(text) if field.is_some_and(|name| REFERENCE_FIELDS.contains(&name)) => {
            ids.push(text);
        }
        Value::Array(items) => items
            .iter()
            .for_each(|item| references(item, field, ids, after)),
        Value::Object(map) => {
            for (key, member) in map {
                match member {
                    Value::String(command) if key == "after_command" => after.push(command),
                    _ => references(member, Some(key), ids, after),
                }
            }
        }
        _ => {}
    }
}

/// The IDs a changed record points at.
fn record_references(record: &Record) -> Vec<&str> {
    match record {
        Record::Task(task) => task
            .project_id
            .iter()
            .map(|id| id.as_str())
            .chain(task.tag_ids.iter().map(|id| id.as_str()))
            .collect(),
        Record::Subtask(child) => vec![child.task_id.as_str()],
        Record::Comment(child) => vec![child.task_id.as_str()],
        Record::ReviewDecision(decision) => vec![decision.task_id.as_str()],
        _ => Vec::new(),
    }
}

/// Ties the command to the immutable identities it builds on, never to a
/// guessed match: a shown revision that a queued command produced becomes an
/// `after_command` check, and every record this command names that a queued
/// command last wrote makes that command a dependency, so a rejection later
/// blocks this one.
fn wire(
    request: &ExecuteRequest,
    entity_id: &Id,
    pending: &HashMap<String, Vec<Pending>>,
) -> (Vec<Precondition>, Vec<CommandId>) {
    let mut depends_on = request.depends_on.clone();
    let mut preconditions = Vec::with_capacity(request.preconditions.len());
    for precondition in &request.preconditions {
        preconditions.push(match precondition {
            Precondition::Revision(shown) => {
                let queued = pending
                    .get(&shown_key(shown.entity_type, shown.entity_id.as_str()))
                    .into_iter()
                    .flatten()
                    .find(|p| {
                        p.entity_type == shown.entity_type
                            && p.edit_revision.as_ref() == Some(&shown.edit_revision)
                    });
                match queued {
                    Some(p) => {
                        push_unique(&mut depends_on, &p.command);
                        Precondition::AfterCommand(AfterCommandPrecondition {
                            after_command: CommandRef {
                                command_id: p.command.clone(),
                                entity_type: shown.entity_type,
                                entity_id: shown.entity_id.clone(),
                            },
                        })
                    }
                    None => precondition.clone(),
                }
            }
            Precondition::AfterCommand(after) => {
                push_unique(&mut depends_on, &after.after_command.command_id);
                precondition.clone()
            }
        });
    }
    let (mut ids, mut after) = (vec![entity_id.as_str()], Vec::new());
    for (field, member) in &request.payload {
        references(member, Some(field), &mut ids, &mut after);
    }
    for id in ids {
        depend_on_key(&mut depends_on, pending, None, &key_json(id));
    }
    // An alias reference names the earlier command it came from.
    for command in after {
        if let Ok(command) = CommandId::parse(command) {
            push_unique(&mut depends_on, &command);
        }
    }
    (preconditions, depends_on)
}

/// What a queued command did, kept so a later gesture can refer to it before
/// any receipt exists (the local counterpart of the retained receipt).
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct LocalResult {
    versions: Vec<LocalVersion>,
    id_bindings: Vec<Binding>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
struct LocalVersion {
    entity_type: EntityType,
    record_key: RecordKey,
    edit_revision: Option<Counter>,
}

/// What a decided command leaves for the commands that build on it, as stored.
pub(crate) fn local_result(changes: &ChangeSet) -> Vec<u8> {
    let result = LocalResult {
        versions: changes
            .changes
            .iter()
            .filter_map(|change| match change {
                DomainChange::Upsert(record) => Some(LocalVersion {
                    entity_type: record.entity_type(),
                    record_key: record.record_key(),
                    edit_revision: edit_revision(record),
                }),
                DomainChange::Tombstone { .. } => None,
            })
            .collect(),
        id_bindings: changes.result.id_bindings.clone(),
    };
    json!(result).to_string().into_bytes()
}

/// The stored local results of the commands a replay decides against.
pub(crate) struct LocalResults(HashMap<String, LocalResult>);

impl LocalResults {
    pub(crate) fn new() -> Self {
        Self(HashMap::new())
    }

    /// Records a command's stored result; none stored is an empty result.
    pub(crate) fn insert(
        &mut self,
        command_id: &CommandId,
        stored: Option<&[u8]>,
    ) -> Result<(), ExecuteError> {
        let result = match stored {
            None => LocalResult::default(),
            Some(bytes) => serde_json::from_slice(bytes).map_err(corrupt)?,
        };
        self.0.insert(command_id.as_str().to_owned(), result);
        Ok(())
    }
}

/// Every dependency must be a command this workspace queued.
fn load_dependencies(
    tx: &Transaction<'_>,
    workspace_id: &str,
    depends_on: &[CommandId],
) -> Result<LocalResults, ExecuteError> {
    let mut found = HashMap::new();
    for id in depends_on {
        let stored: Option<Option<Vec<u8>>> = tx
            .query_row(
                "SELECT local_result FROM outbox WHERE workspace_id = ?1 AND command_id = ?2",
                params![workspace_id, id.as_str()],
                |row| row.get(0),
            )
            .optional()?;
        let result = match stored {
            None => return Err(refuse(Reason::InvalidPayload, "depends_on")),
            Some(None) => LocalResult::default(),
            Some(Some(bytes)) => serde_json::from_slice(&bytes).map_err(corrupt)?,
        };
        found.insert(id.as_str().to_owned(), result);
    }
    Ok(LocalResults(found))
}

impl LocalResults {
    fn result(&self, command_id: &CommandId) -> Result<&LocalResult, DomainError> {
        self.0
            .get(command_id.as_str())
            .ok_or_else(|| DomainError::new(Reason::DependencyPending))
    }
}

impl Dependencies for LocalResults {
    fn edit_revision(&self, reference: &CommandRef) -> Result<Counter, DomainError> {
        let id = reference.entity_id.as_str();
        self.result(&reference.command_id)?
            .versions
            .iter()
            .find(|version| {
                version.entity_type == reference.entity_type
                    && (version.record_key.as_slice() == [id]
                        || (reference.entity_type == EntityType::ReviewSettings
                            && version.record_key.is_empty()))
            })
            .and_then(|version| version.edit_revision.clone())
            .ok_or_else(|| {
                DomainError::about(
                    Reason::DependencyRejected,
                    reference.entity_type,
                    vec![id.to_owned()],
                )
            })
    }

    fn binding(&self, alias: &AliasRef) -> Result<Id, DomainError> {
        self.result(&alias.after_command)?
            .id_bindings
            .iter()
            .find(|binding| {
                binding.entity_type == alias.entity_type && binding.alias_id == alias.alias_id
            })
            .map(|binding| binding.entity_id.clone())
            .ok_or_else(|| {
                DomainError::about(
                    Reason::DependencyRejected,
                    alias.entity_type,
                    vec![alias.alias_id.as_str().to_owned()],
                )
            })
    }
}

// ---------------------------------------------------------------------- SHA-256

const K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

/// FIPS 180-4 SHA-256. The store compares a retried request with the stored
/// one by this digest; it is an equality check on local data, not a secret.
pub(crate) fn sha256(data: &[u8]) -> [u8; 32] {
    let mut state: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let mut padded = data.to_vec();
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&(data.len() as u64 * 8).to_be_bytes());
    for block in padded.as_chunks::<64>().0 {
        let mut w = [0u32; 64];
        for (slot, word) in w.iter_mut().zip(block.as_chunks::<4>().0) {
            *slot = u32::from_be_bytes(*word);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = state;
        for (k, word) in K.iter().zip(w) {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let choose = (e & f) ^ (!e & g);
            let t1 = h
                .wrapping_add(s1)
                .wrapping_add(choose)
                .wrapping_add(*k)
                .wrapping_add(word);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let majority = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(majority);
            (h, g, f, e, d, c, b, a) = (g, f, e, d.wrapping_add(t1), c, b, a, t1.wrapping_add(t2));
        }
        for (slot, value) in state.iter_mut().zip([a, b, c, d, e, f, g, h]) {
            *slot = slot.wrapping_add(value);
        }
    }
    let mut digest = [0u8; 32];
    for (bytes, word) in digest.as_chunks_mut::<4>().0.iter_mut().zip(state) {
        *bytes = word.to_be_bytes();
    }
    digest
}

#[cfg(test)]
mod tests {
    use super::{file, record_from, sha256};
    use bb_domain::types::ReadSet;

    #[test]
    fn execute_026_fr_001_filing_a_list_record_replaces_the_entry_with_its_key() {
        let ack = |formulation: &str, seen: &str| {
            format!(
                r#"{{"task_id":"task_00000000-0000-4000-8000-000000000001","formulation_id":"form_{formulation}","parked_at":"2026-10-10T09:00:00Z","seen_at":{seen},"returned_at":null}}"#
            )
        };
        let mut read_set = ReadSet::default();
        for body in [
            ack("00000000-0000-4000-8000-00000000000a", "null"),
            ack(
                "00000000-0000-4000-8000-00000000000a",
                r#""2026-10-10T10:00:00Z""#,
            ),
            ack("00000000-0000-4000-8000-00000000000b", "null"),
        ] {
            file(
                &mut read_set,
                record_from("review_park_ack", body.as_bytes()).unwrap(),
            );
        }
        assert_eq!(read_set.park_acks.len(), 2);
        assert!(read_set.park_acks.iter().any(|ack| ack.seen_at.is_some()));
    }

    fn hex(digest: [u8; 32]) -> String {
        digest.iter().map(|byte| format!("{byte:02x}")).collect()
    }

    #[test]
    fn execute_026_fr_005_digest_is_sha256_per_fips_180_4() {
        assert_eq!(
            hex(sha256(b"abc")),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(
            hex(sha256(b"")),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        // Two blocks: the padding spills into a second one.
        assert_eq!(
            hex(sha256(
                b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
            )),
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
        );
    }
}
