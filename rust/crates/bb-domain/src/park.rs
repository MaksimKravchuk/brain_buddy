//! Auto-park, the human yield, park acknowledgement and the park rows (spec 026
//! T014, ADR-0027).
//!
//! The pure decisions of `ReviewService.auto_park`, `_parked`,
//! `run_auto_park_sweep`, `_yields`, `acknowledge_parks` and
//! `_unseen_parks` (`backend/app/modules/tasks/review_service.py`), which are
//! normative, built on the clock functions of [`crate::formulation`]
//! (`auto_park`, `reverse_park`, `apply_sweep_gap`, `repair_clock`). Nothing
//! here repeats a clock rule, performs I/O or reads a clock: every `now`, every
//! identifier and every stored row is an input, and every result says what to
//! write.
//!
//! ADR-0027 precedence the functions keep:
//!
//! * A park is automatic bookkeeping of the server's own evaluation. It bumps
//!   the task revision once (the task did change list) and writes a park row;
//!   marking a park seen or returned never touches a task revision.
//! * A human decision made before the park (device time) and on the parked
//!   formulation yields it: the clock is restored exactly, with no revision
//!   bump, before the decision applies, whatever edits were replayed onto the
//!   parked task in between ([`yields`]).
//! * The clock before a park is server-private. A public projection of a park
//!   ([`public_marker`], [`ParkRow::to_ack`] then `public()`) carries neither
//!   it nor the revision the park was made from, so it can neither yield nor be
//!   restored ([`FormulationError::ParkSnapshotUnavailable`]).

use std::collections::BTreeSet;

use crate::calendar::{CalendarDay, UtcInstant};
use crate::formulation::{
    self, DecisionInput, FormulationClass, FormulationError, OwnerClockSettings, ParkMarker,
    TaskClock, decision_allows, parse_instant, wire_instant,
};
use crate::types::{
    DecisionType, FormulationId, ParkAck, ParkAckPrivate, ParkSource, ParksAck, TaskId, TaskState,
};

/// A gap of at least this long since the last effective sweep floors parks.
const SWEEP_GAP_MICROS: i64 = 24 * 3_600 * 1_000_000;

/// Tasks per owner-locked sweep batch.
pub const SWEEP_BATCH: usize = 50;

// ------------------------------------------------------------------- park rows

/// One `review_park_acks` row (data-model E6): a park and whether the person
/// saw it or returned the task. `from_revision` and `source` are server-private,
/// so a row read from a public projection has neither.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParkRow {
    pub task_id: String,
    pub formulation_id: String,
    pub parked_at: UtcInstant,
    pub seen_at: Option<UtcInstant>,
    pub returned_at: Option<UtcInstant>,
    pub from_revision: Option<u64>,
    pub source: Option<ParkSource>,
}

impl ParkRow {
    /// The rule's view of a stored row.
    ///
    /// # Errors
    ///
    /// [`FormulationError::InvalidField`] for an instant or revision the rule
    /// cannot read.
    pub fn from_ack(ack: &ParkAck) -> Result<Self, FormulationError> {
        let optional = |value: Option<&bb_protocol::wire::Instant>, field| {
            value
                .map(|instant| parse_instant(instant, field))
                .transpose()
        };
        let private = ack.private.as_ref();
        Ok(Self {
            task_id: ack.task_id.as_str().to_owned(),
            formulation_id: ack.formulation_id.as_str().to_owned(),
            parked_at: parse_instant(&ack.parked_at, "park_ack.parked_at")?,
            seen_at: optional(ack.seen_at.as_ref(), "park_ack.seen_at")?,
            returned_at: optional(ack.returned_at.as_ref(), "park_ack.returned_at")?,
            from_revision: private.and_then(|private| private.from_revision.to_u64()),
            source: private.map(|private| private.source),
        })
    }

