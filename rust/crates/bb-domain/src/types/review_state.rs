//! Native Review state subsets (data-model.md): settings, sessions, decision
//! queues, decisions, receipts, park acknowledgements, bulk releases and
//! Navigator consent.
//!
//! Server-private bookkeeping (Undo snapshots, clock-before content, progress
//! merge state, sweep clocks) rides in an optional `private` member that is
//! loaded only on the authoritative side. It is never serialized when absent,
//! and every type with one has a `public()` form that drops it: that is the
//! form the replicated feed and query results carry.

use super::primitives::{
    BulkId, DecisionId, FormulationId, NavigatorRequestId, ProgressId, ProviderName, ReasonText,
    SessionId, TaskId, TextVersion, ThresholdDays, WallTime, Weekday, ZoneName,
};
use super::tasks::Task;
use super::vocabulary::{
    AiUse, BulkKind, ClearStart, CountBucket, DecisionType, OpenList, ParkSource, ReceiptKind,
    ReceiptSource, ReviewEntry, ReviewMode, ReviewOrigin, SessionStatus, SkipReason, StallReason,
    StepCode, StepStatus, UndoSkipReason,
};
use bb_protocol::wire::{Counter, Instant};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

// ------------------------------------------------------------------ park, clock

/// The park marker of a task moved Next to Someday by auto-park.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Park {
    pub at: Instant,
    pub formulation_id: FormulationId,
    /// Authoritative side only; never part of the public projection.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub private: Option<ParkPrivate>,
}

impl Park {
    pub fn public(&self) -> Self {
        Self {
            private: None,
            ..self.clone()
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ParkPrivate {
    pub from_revision: Counter,
    pub clock_before: ClockBefore,
}

/// A formulation clock as it stood before a park or bulk release moved it.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ClockBefore {
    pub formulation_id: Option<FormulationId>,
    pub started_at: Instant,
    pub extended_at: Option<Instant>,
    pub extension_reason: Option<ReasonText>,
    pub park_floor_at: Option<Instant>,
    pub stalled_before: u32,
}

// ---------------------------------------------------------------------- settings

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewSettings {
    pub threshold_days: ThresholdDays,
    pub review_weekday: Weekday,
    pub review_time: WallTime,
    pub time_zone: ZoneName,
    pub onboarded_at: Option<Instant>,
    pub activated_at: Option<Instant>,
    pub owner_park_floor_at: Option<Instant>,
    pub revision: Counter,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub private: Option<SettingsPrivate>,
}

impl ReviewSettings {
    pub fn public(&self) -> Self {
        Self {
            private: None,
            ..self.clone()
        }
    }
}

/// Server-private sweep bookkeeping.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SettingsPrivate {
    pub last_effective_sweep_at: Option<Instant>,
    pub threshold_changed_at: Option<Instant>,
}

// ----------------------------------------------------------------------- sessions

/// The ten summary counters, in the summary's fixed order.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionCounts {
    pub done: u32,
    pub reformulated: u32,
    pub first_step: u32,
    pub waiting: u32,
    pub someday: u32,
    pub cancelled: u32,
    pub extended: u32,
    pub inbox_processed: u32,
    pub kept: u32,
    pub moved_to_next: u32,
}

impl SessionCounts {
    pub fn get(&self, bucket: CountBucket) -> u32 {
        match bucket {
            CountBucket::Done => self.done,
            CountBucket::Reformulated => self.reformulated,
            CountBucket::FirstStep => self.first_step,
            CountBucket::Waiting => self.waiting,
            CountBucket::Someday => self.someday,
            CountBucket::Cancelled => self.cancelled,
            CountBucket::Extended => self.extended,
            CountBucket::InboxProcessed => self.inbox_processed,
            CountBucket::Kept => self.kept,
            CountBucket::MovedToNext => self.moved_to_next,
        }
    }
}

/// A Review session: exactly the public field list plus optional private state.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewSession {
    pub id: SessionId,
    pub mode: ReviewMode,
    pub entry: ReviewEntry,
    pub origin: ReviewOrigin,
    pub status: SessionStatus,
    pub started_at: Instant,
    pub last_activity_at: Instant,
    pub ended_at: Option<Instant>,
    pub current_step: Option<StepCode>,
    pub steps: BTreeMap<StepCode, StepStatus>,
    pub active_seconds_by_step: BTreeMap<StepCode, u32>,
    pub counts: SessionCounts,
    pub set_aside_count: u32,
    pub qualifying_activity: bool,
    pub clear_start: Option<ClearStart>,
    pub revision: Counter,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub private: Option<SessionPrivate>,
}

impl ReviewSession {
    pub fn public(&self) -> Self {
        Self {
            private: None,
            ..self.clone()
        }
    }
}

