//! Parity of the Review session, settings, activation and consent rules and of
//! the `ReviewState` / `ReviewQueue` reads with the server (tasks.md T016,
//! PR-16, 026-FR-002, 026-FR-016, 026-SC-001).
//!
//! The oracle is the existing one, never the Rust output:
//!
//! * `review_flow_vectors.json` (steps, wins, capacity, Waiting and Someday
//!   passes, restart, session status, idle close, qualifying activity, counted
//!   reviews, regularity, next review, the decision queue),
//! * `review_wire_fixtures.json` (request bodies decode as catalog payloads,
//!   response bodies decode as the query result types, three of them are
//!   reproduced from a read set),
//! * `review_traces_runs.json` (all five run traces) and `review_traces_tasks.json`
//!   (TR-001, TR-005, TR-006) replayed against a small in-memory server that
//!   routes every request to `decide` / `query`,
//! * progress digests computed by the server's `progress_digest`,
//! * scenarios of `test_review_flow_api.py`, `test_review_settings_api.py` and
//!   `test_review_navigator.py`, named in each test.
//!
//! The family sources are compiled in place (`#[path]`) with the crate paths
//! they use inside `bb-domain`, so this runner does not depend on how the
//! library registers the modules. Every data-driven test counts the cases it
//! executed, so an empty or truncated section fails.

// The scenarios fill one `Store` field by field, as the server tests seed rows.
#![allow(clippy::field_reassign_with_default)]

mod support;

pub use bb_domain::{calendar, normalization, types};

#[allow(dead_code, unused_imports)]
#[path = "../src/formulation.rs"]
mod formulation;
#[allow(dead_code)]
#[path = "../src/park.rs"]
mod park;
#[allow(dead_code)]
#[path = "../src/queries.rs"]
mod queries;
#[allow(dead_code)]
#[path = "../src/review_sessions.rs"]
mod review_sessions;

use std::collections::{BTreeMap, HashMap};

use bb_domain::calendar::{TimeZone, UtcInstant};
use bb_protocol::command::{Decoded, decode_command};
use review_sessions::{
    Receipt, ReviewTask, SessionEnd, SessionSummary, SomedayQueue, StepProgress,
};
use serde_json::{Map, Value, json};
use support::{cases, text};
use types::{
    ChangeOutcome, ChangeSet, Command, CommandType, DomainChange, DomainCommand, DomainError,
    ExecutionInputs, Query, QueryInputs, QueryResult, QueueMeta, QueueView, ReadSet, Reason,
    Record, ReviewMode, ReviewSession, ReviewSettings, ReviewStateView, SessionStatus, StepCode,
    StepStatus, TaskState,
};

const NOW: &str = "2026-10-09T12:00:00Z";
const SCOPE: &str = "scope-example";
const SESSION_A: &str = "review_0b0e1f30-0000-4000-8000-0000000000a1";
const SESSION_B: &str = "review_0b0e1f30-0000-4000-8000-0000000000a2";
const PROVIDER: &str = "openai";

// ------------------------------------------------------------------ helpers

fn at(iso: &str) -> UtcInstant {
    UtcInstant::parse_rfc3339(iso).unwrap_or_else(|error| panic!("{iso}: {error}"))
}

fn at_opt(value: &Value) -> Option<UtcInstant> {
    value.as_str().map(at)
}

fn count(value: &Value) -> u32 {
    u32::try_from(value.as_u64().expect("a count")).expect("a small count")
}

fn strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .expect("a list")
        .iter()
        .map(|item| item.as_str().expect("a string").to_owned())
        .collect()
}

fn state_of(wire: &str) -> TaskState {
    TaskState::from_wire(wire).unwrap_or_else(|| panic!("task state {wire}"))
}

fn step_of(wire: &str) -> StepCode {
    StepCode::from_wire(wire).unwrap_or_else(|| panic!("step {wire}"))
}

fn status_of(wire: &str) -> SessionStatus {
    SessionStatus::from_wire(wire).unwrap_or_else(|| panic!("status {wire}"))
}

/// Wire revisions and order keys are decimal strings in sync v1 and numbers in
/// the HTTP bodies the fixtures hold: turn one into the other.
fn to_sync(value: &Value) -> Value {
    match value {
        Value::Object(members) => Value::Object(
            members
                .iter()
                .map(|(key, member)| {
                    let numeric =
                        matches!(key.as_str(), "revision" | "order_key" | "task_revision");
                    match member {
                        Value::Number(number) if numeric && number.is_u64() => {
                            (key.clone(), Value::String(number.to_string()))
                        }
                        other => (key.clone(), to_sync(other)),
                    }
                })
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(to_sync).collect()),
        other => other.clone(),
    }
}

fn to_http(value: &Value) -> Value {
    match value {
        Value::Object(members) => Value::Object(
            members
                .iter()
                .map(|(key, member)| {
                    let numeric =
                        matches!(key.as_str(), "revision" | "order_key" | "task_revision");
                    match member {
                        Value::String(digits) if numeric && digits.parse::<u64>().is_ok() => {
                            (key.clone(), json!(digits.parse::<u64>().unwrap_or(0)))
                        }
                        other => (key.clone(), to_http(other)),
                    }
                })
                .collect(),
        ),
        Value::Array(items) => Value::Array(items.iter().map(to_http).collect()),
        other => other.clone(),
    }
}

fn form_id(n: u32) -> String {
    format!("form_0b0e1f30-0000-4000-8000-{n:012x}")
}

// ------------------------------------------------------------------ rows

const CREATED: &str = "2026-09-02T09:00:00Z";

fn task(id: &str, state: &str, order_key: u64) -> Value {
    json!({
        "id": id, "title": format!("Title of {id}"), "details": null, "state": state,
        "project_id": null, "tag_ids": [], "due_date": null, "priority": "none",
        "waiting_for": if state == "waiting" { json!("Ann") } else { Value::Null },
        "waiting_since": null,
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

/// A Next task whose clock started at `started`.
fn next_task(n: u32, order_key: u64, started: &str) -> Value {
    with(
        with(
            task(&format!("task_n{n:03}"), "next", order_key),
            "revision",
            json!("1"),
        ),
        "formulation",
        json!({
            "id": form_id(n), "started_at": started, "extended_at": null,
            "extension_reason": null, "park_floor_at": null,
        }),
    )
}

fn project(id: &str, name: &str, state: &str) -> Value {
    json!({
        "id": id, "name": name, "color": null, "state": state, "revision": "1",
        "desired_outcome": null, "archived_at": null, "archived_before_lossless": false,
    })
}

fn settings_row(activated_at: Option<&str>) -> Value {
    json!({
        "threshold_days": 14, "review_weekday": 5, "review_time": "16:00",
        "time_zone": "UTC", "onboarded_at": null, "activated_at": activated_at,
        "owner_park_floor_at": null, "revision": "1",
    })
}

fn counts_zero() -> Value {
    json!({
        "done": 0, "reformulated": 0, "first_step": 0, "waiting": 0, "someday": 0,
        "cancelled": 0, "extended": 0, "inbox_processed": 0, "kept": 0, "moved_to_next": 0,
    })
}

fn quick_steps() -> Value {
    json!({"wins": "pending", "inbox": "pending", "decisions": "pending", "summary": "pending"})
}

fn session_row(id: &str, status: &str, started: &str, last: &str) -> Value {
    json!({
        "id": id, "mode": "quick", "entry": "list", "origin": "ios", "status": status,
        "started_at": started, "last_activity_at": last,
        "ended_at": if status == "open" { Value::Null } else { json!(last) },
        "current_step": "wins", "steps": quick_steps(), "active_seconds_by_step": {},
        "counts": counts_zero(), "set_aside_count": 0, "qualifying_activity": false,
        "clear_start": null, "revision": "1",
    })
}

fn receipt_row(task_id: &str, kind: &str, revision: u64, hidden_until: &str) -> Value {
    json!({
        "task_id": task_id, "kind": kind, "hidden_until": hidden_until,
        "task_revision": revision.to_string(), "reviewed_at": "2026-10-05T10:00:00Z",
        "source": "keep", "decision_id": null, "bulk_id": null,
    })
}

fn decision_row(id: &str, task_id: &str, session_id: &str) -> Value {
    json!({
        "id": id, "type": "first_step", "task_id": task_id, "session_id": session_id,
        "decided_at": "2026-10-09T11:00:00Z", "substantive": null, "stall_reason": null,
        "ai_use": "none", "yielded_auto_park": false, "formulation_id": null,
        "task_revision_before": "1", "task_revision_after": "2", "created_task_id": null,
        "navigator_request_id": null, "review_counts_as": "first_step",
        "client_decided_at": null, "reason_text": null, "undo_available_until": null,
    })
}

fn queue_row(session_id: &str, task_ids: Value, aside: &[&str]) -> Value {
    json!({
        "session_id": session_id, "task_ids": task_ids,
        "decided_task_ids": [], "set_aside_task_ids": aside,
    })
}

/// Rows to load as one owner's `ReadSet`.
#[derive(Default, Clone)]
struct Store {
    tasks: Vec<Value>,
    projects: Vec<Value>,
    settings: Option<Value>,
    sessions: Vec<Value>,
    queues: Vec<Value>,
    decisions: Vec<Value>,
    receipts: Vec<Value>,
    park_acks: Vec<Value>,
    consents: Vec<Value>,
}

fn keyed(rows: &[Value], key: &str) -> Value {
    Value::Object(
        rows.iter()
            .map(|row| (text(row, key).to_owned(), row.clone()))
            .collect::<Map<_, _>>(),
    )
}

impl Store {
    fn read_set(&self) -> ReadSet {
        serde_json::from_value(json!({
            "tasks": keyed(&self.tasks, "id"),
            "projects": keyed(&self.projects, "id"),
            "settings": self.settings,
            "sessions": keyed(&self.sessions, "id"),
            "decision_queues": keyed(&self.queues, "session_id"),
            "decisions": keyed(&self.decisions, "id"),
            "receipts": self.receipts,
            "park_acks": self.park_acks,
            "consents": self.consents,
        }))
        .unwrap_or_else(|error| panic!("a valid read set: {error}"))
    }
}

// ----------------------------------------------------------------- harness

fn exec_with(
    now: &str,
    authoritative: bool,
    provider: Option<&str>,
    allocated: &[&str],
) -> ExecutionInputs {
    serde_json::from_value(json!({
        "rule_version": 1, "now": now, "time_zone": "UTC", "origin": "device",
        "actor_id": "actor-example", "authoritative": authoritative,
        "allocated_ids": allocated,
        "policy": {
            "weekly_review": true, "navigator_provider": provider,
            "navigator_available": provider.is_some(), "consent_text_version": 1,
        },
    }))
    .expect("execution inputs")
}

fn exec(now: &str) -> ExecutionInputs {
    exec_with(now, true, Some(PROVIDER), &[])
}

fn query_inputs(now: &str, weekly_review: bool) -> QueryInputs {
    serde_json::from_value(json!({
        "now": now, "device_zone": "UTC",
        "policy": {
            "weekly_review": weekly_review, "navigator_provider": null,
            "navigator_available": false, "consent_text_version": 1,
        },
    }))
    .expect("query inputs")
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
        "scope_id": SCOPE, "device_id": "device-example", "device_epoch": "epoch-example",
        "local_sequence": "7", "type": kind, "command_version": 1, "entity_id": entity,
        "preconditions": checks, "depends_on": [], "issued_at": NOW, "payload": payload,
    })
    .to_string();
    match decode_command(&envelope) {
        Ok(Decoded::Executable(envelope)) => {
            DomainCommand::from_envelope(&envelope, &types::NoReceipts)
        }
        other => panic!("{kind} did not decode as an executable command: {other:?}"),
    }
}

fn command(kind: &str, entity: &str, payload: Value, checks: Vec<Value>) -> DomainCommand {
    try_command(kind, entity, payload, checks).unwrap_or_else(|e| panic!("{kind}: {e}"))
}

fn start_command(id: &str, mode: &str, skip: &[&str], replace_open: bool) -> DomainCommand {
    command(
        "review.session_start",
        id,
        json!({
            "mode": mode, "entry": "list", "origin": "ios", "skip_steps": skip,
            "replace_open": replace_open,
        }),
        vec![],
    )
}

fn progress_command(session: &str, progress_n: u32, body: Value) -> DomainCommand {
    let mut payload = body;
    payload["progress_id"] = json!(format!(
        "progress_0b0e1f30-0000-4000-8000-{progress_n:012x}"
    ));
    command("review.session_progress", session, payload, vec![])
}

fn finish_command(session: &str, clear_start: Option<&str>) -> DomainCommand {
    let payload = clear_start.map_or_else(|| json!({}), |answer| json!({ "clear_start": answer }));
    command("review.session_finish", session, payload, vec![])
}

fn settings_command(body: Value, revision: u64) -> DomainCommand {
    command(
        "review.settings",
        SCOPE,
        body,
        vec![check("review_settings", SCOPE, revision)],
    )
}

fn apply(read_set: &mut ReadSet, change_set: &ChangeSet) {
    for change in &change_set.changes {
        match change {
            DomainChange::Upsert(Record::ReviewSession(session)) => {
                read_set
                    .sessions
                    .insert(session.id.clone(), session.clone());
            }
            DomainChange::Upsert(Record::ReviewSettings(settings)) => {
                read_set.settings = Some(settings.clone());
            }
            DomainChange::Upsert(Record::ReviewDecisionQueue(queue)) => {
                read_set
                    .decision_queues
                    .insert(queue.session_id.clone(), queue.clone());
            }
            DomainChange::Upsert(Record::Task(task)) => {
                read_set.tasks.insert(task.id.clone(), task.clone());
            }
            DomainChange::Upsert(Record::ReviewNavigatorConsent(consent)) => {
                read_set
                    .consents
                    .retain(|held| held.provider != consent.provider);
                read_set.consents.push(consent.clone());
            }
            other => panic!("a change this family does not make: {other:?}"),
        }
    }
}

/// Decides and applies; the change set is returned.
fn run(read_set: &mut ReadSet, command: &DomainCommand, now: &str) -> ChangeSet {
    let change_set = review_sessions::decide(read_set, command, &exec(now))
        .unwrap_or_else(|error| panic!("{}: {error}", command.command_type().as_str()));
    apply(read_set, &change_set);
    change_set
}

fn refusal(read_set: &ReadSet, command: &DomainCommand, now: &str) -> DomainError {
    review_sessions::decide(read_set, command, &exec(now)).expect_err("the command is refused")
}

fn session_of<'a>(read_set: &'a ReadSet, id: &str) -> &'a ReviewSession {
    read_set
        .sessions
        .values()
        .find(|session| session.id.as_str() == id)
        .unwrap_or_else(|| panic!("no session {id}"))
}