    /// The stored row. The private member is written only when both private
    /// facts are known.
    ///
    /// # Errors
    ///
    /// [`FormulationError::InvalidField`] for a value the stored types refuse.
    pub fn to_ack(&self) -> Result<ParkAck, FormulationError> {
        let invalid = |field| move |_| FormulationError::InvalidField(field);
        let optional = |value: Option<UtcInstant>, field| {
            value
                .map(|instant| wire_instant(instant, field))
                .transpose()
        };
        let private = match (self.from_revision, self.source) {
            (Some(from_revision), Some(source)) => Some(ParkAckPrivate {
                from_revision: from_revision.into(),
                source,
            }),
            _ => None,
        };
        Ok(ParkAck {
            task_id: TaskId::parse(self.task_id.clone()).map_err(invalid("park_ack.task_id"))?,
            formulation_id: FormulationId::parse(self.formulation_id.clone())
                .map_err(invalid("park_ack.formulation_id"))?,
            parked_at: wire_instant(self.parked_at, "park_ack.parked_at")?,
            seen_at: optional(self.seen_at, "park_ack.seen_at")?,
            returned_at: optional(self.returned_at, "park_ack.returned_at")?,
            private,
        })
    }

    fn with_returned(&self, returned_at: Option<UtcInstant>) -> Self {
        Self {
            returned_at,
            ..self.clone()
        }
    }
}

/// The park marker of a public projection: no clock before it, no revision it
/// was made from (ADR-0027 content limits).
#[must_use]
pub fn public_marker(marker: &ParkMarker) -> ParkMarker {
    ParkMarker {
        from_revision: None,
        clock_before: None,
        ..marker.clone()
    }
}

// ---------------------------------------------------------------- sweep bookkeeping

/// The effective-sweep bookkeeping of one evaluation.
#[derive(Clone, Debug, PartialEq)]
pub struct SweepNote {
    /// The owner settings to store: the park floor is raised after a gap.
    pub settings: OwnerClockSettings,
    /// The new `last_effective_sweep_at`: always `now`.
    pub last_effective_sweep_at: UtcInstant,
    /// Whether there was a gap of 24 hours or more (or no earlier evaluation).
    pub gap: bool,
}

/// Records an effective exposure evaluation; a gap of 24 hours or more floors
/// every park for 7 days (SC-006). Bookkeeping, not a settings change: the
/// settings revision stays. The one rule of the sweep and of the device park.
#[must_use]
pub fn note_effective_sweep(
    settings: &OwnerClockSettings,
    last_effective_sweep_at: Option<UtcInstant>,
    now: UtcInstant,
) -> SweepNote {
    let gap = last_effective_sweep_at.is_none_or(|last| now.micros_since(last) >= SWEEP_GAP_MICROS);
    SweepNote {
        settings: if gap {
            formulation::apply_sweep_gap(settings, now)
        } else {
            settings.clone()
        },
        last_effective_sweep_at: now,
        gap,
    }
}

// --------------------------------------------------------------------- auto-park

/// An applied park: the task as it is written and the row to upsert.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Parked {
    /// Someday, the formulation closed, the marker set, revision + 1.
    pub clock: TaskClock,
    /// A fresh row: unseen and not returned, even for a formulation that was
    /// parked, yielded and parked again (E6).
    pub row: ParkRow,
    /// The revision the park was made from.
    pub from_revision: u64,
    /// `auto-park:<task>:<formulation>:<from_revision>`, the sweep's
    /// deterministic idempotency key.
    pub key: String,
}

/// Why a park attempt changed nothing. All of them are `applied: false`, which
/// is a success, never a conflict.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NotApplied {
    /// The weekly-review flag is not effective for the owner.
    NotExposed,
    /// The device named a formulation the task no longer holds.
    FormulationChanged,
    /// Not in Next, or the owner is not activated.
    NotParkable,
    /// The server's own evaluation is not `park_due`.
    NotDue,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AutoPark {
    Applied(Box<Parked>),
    NotApplied(NotApplied),
}

