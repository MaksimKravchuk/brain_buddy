//! Crash-boundary, rollback, retry and contention tests for local execute.
//!
//! Children are this test binary started again with `BB_EXECUTE_CHILD` set:
//! `execute_child_entry` plays one role (a process that crashes mid-gesture,
//! the app and the widget intaking before registration, a lock holder) in its
//! own process, so SQLite's cross-process behaviour is what is under test.

use bb_client::{
    ExecuteContext, ExecuteError, ExecuteRequest, IdSource, OpenOptions, RandomIds, SCHEMA_VERSION,
    Stage, Store, StoreError, StoreStatus, execute, execute_batch, execute_batch_with,
    execute_with,
};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{Precondition, RevisionPrecondition, decode_stable};
use bb_protocol::wire::{CommandId, Counter, Id, Instant};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::Duration;

const WORKSPACE: &str = "workspace-local";
const ROLE: &str = "BB_EXECUTE_CHILD";
const NOW: &str = "2026-10-10T09:00:00Z";

// ----------------------------------------------------------------------- harness

fn scratch(name: &str) -> PathBuf {
    let directory = std::env::temp_dir().join(format!("bb-execute-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    directory.join("store").join("workspace.sqlite3")
}

fn open(path: &Path, timeout_ms: u64) -> Result<Store, StoreError> {
    Store::open(&OpenOptions {
        path: path.to_path_buf(),
        workspace_id: WORKSPACE.to_string(),
        busy_timeout: Duration::from_millis(timeout_ms),
    })
}

/// Counts up from 1, so the IDs a run allocates are predictable.
struct SeqIds(u64);

impl IdSource for SeqIds {
    fn uuid(&mut self) -> std::io::Result<String> {
        self.0 += 1;
        Ok(format!("00000000-0000-4000-8000-{:012x}", self.0))
    }
}

fn cmd(n: u64) -> CommandId {
    CommandId::parse(format!("01900000-0000-4000-8000-{n:012}")).unwrap()
}

fn context(now: &str) -> ExecuteContext {
    ExecuteContext {
        now: Instant::parse(now).unwrap(),
        time_zone: ZoneName::new("UTC").unwrap(),
        actor_id: ActorId::parse("actor-local").unwrap(),
        policy: Policy {
            weekly_review: false,
            navigator_provider: None,
            navigator_available: false,
            consent_text_version: 1,
        },
    }
}

fn request(
    command_id: CommandId,
    command_type: CommandType,
    entity_id: Option<&str>,
    payload: Value,
    preconditions: Vec<Precondition>,
) -> ExecuteRequest {
    ExecuteRequest {
        command_id,
        command_type,
        entity_id: entity_id.map(|id| Id::parse(id).unwrap()),
        payload: payload.as_object().unwrap().clone(),
        preconditions,
        depends_on: Vec::new(),
        context: context(NOW),
    }
}

fn create_task(command_id: CommandId, title: &str) -> ExecuteRequest {
    request(
        command_id,
        CommandType::TaskCreate,
        None,
        json!({ "title": title }),
        Vec::new(),
    )
}

fn shown(entity_type: EntityType, id: &str, revision: &str) -> Precondition {
    Precondition::Revision(RevisionPrecondition {
        entity_type,
        entity_id: Id::parse(id).unwrap(),
        edit_revision: Counter::parse(revision).unwrap(),
    })
}

struct Queued {
    command_id: String,
    local_seq: i64,
    epoch: String,
    envelope: Value,
    depends_on: Vec<String>,
}

fn queue(store: &mut Store) -> Vec<Queued> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT command_id, local_seq, device_epoch, envelope FROM outbox
                 ORDER BY local_seq",
            )?;
            let rows = statement.query_map([], |row| {
                let envelope: Vec<u8> = row.get(3)?;
                Ok((row.get(0)?, row.get(1)?, row.get(2)?, envelope))
            })?;
            let rows: Vec<(String, i64, String, Vec<u8>)> = rows.collect::<Result<_, _>>()?;
            rows.into_iter()
                .map(|(command_id, local_seq, epoch, envelope)| {
                    let mut edges = tx.prepare(
                        "SELECT depends_on FROM outbox_dependencies WHERE command_id = ?1
                         ORDER BY depends_on",
                    )?;
                    let depends_on = edges
                        .query_map([&command_id], |row| row.get(0))?
                        .collect::<Result<_, _>>()?;
                    Ok(Queued {
                        command_id,
                        local_seq,
                        epoch,
                        envelope: serde_json::from_slice(&envelope).unwrap(),
                        depends_on,
                    })
                })
                .collect()
        })
        .unwrap()
}

fn visible(store: &mut Store, record_type: &str) -> Vec<Value> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT body FROM visible_records WHERE record_type = ?1 ORDER BY record_key",
            )?;
            let rows = statement.query_map([record_type], |row| row.get::<_, Vec<u8>>(0))?;
            Ok(rows
                .map(|body| serde_json::from_slice(&body.unwrap()).unwrap())
                .collect())
        })
        .unwrap()
}

