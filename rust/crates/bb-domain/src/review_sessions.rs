//! Review sessions, settings, activation, Navigator consent and the Review
//! reads (spec 026 T016, PR-16): `decide` for the session and owner-setting
//! commands, `query` for `ReviewState` and `ReviewQueue`.
//!
//! The server is normative: `ReviewFlowService.start_session`,
//! `progress_session`, `_merged`, `finish_session`, `close_idle_sessions`,
//! `queue` and the queue builders (`backend/app/modules/tasks/review_flow.py`),
//! `ReviewService.update_settings`, `acknowledge_explainer`, `state`
//! (`review_service.py`), the pure rules of `review_rules.py` and
//! `NavigatorService.grant_consent` / `revoke_consent` (`navigator.py`). The
//! decision queue, classification and park functions are
//! [`crate::formulation`] and [`crate::park`]; nothing here repeats a clock
//! rule, reads a clock or performs I/O.
//!
//! | Command | Rule |
//! | --- | --- |
//! | `review.session_start` | the session ID is the envelope's `entity_id`; a known ID with the same mode and origin is an accepted no-op (the stored run answers, nothing is replaced), another mode or origin is `id_already_exists`; an open run without `replace_open` is `id_already_exists` naming the open run; otherwise every open run ends `partial`/`abandoned` and the new run starts at the effective instant on its first unskipped step |
//! | `review.session_progress` | merged, never revision-checked: a step outside the run's mode is refused first; a known `progress_id` with the same digest merges nothing, another digest is `id_already_exists`; an ended run ignores it; steps only move `pending` < `skipped` < `finished`, active seconds and the Inbox count add (the count floors at 0), a set-aside task must be one of the owner's open tasks, the decision queue is captured once (captured-empty stays captured) and qualifying activity never turns off |
//! | `review.session_finish` | an open run ends `completed` / `completed_empty` with the clear-start answer; an ended run is returned unchanged |
//! | `review.settings` | settings revision check; a value equal to the stored one is no change and a body that changes nothing keeps the revision; a threshold change floors every park for 7 days, a time-zone change floors due-dated Next tasks (no task revision moves), the first `onboarded` is recorded |
//! | `review.explainer_ack` | the first acknowledgement activates the owner (settings and every Next clock publish together); a later one changes nothing, its zone included |
//! | `review.consent_grant` | the configured provider and the current consent text; an already current grant is a no-op |
//! | `review.consent_revoke` | owner-wide: every stored grant is revoked whatever provider the payload names; never gated by availability |
//!
//! Server-private bookkeeping (`applied_progress`, the finished-empty steps,
//! the threshold-change instant, the sweep clock) rides in each record's
//! `private` member: it is read when the read set holds it and written when
//! `inputs.authoritative` or the record already carries it.
//!
//! Refusal mapping where the frozen [`Reason`] set has no member of the same
//! name: `open_session_exists` and `id_conflict` (the server's 409s) are
//! [`Reason::IdAlreadyExists`], told apart by `field` (`replace_open`,
//! `id`, `progress_id`) and naming the session in `entity`; an unknown
//! session is [`Reason::SessionNotFound`]; a step or active-seconds code the
//! run does not have is [`Reason::StepNotInReview`]; the Review reads are
//! [`Reason::ReviewUnavailable`] while the weekly-review flag is off (the
//! writes are not gated).

use std::collections::{BTreeMap, BTreeSet};

use bb_protocol::catalog::EntityType;
use bb_protocol::wire::{Counter, Instant};
use serde_json::{Map, Value, json};

use crate::calendar::{CalendarDay, TimeZone, UtcInstant};
use crate::formulation::{
    self, ACTIVATION_GRACE, FormulationClass, OwnerClockSettings, TaskClock, wire_instant,
};
use crate::park::{self, ParkRow};
use crate::queries::{self, clock_settings, instant, invalid, stored};
use crate::types::{
    ChangeOutcome, ChangeSet, Command, ConsentGrant, ConsentGrantRequest, ConsentRevoke,
    CountedStatus, DatesDay, DatesMeta, DecisionQueue, DecisionsMeta, DomainChange, DomainCommand,
    DomainError, DueDay, ExecutionInputs, ExplainerAck, FormulationId, LastCountedReview,
    NavigatorConsent, NoMeta, ProjectFilter, Query, QueryInputs, QueryResult, QueueMeta, QueueView,
    ReadSet, Reason, ReceiptKind, ReceiptSource, ReceiptView, Record, RestOfNextMeta, ResultRefs,
    ReviewMode, ReviewSession, ReviewSettings, ReviewStateCounts, ReviewStateView, SessionCounts,
    SessionFinish, SessionId, SessionPrivate, SessionProgress, SessionStart, SessionStatus,
    SettingsPrivate, SettingsUpdate, SomedayMeta, StepCode, StepStatus, Task, TaskId, TaskState,
    TaskView, ThresholdDays, WallTime, Weekday, WinsMeta, ZoneName,
};

// ------------------------------------------------------------------- constants

const DAY: i64 = 86_400;
const WEEK: i64 = 7 * DAY;
const MICROS: i64 = 1_000_000;

/// Completed this recently counts as a win (inclusive).
pub const WINS_WINDOW: i64 = 7 * DAY;
/// Weeks of history the capacity mirror needs, and averages over.
pub const CAPACITY_WEEKS: i64 = 4;
/// Waiting longer than this is due for a look (strictly).
pub const WAITING_AGE: i64 = 7 * DAY;
/// An auto-park this recent stays out of the Someday pass.
pub const RECENT_PARK: i64 = 30 * DAY;
/// Cards the Someday pass shows.
pub const SOMEDAY_SHOWN: usize = 7;
/// Restart mode after this long without a counted review (inclusive).
pub const RESTART_AFTER: i64 = 21 * DAY;
/// A run idle this long is closed by the sweep (inclusive).
pub const IDLE_CLOSE_AFTER: i64 = 7 * DAY;
/// A counted review this close before a weekly slot skips the slot.
pub const NOTIFICATION_SKIP: i64 = 6 * DAY;
/// The Dates step looks this many local days ahead, today included.
pub const DATES_WINDOW_DAYS: i64 = 14;

/// A quick review's steps (FR-028).
pub const QUICK_STEPS: [StepCode; 4] = [
    StepCode::Wins,
    StepCode::Inbox,
    StepCode::Decisions,
    StepCode::Summary,
];

/// A full review's ten steps (FR-028).
pub const FULL_STEPS: [StepCode; 10] = [
    StepCode::Wins,
    StepCode::MindSweep,
    StepCode::Inbox,
    StepCode::Decisions,
    StepCode::RestOfNext,
    StepCode::Waiting,
    StepCode::Projects,
    StepCode::Someday,
    StepCode::Dates,
    StepCode::Summary,
];

// ------------------------------------------------------------------ pure rules

/// The steps of a review mode, in order.
#[must_use]
pub fn review_steps(mode: ReviewMode) -> &'static [StepCode] {
    match mode {
        ReviewMode::Quick => &QUICK_STEPS,
        ReviewMode::Full => &FULL_STEPS,
    }
}

/// The task fields the Review queues read (`review_rules.ReviewTask`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReviewTask {
    pub id: String,
    pub state: TaskState,
    pub revision: u64,
    pub completed_at: Option<UtcInstant>,
    pub waiting_since: Option<UtcInstant>,
    pub updated_at: Option<UtcInstant>,
    pub parked_at: Option<UtcInstant>,
}

impl ReviewTask {
    /// # Errors
    ///
    /// [`Reason::InvalidValue`] for a stored instant or revision the rule
    /// cannot read.
    pub fn from_task(task: &Task) -> Result<Self, DomainError> {
        let optional =
            |value: Option<&Instant>, field| value.map(|value| instant(value, field)).transpose();
        Ok(Self {
            id: task.id.as_str().to_owned(),
            state: task.state,
            revision: queries::counter(&task.revision, "revision")?,
            completed_at: optional(task.completed_at.as_ref(), "completed_at")?,
            waiting_since: optional(task.waiting_since.as_ref(), "waiting_since")?,
            updated_at: Some(instant(&task.updated_at, "updated_at")?),
            parked_at: task
                .parked
                .as_ref()
                .map(|park| instant(&park.at, "parked.at"))
                .transpose()?,
        })
    }
}

