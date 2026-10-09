//! Source-linked conversions for the frozen domain types (T061): the Review
//! wire fixtures shared with the backend, the sync-v1 example envelope and the
//! frozen schema's command list all decode into the typed values, and the
//! refusals they pin stay refusals.

use bb_domain::types::*;
use bb_protocol::command::{Decoded, decode_command};
use bb_protocol::receipt::Receipt;
use serde_json::{Value, json};
use std::collections::BTreeSet;

const WIRE: &str = include_str!("../../../../backend/tests/fixtures/review_wire_fixtures.json");
const SCHEMA: &str =
    include_str!("../../../../specs/026-rust-core-sync/contracts/sync-v1.schema.json");

const TASK: &str = "task_9f3c2a1b4d5e";
const SETTINGS_OWNER: &str = "scope-example";

/// REST request model, its sync command type and the entity its revision check names.
const REQUESTS: &[(&str, &str, &str)] = &[
    ("DecisionRequest", "review.decide", "task"),
    ("UndoDecisionRequest", "review.undo_decision", "task"),
    ("AutoParkRequest", "review.auto_park", "task"),
    (
        "ExplainerAcknowledgeRequest",
        "review.explainer_ack",
        "review_settings",
    ),
    (
        "ReviewSettingsUpdateRequest",
        "review.settings",
        "review_settings",
    ),
    ("ParkAcknowledgeRequest", "review.parks_ack", "task"),
    (
        "SessionStartRequest",
        "review.session_start",
        "review_session",
    ),
    (
        "SessionProgressRequest",
        "review.session_progress",
        "review_session",
    ),
    (
        "SessionFinishRequest",
        "review.session_finish",
        "review_session",
    ),
    (
        "BulkReleaseRequest",
        "review.bulk_release",
        "review_bulk_release",
    ),
    (
        "NavigatorConsentGrantRequest",
        "review.consent_grant",
        "review_navigator_consent",
    ),
];

/// Counters travel as integers on REST and as decimal strings on sync v1.
const COUNTER_KEYS: &[&str] = &[
    "revision",
    "order_key",
    "task_revision",
    "revision_after",
    "expected_revision",
    "expected_task_revision",
];

fn decimalize(value: &mut Value) {
    match value {
        Value::Object(map) => {
            for (key, inner) in map.iter_mut() {
                match inner.as_u64() {
                    Some(n) if COUNTER_KEYS.contains(&key.as_str()) => {
                        *inner = Value::String(n.to_string());
                    }
                    _ => decimalize(inner),
                }
            }
        }
        Value::Array(items) => items.iter_mut().for_each(decimalize),
        _ => {}
    }
}

fn entries() -> Vec<Value> {
    let doc: Value = serde_json::from_str(WIRE).expect("fixture parses");
    doc["entries"].as_array().expect("entries").clone()
}

fn entry(id: &str) -> Value {
    entries()
        .into_iter()
        .find(|e| e["id"] == id)
        .unwrap_or_else(|| panic!("fixture {id}"))
}

fn body(id: &str) -> Value {
    let mut body = entry(id)["body"].clone();
    decimalize(&mut body);
    body
}

fn request_row(model: &str) -> Option<&'static (&'static str, &'static str, &'static str)> {
    REQUESTS.iter().find(|(m, _, _)| *m == model)
}

/// REST request body to sync payload: the revision check moves to preconditions,
/// the creation ID moves to the envelope, a missing decision ID is minted.
fn to_payload(model: &str, body: &Value) -> Value {
    let mut payload = body.as_object().cloned().unwrap_or_default();
    payload.remove("expected_revision");
    payload.remove("expected_task_revision");
    if matches!(model, "SessionStartRequest" | "BulkReleaseRequest") {
        payload.remove("id");
    }
    if model == "DecisionRequest" && !payload.contains_key("decision_id") {
        payload.insert(
            "decision_id".into(),
            json!("decision_00000000-0000-4000-8000-000000000000"),
        );
    }
    let mut payload = Value::Object(payload);
    decimalize(&mut payload);
    Value::Object(payload.as_object().cloned().unwrap_or_default())
}

fn object(value: Value) -> bb_protocol::wire::OpenObject {
    value.as_object().cloned().expect("object")
}