fn task(store: &mut Store, id: &str) -> Value {
    visible(store, "task")
        .into_iter()
        .find(|task| task["id"] == id)
        .unwrap_or_else(|| panic!("task {id} is not in the visible projection"))
}

/// `(epoch state, epoch, next local sequence, projection generation)`.
fn meta(store: &mut Store) -> (String, Option<String>, i64, i64) {
    store
        .read(|tx| {
            tx.query_row(
                "SELECT device_epoch_state, device_epoch, next_local_seq, projection_generation
                 FROM sync_meta",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?)),
            )
        })
        .unwrap()
}

fn assert_untouched(store: &mut Store) {
    assert!(queue(store).is_empty());
    assert!(visible(store, "task").is_empty());
    assert_eq!(meta(store), ("none".to_string(), None, 1, 0));
}

#[test]
fn execute_026_fr_001_batch_refusal_rolls_back_every_command() {
    let path = scratch("batch-refusal");
    let mut store = open(&path, 2_000).unwrap();
    let result = execute_batch(
        &mut store,
        &mut SeqIds(0),
        &[
            create_task(cmd(1), "Kept only if everything saves"),
            create_task(cmd(2), ""),
        ],
    );
    assert!(matches!(result, Err(ExecuteError::Refused(_))));
    assert_untouched(&mut store);
}

#[test]
fn execute_026_fr_005_batch_unknown_completion_retries_same_ids() {
    let path = scratch("batch-retry");
    let mut store = open(&path, 2_000).unwrap();
    let requests = [create_task(cmd(1), "One"), create_task(cmd(2), "Two")];
    let saved = execute_batch(&mut store, &mut SeqIds(0), &requests).unwrap();
    drop(store); // completion was lost after commit
    let mut reopened = open(&path, 2_000).unwrap();
    let retried = execute_batch(&mut reopened, &mut SeqIds(100), &requests).unwrap();
    assert!(retried.iter().all(|result| result.replayed));
    assert_eq!(saved[0].entity_id, retried[0].entity_id);
    assert_eq!(saved[1].local_sequence, retried[1].local_sequence);
    assert_eq!(queue(&mut reopened).len(), 2);
}

#[test]
fn execute_026_fr_001_batch_cancel_before_commit_rolls_back() {
    let path = scratch("batch-cancel");
    let mut store = open(&path, 2_000).unwrap();
    let result = execute_batch_with(
        &mut store,
        &mut SeqIds(0),
        &[create_task(cmd(1), "One"), create_task(cmd(2), "Two")],
        |_| Err(ExecuteError::Cancelled),
    );
    assert_eq!(result.unwrap_err(), ExecuteError::Cancelled);
    assert_untouched(&mut store);
}