/// A Keep or release receipt as the queues read it (`review_rules.Receipt`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Receipt {
    pub task_id: String,
    pub kind: ReceiptKind,
    pub task_revision: u64,
    pub reviewed_at: UtcInstant,
    pub hidden_until: UtcInstant,
    pub source: ReceiptSource,
}

impl Receipt {
    /// # Errors
    ///
    /// [`Reason::InvalidValue`] for a stored instant or revision the rule
    /// cannot read.
    pub fn from_row(row: &crate::types::ReviewReceipt) -> Result<Self, DomainError> {
        Ok(Self {
            task_id: row.task_id.as_str().to_owned(),
            kind: row.kind,
            task_revision: queries::counter(&row.task_revision, "task_revision")?,
            reviewed_at: instant(&row.reviewed_at, "reviewed_at")?,
            hidden_until: instant(&row.hidden_until, "hidden_until")?,
            source: row.source,
        })
    }

    /// Hidden while not expired and the task is unchanged since.
    #[must_use]
    pub fn hides(&self, task: &ReviewTask, now: UtcInstant) -> bool {
        now < self.hidden_until && task.revision == self.task_revision
    }
}

/// One step of a run as qualifying activity reads it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct StepProgress {
    pub status: StepStatus,
    pub finished_empty: bool,
}

/// A run as the regularity instant reads it (`review_rules.SessionSummary`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SessionSummary {
    pub status: SessionStatus,
    pub qualifying_activity: bool,
    pub last_activity_at: UtcInstant,
    pub ended_at: Option<UtcInstant>,
}

/// How a run ends.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SessionEnd {
    Finish,
    Replace,
    IdleClose,
}

/// FR-031: the Next count, and the 4-week pace once there are 4 full weeks of
/// history and a completion in them.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CapacityMirror {
    pub next_count: u32,
    pub weeks_of_history: u32,
    pub weekly_average_4w: Option<f64>,
    pub implied_weeks: Option<f64>,
}

/// The Someday pass: how many are eligible and the ones shown.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SomedayQueue {
    pub eligible_total: usize,
    pub shown: Vec<String>,
}

/// Tasks completed in the last 7 days (both ends included), most recent
/// first, then by ID.
#[must_use]
pub fn wins(tasks: &[ReviewTask], now: UtcInstant) -> Vec<String> {
    let since = now.plus_seconds(-WINS_WINDOW);
    let mut done: Vec<(UtcInstant, &str)> = tasks
        .iter()
        .filter(|task| task.state == TaskState::Completed)
        .filter_map(|task| {
            task.completed_at
                .filter(|at| since <= *at && *at <= now)
                .map(|at| (at, task.id.as_str()))
        })
        .collect();
    done.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.cmp(b.1)));
    done.into_iter().map(|(_, id)| id.to_owned()).collect()
}

/// FR-031: the pace needs 4 full weeks since the first completion and at
/// least one completion in the last 4 weeks; otherwise only the Next count.
#[must_use]
pub fn capacity_mirror(
    next_count: u32,
    completed_at: &[UtcInstant],
    now: UtcInstant,
) -> CapacityMirror {
    let weeks = completed_at.iter().min().map_or(0, |first| {
        now.micros_since(*first).div_euclid(WEEK * MICROS)
    });
    let window_start = now.plus_seconds(-CAPACITY_WEEKS * WEEK);
    let recent = completed_at
        .iter()
        .filter(|at| window_start <= **at && **at <= now)
        .count();
    let weeks_of_history = u32::try_from(weeks.max(0)).unwrap_or(u32::MAX);
    if weeks < CAPACITY_WEEKS || recent == 0 {
        return CapacityMirror {
            next_count,
            weeks_of_history,
            weekly_average_4w: None,
            implied_weeks: None,
        };
    }
    let average = f64::from(u32::try_from(recent).unwrap_or(u32::MAX)) / CAPACITY_WEEKS as f64;
    CapacityMirror {
        next_count,
        weeks_of_history,
        weekly_average_4w: Some(average),
        implied_weeks: Some(f64::from(next_count) / average),
    }
}

fn current_receipts(receipts: &[Receipt], kind: ReceiptKind) -> BTreeMap<&str, &Receipt> {
    receipts
        .iter()
        .filter(|receipt| receipt.kind == kind)
        .map(|receipt| (receipt.task_id.as_str(), receipt))
        .collect()
}

/// FR-032: Waiting more than 7 days (strictly), not hidden by a current
/// receipt, oldest first.
#[must_use]
pub fn waiting_queue(tasks: &[ReviewTask], receipts: &[Receipt], now: UtcInstant) -> Vec<String> {
    let by_task = current_receipts(receipts, ReceiptKind::Waiting);
    let mut due: Vec<(UtcInstant, &str)> = tasks
        .iter()
        .filter(|task| task.state == TaskState::Waiting)
        .filter_map(|task| {
            let since = task.waiting_since?;
            if now.micros_since(since) <= WAITING_AGE * MICROS {
                return None;
            }
            if by_task
                .get(task.id.as_str())
                .is_some_and(|receipt| receipt.hides(task, now))
            {
                return None;
            }
            Some((since, task.id.as_str()))
        })
        .collect();
    due.sort();
    due.into_iter().map(|(_, id)| id.to_owned()).collect()
}

/// FR-032: unhidden Someday tasks not auto-parked in the last 30 days. Never
/// reviewed first (oldest `updated_at`, then ID), then the oldest receipt
/// `reviewed_at`; at most `limit` shown.
#[must_use]
pub fn someday_queue(
    tasks: &[ReviewTask],
    receipts: &[Receipt],
    now: UtcInstant,
    limit: usize,
) -> SomedayQueue {
    let by_task = current_receipts(receipts, ReceiptKind::Someday);
    let mut never: Vec<(UtcInstant, &str)> = Vec::new();
    let mut reviewed: Vec<(UtcInstant, UtcInstant, &str)> = Vec::new();
    for task in tasks.iter().filter(|task| task.state == TaskState::Someday) {
        if task
            .parked_at
            .is_some_and(|parked| now.micros_since(parked) < RECENT_PARK * MICROS)
        {
            continue;
        }
        let updated = task.updated_at.unwrap_or(UtcInstant::EARLIEST);
        match by_task.get(task.id.as_str()) {
            None => never.push((updated, task.id.as_str())),
            Some(receipt) if !receipt.hides(task, now) => {
                reviewed.push((receipt.reviewed_at, updated, task.id.as_str()));
            }
            Some(_) => {}
        }
    }
    never.sort();
    reviewed.sort();
    let order: Vec<String> = never
        .into_iter()
        .map(|(_, id)| id)
        .chain(reviewed.into_iter().map(|(_, _, id)| id))
        .map(str::to_owned)
        .collect();
    SomedayQueue {
        eligible_total: order.len(),
        shown: order.into_iter().take(limit).collect(),
    }
}

/// FR-017: onboarded, and 21 days since the last counted review or onboarding.
#[must_use]
pub fn restart_mode(
    onboarded_at: Option<UtcInstant>,
    last_counted_review_at: Option<UtcInstant>,
    now: UtcInstant,
) -> bool {
    let Some(onboarded) = onboarded_at else {
        return false;
    };
    let anchor = last_counted_review_at.unwrap_or(onboarded);
    now.micros_since(anchor) >= RESTART_AFTER * MICROS
}

/// FR-029: Done is `completed` / `completed_empty`; replaced or idle-closed is
/// `partial` / `abandoned`.
#[must_use]
pub fn ended_status(end: SessionEnd, qualifying: bool) -> SessionStatus {
    match (end, qualifying) {
        (SessionEnd::Finish, true) => SessionStatus::Completed,
        (SessionEnd::Finish, false) => SessionStatus::CompletedEmpty,
        (SessionEnd::Replace | SessionEnd::IdleClose, true) => SessionStatus::Partial,
        (SessionEnd::Replace | SessionEnd::IdleClose, false) => SessionStatus::Abandoned,
    }
}

#[must_use]
pub fn idle_close_due(last_activity_at: UtcInstant, now: UtcInstant) -> bool {
    now.micros_since(last_activity_at) >= IDLE_CLOSE_AFTER * MICROS
}

/// At least one item decision, or a non-summary step finished (not skipped)
/// with nothing to decide (FR-029).
#[must_use]
pub fn qualifying_activity(item_decisions: u64, steps: &[(StepCode, StepProgress)]) -> bool {
    item_decisions > 0
        || steps.iter().any(|(code, step)| {
            *code != StepCode::Summary && step.status == StepStatus::Finished && step.finished_empty
        })
}

