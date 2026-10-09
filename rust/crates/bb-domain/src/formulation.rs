//! The formulation clock (spec 020, `contracts/formulation-clock.md`).
//!
//! The pure rule of `backend/app/modules/tasks/formulation.py`, which is
//! normative; the Swift `FormulationRule` and the web `formulation.ts` run the
//! same vector file. Everything here is a function of its arguments: no I/O, no
//! clock of its own (every `now` is an input), no storage types.
//!
//! * Every instant is a [`UtcInstant`]. "Days" are exact 86 400-second spans;
//!   only the start of a due day uses the owner's IANA zone, resolved as
//!   Python's `zoneinfo` with `fold=0` does ([`CalendarDay::start_instant`]).
//! * The transition functions return a new [`TaskClock`]. The ones that are a
//!   normal task write bump `revision`; the clock bookkeeping ones (activation
//!   clamp, repair, sweep-gap floor, time-zone floor, park reversal) never do
//!   (ADR-0027: automatic bookkeeping is not a human edit revision).
//! * [`TaskClock`] keeps the server's flat clock fields, so a floor on a Next
//!   task without a running clock behaves as it does on the server. The
//!   public [`Task`] cannot hold that combination; [`TaskClock::from_task`]
//!   and [`TaskClock::write_clock_fields`] are the only bridge.
//! * The stalled-count scalar [`TaskClock::consecutive_stalled_formulations`]
//!   survives the clock being closed, so it is a task field, not a clock one.

use bb_protocol::wire::Instant;

use crate::calendar::{CalendarDay, TimeZone, UtcInstant};
use crate::types::{
    ClockBefore as StoredClockBefore, DecisionType, FormulationClock, FormulationId, Park,
    ParkPrivate, ReasonText, ReviewSettings, Task, TaskState, TaskView,
};

pub use crate::normalization::{formulation_key, is_substantive};

/// The thresholds an owner may choose, in days.
pub const ALLOWED_THRESHOLD_DAYS: [u32; 4] = [7, 14, 21, 28];

const DAY: i64 = 86_400;
const PARK_AFTER_ASK: i64 = 7 * DAY;
const EXTENSION: i64 = 7 * DAY;
const MOVES_TOMORROW_WINDOW: i64 = DAY;
const DUE_DATE_FLOOR: i64 = 7 * DAY;
const THRESHOLD_CHANGE_FLOOR: i64 = 7 * DAY;
const SWEEP_GAP_FLOOR: i64 = 7 * DAY;
const ACTIVATION_GRACE: i64 = 14 * DAY;
const REPAIR_GRACE: i64 = 14 * DAY;
const RESTART_AGE: i64 = 28 * DAY;
/// A task asking with at least this many stalled formulations before the
/// current one is on its third stall (FR-005).
pub const STALLS_BEFORE_THIRD: u32 = 2;

// ----------------------------------------------------------------------- errors

/// Why a rule refuses or cannot run. The first three carry the HTTP
/// `detail.reason` of the server's `FormulationRuleError`; the others are the
/// server's `ValueError`s (a caller bug) and the conversion failures of the
/// bridge to the stored types.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FormulationError {
    DecisionNotAllowed,
    ExtensionAlreadyUsed,
    ExtensionNotDue,
    /// `unknown time zone`.
    UnknownTimeZone(String),
    /// A threshold other than 7, 14, 21 or 28 days.
    InvalidThreshold(u32),
    /// The input a decision or move needs and the caller did not pass.
    MissingInput(&'static str),
    /// A yield reversal on a task that is not parked.
    NotParked,
    /// A park marker with no stored clock to restore (a public projection).
    ParkSnapshotUnavailable,
    /// A stored field that is not a value the rule can read or write.
    InvalidField(&'static str),
}

impl FormulationError {
    /// The HTTP `detail.reason` of a refused decision, `None` for a caller bug.
    #[must_use]
    pub fn reason(&self) -> Option<&'static str> {
        match self {
            Self::DecisionNotAllowed => Some("decision_not_allowed"),
            Self::ExtensionAlreadyUsed => Some("extension_already_used"),
            Self::ExtensionNotDue => Some("extension_not_due"),
            _ => None,
        }
    }
}

impl std::fmt::Display for FormulationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::UnknownTimeZone(name) => write!(f, "unknown time zone {name:?}"),
            Self::InvalidThreshold(days) => {
                write!(f, "threshold must be one of 7, 14, 21, 28 days, not {days}")
            }
            Self::MissingInput(name) => write!(f, "this decision needs {name}"),
            Self::NotParked => f.write_str("the task is not parked"),
            Self::ParkSnapshotUnavailable => f.write_str("the park carries no clock to restore"),
            Self::InvalidField(name) => write!(f, "invalid stored field {name}"),
            refused => f.write_str(refused.reason().unwrap_or("refused")),
        }
    }
}

impl std::error::Error for FormulationError {}

// ---------------------------------------------------------------------- classes

/// §5 classes, with the wire spelling as `as_str`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum FormulationClass {
    None,
    Paused,
    ParkDue,
    MovesTomorrow,
    Asks,
    Ageing,
    Fresh,
}

impl FormulationClass {
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Paused => "paused",
            Self::ParkDue => "park_due",
            Self::MovesTomorrow => "moves_tomorrow",
            Self::Asks => "asks",
            Self::Ageing => "ageing",
            Self::Fresh => "fresh",
        }
    }

    /// The one "asks for a decision" aggregate of §5 (FR-004): asks, moves
    /// tomorrow, and a park that is due but not applied yet.
    #[must_use]
    pub fn asks_for_decision(self) -> bool {
        matches!(self, Self::Asks | Self::MovesTomorrow | Self::ParkDue)
    }
}

