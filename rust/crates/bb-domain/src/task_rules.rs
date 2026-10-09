//! The task lifecycle rule family (026 PR-07): `task.create`, `task.update`
//! and `task.transition`.
//!
//! `decide(read_set, command, inputs)` is pure: it reads only the protected
//! [`ReadSet`], the typed [`DomainCommand`] and the explicit
//! [`ExecutionInputs`] (time is `inputs.now`, the new task's ID is the
//! command's `entity_id`, a formulation ID the request did not send is the
//! first of `inputs.allocated_ids`) and returns the records it changes in
//! application order, or a typed refusal.
//!
//! The server is normative (`TaskService.create_task_result`,
//! `update_task_result`, `_transitioned`, `_clock_after_edit` and
//! `backend/app/modules/tasks/formulation.py`); the Swift `GTDReducer` differs
//! only where noted. The formulation clock is decided by [`crate::formulation`]
//! and only its stored facts are written back, so a task write owns state,
//! title, revision and timestamps and the clock rule owns the rest.
//!
//! | Command | Rule |
//! | --- | --- |
//! | `task.create` | absent ID; project then tags are checked active; Waiting needs a trimmed `waiting_for` (dropped for the other lists); `source_capture_ids` are refused (they need Capture validation the server does before this rule); order key is one past the list's last; a task created in Next starts its formulation |
//! | `task.update` | revision check; omitted keeps, `null` clears; `waiting_for` only on Waiting tasks and never blank; the project a task already has is not re-validated (ADR-0020), the resulting tags are; always bumps the revision, even when nothing changes; in Next a substantive title restarts the formulation and a due-date change raises the task floor |
//! | `task.transition` | revision check; `complete`/`cancel` need an open task, `reopen` a terminal one with an open destination, `move` an open task and a different open destination; Waiting needs a trimmed `waiting_for`; leaving Next closes the formulation, entering Next starts one, leaving Someday drops the park marker; a parked task returning to Next stamps its park acknowledgement |

use crate::calendar::{CalendarDay, UtcInstant};
use crate::formulation::{self, FormulationError, OwnerClockSettings, TaskClock};
use crate::normalization as norm;
use crate::types::{
    ChangeOutcome, ChangeSet, Command, Counter, DomainChange, DomainCommand, DomainError,
    EntityType, ExecutionInputs, FormulationId, NewFormulationId, OpenList, ParkAck, Patch,
    ProjectId, ProjectState, ReadSet, Reason, Record, ResultRefs, TagChanges, TagId, TagState,
    Task, TaskAction, TaskCreate, TaskId, TaskState, TaskTransition, TaskUpdate, WaitingFor,
};

/// Whether this family decides `command`.
#[must_use]
pub fn handles(command: &Command) -> bool {
    matches!(
        command,
        Command::TaskCreate(_) | Command::TaskUpdate(_) | Command::TaskTransition(_)
    )
}

/// Decides one task lifecycle command against the protected read set.
///
/// A command of another family is refused as [`Reason::InvalidPayload`]
/// (`field = "type"`); the dispatcher asks [`handles`] first.
pub fn decide(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    match &command.command {
        Command::TaskCreate(payload) => task_create(read_set, command, payload, inputs),
        Command::TaskUpdate(payload) => task_update(read_set, command, payload, inputs),
        Command::TaskTransition(payload) => task_transition(read_set, command, payload, inputs),
        _ => Err(DomainError::field(Reason::InvalidPayload, "type")),
    }
}

// --------------------------------------------------------------------- helpers

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

/// A refusal about one record, naming the request field it concerns.
fn refuse(reason: Reason, entity_type: EntityType, id: &str, field: &str) -> DomainError {
    DomainError {
        field: Some(field.to_owned()),
        ..DomainError::about(reason, entity_type, key_of(id))
    }
}

fn not_found(entity_type: EntityType, id: &str) -> DomainError {
    DomainError::about(Reason::NotFound, entity_type, key_of(id))
}

