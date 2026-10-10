//! Real-process durability and contention tests for the local store.
//!
//! Children are this test binary started again with `BB_STORAGE_CHILD` set:
//! `storage_child_entry` then plays one role (writer, crasher, lock holder)
//! in its own process, so SQLite's and `flock`'s cross-process behaviour is
//! what is under test, not a process-local mutex.

use bb_client::{
    LockMode, MigrationLock, OpenOptions, SCHEMA_VERSION, Store, StoreError, StoreStatus,
};
use rusqlite::{Connection, Transaction, params};
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::Duration;

const WORKSPACE: &str = "workspace-local";
const ROLE: &str = "BB_STORAGE_CHILD";

fn scratch(name: &str) -> PathBuf {
    let directory = std::env::temp_dir().join(format!("bb-client-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    directory.join("store").join("workspace.sqlite3")
}

fn options(path: &Path, workspace: &str, timeout_ms: u64) -> OpenOptions {
    OpenOptions {
        path: path.to_path_buf(),
        workspace_id: workspace.to_string(),
        busy_timeout: Duration::from_millis(timeout_ms),
    }
}

fn open(path: &Path, timeout_ms: u64) -> Result<Store, StoreError> {
    Store::open(&options(path, WORKSPACE, timeout_ms))
}

/// Allocates the next local sequence and enqueues one command, the way
/// `execute` will: read under the write lock, then write.
fn enqueue(transaction: &Transaction<'_>, command_id: &str) -> rusqlite::Result<i64> {
    let seq: i64 =
        transaction.query_row("SELECT next_local_seq FROM sync_meta", [], |row| row.get(0))?;
    transaction.execute("UPDATE sync_meta SET next_local_seq = ?1", [seq + 1])?;
    transaction.execute(
        "INSERT INTO outbox (workspace_id, command_id, device_epoch, local_seq, envelope,
            envelope_digest, created_at)
         VALUES (?1, ?2, 'epoch-1', ?3, x'7b7d', x'00', '2026-10-09T00:00:00Z')",
        params![WORKSPACE, command_id, seq],
    )?;
    Ok(seq)
}

fn command_ids(store: &mut Store) -> Vec<String> {
    store
        .read(|tx| {
            let mut statement = tx.prepare("SELECT command_id FROM outbox ORDER BY local_seq")?;
            let rows = statement.query_map([], |row| row.get(0))?;
            rows.collect()
        })
        .unwrap()
}

fn spawn(role: &str, path: &Path, argument: &str) -> Child {
    Command::new(std::env::current_exe().unwrap())
        .args([
            "storage_child_entry",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ])
        .env(ROLE, role)
        .env("BB_STORAGE_PATH", path)
        .env("BB_STORAGE_ARG", argument)
        .stdout(Stdio::piped())
        .spawn()
        .unwrap()
}

/// Blocks until the child prints `marker` (libtest may prefix the line).
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
fn storage_child_entry() {
    let Ok(role) = std::env::var(ROLE) else {
        return;
    };
    let path = PathBuf::from(std::env::var("BB_STORAGE_PATH").unwrap());
    let argument = std::env::var("BB_STORAGE_ARG").unwrap();
    match role.as_str() {
        "enqueue" => {
            let mut store = open(&path, 30_000).unwrap();
            for index in 0..argument.parse::<usize>().unwrap() {
                let id = format!("{}-{index}", std::process::id());
                store.write(|tx| enqueue(tx, &id)).unwrap();
            }
        }
        "commit_then_abort" => {
            let mut store = open(&path, 5_000).unwrap();
            store.write(|tx| enqueue(tx, &argument)).unwrap();
            say("committed");
            std::process::abort();
        }
        "hold_write" => {
            let mut store = open(&path, 5_000).unwrap();
            let _ = store.write(|tx| {
                enqueue(tx, &argument)?;
                say("holding");
                std::thread::sleep(Duration::from_secs(60));
                Ok(())
            });
        }
        "hold_migration_lock" => {
            let _lock =
                MigrationLock::acquire(&path, LockMode::Exclusive, Duration::from_secs(5)).unwrap();
            say("holding");
            std::thread::sleep(Duration::from_secs(60));
        }
        other => panic!("unknown child role {other}"),
    }
}

#[test]
fn storage_026_fr_025_concurrent_processes_allocate_unique_local_sequences() {
    let path = scratch("contention");
    let (processes, per_process) = (4, 40);
    let mut children: Vec<Child> = (0..processes)
        .map(|_| spawn("enqueue", &path, &per_process.to_string()))
        .collect();
    for child in &mut children {
        assert!(child.wait().unwrap().success());
    }

    let mut store = open(&path, 1_000).unwrap();
    let (rows, distinct, max, next, integrity): (i64, i64, i64, i64, String) = store
        .read(|tx| {
            let (rows, distinct, max) = tx.query_row(
                "SELECT count(*), count(DISTINCT local_seq), max(local_seq) FROM outbox",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )?;
            let next =
                tx.query_row("SELECT next_local_seq FROM sync_meta", [], |row| row.get(0))?;
            let integrity = tx.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
            Ok((rows, distinct, max, next, integrity))
        })
        .unwrap();
    let total = processes * per_process;
    assert_eq!(
        (rows, distinct, max, next),
        (total, total, total, total + 1)
    );
    assert_eq!(integrity, "ok");
}

#[test]
fn storage_026_fr_001_committed_write_survives_process_abort() {
    let path = scratch("abort");
    let mut child = spawn("commit_then_abort", &path, "durable-command");
    wait_for(&mut child, "committed");
    assert!(!child.wait().unwrap().success());

    let mut store = open(&path, 1_000).unwrap();
    assert_eq!(command_ids(&mut store), ["durable-command"]);
}

#[test]
fn storage_026_sc_002_busy_writer_never_reports_success_and_dies_without_trace() {
    let path = scratch("busy");
    open(&path, 1_000).unwrap().close().unwrap();
    let mut child = spawn("hold_write", &path, "never-committed");
    wait_for(&mut child, "holding");

    let mut store = open(&path, 100).unwrap();
    let blocked = store.write(|tx| enqueue(tx, "blocked"));
    assert_eq!(blocked, Err(StoreError::Busy));
    assert!(blocked.unwrap_err().is_retryable());

    child.kill().unwrap();
    child.wait().unwrap();
    store.write(|tx| enqueue(tx, "after-crash")).unwrap();
    assert_eq!(command_ids(&mut store), ["after-crash"]);
}

#[test]
fn storage_026_fr_025_migration_lock_holds_off_open_within_the_timeout() {
    let path = scratch("migration-lock");
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    let mut child = spawn("hold_migration_lock", &path, "");
    wait_for(&mut child, "holding");

    assert_eq!(open(&path, 100).unwrap_err(), StoreError::Busy);
    assert!(
        !path.exists(),
        "nothing may be created while a migration runs"
    );

    child.kill().unwrap();
    child.wait().unwrap();
    assert_eq!(open(&path, 1_000).unwrap().status(), StoreStatus::Ready);
}

#[test]
fn storage_026_sc_002_full_store_reports_failure_and_keeps_prior_data() {
    let path = scratch("full");
    let mut store = open(&path, 1_000).unwrap();
    store.write(|tx| enqueue(tx, "kept")).unwrap();

    let full = store.write(|tx| {
        enqueue(tx, "lost")?;
        let pages: i64 = tx.query_row("PRAGMA page_count", [], |row| row.get(0))?;
        tx.pragma_update(None, "max_page_count", pages)?;
        tx.execute(
            "INSERT INTO drafts (workspace_id, draft_id, editor_kind, fields, updated_at)
             VALUES (?1, 'big', 'task', zeroblob(1048576), 'now')",
            [WORKSPACE],
        )?;
        Ok(())
    });
    assert_eq!(full, Err(StoreError::Full));
    store.close().unwrap();

    let mut store = open(&path, 1_000).unwrap();
    assert_eq!(command_ids(&mut store), ["kept"]);
    let drafts: i64 = store
        .read(|tx| tx.query_row("SELECT count(*) FROM drafts", [], |row| row.get(0)))
        .unwrap();
    assert_eq!(drafts, 0);
}

#[test]
fn storage_026_fr_010_newer_schema_opens_read_only_and_is_never_written() {
    let path = scratch("newer");
    let mut store = open(&path, 1_000).unwrap();
    store.write(|tx| enqueue(tx, "pending")).unwrap();
    store.close().unwrap();
    let newer = SCHEMA_VERSION + 1;
    Connection::open(&path)
        .unwrap()
        .pragma_update(None, "user_version", newer)
        .unwrap();

    let mut store = open(&path, 1_000).unwrap();
    assert_eq!(
        store.status(),
        StoreStatus::ReadOnlyRecovery { found: newer }
    );
    assert_eq!(command_ids(&mut store), ["pending"]);
    assert_eq!(
        store.write(|tx| enqueue(tx, "x")),
        Err(StoreError::UpgradeRequired { found: newer })
    );
    let version: i64 = Connection::open(&path)
        .unwrap()
        .query_row("PRAGMA user_version", [], |row| row.get(0))
        .unwrap();
    assert_eq!(version, newer);
}

#[test]
fn storage_026_fr_025_open_handle_stops_writing_once_another_build_upgrades() {
    let path = scratch("upgraded-under");
    let mut store = open(&path, 1_000).unwrap();
    let newer = SCHEMA_VERSION + 1;
    Connection::open(&path)
        .unwrap()
        .pragma_update(None, "user_version", newer)
        .unwrap();

    assert_eq!(
        store.write(|tx| enqueue(tx, "stale")),
        Err(StoreError::UpgradeRequired { found: newer })
    );
    assert!(command_ids(&mut store).is_empty());
}

#[test]
fn storage_026_fr_003_store_is_bound_to_one_protected_workspace() {
    let path = scratch("identity");
    let mut store = open(&path, 1_000).unwrap();
    let tables: Vec<String> = store
        .read(|tx| {
            let mut statement =
                tx.prepare("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")?;
            let rows = statement.query_map([], |row| row.get(0))?;
            rows.collect()
        })
        .unwrap();
    let expected = [
        "command_receipts",
        "confirmed_records",
        "drafts",
        "identity_aliases",
        "outbox",
        "outbox_dependencies",
        "staging_bases",
        "staging_pages",
        "sync_issues",
        "sync_meta",
        "visible_records",
    ];
    assert_eq!(tables, expected);
    assert!(
        store
            .write(|tx| tx.execute("UPDATE sync_meta SET workspace_id = 'other'", []))
            .is_err()
    );
    assert!(
        store
            .write(|tx| tx.execute("DELETE FROM sync_meta", []))
            .is_err()
    );
    store.close().unwrap();

    let other = Store::open(&options(&path, "workspace-other", 1_000));
    assert_eq!(other.unwrap_err(), StoreError::WorkspaceMismatch);
    let mode = |p: &Path| fs::metadata(p).unwrap().permissions().mode() & 0o777;
    assert_eq!(mode(&path), 0o600);
    assert_eq!(mode(path.parent().unwrap()), 0o700);
}

#[test]
fn storage_026_fr_003_wal_files_are_owner_only() {
    let path = scratch("wal-mode");
    let mut store = open(&path, 1_000).unwrap();
    store.write(|tx| enqueue(tx, "first")).unwrap();
    for suffix in ["-wal", "-shm"] {
        let mut name = path.clone().into_os_string();
        name.push(suffix);
        let mode = fs::metadata(&name).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600, "{suffix}");
    }
}

