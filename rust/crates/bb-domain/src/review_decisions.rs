//! The Review decision family (026 PR-15): `review.decide`,
//! `review.undo_decision`, `review.bulk_release` and `review.bulk_undo`.
//!
//! `decide(read_set, command, inputs)` is pure: time is `inputs.now`, every
//! identifier a command did not bring is the next of `inputs.allocated_ids`, and
//! the rows it reads are the protected [`ReadSet`]. The result lists the records
//! it changes in the server's write order, or a typed refusal.
//!
//! The server is normative (`ReviewService.decide`, `_apply_decision`,
//! `undo_decision`, `ReviewFlowService.bulk_release`, `undo_bulk_release` in
//! `backend/app/modules/tasks/review_{service,flow}.py`). The list moves of a
//! decision are [`crate::task_rules`] (`task.transition`, `task.create`), the
//! clock effects are [`crate::formulation`], the auto-park yield and the park
//! rows are [`crate::park`] and the "Undo may not delete a person's rows" check
//! reads [`crate::children`]. Nothing here repeats one of those rules.
//!
//! | Command | `entity_id` | Revision check | Rule |
//! | --- | --- | --- | --- |
//! | `review.decide` | the task | the task | an auto-park yield (ADR-0027) replaces the revision check; the type must be allowed on the task's list; formulation types name the current formulation; `follow_up`/`return_to_next` need an active project; one card, one decision per run |
//! | `review.undo_decision` | the decision | the decision's task | server snapshot, 7-day window, the task still at the decision's revision, the follow-up still as created |
//! | `review.bulk_release` | the bulk release | none: every item brings its own | per item: `not_eligible` (list, restart age), then `stale`; the accepted subset and the record commit once |
//! | `review.bulk_undo` | the bulk release | none | per item: back to its list with its stored clock, or `stale`; 7-day window |
//!
//! A decision or release whose ID is already stored is the adapter's matching
//! record: the same task/type/formulation (decision) or kind/task set (release)
//! is an accepted no-op, anything else is [`Reason::IdAlreadyExists`]. The
//! idempotency-key replay and the stored response stay with the adapter.
//!
//! Server-only content is written only where `inputs.private_review()`: the Undo
//! snapshot of a decision (`Decision::private`) and the clock-before of a bulk
//! release (`BulkReleased::private`). A nonauthoritative read missing those
//! facts reports a precisely named [`Reason::IncompleteReadSet`] after decisive
//! public checks; authoritative purging remains [`Reason::UndoUnavailable`]. The
//! 7-day deadline is judged from the stored instants on every read, whether or
//! not the retention job has nulled the content yet.
//!
//! Not here: the session record's own transitions (progress, finish) and the
//! stored `DecisionQueue`, which the server derives from the decisions at read
//! time; both belong to the session family.

use crate::calendar::UtcInstant;
use crate::children;
use crate::formulation::{
    self, DecisionInput, FormulationError, OwnerClockSettings, ReleasedClock, TaskClock,
    decision_allows, parse_instant, wire_instant,
};
use crate::park::{self, ParkRow, YieldQuery};
use crate::task_rules;
use crate::types::{
    BulkId, BulkKind, BulkRelease, BulkReleaseRequest, BulkReleased, BulkSkipped, BulkUndoResult,
    BulkUndoSkipped, ChangeOutcome, ChangeSet, ClockBefore, Command, CountBucket, Counter, Decide,
    Decision, DecisionId, DecisionType, DecisionUndo, Details, DomainChange, DomainCommand,
    DomainError, EntityType, ExecutionInputs, FormulationId, Id, Instant, LocalDecisionBefore,
    OpenList, Priority, ProjectState, ReadSet, Reason, ReasonText, ReceiptKind, ReceiptSource,
    Record, ReleasedItem, ReleasedPrivate, ReplacedReceipt, ResultRefs, ReviewReceipt,
    ReviewSession, RevisionCheck, SessionBefore, SessionCounts, SessionId, SessionStatus,
    SkipReason, StepCode, StepStatus, Task, TaskAction, TaskCreate, TaskId, TaskState,
    TaskTransition, Title, UndoSkipReason, WaitingFor,
};
use std::collections::BTreeSet;

/// Decision Undo and bulk-release Undo content lives seven days
/// (`SNAPSHOT_RETENTION`).
pub const UNDO_WINDOW_SECONDS: i64 = 7 * 86_400;
/// A Waiting receipt hides its task from the Waiting step for seven days.
pub const WAITING_RECEIPT_SECONDS: i64 = 7 * 86_400;
/// A Someday receipt hides its task from the Someday step for thirty days.
pub const SOMEDAY_RECEIPT_SECONDS: i64 = 30 * 86_400;

/// Whether this family decides `command`.
#[must_use]
pub fn handles(command: &Command) -> bool {
    matches!(
        command,
        Command::ReviewDecide(_)
            | Command::ReviewUndoDecision(_)
            | Command::ReviewBulkRelease(_)
            | Command::ReviewBulkUndo(_)
    )
}

/// Decides one Review decision command against the protected read set.
///
/// A command of another family is refused as [`Reason::InvalidPayload`]
/// (`field = "type"`); the dispatcher asks [`handles`] first.
pub fn decide(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    decide_review(
        read_set,
        command,
        &crate::types::ReviewInputs::server(inputs),
    )
}

pub(crate) fn decide_review(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &crate::types::ReviewInputs<'_>,
) -> Result<ChangeSet, DomainError> {
    let now = parse_instant(&inputs.now, "now").map_err(clock_error)?;
    match &command.command {
        Command::ReviewDecide(payload) => {
            let context = Context {
                read_set,
                command,
                payload,
                inputs,
                settings: clock_settings(read_set)?,
                now,
            };
            review_decide(&context)
        }
        Command::ReviewUndoDecision(_) => undo_decision(read_set, command, inputs, now),
        Command::ReviewBulkRelease(payload) => {
            bulk_release(read_set, command, payload, inputs, now)
        }
        Command::ReviewBulkUndo(_) => bulk_undo(read_set, command, inputs, now),
        _ => Err(DomainError::field(Reason::InvalidPayload, "type")),
    }
}

/// `REVIEW_COUNTS_AS` (data-model E4): the summary counter a decision counts in.
#[must_use]
pub fn counts_as(decision: DecisionType) -> CountBucket {
    match decision {
        DecisionType::Complete => CountBucket::Done,
        DecisionType::Reformulate => CountBucket::Reformulated,
        DecisionType::FirstStep => CountBucket::FirstStep,
        DecisionType::Waiting => CountBucket::Waiting,
        DecisionType::Someday => CountBucket::Someday,
        DecisionType::Cancel => CountBucket::Cancelled,
        DecisionType::Extend => CountBucket::Extended,
        DecisionType::KeepWaiting | DecisionType::KeepSomeday => CountBucket::Kept,
        DecisionType::FollowUp | DecisionType::ReturnToNext => CountBucket::MovedToNext,
    }
}

