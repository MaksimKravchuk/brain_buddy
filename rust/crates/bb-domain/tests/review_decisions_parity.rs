//! Parity of the Review decision commands (`review.decide`,
//! `review.undo_decision`, `review.bulk_release`, `review.bulk_undo`) with the
//! server (tasks.md T015, PR-15).
//!
//! The oracle is the existing one, never the Rust output:
//!
//! * `review_formulation_vectors.json`: the decision, yield, decision-Undo and
//!   bulk-release transitions, and the 62 classification cases (their
//!   `restart_eligible` is the per-item bulk eligibility),
//! * `review_flow_vectors.json` (`qualifying_activity`, which a decision and its
//!   Undo recompute on the linked run),
//! * `review_traces_tasks.json` (TR-001, TR-002, TR-004, TR-006, TR-007),
//!   replayed against a small in-memory server that routes every decision and
//!   Undo request to this family and the rest to the other families,
//! * scenarios of `backend/tests/test_review_decisions_api.py` and
//!   `test_review_flow_api.py`, named in each test.
//!
//! The family sources are compiled in place (`#[path]`) with the crate paths
//! they use inside `bb-domain`, so this runner does not depend on how the
//! library registers the modules. Every data-driven test counts the cases it
//! executed, so an empty or truncated section fails.

mod support;

pub use bb_domain::{calendar, normalization, types};

#[allow(dead_code, unused_imports)]
#[path = "../src/children.rs"]
mod children;
#[allow(dead_code, unused_imports)]
#[path = "../src/formulation.rs"]
mod formulation;
#[allow(dead_code, unused_imports)]
#[path = "../src/park.rs"]
mod park;
#[allow(dead_code)]
#[path = "../src/review_decisions.rs"]
mod review_decisions;
#[allow(dead_code, unused_imports)]
#[path = "../src/task_rules.rs"]
mod task_rules;

use std::collections::{BTreeMap, BTreeSet};
use std::sync::OnceLock;

use bb_domain::calendar::{CalendarDay, UtcInstant};
use bb_protocol::command::{Decoded, decode_command};
use formulation::{OwnerClockSettings, TaskClock};
use park::{AutoPark, DeviceParkRequest, ParkReturn, ParkRow, SweepStep};
use serde_json::{Value, json};
use support::{cases, text};
use types::{
    ChangeOutcome, ChangeSet, Decision, DecisionId, DecisionType, DomainChange, DomainCommand,
    DomainError, EntityType, ExecutionInputs, ReadSet, Reason, Record, ReviewReceipt, TaskId,
    TaskState,
};

const NOW: &str = "2026-10-09T12:00:00Z";

// ------------------------------------------------------------------ identifiers

fn uuid(n: u64) -> String {
    format!("00000000-0000-4000-8000-{n:012x}")
}
fn tid(n: u64) -> String {
    format!("task_{}", uuid(n))
}
fn fid(n: u64) -> String {
    format!("form_{}", uuid(n))
}
fn did(n: u64) -> String {
    format!("decision_{}", uuid(n))
}
fn bid(n: u64) -> String {
    format!("bulk_{}", uuid(n))
}
fn sid(n: u64) -> String {
    format!("review_{}", uuid(n))
}

/// Vector files name formulations `form_a`; the typed IDs need the client shape.
/// A short label maps to a fixed, valid ID (FNV-1a), the same on both sides of
/// every comparison.
fn label(value: &str) -> String {
    if value.starts_with("form_") && value.len() < 20 {
        let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
        for byte in value.bytes() {
            hash = (hash ^ u64::from(byte)).wrapping_mul(0x0100_0000_01b3);
        }
        fid(hash & 0xffff_ffff_ffff)
    } else {
        value.to_owned()
    }
}

fn deep_label(value: &Value) -> Value {
    match value {
        Value::String(text) => Value::String(label(text)),
        Value::Array(items) => Value::Array(items.iter().map(deep_label).collect()),
        Value::Object(members) => Value::Object(
            members
                .iter()
                .map(|(key, member)| (key.clone(), deep_label(member)))
                .collect(),
        ),
        other => other.clone(),
    }
}

// ----------------------------------------------------------------------- harness

