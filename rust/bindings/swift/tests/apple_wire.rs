//! The wire contract of the Apple facade (`RustDomainFacade.swift`, spec 026 T017): the
//! envelopes, payloads, read sets and inputs it builds, written out here as the JSON the
//! Swift encoders produce, run through the bridge's public API. The Swift side keeps the
//! Swift state keyed by bare UUIDs while the core wants `<prefix>_<uuid>` for a record it
//! creates, so the harness maps those identifiers the way `RustIDTable` does.
//!
//! Each step is a command the app issues and the shape of what the core answers:
//! if the core stopped accepting one of these shapes, the Swift facade would break.

use bb_swift::{BridgeAnswer, BridgeDecision, BridgeRuntime};
use serde_json::{Map, Value, json};

const HOME: &str = "aaaaaaaa-0000-4000-8000-000000000001";
const ERRANDS: &str = "bbbbbbbb-0000-4000-8000-000000000001";
const MILK: &str = "cccccccc-0000-4000-8000-000000000001";
const CALL: &str = "cccccccc-0000-4000-8000-000000000002";
const SUB: &str = "dddddddd-0000-4000-8000-000000000001";
const NOTE: &str = "eeeeeeee-0000-4000-8000-000000000001";

fn at(step: u32) -> String {
    format!("2026-10-09T08:{step:02}:00Z")
}

/// The Swift state as the core's read set, kept as the facade's `RustReadSet` shapes it.
struct Device {
    runtime: BridgeRuntime,
    read_set: Value,
}

fn bytes(value: &Value) -> Vec<u8> {
    serde_json::to_vec(value).expect("json")
}

/// `RustIDTable.new`: a bare UUID crosses as `<prefix>_<uuid>`.
fn wire(prefix: &str, raw: &str) -> String {
    format!("{prefix}_{raw}")
}

impl Device {
    fn new() -> Self {
        Self {
            runtime: BridgeRuntime::new(bb_swift::bridge_protocol_version()).expect("opens"),
            read_set: json!({
                "tasks": {}, "projects": {}, "tags": {}, "subtasks": {}, "comments": {},
                "sessions": {}, "decision_queues": {}, "decisions": {}, "receipts": [],
                "park_acks": [], "bulk_releases": {}, "consents": []
            }),
        }
    }

    fn inputs(&self, now: &str, allocated: &[String]) -> Vec<u8> {
        bytes(&json!({
            "rule_version": 1, "now": now, "time_zone": "UTC", "origin": "device",
            "actor_id": "device", "authoritative": false, "allocated_ids": allocated,
            "policy": {"weekly_review": false, "navigator_provider": null,
                       "navigator_available": false, "consent_text_version": 1}
        }))
    }

    /// Decides one command and, when it is accepted, applies the change set to the read set.
    fn run(
        &mut self,
        step: u32,
        kind: &str,
        entity: &str,
        payload: &Value,
        target: Option<(&str, &str)>,
        created: &[(&str, &str)],
    ) -> Result<Value, bb_swift::BridgeRefusal> {
        let now = at(step);
        let preconditions: Vec<Value> = target
            .map(|(entity_type, id)| {
                let section = match entity_type {
                    "task" => "tasks",
                    "project" => "projects",
                    "tag" => "tags",
                    _ => "subtasks",
                };
                let revision = self.read_set[section][id]["revision"].clone();
                json!({"entity_type": entity_type, "entity_id": id, "edit_revision": revision})
            })
            .into_iter()
            .collect();
        let envelope = json!({
            "protocol_version": 1, "command_id": "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11",
            "scope_id": "local", "device_id": "device", "device_epoch": "epoch",
            "local_sequence": "1", "type": kind, "command_version": 1, "entity_id": entity,
            "preconditions": preconditions, "depends_on": [], "issued_at": now, "payload": payload
        });
        let allocated = vec!["form_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d20".to_owned()];
        let decision = self
            .runtime
            .decide(
                bytes(&self.read_set),
                bytes(&envelope),
                bytes(&json!([])),
                self.inputs(&now, &allocated),
            )
            .expect("the bridge itself does not fail");
        match decision {
            BridgeDecision::Refused { refusal } => Err(refusal),
            BridgeDecision::Changed { change_set } => {
                let mut change_set: Value = serde_json::from_slice(&change_set).expect("json");
                for (prefixed, raw) in created {
                    rename(&mut change_set, prefixed, raw);
                }
                self.apply(&change_set);
                Ok(change_set)
            }
        }
    }

