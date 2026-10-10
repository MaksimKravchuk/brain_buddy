//! The legacy import through the Apple bridge (spec 026 T041): the request and report
//! records `RustBridgeRuntime.importLegacyStore` maps, and the typed, content-free errors
//! it throws. The import itself is tested in `bb-client`; these tests are about the
//! boundary: owned values, the `guarded` seam, error codes and no payload text.

use bb_swift::{
    BridgeError, BridgeImportCounts, BridgeImportRequest, BridgeLegacyAlias, BridgeLegacyAnswer,
    BridgeLegacyOutboxRequest, BridgeLegacyReceipt, BridgeRuntime,
};
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};

const SENTINEL: &str = "SENTINEL-user-text-9c1d";
const NOW: &str = "2026-10-10T09:00:00Z";
const T0: &str = "2026-09-25T00:13:20.500000Z";

fn lane(name: &str) -> PathBuf {
    let directory =
        std::env::temp_dir().join(format!("bb-apple-import-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    fs::create_dir_all(&directory).unwrap();
    directory
}

fn document() -> Value {
    json!({
        "version": 2, "generation": 3,
        "account": {"id": "user_1", "email": "sam@example.com",
            "serverURL": "https://brain-buddy-frontend.fly.dev/api", "linkedAt": T0},
        "base": {
            "projects": {"project-1": {"id": "project-1", "serverID": "project_1a2b3c4d5e6f",
                "serverRevision": 1, "name": SENTINEL, "state": "active", "createdAt": T0}},
            "tags": {},
            "tasks": {"task-1": {"id": "task-1", "serverID": "task_1a2b3c4d5e6f", "serverRevision": 2,
                "title": SENTINEL, "state": "next", "projectID": "project-1", "tagIDs": [],
                "priority": "none", "orderKey": 0, "createdAt": T0, "updatedAt": T0,
                "subtasks": [], "comments": []}},
            "review": {}
        },
        "outbox": [{"id": "0e7b8e3c-2c4a-4d6b-9f1e-3a5b7c9d1e2f", "attempts": 0, "issuedAt": T0,
            "idempotencyKey": "00000000-0000-4000-8000-000000000091",
            "command": {"createTask": {"_0": {"taskID": "task-9", "title": SENTINEL, "list": "inbox"}}}}],
        "issues": [], "sync": {}
    })
}

fn request(directory: &Path) -> BridgeImportRequest {
    BridgeImportRequest {
        workspace_id: "workspace-local".to_owned(),
        database_path: directory
            .join("rust")
            .join("workspace.sqlite3")
            .to_string_lossy()
            .into_owned(),
        source_path: directory.join("store.json").to_string_lossy().into_owned(),
        backup_directory: None,
        now: NOW.to_owned(),
        busy_timeout_ms: 2_000,
        expected: None,
    }
}

fn failed(error: BridgeError) -> (String, bool, Option<String>) {
    let BridgeError::Failed {
        code,
        retryable,
        field,
    } = error;
    (code, retryable, field)
}

fn runtime() -> BridgeRuntime {
    BridgeRuntime::new(bb_swift::bridge_protocol_version()).expect("opens")
}

#[test]
fn apple_import_026_fr_013_imports_through_the_bridge_and_reports_owned_values() {
    let directory = lane("imports");
    fs::write(
        directory.join("store.json"),
        serde_json::to_vec(&document()).unwrap(),
    )
    .unwrap();
    let runtime = runtime();

    let report = runtime
        .import_legacy_store(request(&directory))
        .expect("imports");
    assert!(!report.already_active);
    assert_eq!(report.source_version, 2);
    assert_eq!(report.source_generation, 3);
    assert_eq!(report.counts.tasks, 1);
    assert_eq!(report.counts.projects, 1);
    assert_eq!(report.counts.outbox_entries, 1);
    assert_eq!(report.aliases, 2);
    assert_eq!(report.source_sha256.len(), 64);
    assert!(directory.join(&report.backup_file).exists());
    assert!(directory.join(&report.manifest_file).exists());

    // The second call finds the marker and does nothing.
    let again = runtime
        .import_legacy_store(request(&directory))
        .expect("idempotent");
    assert!(again.already_active);
    assert_eq!(again.source_sha256, report.source_sha256);
}

#[test]
fn apple_import_026_sc_005_counts_the_swift_reader_took_must_agree() {
    let directory = lane("expected");
    fs::write(
        directory.join("store.json"),
        serde_json::to_vec(&document()).unwrap(),
    )
    .unwrap();
    let runtime = runtime();
    let mut wrong = request(&directory);
    wrong.expected = Some(BridgeImportCounts {
        tasks: 2,
        subtasks: 0,
        comments: 0,
        projects: 1,
        tags: 0,
        outbox_entries: 1,
        issues: 0,
        review_sessions: 0,
        review_decisions: 0,
        review_receipts: 0,
        review_park_acks: 0,
        review_bulk_releases: 0,
        review_navigator_consents: 0,
        form_drafts: 0,
    });
    let error = failed(runtime.import_legacy_store(wrong).expect_err("refused"));
    assert_eq!(
        error,
        (
            "IMPORT_VERIFICATION_FAILED".to_owned(),
            false,
            Some("expected_counts".to_owned())
        )
    );
    assert!(!directory.join("rust").exists(), "nothing was created");

    let mut right = request(&directory);
    right.expected = Some(BridgeImportCounts {
        tasks: 1,
        subtasks: 0,
        comments: 0,
        projects: 1,
        tags: 0,
        outbox_entries: 1,
        issues: 0,
        review_sessions: 0,
        review_decisions: 0,
        review_receipts: 0,
        review_park_acks: 0,
        review_bulk_releases: 0,
        review_navigator_consents: 0,
        form_drafts: 0,
    });
    assert!(runtime.import_legacy_store(right).is_ok());
}

#[test]
fn apple_import_026_fr_022_failures_are_typed_and_carry_no_user_text() {
    let directory = lane("failures");
    let runtime = runtime();

    // No file.
    let missing = failed(
        runtime
            .import_legacy_store(request(&directory))
            .expect_err("missing"),
    );
    assert_eq!(missing, ("IMPORT_SOURCE_MISSING".to_owned(), false, None));

    // A file this build cannot read, with the user's text all over it.
    let mut newer = document();
    newer["version"] = json!(3);
    fs::write(
        directory.join("store.json"),
        serde_json::to_vec(&newer).unwrap(),
    )
    .unwrap();
    let error = runtime
        .import_legacy_store(request(&directory))
        .expect_err("newer");
    let rendered = format!("{error:?} {error}");
    assert!(!rendered.contains(SENTINEL));
    assert_eq!(
        failed(error),
        (
            "IMPORT_SOURCE_UNSUPPORTED".to_owned(),
            false,
            Some("version".to_owned())
        )
    );

    let mut broken = serde_json::to_vec(&document()).unwrap();
    broken.truncate(broken.len() / 2);
    fs::write(directory.join("store.json"), &broken).unwrap();
    let error = runtime
        .import_legacy_store(request(&directory))
        .expect_err("broken");
    assert!(!format!("{error:?}{error}").contains(SENTINEL));
    assert_eq!(failed(error).0, "IMPORT_SOURCE_UNREADABLE");
    assert_eq!(fs::read(directory.join("store.json")).unwrap(), broken);

    // A request that cannot be read names the argument, not its content.
    let mut bad = request(&directory);
    bad.now = format!("{SENTINEL} is not an instant");
    let error = runtime.import_legacy_store(bad).expect_err("bad instant");
    assert!(!format!("{error:?}{error}").contains(SENTINEL));
    assert_eq!(
        failed(error),
        ("INVALID_REQUEST".to_owned(), false, Some("now".to_owned()))
    );
}

#[test]
fn apple_import_026_fr_025_a_closed_runtime_does_not_import() {
    let directory = lane("closed");
    fs::write(
        directory.join("store.json"),
        serde_json::to_vec(&document()).unwrap(),
    )
    .unwrap();
    let runtime = runtime();
    runtime.close();
    let error = failed(
        runtime
            .import_legacy_store(request(&directory))
            .expect_err("closed"),
    );
    assert_eq!(error.0, "WORKSPACE_CLOSED");
    assert!(!directory.join("rust").exists());
}

#[test]
fn apple_import_026_sc_005_a_busy_store_is_retryable() {
    let directory = lane("busy");
    fs::write(
        directory.join("store.json"),
        serde_json::to_vec(&document()).unwrap(),
    )
    .unwrap();
    let runtime = runtime();
    let request = request(&directory);
    // Hold the store's migration lock the way another process would.
    fs::create_dir_all(directory.join("rust")).unwrap();
    let database = PathBuf::from(&request.database_path);
    fs::write(&database, b"").unwrap();
    let lock = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(
            directory
                .join("rust")
                .join(".workspace.sqlite3.migrate.lock"),
        )
        .unwrap();
    lock.lock().unwrap();

    let mut short = request.clone();
    short.busy_timeout_ms = 100;
    let error = failed(runtime.import_legacy_store(short).expect_err("busy"));
    assert_eq!(error, ("STORE_BUSY".to_owned(), true, None));
    lock.unlock().unwrap();
    assert!(runtime.import_legacy_store(request).is_ok());
}

// ---------------------------------------------------------------- the legacy outbox (T042)

const KEY: &str = "00000000-0000-4000-8000-000000000091";

fn outbox_request(
    directory: &Path,
    receipts: Vec<BridgeLegacyReceipt>,
) -> BridgeLegacyOutboxRequest {
    let import = request(directory);
    BridgeLegacyOutboxRequest {
        workspace_id: import.workspace_id,
        database_path: import.database_path,
        now: NOW.to_owned(),
        busy_timeout_ms: 2_000,
        receipts,
    }
}

fn accepted_alias(entity_type: &str) -> BridgeLegacyAnswer {
    BridgeLegacyAnswer::Accepted {
        aliases: vec![BridgeLegacyAlias {
            entity_type: entity_type.to_owned(),
            old_local_id: "task-9".to_owned(),
            server_id: "task_0123456789ab".to_owned(),
        }],
    }
}

/// The document with its one pending send made a send that reached the server's door twice.
fn sent_document() -> Value {
    let mut document = document();
    document["outbox"][0]["attempts"] = json!(2);
    document["outbox"][0]["everSent"] = json!(true);
    document["outbox"][0]["firstAttemptAt"] = json!(T0);
    document
}

fn imported(name: &str, document: &Value) -> (PathBuf, BridgeRuntime) {
    let directory = lane(name);
    fs::write(
        directory.join("store.json"),
        serde_json::to_vec(document).unwrap(),
    )
    .unwrap();
    let runtime = runtime();
    runtime
        .import_legacy_store(request(&directory))
        .expect("imports");
    (directory, runtime)
}

#[test]
fn apple_outbox_026_fr_005_a_receipt_given_by_key_settles_the_send_and_proves_the_alias() {
    let (directory, runtime) = imported("outbox-accepted", &sent_document());
    // The sends to look up come from the Rust store, with the key and the old body.
    let sends = runtime
        .legacy_outbox_sends(outbox_request(&directory, vec![]))
        .expect("lists");
    assert_eq!(sends.len(), 1);
    assert_eq!(sends[0].idempotency_key, KEY);
    let command: Value = serde_json::from_slice(&sends[0].command).unwrap();
    assert_eq!(command["createTask"]["_0"]["taskID"], "task-9");
    // A Swift `UUID` prints upper case; the key still matches.
    let receipts = vec![BridgeLegacyReceipt {
        idempotency_key: KEY.to_uppercase(),
        answer: accepted_alias("task"),
    }];

    let status = runtime
        .resolve_legacy_outbox(outbox_request(&directory, receipts.clone()))
        .expect("classifies");

    assert_eq!((status.carried, status.accepted, status.aliases), (1, 1, 1));
    assert!(status.classified && status.may_run && status.fully_synced);
    // Again: the verdict is final and nothing changes.
    let again = runtime
        .resolve_legacy_outbox(outbox_request(&directory, receipts))
        .expect("idempotent");
    assert_eq!(again, status);
    assert!(
        runtime
            .legacy_outbox_sends(outbox_request(&directory, vec![]))
            .expect("lists")
            .is_empty()
    );
}

#[test]
fn apple_outbox_026_fr_010_a_send_without_a_receipt_stays_an_issue_and_never_looks_synced() {
    let (directory, runtime) = imported("outbox-uncertain", &sent_document());

    let status = runtime
        .resolve_legacy_outbox(outbox_request(&directory, vec![]))
        .expect("classifies");

    assert_eq!((status.uncertain, status.open_issues), (1, 1));
    assert!(status.classified && status.may_run && !status.fully_synced);
}

#[test]
fn apple_outbox_026_fr_013_a_never_sent_intent_blocks_the_run_until_it_is_a_command() {
    let (directory, runtime) = imported("outbox-unsent", &document());

    let status = runtime
        .resolve_legacy_outbox(outbox_request(&directory, vec![]))
        .expect("classifies");

    assert_eq!(status.unsent, 1);
    assert!(status.classified && !status.may_run && !status.fully_synced);
}

#[test]
fn apple_outbox_026_fr_022_failures_are_typed_and_carry_no_user_text() {
    let directory = lane("outbox-errors");
    let runtime = runtime();

    // Nothing imported yet.
    let error = failed(
        runtime
            .resolve_legacy_outbox(outbox_request(&directory, vec![]))
            .expect_err("not imported"),
    );
    assert_eq!(
        error,
        ("LEGACY_OUTBOX_NOT_IMPORTED".to_owned(), false, None)
    );

    let (directory, runtime) = imported("outbox-errors-2", &sent_document());
    let bad_type = vec![BridgeLegacyReceipt {
        idempotency_key: KEY.to_owned(),
        answer: accepted_alias("not-a-type"),
    }];
    let error = failed(
        runtime
            .resolve_legacy_outbox(outbox_request(&directory, bad_type))
            .expect_err("bad entity type"),
    );
    assert_eq!(
        error,
        (
            "INVALID_REQUEST".to_owned(),
            false,
            Some("entity_type".to_owned())
        )
    );
    let mut bad_now = outbox_request(&directory, vec![]);
    bad_now.now = SENTINEL.to_owned();
    let error = failed(runtime.resolve_legacy_outbox(bad_now).expect_err("bad now"));
    assert_eq!(error.0, "INVALID_REQUEST");
    assert!(!format!("{error:?}").contains(SENTINEL));

    runtime.close();
    let error = failed(
        runtime
            .resolve_legacy_outbox(outbox_request(&directory, vec![]))
            .expect_err("closed"),
    );
    assert_eq!(error.0, "WORKSPACE_CLOSED");
}

#[test]
fn apple_import_026_fr_013_prepared_conversion_preserves_source_identity_and_commit_arbitration() {
    use bb_swift::{
        BridgeExecuteContext, BridgeExecution, BridgeLegacyConversion, BridgeOperation,
        BridgeStoreRequest, BridgeWorkspaceCommand,
    };
    use std::sync::Arc;
    let directory = lane("prepared-conversion");
    fs::write(
        directory.join("store.json"),
        serde_json::to_vec(&document()).unwrap(),
    )
    .unwrap();
    let runtime = runtime();
    let request = request(&directory);
    runtime.import_legacy_store(request.clone()).unwrap();
    runtime
        .resolve_legacy_outbox(BridgeLegacyOutboxRequest {
            workspace_id: request.workspace_id.clone(),
            database_path: request.database_path.clone(),
            now: NOW.into(),
            busy_timeout_ms: 2000,
            receipts: vec![],
        })
        .unwrap();
    let workspace = runtime
        .open_store(BridgeStoreRequest {
            workspace_id: request.workspace_id,
            database_path: request.database_path,
            busy_timeout_ms: 2000,
        })
        .unwrap();
    let unsent = workspace.legacy_unsent().unwrap();
    assert_eq!(unsent.len(), 1);
    assert_eq!(unsent[0].issued_at, T0);
    let source: Value = serde_json::from_slice(&unsent[0].command).unwrap();
    assert_eq!(source["createTask"]["_0"]["title"], SENTINEL);
    let item = BridgeLegacyConversion {
        entry_id: unsent[0].entry_id.clone(),
        issued_at: unsent[0].issued_at.clone(),
        command: BridgeWorkspaceCommand {
            command_id: unsent[0].idempotency_key.clone(),
            command_type: "task.create".into(),
            entity_id: Some("task_00000000-0000-4000-8000-000000000009".into()),
            payload: json!({"title":SENTINEL,"state":"inbox"})
                .to_string()
                .into_bytes(),
            preconditions: b"[]".to_vec(),
            depends_on: vec![],
            admission_tokens: Vec::new(),
        },
    };
    let context = BridgeExecuteContext {now:NOW.into(),time_zone:"UTC".into(),actor_id:"device".into(),policy:json!({"weekly_review":false,"navigator_provider":null,"navigator_available":false,"consent_text_version":1}).to_string().into_bytes()};
    let mut wrong = item.clone();
    wrong.entry_id = "another source".into();
    assert!(matches!(
        workspace
            .convert_legacy_unsent(
                vec![wrong],
                context.clone(),
                Arc::new(BridgeOperation::new())
            )
            .unwrap(),
        BridgeExecution::Refused { .. }
    ));
    let cancelled = Arc::new(BridgeOperation::new());
    cancelled.cancel();
    assert_eq!(
        failed(
            workspace
                .convert_legacy_unsent(vec![item.clone()], context.clone(), cancelled)
                .unwrap_err()
        )
        .0,
        "CANCELLED"
    );
    assert_eq!(workspace.legacy_unsent().unwrap().len(), 1);
    let committed = Arc::new(BridgeOperation::new());
    let BridgeExecution::Saved { results } = workspace
        .convert_legacy_unsent(vec![item.clone()], context.clone(), committed.clone())
        .unwrap()
    else {
        panic!("saved")
    };
    assert_eq!(results[0].command_id, unsent[0].idempotency_key);
    assert!(committed.is_committed());
    assert!(!committed.cancel());
    assert!(workspace.legacy_unsent().unwrap().is_empty());
    let BridgeExecution::Saved { results } = workspace
        .convert_legacy_unsent(
            vec![item.clone()],
            context.clone(),
            Arc::new(BridgeOperation::new()),
        )
        .unwrap()
    else {
        panic!("retry")
    };
    assert!(results[0].replayed);
    let begin = Arc::new(BridgeOperation::new());
    let plan = workspace
        .begin_legacy_conversion(context, false, begin.clone())
        .unwrap();
    assert!(begin.is_committed());
    assert!(!begin.cancel());
    assert_eq!(plan.source_count, 1);
    let page = workspace
        .legacy_conversion_page(plan.token.clone(), None)
        .unwrap();
    assert_eq!(page.items.len(), 1);
    let cancelled = Arc::new(BridgeOperation::new());
    cancelled.cancel();
    assert_eq!(
        failed(
            workspace
                .convert_legacy_conversion_page(
                    plan.token.clone(),
                    page.page_token.clone(),
                    vec![item.clone()],
                    false,
                    cancelled
                )
                .unwrap_err()
        )
        .0,
        "CANCELLED"
    );
    let commit = Arc::new(BridgeOperation::new());
    let progress = workspace
        .convert_legacy_conversion_page(
            plan.token.clone(),
            page.page_token.clone(),
            vec![item.clone()],
            false,
            commit.clone(),
        )
        .unwrap();
    assert!(progress.complete);
    assert!(progress.status.may_run);
    assert!(commit.is_committed());
    assert!(!commit.cancel());
    let mut changed = item;
    changed.command.payload = json!({"title":"Different prepared body","state":"next"})
        .to_string()
        .into_bytes();
    assert_eq!(
        failed(
            workspace
                .convert_legacy_conversion_page(
                    plan.token,
                    page.page_token,
                    vec![changed],
                    false,
                    Arc::new(BridgeOperation::new())
                )
                .unwrap_err()
        )
        .0,
        "COMMAND_ID_REUSED"
    );
}

#[test]
fn owned_review_activation_cancellation_and_marker_retry_share_commit_guard() {
    use bb_swift::{
        BridgeExecuteContext, BridgeLegacyReviewPrepared, BridgeOperation, BridgeStoreRequest,
    };
    use std::sync::Arc;
    let directory = lane("review-activation");
    fs::write(
        directory.join("store.json"),
        serde_json::to_vec(&document()).unwrap(),
    )
    .unwrap();
    let runtime = runtime();
    runtime.import_legacy_store(request(&directory)).unwrap();
    let workspace = runtime
        .open_store(BridgeStoreRequest {
            workspace_id: "workspace-local".into(),
            database_path: request(&directory).database_path,
            busy_timeout_ms: 2_000,
        })
        .unwrap();
    let capture = workspace.capture_legacy_review().unwrap();
    assert!(!capture.already_active);
    let prepare = || BridgeLegacyReviewPrepared {
        token: capture.token.clone(),
        read_set: serde_json::to_vec(&bb_domain::types::ReadSet::default()).unwrap(),
        aliases: b"[]".to_vec(),
        derived_counts: b"{\"decision_queues\":0,\"unseen_park_acks\":0}".to_vec(),
    };
    let context = || {
        BridgeExecuteContext{now:NOW.into(),time_zone:"UTC".into(),actor_id:"actor-local".into(),policy:json!({"weekly_review":true,"navigator_provider":null,"navigator_available":false,"consent_text_version":1}).to_string().into_bytes()}
    };
    let cancelled = Arc::new(BridgeOperation::new());
    assert!(cancelled.cancel());
    assert_eq!(
        failed(
            workspace
                .activate_legacy_review(prepare(), context(), cancelled)
                .unwrap_err()
        )
        .0,
        "CANCELLED"
    );
    assert!(!workspace.capture_legacy_review().unwrap().already_active);
    let operation = Arc::new(BridgeOperation::new());
    let activated = workspace
        .activate_legacy_review(prepare(), context(), operation.clone())
        .unwrap();
    assert!(!activated.already_active);
    assert!(!operation.cancel());
    assert!(
        workspace
            .activate_legacy_review(prepare(), context(), Arc::new(BridgeOperation::new()))
            .unwrap()
            .already_active
    );
    let cancelled = Arc::new(BridgeOperation::new());
    cancelled.cancel();
    assert_eq!(
        failed(
            workspace
                .activate_legacy_review(prepare(), context(), cancelled)
                .unwrap_err()
        )
        .0,
        "CANCELLED"
    );
    assert_eq!(
        workspace.capture_legacy_review().unwrap().token,
        capture.token
    );
}