/// Types that leave the task's revision alone (http §3): the revision check
/// cannot tell a repeat from the first, so the run's own record does.
#[must_use]
pub fn leaves_revision(decision: DecisionType) -> bool {
    matches!(
        decision,
        DecisionType::KeepWaiting | DecisionType::KeepSomeday | DecisionType::FollowUp
    )
}

/// Types decided on the task's current formulation: another id is stale.
fn on_formulation(decision: DecisionType) -> bool {
    matches!(
        decision,
        DecisionType::Reformulate
            | DecisionType::FirstStep
            | DecisionType::Waiting
            | DecisionType::Someday
            | DecisionType::Extend
    )
}

// --------------------------------------------------------------------- helpers

fn key_of(id: &str) -> Vec<String> {
    vec![id.to_owned()]
}

fn not_found(entity_type: EntityType, id: &str) -> DomainError {
    DomainError::about(Reason::NotFound, entity_type, key_of(id))
}

fn refuse(reason: Reason, entity_type: EntityType, id: &str) -> DomainError {
    DomainError::about(reason, entity_type, key_of(id))
}

fn clock_error(error: FormulationError) -> DomainError {
    match error {
        FormulationError::DecisionNotAllowed => DomainError::new(Reason::DecisionNotAllowed),
        FormulationError::ExtensionAlreadyUsed => DomainError::new(Reason::ExtensionAlreadyUsed),
        FormulationError::ExtensionNotDue => DomainError::new(Reason::ExtensionNotDue),
        FormulationError::UnknownTimeZone(_) => {
            DomainError::field(Reason::InvalidTimeZone, "time_zone")
        }
        FormulationError::InvalidThreshold(_) => {
            DomainError::field(Reason::InvalidValue, "threshold_days")
        }
        FormulationError::MissingInput("title") => {
            DomainError::field(Reason::DecisionFieldsMissing, "title")
        }
        FormulationError::MissingInput(name) => {
            DomainError::field(Reason::FormulationIdRequired, name)
        }
        FormulationError::InvalidField(name) => DomainError::field(Reason::InvalidValue, name),
        FormulationError::NotParked | FormulationError::ParkSnapshotUnavailable => {
            DomainError::new(Reason::IncompleteReadSet)
        }
    }
}

/// The owner's clock inputs: the stored settings, or the server's defaults for an
/// owner that has none (14 days, UTC, never activated).
fn clock_settings(read_set: &ReadSet) -> Result<OwnerClockSettings, DomainError> {
    match &read_set.settings {
        Some(settings) => OwnerClockSettings::from_review_settings(settings),
        None => OwnerClockSettings::new(14, "UTC", None, None),
    }
    .map_err(clock_error)
}

fn wire(instant: UtcInstant) -> Result<Instant, DomainError> {
    wire_instant(instant, "instant").map_err(clock_error)
}

fn plus_one(counter: &Counter) -> Result<Counter, DomainError> {
    counter
        .to_u64()
        .and_then(|value| value.checked_add(1))
        .map(Counter::from)
        .ok_or_else(|| DomainError::field(Reason::InvalidValue, "revision"))
}

fn existing_task<'a>(read_set: &'a ReadSet, id: &TaskId) -> Result<&'a Task, DomainError> {
    read_set
        .tasks
        .get(id)
        .ok_or_else(|| not_found(EntityType::Task, id.as_str()))
}

/// The revision a command expects of one task.
fn expected_revision<'a>(
    command: &'a DomainCommand,
    task_id: &TaskId,
) -> Result<&'a Counter, DomainError> {
    command
        .preconditions
        .iter()
        .find(|check| {
            check.entity_type == EntityType::Task && check.entity_id.as_str() == task_id.as_str()
        })
        .map(|check| &check.edit_revision)
        .ok_or_else(|| DomainError::field(Reason::InvalidPayload, "preconditions"))
}

fn applied(changes: Vec<DomainChange>, result: ResultRefs) -> ChangeSet {
    ChangeSet {
        outcome: ChangeOutcome::Applied,
        changes,
        result,
        effects: Vec::new(),
    }
}

fn upsert(record: Record) -> DomainChange {
    DomainChange::Upsert(record)
}

fn tombstone(entity_type: EntityType, record_key: Vec<String>) -> DomainChange {
    DomainChange::Tombstone {
        entity_type,
        record_key,
    }
}

/// The park row of a task's formulation, as the rule reads it.
fn park_row(read_set: &ReadSet, task_id: &TaskId, formulation_id: &str) -> Option<ParkRow> {
    read_set
        .park_acks
        .iter()
        .find(|ack| &ack.task_id == task_id && ack.formulation_id.as_str() == formulation_id)
        .and_then(|ack| ParkRow::from_ack(ack).ok())
}

fn row_change(row: &ParkRow) -> Result<DomainChange, DomainError> {
    row.to_ack()
        .map(|ack| upsert(Record::ReviewParkAck(ack)))
        .map_err(clock_error)
}

/// A session the owner holds, else `None` (an unknown run is recorded without
/// one, never refused).
fn known_session(read_set: &ReadSet, session_id: Option<&SessionId>) -> Option<SessionId> {
    session_id
        .filter(|id| read_set.sessions.contains_key(*id))
        .cloned()
}

fn receipt_for(
    task: &Task,
    kind: ReceiptKind,
    source: ReceiptSource,
    now: UtcInstant,
) -> Result<ReviewReceipt, DomainError> {
    let span = match kind {
        ReceiptKind::Waiting => WAITING_RECEIPT_SECONDS,
        ReceiptKind::Someday => SOMEDAY_RECEIPT_SECONDS,
    };
    Ok(ReviewReceipt {
        task_id: task.id.clone(),
        kind,
        hidden_until: wire(now.plus_seconds(span))?,
        task_revision: task.revision.clone(),
        reviewed_at: wire(now)?,
        source,
        decision_id: None,
        bulk_id: None,
    })
}

/// The seven-day deadline of Undo content that was written at `written`.
fn undo_deadline(written: UtcInstant) -> UtcInstant {
    written.plus_seconds(UNDO_WINDOW_SECONDS)
}

// ---------------------------------------------------------------- session counts

