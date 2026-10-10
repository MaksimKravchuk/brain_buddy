//! The native list modes (026 T012, owner decision 2026-10-09): History,
//! Agenda, the date views and Search as shared queries, so every client lists
//! them the way the Apple kit does.
//!
//! The Apple kit is normative here: `GTDQueries.list` in `Queries.swift`,
//! `Queries+List.swift` (sections, placement of completed and cancelled tasks,
//! grouping) and `Queries+Ordering.swift` (`QueryText.fold`, `TaskOrdering`,
//! `NameSortKey`). The server has no such reads, so where `GET /tasks` and the
//! kit disagree these modes follow the kit (the register entries C-05 and C-06
//! of `reference-store.json` are decided for them):
//!
//! * search and title order fold diacritics as well as case
//!   ([`normalization::diacritic_fold`]); the server's `search_key` does not;
//! * a search query collapses White_Space runs (Swift's `isWhitespace`), not
//!   Python's `str.split()` class;
//! * sections of grouped rows follow `NameSortKey` (folded name, normalized
//!   name, display name, id; archived after active), not `strip().casefold()`;
//! * manual order compares `created_at` as an instant, the server as text.
//!
//! A result is a flat sequence of rows in section order, and a page is a
//! bounded slice of it: one pass over the read set keeps the `limit + 1` best
//! keys after the cursor, so a page costs O(limit) memory however large the
//! store is, and each row's key ends in the task id, so the order is total.
//! A section is ordered by a key computed from its own project when a row is
//! met (looked up by id, O(log n)), never from a table over every project, so
//! grouping adds no memory beyond the page either.
//!
//! The keyset cursor is the server's token format (base64url JSON of the
//! filters that must match and the last key) whose key starts with the id of the
//! row's section, then the section's order key as it was when the cursor was
//! issued (a project's archived flag, folded name, normalized name and display
//! name and id), then the row's key. The next page looks the section up again
//! and refuses the cursor when its order key has since changed (the project was
//! renamed, archived or unarchived): resuming at the section's new position
//! would skip or repeat rows, so the client restarts from the first page
//! instead. A section or key of the wrong shape for the mode's order is refused.
//!
//! Pure: `today` is the device's calendar day of `inputs.now` in
//! `inputs.device_zone`, the same day `list_counts` uses.

use std::cmp::Ordering;
use std::collections::{BTreeSet, BinaryHeap};

use serde_json::{Value, json};
use unicode_normalization::UnicodeNormalization;

use crate::calendar::{CalendarDay, TimeZone, UtcInstant};
use crate::normalization;
use crate::queries::{self, KeyPart, MAX_LIMIT, SortKey, invalid};
use crate::types::{
    DateView, DomainError, HistoryKind, ListMode, ListModePage, ListOptions, Page, PageSection,
    Priority, Project, ProjectId, ProjectState, Query, QueryInputs, QueryResult, ReadSet, Reason,
    SectionKind, Task, TaskSort, TaskState,
};

/// Title of the section of tasks without a (known) project.
const NO_PROJECT_TITLE: &str = "No project";

/// Whether this family answers the query: the list modes.
pub fn handles_query(query: &Query) -> bool {
    matches!(query, Query::ListMode { .. })
}

/// Answers one list mode query.
///
/// # Errors
///
/// [`Reason::InvalidValue`] for a limit outside 1 to 200, a cursor that is
/// malformed, was issued for another query, names a section or key shape the
/// query cannot produce, or was issued while its project sorted elsewhere
/// (renamed, archived or unarchived since), and for a stored value the rules cannot read (or
/// any other query kind); [`Reason::InvalidTimeZone`] for an unknown device
/// zone, which only the Agenda and the date views read.
pub fn query(
    read_set: &ReadSet,
    query: &Query,
    inputs: &QueryInputs,
) -> Result<QueryResult, DomainError> {
    match query {
        Query::ListMode {
            mode,
            options,
            page,
        } => list_mode(read_set, mode, options, page, inputs).map(QueryResult::ListMode),
        _ => Err(invalid("kind")),
    }
}

