//! Snapshot staging and activation tests: a snapshot is invisible until it is
//! complete and verified, one activation replaces the confirmed base while
//! keeping everything saved during the download, a command is proven part of the
//! base only by a receipt of the snapshot's own server generation, and every
//! failure (expiry, a corrupt page, a reset, a crash) leaves the old database
//! readable and the queue whole.
//!
//! Everything goes through the public API on a real SQLite file, across store
//! reopenings, a second connection standing in for the widget, and real process
//! aborts. The server side is played by building the wire JSON the contract
//! describes and decoding it with the `bb-protocol` codecs.

use bb_client::{
    Activated, ApplyError, ApplyStage, DecisionDraft, ExecuteContext, ExecuteRequest, Fence,
    IdSource, OpenOptions, Recovery, SnapshotProgress, Store, StoreError, TransferFault,
    abandon_snapshot, activate_snapshot, activate_snapshot_with, apply_changes, apply_receipt,
    begin_snapshot, capture_fence, execute, load_draft, open_issues, save_draft, sha256_hex,
    stage_snapshot_page,
};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{Precondition, RevisionPrecondition};
use bb_protocol::feed::{ChangesPage, SnapshotManifest, SnapshotPage};
use bb_protocol::receipt::Receipt;
use bb_protocol::wire::{CommandId, Counter, Id, Instant, decode};
use rusqlite::params;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::OnceLock;
use std::time::Duration;

const WORKSPACE: &str = "workspace-local";
const SCOPE: &str = "scope-1";
const GENERATION: &str = "generation-1";
const RESTORED: &str = "generation-2";
const NOW: &str = "2026-10-10T09:00:00Z";
const EXPIRES: &str = "2026-10-10T09:30:00Z";
const AFTER_EXPIRY: &str = "2026-10-10T09:31:00Z";
const ROLE: &str = "BB_SNAPSHOT_CHILD";

/// A way a manifest can disagree with the stream it announces.
type Lie = fn(&mut Value);

// ----------------------------------------------------------------------- harness