/// Counted reviews: completed, partial, and open once it qualifies.
#[must_use]
pub fn is_counted(status: SessionStatus, qualifying: bool) -> bool {
    matches!(status, SessionStatus::Completed | SessionStatus::Partial)
        || (status == SessionStatus::Open && qualifying)
}

/// The regularity instant: the latest completed `ended_at`, partial or
/// qualifying open `last_activity_at`.
#[must_use]
pub fn last_counted_review_at(sessions: &[SessionSummary]) -> Option<UtcInstant> {
    sessions
        .iter()
        .filter(|session| is_counted(session.status, session.qualifying_activity))
        .map(|session| match (session.status, session.ended_at) {
            (SessionStatus::Completed, Some(ended)) => ended,
            _ => session.last_activity_at,
        })
        .max()
}

fn slot(day: CalendarDay, hour_minute: (u8, u8), zone: &TimeZone) -> UtcInstant {
    let seconds = u32::from(hour_minute.0) * 3600 + u32::from(hour_minute.1) * 60;
    UtcInstant::from_unix_seconds_clamped(day.at_local_time(seconds, zone))
}

/// The first weekly slot strictly after `now` (ISO weekday, local wall time in
/// `zone`), skipping a slot with a counted review in the 6 days before it
/// (FR-036).
#[must_use]
pub fn next_review_at(
    review_weekday: u8,
    review_time: (u8, u8),
    zone: &TimeZone,
    now: UtcInstant,
    last_counted_review_at: Option<UtcInstant>,
) -> UtcInstant {
    let today = CalendarDay::of_instant(now.unix_seconds(), zone);
    // 1970-01-01 was a Thursday: ISO weekday 4.
    let today_iso = (today.day_number() + 3).rem_euclid(7) + 1;
    let days_ahead = (i64::from(review_weekday) - today_iso).rem_euclid(7);
    let mut day = today.add_days(days_ahead);
    let mut next = slot(day, review_time, zone);
    if next <= now {
        day = day.add_days(7);
        next = slot(day, review_time, zone);
    }
    if last_counted_review_at.is_some_and(|last| last >= next.plus_seconds(-NOTIFICATION_SKIP)) {
        next = slot(day.add_days(7), review_time, zone);
    }
    next
}

// ------------------------------------------------------------------ helpers

fn key_of(id: &str) -> Vec<String> {
    vec![id.to_owned()]
}

fn applied(changes: Vec<DomainChange>) -> ChangeSet {
    ChangeSet {
        outcome: ChangeOutcome::Applied,
        changes,
        result: ResultRefs::default(),
        effects: Vec::new(),
    }
}

fn upsert(record: Record) -> DomainChange {
    DomainChange::Upsert(record)
}

fn wire(value: UtcInstant, field: &'static str) -> Result<Instant, DomainError> {
    wire_instant(value, field).map_err(stored)
}

fn optional_wire(
    value: Option<UtcInstant>,
    field: &'static str,
) -> Result<Option<Instant>, DomainError> {
    value.map(|value| wire(value, field)).transpose()
}

fn next_counter(counter: &Counter, field: &str) -> Result<Counter, DomainError> {
    queries::counter(counter, field)?
        .checked_add(1)
        .map(Counter::from)
        .ok_or_else(|| invalid(field))
}

fn parse_zone(name: &str, field: &str) -> Result<TimeZone, DomainError> {
    TimeZone::named(name).map_err(|_| DomainError::field(Reason::InvalidTimeZone, field))
}

fn session_not_found(id: &SessionId) -> DomainError {
    DomainError::about(
        Reason::SessionNotFound,
        EntityType::ReviewSession,
        key_of(id.as_str()),
    )
}

/// The server's 409s (`id_conflict`, `open_session_exists`): the session the
/// refusal is about is the entity, the request field tells them apart.
fn conflict(field: &str, session: &SessionId) -> DomainError {
    DomainError {
        field: Some(field.to_owned()),
        ..DomainError::about(
            Reason::IdAlreadyExists,
            EntityType::ReviewSession,
            key_of(session.as_str()),
        )
    }
}

/// The settings row, or the server's defaults while none is stored
/// (`ReviewSettingsDocument`: 14 days, Friday 16:00, UTC, not activated).
fn settings_or_default(read_set: &ReadSet) -> Result<ReviewSettings, DomainError> {
    if let Some(settings) = &read_set.settings {
        return Ok(settings.clone());
    }
    Ok(ReviewSettings {
        threshold_days: ThresholdDays::new(14)?,
        review_weekday: Weekday::new(5)?,
        review_time: WallTime::parse("16:00")?,
        time_zone: ZoneName::new("UTC")?,
        onboarded_at: None,
        activated_at: None,
        owner_park_floor_at: None,
        revision: Counter::from(1),
        private: None,
    })
}

/// The settings' private member, created where the writer is authoritative.
fn settings_private(
    settings: &mut ReviewSettings,
    authoritative: bool,
) -> Option<&mut SettingsPrivate> {
    if settings.private.is_none() && authoritative {
        settings.private = Some(SettingsPrivate {
            last_effective_sweep_at: None,
            threshold_changed_at: None,
        });
    }
    settings.private.as_mut()
}

fn check_revision(
    command: &DomainCommand,
    entity_type: EntityType,
    current: &Counter,
) -> Result<(), DomainError> {
    let expected = command
        .preconditions
        .iter()
        .find(|check| check.entity_type == entity_type && check.entity_id == command.entity_id)
        .ok_or_else(|| DomainError::field(Reason::InvalidPayload, "preconditions"))?;
    if &expected.edit_revision == current {
        Ok(())
    } else {
        Err(DomainError::stale(
            entity_type,
            key_of(command.entity_id.as_str()),
            current.clone(),
        ))
    }
}

// --------------------------------------------------------------------- decide

/// Whether this family decides `command`.
#[must_use]
pub fn handles(command: &Command) -> bool {
    matches!(
        command,
        Command::ReviewSessionStart(_)
            | Command::ReviewSessionProgress(_)
            | Command::ReviewSessionFinish(_)
            | Command::ReviewSettings(_)
            | Command::ReviewExplainerAck(_)
            | Command::ReviewConsentGrant(_)
            | Command::ReviewConsentRevoke(_)
    )
}

/// Decides one session, settings, activation or consent command against the
/// protected read set.
///
/// A command of another family is refused as [`Reason::InvalidPayload`]
/// (`field = "type"`); the dispatcher asks [`handles`] first.
///
/// # Errors
///
/// See the module documentation for each command's refusals.
pub fn decide(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    let now = instant(&inputs.now, "now")?;
    match &command.command {
        Command::ReviewSessionStart(payload) => session_start(read_set, command, payload, inputs),
        Command::ReviewSessionProgress(payload) => {
            session_progress(read_set, command, payload, inputs, now)
        }
        Command::ReviewSessionFinish(payload) => session_finish(read_set, command, payload, now),
        Command::ReviewSettings(payload) => {
            settings_update(read_set, command, payload, inputs, now)
        }
        Command::ReviewExplainerAck(payload) => explainer_ack(read_set, payload, inputs, now),
        Command::ReviewConsentGrant(payload) => consent_grant(read_set, payload, inputs, now),
        Command::ReviewConsentRevoke(payload) => consent_revoke(read_set, payload, now),
        _ => Err(DomainError::field(Reason::InvalidPayload, "type")),
    }
}

// ------------------------------------------------------------------- sessions

fn existing_session<'a>(
    read_set: &'a ReadSet,
    command: &DomainCommand,
) -> Result<&'a ReviewSession, DomainError> {
    let id = SessionId::parse(command.entity_id.as_str())?;
    read_set
        .sessions
        .get(&id)
        .ok_or_else(|| session_not_found(&id))
}

/// A run ended by Done, replacement or the idle close: applied progress is
/// dropped, the revision moves once.
fn ended(
    session: &ReviewSession,
    end: SessionEnd,
    ended_at: UtcInstant,
) -> Result<ReviewSession, DomainError> {
    let mut run = session.clone();
    run.status = ended_status(end, session.qualifying_activity);
    run.ended_at = Some(wire(ended_at, "ended_at")?);
    if let Some(private) = run.private.as_mut() {
        private.applied_progress.clear();
    }
    run.revision = next_counter(&session.revision, "revision")?;
    Ok(run)
}

