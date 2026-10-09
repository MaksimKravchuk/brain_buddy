//! Receipts, errors and lookup (026-FR-005, 026-FR-022, 026-SC-002).

use crate::common::{assert_keys_match_schema, common_fields, golden_receipt, with_common};
use bb_protocol::decode;
use bb_protocol::receipt::{CommandLookup, ErrorBody, LookupStatus, Outcome, Receipt};
use bb_protocol::wire::{CommandId, CorrelationId};
use serde_json::{Value, json};

fn rejected_receipt() -> Value {
    let mut rejected = golden_receipt();
    rejected["outcome"] = json!("rejected");
    rejected["has_changes"] = json!(false);
    rejected["commit_seq"] = Value::Null;
    rejected["error"] = json!({"code": "REVISION_CONFLICT", "retryable": false, "message": "Stale",
        "details": {"current_versions": [{"entity_type": "task", "record_key": ["t"], "record_version": "3"}]}});
    rejected
}

#[test]
fn receipt_026_fr_005_golden_receipt_round_trips() {
    let golden = golden_receipt();
    assert_keys_match_schema("Receipt", &golden);
    let receipt: Receipt = decode(&golden.to_string()).unwrap();
    assert_eq!(serde_json::to_value(&receipt).unwrap(), golden);
}

#[test]
fn receipt_026_fr_005_command_identity_is_distinct_from_correlation_id() {
    let receipt: Receipt = decode(&golden_receipt().to_string()).unwrap();
    assert_eq!(
        receipt.command_id.as_str(),
        "01900000-0000-4000-8000-000000000001"
    );
    assert_eq!(
        receipt.common.correlation_id,
        CorrelationId::parse("opaque-support-reference").unwrap()
    );
    assert!(CommandId::parse(receipt.common.correlation_id.as_str()).is_err());
    let mut swapped = golden_receipt();
    swapped["command_id"] = json!("opaque-support-reference");
    assert!(decode::<Receipt>(&swapped.to_string()).is_err());
}

#[test]
fn receipt_026_sc_002_rejection_and_no_op_receipts_keep_their_invariants() {
    let rejected = rejected_receipt();
    let receipt: Receipt = decode(&rejected.to_string()).unwrap();
    assert_eq!(receipt.outcome, Outcome::Rejected);
    assert_eq!(serde_json::to_value(&receipt).unwrap(), rejected);

    let mut no_op = golden_receipt();
    no_op["has_changes"] = json!(false);
    no_op["commit_seq"] = Value::Null;
    assert!(decode::<Receipt>(&no_op.to_string()).is_ok());

    let invalid: Vec<(&str, Value)> = vec![
        ("commit_seq", Value::Null),
        ("error", rejected["error"].clone()),
        ("outcome", json!("pending")),
        ("commit_seq", json!(908)),
        ("commit_seq", json!("0908")),
    ];
    for (field, value) in invalid {
        let mut receipt = golden_receipt();
        receipt[field] = value;
        assert!(decode::<Receipt>(&receipt.to_string()).is_err(), "{field}");
    }
    let mut missing = golden_receipt();
    missing.as_object_mut().unwrap().remove("error");
    assert!(decode::<Receipt>(&missing.to_string()).is_err());
    let mut rejected_with_changes = rejected;
    rejected_with_changes["has_changes"] = json!(true);
    rejected_with_changes["commit_seq"] = json!("9");
    assert!(decode::<Receipt>(&rejected_with_changes.to_string()).is_err());
}

#[test]
fn receipt_026_fr_022_error_details_allow_only_content_free_keys() {
    let mut leaky = rejected_receipt();
    leaky["error"]["details"]["title"] = json!("Prepare the estimate");
    assert!(decode::<Receipt>(&leaky.to_string()).is_err());

    let details = json!({
        "reason": "stale", "current_versions": [], "dependency_ids": ["01900000-0000-4000-8000-000000000002"],
        "epoch_status": "closed", "reset_reason": "feed changed", "retry_after_seconds": 30
    });
    let body = json!({
        "error": {"code": "RESET_REQUIRED", "retryable": false, "message": "Reset", "details": details},
        "correlation_id": "opaque-support-reference"
    });
    assert_keys_match_schema("ErrorBody", &body);
    let decoded: ErrorBody = decode(&body.to_string()).unwrap();
    assert_eq!(serde_json::to_value(&decoded).unwrap(), body);
}

#[test]
fn receipt_026_sc_002_lookup_states_round_trip() {
    let mut terminal = with_common(json!({"status": "terminal"}));
    terminal["receipt"] = golden_receipt();
    let lookup: CommandLookup = decode(&terminal.to_string()).unwrap();
    assert!(matches!(lookup.status, LookupStatus::Terminal { .. }));
    assert_eq!(serde_json::to_value(&lookup).unwrap(), terminal);
    for status in ["pending", "not_found"] {
        let mut observed = common_fields();
        observed["server_now"] = json!("2026-10-08T10:00:01.5+02:00");
        observed["status"] = json!(status);
        observed["command_id"] = json!("01900000-0000-4000-8000-000000000001");
        assert_keys_match_schema("CommonResponse", &common_fields());
        let lookup: CommandLookup = decode(&observed.to_string()).unwrap();
        assert_eq!(serde_json::to_value(&lookup).unwrap(), observed);
    }
    terminal["receipt"]["commit_seq"] = Value::Null;
    assert!(decode::<CommandLookup>(&terminal.to_string()).is_err());
    let unknown = with_common(json!({"status": "lost", "command_id": "x"}));
    assert!(decode::<CommandLookup>(&unknown.to_string()).is_err());
}