// --------------------------------------------------------------------- settings

/// The owner-level inputs of the rule (§2), a projection of `review_settings`.
#[derive(Clone, Debug, PartialEq)]
pub struct OwnerClockSettings {
    threshold_days: u32,
    time_zone: String,
    zone: TimeZone,
    owner_park_floor_at: Option<UtcInstant>,
    activated_at: Option<UtcInstant>,
}

impl OwnerClockSettings {
    /// # Errors
    ///
    /// [`FormulationError::InvalidThreshold`] or
    /// [`FormulationError::UnknownTimeZone`], as the server's `__post_init__`.
    pub fn new(
        threshold_days: u32,
        time_zone: &str,
        owner_park_floor_at: Option<UtcInstant>,
        activated_at: Option<UtcInstant>,
    ) -> Result<Self, FormulationError> {
        if !ALLOWED_THRESHOLD_DAYS.contains(&threshold_days) {
            return Err(FormulationError::InvalidThreshold(threshold_days));
        }
        Ok(Self {
            threshold_days,
            time_zone: time_zone.to_owned(),
            zone: zone(time_zone)?,
            owner_park_floor_at,
            activated_at,
        })
    }

    /// The settings the stored `review_settings` row carries.
    ///
    /// # Errors
    ///
    /// As [`OwnerClockSettings::new`], or an instant that is not valid.
    pub fn from_review_settings(settings: &ReviewSettings) -> Result<Self, FormulationError> {
        Self::new(
            u32::from(settings.threshold_days.get()),
            settings.time_zone.as_str(),
            optional_instant(settings.owner_park_floor_at.as_ref(), "owner_park_floor_at")?,
            optional_instant(settings.activated_at.as_ref(), "activated_at")?,
        )
    }

    #[must_use]
    pub fn threshold_days(&self) -> u32 {
        self.threshold_days
    }

    /// The IANA name as stored (`UTC` stays `UTC`).
    #[must_use]
    pub fn time_zone(&self) -> &str {
        &self.time_zone
    }

    #[must_use]
    pub fn owner_park_floor_at(&self) -> Option<UtcInstant> {
        self.owner_park_floor_at
    }

    /// While `None` the owner is not activated: every task is `none` and
    /// nothing parks.
    #[must_use]
    pub fn activated_at(&self) -> Option<UtcInstant> {
        self.activated_at
    }

    fn threshold_seconds(&self) -> i64 {
        i64::from(self.threshold_days) * DAY
    }
}

fn zone(name: &str) -> Result<TimeZone, FormulationError> {
    TimeZone::named(name).map_err(|_| FormulationError::UnknownTimeZone(name.to_owned()))
}

// ------------------------------------------------------------------------ clock

/// The clock immediately before an auto-park closed it (`parked.clock_before`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClockBefore {
    pub started_at: UtcInstant,
    pub extended_at: Option<UtcInstant>,
    pub extension_reason: Option<String>,
    pub park_floor_at: Option<UtcInstant>,
    pub stalled_before: u32,
}

/// `TaskDocument.parked`: written only by auto-park. `clock_before` and
/// `from_revision` are server-private, so a public projection has neither.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParkMarker {
    pub at: UtcInstant,
    pub formulation_id: String,
    pub from_revision: Option<u64>,
    pub clock_before: Option<ClockBefore>,
}

/// A Next task's clock as a bulk-release record stores it (data-model E7).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReleasedClock {
    pub formulation_id: String,
    pub started_at: UtcInstant,
    pub extended_at: Option<UtcInstant>,
    pub extension_reason: Option<String>,
    pub park_floor_at: Option<UtcInstant>,
    pub stalled_before: u32,
}

/// The fields of a task the rule reads and writes (§2 plus state and title).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TaskClock {
    pub state: Option<TaskState>,
    pub title: Option<String>,
    pub revision: u64,
    pub formulation_id: Option<String>,
    pub formulation_started_at: Option<UtcInstant>,
    pub formulation_extended_at: Option<UtcInstant>,
    pub formulation_extension_reason: Option<String>,
    pub formulation_park_floor_at: Option<UtcInstant>,
    pub consecutive_stalled_formulations: u32,
    pub due_date: Option<CalendarDay>,
    pub parked: Option<ParkMarker>,
}

/// §4 instants; `start` is the effective start (due day included).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct DerivedInstants {
    pub start: UtcInstant,
    pub ageing_at: UtcInstant,
    pub ask_at: UtcInstant,
    pub park_due_at: UtcInstant,
    pub tomorrow_at: UtcInstant,
    pub paused_until: Option<UtcInstant>,
}

// ------------------------------------------------------- §4 derived instants

/// The first instant of `due_date` in `time_zone`: local midnight, or the end
/// of a DST gap that swallows it.
#[must_use]
pub fn due_start(due_date: CalendarDay, zone: &TimeZone) -> UtcInstant {
    UtcInstant::from_unix_seconds_clamped(due_date.start_instant(zone))
}

