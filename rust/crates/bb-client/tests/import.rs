//! Legacy import tests (spec 026 T041): the Swift `StoreDocument` JSON file becomes
//! a verified Rust store, or nothing changes.
//!
//! Everything goes through the public API on real SQLite files and real source
//! files: the frozen `legacy-import-golden.json`, a populated document in the
//! shape Swift's `Codable` writes, and the Mac fixtures (the pre-021 file shape,
//! which this importer must refuse and the awkward strings of which it must carry
//! verbatim). Children are this test binary started again with `BB_IMPORT_CHILD`
//! set, so a crash, a held lock or a full disk is a real process or a real SQLite
//! error, not a stand-in.

use bb_client::{
    ImportError, ImportRequest, ImportStage, LockMode, MigrationLock, OpenOptions, SCHEMA_VERSION,
    SourceCounts, Store, StoreError, StoreStatus, import_legacy_store, import_legacy_store_with,
    legacy_import_marker, legacy_record_key,
};
use bb_domain::types::{Project, Subtask, Tag, Task};
use bb_protocol::catalog::EntityType;
use bb_protocol::wire::Instant;
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::Duration;

const WORKSPACE: &str = "workspace-local";
const NOW: &str = "2026-10-10T09:00:00Z";
const ROLE: &str = "BB_IMPORT_CHILD";
const SENTINEL: &str = "SENTINEL-user-text-7f3a";

const GOLDEN: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Resources/legacy-import-golden.json"
);
const MAC_RESOURCES: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../macos/Tests/BrainBuddyMacTests/Resources"
);
const REFERENCE_STORE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../specs/026-rust-core-sync/contracts/reference-store.json"
);

// ----------------------------------------------------------------------- harness

struct Lane {
    directory: PathBuf,
    database: PathBuf,
    source: PathBuf,
}

fn lane(name: &str) -> Lane {
    let directory = std::env::temp_dir().join(format!("bb-import-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    fs::create_dir_all(&directory).unwrap();
    Lane {
        database: directory.join("rust").join("workspace.sqlite3"),
        source: directory.join("store.json"),
        directory,
    }
}

impl Lane {
    fn write_source(&self, document: &Value) -> Vec<u8> {
        let bytes = serde_json::to_vec(document).unwrap();
        fs::write(&self.source, &bytes).unwrap();
        bytes
    }

    fn request(&self) -> ImportRequest {
        ImportRequest {
            store: options(&self.database, 2_000),
            source: self.source.clone(),
            backup_dir: None,
            now: Instant::parse(NOW).unwrap(),
            expected: None,
        }
    }

    fn backups(&self) -> Vec<String> {
        let mut names: Vec<String> = fs::read_dir(&self.directory)
            .unwrap()
            .filter_map(Result::ok)
            .map(|entry| entry.file_name().to_string_lossy().into_owned())
            .filter(|name| name.contains(".pre-rust-"))
            .collect();
        names.sort();
        names
    }
}

fn options(path: &Path, timeout_ms: u64) -> OpenOptions {
    OpenOptions {
        path: path.to_path_buf(),
        workspace_id: WORKSPACE.to_string(),
        busy_timeout: Duration::from_millis(timeout_ms),
    }
}

fn open(path: &Path) -> Store {
    Store::open(&options(path, 2_000)).unwrap()
}

fn count(store: &mut Store, table: &str) -> i64 {
    store
        .read(|tx| {
            tx.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
                row.get(0)
            })
        })
        .unwrap()
}

/// Nothing of an import is visible: no marker, no row of any live table.
fn assert_untouched_store(path: &Path) {
    if !path.exists() {
        return;
    }
    let mut store = open(path);
    assert_eq!(legacy_import_marker(&mut store).unwrap(), None);
    for table in [
        "confirmed_records",
        "visible_records",
        "outbox",
        "drafts",
        "identity_aliases",
        "sync_issues",
    ] {
        assert_eq!(count(&mut store, table), 0, "{table} must stay empty");
    }
    let linked: String = store
        .read(|tx| tx.query_row("SELECT account_link_state FROM sync_meta", [], |r| r.get(0)))
        .unwrap();
    assert_eq!(linked, "unchosen");
}

fn bodies(store: &mut Store, kind: &str) -> BTreeMap<String, Value> {
    store
        .read(|tx| {
            let mut statement = tx
                .prepare("SELECT record_key, body FROM confirmed_records WHERE record_type = ?1")?;
            let rows = statement.query_map([kind], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
            })?;
            let mut found = BTreeMap::new();
            for row in rows {
                let (key, body) = row?;
                found.insert(key, serde_json::from_slice(&body).unwrap());
            }
            Ok(found)
        })
        .unwrap()
}

fn carried(store: &mut Store, kind: &str) -> Vec<(String, Option<String>, Value)> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT draft_id, record_key, fields FROM drafts WHERE editor_kind = ?1
                 ORDER BY draft_id",
            )?;
            let rows = statement.query_map([kind], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, Option<String>>(1)?,
                    row.get::<_, Vec<u8>>(2)?,
                ))
            })?;
            let mut found = Vec::new();
            for row in rows {
                let (id, key, fields) = row?;
                found.push((id, key, serde_json::from_slice(&fields).unwrap()));
            }
            Ok(found)
        })
        .unwrap()
}

fn aliases(store: &mut Store) -> Vec<(String, String, String, String)> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT entity_type, old_local_id, server_id, provenance FROM identity_aliases
                 ORDER BY entity_type, old_local_id",
            )?;
            let rows = statement.query_map([], |row| {
                Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?))
            })?;
            rows.collect()
        })
        .unwrap()
}

fn key(id: &str) -> String {
    json!([id]).to_string()
}

fn full_disk() -> rusqlite::Error {
    rusqlite::Error::SqliteFailure(rusqlite::ffi::Error::new(rusqlite::ffi::SQLITE_FULL), None)
}

/// A named change to the populated document, and the section the importer names for it.
type TamperCase = (&'static str, Box<dyn Fn(&mut Value)>, &'static str);

// ---------------------------------------------------------------------- fixtures

const T0: &str = "2026-09-25T00:13:20.500000Z";
const T1: &str = "2026-09-26T03:46:40.000001Z";
const FORM: &str = "form_11111111-1111-4111-8111-111111111111";
const FORM_TWO: &str = "form_22222222-2222-4222-8222-222222222222";
const OLD_FLAT: &str = "6f0e1e0a-0b1c-4d2e-8f3a-4b5c6d7e8f90";

/// A populated document in the shape `Codable` writes it (sorted keys are not
/// required to read it): proven and unproven identities on every kind, an
/// archived project that lost its tasks' project before archives were lossless, a
/// deleted tag, two active projects and tags whose names would collide under the
/// server's rules, a waiting task, a finished task with its `lastOpenList`, a
/// running clock, a park with a private part, children with and without server
/// IDs, the Review aggregate, the local state with form drafts, an outbox with a
/// sent entry, an issue, the account and the sync metadata.
fn rich() -> Value {
    json!({
        "version": 2, "generation": 4,
        "account": {"id": "user_1", "email": "sam@example.com", "displayName": "Sam",
            "serverURL": "https://brain-buddy-frontend.fly.dev/api", "linkedAt": T0},
        "base": {
            "projects": {
                "project-1": {"id": "project-1", "serverID": "project_1a2b3c4d5e6f",
                    "serverRevision": 1, "name": "Home", "color": "#0EA5E9", "state": "active",
                    "createdAt": T0, "desiredOutcome": "A calm house"},
                OLD_FLAT: {"id": OLD_FLAT, "name": "Old flat", "state": "archived",
                    "createdAt": T0, "archivedAt": T1, "archivedBeforeLossless": true},
                "project-3": {"id": "project-3", "serverID": "project_ffffffffffff",
                    "serverRevision": 5, "name": "Home", "state": "active", "createdAt": T1}
            },
            "tags": {
                "tag-1": {"id": "tag-1", "name": "phone", "state": "active", "createdAt": T0},
                "tag-2": {"id": "tag-2", "serverID": "tag_0123456789ab", "serverRevision": 2,
                    "name": "@home", "state": "deleted", "createdAt": T0},
                "tag-3": {"id": "tag-3", "name": "home", "state": "active", "createdAt": T1}
            },
            "tasks": {
                "task-1": {"id": "task-1", "serverID": "task_1a2b3c4d5e6f", "serverRevision": 3,
                    "title": "Call the plumber", "details": "Before Friday", "state": "waiting",
                    "projectID": "project-1", "tagIDs": ["tag-1", "tag-3"], "dueDate": "2026-10-02",
                    "priority": "high", "waitingFor": "Plumber", "waitingSince": T1, "orderKey": 7,
                    "createdAt": T0, "updatedAt": T1, "childrenSyncedAt": T1,
                    "subtasks": [
                        {"id": "subtask-1", "title": "Find the number", "state": "open", "orderKey": 0},
                        {"id": "subtask-2", "serverID": "subtask_aaaaaaaaaaaa", "serverRevision": 2,
                            "title": "Ask for a quote", "state": "completed", "orderKey": 1}
                    ],
                    "comments": [
                        {"id": "comment-1", "authorID": "user_1", "body": "Left a message", "createdAt": T0},
                        {"id": "comment-2", "serverID": "comment_bbbbbbbbbbbb", "serverRevision": 4,
                            "body": "Called back", "createdAt": T0, "editedAt": T1}
                    ]},
                "task-2": {"id": "task-2", "title": "Renovate the bathroom", "state": "next",
                    "tagIDs": [], "priority": "none", "orderKey": 0, "createdAt": T0, "updatedAt": T0,
                    "subtasks": [], "comments": []},
                "task-3": {"id": "task-3", "serverID": "task_bbbbbbbbbbbb", "serverRevision": 9,
                    "title": "Sell the old sofa", "state": "completed", "lastOpenList": "next",
                    "projectID": OLD_FLAT, "tagIDs": [], "priority": "low", "orderKey": 2,
                    "completedAt": T1, "createdAt": T0, "updatedAt": T1, "subtasks": [], "comments": []},
                "task-4": {"id": "task-4", "serverID": "task_cccccccccccc", "serverRevision": 1,
                    "title": "Write the report", "state": "next", "tagIDs": [], "priority": "medium",
                    "orderKey": 3, "createdAt": T0, "updatedAt": T0, "subtasks": [], "comments": [],
                    "consecutiveStalledFormulations": 2,
                    "formulation": {"id": FORM, "startedAt": T0, "extendedAt": T1,
                        "extensionReason": "Waiting for numbers", "parkFloorAt": T1}},
                "task-5": {"id": "task-5", "serverID": "task_dddddddddddd", "serverRevision": 6,
                    "title": "Plan the trip", "state": "someday", "tagIDs": [], "priority": "none",
                    "orderKey": 4, "createdAt": T0, "updatedAt": T1, "subtasks": [], "comments": [],
                    "parked": {"at": T1, "formulationID": FORM_TWO, "fromRevision": 5,
                        "stalledBefore": 1,
                        "clockBefore": {"id": FORM_TWO, "startedAt": T0}}}
            },
            "review": {
                "settings": {"reviewTime": "16:00", "reviewWeekday": 5, "thresholdDays": 14,
                    "timeZone": "UTC", "serverRevision": 3},
                "sessions": {"review_1": {"id": "review_1", "status": "open", "steps": {}}},
                "decisions": {"decision_1": {"id": "decision_1", "type": "keep_waiting"},
                    "decision_2": {"id": "decision_2", "type": "complete"}},
                "receipts": [{"taskID": "task-1", "kind": "waiting", "reviewedAt": T1}],
                "parkAcks": [{"taskID": "task-5", "formulationID": FORM_TWO, "parkedAt": T1}],
                "bulkReleases": {},
                "navigatorConsents": {"anthropic": {"provider": "anthropic", "grantedAt": T0}},
                "server": {"exposed": true}
            }
        },
        "outbox": [
            {"id": "0e7b8e3c-2c4a-4d6b-9f1e-3a5b7c9d1e2f", "attempts": 0, "issuedAt": T1,
                "idempotencyKey": "00000000-0000-4000-8000-000000000091",
                "command": {"createTask": {"_0": {"taskID": "task-9", "title": SENTINEL, "list": "next",
                    "priority": "none", "tagIDs": []}}}},
            {"id": "7c8d9e0f-1a2b-4c3d-8e4f-5a6b7c8d9e0f", "attempts": 2, "everSent": true,
                "firstAttemptAt": T0, "lastAttemptAt": T1, "lastError": "timeout", "issuedAt": T1,
                "idempotencyKey": "00000000-0000-4000-8000-000000000092",
                "command": {"transitionTask": {"_0": {"taskID": "task-1", "action": "complete"}}}}
        ],
        "issues": [{"id": "6f0e1e0a-0b1c-4d2e-8f3a-4b5c6d7e8f91", "message": "Not found",
            "occurredAt": T0, "referenceID": "ref-1", "command": {"deleteTag": {"_0": "tag-1"}}}],
        "sync": {"lastPullAt": T0, "lastPushAt": T1},
        "local": {
            "activatedAt": T0, "explainerSeenLocally": true, "wywaLastShownDay": "2026-10-01",
            "issuedAutoParks": {"task-5": FORM_TWO}, "idleClosedSessions": [],
            "linkedExtensionNotices": ["task-2"], "parkBatchWaiting": false, "parkWarnings": {},
            "formDrafts": {
                "form:reformulate:task-1:-": {"text": SENTINEL, "savedAt": T1},
                "project:project-1": {"text": "first action", "savedAt": T0}
            }
        }
    })
}

