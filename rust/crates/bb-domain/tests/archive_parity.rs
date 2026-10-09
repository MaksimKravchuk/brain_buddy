//! Parity of the archive and restoration family with the server and the
//! frozen oracle (tasks.md T009, PR-09).
//!
//! The runner compiles the **actual** rule source with a plain `#[path]`
//! module, includes the already-merged organization rules under their
//! production name (they decide `project.archive` / `project.unarchive`) and
//! re-exports the shared crates at the test-crate root, so the rule's own
//! `crate::` paths resolve exactly as they do in the library. Every
//! data-driven test counts the cases it executed, so an empty or truncated
//! section fails instead of passing vacuously.

#[path = "../src/archive.rs"]
mod archive;
#[allow(dead_code)]
#[path = "../src/organize.rs"]
mod organize;
mod support;

pub use bb_domain::{calendar, normalization, types};

use bb_protocol::command::{Decoded, decode_command};
use serde_json::{Map, Value, json};
use support::{cases, text};
use types::{
    ChangeOutcome, ChangeSet, DomainChange, DomainCommand, ExecutionInputs, ProjectFilter,
    ProjectId, ProjectState, ReadSet, Reason, Record,
};

const NOW: &str = "2026-10-09T12:00:00Z";
const OWNER: &str = "beea96a4-7827-599d-b786-571f694828ac";

// ----------------------------------------------------------------------- harness

fn project_json(
    id: &str,
    name: &str,
    state: &str,
    archived_at: Option<&str>,
    marker: bool,
) -> Value {
    json!({
        "id": id, "name": name, "color": null, "state": state,
        "revision": "3", "desired_outcome": null,
        "archived_at": archived_at, "archived_before_lossless": marker
    })
}

fn task_json(id: &str, state: &str, project: Option<&str>) -> Value {
    json!({
        "id": id, "title": format!("Task {id}"), "details": null, "state": state,
        "project_id": project, "tag_ids": [], "due_date": null, "priority": "none",
        "waiting_for": null, "waiting_since": null, "order_key": "3",
        "source_capture_ids": [], "created_at": "2026-09-01T09:00:00Z",
        "updated_at": "2026-09-02T09:00:00Z", "completed_at": null, "cancelled_at": null,
        "revision": "2", "consecutive_stalled_formulations": 0,
        "formulation": null, "parked": null
    })
}

fn keyed(rows: &[Value]) -> Value {
    Value::Object(
        rows.iter()
            .map(|row| (row["id"].as_str().expect("id").to_owned(), row.clone()))
            .collect::<Map<_, _>>(),
    )
}

fn read_set(projects: &[Value], tasks: &[Value]) -> ReadSet {
    serde_json::from_value(json!({ "projects": keyed(projects), "tasks": keyed(tasks) }))
        .unwrap_or_else(|e| panic!("read set: {e}"))
}

/// The frozen reference dataset of one owner: projects and tasks, as the
/// public records the rules read.
fn owner_read_set(owner: &str) -> ReadSet {
    let records = &support::reference_store()["dataset"]["records"];
    let of_owner = |section: &str| -> Vec<Value> {
        cases(records, section)
            .iter()
            .filter(|row| text(row, "owner_id") == owner)
            .cloned()
            .collect()
    };
    let revision = |row: &Value| row["revision"].as_u64().expect("revision").to_string();
    let projects: Vec<Value> = of_owner("projects")
        .iter()
        .map(|p| {
            json!({
                "id": p["id"], "name": p["name"], "color": p["color"], "state": p["state"],
                "revision": revision(p), "desired_outcome": p["desired_outcome"],
                "archived_at": p["archived_at"],
                "archived_before_lossless": p["archived_before_lossless"]
            })
        })
        .collect();
    let tasks: Vec<Value> = of_owner("tasks")
        .iter()
        .map(|t| task_json(text(t, "id"), text(t, "state"), t["project_id"].as_str()))
        .collect();
    read_set(&projects, &tasks)
}

fn inputs() -> ExecutionInputs {
    serde_json::from_value(json!({
        "rule_version": 1, "now": NOW, "time_zone": "UTC", "origin": "device",
        "actor_id": "actor-example", "authoritative": true, "allocated_ids": [],
        "policy": {
            "weekly_review": true, "navigator_provider": null,
            "navigator_available": false, "consent_text_version": 1
        }
    }))
    .expect("execution inputs")
}