/// §4 for a started clock in Next of an activated owner, else `None`.
///
/// `paused_until = due_start` if `due_start > formulation_started_at`, else
/// none; the class is `paused` iff it is set and `now < paused_until`.
#[must_use]
pub fn derive_instants(
    clock: &TaskClock,
    settings: &OwnerClockSettings,
) -> Option<DerivedInstants> {
    let started = clock.formulation_started_at?;
    settings.activated_at?;
    if clock.state != Some(TaskState::Next) {
        return None;
    }
    let mut start = started;
    let mut paused_until = None;
    if let Some(day) = clock.due_date {
        let due = due_start(day, &settings.zone);
        if due > start {
            start = due;
            paused_until = Some(due);
        }
    }
    let threshold = settings.threshold_seconds();
    let mut ask_at = start.plus_seconds(threshold);
    if let Some(extended) = clock.formulation_extended_at {
        ask_at = ask_at.max(extended).plus_seconds(EXTENSION);
    }
    let park_due_at = [
        Some(ask_at.plus_seconds(PARK_AFTER_ASK)),
        clock.formulation_park_floor_at,
        settings.owner_park_floor_at,
    ]
    .into_iter()
    .flatten()
    .max()
    .unwrap_or(ask_at);
    Some(DerivedInstants {
        start,
        ageing_at: start.plus_seconds(threshold / 2),
        ask_at,
        park_due_at,
        tomorrow_at: park_due_at.plus_seconds(-MOVES_TOMORROW_WINDOW),
        paused_until,
    })
}

// -------------------------------------------------------- §5 classification

/// §5 from the derived instants alone.
#[must_use]
pub fn classify_instants(instants: Option<&DerivedInstants>, now: UtcInstant) -> FormulationClass {
    let Some(instants) = instants else {
        return FormulationClass::None;
    };
    if instants.paused_until.is_some_and(|until| now < until) {
        FormulationClass::Paused
    } else if now >= instants.park_due_at {
        FormulationClass::ParkDue
    } else if now >= instants.tomorrow_at {
        FormulationClass::MovesTomorrow
    } else if now >= instants.ask_at {
        FormulationClass::Asks
    } else if now >= instants.ageing_at {
        FormulationClass::Ageing
    } else {
        FormulationClass::Fresh
    }
}

#[must_use]
pub fn classify(
    clock: &TaskClock,
    settings: &OwnerClockSettings,
    now: UtcInstant,
) -> FormulationClass {
    classify_instants(derive_instants(clock, settings).as_ref(), now)
}

/// FR-017: not paused and at least 28 days since the effective start.
#[must_use]
pub fn restart_eligible(clock: &TaskClock, settings: &OwnerClockSettings, now: UtcInstant) -> bool {
    let instants = derive_instants(clock, settings);
    match &instants {
        Some(derived) if classify_instants(instants.as_ref(), now) != FormulationClass::Paused => {
            now.micros_since(derived.start) >= RESTART_AGE * 1_000_000
        }
        _ => false,
    }
}

/// FR-005: asking with at least two stalled formulations before this one.
#[must_use]
pub fn third_stall(clock: &TaskClock, settings: &OwnerClockSettings, now: UtcInstant) -> bool {
    classify(clock, settings, now).asks_for_decision()
        && clock.consecutive_stalled_formulations >= STALLS_BEFORE_THIRD
}

/// Ids of the tasks that ask for a decision, earliest-asking first (§5):
/// ascending `ask_at`, then ascending `formulation_started_at`, then id.
#[must_use]
pub fn decision_queue<Id: Ord + Clone>(
    tasks: &[(Id, TaskClock)],
    settings: &OwnerClockSettings,
    now: UtcInstant,
) -> Vec<Id> {
    let mut asking: Vec<(UtcInstant, UtcInstant, Id)> = tasks
        .iter()
        .filter_map(|(id, clock)| {
            let instants = derive_instants(clock, settings)?;
            let started = clock.formulation_started_at?;
            classify_instants(Some(&instants), now)
                .asks_for_decision()
                .then(|| (instants.ask_at, started, id.clone()))
        })
        .collect();
    asking.sort();
    asking.into_iter().map(|(_, _, id)| id).collect()
}

// ------------------------------------------------------------ §3 transitions

/// A new formulation at `now`; extension, floor and park cleared.
#[must_use]
pub fn start_formulation(clock: &TaskClock, formulation_id: &str, now: UtcInstant) -> TaskClock {
    TaskClock {
        formulation_id: Some(formulation_id.to_owned()),
        formulation_started_at: Some(now),
        formulation_extended_at: None,
        formulation_extension_reason: None,
        formulation_park_floor_at: None,
        parked: None,
        ..clock.clone()
    }
}

/// Closes the current formulation with the FR-005 stalled-count rule.
///
/// It reached "asks for a decision" iff it was extended (only possible once it
/// asked) or `now >= ask_at`; then the count goes up by one, otherwise it
/// resets to 0. A clock that never started leaves the count alone.
#[must_use]
pub fn close_formulation(
    clock: &TaskClock,
    settings: &OwnerClockSettings,
    now: UtcInstant,
) -> TaskClock {
    let mut stalled = clock.consecutive_stalled_formulations;
    if clock.formulation_started_at.is_some() {
        let in_next = TaskClock {
            state: Some(TaskState::Next),
            ..clock.clone()
        };
        let reached = clock.formulation_extended_at.is_some()
            || derive_instants(&in_next, settings).is_some_and(|instants| now >= instants.ask_at);
        stalled = if reached {
            stalled.saturating_add(1)
        } else {
            0
        };
    }
    TaskClock {
        formulation_id: None,
        formulation_started_at: None,
        formulation_extended_at: None,
        formulation_extension_reason: None,
        formulation_park_floor_at: None,
        consecutive_stalled_formulations: stalled,
        ..clock.clone()
    }
}