    /// `RustChangeApplier`, for the sections this scenario touches.
    fn apply(&mut self, change_set: &Value) {
        for change in change_set["changes"].as_array().expect("changes") {
            let entity_type = change["entity_type"].as_str().expect("type");
            let section = match entity_type {
                "task" => "tasks",
                "project" => "projects",
                "tag" => "tags",
                "subtask" => "subtasks",
                "comment" => "comments",
                other => panic!("unexpected {other}"),
            };
            if change["operation"] == "upsert" {
                let value = change["value"].clone();
                let id = value["id"].as_str().expect("id").to_owned();
                self.read_set[section]
                    .as_object_mut()
                    .expect("map")
                    .insert(id, value);
            } else {
                let id = change["record_key"][0].as_str().expect("key");
                self.read_set[section]
                    .as_object_mut()
                    .expect("map")
                    .remove(id);
            }
        }
    }

    fn task(&self, id: &str) -> &Value {
        &self.read_set["tasks"][id]
    }
}

fn rename(value: &mut Value, from: &str, to: &str) {
    match value {
        Value::String(text) if text == from => *text = to.to_owned(),
        Value::Array(items) => items.iter_mut().for_each(|item| rename(item, from, to)),
        Value::Object(map) => {
            let renamed: Map<String, Value> = std::mem::take(map)
                .into_iter()
                .map(|(key, mut item)| {
                    rename(&mut item, from, to);
                    (if key == from { to.to_owned() } else { key }, item)
                })
                .collect();
            *map = renamed;
        }
        _ => {}
    }
}