fn bump_bucket(counts: &SessionCounts, bucket: CountBucket, delta: i64) -> SessionCounts {
    let moved = |value: u32| u32::try_from((i64::from(value) + delta).max(0)).unwrap_or(u32::MAX);
    let mut changed = *counts;
    let field = match bucket {
        CountBucket::Done => &mut changed.done,
        CountBucket::Reformulated => &mut changed.reformulated,
        CountBucket::FirstStep => &mut changed.first_step,
        CountBucket::Waiting => &mut changed.waiting,
        CountBucket::Someday => &mut changed.someday,
        CountBucket::Cancelled => &mut changed.cancelled,
        CountBucket::Extended => &mut changed.extended,
        CountBucket::InboxProcessed => &mut changed.inbox_processed,
        CountBucket::Kept => &mut changed.kept,
        CountBucket::MovedToNext => &mut changed.moved_to_next,
    };
    *field = moved(*field);
    changed
}

fn total_decisions(counts: &SessionCounts) -> u64 {
    CountBucket::ALL
        .iter()
        .map(|bucket| u64::from(counts.get(*bucket)))
        .sum()
}

/// `review_rules.qualifying_activity`: a counted decision, or a step other than
/// the summary finished with nothing to decide.
fn qualifies(session: &ReviewSession, counts: &SessionCounts) -> bool {
    if total_decisions(counts) > 0 {
        return true;
    }
    session.private.as_ref().is_some_and(|private| {
        private.finished_empty.iter().any(|code| {
            *code != StepCode::Summary && session.steps.get(code) == Some(&StepStatus::Finished)
        })
    })
}

/// The linked session after a decision (`delta = 1`) or its Undo (`-1`): the
/// bucket moves, the run qualifies, its revision advances and an open run
/// counts the activity (`_update_session`). `None` when the run is gone.
fn session_change(
    read_set: &ReadSet,
    session_id: Option<&SessionId>,
    bucket: CountBucket,
    delta: i64,
    now: UtcInstant,
    local: bool,
    restore: Option<&SessionBefore>,
) -> Result<Option<DomainChange>, DomainError> {
    let Some(session) = session_id.and_then(|id| read_set.sessions.get(id)) else {
        return Ok(None);
    };
    let counts = bump_bucket(&session.counts, bucket, delta);
    let mut updated = ReviewSession {
        counts,
        qualifying_activity: qualifies(session, &counts),
        revision: plus_one(&session.revision)?,
        ..session.clone()
    };
    if local {
        updated.qualifying_activity = session.qualifying_activity;
        if delta > 0 {
            updated.qualifying_activity = true;
            updated.last_activity_at = wire(
                now.max(
                    parse_instant(&session.last_activity_at, "last_activity_at")
                        .map_err(clock_error)?,
                ),
            )?;
        } else if let Some(before) = restore
            && session.last_activity_at == before.last_activity_after
            && before
                .revision_after
                .as_ref()
                .is_none_or(|after| *after == session.revision)
        {
            updated.qualifying_activity = before.qualifying_activity;
            updated.last_activity_at = before.last_activity_at.clone();
        }
    } else if session.status == SessionStatus::Open {
        updated.last_activity_at = wire(now)?;
    }
    Ok(Some(upsert(Record::ReviewSession(updated))))
}

// ================================================================= review.decide

struct Context<'a> {
    read_set: &'a ReadSet,
    command: &'a DomainCommand,
    payload: &'a Decide,
    inputs: &'a crate::types::ReviewInputs<'a>,
    settings: OwnerClockSettings,
    now: UtcInstant,
}

/// What one decision type did to its task.
struct Effect {
    /// The task and park-row writes, in application order.
    changes: Vec<DomainChange>,
    updated: Task,
    created: Option<Task>,
    receipt: Option<ReviewReceipt>,
    substantive: Option<bool>,
}

fn review_decide(context: &Context<'_>) -> Result<ChangeSet, DomainError> {
    let Context {
        read_set,
        command,
        payload,
        ..
    } = *context;
    if let Some(field) = payload.missing_fields().first() {
        return Err(DomainError::field(Reason::DecisionFieldsMissing, field));
    }
    let task_id = TaskId::parse(command.entity_id.as_str())?;
    let decision_id = DecisionId::from(payload.decision_id.clone());
    if let Some(stored) = read_set.decisions.get(&decision_id) {
        let same = stored.task_id == task_id
            && stored.decision_type == payload.decision_type
            && stored.formulation_id == payload.formulation_id;
        return if same {
            Ok(ChangeSet::no_op())
        } else {
            Err(refuse(
                Reason::IdAlreadyExists,
                EntityType::ReviewDecision,
                decision_id.as_str(),
            ))
        };
    }
    let task = existing_task(read_set, &task_id)?;
    let clock = TaskClock::from_task(task).map_err(clock_error)?;
    let expected = expected_revision(command, &task_id)?;
    let expected_number = expected
        .to_u64()
        .ok_or_else(|| DomainError::field(Reason::InvalidValue, "edit_revision"))?;
    let decided_at = payload
        .client_decided_at
        .as_ref()
        .map(|instant| parse_instant(instant, "client_decided_at").map_err(clock_error))
        .transpose()?;
    let query = YieldQuery {
        decision: payload.decision_type,
        formulation_id: payload.formulation_id.as_ref().map(FormulationId::as_str),
        expected_revision: expected_number,
        client_decided_at: decided_at,
    };
    // ADR-0027: a human decision made before the auto-park, on the parked
    // formulation, reverses the park first; it replaces the revision check.
    let yielded = park::yields(&clock, &query);
    let base = if yielded {
        reversed(task, &clock)?
    } else {
        if expected != &task.revision {
            return Err(DomainError::stale(
                EntityType::Task,
                key_of(task_id.as_str()),
                task.revision.clone(),
            ));
        }
        task.clone()
    };
    check_decision(context, &base)?;
    if repeats_run_decision(context, &base)? {
        return Ok(ChangeSet::no_op());
    }
    let effect = apply_decision(context, &base)?;
    assemble_decision(context, &base, effect, yielded)
}

/// The parked task as the yield restores it: back in Next with its clock before
/// the park, the same revision.
fn reversed(task: &Task, clock: &TaskClock) -> Result<Task, DomainError> {
    let restored = formulation::reverse_park(clock).map_err(clock_error)?;
    let mut base = Task {
        state: TaskState::Next,
        ..task.clone()
    };
    restored
        .write_clock_fields(&mut base)
        .map_err(clock_error)?;
    Ok(base)
}

/// `_check_decision`: the list, the formulation and the destination project.
fn check_decision(context: &Context<'_>, task: &Task) -> Result<(), DomainError> {
    let payload = context.payload;
    if !decision_allows(payload.decision_type, task.state) {
        return Err(refuse(
            Reason::DecisionNotAllowed,
            EntityType::Task,
            task.id.as_str(),
        ));
    }
    let names_formulation = on_formulation(payload.decision_type)
        || (task.state == TaskState::Next && payload.formulation_id.is_some());
    let current = task.formulation.as_ref().map(|clock| &clock.id);
    if names_formulation && payload.formulation_id.as_ref() != current {
        return Err(refuse(
            Reason::FormulationChanged,
            EntityType::Task,
            task.id.as_str(),
        ));
    }
    if matches!(
        payload.decision_type,
        DecisionType::FollowUp | DecisionType::ReturnToNext
    ) && let Some(project_id) = &task.project_id
    {
        let project = context.read_set.projects.get(project_id).ok_or_else(|| {
            DomainError::missing(EntityType::Project, key_of(project_id.as_str()))
        })?;
        if project.state != ProjectState::Active {
            return Err(refuse(
                Reason::ProjectArchived,
                EntityType::Project,
                project_id.as_str(),
            ));
        }
    }
    Ok(())
}