fn scratch(name: &str) -> PathBuf {
    let directory = std::env::temp_dir().join(format!("bb-snapshot-{name}-{}", std::process::id()));
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
    store
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

fn shown(id: &str, revision: &str) -> Precondition {
    Precondition::Revision(RevisionPrecondition {
        entity_type: EntityType::Task,
        entity_id: Id::parse(id).unwrap(),
        edit_revision: Counter::parse(revision).unwrap(),
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

fn edit(store: &mut Store, ids: &mut SeqIds, n: u64, task_id: &str, title: &str, revision: &str) {
    let update = request(
        cmd(n),
        CommandType::TaskUpdate,
        Some(task_id),
        json!({ "title": title }),
        vec![shown(task_id, revision)],
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

fn task_change(task_id: &str, title: &str, revision: u64, version: u64) -> Value {
    let mut value = task_template().clone();
    value["id"] = json!(task_id);
    value["title"] = json!(title);
    value["revision"] = json!(revision.to_string());
    json!({
        "entity_type": "task",
        "record_key": [task_id],
        "record_version": version.to_string(),
        "edit_revision": revision.to_string(),
        "operation": "upsert",
        "value": value,
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

fn with_common_in(mut body: Value, generation: &str) -> Value {
    body["correlation_id"] = json!("corr-1");
    body["scope_id"] = json!(SCOPE);
    body["server_generation"] = json!(generation);
    body["server_now"] = json!(NOW);
    body
}

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

/// One page of complete transactions from `from`, ending at `to`.
fn feed_page(from: &str, transactions: Vec<Value>, to: &str, high: u64) -> ChangesPage {
    decode(
        &with_common_in(
            json!({
                "from_cursor": from,
                "transactions": transactions,
                "has_more": false,
                "next_cursor": to,
                "high_watermark": high.to_string(),
            }),
            GENERATION,
        )
        .to_string(),
    )
    .unwrap()
}

fn apply(store: &mut Store, page: &ChangesPage) -> Result<bb_client::FeedStep, ApplyError> {
    let fence = capture_fence(store).unwrap();
    apply_changes(store, &context(), &fence, page)
}

/// `T` created by the server in transaction 1 (an external writer), applied.
fn confirmed_task(store: &mut Store, task_id: &str, title: &str) {
    let seeded = feed_page(
        "cursor-0",
        vec![transaction(
            1,
            &external(1),
            vec![task_change(task_id, title, 1, 1)],
        )],
        "cursor-1",
        1,
    );
    apply(store, &seeded).unwrap();
}

fn receipt(generation: &str, command: &CommandId, seq: u64) -> Receipt {
    decode(
        &with_common_in(
            json!({
                "command_id": command.as_str(),
                "outcome": "accepted",
                "has_changes": true,
                "commit_seq": seq.to_string(),
                "result_versions": [],
                "id_bindings": [],
                "result_redacted": false,
                "result": null,
                "error": null,
            }),
            generation,
        )
        .to_string(),
    )
    .unwrap()
}

fn rejected(command: &CommandId) -> Receipt {
    decode(
        &with_common_in(
            json!({
                "command_id": command.as_str(),
                "outcome": "rejected",
                "has_changes": false,
                "commit_seq": null,
                "result_versions": [],
                "id_bindings": [],
                "result_redacted": false,
                "result": null,
                "error": {
                    "code": "REVISION_CONFLICT", "retryable": false,
                    "message": "refused", "details": {}
                },
            }),
            GENERATION,
        )
        .to_string(),
    )
    .unwrap()
}

fn settle(store: &mut Store, receipt: &Receipt) -> Result<bb_client::Settled, ApplyError> {
    let fence = capture_fence(store).unwrap();
    apply_receipt(store, &context(), &fence, receipt)
}

// -------------------------------------------------------------------- the snapshot

const T: &str = "task_00000000-0000-4000-8000-0000000000aa";
const X: &str = "task_00000000-0000-4000-8000-0000000000bb";

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

/// What the server hands out: the manifest of `POST snapshots` and its pages.
#[derive(Clone)]
struct Fixture {
    id: String,
    manifest: Value,
    pages: Vec<Value>,
}

impl Fixture {
    fn id(&self) -> Id {
        Id::parse(&self.id).unwrap()
    }

    fn manifest(&self) -> SnapshotManifest {
        decode(&self.manifest.to_string()).unwrap()
    }

    fn page(&self, index: usize) -> SnapshotPage {
        decode(&self.pages[index].to_string()).unwrap()
    }

    fn lying(mut self, lie: Lie) -> Self {
        lie(&mut self.manifest);
        self
    }

    fn expiring(mut self, at: &str) -> Self {
        self.manifest["expires_at"] = json!(at);
        self
    }

    /// The server's own clock read `now` when it sent the manifest and pages.
    fn serving_at(mut self, now: &str) -> Self {
        self.manifest["server_now"] = json!(now);
        for page in &mut self.pages {
            page["server_now"] = json!(now);
        }
        self
    }

    /// Only the pages carry the server's clock reading `now`: a later response.
    fn paging_at(mut self, now: &str) -> Self {
        for page in &mut self.pages {
            page["server_now"] = json!(now);
        }
        self
    }

    fn envelope(&self) -> String {
        json!({ "manifest": self.manifest, "pages": self.pages }).to_string()
    }

    fn from_envelope(text: &str) -> Self {
        let value: Value = serde_json::from_str(text).unwrap();
        Self {
            id: value["manifest"]["snapshot_id"].as_str().unwrap().into(),
            manifest: value["manifest"].clone(),
            pages: value["pages"].as_array().unwrap().clone(),
        }
    }
}

/// A snapshot of `changes` at `watermark`, in `generation`, cut into small byte
/// chunks so the stream crosses record boundaries.
fn snapshot(id: &str, generation: &str, watermark: u64, changes: &[Value]) -> Fixture {
    let stream = serde_json::to_vec(&json!(changes)).unwrap();
    stream_snapshot(id, generation, watermark, &stream, changes.len())
}

fn stream_snapshot(
    id: &str,
    generation: &str,
    watermark: u64,
    stream: &[u8],
    records: usize,
) -> Fixture {
    let chunks: Vec<&[u8]> = stream.chunks(331).collect();
    let pages: Vec<Value> = chunks
        .iter()
        .enumerate()
        .map(|(index, chunk)| {
            let last = index + 1 == chunks.len();
            with_common_in(
                json!({
                    "snapshot_id": id,
                    "watermark": watermark.to_string(),
                    "page_index": index,
                    "payload_base64": base64_encode(chunk),
                    "page_sha256": sha256_hex(chunk),
                    "has_more": !last,
                    "next_page_token": if last { Value::Null } else { json!(format!("token-{}", index + 1)) },
                }),
                generation,
            )
        })
        .collect();
    let manifest = with_common_in(
        json!({
            "snapshot_id": id,
            "watermark": watermark.to_string(),
            "cursor": format!("cursor-{watermark}"),
            "page_count": pages.len(),
            "record_count": records,
            "total_bytes": stream.len(),
            "sha256": sha256_hex(stream),
            "expires_at": EXPIRES,
            "first_page_token": "token-0",
        }),
        generation,
    );
    Fixture {
        id: id.to_string(),
        manifest,
        pages,
    }
}

/// Six tasks: enough that the stream is many pages long.
fn six_tasks() -> Vec<Value> {
    (1..=6)
        .map(|n| {
            task_change(
                &format!("task_00000000-0000-4000-8000-{:012}", n + 1000),
                &format!("Server {n}"),
                1,
                n,
            )
        })
        .collect()
}

fn begin_at(
    store: &mut Store,
    fence: &Fence,
    now: &str,
    fx: &Fixture,
) -> Result<SnapshotProgress, ApplyError> {
    begin_snapshot(store, &context_at(now), fence, &fx.manifest())
}

fn begin(store: &mut Store, fx: &Fixture) -> Result<SnapshotProgress, ApplyError> {
    let fence = capture_fence(store).unwrap();
    begin_at(store, &fence, NOW, fx)
}

fn put_at(
    store: &mut Store,
    fence: &Fence,
    now: &str,
    fx: &Fixture,
    index: usize,
) -> Result<SnapshotProgress, ApplyError> {
    stage_snapshot_page(store, &context_at(now), fence, &fx.page(index))
}

fn put(store: &mut Store, fx: &Fixture, index: usize) -> Result<SnapshotProgress, ApplyError> {
    let fence = capture_fence(store).unwrap();
    put_at(store, &fence, NOW, fx, index)
}

fn put_range(store: &mut Store, fx: &Fixture, pages: std::ops::Range<usize>) {
    for index in pages {
        put(store, fx, index).unwrap();
    }
}

fn put_all(store: &mut Store, fx: &Fixture) {
    put_range(store, fx, 0..fx.pages.len());
}

fn activate_at(
    store: &mut Store,
    fence: &Fence,
    now: &str,
    fx: &Fixture,
) -> Result<Activated, ApplyError> {
    activate_snapshot(store, &context_at(now), fence, &fx.id())
}

fn activate(store: &mut Store, fx: &Fixture) -> Result<Activated, ApplyError> {
    let fence = capture_fence(store).unwrap();
    activate_at(store, &fence, NOW, fx)
}

/// The whole download, then the activation.
fn install(store: &mut Store, fx: &Fixture) -> Activated {
    begin(store, fx).unwrap();
    put_all(store, fx);
    activate(store, fx).unwrap()
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

/// The command was sent and its outcome is `state` (or not known yet).
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

fn generation(store: &mut Store) -> Option<String> {
    store
        .read(|tx| tx.query_row("SELECT server_generation FROM sync_meta", [], |r| r.get(0)))
        .unwrap()
}

/// The intake epoch and the next local sequence: what a fresh gesture extends.
fn epoch(store: &mut Store) -> (Option<String>, String, i64) {
    store
        .read(|tx| {
            tx.query_row(
                "SELECT device_epoch, device_epoch_state, next_local_seq FROM sync_meta",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
        })
        .unwrap()
}

fn titles(store: &mut Store) -> BTreeSet<String> {
    store
        .read(|tx| {
            let mut statement =
                tx.prepare("SELECT body FROM visible_records WHERE record_type = 'task'")?;
            let rows = statement.query_map([], |row| row.get::<_, Vec<u8>>(0))?;
            Ok(rows
                .map(|body| {
                    let task: Value = serde_json::from_slice(&body.unwrap()).unwrap();
                    task["title"].as_str().unwrap().to_string()
                })
                .collect())
        })
        .unwrap()
}

fn set(items: &[&str]) -> BTreeSet<String> {
    items.iter().map(|item| (*item).to_string()).collect()
}

/// `(state, staged pages)` of every staging, in activation-ID order.
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

fn receipts_held(store: &mut Store, n: u64) -> Vec<String> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT server_generation FROM command_receipts WHERE command_id = ?1
                 ORDER BY server_generation",
            )?;
            let rows = statement.query_map([cmd(n).as_str()], |row| row.get(0))?;
            rows.collect()
        })
        .unwrap()
}

/// What the old database reads as: the confirmed base, the visible projection,
/// the cursor and the queue.
#[derive(Debug, PartialEq)]
struct Reading {
    confirmed: Vec<(String, String, String, i64)>,
    titles: BTreeSet<String>,
    position: (String, String),
    queue: BTreeMap<String, String>,
}

fn reading(store: &mut Store) -> Reading {
    Reading {
        confirmed: confirmed(store),
        titles: titles(store),
        position: position(store),
        queue: states(store),
    }
}

// ------------------------------------------------------------------ child processes

fn spawn(role: &str, path: &Path, fx: &Fixture) -> Child {
    Command::new(std::env::current_exe().unwrap())
        .args([
            "snapshot_child_entry",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ])
        .env(ROLE, role)
        .env("BB_SNAPSHOT_PATH", path)
        .env("BB_SNAPSHOT_FIXTURE", fx.envelope())
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
fn snapshot_child_entry() {
    let Ok(role) = std::env::var(ROLE) else {
        return;
    };
    let path = PathBuf::from(std::env::var("BB_SNAPSHOT_PATH").unwrap());
    let fx = Fixture::from_envelope(&std::env::var("BB_SNAPSHOT_FIXTURE").unwrap());
    let mut store = open(&path).unwrap();
    match role.as_str() {
        // Killed with half of the pages staged.
        "abort_mid_download" => {
            begin(&mut store, &fx).unwrap();
            put_range(&mut store, &fx, 0..fx.pages.len() / 2);
            announce("staged");
            std::process::abort();
        }
        // Killed with the base replaced but the transaction not committed.
        "abort_before_commit" => {
            begin(&mut store, &fx).unwrap();
            put_all(&mut store, &fx);
            let fence = capture_fence(&mut store).unwrap();
            let _ = activate_snapshot_with(&mut store, &context(), &fence, &fx.id(), |stage, _| {
                if stage == ApplyStage::Replayed {
                    announce("installed");
                    std::process::abort();
                }
                Ok(())
            });
        }
        // Killed right after the commit returned.
        "abort_after_commit" => {
            install(&mut store, &fx);
            announce("committed");
            std::process::abort();
        }
        other => panic!("unknown child role {other}"),
    }
}

// ------------------------------------------------------------------------- tests

mod snapshot {
    use super::*;

    // -------------------------------------------------- the old database stays active

    #[test]
    fn snapshot_026_fr_006_staging_is_never_the_active_base_until_one_activation() {
        let path = scratch("inactive");
        let mut store = linked(&path);
        confirmed_task(&mut store, T, "Old");
        let fx = snapshot(
            "snap-1",
            GENERATION,
            5,
            &[
                task_change(T, "Server", 2, 3),
                task_change(X, "Other", 1, 4),
            ],
        );
        let pages = fx.pages.len();
        assert!(pages > 2, "the stream must span several pages");
        let old = reading(&mut store);
        assert_eq!(old.titles, set(&["Old"]));

        assert_eq!(begin(&mut store, &fx).unwrap().total as usize, pages);
        put_range(&mut store, &fx, 0..pages - 1);
        assert_eq!(
            staging(&mut store),
            [("receiving".into(), pages as i64 - 1)]
        );
        assert_eq!(
            reading(&mut store),
            old,
            "a partial download changes nothing"
        );

        // Even a complete, verified staging is not the base yet.
        let last = put(&mut store, &fx, pages - 1).unwrap();
        assert!(last.is_complete());
        assert_eq!(staging(&mut store), [("complete".into(), pages as i64)]);
        assert_eq!(reading(&mut store), old);

        // A second connection (the widget) reads the old database for as long as
        // the activation transaction is open, and the new one once it committed.
        let mut widget = open(&path).unwrap();
        let mut seen = Vec::new();
        let fence = capture_fence(&mut store).unwrap();
        let done = activate_snapshot_with(&mut store, &context(), &fence, &fx.id(), |_, _| {
            seen.push(reading(&mut widget));
            Ok(())
        })
        .unwrap();
        assert_eq!(seen.len(), 2, "both stages ran inside the transaction");
        assert!(seen.iter().all(|reading| *reading == old));

        assert_eq!((done.watermark, done.records), (5, 2));
        assert_eq!(done.cursor, "cursor-5");
        assert!(!done.already_active);
        assert_eq!(confirmed(&mut store).len(), 2);
        assert_eq!(position(&mut store), ("cursor-5".into(), "5".into()));
        assert_eq!(titles(&mut store), set(&["Server", "Other"]));
        assert_eq!(titles(&mut widget), set(&["Server", "Other"]));
        assert_eq!(generation(&mut store).as_deref(), Some(GENERATION));
        assert_eq!(staging(&mut store), [("activated".into(), 0)]);
    }

    #[test]
    fn snapshot_026_fr_005_a_first_bootstrap_needs_only_the_scope_and_deltas_follow_the_watermark()
    {
        let path = scratch("bootstrap");
        let mut store = open(&path).unwrap();
        let fx = snapshot("snap-1", GENERATION, 5, &[task_change(T, "Server", 1, 3)]);
        // No scope yet: nothing to attach a snapshot to.
        assert_eq!(begin(&mut store, &fx).unwrap_err(), ApplyError::WrongScope);
        store
            .write(|tx| {
                tx.execute("UPDATE sync_meta SET scope_id = ?1", [SCOPE])?;
                Ok(())
            })
            .unwrap();
        assert_eq!(generation(&mut store), None);

        let mut other_scope = fx.clone();
        other_scope.manifest["scope_id"] = json!("scope-other");
        assert_eq!(
            begin(&mut store, &other_scope).unwrap_err(),
            ApplyError::WrongScope
        );

        install(&mut store, &fx);
        assert_eq!(generation(&mut store).as_deref(), Some(GENERATION));
        assert_eq!(position(&mut store), ("cursor-5".into(), "5".into()));

        // Deltas read strictly after the watermark: 5 is a duplicate, 6 continues.
        let step = apply(
            &mut store,
            &feed_page(
                "cursor-5",
                vec![
                    transaction(5, &external(5), vec![task_change(T, "Stale", 1, 3)]),
                    transaction(6, &external(6), vec![task_change(X, "Next", 1, 6)]),
                ],
                "cursor-6",
                6,
            ),
        )
        .unwrap();
        let bb_client::FeedStep::Applied(applied) = step else {
            panic!("expected an applied page");
        };
        assert_eq!((applied.transactions, applied.skipped), (1, 1));
        assert_eq!(titles(&mut store), set(&["Server", "Next"]));
        assert_eq!(position(&mut store), ("cursor-6".into(), "6".into()));
    }

    // ----------------------------------------------- edits made during the download

    #[test]
    fn snapshot_026_sc_002_edits_saved_while_downloading_survive_activation() {
        let path = scratch("during");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        confirmed_task(&mut store, T, "Old");
        create_task(&mut store, &mut ids, 1, "Before");
        edit(&mut store, &mut ids, 2, T, "Mine", "1");
        set_state(&mut store, 2, "sending", true);
        settle(&mut store, &rejected(&cmd(2))).unwrap();
        let issue_id = open_issues(&mut store).unwrap()[0].issue.issue_id.clone();

        let fx = snapshot(
            "snap-1",
            GENERATION,
            5,
            &[
                task_change(T, "Server", 2, 3),
                task_change(X, "Other", 1, 4),
            ],
        );
        let half = fx.pages.len() / 2;
        begin(&mut store, &fx).unwrap();
        put_range(&mut store, &fx, 0..half);

        // The app, the widget and an unsent decision all write mid-download.
        create_task(&mut store, &mut ids, 3, "During");
        let mut widget = open(&path).unwrap();
        create_task(&mut widget, &mut SeqIds(500), 4, "Widget");
        let draft = DecisionDraft {
            shown_revision: Some("1".into()),
            keep_mine: Some(true),
            dependents: BTreeMap::new(),
        };
        save_draft(&mut store, &issue_id, &draft, NOW).unwrap();
        assert_eq!(
            titles(&mut store),
            set(&["Old", "Before", "During", "Widget"])
        );

        put_range(&mut store, &fx, half..fx.pages.len());
        // ... and again after the last page, just before the activation.
        create_task(&mut widget, &mut SeqIds(600), 5, "Late");
        let before = (epoch(&mut store), states(&mut store));

        let done = activate(&mut store, &fx).unwrap();

        // No newer queue loss: every command is there, in order, still pending.
        assert_eq!((epoch(&mut store), states(&mut store)), before);
        assert_eq!(states(&mut store).len(), 5);
        for n in [1, 3, 4, 5] {
            assert_eq!(state(&mut store, n), "queued", "command {n}");
        }
        assert_eq!(state(&mut store, 2), "rejected");
        assert_eq!(
            done.replayed.unwrap().applied,
            [cmd(1), cmd(3), cmd(4), cmd(5)]
        );
        // The visible projection is the snapshot with the pending work over it.
        assert_eq!(
            titles(&mut store),
            set(&["Server", "Other", "Before", "During", "Widget", "Late"])
        );
        assert_eq!(
            confirmed(&mut store).len(),
            2,
            "the base is the snapshot alone"
        );
        // The issue and the unsent decision are the user's, untouched.
        let issues = open_issues(&mut store).unwrap();
        assert_eq!(issues.len(), 1);
        assert_eq!(issues[0].issue.local_text, Some(json!({ "title": "Mine" })));
        let restored = load_draft(&mut store, &issue_id).unwrap().unwrap();
        assert_eq!(restored.draft.keep_mine, Some(true));
    }

    #[test]
    fn snapshot_026_fr_013_a_pending_edit_of_a_record_the_snapshot_deleted_becomes_an_issue() {
        let path = scratch("deleted");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        confirmed_task(&mut store, T, "Old");
        edit(&mut store, &mut ids, 1, T, "Mine", "1");
        let fx = snapshot(
            "snap-1",
            GENERATION,
            5,
            &[tombstone(T, 3), task_change(X, "Other", 1, 4)],
        );

        let done = install(&mut store, &fx);

        // Never resurrected, never dropped: it is an issue holding what was typed.
        assert_eq!(done.replayed.unwrap().rejected, [cmd(1)]);
        assert_eq!(state(&mut store, 1), "rejected");
        let issues = open_issues(&mut store).unwrap();
        assert_eq!(issues.len(), 1);
        assert_eq!(issues[0].issue.reason.code(), "ENTITY_DELETED");
        assert_eq!(issues[0].issue.local_text, Some(json!({ "title": "Mine" })));
        assert_eq!(titles(&mut store), set(&["Other"]));
        assert!(
            confirmed(&mut store).iter().any(|row| row.3 == 1),
            "the tombstone is final"
        );
    }

    #[test]
    fn snapshot_026_fr_010_a_sent_command_the_snapshot_cannot_explain_is_looked_up_not_judged() {
        let path = scratch("sent");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        confirmed_task(&mut store, T, "Old");
        edit(&mut store, &mut ids, 1, T, "Mine", "1");
        set_state(&mut store, 1, "sending", true);
        let fx = snapshot("snap-1", GENERATION, 5, &[tombstone(T, 3)]);

        let done = install(&mut store, &fx);

        assert_eq!(done.lookups, [cmd(1)]);
        assert_eq!(done.replayed.unwrap().deferred, [cmd(1)]);
        assert_eq!(
            state(&mut store, 1),
            "sending",
            "the server's receipt decides"
        );
        assert!(open_issues(&mut store).unwrap().is_empty());
    }

    // ------------------------------------------------------ receipts and generations

    #[test]
    fn snapshot_026_fr_010_an_accepted_command_completes_only_at_or_below_the_watermark() {
        let path = scratch("watermark");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        let first = create_task(&mut store, &mut ids, 1, "One");
        create_task(&mut store, &mut ids, 2, "Two");
        for n in [1, 2] {
            set_state(&mut store, n, "sending", true);
        }
        settle(&mut store, &receipt(GENERATION, &cmd(1), 3)).unwrap();
        settle(&mut store, &receipt(GENERATION, &cmd(2), 9)).unwrap();
        assert_eq!(state(&mut store, 1), "accepted_awaiting_feed");
        let fx = snapshot("snap-1", GENERATION, 5, &[task_change(&first, "One", 1, 3)]);

        let done = install(&mut store, &fx);

        assert_eq!(done.completed, [cmd(1)]);
        assert_eq!(state(&mut store, 1), "completed");
        // Accepted at 9, past the snapshot at 5: it waits for its delta.
        assert_eq!(state(&mut store, 2), "accepted_awaiting_feed");
        assert!(
            done.lookups.is_empty(),
            "a same-generation receipt needs no lookup"
        );
        assert_eq!(titles(&mut store), set(&["One", "Two"]));
    }

    #[test]
    fn snapshot_026_fr_010_a_receipt_of_another_generation_proves_nothing_after_a_restore() {
        let path = scratch("generation");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "One");
        set_state(&mut store, 1, "sending", true);
        settle(&mut store, &receipt(GENERATION, &cmd(1), 2)).unwrap();
        // A restored server: its watermark is far past 2, but it is another
        // generation, and its history may not contain the command at all.
        let fx = snapshot("snap-1", RESTORED, 100, &[task_change(X, "Other", 1, 4)]);

        let done = install(&mut store, &fx);

        assert!(done.completed.is_empty());
        assert_eq!(done.lookups, [cmd(1)]);
        assert_eq!(state(&mut store, 1), "unknown");
        assert_eq!(generation(&mut store).as_deref(), Some(RESTORED));
        // The intent and its optimistic projection stay; the old receipt stays as
        // history under its own generation and is not consulted.
        assert_eq!(titles(&mut store), set(&["One", "Other"]));
        assert_eq!(receipts_held(&mut store, 1), [GENERATION]);

        // A late receipt of the old generation cannot settle anything now.
        assert_eq!(
            settle(&mut store, &receipt(GENERATION, &cmd(1), 2)).unwrap_err(),
            ApplyError::GenerationChanged
        );
        assert_eq!(state(&mut store, 1), "unknown");
        // The lookup answered by the current generation does.
        let settled = settle(&mut store, &receipt(RESTORED, &cmd(1), 50)).unwrap();
        assert_eq!(settled.settlement, bb_client::Settlement::Completed);
        assert_eq!(state(&mut store, 1), "completed");
        assert_eq!(receipts_held(&mut store, 1), [GENERATION, RESTORED]);
    }

    #[test]
    fn snapshot_026_fr_010_every_unknown_outcome_is_listed_for_lookup() {
        let path = scratch("lookups");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        for n in 1..=6 {
            create_task(&mut store, &mut ids, n, &format!("Task {n}"));
        }
        set_state(&mut store, 2, "sending", true);
        set_state(&mut store, 3, "unknown", true);
        set_state(&mut store, 4, "queued", true); // a retry waiting for its turn
        set_state(&mut store, 5, "sending", true);
        settle(&mut store, &receipt(GENERATION, &cmd(5), 99)).unwrap();
        set_state(&mut store, 6, "sending", true);
        settle(&mut store, &rejected(&cmd(6))).unwrap();
        let fx = snapshot("snap-1", GENERATION, 5, &[task_change(X, "Other", 1, 4)]);

        let done = install(&mut store, &fx);

        // Never-sent (1), awaiting its feed under a receipt of this generation (5)
        // and rejected (6) have a known outcome; the rest are looked up.
        assert_eq!(done.lookups, [cmd(2), cmd(3), cmd(4)]);
        assert_eq!(state(&mut store, 1), "queued");
        assert_eq!(state(&mut store, 5), "accepted_awaiting_feed");
        assert_eq!(state(&mut store, 6), "rejected");
        // Looking them up changes nothing until the answers come back.
        assert_eq!(state(&mut store, 2), "sending");
        assert_eq!(state(&mut store, 3), "unknown");
        assert_eq!(state(&mut store, 4), "queued");
    }

    // ---------------------------------------------- completeness and checksum checks

    #[test]
    fn snapshot_026_fr_006_an_incomplete_stream_is_never_activated_and_resumes() {
        let path = scratch("incomplete");
        let mut store = linked(&path);
        confirmed_task(&mut store, T, "Old");
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());
        let pages = fx.pages.len();
        let old = reading(&mut store);
        begin(&mut store, &fx).unwrap();
        for index in (0..pages).filter(|index| *index != 2) {
            put(&mut store, &fx, index).unwrap();
        }

        let error = activate(&mut store, &fx).unwrap_err();

        assert_eq!(
            error,
            ApplyError::Transfer(TransferFault::Incomplete { missing: vec![2] })
        );
        assert_eq!(error.code(), "TRANSFER_INCOMPLETE");
        assert_eq!(error.recovery(), Some(Recovery::Refetch));
        assert_eq!(reading(&mut store), old);
        assert_eq!(
            staging(&mut store),
            [("receiving".into(), pages as i64 - 1)]
        );
        // The missing page arrives, and the same staging activates.
        put(&mut store, &fx, 2).unwrap();
        assert_eq!(activate(&mut store, &fx).unwrap().records, 6);
        assert_eq!(confirmed(&mut store).len(), 6);
    }

    #[test]
    fn snapshot_026_fr_006_a_stream_that_disagrees_with_its_manifest_is_discarded_whole() {
        let lies: [(&str, Lie); 3] = [
            ("digest", |manifest| {
                manifest["sha256"] = json!(sha256_hex(b"other"))
            }),
            ("byte count", |manifest| {
                let bytes = manifest["total_bytes"].as_u64().unwrap();
                manifest["total_bytes"] = json!(bytes + 1);
            }),
            ("record count", |manifest| {
                let records = manifest["record_count"].as_u64().unwrap();
                manifest["record_count"] = json!(records + 1);
            }),
        ];
        for (name, lie) in lies {
            let path = scratch(&format!("lie-{}", name.replace(' ', "-")));
            let mut store = linked(&path);
            confirmed_task(&mut store, T, "Old");
            let old = reading(&mut store);
            let fx = snapshot("snap-1", GENERATION, 5, &six_tasks()).lying(lie);
            begin(&mut store, &fx).unwrap();
            put_all(&mut store, &fx);

            let error = activate(&mut store, &fx).unwrap_err();

            assert_eq!(
                error,
                ApplyError::Transfer(TransferFault::Corrupt),
                "{name}"
            );
            assert_eq!(error.recovery(), Some(Recovery::Snapshot), "{name}");
            assert_eq!(
                reading(&mut store),
                old,
                "{name}: the old base is untouched"
            );
            assert_eq!(staging(&mut store), [("abandoned".into(), 0)], "{name}");
        }
    }

    #[test]
    fn snapshot_026_fr_006_a_repeated_key_or_a_non_array_stream_is_corrupt() {
        let twice = [
            task_change(T, "First", 1, 1),
            task_change(T, "Second", 1, 2),
        ];
        let repeated = snapshot("snap-1", GENERATION, 5, &twice);
        let object = stream_snapshot("snap-1", GENERATION, 5, br#"{"not":"an array"}"#, 0);
        for (name, fx) in [("repeated key", repeated), ("not an array", object)] {
            let path = scratch(&format!("shape-{}", name.replace(' ', "-")));
            let mut store = linked(&path);
            let old = reading(&mut store);
            begin(&mut store, &fx).unwrap();
            put_all(&mut store, &fx);

            assert_eq!(
                activate(&mut store, &fx).unwrap_err(),
                ApplyError::Transfer(TransferFault::Corrupt),
                "{name}"
            );
            assert_eq!(reading(&mut store), old, "{name}");
        }
    }

    #[test]
    fn snapshot_026_fr_006_a_page_that_does_not_belong_to_the_manifest_is_refused() {
        let path = scratch("pages");
        let mut store = linked(&path);
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());
        let announced = |store: &mut Store| begin(store, &fx).unwrap();

        // A page nobody announced.
        assert_eq!(
            put(&mut store, &fx, 0).unwrap_err(),
            ApplyError::Transfer(TransferFault::Unknown)
        );

        // Bytes that do not match the page digest are refused and not kept.
        announced(&mut store);
        let mut flipped = fx.clone();
        let payload = flipped.pages[1]["payload_base64"]
            .as_str()
            .unwrap()
            .to_string();
        flipped.pages[1]["payload_base64"] = json!(format!("QQ{}", &payload[2..]));
        assert_eq!(
            put(&mut store, &flipped, 1).unwrap_err(),
            ApplyError::Transfer(TransferFault::PageCorrupt { page_index: 1 })
        );
        assert_eq!(staging(&mut store), [("receiving".into(), 0)]);

        // A different page for an index already kept is a conflict: the staging
        // is worthless and dropped.
        put(&mut store, &fx, 1).unwrap();
        let mut rival = stream_snapshot("snap-1", GENERATION, 5, &[b'x'; 331], 0);
        rival.pages[0]["page_index"] = json!(1);
        rival.pages[0]["has_more"] = json!(true);
        rival.pages[0]["next_page_token"] = json!("token-2");
        assert_eq!(
            put(&mut store, &rival, 0).unwrap_err(),
            ApplyError::Transfer(TransferFault::Conflict)
        );
        assert_eq!(staging(&mut store), [("abandoned".into(), 0)]);

        // A page of another version of the snapshot.
        announced(&mut store);
        let mut other_version = fx.clone();
        other_version.pages[0]["watermark"] = json!("6");
        assert_eq!(
            put(&mut store, &other_version, 0).unwrap_err(),
            ApplyError::Transfer(TransferFault::Conflict)
        );
        assert_eq!(staging(&mut store), [("abandoned".into(), 0)]);

        // A page of another server generation.
        announced(&mut store);
        let mut restored = fx.clone();
        restored.pages[0]["server_generation"] = json!(RESTORED);
        let error = put(&mut store, &restored, 0).unwrap_err();
        assert_eq!(error, ApplyError::GenerationChanged);
        assert_eq!(error.recovery(), Some(Recovery::Snapshot));
        assert_eq!(staging(&mut store), [("abandoned".into(), 0)]);

        // Another manifest under the ID of a download in progress.
        announced(&mut store);
        let other_manifest = snapshot("snap-1", GENERATION, 5, &six_tasks()[..3]);
        assert_eq!(
            begin(&mut store, &other_manifest).unwrap_err(),
            ApplyError::Transfer(TransferFault::Conflict)
        );
        assert_eq!(staging(&mut store), [("abandoned".into(), 0)]);
    }

    #[test]
    fn snapshot_026_fr_006_a_newer_download_supersedes_one_in_progress_and_can_be_abandoned() {
        let path = scratch("supersede");
        let mut store = linked(&path);
        let first = snapshot("snap-1", GENERATION, 5, &six_tasks());
        let second = snapshot("snap-2", GENERATION, 6, &six_tasks()[..2]);
        begin(&mut store, &first).unwrap();
        put(&mut store, &first, 0).unwrap();

        begin(&mut store, &second).unwrap();

        assert_eq!(
            staging(&mut store),
            [("abandoned".into(), 0), ("receiving".into(), 0)]
        );
        abandon_snapshot(&mut store, &second.id()).unwrap();
        assert_eq!(
            staging(&mut store),
            [("abandoned".into(), 0), ("abandoned".into(), 0)]
        );
        assert_eq!(
            activate(&mut store, &second).unwrap_err(),
            ApplyError::Transfer(TransferFault::Unknown)
        );
    }

    // ----------------------------------------------------- expiry and interruption

    #[test]
    fn snapshot_026_fr_005_expiry_restarts_the_snapshot_and_keeps_the_active_base_and_queue() {
        let path = scratch("expiry");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        confirmed_task(&mut store, T, "Old");
        create_task(&mut store, &mut ids, 1, "Mine");
        let old = reading(&mut store);
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());
        let fence = capture_fence(&mut store).unwrap();
        begin(&mut store, &fx).unwrap();
        put_range(&mut store, &fx, 0..2);

        // The 30 minutes run out in the middle of the download.
        let error = put_at(&mut store, &fence, AFTER_EXPIRY, &fx, 2).unwrap_err();
        assert_eq!(error, ApplyError::Transfer(TransferFault::Expired));
        assert_eq!(error.code(), "RESET_REQUIRED");
        assert_eq!(error.recovery(), Some(Recovery::Snapshot));
        assert_eq!(staging(&mut store), [("abandoned".into(), 0)]);
        assert_eq!(reading(&mut store), old);

        // Restart: the old database reads as before, the expired manifest is not
        // taken up again, and a new snapshot starts without touching the queue.
        store.close().unwrap();
        let mut store = open(&path).unwrap();
        assert_eq!(reading(&mut store), old);
        let fence = capture_fence(&mut store).unwrap();
        let stale = fx.clone().serving_at(AFTER_EXPIRY);
        assert_eq!(
            begin_at(&mut store, &fence, AFTER_EXPIRY, &stale).unwrap_err(),
            ApplyError::Transfer(TransferFault::Expired)
        );
        let again = snapshot("snap-2", GENERATION, 6, &six_tasks())
            .expiring("2026-10-10T10:00:00Z")
            .serving_at(AFTER_EXPIRY);
        begin_at(&mut store, &fence, AFTER_EXPIRY, &again).unwrap();
        for index in 0..again.pages.len() {
            put_at(&mut store, &fence, AFTER_EXPIRY, &again, index).unwrap();
        }
        activate_at(&mut store, &fence, AFTER_EXPIRY, &again).unwrap();
        assert_eq!(state(&mut store, 1), "queued");
        assert_eq!(
            titles(&mut store).len(),
            7,
            "six snapshot tasks and the queued one"
        );
        assert!(titles(&mut store).contains("Mine"));
    }

    #[test]
    fn snapshot_026_fr_005_a_staged_snapshot_that_expired_before_activation_is_not_activated() {
        let path = scratch("expiry-late");
        let mut store = linked(&path);
        confirmed_task(&mut store, T, "Old");
        let old = reading(&mut store);
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());
        let fence = capture_fence(&mut store).unwrap();
        begin(&mut store, &fx).unwrap();
        put_all(&mut store, &fx);

        let error = activate_at(&mut store, &fence, AFTER_EXPIRY, &fx).unwrap_err();

        assert_eq!(error, ApplyError::Transfer(TransferFault::Expired));
        assert_eq!(reading(&mut store), old);
        assert_eq!(staging(&mut store), [("abandoned".into(), 0)]);
    }

    // The TTL is the server's: the device clock is never compared with a server
    // instant. Here the server reads 09:00 and the snapshot expires at 09:30.

    #[test]
    fn snapshot_026_fr_005_a_device_clock_far_ahead_still_activates_a_fresh_snapshot() {
        let path = scratch("clock-ahead");
        let mut store = linked(&path);
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());
        let fence = capture_fence(&mut store).unwrap();
        let ahead = "2026-10-10T14:00:00Z"; // five hours past the server

        begin_at(&mut store, &fence, ahead, &fx).unwrap();
        for index in 0..fx.pages.len() {
            put_at(&mut store, &fence, ahead, &fx, index).unwrap();
        }
        let done = activate_at(&mut store, &fence, ahead, &fx).unwrap();

        assert_eq!(done.records, 6);
        assert_eq!(position(&mut store), ("cursor-5".into(), "5".into()));
    }

    #[test]
    fn snapshot_026_fr_005_a_device_clock_behind_still_expires_a_stale_snapshot() {
        let behind = "2026-10-10T06:00:00Z"; // three hours before the server
        let later = "2026-10-10T06:31:00Z"; // 31 minutes of real time on
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());

        // Elapsed local time spends the TTL, though 06:31 is before 09:30.
        let path = scratch("clock-behind-pages");
        let mut store = linked(&path);
        let old = reading(&mut store);
        let fence = capture_fence(&mut store).unwrap();
        begin_at(&mut store, &fence, behind, &fx).unwrap();
        put_at(&mut store, &fence, behind, &fx, 0).unwrap();
        assert_eq!(
            put_at(&mut store, &fence, later, &fx, 1).unwrap_err(),
            ApplyError::Transfer(TransferFault::Expired)
        );
        assert_eq!(staging(&mut store), [("abandoned".into(), 0)]);
        assert_eq!(reading(&mut store), old);

        // ... the same at activation.
        let path = scratch("clock-behind-activation");
        let mut store = linked(&path);
        let fence = capture_fence(&mut store).unwrap();
        begin_at(&mut store, &fence, behind, &fx).unwrap();
        for index in 0..fx.pages.len() {
            put_at(&mut store, &fence, behind, &fx, index).unwrap();
        }
        assert_eq!(
            activate_at(&mut store, &fence, later, &fx).unwrap_err(),
            ApplyError::Transfer(TransferFault::Expired)
        );
        assert_eq!(staging(&mut store), [("abandoned".into(), 0)]);

        // The server's own reading on a later page spends it even when the device
        // clock has not moved at all.
        let path = scratch("clock-behind-server");
        let mut store = linked(&path);
        let fence = capture_fence(&mut store).unwrap();
        let late_pages = fx.clone().paging_at(AFTER_EXPIRY);
        begin_at(&mut store, &fence, behind, &fx).unwrap();
        assert_eq!(
            put_at(&mut store, &fence, behind, &late_pages, 0).unwrap_err(),
            ApplyError::Transfer(TransferFault::Expired)
        );
    }

    #[test]
    fn snapshot_026_fr_005_a_backwards_clock_does_not_extend_the_lifetime() {
        let path = scratch("clock-back");
        let mut store = linked(&path);
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());
        let fence = capture_fence(&mut store).unwrap();
        begin_at(&mut store, &fence, NOW, &fx).unwrap();
        put_at(&mut store, &fence, "2026-10-10T09:20:00Z", &fx, 0).unwrap();

        // The app restarts and the clock has been set back an hour: 20 minutes of
        // the lifetime are still spent.
        store.close().unwrap();
        let mut store = open(&path).unwrap();
        put_at(&mut store, &fence, "2026-10-10T08:00:00Z", &fx, 1).unwrap();
        // Eleven more minutes by that clock make 31 in all, not 11.
        assert_eq!(
            put_at(&mut store, &fence, "2026-10-10T08:11:00Z", &fx, 2).unwrap_err(),
            ApplyError::Transfer(TransferFault::Expired)
        );
        assert_eq!(staging(&mut store), [("abandoned".into(), 0)]);
    }

    #[test]
    fn snapshot_026_fr_010_a_snapshot_older_than_the_base_of_its_generation_is_refused() {
        let path = scratch("older");
        let mut store = linked(&path);
        confirmed_task(&mut store, T, "Old"); // watermark 1
        let old = reading(&mut store);
        let behind = snapshot("snap-0", GENERATION, 0, &[]);
        let error = begin(&mut store, &behind).unwrap_err();
        assert_eq!(
            error,
            ApplyError::Gap {
                expected: 1,
                found: 0,
                recovery: Recovery::Refetch
            }
        );
        assert!(staging(&mut store).is_empty());

        // The base moves past a snapshot while it downloads.
        let fx = snapshot("snap-1", GENERATION, 2, &[task_change(T, "Snap", 2, 2)]);
        begin(&mut store, &fx).unwrap();
        put_all(&mut store, &fx);
        let feed = feed_page(
            "cursor-1",
            vec![
                transaction(2, &external(2), vec![task_change(X, "Fed", 1, 2)]),
                transaction(3, &external(3), vec![task_change(X, "Fed again", 2, 3)]),
            ],
            "cursor-3",
            3,
        );
        apply(&mut store, &feed).unwrap();
        let ahead = reading(&mut store);
        assert_ne!(ahead, old);

        let error = activate(&mut store, &fx).unwrap_err();

        assert_eq!(
            error,
            ApplyError::Gap {
                expected: 3,
                found: 2,
                recovery: Recovery::Refetch
            }
        );
        assert_eq!(reading(&mut store), ahead, "the base never goes backwards");
        assert_eq!(staging(&mut store), [("abandoned".into(), 0)]);
        // Another generation is a restore, not a regression: it may be lower.
        let restored = snapshot("snap-2", RESTORED, 1, &[task_change(X, "Restored", 1, 1)]);
        install(&mut store, &restored);
        assert_eq!(titles(&mut store), set(&["Restored"]));
    }

    #[test]
    fn snapshot_026_fr_010_a_reset_during_the_download_fences_late_pages_and_activation() {
        let path = scratch("reset");
        let mut store = linked(&path);
        confirmed_task(&mut store, T, "Old");
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());
        let before = capture_fence(&mut store).unwrap();
        begin(&mut store, &fx).unwrap();
        put_range(&mut store, &fx, 0..2);
        put_all(&mut store, &fx);
        let old = reading(&mut store);

        // RESET_REQUIRED: the runtime advances the local sync generation.
        store
            .write(|tx| {
                tx.execute(
                    "UPDATE sync_meta SET local_sync_generation = local_sync_generation + 1",
                    [],
                )?;
                Ok(())
            })
            .unwrap();

        // Responses of the cancelled request are ignored, whatever they carry.
        assert_eq!(
            put_at(&mut store, &before, NOW, &fx, 0).unwrap_err(),
            ApplyError::Stale
        );
        assert_eq!(
            activate_at(&mut store, &before, NOW, &fx).unwrap_err(),
            ApplyError::Stale
        );
        assert_eq!(
            begin_at(&mut store, &before, NOW, &fx).unwrap_err(),
            ApplyError::Stale
        );
        // The download started before the reset is not resumed by a new request.
        assert_eq!(put(&mut store, &fx, 0).unwrap_err(), ApplyError::Stale);
        assert_eq!(activate(&mut store, &fx).unwrap_err(), ApplyError::Stale);
        assert_eq!(reading(&mut store), old);

        // Announcing it again under the new fences starts the staging over.
        assert_eq!(begin(&mut store, &fx).unwrap().received, 0);
        put_all(&mut store, &fx);
        assert_eq!(activate(&mut store, &fx).unwrap().records, 6);
    }

    #[test]
    fn snapshot_026_sc_002_announcing_and_activating_again_changes_nothing() {
        let path = scratch("idempotent");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Mine");
        set_state(&mut store, 1, "sending", true);
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());
        assert_eq!(begin(&mut store, &fx).unwrap().received, 0);
        put(&mut store, &fx, 0).unwrap();
        assert_eq!(
            put(&mut store, &fx, 0).unwrap().received,
            1,
            "a repeated page is kept once"
        );
        assert_eq!(
            begin(&mut store, &fx).unwrap().received,
            1,
            "announcing resumes"
        );
        put_range(&mut store, &fx, 1..fx.pages.len());
        let first = activate(&mut store, &fx).unwrap();
        let after = (reading(&mut store), epoch(&mut store));

        let again = activate(&mut store, &fx).unwrap();

        assert!(again.already_active && again.replayed.is_none());
        assert_eq!(again.cursor, first.cursor);
        assert_eq!(again.lookups, [cmd(1)]);
        assert_eq!((reading(&mut store), epoch(&mut store)), after);
        assert!(begin(&mut store, &fx).unwrap().is_complete());
        assert_eq!(
            put(&mut store, &fx, 0).unwrap_err(),
            ApplyError::Transfer(TransferFault::Unknown)
        );
        assert_eq!(reading(&mut store), after.0);
        assert_eq!(epoch(&mut store), after.1);
    }

    // --------------------------------------------------------------- crash boundaries

    #[test]
    fn snapshot_026_sc_002_a_restart_mid_download_keeps_the_old_base_a_new_capture_and_the_staging()
    {
        let path = scratch("crash-download");
        let mut store = linked(&path);
        confirmed_task(&mut store, T, "Old");
        store.close().unwrap();
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());
        let staged = fx.pages.len() / 2;

        let mut child = spawn("abort_mid_download", &path, &fx);
        wait_for(&mut child, "staged");
        assert!(!child.wait().unwrap().success(), "the child aborts");

        // Restart: the old database reads as before, and the staging is kept.
        let mut store = open(&path).unwrap();
        assert_eq!(titles(&mut store), set(&["Old"]));
        assert_eq!(position(&mut store), ("cursor-1".into(), "1".into()));
        assert_eq!(staging(&mut store), [("receiving".into(), staged as i64)]);

        // The snapshot is interrupted; the user captures something new, and the
        // app restarts again. The epoch, the command and the projection survive.
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Captured");
        let saved = epoch(&mut store);
        assert_eq!(saved.1, "pending_registration");
        store.close().unwrap();
        let mut store = open(&path).unwrap();
        assert_eq!(epoch(&mut store), saved);
        assert_eq!(titles(&mut store), set(&["Old", "Captured"]));

        // The download resumes where it stopped and activates over the capture.
        assert_eq!(begin(&mut store, &fx).unwrap().received as usize, staged);
        put_range(&mut store, &fx, staged..fx.pages.len());
        activate(&mut store, &fx).unwrap();
        assert_eq!(epoch(&mut store), saved);
        assert_eq!(state(&mut store, 1), "queued");
        assert_eq!(titles(&mut store).len(), 7);
        assert!(titles(&mut store).contains("Captured"));
        assert_eq!(position(&mut store), ("cursor-5".into(), "5".into()));
    }

    #[test]
    fn snapshot_026_sc_002_a_crash_before_the_commit_leaves_the_old_base_and_a_complete_staging() {
        let path = scratch("crash-before");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        confirmed_task(&mut store, T, "Old");
        create_task(&mut store, &mut ids, 1, "Before");
        store.close().unwrap();
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());

        let mut child = spawn("abort_before_commit", &path, &fx);
        wait_for(&mut child, "installed");
        assert!(!child.wait().unwrap().success(), "the child aborts");

        // Restart: the base, cursor, generation and queue are exactly as before.
        let mut store = open(&path).unwrap();
        assert_eq!(titles(&mut store), set(&["Old", "Before"]));
        assert_eq!(confirmed(&mut store).len(), 1);
        assert_eq!(position(&mut store), ("cursor-1".into(), "1".into()));
        assert_eq!(state(&mut store, 1), "queued");
        assert_eq!(
            staging(&mut store),
            [("complete".into(), fx.pages.len() as i64)]
        );
        // An edit made after the crash is part of the retried activation.
        create_task(&mut store, &mut ids, 2, "After");
        let done = activate(&mut store, &fx).unwrap();
        assert_eq!(done.replayed.unwrap().applied, [cmd(1), cmd(2)]);
        assert_eq!(titles(&mut store).len(), 8);
        assert!(titles(&mut store).is_superset(&set(&["Before", "After"])));
        assert_eq!(position(&mut store), ("cursor-5".into(), "5".into()));
    }

    #[test]
    fn snapshot_026_sc_002_a_crash_after_the_commit_keeps_the_new_base_and_activating_again_is_a_no_op()
     {
        let path = scratch("crash-after");
        let mut store = linked(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Before");
        store.close().unwrap();
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());

        let mut child = spawn("abort_after_commit", &path, &fx);
        wait_for(&mut child, "committed");
        assert!(!child.wait().unwrap().success(), "the child aborts");

        let mut store = open(&path).unwrap();
        assert_eq!(position(&mut store), ("cursor-5".into(), "5".into()));
        assert_eq!(confirmed(&mut store).len(), 6);
        assert_eq!(titles(&mut store).len(), 7);
        assert_eq!(state(&mut store, 1), "queued");
        // The caller never learned of the commit: it asks again.
        let after = reading(&mut store);
        assert!(begin(&mut store, &fx).unwrap().is_complete());
        assert!(activate(&mut store, &fx).unwrap().already_active);
        assert_eq!(reading(&mut store), after);
    }

    #[test]
    fn snapshot_026_fr_025_activation_takes_its_turn_behind_a_widget_write_and_loses_no_edit() {
        let path = scratch("lock");
        let mut store = linked(&path);
        let fx = snapshot("snap-1", GENERATION, 5, &six_tasks());
        begin(&mut store, &fx).unwrap();
        put_all(&mut store, &fx);
        let mut widget = open(&path).unwrap();
        let (held, held_rx) = std::sync::mpsc::channel::<()>();

        let (done, waited) = std::thread::scope(|scope| {
            // The widget holds the cross-process writer lock while the
            // activation starts, then saves a capture of its own.
            let writer = scope.spawn(move || {
                widget
                    .write(|tx| {
                        tx.execute("UPDATE sync_meta SET last_success_at = ?1", [NOW])?;
                        held.send(()).unwrap();
                        std::thread::sleep(Duration::from_millis(300));
                        Ok(())
                    })
                    .unwrap();
                create_task(&mut widget, &mut SeqIds(700), 9, "Widget");
            });
            held_rx.recv().unwrap();
            let started = std::time::Instant::now();
            let done = activate(&mut store, &fx);
            let waited = started.elapsed();
            writer.join().unwrap();
            (done, waited)
        });

        // The activation waited its turn instead of failing, and whichever of
        // the two committed first, the capture is in the queue and the projection.
        done.unwrap();
        assert!(waited >= Duration::from_millis(150), "waited {waited:?}");
        let mut store = open(&path).unwrap();
        assert_eq!(state(&mut store, 9), "queued");
        assert_eq!(titles(&mut store).len(), 7);
        assert!(titles(&mut store).contains("Widget"));
        assert_eq!(position(&mut store), ("cursor-5".into(), "5".into()));
    }
}

