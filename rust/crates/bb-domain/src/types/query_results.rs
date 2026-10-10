//! Query outputs: what `query(read_set, query, inputs)` returns.
//!
//! Shapes follow the existing API results (`TaskResponse`, `TaskListResponse`,
//! `ReviewStateResponse`, `QueueResponse`, `ProjectResponse`) and the Apple
//! kit's read model (`ListCounts`, `ProjectSummary`, `TagSummary`,
//! `ProjectDisplay`), with sync v1's decimal-string counters. They are derived
//! views: nothing here is persisted or replicated, and none carries
//! server-private state. Advisory formulation instants and the Review
//! classifications are computed by the owning rule families; this module only
//! freezes where they go.

use super::primitives::{
    ActorId, CaptureId, CommentBody, CommentId, Details, DueDay, FormulationId, ProjectId,
    ReasonText, SessionId, SubtaskId, TagId, TaskId, Title, WaitingFor,
};
use super::review_state::{ReviewSession, ReviewSettings, SessionCounts};
use super::tasks::{Comment, FormulationClock, Project, Subtask, Tag, Task};
use super::vocabulary::{
    ChildState, ClearStart, CountedStatus, DateView, Priority, ReceiptKind, ReviewOrigin, TaskState,
};
use bb_protocol::wire::{Counter, Instant};
use serde::{Deserialize, Serialize};

/// The result of one [`Query`](super::Query), tagged by query kind.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[allow(clippy::large_enum_variant)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum QueryResult {
    TaskList(TaskListResult),
    TaskDetail(TaskView),
    ListCounts(ListCounts),
    Projects(Vec<ProjectSummary>),
    ProjectDisplay(ProjectDisplay),
    Tags(Vec<TagSummary>),
    ReviewState(Box<ReviewStateView>),
    ReviewQueue(QueueView),
    ListMode(ListModePage),
    TaskFormulation(TaskFormulationView),
    ParkReturnShown(Option<ParkReturnProblem>),
    RestartCandidates(Vec<TaskView>),
    AutoParkDue(Vec<TaskView>),
    ReviewSummary(ReviewSummaryView),
    OpenReleases(Vec<super::BulkRelease>),
}

// ----------------------------------------------------------------------- tasks

/// A task as an API client sees it (`TaskResponse`), children embedded.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskView {
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
    pub subtasks: Vec<SubtaskView>,
    pub comments: Vec<CommentView>,
    #[serde(default)]
    pub consecutive_stalled_formulations: u32,
    pub formulation: Option<FormulationView>,
    pub parked: Option<ParkView>,
}

