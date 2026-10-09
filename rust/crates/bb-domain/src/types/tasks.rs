//! Task, project, tag, subtask and comment: the public state subsets a rule
//! reads and writes, and the catalog payloads that change them.
//!
//! State follows `data-model.md` (revisions and order keys are decimal
//! strings; the formulation clock is stored facts only; advisory instants are
//! derived by queries). Payloads follow `command-catalog.md`: the canonical
//! request schema with creation IDs supplied up front and the concurrency
//! check moved to preconditions. Every payload rejects unknown fields.

use super::primitives::{
    ActorId, CaptureId, Color, CommentBody, CommentId, DesiredOutcome, Details, DueDay,
    FormulationId, Name, NewFormulationId, Patch, ProjectId, ReasonText, SubtaskId, TagId, TaskId,
    Title, WaitingFor, non_null, outcome_input, outcome_patch,
};
use super::review_state::{ClockBefore, Park};
use super::vocabulary::{
    ChildAction, ChildState, OpenList, Priority, ProjectState, TagState, TaskAction, TaskState,
};
use crate::calendar::UtcInstant;
use bb_protocol::wire::{Counter, Instant};
use serde::de::Error as _;
use serde::{Deserialize, Deserializer, Serialize};

// ----------------------------------------------------------------------- state

/// A task row. `subtasks` and `comments` are separate rows; membership is the
/// authoritative `project_id` and unique `tag_ids` on this row.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Task {
    pub id: TaskId,
    pub title: Title,
    pub details: Option<Details>,
    pub state: TaskState,
    pub project_id: Option<ProjectId>,
    pub tag_ids: Vec<TagId>,
    pub due_date: Option<DueDay>,
    pub priority: Priority,
    pub waiting_for: Option<WaitingFor>,
    pub waiting_since: Option<Instant>,
    pub order_key: Counter,
    pub source_capture_ids: Vec<CaptureId>,
    pub created_at: Instant,
    pub updated_at: Instant,
    pub completed_at: Option<Instant>,
    pub cancelled_at: Option<Instant>,
    pub revision: Counter,
    /// Survives leaving Next, where `formulation` is null; equals the public
    /// `formulation.consecutive_stalled` while a clock runs.
    pub consecutive_stalled_formulations: u32,
    pub formulation: Option<FormulationClock>,
    pub parked: Option<Park>,
}

impl Task {
    /// The task as the public feed carries it: no server-private park snapshot.
    pub fn public(&self) -> Self {
        Self {
            parked: self.parked.as_ref().map(Park::public),
            ..self.clone()
        }
    }
}

/// Stored formulation clock facts of a Next task.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FormulationClock {
    pub id: FormulationId,
    pub started_at: Instant,
    pub extended_at: Option<Instant>,
    pub extension_reason: Option<ReasonText>,
    pub park_floor_at: Option<Instant>,
}

