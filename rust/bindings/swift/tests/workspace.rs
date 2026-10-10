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
