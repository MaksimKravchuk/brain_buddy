//! Children rules (026 PR-10): subtask create/update/transition and comment
//! create/update. Children stay attached to an existing parent and keep their
//! supported order under accepted commands.
//!
//! The server is normative: `TaskService.create_subtask`, `update_subtask`,
//! `transition_subtask`, `create_comment` and `update_comment`
//! (`backend/app/modules/tasks/service.py`). The Swift reducer
//! (`Reducer+Children.swift`) differs in four places that are deliberately not
//! ported: it trims a subtask title and refuses a blank one, it refuses an edit
//! that changes nothing (`nothingToChange`), it has no child revisions, and it
//! leaves a comment's author unknown. Here:
//!
//! * a child is created under any existing parent, open or terminal; parent
//!   state and the parent row never change (no revision, no `updated_at`);
//! * a subtask is appended with `order_key = max(siblings) + 1` (0 for the first
//!   one); there is no reorder command;
//! * update and transition check the **child's** revision (a precondition naming
//!   the child), then bump it by one; an update that changes nothing, or omits
//!   the title, still bumps it, as the server does;
//! * a subtask title and a comment body are stored verbatim (no trimming);
//! * a transition to the current state is refused; any other state is allowed;
//! * a comment's author and `created_at` come from the inputs, an edit sets
//!   `edited_at` to `inputs.now` and keeps the author.
//!
//! Pure: no clock, identifiers or I/O beyond the arguments.

use crate::types::{
    ChangeOutcome, ChangeSet, ChildAction, ChildState, Command, Comment, CommentId, CommentWrite,
    Counter, DomainChange, DomainCommand, DomainError, EntityType, ExecutionInputs, ReadSet,
    Reason, Record, RecordKey, ResultRefs, Subtask, SubtaskCreate, SubtaskId, SubtaskTransition,
    SubtaskUpdate, TaskId,
};

/// Whether `command` belongs to this family.
pub fn handles(command: &Command) -> bool {
    matches!(
        command,
        Command::SubtaskCreate(_)
            | Command::SubtaskUpdate(_)
            | Command::SubtaskTransition(_)
            | Command::CommentCreate(_)
            | Command::CommentUpdate(_)
    )
}

/// Decides one child command against the protected read set.
///
/// A command of another family is [`Reason::InvalidPayload`]: dispatch is the
/// caller's job.
pub fn decide(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    let record = match &command.command {
        Command::SubtaskCreate(create) => create_subtask(read_set, command, create)?,
        Command::SubtaskUpdate(update) => update_subtask(read_set, command, update)?,
        Command::SubtaskTransition(transition) => {
            transition_subtask(read_set, command, transition)?
        }
        Command::CommentCreate(create) => create_comment(read_set, command, create, inputs)?,
        Command::CommentUpdate(update) => update_comment(read_set, command, update, inputs)?,
        _ => return Err(DomainError::new(Reason::InvalidPayload)),
    };
    Ok(ChangeSet {
        outcome: ChangeOutcome::Applied,
        changes: vec![DomainChange::Upsert(record)],
        result: ResultRefs::default(),
        effects: Vec::new(),
    })
}

// ------------------------------------------------------------------- projections

/// A task's subtasks in their supported order: `(order_key, id)`.
pub fn ordered_subtasks<'a>(read_set: &'a ReadSet, task_id: &TaskId) -> Vec<&'a Subtask> {
    let mut subtasks: Vec<&Subtask> = read_set
        .subtasks
        .values()
        .filter(|subtask| &subtask.task_id == task_id)
        .collect();
    subtasks.sort_by(|a, b| {
        counter_value(&a.order_key)
            .cmp(&counter_value(&b.order_key))
            .then_with(|| a.id.as_str().cmp(b.id.as_str()))
    });
    subtasks
}

/// A task's comments in their supported order: `(created_at, id)`.
pub fn ordered_comments<'a>(read_set: &'a ReadSet, task_id: &TaskId) -> Vec<&'a Comment> {
    let mut comments: Vec<&Comment> = read_set
        .comments
        .values()
        .filter(|comment| &comment.task_id == task_id)
        .collect();
    comments.sort_by(|a, b| {
        instant_seconds(a.created_at.as_str())
            .cmp(&instant_seconds(b.created_at.as_str()))
            .then_with(|| a.id.as_str().cmp(b.id.as_str()))
    });
    comments
}

/// Unsortable or oversized counters sort last rather than panicking.
fn counter_value(counter: &Counter) -> u64 {
    counter.to_u64().unwrap_or(u64::MAX)
}

/// Python sorts aware datetimes; an offset is honoured, an unparsable value
/// cannot occur (the wire type is RFC 3339) and sorts first.
fn instant_seconds(value: &str) -> (i64, i32) {
    value
        .parse::<jiff::Timestamp>()
        .map(|t| (t.as_second(), t.subsec_nanosecond()))
        .unwrap_or((i64::MIN, 0))
}

// ---------------------------------------------------------------------- subtasks

fn create_subtask(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &SubtaskCreate,
) -> Result<Record, DomainError> {
    require_parent(read_set, &payload.task_id)?;
    let id = SubtaskId::parse_new(command.entity_id.as_str())?;
    if read_set.subtasks.contains_key(&id) {
        return Err(already_exists(EntityType::Subtask, id.as_str()));
    }
    let order_key = next_order_key(read_set, &payload.task_id)?;
    Ok(Record::Subtask(Subtask {
        id,
        task_id: payload.task_id.clone(),
        title: payload.title.clone(),
        state: ChildState::Open,
        order_key,
        revision: Counter::from(1),
    }))
}

