//! The organization rule family (026 PR-08): projects, tags and explicit task
//! tag membership.
//!
//! `decide(read_set, command, inputs)` is pure: it reads only the protected
//! [`ReadSet`], the typed [`DomainCommand`] and the explicit
//! [`ExecutionInputs`] (time comes from `inputs.now`, the new record's ID from
//! the command's `entity_id`) and returns the records it changes in
//! application order, or a typed refusal.
//!
//! The server is normative (`backend/app/modules/tasks/service.py`); the
//! Swift reducer (`Reducer+Organize.swift`) differs only where noted. Names
//! are stored in the server's display form and keyed with the shared
//! normalization; uniqueness is among **active** records of one scope.
//!
//! | Command | Rule |
//! | --- | --- |
//! | `project.create` | absent ID, display name, unique among active projects |
//! | `project.update` | revision check, rename/recolour/outcome (archived allowed), uniqueness only while active; always bumps the revision |
//! | `project.archive` | revision check; keeps every task; a repeat only bumps the revision |
//! | `project.unarchive` | an active project is an accepted no-op (checked before the revision); name must be free among active projects |
//! | `tag.create` / `tag.update` | like projects, with the leading `@` dropped |
//! | `tag.delete` | revision check; the tag stays as `deleted`; every task holding it loses it and bumps its revision, in one change set |
//! | `task.tags` | task revision check; additions must be active tags, removals are explicit |

use crate::normalization as norm;
use crate::types::{
    ChangeOutcome, ChangeSet, Color, Command, Counter, DesiredOutcome, DomainChange, DomainCommand,
    DomainError, EntityType, ExecutionInputs, Name, Patch, Project, ProjectId, ProjectState,
    ReadSet, Reason, Record, ResultRefs, Tag, TagChanges, TagId, TagState, Task, TaskId,
};

/// Whether this family decides `command`.
#[must_use]
pub fn handles(command: &Command) -> bool {
    matches!(
        command,
        Command::ProjectCreate(_)
            | Command::ProjectUpdate(_)
            | Command::ProjectArchive(_)
            | Command::ProjectUnarchive(_)
            | Command::TagCreate(_)
            | Command::TagUpdate(_)
            | Command::TagDelete(_)
            | Command::TaskTags(_)
    )
}

/// Decides one organization command against the protected read set.
///
/// A command of another family is refused as [`Reason::InvalidPayload`]
/// (`field = "type"`); the dispatcher asks [`handles`] first.
pub fn decide(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    match &command.command {
        Command::ProjectCreate(payload) => project_create(read_set, command, payload),
        Command::ProjectUpdate(payload) => project_update(read_set, command, payload),
        Command::ProjectArchive(_) => project_archive(read_set, command, inputs),
        Command::ProjectUnarchive(_) => project_unarchive(read_set, command),
        Command::TagCreate(payload) => tag_create(read_set, command, payload),
        Command::TagUpdate(payload) => tag_update(read_set, command, payload),
        Command::TagDelete(_) => tag_delete(read_set, command, inputs),
        Command::TaskTags(changes) => task_tags(read_set, command, changes, inputs),
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

/// `edit_revision + 1`; a counter beyond `u64` is not representable.
fn next_revision(revision: &Counter) -> Result<Counter, DomainError> {
    revision
        .to_u64()
        .and_then(|value| value.checked_add(1))
        .map(Counter::from)
        .ok_or_else(|| DomainError::field(Reason::InvalidValue, "revision"))
}

/// The revision check of a revision-required command (`_assert_revision`).
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

fn not_found(entity_type: EntityType, id: &str) -> DomainError {
    DomainError::about(Reason::NotFound, entity_type, key_of(id))
}

/// A name in the display form `display` stores; blank and over-long results
/// are refused (the server's document would reject them, the core says so).
fn display_name(raw: &Name, display: fn(&str) -> String) -> Result<Name, DomainError> {
    let value = display(raw.as_str());
    if value.is_empty() {
        return Err(DomainError::field(Reason::EmptyName, "name"));
    }
    Name::new(value).map_err(|_| DomainError::field(Reason::TextLength, "name"))
}

fn patched<T: Clone>(current: &Option<T>, patch: &Patch<T>) -> Option<T> {
    match patch {
        Patch::Unchanged => current.clone(),
        Patch::Clear => None,
        Patch::Set(value) => Some(value.clone()),
    }
}

// ------------------------------------------------------------- name uniqueness

/// The active project, other than `other`, whose key equals `name`'s. The
/// lowest ID wins when legacy data holds several, so the refusal is stable.
#[must_use]
pub fn active_project_named<'a>(
    read_set: &'a ReadSet,
    name: &str,
    other: &ProjectId,
) -> Option<&'a Project> {
    let key = norm::project_key(name);
    read_set.projects.values().find(|project| {
        &project.id != other
            && project.state == ProjectState::Active
            && norm::project_key(project.name.as_str()) == key
    })
}