fn started_at_key(session: &ReviewSession) -> Result<(UtcInstant, String), DomainError> {
    Ok((
        instant(&session.started_at, "started_at")?,
        session.id.as_str().to_owned(),
    ))
}

/// The owner's open runs, oldest first (`list_open_review_sessions`).
fn open_runs(read_set: &ReadSet) -> Result<Vec<&ReviewSession>, DomainError> {
    let mut keyed = read_set
        .sessions
        .values()
        .filter(|session| session.status == SessionStatus::Open)
        .map(|session| Ok((started_at_key(session)?, session)))
        .collect::<Result<Vec<_>, DomainError>>()?;
    keyed.sort_by(|a, b| a.0.cmp(&b.0));
    Ok(keyed.into_iter().map(|(_, session)| session).collect())
}

fn session_start(
    read_set: &ReadSet,
    command: &DomainCommand,
    start: &SessionStart,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    let now = instant(&inputs.now, "now")?;
    let id = SessionId::parse(command.entity_id.as_str())?;
    if let Some(stored_run) = read_set.sessions.get(&id) {
        // The matching record: the same mode and origin answers the stored
        // run and replaces nothing; another pair is a reused ID.
        return if (stored_run.mode, stored_run.origin) == (start.mode, start.origin) {
            Ok(ChangeSet::no_op())
        } else {
            Err(conflict("id", &id))
        };
    }
    let id = SessionId::parse_new(id.into_string())?;
    let open = open_runs(read_set)?;
    if let Some(latest) = open.last()
        && !start.replace_open
    {
        return Err(conflict("replace_open", &latest.id));
    }
    let mut changes = Vec::with_capacity(open.len() + 1);
    for run in open {
        changes.push(upsert(Record::ReviewSession(ended(
            run,
            SessionEnd::Replace,
            now,
        )?)));
    }
    let skip: BTreeSet<StepCode> = start.skip_steps.as_slice().iter().copied().collect();
    let steps: BTreeMap<StepCode, StepStatus> = review_steps(start.mode)
        .iter()
        .map(|code| {
            let status = if skip.contains(code) {
                StepStatus::Skipped
            } else {
                StepStatus::Pending
            };
            (*code, status)
        })
        .collect();
    let started = wire(now, "now")?;
    let session = ReviewSession {
        id,
        mode: start.mode,
        entry: start.entry,
        origin: start.origin,
        status: SessionStatus::Open,
        started_at: started.clone(),
        last_activity_at: started,
        ended_at: None,
        current_step: review_steps(start.mode)
            .iter()
            .find(|code| !skip.contains(code))
            .copied(),
        steps,
        active_seconds_by_step: BTreeMap::new(),
        counts: SessionCounts::default(),
        set_aside_count: 0,
        qualifying_activity: false,
        clear_start: None,
        revision: Counter::from(1),
        private: inputs.authoritative.then(|| SessionPrivate {
            applied_progress: BTreeMap::new(),
            finished_empty: Vec::new(),
        }),
    };
    changes.push(upsert(Record::ReviewSession(session)));
    Ok(applied(changes))
}

/// The digest of what a progress change applies (`progress_digest`): SHA-256
/// of the canonical body without `progress_id`, so a replay is told from a
/// reused ID with another body. Equal to the server's, whichever side applied
/// the change first.
#[must_use]
pub fn progress_digest(progress: &SessionProgress) -> String {
    let mut body = Map::new();
    if let Some(step) = progress.current_step {
        body.insert("current_step".to_owned(), json!(step.as_str()));
    }
    if let Some(update) = &progress.step {
        body.insert(
            "step".to_owned(),
            json!({ "code": update.code.as_str(), "status": update.status.as_str() }),
        );
    }
    if let Some(active) = &progress.active_seconds {
        body.insert(
            "active_seconds".to_owned(),
            json!({ "code": active.code.as_str(), "seconds": active.seconds }),
        );
    }
    if let Some(task) = &progress.set_aside_task_id {
        body.insert("set_aside_task_id".to_owned(), json!(task.as_str()));
    }
    if let Some(delta) = progress.inbox_processed_delta {
        body.insert("inbox_processed_delta".to_owned(), json!(delta));
    }
    if progress.snapshot_decision_queue.is_some() {
        body.insert("snapshot_decision_queue".to_owned(), json!(true));
    }
    sha256_hex(queries::python_dumps(&Value::Object(body)).as_bytes())
}

fn require_run_steps(
    session: &ReviewSession,
    progress: &SessionProgress,
) -> Result<(), DomainError> {
    let outside = |field| DomainError {
        field: Some(field),
        ..DomainError::about(
            Reason::StepNotInReview,
            EntityType::ReviewSession,
            key_of(session.id.as_str()),
        )
    };
    if let Some(update) = &progress.step
        && !session.steps.contains_key(&update.code)
    {
        return Err(outside("step".to_owned()));
    }
    if let Some(active) = &progress.active_seconds
        && !session.steps.contains_key(&active.code)
    {
        return Err(outside("active_seconds".to_owned()));
    }
    Ok(())
}

fn rank(status: StepStatus) -> u8 {
    match status {
        StepStatus::Pending => 0,
        StepStatus::Skipped => 1,
        StepStatus::Finished => 2,
    }
}

fn session_progress(
    read_set: &ReadSet,
    command: &DomainCommand,
    progress: &SessionProgress,
    inputs: &ExecutionInputs,
    now: UtcInstant,
) -> Result<ChangeSet, DomainError> {
    let session = existing_session(read_set, command)?;
    require_run_steps(session, progress)?;
    let digest = progress_digest(progress);
    let known = session
        .private
        .as_ref()
        .and_then(|private| private.applied_progress.get(&progress.progress_id));
    match known {
        Some(applied_digest) if *applied_digest != digest => {
            return Err(conflict("progress_id", &session.id));
        }
        // Replay-safe at any age: the same body merges nothing.
        Some(_) => return Ok(ChangeSet::no_op()),
        None => {}
    }
    if session.status != SessionStatus::Open {
        // Progress on an ended run is accepted and ignored.
        return Ok(ChangeSet::no_op());
    }
    merged(read_set, session, progress, &digest, inputs, now)
}

/// `ReviewFlowService._merged`.
fn merged(
    read_set: &ReadSet,
    session: &ReviewSession,
    progress: &SessionProgress,
    digest: &str,
    inputs: &ExecutionInputs,
    now: UtcInstant,
) -> Result<ChangeSet, DomainError> {
    let snapshot = Snapshot::new(read_set, now)?;
    let mut next = session.clone();
    let mut finished_empty: BTreeSet<StepCode> = session
        .private
        .as_ref()
        .map(|private| private.finished_empty.iter().copied().collect())
        .unwrap_or_default();
    if let Some(step) = progress.current_step {
        next.current_step = Some(step);
    }
    if let Some(update) = &progress.step {
        let before = session
            .steps
            .get(&update.code)
            .copied()
            .unwrap_or(StepStatus::Pending);
        if !finished_empty.contains(&update.code)
            && update.status == StepStatus::Finished
            && snapshot.nothing_to_decide(update.code)?
        {
            finished_empty.insert(update.code);
        }
        let status = if rank(update.status) > rank(before) {
            update.status
        } else {
            before
        };
        next.steps.insert(update.code, status);
    }
    if let Some(active) = &progress.active_seconds {
        let seconds = next.active_seconds_by_step.entry(active.code).or_insert(0);
        *seconds = seconds.saturating_add(active.seconds);
    }
    let original = read_set.decision_queues.get(&session.id);
    let before_queue = original
        .cloned()
        .unwrap_or_else(|| fresh_queue(read_set, &session.id));
    let mut queue = before_queue.clone();
    if let Some(aside) = &progress.set_aside_task_id
        && !queue.set_aside_task_ids.contains(aside)
        && read_set
            .tasks
            .get(aside)
            .is_some_and(|task| task.state.is_open())
    {
        queue.set_aside_task_ids.push(aside.clone());
    }
    if let Some(delta) = progress.inbox_processed_delta {
        let processed = i64::from(next.counts.inbox_processed) + i64::from(delta);
        next.counts.inbox_processed = u32::try_from(processed.max(0)).unwrap_or(u32::MAX);
    }
    if progress.snapshot_decision_queue.is_some() && queue.task_ids.is_none() {
        queue.task_ids = Some(
            snapshot
                .asking_ids()?
                .iter()
                .map(|id| TaskId::parse(id.as_str()))
                .collect::<Result<_, _>>()?,
        );
    }
    next.set_aside_count = u32::try_from(queue.set_aside_task_ids.len()).unwrap_or(u32::MAX);
    let steps: Vec<(StepCode, StepProgress)> = next
        .steps
        .iter()
        .map(|(code, status)| {
            (
                *code,
                StepProgress {
                    status: *status,
                    finished_empty: finished_empty.contains(code),
                },
            )
        })
        .collect();
    next.qualifying_activity =
        session.qualifying_activity || qualifying_activity(item_decisions(&next.counts), &steps);
    let last_activity = instant(&session.last_activity_at, "last_activity_at")?;
    if now > last_activity {
        next.last_activity_at = wire(now, "now")?;
    }
    next.revision = next_counter(&session.revision, "revision")?;
    if inputs.authoritative || session.private.is_some() {
        let mut applied_progress = session
            .private
            .as_ref()
            .map(|private| private.applied_progress.clone())
            .unwrap_or_default();
        applied_progress.insert(progress.progress_id.clone(), digest.to_owned());
        next.private = Some(SessionPrivate {
            applied_progress,
            finished_empty: finished_empty.into_iter().collect(),
        });
    }
    let mut changes = vec![upsert(Record::ReviewSession(next))];
    if queue != before_queue {
        changes.push(upsert(Record::ReviewDecisionQueue(queue)));
    }
    Ok(applied(changes))
}