fn golden_bytes() -> Vec<u8> {
    fs::read(GOLDEN).expect("the frozen golden fixture exists")
}

fn sha256_hex(bytes: &[u8]) -> String {
    bb_client::sha256_hex(bytes)
}

// ----------------------------------------------------------------------- children

fn spawn(role: &str, lane: &Lane) -> Child {
    Command::new(std::env::current_exe().unwrap())
        .args([
            "import_child_entry",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ])
        .env(ROLE, role)
        .env("BB_IMPORT_DATABASE", &lane.database)
        .env("BB_IMPORT_SOURCE", &lane.source)
        .stdout(Stdio::piped())
        .spawn()
        .unwrap()
}

fn wait_for(child: &mut Child, marker: &str) {
    let stdout = child.stdout.take().unwrap();
    let found = BufReader::new(stdout)
        .lines()
        .map_while(Result::ok)
        .any(|line| line.ends_with(marker));
    assert!(found, "child exited before printing {marker}");
}

fn say(marker: &str) {
    println!("{marker}");
    std::io::stdout().flush().unwrap();
}

#[test]
fn import_child_entry() {
    let Ok(role) = std::env::var(ROLE) else {
        return;
    };
    let database = PathBuf::from(std::env::var("BB_IMPORT_DATABASE").unwrap());
    let source = PathBuf::from(std::env::var("BB_IMPORT_SOURCE").unwrap());
    let request = ImportRequest {
        store: options(&database, 5_000),
        source: source.clone(),
        backup_dir: None,
        now: Instant::parse(NOW).unwrap(),
        expected: None,
    };
    match role.as_str() {
        "abort_while_staging" => {
            let _ = import_legacy_store_with(&request, |stage, _| {
                if stage == ImportStage::Staged(0) {
                    say("staged");
                    std::process::abort();
                }
                Ok(())
            });
        }
        "abort_before_commit" => {
            let _ = import_legacy_store_with(&request, |stage, _| {
                if stage == ImportStage::Verified {
                    say("verified");
                    std::process::abort();
                }
                Ok(())
            });
        }
        "abort_after_commit" => {
            import_legacy_store(&request).unwrap();
            say("committed");
            std::process::abort();
        }
        "hold_migration_lock" => {
            let _lock =
                MigrationLock::acquire(&database, LockMode::Exclusive, Duration::from_secs(5))
                    .unwrap()
                    .unwrap();
            say("holding");
            std::thread::sleep(Duration::from_secs(60));
        }
        // The writers below behave as `FileDocumentStore.update` does: the exclusive
        // `flock` on the sibling lock file, then a temporary file renamed over the document.
        "hold_document_lock" => {
            let _lock = take_document_lock(&source);
            say("holding");
            std::thread::sleep(Duration::from_secs(60));
        }
        "write_then_release" => {
            let _lock = take_document_lock(&source);
            say("holding");
            std::thread::sleep(Duration::from_millis(400));
            rewrite_document(&source, 9);
        }
        "write_under_lock" => {
            touch(&source, "attempting");
            let _lock = take_document_lock(&source);
            rewrite_document(&source, 99);
            touch(&source, "wrote");
        }
        other => panic!("unknown child role {other}"),
    }
}

fn take_document_lock(source: &Path) -> fs::File {
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(source.with_file_name(".store.json.lock"))
        .unwrap();
    lock.lock().unwrap();
    lock
}

/// What a `FileDocumentStore` write does to the file: new content under a new inode.
fn rewrite_document(source: &Path, generation: u64) {
    let mut document: Value = serde_json::from_slice(&fs::read(source).unwrap()).unwrap();
    document["generation"] = json!(generation);
    let temporary = source.with_file_name(".store.json.writer.tmp");
    fs::write(&temporary, serde_json::to_vec(&document).unwrap()).unwrap();
    fs::rename(&temporary, source).unwrap();
}

fn touch(source: &Path, name: &str) {
    fs::write(source.with_file_name(format!(".marker-{name}")), b"").unwrap();
}

fn marked(lane: &Lane, name: &str) -> bool {
    lane.directory.join(format!(".marker-{name}")).exists()
}

fn wait_until(what: &str, mut done: impl FnMut() -> bool) {
    for _ in 0..500 {
        if done() {
            return;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    panic!("timed out waiting for {what}");
}

// ------------------------------------------------------------------------- tests

#[test]
fn import_026_sc_005_a_writer_holding_the_document_lock_makes_the_import_busy_never_stale() {
    let lane = lane("document-lock-held");
    let bytes = lane.write_source(&rich());
    let mut child = spawn("hold_document_lock", &lane);
    wait_for(&mut child, "holding");

    let mut request = lane.request();
    request.store.busy_timeout = Duration::from_millis(150);
    let error = import_legacy_store(&request).unwrap_err();
    assert_eq!(error, ImportError::Store(StoreError::Busy));
    assert!(error.is_retryable());
    // Nothing was read, backed up or created while a writer might be mid-write.
    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
    assert!(lane.backups().is_empty());
    assert!(!lane.database.exists());

    child.kill().unwrap();
    child.wait().unwrap();
    assert!(import_legacy_store(&lane.request()).is_ok());
}

#[test]
fn import_026_sc_005_the_import_waits_for_a_writer_and_imports_what_it_wrote() {
    let lane = lane("document-lock-wait");
    lane.write_source(&rich());
    let mut child = spawn("write_then_release", &lane);
    wait_for(&mut child, "holding");

    // The writer finishes within the wait; the import reads the file after it, so the
    // generation it imports is the writer's (9), not the older 4 it could have read first.
    let mut request = lane.request();
    request.store.busy_timeout = Duration::from_secs(10);
    let report = import_legacy_store(&request).unwrap();
    assert_eq!(report.marker.source_generation, 9);
    child.wait().unwrap();
    assert_eq!(
        report.marker.source_sha256,
        sha256_hex(&fs::read(&lane.source).unwrap())
    );
}

#[test]
fn import_026_fr_025_a_writer_during_the_import_blocks_until_the_commit() {
    let lane = lane("document-lock-writer");
    let original = lane.write_source(&rich());
    let mut writer: Option<Child> = None;
    let source = lane.source.clone();
    let directory = lane.directory.clone();
    let report = import_legacy_store_with(&lane.request(), |at, _| {
        if at == ImportStage::Staged(0) {
            // The import holds the document lock now: a widget starts a write.
            writer = Some(spawn("write_under_lock", &lane));
        }
        if at == ImportStage::Verified {
            wait_until("the writer to start", || {
                directory.join(".marker-attempting").exists()
            });
            std::thread::sleep(Duration::from_millis(300));
            // Everything is validated and uncommitted; the writer has not got in.
            assert!(!directory.join(".marker-wrote").exists());
            assert_eq!(fs::read(&source).unwrap(), original);
        }
        Ok(())
    })
    .unwrap();
    assert_eq!(report.marker.source_sha256, sha256_hex(&original));
    assert_eq!(report.marker.source_generation, 4);

    // Committed and released: now the writer lands, and its file is a later file that is
    // never merged (it is the caller's to carry across, not the import's to guess).
    wait_until("the writer to finish", || marked(&lane, "wrote"));
    writer.unwrap().wait().unwrap();
    assert_ne!(fs::read(&lane.source).unwrap(), original);
    assert_eq!(
        import_legacy_store(&lane.request()).unwrap_err(),
        ImportError::AlreadyImported
    );
}

#[test]
fn import_026_fr_025_a_missing_source_takes_no_lock_and_leaves_no_lock_file() {
    let lane = lane("document-lock-missing");
    assert_eq!(
        import_legacy_store(&lane.request()).unwrap_err(),
        ImportError::SourceMissing
    );
    assert!(!lane.directory.join(".store.json.lock").exists());
}

#[test]
fn import_026_fr_013_golden_outbox_is_carried_whole_and_the_base_counts_equal_the_source() {
    // The fixture is frozen by reference: this is the file the reference store names.
    let reference: Value = serde_json::from_slice(&fs::read(REFERENCE_STORE).unwrap()).unwrap();
    let entry = reference["oracle_sources"]
        .as_array()
        .unwrap()
        .iter()
        .find(|entry| entry["id"] == "SRC-07")
        .unwrap();
    let golden = golden_bytes();
    assert_eq!(entry["sha256"], sha256_hex(&golden));

    let lane = lane("golden");
    fs::write(&lane.source, &golden).unwrap();
    let report = import_legacy_store(&lane.request()).unwrap();

    assert!(!report.already_active);
    assert_eq!(report.marker.source_sha256, sha256_hex(&golden));
    assert_eq!(report.marker.source_version, 2);
    assert_eq!(report.marker.source_generation, 1);
    assert_eq!(
        report.marker.counts,
        SourceCounts {
            outbox_entries: 41,
            ..SourceCounts::default()
        }
    );
    assert_eq!(report.marker.aliases, 0);

    let mut store = open(&lane.database);
    assert_eq!(count(&mut store, "confirmed_records"), 0);
    assert_eq!(
        count(&mut store, "outbox"),
        0,
        "the queue is the next slice's"
    );
    // Every entry is carried verbatim, in queue order.
    let source: Value = serde_json::from_slice(&golden).unwrap();
    let entries = carried(&mut store, "legacy_outbox_entry");
    assert_eq!(entries.len(), 41);
    for (index, (draft_id, id, fields)) in entries.iter().enumerate() {
        assert_eq!(draft_id, &format!("legacy-outbox:{index:08}"));
        assert_eq!(fields, &source["outbox"][index]);
        assert_eq!(id.as_deref(), source["outbox"][index]["id"].as_str());
    }
    // The Review base and the local state are carried too.
    assert_eq!(
        carried(&mut store, "legacy_review_base")[0].2,
        source["base"]["review"]
    );
    assert_eq!(count(&mut store, "drafts"), 41 + 3);
    assert_eq!(
        legacy_import_marker(&mut store).unwrap(),
        Some(report.marker)
    );
}

#[test]
fn import_026_fr_013_every_field_id_relation_and_flag_of_a_populated_base_is_imported() {
    let lane = lane("rich");
    let bytes = lane.write_source(&rich());
    let report = import_legacy_store(&lane.request()).unwrap();

    assert_eq!(
        report.marker.counts,
        SourceCounts {
            tasks: 5,
            subtasks: 2,
            comments: 2,
            projects: 3,
            tags: 3,
            outbox_entries: 2,
            issues: 1,
            review_sessions: 1,
            review_decisions: 2,
            review_receipts: 1,
            review_park_acks: 1,
            review_bulk_releases: 0,
            review_navigator_consents: 1,
            form_drafts: 2,
        }
    );
    let mut store = open(&lane.database);
    assert_eq!(count(&mut store, "confirmed_records"), 5 + 2 + 2 + 3 + 3);
    assert_eq!(count(&mut store, "visible_records"), 15);

    // Identities: a proven server ID is the key, with an alias for the local one; an
    // unproven record keeps its local ID, shaped as the rules accept it.
    let tasks = bodies(&mut store, "task");
    assert_eq!(
        tasks.keys().cloned().collect::<Vec<_>>(),
        [
            key("task-2"),
            key("task_1a2b3c4d5e6f"),
            key("task_bbbbbbbbbbbb"),
            key("task_cccccccccccc"),
            key("task_dddddddddddd"),
        ]
    );
    let projects = bodies(&mut store, "project");
    let old_flat = format!("project_{OLD_FLAT}");
    assert_eq!(
        projects.keys().cloned().collect::<Vec<_>>(),
        [
            key("project_1a2b3c4d5e6f"),
            key(&old_flat),
            key("project_ffffffffffff")
        ]
    );
    let mut expected_aliases = [
        ("comment", "comment-2", "comment_bbbbbbbbbbbb"),
        ("project", "project-1", "project_1a2b3c4d5e6f"),
        ("project", "project-3", "project_ffffffffffff"),
        ("subtask", "subtask-2", "subtask_aaaaaaaaaaaa"),
        ("tag", "tag-2", "tag_0123456789ab"),
        ("task", "task-1", "task_1a2b3c4d5e6f"),
        ("task", "task-3", "task_bbbbbbbbbbbb"),
        ("task", "task-4", "task_cccccccccccc"),
        ("task", "task-5", "task_dddddddddddd"),
    ]
    .map(|(kind, old, new)| {
        (
            kind.to_owned(),
            old.to_owned(),
            new.to_owned(),
            "legacy-import:server-id".to_owned(),
        )
    })
    .to_vec();
    expected_aliases.push((
        "project".into(),
        OLD_FLAT.into(),
        old_flat.clone(),
        "legacy-import:normalized-local-id".into(),
    ));
    expected_aliases.sort();
    assert_eq!(aliases(&mut store), expected_aliases);

    // Fields and relations, through the rules' own record types.
    let plumber: Task = serde_json::from_value(tasks[&key("task_1a2b3c4d5e6f")].clone()).unwrap();
    assert_eq!(plumber.title.as_str(), "Call the plumber");
    assert_eq!(plumber.project_id.unwrap().as_str(), "project_1a2b3c4d5e6f");
    assert_eq!(
        plumber
            .tag_ids
            .iter()
            .map(|tag| tag.as_str())
            .collect::<Vec<_>>(),
        ["tag-1", "tag-3"]
    );
    assert_eq!(plumber.revision.as_str(), "3");
    assert_eq!(plumber.order_key.as_str(), "7");
    assert_eq!(plumber.priority.as_str(), "high");
    assert_eq!(plumber.waiting_for.unwrap().as_str(), "Plumber");
    assert_eq!(plumber.waiting_since.unwrap().as_str(), T1);
    assert_eq!(plumber.due_date.unwrap().as_str(), "2026-10-02");
    assert_eq!(plumber.created_at.as_str(), T0);
    let writer = &tasks[&key("task_cccccccccccc")];
    assert_eq!(writer["consecutive_stalled_formulations"], 2);
    assert_eq!(
        writer["formulation"]["extension_reason"],
        "Waiting for numbers"
    );
    let trip = &tasks[&key("task_dddddddddddd")];
    assert_eq!(
        trip["parked"],
        json!({"at": T1, "formulation_id": FORM_TWO})
    );
    let sofa = &tasks[&key("task_bbbbbbbbbbbb")];
    assert_eq!(sofa["state"], "completed");
    assert_eq!(sofa["completed_at"], T1);
    assert_eq!(sofa["project_id"], old_flat);

    let subtasks = bodies(&mut store, "subtask");
    let quote: Subtask =
        serde_json::from_value(subtasks[&key("subtask_aaaaaaaaaaaa")].clone()).unwrap();
    assert_eq!(quote.task_id.as_str(), "task_1a2b3c4d5e6f");
    assert_eq!(quote.revision.as_str(), "2");
    assert!(subtasks.contains_key(&key("subtask-1")));
    let comments = bodies(&mut store, "comment");
    assert_eq!(comments[&key("comment-1")]["actor_id"], "user_1");
    // The file did not say who wrote it; the account's owner did.
    assert_eq!(comments[&key("comment_bbbbbbbbbbbb")]["actor_id"], "user_1");
    assert_eq!(comments[&key("comment_bbbbbbbbbbbb")]["edited_at"], T1);

    let archived: Project = serde_json::from_value(projects[&key(&old_flat)].clone()).unwrap();
    assert!(archived.archived_before_lossless);
    assert_eq!(archived.archived_at.unwrap().as_str(), T1);
    let home: Project =
        serde_json::from_value(projects[&key("project_1a2b3c4d5e6f")].clone()).unwrap();
    assert_eq!(home.desired_outcome.unwrap().as_str(), "A calm house");
    assert_eq!(home.color.unwrap().as_str(), "#0EA5E9");
    let tags = bodies(&mut store, "tag");
    let deleted: Tag = serde_json::from_value(tags[&key("tag_0123456789ab")].clone()).unwrap();
    assert_eq!(deleted.name.as_str(), "@home");
    assert_eq!(tags[&key("tag_0123456789ab")]["state"], "deleted");

    // Local-only facts survive beside the records.
    let local = carried(&mut store, "legacy_task_local");
    assert_eq!(
        local.iter().map(|(_, _, f)| f.clone()).collect::<Vec<_>>(),
        [
            json!({"childrenSyncedAt": T1}),
            json!({"lastOpenList": "next"}),
            json!({"parked": {"at": T1, "formulationID": FORM_TWO, "fromRevision": 5,
                "stalledBefore": 1, "clockBefore": {"id": FORM_TWO, "startedAt": T0}}}),
        ]
    );
    assert_eq!(report.marker.local_task_facts, 3);

    // The account is linked in the workspace, and the projection is built.
    let (account, link, generation, stale): (String, String, i64, i64) = store
        .read(|tx| {
            tx.query_row(
                "SELECT account_id, account_link_state, projection_generation, projection_stale
                 FROM sync_meta",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
        })
        .unwrap();
    assert_eq!(
        (account.as_str(), link.as_str(), stale),
        ("user_1", "linked", 0)
    );
    assert!(generation >= 1);

    // The source is exactly as it was, and its backup is byte for byte.
    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
    let backup = lane.directory.join(&report.marker.backup_file);
    assert_eq!(fs::read(&backup).unwrap(), bytes);
    assert_eq!(
        fs::metadata(&backup).unwrap().permissions().mode() & 0o777,
        0o600
    );
}

#[test]
fn import_026_fr_010_review_state_local_state_drafts_and_pending_work_are_kept_verbatim() {
    let lane = lane("verbatim");
    let document = rich();
    lane.write_source(&document);
    import_legacy_store(&lane.request()).unwrap();
    let mut store = open(&lane.database);

    assert_eq!(
        carried(&mut store, "legacy_review_base")[0].2,
        document["base"]["review"]
    );
    let mut local = document["local"].clone();
    local.as_object_mut().unwrap().remove("formDrafts");
    assert_eq!(carried(&mut store, "legacy_local_review")[0].2, local);
    assert_eq!(
        carried(&mut store, "legacy_sync_metadata")[0].2,
        document["sync"]
    );
    assert_eq!(
        carried(&mut store, "legacy_account")[0].2,
        document["account"]
    );

    // Drafts are the user's unsaved text, keyed by their own key and dated by it.
    let forms = carried(&mut store, "review_form_draft");
    assert_eq!(forms.len(), 2);
    for (draft_id, form_key, fields) in &forms {
        let form_key = form_key.as_ref().unwrap();
        assert_eq!(draft_id, &format!("legacy-form:{form_key}"));
        assert_eq!(fields, &document["local"]["formDrafts"][form_key]);
    }
    let updated: Vec<String> = store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT updated_at FROM drafts WHERE editor_kind = 'review_form_draft'
                 ORDER BY draft_id",
            )?;
            let rows = statement.query_map([], |row| row.get(0))?;
            rows.collect()
        })
        .unwrap();
    assert_eq!(updated, [T1, T0]);

    // The pending operations and the issue are kept exactly, ever-sent flag and all.
    let outbox = carried(&mut store, "legacy_outbox_entry");
    assert_eq!(outbox[0].2, document["outbox"][0]);
    assert_eq!(outbox[1].2, document["outbox"][1]);
    assert_eq!(outbox[1].2["everSent"], true);
    assert_eq!(
        carried(&mut store, "legacy_sync_issue")[0].2,
        document["issues"][0]
    );
    assert_eq!(count(&mut store, "outbox"), 0);
    assert_eq!(count(&mut store, "sync_issues"), 0);
}

