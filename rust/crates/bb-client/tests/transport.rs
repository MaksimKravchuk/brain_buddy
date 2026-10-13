//! Transport and subscription tests (026 PR-40): bounded send/retry/dependency
//! scheduling, the 30-second poll bound, hint-driven wake-ups that never assert
//! freshness, query invalidations that coalesce, and cancellation that releases
//! everything.
//!
//! The server is a controlled in-memory model behind the `Transport` port, so
//! the tests inject loss, lost answers, timeouts, stale and out-of-order pages
//! and `5xx`/`429`, and drive time with a simulated monotonic clock. The client
//! side is the real one on a real SQLite file. Byte-exact SSE fixtures are the
//! frames the PR-58 publisher writes (`backend/app/modules/tasks/sync/hints.py`);
//! `hints_backend.rs` runs the same parser against the real backend process.

use bb_client::{
    Action, Authentication, Cancellation, ChangeKind, Changes, Clock, ExecuteContext,
    ExecuteRequest, Halt, HintReader, HintStream, HintWatcher, HttpRequest, HttpResponse, IdSource,
    InvalidationHub, Method, OpenOptions, SSE_MAX_EVENT_BYTES, Schedule, Scheduler, SessionBinding,
    SplitMix, SseItem, SseParser, Step, Store, StreamEnd, StreamFailure, SubscriptionError,
    SyncLoop, SyncSession, Syncer, Transport, TransportFailure, Wake, Waker, execute,
};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{AfterCommandPrecondition, CommandRef, Precondition};
use bb_protocol::wire::{CommandId, Id, Instant};
use rusqlite::params;
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashMap, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

const WORKSPACE: &str = "workspace-local";
const ACCOUNT: &str = "account-1";
const SCOPE: &str = "scope-1";
const DEVICE: &str = "device-1";
const GENERATION: &str = "generation-1";
const NOW: &str = "2026-10-10T09:00:00Z";
const EXPIRES: &str = "2026-10-10T09:30:00Z";

// ----------------------------------------------------------------------- harness

fn scratch(name: &str) -> PathBuf {
    let directory =
        std::env::temp_dir().join(format!("bb-transport-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    directory.join("store").join("workspace.sqlite3")
}

fn open(path: &Path) -> Store {
    Store::open(&OpenOptions {
        path: path.to_path_buf(),
        workspace_id: WORKSPACE.to_string(),
        busy_timeout: Duration::from_millis(5_000),
    })
    .unwrap()
}

/// A linked store holding a bootstrapped base at `cursor-0`.
fn linked(path: &Path) -> Store {
    let mut store = open(path);
    store
        .write(|tx| {
            tx.execute(
                "UPDATE sync_meta SET server_generation = ?1, cursor = 'cursor-0',
                    base_watermark = '0', account_link_state = 'linked'",
                [GENERATION],
            )?;
            Ok(())
        })
        .unwrap();
    store
}

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

/// An edit that must wait for command `after` (it depends on its result).
fn edit_after(store: &mut Store, ids: &mut SeqIds, n: u64, after: u64, task_id: &str, title: &str) {
    let update = request(
        cmd(n),
        CommandType::TaskUpdate,
        Some(task_id),
        json!({ "title": title }),
        vec![Precondition::AfterCommand(AfterCommandPrecondition {
            after_command: CommandRef {
                command_id: cmd(after),
                entity_type: EntityType::Task,
                entity_id: Id::parse(task_id).unwrap(),
            },
        })],
    );
    execute(store, ids, &update).unwrap();
}

fn outbox_states(store: &mut Store) -> BTreeMap<String, String> {
    store
        .read(|tx| {
            let mut statement = tx.prepare("SELECT command_id, state FROM outbox")?;
            let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
            rows.collect()
        })
        .unwrap()
}

fn state_of(store: &mut Store, n: u64) -> String {
    outbox_states(store)
        .remove(cmd(n).as_str())
        .unwrap_or_else(|| "absent".to_string())
}

fn confirmed_titles(store: &mut Store) -> Vec<String> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT body FROM confirmed_records WHERE record_type = 'task' AND tombstone = 0",
            )?;
            let rows = statement.query_map([], |row| row.get::<_, Vec<u8>>(0))?;
            let mut titles: Vec<String> = Vec::new();
            for body in rows {
                let value: Value = serde_json::from_slice(&body?).unwrap();
                titles.push(value["title"].as_str().unwrap().to_string());
            }
            titles.sort();
            Ok(titles)
        })
        .unwrap()
}

fn cursor_of(store: &mut Store) -> Option<String> {
    store
        .read(|tx| tx.query_row("SELECT cursor FROM sync_meta", [], |row| row.get(0)))
        .unwrap()
}

// ----------------------------------------------------------------- simulated time

#[derive(Clone)]
struct SimClock(Arc<AtomicU64>);

impl SimClock {
    fn new() -> Self {
        Self(Arc::new(AtomicU64::new(1_000_000)))
    }

    fn advance(&self, by: Duration) {
        self.0.fetch_add(by.as_micros() as u64, Ordering::SeqCst);
    }

    fn at(&self) -> Duration {
        Duration::from_micros(self.0.load(Ordering::SeqCst))
    }
}

impl Clock for SimClock {
    fn now(&self) -> Duration {
        self.at()
    }
}

// ----------------------------------------------------------- the controlled server

fn with_common(mut body: Value, generation: &str) -> Value {
    body["correlation_id"] = json!("corr-1");
    body["scope_id"] = json!(SCOPE);
    body["server_generation"] = json!(generation);
    body["server_now"] = json!(NOW);
    body
}

