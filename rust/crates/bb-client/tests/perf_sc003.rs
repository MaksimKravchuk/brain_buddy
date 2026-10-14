//! 026 SC-003 local-latency evidence: a 10,000-task store with a 1,300-row
//! outbox. The timing test is `#[ignore]`d (run it in release with
//! `cargo test --release -p bb-client --test perf_sc003 -- --ignored --nocapture`);
//! the equivalence test always runs on a smaller store of the same shape.
//!
//! The device-latency budget (<= 50 ms p95 on an iPhone 11) is judged on the
//! device; this prints the host numbers the optimisation is measured with.

use bb_client::{
    ExecuteContext, ExecuteRequest, IdSource, OpenOptions, Store, execute, query_page,
};
use bb_domain::types::{ActorId, Policy, QueryInputs, ZoneName};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{Precondition, RevisionPrecondition};
use bb_protocol::wire::{CommandId, Counter, Id, Instant};
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;
use std::time::{Duration, Instant as Clock};

const WORKSPACE: &str = "workspace-local";
const NOW: &str = "2026-10-10T09:00:00Z";

struct SeqIds(u64);

impl IdSource for SeqIds {
    fn uuid(&mut self) -> std::io::Result<String> {
        self.0 += 1;
        Ok(format!("00000000-0000-4000-8000-{:012x}", self.0))
    }
}

