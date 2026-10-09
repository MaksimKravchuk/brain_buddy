//! Command envelope codecs against the frozen catalog (026-FR-005, 026-FR-012).

use crate::common::{assert_keys_match_schema, golden_command, schema_enum};
use bb_protocol::CodecError;
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{Decoded, Unsupported, decode_command, decode_stable};
use serde_json::{Value, json};

fn executable(value: &Value) -> Result<Value, CodecError> {
    match decode_command(&value.to_string())? {
        Decoded::Executable(command) => Ok(serde_json::to_value(command).expect("serializes")),
        Decoded::Unsupported { reason, .. } => panic!("unexpected unsupported: {reason:?}"),
    }
}

#[test]
fn command_026_fr_005_golden_envelope_round_trips_unchanged() {
    let golden = golden_command();
    assert_keys_match_schema("CommandEnvelope", &golden);
    assert_eq!(executable(&golden).unwrap(), golden);
}

#[test]
fn command_026_fr_005_after_command_dependency_round_trips() {
    let mut command = golden_command();
    command["preconditions"] = json!([{"after_command": {
        "command_id": "01900000-0000-4000-8000-000000000000", "entity_type": "task", "entity_id": "task-existing-id"
    }}]);
    command["depends_on"] = json!(["01900000-0000-4000-8000-000000000000"]);
    command["supersedes_command_id"] = json!("01900000-0000-4000-8000-0000000000ff");
    assert_keys_match_schema("CommandEnvelope", &command);
    assert_eq!(executable(&command).unwrap(), command);
}

#[test]
fn command_026_fr_012_catalog_matches_frozen_schema_and_every_command_round_trips() {
    let commands: Vec<String> = CommandType::ALL
        .iter()
        .map(|t| t.as_str().to_owned())
        .collect();
    assert_eq!(commands, schema_enum("CommandType"));
    assert_eq!(commands.len(), 30);
    let entities: Vec<String> = EntityType::ALL
        .iter()
        .map(|t| t.as_str().to_owned())
        .collect();
    assert_eq!(entities, schema_enum("EntityType"));
    assert_eq!(entities.len(), 13);
    for command_type in CommandType::ALL {
        let mut command = golden_command();
        command["type"] = json!(command_type.as_str());
        command["payload"] = json!({"task_id": "task-parent"});
        assert_eq!(
            executable(&command).unwrap(),
            command,
            "{}",
            command_type.as_str()
        );
    }
}

#[test]
fn command_026_fr_012_unsupported_execution_keeps_a_readable_recovery_envelope() {
    let cases = [
        ("type", json!("task.delete"), Unsupported::CommandType),
        ("command_version", json!(2), Unsupported::CommandVersion),
        ("protocol_version", json!(2), Unsupported::ProtocolVersion),
    ];
    for (field, value, expected) in cases {
        let mut command = golden_command();
        command[field] = value;
        match decode_command(&command.to_string()).unwrap() {
            Decoded::Unsupported { reason, envelope } => {
                assert_eq!(reason, expected);
                assert_eq!(reason.code(), "UPGRADE_REQUIRED");
                assert_eq!(serde_json::to_value(&envelope).unwrap(), command);
            }
            Decoded::Executable(_) => panic!("{field} must not execute"),
        }
    }
}

#[test]
fn command_026_fr_012_stable_form_reads_retired_commands_without_catalog_checks() {
    let mut retired = golden_command();
    retired["type"] = json!("task.delete");
    retired["command_version"] = json!(7);
    let stable = decode_stable(&retired.to_string()).unwrap();
    assert_eq!(stable.command_type, "task.delete");
    assert_eq!(serde_json::to_value(&stable).unwrap(), retired);
}

#[test]
fn command_026_fr_022_malformed_forms_are_rejected_without_echoing_content() {
    let ok = golden_command().to_string();
    let mutate = |edit: &dyn Fn(&mut Value)| {
        let mut command = golden_command();
        edit(&mut command);
        command.to_string()
    };
    let items = |n: usize| json!(vec![json!({"task_id": "task-x"}); n]);
    let cases = vec![
        ok.replacen("{", "{\"protocol_version\":1,", 1),
        ok.replacen("\"title\"", "\"title\":\"x\",\"title\"", 1),
        ok[..ok.len() - 1].to_owned(),
        format!("{ok} {ok}"),
        mutate(&|c| c["extra"] = json!(true)),
        mutate(&|c| c["local_sequence"] = json!(42)),
        mutate(&|c| c["local_sequence"] = json!("042")),
        mutate(&|c| c["command_id"] = json!("not-a-uuid")),
        mutate(&|c| c["issued_at"] = json!("2026-10-08 10:00")),
        mutate(&|c| c["command_version"] = json!(1.5)),
        mutate(&|c| {
            c.as_object_mut().unwrap().remove("depends_on");
        }),
        mutate(&|c| c["preconditions"][0]["extra"] = json!(1)),
        mutate(&|c| c["preconditions"][0]["edit_revision"] = json!(17)),
        mutate(&|c| {
            c["preconditions"] = json!([{"after_command": {
                "command_id": "01900000-0000-4000-8000-000000000000", "entity_type": "task", "entity_id": "t"
            }}])
        }),
        mutate(&|c| c["type"] = json!("subtask.update")),
        mutate(&|c| {
            c["type"] = json!("task.tags");
            c["payload"] = json!({"add_tag_ids": ["tag_a"], "remove_tag_ids": ["tag_a"]});
        }),
        mutate(&|c| c["payload"]["tag_changes"] = json!({"add_tag_ids": ["tag_a", "tag_a"]})),
        mutate(&|c| {
            c["type"] = json!("review.parks_ack");
            c["payload"] = json!({"items": items(201)});
        }),
        mutate(&|c| {
            c["type"] = json!("review.bulk_release");
            c["payload"] = json!({"items": items(501)});
        }),
    ];
    for (index, case) in cases.iter().enumerate() {
        let error = decode_command(case).expect_err(&format!("case {index} must be rejected"));
        assert_eq!(error.code(), "INVALID_REQUEST");
        assert!(
            !error.to_string().contains("Prepare"),
            "case {index} leaked content"
        );
    }
    for (kind, limit) in [("review.parks_ack", 200), ("review.bulk_release", 500)] {
        let at_limit = mutate(&|c| {
            c["type"] = json!(kind);
            c["payload"] = json!({"items": items(limit)});
        });
        assert!(matches!(
            decode_command(&at_limit),
            Ok(Decoded::Executable(_))
        ));
    }
}

#[test]
fn command_026_fr_005_duplicate_keys_are_a_distinct_error() {
    let ok = golden_command().to_string();
    let duplicated = ok.replacen("\"title\"", "\"title\":\"x\",\"title\"", 1);
    assert_eq!(
        decode_command(&duplicated).unwrap_err(),
        CodecError::DuplicateKey
    );
}