fn ask(read_set: &ReadSet, query: &Query, now: &str) -> Result<QueryResult, DomainError> {
    review_sessions::query(read_set, query, &query_inputs(now, true))
}

fn review_state(read_set: &ReadSet, now: &str) -> ReviewStateView {
    match ask(read_set, &Query::ReviewState {}, now).expect("the state is answered") {
        QueryResult::ReviewState(state) => *state,
        other => panic!("not a state: {other:?}"),
    }
}

fn queue_query(step: &str, session: Option<&str>) -> Query {
    serde_json::from_value(json!({
        "kind": "review_queue", "step": step, "session_id": session,
    }))
    .expect("a valid queue query")
}

fn review_queue(read_set: &ReadSet, step: &str, session: Option<&str>, now: &str) -> QueueView {
    match ask(read_set, &queue_query(step, session), now).expect("the queue is answered") {
        QueryResult::ReviewQueue(queue) => queue,
        other => panic!("not a queue: {other:?}"),
    }
}

fn item_ids(queue: &QueueView) -> Vec<String> {
    queue
        .items
        .iter()
        .map(|item| item.id.as_str().to_owned())
        .collect()
}

fn as_json<T: serde::Serialize>(value: &T) -> Value {
    serde_json::to_value(value).expect("serializable")
}

// ----------------------------------------------------------- the flow vectors

fn review_task(raw: &Value) -> ReviewTask {
    ReviewTask {
        id: text(raw, "id").to_owned(),
        state: state_of(text(raw, "state")),
        revision: raw.get("revision").and_then(Value::as_u64).unwrap_or(1),
        completed_at: raw.get("completed_at").and_then(at_opt),
        waiting_since: raw.get("waiting_since").and_then(at_opt),
        updated_at: raw.get("updated_at").and_then(at_opt),
        parked_at: raw.get("parked_at").and_then(at_opt),
    }
}

fn vector_receipt(raw: &Value) -> Receipt {
    Receipt {
        task_id: text(raw, "task_id").to_owned(),
        kind: types::ReceiptKind::from_wire(text(raw, "kind")).expect("a receipt kind"),
        task_revision: raw["task_revision"].as_u64().expect("a revision"),
        reviewed_at: at(text(raw, "reviewed_at")),
        hidden_until: at(text(raw, "hidden_until")),
        source: types::ReceiptSource::from_wire(text(raw, "source")).expect("a source"),
    }
}

#[test]
fn review_sessions_026_fr_002_steps_follow_the_mode() {
    let vectors = cases(support::flow(), "steps");
    for case in vectors {
        let mode = ReviewMode::from_wire(text(case, "mode")).expect("a mode");
        let steps: Vec<&str> = review_sessions::review_steps(mode)
            .iter()
            .map(|step| step.as_str())
            .collect();
        assert_eq!(steps, strings(&case["expect"]), "{}", text(case, "id"));
    }
    assert_eq!(vectors.len(), 2);
}

#[test]
fn review_sessions_026_fr_002_wins_are_the_last_seven_days() {
    let vectors = cases(support::flow(), "wins");
    for case in vectors {
        let tasks: Vec<ReviewTask> = case["tasks"]
            .as_array()
            .expect("tasks")
            .iter()
            .map(review_task)
            .collect();
        let wins = review_sessions::wins(&tasks, at(text(case, "now")));
        assert_eq!(wins, strings(&case["expect"]), "{}", text(case, "id"));
    }
    assert_eq!(vectors.len(), 2);
}

#[test]
fn review_sessions_026_fr_002_capacity_mirror_needs_four_weeks_of_history() {
    let vectors = cases(support::flow(), "capacity");
    for case in vectors {
        let completed: Vec<UtcInstant> = strings(&case["completed_at"])
            .iter()
            .map(|iso| at(iso))
            .collect();
        let mirror = review_sessions::capacity_mirror(
            count(&case["next_count"]),
            &completed,
            at(text(case, "now")),
        );
        let expect = &case["expect"];
        let id = text(case, "id");
        assert_eq!(mirror.next_count, count(&expect["next_count"]), "{id}");
        assert_eq!(
            mirror.weeks_of_history,
            count(&expect["weeks_of_history"]),
            "{id}"
        );
        assert_eq!(
            mirror.weekly_average_4w,
            expect["weekly_average_4w"].as_f64(),
            "{id}"
        );
        assert_eq!(
            mirror.implied_weeks,
            expect["implied_weeks"].as_f64(),
            "{id}"
        );
    }
    assert_eq!(vectors.len(), 7);
}

#[test]
fn review_sessions_026_fr_002_waiting_pass_hides_current_receipts() {
    let vectors = cases(support::flow(), "waiting_queue");
    for case in vectors {
        let tasks: Vec<ReviewTask> = case["tasks"]
            .as_array()
            .expect("tasks")
            .iter()
            .map(review_task)
            .collect();
        let receipts: Vec<Receipt> = case["receipts"]
            .as_array()
            .expect("receipts")
            .iter()
            .map(vector_receipt)
            .collect();
        let due = review_sessions::waiting_queue(&tasks, &receipts, at(text(case, "now")));
        assert_eq!(due, strings(&case["expect"]), "{}", text(case, "id"));
    }
    assert_eq!(vectors.len(), 1);
}

#[test]
fn review_sessions_026_fr_002_someday_pass_orders_never_reviewed_first() {
    let vectors = cases(support::flow(), "someday_queue");
    for case in vectors {
        let tasks: Vec<ReviewTask> = case["tasks"]
            .as_array()
            .expect("tasks")
            .iter()
            .map(review_task)
            .collect();
        let receipts: Vec<Receipt> = case["receipts"]
            .as_array()
            .expect("receipts")
            .iter()
            .map(vector_receipt)
            .collect();
        let limit = usize::try_from(case["limit"].as_u64().expect("a limit")).expect("a limit");
        let pass = review_sessions::someday_queue(&tasks, &receipts, at(text(case, "now")), limit);
        let expect = &case["expect"];
        let id = text(case, "id");
        assert_eq!(
            pass,
            SomedayQueue {
                eligible_total: usize::try_from(expect["eligible_total"].as_u64().expect("total"))
                    .expect("total"),
                shown: strings(&expect["shown"]),
            },
            "{id}"
        );
    }
    assert_eq!(vectors.len(), 2);
}

#[test]
fn review_sessions_026_fr_002_restart_mode_anchors() {
    let vectors = cases(support::flow(), "restart");
    for case in vectors {
        let restart = review_sessions::restart_mode(
            at_opt(&case["onboarded_at"]),
            at_opt(&case["last_counted_review_at"]),
            at(text(case, "now")),
        );
        assert_eq!(
            Some(restart),
            case["expect"].as_bool(),
            "{}",
            text(case, "id")
        );
    }
    assert_eq!(vectors.len(), 6);
}

#[test]
fn review_sessions_026_fr_016_ended_runs_take_their_status_from_qualifying_activity() {
    let vectors = cases(support::flow(), "session_status");
    for case in vectors {
        let end = match text(case, "end") {
            "finish" => SessionEnd::Finish,
            "replace" => SessionEnd::Replace,
            "idle_close" => SessionEnd::IdleClose,
            other => panic!("end {other}"),
        };
        let qualifying = case["qualifying_activity"].as_bool().expect("a flag");
        assert_eq!(
            review_sessions::ended_status(end, qualifying).as_str(),
            text(case, "expect"),
            "{}",
            text(case, "id")
        );
    }
    assert_eq!(vectors.len(), 6);
}

#[test]
fn review_sessions_026_fr_016_idle_close_is_seven_days_inclusive() {
    let vectors = cases(support::flow(), "idle_close");
    for case in vectors {
        assert_eq!(
            Some(review_sessions::idle_close_due(
                at(text(case, "last_activity_at")),
                at(text(case, "now"))
            )),
            case["expect"].as_bool(),
            "{}",
            text(case, "id")
        );
    }
    assert_eq!(vectors.len(), 2);
}

#[test]
fn review_sessions_026_fr_016_qualifying_activity_ignores_the_summary_and_skips() {
    let vectors = cases(support::flow(), "qualifying_activity");
    for case in vectors {
        let steps: Vec<(StepCode, StepProgress)> = case["steps"]
            .as_object()
            .expect("steps")
            .iter()
            .map(|(code, step)| {
                (
                    step_of(code),
                    StepProgress {
                        status: StepStatus::from_wire(text(step, "status")).expect("a status"),
                        finished_empty: step["finished_empty"].as_bool().expect("a flag"),
                    },
                )
            })
            .collect();
        let decisions = case["item_decisions"].as_u64().expect("a count");
        assert_eq!(
            Some(review_sessions::qualifying_activity(decisions, &steps)),
            case["expect"].as_bool(),
            "{}",
            text(case, "id")
        );
    }
    assert_eq!(vectors.len(), 5);
}

#[test]
fn review_sessions_026_fr_016_counted_reviews_and_the_regularity_instant() {
    let counted = cases(support::flow(), "counted_review");
    for case in counted {
        assert_eq!(
            Some(review_sessions::is_counted(
                status_of(text(case, "status")),
                case["qualifying_activity"].as_bool().expect("a flag")
            )),
            case["expect"].as_bool(),
            "{}",
            text(case, "id")
        );
    }
    let regularity = cases(support::flow(), "regularity");
    for case in regularity {
        let sessions: Vec<SessionSummary> = case["sessions"]
            .as_array()
            .expect("sessions")
            .iter()
            .map(|raw| SessionSummary {
                status: status_of(text(raw, "status")),
                qualifying_activity: raw["qualifying_activity"].as_bool().expect("a flag"),
                last_activity_at: at(text(raw, "last_activity_at")),
                ended_at: at_opt(&raw["ended_at"]),
            })
            .collect();
        assert_eq!(
            review_sessions::last_counted_review_at(&sessions),
            at_opt(&case["expect"]),
            "{}",
            text(case, "id")
        );
    }
    assert_eq!((counted.len(), regularity.len()), (6, 3));
}