/// `current + 1`; a counter beyond `u64` is not representable.
fn next_counter(counter: &Counter, field: &str) -> Result<Counter, DomainError> {
    counter
        .to_u64()
        .and_then(|value| value.checked_add(1))
        .map(Counter::from)
        .ok_or_else(|| DomainError::field(Reason::InvalidValue, field))
}

/// The revision check of a revision-required command (`_assert_current`).
/// The check names the target; a command without one is malformed.
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

fn existing_task<'a>(read_set: &'a ReadSet, id: &TaskId) -> Result<&'a Task, DomainError> {
    read_set
        .tasks
        .get(id)
        .ok_or_else(|| not_found(EntityType::Task, id.as_str()))
}

/// `TaskService._waiting_for`: stripped (Python `str.strip()`) and non-blank.
fn required_waiting_for(raw: Option<&WaitingFor>) -> Result<WaitingFor, DomainError> {
    let stripped = norm::strip(raw.map_or("", WaitingFor::as_str));
    if stripped.is_empty() {
        return Err(DomainError::field(
            Reason::WaitingForRequired,
            "waiting_for",
        ));
    }
    WaitingFor::new(stripped).map_err(|_| DomainError::field(Reason::TextLength, "waiting_for"))
}

fn patched<T: Clone>(current: &Option<T>, patch: &Patch<T>) -> Option<T> {
    match patch {
        Patch::Unchanged => current.clone(),
        Patch::Clear => None,
        Patch::Set(value) => Some(value.clone()),
    }
}

// ----------------------------------------------------------------- clock bridge

fn clock_error(error: FormulationError) -> DomainError {
    match error {
        FormulationError::UnknownTimeZone(_) => {
            DomainError::field(Reason::InvalidTimeZone, "time_zone")
        }
        FormulationError::InvalidField(name) => DomainError::field(Reason::InvalidValue, name),
        FormulationError::MissingInput(name) => {
            DomainError::field(Reason::FormulationIdRequired, name)
        }
        _ => DomainError::new(Reason::InvalidValue),
    }
}

fn instant_of(inputs: &ExecutionInputs) -> Result<UtcInstant, DomainError> {
    UtcInstant::parse_rfc3339(inputs.now.as_str())
        .map_err(|_| DomainError::field(Reason::InvalidValue, "now"))
}

/// The owner's clock inputs: the stored settings, or the server's defaults for
/// an owner that has none (14 days, UTC, never activated).
fn clock_settings(read_set: &ReadSet) -> Result<OwnerClockSettings, DomainError> {
    match &read_set.settings {
        Some(settings) => OwnerClockSettings::from_review_settings(settings),
        None => OwnerClockSettings::new(14, "UTC", None, None),
    }
    .map_err(clock_error)
}

/// `_formulation_id`: the client's ID when it sent one, else the first ID the
/// execution allocated for this command.
fn formulation_id(
    requested: Option<&NewFormulationId>,
    inputs: &ExecutionInputs,
) -> Result<FormulationId, DomainError> {
    if let Some(id) = requested {
        return Ok(id.clone().into());
    }
    let allocated = inputs
        .allocated_ids
        .first()
        .ok_or_else(|| DomainError::field(Reason::FormulationIdRequired, "new_formulation_id"))?;
    FormulationId::parse(allocated.as_str())
}

fn day_of(task: &Task) -> Result<Option<CalendarDay>, DomainError> {
    task.due_date
        .as_ref()
        .map(|day| {
            CalendarDay::parse_iso(day.as_str())
                .map_err(|_| DomainError::field(Reason::InvalidValue, "due_date"))
        })
        .transpose()
}

// ------------------------------------------------------------------- references

