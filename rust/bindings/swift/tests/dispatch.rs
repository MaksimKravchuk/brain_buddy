//! The rule dispatch through the Apple bridge's public API (spec 026, T017): typed
//! conversion of read sets, envelopes and results, domain refusals as values, bridge
//! failures as content-free typed errors, and the runtime's lifecycle and sharing
//! rules. The rules themselves are held by the `bb-domain` parity suites; these tests
//! are about the boundary (runtime-ffi.md "Binding tests focus on type conversion,
//! decimal-counter precision, nullable/omitted edits, error transport and handle
//! lifetimes").

use std::sync::Arc;

use bb_swift::{BridgeAnswer, BridgeDecision, BridgeError, BridgeRefusal, BridgeRuntime};
use serde_json::{Value, json};

const TASK: &str = "task_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d12";
const OTHER_TASK: &str = "task_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d13";
const PROJECT: &str = "project_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d14";
const TAG: &str = "tag_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d15";
const NOW: &str = "2026-10-09T12:00:00Z";

fn runtime() -> BridgeRuntime {
    BridgeRuntime::new(bb_swift::bridge_protocol_version()).expect("opens")
}

fn bytes(value: &Value) -> Vec<u8> {
    serde_json::to_vec(value).expect("json")
}

fn inputs() -> Vec<u8> {
    bytes(&json!({
        "rule_version": 1, "now": NOW, "time_zone": "UTC", "origin": "device",
        "actor_id": "device", "authoritative": false,
        "allocated_ids": ["form_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d20"],
        "policy": {"weekly_review": false, "navigator_provider": null,
                   "navigator_available": false, "consent_text_version": 1}
    }))
}

fn query_inputs() -> Vec<u8> {
    bytes(&json!({
        "now": NOW, "device_zone": "UTC",
        "policy": {"weekly_review": false, "navigator_provider": null,
                   "navigator_available": false, "consent_text_version": 1}
    }))
}

fn envelope(kind: &str, entity: &str, payload: &Value, preconditions: &Value) -> Vec<u8> {
    bytes(&json!({
        "protocol_version": 1, "command_id": "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11",
        "scope_id": "local", "device_id": "device", "device_epoch": "epoch",
        "local_sequence": "1", "type": kind, "command_version": 1, "entity_id": entity,
        "preconditions": preconditions, "depends_on": [], "issued_at": NOW,
        "payload": payload
    }))
}

fn task(id: &str, state: &str, revision: &str, order_key: &str) -> Value {
    json!({
        "id": id, "title": "Buy milk", "details": null, "state": state,
        "project_id": null, "tag_ids": [], "due_date": null, "priority": "none",
        "waiting_for": null, "waiting_since": null, "order_key": order_key,
        "source_capture_ids": [], "created_at": NOW, "updated_at": NOW,
        "completed_at": null, "cancelled_at": null, "revision": revision,
        "consecutive_stalled_formulations": 0, "formulation": null, "parked": null
    })
}

fn project(id: &str, name: &str) -> Value {
    json!({
        "id": id, "name": name, "color": null, "state": "active", "revision": "1",
        "desired_outcome": null, "archived_at": null, "archived_before_lossless": false,
        "created_at": NOW
    })
}

fn read_set(tasks: &[Value]) -> Vec<u8> {
    let tasks: serde_json::Map<String, Value> = tasks
        .iter()
        .map(|task| (task["id"].as_str().expect("id").to_owned(), task.clone()))
        .collect();
    bytes(&json!({ "tasks": tasks }))
}

fn changed(decision: BridgeDecision) -> Value {
    match decision {
        BridgeDecision::Changed { change_set } => {
            serde_json::from_slice(&change_set).expect("json")
        }
        BridgeDecision::Refused { refusal } => panic!("refused: {refusal:?}"),
    }
}

fn refused(decision: BridgeDecision) -> BridgeRefusal {
    match decision {
        BridgeDecision::Refused { refusal } => refusal,
        BridgeDecision::Changed { .. } => panic!("expected a refusal"),
    }
}

fn answered(answer: BridgeAnswer) -> Value {
    match answer {
        BridgeAnswer::Answered { result } => serde_json::from_slice(&result).expect("json"),
        BridgeAnswer::Refused { refusal } => panic!("refused: {refusal:?}"),
    }
}

fn failure(error: BridgeError) -> (String, bool, Option<String>) {
    let BridgeError::Failed {
        code,
        retryable,
        field,
    } = error;
    (code, retryable, field)
}

