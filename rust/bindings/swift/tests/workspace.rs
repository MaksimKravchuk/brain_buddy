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
        admission_tokens: Vec::new(),
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
    assert!(
        matches!(result, BridgeExecution::Refused { failed_command_id: Some(id), .. } if id == command(2, "").command_id)
    );
    let snapshot = workspace.snapshot().unwrap();
    assert_eq!(snapshot.pending, "0");
    assert_eq!(snapshot.projection_generation, "0");
    assert_eq!(snapshot.records, b"[]");
}

#[test]
fn batch_duplicate_name_refusal_identifies_second_original_command_and_rolls_back() {
    let (workspace, _) = open("batch-name-context");
    let project = |n, name| {
        let mut request = command(n, "");
        request.command_type = "project.create".into();
        request.payload = json!({"name":name}).to_string().into_bytes();
        request
    };
    workspace
        .execute(vec![project(10, "Taken")], context(), operation())
        .unwrap();
    let before = workspace.snapshot().unwrap();
    let first = project(11, "Fresh");
    let second = project(12, "Taken");
    let BridgeExecution::Refused {
        refusal,
        failed_command_id,
    } = workspace
        .execute(vec![first, second.clone()], context(), operation())
        .unwrap()
    else {
        panic!("duplicate name must refuse");
    };
    assert_eq!(refusal.reason, "duplicate_project_name");
    assert_eq!(
        failed_command_id.as_deref(),
        Some(second.command_id.as_str())
    );
    let after = workspace.snapshot().unwrap();
    assert_eq!(after.records, before.records);
    assert_eq!(after.pending, before.pending);
    assert_eq!(after.projection_generation, before.projection_generation);
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

fn detail_query(task_id: &str) -> Vec<u8> {
    json!({"kind":"task_detail","task_id":task_id})
        .to_string()
        .into_bytes()
}

/// Numeric manual keys and duplicate timestamps exercise both tie-breaks;
/// insertion order deliberately differs from the canonical child order.
fn detail_children(
    options: &OpenOptions,
    task_id: &str,
    subtasks: u32,
    comments: u32,
) -> Vec<String> {
    let mut expected = Vec::new();
    let mut store = Store::open(options).unwrap();
    store.write(|tx| {
        for n in (0..subtasks).rev() {
            let id = format!("subtask_{n:03}");
            let order_key = u64::from(n % 7) * 10;
            let row = json!({"id":id,"task_id":task_id,"title":"Child","state":"open","order_key":order_key.to_string(),"revision":"1"});
            tx.execute("INSERT INTO visible_records(workspace_id,record_type,record_key,edit_revision,body) VALUES('local','subtask',?1,'1',CAST(?2 AS BLOB))", [json!([id]).to_string(), row.to_string()])?;
            expected.push((0, order_key, id));
        }
        for n in (0..comments).rev() {
            let id = format!("comment_{n:03}");
            let second = n % 59;
            let row = json!({"id":id,"task_id":task_id,"body":"Comment","actor_id":"device","created_at":format!("2026-10-10T09:00:{second:02}Z"),"edited_at":null,"revision":"1"});
            tx.execute("INSERT INTO visible_records(workspace_id,record_type,record_key,edit_revision,body) VALUES('local','comment',?1,'1',CAST(?2 AS BLOB))", [json!([id]).to_string(), row.to_string()])?;
            expected.push((1, u64::from(second), id));
        }
        tx.execute("UPDATE sync_meta SET projection_generation = projection_generation + 1", [])?;
        Ok(())
    }).unwrap();
    expected.sort();
    expected.into_iter().map(|(_, _, id)| id).collect()
}

#[test]
fn workspace_026_fr_026_detail_has_one_shared_bounded_child_budget() {
    for (subtasks, comments) in [(0, 0), (101, 99), (101, 100)] {
        let (workspace, options) = open(&format!("detail-budget-{subtasks}-{comments}"));
        let BridgeExecution::Saved { results } = workspace
            .execute(vec![command(1, "Parent")], context(), operation())
            .unwrap()
        else {
            panic!("saved parent");
        };
        let task_id = &results[0].entity_id;
        let expected = detail_children(&options, task_id, subtasks, comments);
        for limit in [200, 3] {
            let mut cursor = None;
            let mut seen = Vec::new();
            let mut generation = None;
            loop {
                let BridgeWorkspaceAnswer::Answered { page } = workspace
                    .query(detail_query(task_id), inputs(), limit, cursor)
                    .unwrap()
                else {
                    panic!("detail page");
                };
                assert_eq!(
                    generation.get_or_insert(page.projection_generation.clone()),
                    &page.projection_generation
                );
                let result: Value = serde_json::from_slice(&page.result).unwrap();
                assert_eq!(result["kind"], "task_detail");
                let value = &result["value"];
                assert_eq!(value["id"], task_id.as_str());
                assert_eq!(value["title"], "Parent");
                assert_eq!(value["revision"], "1");
                let subtasks = value["subtasks"].as_array().unwrap();
                let comments = value["comments"].as_array().unwrap();
                assert!(subtasks.len() + comments.len() <= limit as usize);
                seen.extend(
                    subtasks
                        .iter()
                        .chain(comments)
                        .map(|row| row["id"].as_str().unwrap().to_owned()),
                );
                cursor = page.collection_next_cursor;
                if cursor.is_none() {
                    break;
                }
                assert_eq!(subtasks.len() + comments.len(), limit as usize);
            }
            assert_eq!(
                seen, expected,
                "no omissions/duplicates across the child-kind boundary"
            );
        }
        for limit in [0, 201] {
            assert!(matches!(
                workspace
                    .query(detail_query(task_id), inputs(), limit, None)
                    .unwrap(),
                BridgeWorkspaceAnswer::Refused { .. }
            ));
        }
    }
}

#[test]
fn workspace_026_fr_026_detail_continuation_fences_task_inputs_and_generation() {
    let (workspace, options) = open("detail-fences");
    let BridgeExecution::Saved { results } = workspace
        .execute(
            vec![command(1, "Parent"), command(2, "Other")],
            context(),
            operation(),
        )
        .unwrap()
    else {
        panic!("parents");
    };
    let task_id = &results[0].entity_id;
    detail_children(&options, task_id, 1, 1);
    let BridgeWorkspaceAnswer::Answered { page } = workspace
        .query(detail_query(task_id), inputs(), 1, None)
        .unwrap()
    else {
        panic!("detail");
    };
    let cursor = page.collection_next_cursor.unwrap();
    let mut changed_inputs: Value = serde_json::from_slice(&inputs()).unwrap();
    changed_inputs["now"] = json!("2026-10-10T10:00:00Z");
    for (query, inputs) in [
        (detail_query(&results[1].entity_id), inputs()),
        (br#"{"kind":"tags"}"#.to_vec(), inputs()),
        (
            detail_query(task_id),
            changed_inputs.to_string().into_bytes(),
        ),
    ] {
        assert_eq!(
            code(
                workspace
                    .query(query, inputs, 1, Some(cursor.clone()))
                    .unwrap_err()
            ),
            "QUERY_RESTART_REQUIRED"
        );
    }
    for (field, value) in [("offset", json!(1)), ("key", json!("invalid child cursor"))] {
        let mut invalid: Value = serde_json::from_str(&cursor).unwrap();
        invalid[field] = value;
        assert_eq!(
            code(
                workspace
                    .query(
                        detail_query(task_id),
                        inputs(),
                        1,
                        Some(invalid.to_string())
                    )
                    .unwrap_err()
            ),
            "QUERY_RESTART_REQUIRED"
        );
    }
    let mut neighbor = Store::open(&options).unwrap();
    neighbor
        .write(|tx| {
            tx.execute(
                "UPDATE sync_meta SET projection_generation = projection_generation + 1",
                [],
            )?;
            Ok(())
        })
        .unwrap();
    assert_eq!(
        code(
            workspace
                .query(detail_query(task_id), inputs(), 1, Some(cursor))
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

#[test]
fn imported_presentation_carriers_are_individually_readable_and_immutable() {
    let (workspace, options) = open("imported-draft-reads");
    let mut store = Store::open(&options).unwrap();
    store.write(|tx| {
        for (id,kind,key) in [("legacy-local-review","legacy_local_review",None),("legacy-form:project:project_old","review_form_draft",Some("project:project_old")),("legacy-form:project:project_wrong","legacy_local_review",Some("project:project_wrong"))] {
            tx.execute("INSERT INTO drafts(workspace_id,draft_id,editor_kind,record_key,fields,updated_at) VALUES ('local',?1,?2,?3,CAST(?4 AS BLOB),?5)",[id,kind,key.unwrap_or(""),"{\"text\":\"Retained editor text\"}",NOW])?;
        }Ok(())
    }).unwrap();
    let local = workspace
        .load_draft("legacy-local-review".into())
        .unwrap()
        .unwrap();
    assert_eq!(local.editor_kind, "legacy_local_review");
    let form = workspace
        .load_draft("legacy-form:project:project_old".into())
        .unwrap()
        .unwrap();
    assert_eq!(
        serde_json::from_slice::<Value>(&form.fields).unwrap()["text"],
        "Retained editor text"
    );
    assert!(
        workspace
            .load_draft("legacy-form:project:project_wrong".into())
            .unwrap()
            .is_none()
    );
    assert!(
        workspace
            .load_draft("legacy-form:unknown:project_old".into())
            .is_err()
    );
    assert!(workspace.load_draft("legacy-review-base".into()).is_err());
    assert!(workspace.save_draft(local, operation()).is_err());
    assert!(
        workspace
            .delete_draft(form.draft_id.clone(), operation())
            .is_err()
    );
    assert!(workspace.load_draft(form.draft_id).unwrap().is_some());
}

#[test]
fn workspace_026_fr_052_review_form_owned_ports_cancel_and_cross_connection_invalidation() {
    use bb_swift::{BridgeReviewForm, BridgeSourceIdentityRequest};
    let (first, options) = open("review-form-owned");
    let second = workspace(&options);
    let watch = second.subscribe().unwrap();
    let before = watch.next(None, 0).unwrap().unwrap();
    let draft = BridgeReviewForm {
        text: "Private editor text stays local".into(),
        saved_at: "2026-10-10T09:00:00.123456Z".into(),
    };
    let cancelled = operation();
    assert!(cancelled.cancel());
    assert_eq!(
        code(
            first
                .save_review_form(
                    "project:project-owned".into(),
                    None,
                    Some(draft.clone()),
                    NOW.into(),
                    cancelled
                )
                .unwrap_err()
        ),
        "CANCELLED"
    );
    assert_eq!(
        second.review_form_count(NOW.into()).unwrap().live_count,
        "0"
    );
    assert!(watch.next(Some(before.token.clone()), 0).unwrap().is_none());
    let committed = operation();
    let saved = first
        .save_review_form(
            "project:project-owned".into(),
            None,
            Some(draft.clone()),
            NOW.into(),
            committed.clone(),
        )
        .unwrap();
    assert!(committed.is_committed());
    assert!(!committed.cancel());
    let changed = watch.next(Some(before.token), 0).unwrap().unwrap();
    assert!(!changed.changed_kinds.is_empty());
    assert_eq!(changed.projection_generation, saved.projection_generation);
    let loaded = second
        .load_review_form("project:project-owned".into(), NOW.into())
        .unwrap();
    assert_eq!(loaded.source_key, "project:project-owned");
    assert_eq!(loaded.live_count, "1");
    let owned = loaded.draft.unwrap();
    assert_eq!(owned.text, draft.text);
    assert_eq!(owned.saved_at, draft.saved_at);
    assert_eq!(
        second
            .reverse_identities(vec![BridgeSourceIdentityRequest {
                entity_type: "project".into(),
                canonical_id: "project-owned".into()
            }])
            .unwrap()[0]
            .source_id,
        None
    );
    first
        .save_review_form(
            "project:project-owned".into(),
            Some(loaded.source_key),
            None,
            NOW.into(),
            operation(),
        )
        .unwrap();
    assert_eq!(
        second.review_form_count(NOW.into()).unwrap().live_count,
        "0"
    );
    assert!(
        second
            .load_review_form("project:project-owned".into(), NOW.into())
            .unwrap()
            .draft
            .is_none()
    );
}

#[test]
fn original_query_frame_token_is_owned_content_free_and_retry_survives_frame_change() {
    let (workspace, _) = open("original-query-frame");
    let created = match workspace
        .execute(
            vec![command(901, "Private shown task title")],
            context(),
            operation(),
        )
        .unwrap()
    {
        BridgeExecution::Saved { results } => results[0].clone(),
        other => panic!("{other:?}"),
    };
    let page = match workspace
        .query(
            json!({"kind":"task_detail","task_id":created.entity_id})
                .to_string()
                .into_bytes(),
            inputs(),
            200,
            None,
        )
        .unwrap()
    {
        BridgeWorkspaceAnswer::Answered { page } => page,
        other => panic!("{other:?}"),
    };
    let frames: Value = serde_json::from_slice(&page.task_frames).unwrap();
    assert_eq!(frames[0]["token"]["task_id"], created.entity_id);
    assert!(frames[0]["last_open_list"].is_null());
    assert!(
        !String::from_utf8(page.task_frames.clone())
            .unwrap()
            .contains("Private shown task title")
    );
    let token = frames[0]["token"].clone();
    let parsed: bb_client::ShownFrameToken = serde_json::from_value(token.clone()).unwrap();
    assert_eq!(serde_json::to_value(parsed).unwrap(), token);
    let mut edit = command(902, "Preserved authored text");
    edit.command_type = "task.update".into();
    edit.entity_id = Some(created.entity_id.clone());
    edit.preconditions =
        json!([{"entity_type":"task","entity_id":created.entity_id,"edit_revision":"1"}])
            .to_string()
            .into_bytes();
    edit.admission_tokens = json!([token]).to_string().into_bytes();
    assert!(matches!(
        workspace
            .execute(vec![edit.clone()], context(), operation())
            .unwrap(),
        BridgeExecution::Saved { .. }
    ));
    assert!(
        matches!(workspace.execute(vec![edit.clone()],context(),operation()).unwrap(),BridgeExecution::Saved {results} if results[0].replayed)
    );
    edit.command_id = "01900000-0000-4000-8000-000000000903".into();
    edit.preconditions =
        json!([{"entity_type":"task","entity_id":created.entity_id,"edit_revision":"2"}])
            .to_string()
            .into_bytes();
    assert!(
        matches!(workspace.execute(vec![edit],context(),operation()).unwrap(),BridgeExecution::Refused {refusal, ..} if refusal.reason=="formulation_changed")
    );
}

#[test]
fn old_prepared_batch_known_only_port_never_executes_unknown_suffix() {
    use bb_swift::BridgeKnownBatch;
    let (workspace, _) = open("known-only-prepared");
    let known = command(920, "Original prepared command");
    workspace
        .execute(vec![known.clone()], context(), operation())
        .unwrap();
    let mut future = context();
    future.now = "2040-10-10T09:00:00Z".into();
    assert!(
        matches!(workspace.lookup_known_batch(vec![known.clone()],future).unwrap(),BridgeKnownBatch::Known {results} if results.len()==1&&results[0].replayed)
    );
    let unknown = command(921, "Preserved unknown prepared command");
    assert_eq!(
        workspace
            .lookup_known_batch(vec![known.clone(), unknown.clone()], context())
            .unwrap(),
        BridgeKnownBatch::NotKnown
    );
    let mut changed = known;
    changed.payload = json!({"title":"Different known command"})
        .to_string()
        .into_bytes();
    assert_eq!(
        code(
            workspace
                .lookup_known_batch(vec![unknown, changed], context())
                .unwrap_err()
        ),
        "IDEMPOTENCY_KEY_REUSED"
    );
    let snapshot = workspace.snapshot().unwrap();
    assert_eq!(snapshot.pending, "1");
}