fn inputs_with(now: &str, allocated: &[String], authoritative: bool) -> ExecutionInputs {
    serde_json::from_value(json!({
        "rule_version": 1,
        "now": now,
        "time_zone": "UTC",
        "origin": "device",
        "actor_id": "actor-example",
        "authoritative": authoritative,
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

fn check(entity_type: &str, id: &str, revision: u64) -> Value {
    json!({ "entity_type": entity_type, "entity_id": id, "edit_revision": revision.to_string() })
}

fn try_command(
    kind: &str,
    entity: &str,
    payload: Value,
    checks: Vec<Value>,
) -> Result<DomainCommand, DomainError> {
    let envelope = json!({
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
    .to_string();
    match decode_command(&envelope) {
        Ok(Decoded::Executable(envelope)) => {
            DomainCommand::from_envelope(&envelope, &bb_domain::types::NoReceipts)
        }
        other => panic!("{kind} did not decode as an executable command: {other:?}"),
    }
}

fn command(kind: &str, entity: &str, payload: Value, checks: Vec<Value>) -> DomainCommand {
    try_command(kind, entity, payload, checks).unwrap_or_else(|e| panic!("{kind}: {e}"))
}

/// `review.decide` on task `task` at `revision`; `decision` is its client ID.
fn decide_command(
    task: &str,
    decision: &str,
    kind: &str,
    extra: Value,
    revision: u64,
) -> DomainCommand {
    let mut payload = json!({ "decision_id": decision, "type": kind });
    for (key, value) in extra.as_object().expect("extra fields") {
        payload[key] = value.clone();
    }
    command(
        "review.decide",
        task,
        payload,
        vec![check("task", task, revision)],
    )
}

fn undo_command(decision: &str, task: &str, task_revision: u64) -> DomainCommand {
    command(
        "review.undo_decision",
        decision,
        json!({}),
        vec![check("task", task, task_revision)],
    )
}

fn bulk_command(
    bulk: &str,
    kind: &str,
    items: &[(&str, u64)],
    session: Option<&str>,
) -> DomainCommand {
    let items: Vec<Value> = items
        .iter()
        .map(|(task, revision)| json!({ "task_id": task, "expected_revision": revision.to_string() }))
        .collect();
    let mut payload = json!({ "kind": kind, "items": items });
    if let Some(session) = session {
        payload["session_id"] = json!(session);
    }
    command("review.bulk_release", bulk, payload, vec![])
}

fn bulk_undo_command(bulk: &str) -> DomainCommand {
    command("review.bulk_undo", bulk, json!({}), vec![])
}

fn with(mut row: Value, patch: Value) -> Value {
    for (key, value) in patch.as_object().expect("a patch object") {
        row[key] = value.clone();
    }
    row
}

fn task_json(id: &str, state: &str, revision: u64) -> Value {
    json!({
        "id": id, "title": "Call Bob", "details": null, "state": state,
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

fn formulation_json(id: &str, started: &str) -> Value {
    json!({ "id": id, "started_at": started, "extended_at": null,
            "extension_reason": null, "park_floor_at": null })
}

/// A Next task `n` with a running formulation started at `started`.
fn next_json(n: u64, revision: u64, started: &str) -> Value {
    with(
        task_json(&tid(n), "next", revision),
        json!({ "formulation": formulation_json(&fid(n), started) }),
    )
}

fn project_json(id: &str, state: &str) -> Value {
    json!({
        "id": id, "name": format!("Project {id}"), "color": null, "state": state,
        "revision": "2", "desired_outcome": null,
        "archived_at": if state == "archived" { json!("2026-09-01T09:00:00Z") } else { Value::Null },
        "archived_before_lossless": false
    })
}

fn settings_json(activated: Option<&str>) -> Value {
    json!({
        "threshold_days": 14, "review_weekday": 5, "review_time": "16:00", "time_zone": "UTC",
        "onboarded_at": null, "activated_at": activated, "owner_park_floor_at": null,
        "revision": "2"
    })
}

fn session_json(n: u64, status: &str) -> Value {
    json!({
        "id": sid(n), "mode": "quick", "entry": "list", "origin": "web", "status": status,
        "started_at": "2026-10-09T09:00:00Z", "last_activity_at": "2026-10-09T09:30:00Z",
        "ended_at": null, "current_step": "decisions",
        "steps": {"wins": "finished", "inbox": "pending", "decisions": "pending", "summary": "pending"},
        "active_seconds_by_step": {},
        "counts": {"done": 0, "reformulated": 0, "first_step": 0, "waiting": 0, "someday": 0,
                   "cancelled": 0, "extended": 0, "inbox_processed": 0, "kept": 0, "moved_to_next": 0},
        "set_aside_count": 0, "qualifying_activity": false, "clear_start": null, "revision": "4"
    })
}

fn keyed(rows: &[Value]) -> Value {
    Value::Object(
        rows.iter()
            .map(|row| (row["id"].as_str().expect("id").to_owned(), row.clone()))
            .collect(),
    )
}

fn id_of(task: &Value) -> TaskId {
    TaskId::parse(task["id"].as_str().expect("task id")).expect("task id")
}

// ------------------------------------------------------------------------ store

/// One owner's protected read set and the way a change set lands in it.
#[derive(Clone)]
struct Store {
    read_set: ReadSet,
    authoritative: bool,
}

impl Store {
    fn new(tasks: &[Value]) -> Self {
        let read_set = serde_json::from_value(json!({
            "tasks": keyed(tasks),
            "settings": settings_json(Some("2026-08-01T00:00:00Z")),
        }))
        .unwrap_or_else(|e| panic!("read set: {e}"));
        Self {
            read_set,
            authoritative: true,
        }
    }

    fn put(mut self, field: &str, rows: Vec<Value>) -> Self {
        let mut value = serde_json::to_value(&self.read_set).expect("read set JSON");
        match field {
            "receipts" | "park_acks" => value[field] = Value::Array(rows),
            _ => value[field] = keyed(&rows),
        }
        self.read_set = serde_json::from_value(value).unwrap_or_else(|e| panic!("{field}: {e}"));
        self
    }

    fn with_projects(self, rows: Vec<Value>) -> Self {
        self.put("projects", rows)
    }
    fn with_sessions(self, rows: Vec<Value>) -> Self {
        self.put("sessions", rows)
    }

    fn device(mut self) -> Self {
        self.authoritative = false;
        self
    }

    fn decide_at(
        &self,
        command: &DomainCommand,
        now: &str,
        allocated: &[String],
    ) -> Result<ChangeSet, DomainError> {
        review_decisions::decide(
            &self.read_set,
            command,
            &inputs_with(now, allocated, self.authoritative),
        )
    }

    fn decide(&self, command: &DomainCommand) -> Result<ChangeSet, DomainError> {
        self.decide_at(command, NOW, &[])
    }

    /// Decides and, when accepted, lands the changes in application order.
    fn run_at(
        &mut self,
        command: &DomainCommand,
        now: &str,
        allocated: &[String],
    ) -> Result<ChangeSet, DomainError> {
        let set = self.decide_at(command, now, allocated)?;
        self.land(&set);
        Ok(set)
    }

    fn run(&mut self, command: &DomainCommand) -> Result<ChangeSet, DomainError> {
        self.run_at(command, NOW, &[])
    }

    fn land(&mut self, set: &ChangeSet) {
        for change in &set.changes {
            let read_set = &mut self.read_set;
            match change {
                DomainChange::Upsert(Record::Task(task)) => {
                    read_set.tasks.insert(task.id.clone(), task.clone());
                }
                DomainChange::Upsert(Record::ReviewDecision(decision)) => {
                    read_set
                        .decisions
                        .insert(decision.id.clone(), decision.clone());
                }
                DomainChange::Upsert(Record::ReviewSession(session)) => {
                    read_set
                        .sessions
                        .insert(session.id.clone(), session.clone());
                }
                DomainChange::Upsert(Record::ReviewBulkRelease(release)) => {
                    read_set
                        .bulk_releases
                        .insert(release.id.clone(), release.clone());
                }
                DomainChange::Upsert(Record::ReviewReceipt(receipt)) => {
                    read_set
                        .receipts
                        .retain(|r| !(r.task_id == receipt.task_id && r.kind == receipt.kind));
                    read_set.receipts.push(receipt.clone());
                }
                DomainChange::Upsert(Record::ReviewParkAck(ack)) => {
                    read_set.park_acks.retain(|a| {
                        !(a.task_id == ack.task_id && a.formulation_id == ack.formulation_id)
                    });
                    read_set.park_acks.push(ack.clone());
                }
                DomainChange::Tombstone {
                    entity_type: EntityType::Task,
                    record_key,
                } => {
                    read_set
                        .tasks
                        .remove(&TaskId::parse(&record_key[0]).expect("task id"));
                }
                DomainChange::Tombstone {
                    entity_type: EntityType::ReviewDecision,
                    record_key,
                } => {
                    read_set
                        .decisions
                        .remove(&DecisionId::parse(&record_key[0]).expect("decision id"));
                }
                DomainChange::Tombstone {
                    entity_type: EntityType::ReviewReceipt,
                    record_key,
                } => {
                    read_set.receipts.retain(|r| {
                        !(r.task_id.as_str() == record_key[0] && r.kind.as_str() == record_key[1])
                    });
                }
                other => panic!("an unexpected change {other:?}"),
            }
        }
    }

    fn task(&self, id: &str) -> &types::Task {
        &self.read_set.tasks[&TaskId::parse(id).expect("task id")]
    }

    fn has_task(&self, id: &str) -> bool {
        self.read_set
            .tasks
            .contains_key(&TaskId::parse(id).expect("task id"))
    }

    fn decision(&self, id: &str) -> Option<&Decision> {
        self.read_set
            .decisions
            .get(&DecisionId::parse(id).expect("decision id"))
    }

    fn receipt(&self, task: &str, kind: &str) -> Option<&ReviewReceipt> {
        self.read_set
            .receipts
            .iter()
            .find(|r| r.task_id.as_str() == task && r.kind.as_str() == kind)
    }

    fn session(&self, n: u64) -> &types::ReviewSession {
        &self.read_set.sessions[&types::SessionId::parse(sid(n)).expect("session id")]
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

fn tasks_in(set: &ChangeSet) -> Vec<&types::Task> {
    set.changes
        .iter()
        .filter_map(|change| match change {
            DomainChange::Upsert(Record::Task(task)) => Some(task),
            _ => None,
        })
        .collect()
}

fn the_task(set: &ChangeSet) -> &types::Task {
    match tasks_in(set).as_slice() {
        [task] => task,
        other => panic!("expected exactly one task change, got {other:?}"),
    }
}

fn the_decision(set: &ChangeSet) -> &Decision {
    let found: Vec<&Decision> = set
        .changes
        .iter()
        .filter_map(|change| match change {
            DomainChange::Upsert(Record::ReviewDecision(decision)) => Some(decision),
            _ => None,
        })
        .collect();
    match found.as_slice() {
        [decision] => decision,
        other => panic!("expected exactly one decision, got {other:?}"),
    }
}

fn the_release(set: &ChangeSet) -> &types::BulkRelease {
    set.changes
        .iter()
        .find_map(|change| match change {
            DomainChange::Upsert(Record::ReviewBulkRelease(release)) => Some(release),
            _ => None,
        })
        .expect("a bulk release record")
}

fn at(iso: &str) -> UtcInstant {
    UtcInstant::parse_rfc3339(iso).unwrap_or_else(|error| panic!("{iso}: {error}"))
}

fn iso(instant: UtcInstant) -> String {
    instant.to_rfc3339()
}

// -------------------------------------------------------------- vector -> state

/// A stored task for a vector clock (`before`), formulation labels mapped to
/// valid IDs. A started clock without an explicit ID gets the default.
fn task_from_vector(before: &Value, id: &str) -> types::Task {
    let before = deep_label(before);
    let default_form = fid(0xd0);
    let started = before["formulation_started_at"].clone();
    let form_id = before
        .get("formulation_id")
        .map_or_else(|| json!(default_form), Clone::clone);
    let formulation = if started.is_null() {
        Value::Null
    } else {
        json!({
            "id": form_id,
            "started_at": started,
            "extended_at": before["formulation_extended_at"],
            "extension_reason": before["formulation_extension_reason"],
            "park_floor_at": before["formulation_park_floor_at"],
        })
    };
    let parked = before
        .get("parked")
        .filter(|value| !value.is_null())
        .map_or(Value::Null, |parked| {
            json!({
                "at": parked["at"],
                "formulation_id": parked["formulation_id"],
                "private": {
                    "from_revision": parked["from_revision"].as_u64().expect("from_revision").to_string(),
                    "clock_before": {
                        "formulation_id": parked["formulation_id"],
                        "started_at": parked["clock_before"]["started_at"],
                        "extended_at": parked["clock_before"]["extended_at"],
                        "extension_reason": parked["clock_before"]["extension_reason"],
                        "park_floor_at": parked["clock_before"]["park_floor_at"],
                        "stalled_before": parked["clock_before"]["stalled_before"],
                    }
                }
            })
        });
    let state = before["state"].as_str().expect("a state");
    let row = with(
        task_json(
            id,
            state,
            before.get("revision").and_then(Value::as_u64).unwrap_or(1),
        ),
        json!({
            "title": before.get("title").cloned().unwrap_or(json!("Call Bob")),
            "due_date": before.get("due_date").cloned().unwrap_or(Value::Null),
            "consecutive_stalled_formulations":
                before.get("consecutive_stalled_formulations").cloned().unwrap_or(json!(0)),
            "formulation": formulation,
            "parked": parked,
        }),
    );
    serde_json::from_value(row).unwrap_or_else(|e| panic!("task {before}: {e}"))
}

fn settings_from_vector(raw: &Value) -> Value {
    json!({
        "threshold_days": raw["threshold_days"], "review_weekday": 5, "review_time": "16:00",
        "time_zone": raw["time_zone"], "onboarded_at": null,
        "activated_at": raw["activated_at"], "owner_park_floor_at": raw["owner_park_floor_at"],
        "revision": "2"
    })
}

fn store_of(task: &types::Task, settings: &Value) -> Store {
    let mut store = Store::new(&[]);
    store.read_set.settings =
        Some(serde_json::from_value(settings_from_vector(settings)).expect("settings"));
    store.read_set.tasks.insert(task.id.clone(), task.clone());
    store
}

/// The rule's flat view of a stored task, as the vector `expect` blocks spell it.
fn clock_view(task: &types::Task) -> Value {
    let clock = TaskClock::from_task(task).expect("a readable task");
    let instant = |value: Option<UtcInstant>| value.map_or(Value::Null, |i| json!(iso(i)));
    let parked = clock.parked.as_ref().map_or(Value::Null, |marker| {
        let before = marker.clock_before.as_ref().expect("a stored clock");
        json!({
            "at": iso(marker.at),
            "formulation_id": marker.formulation_id,
            "from_revision": marker.from_revision,
            "clock_before": {
                "started_at": iso(before.started_at),
                "extended_at": instant(before.extended_at),
                "extension_reason": before.extension_reason,
                "park_floor_at": instant(before.park_floor_at),
                "stalled_before": before.stalled_before,
            },
        })
    });
    json!({
        "state": clock.state.map(TaskState::as_str),
        "title": clock.title,
        "revision": clock.revision,
        "formulation_id": clock.formulation_id,
        "formulation_started_at": instant(clock.formulation_started_at),
        "formulation_extended_at": instant(clock.formulation_extended_at),
        "formulation_extension_reason": clock.formulation_extension_reason,
        "formulation_park_floor_at": instant(clock.formulation_park_floor_at),
        "consecutive_stalled_formulations": clock.consecutive_stalled_formulations,
        "due_date": clock.due_date.map(|day| day.iso_string()),
        "parked": parked,
    })
}

/// Every key listed in `expect` equals the same key of `actual`.
fn assert_subset(expect: &Value, actual: &Value, id: &str) {
    for (key, wanted) in expect.as_object().expect("an expect object") {
        assert_eq!(&actual[key], wanted, "{id}: {key}");
    }
}

fn ran_all(section: &str, ran: usize, expected: usize) {
    assert!(ran > 0, "{section}: no case executed");
    assert_eq!(
        ran, expected,
        "{section}: executed cases differ from the file"
    );
}

fn transitions_of(kind: &str) -> Vec<&'static Value> {
    let found: Vec<_> = cases(support::formulation(), "transitions")
        .iter()
        .filter(|vector| text(&vector["event"], "type") == kind)
        .collect();
    assert!(!found.is_empty(), "no {kind} vector in the file");
    found
}

const VECTOR_TASK: &str = "task_vector";

// ------------------------------------------------ formulation vectors, decision layer

#[test]
fn review_decisions_026_fr_016_decide_vectors_match_the_server() {
    let section = transitions_of("decide");
    let mut ran = 0;
    for vector in &section {
        let id = text(vector, "id");
        let event = deep_label(&vector["event"]);
        let task = task_from_vector(&vector["before"], VECTOR_TASK);
        let store = store_of(&task, &vector["settings"]);
        let kind = text(&event, "decision_type");
        let mut extra = json!({});
        for key in ["title", "reason", "waiting_for", "new_formulation_id"] {
            if let Some(value) = event.get(key) {
                extra[key] = value.clone();
            }
        }
        // The types that decide on a formulation name it; a task outside Next
        // has none, so a stand-in is named and the list check refuses first.
        if matches!(
            kind,
            "reformulate" | "first_step" | "waiting" | "someday" | "extend"
        ) {
            extra["formulation_id"] = task
                .formulation
                .as_ref()
                .map_or_else(|| json!(fid(0xe0)), |clock| json!(clock.id.as_str()));
        }
        let revision = vector["before"]["revision"].as_u64().expect("revision");
        let command = decide_command(VECTOR_TASK, &did(1), kind, extra, revision);
        let result = store.decide_at(&command, text(vector, "now"), &[]);
        let expect = &vector["expect"];
        if let Some(error) = expect.get("error") {
            let refused = refusal(result);
            assert_eq!(
                refused.reason.as_str(),
                error.as_str().expect("an error"),
                "{id}"
            );
        } else {
            let set = accepted(result);
            assert_subset(&deep_label(expect), &clock_view(the_task(&set)), id);
            let decision = the_decision(&set);
            assert_eq!(
                decision.task_revision_before.to_u64(),
                Some(revision),
                "{id}"
            );
            assert_eq!(
                decision.task_revision_after.to_u64(),
                the_task(&set).revision.to_u64(),
                "{id}"
            );
            assert_eq!(
                decision.review_counts_as,
                review_decisions::counts_as(decision.decision_type),
                "{id}"
            );
        }
        ran += 1;
    }
    ran_all("decide", ran, section.len());
}

#[test]
fn review_decisions_026_fr_016_yield_reversal_vectors_match_the_server() {
    let section = transitions_of("yield_reversal");
    let mut ran = 0;
    for vector in &section {
        let id = text(vector, "id");
        let event = deep_label(&vector["event"]["decision"]);
        let task = task_from_vector(&vector["before"], VECTOR_TASK);
        let store = store_of(&task, &vector["settings"]);
        let marker = task.parked.as_ref().expect("a parked task");
        let private = marker.private.as_ref().expect("a private park");
        let kind = text(&event, "decision_type");
        let mut extra = json!({
            "formulation_id": marker.formulation_id.as_str(),
            // A decision made one second before the park: the card the person saw.
            "client_decided_at": iso(at(marker.at.as_str()).plus_seconds(-1)),
        });
        for key in ["title", "reason", "waiting_for", "new_formulation_id"] {
            if let Some(value) = event.get(key) {
                extra[key] = value.clone();
            }
        }
        let from_revision = private.from_revision.to_u64().expect("from_revision");
        let command = decide_command(VECTOR_TASK, &did(1), kind, extra, from_revision);
        let set = accepted(store.decide_at(&command, text(vector, "now"), &[]));
        assert_subset(
            &deep_label(&vector["expect"]),
            &clock_view(the_task(&set)),
            id,
        );
        let decision = the_decision(&set);
        assert!(decision.yielded_auto_park, "{id}");
        // The decision starts from the restored task: the parked revision.
        assert_eq!(
            decision.task_revision_before.to_u64(),
            vector["before"]["revision"].as_u64(),
            "{id}"
        );
        let snapshot = &decision
            .private
            .as_ref()
            .expect("an Undo snapshot")
            .task_before;
        assert_eq!(snapshot.state, TaskState::Next, "{id}");
        assert!(snapshot.parked.is_none(), "{id}");
        ran += 1;
    }
    ran_all("yield_reversal", ran, section.len());
}

/// A decision whose Undo snapshot is `task_before`, over the task as it stands.
fn undo_store(vector: &Value, task_before: &types::Task) -> (Store, String) {
    let task = task_from_vector(&vector["before"], VECTOR_TASK);
    let mut store = store_of(&task, &vector["settings"]);
    let now = at(text(vector, "now"));
    let decision = serde_json::from_value::<Decision>(json!({
        "id": did(7), "type": "waiting", "task_id": VECTOR_TASK, "session_id": null,
        "decided_at": iso(now.plus_seconds(-60)), "substantive": null, "stall_reason": null,
        "ai_use": "none", "yielded_auto_park": false, "formulation_id": null,
        "task_revision_before": task_before.revision.as_str(),
        "task_revision_after": task.revision.as_str(),
        "created_task_id": null, "navigator_request_id": null,
        "review_counts_as": "waiting", "client_decided_at": null, "reason_text": null,
        "undo_available_until": iso(now.plus_seconds(7 * 86_400 - 60)),
        "private": {"task_before": task_before, "created_task_revision": null, "receipt_kind": null}
    }))
    .expect("a decision");
    store
        .read_set
        .decisions
        .insert(decision.id.clone(), decision);
    (store, did(7))
}

#[test]
fn review_decisions_026_fr_016_undo_decision_vectors_match_the_server() {
    let section = transitions_of("undo_decision");
    let mut ran = 0;
    for vector in &section {
        let id = text(vector, "id");
        let snapshot = task_from_vector(&vector["event"]["task_before"], VECTOR_TASK);
        let (store, decision) = undo_store(vector, &snapshot);
        let revision = vector["before"]["revision"].as_u64().expect("revision");
        let set = accepted(store.decide_at(
            &undo_command(&decision, VECTOR_TASK, revision),
            text(vector, "now"),
            &[],
        ));
        assert_subset(
            &deep_label(&vector["expect"]),
            &clock_view(the_task(&set)),
            id,
        );
        assert!(
            set.changes.iter().any(|change| matches!(
                change,
                DomainChange::Tombstone {
                    entity_type: EntityType::ReviewDecision,
                    ..
                }
            )),
            "{id}: the decision is deleted with the Undo"
        );
        ran += 1;
    }
    ran_all("undo_decision", ran, section.len());
}

#[test]
fn review_decisions_026_fr_016_undoing_a_yielded_decision_restores_the_reversed_task() {
    // T-044 then T-045: the Undo of a yielded decision restores the task as it
    // was after the reversal (FR-048), not the parked one.
    let yielded = transitions_of("yield_reversal")
        .into_iter()
        .find(|vector| text(vector, "id") == "T-044")
        .expect("T-044");
    let undo = transitions_of("undo_decision")
        .into_iter()
        .find(|vector| text(vector, "id") == "T-045")
        .expect("T-045");
    let task = task_from_vector(&yielded["before"], VECTOR_TASK);
    let mut store = store_of(&task, &yielded["settings"]);
    let marker = task.parked.as_ref().expect("parked");
    let command = decide_command(
        VECTOR_TASK,
        &did(1),
        "waiting",
        json!({
            "formulation_id": marker.formulation_id.as_str(),
            "waiting_for": "Ann",
            "client_decided_at": iso(at(marker.at.as_str()).plus_seconds(-1)),
        }),
        3,
    );
    let decided = accepted(store.run_at(&command, text(yielded, "now"), &[]));
    assert_eq!(the_task(&decided).revision.to_u64(), Some(5));
    let back = accepted(store.run_at(
        &undo_command(&did(1), VECTOR_TASK, 5),
        text(undo, "now"),
        &[],
    ));
    assert_subset(
        &deep_label(&undo["expect"]),
        &clock_view(the_task(&back)),
        "T-045",
    );
}

fn released_clock_json(raw: &Value) -> Value {
    json!({
        "formulation_id": raw["formulation_id"], "started_at": raw["started_at"],
        "extended_at": raw["extended_at"], "extension_reason": raw["extension_reason"],
        "park_floor_at": raw["park_floor_at"], "stalled_before": raw["stalled_before"],
    })
}

#[test]
fn review_decisions_026_fr_016_bulk_release_vectors_match_the_server() {
    let section = transitions_of("bulk_release");
    let mut ran = 0;
    for vector in &section {
        let id = text(vector, "id");
        let task = task_from_vector(&vector["before"], VECTOR_TASK);
        let store = store_of(&task, &vector["settings"]);
        let revision = vector["before"]["revision"].as_u64().expect("revision");
        let set = accepted(store.decide_at(
            &bulk_command(&bid(1), "restart", &[(VECTOR_TASK, revision)], None),
            text(vector, "now"),
            &[],
        ));
        let expect = deep_label(&vector["expect"]);
        assert_subset(
            &json!({
                "state": expect["state"], "revision": expect["revision"],
                "formulation_id": expect["formulation_id"],
                "formulation_started_at": expect["formulation_started_at"],
                "consecutive_stalled_formulations": expect["consecutive_stalled_formulations"],
                "parked": expect["parked"],
            }),
            &clock_view(the_task(&set)),
            id,
        );
        // The record keeps the clock before, so the Undo restores it exactly.
        let release = the_release(&set);
        let stored = release.released[0]
            .private
            .as_ref()
            .expect("an authoritative record");
        assert_eq!(stored.previous_state, types::OpenList::Next, "{id}");
        let stored =
            serde_json::to_value(stored.clock_before.as_ref().expect("a clock")).expect("JSON");
        assert_eq!(
            stored,
            released_clock_json(&expect["bulk_clock_before"]),
            "{id}"
        );
        assert_eq!(set.result.released.len(), 1, "{id}");
        assert!(set.result.skipped.is_empty(), "{id}");
        ran += 1;
    }
    ran_all("bulk_release", ran, section.len());
}

#[test]
fn review_decisions_026_fr_016_undo_bulk_release_vectors_match_the_server() {
    let section = transitions_of("undo_bulk_release");
    let mut ran = 0;
    for vector in &section {
        let id = text(vector, "id");
        let event = deep_label(&vector["event"]);
        let task = task_from_vector(&vector["before"], VECTOR_TASK);
        let mut store = store_of(&task, &vector["settings"]);
        let now = at(text(vector, "now"));
        let release: types::BulkRelease = serde_json::from_value(json!({
            "id": bid(1), "kind": "restart", "session_id": null,
            "created_at": iso(now.plus_seconds(-30)), "undone_at": null,
            "released": [{
                "task_id": VECTOR_TASK, "revision_after": task.revision.as_str(),
                "private": {"previous_state": event["previous_state"], "clock_before": event["clock_before"]}
            }],
            "skipped": [], "undo": null
        }))
        .expect("a bulk release");
        store
            .read_set
            .bulk_releases
            .insert(release.id.clone(), release);
        let set = accepted(store.decide_at(&bulk_undo_command(&bid(1)), text(vector, "now"), &[]));
        assert_subset(
            &deep_label(&vector["expect"]),
            &clock_view(the_task(&set)),
            id,
        );
        let undo = set.result.bulk_undo.as_ref().expect("an Undo result");
        assert_eq!(undo.restored.len(), 1, "{id}");
        assert!(undo.skipped.is_empty(), "{id}");
        ran += 1;
    }
    ran_all("undo_bulk_release", ran, section.len());
}

#[test]
fn review_decisions_026_fr_016_restart_eligibility_of_every_classification_case_is_the_per_item_rule()
 {
    let section = cases(support::formulation(), "classification");
    let mut ran = 0;
    let mut released = 0;
    for vector in section {
        let id = text(vector, "id");
        let task = task_from_vector(&vector["task"], VECTOR_TASK);
        let store = store_of(&task, &vector["settings"]);
        let now = text(vector, "now");
        let eligible = vector["expect"]["restart_eligible"]
            .as_bool()
            .expect("restart_eligible");
        let revision = task.revision.to_u64().expect("revision");
        let set = accepted(store.decide_at(
            &bulk_command(&bid(1), "restart", &[(VECTOR_TASK, revision)], None),
            now,
            &[],
        ));
        let release = the_release(&set);
        if eligible {
            assert_eq!(release.released.len(), 1, "{id}: released");
            assert!(release.skipped.is_empty(), "{id}");
            released += 1;
            // The same item at another revision is stale, not ineligible.
            let stale = accepted(store.decide_at(
                &bulk_command(&bid(2), "restart", &[(VECTOR_TASK, revision + 1)], None),
                now,
                &[],
            ));
            assert_eq!(
                the_release(&stale).skipped[0].reason,
                types::SkipReason::Stale,
                "{id}"
            );
            assert!(tasks_in(&stale).is_empty(), "{id}: nothing moved");
        } else {
            assert!(release.released.is_empty(), "{id}: skipped");
            assert_eq!(
                release.skipped[0].reason,
                types::SkipReason::NotEligible,
                "{id}"
            );
        }
        ran += 1;
    }
    ran_all("classification", ran, section.len());
    assert!(released > 0, "no classification case released a task");
}

// --------------------------------------------------- review_flow_vectors.json

#[test]
fn review_decisions_026_fr_016_qualifying_activity_vectors_hold_on_the_linked_run() {
    let section = cases(support::flow(), "qualifying_activity");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        let decisions = case["item_decisions"].as_u64().expect("item_decisions");
        let steps = case["steps"].as_object().expect("steps");
        let finished_empty: Vec<&str> = steps
            .iter()
            .filter(|(_, step)| step["finished_empty"] == true)
            .map(|(code, _)| code.as_str())
            .collect();
        let statuses: BTreeMap<&str, &str> = steps
            .iter()
            .map(|(code, step)| (code.as_str(), step["status"].as_str().expect("status")))
            .collect();
        let run = |done: u64| {
            let mut row = session_json(1, "open");
            row["counts"]["done"] = json!(done);
            row["steps"] = json!(statuses);
            row["private"] = json!({"applied_progress": {}, "finished_empty": finished_empty});
            row
        };
        let mut store = Store::new(&[next_json(1, 1, "2026-10-01T09:00:00Z")])
            .with_sessions(vec![run(decisions.saturating_sub(1))]);
        let payload = json!({"session_id": sid(1)});
        let decided =
            accepted(store.run(&decide_command(&tid(1), &did(1), "complete", payload, 1)));
        let session = match decided.changes.last() {
            Some(DomainChange::Upsert(Record::ReviewSession(session))) => session.clone(),
            other => panic!("{id}: no session change, got {other:?}"),
        };
        if decisions >= 1 {
            assert_eq!(session.qualifying_activity, case["expect"] == true, "{id}");
        } else {
            // Nothing decided: the one decision is taken back again.
            let mut store = store;
            store.read_set.sessions.insert(session.id.clone(), {
                let mut zero = serde_json::to_value(&session).expect("JSON");
                zero["counts"]["done"] = json!(1);
                serde_json::from_value(zero).expect("session")
            });
            let undone = accepted(store.run(&undo_command(&did(1), &tid(1), 2)));
            let Some(DomainChange::Upsert(Record::ReviewSession(back))) = undone.changes.last()
            else {
                panic!("{id}: no session change");
            };
            assert_eq!(back.counts.done, 0, "{id}");
            assert_eq!(back.qualifying_activity, case["expect"] == true, "{id}");
        }
        ran += 1;
    }
    ran_all("qualifying_activity", ran, section.len());
}

// ------------------------------------------------------------- the in-memory server

/// What `ReviewService` and `TaskService` do with a request, reduced to the
/// routes the traces use. Every decision and Undo goes through
/// `review_decisions`; the rest goes to the formulation clock and the park rules
/// as in `park_parity.rs`.
struct Sim {
    now: UtcInstant,
    exposed: bool,
    settings: OwnerClockSettings,
    settings_revision: u64,
    last_sweep: Option<UtcInstant>,
    tasks: BTreeMap<String, SimTask>,
    rows: BTreeMap<(String, String), ParkRow>,
    keys: BTreeSet<String>,
    decisions: BTreeMap<DecisionId, Decision>,
    receipts: Vec<ReviewReceipt>,
    next_id: u32,
    out_of_scope: Vec<String>,
}

struct SimTask {
    clock: TaskClock,
    details: Option<String>,
    waiting_for: Option<String>,
}

struct Reply {
    status: u16,
    body: Value,
}

fn reply(status: u16, body: Value) -> Reply {
    Reply { status, body }
}

impl Sim {
    fn new(start: &str, exposed: bool) -> Self {
        Self {
            now: at(start),
            exposed,
            settings: OwnerClockSettings::new(14, "UTC", None, None).expect("settings"),
            settings_revision: 1,
            last_sweep: None,
            tasks: BTreeMap::new(),
            rows: BTreeMap::new(),
            keys: BTreeSet::new(),
            decisions: BTreeMap::new(),
            receipts: Vec::new(),
            next_id: 0,
            out_of_scope: Vec::new(),
        }
    }

    fn string(value: &Value) -> Option<String> {
        value.as_str().map(str::to_owned)
    }

    fn view(&self, id: &str) -> Value {
        let task = &self.tasks[id];
        let clock = &task.clock;
        let instants = formulation::derive_instants(clock, &self.settings);
        let formulation = clock
            .formulation_id
            .as_ref()
            .map_or(Value::Null, |formulation_id| {
                json!({
                    "id": formulation_id,
                    "started_at": clock.formulation_started_at.map(iso),
                    "ask_at": instants.map(|i| iso(i.ask_at)),
                    "park_due_at": instants.map(|i| iso(i.park_due_at)),
                    "consecutive_stalled": clock.consecutive_stalled_formulations,
                })
            });
        json!({
            "id": id,
            "title": clock.title,
            "state": clock.state.map(TaskState::as_str),
            "revision": clock.revision,
            "details": task.details,
            "waiting_for": task.waiting_for,
            "formulation": formulation,
            "parked": clock.parked.as_ref().map(|marker| json!({
                "at": iso(marker.at),
                "formulation_id": marker.formulation_id,
            })),
        })
    }

    fn advance(&mut self, by: &Value) {
        let unit =
            |key: &str, seconds: i64| by.get(key).and_then(Value::as_i64).unwrap_or(0) * seconds;
        self.now = self
            .now
            .plus_seconds(unit("days", 86_400) + unit("hours", 3_600) + unit("minutes", 60));
    }

    fn store_row(&mut self, row: ParkRow) {
        self.rows
            .insert((row.task_id.clone(), row.formulation_id.clone()), row);
    }

    fn sweep(&mut self) {
        if self.settings.activated_at().is_some() {
            self.last_sweep = Some(self.now.plus_seconds(-60));
        }
        let next: Vec<(String, TaskClock)> = self
            .tasks
            .iter()
            .filter(|(_, task)| task.clock.state == Some(TaskState::Next))
            .map(|(id, task)| (id.clone(), task.clock.clone()))
            .collect();
        let Some(plan) = park::plan_owner_sweep(
            self.exposed,
            &self.settings,
            self.last_sweep,
            &next,
            self.now,
        ) else {
            return;
        };
        self.settings = plan.note.settings.clone();
        self.last_sweep = Some(plan.note.last_effective_sweep_at);
        for id in &plan.due {
            self.next_id += 1;
            let repair_id = fid(0x1000 + u64::from(self.next_id));
            let clock = self.tasks[id].clock.clone();
            match park::sweep_task(id, &clock, &self.settings, self.now, &repair_id) {
                SweepStep::Skipped => {}
                SweepStep::Repaired(repaired) => {
                    self.tasks.get_mut(id).expect("task").clock = *repaired
                }
                SweepStep::Parked(parked) => {
                    if self.keys.insert(parked.key.clone()) {
                        self.tasks.get_mut(id).expect("task").clock = parked.clock;
                        self.store_row(parked.row);
                    }
                }
            }
        }
    }

    fn request(&mut self, method: &str, path: &str, body: &Value) -> Option<Reply> {
        let segments: Vec<&str> = path.trim_matches('/').split('/').collect();
        match (method, segments.as_slice()) {
            ("POST", ["api", "review", "explainer", "acknowledge"]) => Some(self.activate(body)),
            ("POST", ["api", "tasks"]) => Some(self.create(body)),
            ("GET", ["api", "tasks", id]) => Some(reply(200, self.view(id))),
            ("PATCH", ["api", "tasks", id]) => Some(self.patch(id, body)),
            ("POST", ["api", "tasks", id, "auto-park"]) => Some(self.device_park(id, body)),
            ("POST", ["api", "tasks", id, "decisions"]) => Some(self.decide(id, body)),
            ("POST", ["api", "review", "decisions", id, "undo"]) => Some(self.undo(id, body)),
            _ => None,
        }
    }

    fn activate(&mut self, body: &Value) -> Reply {
        let zone = body.get("time_zone").and_then(Value::as_str);
        let activated =
            formulation::activate_owner(&self.settings, self.now, zone).expect("activation");
        if activated != self.settings {
            self.settings_revision += 1;
            let ids: Vec<String> = self.tasks.keys().cloned().collect();
            for id in ids {
                self.next_id += 1;
                let form = fid(0x2000 + u64::from(self.next_id));
                let task = self.tasks.get_mut(&id).expect("task");
                task.clock = formulation::activate_clock(&task.clock, self.now, &form);
            }
        }
        self.settings = activated;
        reply(
            200,
            json!({
                "explainer_seen": true,
                "settings": {"time_zone": self.settings.time_zone(), "revision": self.settings_revision},
            }),
        )
    }

    fn create(&mut self, body: &Value) -> Reply {
        assert_eq!(text(body, "state"), "next", "the traces create in Next");
        self.next_id += 1;
        let id = format!("task_sim_{}", self.next_id);
        let form = body
            .get("new_formulation_id")
            .and_then(Value::as_str)
            .map_or_else(|| fid(0x3000 + u64::from(self.next_id)), str::to_owned);
        let clock = formulation::create_in_next(text(body, "title"), &form, self.now);
        self.tasks.insert(
            id.clone(),
            SimTask {
                clock,
                details: None,
                waiting_for: None,
            },
        );
        reply(201, self.view(&id))
    }

    fn patch(&mut self, id: &str, body: &Value) -> Reply {
        let task = self.tasks.get_mut(id).expect("task");
        if body["expected_revision"].as_u64() != Some(task.clock.revision) {
            return reply(409, Value::Null);
        }
        task.clock = formulation::edit_without_clock(&task.clock);
        task.details = Self::string(&body["details"]);
        reply(200, self.view(id))
    }

    fn device_park(&mut self, id: &str, body: &Value) -> Reply {
        let request = DeviceParkRequest {
            task_id: id,
            formulation_id: text(body, "formulation_id"),
            exposed: self.exposed,
            last_effective_sweep_at: self.last_sweep,
        };
        let clock = self.tasks[id].clock.clone();
        let result = park::device_auto_park(&clock, &self.settings, &request, self.now);
        if let Some(note) = &result.sweep {
            self.settings = note.settings.clone();
            self.last_sweep = Some(note.last_effective_sweep_at);
        }
        let applied = match result.outcome {
            AutoPark::Applied(parked) => {
                self.tasks.get_mut(id).expect("task").clock = parked.clock;
                self.store_row(parked.row);
                true
            }
            AutoPark::NotApplied(_) => false,
        };
        reply(200, json!({ "applied": applied, "task": self.view(id) }))
    }

    // ---- the review decision routes: the part under test

    /// The owner's read set as the server loads it under the lock.
    fn read_set(&self) -> ReadSet {
        let tasks: serde_json::Map<String, Value> = self
            .tasks
            .iter()
            .map(|(id, task)| (id.clone(), self.stored(id, task)))
            .collect();
        let acks: Vec<Value> = self
            .rows
            .values()
            .map(|row| serde_json::to_value(row.to_ack().expect("an ack")).expect("JSON"))
            .collect();
        let mut read_set: ReadSet = serde_json::from_value(json!({
            "tasks": tasks,
            "settings": {
                "threshold_days": self.settings.threshold_days(), "review_weekday": 5,
                "review_time": "16:00", "time_zone": self.settings.time_zone(),
                "onboarded_at": null,
                "activated_at": self.settings.activated_at().map(iso),
                "owner_park_floor_at": self.settings.owner_park_floor_at().map(iso),
                "revision": self.settings_revision.to_string(),
            },
            "park_acks": acks,
        }))
        .expect("a read set");
        read_set.decisions = self.decisions.clone();
        read_set.receipts = self.receipts.clone();
        read_set
    }

    fn stored(&self, id: &str, task: &SimTask) -> Value {
        let clock = &task.clock;
        let state = clock.state.map_or("inbox", TaskState::as_str);
        let mut row = with(
            task_json(id, state, clock.revision),
            json!({
                "title": clock.title, "details": task.details, "waiting_for": task.waiting_for,
                "waiting_since": task.waiting_for.as_ref().map(|_| "2026-10-01T09:00:00Z"),
            }),
        );
        let mut stored: types::Task = serde_json::from_value(row.clone()).expect("a task");
        clock.write_clock_fields(&mut stored).expect("clock fields");
        row = serde_json::to_value(stored).expect("JSON");
        row
    }

    fn land(&mut self, id: &str, set: &ChangeSet) {
        for change in &set.changes {
            match change {
                DomainChange::Upsert(Record::Task(task)) => {
                    let sim = self.tasks.get_mut(task.id.as_str()).expect("task");
                    sim.clock = TaskClock::from_task(task).expect("clock");
                    sim.details = task.details.as_ref().map(|d| d.as_str().to_owned());
                    sim.waiting_for = task.waiting_for.as_ref().map(|w| w.as_str().to_owned());
                }
                DomainChange::Upsert(Record::ReviewParkAck(ack)) => {
                    self.store_row(ParkRow::from_ack(ack).expect("a row"));
                }
                DomainChange::Upsert(Record::ReviewDecision(decision)) => {
                    self.decisions.insert(decision.id.clone(), decision.clone());
                }
                DomainChange::Upsert(Record::ReviewReceipt(receipt)) => {
                    self.receipts
                        .retain(|r| !(r.task_id == receipt.task_id && r.kind == receipt.kind));
                    self.receipts.push(receipt.clone());
                }
                DomainChange::Tombstone {
                    entity_type: EntityType::ReviewDecision,
                    record_key,
                } => {
                    self.decisions
                        .remove(&DecisionId::parse(&record_key[0]).expect("id"));
                }
                DomainChange::Tombstone {
                    entity_type: EntityType::ReviewReceipt,
                    record_key,
                } => {
                    self.receipts.retain(|r| {
                        !(r.task_id.as_str() == record_key[0] && r.kind.as_str() == record_key[1])
                    });
                }
                other => panic!("{id}: unexpected change {other:?}"),
            }
        }
    }

    fn refused(&self, id: &str, error: &DomainError) -> Reply {
        match error.reason {
            Reason::RevisionConflict | Reason::FormulationChanged | Reason::UndoUnavailable => {
                reply(
                    409,
                    json!({"detail": {"resource": "Task", "id": id, "reason": error.reason.as_str()},
                       "reference_id": "ref"}),
                )
            }
            Reason::NotFound => reply(404, Value::Null),
            _ => reply(400, json!({"detail": {"reason": error.reason.as_str()}})),
        }
    }

    fn decision_body(&self, decision: &Decision, id: &str) -> Value {
        let receipt = self
            .receipts
            .iter()
            .find(|r| r.decision_id.as_ref() == Some(&decision.id))
            .map(|r| json!({"task_id": r.task_id, "kind": r.kind.as_str(), "task_revision": r.task_revision}));
        json!({
            "decision": {
                "id": decision.id, "type": decision.decision_type.as_str(),
                "task_id": decision.task_id, "session_id": decision.session_id,
                "substantive": decision.substantive,
                "stall_reason": decision.stall_reason.map(types::StallReason::as_str),
                "ai_use": decision.ai_use.as_str(), "yielded_auto_park": decision.yielded_auto_park,
            },
            "task": self.view(id),
            "created_task": null,
            "receipt": receipt,
            "session_counts": null,
        })
    }

    fn decide(&mut self, id: &str, body: &Value) -> Reply {
        let mut payload = body.clone();
        let expected = payload
            .as_object_mut()
            .and_then(|members| members.remove("expected_revision"))
            .and_then(|revision| revision.as_u64())
            .expect("an expected revision");
        if payload.get("decision_id").is_none() {
            self.next_id += 1;
            payload["decision_id"] = json!(did(0x4000 + u64::from(self.next_id)));
        }
        let command = command(
            "review.decide",
            id,
            payload,
            vec![check("task", id, expected)],
        );
        let allocated = [fid(0x5000 + u64::from(self.next_id))];
        let inputs = inputs_with(&iso(self.now), &allocated, true);
        match review_decisions::decide(&self.read_set(), &command, &inputs) {
            Err(error) => self.refused(id, &error),
            Ok(set) => {
                self.land(id, &set);
                let stored = self
                    .decisions
                    .get(
                        &DecisionId::parse(text(&command_payload(&command), "decision_id"))
                            .expect("id"),
                    )
                    .cloned()
                    .expect("the decision is stored");
                reply(200, self.decision_body(&stored, id))
            }
        }
    }

    fn undo(&mut self, decision_id: &str, body: &Value) -> Reply {
        let stored = self
            .decisions
            .get(&DecisionId::parse(decision_id).expect("id"))
            .cloned();
        let task = stored.as_ref().map(|d| d.task_id.as_str().to_owned());
        let command = command(
            "review.undo_decision",
            decision_id,
            json!({}),
            task.iter()
                .map(|task| {
                    check(
                        "task",
                        task,
                        body["expected_task_revision"].as_u64().expect("revision"),
                    )
                })
                .collect(),
        );
        let id = task.unwrap_or_default();
        let inputs = inputs_with(&iso(self.now), &[], true);
        match review_decisions::decide(&self.read_set(), &command, &inputs) {
            Err(error) => self.refused(&id, &error),
            Ok(set) => {
                self.land(&id, &set);
                reply(
                    200,
                    json!({"task": self.view(&id), "undone_decision_id": decision_id,
                           "deleted_task_id": set.result.deleted_task_id, "session_counts": null}),
                )
            }
        }
    }
}

fn command_payload(command: &DomainCommand) -> Value {
    match serde_json::to_value(command).expect("JSON") {
        Value::Object(mut members) => members.remove("payload").expect("a payload"),
        other => panic!("{other:?}"),
    }
}

/// The trace convention of `expect.body`: a subset; lists match element-wise;
/// `$present` matches any non-null value; instants compare as instants.
fn matches(expected: &Value, actual: &Value, place: &str) {
    match expected {
        Value::String(text) if text == "$present" => assert!(!actual.is_null(), "{place}"),
        Value::Object(members) => {
            for (key, wanted) in members {
                matches(wanted, &actual[key], &format!("{place}.{key}"));
            }
        }
        Value::Array(items) => {
            let have = actual
                .as_array()
                .unwrap_or_else(|| panic!("{place}: no list"));
            assert_eq!(have.len(), items.len(), "{place}");
            for (index, wanted) in items.iter().enumerate() {
                matches(wanted, &have[index], &format!("{place}[{index}]"));
            }
        }
        Value::String(text) if text.starts_with("20") && text.ends_with('Z') => {
            let have = actual
                .as_str()
                .unwrap_or_else(|| panic!("{place}: not text"));
            assert_eq!(at(have), at(text), "{place}");
        }
        other => assert_eq!(actual, other, "{place}"),
    }
}

fn substitute(value: &Value, captured: &BTreeMap<String, String>) -> Value {
    match value {
        Value::String(text) => {
            let mut text = text.clone();
            for (name, captured_value) in captured {
                text = text.replace(&format!("{{{name}}}"), captured_value);
            }
            Value::String(text)
        }
        Value::Array(items) => {
            Value::Array(items.iter().map(|i| substitute(i, captured)).collect())
        }
        Value::Object(members) => Value::Object(
            members
                .iter()
                .map(|(k, v)| (k.clone(), substitute(v, captured)))
                .collect(),
        ),
        other => other.clone(),
    }
}

fn traces() -> &'static Value {
    static TRACES: OnceLock<Value> = OnceLock::new();
    TRACES.get_or_init(|| {
        let path = support::repo_root().join("backend/tests/fixtures/review_traces_tasks.json");
        let raw = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{path:?}: {e}"));
        serde_json::from_str(&raw).expect("trace file JSON")
    })
}

/// Replays a recorded trace. Returns the paths of the decision and Undo requests
/// this family answered, the number of all requests answered, and the names of
/// the steps that belong to other rule families.
fn replay(id: &str) -> (Vec<String>, usize, Vec<String>) {
    let trace = traces()["traces"]
        .as_array()
        .expect("traces")
        .iter()
        .find(|trace| text(trace, "id") == id)
        .unwrap_or_else(|| panic!("trace {id} is not in the file"));
    let mut sim = Sim::new(text(trace, "start"), text(trace, "flag") == "on");
    let mut captured = BTreeMap::new();
    let (mut mine, mut answered) = (Vec::new(), 0);
    for step in trace["steps"].as_array().expect("steps") {
        let name = text(step, "name");
        if let Some(by) = step.get("advance") {
            sim.advance(by);
        } else if step.get("sweep").is_some() {
            sim.sweep();
        } else if let Some(flag) = step.get("flag") {
            sim.exposed = flag == "on";
        } else {
            let request = substitute(&step["request"], &captured);
            let body = request.get("body").cloned().unwrap_or(Value::Null);
            let path = text(&request, "path");
            let Some(response) = sim.request(text(&request, "method"), path, &body) else {
                sim.out_of_scope.push(name.to_owned());
                continue;
            };
            let expect = substitute(&step["expect"], &captured);
            assert_eq!(
                u64::from(response.status),
                expect["status"].as_u64().expect("status"),
                "{id}: {name}"
            );
            if let Some(wanted) = expect.get("body") {
                matches(wanted, &response.body, &format!("{id}: {name}"));
            }
            if let Some(names) = step.get("capture") {
                for (variable, found) in names.as_object().expect("capture map") {
                    let node = found
                        .as_str()
                        .expect("a path")
                        .split('.')
                        .fold(&response.body, |node, key| &node[key]);
                    captured.insert(
                        variable.clone(),
                        node.as_str().expect("a captured id").to_owned(),
                    );
                }
            }
            if path.ends_with("/decisions") || path.ends_with("/undo") {
                mine.push(format!(
                    "{}: {name}",
                    step["request"]["method"].as_str().unwrap_or("")
                ));
            }
            answered += 1;
        }
    }
    (mine, answered, sim.out_of_scope)
}

#[test]
fn review_decisions_026_fr_016_trace_a_stalled_next_task_gets_a_first_step() {
    let (mine, answered, other) = replay("TR-001");
    assert_eq!(mine.len(), 1, "the one decision request");
    assert_eq!(answered, 3, "acknowledge, create, decide");
    assert!(other.is_empty(), "{other:?}");
}

#[test]
fn review_decisions_026_fr_016_trace_a_decision_on_a_changed_task_is_refused_and_applies_nothing() {
    let (mine, answered, other) = replay("TR-002");
    assert_eq!(mine.len(), 1, "the stale decision");
    assert_eq!(answered, 4, "create, edit, decide, read");
    assert!(other.is_empty(), "{other:?}");
}

#[test]
fn review_decisions_026_fr_016_trace_an_offline_decision_before_the_park_yields_it() {
    let (mine, answered, other) = replay("TR-004");
    assert_eq!(mine.len(), 1, "the yielding decision");
    assert_eq!(
        answered, 6,
        "every request step; the advance and the sweep are not requests"
    );
    assert!(other.is_empty(), "{other:?}");
}

#[test]
fn review_decisions_026_fr_042_trace_with_the_flag_off_a_decision_and_its_undo_are_accepted() {
    let (mine, answered, other) = replay("TR-006");
    assert_eq!(mine.len(), 2, "the queued decision and the queued Undo");
    assert_eq!(answered, 5, "acknowledge, create, park, decision, undo");
    // Review state, settings and the park acknowledgement belong to other families.
    assert_eq!(
        other,
        [
            "the gated read is hidden",
            "a queued settings change is accepted",
            "queued park acknowledgements are accepted"
        ]
    );
}

#[test]
fn review_decisions_026_fr_005_trace_a_decision_retried_after_the_retention_is_applied_once() {
    let (mine, answered, other) = replay("TR-007");
    assert_eq!(mine.len(), 2, "the decision and its retry");
    assert_eq!(answered, 4, "create, decide, retry, read");
    assert!(other.is_empty(), "{other:?}");
}

// --------------------------------------------------------- decision scenarios
//
// Rebuilt over a `Store` from `backend/tests/test_review_decisions_api.py`.

const STARTED: &str = "2026-09-20T09:00:00Z";

fn asks_store() -> Store {
    // Started 19 days ago: past its ask (14 d), before its park (21 d).
    Store::new(&[next_json(1, 1, STARTED)])
}

fn on_form(n: u64, extra: Value) -> Value {
    with(json!({"formulation_id": fid(n)}), extra)
}

#[test]
fn review_decisions_026_fr_016_every_decision_type_counts_in_its_bucket() {
    // test_020_FR_006_020_FR_033_every_decision_type_and_its_counter
    let waiting = with(task_json(&tid(2), "waiting", 1), json!({}));
    let someday = task_json(&tid(3), "someday", 1);
    let inbox = task_json(&tid(4), "inbox", 1);
    let table: [(&str, u64, Value, &str); 11] = [
        ("complete", 1, json!({}), "done"),
        (
            "reformulate",
            1,
            on_form(
                1,
                json!({"title": "Email Bob the quote", "new_formulation_id": fid(94)}),
            ),
            "reformulated",
        ),
        (
            "first_step",
            1,
            on_form(
                1,
                json!({"title": "Find Bob's number", "new_formulation_id": fid(90)}),
            ),
            "first_step",
        ),
        (
            "waiting",
            1,
            on_form(1, json!({"waiting_for": "Ann"})),
            "waiting",
        ),
        ("someday", 1, on_form(1, json!({})), "someday"),
        ("cancel", 4, json!({}), "cancelled"),
        (
            "extend",
            1,
            on_form(1, json!({"reason": "Waiting for the quote"})),
            "extended",
        ),
        ("keep_waiting", 2, json!({}), "kept"),
        ("keep_someday", 3, json!({}), "kept"),
        (
            "follow_up",
            2,
            json!({"title": "Chase Bob", "new_formulation_id": fid(91), "follow_up_task_id": tid(92)}),
            "moved_to_next",
        ),
        (
            "return_to_next",
            3,
            json!({"title": "Call Bob", "new_formulation_id": fid(93)}),
            "moved_to_next",
        ),
    ];
    assert_eq!(table.len(), DecisionType::ALL.len());
    for (kind, task, extra, bucket) in table {
        let store = Store::new(&[
            next_json(1, 1, STARTED),
            waiting.clone(),
            someday.clone(),
            inbox.clone(),
        ])
        .with_sessions(vec![session_json(1, "open")]);
        let mut payload = extra;
        payload["session_id"] = json!(sid(1));
        let set = accepted(store.decide(&decide_command(&tid(task), &did(1), kind, payload, 1)));
        let decision = the_decision(&set);
        let counted = decision.review_counts_as.as_str();
        assert_eq!(counted, bucket, "{kind}");
        assert_eq!(
            review_decisions::counts_as(DecisionType::from_wire(kind).expect("type")).as_str(),
            bucket,
            "{kind}"
        );
        let Some(DomainChange::Upsert(Record::ReviewSession(session))) = set.changes.last() else {
            panic!("{kind}: the run is the last change");
        };
        let counts = serde_json::to_value(session.counts).expect("JSON");
        for (name, value) in counts.as_object().expect("counts") {
            assert_eq!(
                value.as_u64(),
                Some(u64::from(name == bucket)),
                "{kind}: {name}"
            );
        }
        assert_eq!(
            session.revision.to_u64(),
            Some(5),
            "{kind}: the run's revision advances"
        );
        assert!(session.qualifying_activity, "{kind}");
        assert_eq!(
            session.last_activity_at.as_str(),
            NOW,
            "{kind}: an open run counts the activity"
        );
    }
}

#[test]
fn review_decisions_026_fr_016_a_decision_outside_a_review_or_in_an_unknown_one_has_no_run() {
    // test_020_FR_010_..._recorded_the_same_way, test_020_FR_011_unknown_session
    let store = asks_store().with_sessions(vec![session_json(1, "open")]);
    for session in [None, Some(sid(9))] {
        let payload = session.map_or(json!({}), |id| json!({"session_id": id}));
        let set = accepted(store.decide(&decide_command(&tid(1), &did(1), "complete", payload, 1)));
        assert_eq!(the_decision(&set).session_id, None);
        assert!(
            !set.changes
                .iter()
                .any(|c| matches!(c, DomainChange::Upsert(Record::ReviewSession(_)))),
            "no run is touched"
        );
    }
}

#[test]
fn review_decisions_026_fr_016_a_finished_run_still_counts_a_late_decision() {
    // test_020_SC_007_a_finished_session_still_counts_a_late_decision
    let store = asks_store().with_sessions(vec![session_json(1, "completed")]);
    let set = accepted(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "complete",
        json!({"session_id": sid(1)}),
        1,
    )));
    let Some(DomainChange::Upsert(Record::ReviewSession(session))) = set.changes.last() else {
        panic!("the run changes");
    };
    assert_eq!(session.counts.done, 1);
    assert_eq!(
        session.last_activity_at.as_str(),
        "2026-10-09T09:30:00Z",
        "only an open run is active"
    );
}

#[test]
fn review_decisions_026_fr_016_cosmetic_save_anyway_is_a_reformulate_without_a_clock_change() {
    // test_020_FR_002_cosmetic_save_anyway_...
    let store = asks_store();
    let set = accepted(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "reformulate",
        on_form(
            1,
            json!({"title": "call bob!", "new_formulation_id": fid(80)}),
        ),
        1,
    )));
    let task = the_task(&set);
    assert_eq!(task.title.as_str(), "call bob!");
    assert_eq!(task.revision.to_u64(), Some(2));
    assert_eq!(
        task.formulation.as_ref().map(|c| c.id.as_str()),
        Some(fid(1).as_str())
    );
    assert_eq!(the_decision(&set).substantive, Some(false));
    // The same without any ID for a new formulation: the clock is not restarted.
    let none = accepted(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "reformulate",
        on_form(1, json!({"title": "call bob!"})),
        1,
    )));
    assert_eq!(the_task(&none).formulation, task.formulation);
}

#[test]
fn review_decisions_026_fr_016_substantive_reformulate_adopts_the_client_formulation_id() {
    // test_020_FR_002_substantive_reformulate_adopts_the_client_formulation_id
    let store = asks_store();
    let set = accepted(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "reformulate",
        on_form(
            1,
            json!({"title": "Email Bob the quote", "new_formulation_id": fid(80)}),
        ),
        1,
    )));
    let task = the_task(&set);
    assert_eq!(
        task.formulation.as_ref().map(|c| c.id.as_str()),
        Some(fid(80).as_str())
    );
    assert_eq!(
        task.consecutive_stalled_formulations, 1,
        "it had reached its ask"
    );
    assert_eq!(the_decision(&set).substantive, Some(true));
    // Without one the allocated ID is used; without either, it is refused.
    let allocated = accepted(store.decide_at(
        &decide_command(
            &tid(1),
            &did(1),
            "reformulate",
            on_form(1, json!({"title": "Email Bob the quote"})),
            1,
        ),
        NOW,
        &[fid(81)],
    ));
    assert_eq!(
        the_task(&allocated)
            .formulation
            .as_ref()
            .map(|c| c.id.as_str()),
        Some(fid(81).as_str())
    );
    let missing = refusal(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "reformulate",
        on_form(1, json!({"title": "Email Bob the quote"})),
        1,
    )));
    assert_eq!(missing.reason, Reason::FormulationIdRequired);
}