fn spawn(role: &str, path: &Path, argument: &str) -> Child {
    Command::new(std::env::current_exe().unwrap())
        .args([
            "execute_child_entry",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ])
        .env(ROLE, role)
        .env("BB_EXECUTE_PATH", path)
        .env("BB_EXECUTE_ARG", argument)
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
fn execute_child_entry() {
    let Ok(role) = std::env::var(ROLE) else {
        return;
    };
    let path = PathBuf::from(std::env::var("BB_EXECUTE_PATH").unwrap());
    let argument = std::env::var("BB_EXECUTE_ARG").unwrap();
    match role.as_str() {
        "commit_then_abort" => {
            let mut store = open(&path, 5_000).unwrap();
            execute(&mut store, &mut RandomIds, &create_task(cmd(1), "kept")).unwrap();
            say("committed");
            std::process::abort();
        }
        "stage_then_abort" => {
            let mut store = open(&path, 5_000).unwrap();
            let stage = match argument.as_str() {
                "intent" => Stage::IntentStored,
                _ => Stage::ProjectionStored,
            };
            let _ = execute_with(
                &mut store,
                &mut RandomIds,
                &create_task(cmd(1), "lost"),
                |reached, _| {
                    if reached == stage {
                        say("staged");
                        std::process::abort();
                    }
                    Ok(())
                },
            );
        }
        "intake" => {
            let mut store = open(&path, 30_000).unwrap();
            let me = u64::from(std::process::id());
            for index in 0..argument.parse::<u64>().unwrap() {
                let id = CommandId::parse(format!("{me:08x}-0000-4000-8000-{index:012}")).unwrap();
                execute(
                    &mut store,
                    &mut RandomIds,
                    &create_task(id, "from a process"),
                )
                .unwrap();
            }
        }
        "hold_write" => {
            let mut store = open(&path, 5_000).unwrap();
            let _ = store.write(|tx| {
                tx.execute("UPDATE sync_meta SET next_local_seq = next_local_seq", [])?;
                say("holding");
                std::thread::sleep(Duration::from_secs(60));
                Ok(())
            });
        }
        other => panic!("unknown child role {other}"),
    }
}

// ------------------------------------------------------------------------- tests

#[test]
fn execute_026_fr_001_offline_create_then_edit_orders_by_identity_and_survives_restart() {
    let path = scratch("chain");
    let mut store = open(&path, 1_000).unwrap();
    let mut ids = SeqIds(0);

    let created = execute(
        &mut store,
        &mut ids,
        &create_task(cmd(1), "Draft the estimate"),
    )
    .unwrap();
    assert_eq!(
        (created.local_sequence, created.projection_generation),
        (1, 1)
    );
    let task_id = created.entity_id.as_str().to_string();
    assert!(task_id.starts_with("task_"), "{task_id}");
    let revision = task(&mut store, &task_id)["revision"]
        .as_str()
        .unwrap()
        .to_string();

    // The user is shown the offline-created task and edits it, then moves it.
    let edit = request(
        cmd(2),
        CommandType::TaskUpdate,
        Some(&task_id),
        json!({ "title": "Prepare the estimate" }),
        vec![shown(EntityType::Task, &task_id, &revision)],
    );
    let edited = execute(&mut store, &mut ids, &edit).unwrap();
    assert_eq!(
        (edited.local_sequence, edited.projection_generation),
        (2, 2)
    );
    let revision = task(&mut store, &task_id)["revision"]
        .as_str()
        .unwrap()
        .to_string();
    let moved = request(
        cmd(3),
        CommandType::TaskTransition,
        Some(&task_id),
        json!({ "action": "move", "to_state": "next" }),
        vec![shown(EntityType::Task, &task_id, &revision)],
    );
    execute(&mut store, &mut ids, &moved).unwrap();
    store.close().unwrap();

    let mut store = open(&path, 1_000).unwrap();
    let queued = queue(&mut store);
    let order: Vec<_> = queued
        .iter()
        .map(|q| (q.local_seq, &q.command_id))
        .collect();
    assert_eq!(
        order,
        [
            (1, &cmd(1).as_str().to_string()),
            (2, &cmd(2).as_str().to_string()),
            (3, &cmd(3).as_str().to_string()),
        ]
    );
    // A revision the queue produced is never sent as a guessed number: it is
    // the immutable identity of the command that produced it.
    assert_eq!(queued[0].envelope["preconditions"], json!([]));
    assert_eq!(queued[0].depends_on, Vec::<String>::new());
    for (later, earlier) in [(1, 0), (2, 1)] {
        assert_eq!(
            queued[later].envelope["preconditions"],
            json!([{ "after_command": {
                "command_id": queued[earlier].command_id,
                "entity_type": "task",
                "entity_id": task_id,
            }}])
        );
        assert_eq!(
            queued[later].envelope["depends_on"],
            json!([queued[earlier].command_id])
        );
        assert_eq!(
            queued[later].depends_on,
            [queued[earlier].command_id.clone()]
        );
    }
    let state = task(&mut store, &task_id);
    assert_eq!(state["title"], "Prepare the estimate");
    assert_eq!(state["state"], "next");
    assert_eq!(meta(&mut store).2, 4);
    assert_eq!(meta(&mut store).3, 3);
}

#[test]
fn execute_026_fr_001_committed_gesture_survives_process_abort() {
    let path = scratch("abort");
    let mut child = spawn("commit_then_abort", &path, "");
    wait_for(&mut child, "committed");
    assert!(!child.wait().unwrap().success());

    let mut store = open(&path, 1_000).unwrap();
    let queued = queue(&mut store);
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].command_id, cmd(1).as_str());
    let tasks = visible(&mut store, "task");
    assert_eq!(tasks.len(), 1);
    assert_eq!(tasks[0]["title"], "kept");
    let (state, epoch, next, generation) = meta(&mut store);
    assert_eq!(
        (state.as_str(), epoch.as_deref(), next, generation),
        ("pending_registration", Some(queued[0].epoch.as_str()), 2, 1)
    );
}

#[test]
fn execute_026_sc_002_crash_before_commit_leaves_no_intent_projection_or_epoch() {
    for stage in ["intent", "projection"] {
        let path = scratch(&format!("crash-{stage}"));
        let mut child = spawn("stage_then_abort", &path, stage);
        wait_for(&mut child, "staged");
        assert!(!child.wait().unwrap().success());

        let mut store = open(&path, 1_000).unwrap();
        assert_untouched(&mut store);
        // The gesture can be made again, from scratch, under the same ID.
        let again = execute(&mut store, &mut SeqIds(0), &create_task(cmd(1), "lost")).unwrap();
        assert_eq!((again.local_sequence, again.replayed), (1, false));
    }
}

