//! Golden messages and helpers that read the frozen schema.

use serde_json::{Value, json};

const SCHEMA: &str =
    include_str!("../../../../../specs/026-rust-core-sync/contracts/sync-v1.schema.json");

pub fn schema() -> Value {
    serde_json::from_str(SCHEMA).expect("schema parses")
}

pub fn schema_enum(name: &str) -> Vec<String> {
    serde_json::from_value(schema()["$defs"][name]["enum"].clone()).expect("enum list")
}

/// Property names and required names of a schema definition, following `$ref`.
fn shape(def: &str, properties: &mut Vec<String>, required: &mut Vec<String>) {
    let schema = schema();
    let body = &schema["$defs"][def];
    assert!(!body.is_null(), "schema has no definition {def}");
    if let Some(parent) = body["$ref"].as_str() {
        shape(parent.trim_start_matches("#/$defs/"), properties, required);
    }
    if let Some(map) = body["properties"].as_object() {
        properties.extend(map.keys().cloned());
    }
    if let Some(list) = body["required"].as_array() {
        required.extend(list.iter().filter_map(|v| v.as_str().map(str::to_owned)));
    }
}

/// Asserts `value` carries every required key of `def` and no key the schema
/// does not define: the codecs add no field the contract lacks.
pub fn assert_keys_match_schema(def: &str, value: &Value) {
    let (mut properties, mut required) = (Vec::new(), Vec::new());
    shape(def, &mut properties, &mut required);
    let object = value.as_object().expect("object");
    for key in &required {
        assert!(object.contains_key(key), "{def}: missing required {key}");
    }
    for key in object.keys() {
        assert!(properties.contains(key), "{def}: key {key} not in schema");
    }
}

pub fn golden_command() -> Value {
    json!({
        "protocol_version": 1,
        "command_id": "01900000-0000-4000-8000-000000000001",
        "scope_id": "scope-example",
        "device_id": "device-example",
        "device_epoch": "epoch-example",
        "local_sequence": "42",
        "type": "task.update",
        "command_version": 1,
        "entity_id": "task-existing-id",
        "preconditions": [
            {"entity_type": "task", "entity_id": "task-existing-id", "edit_revision": "17"}
        ],
        "depends_on": [],
        "issued_at": "2026-10-08T10:00:00Z",
        "payload": {"title": "Prepare the estimate"}
    })
}

pub fn golden_receipt() -> Value {
    json!({
        "command_id": "01900000-0000-4000-8000-000000000001",
        "outcome": "accepted",
        "has_changes": true,
        "result_redacted": false,
        "result": null,
        "error": null,
        "id_bindings": [],
        "scope_id": "scope-example",
        "server_now": "2026-10-08T10:00:01Z",
        "server_generation": "generation-example",
        "commit_seq": "908",
        "result_versions": [
            {"entity_type": "task", "record_key": ["task-existing-id"], "edit_revision": "18", "record_version": "24"}
        ],
        "correlation_id": "opaque-support-reference"
    })
}

pub fn common_fields() -> Value {
    json!({
        "correlation_id": "opaque-support-reference",
        "scope_id": "scope-example",
        "server_generation": "generation-example",
        "server_now": "2026-10-08T10:00:01Z"
    })
}

/// `body` merged over the common response fields.
pub fn with_common(body: Value) -> Value {
    let mut merged = common_fields();
    merged
        .as_object_mut()
        .unwrap()
        .extend(body.as_object().unwrap().clone());
    merged
}