impl AutoPark {
    #[must_use]
    pub fn applied(&self) -> bool {
        matches!(self, Self::Applied(_))
    }
}

/// The deterministic key of a park of `formulation_id` made from `revision`.
#[must_use]
pub fn sweep_key(task_id: &str, formulation_id: &str, revision: u64) -> String {
    format!("auto-park:{task_id}:{formulation_id}:{revision}")
}

/// The park of a `park_due` Next task of an activated owner (`_parked`).
#[must_use]
pub fn attempt_park(
    task_id: &str,
    clock: &TaskClock,
    settings: &OwnerClockSettings,
    now: UtcInstant,
    source: ParkSource,
) -> AutoPark {
    if clock.state != Some(TaskState::Next) || settings.activated_at().is_none() {
        return AutoPark::NotApplied(NotApplied::NotParkable);
    }
    let Some(parked) = formulation::auto_park(clock, settings, now) else {
        return AutoPark::NotApplied(NotApplied::NotDue);
    };
    let Some(marker) = parked.parked.as_ref() else {
        return AutoPark::NotApplied(NotApplied::NotDue);
    };
    let row = ParkRow {
        task_id: task_id.to_owned(),
        formulation_id: marker.formulation_id.clone(),
        parked_at: now,
        seen_at: None,
        returned_at: None,
        from_revision: Some(clock.revision),
        source: Some(source),
    };
    let key = sweep_key(task_id, &marker.formulation_id, clock.revision);
    AutoPark::Applied(Box::new(Parked {
        clock: parked,
        row,
        from_revision: clock.revision,
        key,
    }))
}

/// A park a device observed (`POST /tasks/{id}/auto-park`).
#[derive(Clone, Copy, Debug)]
pub struct DeviceParkRequest<'a> {
    pub task_id: &'a str,
    /// The formulation the device saw as due.
    pub formulation_id: &'a str,
    /// Whether the weekly-review flag is effective for the owner.
    pub exposed: bool,
    /// `last_effective_sweep_at` of the owner's settings.
    pub last_effective_sweep_at: Option<UtcInstant>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct DevicePark {
    /// The owner settings after the sweep-gap bookkeeping, for the response.
    pub settings: OwnerClockSettings,
    /// The bookkeeping to store; `None` when the flag is off or the owner is
    /// not activated.
    pub sweep: Option<SweepNote>,
    pub outcome: AutoPark,
}

/// The server re-evaluates with its own clock and settings. For an exposed,
/// activated owner the sweep-gap bookkeeping runs first, so a device park never
/// skips the gap floor (SC-006); the park then parks iff the task is in Next on
/// the named formulation and classifies `park_due`.
#[must_use]
pub fn device_auto_park(
    clock: &TaskClock,
    settings: &OwnerClockSettings,
    request: &DeviceParkRequest<'_>,
    now: UtcInstant,
) -> DevicePark {
    let sweep = (request.exposed && settings.activated_at().is_some())
        .then(|| note_effective_sweep(settings, request.last_effective_sweep_at, now));
    let settings = sweep
        .as_ref()
        .map_or_else(|| settings.clone(), |note| note.settings.clone());
    let outcome = if !request.exposed {
        AutoPark::NotApplied(NotApplied::NotExposed)
    } else if clock.formulation_id.as_deref() != Some(request.formulation_id) {
        AutoPark::NotApplied(NotApplied::FormulationChanged)
    } else {
        attempt_park(request.task_id, clock, &settings, now, ParkSource::Device)
    };
    DevicePark {
        settings,
        sweep,
        outcome,
    }
}

// ------------------------------------------------------------------------ sweep

/// One owner's exposure evaluation: the bookkeeping to store and the Next tasks
/// to visit, in the order given.
#[derive(Clone, Debug, PartialEq)]
pub struct SweepPlan<Id> {
    pub note: SweepNote,
    /// Tasks without a running clock (to repair) and tasks that are `park_due`
    /// under the settings after the gap floor. Visit them in batches of
    /// [`SWEEP_BATCH`], re-reading each under the owner lock ([`sweep_task`]).
    pub due: Vec<Id>,
}