/// An `after_command` precondition must also be in `depends_on` (sync-v1 §3).
fn envelope_json(command_type: &str, payload: Value, preconditions: Value) -> String {
    let depends_on: Vec<Value> = preconditions
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|p| p["after_command"]["command_id"].as_str())
        .map(|id| json!(id))
        .collect();
    json!({
        "protocol_version": 1,
        "command_id": "01900000-0000-4000-8000-000000000001",
        "scope_id": SETTINGS_OWNER,
        "device_id": "device-example",
        "device_epoch": "epoch-example",
        "local_sequence": "42",
        "type": command_type,
        "command_version": 1,
        "entity_id": TASK,
        "preconditions": preconditions,
        "depends_on": depends_on,
        "issued_at": "2026-10-08T10:00:00Z",
        "payload": payload
    })
    .to_string()
}

fn executable(
    command_type: &str,
    payload: Value,
    preconditions: Value,
) -> bb_protocol::command::CommandEnvelope {
    match decode_command(&envelope_json(command_type, payload, preconditions)) {
        Ok(Decoded::Executable(envelope)) => envelope,
        other => panic!("{command_type} should decode as executable: {other:?}"),
    }
}

fn typed(model: &str, body: &Value) -> Result<Command, DomainError> {
    let (_, command_type, _) = request_row(model).expect("mapped model");
    let command_type = CommandType::from_wire(command_type).expect("catalog type");
    let command = Command::from_payload(command_type, &object(to_payload(model, body)))?;
    command.check_shape()?;
    Ok(command)
}

// ------------------------------------------------------------- review requests

#[test]
fn types_026_fr_002_valid_review_requests_decode_as_catalog_payloads() {
    let mut decoded = 0;
    for e in entries().iter().filter(|e| e["valid"] == true) {
        let model = e["model"].as_str().unwrap();
        if request_row(model).is_none() {
            continue;
        }
        let command = typed(model, &e["body"]).unwrap_or_else(|err| panic!("{}: {err}", e["id"]));
        assert_eq!(
            command.command_type().as_str(),
            request_row(model).unwrap().1,
            "{}",
            e["id"]
        );
        decoded += 1;
    }
    assert_eq!(decoded, 17, "source-linked request fixtures decoded");
}

#[test]
fn types_026_fr_002_review_requests_pass_the_full_envelope_path() {
    for e in entries().iter().filter(|e| e["valid"] == true) {
        let model = e["model"].as_str().unwrap();
        let Some((_, command_type, entity)) = request_row(model) else {
            continue;
        };
        let revision = e["body"]
            .get("expected_revision")
            .or_else(|| e["body"].get("expected_task_revision"))
            .and_then(Value::as_u64);
        let checks = revision.map_or(
            json!([]),
            |n| json!([{"entity_type": entity, "entity_id": TASK, "edit_revision": n.to_string()}]),
        );
        let envelope = executable(command_type, to_payload(model, &e["body"]), checks);
        let command = DomainCommand::from_envelope(&envelope, &NoReceipts)
            .unwrap_or_else(|err| panic!("{}: {err}", e["id"]));
        assert_eq!(command.preconditions.len(), usize::from(revision.is_some()));
        assert_eq!(command.command_type().as_str(), *command_type);
        assert_eq!(command.entity_id.as_str(), TASK);
    }
}

#[test]
fn types_026_fr_002_structural_refusals_match_the_wire_fixtures() {
    let mut refused = 0;
    for e in entries().iter().filter(|e| e["valid"] == false) {
        let model = e["model"].as_str().unwrap();
        if request_row(model).is_none() {
            continue;
        }
        assert!(
            typed(model, &e["body"]).is_err(),
            "{} must be refused",
            e["id"]
        );
        refused += 1;
    }
    assert_eq!(refused, 11);
}

#[test]
fn types_026_fr_016_a_decision_must_carry_the_fields_its_type_needs() {
    // W-R06: "keep 7 more days" needs a reason.
    let err = typed("DecisionRequest", &entry("W-R06")["body"]).unwrap_err();
    assert_eq!(
        (err.reason, err.field.as_deref()),
        (Reason::DecisionFieldsMissing, Some("reason"))
    );
    // A Next-only type must name the formulation it decides on.
    let body = json!({"type": "someday", "expected_revision": 4});
    let err = typed("DecisionRequest", &body).unwrap_err();
    assert_eq!(err.field.as_deref(), Some("formulation_id"));
    // The decision types with no extra requirement stand on their own.
    for decision_type in ["complete", "cancel", "keep_waiting", "keep_someday"] {
        let body = json!({"type": decision_type, "expected_revision": 4});
        assert!(typed("DecisionRequest", &body).is_ok(), "{decision_type}");
    }
}

