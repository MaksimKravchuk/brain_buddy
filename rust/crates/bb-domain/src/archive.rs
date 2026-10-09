//! The archive and restoration family (026 PR-09): what a lossless project
//! archive leaves behind, and the pre-feature archives that must be recognised.
//!
//! `project.archive` / `project.unarchive` themselves are decided by
//! [`crate::organize`] (PR-08): ADR-0020 made archive lossless, so neither
//! command changes a task and there is no cascade to compute. What remains is
//! pure and lives here:
//!
//! | Function | Server rule |
//! | --- | --- |
//! | [`members_of`] / [`open_member_count`] | every task keeps its `project_id` in any state; the `open_task_count` of the archive answer counts open lists only (`_OPEN_STATES`) |
//! | [`needs_marker`] / [`restore_detached_archives`] | `TaskRepository._mark_detached_archives`: an archived project without `archived_at` had its members cleared before ADR-0020; the step stamps `archived_before_lossless` and bumps neither `revision` nor `updated_at`, and a second run changes nothing |
//! | [`parse_state_filter`] / [`projects_in_state`] | `GET /projects?state=` (TR-L01): `active` by default, `archived`, `all`; any other value is a 422; by trimmed case-folded name, then ID |
//!
//! Differences from the Swift side, kept on purpose: the Swift reducer treats
//! a repeat archive as already satisfied (no revision bump), while the server
//! bumps the revision; the sync engine never restores a marker itself, it only
//! raises an issue when a server answers an archive without `archived_at`.

use crate::normalization as norm;
use crate::types::{
    ChangeOutcome, ChangeSet, DomainChange, DomainError, Project, ProjectFilter, ProjectId,
    ProjectState, ReadSet, Reason, Record, ResultRefs, Task,
};

/// Every task of `project`, in any state: open, completed, cancelled. Archive
/// keeps them all (ADR-0020), so this is the same set before and after.
pub fn members_of<'a>(
    read_set: &'a ReadSet,
    project: &'a ProjectId,
) -> impl Iterator<Item = &'a Task> {
    read_set
        .tasks
        .values()
        .filter(move |task| task.project_id.as_ref() == Some(project))
}

/// The `open_task_count` of a project: members in an open list only.
#[must_use]
pub fn open_member_count(read_set: &ReadSet, project: &ProjectId) -> u32 {
    let open = members_of(read_set, project)
        .filter(|task| task.state.is_open())
        .count();
    u32::try_from(open).unwrap_or(u32::MAX)
}

/// An archive made before ADR-0020: archived, no archive time, marker not yet
/// stamped. Active projects and archives that carry `archived_at` never match.
#[must_use]
pub fn needs_marker(project: &Project) -> bool {
    project.state == ProjectState::Archived
        && project.archived_at.is_none()
        && !project.archived_before_lossless
}

/// The marker restoration over a whole scope: one upsert per project that
/// [`needs_marker`], in ID order, otherwise a no-op. The projects keep their
/// revision, so no queued command goes stale. The result lands in the read
/// set and a second call is a no-op (`_mark_detached_archives` is idempotent).
#[must_use]
pub fn restore_detached_archives(read_set: &ReadSet) -> ChangeSet {
    let changes: Vec<DomainChange> = read_set
        .projects
        .values()
        .filter(|project| needs_marker(project))
        .map(|project| {
            DomainChange::Upsert(Record::Project(Project {
                archived_before_lossless: true,
                ..project.clone()
            }))
        })
        .collect();
    if changes.is_empty() {
        return ChangeSet::no_op();
    }
    ChangeSet {
        outcome: ChangeOutcome::Applied,
        changes,
        result: ResultRefs::default(),
        effects: Vec::new(),
    }
}

/// The `state` query parameter of `GET /projects`: absent is `active`; a value
/// outside `active|archived|all` is refused (the server answers 422).
pub fn parse_state_filter(raw: Option<&str>) -> Result<ProjectFilter, DomainError> {
    match raw {
        None => Ok(ProjectFilter::Active),
        Some(value) => ProjectFilter::from_wire(value)
            .ok_or_else(|| DomainError::field(Reason::InvalidValue, "state")),
    }
}

/// The projects `filter` selects, in the server's order: trimmed, case-folded
/// name, then ID. A project is listed by its own state, whatever its members.
#[must_use]
pub fn projects_in_state(read_set: &ReadSet, filter: ProjectFilter) -> Vec<&Project> {
    let mut listed: Vec<(String, &Project)> = read_set
        .projects
        .values()
        .filter(|project| match filter {
            ProjectFilter::All => true,
            ProjectFilter::Active => project.state == ProjectState::Active,
            ProjectFilter::Archived => project.state == ProjectState::Archived,
        })
        .map(|project| (norm::casefold(norm::strip(project.name.as_str())), project))
        .collect();
    listed.sort_by(|(left_key, left), (right_key, right)| {
        left_key
            .cmp(right_key)
            .then_with(|| left.id.as_str().cmp(right.id.as_str()))
    });
    listed.into_iter().map(|(_, project)| project).collect()
}