fn create_task(runtime: &BridgeRuntime, entity: &str) -> Result<BridgeDecision, BridgeError> {
    runtime.decide(
        read_set(&[]),
        envelope(
            "task.create",
            entity,
            &json!({"title": "Buy milk"}),
            &json!([]),
        ),
        bytes(&json!([])),
        inputs(),
    )
}

#[test]
fn dispatch_026_fr_002_decides_a_command_into_an_owned_change_set() {
    let out = changed(create_task(&runtime(), TASK).expect("decides"));
    assert_eq!(out["outcome"], "applied");
    let record = &out["changes"][0];
    assert_eq!(record["operation"], "upsert");
    assert_eq!(record["entity_type"], "task");
    assert_eq!(record["value"]["id"], TASK);
    assert_eq!(record["value"]["state"], "inbox");
    assert_eq!(record["value"]["revision"], "1");
}

#[test]
fn dispatch_026_fr_002_reports_a_domain_refusal_as_a_value_with_its_record() {
    let runtime = runtime();
    // A bare UUID is not a native new ID: the rule refuses, the bridge does not fail.
    let refusal =
        refused(create_task(&runtime, "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d12").expect("a value"));
    assert_eq!(refusal.reason, "invalid_value");
    assert_eq!(refusal.field.as_deref(), Some("TaskId"));
    assert!(runtime.is_open());

    let stale = runtime
        .decide(
            read_set(&[task(TASK, "next", "4", "0")]),
            envelope(
                "task.update",
                TASK,
                &json!({"title": "Buy oat milk"}),
                &json!([{"entity_type": "task", "entity_id": TASK, "edit_revision": "3"}]),
            ),
            bytes(&json!([])),
            inputs(),
        )
        .expect("a value");
    assert_eq!(
        refused(stale),
        BridgeRefusal {
            reason: "revision_conflict".to_owned(),
            field: None,
            entity_type: Some("task".to_owned()),
            entity_key: vec![TASK.to_owned()],
            current_revision: Some("4".to_owned()),
        }
    );
}

#[test]
fn dispatch_026_fr_002_keeps_decimal_counters_exact_and_omitted_edits_omitted() {
    let runtime = runtime();
    let huge = "9007199254740993";
    let out = changed(
        runtime
            .decide(
                read_set(&[task(TASK, "inbox", huge, "9007199254740993")]),
                envelope(
                    "task.update",
                    TASK,
                    // `details` is omitted (unchanged); `due_date` is null (clear).
                    &json!({"title": "Buy oat milk", "due_date": null}),
                    &json!([{"entity_type": "task", "entity_id": TASK, "edit_revision": huge}]),
                ),
                bytes(&json!([])),
                inputs(),
            )
            .expect("decides"),
    );
    let value = &out["changes"][0]["value"];
    assert_eq!(value["revision"], "9007199254740994");
    assert_eq!(value["order_key"], "9007199254740993");
    assert_eq!(value["title"], "Buy oat milk");
}

#[test]
fn dispatch_026_fr_009_orders_a_new_task_after_the_last_of_its_list() {
    let out = changed(
        runtime()
            .decide(
                read_set(&[task(OTHER_TASK, "inbox", "1", "6")]),
                envelope("task.create", TASK, &json!({"title": "Second"}), &json!([])),
                bytes(&json!([])),
                inputs(),
            )
            .expect("decides"),
    );
    assert_eq!(out["changes"][0]["value"]["order_key"], "7");
}

#[test]
fn dispatch_026_fr_016_starts_a_formulation_from_the_allocated_id_in_next() {
    let out = changed(
        runtime()
            .decide(
                read_set(&[]),
                envelope(
                    "task.create",
                    TASK,
                    &json!({"title": "Call Sam", "state": "next"}),
                    &json!([]),
                ),
                bytes(&json!([])),
                inputs(),
            )
            .expect("decides"),
    );
    let clock = &out["changes"][0]["value"]["formulation"];
    assert_eq!(clock["id"], "form_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d20");
    assert_eq!(clock["started_at"], NOW);
}

