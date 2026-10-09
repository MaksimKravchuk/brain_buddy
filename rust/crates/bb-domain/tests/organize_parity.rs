//! Parity of the organization rules (project, tag and task-tag commands) with
//! the server, the Swift reducer and the frozen oracle (tasks.md T008, PR-08).
//!
//! The runner compiles the **actual** rule source with a plain `#[path]` module
//! and re-exports the shared crates at the test-crate root, so the rule's own
//! `crate::types` / `crate::normalization` paths resolve exactly as they do in
//! the library (tasks.md, "Dependencies"). Every data-driven test counts the
//! cases it executed, so an empty or truncated section fails instead of
//! passing vacuously.

#[path = "../src/organize.rs"]
mod organize;
mod support;

pub use bb_domain::{calendar, normalization, types};

use bb_protocol::command::{Decoded, decode_command};
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::sync::OnceLock;
use support::{cases, text};
use types::{
    ChangeOutcome, ChangeSet, Command, CommandType, Counter, DomainChange, DomainCommand,
    DomainError, EntityType, ExecutionInputs, Project, ProjectId, ProjectState, ReadSet, Reason,
    Record, Tag, TagChanges, TagId, TagState, Task, TaskId, TaskState,
};

/// The spec 021 golden traces; the shared loader does not list them.
fn project_archive_traces() -> &'static Value {
    static CELL: OnceLock<Value> = OnceLock::new();
    CELL.get_or_init(|| {
        let path = support::repo_root().join("backend/tests/fixtures/project_archive_traces.json");
        let text = std::fs::read_to_string(&path)
            .unwrap_or_else(|e| panic!("cannot read {}: {e}", path.display()));
        serde_json::from_str(&text)
            .unwrap_or_else(|e| panic!("invalid JSON in {}: {e}", path.display()))
    })
}

const NOW: &str = "2026-10-09T12:00:00Z";
const LATER: &str = "2026-10-09T13:30:00Z";

// ----------------------------------------------------------------------- harness

fn inputs_at(now: &str) -> ExecutionInputs {
    serde_json::from_value(json!({
        "rule_version": 1,
        "now": now,
        "time_zone": "UTC",
        "origin": "device",
        "actor_id": "actor-example",
        "authoritative": true,
        "allocated_ids": [],
        "policy": {
            "weekly_review": true,
            "navigator_provider": null,
            "navigator_available": false,
            "consent_text_version": 1
        }
    }))
    .expect("execution inputs")
}

/// An edit-revision precondition on one entity.
fn check(entity_type: &str, id: &str, revision: u64) -> Value {
    json!({ "entity_type": entity_type, "entity_id": id, "edit_revision": revision.to_string() })
}

fn envelope_json(kind: &str, entity: &str, payload: Value, checks: Vec<Value>) -> String {
    json!({
        "protocol_version": 1,
        "command_id": "01900000-0000-4000-8000-000000000001",
        "scope_id": "scope-example",
        "device_id": "device-example",
        "device_epoch": "epoch-example",
        "local_sequence": "7",
        "type": kind,
        "command_version": 1,
        "entity_id": entity,
        "preconditions": checks,
        "depends_on": [],
        "issued_at": NOW,
        "payload": payload
    })
    .to_string()
}

fn try_command(
    kind: &str,
    entity: &str,
    payload: Value,
    checks: Vec<Value>,
) -> Result<DomainCommand, DomainError> {
    match decode_command(&envelope_json(kind, entity, payload, checks)) {
        Ok(Decoded::Executable(envelope)) => DomainCommand::from_envelope(&envelope, |_| None),
        other => panic!("{kind} did not decode as an executable command: {other:?}"),
    }
}

fn command(kind: &str, entity: &str, payload: Value, checks: Vec<Value>) -> DomainCommand {
    try_command(kind, entity, payload, checks).unwrap_or_else(|e| panic!("{kind}: {e}"))
}

fn project_json(id: &str, name: &str, state: &str, revision: u64) -> Value {
    let archived = state == "archived";
    json!({
        "id": id, "name": name, "color": null, "state": state,
        "revision": revision.to_string(), "desired_outcome": null,
        "archived_at": if archived { json!("2026-09-01T09:00:00Z") } else { Value::Null },
        "archived_before_lossless": false
    })
}

fn tag_json(id: &str, name: &str, state: &str, revision: u64) -> Value {
    json!({ "id": id, "name": name, "state": state, "revision": revision.to_string() })
}