#[test]
fn review_sessions_026_fr_002_next_review_is_the_local_slot_with_the_skip() {
    let vectors = cases(support::flow(), "next_review");
    for case in vectors {
        let settings = &case["settings"];
        let zone = TimeZone::named(text(settings, "time_zone")).expect("a zone");
        let time = text(settings, "review_time");
        let (hour, minute) = time.split_once(':').expect("HH:MM");
        let weekday = u8::try_from(settings["review_weekday"].as_u64().expect("a weekday"))
            .expect("a weekday");
        let slot = review_sessions::next_review_at(
            weekday,
            (hour.parse().expect("hour"), minute.parse().expect("minute")),
            &zone,
            at(text(case, "now")),
            at_opt(&case["last_counted_review_at"]),
        );
        assert_eq!(slot, at(text(case, "expect")), "{}", text(case, "id"));
    }
    assert_eq!(vectors.len(), 10);
}

/// DQ-001 through the whole `decisions` step: the live aggregate of a read set.
#[test]
fn review_sessions_026_fr_002_decisions_step_is_the_vector_decision_queue() {
    let vectors = cases(support::flow(), "decision_queue");
    for case in vectors {
        let rows: Vec<Value> = case["tasks"]
            .as_array()
            .expect("tasks")
            .iter()
            .enumerate()
            .map(|(index, raw)| {
                let mut row = task(text(raw, "id"), text(raw, "state"), index as u64 + 1);
                row["due_date"] = raw["due_date"].clone();
                row["consecutive_stalled_formulations"] =
                    raw["consecutive_stalled_formulations"].clone();
                if let Some(started) = raw["formulation_started_at"].as_str() {
                    row["formulation"] = json!({
                        "id": form_id(index as u32 + 1), "started_at": started,
                        "extended_at": raw["formulation_extended_at"],
                        "extension_reason": null,
                        "park_floor_at": raw["formulation_park_floor_at"],
                    });
                }
                row
            })
            .collect();
        let settings = &case["settings"];
        let store = Store {
            tasks: rows,
            settings: Some(json!({
                "threshold_days": settings["threshold_days"], "review_weekday": 5,
                "review_time": "16:00", "time_zone": settings["time_zone"],
                "onboarded_at": null, "activated_at": settings["activated_at"],
                "owner_park_floor_at": settings["owner_park_floor_at"], "revision": "1",
            })),
            ..Store::default()
        };
        let queue = review_queue(&store.read_set(), "decisions", None, text(case, "now"));
        assert_eq!(
            item_ids(&queue),
            strings(&case["expect"]),
            "{}",
            text(case, "id")
        );
    }
    assert_eq!(vectors.len(), 1);
}

// ------------------------------------------------------------- wire fixtures

fn wire_entries(models: &[&str]) -> Vec<&'static Value> {
    let entries: Vec<&Value> = cases(wire_file(), "entries")
        .iter()
        .filter(|entry| models.contains(&text(entry, "model")))
        .collect();
    assert!(!entries.is_empty(), "no wire fixtures for {models:?}");
    entries
}

fn payload_of(body: &Value) -> Map<String, Value> {
    let mut payload = body.as_object().expect("an object").clone();
    payload.remove("expected_revision");
    payload.remove("id");
    payload
}

#[test]
fn review_sessions_026_fr_002_valid_request_fixtures_are_catalog_payloads() {
    let routes = [
        ("SessionStartRequest", CommandType::ReviewSessionStart),
        ("SessionProgressRequest", CommandType::ReviewSessionProgress),
        ("SessionFinishRequest", CommandType::ReviewSessionFinish),
        ("ReviewSettingsUpdateRequest", CommandType::ReviewSettings),
        (
            "ExplainerAcknowledgeRequest",
            CommandType::ReviewExplainerAck,
        ),
        (
            "NavigatorConsentGrantRequest",
            CommandType::ReviewConsentGrant,
        ),
    ];
    let mut executed = 0;
    for (model, command_type) in routes {
        for entry in wire_entries(&[model]) {
            let payload = payload_of(&entry["body"]);
            let parsed = Command::from_payload(command_type, &payload);
            if entry["valid"].as_bool() == Some(true) {
                let command = parsed.unwrap_or_else(|e| panic!("{}: {e}", text(entry, "id")));
                assert!(review_sessions::handles(&command), "{}", text(entry, "id"));
            } else {
                assert_eq!(
                    parsed.expect_err("refused").reason,
                    Reason::InvalidPayload,
                    "{}",
                    text(entry, "id")
                );
            }
            executed += 1;
        }
    }
    // starts 2, progress 4 (2 valid, 2 invalid), finish 1, settings 3 (2 valid,
    // 1 invalid), explainer 1, consent 1
    assert_eq!(executed, 12);
}

#[test]
fn review_sessions_026_fr_002_response_fixtures_decode_as_the_query_results() {
    let mut executed = 0;
    for entry in wire_entries(&["ReviewStateResponse"]) {
        let state: ReviewStateView =
            serde_json::from_value(to_sync(&entry["body"])).expect("a state");
        assert_eq!(
            to_http(&as_json(&state)),
            entry["body"],
            "{}",
            text(entry, "id")
        );
        executed += 1;
    }
    for entry in wire_entries(&["QueueResponse"]) {
        let queue: QueueView = serde_json::from_value(to_sync(&entry["body"])).expect("a queue");
        assert_eq!(
            to_http(&as_json(&queue)),
            entry["body"],
            "{}",
            text(entry, "id")
        );
        executed += 1;
    }
    for entry in wire_entries(&["SessionResponse"]) {
        let decoded = serde_json::from_value::<ReviewSession>(to_sync(&entry["body"]));
        if entry["valid"].as_bool() == Some(true) {
            let session = decoded.expect("a session");
            assert_eq!(
                to_http(&as_json(&session)),
                entry["body"],
                "{}",
                text(entry, "id")
            );
        } else {
            assert!(decoded.is_err(), "{}", text(entry, "id"));
        }
        executed += 1;
    }
    for entry in wire_entries(&["ReviewSettingsResponse"]) {
        let settings: ReviewSettings =
            serde_json::from_value(to_sync(&entry["body"])).expect("settings");
        assert_eq!(
            to_http(&as_json(&settings)),
            entry["body"],
            "{}",
            text(entry, "id")
        );
        executed += 1;
    }
    // 2 states, 6 queues, 3 sessions, 1 settings
    assert_eq!(executed, 12);
}

fn fixture(id: &str) -> &'static Value {
    wire_entries(&["ReviewStateResponse", "QueueResponse"])
        .into_iter()
        .find(|entry| text(entry, "id") == id)
        .unwrap_or_else(|| panic!("no fixture {id}"))
}

#[test]
fn review_sessions_026_fr_002_a_new_owner_state_is_the_defaults_fixture() {
    let state = review_state(&Store::default().read_set(), "2026-10-09T12:00:00Z");
    assert_eq!(to_http(&as_json(&state)), fixture("W-031")["body"]);
}

#[test]
fn review_sessions_026_fr_002_wins_and_dates_queues_reproduce_their_fixtures() {
    // A queue item is a `TaskResponse`: the stored task has no children and
    // keeps the stalled count beside, not inside, its clock.
    let item_of = |id: &str| {
        let mut row = to_sync(&fixture(id)["body"]["items"][0]);
        let members = row.as_object_mut().expect("an item");
        members.remove("subtasks");
        members.remove("comments");
        members.insert("consecutive_stalled_formulations".to_owned(), json!(0));
        row
    };
    let wins = Store {
        tasks: vec![item_of("W-047")],
        ..Store::default()
    };
    let got = review_queue(&wins.read_set(), "wins", None, "2026-10-09T14:05:13Z");
    assert_eq!(to_http(&as_json(&got)), fixture("W-047")["body"]);

    let dates = Store {
        tasks: vec![item_of("W-051")],
        ..Store::default()
    };
    let got = review_queue(&dates.read_set(), "dates", None, "2026-10-09T14:05:13Z");
    assert_eq!(to_http(&as_json(&got)), fixture("W-051")["body"]);
}

/// W-048 and W-049: every Next task is in the run's captured queue, so the
/// rest of Next lists none and the meta is the capacity mirror of CAP-001 /
/// CAP-002.
#[test]
fn review_sessions_026_fr_002_rest_of_next_queues_reproduce_the_capacity_fixtures() {
    for (fixture_id, vector_id) in [("W-048", "CAP-001"), ("W-049", "CAP-002")] {
        let vector = cases(support::flow(), "capacity")
            .iter()
            .find(|case| text(case, "id") == vector_id)
            .expect("a capacity vector");
        let next_count =
            usize::try_from(vector["next_count"].as_u64().expect("count")).expect("count");
        let mut tasks: Vec<Value> = (0..next_count)
            .map(|n| task(&format!("task_n{n:03}"), "next", n as u64 + 1))
            .collect();
        for (n, completed) in strings(&vector["completed_at"]).iter().enumerate() {
            tasks.push(with(
                with(
                    task(&format!("task_c{n:03}"), "completed", 1),
                    "completed_at",
                    json!(completed),
                ),
                "revision",
                json!("2"),
            ));
        }
        let ids: Vec<String> = (0..next_count).map(|n| format!("task_n{n:03}")).collect();
        let store = Store {
            tasks,
            sessions: vec![session_row(SESSION_A, "open", NOW, NOW)],
            queues: vec![queue_row(SESSION_A, json!(ids), &[])],
            ..Store::default()
        };
        let got = review_queue(
            &store.read_set(),
            "rest_of_next",
            Some(SESSION_A),
            text(vector, "now"),
        );
        assert_eq!(
            to_http(&as_json(&got)),
            fixture(fixture_id)["body"],
            "{fixture_id}"
        );
    }
}

