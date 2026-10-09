//! Parity of the native list modes with the Apple kit (tasks.md T012, owner
//! decision 2026-10-09): History, Agenda, the date views and Search.
//!
//! The oracle is the Swift package, which is normative for these modes
//! (`GTDQueries.list`, `Queries+List.swift`, `Queries+Ordering.swift`). The
//! scenarios below are its tests, rebuilt over a `ReadSet` with the same
//! fixture rules as `QueryFixture` (every task, project and tag takes the next
//! serial number: id `task-000N`, order key `N * 10`, created `N` seconds after
//! the epoch) and the same expected titles, section ids and counts:
//!
//! * `QueriesHistoryTests`, `QueriesDateViewTests`, `QueriesSearchTests`;
//! * the grouping, ordering and filter scenarios of `QueriesListTests` that
//!   these modes share (`groupByProject`, `title order`, the filters);
//! * the cross-checks of `QueriesInvariantTests` (the agenda is the three date
//!   views, History holds every terminal task), over a generated store.
//!
//! No expectation here was produced by the Rust code under test. The Swift
//! suite could not be run in this environment (no Docker daemon, no Swift
//! toolchain), so the expected values are read from the committed Swift tests,
//! which CI runs.

mod support;

use std::collections::{BTreeMap, BTreeSet};

use bb_domain::calendar::UtcInstant;
use bb_domain::dispatch::{self, QueryFamily, QueryKind, query_kind, query_owner};
use bb_domain::types::{
    DomainError, ListModePage, Query, QueryInputs, QueryResult, ReadSet, Reason, SectionKind,
};
use serde_json::{Map, Value, json};

// ---------------------------------------------------------------- the fixture

const EPOCH: i64 = 1_790_000_000;
const TODAY: &str = "2026-09-29";

fn at_secs(offset: i64) -> String {
    UtcInstant::from_unix_seconds_clamped(EPOCH + offset).to_rfc3339()
}

/// `at(hours:)`: the epoch plus whole hours.
fn at_hours(hours: i64) -> String {
    at_secs(hours * 3600)
}

/// A task to add; the defaults of `QueryFixture.task`.
#[derive(Clone)]
struct T {
    title: String,
    state: &'static str,
    id: Option<String>,
    details: Option<String>,
    project: Option<String>,
    tags: Vec<String>,
    due: Option<String>,
    priority: &'static str,
    order_key: Option<i64>,
    ended_hours: Option<i64>,
}

fn t(title: &str) -> T {
    T {
        title: title.to_owned(),
        state: "next",
        id: None,
        details: None,
        project: None,
        tags: Vec::new(),
        due: None,
        priority: "none",
        order_key: None,
        ended_hours: None,
    }
}

impl T {
    fn state(self, state: &'static str) -> Self {
        Self { state, ..self }
    }
    fn id(self, id: &str) -> Self {
        Self {
            id: Some(id.to_owned()),
            ..self
        }
    }
    fn details(self, details: &str) -> Self {
        Self {
            details: Some(details.to_owned()),
            ..self
        }
    }
    fn project(self, project: &str) -> Self {
        Self {
            project: Some(project.to_owned()),
            ..self
        }
    }
    fn tags(self, tags: &[&str]) -> Self {
        Self {
            tags: tags.iter().map(|tag| (*tag).to_owned()).collect(),
            ..self
        }
    }
    fn due(self, due: &str) -> Self {
        Self {
            due: Some(due.to_owned()),
            ..self
        }
    }
    fn priority(self, priority: &'static str) -> Self {
        Self { priority, ..self }
    }
    fn order_key(self, order_key: i64) -> Self {
        Self {
            order_key: Some(order_key),
            ..self
        }
    }
    fn ended(self, hours: i64) -> Self {
        Self {
            ended_hours: Some(hours),
            ..self
        }
    }
}

#[derive(Default)]
struct Fixture {
    tasks: Vec<Value>,
    projects: Vec<Value>,
    tags: Vec<Value>,
    serial: i64,
}

impl Fixture {
    fn project(&mut self, name: &str, id: &str, archived: bool) -> String {
        self.serial += 1;
        self.projects.push(json!({
            "id": id, "name": name, "color": null,
            "state": if archived { "archived" } else { "active" }, "revision": "1",
            "desired_outcome": null, "archived_at": null, "archived_before_lossless": false,
            "created_at": "2026-09-01T09:00:00Z",
        }));
        id.to_owned()
    }

    fn tag(&mut self, name: &str, id: &str) -> String {
        self.serial += 1;
        self.tags.push(json!({
            "id": id, "name": name, "state": "active", "revision": "1",
            "created_at": "2026-09-01T09:00:00Z",
        }));
        id.to_owned()
    }

    fn add(&mut self, task: T) -> String {
        self.serial += 1;
        let id = task
            .id
            .clone()
            .unwrap_or_else(|| format!("task-{:04}", self.serial));
        let created = at_secs(self.serial);
        let ended = task.ended_hours.map(at_hours);
        let waiting = task.state == "waiting";
        self.tasks.push(json!({
            "id": id, "title": task.title, "details": task.details, "state": task.state,
            "project_id": task.project, "tag_ids": task.tags, "due_date": task.due,
            "priority": task.priority,
            "waiting_for": waiting.then_some("Sam"),
            "waiting_since": waiting.then(|| created.clone()),
            "order_key": task.order_key.unwrap_or(self.serial * 10).to_string(),
            "source_capture_ids": [], "created_at": created, "updated_at": created,
            "completed_at": if task.state == "completed" { ended.clone() } else { None },
            "cancelled_at": if task.state == "cancelled" { ended } else { None },
            "revision": "1", "consecutive_stalled_formulations": 0,
            "formulation": null, "parked": null,
        }));
        id
    }

    fn read_set(&self) -> ReadSet {
        let keyed = |rows: &[Value]| -> Value {
            Value::Object(
                rows.iter()
                    .map(|row| (row["id"].as_str().expect("an id").to_owned(), row.clone()))
                    .collect::<Map<_, _>>(),
            )
        };
        serde_json::from_value(json!({
            "tasks": keyed(&self.tasks), "projects": keyed(&self.projects),
            "tags": keyed(&self.tags),
        }))
        .expect("a valid read set")
    }

    fn list(&self, mode: Value, options: Value) -> R {
        run(&self.read_set(), mode, options, TODAY, "UTC")
    }

    fn plain(&self, mode: Value) -> R {
        self.list(mode, json!({}))
    }
}

fn inputs(day: &str, zone: &str) -> QueryInputs {
    run_inputs(&format!("{day}T12:00:00Z"), zone)
}

fn run_inputs(now: &str, zone: &str) -> QueryInputs {
    serde_json::from_value(json!({
        "now": now, "device_zone": zone,
        "policy": {
            "weekly_review": false, "navigator_provider": null,
            "navigator_available": false, "consent_text_version": 1,
        },
    }))
    .expect("valid inputs")
}

// ------------------------------------------------------------------- the modes

fn history(kind: &str) -> Value {
    json!({ "type": "history", "kind": kind })
}
fn agenda() -> Value {
    json!({ "type": "agenda" })
}
fn date_view(view: &str) -> Value {
    json!({ "type": "date_view", "view": view })
}
fn search(text: &str) -> Value {
    json!({ "type": "search", "text": text })
}

fn query_of(mode: Value, options: Value, limit: u32, after: Option<&str>) -> Query {
    serde_json::from_value(json!({
        "kind": "list_mode", "mode": mode, "options": options,
        "page": { "limit": limit, "after": after },
    }))
    .expect("a valid list mode query")
}

fn try_page(
    read_set: &ReadSet,
    query: &Query,
    inputs: &QueryInputs,
) -> Result<ListModePage, DomainError> {
    match dispatch::query(read_set, query, inputs)? {
        QueryResult::ListMode(page) => Ok(page),
        other => panic!("not a list mode page: {other:?}"),
    }
}

/// One unpaged result: the whole answer on a single page of 200.
fn run(read_set: &ReadSet, mode: Value, options: Value, day: &str, zone: &str) -> R {
    let page = try_page(
        read_set,
        &query_of(mode, options, 200, None),
        &inputs(day, zone),
    )
    .expect("the list mode is answered");
    assert!(!page.has_more, "a fixture fits one page");
    R(page)
}

/// `TaskListResult` with the helpers of `QueryFixtures.swift`.
struct R(ListModePage);