#[test]
fn storage_026_fr_003_account_link_choice_defaults_to_unchosen() {
    let path = scratch("link-state");
    let mut store = open(&path, 1_000).unwrap();
    let (state, checkpoint): (String, Option<Vec<u8>>) = store
        .read(|tx| {
            tx.query_row(
                "SELECT account_link_state, link_checkpoint FROM sync_meta",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
        })
        .unwrap();
    assert_eq!((state.as_str(), checkpoint), ("unchosen", None));
    assert!(
        store
            .write(|tx| tx.execute("UPDATE sync_meta SET account_link_state = 'maybe'", []))
            .is_err()
    );
}

#[test]
fn storage_026_fr_025_proven_alias_is_immutable_and_scoped_to_the_workspace() {
    let path = scratch("alias");
    let mut store = open(&path, 1_000).unwrap();
    store
        .write(|tx| {
            tx.execute(
                "INSERT INTO identity_aliases VALUES (?1, 'task', 'local-1', 'task_a', 'proven')",
                [WORKSPACE],
            )
        })
        .unwrap();
    assert!(
        store
            .write(|tx| tx.execute("UPDATE identity_aliases SET server_id = 'task_b'", []))
            .is_err()
    );
    assert!(
        store
            .write(|tx| tx.execute(
                "INSERT INTO identity_aliases VALUES ('other', 'task', 'local-2', 'task_c', 'x')",
                []
            ))
            .is_err()
    );
}

#[test]
fn storage_026_fr_025_staged_base_is_separate_from_the_confirmed_base() {
    let path = scratch("staging");
    let mut store = open(&path, 1_000).unwrap();
    store
        .write(|tx| {
            tx.execute(
                "INSERT INTO staging_bases (workspace_id, activation_id, kind, target_generation,
                    target_watermark, manifest, manifest_digest, total_pages, created_at)
                 VALUES (?1, 'act-1', 'snapshot', '7', '42', x'7b7d', x'00', 2,
                    '2026-10-09T00:00:00Z')",
                [WORKSPACE],
            )?;
            tx.execute(
                "INSERT INTO staging_pages VALUES (?1, 'act-1', 0, x'01', x'02')",
                [WORKSPACE],
            )
        })
        .unwrap();
    let counts = |store: &mut Store| -> (i64, i64) {
        store
            .read(|tx| {
                Ok((
                    tx.query_row("SELECT count(*) FROM confirmed_records", [], |r| r.get(0))?,
                    tx.query_row("SELECT count(*) FROM staging_pages", [], |r| r.get(0))?,
                ))
            })
            .unwrap()
    };
    assert_eq!(counts(&mut store), (0, 1));
    // A page cannot be staged for a base that was never announced.
    assert!(
        store
            .write(|tx| tx.execute(
                "INSERT INTO staging_pages VALUES (?1, 'nope', 0, x'01', x'02')",
                [WORKSPACE]
            ))
            .is_err()
    );
    store
        .write(|tx| {
            tx.execute(
                "DELETE FROM staging_bases WHERE activation_id = 'act-1'",
                [],
            )
        })
        .unwrap();
    assert_eq!(counts(&mut store), (0, 0));
}

