//! Cross-command dependencies (command-catalog.md "Smart Add bindings",
//! sync-v1.md §3): a Smart Add alias reference in a payload resolves against the
//! retained `id_bindings`, and an `after_command` precondition selects the
//! receipt version of the exact entity it names. Neither rewrites the envelope.

use bb_domain::types::*;
use bb_protocol::command::{CommandEnvelope, Decoded, decode_command};
use bb_protocol::receipt::Receipt;
use serde_json::{Value, json};

const SCOPE: &str = "scope-example";
const SMART_ADD: &str = "01900000-0000-4000-8000-0000000000a0";
const OTHER_CMD: &str = "01900000-0000-4000-8000-0000000000b0";
const PROJECT_ALIAS: &str = "project_00000000-0000-4000-8000-0000000000a1";
const TAG_ALIAS: &str = "tag_00000000-0000-4000-8000-0000000000a2";

fn receipt(command_id: &str, accepted: bool, versions: Value, bindings: Value) -> Receipt {
    let error =
        json!({"code": "REVISION_CONFLICT", "message": "x", "retryable": false, "details": {}});
    serde_json::from_value(json!({
        "command_id": command_id,
        "outcome": if accepted { "accepted" } else { "rejected" },
        "has_changes": accepted,
        "result_redacted": true,
        "result": null,
        "error": if accepted { Value::Null } else { error },
        "id_bindings": bindings,
        "scope_id": SCOPE,
        "server_now": "2026-10-08T10:00:01Z",
        "server_generation": "generation-example",
        "commit_seq": if accepted { json!("908") } else { Value::Null },
        "result_versions": versions,
        "correlation_id": "opaque-support-reference"
    }))
    .expect("receipt")
}

fn smart_add_receipt() -> Receipt {
    receipt(
        SMART_ADD,
        true,
        json!([]),
        json!([
            {"entity_type": "project", "alias_id": PROJECT_ALIAS, "entity_id": "project_resolved"},
            {"entity_type": "tag", "alias_id": TAG_ALIAS, "entity_id": "tag_resolved"}
        ]),
    )
}

fn alias(entity_type: &str, alias_id: &str) -> Value {
    json!({"after_command": SMART_ADD, "alias_id": alias_id, "entity_type": entity_type})
}

fn envelope(
    command_type: &str,
    payload: Value,
    preconditions: Value,
    depends_on: &[&str],
) -> CommandEnvelope {
    let json = json!({
        "protocol_version": 1,
        "command_id": "01900000-0000-4000-8000-000000000001",
        "scope_id": SCOPE,
        "device_id": "device-example",
        "device_epoch": "epoch-example",
        "local_sequence": "42",
        "type": command_type,
        "command_version": 1,
        "entity_id": "task_1",
        "preconditions": preconditions,
        "depends_on": depends_on,
        "issued_at": "2026-10-08T10:00:00Z",
        "payload": payload
    })
    .to_string();
    match decode_command(&json) {
        Ok(Decoded::Executable(envelope)) => envelope,
        other => panic!("{command_type} should decode as executable: {other:?}"),
    }
}

/// An executable envelope that waits on the Smart Add command.
fn dependent(command_type: &str, payload: Value) -> CommandEnvelope {
    envelope(command_type, payload, json!([]), &[SMART_ADD])
}

fn reason(result: Result<DomainCommand, DomainError>) -> Reason {
    result.expect_err("refused").reason
}

#[test]
fn references_026_fr_002_alias_reference_decodes_and_resolves_to_the_bound_entity() {
    let payload = json!({
        "title": "Buy milk",
        "project_id": alias("project", PROJECT_ALIAS),
        "tag_ids": [alias("tag", TAG_ALIAS), "tag_direct"]
    });
    let envelope = dependent("task.create", payload.clone());
    // As the wire carries it, an alias stays an alias.
    let WireCommand::TaskCreate(raw) =
        WireCommand::from_wire_payload(CommandType::TaskCreate, &envelope.envelope.payload)
            .unwrap()
    else {
        panic!("task.create")
    };
    assert!(matches!(raw.project_id, Some(EntityRef::Alias(_))));
    assert!(matches!(raw.tag_ids[1], EntityRef::Direct(_)));
    // The typed command reads the retained binding; the envelope is untouched.
    let receipts = [smart_add_receipt()];
    let command = DomainCommand::from_envelope(&envelope, receipts.as_slice()).unwrap();
    let Command::TaskCreate(create) = &command.command else {
        panic!("task.create")
    };
    assert_eq!(
        create.project_id.as_ref().map(ProjectId::as_str),
        Some("project_resolved")
    );
    let tags: Vec<_> = create.tag_ids.iter().map(TagId::as_str).collect();
    assert_eq!(tags, ["tag_resolved", "tag_direct"]);
    assert_eq!(Value::Object(envelope.envelope.payload.clone()), payload);
    // A resolved command takes direct IDs only; the alias is wire-form.
    let refused = Command::from_payload(CommandType::TaskCreate, &envelope.envelope.payload);
    assert_eq!(refused.unwrap_err().reason, Reason::InvalidPayload);
}