impl R {
    fn section_ids(&self) -> Vec<&str> {
        self.0.sections.iter().map(|s| s.id.as_str()).collect()
    }
    fn section_titles(&self) -> Vec<Option<&str>> {
        self.0.sections.iter().map(|s| s.title.as_deref()).collect()
    }
    fn titles(&self) -> Vec<Vec<&str>> {
        self.0
            .sections
            .iter()
            .map(|s| s.items.iter().map(|task| task.title.as_str()).collect())
            .collect()
    }
    fn all_titles(&self) -> Vec<&str> {
        self.titles().into_iter().flatten().collect()
    }
    fn titles_in(&self, id: &str) -> Vec<&str> {
        self.0
            .sections
            .iter()
            .find(|s| s.id == id)
            .map(|s| s.items.iter().map(|task| task.title.as_str()).collect())
            .unwrap_or_default()
    }
    fn open_count(&self) -> u32 {
        self.0.open_count
    }
}

// ----------------------------------------------------------- History (Swift)

#[test]
fn queries_026_fr_009_completed_history_is_most_recent_first_then_id_unknown_times_last() {
    let mut f = Fixture::default();
    f.add(t("Oldest").state("completed").ended(1));
    f.add(t("Newest").state("completed").ended(9));
    f.add(t("Tie b").state("completed").id("b").ended(5));
    f.add(t("Tie a").state("completed").id("a").ended(5));
    f.add(t("Unknown time").state("completed"));
    f.add(t("Cancelled").state("cancelled").ended(20));
    f.add(t("Open"));

    let result = f.plain(history("completed"));

    assert_eq!(result.section_ids(), ["completed"]);
    assert_eq!(result.section_titles(), [None]);
    assert!(matches!(
        result.0.sections[0].kind,
        SectionKind::Completed {}
    ));
    assert_eq!(
        result.all_titles(),
        ["Newest", "Tie a", "Tie b", "Oldest", "Unknown time"]
    );
    assert_eq!(result.open_count(), 0);
}

#[test]
fn queries_026_fr_009_cancelled_history_orders_by_cancellation_time() {
    let mut f = Fixture::default();
    f.add(t("Dropped early").state("cancelled").ended(1));
    f.add(t("Dropped late").state("cancelled").ended(3));
    f.add(t("Completed").state("completed").ended(2));

    let result = f.plain(history("cancelled"));

    assert_eq!(result.section_ids(), ["cancelled"]);
    assert!(matches!(
        result.0.sections[0].kind,
        SectionKind::Cancelled {}
    ));
    assert_eq!(result.all_titles(), ["Dropped late", "Dropped early"]);
}

#[test]
fn queries_026_fr_009_history_ignores_show_completed_and_show_cancelled() {
    let mut f = Fixture::default();
    f.add(t("Done").state("completed").ended(1));
    f.add(t("Dropped").state("cancelled").ended(1));

    let result = f.list(
        history("completed"),
        json!({ "show_completed": false, "show_cancelled": true }),
    );

    assert_eq!(result.all_titles(), ["Done"]);
}

#[test]
fn queries_026_fr_009_history_honours_an_explicit_sort() {
    let mut f = Fixture::default();
    f.add(t("Bravo").state("completed").ended(9));
    f.add(t("alpha").state("completed").ended(1));
    f.add(t("Charlie").state("completed").ended(5));

    let result = f.list(history("completed"), json!({ "sort": "title" }));

    assert_eq!(result.all_titles(), ["alpha", "Bravo", "Charlie"]);
}

#[test]
fn queries_026_fr_009_history_groups_by_project_and_applies_filters() {
    let mut f = Fixture::default();
    let home = f.project("Home", "p-home", false);
    let phone = f.tag("phone", "tag-phone");
    f.add(
        t("Home call")
            .state("completed")
            .project(&home)
            .tags(&[&phone])
            .ended(2),
    );
    f.add(t("Home chore").state("completed").project(&home).ended(3));
    f.add(
        t("Loose call old")
            .state("completed")
            .tags(&[&phone])
            .priority("high")
            .ended(1),
    );
    f.add(
        t("Loose call new")
            .state("completed")
            .tags(&[&phone])
            .priority("high")
            .ended(4),
    );

    let grouped = f.list(
        history("completed"),
        json!({ "group_by_project": true, "tag_filter": phone }),
    );
    assert_eq!(grouped.section_ids(), ["project:p-home", "none"]);
    assert_eq!(
        grouped.titles(),
        [vec!["Home call"], vec!["Loose call new", "Loose call old"]]
    );
    assert_eq!(grouped.open_count(), 0);

    let high_only = f.list(history("completed"), json!({ "priorities": ["high"] }));
    assert_eq!(high_only.all_titles(), ["Loose call new", "Loose call old"]);
}

#[test]
fn queries_026_fr_009_empty_history_has_no_sections() {
    let mut f = Fixture::default();
    f.add(t("Open"));

    let result = f.plain(history("cancelled"));

    assert!(result.0.sections.is_empty());
    assert_eq!(result.open_count(), 0);
}

// --------------------------------------------------- Agenda and date views

/// `QueriesDateViewTests.dated()`; today is 2026-09-29.
fn dated() -> Fixture {
    let mut f = Fixture::default();
    f.add(t("Undated"));
    f.add(t("Last week").due("2026-09-22").order_key(50));
    f.add(
        t("Yesterday")
            .state("inbox")
            .due("2026-09-28")
            .order_key(10),
    );
    f.add(
        t("Today, key 30")
            .state("waiting")
            .due("2026-09-29")
            .order_key(30),
    );
    f.add(
        t("Today, key 20")
            .state("someday")
            .due("2026-09-29")
            .order_key(20),
    );
    f.add(t("Tomorrow").due("2026-09-30").order_key(5));
    f.add(t("Next year").due("2027-01-01").order_key(1));
    f.add(t("Done yesterday").state("completed").due("2026-09-28"));
    f.add(t("Dropped today").state("cancelled").due("2026-09-29"));
    f
}

#[test]
fn queries_026_fr_017_agenda_has_overdue_today_and_upcoming_over_open_tasks() {
    let result = dated().plain(agenda());

    assert_eq!(
        result.section_ids(),
        ["date:overdue", "date:today", "date:upcoming"]
    );
    assert_eq!(
        result.section_titles(),
        [Some("Overdue"), Some("Today"), Some("Upcoming")]
    );
    let kinds: Vec<_> = result.0.sections.iter().map(|s| s.kind.clone()).collect();
    assert_eq!(
        kinds,
        [
            SectionKind::DateView {
                view: "overdue".parse_view()
            },
            SectionKind::DateView {
                view: "today".parse_view()
            },
            SectionKind::DateView {
                view: "upcoming".parse_view()
            },
        ]
    );
    assert_eq!(
        result.titles(),
        [
            vec!["Last week", "Yesterday"],
            vec!["Today, key 20", "Today, key 30"],
            vec!["Tomorrow", "Next year"],
        ]
    );
    assert_eq!(result.open_count(), 6);
}

trait ParseView {
    fn parse_view(&self) -> bb_domain::types::DateView;
}
impl ParseView for str {
    fn parse_view(&self) -> bb_domain::types::DateView {
        bb_domain::types::DateView::from_wire(self).expect("a date view")
    }
}

#[test]
fn queries_026_fr_017_agenda_omits_empty_sections() {
    let mut f = Fixture::default();
    f.add(t("Tomorrow").due("2026-09-30"));
    f.add(t("Done today").state("completed").due("2026-09-29"));

    assert_eq!(f.plain(agenda()).section_ids(), ["date:upcoming"]);
}

#[test]
fn queries_026_fr_009_agenda_honours_an_explicit_sort_inside_each_section() {
    let mut f = Fixture::default();
    f.add(
        t("Low today")
            .due("2026-09-29")
            .priority("low")
            .order_key(1),
    );
    f.add(
        t("High today")
            .due("2026-09-29")
            .priority("high")
            .order_key(2),
    );
    f.add(
        t("Later upcoming")
            .due("2026-10-05")
            .priority("medium")
            .order_key(3),
    );
    f.add(
        t("Sooner upcoming")
            .due("2026-10-01")
            .priority("none")
            .order_key(4),
    );

    let result = f.list(agenda(), json!({ "sort": "priority" }));

    assert_eq!(
        result.titles(),
        [
            vec!["High today", "Low today"],
            vec!["Later upcoming", "Sooner upcoming"]
        ]
    );
}