fn project_command(kind: &str, id: &str, revision: u64) -> DomainCommand {
    let envelope = json!({
        "protocol_version": 1,
        "command_id": "01900000-0000-4000-8000-000000000001",
        "scope_id": "scope-example", "device_id": "device-example",
        "device_epoch": "epoch-example", "local_sequence": "7",
        "type": kind, "command_version": 1, "entity_id": id,
        "preconditions": [{
            "entity_type": "project", "entity_id": id, "edit_revision": revision.to_string()
        }],
        "depends_on": [], "issued_at": NOW, "payload": {}
    })
    .to_string();
    match decode_command(&envelope) {
        Ok(Decoded::Executable(envelope)) => {
            DomainCommand::from_envelope(&envelope, |_| None).unwrap_or_else(|e| panic!("{e:?}"))
        }
        other => panic!("{kind} did not decode as an executable command: {other:?}"),
    }
}

/// Lands a change set's upserts in the read set, in application order.
fn land(read_set: &mut ReadSet, set: &ChangeSet) {
    for change in &set.changes {
        match change {
            DomainChange::Upsert(Record::Project(p)) => {
                read_set.projects.insert(p.id.clone(), p.clone());
            }
            DomainChange::Upsert(Record::Task(t)) => {
                read_set.tasks.insert(t.id.clone(), t.clone());
            }
            other => panic!("an archive change set held {other:?}"),
        }
    }
}

/// Decides one project command and lands it.
fn run(read_set: &mut ReadSet, kind: &str, id: &str, revision: u64) -> ChangeSet {
    let command = project_command(kind, id, revision);
    let set = organize::decide(read_set, &command, &inputs())
        .unwrap_or_else(|e| panic!("{kind} {id}: {e:?}"));
    land(read_set, &set);
    set
}

fn project<'a>(read_set: &'a ReadSet, id: &str) -> &'a types::Project {
    &read_set.projects[&ProjectId::parse(id).expect("project id")]
}

fn id_of(read_set: &ReadSet, name: &str) -> String {
    read_set
        .projects
        .values()
        .find(|p| p.name.as_str() == name)
        .unwrap_or_else(|| panic!("no project {name:?}"))
        .id
        .as_str()
        .to_owned()
}

fn member_ids(read_set: &ReadSet, project: &str) -> Vec<String> {
    let id = ProjectId::parse(project).expect("project id");
    archive::members_of(read_set, &id)
        .map(|t| t.id.as_str().to_owned())
        .collect()
}

fn open_count(read_set: &ReadSet, project: &str) -> u32 {
    archive::open_member_count(read_set, &ProjectId::parse(project).expect("project id"))
}

fn ran_all(section: &str, ran: usize, expected: usize) {
    assert!(ran > 0, "{section}: no case executed");
    assert_eq!(
        ran, expected,
        "{section}: executed cases differ from the file"
    );
}

// ----------------------------------- parity: the golden list trace (TR-L01, backend)

fn project_archive_traces() -> Value {
    let path = support::repo_root().join("backend/tests/fixtures/project_archive_traces.json");
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
    serde_json::from_str(&text)
        .unwrap_or_else(|e| panic!("invalid JSON in {}: {e}", path.display()))
}

fn listing(read_set: &ReadSet, path: &str) -> (u16, Value) {
    let state = path.split_once("?state=").map(|(_, state)| state);
    match archive::parse_state_filter(state) {
        Err(error) => {
            assert_eq!(
                (error.reason, error.field.as_deref()),
                (Reason::InvalidValue, Some("state"))
            );
            (422, Value::Null)
        }
        Ok(filter) => {
            let rows = archive::projects_in_state(read_set, filter)
                .iter()
                .map(|p| {
                    json!({
                        "name": p.name.as_str(), "state": p.state.as_str(),
                        "archived_at": p.archived_at.as_ref().map(|i| i.as_str())
                    })
                })
                .collect();
            (200, Value::Array(rows))
        }
    }
}