impl TaskView {
    /// The view of a stored task with its children. Advisory formulation
    /// instants stay unset until the formulation family derives them.
    pub fn new(task: &Task, subtasks: Vec<SubtaskView>, comments: Vec<CommentView>) -> Self {
        Self {
            id: task.id.clone(),
            title: task.title.clone(),
            details: task.details.clone(),
            state: task.state,
            project_id: task.project_id.clone(),
            tag_ids: task.tag_ids.clone(),
            due_date: task.due_date.clone(),
            priority: task.priority,
            waiting_for: task.waiting_for.clone(),
            waiting_since: task.waiting_since.clone(),
            order_key: task.order_key.clone(),
            source_capture_ids: task.source_capture_ids.clone(),
            created_at: task.created_at.clone(),
            updated_at: task.updated_at.clone(),
            completed_at: task.completed_at.clone(),
            cancelled_at: task.cancelled_at.clone(),
            revision: task.revision.clone(),
            subtasks,
            comments,
            consecutive_stalled_formulations: task.consecutive_stalled_formulations,
            formulation: task.formulation.as_ref().map(|clock| {
                FormulationView::from_clock(clock, task.consecutive_stalled_formulations)
            }),
            parked: task.parked.as_ref().map(|park| ParkView {
                at: park.at.clone(),
                formulation_id: park.formulation_id.clone(),
            }),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SubtaskView {
    pub id: SubtaskId,
    pub title: Title,
    pub state: ChildState,
    pub order_key: Counter,
    pub revision: Counter,
}

impl From<&Subtask> for SubtaskView {
    fn from(subtask: &Subtask) -> Self {
        Self {
            id: subtask.id.clone(),
            title: subtask.title.clone(),
            state: subtask.state,
            order_key: subtask.order_key.clone(),
            revision: subtask.revision.clone(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommentView {
    pub id: CommentId,
    pub body: CommentBody,
    pub actor_id: ActorId,
    pub created_at: Instant,
    pub edited_at: Option<Instant>,
    pub revision: Counter,
}

impl From<&Comment> for CommentView {
    fn from(comment: &Comment) -> Self {
        Self {
            id: comment.id.clone(),
            body: comment.body.clone(),
            actor_id: comment.actor_id.clone(),
            created_at: comment.created_at.clone(),
            edited_at: comment.edited_at.clone(),
            revision: comment.revision.clone(),
        }
    }
}

/// The formulation clock of a Next task: stored facts plus the stalled count
/// and the advisory instants (null while the owner is not activated).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FormulationView {
    pub id: FormulationId,
    pub started_at: Instant,
    pub extended_at: Option<Instant>,
    pub extension_reason: Option<ReasonText>,
    pub park_floor_at: Option<Instant>,
    pub consecutive_stalled: u32,
    pub ageing_at: Option<Instant>,
    pub ask_at: Option<Instant>,
    pub park_due_at: Option<Instant>,
    pub paused_until: Option<Instant>,
}

impl FormulationView {
    /// Stored facts with every advisory instant unset.
    pub fn from_clock(clock: &FormulationClock, consecutive_stalled: u32) -> Self {
        Self {
            id: clock.id.clone(),
            started_at: clock.started_at.clone(),
            extended_at: clock.extended_at.clone(),
            extension_reason: clock.extension_reason.clone(),
            park_floor_at: clock.park_floor_at.clone(),
            consecutive_stalled,
            ageing_at: None,
            ask_at: None,
            park_due_at: None,
            paused_until: None,
        }
    }
}

/// The public park marker (`clock_before` never leaves the server).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ParkView {
    pub at: Instant,
    pub formulation_id: FormulationId,
}

/// Open-task counts of the four lists (`TaskCounts`).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskCounts {
    pub inbox: u32,
    pub next: u32,
    pub waiting: u32,
    pub someday: u32,
}

/// One list page (`TaskListResponse`). The cursor is bound to the query and
/// the projection generation by the caller.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskListResult {
    pub items: Vec<TaskView>,
    pub next_cursor: Option<String>,
    pub has_more: bool,
    pub counts_by_state: TaskCounts,
}

/// One page of a native list mode (`TaskListResult` of the Apple kit, paged):
/// the sections' rows in order. A section the page starts inside continues the
/// previous page's last one under the same `id`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ListModePage {
    pub sections: Vec<PageSection>,
    /// Open tasks in the whole result, not the page (terminal rows excluded).
    pub open_count: u32,
    pub next_cursor: Option<String>,
    pub has_more: bool,
}

/// The rows of one section on a page. `id` is stable across pages and
/// recomputation: `open`, `project:<id>`, `none`, `date:<view>`, `completed`,
/// `cancelled`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PageSection {
    pub id: String,
    /// The header, or none for a single unnamed section.
    pub title: Option<String>,
    pub kind: SectionKind,
    pub items: Vec<TaskView>,
}

/// What a section holds (`TaskSection.Kind`).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum SectionKind {
    Open {},
    List {
        list: super::OpenList,
    },
    /// `project_id` is none for the "No project" section.
    Project {
        project_id: Option<ProjectId>,
    },
    DateView {
        view: DateView,
    },
    Completed {},
    Cancelled {},
}

/// Global badge counts over open tasks; they ignore the screen's filters. Inbox
/// counts projectless inbox tasks only; `overdue` and `today` use the device day.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ListCounts {
    pub inbox: u32,
    pub next: u32,
    pub waiting: u32,
    pub someday: u32,
    pub overdue: u32,
    pub today: u32,
}

// ------------------------------------------------------- projects and tags

/// A project with its open-task counts, in name order.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectSummary {
    pub project: Project,
    pub open_task_count: u32,
    pub next_action_count: u32,
}