#[test]
fn queries_026_fr_009_agenda_ignores_grouping_and_appends_dated_history_when_asked() {
    let result = dated().list(
        agenda(),
        json!({ "group_by_project": true, "show_completed": true, "show_cancelled": true }),
    );

    assert_eq!(
        result.section_ids(),
        [
            "date:overdue",
            "date:today",
            "date:upcoming",
            "completed",
            "cancelled"
        ]
    );
    assert_eq!(result.titles_in("completed"), ["Done yesterday"]);
    assert_eq!(result.titles_in("cancelled"), ["Dropped today"]);
    assert_eq!(result.section_titles()[3], Some("Completed"));
    assert_eq!(result.open_count(), 6);
}

#[test]
fn queries_026_fr_017_a_date_view_shows_one_range_of_open_tasks_in_a_single_section() {
    for (view, expected) in [
        ("overdue", vec!["Last week", "Yesterday"]),
        ("today", vec!["Today, key 20", "Today, key 30"]),
        ("upcoming", vec!["Tomorrow", "Next year"]),
    ] {
        let result = dated().plain(date_view(view));

        assert_eq!(result.section_ids(), ["open"], "{view}");
        assert_eq!(result.section_titles(), [None], "{view}");
        assert_eq!(result.all_titles(), expected, "{view}");
        assert_eq!(result.open_count() as usize, expected.len(), "{view}");
    }
}

#[test]
fn queries_026_fr_009_date_views_sort_by_due_date_when_the_sort_is_manual() {
    let mut f = Fixture::default();
    f.add(t("Later, key 1").due("2026-10-09").order_key(1));
    f.add(t("Sooner, key 2").due("2026-10-01").order_key(2));

    assert_eq!(
        f.plain(date_view("upcoming")).all_titles(),
        ["Sooner, key 2", "Later, key 1"]
    );
    assert_eq!(
        f.list(date_view("upcoming"), json!({ "sort": "title" }))
            .all_titles(),
        ["Later, key 1", "Sooner, key 2"]
    );
}

#[test]
fn queries_026_fr_009_a_date_view_groups_by_project_and_appends_its_ranges_history() {
    let mut f = Fixture::default();
    let work = f.project("Work", "p-work", false);
    f.add(t("Work today").project(&work).due("2026-09-29"));
    f.add(t("Loose today").state("inbox").due("2026-09-29"));
    f.add(t("Work tomorrow").project(&work).due("2026-09-30"));
    f.add(t("Done today").state("completed").due("2026-09-29"));
    f.add(t("Done tomorrow").state("completed").due("2026-09-30"));

    let result = f.list(
        date_view("today"),
        json!({ "group_by_project": true, "show_completed": true }),
    );

    assert_eq!(
        result.section_ids(),
        ["project:p-work", "none", "completed"]
    );
    assert_eq!(
        result.titles(),
        [vec!["Work today"], vec!["Loose today"], vec!["Done today"]]
    );
}

#[test]
fn queries_026_fr_017_today_is_an_input_the_same_data_moves_between_views_as_the_day_changes() {
    let mut f = Fixture::default();
    f.add(t("Due 30th").due("2026-09-30"));
    let rs = f.read_set();
    let titles = |view: &str, day: &str| {
        run(&rs, date_view(view), json!({}), day, "UTC")
            .all_titles()
            .into_iter()
            .map(str::to_owned)
            .collect::<Vec<_>>()
    };

    assert_eq!(titles("upcoming", "2026-09-29"), ["Due 30th"]);
    assert_eq!(titles("today", "2026-09-30"), ["Due 30th"]);
    assert_eq!(titles("overdue", "2026-10-01"), ["Due 30th"]);
}

#[test]
fn queries_026_fr_017_the_day_is_the_device_zones_day_of_the_instant() {
    let mut f = Fixture::default();
    f.add(t("Due 30th").due("2026-09-30"));
    let rs = f.read_set();
    // 23:30 UTC on the 29th is already 12:30 on the 30th in Auckland (UTC+13),
    // and 16:30 on the 29th in Los Angeles (UTC-7).
    let now = "2026-09-29T23:30:00Z";
    let view_in = |zone: &str| {
        let query = query_of(agenda(), json!({}), 200, None);
        let page = try_page(&rs, &query, &run_inputs(now, zone)).expect("answered");
        page.sections[0].id.clone()
    };

    assert_eq!(view_in("Pacific/Auckland"), "date:today");
    assert_eq!(view_in("America/Los_Angeles"), "date:upcoming");
    assert_eq!(view_in("UTC"), "date:upcoming");
}

#[test]
fn queries_026_fr_017_year_and_month_boundaries_compare_chronologically() {
    let mut f = Fixture::default();
    f.add(t("Dec 31").due("2025-12-31"));
    f.add(t("Jan 1").due("2026-01-01"));
    f.add(t("Feb 29").due("2028-02-29"));
    let rs = f.read_set();

    let result = run(&rs, agenda(), json!({}), "2026-01-01", "UTC");

    assert_eq!(
        result.titles(),
        [vec!["Dec 31"], vec!["Jan 1"], vec!["Feb 29"]]
    );
}

#[test]
fn queries_026_fr_017_only_the_day_modes_read_the_device_zone() {
    let mut f = Fixture::default();
    f.add(t("Report").due("2026-09-30").state("completed").ended(1));
    let rs = f.read_set();
    let bad = run_inputs("2026-09-29T12:00:00Z", "Mars/Olympus");

    for mode in [agenda(), date_view("today")] {
        let error = try_page(&rs, &query_of(mode, json!({}), 10, None), &bad)
            .expect_err("a day mode needs a zone");
        assert_eq!(
            (error.reason, error.field.as_deref()),
            (Reason::InvalidTimeZone, Some("device_zone"))
        );
    }
    for mode in [history("completed"), search("report")] {
        assert!(try_page(&rs, &query_of(mode, json!({}), 10, None), &bad).is_ok());
    }
}

// ------------------------------------------------------------- Search (Swift)

#[test]
fn queries_026_fr_002_search_ignores_case_diacritics_and_width_and_folds_like_the_kit() {
    for (query, title) in [
        ("café", "Book the Cafe"),
        ("CAFE", "Book the Café"),
        ("ｃａｆｅ", "Book the café"), // full-width query
        ("cafe", "Book the ｃａｆé"),  // full-width title
        ("strasse", "Walk down the Straße"),
        ("STRASSE", "Walk down the strasse"),
        ("naive", "A naïve plan"),
        ("istanbul", "Fly to İstanbul"),
        ("file", "Rename the ﬁle"), // ligature
    ] {
        let mut f = Fixture::default();
        f.add(t(title));
        f.add(t("Unrelated"));

        assert_eq!(f.plain(search(query)).all_titles(), [title], "{query}");
    }
}

#[test]
fn queries_026_fr_002_the_search_query_is_trimmed_and_its_whitespace_collapsed() {
    let mut f = Fixture::default();
    f.add(t("Buy oat milk"));

    assert_eq!(
        f.plain(search("  buy \t  oat\n milk  ")).all_titles(),
        ["Buy oat milk"]
    );
}

#[test]
fn queries_026_fr_002_search_collapses_the_kits_whitespace_not_pythons() {
    // `Character.isWhitespace` is Unicode White_Space: U+001F is not one (the
    // server's `str.split()` treats it as a space; register entry C-05/C-02).
    let mut f = Fixture::default();
    f.add(t("Buy oat milk"));
    f.add(t("Nbsp"));

    assert_eq!(
        f.plain(search("buy\u{a0}oat\u{2003}milk")).all_titles(),
        ["Buy oat milk"],
        "no-break and em spaces collapse"
    );
    assert!(f.plain(search("buy\u{1f}oat milk")).all_titles().is_empty());
}

#[test]
fn queries_026_fr_002_search_reads_notes_but_a_match_cannot_span_title_and_notes() {
    let mut f = Fixture::default();
    f.add(t("Buy milk").details("From the corner shop"));
    f.add(t("Plain"));

    assert_eq!(f.plain(search("corner")).all_titles(), ["Buy milk"]);
    assert!(f.plain(search("milk from")).all_titles().is_empty());
}

#[test]
fn queries_026_fr_002_a_blank_search_query_matches_nothing() {
    for query in ["", " ", "\n\t", "\u{301}"] {
        let mut f = Fixture::default();
        f.add(t("Anything"));

        let result = f.list(search(query), json!({ "show_completed": true }));

        assert!(result.0.sections.is_empty(), "{query:?}");
        assert_eq!(result.open_count(), 0, "{query:?}");
        assert!(!result.0.has_more && result.0.next_cursor.is_none());
    }
}