/// `_repeated_decision`: one card, one decision per run. A repeat changes
/// nothing and the run counts it once; an Undo deletes the decision, so the
/// card is new again.
fn repeats_run_decision(context: &Context<'_>, task: &Task) -> Result<bool, DomainError> {
    let payload = context.payload;
    let Some(session_id) = known_session(context.read_set, payload.session_id.as_ref()) else {
        return Ok(false);
    };
    let earlier = context.read_set.decisions.values().filter(|decision| {
        decision.session_id.as_ref() == Some(&session_id) && decision.task_id == task.id
    });
    if payload.decision_type == DecisionType::Reformulate {
        let title = payload.title.as_ref().map_or("", |text| text.as_str());
        if formulation::is_substantive(task.title.as_str(), title) {
            return Ok(false);
        }
        // A cosmetic reformulate of the same formulation after one the run holds.
        let mut earlier = earlier;
        return Ok(earlier.any(|decision| {
            decision.decision_type == DecisionType::Reformulate
                && decision.substantive == Some(false)
                && decision.formulation_id == payload.formulation_id
        }));
    }
    if leaves_revision(payload.decision_type) {
        // The task is still as the run's keep or follow-up decision left it.
        let mut earlier = earlier;
        return Ok(earlier.any(|decision| {
            leaves_revision(decision.decision_type) && decision.task_revision_after == task.revision
        }));
    }
    Ok(false)
}

fn apply_decision(context: &Context<'_>, task: &Task) -> Result<Effect, DomainError> {
    let payload = context.payload;
    let unchanged = |receipt: Option<ReviewReceipt>| Effect {
        changes: Vec::new(),
        updated: task.clone(),
        created: None,
        receipt,
        substantive: None,
    };
    match payload.decision_type {
        DecisionType::Complete
        | DecisionType::Cancel
        | DecisionType::Waiting
        | DecisionType::Someday
        | DecisionType::ReturnToNext => list_move(context, task),
        DecisionType::Reformulate | DecisionType::FirstStep | DecisionType::Extend => {
            clock_edit(context, task)
        }
        DecisionType::KeepWaiting => Ok(unchanged(Some(receipt_for(
            task,
            ReceiptKind::Waiting,
            ReceiptSource::Keep,
            context.now,
        )?))),
        DecisionType::KeepSomeday => Ok(unchanged(Some(receipt_for(
            task,
            ReceiptKind::Someday,
            ReceiptSource::Keep,
            context.now,
        )?))),
        DecisionType::FollowUp => follow_up(context, task),
    }
}

/// complete, cancel, waiting, someday and return_to_next are the task
/// lifecycle's own `task.transition` (`_transitioned`), run on the task as the
/// decision sees it.
fn list_move(context: &Context<'_>, task: &Task) -> Result<Effect, DomainError> {
    let payload = context.payload;
    let (action, to_state) = match payload.decision_type {
        DecisionType::Complete => (TaskAction::Complete, None),
        DecisionType::Cancel => (TaskAction::Cancel, None),
        DecisionType::Waiting => (TaskAction::Move, Some(OpenList::Waiting)),
        DecisionType::Someday => (TaskAction::Move, Some(OpenList::Someday)),
        _ => (TaskAction::Move, Some(OpenList::Next)),
    };
    let waiting_for = payload
        .waiting_for
        .as_ref()
        .map(|text| WaitingFor::new(text.as_str()))
        .transpose()?;
    let transition = DomainCommand {
        command_id: context.command.command_id.clone(),
        entity_id: context.command.entity_id.clone(),
        issued_at: context.command.issued_at.clone(),
        preconditions: vec![RevisionCheck {
            entity_type: EntityType::Task,
            entity_id: context.command.entity_id.clone(),
            edit_revision: task.revision.clone(),
        }],
        command: Command::TaskTransition(TaskTransition {
            action,
            to_state,
            waiting_for,
            new_formulation_id: payload.new_formulation_id.clone(),
        }),
    };
    let scoped = ReadSet {
        tasks: [(task.id.clone(), task.clone())].into(),
        settings: context.read_set.settings.clone(),
        park_acks: context
            .read_set
            .park_acks
            .iter()
            .filter(|ack| ack.task_id == task.id)
            .cloned()
            .collect(),
        ..ReadSet::default()
    };
    let mut changes = task_rules::decide(&scoped, &transition, context.inputs)?.changes;
    let Some(DomainChange::Upsert(Record::Task(moved))) = changes.first_mut() else {
        return Err(DomainError::new(Reason::InvalidValue));
    };
    if payload.decision_type == DecisionType::ReturnToNext
        && let Some(title) = &payload.title
        && title.as_str() != moved.title.as_str()
    {
        // The title changes with the move and does not advance the revision.
        moved.title = Title::new(title.as_str())?;
    }
    let updated = moved.clone();
    let receipt = if payload.decision_type == DecisionType::Someday {
        Some(receipt_for(
            &updated,
            ReceiptKind::Someday,
            ReceiptSource::Release,
            context.now,
        )?)
    } else {
        None
    };
    Ok(Effect {
        changes,
        updated,
        created: None,
        receipt,
        substantive: None,
    })
}