fn bump(clock: TaskClock) -> TaskClock {
    TaskClock {
        revision: clock.revision.saturating_add(1),
        ..clock
    }
}

/// A task created in Next starts its first formulation (revision 1).
#[must_use]
pub fn create_in_next(title: &str, formulation_id: &str, now: UtcInstant) -> TaskClock {
    TaskClock {
        state: Some(TaskState::Next),
        title: Some(title.to_owned()),
        revision: 1,
        formulation_id: Some(formulation_id.to_owned()),
        formulation_started_at: Some(now),
        formulation_extended_at: None,
        formulation_extension_reason: None,
        formulation_park_floor_at: None,
        consecutive_stalled_formulations: 0,
        due_date: None,
        parked: None,
    }
}

/// Title edit: a substantive change in Next closes and restarts the clock.
#[must_use]
pub fn change_title(
    clock: &TaskClock,
    title: &str,
    settings: &OwnerClockSettings,
    now: UtcInstant,
    new_formulation_id: &str,
) -> TaskClock {
    let mut changed = clock.clone();
    if clock.state == Some(TaskState::Next)
        && is_substantive(clock.title.as_deref().unwrap_or(""), title)
    {
        changed = close_formulation(clock, settings, now);
        changed = start_formulation(&changed, new_formulation_id, now);
    }
    changed.title = Some(title.to_owned());
    bump(changed)
}

/// Due date set, moved or removed: in Next the task floor rises (FR-046).
#[must_use]
pub fn change_due_date(
    clock: &TaskClock,
    due_date: Option<CalendarDay>,
    now: UtcInstant,
) -> TaskClock {
    let mut changed = TaskClock {
        due_date,
        ..clock.clone()
    };
    if clock.state == Some(TaskState::Next) {
        changed = raise_task_floor(&changed, now.plus_seconds(DUE_DATE_FLOOR));
    }
    bump(changed)
}

/// Notes, tags, project, priority, subtasks, comments, waiting-for (FR-003).
#[must_use]
pub fn edit_without_clock(clock: &TaskClock) -> TaskClock {
    bump(clock.clone())
}

fn raise_task_floor(clock: &TaskClock, floor: UtcInstant) -> TaskClock {
    TaskClock {
        formulation_park_floor_at: Some(
            clock
                .formulation_park_floor_at
                .map_or(floor, |existing| existing.max(floor)),
        ),
        ..clock.clone()
    }
}

/// Moves between lists without bumping the revision.
fn relocate(
    clock: &TaskClock,
    to_state: TaskState,
    settings: &OwnerClockSettings,
    now: UtcInstant,
    new_formulation_id: Option<&str>,
) -> Result<TaskClock, FormulationError> {
    if clock.state == Some(to_state) {
        return Ok(clock.clone());
    }
    let mut changed = clock.clone();
    if clock.state == Some(TaskState::Next) {
        changed = close_formulation(&changed, settings, now);
    }
    if clock.state == Some(TaskState::Someday) {
        changed.parked = None;
    }
    if to_state == TaskState::Next {
        let id = new_formulation_id.ok_or(FormulationError::MissingInput("new_formulation_id"))?;
        changed = start_formulation(&changed, id, now);
    }
    changed.state = Some(to_state);
    Ok(changed)
}

/// A move, reopen, completion or cancellation (one task write).
///
/// # Errors
///
/// [`FormulationError::MissingInput`] when moving into Next without an id.
pub fn move_to(
    clock: &TaskClock,
    to_state: TaskState,
    settings: &OwnerClockSettings,
    now: UtcInstant,
    new_formulation_id: Option<&str>,
) -> Result<TaskClock, FormulationError> {
    relocate(clock, to_state, settings, now, new_formulation_id).map(bump)
}

/// The one-time "keep 7 more days" (FR-009), checked in a fixed order.
///
/// # Errors
///
/// The three refusals of `extend`, in the order the server checks them.
pub fn extend(
    clock: &TaskClock,
    reason: &str,
    settings: &OwnerClockSettings,
    now: UtcInstant,
) -> Result<TaskClock, FormulationError> {
    if clock.state != Some(TaskState::Next) {
        return Err(FormulationError::DecisionNotAllowed);
    }
    if clock.formulation_extended_at.is_some() {
        return Err(FormulationError::ExtensionAlreadyUsed);
    }
    if !classify(clock, settings, now).asks_for_decision() {
        return Err(FormulationError::ExtensionNotDue);
    }
    Ok(bump(TaskClock {
        formulation_extended_at: Some(now),
        formulation_extension_reason: Some(reason.to_owned()),
        ..clock.clone()
    }))
}

/// "Find a first step" always starts a new formulation (FR-008).
#[must_use]
pub fn first_step(
    clock: &TaskClock,
    title: &str,
    settings: &OwnerClockSettings,
    now: UtcInstant,
    new_formulation_id: &str,
) -> TaskClock {
    let closed = close_formulation(clock, settings, now);
    let started = start_formulation(&closed, new_formulation_id, now);
    bump(TaskClock {
        title: Some(title.to_owned()),
        ..started
    })
}

/// The fields of a decision the clock rule reads (http §3).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct DecisionInput<'a> {
    pub title: Option<&'a str>,
    pub reason: Option<&'a str>,
    pub new_formulation_id: Option<&'a str>,
}