#[test]
fn review_decisions_026_fr_016_first_step_keeps_the_old_title_in_the_notes_and_refuses_overflow() {
    // test_020_FR_008_first_step_keeps_the_old_title_in_the_notes, ..._refuses_notes_that_would_overflow
    let store = asks_store();
    let set = accepted(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "first_step",
        on_form(
            1,
            json!({"title": "Find Bob's number", "new_formulation_id": fid(80)}),
        ),
        1,
    )));
    let task = the_task(&set);
    assert_eq!(
        task.details.as_ref().map(|d| d.as_str()),
        Some("Was: Call Bob")
    );
    assert_eq!(task.title.as_str(), "Find Bob's number");
    assert_eq!(the_decision(&set).substantive, Some(true));
    let with_notes = Store::new(&[with(
        next_json(1, 1, STARTED),
        json!({"details": "Bob is back Monday"}),
    )]);
    let set = accepted(with_notes.decide(&decide_command(
        &tid(1),
        &did(1),
        "first_step",
        on_form(
            1,
            json!({"title": "Find Bob's number", "new_formulation_id": fid(80)}),
        ),
        1,
    )));
    assert_eq!(
        the_task(&set).details.as_ref().map(|d| d.as_str()),
        Some("Was: Call Bob\n\nBob is back Monday")
    );
    let long = "x".repeat(20_000 - "Was: Call Bob\n\n".chars().count() + 1);
    let overflow = Store::new(&[with(next_json(1, 1, STARTED), json!({"details": long}))]);
    let refused = refusal(overflow.decide(&decide_command(
        &tid(1),
        &did(1),
        "first_step",
        on_form(
            1,
            json!({"title": "Find Bob's number", "new_formulation_id": fid(80)}),
        ),
        1,
    )));
    assert_eq!(refused.reason, Reason::TextLength);
    assert_eq!(refused.field.as_deref(), Some("details"));
}