#[test]
fn import_026_fr_013_nothing_is_merged_and_awkward_text_is_carried_exactly() {
    // The strings of the Mac "awkward" fixture, as the kit stores them: NFKC-sensitive
    // names, doubled spaces, an "@" prefix, emoji, and names two active records share.
    let awkward: Value =
        serde_json::from_slice(&fs::read(format!("{MAC_RESOURCES}/legacy-awkward.json")).unwrap())
            .unwrap();
    let mut titles: Vec<String> = Vec::new();
    for section in ["tasks", "projects", "tags"] {
        for record in awkward[section].as_array().unwrap() {
            for field in ["title", "name"] {
                if let Some(text) = record[field].as_str()
                    && (1..=500).contains(&text.chars().count())
                {
                    titles.push(text.to_owned());
                }
            }
        }
    }
    titles.extend(
        [
            "Квартира №5",
            "™ Ideas",
            "Home  Repair",
            "Home Repair",
            "@home",
            "home",
            "👍🏽 Call  mom ",
        ]
        .map(str::to_owned),
    );
    assert!(titles.len() > 8, "the awkward fixture supplies its strings");

    let mut projects = serde_json::Map::new();
    let mut tags = serde_json::Map::new();
    let mut tasks = serde_json::Map::new();
    for (index, text) in titles.iter().enumerate() {
        let id = format!("{index:04}");
        projects.insert(
            format!("p{id}"),
            json!({"id": format!("p{id}"), "name": text, "state": "active", "createdAt": T0}),
        );
        tags.insert(
            format!("g{id}"),
            json!({"id": format!("g{id}"), "name": text, "state": "active", "createdAt": T0}),
        );
        tasks.insert(
            format!("t{id}"),
            json!({"id": format!("t{id}"), "title": text, "details": text, "state": "inbox",
                "projectID": format!("p{id}"), "tagIDs": [format!("g{id}")], "priority": "none",
                "orderKey": index, "createdAt": T0, "updatedAt": T0, "subtasks": [], "comments": []}),
        );
    }
    let document = json!({
        "version": 2, "generation": 1,
        "base": {"projects": projects, "tags": tags, "tasks": tasks, "review": {}},
        "outbox": [], "issues": [], "sync": {}
    });
    let lane = lane("awkward");
    lane.write_source(&document);
    let report = import_legacy_store(&lane.request()).unwrap();
    assert_eq!(report.marker.counts.tasks, titles.len() as u64);

    let mut store = open(&lane.database);
    let stored_tasks = bodies(&mut store, "task");
    let stored_projects = bodies(&mut store, "project");
    let stored_tags = bodies(&mut store, "tag");
    // One record per source record (equal names did not merge), text byte for byte.
    assert_eq!(stored_tasks.len(), titles.len());
    assert_eq!(stored_projects.len(), titles.len());
    assert_eq!(stored_tags.len(), titles.len());
    for (index, text) in titles.iter().enumerate() {
        let id = format!("{index:04}");
        let task = &stored_tasks[&key(&legacy_record_key(
            EntityType::Task,
            &format!("t{id}"),
            None,
        ))];
        assert_eq!(task["title"], text.as_str());
        assert_eq!(task["details"], text.as_str());
        let project = &stored_projects[&key(&format!("p{id}"))];
        assert_eq!(project["name"], text.as_str());
        assert_eq!(task["project_id"], format!("p{id}"));
        assert_eq!(stored_tags[&key(&format!("g{id}"))]["name"], text.as_str());
        assert_eq!(task["tag_ids"], json!([format!("g{id}")]));
    }
    assert!(aliases(&mut store).is_empty(), "no server ID was proven");
}

#[test]
fn import_026_fr_013_unproven_ids_get_a_deterministic_key_and_proven_ids_stay_verbatim() {
    let uuid = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
    assert_eq!(
        legacy_record_key(EntityType::Task, uuid, None),
        format!("task_{uuid}")
    );
    assert_eq!(
        legacy_record_key(EntityType::Task, &format!("task_{uuid}"), None),
        format!("task_{uuid}")
    );
    assert_eq!(legacy_record_key(EntityType::Tag, "tag-1", None), "tag-1");
    assert_eq!(
        legacy_record_key(EntityType::Project, uuid, Some("project_1a2b3c4d5e6f")),
        "project_1a2b3c4d5e6f"
    );
    // An uppercase UUID is not the lowercase shape the rules mint: it crosses unchanged.
    let upper = uuid.to_uppercase();
    assert_eq!(legacy_record_key(EntityType::Task, &upper, None), upper);
}

#[test]
fn import_026_fr_013_unsynced_normalization_persists_exact_reverse_alias_proof() {
    let lane = lane("normalized-reverse-proof");
    let uuid = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
    let source = json!({"version":2,"generation":1,"base":{"tasks":{uuid:{"id":uuid,"title":"Unsynced task","state":"next","tagIDs":[],"priority":"none","orderKey":0,"createdAt":NOW,"updatedAt":NOW,"subtasks":[],"comments":[]}},"projects":{},"tags":{}},"outbox":[],"issues":[],"local":{"formDrafts":{format!("form:reformulate:{uuid}:-"):{"text":"Exact source-key draft","savedAt":NOW}}}});
    lane.write_source(&source);
    let report = import_legacy_store(&lane.request()).unwrap();
    assert_eq!(report.marker.aliases, 1);
    let mut store = open(&lane.database);
    assert_eq!(
        bb_client::reverse_workspace_identities(
            &mut store,
            &[(EntityType::Task, format!("task_{uuid}"))]
        )
        .unwrap(),
        vec![Some(uuid.to_owned())]
    );
    assert_eq!(
        aliases(&mut store)[0].3,
        "legacy-import:normalized-local-id"
    );
    let form = bb_client::load_review_form(
        &mut store,
        &format!("form:reformulate:task_{uuid}:-"),
        &Instant::parse(NOW).unwrap(),
    )
    .unwrap();
    assert_eq!(form.source_key, format!("form:reformulate:{uuid}:-"));
    assert_eq!(form.draft.unwrap().text, "Exact source-key draft");
}