fn task_json(id: &str, state: &str, project: Option<&str>, tags: &[&str], revision: u64) -> Value {
    json!({
        "id": id, "title": format!("Task {id}"), "details": null, "state": state,
        "project_id": project, "tag_ids": tags, "due_date": null, "priority": "none",
        "waiting_for": null, "waiting_since": null, "order_key": "3",
        "source_capture_ids": [], "created_at": "2026-09-01T09:00:00Z",
        "updated_at": "2026-09-02T09:00:00Z", "completed_at": null, "cancelled_at": null,
        "revision": revision.to_string(), "consecutive_stalled_formulations": 0,
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

/// The protected read set of one scope plus the way a change set lands in it.
#[derive(Clone, Default)]
struct Store {
    read_set: ReadSet,
}

impl Store {
    fn new(projects: &[Value], tags: &[Value], tasks: &[Value]) -> Self {
        let read_set = serde_json::from_value(json!({
            "projects": keyed(projects), "tags": keyed(tags), "tasks": keyed(tasks)
        }))
        .unwrap_or_else(|e| panic!("read set: {e}"));
        Self { read_set }
    }

    fn decide(&self, command: &DomainCommand) -> Result<ChangeSet, DomainError> {
        organize::decide(&self.read_set, command, &inputs_at(NOW))
    }

    fn decide_at(&self, command: &DomainCommand, now: &str) -> Result<ChangeSet, DomainError> {
        organize::decide(&self.read_set, command, &inputs_at(now))
    }

    /// Decides and, when accepted, lands the changes in application order.
    fn run(&mut self, command: &DomainCommand) -> Result<ChangeSet, DomainError> {
        let set = self.decide(command)?;
        for change in &set.changes {
            match change {
                DomainChange::Upsert(Record::Project(p)) => {
                    self.read_set.projects.insert(p.id.clone(), p.clone());
                }
                DomainChange::Upsert(Record::Tag(t)) => {
                    self.read_set.tags.insert(t.id.clone(), t.clone());
                }
                DomainChange::Upsert(Record::Task(t)) => {
                    self.read_set.tasks.insert(t.id.clone(), t.clone());
                }
                other => panic!("an organization command changed {other:?}"),
            }
        }
        Ok(set)
    }

    fn project(&self, id: &str) -> &Project {
        &self.read_set.projects[&ProjectId::parse(id).expect("project id")]
    }

    fn tag(&self, id: &str) -> &Tag {
        &self.read_set.tags[&TagId::parse(id).expect("tag id")]
    }

    fn task(&self, id: &str) -> &Task {
        &self.read_set.tasks[&TaskId::parse(id).expect("task id")]
    }

    fn project_named(&self, name: &str) -> &Project {
        self.read_set
            .projects
            .values()
            .find(|p| p.name.as_str() == name)
            .unwrap_or_else(|| panic!("no project {name:?}"))
    }

    fn tag_named(&self, name: &str) -> &Tag {
        self.read_set
            .tags
            .values()
            .find(|t| t.name.as_str() == name)
            .unwrap_or_else(|| panic!("no tag {name:?}"))
    }
}

fn refusal(result: Result<ChangeSet, DomainError>) -> DomainError {
    match result {
        Err(error) => error,
        Ok(set) => panic!("expected a refusal, got {set:?}"),
    }
}

fn accepted(result: Result<ChangeSet, DomainError>) -> ChangeSet {
    result.unwrap_or_else(|e| panic!("expected acceptance, got {e:?}"))
}

fn the_project(set: &ChangeSet) -> &Project {
    match set.changes.as_slice() {
        [DomainChange::Upsert(Record::Project(project))] => project,
        other => panic!("expected exactly one project change, got {other:?}"),
    }
}

fn the_tag(set: &ChangeSet) -> &Tag {
    match set.changes.as_slice() {
        [DomainChange::Upsert(Record::Tag(tag))] => tag,
        other => panic!("expected exactly one tag change, got {other:?}"),
    }
}

fn the_task(set: &ChangeSet) -> &Task {
    match set.changes.as_slice() {
        [DomainChange::Upsert(Record::Task(task))] => task,
        other => panic!("expected exactly one task change, got {other:?}"),
    }
}

fn tag_ids(task: &Task) -> Vec<&str> {
    task.tag_ids.iter().map(TagId::as_str).collect()
}

fn ran_all(section: &str, ran: usize, expected: usize) {
    assert!(ran > 0, "{section}: no case executed");
    assert_eq!(
        ran, expected,
        "{section}: executed cases differ from the file"
    );
}

fn project_create(id: &str, name: &str) -> DomainCommand {
    command("project.create", id, json!({ "name": name }), vec![])
}

fn tag_create(id: &str, name: &str) -> DomainCommand {
    command("tag.create", id, json!({ "name": name }), vec![])
}

fn project_edit(kind: &str, id: &str, payload: Value, revision: u64) -> DomainCommand {
    command(kind, id, payload, vec![check("project", id, revision)])
}

fn tag_edit(kind: &str, id: &str, payload: Value, revision: u64) -> DomainCommand {
    command(kind, id, payload, vec![check("tag", id, revision)])
}

fn task_tags(id: &str, add: &[&str], remove: &[&str], revision: u64) -> DomainCommand {
    command(
        "task.tags",
        id,
        json!({ "add_tag_ids": add, "remove_tag_ids": remove }),
        vec![check("task", id, revision)],
    )
}

/// Work and Other are active projects, Old is archived; Home and Calls are
/// active tags, Gone is deleted. `open` and `done` carry Home.
fn world() -> Store {
    Store::new(
        &[
            project_json("work", "Work", "active", 1),
            project_json("other", "Other", "active", 4),
            project_json("old", "Old", "archived", 3),
        ],
        &[
            tag_json("home", "Home", "active", 1),
            tag_json("calls", "Calls", "active", 2),
            tag_json("gone", "Gone", "deleted", 2),
        ],
        &[
            task_json("open", "next", Some("work"), &["home", "calls"], 5),
            task_json("done", "completed", Some("work"), &["home"], 2),
            task_json("cut", "cancelled", Some("old"), &[], 2),
            task_json("loose", "inbox", None, &[], 1),
        ],
    )
}

// ---------------------------------------------------------------- 026-FR-002: projects

#[test]
fn organize_026_fr_002_a_new_project_stores_the_servers_display_form() {
    let store = world();
    let set = accepted(store.decide(&command(
        "project.create",
        "project_new",
        json!({ "name": "  Ｄｅｅｐ   work ", "color": "#123456", "desired_outcome": "  Ship it \n" }),
        vec![],
    )));
    let project = the_project(&set);
    assert_eq!(project.id.as_str(), "project_new");
    assert_eq!(project.name.as_str(), "Deep work");
    assert_eq!(project.color.as_ref().map(|c| c.as_str()), Some("#123456"));
    assert_eq!(
        project.desired_outcome.as_ref().map(|o| o.as_str()),
        Some("Ship it")
    );
    assert_eq!(project.state, ProjectState::Active);
    assert_eq!(project.revision, Counter::from(1));
    assert!(project.archived_at.is_none() && !project.archived_before_lossless);
    assert_eq!(set.outcome, ChangeOutcome::Applied);
    assert!(set.effects.is_empty() && set.result.created_task_id.is_none());
    assert_eq!(
        set.affected_keys(),
        vec![(EntityType::Project, vec!["project_new".to_owned()])]
    );
}

#[test]
fn organize_026_fr_002_blank_outcomes_are_none_and_the_limit_is_one_thousand_scalars() {
    let store = world();
    let blank = accepted(store.decide(&command(
        "project.create",
        "project_b",
        json!({ "name": "B", "desired_outcome": " \n " }),
        vec![],
    )));
    assert!(the_project(&blank).desired_outcome.is_none());
    let longest = "o".repeat(1_000);
    let kept = accepted(store.decide(&command(
        "project.create",
        "project_c",
        json!({ "name": "C", "desired_outcome": longest }),
        vec![],
    )));
    assert_eq!(
        the_project(&kept)
            .desired_outcome
            .as_ref()
            .map(|o| o.as_str().chars().count()),
        Some(1_000)
    );
    // The type refuses a 1,001 scalar outcome before the rule runs (422 on the server).
    let err = try_command(
        "project.create",
        "project_d",
        json!({ "name": "D", "desired_outcome": "o".repeat(1_001) }),
        vec![],
    )
    .unwrap_err();
    assert_eq!(err.reason, Reason::InvalidPayload);
}

#[test]
fn organize_026_fr_002_project_names_are_unique_among_active_projects_by_normalized_key() {
    let mut store = world();
    // NFKC, collapsing and full case folding: the names the server treats as one.
    for clash in [" WORK ", "ｗｏｒｋ", "W\u{FF2F}RK", "work\u{3000}"] {
        let err = refusal(store.decide(&project_create("project_x", clash)));
        assert_eq!(err.reason, Reason::DuplicateProjectName, "{clash:?}");
        assert_eq!(
            err.entity,
            Some((EntityType::Project, vec!["work".to_owned()]))
        );
        assert_eq!(err.field.as_deref(), Some("name"));
    }
    // An archived project's name is free again.
    accepted(store.run(&project_create("project_old2", "old")));
    assert_eq!(store.project("project_old2").name.as_str(), "old");
    // Full case folding: ß matches SS.
    accepted(store.run(&project_create("project_s", "Straße")));
    let err = refusal(store.decide(&project_create("project_t", "STRASSE")));
    assert_eq!(err.reason, Reason::DuplicateProjectName);
    // A project key keeps the leading @ (only tags drop it).
    accepted(store.decide(&project_create("project_at", "@Work")));
}

#[test]
fn organize_026_fr_002_blank_and_expanding_names_are_refused_with_typed_reasons() {
    let store = world();
    for blank in ["   ", " \n "] {
        let err = refusal(store.decide(&project_create("project_x", blank)));
        assert_eq!(err.reason, Reason::EmptyName, "{blank:?}");
    }
    // 300 compatibility characters become 600 after NFKC: the stored document
    // would be refused, so the core refuses it too.
    let err = refusal(store.decide(&project_create("project_x", &"㎏".repeat(300))));
    assert_eq!(err.reason, Reason::TextLength);
    // The request types refuse 501 scalars, an empty name and a 65 scalar colour first.
    for payload in [
        json!({ "name": "n".repeat(501) }),
        json!({ "name": "" }),
        json!({ "name": "P", "color": "c".repeat(65) }),
        json!({ "name": "P", "unknown": 1 }),
    ] {
        let err = try_command("project.create", "project_x", payload, vec![]).unwrap_err();
        assert_eq!(err.reason, Reason::InvalidPayload);
    }
}

#[test]
fn organize_026_fr_008_an_id_that_exists_is_never_created_again() {
    let store = world();
    for existing in ["work", "old"] {
        let err = refusal(store.decide(&project_create(existing, "Brand new")));
        assert_eq!(err.reason, Reason::IdAlreadyExists, "{existing}");
    }
    // A deleted tag keeps its ID: it cannot be recreated under a new name.
    let err = refusal(store.decide(&tag_create("gone", "Reborn")));
    assert_eq!(err.reason, Reason::IdAlreadyExists);
    assert_eq!(err.field.as_deref(), Some("entity_id"));
}

#[test]
fn organize_026_fr_002_update_renames_recolours_and_edits_the_outcome_under_the_revision() {
    let mut store = world();
    let set = accepted(store.run(&project_edit(
        "project.update",
        "work",
        json!({ "name": "WORK", "color": "#00FF00" }),
        1,
    )));
    let project = the_project(&set);
    assert_eq!(project.name.as_str(), "WORK");
    assert_eq!(project.color.as_ref().map(|c| c.as_str()), Some("#00FF00"));
    assert_eq!(project.revision, Counter::from(2));
    // omitted keeps, null clears (021-FR-028 and the Swift update case)
    accepted(store.run(&project_edit(
        "project.update",
        "work",
        json!({ "desired_outcome": "Ship" }),
        2,
    )));
    accepted(store.run(&project_edit(
        "project.update",
        "work",
        json!({ "color": null }),
        3,
    )));
    let work = store.project("work");
    assert!(work.color.is_none());
    assert_eq!(work.name.as_str(), "WORK");
    assert_eq!(
        work.desired_outcome.as_ref().map(|o| o.as_str()),
        Some("Ship")
    );
    accepted(store.run(&project_edit(
        "project.update",
        "work",
        json!({ "desired_outcome": "   " }),
        4,
    )));
    assert!(store.project("work").desired_outcome.is_none());
    assert_eq!(store.project("work").revision, Counter::from(5));
}

#[test]
fn organize_026_fr_002_update_with_nothing_to_change_still_bumps_the_revision() {
    // Server: PATCH always writes (revision + 1). Swift refuses `nothingToChange`
    // to the user; the shared rule follows the server.
    let mut store = world();
    for (revision, payload) in [(1, json!({})), (2, json!({ "name": " Work " }))] {
        let set = accepted(store.run(&project_edit("project.update", "work", payload, revision)));
        assert_eq!(the_project(&set).revision, Counter::from(revision + 1));
        assert_eq!(the_project(&set).name.as_str(), "Work");
    }
}

#[test]
fn organize_026_fr_002_renaming_checks_uniqueness_only_while_the_project_is_active() {
    let mut store = world();
    let err = refusal(store.decide(&project_edit(
        "project.update",
        "work",
        json!({ "name": "other" }),
        1,
    )));
    assert_eq!(err.reason, Reason::DuplicateProjectName);
    assert_eq!(
        err.entity,
        Some((EntityType::Project, vec!["other".to_owned()]))
    );
    // A case-only rename of itself is fine.
    accepted(store.decide(&project_edit(
        "project.update",
        "work",
        json!({ "name": "wORK" }),
        1,
    )));
    // An archived project can take any name, including an active one's (server rule).
    let set = accepted(store.run(&project_edit(
        "project.update",
        "old",
        json!({ "name": "Work" }),
        3,
    )));
    assert_eq!(the_project(&set).state, ProjectState::Archived);
    // The collision surfaces when it is unarchived.
    let err = refusal(store.decide(&project_edit("project.unarchive", "old", json!({}), 4)));
    assert_eq!(err.reason, Reason::UnarchiveNameInUse);
}

#[test]
fn organize_026_fr_002_a_blank_rename_is_refused_not_stored() {
    // The server's model_copy stores a blank name unvalidated and then cannot
    // load it; the core refuses (as the Swift reducer does).
    let store = world();
    let err = refusal(store.decide(&project_edit(
        "project.update",
        "work",
        json!({ "name": " " }),
        1,
    )));
    assert_eq!(err.reason, Reason::EmptyName);
    let err = try_command(
        "project.update",
        "work",
        json!({ "name": null }),
        vec![check("project", "work", 1)],
    )
    .unwrap_err();
    assert_eq!(
        err.reason,
        Reason::InvalidPayload,
        "a name cannot be cleared"
    );
}

#[test]
fn organize_026_fr_007_a_stale_or_missing_revision_check_changes_nothing() {
    let store = world();
    for command in [
        project_edit("project.update", "other", json!({ "name": "X" }), 3),
        project_edit("project.archive", "other", json!({}), 5),
        tag_edit("tag.update", "calls", json!({ "name": "X" }), 1),
        tag_edit("tag.delete", "calls", json!({}), 3),
        task_tags("open", &["calls"], &[], 4),
    ] {
        let err = refusal(store.decide(&command));
        assert_eq!(
            err.reason,
            Reason::RevisionConflict,
            "{:?}",
            command.command_type()
        );
        assert!(err.current_revision.is_some());
        assert!(err.entity.is_some());
    }
    let stale = refusal(store.decide(&project_edit("project.archive", "other", json!({}), 1)));
    assert_eq!(stale.current_revision, Some(Counter::from(4)));
    assert_eq!(
        stale.entity,
        Some((EntityType::Project, vec!["other".to_owned()]))
    );
    // A command without a check on its own target is malformed, not stale; a
    // check on another entity does not count.
    for checks in [
        vec![],
        vec![check("project", "work", 4)],
        vec![check("tag", "other", 4)],
    ] {
        let err = refusal(store.decide(&command("project.archive", "other", json!({}), checks)));
        assert_eq!(err.reason, Reason::InvalidPayload);
        assert_eq!(err.field.as_deref(), Some("preconditions"));
    }
}

// ------------------------------------------------------- 026-FR-002: archive and back

#[test]
fn organize_026_fr_009_archiving_keeps_every_task_exactly_as_it_is() {
    let mut store = world();
    let before = store.read_set.tasks.clone();
    let set = accepted(store.run(&project_edit("project.archive", "work", json!({}), 1)));
    let project = the_project(&set);
    assert_eq!(project.state, ProjectState::Archived);
    assert_eq!(project.revision, Counter::from(2));
    assert_eq!(project.archived_at.as_ref().map(|i| i.as_str()), Some(NOW));
    assert!(!project.archived_before_lossless);
    assert_eq!(set.changes.len(), 1, "no task is touched");
    assert_eq!(
        store.read_set.tasks, before,
        "memberships, order, state and revision stay"
    );
}

#[test]
fn organize_026_fr_002_a_repeat_archive_only_bumps_the_revision() {
    // 021-FR-027: archived_at and the pre-feature marker are never rewritten.
    for (archived_at, marker) in [(None, true), (Some("2026-09-01T09:00:00Z"), false)] {
        let mut project = project_json("old", "Old", "archived", 3);
        project["archived_at"] = json!(archived_at);
        project["archived_before_lossless"] = json!(marker);
        let store = Store::new(&[project], &[], &[]);
        let set =
            accepted(store.decide_at(&project_edit("project.archive", "old", json!({}), 3), LATER));
        let repeat = the_project(&set);
        assert_eq!(repeat.revision, Counter::from(4));
        assert_eq!(repeat.archived_at.as_ref().map(|i| i.as_str()), archived_at);
        assert_eq!(repeat.archived_before_lossless, marker);
        assert_eq!(repeat.state, ProjectState::Archived);
    }
}

#[test]
fn organize_026_fr_002_unarchiving_reopens_and_keeps_the_marker() {
    let mut project = project_json("old", "Old", "archived", 3);
    project["archived_before_lossless"] = json!(true);
    project["archived_at"] = Value::Null;
    let mut store = Store::new(
        &[project],
        &[],
        &[task_json("t", "next", Some("old"), &[], 1)],
    );
    let before = store.read_set.tasks.clone();
    let set = accepted(store.run(&project_edit("project.unarchive", "old", json!({}), 3)));
    let reopened = the_project(&set);
    assert_eq!(reopened.state, ProjectState::Active);
    assert!(reopened.archived_at.is_none());
    assert!(
        reopened.archived_before_lossless,
        "the marker survives unarchive"
    );
    assert_eq!(reopened.revision, Counter::from(4));
    assert_eq!(store.read_set.tasks, before);
    // Archiving the marked, reopened project is lossless this time and clears it.
    let again = accepted(store.run(&project_edit("project.archive", "old", json!({}), 4)));
    assert!(!the_project(&again).archived_before_lossless);
    assert_eq!(
        the_project(&again).archived_at.as_ref().map(|i| i.as_str()),
        Some(NOW)
    );
}

#[test]
fn organize_026_fr_002_unarchiving_an_active_project_is_an_accepted_no_op_even_when_stale() {
    // Server (http section 3): answered before the revision is looked at.
    // The Swift reducer throws `nothingToChange` to the user.
    let store = world();
    for revision in [1, 99] {
        let set = accepted(store.decide(&project_edit(
            "project.unarchive",
            "work",
            json!({}),
            revision,
        )));
        assert_eq!(set, ChangeSet::no_op());
    }
    let missing = command("project.unarchive", "work", json!({}), vec![]);
    assert_eq!(accepted(store.decide(&missing)), ChangeSet::no_op());
}

#[test]
fn organize_026_fr_002_unarchive_needs_a_free_active_name_and_a_current_revision() {
    let mut store = world();
    let err = refusal(store.decide(&project_edit("project.unarchive", "old", json!({}), 1)));
    assert_eq!(err.reason, Reason::RevisionConflict);
    accepted(store.run(&project_create("project_again", "OLD")));
    for _ in 0..2 {
        let err = refusal(store.decide(&project_edit("project.unarchive", "old", json!({}), 3)));
        assert_eq!(err.reason, Reason::UnarchiveNameInUse);
        assert_eq!(
            err.entity,
            Some((EntityType::Project, vec!["project_again".to_owned()]))
        );
    }
    // Archived namesakes do not count.
    accepted(store.run(&project_edit(
        "project.archive",
        "project_again",
        json!({}),
        1,
    )));
    let set = accepted(store.run(&project_edit("project.unarchive", "old", json!({}), 3)));
    assert_eq!(the_project(&set).state, ProjectState::Active);
}

#[test]
fn organize_026_fr_008_late_edits_never_recreate_a_missing_record() {
    let store = world();
    for command in [
        project_edit("project.update", "ghost", json!({ "name": "X" }), 1),
        project_edit("project.archive", "ghost", json!({}), 1),
        project_edit("project.unarchive", "ghost", json!({}), 1),
        tag_edit("tag.update", "ghost", json!({ "name": "X" }), 1),
        tag_edit("tag.delete", "ghost", json!({}), 1),
        task_tags("ghost", &["home"], &[], 1),
    ] {
        let err = refusal(store.decide(&command));
        assert_eq!(err.reason, Reason::NotFound, "{:?}", command.command_type());
        assert!(err.entity.is_some());
    }
}

// ----------------------------------------------------------------------------- tags

#[test]
fn organize_026_fr_002_a_new_tag_drops_one_leading_at_and_is_unique_among_active_tags() {
    let mut store = world();
    let set = accepted(store.run(&tag_create("tag_o", " @Office  hours ")));
    let tag = the_tag(&set);
    assert_eq!(tag.name.as_str(), "Office hours");
    assert_eq!(
        (tag.state, tag.revision.clone()),
        (TagState::Active, Counter::from(1))
    );
    let err = refusal(store.decide(&tag_create("tag_x", "@HOME")));
    assert_eq!(err.reason, Reason::DuplicateTagName);
    assert_eq!(err.entity, Some((EntityType::Tag, vec!["home".to_owned()])));
    assert_eq!(
        refusal(store.decide(&tag_create("tag_x", "@"))).reason,
        Reason::EmptyName
    );
    assert_eq!(
        refusal(store.decide(&tag_create("home", "Other"))).reason,
        Reason::IdAlreadyExists
    );
    // A deleted tag's name is free again.
    accepted(store.run(&tag_create("tag_g", "Gone")));
    assert_eq!(store.tag("tag_g").state, TagState::Active);
    // "@@x" is stored as "@x" and keyed as "x" (the server strips the prefix again).
    accepted(store.run(&tag_create("tag_at", "@@errands")));
    assert_eq!(store.tag("tag_at").name.as_str(), "@errands");
    assert_eq!(
        refusal(store.decide(&tag_create("tag_y", "errands"))).reason,
        Reason::DuplicateTagName
    );
}

#[test]
fn organize_026_fr_002_renaming_a_tag_keeps_uniqueness_among_active_tags() {
    let mut store = world();
    accepted(store.run(&tag_edit(
        "tag.update",
        "calls",
        json!({ "name": "@Phone" }),
        2,
    )));
    assert_eq!(store.tag("calls").name.as_str(), "Phone");
    accepted(store.run(&tag_edit(
        "tag.update",
        "home",
        json!({ "name": "HOME" }),
        1,
    )));
    assert_eq!(store.tag("home").name.as_str(), "HOME");
    let err = refusal(store.decide(&tag_edit(
        "tag.update",
        "calls",
        json!({ "name": "home" }),
        3,
    )));
    assert_eq!(err.reason, Reason::DuplicateTagName);
    assert_eq!(err.entity, Some((EntityType::Tag, vec!["home".to_owned()])));
    // A rename to the same text still bumps the revision (server: PATCH always writes).
    let same = accepted(store.decide(&tag_edit(
        "tag.update",
        "calls",
        json!({ "name": "Phone" }),
        3,
    )));
    assert_eq!(the_tag(&same).revision, Counter::from(4));
    assert_eq!(
        refusal(store.decide(&tag_edit("tag.update", "calls", json!({ "name": "@" }), 3))).reason,
        Reason::EmptyName
    );
}

#[test]
fn organize_026_fr_008_a_deleted_tag_can_be_renamed_but_is_never_reactivated() {
    let mut store = world();
    let set = accepted(store.run(&tag_edit(
        "tag.update",
        "gone",
        json!({ "name": "home" }),
        2,
    )));
    assert_eq!(
        the_tag(&set).state,
        TagState::Deleted,
        "an edit does not resurrect"
    );
    assert_eq!(store.tag("gone").name.as_str(), "home");
    // A late task edit cannot attach it, nor can anything add it.
    let err = refusal(store.decide(&task_tags("loose", &["gone"], &[], 1)));
    assert_eq!(err.reason, Reason::TagNotActive);
    assert_eq!(err.entity, Some((EntityType::Tag, vec!["gone".to_owned()])));
    assert_eq!(
        refusal(store.decide(&task_tags("loose", &["nope"], &[], 1))).reason,
        Reason::NotFound
    );
}

#[test]
fn organize_026_fr_008_deleting_a_tag_keeps_the_record_and_unlinks_every_task() {
    let mut store = world();
    let set = accepted(store.run(&tag_edit("tag.delete", "home", json!({}), 1)));
    assert_eq!(set.outcome, ChangeOutcome::Applied);
    let kinds: Vec<EntityType> = set.changes.iter().map(DomainChange::entity_type).collect();
    assert_eq!(kinds, [EntityType::Tag, EntityType::Task, EntityType::Task]);
    let tag = store.tag("home");
    assert_eq!(
        (tag.state, tag.revision.clone()),
        (TagState::Deleted, Counter::from(2))
    );
    assert!(
        set.changes
            .iter()
            .all(|change| !matches!(change, DomainChange::Tombstone { .. })),
        "the tag stays as a deleted record"
    );
    // Every task that held it, in any state, loses it, and only that.
    for (id, revision, tags) in [("open", 6, vec!["calls"]), ("done", 3, vec![])] {
        let task = store.task(id);
        assert_eq!(tag_ids(task), tags, "{id}");
        assert_eq!(task.revision, Counter::from(revision), "{id}");
        assert_eq!(task.updated_at.as_str(), NOW, "{id}");
    }
    for id in ["cut", "loose"] {
        assert_eq!(store.task(id), world().task(id), "{id} is untouched");
    }
    assert!(
        store
            .read_set
            .tasks
            .values()
            .all(|t| !t.tag_ids.contains(&TagId::parse("home").unwrap()))
    );
}

#[test]
fn organize_026_fr_009_tag_deletion_does_not_reorder_or_move_anything() {
    let original = world();
    let mut store = world();
    accepted(store.run(&tag_edit("tag.delete", "home", json!({}), 1)));
    for (id, task) in &original.read_set.tasks {
        let after = &store.read_set.tasks[id];
        let restored = Task {
            tag_ids: task.tag_ids.clone(),
            updated_at: task.updated_at.clone(),
            revision: task.revision.clone(),
            ..after.clone()
        };
        assert_eq!(
            &restored, task,
            "only tags, updated_at and revision may change"
        );
        assert_eq!(after.state, task.state);
        assert_eq!(after.order_key, task.order_key);
        assert_eq!(after.project_id, task.project_id);
    }
    assert_eq!(store.task("open").state, TaskState::Next);
}

#[test]
fn organize_026_fr_002_a_repeat_tag_delete_is_accepted_and_only_bumps_the_revision() {
    // Server: delete_tag has no already-deleted check. Swift answers
    // `tagAlreadyDeleted` to the user.
    let mut store = world();
    let set = accepted(store.run(&tag_edit("tag.delete", "gone", json!({}), 2)));
    assert_eq!(the_tag(&set).state, TagState::Deleted);
    assert_eq!(the_tag(&set).revision, Counter::from(3));
    assert_eq!(set.changes.len(), 1);
}

// --------------------------------------------------------------- task tag membership

#[test]
fn organize_026_fr_002_explicit_tag_changes_add_active_tags_and_remove_the_named_ones() {
    let mut store = world();
    accepted(store.run(&tag_create("tag_new", "Errands")));
    let set = accepted(store.run(&task_tags("open", &["tag_new"], &["home"], 5)));
    let task = the_task(&set);
    assert_eq!(
        tag_ids(task),
        ["calls", "tag_new"],
        "order kept, additions follow"
    );
    assert_eq!(task.revision, Counter::from(6));
    assert_eq!(task.updated_at.as_str(), NOW);
    assert_eq!(task.state, TaskState::Next);
    assert_eq!(task.formulation, store.task("open").formulation);
}

#[test]
fn organize_026_fr_002_tag_changes_are_idempotent_per_tag_and_always_one_task_update() {
    let mut store = world();
    // An addition the task holds and a removal it does not are moot; the edit
    // is still one task update and bumps the revision, like a legacy PATCH.
    let set = accepted(store.run(&task_tags("open", &["home"], &["gone"], 5)));
    assert_eq!(tag_ids(the_task(&set)), ["home", "calls"]);
    assert_eq!(the_task(&set).revision, Counter::from(6));
    let empty = accepted(store.run(&task_tags("open", &[], &[], 6)));
    assert_eq!(the_task(&empty).revision, Counter::from(7));
    // A held membership is not re-validated; removing a deleted tag is allowed.
    let mut stale = world();
    stale.read_set.tasks.insert(
        TaskId::parse("legacy").unwrap(),
        serde_json::from_value(task_json("legacy", "inbox", None, &["gone"], 1)).unwrap(),
    );
    let cleaned = accepted(stale.run(&task_tags("legacy", &[], &["gone"], 1)));
    assert!(the_task(&cleaned).tag_ids.is_empty());
}

#[test]
fn organize_026_fr_002_a_refused_membership_edit_changes_nothing() {
    let store = world();
    let before = store.read_set.clone();
    let err = refusal(store.decide(&task_tags("loose", &["calls", "gone"], &[], 1)));
    assert_eq!(
        (err.reason, err.field.as_deref()),
        (Reason::TagNotActive, Some("tag_ids"))
    );
    assert_eq!(
        refusal(store.decide(&task_tags("loose", &["calls", "ghost"], &[], 1))).reason,
        Reason::NotFound
    );
    assert_eq!(
        refusal(store.decide(&task_tags("loose", &["calls"], &[], 2))).reason,
        Reason::RevisionConflict
    );
    // Duplicates and overlap are refused where the envelope is decoded, where
    // the command is typed, and again by the rule for a hand-built command.
    for payload in [
        json!({ "add_tag_ids": ["calls", "calls"] }),
        json!({ "add_tag_ids": ["calls"], "remove_tag_ids": ["calls"] }),
    ] {
        let wire = envelope_json(
            "task.tags",
            "loose",
            payload.clone(),
            vec![check("task", "loose", 1)],
        );
        assert!(decode_command(&wire).is_err(), "{payload}");
        let typed = Command::from_payload(CommandType::TaskTags, payload.as_object().unwrap())
            .and_then(|c| c.check_shape().map(|()| c));
        assert_eq!(typed.unwrap_err().reason, Reason::TagChangesOverlap);
        let changes: TagChanges = serde_json::from_value(payload).unwrap();
        let err = organize::apply_tag_changes(&store.read_set, &[], &changes).unwrap_err();
        assert_eq!(err.reason, Reason::TagChangesOverlap);
    }
    assert_eq!(store.read_set, before);
}

// -------------------------------------------------------------------- references

#[test]
fn organize_026_fr_008_references_follow_the_task_service_order_and_carry_archived_memberships() {
    let store = world();
    let (work, old, other) = (
        ProjectId::parse("work").unwrap(),
        ProjectId::parse("old").unwrap(),
        ProjectId::parse("other").unwrap(),
    );
    let tags = |ids: &[&str]| {
        ids.iter()
            .map(|id| TagId::parse(*id).unwrap())
            .collect::<Vec<_>>()
    };
    let verify =
        |project: Option<&ProjectId>, ids: Option<&[TagId]>, current: Option<&ProjectId>| {
            organize::check_references(&store.read_set, project, ids, current)
        };
    let reason = |result: Result<(), DomainError>| result.unwrap_err().reason;
    assert!(verify(Some(&work), Some(&tags(&["home", "calls"])), None).is_ok());
    assert!(verify(None, None, None).is_ok());
    // ADR-0020: an archived project is refused, unless the task is already in it.
    assert_eq!(
        reason(verify(Some(&old), None, None)),
        Reason::ProjectNotActive
    );
    assert_eq!(
        reason(verify(Some(&old), None, Some(&other))),
        Reason::ProjectNotActive
    );
    assert!(verify(Some(&old), None, Some(&old)).is_ok());
    let ghost = ProjectId::parse("ghost").unwrap();
    assert_eq!(reason(verify(Some(&ghost), None, None)), Reason::NotFound);
    // Project first, then tag duplicates, then each tag in order.
    let dup = tags(&["gone", "home", "home"]);
    assert_eq!(
        reason(verify(Some(&old), Some(&dup), None)),
        Reason::ProjectNotActive
    );
    assert_eq!(reason(verify(None, Some(&dup), None)), Reason::DuplicateTag);
    let inactive_first = tags(&["home", "gone", "ghost"]);
    assert_eq!(
        reason(verify(None, Some(&inactive_first), None)),
        Reason::TagNotActive
    );
    let missing_first = tags(&["ghost", "gone"]);
    assert_eq!(
        reason(verify(None, Some(&missing_first), None)),
        Reason::NotFound
    );
}

// ----------------------------------------------------------------- determinism

#[test]
fn organize_026_fr_002_decide_is_pure_and_time_is_only_an_input() {
    let store = world();
    let before = store.read_set.clone();
    for command in [
        project_edit("project.archive", "work", json!({}), 1),
        tag_edit("tag.delete", "home", json!({}), 1),
        task_tags("open", &[], &["home"], 5),
    ] {
        let first = accepted(store.decide(&command));
        assert_eq!(first, accepted(store.decide(&command)));
        let later = accepted(store.decide_at(&command, LATER));
        assert_ne!(first, later, "the instant reaches the records");
        assert_eq!(first.changes.len(), later.changes.len());
        assert_eq!(store.read_set, before, "the read set is never mutated");
    }
}

#[test]
fn organize_026_fr_002_only_organization_commands_are_decided_here() {
    let store = world();
    let ours = [
        command(
            "project.create",
            "project_n",
            json!({ "name": "N" }),
            vec![],
        ),
        project_edit("project.archive", "work", json!({}), 1),
        task_tags("open", &[], &[], 5),
    ];
    assert!(ours.iter().all(|c| organize::handles(&c.command)));
    let foreign = command(
        "task.create",
        "task_n",
        json!({ "title": "Elsewhere" }),
        vec![],
    );
    assert!(!organize::handles(&foreign.command));
    let err = refusal(store.decide(&foreign));
    assert_eq!(
        (err.reason, err.field.as_deref()),
        (Reason::InvalidPayload, Some("type"))
    );
}

// ------------------------------------------- parity: name vectors (primitive-vectors)

#[test]
fn organize_026_fr_002_project_uniqueness_agrees_with_every_name_vector_pair() {
    let vectors = cases(support::primitives(), "name_normalization");
    let mut pairs = 0;
    for first in vectors {
        let shown = text(first, "project_display");
        let mut store = Store::default();
        if shown.is_empty() {
            let err = refusal(store.decide(&project_create("project_a", text(first, "input"))));
            assert_eq!(err.reason, Reason::EmptyName, "{}", text(first, "id"));
            pairs += vectors.len();
            continue;
        }
        let created = accepted(store.run(&project_create("project_a", text(first, "input"))));
        assert_eq!(
            the_project(&created).name.as_str(),
            shown,
            "{}",
            text(first, "id")
        );
        for second in vectors {
            pairs += 1;
            if text(second, "project_display").is_empty() {
                let err =
                    refusal(store.decide(&project_create("project_b", text(second, "input"))));
                assert_eq!(err.reason, Reason::EmptyName);
                continue;
            }
            let result = store.decide(&project_create("project_b", text(second, "input")));
            let same_key = text(first, "project_key") == text(second, "project_key");
            match (same_key, result) {
                (true, Err(e)) => assert_eq!(e.reason, Reason::DuplicateProjectName),
                (false, Ok(set)) => {
                    assert_eq!(
                        the_project(&set).name.as_str(),
                        text(second, "project_display")
                    );
                }
                (same, result) => panic!(
                    "{} vs {}: same key {same}, got {result:?}",
                    text(first, "id"),
                    text(second, "id")
                ),
            }
        }
    }
    ran_all("project name pairs", pairs, vectors.len() * vectors.len());
}

#[test]
fn organize_026_fr_002_tag_uniqueness_agrees_with_every_name_vector_pair() {
    let vectors = cases(support::primitives(), "name_normalization");
    // The key a stored tag collides on is the key of its stored display name.
    // It equals the vector's key except where the display keeps a second `@`
    // (NN-024: "@@home" is stored "@home" and keyed "home").
    let stored_key = |case: &Value| normalization::tag_key(text(case, "tag_display"));
    let double_prefix: Vec<&str> = vectors
        .iter()
        .filter(|v| stored_key(v) != text(v, "tag_key"))
        .map(|v| text(v, "id"))
        .collect();
    assert_eq!(double_prefix, ["NN-024"]);
    let mut pairs = 0;
    for first in vectors {
        let mut store = Store::default();
        if text(first, "tag_display").is_empty() {
            let err = refusal(store.decide(&tag_create("tag_a", text(first, "input"))));
            assert_eq!(err.reason, Reason::EmptyName, "{}", text(first, "id"));
            pairs += vectors.len();
            continue;
        }
        let created = accepted(store.run(&tag_create("tag_a", text(first, "input"))));
        assert_eq!(the_tag(&created).name.as_str(), text(first, "tag_display"));
        for second in vectors {
            pairs += 1;
            if text(second, "tag_display").is_empty() {
                let err = refusal(store.decide(&tag_create("tag_b", text(second, "input"))));
                assert_eq!(err.reason, Reason::EmptyName);
                continue;
            }
            let result = store.decide(&tag_create("tag_b", text(second, "input")));
            match (stored_key(first) == stored_key(second), result) {
                (true, Err(e)) => assert_eq!(e.reason, Reason::DuplicateTagName),
                (false, Ok(set)) => {
                    assert_eq!(the_tag(&set).name.as_str(), text(second, "tag_display"));
                }
                (same, result) => panic!(
                    "{} vs {}: same key {same}, got {result:?}",
                    text(first, "id"),
                    text(second, "id")
                ),
            }
        }
    }
    ran_all("tag name pairs", pairs, vectors.len() * vectors.len());
}

// ----------------------------------------- parity: frozen reference store (T002)

fn owner_store(owner: &str) -> Store {
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
    let tags: Vec<Value> = of_owner("tags")
        .iter()
        .map(|t| json!({ "id": t["id"], "name": t["name"], "state": t["state"], "revision": revision(t) }))
        .collect();
    let tasks: Vec<Value> = of_owner("tasks").iter().map(public_task).collect();
    Store::new(&projects, &tags, &tasks)
}

/// The oracle's storage row as the public task record.
fn public_task(row: &Value) -> Value {
    let clock = row["formulation_id"].as_str().map(|id| {
        json!({
            "id": id, "started_at": row["formulation_started_at"],
            "extended_at": row["formulation_extended_at"],
            "extension_reason": row["formulation_extension_reason"],
            "park_floor_at": row["formulation_park_floor_at"]
        })
    });
    let parked = row["parked"].as_object().map(|park| {
        json!({
            "at": park["at"], "formulation_id": park["formulation_id"],
            "private": {
                "from_revision": park["from_revision"].as_u64().expect("from_revision").to_string(),
                "clock_before": park["clock_before"]
            }
        })
    });
    json!({
        "id": row["id"], "title": row["title"], "details": row["details"], "state": row["state"],
        "project_id": row["project_id"], "tag_ids": row["tag_ids"], "due_date": row["due_date"],
        "priority": row["priority"], "waiting_for": row["waiting_for"],
        "waiting_since": row["waiting_since"],
        "order_key": row["order_key"].as_u64().expect("order_key").to_string(),
        "source_capture_ids": row["source_capture_ids"], "created_at": row["created_at"],
        "updated_at": row["updated_at"], "completed_at": row["completed_at"],
        "cancelled_at": row["cancelled_at"],
        "revision": row["revision"].as_u64().expect("revision").to_string(),
        "consecutive_stalled_formulations": row["consecutive_stalled_formulations"],
        "formulation": clock, "parked": parked
    })
}

const OWNER: &str = "beea96a4-7827-599d-b786-571f694828ac";
const OTHER_OWNER: &str = "863e24a2-2512-59a9-8531-f435e248f118";

/// The oracle's relationship rules: every reference names a record of the same
/// owner, and a deleted tag is referenced by no task.
fn assert_references_hold(store: &Store) {
    for task in store.read_set.tasks.values() {
        if let Some(project) = &task.project_id {
            assert!(store.read_set.projects.contains_key(project), "{}", task.id);
        }
        for tag in &task.tag_ids {
            let record = store
                .read_set
                .tags
                .get(tag)
                .unwrap_or_else(|| panic!("{tag}"));
            assert_eq!(
                record.state,
                TagState::Active,
                "{} holds deleted {tag}",
                task.id
            );
        }
    }
}

#[test]
fn organize_026_fr_002_the_reference_dataset_loads_per_owner_and_satisfies_its_rules() {
    let expected = &support::reference_store()["dataset"]["expected_counts"];
    let mut ran = 0;
    for owner in [OWNER, OTHER_OWNER] {
        let store = owner_store(owner);
        let counts = &expected[owner];
        assert_eq!(store.read_set.projects.len() as u64, counts["projects"]);
        assert_eq!(store.read_set.tags.len() as u64, counts["tags"]);
        assert_eq!(store.read_set.tasks.len() as u64, counts["tasks"]);
        assert_references_hold(&store);
        ran += 1;
    }
    ran_all("reference owners", ran, 2);
}

#[test]
fn organize_026_fr_002_reference_names_collide_per_owner_only() {
    let store = owner_store(OWNER);
    let garden = store.project_named("Garden").id.clone();
    let err = refusal(store.decide(&project_create("project_n", "  GARDEN ")));
    assert_eq!(
        (err.reason, err.entity),
        (
            Reason::DuplicateProjectName,
            Some((EntityType::Project, vec![garden.to_string()]))
        )
    );
    let err = refusal(store.decide(&project_create("project_s", "STRASSE")));
    assert_eq!(
        err.entity.map(|(_, key)| key),
        Some(vec![store.project_named("Straße").id.to_string()])
    );
    // The other owner has its own Garden and no Straße.
    let other = owner_store(OTHER_OWNER);
    assert_eq!(
        refusal(other.decide(&project_create("project_n", "garden"))).reason,
        Reason::DuplicateProjectName
    );
    accepted(other.decide(&project_create("project_s", "STRASSE")));
    // Tags: the leading @ and Unicode forms collide with stored keys; a deleted tag's name is free.
    assert_eq!(
        refusal(store.decide(&tag_create("tag_n", "@HOME"))).reason,
        Reason::DuplicateTagName
    );
    assert_eq!(
        refusal(store.decide(&tag_create("tag_c", "cafe\u{301}"))).reason,
        Reason::DuplicateTagName
    );
    assert_eq!(
        refusal(other.decide(&tag_create("tag_w", "WORK"))).reason,
        Reason::DuplicateTagName
    );
    let old = accepted(store.decide(&tag_create("tag_o", "OLD")));
    assert_eq!(the_tag(&old).state, TagState::Active);
}

#[test]
fn organize_026_fr_002_archived_reference_project_names_are_free_and_unarchive_refuses_a_taken_one()
{
    let mut store = owner_store(OWNER);
    let flat = store.project_named("Квартира No5").clone();
    assert_eq!(flat.state, ProjectState::Archived);
    accepted(store.run(&project_create("project_flat", "КВАРТИРА NO5")));
    let id = flat.id.as_str();
    let err = refusal(store.decide(&project_edit("project.unarchive", id, json!({}), 3)));
    assert_eq!(err.reason, Reason::UnarchiveNameInUse);
    // The archived project is still editable meanwhile.
    accepted(store.run(&project_edit(
        "project.update",
        id,
        json!({ "desired_outcome": "Moved in" }),
        3,
    )));
    assert_eq!(store.project(id).state, ProjectState::Archived);
}

#[test]
fn organize_026_fr_009_reference_archives_keep_members_and_old_archives_keep_their_marker() {
    let mut store = owner_store(OWNER);
    let tasks_before = store.read_set.tasks.clone();
    let strasse = store.project_named("Straße").id.clone();
    let set = accepted(store.run(&project_edit(
        "project.archive",
        strasse.as_str(),
        json!({}),
        1,
    )));
    assert_eq!(set.changes.len(), 1);
    assert_eq!(store.read_set.tasks, tasks_before);
    assert!(
        store
            .read_set
            .tasks
            .values()
            .any(|t| t.project_id.as_ref() == Some(&strasse)),
        "the project keeps a member"
    );
    let legacy = store.project_named("Legacy Project").id.clone();
    assert!(store.project(legacy.as_str()).archived_before_lossless);
    let repeat = accepted(store.run(&project_edit(
        "project.archive",
        legacy.as_str(),
        json!({}),
        2,
    )));
    let kept = the_project(&repeat);
    assert!(kept.archived_at.is_none() && kept.archived_before_lossless);
    assert_eq!(kept.revision, Counter::from(3));
    let reopened = accepted(store.run(&project_edit(
        "project.unarchive",
        legacy.as_str(),
        json!({}),
        3,
    )));
    assert!(the_project(&reopened).archived_before_lossless);
    assert_eq!(the_project(&reopened).state, ProjectState::Active);
}

#[test]
fn organize_026_fr_008_deleting_a_reference_tag_unlinks_exactly_the_tasks_that_held_it() {
    let mut store = owner_store(OWNER);
    for name in ["work", "Home", "caf\u{e9}"] {
        let tag = store.tag_named(name).clone();
        let holders: Vec<TaskId> = store
            .read_set
            .tasks
            .values()
            .filter(|t| t.tag_ids.contains(&tag.id))
            .map(|t| t.id.clone())
            .collect();
        assert!(
            !holders.is_empty(),
            "{name} is held by a task in the oracle"
        );
        let set = accepted(store.run(&tag_edit("tag.delete", tag.id.as_str(), json!({}), 1)));
        let changed: Vec<String> = set
            .changes
            .iter()
            .skip(1)
            .map(|c| c.record_key()[0].clone())
            .collect();
        let expected: Vec<String> = holders.iter().map(ToString::to_string).collect();
        assert_eq!(changed, expected, "{name}");
        assert_eq!(store.tag(tag.id.as_str()).state, TagState::Deleted);
        assert_references_hold(&store);
    }
}

#[test]
fn organize_026_fr_002_reference_membership_edits_are_scope_local_and_revision_checked() {
    let store = owner_store(OWNER);
    let work = store.tag_named("work").id.clone();
    let home = store.tag_named("Home").id.clone();
    let old = store.tag_named("old").id.clone();
    let foreign = owner_store(OTHER_OWNER).tag_named("work").id.clone();
    let task = store
        .read_set
        .tasks
        .values()
        .find(|t| t.tag_ids.contains(&work) && t.tag_ids.len() == 2)
        .expect("the two-tag task")
        .clone();
    let revision = task.revision.to_u64().expect("revision");
    let set = accepted(store.decide(&task_tags(
        task.id.as_str(),
        &[home.as_str()],
        &[work.as_str()],
        revision,
    )));
    let edited = the_task(&set);
    assert_eq!(edited.tag_ids.len(), 2);
    assert!(edited.tag_ids.contains(&home) && !edited.tag_ids.contains(&work));
    assert_eq!(edited.parked, task.parked);
    assert_eq!(
        edited.formulation, task.formulation,
        "tags never touch the clock"
    );
    let stale = refusal(store.decide(&task_tags(
        task.id.as_str(),
        &[home.as_str()],
        &[],
        revision - 1,
    )));
    assert_eq!(stale.current_revision, Some(task.revision.clone()));
    assert_eq!(
        refusal(store.decide(&task_tags(task.id.as_str(), &[old.as_str()], &[], revision))).reason,
        Reason::TagNotActive
    );
    assert_eq!(
        refusal(store.decide(&task_tags(
            task.id.as_str(),
            &[foreign.as_str()],
            &[],
            revision
        )))
        .reason,
        Reason::NotFound
    );
}

// -------------------------------- parity: golden project traces (spec 021, backend)

const SEEDED_AT: &str = "2026-10-01T10:00:00Z";
/// `GET /projects?state=` lists and sorts: a query, not an organization command.
const QUERY_TRACES: [&str; 1] = ["TR-L01"];

struct Server {
    store: Store,
    receipts: HashMap<String, (u16, Value)>,
    minted: u64,
}

impl Server {
    fn new() -> Self {
        Self {
            store: Store::default(),
            receipts: HashMap::new(),
            minted: 0,
        }
    }

    fn mint(&mut self, prefix: &str) -> String {
        self.minted += 1;
        format!("{prefix}_{:012x}", self.minted)
    }

    fn project_body(&self, project: &Project) -> Value {
        let open = self
            .store
            .read_set
            .tasks
            .values()
            .filter(|t| t.project_id.as_ref() == Some(&project.id) && t.state.is_open())
            .count();
        json!({
            "id": project.id.as_str(), "name": project.name.as_str(),
            "color": project.color.as_ref().map(|c| c.as_str()),
            "state": project.state.as_str(),
            "revision": project.revision.to_u64(), "open_task_count": open,
            "desired_outcome": project.desired_outcome.as_ref().map(|o| o.as_str()),
            "archived_at": project.archived_at.as_ref().map(|i| i.as_str()),
            "archived_before_lossless": project.archived_before_lossless
        })
    }

    fn task_body(task: &Task) -> Value {
        json!({ "id": task.id.as_str(), "project_id": task.project_id.as_ref().map(|p| p.as_str()),
                "revision": task.revision.to_u64() })
    }

    fn failure(error: &DomainError) -> (u16, Value) {
        let status = match error.reason {
            Reason::NotFound => 404,
            Reason::RevisionConflict
            | Reason::IdAlreadyExists
            | Reason::DuplicateProjectName
            | Reason::UnarchiveNameInUse => 409,
            Reason::ProjectNotActive | Reason::TagNotActive | Reason::DuplicateTag => 400,
            _ => 422,
        };
        let message = match error.reason {
            Reason::ProjectNotActive => "Task project must be active.".to_owned(),
            other => other.as_str().to_owned(),
        };
        (status, json!({ "message": message }))
    }

    fn command_response(
        &mut self,
        result: Result<ChangeSet, DomainError>,
        id: &str,
        status: u16,
    ) -> (u16, Value) {
        match result {
            Err(error) => Self::failure(&error),
            Ok(_) => (status, self.project_body(&self.store.project(id).clone())),
        }
    }

    fn request(
        &mut self,
        method: &str,
        path: &str,
        key: Option<&str>,
        body: &Value,
    ) -> (u16, Value) {
        if let Some(stored) = key.and_then(|k| self.receipts.get(k)) {
            return stored.clone(); // the receipt layer answers a retried key; the core never sees it
        }
        let outcome = self.dispatch(method, path, body);
        if let Some(key) = key {
            self.receipts.insert(key.to_owned(), outcome.clone());
        }
        outcome
    }

    fn dispatch(&mut self, method: &str, path: &str, body: &Value) -> (u16, Value) {
        let parts: Vec<&str> = path.trim_start_matches("/api/").split('/').collect();
        let revision = || {
            body["expected_revision"]
                .as_u64()
                .unwrap_or_else(|| panic!("{path}: no expected_revision"))
        };
        match (method, parts.as_slice()) {
            ("POST", ["projects"]) => {
                let id = self.mint("project");
                let payload: Map<String, Value> = body.as_object().expect("body").clone();
                let command = command("project.create", &id, Value::Object(payload), vec![]);
                let result = self.store.run(&command);
                self.command_response(result, &id, 201)
            }
            ("POST", ["projects", id, action @ ("archive" | "unarchive")]) => {
                let command = project_edit(&format!("project.{action}"), id, json!({}), revision());
                let result = self.store.run(&command);
                self.command_response(result, id, 200)
            }
            ("PATCH", ["projects", id]) => {
                let mut payload = body.as_object().expect("body").clone();
                payload.remove("expected_revision");
                let command =
                    project_edit("project.update", id, Value::Object(payload), revision());
                let result = self.store.run(&command);
                self.command_response(result, id, 200)
            }
            ("GET", ["projects", id]) => match self
                .store
                .read_set
                .projects
                .get(&ProjectId::parse(*id).unwrap())
            {
                Some(project) => (200, self.project_body(project)),
                None => Self::failure(&DomainError::new(Reason::NotFound)),
            },
            ("POST", ["tasks"]) => {
                let id = self.mint("task");
                let project = body["project_id"].as_str();
                if let Some(project) = project {
                    let reference = ProjectId::parse(project).unwrap();
                    if let Err(error) = organize::check_references(
                        &self.store.read_set,
                        Some(&reference),
                        None,
                        None,
                    ) {
                        return Self::failure(&error);
                    }
                }
                let row = task_json(&id, "inbox", project, &[], 1);
                let task: Task = serde_json::from_value(row).expect("task");
                self.store
                    .read_set
                    .tasks
                    .insert(task.id.clone(), task.clone());
                (201, Self::task_body(&task))
            }
            ("GET", ["tasks", id]) => (200, Self::task_body(self.store.task(id))),
            ("PATCH", ["tasks", id]) => self.patch_task_project(id, body),
            other => panic!("the harness has no route for {other:?}"),
        }
    }

    /// The project-membership part of `PATCH /tasks/{id}` (021-FR-025): the
    /// task rule family owns the rest; this shim only exercises the shared
    /// reference check the way `update_task_result` calls it.
    fn patch_task_project(&mut self, id: &str, body: &Value) -> (u16, Value) {
        let task = self.store.task(id).clone();
        if body["expected_revision"].as_u64() != task.revision.to_u64() {
            return Self::failure(&DomainError::new(Reason::RevisionConflict));
        }
        let mut updated = task.clone();
        if let Some(requested) = body.get("project_id") {
            updated.project_id = match requested.as_str() {
                None => None,
                Some(project) => {
                    let reference = ProjectId::parse(project).unwrap();
                    let checked = organize::check_references(
                        &self.store.read_set,
                        Some(&reference),
                        None,
                        task.project_id.as_ref(),
                    );
                    if let Err(error) = checked {
                        return Self::failure(&error);
                    }
                    Some(reference)
                }
            };
        }
        updated.revision = Counter::from(task.revision.to_u64().expect("revision") + 1);
        self.store
            .read_set
            .tasks
            .insert(updated.id.clone(), updated.clone());
        (200, Self::task_body(&updated))
    }

    /// `_seed` of backend/tests/test_project_archive_traces.py.
    fn seed(&mut self, seed: &Value) {
        let id = ProjectId::parse(text(seed, "project")).unwrap();
        let kept = text(seed, "kind") == "archive_keeping_members";
        let stored = self.store.read_set.projects[&id].clone();
        let seeded = Project {
            state: ProjectState::Archived,
            revision: Counter::from(stored.revision.to_u64().unwrap() + 1),
            archived_at: kept.then(|| serde_json::from_value(json!(SEEDED_AT)).unwrap()),
            archived_before_lossless: !kept,
            ..stored
        };
        self.store.read_set.projects.insert(id, seeded);
    }
}

fn substitute(value: &Value, captured: &HashMap<String, Value>) -> Value {
    match value {
        Value::String(s) => {
            let mut out = s.clone();
            for (name, replacement) in captured {
                let marker = format!("{{{name}}}");
                if out == marker {
                    return replacement.clone();
                }
                out = out.replace(&marker, replacement.as_str().expect("string capture"));
            }
            Value::String(out)
        }
        Value::Array(items) => {
            Value::Array(items.iter().map(|v| substitute(v, captured)).collect())
        }
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(k, v)| (k.clone(), substitute(v, captured)))
                .collect(),
        ),
        other => other.clone(),
    }
}

/// The trace matcher: every expected key is present and equal, recursively; a
/// list has the same length; `$present` is any non-null value.
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
fn organize_026_fr_002_the_golden_project_traces_replay_through_the_shared_rules() {
    let file = project_archive_traces();
    let traces = cases(file, "traces");
    let (mut replayed, mut steps) = (0, 0);
    for trace in traces {
        let id = text(trace, "id");
        if QUERY_TRACES.contains(&id) {
            continue;
        }
        let mut servers = [Server::new(), Server::new()];
        let mut captured: HashMap<String, Value> = HashMap::new();
        for step in trace["steps"].as_array().expect("steps") {
            let name = text(step, "name");
            if let Some(seed) = step.get("seed") {
                servers[0].seed(&substitute(seed, &captured));
                steps += 1;
                continue;
            }
            let request = substitute(&step["request"], &captured);
            let who = usize::from(request["as"].as_str() == Some("second"));
            let (status, body) = servers[who].request(
                text(&request, "method"),
                text(&request, "path"),
                request["key"].as_str(),
                &request["body"],
            );
            let expect = substitute(&step["expect"], &captured);
            assert_eq!(
                i64::from(status),
                expect["status"].as_i64().unwrap(),
                "{id}: {name}: {body}"
            );
            if let Some(want) = expect.get("body") {
                assert_subset(want, &body, &format!("{id}: {name}"));
            }
            for (variable, path) in step["capture"].as_object().into_iter().flatten() {
                captured.insert(variable.clone(), body[path.as_str().expect("path")].clone());
            }
            steps += 1;
        }
        replayed += 1;
    }
    ran_all("golden traces", replayed, traces.len() - QUERY_TRACES.len());
    assert!(steps >= 30, "ran {steps} trace steps");
}
