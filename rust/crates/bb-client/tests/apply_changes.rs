//! Feed and receipt application tests: the confirmed base only ever moves by
//! whole commit-ordered transactions, a gap or a duplicate is detected and
//! changes nothing, a receipt settles its command without writing the base,
//! and an oversized transaction is invisible until it is complete and verified.
//!
//! Everything goes through the public API on a real SQLite file, across store
//! reopenings and real process aborts. The server side is played by building
//! the wire JSON the contract describes and decoding it with the `bb-protocol`
//! codecs, so a page the codec would refuse never reaches the runtime.

use bb_client::{
    Applied, ApplyError, ApplyStage, ExecuteContext, ExecuteRequest, FeedStep, IdSource, Looked,
    OpenOptions, Recovery, Settlement, Store, StoreError, TransferFault, abandon_transfer,
    apply_changes, apply_changes_with, apply_lookup, apply_receipt, apply_transfer,
    apply_transfer_with, capture_fence, execute, open_issues, sha256_hex, stage_transfer_page,
};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{
    AfterCommandPrecondition, CommandRef, Precondition, RevisionPrecondition,
};
use bb_protocol::feed::{ChangesPage, TransferPage};
use bb_protocol::receipt::{CommandLookup, Receipt};
use bb_protocol::wire::{CommandId, Counter, Id, Instant, decode};
use rusqlite::params;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::OnceLock;
use std::time::Duration;

const WORKSPACE: &str = "workspace-local";
const SCOPE: &str = "scope-1";
const GENERATION: &str = "generation-1";
const NOW: &str = "2026-10-10T09:00:00Z";
const ROLE: &str = "BB_APPLY_CHILD";

/// A way a manifest can disagree with the stream it announces.
type Lie = fn(&mut Value);

// ----------------------------------------------------------------------- harness

fn scratch(name: &str) -> PathBuf {
    let directory = std::env::temp_dir().join(format!("bb-apply-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    directory.join("store").join("workspace.sqlite3")
}

fn open(path: &Path) -> Result<Store, StoreError> {
    Store::open(&OpenOptions {
        path: path.to_path_buf(),
        workspace_id: WORKSPACE.to_string(),
        busy_timeout: Duration::from_millis(5_000),
    })
}

/// A store bound to a scope and server generation, with a confirmed base at
/// cursor `cursor-0`, watermark 0: what a finished bootstrap leaves.
fn linked(path: &Path) -> Store {
    let mut store = open(path).unwrap();
    bind(&mut store);
    store
}

fn bind(store: &mut Store) {
    store
        .write(|tx| {
            tx.execute(
                "UPDATE sync_meta SET scope_id = ?1, device_id = 'device-1',
                    server_generation = ?2, cursor = 'cursor-0', base_watermark = '0',
                    account_link_state = 'linked'",
                params![SCOPE, GENERATION],
            )?;
            Ok(())
        })
        .unwrap();
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

fn id(n: u64) -> String {
    cmd(n).as_str().to_string()
}

fn context_at(now: &str) -> ExecuteContext {
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

fn context() -> ExecuteContext {
    context_at(NOW)
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
        admission_tokens: Vec::new(),
        context: context(),
    }
}

fn shown(entity_type: EntityType, id: &str, revision: &str) -> Precondition {
    Precondition::Revision(RevisionPrecondition {
        entity_type,
        entity_id: Id::parse(id).unwrap(),
        edit_revision: Counter::parse(revision).unwrap(),
    })
}

fn after(command: &CommandId, entity_type: EntityType, id: &str) -> Precondition {
    Precondition::AfterCommand(AfterCommandPrecondition {
        after_command: CommandRef {
            command_id: command.clone(),
            entity_type,
            entity_id: Id::parse(id).unwrap(),
        },
    })
}

fn create_task(store: &mut Store, ids: &mut SeqIds, n: u64, title: &str) -> String {
    let created = request(
        cmd(n),
        CommandType::TaskCreate,
        None,
        json!({ "title": title }),
        Vec::new(),
    );
    execute(store, ids, &created)
        .unwrap()
        .entity_id
        .as_str()
        .to_string()
}

fn edit(
    store: &mut Store,
    ids: &mut SeqIds,
    n: u64,
    task_id: &str,
    payload: Value,
    precondition: Precondition,
) {
    let update = request(
        cmd(n),
        CommandType::TaskUpdate,
        Some(task_id),
        payload,
        vec![precondition],
    );
    execute(store, ids, &update).unwrap();
}

// ------------------------------------------------------------------ the server side

/// A task after-image, in the shape the runtime itself projects.
fn task_template() -> &'static Value {
    static TEMPLATE: OnceLock<Value> = OnceLock::new();
    TEMPLATE.get_or_init(|| {
        let path = scratch("template");
        let mut store = open(&path).unwrap();
        create_task(&mut store, &mut SeqIds(0), 1, "Template");
        let body: Vec<u8> = store
            .read(|tx| {
                tx.query_row(
                    "SELECT body FROM visible_records WHERE record_type = 'task'",
                    [],
                    |row| row.get(0),
                )
            })
            .unwrap();
        serde_json::from_slice(&body).unwrap()
    })
}

fn task_image(task_id: &str, title: &str, revision: u64) -> Value {
    let mut value = task_template().clone();
    value["id"] = json!(task_id);
    value["title"] = json!(title);
    value["revision"] = json!(revision.to_string());
    value
}

fn task_change(task_id: &str, title: &str, revision: u64, version: u64) -> Value {
    json!({
        "entity_type": "task",
        "record_key": [task_id],
        "record_version": version.to_string(),
        "edit_revision": revision.to_string(),
        "operation": "upsert",
        "value": task_image(task_id, title, revision),
    })
}

fn tombstone(task_id: &str, version: u64) -> Value {
    json!({
        "entity_type": "task",
        "record_key": [task_id],
        "record_version": version.to_string(),
        "operation": "tombstone",
        "value": null,
    })
}

fn common() -> Value {
    json!({
        "correlation_id": "corr-1",
        "scope_id": SCOPE,
        "server_generation": GENERATION,
        "server_now": NOW,
    })
}

fn with_common(mut body: Value) -> Value {
    for (key, value) in common().as_object().unwrap() {
        body[key] = value.clone();
    }
    body
}

/// Transaction `seq`, written by `source` (an external writer unless a test
/// names one of its own commands).
fn transaction(seq: u64, source: &CommandId, changes: Vec<Value>) -> Value {
    json!({
        "transaction_id": format!("tx-{seq}"),
        "commit_seq": seq.to_string(),
        "source_command_id": source.as_str(),
        "changes": changes,
    })
}

fn external(seq: u64) -> CommandId {
    cmd(900 + seq)
}

fn page_json(from: &str, transactions: Vec<Value>, next: &str, high: u64, more: bool) -> Value {
    with_common(json!({
        "from_cursor": from,
        "transactions": transactions,
        "has_more": more,
        "next_cursor": next,
        "high_watermark": high.to_string(),
    }))
}

/// A page that stops short of the server's high watermark.
fn page_more(from: &str, transactions: Vec<Value>, to: &str, high: u64) -> ChangesPage {
    decode_page(&page_json(from, transactions, to, high, true))
}

fn decode_page(value: &Value) -> ChangesPage {
    decode(&value.to_string()).unwrap()
}

/// One page of complete transactions from `from`, ending at `to`.
fn page(from: &str, transactions: Vec<Value>, to: &str, high: u64) -> ChangesPage {
    decode_page(&page_json(from, transactions, to, high, false))
}

fn apply(store: &mut Store, page: &ChangesPage) -> Result<FeedStep, ApplyError> {
    let fence = capture_fence(store).unwrap();
    apply_changes(store, &context(), &fence, page)
}

fn applied(step: FeedStep) -> Applied {
    match step {
        FeedStep::Applied(applied) => applied,
        other => panic!("expected an applied page, got {other:?}"),
    }
}

fn accepted(command: &CommandId, seq: u64) -> Receipt {
    decode(
        &with_common(json!({
            "command_id": command.as_str(),
            "outcome": "accepted",
            "has_changes": true,
            "commit_seq": seq.to_string(),
            "result_versions": [],
            "id_bindings": [],
            "result_redacted": false,
            "result": null,
            "error": null,
        }))
        .to_string(),
    )
    .unwrap()
}

fn no_op(command: &CommandId) -> Receipt {
    decode(
        &with_common(json!({
            "command_id": command.as_str(),
            "outcome": "accepted",
            "has_changes": false,
            "commit_seq": null,
            "result_versions": [],
            "id_bindings": [],
            "result_redacted": false,
            "result": null,
            "error": null,
        }))
        .to_string(),
    )
    .unwrap()
}

fn rejected(command: &CommandId, code: &str, retryable: bool) -> Receipt {
    decode(
        &with_common(json!({
            "command_id": command.as_str(),
            "outcome": "rejected",
            "has_changes": false,
            "commit_seq": null,
            "result_versions": [],
            "id_bindings": [],
            "result_redacted": false,
            "result": null,
            "error": { "code": code, "retryable": retryable, "message": "refused", "details": {} },
        }))
        .to_string(),
    )
    .unwrap()
}

/// An acceptance carrying what the server resolved: the versions it wrote and
/// the entity it bound each proposed alias to.
fn accepted_with(command: &CommandId, seq: u64, versions: Value, bindings: Value) -> Receipt {
    decode(
        &with_common(json!({
            "command_id": command.as_str(),
            "outcome": "accepted",
            "has_changes": true,
            "commit_seq": seq.to_string(),
            "result_versions": versions,
            "id_bindings": bindings,
            "result_redacted": false,
            "result": null,
            "error": null,
        }))
        .to_string(),
    )
    .unwrap()
}

fn project_template() -> &'static Value {
    static TEMPLATE: OnceLock<Value> = OnceLock::new();
    TEMPLATE.get_or_init(|| {
        let path = scratch("project-template");
        let mut store = open(&path).unwrap();
        let created = request(
            cmd(1),
            CommandType::ProjectCreate,
            None,
            json!({ "name": "Template" }),
            Vec::new(),
        );
        execute(&mut store, &mut SeqIds(0), &created).unwrap();
        let body: Vec<u8> = store
            .read(|tx| {
                tx.query_row(
                    "SELECT body FROM visible_records WHERE record_type = 'project'",
                    [],
                    |row| row.get(0),
                )
            })
            .unwrap();
        serde_json::from_slice(&body).unwrap()
    })
}

fn project_change(project_id: &str, name: &str, version: u64) -> Value {
    let mut value = project_template().clone();
    value["id"] = json!(project_id);
    value["name"] = json!(name);
    value["revision"] = json!("1");
    json!({
        "entity_type": "project",
        "record_key": [project_id],
        "record_version": version.to_string(),
        "edit_revision": "1",
        "operation": "upsert",
        "value": value,
    })
}

fn settle(store: &mut Store, receipt: &Receipt) -> Result<bb_client::Settled, ApplyError> {
    let fence = capture_fence(store).unwrap();
    apply_receipt(store, &context(), &fence, receipt)
}

// -------------------------------------------------------------------- the store

fn states(store: &mut Store) -> BTreeMap<String, String> {
    store
        .read(|tx| {
            let mut statement = tx.prepare("SELECT command_id, state FROM outbox")?;
            let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
            rows.collect()
        })
        .unwrap()
}

fn state(store: &mut Store, n: u64) -> String {
    states(store)[cmd(n).as_str()].clone()
}

/// The command was sent and its outcome is not known yet.
fn set_state(store: &mut Store, n: u64, state: &str, ever_sent: bool) {
    store
        .write(|tx| {
            tx.execute(
                "UPDATE outbox SET state = ?2, ever_sent = ?3 WHERE command_id = ?1",
                params![cmd(n).as_str(), state, i64::from(ever_sent)],
            )?;
            Ok(())
        })
        .unwrap();
}

/// `(record_type, record_key, record_version, tombstone)` of the confirmed base.
fn confirmed(store: &mut Store) -> Vec<(String, String, String, i64)> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT record_type, record_key, record_version, tombstone
                 FROM confirmed_records ORDER BY record_type, record_key",
            )?;
            let rows = statement.query_map([], |row| {
                Ok((row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?))
            })?;
            rows.collect()
        })
        .unwrap()
}

