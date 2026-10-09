//! The task, project and tag queries (026 T012): what `query(read_set, query,
//! inputs)` answers for the list, detail, counts, project and tag reads.
//!
//! The server is the normative source: `TaskService.list_tasks`,
//! `get_task_detail`, `list_projects`, `list_tags` and the open-task counters
//! in `backend/app/modules/tasks/service.py`, and the response mapping of
//! `app/api/task_mapping.py`. The Apple kit (`Queries.swift`,
//! `Queries+List.swift`, `Queries+Ordering.swift`,
//! `Queries+ProjectDisplay.swift`) supplies only what the server has no
//! equivalent for: [`ListCounts`], a project's `next_action_count` and
//! [`ProjectDisplay`]. Where the two disagree the server wins: titles order by
//! NFKC + full case folding (no diacritic folding, C-05), and projects and tags
//! order by Python's `name.strip().casefold()` then id (C-06), not by the
//! `NameNormalizer` key.
//!
//! Everything is a function of its arguments. The caller owns the SQL page, the
//! binding of a cursor to the projection generation and the owner scope: the
//! [`ReadSet`] holds one owner's rows. The cursor in [`Page::after`] is the
//! server's own keyset token (`_encode_cursor`), so a page can continue across
//! the HTTP and local paths for an equal query.

use std::collections::{BTreeMap, BTreeSet};

use bb_protocol::catalog::EntityType;
use bb_protocol::wire::{Counter, Instant};
use serde_json::{Value, json};

use crate::calendar::{CalendarDay, TimeZone, UtcInstant};
use crate::formulation::{self, FormulationError, OwnerClockSettings};
use crate::normalization;
use crate::types::{
    CommentView, DomainError, ListCounts, OpenList, Page, Priority, Project, ProjectDisplay,
    ProjectFilter, ProjectId, ProjectState, ProjectSummary, Query, QueryInputs, QueryResult,
    ReadSet, Reason, Subtask, SubtaskView, Tag, TagId, TagState, TagSummary, Task, TaskCounts,
    TaskId, TaskListResult, TaskSort, TaskState, TaskView,
};

/// `limit` is `ge=1, le=200` on the list route.
const MAX_LIMIT: u32 = 200;

/// Owner settings when none are stored: `ReviewSettingsDocument` defaults (14
/// days, UTC, not activated), so no task has advisory instants.
const DEFAULT_THRESHOLD_DAYS: u32 = 14;

/// Answers one task, project or tag query.
///
/// The Review queries belong to the Review sessions family
/// ([`crate::review_sessions::query`]) and are refused here as
/// [`Reason::InvalidValue`] on `kind`, never answered with a placeholder; the
/// dispatcher asks `review_sessions::handles_query` first.
///
/// # Errors
///
/// [`Reason::NotFound`] for an unknown task, project or tag;
/// [`Reason::InvalidValue`] for a limit outside 1 to 200, a cursor that is
/// malformed or was issued for another query, or a stored value the rules
/// cannot read; [`Reason::InvalidTimeZone`] for an unknown zone.
pub fn query(
    read_set: &ReadSet,
    query: &Query,
    inputs: &QueryInputs,
) -> Result<QueryResult, DomainError> {
    match query {
        Query::TaskList {
            list,
            project_id,
            tag_id,
            sort,
            page,
        } => task_list(
            read_set,
            *list,
            project_id.as_ref(),
            tag_id.as_ref(),
            *sort,
            page,
        )
        .map(QueryResult::TaskList),
        Query::TaskDetail { task_id } => {
            task_detail(read_set, task_id).map(QueryResult::TaskDetail)
        }
        Query::ListCounts {} => list_counts(read_set, inputs).map(QueryResult::ListCounts),
        Query::Projects { filter } => Ok(QueryResult::Projects(projects(read_set, *filter))),
        Query::ProjectDisplay { project_id } => {
            project_display(read_set, project_id).map(QueryResult::ProjectDisplay)
        }
        Query::Tags {} => Ok(QueryResult::Tags(tags(read_set))),
        Query::ReviewState {} | Query::ReviewQueue { .. } => {
            Err(DomainError::field(Reason::InvalidValue, "kind"))
        }
    }
}