fn assert_subset(expected: &Value, actual: &Value, at: &str) {
    match (expected, actual) {
        (Value::String(s), actual) if s == "$present" => assert!(!actual.is_null(), "{at}: null"),
        (Value::Object(want), Value::Object(have)) => {
            for (key, value) in want {
                let found = have
                    .get(key)
                    .unwrap_or_else(|| panic!("{at}: missing {key}"));
                assert_subset(value, found, &format!("{at}.{key}"));
            }
        }
        (Value::Array(want), Value::Array(have)) => {
            assert_eq!(want.len(), have.len(), "{at}");
            for (index, (w, h)) in want.iter().zip(have).enumerate() {
                assert_subset(w, h, &format!("{at}[{index}]"));
            }
        }
        (want, have) => assert_eq!(want, have, "{at}"),
    }
}

#[test]
fn archive_026_fr_002_the_list_trace_replays_through_the_shared_filter() {
    let file = project_archive_traces();
    let trace = cases(&file, "traces")
        .iter()
        .find(|t| text(t, "id") == "TR-L01")
        .expect("TR-L01 is in the golden traces");
    let mut set = ReadSet::default();
    let mut captured = std::collections::HashMap::<String, String>::new();
    let (mut created, mut seeded, mut listings, mut refused) = (0, 0, 0, 0);
    for step in trace["steps"].as_array().expect("steps") {
        if let Some(seed) = step.get("seed") {
            // `archive_keeping_members`: archived with a stamp, members untouched, one revision up.
            assert_eq!(text(seed, "kind"), "archive_keeping_members");
            let var = text(seed, "project").trim_matches(|c| c == '{' || c == '}');
            let id = ProjectId::parse(&captured[var]).expect("captured id");
            let row = set.projects.get(&id).expect("seeded project").clone();
            let mut doc = serde_json::to_value(&row).expect("project json");
            doc["state"] = json!("archived");
            doc["archived_at"] = json!("2026-10-01T10:00:00Z");
            doc["revision"] = json!("2");
            set.projects
                .insert(id, serde_json::from_value(doc).expect("project"));
            seeded += 1;
            continue;
        }
        let request = &step["request"];
        let (method, path) = (text(request, "method"), text(request, "path"));
        let expect = &step["expect"];
        if method == "POST" {
            // `POST /api/projects`: an active project; its ID is minted here.
            let id = format!("project{:02}", set.projects.len() + 1);
            set.projects.insert(
                ProjectId::parse(&id).expect("id"),
                serde_json::from_value(project_json(
                    &id,
                    text(&request["body"], "name"),
                    "active",
                    None,
                    false,
                ))
                .map(|mut p: types::Project| {
                    p.revision = 1.into();
                    p
                })
                .expect("project"),
            );
            for (variable, _) in step["capture"].as_object().into_iter().flatten() {
                captured.insert(variable.clone(), id.clone());
            }
            created += 1;
            continue;
        }
        let (status, body) = listing(&set, path);
        assert_eq!(
            i64::from(status),
            expect["status"].as_i64().unwrap(),
            "{}",
            text(step, "name")
        );
        if let Some(want) = expect.get("body") {
            assert_subset(want, &body, text(step, "name"));
        }
        if status == 200 {
            listings += 1
        } else {
            refused += 1
        }
    }
    assert_eq!(
        (created, seeded),
        (2, 1),
        "the trace builds two projects, archives one"
    );
    ran_all("TR-L01 listings", listings, 4);
    ran_all("TR-L01 refusals", refused, 1);
}

// ------------------------------------------------ list order and filter parsing

#[test]
fn archive_026_fr_002_listing_orders_by_folded_name_then_id() {
    let set = read_set(
        &[
            project_json("p3", "strasse", "active", None, false),
            project_json(
                "p2",
                "Straße",
                "archived",
                Some("2026-09-01T09:00:00Z"),
                false,
            ),
            project_json("p1", "STRASSE", "active", None, false),
            project_json(
                "p4",
                "Álamo",
                "archived",
                Some("2026-09-01T09:00:00Z"),
                false,
            ),
            project_json("p5", "alamo", "active", None, false),
        ],
        &[],
    );
    let list = |filter| -> Vec<String> {
        archive::projects_in_state(&set, filter)
            .iter()
            .map(|p| p.id.as_str().to_owned())
            .collect()
    };
    // Full case folding makes "ß" equal "ss" and equal keys fall back to the ID. The key is only
    // trimmed and folded (`name.strip().casefold()`), so "Álamo" does not fold to "alamo".
    assert_eq!(list(ProjectFilter::All), ["p5", "p1", "p2", "p3", "p4"]);
    assert_eq!(list(ProjectFilter::Active), ["p5", "p1", "p3"]);
    assert_eq!(list(ProjectFilter::Archived), ["p2", "p4"]);
    assert!(archive::projects_in_state(&ReadSet::default(), ProjectFilter::All).is_empty());
}

