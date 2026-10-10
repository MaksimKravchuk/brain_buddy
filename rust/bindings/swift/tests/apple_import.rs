//! The legacy import through the Apple bridge (spec 026 T041): the request and report
//! records `RustBridgeRuntime.importLegacyStore` maps, and the typed, content-free errors
//! it throws. The import itself is tested in `bb-client`; these tests are about the
//! boundary: owned values, the `guarded` seam, error codes and no payload text.

use bb_swift::{BridgeError, BridgeImportCounts, BridgeImportRequest, BridgeRuntime};
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