/// One page of a list mode.
///
/// A blank Search query (nothing left after folding) matches nothing: an empty
/// page, whatever the cursor.
///
/// # Errors
///
/// See [`query`].
pub fn list_mode(
    read_set: &ReadSet,
    mode: &ListMode,
    options: &ListOptions,
    page: &Page,
    inputs: &QueryInputs,
) -> Result<ListModePage, DomainError> {
    list_mode_with_local_facts(
        read_set,
        mode,
        options,
        page,
        inputs,
        &std::collections::BTreeMap::new(),
    )
}

/// Local terminal-list origins are presentation facts, never replicated task data.
/// Unknown origins are shown in History only.
pub fn list_mode_with_local_facts(
    read_set: &ReadSet,
    mode: &ListMode,
    options: &ListOptions,
    page: &Page,
    inputs: &QueryInputs,
    last_open_lists: &std::collections::BTreeMap<crate::types::TaskId, crate::types::OpenList>,
) -> Result<ListModePage, DomainError> {
    list_mode_with_origin_lookup(read_set, mode, options, page, inputs, &|task| {
        last_open_lists.get(&task.id).copied()
    })
}

/// Store adapters can read one exact local carrier per terminal task without
/// constructing an additional origin map over the entire projection.
pub fn list_mode_with_origin_lookup(
    read_set: &ReadSet,
    mode: &ListMode,
    options: &ListOptions,
    page: &Page,
    inputs: &QueryInputs,
    origin: &dyn Fn(&Task) -> Option<crate::types::OpenList>,
) -> Result<ListModePage, DomainError> {
    if !(1..=MAX_LIMIT).contains(&page.limit) {
        return Err(invalid("limit"));
    }
    let needle = match mode {
        ListMode::Search { text } => match search_query(text) {
            Some(needle) => Some(needle),
            None => return Ok(empty_page()),
        },
        _ => None,
    };
    let plan = Plan::new(read_set, mode, options, needle, inputs, origin)?;
    let filters = plan.filters();
    let after = page
        .after
        .as_deref()
        .map(|cursor| plan.decode_cursor(cursor, &filters))
        .transpose()?;

    // One pass: count the open rows, and keep only the `limit + 1` smallest
    // keys after the cursor.
    let limit = usize::try_from(page.limit).unwrap_or(usize::MAX);
    let keep = limit.saturating_add(1);
    let mut open_count = 0u32;
    let mut best: BinaryHeap<Candidate> =
        BinaryHeap::with_capacity(keep.min(MAX_LIMIT as usize + 1));
    for task in read_set.tasks.values() {
        let Some(placed) = plan.place(task)? else {
            continue;
        };
        open_count = open_count.saturating_add(u32::from(placed.open));
        let key = plan.key(task, &placed.section)?;
        if after.as_ref().is_some_and(|last| &key <= last) {
            continue;
        }
        if best.len() == keep && best.peek().is_some_and(|worst| key >= worst.key) {
            continue;
        }
        if best.len() == keep {
            best.pop();
        }
        best.push(Candidate {
            key,
            section: placed.section,
            task,
        });
    }
    let mut keyed = best.into_sorted_vec();
    let has_more = keyed.len() > limit;
    keyed.truncate(limit);
    let next_cursor = keyed
        .last()
        .filter(|_| has_more)
        .map(|last| plan.encode_cursor(&filters, last));

    let settings = queries::clock_settings(read_set)?;
    let mut sections: Vec<PageSection> = Vec::new();
    let mut current: Option<&Section> = None;
    for candidate in &keyed {
        if current != Some(&candidate.section) {
            sections.push(plan.describe(&candidate.section));
            current = Some(&candidate.section);
        }
        if let Some(section) = sections.last_mut() {
            section.items.push(queries::task_view(
                candidate.task,
                Vec::new(),
                Vec::new(),
                &settings,
            )?);
        }
    }
    Ok(ListModePage {
        sections,
        open_count,
        next_cursor,
        has_more,
    })
}

fn empty_page() -> ListModePage {
    ListModePage {
        sections: Vec::new(),
        open_count: 0,
        next_cursor: None,
        has_more: false,
    }
}

// ----------------------------------------------------------------- search text

/// `QueryText.searchQuery`: the query folded and its whitespace collapsed, or
/// none when nothing is left to match.
pub fn search_query(raw: &str) -> Option<String> {
    let query = normalization::collapse_unicode_whitespace(&normalization::diacritic_fold(raw));
    (!query.is_empty()).then_some(query)
}