/// reformulate, first_step and extend: the formulation clock decides, the task
/// keeps the clock's revision (`_edited`).
fn clock_edit(context: &Context<'_>, task: &Task) -> Result<Effect, DomainError> {
    let payload = context.payload;
    let decision = payload.decision_type;
    let clock = TaskClock::from_task(task).map_err(clock_error)?;
    let title = payload.title.as_ref().map(|text| text.as_str());
    let substantive = match decision {
        DecisionType::Reformulate => Some(formulation::is_substantive(
            task.title.as_str(),
            title.unwrap_or(""),
        )),
        DecisionType::FirstStep => Some(true),
        _ => None,
    };
    let allocated = context.inputs.allocated_ids.first().map(|id| id.as_str());
    let requested = payload.new_formulation_id.as_ref().map(|id| id.as_str());
    // A cosmetic reformulate keeps the clock, so it needs no new formulation.
    let new_formulation_id = match (requested.or(allocated), substantive) {
        (Some(id), _) => Some(id),
        (None, Some(false)) | (None, None) => Some(""),
        (None, Some(true)) => None,
    };
    let edited = formulation::decide(
        &clock,
        decision,
        &context.settings,
        context.now,
        &DecisionInput {
            title,
            reason: payload.reason.as_ref().map(ReasonText::as_str),
            new_formulation_id,
        },
    )
    .map_err(clock_error)?;
    let mut updated = Task {
        updated_at: context.inputs.now.clone(),
        revision: Counter::from(edited.revision),
        ..task.clone()
    };
    if let Some(title) = title.filter(|_| decision != DecisionType::Extend) {
        updated.title = Title::new(title)?;
    }
    if decision == DecisionType::FirstStep {
        // The old title is kept in the notes (FR-008).
        let was = format!("Was: {}", task.title.as_str());
        let notes = match &task.details {
            Some(details) if !details.as_str().is_empty() => {
                format!("{was}\n\n{}", details.as_str())
            }
            _ => was,
        };
        updated.details = Some(
            Details::new(notes).map_err(|_| DomainError::field(Reason::TextLength, "details"))?,
        );
    }
    edited
        .write_clock_fields(&mut updated)
        .map_err(clock_error)?;
    Ok(Effect {
        changes: vec![upsert(Record::Task(updated.clone()))],
        updated,
        created: None,
        receipt: None,
        substantive,
    })
}

/// follow_up: a new Next task in the same project and a Keep receipt for the
/// waiting task, which stays as it is (`_follow_up`).
fn follow_up(context: &Context<'_>, task: &Task) -> Result<Effect, DomainError> {
    let payload = context.payload;
    let allocated = &context.inputs.allocated_ids;
    let (new_id, taken) = match &payload.follow_up_task_id {
        Some(id) => (TaskId::from(id.clone()), 0),
        None => {
            let id = allocated
                .first()
                .ok_or_else(|| DomainError::field(Reason::InvalidValue, "follow_up_task_id"))?;
            (TaskId::parse(id.as_str())?, 1)
        }
    };
    let title = payload
        .title
        .as_ref()
        .ok_or_else(|| DomainError::field(Reason::DecisionFieldsMissing, "title"))?;
    let create = DomainCommand {
        command_id: context.command.command_id.clone(),
        entity_id: Id::parse(new_id.as_str())
            .map_err(|_| DomainError::field(Reason::InvalidValue, "follow_up_task_id"))?,
        issued_at: context.command.issued_at.clone(),
        preconditions: Vec::new(),
        command: Command::TaskCreate(TaskCreate {
            title: Title::new(title.as_str())?,
            details: None,
            state: OpenList::Next,
            project_id: task.project_id.clone(),
            tag_ids: Vec::new(),
            due_date: None,
            priority: Priority::None,
            waiting_for: None,
            source_capture_ids: Vec::new(),
            new_formulation_id: payload.new_formulation_id.clone(),
        }),
    };
    let inputs = ExecutionInputs {
        allocated_ids: allocated.iter().skip(taken).cloned().collect(),
        ..(**context.inputs).clone()
    };
    let scoped = ReadSet {
        tasks: context
            .read_set
            .tasks
            .iter()
            .filter(|(_, other)| other.state == TaskState::Next)
            .map(|(id, other)| (id.clone(), other.clone()))
            .collect(),
        projects: context.read_set.projects.clone(),
        ..ReadSet::default()
    };
    // The id must be free in the whole read set, not only among Next tasks.
    if context.read_set.tasks.contains_key(&new_id) {
        return Err(refuse(
            Reason::IdAlreadyExists,
            EntityType::Task,
            new_id.as_str(),
        ));
    }
    let created = task_rules::decide(&scoped, &create, &inputs)?
        .changes
        .into_iter()
        .find_map(|change| match change {
            DomainChange::Upsert(Record::Task(created)) => Some(created),
            _ => None,
        })
        .ok_or_else(|| DomainError::new(Reason::InvalidValue))?;
    Ok(Effect {
        changes: Vec::new(),
        updated: task.clone(),
        created: Some(created),
        receipt: Some(receipt_for(
            task,
            ReceiptKind::Waiting,
            ReceiptSource::Keep,
            context.now,
        )?),
        substantive: None,
    })
}

/// The records of one applied decision in `_write_decision` order.
fn assemble_decision(
    context: &Context<'_>,
    base: &Task,
    effect: Effect,
    yielded: bool,
) -> Result<ChangeSet, DomainError> {
    let Context {
        read_set,
        payload,
        inputs,
        now,
        ..
    } = *context;
    let decision_id = DecisionId::from(payload.decision_id.clone());
    let session_id = known_session(read_set, payload.session_id.as_ref());
    let bucket = counts_as(payload.decision_type);
    let session_after = session_change(
        read_set,
        session_id.as_ref(),
        bucket,
        1,
        now,
        inputs.local_review(),
        None,
    )?;
    let local_before = inputs.local_review().then(|| LocalDecisionBefore {
        receipt_replaced: effect
            .receipt
            .as_ref()
            .and_then(|written| {
                read_set
                    .receipts
                    .iter()
                    .find(|receipt| receipt.task_id == base.id && receipt.kind == written.kind)
            })
            .map(|receipt| ReplacedReceipt {
                receipt: receipt.clone(),
                task_was_unchanged: receipt.task_revision == base.revision,
            }),
        session_before: session_id
            .as_ref()
            .and_then(|id| read_set.sessions.get(id))
            .and_then(|before| match &session_after {
                Some(DomainChange::Upsert(Record::ReviewSession(after))) => Some(SessionBefore {
                    qualifying_activity: before.qualifying_activity,
                    last_activity_at: before.last_activity_at.clone(),
                    last_activity_after: after.last_activity_at.clone(),
                    revision_after: Some(after.revision.clone()),
                }),
                _ => None,
            }),
    });
    let mut changes = effect.changes;
    if yielded && let Some(parked) = formulation_of_park(read_set, base, payload) {
        // A yield reverses the park itself; it is not a return (E6).
        if let Some(row) = park::set_returned(Some(&parked), None) {
            changes.push(row_change(&row)?);
        }
    }
    let created_id = effect.created.as_ref().map(|created| created.id.clone());
    let created_revision = effect
        .created
        .as_ref()
        .map(|created| created.revision.clone());
    if let Some(created) = effect.created {
        changes.push(upsert(Record::Task(created)));
    }
    let receipt_kind = effect.receipt.as_ref().map(|receipt| receipt.kind);
    if let Some(receipt) = effect.receipt {
        changes.push(upsert(Record::ReviewReceipt(ReviewReceipt {
            decision_id: Some(decision_id.clone()),
            ..receipt
        })));
    }
    let private = inputs.private_review().then(|| DecisionUndo {
        task_before: Box::new(base.clone()),
        created_task_revision: created_revision,
        receipt_kind,
        local_before,
    });
    let undo_available_until = private
        .as_ref()
        .map(|_| wire(undo_deadline(now)))
        .transpose()?;
    changes.push(upsert(Record::ReviewDecision(Decision {
        id: decision_id,
        decision_type: payload.decision_type,
        task_id: base.id.clone(),
        session_id: session_id.clone(),
        decided_at: inputs.now.clone(),
        substantive: effect.substantive,
        stall_reason: payload.stall_reason,
        ai_use: payload.ai_use,
        yielded_auto_park: yielded,
        formulation_id: payload.formulation_id.clone(),
        task_revision_before: base.revision.clone(),
        task_revision_after: effect.updated.revision.clone(),
        created_task_id: created_id.clone(),
        navigator_request_id: payload.navigator_request_id.clone(),
        review_counts_as: bucket,
        client_decided_at: payload.client_decided_at.clone(),
        reason_text: (payload.decision_type == DecisionType::Extend)
            .then(|| payload.reason.clone())
            .flatten(),
        undo_available_until,
        private,
    })));
    changes.extend(session_after);
    Ok(applied(
        changes,
        ResultRefs {
            created_task_id: created_id,
            ..ResultRefs::default()
        },
    ))
}