#[test]
fn execute_026_sc_002_storage_failure_after_intent_rolls_back_the_whole_gesture() {
    let path = scratch("full");
    let mut store = open(&path, 1_000).unwrap();
    let kept = execute(&mut store, &mut SeqIds(0), &create_task(cmd(1), "kept")).unwrap();

    let full = execute_with(
        &mut store,
        &mut SeqIds(100),
        &create_task(cmd(2), "lost"),
        |stage, tx| {
            if stage == Stage::IntentStored {
                let pages: i64 = tx.query_row("PRAGMA page_count", [], |row| row.get(0))?;
                tx.pragma_update(None, "max_page_count", pages)?;
                tx.execute(
                    "INSERT INTO drafts (workspace_id, draft_id, editor_kind, fields, updated_at)
                     VALUES (?1, 'big', 'task', zeroblob(1048576), 'now')",
                    [WORKSPACE],
                )?;
            }
            Ok(())
        },
    );
    assert_eq!(full, Err(ExecuteError::Store(StoreError::Full)));
    assert_eq!(full.unwrap_err().code(), "STORE_FULL");
    store.close().unwrap();

    let mut store = open(&path, 1_000).unwrap();
    let queued = queue(&mut store);
    assert_eq!(queued.len(), 1);
    assert_eq!(queued[0].command_id, cmd(1).as_str());
    assert_eq!(visible(&mut store, "task").len(), 1);
    assert_eq!(meta(&mut store).2, 2);
    assert_eq!(meta(&mut store).3, 1);
    assert_eq!(kept.local_sequence, 1);
}

#[test]
fn execute_026_fr_001_refused_command_saves_nothing_and_takes_no_sequence() {
    let path = scratch("refused");
    let mut store = open(&path, 1_000).unwrap();
    let mut ids = SeqIds(0);

    let missing = request(
        cmd(1),
        CommandType::TaskUpdate,
        Some("task_00000000-0000-4000-8000-0000000000ff"),
        json!({ "title": "Nothing here" }),
        vec![shown(
            EntityType::Task,
            "task_00000000-0000-4000-8000-0000000000ff",
            "1",
        )],
    );
    let refused = execute(&mut store, &mut ids, &missing).unwrap_err();
    assert_eq!(refused.code(), "VALIDATION_FAILED");
    assert!(!refused.is_retryable());
    assert!(matches!(refused, ExecuteError::Refused(_)));
    assert_untouched(&mut store);

    // A dependency must be a command this workspace queued.
    let mut orphan = create_task(cmd(2), "Orphan");
    orphan.depends_on = vec![cmd(99)];
    let refused = execute(&mut store, &mut ids, &orphan).unwrap_err();
    assert!(matches!(refused, ExecuteError::Refused(_)), "{refused:?}");
    assert_untouched(&mut store);

    // A stale shown revision is a conflict, decided before anything is saved.
    let created = execute(&mut store, &mut ids, &create_task(cmd(3), "Real")).unwrap();
    let id = created.entity_id.as_str().to_string();
    let stale = request(
        cmd(4),
        CommandType::TaskUpdate,
        Some(&id),
        json!({ "title": "Late" }),
        vec![shown(EntityType::Task, &id, "7")],
    );
    let ExecuteError::Refused(conflict) = execute(&mut store, &mut ids, &stale).unwrap_err() else {
        panic!("a stale revision is refused");
    };
    assert_eq!(conflict.reason.as_str(), "revision_conflict");
    assert_eq!(queue(&mut store).len(), 1);
    assert_eq!(task(&mut store, &id)["title"], "Real");
    assert_eq!(meta(&mut store).2, 2);
}

#[test]
fn execute_026_fr_005_retry_returns_the_stored_result_and_changed_content_is_refused() {
    let path = scratch("retry");
    let mut store = open(&path, 1_000).unwrap();
    let first = execute(&mut store, &mut SeqIds(0), &create_task(cmd(1), "Once")).unwrap();
    assert!(!first.replayed);

    // The lost-response retry: same ID and content, a later device clock.
    let mut retry = create_task(cmd(1), "Once");
    retry.context = context("2026-10-10T09:05:00Z");
    let again = execute(&mut store, &mut SeqIds(500), &retry).unwrap();
    assert!(again.replayed);
    assert_eq!(
        (
            &again.entity_id,
            again.local_sequence,
            again.projection_generation
        ),
        (
            &first.entity_id,
            first.local_sequence,
            first.projection_generation
        )
    );

    // The same ID is never re-bound to other content.
    let changed = create_task(cmd(1), "Something else");
    assert_eq!(
        execute(&mut store, &mut SeqIds(500), &changed),
        Err(ExecuteError::CommandIdReused)
    );
    assert_eq!(
        ExecuteError::CommandIdReused.code(),
        "IDEMPOTENCY_KEY_REUSED"
    );

    // Across a restart too, and still exactly one command and one task.
    store.close().unwrap();
    let mut store = open(&path, 1_000).unwrap();
    let after_restart = execute(&mut store, &mut SeqIds(900), &retry).unwrap();
    assert_eq!(after_restart, again);
    assert_eq!(queue(&mut store).len(), 1);
    assert_eq!(visible(&mut store, "task").len(), 1);
    assert_eq!(meta(&mut store).2, 2);
}