/// `QueryText.searchHaystack`: title and notes joined by a newline, which a
/// collapsed query never contains, so a match cannot span both.
fn search_haystack(task: &Task) -> String {
    normalization::diacritic_fold(&format!(
        "{}\n{}",
        task.title.as_str(),
        task.details.as_ref().map_or("", |details| details.as_str())
    ))
}

fn nfc(value: &str) -> String {
    value.nfc().collect()
}

// -------------------------------------------------------------------- sections

/// Where a row goes. Ordered by [`Plan::section_key`] within one query.
#[derive(Clone, Debug, PartialEq, Eq)]
enum Section {
    /// The one unnamed section of open rows.
    Open,
    Project(ProjectId),
    List(crate::types::OpenList),
    /// Tasks without a project, or whose project the read set lacks.
    NoProject,
    Date(DateView),
    /// The terminal rows of one kind: `Completed` then `Cancelled`.
    Ended(HistoryKind),
}

/// How the rows of every section are ordered (`TaskOrdering`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Order {
    Sorted(TaskSort),
    /// Most recently completed or cancelled first, unknown times last, then id.
    Recency,
}

impl Order {
    /// Whether each position of the item key is an integer (`true`) or text.
    fn shape(self) -> &'static [bool] {
        match self {
            Self::Sorted(TaskSort::Manual) | Self::Recency => &[true, true, false],
            Self::Sorted(TaskSort::Due) => &[true, false, true, true, false],
            Self::Sorted(TaskSort::Priority) => &[true, true, true, false],
            Self::Sorted(TaskSort::Title) => &[false, false],
        }
    }
}

fn view_index(view: DateView) -> u64 {
    match view {
        DateView::Overdue => 0,
        DateView::Today => 1,
        DateView::Upcoming => 2,
    }
}

fn view_title(view: DateView) -> &'static str {
    match view {
        DateView::Overdue => "Overdue",
        DateView::Today => "Today",
        DateView::Upcoming => "Upcoming",
    }
}

fn history_title(kind: HistoryKind) -> &'static str {
    match kind {
        HistoryKind::Completed => "Completed",
        HistoryKind::Cancelled => "Cancelled",
    }
}

fn history_state(kind: HistoryKind) -> TaskState {
    match kind {
        HistoryKind::Completed => TaskState::Completed,
        HistoryKind::Cancelled => TaskState::Cancelled,
    }
}

/// A task in the page selection, ordered by its key alone.
struct Candidate<'a> {
    key: SortKey,
    section: Section,
    task: &'a Task,
}

impl PartialEq for Candidate<'_> {
    fn eq(&self, other: &Self) -> bool {
        self.key == other.key
    }
}

impl Eq for Candidate<'_> {}

impl PartialOrd for Candidate<'_> {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Candidate<'_> {
    fn cmp(&self, other: &Self) -> Ordering {
        self.key.cmp(&other.key)
    }
}

/// A task that belongs to the result.
struct Placed {
    section: Section,
    /// An open task: counted in `open_count`.
    open: bool,
}

/// Everything a page reads besides the tasks: the mode resolved against the
/// options (`TaskListBuilder`).
struct Plan<'a> {
    read_set: &'a ReadSet,
    mode: &'a ListMode,
    options: &'a ListOptions,
    /// The folded Search query.
    needle: Option<String>,
    /// The device's day; set for the Agenda and the date views only.
    today: Option<CalendarDay>,
    order: Order,
    /// Open rows (History's rows) in one section per project.
    grouped: bool,
    show_completed: bool,
    show_cancelled: bool,
    priorities: BTreeSet<Priority>,
    origin: &'a dyn Fn(&Task) -> Option<crate::types::OpenList>,
}