fn decision_allows(decision: DecisionType, state: TaskState) -> bool {
    use DecisionType::{
        Cancel, Complete, Extend, FirstStep, FollowUp, KeepSomeday, KeepWaiting, Reformulate,
        ReturnToNext, Someday, Waiting,
    };
    use TaskState::{Inbox, Next, Someday as InSomeday, Waiting as InWaiting};
    match decision {
        Complete | Cancel => matches!(state, Inbox | Next | InWaiting | InSomeday),
        Reformulate | FirstStep | Waiting | Someday | Extend => state == Next,
        KeepWaiting | FollowUp => state == InWaiting,
        ReturnToNext => matches!(state, InWaiting | InSomeday),
        KeepSomeday => state == InSomeday,
    }
}

/// The clock effect of a decision of the http §3 type table.
///
/// `keep_waiting`, `keep_someday` and `follow_up` leave the decided task
/// unchanged (they write a receipt or create another task).
///
/// # Errors
///
/// [`FormulationError::DecisionNotAllowed`] when the task's list does not allow
/// the decision, the refusals of [`extend`], or
/// [`FormulationError::MissingInput`] for a title or formulation id the
/// decision needs.
pub fn decide(
    clock: &TaskClock,
    decision: DecisionType,
    settings: &OwnerClockSettings,
    now: UtcInstant,
    input: &DecisionInput<'_>,
) -> Result<TaskClock, FormulationError> {
    if !clock
        .state
        .is_some_and(|state| decision_allows(decision, state))
    {
        return Err(FormulationError::DecisionNotAllowed);
    }
    let required_id = || {
        input
            .new_formulation_id
            .ok_or(FormulationError::MissingInput("new_formulation_id"))
    };
    let required_title = || input.title.ok_or(FormulationError::MissingInput("title"));
    let target = match decision {
        DecisionType::Extend => {
            return extend(clock, input.reason.unwrap_or(""), settings, now);
        }
        DecisionType::Reformulate => {
            return Ok(change_title(
                clock,
                required_title()?,
                settings,
                now,
                required_id()?,
            ));
        }
        DecisionType::FirstStep => {
            return Ok(first_step(
                clock,
                required_title()?,
                settings,
                now,
                required_id()?,
            ));
        }
        DecisionType::Complete => TaskState::Completed,
        DecisionType::Cancel => TaskState::Cancelled,
        DecisionType::Waiting => TaskState::Waiting,
        DecisionType::Someday => TaskState::Someday,
        DecisionType::ReturnToNext => TaskState::Next,
        DecisionType::KeepWaiting | DecisionType::KeepSomeday | DecisionType::FollowUp => {
            return Ok(clock.clone());
        }
    };
    let mut moved = move_to(clock, target, settings, now, input.new_formulation_id)?;
    if decision == DecisionType::ReturnToNext
        && let Some(title) = input.title
    {
        moved.title = Some(title.to_owned());
    }
    Ok(moved)
}

/// Parks a task whose own evaluation is `park_due`; `None` if it is not due.
///
/// The clock is captured in `parked.clock_before` before it is closed, so a
/// yield reversal restores it without closing the formulation twice.
#[must_use]
pub fn auto_park(
    clock: &TaskClock,
    settings: &OwnerClockSettings,
    now: UtcInstant,
) -> Option<TaskClock> {
    if classify(clock, settings, now) != FormulationClass::ParkDue {
        return None;
    }
    let started = clock.formulation_started_at?;
    let formulation_id = clock.formulation_id.clone()?;
    let marker = ParkMarker {
        at: now,
        formulation_id,
        from_revision: Some(clock.revision),
        clock_before: Some(ClockBefore {
            started_at: started,
            extended_at: clock.formulation_extended_at,
            extension_reason: clock.formulation_extension_reason.clone(),
            park_floor_at: clock.formulation_park_floor_at,
            stalled_before: clock.consecutive_stalled_formulations,
        }),
    };
    let closed = close_formulation(clock, settings, now);
    Some(bump(TaskClock {
        state: Some(TaskState::Someday),
        parked: Some(marker),
        ..closed
    }))
}

/// Yield reversal: restores `clock_before` exactly (no revision bump). The
/// yielding decision is applied to the result and bumps the revision.
///
/// # Errors
///
/// [`FormulationError::NotParked`], or
/// [`FormulationError::ParkSnapshotUnavailable`] for a public park marker.
pub fn reverse_park(clock: &TaskClock) -> Result<TaskClock, FormulationError> {
    let marker = clock.parked.as_ref().ok_or(FormulationError::NotParked)?;
    let before = marker
        .clock_before
        .as_ref()
        .ok_or(FormulationError::ParkSnapshotUnavailable)?;
    Ok(TaskClock {
        state: Some(TaskState::Next),
        formulation_id: Some(marker.formulation_id.clone()),
        formulation_started_at: Some(before.started_at),
        formulation_extended_at: before.extended_at,
        formulation_extension_reason: before.extension_reason.clone(),
        formulation_park_floor_at: before.park_floor_at,
        consecutive_stalled_formulations: before.stalled_before,
        parked: None,
        ..clock.clone()
    })
}

/// A person's release to Someday (restart or Inbox-remainder bulk release).
///
/// Returns the released task and, for a Next task with a clock, the clock the
/// bulk-release record stores so its Undo restores it exactly.
#[must_use]
pub fn release(
    clock: &TaskClock,
    settings: &OwnerClockSettings,
    now: UtcInstant,
) -> (TaskClock, Option<ReleasedClock>) {
    let snapshot = match (&clock.formulation_id, clock.formulation_started_at) {
        (Some(id), Some(started)) if clock.state == Some(TaskState::Next) && !id.is_empty() => {
            Some(ReleasedClock {
                formulation_id: id.clone(),
                started_at: started,
                extended_at: clock.formulation_extended_at,
                extension_reason: clock.formulation_extension_reason.clone(),
                park_floor_at: clock.formulation_park_floor_at,
                stalled_before: clock.consecutive_stalled_formulations,
            })
        }
        _ => None,
    };
    // Moving to Someday needs no formulation id, so relocate cannot refuse.
    let mut released =
        relocate(clock, TaskState::Someday, settings, now, None).unwrap_or_else(|_| clock.clone());
    released.parked = None;
    (bump(released), snapshot)
}