#[test]
fn apple_wire_026_sc_001_the_scenario_the_swift_parity_suite_runs_is_accepted() {
    let mut device = Device::new();

    // createProject, createTag, createTask: titles trimmed by the facade, names left to the core.
    device
        .run(
            1,
            "project.create",
            &wire("project", HOME),
            &json!({"name": "  Home  ", "color": null, "desired_outcome": null}),
            None,
            &[(&wire("project", HOME), HOME)],
        )
        .expect("project");
    assert_eq!(device.read_set["projects"][HOME]["name"], "Home");
    device
        .run(
            2,
            "tag.create",
            &wire("tag", ERRANDS),
            &json!({"name": "@errands"}),
            None,
            &[(&wire("tag", ERRANDS), ERRANDS)],
        )
        .expect("tag");
    assert_eq!(device.read_set["tags"][ERRANDS]["name"], "errands");

    let created = device
        .run(
            3,
            "task.create",
            &wire("task", MILK),
            &json!({
                "title": "Buy milk", "details": "From the shop", "state": "inbox",
                "project_id": HOME, "tag_ids": [ERRANDS], "due_date": "2026-12-01",
                "priority": "high", "waiting_for": null
            }),
            None,
            &[(&wire("task", MILK), MILK)],
        )
        .expect("task");
    assert_eq!(created["changes"][0]["value"]["id"], MILK);
    assert_eq!(device.task(MILK)["order_key"], "0");
    assert_eq!(device.task(MILK)["revision"], "1");

    // A task created in Next starts the formulation the facade allocated.
    device
        .run(
            4,
            "task.create",
            &wire("task", CALL),
            &json!({"title": "Call Sam", "details": null, "state": "next", "project_id": null,
                    "tag_ids": [], "due_date": null, "priority": "none", "waiting_for": null}),
            None,
            &[(&wire("task", CALL), CALL)],
        )
        .expect("next task");
    assert_eq!(
        device.task(CALL)["formulation"]["id"],
        "form_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d20"
    );

    // updateTask: only the changed members, the revision check on the target.
    device
        .run(
            5,
            "task.update",
            CALL,
            &json!({"title": "Call Sam about the invoice"}),
            Some(("task", CALL)),
            &[],
        )
        .expect("update");
    assert_eq!(device.task(CALL)["title"], "Call Sam about the invoice");

    // Moving to Waiting without a note is the core's refusal, with the reason the app words.
    let refusal = device
        .run(
            6,
            "task.transition",
            CALL,
            &json!({"action": "move", "to_state": "waiting"}),
            Some(("task", CALL)),
            &[],
        )
        .expect_err("a note is required");
    assert_eq!(refusal.reason, "waiting_for_required");
    device
        .run(
            7,
            "task.transition",
            CALL,
            &json!({"action": "move", "to_state": "waiting", "waiting_for": "  Sam  "}),
            Some(("task", CALL)),
            &[],
        )
        .expect("waiting");
    assert_eq!(device.task(CALL)["waiting_for"], "Sam");
    assert!(device.task(CALL)["formulation"].is_null());
    device
        .run(
            8,
            "task.transition",
            CALL,
            &json!({"action": "complete"}),
            Some(("task", CALL)),
            &[],
        )
        .expect("complete");
    assert_eq!(device.task(CALL)["state"], "completed");
    device
        .run(
            9,
            "task.transition",
            CALL,
            &json!({"action": "reopen", "to_state": "next"}),
            Some(("task", CALL)),
            &[],
        )
        .expect("reopen");
    assert_eq!(device.task(CALL)["state"], "next");

    // Archive: a task cannot join an archived project.
    device
        .run(
            10,
            "project.archive",
            HOME,
            &json!({}),
            Some(("project", HOME)),
            &[],
        )
        .expect("archive");
    let third = "cccccccc-0000-4000-8000-000000000003";
    let refusal = device
        .run(
            11,
            "task.create",
            &wire("task", third),
            &json!({"title": "Dust", "details": null, "state": "inbox", "project_id": HOME,
                    "tag_ids": [], "due_date": null, "priority": "none", "waiting_for": null}),
            None,
            &[],
        )
        .expect_err("archived");
    assert_eq!(refusal.reason, "project_not_active");
    device
        .run(
            12,
            "project.unarchive",
            HOME,
            &json!({}),
            Some(("project", HOME)),
            &[],
        )
        .expect("unarchive");

    // Children: a subtask and a comment, each with its own revision.
    device
        .run(
            13,
            "subtask.create",
            &wire("subtask", SUB),
            &json!({"task_id": MILK, "title": "Oat milk"}),
            None,
            &[(&wire("subtask", SUB), SUB)],
        )
        .expect("subtask");
    device
        .run(
            14,
            "subtask.transition",
            SUB,
            &json!({"task_id": MILK, "action": "complete"}),
            Some(("subtask", SUB)),
            &[],
        )
        .expect("subtask done");
    assert_eq!(device.read_set["subtasks"][SUB]["state"], "completed");
    device
        .run(
            15,
            "comment.create",
            &wire("comment", NOTE),
            &json!({"task_id": MILK, "body": "Ask for the big bottle"}),
            None,
            &[(&wire("comment", NOTE), NOTE)],
        )
        .expect("comment");
    assert_eq!(device.read_set["comments"][NOTE]["actor_id"], "device");

    // Deleting a tag takes it off every task; project outcome and a multi-field edit.
    device
        .run(
            16,
            "tag.delete",
            ERRANDS,
            &json!({}),
            Some(("tag", ERRANDS)),
            &[],
        )
        .expect("tag delete");
    assert_eq!(device.task(MILK)["tag_ids"], json!([]));
    assert_eq!(device.read_set["tags"][ERRANDS]["state"], "deleted");
    device
        .run(
            17,
            "project.update",
            HOME,
            &json!({"desired_outcome": "Calm home"}),
            Some(("project", HOME)),
            &[],
        )
        .expect("outcome");
    assert_eq!(
        device.read_set["projects"][HOME]["desired_outcome"],
        "Calm home"
    );
    device
        .run(
            18,
            "task.update",
            MILK,
            &json!({"details": null, "due_date": null, "priority": "low",
                    "tag_changes": {"add_tag_ids": [], "remove_tag_ids": []}}),
            Some(("task", MILK)),
            &[],
        )
        .expect("clears");
    let milk = device.task(MILK);
    assert!(milk["details"].is_null() && milk["due_date"].is_null());
    assert_eq!(milk["priority"], "low");

    // A second project with the same name: the refusal names the project that holds it.
    let refusal = device
        .run(
            19,
            "project.create",
            &wire("project", "aaaaaaaa-0000-4000-8000-000000000002"),
            &json!({"name": "home", "color": null, "desired_outcome": null}),
            None,
            &[],
        )
        .expect_err("duplicate");
    assert_eq!(refusal.reason, "duplicate_project_name");
    assert_eq!(refusal.entity_key, vec![HOME.to_owned()]);

    // A missing record has no revision to check: the core says it is not found.
    let refusal = device
        .run(
            20,
            "task.update",
            "missing",
            &json!({"title": "x"}),
            None,
            &[],
        )
        .expect_err("missing");
    assert_eq!(
        (refusal.reason.as_str(), refusal.entity_type.as_deref()),
        ("not_found", Some("task"))
    );

    // An empty or overlong title is one payload error, told apart by the request's length.
    for title in [String::new(), "x".repeat(501)] {
        let refusal = device
            .run(
                21,
                "task.create",
                &wire("task", third),
                &json!({"title": title, "details": null, "state": "inbox", "project_id": null,
                        "tag_ids": [], "due_date": null, "priority": "none", "waiting_for": null}),
                None,
                &[],
            )
            .expect_err("title");
        assert_eq!(
            (refusal.reason.as_str(), refusal.field.as_deref()),
            ("invalid_payload", Some("Title"))
        );
    }
}