#[test]
fn storage_026_sc_002_unreadable_file_is_reported_and_left_untouched() {
    let path = scratch("corrupt");
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    let garbage = b"this is not a database, and it is somebody's only copy".repeat(100);
    fs::write(&path, &garbage).unwrap();

    assert_eq!(open(&path, 1_000).unwrap_err(), StoreError::Corrupt);
    assert_eq!(fs::read(&path).unwrap(), garbage);
}

#[test]
fn storage_026_fr_001_enqueued_envelope_is_immutable() {
    let path = scratch("immutable");
    let mut store = open(&path, 1_000).unwrap();
    store.write(|tx| enqueue(tx, "sent")).unwrap();
    store
        .write(|tx| tx.execute("UPDATE outbox SET ever_sent = 1, state = 'sending'", []))
        .unwrap();

    assert!(
        store
            .write(|tx| tx.execute("UPDATE outbox SET envelope = x'00'", []))
            .is_err()
    );
    assert!(
        store
            .write(|tx| tx.execute("UPDATE outbox SET local_seq = 99", []))
            .is_err()
    );
    assert!(
        store
            .write(|tx| tx.execute("UPDATE outbox SET ever_sent = 0", []))
            .is_err()
    );
    let row: (Vec<u8>, i64, i64) = store
        .read(|tx| {
            tx.query_row(
                "SELECT envelope, local_seq, ever_sent FROM outbox",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
        })
        .unwrap();
    assert_eq!(row, (b"{}".to_vec(), 1, 1));
}