/// Returns a released task to its list with its stored clock, exactly.
#[must_use]
pub fn undo_release(
    clock: &TaskClock,
    previous_state: TaskState,
    released: Option<&ReleasedClock>,
) -> TaskClock {
    let mut restored = TaskClock {
        state: Some(previous_state),
        parked: None,
        ..clock.clone()
    };
    if let Some(stored) = released {
        restored.formulation_id = Some(stored.formulation_id.clone());
        restored.formulation_started_at = Some(stored.started_at);
        restored.formulation_extended_at = stored.extended_at;
        restored.formulation_extension_reason = stored.extension_reason.clone();
        restored.formulation_park_floor_at = stored.park_floor_at;
        restored.consecutive_stalled_formulations = stored.stalled_before;
    }
    bump(restored)
}

/// Decision Undo: the snapshot at `revision + 1`, keeping the bookkeeping
/// written since the decision (FR-048, §3 "decision undo").
///
/// A task restored into Next keeps `max(snapshot floor, current floor)` (the
/// current one counts only while it is in Next), and a restored formulation
/// that started before `activated_at` gets the activation clamp.
#[must_use]
pub fn restore(
    clock: &TaskClock,
    snapshot: &TaskClock,
    settings: &OwnerClockSettings,
) -> TaskClock {
    let mut restored = TaskClock {
        revision: clock.revision.saturating_add(1),
        ..snapshot.clone()
    };
    if restored.state != Some(TaskState::Next) {
        return restored;
    }
    let current_floor = if clock.state == Some(TaskState::Next) {
        clock.formulation_park_floor_at
    } else {
        None
    };
    if let Some(floor) = [snapshot.formulation_park_floor_at, current_floor]
        .into_iter()
        .flatten()
        .max()
    {
        restored.formulation_park_floor_at = Some(floor);
    }
    if let (Some(activated_at), Some(started)) =
        (settings.activated_at, restored.formulation_started_at)
        && started < activated_at
    {
        let id = restored.formulation_id.clone().unwrap_or_default();
        restored = activate_clock(&restored, activated_at, &id);
    }
    restored
}

// ------------------------------------------------- clock bookkeeping (no bump)

/// The activation clamp for one task (FR-016); never bumps the revision.
#[must_use]
pub fn activate_clock(
    clock: &TaskClock,
    activated_at: UtcInstant,
    formulation_id: &str,
) -> TaskClock {
    if clock.state != Some(TaskState::Next) {
        return clock.clone();
    }
    let changed = match clock.formulation_started_at {
        None => start_formulation(clock, formulation_id, activated_at),
        Some(started) => TaskClock {
            formulation_started_at: Some(started.max(activated_at)),
            ..clock.clone()
        },
    };
    raise_task_floor(&changed, activated_at.plus_seconds(ACTIVATION_GRACE))
}

/// Starts a missing clock on a Next task (old-client save, rollback).
#[must_use]
pub fn repair_clock(clock: &TaskClock, now: UtcInstant, formulation_id: &str) -> TaskClock {
    if clock.state != Some(TaskState::Next) || clock.formulation_started_at.is_some() {
        return clock.clone();
    }
    TaskClock {
        formulation_park_floor_at: Some(now.plus_seconds(REPAIR_GRACE)),
        ..start_formulation(clock, formulation_id, now)
    }
}

/// Time-zone change: a due-dated Next task cannot park within 7 days.
#[must_use]
pub fn raise_due_floor(clock: &TaskClock, now: UtcInstant) -> TaskClock {
    if clock.state != Some(TaskState::Next) || clock.due_date.is_none() {
        return clock.clone();
    }
    raise_task_floor(clock, now.plus_seconds(DUE_DATE_FLOOR))
}

// ------------------------------------------------------------ owner settings

/// First acknowledgement wins; a later one returns `settings` unchanged.
///
/// # Errors
///
/// [`FormulationError::UnknownTimeZone`] for a `time_zone` that is not IANA.
pub fn activate_owner(
    settings: &OwnerClockSettings,
    at: UtcInstant,
    time_zone: Option<&str>,
) -> Result<OwnerClockSettings, FormulationError> {
    if settings.activated_at.is_some() {
        return Ok(settings.clone());
    }
    let name = time_zone.unwrap_or(&settings.time_zone);
    Ok(OwnerClockSettings {
        activated_at: Some(at),
        time_zone: name.to_owned(),
        zone: zone(name)?,
        ..settings.clone()
    })
}

fn raise_owner_floor(settings: &OwnerClockSettings, floor: UtcInstant) -> OwnerClockSettings {
    OwnerClockSettings {
        owner_park_floor_at: Some(
            settings
                .owner_park_floor_at
                .map_or(floor, |existing| existing.max(floor)),
        ),
        ..settings.clone()
    }
}

/// After a sweep gap of 24 h or more, no park within 7 days (SC-006).
#[must_use]
pub fn apply_sweep_gap(settings: &OwnerClockSettings, now: UtcInstant) -> OwnerClockSettings {
    raise_owner_floor(settings, now.plus_seconds(SWEEP_GAP_FLOOR))
}