impl<'a> Plan<'a> {
    fn new(
        read_set: &'a ReadSet,
        mode: &'a ListMode,
        options: &'a ListOptions,
        needle: Option<String>,
        inputs: &QueryInputs,
        origin: &'a dyn Fn(&Task) -> Option<crate::types::OpenList>,
    ) -> Result<Self, DomainError> {
        let uses_day = matches!(mode, ListMode::Agenda {} | ListMode::DateView { .. });
        let today = if uses_day {
            let now = queries::instant(&inputs.now, "now")?;
            let zone = TimeZone::named(inputs.device_zone.as_str())
                .map_err(|_| DomainError::field(Reason::InvalidTimeZone, "device_zone"))?;
            Some(CalendarDay::of_instant(now.unix_seconds(), &zone))
        } else {
            None
        };
        // Date views read best in date order, so manual means due there.
        let date_sort = match options.sort {
            TaskSort::Manual => TaskSort::Due,
            other => other,
        };
        let order = match mode {
            ListMode::History { .. } if options.sort == TaskSort::Manual => Order::Recency,
            ListMode::History { .. }
            | ListMode::Search { .. }
            | ListMode::OpenList { .. }
            | ListMode::Project { .. }
            | ListMode::Tag { .. } => Order::Sorted(options.sort),
            ListMode::Agenda {} | ListMode::DateView { .. } => Order::Sorted(date_sort),
        };
        let (show_completed, show_cancelled) = match mode {
            ListMode::Search { .. } => (true, true),
            ListMode::History { .. } => (false, false),
            ListMode::Agenda {}
            | ListMode::DateView { .. }
            | ListMode::OpenList { .. }
            | ListMode::Project { .. }
            | ListMode::Tag { .. } => (options.show_completed, options.show_cancelled),
        };
        let grouped = options.group_by_project
            && !matches!(
                mode,
                ListMode::Agenda {}
                    | ListMode::Project { .. }
                    | ListMode::OpenList {
                        list: crate::types::OpenList::Inbox
                    }
            );
        Ok(Self {
            read_set,
            origin,
            mode,
            options,
            needle,
            today,
            order,
            grouped,
            show_completed,
            show_cancelled,
            priorities: options.priorities.iter().copied().collect(),
        })
    }

    /// The filters a cursor is bound to, in the effective form: options the mode
    /// ignores do not change them.
    fn filters(&self) -> Value {
        let (mode, detail) = match self.mode {
            ListMode::OpenList { list } => ("open_list", Value::from(list.as_str())),
            ListMode::Project { project_id } => ("project", Value::from(project_id.as_str())),
            ListMode::Tag { tag_id } => ("tag", Value::from(tag_id.as_str())),
            ListMode::History { kind } => ("history", Value::from(kind.as_str())),
            ListMode::Agenda {} => ("agenda", Value::Null),
            ListMode::DateView { view } => ("date_view", Value::from(view.as_str())),
            ListMode::Search { .. } => ("search", Value::from(self.needle.clone())),
        };
        json!({
            "screen": "list_mode",
            "mode": mode,
            "detail": detail,
            "today": self.today.map(CalendarDay::iso_string),
            "sort": self.options.sort.as_str(),
            "grouped": self.grouped,
            "show_completed": self.show_completed,
            "show_cancelled": self.show_cancelled,
            "priorities": self.priorities.iter().map(|p| p.as_str()).collect::<Vec<_>>(),
            "tag_filter": self.options.tag_filter.as_ref().map(|tag| tag.as_str()),
        })
    }

    // ------------------------------------------------------------- placement