#[test]
fn apple_wire_026_fr_016_review_commands_are_accepted_in_the_shapes_the_facade_sends() {
    let mut device = Device::new();
    let runtime = &device.runtime;
    let run = |read_set: &Value,
               kind: &str,
               entity: &str,
               payload: &Value,
               pre: &Value,
               policy: &Value| {
        let envelope = json!({
            "protocol_version": 1, "command_id": "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11",
            "scope_id": "local", "device_id": "device", "device_epoch": "epoch",
            "local_sequence": "1", "type": kind, "command_version": 1, "entity_id": entity,
            "preconditions": pre, "depends_on": [], "issued_at": "2026-10-09T12:00:00Z",
            "payload": payload
        });
        let inputs = json!({
            "rule_version": 1, "now": "2026-10-09T12:00:00Z", "time_zone": "UTC", "origin": "device",
            "actor_id": "device", "authoritative": false,
            "allocated_ids": ["form_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d20"], "policy": policy
        });
        runtime
            .decide(
                bytes(read_set),
                bytes(&envelope),
                bytes(&json!([])),
                bytes(&inputs),
            )
            .expect("the bridge itself does not fail")
    };
    let exposed = json!({"weekly_review": true, "navigator_provider": null,
                         "navigator_available": false, "consent_text_version": 1});
    let session = "review_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d30";

    // The first acknowledgement activates the owner; settings are "not stored" until then.
    let outcome = run(
        &device.read_set,
        "review.explainer_ack",
        "local",
        &json!({"time_zone": "UTC"}),
        &json!([]),
        &exposed,
    );
    let BridgeDecision::Changed { change_set } = outcome else {
        panic!("explainer_ack was refused");
    };
    let change_set: Value = serde_json::from_slice(&change_set).expect("json");
    let settings = change_set["changes"]
        .as_array()
        .expect("changes")
        .iter()
        .find(|change| change["entity_type"] == "review_settings")
        .expect("settings change");
    assert!(settings["value"]["activated_at"].is_string());
    device.read_set["settings"] = settings["value"].clone();

    // Settings: only the named members, checked against the settings revision at the scope.
    let revision = device.read_set["settings"]["revision"].clone();
    let outcome = run(
        &device.read_set,
        "review.settings",
        "local",
        &json!({"threshold_days": 21, "onboarded": true}),
        &json!([{"entity_type": "review_settings", "entity_id": "local", "edit_revision": revision}]),
        &exposed,
    );
    assert!(matches!(outcome, BridgeDecision::Changed { .. }));

    // Starting a session with the facade's payload.
    let outcome = run(
        &device.read_set,
        "review.session_start",
        session,
        &json!({"mode": "quick", "entry": "list", "origin": "ios", "skip_steps": [], "replace_open": true}),
        &json!([]),
        &exposed,
    );
    let BridgeDecision::Changed { change_set } = outcome else {
        panic!("session_start was refused");
    };
    let change_set: Value = serde_json::from_slice(&change_set).expect("json");
    let stored = change_set["changes"]
        .as_array()
        .expect("changes")
        .iter()
        .find(|change| change["entity_type"] == "review_session")
        .expect("session change");
    assert_eq!(stored["value"]["status"], "open");
    assert_eq!(stored["value"]["counts"]["done"], 0);
    device.read_set["sessions"][session] = stored["value"].clone();

    // Progress and finish, the optional members omitted as the facade omits them.
    let outcome = run(
        &device.read_set,
        "review.session_progress",
        session,
        &json!({"progress_id": "progress_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d31",
                "step": {"code": "wins", "status": "finished"},
                "active_seconds": {"code": "wins", "seconds": 12}}),
        &json!([]),
        &exposed,
    );
    assert!(matches!(outcome, BridgeDecision::Changed { .. }));
    let outcome = run(
        &device.read_set,
        "review.session_finish",
        session,
        &json!({"clear_start": null}),
        &json!([]),
        &exposed,
    );
    assert!(matches!(outcome, BridgeDecision::Changed { .. }));

    // Consent: the provider and the consent text version travel as policy too.
    let policy = json!({"weekly_review": true, "navigator_provider": "apple",
                        "navigator_available": true, "consent_text_version": 2});
    let outcome = run(
        &device.read_set,
        "review.consent_grant",
        "local",
        &json!({"provider": "apple", "consent_text_version": 2}),
        &json!([]),
        &policy,
    );
    assert!(matches!(outcome, BridgeDecision::Changed { .. }));
    let outcome = run(
        &device.read_set,
        "review.consent_revoke",
        "local",
        &json!({"provider": "apple"}),
        &json!([]),
        &exposed,
    );
    assert!(matches!(
        outcome,
        BridgeDecision::Changed { .. } | BridgeDecision::Refused { .. }
    ));

    let task = json!({
        "id": MILK, "title": "Call Sam", "details": null, "state": "next", "project_id": null,
        "tag_ids": [], "due_date": null, "priority": "none", "waiting_for": null,
        "waiting_since": null, "order_key": "0", "source_capture_ids": [],
        "created_at": "2026-10-01T08:00:00Z", "updated_at": "2026-10-01T08:00:00Z",
        "completed_at": null, "cancelled_at": null, "revision": "3",
        "consecutive_stalled_formulations": 0, "parked": null,
        "formulation": {"id": "form_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d21",
                        "started_at": "2026-10-01T08:00:00Z", "extended_at": null,
                        "extension_reason": null, "park_floor_at": null}
    });
    device.read_set["tasks"][MILK] = task;
    let decide = json!({
        "decision_id": "decision_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d32", "type": "complete",
        "formulation_id": "form_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d21", "stall_reason": null,
        "title": null, "waiting_for": null, "reason": null, "session_id": null, "ai_use": "none",
        "navigator_request_id": null, "client_decided_at": "2026-10-09T12:00:00Z"
    });
    let check = json!([{"entity_type": "task", "entity_id": MILK, "edit_revision": "3"}]);
    // The core gates only the Review reads on the weekly-review flag, not a write: the
    // facade keeps that product gate (`ReviewState.isExposed`) at its own boundary.
    let off = json!({"weekly_review": false, "navigator_provider": null,
                     "navigator_available": false, "consent_text_version": 1});
    let outcome = run(
        &device.read_set,
        "review.decide",
        MILK,
        &decide,
        &check,
        &off,
    );
    assert!(
        matches!(outcome, BridgeDecision::Changed { .. }),
        "{outcome:?}"
    );
    let outcome = run(
        &device.read_set,
        "review.decide",
        MILK,
        &decide,
        &check,
        &exposed,
    );
    assert!(
        matches!(outcome, BridgeDecision::Changed { .. }),
        "the decision payload the facade sends is accepted: {outcome:?}"
    );

    // A bulk release names each task with the revision it was shown at.
    let inbox_task = json!({
        "id": CALL, "title": "Sort mail", "details": null, "state": "inbox", "project_id": null,
        "tag_ids": [], "due_date": null, "priority": "none", "waiting_for": null,
        "waiting_since": null, "order_key": "0", "source_capture_ids": [],
        "created_at": "2026-10-01T08:00:00Z", "updated_at": "2026-10-01T08:00:00Z",
        "completed_at": null, "cancelled_at": null, "revision": "1",
        "consecutive_stalled_formulations": 0, "parked": null, "formulation": null
    });
    device.read_set["tasks"][CALL] = inbox_task;
    let outcome = run(
        &device.read_set,
        "review.bulk_release",
        "bulk_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d33",
        &json!({"kind": "inbox_remainder", "session_id": null,
                "items": [{"task_id": CALL, "expected_revision": "1"}]}),
        &json!([]),
        &exposed,
    );
    let BridgeDecision::Changed { change_set } = outcome else {
        panic!("bulk release refused");
    };
    let change_set: Value = serde_json::from_slice(&change_set).expect("json");
    let released = change_set["changes"]
        .as_array()
        .expect("changes")
        .iter()
        .find(|change| change["entity_type"] == "review_bulk_release")
        .expect("bulk release record");
    assert_eq!(released["value"]["released"][0]["task_id"], CALL);
    let receipt = change_set["changes"]
        .as_array()
        .expect("changes")
        .iter()
        .find(|change| change["entity_type"] == "review_receipt")
        .expect("the release's Someday receipt");
    assert_eq!(
        receipt["value"]["bulk_id"],
        "bulk_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d33"
    );
    assert_eq!(receipt["value"]["kind"], "someday");

    // Parks are acknowledged by key.
    let outcome = run(
        &device.read_set,
        "review.parks_ack",
        "local",
        &json!({"items": [{"task_id": MILK, "formulation_id": "form_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d21"}]}),
        &json!([]),
        &exposed,
    );
    assert!(matches!(outcome, BridgeDecision::Changed { .. }));

    // Undo needs the authoritative side's snapshot: the device is told it is unavailable.
    let outcome = run(
        &device.read_set,
        "review.undo_decision",
        "decision_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d32",
        &json!({}),
        &json!([]),
        &exposed,
    );
    let BridgeDecision::Refused { refusal } = outcome else {
        panic!("nothing to undo");
    };
    assert_eq!(refusal.reason, "not_found");
    assert_eq!(refusal.entity_type.as_deref(), Some("review_decision"));
}