fn native_origin(store: &mut Store, task_id: &str) -> Option<bb_domain::types::OpenList> {
    let mut read_set = bb_domain::types::ReadSet::default();
    for record in bb_client::visible_snapshot(store).unwrap().records {
        if let bb_domain::types::Record::Task(task) = record {
            read_set.tasks.insert(task.id.clone(), task);
        }
    }
    bb_client::local_task_origins(store, &read_set)
        .unwrap()
        .get(&bb_domain::types::TaskId::parse(task_id).unwrap())
        .copied()
}

fn completed_change(revision: u64, version: u64) -> Value {
    let mut change = task_change(T, "Origin", revision, version);
    change["value"]["state"] = json!("completed");
    change["value"]["completed_at"] = json!(NOW);
    change
}

#[test]
fn snapshot_local_origin_requires_exact_confirmed_version_and_generation() {
    use bb_domain::types::OpenList;
    for (name, generation, version, retained) in [
        ("same-version", GENERATION, 2, true),
        ("new-version", GENERATION, 3, false),
        ("new-generation", RESTORED, 2, false),
    ] {
        let mut store = linked(&scratch(name));
        confirmed_task(&mut store, T, "Origin");
        apply(
            &mut store,
            &feed_page(
                "cursor-1",
                vec![transaction(2, &external(2), vec![completed_change(2, 2)])],
                "cursor-2",
                2,
            ),
        )
        .unwrap();
        assert_eq!(native_origin(&mut store, T), Some(OpenList::Inbox));
        install(
            &mut store,
            &snapshot(
                "snapshot-origin",
                generation,
                2,
                &[completed_change(2, version)],
            ),
        );
        assert_eq!(
            native_origin(&mut store, T),
            retained.then_some(OpenList::Inbox),
            "{name}"
        );
    }
}