impl FormulationClock {
    /// The clock a park or bulk release snapshots, with the stalled count.
    pub fn snapshot(&self, stalled_before: u32) -> ClockBefore {
        ClockBefore {
            formulation_id: Some(self.id.clone()),
            started_at: self.started_at.clone(),
            extended_at: self.extended_at.clone(),
            extension_reason: self.extension_reason.clone(),
            park_floor_at: self.park_floor_at.clone(),
            stalled_before,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Project {
    pub id: ProjectId,
    pub name: Name,
    pub color: Option<Color>,
    pub state: ProjectState,
    pub revision: Counter,
    pub desired_outcome: Option<DesiredOutcome>,
    pub archived_at: Option<Instant>,
    /// An archive cleared its tasks' project before archives kept memberships.
    pub archived_before_lossless: bool,
    /// When the project was created. Required, like Swift's `createdAt`; it
    /// orders same-name Smart Add ties (oldest wins, see [`Project::age_key`]).
    pub created_at: Instant,
}

impl Project {
    /// The tie-break order of same-name active projects: oldest first, then
    /// lowest ID (`(created_at, id)`, the Swift planner's and the server's).
    pub fn age_key(&self) -> (UtcInstant, &str) {
        (created_at_key(&self.created_at), self.id.as_str())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Tag {
    pub id: TagId,
    pub name: Name,
    pub state: TagState,
    pub revision: Counter,
    /// When the tag was created; orders same-name Smart Add ties like
    /// [`Project::created_at`].
    pub created_at: Instant,
}

impl Tag {
    /// The tie-break order of same-name active tags: `(created_at, id)`.
    pub fn age_key(&self) -> (UtcInstant, &str) {
        (created_at_key(&self.created_at), self.id.as_str())
    }
}

/// A creation instant as the server compares it (microsecond datetimes). The
/// only wire-valid value this rejects is a leap second (`:60`), which no
/// producer stamps: the server's Python `datetime` cannot represent one. Such a
/// value would sort first.
fn created_at_key(instant: &Instant) -> UtcInstant {
    UtcInstant::parse_rfc3339(instant.as_str()).unwrap_or(UtcInstant::EARLIEST)
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Subtask {
    pub id: SubtaskId,
    pub task_id: TaskId,
    pub title: Title,
    pub state: ChildState,
    pub order_key: Counter,
    pub revision: Counter,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Comment {
    pub id: CommentId,
    pub task_id: TaskId,
    pub body: CommentBody,
    pub actor_id: ActorId,
    pub created_at: Instant,
    pub edited_at: Option<Instant>,
    pub revision: Counter,
}

// -------------------------------------------------------------------- payloads

fn inbox() -> OpenList {
    OpenList::Inbox
}

fn no_priority() -> Priority {
    Priority::None
}

// `Default` for these would demand `P: Default`; an absent reference is empty.
fn no_ref<R>() -> Option<R> {
    None
}

fn no_refs<R>() -> Vec<R> {
    Vec::new()
}

/// `project.create`: the project ID is the envelope's `entity_id`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectCreate {
    pub name: Name,
    #[serde(default)]
    pub color: Option<Color>,
    /// Trimmed on input; blank means none.
    #[serde(default, deserialize_with = "outcome_input")]
    pub desired_outcome: Option<DesiredOutcome>,
}

/// `project.update`: `name` cannot be cleared; `color` and `desired_outcome`
/// distinguish omitted, `null` (clear) and value (set).
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ProjectUpdate {
    #[serde(deserialize_with = "non_null", skip_serializing_if = "Option::is_none")]
    pub name: Option<Name>,
    #[serde(skip_serializing_if = "Patch::is_unchanged")]
    pub color: Patch<Color>,
    #[serde(
        deserialize_with = "outcome_patch",
        skip_serializing_if = "Patch::is_unchanged"
    )]
    pub desired_outcome: Patch<DesiredOutcome>,
}

/// `tag.create`: the tag ID is the envelope's `entity_id`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TagCreate {
    pub name: Name,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TagUpdate {
    #[serde(deserialize_with = "non_null", skip_serializing_if = "Option::is_none")]
    pub name: Option<Name>,
}

/// `task.create`: the task ID is the envelope's `entity_id`. State and
/// priority default as the canonical request does (`inbox`, `none`).
///
/// `P` and `T` are the project and tag reference types: direct IDs once
/// resolved (the default, what `decide` reads), [`ProjectRef`] and [`TagRef`]
/// as they arrive on the wire, where an earlier Smart Add alias may stand in.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskCreate<P = ProjectId, T = TagId> {
    pub title: Title,
    #[serde(default)]
    pub details: Option<Details>,
    #[serde(default = "inbox")]
    pub state: OpenList,
    #[serde(default = "no_ref")]
    pub project_id: Option<P>,
    #[serde(default = "no_refs")]
    pub tag_ids: Vec<T>,
    #[serde(default)]
    pub due_date: Option<DueDay>,
    #[serde(default = "no_priority")]
    pub priority: Priority,
    #[serde(default)]
    pub waiting_for: Option<WaitingFor>,
    #[serde(default)]
    pub source_capture_ids: Vec<CaptureId>,
    #[serde(default)]
    pub new_formulation_id: Option<NewFormulationId>,
}

/// A Smart Add project or tag reference: an existing ID, or a name with the
/// ID the client proposes for its creation (bindings return the resolution).
/// Exactly one form is accepted and no other key (the canonical strict XOR).
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(untagged)]
pub enum ClassificationRef<I> {
    Existing { id: I },
    ByName { name: Name, proposed_id: I },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RawClassificationRef<I> {
    id: Option<I>,
    name: Option<Name>,
    proposed_id: Option<I>,
}

impl<'de, I: Deserialize<'de>> Deserialize<'de> for ClassificationRef<I> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let raw = RawClassificationRef::<I>::deserialize(deserializer)?;
        match (raw.id, raw.name, raw.proposed_id) {
            (Some(id), None, None) => Ok(Self::Existing { id }),
            (None, Some(name), Some(proposed_id)) => Ok(Self::ByName { name, proposed_id }),
            _ => Err(D::Error::custom(
                "a reference is an id, or a name with its proposed id",
            )),
        }
    }
}

/// `task.smart_add`: one task plus atomic resolve-or-create classification.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SmartAdd {
    pub title: Title,
    #[serde(default)]
    pub details: Option<Details>,
    #[serde(default = "inbox")]
    pub state: OpenList,
    #[serde(default)]
    pub waiting_for: Option<WaitingFor>,
    #[serde(default)]
    pub due_date: Option<DueDay>,
    #[serde(default = "no_priority")]
    pub priority: Priority,
    #[serde(default)]
    pub project: Option<ClassificationRef<ProjectId>>,
    #[serde(default)]
    pub tags: Vec<ClassificationRef<TagId>>,
    #[serde(default)]
    pub new_formulation_id: Option<NewFormulationId>,
}