/// The active tag, other than `other`, whose key equals `name`'s (`name` is in
/// stored display form).
#[must_use]
pub fn active_tag_named<'a>(read_set: &'a ReadSet, name: &str, other: &TagId) -> Option<&'a Tag> {
    let key = norm::tag_key(name);
    read_set.tags.values().find(|tag| {
        &tag.id != other && tag.state == TagState::Active && norm::tag_key(tag.name.as_str()) == key
    })
}

fn project_clash(existing: &Project, reason: Reason) -> DomainError {
    refuse(reason, EntityType::Project, existing.id.as_str(), "name")
}

fn tag_clash(existing: &Tag) -> DomainError {
    refuse(
        Reason::DuplicateTagName,
        EntityType::Tag,
        existing.id.as_str(),
        "name",
    )
}

// ------------------------------------------------------------------- references

/// `TaskService._assert_active_references` for the references a command sets.
///
/// `current` is the project the task already belongs to: a membership the task
/// has is never re-validated, so an archived project's tasks stay editable
/// (ADR-0020). The project is checked first, then tag duplicates, then each
/// tag in order. Task rules (create, update, Smart Add) call this.
pub fn check_references(
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
    tags.iter()
        .try_for_each(|id| check_tag_active(read_set, id))
}

fn check_tag_active(read_set: &ReadSet, id: &TagId) -> Result<(), DomainError> {
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
}

// --------------------------------------------------------------------- projects

fn project_target(command: &DomainCommand) -> Result<ProjectId, DomainError> {
    ProjectId::parse(command.entity_id.as_str())
}

fn existing_project<'a>(read_set: &'a ReadSet, id: &ProjectId) -> Result<&'a Project, DomainError> {
    read_set
        .projects
        .get(id)
        .ok_or_else(|| not_found(EntityType::Project, id.as_str()))
}

fn project_create(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &crate::types::ProjectCreate,
) -> Result<ChangeSet, DomainError> {
    let id = project_target(command)?;
    if read_set.projects.contains_key(&id) {
        return Err(refuse(
            Reason::IdAlreadyExists,
            EntityType::Project,
            id.as_str(),
            "entity_id",
        ));
    }
    let name = display_name(&payload.name, norm::project_display)?;
    if let Some(existing) = active_project_named(read_set, name.as_str(), &id) {
        return Err(project_clash(existing, Reason::DuplicateProjectName));
    }
    let project = Project {
        id,
        name,
        color: payload.color.clone(),
        state: ProjectState::Active,
        revision: Counter::from(1),
        desired_outcome: payload.desired_outcome.clone(),
        archived_at: None,
        archived_before_lossless: false,
    };
    Ok(applied(vec![upsert(Record::Project(project))]))
}