#[test]
fn review_sessions_026_fr_016_progress_digests_equal_the_servers() {
    // Computed with the server's `progress_digest`: SHA-256 of the canonical
    // body without `progress_id`.
    let digests = [
        (
            json!({"current_step": "decisions", "step": {"code": "wins", "status": "finished"},
                   "active_seconds": {"code": "wins", "seconds": 42}, "inbox_processed_delta": -1}),
            "406773182ad270965035d51432439dfda78959654c2c9a92686454bee6dff794",
        ),
        (
            json!({"set_aside_task_id": "task_6d2f8b4a1c7e", "snapshot_decision_queue": true}),
            "ad73617978b858de42296c039c6922ab8e4fda74d49162ff838e0f6a49ef1fde",
        ),
        (
            json!({"current_step": "decisions", "active_seconds": {"code": "decisions", "seconds": 30},
                   "inbox_processed_delta": 1}),
            "4142319f805b92190cd31256e41113a215362846ad238d95358267403aca34ca",
        ),
        (
            json!({"inbox_processed_delta": 2}),
            "60ad7769c89fc22230c41c488c4920806b66122cb7e08bbcc1f3daa337155718",
        ),
        (
            json!({"current_step": "summary"}),
            "f846a916871169a50354a9231c4b3e67613330bbae9a837b1585fe27f4ea1e47",
        ),
        (
            json!({}),
            "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        ),
        (
            json!({"set_aside_task_id": "task_caf\u{e9}\u{1f600}"}),
            "b2316a072663aa451c816613ebe5df2035ac7d14e16049dc0470781e72db2ba6",
        ),
    ];
    for (n, (body, expected)) in digests.iter().enumerate() {
        let command = progress_command(SESSION_A, 0x100 + n as u32, body.clone());
        let Command::ReviewSessionProgress(progress) = command.command else {
            panic!("a progress command");
        };
        assert_eq!(
            review_sessions::progress_digest(&progress),
            *expected,
            "{body}"
        );
    }
}

// ------------------------------------------------------------ session lifecycle

/// `test_020_FR_027_020_FR_028_quick_and_full_runs_start_with_their_steps` and
/// the offline start of W-040.
#[test]
fn review_sessions_026_fr_002_a_run_starts_on_its_first_unskipped_step() {
    let mut read_set = Store::default().read_set();
    let change_set = run(
        &mut read_set,
        &start_command(SESSION_A, "quick", &["wins", "inbox"], true),
        NOW,
    );
    assert_eq!(change_set.outcome, ChangeOutcome::Applied);
    let run_a = as_json(session_of(&read_set, SESSION_A));
    assert_eq!(
        run_a,
        json!({
            "id": SESSION_A, "mode": "quick", "entry": "list", "origin": "ios", "status": "open",
            "started_at": NOW, "last_activity_at": NOW, "ended_at": null,
            "current_step": "decisions",
            "steps": {"wins": "skipped", "inbox": "skipped", "decisions": "pending", "summary": "pending"},
            "active_seconds_by_step": {}, "counts": counts_zero(), "set_aside_count": 0,
            "qualifying_activity": false, "clear_start": null, "revision": "1",
            "private": {"applied_progress": {}, "finished_empty": []},
        })
    );
    let full = run(
        &mut read_set,
        &start_command(SESSION_B, "full", &[], true),
        NOW,
    );
    assert_eq!(full.changes.len(), 2, "the open run is replaced");
    let steps = &session_of(&read_set, SESSION_B).steps;
    assert_eq!(steps.len(), 10);
    assert!(steps.values().all(|status| *status == StepStatus::Pending));
    assert_eq!(
        session_of(&read_set, SESSION_B).current_step,
        Some(StepCode::Wins)
    );
}

#[test]
fn review_sessions_026_fr_016_a_device_without_private_state_writes_none() {
    let mut read_set = Store::default().read_set();
    let inputs = exec_with(NOW, false, None, &[]);
    let change_set = review_sessions::decide(
        &read_set,
        &start_command(SESSION_A, "quick", &[], false),
        &inputs,
    )
    .expect("started");
    apply(&mut read_set, &change_set);
    assert!(session_of(&read_set, SESSION_A).private.is_none());
}

/// `test_020_FR_029_an_open_run_without_replace_open_is_open_session_exists` and
/// `..._replace_open_ends_the_open_run_by_the_e3_rule`.
#[test]
fn review_sessions_026_fr_016_an_open_run_is_replaced_partial_or_abandoned() {
    let mut read_set = Store::default().read_set();
    run(
        &mut read_set,
        &start_command(SESSION_A, "full", &[], false),
        NOW,
    );

    let blocked = refusal(
        &read_set,
        &start_command(SESSION_B, "quick", &[], false),
        NOW,
    );
    assert_eq!(blocked.reason, Reason::IdAlreadyExists);
    assert_eq!(blocked.field.as_deref(), Some("replace_open"));
    assert_eq!(
        blocked.entity,
        Some((types::EntityType::ReviewSession, vec![SESSION_A.to_owned()]))
    );

    // Without activity the replaced run is abandoned.
    let mut abandoned = read_set.clone();
    run(
        &mut abandoned,
        &start_command(SESSION_B, "quick", &[], true),
        "2026-10-09T12:05:00Z",
    );
    let replaced = session_of(&abandoned, SESSION_A);
    assert_eq!(replaced.status, SessionStatus::Abandoned);
    assert_eq!(as_json(&replaced.ended_at), json!("2026-10-09T12:05:00Z"));
    assert_eq!(as_json(&replaced.revision), json!("2"));
    assert_eq!(
        session_of(&abandoned, SESSION_B).status,
        SessionStatus::Open
    );

    // With a finished step it is partial.
    run(
        &mut read_set,
        &progress_command(
            SESSION_A,
            1,
            json!({"step": {"code": "wins", "status": "finished"}}),
        ),
        "2026-10-09T12:01:00Z",
    );
    run(
        &mut read_set,
        &start_command(SESSION_B, "quick", &[], true),
        "2026-10-09T12:05:00Z",
    );
    assert_eq!(
        session_of(&read_set, SESSION_A).status,
        SessionStatus::Partial
    );
    assert!(
        session_of(&read_set, SESSION_A)
            .private
            .as_ref()
            .expect("private")
            .applied_progress
            .is_empty(),
        "applied progress is dropped when the run ends"
    );
}

/// `test_020_FR_011_a_start_replays_by_key_and_a_reused_id_matches_or_conflicts`.
#[test]
fn review_sessions_026_fr_016_a_reused_session_id_matches_or_conflicts() {
    let mut read_set = Store::default().read_set();
    run(
        &mut read_set,
        &start_command(SESSION_A, "quick", &[], true),
        NOW,
    );
    let again = review_sessions::decide(
        &read_set,
        &start_command(SESSION_A, "quick", &[], false),
        &exec("2026-10-09T13:00:00Z"),
    )
    .expect("the stored run answers");
    assert_eq!(again.outcome, ChangeOutcome::NoOp);

    let other_mode = refusal(&read_set, &start_command(SESSION_A, "full", &[], true), NOW);
    assert_eq!(
        (other_mode.reason, other_mode.field.as_deref()),
        (Reason::IdAlreadyExists, Some("id"))
    );
    let legacy_new_id = refusal(
        &Store::default().read_set(),
        &start_command("review_2b7d9f1c3e5a", "quick", &[], true),
        NOW,
    );
    assert_eq!(
        legacy_new_id.reason,
        Reason::InvalidValue,
        "a new run carries the client shape"
    );
}

/// `test_020_FR_029_020_SC_004_progress_merges_monotonically_without_conflict`.
#[test]
fn review_sessions_026_fr_016_progress_merges_monotonically_without_conflict() {
    let mut store = Store::default();
    store.settings = Some(settings_row(Some("2026-09-01T08:00:00Z")));
    store.tasks = vec![
        task("task_own", "next", 1),
        task("task_done", "completed", 2),
    ];
    let mut read_set = store.read_set();
    run(
        &mut read_set,
        &start_command(SESSION_A, "full", &[], true),
        NOW,
    );
    let mut n = 0;
    let mut step = |read_set: &mut ReadSet, body: Value| {
        n += 1;
        run(
            read_set,
            &progress_command(SESSION_A, n, body),
            "2026-10-09T12:01:00Z",
        );
    };
    let steps_of = |read_set: &ReadSet| session_of(read_set, SESSION_A).steps.clone();

    step(
        &mut read_set,
        json!({"step": {"code": "wins", "status": "finished"}}),
    );
    step(
        &mut read_set,
        json!({"step": {"code": "wins", "status": "pending"}}),
    );
    assert_eq!(steps_of(&read_set)[&StepCode::Wins], StepStatus::Finished);
    step(
        &mut read_set,
        json!({"step": {"code": "inbox", "status": "skipped"}}),
    );
    step(
        &mut read_set,
        json!({"step": {"code": "inbox", "status": "finished"}}),
    );
    assert_eq!(steps_of(&read_set)[&StepCode::Inbox], StepStatus::Finished);
    step(
        &mut read_set,
        json!({"step": {"code": "inbox", "status": "skipped"}}),
    );
    assert_eq!(steps_of(&read_set)[&StepCode::Inbox], StepStatus::Finished);

    step(&mut read_set, json!({"current_step": "decisions"}));
    step(&mut read_set, json!({"current_step": "inbox"}));
    assert_eq!(
        session_of(&read_set, SESSION_A).current_step,
        Some(StepCode::Inbox)
    );

    step(
        &mut read_set,
        json!({"active_seconds": {"code": "wins", "seconds": 40}}),
    );
    step(
        &mut read_set,
        json!({"active_seconds": {"code": "wins", "seconds": 2}}),
    );
    assert_eq!(
        session_of(&read_set, SESSION_A).active_seconds_by_step[&StepCode::Wins],
        42
    );

    step(&mut read_set, json!({"inbox_processed_delta": 2}));
    step(&mut read_set, json!({"inbox_processed_delta": -1}));
    assert_eq!(session_of(&read_set, SESSION_A).counts.inbox_processed, 1);
    step(&mut read_set, json!({"inbox_processed_delta": -5}));
    assert_eq!(session_of(&read_set, SESSION_A).counts.inbox_processed, 0);

    step(&mut read_set, json!({"set_aside_task_id": "task_own"}));
    step(&mut read_set, json!({"set_aside_task_id": "task_own"}));
    step(&mut read_set, json!({"set_aside_task_id": "task_done"}));
    step(
        &mut read_set,
        json!({"set_aside_task_id": "task_000000000000"}),
    );
    let merged = session_of(&read_set, SESSION_A);
    assert_eq!(merged.set_aside_count, 1);
    let aside: Vec<&str> = read_set.decision_queues[&merged.id]
        .set_aside_task_ids
        .iter()
        .map(|id| id.as_str())
        .collect();
    assert_eq!(aside, ["task_own"]);
    assert_eq!(merged.status, SessionStatus::Open);
    assert_eq!(as_json(&merged.revision), json!(format!("{}", 1 + n)));
}

/// `test_020_FR_011_020_SC_004_a_progress_change_resent_is_merged_once` and
/// `..._the_same_progress_id_with_another_body_is_id_conflict`.
#[test]
fn review_sessions_026_fr_016_a_progress_change_is_merged_once() {
    let mut read_set = Store::default().read_set();
    run(
        &mut read_set,
        &start_command(SESSION_A, "quick", &[], true),
        NOW,
    );
    let body = json!({"inbox_processed_delta": 1, "current_step": "decisions"});
    let first = run(
        &mut read_set,
        &progress_command(SESSION_A, 7, body.clone()),
        "2026-10-09T12:01:00Z",
    );
    assert_eq!(first.outcome, ChangeOutcome::Applied);
    let moved = progress_command(SESSION_A, 8, json!({"current_step": "summary"}));
    run(&mut read_set, &moved, "2026-10-09T12:02:00Z");

    // The retry after the idempotency retention: merged nothing, answered as it stands.
    let retry = review_sessions::decide(
        &read_set,
        &progress_command(SESSION_A, 7, body),
        &exec("2026-10-10T13:00:00Z"),
    )
    .expect("a replay");
    assert_eq!(retry.outcome, ChangeOutcome::NoOp);
    let current = session_of(&read_set, SESSION_A);
    assert_eq!(
        (current.counts.inbox_processed, current.current_step),
        (1, Some(StepCode::Summary))
    );

    let conflict = refusal(
        &read_set,
        &progress_command(SESSION_A, 7, json!({"inbox_processed_delta": 2})),
        NOW,
    );
    assert_eq!(
        (conflict.reason, conflict.field.as_deref()),
        (Reason::IdAlreadyExists, Some("progress_id"))
    );
}

/// `test_020_FR_028_a_quick_run_refuses_progress_for_a_step_outside_its_mode` and
/// `test_020_FR_029_progress_on_a_finished_run_is_accepted_and_ignored`.
#[test]
fn review_sessions_026_fr_016_progress_names_the_runs_own_steps_and_an_ended_run_ignores_it() {
    let mut read_set = Store::default().read_set();
    run(
        &mut read_set,
        &start_command(SESSION_A, "quick", &[], true),
        NOW,
    );
    for (n, (body, field)) in [
        (
            json!({"step": {"code": "dates", "status": "finished"}}),
            "step",
        ),
        (
            json!({"step": {"code": "mind_sweep", "status": "skipped"}}),
            "step",
        ),
        (
            json!({"active_seconds": {"code": "rest_of_next", "seconds": 30}}),
            "active_seconds",
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let error = refusal(
            &read_set,
            &progress_command(SESSION_A, 20 + n as u32, body),
            NOW,
        );
        assert_eq!(
            (error.reason, error.field.as_deref()),
            (Reason::StepNotInReview, Some(field))
        );
    }
    let own = run(
        &mut read_set,
        &progress_command(
            SESSION_A,
            30,
            json!({"step": {"code": "inbox", "status": "finished"}}),
        ),
        NOW,
    );
    assert_eq!(own.outcome, ChangeOutcome::Applied);

    run(&mut read_set, &finish_command(SESSION_A, None), NOW);
    let ignored = review_sessions::decide(
        &read_set,
        &progress_command(
            SESSION_A,
            31,
            json!({"inbox_processed_delta": 3, "current_step": "wins"}),
        ),
        &exec(NOW),
    )
    .expect("accepted");
    assert_eq!(ignored.outcome, ChangeOutcome::NoOp);
    // A step outside the run is refused whatever the run's status.
    let outside = refusal(
        &read_set,
        &progress_command(
            SESSION_A,
            32,
            json!({"step": {"code": "dates", "status": "finished"}}),
        ),
        NOW,
    );
    assert_eq!(outside.reason, Reason::StepNotInReview);
    let missing = refusal(
        &read_set,
        &progress_command("review_0b0e1f30-0000-4000-8000-0000000000ff", 33, json!({})),
        NOW,
    );
    assert_eq!(missing.reason, Reason::SessionNotFound);
}

/// `test_020_FR_028_020_FR_034_the_decision_queue_is_a_stable_snapshot` and
/// `..._an_empty_snapshot_stays_taken`.
#[test]
fn review_sessions_026_fr_016_the_decision_queue_is_captured_once_and_empty_stays_captured() {
    let started = "2026-09-24T12:00:00Z";
    let mut store = Store::default();
    store.settings = Some(settings_row(Some("2026-09-01T08:00:00Z")));
    store.tasks = vec![
        next_task(1, 1, started),
        next_task(2, 2, started),
        next_task(3, 3, "2026-10-09T08:00:00Z"),
    ];
    let mut read_set = store.read_set();
    run(
        &mut read_set,
        &start_command(SESSION_A, "quick", &[], true),
        NOW,
    );
    run(
        &mut read_set,
        &progress_command(
            SESSION_A,
            1,
            json!({"snapshot_decision_queue": true, "current_step": "decisions"}),
        ),
        NOW,
    );
    let ids = |read_set: &ReadSet| {
        read_set
            .decision_queues
            .values()
            .next()
            .expect("a queue row")
            .task_ids
            .as_ref()
            .map(|ids| {
                ids.iter()
                    .map(|id| id.as_str().to_owned())
                    .collect::<Vec<_>>()
            })
    };
    assert_eq!(
        ids(&read_set),
        Some(vec!["task_n001".to_owned(), "task_n002".to_owned()])
    );

    // A task asking later does not join the captured run.
    read_set.tasks.insert(
        types::TaskId::parse("task_n004").expect("an id"),
        serde_json::from_value(next_task(4, 4, started)).expect("a task"),
    );
    let again = review_sessions::decide(
        &read_set,
        &progress_command(SESSION_A, 2, json!({"snapshot_decision_queue": true})),
        &exec(NOW),
    )
    .expect("applied");
    apply(&mut read_set, &again);
    assert_eq!(ids(&read_set).map(|ids| ids.len()), Some(2));
    assert_eq!(
        item_ids(&review_queue(&read_set, "decisions", Some(SESSION_A), NOW)),
        ["task_n001", "task_n002"]
    );
    assert_eq!(
        item_ids(&review_queue(&read_set, "decisions", None, NOW)),
        ["task_n001", "task_n002", "task_n004"],
        "without a run the queue is the live aggregate"
    );

    // Nothing asks: the snapshot is the captured-empty list, not an absent one.
    let mut empty = Store::default().read_set();
    run(
        &mut empty,
        &start_command(SESSION_B, "quick", &[], true),
        NOW,
    );
    assert!(
        empty.decision_queues.is_empty(),
        "an uncaptured queue has no row"
    );
    run(
        &mut empty,
        &progress_command(SESSION_B, 3, json!({"snapshot_decision_queue": true})),
        NOW,
    );
    let row = empty.decision_queues.values().next().expect("a row");
    assert_eq!(row.task_ids, Some(Vec::new()));
}

/// `test_020_FR_029_finish_means_done_completed_or_completed_empty` and the
/// finish trace of TR-R05.
#[test]
fn review_sessions_026_fr_016_finish_means_done_completed_or_completed_empty() {
    let cases: [(Vec<Value>, &str); 5] = [
        (vec![], "completed_empty"),
        (
            vec![json!({"step": {"code": "wins", "status": "skipped"}})],
            "completed_empty",
        ),
        (
            vec![json!({"step": {"code": "wins", "status": "finished"}})],
            "completed",
        ),
        (vec![json!({"inbox_processed_delta": 1})], "completed"),
        (
            vec![json!({"step": {"code": "summary", "status": "finished"}})],
            "completed_empty",
        ),
    ];
    for (n, (progress, status)) in cases.into_iter().enumerate() {
        let mut read_set = Store::default().read_set();
        run(
            &mut read_set,
            &start_command(SESSION_A, "quick", &[], true),
            NOW,
        );
        for (m, body) in progress.into_iter().enumerate() {
            run(
                &mut read_set,
                &progress_command(SESSION_A, (n * 10 + m) as u32 + 1, body),
                NOW,
            );
        }
        let later = "2026-10-09T12:04:00Z";
        let done = run(
            &mut read_set,
            &finish_command(SESSION_A, Some("yes")),
            later,
        );
        assert_eq!(done.outcome, ChangeOutcome::Applied);
        let finished = session_of(&read_set, SESSION_A);
        assert_eq!(finished.status.as_str(), status, "case {n}");
        assert_eq!(as_json(&finished.ended_at), json!(later));
        assert_eq!(finished.clear_start, Some(types::ClearStart::Yes));
        let again = review_sessions::decide(
            &read_set,
            &finish_command(SESSION_A, Some("not_really")),
            &exec(later),
        )
        .expect("returned unchanged");
        assert_eq!(again.outcome, ChangeOutcome::NoOp);
    }
}

/// `test_020_FR_029_a_step_with_items_left_to_decide_does_not_qualify`,
/// `..._display_steps_always_nothing_to_decide`.
#[test]
fn review_sessions_026_fr_016_finishing_a_step_qualifies_only_with_nothing_to_decide() {
    let mut store = Store::default();
    store.tasks = vec![task("task_inbox", "inbox", 1)];
    let mut read_set = store.read_set();
    run(
        &mut read_set,
        &start_command(SESSION_A, "full", &[], true),
        NOW,
    );
    let merged = run(
        &mut read_set,
        &progress_command(
            SESSION_A,
            1,
            json!({"step": {"code": "inbox", "status": "finished"}}),
        ),
        NOW,
    );
    assert_eq!(merged.outcome, ChangeOutcome::Applied);
    assert!(!session_of(&read_set, SESSION_A).qualifying_activity);

    for (n, step) in ["wins", "mind_sweep", "rest_of_next", "dates"]
        .into_iter()
        .enumerate()
    {
        let mut display = Store::default().read_set();
        run(
            &mut display,
            &start_command(SESSION_B, "full", &[], true),
            NOW,
        );
        run(
            &mut display,
            &progress_command(
                SESSION_B,
                50 + n as u32,
                json!({"step": {"code": step, "status": "finished"}}),
            ),
            NOW,
        );
        let session = session_of(&display, SESSION_B);
        assert!(session.qualifying_activity, "{step}");
        assert_eq!(session.counts, types::SessionCounts::default(), "{step}");
    }

    // The summary never qualifies; an empty Waiting, Someday or Projects step does.
    let mut empty = Store::default().read_set();
    run(
        &mut empty,
        &start_command(SESSION_B, "full", &[], true),
        NOW,
    );
    run(
        &mut empty,
        &progress_command(
            SESSION_B,
            60,
            json!({"step": {"code": "summary", "status": "finished"}}),
        ),
        NOW,
    );
    assert!(!session_of(&empty, SESSION_B).qualifying_activity);
    for (n, step) in ["inbox", "decisions", "waiting", "projects", "someday"]
        .into_iter()
        .enumerate()
    {
        run(
            &mut empty,
            &progress_command(
                SESSION_B,
                70 + n as u32,
                json!({"step": {"code": step, "status": "finished"}}),
            ),
            NOW,
        );
    }
    let qualified = session_of(&empty, SESSION_B);
    assert!(qualified.qualifying_activity);
    let finished_empty = &qualified.private.as_ref().expect("private").finished_empty;
    assert!(!finished_empty.contains(&StepCode::Summary));
    assert_eq!(finished_empty.len(), 5);
}

/// `test_020_FR_029_the_seven_day_idle_close_runs_in_the_sweep`.
#[test]
fn review_sessions_026_fr_016_idle_runs_close_seven_days_after_their_last_activity() {
    for (activity, status) in [
        (false, SessionStatus::Abandoned),
        (true, SessionStatus::Partial),
    ] {
        let mut read_set = Store::default().read_set();
        run(
            &mut read_set,
            &start_command(SESSION_A, "quick", &[], true),
            NOW,
        );
        if activity {
            run(
                &mut read_set,
                &progress_command(SESSION_A, 1, json!({"inbox_processed_delta": 1})),
                NOW,
            );
        }
        assert!(
            review_sessions::close_idle_sessions(&read_set, at("2026-10-16T11:59:59Z"))
                .expect("closed")
                .is_empty()
        );
        let closed = review_sessions::close_idle_sessions(&read_set, at("2026-10-16T12:00:00Z"))
            .expect("closed");
        assert_eq!(closed.len(), 1);
        assert_eq!(closed[0].status, status);
        assert_eq!(as_json(&closed[0].ended_at), json!("2026-10-16T12:00:00Z"));
    }
}

// ------------------------------------------------------------------- settings

fn settings_of(read_set: &ReadSet) -> Value {
    as_json(&read_set.settings.as_ref().expect("settings").public())
}

/// `test_020_FR_039_a_stale_expected_revision_is_409` and TR-005.
#[test]
fn review_sessions_026_fr_016_settings_check_their_revision() {
    let mut read_set = Store::default().read_set();
    run(
        &mut read_set,
        &settings_command(json!({"threshold_days": 21}), 1),
        NOW,
    );
    let stale = refusal(
        &read_set,
        &settings_command(json!({"threshold_days": 7}), 1),
        NOW,
    );
    assert_eq!(stale.reason, Reason::RevisionConflict);
    assert_eq!(
        stale.current_revision.as_ref().map(|c| c.to_u64()),
        Some(Some(2))
    );
    assert_eq!(settings_of(&read_set)["threshold_days"], json!(21));
    let unchecked = try_command(
        "review.settings",
        SCOPE,
        json!({"threshold_days": 7}),
        vec![],
    );
    let command = unchecked.expect("a typed command");
    let missing =
        review_sessions::decide(&read_set, &command, &exec(NOW)).expect_err("needs a revision");
    assert_eq!(missing.reason, Reason::InvalidPayload);
}

/// `test_020_FR_039_threshold_change_updates_markers_and_floors_parks_7_days`.
#[test]
fn review_sessions_026_fr_016_a_threshold_change_floors_parks_for_seven_days() {
    let mut store = Store::default();
    store.settings = Some(settings_row(Some("2026-09-01T08:00:00Z")));
    store.tasks = vec![next_task(1, 1, "2026-09-24T12:00:00Z")];
    let mut read_set = store.read_set();
    let before = review_state(&read_set, NOW);
    assert_eq!(before.counts.asks_for_decision, 1);
    let change = run(
        &mut read_set,
        &settings_command(json!({"threshold_days": 7}), 1),
        NOW,
    );
    assert_eq!(change.changes.len(), 1, "no task is written");
    let settings = settings_of(&read_set);
    assert_eq!(settings["threshold_days"], json!(7));
    assert_eq!(
        settings["owner_park_floor_at"],
        json!("2026-10-16T12:00:00Z")
    );
    assert_eq!(settings["revision"], json!("2"));
    let private = read_set
        .settings
        .as_ref()
        .and_then(|s| s.private.as_ref())
        .expect("private");
    assert_eq!(as_json(&private.threshold_changed_at), json!(NOW));
    // The marker moved at once: asking since 7 days after the start.
    let task = &read_set.tasks.values().next().expect("a task");
    let view = review_queue(&read_set, "rest_of_next", None, NOW);
    assert!(
        view.items.is_empty(),
        "the task asks, so it is not rest of Next"
    );
    assert_eq!(as_json(&task.revision), json!("1"));
}

/// `test_020_FR_046_a_time_zone_change_floors_due_dated_next_tasks_only`.
#[test]
fn review_sessions_026_fr_016_a_zone_change_floors_due_dated_next_tasks_without_a_revision() {
    let mut dated = next_task(1, 1, "2026-10-08T09:00:00Z");
    dated["due_date"] = json!("2026-10-20");
    let plain = next_task(2, 2, "2026-10-08T09:00:00Z");
    let mut store = Store::default();
    store.settings = Some(settings_row(Some("2026-09-01T08:00:00Z")));
    store.tasks = vec![
        dated,
        plain,
        with(
            task("task_w", "waiting", 3),
            "due_date",
            json!("2026-10-20"),
        ),
    ];
    let mut read_set = store.read_set();
    let change = run(
        &mut read_set,
        &settings_command(json!({"time_zone": "Asia/Tokyo"}), 1),
        NOW,
    );
    assert_eq!(
        change.changes.len(),
        2,
        "settings and the one due-dated Next task"
    );
    let floored = &read_set.tasks[&types::TaskId::parse("task_n001").expect("id")];
    assert_eq!(
        floored
            .formulation
            .as_ref()
            .and_then(|c| c.park_floor_at.as_ref())
            .map(|f| f.as_str()),
        Some("2026-10-16T12:00:00Z")
    );
    assert_eq!(as_json(&floored.revision), json!("1"));
    assert_eq!(as_json(&floored.updated_at), json!(CREATED));
    let unchanged = &read_set.tasks[&types::TaskId::parse("task_n002").expect("id")];
    assert!(
        unchanged
            .formulation
            .as_ref()
            .expect("a clock")
            .park_floor_at
            .is_none()
    );
}

/// `test_020_FR_035_values_equal_to_the_stored_ones_are_no_change` and
/// `..._onboarding_records_the_first_onboarded_instant`.
#[test]
fn review_sessions_026_fr_016_equal_values_are_no_change_and_onboarding_is_recorded_once() {
    let mut read_set = Store::default().read_set();
    run(
        &mut read_set,
        &settings_command(
            json!({"time_zone": "Europe/Berlin", "review_weekday": 5}),
            1,
        ),
        NOW,
    );
    assert_eq!(settings_of(&read_set)["revision"], json!("2"));
    // A due-dated Next task that appears after the zone was set.
    let mut dated = next_task(1, 1, "2026-10-08T09:00:00Z");
    dated["due_date"] = json!("2026-10-20");
    read_set.tasks.insert(
        types::TaskId::parse("task_n001").expect("an id"),
        serde_json::from_value(dated).expect("a task"),
    );

    let same = review_sessions::decide(
        &read_set,
        &settings_command(
            json!({"time_zone": "Europe/Berlin", "threshold_days": 14, "review_weekday": 5, "review_time": "16:00"}),
            2,
        ),
        &exec("2026-10-10T12:00:00Z"),
    )
    .expect("accepted");
    assert_eq!(same.outcome, ChangeOutcome::NoOp);
    assert!(settings_of(&read_set)["owner_park_floor_at"].is_null());
    assert!(read_set.tasks.values().all(|t| {
        t.formulation
            .as_ref()
            .is_none_or(|c| c.park_floor_at.is_none())
    }));

    run(
        &mut read_set,
        &settings_command(
            json!({"onboarded": true, "review_weekday": 1, "review_time": "09:30"}),
            2,
        ),
        NOW,
    );
    assert_eq!(settings_of(&read_set)["onboarded_at"], json!(NOW));
    let again = review_sessions::decide(
        &read_set,
        &settings_command(json!({"onboarded": true}), 3),
        &exec("2026-10-12T12:00:00Z"),
    )
    .expect("accepted");
    assert_eq!(again.outcome, ChangeOutcome::NoOp);
}

#[test]
fn review_sessions_026_fr_016_a_zone_that_is_not_iana_is_invalid_time_zone() {
    let read_set = Store::default().read_set();
    for command in [
        settings_command(json!({"time_zone": "Mars/Olympus"}), 1),
        command(
            "review.explainer_ack",
            SCOPE,
            json!({"time_zone": "Mars/Olympus"}),
            vec![],
        ),
    ] {
        let error = refusal(&read_set, &command, NOW);
        assert_eq!(
            (error.reason, error.field.as_deref()),
            (Reason::InvalidTimeZone, Some("time_zone"))
        );
    }
}

// ----------------------------------------------------------------- activation

/// FR-016/FR-051: the first acknowledgement activates the owner and clamps
/// every Next clock in the same change set; a later one changes nothing.
#[test]
fn review_sessions_026_fr_016_the_first_acknowledgement_activates_and_clamps_next_clocks() {
    let mut store = Store::default();
    let mut old = next_task(1, 1, "2026-08-01T09:00:00Z");
    old["consecutive_stalled_formulations"] = json!(1);
    let clockless = task("task_noclock", "next", 2);
    store.tasks = vec![old, clockless, task("task_inbox", "inbox", 3)];
    let mut read_set = store.read_set();
    let ack = command(
        "review.explainer_ack",
        SCOPE,
        json!({"time_zone": "Europe/Berlin"}),
        vec![],
    );

    let starved = review_sessions::decide(&read_set, &ack, &exec(NOW)).expect_err("needs an id");
    assert_eq!(starved.reason, Reason::FormulationIdRequired);

    let minted = form_id(0xaa);
    let inputs = exec_with(NOW, true, None, &[minted.as_str()]);
    let change_set = review_sessions::decide(&read_set, &ack, &inputs).expect("activated");
    apply(&mut read_set, &change_set);
    assert_eq!(
        change_set.changes.len(),
        3,
        "settings and the two Next tasks"
    );
    let settings = settings_of(&read_set);
    assert_eq!(settings["activated_at"], json!(NOW));
    assert_eq!(settings["time_zone"], json!("Europe/Berlin"));
    assert_eq!(settings["revision"], json!("2"));
    let sweep = read_set
        .settings
        .as_ref()
        .and_then(|s| s.private.as_ref())
        .map(|p| p.last_effective_sweep_at.clone());
    assert_eq!(as_json(&sweep), json!(NOW));

    let by_id = |id: &str| &read_set.tasks[&types::TaskId::parse(id).expect("id")];
    let clamped = by_id("task_n001").formulation.as_ref().expect("a clock");
    assert_eq!(
        clamped.started_at.as_str(),
        NOW,
        "an older clock restarts at activation"
    );
    assert_eq!(
        clamped.park_floor_at.as_ref().map(|f| f.as_str()),
        Some("2026-10-23T12:00:00Z")
    );
    let started = by_id("task_noclock")
        .formulation
        .as_ref()
        .expect("a started clock");
    assert_eq!(
        (started.id.as_str(), started.started_at.as_str()),
        (minted.as_str(), NOW)
    );
    assert_eq!(
        as_json(&by_id("task_n001").revision),
        json!("1"),
        "no task revision moves"
    );

    let later = command(
        "review.explainer_ack",
        SCOPE,
        json!({"time_zone": "America/New_York"}),
        vec![],
    );
    let noop = review_sessions::decide(&read_set, &later, &exec("2026-10-10T12:00:00Z"))
        .expect("accepted");
    assert_eq!(noop.outcome, ChangeOutcome::NoOp);
}

// -------------------------------------------------------------------- consent

fn grant_command(provider: &str, version: u32) -> DomainCommand {
    command(
        "review.consent_grant",
        provider,
        json!({"provider": provider, "consent_text_version": version}),
        vec![],
    )
}

fn revoke_command(provider: &str) -> DomainCommand {
    command(
        "review.consent_revoke",
        provider,
        json!({"provider": provider}),
        vec![],
    )
}

fn consent_of(read_set: &ReadSet, provider: &str) -> Value {
    as_json(
        read_set
            .consents
            .iter()
            .find(|consent| consent.provider.as_str() == provider)
            .expect("a consent row"),
    )
}

/// `NavigatorService.grant_consent` / `revoke_consent`.
#[test]
fn review_sessions_026_fr_016_consent_is_granted_for_the_configured_provider_and_text() {
    let mut read_set = Store::default().read_set();
    let unavailable = review_sessions::decide(
        &read_set,
        &grant_command(PROVIDER, 1),
        &exec_with(NOW, true, None, &[]),
    )
    .expect_err("no provider");
    assert_eq!(unavailable.reason, Reason::ProviderUnavailable);
    let mismatch = refusal(&read_set, &grant_command("anthropic", 1), NOW);
    assert_eq!(
        (mismatch.reason, mismatch.field.as_deref()),
        (Reason::ProviderUnavailable, Some("provider"))
    );
    let outdated = refusal(&read_set, &grant_command(PROVIDER, 2), NOW);
    assert_eq!(outdated.reason, Reason::ConsentTextOutdated);

    let granted = run(&mut read_set, &grant_command(PROVIDER, 1), NOW);
    assert_eq!(granted.outcome, ChangeOutcome::Applied);
    assert_eq!(
        consent_of(&read_set, PROVIDER),
        json!({"provider": PROVIDER, "consent": {"granted_at": NOW, "revoked_at": null, "consent_text_version": 1}})
    );
    let current = review_sessions::decide(
        &read_set,
        &grant_command(PROVIDER, 1),
        &exec("2026-10-10T12:00:00Z"),
    )
    .expect("accepted");
    assert_eq!(
        current.outcome,
        ChangeOutcome::NoOp,
        "a current grant is not rewritten"
    );
}

/// Revoke is owner-wide: the provider the payload names never narrows it, and
/// it is not gated by availability. A re-grant after a revoke starts a new grant.
#[test]
fn review_sessions_026_fr_016_consent_revoke_is_owner_wide_and_never_gated() {
    let store = Store {
        consents: vec![
            json!({"provider": PROVIDER, "consent": {"granted_at": "2026-10-01T10:00:00Z", "revoked_at": null, "consent_text_version": 1}}),
            json!({"provider": "other", "consent": {"granted_at": "2026-09-01T10:00:00Z", "revoked_at": null, "consent_text_version": 1}}),
            json!({"provider": "never", "consent": null}),
            json!({"provider": "old", "consent": {"granted_at": "2026-08-01T10:00:00Z", "revoked_at": "2026-08-02T10:00:00Z", "consent_text_version": 1}}),
        ],
        ..Store::default()
    };
    let mut read_set = store.read_set();
    // The provider is switched off and the payload names an unconfigured one.
    let inputs = exec_with(NOW, true, None, &[]);
    let change_set =
        review_sessions::decide(&read_set, &revoke_command("apple"), &inputs).expect("revoked");
    apply(&mut read_set, &change_set);
    assert_eq!(
        change_set.changes.len(),
        2,
        "the two live grants, nothing else"
    );
    assert_eq!(
        consent_of(&read_set, PROVIDER)["consent"]["revoked_at"],
        json!(NOW)
    );
    assert_eq!(
        consent_of(&read_set, "other")["consent"]["revoked_at"],
        json!(NOW)
    );
    assert_eq!(
        consent_of(&read_set, "old")["consent"]["revoked_at"],
        json!("2026-08-02T10:00:00Z")
    );
    assert!(consent_of(&read_set, "never")["consent"].is_null());

    let again =
        review_sessions::decide(&read_set, &revoke_command(PROVIDER), &inputs).expect("accepted");
    assert_eq!(again.outcome, ChangeOutcome::NoOp);

    run(
        &mut read_set,
        &grant_command(PROVIDER, 1),
        "2026-10-11T12:00:00Z",
    );
    assert_eq!(
        consent_of(&read_set, PROVIDER)["consent"],
        json!({"granted_at": "2026-10-11T12:00:00Z", "revoked_at": null, "consent_text_version": 1})
    );
}

// ------------------------------------------------------------------- the reads

#[test]
fn review_sessions_026_fr_016_the_reads_are_hidden_while_the_flag_is_off() {
    let read_set = Store::default().read_set();
    for query in [Query::ReviewState {}, queue_query("wins", None)] {
        let error = review_sessions::query(&read_set, &query, &query_inputs(NOW, false))
            .expect_err("hidden");
        assert_eq!(error.reason, Reason::ReviewUnavailable);
    }
    let unknown = review_sessions::query(
        &read_set,
        &queue_query("wins", Some(SESSION_A)),
        &query_inputs(NOW, true),
    )
    .expect_err("no such run");
    assert_eq!(unknown.reason, Reason::SessionNotFound);
    let task_query = Query::Tags {};
    assert!(!review_sessions::handles_query(&task_query));
    assert_eq!(
        review_sessions::query(&read_set, &task_query, &query_inputs(NOW, true))
            .expect_err("not ours")
            .field
            .as_deref(),
        Some("kind")
    );
}

/// `test_020_FR_004_state_counts_the_asks_for_decision_aggregate`,
/// `..._last_counted_review_uses_counted_reviews_only`, `..._restart_mode_...`,
/// `..._state_reports_activation_grace_receipts_and_server_now`.
#[test]
fn review_sessions_026_fr_016_the_state_derives_from_the_rows_and_the_clock() {
    let completed = {
        let mut row = session_row(
            "review_2b7d9f1c3e5a",
            "completed",
            "2026-09-30T15:20:00Z",
            "2026-09-30T15:39:00Z",
        );
        row["ended_at"] = json!("2026-09-30T15:40:00Z");
        row["qualifying_activity"] = json!(true);
        row["clear_start"] = json!("yes");
        row["counts"]["done"] = json!(3);
        row
    };
    let mut open = session_row(
        SESSION_A,
        "open",
        "2026-10-09T09:00:00Z",
        "2026-10-09T09:30:00Z",
    );
    open["qualifying_activity"] = json!(true);
    let empty = {
        let mut row = session_row(
            SESSION_B,
            "completed_empty",
            "2026-10-08T09:00:00Z",
            "2026-10-08T09:01:00Z",
        );
        row["ended_at"] = json!("2026-10-08T09:01:00Z");
        row
    };
    let parked = with(
        with(task("task_parked", "someday", 5), "revision", json!("3")),
        "parked",
        json!({"at": "2026-10-08T09:14:03Z", "formulation_id": form_id(0x70)}),
    );
    let seen = with(
        with(task("task_seen", "someday", 6), "revision", json!("3")),
        "parked",
        json!({"at": "2026-10-07T09:14:03Z", "formulation_id": form_id(0x71)}),
    );
    let mut store = Store::default();
    store.settings = Some(with(
        settings_row(Some("2026-09-05T08:00:00Z")),
        "onboarded_at",
        json!("2026-09-18T10:00:00Z"),
    ));
    store.settings.as_mut().expect("settings")["time_zone"] = json!("Europe/Berlin");
    store.tasks = vec![
        next_task(1, 1, "2026-09-24T12:00:00Z"),
        next_task(2, 2, "2026-09-24T12:00:00Z"),
        next_task(3, 3, "2026-09-19T00:00:00Z"),
        next_task(4, 4, "2026-10-08T12:00:00Z"),
        parked,
        seen,
        with(task("task_waiting", "waiting", 7), "revision", json!("4")),
        with(task("task_changed", "waiting", 8), "revision", json!("5")),
    ];
    store.sessions = vec![completed, open, empty];
    store.park_acks = vec![json!({
        "task_id": "task_seen", "formulation_id": form_id(0x71),
        "parked_at": "2026-10-07T09:14:03Z", "seen_at": "2026-10-07T20:00:00Z", "returned_at": null,
    })];
    store.receipts = vec![
        receipt_row("task_waiting", "waiting", 4, "2026-10-12T10:00:00Z"),
        receipt_row("task_changed", "waiting", 4, "2026-10-12T10:00:00Z"),
        receipt_row("task_waiting", "someday", 4, "2026-10-09T11:00:00Z"),
    ];
    let state = review_state(&store.read_set(), NOW);
    let body = to_http(&as_json(&state));

    assert_eq!(body["explainer_seen"], json!(true));
    assert_eq!(body["grace_until"], json!("2026-09-19T08:00:00Z"));
    assert_eq!(
        body["counts"],
        json!({"asks_for_decision": 3, "moves_tomorrow": 1})
    );
    assert_eq!(body["server_now"], json!(NOW));
    // The counted instants: the completed run's end and the open run's activity.
    assert_eq!(
        body["last_counted_review_at"],
        json!("2026-10-09T09:30:00Z")
    );
    assert_eq!(
        body["last_counted_review"]["session_id"],
        json!("review_2b7d9f1c3e5a")
    );
    assert_eq!(body["last_counted_review"]["status"], json!("completed"));
    assert_eq!(body["last_counted_review"]["clear_start"], json!("yes"));
    assert_eq!(body["last_counted_review"]["counts"]["done"], json!(3));
    assert_eq!(body["open_session"]["id"], json!(SESSION_A));
    assert!(body["open_session"].get("private").is_none());
    assert_eq!(body["restart_mode"], json!(false));
    // Friday 16:00 Berlin today; the counted review of this morning is within 6 days: next week.
    assert_eq!(body["next_review_at"], json!("2026-10-16T14:00:00Z"));
    assert_eq!(
        body["unseen_parks"],
        json!([{"task_id": "task_parked", "formulation_id": form_id(0x70), "parked_at": "2026-10-08T09:14:03Z"}])
    );
    assert_eq!(
        body["receipts"],
        json!([{"task_id": "task_waiting", "kind": "waiting", "hidden_until": "2026-10-12T10:00:00Z", "task_revision": 4}]),
        "an expired receipt and a receipt of a changed task are not listed"
    );
}

#[test]
fn review_sessions_026_fr_016_restart_mode_and_the_last_review_count_only_counted_runs() {
    let mut store = Store::default();
    store.settings = Some(with(
        settings_row(Some("2026-08-01T08:00:00Z")),
        "onboarded_at",
        json!("2026-09-01T10:00:00Z"),
    ));
    let mut abandoned = session_row(
        SESSION_B,
        "abandoned",
        "2026-10-08T09:00:00Z",
        "2026-10-08T10:00:00Z",
    );
    abandoned["qualifying_activity"] = json!(false);
    store.sessions = vec![abandoned];
    let state = review_state(&store.read_set(), NOW);
    assert!(
        state.restart_mode,
        "21 days from onboarding with no counted review"
    );
    assert!(state.last_counted_review.is_none() && state.last_counted_review_at.is_none());

    let mut partial = session_row(
        SESSION_A,
        "partial",
        "2026-10-02T09:00:00Z",
        "2026-10-02T10:00:00Z",
    );
    partial["qualifying_activity"] = json!(true);
    store.sessions.push(partial);
    let state = review_state(&store.read_set(), NOW);
    assert!(!state.restart_mode);
    let last = state
        .last_counted_review
        .expect("a partial run is the last review");
    assert_eq!(
        (last.session_id.as_str(), last.status),
        (SESSION_A, types::CountedStatus::Partial)
    );
}

fn queue_store() -> Store {
    let mut store = Store::default();
    store.settings = Some(settings_row(Some("2026-09-01T08:00:00Z")));
    store
}

/// `test_020_FR_028_wins_are_the_tasks_completed_in_the_last_seven_days` and
/// `..._inbox_and_steps_without_a_queue`.
#[test]
fn review_sessions_026_fr_002_wins_inbox_and_the_steps_without_a_queue() {
    let mut store = queue_store();
    store.tasks = vec![
        with(
            task("task_won", "completed", 1),
            "completed_at",
            json!("2026-10-07T10:00:00Z"),
        ),
        with(
            task("task_older", "completed", 2),
            "completed_at",
            json!("2026-09-20T10:00:00Z"),
        ),
        task("task_i2", "inbox", 4),
        task("task_i1", "inbox", 3),
    ];
    let read_set = store.read_set();
    let wins = review_queue(&read_set, "wins", None, NOW);
    assert_eq!(
        (item_ids(&wins), as_json(&wins.meta)),
        (vec!["task_won".to_owned()], json!({"count": 1}))
    );
    let inbox = review_queue(&read_set, "inbox", None, NOW);
    assert_eq!(
        (item_ids(&inbox), as_json(&inbox.meta)),
        (vec!["task_i1".to_owned(), "task_i2".to_owned()], json!({}))
    );
    for step in ["mind_sweep", "summary"] {
        let none = review_queue(&read_set, step, None, NOW);
        assert!(
            none.items.is_empty() && matches!(none.meta, QueueMeta::Empty(_)),
            "{step}"
        );
    }
}

/// `test_020_FR_048_020_FR_050_the_decision_queue_names_the_cards_already_handled`.
#[test]
fn review_sessions_026_fr_016_the_decisions_step_names_the_cards_already_handled() {
    let started = "2026-09-24T12:00:00Z";
    let mut store = queue_store();
    store.tasks = (1..=4)
        .map(|n| next_task(n, u64::from(n), started))
        .collect();
    store.sessions = vec![session_row(SESSION_A, "open", NOW, NOW)];
    store.queues = vec![queue_row(
        SESSION_A,
        json!([
            "task_n003",
            "task_n001",
            "task_n002",
            "task_n004",
            "task_gone"
        ]),
        &["task_n001", "task_n002", "task_n009"],
    )];
    store.decisions = vec![decision_row(
        "decision_0b0e1f30-0000-4000-8000-000000000001",
        "task_n002",
        SESSION_A,
    )];
    let read_set = store.read_set();
    let queue = review_queue(&read_set, "decisions", Some(SESSION_A), NOW);
    assert_eq!(
        item_ids(&queue),
        ["task_n003", "task_n001", "task_n002", "task_n004"]
    );
    assert_eq!(
        as_json(&queue.meta),
        json!({"decided_task_ids": ["task_n002"], "set_aside_task_ids": ["task_n001"]}),
        "decided wins over set aside; both follow the queue's order and name only listed cards"
    );
    let live = review_queue(&read_set, "decisions", None, NOW);
    assert_eq!(
        as_json(&live.meta),
        json!({"decided_task_ids": [], "set_aside_task_ids": []})
    );
    let rest = review_queue(&read_set, "rest_of_next", Some(SESSION_A), NOW);
    assert!(
        rest.items.is_empty(),
        "every Next task is in the captured queue"
    );
}

/// `test_020_FR_028_rest_of_next_lists_next_tasks_that_do_not_ask`,
/// `..._waiting_older_than_seven_days_...`, `..._someday_pass_...`,
/// `..._projects_without_a_next_action`, `..._dates_in_the_next_fourteen_days_...`.
#[test]
fn review_sessions_026_fr_002_the_remaining_queues_follow_the_server() {
    let mut store = queue_store();
    let mut dated_late = task("task_d2", "waiting", 12);
    dated_late["due_date"] = json!("2026-10-22");
    let mut dated_first = task("task_d1", "next", 11);
    dated_first["due_date"] = json!("2026-10-09");
    let mut dated_same = task("task_d0", "inbox", 10);
    dated_same["due_date"] = json!("2026-10-09");
    let mut out_of_window = task("task_d3", "next", 13);
    out_of_window["due_date"] = json!("2026-10-23");
    let mut closed = with(
        task("task_d4", "completed", 14),
        "completed_at",
        json!("2026-10-01T09:00:00Z"),
    );
    closed["due_date"] = json!("2026-10-10");
    store.projects = vec![
        project("project_stuck", "b stuck", "active"),
        project("project_fine", "a fine", "active"),
        project("project_empty", "c empty", "active"),
        project("project_old", "d old", "archived"),
    ];
    store.tasks = vec![
        next_task(1, 1, "2026-10-08T12:00:00Z"),
        with(
            next_task(2, 2, "2026-10-08T12:00:00Z"),
            "project_id",
            json!("project_fine"),
        ),
        with(
            task("task_s1", "inbox", 21),
            "project_id",
            json!("project_stuck"),
        ),
        with(
            task("task_s2", "someday", 20),
            "project_id",
            json!("project_stuck"),
        ),
        with(
            with(
                task("task_old", "waiting", 3),
                "waiting_since",
                json!("2026-09-20T10:00:00Z"),
            ),
            "revision",
            json!("1"),
        ),
        with(
            task("task_new", "waiting", 4),
            "waiting_since",
            json!("2026-10-08T10:00:00Z"),
        ),
        task("task_sd1", "someday", 5),
        dated_late,
        dated_first,
        dated_same,
        out_of_window,
        closed,
    ];
    let read_set = store.read_set();

    let rest = review_queue(&read_set, "rest_of_next", None, NOW);
    assert_eq!(
        item_ids(&rest),
        ["task_n001", "task_n002", "task_d1", "task_d3"]
    );
    assert_eq!(as_json(&rest.meta)["next_count"], json!(4));
    assert_eq!(as_json(&rest.meta)["weeks_of_history"], json!(1));
    assert!(as_json(&rest.meta)["weekly_average_4w"].is_null());

    assert_eq!(
        item_ids(&review_queue(&read_set, "waiting", None, NOW)),
        ["task_old"]
    );
    let someday = review_queue(&read_set, "someday", None, NOW);
    // Equal `updated_at`: by ID.
    assert_eq!(item_ids(&someday), ["task_s2", "task_sd1"]);
    assert_eq!(
        as_json(&someday.meta),
        json!({"eligible_total": 2, "shown": 2})
    );
    // `project_stuck` and `project_empty` have no Next task; the archived one is out.
    assert_eq!(
        item_ids(&review_queue(&read_set, "projects", None, NOW)),
        ["task_s2", "task_s1"]
    );

    let dates = review_queue(&read_set, "dates", None, NOW);
    assert_eq!(item_ids(&dates), ["task_d0", "task_d1", "task_d2"]);
    assert_eq!(
        as_json(&dates.meta),
        json!({"days": [
            {"day": "2026-10-09", "task_ids": ["task_d0", "task_d1"]},
            {"day": "2026-10-22", "task_ids": ["task_d2"]},
        ]})
    );
    let queue = review_queue(&read_set, "dates", None, "2026-10-09T23:30:00Z");
    assert_eq!(queue.items.len(), 3, "the day is the stored zone's");
}

/// The Someday pass shows at most seven.
#[test]
fn review_sessions_026_fr_002_the_someday_pass_shows_seven() {
    let mut store = queue_store();
    store.tasks = (0..9)
        .map(|n| {
            with(
                task(&format!("task_s{n}"), "someday", n),
                "updated_at",
                json!(format!("2026-08-0{}T10:00:00Z", n + 1)),
            )
        })
        .collect();
    let queue = review_queue(&store.read_set(), "someday", None, NOW);
    assert_eq!(queue.items.len(), 7);
    assert_eq!(
        as_json(&queue.meta),
        json!({"eligible_total": 9, "shown": 7})
    );
}

// ----------------------------------------------------------------------- traces

/// The in-memory server the traces run against: every request is routed to
/// `decide` or `query`, as the adapter routes it, and the Idempotency-Key
/// record of the adapter is kept for 24 hours.
struct Server {
    read_set: ReadSet,
    now: UtcInstant,
    weekly_review: bool,
    keys: HashMap<String, (UtcInstant, u16, Value)>,
    routed: usize,
}

impl Server {
    fn new(start: &str) -> Self {
        Self {
            read_set: Store::default().read_set(),
            now: at(start),
            weekly_review: true,
            keys: HashMap::new(),
            routed: 0,
        }
    }

    fn now(&self) -> String {
        self.now.to_rfc3339()
    }

    fn session_body(&self, id: &str) -> Value {
        to_http(&as_json(&session_of(&self.read_set, id).public()))
    }

    fn state_body(&self) -> Value {
        let state = review_sessions::query(
            &self.read_set,
            &Query::ReviewState {},
            &query_inputs(&self.now(), true),
        )
        .expect("state");
        let QueryResult::ReviewState(state) = state else {
            panic!("a state")
        };
        to_http(&as_json(&*state))
    }

    fn settings_body(&self) -> Value {
        let settings = self.read_set.settings.as_ref().expect("settings").public();
        to_http(&as_json(&settings))
    }

    fn error(error: &DomainError) -> (u16, Value) {
        match (error.reason, error.field.as_deref()) {
            (Reason::IdAlreadyExists, Some("replace_open")) => {
                let session = error.entity.as_ref().map(|(_, key)| key[0].clone());
                (
                    409,
                    json!({"detail": {"reason": "open_session_exists", "session_id": session}}),
                )
            }
            (Reason::IdAlreadyExists, _) => (409, json!({"detail": {"reason": "id_conflict"}})),
            (Reason::RevisionConflict, _) => {
                (409, json!({"detail": {"resource": "Review settings"}}))
            }
            (Reason::ReviewUnavailable, _) => (
                404,
                json!({"message": "Not found", "detail": {"reason": "weekly_review_disabled"}}),
            ),
            (Reason::SessionNotFound, _) => (404, json!({"detail": {"reason": "not_found"}})),
            (reason, _) => (400, json!({"detail": {"reason": reason.as_str()}})),
        }
    }

    fn execute(&mut self, command: &DomainCommand) -> Result<(), (u16, Value)> {
        let inputs = exec_with(&self.now(), true, Some(PROVIDER), &[]);
        let change_set = review_sessions::decide(&self.read_set, command, &inputs)
            .map_err(|e| Self::error(&e))?;
        apply(&mut self.read_set, &change_set);
        Ok(())
    }

    /// `None` for a request of another family.
    fn request(
        &mut self,
        method: &str,
        path: &str,
        key: Option<&str>,
        body: &Value,
    ) -> Option<(u16, Value)> {
        let route = path.strip_prefix("/api/review/")?;
        let parts: Vec<&str> = route.split('/').collect();
        let own = matches!(
            (method, parts.as_slice()),
            ("POST", ["sessions"])
                | ("GET" | "PATCH", ["sessions", _])
                | ("POST", ["sessions", _, "finish"])
                | ("GET", ["state"])
                | ("PUT", ["settings"])
                | ("POST", ["explainer", "acknowledge"])
        );
        if !own {
            return None;
        }
        self.routed += 1;
        if let Some(key) = key
            && let Some((created, status, stored)) = self.keys.get(key)
            && self.now.micros_since(*created) < 24 * 3_600 * 1_000_000
        {
            return Some((*status, stored.clone()));
        }
        let answer = self
            .dispatch(method, &parts, body)
            .unwrap_or_else(|failure| failure);
        if let (Some(key), true) = (key, answer.0 < 300) {
            self.keys
                .insert(key.to_owned(), (self.now, answer.0, answer.1.clone()));
        }
        Some(answer)
    }

    fn dispatch(
        &mut self,
        method: &str,
        parts: &[&str],
        body: &Value,
    ) -> Result<(u16, Value), (u16, Value)> {
        match (method, parts) {
            ("POST", ["sessions"]) => {
                let id = text(body, "id");
                let mut payload = body.clone();
                payload.as_object_mut().expect("an object").remove("id");
                self.execute(&command("review.session_start", id, payload, vec![]))?;
                Ok((201, self.session_body(id)))
            }
            ("GET", ["sessions", id]) => {
                if !self
                    .read_set
                    .sessions
                    .keys()
                    .any(|session| session.as_str() == *id)
                {
                    return Err((404, json!({"detail": {"reason": "not_found"}})));
                }
                Ok((200, self.session_body(id)))
            }
            ("PATCH", ["sessions", id]) => {
                self.execute(&command(
                    "review.session_progress",
                    id,
                    body.clone(),
                    vec![],
                ))?;
                Ok((200, self.session_body(id)))
            }
            ("POST", ["sessions", id, "finish"]) => {
                self.execute(&command("review.session_finish", id, body.clone(), vec![]))?;
                Ok((200, self.session_body(id)))
            }
            ("GET", ["state"]) => {
                let result = review_sessions::query(
                    &self.read_set,
                    &Query::ReviewState {},
                    &query_inputs(&self.now(), self.weekly_review),
                )
                .map_err(|e| Self::error(&e))?;
                let QueryResult::ReviewState(state) = result else {
                    panic!("a state")
                };
                Ok((200, to_http(&as_json(&*state))))
            }
            ("PUT", ["settings"]) => {
                let mut payload = body.clone();
                let revision = payload
                    .as_object_mut()
                    .and_then(|members| members.remove("expected_revision"))
                    .and_then(|value| value.as_u64())
                    .expect("an expected revision");
                self.execute(&settings_command(payload, revision))?;
                Ok((200, self.settings_body()))
            }
            ("POST", ["explainer", "acknowledge"]) => {
                let allocated = [form_id(0x900)];
                let inputs = exec_with(&self.now(), true, Some(PROVIDER), &[allocated[0].as_str()]);
                let ack = command("review.explainer_ack", SCOPE, body.clone(), vec![]);
                let change_set = review_sessions::decide(&self.read_set, &ack, &inputs)
                    .map_err(|e| Self::error(&e))?;
                apply(&mut self.read_set, &change_set);
                Ok((200, self.state_body()))
            }
            other => panic!("unrouted {other:?}"),
        }
    }
}

/// The trace conventions: `body` is a subset match, a list matches element-wise
/// with equal length, `$present` matches any non-null value.
fn subset(expected: &Value, actual: &Value, path: &str) {
    match (expected, actual) {
        (Value::String(marker), actual) if marker == "$present" => {
            assert!(!actual.is_null(), "{path}: expected a value");
        }
        (Value::Object(want), Value::Object(have)) => {
            for (key, value) in want {
                let found = have
                    .get(key)
                    .unwrap_or_else(|| panic!("{path}.{key} is missing in {actual}"));
                subset(value, found, &format!("{path}.{key}"));
            }
        }
        (Value::Array(want), Value::Array(have)) => {
            assert_eq!(want.len(), have.len(), "{path}: length");
            for (index, (want, have)) in want.iter().zip(have).enumerate() {
                subset(want, have, &format!("{path}[{index}]"));
            }
        }
        (want, have) => assert_eq!(want, have, "{path}"),
    }
}

/// Replays the steps of a trace this family routes; returns how many requests
/// were checked.
fn replay(trace: &Value) -> usize {
    let id = text(trace, "id");
    let mut server = Server::new(text(trace, "start"));
    let mut checked = 0;
    for step in trace["steps"].as_array().expect("steps") {
        let name = text(step, "name");
        if let Some(advance) = step.get("advance") {
            let seconds = advance["days"].as_i64().unwrap_or(0) * 86_400
                + advance["hours"].as_i64().unwrap_or(0) * 3_600
                + advance["minutes"].as_i64().unwrap_or(0) * 60;
            server.now = server.now.plus_seconds(seconds);
        } else if let Some(flag) = step.get("flag") {
            server.weekly_review = flag.as_str() == Some("on");
        } else if let Some(request) = step.get("request") {
            let body = request.get("body").cloned().unwrap_or(Value::Null);
            let Some((status, answer)) = server.request(
                text(request, "method"),
                text(request, "path"),
                request.get("key").and_then(Value::as_str),
                &body,
            ) else {
                continue;
            };
            let expect = &step["expect"];
            assert_eq!(
                i64::from(status),
                int_of(expect, "status"),
                "{id}: {name}: {answer}"
            );
            if let Some(expected) = expect.get("body") {
                subset(expected, &answer, &format!("{id}: {name}"));
            }
            checked += 1;
        }
    }
    assert!(server.routed >= checked, "{id}");
    checked
}

fn int_of(value: &Value, key: &str) -> i64 {
    support::int(value, key)
}

fn trace<'a>(file: &'a Value, id: &str) -> &'a Value {
    cases(file, "traces")
        .iter()
        .find(|trace| text(trace, "id") == id)
        .unwrap_or_else(|| panic!("no trace {id}"))
}