#[test]
fn execute_026_fr_006_intake_epoch_is_durable_with_the_first_command_and_reused() {
    let path = scratch("epoch");
    let mut store = open(&path, 1_000).unwrap();
    assert_eq!(meta(&mut store).0, "none");
    let mut ids = SeqIds(0);

    execute(&mut store, &mut ids, &create_task(cmd(1), "first")).unwrap();
    let (state, epoch, _, _) = meta(&mut store);
    let epoch = epoch.unwrap();
    assert_eq!(state, "pending_registration");

    execute(&mut store, &mut ids, &create_task(cmd(2), "second")).unwrap();
    // Registration confirmed the same epoch: still reused.
    store
        .write(|tx| tx.execute("UPDATE sync_meta SET device_epoch_state = 'active'", []))
        .unwrap();
    execute(&mut store, &mut ids, &create_task(cmd(3), "third")).unwrap();
    assert!(queue(&mut store).iter().all(|q| q.epoch == epoch));

    // An explicit closure keeps the old envelopes and gives new work a new epoch.
    store
        .write(|tx| tx.execute("UPDATE sync_meta SET device_epoch_state = 'closed'", []))
        .unwrap();
    execute(&mut store, &mut ids, &create_task(cmd(4), "fourth")).unwrap();
    let (state, fresh, _, _) = meta(&mut store);
    assert_eq!(state, "pending_registration");
    let fresh = fresh.unwrap();
    assert_ne!(fresh, epoch);
    let epochs: Vec<_> = queue(&mut store).into_iter().map(|q| q.epoch).collect();
    assert_eq!(epochs, [&*epoch, &*epoch, &*epoch, &*fresh]);
    for q in queue(&mut store) {
        assert_eq!(q.envelope["device_epoch"], json!(q.epoch));
    }
}

#[test]
fn execute_026_fr_025_app_and_widget_processes_share_one_intake_epoch_before_registration() {
    let path = scratch("intake");
    let per_process = 25;
    let mut children: Vec<Child> = (0..2)
        .map(|_| spawn("intake", &path, &per_process.to_string()))
        .collect();
    for child in &mut children {
        assert!(child.wait().unwrap().success());
    }

    let mut store = open(&path, 1_000).unwrap();
    let queued = queue(&mut store);
    let total = 2 * per_process;
    let sequences: Vec<i64> = queued.iter().map(|q| q.local_seq).collect();
    assert_eq!(sequences, (1..=total).collect::<Vec<_>>());
    let epochs: BTreeSet<&str> = queued.iter().map(|q| q.epoch.as_str()).collect();
    assert_eq!(epochs.len(), 1, "one durable intake epoch: {epochs:?}");
    let (state, epoch, next, generation) = meta(&mut store);
    assert_eq!(state, "pending_registration");
    assert_eq!(epoch.as_deref(), epochs.first().copied());
    assert_eq!((next, generation), (total + 1, total));
    assert_eq!(visible(&mut store, "task").len(), total as usize);
    let integrity: String = store
        .read(|tx| tx.query_row("PRAGMA integrity_check", [], |row| row.get(0)))
        .unwrap();
    assert_eq!(integrity, "ok");
}

#[test]
fn execute_026_sc_002_busy_store_never_reports_a_local_save() {
    let path = scratch("busy");
    open(&path, 1_000).unwrap().close().unwrap();
    let mut child = spawn("hold_write", &path, "");
    wait_for(&mut child, "holding");

    let mut store = open(&path, 100).unwrap();
    let blocked = execute(&mut store, &mut SeqIds(0), &create_task(cmd(1), "blocked"));
    let blocked = blocked.unwrap_err();
    assert_eq!(blocked, ExecuteError::Store(StoreError::Busy));
    assert_eq!(blocked.code(), "STORE_BUSY");
    assert!(blocked.is_retryable());

    child.kill().unwrap();
    child.wait().unwrap();
    assert_untouched(&mut store);
    let saved = execute(&mut store, &mut SeqIds(0), &create_task(cmd(1), "blocked")).unwrap();
    assert_eq!(saved.local_sequence, 1);
}

#[test]
fn execute_026_fr_003_account_less_intent_has_no_scope_and_linked_intent_is_a_wire_envelope() {
    let path = scratch("scope");
    let mut store = open(&path, 1_000).unwrap();
    let mut ids = SeqIds(0);
    // Account-less: no registered account, no fictitious scope or device.
    execute(&mut store, &mut ids, &create_task(cmd(1), "local only")).unwrap();
    let local = &queue(&mut store)[0];
    assert!(local.envelope.get("scope_id").is_none());
    assert!(local.envelope.get("device_id").is_none());
    assert_eq!(local.envelope["local_sequence"], "1");
    assert_eq!(local.envelope["type"], "task.create");

    store
        .write(|tx| {
            tx.execute(
                "UPDATE sync_meta SET scope_id = 'scope-a', device_id = 'device-a'",
                [],
            )
        })
        .unwrap();
    execute(&mut store, &mut ids, &create_task(cmd(2), "linked")).unwrap();
    let linked = &queue(&mut store)[1];
    let wire = decode_stable(&linked.envelope.to_string()).unwrap();
    assert_eq!(
        (wire.scope_id.as_str(), wire.device_id.as_str()),
        ("scope-a", "device-a")
    );
    assert_eq!(wire.local_sequence.as_str(), "2");
    assert_eq!(wire.device_epoch.as_str(), linked.epoch);
}

