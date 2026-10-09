//! Parity of the task lifecycle rules (`task.create`, `task.update`,
//! `task.transition`) with the server, the Swift reducer and the frozen oracle
//! (tasks.md T007, PR-07).
//!
//! The runner compiles the **actual** rule source with a plain `#[path]` module
//! (plus the formulation clock it builds on) and re-exports the shared crates
//! at the test-crate root, so the rule's own `crate::` paths resolve exactly as
//! they do in the library (tasks.md, "Dependencies"). Every data-driven test
//! counts the cases it executed, so an empty or truncated section fails
//! instead of passing vacuously.

mod support;

pub use bb_domain::{calendar, normalization, types};

#[allow(dead_code, unused_imports)]
#[path = "../src/formulation.rs"]
mod formulation;
#[path = "../src/task_rules.rs"]
mod task_rules;

use bb_domain::calendar::UtcInstant;
use bb_protocol::command::{Decoded, decode_command};
use formulation::{OwnerClockSettings, TaskClock};
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use support::{cases, text};
use types::{
    ChangeOutcome, ChangeSet, Counter, DomainChange, DomainCommand, DomainError, EntityType,
    ExecutionInputs, ProjectId, ReadSet, Reason, Record, Task, TaskId, TaskState,
};

const NOW: &str = "2026-10-09T12:00:00Z";
const LATER: &str = "2026-10-09T13:30:00Z";
/// IDs a created task carries are native-shaped (`task_<lowercase uuid>`).
const NEW_TASK: &str = "task_0b0e1f30-0000-4000-8000-00000000a001";
const EXTRA_TASK: &str = "task_0b0e1f30-0000-4000-8000-00000000a002";
const VECTOR_TASK: &str = "task_0b0e1f30-0000-4000-8000-00000000a003";
const FORM_A: &str = "form_0b0e1f30-0000-4000-8000-00000000000a";
const FORM_B: &str = "form_0b0e1f30-0000-4000-8000-00000000000b";
const FORM_C: &str = "form_0b0e1f30-0000-4000-8000-00000000000c";

// ----------------------------------------------------------------------- harness