fn update_subtask(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &SubtaskUpdate,
) -> Result<Record, DomainError> {
    let current = load_subtask(read_set, command, &payload.task_id)?;
    let revision = next_revision(&current.revision)?;
    let title = payload
        .title
        .clone()
        .unwrap_or_else(|| current.title.clone());
    Ok(Record::Subtask(Subtask {
        title,
        revision,
        ..current.clone()
    }))
}

fn transition_subtask(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &SubtaskTransition,
) -> Result<Record, DomainError> {
    let current = load_subtask(read_set, command, &payload.task_id)?;
    let target = match payload.action {
        ChildAction::Complete => ChildState::Completed,
        ChildAction::Cancel => ChildState::Cancelled,
        ChildAction::Reopen => ChildState::Open,
    };
    if current.state == target {
        return Err(DomainError::about(
            Reason::SubtaskAlreadyInState,
            EntityType::Subtask,
            key(current.id.as_str()),
        ));
    }
    Ok(Record::Subtask(Subtask {
        state: target,
        revision: next_revision(&current.revision)?,
        ..current.clone()
    }))
}

/// Parent, child and revision, in the server's order: a missing parent, then a
/// missing child (or one under another parent), then a stale revision.
fn load_subtask<'a>(
    read_set: &'a ReadSet,
    command: &DomainCommand,
    task_id: &TaskId,
) -> Result<&'a Subtask, DomainError> {
    require_parent(read_set, task_id)?;
    let id = SubtaskId::parse(command.entity_id.as_str())?;
    let current = read_set
        .subtasks
        .get(&id)
        .filter(|subtask| &subtask.task_id == task_id)
        .ok_or_else(|| not_found(EntityType::Subtask, id.as_str()))?;
    check_revision(
        command,
        EntityType::Subtask,
        current.id.as_str(),
        &current.revision,
    )?;
    Ok(current)
}

/// `max(order_key) + 1` over the parent's subtasks, 0 for the first.
fn next_order_key(read_set: &ReadSet, task_id: &TaskId) -> Result<Counter, DomainError> {
    let mut next: u64 = 0;
    for subtask in read_set.subtasks.values() {
        if &subtask.task_id == task_id {
            let value = subtask
                .order_key
                .to_u64()
                .ok_or_else(|| DomainError::field(Reason::InvalidValue, "order_key"))?;
            next = next.max(
                value
                    .checked_add(1)
                    .ok_or_else(|| DomainError::field(Reason::InvalidValue, "order_key"))?,
            );
        }
    }
    Ok(Counter::from(next))
}

// ---------------------------------------------------------------------- comments

fn create_comment(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &CommentWrite,
    inputs: &ExecutionInputs,
) -> Result<Record, DomainError> {
    require_parent(read_set, &payload.task_id)?;
    let id = CommentId::parse_new(command.entity_id.as_str())?;
    if read_set.comments.contains_key(&id) {
        return Err(already_exists(EntityType::Comment, id.as_str()));
    }
    Ok(Record::Comment(Comment {
        id,
        task_id: payload.task_id.clone(),
        body: payload.body.clone(),
        actor_id: inputs.actor_id.clone(),
        created_at: inputs.now.clone(),
        edited_at: None,
        revision: Counter::from(1),
    }))
}

fn update_comment(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &CommentWrite,
    inputs: &ExecutionInputs,
) -> Result<Record, DomainError> {
    require_parent(read_set, &payload.task_id)?;
    let id = CommentId::parse(command.entity_id.as_str())?;
    let current = read_set
        .comments
        .get(&id)
        .filter(|comment| comment.task_id == payload.task_id)
        .ok_or_else(|| not_found(EntityType::Comment, id.as_str()))?;
    check_revision(
        command,
        EntityType::Comment,
        current.id.as_str(),
        &current.revision,
    )?;
    Ok(Record::Comment(Comment {
        body: payload.body.clone(),
        edited_at: Some(inputs.now.clone()),
        revision: next_revision(&current.revision)?,
        ..current.clone()
    }))
}

// ------------------------------------------------------------------------ shared

fn key(id: &str) -> RecordKey {
    vec![id.to_owned()]
}

fn not_found(entity_type: EntityType, id: &str) -> DomainError {
    DomainError::about(Reason::NotFound, entity_type, key(id))
}

fn already_exists(entity_type: EntityType, id: &str) -> DomainError {
    DomainError::about(Reason::IdAlreadyExists, entity_type, key(id))
}

/// `get_task`: the parent must exist for the owner, in any state.
fn require_parent(read_set: &ReadSet, task_id: &TaskId) -> Result<(), DomainError> {
    if read_set.tasks.contains_key(task_id) {
        Ok(())
    } else {
        Err(not_found(EntityType::Task, task_id.as_str()))
    }
}

/// The child's own revision check. The command must carry at least one
/// precondition naming this child (the server requires `expected_revision`);
/// the parent task's revision is never consulted.
fn check_revision(
    command: &DomainCommand,
    entity_type: EntityType,
    id: &str,
    current: &Counter,
) -> Result<(), DomainError> {
    let mut checked = false;
    for check in &command.preconditions {
        if check.entity_type == entity_type && check.entity_id.as_str() == id {
            checked = true;
            if &check.edit_revision != current {
                return Err(DomainError::stale(entity_type, key(id), current.clone()));
            }
        }
    }
    if checked {
        Ok(())
    } else {
        Err(DomainError::field(Reason::InvalidPayload, "preconditions"))
    }
}

fn next_revision(current: &Counter) -> Result<Counter, DomainError> {
    current
        .to_u64()
        .and_then(|value| value.checked_add(1))
        .map(Counter::from)
        .ok_or_else(|| DomainError::field(Reason::InvalidValue, "revision"))
}