#[test]
fn archive_026_fr_002_the_state_parameter_defaults_to_active_and_refuses_anything_else() {
    assert_eq!(archive::parse_state_filter(None), Ok(ProjectFilter::Active));
    for (raw, want) in [
        ("active", ProjectFilter::Active),
        ("archived", ProjectFilter::Archived),
        ("all", ProjectFilter::All),
    ] {
        assert_eq!(archive::parse_state_filter(Some(raw)), Ok(want), "{raw}");
    }
    let mut refused = 0;
    for raw in ["bogus", "", "ACTIVE", "Archived", " all", "active,archived"] {
        let error = archive::parse_state_filter(Some(raw)).expect_err(raw);
        assert_eq!(
            (error.reason, error.field.as_deref()),
            (Reason::InvalidValue, Some("state"))
        );
        refused += 1;
    }
    ran_all("refused state values", refused, 6);
}

// ------------------------------------- parity: archive retains membership (T002)

#[test]
fn archive_026_fr_009_the_reference_archive_keeps_every_member_in_every_state() {
    let set = owner_read_set(OWNER);
    // The oracle's archived project holds a waiting, a someday and a cancelled task.
    let flat = id_of(&set, "Квартира No5");
    assert_eq!(project(&set, &flat).state, ProjectState::Archived);
    assert_eq!(member_ids(&set, &flat).len(), 3);
    assert_eq!(
        open_count(&set, &flat),
        2,
        "the cancelled member is kept but not open"
    );
    // The legacy archive keeps the one task the oracle gives it.
    let legacy = id_of(&set, "Legacy Project");
    assert_eq!(member_ids(&set, &legacy).len(), 1);
    assert_eq!(open_count(&set, &legacy), 1);
    // Another account's project is not a member source.
    let other = owner_read_set("863e24a2-2512-59a9-8531-f435e248f118");
    assert_eq!(
        archive::members_of(&other, &ProjectId::parse(&flat).unwrap()).count(),
        0
    );
}

#[test]
fn archive_026_fr_009_archive_and_unarchive_change_no_task_and_keep_the_counts() {
    let mut set = owner_read_set(OWNER);
    let strasse = id_of(&set, "Straße");
    let (members, open) = (member_ids(&set, &strasse), open_count(&set, &strasse));
    assert_eq!((members.len(), open), (1, 1));
    let tasks = set.tasks.clone();

    let archived = run(&mut set, "project.archive", &strasse, 1);
    assert_eq!(
        archived.changes.len(),
        1,
        "a lossless archive is one record"
    );
    assert_eq!(set.tasks, tasks);
    assert_eq!(project(&set, &strasse).state, ProjectState::Archived);
    assert_eq!(member_ids(&set, &strasse), members);
    assert_eq!(open_count(&set, &strasse), open);

    let restored = run(&mut set, "project.unarchive", &strasse, 2);
    assert_eq!(restored.changes.len(), 1);
    assert_eq!(set.tasks, tasks);
    assert_eq!(project(&set, &strasse).state, ProjectState::Active);
    assert_eq!(member_ids(&set, &strasse), members);
    assert_eq!(open_count(&set, &strasse), open);
}

#[test]
fn archive_026_fr_009_completed_and_cancelled_members_stay_but_are_not_open() {
    let mut set = read_set(
        &[project_json("work", "Work", "active", None, false)],
        &[
            task_json("a", "next", Some("work")),
            task_json("b", "inbox", Some("work")),
            task_json("c", "completed", Some("work")),
            task_json("d", "cancelled", Some("work")),
            task_json("e", "waiting", None),
        ],
    );
    assert_eq!(
        (member_ids(&set, "work").len(), open_count(&set, "work")),
        (4, 2)
    );
    run(&mut set, "project.archive", "work", 3);
    assert_eq!(
        (member_ids(&set, "work").len(), open_count(&set, "work")),
        (4, 2)
    );
    // Placement is the task's own: archive moves no completed task out of the project.
    let completed = &set.tasks[&types::TaskId::parse("c").unwrap()];
    assert_eq!(
        completed.project_id,
        Some(ProjectId::parse("work").unwrap())
    );
}