/// `None` unless the flag is effective and the owner is activated (the sweep
/// skips such an owner).
#[must_use]
pub fn plan_owner_sweep<Id: Clone>(
    exposed: bool,
    settings: &OwnerClockSettings,
    last_effective_sweep_at: Option<UtcInstant>,
    next_tasks: &[(Id, TaskClock)],
    now: UtcInstant,
) -> Option<SweepPlan<Id>> {
    if !exposed || settings.activated_at().is_none() {
        return None;
    }
    let note = note_effective_sweep(settings, last_effective_sweep_at, now);
    let due = next_tasks
        .iter()
        .filter(|(_, clock)| {
            clock.state == Some(TaskState::Next)
                && (clock.formulation_started_at.is_none()
                    || formulation::classify(clock, &note.settings, now)
                        == FormulationClass::ParkDue)
        })
        .map(|(id, _)| id.clone())
        .collect();
    Some(SweepPlan { note, due })
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SweepStep {
    /// Not in Next any more, or not due when re-read.
    Skipped,
    /// A Next task without a clock gets one with a 14-day floor; no revision
    /// bump (bookkeeping).
    Repaired(Box<TaskClock>),
    Parked(Box<Parked>),
}

/// One task re-read under the owner lock. The caller skips a task whose
/// [`Parked::key`] is already recorded.
#[must_use]
pub fn sweep_task(
    task_id: &str,
    clock: &TaskClock,
    settings: &OwnerClockSettings,
    now: UtcInstant,
    repair_formulation_id: &str,
) -> SweepStep {
    if clock.state != Some(TaskState::Next) {
        return SweepStep::Skipped;
    }
    if clock.formulation_started_at.is_none() {
        return SweepStep::Repaired(Box::new(formulation::repair_clock(
            clock,
            now,
            repair_formulation_id,
        )));
    }
    match attempt_park(task_id, clock, settings, now, ParkSource::Sweep) {
        AutoPark::Applied(parked) => SweepStep::Parked(parked),
        AutoPark::NotApplied(_) => SweepStep::Skipped,
    }
}

// -------------------------------------------------------------------- human yield

/// What the yield rule reads of a decision request.
#[derive(Clone, Copy, Debug)]
pub struct YieldQuery<'a> {
    pub decision: DecisionType,
    pub formulation_id: Option<&'a str>,
    pub expected_revision: u64,
    /// The device time of the decision.
    pub client_decided_at: Option<UtcInstant>,
}

/// The auto-park yield rule (http §3, research R9): a decision of a type that
/// Next allows, on the parked formulation, made before the park, whose
/// `expected_revision` lies between the park's `from_revision` and the current
/// revision. Plain edits replayed onto the parked task in between (revisions
/// above `from_revision`) do not defeat it, and a decision made after the park
/// does not yield. A park without its private revision cannot be judged and
/// does not yield.
#[must_use]
pub fn yields(clock: &TaskClock, query: &YieldQuery<'_>) -> bool {
    let (Some(marker), Some(decided)) = (clock.parked.as_ref(), query.client_decided_at) else {
        return false;
    };
    let Some(from_revision) = marker.from_revision else {
        return false;
    };
    clock.state == Some(TaskState::Someday)
        && decision_allows(query.decision, TaskState::Next)
        && query.formulation_id == Some(marker.formulation_id.as_str())
        && from_revision <= query.expected_revision
        && query.expected_revision <= clock.revision
        && decided < marker.at
}

