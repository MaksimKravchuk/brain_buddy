//! The frozen catalog unions: [`Command`] and [`DomainCommand::from_envelope`],
//! the protected [`ReadSet`], replicated [`Record`]s, the [`ChangeSet`] a
//! command produces and the execution and query inputs.
//!
//! `decide(read_set, command, inputs) -> ChangeSet | DomainError` and
//! `query(read_set, query, inputs) -> QueryResult` are deterministic: every
//! fact a rule needs (time, zone, IDs, policy, origin) arrives in the inputs.

use super::errors::{DomainError, Reason};
use super::primitives::{
    ActorId, BulkId, CommentId, DecisionId, ProjectId, ProviderName, SessionId, SubtaskId, TagId,
    TaskId, ZoneName,
};
use super::review_commands::{
    BulkReleaseRequest, ConsentGrantRequest, ConsentRevoke, Decide, Empty, ExplainerAck,
    FormulationRef, ParksAck, SessionFinish, SessionProgress, SessionStart, SettingsUpdate,
};
use super::review_state::{
    BulkRelease, BulkSkipped, BulkUndoResult, Decision, DecisionQueue, NavigatorConsent, ParkAck,
    ReleasedItem, ReviewReceipt, ReviewSession, ReviewSettings,
};
use super::tasks::{
    Comment, CommentWrite, Project, ProjectCreate, ProjectUpdate, SmartAdd, Subtask, SubtaskCreate,
    SubtaskTransition, SubtaskUpdate, Tag, TagChanges, TagCreate, TagUpdate, Task, TaskCreate,
    TaskTransition, TaskUpdate,
};
use super::vocabulary::{OpenList, ProjectFilter, StepCode, TaskSort, WriterOrigin};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{CommandEnvelope, Precondition};
use bb_protocol::receipt::Binding;
use bb_protocol::wire::{CommandId, Counter, Id, Instant, OpenObject, RecordKey};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;

// ----------------------------------------------------------------------- command

/// The frozen sync v1 catalog as typed payloads. `type` and `payload` mirror the
/// envelope; the target is the envelope's `entity_id` and is carried by
/// [`DomainCommand`].
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum Command {
    #[serde(rename = "project.create")]
    ProjectCreate(ProjectCreate),
    #[serde(rename = "project.update")]
    ProjectUpdate(ProjectUpdate),
    #[serde(rename = "project.archive")]
    ProjectArchive(Empty),
    #[serde(rename = "project.unarchive")]
    ProjectUnarchive(Empty),
    #[serde(rename = "tag.create")]
    TagCreate(TagCreate),
    #[serde(rename = "tag.update")]
    TagUpdate(TagUpdate),
    #[serde(rename = "tag.delete")]
    TagDelete(Empty),
    #[serde(rename = "task.create")]
    TaskCreate(TaskCreate),
    #[serde(rename = "task.smart_add")]
    TaskSmartAdd(SmartAdd),
    #[serde(rename = "task.update")]
    TaskUpdate(TaskUpdate),
    #[serde(rename = "task.tags")]
    TaskTags(TagChanges),
    #[serde(rename = "task.transition")]
    TaskTransition(TaskTransition),
    #[serde(rename = "subtask.create")]
    SubtaskCreate(SubtaskCreate),
    #[serde(rename = "subtask.update")]
    SubtaskUpdate(SubtaskUpdate),
    #[serde(rename = "subtask.transition")]
    SubtaskTransition(SubtaskTransition),
    #[serde(rename = "comment.create")]
    CommentCreate(CommentWrite),
    #[serde(rename = "comment.update")]
    CommentUpdate(CommentWrite),
    #[serde(rename = "review.decide")]
    ReviewDecide(Decide),
    #[serde(rename = "review.undo_decision")]
    ReviewUndoDecision(Empty),
    #[serde(rename = "review.auto_park")]
    ReviewAutoPark(FormulationRef),
    #[serde(rename = "review.explainer_ack")]
    ReviewExplainerAck(ExplainerAck),
    #[serde(rename = "review.settings")]
    ReviewSettings(SettingsUpdate),
    #[serde(rename = "review.parks_ack")]
    ReviewParksAck(ParksAck),
    #[serde(rename = "review.session_start")]
    ReviewSessionStart(SessionStart),
    #[serde(rename = "review.session_progress")]
    ReviewSessionProgress(SessionProgress),
    #[serde(rename = "review.session_finish")]
    ReviewSessionFinish(SessionFinish),
    #[serde(rename = "review.bulk_release")]
    ReviewBulkRelease(BulkReleaseRequest),
    #[serde(rename = "review.bulk_undo")]
    ReviewBulkUndo(Empty),
    #[serde(rename = "review.consent_grant")]
    ReviewConsentGrant(ConsentGrantRequest),
    #[serde(rename = "review.consent_revoke")]
    ReviewConsentRevoke(ConsentRevoke),
}