fn load(relative: &str) -> Value {
    let path = support::repo_root().join(relative);
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("{}: {e}", path.display()))
}

fn runs_file() -> &'static Value {
    static CELL: std::sync::OnceLock<Value> = std::sync::OnceLock::new();
    CELL.get_or_init(|| load("backend/tests/fixtures/review_traces_runs.json"))
}

fn tasks_file() -> &'static Value {
    static CELL: std::sync::OnceLock<Value> = std::sync::OnceLock::new();
    CELL.get_or_init(|| load("backend/tests/fixtures/review_traces_tasks.json"))
}

fn wire_file() -> &'static Value {
    static CELL: std::sync::OnceLock<Value> = std::sync::OnceLock::new();
    CELL.get_or_init(|| load("backend/tests/fixtures/review_wire_fixtures.json"))
}

#[test]
fn review_sessions_026_fr_016_every_run_trace_replays_on_the_domain() {
    let mut checked = BTreeMap::new();
    for id in ["TR-R01", "TR-R02", "TR-R03", "TR-R04", "TR-R05"] {
        checked.insert(id, replay(trace(runs_file(), id)));
    }
    // Requests checked per trace: start/read, replace, merge, retention retry, finish.
    assert_eq!(
        checked,
        BTreeMap::from([
            ("TR-R01", 4),
            ("TR-R02", 6),
            ("TR-R03", 5),
            ("TR-R04", 5),
            ("TR-R05", 7),
        ])
    );
}