fn inputs_at(now: &str, allocated: &[&str]) -> ExecutionInputs {
    serde_json::from_value(json!({
        "rule_version": 1,
        "now": now,
        "time_zone": "UTC",
        "origin": "device",
        "actor_id": "actor-example",
        "authoritative": true,
        "allocated_ids": allocated,
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

fn create(id: &str, payload: Value) -> DomainCommand {
    command("task.create", id, payload, vec![])
}

fn update(id: &str, payload: Value, revision: u64) -> DomainCommand {
    command(
        "task.update",
        id,
        payload,
        vec![check("task", id, revision)],
    )
}

fn transition(id: &str, payload: Value, revision: u64) -> DomainCommand {
    command(
        "task.transition",
        id,
        payload,
        vec![check("task", id, revision)],
    )
}

fn project_json(id: &str, name: &str, state: &str) -> Value {
    json!({
        "id": id, "name": name, "color": null, "state": state, "revision": "2",
        "desired_outcome": null,
        "archived_at": if state == "archived" { json!("2026-09-01T09:00:00Z") } else { Value::Null },
        "archived_before_lossless": false
    })
}

fn tag_json(id: &str, name: &str, state: &str) -> Value {
    json!({ "id": id, "name": name, "state": state, "revision": "1" })
}

fn task_json(id: &str, state: &str, revision: u64) -> Value {
    json!({
        "id": id, "title": format!("Task {id}"), "details": null, "state": state,
        "project_id": null, "tag_ids": [], "due_date": null, "priority": "none",
        "waiting_for": if state == "waiting" { json!("Bob") } else { Value::Null },
        "waiting_since": if state == "waiting" { json!("2026-09-02T09:00:00Z") } else { Value::Null },
        "order_key": "3",
        "source_capture_ids": [], "created_at": "2026-09-01T09:00:00Z",
        "updated_at": "2026-09-02T09:00:00Z",
        "completed_at": if state == "completed" { json!("2026-09-03T09:00:00Z") } else { Value::Null },
        "cancelled_at": if state == "cancelled" { json!("2026-09-03T09:00:00Z") } else { Value::Null },
        "revision": revision.to_string(), "consecutive_stalled_formulations": 0,
        "formulation": null, "parked": null
    })
}

/// `row` with the members of `patch` replaced.
fn with(mut row: Value, patch: Value) -> Value {
    for (key, value) in patch.as_object().expect("a patch object") {
        row[key] = value.clone();
    }
    row
}

fn clock_json(id: &str, started: &str) -> Value {
    json!({ "id": id, "started_at": started, "extended_at": null,
            "extension_reason": null, "park_floor_at": null })
}

fn parked_json(formulation: &str) -> Value {
    json!({
        "at": "2026-10-01T09:00:00Z", "formulation_id": formulation,
        "private": { "from_revision": "3", "clock_before": {
            "formulation_id": formulation, "started_at": "2026-09-10T09:00:00Z",
            "extended_at": null, "extension_reason": null, "park_floor_at": null,
            "stalled_before": 0 } }
    })
}

fn settings_json(zone: &str, activated: Option<&str>) -> Value {
    json!({
        "threshold_days": 14, "review_weekday": 5, "review_time": "16:00", "time_zone": zone,
        "onboarded_at": null, "activated_at": activated, "owner_park_floor_at": null,
        "revision": "1"
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

    fn with_settings(mut self, settings: &Value) -> Self {
        self.read_set.settings = Some(serde_json::from_value(settings.clone()).expect("settings"));
        self
    }

    fn with_park_ack(mut self, task: &str, formulation: &str) -> Self {
        self.read_set.park_acks.push(
            serde_json::from_value(json!({
                "task_id": task, "formulation_id": formulation,
                "parked_at": "2026-10-01T09:00:00Z", "seen_at": null, "returned_at": null
            }))
            .expect("park ack"),
        );
        self
    }

    fn decide_with(
        &self,
        command: &DomainCommand,
        now: &str,
        allocated: &[&str],
    ) -> Result<ChangeSet, DomainError> {
        task_rules::decide(&self.read_set, command, &inputs_at(now, allocated))
    }

    fn decide(&self, command: &DomainCommand) -> Result<ChangeSet, DomainError> {
        self.decide_with(command, NOW, &[])
    }

    /// Decides and, when accepted, lands the changes in application order.
    fn run_with(
        &mut self,
        command: &DomainCommand,
        now: &str,
        allocated: &[&str],
    ) -> Result<ChangeSet, DomainError> {
        let set = self.decide_with(command, now, allocated)?;
        for change in &set.changes {
            match change {
                DomainChange::Upsert(Record::Task(t)) => {
                    self.read_set.tasks.insert(t.id.clone(), t.clone());
                }
                DomainChange::Upsert(Record::ReviewParkAck(ack)) => {
                    let slot = self
                        .read_set
                        .park_acks
                        .iter_mut()
                        .find(|a| {
                            a.task_id == ack.task_id && a.formulation_id == ack.formulation_id
                        })
                        .expect("an acknowledgement that exists");
                    *slot = ack.clone();
                }
                other => panic!("a task command changed {other:?}"),
            }
        }
        Ok(set)
    }

    fn run(&mut self, command: &DomainCommand) -> Result<ChangeSet, DomainError> {
        self.run_with(command, NOW, &[])
    }

    fn task(&self, id: &str) -> &Task {
        &self.read_set.tasks[&TaskId::parse(id).expect("task id")]
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

fn the_task(set: &ChangeSet) -> &Task {
    match set.changes.as_slice() {
        [DomainChange::Upsert(Record::Task(task))] => task,
        other => panic!("expected exactly one task change, got {other:?}"),
    }
}

fn ran_all(section: &str, ran: usize, expected: usize) {
    assert!(ran > 0, "{section}: no case executed");
    assert_eq!(
        ran, expected,
        "{section}: executed cases differ from the file"
    );
}

fn revision(task: &Task) -> u64 {
    task.revision.to_u64().expect("a small revision")
}

fn instant(task_field: Option<&types::Instant>) -> Option<String> {
    task_field.map(|value| value.as_str().to_owned())
}

fn tag_ids(task: &Task) -> Vec<&str> {
    task.tag_ids.iter().map(types::TagId::as_str).collect()
}

/// A scope with two projects (one archived), three tags (one deleted) and a
/// task in every state; each task's revision is 2.
fn world() -> Store {
    Store::new(
        &[
            project_json("project_live", "Live", "active"),
            project_json("project_old", "Old", "archived"),
        ],
        &[
            tag_json("tag_work", "work", "active"),
            tag_json("tag_home", "home", "active"),
            tag_json("tag_gone", "gone", "deleted"),
        ],
        &[
            with(task_json("t_inbox", "inbox", 2), json!({"order_key": "4"})),
            with(task_json("t_next", "next", 2), json!({"order_key": "1"})),
            task_json("t_waiting", "waiting", 2),
            with(
                task_json("t_someday", "someday", 2),
                json!({"order_key": "0"}),
            ),
            task_json("t_done", "completed", 2),
            task_json("t_cancelled", "cancelled", 2),
        ],
    )
}

// ------------------------------------------------------------------ the family

#[test]
fn task_rules_026_fr_002_this_family_decides_exactly_the_three_task_lifecycle_commands() {
    let ours = [
        create(NEW_TASK, json!({"title": "A"})),
        update("t_inbox", json!({"details": "d"}), 2),
        transition("t_inbox", json!({"action": "complete"}), 2),
    ];
    for c in &ours {
        assert!(
            task_rules::handles(&c.command),
            "{}",
            c.command_type().as_str()
        );
    }
    let others = [
        command(
            "task.tags",
            "t_inbox",
            json!({"add_tag_ids": ["tag_work"], "remove_tag_ids": []}),
            vec![check("task", "t_inbox", 2)],
        ),
        command("tag.create", "tag_new", json!({"name": "x"}), vec![]),
        command(
            "subtask.create",
            "subtask_new",
            json!({"task_id": "t_inbox", "title": "s"}),
            vec![],
        ),
    ];
    let mut refused = 0;
    for c in &others {
        assert!(!task_rules::handles(&c.command));
        let error = refusal(world().decide(c));
        assert_eq!(error.reason, Reason::InvalidPayload);
        assert_eq!(error.field.as_deref(), Some("type"));
        refused += 1;
    }
    ran_all("foreign commands", refused, others.len());
}

#[test]
fn task_rules_026_fr_002_decide_is_pure_and_time_is_only_an_input() {
    let store = world();
    let before = store.read_set.clone();
    let c = update("t_next", json!({"title": "Something else entirely"}), 2);
    let first = accepted(store.decide_with(&c, NOW, &[FORM_A]));
    let again = accepted(store.decide_with(&c, NOW, &[FORM_A]));
    assert_eq!(first, again);
    assert_eq!(store.read_set, before, "decide never edits the read set");
    let later = accepted(store.decide_with(&c, LATER, &[FORM_A]));
    assert_eq!(the_task(&first).updated_at.as_str(), NOW);
    assert_eq!(the_task(&later).updated_at.as_str(), LATER);
}

// ----------------------------------------------------------------------- create

#[test]
fn task_rules_026_fr_002_a_new_task_has_the_server_defaults() {
    let store = world();
    let set = accepted(store.decide(&create(NEW_TASK, json!({"title": "  Call Bob  "}))));
    assert_eq!(set.outcome, ChangeOutcome::Applied);
    let task = the_task(&set);
    // Verbatim: the server neither trims nor collapses a title.
    assert_eq!(task.title.as_str(), "  Call Bob  ");
    assert_eq!(task.id.as_str(), NEW_TASK);
    assert_eq!(task.state, TaskState::Inbox);
    assert_eq!(task.priority, types::Priority::None);
    assert_eq!(task.details, None);
    assert_eq!(task.revision, Counter::from(1));
    assert_eq!(task.created_at.as_str(), NOW);
    assert_eq!(task.updated_at.as_str(), NOW);
    assert!(task.completed_at.is_none() && task.cancelled_at.is_none());
    assert!(task.waiting_for.is_none() && task.waiting_since.is_none());
    assert!(task.formulation.is_none() && task.parked.is_none());
    assert_eq!(task.consecutive_stalled_formulations, 0);
    assert!(task.tag_ids.is_empty() && task.source_capture_ids.is_empty());
    assert!(set.result.created_task_id.is_none() && set.effects.is_empty());
}

#[test]
fn task_rules_026_fr_002_a_new_task_keeps_every_field_it_was_given() {
    let set = accepted(world().decide(&create(
        NEW_TASK,
        json!({
            "title": "Plan", "details": "", "state": "someday",
            "project_id": "project_live", "tag_ids": ["tag_home", "tag_work"],
            "due_date": "2026-12-01", "priority": "high"
        }),
    )));
    let task = the_task(&set);
    // An empty note stays empty: the server stores what it was sent.
    assert_eq!(task.details.as_ref().map(types::Details::as_str), Some(""));
    assert_eq!(task.state, TaskState::Someday);
    assert_eq!(
        task.project_id.as_ref().map(ProjectId::as_str),
        Some("project_live")
    );
    assert_eq!(tag_ids(task), ["tag_home", "tag_work"]);
    assert_eq!(
        task.due_date.as_ref().map(types::DueDay::as_str),
        Some("2026-12-01")
    );
    assert_eq!(task.priority, types::Priority::High);
}

#[test]
fn task_rules_026_fr_002_waiting_needs_a_trimmed_note_and_other_lists_drop_one() {
    let store = world();
    let set = accepted(store.decide(&create(
        NEW_TASK,
        json!({"title": "Reply", "state": "waiting", "waiting_for": " \u{1c}Landlord \t"}),
    )));
    let task = the_task(&set);
    assert_eq!(
        task.waiting_for.as_ref().map(types::WaitingFor::as_str),
        Some("Landlord")
    );
    assert_eq!(instant(task.waiting_since.as_ref()).as_deref(), Some(NOW));
    for payload in [
        json!({"title": "Reply", "state": "waiting"}),
        json!({"title": "Reply", "state": "waiting", "waiting_for": null}),
        json!({"title": "Reply", "state": "waiting", "waiting_for": " \n\u{a0}"}),
    ] {
        let error = refusal(store.decide(&create(NEW_TASK, payload)));
        assert_eq!(error.reason, Reason::WaitingForRequired);
        assert_eq!(error.field.as_deref(), Some("waiting_for"));
    }
    let mut dropped = 0;
    for list in ["inbox", "next", "someday"] {
        let set = accepted(store.decide_with(
            &create(
                NEW_TASK,
                json!({"title": "Reply", "state": list, "waiting_for": "Bob"}),
            ),
            NOW,
            &[FORM_A],
        ));
        let task = the_task(&set);
        assert!(
            task.waiting_for.is_none() && task.waiting_since.is_none(),
            "{list}"
        );
        dropped += 1;
    }
    ran_all("lists that drop the note", dropped, 3);
}

#[test]
fn task_rules_026_fr_002_the_order_key_is_one_past_the_last_of_the_same_list() {
    let store = world();
    let mut seen = Vec::new();
    for (list, expected) in [
        ("inbox", "5"),
        ("next", "2"),
        ("waiting", "4"),
        ("someday", "1"),
    ] {
        let mut payload = json!({"title": "X", "state": list});
        if list == "waiting" {
            payload["waiting_for"] = json!("Bob");
        }
        let set = accepted(store.decide_with(&create(NEW_TASK, payload), NOW, &[FORM_A]));
        assert_eq!(the_task(&set).order_key.as_str(), expected, "{list}");
        seen.push(list);
    }
    ran_all("lists", seen.len(), 4);
    // Closed tasks do not count and an empty list starts at zero.
    let empty = Store::new(&[], &[], &[task_json("t_done", "completed", 1)]);
    let set = accepted(empty.decide(&create(NEW_TASK, json!({"title": "X"}))));
    assert_eq!(the_task(&set).order_key.as_str(), "0");
}

#[test]
fn task_rules_026_fr_008_an_id_that_exists_is_never_created_again() {
    let store = Store::new(&[], &[], &[task_json(NEW_TASK, "inbox", 2)]);
    let error = refusal(store.decide(&create(NEW_TASK, json!({"title": "Again"}))));
    assert_eq!(error.reason, Reason::IdAlreadyExists);
    assert_eq!(error.field.as_deref(), Some("entity_id"));
    assert_eq!(
        store.task(NEW_TASK).title.as_str(),
        format!("Task {NEW_TASK}")
    );
}

#[test]
fn task_rules_026_fr_008_a_created_task_needs_a_native_id_and_legacy_ids_stay_references() {
    let store = world();
    let payload = || json!({"title": "Fresh"});
    // Malformed and legacy-shaped IDs are never persisted as new tasks, whether
    // the ID is free or already held by an existing record.
    let refused = [
        "x",
        "t_new",
        "t_inbox",
        "task_abc123def456",
        "task_0B0E1F30-0000-4000-8000-00000000A001",
        "project_0b0e1f30-0000-4000-8000-00000000a001",
        "task_0b0e1f30-0000-4000-8000-00000000a001-extra",
    ];
    for id in refused {
        let error = refusal(store.decide(&create(id, payload())));
        assert_eq!(error.reason, Reason::InvalidValue, "{id}");
        assert_eq!(error.field.as_deref(), Some("TaskId"), "{id}");
    }
    // The same legacy ID is still a valid reference to the record that holds it.
    let set = accepted(store.decide(&update("t_inbox", json!({"title": "Still editable"}), 2)));
    assert_eq!(the_task(&set).id.as_str(), "t_inbox");
    // A native ID is accepted.
    let set = accepted(store.decide(&create(NEW_TASK, payload())));
    assert_eq!(the_task(&set).id.as_str(), NEW_TASK);
}

#[test]
fn task_rules_026_fr_002_creation_checks_references_in_the_service_order() {
    let store = world();
    let reason = |payload: Value| refusal(store.decide(&create(NEW_TASK, payload)));
    let error = reason(json!({"title": "X", "project_id": "project_missing"}));
    assert_eq!(error.reason, Reason::NotFound);
    assert_eq!(
        error.entity.as_ref().map(|e| e.0),
        Some(EntityType::Project)
    );
    let error = reason(json!({"title": "X", "project_id": "project_old"}));
    assert_eq!(error.reason, Reason::ProjectNotActive);
    assert_eq!(error.field.as_deref(), Some("project_id"));
    assert_eq!(
        reason(json!({"title": "X", "tag_ids": ["tag_work", "tag_work"]})).reason,
        Reason::DuplicateTag
    );
    let error = reason(json!({"title": "X", "tag_ids": ["tag_missing"]}));
    assert_eq!(
        (error.reason, error.entity.map(|e| e.0)),
        (Reason::NotFound, Some(EntityType::Tag))
    );
    assert_eq!(
        reason(json!({"title": "X", "tag_ids": ["tag_work", "tag_gone"]})).reason,
        Reason::TagNotActive
    );
    // The project is checked before the tags and both before the note.
    let both = json!({"title": "X", "project_id": "project_old", "tag_ids": ["tag_gone"],
                      "state": "waiting"});
    assert_eq!(reason(both).reason, Reason::ProjectNotActive);
    let tags_and_note = json!({"title": "X", "tag_ids": ["tag_gone"], "state": "waiting"});
    assert_eq!(reason(tags_and_note).reason, Reason::TagNotActive);
    let note_and_capture = json!({"title": "X", "state": "waiting", "source_capture_ids": ["c1"]});
    assert_eq!(reason(note_and_capture).reason, Reason::WaitingForRequired);
}

#[test]
fn task_rules_026_fr_002_source_captures_need_the_adapters_capture_validation() {
    let error = refusal(world().decide(&create(
        NEW_TASK,
        json!({"title": "X", "source_capture_ids": ["capture-1"]}),
    )));
    assert_eq!(error.reason, Reason::InvalidValue);
    assert_eq!(error.field.as_deref(), Some("source_capture_ids"));
}

#[test]
fn task_rules_026_fr_002_a_task_created_in_next_starts_its_formulation() {
    let store = world();
    let asked = accepted(store.decide_with(
        &create(
            NEW_TASK,
            json!({"title": "X", "state": "next", "new_formulation_id": FORM_B}),
        ),
        NOW,
        &[FORM_A],
    ));
    let clock = the_task(&asked).formulation.as_ref().expect("a clock");
    assert_eq!(
        clock.id.as_str(),
        FORM_B,
        "the client's id wins over the allocated one"
    );
    assert_eq!(clock.started_at.as_str(), NOW);
    assert!(clock.extended_at.is_none() && clock.extension_reason.is_none());
    assert!(clock.park_floor_at.is_none());
    let minted = accepted(store.decide_with(
        &create(NEW_TASK, json!({"title": "X", "state": "next"})),
        NOW,
        &[FORM_A],
    ));
    assert_eq!(
        the_task(&minted)
            .formulation
            .as_ref()
            .expect("a clock")
            .id
            .as_str(),
        FORM_A
    );
    let error = refusal(store.decide(&create(NEW_TASK, json!({"title": "X", "state": "next"}))));
    assert_eq!(error.reason, Reason::FormulationIdRequired);
    // Only a task created in Next gets a clock.
    let inbox = accepted(store.decide(&create(
        NEW_TASK,
        json!({"title": "X", "new_formulation_id": FORM_B}),
    )));
    assert!(the_task(&inbox).formulation.is_none());
}

#[test]
fn task_rules_026_fr_002_catalog_limits_count_unicode_scalars_not_bytes() {
    let emoji = |count: usize| "\u{1F600}".repeat(count);
    let make = |payload: Value| try_command("task.create", NEW_TASK, payload, vec![]);
    let mut ran = 0;
    for (name, ok, too_long) in [
        (
            "title",
            json!({"title": emoji(500)}),
            json!({"title": emoji(501)}),
        ),
        (
            "details",
            json!({"title": "X", "details": emoji(20_000)}),
            json!({"title": "X", "details": emoji(20_001)}),
        ),
        (
            "waiting_for",
            json!({"title": "X", "state": "waiting", "waiting_for": emoji(500)}),
            json!({"title": "X", "state": "waiting", "waiting_for": emoji(501)}),
        ),
    ] {
        let command = make(ok).unwrap_or_else(|e| panic!("{name} at the limit: {e}"));
        accepted(world().decide(&command));
        assert_eq!(
            make(too_long).unwrap_err().reason,
            Reason::InvalidPayload,
            "{name}"
        );
        ran += 1;
    }
    ran_all("limits", ran, 3);
    assert_eq!(
        make(json!({"title": ""})).unwrap_err().reason,
        Reason::InvalidPayload
    );
    assert_eq!(
        make(json!({"title": "X", "priority": "urgent"}))
            .unwrap_err()
            .reason,
        Reason::InvalidPayload
    );
    assert_eq!(
        make(json!({"title": "X", "state": "completed"}))
            .unwrap_err()
            .reason,
        Reason::InvalidPayload
    );
}

// ----------------------------------------------------------------------- update

#[test]
fn task_rules_026_fr_007_a_stale_missing_or_unknown_target_changes_nothing() {
    let mut store = world();
    let before = store.read_set.clone();
    for stale in [1, 3, 99] {
        let error = refusal(store.run(&update("t_inbox", json!({"details": "x"}), stale)));
        assert_eq!(error.reason, Reason::RevisionConflict);
        assert_eq!(error.current_revision, Some(Counter::from(2)));
        assert_eq!(error.entity.as_ref().map(|e| e.0), Some(EntityType::Task));
    }
    let unchecked = command("task.update", "t_inbox", json!({"details": "x"}), vec![]);
    let error = refusal(store.run(&unchecked));
    assert_eq!(
        (error.reason, error.field.as_deref()),
        (Reason::InvalidPayload, Some("preconditions"))
    );
    // A check on another entity is no check on this one.
    let wrong = command(
        "task.update",
        "t_inbox",
        json!({"details": "x"}),
        vec![check("task", "t_next", 2)],
    );
    assert_eq!(refusal(store.run(&wrong)).reason, Reason::InvalidPayload);
    let error = refusal(store.run(&update("t_missing", json!({"details": "x"}), 1)));
    assert_eq!(error.reason, Reason::NotFound);
    assert_eq!(store.read_set, before);
    assert_eq!(
        revision(the_task(&accepted(store.run(&update(
            "t_inbox",
            json!({"details": "x"}),
            2
        ))))),
        3
    );
}

#[test]
fn task_rules_026_fr_002_omitted_null_and_value_stay_distinct() {
    let mut store = world();
    let start = with(
        task_json("t_full", "inbox", 1),
        json!({"details": "notes", "project_id": "project_live", "due_date": "2026-11-01",
               "priority": "medium", "tag_ids": ["tag_work"]}),
    );
    store.read_set.tasks.insert(
        TaskId::parse("t_full").unwrap(),
        serde_json::from_value(start).unwrap(),
    );
    // Omitted keeps everything but still counts as an edit.
    let kept = accepted(store.decide(&update("t_full", json!({}), 1))).clone();
    let task = the_task(&kept);
    assert_eq!(
        task.details.as_ref().map(types::Details::as_str),
        Some("notes")
    );
    assert_eq!(
        task.project_id.as_ref().map(ProjectId::as_str),
        Some("project_live")
    );
    assert_eq!(
        task.due_date.as_ref().map(types::DueDay::as_str),
        Some("2026-11-01")
    );
    assert_eq!(task.priority, types::Priority::Medium);
    assert_eq!(tag_ids(task), ["tag_work"]);
    assert_eq!(revision(task), 2);
    assert_eq!(task.updated_at.as_str(), NOW);
    // null clears what can be cleared.
    let cleared = accepted(store.decide(&update(
        "t_full",
        json!({"details": null, "project_id": null, "due_date": null}),
        1,
    )));
    let task = the_task(&cleared);
    assert!(task.details.is_none() && task.project_id.is_none() && task.due_date.is_none());
    assert_eq!(task.priority, types::Priority::Medium);
    // A value sets; the title is verbatim and an empty note is an empty note.
    let set = accepted(store.decide(&update(
        "t_full",
        json!({"title": " Spaced ", "details": "", "priority": "low", "due_date": "2027-01-31"}),
        1,
    )));
    let task = the_task(&set);
    assert_eq!(task.title.as_str(), " Spaced ");
    assert_eq!(task.details.as_ref().map(types::Details::as_str), Some(""));
    assert_eq!(task.priority, types::Priority::Low);
    assert_eq!(
        task.due_date.as_ref().map(types::DueDay::as_str),
        Some("2027-01-31")
    );
    // Title and priority cannot be cleared, and the vocabulary is closed.
    for payload in [
        json!({"title": null}),
        json!({"priority": null}),
        json!({"priority": "urgent"}),
        json!({"state": "next"}),
        json!({"tag_ids": ["tag_work"]}),
    ] {
        let rejected = try_command(
            "task.update",
            "t_full",
            payload,
            vec![check("task", "t_full", 1)],
        );
        assert_eq!(rejected.unwrap_err().reason, Reason::InvalidPayload);
    }
    for priority in ["none", "low", "medium", "high"] {
        let set = accepted(store.decide(&update("t_full", json!({"priority": priority}), 1)));
        assert_eq!(the_task(&set).priority.as_str(), priority);
    }
}

#[test]
fn task_rules_026_fr_002_an_edit_with_nothing_to_change_still_bumps_the_revision() {
    let store = world();
    let same = accepted(store.decide_with(
        &update(
            "t_inbox",
            json!({"title": "Task t_inbox", "priority": "none"}),
            2,
        ),
        LATER,
        &[],
    ));
    let task = the_task(&same);
    assert_eq!((revision(task), task.updated_at.as_str()), (3, LATER));
    assert_eq!(task.title, store.task("t_inbox").title);
}

#[test]
fn task_rules_026_fr_002_waiting_for_is_edited_only_on_waiting_tasks_and_never_blank() {
    let mut store = world();
    for id in ["t_inbox", "t_next", "t_someday", "t_done", "t_cancelled"] {
        for payload in [json!({"waiting_for": "Bob"}), json!({"waiting_for": null})] {
            let error = refusal(store.decide(&update(id, payload, 2)));
            assert_eq!(error.reason, Reason::WaitingForOnlyOnWaitingTasks, "{id}");
            assert_eq!(error.field.as_deref(), Some("waiting_for"));
        }
    }
    for blank in [json!(null), json!(""), json!("  \t")] {
        let error = refusal(store.decide(&update("t_waiting", json!({"waiting_for": blank}), 2)));
        assert_eq!(error.reason, Reason::WaitingForRequired);
    }
    let set = accepted(store.run(&update("t_waiting", json!({"waiting_for": "  Carol "}), 2)));
    let task = the_task(&set);
    assert_eq!(
        task.waiting_for.as_ref().map(types::WaitingFor::as_str),
        Some("Carol")
    );
    // Editing the note does not restart the wait (ADR-0006).
    assert_eq!(
        instant(task.waiting_since.as_ref()).as_deref(),
        Some("2026-09-02T09:00:00Z")
    );
    assert_eq!(task.state, TaskState::Waiting);
}

#[test]
fn task_rules_026_fr_009_a_carried_archived_project_is_never_revalidated() {
    // spec 021 TR-T01: omit, the same archived project, a different archived
    // one (refused), null, then an active one.
    let mut store = world();
    store.read_set.projects.insert(
        ProjectId::parse("project_older").unwrap(),
        serde_json::from_value(project_json("project_older", "Older", "archived")).unwrap(),
    );
    store.read_set.tasks.insert(
        TaskId::parse("t_member").unwrap(),
        serde_json::from_value(with(
            task_json("t_member", "inbox", 1),
            json!({"project_id": "project_old"}),
        ))
        .unwrap(),
    );
    let project = |store: &Store| store.task("t_member").project_id.clone();
    accepted(store.run(&update("t_member", json!({"title": "One"}), 1)));
    assert_eq!(project(&store).unwrap().as_str(), "project_old");
    accepted(store.run(&update(
        "t_member",
        json!({"title": "Two", "project_id": "project_old"}),
        2,
    )));
    assert_eq!(revision(store.task("t_member")), 3);
    let error = refusal(store.run(&update(
        "t_member",
        json!({"project_id": "project_older"}),
        3,
    )));
    assert_eq!(error.reason, Reason::ProjectNotActive);
    assert_eq!(revision(store.task("t_member")), 3);
    accepted(store.run(&update("t_member", json!({"project_id": null}), 3)));
    assert!(project(&store).is_none());
    accepted(store.run(&update(
        "t_member",
        json!({"project_id": "project_live"}),
        4,
    )));
    assert_eq!(project(&store).unwrap().as_str(), "project_live");
    let error = refusal(store.run(&update(
        "t_member",
        json!({"project_id": "project_nope"}),
        5,
    )));
    assert_eq!(error.reason, Reason::NotFound);
}

#[test]
fn task_rules_026_fr_002_tag_changes_ride_in_the_same_edit_and_are_validated() {
    let mut store = world();
    let set = accepted(store.run(&update(
        "t_inbox",
        json!({"details": "n", "tag_changes": {"add_tag_ids": ["tag_work", "tag_home"], "remove_tag_ids": []}}),
        2,
    )));
    let task = the_task(&set);
    assert_eq!(tag_ids(task), ["tag_work", "tag_home"]);
    assert_eq!(revision(task), 3, "one gesture, one revision");
    let set = accepted(store.run(&update(
        "t_inbox",
        json!({"tag_changes": {"add_tag_ids": ["tag_work"], "remove_tag_ids": ["tag_home", "tag_missing"]}}),
        3,
    )));
    assert_eq!(tag_ids(the_task(&set)), ["tag_work"]);
    for (changes, reason) in [
        (
            json!({"add_tag_ids": ["tag_gone"], "remove_tag_ids": []}),
            Reason::TagNotActive,
        ),
        (
            json!({"add_tag_ids": ["tag_missing"], "remove_tag_ids": []}),
            Reason::NotFound,
        ),
    ] {
        let error = refusal(store.run(&update("t_inbox", json!({"tag_changes": changes}), 4)));
        assert_eq!(error.reason, reason);
    }
    // Overlapping lists never become a command: the envelope refuses them.
    let overlap = envelope_json(
        "task.update",
        "t_inbox",
        json!({"tag_changes": {"add_tag_ids": ["tag_home"], "remove_tag_ids": ["tag_home"]}}),
        vec![check("task", "t_inbox", 4)],
    );
    assert!(decode_command(&overlap).is_err());
    assert_eq!(revision(store.task("t_inbox")), 4);
}

#[test]
fn task_rules_026_fr_002_closed_tasks_stay_editable_without_a_clock() {
    let mut store = world();
    let set = accepted(store.run(&update(
        "t_done",
        json!({"details": "after the fact", "due_date": "2026-12-24", "title": "Totally new title"}),
        2,
    )));
    let task = the_task(&set);
    assert_eq!(task.state, TaskState::Completed);
    assert!(task.formulation.is_none());
    assert_eq!(
        instant(task.completed_at.as_ref()).as_deref(),
        Some("2026-09-03T09:00:00Z")
    );
}

fn next_world() -> Store {
    Store::new(
        &[project_json("project_live", "Live", "active")],
        &[tag_json("tag_work", "work", "active")],
        &[with(
            task_json("t_next", "next", 3),
            json!({"title": "Call Bob", "consecutive_stalled_formulations": 1,
                   "formulation": clock_json(FORM_A, "2026-09-24T09:14:00Z")}),
        )],
    )
    .with_settings(&settings_json(
        "Europe/Berlin",
        Some("2026-09-01T08:00:00Z"),
    ))
}

#[test]
fn task_rules_026_fr_001_a_substantive_title_in_next_restarts_the_formulation() {
    let store = next_world();
    let now = "2026-10-09T14:02:00Z";
    let restart = update("t_next", json!({"title": "Email Bob the quote"}), 3);
    let set = accepted(store.decide_with(&restart, now, &[FORM_B]));
    let task = the_task(&set);
    let clock = task.formulation.as_ref().expect("a clock");
    assert_eq!(
        (clock.id.as_str(), clock.started_at.as_str()),
        (FORM_B, now)
    );
    // Asking when it closed: the stalled count goes up.
    assert_eq!(task.consecutive_stalled_formulations, 2);
    assert_eq!(revision(task), 4);
    // The client's id wins over an allocated one.
    let named = update(
        "t_next",
        json!({"title": "Email Bob the quote", "new_formulation_id": FORM_C}),
        3,
    );
    let set = accepted(store.decide_with(&named, now, &[FORM_B]));
    assert_eq!(
        the_task(&set).formulation.as_ref().unwrap().id.as_str(),
        FORM_C
    );
    // No id at all is a typed refusal, not a made-up one.
    let error = refusal(store.decide_with(&restart, now, &[]));
    assert_eq!(error.reason, Reason::FormulationIdRequired);
    // A cosmetic change keeps the clock and needs no id.
    let cosmetic = update("t_next", json!({"title": "call bob."}), 3);
    let set = accepted(store.decide_with(&cosmetic, now, &[]));
    let task = the_task(&set);
    assert_eq!(task.formulation, store.task("t_next").formulation);
    assert_eq!((task.title.as_str(), revision(task)), ("call bob.", 4));
    assert_eq!(task.consecutive_stalled_formulations, 1);
}

#[test]
fn task_rules_026_fr_046_a_due_date_change_in_next_raises_the_task_floor() {
    let store = next_world();
    let now = "2026-10-09T14:02:00Z";
    let mut with_due = next_world();
    let mut row = serde_json::to_value(with_due.task("t_next")).unwrap();
    row["due_date"] = json!("2026-09-20");
    with_due.read_set.tasks.insert(
        TaskId::parse("t_next").unwrap(),
        serde_json::from_value(row).unwrap(),
    );
    let mut ran = 0;
    // Set, moved into the past and removed: the floor rises each time.
    for (world, due) in [
        (&store, json!("2026-10-20")),
        (&store, json!("2026-09-01")),
        (&with_due, json!(null)),
        (&with_due, json!("2026-10-20")),
    ] {
        let set =
            accepted(world.decide_with(&update("t_next", json!({"due_date": due}), 3), now, &[]));
        let clock = the_task(&set).formulation.clone().expect("a clock");
        assert_eq!(
            instant(clock.park_floor_at.as_ref()).as_deref(),
            Some("2026-10-16T14:02:00Z")
        );
        assert_eq!(clock.started_at.as_str(), "2026-09-24T09:14:00Z");
        ran += 1;
    }
    ran_all("due date changes", ran, 4);
    // The same due date is no change at all for the clock.
    let same = accepted(with_due.decide_with(
        &update("t_next", json!({"due_date": "2026-09-20"}), 3),
        now,
        &[],
    ));
    assert_eq!(
        the_task(&same).formulation,
        with_due.task("t_next").formulation
    );
    // The same due date is no change; a later existing floor is kept.
    let mut later = next_world();
    let mut row = serde_json::to_value(later.task("t_next")).unwrap();
    row["formulation"]["park_floor_at"] = json!("2026-10-30T00:00:00Z");
    later.read_set.tasks.insert(
        TaskId::parse("t_next").unwrap(),
        serde_json::from_value(row).unwrap(),
    );
    let set = accepted(later.decide_with(
        &update("t_next", json!({"due_date": "2026-10-20"}), 3),
        now,
        &[],
    ));
    let floor = the_task(&set)
        .formulation
        .as_ref()
        .unwrap()
        .park_floor_at
        .clone();
    assert_eq!(
        instant(floor.as_ref()).as_deref(),
        Some("2026-10-30T00:00:00Z")
    );
    let set = accepted(store.decide_with(
        &update("t_next", json!({"details": "n", "priority": "high"}), 3),
        now,
        &[],
    ));
    assert_eq!(the_task(&set).formulation, store.task("t_next").formulation);
}

#[test]
fn task_rules_026_fr_046_outside_next_an_edit_never_touches_the_clock() {
    let mut store = world();
    let before = store.task("t_waiting").clone();
    let set = accepted(store.run(&update(
        "t_waiting",
        json!({"title": "A different thing", "due_date": "2026-12-01"}),
        2,
    )));
    let task = the_task(&set);
    assert_eq!(task.formulation, before.formulation);
    assert_eq!(task.consecutive_stalled_formulations, 0);
}

// ------------------------------------------------------------------- transition

fn transition_payload(action: &str, to: Option<&str>, waiting_for: Option<&str>) -> Value {
    let mut payload = json!({"action": action});
    if let Some(to) = to {
        payload["to_state"] = json!(to);
        if to == "next" {
            payload["new_formulation_id"] = json!(FORM_B);
        }
    }
    if let Some(note) = waiting_for {
        payload["waiting_for"] = json!(note);
    }
    payload
}

#[test]
fn task_rules_026_fr_002_every_state_and_action_follows_the_lifecycle_matrix() {
    let open = ["inbox", "next", "waiting", "someday"];
    let closed = ["completed", "cancelled"];
    let mut ran = 0;
    let mut expect = |state: &str,
                      action: &str,
                      to: Option<&str>,
                      note: Option<&str>,
                      want: Result<&str, Reason>| {
        let store = world();
        let id = match state {
            "completed" => "t_done".to_owned(),
            other => format!("t_{other}"),
        };
        let result = store.decide(&transition(&id, transition_payload(action, to, note), 2));
        match (result, want) {
            (Ok(set), Ok(target)) => {
                let task = the_task(&set);
                assert_eq!(task.state.as_str(), target, "{state} {action} {to:?}");
                assert_eq!(revision(task), 3);
                assert_eq!(task.updated_at.as_str(), NOW);
            }
            (Err(error), Err(reason)) => {
                assert_eq!(error.reason, reason, "{state} {action} {to:?}");
            }
            (got, want) => panic!("{state} {action} {to:?}: {got:?} vs {want:?}"),
        }
        ran += 1;
    };
    for state in open {
        expect(state, "complete", None, None, Ok("completed"));
        expect(
            state,
            "complete",
            Some("next"),
            Some("ignored"),
            Ok("completed"),
        );
        expect(state, "cancel", None, None, Ok("cancelled"));
        expect(
            state,
            "reopen",
            Some("inbox"),
            None,
            Err(Reason::TaskNotClosed),
        );
        expect(
            state,
            "reopen",
            None,
            None,
            Err(Reason::ReopenRequiresDestination),
        );
        expect(
            state,
            "move",
            None,
            None,
            Err(Reason::MoveRequiresDestination),
        );
        for to in open {
            if to == state {
                expect(
                    state,
                    "move",
                    Some(to),
                    Some("Bob"),
                    Err(Reason::MoveRequiresDifferentList),
                );
            } else if to == "waiting" {
                expect(
                    state,
                    "move",
                    Some(to),
                    None,
                    Err(Reason::WaitingForRequired),
                );
                expect(
                    state,
                    "move",
                    Some(to),
                    Some("  "),
                    Err(Reason::WaitingForRequired),
                );
                expect(state, "move", Some(to), Some("Bob"), Ok(to));
            } else {
                expect(state, "move", Some(to), None, Ok(to));
                expect(state, "move", Some(to), Some("dropped"), Ok(to));
            }
        }
    }
    for state in closed {
        expect(state, "complete", None, None, Err(Reason::TaskNotOpen));
        expect(state, "cancel", None, None, Err(Reason::TaskNotOpen));
        expect(state, "move", Some("inbox"), None, Err(Reason::TaskNotOpen));
        expect(
            state,
            "move",
            None,
            None,
            Err(Reason::MoveRequiresDestination),
        );
        expect(
            state,
            "reopen",
            None,
            None,
            Err(Reason::ReopenRequiresDestination),
        );
        for to in open {
            if to == "waiting" {
                expect(
                    state,
                    "reopen",
                    Some(to),
                    None,
                    Err(Reason::WaitingForRequired),
                );
            }
            let note = (to == "waiting").then_some("Bob");
            expect(state, "reopen", Some(to), note, Ok(to));
        }
    }
    // Open states: 14 + 14 + 13 + 14 rows; completed and cancelled: 10 rows each.
    ran_all("lifecycle matrix", ran, 55 + 20);
}

#[test]
fn task_rules_026_fr_002_terminal_stamps_and_the_waiting_note_follow_the_lifecycle() {
    let mut store = world();
    let done = accepted(store.run_with(
        &transition("t_waiting", json!({"action": "complete"}), 2),
        LATER,
        &[],
    ));
    let task = the_task(&done);
    assert_eq!(task.state, TaskState::Completed);
    assert_eq!(instant(task.completed_at.as_ref()).as_deref(), Some(LATER));
    assert!(
        task.cancelled_at.is_none() && task.waiting_for.is_none() && task.waiting_since.is_none()
    );
    let reopened = accepted(store.run(&transition(
        "t_waiting",
        transition_payload("reopen", Some("waiting"), Some(" Dana ")),
        3,
    )));
    let task = the_task(&reopened);
    assert_eq!(task.state, TaskState::Waiting);
    assert!(task.completed_at.is_none() && task.cancelled_at.is_none());
    assert_eq!(
        task.waiting_for.as_ref().map(types::WaitingFor::as_str),
        Some("Dana")
    );
    assert_eq!(
        instant(task.waiting_since.as_ref()).as_deref(),
        Some(NOW),
        "a new wait starts now"
    );
    let cancelled = accepted(store.run_with(
        &transition("t_waiting", json!({"action": "cancel"}), 4),
        LATER,
        &[],
    ));
    let task = the_task(&cancelled);
    assert!(task.completed_at.is_none());
    assert_eq!(instant(task.cancelled_at.as_ref()).as_deref(), Some(LATER));
    let moved = accepted(store.run(&transition(
        "t_waiting",
        transition_payload("reopen", Some("inbox"), None),
        5,
    )));
    let task = the_task(&moved);
    assert!(task.waiting_for.is_none() && task.waiting_since.is_none());
    assert!(task.completed_at.is_none() && task.cancelled_at.is_none());
    let to_waiting = accepted(store.run(&transition(
        "t_waiting",
        transition_payload("move", Some("waiting"), Some("Eve")),
        6,
    )));
    assert!(the_task(&to_waiting).waiting_since.is_some());
    let away = accepted(store.run(&transition(
        "t_waiting",
        transition_payload("move", Some("someday"), None),
        7,
    )));
    let task = the_task(&away);
    assert!(task.waiting_for.is_none() && task.waiting_since.is_none());
    assert_eq!(revision(task), 8);
}

#[test]
fn task_rules_026_fr_009_a_transition_changes_nothing_but_the_lifecycle() {
    let mut store = world();
    let rich = with(
        task_json("t_rich", "inbox", 5),
        json!({"details": "notes", "project_id": "project_old", "due_date": "2026-11-01",
               "priority": "high", "tag_ids": ["tag_work", "tag_home"], "order_key": "9",
               "title": " Verbatim "}),
    );
    store.read_set.tasks.insert(
        TaskId::parse("t_rich").unwrap(),
        serde_json::from_value(rich).unwrap(),
    );
    let before = store.task("t_rich").clone();
    let mut revision_now = 5;
    for payload in [
        json!({"action": "complete"}),
        transition_payload("reopen", Some("someday"), None),
        transition_payload("move", Some("inbox"), None),
        json!({"action": "cancel"}),
    ] {
        let set = accepted(store.run(&transition("t_rich", payload, revision_now)));
        revision_now += 1;
        let task = the_task(&set);
        assert_eq!(revision(task), revision_now);
        let same = |field: &dyn Fn(&Task) -> String| field(task) == field(&before);
        assert!(same(&|t| format!(
            "{:?}",
            (&t.title, &t.details, &t.project_id, &t.tag_ids)
        )));
        assert!(same(&|t| format!(
            "{:?}",
            (&t.due_date, t.priority, &t.order_key, &t.created_at)
        )));
    }
}

#[test]
fn task_rules_026_fr_007_a_stale_completion_does_not_undo_a_later_reopen() {
    let mut store = world();
    // Two devices both saw revision 2 of an open task.
    let stale_complete = transition("t_inbox", json!({"action": "complete"}), 2);
    accepted(store.run(&stale_complete));
    assert_eq!(store.task("t_inbox").state, TaskState::Completed);
    let reopen = transition(
        "t_inbox",
        transition_payload("reopen", Some("next"), None),
        3,
    );
    accepted(store.run_with(&reopen, NOW, &[FORM_A]));
    assert_eq!(store.task("t_inbox").state, TaskState::Next);
    let reopened = store.task("t_inbox").clone();
    // The first device's queued completion arrives late (and twice).
    for _ in 0..2 {
        let error = refusal(store.run(&stale_complete));
        assert_eq!(error.reason, Reason::RevisionConflict);
        assert_eq!(error.current_revision, Some(Counter::from(4)));
    }
    let also_stale = transition("t_inbox", json!({"action": "complete"}), 3);
    assert_eq!(
        refusal(store.run(&also_stale)).reason,
        Reason::RevisionConflict
    );
    assert_eq!(store.task("t_inbox"), &reopened, "the reopen stands");
    // Replaying it with the current revision is a deliberate new completion.
    accepted(store.run(&transition("t_inbox", json!({"action": "complete"}), 4)));
    assert_eq!(store.task("t_inbox").state, TaskState::Completed);
    assert_eq!(revision(store.task("t_inbox")), 5);
}

#[test]
fn task_rules_026_fr_007_a_transition_needs_the_current_revision_of_an_existing_task() {
    let store = world();
    for stale in [1, 3] {
        let error =
            refusal(store.decide(&transition("t_next", json!({"action": "cancel"}), stale)));
        assert_eq!(error.reason, Reason::RevisionConflict);
        assert_eq!(error.current_revision, Some(Counter::from(2)));
    }
    let bare = command(
        "task.transition",
        "t_next",
        json!({"action": "cancel"}),
        vec![],
    );
    assert_eq!(refusal(store.decide(&bare)).reason, Reason::InvalidPayload);
    let error = refusal(store.decide(&transition("t_missing", json!({"action": "cancel"}), 1)));
    assert_eq!(error.reason, Reason::NotFound);
    // The revision is checked before the lifecycle: a stale check on a closed
    // task is a conflict, not "not open".
    let closed = refusal(store.decide(&transition("t_done", json!({"action": "complete"}), 1)));
    assert_eq!(closed.reason, Reason::RevisionConflict);
    for payload in [
        json!({"action": "archive"}),
        json!({"action": "move", "to_state": "completed"}),
        json!({"action": "move", "to_state": "next", "new_formulation_id": "form_short"}),
    ] {
        let rejected = try_command(
            "task.transition",
            "t_next",
            payload,
            vec![check("task", "t_next", 2)],
        );
        assert_eq!(rejected.unwrap_err().reason, Reason::InvalidPayload);
    }
}

#[test]
fn task_rules_026_fr_001_leaving_and_entering_next_close_and_start_the_formulation() {
    let mut store = next_world();
    let leave = |store: &mut Store, now: &str, payload: Value, rev: u64| {
        accepted(store.run_with(&transition("t_next", payload, rev), now, &[FORM_B]))
    };
    // Asking when it left (28 days in): stalled count +1, clock gone.
    let set = leave(
        &mut store,
        "2026-10-09T14:02:00Z",
        transition_payload("move", Some("waiting"), Some("Bob")),
        3,
    );
    let task = the_task(&set);
    assert!(task.formulation.is_none());
    assert_eq!(task.consecutive_stalled_formulations, 2);
    // Back to Next: a new formulation (from the allocation), the count stays.
    let back = transition("t_next", json!({"action": "move", "to_state": "next"}), 4);
    assert_eq!(
        refusal(store.decide(&back)).reason,
        Reason::FormulationIdRequired
    );
    accepted(store.run_with(&back, "2026-10-10T08:00:00Z", &[FORM_C]));
    let clock = store.task("t_next").formulation.clone().expect("a clock");
    assert_eq!(
        (clock.id.as_str(), clock.started_at.as_str()),
        (FORM_C, "2026-10-10T08:00:00Z")
    );
    assert_eq!(store.task("t_next").consecutive_stalled_formulations, 2);
    // Completing while fresh resets the count.
    let done = leave(
        &mut store,
        "2026-10-11T08:00:00Z",
        json!({"action": "complete"}),
        5,
    );
    let task = the_task(&done);
    assert!(task.formulation.is_none());
    assert_eq!(task.consecutive_stalled_formulations, 0);
}

#[test]
fn task_rules_026_fr_001_a_parked_task_returning_to_next_stamps_its_acknowledgement() {
    let parked = with(
        task_json("t_parked", "someday", 4),
        json!({"consecutive_stalled_formulations": 1, "parked": parked_json(FORM_A)}),
    );
    let build = || {
        let mut store = Store::new(&[], &[], std::slice::from_ref(&parked))
            .with_settings(&settings_json("UTC", Some("2026-09-01T08:00:00Z")));
        store.read_set.park_acks.clear();
        store
    };
    let back = transition(
        "t_parked",
        transition_payload("move", Some("next"), None),
        4,
    );
    // With the acknowledgement: the task, then the acknowledgement.
    let store = build().with_park_ack("t_parked", FORM_A);
    let set = accepted(store.decide_with(&back, "2026-10-16T08:00:00Z", &[]));
    match set.changes.as_slice() {
        [
            DomainChange::Upsert(Record::Task(task)),
            DomainChange::Upsert(Record::ReviewParkAck(ack)),
        ] => {
            assert!(task.parked.is_none());
            assert_eq!(task.formulation.as_ref().unwrap().id.as_str(), FORM_B);
            assert_eq!(task.consecutive_stalled_formulations, 1);
            assert_eq!(
                instant(ack.returned_at.as_ref()).as_deref(),
                Some("2026-10-16T08:00:00Z")
            );
            assert_eq!(
                (ack.task_id.as_str(), ack.formulation_id.as_str()),
                ("t_parked", FORM_A)
            );
            assert_eq!(ack.parked_at.as_str(), "2026-10-01T09:00:00Z");
        }
        other => panic!("expected the task and its acknowledgement, got {other:?}"),
    }
    // Without it nothing is made up; for another formulation likewise.
    for store in [build(), build().with_park_ack("t_parked", FORM_C)] {
        assert_eq!(
            accepted(store.decide_with(&back, NOW, &[FORM_B]))
                .changes
                .len(),
            1
        );
    }
    // Leaving Someday any other way drops the marker and stamps nothing.
    let store = build().with_park_ack("t_parked", FORM_A);
    let done = accepted(store.decide(&transition("t_parked", json!({"action": "complete"}), 4)));
    assert!(the_task(&done).parked.is_none());
    let inbox = accepted(store.decide(&transition(
        "t_parked",
        transition_payload("move", Some("inbox"), None),
        4,
    )));
    assert!(the_task(&inbox).parked.is_none());
}

// ----------------------------------------------- parity: formulation vectors (T013)

/// Vector ids such as `form_a` are not client-shaped; map each one to a stable
/// client-shaped id so the stored types accept it.
fn shaped(id: &str) -> String {
    let is_uuid_tail = id.len() == 41 && id.as_bytes()[13] == b'-';
    if is_uuid_tail {
        return id.to_owned();
    }
    let hash = id.bytes().fold(0xcbf2_9ce4_8422_2325_u64, |h, b| {
        (h ^ u64::from(b)).wrapping_mul(0x100_0000_01b3)
    });
    format!(
        "form_00000000-0000-4000-8000-{:012x}",
        hash & 0xffff_ffff_ffff
    )
}

fn shape_ids(value: &Value) -> Value {
    match value {
        Value::String(s) if s.starts_with("form_") => Value::String(shaped(s)),
        Value::Array(items) => Value::Array(items.iter().map(shape_ids).collect()),
        Value::Object(map) => {
            Value::Object(map.iter().map(|(k, v)| (k.clone(), shape_ids(v))).collect())
        }
        other => other.clone(),
    }
}

fn iso(value: Option<UtcInstant>) -> Value {
    value.map_or(Value::Null, |instant| Value::String(instant.to_rfc3339()))
}

/// The clock view the vectors compare: the task's stored facts through the
/// rule's own bridge.
fn clock_to(task: &Task) -> Value {
    let clock = TaskClock::from_task(task).expect("a readable task");
    let parked = clock.parked.as_ref().map_or(Value::Null, |marker| {
        let before = marker.clock_before.as_ref().expect("a stored clock");
        json!({
            "at": iso(Some(marker.at)),
            "formulation_id": marker.formulation_id,
            "from_revision": marker.from_revision,
            "clock_before": {
                "started_at": iso(Some(before.started_at)),
                "extended_at": iso(before.extended_at),
                "extension_reason": before.extension_reason,
                "park_floor_at": iso(before.park_floor_at),
                "stalled_before": before.stalled_before,
            },
        })
    });
    json!({
        "state": clock.state.map(TaskState::as_str),
        "title": clock.title,
        "revision": clock.revision,
        "formulation_id": clock.formulation_id,
        "formulation_started_at": iso(clock.formulation_started_at),
        "formulation_extended_at": iso(clock.formulation_extended_at),
        "formulation_extension_reason": clock.formulation_extension_reason,
        "formulation_park_floor_at": iso(clock.formulation_park_floor_at),
        "consecutive_stalled_formulations": clock.consecutive_stalled_formulations,
        "due_date": clock.due_date.map(|day| day.iso_string()),
        "parked": parked,
    })
}

/// A public task whose clock facts are the vector's `before`.
fn task_from_clock(before: &Value) -> Value {
    let mut row = task_json(VECTOR_TASK, before["state"].as_str().expect("a state"), 1);
    row["title"] = before["title"].clone();
    row["revision"] = json!(before["revision"].as_u64().expect("revision").to_string());
    row["due_date"] = before["due_date"].clone();
    row["consecutive_stalled_formulations"] = before["consecutive_stalled_formulations"].clone();
    row["waiting_for"] = Value::Null;
    row["waiting_since"] = Value::Null;
    if let Some(id) = before["formulation_id"].as_str() {
        row["formulation"] = json!({
            "id": id, "started_at": before["formulation_started_at"],
            "extended_at": before["formulation_extended_at"],
            "extension_reason": before["formulation_extension_reason"],
            "park_floor_at": before["formulation_park_floor_at"],
        });
    }
    if let Some(park) = before["parked"].as_object() {
        row["parked"] = json!({
            "at": park["at"], "formulation_id": park["formulation_id"],
            "private": {
                "from_revision": park["from_revision"].as_u64().expect("from_revision").to_string(),
                "clock_before": {
                    "formulation_id": park["formulation_id"],
                    "started_at": park["clock_before"]["started_at"],
                    "extended_at": park["clock_before"]["extended_at"],
                    "extension_reason": park["clock_before"]["extension_reason"],
                    "park_floor_at": park["clock_before"]["park_floor_at"],
                    "stalled_before": park["clock_before"]["stalled_before"],
                }
            }
        });
    }
    row
}

const VECTOR_EVENTS: [&str; 5] = [
    "create_in_next",
    "update_title",
    "update_due_date",
    "update_other",
    "transition",
];

fn vector_command(event: &Value, state: &str, revision: u64) -> DomainCommand {
    let id = VECTOR_TASK;
    let new_id = event.get("new_formulation_id").and_then(Value::as_str);
    match text(event, "type") {
        "create_in_next" => {
            let mut payload = json!({"title": text(event, "title"), "state": "next"});
            payload["new_formulation_id"] = json!(new_id.expect("an id"));
            create(id, payload)
        }
        "update_title" => {
            let mut payload = json!({"title": text(event, "title")});
            if let Some(id) = new_id {
                payload["new_formulation_id"] = json!(id);
            }
            update(id, payload, revision)
        }
        "update_due_date" => update(id, json!({"due_date": event["due_date"]}), revision),
        // Notes, project, priority and tags: the FR-003 edits that leave the clock alone.
        "update_other" => update(
            id,
            json!({"details": "notes", "priority": "high", "project_id": "project_live",
                   "tag_changes": {"add_tag_ids": ["tag_work"], "remove_tag_ids": []}}),
            revision,
        ),
        "transition" => {
            let to = text(event, "to");
            let payload = match (to, state) {
                ("completed", _) => json!({"action": "complete"}),
                ("cancelled", _) => json!({"action": "cancel"}),
                (_, "completed" | "cancelled") => {
                    transition_payload("reopen", Some(to), Some("Bob"))
                }
                _ => transition_payload("move", Some(to), Some("Bob")),
            };
            let mut payload = payload;
            if let Some(id) = new_id {
                payload["new_formulation_id"] = json!(id);
            }
            transition(id, payload, revision)
        }
        other => panic!("unexpected vector event {other}"),
    }
}

#[test]
fn task_rules_026_fr_001_formulation_vectors_hold_through_the_task_commands() {
    let file = support::formulation();
    let vectors = cases(file, "transitions");
    let wanted: Vec<&Value> = vectors
        .iter()
        .filter(|v| VECTOR_EVENTS.contains(&text(&v["event"], "type")))
        .collect();
    let mut ran = 0;
    for vector in &wanted {
        let vector = shape_ids(vector);
        let id = text(&vector, "id").to_owned();
        let (event, settings) = (&vector["event"], &vector["settings"]);
        let created = text(event, "type") == "create_in_next";
        let before = if created {
            json!({
                "state": null, "title": null, "revision": 1, "formulation_id": null,
                "formulation_started_at": null, "formulation_extended_at": null,
                "formulation_extension_reason": null, "formulation_park_floor_at": null,
                "consecutive_stalled_formulations": 0, "due_date": null, "parked": null
            })
        } else {
            vector["before"].clone()
        };
        let tasks = if created {
            vec![]
        } else {
            vec![task_from_clock(&before)]
        };
        let mut store = Store::new(
            &[project_json("project_live", "Live", "active")],
            &[tag_json("tag_work", "work", "active")],
            &tasks,
        )
        .with_settings(&settings_json(
            text(settings, "time_zone"),
            settings["activated_at"].as_str(),
        ));
        if let Some(days) = settings["threshold_days"].as_u64() {
            let stored = store.read_set.settings.as_mut().unwrap();
            stored.threshold_days = types::ThresholdDays::new(u8::try_from(days).unwrap()).unwrap();
        }
        let state = before["state"].as_str().unwrap_or("");
        let revision = before["revision"].as_u64().unwrap();
        let c = vector_command(event, state, revision);
        let now = text(&vector, "now");
        let result = store.run_with(&c, now, &[]);
        if let Some(code) = vector["expect"].get("error").and_then(Value::as_str) {
            panic!("{id}: the task commands have no refusal named {code}");
        }
        accepted(result);
        let after = clock_to(store.task(VECTOR_TASK));
        let mut expected = before.clone();
        for (key, value) in vector["expect"].as_object().expect("expect") {
            expected[key] = value.clone();
        }
        if created {
            expected["revision"] = json!(1);
        }
        assert_eq!(after, expected, "{id}: {}", text(&vector, "note"));
        ran += 1;
    }
    ran_all("formulation vectors", ran, wanted.len());
    assert!(ran >= 20, "ran {ran} vectors");
}

// ----------------------------------------- parity: backend traces (golden sequences)

/// A tiny server over the rules: what the traces' task requests need, with the
/// projects the traces create stored directly (their rules are another family).
struct Server {
    store: Store,
    now: UtcInstant,
    counter: u32,
}

impl Server {
    fn new(start: &str) -> Self {
        Self {
            store: Store::default(),
            now: UtcInstant::parse_rfc3339(start).unwrap(),
            counter: 0,
        }
    }

    fn mint(&mut self, prefix: &str) -> String {
        self.counter += 1;
        format!(
            "{prefix}_0b0e1f30-0000-4000-8000-{:012x}",
            0x1000 + self.counter
        )
    }

    fn settings(&self) -> OwnerClockSettings {
        match &self.store.read_set.settings {
            Some(s) => OwnerClockSettings::from_review_settings(s).unwrap(),
            None => OwnerClockSettings::new(14, "UTC", None, None).unwrap(),
        }
    }

    fn task_body(&self, task: &Task) -> Value {
        let mut body = serde_json::to_value(task).unwrap();
        body["revision"] = json!(revision(task));
        if let Some(clock) = &task.formulation {
            let mut view = serde_json::to_value(clock).unwrap();
            view["consecutive_stalled"] = json!(task.consecutive_stalled_formulations);
            if let Some(adv) = formulation::advisory_instants(task, &self.settings()).unwrap() {
                view["ageing_at"] = json!(adv.ageing_at.as_str());
                view["ask_at"] = json!(adv.ask_at.as_str());
                view["park_due_at"] = json!(adv.park_due_at.as_str());
            }
            body["formulation"] = view;
        }
        body
    }

    fn error(error: &DomainError) -> (u16, Value) {
        let status = match error.reason {
            Reason::RevisionConflict => 409,
            Reason::NotFound => 404,
            _ => 400,
        };
        let message = match error.reason {
            Reason::ProjectNotActive => "Task project must be active.".to_owned(),
            other => other.as_str().to_owned(),
        };
        (status, json!({ "message": message }))
    }

    /// `None` when the trace step is outside this family.
    fn request(&mut self, method: &str, path: &str, body: &Value) -> Option<(u16, Value)> {
        let alloc = self.mint("form");
        let now = self.now.to_rfc3339();
        let run = |server: &mut Self, c: DomainCommand| {
            server.store.run_with(&c, &now, &[alloc.as_str()])
        };
        let tail = path.strip_prefix("/api/tasks/");
        match (method, path, tail) {
            ("POST", "/api/projects", _) => {
                let id = self.mint("project");
                let row = project_json(&id, text(body, "name"), "active");
                let row = with(row, json!({"revision": "1"}));
                self.store.read_set.projects.insert(
                    ProjectId::parse(&id).unwrap(),
                    serde_json::from_value(row).unwrap(),
                );
                Some((201, json!({"id": id, "state": "active", "revision": 1})))
            }
            ("POST", "/api/review/explainer/acknowledge", _) => {
                let zone = text(body, "time_zone");
                self.store.read_set.settings = Some(
                    serde_json::from_value(settings_json(zone, Some(&self.now.to_rfc3339())))
                        .unwrap(),
                );
                Some((200, json!({"explainer_seen": true})))
            }
            ("POST", "/api/tasks", _) => {
                let id = self.mint("task");
                let c = create(&id, body.clone());
                Some(match run(self, c) {
                    Ok(set) => (201, self.task_body(the_task(&set))),
                    Err(e) => Self::error(&e),
                })
            }
            ("GET", _, Some(id)) => Some(
                match self.store.read_set.tasks.get(&TaskId::parse(id).unwrap()) {
                    Some(task) => (200, self.task_body(task)),
                    None => (404, json!({})),
                },
            ),
            ("PATCH", _, Some(id)) => {
                let mut payload = body.clone();
                let expected = payload
                    .as_object_mut()
                    .unwrap()
                    .remove("expected_revision")
                    .unwrap();
                let c = update(id, payload, expected.as_u64().unwrap());
                Some(match run(self, c) {
                    Ok(set) => (200, self.task_body(the_task(&set))),
                    Err(e) => Self::error(&e),
                })
            }
            ("POST", _, Some(rest)) if rest.ends_with("/transitions") => {
                let id = rest.trim_end_matches("/transitions");
                let mut payload = body.clone();
                let expected = payload
                    .as_object_mut()
                    .unwrap()
                    .remove("expected_revision")
                    .unwrap();
                let c = transition(id, payload, expected.as_u64().unwrap());
                Some(match run(self, c) {
                    Ok(set) => (200, self.task_body(the_task(&set))),
                    Err(e) => Self::error(&e),
                })
            }
            _ => None,
        }
    }

    fn advance(&mut self, spec: &Value) {
        let seconds = spec["days"].as_i64().unwrap_or(0) * 86_400
            + spec["hours"].as_i64().unwrap_or(0) * 3600
            + spec["minutes"].as_i64().unwrap_or(0) * 60;
        self.now = self.now.plus_seconds(seconds);
    }

    /// `_seed` of backend/tests/test_project_archive_traces.py: archive and keep the members.
    fn seed(&mut self, seed: &Value) {
        assert_eq!(text(seed, "kind"), "archive_keeping_members");
        let id = ProjectId::parse(text(seed, "project")).unwrap();
        let project = self.store.read_set.projects.get_mut(&id).unwrap();
        project.state = types::ProjectState::Archived;
        project.revision = Counter::from(project.revision.to_u64().unwrap() + 1);
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

fn trace_file(relative: &str) -> Value {
    let path = support::repo_root().join(relative);
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

/// Replays the leading steps of a trace that this family decides; the first
/// step of another family (a decision, a sweep) ends the replay. Returns the
/// number of steps replayed.
fn replay(trace: &Value, start: &str) -> usize {
    let id = text(trace, "id");
    let mut server = Server::new(start);
    let mut captured: HashMap<String, Value> = HashMap::new();
    let mut steps = 0;
    for step in trace["steps"].as_array().expect("steps") {
        if let Some(seed) = step.get("seed") {
            server.seed(&substitute(seed, &captured));
        } else if let Some(advance) = step.get("advance") {
            server.advance(advance);
        } else if let Some(request) = step.get("request") {
            let request = substitute(request, &captured);
            let name = text(step, "name");
            let Some((status, body)) = server.request(
                text(&request, "method"),
                text(&request, "path"),
                &request["body"],
            ) else {
                break;
            };
            let expect = substitute(&step["expect"], &captured);
            assert_eq!(
                i64::from(status),
                expect["status"].as_i64().unwrap(),
                "{id}: {name}: {body}"
            );
            // The acknowledgement is another family's: only its status counts.
            if !text(&request, "path").contains("/review/")
                && let Some(want) = expect.get("body")
            {
                assert_subset(want, &body, &format!("{id}: {name}"));
            }
            for (variable, path) in step["capture"].as_object().into_iter().flatten() {
                let mut node = &body;
                for key in path.as_str().expect("a path").split('.') {
                    node = &node[key];
                }
                captured.insert(variable.clone(), node.clone());
            }
        } else {
            break;
        }
        steps += 1;
    }
    steps
}

#[test]
fn task_rules_026_fr_009_the_archived_membership_trace_replays_through_the_task_rules() {
    let file = trace_file("backend/tests/fixtures/project_archive_traces.json");
    let trace = cases(&file, "traces")
        .iter()
        .find(|t| text(t, "id") == "TR-T01")
        .expect("TR-T01");
    let steps = replay(trace, "2026-10-09T12:00:00Z");
    ran_all(
        "TR-T01 steps",
        steps,
        trace["steps"].as_array().unwrap().len(),
    );
}

#[test]
fn task_rules_026_fr_001_the_review_task_traces_replay_their_create_and_edit_steps() {
    let file = trace_file("backend/tests/fixtures/review_traces_tasks.json");
    let traces = cases(&file, "traces");
    let mut replayed = 0;
    let mut steps = 0;
    for (id, minimum) in [("TR-001", 3), ("TR-002", 2), ("TR-007", 1)] {
        let trace = traces
            .iter()
            .find(|t| text(t, "id") == id)
            .expect("a trace");
        let ran = replay(trace, text(trace, "start"));
        assert!(ran >= minimum, "{id}: replayed {ran} steps");
        steps += ran;
        replayed += 1;
    }
    ran_all("review traces", replayed, 3);
    assert!(steps >= 6, "ran {steps} steps");
}

// --------------------------------------------- parity: frozen reference store (T002)

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
    Store::new(&projects, &tags, &tasks).with_settings(&settings_json(
        "Europe/Berlin",
        Some("2026-09-01T08:00:00Z"),
    ))
}

fn of_state(store: &Store, state: TaskState) -> Vec<&Task> {
    store
        .read_set
        .tasks
        .values()
        .filter(|t| t.state == state)
        .collect()
}

#[test]
fn task_rules_026_fr_002_the_reference_dataset_loads_per_owner_with_its_counts() {
    let expected = &support::reference_store()["dataset"]["expected_counts"];
    let mut ran = 0;
    for owner in [OWNER, OTHER_OWNER] {
        let store = owner_store(owner);
        let counts = &expected[owner];
        assert_eq!(store.read_set.tasks.len() as u64, counts["tasks"]);
        for (state, want) in counts["tasks_by_state"].as_object().expect("by state") {
            let state = TaskState::from_wire(state).expect("a state");
            assert_eq!(of_state(&store, state).len() as u64, want.as_u64().unwrap());
        }
        ran += 1;
    }
    ran_all("reference owners", ran, 2);
}

#[test]
fn task_rules_026_fr_002_every_reference_task_takes_its_lifecycle_actions_per_owner() {
    let mut ran = 0;
    for owner in [OWNER, OTHER_OWNER] {
        let store = owner_store(owner);
        for task in store.read_set.tasks.values() {
            let id = task.id.as_str();
            let rev = revision(task);
            let open = task.state.is_open();
            let complete = store.decide_with(
                &transition(id, json!({"action": "complete"}), rev),
                NOW,
                &[],
            );
            assert_eq!(complete.is_ok(), open, "{id} complete");
            let cancel =
                store.decide_with(&transition(id, json!({"action": "cancel"}), rev), NOW, &[]);
            assert_eq!(cancel.is_ok(), open, "{id} cancel");
            let reopen = transition(id, transition_payload("reopen", Some("inbox"), None), rev);
            assert_eq!(
                store.decide_with(&reopen, NOW, &[]).is_ok(),
                !open,
                "{id} reopen"
            );
            // Another owner's scope never sees this task: its revision check misses.
            let stale = store.decide_with(&update(id, json!({"details": "x"}), rev + 1), NOW, &[]);
            assert_eq!(refusal(stale).reason, Reason::RevisionConflict);
            let edited = accepted(store.decide_with(
                &update(id, json!({"details": "x"}), rev),
                NOW,
                &[FORM_A],
            ));
            assert_eq!(revision(the_task(&edited)), rev + 1);
            ran += 1;
        }
    }
    ran_all("reference tasks", ran, 13);
}

#[test]
fn task_rules_026_fr_009_reference_edits_keep_archived_memberships_and_check_new_references() {
    let store = owner_store(OWNER);
    // "Call the old landlord" is cancelled in an archived project.
    let member = store
        .read_set
        .tasks
        .values()
        .find(|t| {
            t.project_id
                .as_ref()
                .is_some_and(|p| store.read_set.projects[p].state == types::ProjectState::Archived)
        })
        .expect("an archived member");
    let id = member.id.as_str();
    let rev = revision(member);
    accepted(store.decide(&update(id, json!({"details": "still editable"}), rev)));
    let same = json!({"project_id": member.project_id.as_ref().unwrap().as_str()});
    accepted(store.decide(&update(id, same, rev)));
    let other_archived = store
        .read_set
        .projects
        .values()
        .find(|p| {
            p.state == types::ProjectState::Archived && Some(&p.id) != member.project_id.as_ref()
        })
        .expect("another archived project");
    let into = json!({"project_id": other_archived.id.as_str()});
    assert_eq!(
        refusal(store.decide(&update(id, into, rev))).reason,
        Reason::ProjectNotActive
    );
    // Another owner's project is not in this scope: it does not exist here.
    let foreign = owner_store(OTHER_OWNER);
    let foreign_project = foreign
        .read_set
        .projects
        .keys()
        .next()
        .unwrap()
        .as_str()
        .to_owned();
    let error = refusal(store.decide(&update(id, json!({"project_id": foreign_project}), rev)));
    assert_eq!(error.reason, Reason::NotFound);
    // The deleted reference tag cannot be added; an active one can.
    let deleted = store
        .read_set
        .tags
        .values()
        .find(|t| t.state == types::TagState::Deleted)
        .unwrap();
    let add = |tag: &str| json!({"tag_changes": {"add_tag_ids": [tag], "remove_tag_ids": []}});
    assert_eq!(
        refusal(store.decide(&update(id, add(deleted.id.as_str()), rev))).reason,
        Reason::TagNotActive
    );
    let active = store
        .read_set
        .tags
        .values()
        .find(|t| t.state == types::TagState::Active)
        .unwrap();
    let set = accepted(store.decide(&update(id, add(active.id.as_str()), rev)));
    assert!(the_task(&set).tag_ids.contains(&active.id));
}

#[test]
fn task_rules_026_fr_001_reference_next_tasks_keep_their_clock_through_non_clock_edits() {
    let store = owner_store(OWNER);
    let mut ran = 0;
    for task in of_state(&store, TaskState::Next) {
        let id = task.id.as_str();
        let rev = revision(task);
        let notes =
            accepted(store.decide(&update(id, json!({"details": "n", "priority": "low"}), rev)));
        assert_eq!(the_task(&notes).formulation, task.formulation, "{id}");
        let due = accepted(store.decide_with(
            &update(id, json!({"due_date": "2026-12-24"}), rev),
            "2026-10-09T12:00:00Z",
            &[],
        ));
        let stored = the_task(&due).formulation.as_ref();
        match &task.formulation {
            // A running clock: the task floor is now + 7 days.
            Some(_) => {
                let floor = stored.and_then(|c| c.park_floor_at.as_ref());
                assert_eq!(
                    instant(floor).as_deref(),
                    Some("2026-10-16T12:00:00Z"),
                    "{id}"
                );
            }
            // A stored floor without a running clock has no place in a public task.
            None => assert!(stored.is_none(), "{id}"),
        }
        ran += 1;
    }
    let counts = &support::reference_store()["dataset"]["expected_counts"][OWNER]["tasks_by_state"];
    ran_all(
        "reference next tasks",
        ran,
        counts["next"].as_u64().unwrap() as usize,
    );
}

#[test]
fn task_rules_026_fr_002_created_reference_tasks_continue_each_owners_order_keys() {
    let mut ran = 0;
    for owner in [OWNER, OTHER_OWNER] {
        let store = owner_store(owner);
        for list in ["inbox", "someday"] {
            let highest = of_state(&store, TaskState::from_wire(list).unwrap())
                .iter()
                .map(|t| t.order_key.to_u64().unwrap())
                .max();
            let set = accepted(store.decide(&create(
                EXTRA_TASK,
                json!({"title": "Extra", "state": list}),
            )));
            let want = highest.map_or(0, |h| h + 1);
            assert_eq!(
                the_task(&set).order_key.to_u64(),
                Some(want),
                "{owner} {list}"
            );
            ran += 1;
        }
    }
    ran_all("order keys", ran, 4);
}
