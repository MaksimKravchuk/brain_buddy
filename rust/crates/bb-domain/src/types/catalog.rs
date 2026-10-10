//! The frozen catalog unions: [`Command`] and [`DomainCommand::from_envelope`],
//! the protected [`ReadSet`], replicated [`Record`]s, the [`ChangeSet`] a
//! command produces and the execution and query inputs.
//!
//! `decide(read_set, command, inputs) -> ChangeSet | DomainError` and
//! `query(read_set, query, inputs) -> QueryResult` are deterministic: every
//! fact a rule needs (time, zone, IDs, policy, origin) arrives in the inputs.

use super::errors::{DomainError, Reason};
use super::primitives::{
    ActorId, BulkId, CommentId, DecisionId, FormulationId, ProjectId, ProviderName, SessionId,
    SubtaskId, TagId, TaskId, ZoneName,
};
use super::references::{AliasRef, Dependencies, ProjectRef, TagRef};
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
use super::vocabulary::{
    BulkKind, DateView, HistoryKind, OpenList, Priority, ProjectFilter, StepCode, TaskSort,
    WriterOrigin,
};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{CommandEnvelope, CommandRef, Precondition};
use bb_protocol::receipt::Binding;
use bb_protocol::wire::{CommandId, Counter, Id, Instant, OpenObject, RecordKey};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::hash::Hash;

// ----------------------------------------------------------------------- command

/// The frozen sync v1 catalog as typed payloads. `type` and `payload` mirror the
/// envelope; the target is the envelope's `entity_id` and is carried by
/// [`DomainCommand`].
///
/// `P` and `T` are the project and tag reference types of the payloads that
/// name them. `decide` reads the default, direct IDs; [`WireCommand`] is what
/// an envelope carries, where an earlier Smart Add alias may stand in, and
/// [`WireCommand::resolve`] turns it into the first.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", content = "payload")]
pub enum Command<P = ProjectId, T = TagId> {
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
    TaskCreate(TaskCreate<P, T>),
    #[serde(rename = "task.smart_add")]
    TaskSmartAdd(SmartAdd),
    #[serde(rename = "task.update")]
    TaskUpdate(TaskUpdate<P, T>),
    #[serde(rename = "task.tags")]
    TaskTags(TagChanges<T>),
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

/// A command as an envelope carries it: project and tag references may be
/// Smart Add aliases awaiting a retained receipt binding.
pub type WireCommand = Command<ProjectRef, TagRef>;

impl<P, T> Command<P, T> {
    /// The catalog type. Exhaustive: a new variant must name its type here.
    pub fn command_type(&self) -> CommandType {
        use CommandType as K;
        match self {
            Self::ProjectCreate(_) => K::ProjectCreate,
            Self::ProjectUpdate(_) => K::ProjectUpdate,
            Self::ProjectArchive(_) => K::ProjectArchive,
            Self::ProjectUnarchive(_) => K::ProjectUnarchive,
            Self::TagCreate(_) => K::TagCreate,
            Self::TagUpdate(_) => K::TagUpdate,
            Self::TagDelete(_) => K::TagDelete,
            Self::TaskCreate(_) => K::TaskCreate,
            Self::TaskSmartAdd(_) => K::TaskSmartAdd,
            Self::TaskUpdate(_) => K::TaskUpdate,
            Self::TaskTags(_) => K::TaskTags,
            Self::TaskTransition(_) => K::TaskTransition,
            Self::SubtaskCreate(_) => K::SubtaskCreate,
            Self::SubtaskUpdate(_) => K::SubtaskUpdate,
            Self::SubtaskTransition(_) => K::SubtaskTransition,
            Self::CommentCreate(_) => K::CommentCreate,
            Self::CommentUpdate(_) => K::CommentUpdate,
            Self::ReviewDecide(_) => K::ReviewDecide,
            Self::ReviewUndoDecision(_) => K::ReviewUndoDecision,
            Self::ReviewAutoPark(_) => K::ReviewAutoPark,
            Self::ReviewExplainerAck(_) => K::ReviewExplainerAck,
            Self::ReviewSettings(_) => K::ReviewSettings,
            Self::ReviewParksAck(_) => K::ReviewParksAck,
            Self::ReviewSessionStart(_) => K::ReviewSessionStart,
            Self::ReviewSessionProgress(_) => K::ReviewSessionProgress,
            Self::ReviewSessionFinish(_) => K::ReviewSessionFinish,
            Self::ReviewBulkRelease(_) => K::ReviewBulkRelease,
            Self::ReviewBulkUndo(_) => K::ReviewBulkUndo,
            Self::ReviewConsentGrant(_) => K::ReviewConsentGrant,
            Self::ReviewConsentRevoke(_) => K::ReviewConsentRevoke,
        }
    }
}

impl<P, T: Eq + Hash> Command<P, T> {
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

/// Types one payload. Unknown fields, wrong types and out-of-range values are
/// refused as [`Reason::InvalidPayload`], naming the offending value type
/// when it is one of ours; the parser's own message is dropped because it
/// can quote the input.
fn decode_payload<P, T>(
    command_type: CommandType,
    payload: &OpenObject,
) -> Result<Command<P, T>, DomainError>
where
    Command<P, T>: DeserializeOwned,
{
    let tagged =
        json!({ "type": command_type.as_str(), "payload": Value::Object(payload.clone()) });
    let command: Command<P, T> = serde_json::from_value(tagged).map_err(|e| payload_error(&e))?;
    if command.command_type() == command_type {
        Ok(command)
    } else {
        Err(DomainError::new(Reason::InvalidPayload))
    }
}

impl Command {
    /// Types one payload whose project and tag references are direct IDs;
    /// an alias reference is refused here (see [`WireCommand::from_wire_payload`]).
    pub fn from_payload(
        command_type: CommandType,
        payload: &OpenObject,
    ) -> Result<Self, DomainError> {
        decode_payload(command_type, payload)
    }
}

impl WireCommand {
    /// Types one payload as an envelope carries it: a project or tag
    /// reference is a direct ID or an alias to an earlier Smart Add command.
    pub fn from_wire_payload(
        command_type: CommandType,
        payload: &OpenObject,
    ) -> Result<Self, DomainError> {
        decode_payload(command_type, payload)
    }