impl Command {
    /// The catalog type. Exhaustive: a new variant must name its type here.
    pub fn command_type(&self) -> CommandType {
        use CommandType as T;
        match self {
            Self::ProjectCreate(_) => T::ProjectCreate,
            Self::ProjectUpdate(_) => T::ProjectUpdate,
            Self::ProjectArchive(_) => T::ProjectArchive,
            Self::ProjectUnarchive(_) => T::ProjectUnarchive,
            Self::TagCreate(_) => T::TagCreate,
            Self::TagUpdate(_) => T::TagUpdate,
            Self::TagDelete(_) => T::TagDelete,
            Self::TaskCreate(_) => T::TaskCreate,
            Self::TaskSmartAdd(_) => T::TaskSmartAdd,
            Self::TaskUpdate(_) => T::TaskUpdate,
            Self::TaskTags(_) => T::TaskTags,
            Self::TaskTransition(_) => T::TaskTransition,
            Self::SubtaskCreate(_) => T::SubtaskCreate,
            Self::SubtaskUpdate(_) => T::SubtaskUpdate,
            Self::SubtaskTransition(_) => T::SubtaskTransition,
            Self::CommentCreate(_) => T::CommentCreate,
            Self::CommentUpdate(_) => T::CommentUpdate,
            Self::ReviewDecide(_) => T::ReviewDecide,
            Self::ReviewUndoDecision(_) => T::ReviewUndoDecision,
            Self::ReviewAutoPark(_) => T::ReviewAutoPark,
            Self::ReviewExplainerAck(_) => T::ReviewExplainerAck,
            Self::ReviewSettings(_) => T::ReviewSettings,
            Self::ReviewParksAck(_) => T::ReviewParksAck,
            Self::ReviewSessionStart(_) => T::ReviewSessionStart,
            Self::ReviewSessionProgress(_) => T::ReviewSessionProgress,
            Self::ReviewSessionFinish(_) => T::ReviewSessionFinish,
            Self::ReviewBulkRelease(_) => T::ReviewBulkRelease,
            Self::ReviewBulkUndo(_) => T::ReviewBulkUndo,
            Self::ReviewConsentGrant(_) => T::ReviewConsentGrant,
            Self::ReviewConsentRevoke(_) => T::ReviewConsentRevoke,
        }
    }

    /// Types one payload. Unknown fields, wrong types and out-of-range values are
    /// refused as [`Reason::InvalidPayload`], naming the offending value type
    /// when it is one of ours; the parser's own message is dropped because it
    /// can quote the input.
    pub fn from_payload(
        command_type: CommandType,
        payload: &OpenObject,
    ) -> Result<Self, DomainError> {
        let tagged =
            json!({ "type": command_type.as_str(), "payload": Value::Object(payload.clone()) });
        let command: Self = serde_json::from_value(tagged).map_err(|e| payload_error(&e))?;
        if command.command_type() == command_type {
            Ok(command)
        } else {
            Err(DomainError::new(Reason::InvalidPayload))
        }
    }