/// The cursor and watermark of the confirmed base.
fn position(store: &mut Store) -> (String, String) {
    store
        .read(|tx| {
            tx.query_row("SELECT cursor, base_watermark FROM sync_meta", [], |row| {
                Ok((row.get(0)?, row.get(1)?))
            })
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

fn task(store: &mut Store, id: &str) -> Option<Value> {
    visible(store, "task")
        .into_iter()
        .find(|task| task["id"] == id)
}

fn revision(store: &mut Store, task_id: &str) -> String {
    task(store, task_id).unwrap()["revision"]
        .as_str()
        .unwrap()
        .to_string()
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

fn staging(store: &mut Store) -> Vec<(String, i64)> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT b.state, (SELECT COUNT(*) FROM staging_pages p
                                   WHERE p.activation_id = b.activation_id)
                 FROM staging_bases b ORDER BY b.activation_id",
            )?;
            let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
            rows.collect()
        })
        .unwrap()
}

/// `T` created by the server in transaction 1 (an external writer), applied.
fn confirmed_task(store: &mut Store, task_id: &str, title: &str) {
    let seeded = page(
        "cursor-0",
        vec![transaction(
            1,
            &external(1),
            vec![task_change(task_id, title, 1, 1)],
        )],
        "cursor-1",
        1,
    );
    applied(apply(store, &seeded).unwrap());
}

const T: &str = "task_00000000-0000-4000-8000-0000000000aa";

// ------------------------------------------------------------------ child processes

