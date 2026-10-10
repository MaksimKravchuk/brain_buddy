//! Actual owned UniFFI-facing values and durable completion/lifecycle behavior.
use bb_client::{OpenOptions, Store};
use bb_swift::{
    BridgeError, BridgeExecuteContext, BridgeExecution, BridgeOperation, BridgeRuntime,
    BridgeStoreRequest, BridgeWorkspace, BridgeWorkspaceAnswer, BridgeWorkspaceCommand,
};
use serde_json::{Value, json};
use std::{fs, sync::Arc, time::Duration};

const NOW: &str = "2026-10-10T09:00:00Z";

fn open(name: &str) -> (Arc<BridgeWorkspace>, OpenOptions) {
    let directory =
        std::env::temp_dir().join(format!("bb-workspace-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    let options = OpenOptions {
        path: directory.join("store.sqlite3"),
        workspace_id: "local".into(),
        busy_timeout: Duration::from_secs(2),
    };
    (workspace(&options), options)
}

fn workspace(options: &OpenOptions) -> Arc<BridgeWorkspace> {
    BridgeRuntime::new(1)
        .unwrap()
        .open_store(BridgeStoreRequest {
            workspace_id: options.workspace_id.clone(),
            database_path: options.path.to_string_lossy().into_owned(),
            busy_timeout_ms: 2_000,
        })
        .unwrap()
}

fn context() -> BridgeExecuteContext {
    BridgeExecuteContext { now: NOW.into(), time_zone: "UTC".into(), actor_id: "device".into(), policy: json!({
        "weekly_review": false, "navigator_provider": null, "navigator_available": false, "consent_text_version": 1,
    }).to_string().into_bytes() }
}

fn command(n: u64, title: &str) -> BridgeWorkspaceCommand {
    BridgeWorkspaceCommand {
        command_id: format!("01900000-0000-4000-8000-{n:012}"),
        command_type: "task.create".into(),
        entity_id: None,
        payload: json!({"title":title}).to_string().into_bytes(),
        preconditions: b"[]".to_vec(),
        depends_on: vec![],
    }
}

fn operation() -> Arc<BridgeOperation> {
    Arc::new(BridgeOperation::new())
}
fn code(error: BridgeError) -> String {
    let BridgeError::Failed { code, .. } = error;
    code
}

fn list(after: Option<Value>) -> Vec<u8> {
    json!({"kind":"task_list", "list":"inbox", "project_id":null, "tag_id":null, "sort":"manual",
        "page":{"limit":2,"after":after}})
    .to_string()
    .into_bytes()
}

fn inputs() -> Vec<u8> {
    let context = context();
    json!({"now":NOW,"device_zone":"UTC","policy":serde_json::from_slice::<Value>(&context.policy).unwrap()}).to_string().into_bytes()
}

#[test]
fn workspace_026_fr_001_batch_refusal_preserves_everything() {
    let (workspace, _) = open("refusal");
    let result = workspace
        .execute(
            vec![command(1, "User draft"), command(2, "")],
            context(),
            operation(),
        )
        .unwrap();
    assert!(matches!(result, BridgeExecution::Refused { .. }));
    let snapshot = workspace.snapshot().unwrap();
    assert_eq!(snapshot.pending, "0");
    assert_eq!(snapshot.projection_generation, "0");
    assert_eq!(snapshot.records, b"[]");
}

#[test]
fn workspace_026_fr_001_cancel_wins_before_commit_and_loses_after_commit() {
    let (workspace, options) = open("cancel");
    let cancelled = operation();
    assert!(cancelled.cancel());
    assert_eq!(
        code(
            workspace
                .execute(vec![command(1, "Draft")], context(), cancelled)
                .unwrap_err()
        ),
        "CANCELLED"
    );
    assert_eq!(workspace.snapshot().unwrap().pending, "0");
    let committed = operation();
    let saved = workspace
        .execute(vec![command(1, "Draft")], context(), committed.clone())
        .unwrap();
    assert!(committed.is_committed());
    assert!(!committed.cancel());
    workspace.close().unwrap();
    workspace.close().unwrap();
    let reopened = crate::workspace(&options);
    let retry = reopened
        .execute(vec![command(1, "Draft")], context(), operation())
        .unwrap();
    let (BridgeExecution::Saved { results: saved }, BridgeExecution::Saved { results: retry }) =
        (saved, retry)
    else {
        panic!("saved");
    };
    assert!(retry[0].replayed);
    assert_eq!(saved[0].entity_id, retry[0].entity_id);
    assert_eq!(saved[0].local_sequence, retry[0].local_sequence);
    assert_eq!(reopened.snapshot().unwrap().pending, "1");
}

#[test]
fn workspace_026_fr_026_lists_are_bounded_and_generation_bound() {
    let (workspace, options) = open("pages");
    workspace
        .execute(
            (1..=5).map(|n| command(n, "Task")).collect(),
            context(),
            operation(),
        )
        .unwrap();
    let BridgeWorkspaceAnswer::Answered { page } =
        workspace.query(list(None), inputs(), 200, None).unwrap()
    else {
        panic!("page");
    };
    let value: Value = serde_json::from_slice(&page.result).unwrap();
    assert_eq!(value["value"]["items"].as_array().unwrap().len(), 2);
    let cursor = value["value"]["next_cursor"].clone();
    let BridgeWorkspaceAnswer::Answered { page: next } = workspace
        .query(list(Some(cursor.clone())), inputs(), 200, None)
        .unwrap()
    else {
        panic!("page");
    };
    assert_eq!(next.projection_generation, page.projection_generation);
    let next: Value = serde_json::from_slice(&next.result).unwrap();
    assert_ne!(
        value["value"]["items"][0]["id"],
        next["value"]["items"][0]["id"]
    );
    // A neighboring widget changes the durable generation, not this handle's cache.
    crate::workspace(&options)
        .execute(vec![command(6, "Widget")], context(), operation())
        .unwrap();
    assert_eq!(
        code(
            workspace
                .query(list(Some(cursor)), inputs(), 200, None)
                .unwrap_err()
        ),
        "QUERY_RESTART_REQUIRED"
    );
}

#[test]
fn workspace_026_fr_026_catalog_collections_are_bounded_and_query_bound() {
    let (workspace, _) = open("catalog-pages");
    let commands = (1..=5)
        .map(|n| {
            let mut request = command(n, "unused");
            request.command_type = "tag.create".into();
            request.payload = json!({"name":format!("Tag {n}")}).to_string().into_bytes();
            request
        })
        .collect();
    workspace.execute(commands, context(), operation()).unwrap();
    let tags = br#"{"kind":"tags"}"#.to_vec();
    let BridgeWorkspaceAnswer::Answered { page } =
        workspace.query(tags.clone(), inputs(), 2, None).unwrap()
    else {
        panic!("tags");
    };
    let value: Value = serde_json::from_slice(&page.result).unwrap();
    assert_eq!(value["value"].as_array().unwrap().len(), 2);
    let cursor = page.collection_next_cursor.clone().unwrap();
    let BridgeWorkspaceAnswer::Answered { page: next } = workspace
        .query(tags, inputs(), 2, Some(cursor.clone()))
        .unwrap()
    else {
        panic!("tags");
    };
    let next: Value = serde_json::from_slice(&next.result).unwrap();
    assert_ne!(value["value"][0], next["value"][0]);
    assert_eq!(
        code(
            workspace
                .query(
                    br#"{"kind":"projects","filter":"active"}"#.to_vec(),
                    inputs(),
                    2,
                    Some(cursor)
                )
                .unwrap_err()
        ),
        "QUERY_RESTART_REQUIRED"
    );
}

#[test]
fn workspace_026_fr_004_issues_and_status_invalidate_without_projection_change() {
    let (workspace, options) = open("subscription");
    let subscription = workspace.subscribe().unwrap();
    let initial = subscription.next(None, 0).unwrap().unwrap();
    assert!(
        subscription
            .next(Some(initial.token.clone()), 0)
            .unwrap()
            .is_none()
    );
    let mut neighbor = Store::open(&options).unwrap();
    neighbor.write(|tx| {
        tx.execute("INSERT INTO sync_issues(workspace_id,issue_id,command_id,reason,local_intent,created_at)
            VALUES('local','safe-issue','safe-command','OUTCOME_UNKNOWN',X'7B7D','2026-10-10T09:00:00Z')",[])?;
        tx.execute("UPDATE sync_meta SET session_generation = session_generation + 1",[])?;
        Ok(())
    }).unwrap();
    let changed = subscription.next(Some(initial.token), 0).unwrap().unwrap();
    assert_eq!(changed.projection_generation, initial.projection_generation);
    assert!(changed.changed_kinds.is_empty());
    assert!(changed.issues_changed);
    assert!(changed.sync_status_changed);
    subscription.cancel();
    assert_eq!(
        code(subscription.next(Some(changed.token), 0).unwrap_err()),
        "CANCELLED"
    );
    let another = workspace.subscribe().unwrap();
    workspace.close().unwrap();
    assert_eq!(code(another.next(None, 0).unwrap_err()), "WORKSPACE_CLOSED");
}

#[test]
fn workspace_026_fr_022_errors_have_no_authored_payload() {
    let (workspace, _) = open("safe-error");
    let mut request = command(1, "SECRET DRAFT");
    request.payload = b"SECRET DRAFT".to_vec();
    let error = workspace
        .execute(vec![request], context(), operation())
        .unwrap_err();
    assert!(!format!("{error:?}").contains("SECRET"));
    assert_eq!(code(error), "INVALID_REQUEST");
}

#[test]
fn workspace_026_fr_009_draft_proposal_fences_generation_and_cursor_fences_frozen_inputs() {
    let (workspace, _) = open("smart-fence");
    let draft = json!({"text":"Call Sam #phone","list":"next"})
        .to_string()
        .into_bytes();
    let BridgeWorkspaceAnswer::Answered { page } =
        workspace.smart_add_resolve(draft.clone()).unwrap()
    else {
        panic!("resolution")
    };
    let result: Value = serde_json::from_slice(&page.result).unwrap();
    assert_eq!(result["title"], "Call Sam");
    assert_eq!(result["tags"][0]["type"], "new");
    workspace
        .execute(
            vec![command(1, "One"), command(2, "Two"), command(3, "Three")],
            context(),
            operation(),
        )
        .unwrap();
    assert_eq!(
        code(
            workspace
                .smart_add_propose(
                    draft.clone(),
                    b"{\"tags\":[\"tag-phone\"]}".to_vec(),
                    page.projection_generation
                )
                .unwrap_err()
        ),
        "QUERY_RESTART_REQUIRED"
    );
    let BridgeWorkspaceAnswer::Answered { page } = workspace
        .smart_add_propose(draft, b"{\"tags\":[\"tag-phone\"]}".to_vec(), "3".into())
        .unwrap()
    else {
        panic!("proposal")
    };
    let payload: Value = serde_json::from_slice(&page.result).unwrap();
    assert_eq!(payload["tags"][0]["proposed_id"], "tag-phone");
    let BridgeWorkspaceAnswer::Answered { page } =
        workspace.query(list(None), inputs(), 200, None).unwrap()
    else {
        panic!("list")
    };
    let result: Value = serde_json::from_slice(&page.result).unwrap();
    let after = result["value"]["next_cursor"].clone();
    let mut changed: Value = serde_json::from_slice(&inputs()).unwrap();
    changed["now"] = json!("2026-10-10T10:00:00Z");
    assert_eq!(
        code(
            workspace
                .query(
                    list(Some(after)),
                    serde_json::to_vec(&changed).unwrap(),
                    200,
                    None
                )
                .unwrap_err()
        ),
        "QUERY_RESTART_REQUIRED"
    );
}

#[test]
fn workspace_026_fr_013_touched_identity_lookup_prefers_owned_canonical_and_proven_alias() {
    use bb_swift::BridgeIdentityRequest;
    let (workspace, options) = open("identity-proof");
    let mut store = Store::open(&options).unwrap();
    store.write(|tx| {
        tx.execute("INSERT INTO identity_aliases(workspace_id,entity_type,old_local_id,server_id,provenance) VALUES ('local','task','old-task','server-task','import')",[])?;
        Ok(())
    }).unwrap();
    let bindings = workspace
        .resolve_identities(vec![
            BridgeIdentityRequest {
                entity_type: "task".into(),
                local_id: "old-task".into(),
            },
            BridgeIdentityRequest {
                entity_type: "project".into(),
                local_id: "old-task".into(),
            },
        ])
        .unwrap();
    assert_eq!(bindings[0].canonical_id.as_deref(), Some("server-task"));
    assert_eq!(bindings[1].canonical_id, None);
    let BridgeExecution::Saved { results } = workspace
        .execute(vec![command(1, "One")], context(), operation())
        .unwrap()
    else {
        panic!("save")
    };
    let id = results[0].entity_id.clone();
    let bindings = workspace
        .resolve_identities(vec![BridgeIdentityRequest {
            entity_type: "task".into(),
            local_id: id.clone(),
        }])
        .unwrap();
    assert_eq!(bindings[0].canonical_id, Some(id));
    assert_eq!(
        code(
            workspace
                .resolve_identities(vec![
                    BridgeIdentityRequest {
                        entity_type: "task".into(),
                        local_id: "old-task".into()
                    };
                    201
                ])
                .unwrap_err()
        ),
        "INVALID_REQUEST"
    );
}

#[test]
fn workspace_026_fr_001_prepared_gesture_draft_survives_reopen_and_cancel_preserves_it() {
    use bb_swift::BridgeWorkspaceDraft;
    let (workspace, options) = open("gesture-draft");
    let draft = BridgeWorkspaceDraft {draft_id:"runtime:prepared:gesture-1".into(),editor_kind:"runtime_gesture".into(),record_type:Some("task".into()),record_key:Some("[\"task-1\"]".into()),base_revision:Some("4".into()),fields:json!({"original_command_id":"01900000-0000-4000-8000-000000000111","context":{"now":NOW},"payload":{"title":"Authored draft"}}).to_string().into_bytes(),updated_at:NOW.into()};
    let cancelled = operation();
    cancelled.cancel();
    assert_eq!(
        code(workspace.save_draft(draft.clone(), cancelled).unwrap_err()),
        "CANCELLED"
    );
    assert!(
        workspace
            .load_draft(draft.draft_id.clone())
            .unwrap()
            .is_none()
    );
    let committed = operation();
    workspace
        .save_draft(draft.clone(), committed.clone())
        .unwrap();
    assert!(committed.is_committed());
    assert!(!committed.cancel());
    workspace.close().unwrap();
    let reopened = crate::workspace(&options);
    let saved = reopened
        .load_draft(draft.draft_id.clone())
        .unwrap()
        .unwrap();
    assert_eq!(saved.fields, draft.fields);
    assert_eq!(saved.base_revision, draft.base_revision);
    let cancelled = operation();
    cancelled.cancel();
    assert_eq!(
        code(
            reopened
                .delete_draft(draft.draft_id.clone(), cancelled)
                .unwrap_err()
        ),
        "CANCELLED"
    );
    assert!(
        reopened
            .load_draft(draft.draft_id.clone())
            .unwrap()
            .is_some()
    );
    reopened
        .delete_draft(draft.draft_id.clone(), operation())
        .unwrap();
    assert!(reopened.load_draft(draft.draft_id).unwrap().is_none());
    assert_eq!(
        code(
            reopened
                .delete_draft("legacy-task-local:task-1".into(), operation())
                .unwrap_err()
        ),
        "VALIDATION_FAILED"
    );
}

#[test]
fn workspace_026_fr_004_issue_pages_fence_independent_changes_and_not_found_has_generation() {
    let (workspace, options) = open("issue-pages");
    let mut store = Store::open(&options).unwrap();
    store.write(|tx| {
        for id in ["issue-1","issue-2"] {
            tx.execute("INSERT INTO sync_issues(workspace_id,issue_id,command_id,reason,local_intent,dependent_ids,resolution,created_at) VALUES ('local',?1,'01900000-0000-4000-8000-000000000199','REVISION_CONFLICT',CAST('{}' AS BLOB),'[]','open',?2)",[id,NOW])?;
        }
        Ok(())
    }).unwrap();
    let BridgeWorkspaceAnswer::Answered { page } = workspace.workspace_issues(1, None).unwrap()
    else {
        panic!("page")
    };
    let data: Value = serde_json::from_slice(&page.result).unwrap();
    assert_eq!(data["value"].as_array().unwrap().len(), 1);
    store
        .write(|tx| {
            tx.execute(
                "UPDATE sync_issues SET reason='ENTITY_DELETED' WHERE issue_id='issue-1'",
                [],
            )?;
            Ok(())
        })
        .unwrap();
    assert_eq!(
        code(
            workspace
                .workspace_issues(1, page.collection_next_cursor)
                .unwrap_err()
        ),
        "QUERY_RESTART_REQUIRED"
    );
    let status: Value = serde_json::from_slice(&workspace.sync_status().unwrap()).unwrap();
    assert_eq!(status["open_issues"], "2");
    let answer = workspace
        .query(
            json!({"kind":"task_detail","task_id":"missing"})
                .to_string()
                .into_bytes(),
            inputs(),
            200,
            None,
        )
        .unwrap();
    let BridgeWorkspaceAnswer::Refused {
        refusal,
        projection_generation,
    } = answer
    else {
        panic!("refusal")
    };
    assert_eq!(refusal.reason, "not_found");
    assert_eq!(projection_generation.as_deref(), Some("0"));
}

#[test]
fn exact_public_record_reads_are_bounded_typed_missing_and_generation_bound() {
    use bb_swift::BridgeRecordRequest;
    let (workspace, _) = open("public-records");
    let BridgeExecution::Saved { results } = workspace
        .execute(vec![command(90, "Owned row")], context(), operation())
        .unwrap()
    else {
        panic!()
    };
    let request = |kind: &str, key: Value| BridgeRecordRequest {
        entity_type: kind.into(),
        record_key: key.to_string().into_bytes(),
    };
    let BridgeWorkspaceAnswer::Answered { page } = workspace
        .records(vec![
            request("task", json!([results[0].entity_id])),
            request("task", json!(["task_missing"])),
        ])
        .unwrap()
    else {
        panic!()
    };
    assert_eq!(page.projection_generation, results[0].projection_generation);
    let result: Value = serde_json::from_slice(&page.result).unwrap();
    assert_eq!(result["value"][0]["entity_type"], "task");
    assert_eq!(result["value"][0]["value"]["title"], "Owned row");
    assert!(result["value"][1].is_null());
    assert_eq!(
        code(
            workspace
                .records(vec![request("sync_meta", json!([]))])
                .unwrap_err()
        ),
        "INVALID_REQUEST"
    );
    for items in [
        vec![request("task", json!([]))],
        vec![request(
            "review_receipt",
            json!(["task_missing", "invalid_kind"]),
        )],
        (0..201)
            .map(|_| request("task", json!(["task_missing"])))
            .collect(),
    ] {
        assert!(matches!(
            workspace.records(items).unwrap(),
            BridgeWorkspaceAnswer::Refused { .. }
        ));
    }
}

#[test]
fn native_open_list_uses_durable_origin_without_host_facts() {
    let (workspace, options) = open("origin-native");
    let BridgeExecution::Saved { results } = workspace
        .execute(vec![command(92, "Finish this")], context(), operation())
        .unwrap()
    else {
        panic!()
    };
    let mut complete = command(93, "");
    complete.command_type = "task.transition".into();
    complete.entity_id = Some(results[0].entity_id.clone());
    complete.payload = b"{\"action\":\"complete\"}".to_vec();
    complete.preconditions =
        json!([{"entity_type":"task","entity_id":results[0].entity_id,"edit_revision":"1"}])
            .to_string()
            .into_bytes();
    assert!(matches!(
        workspace
            .execute(vec![complete], context(), operation())
            .unwrap(),
        BridgeExecution::Saved { .. }
    ));
    workspace.close().unwrap();
    let workspace = crate::workspace(&options);
    let query=json!({"kind":"list_mode","mode":{"type":"open_list","list":"inbox"},"options":{"show_completed":true},"page":{"limit":1}}).to_string().into_bytes();
    let BridgeWorkspaceAnswer::Answered { page } =
        workspace.query(query, inputs(), 1, None).unwrap()
    else {
        panic!()
    };
    let result: Value = serde_json::from_slice(&page.result).unwrap();
    assert_eq!(
        result["value"]["sections"][0]["items"][0]["id"],
        results[0].entity_id
    );
}
