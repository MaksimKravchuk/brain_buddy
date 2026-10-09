//! Native Review command payloads (command-catalog.md): the canonical
//! `backend/app/schemas/review.py` request fields with creation IDs supplied
//! up front, `expected_revision` moved into preconditions and numeric
//! revisions as decimal strings. Every payload rejects unknown fields.

use super::primitives::{
    FollowUpTaskId, FormulationId, Limited, NavigatorRequestId, NewDecisionId, NewFormulationId,
    ProgressId, ProviderName, ReasonText, SessionId, ShortText, TaskId, TextVersion, ThresholdDays,
    True, WallTime, Weekday, ZoneName,
};
use super::vocabulary::{
    AiUse, BulkKind, ClearStart, DecisionType, ReviewEntry, ReviewMode, ReviewOrigin, StallReason,
    StepCode, StepStatus,
};
use bb_protocol::wire::{Counter, Instant};
use serde::{Deserialize, Serialize};

/// A command with no payload fields (archive, unarchive, tag delete, Undo).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Empty {}

fn no_ai() -> AiUse {
    AiUse::None
}

/// `review.decide`: the decision ID is client-created, the task is the envelope's
/// `entity_id`, and the expected task revision is a precondition.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Decide {
    pub decision_id: NewDecisionId,
    #[serde(rename = "type")]
    pub decision_type: DecisionType,
    #[serde(default)]
    pub formulation_id: Option<FormulationId>,
    #[serde(default)]
    pub stall_reason: Option<StallReason>,
    #[serde(default)]
    pub title: Option<ShortText>,
    #[serde(default)]
    pub waiting_for: Option<ShortText>,
    #[serde(default)]
    pub reason: Option<ReasonText>,
    #[serde(default)]
    pub session_id: Option<SessionId>,
    #[serde(default = "no_ai")]
    pub ai_use: AiUse,
    #[serde(default)]
    pub navigator_request_id: Option<NavigatorRequestId>,
    #[serde(default)]
    pub client_decided_at: Option<Instant>,
    #[serde(default)]
    pub new_formulation_id: Option<NewFormulationId>,
    #[serde(default)]
    pub follow_up_task_id: Option<FollowUpTaskId>,
}

impl Decide {
    /// Fields the decision type requires and the request omitted (http §3):
    /// the type's own fields, then `formulation_id` for the types that decide
    /// on the task's current formulation.
    pub fn missing_fields(&self) -> Vec<&'static str> {
        use DecisionType as T;
        let mut missing = Vec::new();
        let required = match self.decision_type {
            T::Reformulate | T::FirstStep | T::FollowUp | T::ReturnToNext => {
                self.title.is_none().then_some("title")
            }
            T::Waiting => self.waiting_for.is_none().then_some("waiting_for"),
            T::Extend => self.reason.is_none().then_some("reason"),
            _ => None,
        };
        missing.extend(required);
        let names_formulation = matches!(
            self.decision_type,
            T::Reformulate | T::FirstStep | T::Waiting | T::Someday | T::Extend
        );
        if names_formulation && self.formulation_id.is_none() {
            missing.push("formulation_id");
        }
        missing
    }
}

/// `review.auto_park`: names the formulation; no generic revision precondition.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FormulationRef {
    pub formulation_id: FormulationId,
}

/// `review.explainer_ack`: the device zone, if known.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ExplainerAck {
    pub time_zone: Option<ZoneName>,
}

/// `review.settings`: only the named fields change; `onboarded` can only be
/// switched on. The IANA check is the rules' (`INVALID_TIME_ZONE`).
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct SettingsUpdate {
    pub threshold_days: Option<ThresholdDays>,
    pub review_weekday: Option<Weekday>,
    pub review_time: Option<WallTime>,
    pub time_zone: Option<ZoneName>,
    pub onboarded: Option<True>,
}

/// One park acknowledgement key.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ParkKey {
    pub task_id: TaskId,
    pub formulation_id: FormulationId,
}

/// `review.parks_ack`: at most 200 keys.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ParksAck {
    pub items: Limited<ParkKey, 200>,
}

/// `review.session_start`: the session ID is the envelope's `entity_id`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionStart {
    pub mode: ReviewMode,
    pub entry: ReviewEntry,
    pub origin: ReviewOrigin,
    #[serde(default)]
    pub skip_steps: Limited<StepCode, 10>,
    pub replace_open: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StepUpdate {
    pub code: StepCode,
    pub status: StepStatus,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ActiveSeconds {
    pub code: StepCode,
    pub seconds: u32,
}

/// `review.session_progress`: merged and replay-safe by `progress_id`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionProgress {
    pub progress_id: ProgressId,
    #[serde(default)]
    pub current_step: Option<StepCode>,
    #[serde(default)]
    pub step: Option<StepUpdate>,
    #[serde(default)]
    pub active_seconds: Option<ActiveSeconds>,
    #[serde(default)]
    pub set_aside_task_id: Option<TaskId>,
    #[serde(default)]
    pub inbox_processed_delta: Option<i32>,
    #[serde(default)]
    pub snapshot_decision_queue: Option<True>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct SessionFinish {
    pub clear_start: Option<ClearStart>,
}

/// A bulk item with its own expected revision; a stale item is skipped, not refused.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BulkItem {
    pub task_id: TaskId,
    pub expected_revision: Counter,
}

/// `review.bulk_release`: the bulk ID is the envelope's `entity_id`; at most 500 items.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BulkReleaseRequest {
    pub kind: BulkKind,
    #[serde(default)]
    pub session_id: Option<SessionId>,
    pub items: Limited<BulkItem, 500>,
}

/// `review.consent_grant`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConsentGrantRequest {
    pub provider: ProviderName,
    pub consent_text_version: TextVersion,
}

/// `review.consent_revoke`. Revoke is owner-wide: the Apple provider label
/// never narrows it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ConsentRevoke {
    pub provider: ProviderName,
}
