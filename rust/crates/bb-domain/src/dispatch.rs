//! The one entry point from a catalog command or query to the rule family that
//! owns it (026 T062; contracts/runtime-ffi.md "Pure core").
//!
//! * [`decide_envelope`] types an executable envelope with
//!   [`DomainCommand::from_envelope`] (version, item ceilings, shape, Smart Add
//!   aliases and `after_command` revisions, read from the retained receipts),
//!   then routes it. A reference whose receipt is not known yet stays
//!   [`Reason::DependencyPending`]: nothing is decided and the envelope is
//!   retried unchanged.
//! * [`decide`] routes an already typed [`DomainCommand`] to the one family
//!   whose `handles` claims it.
//! * [`query`] routes a [`Query`] to the one family whose `handles_query`
//!   claims it. The Review reads belong to `review_sessions` and are asked
//!   before `queries`, which refuses them; the native list modes belong to
//!   `list_modes`.
//!
//! Ownership is read from each family's own `handles`/`handles_query`, never
//! restated here, so a family cannot change what it accepts without the
//! dispatch following. A command or query no family claims, or that more than
//! one claims, is an explicit refusal ([`unowned`]); neither case panics. The
//! tests assert that every command type and query kind of the frozen catalog
//! has exactly one owner, so the refusal is only ever reached by a command
//! outside the catalog.
//!
//! Pure: no clock, I/O or randomness. Every fact a rule needs arrives in the
//! read set and the inputs.

use crate::types::{
    ChangeSet, Command, Dependencies, DomainCommand, DomainError, ExecutionInputs, Query,
    QueryInputs, QueryResult, ReadSet, Reason,
};
use crate::{
    children, list_modes, organize, park, queries, review_decisions, review_sessions, smart_add,
    task_rules,
};
use bb_protocol::command::CommandEnvelope;

/// A rule family that decides commands.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CommandFamily {
    /// Subtasks and comments ([`children`]).
    Children,
    /// Projects, tags and `task.tags` ([`organize`]).
    Organize,
    /// `review.auto_park` and `review.parks_ack` ([`park`]).
    Park,
    /// Review decisions, Undo and bulk release ([`review_decisions`]).
    ReviewDecisions,
    /// Review sessions, settings, activation and consent ([`review_sessions`]).
    ReviewSessions,
    /// `task.smart_add` ([`smart_add`]).
    SmartAdd,
    /// `task.create`, `task.update` and `task.transition` ([`task_rules`]).
    TaskRules,
}

impl CommandFamily {
    /// Every family that decides commands, in dispatch order.
    pub const ALL: [Self; 7] = [
        Self::Children,
        Self::Organize,
        Self::Park,
        Self::ReviewDecisions,
        Self::ReviewSessions,
        Self::SmartAdd,
        Self::TaskRules,
    ];

    /// The family's own claim on a command.
    pub fn handles(self, command: &Command) -> bool {
        match self {
            Self::Children => children::handles(command),
            Self::Organize => organize::handles(command),
            Self::Park => park::handles(command),
            Self::ReviewDecisions => review_decisions::handles(command),
            Self::ReviewSessions => review_sessions::handles(command),
            Self::SmartAdd => smart_add::handles(command),
            Self::TaskRules => task_rules::handles(command),
        }
    }
}

/// A rule family that answers queries.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum QueryFamily {
    /// The native list modes: History, Agenda, date views and Search
    /// ([`list_modes`]).
    ListModes,
    /// Task, project and tag reads ([`queries`]).
    Queries,
    /// `ReviewState` and `ReviewQueue` ([`review_sessions`]).
    ReviewSessions,
}

impl QueryFamily {
    /// Every family that answers queries, in dispatch order (the Review reads
    /// are claimed before `queries` sees them).
    pub const ALL: [Self; 3] = [Self::ReviewSessions, Self::ListModes, Self::Queries];

    /// The family's own claim on a query.
    pub fn handles(self, query: &Query) -> bool {
        match self {
            Self::Queries => queries::handles_query(query),
            Self::ListModes => list_modes::handles_query(query),
            Self::ReviewSessions => review_sessions::handles_query(query),
        }
    }
}

/// The kinds of [`Query`], for the ownership table.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum QueryKind {
    TaskList,
    TaskDetail,
    ListCounts,
    Projects,
    ProjectDisplay,
    Tags,
    ReviewState,
    ReviewQueue,
    ListMode,
    TaskFormulation,
    ParkReturnShown,
    RestartCandidates,
    AutoParkDue,
    ReviewSummary,
    OpenReleases,
}

impl QueryKind {
    /// Every query kind of the catalog.
    pub const ALL: [Self; 15] = [
        Self::TaskList,
        Self::TaskDetail,
        Self::ListCounts,
        Self::Projects,
        Self::ProjectDisplay,
        Self::Tags,
        Self::ReviewState,
        Self::ReviewQueue,
        Self::ListMode,
        Self::TaskFormulation,
        Self::ParkReturnShown,
        Self::RestartCandidates,
        Self::AutoParkDue,
        Self::ReviewSummary,
        Self::OpenReleases,
    ];