#[test]
fn import_026_fr_013_a_dangling_or_repeated_identity_stops_with_the_source_intact() {
    let cases: Vec<TamperCase> = vec![
        (
            "missing-project",
            Box::new(|d| d["base"]["tasks"]["task-2"]["projectID"] = json!("project-404")),
            "task_project",
        ),
        (
            "missing-tag",
            Box::new(|d| d["base"]["tasks"]["task-2"]["tagIDs"] = json!(["tag-404"])),
            "task_tag",
        ),
        (
            "same-server-id",
            Box::new(|d| d["base"]["tasks"]["task-2"]["serverID"] = json!("task_1a2b3c4d5e6f")),
            "duplicate_identity",
        ),
        (
            "key-mismatch",
            Box::new(|d| d["base"]["tasks"]["task-2"]["id"] = json!("task-22")),
            "task",
        ),
        (
            "negative-order",
            Box::new(|d| d["base"]["tasks"]["task-2"]["orderKey"] = json!(-1)),
            "order_key",
        ),
        (
            "over-long-title",
            Box::new(|d| d["base"]["tasks"]["task-2"]["title"] = json!("x".repeat(501))),
            "record",
        ),
        (
            "unknown-state",
            Box::new(|d| d["base"]["tasks"]["task-2"]["state"] = json!("archived")),
            "record",
        ),
    ];
    for (name, tamper, field) in cases {
        let lane = lane(&format!("inconsistent-{name}"));
        let mut document = rich();
        tamper(&mut document);
        let bytes = lane.write_source(&document);
        let error = import_legacy_store(&lane.request()).unwrap_err();
        assert_eq!(
            error,
            ImportError::SourceInconsistent { field },
            "case {name}"
        );
        assert_eq!(error.code(), "IMPORT_SOURCE_INCONSISTENT");
        assert_eq!(fs::read(&lane.source).unwrap(), bytes);
        assert!(lane.backups().is_empty(), "case {name}: nothing is written");
        assert!(!lane.database.exists(), "case {name}: no store is created");
    }
}

#[test]
fn import_026_fr_022_a_member_this_build_does_not_carry_is_refused_not_dropped() {
    let cases: Vec<TamperCase> = vec![
        (
            "task",
            Box::new(|d| d["base"]["tasks"]["task-2"]["colour"] = json!("red")),
            "task",
        ),
        (
            "project",
            Box::new(|d| d["base"]["projects"]["project-1"]["icon"] = json!("house")),
            "project",
        ),
        (
            "document",
            Box::new(|d| d["widgetState"] = json!({})),
            "document",
        ),
        (
            "parked",
            Box::new(|d| d["base"]["tasks"]["task-5"]["parked"]["reason"] = json!("sweep")),
            "parked",
        ),
    ];
    for (name, tamper, field) in cases {
        let lane = lane(&format!("unknown-{name}"));
        let mut document = rich();
        tamper(&mut document);
        lane.write_source(&document);
        let error = import_legacy_store(&lane.request()).unwrap_err();
        assert_eq!(
            error,
            ImportError::SourceUnsupported {
                found: None,
                field: Some(field)
            },
            "case {name}"
        );
        assert!(!lane.database.exists());
    }
}

#[test]
fn import_026_fr_022_a_newer_source_version_fails_before_anything_is_written() {
    let lane = lane("newer");
    let mut document = rich();
    document["version"] = json!(3);
    let bytes = lane.write_source(&document);
    let error = import_legacy_store(&lane.request()).unwrap_err();
    assert_eq!(
        error,
        ImportError::SourceUnsupported {
            found: Some(3),
            field: Some("version")
        }
    );
    assert_eq!(error.code(), "IMPORT_SOURCE_UNSUPPORTED");
    assert!(!error.is_retryable());
    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
    assert!(lane.backups().is_empty());
    assert!(!lane.database.exists());

    // The Mac fixture of the same name is the pre-021 file shape (its own importer
    // reads it): it is not a StoreDocument and is left alone.
    let mac = fs::read(format!("{MAC_RESOURCES}/legacy-newer.json")).unwrap();
    fs::write(&lane.source, &mac).unwrap();
    assert_eq!(
        import_legacy_store(&lane.request()).unwrap_err(),
        ImportError::SourceUnreadable { field: "document" }
    );
    assert_eq!(fs::read(&lane.source).unwrap(), mac);
}

#[test]
fn import_026_fr_022_corrupt_and_foreign_sources_fail_before_switching_and_stay_as_they_are() {
    let lane = lane("corrupt");
    let corrupt = fs::read(format!("{MAC_RESOURCES}/legacy-corrupt.json")).unwrap();
    let pre_021 = fs::read(format!("{MAC_RESOURCES}/legacy-awkward.json")).unwrap();
    let cases: Vec<(&str, Vec<u8>, ImportError)> = vec![
        (
            "truncated",
            corrupt,
            ImportError::SourceUnreadable { field: "json" },
        ),
        (
            "pre-021",
            pre_021,
            ImportError::SourceUnreadable { field: "document" },
        ),
        (
            "empty",
            Vec::new(),
            ImportError::SourceUnreadable { field: "json" },
        ),
        (
            "not-utf8",
            vec![0xff, 0xfe, 0x00],
            ImportError::SourceUnreadable { field: "encoding" },
        ),
        (
            "duplicate-key",
            br#"{"version":2,"version":2}"#.to_vec(),
            ImportError::SourceUnreadable { field: "json" },
        ),
        (
            "version-zero",
            br#"{"version":0,"generation":1}"#.to_vec(),
            ImportError::SourceUnreadable { field: "version" },
        ),
        (
            "no-base",
            br#"{"version":2,"generation":1}"#.to_vec(),
            ImportError::SourceUnreadable { field: "document" },
        ),
    ];
    for (name, bytes, expected) in cases {
        fs::write(&lane.source, &bytes).unwrap();
        let error = import_legacy_store(&lane.request()).unwrap_err();
        assert_eq!(error, expected, "case {name}");
        assert_eq!(error.code(), "IMPORT_SOURCE_UNREADABLE");
        assert_eq!(fs::read(&lane.source).unwrap(), bytes, "case {name}");
        assert!(lane.backups().is_empty(), "case {name}");
        assert!(!lane.database.exists(), "case {name}");
    }

    fs::remove_file(&lane.source).unwrap();
    assert_eq!(
        import_legacy_store(&lane.request()).unwrap_err(),
        ImportError::SourceMissing
    );
}

#[test]
fn import_026_sc_005_a_store_of_an_unsupported_epoch_fails_before_switching() {
    let lane = lane("epoch");
    let bytes = lane.write_source(&rich());
    open(&lane.database).close().unwrap();
    let newer = SCHEMA_VERSION + 1;
    Connection::open(&lane.database)
        .unwrap()
        .pragma_update(None, "user_version", newer)
        .unwrap();

    let error = import_legacy_store(&lane.request()).unwrap_err();
    assert_eq!(
        error,
        ImportError::Store(StoreError::UpgradeRequired { found: newer })
    );
    assert_eq!(error.code(), "STORE_UPGRADE_REQUIRED");
    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
    assert!(
        lane.backups().is_empty(),
        "nothing is written for a store that cannot take it"
    );
    let store = open(&lane.database);
    assert_eq!(
        store.status(),
        StoreStatus::ReadOnlyRecovery { found: newer }
    );
}

#[test]
fn import_026_sc_005_a_corrupt_store_file_fails_before_switching_and_is_left_as_it_is() {
    let lane = lane("corrupt-store");
    let bytes = lane.write_source(&rich());
    fs::create_dir_all(lane.database.parent().unwrap()).unwrap();
    let garbage = b"this is not a database, and it is somebody's only copy".repeat(100);
    fs::write(&lane.database, &garbage).unwrap();

    let error = import_legacy_store(&lane.request()).unwrap_err();
    assert_eq!(error, ImportError::Store(StoreError::Corrupt));
    assert_eq!(fs::read(&lane.database).unwrap(), garbage);
    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
    assert!(lane.backups().is_empty());
}

#[test]
fn import_026_sc_005_a_full_disk_at_any_stage_fails_before_switching_and_a_retry_succeeds() {
    for stage in [
        ImportStage::Staged(0),
        ImportStage::Installed,
        ImportStage::Verified,
    ] {
        let lane = lane("full");
        let bytes = lane.write_source(&rich());
        let error = import_legacy_store_with(&lane.request(), |at, _| {
            if at == stage {
                Err(full_disk())
            } else {
                Ok(())
            }
        })
        .unwrap_err();
        assert_eq!(error, ImportError::Store(StoreError::Full), "{stage:?}");
        assert_eq!(error.code(), "STORE_FULL");
        assert_eq!(fs::read(&lane.source).unwrap(), bytes);
        assert_untouched_store(&lane.database);

        // Space freed: the same call imports, and does not duplicate the backup.
        let report = import_legacy_store(&lane.request()).unwrap();
        assert!(!report.already_active);
        assert_eq!(lane.backups().len(), 2);
    }
}

#[test]
fn import_026_sc_005_a_database_that_really_fills_up_rolls_the_activation_back() {
    let lane = lane("really-full");
    let bytes = lane.write_source(&rich());
    // The first staged page is written; from then on the database may not grow.
    let error = import_legacy_store_with(&lane.request(), |at, tx| {
        if at == ImportStage::Staged(0) {
            let pages: i64 = tx.query_row("PRAGMA page_count", [], |row| row.get(0))?;
            tx.pragma_update(None, "max_page_count", pages)?;
        }
        Ok(())
    })
    .unwrap_err();
    assert_eq!(error, ImportError::Store(StoreError::Full));
    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
    assert_untouched_store(&lane.database);
    import_legacy_store(&lane.request()).unwrap();
}

#[test]
fn import_026_fr_010_a_crash_while_staging_leaves_the_original_active_and_the_rerun_imports() {
    let lane = lane("crash-staging");
    let bytes = lane.write_source(&rich());
    let mut child = spawn("abort_while_staging", &lane);
    wait_for(&mut child, "staged");
    assert!(!child.wait().unwrap().success(), "the child aborts");

    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
    assert_untouched_store(&lane.database);
    let report = import_legacy_store(&lane.request()).unwrap();
    assert!(!report.already_active);
    let mut store = open(&lane.database);
    assert_eq!(count(&mut store, "confirmed_records"), 15);
    assert_eq!(count(&mut store, "staging_pages"), 0);
    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
}

#[test]
fn import_026_fr_010_a_crash_before_the_commit_switches_nothing_and_the_rerun_imports_once() {
    let lane = lane("crash-before");
    let bytes = lane.write_source(&rich());
    let mut child = spawn("abort_before_commit", &lane);
    wait_for(&mut child, "verified");
    assert!(!child.wait().unwrap().success(), "the child aborts");

    // The activation was never committed: the staged bytes are all there is of it.
    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
    assert_untouched_store(&lane.database);
    let report = import_legacy_store(&lane.request()).unwrap();
    assert!(!report.already_active);
    let mut store = open(&lane.database);
    assert_eq!(count(&mut store, "confirmed_records"), 15);
    assert_eq!(count(&mut store, "identity_aliases"), 10);
    let integrity: String = store
        .read(|tx| tx.query_row("PRAGMA integrity_check", [], |row| row.get(0)))
        .unwrap();
    assert_eq!(integrity, "ok");
}

#[test]
fn import_026_fr_010_a_committed_import_survives_a_crash_and_a_rerun_does_nothing() {
    let lane = lane("crash-after");
    let bytes = lane.write_source(&rich());
    let mut child = spawn("abort_after_commit", &lane);
    wait_for(&mut child, "committed");
    assert!(!child.wait().unwrap().success(), "the child aborts");

    let mut store = open(&lane.database);
    let marker = legacy_import_marker(&mut store)
        .unwrap()
        .expect("the marker is durable");
    assert_eq!(count(&mut store, "confirmed_records"), 15);
    store.close().unwrap();

    let again = import_legacy_store(&lane.request()).unwrap();
    assert!(again.already_active);
    assert_eq!(again.marker, marker);
    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
    assert_eq!(lane.backups().len(), 2);
}

#[test]
fn import_026_fr_025_a_held_migration_lock_makes_the_import_busy_not_wrong() {
    let lane = lane("locked");
    let bytes = lane.write_source(&rich());
    open(&lane.database).close().unwrap();
    let mut child = spawn("hold_migration_lock", &lane);
    wait_for(&mut child, "holding");

    let mut request = lane.request();
    request.store.busy_timeout = Duration::from_millis(150);
    let error = import_legacy_store(&request).unwrap_err();
    assert_eq!(error, ImportError::Store(StoreError::Busy));
    assert!(error.is_retryable());
    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
    assert!(lane.backups().is_empty());

    child.kill().unwrap();
    child.wait().unwrap();
    assert!(import_legacy_store(&lane.request()).is_ok());
}