/// `TaskService._assert_active_references` for the references a command sets.
///
/// `current` is the project the task already belongs to: a membership the task
/// has is never re-validated, so an archived project's tasks stay editable
/// (ADR-0020). The project is checked first, then tag duplicates, then each
/// tag in order.
fn check_references(
    read_set: &ReadSet,
    project: Option<&ProjectId>,
    tags: Option<&[TagId]>,
    current: Option<&ProjectId>,
) -> Result<(), DomainError> {
    if let Some(id) = project.filter(|id| Some(*id) != current) {
        let record = read_set
            .projects
            .get(id)
            .ok_or_else(|| not_found(EntityType::Project, id.as_str()))?;
        if record.state != ProjectState::Active {
            return Err(refuse(
                Reason::ProjectNotActive,
                EntityType::Project,
                id.as_str(),
                "project_id",
            ));
        }
    }
    let Some(tags) = tags else { return Ok(()) };
    let mut seen = std::collections::HashSet::new();
    if !tags.iter().all(|id| seen.insert(id)) {
        return Err(DomainError::field(Reason::DuplicateTag, "tag_ids"));
    }
    tags.iter().try_for_each(|id| {
        let record = read_set
            .tags
            .get(id)
            .ok_or_else(|| not_found(EntityType::Tag, id.as_str()))?;
        if record.state == TagState::Active {
            Ok(())
        } else {
            Err(refuse(
                Reason::TagNotActive,
                EntityType::Tag,
                id.as_str(),
                "tag_ids",
            ))
        }
    })
}

/// The membership after explicit changes: existing order is kept, removals
/// are dropped, additions the task does not hold follow in request order.
/// Validation is [`check_references`]' job, over the whole result.
fn membership_after(current: &[TagId], changes: &TagChanges) -> Vec<TagId> {
    current
        .iter()
        .filter(|id| !changes.remove_tag_ids.contains(id))
        .chain(
            changes
                .add_tag_ids
                .iter()
                .filter(|id| !current.contains(id)),
        )
        .cloned()
        .collect()
}

// ----------------------------------------------------------------------- create

fn task_create(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &TaskCreate,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    // A created task carries the native shape; legacy and alias IDs are only
    // valid as references to records that already exist.
    let id = TaskId::parse_new(command.entity_id.as_str())?;
    if read_set.tasks.contains_key(&id) {
        return Err(refuse(
            Reason::IdAlreadyExists,
            EntityType::Task,
            id.as_str(),
            "entity_id",
        ));
    }
    check_references(
        read_set,
        payload.project_id.as_ref(),
        Some(&payload.tag_ids),
        None,
    )?;
    let state = payload.state.task_state();
    let waiting_for = if payload.state == OpenList::Waiting {
        Some(required_waiting_for(payload.waiting_for.as_ref())?)
    } else {
        None
    };
    // The server refuses these before the task exists: a source Capture needs
    // an owner-scoped Capture lookup this rule has no read set for.
    if !payload.source_capture_ids.is_empty() {
        return Err(DomainError::field(
            Reason::InvalidValue,
            "source_capture_ids",
        ));
    }
    let order_key = next_order_key(read_set, state)?;
    let mut task = Task {
        id,
        title: payload.title.clone(),
        details: payload.details.clone(),
        state,
        project_id: payload.project_id.clone(),
        tag_ids: payload.tag_ids.clone(),
        due_date: payload.due_date.clone(),
        priority: payload.priority,
        waiting_since: waiting_for.as_ref().map(|_| inputs.now.clone()),
        waiting_for,
        order_key,
        source_capture_ids: Vec::new(),
        created_at: inputs.now.clone(),
        updated_at: inputs.now.clone(),
        completed_at: None,
        cancelled_at: None,
        revision: Counter::from(1),
        consecutive_stalled_formulations: 0,
        formulation: None,
        parked: None,
    };
    // A task created in Next starts its first formulation (FR-001).
    if state == TaskState::Next {
        let started = formulation::start_formulation(
            &TaskClock::from_task(&task).map_err(clock_error)?,
            formulation_id(payload.new_formulation_id.as_ref(), inputs)?.as_str(),
            instant_of(inputs)?,
        );
        started.write_clock_fields(&mut task).map_err(clock_error)?;
    }
    Ok(applied(vec![upsert(Record::Task(task))]))
}