#[test]
fn review_decisions_026_fr_016_extend_needs_a_due_formulation_works_once_and_needs_a_reason() {
    // test_020_FR_009_extend_*
    let fresh = Store::new(&[next_json(1, 1, "2026-10-05T09:00:00Z")]);
    let not_due = refusal(fresh.decide(&decide_command(
        &tid(1),
        &did(1),
        "extend",
        on_form(1, json!({"reason": "Waiting for the quote"})),
        1,
    )));
    assert_eq!(not_due.reason, Reason::ExtensionNotDue);
    let mut store = asks_store();
    let set = accepted(store.run(&decide_command(
        &tid(1),
        &did(1),
        "extend",
        on_form(1, json!({"reason": "Waiting for the quote"})),
        1,
    )));
    let task = the_task(&set);
    assert_eq!(
        task.formulation
            .as_ref()
            .and_then(|c| c.extension_reason.as_ref())
            .map(|r| r.as_str()),
        Some("Waiting for the quote")
    );
    assert_eq!(
        the_decision(&set).reason_text.as_ref().map(|r| r.as_str()),
        Some("Waiting for the quote")
    );
    let twice = refusal(store.decide(&decide_command(
        &tid(1),
        &did(2),
        "extend",
        on_form(1, json!({"reason": "Still waiting"})),
        2,
    )));
    assert_eq!(twice.reason, Reason::ExtensionAlreadyUsed);
    // At the park's due instant, before the park is applied, it is still allowed.
    let due = Store::new(&[next_json(1, 1, "2026-09-18T09:00:00Z")]);
    accepted(due.decide(&decide_command(
        &tid(1),
        &did(1),
        "extend",
        on_form(1, json!({"reason": "Waiting for the quote"})),
        1,
    )));
    // The reason is required: the command does not even type.
    let typed = try_command(
        "review.decide",
        &tid(1),
        json!({"decision_id": did(1), "type": "extend", "formulation_id": fid(1)}),
        vec![check("task", &tid(1), 1)],
    );
    assert_eq!(
        typed.expect_err("a refusal").reason,
        Reason::DecisionFieldsMissing
    );
}