#[test]
fn dispatch_026_fr_002_maps_bad_inputs_to_typed_errors_without_content() {
    let runtime = runtime();
    let good = envelope(
        "task.create",
        TASK,
        &json!({"title": "Buy milk"}),
        &json!([]),
    );
    let cases = [
        (
            runtime.decide(
                b"{\"tasks\": 7}".to_vec(),
                good.clone(),
                bytes(&json!([])),
                inputs(),
            ),
            ("INVALID_REQUEST", Some("read_set")),
        ),
        (
            runtime.decide(read_set(&[]), good.clone(), b"{".to_vec(), inputs()),
            ("INVALID_REQUEST", Some("receipts")),
        ),
        (
            runtime.decide(
                read_set(&[]),
                good.clone(),
                bytes(&json!([])),
                b"{}".to_vec(),
            ),
            ("INVALID_REQUEST", Some("execution_inputs")),
        ),
        (
            runtime.decide(read_set(&[]), vec![0xff, 0xfe], bytes(&json!([])), inputs()),
            ("INVALID_REQUEST", None),
        ),
        (
            runtime.decide(
                read_set(&[]),
                envelope("task.from_the_future", TASK, &json!({}), &json!([])),
                bytes(&json!([])),
                inputs(),
            ),
            ("UPGRADE_REQUIRED", Some("command_type")),
        ),
        (
            runtime
                .query(
                    read_set(&[]),
                    b"{\"kind\": \"nope\"}".to_vec(),
                    query_inputs(),
                )
                .map(|_| BridgeDecision::Changed {
                    change_set: Vec::new(),
                }),
            ("INVALID_REQUEST", Some("query")),
        ),
    ];
    for (outcome, (code, field)) in cases {
        let (got_code, retryable, got_field) = failure(outcome.expect_err("rejected"));
        assert_eq!((got_code.as_str(), got_field.as_deref()), (code, field));
        assert!(!retryable);
    }
    // A failed call leaves the runtime usable.
    assert!(runtime.is_open());
    assert!(create_task(&runtime, TASK).is_ok());
}

#[test]
fn dispatch_026_fr_002_refusals_carry_no_payload_text() {
    let secret = "SECRET-VALUE-9f2c";
    let runtime = runtime();
    let payloads = [
        json!({"title": "ok", "priority": secret}),
        json!({"title": "ok", (secret): 1}),
        json!({"title": "x".repeat(501), "details": secret}),
    ];
    for payload in payloads {
        let decision = runtime
            .decide(
                read_set(&[]),
                envelope("task.create", TASK, &payload, &json!([])),
                bytes(&json!([])),
                inputs(),
            )
            .expect("a value");
        let refusal = refused(decision);
        assert!(!format!("{refusal:?}").contains(secret), "{refusal:?}");
    }
}

#[test]
fn dispatch_026_sc_001_answers_each_query_kind_over_an_owned_read_set() {
    let runtime = runtime();
    let read = bytes(&json!({
        "tasks": { TASK: task(TASK, "next", "2", "0") },
        "projects": { PROJECT: project(PROJECT, "Home") },
    }));
    let ask = |query: Value| runtime.query(read.clone(), bytes(&query), query_inputs());

    let counts = answered(ask(json!({"kind": "list_counts"})).expect("answers"));
    assert_eq!(counts["kind"], "list_counts");
    assert_eq!(counts["value"]["next"], 1);

    let list = answered(
        ask(
            json!({"kind": "task_list", "list": "next", "project_id": null, "tag_id": null,
                   "sort": "manual", "page": {"limit": 50, "after": null}}),
        )
        .expect("answers"),
    );
    assert_eq!(list["value"]["items"][0]["id"], TASK);
    assert_eq!(list["value"]["has_more"], false);

    let projects = answered(ask(json!({"kind": "projects", "filter": "active"})).expect("answers"));
    assert_eq!(projects["value"][0]["project"]["id"], PROJECT);
    assert_eq!(projects["value"][0]["open_task_count"], 0);

    let mode = answered(
        ask(json!({"kind": "list_mode", "mode": {"type": "agenda"},
                   "page": {"limit": 50, "after": null}}))
        .expect("answers"),
    );
    assert_eq!(mode["value"]["open_count"], 0);

    // The shapes the Apple facade sends for the native list modes, with every option set.
    let options = json!({"sort": "manual", "group_by_project": false, "show_completed": false,
                         "show_cancelled": false, "priorities": [], "tag_filter": null});
    for mode in [
        json!({"type": "history", "kind": "completed"}),
        json!({"type": "date_view", "view": "today"}),
        json!({"type": "search", "text": "milk"}),
    ] {
        let page = answered(
            ask(
                json!({"kind": "list_mode", "mode": mode, "options": options,
                       "page": {"limit": 200, "after": null}}),
            )
            .expect("answers"),
        );
        assert_eq!(page["kind"], "list_mode");
    }
    let search = answered(
        ask(
            json!({"kind": "list_mode", "mode": {"type": "search", "text": "milk"},
                   "options": options, "page": {"limit": 200, "after": null}}),
        )
        .expect("answers"),
    );
    assert_eq!(search["value"]["sections"][0]["items"][0]["id"], TASK);
    let review = ask(json!({"kind": "review_queue", "step": "wins", "session_id": null}));
    assert!(review.is_ok());

    let detail = ask(json!({"kind": "task_detail", "task_id": "missing"})).expect("a value");
    let BridgeAnswer::Refused { refusal } = detail else {
        panic!("expected a refusal");
    };
    assert_eq!(refusal.reason, "not_found");
    assert_eq!(refusal.entity_type.as_deref(), Some("task"));
    assert_eq!(refusal.entity_key, vec!["missing".to_owned()]);
}