// ------------------------------------------------------------------- helpers

pub(crate) fn invalid(field: &str) -> DomainError {
    DomainError::field(Reason::InvalidValue, field)
}

pub(crate) fn not_found(entity_type: EntityType, id: &str) -> DomainError {
    DomainError::about(Reason::NotFound, entity_type, vec![id.to_owned()])
}

pub(crate) fn counter(value: &Counter, field: &str) -> Result<u64, DomainError> {
    value.to_u64().ok_or_else(|| invalid(field))
}

pub(crate) fn instant(value: &Instant, field: &str) -> Result<UtcInstant, DomainError> {
    UtcInstant::parse_rfc3339(value.as_str()).map_err(|_| invalid(field))
}

pub(crate) fn stored(error: FormulationError) -> DomainError {
    match error {
        FormulationError::InvalidField(field) => invalid(field),
        FormulationError::UnknownTimeZone(_) => {
            DomainError::field(Reason::InvalidTimeZone, "time_zone")
        }
        _ => invalid("review_settings"),
    }
}

/// The owner's clock inputs (`TaskService.clock_settings`): the stored
/// `review_settings`, or its defaults.
pub(crate) fn clock_settings(read_set: &ReadSet) -> Result<OwnerClockSettings, DomainError> {
    match &read_set.settings {
        Some(settings) => OwnerClockSettings::from_review_settings(settings),
        None => OwnerClockSettings::new(DEFAULT_THRESHOLD_DAYS, "UTC", None, None),
    }
    .map_err(stored)
}

/// `task_response` with its formulation projection (`formulation_view`):
/// the clock shows only on a Next task, the park marker only on a Someday one
/// (`TaskResponse.parked`), and the advisory instants are derived here.
pub(crate) fn task_view(
    task: &Task,
    subtasks: Vec<SubtaskView>,
    comments: Vec<CommentView>,
    settings: &OwnerClockSettings,
) -> Result<TaskView, DomainError> {
    let mut view = TaskView::new(task, subtasks, comments);
    if task.state != TaskState::Next {
        view.formulation = None;
    }
    if task.state != TaskState::Someday {
        view.parked = None;
    }
    formulation::fill_advisory_instants(&mut view, task, settings).map_err(stored)?;
    Ok(view)
}

/// Python's `name.strip().casefold()`: the project and tag order key (C-06).
fn name_key(name: &str) -> String {
    normalization::casefold(normalization::strip(name))
}

// ------------------------------------------------------------------- the list

/// One position of a sort key. Every position holds the same variant for all
/// tasks of one sort, so the derived order is Python's tuple order.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub(crate) enum KeyPart {
    Int(u64),
    Text(String),
}

pub(crate) type SortKey = Vec<KeyPart>;

/// `_PRIORITY_RANK`.
fn priority_rank(priority: Priority) -> u64 {
    match priority {
        Priority::High => 0,
        Priority::Medium => 1,
        Priority::Low => 2,
        Priority::None => 3,
    }
}

/// `datetime.isoformat()` of an aware UTC value, which the server compares as
/// text (`created_at.isoformat()`).
fn python_isoformat(value: UtcInstant) -> String {
    let text = value.to_rfc3339();
    format!("{}+00:00", text.strip_suffix('Z').unwrap_or(&text))
}