fn task_template() -> &'static Value {
    static TEMPLATE: OnceLock<Value> = OnceLock::new();
    TEMPLATE.get_or_init(|| {
        let path = scratch("template");
        let mut store = open(&path);
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

/// What the server does to the next matching request.
enum Effect {
    /// Not processed: the connection fails.
    Lose,
    /// Not processed: the request times out (takes the full request timeout).
    Timeout,
    /// Processed and committed, but the answer never arrives.
    LoseAnswer,
    /// An empty answer with this status and optional `Retry-After` seconds.
    Status(u16, Option<u64>),
    /// A protocol `ErrorBody`.
    Error(u16, &'static str, bool),
    /// This exact body, 200, instead of the real answer.
    Serve(Value),
    /// Runs, then the request is answered normally.
    Hook(Box<dyn FnOnce() + Send>),
    /// Hangs until the call is cancelled.
    Block,
}

struct Fault {
    route: &'static str,
    effect: Effect,
}

struct Tx {
    source: String,
    changes: Vec<Value>,
}

struct Model {
    generation: String,
    txs: Vec<Tx>,
    tasks: BTreeMap<String, (String, u64)>,
    commands: HashMap<String, u64>,
    faults: VecDeque<Fault>,
    log: Vec<(String, Option<Vec<u8>>)>,
    snapshot: Option<Vec<Value>>,
}

impl Model {
    fn new() -> Self {
        Self {
            generation: GENERATION.to_string(),
            txs: Vec::new(),
            tasks: BTreeMap::new(),
            commands: HashMap::new(),
            faults: VecDeque::new(),
            log: Vec::new(),
            snapshot: None,
        }
    }

    fn seq(&self) -> u64 {
        self.txs.len() as u64
    }

    fn common(&self, body: Value) -> Value {
        with_common(body, &self.generation)
    }

    /// A commit by another writer (the web, another device).
    fn commit_external(&mut self, task_id: &str, title: &str) -> u64 {
        let revision = self
            .tasks
            .get(task_id)
            .map_or(1, |(_, revision)| revision + 1);
        self.commit(cmd(900 + self.seq() + 1).as_str(), task_id, title, revision)
    }

    fn commit(&mut self, source: &str, task_id: &str, title: &str, revision: u64) -> u64 {
        let seq = self.seq() + 1;
        self.tasks
            .insert(task_id.to_string(), (title.to_string(), revision));
        self.txs.push(Tx {
            source: source.to_string(),
            changes: vec![task_change(task_id, title, revision, seq)],
        });
        seq
    }

    fn receipt(&self, command: &str, seq: u64) -> Value {
        self.common(json!({
            "command_id": command,
            "outcome": "accepted",
            "has_changes": true,
            "commit_seq": seq.to_string(),
            "result_versions": [],
            "id_bindings": [],
            "result_redacted": false,
            "result": null,
            "error": null,
        }))
    }

    fn page(&self, cursor: &str, limit: usize) -> Value {
        let after: u64 = cursor.strip_prefix("cursor-").unwrap().parse().unwrap();
        let rest: Vec<(u64, &Tx)> = self
            .txs
            .iter()
            .enumerate()
            .map(|(index, tx)| (index as u64 + 1, tx))
            .filter(|(seq, _)| *seq > after)
            .collect();
        let taken: Vec<&(u64, &Tx)> = rest.iter().take(limit).collect();
        let next = taken.last().map_or(after, |(seq, _)| *seq);
        self.common(json!({
            "from_cursor": cursor,
            "transactions": taken.iter().map(|(seq, tx)| json!({
                "transaction_id": format!("tx-{seq}"),
                "commit_seq": seq.to_string(),
                "source_command_id": tx.source,
                "changes": tx.changes,
            })).collect::<Vec<_>>(),
            "has_more": rest.len() > taken.len(),
            "next_cursor": format!("cursor-{next}"),
            "high_watermark": self.seq().to_string(),
        }))
    }

    fn snapshot_fixture(&mut self) -> (Value, Vec<Value>) {
        let changes: Vec<Value> = self
            .tasks
            .iter()
            .enumerate()
            .map(|(index, (id, (title, revision)))| {
                task_change(id, title, *revision, index as u64 + 1)
            })
            .collect();
        let stream = serde_json::to_vec(&json!(changes)).unwrap();
        let chunks: Vec<&[u8]> = stream.chunks(331).collect();
        let id = format!("snap-{}", self.seq());
        let watermark = self.seq();
        let pages: Vec<Value> = chunks
            .iter()
            .enumerate()
            .map(|(index, chunk)| {
                let last = index + 1 == chunks.len();
                self.common(json!({
                    "snapshot_id": id,
                    "watermark": watermark.to_string(),
                    "page_index": index,
                    "payload_base64": base64_encode(chunk),
                    "page_sha256": bb_client::sha256_hex(chunk),
                    "has_more": !last,
                    "next_page_token": if last { Value::Null } else { json!(format!("token-{}", index + 1)) },
                }))
            })
            .collect();
        let manifest = self.common(json!({
            "snapshot_id": id,
            "watermark": watermark.to_string(),
            "cursor": format!("cursor-{watermark}"),
            "page_count": pages.len(),
            "record_count": changes.len(),
            "total_bytes": stream.len(),
            "sha256": bb_client::sha256_hex(&stream),
            "expires_at": EXPIRES,
            "first_page_token": "token-0",
        }));
        (manifest, pages)
    }
}

struct World {
    model: Arc<Mutex<Model>>,
    clock: SimClock,
    latency: Arc<Mutex<Duration>>,
}

impl World {
    fn new() -> Self {
        Self {
            model: Arc::new(Mutex::new(Model::new())),
            clock: SimClock::new(),
            latency: Arc::new(Mutex::new(Duration::from_millis(100))),
        }
    }

    fn model(&self) -> std::sync::MutexGuard<'_, Model> {
        self.model.lock().unwrap()
    }

    fn fault(&self, route: &'static str, effect: Effect) {
        self.model().faults.push_back(Fault { route, effect });
    }

    fn common_json(&self, body: Value) -> Value {
        self.model().common(body)
    }

    fn requests(&self, route: &str) -> Vec<Option<Vec<u8>>> {
        self.model()
            .log
            .iter()
            .filter(|(logged, _)| logged == route)
            .map(|(_, body)| body.clone())
            .collect()
    }

    fn count(&self, route: &str) -> usize {
        self.requests(route).len()
    }

    fn transport(&self) -> Controlled {
        Controlled {
            model: Arc::clone(&self.model),
            clock: self.clock.clone(),
            latency: Arc::clone(&self.latency),
        }
    }

    fn syncer(&self, store: &mut Store, schedule: Schedule) -> Syncer {
        let session = SyncSession::start(
            store,
            &SessionBinding {
                account_id: Id::parse(ACCOUNT).unwrap(),
                scope_id: Id::parse(SCOPE).unwrap(),
                device_id: Id::parse(DEVICE).unwrap(),
                authentication: Authentication::Fresh,
            },
        )
        .unwrap();
        Syncer::new(
            Box::new(self.transport()),
            session,
            Box::new(context),
            Arc::new(self.clock.clone()),
            Box::new(SplitMix::seeded(11)),
            schedule,
        )
    }
}

struct Controlled {
    model: Arc<Mutex<Model>>,
    clock: SimClock,
    latency: Arc<Mutex<Duration>>,
}

fn route_of(request: &HttpRequest) -> (String, Vec<(String, String)>) {
    let path = request.path.strip_prefix("/api/sync/v1/").unwrap();
    let (name, query) = path.split_once('?').unwrap_or((path, ""));
    let params = query
        .split('&')
        .filter(|pair| !pair.is_empty())
        .map(|pair| {
            let (key, value) = pair.split_once('=').unwrap();
            (key.to_string(), value.to_string())
        })
        .collect();
    let verb = if request.method == Method::Get {
        "GET"
    } else {
        "POST"
    };
    let generic = if name.starts_with("commands/") {
        "commands/*".to_string()
    } else if name.starts_with("snapshots/") {
        "snapshots/*".to_string()
    } else {
        name.to_string()
    };
    (format!("{verb} {generic}"), params)
}

fn param(params: &[(String, String)], key: &str) -> String {
    params
        .iter()
        .find(|(name, _)| name == key)
        .map(|(_, value)| value.clone())
        .unwrap_or_default()
}

fn ok(body: &Value) -> Result<HttpResponse, TransportFailure> {
    Ok(HttpResponse {
        status: 200,
        retry_after: None,
        body: body.to_string().into_bytes(),
    })
}

impl Transport for Controlled {
    fn send(
        &self,
        request: &HttpRequest,
        cancel: &Cancellation<'_>,
    ) -> Result<HttpResponse, TransportFailure> {
        let (route, params) = route_of(request);
        let latency = *self.latency.lock().unwrap();
        let effect = {
            let mut model = self.model.lock().unwrap();
            model.log.push((route.clone(), request.body.clone()));
            let position = model.faults.iter().position(|fault| fault.route == route);
            position
                .and_then(|at| model.faults.remove(at))
                .map(|fault| fault.effect)
        };
        if cancel.is_cancelled() {
            return Err(TransportFailure::Cancelled);
        }
        let mut lose_answer = false;
        match effect {
            Some(Effect::Lose) => return Err(TransportFailure::Connection),
            Some(Effect::Timeout) => {
                self.clock.advance(request.timeout);
                return Err(TransportFailure::Timeout);
            }
            Some(Effect::Status(status, retry_after)) => {
                self.clock.advance(latency);
                return Ok(HttpResponse {
                    status,
                    retry_after: retry_after.map(Duration::from_secs),
                    body: Vec::new(),
                });
            }
            Some(Effect::Error(status, code, retryable)) => {
                self.clock.advance(latency);
                let body = json!({
                    "error": {"code": code, "retryable": retryable, "message": "m", "details": {}},
                    "correlation_id": "corr-err",
                });
                return Ok(HttpResponse {
                    status,
                    retry_after: None,
                    body: body.to_string().into_bytes(),
                });
            }
            Some(Effect::Serve(body)) => {
                self.clock.advance(latency);
                return ok(&body);
            }
            Some(Effect::Hook(hook)) => hook(),
            Some(Effect::LoseAnswer) => lose_answer = true,
            Some(Effect::Block) => {
                while !cancel.is_cancelled() {
                    std::thread::sleep(Duration::from_millis(2));
                }
                return Err(TransportFailure::Cancelled);
            }
            None => {}
        }
        self.clock.advance(latency);
        let answer = self.model.lock().unwrap().handle(&route, &params, request);
        if lose_answer {
            self.clock.advance(request.timeout);
            return Err(TransportFailure::Timeout);
        }
        answer
    }
}

impl Model {
    fn handle(
        &mut self,
        route: &str,
        params: &[(String, String)],
        request: &HttpRequest,
    ) -> Result<HttpResponse, TransportFailure> {
        match route {
            "GET capabilities" => ok(&self.common(json!({
                "protocol_versions": [1],
                "command_versions": [],
                "rule_version": 1,
                "projection_schema_version": 1,
                "storage_epoch": 1,
                "feed_generation": "feed-1",
                "scope_enabled": true,
                "limits": {},
                "recovery": {},
            }))),
            "POST devices" => {
                let body: Value = serde_json::from_slice(request.body.as_ref().unwrap()).unwrap();
                ok(&self.common(json!({
                    "device_id": body["device_id"],
                    "device_epoch": body["device_epoch"],
                    "epoch_status": "active",
                })))
            }
            "POST commands" => {
                let body: Value = serde_json::from_slice(request.body.as_ref().unwrap()).unwrap();
                let id = body["command_id"].as_str().unwrap().to_string();
                if let Some(seq) = self.commands.get(&id) {
                    return ok(&self.receipt(&id, *seq));
                }
                let task = body["entity_id"].as_str().unwrap().to_string();
                let title = body["payload"]["title"]
                    .as_str()
                    .unwrap_or("untitled")
                    .to_string();
                let revision = self
                    .tasks
                    .get(&task)
                    .map_or(1, |(_, revision)| revision + 1);
                let seq = self.commit(&id, &task, &title, revision);
                self.commands.insert(id.clone(), seq);
                ok(&self.receipt(&id, seq))
            }
            "GET commands/*" => {
                let id = request
                    .path
                    .split('?')
                    .next()
                    .unwrap()
                    .rsplit('/')
                    .next()
                    .unwrap();
                match self.commands.get(id) {
                    Some(seq) => ok(&self.common(json!({
                        "status": "terminal",
                        "receipt": self.receipt(id, *seq),
                    }))),
                    None => ok(&self.common(json!({"status": "not_found", "command_id": id}))),
                }
            }
            "GET changes" => {
                let limit: usize = param(params, "limit").parse().unwrap();
                ok(&self.page(&param(params, "cursor"), limit))
            }
            "POST snapshots" => {
                let (manifest, pages) = self.snapshot_fixture();
                self.snapshot = Some(vec![manifest.clone(), json!(pages)]);
                ok(&manifest)
            }
            "GET snapshots/*" => {
                let token = param(params, "page_token");
                let index: usize = token.strip_prefix("token-").unwrap().parse().unwrap();
                let stored = self.snapshot.clone().unwrap();
                ok(&stored[1][index])
            }
            other => panic!("unmodelled route {other}"),
        }
    }
}

/// A round that drives the sim clock past any backoff, so it never depends on
/// wall time.
fn later(world: &World, seconds: u64) {
    world.clock.advance(Duration::from_secs(seconds));
}

fn halt_of(report: &bb_client::RoundReport) -> Option<Halt> {
    report.halt.clone()
}

// ============================================================ sends and retries

mod sends {
    use super::*;

    /// A command whose answer was lost is not resent blind: it is looked up, and a
    /// committed one settles from its receipt, so the mutation happens once.
    #[test]
    fn transport_026_fr_005_a_lost_answer_is_looked_up_and_never_committed_twice() {
        let world = World::new();
        let mut store = linked(&scratch("lost-answer"));
        let mut syncer = world.syncer(&mut store, Schedule::default());
        create_task(&mut store, &mut SeqIds(0), 1, "Write the estimate");
        world.fault("POST commands", Effect::LoseAnswer);

        let first = syncer.round(&mut store);
        assert!(first.registered, "the pending epoch registers first");
        assert_eq!(first.halt, Some(Halt::Offline));
        assert_eq!(
            state_of(&mut store, 1),
            "unknown",
            "possibly sent, not forgotten"
        );
        assert_eq!(world.model().seq(), 1, "the server did commit it");
        assert!(first.send_retry_at.is_some());

        later(&world, 120);
        // The feed has not caught up with the commit yet: only a lookup proves it.
        let behind = world.common_json(json!({
            "from_cursor": "cursor-0", "transactions": [], "has_more": false,
            "next_cursor": "cursor-0", "high_watermark": "0",
        }));
        world.fault("GET changes", Effect::Serve(behind));
        let second = syncer.round(&mut store);
        assert_eq!(second.halt, None);
        assert_eq!(second.looked_up, 1);
        assert_eq!(
            world.count("POST commands"),
            1,
            "never posted a second time"
        );
        assert_eq!(world.model().seq(), 1, "one commit");
        assert_ne!(state_of(&mut store, 1), "unknown");
    }

    /// The server has no record at lookup time: the same immutable envelope goes
    /// again, byte for byte, under the same command ID.
    #[test]
    fn transport_026_fr_005_an_unknown_command_is_resent_with_the_same_envelope() {
        let world = World::new();
        let mut store = linked(&scratch("resend"));
        let mut syncer = world.syncer(&mut store, Schedule::default());
        create_task(&mut store, &mut SeqIds(0), 1, "Same bytes");
        world.fault("POST commands", Effect::Lose);

        let first = syncer.round(&mut store);
        assert_eq!(first.halt, Some(Halt::Offline));
        later(&world, 120);
        let second = syncer.round(&mut store);
        assert_eq!(second.halt, None);

        let posts = world.requests("POST commands");
        assert_eq!(posts.len(), 2);
        assert_eq!(posts[0], posts[1], "the immutable envelope, byte for byte");
        assert_eq!(world.count("GET commands/*"), 1, "a lookup came between");
        assert_eq!(world.model().seq(), 1);
    }

    /// Exponential backoff with jitter, `Retry-After` honoured, and a bound after
    /// which a command is parked until a foreground wake.
    #[test]
    fn transport_026_fr_005_send_failures_back_off_honour_retry_after_and_park() {
        let world = World::new();
        let mut store = linked(&scratch("backoff"));
        let schedule = Schedule::default();
        let mut syncer = world.syncer(&mut store, schedule.clone());
        create_task(&mut store, &mut SeqIds(0), 1, "Backing off");

        let mut delays = Vec::new();
        for attempt in 0..schedule.max_send_attempts {
            if attempt == 1 {
                world.fault("POST commands", Effect::Status(429, Some(45)));
            } else {
                world.fault("POST commands", Effect::Status(503, None));
            }
            // A lookup precedes a retry; it finds nothing.
            let started = world.clock.at();
            let report = syncer.round(&mut store);
            assert!(
                matches!(report.halt, Some(Halt::Retry { .. })),
                "attempt {attempt}"
            );
            let until = report.send_retry_at.expect("a backoff");
            delays.push(until - world.clock.at().min(until));
            assert!(until >= started);
            // Inside the backoff nothing is sent.
            let sent_before = world.count("POST commands");
            let early = syncer.round(&mut store);
            assert_eq!(world.count("POST commands"), sent_before, "backing off");
            assert_eq!(early.send_retry_at, Some(until));
            world
                .clock
                .advance(until - world.clock.at() + Duration::from_millis(1));
        }
        let ceiling = |n: u32| {
            schedule
                .send_backoff_base
                .saturating_mul(2u32.pow(n))
                .min(schedule.send_backoff_cap)
        };
        // Delay n lies in [ceiling(n)/2, ceiling(n)] (the 429 asked for 45 s).
        for (n, delay) in delays.iter().enumerate() {
            let n = n as u32;
            if n == 1 {
                assert!(
                    *delay >= Duration::from_secs(44),
                    "Retry-After honoured: {delay:?}"
                );
            } else {
                assert!(
                    *delay <= ceiling(n) + Duration::from_millis(250),
                    "n={n} {delay:?}"
                );
                assert!(
                    *delay >= ceiling(n) / 2 - Duration::from_millis(250),
                    "n={n} {delay:?}"
                );
            }
        }
        assert_eq!(world.count("POST commands"), 5, "bounded attempts");

        // Parked: even long after, nothing is sent until a foreground resumes it.
        later(&world, 3_600);
        let idle = syncer.round(&mut store);
        assert_eq!(idle.sent, 0);
        assert_eq!(world.count("POST commands"), 5);
        syncer.resume();
        let resumed = syncer.round(&mut store);
        assert_eq!(resumed.halt, None);
        assert_eq!(world.count("POST commands"), 6);
    }

    /// A dependent waits for its predecessor; independent work flows meanwhile.
    #[test]
    fn transport_026_fr_005_a_dependent_waits_while_independent_work_proceeds() {
        let world = World::new();
        let mut store = linked(&scratch("dependency"));
        let mut syncer = world.syncer(&mut store, Schedule::default());
        let mut ids = SeqIds(0);
        let task = create_task(&mut store, &mut ids, 1, "Parent");
        edit_after(&mut store, &mut ids, 2, 1, &task, "Child edit");
        create_task(&mut store, &mut ids, 3, "Independent");

        // The parent's send fails: its dependant must not go out.
        world.fault("POST commands", Effect::Status(503, None));
        let blocked = syncer.round(&mut store);
        assert!(matches!(blocked.halt, Some(Halt::Retry { .. })));
        let bodies: Vec<String> = world
            .requests("POST commands")
            .into_iter()
            .map(|body| String::from_utf8(body.unwrap()).unwrap())
            .collect();
        assert_eq!(bodies.len(), 1);
        assert!(bodies[0].contains(cmd(1).as_str()), "the parent was tried");

        later(&world, 120);
        let flowing = syncer.round(&mut store);
        assert_eq!(flowing.halt, None);
        let order: Vec<String> = world
            .requests("POST commands")
            .into_iter()
            .skip(1)
            .map(|body| {
                let value: Value = serde_json::from_slice(&body.unwrap()).unwrap();
                value["command_id"].as_str().unwrap().to_string()
            })
            .collect();
        assert_eq!(
            order,
            [cmd(1), cmd(2), cmd(3)]
                .iter()
                .map(|id| id.as_str().to_string())
                .collect::<Vec<_>>(),
            "local order, the dependant only after its predecessor settled"
        );
        assert_eq!(world.model().seq(), 3);
    }

    /// Sends per round are bounded; the rest is reported, not dropped.
    #[test]
    fn transport_026_fr_005_sends_per_round_are_bounded_and_the_rest_continues() {
        let world = World::new();
        let mut store = linked(&scratch("bounded"));
        let mut syncer = world.syncer(&mut store, Schedule::default());
        let mut ids = SeqIds(0);
        for n in 1..=30 {
            create_task(&mut store, &mut ids, n, &format!("Task {n}"));
        }
        let first = syncer.round(&mut store);
        assert_eq!(first.sent, 20);
        assert!(first.more_sends);
        let second = syncer.round(&mut store);
        assert_eq!(second.sent, 10);
        assert!(!second.more_sends);
        assert_eq!(world.model().seq(), 30);
    }

    /// 401 pauses; nothing in the outbox is destroyed and no further request is made.
    #[test]
    fn transport_026_fr_011_unauthorized_pauses_without_touching_the_queue() {
        let world = World::new();
        let mut store = linked(&scratch("auth"));
        let mut syncer = world.syncer(&mut store, Schedule::default());
        create_task(&mut store, &mut SeqIds(0), 1, "Waiting for sign-in");
        world.fault("GET changes", Effect::Status(401, None));
        let report = syncer.round(&mut store);
        assert_eq!(halt_of(&report), Some(Halt::AuthRequired));
        assert_eq!(state_of(&mut store, 1), "queued");
        let requests = world.count("GET changes");
        let again = syncer.round(&mut store);
        assert_eq!(halt_of(&again), Some(Halt::AuthRequired));
        assert_eq!(
            world.count("GET changes"),
            requests,
            "no authority, no request"
        );
    }

    /// An unsupported protocol stops sync and writes nothing.
    #[test]
    fn transport_026_fr_012_upgrade_required_stops_sync_and_keeps_the_queue() {
        let world = World::new();
        let mut store = linked(&scratch("upgrade"));
        let mut syncer = world.syncer(&mut store, Schedule::default());
        create_task(&mut store, &mut SeqIds(0), 1, "Needs a newer build");
        world.fault("GET changes", Effect::Error(426, "UPGRADE_REQUIRED", false));
        let report = syncer.round(&mut store);
        assert_eq!(halt_of(&report), Some(Halt::UpdateRequired));
        assert_eq!(state_of(&mut store, 1), "queued");
        assert_eq!(world.count("POST commands"), 0);
        assert_eq!(cursor_of(&mut store).as_deref(), Some("cursor-0"));
    }
}

// ================================================================== pulls

mod pulls {
    use super::*;

    fn external_tasks(world: &World, n: u64) {
        let mut model = world.model();
        for index in 1..=n {
            model.commit_external(&format!("task_ext_{index}"), &format!("Server {index}"));
        }
    }

    /// Pages are fetched until the feed is drained, each applied whole.
    #[test]
    fn transport_026_fr_004_a_pull_drains_the_feed_page_by_page() {
        let world = World::new();
        let mut store = linked(&scratch("drain"));
        external_tasks(&world, 5);
        let schedule = Schedule {
            page_limit: 2,
            ..Schedule::default()
        };
        let mut syncer = world.syncer(&mut store, schedule);
        let report = syncer.pull(&mut store);
        assert_eq!(report.halt, None);
        assert_eq!(report.transactions, 5);
        assert_eq!(report.requests, 3);
        assert!(report.changes.records);
        assert_eq!(cursor_of(&mut store).as_deref(), Some("cursor-5"));
        assert_eq!(confirmed_titles(&mut store).len(), 5);
    }

    /// A repeated page changes nothing and does not break the pull.
    #[test]
    fn transport_026_fr_004_a_duplicate_page_is_harmless() {
        let world = World::new();
        let mut store = linked(&scratch("duplicate"));
        external_tasks(&world, 2);
        let mut syncer = world.syncer(&mut store, Schedule::default());
        let stale = world.model().page("cursor-0", 100);
        assert_eq!(syncer.pull(&mut store).transactions, 2);
        world.fault("GET changes", Effect::Serve(stale));
        let again = syncer.pull(&mut store);
        assert_eq!(again.halt, None);
        assert_eq!(again.transactions, 0, "already in the base");
        assert_eq!(cursor_of(&mut store).as_deref(), Some("cursor-2"));
        assert_eq!(confirmed_titles(&mut store).len(), 2);
    }

    /// A page that skips a transaction cannot be applied: the base is rebuilt from
    /// a snapshot, and saved work survives it.
    #[test]
    fn transport_026_fr_010_a_gap_rebuilds_from_a_snapshot_and_keeps_pending_work() {
        let world = World::new();
        let mut store = linked(&scratch("gap"));
        create_task(&mut store, &mut SeqIds(0), 1, "Typed offline");
        external_tasks(&world, 3);
        let mut syncer = world.syncer(&mut store, Schedule::default());
        // Reordered feed: the server answers from transaction 3 first.
        let late = {
            let mut page = world.model().page("cursor-2", 100);
            page["from_cursor"] = json!("cursor-0");
            page
        };
        world.fault("GET changes", Effect::Serve(late));
        let report = syncer.pull(&mut store);
        assert_eq!(report.halt, None, "{report:?}");
        assert_eq!(report.snapshots, 1);
        assert_eq!(cursor_of(&mut store).as_deref(), Some("cursor-3"));
        assert_eq!(confirmed_titles(&mut store).len(), 3);
        assert_eq!(
            state_of(&mut store, 1),
            "queued",
            "the typed task is untouched"
        );
    }

    /// `RESET_REQUIRED` from the feed resets, takes a snapshot and goes on.
    #[test]
    fn transport_026_fr_010_reset_required_recovers_through_a_snapshot() {
        let world = World::new();
        let mut store = linked(&scratch("reset"));
        external_tasks(&world, 2);
        let mut syncer = world.syncer(&mut store, Schedule::default());
        world.fault("GET changes", Effect::Error(409, "RESET_REQUIRED", false));
        let report = syncer.pull(&mut store);
        assert_eq!(report.halt, None, "{report:?}");
        assert_eq!(report.snapshots, 1);
        assert_eq!(cursor_of(&mut store).as_deref(), Some("cursor-2"));
        assert_eq!(confirmed_titles(&mut store), vec!["Server 1", "Server 2"]);
    }

    /// Timeouts and losses leave the store as it was; the next pull is normal.
    #[test]
    fn transport_026_fr_004_timeouts_and_losses_change_nothing_and_recover() {
        let world = World::new();
        let mut store = linked(&scratch("timeouts"));
        external_tasks(&world, 2);
        let mut syncer = world.syncer(&mut store, Schedule::default());
        world.fault("GET changes", Effect::Timeout);
        let lost = syncer.pull(&mut store);
        assert_eq!(lost.halt, Some(Halt::Offline));
        assert_eq!(cursor_of(&mut store).as_deref(), Some("cursor-0"));
        world.fault("GET changes", Effect::Lose);
        assert_eq!(syncer.pull(&mut store).halt, Some(Halt::Offline));
        world.fault("GET changes", Effect::Status(503, Some(2)));
        assert!(matches!(
            syncer.pull(&mut store).halt,
            Some(Halt::Retry { after: Some(_) })
        ));
        let fine = syncer.pull(&mut store);
        assert_eq!(fine.halt, None);
        assert_eq!(fine.transactions, 2);
    }

    /// A pull stops starting requests once its budget is spent and says so, so
    /// requests plus application stay inside the catch-up window.
    #[test]
    fn transport_026_sc_004_a_pull_is_budgeted_and_continues_without_waiting() {
        let world = World::new();
        let mut store = linked(&scratch("budget"));
        external_tasks(&world, 40);
        *world.latency.lock().unwrap() = Duration::from_secs(8);
        let schedule = Schedule {
            page_limit: 1,
            ..Schedule::default()
        };
        assert!(schedule.fits_catch_up_window());
        let mut syncer = world.syncer(&mut store, schedule.clone());
        let started = world.clock.at();
        let report = syncer.pull(&mut store);
        let spent = world.clock.at() - started;
        assert!(report.more, "{report:?}");
        assert!(
            spent <= schedule.pull_budget + schedule.request_timeout,
            "{spent:?} exceeds the catch-up window"
        );
        assert!(report.transactions >= 1 && report.transactions < 40);
    }

    /// A late answer for an old session never reaches the workspace: another
    /// process starting a new session fences the in-flight page.
    #[test]
    fn transport_026_fr_011_a_late_answer_from_an_old_session_is_ignored() {
        let world = World::new();
        let path = scratch("stale");
        let mut store = linked(&path);
        external_tasks(&world, 2);
        let mut syncer = world.syncer(&mut store, Schedule::default());
        let other = path.clone();
        world.fault(
            "GET changes",
            Effect::Hook(Box::new(move || {
                let mut elsewhere = open(&other);
                elsewhere
                    .write(|tx| {
                        tx.execute(
                            "UPDATE sync_meta SET session_generation = session_generation + 1",
                            params![],
                        )?;
                        Ok(())
                    })
                    .unwrap();
            })),
        );
        let report = syncer.pull(&mut store);
        assert_eq!(report.halt, Some(Halt::Stale), "{report:?}");
        assert_eq!(cursor_of(&mut store).as_deref(), Some("cursor-0"));
        assert!(
            confirmed_titles(&mut store).is_empty(),
            "nothing of the old answer"
        );
    }

    /// Closing cancels the call in flight and the answer, whenever it comes,
    /// counts for nothing. The saved command survives.
    #[test]
    fn transport_026_fr_011_close_cancels_the_call_in_flight_and_keeps_saved_work() {
        let world = World::new();
        let path = scratch("close");
        let mut store = linked(&path);
        let mut syncer = world.syncer(&mut store, Schedule::default());
        create_task(&mut store, &mut SeqIds(0), 1, "Survives a close");
        world.fault("GET capabilities", Effect::Block);
        let closing = syncer.closing_flag();
        let handle = std::thread::spawn(move || {
            let report = syncer.round(&mut store);
            (report, store)
        });
        std::thread::sleep(Duration::from_millis(50));
        closing.store(true, Ordering::SeqCst);
        let (report, mut store) = handle.join().unwrap();
        assert_eq!(report.halt, Some(Halt::Cancelled));
        assert_eq!(state_of(&mut store, 1), "queued");
        assert_eq!(world.count("POST commands"), 0);
    }
}

// ============================================================ the poll schedule

mod schedule {
    use super::*;

    fn secs(n: u64) -> Duration {
        Duration::from_secs(n)
    }

    /// Fallback polls start at most 30 seconds apart however jitter falls, and
    /// jitter only ever shortens the interval.
    #[test]
    fn transport_026_sc_004_polls_start_at_most_thirty_seconds_apart_with_jitter() {
        let schedule = Schedule::default();
        assert!(schedule.fits_catch_up_window());
        let mut scheduler = Scheduler::new(schedule.clone());
        let mut jitter = SplitMix::seeded(3);
        scheduler.wake(Wake::Foreground);
        let mut now = secs(100);
        assert_eq!(scheduler.next_action(now), Action::Pull(Wake::Foreground));
        scheduler.started(now, Wake::Foreground, &mut jitter);
        let mut previous_start = now;
        let (mut shortest, mut longest) = (secs(1_000), Duration::ZERO);
        for _ in 0..500 {
            let Action::Wait(left) = scheduler.next_action(now) else {
                panic!("a poll is not due yet");
            };
            now += left;
            assert_eq!(scheduler.next_action(now), Action::Pull(Wake::Poll));
            let gap = now - previous_start;
            shortest = shortest.min(gap);
            longest = longest.max(gap);
            assert!(gap <= secs(30), "{gap:?}");
            assert!(gap >= secs(25), "{gap:?}");
            scheduler.started(now, Wake::Poll, &mut jitter);
            previous_start = now;
            scheduler.finished(
                now + secs(1),
                &bb_client::RoundReport::default(),
                &mut jitter,
            );
        }
        assert!(shortest < longest, "jitter varies the interval");
    }

    /// The schedule counts from the previous poll's *start*, not its completion.
    #[test]
    fn transport_026_sc_004_the_next_poll_counts_from_the_previous_start() {
        let mut scheduler = Scheduler::new(Schedule::default());
        let mut jitter = SplitMix::seeded(5);
        scheduler.wake(Wake::Foreground);
        scheduler.started(secs(0), Wake::Foreground, &mut jitter);
        let due = scheduler.next_poll().unwrap();
        // The pull takes 20 s; the poll is due 5 to 10 s after it ends.
        scheduler.finished(secs(20), &bb_client::RoundReport::default(), &mut jitter);
        assert_eq!(scheduler.next_poll(), Some(due), "completion moved nothing");
        assert!(due <= secs(30));
    }

    /// A hint (or many) coalesces into one pull and never postpones the poll.
    #[test]
    fn transport_026_fr_004_hints_coalesce_and_never_move_the_poll_deadline() {
        let mut scheduler = Scheduler::new(Schedule::default());
        let mut jitter = SplitMix::seeded(9);
        scheduler.wake(Wake::Foreground);
        scheduler.started(secs(0), Wake::Foreground, &mut jitter);
        scheduler.finished(secs(1), &bb_client::RoundReport::default(), &mut jitter);
        let due = scheduler.next_poll().unwrap();
        for _ in 0..20 {
            scheduler.wake(Wake::Hint);
        }
        assert_eq!(scheduler.next_action(secs(3)), Action::Pull(Wake::Hint));
        scheduler.started(secs(3), Wake::Hint, &mut jitter);
        scheduler.finished(secs(4), &bb_client::RoundReport::default(), &mut jitter);
        assert_eq!(
            scheduler.next_poll(),
            Some(due),
            "a hint pull is not a poll"
        );
        assert!(
            matches!(scheduler.next_action(secs(5)), Action::Wait(_)),
            "one pull absorbed all 20"
        );
    }

    /// Foreground and network return pull at once; offline and background do not.
    #[test]
    fn transport_026_fr_004_foreground_and_network_return_pull_immediately() {
        let mut scheduler = Scheduler::new(Schedule::default());
        let mut jitter = SplitMix::seeded(1);
        assert_eq!(scheduler.next_action(secs(0)), Action::Idle, "inactive");
        scheduler.wake(Wake::Foreground);
        assert_eq!(
            scheduler.next_action(secs(0)),
            Action::Pull(Wake::Foreground)
        );
        scheduler.started(secs(0), Wake::Foreground, &mut jitter);
        scheduler.finished(secs(1), &bb_client::RoundReport::default(), &mut jitter);
        scheduler.set_offline();
        assert_eq!(
            scheduler.next_action(secs(100)),
            Action::Idle,
            "no polls offline"
        );
        scheduler.wake(Wake::NetworkReturn);
        assert_eq!(
            scheduler.next_action(secs(101)),
            Action::Pull(Wake::NetworkReturn)
        );
        scheduler.started(secs(101), Wake::NetworkReturn, &mut jitter);
        scheduler.set_inactive();
        scheduler.wake(Wake::Hint);
        assert_eq!(
            scheduler.next_action(secs(200)),
            Action::Idle,
            "background: no hint pulls"
        );
    }

    /// A failing pull backs hint-driven pulls off, but the scheduled poll starts on
    /// time regardless.
    #[test]
    fn transport_026_sc_004_failures_delay_hint_pulls_but_not_the_poll() {
        let mut scheduler = Scheduler::new(Schedule::default());
        let mut jitter = SplitMix::seeded(2);
        scheduler.wake(Wake::Foreground);
        scheduler.started(secs(0), Wake::Foreground, &mut jitter);
        let failed = bb_client::RoundReport {
            halt: Some(Halt::Offline),
            ..Default::default()
        };
        scheduler.finished(secs(8), &failed, &mut jitter);
        let due = scheduler.next_poll().unwrap();
        scheduler.wake(Wake::Hint);
        assert!(
            matches!(scheduler.next_action(secs(8)), Action::Wait(_)),
            "backing off"
        );
        assert_eq!(
            scheduler.next_action(due),
            Action::Pull(Wake::Poll),
            "the poll is not delayed"
        );
    }

    /// A sign-out or update requirement stops the schedule until a wake.
    #[test]
    fn transport_026_fr_011_authorization_loss_pauses_polling_until_a_wake() {
        let mut scheduler = Scheduler::new(Schedule::default());
        let mut jitter = SplitMix::seeded(4);
        scheduler.wake(Wake::Foreground);
        scheduler.started(secs(0), Wake::Foreground, &mut jitter);
        let report = bb_client::RoundReport {
            halt: Some(Halt::AuthRequired),
            ..Default::default()
        };
        scheduler.finished(secs(1), &report, &mut jitter);
        assert!(scheduler.is_paused());
        assert_eq!(scheduler.next_action(secs(500)), Action::Idle);
        scheduler.wake(Wake::Foreground);
        assert!(!scheduler.is_paused());
    }

    /// SC-004: with every hint dropped, an update committed at any moment of the
    /// poll cycle is applied and visible within 60 seconds of its commit.
    #[test]
    fn transport_026_sc_004_a_commit_is_visible_within_sixty_seconds_without_hints() {
        for offset_ms in (0..=31_000).step_by(1_000) {
            let world = World::new();
            let mut store = linked(&scratch("deadline"));
            let schedule = Schedule::default();
            let syncer = world.syncer(&mut store, schedule);
            let mut worker = SyncLoop::new(
                syncer,
                Waker::new(),
                InvalidationHub::new(4),
                Arc::new(world.clock.clone()),
                Box::new(SplitMix::seeded(offset_ms)),
            );
            worker.waker().post(Wake::Foreground);
            // The first round starts the schedule.
            let Step::Ran { .. } = worker.step(&mut store) else {
                panic!("the foreground round runs");
            };
            let anchor = world.clock.at();
            let commit_at = anchor + Duration::from_millis(offset_ms);
            let mut committed = false;
            let mut visible_at = None;
            for _ in 0..200 {
                if !committed && world.clock.at() >= commit_at {
                    world
                        .model()
                        .commit_external("task_ext_1", "Committed elsewhere");
                    committed = true;
                    // The deadline counts from here.
                }
                match worker.step(&mut store) {
                    Step::Ran { .. } => {
                        if committed
                            && visible_at.is_none()
                            && !confirmed_titles(&mut store).is_empty()
                        {
                            visible_at = Some(world.clock.at());
                        }
                    }
                    Step::Wait(left) => {
                        let until_commit = commit_at.saturating_sub(world.clock.at());
                        let step = if committed || until_commit.is_zero() {
                            left
                        } else {
                            left.min(until_commit)
                        };
                        world.clock.advance(step.max(Duration::from_millis(1)));
                    }
                    Step::Idle => panic!("an active, online loop is never idle"),
                }
                if visible_at.is_some() {
                    break;
                }
            }
            let commit_time = commit_at;
            let visible = visible_at.expect("the update became visible");
            assert!(
                visible - commit_time <= Duration::from_secs(60),
                "offset {offset_ms} ms: visible after {:?}",
                visible - commit_time
            );
        }
    }

    /// A hint, by contrast, wakes the very next step: catch-up in one round trip.
    #[test]
    fn transport_026_fr_004_a_hint_wakes_a_pull_that_applies_the_commit_at_once() {
        let world = World::new();
        let mut store = linked(&scratch("hinted"));
        let syncer = world.syncer(&mut store, Schedule::default());
        let waker = Waker::new();
        let mut worker = SyncLoop::new(
            syncer,
            waker.clone(),
            InvalidationHub::new(4),
            Arc::new(world.clock.clone()),
            Box::new(SplitMix::seeded(8)),
        );
        waker.post(Wake::Foreground);
        let Step::Ran { .. } = worker.step(&mut store) else {
            panic!()
        };
        let poll = worker.scheduler().next_poll();
        world.model().commit_external("task_ext_1", "Hinted");
        assert!(
            matches!(worker.step(&mut store), Step::Wait(_)),
            "nothing wakes it yet"
        );
        waker.post(Wake::Hint);
        waker.post(Wake::Hint);
        let before = world.clock.at();
        let Step::Ran { reason, report } = worker.step(&mut store) else {
            panic!()
        };
        assert_eq!(reason, Wake::Hint);
        assert_eq!(report.pull.transactions, 1);
        assert!(world.clock.at() - before < Duration::from_secs(2));
        assert_eq!(
            worker.scheduler().next_poll(),
            poll,
            "the poll deadline is unchanged"
        );
        assert_eq!(confirmed_titles(&mut store), vec!["Hinted"]);
    }
}

// ===================================================================== the SSE

mod sse {
    use super::*;

    /// The exact bytes `HintHub._event` writes, and the heartbeat comment.
    const HEARTBEAT: &[u8] = b": keep-alive\n\n";

    fn event(scope: &str, generation: &str) -> Vec<u8> {
        format!(
            "event: scope_changed\ndata: {{\"scope_id\":\"{scope}\",\"server_generation\":\"{generation}\",\"feed_generation\":\"feed-1\",\"server_now\":\"2026-10-10T09:00:00+00:00\",\"correlation_id\":\"corr-9\"}}\n\n"
        )
        .into_bytes()
    }

    fn hints(items: &[SseItem]) -> usize {
        items
            .iter()
            .filter(|item| matches!(item, SseItem::Hint(_)))
            .count()
    }

    fn parse_all(bytes: &[u8]) -> Vec<SseItem> {
        SseParser::new().feed(bytes).unwrap()
    }

    #[test]
    fn transport_026_fr_004_the_publishers_frames_parse_byte_exact() {
        let mut stream = event(SCOPE, GENERATION);
        stream.extend_from_slice(HEARTBEAT);
        stream.extend_from_slice(&event(SCOPE, GENERATION));
        let items = parse_all(&stream);
        assert_eq!(items.len(), 3);
        let SseItem::Hint(first) = &items[0] else {
            panic!("{items:?}")
        };
        assert_eq!(first.scope_id.as_str(), SCOPE);
        assert_eq!(first.server_generation.as_str(), GENERATION);
        assert_eq!(items[1], SseItem::Comment);
        assert_eq!(
            hints(&items),
            2,
            "duplicates are two events; coalescing is the waker's job"
        );
    }

    /// Any split of the byte stream gives the same events.
    #[test]
    fn transport_026_fr_004_any_chunking_gives_the_same_events() {
        let mut stream = event(SCOPE, GENERATION);
        stream.extend_from_slice(HEARTBEAT);
        stream.extend_from_slice(&event(SCOPE, "generation-2"));
        let whole = parse_all(&stream);
        for split in 1..stream.len() {
            let mut parser = SseParser::new();
            let mut items = parser.feed(&stream[..split]).unwrap();
            items.extend(parser.feed(&stream[split..]).unwrap());
            assert_eq!(items, whole, "split at {split}");
        }
        let mut parser = SseParser::new();
        let mut bytewise = Vec::new();
        for byte in &stream {
            bytewise.extend(parser.feed(std::slice::from_ref(byte)).unwrap());
        }
        assert_eq!(bytewise, whole);
    }

    /// CRLF and CR line ends, comments mid-event, and a leading BOM are all SSE.
    #[test]
    fn transport_026_fr_004_line_ends_comments_and_bom_follow_the_sse_rules() {
        let body = String::from_utf8(event(SCOPE, GENERATION)).unwrap();
        let crlf = body.replace('\n', "\r\n").into_bytes();
        assert_eq!(hints(&parse_all(&crlf)), 1);
        let cr = body.replace('\n', "\r").into_bytes();
        assert_eq!(hints(&parse_all(&cr)), 1);
        let mut bom = b"\xEF\xBB\xBF".to_vec();
        bom.extend_from_slice(body.as_bytes());
        assert_eq!(hints(&parse_all(&bom)), 1);
        let with_id = body.replacen("event:", "id: 7\nretry: 5\n: note\nevent:", 1);
        let items = parse_all(with_id.as_bytes());
        assert_eq!(
            hints(&items),
            1,
            "id and retry carry no position or authority"
        );
        assert!(items.contains(&SseItem::Comment));
    }

    /// Anything but a well-formed content-free `scope_changed` is ignored: a stray
    /// key, another event name, bad JSON.
    #[test]
    fn transport_026_fr_004_malformed_or_unknown_events_never_wake_anything() {
        let extra = br#"event: scope_changed
data: {"scope_id":"s","server_generation":"g","feed_generation":"f","server_now":"2026-10-10T09:00:00+00:00","correlation_id":"c","title":"secret"}

"#;
        let mut parser = SseParser::new();
        assert_eq!(parser.feed(extra).unwrap(), vec![SseItem::Ignored]);
        assert_eq!(parser.ignored(), 1);
        assert_eq!(
            parse_all(b"event: other\ndata: {}\n\n"),
            vec![SseItem::Ignored]
        );
        assert_eq!(
            parse_all(b"event: scope_changed\ndata: not json\n\n"),
            vec![SseItem::Ignored]
        );
        assert!(
            parse_all(b"event: scope_changed\n\n").is_empty(),
            "no data, no event"
        );
    }

    #[test]
    fn transport_026_fr_004_a_runaway_stream_is_refused_not_buffered() {
        let mut parser = SseParser::new();
        let junk = vec![b'x'; SSE_MAX_EVENT_BYTES + 1];
        assert!(parser.feed(&junk).is_err());
        let mut parser = SseParser::new();
        let mut result = Ok(Vec::new());
        for _ in 0..(SSE_MAX_EVENT_BYTES / 4) {
            result = parser.feed(b"data: aaaa\n");
            if result.is_err() {
                break;
            }
        }
        assert!(result.is_err(), "unbounded data lines are refused");
    }

    // ------------------------------------------------------- the watcher state machine

    enum Script {
        Open(Vec<Result<Vec<u8>, StreamFailure>>),
        Fail(StreamFailure),
    }

    struct Scripted {
        scripts: Mutex<VecDeque<Script>>,
        clock: SimClock,
        opens: Mutex<Vec<String>>,
        lifetimes: Mutex<VecDeque<Duration>>,
    }

    struct Reader {
        chunks: VecDeque<Result<Vec<u8>, StreamFailure>>,
        clock: SimClock,
        lived: Duration,
    }

    impl HintReader for Reader {
        fn read(
            &mut self,
            buffer: &mut [u8],
            _cancel: &Cancellation<'_>,
        ) -> Result<usize, StreamFailure> {
            self.clock.advance(self.lived);
            self.lived = Duration::ZERO;
            match self.chunks.pop_front() {
                None => Ok(0),
                Some(Err(failure)) => Err(failure),
                Some(Ok(bytes)) => {
                    buffer[..bytes.len()].copy_from_slice(&bytes);
                    Ok(bytes.len())
                }
            }
        }
    }

    impl HintStream for Scripted {
        fn open(
            &self,
            path: &str,
            _idle: Duration,
            _cancel: &Cancellation<'_>,
        ) -> Result<Box<dyn HintReader>, StreamFailure> {
            self.opens.lock().unwrap().push(path.to_string());
            match self.scripts.lock().unwrap().pop_front() {
                Some(Script::Open(chunks)) => Ok(Box::new(Reader {
                    chunks: chunks.into(),
                    clock: self.clock.clone(),
                    lived: self
                        .lifetimes
                        .lock()
                        .unwrap()
                        .pop_front()
                        .unwrap_or_default(),
                })),
                Some(Script::Fail(failure)) => Err(failure),
                None => Err(StreamFailure::Cancelled),
            }
        }
    }

    fn watcher(
        scripts: Vec<Script>,
        lifetimes: Vec<Duration>,
    ) -> (HintWatcher, Waker, SimClock, Arc<Scripted>) {
        let clock = SimClock::new();
        let stream = Arc::new(Scripted {
            scripts: Mutex::new(scripts.into()),
            clock: clock.clone(),
            opens: Mutex::new(Vec::new()),
            lifetimes: Mutex::new(lifetimes.into()),
        });
        let waker = Waker::new();
        let watcher = HintWatcher::new(
            Arc::clone(&stream) as Arc<dyn HintStream>,
            waker.clone(),
            Id::parse(SCOPE).unwrap(),
            Arc::new(clock.clone()),
            Box::new(SplitMix::seeded(6)),
            &Schedule::default(),
        );
        (watcher, waker, clock, stream)
    }

    /// Opening asks for an immediate catch-up; duplicate events coalesce into one
    /// wake; another scope's event wakes nothing; the path carries no credential
    /// and no `Last-Event-ID`.
    #[test]
    fn transport_026_fr_004_open_catches_up_and_duplicate_hints_coalesce() {
        let mut chunks = vec![Ok(event(SCOPE, GENERATION)), Ok(HEARTBEAT.to_vec())];
        chunks.push(Ok(event(SCOPE, GENERATION)));
        chunks.push(Ok(event(SCOPE, GENERATION)));
        chunks.push(Ok(event("someone-else", GENERATION)));
        let (mut watcher, waker, _clock, stream) = watcher(vec![Script::Open(chunks)], vec![]);
        let end = watcher.connect_once();
        assert!(matches!(end, StreamEnd::Ended { hints: 3, .. }), "{end:?}");
        let woken = waker.drain();
        assert!(woken.contains(Wake::StreamOpened));
        assert!(woken.contains(Wake::Hint));
        assert_eq!(woken.iter().count(), 2, "one set, however many events");
        assert_eq!(
            stream.opens.lock().unwrap().as_slice(),
            [format!("/api/sync/v1/hints?scope_id={SCOPE}")],
        );
        assert_eq!(watcher.hints(), 3);
    }

    /// Reconnects: immediate after a stream that lived (the 15-minute cap or a
    /// generation closure), backing off with jitter and a cap when it fails.
    #[test]
    fn transport_026_fr_004_reconnect_is_immediate_after_a_good_stream_then_backs_off() {
        let schedule = Schedule::default();
        let (mut watcher, _waker, _clock, _stream) = watcher(vec![], vec![]);
        let lived = StreamEnd::Ended {
            lived: Duration::from_secs(900),
            hints: 3,
        };
        assert_eq!(watcher.reconnect_delay(lived), Duration::ZERO);
        let mut previous = Duration::ZERO;
        for failure in 0..12u32 {
            let delay = watcher.reconnect_delay(StreamEnd::NotOpened(StreamFailure::Connection));
            let ceiling = schedule
                .stream_backoff_base
                .saturating_mul(2u32.pow(failure.min(10)))
                .min(schedule.stream_backoff_cap);
            assert!(
                delay <= ceiling,
                "failure {failure}: {delay:?} > {ceiling:?}"
            );
            assert!(delay >= ceiling / 2, "failure {failure}: {delay:?}");
            assert!(delay <= Duration::from_secs(30), "bounded");
            assert!(delay + Duration::from_millis(1) >= previous / 2);
            previous = delay;
        }
        // A good stream resets the escalation.
        assert_eq!(watcher.reconnect_delay(lived), Duration::ZERO);
        let first = watcher.reconnect_delay(StreamEnd::NotOpened(StreamFailure::Timeout));
        assert!(first <= Duration::from_secs(1));
        // A stream that dies at once is a failure, not a success.
        let flapping = StreamEnd::Ended {
            lived: Duration::from_millis(5),
            hints: 0,
        };
        assert!(watcher.reconnect_delay(flapping) > Duration::ZERO);
    }

    /// Generation closure and the 15-minute cap are a clean end; the reopen asks for
    /// another immediate catch-up, and the not-admitted answers wait long.
    #[test]
    fn transport_026_fr_011_a_closed_stream_reopens_with_a_fresh_catch_up() {
        let scripts = vec![
            Script::Open(vec![Ok(event(SCOPE, GENERATION))]),
            Script::Fail(StreamFailure::Status(404)),
            Script::Open(vec![Ok(event(SCOPE, "generation-2"))]),
        ];
        let (mut watcher, waker, _clock, stream) = watcher(
            scripts,
            vec![
                Duration::from_secs(900),
                Duration::ZERO,
                Duration::from_secs(900),
            ],
        );
        let first = watcher.connect_once();
        assert!(matches!(first, StreamEnd::Ended { .. }));
        assert_eq!(watcher.reconnect_delay(first), Duration::ZERO);
        let drained = waker.drain();
        assert!(drained.contains(Wake::StreamOpened) && drained.contains(Wake::Hint));

        let refused = watcher.connect_once();
        assert_eq!(refused, StreamEnd::NotOpened(StreamFailure::Status(404)));
        assert!(watcher.reconnect_delay(refused) >= Duration::from_secs(1));
        assert!(waker.drain().is_empty(), "a refused stream wakes nothing");

        let reopened = watcher.connect_once();
        assert!(matches!(reopened, StreamEnd::Ended { hints: 1, .. }));
        assert!(
            waker.drain().contains(Wake::StreamOpened),
            "immediate catch-up on reopen"
        );
        assert_eq!(watcher.opened(), 2);
        assert_eq!(stream.opens.lock().unwrap().len(), 3);
    }

    /// Stopping releases the stream within one read and starts nothing new.
    #[test]
    fn transport_026_fr_011_stop_releases_the_stream() {
        let (mut watcher, _waker, _clock, stream) = watcher(
            vec![Script::Open(vec![Ok(event(SCOPE, GENERATION))])],
            vec![],
        );
        watcher.stop();
        assert_eq!(watcher.connect_once(), StreamEnd::Closed);
        assert!(
            stream.opens.lock().unwrap().is_empty(),
            "no stream was opened"
        );
        watcher.run();
    }
}

// ============================================================== invalidations

mod subscriptions {
    use super::*;
    use std::sync::atomic::AtomicUsize;

    fn records() -> Changes {
        Changes {
            records: true,
            ..Changes::default()
        }
    }

    /// A slow subscriber holds one invalidation: the latest generation, the union
    /// of kinds, and exactly one poke however many changes arrived.
    #[test]
    fn transport_026_fr_023_invalidations_coalesce_to_the_latest_for_a_slow_consumer() {
        let hub = InvalidationHub::new(4);
        let pokes = Arc::new(AtomicUsize::new(0));
        let counter = Arc::clone(&pokes);
        let subscription = hub
            .subscribe(
                [ChangeKind::Records, ChangeKind::Issues],
                true,
                Some(Arc::new(move || {
                    counter.fetch_add(1, Ordering::SeqCst);
                })),
            )
            .unwrap();
        for generation in 1..=50 {
            hub.publish(generation, &records());
        }
        hub.publish(
            51,
            &Changes {
                issues: true,
                status: true,
                ..Changes::default()
            },
        );
        assert_eq!(pokes.load(Ordering::SeqCst), 1, "one poke for the burst");
        let invalidation = subscription.take().expect("pending");
        assert_eq!(invalidation.projection_generation, 51);
        assert!(invalidation.changed_kinds.contains(&ChangeKind::Records));
        assert!(invalidation.changed_kinds.contains(&ChangeKind::Issues));
        assert!(invalidation.sync_status_changed);
        assert!(subscription.take().is_none(), "nothing queued behind it");
        hub.publish(52, &records());
        assert_eq!(pokes.load(Ordering::SeqCst), 2, "poked again once drained");
    }

    #[test]
    fn transport_026_fr_023_subscribers_see_only_what_they_asked_for_and_are_bounded() {
        let hub = InvalidationHub::new(2);
        let issues_only = hub.subscribe([ChangeKind::Issues], false, None).unwrap();
        let status_only = hub.subscribe([], true, None).unwrap();
        assert_eq!(
            hub.subscribe([ChangeKind::Records], false, None).err(),
            Some(SubscriptionError::TooMany)
        );
        hub.publish(1, &records());
        assert!(issues_only.take().is_none());
        assert!(status_only.take().is_none());
        hub.publish(
            2,
            &Changes {
                status: true,
                ..Changes::default()
            },
        );
        assert!(issues_only.take().is_none());
        assert!(status_only.take().unwrap().sync_status_changed);
        assert_eq!(hub.subscribers(), 2);
    }

    /// Unsubscribing, dropping and closing the hub all stop delivery, including a
    /// poke that was already queued behind the lock.
    #[test]
    fn transport_026_fr_011_close_releases_subscriptions_and_delivers_nothing_after() {
        let hub = InvalidationHub::new(4);
        let pokes = Arc::new(AtomicUsize::new(0));
        let counter = Arc::clone(&pokes);
        let kept = hub
            .subscribe(
                [ChangeKind::Records],
                false,
                Some(Arc::new(move || {
                    counter.fetch_add(1, Ordering::SeqCst);
                })),
            )
            .unwrap();
        let dropped = hub.subscribe([ChangeKind::Records], false, None).unwrap();
        drop(dropped);
        assert_eq!(hub.subscribers(), 1, "drop unsubscribes");
        kept.close();
        hub.publish(1, &records());
        assert_eq!(pokes.load(Ordering::SeqCst), 0);
        assert!(kept.take().is_none());
        assert!(!kept.is_live());
        assert_eq!(hub.subscribers(), 0);

        let late = hub.subscribe([ChangeKind::Records], false, None).unwrap();
        hub.publish(2, &records());
        hub.close();
        assert!(
            late.take().is_none(),
            "closed hub delivers nothing, even pending"
        );
        assert_eq!(
            hub.subscribe([ChangeKind::Records], false, None).err(),
            Some(SubscriptionError::Closed)
        );
        hub.publish(3, &records());
        assert!(late.take().is_none());
    }

    /// The loop publishes one invalidation per round, with the projection generation,
    /// and a changed stopping reason is a status change even with no record moving.
    #[test]
    fn transport_026_fr_023_a_round_publishes_one_coalesced_invalidation() {
        let world = World::new();
        let mut store = linked(&scratch("announce"));
        {
            let mut model = world.model();
            for n in 1..=4 {
                model.commit_external(&format!("task_ext_{n}"), &format!("Server {n}"));
            }
        }
        let syncer = world.syncer(&mut store, Schedule::default());
        let hub = InvalidationHub::new(4);
        let subscription = hub
            .subscribe([ChangeKind::Records, ChangeKind::Issues], true, None)
            .unwrap();
        let waker = Waker::new();
        let mut worker = SyncLoop::new(
            syncer,
            waker.clone(),
            hub.clone(),
            Arc::new(world.clock.clone()),
            Box::new(SplitMix::seeded(12)),
        );
        waker.post(Wake::Foreground);
        let Step::Ran { report, .. } = worker.step(&mut store) else {
            panic!()
        };
        assert_eq!(report.pull.transactions, 4);
        assert_eq!(hub.published(), 1, "four transactions, one publication");
        let invalidation = subscription.take().unwrap();
        assert!(invalidation.changed_kinds.contains(&ChangeKind::Records));
        assert!(subscription.take().is_none());
        // Offline: no record moves, but the status flips.
        world.fault("GET changes", Effect::Timeout);
        waker.post(Wake::Manual);
        let Step::Ran { .. } = worker.step(&mut store) else {
            panic!()
        };
        let status = subscription.take().expect("the stopping reason changed");
        assert!(status.sync_status_changed);
        assert!(status.changed_kinds.is_empty());
    }

    /// Closing the loop releases every subscriber, cancels what is in flight and
    /// leaves the durable queue alone.
    #[test]
    fn transport_026_fr_011_closing_the_loop_releases_subscribers_and_stops_sync() {
        let world = World::new();
        let mut store = linked(&scratch("loop-close"));
        create_task(&mut store, &mut SeqIds(0), 1, "Still saved");
        let syncer = world.syncer(&mut store, Schedule::default());
        let hub = InvalidationHub::new(4);
        let subscription = hub.subscribe([ChangeKind::Records], true, None).unwrap();
        let waker = Waker::new();
        let mut worker = SyncLoop::new(
            syncer,
            waker.clone(),
            hub.clone(),
            Arc::new(world.clock.clone()),
            Box::new(SplitMix::seeded(13)),
        );
        worker.close();
        assert!(!subscription.is_live());
        assert_eq!(hub.subscribers(), 0);
        waker.post(Wake::Foreground);
        let requests = world.model().log.len();
        let step = worker.step(&mut store);
        if let Step::Ran { report, .. } = step {
            assert_eq!(report.halt, Some(Halt::Cancelled));
        }
        assert_eq!(world.model().log.len(), requests, "no request after close");
        assert_eq!(state_of(&mut store, 1), "queued");
        worker.run(&mut store); // returns at once: closed
    }
}

// ============================================================ off the main thread

mod threading {
    use super::*;
    use std::thread::ThreadId;

    /// Records the thread every request is made from.
    struct Spy {
        inner: Controlled,
        threads: Arc<Mutex<Vec<ThreadId>>>,
    }

    impl Transport for Spy {
        fn send(
            &self,
            request: &HttpRequest,
            cancel: &Cancellation<'_>,
        ) -> Result<HttpResponse, TransportFailure> {
            self.threads
                .lock()
                .unwrap()
                .push(std::thread::current().id());
            self.inner.send(request, cancel)
        }
    }

    /// The worker does all store and network work on its own thread; the caller's
    /// thread only posts wakes, and closing ends the worker and releases it.
    #[test]
    fn transport_026_fr_004_background_application_never_touches_the_calling_thread() {
        let world = World::new();
        let mut store = linked(&scratch("threads"));
        world
            .model()
            .commit_external("task_ext_1", "Applied in the background");
        let session = SyncSession::start(
            &mut store,
            &SessionBinding {
                account_id: Id::parse(ACCOUNT).unwrap(),
                scope_id: Id::parse(SCOPE).unwrap(),
                device_id: Id::parse(DEVICE).unwrap(),
                authentication: Authentication::Fresh,
            },
        )
        .unwrap();
        let threads = Arc::new(Mutex::new(Vec::new()));
        let syncer = Syncer::new(
            Box::new(Spy {
                inner: world.transport(),
                threads: Arc::clone(&threads),
            }),
            session,
            Box::new(context),
            Arc::new(world.clock.clone()),
            Box::new(SplitMix::seeded(21)),
            Schedule::default(),
        );
        let waker = Waker::new();
        let hub = InvalidationHub::new(2);
        let subscription = hub.subscribe([ChangeKind::Records], false, None).unwrap();
        let mut worker = SyncLoop::new(
            syncer,
            waker.clone(),
            hub.clone(),
            Arc::new(world.clock.clone()),
            Box::new(SplitMix::seeded(22)),
        );
        let caller = std::thread::current().id();
        let handle = std::thread::spawn(move || {
            worker.run(&mut store);
            (worker, store)
        });
        waker.post(Wake::Foreground);
        let deadline = std::time::Instant::now() + Duration::from_secs(10);
        let mut seen = None;
        while std::time::Instant::now() < deadline && seen.is_none() {
            seen = subscription.take();
            std::thread::sleep(Duration::from_millis(5));
        }
        let invalidation = seen.expect("the background pull applied and announced the change");
        assert!(invalidation.changed_kinds.contains(&ChangeKind::Records));
        let used = threads.lock().unwrap().clone();
        assert!(!used.is_empty());
        assert!(
            used.iter().all(|id| *id != caller),
            "I/O ran on the calling thread"
        );

        // Close from the caller: the worker returns, subscribers are released.
        waker.close();
        let (mut worker, mut store) = handle.join().unwrap();
        worker.close();
        assert!(!subscription.is_live());
        assert_eq!(
            confirmed_titles(&mut store),
            vec!["Applied in the background"]
        );
    }
}
