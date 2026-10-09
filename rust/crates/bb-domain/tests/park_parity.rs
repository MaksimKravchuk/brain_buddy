//! Parity of auto-park, the human yield and park acknowledgement with the server
//! (tasks.md T014, ADR-0027).
//!
//! The oracle is the existing one, never the Rust output:
//!
//! * `review_formulation_vectors.json` (auto-park, yield reversal, sweep gap),
//! * `review_flow_vectors.json` (`while_away`),
//! * `review_traces_tasks.json` (TR-003, TR-004, TR-006), replayed against a
//!   small in-memory server that routes every request to the park functions and
//!   to the formulation clock, as `ReviewService` does,
//! * scenarios taken from `backend/tests/test_review_auto_park.py`,
//! * the command level (`park::handles` / `park::decide`, T062): the same
//!   `auto_park` vectors replayed through `review.auto_park`, and the server
//!   scenarios of `ReviewService.auto_park` and `acknowledge_parks` through
//!   the change sets of `review.auto_park` and `review.parks_ack`.
//!
//! The family sources are compiled in place (`#[path]`) with the crate paths
//! they use inside `bb-domain`, so this runner does not depend on how the
//! library registers the modules. Every test counts the cases it executed, so an
//! empty or truncated section fails.

mod support;

pub use bb_domain::{calendar, normalization, types};

#[allow(dead_code, unused_imports)]
#[path = "../src/formulation.rs"]
mod formulation;
#[allow(dead_code)]
#[path = "../src/park.rs"]
mod park;

use std::collections::{BTreeMap, BTreeSet};
use std::sync::OnceLock;

use bb_domain::calendar::{CalendarDay, UtcInstant};
use bb_domain::types::{
    ChangeOutcome, ChangeSet, DecisionType, DomainChange, DomainCommand, DomainError, EntityType,
    ExecutionInputs, ParkAck, ParkSource, ParksAck, ReadSet, Reason, Record, ResultRefs,
    ReviewSettings, Task, TaskState,
};
use formulation::{
    ClockBefore, DecisionInput, FormulationError, OwnerClockSettings, ParkMarker, TaskClock,
};
use park::{
    AutoPark, DeviceParkRequest, NotApplied, ParkReturn, ParkRow, SweepStep, WhileAwayContext,
    YieldQuery,
};
use serde_json::{Value, json};
use support::{cases, text};

// ------------------------------------------------------------------ helpers

fn at(iso: &str) -> UtcInstant {
    UtcInstant::parse_rfc3339(iso).unwrap_or_else(|error| panic!("{iso}: {error}"))
}

fn at_opt(value: &Value) -> Option<UtcInstant> {
    value.as_str().map(at)
}

fn iso(value: Option<UtcInstant>) -> Value {
    value.map_or(Value::Null, |instant| Value::String(instant.to_rfc3339()))
}

fn string(value: &Value) -> Option<String> {
    value.as_str().map(str::to_owned)
}

fn count(value: &Value) -> u32 {
    u32::try_from(value.as_u64().expect("a count")).expect("a small count")
}

fn settings_from(raw: &Value) -> OwnerClockSettings {
    OwnerClockSettings::new(
        count(&raw["threshold_days"]),
        text(raw, "time_zone"),
        at_opt(&raw["owner_park_floor_at"]),
        at_opt(&raw["activated_at"]),
    )
    .unwrap_or_else(|error| panic!("settings {raw}: {error}"))
}

fn settings_to(settings: &OwnerClockSettings) -> Value {
    json!({
        "threshold_days": settings.threshold_days(),
        "time_zone": settings.time_zone(),
        "owner_park_floor_at": iso(settings.owner_park_floor_at()),
        "activated_at": iso(settings.activated_at()),
    })
}

/// A started clock without an explicit id gets `form_<task id>`, as the server
/// vector helper does.
fn clock_from(raw: &Value, task_id: &str) -> TaskClock {
    let started = at_opt(&raw["formulation_started_at"]);
    let default_id = started.map(|_| format!("form_{task_id}"));
    let formulation_id = match raw.get("formulation_id") {
        Some(value) => string(value),
        None => default_id,
    };
    let parked = raw
        .get("parked")
        .filter(|value| !value.is_null())
        .map(|parked| ParkMarker {
            at: at(text(parked, "at")),
            formulation_id: text(parked, "formulation_id").to_owned(),
            from_revision: parked["from_revision"].as_u64(),
            clock_before: Some(ClockBefore {
                started_at: at(text(&parked["clock_before"], "started_at")),
                extended_at: at_opt(&parked["clock_before"]["extended_at"]),
                extension_reason: string(&parked["clock_before"]["extension_reason"]),
                park_floor_at: at_opt(&parked["clock_before"]["park_floor_at"]),
                stalled_before: count(&parked["clock_before"]["stalled_before"]),
            }),
        });
    TaskClock {
        state: raw["state"]
            .as_str()
            .map(|name| TaskState::from_wire(name).expect("a task state")),
        title: string(&raw["title"]),
        revision: raw.get("revision").and_then(Value::as_u64).unwrap_or(1),
        formulation_id,
        formulation_started_at: started,
        formulation_extended_at: at_opt(&raw["formulation_extended_at"]),
        formulation_extension_reason: string(&raw["formulation_extension_reason"]),
        formulation_park_floor_at: at_opt(&raw["formulation_park_floor_at"]),
        consecutive_stalled_formulations: raw
            .get("consecutive_stalled_formulations")
            .map_or(0, count),
        due_date: raw["due_date"]
            .as_str()
            .map(|day| CalendarDay::parse_iso(day).expect("a calendar day")),
        parked,
    }
}