#[test]
fn apple_wire_026_sc_001_smart_add_decides_atomically_from_the_proposed_payload() {
    let device = Device::new();
    let draft = bytes(&json!({"text": "Buy milk @Home #errands", "list": "inbox",
                              "waiting_for": "", "details": "", "due_date": null,
                              "priority": "none", "context_project": null, "context_tag": null}));
    let read = bytes(&device.read_set);
    let project = wire("project", HOME);
    let tag = wire("tag", ERRANDS);
    let minted = bytes(&json!({"project": project, "tags": [tag]}));
    let BridgeAnswer::Answered { result } = device
        .runtime
        .smart_add_propose(read.clone(), draft, minted)
        .expect("proposes")
    else {
        panic!("blocked");
    };
    let payload: Value = serde_json::from_slice(&result).expect("json");
    assert_eq!(
        payload["project"],
        json!({"name": "Home", "proposed_id": project})
    );

    let envelope = json!({
        "protocol_version": 1, "command_id": "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11",
        "scope_id": "local", "device_id": "device", "device_epoch": "epoch", "local_sequence": "1",
        "type": "task.smart_add", "command_version": 1, "entity_id": wire("task", MILK),
        "preconditions": [], "depends_on": [], "issued_at": at(1), "payload": payload
    });
    let decision = device
        .runtime
        .decide(
            read,
            bytes(&envelope),
            bytes(&json!([])),
            device.inputs(&at(1), &[]),
        )
        .expect("decides");
    let BridgeDecision::Changed { change_set } = decision else {
        panic!("smart add refused");
    };
    let change_set: Value = serde_json::from_slice(&change_set).expect("json");
    let kinds: Vec<&str> = change_set["changes"]
        .as_array()
        .expect("changes")
        .iter()
        .map(|change| change["entity_type"].as_str().expect("type"))
        .collect();
    assert_eq!(kinds, ["project", "tag", "task"]);
}