#[test]
fn queries_026_fr_009_search_covers_every_state_open_first_then_completed_then_cancelled() {
    let mut f = Fixture::default();
    f.add(t("Report done").state("completed").ended(1));
    f.add(t("Report dropped").state("cancelled").ended(1));
    f.add(t("Report draft").state("someday"));
    f.add(t("Report inbox").state("inbox"));
    let home = f.project("Home", "p-home", false);
    f.add(t("Report for home").state("inbox").project(&home));
    f.add(t("Unrelated"));

    let result = f.plain(search("report"));

    assert_eq!(result.section_ids(), ["open", "completed", "cancelled"]);
    assert_eq!(
        result.section_titles(),
        [None, Some("Completed"), Some("Cancelled")]
    );
    assert_eq!(
        result.titles(),
        [
            vec!["Report draft", "Report inbox", "Report for home"],
            vec!["Report done"],
            vec!["Report dropped"],
        ]
    );
    assert_eq!(result.open_count(), 3);
}

#[test]
fn queries_026_fr_009_search_honours_the_sort_filters_and_group_by_project() {
    let mut f = Fixture::default();
    let home = f.project("Home", "p-home", false);
    let phone = f.tag("phone", "tag-phone");
    f.add(
        t("Call plumber")
            .project(&home)
            .tags(&[&phone])
            .priority("low"),
    );
    f.add(t("Call bank").tags(&[&phone]).priority("high"));
    f.add(t("Call mum").priority("high"));
    f.add(
        t("Called gran")
            .state("completed")
            .tags(&[&phone])
            .priority("high"),
    );

    let sorted = f.list(search("call"), json!({ "sort": "priority" }));
    assert_eq!(
        sorted.titles(),
        [
            vec!["Call bank", "Call mum", "Call plumber"],
            vec!["Called gran"]
        ]
    );

    let filtered = f.list(
        search("call"),
        json!({ "priorities": ["high"], "tag_filter": phone }),
    );
    assert_eq!(filtered.titles(), [vec!["Call bank"], vec!["Called gran"]]);

    let grouped = f.list(search("call"), json!({ "group_by_project": true }));
    assert_eq!(
        grouped.section_ids(),
        ["project:p-home", "none", "completed"]
    );
}

#[test]
fn queries_026_fr_002_the_diacritic_fold_is_the_kits_query_text_fold() {
    use bb_domain::normalization::diacritic_fold;
    // The fold cases of `QueriesSearchTests` and `QueriesListTests.titleOrder`.
    for (raw, folded) in [
        ("Straße", "strasse"),
        ("Éclair", "eclair"),
        ("ｃａｆé", "cafe"),
        ("İstanbul", "istanbul"),
        ("ﬁle", "file"),
        ("A naïve plan", "a naive plan"),
        ("\u{301}", ""),
        ("Привет", "привет"),
    ] {
        assert_eq!(diacritic_fold(raw), folded, "{raw:?}");
    }
    // Decomposed and precomposed spellings fold alike.
    assert_eq!(diacritic_fold("e\u{301}clair"), diacritic_fold("Éclair"));
}

// ------------------------------------------ grouping and ordering shared with lists

#[test]
fn queries_026_fr_009_title_order_ignores_case_diacritics_and_width_then_falls_back_to_id() {
    let mut f = Fixture::default();
    for (id, title) in [
        ("t1", "zebra"),
        ("t3", "Éclair"),
        ("t2", "eclair"),
        ("t4", "Banana"),
        ("t5", "ａpple"), // full-width a
        ("t6", "apple pie"),
        ("t7", "Dates"),
    ] {
        f.add(t(title).state("completed").id(id).ended(1));
    }

    let result = f.list(history("completed"), json!({ "sort": "title" }));

    assert_eq!(
        result.all_titles(),
        [
            "ａpple",
            "apple pie",
            "Banana",
            "Dates",
            "eclair",
            "Éclair",
            "zebra"
        ]
    );
}

#[test]
fn queries_026_fr_009_grouped_sections_follow_the_kits_name_key_not_the_servers() {
    // `NameSortKey` folds diacritics, so Éclair sits beside eclair, before
    // zulu; the server's `strip().casefold()` would put it last (C-06).
    let mut g = Fixture::default();
    let zulu = g.project("zulu", "p-zulu", false);
    let alpha = g.project("Alpha", "p-alpha", false);
    let eclair = g.project("Éclair", "p-eclair", false);
    let bravo = g.project("bravo", "p-bravo", false);
    for (title, project, key) in [
        ("Loose 2", None, 2),
        ("Zulu 1", Some(&zulu), 1),
        ("Alpha 2", Some(&alpha), 20),
        ("Alpha 1", Some(&alpha), 10),
        ("Eclair 1", Some(&eclair), 3),
        ("Loose 1", None, 1),
        ("Bravo 1", Some(&bravo), 4),
    ] {
        let task = t(title).state("completed").order_key(key).ended(key);
        g.add(match project {
            Some(project) => task.project(project),
            None => task,
        });
    }
    let result = g.list(
        history("completed"),
        json!({ "group_by_project": true, "sort": "manual" }),
    );
    assert_eq!(
        result.section_ids(),
        [
            "project:p-alpha",
            "project:p-bravo",
            "project:p-eclair",
            "project:p-zulu",
            "none"
        ]
    );
    assert_eq!(
        result.section_titles(),
        [
            Some("Alpha"),
            Some("bravo"),
            Some("Éclair"),
            Some("zulu"),
            Some("No project")
        ]
    );
    // History order inside a project is recency, not the project's own order.
    assert_eq!(result.titles_in("project:p-alpha"), ["Alpha 2", "Alpha 1"]);
    assert_eq!(result.titles_in("none"), ["Loose 2", "Loose 1"]);
}

#[test]
fn queries_026_fr_009_archived_projects_follow_active_ones_and_unknown_projects_are_no_project() {
    let mut f = Fixture::default();
    let old = f.project("Aardvark", "p-old", true);
    let live = f.project("Zebra", "p-live", false);
    f.add(t("In archived").project(&old).state("inbox"));
    f.add(t("In active").project(&live).state("inbox"));
    f.add(t("Dangling").project("p-missing").state("inbox"));

    let result = f.list(search("in"), json!({ "group_by_project": true }));

    assert_eq!(
        result.section_ids(),
        ["project:p-live", "project:p-old", "none"]
    );
    assert_eq!(
        result.titles(),
        [vec!["In active"], vec!["In archived"], vec!["Dangling"]]
    );
}

#[test]
fn queries_026_fr_009_completed_and_cancelled_sections_stay_flat_when_grouping() {
    let mut f = Fixture::default();
    let home = f.project("Home", "p-home", false);
    f.add(t("Open in home").project(&home));
    f.add(t("Done in home").state("completed").project(&home));
    f.add(t("Done loose").state("completed"));

    let result = f.list(search("done open"), json!({ "group_by_project": true }));
    assert!(result.0.sections.is_empty());

    let result = f.list(search("in"), json!({ "group_by_project": true }));
    assert_eq!(result.section_ids(), ["project:p-home", "completed"]);
    assert_eq!(result.titles_in("completed"), ["Done in home"]);
}

#[test]
fn queries_026_fr_009_filters_apply_to_every_section_and_an_empty_priority_filter_means_all() {
    let mut f = Fixture::default();
    let phone = f.tag("phone", "tag-phone");
    f.add(t("Call high").priority("high").tags(&[&phone]));
    f.add(t("Call low").priority("low").tags(&[&phone]));
    f.add(t("Call none").tags(&[&phone]));
    f.add(t("Call done high").state("completed").priority("high"));
    f.add(t("Call done low").state("completed").priority("low"));

    let both = f.list(
        search("call"),
        json!({ "priorities": ["high", "none", "high"] }),
    );
    assert_eq!(
        both.titles(),
        [vec!["Call high", "Call none"], vec!["Call done high"]]
    );
    assert_eq!(both.open_count(), 2);
    assert_eq!(
        f.list(search("call"), json!({ "priorities": [] }))
            .open_count(),
        3
    );

    let tagged = f.list(search("call"), json!({ "tag_filter": phone }));
    assert_eq!(tagged.all_titles(), ["Call high", "Call low", "Call none"]);
    let unknown = f.list(search("call"), json!({ "tag_filter": "tag-gone" }));
    assert!(
        unknown.0.sections.is_empty(),
        "an unknown tag matches nothing"
    );
}