#[test]
fn types_026_fr_002_client_and_reference_id_shapes_are_distinct() {
    // W-012 references a server-minted formulation and session; both are fine as references.
    let reference = typed("DecisionRequest", &entry("W-012")["body"]).unwrap();
    let Command::ReviewDecide(decide) = reference else {
        panic!("decide")
    };
    assert!(!decide.formulation_id.unwrap().has_client_shape());
    // A creation ID must be the client shape: the legacy 12-hex form is refused there.
    let legacy_new = json!({"decision_id": "decision_8c4e1a7d2b9f", "type": "complete"});
    let err = Command::from_payload(CommandType::ReviewDecide, &object(legacy_new)).unwrap_err();
    assert_eq!(err.field.as_deref(), Some("NewDecisionId"));
    let legacy_form = json!({"decision_id": "decision_6b1e8a52-3f0c-4e7a-9d21-5c8b0f4a7e19",
        "type": "complete", "new_formulation_id": "form_0a1b2c3d4e5f"});
    assert!(Command::from_payload(CommandType::ReviewDecide, &object(legacy_form)).is_err());
    // The Navigator request ID is a bare UUID, never prefixed.
    assert!(NavigatorRequestId::parse("4f0c2b7e-8a1d-4e69-b3c5-0d7f9a2e6c81").is_ok());
    assert!(NavigatorRequestId::parse("navigator_4f0c2b7e-8a1d-4e69-b3c5-0d7f9a2e6c81").is_err());
}

// ---------------------------------------------------------- public record shapes

#[test]
fn types_026_fr_013_public_review_records_decode_and_round_trip() {
    for e in entries() {
        let id = e["id"].as_str().unwrap().to_owned();
        let mut wire = e["body"].clone();
        decimalize(&mut wire);
        let valid = e["valid"] == true;
        match e["model"].as_str().unwrap() {
            "SessionResponse" => {
                let decoded = serde_json::from_value::<ReviewSession>(wire.clone());
                assert_eq!(decoded.is_ok(), valid, "{id}");
                if let Ok(session) = decoded {
                    assert!(session.private.is_none());
                    assert_eq!(serde_json::to_value(&session).unwrap(), wire, "{id}");
                }
            }
            "ReviewSettingsResponse" => {
                let settings: ReviewSettings = serde_json::from_value(wire.clone()).unwrap();
                assert_eq!(serde_json::to_value(&settings).unwrap(), wire, "{id}");
            }
            "ReviewStateResponse" => {
                let state: ReviewStateView = serde_json::from_value(wire.clone()).unwrap();
                assert_eq!(serde_json::to_value(&state).unwrap(), wire, "{id}");
            }
            "QueueResponse" => {
                let queue: QueueView = serde_json::from_value(wire.clone()).unwrap();
                assert_eq!(serde_json::to_value(&queue).unwrap(), wire, "{id}");
            }
            "TaskResponse" => {
                let task: TaskView = serde_json::from_value(wire.clone()).unwrap();
                assert_eq!(serde_json::to_value(&task).unwrap(), wire, "{id}");
            }
            "BulkReleaseUndoResponse" => {
                let undo: BulkUndoResult = serde_json::from_value(wire.clone()).unwrap();
                assert_eq!(serde_json::to_value(&undo).unwrap(), wire, "{id}");
            }
            _ => {}
        }
    }
}