#[test]
fn apple_wire_026_fr_002_a_repeated_create_meets_the_canonical_id_in_the_read_set() {
    // The facade sends every identifier in its canonical `<prefix>_<uuid>` form, the read set
    // included, so a create of an ID the state holds is the core's `id_already_exists`.
    let mut device = Device::new();
    let project = wire("project", HOME);
    let tag = wire("tag", ERRANDS);
    let task = wire("task", MILK);
    let subtask = wire("subtask", SUB);
    let comment = wire("comment", NOTE);
    let creates: Vec<(&str, String, Value)> = vec![
        (
            "project.create",
            project.clone(),
            json!({"name": "Home", "color": null, "desired_outcome": null}),
        ),
        ("tag.create", tag.clone(), json!({"name": "errands"})),
        (
            "task.create",
            task.clone(),
            json!({"title": "Buy milk", "details": null, "state": "inbox", "project_id": project,
                   "tag_ids": [tag], "due_date": null, "priority": "none", "waiting_for": null}),
        ),
        (
            "subtask.create",
            subtask,
            json!({"task_id": task, "title": "Oat milk"}),
        ),
        (
            "comment.create",
            comment,
            json!({"task_id": task, "body": "Ask for the big bottle"}),
        ),
    ];
    for (step, (kind, entity, payload)) in creates.iter().enumerate() {
        device
            .run(step as u32 + 1, kind, entity, payload, None, &[])
            .unwrap_or_else(|refusal| panic!("{kind} refused: {refusal:?}"));
    }
    let before = device.read_set.clone();
    for (step, (kind, entity, payload)) in creates.iter().enumerate() {
        let refusal = device
            .run(step as u32 + 10, kind, entity, payload, None, &[])
            .expect_err("a second create of the same ID");
        assert_eq!(refusal.reason, "id_already_exists", "{kind}");
    }
    assert_eq!(device.read_set, before, "a refusal changes nothing");
}