/// The clock a yielded decision decides on: `clock_before` restored exactly,
/// back in Next, with no revision bump. `None` when the decision does not
/// yield.
///
/// # Errors
///
/// [`FormulationError::ParkSnapshotUnavailable`] for a park whose marker lost
/// its private clock (the server, which keeps it, decides).
pub fn yield_reversal(
    clock: &TaskClock,
    query: &YieldQuery<'_>,
) -> Result<Option<TaskClock>, FormulationError> {
    if yields(clock, query) {
        formulation::reverse_park(clock).map(Some)
    } else {
        Ok(None)
    }
}

/// A decision applied through a yield.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct YieldedDecision {
    /// The task after the decision: one revision above the parked task's.
    pub clock: TaskClock,
    /// The park row's `returned_at` goes back to null: the reversal is not a
    /// return (E6).
    pub reset_returned: bool,
}

/// The decision of a yielding request, applied to the restored clock; `None`
/// when the request does not yield and the ordinary path (`expected_revision`
/// check, then [`formulation::decide`]) applies.
///
/// # Errors
///
/// [`yield_reversal`]'s, then [`formulation::decide`]'s: the yield is not
/// retried as a stale conflict when the restored task refuses the decision.
pub fn decide_through_yield(
    clock: &TaskClock,
    query: &YieldQuery<'_>,
    settings: &OwnerClockSettings,
    now: UtcInstant,
    input: &DecisionInput<'_>,
) -> Result<Option<YieldedDecision>, FormulationError> {
    let Some(restored) = yield_reversal(clock, query)? else {
        return Ok(None);
    };
    let decided = formulation::decide(&restored, query.decision, settings, now, input)?;
    Ok(Some(YieldedDecision {
        clock: decided,
        reset_returned: true,
    }))
}

// ------------------------------------------------------------------ row transitions

/// A row's `returned_at` set to `returned_at`; `None` when no row exists (it is
/// never made up) or nothing changes (`_set_park_returned`).
#[must_use]
pub fn set_returned(row: Option<&ParkRow>, returned_at: Option<UtcInstant>) -> Option<ParkRow> {
    row.filter(|row| row.returned_at != returned_at)
        .map(|row| row.with_returned(returned_at))
}

/// What moving a parked task did to its row.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ParkReturn {
    /// Not a return: no marker, not parked in Someday, or not moved to Next.
    NotAReturn,
    /// A return whose row is missing: write nothing and warn with ids only.
    Unrecorded,
    /// The row to write with `returned_at = now`, in the move's transaction.
    Returned(ParkRow),
}

/// A parked task moved back to Next (`_note_park_return`). `row_of` looks the
/// row up by the marker's formulation id.
#[must_use]
pub fn note_park_return(
    before: &TaskClock,
    after_state: Option<TaskState>,
    row_of: impl FnOnce(&str) -> Option<ParkRow>,
    now: UtcInstant,
) -> ParkReturn {
    let Some(marker) = before.parked.as_ref() else {
        return ParkReturn::NotAReturn;
    };
    if before.state != Some(TaskState::Someday) || after_state != Some(TaskState::Next) {
        return ParkReturn::NotAReturn;
    }
    match row_of(&marker.formulation_id) {
        None => ParkReturn::Unrecorded,
        Some(row) => ParkReturn::Returned(row.with_returned(Some(now))),
    }
}

/// An Undo that puts a task back in its park (for example Undo of
/// `return_to_next`) makes its row read as it did while parked, not returned.
#[must_use]
pub fn restore_park_row(
    restored: &TaskClock,
    row_of: impl FnOnce(&str) -> Option<ParkRow>,
) -> Option<ParkRow> {
    let marker = restored.parked.as_ref()?;
    if restored.state != Some(TaskState::Someday) {
        return None;
    }
    set_returned(row_of(&marker.formulation_id).as_ref(), None)
}

// -------------------------------------------------------------------- acknowledgement

/// The recorded outcome of one `review.parks_ack`: the idempotency record body.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AckResult {
    pub seen_at: UtcInstant,
    /// The `(task_id, formulation_id)` rows this request moved from unseen to
    /// seen, each once, in request order. Unknown and foreign keys are ignored
    /// identically, so a key that marks nothing leaves no trace.
    pub marked: Vec<(String, String)>,
}