// ------------------------------------------------------------ the generated store

/// A task of the generated store, with what the independent reference needs.
#[derive(Clone)]
struct Gen {
    id: String,
    title: String,
    state: &'static str,
    project: Option<String>,
    tag: Option<String>,
    due: Option<String>,
    priority: &'static str,
    order_key: i64,
    created: i64,
    ended: Option<i64>,
}

struct Lcg(u64);
impl Lcg {
    fn next(&mut self, bound: u64) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        (self.0 >> 33) % bound
    }
}

const STATES: [&str; 6] = [
    "inbox",
    "next",
    "waiting",
    "someday",
    "completed",
    "cancelled",
];
const PRIORITIES: [&str; 4] = ["none", "low", "medium", "high"];
const WORDS: [&str; 8] = [
    "call", "email", "buy", "Café", "report", "plan", "fix", "read",
];

fn day_offset(base: &str, days: i64) -> String {
    let day = bb_domain::calendar::CalendarDay::parse_iso(base).expect("a day");
    day.add_days(days).iso_string()
}

/// A few thousand tasks over 12 projects (the last archived) and 6 tags, with
/// many ties on order key, due day and end time so that every tie-break runs.
fn generated(count: usize) -> (ReadSet, Vec<Gen>) {
    let mut rng = Lcg(0xB2A1_7D0C);
    let mut f = Fixture::default();
    let projects: Vec<String> = (0..12)
        .map(|n| f.project(&format!("Project {n}"), &format!("p-{n:02}"), n == 11))
        .collect();
    let tags: Vec<String> = (0..6)
        .map(|n| f.tag(&format!("tag{n}"), &format!("tag-{n}")))
        .collect();
    let mut rows = Vec::new();
    for index in 0..count {
        let state = STATES[rng.next(6) as usize];
        let project = (rng.next(2) == 0).then(|| projects[rng.next(12) as usize].clone());
        let tag = (rng.next(3) == 0).then(|| tags[rng.next(6) as usize].clone());
        let due = (rng.next(2) == 0).then(|| day_offset(TODAY, rng.next(41) as i64 - 20));
        let priority = PRIORITIES[rng.next(4) as usize];
        let order_key = rng.next(51) as i64;
        let ended = rng.next(500) as i64;
        let title = format!("{} {index}", WORDS[index % WORDS.len()]);
        let mut task = t(&title)
            .state(state)
            .priority(priority)
            .order_key(order_key)
            .ended(ended);
        if let Some(project) = &project {
            task = task.project(project);
        }
        if let Some(tag) = &tag {
            task = task.tags(&[tag]);
        }
        if let Some(due) = &due {
            task = task.due(due);
        }
        let id = f.add(task);
        let terminal = matches!(state, "completed" | "cancelled");
        rows.push(Gen {
            id,
            title,
            state,
            project,
            tag,
            due,
            priority,
            order_key,
            created: f.serial,
            ended: terminal.then_some(ended * 3600),
        });
    }
    (f.read_set(), rows)
}

fn priority_rank(priority: &str) -> u64 {
    match priority {
        "high" => 0,
        "medium" => 1,
        "low" => 2,
        _ => 3,
    }
}

/// An ASCII stand-in for the kit's fold, enough for the generated titles.
fn fold(title: &str) -> String {
    title.to_lowercase().replace('é', "e")
}

/// Plain sorts of `TaskOrdering`, written independently of the crate.
fn sort_rows(rows: &mut [&Gen], sort: &str) {
    let manual = |g: &Gen| (g.order_key, g.created, g.id.clone());
    match sort {
        "manual" => rows.sort_by_key(|g| manual(g)),
        "due" => rows.sort_by_key(|g| {
            (
                g.due.is_none(),
                g.due.clone().unwrap_or_default(),
                manual(g),
            )
        }),
        "priority" => rows.sort_by_key(|g| (priority_rank(g.priority), manual(g))),
        "title" => rows.sort_by_key(|g| (fold(&g.title), g.id.clone())),
        "recency" => rows.sort_by_key(|g| {
            (
                g.ended.is_none(),
                std::cmp::Reverse(g.ended.unwrap_or(0)),
                g.id.clone(),
            )
        }),
        other => panic!("unknown sort {other}"),
    }
}

/// The unpaged oracle: `(section id, task id)` in order, and the open count,
/// built the way `TaskListBuilder` does (partition, sort, section).
fn reference(
    rows: &[Gen],
    mode: &str,
    detail: &str,
    sort: &str,
    grouped: bool,
    tag_filter: Option<&str>,
) -> (Vec<(String, String)>, u32) {
    let is_open = |g: &Gen| !matches!(g.state, "completed" | "cancelled");
    let view_of = |g: &Gen| {
        g.due.as_deref().map(|due| {
            if due < TODAY {
                "overdue"
            } else if due == TODAY {
                "today"
            } else {
                "upcoming"
            }
        })
    };
    let date_sort = if sort == "manual" { "due" } else { sort };
    let passing: Vec<&Gen> = rows
        .iter()
        .filter(|g| tag_filter.is_none_or(|tag| g.tag.as_deref() == Some(tag)))
        .collect();
    let project_order = |id: &str| -> u64 {
        // Names are "Project n" with n < 12; Swift's key is the folded name, so
        // "project 10" sorts before "project 2"; the archived one (11) is last.
        let n: u64 = id.trim_start_matches("p-").parse().expect("a project");
        let name = format!("project {n}");
        let archived = n == 11;
        let mut all: Vec<(bool, String)> =
            (0..12).map(|k| (k == 11, format!("project {k}"))).collect();
        all.sort();
        all.iter()
            .position(|entry| *entry == (archived, name.clone()))
            .expect("listed") as u64
    };
    let section_rank = |section: &str| -> (u64, String) {
        match section {
            "open" => (0, String::new()),
            s if s.starts_with("date:") => (
                match &s[5..] {
                    "overdue" => 0,
                    "today" => 1,
                    _ => 2,
                },
                String::new(),
            ),
            s if s.starts_with("project:") => (project_order(&s[8..]), String::new()),
            "none" => (100, String::new()),
            "completed" => (200, String::new()),
            "cancelled" => (201, String::new()),
            other => panic!("unknown section {other}"),
        }
    };
    let project_section = |g: &Gen| match &g.project {
        Some(project) => format!("project:{project}"),
        None => "none".to_owned(),
    };
    // (section, row) pairs before ordering, then the order inside sections.
    let mut placed: Vec<(String, &Gen)> = Vec::new();
    let mut open_count = 0;
    for g in &passing {
        let section = match (mode, detail) {
            ("history", kind) => (g.state == kind).then(|| {
                if grouped {
                    project_section(g)
                } else {
                    kind.to_owned()
                }
            }),
            ("agenda", _) => view_of(g).map(|view| {
                if is_open(g) {
                    format!("date:{view}")
                } else {
                    g.state.to_owned()
                }
            }),
            ("date_view", view) => (view_of(g) == Some(view)).then(|| {
                if is_open(g) {
                    if grouped {
                        project_section(g)
                    } else {
                        "open".to_owned()
                    }
                } else {
                    g.state.to_owned()
                }
            }),
            ("search", needle) => fold(&g.title).contains(needle).then(|| {
                if is_open(g) {
                    if grouped {
                        project_section(g)
                    } else {
                        "open".to_owned()
                    }
                } else {
                    g.state.to_owned()
                }
            }),
            other => panic!("unknown mode {other:?}"),
        };
        if let Some(section) = section {
            open_count += u32::from(is_open(g));
            placed.push((section, g));
        }
    }
    let order = match (mode, sort) {
        ("history", "manual") => "recency",
        ("agenda" | "date_view", _) => date_sort,
        _ => sort,
    };
    let mut by_section: BTreeMap<(u64, String), Vec<&Gen>> = BTreeMap::new();
    let mut names: BTreeMap<(u64, String), String> = BTreeMap::new();
    for (section, g) in placed {
        let rank = section_rank(&section);
        names.insert(rank.clone(), section);
        by_section.entry(rank).or_default().push(g);
    }
    let mut out = Vec::new();
    for (rank, mut rows) in by_section {
        sort_rows(&mut rows, order);
        for g in rows {
            out.push((names[&rank].clone(), g.id.clone()));
        }
    }
    (out, open_count)
}