/// Every counter: an item decision, or the Inbox items processed.
fn item_decisions(counts: &SessionCounts) -> u64 {
    [
        counts.done,
        counts.reformulated,
        counts.first_step,
        counts.waiting,
        counts.someday,
        counts.cancelled,
        counts.extended,
        counts.inbox_processed,
        counts.kept,
        counts.moved_to_next,
    ]
    .iter()
    .map(|count| u64::from(*count))
    .sum()
}

/// The decision queue row of a run that has none yet: uncaptured, nothing set
/// aside, and the tasks the run's decisions name.
fn fresh_queue(read_set: &ReadSet, session: &SessionId) -> DecisionQueue {
    let mut decided: Vec<(&Instant, &crate::types::DecisionId, &TaskId)> = read_set
        .decisions
        .values()
        .filter(|decision| decision.session_id.as_ref() == Some(session))
        .map(|decision| (&decision.decided_at, &decision.id, &decision.task_id))
        .collect();
    decided.sort_by(|a, b| (a.0.as_str(), a.1).cmp(&(b.0.as_str(), b.1)));
    let mut seen = BTreeSet::new();
    DecisionQueue {
        session_id: session.clone(),
        task_ids: None,
        decided_task_ids: decided
            .into_iter()
            .filter(|(_, _, task)| seen.insert(*task))
            .map(|(_, _, task)| task.clone())
            .collect(),
        set_aside_task_ids: Vec::new(),
    }
}

fn session_finish(
    read_set: &ReadSet,
    command: &DomainCommand,
    finish: &SessionFinish,
    now: UtcInstant,
) -> Result<ChangeSet, DomainError> {
    let session = existing_session(read_set, command)?;
    if session.status != SessionStatus::Open {
        // Idempotent by state: an ended run is returned unchanged.
        return Ok(ChangeSet::no_op());
    }
    let mut run = ended(session, SessionEnd::Finish, now)?;
    run.clear_start = finish.clear_start;
    let last_activity = instant(&session.last_activity_at, "last_activity_at")?;
    if now > last_activity {
        run.last_activity_at = wire(now, "now")?;
    }
    Ok(applied(vec![upsert(Record::ReviewSession(run))]))
}

/// The runs idle for 7 days, closed as the sweep closes them
/// (`close_idle_sessions`): each ends 7 days after its last activity.
///
/// # Errors
///
/// [`Reason::InvalidValue`] for a stored instant the rule cannot read.
pub fn close_idle_sessions(
    read_set: &ReadSet,
    now: UtcInstant,
) -> Result<Vec<ReviewSession>, DomainError> {
    let mut closed = Vec::new();
    for run in open_runs(read_set)? {
        let last_activity = instant(&run.last_activity_at, "last_activity_at")?;
        if idle_close_due(last_activity, now) {
            closed.push(ended(
                run,
                SessionEnd::IdleClose,
                last_activity.plus_seconds(IDLE_CLOSE_AFTER),
            )?);
        }
    }
    Ok(closed)
}

// ------------------------------------------------------------ settings, activation

fn settings_update(
    read_set: &ReadSet,
    command: &DomainCommand,
    update: &SettingsUpdate,
    inputs: &ExecutionInputs,
    now: UtcInstant,
) -> Result<ChangeSet, DomainError> {
    let current = settings_or_default(read_set)?;
    check_revision(command, EntityType::ReviewSettings, &current.revision)?;
    if let Some(zone) = &update.time_zone {
        parse_zone(zone.as_str(), "time_zone")?;
    }
    let mut updated = current.clone();
    if let Some(days) = update.threshold_days
        && days != current.threshold_days
    {
        let clock = OwnerClockSettings::from_review_settings(&current).map_err(stored)?;
        let changed =
            formulation::change_threshold(&clock, u32::from(days.get()), now).map_err(stored)?;
        updated.threshold_days = days;
        updated.owner_park_floor_at =
            optional_wire(changed.owner_park_floor_at(), "owner_park_floor_at")?;
        let changed_at = wire(now, "now")?;
        if let Some(private) = settings_private(&mut updated, inputs.authoritative) {
            private.threshold_changed_at = Some(changed_at);
        }
    }
    if let Some(weekday) = update.review_weekday {
        updated.review_weekday = weekday;
    }
    if let Some(time) = &update.review_time {
        updated.review_time = time.clone();
    }
    if let Some(zone) = &update.time_zone {
        updated.time_zone = zone.clone();
    }
    if update.onboarded.is_some() && current.onboarded_at.is_none() {
        updated.onboarded_at = Some(wire(now, "now")?);
    }
    if updated == current {
        return Ok(ChangeSet::no_op());
    }
    updated.revision = next_counter(&current.revision, "revision")?;
    let zone_changed = updated.time_zone != current.time_zone;
    let mut changes = vec![upsert(Record::ReviewSettings(updated))];
    if zone_changed {
        // A zone change floors every due-dated Next task; clock bookkeeping,
        // so no task revision or `updated_at` moves.
        changes.extend(clock_changes(read_set, |clock| {
            Ok(formulation::raise_due_floor(clock, now))
        })?);
    }
    Ok(applied(changes))
}

/// The Next tasks whose clock `rule` changes, as task upserts in ID order.
fn clock_changes(
    read_set: &ReadSet,
    mut rule: impl FnMut(&TaskClock) -> Result<TaskClock, DomainError>,
) -> Result<Vec<DomainChange>, DomainError> {
    let mut changes = Vec::new();
    for task in read_set
        .tasks
        .values()
        .filter(|task| task.state == TaskState::Next)
    {
        let clock = TaskClock::from_task(task).map_err(stored)?;
        let changed = rule(&clock)?;
        if changed != clock {
            let mut written = task.clone();
            changed.write_clock_fields(&mut written).map_err(stored)?;
            if written != *task {
                changes.push(upsert(Record::Task(written)));
            }
        }
    }
    Ok(changes)
}

fn explainer_ack(
    read_set: &ReadSet,
    ack: &ExplainerAck,
    inputs: &ExecutionInputs,
    now: UtcInstant,
) -> Result<ChangeSet, DomainError> {
    if let Some(zone) = &ack.time_zone {
        parse_zone(zone.as_str(), "time_zone")?;
    }
    let current = settings_or_default(read_set)?;
    if current.activated_at.is_some() {
        // First wins: a later acknowledgement changes nothing, its zone included.
        return Ok(ChangeSet::no_op());
    }
    let at = wire(now, "now")?;
    let mut activated = current.clone();
    activated.activated_at = Some(at.clone());
    if let Some(zone) = &ack.time_zone {
        activated.time_zone = zone.clone();
    }
    activated.revision = next_counter(&current.revision, "revision")?;
    if let Some(private) = settings_private(&mut activated, inputs.authoritative) {
        private.last_effective_sweep_at = Some(at);
    }
    let mut changes = vec![upsert(Record::ReviewSettings(activated))];
    // The activation clamp of every Next task, in the same transaction. A task
    // without a clock starts one with the next allocated formulation ID.
    let mut ids = inputs.allocated_ids.iter();
    changes.extend(clock_changes(read_set, |clock| {
        let id = if clock.formulation_started_at.is_none() {
            let allocated = ids.next().ok_or_else(|| {
                DomainError::field(Reason::FormulationIdRequired, "allocated_ids")
            })?;
            FormulationId::parse(allocated.as_str())?.into_string()
        } else {
            String::new()
        };
        Ok(formulation::activate_clock(clock, now, &id))
    })?);
    Ok(applied(changes))
}