/// `TaskService._sort_key`.
pub(crate) fn sort_key(task: &Task, sort: TaskSort) -> Result<SortKey, DomainError> {
    use KeyPart::{Int, Text};
    let id = Text(task.id.as_str().to_owned());
    let manual = || -> Result<SortKey, DomainError> {
        Ok(vec![
            Int(counter(&task.order_key, "order_key")?),
            Text(python_isoformat(instant(&task.created_at, "created_at")?)),
            id.clone(),
        ])
    };
    Ok(match sort {
        TaskSort::Manual => manual()?,
        TaskSort::Due => {
            let mut key = vec![
                Int(u64::from(task.due_date.is_none())),
                Text(
                    task.due_date
                        .as_ref()
                        .map_or_else(String::new, |day| day.as_str().to_owned()),
                ),
            ];
            key.extend(manual()?);
            key
        }
        TaskSort::Priority => {
            let mut key = vec![Int(priority_rank(task.priority))];
            key.extend(manual()?);
            key
        }
        TaskSort::Title => vec![Text(normalization::search_key(task.title.as_str())), id],
    })
}

/// The filters the server fingerprints into its cursor, for the request this
/// query corresponds to (the ones the query type cannot express stay at their
/// defaults), so a cursor is accepted only for an equal query.
fn cursor_filters(
    list: OpenList,
    project_id: Option<&ProjectId>,
    tag_id: Option<&TagId>,
    unassigned_project: bool,
    sort: TaskSort,
) -> Value {
    json!({
        "state": list.as_str(),
        "project_id": project_id.map(ProjectId::as_str),
        "tag_id": tag_id.map(TagId::as_str),
        "unassigned_project": unassigned_project,
        "include_completed": false,
        "include_cancelled": false,
        "q": "",
        "priority": [],
        "due_before": null,
        "due_on": null,
        "due_after": null,
        "sort": sort.as_str(),
    })
}

/// A page of one open list (`GET /tasks?state=<list>`), with the server's
/// ordering, keyset cursor and `counts_by_state`.
///
/// The Inbox of a query without a project is the product projection, projectless
/// inbox tasks (`unassigned_project=true`, docs/projectless-inbox-contract.md);
/// every other list, and an Inbox read for one project, is the raw lifecycle
/// state. `counts_by_state` counts every open list under the same
/// project, tag and projectless scope, before the cursor and the limit.
///
/// # Errors
///
/// See [`query`].
pub fn task_list(
    read_set: &ReadSet,
    list: OpenList,
    project_id: Option<&ProjectId>,
    tag_id: Option<&TagId>,
    sort: TaskSort,
    page: &Page,
) -> Result<TaskListResult, DomainError> {
    if !(1..=MAX_LIMIT).contains(&page.limit) {
        return Err(invalid("limit"));
    }
    if let Some(id) = project_id
        && !read_set.projects.contains_key(id)
    {
        return Err(not_found(EntityType::Project, id.as_str()));
    }
    if let Some(id) = tag_id
        && !read_set.tags.contains_key(id)
    {
        return Err(not_found(EntityType::Tag, id.as_str()));
    }
    let unassigned = list == OpenList::Inbox && project_id.is_none();
    let filters = cursor_filters(list, project_id, tag_id, unassigned, sort);
    let after = page
        .after
        .as_deref()
        .map(|cursor| decode_cursor(cursor, &filters))
        .transpose()?;

    let scoped: Vec<&Task> = read_set
        .tasks
        .values()
        .filter(|task| {
            project_id.is_none_or(|id| task.project_id.as_ref() == Some(id))
                && tag_id.is_none_or(|id| task.tag_ids.contains(id))
                && (!unassigned || task.project_id.is_none())
        })
        .collect();
    let counts_by_state = open_counts(&scoped);

    let mut keyed = scoped
        .into_iter()
        .filter(|task| task.state == list.task_state())
        .map(|task| Ok((sort_key(task, sort)?, task)))
        .collect::<Result<Vec<_>, DomainError>>()?;
    keyed.sort_by(|a, b| a.0.cmp(&b.0));
    if let Some(last) = &after {
        keyed.retain(|(key, _)| key > last);
    }
    let limit = usize::try_from(page.limit).unwrap_or(usize::MAX);
    let has_more = keyed.len() > limit;
    keyed.truncate(limit);
    let next_cursor = keyed
        .last()
        .filter(|_| has_more)
        .map(|(key, _)| encode_cursor(&filters, key));

    let settings = clock_settings(read_set)?;
    let items = keyed
        .iter()
        .map(|(_, task)| task_view(task, Vec::new(), Vec::new(), &settings))
        .collect::<Result<_, _>>()?;
    Ok(TaskListResult {
        items,
        next_cursor,
        has_more,
        counts_by_state,
    })
}