/// The park row of the formulation a yielded decision reversed.
fn formulation_of_park(read_set: &ReadSet, base: &Task, payload: &Decide) -> Option<ParkRow> {
    let formulation_id = payload.formulation_id.as_ref()?;
    park_row(read_set, &base.id, formulation_id.as_str())
}

// ========================================================== review.undo_decision

fn undo_decision(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &crate::types::ReviewInputs<'_>,
    now: UtcInstant,
) -> Result<ChangeSet, DomainError> {
    let decision_id = DecisionId::parse(command.entity_id.as_str())?;
    let decision = read_set
        .decisions
        .get(&decision_id)
        .ok_or_else(|| not_found(EntityType::ReviewDecision, decision_id.as_str()))?;
    let task = existing_task(read_set, &decision.task_id)?;
    let expected = expected_revision(command, &task.id)?;
    let unavailable = || refuse(Reason::UndoUnavailable, EntityType::Task, task.id.as_str());
    let decided = parse_instant(&decision.decided_at, "decided_at").map_err(clock_error)?;
    let at_decision = task.revision == decision.task_revision_after && expected == &task.revision;
    if now >= undo_deadline(decided) || !at_decision {
        return Err(unavailable());
    }
    // Visible user rows already make deleting the follow-up unsafe, even when
    // the private creation revision was not supplied by this read.
    if let Some(created) = decision
        .created_task_id
        .as_ref()
        .and_then(|id| read_set.tasks.get(id))
        && (!created.tag_ids.is_empty()
            || read_set
                .subtasks
                .values()
                .any(|child| child.task_id == created.id)
            || read_set
                .comments
                .values()
                .any(|child| child.task_id == created.id))
    {
        return Err(unavailable());
    }
    let undo = decision.private.as_ref().ok_or_else(|| {
        if inputs.private_review() {
            unavailable()
        } else {
            private_missing(
                EntityType::ReviewDecision,
                decision.id.as_str(),
                "undo_snapshot",
            )
        }
    })?;
    if undo.task_before.id != task.id || undo.task_before.revision != decision.task_revision_before
    {
        return Err(DomainError::field(Reason::InvalidValue, "task_before"));
    }
    if decision
        .created_task_id
        .as_ref()
        .is_some_and(|id| read_set.tasks.contains_key(id))
        && undo.created_task_revision.is_none()
    {
        return Err(DomainError::field(
            Reason::InvalidValue,
            "created_task_revision",
        ));
    }
    if inputs.local_review()
        && let Some(local) = &undo.local_before
    {
        if local.receipt_replaced.as_ref().is_some_and(|previous| {
            previous.receipt.task_id != decision.task_id
                || Some(previous.receipt.kind) != undo.receipt_kind
        }) {
            return Err(DomainError::field(Reason::InvalidValue, "receipt_replaced"));
        }
        if let Some(before) = &local.session_before {
            if decision.session_id.is_none() {
                return Err(DomainError::field(Reason::InvalidValue, "session_before"));
            }
            parse_instant(&before.last_activity_at, "last_activity_at").map_err(clock_error)?;
            parse_instant(&before.last_activity_after, "last_activity_after")
                .map_err(clock_error)?;
        }
    }
    if !created_task_unchanged(read_set, decision, undo) {
        return Err(unavailable());
    }
    let settings = clock_settings(read_set)?;
    let restored_clock = formulation::restore(
        &TaskClock::from_task(task).map_err(clock_error)?,
        &TaskClock::from_task(&undo.task_before).map_err(clock_error)?,
        &settings,
    );
    let mut restored = Task {
        revision: plus_one(&task.revision)?,
        updated_at: inputs.now.clone(),
        ..(*undo.task_before).clone()
    };
    restored_clock
        .write_clock_fields(&mut restored)
        .map_err(clock_error)?;
    let restored_revision = restored.revision.clone();
    let mut changes = vec![upsert(Record::Task(restored))];
    // Back in its park (Undo of `return_to_next`): the row reads as it did
    // while parked, not returned (E6).
    if let Some(row) = park::restore_park_row(&restored_clock, |formulation_id| {
        park_row(read_set, &task.id, formulation_id)
    }) {
        changes.push(row_change(&row)?);
    }
    let deleted_task_id = decision.created_task_id.clone();
    if let Some(created) = &deleted_task_id {
        changes.push(tombstone(EntityType::Task, key_of(created.as_str())));
    }
    if let Some(kind) = undo.receipt_kind
        && read_set.receipts.iter().any(|receipt| {
            receipt.task_id == decision.task_id
                && receipt.kind == kind
                && receipt.decision_id.as_ref() == Some(&decision.id)
        })
    {
        // Only the receipt this decision still owns; preserve later receipts.
        if inputs.local_review()
            && let Some(previous) = undo
                .local_before
                .as_ref()
                .and_then(|before| before.receipt_replaced.as_ref())
        {
            let mut receipt = previous.receipt.clone();
            if previous.task_was_unchanged {
                receipt.task_revision = restored_revision.clone();
            }
            changes.push(upsert(Record::ReviewReceipt(receipt)));
        } else {
            changes.push(tombstone(
                EntityType::ReviewReceipt,
                vec![
                    decision.task_id.as_str().to_owned(),
                    kind.as_str().to_owned(),
                ],
            ));
        }
    }
    changes.push(tombstone(
        EntityType::ReviewDecision,
        key_of(decision.id.as_str()),
    ));
    changes.extend(session_change(
        read_set,
        decision.session_id.as_ref(),
        decision.review_counts_as,
        -1,
        now,
        inputs.local_review(),
        undo.local_before
            .as_ref()
            .and_then(|before| before.session_before.as_ref()),
    )?);
    Ok(applied(
        changes,
        ResultRefs {
            deleted_task_id,
            ..ResultRefs::default()
        },
    ))
}