#[test]
fn execute_026_fr_001_dependencies_refer_to_identities_not_names() {
    let path = scratch("identity");
    let mut store = open(&path, 1_000).unwrap();
    let mut ids = SeqIds(0);

    let project = request(
        cmd(1),
        CommandType::ProjectCreate,
        None,
        json!({ "name": "Trips" }),
        Vec::new(),
    );
    let project = execute(&mut store, &mut ids, &project).unwrap();
    let project_id = project.entity_id.as_str().to_string();

    // Smart Add names the project; the rules resolve it onto the one the
    // queue created, so the new task is tied to that command.
    let by_name = request(
        cmd(2),
        CommandType::TaskSmartAdd,
        None,
        json!({ "title": "Book flights", "project": {
            "name": "trips",
            "proposed_id": "project_00000000-0000-4000-8000-0000000000aa",
        }}),
        Vec::new(),
    );
    let flights = execute(&mut store, &mut ids, &by_name).unwrap();
    assert_eq!(
        task(&mut store, flights.entity_id.as_str())["project_id"],
        json!(project_id)
    );
    // A different name resolves to nothing queued: no dependency is invented.
    let unrelated = request(
        cmd(3),
        CommandType::TaskCreate,
        None,
        json!({ "title": "Trips" }),
        Vec::new(),
    );
    execute(&mut store, &mut ids, &unrelated).unwrap();

    // An explicit alias to a classification a queued Smart Add created.
    let new_project = "project_00000000-0000-4000-8000-0000000000bb";
    let creating = request(
        cmd(4),
        CommandType::TaskSmartAdd,
        None,
        json!({ "title": "Buy stamps", "project": { "name": "Errands", "proposed_id": new_project }}),
        Vec::new(),
    );
    execute(&mut store, &mut ids, &creating).unwrap();
    let following = request(
        cmd(5),
        CommandType::TaskCreate,
        None,
        json!({ "title": "Post parcel", "project_id": {
            "after_command": cmd(4).as_str(),
            "alias_id": new_project,
            "entity_type": "project",
        }}),
        Vec::new(),
    );
    let parcel = execute(&mut store, &mut ids, &following).unwrap();
    assert_eq!(
        task(&mut store, parcel.entity_id.as_str())["project_id"],
        new_project
    );

    let queued = queue(&mut store);
    let depends: Vec<_> = queued.iter().map(|q| q.depends_on.clone()).collect();
    assert_eq!(
        depends,
        [
            vec![],
            vec![cmd(1).as_str().to_string()],
            vec![],
            vec![],
            vec![cmd(4).as_str().to_string()],
        ]
    );
    // The stored envelope still carries the alias, never a guessed ID.
    assert_eq!(
        queued[4].envelope["payload"]["project_id"]["after_command"],
        cmd(4).as_str()
    );
    assert_eq!(queued[4].envelope["depends_on"], json!([cmd(4).as_str()]));
}

#[test]
fn execute_026_fr_001_v1_store_upgrades_and_keeps_its_queued_work() {
    let path = scratch("upgrade");
    let mut store = open(&path, 1_000).unwrap();
    execute(&mut store, &mut SeqIds(0), &create_task(cmd(1), "before")).unwrap();
    store.close().unwrap();
    // Take the file back to what the first release wrote.
    Connection::open(&path)
        .unwrap()
        .execute_batch(
            "DROP TABLE visible_records;
             ALTER TABLE outbox DROP COLUMN projection_generation;
             ALTER TABLE outbox DROP COLUMN local_result;
             ALTER TABLE sync_meta DROP COLUMN projection_stale;
             PRAGMA user_version = 1;",
        )
        .unwrap();

    let mut store = open(&path, 1_000).unwrap();
    assert_eq!(store.status(), StoreStatus::Ready);
    let version: i64 = store
        .read(|tx| tx.query_row("PRAGMA user_version", [], |row| row.get(0)))
        .unwrap();
    assert_eq!(version, SCHEMA_VERSION);
    assert_eq!(queue(&mut store).len(), 1);
    let second = execute(&mut store, &mut SeqIds(50), &create_task(cmd(2), "after")).unwrap();
    assert_eq!(second.local_sequence, 2);
    // The queued command of the old file still answers its retry.
    let retry = execute(&mut store, &mut SeqIds(60), &create_task(cmd(1), "before")).unwrap();
    assert!(retry.replayed);
    assert_eq!(retry.local_sequence, 1);
}

#[test]
fn execute_026_fr_001_read_only_recovery_store_refuses_execute() {
    let path = scratch("newer");
    open(&path, 1_000).unwrap().close().unwrap();
    let newer = SCHEMA_VERSION + 1;
    Connection::open(&path)
        .unwrap()
        .pragma_update(None, "user_version", newer)
        .unwrap();

    let mut store = open(&path, 1_000).unwrap();
    assert_eq!(
        execute(&mut store, &mut SeqIds(0), &create_task(cmd(1), "no")),
        Err(ExecuteError::Store(StoreError::UpgradeRequired {
            found: newer
        }))
    );
}