#[test]
fn review_decisions_026_fr_016_receipts_hide_a_task_from_its_review_step() {
    // test_020_FR_032_someday_is_a_release_receipt_not_a_park, ..._keep_waiting_and_keep_someday_write_keep_receipts
    let waiting = task_json(&tid(2), "waiting", 3);
    let someday = task_json(&tid(3), "someday", 5);
    let store = Store::new(&[next_json(1, 1, STARTED), waiting, someday]);
    let release = accepted(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "someday",
        on_form(1, json!({})),
        1,
    )));
    let moved = the_task(&release);
    assert_eq!(moved.state, TaskState::Someday);
    assert!(moved.parked.is_none(), "a person's release is not a park");
    let receipts: Vec<&ReviewReceipt> = release
        .changes
        .iter()
        .filter_map(|c| match c {
            DomainChange::Upsert(Record::ReviewReceipt(r)) => Some(r),
            _ => None,
        })
        .collect();
    let [receipt] = receipts.as_slice() else {
        panic!("one receipt")
    };
    assert_eq!(
        (
            receipt.kind.as_str(),
            receipt.source.as_str(),
            receipt.task_revision.to_u64()
        ),
        ("someday", "release", Some(2)),
        "at the revision the move wrote"
    );
    assert_eq!(
        receipt.hidden_until.as_str(),
        "2026-11-08T12:00:00Z",
        "30 days"
    );
    assert_eq!(
        receipt.decision_id.as_ref().map(|id| id.as_str()),
        Some(did(1).as_str())
    );
    assert_eq!(receipt.bulk_id, None);

    let keep_waiting = accepted(store.decide(&decide_command(
        &tid(2),
        &did(2),
        "keep_waiting",
        json!({}),
        3,
    )));
    assert!(
        tasks_in(&keep_waiting).is_empty(),
        "a keep leaves the task alone"
    );
    assert_eq!(
        the_decision(&keep_waiting).task_revision_after.to_u64(),
        Some(3)
    );
    let DomainChange::Upsert(Record::ReviewReceipt(kept)) = &keep_waiting.changes[0] else {
        panic!("the receipt comes first");
    };
    assert_eq!(
        (
            kept.kind.as_str(),
            kept.source.as_str(),
            kept.task_revision.to_u64()
        ),
        ("waiting", "keep", Some(3))
    );
    assert_eq!(kept.hidden_until.as_str(), "2026-10-16T12:00:00Z", "7 days");
    let keep_someday = accepted(store.decide(&decide_command(
        &tid(3),
        &did(3),
        "keep_someday",
        json!({}),
        5,
    )));
    let DomainChange::Upsert(Record::ReviewReceipt(kept)) = &keep_someday.changes[0] else {
        panic!("the receipt comes first");
    };
    assert_eq!(
        (kept.kind.as_str(), kept.source.as_str()),
        ("someday", "keep")
    );
    assert_eq!(kept.hidden_until.as_str(), "2026-11-08T12:00:00Z");
}

#[test]
fn review_decisions_026_fr_016_follow_up_creates_a_next_task_in_the_same_project() {
    // test_020_FR_006_follow_up_creates_a_next_task_in_the_same_project
    let project = project_json("project_p1", "active");
    let parent = with(
        task_json(&tid(2), "waiting", 3),
        json!({"project_id": "project_p1"}),
    );
    let store = Store::new(&[parent]).with_projects(vec![project]);
    let payload =
        json!({"title": "Chase Bob", "follow_up_task_id": tid(50), "new_formulation_id": fid(51)});
    let set = accepted(store.decide(&decide_command(&tid(2), &did(1), "follow_up", payload, 3)));
    let created: Vec<&types::Task> = tasks_in(&set);
    let [created] = created.as_slice() else {
        panic!("the follow-up only; the waiting task stays")
    };
    assert_eq!(created.id.as_str(), tid(50));
    assert_eq!(
        (created.state, created.revision.to_u64()),
        (TaskState::Next, Some(1))
    );
    assert_eq!(
        created.project_id.as_ref().map(|p| p.as_str()),
        Some("project_p1")
    );
    assert_eq!(
        created.formulation.as_ref().map(|c| c.id.as_str()),
        Some(fid(51).as_str())
    );
    assert_eq!(created.order_key.to_u64(), Some(0));
    assert_eq!(
        set.result.created_task_id.as_ref().map(|id| id.as_str()),
        Some(tid(50).as_str())
    );
    let decision = the_decision(&set);
    assert_eq!(
        decision.created_task_id.as_ref().map(|id| id.as_str()),
        Some(tid(50).as_str())
    );
    assert_eq!(
        (
            decision.task_revision_before.to_u64(),
            decision.task_revision_after.to_u64()
        ),
        (Some(3), Some(3))
    );
    let undo = decision.private.as_ref().expect("an Undo snapshot");
    assert_eq!(
        undo.created_task_revision.as_ref().and_then(|r| r.to_u64()),
        Some(1)
    );
    assert_eq!(undo.receipt_kind.map(|k| k.as_str()), Some("waiting"));
    // Without a client ID the first allocated ID is the task, the next the formulation.
    let allocated = accepted(store.decide_at(
        &decide_command(
            &tid(2),
            &did(1),
            "follow_up",
            json!({"title": "Chase Bob"}),
            3,
        ),
        NOW,
        &[tid(60), fid(61)],
    ));
    let made = the_task(&allocated);
    assert_eq!(made.id.as_str(), tid(60));
    assert_eq!(
        made.formulation.as_ref().map(|c| c.id.as_str()),
        Some(fid(61).as_str())
    );
}