#[test]
fn snapshot_local_origin_accepted_transition_requires_exact_receipt_result_version() {
    use bb_domain::types::OpenList;
    for (name, result_version, seq, version, watermark, generation, retained) in [
        ("receipt-matching", 2, 2, 2, 2, GENERATION, true),
        ("receipt-mismatch", 3, 2, 2, 2, GENERATION, false),
        ("receipt-newer", 2, 3, 2, 2, GENERATION, false),
        ("receipt-exhausted", 2, 2, 3, 3, GENERATION, false),
        ("receipt-wrong-generation", 2, 2, 2, 2, RESTORED, false),
    ] {
        let mut store = linked(&scratch(name));
        confirmed_task(&mut store, T, "Origin");
        execute(
            &mut store,
            &mut SeqIds(0),
            &request(
                cmd(1),
                CommandType::TaskTransition,
                Some(T),
                json!({"action":"complete"}),
                vec![shown(T, "1")],
            ),
        )
        .unwrap();
        store
            .write(|tx| {
                tx.execute("UPDATE outbox SET state = 'sending', ever_sent = 1", [])?;
                Ok(())
            })
            .unwrap();
        let mut accepted = receipt(GENERATION, &cmd(1), seq);
        accepted
            .result_versions
            .push(bb_protocol::receipt::Version {
                entity_type: EntityType::Task,
                record_key: vec![T.to_owned()],
                record_version: Counter::from(result_version),
                edit_revision: Some(Counter::from(2)),
            });
        settle(&mut store, &accepted).unwrap();
        install(
            &mut store,
            &snapshot(
                "snapshot-origin",
                generation,
                watermark,
                &[completed_change(2, version)],
            ),
        );
        assert_eq!(
            native_origin(&mut store, T),
            retained.then_some(OpenList::Inbox),
            "{name}"
        );
        let fields: Vec<u8> = store
            .read(|tx| {
                tx.query_row(
                    "SELECT fields FROM drafts WHERE editor_kind = 'runtime_task_local'",
                    [],
                    |r| r.get(0),
                )
            })
            .unwrap();
        let fact: Value = serde_json::from_slice(&fields).unwrap();
        let candidate_kept = fact["candidates"].get(cmd(1).as_str()).is_some();
        assert_eq!(
            candidate_kept,
            !matches!(name, "receipt-matching" | "receipt-exhausted"),
            "only promoted or exhausted proof paths retire candidates: {name}"
        );
    }
}