#[test]
fn import_026_fr_010_the_same_file_is_idempotent_and_a_different_one_is_never_merged() {
    let lane = lane("idempotent");
    lane.write_source(&rich());
    let first = import_legacy_store(&lane.request()).unwrap();
    let again = import_legacy_store(&lane.request()).unwrap();
    assert!(again.already_active);
    assert_eq!(again.marker, first.marker);

    // A later file (an older copy that wrote, a restored backup) is not imported.
    let mut later = rich();
    later["base"]["tasks"]["task-2"]["title"] = json!("Written by an older build");
    let later_bytes = lane.write_source(&later);
    let error = import_legacy_store(&lane.request()).unwrap_err();
    assert_eq!(error, ImportError::AlreadyImported);
    assert_eq!(error.code(), "IMPORT_ALREADY_IMPORTED");
    assert_eq!(fs::read(&lane.source).unwrap(), later_bytes);
    let mut store = open(&lane.database);
    assert_eq!(count(&mut store, "confirmed_records"), 15);
    let titles = bodies(&mut store, "task");
    assert_eq!(titles[&key("task-2")]["title"], "Renovate the bathroom");
}

#[test]
fn import_026_fr_025_a_store_with_data_of_its_own_is_never_overwritten() {
    let lane = lane("in-use");
    let bytes = lane.write_source(&rich());
    let mut store = open(&lane.database);
    store
        .write(|tx| {
            tx.execute(
                "INSERT INTO drafts (workspace_id, draft_id, editor_kind, fields, updated_at)
                 VALUES (?1, 'mine', 'task', x'7b7d', ?2)",
                params![WORKSPACE, NOW],
            )
        })
        .unwrap();
    store.close().unwrap();

    let error = import_legacy_store(&lane.request()).unwrap_err();
    assert_eq!(error, ImportError::TargetInUse);
    assert_eq!(error.code(), "IMPORT_TARGET_IN_USE");
    assert_eq!(fs::read(&lane.source).unwrap(), bytes);
    assert!(lane.backups().is_empty());
    let mut store = open(&lane.database);
    assert_eq!(count(&mut store, "drafts"), 1);
    assert_eq!(count(&mut store, "confirmed_records"), 0);
}

#[test]
fn import_026_sc_005_a_source_that_changes_during_the_import_is_refused() {
    let lane = lane("changed");
    lane.write_source(&rich());
    let source = lane.source.clone();
    let error = import_legacy_store_with(&lane.request(), |at, _| {
        if at == ImportStage::Staged(0) {
            // A widget wrote the file after it was read.
            let mut newer = rich();
            newer["generation"] = json!(5);
            fs::write(&source, serde_json::to_vec(&newer).unwrap()).unwrap();
        }
        Ok(())
    })
    .unwrap_err();
    assert_eq!(error, ImportError::SourceChanged);
    assert!(error.is_retryable());
    assert_untouched_store(&lane.database);

    // Run again over the file as it is now.
    let report = import_legacy_store(&lane.request()).unwrap();
    assert_eq!(report.marker.source_generation, 5);
}

#[test]
fn import_026_sc_005_counts_from_an_independent_reader_must_agree_before_the_store_is_touched() {
    let lane = lane("expected");
    lane.write_source(&rich());
    let report = import_legacy_store(&{
        let mut request = lane.request();
        request.expected = Some(SourceCounts {
            tasks: 6,
            ..counts_of_rich()
        });
        request
    });
    assert_eq!(
        report.unwrap_err(),
        ImportError::VerificationFailed {
            check: "expected_counts"
        }
    );
    assert!(!lane.database.exists());
    assert!(lane.backups().is_empty());

    let mut request = lane.request();
    request.expected = Some(counts_of_rich());
    assert!(import_legacy_store(&request).is_ok());
}

fn counts_of_rich() -> SourceCounts {
    SourceCounts {
        tasks: 5,
        subtasks: 2,
        comments: 2,
        projects: 3,
        tags: 3,
        outbox_entries: 2,
        issues: 1,
        review_sessions: 1,
        review_decisions: 2,
        review_receipts: 1,
        review_park_acks: 1,
        review_bulk_releases: 0,
        review_navigator_consents: 1,
        form_drafts: 2,
    }
}

