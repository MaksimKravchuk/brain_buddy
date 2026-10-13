//! 026-FR-003 / 026-FR-023: the local export carries what the person authored,
//! with relationships intact, and nothing protected.

use bb_client::{
    EXPORT_FORMAT, ExportStage, OpenOptions, Store, StoreError, WorkspaceExport, export_workspace,
};
use rusqlite::params;
use std::path::PathBuf;
use std::time::Duration;

const WORKSPACE: &str = "workspace-local";

fn open(name: &str) -> Store {
    let directory = std::env::temp_dir().join(format!("bb-export-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&directory);
    let path: PathBuf = directory.join("store").join("workspace.sqlite3");
    Store::open(&OpenOptions {
        path,
        workspace_id: WORKSPACE.to_string(),
        busy_timeout: Duration::from_millis(500),
    })
    .expect("open store")
}

fn seed(store: &mut Store) {
    store
        .write(|tx| {
            tx.execute(
                "INSERT INTO visible_records (workspace_id, record_type, record_key,
                    edit_revision, source_command_id, body)
                 VALUES (?1, 'task', 'task-1', '3', 'cmd-queued', ?2)",
                params![WORKSPACE, br#"{"title":"Buy milk","lease_token":"L-SECRET"}"#.to_vec()],
            )?;
            for (id, seq, state) in [
                ("cmd-queued", 1, "queued"),
                ("cmd-rejected", 2, "rejected"),
                ("cmd-done", 3, "completed"),
                ("cmd-blocked", 4, "blocked_dependency"),
            ] {
                tx.execute(
                    "INSERT INTO outbox (workspace_id, command_id, device_epoch, local_seq,
                        envelope, envelope_digest, state, created_at)
                     VALUES (?1, ?2, 'epoch-1', ?3, ?4, x'deadbeef', ?5, '2026-10-09T00:00:00Z')",
                    params![
                        WORKSPACE,
                        id,
                        seq,
                        format!(r#"{{"command_id":"{id}","payload":{{"title":"text of {id}"}},"fingerprint":"FP-SECRET"}}"#)
                            .into_bytes(),
                        state
                    ],
                )?;
            }
            tx.execute(
                "INSERT INTO outbox_dependencies (workspace_id, command_id, depends_on)
                 VALUES (?1, 'cmd-blocked', 'cmd-rejected')",
                [WORKSPACE],
            )?;
            tx.execute(
                "INSERT INTO sync_issues (workspace_id, issue_id, command_id, reason,
                    local_intent, local_text, dependent_ids, created_at)
                 VALUES (?1, 'issue-1', 'cmd-rejected', 'stale_base', ?2, 'my typed words',
                    '[\"cmd-blocked\"]', '2026-10-09T00:00:01Z')",
                params![WORKSPACE, br#"{"op":"edit","token":"T-SECRET"}"#.to_vec()],
            )?;
            tx.execute(
                "INSERT INTO identity_aliases (workspace_id, entity_type, old_local_id,
                    server_id, provenance) VALUES (?1, 'task', 'local-7', 'server-7', 'receipt')",
                [WORKSPACE],
            )?;
            for (id, kind) in [("d-form", "review_form_draft"), ("d-origin", "runtime_task_local")] {
                tx.execute(
                    "INSERT INTO drafts (workspace_id, draft_id, editor_kind, fields, updated_at)
                     VALUES (?1, ?2, ?3, ?4, '2026-10-09T00:00:02Z')",
                    params![WORKSPACE, id, kind, br#"{"note":"unsaved words"}"#.to_vec()],
                )?;
            }
            // Protected rows that must never appear.
            tx.execute(
                "INSERT INTO command_receipts (workspace_id, command_id, server_generation,
                    outcome, receipt, verified_at)
                 VALUES (?1, 'cmd-done', 'gen-1', 'accepted', ?2, '2026-10-09T00:00:03Z')",
                params![WORKSPACE, br#"{"fingerprint":"RECEIPT-FP"}"#.to_vec()],
            )?;
            Ok(())
        })
        .expect("seed");
}

fn exported(name: &str) -> (WorkspaceExport, String) {
    let mut store = open(name);
    seed(&mut store);
    let (export, _) = export_workspace(&mut store, WORKSPACE).expect("export");
    let json = serde_json::to_string(&export).expect("serialise");
    (export, json)
}

#[test]
fn feature_026_fr_003_export_carries_visible_pending_issues_and_aliases() {
    let (export, _) = exported("complete");
    assert_eq!(export.format, EXPORT_FORMAT);
    assert_eq!(export.visible_records.len(), 1);
    assert_eq!(export.visible_records[0].body["title"], "Buy milk");
    assert_eq!(export.identity_aliases.len(), 1);
    assert_eq!(export.identity_aliases[0].server_id, "server-7");
    let ids: Vec<&str> = export
        .pending_intents
        .iter()
        .map(|i| i.command_id.as_str())
        .collect();
    assert_eq!(ids, ["cmd-queued", "cmd-rejected", "cmd-blocked"]);
    assert_eq!(
        export.issues[0].local_text.as_deref(),
        Some("my typed words")
    );
}

#[test]
fn feature_026_fr_003_export_keeps_relationships_complete() {
    let (export, _) = exported("relations");
    let ids: Vec<&str> = export
        .pending_intents
        .iter()
        .map(|i| i.command_id.as_str())
        .collect();
    for issue in &export.issues {
        assert!(
            ids.contains(&issue.command_id.as_str()),
            "issue command exported"
        );
        for dependent in &issue.dependent_ids {
            assert!(ids.contains(&dependent.as_str()), "dependent exported");
        }
    }
    let blocked = export
        .pending_intents
        .iter()
        .find(|i| i.command_id == "cmd-blocked");
    assert_eq!(
        blocked.map(|i| i.depends_on.clone()),
        Some(vec!["cmd-rejected".to_string()])
    );
}

#[test]
fn feature_026_fr_003_export_keeps_only_user_authored_drafts() {
    let (export, _) = exported("drafts");
    let kinds: Vec<&str> = export
        .drafts
        .iter()
        .map(|d| d.editor_kind.as_str())
        .collect();
    assert_eq!(kinds, ["review_form_draft"]);
}

#[test]
fn feature_026_fr_023_export_excludes_fingerprints_tokens_and_digests() {
    let (_, json) = exported("protected");
    for needle in [
        "FP-SECRET",
        "T-SECRET",
        "L-SECRET",
        "RECEIPT-FP",
        "fingerprint",
        "deadbeef",
        "digest",
    ] {
        assert!(!json.contains(needle), "export leaked {needle}");
    }
}

#[test]
fn feature_026_fr_023_report_and_errors_carry_counts_stage_and_timing_only() {
    let mut store = open("report");
    seed(&mut store);
    let (_, report) = export_workspace(&mut store, WORKSPACE).expect("export");
    let rendered = serde_json::to_string(&report).expect("report");
    assert!(rendered.contains("\"pending_intents\":3"));
    assert!(!rendered.contains("milk") && !rendered.contains("typed words"));

    store
        .write(|tx| {
            tx.execute("UPDATE visible_records SET body = x'00'", [])?;
            Ok(())
        })
        .expect("corrupt");
    let error = export_workspace(&mut store, WORKSPACE).expect_err("corrupt body");
    assert_eq!(error.stage, ExportStage::Records);
    assert_eq!(error.store, StoreError::Corrupt);
    assert_eq!(error.to_string(), "EXPORT_RECORDS: STORE_CORRUPT");
}

#[test]
fn feature_026_fr_003_export_of_another_workspace_is_empty() {
    let mut store = open("scoped");
    seed(&mut store);
    let (export, report) = export_workspace(&mut store, "someone-else").expect("export");
    assert!(export.visible_records.is_empty() && export.pending_intents.is_empty());
    assert_eq!(report.issues + report.identity_aliases + report.drafts, 0);
}
