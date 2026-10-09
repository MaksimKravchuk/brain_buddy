//! Feed, transfer, snapshot and hint messages (026-FR-004, 026-FR-006,
//! 026-FR-010). Shapes follow sync-v1 section 11.

use crate::common::{assert_keys_match_schema, with_common};
use bb_protocol::decode;
use bb_protocol::feed::{
    Change, ChangesPage, HintEvent, Operation, SnapshotManifest, SnapshotPage, SnapshotRequest,
    Transaction, TransferManifest, TransferPage, decode_change_stream,
};
use serde_json::{Value, json};

fn upsert(id: &str) -> Value {
    json!({"entity_type": "task", "record_key": [id], "record_version": "24",
        "edit_revision": "18", "operation": "upsert", "value": {"title": "Prepare the estimate"}})
}

fn tombstone(id: &str) -> Value {
    json!({"entity_type": "task", "record_key": [id], "record_version": "25",
        "operation": "tombstone", "value": null})
}

fn transaction(changes: Vec<Value>) -> Value {
    json!({"transaction_id": "tx-1", "commit_seq": "908",
        "source_command_id": "01900000-0000-4000-8000-000000000001", "changes": changes})
}

fn manifest() -> Value {
    json!({"transfer_id": "transfer-1", "transaction_id": "tx-2", "commit_seq": "909",
        "source_command_id": "01900000-0000-4000-8000-000000000001", "page_count": 3,
        "record_count": 900, "total_bytes": 5_000_000, "sha256": "ab".repeat(32),
        "expires_at": "2026-10-08T10:30:00Z", "first_page_token": "page-0", "after_cursor": "cursor-2"})
}

fn changes_page() -> Value {
    with_common(json!({
        "from_cursor": "cursor-0",
        "transactions": [transaction(vec![upsert("a"), tombstone("b")])],
        "has_more": false, "next_cursor": "cursor-1", "high_watermark": "908"
    }))
}

#[test]
fn feed_026_fr_004_changes_page_round_trips() {
    let page = changes_page();
    assert_keys_match_schema("ChangesPage", &page);
    assert_keys_match_schema("Transaction", &page["transactions"][0]);
    assert_keys_match_schema("Change", &page["transactions"][0]["changes"][0]);
    let decoded: ChangesPage = decode(&page.to_string()).unwrap();
    assert_eq!(
        decoded.transactions[0].changes[1].operation,
        Operation::Tombstone
    );
    assert_eq!(serde_json::to_value(&decoded).unwrap(), page);

    let mut empty = changes_page();
    empty["transactions"] = json!([]);
    empty["next_cursor"] = empty["from_cursor"].clone();
    assert!(decode::<ChangesPage>(&empty.to_string()).is_ok());
    let mut empty_but_advanced = empty;
    empty_but_advanced["next_cursor"] = json!("cursor-1");
    assert!(decode::<ChangesPage>(&empty_but_advanced.to_string()).is_err());
}

#[test]
fn feed_026_fr_006_a_transaction_is_complete_and_names_each_record_once() {
    let repeated = transaction(vec![upsert("a"), tombstone("a")]);
    assert!(decode::<Transaction>(&repeated.to_string()).is_err());
    let other_type = transaction(vec![
        upsert("a"),
        json!({"entity_type": "project", "record_key": ["a"], "record_version": "1",
            "operation": "upsert", "value": {}}),
    ]);
    assert!(decode::<Transaction>(&other_type.to_string()).is_ok());
    let empty_key = transaction(vec![
        json!({"entity_type": "review_settings", "record_key": [], "record_version": "1",
            "operation": "upsert", "value": {}}),
    ]);
    assert!(decode::<Transaction>(&empty_key.to_string()).is_ok());
}

#[test]
fn feed_026_fr_006_tombstones_carry_no_value_and_upserts_always_do() {
    let mut tombstone_with_value = tombstone("a");
    tombstone_with_value["value"] = json!({"title": "x"});
    let mut upsert_without_value = upsert("a");
    upsert_without_value["value"] = Value::Null;
    let mut value_missing = tombstone("a");
    value_missing.as_object_mut().unwrap().remove("value");
    for bad in [tombstone_with_value, upsert_without_value, value_missing] {
        assert!(decode::<Change>(&bad.to_string()).is_err(), "{bad}");
    }
    let mut unknown_type = upsert("a");
    unknown_type["entity_type"] = json!("goal");
    assert!(decode::<Change>(&unknown_type.to_string()).is_err());
}

#[test]
fn feed_026_fr_006_oversized_transaction_manifest_stands_alone() {
    let mut page = changes_page();
    page["transactions"] = json!([]);
    page["has_more"] = json!(true);
    page["next_cursor"] = page["from_cursor"].clone();
    page["transaction_manifest"] = manifest();
    assert_keys_match_schema("TransferManifest", &page["transaction_manifest"]);
    let decoded: ChangesPage = decode(&page.to_string()).unwrap();
    assert_eq!(serde_json::to_value(&decoded).unwrap(), page);

    // The cursor stays put until the announced transaction is applied.
    let mut advanced = page.clone();
    advanced["next_cursor"] = json!("cursor-2");
    assert!(decode::<ChangesPage>(&advanced.to_string()).is_err());

    let mut inline_too = page.clone();
    inline_too["transactions"] = changes_page()["transactions"].clone();
    assert!(decode::<ChangesPage>(&inline_too.to_string()).is_err());
    let mut last_page = page.clone();
    last_page["has_more"] = json!(false);
    assert!(decode::<ChangesPage>(&last_page.to_string()).is_err());
    let mut no_pages = manifest();
    no_pages["page_count"] = json!(0);
    assert!(decode::<TransferManifest>(&no_pages.to_string()).is_err());
}