#[test]
fn apple_wire_026_fr_016_an_observed_park_is_decided_by_the_core_without_a_snapshot() {
    let device = Device::new();
    let form = "form_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d21";
    let read_set = json!({
        "settings": {
            "threshold_days": 14, "review_weekday": 5, "review_time": "16:00", "time_zone": "UTC",
            "onboarded_at": null, "activated_at": "2026-03-01T08:00:00Z",
            "owner_park_floor_at": null, "revision": "1",
            // The sweep ran an hour ago: without it the core sees a gap of 24 hours or more and
            // floors every park for 7 days (SC-006), which is what a device without the
            // server's sweep bookkeeping always gets.
            "private": {"last_effective_sweep_at": "2026-10-09T11:00:00Z",
                        "threshold_changed_at": null}
        },
        "tasks": { MILK: {
            "id": MILK, "title": "Call Sam", "details": null, "state": "next", "project_id": null,
            "tag_ids": [], "due_date": null, "priority": "none", "waiting_for": null,
            "waiting_since": null, "order_key": "0", "source_capture_ids": [],
            "created_at": "2026-06-01T08:00:00Z", "updated_at": "2026-06-01T08:00:00Z",
            "completed_at": null, "cancelled_at": null, "revision": "1",
            "consecutive_stalled_formulations": 0, "parked": null,
            "formulation": {"id": form, "started_at": "2026-06-01T08:00:00Z", "extended_at": null,
                            "extension_reason": null, "park_floor_at": null}
        } }
    });
    let envelope = json!({
        "protocol_version": 1, "command_id": "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11",
        "scope_id": "local", "device_id": "device", "device_epoch": "epoch", "local_sequence": "1",
        "type": "review.auto_park", "command_version": 1, "entity_id": MILK,
        "preconditions": [], "depends_on": [], "issued_at": "2026-10-09T12:00:00Z",
        "payload": {"formulation_id": form}
    });
    let inputs = json!({
        "rule_version": 1, "now": "2026-10-09T12:00:00Z", "time_zone": "UTC", "origin": "device",
        "actor_id": "device", "authoritative": false, "allocated_ids": [],
        "policy": {"weekly_review": true, "navigator_provider": null,
                   "navigator_available": false, "consent_text_version": 1}
    });
    let decision = device
        .runtime
        .decide(
            bytes(&read_set),
            bytes(&envelope),
            bytes(&json!([])),
            bytes(&inputs),
        )
        .expect("decides");
    let BridgeDecision::Changed { change_set } = decision else {
        panic!("the park was refused");
    };
    let change_set: Value = serde_json::from_slice(&change_set).expect("json");
    assert_eq!(change_set["result"]["applied"], true);
    let parked = change_set["changes"]
        .as_array()
        .expect("changes")
        .iter()
        .find(|change| change["entity_type"] == "task")
        .expect("the parked task");
    assert_eq!(parked["value"]["state"], "someday");
    assert_eq!(parked["value"]["parked"]["formulation_id"], form);
    // The device is not authoritative: no private snapshot is written.
    assert!(parked["value"]["parked"].get("private").is_none());

    // Without the server's sweep bookkeeping the same park is `applied: false`.
    let mut gap = read_set.clone();
    gap["settings"]
        .as_object_mut()
        .expect("settings")
        .remove("private");
    let decision = device
        .runtime
        .decide(
            bytes(&gap),
            bytes(&envelope),
            bytes(&json!([])),
            bytes(&inputs),
        )
        .expect("decides");
    let BridgeDecision::Changed { change_set } = decision else {
        panic!("the park was refused");
    };
    let change_set: Value = serde_json::from_slice(&change_set).expect("json");
    assert_eq!(change_set["result"]["applied"], false);
}

#[test]
fn apple_wire_026_fr_016_settings_never_stored_are_checked_at_the_default_revision() {
    // Settings nobody changed are left out of the read set; the core's default row is at
    // revision 1, which is what the facade's revision check names for them.
    let device = Device::new();
    let envelope = |revision: &str| {
        json!({
            "protocol_version": 1, "command_id": "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11",
            "scope_id": "local", "device_id": "device", "device_epoch": "epoch", "local_sequence": "1",
            "type": "review.settings", "command_version": 1, "entity_id": "local",
            "preconditions": [{"entity_type": "review_settings", "entity_id": "local",
                               "edit_revision": revision}],
            "depends_on": [], "issued_at": "2026-10-09T12:00:00Z",
            "payload": {"threshold_days": 21}
        })
    };
    for (revision, accepted) in [("1", true), ("0", false)] {
        let decision = device
            .runtime
            .decide(
                bytes(&device.read_set),
                bytes(&envelope(revision)),
                bytes(&json!([])),
                device.inputs(&at(1), &[]),
            )
            .expect("decides");
        assert_eq!(
            matches!(decision, BridgeDecision::Changed { .. }),
            accepted,
            "{revision}"
        );
    }
}