    /// Replaces every alias with the ID the retained receipt bound to it, in
    /// memory only. The envelope is untouched: a payload that cannot resolve
    /// yet is [`Reason::DependencyPending`] and is retried unchanged.
    pub fn resolve(
        self,
        dependencies: &(impl Dependencies + ?Sized),
    ) -> Result<Command, DomainError> {
        Ok(match self {
            Self::TaskCreate(payload) => Command::TaskCreate(payload.resolve(dependencies)?),
            Self::TaskUpdate(payload) => Command::TaskUpdate(payload.resolve(dependencies)?),
            Self::TaskTags(changes) => Command::TaskTags(changes.resolve(dependencies)?),
            Self::ProjectCreate(p) => Command::ProjectCreate(p),
            Self::ProjectUpdate(p) => Command::ProjectUpdate(p),
            Self::ProjectArchive(p) => Command::ProjectArchive(p),
            Self::ProjectUnarchive(p) => Command::ProjectUnarchive(p),
            Self::TagCreate(p) => Command::TagCreate(p),
            Self::TagUpdate(p) => Command::TagUpdate(p),
            Self::TagDelete(p) => Command::TagDelete(p),
            Self::TaskSmartAdd(p) => Command::TaskSmartAdd(p),
            Self::TaskTransition(p) => Command::TaskTransition(p),
            Self::SubtaskCreate(p) => Command::SubtaskCreate(p),
            Self::SubtaskUpdate(p) => Command::SubtaskUpdate(p),
            Self::SubtaskTransition(p) => Command::SubtaskTransition(p),
            Self::CommentCreate(p) => Command::CommentCreate(p),
            Self::CommentUpdate(p) => Command::CommentUpdate(p),
            Self::ReviewDecide(p) => Command::ReviewDecide(p),
            Self::ReviewUndoDecision(p) => Command::ReviewUndoDecision(p),
            Self::ReviewAutoPark(p) => Command::ReviewAutoPark(p),
            Self::ReviewExplainerAck(p) => Command::ReviewExplainerAck(p),
            Self::ReviewSettings(p) => Command::ReviewSettings(p),
            Self::ReviewParksAck(p) => Command::ReviewParksAck(p),
            Self::ReviewSessionStart(p) => Command::ReviewSessionStart(p),
            Self::ReviewSessionProgress(p) => Command::ReviewSessionProgress(p),
            Self::ReviewSessionFinish(p) => Command::ReviewSessionFinish(p),
            Self::ReviewBulkRelease(p) => Command::ReviewBulkRelease(p),
            Self::ReviewBulkUndo(p) => Command::ReviewBulkUndo(p),
            Self::ReviewConsentGrant(p) => Command::ReviewConsentGrant(p),
            Self::ReviewConsentRevoke(p) => Command::ReviewConsentRevoke(p),
        })
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

/// Alias lookups are valid only for a command the envelope lists in
/// `depends_on` (command-catalog.md "Smart Add bindings").
struct Listed<'a, D: ?Sized> {
    dependencies: &'a D,
    depends_on: &'a [CommandId],
}

impl<D: Dependencies + ?Sized> Dependencies for Listed<'_, D> {
    fn edit_revision(&self, reference: &CommandRef) -> Result<Counter, DomainError> {
        self.dependencies.edit_revision(reference)
    }

