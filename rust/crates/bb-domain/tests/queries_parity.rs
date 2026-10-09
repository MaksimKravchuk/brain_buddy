//! Parity of the task, project and tag queries with the server (tasks.md T012).
//!
//! The expectations come from three places, none of them this crate:
//!
//! * the frozen synthetic store `reference-store.json`, read through the same
//!   `ReadSet` shapes the runtime loads, with the order and counts worked out
//!   from `TaskService` (`_filter_tasks`, `_sort_key`, `_open_counts`,
//!   `list_projects`, `list_tags`);
//! * scenarios of the backend API tests (`test_task_api.py`,
//!   `test_task_lifecycle_detail_api.py`), named in each test, rebuilt over a
//!   `ReadSet`;
//! * keyset cursors written by the server's own `_encode_cursor` (the strings
//!   below were produced by running that function), so a page continues across
//!   the HTTP and local paths.
//!
//! The family source is compiled in place (`#[path]`) with the crate paths it
//! uses inside `bb-domain`, so this runner does not depend on how the library
//! registers the module. Each test counts the cases it executed.

mod support;

pub use bb_domain::{calendar, normalization, types};

#[allow(dead_code, unused_imports)]
#[path = "../src/formulation.rs"]
mod formulation;
#[allow(dead_code)]
#[path = "../src/queries.rs"]
mod queries;

use bb_domain::types::{
    DomainError, OpenList, ProjectFilter, Query, QueryInputs, QueryResult, ReadSet, Reason,
    TaskListResult, TaskSort, TaskView,
};
use serde_json::{Map, Value, json};
use support::{cases, text};

// ---------------------------------------------------------------- the store

/// Rows to load as one owner's `ReadSet`.
#[derive(Default)]
struct Store {
    tasks: Vec<Value>,
    projects: Vec<Value>,
    tags: Vec<Value>,
    subtasks: Vec<Value>,
    comments: Vec<Value>,
    settings: Option<Value>,
}

fn keyed(rows: &[Value]) -> Value {
    Value::Object(
        rows.iter()
            .map(|row| (text(row, "id").to_owned(), row.clone()))
            .collect::<Map<_, _>>(),
    )
}

impl Store {
    fn read_set(&self) -> ReadSet {
        serde_json::from_value(json!({
            "tasks": keyed(&self.tasks),
            "projects": keyed(&self.projects),
            "tags": keyed(&self.tags),
            "subtasks": keyed(&self.subtasks),
            "comments": keyed(&self.comments),
            "settings": self.settings,
        }))
        .expect("a valid read set")
    }
}

const CREATED: &str = "2026-09-02T09:00:00Z";

/// A task row with the defaults a new task has.
fn task(id: &str, title: &str, state: &str, order_key: u64) -> Value {
    json!({
        "id": id, "title": title, "details": null, "state": state,
        "project_id": null, "tag_ids": [], "due_date": null, "priority": "none",
        "waiting_for": null, "waiting_since": null,
        "order_key": order_key.to_string(), "source_capture_ids": [],
        "created_at": CREATED, "updated_at": CREATED,
        "completed_at": null, "cancelled_at": null, "revision": "1",
        "consecutive_stalled_formulations": 0, "formulation": null, "parked": null,
    })
}

fn with(mut row: Value, key: &str, value: Value) -> Value {
    row[key] = value;
    row
}

fn project(id: &str, name: &str, state: &str) -> Value {
    json!({
        "id": id, "name": name, "color": null, "state": state, "revision": "1",
        "desired_outcome": null, "archived_at": null, "archived_before_lossless": false,
    })
}

fn tag(id: &str, name: &str, state: &str) -> Value {
    json!({ "id": id, "name": name, "state": state, "revision": "1" })
}

fn settings(activated_at: Option<&str>) -> Value {
    json!({
        "threshold_days": 14, "review_weekday": 5, "review_time": "16:00",
        "time_zone": "UTC", "onboarded_at": null, "activated_at": activated_at,
        "owner_park_floor_at": null, "revision": "1",
    })
}

fn inputs(now: &str, zone: &str) -> QueryInputs {
    serde_json::from_value(json!({
        "now": now, "device_zone": zone,
        "policy": {
            "weekly_review": false, "navigator_provider": null,
            "navigator_available": false, "consent_text_version": 1,
        },
    }))
    .expect("valid inputs")
}

// -------------------------------------------------------------- the queries

fn run(
    read_set: &ReadSet,
    query: &Query,
    now: &str,
    zone: &str,
) -> Result<QueryResult, DomainError> {
    queries::query(read_set, query, &inputs(now, zone))
}

struct Listing<'a> {
    list: OpenList,
    project: Option<&'a str>,
    tag: Option<&'a str>,
    sort: TaskSort,
    limit: u32,
    after: Option<&'a str>,
}

impl<'a> Listing<'a> {
    fn of(list: OpenList) -> Self {
        Self {
            list,
            project: None,
            tag: None,
            sort: TaskSort::Manual,
            limit: 50,
            after: None,
        }
    }

    fn sorted(self, sort: TaskSort) -> Self {
        Self { sort, ..self }
    }

    fn limit(self, limit: u32) -> Self {
        Self { limit, ..self }
    }

    fn after(self, after: Option<&'a str>) -> Self {
        Self { after, ..self }
    }

    fn project(self, project: &'a str) -> Self {
        Self {
            project: Some(project),
            ..self
        }
    }

    fn tag(self, tag: &'a str) -> Self {
        Self {
            tag: Some(tag),
            ..self
        }
    }

    fn query(&self) -> Query {
        serde_json::from_value(json!({
            "kind": "task_list", "list": self.list.as_str(),
            "project_id": self.project, "tag_id": self.tag, "sort": self.sort.as_str(),
            "page": { "limit": self.limit, "after": self.after },
        }))
        .expect("a valid query")
    }

    fn run(&self, read_set: &ReadSet) -> Result<TaskListResult, DomainError> {
        match run(read_set, &self.query(), "2026-10-09T12:00:00Z", "UTC")? {
            QueryResult::TaskList(page) => Ok(page),
            other => panic!("not a list: {other:?}"),
        }
    }

    fn page(&self, read_set: &ReadSet) -> TaskListResult {
        self.run(read_set).expect("the list is answered")
    }
}

fn ids(items: &[TaskView]) -> Vec<&str> {
    items.iter().map(|item| item.id.as_str()).collect()
}

/// The first four characters of each id: enough to name a reference-store row.
fn short(items: &[TaskView]) -> Vec<String> {
    items
        .iter()
        .map(|item| item.id.as_str().chars().take(4).collect())
        .collect()
}

fn detail(read_set: &ReadSet, id: &str) -> Result<TaskView, DomainError> {
    let query: Query =
        serde_json::from_value(json!({ "kind": "task_detail", "task_id": id })).expect("query");
    match run(read_set, &query, "2026-10-09T12:00:00Z", "UTC")? {
        QueryResult::TaskDetail(view) => Ok(view),
        other => panic!("not a detail: {other:?}"),
    }
}

fn counts(read_set: &ReadSet, now: &str, zone: &str) -> bb_domain::types::ListCounts {
    let query: Query = serde_json::from_value(json!({ "kind": "list_counts" })).expect("query");
    match run(read_set, &query, now, zone).expect("counts") {
        QueryResult::ListCounts(counts) => counts,
        other => panic!("not counts: {other:?}"),
    }
}

fn projects(read_set: &ReadSet, filter: ProjectFilter) -> Vec<bb_domain::types::ProjectSummary> {
    let query: Query =
        serde_json::from_value(json!({ "kind": "projects", "filter": filter.as_str() }))
            .expect("query");
    match run(read_set, &query, "2026-10-09T12:00:00Z", "UTC").expect("projects") {
        QueryResult::Projects(list) => list,
        other => panic!("not projects: {other:?}"),
    }
}

fn tags(read_set: &ReadSet) -> Vec<bb_domain::types::TagSummary> {
    let query: Query = serde_json::from_value(json!({ "kind": "tags" })).expect("query");
    match run(read_set, &query, "2026-10-09T12:00:00Z", "UTC").expect("tags") {
        QueryResult::Tags(list) => list,
        other => panic!("not tags: {other:?}"),
    }
}