fn clock_to(clock: &TaskClock) -> Value {
    let parked = clock.parked.as_ref().map_or(Value::Null, |marker| {
        let before = marker
            .clock_before
            .as_ref()
            .expect("vector parks keep a clock");
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

/// Every key listed in `expect` equals the same key of `actual`.
fn assert_subset(expect: &Value, actual: &Value, id: &str) {
    for (key, wanted) in expect.as_object().expect("an expect object") {
        assert_eq!(&actual[key], wanted, "{id}: {key}");
    }
}

/// Fails unless exactly `expected` cases ran, and at least one.
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

// -------------------------------------------------- formulation vectors, park layer

#[test]
fn park_026_fr_013_auto_park_vectors_match_the_server() {
    let section = transitions_of("auto_park");
    let mut ran = 0;
    for vector in &section {
        let id = text(vector, "id");
        let clock = clock_from(&vector["before"], "task_vector");
        let settings = settings_from(&vector["settings"]);
        let now = at(text(vector, "now"));
        let outcome = park::attempt_park("task_vector", &clock, &settings, now, ParkSource::Sweep);
        let expect = &vector["expect"];
        if expect.get("applied") == Some(&Value::Bool(false)) {
            assert!(!outcome.applied(), "{id}: parked");
        } else {
            let AutoPark::Applied(parked) = outcome else {
                panic!("{id}: not parked");
            };
            assert_subset(expect, &clock_to(&parked.clock), id);
            // The row and the key follow the revision the park was made from.
            assert_eq!(parked.from_revision, clock.revision, "{id}");
            assert_eq!(parked.row.parked_at, now, "{id}");
            assert_eq!(parked.row.seen_at, None, "{id}");
            assert_eq!(parked.row.returned_at, None, "{id}");
            assert_eq!(parked.row.source, Some(ParkSource::Sweep), "{id}");
            assert_eq!(
                parked.key,
                format!(
                    "auto-park:task_vector:{}:{}",
                    clock.formulation_id.as_deref().expect("a formulation"),
                    clock.revision
                ),
                "{id}"
            );
        }
        ran += 1;
    }
    ran_all("auto_park", ran, section.len());
}

#[test]
fn park_026_fr_013_yield_reversal_vectors_match_the_server() {
    let section = transitions_of("yield_reversal");
    let mut ran = 0;
    for vector in &section {
        let id = text(vector, "id");
        let clock = clock_from(&vector["before"], "task_vector");
        let settings = settings_from(&vector["settings"]);
        let now = at(text(vector, "now"));
        let event = &vector["event"]["decision"];
        let decision = DecisionType::from_wire(text(event, "decision_type")).expect("a type");
        let marker = clock.parked.as_ref().expect("a parked task");
        // A decision made one second before the park, on the parked formulation,
        // against the revision the park was made from: the card the person saw.
        let query = YieldQuery {
            decision,
            formulation_id: Some(&marker.formulation_id),
            expected_revision: marker.from_revision.expect("a private revision"),
            client_decided_at: Some(marker.at.plus_seconds(-1)),
        };
        assert!(park::yields(&clock, &query), "{id}: no yield");
        let input = DecisionInput {
            title: event.get("title").and_then(Value::as_str),
            reason: event.get("reason").and_then(Value::as_str),
            new_formulation_id: event.get("new_formulation_id").and_then(Value::as_str),
        };
        let yielded = park::decide_through_yield(&clock, &query, &settings, now, &input)
            .unwrap_or_else(|error| panic!("{id}: {error}"))
            .unwrap_or_else(|| panic!("{id}: not yielded"));
        assert!(yielded.reset_returned, "{id}");
        assert_subset(&vector["expect"], &clock_to(&yielded.clock), id);
        ran += 1;
    }
    ran_all("yield_reversal", ran, section.len());
}

#[test]
fn park_026_sc_006_sweep_gap_vectors_match_the_server() {
    let section = transitions_of("sweep_gap");
    let mut ran = 0;
    for vector in &section {
        let id = text(vector, "id");
        let settings = settings_from(&vector["settings"]);
        let now = at(text(vector, "now"));
        // The vector's event is the gap itself: no earlier evaluation recorded.
        let note = park::note_effective_sweep(&settings, None, now);
        assert!(note.gap, "{id}");
        assert_eq!(note.last_effective_sweep_at, now, "{id}");
        assert_subset(&vector["expect_settings"], &settings_to(&note.settings), id);
        ran += 1;
    }
    ran_all("sweep_gap", ran, section.len());
}

// ----------------------------------------------------------- while-away vectors

#[test]
fn park_026_fr_015_while_away_vectors_match_the_server() {
    let section = cases(support::flow(), "while_away");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        let context = WhileAwayContext::from_wire(text(case, "context")).expect("a context");
        let day = |value: &Value| {
            value
                .as_str()
                .map(|text| CalendarDay::parse_iso(text).expect("a calendar day"))
        };
        let shown = park::show_while_away(
            context,
            case["has_unseen"].as_bool().expect("has_unseen"),
            day(&case["last_shown_day"]),
            day(&case["today"]).expect("today"),
        );
        assert_eq!(shown, case["expect"].as_bool().expect("expect"), "{id}");
        ran += 1;
    }
    ran_all("while_away", ran, section.len());
}

// ------------------------------------------------------ the in-memory server

/// What `ReviewService` and `TaskService` do with a request, reduced to the
/// routes the park traces use. Every park decision goes through `park`.
struct Sim {
    now: UtcInstant,
    exposed: bool,
    settings: OwnerClockSettings,
    last_sweep: Option<UtcInstant>,
    tasks: BTreeMap<String, SimTask>,
    rows: BTreeMap<(String, String), ParkRow>,
    keys: BTreeSet<String>,
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
            last_sweep: None,
            tasks: BTreeMap::new(),
            rows: BTreeMap::new(),
            keys: BTreeSet::new(),
            next_id: 0,
            out_of_scope: Vec::new(),
        }
    }

    fn row_of(&self, task_id: &str, formulation_id: &str) -> Option<ParkRow> {
        self.rows
            .get(&(task_id.to_owned(), formulation_id.to_owned()))
            .cloned()
    }

    fn store_row(&mut self, row: ParkRow) {
        self.rows
            .insert((row.task_id.clone(), row.formulation_id.clone()), row);
    }

    fn view(&self, id: &str) -> Value {
        let task = &self.tasks[id];
        let clock = &task.clock;
        let formulation = formulation::derive_instants(clock, &self.settings)
            .zip(clock.formulation_id.as_ref())
            .map_or(Value::Null, |(instants, formulation_id)| {
                json!({
                    "id": formulation_id,
                    "started_at": iso(clock.formulation_started_at),
                    "ask_at": iso(Some(instants.ask_at)),
                    "park_due_at": iso(Some(instants.park_due_at)),
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
                "at": iso(Some(marker.at)),
                "formulation_id": marker.formulation_id,
            })),
        })
    }

    fn advance(&mut self, by: &Value) {
        let unit =
            |key: &str, seconds: i64| by.get(key).and_then(Value::as_i64).unwrap_or(0) * seconds;
        let total = unit("days", 86_400) + unit("hours", 3_600) + unit("minutes", 60);
        self.now = self.now.plus_seconds(total);
    }

    /// One maintenance sweep with the 60 s loop having kept running (the trace
    /// convention): an effective evaluation a minute ago, so no gap floor.
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
        for batch in plan.due.chunks(park::SWEEP_BATCH) {
            for id in batch {
                self.next_id += 1;
                let repair_id = format!("form_repair_{}", self.next_id);
                let clock = self.tasks[id].clock.clone();
                match park::sweep_task(id, &clock, &self.settings, self.now, &repair_id) {
                    SweepStep::Skipped => {}
                    SweepStep::Repaired(repaired) => {
                        self.tasks.get_mut(id).expect("task").clock = *repaired;
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
    }

    /// `None` is a route of another rule family (task edits are the exception:
    /// they only bump the revision).
    fn request(&mut self, method: &str, path: &str, body: &Value) -> Option<Reply> {
        let segments: Vec<&str> = path.trim_matches('/').split('/').collect();
        match (method, segments.as_slice()) {
            ("POST", ["api", "review", "explainer", "acknowledge"]) => Some(self.activate(body)),
            ("POST", ["api", "tasks"]) => Some(self.create(body)),
            ("GET", ["api", "tasks", id]) => Some(reply(200, self.view(id))),
            ("PATCH", ["api", "tasks", id]) => Some(self.patch(id, body)),
            ("POST", ["api", "tasks", id, "auto-park"]) => Some(self.device_park(id, body)),
            ("POST", ["api", "tasks", id, "decisions"]) => Some(self.decide(id, body)),
            ("POST", ["api", "review", "parks", "acknowledge"]) => Some(self.acknowledge(body)),
            _ => None,
        }
    }

    fn activate(&mut self, body: &Value) -> Reply {
        let zone = body.get("time_zone").and_then(Value::as_str);
        let activated =
            formulation::activate_owner(&self.settings, self.now, zone).expect("activation");
        if activated != self.settings {
            let ids: Vec<String> = self.tasks.keys().cloned().collect();
            for id in ids {
                self.next_id += 1;
                let form = format!("form_activation_{}", self.next_id);
                let task = self.tasks.get_mut(&id).expect("task");
                task.clock = formulation::activate_clock(&task.clock, self.now, &form);
            }
        }
        self.settings = activated;
        reply(200, json!({ "explainer_seen": true }))
    }

    fn create(&mut self, body: &Value) -> Reply {
        assert_eq!(text(body, "state"), "next", "the traces create in Next");
        self.next_id += 1;
        let id = format!("task_sim_{}", self.next_id);
        let clock = formulation::create_in_next(
            text(body, "title"),
            text(body, "new_formulation_id"),
            self.now,
        );
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
        task.details = string(&body["details"]);
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

    fn decide(&mut self, id: &str, body: &Value) -> Reply {
        let decision = DecisionType::from_wire(text(body, "type")).expect("a decision type");
        let query = YieldQuery {
            decision,
            formulation_id: body.get("formulation_id").and_then(Value::as_str),
            expected_revision: body["expected_revision"].as_u64().expect("a revision"),
            client_decided_at: at_opt(&body["client_decided_at"]),
        };
        let input = DecisionInput {
            title: body.get("title").and_then(Value::as_str),
            reason: body.get("reason").and_then(Value::as_str),
            new_formulation_id: body.get("new_formulation_id").and_then(Value::as_str),
        };
        let before = self.tasks[id].clock.clone();
        let (after, yielded) =
            match park::decide_through_yield(&before, &query, &self.settings, self.now, &input) {
                Ok(Some(done)) => {
                    // The reversal is not a return: `returned_at` reads null again.
                    let formulation_id = &before.parked.as_ref().expect("parked").formulation_id;
                    let row = self.row_of(id, formulation_id);
                    if let Some(row) = park::set_returned(row.as_ref(), None) {
                        self.store_row(row);
                    }
                    (done.clock, true)
                }
                Ok(None) => {
                    if query.expected_revision != before.revision {
                        return reply(409, Value::Null);
                    }
                    let stale = before.state == Some(TaskState::Next)
                        && query
                            .formulation_id
                            .is_some_and(|named| before.formulation_id.as_deref() != Some(named));
                    if stale {
                        return reply(409, Value::Null);
                    }
                    match formulation::decide(&before, decision, &self.settings, self.now, &input) {
                        Ok(after) => (after, false),
                        Err(FormulationError::DecisionNotAllowed) => {
                            return reply(409, Value::Null);
                        }
                        Err(error) => panic!("{error}"),
                    }
                }
                Err(error) => panic!("{error}"),
            };
        if let ParkReturn::Returned(row) =
            park::note_park_return(&before, after.state, |form| self.row_of(id, form), self.now)
        {
            self.store_row(row);
        }
        let task = self.tasks.get_mut(id).expect("task");
        task.clock = after;
        if decision == DecisionType::Waiting {
            task.waiting_for = string(&body["waiting_for"]);
        }
        reply(
            200,
            json!({
                "decision": { "type": decision.as_str(), "yielded_auto_park": yielded },
                "task": self.view(id),
            }),
        )
    }

    fn acknowledge(&mut self, body: &Value) -> Reply {
        let request: ParksAck = serde_json::from_value(body.clone()).expect("a park ack body");
        let result = park::acknowledge_parks(&request, |t, f| self.row_of(t, f), self.now);
        for row in park::rows_marked_seen(&result, |t, f| self.row_of(t, f)) {
            self.store_row(row);
        }
        reply(204, Value::Null)
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

/// Replays a recorded trace. Returns the number of requests the park rules
/// answered and the names of the steps that belong to other rule families.
fn replay(id: &str) -> (usize, Vec<String>) {
    let trace = traces()["traces"]
        .as_array()
        .expect("traces")
        .iter()
        .find(|trace| text(trace, "id") == id)
        .unwrap_or_else(|| panic!("trace {id} is not in the file"));
    let mut sim = Sim::new(text(trace, "start"), text(trace, "flag") == "on");
    let mut captured = BTreeMap::new();
    let mut answered = 0;
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
            let Some(response) =
                sim.request(text(&request, "method"), text(&request, "path"), &body)
            else {
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
                for (variable, path) in names.as_object().expect("capture map") {
                    let found = path
                        .as_str()
                        .expect("a path")
                        .split('.')
                        .fold(&response.body, |node, key| &node[key]);
                    captured.insert(
                        variable.clone(),
                        found.as_str().expect("a captured id").to_owned(),
                    );
                }
            }
            answered += 1;
        }
    }
    (answered, sim.out_of_scope)
}

#[test]
fn park_026_fr_013_trace_a_device_park_the_server_disagrees_with_is_applied_false() {
    let (answered, other) = replay("TR-003");
    assert_eq!(answered, 3, "acknowledge, create, the device park");
    assert!(other.is_empty(), "{other:?}");
}

#[test]
fn park_026_fr_013_trace_an_offline_decision_before_the_park_yields_it_and_keeps_replayed_notes() {
    let (answered, other) = replay("TR-004");
    assert_eq!(
        answered, 6,
        "every request step; the advance and the sweep are not requests"
    );
    assert!(other.is_empty(), "{other:?}");
}

#[test]
fn park_026_fr_015_trace_with_the_flag_off_a_device_park_is_applied_false_and_acks_are_accepted() {
    let (answered, other) = replay("TR-006");
    // Review state, settings and Undo belong to other rule families.
    assert_eq!(
        answered, 5,
        "acknowledge, create, park, decision, parks ack"
    );
    assert_eq!(
        other,
        [
            "the gated read is hidden",
            "a queued settings change is accepted",
            "a queued undo is accepted"
        ]
    );
}

// ------------------------------------------------- scenarios of test_review_auto_park.py

const START: &str = "2026-10-09T14:02:00Z";

/// A Next task created at the start, an activated owner, 22 days later: due.
fn due_sim() -> (Sim, String, String) {
    let mut sim = Sim::new(START, true);
    sim.request("POST", "/api/review/explainer/acknowledge", &json!({}));
    let created = sim
        .request(
            "POST",
            "/api/tasks",
            &json!({"title": "Call Bob", "state": "next",
                    "new_formulation_id": "form_0b0e1f30-0000-4000-8000-0000000000f1"}),
        )
        .expect("created");
    let id = created.body["id"].as_str().expect("id").to_owned();
    sim.advance(&json!({"days": 22}));
    (
        sim,
        id,
        "form_0b0e1f30-0000-4000-8000-0000000000f1".to_owned(),
    )
}

#[test]
fn park_026_fr_013_a_second_device_park_of_the_same_formulation_is_a_no_op() {
    let (mut sim, id, form) = due_sim();
    let path = format!("/api/tasks/{id}/auto-park");
    let body = json!({ "formulation_id": form });
    sim.last_sweep = Some(sim.now.plus_seconds(-60));
    let first = sim.request("POST", &path, &body).expect("routed");
    let second = sim.request("POST", &path, &body).expect("routed");
    assert_eq!((first.status, second.status), (200, 200));
    assert_eq!(first.body["applied"], true);
    assert_eq!(first.body["task"]["state"], "someday");
    assert_eq!(second.body["applied"], false);
    let row = sim.row_of(&id, &form).expect("a park row");
    assert_eq!(row.source, Some(ParkSource::Device));
}

#[test]
fn park_026_fr_013_a_device_park_is_applied_false_unless_the_server_agrees() {
    let (mut sim, id, form) = due_sim();
    sim.last_sweep = Some(sim.now.plus_seconds(-60));
    let clock = sim.tasks[&id].clock.clone();
    let device = |sim: &Sim, formulation_id: &str, exposed: bool, clock: &TaskClock| {
        park::device_auto_park(
            clock,
            &sim.settings,
            &DeviceParkRequest {
                task_id: &id,
                formulation_id,
                exposed,
                last_effective_sweep_at: sim.last_sweep,
            },
            sim.now,
        )
    };
    // The flag is off: no park and no bookkeeping.
    let off = device(&sim, &form, false, &clock);
    assert_eq!(off.outcome, AutoPark::NotApplied(NotApplied::NotExposed));
    assert!(off.sweep.is_none());
    // Another formulation.
    let other = device(
        &sim,
        "form_0b0e1f30-0000-4000-8000-0000000000f2",
        true,
        &clock,
    );
    assert_eq!(
        other.outcome,
        AutoPark::NotApplied(NotApplied::FormulationChanged)
    );
    // Not due yet.
    let fresh = formulation::create_in_next("Fresh", &form, sim.now);
    let early = device(&sim, &form, true, &fresh);
    assert_eq!(early.outcome, AutoPark::NotApplied(NotApplied::NotDue));
    // Not activated: nothing parks and the sweep note is not taken.
    let mut inactive = Sim::new(START, true);
    inactive.advance(&json!({"days": 30}));
    let task = formulation::create_in_next("Old", &form, at(START));
    let unactivated = park::device_auto_park(
        &task,
        &inactive.settings,
        &DeviceParkRequest {
            task_id: "task_x",
            formulation_id: &form,
            exposed: true,
            last_effective_sweep_at: None,
        },
        inactive.now,
    );
    assert_eq!(
        unactivated.outcome,
        AutoPark::NotApplied(NotApplied::NotParkable)
    );
    assert!(unactivated.sweep.is_none());
    // A task outside Next never parks.
    let waiting = TaskClock {
        state: Some(TaskState::Waiting),
        ..clock.clone()
    };
    assert_eq!(
        device(&sim, &form, true, &waiting).outcome,
        AutoPark::NotApplied(NotApplied::NotParkable)
    );
}

#[test]
fn park_026_sc_006_a_device_park_after_a_sweep_gap_applies_the_floor_first() {
    // Flag off for 5 days, then a device park lands before the first sweep.
    let (mut sim, id, form) = due_sim();
    let now = sim.now;
    sim.last_sweep = Some(now.plus_seconds(-5 * 86_400));
    let reply = sim
        .request(
            "POST",
            &format!("/api/tasks/{id}/auto-park"),
            &json!({ "formulation_id": form }),
        )
        .expect("routed");
    assert_eq!(reply.body["applied"], false);
    assert_eq!(reply.body["task"]["state"], "next");
    // The park waits behind the floor the gap raised; the settings revision
    // does not move because the floor is bookkeeping.
    assert_eq!(
        sim.settings.owner_park_floor_at(),
        Some(now.plus_seconds(7 * 86_400))
    );
    assert_eq!(sim.last_sweep, Some(now));
    assert_eq!(
        reply.body["task"]["formulation"]["park_due_at"]
            .as_str()
            .map(at),
        Some(now.plus_seconds(7 * 86_400))
    );
    // The next sweep, a minute on, finds no gap and parks nothing yet.
    sim.advance(&json!({"minutes": 1}));
    sim.sweep();
    assert_eq!(sim.tasks[&id].clock.state, Some(TaskState::Next));
    assert_eq!(
        sim.settings.owner_park_floor_at(),
        Some(now.plus_seconds(7 * 86_400))
    );
}

#[test]
fn park_026_sc_006_a_device_park_without_a_gap_leaves_the_owner_floor_alone() {
    let (mut sim, id, form) = due_sim();
    sim.last_sweep = Some(sim.now.plus_seconds(-60));
    let reply = sim
        .request(
            "POST",
            &format!("/api/tasks/{id}/auto-park"),
            &json!({ "formulation_id": form }),
        )
        .expect("routed");
    assert_eq!(reply.body["applied"], true);
    assert_eq!(sim.settings.owner_park_floor_at(), None);
    assert_eq!(sim.last_sweep, Some(sim.now));
}

#[test]
fn park_026_fr_013_the_sweep_repairs_a_missing_clock_and_never_parks_it_in_the_same_pass() {
    let (mut sim, id, _) = due_sim();
    let now = sim.now;
    let clock = &mut sim.tasks.get_mut(&id).expect("task").clock;
    *clock = TaskClock {
        formulation_id: None,
        formulation_started_at: None,
        ..clock.clone()
    };
    let revision = clock.revision;
    sim.sweep();
    let repaired = &sim.tasks[&id].clock;
    assert_eq!(repaired.state, Some(TaskState::Next));
    assert_eq!(repaired.formulation_started_at, Some(now));
    assert_eq!(
        repaired.formulation_park_floor_at,
        Some(now.plus_seconds(14 * 86_400))
    );
    assert_eq!(repaired.revision, revision, "repair is bookkeeping");
    assert!(sim.rows.is_empty());
}

#[test]
fn park_026_fr_013_a_sweep_key_already_recorded_is_not_parked_twice() {
    let (mut sim, id, _) = due_sim();
    let clock = sim.tasks[&id].clock.clone();
    let AutoPark::Applied(parked) =
        park::attempt_park(&id, &clock, &sim.settings, sim.now, ParkSource::Sweep)
    else {
        panic!("the task is due");
    };
    sim.keys.insert(parked.key.clone());
    sim.sweep();
    assert_eq!(
        sim.tasks[&id].clock.state,
        Some(TaskState::Next),
        "recorded key skipped"
    );
    assert!(sim.rows.is_empty());
}

#[test]
fn park_026_fr_013_the_sweep_visits_only_due_next_tasks_in_batches_of_fifty() {
    let settings = OwnerClockSettings::new(14, "UTC", None, Some(at("2026-09-01T00:00:00Z")))
        .expect("settings");
    let start = at("2026-09-01T00:00:00Z");
    let now = start.plus_seconds(40 * 86_400);
    let mut tasks: Vec<(String, TaskClock)> = (0..120)
        .map(|n| {
            (
                format!("task_{n:03}"),
                formulation::create_in_next("Due", &format!("form_{n:03}"), start),
            )
        })
        .collect();
    tasks.push((
        "task_fresh".to_owned(),
        formulation::create_in_next("New", "form_new", now),
    ));
    let mut unstarted = formulation::create_in_next("No clock", "form_none", start);
    unstarted.formulation_started_at = None;
    tasks.push(("task_unstarted".to_owned(), unstarted));
    tasks.push((
        "task_waiting".to_owned(),
        TaskClock {
            state: Some(TaskState::Waiting),
            ..formulation::create_in_next("Waiting", "form_w", start)
        },
    ));
    let plan = park::plan_owner_sweep(true, &settings, Some(now.plus_seconds(-60)), &tasks, now)
        .expect("an exposed, activated owner");
    assert!(!plan.note.gap);
    assert_eq!(plan.due.len(), 121, "120 due tasks and the one to repair");
    assert!(!plan.due.contains(&"task_fresh".to_owned()));
    assert!(!plan.due.contains(&"task_waiting".to_owned()));
    assert_eq!(plan.due.chunks(park::SWEEP_BATCH).count(), 3);
    // The flag and activation gate the whole evaluation.
    assert!(park::plan_owner_sweep(false, &settings, None, &tasks, now).is_none());
    let inactive = OwnerClockSettings::new(14, "UTC", None, None).expect("settings");
    assert!(park::plan_owner_sweep(true, &inactive, None, &tasks, now).is_none());
}

// ------------------------------------------------------------- the yield rule

/// A task parked by the sweep: the card the person saw (revision 1) and the
/// parked task (revision 2), as `_park_with_sweep` builds them.
fn parked_sim() -> (Sim, String, String, UtcInstant) {
    let (mut sim, id, form) = due_sim();
    let decided_at = sim.now.plus_seconds(-3_600);
    sim.sweep();
    assert_eq!(sim.tasks[&id].clock.state, Some(TaskState::Someday));
    assert_eq!(sim.tasks[&id].clock.revision, 2);
    (sim, id, form, decided_at)
}

fn decision_body(form: &str, kind: &str, decided_at: UtcInstant) -> Value {
    json!({
        "decision_id": "decision_0b0e1f30-0000-4000-8000-0000000000f1",
        "type": kind, "expected_revision": 1, "formulation_id": form,
        "waiting_for": "Ann", "reason": "Away", "title": "Call Bob",
        "new_formulation_id": "form_0b0e1f30-0000-4000-8000-0000000000f9",
        "client_decided_at": decided_at.to_rfc3339(),
    })
}

#[test]
fn park_026_fr_013_an_offline_decision_before_the_park_wins_the_yield() {
    let (mut sim, id, form, decided_at) = parked_sim();
    let path = format!("/api/tasks/{id}/decisions");
    let done = sim
        .request("POST", &path, &decision_body(&form, "someday", decided_at))
        .expect("routed");
    assert_eq!(done.status, 200);
    assert_eq!(done.body["decision"]["yielded_auto_park"], true);
    assert_eq!(done.body["task"]["state"], "someday");
    assert_eq!(done.body["task"]["parked"], Value::Null);
    // Restored with its stalled count, then closed by the decision itself once.
    assert_eq!(sim.tasks[&id].clock.consecutive_stalled_formulations, 1);
    // The reversal is not a return: the row reads as unreturned.
    assert_eq!(sim.row_of(&id, &form).expect("row").returned_at, None);
}

#[test]
fn park_026_fr_013_an_offline_extend_before_the_park_is_accepted() {
    let (mut sim, id, form, decided_at) = parked_sim();
    let done = sim
        .request(
            "POST",
            &format!("/api/tasks/{id}/decisions"),
            &decision_body(&form, "extend", decided_at),
        )
        .expect("routed");
    assert_eq!(done.status, 200, "{}", done.body);
    let formulation = &done.body["task"]["formulation"];
    assert_eq!(done.body["task"]["state"], "next");
    assert_eq!(formulation["id"], form.as_str());
    assert_eq!(formulation["started_at"], START);
    assert_eq!(formulation["consecutive_stalled"], 0);
}

#[test]
fn park_026_fr_013_a_decision_made_after_the_park_does_not_yield() {
    let (mut sim, id, form, _) = parked_sim();
    let late = sim.now.plus_seconds(3_600);
    let done = sim
        .request(
            "POST",
            &format!("/api/tasks/{id}/decisions"),
            &decision_body(&form, "someday", late),
        )
        .expect("routed");
    assert_eq!(done.status, 409, "stale: the card showed revision 1");
    assert!(sim.tasks[&id].clock.parked.is_some());
}

#[test]
fn park_026_fr_013_the_yield_window_is_from_revision_to_the_current_revision() {
    let (mut sim, id, form, decided_at) = parked_sim();
    let marker_form = form.as_str();
    let edited = formulation::edit_without_clock(&sim.tasks[&id].clock);
    sim.tasks.get_mut(&id).expect("task").clock = edited;
    let clock = &sim.tasks[&id].clock;
    let parked_at = clock.parked.as_ref().expect("parked").at;
    let query = |decision, expected_revision, formulation_id, decided| YieldQuery {
        decision,
        formulation_id,
        expected_revision,
        client_decided_at: decided,
    };
    let base = |expected| {
        query(
            DecisionType::Waiting,
            expected,
            Some(marker_form),
            Some(decided_at),
        )
    };
    // from_revision is 1, the current revision 3.
    assert!(!park::yields(clock, &base(0)));
    assert!(park::yields(clock, &base(1)));
    assert!(park::yields(clock, &base(2)));
    assert!(park::yields(clock, &base(3)));
    assert!(!park::yields(clock, &base(4)));
    // The device time must lie strictly before the park.
    assert!(!park::yields(
        clock,
        &query(DecisionType::Waiting, 1, Some(marker_form), Some(parked_at))
    ));
    assert!(!park::yields(
        clock,
        &query(DecisionType::Waiting, 1, Some(marker_form), None)
    ));
    // The parked formulation only, and only decisions Next allows.
    assert!(!park::yields(
        clock,
        &query(
            DecisionType::Waiting,
            1,
            Some("form_other"),
            Some(decided_at)
        )
    ));
    assert!(!park::yields(
        clock,
        &query(DecisionType::Waiting, 1, None, Some(decided_at))
    ));
    assert!(!park::yields(
        clock,
        &query(
            DecisionType::KeepSomeday,
            1,
            Some(marker_form),
            Some(decided_at)
        )
    ));
    assert!(!park::yields(
        clock,
        &query(
            DecisionType::KeepWaiting,
            1,
            Some(marker_form),
            Some(decided_at)
        )
    ));
    assert!(park::yields(
        clock,
        &query(
            DecisionType::Complete,
            1,
            Some(marker_form),
            Some(decided_at)
        )
    ));
    // A task that is not parked in Someday never yields.
    let moved = TaskClock {
        state: Some(TaskState::Waiting),
        ..clock.clone()
    };
    assert!(!park::yields(&moved, &base(1)));
    let unparked = TaskClock {
        parked: None,
        ..clock.clone()
    };
    assert!(!park::yields(&unparked, &base(1)));
}

#[test]
fn park_026_fr_013_a_public_park_marker_neither_yields_nor_restores() {
    let (sim, id, form, decided_at) = parked_sim();
    let public = TaskClock {
        parked: sim.tasks[&id]
            .clock
            .parked
            .as_ref()
            .map(park::public_marker),
        ..sim.tasks[&id].clock.clone()
    };
    let marker = public.parked.as_ref().expect("marker");
    assert_eq!(
        (marker.from_revision, marker.clock_before.is_none()),
        (None, true)
    );
    assert_eq!(marker.formulation_id, form);
    let query = YieldQuery {
        decision: DecisionType::Waiting,
        formulation_id: Some(&form),
        expected_revision: 1,
        client_decided_at: Some(decided_at),
    };
    assert!(!park::yields(&public, &query));
    // Forced through the clock restore, it is refused rather than invented.
    assert_eq!(
        formulation::reverse_park(&public),
        Err(FormulationError::ParkSnapshotUnavailable)
    );
    // A yielding request against a marker that lost only its clock is refused too.
    let no_clock = TaskClock {
        parked: Some(ParkMarker {
            clock_before: None,
            ..sim.tasks[&id].clock.parked.clone().expect("parked")
        }),
        ..sim.tasks[&id].clock.clone()
    };
    assert_eq!(
        park::yield_reversal(&no_clock, &query),
        Err(FormulationError::ParkSnapshotUnavailable)
    );
}

// ------------------------------------------------------- rows and acknowledgement

#[test]
fn park_026_fr_015_a_return_records_returned_at_and_a_missing_row_is_never_made_up() {
    let (sim, id, form, _) = parked_sim();
    let before = sim.tasks[&id].clock.clone();
    let now = sim.now;
    let row = sim.row_of(&id, &form).expect("row");
    let by_form = |wanted: &str| (wanted == form).then(|| row.clone());
    let ParkReturn::Returned(returned) =
        park::note_park_return(&before, Some(TaskState::Next), by_form, now)
    else {
        panic!("a parked task moved to Next is a return");
    };
    assert_eq!(returned.returned_at, Some(now));
    assert_eq!(returned.seen_at, None, "returning is not seeing");
    assert_eq!(
        park::note_park_return(&before, Some(TaskState::Next), |_| None, now),
        ParkReturn::Unrecorded
    );
    for not_a_return in [Some(TaskState::Waiting), Some(TaskState::Someday), None] {
        assert_eq!(
            park::note_park_return(&before, not_a_return, |_| None, now),
            ParkReturn::NotAReturn
        );
    }
    // Undo of the return puts the task back in its park: the row reads unreturned.
    let restored = park::restore_park_row(&before, |_| Some(returned.clone()));
    assert_eq!(restored.map(|r| r.returned_at), Some(None));
    assert_eq!(
        park::restore_park_row(&before, |_| Some(row.clone())),
        None,
        "unchanged"
    );
    let in_next = TaskClock {
        state: Some(TaskState::Next),
        ..before
    };
    assert_eq!(
        park::restore_park_row(&in_next, |_| Some(returned.clone())),
        None
    );
}

#[test]
fn park_026_fr_015_acknowledgement_marks_once_ignores_unknown_keys_and_never_bumps_a_task() {
    let (mut sim, id, form, _) = parked_sim();
    let revision = sim.tasks[&id].clock.revision;
    let key = json!({"task_id": id, "formulation_id": form});
    let unknown = json!({"task_id": "task_unknown", "formulation_id": form});
    let body = json!({"items": [key, key, unknown]});
    let request: ParksAck = serde_json::from_value(body.clone()).expect("a request");
    let result = park::acknowledge_parks(&request, |t, f| sim.row_of(t, f), sim.now);
    assert_eq!(
        result.marked,
        [(id.clone(), form.clone())],
        "once, unknown ignored"
    );
    let done = sim
        .request("POST", "/api/review/parks/acknowledge", &body)
        .expect("routed");
    assert_eq!(done.status, 204);
    let row = sim.row_of(&id, &form).expect("row");
    assert_eq!(row.seen_at, Some(sim.now));
    assert_eq!(sim.tasks[&id].clock.revision, revision);
    // Idempotent by state: the acknowledged park marks nothing the second time.
    let again = park::acknowledge_parks(&request, |t, f| sim.row_of(t, f), sim.now.plus_seconds(5));
    assert!(again.marked.is_empty());
    assert!(park::rows_marked_seen(&result, |t, f| sim.row_of(t, f)).is_empty());
}

#[test]
fn park_026_fr_015_a_replayed_acknowledgement_leaves_a_repeat_park_unseen() {
    let (mut sim, id, form, decided_at) = parked_sim();
    let key = json!({"items": [{"task_id": id, "formulation_id": form}]});
    let request: ParksAck = serde_json::from_value(key).expect("a request");
    let first = park::acknowledge_parks(&request, |t, f| sim.row_of(t, f), sim.now);
    // The yield returns the task to Next, a cosmetic save keeps the formulation,
    // and the next sweep parks it again: a fresh row, unseen and unreturned.
    let done = sim
        .request(
            "POST",
            &format!("/api/tasks/{id}/decisions"),
            &decision_body(&form, "reformulate", decided_at),
        )
        .expect("routed");
    assert_eq!(done.status, 200);
    sim.advance(&json!({"minutes": 1}));
    sim.sweep();
    let again = sim.tasks[&id].clock.clone();
    assert_eq!(again.state, Some(TaskState::Someday));
    let row = sim.row_of(&id, &form).expect("row");
    assert_eq!(row.from_revision, Some(again.revision - 1));
    assert_eq!((row.seen_at, row.returned_at), (None, None));
    // Replaying the first acknowledgement (a lost write) must leave it unseen.
    assert!(row.parked_at > first.seen_at);
    assert!(park::rows_marked_seen(&first, |t, f| sim.row_of(t, f)).is_empty());
    let parks = [(id.as_str(), &again)];
    let unseen = park::unseen_parks(parks, |t, f| sim.row_of(t, f));
    assert_eq!(unseen.len(), 1);
    assert_eq!(unseen[0].parked_at, row.parked_at);
}

#[test]
fn park_026_fr_015_unseen_parks_list_the_oldest_park_first_and_skip_seen_and_moved_tasks() {
    let (mut sim, id, form, _) = parked_sim();
    let parked = sim.tasks[&id].clock.clone();
    let at_park = parked.parked.as_ref().expect("parked").at;
    let clock_at = |when: UtcInstant| TaskClock {
        parked: parked.parked.as_ref().map(|m| ParkMarker {
            at: when,
            ..m.clone()
        }),
        ..parked.clone()
    };
    let (older, newer, same_a, same_b) = (
        clock_at(at_park.plus_seconds(-100)),
        clock_at(at_park.plus_seconds(100)),
        clock_at(at_park),
        clock_at(at_park),
    );
    let waiting = TaskClock {
        state: Some(TaskState::Waiting),
        ..parked.clone()
    };
    let nothing = TaskClock {
        parked: None,
        ..parked.clone()
    };
    let mut seen_row = sim.row_of(&id, &form).expect("row");
    seen_row.seen_at = Some(sim.now);
    let seen = |t: &str, f: &str| {
        (t == "task_seen").then(|| ParkRow {
            task_id: t.to_owned(),
            formulation_id: f.to_owned(),
            ..seen_row.clone()
        })
    };
    let tasks = [
        ("task_b", &same_b),
        ("task_new", &newer),
        ("task_seen", &same_a),
        ("task_waiting", &waiting),
        ("task_plain", &nothing),
        ("task_a", &same_a),
        ("task_old", &older),
    ];
    let order: Vec<_> = park::unseen_parks(tasks, seen)
        .into_iter()
        .map(|park| park.task_id)
        .collect();
    assert_eq!(order, ["task_old", "task_a", "task_b", "task_new"]);
    sim.rows.clear();
}

// ------------------------------------------------- stored rows and content limits

#[test]
fn park_026_fr_016_a_stored_park_row_round_trips_and_its_public_form_drops_private_facts() {
    let form = "form_0b0e1f30-0000-4000-8000-0000000000f1";
    let row = ParkRow {
        task_id: "task_9f3c2a1b4d5e".to_owned(),
        formulation_id: form.to_owned(),
        parked_at: at("2026-10-30T14:02:00Z"),
        seen_at: Some(at("2026-10-30T15:00:00Z")),
        returned_at: None,
        from_revision: Some(1),
        source: Some(ParkSource::Sweep),
    };
    let stored = row.to_ack().expect("a stored row");
    assert_eq!(ParkRow::from_ack(&stored).expect("readable"), row);
    let private = stored.private.as_ref().expect("private facts");
    assert_eq!(private.from_revision.to_u64(), Some(1));
    // The replicated projection carries neither revision nor source, and what
    // is read back from it cannot be mistaken for the authoritative row.
    let public = ParkRow::from_ack(&stored.public()).expect("readable");
    assert_eq!((public.from_revision, public.source), (None, None));
    assert_eq!(
        (public.parked_at, public.seen_at),
        (row.parked_at, row.seen_at)
    );
    assert!(public.to_ack().expect("storable").private.is_none());
    assert!(
        serde_json::to_value(stored.public())
            .expect("json")
            .get("private")
            .is_none()
    );

    // A private revision the rule cannot hold is refused, never read back as a
    // public row that would silently drop the private facts on the next write.
    let mut wide = serde_json::to_value(&stored).expect("json");
    wide["private"]["from_revision"] = json!("18446744073709551616");
    let wide: bb_domain::types::ParkAck = serde_json::from_value(wide).expect("a wire-valid row");
    assert_eq!(
        ParkRow::from_ack(&wide),
        Err(FormulationError::InvalidField(
            "park_ack.private.from_revision"
        ))
    );
}

// --------------------------------------------- the command-level family (T062)

const NOW: &str = "2026-10-09T12:00:00Z";
const TASK: &str = "task_00000000-0000-4000-8000-0000000000d1";
const FORM: &str = "form_0b0e1f30-0000-4000-8000-0000000000d1";
const LAST_SWEEP: &str = "2026-10-09T11:59:00Z";

fn exec(now: &str, authoritative: bool, weekly_review: bool) -> ExecutionInputs {
    serde_json::from_value(json!({
        "rule_version": 1, "now": now, "time_zone": "UTC", "origin": "device",
        "actor_id": "actor-example", "authoritative": authoritative, "allocated_ids": [],
        "policy": {
            "weekly_review": weekly_review, "navigator_provider": null,
            "navigator_available": false, "consent_text_version": 1,
        },
    }))
    .expect("execution inputs")
}

fn command_of(kind: &str, entity: &str, payload: Value, preconditions: Value) -> DomainCommand {
    serde_json::from_value(json!({
        "command_id": "01900000-0000-4000-8000-000000000001", "entity_id": entity,
        "issued_at": NOW, "preconditions": preconditions, "type": kind, "payload": payload,
    }))
    .unwrap_or_else(|error| panic!("{kind}: {error}"))
}

fn auto_park_of(formulation_id: &str) -> DomainCommand {
    command_of(
        "review.auto_park",
        TASK,
        json!({ "formulation_id": formulation_id }),
        json!([]),
    )
}

fn ack_command(items: &[(&str, &str)]) -> DomainCommand {
    let items: Vec<Value> = items
        .iter()
        .map(|(task, form)| json!({ "task_id": task, "formulation_id": form }))
        .collect();
    command_of(
        "review.parks_ack",
        "scope-example",
        json!({ "items": items }),
        json!([]),
    )
}

fn task_row(id: &str, state: &str, formulation_started: Option<&str>, form: &str) -> Value {
    json!({
        "id": id, "title": "Call Bob", "details": "Ask about the lease", "state": state,
        "project_id": null, "tag_ids": [], "due_date": null, "priority": "none",
        "waiting_for": (state == "waiting").then_some("Bob"), "waiting_since": null,
        "order_key": "3", "source_capture_ids": [], "created_at": "2026-09-01T09:00:00Z",
        "updated_at": "2026-09-02T09:00:00Z", "completed_at": null, "cancelled_at": null,
        "revision": "4", "consecutive_stalled_formulations": 0,
        "formulation": formulation_started.map(|started| json!({
            "id": form, "started_at": started, "extended_at": null,
            "extension_reason": null, "park_floor_at": null,
        })),
        "parked": null,
    })
}

fn settings_row(activated: bool, last_sweep: Option<&str>) -> Value {
    json!({
        "threshold_days": 14, "review_weekday": 5, "review_time": "16:00", "time_zone": "UTC",
        "onboarded_at": null, "activated_at": activated.then_some("2026-08-01T00:00:00Z"),
        "owner_park_floor_at": null, "revision": "2",
        "private": last_sweep.map(|at| json!({
            "last_effective_sweep_at": at, "threshold_changed_at": null,
        })),
    })
}

fn read_set_of(task: Value, settings: Value, park_acks: Value) -> ReadSet {
    serde_json::from_value(json!({
        "tasks": { TASK: task }, "settings": settings, "park_acks": park_acks,
    }))
    .expect("a read set")
}

/// A Next task whose formulation started 29 days before `NOW` (`park_due`), an
/// activated owner and, as given, the last effective evaluation.
fn due_set(last_sweep: Option<&str>) -> ReadSet {
    read_set_of(
        task_row(TASK, "next", Some("2026-09-10T09:00:00Z"), FORM),
        settings_row(true, last_sweep),
        json!([]),
    )
}

fn tasks_of(set: &ChangeSet) -> Vec<&Task> {
    set.changes
        .iter()
        .filter_map(|change| match change {
            DomainChange::Upsert(Record::Task(task)) => Some(task),
            _ => None,
        })
        .collect()
}

fn acks_of(set: &ChangeSet) -> Vec<&ParkAck> {
    set.changes
        .iter()
        .filter_map(|change| match change {
            DomainChange::Upsert(Record::ReviewParkAck(ack)) => Some(ack),
            _ => None,
        })
        .collect()
}

fn settings_of(set: &ChangeSet) -> Vec<&ReviewSettings> {
    set.changes
        .iter()
        .filter_map(|change| match change {
            DomainChange::Upsert(Record::ReviewSettings(settings)) => Some(settings),
            _ => None,
        })
        .collect()
}

/// The accepted no-op of an `applied: false` auto-park.
fn declined_no_op() -> ChangeSet {
    ChangeSet {
        result: ResultRefs {
            applied: Some(false),
            ..ResultRefs::default()
        },
        ..ChangeSet::no_op()
    }
}

#[test]
fn park_026_fr_013_the_family_claims_exactly_its_two_commands() {
    let decision = "decision_0b0e1f30-0000-4000-8000-0000000000d2";
    let mut claimed = Vec::new();
    for (kind, payload) in [
        ("review.auto_park", json!({ "formulation_id": FORM })),
        ("review.parks_ack", json!({ "items": [] })),
        ("review.settings", json!({})),
        (
            "review.decide",
            json!({ "decision_id": decision, "type": "complete" }),
        ),
        ("task.update", json!({ "title": "x" })),
        ("tag.delete", json!({})),
    ] {
        let command = command_of(kind, TASK, payload, json!([]));
        if park::handles(&command.command) {
            claimed.push(kind);
        }
    }
    assert_eq!(claimed, ["review.auto_park", "review.parks_ack"]);
}

#[test]
fn park_026_fr_013_a_command_of_another_family_is_refused_as_invalid_payload_on_type() {
    let read_set = due_set(Some(LAST_SWEEP));
    for (kind, payload) in [
        ("review.settings", json!({ "threshold_days": 21 })),
        ("task.update", json!({ "title": "x" })),
        ("review.bulk_undo", json!({})),
    ] {
        let foreign = command_of(kind, TASK, payload, json!([]));
        assert!(!park::handles(&foreign.command), "{kind}");
        assert_eq!(
            park::decide(&read_set, &foreign, &exec(NOW, true, true)),
            Err(DomainError::field(Reason::InvalidPayload, "type")),
            "{kind}"
        );
    }
}

#[test]
fn park_026_fr_013_the_auto_park_vectors_hold_through_the_command() {
    let section = transitions_of("auto_park");
    let mut ran = 0;
    for vector in &section {
        let id = text(vector, "id");
        let now = text(vector, "now");
        let read_set: ReadSet =
            serde_json::from_value(support::auto_park_read_set(vector, "task_vector"))
                .unwrap_or_else(|error| panic!("{id}: {error}"));
        let command = command_of(
            "review.auto_park",
            "task_vector",
            json!({ "formulation_id": support::VECTOR_FORMULATION }),
            json!([]),
        );
        let set = park::decide(&read_set, &command, &exec(now, true, true))
            .unwrap_or_else(|error| panic!("{id}: {error}"));
        // The wrapper adds nothing to the primitive's verdict.
        let stored = read_set.tasks.values().next().expect("the vector task");
        let before = TaskClock::from_task(stored).expect("a clock");
        let owner =
            OwnerClockSettings::from_review_settings(read_set.settings.as_ref().expect("settings"))
                .expect("settings");
        let direct = park::device_auto_park(
            &before,
            &owner,
            &DeviceParkRequest {
                task_id: "task_vector",
                formulation_id: support::VECTOR_FORMULATION,
                exposed: true,
                last_effective_sweep_at: Some(at(now).plus_seconds(-60)),
            },
            at(now),
        );
        assert_eq!(set.result.applied, Some(direct.outcome.applied()), "{id}");
        let expect = &vector["expect"];
        if expect.get("applied") == Some(&Value::Bool(false)) {
            assert!(
                tasks_of(&set).is_empty() && acks_of(&set).is_empty(),
                "{id}"
            );
        } else {
            let expected: Value = serde_json::from_str(
                &expect
                    .to_string()
                    .replace("form_a", support::VECTOR_FORMULATION),
            )
            .expect("an expectation");
            let [task] = tasks_of(&set)[..] else {
                panic!("{id}: one parked task");
            };
            let clock = TaskClock::from_task(task).expect("a clock");
            assert_subset(&expected, &clock_to(&clock), id);
            let [ack] = acks_of(&set)[..] else {
                panic!("{id}: one park row");
            };
            assert_eq!(
                ack.formulation_id.as_str(),
                support::VECTOR_FORMULATION,
                "{id}"
            );
            assert_eq!(ack.seen_at, None, "{id}");
        }
        ran += 1;
    }
    ran_all("auto_park command", ran, section.len());
}

#[test]
fn park_026_fr_013_an_applied_park_bumps_the_revision_once_and_writes_a_fresh_unseen_row() {
    let read_set = due_set(Some(LAST_SWEEP));
    let before = read_set.tasks.values().next().expect("a task").clone();
    // No generic revision precondition: one that names another revision is not read.
    let stale = command_of(
        "review.auto_park",
        TASK,
        json!({ "formulation_id": FORM }),
        json!([{ "entity_type": "task", "entity_id": TASK, "edit_revision": "99" }]),
    );
    let set = park::decide(&read_set, &stale, &exec(NOW, true, true)).expect("decided");
    assert_eq!(
        set,
        park::decide(&read_set, &auto_park_of(FORM), &exec(NOW, true, true)).expect("decided"),
    );
    assert_eq!(set.outcome, ChangeOutcome::Applied);
    assert_eq!(set.result.applied, Some(true));
    // The server's write order: bookkeeping, the parked task, the park row.
    assert_eq!(
        set.affected_keys(),
        [
            (EntityType::ReviewSettings, vec![]),
            (EntityType::Task, vec![TASK.to_owned()]),
            (
                EntityType::ReviewParkAck,
                vec![TASK.to_owned(), FORM.to_owned()]
            ),
        ]
    );
    let [task] = tasks_of(&set)[..] else {
        panic!("one task")
    };
    assert_eq!(task.state, TaskState::Someday);
    assert_eq!(task.revision.to_u64(), Some(5), "bumped once, from 4");
    assert_eq!(task.updated_at.as_str(), NOW);
    assert!(task.formulation.is_none(), "the formulation is closed");
    assert_eq!(
        (
            &task.title,
            &task.details,
            &task.order_key,
            &task.created_at
        ),
        (
            &before.title,
            &before.details,
            &before.order_key,
            &before.created_at
        ),
        "nothing else of the task changes"
    );
    let marker = task.parked.as_ref().expect("a park marker");
    assert_eq!(
        (marker.at.as_str(), marker.formulation_id.as_str()),
        (NOW, FORM)
    );
    let private = marker
        .private
        .as_ref()
        .expect("the server keeps the snapshot");
    assert_eq!(private.from_revision.to_u64(), Some(4));
    assert_eq!(
        private.clock_before.started_at.as_str(),
        "2026-09-10T09:00:00Z"
    );
    let [ack] = acks_of(&set)[..] else {
        panic!("one row")
    };
    assert_eq!(ack.parked_at.as_str(), NOW);
    assert_eq!((&ack.seen_at, &ack.returned_at), (&None, &None));
    let row = ack.private.as_ref().expect("private row facts");
    assert_eq!(
        (row.from_revision.to_u64(), row.source),
        (Some(4), ParkSource::Device)
    );
    // The settings revision stays: the evaluation instant is bookkeeping.
    let [settings] = settings_of(&set)[..] else {
        panic!("settings")
    };
    assert_eq!(settings.revision.to_u64(), Some(2));
    let note = settings.private.as_ref().expect("private bookkeeping");
    assert_eq!(
        note.last_effective_sweep_at.as_ref().map(|at| at.as_str()),
        Some(NOW)
    );
    assert_eq!(settings.owner_park_floor_at, None, "no gap, no floor");
}

#[test]
fn park_026_fr_013_a_park_the_server_disagrees_with_is_applied_false_and_writes_no_task() {
    let due = due_set(Some(LAST_SWEEP));
    let other_form = "form_0b0e1f30-0000-4000-8000-0000000000ee";
    let fresh = read_set_of(
        task_row(TASK, "next", Some("2026-10-08T09:00:00Z"), FORM),
        settings_row(true, Some(LAST_SWEEP)),
        json!([]),
    );
    let waiting = read_set_of(
        task_row(TASK, "waiting", None, FORM),
        settings_row(true, Some(LAST_SWEEP)),
        json!([]),
    );
    let inactive = read_set_of(
        task_row(TASK, "next", Some("2026-09-10T09:00:00Z"), FORM),
        settings_row(false, Some(LAST_SWEEP)),
        json!([]),
    );
    let no_settings = read_set_of(
        task_row(TASK, "next", Some("2026-09-10T09:00:00Z"), FORM),
        Value::Null,
        json!([]),
    );
    let cases = [
        ("another formulation", &due, auto_park_of(other_form), true),
        ("not due yet", &fresh, auto_park_of(FORM), true),
        ("outside Next", &waiting, auto_park_of(FORM), true),
        ("owner not activated", &inactive, auto_park_of(FORM), true),
        ("no settings row", &no_settings, auto_park_of(FORM), true),
        ("flag off", &due, auto_park_of(FORM), false),
    ];
    for (label, read_set, command, exposed) in cases {
        let set = park::decide(read_set, &command, &exec(NOW, true, exposed))
            .unwrap_or_else(|error| panic!("{label}: {error}"));
        assert_eq!(set.result.applied, Some(false), "{label}");
        assert!(tasks_of(&set).is_empty(), "{label}: no task");
        assert!(acks_of(&set).is_empty(), "{label}: no park row");
    }
    // Flag off, or an owner who never activated: no bookkeeping either, so the
    // answer is the bare accepted no-op.
    for (read_set, exposed) in [(&due, false), (&inactive, true), (&no_settings, true)] {
        assert_eq!(
            park::decide(read_set, &auto_park_of(FORM), &exec(NOW, true, exposed)),
            Ok(declined_no_op())
        );
    }
}

#[test]
fn park_026_sc_006_a_declined_park_after_a_sweep_gap_still_raises_the_owner_floor() {
    // Flag off for 5 days, then a device park lands before the first sweep.
    let read_set = due_set(Some("2026-10-04T12:00:00Z"));
    let set =
        park::decide(&read_set, &auto_park_of(FORM), &exec(NOW, true, true)).expect("decided");
    assert_eq!(set.result.applied, Some(false));
    assert_eq!(
        set.outcome,
        ChangeOutcome::Applied,
        "the settings row changed"
    );
    assert!(tasks_of(&set).is_empty() && acks_of(&set).is_empty());
    let [settings] = settings_of(&set)[..] else {
        panic!("settings")
    };
    assert_eq!(
        settings
            .owner_park_floor_at
            .as_ref()
            .map(|floor| at(floor.as_str())),
        Some(at(NOW).plus_seconds(7 * 86_400))
    );
    assert_eq!(
        settings.revision.to_u64(),
        Some(2),
        "bookkeeping, not an edit"
    );
    // Without a recorded evaluation there is no earlier one: also a gap.
    let unrecorded = due_set(None);
    let set =
        park::decide(&unrecorded, &auto_park_of(FORM), &exec(NOW, true, true)).expect("decided");
    assert_eq!(set.result.applied, Some(false));
    assert_eq!(settings_of(&set).len(), 1);
}

#[test]
fn park_026_fr_013_a_replayed_auto_park_over_the_committed_state_is_a_no_op() {
    let read_set = due_set(Some(LAST_SWEEP));
    let command = auto_park_of(FORM);
    let first = park::decide(&read_set, &command, &exec(NOW, true, true)).expect("decided");
    assert_eq!(first.result.applied, Some(true));
    let committed = support::commit(&read_set, &first);
    // The same command, and a second device observing the same due park, find
    // the task parked: an accepted no-op, never a conflict.
    assert_eq!(
        park::decide(&committed, &command, &exec(NOW, true, true)),
        Ok(declined_no_op())
    );
    let other_device = command_of(
        "review.auto_park",
        TASK,
        json!({ "formulation_id": FORM }),
        json!([{ "entity_type": "task", "entity_id": TASK, "edit_revision": "4" }]),
    );
    assert_eq!(
        park::decide(&committed, &other_device, &exec(NOW, true, true)),
        Ok(declined_no_op())
    );
}

#[test]
fn park_026_fr_013_an_unknown_task_is_not_found() {
    let read_set = due_set(Some(LAST_SWEEP));
    let missing = "task_00000000-0000-4000-8000-0000000000d9";
    let command = command_of(
        "review.auto_park",
        missing,
        json!({ "formulation_id": FORM }),
        json!([]),
    );
    assert_eq!(
        park::decide(&read_set, &command, &exec(NOW, true, true)),
        Err(DomainError::about(
            Reason::NotFound,
            EntityType::Task,
            vec![missing.to_owned()]
        ))
    );
}

#[test]
fn park_026_fr_016_a_writer_without_authority_produces_the_public_projection() {
    let read_set = due_set(Some(LAST_SWEEP));
    let set =
        park::decide(&read_set, &auto_park_of(FORM), &exec(NOW, false, true)).expect("decided");
    assert_eq!(set.result.applied, Some(true));
    let [task] = tasks_of(&set)[..] else {
        panic!("one task")
    };
    let marker = task.parked.as_ref().expect("a marker");
    assert!(marker.private.is_none(), "no clock before, no revision");
    assert_eq!(task, &task.public());
    let [ack] = acks_of(&set)[..] else {
        panic!("one row")
    };
    assert!(ack.private.is_none());
    // A row that never carried the private member does not grow one.
    let bare = due_set(None);
    let gapped =
        park::decide(&bare, &auto_park_of(FORM), &exec(NOW, false, true)).expect("decided");
    assert_eq!(settings_of(&gapped).len(), 1, "the floor is public");
    assert!(settings_of(&gapped)[0].private.is_none());
}

fn row_json(task: &str, form: &str, parked_at: &str, seen_at: Option<&str>) -> Value {
    json!({
        "task_id": task, "formulation_id": form, "parked_at": parked_at,
        "seen_at": seen_at, "returned_at": null,
        "private": { "from_revision": "3", "source": "sweep" },
    })
}

const ROW_A: (&str, &str) = (
    "task_00000000-0000-4000-8000-0000000000e1",
    "form_0b0e1f30-0000-4000-8000-0000000000e1",
);
const ROW_B: (&str, &str) = (
    "task_00000000-0000-4000-8000-0000000000e2",
    "form_0b0e1f30-0000-4000-8000-0000000000e2",
);
const ROW_SEEN: (&str, &str) = (
    "task_00000000-0000-4000-8000-0000000000e3",
    "form_0b0e1f30-0000-4000-8000-0000000000e3",
);

/// Two unseen park rows and one seen, and the parked task of the first.
fn parked_rows() -> ReadSet {
    let mut task = task_row(ROW_A.0, "someday", None, ROW_A.1);
    task["revision"] = json!("5");
    let mut read_set = read_set_of(
        task_row(TASK, "next", Some("2026-09-10T09:00:00Z"), FORM),
        settings_row(true, Some(LAST_SWEEP)),
        json!([
            row_json(ROW_A.0, ROW_A.1, "2026-10-08T09:00:00Z", None),
            row_json(ROW_B.0, ROW_B.1, "2026-10-08T09:30:00Z", None),
            row_json(
                ROW_SEEN.0,
                ROW_SEEN.1,
                "2026-10-07T09:00:00Z",
                Some("2026-10-07T10:00:00Z")
            ),
        ]),
    );
    read_set.tasks.insert(
        serde_json::from_value(json!(ROW_A.0)).expect("an id"),
        serde_json::from_value(task).expect("a task"),
    );
    read_set
}

#[test]
fn park_026_fr_015_the_acknowledgement_marks_each_unseen_row_once_and_ignores_unknown_keys() {
    let read_set = parked_rows();
    let unknown = ("task_unknown", ROW_A.1);
    let foreign_formulation = (ROW_A.0, "form_0b0e1f30-0000-4000-8000-0000000000ff");
    // Duplicates, an already seen row, an unknown task and a formulation the
    // task never had: each ignored without a trace.
    let command = ack_command(&[ROW_B, ROW_A, ROW_B, ROW_SEEN, unknown, foreign_formulation]);
    let set = park::decide(&read_set, &command, &exec(NOW, true, true)).expect("decided");
    assert_eq!(set.outcome, ChangeOutcome::Applied);
    assert_eq!(set.result, ResultRefs::default());
    assert!(set.effects.is_empty());
    let marked: Vec<_> = acks_of(&set)
        .iter()
        .map(|ack| (ack.task_id.as_str(), ack.formulation_id.as_str()))
        .collect();
    assert_eq!(marked, [ROW_B, ROW_A], "once each, in request order");
    for ack in acks_of(&set) {
        assert_eq!(ack.seen_at.as_ref().map(|at| at.as_str()), Some(NOW));
        // Only the seen mark changes: the rest of the stored row is kept.
        let stored = read_set
            .park_acks
            .iter()
            .find(|stored| stored.task_id == ack.task_id)
            .expect("a stored row");
        assert_eq!(
            ack,
            &ParkAck {
                seen_at: ack.seen_at.clone(),
                ..stored.clone()
            }
        );
    }
    assert_eq!(
        set.changes.len(),
        2,
        "the seen and unknown keys left no trace"
    );
}

#[test]
fn park_026_fr_015_the_acknowledgement_never_writes_or_bumps_a_task() {
    let read_set = parked_rows();
    let command = ack_command(&[ROW_A, ROW_B]);
    let set = park::decide(&read_set, &command, &exec(NOW, true, true)).expect("decided");
    assert!(tasks_of(&set).is_empty() && settings_of(&set).is_empty());
    assert!(
        set.affected_keys()
            .iter()
            .all(|(entity, _)| *entity == EntityType::ReviewParkAck)
    );
    let committed = support::commit(&read_set, &set);
    assert_eq!(committed.tasks, read_set.tasks, "no task revision moved");
    // The generic revision precondition does not exist for this command.
    let with_check = command_of(
        "review.parks_ack",
        "scope-example",
        json!({ "items": [{ "task_id": ROW_A.0, "formulation_id": ROW_A.1 }] }),
        json!([{ "entity_type": "task", "entity_id": ROW_A.0, "edit_revision": "1" }]),
    );
    let checked = park::decide(&read_set, &with_check, &exec(NOW, true, true)).expect("decided");
    assert_eq!(acks_of(&checked).len(), 1);
}

#[test]
fn park_026_fr_015_a_replayed_acknowledgement_over_the_committed_state_is_a_no_op() {
    let read_set = parked_rows();
    let command = ack_command(&[ROW_A, ROW_B]);
    let first = park::decide(&read_set, &command, &exec(NOW, true, true)).expect("decided");
    assert_eq!(first.changes.len(), 2);
    let committed = support::commit(&read_set, &first);
    for now in [NOW, "2026-10-09T12:05:00Z"] {
        assert_eq!(
            park::decide(&committed, &command, &exec(now, true, true)),
            Ok(ChangeSet::no_op()),
            "idempotent by state at {now}"
        );
    }
    // An empty request is the same accepted no-op.
    assert_eq!(
        park::decide(&read_set, &ack_command(&[]), &exec(NOW, true, true)),
        Ok(ChangeSet::no_op())
    );
}

#[test]
fn park_026_fr_015_a_park_written_after_the_acknowledgement_instant_stays_unseen() {
    // A repeat park of a formulation (a fresh, unseen row) is not marked by an
    // acknowledgement decided before it was parked.
    let mut read_set = parked_rows();
    read_set.park_acks = vec![
        serde_json::from_value(row_json(ROW_A.0, ROW_A.1, "2026-10-09T12:30:00Z", None))
            .expect("a row"),
    ];
    assert_eq!(
        park::decide(&read_set, &ack_command(&[ROW_A]), &exec(NOW, true, true)),
        Ok(ChangeSet::no_op())
    );
}

#[test]
fn park_026_fr_015_only_the_rows_a_request_names_are_read() {
    let mut read_set = parked_rows();
    let mut wide = row_json(ROW_B.0, ROW_B.1, "2026-10-08T09:30:00Z", None);
    wide["private"]["from_revision"] = json!("18446744073709551616");
    read_set.park_acks[1] = serde_json::from_value(wide).expect("a wire-valid row");
    // An unreadable row nobody asked about cannot refuse the acknowledgement ...
    let set =
        park::decide(&read_set, &ack_command(&[ROW_A]), &exec(NOW, true, true)).expect("decided");
    assert_eq!(acks_of(&set).len(), 1);
    // ... and one that was asked about is refused, never half-marked.
    let refusal = park::decide(
        &read_set,
        &ack_command(&[ROW_A, ROW_B]),
        &exec(NOW, true, true),
    )
    .expect_err("an unreadable row");
    assert_eq!(refusal.reason, Reason::InvalidValue);
}

#[test]
fn park_026_fr_015_a_command_of_another_family_is_refused_as_invalid_payload_on_type() {
    let read_set = parked_rows();
    let foreign = command_of(
        "review.session_finish",
        "review_0b0e1f30-0000-4000-8000-0000000000e9",
        json!({}),
        json!([]),
    );
    assert!(!park::handles(&foreign.command));
    assert_eq!(
        park::decide(&read_set, &foreign, &exec(NOW, true, true)),
        Err(DomainError::field(Reason::InvalidPayload, "type"))
    );
    assert!(park::handles(&ack_command(&[]).command));
}