/// `TaskService._open_counts` over tasks already scoped by project and tag.
fn open_counts(tasks: &[&Task]) -> TaskCounts {
    let mut counts = TaskCounts::default();
    for task in tasks {
        match task.state {
            TaskState::Inbox => counts.inbox += 1,
            TaskState::Next => counts.next += 1,
            TaskState::Waiting => counts.waiting += 1,
            TaskState::Someday => counts.someday += 1,
            TaskState::Completed | TaskState::Cancelled => {}
        }
    }
    counts
}

// ------------------------------------------------------------------- cursors

const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

/// `base64.urlsafe_b64encode(..).rstrip("=")`.
fn base64url_encode(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let group = chunk.iter().enumerate().fold(0u32, |acc, (i, byte)| {
            acc | (u32::from(*byte) << (16 - 8 * i))
        });
        for position in 0..=chunk.len() {
            let index = (group >> (18 - 6 * position)) & 0x3f;
            out.push(char::from(ALPHABET[index as usize]));
        }
    }
    out
}

/// The inverse, accepting the optional `=` padding; `None` for anything that
/// is not URL-safe base64.
fn base64url_decode(text: &str) -> Option<Vec<u8>> {
    let text = text.trim_end_matches('=');
    if text.len() % 4 == 1 {
        return None;
    }
    let mut out = Vec::with_capacity(text.len() * 3 / 4);
    let (mut acc, mut bits) = (0u32, 0u32);
    for byte in text.bytes() {
        let value = ALPHABET.iter().position(|candidate| *candidate == byte)?;
        acc = (acc << 6) | u32::try_from(value).ok()?;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push(u8::try_from((acc >> bits) & 0xff).ok()?);
            acc &= (1 << bits) - 1;
        }
    }
    Some(out)
}

/// `json.dumps(value, sort_keys=True, separators=(",", ":"))`, ASCII only, the
/// bytes the server's cursor is made of.
pub(crate) fn python_dumps(value: &Value) -> String {
    match value {
        Value::Null => "null".to_owned(),
        Value::Bool(flag) => flag.to_string(),
        Value::Number(number) => number.to_string(),
        Value::String(text) => python_string(text),
        Value::Array(items) => {
            let items: Vec<String> = items.iter().map(python_dumps).collect();
            format!("[{}]", items.join(","))
        }
        Value::Object(members) => {
            let sorted: BTreeMap<&String, &Value> = members.iter().collect();
            let members: Vec<String> = sorted
                .into_iter()
                .map(|(key, member)| format!("{}:{}", python_string(key), python_dumps(member)))
                .collect();
            format!("{{{}}}", members.join(","))
        }
    }
}

/// A JSON string as Python's `ensure_ascii` writes it.
fn python_string(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + 2);
    out.push('"');
    for c in text.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            ' '..='~' => out.push(c),
            _ => {
                let mut units = [0u16; 2];
                for unit in c.encode_utf16(&mut units) {
                    out.push_str(&format!("\\u{unit:04x}"));
                }
            }
        }
    }
    out.push('"');
    out
}

/// `TaskService._encode_cursor`.
fn encode_cursor(filters: &Value, last: &SortKey) -> String {
    let last: Vec<Value> = last
        .iter()
        .map(|part| match part {
            KeyPart::Int(number) => Value::from(*number),
            KeyPart::Text(text) => Value::String(text.clone()),
        })
        .collect();
    let payload = json!({ "filters": filters, "last": last });
    base64url_encode(python_dumps(&payload).as_bytes())
}

