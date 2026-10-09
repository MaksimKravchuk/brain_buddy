//! Closed vocabularies of the Tasks aggregate and native Review. Each enum
//! lists every variant (`ALL`) with its wire spelling (`as_str`), pinned to
//! `backend/app/schemas/{tasks,review}.py` and `ios/.../Vocabulary.swift`.

use serde::{Deserialize, Serialize};

/// Defines a closed, ordered string enum with `ALL`, `as_str` and `from_wire`.
macro_rules! vocab {
    ($($(#[$doc:meta])* $name:ident { $($variant:ident => $wire:literal),+ $(,)? })*) => {$(
        $(#[$doc])*
        #[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
        pub enum $name {
            $(#[serde(rename = $wire)] $variant),+
        }

        impl $name {
            /// Every variant, in declaration order.
            pub const ALL: &'static [Self] = &[$(Self::$variant),+];

            pub fn as_str(self) -> &'static str {
                match self { $(Self::$variant => $wire),+ }
            }

            pub fn from_wire(value: &str) -> Option<Self> {
                match value { $($wire => Some(Self::$variant),)+ _ => None }
            }
        }
    )*};
}
pub(crate) use vocab;

vocab! {
    /// Task state: four open lists plus two terminal states.
    TaskState {
        Inbox => "inbox", Next => "next", Waiting => "waiting", Someday => "someday",
        Completed => "completed", Cancelled => "cancelled",
    }
    /// The four open lists (`OpenTaskState`).
    OpenList { Inbox => "inbox", Next => "next", Waiting => "waiting", Someday => "someday" }
    Priority { None => "none", Low => "low", Medium => "medium", High => "high" }
    ProjectState { Active => "active", Archived => "archived" }
    TagState { Active => "active", Deleted => "deleted" }
    /// Subtask lifecycle.
    ChildState { Open => "open", Completed => "completed", Cancelled => "cancelled" }
    TaskAction { Move => "move", Complete => "complete", Reopen => "reopen", Cancel => "cancel" }
    ChildAction { Complete => "complete", Reopen => "reopen", Cancel => "cancel" }
    DecisionType {
        Complete => "complete", Reformulate => "reformulate", FirstStep => "first_step",
        Waiting => "waiting", Someday => "someday", Cancel => "cancel", Extend => "extend",
        KeepWaiting => "keep_waiting", FollowUp => "follow_up", ReturnToNext => "return_to_next",
        KeepSomeday => "keep_someday",
    }
    StallReason {
        Unclear => "unclear", TooBig => "too_big", MissingInfo => "missing_info",
        WaitingOnSomeone => "waiting_on_someone", NoEnergy => "no_energy",
        NoLongerMatters => "no_longer_matters",
    }
    AiUse { None => "none", AsIs => "as_is", Edited => "edited", NotUsed => "not_used" }
    /// The summary counter a decision is counted in (the ten session counts).
    CountBucket {
        Done => "done", Reformulated => "reformulated", FirstStep => "first_step",
        Waiting => "waiting", Someday => "someday", Cancelled => "cancelled",
        Extended => "extended", InboxProcessed => "inbox_processed", Kept => "kept",
        MovedToNext => "moved_to_next",
    }
    ReceiptKind { Waiting => "waiting", Someday => "someday" }
    ReceiptSource { Keep => "keep", Release => "release" }
    ParkSource { Sweep => "sweep", Device => "device" }
    SessionStatus {
        Open => "open", Completed => "completed", CompletedEmpty => "completed_empty",
        Partial => "partial", Abandoned => "abandoned",
    }
    StepCode {
        Wins => "wins", MindSweep => "mind_sweep", Inbox => "inbox", Decisions => "decisions",
        RestOfNext => "rest_of_next", Waiting => "waiting", Projects => "projects",
        Someday => "someday", Dates => "dates", Summary => "summary",
    }
    StepStatus { Pending => "pending", Finished => "finished", Skipped => "skipped" }
    ReviewMode { Quick => "quick", Full => "full" }
    ReviewEntry {
        List => "list", Notification => "notification", WidgetDecisions => "widget_decisions",
        Sidebar => "sidebar", Restart => "restart",
    }
    ReviewOrigin { Ios => "ios", Web => "web", Macos => "macos" }
    ClearStart { Yes => "yes", NotReally => "not_really" }
    BulkKind { Restart => "restart", InboxRemainder => "inbox_remainder" }
    SkipReason { Stale => "stale", NotEligible => "not_eligible" }
    /// Why a bulk Undo left a task alone.
    UndoSkipReason { Stale => "stale" }
    /// The two states a counted review can end in (`last_counted_review.status`).
    CountedStatus { Completed => "completed", Partial => "partial" }
    TaskSort { Manual => "manual", Due => "due", Priority => "priority", Title => "title" }
    ProjectFilter { Active => "active", Archived => "archived", All => "all" }
    /// Trusted writer origin the execution boundary supplies (command-catalog.md).
    WriterOrigin {
        Device => "device", Legacy => "legacy", Application => "application", Job => "job",
    }
}

impl OpenList {
    /// The task state this list holds.
    pub fn task_state(self) -> TaskState {
        match self {
            Self::Inbox => TaskState::Inbox,
            Self::Next => TaskState::Next,
            Self::Waiting => TaskState::Waiting,
            Self::Someday => TaskState::Someday,
        }
    }
}

impl TaskState {
    /// The open list for an open state; `None` for completed and cancelled.
    pub fn open_list(self) -> Option<OpenList> {
        match self {
            Self::Inbox => Some(OpenList::Inbox),
            Self::Next => Some(OpenList::Next),
            Self::Waiting => Some(OpenList::Waiting),
            Self::Someday => Some(OpenList::Someday),
            Self::Completed | Self::Cancelled => None,
        }
    }

    pub fn is_open(self) -> bool {
        self.open_list().is_some()
    }
}