#[test]
fn snapshot_local_origin_cleared_overlay_never_reactivates_import_carrier() {
    let mut store = linked(&scratch("origin-carrier-inactive"));
    confirmed_task(&mut store, T, "Origin");
    store.write(|tx| {
        let body = serde_json::to_vec(&completed_change(1, 1)["value"]).unwrap();
        tx.execute("UPDATE confirmed_records SET body = ?1 WHERE record_type = 'task'", [&body])?;
        tx.execute("UPDATE visible_records SET body = ?1 WHERE record_type = 'task'", [&body])?;
        tx.execute("DELETE FROM drafts WHERE editor_kind = 'runtime_task_local'", [])?;
        tx.execute("INSERT INTO drafts (workspace_id,draft_id,editor_kind,record_type,record_key,fields,updated_at)
            VALUES (?1,'legacy-origin','legacy_task_local','task',?2,?3,?4)",
            params![WORKSPACE, json!([T]).to_string(), br#"{"lastOpenList":"someday"}"#.as_slice(), NOW])?;
        Ok(())
    }).unwrap();
    let generation = bb_client::projection_generation(&mut store).unwrap();
    bb_client::replay(&mut store, &context()).unwrap();
    assert!(
        bb_client::projection_generation(&mut store).unwrap() > generation,
        "a local-fact-only seed invalidates the projection generation"
    );
    assert_eq!(
        native_origin(&mut store, T),
        Some(bb_domain::types::OpenList::Someday)
    );
    install(
        &mut store,
        &snapshot("snapshot-origin", RESTORED, 2, &[completed_change(2, 2)]),
    );
    assert_eq!(native_origin(&mut store, T), None);
    bb_client::replay(&mut store, &context()).unwrap();
    assert_eq!(native_origin(&mut store, T), None);
    let carrier: Vec<u8> = store
        .read(|tx| {
            tx.query_row(
                "SELECT fields FROM drafts WHERE draft_id = 'legacy-origin'",
                [],
                |r| r.get(0),
            )
        })
        .unwrap();
    assert_eq!(carrier, br#"{"lastOpenList":"someday"}"#);
}