/// `TaskService._decode_cursor`: the last sort key, or a refusal when the token
/// is malformed or was issued for other filters.
fn decode_cursor(cursor: &str, filters: &Value) -> Result<SortKey, DomainError> {
    let refused = || invalid("cursor");
    let bytes = base64url_decode(cursor).ok_or_else(refused)?;
    let payload: Value = serde_json::from_slice(&bytes).map_err(|_| refused())?;
    if payload.get("filters") != Some(filters) {
        return Err(refused());
    }
    let last = payload
        .get("last")
        .and_then(Value::as_array)
        .filter(|parts| !parts.is_empty())
        .ok_or_else(refused)?;
    last.iter()
        .map(|part| match part {
            Value::String(text) => Some(KeyPart::Text(text.clone())),
            Value::Number(number) => number.as_u64().map(KeyPart::Int),
            _ => None,
        })
        .map(|part| part.ok_or_else(refused))
        .collect()
}

// ---------------------------------------------------------------- the detail

/// `GET /tasks/{id}`: the task with its subtasks by `(order_key, id)` and its
/// comments by `(created_at, id)`.
///
/// # Errors
///
/// See [`query`].
pub fn task_detail(read_set: &ReadSet, task_id: &TaskId) -> Result<TaskView, DomainError> {
    let task = read_set
        .tasks
        .get(task_id)
        .ok_or_else(|| not_found(EntityType::Task, task_id.as_str()))?;

    let mut subtasks = read_set
        .subtasks
        .values()
        .filter(|subtask| &subtask.task_id == task_id)
        .map(|subtask| Ok((counter(&subtask.order_key, "order_key")?, subtask)))
        .collect::<Result<Vec<(u64, &Subtask)>, DomainError>>()?;
    subtasks.sort_by(|a, b| (a.0, &a.1.id).cmp(&(b.0, &b.1.id)));

    let mut comments = read_set
        .comments
        .values()
        .filter(|comment| &comment.task_id == task_id)
        .map(|comment| Ok((instant(&comment.created_at, "created_at")?, comment)))
        .collect::<Result<Vec<_>, DomainError>>()?;
    comments.sort_by(|a, b| (a.0, &a.1.id).cmp(&(b.0, &b.1.id)));

    task_view(
        task,
        subtasks
            .into_iter()
            .map(|(_, subtask)| SubtaskView::from(subtask))
            .collect(),
        comments
            .into_iter()
            .map(|(_, comment)| CommentView::from(comment))
            .collect(),
        &clock_settings(read_set)?,
    )
}

// ------------------------------------------------------------------- counts

/// Global badge counts over open tasks (`GTDQueries.counts`): Inbox counts
/// projectless inbox tasks, the other lists every project; `overdue` and
/// `today` count every open task, in any list, due before or on the device's
/// local day. The server has no such read.
///
/// # Errors
///
/// See [`query`].
pub fn list_counts(read_set: &ReadSet, inputs: &QueryInputs) -> Result<ListCounts, DomainError> {
    let now = instant(&inputs.now, "now")?;
    let zone = TimeZone::named(inputs.device_zone.as_str())
        .map_err(|_| DomainError::field(Reason::InvalidTimeZone, "device_zone"))?;
    let today = CalendarDay::of_instant(now.unix_seconds(), &zone);
    let mut counts = ListCounts::default();
    for task in read_set.tasks.values() {
        match task.state {
            TaskState::Inbox if task.project_id.is_none() => counts.inbox += 1,
            TaskState::Inbox => {}
            TaskState::Next => counts.next += 1,
            TaskState::Waiting => counts.waiting += 1,
            TaskState::Someday => counts.someday += 1,
            TaskState::Completed | TaskState::Cancelled => continue,
        }
        if let Some(due) = &task.due_date {
            let due = CalendarDay::parse_iso(due.as_str()).map_err(|_| invalid("due_date"))?;
            match due.cmp(&today) {
                std::cmp::Ordering::Less => counts.overdue += 1,
                std::cmp::Ordering::Equal => counts.today += 1,
                std::cmp::Ordering::Greater => {}
            }
        }
    }
    Ok(counts)
}