/// Progress-merge bookkeeping that stays out of the public projection:
/// applied progress IDs (with the digest of what each applied) and steps
/// finished with nothing to decide.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionPrivate {
    pub applied_progress: BTreeMap<ProgressId, String>,
    pub finished_empty: Vec<StepCode>,
}

/// `task_ids: None` is an uncaptured queue; `Some(vec![])` is captured-empty.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DecisionQueue {
    pub session_id: SessionId,
    pub task_ids: Option<Vec<TaskId>>,
    pub decided_task_ids: Vec<TaskId>,
    pub set_aside_task_ids: Vec<TaskId>,
}

// --------------------------------------------------------------------- decisions

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Decision {
    pub id: DecisionId,
    #[serde(rename = "type")]
    pub decision_type: DecisionType,
    pub task_id: TaskId,
    pub session_id: Option<SessionId>,
    pub decided_at: Instant,
    pub substantive: Option<bool>,
    pub stall_reason: Option<StallReason>,
    pub ai_use: AiUse,
    pub yielded_auto_park: bool,
    pub formulation_id: Option<FormulationId>,
    pub task_revision_before: Counter,
    pub task_revision_after: Counter,
    pub created_task_id: Option<TaskId>,
    pub navigator_request_id: Option<NavigatorRequestId>,
    pub review_counts_as: CountBucket,
    pub client_decided_at: Option<Instant>,
    pub reason_text: Option<ReasonText>,
    pub undo_available_until: Option<Instant>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub private: Option<DecisionUndo>,
}

impl Decision {
    pub fn public(&self) -> Self {
        Self {
            private: None,
            ..self.clone()
        }
    }
}

/// Server-only Undo snapshot, kept to its seven-day deadline.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DecisionUndo {
    pub task_before: Box<Task>,
    pub created_task_revision: Option<Counter>,
    pub receipt_kind: Option<ReceiptKind>,
}

/// A Keep or release receipt: one current receipt per task and kind.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewReceipt {
    pub task_id: TaskId,
    pub kind: ReceiptKind,
    pub hidden_until: Instant,
    pub task_revision: Counter,
    pub reviewed_at: Instant,
    pub source: ReceiptSource,
    pub decision_id: Option<DecisionId>,
    pub bulk_id: Option<BulkId>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ParkAck {
    pub task_id: TaskId,
    pub formulation_id: FormulationId,
    pub parked_at: Instant,
    pub seen_at: Option<Instant>,
    pub returned_at: Option<Instant>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub private: Option<ParkAckPrivate>,
}

impl ParkAck {
    pub fn public(&self) -> Self {
        Self {
            private: None,
            ..self.clone()
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ParkAckPrivate {
    pub from_revision: Counter,
    pub source: ParkSource,
}

// ------------------------------------------------------------------ bulk release

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BulkRelease {
    pub id: BulkId,
    pub kind: BulkKind,
    pub session_id: Option<SessionId>,
    pub created_at: Instant,
    pub undone_at: Option<Instant>,
    pub released: Vec<BulkReleased>,
    pub skipped: Vec<BulkSkipped>,
    pub undo: Option<BulkUndoResult>,
}

impl BulkRelease {
    pub fn public(&self) -> Self {
        Self {
            released: self.released.iter().map(BulkReleased::public).collect(),
            ..self.clone()
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BulkReleased {
    pub task_id: TaskId,
    pub revision_after: Counter,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub private: Option<ReleasedPrivate>,
}

impl BulkReleased {
    pub fn public(&self) -> Self {
        Self {
            private: None,
            ..self.clone()
        }
    }
}

/// The public face of a released item (also the bulk-release result).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReleasedItem {
    pub task_id: TaskId,
    pub revision_after: Counter,
}

/// Seven-day clock-before content kept for bulk Undo.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReleasedPrivate {
    pub previous_state: OpenList,
    pub clock_before: Option<ClockBefore>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BulkSkipped {
    pub task_id: TaskId,
    pub reason: SkipReason,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BulkUndoSkipped {
    pub task_id: TaskId,
    pub reason: UndoSkipReason,
}

/// The content-free result of undoing a bulk release.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BulkUndoResult {
    pub restored: Vec<TaskId>,
    pub skipped: Vec<BulkUndoSkipped>,
}

// ------------------------------------------------------------- navigator consent

/// A provider and its consent, or `None` before the first grant. Usage, cost
/// reservations, credentials and consent audit history are not task data.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NavigatorConsent {
    pub provider: ProviderName,
    pub consent: Option<ConsentGrant>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConsentGrant {
    pub granted_at: Instant,
    pub revoked_at: Option<Instant>,
    pub consent_text_version: TextVersion,
}