#[test]
fn execute_026_fr_001_consecutive_offline_settings_edits_chain_on_the_singleton_key() {
    let path = scratch("settings");
    let mut store = open(&path, 1_000).unwrap();
    let mut ids = SeqIds(0);
    let edit = |command_id, weekday: u8, revision: &str| {
        request(
            command_id,
            CommandType::ReviewSettings,
            Some("scope-a"),
            json!({ "review_weekday": weekday }),
            vec![shown(EntityType::ReviewSettings, "scope-a", revision)],
        )
    };

    execute(&mut store, &mut ids, &edit(cmd(1), 2, "1")).unwrap();
    // The settings row is a singleton stored under the empty key.
    let revision: String = store
        .read(|tx| {
            tx.query_row(
                "SELECT edit_revision FROM visible_records
                 WHERE record_type = 'review_settings' AND record_key = '[]'",
                [],
                |row| row.get(0),
            )
        })
        .unwrap();
    execute(&mut store, &mut ids, &edit(cmd(2), 3, &revision)).unwrap();

    let queued = queue(&mut store);
    assert_eq!(queued[0].envelope["preconditions"][0]["edit_revision"], "1");
    assert_eq!(
        queued[1].envelope["preconditions"],
        json!([{ "after_command": {
            "command_id": cmd(1).as_str(),
            "entity_type": "review_settings",
            "entity_id": "scope-a",
        }}])
    );
    assert_eq!(queued[1].envelope["depends_on"], json!([cmd(1).as_str()]));
    assert_eq!(queued[1].depends_on, [cmd(1).as_str().to_string()]);
}

#[test]
fn execute_026_fr_001_only_typed_reference_fields_create_dependencies() {
    let path = scratch("text");
    let mut store = open(&path, 1_000).unwrap();
    let mut ids = SeqIds(0);
    let project = request(
        cmd(1),
        CommandType::ProjectCreate,
        None,
        json!({ "name": "Trips" }),
        Vec::new(),
    );
    let project_id = execute(&mut store, &mut ids, &project)
        .unwrap()
        .entity_id
        .as_str()
        .to_string();

    // User text that happens to equal a queued project's ID is just text.
    let titled = request(
        cmd(2),
        CommandType::TaskCreate,
        None,
        json!({ "title": project_id, "details": project_id }),
        Vec::new(),
    );
    execute(&mut store, &mut ids, &titled).unwrap();
    // The same ID in a reference field is a real dependency.
    let member = request(
        cmd(3),
        CommandType::TaskCreate,
        None,
        json!({ "title": "Pack", "project_id": project_id }),
        Vec::new(),
    );
    execute(&mut store, &mut ids, &member).unwrap();

    let depends: Vec<_> = queue(&mut store)
        .into_iter()
        .map(|q| q.depends_on)
        .collect();
    assert_eq!(depends, [vec![], vec![], vec![cmd(1).as_str().to_string()]]);
}

#[test]
fn bulk_item_after_command_uses_actual_result_and_retry_keeps_original_fingerprint() {
    use bb_protocol::command::{AfterCommandPrecondition, CommandRef};
    let path = scratch("bulk-after-result");
    let mut store = open(&path, 1_000).unwrap();
    let mut ids = SeqIds(0);
    let created = execute(&mut store, &mut ids, &create_task(cmd(70), "Inbox item")).unwrap();
    let task_id = created.entity_id.as_str();
    let shown_revision = task(&mut store, task_id)["revision"]
        .as_str()
        .unwrap()
        .to_owned();
    let edit = request(
        cmd(71),
        CommandType::TaskUpdate,
        Some(task_id),
        json!({"title":"Clarified item"}),
        vec![shown(EntityType::Task, task_id, &shown_revision)],
    );
    let reference = Precondition::AfterCommand(AfterCommandPrecondition {
        after_command: CommandRef {
            command_id: cmd(71),
            entity_type: EntityType::Task,
            entity_id: created.entity_id.clone(),
        },
    });
    let bulk_id = "bulk_00000000-0000-4000-8000-000000000073";
    let mut release = request(
        cmd(72),
        CommandType::ReviewBulkRelease,
        Some(bulk_id),
        json!({"kind":"inbox_remainder","items":[{"task_id":task_id,"expected_revision":shown_revision}]}),
        vec![reference.clone()],
    );
    release.context.policy.weekly_review = true;
    let results = execute_batch(&mut store, &mut ids, &[edit, release.clone()]).unwrap();
    assert_eq!(results.len(), 2);
    assert_eq!(task(&mut store, task_id)["state"], "someday");
    let queued = queue(&mut store);
    assert_eq!(
        queued[2].envelope["payload"]["items"][0]["expected_revision"],
        "2"
    );
    assert!(queued[2].depends_on.contains(&cmd(71).as_str().to_owned()));
    assert!(execute(&mut store, &mut ids, &release).unwrap().replayed);
    let mut changed = release.clone();
    changed.preconditions.clear();
    assert_eq!(
        execute(&mut store, &mut ids, &changed),
        Err(ExecuteError::CommandIdReused)
    );
    let queue_len = queue(&mut store).len();
    for (number, preconditions) in [
        (73, vec![reference.clone(), reference]),
        (
            74,
            vec![Precondition::AfterCommand(AfterCommandPrecondition {
                after_command: CommandRef {
                    command_id: cmd(71),
                    entity_type: EntityType::Task,
                    entity_id: Id::parse("task_missing").unwrap(),
                },
            })],
        ),
        (
            75,
            vec![Precondition::AfterCommand(AfterCommandPrecondition {
                after_command: CommandRef {
                    command_id: cmd(99),
                    entity_type: EntityType::Task,
                    entity_id: created.entity_id.clone(),
                },
            })],
        ),
    ] {
        let mut invalid = release.clone();
        invalid.command_id = cmd(number);
        invalid.entity_id =
            Some(Id::parse(format!("bulk_00000000-0000-4000-8000-{number:012}")).unwrap());
        invalid.preconditions = preconditions;
        assert!(matches!(
            execute(&mut store, &mut ids, &invalid),
            Err(ExecuteError::Refused(_))
        ));
        assert_eq!(queue(&mut store).len(), queue_len);
    }
}