#[test]
fn import_026_sc_005_validation_stops_the_switch_when_the_rows_do_not_equal_the_source() {
    type Tamper = fn(&rusqlite::Transaction<'_>) -> rusqlite::Result<()>;
    let cases: [(&str, Tamper, &str); 7] = [
        (
            "a record is missing",
            |tx| {
                tx.execute("DELETE FROM confirmed_records WHERE record_type = 'tag' AND record_key = '[\"tag-1\"]'", [])
                    .map(drop)
            },
            "record_counts",
        ),
        (
            "a flag differs",
            |tx| {
                tx.execute(
                    "UPDATE confirmed_records SET body = CAST(replace(CAST(body AS TEXT), '\"archived_before_lossless\":true', '\"archived_before_lossless\":false') AS BLOB) WHERE record_type = 'project'",
                    [],
                )
                .map(drop)
            },
            "lossless_archives",
        ),
        (
            "a link is cut",
            |tx| {
                tx.execute(
                    "UPDATE confirmed_records SET body = CAST(replace(CAST(body AS TEXT), '\"project_id\":\"project_1a2b3c4d5e6f\"', '\"project_id\":null') AS BLOB) WHERE record_type = 'task'",
                    [],
                )
                .map(drop)
            },
            "task_project_links",
        ),
        (
            "a field differs",
            |tx| {
                tx.execute(
                    "UPDATE confirmed_records SET body = CAST(replace(CAST(body AS TEXT), 'Call the plumber', 'Call the electrician') AS BLOB) WHERE record_type = 'task'",
                    [],
                )
                .map(drop)
            },
            "records",
        ),
        (
            "an alias is missing",
            |tx| {
                tx.execute(
                    "DELETE FROM identity_aliases WHERE old_local_id = 'task-1'",
                    [],
                )
                .map(drop)
            },
            "aliases",
        ),
        (
            "a carried entry is altered",
            |tx| {
                tx.execute(
                    "UPDATE drafts SET fields = x'7b7d' WHERE draft_id = 'legacy-outbox:00000001'",
                    [],
                )
                .map(drop)
            },
            "verbatim_sections",
        ),
        (
            "a relation dangles",
            |tx| {
                tx.execute(
                    "UPDATE confirmed_records SET body = CAST(replace(CAST(body AS TEXT), '\"task_id\":\"task_1a2b3c4d5e6f\"', '\"task_id\":\"task_gone\"') AS BLOB) WHERE record_type = 'subtask'",
                    [],
                )
                .map(drop)
            },
            "records",
        ),
    ];
    for (name, tamper, check) in cases {
        let lane = lane("tamper");
        let bytes = lane.write_source(&rich());
        let error = import_legacy_store_with(&lane.request(), |at, tx| {
            if at == ImportStage::Installed {
                tamper(tx)?;
            }
            Ok(())
        })
        .unwrap_err();
        assert_eq!(error, ImportError::VerificationFailed { check }, "{name}");
        assert_eq!(error.code(), "IMPORT_VERIFICATION_FAILED");
        assert_eq!(fs::read(&lane.source).unwrap(), bytes, "{name}");
        assert_untouched_store(&lane.database);
        // The staging was dropped with the failure: nothing waits to be activated.
        let mut store = open(&lane.database);
        assert_eq!(count(&mut store, "staging_pages"), 0, "{name}");
        // And the import is still possible afterwards.
        assert!(import_legacy_store(&lane.request()).is_ok(), "{name}");
    }
}

#[test]
fn import_026_fr_013_the_backup_and_the_schema_manifest_describe_the_source_without_its_text() {
    let lane = lane("manifest");
    let bytes = lane.write_source(&rich());
    let report = import_legacy_store(&lane.request()).unwrap();

    assert_eq!(lane.backups().len(), 2);
    let manifest_path = lane.directory.join(&report.marker.manifest_file);
    let manifest_bytes = fs::read(&manifest_path).unwrap();
    let manifest: Value = serde_json::from_slice(&manifest_bytes).unwrap();
    assert_eq!(manifest["schema"], "brainbuddy-legacy-source-manifest/v1");
    assert_eq!(manifest["source_version"], 2);
    assert_eq!(manifest["source_generation"], 4);
    assert_eq!(manifest["source_bytes"], bytes.len());
    assert_eq!(manifest["source_sha256"], sha256_hex(&bytes));
    assert_eq!(manifest["backup_file"], report.marker.backup_file.as_str());
    assert_eq!(manifest["counts"]["tasks"], 5);
    assert_eq!(manifest["counts"]["outbox_entries"], 2);
    assert_eq!(manifest["records"]["task"], 5);
    assert_eq!(manifest["sections"].as_object().unwrap().len(), 7);
    // Counts and digests, never text: the manifest may be shared in a bug report.
    let text = String::from_utf8(manifest_bytes).unwrap();
    for secret in [SENTINEL, "Call the plumber", "sam@example.com", "Plumber"] {
        assert!(!text.contains(secret), "the manifest leaks {secret}");
    }
    assert_eq!(
        fs::metadata(&manifest_path).unwrap().permissions().mode() & 0o777,
        0o600
    );
    // The marker holds no text either.
    let marker = serde_json::to_string(&report.marker).unwrap();
    assert!(!marker.contains("Call the plumber") && !marker.contains(SENTINEL));
}

#[test]
fn import_026_fr_022_no_failure_carries_user_text_in_its_code_field_or_rendering() {
    let mut messages = Vec::new();
    for tamper in [
        (|d: &mut Value| d["base"]["tasks"]["task-2"]["projectID"] = json!("project-404"))
            as fn(&mut Value),
        |d| d["base"]["tasks"]["task-2"]["title"] = json!(format!("{SENTINEL}{}", "x".repeat(501))),
        |d| d["base"]["tasks"]["task-2"][SENTINEL] = json!(SENTINEL),
        |d| d["version"] = json!(9),
    ] {
        let lane = lane("text");
        let mut document = rich();
        tamper(&mut document);
        lane.write_source(&document);
        let error = import_legacy_store(&lane.request()).unwrap_err();
        messages.push(format!(
            "{error:?} {error} {} {:?}",
            error.code(),
            error.field()
        ));
    }
    for message in messages {
        assert!(!message.contains(SENTINEL), "{message}");
    }
}

#[test]
fn import_026_fr_013_an_empty_base_with_no_pending_work_imports_to_an_empty_verified_store() {
    let lane = lane("empty");
    lane.write_source(&json!({
        "version": 1, "generation": 0,
        "base": {"projects": {}, "tags": {}, "tasks": {}},
        "outbox": [], "issues": [], "sync": {}
    }));
    let report = import_legacy_store(&lane.request()).unwrap();
    assert_eq!(report.marker.source_version, 1);
    assert_eq!(report.marker.counts, SourceCounts::default());
    let mut store = open(&lane.database);
    assert_eq!(count(&mut store, "confirmed_records"), 0);
    assert!(legacy_import_marker(&mut store).unwrap().is_some());
    let link: String = store
        .read(|tx| tx.query_row("SELECT account_link_state FROM sync_meta", [], |r| r.get(0)))
        .unwrap();
    assert_eq!(link, "unchosen", "no account, no link");
}

#[test]
fn import_026_fr_025_a_large_base_stages_in_several_pages_and_imports_whole() {
    let lane = lane("large");
    let mut tasks = serde_json::Map::new();
    for index in 0..1_500 {
        let id = format!("task-{index}");
        tasks.insert(
            id.clone(),
            json!({"id": id, "serverID": format!("task_{index:012x}"), "serverRevision": 1,
                "title": format!("Task number {index} {}", "words ".repeat(40)),
                "details": "d".repeat(400), "state": "next", "tagIDs": [], "priority": "none",
                "orderKey": index, "createdAt": T0, "updatedAt": T0, "subtasks": [], "comments": []}),
        );
    }
    lane.write_source(&json!({
        "version": 2, "generation": 7,
        "base": {"projects": {}, "tags": {}, "tasks": tasks, "review": {}},
        "outbox": [], "issues": [], "sync": {}
    }));
    let mut pages = 0;
    let report = import_legacy_store_with(&lane.request(), |at, _| {
        if let ImportStage::Staged(index) = at {
            pages = index + 1;
        }
        Ok(())
    })
    .unwrap();
    assert!(
        pages > 1,
        "the stream spans several staged pages, got {pages}"
    );
    assert_eq!(report.marker.counts.tasks, 1_500);
    let mut store = open(&lane.database);
    assert_eq!(count(&mut store, "confirmed_records"), 1_500);
    assert_eq!(count(&mut store, "identity_aliases"), 1_500);
    assert_eq!(count(&mut store, "staging_pages"), 0);
}

// Review activation admission and transaction tests. The mapping oracle is
// explicit fixture data; production conversion remains the existing Swift codec.
fn review_fixture() -> Value {
    serde_json::from_str(include_str!("fixtures/legacy-review-activation.json")).unwrap()
}
fn review_context() -> bb_client::ExecuteContext {
    bb_client::ExecuteContext {
        now: Instant::parse(NOW).unwrap(),
        time_zone: bb_domain::types::ZoneName::new("UTC").unwrap(),
        actor_id: bb_domain::types::ActorId::parse("local").unwrap(),
        policy: bb_domain::types::Policy {
            weekly_review: true,
            navigator_provider: None,
            navigator_available: false,
            consent_text_version: 1,
        },
    }
}
fn review_lane(name: &str) -> (Lane, Store, bb_client::PreparedLegacyReview) {
    review_lane_with(name, review_fixture())
}
fn review_lane_with(name: &str, fixture: Value) -> (Lane, Store, bb_client::PreparedLegacyReview) {
    let lane = lane(name);
    let mut source: Value = serde_json::from_slice(&golden_bytes()).unwrap();
    source["base"]["review"] = fixture["source_review"].clone();
    source["base"]["tasks"] = fixture["source_tasks"].clone();
    source["outbox"] = json!([]);
    lane.write_source(&source);
    import_legacy_store(&lane.request()).unwrap();
    let mut store = open(&lane.database);
    let capture = bb_client::capture_legacy_review(&mut store).unwrap();
    assert_eq!(capture.review, fixture["source_review"]);
    let prepared = bb_client::PreparedLegacyReview {
        token: capture.token,
        read_set: serde_json::from_value(fixture["expected_read_set"].clone()).unwrap(),
        aliases: vec![],
        derived_counts: serde_json::from_value(fixture["expected_derived_counts"].clone()).unwrap(),
    };
    (lane, store, prepared)
}

#[test]
fn review_activation_026_fr_013_atomic_rollback_then_retry_preserves_later_canonical_writes() {
    let (lane, mut store, prepared) = review_lane("review-atomic");
    let carrier = carried(&mut store, "legacy_review_base");
    let tasks = bodies(&mut store, "task");
    assert_eq!(
        bb_client::activate_legacy_review_with(&mut store, &review_context(), &prepared, |_| Err(
            bb_client::LegacyReviewError::Cancelled
        )),
        Err(bb_client::LegacyReviewError::Cancelled)
    );
    assert!(bodies(&mut store, "review_session").is_empty());
    assert!(
        !bb_client::capture_legacy_review(&mut store)
            .unwrap()
            .already_active
    );
    let first =
        bb_client::activate_legacy_review(&mut store, &review_context(), &prepared).unwrap();
    assert!(!first.already_active);
    assert_eq!(bodies(&mut store, "task"), tasks);
    assert_eq!(carried(&mut store, "legacy_review_base"), carrier);
    assert_eq!(
        bb_client::visible_snapshot(&mut store)
            .unwrap()
            .records
            .iter()
            .filter(|record| record.entity_type().as_str().starts_with("review_"))
            .count(),
        8
    );
    // Subsequent canonical edits do not invalidate a completed migration marker.
    store.write(|tx| {
        let body: Vec<u8> = tx.query_row("SELECT body FROM confirmed_records WHERE record_type = 'review_settings'", [], |r| r.get(0))?;
        let mut value: Value = serde_json::from_slice(&body).unwrap(); value["threshold_days"] = json!(28);
        tx.execute("UPDATE confirmed_records SET body=?1,record_version='1' WHERE record_type='review_settings'", [serde_json::to_vec(&value).unwrap()])?;
        tx.execute("UPDATE sync_meta SET projection_generation = projection_generation+1", [])?;
        Ok(())
    }).unwrap();
    drop(store);
    let mut store = open(&lane.database);
    let again =
        bb_client::activate_legacy_review(&mut store, &review_context(), &prepared).unwrap();
    assert!(again.already_active);
    assert_eq!(again.projection_generation, first.projection_generation);
    assert_eq!(
        bodies(&mut store, "review_settings")["[]"]["threshold_days"],
        28
    );
    assert_eq!(
        bb_client::capture_legacy_review(&mut store).unwrap().token,
        prepared.token
    );
    assert!(
        import_legacy_store(&lane.request()).unwrap().already_active,
        "original import marker still works"
    );
    let mut changed = prepared;
    changed.read_set.settings.as_mut().unwrap().threshold_days =
        bb_domain::types::ThresholdDays::new(14).unwrap();
    assert_eq!(
        bb_client::activate_legacy_review(&mut store, &review_context(), &changed),
        Err(bb_client::LegacyReviewError::AlreadyActivated)
    );
}

#[test]
fn review_activation_026_fr_013_rejects_changed_capture_dirty_target_and_invented_aliases() {
    for case in [
        "generation",
        "carrier",
        "target",
        "aliases",
        "references",
        "map-key",
        "counts",
        "task",
        "schema",
    ] {
        let (_lane, mut store, mut prepared) = review_lane(&format!("review-reject-{case}"));
        let carrier = carried(&mut store, "legacy_review_base");
        match case {
            "generation" => {
                store
                    .write(|tx| {
                        tx.execute(
                            "UPDATE sync_meta SET projection_generation=projection_generation+1",
                            [],
                        )?;
                        Ok(())
                    })
                    .unwrap();
            }
            "carrier" => {
                store.write(|tx| { tx.execute("UPDATE drafts SET fields=x'7b7d' WHERE editor_kind='legacy_review_base'", [])?; Ok(()) }).unwrap();
            }
            "target" => {
                store.write(|tx| { tx.execute("INSERT INTO confirmed_records (workspace_id,record_type,record_key,record_version,tombstone,body) VALUES (?1,'review_settings','[]','0',0,?2)", params![WORKSPACE,serde_json::to_vec(prepared.read_set.settings.as_ref().unwrap()).unwrap()])?; Ok(()) }).unwrap();
            }
            "aliases" => prepared.aliases.push(bb_client::LegacyReviewAlias {
                entity_type: EntityType::ReviewSession,
                local_id: review_fixture()["source_review"]["sessions"]
                    .as_object()
                    .unwrap()
                    .keys()
                    .next()
                    .unwrap()
                    .clone(),
                server_id: "review_abcdef123abc".into(),
            }),
            "references" => {
                prepared
                    .read_set
                    .decisions
                    .values_mut()
                    .next()
                    .unwrap()
                    .created_task_id =
                    Some(bb_domain::types::TaskId::parse("invented-history-task").unwrap())
            }
            "map-key" => {
                let session = prepared.read_set.sessions.values().next().unwrap().clone();
                prepared.read_set.sessions.clear();
                prepared.read_set.sessions.insert(
                    bb_domain::types::SessionId::parse("review_abcdef123abc").unwrap(),
                    session,
                );
            }
            "counts" => prepared.derived_counts.decision_queues = 0,
            "task" => {
                let task: Task = serde_json::from_value(
                    bodies(&mut store, "task").into_values().next().unwrap(),
                )
                .unwrap();
                prepared.read_set.tasks.insert(task.id.clone(), task);
            }
            "schema" => store
                .write(|tx| {
                    tx.pragma_update(None, "user_version", bb_client::SCHEMA_VERSION + 1)?;
                    Ok(())
                })
                .unwrap(),
            _ => unreachable!(),
        }
        assert!(
            bb_client::activate_legacy_review(&mut store, &review_context(), &prepared).is_err(),
            "{case}"
        );
        assert_eq!(store.read(|tx| tx.query_row("SELECT COUNT(*) FROM drafts WHERE editor_kind='runtime_legacy_review_activation'", [], |r| r.get::<_,i64>(0))).unwrap(), 0);
        if case != "carrier" {
            assert_eq!(carried(&mut store, "legacy_review_base"), carrier);
        }
    }
}

#[test]
fn review_activation_026_fr_013_admits_exact_historical_alias_atomically() {
    let mut fixture = review_fixture();
    let historical = "00000000-0000-4000-8000-000000000012";
    let decision = fixture["source_review"]["decisions"]
        .as_object_mut()
        .unwrap()
        .values_mut()
        .next()
        .unwrap();
    decision["undo"]["taskBefore"]["id"] = json!(historical);
    decision["undo"]["taskBefore"]["serverID"] = json!("task_undoremoved_proven");
    let expected = serde_json::to_string(&fixture["expected_read_set"])
        .unwrap()
        .replace(&format!("task_{historical}"), "task_undoremoved_proven");
    fixture["expected_read_set"] = serde_json::from_str(&expected).unwrap();
    let (_lane, mut store, mut prepared) = review_lane_with("review-historical-alias", fixture);
    prepared.aliases.push(bb_client::LegacyReviewAlias {
        entity_type: EntityType::Task,
        local_id: historical.into(),
        server_id: "task_undoremoved_proven".into(),
    });
    let aliases_before = count(&mut store, "identity_aliases");
    assert_eq!(
        bb_client::activate_legacy_review_with(&mut store, &review_context(), &prepared, |_| Err(
            bb_client::LegacyReviewError::Cancelled
        )),
        Err(bb_client::LegacyReviewError::Cancelled)
    );
    assert_eq!(count(&mut store, "identity_aliases"), aliases_before);
    let result =
        bb_client::activate_legacy_review(&mut store, &review_context(), &prepared).unwrap();
    assert_eq!(result.aliases, prepared.aliases);
    assert_eq!(count(&mut store, "identity_aliases"), aliases_before + 4);
    assert!(
        bb_client::capture_legacy_review(&mut store)
            .unwrap()
            .aliases
            .contains(&prepared.aliases[0])
    );
    assert!(!bodies(&mut store, "task").contains_key("task_undoremoved_proven"));
}

#[test]
fn accountless_import_authority_requires_exact_admitted_source_none_and_rechecks_marker() {
    let lane = lane("accountless-proof");
    let mut source: Value = serde_json::from_slice(&golden_bytes()).unwrap();
    source["account"] = Value::Null;
    source["outbox"] = json!([]);
    lane.write_source(&source);
    let report = import_legacy_store(&lane.request()).unwrap();
    let backup = lane.directory.join(report.marker.backup_file);
    let mut store = open(&lane.database);
    assert!(bb_client::establish_account_less_with(&mut store, || Ok(())).is_err());
    let proof = bb_client::verify_accountless_import(&mut store, &backup).unwrap();
    assert_eq!(
        bb_client::establish_account_less_from_import_with(&mut store, &proof, || Err(
            bb_client::ExecuteError::Cancelled
        )),
        Err(bb_client::ExecuteError::Cancelled)
    );
    let mode: String = store
        .read(|tx| tx.query_row("SELECT account_link_state FROM sync_meta", [], |r| r.get(0)))
        .unwrap();
    assert_eq!(mode, "unchosen");
    let bytes = fs::read(&backup).unwrap();
    let mut mismatched = bytes.clone();
    mismatched.push(b' ');
    fs::write(&backup, &mismatched).unwrap();
    assert!(bb_client::verify_accountless_import(&mut store, &backup).is_err());
    fs::write(&backup, &bytes).unwrap();
    let before = bodies(&mut store, "task");
    bb_client::establish_account_less_from_import_with(&mut store, &proof, || Ok(())).unwrap();
    bb_client::establish_account_less_from_import_with(&mut store, &proof, || Ok(())).unwrap();
    assert_eq!(bodies(&mut store, "task"), before);
    assert_eq!(count(&mut store, "outbox"), 0);
    let marker: Vec<u8> = store
        .read(|tx| {
            tx.query_row(
                "SELECT manifest FROM staging_bases WHERE state='activated'",
                [],
                |r| r.get(0),
            )
        })
        .unwrap();
    store.write(|tx|tx.execute("UPDATE staging_bases SET manifest=CAST('tampered' AS BLOB) WHERE state='activated'",[])).unwrap();
    assert!(
        bb_client::establish_account_less_from_import_with(&mut store, &proof, || Ok(())).is_err()
    );
    store
        .write(|tx| {
            tx.execute(
                "UPDATE staging_bases SET manifest=?1 WHERE state='activated'",
                [marker],
            )
        })
        .unwrap();
}

#[test]
fn accountless_import_proof_cannot_grant_linked_source_or_reinterpret_existing_native_history() {
    let linked = lane("accountless-linked-proof");
    let mut source: Value = serde_json::from_slice(&golden_bytes()).unwrap();
    source["account"] =
        json!({"id":"owner-test","email":"sample@example.test","displayName":"Sample"});
    source["outbox"] = json!([]);
    linked.write_source(&source);
    let report = import_legacy_store(&linked.request()).unwrap();
    let mut store = open(&linked.database);
    assert!(
        bb_client::verify_accountless_import(
            &mut store,
            &linked.directory.join(report.marker.backup_file)
        )
        .is_err()
    );
    let fresh = lane("accountless-before-conversion");
    source["account"] = Value::Null;
    fresh.write_source(&source);
    let report = import_legacy_store(&fresh.request()).unwrap();
    let mut store = open(&fresh.database);
    let proof = bb_client::verify_accountless_import(
        &mut store,
        &fresh.directory.join(report.marker.backup_file),
    )
    .unwrap();
    store
        .write(|tx| tx.execute("UPDATE sync_meta SET next_local_seq=2", []))
        .unwrap();
    assert!(
        bb_client::establish_account_less_from_import_with(&mut store, &proof, || Ok(())).is_err()
    );
}

fn local_private_lane_custom(
    name: &str,
    modify: impl FnOnce(&mut Value),
) -> (Lane, Store, bb_client::AccountlessImportProof) {
    let lane = lane(name);
    let mut source: Value = serde_json::from_slice(&golden_bytes()).unwrap();
    let mut fixture = review_fixture();
    let task = "00000000-0000-4000-8000-000000000011";
    let decision = "00000000-0000-4000-8000-000000000014";
    fixture["source_tasks"][task]["serverRevision"] = Value::Null;
    fixture["source_review"]["decisions"][decision]["taskAfter"]["serverRevision"] = Value::Null;
    fixture["source_review"]["decisions"][decision]["undo"]["taskBefore"]["serverRevision"] =
        Value::Null;
    fixture["source_review"]["decisions"][decision]["undo"]
        .as_object_mut()
        .unwrap()
        .remove("createdTaskID");
    fixture["source_review"]["decisions"][decision]["undo"]
        .as_object_mut()
        .unwrap()
        .remove("createdTaskAfter");
    let canonical = "decision_00000000-0000-4000-8000-000000000014";
    fixture["expected_read_set"]["decisions"][canonical]["task_revision_before"] = json!("0");
    fixture["expected_read_set"]["decisions"][canonical]["task_revision_after"] = json!("0");
    fixture["expected_read_set"]["decisions"][canonical]["created_task_id"] = Value::Null;
    modify(&mut fixture);
    source["account"] = Value::Null;
    source["outbox"] = json!([]);
    source["base"]["tasks"] = fixture["source_tasks"].clone();
    source["base"]["review"] = fixture["source_review"].clone();
    lane.write_source(&source);
    let report = import_legacy_store(&lane.request()).unwrap();
    let mut store = open(&lane.database);
    let proof = bb_client::verify_accountless_import(
        &mut store,
        &lane.directory.join(report.marker.backup_file),
    )
    .unwrap();
    bb_client::establish_account_less_from_import_with(&mut store, &proof, || Ok(())).unwrap();
    let capture = bb_client::capture_legacy_review(&mut store).unwrap();
    let prepared = bb_client::PreparedLegacyReview {
        token: capture.token,
        read_set: serde_json::from_value(fixture["expected_read_set"].clone()).unwrap(),
        aliases: vec![],
        derived_counts: serde_json::from_value(fixture["expected_derived_counts"].clone()).unwrap(),
    };
    bb_client::activate_legacy_review(&mut store, &review_context(), &prepared).unwrap();
    (lane, store, proof)
}

#[test]
fn accountless_private_import_original_nil_stamp_pins_native_zero_and_undo_survives_reopen() {
    use bb_client::{ExecuteRequest, RandomIds, execute};
    use bb_protocol::{
        catalog::CommandType,
        command::{Precondition, RevisionPrecondition},
        wire::{CommandId, Counter, Id},
    };
    let (lane, mut store, proof) = local_private_lane_custom("local-private-nil-stamp", |_| {});
    let page = capture_fragment(
        &mut store,
        &proof,
        bb_client::LocalReviewSourceKind::Decision,
        "00000000-0000-4000-8000-000000000014",
        None,
    );
    let prepared = prepare_fragment(&page, &mut store);
    let serialized = serde_json::to_vec(&prepared).unwrap();
    let prepared: bb_client::PreparedLocalReviewFragment =
        serde_json::from_slice(&serialized).unwrap();
    let public = bb_client::visible_snapshot(&mut store).unwrap();
    assert_eq!(
        bb_client::admit_local_review_private_fragment_with(
            &mut store,
            &proof,
            &prepared,
            &Instant::parse(NOW).unwrap(),
            || Err(bb_client::LegacyReviewError::Cancelled)
        ),
        Err(bb_client::LegacyReviewError::Cancelled)
    );
    assert!(carried(&mut store, "runtime_local_review_private").is_empty());
    assert_eq!(
        bb_client::admit_local_review_private_fragment_with(
            &mut store,
            &proof,
            &prepared,
            &Instant::parse(NOW).unwrap(),
            || Ok(())
        )
        .unwrap(),
        bb_client::LocalReviewFragmentAdmitted::Admitted
    );
    assert_eq!(
        bb_client::admit_local_review_private_fragment_with(
            &mut store,
            &proof,
            &prepared,
            &Instant::parse(NOW).unwrap(),
            || Ok(())
        )
        .unwrap(),
        bb_client::LocalReviewFragmentAdmitted::AlreadyAdmitted
    );
    assert_eq!(bb_client::visible_snapshot(&mut store).unwrap(), public);
    let private = carried(&mut store, "runtime_local_review_private");
    assert_eq!(
        private[0].2["private"]["fields"]["local_before"]["session_before"]["revision_after"],
        json!("2")
    );
    drop(store);
    let mut store = open(&lane.database);
    let request = ExecuteRequest {
        command_id: CommandId::parse("cmd_00000000-0000-4000-8000-000000000099").unwrap(),
        command_type: CommandType::ReviewUndoDecision,
        entity_id: Some(Id::parse("decision_00000000-0000-4000-8000-000000000014").unwrap()),
        payload: json!({}).as_object().unwrap().clone(),
        preconditions: vec![Precondition::Revision(RevisionPrecondition {
            entity_type: EntityType::Task,
            entity_id: Id::parse("task_history_proven").unwrap(),
            edit_revision: Counter::from(0),
        })],
        depends_on: vec![],
        admission_tokens: vec![],
        context: review_context(),
    };
    execute(&mut store, &mut RandomIds, &request).unwrap();
    assert_eq!(
        bodies(&mut store, "task")["task_history_proven"]["revision"],
        json!("1")
    );
    let before = bb_client::visible_snapshot(&mut store).unwrap();
    bb_client::replay(&mut store, &review_context()).unwrap();
    assert_eq!(
        bb_client::visible_snapshot(&mut store).unwrap().records,
        before.records
    );
    assert!(bb_client::send_candidates(&mut store).unwrap().is_empty());
}

#[test]
fn accountless_private_import_source_mismatch_and_live_pin_changes_never_authorize_undo() {
    let (_lane, mut store, proof) = local_private_lane_custom("local-private-pin", |_| {});
    let page = capture_fragment(
        &mut store,
        &proof,
        bb_client::LocalReviewSourceKind::Decision,
        "00000000-0000-4000-8000-000000000014",
        None,
    );
    let mut prepared = prepare_fragment(&page, &mut store);
    prepared.evidence.task_matches = Some(false);
    assert_eq!(
        bb_client::admit_local_review_private_fragment_with(
            &mut store,
            &proof,
            &prepared,
            &Instant::parse(NOW).unwrap(),
            || Ok(())
        )
        .unwrap(),
        bb_client::LocalReviewFragmentAdmitted::Admitted
    );
    assert!(carried(&mut store, "runtime_local_review_private").is_empty());
    prepared.evidence.task_matches = Some(true);
    store
        .write(|tx| {
            tx.execute(
                "UPDATE confirmed_records SET record_version='1' WHERE record_type='task'",
                [],
            )
        })
        .unwrap();
    assert_eq!(
        bb_client::admit_local_review_private_fragment_with(
            &mut store,
            &proof,
            &prepared,
            &Instant::parse(NOW).unwrap(),
            || Ok(())
        ),
        Err(bb_client::LegacyReviewError::SourceChanged)
    );
    assert!(carried(&mut store, "runtime_local_review_private").is_empty());
}

fn prepare_fragment(
    page: &bb_client::LocalReviewFragmentPage,
    store: &mut Store,
) -> bb_client::PreparedLocalReviewFragment {
    use bb_client::{LocalReviewComponent as C, PreparedLocalFragmentFields as F};
    let mut evidence = bb_client::LocalReviewSourceEvidence {
        task_matches: None,
        created_task_matches: None,
        session_matches: None,
    };
    let private = match page.component {
        C::DecisionScalar => {
            let task = bb_client::visible_snapshot(store)
                .unwrap()
                .records
                .into_iter()
                .find_map(|record| match record {
                    bb_domain::types::Record::Task(task)
                        if task.id.as_str() == "task_history_proven" =>
                    {
                        Some(task)
                    }
                    _ => None,
                })
                .unwrap();
            let mut task = serde_json::to_value(task).unwrap();
            task.as_object_mut().unwrap().remove("tag_ids");
            evidence.task_matches = Some(true);
            evidence.session_matches = Some(true);
            Some(F::Decision(serde_json::from_value(json!({"task_before":task,"created_task_revision":null,"receipt_kind":"waiting","local_before":{"receipt_replaced":null,"session_before":{"qualifying_activity":false,"last_activity_at":NOW,"last_activity_after":NOW,"revision_after":null}}})).unwrap()))
        }
        C::DecisionTags => Some(F::DecisionTags(
            page.source
                .as_array()
                .unwrap()
                .iter()
                .map(|id| {
                    bb_domain::types::TagId::parse(legacy_record_key(
                        EntityType::Tag,
                        id.as_str().unwrap(),
                        None,
                    ))
                    .unwrap()
                })
                .collect(),
        )),
        C::BulkReleased => Some(F::Bulk(
            page.source["released"]
                .as_array()
                .unwrap()
                .iter()
                .map(|_| {
                    Some(bb_domain::types::ReleasedPrivate {
                        previous_state: bb_domain::types::TaskState::Waiting,
                        clock_before: None,
                        local_receipt_replaced: None,
                        local_source_task_unchanged: Some(true),
                    })
                })
                .collect(),
        )),
        C::SessionScalar => Some(F::Session(bb_domain::types::SessionPrivate {
            applied_progress: BTreeMap::new(),
            finished_empty: vec![],
            local_imported_progress: vec![],
        })),
        C::SessionProgress => Some(F::SessionProgress(
            page.source
                .as_array()
                .unwrap()
                .iter()
                .map(|id| {
                    bb_domain::types::ProgressId::parse(format!(
                        "progress_{}",
                        id.as_str().unwrap()
                    ))
                    .unwrap()
                })
                .collect(),
        )),
        C::Settings => Some(F::Settings(bb_domain::types::SettingsPrivate {
            last_effective_sweep_at: None,
            threshold_changed_at: serde_json::from_value(page.source["thresholdChangedAt"].clone())
                .unwrap(),
        })),
        C::TaskPark => Some(F::TaskPark(serde_json::from_value(json!({"from_revision":null,"clock_before":{"formulation_id":page.source["parked"]["clockBefore"]["id"],"started_at":page.source["parked"]["clockBefore"]["startedAt"],"extended_at":null,"extension_reason":null,"park_floor_at":null,"stalled_before":2}})).unwrap())),
    };
    let prepared = bb_client::PreparedLocalReviewFragment {
        header: page.header.clone(),
        ordinal: page.ordinal,
        component: page.component,
        offset: page.offset,
        count: page.count,
        fragment_sha256: page.fragment_sha256.clone(),
        task_public: page.task_public.clone(),
        session_public: page.session_public.clone(),
        private,
        evidence,
        task_before_park: None,
    };
    serde_json::from_slice(&serde_json::to_vec(&prepared).unwrap()).unwrap()
}
fn capture_fragment(
    store: &mut Store,
    proof: &bb_client::AccountlessImportProof,
    kind: bb_client::LocalReviewSourceKind,
    id: &str,
    after: Option<&str>,
) -> bb_client::LocalReviewFragmentPage {
    bb_client::capture_local_review_private_fragment(
        store,
        proof,
        &bb_client::LocalReviewSourceId {
            source_kind: kind,
            source_id: id.into(),
        },
        after,
        &Instant::parse(NOW).unwrap(),
    )
    .unwrap()
    .unwrap()
}
fn admit_fragment(
    store: &mut Store,
    proof: &bb_client::AccountlessImportProof,
    prepared: &bb_client::PreparedLocalReviewFragment,
) -> bb_client::LocalReviewFragmentAdmitted {
    bb_client::admit_local_review_private_fragment_with(
        store,
        proof,
        prepared,
        &Instant::parse(NOW).unwrap(),
        || Ok(()),
    )
    .unwrap()
}
#[test]
fn accountless_private_fragments_require_complete_tags_and_all_original_pins_then_retry_after_prune()
 {
    use bb_client::{LocalReviewFragmentAdmitted as A, LocalReviewSourceKind as K};
    let decision = "00000000-0000-4000-8000-000000000014";
    let (lane, mut store, proof) = local_private_lane_custom("private-fragment-tags", |fixture| {
        fixture["source_review"]["decisions"][decision]["undo"]["taskBefore"]["tagIDs"] = json!(
            (1000..1201)
                .map(|id| format!("00000000-0000-4000-8000-{id:012}"))
                .collect::<Vec<_>>()
        );
    });
    let first = capture_fragment(&mut store, &proof, K::Decision, decision, None);
    assert!(first.source["undo"]["taskBefore"].get("tagIDs").is_none());
    assert!(first.source["undo"]["taskBefore"].get("subtasks").is_none());
    let prepared = prepare_fragment(&first, &mut store);
    assert!(matches!(
        admit_fragment(&mut store, &proof, &prepared),
        A::Pending { next_ordinal: 1 }
    ));
    assert!(carried(&mut store, "runtime_local_review_private").is_empty());
    assert!(matches!(
        admit_fragment(&mut store, &proof, &prepared),
        A::Pending { next_ordinal: 1 }
    ));
    let mut different = prepared.clone();
    different.evidence.task_matches = Some(false);
    assert_eq!(
        bb_client::admit_local_review_private_fragment_with(
            &mut store,
            &proof,
            &different,
            &Instant::parse(NOW).unwrap(),
            || Ok(())
        ),
        Err(bb_client::LegacyReviewError::SourceChanged)
    );
    drop(store);
    let mut store = open(&lane.database);
    let mut cursor = first.next_cursor;
    let mut last = None;
    while let Some(after) = cursor {
        let page = capture_fragment(&mut store, &proof, K::Decision, decision, Some(&after));
        let prepared = prepare_fragment(&page, &mut store);
        if page.next_cursor.is_none() {
            assert_eq!(
                bb_client::admit_local_review_private_fragment_with(
                    &mut store,
                    &proof,
                    &prepared,
                    &Instant::parse(NOW).unwrap(),
                    || Err(bb_client::LegacyReviewError::Cancelled)
                ),
                Err(bb_client::LegacyReviewError::Cancelled)
            );
            assert!(carried(&mut store, "runtime_local_review_private").is_empty());
        }
        let result = admit_fragment(&mut store, &proof, &prepared);
        if page.next_cursor.is_none() {
            assert_eq!(result, A::Admitted);
            last = Some(prepared);
        }
        cursor = page.next_cursor;
    }
    let overlays = carried(&mut store, "runtime_local_review_private");
    assert_eq!(
        overlays[0].2["private"]["fields"]["task_before"]["tag_ids"]
            .as_array()
            .unwrap()
            .len(),
        201
    );
    let expired = Instant::parse("2026-10-17T09:00:00Z").unwrap();
    bb_client::prune_local_review_private_with(&mut store, &expired, 200, || Ok(())).unwrap();
    assert!(carried(&mut store, "runtime_local_review_private").is_empty());
    assert_eq!(
        bb_client::lookup_local_review_private_fragment(&mut store, &last.unwrap()).unwrap(),
        Some(A::AlreadyAdmitted)
    );
    assert!(
        bb_client::capture_local_review_private_fragment(
            &mut store,
            &proof,
            &bb_client::LocalReviewSourceId {
                source_kind: K::Decision,
                source_id: decision.into()
            },
            None,
            &expired
        )
        .unwrap()
        .is_none()
    );
}
#[test]
fn accountless_private_fragments_do_not_complete_after_task_pin_interference_or_gaps() {
    use bb_client::LocalReviewSourceKind as K;
    let decision = "00000000-0000-4000-8000-000000000014";
    let (_lane, mut store, proof) = local_private_lane_custom("private-fragment-pin", |fixture| {
        fixture["source_review"]["decisions"][decision]["undo"]["taskBefore"]["tagIDs"] =
            json!(["00000000-0000-4000-8000-000000000100"]);
    });
    let page = capture_fragment(&mut store, &proof, K::Decision, decision, None);
    let prepared = prepare_fragment(&page, &mut store);
    let mut gap = prepared.clone();
    gap.ordinal = 1;
    assert!(
        bb_client::admit_local_review_private_fragment_with(
            &mut store,
            &proof,
            &gap,
            &Instant::parse(NOW).unwrap(),
            || Ok(())
        )
        .is_err()
    );
    admit_fragment(&mut store, &proof, &prepared);
    let final_page = capture_fragment(
        &mut store,
        &proof,
        K::Decision,
        decision,
        page.next_cursor.as_deref(),
    );
    let prepared = prepare_fragment(&final_page, &mut store);
    store
        .write(|tx| {
            tx.execute(
                "UPDATE confirmed_records SET record_version='1' WHERE record_type='task'",
                [],
            )
        })
        .unwrap();
    assert_eq!(
        bb_client::admit_local_review_private_fragment_with(
            &mut store,
            &proof,
            &prepared,
            &Instant::parse(NOW).unwrap(),
            || Ok(())
        ),
        Err(bb_client::LegacyReviewError::SourceChanged)
    );
    assert!(carried(&mut store, "runtime_local_review_private").is_empty());
}
#[test]
fn accountless_private_import_pages_five_hundred_bulk_rows_without_partial_undo_or_revision_guess()
{
    use bb_client::{LocalReviewFragmentAdmitted as A, LocalReviewSourceKind as K};
    let bulk = "00000000-0000-4000-8000-000000000015";
    let canonical_bulk = format!("bulk_{bulk}");
    let (_lane, mut store, proof) = local_private_lane_custom("private-fragment-bulk", |fixture| {
        let original = fixture["source_tasks"]["00000000-0000-4000-8000-000000000011"].clone();
        let mut released = vec![];
        let mut public = vec![];
        for seq in 2000..2500 {
            let id = format!("00000000-0000-4000-8000-{seq:012}");
            let canonical = format!("task_{id}");
            let mut task = original.clone();
            task["id"] = json!(id);
            task["serverID"] = json!(canonical);
            task["serverRevision"] = json!(6);
            task["state"] = json!("someday");
            fixture["source_tasks"][&id] = task;
            released.push(json!({"taskID":id,"previousState":"waiting","taskAfter":{"serverRevision":6},"clockKnown":true}));
            public.push(json!({"task_id":canonical,"revision_after":"6"}));
        }
        fixture["source_review"]["bulkReleases"][bulk]["released"] = json!(released);
        fixture["source_review"]["bulkReleases"][bulk]["skipped"] = json!([]);
        fixture["source_review"]["bulkReleases"][bulk]["undoneAt"] = Value::Null;
        fixture["source_review"]["bulkReleases"][bulk]["undoResult"] = Value::Null;
        fixture["expected_read_set"]["bulk_releases"][&canonical_bulk]["released"] = json!(public);
        fixture["expected_read_set"]["bulk_releases"][&canonical_bulk]["skipped"] = json!([]);
        fixture["expected_read_set"]["bulk_releases"][&canonical_bulk]["undone_at"] = Value::Null;
        fixture["expected_read_set"]["bulk_releases"][&canonical_bulk]["undo"] = Value::Null;
    });
    let mut cursor = None;
    let mut total = 0;
    let mut pages = 0;
    loop {
        let page = capture_fragment(&mut store, &proof, K::BulkRelease, bulk, cursor.as_deref());
        assert!(page.count <= 200);
        assert!(page.header.binding.task_public.is_empty());
        assert_eq!(
            page.public["released"].as_array().unwrap().len(),
            page.count as usize
        );
        total += page.count;
        pages += 1;
        let prepared = prepare_fragment(&page, &mut store);
        let result = admit_fragment(&mut store, &proof, &prepared);
        cursor = page.next_cursor;
        if cursor.is_none() {
            assert_eq!(result, A::Admitted);
            break;
        }
        assert!(carried(&mut store, "runtime_local_review_private").is_empty());
    }
    assert_eq!(total, 500);
    assert!(pages > 2);
    let private = carried(&mut store, "runtime_local_review_private");
    assert_eq!(
        private[0].2["private"]["fields"].as_array().unwrap().len(),
        500
    );
    assert!(
        private[0].2["private"]["fields"]
            .as_array()
            .unwrap()
            .iter()
            .all(|item| item["local_source_task_unchanged"] == true)
    );
    assert!(bb_client::send_candidates(&mut store).unwrap().is_empty());
    let public = bb_client::visible_snapshot(&mut store).unwrap();
    assert!(
        !serde_json::to_string(&public)
            .unwrap()
            .contains("local_source_task_unchanged")
    );
}
#[test]
fn accountless_private_settings_preserve_null_and_session_progress_uses_bounded_source_ids() {
    use bb_client::{LocalReviewFragmentAdmitted as A, LocalReviewSourceKind as K};
    let session = "00000000-0000-4000-8000-000000000013";
    let (_lane, mut store, proof) =
        local_private_lane_custom("private-fragment-progress", |fixture| {
            fixture["source_review"]["settings"]["thresholdChangedAt"] = Value::Null;
            fixture["source_review"]["sessions"][session]["appliedProgress"] = json!(
                (3000..3201)
                    .map(|id| format!("00000000-0000-4000-8000-{id:012}"))
                    .collect::<Vec<_>>()
            );
        });
    let page = capture_fragment(&mut store, &proof, K::Settings, "settings", None);
    assert!(page.header.source_at.is_none());
    let prepared = prepare_fragment(&page, &mut store);
    assert_eq!(admit_fragment(&mut store, &proof, &prepared), A::Admitted);
    let mut cursor = None;
    let mut total = 0;
    loop {
        let page = capture_fragment(&mut store, &proof, K::Session, session, cursor.as_deref());
        if page.component == bb_client::LocalReviewComponent::SessionProgress {
            total += page.count;
        }
        let prepared = prepare_fragment(&page, &mut store);
        admit_fragment(&mut store, &proof, &prepared);
        cursor = page.next_cursor;
        if cursor.is_none() {
            break;
        }
    }
    assert_eq!(total, 201);
    let rows = carried(&mut store, "runtime_local_review_private");
    let session = rows
        .iter()
        .find(|row| row.2["entity_type"] == "review_session")
        .unwrap();
    assert_eq!(
        session.2["private"]["fields"]["local_imported_progress"]
            .as_array()
            .unwrap()
            .len(),
        201
    );
}

#[test]
fn native_task_view_page_uses_same_local_park_evidence_and_returns_only_public_facts() {
    use bb_domain::types::{Query, QueryResult, TaskId};
    let original = "00000000-0000-4000-8000-000000000011";
    let (_lane, mut store, proof) = local_private_lane_custom(
        "private-native-task-view",
        |fixture| {
            fixture["source_tasks"][original]["state"] = json!("someday");
            fixture["source_tasks"][original]["parked"] = json!({"at":NOW,"formulationID":"00000000-0000-4000-8000-000000000016","fromRevision":null,"clockBefore":{"id":"00000000-0000-4000-8000-000000000016","startedAt":"2026-10-01T09:00:00Z"},"stalledBefore":2});
        },
    );
    let task = TaskId::parse("task_history_proven").unwrap();
    let context = review_context();
    let inputs = bb_domain::types::QueryInputs {
        now: context.now,
        device_zone: context.time_zone,
        policy: context.policy,
    };
    let query = Query::NativeTaskViews {
        task_ids: vec![task.clone()],
    };
    let before = bb_client::query_page(&mut store, &query, &inputs).unwrap();
    let QueryResult::TaskList(before) = before.result else {
        panic!("task list")
    };
    assert!(
        before.items[0]
            .formulation_state
            .as_ref()
            .unwrap()
            .parked_after_days
            .is_none()
    );
    let captured = capture_fragment(
        &mut store,
        &proof,
        bb_client::LocalReviewSourceKind::TaskPark,
        original,
        None,
    );
    let prepared = prepare_fragment(&captured, &mut store);
    admit_fragment(&mut store, &proof, &prepared);
    let page = bb_client::query_page(&mut store, &query, &inputs).unwrap();
    assert_eq!(page.task_frames.len(), 1);
    assert!(!page.task_frames[0].token.children_known);
    let wire = serde_json::to_string(&page.result).unwrap();
    assert!(!wire.contains("clock_before"));
    assert!(!wire.contains("from_revision"));
    assert!(!wire.contains("private"));
    let QueryResult::TaskList(list) = page.result else {
        panic!("task list")
    };
    assert_eq!(
        list.items[0]
            .formulation_state
            .as_ref()
            .unwrap()
            .parked_after_days,
        Some(9)
    );
    let QueryResult::TaskFormulation(explicit) = bb_client::query_page(
        &mut store,
        &Query::TaskFormulation { task_id: task },
        &inputs,
    )
    .unwrap()
    .result
    else {
        panic!("formulation")
    };
    assert_eq!(list.items[0].formulation_state, Some(explicit));
}