#[test]
fn review_sessions_026_fr_016_settings_and_activation_traces_replay_on_the_domain() {
    // TR-005 settings on two devices; TR-006 flag off (reads hidden, settings
    // accepted); TR-001 explainer acknowledgement with the device zone.
    let mut checked = BTreeMap::new();
    for id in ["TR-005", "TR-006", "TR-001"] {
        checked.insert(id, replay(trace(tasks_file(), id)));
    }
    assert_eq!(
        checked,
        BTreeMap::from([("TR-001", 1), ("TR-005", 2), ("TR-006", 3)])
    );
}

/// The domain refuses what the traces' adapters map to 409: a run that is
/// open elsewhere is named, never silently replaced.
#[test]
fn review_sessions_026_fr_016_a_session_command_of_another_family_is_refused() {
    let read_set = Store::default().read_set();
    let other = command(
        "task.create",
        "task_0b0e1f30-0000-4000-8000-000000000001",
        json!({"title": "A task"}),
        vec![],
    );
    assert!(!review_sessions::handles(&other.command));
    let error = review_sessions::decide(&read_set, &other, &exec(NOW)).expect_err("not ours");
    assert_eq!(
        (error.reason, error.field.as_deref()),
        (Reason::InvalidPayload, Some("type"))
    );
}

#[test]
fn review_sessions_026_sc_001_a_session_round_trips_through_the_record_form() {
    // The after-image a client replicates has no private member.
    let mut read_set = Store::default().read_set();
    let change_set = run(
        &mut read_set,
        &start_command(SESSION_A, "quick", &[], true),
        NOW,
    );
    let DomainChange::Upsert(record) = &change_set.changes[0] else {
        panic!("an upsert")
    };
    let public = as_json(&record.public());
    assert!(public["value"].get("private").is_none());
    assert_eq!(record.record_key(), vec![SESSION_A.to_owned()]);
    let _ = (ReviewMode::Quick, TaskState::Next);
}