/// FR-039: a real change floors every park for 7 days; equal is no change.
///
/// # Errors
///
/// [`FormulationError::InvalidThreshold`] unless `to` is 7, 14, 21 or 28.
pub fn change_threshold(
    settings: &OwnerClockSettings,
    to: u32,
    now: UtcInstant,
) -> Result<OwnerClockSettings, FormulationError> {
    if !ALLOWED_THRESHOLD_DAYS.contains(&to) {
        return Err(FormulationError::InvalidThreshold(to));
    }
    if to == settings.threshold_days {
        return Ok(settings.clone());
    }
    Ok(raise_owner_floor(
        &OwnerClockSettings {
            threshold_days: to,
            ..settings.clone()
        },
        now.plus_seconds(THRESHOLD_CHANGE_FLOOR),
    ))
}

/// A zone equal to the stored one is no change.
///
/// # Errors
///
/// [`FormulationError::UnknownTimeZone`], checked before the equality.
pub fn change_time_zone(
    settings: &OwnerClockSettings,
    to: &str,
) -> Result<OwnerClockSettings, FormulationError> {
    let resolved = zone(to)?;
    if to == settings.time_zone {
        return Ok(settings.clone());
    }
    Ok(OwnerClockSettings {
        time_zone: to.to_owned(),
        zone: resolved,
        ..settings.clone()
    })
}

// --------------------------------------------------- the stored-record bridge

fn parse_instant(value: &Instant, field: &'static str) -> Result<UtcInstant, FormulationError> {
    UtcInstant::parse_rfc3339(value.as_str()).map_err(|_| FormulationError::InvalidField(field))
}

fn optional_instant(
    value: Option<&Instant>,
    field: &'static str,
) -> Result<Option<UtcInstant>, FormulationError> {
    value
        .map(|instant| parse_instant(instant, field))
        .transpose()
}

fn wire_instant(value: UtcInstant, field: &'static str) -> Result<Instant, FormulationError> {
    Instant::parse(value.to_rfc3339()).map_err(|_| FormulationError::InvalidField(field))
}

fn optional_wire(
    value: Option<UtcInstant>,
    field: &'static str,
) -> Result<Option<Instant>, FormulationError> {
    value
        .map(|instant| wire_instant(instant, field))
        .transpose()
}

impl TaskClock {
    /// The rule's view of a stored task, instants normalized to UTC.
    ///
    /// # Errors
    ///
    /// [`FormulationError::InvalidField`] for a revision or instant the rule
    /// cannot read.
    pub fn from_task(task: &Task) -> Result<Self, FormulationError> {
        let revision = task
            .revision
            .to_u64()
            .ok_or(FormulationError::InvalidField("revision"))?;
        let due_date = task
            .due_date
            .as_ref()
            .map(|day| {
                CalendarDay::parse_iso(day.as_str())
                    .map_err(|_| FormulationError::InvalidField("due_date"))
            })
            .transpose()?;
        let mut clock = Self {
            state: Some(task.state),
            title: Some(task.title.as_str().to_owned()),
            revision,
            formulation_id: None,
            formulation_started_at: None,
            formulation_extended_at: None,
            formulation_extension_reason: None,
            formulation_park_floor_at: None,
            consecutive_stalled_formulations: task.consecutive_stalled_formulations,
            due_date,
            parked: task.parked.as_ref().map(park_marker).transpose()?,
        };
        if let Some(stored) = &task.formulation {
            clock.formulation_id = Some(stored.id.as_str().to_owned());
            clock.formulation_started_at =
                Some(parse_instant(&stored.started_at, "formulation.started_at")?);
            clock.formulation_extended_at =
                optional_instant(stored.extended_at.as_ref(), "formulation.extended_at")?;
            clock.formulation_extension_reason = stored
                .extension_reason
                .as_ref()
                .map(|reason| reason.as_str().to_owned());
            clock.formulation_park_floor_at =
                optional_instant(stored.park_floor_at.as_ref(), "formulation.park_floor_at")?;
        }
        Ok(clock)
    }

    /// Writes the clock fields of this clock to `task`, and nothing else: the
    /// task commands own state, title and revision (`clock_fields`). A floor
    /// with no running clock has no place in a [`Task`] and is not stored.
    ///
    /// # Errors
    ///
    /// [`FormulationError::InvalidField`] for a value the stored types refuse;
    /// `task` is left unchanged then.
    pub fn write_clock_fields(&self, task: &mut Task) -> Result<(), FormulationError> {
        let formulation = match (&self.formulation_id, self.formulation_started_at) {
            (Some(id), Some(started)) => Some(FormulationClock {
                id: FormulationId::parse(id.clone())
                    .map_err(|_| FormulationError::InvalidField("formulation.id"))?,
                started_at: wire_instant(started, "formulation.started_at")?,
                extended_at: optional_wire(
                    self.formulation_extended_at,
                    "formulation.extended_at",
                )?,
                extension_reason: self
                    .formulation_extension_reason
                    .as_deref()
                    .map(reason_text)
                    .transpose()?,
                park_floor_at: optional_wire(
                    self.formulation_park_floor_at,
                    "formulation.park_floor_at",
                )?,
            }),
            _ => None,
        };
        let parked = self.parked.as_ref().map(stored_park).transpose()?;
        task.formulation = formulation;
        task.consecutive_stalled_formulations = self.consecutive_stalled_formulations;
        task.parked = parked;
        Ok(())
    }
}