    /// The wire spelling of `Query`'s `kind` tag.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::TaskList => "task_list",
            Self::TaskDetail => "task_detail",
            Self::ListCounts => "list_counts",
            Self::Projects => "projects",
            Self::ProjectDisplay => "project_display",
            Self::Tags => "tags",
            Self::ReviewState => "review_state",
            Self::ReviewQueue => "review_queue",
            Self::ListMode => "list_mode",
            Self::TaskFormulation => "task_formulation",
            Self::ParkReturnShown => "park_return_shown",
            Self::RestartCandidates => "restart_candidates",
            Self::AutoParkDue => "auto_park_due",
            Self::ReviewSummary => "review_summary",
            Self::OpenReleases => "open_releases",
        }
    }
}

/// The kind of a query. Exhaustive: a new variant must name its kind here.
pub fn query_kind(query: &Query) -> QueryKind {
    match query {
        Query::TaskList { .. } => QueryKind::TaskList,
        Query::TaskDetail { .. } => QueryKind::TaskDetail,
        Query::ListCounts {} => QueryKind::ListCounts,
        Query::Projects { .. } | Query::NativeProjects { .. } => QueryKind::Projects,
        Query::ProjectDisplay { .. } => QueryKind::ProjectDisplay,
        Query::Tags {} | Query::NativeTags { .. } => QueryKind::Tags,
        Query::ReviewState {} => QueryKind::ReviewState,
        Query::ReviewQueue { .. } => QueryKind::ReviewQueue,
        Query::ListMode { .. } => QueryKind::ListMode,
        Query::TaskFormulation { .. } => QueryKind::TaskFormulation,
        Query::ParkReturnShown { .. } => QueryKind::ParkReturnShown,
        Query::RestartCandidates { .. } => QueryKind::RestartCandidates,
        Query::AutoParkDue { .. } => QueryKind::AutoParkDue,
        Query::ReviewSummary { .. } => QueryKind::ReviewSummary,
        Query::OpenReleases { .. } => QueryKind::OpenReleases,
    }
}

/// Every family that claims the command. Exactly one is the contract; the
/// tests hold the families to it.
pub fn command_claims(command: &Command) -> Vec<CommandFamily> {
    CommandFamily::ALL
        .into_iter()
        .filter(|family| family.handles(command))
        .collect()
}

/// Every family that claims the query.
pub fn query_claims(query: &Query) -> Vec<QueryFamily> {
    QueryFamily::ALL
        .into_iter()
        .filter(|family| family.handles(query))
        .collect()
}

/// The refusal for a command or query no single family owns: the same
/// `invalid_payload` on `type` a family gives a command of another family.
pub fn unowned() -> DomainError {
    DomainError::field(Reason::InvalidPayload, "type")
}

/// The one family that decides the command.
///
/// # Errors
///
/// [`unowned`] when no family, or more than one, claims it.
pub fn command_owner(command: &Command) -> Result<CommandFamily, DomainError> {
    match command_claims(command).as_slice() {
        [family] => Ok(*family),
        _ => Err(unowned()),
    }
}

/// The one family that answers the query.
///
/// # Errors
///
/// [`unowned`] when no family, or more than one, claims it.
pub fn query_owner(query: &Query) -> Result<QueryFamily, DomainError> {
    match query_claims(query).as_slice() {
        [family] => Ok(*family),
        _ => Err(unowned()),
    }
}

/// Types an executable envelope and decides it.
///
/// `dependencies` reads the retained terminal receipts of earlier commands (an
/// `after_command` revision, a Smart Add alias binding); a receipt not known
/// yet is [`Reason::DependencyPending`] and the envelope is untouched.
///
/// # Errors
///
/// Whatever [`DomainCommand::from_envelope`] or the owning family's `decide`
/// refuses; [`unowned`] for a command without exactly one owner.
pub fn decide_envelope(
    read_set: &ReadSet,
    envelope: &CommandEnvelope,
    dependencies: &(impl Dependencies + ?Sized),
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    let command = DomainCommand::from_envelope(envelope, dependencies)?;
    decide(read_set, &command, inputs)
}

/// Decides a typed command with the one family that owns it.
///
/// # Errors
///
/// The owning family's refusal; [`unowned`] for a command without exactly one
/// owner.
pub fn decide(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    match command_owner(&command.command)? {
        CommandFamily::Children => children::decide(read_set, command, inputs),
        CommandFamily::Organize => organize::decide(read_set, command, inputs),
        CommandFamily::Park => park::decide(read_set, command, inputs),
        CommandFamily::ReviewDecisions => review_decisions::decide(read_set, command, inputs),
        CommandFamily::ReviewSessions => review_sessions::decide(read_set, command, inputs),
        CommandFamily::SmartAdd => smart_add::decide(read_set, command, inputs),
        CommandFamily::TaskRules => task_rules::decide(read_set, command, inputs),
    }
}

/// Answers a query with the one family that owns it.
///
/// # Errors
///
/// The owning family's refusal; [`unowned`] for a query without exactly one
/// owner.
pub fn query(
    read_set: &ReadSet,
    query: &Query,
    inputs: &QueryInputs,
) -> Result<QueryResult, DomainError> {
    match query_owner(query)? {
        QueryFamily::ReviewSessions => review_sessions::query(read_set, query, inputs),
        QueryFamily::ListModes => list_modes::query(read_set, query, inputs),
        QueryFamily::Queries => queries::query(read_set, query, inputs),
    }
}