#[test]
fn review_decisions_026_fr_016_follow_up_and_return_to_next_need_an_active_project_and_a_free_id() {
    // test_020_FR_006_project_archived_blocks_..., test_020_FR_011_a_follow_up_id_already_used_is_id_conflict
    let archived = project_json("project_p1", "archived");
    let waiting = with(
        task_json(&tid(2), "waiting", 3),
        json!({"project_id": "project_p1"}),
    );
    let someday = with(
        task_json(&tid(3), "someday", 3),
        json!({"project_id": "project_p1"}),
    );
    let store = Store::new(&[waiting, someday.clone(), task_json(&tid(70), "inbox", 1)])
        .with_projects(vec![archived]);
    let follow = refusal(store.decide(&decide_command(
        &tid(2),
        &did(1),
        "follow_up",
        json!({"title": "Chase Bob", "new_formulation_id": fid(51)}),
        3,
    )));
    assert_eq!(follow.reason, Reason::ProjectArchived);
    let back = refusal(store.decide(&decide_command(
        &tid(3),
        &did(1),
        "return_to_next",
        json!({"title": "Call Bob", "new_formulation_id": fid(51)}),
        3,
    )));
    assert_eq!(back.reason, Reason::ProjectArchived);
    // A project the read set lacks is a missing fact, not a default.
    let unloaded = Store::new(&[someday]);
    let missing = refusal(unloaded.decide(&decide_command(
        &tid(3),
        &did(1),
        "return_to_next",
        json!({"title": "Call Bob", "new_formulation_id": fid(51)}),
        3,
    )));
    assert_eq!(missing.reason, Reason::IncompleteReadSet);
    let free = Store::new(&[
        task_json(&tid(2), "waiting", 3),
        task_json(&tid(70), "inbox", 1),
    ]);
    let used = refusal(free.decide(&decide_command(
        &tid(2),
        &did(1),
        "follow_up",
        json!({"title": "Chase Bob", "follow_up_task_id": tid(70), "new_formulation_id": fid(51)}),
        3,
    )));
    assert_eq!(used.reason, Reason::IdAlreadyExists);
}

#[test]
fn review_decisions_026_fr_016_return_to_next_can_change_the_title_without_a_second_revision() {
    // test_020_FR_006_return_to_next_can_change_the_title
    let store = Store::new(&[task_json(&tid(3), "someday", 4)]);
    let set = accepted(store.decide(&decide_command(
        &tid(3),
        &did(1),
        "return_to_next",
        json!({"title": "Call Bob on Monday", "new_formulation_id": fid(51)}),
        4,
    )));
    let task = the_task(&set);
    assert_eq!(
        (task.state, task.revision.to_u64()),
        (TaskState::Next, Some(5))
    );
    assert_eq!(task.title.as_str(), "Call Bob on Monday");
    assert_eq!(
        task.formulation.as_ref().map(|c| c.id.as_str()),
        Some(fid(51).as_str())
    );
    let same = accepted(store.decide(&decide_command(
        &tid(3),
        &did(1),
        "return_to_next",
        json!({"title": "Call Bob", "new_formulation_id": fid(51)}),
        4,
    )));
    assert_eq!(the_task(&same).title.as_str(), "Call Bob");
}

#[test]
fn review_decisions_026_fr_016_a_stale_revision_or_formulation_or_list_refuses_and_applies_nothing()
{
    // test_020_FR_011_stale_revision_or_formulation_is_409..., ..._a_type_the_list_does_not_allow..., ..._another_owners_task_is_404
    let store = asks_store();
    let stale = refusal(store.decide(&decide_command(&tid(1), &did(1), "complete", json!({}), 7)));
    assert_eq!(stale.reason, Reason::RevisionConflict);
    assert_eq!(
        stale.current_revision.as_ref().and_then(|c| c.to_u64()),
        Some(1)
    );
    let other_form = refusal(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "waiting",
        json!({"formulation_id": fid(99), "waiting_for": "Ann"}),
        1,
    )));
    assert_eq!(other_form.reason, Reason::FormulationChanged);
    // A type that does not name a formulation still checks one it was given.
    let named = refusal(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "complete",
        json!({"formulation_id": fid(99)}),
        1,
    )));
    assert_eq!(named.reason, Reason::FormulationChanged);
    let not_allowed = refusal(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "keep_waiting",
        json!({}),
        1,
    )));
    assert_eq!(not_allowed.reason, Reason::DecisionNotAllowed);
    let no_task =
        refusal(store.decide(&decide_command(&tid(8), &did(1), "complete", json!({}), 1)));
    assert_eq!(no_task.reason, Reason::NotFound);
    assert_eq!(
        no_task.entity.as_ref().map(|(t, _)| *t),
        Some(EntityType::Task)
    );
}

#[test]
fn review_decisions_026_fr_016_waiting_needs_a_note_and_the_command_types_its_fields() {
    let store = asks_store();
    let blank = refusal(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "waiting",
        on_form(1, json!({"waiting_for": "   "})),
        1,
    )));
    assert_eq!(blank.reason, Reason::WaitingForRequired);
    let typed = try_command(
        "review.decide",
        &tid(1),
        json!({"decision_id": did(1), "type": "waiting"}),
        vec![check("task", &tid(1), 1)],
    );
    let error = typed.expect_err("a refusal");
    assert_eq!(
        (error.reason, error.field.as_deref()),
        (Reason::DecisionFieldsMissing, Some("waiting_for"))
    );
    // A direct call with a payload that skipped the typing is refused the same way.
    let without = types::Decide {
        decision_id: types::NewDecisionId::parse(did(1)).expect("id"),
        decision_type: DecisionType::Waiting,
        formulation_id: None,
        stall_reason: None,
        title: None,
        waiting_for: None,
        reason: None,
        session_id: None,
        ai_use: types::AiUse::None,
        navigator_request_id: None,
        client_decided_at: None,
        new_formulation_id: None,
        follow_up_task_id: None,
    };
    let mut bad = decide_command(&tid(1), &did(1), "complete", json!({}), 1);
    bad.command = types::Command::ReviewDecide(without);
    let direct = refusal(store.decide(&bad));
    assert_eq!(direct.reason, Reason::DecisionFieldsMissing);
}

#[test]
fn review_decisions_026_fr_005_a_stored_decision_id_is_a_matching_replay_or_a_conflict() {
    // test_020_FR_011_reused_decision_id_matches_or_conflicts
    let mut store = asks_store();
    let first = decide_command(
        &tid(1),
        &did(1),
        "waiting",
        on_form(1, json!({"waiting_for": "Ann"})),
        1,
    );
    accepted(store.run(&first));
    // The identical request, even at a stale revision, changes nothing.
    let again = accepted(store.decide(&first));
    assert_eq!(
        (again.outcome, again.changes.len()),
        (ChangeOutcome::NoOp, 0)
    );
    // Another type, another formulation or another task is a conflict.
    let other_type =
        refusal(store.decide(&decide_command(&tid(1), &did(1), "complete", json!({}), 2)));
    assert_eq!(other_type.reason, Reason::IdAlreadyExists);
    let other_form = refusal(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "waiting",
        on_form(2, json!({"waiting_for": "Ann"})),
        2,
    )));
    assert_eq!(other_form.reason, Reason::IdAlreadyExists);
    let mut two_tasks = Store::new(&[next_json(1, 1, STARTED), next_json(2, 1, STARTED)]);
    two_tasks.read_set.decisions = store.read_set.decisions.clone();
    let other_task = refusal(two_tasks.decide(&decide_command(
        &tid(2),
        &did(1),
        "waiting",
        on_form(2, json!({"waiting_for": "Ann"})),
        1,
    )));
    assert_eq!(other_task.reason, Reason::IdAlreadyExists);
}

#[test]
fn review_decisions_026_fr_016_one_card_one_decision_per_run() {
    // test_020_FR_002_020_FR_048_a_repeated_save_anyway_in_one_run_counts_once,
    // ..._a_cosmetic_save_is_new_in_another_run_or_wording,
    // ..._a_second_keep_waiting_in_one_run_counts_once, ..._a_second_follow_up_...,
    // ..._one_card_one_kept_decision_whichever_no_revision_type,
    // ..._a_no_revision_decision_is_new_after_undo_run_or_change
    let in_run = |n: u64| json!({"session_id": sid(n)});
    let sessions = || vec![session_json(1, "open"), session_json(2, "open")];

    // Save anyway twice.
    let mut store = asks_store().with_sessions(sessions());
    let save = |decision: u64, title: &str, revision: u64, run: u64| {
        decide_command(
            &tid(1),
            &did(decision),
            "reformulate",
            on_form(
                1,
                with(
                    in_run(run),
                    json!({"title": title, "new_formulation_id": fid(80)}),
                ),
            ),
            revision,
        )
    };
    accepted(store.run(&save(1, "call bob!", 1, 1)));
    let repeat = accepted(store.decide(&save(2, "call bob!!", 2, 1)));
    assert_eq!(
        repeat.outcome,
        ChangeOutcome::NoOp,
        "a cosmetic repeat in the run counts once"
    );
    let other_run = accepted(store.decide(&save(2, "call bob!!", 2, 2)));
    assert_eq!(
        other_run.outcome,
        ChangeOutcome::Applied,
        "another run counts it"
    );
    let reworded = accepted(store.decide(&save(2, "Email Bob the quote", 2, 1)));
    assert_eq!(
        reworded.outcome,
        ChangeOutcome::Applied,
        "a substantive wording is new"
    );
    let mut no_run = store.clone();
    let loose = accepted(no_run.run(&decide_command(
        &tid(1),
        &did(3),
        "reformulate",
        on_form(1, json!({"title": "call bob!!"})),
        2,
    )));
    assert_eq!(
        loose.outcome,
        ChangeOutcome::Applied,
        "a request without a run is a new decision"
    );

    // Keep waiting twice, whichever no-revision type came first.
    let waiting = || Store::new(&[task_json(&tid(2), "waiting", 3)]).with_sessions(sessions());
    let keep = |decision: u64, kind: &str, run: u64| {
        let extra = if kind == "follow_up" {
            with(
                in_run(run),
                json!({"title": "Chase Bob", "new_formulation_id": fid(51), "follow_up_task_id": tid(50 + decision)}),
            )
        } else {
            in_run(run)
        };
        decide_command(&tid(2), &did(decision), kind, extra, 3)
    };
    for first in ["keep_waiting", "follow_up"] {
        for second in ["keep_waiting", "follow_up"] {
            let mut store = waiting();
            accepted(store.run(&keep(1, first, 1)));
            let again = accepted(store.decide(&keep(2, second, 1)));
            assert_eq!(
                again.outcome,
                ChangeOutcome::NoOp,
                "{first} then {second}: one kept decision"
            );
            assert!(
                tasks_in(&again).is_empty(),
                "no second Next task is created"
            );
            let elsewhere = accepted(store.decide(&keep(2, second, 2)));
            assert_eq!(
                elsewhere.outcome,
                ChangeOutcome::Applied,
                "another run: new"
            );
            // An Undo deletes the decision: the card is new again.
            let undo_store = store.clone();
            let mut undone = undo_store;
            accepted(undone.run(&undo_command(&did(1), &tid(2), 3)));
            let fresh = accepted(undone.decide(&keep(2, second, 1).with_revision(4)));
            assert_eq!(
                fresh.outcome,
                ChangeOutcome::Applied,
                "{first} then undo then {second}"
            );
            // The task changed since: new.
            let mut changed = store.clone();
            changed
                .read_set
                .tasks
                .get_mut(&id_of(&task_json(&tid(2), "waiting", 3)))
                .expect("task")
                .revision = 4u64.into();
            let after_edit = accepted(changed.decide(&keep(2, second, 1).with_revision(4)));
            assert_eq!(
                after_edit.outcome,
                ChangeOutcome::Applied,
                "{first} then an edit then {second}"
            );
        }
    }
    // keep_someday twice.
    let mut store = Store::new(&[task_json(&tid(3), "someday", 5)]).with_sessions(sessions());
    let keep_someday =
        |decision: u64| decide_command(&tid(3), &did(decision), "keep_someday", in_run(1), 5);
    accepted(store.run(&keep_someday(1)));
    assert_eq!(
        accepted(store.decide(&keep_someday(2))).outcome,
        ChangeOutcome::NoOp
    );
}

trait WithRevision {
    fn with_revision(self, revision: u64) -> Self;
}

impl WithRevision for DomainCommand {
    fn with_revision(mut self, revision: u64) -> Self {
        for check in &mut self.preconditions {
            check.edit_revision = revision.into();
        }
        self
    }
}