/// `next_order_key`: one past the highest key of the list, `0` for an empty one.
fn next_order_key(read_set: &ReadSet, state: TaskState) -> Result<Counter, DomainError> {
    let mut highest: Option<u64> = None;
    for task in read_set.tasks.values().filter(|task| task.state == state) {
        let key = task
            .order_key
            .to_u64()
            .ok_or_else(|| DomainError::field(Reason::InvalidValue, "order_key"))?;
        highest = Some(highest.map_or(key, |current| current.max(key)));
    }
    match highest {
        None => Ok(Counter::from(0)),
        Some(key) => next_counter(&Counter::from(key), "order_key"),
    }
}

// ----------------------------------------------------------------------- update

fn task_update(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &TaskUpdate,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    let id = TaskId::parse(command.entity_id.as_str())?;
    let task = existing_task(read_set, &id)?;
    check_revision(command, EntityType::Task, &task.revision)?;
    // Title and priority cannot be cleared: the payload type refuses `null`.
    let waiting_for = match &payload.waiting_for {
        Patch::Unchanged => task.waiting_for.clone(),
        edit => {
            if task.state != TaskState::Waiting {
                return Err(DomainError::field(
                    Reason::WaitingForOnlyOnWaitingTasks,
                    "waiting_for",
                ));
            }
            let value = match edit {
                Patch::Set(value) => Some(value),
                _ => None,
            };
            Some(required_waiting_for(value)?)
        }
    };
    let project_id = patched(&task.project_id, &payload.project_id);
    let tag_ids = payload.tag_changes.as_ref().map_or_else(
        || task.tag_ids.clone(),
        |changes| membership_after(&task.tag_ids, changes),
    );
    // The server validates the whole resulting membership on every edit.
    check_references(
        read_set,
        project_id.as_ref(),
        Some(&tag_ids),
        task.project_id.as_ref(),
    )?;
    let mut updated = Task {
        title: payload.title.clone().unwrap_or_else(|| task.title.clone()),
        details: patched(&task.details, &payload.details),
        project_id,
        tag_ids,
        due_date: patched(&task.due_date, &payload.due_date),
        priority: payload.priority.unwrap_or(task.priority),
        waiting_for,
        updated_at: inputs.now.clone(),
        revision: next_counter(&task.revision, "revision")?,
        ..task.clone()
    };
    if task.state == TaskState::Next {
        clock_after_edit(read_set, task, &mut updated, payload, inputs)?;
    }
    Ok(applied(vec![upsert(Record::Task(updated))]))
}

/// PATCH in Next: a substantive title restarts the formulation, a due date
/// set, moved or removed raises the task floor to `max(existing, now + 7 d)`.
/// Notes, tags, project, priority and waiting-for leave the clock alone.
fn clock_after_edit(
    read_set: &ReadSet,
    before: &Task,
    after: &mut Task,
    payload: &TaskUpdate,
    inputs: &ExecutionInputs,
) -> Result<(), DomainError> {
    let now = instant_of(inputs)?;
    let mut clock = TaskClock::from_task(before).map_err(clock_error)?;
    if after.title != before.title
        && formulation::is_substantive(before.title.as_str(), after.title.as_str())
    {
        let restarted = formulation_id(payload.new_formulation_id.as_ref(), inputs)?;
        clock = formulation::change_title(
            &clock,
            after.title.as_str(),
            &clock_settings(read_set)?,
            now,
            restarted.as_str(),
        );
    }
    if after.due_date != before.due_date {
        clock = formulation::change_due_date(&clock, day_of(after)?, now);
    }
    clock.write_clock_fields(after).map_err(clock_error)
}

// ------------------------------------------------------------------- transition