    /// `TaskListBuilder`: the section a task belongs to, or none when the mode
    /// leaves it out.
    fn place(&self, task: &Task) -> Result<Option<Placed>, DomainError> {
        if !self.priorities.is_empty() && !self.priorities.contains(&task.priority) {
            return Ok(None);
        }
        if let Some(tag) = &self.options.tag_filter
            && !task.tag_ids.contains(tag)
        {
            return Ok(None);
        }
        let open = |section: Section| Placed {
            section,
            open: true,
        };
        let ended = |kind: HistoryKind| Placed {
            section: Section::Ended(kind),
            open: false,
        };
        Ok(match self.mode {
            ListMode::OpenList { list } => {
                if *list == crate::types::OpenList::Inbox && task.project_id.is_some() {
                    None
                } else if task.state.open_list().is_some() {
                    (task.state == list.task_state()).then(|| {
                        open(if self.grouped {
                            self.project_section(task)
                        } else {
                            Section::Open
                        })
                    })
                } else if (self.origin)(task) == Some(*list) {
                    self.by_state(task, open)
                } else {
                    None
                }
            }
            ListMode::Project { project_id } => {
                if task.project_id.as_ref() != Some(project_id) {
                    None
                } else if let Some(list) = task.state.open_list() {
                    Some(open(Section::List(list)))
                } else {
                    self.by_state(task, open)
                }
            }
            ListMode::Tag { tag_id } => {
                if task.tag_ids.contains(tag_id) {
                    self.by_state(task, open)
                } else {
                    None
                }
            }
            ListMode::History { kind } => (task.state == history_state(*kind)).then(|| Placed {
                section: if self.grouped {
                    self.project_section(task)
                } else {
                    Section::Ended(*kind)
                },
                open: false,
            }),
            ListMode::Agenda {} => match (task.state, self.view_of(task)?) {
                (_, None) => None,
                (TaskState::Completed, Some(_)) => {
                    self.show_completed.then(|| ended(HistoryKind::Completed))
                }
                (TaskState::Cancelled, Some(_)) => {
                    self.show_cancelled.then(|| ended(HistoryKind::Cancelled))
                }
                (_, Some(view)) => Some(open(Section::Date(view))),
            },
            ListMode::DateView { view } => {
                if self.view_of(task)? != Some(*view) {
                    None
                } else {
                    self.by_state(task, open)
                }
            }
            ListMode::Search { .. } => {
                let matches = self
                    .needle
                    .as_deref()
                    .is_some_and(|needle| search_haystack(task).contains(needle));
                if matches {
                    self.by_state(task, open)
                } else {
                    None
                }
            }
        })
    }

    /// An open task goes to the open (or its project's) section; a terminal one
    /// to its ended section when the mode shows it (`partition`).
    fn by_state(&self, task: &Task, open: impl Fn(Section) -> Placed) -> Option<Placed> {
        let ended = |kind: HistoryKind| Placed {
            section: Section::Ended(kind),
            open: false,
        };
        match task.state {
            TaskState::Completed => self.show_completed.then(|| ended(HistoryKind::Completed)),
            TaskState::Cancelled => self.show_cancelled.then(|| ended(HistoryKind::Cancelled)),
            TaskState::Inbox | TaskState::Next | TaskState::Waiting | TaskState::Someday => {
                Some(open(if self.grouped {
                    self.project_section(task)
                } else {
                    Section::Open
                }))
            }
        }
    }

    /// The task's project section, or "No project" for none or an unknown one.
    fn project_section(&self, task: &Task) -> Section {
        match &task.project_id {
            Some(id) if self.read_set.projects.contains_key(id) => Section::Project(id.clone()),
            _ => Section::NoProject,
        }
    }

    /// `DateView(due:today:)`: none without a due date.
    fn view_of(&self, task: &Task) -> Result<Option<DateView>, DomainError> {
        let (Some(due), Some(today)) = (&task.due_date, self.today) else {
            return Ok(None);
        };
        let due = CalendarDay::parse_iso(due.as_str()).map_err(|_| invalid("due_date"))?;
        Ok(Some(match due.cmp(&today) {
            Ordering::Less => DateView::Overdue,
            Ordering::Equal => DateView::Today,
            Ordering::Greater => DateView::Upcoming,
        }))
    }

    // ------------------------------------------------------------------ keys

    /// Where a section sorts: open rows and date views first, then projects in
    /// `NameSortKey` order, "No project" after them, then Completed and
    /// Cancelled. The key is computed from the section alone (a project from its
    /// own record), so ordering needs no table over the projects.
    fn section_key(&self, section: &Section) -> SortKey {
        use KeyPart::Int;
        match section {
            Section::Open => vec![Int(0), Int(0)],
            Section::List(list) => vec![
                Int(0),
                Int(match list {
                    crate::types::OpenList::Next => 0,
                    crate::types::OpenList::Waiting => 1,
                    crate::types::OpenList::Inbox => 2,
                    crate::types::OpenList::Someday => 3,
                }),
            ],
            Section::Date(view) => vec![Int(0), Int(view_index(*view))],
            Section::Project(id) => {
                let mut key = vec![Int(1)];
                // A project section is only built for a project of the read set.
                if let Some(project) = self.read_set.projects.get(id) {
                    key.extend(project_order(project));
                }
                key
            }
            Section::NoProject => vec![Int(2)],
            Section::Ended(HistoryKind::Completed) => vec![Int(3)],
            Section::Ended(HistoryKind::Cancelled) => vec![Int(4)],
        }
    }