// ------------------------------------------------------------------- consent

fn consent_grant(
    read_set: &ReadSet,
    grant: &ConsentGrantRequest,
    inputs: &ExecutionInputs,
    now: UtcInstant,
) -> Result<ChangeSet, DomainError> {
    let provider = inputs
        .policy
        .navigator_provider
        .as_ref()
        .filter(|configured| **configured == grant.provider)
        .ok_or_else(|| DomainError::field(Reason::ProviderUnavailable, "provider"))?;
    if grant.consent_text_version.get() != inputs.policy.consent_text_version {
        return Err(DomainError::field(
            Reason::ConsentTextOutdated,
            "consent_text_version",
        ));
    }
    let current = read_set
        .consents
        .iter()
        .find(|consent| consent.provider == *provider)
        .and_then(|consent| consent.consent.as_ref())
        .is_some_and(|stored_grant| {
            stored_grant.revoked_at.is_none()
                && stored_grant.consent_text_version == grant.consent_text_version
        });
    if current {
        return Ok(ChangeSet::no_op());
    }
    Ok(applied(vec![upsert(Record::ReviewNavigatorConsent(
        NavigatorConsent {
            provider: provider.clone(),
            consent: Some(ConsentGrant {
                granted_at: wire(now, "now")?,
                revoked_at: None,
                consent_text_version: grant.consent_text_version,
            }),
        },
    ))]))
}

/// `NavigatorService.revoke_consent`: every stored grant is revoked, whatever
/// provider the payload names. Revoke is owner-wide (command-catalog.md): the
/// Apple provider label never narrows it, and it is not gated by the
/// feature, the provider or the consent text.
fn consent_revoke(
    read_set: &ReadSet,
    _revoke: &ConsentRevoke,
    now: UtcInstant,
) -> Result<ChangeSet, DomainError> {
    let revoked_at = wire(now, "now")?;
    let changes: Vec<DomainChange> = read_set
        .consents
        .iter()
        .filter_map(|consent| {
            let grant = consent.consent.as_ref()?;
            grant.revoked_at.is_none().then(|| {
                upsert(Record::ReviewNavigatorConsent(NavigatorConsent {
                    provider: consent.provider.clone(),
                    consent: Some(ConsentGrant {
                        revoked_at: Some(revoked_at.clone()),
                        ..grant.clone()
                    }),
                }))
            })
        })
        .collect();
    Ok(if changes.is_empty() {
        ChangeSet::no_op()
    } else {
        applied(changes)
    })
}

// ------------------------------------------------------------------- snapshot

/// One consistent read of the owner's tasks, receipts and settings at `now`
/// (`review_flow._Snapshot`).
struct Snapshot<'a> {
    read_set: &'a ReadSet,
    now: UtcInstant,
    settings: OwnerClockSettings,
    zone: TimeZone,
    receipts: Vec<Receipt>,
    review_tasks: Vec<ReviewTask>,
}

impl<'a> Snapshot<'a> {
    fn new(read_set: &'a ReadSet, now: UtcInstant) -> Result<Self, DomainError> {
        let settings = clock_settings(read_set)?;
        let zone = parse_zone(settings.time_zone(), "time_zone")?;
        Ok(Self {
            read_set,
            now,
            settings,
            zone,
            receipts: read_set
                .receipts
                .iter()
                .map(Receipt::from_row)
                .collect::<Result<_, _>>()?,
            review_tasks: read_set
                .tasks
                .values()
                .map(ReviewTask::from_task)
                .collect::<Result<_, _>>()?,
        })
    }

    /// The tasks in `state` in manual order (`order_key`, creation, ID).
    fn in_state(&self, state: TaskState) -> Result<Vec<&'a Task>, DomainError> {
        self.manual(|task| task.state == state)
    }

    fn manual(&self, keep: impl Fn(&Task) -> bool) -> Result<Vec<&'a Task>, DomainError> {
        let mut keyed = self
            .read_set
            .tasks
            .values()
            .filter(|task| keep(task))
            .map(|task| {
                Ok((
                    queries::sort_key(task, crate::types::TaskSort::Manual)?,
                    task,
                ))
            })
            .collect::<Result<Vec<_>, DomainError>>()?;
        keyed.sort_by(|a, b| a.0.cmp(&b.0));
        Ok(keyed.into_iter().map(|(_, task)| task).collect())
    }

    /// The tasks of `ids` in that order; an ID no longer held is left out.
    fn pick(&self, ids: &[String]) -> Vec<&'a Task> {
        ids.iter()
            .filter_map(|id| {
                self.read_set
                    .tasks
                    .values()
                    .find(|task| task.id.as_str() == id)
            })
            .collect()
    }

    /// The live `asks_for_decision` aggregate in clock order.
    fn asking_ids(&self) -> Result<Vec<String>, DomainError> {
        formulation::decision_queue_of_tasks(
            self.read_set
                .tasks
                .values()
                .filter(|task| task.state == TaskState::Next),
            &self.settings,
            self.now,
        )
        .map_err(stored)
    }

    /// Active projects without a Next task, each as its open tasks in order.
    fn stuck_projects(&self) -> Result<Vec<Vec<&'a Task>>, DomainError> {
        queries::projects(self.read_set, ProjectFilter::Active)
            .iter()
            .filter(|summary| summary.needs_next_action())
            .map(|summary| {
                let id = &summary.project.id;
                self.manual(|task| task.state.is_open() && task.project_id.as_ref() == Some(id))
            })
            .collect()
    }

    /// E3 / FR-029: finishing `step` now is qualifying activity. Steps that
    /// only show have nothing to decide; a deciding step only when its queue
    /// is empty; the summary never qualifies.
    fn nothing_to_decide(&self, step: StepCode) -> Result<bool, DomainError> {
        Ok(match step {
            StepCode::Summary => false,
            StepCode::Wins | StepCode::MindSweep | StepCode::RestOfNext | StepCode::Dates => true,
            StepCode::Inbox => self.in_state(TaskState::Inbox)?.is_empty(),
            StepCode::Decisions => self.asking_ids()?.is_empty(),
            StepCode::Waiting => {
                waiting_queue(&self.review_tasks, &self.receipts, self.now).is_empty()
            }
            StepCode::Someday => {
                someday_queue(&self.review_tasks, &self.receipts, self.now, SOMEDAY_SHOWN)
                    .eligible_total
                    == 0
            }
            StepCode::Projects => self.stuck_projects()?.is_empty(),
        })
    }

    fn view(&self, task: &Task) -> Result<TaskView, DomainError> {
        queries::task_view(task, Vec::new(), Vec::new(), &self.settings)
    }

    fn views(&self, tasks: &[&Task]) -> Result<Vec<TaskView>, DomainError> {
        tasks.iter().map(|task| self.view(task)).collect()
    }
}

// -------------------------------------------------------------------- queries

/// Whether this family answers `query`.
#[must_use]
pub fn handles_query(query: &Query) -> bool {
    matches!(query, Query::ReviewState {} | Query::ReviewQueue { .. })
}

/// Answers `ReviewState` and `ReviewQueue`. Both are reads of the weekly
/// review and are [`Reason::ReviewUnavailable`] while its flag is off.
///
/// # Errors
///
/// [`Reason::ReviewUnavailable`], [`Reason::SessionNotFound`] for a queue of
/// an unknown run, [`Reason::InvalidTimeZone`] for a stored zone the rules
/// cannot read, [`Reason::InvalidValue`] for another stored value they cannot
/// read; any other query is [`Reason::InvalidValue`] on `kind`.
pub fn query(
    read_set: &ReadSet,
    query: &Query,
    inputs: &QueryInputs,
) -> Result<QueryResult, DomainError> {
    if !handles_query(query) {
        return Err(DomainError::field(Reason::InvalidValue, "kind"));
    }
    if !inputs.policy.weekly_review {
        return Err(DomainError::new(Reason::ReviewUnavailable));
    }
    let now = instant(&inputs.now, "now")?;
    match query {
        Query::ReviewQueue { step, session_id } => {
            review_queue(read_set, *step, session_id.as_ref(), now).map(QueryResult::ReviewQueue)
        }
        _ => review_state(read_set, now).map(|state| QueryResult::ReviewState(Box::new(state))),
    }
}