fn display(read_set: &ReadSet, id: &str) -> Result<bb_domain::types::ProjectDisplay, DomainError> {
    let query: Query =
        serde_json::from_value(json!({ "kind": "project_display", "project_id": id }))
            .expect("query");
    match run(read_set, &query, "2026-10-09T12:00:00Z", "UTC")? {
        QueryResult::ProjectDisplay(display) => Ok(display),
        other => panic!("not a display: {other:?}"),
    }
}

fn counts_of(page: &TaskListResult) -> [u32; 4] {
    let c = page.counts_by_state;
    [c.inbox, c.next, c.waiting, c.someday]
}

// ----------------------------------------------- reference store (frozen oracle)

const OWNER_A: &str = "beea96a4-7827-599d-b786-571f694828ac";
const OWNER_B: &str = "863e24a2-2512-59a9-8531-f435e248f118";

/// One owner's stored rows of `reference-store.json` in the shapes of `ReadSet`.
fn reference_store(owner: &str) -> Store {
    let records = &support::reference_store()["dataset"]["records"];
    let mine = |name: &str| -> Vec<Value> {
        cases(records, name)
            .iter()
            .filter(|row| text(row, "owner_id") == owner)
            .cloned()
            .collect()
    };
    let optional = |row: &Value, key: &str| row[key].clone();
    let counter = |row: &Value, key: &str| Value::String(row[key].to_string());
    let mut store = Store::default();
    for row in mine("projects") {
        store.projects.push(json!({
            "id": row["id"], "name": row["name"], "color": row["color"],
            "state": row["state"], "revision": counter(&row, "revision"),
            "desired_outcome": row["desired_outcome"], "archived_at": row["archived_at"],
            "archived_before_lossless": row["archived_before_lossless"],
        }));
    }
    for row in mine("tags") {
        store.tags.push(json!({
            "id": row["id"], "name": row["name"], "state": row["state"],
            "revision": counter(&row, "revision"),
        }));
    }
    for row in mine("tasks") {
        let formulation = row["formulation_id"].as_str().map(|id| {
            json!({
                "id": id, "started_at": row["formulation_started_at"],
                "extended_at": row["formulation_extended_at"],
                "extension_reason": row["formulation_extension_reason"],
                "park_floor_at": row["formulation_park_floor_at"],
            })
        });
        let parked = row["parked"].as_object().map(|park| {
            let before = &park["clock_before"];
            json!({
                "at": park["at"], "formulation_id": park["formulation_id"],
                "private": {
                    "from_revision": park["from_revision"].to_string(),
                    "clock_before": {
                        "formulation_id": park["formulation_id"],
                        "started_at": before["started_at"], "extended_at": before["extended_at"],
                        "extension_reason": before["extension_reason"],
                        "park_floor_at": before["park_floor_at"],
                        "stalled_before": before["stalled_before"],
                    },
                },
            })
        });
        store.tasks.push(json!({
            "id": row["id"], "title": row["title"], "details": row["details"],
            "state": row["state"], "project_id": row["project_id"], "tag_ids": row["tag_ids"],
            "due_date": row["due_date"], "priority": row["priority"],
            "waiting_for": row["waiting_for"], "waiting_since": row["waiting_since"],
            "order_key": counter(&row, "order_key"),
            "source_capture_ids": row["source_capture_ids"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "completed_at": row["completed_at"], "cancelled_at": row["cancelled_at"],
            "revision": counter(&row, "revision"),
            "consecutive_stalled_formulations": row["consecutive_stalled_formulations"],
            "formulation": formulation, "parked": parked,
        }));
    }
    for row in mine("subtasks") {
        store.subtasks.push(json!({
            "id": row["id"], "task_id": row["task_id"], "title": row["title"],
            "state": row["state"], "order_key": counter(&row, "order_key"),
            "revision": counter(&row, "revision"),
        }));
    }
    for row in mine("comments") {
        store.comments.push(json!({
            "id": row["id"], "task_id": row["task_id"], "body": row["body"],
            "actor_id": row["actor_id"], "created_at": row["created_at"],
            "edited_at": optional(&row, "edited_at"), "revision": counter(&row, "revision"),
        }));
    }
    store
}

#[test]
fn queries_026_fr_009_reference_store_lists_follow_the_server_manual_order() {
    let a = reference_store(OWNER_A).read_set();
    // (list, projectless-inbox rule, expected ids, counts_by_state)
    // Inbox is the projectless projection; the other lists count every project.
    let expected = [
        (OpenList::Inbox, vec!["4722", "b4d4"], [2, 1, 0, 1]),
        (OpenList::Next, vec!["da63", "96ef", "2b25"], [2, 3, 1, 3]),
        (OpenList::Waiting, vec!["7321"], [2, 3, 1, 3]),
        (
            OpenList::Someday,
            vec!["373f", "6476", "cc51"],
            [2, 3, 1, 3],
        ),
    ];
    let mut ran = 0;
    for (list, wanted, wanted_counts) in &expected {
        let page = Listing::of(*list).page(&a);
        assert_eq!(short(&page.items), *wanted, "{list:?}");
        assert_eq!(counts_of(&page), *wanted_counts, "{list:?} counts");
        assert!(!page.has_more && page.next_cursor.is_none(), "{list:?}");
        // Terminal tasks never appear in an open list.
        assert!(!ids(&page.items).contains(&"576d7507-f146-52d6-933e-bfa9b7db1884"));
        ran += 1;
    }
    assert_eq!(ran, expected.len());
}

#[test]
fn queries_026_fr_009_reference_store_sorts_match_the_server_keys() {
    let a = reference_store(OWNER_A).read_set();
    // Due: dated first by date, then undated by the manual key.
    let due = Listing::of(OpenList::Next).sorted(TaskSort::Due).page(&a);
    assert_eq!(short(&due.items), ["da63", "2b25", "96ef"]);
    // Priority: high first, then the manual key.
    let priority = Listing::of(OpenList::Next)
        .sorted(TaskSort::Priority)
        .page(&a);
    assert_eq!(short(&priority.items), ["da63", "96ef", "2b25"]);
    // Title: NFKC + casefold of the title, then id.
    let title = Listing::of(OpenList::Next).sorted(TaskSort::Title).page(&a);
    assert_eq!(short(&title.items), ["2b25", "96ef", "da63"]);
    let someday = Listing::of(OpenList::Someday)
        .sorted(TaskSort::Title)
        .page(&a);
    assert_eq!(short(&someday.items), ["6476", "373f", "cc51"]);
}

#[test]
fn queries_026_fr_002_reference_store_filters_by_project_and_tag() {
    let a = reference_store(OWNER_A).read_set();
    let archived = "8af3bf55-0969-56e4-9eac-16cf5d8da698";
    // An archived project still lists its open tasks (lossless archive).
    let waiting = Listing::of(OpenList::Waiting).project(archived).page(&a);
    assert_eq!(short(&waiting.items), ["7321"]);
    assert_eq!(counts_of(&waiting), [0, 0, 1, 1]);
    let someday = Listing::of(OpenList::Someday).project(archived).page(&a);
    assert_eq!(short(&someday.items), ["cc51"]);
    // Inbox for one project is the raw lifecycle state, not the projection.
    let inbox = Listing::of(OpenList::Inbox).project(archived).page(&a);
    assert!(inbox.items.is_empty());
    assert_eq!(counts_of(&inbox), [0, 0, 1, 1]);
    // A tag filter composes with the list; counts follow the tag scope.
    let work = "a2743e5d-23a6-5732-a346-e4553015c8b3";
    let tagged = Listing::of(OpenList::Next).tag(work).page(&a);
    assert_eq!(short(&tagged.items), ["da63"]);
    assert_eq!(counts_of(&tagged), [0, 1, 0, 0]);
    let both = Listing::of(OpenList::Next)
        .project("4f4a6fa6-8e51-598c-a064-36566e6b1101")
        .tag(work)
        .page(&a);
    assert_eq!(short(&both.items), ["da63"]);
    // A deleted tag is still a known tag: the filter is valid and empty.
    let deleted = "d75b0b18-664f-5cc6-81fa-beebb8738eb3";
    assert!(
        Listing::of(OpenList::Next)
            .tag(deleted)
            .page(&a)
            .items
            .is_empty()
    );
}

#[test]
fn queries_026_fr_002_reference_store_owners_never_see_each_other() {
    let b = reference_store(OWNER_B).read_set();
    let inbox = Listing::of(OpenList::Inbox).page(&b);
    assert_eq!(short(&inbox.items), ["53a2"]);
    let next = Listing::of(OpenList::Next).page(&b);
    assert_eq!(short(&next.items), ["5580"]);
    // Owner A's project id is unknown to owner B's read set.
    let foreign = Listing::of(OpenList::Next)
        .project("66055107-daf7-57da-95a4-8d3803adb031")
        .run(&b)
        .expect_err("not found");
    assert_eq!(foreign.reason, Reason::NotFound);
    // Owners share the names Garden and work without colliding.
    let names: Vec<String> = projects(&b, ProjectFilter::All)
        .iter()
        .map(|p| p.project.name.as_str().to_owned())
        .collect();
    assert_eq!(names, ["Garden"]);
    assert_eq!(tags(&b)[0].tag.name.as_str(), "work");
}

#[test]
fn queries_026_fr_009_reference_store_paginates_with_the_server_cursor() {
    let a = reference_store(OWNER_A).read_set();
    let first = Listing::of(OpenList::Next).limit(2).page(&a);
    assert_eq!(short(&first.items), ["da63", "96ef"]);
    assert!(first.has_more);
    // Produced by TaskService._encode_cursor for state=next, sort=manual, last=96ef.
    assert_eq!(
        first.next_cursor.as_deref(),
        Some(
            "eyJmaWx0ZXJzIjp7ImR1ZV9hZnRlciI6bnVsbCwiZHVlX2JlZm9yZSI6bnVsbCwiZHVlX29uIjpudWxsLCJpbmNsdWRlX2NhbmNlbGxlZCI6ZmFsc2UsImluY2x1ZGVfY29tcGxldGVkIjpmYWxzZSwicHJpb3JpdHkiOltdLCJwcm9qZWN0X2lkIjpudWxsLCJxIjoiIiwic29ydCI6Im1hbnVhbCIsInN0YXRlIjoibmV4dCIsInRhZ19pZCI6bnVsbCwidW5hc3NpZ25lZF9wcm9qZWN0IjpmYWxzZX0sImxhc3QiOlsxLCIyMDI2LTA5LTAyVDA5OjAwOjAwKzAwOjAwIiwiOTZlZjkyZWItODJhMC01Y2IyLTllZWUtMTY5YWFjOThiZTQzIl19"
        )
    );
    let second = Listing::of(OpenList::Next)
        .limit(2)
        .after(first.next_cursor.as_deref())
        .page(&a);
    assert_eq!(short(&second.items), ["2b25"]);
    assert!(!second.has_more && second.next_cursor.is_none());
    assert_eq!(counts_of(&second), [2, 3, 1, 3], "counts ignore the cursor");

    // Due and priority keys, from the same server function.
    let due = Listing::of(OpenList::Next)
        .sorted(TaskSort::Due)
        .limit(1)
        .page(&a);
    assert_eq!(
        due.next_cursor.as_deref(),
        Some(
            "eyJmaWx0ZXJzIjp7ImR1ZV9hZnRlciI6bnVsbCwiZHVlX2JlZm9yZSI6bnVsbCwiZHVlX29uIjpudWxsLCJpbmNsdWRlX2NhbmNlbGxlZCI6ZmFsc2UsImluY2x1ZGVfY29tcGxldGVkIjpmYWxzZSwicHJpb3JpdHkiOltdLCJwcm9qZWN0X2lkIjpudWxsLCJxIjoiIiwic29ydCI6ImR1ZSIsInN0YXRlIjoibmV4dCIsInRhZ19pZCI6bnVsbCwidW5hc3NpZ25lZF9wcm9qZWN0IjpmYWxzZX0sImxhc3QiOlswLCIyMDI2LTEwLTIwIiwwLCIyMDI2LTA5LTAyVDA5OjAwOjAwKzAwOjAwIiwiZGE2Mzk1YzItOGU2Ny01MjdiLWJlNmQtNGI1NjczZDllNzU2Il19"
        )
    );
    let priority = Listing::of(OpenList::Next)
        .sorted(TaskSort::Priority)
        .limit(1)
        .page(&a);
    assert_eq!(
        priority.next_cursor.as_deref(),
        Some(
            "eyJmaWx0ZXJzIjp7ImR1ZV9hZnRlciI6bnVsbCwiZHVlX2JlZm9yZSI6bnVsbCwiZHVlX29uIjpudWxsLCJpbmNsdWRlX2NhbmNlbGxlZCI6ZmFsc2UsImluY2x1ZGVfY29tcGxldGVkIjpmYWxzZSwicHJpb3JpdHkiOltdLCJwcm9qZWN0X2lkIjpudWxsLCJxIjoiIiwic29ydCI6InByaW9yaXR5Iiwic3RhdGUiOiJuZXh0IiwidGFnX2lkIjpudWxsLCJ1bmFzc2lnbmVkX3Byb2plY3QiOmZhbHNlfSwibGFzdCI6WzAsMCwiMjAyNi0wOS0wMlQwOTowMDowMCswMDowMCIsImRhNjM5NWMyLThlNjctNTI3Yi1iZTZkLTRiNTY3M2Q5ZTc1NiJdfQ"
        )
    );
    // The filter fingerprint also carries project and tag.
    let scoped = Store {
        tasks: vec![
            with(
                with(task("t-w", "W", "waiting", 0), "project_id", json!("p-1")),
                "tag_ids",
                json!(["g-1"]),
            ),
            with(
                with(task("t-x", "X", "waiting", 1), "project_id", json!("p-1")),
                "tag_ids",
                json!(["g-1"]),
            ),
        ],
        projects: vec![project("p-1", "P", "active")],
        tags: vec![tag("g-1", "G", "active")],
        ..Store::default()
    }
    .read_set();
    let page = Listing::of(OpenList::Waiting)
        .project("p-1")
        .tag("g-1")
        .limit(1)
        .page(&scoped);
    assert_eq!(
        page.next_cursor.as_deref(),
        Some(
            "eyJmaWx0ZXJzIjp7ImR1ZV9hZnRlciI6bnVsbCwiZHVlX2JlZm9yZSI6bnVsbCwiZHVlX29uIjpudWxsLCJpbmNsdWRlX2NhbmNlbGxlZCI6ZmFsc2UsImluY2x1ZGVfY29tcGxldGVkIjpmYWxzZSwicHJpb3JpdHkiOltdLCJwcm9qZWN0X2lkIjoicC0xIiwicSI6IiIsInNvcnQiOiJtYW51YWwiLCJzdGF0ZSI6IndhaXRpbmciLCJ0YWdfaWQiOiJnLTEiLCJ1bmFzc2lnbmVkX3Byb2plY3QiOmZhbHNlfSwibGFzdCI6WzAsIjIwMjYtMDktMDJUMDk6MDA6MDArMDA6MDAiLCJ0LXciXX0"
        )
    );
}

#[test]
fn queries_026_fr_009_a_server_cursor_continues_a_local_page_and_a_foreign_one_is_refused() {
    let a = reference_store(OWNER_A).read_set();
    let first = Listing::of(OpenList::Next).limit(2).page(&a);
    let cursor = first.next_cursor.as_deref();
    // Other sort, list, project scope or tag scope: the fingerprint differs.
    let refused = [
        Listing::of(OpenList::Next)
            .sorted(TaskSort::Title)
            .limit(2)
            .after(cursor),
        Listing::of(OpenList::Someday).limit(2).after(cursor),
        Listing::of(OpenList::Next)
            .project("4f4a6fa6-8e51-598c-a064-36566e6b1101")
            .limit(2)
            .after(cursor),
        Listing::of(OpenList::Next)
            .tag("a2743e5d-23a6-5732-a346-e4553015c8b3")
            .limit(2)
            .after(cursor),
    ];
    for listing in &refused {
        let error = listing.run(&a).expect_err("a foreign cursor is refused");
        assert_eq!(error.reason, Reason::InvalidValue);
        assert_eq!(error.field.as_deref(), Some("cursor"));
    }
    // Garbage, not base64, not JSON, wrong shape.
    for bad in ["!!!", "e30", "bm90LWpzb24", "eyJmaWx0ZXJzIjp7fX0", "a"] {
        let error = Listing::of(OpenList::Next)
            .after(Some(bad))
            .run(&a)
            .expect_err("a bad cursor is refused");
        assert_eq!(error.reason, Reason::InvalidValue, "{bad}");
    }
    // Padding is accepted as Python accepts it.
    let padded = format!("{}==", cursor.expect("cursor"));
    let continued = Listing::of(OpenList::Next)
        .limit(2)
        .after(Some(&padded))
        .page(&a);
    assert_eq!(short(&continued.items), ["2b25"]);
}

#[test]
fn queries_026_fr_009_cursor_text_is_ascii_json_with_sorted_keys_and_python_isoformat() {
    // Title order key: NFKC + casefold, escaped as `json.dumps` escapes it
    // (BMP escape, surrogate pair, DEL, quote, backslash); the creation time is
    // `datetime.isoformat()` with its microseconds.
    let title = "A\u{c9}clair \u{1f600}\u{7f}\"\\";
    let read_set = Store {
        tasks: vec![
            task("t-eclair", title, "inbox", 0),
            task("t-zebra", "zebra", "inbox", 1),
        ],
        ..Store::default()
    }
    .read_set();
    let page = Listing::of(OpenList::Inbox)
        .sorted(TaskSort::Title)
        .limit(1)
        .page(&read_set);
    assert_eq!(ids(&page.items), ["t-eclair"]);
    assert_eq!(
        page.next_cursor.as_deref(),
        Some(
            "eyJmaWx0ZXJzIjp7ImR1ZV9hZnRlciI6bnVsbCwiZHVlX2JlZm9yZSI6bnVsbCwiZHVlX29uIjpudWxsLCJpbmNsdWRlX2NhbmNlbGxlZCI6ZmFsc2UsImluY2x1ZGVfY29tcGxldGVkIjpmYWxzZSwicHJpb3JpdHkiOltdLCJwcm9qZWN0X2lkIjpudWxsLCJxIjoiIiwic29ydCI6InRpdGxlIiwic3RhdGUiOiJpbmJveCIsInRhZ19pZCI6bnVsbCwidW5hc3NpZ25lZF9wcm9qZWN0Ijp0cnVlfSwibGFzdCI6WyJhXHUwMGU5Y2xhaXIgXHVkODNkXHVkZTAwXHUwMDdmXCJcXCIsInQtZWNsYWlyIl19"
        )
    );
    let rest = Listing::of(OpenList::Inbox)
        .sorted(TaskSort::Title)
        .limit(1)
        .after(page.next_cursor.as_deref())
        .page(&read_set);
    assert_eq!(ids(&rest.items), ["t-zebra"]);

    let fractional = Store {
        tasks: vec![
            with(
                task("t-frac", "frac", "inbox", 3),
                "created_at",
                json!("2026-09-02T09:00:00.5Z"),
            ),
            task("t-next", "next", "inbox", 4),
        ],
        ..Store::default()
    }
    .read_set();
    let page = Listing::of(OpenList::Inbox).limit(1).page(&fractional);
    assert_eq!(ids(&page.items), ["t-frac"]);
    assert_eq!(
        page.next_cursor.as_deref(),
        Some(
            "eyJmaWx0ZXJzIjp7ImR1ZV9hZnRlciI6bnVsbCwiZHVlX2JlZm9yZSI6bnVsbCwiZHVlX29uIjpudWxsLCJpbmNsdWRlX2NhbmNlbGxlZCI6ZmFsc2UsImluY2x1ZGVfY29tcGxldGVkIjpmYWxzZSwicHJpb3JpdHkiOltdLCJwcm9qZWN0X2lkIjpudWxsLCJxIjoiIiwic29ydCI6Im1hbnVhbCIsInN0YXRlIjoiaW5ib3giLCJ0YWdfaWQiOm51bGwsInVuYXNzaWduZWRfcHJvamVjdCI6dHJ1ZX0sImxhc3QiOlszLCIyMDI2LTA5LTAyVDA5OjAwOjAwLjUwMDAwMCswMDowMCIsInQtZnJhYyJdfQ"
        )
    );
}

#[test]
fn queries_026_fr_002_list_refusals_are_typed() {
    let a = reference_store(OWNER_A).read_set();
    for limit in [0, 201] {
        let error = Listing::of(OpenList::Next)
            .limit(limit)
            .run(&a)
            .expect_err("limit");
        assert_eq!(
            (error.reason, error.field.as_deref()),
            (Reason::InvalidValue, Some("limit"))
        );
    }
    assert!(Listing::of(OpenList::Next).limit(200).run(&a).is_ok());
    let project = Listing::of(OpenList::Next)
        .project("nope")
        .run(&a)
        .expect_err("project");
    assert_eq!(project.reason, Reason::NotFound);
    assert_eq!(
        project.entity.expect("entity").0,
        bb_domain::types::EntityType::Project
    );
    let tag = Listing::of(OpenList::Next)
        .tag("nope")
        .run(&a)
        .expect_err("tag");
    assert_eq!(
        tag.entity.expect("entity").0,
        bb_domain::types::EntityType::Tag
    );
    let missing = detail(&a, "nope").expect_err("task");
    assert_eq!(missing.reason, Reason::NotFound);
    // Review queries belong to the Review family.
    let review: Query = serde_json::from_value(json!({ "kind": "review_state" })).expect("query");
    let error = run(&a, &review, "2026-10-09T12:00:00Z", "UTC").expect_err("not here");
    assert_eq!(error.reason, Reason::InvalidValue);
}

// ------------------------------------------------------------------ the detail

#[test]
fn queries_026_fr_002_reference_store_detail_orders_children_and_hides_private_state() {
    let a = reference_store(OWNER_A).read_set();
    let quote = detail(&a, "da6395c2-8e67-527b-be6d-4b5673d9e756").expect("detail");
    let subtasks: Vec<&str> = quote.subtasks.iter().map(|s| s.title.as_str()).collect();
    assert_eq!(subtasks, ["Draft the mail", "Attach the price list"]);
    let comments: Vec<&str> = quote.comments.iter().map(|c| c.id.as_str()).collect();
    assert_eq!(
        comments,
        [
            "6a5b54bc-3982-5686-b6a0-052e7458045f",
            "d5eacd6a-b20c-5ec8-b527-73cd6c867384"
        ]
    );
    assert_eq!(quote.revision.as_str(), "4");
    // Children of another task are not embedded.
    let bob = detail(&a, "47229eef-b12d-56a4-aafb-845b4696ff3d").expect("detail");
    assert_eq!(bob.subtasks.len(), 1);
    assert!(bob.comments.is_empty());
    let none = detail(&a, "73210fee-9990-55e6-b61e-786466a63eff").expect("detail");
    assert!(none.subtasks.is_empty() && none.comments.is_empty());

    // TaskResponse.parked is shown for a Someday task only, without the
    // private clock; a Someday task shows no formulation.
    let parked = detail(&a, "373f88d2-6fb1-5248-9ce0-1f1f8649435b").expect("detail");
    assert!(parked.formulation.is_none());
    let park = parked.parked.as_ref().expect("the park marker");
    assert_eq!(park.at.as_str(), "2026-09-08T03:00:00Z");
    let wire = serde_json::to_string(&parked).expect("json");
    assert!(!wire.contains("clock_before") && !wire.contains("from_revision"));
    assert_eq!(parked.state, bb_domain::types::TaskState::Someday);

    // The same view comes from the list.
    let listed = Listing::of(OpenList::Next).page(&a);
    let from_list = listed
        .items
        .iter()
        .find(|item| item.id.as_str() == "da6395c2-8e67-527b-be6d-4b5673d9e756")
        .expect("listed");
    assert!(from_list.subtasks.is_empty() && from_list.comments.is_empty());
    assert_eq!(from_list.formulation, quote.formulation);
}

#[test]
fn queries_026_fr_017_advisory_instants_are_filled_for_an_activated_owner_only() {
    let mut store = reference_store(OWNER_A);
    let idle = store.read_set();
    let quote = "da6395c2-8e67-527b-be6d-4b5673d9e756";
    let view = detail(&idle, quote).expect("detail");
    let clock = view.formulation.expect("a running clock");
    assert_eq!(clock.started_at.as_str(), "2026-09-24T09:14:00Z");
    assert!(
        clock.ageing_at.is_none()
            && clock.ask_at.is_none()
            && clock.park_due_at.is_none()
            && clock.paused_until.is_none(),
        "an owner who is not activated has no advisory instants"
    );

    store.settings = Some(settings(Some("2026-09-01T00:00:00Z")));
    let read_set = store.read_set();
    let at = |view: &TaskView| {
        let clock = view.formulation.as_ref().expect("clock");
        [
            clock.ageing_at.clone(),
            clock.ask_at.clone(),
            clock.park_due_at.clone(),
            clock.paused_until.clone(),
        ]
        .map(|instant| instant.map(|i| i.as_str().to_owned()))
    };
    // Due 2026-10-20 is after the clock start: the clock is paused until the due
    // day starts, then 14 days to ask, 7 to park, half the threshold to ageing.
    let view = detail(&read_set, quote).expect("detail");
    assert_eq!(
        at(&view),
        [
            Some("2026-10-27T00:00:00Z".to_owned()),
            Some("2026-11-03T00:00:00Z".to_owned()),
            Some("2026-11-10T00:00:00Z".to_owned()),
            Some("2026-10-20T00:00:00Z".to_owned()),
        ]
    );
    // The list carries the same instants; stored facts are untouched.
    let listed = Listing::of(OpenList::Next).page(&read_set);
    let item = listed
        .items
        .iter()
        .find(|i| i.id.as_str() == quote)
        .expect("item");
    assert_eq!(at(item), at(&view));
    assert_eq!(
        item.formulation
            .as_ref()
            .expect("clock")
            .consecutive_stalled,
        0
    );
    // A Next task without a clock has no formulation at all.
    let plain = detail(&read_set, "96ef92eb-82a0-5cb2-9eee-169aac98be43").expect("detail");
    assert!(plain.formulation.is_none());
    // The venue: due 2026-12-01 and extended once, so ask moves a week later.
    let venue = detail(&read_set, "2b255a85-6c5a-531d-9e19-983dd6d19b95").expect("detail");
    assert_eq!(
        at(&venue),
        [
            Some("2026-12-08T00:00:00Z".to_owned()),
            Some("2026-12-22T00:00:00Z".to_owned()),
            Some("2026-12-29T00:00:00Z".to_owned()),
            Some("2026-12-01T00:00:00Z".to_owned()),
        ]
    );
}

// -------------------------------------------------------------- counts, dates

#[test]
fn queries_026_fr_017_reference_store_counts_use_the_device_day() {
    let a = reference_store(OWNER_A).read_set();
    let utc = counts(&a, "2026-10-09T12:00:00Z", "UTC");
    assert_eq!(
        (
            utc.inbox,
            utc.next,
            utc.waiting,
            utc.someday,
            utc.overdue,
            utc.today
        ),
        (2, 3, 1, 3, 0, 0)
    );
    // Due 2026-10-20: 00:30 UTC is still the 19th in Los Angeles, the 20th in Tokyo.
    let la = counts(&a, "2026-10-20T00:30:00Z", "America/Los_Angeles");
    assert_eq!((la.overdue, la.today), (0, 0));
    let utc_day = counts(&a, "2026-10-20T00:30:00Z", "UTC");
    assert_eq!((utc_day.overdue, utc_day.today), (0, 1));
    let tokyo = counts(&a, "2026-10-20T00:30:00Z", "Asia/Tokyo");
    assert_eq!((tokyo.overdue, tokyo.today), (0, 1));
    let late = counts(&a, "2026-12-02T08:00:00Z", "UTC");
    assert_eq!((late.overdue, late.today), (2, 0));
    // 15:30 UTC is already the 21st in Tokyo: the task due on the 20th is overdue.
    let tokyo_late = counts(&a, "2026-10-20T15:30:00Z", "Asia/Tokyo");
    assert_eq!((tokyo_late.overdue, tokyo_late.today), (1, 0));
    let unknown = {
        let query: Query = serde_json::from_value(json!({ "kind": "list_counts" })).expect("query");
        run(&a, &query, "2026-10-09T12:00:00Z", "Not/AZone").expect_err("zone")
    };
    assert_eq!(unknown.reason, Reason::InvalidTimeZone);
}

#[test]
fn queries_026_fr_017_inbox_count_is_projectless_but_date_counts_keep_assigned_tasks() {
    // GTDQueries.counts: an assigned inbox task is not in the Inbox badge, but a
    // dated one still counts as overdue or due today; terminal tasks never count.
    let read_set = Store {
        tasks: vec![
            task("t-loose", "loose", "inbox", 0),
            with(
                task("t-assigned", "assigned", "inbox", 1),
                "project_id",
                json!("p-1"),
            ),
            with(
                with(
                    task("t-late", "late", "inbox", 2),
                    "project_id",
                    json!("p-1"),
                ),
                "due_date",
                json!("2026-10-08"),
            ),
            with(
                task("t-today", "today", "waiting", 3),
                "due_date",
                json!("2026-10-09"),
            ),
            with(
                with(
                    task("t-done", "done", "completed", 4),
                    "due_date",
                    json!("2026-10-01"),
                ),
                "completed_at",
                json!("2026-10-02T09:00:00Z"),
            ),
        ],
        projects: vec![project("p-1", "P", "active")],
        ..Store::default()
    }
    .read_set();
    let counted = counts(&read_set, "2026-10-09T12:00:00Z", "UTC");
    assert_eq!(
        (
            counted.inbox,
            counted.next,
            counted.waiting,
            counted.someday,
            counted.overdue,
            counted.today
        ),
        (1, 0, 1, 0, 1, 1)
    );
}

// ----------------------------------------------------------- projects and tags

#[test]
fn queries_026_fr_009_reference_store_projects_and_tags_follow_the_server_order() {
    let a = reference_store(OWNER_A).read_set();
    let row = |summary: &bb_domain::types::ProjectSummary| {
        (
            summary.project.name.as_str().to_owned(),
            summary.open_task_count,
            summary.next_action_count,
            summary.needs_next_action(),
        )
    };
    let active: Vec<_> = projects(&a, ProjectFilter::Active)
        .iter()
        .map(row)
        .collect();
    assert_eq!(
        active,
        [
            ("Garden".to_owned(), 1, 0, true),
            ("Stra\u{df}e".to_owned(), 1, 1, false),
        ]
    );
    let archived: Vec<_> = projects(&a, ProjectFilter::Archived)
        .iter()
        .map(row)
        .collect();
    assert_eq!(
        archived,
        [
            ("Legacy Project".to_owned(), 1, 1, false),
            (
                "\u{41a}\u{432}\u{430}\u{440}\u{442}\u{438}\u{440}\u{430} No5".to_owned(),
                2,
                0,
                false
            ),
        ]
    );
    let all: Vec<String> = projects(&a, ProjectFilter::All)
        .iter()
        .map(|p| p.project.name.as_str().to_owned())
        .collect();
    assert_eq!(all.len(), 4);
    assert_eq!(all[..3], ["Garden", "Legacy Project", "Stra\u{df}e"]);

    let listed = tags(&a);
    let tag_rows: Vec<(&str, u32)> = listed
        .iter()
        .map(|t| (t.tag.name.as_str(), t.open_task_count))
        .collect();
    // The deleted tag is absent; the order is name.strip().casefold().
    assert_eq!(
        tag_rows,
        [("caf\u{e9}", 1), ("Deep Work", 1), ("Home", 1), ("work", 1)]
    );
}

#[test]
fn queries_026_fr_009_project_and_tag_order_follows_python_not_the_apple_key() {
    // C-06: Python `strip().casefold()` then id. No NFKC, no whitespace collapse,
    // no `@` strip and no diacritic fold, so an accent sorts after `z`.
    let read_set = Store {
        projects: vec![
            project("p-1", "\u{c9}clair", "active"),
            project("p-2", "eclair", "active"),
            project("p-3", "Zoo", "active"),
            project("p-4", "  alpha", "active"),
            project("p-6", "STRASSE", "active"),
            project("p-5", "Stra\u{df}e", "active"),
        ],
        tags: vec![
            tag("g-1", "@zed", "active"),
            tag("g-2", "Calls", "active"),
            tag("g-3", "b", "active"),
            tag("g-4", "gone", "deleted"),
        ],
        ..Store::default()
    }
    .read_set();
    let order: Vec<String> = projects(&read_set, ProjectFilter::All)
        .into_iter()
        .map(|p| p.project.id.into_string())
        .collect();
    // alpha, eclair, strasse (Stra\u{df}e before STRASSE by id), zoo, then the accent.
    assert_eq!(order, ["p-4", "p-2", "p-5", "p-6", "p-3", "p-1"]);
    let tag_names: Vec<String> = tags(&read_set)
        .into_iter()
        .map(|t| t.tag.name.into_string())
        .collect();
    assert_eq!(tag_names, ["@zed", "b", "Calls"]);
}

#[test]
fn queries_026_fr_002_project_display_is_decided_once() {
    let a = reference_store(OWNER_A).read_set();
    let garden = display(&a, "66055107-daf7-57da-95a4-8d3803adb031").expect("display");
    assert_eq!(
        (
            garden.is_archived,
            garden.accepts_new_tasks,
            garden.shows_pre_lossless_line,
            garden.label.as_str()
        ),
        (false, true, false, "Garden")
    );
    let flat = display(&a, "8af3bf55-0969-56e4-9eac-16cf5d8da698").expect("display");
    assert_eq!(
        (
            flat.is_archived,
            flat.accepts_new_tasks,
            flat.shows_pre_lossless_line,
            flat.label.as_str()
        ),
        (
            true,
            false,
            false,
            "\u{41a}\u{432}\u{430}\u{440}\u{442}\u{438}\u{440}\u{430} No5 \u{b7} archived"
        )
    );
    // Archived before archives kept memberships: the explanation shows only when
    // no task of any state still names the project.
    let legacy = "ecd232db-17cc-5f24-a604-a7be5e7f5829";
    assert!(
        !display(&a, legacy)
            .expect("display")
            .shows_pre_lossless_line
    );
    let mut emptied = reference_store(OWNER_A);
    emptied
        .tasks
        .retain(|task| task["project_id"].as_str() != Some(legacy));
    let shown = display(&emptied.read_set(), legacy).expect("display");
    assert!(shown.shows_pre_lossless_line && shown.is_archived && !shown.accepts_new_tasks);
    assert_eq!(
        display(&a, "nope").expect_err("unknown").reason,
        Reason::NotFound
    );
}

// --------------------------------------- backend API scenarios over a read set

#[test]
fn queries_026_fr_009_backend_task_list_filters_counts_and_stable_cursor() {
    // test_task_api.py::test_task_list_filters_counts_and_stable_cursor
    let mut cancelled = task("t-cancelled", "Cancelled", "cancelled", 4);
    cancelled["cancelled_at"] = json!("2026-09-02T10:00:00Z");
    let mut completed = task("t-done", "Done", "completed", 3);
    completed["completed_at"] = json!("2026-09-02T10:00:00Z");
    let read_set = Store {
        tasks: vec![
            task("t-first", "First", "inbox", 0),
            task("t-second", "Second", "inbox", 1),
            with(
                with(
                    task("t-assigned", "Assigned", "inbox", 2),
                    "project_id",
                    json!("p-health"),
                ),
                "tag_ids",
                json!(["g-phone"]),
            ),
            completed,
            cancelled,
        ],
        projects: vec![project("p-health", "Health", "active")],
        tags: vec![tag("g-phone", "phone", "active")],
        ..Store::default()
    }
    .read_set();
    // The projectless Inbox is the product list: the assigned task is not in it.
    let page = Listing::of(OpenList::Inbox).limit(1).page(&read_set);
    assert!(page.has_more);
    assert_eq!(ids(&page.items), ["t-first"]);
    assert_eq!(counts_of(&page)[0], 2);
    let next_page = Listing::of(OpenList::Inbox)
        .limit(1)
        .after(page.next_cursor.as_deref())
        .page(&read_set);
    assert_eq!(ids(&next_page.items), ["t-second"]);
    assert!(!next_page.has_more);
    // A cursor of the Inbox projection does not continue another list.
    let error = Listing::of(OpenList::Next)
        .after(page.next_cursor.as_deref())
        .run(&read_set)
        .expect_err("another list");
    assert_eq!(error.reason, Reason::InvalidValue);
    // Project and tag together.
    let assigned = Listing::of(OpenList::Inbox)
        .project("p-health")
        .tag("g-phone")
        .page(&read_set);
    assert_eq!(ids(&assigned.items), ["t-assigned"]);
    assert_eq!(counts_of(&assigned), [1, 0, 0, 0]);
    // Terminal tasks are in no open list.
    for list in OpenList::ALL {
        let page = Listing::of(*list).page(&read_set);
        assert!(
            !ids(&page.items).contains(&"t-done") && !ids(&page.items).contains(&"t-cancelled"),
            "{list:?}"
        );
    }
}

#[test]
fn queries_026_fr_002_backend_projectless_inbox_projection_tracks_assignment() {
    // test_task_api.py::test_projectless_inbox_projection_paginates_searches_and_tracks_assignment
    let build = |first_project: Option<&str>, project_state: &str| {
        Store {
            tasks: vec![
                with(
                    task("t-first", "Shared alpha projectless", "inbox", 0),
                    "project_id",
                    json!(first_project),
                ),
                with(
                    task("t-assigned", "Shared assigned alpha", "inbox", 1),
                    "project_id",
                    json!("p-launch"),
                ),
                task("t-second", "Shared beta projectless", "inbox", 2),
            ],
            projects: vec![project("p-launch", "Launch Inbox", project_state)],
            ..Store::default()
        }
        .read_set()
    };
    let before = build(None, "active");
    let page = Listing::of(OpenList::Inbox).limit(1).page(&before);
    assert_eq!(
        counts_of(&page)[0],
        2,
        "counted over every match, not the page"
    );
    assert!(page.has_more);
    assert!(page.items.iter().all(|item| item.project_id.is_none()));
    let second = Listing::of(OpenList::Inbox)
        .limit(1)
        .after(page.next_cursor.as_deref())
        .page(&before);
    let both: Vec<&str> = ids(&page.items)
        .into_iter()
        .chain(ids(&second.items))
        .collect();
    assert_eq!(both, ["t-first", "t-second"]);
    assert!(!second.has_more);
    // A cursor from the projection is refused by the raw-state query (an Inbox
    // read for one project) and the other way round.
    let raw = Listing::of(OpenList::Inbox)
        .project("p-launch")
        .after(page.next_cursor.as_deref())
        .run(&before)
        .expect_err("raw state query");
    assert_eq!(raw.reason, Reason::InvalidValue);
    let raw_page = Listing::of(OpenList::Inbox)
        .project("p-launch")
        .limit(1)
        .page(&before);
    assert_eq!(ids(&raw_page.items), ["t-assigned"]);
    assert!(raw_page.next_cursor.is_none() && !raw_page.has_more);

    // Assigning the first task removes it from the Inbox, not from the project.
    let assigned = build(Some("p-launch"), "active");
    let inbox = Listing::of(OpenList::Inbox).page(&assigned);
    assert_eq!(ids(&inbox.items), ["t-second"]);
    assert_eq!(counts_of(&inbox)[0], 1);
    let in_project = Listing::of(OpenList::Inbox)
        .project("p-launch")
        .page(&assigned);
    assert!(ids(&in_project.items).contains(&"t-first"));
    // Archiving keeps the assignment: the task stays out of the Inbox.
    let archived = build(Some("p-launch"), "archived");
    assert_eq!(
        ids(&Listing::of(OpenList::Inbox).page(&archived).items),
        ["t-second"]
    );
    let kept = detail(&archived, "t-first").expect("detail");
    assert_eq!(kept.project_id.expect("kept").as_str(), "p-launch");
}

#[test]
fn queries_026_fr_009_backend_priority_due_and_title_sorts_compose_with_the_cursor() {
    // test_task_api.py::test_task_priority_search_date_sort_and_cursor_filters_compose
    let read_set = Store {
        tasks: vec![
            with(
                with(
                    with(
                        with(
                            task("t-urgent", "Ship billing audit", "next", 0),
                            "project_id",
                            json!("p-launch"),
                        ),
                        "tag_ids",
                        json!(["g-deep"]),
                    ),
                    "due_date",
                    json!("2026-01-02"),
                ),
                "priority",
                json!("high"),
            ),
            with(
                with(
                    task("t-alpha", "Write alpha notes", "next", 1),
                    "due_date",
                    json!("2026-01-01"),
                ),
                "priority",
                json!("low"),
            ),
            with(
                task("t-medium", "Undated medium", "next", 2),
                "priority",
                json!("medium"),
            ),
        ],
        projects: vec![project("p-launch", "Launch", "active")],
        tags: vec![tag("g-deep", "Deep Work", "active")],
        ..Store::default()
    }
    .read_set();
    let scoped = Listing::of(OpenList::Next)
        .project("p-launch")
        .tag("g-deep")
        .sorted(TaskSort::Priority)
        .page(&read_set);
    assert_eq!(ids(&scoped.items), ["t-urgent"]);
    assert_eq!(counts_of(&scoped), [0, 1, 0, 0]);
    let due = Listing::of(OpenList::Next)
        .sorted(TaskSort::Due)
        .page(&read_set);
    let titles: Vec<&str> = due.items.iter().map(|i| i.title.as_str()).collect();
    assert_eq!(
        titles,
        ["Write alpha notes", "Ship billing audit", "Undated medium"]
    );
    let priority = Listing::of(OpenList::Next)
        .sorted(TaskSort::Priority)
        .limit(2)
        .page(&read_set);
    assert_eq!(ids(&priority.items), ["t-urgent", "t-medium"]);
    let rest = Listing::of(OpenList::Next)
        .sorted(TaskSort::Priority)
        .limit(2)
        .after(priority.next_cursor.as_deref())
        .page(&read_set);
    assert_eq!(ids(&rest.items), ["t-alpha"]);
    // The cursor carries its sort: a title read cannot continue it.
    let error = Listing::of(OpenList::Next)
        .sorted(TaskSort::Title)
        .limit(2)
        .after(priority.next_cursor.as_deref())
        .run(&read_set)
        .expect_err("another sort");
    assert_eq!(error.reason, Reason::InvalidValue);
    // test_task_lifecycle_detail_api.py: medium sorts before low.
    let low_and_medium = Store {
        tasks: vec![
            with(
                task("t-call", "Call Ada about launch", "inbox", 0),
                "priority",
                json!("low"),
            ),
            with(
                task("t-medium", "Medium task", "inbox", 1),
                "priority",
                json!("medium"),
            ),
        ],
        ..Store::default()
    }
    .read_set();
    let sorted = Listing::of(OpenList::Inbox)
        .sorted(TaskSort::Priority)
        .page(&low_and_medium);
    let titles: Vec<&str> = sorted.items.iter().map(|i| i.title.as_str()).collect();
    assert_eq!(titles, ["Medium task", "Call Ada about launch"]);
}

#[test]
fn queries_026_fr_009_backend_manual_order_breaks_ties_by_creation_time_then_id() {
    let read_set = Store {
        tasks: vec![
            with(
                task("t-c", "c", "next", 1),
                "created_at",
                json!("2026-09-02T09:00:01Z"),
            ),
            with(
                task("t-b", "b", "next", 1),
                "created_at",
                json!("2026-09-02T09:00:00Z"),
            ),
            task("t-a", "a", "next", 1),
            task("t-z", "z", "next", 0),
            with(
                task("t-late", "late", "next", 10),
                "created_at",
                json!("2026-09-01T00:00:00Z"),
            ),
        ],
        ..Store::default()
    }
    .read_set();
    // order_key is numeric (10 after 1), then created_at, then id.
    let page = Listing::of(OpenList::Next).page(&read_set);
    assert_eq!(ids(&page.items), ["t-z", "t-a", "t-b", "t-c", "t-late"]);
}

#[test]
fn queries_026_fr_002_backend_detail_orders_subtasks_and_comments() {
    // test_task_lifecycle_detail_api.py::test_subtask_and_comment_detail_commands_persist
    let subtask = |id: &str, task: &str, order: u64| {
        json!({ "id": id, "task_id": task, "title": id, "state": "open",
                "order_key": order.to_string(), "revision": "1" })
    };
    let comment = |id: &str, task: &str, at: &str| {
        json!({ "id": id, "task_id": task, "body": id, "actor_id": "u-1",
                "created_at": at, "edited_at": null, "revision": "1" })
    };
    let read_set = Store {
        tasks: vec![task("t-1", "one", "next", 0), task("t-2", "two", "next", 1)],
        subtasks: vec![
            subtask("s-b", "t-1", 1),
            subtask("s-a", "t-1", 1),
            subtask("s-10", "t-1", 10),
            subtask("s-0", "t-1", 0),
            subtask("s-other", "t-2", 0),
        ],
        comments: vec![
            comment("c-late", "t-1", "2026-09-03T09:00:00Z"),
            comment("c-b", "t-1", "2026-09-02T09:00:00Z"),
            comment("c-a", "t-1", "2026-09-02T09:00:00Z"),
            comment("c-frac", "t-1", "2026-09-02T09:00:00.25Z"),
            comment("c-other", "t-2", "2026-09-01T09:00:00Z"),
        ],
        ..Store::default()
    }
    .read_set();
    let view = detail(&read_set, "t-1").expect("detail");
    let subtasks: Vec<&str> = view.subtasks.iter().map(|s| s.id.as_str()).collect();
    assert_eq!(subtasks, ["s-0", "s-a", "s-b", "s-10"]);
    let comments: Vec<&str> = view.comments.iter().map(|c| c.id.as_str()).collect();
    assert_eq!(comments, ["c-a", "c-b", "c-frac", "c-late"]);
    assert_eq!(view.title.as_str(), "one");
}

#[test]
fn queries_026_fr_009_backend_projects_and_tags_listed_by_normalized_name() {
    // test_task_api.py::test_project_and_tag_creation_are_idempotent_and_listed_by_normalized_name
    let read_set = Store {
        projects: vec![
            project("p-zoo", "Zoo", "active"),
            project("p-alpha", "alpha", "active"),
        ],
        tags: vec![tag("g-calls", "Calls", "active")],
        ..Store::default()
    }
    .read_set();
    let order: Vec<String> = projects(&read_set, ProjectFilter::Active)
        .into_iter()
        .map(|p| p.project.name.into_string())
        .collect();
    assert_eq!(order, ["alpha", "Zoo"]);
    assert_eq!(tags(&read_set)[0].tag.name.as_str(), "Calls");
}

#[test]
fn queries_026_fr_002_backend_archive_keeps_assignments_in_every_open_list() {
    // test_task_api.py::test_project_archive_keeps_assignments_from_all_task_states
    let in_project = |id: &str, state: &str, order: u64| {
        with(task(id, id, state, order), "project_id", json!("p-cleanup"))
    };
    let read_set = Store {
        tasks: vec![
            in_project("t-inbox", "inbox", 0),
            in_project("t-next", "next", 1),
            in_project("t-waiting", "waiting", 2),
            in_project("t-someday", "someday", 3),
        ],
        projects: vec![project("p-cleanup", "Cleanup", "archived")],
        ..Store::default()
    }
    .read_set();
    for (list, wanted) in [
        (OpenList::Inbox, "t-inbox"),
        (OpenList::Next, "t-next"),
        (OpenList::Waiting, "t-waiting"),
        (OpenList::Someday, "t-someday"),
    ] {
        let page = Listing::of(list).project("p-cleanup").page(&read_set);
        assert_eq!(ids(&page.items), [wanted]);
        assert_eq!(counts_of(&page), [1, 1, 1, 1]);
    }
    let summary = &projects(&read_set, ProjectFilter::Archived)[0];
    assert_eq!((summary.open_task_count, summary.next_action_count), (4, 1));
    // The projectless Inbox holds none of them.
    assert!(
        Listing::of(OpenList::Inbox)
            .page(&read_set)
            .items
            .is_empty()
    );
}

// ----------------------------------------------------------------- dispatch

#[test]
fn queries_026_fr_002_every_task_query_kind_is_answered_through_query() {
    let a = reference_store(OWNER_A).read_set();
    let kinds = [
        json!({ "kind": "task_list", "list": "next", "project_id": null, "tag_id": null,
                "sort": "manual", "page": { "limit": 10, "after": null } }),
        json!({ "kind": "task_detail", "task_id": "da6395c2-8e67-527b-be6d-4b5673d9e756" }),
        json!({ "kind": "list_counts" }),
        json!({ "kind": "projects", "filter": "all" }),
        json!({ "kind": "project_display", "project_id": "66055107-daf7-57da-95a4-8d3803adb031" }),
        json!({ "kind": "tags" }),
    ];
    let mut tags_seen = Vec::new();
    for raw in &kinds {
        let query: Query = serde_json::from_value(raw.clone()).expect("query");
        let result = run(&a, &query, "2026-10-09T12:00:00Z", "UTC").expect("answered");
        let wire = serde_json::to_value(&result).expect("json");
        tags_seen.push(wire["kind"].as_str().expect("kind").to_owned());
    }
    assert_eq!(
        tags_seen,
        [
            "task_list",
            "task_detail",
            "list_counts",
            "projects",
            "project_display",
            "tags"
        ]
    );
}

// ------------------------------------------------- bounded pagination, cursor shape

const ALL_SORTS: [TaskSort; 4] = [
    TaskSort::Manual,
    TaskSort::Due,
    TaskSort::Priority,
    TaskSort::Title,
];

/// A 10,000-task store with ties on every key part: a few order keys, minutes,
/// due days and priorities shared by many tasks, a quarter of the tasks without
/// a due date, mixed-case repeated titles, and every fifth task in another list.
/// Returns the read set and the Inbox tasks as `(id, title, order_key, minute,
/// due, priority rank)`.
type Generated = (String, String, u64, u64, Option<String>, usize);

fn large_store() -> (ReadSet, Vec<Generated>) {
    const PRIORITIES: [&str; 4] = ["high", "medium", "low", "none"];
    let mut tasks = Vec::new();
    let mut expected = Vec::new();
    let mut seed: u64 = 0x2545_f491_4f6c_dd1d;
    let mut roll = |modulus: u64| {
        seed = seed
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        (seed >> 33) % modulus
    };
    for index in 0..10_000_u64 {
        let id = format!("t-{index:05}");
        let title = format!(
            "{}{}",
            ["alpha", "Alpha", "BETA", "gamma", "Delta"][roll(5) as usize],
            roll(40)
        );
        let order_key = roll(60);
        let minute = roll(7);
        let due = (roll(4) != 0).then(|| format!("2026-10-{:02}", 1 + roll(9)));
        let priority = roll(4) as usize;
        let state = if index % 5 == 0 { "next" } else { "inbox" };
        let mut row = with(
            task(&id, &title, state, order_key),
            "priority",
            json!(PRIORITIES[priority]),
        );
        row = with(
            row,
            "created_at",
            json!(format!("2026-09-02T09:0{minute}:00Z")),
        );
        row = with(row, "due_date", json!(due));
        tasks.push(row);
        if state == "inbox" {
            expected.push((id, title, order_key, minute, due, priority));
        }
    }
    let read_set = Store {
        tasks,
        ..Store::default()
    }
    .read_set();
    (read_set, expected)
}

/// The server's `_sort_key` order, worked out here from the generated columns.
fn expected_order(mut rows: Vec<Generated>, sort: TaskSort) -> Vec<String> {
    let manual = |row: &Generated| (row.2, row.3, row.0.clone());
    rows.sort_by_cached_key(|row| match sort {
        TaskSort::Manual => (0, String::new(), 0, manual(row)),
        TaskSort::Due => (
            u64::from(row.4.is_none()),
            row.4.clone().unwrap_or_default(),
            0,
            manual(row),
        ),
        TaskSort::Priority => (row.5 as u64, String::new(), 0, manual(row)),
        TaskSort::Title => (0, row.1.to_lowercase(), 0, (0, 0, row.0.clone())),
    });
    rows.into_iter().map(|row| row.0).collect()
}

#[test]
fn queries_026_fr_009_a_ten_thousand_task_store_pages_in_full_order_for_every_sort() {
    let (read_set, rows) = large_store();
    assert_eq!(rows.len(), 8_000);
    for sort in ALL_SORTS {
        let expected = expected_order(rows.clone(), sort);
        // A limit that divides nothing, so the last page is short.
        let limit = 199;
        let mut seen: Vec<String> = Vec::new();
        let mut after: Option<String> = None;
        let mut pages = 0;
        loop {
            let page = Listing::of(OpenList::Inbox)
                .sorted(sort)
                .limit(limit)
                .after(after.as_deref())
                .page(&read_set);
            pages += 1;
            assert!(page.items.len() <= limit as usize);
            assert_eq!(page.counts_by_state.inbox, 8_000);
            assert_eq!(page.counts_by_state.next, 2_000);
            seen.extend(ids(&page.items).into_iter().map(str::to_owned));
            assert_eq!(page.has_more, page.next_cursor.is_some());
            if !page.has_more {
                break;
            }
            after = page.next_cursor;
        }
        assert_eq!(pages, 41, "{sort:?}");
        assert_eq!(seen.len(), expected.len(), "{sort:?}: no gap, no duplicate");
        assert_eq!(
            seen, expected,
            "{sort:?}: the concatenated pages are the full order"
        );
    }
}

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

/// The server's own cursor with its `last` key replaced, filters untouched.
fn cursor_with_last(cursor: &str, last: &[Value]) -> String {
    let mut payload: Value = serde_json::from_slice(&unbase64url(cursor)).expect("cursor json");
    payload["last"] = Value::Array(last.to_vec());
    base64url(payload.to_string().as_bytes())
}

fn cursor_last(cursor: &str) -> Vec<Value> {
    let payload: Value = serde_json::from_slice(&unbase64url(cursor)).expect("cursor json");
    payload["last"].as_array().expect("last").clone()
}

fn assert_cursor_refused(read_set: &ReadSet, sort: TaskSort, cursor: &str, why: &str) {
    let error = Listing::of(OpenList::Inbox)
        .sorted(sort)
        .limit(1)
        .after(Some(cursor))
        .run(read_set)
        .expect_err(why);
    assert_eq!(
        (error.reason, error.field.as_deref()),
        (Reason::InvalidValue, Some("cursor")),
        "{sort:?}: {why}"
    );
}

#[test]
fn queries_026_fr_009_a_cursor_key_of_the_wrong_shape_is_refused_for_every_sort() {
    let read_set = Store {
        tasks: vec![
            task("t-a", "a", "inbox", 0),
            task("t-b", "b", "inbox", 1),
            task("t-c", "c", "inbox", 2),
        ],
        ..Store::default()
    }
    .read_set();
    for sort in ALL_SORTS {
        let first = Listing::of(OpenList::Inbox)
            .sorted(sort)
            .limit(1)
            .page(&read_set);
        let cursor = first.next_cursor.expect("a cursor");
        let last = cursor_last(&cursor);
        // The untouched key, re-encoded, still continues the list.
        let valid = cursor_with_last(&cursor, &last);
        let rest = Listing::of(OpenList::Inbox)
            .sorted(sort)
            .limit(5)
            .after(Some(&valid))
            .page(&read_set);
        assert_eq!(ids(&rest.items), ["t-b", "t-c"], "{sort:?}");

        // Wrong length: shorter, longer, and a lone text part.
        let mut shorter = last.clone();
        shorter.pop();
        assert_cursor_refused(
            &read_set,
            sort,
            &cursor_with_last(&cursor, &shorter),
            "shorter",
        );
        let mut longer = last.clone();
        longer.push(json!("x"));
        assert_cursor_refused(
            &read_set,
            sort,
            &cursor_with_last(&cursor, &longer),
            "longer",
        );
        assert_cursor_refused(
            &read_set,
            sort,
            &cursor_with_last(&cursor, &[json!("x")]),
            "lone text",
        );
        assert_cursor_refused(
            &read_set,
            sort,
            &cursor_with_last(&cursor, &[json!(1)]),
            "lone int",
        );

        // Wrong variant at each position: an integer for text and text for an integer.
        for position in 0..last.len() {
            let mut swapped = last.clone();
            swapped[position] = if last[position].is_u64() {
                json!("x")
            } else {
                json!(7)
            };
            assert_cursor_refused(
                &read_set,
                sort,
                &cursor_with_last(&cursor, &swapped),
                &format!("variant at position {position}"),
            );
        }
    }
}