fn page_through(
    rs: &ReadSet,
    mode: &Value,
    options: &Value,
    limit: u32,
) -> (Vec<(String, String)>, u32, usize) {
    let (mut seen, mut after, mut pages, mut open) = (Vec::new(), None::<String>, 0, None);
    loop {
        let query = query_of(mode.clone(), options.clone(), limit, after.as_deref());
        let page = try_page(rs, &query, &inputs(TODAY, "UTC")).expect("a page");
        pages += 1;
        let rows: usize = page.sections.iter().map(|s| s.items.len()).sum();
        assert!(rows <= limit as usize, "a page holds at most `limit` rows");
        assert_eq!(page.has_more, page.next_cursor.is_some());
        assert_eq!(*open.get_or_insert(page.open_count), page.open_count);
        let mut ids = BTreeSet::new();
        for section in &page.sections {
            assert!(!section.items.is_empty(), "a page has no empty section");
            assert!(ids.insert(&section.id), "a section appears once per page");
            for item in &section.items {
                seen.push((section.id.clone(), item.id.as_str().to_owned()));
            }
        }
        if !page.has_more {
            return (seen, open.unwrap_or(0), pages);
        }
        after = page.next_cursor;
    }
}

#[test]
fn queries_026_fr_026_pages_of_a_large_store_concatenate_to_the_unpaged_order_for_every_mode() {
    let (rs, rows) = generated(3_000);
    assert_eq!(rs.tasks.len(), 3_000);
    let cases: Vec<(&str, &str, Value)> = vec![
        ("history", "completed", history("completed")),
        ("history", "cancelled", history("cancelled")),
        ("agenda", "", agenda()),
        ("date_view", "overdue", date_view("overdue")),
        ("date_view", "today", date_view("today")),
        ("date_view", "upcoming", date_view("upcoming")),
        ("search", "caf", search("CAF")),
        ("search", "report 1", search("Report 1")),
    ];
    let mut ran = 0;
    for (mode, detail, wire) in cases {
        for sort in ["manual", "due", "priority", "title"] {
            for grouped in [false, true] {
                for tag_filter in [None, Some("tag-2")] {
                    let options = json!({
                        "sort": sort, "group_by_project": grouped,
                        "show_completed": true, "show_cancelled": true,
                        "tag_filter": tag_filter,
                    });
                    // The agenda is already sectioned by date and ignores grouping.
                    let (expected, open) = reference(
                        &rows,
                        mode,
                        detail,
                        sort,
                        grouped && mode != "agenda",
                        tag_filter,
                    );
                    assert!(
                        mode != "history" || tag_filter.is_some() || !expected.is_empty(),
                        "{mode} {detail}: the store has rows"
                    );
                    // A page size that divides nothing for the large result sets,
                    // and a small one for the tag-narrowed sets, so cursors chain.
                    {
                        let limit = if tag_filter.is_some() { 13 } else { 199 };
                        let label = format!(
                            "{mode} {detail} {sort} grouped={grouped} {tag_filter:?} limit={limit}"
                        );
                        let (seen, seen_open, pages) = page_through(&rs, &wire, &options, limit);
                        assert_eq!(seen.len(), expected.len(), "{label}: no gap, no duplicate");
                        assert_eq!(seen, expected, "{label}: the pages are the full order");
                        assert_eq!(seen_open, open, "{label}: the open count");
                        assert_eq!(
                            pages,
                            expected.len().div_ceil(limit as usize).max(1),
                            "{label}"
                        );
                        ran += 1;
                    }
                }
            }
        }
    }
    assert_eq!(ran, 8 * 4 * 2 * 2, "every case ran");
}

#[test]
fn queries_026_fr_026_a_page_is_bounded_by_its_limit_however_large_the_store_is() {
    let (rs, _) = generated(10_000);
    assert_eq!(rs.tasks.len(), 10_000);
    // A whole walk of the ten thousand tasks for one configuration per mode.
    let (_, rows) = generated(10_000);
    for (mode, detail, wire, sort) in [
        ("history", "completed", history("completed"), "manual"),
        ("agenda", "", agenda(), "priority"),
        ("search", "caf", search("caf"), "title"),
    ] {
        let options = json!({ "sort": sort, "show_completed": true, "show_cancelled": true });
        let (expected, open) = reference(&rows, mode, detail, sort, false, None);
        let (seen, seen_open, pages) = page_through(&rs, &wire, &options, 200);
        assert_eq!(seen, expected, "{mode}: the pages are the full order");
        assert_eq!(seen_open, open, "{mode}: the open count");
        assert_eq!(pages, expected.len().div_ceil(200), "{mode}");
        assert!(expected.len() > 1_000, "{mode}: a large result");
    }
    for (mode, expected_more) in [
        (history("completed"), true),
        (agenda(), true),
        (search("a"), true),
    ] {
        let page = try_page(
            &rs,
            &query_of(mode, json!({}), 25, None),
            &inputs(TODAY, "UTC"),
        )
        .expect("a page");
        let rows: usize = page.sections.iter().map(|s| s.items.len()).sum();
        assert_eq!(rows, 25);
        assert_eq!(page.has_more, expected_more);
        assert!(page.next_cursor.is_some());
    }
}

#[test]
fn queries_026_fr_002_the_agenda_is_exactly_the_three_date_views_and_history_holds_every_terminal_task()
 {
    let (rs, rows) = generated(3_000);
    let agenda_all = page_through(&rs, &agenda(), &json!({}), 200).0;
    let mut views = Vec::new();
    let mut open = 0;
    for view in ["overdue", "today", "upcoming"] {
        let (seen, count, _) = page_through(&rs, &date_view(view), &json!({}), 200);
        open += count;
        views.extend(seen.into_iter().map(|(_, id)| (format!("date:{view}"), id)));
    }
    assert_eq!(agenda_all, views, "the agenda is the three date views");
    assert_eq!(
        page_through(&rs, &agenda(), &json!({}), 200).1,
        open,
        "and its open count their sum"
    );

    let terminal = rows
        .iter()
        .filter(|g| matches!(g.state, "completed" | "cancelled"))
        .count();
    let completed = page_through(&rs, &history("completed"), &json!({}), 200).0;
    let cancelled = page_through(&rs, &history("cancelled"), &json!({}), 200).0;
    assert_eq!(completed.len() + cancelled.len(), terminal);

    // Grouping changes sections, never membership.
    for sort in ["manual", "due", "priority", "title"] {
        let flat = page_through(&rs, &search("a"), &json!({ "sort": sort }), 200).0;
        let grouped = page_through(
            &rs,
            &search("a"),
            &json!({ "sort": sort, "group_by_project": true }),
            200,
        )
        .0;
        let ids = |rows: &[(String, String)]| -> BTreeSet<String> {
            rows.iter().map(|row| row.1.clone()).collect()
        };
        assert_eq!(ids(&flat), ids(&grouped), "{sort}");
        assert_eq!(flat.len(), grouped.len(), "{sort}");
    }
}

// ----------------------------------------------------------------- cursors

fn base64url(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::new();
    for chunk in bytes.chunks(3) {
        let group = chunk.iter().enumerate().fold(0u32, |acc, (i, byte)| {
            acc | (u32::from(*byte) << (16 - 8 * i))
        });
        for position in 0..=chunk.len() {
            out.push(char::from(
                ALPHABET[((group >> (18 - 6 * position)) & 0x3f) as usize],
            ));
        }
    }
    out
}

fn unbase64url(text: &str) -> Vec<u8> {
    let value = |byte: u8| match byte {
        b'A'..=b'Z' => byte - b'A',
        b'a'..=b'z' => byte - b'a' + 26,
        b'0'..=b'9' => byte - b'0' + 52,
        b'-' => 62,
        _ => 63,
    };
    let (mut acc, mut bits, mut out) = (0u32, 0u32, Vec::new());
    for byte in text.bytes() {
        acc = (acc << 6) | u32::from(value(byte));
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push(((acc >> bits) & 0xff) as u8);
            acc &= (1 << bits) - 1;
        }
    }
    out
}

fn payload(cursor: &str) -> Value {
    serde_json::from_slice(&unbase64url(cursor)).expect("cursor json")
}

fn with_last(cursor: &str, last: &[Value]) -> String {
    let mut parsed = payload(cursor);
    parsed["last"] = Value::Array(last.to_vec());
    base64url(parsed.to_string().as_bytes())
}