// -------------------------------- legacy archive marker restoration (_mark_detached)

fn legacy_world() -> ReadSet {
    read_set(
        &[
            // Archived before ADR-0020: no stamp, marker not yet recorded.
            project_json("b-old", "Barn", "archived", None, false),
            project_json("a-old", "Attic", "archived", None, false),
            // Already recorded, lossless, active: all left alone.
            project_json("c-marked", "Cellar", "archived", None, true),
            project_json(
                "d-lossless",
                "Dairy",
                "archived",
                Some("2026-09-01T09:00:00Z"),
                false,
            ),
            project_json("e-active", "Eaves", "active", None, false),
        ],
        &[task_json("t1", "next", Some("d-lossless"))],
    )
}

#[test]
fn archive_026_fr_002_detached_archives_get_the_marker_without_a_revision_bump() {
    let mut set = legacy_world();
    let detached: Vec<&str> = set
        .projects
        .values()
        .filter(|p| archive::needs_marker(p))
        .map(|p| p.name.as_str())
        .collect();
    assert_eq!(detached, ["Attic", "Barn"]);

    let before = set.projects.clone();
    let restored = archive::restore_detached_archives(&set);
    assert_eq!(restored.outcome, ChangeOutcome::Applied);
    assert_eq!(restored.changes.len(), 2, "both records land together");
    let touched: Vec<&str> = restored
        .changes
        .iter()
        .map(|c| match c {
            DomainChange::Upsert(Record::Project(p)) => p.id.as_str(),
            other => panic!("unexpected {other:?}"),
        })
        .collect();
    assert_eq!(touched, ["a-old", "b-old"], "ID order");
    land(&mut set, &restored);
    for id in ["a-old", "b-old"] {
        let now = project(&set, id);
        let was = &before[&ProjectId::parse(id).unwrap()];
        assert!(now.archived_before_lossless && now.archived_at.is_none());
        assert_eq!(
            (&now.revision, &now.state),
            (&was.revision, &was.state),
            "{id}"
        );
    }
    for id in ["c-marked", "d-lossless", "e-active"] {
        let key = ProjectId::parse(id).unwrap();
        assert_eq!(set.projects[&key], before[&key], "{id} is unchanged");
    }
}

#[test]
fn archive_026_fr_002_marker_restoration_is_idempotent_and_ignores_current_data() {
    let mut set = legacy_world();
    let first = archive::restore_detached_archives(&set);
    land(&mut set, &first);
    let again = archive::restore_detached_archives(&set);
    assert_eq!(again.outcome, ChangeOutcome::NoOp);
    assert!(again.changes.is_empty());
    // Data written under the current rules never needs the step.
    for owner in [OWNER, "863e24a2-2512-59a9-8531-f435e248f118"] {
        let reference = owner_read_set(owner);
        assert_eq!(
            archive::restore_detached_archives(&reference).outcome,
            ChangeOutcome::NoOp,
            "{owner}"
        );
    }
    assert_eq!(
        archive::restore_detached_archives(&ReadSet::default()).outcome,
        ChangeOutcome::NoOp
    );
}

#[test]
fn archive_026_fr_002_a_restored_marker_survives_repeat_archive_and_unarchive() {
    let mut set = legacy_world();
    let restored = archive::restore_detached_archives(&set);
    land(&mut set, &restored);
    // A repeat archive only bumps the revision (server rule); the signal stays.
    run(&mut set, "project.archive", "a-old", 3);
    let repeat = project(&set, "a-old");
    assert!(repeat.archived_before_lossless && repeat.archived_at.is_none());
    assert_eq!(repeat.revision, types::Counter::from(4));
    // Unarchive reopens it, and the display still knows how it was archived.
    run(&mut set, "project.unarchive", "a-old", 4);
    let reopened = project(&set, "a-old");
    assert_eq!(reopened.state, ProjectState::Active);
    assert!(reopened.archived_before_lossless && reopened.archived_at.is_none());
    assert!(
        !archive::needs_marker(reopened),
        "an active project never needs the step"
    );
    assert_eq!(
        member_ids(&set, "a-old").len(),
        0,
        "nothing can be restored from before"
    );
}