/// `_created_task_unchanged`: the follow-up is still exactly as the decision
/// created it, and holds no tag link, subtask or comment of the person's.
fn created_task_unchanged(read_set: &ReadSet, decision: &Decision, undo: &DecisionUndo) -> bool {
    let Some(created_id) = &decision.created_task_id else {
        return true;
    };
    let Some(created) = read_set.tasks.get(created_id) else {
        return true;
    };
    undo.created_task_revision.as_ref() == Some(&created.revision)
        && created.tag_ids.is_empty()
        && children::ordered_subtasks(read_set, created_id).is_empty()
        && children::ordered_comments(read_set, created_id).is_empty()
}

// ===================================================================== bulk release

/// The list each bulk-release kind releases from (http §6, data-model E7).
fn releasable(kind: BulkKind) -> OpenList {
    match kind {
        BulkKind::Restart => OpenList::Next,
        BulkKind::InboxRemainder => OpenList::Inbox,
    }
}

fn eligible(
    task: &Task,
    kind: BulkKind,
    settings: &OwnerClockSettings,
    now: UtcInstant,
) -> Result<bool, DomainError> {
    if task.state != releasable(kind).task_state() {
        return Ok(false);
    }
    match kind {
        BulkKind::Restart => {
            let clock = TaskClock::from_task(task).map_err(clock_error)?;
            Ok(formulation::restart_eligible(&clock, settings, now))
        }
        BulkKind::InboxRemainder => Ok(true),
    }
}

fn stored_clock(clock: &ReleasedClock) -> Result<ClockBefore, DomainError> {
    let invalid = |field: &str| DomainError::field(Reason::InvalidValue, field);
    let optional = |value: Option<UtcInstant>| value.map(wire).transpose();
    Ok(ClockBefore {
        formulation_id: Some(
            FormulationId::parse(clock.formulation_id.clone())
                .map_err(|_| invalid("formulation_id"))?,
        ),
        started_at: wire(clock.started_at)?,
        extended_at: optional(clock.extended_at)?,
        extension_reason: clock
            .extension_reason
            .as_deref()
            .map(ReasonText::new)
            .transpose()?,
        park_floor_at: optional(clock.park_floor_at)?,
        stalled_before: clock.stalled_before,
    })
}

fn released_clock(stored: &ClockBefore) -> Result<ReleasedClock, DomainError> {
    let formulation_id = stored
        .formulation_id
        .as_ref()
        .ok_or_else(|| DomainError::field(Reason::InvalidValue, "formulation_id"))?;
    let instant = |value: &Instant| parse_instant(value, "clock_before").map_err(clock_error);
    Ok(ReleasedClock {
        formulation_id: formulation_id.as_str().to_owned(),
        started_at: instant(&stored.started_at)?,
        extended_at: stored.extended_at.as_ref().map(instant).transpose()?,
        extension_reason: stored
            .extension_reason
            .as_ref()
            .map(|reason| reason.as_str().to_owned()),
        park_floor_at: stored.park_floor_at.as_ref().map(instant).transpose()?,
        stalled_before: stored.stalled_before,
    })
}

fn bulk_release(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &BulkReleaseRequest,
    inputs: &crate::types::ReviewInputs<'_>,
    now: UtcInstant,
) -> Result<ChangeSet, DomainError> {
    let bulk_id = BulkId::parse(command.entity_id.as_str())?;
    // The first revision named for a task is the one that counts.
    let mut expected: Vec<(&TaskId, &Counter)> = Vec::new();
    let mut named = BTreeSet::new();
    for item in payload.items.as_slice() {
        if named.insert(&item.task_id) {
            expected.push((&item.task_id, &item.expected_revision));
        }
    }
    if let Some(stored) = read_set.bulk_releases.get(&bulk_id) {
        let asked: BTreeSet<&TaskId> = stored
            .released
            .iter()
            .map(|item| &item.task_id)
            .chain(stored.skipped.iter().map(|item| &item.task_id))
            .collect();
        return if stored.kind == payload.kind && asked == named {
            Ok(ChangeSet::no_op())
        } else {
            Err(refuse(
                Reason::IdAlreadyExists,
                EntityType::ReviewBulkRelease,
                bulk_id.as_str(),
            ))
        };
    }
    let settings = clock_settings(read_set)?;
    let mut released = Vec::new();
    let mut skipped = Vec::new();
    let mut tasks = Vec::new();
    let mut receipts = Vec::new();
    for (task_id, revision) in expected {
        // Unknown, foreign and ineligible ids are all `not_eligible`.
        let task = match read_set.tasks.get(task_id) {
            Some(task) if eligible(task, payload.kind, &settings, now)? => task,
            _ => {
                skipped.push(BulkSkipped {
                    task_id: task_id.clone(),
                    reason: SkipReason::NotEligible,
                });
                continue;
            }
        };
        if &task.revision != revision {
            skipped.push(BulkSkipped {
                task_id: task_id.clone(),
                reason: SkipReason::Stale,
            });
            continue;
        }
        let (clock, snapshot) = formulation::release(
            &TaskClock::from_task(task).map_err(clock_error)?,
            &settings,
            now,
        );
        let mut moved = Task {
            state: TaskState::Someday,
            revision: Counter::from(clock.revision),
            updated_at: inputs.now.clone(),
            ..task.clone()
        };
        clock.write_clock_fields(&mut moved).map_err(clock_error)?;
        receipts.push(ReviewReceipt {
            bulk_id: Some(bulk_id.clone()),
            ..receipt_for(&moved, ReceiptKind::Someday, ReceiptSource::Release, now)?
        });
        let private = if inputs.private_review() {
            Some(ReleasedPrivate {
                previous_state: releasable(payload.kind),
                clock_before: snapshot.as_ref().map(stored_clock).transpose()?,
                local_receipt_replaced: inputs
                    .local_review()
                    .then(|| {
                        read_set
                            .receipts
                            .iter()
                            .find(|receipt| {
                                receipt.task_id == task.id && receipt.kind == ReceiptKind::Someday
                            })
                            .map(|receipt| ReplacedReceipt {
                                receipt: receipt.clone(),
                                task_was_unchanged: receipt.task_revision == task.revision,
                            })
                    })
                    .flatten(),
            })
        } else {
            None
        };
        released.push(BulkReleased {
            task_id: task_id.clone(),
            revision_after: moved.revision.clone(),
            private,
        });
        tasks.push(moved);
    }
    let result = ResultRefs {
        released: released
            .iter()
            .map(|item| ReleasedItem {
                task_id: item.task_id.clone(),
                revision_after: item.revision_after.clone(),
            })
            .collect(),
        skipped: skipped.clone(),
        ..ResultRefs::default()
    };
    let release = BulkRelease {
        id: bulk_id,
        kind: payload.kind,
        session_id: known_session(read_set, payload.session_id.as_ref()),
        created_at: inputs.now.clone(),
        undone_at: None,
        released,
        skipped,
        undo: None,
    };
    let mut changes: Vec<DomainChange> = tasks
        .into_iter()
        .map(|task| upsert(Record::Task(task)))
        .collect();
    changes.extend(
        receipts
            .into_iter()
            .map(|receipt| upsert(Record::ReviewReceipt(receipt))),
    );
    changes.push(upsert(Record::ReviewBulkRelease(release)));
    Ok(applied(changes, result))
}