#[test]
fn dispatch_026_fr_002_resolves_and_proposes_a_smart_add_draft() {
    let runtime = runtime();
    let read = bytes(&json!({ "projects": { PROJECT: project(PROJECT, "Home") } }));
    let draft = bytes(&json!({"text": "Buy milk @Home #errands #\"big list\"", "list": "inbox"}));

    let resolved: Value = serde_json::from_slice(
        &runtime
            .smart_add_resolve(read.clone(), draft.clone())
            .expect("resolves"),
    )
    .expect("json");
    assert_eq!(resolved["title"], "Buy milk");
    assert_eq!(resolved["project"]["type"], "existing");
    assert_eq!(resolved["project"]["id"], PROJECT);
    assert_eq!(
        resolved["tags"][0],
        json!({"type": "new", "name": "errands"})
    );
    assert_eq!(resolved["tokens"][0]["kind"], "project");
    assert_eq!(resolved["tokens"][0]["utf16_start"], 9);
    assert!(resolved["problem"].is_null());

    let minted = bytes(&json!({"tags": [TAG, "tag_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d16"]}));
    let payload = answered(
        runtime
            .smart_add_propose(read.clone(), draft.clone(), minted)
            .expect("proposes"),
    );
    assert_eq!(payload["title"], "Buy milk");
    assert_eq!(payload["project"], json!({"id": PROJECT}));
    assert_eq!(
        payload["tags"][0],
        json!({"name": "errands", "proposed_id": TAG})
    );

    // A short supply of minted IDs is a request error, not a placeholder.
    let short = runtime
        .smart_add_propose(read.clone(), draft, bytes(&json!({"tags": [TAG]})))
        .expect_err("rejected");
    assert_eq!(
        failure(short),
        (
            "INVALID_REQUEST".to_owned(),
            false,
            Some("minted_ids".to_owned())
        )
    );

    // A blocked draft is a typed refusal that names the first problem.
    let blocked = runtime
        .smart_add_propose(
            read,
            bytes(&json!({"text": "@Home", "list": "inbox"})),
            b"{}".to_vec(),
        )
        .expect("a value");
    let BridgeAnswer::Refused { refusal } = blocked else {
        panic!("expected a refusal");
    };
    assert_eq!(refusal.reason, "empty_title");
}

#[test]
fn dispatch_026_fr_025_a_closed_runtime_rejects_every_dispatch_call() {
    let runtime = runtime();
    runtime.close();
    runtime.close();
    let closed = |error: BridgeError| failure(error).0;
    assert_eq!(
        closed(create_task(&runtime, TASK).expect_err("closed")),
        "WORKSPACE_CLOSED"
    );
    assert_eq!(
        closed(
            runtime
                .query(
                    read_set(&[]),
                    bytes(&json!({"kind": "tags"})),
                    query_inputs()
                )
                .expect_err("closed")
        ),
        "WORKSPACE_CLOSED"
    );
    assert_eq!(
        closed(
            runtime
                .smart_add_resolve(read_set(&[]), bytes(&json!({"text": "a", "list": "inbox"})))
                .expect_err("closed")
        ),
        "WORKSPACE_CLOSED"
    );
}

#[test]
fn dispatch_026_fr_025_shares_one_handle_across_threads_and_close_ends_every_call() {
    let runtime = Arc::new(runtime());
    let workers: Vec<_> = (0..8)
        .map(|_| {
            let runtime = Arc::clone(&runtime);
            std::thread::spawn(move || {
                (0..40)
                    .map(|_| match create_task(&runtime, TASK) {
                        Ok(BridgeDecision::Changed { .. }) => "ok".to_owned(),
                        Ok(BridgeDecision::Refused { .. }) => "refused".to_owned(),
                        Err(error) => failure(error).0,
                    })
                    .collect::<Vec<_>>()
            })
        })
        .collect();
    let closer = {
        let runtime = Arc::clone(&runtime);
        std::thread::spawn(move || runtime.close())
    };
    closer.join().expect("closer finished");
    for worker in workers {
        for outcome in worker.join().expect("worker finished") {
            assert!(
                ["ok", "CANCELLED", "WORKSPACE_CLOSED"].contains(&outcome.as_str()),
                "{outcome}"
            );
        }
    }
    assert!(!runtime.is_open());
}