fn task_transition(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &TaskTransition,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    let id = TaskId::parse(command.entity_id.as_str())?;
    let task = existing_task(read_set, &id)?;
    check_revision(command, EntityType::Task, &task.revision)?;
    let mut updated = Task {
        updated_at: inputs.now.clone(),
        revision: next_counter(&task.revision, "revision")?,
        ..task.clone()
    };
    match payload.action {
        TaskAction::Complete => close(task, &mut updated, TaskState::Completed, inputs)?,
        TaskAction::Cancel => close(task, &mut updated, TaskState::Cancelled, inputs)?,
        TaskAction::Reopen => {
            let list = payload
                .to_state
                .ok_or_else(|| DomainError::field(Reason::ReopenRequiresDestination, "to_state"))?;
            if task.state.is_open() {
                return Err(DomainError::field(Reason::TaskNotClosed, "action"));
            }
            enter(&mut updated, list, payload.waiting_for.as_ref(), inputs)?;
            updated.completed_at = None;
            updated.cancelled_at = None;
        }
        TaskAction::Move => {
            let list = payload
                .to_state
                .ok_or_else(|| DomainError::field(Reason::MoveRequiresDestination, "to_state"))?;
            if !task.state.is_open() {
                return Err(DomainError::field(Reason::TaskNotOpen, "action"));
            }
            if task.state == list.task_state() {
                return Err(DomainError::field(
                    Reason::MoveRequiresDifferentList,
                    "to_state",
                ));
            }
            enter(&mut updated, list, payload.waiting_for.as_ref(), inputs)?;
        }
    }
    let now = instant_of(inputs)?;
    let to_next = updated.state == TaskState::Next;
    let new_id = if to_next {
        Some(formulation_id(payload.new_formulation_id.as_ref(), inputs)?)
    } else {
        None
    };
    TaskClock::from_task(task)
        .and_then(|clock| {
            formulation::move_to(
                &clock,
                updated.state,
                &clock_settings(read_set)
                    .map_err(|_| FormulationError::InvalidField("settings"))?,
                now,
                new_id.as_ref().map(FormulationId::as_str),
            )
        })
        .and_then(|clock| clock.write_clock_fields(&mut updated))
        .map_err(clock_error)?;
    let mut changes = vec![upsert(Record::Task(updated.clone()))];
    changes.extend(returned_park_ack(read_set, task, &updated, inputs));
    Ok(applied(changes))
}

/// `complete` / `cancel`: only an open task closes; the waiting note goes.
fn close(
    task: &Task,
    updated: &mut Task,
    terminal: TaskState,
    inputs: &ExecutionInputs,
) -> Result<(), DomainError> {
    if !task.state.is_open() {
        return Err(DomainError::field(Reason::TaskNotOpen, "action"));
    }
    let stamp = Some(inputs.now.clone());
    let completing = terminal == TaskState::Completed;
    updated.state = terminal;
    updated.completed_at = if completing { stamp.clone() } else { None };
    updated.cancelled_at = if completing { None } else { stamp };
    updated.waiting_for = None;
    updated.waiting_since = None;
    Ok(())
}

/// Puts `updated` in the open `list`: Waiting needs a non-blank note and
/// starts waiting now; any other list drops a supplied note.
fn enter(
    updated: &mut Task,
    list: OpenList,
    waiting_for: Option<&WaitingFor>,
    inputs: &ExecutionInputs,
) -> Result<(), DomainError> {
    let note = if list == OpenList::Waiting {
        Some(required_waiting_for(waiting_for)?)
    } else {
        None
    };
    updated.state = list.task_state();
    updated.waiting_since = note.as_ref().map(|_| inputs.now.clone());
    updated.waiting_for = note;
    Ok(())
}

/// `_note_park_return`: a parked task moved from Someday back to Next stamps
/// `returned_at` on its park acknowledgement, in the same change set. A missing
/// acknowledgement writes nothing (its source would be invented).
fn returned_park_ack(
    read_set: &ReadSet,
    before: &Task,
    after: &Task,
    inputs: &ExecutionInputs,
) -> Option<DomainChange> {
    let parked = before.parked.as_ref()?;
    if before.state != TaskState::Someday || after.state != TaskState::Next {
        return None;
    }
    let ack = read_set
        .park_acks
        .iter()
        .find(|ack| ack.task_id == before.id && ack.formulation_id == parked.formulation_id)?;
    Some(upsert(Record::ReviewParkAck(ParkAck {
        returned_at: Some(inputs.now.clone()),
        ..ack.clone()
    })))
}