/// Idempotent by state: an acknowledged park stays acknowledged. No task
/// revision is touched. The request holds at most 200 keys by construction.
#[must_use]
pub fn acknowledge_parks(
    request: &ParksAck,
    row_of: impl Fn(&str, &str) -> Option<ParkRow>,
    now: UtcInstant,
) -> AckResult {
    let mut seen_keys = BTreeSet::new();
    let mut marked = Vec::new();
    for item in request.items.as_slice() {
        let key = (
            item.task_id.as_str().to_owned(),
            item.formulation_id.as_str().to_owned(),
        );
        if !seen_keys.insert(key.clone()) {
            continue;
        }
        if row_of(&key.0, &key.1).is_some_and(|row| row.seen_at.is_none()) {
            marked.push(key);
        }
    }
    AckResult {
        seen_at: now,
        marked,
    }
}

/// The rows to write for a recorded [`AckResult`], also the reconciler of a lost
/// write. Only a row still unseen and parked no later than `seen_at` is marked:
/// a repeat park written after the acknowledgement is a park the person has not
/// seen, so a replay leaves it.
#[must_use]
pub fn rows_marked_seen(
    result: &AckResult,
    row_of: impl Fn(&str, &str) -> Option<ParkRow>,
) -> Vec<ParkRow> {
    result
        .marked
        .iter()
        .filter_map(|(task_id, formulation_id)| row_of(task_id, formulation_id))
        .filter(|row| row.seen_at.is_none() && row.parked_at <= result.seen_at)
        .map(|row| ParkRow {
            seen_at: Some(result.seen_at),
            ..row
        })
        .collect()
}

// ------------------------------------------------------------------- "while away"

/// A park the person has not seen yet.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UnseenPark {
    pub task_id: String,
    pub formulation_id: String,
    pub parked_at: UtcInstant,
}

/// Tasks parked automatically and still in their park whose row is missing or
/// unseen, oldest park first (E6).
#[must_use]
pub fn unseen_parks<'a>(
    tasks: impl IntoIterator<Item = (&'a str, &'a TaskClock)>,
    row_of: impl Fn(&str, &str) -> Option<ParkRow>,
) -> Vec<UnseenPark> {
    let mut unseen: Vec<UnseenPark> = tasks
        .into_iter()
        .filter_map(|(task_id, clock)| {
            let marker = clock.parked.as_ref()?;
            if clock.state != Some(TaskState::Someday) {
                return None;
            }
            if row_of(task_id, &marker.formulation_id).is_some_and(|row| row.seen_at.is_some()) {
                return None;
            }
            Some(UnseenPark {
                task_id: task_id.to_owned(),
                formulation_id: marker.formulation_id.clone(),
                parked_at: marker.at,
            })
        })
        .collect();
    unseen.sort_by(|a, b| (a.parked_at, &a.task_id).cmp(&(b.parked_at, &b.task_id)));
    unseen
}

/// Where the "While you were away" screen could show.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WhileAwayContext {
    AppOpen,
    ReviewStart,
}

impl WhileAwayContext {
    #[must_use]
    pub fn from_wire(value: &str) -> Option<Self> {
        match value {
            "app_open" => Some(Self::AppOpen),
            "review_start" => Some(Self::ReviewStart),
            _ => None,
        }
    }
}

/// FR-015: always first in a review; at app open at most once a day.
#[must_use]
pub fn show_while_away(
    context: WhileAwayContext,
    has_unseen: bool,
    last_shown_day: Option<CalendarDay>,
    today: CalendarDay,
) -> bool {
    if !has_unseen {
        return false;
    }
    match context {
        WhileAwayContext::ReviewStart => true,
        WhileAwayContext::AppOpen => last_shown_day.is_none_or(|shown| today > shown),
    }
}