fn byte_page(extra: Value) -> Value {
    let mut page = with_common(json!({
        "page_index": 0, "payload_base64": "W10=", "page_sha256": "cd".repeat(32),
        "has_more": true, "next_page_token": "page-1"
    }));
    page.as_object_mut()
        .unwrap()
        .extend(extra.as_object().unwrap().clone());
    page
}

#[test]
fn feed_026_fr_010_snapshot_manifest_and_pages_round_trip() {
    let request = json!({"scope_id": "scope-example", "projection_schema_version": 2});
    assert_keys_match_schema("SnapshotRequest", &request);
    assert!(decode::<SnapshotRequest>(&request.to_string()).is_ok());
    let mut extra = request.clone();
    extra["cursor"] = json!("c");
    assert!(decode::<SnapshotRequest>(&extra.to_string()).is_err());

    let snapshot = with_common(json!({
        "snapshot_id": "snap-1", "watermark": "908", "cursor": "cursor-908", "page_count": 2,
        "record_count": 40, "total_bytes": 4096, "sha256": "ab".repeat(32),
        "expires_at": "2026-10-08T10:30:00Z", "first_page_token": "page-0"
    }));
    assert_keys_match_schema("SnapshotManifest", &snapshot);
    let decoded: SnapshotManifest = decode(&snapshot.to_string()).unwrap();
    assert_eq!(serde_json::to_value(&decoded).unwrap(), snapshot);
    let mut empty = snapshot.clone();
    empty["page_count"] = json!(0);
    assert!(decode::<SnapshotManifest>(&empty.to_string()).is_err());

    let first = byte_page(json!({"snapshot_id": "snap-1", "watermark": "908"}));
    assert_keys_match_schema("SnapshotPage", &first);
    let decoded: SnapshotPage = decode(&first.to_string()).unwrap();
    assert_eq!(serde_json::to_value(&decoded).unwrap(), first);
    let mut last = first.clone();
    last["page_index"] = json!(1);
    last["has_more"] = json!(false);
    last["next_page_token"] = Value::Null;
    assert!(decode::<SnapshotPage>(&last.to_string()).is_ok());
}

#[test]
fn feed_026_fr_010_byte_pages_pair_has_more_with_the_next_token() {
    let page = byte_page(json!({"transfer_id": "transfer-1"}));
    assert_keys_match_schema("TransferPage", &page);
    assert!(decode::<TransferPage>(&page.to_string()).is_ok());
    let mut dangling = page.clone();
    dangling["next_page_token"] = Value::Null;
    let mut premature = page.clone();
    premature["has_more"] = json!(false);
    let mut missing = page.clone();
    missing.as_object_mut().unwrap().remove("next_page_token");
    for bad in [dangling, premature, missing] {
        assert!(decode::<TransferPage>(&bad.to_string()).is_err());
    }
    let mut skipped = page.clone();
    skipped["page_index"] = json!(-1);
    assert!(decode::<TransferPage>(&skipped.to_string()).is_err());
}

#[test]
fn feed_026_fr_010_assembled_change_stream_is_one_validated_array() {
    let whole = json!([upsert("a"), tombstone("b")]).to_string();
    // A chunk boundary may fall inside a record; only the assembled bytes parse.
    let (head, tail) = whole.as_bytes().split_at(20);
    assert!(decode_change_stream(head).is_err());
    let assembled = [head, tail].concat();
    assert_eq!(decode_change_stream(&assembled).unwrap().len(), 2);

    let mut bad = tombstone("b");
    bad["value"] = json!({"x": 1});
    assert!(decode_change_stream(json!([bad]).to_string().as_bytes()).is_err());
    assert!(decode_change_stream(&[0xff, 0xfe]).is_err());
    assert!(decode_change_stream(b"{}").is_err());
}

#[test]
fn feed_026_fr_004_hint_events_carry_no_content_or_cursor() {
    let hint = json!({"scope_id": "scope-example", "server_generation": "generation-example",
        "feed_generation": "feed-1", "server_now": "2026-10-08T10:00:01Z",
        "correlation_id": "opaque-support-reference"});
    assert_keys_match_schema("HintEvent", &hint);
    let decoded: HintEvent = decode(&hint.to_string()).unwrap();
    assert_eq!(serde_json::to_value(&decoded).unwrap(), hint);
    for leaked in ["cursor", "command_id", "title"] {
        let mut bad = hint.clone();
        bad[leaked] = json!("x");
        assert!(decode::<HintEvent>(&bad.to_string()).is_err(), "{leaked}");
    }
}