    fn binding(&self, alias: &AliasRef) -> Result<Id, DomainError> {
        if self.depends_on.contains(&alias.after_command) {
            self.dependencies.binding(alias)
        } else {
            Err(DomainError::field(Reason::InvalidPayload, "depends_on"))
        }
    }
}

impl DomainCommand {
    /// Types an executable envelope without changing it. `dependencies` reads
    /// the retained terminal receipts of earlier commands:
    ///
    /// * an `after_command` precondition takes the edit revision the receipt
    ///   recorded for exactly the `entity_type` and `entity_id` it names;
    /// * a Smart Add alias reference takes the entity ID the receipt bound to
    ///   its `alias_id`.
    ///
    /// A receipt not known yet is [`Reason::DependencyPending`], never a
    /// guess; a known one lacking the named result is
    /// [`Reason::DependencyRejected`].
    pub fn from_envelope(
        envelope: &CommandEnvelope,
        dependencies: &(impl Dependencies + ?Sized),
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
        let wire = WireCommand::from_wire_payload(envelope.command_type, &stable.payload)?;
        wire.check_shape()?;
        let command = wire.resolve(&Listed {
            dependencies,
            depends_on: &stable.depends_on,
        })?;
        // Two references that resolve to one tag overlap only now.
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
                Precondition::AfterCommand(after) => dependencies
                    .edit_revision(&after.after_command)
                    .map(|edit_revision| RevisionCheck {
                        entity_type: after.after_command.entity_type,
                        entity_id: after.after_command.entity_id.clone(),
                        edit_revision,
                    }),
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
    /// Runtime-only bounded catalog selector; the server Projects shape stays unchanged.
    NativeProjects {
        filter: ProjectFilter,
        #[serde(default)]
        search: Option<String>,
        #[serde(default)]
        project_id: Option<ProjectId>,
    },
    NativeTags {
        #[serde(default)]
        search: Option<String>,
        #[serde(default)]
        sort: NativeTagSort,
    },
    ProjectDisplay {
        project_id: ProjectId,
    },
    Tags {},
    ReviewState {},
    TaskFormulation {
        task_id: TaskId,
    },
    ParkReturnShown {
        task_id: TaskId,
        parked_at: Option<Instant>,
        formulation_id: Option<FormulationId>,
    },
    RestartCandidates {},
    AutoParkDue {},
    ReviewSummary {
        session_id: Option<SessionId>,
        #[serde(default)]
        local: Option<ReviewPresentation>,
    },
    OpenReleases {
        release_kind: BulkKind,
        session_id: Option<SessionId>,
    },
    ReviewQueue {
        step: StepCode,
        session_id: Option<SessionId>,
    },
    /// A native list mode (History, Agenda, a date view, Search): sectioned
    /// rows in the Apple kit's order, one bounded page at a time.
    ListMode {
        mode: ListMode,
        #[serde(default)]
        options: ListOptions,
        page: Page,
    },
}

/// The destinations of `GTDQueries.list` that the server's `GET /tasks` has no
/// equivalent for (`Destination` in `Queries.swift`). The open lists, projects
/// and tags stay [`Query::TaskList`].
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum ListMode {
    OpenList {
        list: OpenList,
    },
    Project {
        project_id: ProjectId,
    },
    Tag {
        tag_id: TagId,
    },
    /// Completed or cancelled tasks, most recent first.
    History {
        kind: HistoryKind,
    },
    /// Open dated tasks as Overdue, Today and Upcoming sections.
    Agenda {},
    /// One of the agenda's sections on its own.
    DateView {
        view: DateView,
    },
    /// Title and notes, NFKC and case- and diacritic-insensitive, all states.
    Search {
        text: String,
    },
}

/// Native tag catalog order. Default/server ordering is unchanged.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeTagSort {
    #[default]
    Name,
    OpenCount,
}

/// `ListOptions` of `Queries.swift`; every field is optional on the wire.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ListOptions {
    pub sort: TaskSort,
    /// One section per project (name order, archived last, "No project" last)
    /// for open tasks. Ignored by the agenda; History groups its own rows.
    pub group_by_project: bool,
    /// Append completed tasks in the mode's range as a section. Search always
    /// includes them; History ignores it.
    pub show_completed: bool,
    /// As `show_completed`, for cancelled tasks.
    pub show_cancelled: bool,
    /// A set: empty means every priority, repeats mean nothing.
    pub priorities: Vec<Priority>,
    /// Narrow to tasks carrying this tag. A tag the read set lacks matches
    /// nothing; it is not an error.
    pub tag_filter: Option<TagId>,
    /// Optional title/notes search combined with this destination before paging.
    pub search: Option<String>,
}

/// The explicit facts a query reads besides the state.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QueryInputs {
    pub now: Instant,
    pub device_zone: ZoneName,
    pub policy: Policy,
}

/// Device presentation marks supplied explicitly; never canonical task/session state.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ReviewPresentation {
    pub explainer_seen_locally: bool,
    pub activated_at: Option<Instant>,
    pub ended_elsewhere_session: Option<SessionId>,
}

/// Borrowed private Review bookkeeping capability. It cannot be serialized.
/// Ordinary rules derive it from their existing server authority; only the
/// Rust dispatcher constructs the distinct local capability.
pub struct ReviewInputs<'a> {
    execution: &'a ExecutionInputs,
    private_review: bool,
    local_review: bool,
}
impl<'a> ReviewInputs<'a> {
    pub fn server(execution: &'a ExecutionInputs) -> Self {
        Self {
            execution,
            private_review: execution.authoritative,
            local_review: false,
        }
    }
    pub(crate) fn local(execution: &'a ExecutionInputs) -> Self {
        Self {
            execution,
            private_review: true,
            local_review: true,
        }
    }
    pub fn private_review(&self) -> bool {
        self.private_review
    }
    pub fn local_review(&self) -> bool {
        self.local_review
    }
}
impl std::ops::Deref for ReviewInputs<'_> {
    type Target = ExecutionInputs;
    fn deref(&self) -> &ExecutionInputs {
        self.execution
    }
}