impl ProjectSummary {
    /// An active project without an open next action: the "stuck" signal.
    pub fn needs_next_action(&self) -> bool {
        self.project.state == super::vocabulary::ProjectState::Active && self.next_action_count == 0
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TagSummary {
    pub tag: Tag,
    pub open_task_count: u32,
}

/// How a project presents itself, decided once for every surface (FR-025, FR-027).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ProjectDisplay {
    pub is_archived: bool,
    /// False for an archived project: capture into it is refused until unarchived.
    pub accepts_new_tasks: bool,
    /// Archived before archives kept memberships and no task of any state is left.
    pub shows_pre_lossless_line: bool,
    /// The name, with " · archived" after an archived project's.
    pub label: String,
}

// ------------------------------------------------------------------ review

/// `GET /review/state` as a derived view of the replicated rows, the explicit
/// time and zone, and current policy.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewStateView {
    pub settings: ReviewSettings,
    pub explainer_seen: bool,
    pub grace_until: Option<Instant>,
    pub last_counted_review_at: Option<Instant>,
    pub last_counted_review: Option<LastCountedReview>,
    pub next_review_at: Instant,
    pub restart_mode: bool,
    pub open_session: Option<ReviewSession>,
    pub unseen_parks: Vec<UnseenPark>,
    pub counts: ReviewStateCounts,
    pub receipts: Vec<ReceiptView>,
    pub server_now: Instant,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LastCountedReview {
    pub session_id: SessionId,
    pub status: CountedStatus,
    pub origin: ReviewOrigin,
    pub ended_at: Option<Instant>,
    pub counts: SessionCounts,
    pub clear_start: Option<ClearStart>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UnseenPark {
    pub task_id: TaskId,
    pub formulation_id: FormulationId,
    pub parked_at: Instant,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewStateCounts {
    pub asks_for_decision: u32,
    pub moves_tomorrow: u32,
}

/// The public face of a Keep or release receipt (`ReviewReceiptResponse`).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReceiptView {
    pub task_id: TaskId,
    pub kind: ReceiptKind,
    pub hidden_until: Instant,
    pub task_revision: Counter,
}

/// `GET /review/queues/{step}`: the cards and the step's own metadata.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QueueView {
    pub items: Vec<TaskView>,
    pub meta: QueueMeta,
}

/// Step metadata. Each shape is strict and distinct, so the union is decoded
/// without a tag, as the API sends it; steps without metadata send `{}`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum QueueMeta {
    Wins(WinsMeta),
    RestOfNext(RestOfNextMeta),
    Someday(SomedayMeta),
    Dates(DatesMeta),
    Decisions(DecisionsMeta),
    Empty(NoMeta),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WinsMeta {
    pub count: u32,
}

/// The capacity mirror (FR-031): pace and implied weeks need four weeks of history.
#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RestOfNextMeta {
    pub next_count: u32,
    pub weekly_average_4w: Option<f64>,
    pub weeks_of_history: u32,
    pub implied_weeks: Option<f64>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SomedayMeta {
    pub eligible_total: u32,
    pub shown: u32,
}

/// The next 14 days grouped by local day.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DatesMeta {
    pub days: Vec<DatesDay>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DatesDay {
    pub day: DueDay,
    pub task_ids: Vec<TaskId>,
}

/// Which cards of the run are handled already, in queue order.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DecisionsMeta {
    pub decided_task_ids: Vec<TaskId>,
    pub set_aside_task_ids: Vec<TaskId>,
}

/// Steps without metadata: inbox, waiting, projects.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NoMeta {}

/// Clock-derived native helpers, read from the same protected generation as tasks.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DerivedView {
    pub start: Instant,
    pub ageing_at: Instant,
    pub ask_at: Instant,
    pub park_due_at: Instant,
    pub tomorrow_at: Instant,
    pub paused_until: Option<Instant>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TaskFormulationView {
    pub task_id: TaskId,
    pub class: String,
    pub derived: Option<DerivedView>,
    pub third_stall: bool,
    pub extension: Option<DerivedView>,
    pub parked_after_days: Option<i64>,
    pub unavailable_local_facts: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ParkReturnProblem {
    ChangedElsewhere,
    ProjectArchived { name: String },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum DecisionStepView {
    Card {
        task_id: TaskId,
        position: u32,
        total: u32,
    },
    NothingAsks,
    AllDecided {
        decided: u32,
        kept_wording: u32,
    },
    SomeLeft {
        decided: u32,
        total: u32,
        still_asking: u32,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReviewSummaryView {
    /// The public session does not carry the local end reason. Do not guess it.
    pub entry_notice: Option<serde_json::Value>,
    pub explainer_needed: bool,
    pub days_since_last_review: Option<i64>,
    pub decision_step: Option<DecisionStepView>,
    pub unavailable_local_facts: Vec<String>,
}