fn refused(rs: &ReadSet, mode: Value, options: Value, day: &str, cursor: &str) -> DomainError {
    try_page(
        rs,
        &query_of(mode, options, 1, Some(cursor)),
        &inputs(day, "UTC"),
    )
    .expect_err("the cursor is refused")
}

/// Three short tasks in every section a mode can have, with one-row pages.
fn small_store() -> (ReadSet, Vec<(&'static str, Value, Value)>) {
    let mut f = Fixture::default();
    let home = f.project("Home", "p-home", false);
    f.add(
        t("Alpha a")
            .due("2026-09-28")
            .project(&home)
            .priority("high"),
    );
    f.add(t("Alpha b").due("2026-09-29"));
    f.add(t("Alpha c").due("2026-09-30").priority("low"));
    f.add(t("Alpha d").state("completed").due("2026-09-29").ended(3));
    f.add(t("Alpha e").state("cancelled").due("2026-09-29").ended(4));
    f.add(t("Alpha f").state("completed").due("2026-09-29").ended(5));
    f.add(t("Alpha g").state("cancelled").due("2026-09-29").ended(6));
    let both = json!({ "show_completed": true, "show_cancelled": true });
    let grouped =
        json!({ "show_completed": true, "show_cancelled": true, "group_by_project": true });
    (
        f.read_set(),
        vec![
            ("history", history("completed"), json!({})),
            (
                "history grouped",
                history("cancelled"),
                json!({ "group_by_project": true }),
            ),
            ("agenda", agenda(), both.clone()),
            ("date view", date_view("today"), both.clone()),
            ("date view grouped", date_view("today"), grouped.clone()),
            ("search", search("alpha"), json!({})),
            ("search grouped", search("alpha"), grouped),
        ],
    )
}

#[test]
fn queries_026_fr_009_a_cursor_continues_only_the_query_it_was_issued_for() {
    let (rs, queries) = small_store();
    for (label, mode, options) in &queries {
        let first = try_page(
            &rs,
            &query_of(mode.clone(), options.clone(), 1, None),
            &inputs(TODAY, "UTC"),
        )
        .expect("a first page");
        let cursor = first
            .next_cursor
            .unwrap_or_else(|| panic!("{label}: a cursor"));

        // The same query continues it.
        let rest = try_page(
            &rs,
            &query_of(mode.clone(), options.clone(), 50, Some(&cursor)),
            &inputs(TODAY, "UTC"),
        )
        .unwrap_or_else(|e| panic!("{label}: {e:?}"));
        let first_id = first.sections[0].items[0].id.clone();
        assert!(
            rest.sections
                .iter()
                .all(|s| s.items.iter().all(|i| i.id != first_id)),
            "{label}: the continuation never repeats the last row"
        );

        // Another mode, sort, filter, grouping or day refuses it.
        let with = |key: &str, value: Value| {
            let mut changed = options.clone();
            changed[key] = value;
            changed
        };
        let mut attempts = vec![
            (mode.clone(), with("sort", json!("title")), TODAY),
            (mode.clone(), with("tag_filter", json!("tag-x")), TODAY),
            (mode.clone(), with("priorities", json!(["high"])), TODAY),
            (search("zzz"), options.clone(), TODAY),
            (history("cancelled"), json!({}), TODAY),
        ];
        if label.starts_with("history") || label.starts_with("date") || label.starts_with("search")
        {
            let grouped = options["group_by_project"].as_bool().unwrap_or(false);
            attempts.push((
                mode.clone(),
                with("group_by_project", json!(!grouped)),
                TODAY,
            ));
        }
        if label.starts_with("agenda") || label.starts_with("date") {
            attempts.push((mode.clone(), options.clone(), "2026-09-30"));
        }
        for (mode, options, day) in attempts {
            let error = refused(&rs, mode, options, day, &cursor);
            assert_eq!(
                (error.reason, error.field.as_deref()),
                (Reason::InvalidValue, Some("cursor")),
                "{label}"
            );
        }
    }
}

#[test]
fn queries_026_fr_009_a_cursor_with_an_impossible_section_or_key_shape_is_refused() {
    let (rs, queries) = small_store();
    for (label, mode, options) in &queries {
        let first = try_page(
            &rs,
            &query_of(mode.clone(), options.clone(), 1, None),
            &inputs(TODAY, "UTC"),
        )
        .expect("a first page");
        let cursor = first.next_cursor.expect("a cursor");
        let last = payload(&cursor)["last"].as_array().expect("last").clone();
        let attempt = |last: &[Value]| {
            try_page(
                &rs,
                &query_of(
                    mode.clone(),
                    options.clone(),
                    1,
                    Some(&with_last(&cursor, last)),
                ),
                &inputs(TODAY, "UTC"),
            )
        };
        // The untouched key re-encoded still continues.
        assert!(attempt(&last).is_ok(), "{label}");

        let mut cases: Vec<(String, Vec<Value>)> = Vec::new();
        let mut shorter = last.clone();
        shorter.pop();
        cases.push(("shorter".into(), shorter));
        let mut longer = last.clone();
        longer.push(json!("x"));
        cases.push(("longer".into(), longer));
        cases.push(("empty".into(), vec![]));
        cases.push(("lone int".into(), vec![json!(1)]));
        cases.push(("lone section".into(), vec![last[0].clone()]));
        for position in 0..last.len() {
            let mut swapped = last.clone();
            swapped[position] = if last[position].is_u64() {
                json!("x")
            } else {
                json!(7)
            };
            cases.push((format!("variant at {position}"), swapped));
        }
        for section in [
            "no-such-section",
            "project:p-missing",
            "date:never",
            "open:x",
            "",
        ] {
            let mut moved = last.clone();
            moved[0] = json!(section);
            cases.push((format!("section {section:?}"), moved));
        }
        for (why, key) in cases {
            let error = attempt(&key).expect_err(&format!("{label}: {why}"));
            assert_eq!(
                (error.reason, error.field.as_deref()),
                (Reason::InvalidValue, Some("cursor")),
                "{label}: {why}"
            );
        }
    }
}

#[test]
fn queries_026_fr_009_malformed_cursors_and_limits_are_typed_refusals() {
    let (rs, _) = small_store();
    for cursor in ["", "!!!", "e30", "bm90LWpzb24"] {
        let error = refused(&rs, search("alpha"), json!({}), TODAY, cursor);
        assert_eq!(
            (error.reason, error.field.as_deref()),
            (Reason::InvalidValue, Some("cursor")),
            "{cursor:?}"
        );
    }
    for limit in [0, 201] {
        let error = try_page(
            &rs,
            &query_of(search("alpha"), json!({}), limit, None),
            &inputs(TODAY, "UTC"),
        )
        .expect_err("the limit is refused");
        assert_eq!(
            (error.reason, error.field.as_deref()),
            (Reason::InvalidValue, Some("limit"))
        );
    }
}

/// Replaces one project of a read set: the same id under another name, state
/// or colour, as if the user had edited it between two pages.
fn edit_project(rs: &mut ReadSet, id: &str, name: &str, state: &str, color: Option<&str>) {
    let project = rs
        .projects
        .values_mut()
        .find(|p| p.id.as_str() == id)
        .expect("a project");
    *project = serde_json::from_value(json!({
        "id": id, "name": name, "color": color, "state": state, "revision": "2",
        "desired_outcome": null, "archived_at": null, "archived_before_lossless": false,
        "created_at": "2026-09-01T09:00:00Z",
    }))
    .expect("a project");
}

fn row_ids(page: &ListModePage) -> Vec<String> {
    page.sections
        .iter()
        .flat_map(|s| s.items.iter().map(|i| i.id.as_str().to_owned()))
        .collect()
}

/// `projects` named in order, each with three completed tasks.
fn grouped_history(names: &[(&str, &str)]) -> ReadSet {
    let mut f = Fixture::default();
    for (id, name) in names {
        let project = f.project(name, id, false);
        for n in 0..3 {
            f.add(
                t(&format!("{id}-{n}"))
                    .project(&project)
                    .state("completed")
                    .ended(n),
            );
        }
    }
    f.read_set()
}

#[test]
fn queries_026_fr_009_a_cursor_is_refused_once_its_projects_order_key_changed() {
    let options = json!({ "group_by_project": true });
    let rs = grouped_history(&[("p-a", "Aaa"), ("p-b", "Bbb")]);
    let first = try_page(
        &rs,
        &query_of(history("completed"), options.clone(), 2, None),
        &inputs(TODAY, "UTC"),
    )
    .expect("a page");
    let cursor = first.next_cursor.clone().expect("a cursor");
    assert_eq!(first.sections.len(), 1, "page 1 ends inside project A");
    assert_eq!(first.sections[0].id, "project:p-a");
    let key = payload(&cursor)["last"].as_array().expect("last").clone();
    assert_eq!(
        key[..6],
        [
            json!("project:p-a"),
            json!(0),
            json!("aaa"),
            json!("aaa"),
            json!("Aaa"),
            json!("p-a")
        ],
        "the key carries the section id and the section's order key"
    );

    // A key without the section's order key, or with a forged one, is refused
    // by its shape or its content, not resumed.
    let mut without = key.clone();
    without.drain(1..6);
    let mut forged = key.clone();
    forged[4] = json!("Zzz");
    let mut cut = key.clone();
    cut.truncate(3);
    for (what, last) in [("without", without), ("forged", forged), ("cut", cut)] {
        let error = try_page(
            &rs,
            &query_of(
                history("completed"),
                options.clone(),
                50,
                Some(&with_last(&cursor, &last)),
            ),
            &inputs(TODAY, "UTC"),
        )
        .expect_err(what);
        assert_eq!(
            (error.reason, error.field.as_deref()),
            (Reason::InvalidValue, Some("cursor")),
            "{what}"
        );
    }

    // Renamed so that it now sorts after B, archived, or unarchived: each moves
    // the section, so resuming at its new position would skip B's rows (or
    // repeat A's). The cursor is refused and the client starts over.
    let resume = |rs: &ReadSet, cursor: &str| {
        try_page(
            rs,
            &query_of(history("completed"), options.clone(), 50, Some(cursor)),
            &inputs(TODAY, "UTC"),
        )
    };
    for (what, name, state) in [
        ("renamed after B", "Zzz", "active"),
        ("renamed but still before B", "Aab", "active"),
        ("a case-only rename", "AAA", "active"),
        ("archived", "Aaa", "archived"),
    ] {
        let mut changed = rs.clone();
        edit_project(&mut changed, "p-a", name, state, None);
        let error = resume(&changed, &cursor).expect_err(what);
        assert_eq!(
            (error.reason, error.field.as_deref()),
            (Reason::InvalidValue, Some("cursor")),
            "{what}"
        );
        // Starting over is answered, and lists every row once in the new order.
        let (all, _, _) = page_through(&changed, &history("completed"), &options, 2);
        assert_eq!(all.len(), 6, "{what}");
    }
    let mut unarchived = rs.clone();
    edit_project(&mut unarchived, "p-a", "Aaa", "archived", None);
    let archived_first = try_page(
        &unarchived,
        &query_of(history("completed"), options.clone(), 4, None),
        &inputs(TODAY, "UTC"),
    )
    .expect("a page");
    let archived_cursor = archived_first.next_cursor.expect("a cursor");
    assert_eq!(
        archived_first.sections.last().expect("a section").id,
        "project:p-a"
    );
    let error = resume(&rs, &archived_cursor).expect_err("unarchived");
    assert_eq!(
        (error.reason, error.field.as_deref()),
        (Reason::InvalidValue, Some("cursor")),
        "unarchived"
    );

    // An edit that leaves the order key alone does not disturb the cursor.
    let mut recoloured = rs.clone();
    edit_project(&mut recoloured, "p-a", "Aaa", "active", Some("#ff0000"));
    let rest = resume(&recoloured, &cursor).expect("the order key is unchanged");
    let mut all = row_ids(&first);
    all.extend(row_ids(&rest));
    let unpaged = row_ids(
        &try_page(
            &recoloured,
            &query_of(history("completed"), options.clone(), 50, None),
            &inputs(TODAY, "UTC"),
        )
        .expect("a page"),
    );
    assert_eq!(all, unpaged, "no row skipped or repeated");
}

#[test]
fn queries_026_fr_009_a_rename_elsewhere_does_not_disturb_a_cursor_that_sections_ahead_of_it() {
    let options = json!({ "group_by_project": true });
    let rs = grouped_history(&[("p-a", "Aaa"), ("p-b", "Bbb"), ("p-c", "Ccc")]);
    let first = try_page(
        &rs,
        &query_of(history("completed"), options.clone(), 2, None),
        &inputs(TODAY, "UTC"),
    )
    .expect("a page");
    assert_eq!(first.sections[0].id, "project:p-a", "page 1 ends in A");
    let seen = row_ids(&first);
    let cursor = first.next_cursor.clone().expect("a cursor");

    // What is guaranteed: while the cursor's own section keeps its order key,
    // projects that sort after it may be renamed, even past one another, and
    // paging on neither skips nor repeats a row of them. (A project renamed to
    // sort before the cursor's section is behind the cursor, as for any keyset
    // cursor; that is not promised either way.)
    for (rename_c, rename_b) in [
        ("Bbc", "Bbb"),
        ("Zzz", "Bbb"),
        ("Ccc", "Yyy"),
        ("Ccc", "Bbb"),
    ] {
        let mut changed = rs.clone();
        edit_project(&mut changed, "p-c", rename_c, "active", None);
        edit_project(&mut changed, "p-b", rename_b, "active", None);
        let mut all = seen.clone();
        let mut after = Some(cursor.clone());
        while let Some(token) = after {
            let page = try_page(
                &changed,
                &query_of(history("completed"), options.clone(), 2, Some(&token)),
                &inputs(TODAY, "UTC"),
            )
            .expect("the cursor still continues");
            all.extend(row_ids(&page));
            after = page.next_cursor;
        }
        let unpaged = row_ids(
            &try_page(
                &changed,
                &query_of(history("completed"), options.clone(), 50, None),
                &inputs(TODAY, "UTC"),
            )
            .expect("a page"),
        );
        assert_eq!(all, unpaged, "{rename_b}/{rename_c}");
    }
}

// ----------------------------------------------------------- wire and dispatch

#[test]
fn queries_026_fr_002_list_modes_have_a_json_wire_shape_and_one_owner() {
    let query: Query = serde_json::from_value(json!({
        "kind": "list_mode",
        "mode": { "type": "history", "kind": "completed" },
        "page": { "limit": 5, "after": null },
    }))
    .expect("options default");
    assert_eq!(query_kind(&query), QueryKind::ListMode);
    assert_eq!(QueryKind::ListMode.as_str(), "list_mode");
    assert_eq!(query_owner(&query), Ok(QueryFamily::ListModes));
    let written = serde_json::to_value(&query).expect("serializes");
    assert_eq!(written["kind"], "list_mode");
    assert_eq!(
        written["mode"],
        json!({ "type": "history", "kind": "completed" })
    );
    assert_eq!(written["options"]["sort"], "manual");
    assert_eq!(written["options"]["priorities"], json!([]));
    assert_eq!(written["options"]["tag_filter"], Value::Null);

    // Unknown members and modes are refused, not ignored.
    for bad in [
        json!({ "kind": "list_mode", "mode": { "type": "agenda", "x": 1 }, "page": {"limit": 1, "after": null} }),
        json!({ "kind": "list_mode", "mode": { "type": "project", "id": "p" }, "page": {"limit": 1, "after": null} }),
        json!({ "kind": "list_mode", "mode": { "type": "agenda" }, "options": { "sort": "newest" }, "page": {"limit": 1, "after": null} }),
        json!({ "kind": "list_mode", "mode": { "type": "agenda" }, "options": { "extra": 1 }, "page": {"limit": 1, "after": null} }),
        json!({ "kind": "list_mode", "mode": { "type": "date_view", "view": "later" }, "page": {"limit": 1, "after": null} }),
    ] {
        assert!(
            serde_json::from_value::<Query>(bad.clone()).is_err(),
            "{bad}"
        );
    }

    let mut f = Fixture::default();
    f.add(t("Done").state("completed").ended(1));
    let page = f.plain(history("completed"));
    let written = serde_json::to_value(QueryResult::ListMode(page.0)).expect("serializes");
    assert_eq!(written["kind"], "list_mode");
    let section = &written["value"]["sections"][0];
    assert_eq!(section["id"], "completed");
    assert_eq!(section["title"], Value::Null);
    assert_eq!(section["kind"], json!({ "type": "completed" }));
    assert_eq!(section["items"][0]["title"], "Done");
    assert_eq!(written["value"]["open_count"], 0);
}