fn spawn(role: &str, path: &Path, page: &Value) -> Child {
    Command::new(std::env::current_exe().unwrap())
        .args([
            "apply_child_entry",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ])
        .env(ROLE, role)
        .env("BB_APPLY_PATH", path)
        .env("BB_APPLY_PAGE", page.to_string())
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

fn announce(marker: &str) {
    println!("{marker}");
    std::io::stdout().flush().unwrap();
}

#[test]
fn apply_child_entry() {
    let Ok(role) = std::env::var(ROLE) else {
        return;
    };
    let path = PathBuf::from(std::env::var("BB_APPLY_PATH").unwrap());
    let page =
        decode_page(&serde_json::from_str(&std::env::var("BB_APPLY_PAGE").unwrap()).unwrap());
    let mut store = open(&path).unwrap();
    let fence = capture_fence(&mut store).unwrap();
    match role.as_str() {
        // Killed with the base installed but the transaction not committed.
        "abort_before_commit" => {
            let _ = apply_changes_with(&mut store, &context(), &fence, &page, |stage, _| {
                if stage == ApplyStage::Replayed {
                    announce("installed");
                    std::process::abort();
                }
                Ok(())
            });
        }
        // Killed right after the commit returned.
        "abort_after_commit" => {
            apply_changes(&mut store, &context(), &fence, &page).unwrap();
            announce("committed");
            std::process::abort();
        }
        other => panic!("unknown child role {other}"),
    }
}

// --------------------------------------------------------------- transfer builders

fn base64_encode(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut text = String::new();
    for chunk in bytes.chunks(3) {
        let bits = chunk.iter().enumerate().fold(0_u32, |bits, (index, byte)| {
            bits | u32::from(*byte) << (16 - 8 * index)
        });
        for position in 0..4 {
            if position <= chunk.len() {
                text.push(char::from(
                    ALPHABET[(bits >> (18 - 6 * position) & 63) as usize],
                ));
            } else {
                text.push('=');
            }
        }
    }
    text
}

/// A transaction too large for a page: its manifest page and its byte pages.
struct Oversized {
    manifest_page: Value,
    pages: Vec<Value>,
    stream: Vec<u8>,
}

fn oversized(seq: u64, source: &CommandId, after_cursor: &str, changes: &[Value]) -> Oversized {
    let stream = serde_json::to_vec(&json!(changes)).unwrap();
    let chunks: Vec<&[u8]> = stream.chunks(331).collect();
    let pages: Vec<Value> = chunks
        .iter()
        .enumerate()
        .map(|(index, chunk)| {
            let last = index + 1 == chunks.len();
            with_common(json!({
                "transfer_id": "transfer-1",
                "page_index": index,
                "payload_base64": base64_encode(chunk),
                "page_sha256": sha256_hex(chunk),
                "has_more": !last,
                "next_page_token": if last { Value::Null } else { json!(format!("token-{}", index + 1)) },
            }))
        })
        .collect();
    let manifest = json!({
        "transfer_id": "transfer-1",
        "transaction_id": format!("tx-{seq}"),
        "commit_seq": seq.to_string(),
        "source_command_id": source.as_str(),
        "page_count": pages.len(),
        "record_count": changes.len(),
        "total_bytes": stream.len(),
        "sha256": sha256_hex(&stream),
        "expires_at": "2026-10-10T09:30:00Z",
        "first_page_token": "token-0",
        "after_cursor": after_cursor,
    });
    let manifest_page = with_common(json!({
        "from_cursor": "cursor-0",
        "transactions": [],
        "has_more": true,
        "next_cursor": "cursor-0",
        "high_watermark": seq.to_string(),
        "transaction_manifest": manifest,
    }));
    Oversized {
        manifest_page,
        pages,
        stream,
    }
}

fn transfer_page(value: &Value) -> TransferPage {
    decode(&value.to_string()).unwrap()
}

fn stage(store: &mut Store, value: &Value) -> Result<bb_client::TransferProgress, ApplyError> {
    let fence = capture_fence(store).unwrap();
    stage_transfer_page(store, &context(), &fence, &transfer_page(value))
}

fn finish_transfer(store: &mut Store) -> Result<Applied, ApplyError> {
    let fence = capture_fence(store).unwrap();
    apply_transfer(store, &context(), &fence, &Id::parse("transfer-1").unwrap())
}

/// Six tasks: enough that the stream crosses several record boundaries.
fn big_changes() -> Vec<Value> {
    (1..=6)
        .map(|n| {
            task_change(
                &format!("task_00000000-0000-4000-8000-{:012}", n + 1000),
                &format!("Bulk {n}"),
                1,
                1,
            )
        })
        .collect()
}

fn announced(store: &mut Store, big: &Oversized) -> FeedStep {
    apply(store, &decode_page(&big.manifest_page)).unwrap()
}

// ------------------------------------------------------------------------- tests

mod apply_changes {
    use super::*;

    #[test]
    fn feed_026_fr_004_a_multi_record_page_installs_whole_transactions_and_moves_the_cursor() {
        let path = scratch("whole");
        let mut store = linked(&path);
        let (a, b, c) = (
            "task_00000000-0000-4000-8000-0000000000a1",
            "task_00000000-0000-4000-8000-0000000000a2",
            "task_00000000-0000-4000-8000-0000000000a3",
        );
        let first = transaction(
            1,
            &external(1),
            vec![task_change(a, "A", 1, 1), task_change(b, "B", 1, 1)],
        );
        let second = transaction(2, &external(2), vec![task_change(c, "C", 1, 1)]);

        let done = applied(
            apply(
                &mut store,
                &page("cursor-0", vec![first, second], "cursor-2", 2),
            )
            .unwrap(),
        );

        assert_eq!((done.transactions, done.skipped, done.watermark), (2, 0, 2));
        assert_eq!(done.cursor, "cursor-2");
        assert_eq!(confirmed(&mut store).len(), 3);
        assert_eq!(position(&mut store), ("cursor-2".into(), "2".into()));
        // The visible projection is confirmed + replay(pending), rebuilt in the
        // same commit.
        assert_eq!(visible(&mut store, "task").len(), 3);
        assert_eq!(task(&mut store, b).unwrap()["title"], "B");
        let synced: Option<String> = store
            .read(|tx| tx.query_row("SELECT last_success_at FROM sync_meta", [], |r| r.get(0)))
            .unwrap();
        assert_eq!(synced.as_deref(), Some(NOW));
    }

    #[test]
    fn feed_026_fr_004_a_bad_change_anywhere_leaves_the_whole_page_unapplied() {
        let path = scratch("atomic");
        let mut store = linked(&path);
        let good = transaction(1, &external(1), vec![task_change(T, "Good", 1, 1)]);
        let mut wrong_key = task_change(T, "Wrong", 1, 1);
        wrong_key["record_key"] = json!(["task_somebody-else"]);
        let bad = transaction(2, &external(2), vec![wrong_key]);

        let error = apply(
            &mut store,
            &page("cursor-0", vec![good, bad], "cursor-2", 2),
        )
        .unwrap_err();

        assert!(matches!(error, ApplyError::Malformed(_)), "{error:?}");
        assert!(
            confirmed(&mut store).is_empty(),
            "the good half is not kept"
        );
        assert!(visible(&mut store, "task").is_empty());
        assert_eq!(position(&mut store), ("cursor-0".into(), "0".into()));
    }

    #[test]
    fn feed_026_fr_005_a_source_command_completes_and_the_rest_replays_over_the_new_base() {
        let path = scratch("replay");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        let created = create_task(&mut store, &mut ids, 1, "Mine");
        let r1 = revision(&mut store, &created);
        edit(
            &mut store,
            &mut ids,
            2,
            &created,
            json!({ "details": "Later" }),
            after(&cmd(1), EntityType::Task, &created),
        );
        set_state(&mut store, 1, "sending", true);
        assert_eq!(r1, "1");

        // The server committed command 1, and an unrelated task alongside it.
        let step = apply(
            &mut store,
            &page(
                "cursor-0",
                vec![transaction(
                    1,
                    &cmd(1),
                    vec![
                        task_change(&created, "Mine", 1, 1),
                        task_change(T, "Other", 1, 1),
                    ],
                )],
                "cursor-1",
                1,
            ),
        )
        .unwrap();
        let done = applied(step);

        assert_eq!(done.completed, [cmd(1)]);
        assert_eq!(state(&mut store, 1), "completed");
        assert_eq!(state(&mut store, 2), "queued", "later work is untouched");
        // visible = confirmed + replay(pending): command 2 still shows over the base.
        assert_eq!(task(&mut store, &created).unwrap()["title"], "Mine");
        assert_eq!(task(&mut store, &created).unwrap()["details"], "Later");
        assert_eq!(task(&mut store, T).unwrap()["title"], "Other");
        assert_eq!(confirmed(&mut store).len(), 2);
    }

    #[test]
    fn feed_026_fr_004_a_missing_intermediate_transaction_is_a_gap_that_changes_nothing() {
        let path = scratch("gap");
        let mut store = linked(&path);
        let ahead = transaction(2, &external(2), vec![task_change(T, "Ahead", 1, 1)]);

        // From the cursor the device holds, the feed itself skipped sequence 1.
        let error = apply(
            &mut store,
            &page("cursor-0", vec![ahead.clone()], "cursor-2", 2),
        )
        .unwrap_err();
        assert_eq!(
            error,
            ApplyError::Gap {
                expected: 1,
                found: 2,
                recovery: Recovery::Snapshot
            }
        );
        assert_eq!(error.recovery(), Some(Recovery::Snapshot));

        // A page that starts somewhere else is merely out of order: refetch.
        let error = apply(&mut store, &page("cursor-1", vec![ahead], "cursor-2", 2)).unwrap_err();
        assert_eq!(error.recovery(), Some(Recovery::Refetch));
        assert_eq!(error.code(), "FEED_GAP");

        // A hole inside a page is the feed's, whatever the cursor says.
        let first = transaction(1, &external(1), vec![task_change(T, "One", 1, 1)]);
        let third = transaction(3, &external(3), vec![task_change(T, "Three", 1, 3)]);
        let error = apply(
            &mut store,
            &page("cursor-0", vec![first, third], "cursor-3", 3),
        )
        .unwrap_err();
        assert!(matches!(
            error,
            ApplyError::Gap {
                expected: 2,
                found: 3,
                ..
            }
        ));

        assert!(confirmed(&mut store).is_empty());
        assert_eq!(position(&mut store), ("cursor-0".into(), "0".into()));
    }

    #[test]
    fn feed_026_fr_004_out_of_order_pages_apply_only_after_the_refetch_fills_the_hole() {
        let path = scratch("order");
        let mut store = linked(&path);
        let a = "task_00000000-0000-4000-8000-0000000000b1";
        let b = "task_00000000-0000-4000-8000-0000000000b2";
        let early = page_more(
            "cursor-0",
            vec![
                transaction(1, &external(1), vec![task_change(a, "A", 1, 1)]),
                transaction(2, &external(2), vec![task_change(b, "B", 1, 1)]),
            ],
            "cursor-2",
            4,
        );
        let late = page(
            "cursor-2",
            vec![
                transaction(3, &external(3), vec![task_change(a, "A2", 2, 3)]),
                transaction(4, &external(4), vec![task_change(b, "B2", 2, 4)]),
            ],
            "cursor-4",
            4,
        );

        // The later page is delivered first.
        let error = apply(&mut store, &late).unwrap_err();
        assert_eq!(error.recovery(), Some(Recovery::Refetch));
        assert!(confirmed(&mut store).is_empty());

        // The earlier page arrives (the refetch), then the later one again.
        applied(apply(&mut store, &early).unwrap());
        assert_eq!(task(&mut store, a).unwrap()["title"], "A");
        let done = applied(apply(&mut store, &late).unwrap());
        assert_eq!(done.watermark, 4);
        assert_eq!(position(&mut store), ("cursor-4".into(), "4".into()));
        assert_eq!(task(&mut store, a).unwrap()["title"], "A2");
        assert_eq!(task(&mut store, b).unwrap()["title"], "B2");
    }

    #[test]
    fn feed_026_fr_004_duplicate_and_overlapping_pages_are_idempotent() {
        let path = scratch("duplicate");
        let mut store = linked(&path);
        let t1 = transaction(1, &external(1), vec![task_change(T, "One", 1, 1)]);
        let t2 = transaction(2, &external(2), vec![task_change(T, "Two", 2, 2)]);
        let t3 = transaction(3, &external(3), vec![task_change(T, "Three", 3, 3)]);
        let first = page_more("cursor-0", vec![t1, t2.clone()], "cursor-2", 3);
        applied(apply(&mut store, &first).unwrap());
        let projection: Vec<Value> = visible(&mut store, "task");

        // The same page again, as a retried request would deliver it.
        let again = applied(apply(&mut store, &first).unwrap());
        assert_eq!((again.transactions, again.skipped), (0, 2));
        assert_eq!(position(&mut store), ("cursor-2".into(), "2".into()));
        assert_eq!(visible(&mut store, "task"), projection);

        // A page that overlaps what is applied installs only the new tail.
        let overlap = page("cursor-1", vec![t2, t3], "cursor-3", 3);
        let done = applied(apply(&mut store, &overlap).unwrap());
        assert_eq!((done.transactions, done.skipped, done.watermark), (1, 1, 3));
        assert_eq!(task(&mut store, T).unwrap()["title"], "Three");
        assert_eq!(position(&mut store), ("cursor-3".into(), "3".into()));
    }

    #[test]
    fn feed_026_fr_004_an_empty_page_confirms_catch_up_and_never_a_domain_write() {
        let path = scratch("empty");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Pending");
        let generation = |store: &mut Store| -> i64 {
            store
                .read(|tx| {
                    tx.query_row("SELECT projection_generation FROM sync_meta", [], |r| {
                        r.get(0)
                    })
                })
                .unwrap()
        };
        let before = generation(&mut store);

        let done =
            applied(apply(&mut store, &page("cursor-0", Vec::new(), "cursor-0", 0)).unwrap());

        assert_eq!(done.transactions, 0);
        assert_eq!(generation(&mut store), before, "no projection churn");
        assert_eq!(position(&mut store), ("cursor-0".into(), "0".into()));
        let synced: Option<String> = store
            .read(|tx| tx.query_row("SELECT last_success_at FROM sync_meta", [], |r| r.get(0)))
            .unwrap();
        assert_eq!(synced.as_deref(), Some(NOW));

        // An empty page is not recovery: if the server reports commits the
        // device does not hold, that is a gap, not "caught up".
        let error = apply(&mut store, &page("cursor-0", Vec::new(), "cursor-0", 5)).unwrap_err();
        assert!(matches!(
            error,
            ApplyError::Gap {
                recovery: Recovery::Snapshot,
                ..
            }
        ));
        // A stale empty page from another position changes nothing.
        let stale =
            applied(apply(&mut store, &page("cursor-9", Vec::new(), "cursor-9", 0)).unwrap());
        assert_eq!(stale.transactions, 0);
    }

    #[test]
    fn feed_026_fr_010_a_tombstone_is_final_and_a_pending_edit_is_kept_as_an_issue() {
        let path = scratch("tombstone");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        confirmed_task(&mut store, T, "Base");
        edit(
            &mut store,
            &mut ids,
            2,
            T,
            json!({ "title": "Mine" }),
            shown(EntityType::Task, T, "1"),
        );
        assert_eq!(task(&mut store, T).unwrap()["title"], "Mine");

        // Another device deleted T.
        let deleted = page(
            "cursor-1",
            vec![transaction(2, &external(2), vec![tombstone(T, 2)])],
            "cursor-2",
            2,
        );
        let done = applied(apply(&mut store, &deleted).unwrap());

        let replayed = done.replayed.unwrap();
        assert_eq!(replayed.rejected, [cmd(2)]);
        assert_eq!(state(&mut store, 2), "rejected");
        assert!(
            task(&mut store, T).is_none(),
            "a deleted record is not resurrected"
        );
        let issues = open_issues(&mut store).unwrap();
        assert_eq!(issues.len(), 1);
        assert_eq!(issues[0].issue.local_text, Some(json!({ "title": "Mine" })));
        assert_eq!(confirmed(&mut store)[0].3, 1, "the tombstone is a row");

        // Versions only move forward: neither a replay of the old image nor a
        // regression is accepted, and the refusal leaves the base as it was.
        for version in [1, 2] {
            let stale = page(
                "cursor-2",
                vec![transaction(
                    3,
                    &external(3),
                    vec![task_change(T, "Old", 1, version)],
                )],
                "cursor-3",
                3,
            );
            let error = apply(&mut store, &stale).unwrap_err();
            assert!(matches!(error, ApplyError::Contradiction(_)), "{error:?}");
        }
        assert_eq!(position(&mut store), ("cursor-2".into(), "2".into()));
        assert_eq!(confirmed(&mut store)[0].3, 1);
    }

    #[test]
    fn feed_026_fr_004_responses_of_another_generation_scope_or_request_are_not_applied() {
        let path = scratch("fences");
        let mut store = linked(&path);
        let t1 = transaction(1, &external(1), vec![task_change(T, "One", 1, 1)]);
        let good = page_json("cursor-0", vec![t1], "cursor-1", 1, false);

        let mut other_generation = good.clone();
        other_generation["server_generation"] = json!("generation-2");
        let error = apply(&mut store, &decode_page(&other_generation)).unwrap_err();
        assert_eq!(error, ApplyError::GenerationChanged);
        assert_eq!(error.recovery(), Some(Recovery::Snapshot));

        let mut other_scope = good.clone();
        other_scope["scope_id"] = json!("scope-2");
        assert_eq!(
            apply(&mut store, &decode_page(&other_scope)).unwrap_err(),
            ApplyError::WrongScope
        );

        // A response issued before a reset or an account switch is ignored,
        // even though everything else about it is valid.
        let old = capture_fence(&mut store).unwrap();
        store
            .write(|tx| {
                tx.execute("UPDATE sync_meta SET local_sync_generation = 1", [])?;
                Ok(())
            })
            .unwrap();
        let error = apply_changes(&mut store, &context(), &old, &decode_page(&good)).unwrap_err();
        assert_eq!(error, ApplyError::Stale);
        assert_eq!(error.code(), "STALE_RESPONSE");

        assert!(confirmed(&mut store).is_empty());
        assert_eq!(position(&mut store), ("cursor-0".into(), "0".into()));

        // Without a bootstrap there is nothing to extend: a snapshot comes first.
        let bare = scratch("fences-bare");
        let mut unbound = open(&bare).unwrap();
        assert_eq!(
            apply(&mut unbound, &decode_page(&good)).unwrap_err(),
            ApplyError::NoBase
        );
    }

    #[test]
    fn feed_026_fr_010_a_feed_transaction_naming_a_rejected_command_is_a_contradiction() {
        let path = scratch("contradiction");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        confirmed_task(&mut store, T, "Base");
        edit(
            &mut store,
            &mut ids,
            2,
            T,
            json!({ "title": "Mine" }),
            shown(EntityType::Task, T, "1"),
        );
        set_state(&mut store, 2, "sending", true);
        settle(&mut store, &rejected(&cmd(2), "REVISION_CONFLICT", false)).unwrap();

        let lie = page(
            "cursor-1",
            vec![transaction(2, &cmd(2), vec![task_change(T, "Mine", 2, 2)])],
            "cursor-2",
            2,
        );
        let error = apply(&mut store, &lie).unwrap_err();

        assert!(matches!(error, ApplyError::Contradiction(_)));
        assert_eq!(state(&mut store, 2), "rejected");
        assert_eq!(position(&mut store), ("cursor-1".into(), "1".into()));
    }

    // ------------------------------------------------------------ crash boundaries

    #[test]
    fn feed_026_sc_002_a_crash_before_the_commit_leaves_the_old_base_and_cursor() {
        let path = scratch("crash-before");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        let created = create_task(&mut store, &mut ids, 1, "Mine");
        set_state(&mut store, 1, "sending", true);
        store.close().unwrap();
        let feed = page_json(
            "cursor-0",
            vec![transaction(
                1,
                &cmd(1),
                vec![task_change(&created, "Mine", 1, 1)],
            )],
            "cursor-1",
            1,
            false,
        );

        let mut child = spawn("abort_before_commit", &path, &feed);
        wait_for(&mut child, "installed");
        assert!(!child.wait().unwrap().success(), "the child aborts");

        // Restart: the base, cursor and command are exactly as before.
        let mut store = open(&path).unwrap();
        assert!(confirmed(&mut store).is_empty());
        assert_eq!(position(&mut store), ("cursor-0".into(), "0".into()));
        assert_eq!(state(&mut store, 1), "sending");
        // And the same page applies cleanly afterwards.
        let done = applied(apply(&mut store, &decode_page(&feed)).unwrap());
        assert_eq!(done.completed, [cmd(1)]);
    }

    #[test]
    fn feed_026_sc_002_a_crash_after_the_commit_keeps_the_page_and_redelivery_is_a_duplicate() {
        let path = scratch("crash-after");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        let created = create_task(&mut store, &mut ids, 1, "Mine");
        set_state(&mut store, 1, "sending", true);
        store.close().unwrap();
        let feed = page_json(
            "cursor-0",
            vec![
                transaction(1, &cmd(1), vec![task_change(&created, "Mine", 1, 1)]),
                transaction(2, &external(2), vec![task_change(T, "Other", 1, 2)]),
            ],
            "cursor-2",
            2,
            false,
        );

        let mut child = spawn("abort_after_commit", &path, &feed);
        wait_for(&mut child, "committed");
        assert!(!child.wait().unwrap().success(), "the child aborts");

        let mut store = open(&path).unwrap();
        assert_eq!(confirmed(&mut store).len(), 2);
        assert_eq!(position(&mut store), ("cursor-2".into(), "2".into()));
        assert_eq!(state(&mut store, 1), "completed");
        // The response was lost to the crash: the retried request redelivers it.
        let again = applied(apply(&mut store, &decode_page(&feed)).unwrap());
        assert_eq!((again.transactions, again.skipped), (0, 2));
        assert_eq!(position(&mut store), ("cursor-2".into(), "2".into()));
    }

    #[test]
    fn feed_026_sc_002_a_failure_between_install_and_cursor_rolls_everything_back() {
        let path = scratch("hook");
        let mut store = linked(&path);
        let feed = page(
            "cursor-0",
            vec![transaction(
                1,
                &external(1),
                vec![task_change(T, "One", 1, 1)],
            )],
            "cursor-1",
            1,
        );
        let fence = capture_fence(&mut store).unwrap();

        for failing in [ApplyStage::Installed, ApplyStage::Replayed] {
            let error = apply_changes_with(&mut store, &context(), &fence, &feed, |stage, _| {
                if stage == failing {
                    Err(rusqlite::Error::ExecuteReturnedResults)
                } else {
                    Ok(())
                }
            })
            .unwrap_err();
            assert!(matches!(error, ApplyError::Store(_)));
            assert!(confirmed(&mut store).is_empty());
            assert!(visible(&mut store, "task").is_empty());
            assert_eq!(position(&mut store), ("cursor-0".into(), "0".into()));
        }
    }

    // --------------------------------------------------------------------- oversized

    #[test]
    fn feed_026_fr_004_an_oversized_transaction_is_invisible_until_complete_then_applies_whole() {
        let path = scratch("transfer");
        let mut store = linked(&path);
        let big = oversized(1, &external(1), "cursor-1", &big_changes());
        assert!(big.pages.len() > 3, "the stream spans several chunks");
        // A chunk crosses a record boundary: it is not valid JSON on its own.
        assert!(serde_json::from_slice::<Value>(&big.stream[..331]).is_err());

        let FeedStep::Transfer(transfer) = announced(&mut store, &big) else {
            panic!("the manifest asks for a transfer");
        };
        assert_eq!(transfer.as_str(), "transfer-1");
        assert_eq!(position(&mut store), ("cursor-0".into(), "0".into()));

        // Pages out of order, one twice; nothing is exposed along the way.
        let order: Vec<usize> = (0..big.pages.len()).rev().collect();
        for (done, index) in order.iter().enumerate() {
            let progress = stage(&mut store, &big.pages[*index]).unwrap();
            assert_eq!(progress.received, u64::try_from(done + 1).unwrap());
            assert!(confirmed(&mut store).is_empty());
            assert!(visible(&mut store, "task").is_empty());
            if done == 1 {
                assert_eq!(stage(&mut store, &big.pages[*index]).unwrap(), progress);
                // Not complete yet: nothing to apply, and nothing is lost.
                let error = finish_transfer(&mut store).unwrap_err();
                assert!(matches!(
                    error,
                    ApplyError::Transfer(TransferFault::Incomplete { .. })
                ));
            }
        }

        let done = finish_transfer(&mut store).unwrap();
        assert_eq!((done.transactions, done.watermark), (1, 1));
        assert_eq!(done.cursor, "cursor-1");
        assert_eq!(confirmed(&mut store).len(), 6, "all six records, at once");
        assert_eq!(visible(&mut store, "task").len(), 6);
        assert_eq!(position(&mut store), ("cursor-1".into(), "1".into()));
        assert_eq!(staging(&mut store), [("activated".to_string(), 0)]);

        // The announcement or the apply repeated is a duplicate.
        assert_eq!(finish_transfer(&mut store).unwrap().skipped, 1);
        let again = applied(announced(&mut store, &big));
        assert_eq!(again.skipped, 1);
        assert_eq!(confirmed(&mut store).len(), 6);
    }

    #[test]
    fn feed_026_fr_004_an_oversized_transaction_matches_its_source_command_and_replays() {
        let path = scratch("transfer-source");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        let created = create_task(&mut store, &mut ids, 1, "Mine");
        set_state(&mut store, 1, "sending", true);
        let mut changes = big_changes();
        changes.push(task_change(&created, "Mine", 1, 1));
        let big = oversized(1, &cmd(1), "cursor-1", &changes);

        announced(&mut store, &big);
        for page in &big.pages {
            stage(&mut store, page).unwrap();
        }
        let done = finish_transfer(&mut store).unwrap();

        assert_eq!(done.completed, [cmd(1)]);
        assert_eq!(state(&mut store, 1), "completed");
        assert_eq!(confirmed(&mut store).len(), 7);
    }

    #[test]
    fn feed_026_fr_004_staging_survives_a_restart_and_resumes_where_it_stopped() {
        let path = scratch("transfer-restart");
        let mut store = linked(&path);
        let big = oversized(1, &external(1), "cursor-1", &big_changes());
        announced(&mut store, &big);
        let (first, rest) = big.pages.split_at(2);
        for page in first {
            stage(&mut store, page).unwrap();
        }
        store.close().unwrap();

        let mut store = open(&path).unwrap();
        assert_eq!(staging(&mut store), [("receiving".to_string(), 2)]);
        assert!(
            confirmed(&mut store).is_empty(),
            "staging is never the base"
        );
        // The announcement repeated after the restart resumes the same transfer.
        assert!(matches!(announced(&mut store, &big), FeedStep::Transfer(_)));
        for page in rest {
            stage(&mut store, page).unwrap();
        }
        assert_eq!(finish_transfer(&mut store).unwrap().transactions, 1);
        assert_eq!(confirmed(&mut store).len(), 6);
    }

    #[test]
    fn feed_026_fr_004_a_corrupted_chunk_is_refused_and_not_kept() {
        let path = scratch("transfer-corrupt");
        let mut store = linked(&path);
        let big = oversized(1, &external(1), "cursor-1", &big_changes());
        announced(&mut store, &big);

        let mut flipped = big.pages[1].clone();
        let mut bytes = base64_decode_for_test(flipped["payload_base64"].as_str().unwrap());
        bytes[0] ^= 1;
        flipped["payload_base64"] = json!(base64_encode(&bytes));
        let mut not_base64 = big.pages[1].clone();
        not_base64["payload_base64"] = json!("***not base64***");
        let mut wrong_flag = big.pages[1].clone();
        wrong_flag["has_more"] = json!(false);
        wrong_flag["next_page_token"] = Value::Null;
        let mut out_of_range = big.pages[1].clone();
        out_of_range["page_index"] = json!(big.pages.len() + 4);
        out_of_range["has_more"] = json!(false);
        out_of_range["next_page_token"] = Value::Null;

        for bad in [flipped, not_base64, wrong_flag, out_of_range] {
            let error = stage(&mut store, &bad).unwrap_err();
            assert!(
                matches!(
                    error,
                    ApplyError::Transfer(TransferFault::PageCorrupt { .. })
                ),
                "{error:?}"
            );
            assert_eq!(error.recovery(), Some(Recovery::Refetch));
        }
        assert_eq!(staging(&mut store), [("receiving".to_string(), 0)]);

        // The genuine pages still complete the transfer.
        for page in &big.pages {
            stage(&mut store, page).unwrap();
        }
        assert_eq!(finish_transfer(&mut store).unwrap().transactions, 1);
    }

    #[test]
    fn feed_026_fr_004_a_stream_that_contradicts_its_manifest_is_discarded_and_never_applied() {
        let cases: [(&str, Lie); 4] = [
            ("digest", |m| m["sha256"] = json!("0".repeat(64))),
            ("bytes", |m| {
                m["total_bytes"] = json!(m["total_bytes"].as_u64().unwrap() + 1);
            }),
            ("records", |m| m["record_count"] = json!(99)),
            ("pages", |m| {
                m["page_count"] = json!(m["page_count"].as_u64().unwrap() + 1);
            }),
        ];
        for (name, lie) in cases {
            let path = scratch(&format!("transfer-lie-{name}"));
            let mut store = linked(&path);
            let mut big = oversized(1, &external(1), "cursor-1", &big_changes());
            lie(&mut big.manifest_page["transaction_manifest"]);
            announced(&mut store, &big);
            for page in &big.pages {
                // The last page's `has_more` follows the real page count.
                let _ = stage(&mut store, page);
            }

            let error = finish_transfer(&mut store).unwrap_err();

            if name == "pages" {
                // A page the manifest promises but the server never sent.
                assert!(
                    matches!(
                        error,
                        ApplyError::Transfer(TransferFault::Incomplete { .. })
                    ) || matches!(
                        error,
                        ApplyError::Transfer(TransferFault::PageCorrupt { .. })
                    ) || matches!(error, ApplyError::Transfer(TransferFault::Corrupt)),
                    "{name}: {error:?}"
                );
            } else {
                assert_eq!(
                    error,
                    ApplyError::Transfer(TransferFault::Corrupt),
                    "{name}"
                );
                assert_eq!(error.recovery(), Some(Recovery::Snapshot));
                assert_eq!(
                    staging(&mut store),
                    [("abandoned".to_string(), 0)],
                    "{name}"
                );
            }
            assert!(confirmed(&mut store).is_empty(), "{name}");
            assert!(visible(&mut store, "task").is_empty(), "{name}");
            assert_eq!(
                position(&mut store),
                ("cursor-0".into(), "0".into()),
                "{name}"
            );
        }
    }

    #[test]
    fn feed_026_fr_004_a_missing_chunk_keeps_the_staging_and_applies_nothing() {
        let path = scratch("transfer-missing");
        let mut store = linked(&path);
        let big = oversized(1, &external(1), "cursor-1", &big_changes());
        announced(&mut store, &big);
        for (index, page) in big.pages.iter().enumerate() {
            if index != 2 {
                stage(&mut store, page).unwrap();
            }
        }

        let error = finish_transfer(&mut store).unwrap_err();

        assert_eq!(
            error,
            ApplyError::Transfer(TransferFault::Incomplete { missing: vec![2] })
        );
        assert_eq!(error.code(), "TRANSFER_INCOMPLETE");
        assert!(confirmed(&mut store).is_empty());
        assert_eq!(
            staging(&mut store),
            [(
                "receiving".to_string(),
                i64::try_from(big.pages.len() - 1).unwrap()
            )]
        );
        // The missing chunk arrives and the same transfer completes.
        stage(&mut store, &big.pages[2]).unwrap();
        assert_eq!(finish_transfer(&mut store).unwrap().transactions, 1);
    }

    // A transfer's TTL is the server's: the server reads 09:00 and it expires at
    // 09:30. The device clock is never compared with that instant.

    fn announce_at(store: &mut Store, now: &str, big: &Oversized) {
        let fence = capture_fence(store).unwrap();
        let step = apply_changes(
            store,
            &context_at(now),
            &fence,
            &decode_page(&big.manifest_page),
        );
        assert!(matches!(step.unwrap(), FeedStep::Transfer(_)));
    }

    fn stage_at(
        store: &mut Store,
        now: &str,
        page: &Value,
    ) -> Result<bb_client::TransferProgress, ApplyError> {
        let fence = capture_fence(store).unwrap();
        stage_transfer_page(store, &context_at(now), &fence, &transfer_page(page))
    }

    fn finish_at(store: &mut Store, now: &str) -> Result<Applied, ApplyError> {
        let fence = capture_fence(store).unwrap();
        apply_transfer(
            store,
            &context_at(now),
            &fence,
            &Id::parse("transfer-1").unwrap(),
        )
    }

    #[test]
    fn feed_026_fr_004_a_device_clock_far_ahead_still_applies_a_fresh_transfer() {
        let path = scratch("transfer-clock-ahead");
        let mut store = linked(&path);
        let big = oversized(1, &external(1), "cursor-1", &big_changes());
        let ahead = "2026-10-10T14:00:00Z"; // five hours past the server

        announce_at(&mut store, ahead, &big);
        for page in &big.pages {
            stage_at(&mut store, ahead, page).unwrap();
        }
        let done = finish_at(&mut store, ahead).unwrap();

        assert_eq!(done.transactions, 1);
        assert_eq!(confirmed(&mut store).len(), 6);
        assert_eq!(position(&mut store), ("cursor-1".into(), "1".into()));
    }

    #[test]
    fn feed_026_fr_004_a_device_clock_behind_still_expires_a_stale_transfer() {
        let behind = "2026-10-10T06:00:00Z"; // three hours before the server
        let later = "2026-10-10T06:31:00Z"; // 31 minutes of real time on
        let big = oversized(1, &external(1), "cursor-1", &big_changes());

        // Elapsed local time spends the TTL, though 06:31 is before 09:30.
        let path = scratch("transfer-clock-behind-pages");
        let mut store = linked(&path);
        announce_at(&mut store, behind, &big);
        stage_at(&mut store, behind, &big.pages[0]).unwrap();
        assert_eq!(
            stage_at(&mut store, later, &big.pages[1]).unwrap_err(),
            ApplyError::Transfer(TransferFault::Expired)
        );
        assert_eq!(staging(&mut store), [("abandoned".to_string(), 0)]);

        // ... the same when applying the completed staging.
        let path = scratch("transfer-clock-behind-apply");
        let mut store = linked(&path);
        announce_at(&mut store, behind, &big);
        for page in &big.pages {
            stage_at(&mut store, behind, page).unwrap();
        }
        assert_eq!(
            finish_at(&mut store, later).unwrap_err(),
            ApplyError::Transfer(TransferFault::Expired)
        );
        assert!(confirmed(&mut store).is_empty());

        // The server's own reading on a later page spends it with a still clock.
        let path = scratch("transfer-clock-behind-server");
        let mut store = linked(&path);
        announce_at(&mut store, behind, &big);
        let mut late_page = big.pages[0].clone();
        late_page["server_now"] = json!("2026-10-10T09:31:00Z");
        assert_eq!(
            stage_at(&mut store, behind, &late_page).unwrap_err(),
            ApplyError::Transfer(TransferFault::Expired)
        );
    }

    #[test]
    fn feed_026_fr_004_a_backwards_clock_does_not_extend_a_transfers_lifetime() {
        let path = scratch("transfer-clock-back");
        let mut store = linked(&path);
        let big = oversized(1, &external(1), "cursor-1", &big_changes());
        announce_at(&mut store, NOW, &big);
        stage_at(&mut store, "2026-10-10T09:20:00Z", &big.pages[0]).unwrap();

        // Restart with the clock set back an hour: 20 minutes are still spent.
        store.close().unwrap();
        let mut store = open(&path).unwrap();
        stage_at(&mut store, "2026-10-10T08:00:00Z", &big.pages[1]).unwrap();
        assert_eq!(
            stage_at(&mut store, "2026-10-10T08:11:00Z", &big.pages[2]).unwrap_err(),
            ApplyError::Transfer(TransferFault::Expired),
            "31 minutes in all, not 11"
        );
        assert_eq!(staging(&mut store), [("abandoned".to_string(), 0)]);
    }

    #[test]
    fn feed_026_fr_004_an_expired_transfer_is_discarded_and_live_work_is_untouched() {
        let path = scratch("transfer-expired");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Mine");
        let big = oversized(1, &external(1), "cursor-1", &big_changes());
        announced(&mut store, &big);
        stage(&mut store, &big.pages[0]).unwrap();

        // Half an hour later the transfer is gone.
        let fence = capture_fence(&mut store).unwrap();
        let late = context_at("2026-10-10T09:45:00Z");
        let error = stage_transfer_page(&mut store, &late, &fence, &transfer_page(&big.pages[1]))
            .unwrap_err();
        assert_eq!(error, ApplyError::Transfer(TransferFault::Expired));
        assert_eq!(error.code(), "RESET_REQUIRED");
        assert_eq!(staging(&mut store), [("abandoned".to_string(), 0)]);

        // Nothing applies, the pending work is intact, and the dropped transfer
        // is not an error to ask again about.
        let error = finish_transfer(&mut store).unwrap_err();
        assert_eq!(error, ApplyError::Transfer(TransferFault::Unknown));
        assert!(confirmed(&mut store).is_empty());
        assert_eq!(state(&mut store, 1), "queued");
        assert_eq!(visible(&mut store, "task").len(), 1);

        // A manifest the server itself dates after its expiry is not even staged.
        let mut late_announce = big.manifest_page.clone();
        late_announce["transaction_manifest"]["transfer_id"] = json!("transfer-2");
        late_announce["server_now"] = json!("2026-10-10T09:45:00Z");
        let expired = decode_page(&late_announce);
        let error = apply_changes(&mut store, &late, &fence, &expired).unwrap_err();
        assert_eq!(error, ApplyError::Transfer(TransferFault::Expired));
        assert_eq!(staging(&mut store), [("abandoned".to_string(), 0)]);
    }

    #[test]
    fn feed_026_fr_004_a_reannounced_transfer_replaces_the_stale_one_and_abandon_clears_it() {
        let path = scratch("transfer-reissue");
        let mut store = linked(&path);
        let big = oversized(1, &external(1), "cursor-1", &big_changes());
        announced(&mut store, &big);
        stage(&mut store, &big.pages[0]).unwrap();

        // The server offers the same transaction under a new transfer.
        let mut second = oversized(1, &external(1), "cursor-1", &big_changes());
        second.manifest_page["transaction_manifest"]["transfer_id"] = json!("transfer-9");
        let FeedStep::Transfer(next) = announced(&mut store, &second) else {
            panic!("a new transfer is asked for");
        };
        assert_eq!(next.as_str(), "transfer-9");
        assert_eq!(
            staging(&mut store),
            [("abandoned".to_string(), 0), ("receiving".to_string(), 0)]
        );

        // A manifest that changes under a known transfer ID is refused.
        let mut changed = oversized(1, &external(1), "cursor-1", &big_changes());
        changed.manifest_page["transaction_manifest"]["transfer_id"] = json!("transfer-9");
        changed.manifest_page["transaction_manifest"]["after_cursor"] = json!("cursor-other");
        let error = apply(&mut store, &decode_page(&changed.manifest_page)).unwrap_err();
        assert_eq!(error, ApplyError::Transfer(TransferFault::Conflict));

        abandon_transfer(&mut store, &next).unwrap();
        assert_eq!(
            staging(&mut store),
            [("abandoned".to_string(), 0), ("abandoned".to_string(), 0)]
        );
        assert!(confirmed(&mut store).is_empty());
    }

    #[test]
    fn feed_026_sc_002_a_crash_inside_the_transfer_apply_leaves_staging_and_base_intact() {
        let path = scratch("transfer-crash");
        let mut store = linked(&path);
        let big = oversized(1, &external(1), "cursor-1", &big_changes());
        announced(&mut store, &big);
        for page in &big.pages {
            stage(&mut store, page).unwrap();
        }
        let fence = capture_fence(&mut store).unwrap();

        let error = apply_transfer_with(
            &mut store,
            &context(),
            &fence,
            &Id::parse("transfer-1").unwrap(),
            |stage, _| match stage {
                ApplyStage::Replayed => Err(rusqlite::Error::ExecuteReturnedResults),
                ApplyStage::Installed => Ok(()),
            },
        )
        .unwrap_err();

        assert!(matches!(error, ApplyError::Store(_)));
        assert!(confirmed(&mut store).is_empty());
        assert_eq!(position(&mut store), ("cursor-0".into(), "0".into()));
        assert_eq!(
            staging(&mut store),
            [(
                "complete".to_string(),
                i64::try_from(big.pages.len()).unwrap()
            )]
        );
        // Nothing was lost: the same staged pages apply on the next try.
        assert_eq!(finish_transfer(&mut store).unwrap().transactions, 1);
    }

    // ---------------------------------------------------------------------- receipts

    #[test]
    fn receipt_026_fr_005_an_ack_keeps_intent_and_projection_and_never_writes_the_base() {
        let path = scratch("ack-before");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        let created = create_task(&mut store, &mut ids, 1, "Mine");
        set_state(&mut store, 1, "sending", true);
        let projection = visible(&mut store, "task");
        let envelope: Vec<u8> = store
            .read(|tx| tx.query_row("SELECT envelope FROM outbox", [], |row| row.get(0)))
            .unwrap();

        let settled = settle(&mut store, &accepted(&cmd(1), 1)).unwrap();

        assert_eq!(settled.settlement, Settlement::AwaitingFeed);
        assert_eq!(state(&mut store, 1), "accepted_awaiting_feed");
        assert!(
            confirmed(&mut store).is_empty(),
            "an ACK writes no after-image"
        );
        assert_eq!(
            position(&mut store),
            ("cursor-0".into(), "0".into()),
            "and no cursor"
        );
        assert_eq!(
            visible(&mut store, "task"),
            projection,
            "the projection stays"
        );
        let kept: Vec<u8> = store
            .read(|tx| tx.query_row("SELECT envelope FROM outbox", [], |row| row.get(0)))
            .unwrap();
        assert_eq!(kept, envelope, "the intent is retained");
        assert_eq!(count(&mut store, "command_receipts"), 1);

        // The same ACK again changes nothing, then the feed proves inclusion.
        assert_eq!(
            settle(&mut store, &accepted(&cmd(1), 1))
                .unwrap()
                .settlement,
            Settlement::AwaitingFeed
        );
        assert_eq!(count(&mut store, "command_receipts"), 1);
        let done = applied(
            apply(
                &mut store,
                &page(
                    "cursor-0",
                    vec![transaction(
                        1,
                        &cmd(1),
                        vec![task_change(&created, "Mine", 1, 1)],
                    )],
                    "cursor-1",
                    1,
                ),
            )
            .unwrap(),
        );
        assert_eq!(done.completed, [cmd(1)]);
        assert_eq!(state(&mut store, 1), "completed");
        assert_eq!(
            visible(&mut store, "task"),
            projection,
            "no flicker when it lands"
        );
        assert_eq!(confirmed(&mut store).len(), 1);
    }

    #[test]
    fn receipt_026_fr_005_an_ack_beyond_the_base_waits_for_the_missing_intermediates() {
        let path = scratch("ack-beyond");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        let created = create_task(&mut store, &mut ids, 1, "Mine");
        set_state(&mut store, 1, "sending", true);

        // The server committed it at sequence 3; sequences 1 and 2 are not here.
        let settled = settle(&mut store, &accepted(&cmd(1), 3)).unwrap();
        assert_eq!(settled.settlement, Settlement::AwaitingFeed);

        // A page carrying only sequence 3 cannot skip the hole: the ACK did
        // not move the cursor, and neither does this.
        let third = transaction(3, &cmd(1), vec![task_change(&created, "Mine", 1, 3)]);
        let error = apply(
            &mut store,
            &page("cursor-2", vec![third.clone()], "cursor-3", 3),
        )
        .unwrap_err();
        assert_eq!(error.recovery(), Some(Recovery::Refetch));
        assert_eq!(state(&mut store, 1), "accepted_awaiting_feed");
        assert!(confirmed(&mut store).is_empty());
        assert_eq!(position(&mut store), ("cursor-0".into(), "0".into()));

        // In order, the multi-record history lands and only then completes it.
        let first = page_more(
            "cursor-0",
            vec![
                transaction(1, &external(1), vec![task_change(T, "Other", 1, 1)]),
                transaction(2, &external(2), vec![task_change(T, "Other 2", 2, 2)]),
            ],
            "cursor-2",
            3,
        );
        applied(apply(&mut store, &first).unwrap());
        assert_eq!(state(&mut store, 1), "accepted_awaiting_feed");
        assert_eq!(position(&mut store), ("cursor-2".into(), "2".into()));
        let done =
            applied(apply(&mut store, &page("cursor-2", vec![third], "cursor-3", 3)).unwrap());
        assert_eq!(done.completed, [cmd(1)]);
        assert_eq!(state(&mut store, 1), "completed");
    }

    #[test]
    fn receipt_026_fr_005_an_ack_after_the_feed_is_recorded_without_changing_anything() {
        let path = scratch("ack-after");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        let created = create_task(&mut store, &mut ids, 1, "Mine");
        set_state(&mut store, 1, "unknown", true);
        applied(
            apply(
                &mut store,
                &page(
                    "cursor-0",
                    vec![transaction(
                        1,
                        &cmd(1),
                        vec![task_change(&created, "Mine", 1, 1)],
                    )],
                    "cursor-1",
                    1,
                ),
            )
            .unwrap(),
        );
        // The feed alone proved it, even though the response was lost.
        assert_eq!(state(&mut store, 1), "completed");

        let settled = settle(&mut store, &accepted(&cmd(1), 1)).unwrap();

        // The command stays done; the receipt's result replaces the prediction.
        assert_eq!(settled.settlement, Settlement::Completed);
        assert_eq!(state(&mut store, 1), "completed");
        assert_eq!(count(&mut store, "command_receipts"), 1);
        assert_eq!(position(&mut store), ("cursor-1".into(), "1".into()));
        assert_eq!(
            settle(&mut store, &accepted(&cmd(1), 1))
                .unwrap()
                .settlement,
            Settlement::Unchanged
        );
    }

    #[test]
    fn receipt_026_fr_006_a_no_op_receipt_completes_from_the_receipt_without_a_feed_transaction() {
        let path = scratch("noop");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        confirmed_task(&mut store, T, "Base");
        edit(
            &mut store,
            &mut ids,
            2,
            T,
            json!({ "title": "Mine" }),
            shown(EntityType::Task, T, "1"),
        );
        set_state(&mut store, 2, "sending", true);

        let settled = settle(&mut store, &no_op(&cmd(2))).unwrap();

        assert_eq!(settled.settlement, Settlement::Completed);
        assert_eq!(state(&mut store, 2), "completed");
        // Nothing waits for a feed transaction that will never come, and the
        // visible state is the confirmed base once more.
        assert_eq!(task(&mut store, T).unwrap()["title"], "Base");
        assert_eq!(position(&mut store), ("cursor-1".into(), "1".into()));
        assert_eq!(
            settle(&mut store, &no_op(&cmd(2))).unwrap().settlement,
            Settlement::Unchanged
        );
    }

    #[test]
    fn receipt_026_fr_007_a_rejected_receipt_keeps_the_intent_and_independent_work_progresses() {
        let path = scratch("rejected");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        confirmed_task(&mut store, T, "Base");
        edit(
            &mut store,
            &mut ids,
            2,
            T,
            json!({ "title": "Mine" }),
            shown(EntityType::Task, T, "1"),
        );
        let r2 = revision(&mut store, T);
        edit(
            &mut store,
            &mut ids,
            3,
            T,
            json!({ "details": "Held" }),
            shown(EntityType::Task, T, &r2),
        );
        create_task(&mut store, &mut ids, 4, "Independent");
        set_state(&mut store, 2, "sending", true);

        let settled = settle(&mut store, &rejected(&cmd(2), "REVISION_CONFLICT", false)).unwrap();

        assert_eq!(settled.settlement, Settlement::Rejected);
        assert_eq!(state(&mut store, 2), "rejected");
        assert_eq!(state(&mut store, 3), "blocked_dependency");
        assert_eq!(state(&mut store, 4), "queued", "independent work continues");
        let issues = open_issues(&mut store).unwrap();
        assert_eq!(issues.len(), 2);
        assert_eq!(issues[0].issue.reason.code(), "REVISION_CONFLICT");
        assert_eq!(issues[0].issue.local_text, Some(json!({ "title": "Mine" })));
        assert_eq!(task(&mut store, T).unwrap()["title"], "Base");
        assert!(
            visible(&mut store, "task")
                .iter()
                .any(|t| t["title"] == "Independent")
        );
        assert_eq!(confirmed(&mut store).len(), 1, "a rejection writes no base");

        assert_eq!(
            settle(&mut store, &rejected(&cmd(2), "REVISION_CONFLICT", false))
                .unwrap()
                .settlement,
            Settlement::Unchanged
        );
        assert_eq!(open_issues(&mut store).unwrap().len(), 2);
    }

    #[test]
    fn receipt_026_fr_010_a_receipt_that_cannot_be_true_is_refused_and_saves_nothing() {
        let path = scratch("refused");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Mine");
        create_task(&mut store, &mut ids, 2, "Other");
        set_state(&mut store, 1, "sending", true);
        let before = states(&mut store);

        // Never sent: no receipt can be for it.
        assert_eq!(
            settle(&mut store, &accepted(&cmd(2), 1)).unwrap_err(),
            ApplyError::NeverSent
        );
        // Not ours at all.
        assert_eq!(
            settle(&mut store, &accepted(&cmd(77), 1)).unwrap_err(),
            ApplyError::UnknownCommand
        );
        // A "terminal" receipt that asks to be retried is not terminal.
        assert!(matches!(
            settle(&mut store, &rejected(&cmd(1), "DEPENDENCY_PENDING", true)).unwrap_err(),
            ApplyError::Malformed(_)
        ));
        // Another server generation proves nothing here.
        let mut elsewhere = serde_json::to_value(accepted(&cmd(1), 1)).unwrap();
        elsewhere["server_generation"] = json!("generation-2");
        let elsewhere: Receipt = decode(&elsewhere.to_string()).unwrap();
        assert_eq!(
            settle(&mut store, &elsewhere).unwrap_err(),
            ApplyError::GenerationChanged
        );
        // A response issued before a reset is ignored.
        let old = capture_fence(&mut store).unwrap();
        store
            .write(|tx| {
                tx.execute("UPDATE sync_meta SET session_generation = 3", [])?;
                Ok(())
            })
            .unwrap();
        assert_eq!(
            apply_receipt(&mut store, &context(), &old, &accepted(&cmd(1), 1)).unwrap_err(),
            ApplyError::Stale
        );
        store
            .write(|tx| {
                tx.execute("UPDATE sync_meta SET session_generation = 0", [])?;
                Ok(())
            })
            .unwrap();
        assert_eq!(states(&mut store), before);
        assert_eq!(count(&mut store, "command_receipts"), 0);

        // Accepted, then "rejected": the server cannot have said both.
        settle(&mut store, &accepted(&cmd(1), 5)).unwrap();
        let error = settle(&mut store, &rejected(&cmd(1), "REVISION_CONFLICT", false)).unwrap_err();
        assert!(matches!(error, ApplyError::Contradiction(_)), "{error:?}");
        assert_eq!(state(&mut store, 1), "accepted_awaiting_feed");
        // Another outcome for the same sequence: also a contradiction.
        let error = settle(&mut store, &no_op(&cmd(1))).unwrap_err();
        assert!(matches!(error, ApplyError::Contradiction(_)), "{error:?}");
        assert_eq!(open_issues(&mut store).unwrap().len(), 0);
        assert_eq!(count(&mut store, "command_receipts"), 1);
    }

    const P_ALIAS: &str = "project_00000000-0000-4000-8000-0000000000bb";
    const P_REAL: &str = "project_00000000-0000-4000-8000-0000000000cc";

    /// A queued Smart Add that proposes a new project `P_ALIAS`, and a task made
    /// after it that refers to that project by the alias. Returns the first
    /// command's task.
    fn smart_add_with_dependent(store: &mut Store, ids: &mut SeqIds) -> String {
        let creating = request(
            cmd(1),
            CommandType::TaskSmartAdd,
            None,
            json!({ "title": "Buy stamps", "project": { "name": "Errands", "proposed_id": P_ALIAS }}),
            Vec::new(),
        );
        let added = execute(store, ids, &creating)
            .unwrap()
            .entity_id
            .as_str()
            .to_string();
        let following = request(
            cmd(2),
            CommandType::TaskCreate,
            None,
            json!({ "title": "Post parcel", "project_id": {
                "after_command": cmd(1).as_str(),
                "alias_id": P_ALIAS,
                "entity_type": "project",
            }}),
            Vec::new(),
        );
        execute(store, ids, &following).unwrap();
        set_state(store, 1, "sending", true);
        added
    }

    /// What the server committed for command 1: it found the project "Errands"
    /// another device had made (`P_REAL`) and put the task on it.
    fn server_smart_add(added: &str) -> Vec<Value> {
        let mut task = task_change(added, "Buy stamps", 1, 1);
        task["value"]["project_id"] = json!(P_REAL);
        vec![project_change(P_REAL, "Errands", 1), task]
    }

    fn server_binding(added: &str, seq: u64) -> Receipt {
        accepted_with(
            &cmd(1),
            seq,
            json!([{ "entity_type": "task", "record_key": [added],
                     "record_version": "1", "edit_revision": "1" }]),
            json!([{ "entity_type": "project", "alias_id": P_ALIAS, "entity_id": P_REAL }]),
        )
    }

    fn parcel(store: &mut Store) -> Option<Value> {
        visible(store, "task")
            .into_iter()
            .find(|task| task["title"] == "Post parcel")
    }

    fn proven_alias(store: &mut Store) -> Vec<(String, String)> {
        store
            .read(|tx| {
                let mut statement = tx.prepare(
                    "SELECT old_local_id, server_id FROM identity_aliases ORDER BY old_local_id",
                )?;
                let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
                rows.collect()
            })
            .unwrap()
    }

    #[test]
    fn receipt_026_fr_005_ack_then_feed_the_dependent_resolves_the_server_binding() {
        let path = scratch("binding");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        let added = smart_add_with_dependent(&mut store, &mut ids);
        // Before anything is known the dependent follows the local prediction.
        assert_eq!(parcel(&mut store).unwrap()["project_id"], P_ALIAS);

        // The ACK says the alias is `P_REAL`, an entity this device has not
        // received yet. The dependent can neither follow the prediction nor be
        // judged against a base that lacks the entity: it waits, it is not
        // rejected or held.
        let settled = settle(&mut store, &server_binding(&added, 1)).unwrap();
        assert_eq!(settled.settlement, Settlement::AwaitingFeed);
        assert_eq!(state(&mut store, 1), "accepted_awaiting_feed");
        assert_eq!(state(&mut store, 2), "queued");
        assert!(open_issues(&mut store).unwrap().is_empty());
        assert_eq!(
            proven_alias(&mut store),
            [(P_ALIAS.to_string(), P_REAL.to_string())]
        );
        assert!(confirmed(&mut store).is_empty(), "an ACK writes no base");

        // The feed lands the source transaction.
        let done = applied(
            apply(
                &mut store,
                &page(
                    "cursor-0",
                    vec![transaction(1, &cmd(1), server_smart_add(&added))],
                    "cursor-1",
                    1,
                ),
            )
            .unwrap(),
        );
        assert_eq!(done.completed, [cmd(1)]);
        assert_eq!(state(&mut store, 1), "completed");
        assert_eq!(state(&mut store, 2), "queued", "not rejected, not held");
        assert!(open_issues(&mut store).unwrap().is_empty());
        // Replayed against the server's entity, never the proposed ID.
        assert_eq!(parcel(&mut store).unwrap()["project_id"], P_REAL);
        assert!(
            visible(&mut store, "project")
                .iter()
                .all(|project| project["id"] != P_ALIAS),
            "the proposed project does not survive beside the real one"
        );

        // The binding is permanent: another ACK for it changes nothing, and a
        // different one is refused.
        assert_eq!(
            settle(&mut store, &server_binding(&added, 1))
                .unwrap()
                .settlement,
            Settlement::Unchanged
        );
        let mut elsewhere = server_binding(&added, 1);
        elsewhere.id_bindings[0].entity_id = Id::parse("project_other").unwrap();
        assert!(matches!(
            settle(&mut store, &elsewhere).unwrap_err(),
            ApplyError::Contradiction(_)
        ));
        assert_eq!(parcel(&mut store).unwrap()["project_id"], P_REAL);
    }

    #[test]
    fn receipt_026_fr_005_feed_first_the_late_receipt_supplies_the_binding_without_a_rejection() {
        let path = scratch("binding-late");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        let added = smart_add_with_dependent(&mut store, &mut ids);

        // The feed proves the Smart Add before any receipt arrived.
        applied(
            apply(
                &mut store,
                &page(
                    "cursor-0",
                    vec![transaction(1, &cmd(1), server_smart_add(&added))],
                    "cursor-1",
                    1,
                ),
            )
            .unwrap(),
        );
        assert_eq!(state(&mut store, 1), "completed");
        // Which entity the alias became is unknown, so the dependent is not
        // judged against the local guess: it waits, and is not rejected.
        assert_eq!(state(&mut store, 2), "queued");
        assert!(open_issues(&mut store).unwrap().is_empty());

        // The lookup (or the original ACK) supplies the server's binding.
        settle(&mut store, &server_binding(&added, 1)).unwrap();

        assert_eq!(state(&mut store, 2), "queued");
        assert!(open_issues(&mut store).unwrap().is_empty());
        assert_eq!(parcel(&mut store).unwrap()["project_id"], P_REAL);
    }

    #[test]
    fn receipt_026_fr_010_a_lookup_observation_from_an_obsolete_response_is_refused() {
        let path = scratch("lookup-fence");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Mine");
        set_state(&mut store, 1, "unknown", true);
        let observation = |status: &str, patch: fn(&mut Value)| -> CommandLookup {
            let mut body = with_common(json!({ "status": status, "command_id": id(1) }));
            patch(&mut body);
            decode(&body.to_string()).unwrap()
        };
        let fence = capture_fence(&mut store).unwrap();

        for status in ["pending", "not_found"] {
            let other_generation = observation(status, |body| {
                body["server_generation"] = json!("generation-2");
            });
            assert_eq!(
                apply_lookup(&mut store, &context(), &fence, &other_generation).unwrap_err(),
                ApplyError::GenerationChanged
            );
            let other_scope = observation(status, |body| body["scope_id"] = json!("scope-2"));
            assert_eq!(
                apply_lookup(&mut store, &context(), &fence, &other_scope).unwrap_err(),
                ApplyError::WrongScope
            );
        }

        // Issued before a reset: ignored, whatever it says.
        store
            .write(|tx| {
                tx.execute("UPDATE sync_meta SET local_sync_generation = 4", [])?;
                Ok(())
            })
            .unwrap();
        let current = observation("pending", |_| {});
        assert_eq!(
            apply_lookup(&mut store, &context(), &fence, &current).unwrap_err(),
            ApplyError::Stale
        );
        // The same observation under the current fences is fine.
        let fence = capture_fence(&mut store).unwrap();
        assert!(matches!(
            apply_lookup(&mut store, &context(), &fence, &current).unwrap(),
            Looked::Pending(_)
        ));
        assert_eq!(state(&mut store, 1), "unknown");
    }

    #[test]
    fn receipt_026_fr_010_a_lookup_synthesised_for_a_foreign_scope_cannot_settle_a_command() {
        let path = scratch("lookup-foreign");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Mine");
        set_state(&mut store, 1, "unknown", true);
        let fence = capture_fence(&mut store).unwrap();
        // The lookup envelope is for another scope, the inner receipt is not.
        let body = with_common(json!({
            "status": "terminal",
            "receipt": serde_json::to_value(accepted(&cmd(1), 1)).unwrap(),
        }));
        let mut foreign = body.clone();
        foreign["scope_id"] = json!("scope-2");
        let foreign: CommandLookup = decode(&foreign.to_string()).unwrap();

        assert_eq!(
            apply_lookup(&mut store, &context(), &fence, &foreign).unwrap_err(),
            ApplyError::WrongScope
        );
        assert_eq!(state(&mut store, 1), "unknown");
        assert_eq!(count(&mut store, "command_receipts"), 0);
    }

    #[test]
    fn feed_026_fr_004_a_record_that_fails_late_in_an_oversized_stream_leaves_nothing_visible() {
        let path = scratch("transfer-late-failure");
        let mut store = linked(&path);
        let mut changes = big_changes();
        // The last record is well formed JSON but its key does not match its image.
        let mut last = changes.pop().unwrap();
        last["record_key"] = json!(["task_somebody-else"]);
        changes.push(last);
        let big = oversized(1, &external(1), "cursor-1", &changes);
        announced(&mut store, &big);
        for page in &big.pages {
            stage(&mut store, page).unwrap();
        }

        let error = finish_transfer(&mut store).unwrap_err();

        assert!(matches!(error, ApplyError::Malformed(_)), "{error:?}");
        assert!(
            confirmed(&mut store).is_empty(),
            "five good records are not kept"
        );
        assert!(visible(&mut store, "task").is_empty());
        assert_eq!(position(&mut store), ("cursor-0".into(), "0".into()));
        // The staged bytes are intact; nothing was lost by the refusal.
        assert_eq!(staging(&mut store).len(), 1);
    }

    #[test]
    fn receipt_026_fr_010_a_lookup_settles_the_same_way_and_observations_change_nothing() {
        let path = scratch("lookup");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Mine");
        set_state(&mut store, 1, "unknown", true);
        let fence = capture_fence(&mut store).unwrap();
        let lookup =
            |status: Value| -> CommandLookup { decode(&with_common(status).to_string()).unwrap() };

        for status in ["pending", "not_found"] {
            let looked = apply_lookup(
                &mut store,
                &context(),
                &fence,
                &lookup(json!({ "status": status, "command_id": id(1) })),
            )
            .unwrap();
            assert!(matches!(looked, Looked::Pending(_) | Looked::NotFound(_)));
            assert_eq!(state(&mut store, 1), "unknown", "no new ID, no new state");
        }

        let terminal = lookup(json!({
            "status": "terminal",
            "receipt": serde_json::to_value(accepted(&cmd(1), 1)).unwrap(),
        }));
        let Looked::Settled(settled) =
            apply_lookup(&mut store, &context(), &fence, &terminal).unwrap()
        else {
            panic!("a terminal lookup settles");
        };
        assert_eq!(settled.settlement, Settlement::AwaitingFeed);
        assert_eq!(state(&mut store, 1), "accepted_awaiting_feed");
    }
}

fn base64_decode_for_test(text: &str) -> Vec<u8> {
    let value = |c: u8| match c {
        b'A'..=b'Z' => c - b'A',
        b'a'..=b'z' => c - b'a' + 26,
        b'0'..=b'9' => c - b'0' + 52,
        b'+' => 62,
        b'/' => 63,
        _ => 0,
    };
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    for quad in bytes.chunks(4) {
        let pad = quad.iter().filter(|c| **c == b'=').count();
        let bits = quad
            .iter()
            .fold(0_u32, |bits, c| (bits << 6) | u32::from(value(*c)));
        out.extend_from_slice(&bits.to_be_bytes()[1..4 - pad]);
    }
    out
}

// Native local origins use the same durable transaction and replay paths as
// domain records; neither an ACK nor a rejected prediction becomes confirmed.
fn local_origin(store: &mut Store, task_id: &str) -> Option<bb_domain::types::OpenList> {
    let mut read_set = bb_domain::types::ReadSet::default();
    for value in visible(store, "task") {
        let task: bb_domain::types::Task = serde_json::from_value(value).unwrap();
        read_set.tasks.insert(task.id.clone(), task);
    }
    bb_client::local_task_origins(store, &read_set)
        .unwrap()
        .get(&bb_domain::types::TaskId::parse(task_id).unwrap())
        .copied()
}

fn transition_local(store: &mut Store, n: u64, task_id: &str, revision: &str, payload: Value) {
    execute(
        store,
        &mut SeqIds(0),
        &request(
            cmd(n),
            CommandType::TaskTransition,
            Some(task_id),
            payload,
            vec![shown(EntityType::Task, task_id, revision)],
        ),
    )
    .unwrap();
}

fn state_change(task_id: &str, state: &str, revision: u64, version: u64) -> Value {
    let mut change = task_change(task_id, "Origin", revision, version);
    change["value"]["state"] = json!(state);
    change["value"]["completed_at"] = if state == "completed" {
        json!(NOW)
    } else {
        Value::Null
    };
    change["value"]["cancelled_at"] = if state == "cancelled" {
        json!(NOW)
    } else {
        Value::Null
    };
    change
}

#[test]
fn local_origin_rejected_completion_and_reopen_rebuild_from_confirmed_facts() {
    use bb_domain::types::OpenList;
    let path = scratch("local-origin-rejections");
    let mut store = linked(&path);
    let task = "task-origin";
    apply(
        &mut store,
        &page(
            "cursor-0",
            vec![transaction(
                1,
                &external(1),
                vec![state_change(task, "inbox", 1, 1)],
            )],
            "cursor-1",
            1,
        ),
    )
    .unwrap();
    transition_local(&mut store, 1, task, "1", json!({"action":"complete"}));
    assert_eq!(local_origin(&mut store, task), Some(OpenList::Inbox));
    bb_client::record_rejection(
        &mut store,
        &context(),
        &cmd(1),
        &bb_client::IssueReason::RevisionConflict,
    )
    .unwrap();
    assert_eq!(local_origin(&mut store, task), None);
    // A genuine feed transition establishes the confirmed origin.
    apply(
        &mut store,
        &page(
            "cursor-1",
            vec![transaction(
                2,
                &external(2),
                vec![state_change(task, "completed", 2, 2)],
            )],
            "cursor-2",
            2,
        ),
    )
    .unwrap();
    transition_local(
        &mut store,
        2,
        task,
        "2",
        json!({"action":"reopen","to_state":"someday"}),
    );
    assert_eq!(local_origin(&mut store, task), None);
    bb_client::record_rejection(
        &mut store,
        &context(),
        &cmd(2),
        &bb_client::IssueReason::RevisionConflict,
    )
    .unwrap();
    assert_eq!(local_origin(&mut store, task), Some(OpenList::Inbox));
    drop(store);
    assert_eq!(
        local_origin(&mut open(&path).unwrap(), task),
        Some(OpenList::Inbox)
    );
}

#[test]
fn local_origin_ack_before_feed_and_contiguous_remote_recompletion() {
    use bb_domain::types::OpenList;
    let path = scratch("local-origin-ack");
    let mut store = linked(&path);
    let task = "task-origin";
    apply(
        &mut store,
        &page(
            "cursor-0",
            vec![transaction(
                1,
                &external(1),
                vec![state_change(task, "inbox", 1, 1)],
            )],
            "cursor-1",
            1,
        ),
    )
    .unwrap();
    transition_local(&mut store, 1, task, "1", json!({"action":"complete"}));
    set_state(&mut store, 1, "sending", true);
    let fence = capture_fence(&mut store).unwrap();
    apply_receipt(&mut store, &context(), &fence, &accepted(&cmd(1), 2)).unwrap();
    let confirmed_origin: Value = store
        .read(|tx| {
            let body: Vec<u8> = tx.query_row(
                "SELECT fields FROM drafts WHERE editor_kind = 'runtime_task_local'",
                [],
                |r| r.get(0),
            )?;
            Ok(serde_json::from_slice::<Value>(&body).unwrap()["confirmed"].clone())
        })
        .unwrap();
    assert_eq!(
        confirmed_origin,
        Value::Null,
        "ACK cannot promote the prediction"
    );
    apply(
        &mut store,
        &page(
            "cursor-1",
            vec![
                transaction(2, &cmd(1), vec![state_change(task, "completed", 2, 2)]),
                transaction(3, &external(3), vec![state_change(task, "someday", 3, 3)]),
                transaction(4, &external(4), vec![state_change(task, "completed", 4, 4)]),
            ],
            "cursor-4",
            4,
        ),
    )
    .unwrap();
    assert_eq!(local_origin(&mut store, task), Some(OpenList::Someday));
    apply(
        &mut store,
        &page(
            "cursor-4",
            vec![transaction(
                5,
                &external(5),
                vec![state_change(task, "cancelled", 5, 5)],
            )],
            "cursor-5",
            5,
        ),
    )
    .unwrap();
    assert_eq!(
        local_origin(&mut store, task),
        None,
        "terminal kind changes clear origin"
    );
}