// ------------------------------------------------------- projects and tags

/// `GET /projects?state=`: by `(name.strip().casefold(), id)`, with the open
/// task count (`open_task_counts_by_project`) and, from the Apple kit, the
/// open Next tasks that make a project not stuck.
pub fn projects(read_set: &ReadSet, filter: ProjectFilter) -> Vec<ProjectSummary> {
    let mut counts: BTreeMap<&ProjectId, (u32, u32)> = BTreeMap::new();
    for task in read_set.tasks.values().filter(|task| task.state.is_open()) {
        if let Some(id) = &task.project_id {
            let entry = counts.entry(id).or_default();
            entry.0 += 1;
            entry.1 += u32::from(task.state == TaskState::Next);
        }
    }
    let mut listed: Vec<&Project> = read_set
        .projects
        .values()
        .filter(|project| match filter {
            ProjectFilter::All => true,
            ProjectFilter::Active => project.state == ProjectState::Active,
            ProjectFilter::Archived => project.state == ProjectState::Archived,
        })
        .collect();
    listed.sort_by_cached_key(|project| (name_key(project.name.as_str()), project.id.clone()));
    listed
        .into_iter()
        .map(|project| {
            let (open_task_count, next_action_count) =
                counts.get(&project.id).copied().unwrap_or_default();
            ProjectSummary {
                project: project.clone(),
                open_task_count,
                next_action_count,
            }
        })
        .collect()
}

/// `GET /tags`: active tags by `(name.strip().casefold(), id)`, with the open
/// tasks carrying each (a task counts once).
pub fn tags(read_set: &ReadSet) -> Vec<TagSummary> {
    let mut counts: BTreeMap<&TagId, u32> = BTreeMap::new();
    for task in read_set.tasks.values().filter(|task| task.state.is_open()) {
        for id in task.tag_ids.iter().collect::<BTreeSet<_>>() {
            *counts.entry(id).or_default() += 1;
        }
    }
    let mut listed: Vec<&Tag> = read_set
        .tags
        .values()
        .filter(|tag| tag.state == TagState::Active)
        .collect();
    listed.sort_by_cached_key(|tag| (name_key(tag.name.as_str()), tag.id.clone()));
    listed
        .into_iter()
        .map(|tag| TagSummary {
            tag: tag.clone(),
            open_task_count: counts.get(&tag.id).copied().unwrap_or_default(),
        })
        .collect()
}

/// How a project presents itself (`GTDQueries.projectDisplay`): the label,
/// whether capture is accepted, and the pre-lossless explanation shown only
/// when no task of any state is left.
///
/// # Errors
///
/// [`Reason::NotFound`] for a project the read set does not hold.
pub fn project_display(
    read_set: &ReadSet,
    project_id: &ProjectId,
) -> Result<ProjectDisplay, DomainError> {
    let project = read_set
        .projects
        .get(project_id)
        .ok_or_else(|| not_found(EntityType::Project, project_id.as_str()))?;
    let archived = project.state == ProjectState::Archived;
    Ok(ProjectDisplay {
        is_archived: archived,
        accepts_new_tasks: !archived,
        shows_pre_lossless_line: project.archived_before_lossless
            && !read_set
                .tasks
                .values()
                .any(|task| task.project_id.as_ref() == Some(project_id)),
        label: if archived {
            format!("{} · archived", project.name.as_str())
        } else {
            project.name.as_str().to_owned()
        },
    })
}