#[test]
fn review_decisions_026_fr_016_a_yield_resets_the_park_row_and_an_ordinary_return_stamps_it() {
    // ADR-0027 / E6: a yield is not a return; moving a parked task back is.
    let parked = |revision: u64| {
        with(
            task_json(&tid(1), "someday", revision),
            json!({"consecutive_stalled_formulations": 1, "parked": {
                "at": "2026-10-01T09:00:00Z", "formulation_id": fid(1),
                "private": {"from_revision": "2", "clock_before": {
                    "formulation_id": fid(1), "started_at": "2026-09-10T09:00:00Z", "extended_at": null,
                    "extension_reason": null, "park_floor_at": null, "stalled_before": 0}}}}),
        )
    };
    let seen = |returned: Value| {
        json!({"task_id": tid(1), "formulation_id": fid(1), "parked_at": "2026-10-01T09:00:00Z",
               "seen_at": "2026-10-02T09:00:00Z", "returned_at": returned,
               "private": {"from_revision": "2", "source": "sweep"}})
    };
    // A person's return to Next stamps `returned_at` in the same change set.
    let store = Store::new(&[parked(2)]).put("park_acks", vec![seen(Value::Null)]);
    let back = accepted(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "return_to_next",
        json!({"title": "Call Bob", "new_formulation_id": fid(51)}),
        2,
    )));
    assert!(back.changes.iter().any(|c| matches!(
        c,
        DomainChange::Upsert(Record::ReviewParkAck(ack)) if ack.returned_at.as_ref().map(|i| i.as_str()) == Some(NOW)
    )));
    // A decision made before the park yields it: the row reads "not returned" again.
    let store =
        Store::new(&[parked(2)]).put("park_acks", vec![seen(json!("2026-10-03T09:00:00Z"))]);
    let yielded = accepted(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "complete",
        json!({"formulation_id": fid(1), "client_decided_at": "2026-09-30T09:00:00Z"}),
        2,
    )));
    let ack = yielded.changes.iter().find_map(|c| match c {
        DomainChange::Upsert(Record::ReviewParkAck(ack)) => Some(ack),
        _ => None,
    });
    assert_eq!(ack.expect("the row").returned_at, None);
    assert!(the_decision(&yielded).yielded_auto_park);
    // Made after the park it does not yield: the parked Someday task decides as it
    // stands and the Undo snapshot keeps the park.
    let late = accepted(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "complete",
        json!({"formulation_id": fid(1), "client_decided_at": "2026-10-02T09:00:00Z"}),
        2,
    )));
    assert!(!the_decision(&late).yielded_auto_park);
    let snapshot = &the_decision(&late)
        .private
        .as_ref()
        .expect("a snapshot")
        .task_before;
    assert!(snapshot.parked.is_some() && snapshot.state == TaskState::Someday);
    assert!(
        !late
            .changes
            .iter()
            .any(|c| matches!(c, DomainChange::Upsert(Record::ReviewParkAck(_)))),
        "a decision of a parked Someday task is no return and no yield"
    );
    // A stale expected revision outside the yield window is refused.
    let stale = refusal(store.decide(&decide_command(
        &tid(1),
        &did(1),
        "complete",
        json!({"formulation_id": fid(1), "client_decided_at": "2026-10-02T09:00:00Z"}),
        1,
    )));
    assert_eq!(stale.reason, Reason::RevisionConflict);
}

// ----------------------------------------------------------------------- Undo

fn decided(store: &mut Store, kind: &str, extra: Value, task: u64, revision: u64) -> ChangeSet {
    accepted(store.run(&decide_command(&tid(task), &did(1), kind, extra, revision)))
}

#[test]
fn review_decisions_026_fr_016_undo_restores_the_task_and_its_clock_field_for_field() {
    // test_020_FR_048_undo_restores_the_task_and_its_clock_field_for_field
    let mut store = asks_store().with_sessions(vec![session_json(1, "open")]);
    let before = store.task(&tid(1)).clone();
    let decision = decided(
        &mut store,
        "someday",
        on_form(1, json!({"session_id": sid(1)})),
        1,
        1,
    );
    assert_eq!(store.task(&tid(1)).state, TaskState::Someday);
    assert!(store.receipt(&tid(1), "someday").is_some());
    let undone = accepted(store.run(&undo_command(&did(1), &tid(1), 2)));
    let restored = store.task(&tid(1));
    assert_eq!(
        restored.revision.to_u64(),
        Some(3),
        "the Undo is a write: one past the decision's"
    );
    assert_eq!(restored.updated_at.as_str(), NOW);
    assert_eq!(restored.formulation, before.formulation);
    assert_eq!(
        (
            restored.state,
            &restored.title,
            restored.consecutive_stalled_formulations
        ),
        (
            before.state,
            &before.title,
            before.consecutive_stalled_formulations
        )
    );
    assert!(store.decision(&did(1)).is_none(), "the decision goes");
    assert!(
        store.receipt(&tid(1), "someday").is_none(),
        "the receipt it wrote goes"
    );
    assert_eq!(
        store.session(1).counts.someday,
        0,
        "the run counts it no more"
    );
    assert_eq!(store.session(1).revision.to_u64(), Some(6));
    assert_eq!(undone.result.deleted_task_id, None);
    // A second Undo finds no decision.
    let gone = refusal(store.decide(&undo_command(&did(1), &tid(1), 3)));
    assert_eq!(gone.reason, Reason::NotFound);
    assert_eq!(the_decision(&decision).id.as_str(), did(1));
}

#[test]
fn review_decisions_026_fr_016_undo_of_a_follow_up_deletes_the_unchanged_follow_up() {
    // test_020_FR_048_undo_of_a_follow_up_deletes_the_unchanged_follow_up
    let mut store = Store::new(&[task_json(&tid(2), "waiting", 3)]);
    let payload =
        json!({"title": "Chase Bob", "follow_up_task_id": tid(50), "new_formulation_id": fid(51)});
    decided(&mut store, "follow_up", payload, 2, 3);
    assert!(store.has_task(&tid(50)));
    assert!(store.receipt(&tid(2), "waiting").is_some());
    let undone = accepted(store.run(&undo_command(&did(1), &tid(2), 3)));
    assert!(!store.has_task(&tid(50)), "the follow-up is deleted");
    assert_eq!(
        undone.result.deleted_task_id.as_ref().map(|id| id.as_str()),
        Some(tid(50).as_str())
    );
    assert!(store.receipt(&tid(2), "waiting").is_none());
    assert_eq!(
        store.task(&tid(2)).revision.to_u64(),
        Some(4),
        "the waiting task is rewritten, once"
    );
    assert!(undone.changes.iter().any(|c| matches!(
        c,
        DomainChange::Tombstone { entity_type: EntityType::Task, record_key } if record_key == &vec![tid(50)]
    )));
}

#[test]
fn review_decisions_026_fr_016_undo_is_unavailable_once_the_follow_up_changed_or_gained_a_row() {
    // test_020_FR_048_undo_after_the_follow_up_changed_is_unavailable,
    // ..._that_gained_a_child_row_is_unavailable
    let base = || {
        let mut store = Store::new(&[task_json(&tid(2), "waiting", 3)]);
        let payload = json!({"title": "Chase Bob", "follow_up_task_id": tid(50), "new_formulation_id": fid(51)});
        decided(&mut store, "follow_up", payload, 2, 3);
        store
    };
    let id = id_of(&json!({"id": tid(50)}));
    type Change = Box<dyn Fn(&mut Store)>;
    let cases: [(&str, Change); 4] = [
        (
            "an edit",
            Box::new(|s| {
                s.read_set
                    .tasks
                    .get_mut(&id_of(&json!({"id": tid(50)})))
                    .expect("task")
                    .revision = 2u64.into()
            }),
        ),
        (
            "a tag link",
            Box::new(|s| {
                s.read_set
                    .tasks
                    .get_mut(&id_of(&json!({"id": tid(50)})))
                    .expect("task")
                    .tag_ids = vec![types::TagId::parse("tag_t1").expect("tag")]
            }),
        ),
        (
            "a subtask",
            Box::new(|s| {
                s.read_set.subtasks.insert(
                types::SubtaskId::parse("subtask_s1").expect("id"),
                serde_json::from_value(json!({"id": "subtask_s1", "task_id": tid(50), "title": "Ask", "state": "open", "order_key": "0", "revision": "1"})).expect("subtask"),
            );
            }),
        ),
        (
            "a comment",
            Box::new(|s| {
                s.read_set.comments.insert(
                types::CommentId::parse("comment_c1").expect("id"),
                serde_json::from_value(json!({"id": "comment_c1", "task_id": tid(50), "body": "Hi", "actor_id": "actor-example", "created_at": NOW, "edited_at": null, "revision": "1"})).expect("comment"),
            );
            }),
        ),
    ];
    for (what, change) in cases {
        let mut store = base();
        change(&mut store);
        let refused = refusal(store.decide(&undo_command(&did(1), &tid(2), 3)));
        assert_eq!(refused.reason, Reason::UndoUnavailable, "{what}");
    }
    // The follow-up already gone does not block the Undo.
    let mut store = base();
    store.read_set.tasks.remove(&id);
    accepted(store.decide(&undo_command(&did(1), &tid(2), 3)));
}

#[test]
fn review_decisions_026_fr_016_undo_after_the_task_changed_the_snapshot_expired_or_off_the_server_is_unavailable()
 {
    // test_020_FR_048_undo_after_the_task_changed_or_the_snapshot_was_purged
    let mut store = asks_store();
    decided(&mut store, "complete", json!({}), 1, 1);
    let ok = undo_command(&did(1), &tid(1), 2);
    accepted(store.decide(&ok));
    // The expected revision names another revision than the task's.
    let stale = refusal(store.decide(&undo_command(&did(1), &tid(1), 1)));
    assert_eq!(stale.reason, Reason::UndoUnavailable);
    // The task moved on since the decision.
    let mut moved = store.clone();
    moved
        .read_set
        .tasks
        .get_mut(&id_of(&json!({"id": tid(1)})))
        .expect("task")
        .revision = 3u64.into();
    let changed = refusal(moved.decide(&undo_command(&did(1), &tid(1), 3)));
    assert_eq!(changed.reason, Reason::UndoUnavailable);
    // Seven days: the deadline is judged from the stored instants, whether or not
    // the retention job has nulled the content.
    for (when, available) in [
        ("2026-10-16T11:59:59Z", true),
        ("2026-10-16T12:00:00Z", false),
        ("2026-11-20T12:00:00Z", false),
    ] {
        let result = store.decide_at(&ok, when, &[]);
        assert_eq!(result.is_ok(), available, "{when}");
        if !available {
            assert_eq!(refusal(result).reason, Reason::UndoUnavailable, "{when}");
        }
    }
    let decision = store.decision(&did(1)).expect("decision");
    assert_eq!(
        decision.undo_available_until.as_ref().map(|i| i.as_str()),
        Some("2026-10-16T12:00:00Z")
    );
    // Purged by the retention job: no private content left.
    let mut purged = store.clone();
    purged
        .read_set
        .decisions
        .get_mut(&DecisionId::parse(did(1)).expect("id"))
        .expect("decision")
        .private = None;
    assert_eq!(refusal(purged.decide(&ok)).reason, Reason::UndoUnavailable);
    // A client without the server's snapshots queues the decision but cannot fabricate its Undo.
    let mut device = asks_store().device();
    decided(&mut device, "complete", json!({}), 1, 1);
    let local = device.decision(&did(1)).expect("decision");
    assert!(local.private.is_none() && local.undo_available_until.is_none());
    assert_eq!(refusal(device.decide(&ok)).reason, Reason::UndoUnavailable);
}

#[test]
fn review_decisions_026_fr_016_undo_keeps_a_receipt_a_later_decision_wrote() {
    // test_020_FR_048_undo_keeps_a_receipt_a_later_decision_wrote
    let mut store = Store::new(&[task_json(&tid(3), "someday", 5)]);
    decided(&mut store, "keep_someday", json!({}), 3, 5);
    // Another decision wrote the current receipt of that task and kind since.
    let mut later = store.clone();
    let receipt = later
        .read_set
        .receipts
        .iter_mut()
        .find(|r| r.task_id.as_str() == tid(3))
        .expect("receipt");
    receipt.decision_id = Some(DecisionId::parse(did(2)).expect("id"));
    let undone = accepted(later.decide(&undo_command(&did(1), &tid(3), 5)));
    assert!(!undone.changes.iter().any(|c| matches!(
        c,
        DomainChange::Tombstone {
            entity_type: EntityType::ReviewReceipt,
            ..
        }
    )));
    // Its own receipt does go.
    let own = accepted(store.decide(&undo_command(&did(1), &tid(3), 5)));
    assert!(own.changes.iter().any(|c| matches!(
        c,
        DomainChange::Tombstone { entity_type: EntityType::ReviewReceipt, record_key } if record_key == &vec![tid(3), "someday".to_owned()]
    )));
}

#[test]
fn review_decisions_026_fr_016_undo_of_return_to_next_puts_the_task_back_in_its_park() {
    // ADR-0027 E6: Undo back into the park reads as it did while parked.
    let parked = with(
        task_json(&tid(1), "someday", 4),
        json!({"consecutive_stalled_formulations": 1, "parked": {
            "at": "2026-10-01T09:00:00Z", "formulation_id": fid(1),
            "private": {"from_revision": "3", "clock_before": {
                "formulation_id": fid(1), "started_at": "2026-09-10T09:00:00Z", "extended_at": null,
                "extension_reason": null, "park_floor_at": null, "stalled_before": 0}}}}),
    );
    let mut store = Store::new(std::slice::from_ref(&parked)).put(
        "park_acks",
        vec![json!({
        "task_id": tid(1), "formulation_id": fid(1), "parked_at": "2026-10-01T09:00:00Z",
        "seen_at": null, "returned_at": null})],
    );
    decided(
        &mut store,
        "return_to_next",
        json!({"title": "Call Bob", "new_formulation_id": fid(51)}),
        1,
        4,
    );
    assert!(
        store.read_set.park_acks[0].returned_at.is_some(),
        "the move returned it"
    );
    accepted(store.run(&undo_command(&did(1), &tid(1), 5)));
    assert!(
        store.read_set.park_acks[0].returned_at.is_none(),
        "back in its park"
    );
    let back = store.task(&tid(1));
    assert_eq!(back.state, TaskState::Someday);
    assert!(back.parked.is_some());
    assert_eq!(back.revision.to_u64(), Some(6));
}

#[test]
fn review_decisions_026_fr_016_undo_keeps_a_floor_written_after_the_decision() {
    // test_020_FR_046_020_FR_048_undo_keeps_a_time_zone_floor_written_after_it
    let mut store = asks_store();
    decided(
        &mut store,
        "extend",
        on_form(1, json!({"reason": "Waiting for the quote"})),
        1,
        1,
    );
    let floor = "2026-10-20T00:00:00Z";
    let task = store
        .read_set
        .tasks
        .get_mut(&id_of(&json!({"id": tid(1)})))
        .expect("task");
    task.formulation.as_mut().expect("a clock").park_floor_at =
        Some(types::Instant::parse(floor).expect("instant"));
    accepted(store.run(&undo_command(&did(1), &tid(1), 2)));
    let restored = store.task(&tid(1));
    let clock = restored.formulation.as_ref().expect("a clock");
    assert_eq!(clock.extended_at, None, "the extension is undone");
    assert_eq!(
        clock.park_floor_at.as_ref().map(|i| i.as_str()),
        Some(floor),
        "the larger floor stays"
    );
}

// ----------------------------------------------------------------- bulk release

fn restart_store(tasks: &[Value]) -> Store {
    Store::new(tasks)
}

/// A Next task old enough for a restart release (28 days of formulation).
fn old_next(n: u64, revision: u64) -> Value {
    next_json(n, revision, "2026-08-20T09:00:00Z")
}