#[test]
fn references_026_fr_002_alias_reference_resolves_in_task_update_and_task_tags() {
    let receipts = [smart_add_receipt()];
    let update = dependent(
        "task.update",
        json!({
            "project_id": alias("project", PROJECT_ALIAS),
            "tag_changes": {"add_tag_ids": [alias("tag", TAG_ALIAS)], "remove_tag_ids": ["tag_old"]}
        }),
    );
    let command = DomainCommand::from_envelope(&update, receipts.as_slice()).unwrap();
    let Command::TaskUpdate(update) = &command.command else {
        panic!("task.update")
    };
    assert_eq!(
        update.project_id,
        Patch::Set(ProjectId::parse("project_resolved").unwrap())
    );
    assert_eq!(
        update.tag_changes.as_ref().unwrap().add_tag_ids[0].as_str(),
        "tag_resolved"
    );

    let tags = dependent(
        "task.tags",
        json!({"add_tag_ids": ["tag_new"], "remove_tag_ids": [alias("tag", TAG_ALIAS)]}),
    );
    let command = DomainCommand::from_envelope(&tags, receipts.as_slice()).unwrap();
    let Command::TaskTags(changes) = &command.command else {
        panic!("task.tags")
    };
    assert_eq!(changes.remove_tag_ids[0].as_str(), "tag_resolved");

    // `null` still clears the project without any receipt.
    let clear = dependent("task.update", json!({"project_id": null}));
    let command = DomainCommand::from_envelope(&clear, &NoReceipts).unwrap();
    assert!(matches!(
        command.command,
        Command::TaskUpdate(TaskUpdate {
            project_id: Patch::Clear,
            ..
        })
    ));
}

#[test]
fn references_026_fr_002_unresolved_alias_waits_then_resolves_unchanged() {
    let envelope = dependent(
        "task.create",
        json!({"title": "Buy milk", "project_id": alias("project", PROJECT_ALIAS)}),
    );
    assert_eq!(
        reason(DomainCommand::from_envelope(&envelope, &NoReceipts)),
        Reason::DependencyPending
    );
    // Another command's receipt does not settle it.
    let unrelated = receipt(OTHER_CMD, true, json!([]), json!([]));
    let receipts = [unrelated.clone()];
    assert_eq!(
        reason(DomainCommand::from_envelope(&envelope, receipts.as_slice())),
        Reason::DependencyPending
    );
    // The same immutable envelope resolves once the receipt is retained.
    let receipts = [unrelated, smart_add_receipt()];
    assert!(DomainCommand::from_envelope(&envelope, receipts.as_slice()).is_ok());
}

#[test]
fn references_026_fr_002_alias_reference_is_scoped_typed_and_listed() {
    let receipts = [smart_add_receipt()];
    let project = |reference: Value| json!({"title": "x", "project_id": reference});
    // Not in depends_on: the contract requires it.
    let unlisted = envelope(
        "task.create",
        project(alias("project", PROJECT_ALIAS)),
        json!([]),
        &[],
    );
    let err = DomainCommand::from_envelope(&unlisted, receipts.as_slice()).unwrap_err();
    assert_eq!(
        (err.reason, err.field.as_deref()),
        (Reason::InvalidPayload, Some("depends_on"))
    );
    // A tag alias cannot stand in a project field, and no extra key rides along.
    for bad in [
        alias("tag", TAG_ALIAS),
        alias("task", PROJECT_ALIAS),
        json!({"after_command": SMART_ADD, "alias_id": PROJECT_ALIAS}),
        json!({"after_command": SMART_ADD, "alias_id": PROJECT_ALIAS, "entity_type": "project", "name": "x"}),
        json!(7),
    ] {
        let envelope = dependent("task.create", project(bad.clone()));
        assert_eq!(
            reason(DomainCommand::from_envelope(&envelope, receipts.as_slice())),
            Reason::InvalidPayload,
            "{bad}"
        );
    }
    // The binding is typed: a tag binding is not a project binding.
    let swapped = dependent("task.create", project(alias("project", TAG_ALIAS)));
    assert_eq!(
        reason(DomainCommand::from_envelope(&swapped, receipts.as_slice())),
        Reason::DependencyRejected
    );
}