fn summary_of(session: &ReviewSession) -> Result<SessionSummary, DomainError> {
    Ok(SessionSummary {
        status: session.status,
        qualifying_activity: session.qualifying_activity,
        last_activity_at: instant(&session.last_activity_at, "last_activity_at")?,
        ended_at: session
            .ended_at
            .as_ref()
            .map(|ended| instant(ended, "ended_at"))
            .transpose()?,
    })
}

/// `_last_counted_review`: the most recent completed or partial run.
fn last_counted_session(read_set: &ReadSet) -> Result<Option<&ReviewSession>, DomainError> {
    let mut best: Option<((UtcInstant, &str), &ReviewSession)> = None;
    for session in read_set.sessions.values().filter(|session| {
        matches!(
            session.status,
            SessionStatus::Completed | SessionStatus::Partial
        )
    }) {
        let summary = summary_of(session)?;
        let counted = match (session.status, summary.ended_at) {
            (SessionStatus::Completed, Some(ended)) => ended,
            _ => summary.last_activity_at,
        };
        let key = (counted, session.id.as_str());
        if best.as_ref().is_none_or(|(held, _)| key > *held) {
            best = Some((key, session));
        }
    }
    Ok(best.map(|(_, session)| session))
}

fn review_state(read_set: &ReadSet, now: UtcInstant) -> Result<ReviewStateView, DomainError> {
    let settings = settings_or_default(read_set)?;
    let clock = OwnerClockSettings::from_review_settings(&settings).map_err(stored)?;
    let zone = parse_zone(settings.time_zone.as_str(), "time_zone")?;

    let (mut asks, mut moves_tomorrow) = (0u32, 0u32);
    for task in read_set.tasks.values() {
        let class = formulation::classify_task(task, &clock, now).map_err(stored)?;
        asks += u32::from(class.asks_for_decision());
        moves_tomorrow += u32::from(class == FormulationClass::MovesTomorrow);
    }

    let summaries = read_set
        .sessions
        .values()
        .map(summary_of)
        .collect::<Result<Vec<_>, _>>()?;
    let last_counted_at = last_counted_review_at(&summaries);

    let last_counted_review = last_counted_session(read_set)?.map(|session| LastCountedReview {
        session_id: session.id.clone(),
        status: if session.status == SessionStatus::Completed {
            CountedStatus::Completed
        } else {
            CountedStatus::Partial
        },
        origin: session.origin,
        ended_at: session.ended_at.clone(),
        counts: session.counts,
        clear_start: session.clear_start,
    });

    let mut open = None;
    for session in read_set
        .sessions
        .values()
        .filter(|session| session.status == SessionStatus::Open)
    {
        let key = started_at_key(session)?;
        if open
            .as_ref()
            .is_none_or(|(held, _): &((UtcInstant, String), &ReviewSession)| key > *held)
        {
            open = Some((key, session));
        }
    }

    let onboarded_at = settings
        .onboarded_at
        .as_ref()
        .map(|at| instant(at, "onboarded_at"))
        .transpose()?;
    let activated_at = clock.activated_at();
    let (hour, minute) = settings.review_time.hour_minute();

    Ok(ReviewStateView {
        explainer_seen: activated_at.is_some(),
        grace_until: optional_wire(
            activated_at.map(|at| at.plus_seconds(ACTIVATION_GRACE)),
            "grace_until",
        )?,
        last_counted_review_at: optional_wire(last_counted_at, "last_counted_review_at")?,
        last_counted_review,
        next_review_at: wire(
            next_review_at(
                settings.review_weekday.get(),
                (hour, minute),
                &zone,
                now,
                last_counted_at,
            ),
            "next_review_at",
        )?,
        restart_mode: restart_mode(onboarded_at, last_counted_at, now),
        open_session: open.map(|(_, session)| session.public()),
        unseen_parks: unseen_parks(read_set)?,
        counts: ReviewStateCounts {
            asks_for_decision: asks,
            moves_tomorrow,
        },
        receipts: visible_receipts(read_set, now)?,
        server_now: wire(now, "server_now")?,
        settings: settings.public(),
    })
}

/// Tasks parked automatically whose park the person has not seen (E6).
fn unseen_parks(read_set: &ReadSet) -> Result<Vec<crate::types::UnseenPark>, DomainError> {
    let mut rows: BTreeMap<(String, String), ParkRow> = BTreeMap::new();
    for ack in &read_set.park_acks {
        let row = ParkRow::from_ack(ack).map_err(stored)?;
        rows.insert((row.task_id.clone(), row.formulation_id.clone()), row);
    }
    let clocks = read_set
        .tasks
        .values()
        .filter(|task| task.parked.is_some())
        .map(|task| {
            Ok((
                task.id.as_str(),
                TaskClock::from_task(task).map_err(stored)?,
            ))
        })
        .collect::<Result<Vec<_>, DomainError>>()?;
    park::unseen_parks(
        clocks.iter().map(|(id, clock)| (*id, clock)),
        |task_id, formulation_id| {
            rows.get(&(task_id.to_owned(), formulation_id.to_owned()))
                .cloned()
        },
    )
    .into_iter()
    .map(|unseen| {
        Ok(crate::types::UnseenPark {
            task_id: TaskId::parse(unseen.task_id)?,
            formulation_id: FormulationId::parse(unseen.formulation_id)?,
            parked_at: wire(unseen.parked_at, "parked_at")?,
        })
    })
    .collect()
}

/// Receipts that still hide their task: not expired, and the task unchanged
/// since (data-model E5), by `(task_id, kind)`.
fn visible_receipts(read_set: &ReadSet, now: UtcInstant) -> Result<Vec<ReceiptView>, DomainError> {
    let mut keyed = read_set
        .receipts
        .iter()
        .map(|receipt| (receipt.task_id.as_str(), receipt.kind.as_str(), receipt))
        .collect::<Vec<_>>();
    keyed.sort_by(|a, b| (a.0, a.1).cmp(&(b.0, b.1)));
    let mut visible = Vec::new();
    for (_, _, receipt) in keyed {
        let unchanged = read_set
            .tasks
            .get(&receipt.task_id)
            .is_some_and(|task| task.revision == receipt.task_revision);
        if unchanged && now < instant(&receipt.hidden_until, "hidden_until")? {
            visible.push(ReceiptView {
                task_id: receipt.task_id.clone(),
                kind: receipt.kind,
                hidden_until: receipt.hidden_until.clone(),
                task_revision: receipt.task_revision.clone(),
            });
        }
    }
    Ok(visible)
}

fn review_queue(
    read_set: &ReadSet,
    step: StepCode,
    session_id: Option<&SessionId>,
    now: UtcInstant,
) -> Result<QueueView, DomainError> {
    let session = session_id
        .map(|id| {
            read_set
                .sessions
                .get(id)
                .ok_or_else(|| session_not_found(id))
        })
        .transpose()?;
    let snapshot = Snapshot::new(read_set, now)?;
    let no_meta = || QueueMeta::Empty(NoMeta {});
    let (tasks, meta): (Vec<&Task>, QueueMeta) = match step {
        StepCode::MindSweep | StepCode::Summary => (Vec::new(), no_meta()),
        StepCode::Wins => {
            let ids = wins(&snapshot.review_tasks, now);
            let count = u32::try_from(ids.len()).unwrap_or(u32::MAX);
            (snapshot.pick(&ids), QueueMeta::Wins(WinsMeta { count }))
        }
        StepCode::Inbox => (snapshot.in_state(TaskState::Inbox)?, no_meta()),
        StepCode::Decisions => {
            let ids = decision_ids(&snapshot, session)?;
            let tasks = snapshot.pick(&ids);
            let meta = handled_decisions(read_set, session, &tasks);
            (tasks, QueueMeta::Decisions(meta))
        }
        StepCode::RestOfNext => rest_of_next(&snapshot, session)?,
        StepCode::Waiting => {
            let ids = waiting_queue(&snapshot.review_tasks, &snapshot.receipts, now);
            (snapshot.pick(&ids), no_meta())
        }
        StepCode::Projects => (
            snapshot.stuck_projects()?.into_iter().flatten().collect(),
            no_meta(),
        ),
        StepCode::Someday => {
            let pass = someday_queue(
                &snapshot.review_tasks,
                &snapshot.receipts,
                now,
                SOMEDAY_SHOWN,
            );
            let meta = SomedayMeta {
                eligible_total: u32::try_from(pass.eligible_total).unwrap_or(u32::MAX),
                shown: u32::try_from(pass.shown.len()).unwrap_or(u32::MAX),
            };
            (snapshot.pick(&pass.shown), QueueMeta::Someday(meta))
        }
        StepCode::Dates => dates(&snapshot)?,
    };
    Ok(QueueView {
        items: snapshot.views(&tasks)?,
        meta,
    })
}