    /// Cross-field rules the canonical request models state structurally.
    pub fn check_shape(&self) -> Result<(), DomainError> {
        match self {
            Self::TaskTags(changes)
            | Self::TaskUpdate(TaskUpdate {
                tag_changes: Some(changes),
                ..
            }) if !changes.is_unique_and_disjoint() => {
                Err(DomainError::field(Reason::TagChangesOverlap, "tag_changes"))
            }
            Self::ReviewDecide(decide) => match decide.missing_fields().first() {
                Some(field) => Err(DomainError::field(Reason::DecisionFieldsMissing, field)),
                None => Ok(()),
            },
            _ => Ok(()),
        }
    }
}

fn payload_error(error: &serde_json::Error) -> DomainError {
    let message = error.to_string();
    let named = message
        .strip_prefix("invalid ")
        .and_then(|rest| rest.split(|c: char| !c.is_ascii_alphanumeric()).next())
        .filter(|name| name.starts_with(|c: char| c.is_ascii_uppercase()));
    match named {
        Some(name) => DomainError::field(Reason::InvalidPayload, name),
        None => DomainError::new(Reason::InvalidPayload),
    }
}

/// A revision check after the runtime resolved any `after_command` reference.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RevisionCheck {
    pub entity_type: EntityType,
    pub entity_id: Id,
    pub edit_revision: Counter,
}

/// A catalog command ready for `decide`: identity, target, checks and typed payload.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct DomainCommand {
    pub command_id: CommandId,
    /// The primary target (the new ID for creation; the scope ID for owner singletons).
    pub entity_id: Id,
    pub issued_at: Instant,
    pub preconditions: Vec<RevisionCheck>,
    #[serde(flatten)]
    pub command: Command,
}

impl DomainCommand {
    /// Types an executable envelope. `resolve` substitutes the edit revision of
    /// an accepted earlier command (an `after_command` precondition); `None`
    /// means that receipt is not known yet, which is
    /// [`Reason::DependencyPending`], never a guess.
    pub fn from_envelope(
        envelope: &CommandEnvelope,
        resolve: impl Fn(&CommandId) -> Option<Counter>,
    ) -> Result<Self, DomainError> {
        let stable = &envelope.envelope;
        if !envelope
            .command_type
            .supported_versions()
            .contains(&stable.command_version)
        {
            return Err(DomainError::new(Reason::UnsupportedCommandVersion));
        }
        if let Some(limit) = envelope.command_type.item_limit()
            && let Some(Value::Array(items)) = stable.payload.get("items")
            && items.len() > limit
        {
            return Err(DomainError::field(Reason::TooManyItems, "items"));
        }
        let command = Command::from_payload(envelope.command_type, &stable.payload)?;
        command.check_shape()?;
        let preconditions = envelope
            .preconditions
            .iter()
            .map(|precondition| match precondition {
                Precondition::Revision(check) => Ok(RevisionCheck {
                    entity_type: check.entity_type,
                    entity_id: check.entity_id.clone(),
                    edit_revision: check.edit_revision.clone(),
                }),
                Precondition::AfterCommand(after) => resolve(&after.after_command.command_id)
                    .map(|edit_revision| RevisionCheck {
                        entity_type: after.after_command.entity_type,
                        entity_id: after.after_command.entity_id.clone(),
                        edit_revision,
                    })
                    .ok_or_else(|| DomainError::new(Reason::DependencyPending)),
            })
            .collect::<Result<_, _>>()?;
        Ok(Self {
            command_id: stable.command_id.clone(),
            entity_id: stable.entity_id.clone(),
            issued_at: stable.issued_at.clone(),
            preconditions,
            command,
        })
    }

    pub fn command_type(&self) -> CommandType {
        self.command.command_type()
    }
}

// ------------------------------------------------------------------ execution inputs

/// Explicit, trusted execution facts. The core has no clock, randomness or I/O.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionInputs {
    pub rule_version: u32,
    /// The effective instant (server time, or the device's for local projection).
    pub now: Instant,
    pub time_zone: ZoneName,
    pub origin: WriterOrigin,
    pub actor_id: ActorId,
    /// True only where private Undo and park snapshots are loaded (the server).
    pub authoritative: bool,
    /// IDs the rules may mint, in the order they are consumed.
    pub allocated_ids: Vec<Id>,
    pub policy: Policy,
}