fn reason_text(value: &str) -> Result<ReasonText, FormulationError> {
    ReasonText::new(value).map_err(|_| FormulationError::InvalidField("extension_reason"))
}

fn park_marker(park: &Park) -> Result<ParkMarker, FormulationError> {
    let private = park.private.as_ref();
    let clock_before = private
        .map(|private| {
            let before = &private.clock_before;
            Ok::<_, FormulationError>(ClockBefore {
                started_at: parse_instant(&before.started_at, "parked.clock_before.started_at")?,
                extended_at: optional_instant(
                    before.extended_at.as_ref(),
                    "parked.clock_before.extended_at",
                )?,
                extension_reason: before
                    .extension_reason
                    .as_ref()
                    .map(|reason| reason.as_str().to_owned()),
                park_floor_at: optional_instant(
                    before.park_floor_at.as_ref(),
                    "parked.clock_before.park_floor_at",
                )?,
                stalled_before: before.stalled_before,
            })
        })
        .transpose()?;
    Ok(ParkMarker {
        at: parse_instant(&park.at, "parked.at")?,
        formulation_id: park.formulation_id.as_str().to_owned(),
        from_revision: private.and_then(|private| private.from_revision.to_u64()),
        clock_before,
    })
}

fn stored_park(marker: &ParkMarker) -> Result<Park, FormulationError> {
    let formulation_id = FormulationId::parse(marker.formulation_id.clone())
        .map_err(|_| FormulationError::InvalidField("parked.formulation_id"))?;
    let private = match (&marker.clock_before, marker.from_revision) {
        (Some(before), Some(from_revision)) => Some(ParkPrivate {
            from_revision: from_revision.into(),
            clock_before: StoredClockBefore {
                formulation_id: Some(formulation_id.clone()),
                started_at: wire_instant(before.started_at, "parked.clock_before.started_at")?,
                extended_at: optional_wire(before.extended_at, "parked.clock_before.extended_at")?,
                extension_reason: before
                    .extension_reason
                    .as_deref()
                    .map(reason_text)
                    .transpose()?,
                park_floor_at: optional_wire(
                    before.park_floor_at,
                    "parked.clock_before.park_floor_at",
                )?,
                stalled_before: before.stalled_before,
            },
        }),
        _ => None,
    };
    Ok(Park {
        at: wire_instant(marker.at, "parked.at")?,
        formulation_id,
        private,
    })
}

// ------------------------------------------------------- the evaluation view

/// The four advisory instants of `TaskView.formulation` (http §2), as the wire
/// spells them.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AdvisoryInstants {
    pub ageing_at: Instant,
    pub ask_at: Instant,
    pub park_due_at: Instant,
    pub paused_until: Option<Instant>,
}

/// The advisory instants of a stored task: `None` unless it is in Next with a
/// running clock of an activated owner (null instants otherwise, never zero).
///
/// # Errors
///
/// [`FormulationError::InvalidField`] for a stored value the rule cannot read.
pub fn advisory_instants(
    task: &Task,
    settings: &OwnerClockSettings,
) -> Result<Option<AdvisoryInstants>, FormulationError> {
    if task.state != TaskState::Next || task.formulation.is_none() {
        return Ok(None);
    }
    let Some(instants) = derive_instants(&TaskClock::from_task(task)?, settings) else {
        return Ok(None);
    };
    Ok(Some(AdvisoryInstants {
        ageing_at: wire_instant(instants.ageing_at, "ageing_at")?,
        ask_at: wire_instant(instants.ask_at, "ask_at")?,
        park_due_at: wire_instant(instants.park_due_at, "park_due_at")?,
        paused_until: optional_wire(instants.paused_until, "paused_until")?,
    }))
}

/// Fills the four advisory instants of `view` from `task` with the owner's
/// settings, leaving every stored fact untouched. No-op when the task has no
/// advisory instants.
///
/// # Errors
///
/// As [`advisory_instants`]; `view` is unchanged on error.
pub fn fill_advisory_instants(
    view: &mut TaskView,
    task: &Task,
    settings: &OwnerClockSettings,
) -> Result<(), FormulationError> {
    if let (Some(formulation), Some(advisory)) = (
        view.formulation.as_mut(),
        advisory_instants(task, settings)?,
    ) {
        formulation.ageing_at = Some(advisory.ageing_at);
        formulation.ask_at = Some(advisory.ask_at);
        formulation.park_due_at = Some(advisory.park_due_at);
        formulation.paused_until = advisory.paused_until;
    }
    Ok(())
}

/// §5 class of a stored task.
///
/// # Errors
///
/// [`FormulationError::InvalidField`] for a stored value the rule cannot read.
pub fn classify_task(
    task: &Task,
    settings: &OwnerClockSettings,
    now: UtcInstant,
) -> Result<FormulationClass, FormulationError> {
    Ok(classify(&TaskClock::from_task(task)?, settings, now))
}

/// The tasks that ask for a decision, earliest-asking first, by task id.
///
/// # Errors
///
/// [`FormulationError::InvalidField`] for a stored value the rule cannot read.
pub fn decision_queue_of_tasks<'a>(
    tasks: impl IntoIterator<Item = &'a Task>,
    settings: &OwnerClockSettings,
    now: UtcInstant,
) -> Result<Vec<String>, FormulationError> {
    let clocks = tasks
        .into_iter()
        .map(|task| Ok((task.id.as_str().to_owned(), TaskClock::from_task(task)?)))
        .collect::<Result<Vec<_>, FormulationError>>()?;
    Ok(decision_queue(&clocks, settings, now))
}