/// The run's snapshot once taken, else the live aggregate (http §6).
fn decision_ids(
    snapshot: &Snapshot<'_>,
    session: Option<&ReviewSession>,
) -> Result<Vec<String>, DomainError> {
    let captured = session
        .and_then(|session| snapshot.read_set.decision_queues.get(&session.id))
        .and_then(|queue| queue.task_ids.as_ref());
    match captured {
        Some(ids) => Ok(ids.iter().map(|id| id.as_str().to_owned()).collect()),
        None => snapshot.asking_ids(),
    }
}

/// Which cards of the run are handled already, and how (http §6): decided
/// (a decision of this run exists, an Undo having deleted it) and "Not now"
/// (unless decided after), both in queue order and only for tasks it lists.
fn handled_decisions(
    read_set: &ReadSet,
    session: Option<&ReviewSession>,
    queue: &[&Task],
) -> DecisionsMeta {
    let Some(session) = session else {
        return DecisionsMeta {
            decided_task_ids: Vec::new(),
            set_aside_task_ids: Vec::new(),
        };
    };
    let decided: BTreeSet<&TaskId> = read_set
        .decisions
        .values()
        .filter(|decision| decision.session_id.as_ref() == Some(&session.id))
        .map(|decision| &decision.task_id)
        .collect();
    let aside: BTreeSet<&TaskId> = read_set
        .decision_queues
        .get(&session.id)
        .map(|queue| queue.set_aside_task_ids.iter().collect())
        .unwrap_or_default();
    DecisionsMeta {
        decided_task_ids: queue
            .iter()
            .filter(|task| decided.contains(&task.id))
            .map(|task| task.id.clone())
            .collect(),
        set_aside_task_ids: queue
            .iter()
            .filter(|task| aside.contains(&task.id) && !decided.contains(&task.id))
            .map(|task| task.id.clone())
            .collect(),
    }
}

/// FR-031: Next beyond the decisions, with the capacity mirror.
fn rest_of_next<'a>(
    snapshot: &Snapshot<'a>,
    session: Option<&ReviewSession>,
) -> Result<(Vec<&'a Task>, QueueMeta), DomainError> {
    let next_tasks = snapshot.in_state(TaskState::Next)?;
    let asking: BTreeSet<String> = decision_ids(snapshot, session)?.into_iter().collect();
    let completed = snapshot
        .review_tasks
        .iter()
        .filter_map(|task| task.completed_at)
        .collect::<Vec<_>>();
    let mirror = capacity_mirror(
        u32::try_from(next_tasks.len()).unwrap_or(u32::MAX),
        &completed,
        snapshot.now,
    );
    let items = next_tasks
        .into_iter()
        .filter(|task| !asking.contains(task.id.as_str()))
        .collect();
    Ok((
        items,
        QueueMeta::RestOfNext(RestOfNextMeta {
            next_count: mirror.next_count,
            weekly_average_4w: mirror.weekly_average_4w,
            weeks_of_history: mirror.weeks_of_history,
            implied_weeks: mirror.implied_weeks,
        }),
    ))
}

/// Open tasks due from today to today + 13 in the stored zone, by day, and
/// within a day in `(order_key, id)` order.
fn dates<'a>(snapshot: &Snapshot<'a>) -> Result<(Vec<&'a Task>, QueueMeta), DomainError> {
    let today = CalendarDay::of_instant(snapshot.now.unix_seconds(), &snapshot.zone);
    let last = today.add_days(DATES_WINDOW_DAYS - 1);
    let mut by_day: BTreeMap<CalendarDay, Vec<(u64, &'a Task)>> = BTreeMap::new();
    for task in snapshot.read_set.tasks.values() {
        let Some(due) = task.due_date.as_ref() else {
            continue;
        };
        let due = CalendarDay::parse_iso(due.as_str()).map_err(|_| invalid("due_date"))?;
        if task.state.is_open() && today <= due && due <= last {
            by_day
                .entry(due)
                .or_default()
                .push((queries::counter(&task.order_key, "order_key")?, task));
        }
    }
    let mut days = Vec::new();
    let mut items = Vec::new();
    for (day, mut tasks) in by_day {
        tasks.sort_by(|a, b| (a.0, &a.1.id).cmp(&(b.0, &b.1.id)));
        days.push(DatesDay {
            day: DueDay::parse(day.iso_string())?,
            task_ids: tasks.iter().map(|(_, task)| task.id.clone()).collect(),
        });
        items.extend(tasks.into_iter().map(|(_, task)| task));
    }
    Ok((items, QueueMeta::Dates(DatesMeta { days })))
}

// ------------------------------------------------------------------- SHA-256

/// FIPS 180-4 SHA-256 as lowercase hex: the progress digest the server stores
/// (`hashlib.sha256(...).hexdigest()`), so a replay is recognised whichever
/// side applied the change.
fn sha256_hex(data: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a_2f98,
        0x7137_4491,
        0xb5c0_fbcf,
        0xe9b5_dba5,
        0x3956_c25b,
        0x59f1_11f1,
        0x923f_82a4,
        0xab1c_5ed5,
        0xd807_aa98,
        0x1283_5b01,
        0x2431_85be,
        0x550c_7dc3,
        0x72be_5d74,
        0x80de_b1fe,
        0x9bdc_06a7,
        0xc19b_f174,
        0xe49b_69c1,
        0xefbe_4786,
        0x0fc1_9dc6,
        0x240c_a1cc,
        0x2de9_2c6f,
        0x4a74_84aa,
        0x5cb0_a9dc,
        0x76f9_88da,
        0x983e_5152,
        0xa831_c66d,
        0xb003_27c8,
        0xbf59_7fc7,
        0xc6e0_0bf3,
        0xd5a7_9147,
        0x06ca_6351,
        0x1429_2967,
        0x27b7_0a85,
        0x2e1b_2138,
        0x4d2c_6dfc,
        0x5338_0d13,
        0x650a_7354,
        0x766a_0abb,
        0x81c2_c92e,
        0x9272_2c85,
        0xa2bf_e8a1,
        0xa81a_664b,
        0xc24b_8b70,
        0xc76c_51a3,
        0xd192_e819,
        0xd699_0624,
        0xf40e_3585,
        0x106a_a070,
        0x19a4_c116,
        0x1e37_6c08,
        0x2748_774c,
        0x34b0_bcb5,
        0x391c_0cb3,
        0x4ed8_aa4a,
        0x5b9c_ca4f,
        0x682e_6ff3,
        0x748f_82ee,
        0x78a5_636f,
        0x84c8_7814,
        0x8cc7_0208,
        0x90be_fffa,
        0xa450_6ceb,
        0xbef9_a3f7,
        0xc671_78f2,
    ];
    let mut state: [u32; 8] = [
        0x6a09_e667,
        0xbb67_ae85,
        0x3c6e_f372,
        0xa54f_f53a,
        0x510e_527f,
        0x9b05_688c,
        0x1f83_d9ab,
        0x5be0_cd19,
    ];
    let mut message = data.to_vec();
    message.push(0x80);
    while message.len() % 64 != 56 {
        message.push(0);
    }
    message.extend_from_slice(&(u64::try_from(data.len()).unwrap_or(u64::MAX) * 8).to_be_bytes());
    for block in message.chunks_exact(64) {
        let mut w = [0u32; 64];
        for (slot, bytes) in w.iter_mut().zip(block.chunks_exact(4)) {
            *slot = u32::from_be_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = state;
        for (k, word) in K.iter().zip(w.iter()) {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let choose = (e & f) ^ (!e & g);
            let t1 = h
                .wrapping_add(s1)
                .wrapping_add(choose)
                .wrapping_add(*k)
                .wrapping_add(*word);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let majority = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(majority);
            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        for (held, added) in state.iter_mut().zip([a, b, c, d, e, f, g, h]) {
            *held = held.wrapping_add(added);
        }
    }
    state.iter().map(|word| format!("{word:08x}")).collect()
}