/// Server or OS capability facts; never read from a client payload.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Policy {
    pub weekly_review: bool,
    pub navigator_provider: Option<ProviderName>,
    pub navigator_available: bool,
    pub consent_text_version: u32,
}

// ------------------------------------------------------------------------ read set

/// The protected read set loaded under the owner lock. Facts the command needs
/// but the set lacks are reported as [`Reason::IncompleteReadSet`], not defaulted.
/// Receipts, park acknowledgements and consents are unique by their record key.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ReadSet {
    pub tasks: BTreeMap<TaskId, Task>,
    pub projects: BTreeMap<ProjectId, Project>,
    pub tags: BTreeMap<TagId, Tag>,
    pub subtasks: BTreeMap<SubtaskId, Subtask>,
    pub comments: BTreeMap<CommentId, Comment>,
    pub settings: Option<ReviewSettings>,
    pub sessions: BTreeMap<SessionId, ReviewSession>,
    pub decision_queues: BTreeMap<SessionId, DecisionQueue>,
    pub decisions: BTreeMap<DecisionId, Decision>,
    pub receipts: Vec<ReviewReceipt>,
    pub park_acks: Vec<ParkAck>,
    pub bulk_releases: BTreeMap<BulkId, BulkRelease>,
    pub consents: Vec<NavigatorConsent>,
}

// ------------------------------------------------------------------------ records

/// One replicated record: the after-image of a changed row.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[allow(clippy::large_enum_variant)]
#[serde(tag = "entity_type", content = "value", rename_all = "snake_case")]
pub enum Record {
    Task(Task),
    Project(Project),
    Tag(Tag),
    Subtask(Subtask),
    Comment(Comment),
    ReviewSettings(ReviewSettings),
    ReviewSession(ReviewSession),
    ReviewDecisionQueue(DecisionQueue),
    ReviewDecision(Decision),
    ReviewReceipt(ReviewReceipt),
    ReviewParkAck(ParkAck),
    ReviewBulkRelease(BulkRelease),
    ReviewNavigatorConsent(NavigatorConsent),
}

impl Record {
    pub fn entity_type(&self) -> EntityType {
        match self {
            Self::Task(_) => EntityType::Task,
            Self::Project(_) => EntityType::Project,
            Self::Tag(_) => EntityType::Tag,
            Self::Subtask(_) => EntityType::Subtask,
            Self::Comment(_) => EntityType::Comment,
            Self::ReviewSettings(_) => EntityType::ReviewSettings,
            Self::ReviewSession(_) => EntityType::ReviewSession,
            Self::ReviewDecisionQueue(_) => EntityType::ReviewDecisionQueue,
            Self::ReviewDecision(_) => EntityType::ReviewDecision,
            Self::ReviewReceipt(_) => EntityType::ReviewReceipt,
            Self::ReviewParkAck(_) => EntityType::ReviewParkAck,
            Self::ReviewBulkRelease(_) => EntityType::ReviewBulkRelease,
            Self::ReviewNavigatorConsent(_) => EntityType::ReviewNavigatorConsent,
        }
    }

    /// The record key per data-model.md; settings is the empty singleton key.
    pub fn record_key(&self) -> RecordKey {
        let one = |id: &str| vec![id.to_owned()];
        match self {
            Self::Task(r) => one(r.id.as_str()),
            Self::Project(r) => one(r.id.as_str()),
            Self::Tag(r) => one(r.id.as_str()),
            Self::Subtask(r) => one(r.id.as_str()),
            Self::Comment(r) => one(r.id.as_str()),
            Self::ReviewSettings(_) => Vec::new(),
            Self::ReviewSession(r) => one(r.id.as_str()),
            Self::ReviewDecisionQueue(r) => one(r.session_id.as_str()),
            Self::ReviewDecision(r) => one(r.id.as_str()),
            Self::ReviewReceipt(r) => {
                vec![r.task_id.as_str().to_owned(), r.kind.as_str().to_owned()]
            }
            Self::ReviewParkAck(r) => vec![
                r.task_id.as_str().to_owned(),
                r.formulation_id.as_str().to_owned(),
            ],
            Self::ReviewBulkRelease(r) => one(r.id.as_str()),
            Self::ReviewNavigatorConsent(r) => one(r.provider.as_str()),
        }
    }