fn project_update(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &crate::types::ProjectUpdate,
) -> Result<ChangeSet, DomainError> {
    let id = project_target(command)?;
    let project = existing_project(read_set, &id)?;
    check_revision(command, EntityType::Project, &project.revision)?;
    let name = match &payload.name {
        Some(raw) => display_name(raw, norm::project_display)?,
        None => project.name.clone(),
    };
    // Only an active project's name must be free; an archived project can take
    // any name and meets the check again when it is unarchived.
    if project.state == ProjectState::Active
        && let Some(existing) = active_project_named(read_set, name.as_str(), &id)
    {
        return Err(project_clash(existing, Reason::DuplicateProjectName));
    }
    let updated = Project {
        name,
        color: patched::<Color>(&project.color, &payload.color),
        desired_outcome: patched::<DesiredOutcome>(
            &project.desired_outcome,
            &payload.desired_outcome,
        ),
        revision: next_revision(&project.revision)?,
        ..project.clone()
    };
    Ok(applied(vec![upsert(Record::Project(updated))]))
}

/// Archiving keeps every membership (ADR-0020), so no task changes. A repeat
/// archive changes only the revision: `archived_at` and the pre-feature marker
/// are the one signal an old archive has.
fn project_archive(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    let id = project_target(command)?;
    let project = existing_project(read_set, &id)?;
    check_revision(command, EntityType::Project, &project.revision)?;
    let mut updated = Project {
        state: ProjectState::Archived,
        revision: next_revision(&project.revision)?,
        ..project.clone()
    };
    if project.state == ProjectState::Active {
        updated.archived_at = Some(inputs.now.clone());
        updated.archived_before_lossless = false;
    }
    Ok(applied(vec![upsert(Record::Project(updated))]))
}

/// An active project is answered before the revision is looked at, so a retry
/// that carries an old revision gets the same answer (http §3).
fn project_unarchive(
    read_set: &ReadSet,
    command: &DomainCommand,
) -> Result<ChangeSet, DomainError> {
    let id = project_target(command)?;
    let project = existing_project(read_set, &id)?;
    if project.state == ProjectState::Active {
        return Ok(ChangeSet::no_op());
    }
    check_revision(command, EntityType::Project, &project.revision)?;
    if let Some(existing) = active_project_named(read_set, project.name.as_str(), &id) {
        return Err(project_clash(existing, Reason::UnarchiveNameInUse));
    }
    let updated = Project {
        state: ProjectState::Active,
        archived_at: None,
        revision: next_revision(&project.revision)?,
        ..project.clone()
    };
    Ok(applied(vec![upsert(Record::Project(updated))]))
}

// ------------------------------------------------------------------------- tags

fn tag_target(command: &DomainCommand) -> Result<TagId, DomainError> {
    TagId::parse(command.entity_id.as_str())
}

fn existing_tag<'a>(read_set: &'a ReadSet, id: &TagId) -> Result<&'a Tag, DomainError> {
    read_set
        .tags
        .get(id)
        .ok_or_else(|| not_found(EntityType::Tag, id.as_str()))
}

fn tag_create(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &crate::types::TagCreate,
) -> Result<ChangeSet, DomainError> {
    let id = tag_target(command)?;
    if read_set.tags.contains_key(&id) {
        return Err(refuse(
            Reason::IdAlreadyExists,
            EntityType::Tag,
            id.as_str(),
            "entity_id",
        ));
    }
    let name = display_name(&payload.name, norm::tag_display)?;
    if let Some(existing) = active_tag_named(read_set, name.as_str(), &id) {
        return Err(tag_clash(existing));
    }
    let tag = Tag {
        id,
        name,
        state: TagState::Active,
        revision: Counter::from(1),
    };
    Ok(applied(vec![upsert(Record::Tag(tag))]))
}