#[test]
fn types_026_fr_013_queue_metadata_is_decoded_by_shape() {
    let kinds: Vec<_> = ["W-047", "W-048", "W-049", "W-050", "W-051", "W-052"]
        .into_iter()
        .map(|id| {
            let queue: QueueView = serde_json::from_value(body(id)).unwrap();
            match queue.meta {
                QueueMeta::Wins(_) => "wins",
                QueueMeta::RestOfNext(_) => "rest_of_next",
                QueueMeta::Someday(_) => "someday",
                QueueMeta::Dates(_) => "dates",
                QueueMeta::Decisions(_) => "decisions",
                QueueMeta::Empty(_) => "empty",
            }
        })
        .collect();
    // W-052 is documented as "a queue without step meta"; the fixture sends {}.
    assert_eq!(
        kinds,
        [
            "wins",
            "rest_of_next",
            "rest_of_next",
            "someday",
            "dates",
            "empty"
        ]
    );
    // The mirror keeps null pace without four weeks of history.
    let QueueMeta::RestOfNext(thin) = serde_json::from_value::<QueueView>(body("W-049"))
        .unwrap()
        .meta
    else {
        panic!("rest of next")
    };
    assert_eq!((thin.weekly_average_4w, thin.implied_weeks), (None, None));
    assert!(serde_json::from_value::<QueueMeta>(json!({"count": 1, "extra": true})).is_err());
}

#[test]
fn types_026_fr_013_task_view_carries_a_stored_task_without_private_state() {
    let wire = body("W-002");
    let view: TaskView = serde_json::from_value(wire.clone()).unwrap();
    let formulation = view.formulation.as_ref().unwrap();
    assert_eq!(formulation.consecutive_stalled, 1);
    assert!(formulation.ageing_at.is_some());
    let task = Task {
        id: view.id.clone(),
        title: view.title.clone(),
        details: view.details.clone(),
        state: view.state,
        project_id: view.project_id.clone(),
        tag_ids: view.tag_ids.clone(),
        due_date: None,
        priority: view.priority,
        waiting_for: None,
        waiting_since: None,
        order_key: view.order_key.clone(),
        source_capture_ids: vec![],
        created_at: view.created_at.clone(),
        updated_at: view.updated_at.clone(),
        completed_at: None,
        cancelled_at: None,
        revision: view.revision.clone(),
        consecutive_stalled_formulations: 1,
        formulation: Some(FormulationClock {
            id: formulation.id.clone(),
            started_at: formulation.started_at.clone(),
            extended_at: None,
            extension_reason: None,
            park_floor_at: None,
        }),
        parked: None,
    };
    let rebuilt = TaskView::new(&task, vec![], vec![]);
    assert_eq!(rebuilt.formulation.as_ref().unwrap().consecutive_stalled, 1);
    assert!(rebuilt.formulation.as_ref().unwrap().ageing_at.is_none());
    assert_eq!(rebuilt.parked, None);
}

// -------------------------------------------------------------- sync-v1 examples

#[test]
fn types_026_fr_002_sync_v1_example_envelope_becomes_a_typed_command() {
    // contracts/sync-v1.md §3.
    let revision =
        json!([{"entity_type": "task", "entity_id": "task-existing-id", "edit_revision": "17"}]);
    let envelope = executable(
        "task.update",
        json!({"title": "Prepare the estimate"}),
        revision,
    );
    let command = DomainCommand::from_envelope(&envelope, &NoReceipts).unwrap();
    assert_eq!(command.preconditions[0].edit_revision.to_u64(), Some(17));
    assert_eq!(command.command_type(), CommandType::TaskUpdate);
    let Command::TaskUpdate(update) = &command.command else {
        panic!("task.update")
    };
    assert_eq!(
        update.title.as_ref().map(Title::as_str),
        Some("Prepare the estimate")
    );
    assert_eq!(update.details, Patch::Unchanged);
}

#[test]
fn types_026_fr_002_after_command_resolves_from_a_receipt_or_waits() {
    let after = json!([{"after_command": {
        "command_id": "01900000-0000-4000-8000-000000000000",
        "entity_type": "task", "entity_id": "task-existing-id"}}]);
    let envelope = executable("task.transition", json!({"action": "complete"}), after);
    let pending = DomainCommand::from_envelope(&envelope, &NoReceipts).unwrap_err();
    assert_eq!(pending.reason, Reason::DependencyPending);
    let receipt: Receipt = serde_json::from_value(json!({
        "command_id": "01900000-0000-4000-8000-000000000000",
        "outcome": "accepted", "has_changes": true, "result_redacted": false,
        "result": null, "error": null, "id_bindings": [],
        "scope_id": SETTINGS_OWNER, "server_now": "2026-10-08T10:00:01Z",
        "server_generation": "generation-example", "commit_seq": "908",
        "result_versions": [{"entity_type": "task", "record_key": ["task-existing-id"],
            "record_version": "24", "edit_revision": "3"}],
        "correlation_id": "opaque-support-reference"
    }))
    .unwrap();
    let receipts = [receipt];
    let resolved = DomainCommand::from_envelope(&envelope, receipts.as_slice()).unwrap();
    assert_eq!(resolved.preconditions[0].edit_revision.as_str(), "3");
    assert_eq!(resolved.preconditions[0].entity_type, EntityType::Task);
}