#[test]
fn same_batch_bulk_skip_keeps_frozen_guard_and_dependency_without_inventing_result() {
    use bb_protocol::command::{AfterCommandPrecondition, CommandRef};
    let path = scratch("bulk-skip-guard");
    let mut store = open(&path, 1_000).unwrap();
    let mut ids = SeqIds(0);
    let a = execute(&mut store, &mut ids, &create_task(cmd(80), "Release me")).unwrap();
    let b = execute(&mut store, &mut ids, &create_task(cmd(81), "Keep next")).unwrap();
    let moved = request(
        cmd(82),
        CommandType::TaskTransition,
        Some(b.entity_id.as_str()),
        json!({"action":"move","to_state":"next"}),
        vec![shown(EntityType::Task, b.entity_id.as_str(), "1")],
    );
    execute(&mut store, &mut ids, &moved).unwrap();
    let mut bulk = request(
        cmd(83),
        CommandType::ReviewBulkRelease,
        Some("bulk_00000000-0000-4000-8000-000000000083"),
        json!({"kind":"inbox_remainder","items":[{"task_id":a.entity_id.as_str(),"expected_revision":"1"},{"task_id":b.entity_id.as_str(),"expected_revision":"2"}]}),
        vec![],
    );
    bulk.context.policy.weekly_review = true;
    let edit = |n, target: &Id, predecessor| {
        request(
            cmd(n),
            CommandType::TaskUpdate,
            Some(target.as_str()),
            json!({"title":"Saved editor text"}),
            vec![Precondition::AfterCommand(AfterCommandPrecondition {
                after_command: CommandRef {
                    command_id: cmd(predecessor),
                    entity_type: EntityType::Task,
                    entity_id: target.clone(),
                },
            })],
        )
    };
    let batch = vec![bulk, edit(84, &a.entity_id, 83), edit(85, &b.entity_id, 83)];
    assert_eq!(
        execute_batch(&mut store, &mut ids, &batch).unwrap().len(),
        3
    );
    assert_eq!(task(&mut store, a.entity_id.as_str())["state"], "someday");
    assert_eq!(task(&mut store, b.entity_id.as_str())["state"], "next");
    let queued = queue(&mut store);
    assert!(queued[5].depends_on.contains(&cmd(83).as_str().to_owned()));
    assert_eq!(
        queued[4].envelope["preconditions"][0]["after_command"]["command_id"],
        cmd(83).as_str()
    );
    assert_eq!(
        queued[5].envelope["preconditions"][0]["after_command"]["command_id"],
        cmd(82).as_str()
    );
    assert!(
        execute_batch(&mut store, &mut ids, &batch)
            .unwrap()
            .iter()
            .all(|saved| saved.replayed)
    );
    assert!(matches!(
        execute(&mut store, &mut ids, &edit(86, &b.entity_id, 83)),
        Err(ExecuteError::Refused(_))
    ));
    let before = queue(&mut store).len();
    let mut stale = batch[0].clone();
    stale.command_id = cmd(87);
    stale.entity_id = Some(Id::parse("bulk_00000000-0000-4000-8000-000000000087").unwrap());
    stale.payload=json!({"kind":"inbox_remainder","items":[{"task_id":b.entity_id.as_str(),"expected_revision":"2"}]}).as_object().unwrap().clone();
    assert!(matches!(
        execute_batch(&mut store, &mut ids, &[stale, edit(88, &b.entity_id, 87)]),
        Err(ExecuteError::Refused(_))
    ));
    assert_eq!(queue(&mut store).len(), before);
}