fn scratch(name: &str) -> PathBuf {
    let directory = std::env::temp_dir().join(format!("bb-perf-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    directory.join("store").join("workspace.sqlite3")
}

fn open(path: &std::path::Path) -> Store {
    Store::open(&OpenOptions {
        path: path.to_path_buf(),
        workspace_id: WORKSPACE.to_string(),
        busy_timeout: Duration::from_secs(5),
    })
    .unwrap()
}

fn context() -> ExecuteContext {
    ExecuteContext {
        now: Instant::parse(NOW).unwrap(),
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

fn inputs() -> QueryInputs {
    QueryInputs {
        now: context().now,
        device_zone: context().time_zone,
        policy: context().policy,
    }
}

fn cmd(n: u64) -> CommandId {
    CommandId::parse(format!("01900000-0000-4000-8000-{n:012}")).unwrap()
}

fn task_id(n: usize) -> String {
    format!("task-{n:06}")
}

/// Synthetic store: `tasks` visible tasks across inbox/next/waiting/someday,
/// `outbox` finished intents (a third of them subtask/comment edits), and, when
/// `legacy_drafts`, one imported `legacy_task_local` carrier per task.
fn populate(store: &mut Store, tasks: usize, outbox: usize, legacy_drafts: bool, local_only: bool) {
    store
        .write(|tx| {
            let states = ["inbox", "next", "waiting", "someday"];
            let mut task_row = tx.prepare(
                "INSERT INTO visible_records (workspace_id, record_type, record_key,
                    edit_revision, source_command_id, body)
                 VALUES (?1, 'task', ?2, '1', NULL, ?3)",
            )?;
            let mut draft = tx.prepare(
                "INSERT INTO drafts (workspace_id, draft_id, editor_kind, record_type,
                    record_key, fields, base_revision, updated_at)
                 VALUES (?1, ?2, 'legacy_task_local', 'task', ?3, ?4, NULL, ?5)",
            )?;
            for n in 0..tasks {
                let id = task_id(n);
                let state = states[n % states.len()];
                let waiting = state == "waiting";
                let created = format!("2026-09-01T09:{:02}:{:02}Z", (n / 60) % 60, n % 60);
                let body = json!({
                    "id": id, "title": format!("Task {n}"), "details": null, "state": state,
                    "project_id": null, "tag_ids": [], "due_date": null, "priority": "none",
                    "waiting_for": waiting.then_some("Sam"),
                    "waiting_since": waiting.then(|| created.clone()),
                    "order_key": ((n + 1) * 10).to_string(),
                    "source_capture_ids": [], "created_at": created, "updated_at": created,
                    "completed_at": null, "cancelled_at": null,
                    "revision": "1", "consecutive_stalled_formulations": 0,
                    "formulation": null, "parked": null,
                });
                let key = json!([id]).to_string();
                task_row.execute(rusqlite::params![WORKSPACE, key, body.to_string().into_bytes()])?;
                if legacy_drafts {
                    draft.execute(rusqlite::params![
                        WORKSPACE,
                        format!("legacy-task-local:{id}"),
                        key,
                        br#"{"lastOpenList":null,"childrenSyncedAt":null}"#.to_vec(),
                        "1970-01-01T00:00:00Z",
                    ])?;
                }
            }
            let types = [
                "task.update",
                "subtask.create",
                "task.update",
                "comment.create",
                "task.transition",
                "subtask.update",
            ];
            let start: i64 = tx.query_row("SELECT next_local_seq FROM sync_meta", [], |r| r.get(0))?;
            let mut insert = tx.prepare(
                "INSERT INTO outbox (workspace_id, command_id, device_epoch, local_seq, envelope,
                    envelope_digest, state, created_at)
                 VALUES (?1, ?2, 'epoch-1', ?3, ?4, x'00', ?5, ?6)",
            )?;
            for n in 0..outbox {
                let kind = types[n % types.len()];
                let envelope = json!({
                    "protocol_version": 1,
                    "command_id": format!("perf-{n:08}"), "local_sequence": (start + n as i64).to_string(),
                    "type": kind, "entity_id": task_id(n * 7 % tasks),
                    "preconditions": [], "depends_on": [], "issued_at": NOW,
                    "payload": {"task_id": task_id(n * 7 % tasks), "title": "x"},
                });
                // The newest 100 are still queued; the rest are settled history.
                let state = if n + 100 >= outbox && !local_only {
                    "queued"
                } else {
                    "completed"
                };
                insert.execute(rusqlite::params![
                    WORKSPACE,
                    format!("perf-{n:08}"),
                    start + n as i64,
                    envelope.to_string().into_bytes(),
                    state,
                    NOW,
                ])?;
            }
            if local_only {
                tx.execute("UPDATE sync_meta SET account_link_state = 'account_less'", [])?;
            }
            tx.execute(
                "UPDATE sync_meta SET next_local_seq = ?1, projection_generation = projection_generation + 1",
                [start + outbox as i64],
            )?;
            Ok(())
        })
        .unwrap();
}

fn inbox_query() -> bb_domain::types::Query {
    serde_json::from_value(json!({
        "kind": "list_mode", "mode": {"type": "open_list", "list": "inbox"},
        "options": {}, "page": {"limit": 50},
    }))
    .unwrap()
}

fn list_query() -> bb_domain::types::Query {
    serde_json::from_value(
        json!({"kind":"task_list","list":"inbox","sort":"manual","page":{"limit":50}}),
    )
    .unwrap()
}

fn percentile(samples: &mut [f64], p: f64) -> f64 {
    samples.sort_by(|a, b| a.total_cmp(b));
    samples[((samples.len() as f64 * p).ceil() as usize).clamp(1, samples.len()) - 1]
}

fn report(label: &str, samples: &mut [f64]) {
    println!(
        "  {label:<34} n={:<4} p50={:>8.2} ms  p95={:>8.2} ms  max={:>8.2} ms",
        samples.len(),
        percentile(samples, 0.5),
        percentile(samples, 0.95),
        percentile(samples, 1.0),
    );
}

fn timed<T>(body: impl FnOnce() -> T) -> (T, f64) {
    let start = Clock::now();
    let value = body();
    (value, start.elapsed().as_secs_f64() * 1_000.0)
}

fn scenario(
    label: &str,
    tasks: usize,
    outbox: usize,
    legacy_drafts: bool,
    local_only: bool,
    operations: usize,
) {
    println!(
        "{label}: {tasks} tasks, {outbox} outbox rows, legacy drafts: {legacy_drafts}, local-only: {local_only}"
    );
    let path = scratch(label);
    let mut store = open(&path);
    populate(&mut store, tasks, outbox, legacy_drafts, local_only);
    store.close().unwrap();
    let mut store = open(&path);
    let mut ids = SeqIds(0);

    // The first call on a newly opened handle (app launch, widget, App Intent)
    // decodes the whole projection; later calls reuse it.
    let (_, cold) = timed(|| query_page(&mut store, &inbox_query(), &inputs()).unwrap());
    println!("  cold first query (new handle)      {cold:>8.2} ms");
    query_page(&mut store, &list_query(), &inputs()).unwrap();

    let (mut list_mode, mut task_list) = (Vec::new(), Vec::new());
    for _ in 0..20 {
        list_mode.push(timed(|| query_page(&mut store, &inbox_query(), &inputs()).unwrap()).1);
        task_list.push(timed(|| query_page(&mut store, &list_query(), &inputs()).unwrap()).1);
    }
    report("query inbox list_mode (50)", &mut list_mode);
    report("query inbox task_list (50)", &mut task_list);

    // Edit tasks that an Inbox page just showed, carrying the admission token
    // the UI holds (create / title edit / move, as SC-003 mixes them).
    let page = query_page(&mut store, &list_query(), &inputs()).unwrap();
    let frames = page.task_frames;
    let (mut creates, mut edits, mut moves) = (Vec::new(), Vec::new(), Vec::new());
    for n in 0..operations {
        let seq = 10_000_000 + (n as u64) * 3;
        let create = ExecuteRequest {
            command_id: cmd(seq),
            command_type: CommandType::TaskCreate,
            entity_id: None,
            payload: json!({"title": format!("New {n}")})
                .as_object()
                .unwrap()
                .clone(),
            preconditions: Vec::new(),
            depends_on: Vec::new(),
            admission_tokens: Vec::new(),
            context: context(),
        };
        creates.push(timed(|| execute(&mut store, &mut ids, &create).unwrap()).1);

        let frame = &frames[n % frames.len()];
        let target = frame.token.task_id.as_str().to_owned();
        let shown = Precondition::Revision(RevisionPrecondition {
            entity_type: EntityType::Task,
            entity_id: Id::parse(&target).unwrap(),
            edit_revision: Counter::parse("1").unwrap(),
        });
        let edit = ExecuteRequest {
            command_id: cmd(seq + 1),
            command_type: CommandType::TaskUpdate,
            entity_id: Some(Id::parse(&target).unwrap()),
            payload: json!({"title": format!("Edited {n}")})
                .as_object()
                .unwrap()
                .clone(),
            preconditions: vec![shown],
            depends_on: Vec::new(),
            admission_tokens: vec![frame.token.clone()],
            context: context(),
        };
        // Each page task is edited at most once at revision 1.
        if n < frames.len() {
            edits.push(timed(|| execute(&mut store, &mut ids, &edit).unwrap()).1);
        }

        let target_move = task_id(4 * (n + 1) + 1); // a "next" task, revision 1
        let moved = ExecuteRequest {
            command_id: cmd(seq + 2),
            command_type: CommandType::TaskTransition,
            entity_id: Some(Id::parse(&target_move).unwrap()),
            payload: json!({"action": "complete"}).as_object().unwrap().clone(),
            preconditions: vec![Precondition::Revision(RevisionPrecondition {
                entity_type: EntityType::Task,
                entity_id: Id::parse(&target_move).unwrap(),
                edit_revision: Counter::parse("1").unwrap(),
            })],
            depends_on: Vec::new(),
            admission_tokens: Vec::new(),
            context: context(),
        };
        moves.push(timed(|| execute(&mut store, &mut ids, &moved).unwrap()).1);
    }
    let mut all: Vec<f64> = creates
        .iter()
        .chain(&edits)
        .chain(&moves)
        .copied()
        .collect();
    report("execute create", &mut creates);
    report("execute title edit (+token)", &mut edits);
    report("execute complete", &mut moves);
    report("execute pooled", &mut all);
    store.close().unwrap();
    let _ = fs::remove_dir_all(path.parent().unwrap().parent().unwrap());
}

#[test]
#[ignore = "SC-003 timing evidence; run with --release --ignored --nocapture"]
fn perf_026_sc_003_ten_thousand_tasks_thirteen_hundred_outbox_rows() {
    scenario("linked-queue", 10_000, 1_300, false, false, 60);
    scenario("imported-drafts", 10_000, 1_300, true, false, 60);
    scenario("local-only", 10_000, 1_300, true, true, 60);
}

#[test]
fn perf_026_sc_003_fixture_queries_and_gestures_work_on_a_small_store() {
    // The same shape at a size that runs in every `cargo test`.
    scenario("small", 400, 60, true, false, 8);
    scenario("small-local", 400, 60, true, true, 8);
    let _: Option<Value> = None;
}