    /// The record as the public feed carries it: server-private members dropped.
    pub fn public(&self) -> Self {
        match self {
            Self::Task(r) => Self::Task(r.public()),
            Self::ReviewSettings(r) => Self::ReviewSettings(r.public()),
            Self::ReviewSession(r) => Self::ReviewSession(r.public()),
            Self::ReviewDecision(r) => Self::ReviewDecision(r.public()),
            Self::ReviewParkAck(r) => Self::ReviewParkAck(r.public()),
            Self::ReviewBulkRelease(r) => Self::ReviewBulkRelease(r.public()),
            other => other.clone(),
        }
    }
}

/// One change: an after-image or a tombstone.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[allow(clippy::large_enum_variant)]
#[serde(tag = "operation", rename_all = "snake_case")]
pub enum DomainChange {
    Upsert(Record),
    Tombstone {
        entity_type: EntityType,
        record_key: RecordKey,
    },
}

impl DomainChange {
    pub fn entity_type(&self) -> EntityType {
        match self {
            Self::Upsert(record) => record.entity_type(),
            Self::Tombstone { entity_type, .. } => *entity_type,
        }
    }

    pub fn record_key(&self) -> RecordKey {
        match self {
            Self::Upsert(record) => record.record_key(),
            Self::Tombstone { record_key, .. } => record_key.clone(),
        }
    }
}

/// Whether the command changed anything.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChangeOutcome {
    Applied,
    NoOp,
}

/// A durable internal effect the adapter commits with the domain change.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EffectIntent {
    pub kind: String,
    pub dedup_key: String,
    pub run_at: Option<Instant>,
}

/// Content-free result references a receipt may return.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ResultRefs {
    /// Smart Add alias resolutions: proposed ID to the resolved or created ID.
    pub id_bindings: Vec<Binding>,
    pub created_task_id: Option<TaskId>,
    pub deleted_task_id: Option<TaskId>,
    pub released: Vec<ReleasedItem>,
    pub skipped: Vec<BulkSkipped>,
    pub bulk_undo: Option<BulkUndoResult>,
    /// Auto-park only: `Some(false)` is an accepted no-op.
    pub applied: Option<bool>,
}

/// What `decide` returns: changes in application order, result references and effects.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChangeSet {
    pub outcome: ChangeOutcome,
    pub changes: Vec<DomainChange>,
    pub result: ResultRefs,
    pub effects: Vec<EffectIntent>,
}

impl ChangeSet {
    /// An accepted command that changed nothing.
    pub fn no_op() -> Self {
        Self {
            outcome: ChangeOutcome::NoOp,
            changes: Vec::new(),
            result: ResultRefs::default(),
            effects: Vec::new(),
        }
    }

    /// The `(entity type, record key)` of every change, in order.
    pub fn affected_keys(&self) -> Vec<(EntityType, RecordKey)> {
        self.changes
            .iter()
            .map(|change| (change.entity_type(), change.record_key()))
            .collect()
    }
}

// ------------------------------------------------------------------------- queries

/// A page request; the caller owns pagination.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Page {
    pub limit: u32,
    pub after: Option<String>,
}

/// A typed read over a consistent [`ReadSet`]. Output: [`super::QueryResult`].
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Query {
    TaskList {
        list: OpenList,
        project_id: Option<ProjectId>,
        tag_id: Option<TagId>,
        sort: TaskSort,
        page: Page,
    },
    TaskDetail {
        task_id: TaskId,
    },
    // Field-less variants are written `{}`: serde ignores unknown fields on a
    // unit variant of an internally tagged enum, a struct variant refuses them.
    ListCounts {},
    Projects {
        filter: ProjectFilter,
    },
    ProjectDisplay {
        project_id: ProjectId,
    },
    Tags {},
    ReviewState {},
    ReviewQueue {
        step: StepCode,
        session_id: Option<SessionId>,
    },
}

/// The explicit facts a query reads besides the state.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QueryInputs {
    pub now: Instant,
    pub device_zone: ZoneName,
    pub policy: Policy,
}