#[test]
fn types_026_fr_012_unknown_fields_and_versions_are_refused_not_executed() {
    let none = json!([]);
    let unknown = executable(
        "task.update",
        json!({"title": "x", "colour": "red"}),
        none.clone(),
    );
    assert_eq!(
        DomainCommand::from_envelope(&unknown, &NoReceipts)
            .unwrap_err()
            .reason,
        Reason::InvalidPayload
    );
    let mut future = executable("task.update", json!({"title": "x"}), none.clone());
    future.envelope.command_version = 2;
    assert_eq!(
        DomainCommand::from_envelope(&future, &NoReceipts)
            .unwrap_err()
            .reason,
        Reason::UnsupportedCommandVersion
    );
    // The protocol layer already keeps an unknown type out of the executable form.
    let retired = envelope_json("task.delete", json!({}), none);
    assert!(matches!(
        decode_command(&retired),
        Ok(Decoded::Unsupported { .. })
    ));
}

#[test]
fn types_026_fr_002_item_ceilings_are_enforced_by_the_domain_too() {
    let key = json!({"task_id": TASK, "formulation_id": "form_0a1b2c3d4e5f"});
    let mut envelope = executable(
        "review.parks_ack",
        json!({"items": [key.clone()]}),
        json!([]),
    );
    envelope.envelope.payload = object(json!({"items": vec![key; 201]}));
    let err = DomainCommand::from_envelope(&envelope, &NoReceipts).unwrap_err();
    assert_eq!(
        (err.reason, err.field.as_deref()),
        (Reason::TooManyItems, Some("items"))
    );
    // Exactly at the ceiling is accepted by the type itself.
    let max = vec![json!({"task_id": TASK, "formulation_id": "form_0a1b2c3d4e5f"}); 200];
    assert!(
        Command::from_payload(CommandType::ReviewParksAck, &object(json!({"items": max}))).is_ok()
    );
    let bulk = vec![json!({"task_id": TASK, "expected_revision": "1"}); 501];
    assert!(
        Command::from_payload(
            CommandType::ReviewBulkRelease,
            &object(json!({"kind": "restart", "items": bulk}))
        )
        .is_err()
    );
}

#[test]
fn types_026_fr_002_tag_changes_must_be_unique_and_disjoint() {
    let overlap = json!({"add_tag_ids": ["tag_a"], "remove_tag_ids": ["tag_a"]});
    let err = Command::from_payload(CommandType::TaskTags, &object(overlap.clone()))
        .and_then(|c| c.check_shape().map(|()| c))
        .unwrap_err();
    assert_eq!(err.reason, Reason::TagChangesOverlap);
    let nested = Command::from_payload(
        CommandType::TaskUpdate,
        &object(json!({"tag_changes": overlap})),
    )
    .and_then(|c| c.check_shape())
    .unwrap_err();
    assert_eq!(nested.reason, Reason::TagChangesOverlap);
}

// ----------------------------------------------------------------- the catalog