#[test]
fn references_026_fr_002_rejected_dependency_is_terminal_not_pending() {
    let envelope = dependent(
        "task.create",
        json!({"title": "x", "project_id": alias("project", PROJECT_ALIAS)}),
    );
    let rejected = [receipt(SMART_ADD, false, json!([]), json!([]))];
    assert_eq!(
        reason(DomainCommand::from_envelope(&envelope, rejected.as_slice())),
        Reason::DependencyRejected
    );
}

#[test]
fn references_026_fr_002_alias_resolving_into_an_overlap_is_refused() {
    let envelope = dependent(
        "task.tags",
        json!({"add_tag_ids": [alias("tag", TAG_ALIAS)], "remove_tag_ids": ["tag_resolved"]}),
    );
    let receipts = [smart_add_receipt()];
    assert_eq!(
        reason(DomainCommand::from_envelope(&envelope, receipts.as_slice())),
        Reason::TagChangesOverlap
    );
}

fn after(entity_type: &str, entity_id: &str) -> Value {
    json!({"after_command": {
        "command_id": OTHER_CMD, "entity_type": entity_type, "entity_id": entity_id}})
}

/// One accepted command that changed a task, a project and a tag; the tag
/// shares the task's key text, and the subtask has no edit revision.
fn multi_record_receipt() -> Receipt {
    receipt(
        OTHER_CMD,
        true,
        json!([
            {"entity_type": "task", "record_key": ["task_1"], "record_version": "40", "edit_revision": "5"},
            {"entity_type": "project", "record_key": ["project_1"], "record_version": "41", "edit_revision": "7"},
            {"entity_type": "tag", "record_key": ["task_1"], "record_version": "42", "edit_revision": "9"},
            {"entity_type": "subtask", "record_key": ["subtask_1"], "record_version": "43"}
        ]),
        json!([]),
    )
}

fn preconditions(
    preconditions: Vec<Value>,
    receipts: &[Receipt],
) -> Result<Vec<(EntityType, String)>, DomainError> {
    let envelope = envelope(
        "task.update",
        json!({"title": "x"}),
        Value::Array(preconditions),
        &[OTHER_CMD],
    );
    DomainCommand::from_envelope(&envelope, receipts).map(|command| {
        command
            .preconditions
            .iter()
            .map(|check| (check.entity_type, check.edit_revision.as_str().to_owned()))
            .collect()
    })
}

#[test]
fn references_026_fr_002_after_command_selects_the_version_of_the_exact_entity() {
    let receipts = [multi_record_receipt()];
    let resolved = preconditions(
        vec![
            after("project", "project_1"),
            after("task", "task_1"),
            after("tag", "task_1"),
        ],
        &receipts,
    )
    .unwrap();
    assert_eq!(
        resolved,
        [
            (EntityType::Project, "7".to_owned()),
            (EntityType::Task, "5".to_owned()),
            (EntityType::Tag, "9".to_owned()),
        ]
    );
}

#[test]
fn references_026_fr_002_after_command_for_an_entity_the_receipt_lacks_is_refused() {
    let receipts = [multi_record_receipt()];
    for (entity_type, entity_id) in [
        ("task", "task_other"),
        ("project", "task_1"),
        ("tag", "project_1"),
        // A version without an edit revision cannot satisfy a revision check.
        ("subtask", "subtask_1"),
    ] {
        let err = preconditions(vec![after(entity_type, entity_id)], &receipts).unwrap_err();
        assert_eq!(err.reason, Reason::DependencyRejected, "{entity_type}");
        let (found_type, key) = err.entity.expect("names the entity");
        assert_eq!(
            (found_type.as_str(), key),
            (entity_type, vec![entity_id.to_owned()])
        );
    }
    // A predecessor with no terminal receipt yet is retryable, not refused.
    let err = preconditions(vec![after("task", "task_1")], &[]).unwrap_err();
    assert_eq!(err.reason, Reason::DependencyPending);
}