#[test]
fn review_decisions_026_fr_017_restart_release_has_per_item_eligibility_and_skips() {
    // test_020_FR_017_020_FR_032_restart_release_with_server_side_eligibility
    let young = next_json(2, 1, "2026-10-01T09:00:00Z");
    let inbox = task_json(&tid(3), "inbox", 1);
    let store = restart_store(&[old_next(1, 3), young, inbox, old_next(4, 2)])
        .with_sessions(vec![session_json(1, "open")]);
    let command = bulk_command(
        &bid(1),
        "restart",
        &[
            (&tid(1), 3),
            (&tid(2), 1),
            (&tid(3), 1),
            (&tid(9), 1),
            (&tid(4), 7),
            (&tid(1), 99),
        ],
        Some(&sid(1)),
    );
    let set = accepted(store.decide(&command));
    let release = the_release(&set);
    let released: Vec<_> = release
        .released
        .iter()
        .map(|i| (i.task_id.as_str().to_owned(), i.revision_after.to_u64()))
        .collect();
    assert_eq!(
        released,
        [(tid(1), Some(4))],
        "the first revision named for a task counts"
    );
    let skipped: Vec<_> = release
        .skipped
        .iter()
        .map(|i| (i.task_id.as_str().to_owned(), i.reason.as_str()))
        .collect();
    assert_eq!(
        skipped,
        [
            (tid(2), "not_eligible"),
            (tid(3), "not_eligible"),
            (tid(9), "not_eligible"),
            (tid(4), "stale")
        ]
    );
    assert_eq!(
        release.session_id.as_ref().map(|s| s.as_str()),
        Some(sid(1).as_str())
    );
    assert_eq!(
        (
            release.created_at.as_str(),
            release.undone_at.as_ref(),
            release.undo.as_ref()
        ),
        (NOW, None, None)
    );
    // The accepted subset and its metadata commit once: tasks, receipts, then the record.
    assert_eq!(set.changes.len(), 3);
    let moved = the_task(&set);
    assert_eq!(
        (moved.state, moved.revision.to_u64()),
        (TaskState::Someday, Some(4))
    );
    assert!(
        moved.formulation.is_none() && moved.parked.is_none(),
        "a release is not a park"
    );
    assert_eq!(
        moved.consecutive_stalled_formulations, 1,
        "the stalled count survives the release"
    );
    let DomainChange::Upsert(Record::ReviewReceipt(receipt)) = &set.changes[1] else {
        panic!("the receipt")
    };
    assert_eq!(
        (
            receipt.kind.as_str(),
            receipt.source.as_str(),
            receipt.task_revision.to_u64()
        ),
        ("someday", "release", Some(4))
    );
    assert_eq!(
        receipt.bulk_id.as_ref().map(|b| b.as_str()),
        Some(bid(1).as_str())
    );
    assert_eq!(receipt.decision_id, None);
    assert_eq!(set.result.released.len(), 1);
    assert_eq!(set.result.skipped.len(), 4);
    // The run's counters are not touched by a release.
    assert!(
        !set.changes
            .iter()
            .any(|c| matches!(c, DomainChange::Upsert(Record::ReviewSession(_))))
    );
    // An unknown run is recorded without one.
    let unknown = accepted(store.decide(&bulk_command(
        &bid(1),
        "restart",
        &[(&tid(1), 3)],
        Some(&sid(9)),
    )));
    assert_eq!(the_release(&unknown).session_id, None);
}

#[test]
fn review_decisions_026_fr_030_inbox_remainder_release_and_undo() {
    // test_020_FR_030_inbox_remainder_release_and_undo
    let mut store = restart_store(&[
        task_json(&tid(1), "inbox", 2),
        task_json(&tid(2), "next", 2),
        task_json(&tid(3), "inbox", 4),
    ]);
    let set = accepted(store.run(&bulk_command(
        &bid(1),
        "inbox_remainder",
        &[(&tid(1), 2), (&tid(2), 2), (&tid(3), 1)],
        None,
    )));
    let release = the_release(&set);
    assert_eq!(release.released.len(), 1);
    assert_eq!(
        release
            .skipped
            .iter()
            .map(|i| (i.task_id.as_str(), i.reason.as_str()))
            .collect::<Vec<_>>(),
        [
            (tid(2).as_str(), "not_eligible"),
            (tid(3).as_str(), "stale")
        ]
    );
    let private = release.released[0].private.as_ref().expect("private");
    assert_eq!(
        (private.previous_state, private.clock_before.is_none()),
        (types::OpenList::Inbox, true)
    );
    assert_eq!(store.task(&tid(1)).state, TaskState::Someday);
    let undone = accepted(store.run(&bulk_undo_command(&bid(1))));
    assert_eq!(store.task(&tid(1)).state, TaskState::Inbox);
    assert_eq!(store.task(&tid(1)).revision.to_u64(), Some(4));
    let result = undone.result.bulk_undo.as_ref().expect("a result");
    assert_eq!(result.restored.len(), 1);
    assert!(
        store.receipt(&tid(1), "someday").is_none(),
        "the release receipt goes with the Undo"
    );
    // Seven days later the same release can no longer be undone (before undoing it).
    let mut late = restart_store(&[task_json(&tid(1), "inbox", 2)]);
    accepted(late.run(&bulk_command(
        &bid(1),
        "inbox_remainder",
        &[(&tid(1), 2)],
        None,
    )));
    let refused = refusal(late.decide_at(&bulk_undo_command(&bid(1)), "2026-10-16T12:00:00Z", &[]));
    assert_eq!(refused.reason, Reason::UndoUnavailable);
    accepted(late.decide_at(&bulk_undo_command(&bid(1)), "2026-10-16T11:59:59Z", &[]));
    // test_020_FR_030_an_inbox_release_undo_is_unavailable_after_seven_days
}

#[test]
fn review_decisions_026_fr_017_bulk_undo_restores_the_next_clock_and_skips_changed_items() {
    // test_020_FR_011_an_undone_release_answers_its_stored_undo_result, ..._per-item stale
    let mut store = restart_store(&[old_next(1, 3), old_next(2, 3)]);
    let before = store.task(&tid(1)).clone();
    accepted(store.run(&bulk_command(
        &bid(1),
        "restart",
        &[(&tid(1), 3), (&tid(2), 3)],
        None,
    )));
    // One task is edited after the release.
    store
        .read_set
        .tasks
        .get_mut(&id_of(&json!({"id": tid(2)})))
        .expect("task")
        .revision = 9u64.into();
    let undone = accepted(store.run_at(&bulk_undo_command(&bid(1)), "2026-10-09T12:00:30Z", &[]));
    let result = undone.result.bulk_undo.as_ref().expect("a result");
    assert_eq!(
        result
            .restored
            .iter()
            .map(|t| t.as_str())
            .collect::<Vec<_>>(),
        [tid(1)]
    );
    assert_eq!(
        result
            .skipped
            .iter()
            .map(|s| (s.task_id.as_str(), s.reason.as_str()))
            .collect::<Vec<_>>(),
        [(tid(2).as_str(), "stale")]
    );
    let restored = store.task(&tid(1));
    assert_eq!(
        restored.formulation, before.formulation,
        "the clock exactly as it was"
    );
    assert_eq!(
        (restored.state, restored.revision.to_u64()),
        (TaskState::Next, Some(5))
    );
    assert_eq!(
        restored.consecutive_stalled_formulations,
        before.consecutive_stalled_formulations
    );
    assert!(store.receipt(&tid(1), "someday").is_none());
    assert!(
        store.receipt(&tid(2), "someday").is_some(),
        "a stale item keeps its receipt"
    );
    let release = store
        .read_set
        .bulk_releases
        .values()
        .next()
        .expect("a record");
    assert_eq!(
        release.undone_at.as_ref().map(|i| i.as_str()),
        Some("2026-10-09T12:00:30Z")
    );
    // Asked again, at any age, it answers its stored result and changes nothing.
    let again = accepted(store.decide_at(&bulk_undo_command(&bid(1)), "2027-03-01T00:00:00Z", &[]));
    assert_eq!(
        (again.outcome, again.changes.len()),
        (ChangeOutcome::NoOp, 0)
    );
    assert_eq!(again.result.bulk_undo.as_ref(), Some(result));
    // No release: not found.
    assert_eq!(
        refusal(store.decide(&bulk_undo_command(&bid(8)))).reason,
        Reason::NotFound
    );
}

#[test]
fn review_decisions_026_fr_017_bulk_undo_needs_the_next_clock_and_the_server_content() {
    let mut store = restart_store(&[old_next(1, 3)]);
    accepted(store.run(&bulk_command(&bid(1), "restart", &[(&tid(1), 3)], None)));
    // A Next item whose clock the retention job nulled cannot be undone.
    let mut nulled = store.clone();
    let record = nulled
        .read_set
        .bulk_releases
        .values_mut()
        .next()
        .expect("record");
    record.released[0]
        .private
        .as_mut()
        .expect("private")
        .clock_before = None;
    assert_eq!(
        refusal(nulled.decide(&bulk_undo_command(&bid(1)))).reason,
        Reason::UndoUnavailable
    );
    // So cannot an item whose private content is gone, or a release made off the server.
    let mut gone = store.clone();
    gone.read_set
        .bulk_releases
        .values_mut()
        .next()
        .expect("record")
        .released[0]
        .private = None;
    assert_eq!(
        refusal(gone.decide(&bulk_undo_command(&bid(1)))).reason,
        Reason::UndoUnavailable
    );
    let mut device = restart_store(&[old_next(1, 3)]).device();
    accepted(device.run(&bulk_command(&bid(1), "restart", &[(&tid(1), 3)], None)));
    assert!(
        device
            .read_set
            .bulk_releases
            .values()
            .next()
            .expect("record")
            .released[0]
            .private
            .is_none()
    );
    assert_eq!(
        refusal(device.decide(&bulk_undo_command(&bid(1)))).reason,
        Reason::UndoUnavailable
    );
    // A release receipt another release or decision wrote since stays.
    let mut overwritten = store.clone();
    overwritten.read_set.receipts[0].bulk_id = Some(types::BulkId::parse(bid(2)).expect("id"));
    let undone = accepted(overwritten.decide(&bulk_undo_command(&bid(1))));
    assert!(
        !undone
            .changes
            .iter()
            .any(|c| matches!(c, DomainChange::Tombstone { .. }))
    );
}

#[test]
fn review_decisions_026_fr_005_a_stored_bulk_id_is_a_matching_replay_or_a_conflict() {
    // test_020_FR_011_a_bulk_release_replays_by_key / matching-record form
    let mut store = restart_store(&[old_next(1, 3), old_next(2, 3)]);
    let first = bulk_command(&bid(1), "restart", &[(&tid(1), 3), (&tid(2), 3)], None);
    accepted(store.run(&first));
    let again = accepted(store.decide(&first));
    assert_eq!(
        (again.outcome, again.changes.len()),
        (ChangeOutcome::NoOp, 0)
    );
    // The same set in another order and a stale revision is still the same release.
    let reordered = bulk_command(&bid(1), "restart", &[(&tid(2), 99), (&tid(1), 3)], None);
    assert_eq!(
        accepted(store.decide(&reordered)).outcome,
        ChangeOutcome::NoOp
    );
    let other_kind = refusal(store.decide(&bulk_command(
        &bid(1),
        "inbox_remainder",
        &[(&tid(1), 3), (&tid(2), 3)],
        None,
    )));
    assert_eq!(other_kind.reason, Reason::IdAlreadyExists);
    let other_set = refusal(store.decide(&bulk_command(&bid(1), "restart", &[(&tid(1), 3)], None)));
    assert_eq!(other_set.reason, Reason::IdAlreadyExists);
    // A skipped item counts as asked about.
    let mut skipping = restart_store(&[old_next(1, 3)]);
    let ask = bulk_command(&bid(1), "restart", &[(&tid(1), 3), (&tid(9), 1)], None);
    accepted(skipping.run(&ask));
    assert_eq!(accepted(skipping.decide(&ask)).outcome, ChangeOutcome::NoOp);
    // The ID shape is the bulk reference's.
    let bad = bulk_command("bulk_not-a-uuid", "restart", &[(&tid(1), 3)], None);
    assert_eq!(refusal(store.decide(&bad)).reason, Reason::InvalidValue);
}

#[test]
fn review_decisions_026_fr_017_an_empty_release_still_commits_its_record() {
    let store = restart_store(&[]);
    let set = accepted(store.decide(&bulk_command(&bid(1), "restart", &[], None)));
    assert_eq!(set.outcome, ChangeOutcome::Applied);
    assert_eq!(set.changes.len(), 1);
    assert!(the_release(&set).released.is_empty() && the_release(&set).skipped.is_empty());
}

// ------------------------------------------------------------------- dispatch

#[test]
fn review_decisions_026_fr_002_the_family_handles_exactly_its_four_commands() {
    let owned = [
        decide_command(&tid(1), &did(1), "complete", json!({}), 1),
        undo_command(&did(1), &tid(1), 1),
        bulk_command(&bid(1), "restart", &[], None),
        bulk_undo_command(&bid(1)),
    ];
    for command in &owned {
        assert!(
            review_decisions::handles(&command.command),
            "{:?}",
            command.command_type()
        );
    }
    let other = command(
        "task.transition",
        &tid(1),
        json!({"action": "complete"}),
        vec![check("task", &tid(1), 1)],
    );
    assert!(!review_decisions::handles(&other.command));
    let store = asks_store();
    let refused = refusal(store.decide(&other));
    assert_eq!(
        (refused.reason, refused.field.as_deref()),
        (Reason::InvalidPayload, Some("type"))
    );
    // The park acknowledgement is the park family's, not this one's.
    let ack = command("review.parks_ack", &tid(1), json!({"items": []}), vec![]);
    assert!(!review_decisions::handles(&ack.command));
}

#[test]
fn review_decisions_026_fr_002_the_family_reuses_the_clock_park_and_task_rules_it_does_not_copy() {
    // A complete decision of an overdue Next task closes the formulation as
    // stalled (T-033) and is the task lifecycle's own completion.
    let store = Store::new(&[next_json(1, 1, "2026-09-10T09:00:00Z")]);
    let via_decision =
        accepted(store.decide(&decide_command(&tid(1), &did(1), "complete", json!({}), 1)));
    let transition = command(
        "task.transition",
        &tid(1),
        json!({"action": "complete"}),
        vec![check("task", &tid(1), 1)],
    );
    let via_rules = accepted(task_rules::decide(
        &store.read_set,
        &transition,
        &inputs_with(NOW, &[], true),
    ));
    assert_eq!(the_task(&via_decision), the_task(&via_rules));
    let _ = (ParkReturn::NotAReturn, CalendarDay::parse_iso("2026-10-09"));
}