/// Explicit tag membership edit: unique IDs, disjoint lists. `T` is the tag
/// reference type (see [`TaskCreate`]).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct TagChanges<T = TagId> {
    pub add_tag_ids: Vec<T>,
    pub remove_tag_ids: Vec<T>,
}

impl<T> Default for TagChanges<T> {
    fn default() -> Self {
        Self {
            add_tag_ids: Vec::new(),
            remove_tag_ids: Vec::new(),
        }
    }
}

impl<T: Eq + std::hash::Hash> TagChanges<T> {
    /// Whether every ID appears once across both lists.
    pub fn is_unique_and_disjoint(&self) -> bool {
        let mut seen = std::collections::HashSet::new();
        self.add_tag_ids
            .iter()
            .chain(&self.remove_tag_ids)
            .all(|id| seen.insert(id))
    }
}

/// `task.update`: lifecycle is not a patch. `title` and `priority` cannot be
/// cleared; `details`, `project_id`, `due_date` and `waiting_for` can.
/// `P` and `T` are the project and tag reference types (see [`TaskCreate`]).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(
    default,
    deny_unknown_fields,
    bound(deserialize = "P: Deserialize<'de>, T: Deserialize<'de>")
)]
pub struct TaskUpdate<P = ProjectId, T = TagId> {
    #[serde(deserialize_with = "non_null", skip_serializing_if = "Option::is_none")]
    pub title: Option<Title>,
    #[serde(skip_serializing_if = "Patch::is_unchanged")]
    pub details: Patch<Details>,
    #[serde(skip_serializing_if = "Patch::is_unchanged")]
    pub project_id: Patch<P>,
    #[serde(skip_serializing_if = "Patch::is_unchanged")]
    pub due_date: Patch<DueDay>,
    #[serde(deserialize_with = "non_null", skip_serializing_if = "Option::is_none")]
    pub priority: Option<Priority>,
    #[serde(skip_serializing_if = "Patch::is_unchanged")]
    pub waiting_for: Patch<WaitingFor>,
    /// One gesture, one command: tag edits ride in the same payload.
    #[serde(deserialize_with = "non_null", skip_serializing_if = "Option::is_none")]
    pub tag_changes: Option<TagChanges<T>>,
    #[serde(deserialize_with = "non_null", skip_serializing_if = "Option::is_none")]
    pub new_formulation_id: Option<NewFormulationId>,
}

impl<P, T> Default for TaskUpdate<P, T> {
    fn default() -> Self {
        Self {
            title: None,
            details: Patch::Unchanged,
            project_id: Patch::Unchanged,
            due_date: Patch::Unchanged,
            priority: None,
            waiting_for: Patch::Unchanged,
            tag_changes: None,
            new_formulation_id: None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskTransition {
    pub action: TaskAction,
    #[serde(default)]
    pub to_state: Option<OpenList>,
    #[serde(default)]
    pub waiting_for: Option<WaitingFor>,
    #[serde(default)]
    pub new_formulation_id: Option<NewFormulationId>,
}

/// `subtask.create`: the subtask ID is the envelope's `entity_id`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SubtaskCreate {
    pub task_id: TaskId,
    pub title: Title,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SubtaskUpdate {
    pub task_id: TaskId,
    #[serde(
        default,
        deserialize_with = "non_null",
        skip_serializing_if = "Option::is_none"
    )]
    pub title: Option<Title>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SubtaskTransition {
    pub task_id: TaskId,
    pub action: ChildAction,
}

/// `comment.create` and `comment.update`; the actor is server-derived.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommentWrite {
    pub task_id: TaskId,
    pub body: CommentBody,
}