fn sample_payloads() -> Vec<(&'static str, Value)> {
    let id = "00000000-0000-4000-8000-000000000000";
    vec![
        ("project.create", json!({"name": "Flat"})),
        ("project.update", json!({"color": null})),
        ("project.archive", json!({})),
        ("project.unarchive", json!({})),
        ("tag.create", json!({"name": "@home"})),
        ("tag.update", json!({"name": "@office"})),
        ("tag.delete", json!({})),
        ("task.create", json!({"title": "Buy milk"})),
        (
            "task.smart_add",
            json!({"title": "Call Ann",
                "project": {"name": "Flat", "proposed_id": format!("project_{id}")},
                "tags": [{"id": "tag_1"}]}),
        ),
        ("task.update", json!({"title": "x"})),
        (
            "task.tags",
            json!({"add_tag_ids": ["tag_a"], "remove_tag_ids": ["tag_b"]}),
        ),
        ("task.transition", json!({"action": "complete"})),
        ("subtask.create", json!({"task_id": "task_1", "title": "x"})),
        ("subtask.update", json!({"task_id": "task_1", "title": "y"})),
        (
            "subtask.transition",
            json!({"task_id": "task_1", "action": "cancel"}),
        ),
        ("comment.create", json!({"task_id": "task_1", "body": "hi"})),
        (
            "comment.update",
            json!({"task_id": "task_1", "body": "hello"}),
        ),
        (
            "review.decide",
            json!({"decision_id": format!("decision_{id}"), "type": "complete"}),
        ),
        ("review.undo_decision", json!({})),
        (
            "review.auto_park",
            json!({"formulation_id": "form_0a1b2c3d4e5f"}),
        ),
        ("review.explainer_ack", json!({})),
        (
            "review.settings",
            json!({"threshold_days": 14, "onboarded": true}),
        ),
        ("review.parks_ack", json!({"items": []})),
        (
            "review.session_start",
            json!({"mode": "quick", "entry": "list", "origin": "web", "replace_open": false}),
        ),
        (
            "review.session_progress",
            json!({"progress_id": format!("progress_{id}")}),
        ),
        ("review.session_finish", json!({})),
        (
            "review.bulk_release",
            json!({"kind": "restart", "items": []}),
        ),
        ("review.bulk_undo", json!({})),
        (
            "review.consent_grant",
            json!({"provider": "openai", "consent_text_version": 1}),
        ),
        ("review.consent_revoke", json!({"provider": "openai"})),
    ]
}

#[test]
fn types_026_fr_002_every_catalog_command_type_has_a_typed_payload() {
    let schema: Value = serde_json::from_str(SCHEMA).unwrap();
    let schema_types: BTreeSet<String> = schema["$defs"]["CommandType"]["enum"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap().to_owned())
        .collect();
    assert_eq!(schema_types.len(), 30);
    let protocol_types: BTreeSet<String> = CommandType::ALL
        .iter()
        .map(|t| t.as_str().to_owned())
        .collect();
    assert_eq!(protocol_types, schema_types);

    let samples = sample_payloads();
    let sampled: BTreeSet<String> = samples.iter().map(|(t, _)| (*t).to_owned()).collect();
    assert_eq!(sampled, schema_types, "one sample per catalog type");

    for (wire, payload) in samples {
        let command_type = CommandType::from_wire(wire).unwrap();
        let command = Command::from_payload(command_type, &object(payload))
            .unwrap_or_else(|err| panic!("{wire}: {err}"));
        assert_eq!(command.command_type(), command_type, "{wire}");
        command
            .check_shape()
            .unwrap_or_else(|err| panic!("{wire}: {err}"));
        let tagged = serde_json::to_value(&command).unwrap();
        assert_eq!(tagged["type"], wire);
        // Re-typing what a command serializes to gives the same command.
        let again: Command = serde_json::from_value(tagged).unwrap();
        assert_eq!(again, command, "{wire}");
    }
}

#[test]
fn types_026_fr_012_no_catalog_payload_accepts_an_unknown_field() {
    for (wire, payload) in sample_payloads() {
        let mut probed = object(payload);
        probed.insert("__probe__".into(), json!(true));
        let err =
            Command::from_payload(CommandType::from_wire(wire).unwrap(), &probed).expect_err(wire);
        assert_eq!(err.reason, Reason::InvalidPayload, "{wire}");
    }
}

#[test]
fn types_026_fr_002_a_payload_of_another_type_is_not_silently_accepted() {
    // project.create requires `name`; a task payload is not a project payload.
    let err = Command::from_payload(CommandType::ProjectCreate, &object(json!({"title": "x"})))
        .unwrap_err();
    assert_eq!(err.reason, Reason::InvalidPayload);
}

#[test]
fn types_026_fr_002_domain_command_round_trips_flattened() {
    let envelope = executable(
        "comment.create",
        json!({"task_id": "task_1", "body": "hi"}),
        json!([]),
    );
    let command = DomainCommand::from_envelope(&envelope, &NoReceipts).unwrap();
    let wire = serde_json::to_value(&command).unwrap();
    assert_eq!(wire["type"], "comment.create");
    assert_eq!(wire["payload"]["task_id"], "task_1");
    assert_eq!(wire["command_id"], "01900000-0000-4000-8000-000000000001");
    assert_eq!(
        serde_json::from_value::<DomainCommand>(wire).unwrap(),
        command
    );
}