    /// The comparison key of a row: its section's key, then its order key.
    fn key(&self, task: &Task, section: &Section) -> Result<SortKey, DomainError> {
        let mut key = self.section_key(section);
        key.extend(self.item_key(task)?);
        Ok(key)
    }

    fn item_key(&self, task: &Task) -> Result<SortKey, DomainError> {
        use KeyPart::{Int, Text};
        let id = Text(task.id.as_str().to_owned());
        let manual = || -> Result<SortKey, DomainError> {
            Ok(vec![
                Int(queries::counter(&task.order_key, "order_key")?),
                Int(instant_rank(queries::instant(
                    &task.created_at,
                    "created_at",
                )?)),
                id.clone(),
            ])
        };
        Ok(match self.order {
            Order::Sorted(TaskSort::Manual) => manual()?,
            Order::Sorted(TaskSort::Due) => {
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
            Order::Sorted(TaskSort::Priority) => {
                let mut key = vec![Int(queries::priority_rank(task.priority))];
                key.extend(manual()?);
                key
            }
            Order::Sorted(TaskSort::Title) => {
                vec![
                    Text(nfc(&normalization::diacritic_fold(task.title.as_str()))),
                    id,
                ]
            }
            Order::Recency => {
                let ended = match task.state {
                    TaskState::Completed => task.completed_at.as_ref(),
                    TaskState::Cancelled => task.cancelled_at.as_ref(),
                    _ => None,
                };
                match ended {
                    Some(at) => {
                        let at = queries::instant(at, "ended_at")?;
                        vec![Int(0), Int(latest_first_rank(at)), id]
                    }
                    None => vec![Int(1), Int(0), id],
                }
            }
        })
    }

    // --------------------------------------------------------------- sections

    fn section_id(section: &Section) -> String {
        match section {
            Section::Open => "open".to_owned(),
            Section::List(list) => format!("list:{}", list.as_str()),
            Section::Project(id) => format!("project:{}", id.as_str()),
            Section::NoProject => "none".to_owned(),
            Section::Date(view) => format!("date:{}", view.as_str()),
            Section::Ended(kind) => kind.as_str().to_owned(),
        }
    }

    /// `TaskSection` without its rows.
    fn describe(&self, section: &Section) -> PageSection {
        let (title, kind) = match section {
            Section::Open => (None, SectionKind::Open {}),
            Section::List(list) => (
                Some(
                    match list {
                        crate::types::OpenList::Inbox => "Inbox",
                        crate::types::OpenList::Next => "Next",
                        crate::types::OpenList::Waiting => "Waiting",
                        crate::types::OpenList::Someday => "Someday / Maybe",
                    }
                    .to_owned(),
                ),
                SectionKind::List { list: *list },
            ),
            Section::Project(id) => (
                self.read_set
                    .projects
                    .get(id)
                    .map(|project| project.name.as_str().to_owned()),
                SectionKind::Project {
                    project_id: Some(id.clone()),
                },
            ),
            Section::NoProject => (
                Some(NO_PROJECT_TITLE.to_owned()),
                SectionKind::Project { project_id: None },
            ),
            Section::Date(view) => (
                Some(view_title(*view).to_owned()),
                SectionKind::DateView { view: *view },
            ),
            // History's one flat section is unnamed.
            Section::Ended(kind) => (
                (!matches!(self.mode, ListMode::History { .. }))
                    .then(|| history_title(*kind).to_owned()),
                match kind {
                    HistoryKind::Completed => SectionKind::Completed {},
                    HistoryKind::Cancelled => SectionKind::Cancelled {},
                },
            ),
        };
        PageSection {
            id: Self::section_id(section),
            title,
            kind,
            items: Vec::new(),
        }
    }

    /// The section a cursor names, if this query can produce it.
    fn section_from_id(&self, id: &str) -> Option<Section> {
        let section = match id {
            "open" => Section::Open,
            "none" => Section::NoProject,
            "completed" => Section::Ended(HistoryKind::Completed),
            "cancelled" => Section::Ended(HistoryKind::Cancelled),
            other => match other.split_once(':')? {
                ("list", list) => Section::List(crate::types::OpenList::from_wire(list)?),
                ("date", view) => Section::Date(DateView::from_wire(view)?),
                ("project", project) => {
                    let (known, _) = self
                        .read_set
                        .projects
                        .get_key_value(&ProjectId::parse(project).ok()?)?;
                    Section::Project(known.clone())
                }
                _ => return None,
            },
        };
        let allowed = match (&section, self.mode) {
            (
                Section::Open,
                ListMode::DateView { .. }
                | ListMode::Search { .. }
                | ListMode::OpenList { .. }
                | ListMode::Tag { .. },
            ) => !self.grouped,
            (Section::List(_), ListMode::Project { .. }) => true,
            (Section::Project(_) | Section::NoProject, _) => self.grouped,
            (Section::Date(_), ListMode::Agenda {}) => true,
            (Section::Ended(kind), ListMode::History { kind: wanted }) => {
                !self.grouped && kind == wanted
            }
            (Section::Ended(_), _) => true,
            _ => false,
        };
        allowed.then_some(section)
    }

    // ---------------------------------------------------------------- cursors

    /// The part of a section's order key a cursor is bound to: a project's
    /// `NameSortKey` as it stands now (everything after the class), nothing for
    /// the fixed sections, whose order never changes.
    fn bound_order<'k>(section: &Section, section_key: &'k [KeyPart]) -> &'k [KeyPart] {
        match section {
            Section::Project(_) => section_key.get(1..).unwrap_or_default(),
            _ => &[],
        }
    }

    /// The server's token format with the last row's section id and that
    /// section's order key in front of the row's own order key.
    fn encode_cursor(&self, filters: &Value, last: &Candidate) -> String {
        let section_key = self.section_key(&last.section);
        let mut key = vec![KeyPart::Text(Self::section_id(&last.section))];
        key.extend_from_slice(Self::bound_order(&last.section, &section_key));
        key.extend(last.key.iter().skip(section_key.len()).cloned());
        queries::encode_cursor(filters, &key)
    }

    /// The comparison key a cursor stands for, or a refusal when the token is
    /// malformed, was issued for other filters, names a section or a key shape
    /// this query cannot produce, or was issued while its section sorted
    /// elsewhere (the project was renamed, archived or unarchived), which would
    /// skip or repeat rows.
    fn decode_cursor(&self, cursor: &str, filters: &Value) -> Result<SortKey, DomainError> {
        let refused = || invalid("cursor");
        let parts = queries::decode_cursor_key(cursor, filters)?;
        let Some((KeyPart::Text(section), rest)) = parts.split_first() else {
            return Err(refused());
        };
        let section = self.section_from_id(section).ok_or_else(refused)?;
        let section_key = self.section_key(&section);
        let bound = Self::bound_order(&section, &section_key);
        let Some((issued, item)) = rest.split_at_checked(bound.len()) else {
            return Err(refused());
        };
        if issued != bound {
            return Err(refused());
        }
        let shape = self.order.shape();
        let fits = item.len() == shape.len()
            && item
                .iter()
                .zip(shape)
                .all(|(part, is_int)| matches!(part, KeyPart::Int(_)) == *is_int);
        if !fits {
            return Err(refused());
        }
        let mut key = section_key;
        key.extend(item.iter().cloned());
        Ok(key)
    }
}

/// `NameSortKey` of a project, the order of grouped sections: active before
/// archived, then the diacritic-folded normalized name, the normalized name,
/// the display name and the id.
fn project_order(project: &Project) -> SortKey {
    let normalized = nfc(&normalization::project_key(project.name.as_str()));
    vec![
        KeyPart::Int(u64::from(project.state == ProjectState::Archived)),
        KeyPart::Text(nfc(&normalization::diacritic_fold(&normalized))),
        KeyPart::Text(normalized),
        KeyPart::Text(nfc(project.name.as_str())),
        KeyPart::Text(project.id.as_str().to_owned()),
    ]
}

/// An instant as a non-negative integer that grows with time.
fn instant_rank(at: UtcInstant) -> u64 {
    u64::try_from(at.unix_micros() - UtcInstant::EARLIEST.unix_micros()).unwrap_or(0)
}

/// An instant as a non-negative integer that shrinks with time: latest first.
fn latest_first_rank(at: UtcInstant) -> u64 {
    u64::try_from(UtcInstant::LATEST.unix_micros() - at.unix_micros()).unwrap_or(0)
}