// ======================================================================= bulk undo

/// Only absent private facts qualify for deferred native Undo. Present malformed
/// snapshots are validated by the ordinary restoration path instead.
fn private_missing(entity: EntityType, id: &str, field: &str) -> DomainError {
    DomainError {
        field: Some(field.to_owned()),
        ..DomainError::missing(entity, key_of(id))
    }
}

fn bulk_undo(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &crate::types::ReviewInputs<'_>,
    now: UtcInstant,
) -> Result<ChangeSet, DomainError> {
    let bulk_id = BulkId::parse(command.entity_id.as_str())?;
    let release = read_set
        .bulk_releases
        .get(&bulk_id)
        .ok_or_else(|| not_found(EntityType::ReviewBulkRelease, bulk_id.as_str()))?;
    if release.undone_at.is_some()
        && let Some(stored) = &release.undo
    {
        // Answers its stored result at any age and changes nothing.
        return Ok(ChangeSet {
            result: ResultRefs {
                bulk_undo: Some(stored.clone()),
                ..ResultRefs::default()
            },
            ..ChangeSet::no_op()
        });
    }
    if release.undone_at.is_some() {
        return Err(DomainError::field(Reason::InvalidValue, "undo"));
    }
    let created = parse_instant(&release.created_at, "created_at").map_err(clock_error)?;
    let unavailable = || {
        refuse(
            Reason::UndoUnavailable,
            EntityType::ReviewBulkRelease,
            bulk_id.as_str(),
        )
    };
    if now >= undo_deadline(created) {
        return Err(unavailable());
    }
    // Publicly stale/missing tasks are skips, but they do not prove the
    // source's private snapshot was retained. Never complete the bulk locally
    // while any required private fact is absent, including an all-skipped bulk.
    let mut missing = None;
    for item in &release.released {
        let task = read_set
            .tasks
            .get(&item.task_id)
            .filter(|task| task.revision == item.revision_after);
        if let Some(task) = task {
            TaskClock::from_task(task).map_err(clock_error)?;
        }
        match &item.private {
            None if inputs.private_review() => return Err(unavailable()),
            None => {
                missing.get_or_insert("released_private");
            }
            Some(private)
                if private.previous_state == OpenList::Next && private.clock_before.is_none() =>
            {
                if inputs.private_review() {
                    return Err(unavailable());
                }
                missing.get_or_insert("clock_before");
            }
            _ => {}
        }
        if let Some(private) = &item.private
            && (private.previous_state != releasable(release.kind)
                || (private.previous_state != OpenList::Next && private.clock_before.is_some()))
        {
            return Err(DomainError::field(Reason::InvalidValue, "released_private"));
        }
        if inputs.local_review()
            && let Some(previous) = item
                .private
                .as_ref()
                .and_then(|private| private.local_receipt_replaced.as_ref())
            && (previous.receipt.task_id != item.task_id
                || previous.receipt.kind != ReceiptKind::Someday)
        {
            return Err(DomainError::field(Reason::InvalidValue, "receipt_replaced"));
        }
        if let Some(clock) = item
            .private
            .as_ref()
            .and_then(|private| private.clock_before.as_ref())
        {
            released_clock(clock)?;
        }
    }
    if let Some(field) = missing {
        return Err(private_missing(
            EntityType::ReviewBulkRelease,
            bulk_id.as_str(),
            field,
        ));
    }
    let mut restored = Vec::new();
    let mut skipped = Vec::new();
    let mut changes = Vec::new();
    for item in &release.released {
        let current = read_set
            .tasks
            .get(&item.task_id)
            .filter(|task| task.revision == item.revision_after);
        let (Some(task), Some(private)) = (current, &item.private) else {
            skipped.push(BulkUndoSkipped {
                task_id: item.task_id.clone(),
                reason: UndoSkipReason::Stale,
            });
            continue;
        };
        let stored = private
            .clock_before
            .as_ref()
            .map(released_clock)
            .transpose()?;
        let clock = formulation::undo_release(
            &TaskClock::from_task(task).map_err(clock_error)?,
            private.previous_state.task_state(),
            stored.as_ref(),
        )
        .map_err(clock_error)?;
        let mut back = Task {
            state: private.previous_state.task_state(),
            revision: Counter::from(clock.revision),
            updated_at: inputs.now.clone(),
            ..task.clone()
        };
        clock.write_clock_fields(&mut back).map_err(clock_error)?;
        let restored_revision = back.revision.clone();
        changes.push(upsert(Record::Task(back)));
        // The release receipt goes only when this release wrote it (E5).
        if read_set.receipts.iter().any(|receipt| {
            receipt.task_id == item.task_id
                && receipt.kind == ReceiptKind::Someday
                && receipt.bulk_id.as_ref() == Some(&bulk_id)
        }) {
            if inputs.local_review()
                && let Some(previous) = &private.local_receipt_replaced
            {
                let mut receipt = previous.receipt.clone();
                if previous.task_was_unchanged {
                    receipt.task_revision = restored_revision.clone();
                }
                changes.push(upsert(Record::ReviewReceipt(receipt)));
            } else {
                changes.push(tombstone(
                    EntityType::ReviewReceipt,
                    vec![
                        item.task_id.as_str().to_owned(),
                        ReceiptKind::Someday.as_str().to_owned(),
                    ],
                ));
            }
        }
        restored.push(item.task_id.clone());
    }
    let undo = BulkUndoResult { restored, skipped };
    changes.push(upsert(Record::ReviewBulkRelease(BulkRelease {
        undone_at: Some(inputs.now.clone()),
        undo: Some(undo.clone()),
        released: if inputs.local_review() {
            release.released.iter().map(BulkReleased::public).collect()
        } else {
            release.released.clone()
        },
        ..release.clone()
    })));
    Ok(applied(
        changes,
        ResultRefs {
            bulk_undo: Some(undo),
            ..ResultRefs::default()
        },
    ))
}