fn tag_update(
    read_set: &ReadSet,
    command: &DomainCommand,
    payload: &crate::types::TagUpdate,
) -> Result<ChangeSet, DomainError> {
    let id = tag_target(command)?;
    let tag = existing_tag(read_set, &id)?;
    check_revision(command, EntityType::Tag, &tag.revision)?;
    let name = match &payload.name {
        Some(raw) => display_name(raw, norm::tag_display)?,
        None => tag.name.clone(),
    };
    // A deleted tag can be renamed freely; only an active name must be unique.
    if tag.state == TagState::Active
        && let Some(existing) = active_tag_named(read_set, name.as_str(), &id)
    {
        return Err(tag_clash(existing));
    }
    let updated = Tag {
        name,
        revision: next_revision(&tag.revision)?,
        ..tag.clone()
    };
    Ok(applied(vec![upsert(Record::Tag(updated))]))
}

/// A soft delete: the tag stays as `deleted` (its name is free again) and
/// every task that holds it, in any state, loses it in the same change set.
/// A repeat delete is accepted and only bumps the revision, as the server does.
fn tag_delete(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    let id = tag_target(command)?;
    let tag = existing_tag(read_set, &id)?;
    check_revision(command, EntityType::Tag, &tag.revision)?;
    let deleted = Tag {
        state: TagState::Deleted,
        revision: next_revision(&tag.revision)?,
        ..tag.clone()
    };
    let mut changes = vec![upsert(Record::Tag(deleted))];
    for task in read_set
        .tasks
        .values()
        .filter(|task| task.tag_ids.contains(&id))
    {
        let tag_ids = task.tag_ids.iter().filter(|tag| **tag != id).cloned();
        changes.push(upsert(Record::Task(edited(
            task,
            tag_ids.collect(),
            inputs,
        )?)));
    }
    Ok(applied(changes))
}

// ------------------------------------------------------------------ membership

/// The task after a membership edit: new tags, `updated_at`, revision + 1.
/// Tags never touch the formulation clock (spec 020 FR-003).
fn edited(task: &Task, tag_ids: Vec<TagId>, inputs: &ExecutionInputs) -> Result<Task, DomainError> {
    Ok(Task {
        tag_ids,
        updated_at: inputs.now.clone(),
        revision: next_revision(&task.revision)?,
        ..task.clone()
    })
}

/// The membership after explicit changes. Removals of tags the task does not
/// hold are moot, and so are additions it already holds (such a membership is
/// not re-validated, as for an existing project). A new membership must be an
/// active tag. Existing order is kept; additions follow in request order.
pub fn apply_tag_changes(
    read_set: &ReadSet,
    current: &[TagId],
    changes: &TagChanges,
) -> Result<Vec<TagId>, DomainError> {
    if !changes.is_unique_and_disjoint() {
        return Err(DomainError::field(Reason::TagChangesOverlap, "tag_changes"));
    }
    let added: Vec<&TagId> = changes
        .add_tag_ids
        .iter()
        .filter(|id| !current.contains(id))
        .collect();
    added
        .iter()
        .try_for_each(|id| check_tag_active(read_set, id))?;
    Ok(current
        .iter()
        .filter(|id| !changes.remove_tag_ids.contains(id))
        .chain(added)
        .cloned()
        .collect())
}

/// `task.tags`: the explicit membership edit, one Task update under the task's
/// revision. Like every task edit it bumps the revision even when the
/// membership ends up unchanged.
fn task_tags(
    read_set: &ReadSet,
    command: &DomainCommand,
    changes: &TagChanges,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    let id = TaskId::parse(command.entity_id.as_str())?;
    let task = read_set
        .tasks
        .get(&id)
        .ok_or_else(|| not_found(EntityType::Task, id.as_str()))?;
    check_revision(command, EntityType::Task, &task.revision)?;
    let tag_ids = apply_tag_changes(read_set, &task.tag_ids, changes)?;
    Ok(applied(vec![upsert(Record::Task(edited(
        task, tag_ids, inputs,
    )?))]))
}
