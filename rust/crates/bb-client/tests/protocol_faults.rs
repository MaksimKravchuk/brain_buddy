//! Protocol fault replay (026 PR-54): the crash / loss / reorder / reset / restore
//! cases of sync-v1 section 10, run through the PR-40 `Syncer` against the real
//! backend process.
//!
//! The server is the production application (uvicorn, temporary data directory,
//! `rust_core_sync` on for the signed-in owner); only the wire between the two
//! is hostile. `Faults` wraps the real HTTP `Transport` and, per matching
//! request, drops it, delivers it and loses the answer, delivers it twice, replays
//! an older answer, or runs an action (a web write, a server-side restore) between
//! the client's decision and the server's hearing. A manual monotonic clock drives
//! backoff and polling, so no case waits on wall time.
//!
//! Every case ends on the same three claims: the device's visible state equals the
//! server's public state (convergence), each command took effect on the server at
//! most once (no duplicate effect), and a command whose outcome is unknown is kept
//! in the queue, never dropped or rekeyed (no silent loss). Gated like
//! `e2e_backend.rs`: `BB_BACKEND_PYTHON` names the interpreter and
//! `BB_REQUIRE_BACKEND=1` turns its absence into a failure.

mod support;

use bb_client::{
    Authentication, Cancellation, Clock, ExecuteContext, ExecuteRequest, Halt, HttpRequest,
    HttpResponse, InvalidationHub, Method, OpenOptions, RandomIds, Schedule, SessionBinding,
    SplitMix, Step, Store, SyncLoop, SyncSession, Syncer, Transport, TransportFailure, Wake, Waker,
    execute, open_issues,
};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{AfterCommandPrecondition, CommandRef, Precondition};
use bb_protocol::wire::{CommandId, Id, Instant};
use rusqlite::Connection;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use support::{Backend, Verb};

// -------------------------------------------------------------------- the backend

/// Backends start one at a time: a dozen cold Python imports at once can outlast
/// the harness's health deadline on a busy machine.
static BOOT: Mutex<()> = Mutex::new(());

fn start(name: &str) -> Option<Backend> {
    start_with(name, None)
}

fn start_with(name: &str, limits: Option<&str>) -> Option<Backend> {
    let _turn = BOOT
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    support::start_with(name, limits)
}

// ----------------------------------------------------------------------- the clock

/// Monotonic time the test moves by hand.
#[derive(Clone)]
struct ManualClock(Arc<AtomicU64>);

impl ManualClock {
    fn new() -> Self {
        Self(Arc::new(AtomicU64::new(1_000_000_000)))
    }

    fn advance(&self, by: Duration) {
        self.0.fetch_add(by.as_micros() as u64, Ordering::SeqCst);
    }

    fn at(&self) -> Duration {
        Duration::from_micros(self.0.load(Ordering::SeqCst))
    }
}

impl Clock for ManualClock {
    fn now(&self) -> Duration {
        self.at()
    }
}

// --------------------------------------------------------------------- the hostile wire

type Action = Box<dyn FnOnce() + Send>;

/// What happens to the next request that matches a rule.
enum Effect {
    /// The request never reaches the server (connection lost).
    Drop,
    /// The server processes it and commits; the answer never arrives.
    LoseAnswer,
    /// The server hears it twice; the client reads the second answer.
    Duplicate,
    /// The previous answer of the same route is delivered again, unprocessed.
    Replay,
    /// Runs first, then the request is delivered normally.
    Before(Action),
    /// Every matching request is answered with this status and body, unprocessed.
    Refuse(u16, Value),
}

struct Rule {
    /// Only requests whose body contains this text match.
    body_has: Option<String>,
    /// `METHOD path` (query stripped); a trailing `*` matches any suffix.
    needle: String,
    /// Matching requests to let through before the rule fires.
    skip: usize,
    effect: Effect,
}

#[derive(Default)]
struct Wire {
    log: Vec<String>,
    rules: Vec<Rule>,
    last_answer: BTreeMap<String, HttpResponse>,
}

#[derive(Clone, Default)]
struct Net(Arc<Mutex<Wire>>);

fn matches(needle: &str, line: &str) -> bool {
    needle
        .strip_suffix('*')
        .map_or(needle == line, |prefix| line.starts_with(prefix))
}

impl Net {
    fn fault(&self, needle: &str, effect: Effect) {
        self.fault_after(needle, 0, effect);
    }

    fn fault_after(&self, needle: &str, skip: usize, effect: Effect) {
        self.0.lock().unwrap().rules.push(Rule {
            body_has: None,
            needle: needle.to_string(),
            skip,
            effect,
        });
    }

    /// A standing refusal of the requests to `needle` whose body mentions `body_has`.
    fn refuse(&self, needle: &str, body_has: &str, status: u16, body: Value) {
        self.0.lock().unwrap().rules.push(Rule {
            body_has: Some(body_has.to_string()),
            needle: needle.to_string(),
            skip: 0,
            effect: Effect::Refuse(status, body),
        });
    }

    fn count(&self, needle: &str) -> usize {
        self.0
            .lock()
            .unwrap()
            .log
            .iter()
            .filter(|line| matches(needle, line))
            .count()
    }

    fn pending_rules(&self) -> usize {
        self.0.lock().unwrap().rules.len()
    }
}

struct Faults {
    inner: support::HttpTransport,
    net: Net,
}

impl Transport for Faults {
    fn send(
        &self,
        request: &HttpRequest,
        cancel: &Cancellation<'_>,
    ) -> Result<HttpResponse, TransportFailure> {
        let verb = if request.method == Method::Get {
            "GET"
        } else {
            "POST"
        };
        let line = format!("{verb} {}", request.path.split('?').next().unwrap());
        let text = request
            .body
            .as_ref()
            .map(|body| String::from_utf8_lossy(body).into_owned())
            .unwrap_or_default();
        let effect = {
            let mut wire = self.net.0.lock().unwrap();
            wire.log.push(line.clone());
            let hit = wire.rules.iter().position(|rule| {
                matches(&rule.needle, &line)
                    && rule
                        .body_has
                        .as_ref()
                        .is_none_or(|part| text.contains(part))
            });
            match hit {
                Some(at) if matches!(wire.rules[at].effect, Effect::Refuse(..)) => {
                    let Effect::Refuse(status, body) = &wire.rules[at].effect else {
                        unreachable!()
                    };
                    return Ok(HttpResponse {
                        status: *status,
                        retry_after: None,
                        body: body.to_string().into_bytes(),
                    });
                }
                Some(at) if wire.rules[at].skip > 0 => {
                    wire.rules[at].skip -= 1;
                    None
                }
                Some(at) => Some(wire.rules.remove(at).effect),
                None => None,
            }
        };
        let answer = match effect {
            Some(Effect::Drop) => return Err(TransportFailure::Connection),
            Some(Effect::Replay) => {
                let kept = self.net.0.lock().unwrap().last_answer.get(&line).cloned();
                match kept {
                    Some(answer) => return Ok(answer),
                    None => self.inner.send(request, cancel),
                }
            }
            Some(Effect::LoseAnswer) => {
                let _ = self.inner.send(request, cancel);
                return Err(TransportFailure::Timeout);
            }
            Some(Effect::Duplicate) => {
                let _ = self.inner.send(request, cancel);
                self.inner.send(request, cancel)
            }
            Some(Effect::Refuse(..)) => unreachable!("answered above"),
            Some(Effect::Before(action)) => {
                action();
                self.inner.send(request, cancel)
            }
            None => self.inner.send(request, cancel),
        };
        if let Ok(answer) = &answer {
            if answer.status >= 400 {
                eprintln!(
                    "{line} -> {} {}",
                    answer.status,
                    String::from_utf8_lossy(&answer.body)
                );
            }
            self.net
                .0
                .lock()
                .unwrap()
                .last_answer
                .insert(line, answer.clone());
        }
        answer
    }
}

// ------------------------------------------------------------------------ the device

struct Device {
    store: Store,
    syncer: Syncer,
    net: Net,
    clock: ManualClock,
}

fn context() -> ExecuteContext {
    ExecuteContext {
        now: Instant::parse(now()).unwrap(),
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

/// The device instant, RFC 3339 UTC (civil-from-days, no calendar dependency).
fn now() -> String {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    let (days, rest) = (seconds.div_euclid(86_400), seconds.rem_euclid(86_400));
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rest / 3_600,
        rest % 3_600 / 60,
        rest % 60
    )
}

/// Opens (`fresh`) or reopens a device's store under `name`: reopening is the
/// restart after a crash, with the durable queue and epoch intact.
fn open_device(backend: &Backend, name: &str, clock: &ManualClock, fresh: bool) -> Device {
    let path = std::env::temp_dir()
        .join(format!(
            "bb-faults-{name}-{}-{}",
            backend.addr.port(),
            std::process::id()
        ))
        .join("workspace.sqlite3");
    if fresh {
        let _ = std::fs::remove_dir_all(path.parent().unwrap());
    }
    let mut store = Store::open(&OpenOptions {
        path,
        workspace_id: "workspace-local".to_string(),
        busy_timeout: Duration::from_millis(5_000),
    })
    .unwrap();
    store
        .write(|tx| {
            tx.execute("UPDATE sync_meta SET account_link_state = 'linked'", [])?;
            Ok(())
        })
        .unwrap();
    let session = SyncSession::start(
        &mut store,
        &SessionBinding {
            account_id: Id::parse(&backend.owner).unwrap(),
            scope_id: Id::parse(&backend.owner).unwrap(),
            device_id: Id::parse(format!("device-{name}")).unwrap(),
            authentication: Authentication::Fresh,
        },
    )
    .unwrap();
    let net = Net::default();
    let syncer = Syncer::new(
        Box::new(Faults {
            inner: backend.transport(),
            net: net.clone(),
        }),
        session,
        Box::new(context),
        Arc::new(clock.clone()),
        Box::new(SplitMix::seeded(7)),
        Schedule::default(),
    );
    Device {
        store,
        syncer,
        net,
        clock: clock.clone(),
    }
}

/// Command IDs unique within one test's fresh server.
fn next_command() -> CommandId {
    static NEXT: AtomicU64 = AtomicU64::new(1);
    let n = NEXT.fetch_add(1, Ordering::SeqCst);
    CommandId::parse(format!("01900000-0000-4000-8000-{n:012}")).unwrap()
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

/// Saves one gesture locally; returns the command ID and the entity it names.
fn save(
    device: &mut Device,
    command_type: CommandType,
    entity_id: Option<&str>,
    payload: Value,
    preconditions: Vec<Precondition>,
) -> (CommandId, String) {
    let command_id = next_command();
    let request = ExecuteRequest {
        command_id: command_id.clone(),
        command_type,
        entity_id: entity_id.map(|id| Id::parse(id).unwrap()),
        payload: payload.as_object().unwrap().clone(),
        preconditions,
        depends_on: Vec::new(),
        admission_tokens: Vec::new(),
        context: context(),
    };
    let done = execute(&mut device.store, &mut RandomIds, &request).unwrap();
    (command_id, done.entity_id.as_str().to_string())
}

fn create(device: &mut Device, title: &str) -> (CommandId, String) {
    save(
        device,
        CommandType::TaskCreate,
        None,
        json!({ "title": title }),
        vec![],
    )
}

fn rename_after(
    device: &mut Device,
    task: &str,
    previous: &CommandId,
    title: &str,
) -> (CommandId, String) {
    save(
        device,
        CommandType::TaskUpdate,
        Some(task),
        json!({ "title": title }),
        vec![after(previous, EntityType::Task, task)],
    )
}

fn outbox(store: &mut Store) -> BTreeMap<String, String> {
    store
        .read(|tx| {
            let mut statement = tx.prepare("SELECT command_id, state FROM outbox")?;
            let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
            rows.collect()
        })
        .unwrap()
}

fn state_of(device: &mut Device, command: &CommandId) -> String {
    outbox(&mut device.store)
        .remove(command.as_str())
        .unwrap_or_else(|| "absent".to_string())
}

fn envelope_bytes(store: &mut Store, id: &CommandId) -> Vec<u8> {
    store
        .read(|tx| {
            tx.query_row(
                "SELECT envelope FROM outbox WHERE command_id = ?1",
                [id.as_str()],
                |row| row.get(0),
            )
        })
        .unwrap()
}

fn envelope(store: &mut Store, id: &CommandId) -> Value {
    serde_json::from_slice(&envelope_bytes(store, id)).unwrap()
}

fn unsettled(device: &mut Device) -> usize {
    outbox(&mut device.store)
        .values()
        .filter(|state| !matches!(state.as_str(), "completed" | "rejected"))
        .count()
}

/// Rounds, moving the clock past any backoff between them, until every command
/// is settled or `rounds` run out. Returns the last report.
fn settle(device: &mut Device, rounds: usize) -> bb_client::RoundReport {
    let mut report = device.syncer.round(&mut device.store);
    for _ in 1..rounds {
        if report.halt.is_none() && unsettled(device) == 0 {
            break;
        }
        device.clock.advance(Duration::from_secs(120));
        report = device.syncer.round(&mut device.store);
    }
    report
}

/// A round that must end clean.
fn bootstrap(device: &mut Device) {
    let report = device.syncer.round(&mut device.store);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(report.pull.snapshots, 1, "a fresh device starts from one");
}

/// Pulls until the feed is drained, advancing the clock past any backoff.
fn catch_up(device: &mut Device) {
    for _ in 0..10 {
        let report = device.syncer.pull(&mut device.store);
        if report.halt.is_none() && !report.more {
            return;
        }
        device.clock.advance(Duration::from_secs(120));
    }
    panic!("the feed never drained");
}

// ------------------------------------------------------------- server and device state

fn titles(inbox: &Value) -> Vec<String> {
    let mut found: Vec<String> = inbox["value"]["items"]
        .as_array()
        .unwrap_or(&Vec::new())
        .iter()
        .map(|item| item["title"].as_str().unwrap().to_string())
        .collect();
    found.sort();
    found
}

/// What the local query (the app's list read) shows for the inbox.
fn local_inbox(device: &mut Device) -> Value {
    let inputs = bb_domain::types::QueryInputs {
        now: context().now,
        device_zone: context().time_zone,
        policy: context().policy,
    };
    let query =
        json!({"kind": "task_list", "list": "inbox", "sort": "manual", "page": {"limit": 200}});
    let page = bb_client::query_page(
        &mut device.store,
        &serde_json::from_value(query).unwrap(),
        &inputs,
    )
    .unwrap();
    serde_json::to_value(&page.result).unwrap()
}

fn visible_titles(device: &mut Device) -> Vec<String> {
    titles(&local_inbox(device))
}

/// The public server state: the titles the REST list shows, sorted.
fn server_titles(backend: &Backend) -> Vec<String> {
    let (status, body) = backend.rest(Verb::Get, "/api/tasks?limit=200", None);
    assert_eq!(status, 200, "{body}");
    let mut found: Vec<String> = body["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|item| item["title"].as_str().unwrap().to_string())
        .collect();
    found.sort();
    found
}

fn db(backend: &Backend) -> Connection {
    let connection = Connection::open(&backend.db_path).unwrap();
    connection
        .busy_timeout(Duration::from_secs(10))
        .expect("busy timeout");
    connection
}

fn commit_seq(backend: &Backend) -> i64 {
    db(backend)
        .query_row("SELECT commit_seq FROM sync_scopes", [], |row| {
            row.get::<_, String>(0)
        })
        .unwrap()
        .parse()
        .unwrap()
}

/// How many feed transactions the server committed for `command`: the effect count.
fn effects(backend: &Backend, command: &CommandId) -> i64 {
    db(backend)
        .query_row(
            "SELECT count(*) FROM sync_change_transactions WHERE source_command_id = ?1",
            [command.as_str()],
            |row| row.get(0),
        )
        .unwrap()
}

/// The three closing claims: the device sees what the server publishes.
fn assert_converged(device: &mut Device, backend: &Backend) {
    catch_up(device);
    let local = visible_titles(device);
    assert_eq!(
        local,
        server_titles(backend),
        "visible state must equal the server's public state"
    );
}

fn web_create(backend: &Backend, title: &str) -> Value {
    let (status, task) = backend.rest(Verb::Post, "/api/tasks", Some(&json!({ "title": title })));
    assert_eq!(status, 201, "{task}");
    task
}

const COMMANDS: &str = "POST /api/sync/v1/commands";

// =================================================================== crash and loss

/// The process dies after the gesture is saved and before anything is sent.
#[test]
fn faults_026_sc_002_a_crash_between_the_local_commit_and_the_send_loses_nothing() {
    let Some(backend) = start("crash-before-send") else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "crash-before-send", &clock, true);
    bootstrap(&mut device);
    let (made, task) = create(&mut device, "Saved before the crash");
    let (edited, _) = rename_after(&mut device, &task, &made, "Edited before the crash");
    drop(device);
    assert!(
        server_titles(&backend).is_empty(),
        "nothing was sent before the crash"
    );

    let mut device = open_device(&backend, "crash-before-send", &clock, false);
    assert_eq!(state_of(&mut device, &made), "queued");
    assert_eq!(state_of(&mut device, &edited), "queued");
    assert_eq!(
        visible_titles(&mut device),
        ["Edited before the crash"],
        "the saved gesture is still visible after the restart"
    );
    let report = settle(&mut device, 4);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(unsettled(&mut device), 0);
    assert_eq!(effects(&backend, &made), 1);
    assert_eq!(effects(&backend, &edited), 1);
    assert_eq!(server_titles(&backend), ["Edited before the crash"]);
    assert_converged(&mut device, &backend);
}

/// The server committed, the answer was lost, and the device then crashed: the
/// restart finds the command possibly sent and learns its outcome by lookup.
#[test]
fn faults_026_fr_005_a_lost_ack_then_a_crash_settles_by_receipt_without_a_second_effect() {
    let Some(backend) = start("lost-ack-crash") else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "lost-ack-crash", &clock, true);
    bootstrap(&mut device);
    let (made, _) = create(&mut device, "Acknowledged too late");
    device.net.fault(COMMANDS, Effect::LoseAnswer);
    let first = device.syncer.round(&mut device.store);
    assert_eq!(first.halt, Some(Halt::Offline), "{first:#?}");
    assert_eq!(
        state_of(&mut device, &made),
        "unknown",
        "possibly sent, not forgotten"
    );
    assert_eq!(effects(&backend, &made), 1, "the server did commit it");
    let committed = commit_seq(&backend);
    let sent = envelope_bytes(&mut device.store, &made);
    drop(device);

    clock.advance(Duration::from_secs(120));
    let mut device = open_device(&backend, "lost-ack-crash", &clock, false);
    assert_eq!(
        state_of(&mut device, &made),
        "unknown",
        "survives the crash"
    );
    let report = settle(&mut device, 4);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(state_of(&mut device, &made), "completed");
    assert_eq!(
        envelope_bytes(&mut device.store, &made),
        sent,
        "the immutable envelope is never rekeyed"
    );
    assert_eq!(
        commit_seq(&backend),
        committed,
        "settling committed nothing"
    );
    assert_eq!(effects(&backend, &made), 1);

    // A receipt replay long after: the same envelope answers the same, once more.
    let body = envelope(&mut device.store, &made);
    let (status, receipt) = backend.rest(Verb::Post, "/api/sync/v1/commands", Some(&body));
    assert_eq!(status, 200, "{receipt}");
    assert_eq!(receipt["outcome"], "accepted");
    assert_eq!(
        commit_seq(&backend),
        committed,
        "a replay is not a new effect"
    );
    assert_eq!(server_titles(&backend), ["Acknowledged too late"]);
    assert_converged(&mut device, &backend);
}

/// The same envelope delivered twice (a retransmit racing the original).
#[test]
fn faults_026_fr_005_duplicate_delivery_of_a_command_chain_takes_effect_once() {
    let Some(backend) = start("duplicate") else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "duplicate", &clock, true);
    bootstrap(&mut device);
    let (made, task) = create(&mut device, "Delivered twice");
    let (edited, _) = rename_after(&mut device, &task, &made, "Delivered twice, edited");
    device.net.fault(COMMANDS, Effect::Duplicate);
    device.net.fault(COMMANDS, Effect::Duplicate);
    let before = commit_seq(&backend);
    let report = settle(&mut device, 4);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(device.net.pending_rules(), 0, "both duplicates fired");
    assert_eq!(effects(&backend, &made), 1);
    assert_eq!(effects(&backend, &edited), 1);
    assert_eq!(
        commit_seq(&backend),
        before + 2,
        "two commands, two commits"
    );
    assert_eq!(server_titles(&backend), ["Delivered twice, edited"]);
    assert_eq!(unsettled(&mut device), 0);
    assert_converged(&mut device, &backend);
}

/// A feed page delivered again after a newer state is already applied.
#[test]
fn faults_026_fr_004_a_replayed_feed_page_changes_nothing_and_the_next_pull_converges() {
    let Some(backend) = start("page-replay") else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "page-replay", &clock, true);
    bootstrap(&mut device);
    web_create(&backend, "First");
    web_create(&backend, "Second");
    catch_up(&mut device);
    assert_eq!(visible_titles(&mut device), ["First", "Second"]);

    web_create(&backend, "Third");
    // The page that already arrived is delivered instead of the new one.
    device.net.fault("GET /api/sync/v1/changes", Effect::Replay);
    let _ = device.syncer.pull(&mut device.store);
    assert_eq!(
        visible_titles(&mut device),
        ["First", "Second"],
        "an old page neither duplicates nor removes anything"
    );
    assert_converged(&mut device, &backend);
    assert_eq!(visible_titles(&mut device), ["First", "Second", "Third"]);
}

// ===================================================================== reordering

/// A dependent command reaches the server before the command it depends on.
#[test]
fn faults_026_fr_005_a_dependent_that_overtakes_its_create_is_not_applied_early() {
    let Some(backend) = start("reorder") else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "reorder", &clock, true);
    bootstrap(&mut device);
    // A first pair registers the epoch, so the early arrival reaches the command gate.
    let (made, task) = create(&mut device, "Created first");
    let (edited, _) = rename_after(&mut device, &task, &made, "Edited second");
    let registered = device.syncer.round(&mut device.store);
    assert_eq!(registered.halt, None, "{registered:#?}");
    assert_eq!(unsettled(&mut device), 0, "the plain order settles");
    let seen: Arc<Mutex<Option<(u16, Value)>>> = Arc::new(Mutex::new(None));
    let slot = Arc::clone(&seen);
    let web = backend.web();
    let (made2, task2) = create(&mut device, "Second pair, created");
    let (edited2, _) = rename_after(&mut device, &task2, &made2, "Second pair, edited");
    let early2 = envelope(&mut device.store, &edited2);
    device.net.fault(
        COMMANDS,
        Effect::Before(Box::new(move || {
            let answer = web.rest(Verb::Post, "/api/sync/v1/commands", Some(&early2));
            *slot.lock().unwrap() = Some(answer);
        })),
    );
    let report = settle(&mut device, 6);
    let (status, receipt) = seen
        .lock()
        .unwrap()
        .clone()
        .expect("the early delivery ran");
    eprintln!("early dependent -> {status} {receipt}");
    assert_eq!(status, 409, "{receipt}");
    assert_eq!(
        receipt["error"]["code"], "DEPENDENCY_PENDING",
        "a dependent is not accepted before its create: {receipt}"
    );
    assert_eq!(receipt["error"]["retryable"], true, "{receipt}");
    assert_eq!(report.halt, None, "{report:#?}");
    // The early arrival left no verdict behind: the real delivery settles normally.
    for command in [&made, &edited, &made2, &edited2] {
        assert_eq!(state_of(&mut device, command), "completed");
        assert_eq!(effects(&backend, command), 1);
    }
    assert!(open_issues(&mut device.store).unwrap().is_empty());
    assert_eq!(
        server_titles(&backend),
        ["Edited second", "Second pair, edited"]
    );
    assert_converged(&mut device, &backend);
}

// =================================================================== epoch closure

/// The server closes the epoch after the client decided to send and before it hears.
#[test]
fn faults_026_fr_011_an_epoch_closed_mid_send_holds_the_command_and_new_work_proceeds() {
    let Some(backend) = start("epoch-mid-send") else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "epoch-mid-send", &clock, true);
    bootstrap(&mut device);
    let (held, _) = create(&mut device, "Sent into a closed epoch");
    let sent = envelope_bytes(&mut device.store, &held);
    let path = backend.db_path.clone();
    device.net.fault(
        COMMANDS,
        Effect::Before(Box::new(move || {
            Connection::open(path)
                .unwrap()
                .execute(
                    "UPDATE sync_device_epochs SET status = 'closed', close_reason = 'revoked'",
                    [],
                )
                .unwrap();
        })),
    );
    let report = device.syncer.round(&mut device.store);
    assert!(report.registered, "{report:#?}");
    assert_eq!(report.halt, Some(Halt::EpochClosed), "{report:#?}");
    assert!(
        server_titles(&backend).is_empty(),
        "the server executed nothing"
    );
    assert_eq!(
        state_of(&mut device, &held),
        "unknown",
        "kept for reconciliation, not dropped"
    );
    assert_eq!(
        envelope_bytes(&mut device.store, &held),
        sent,
        "never rekeyed"
    );

    // New, independent work is accepted into a fresh epoch.
    let (fresh, _) = create(&mut device, "Typed after the closure");
    clock.advance(Duration::from_secs(120));
    let again = settle(&mut device, 4);
    assert_eq!(again.halt, None, "{again:#?}");
    assert_eq!(
        state_of(&mut device, &fresh),
        "completed",
        "sent under a new epoch"
    );
    assert_eq!(effects(&backend, &fresh), 1);
    assert_eq!(
        effects(&backend, &held),
        0,
        "the old command never executes"
    );
    assert_eq!(state_of(&mut device, &held), "unknown", "still held");
    assert_eq!(server_titles(&backend), ["Typed after the closure"]);
    assert_eq!(
        envelope_bytes(&mut device.store, &held),
        sent,
        "the held envelope is intact"
    );
}

// ================================================================ restore / rollback

/// The scope is rolled back to an earlier backup, in a new server generation with
/// every device epoch closed (sync-v1 section 9). Work the backup never saw is
/// gone from the server; the device must converge on what the server now publishes.
#[test]
fn faults_026_fr_010_a_server_rolled_back_to_a_backup_is_rebuilt_from_a_snapshot() {
    let Some(backend) = start("rollback") else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "rollback", &clock, true);
    bootstrap(&mut device);
    web_create(&backend, "In the backup");
    catch_up(&mut device);
    let backup = backend.data_dir.join("backup.sqlite3");
    let _ = std::fs::remove_file(&backup);
    db(&backend)
        .execute("VACUUM INTO ?1", [backup.to_str().unwrap()])
        .unwrap();

    // Work the backup will not contain, acknowledged and seen by the device.
    let (later, _) = create(&mut device, "Lost to the rollback");
    let report = settle(&mut device, 4);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(state_of(&mut device, &later), "completed");
    assert_eq!(
        server_titles(&backend),
        ["In the backup", "Lost to the rollback"]
    );
    // Saved offline during the outage.
    let (offline, _) = create(&mut device, "Typed during the outage");

    // The restore procedure closes every epoch, including those registered after
    // the backup was taken (the image alone cannot know them).
    backend.python(&format!(
        "import sqlite3\n\
         src = sqlite3.connect({backup:?})\n\
         dst = sqlite3.connect({live:?})\n\
         epochs = dst.execute('SELECT * FROM sync_device_epochs').fetchall()\n\
         devices = dst.execute('SELECT * FROM sync_devices').fetchall()\n\
         src.backup(dst)\n\
         dst.executemany('INSERT OR REPLACE INTO sync_devices VALUES (?,?,?)', devices)\n\
         dst.executemany('INSERT OR REPLACE INTO sync_device_epochs VALUES (?,?,?,?,?,?,?,?)', epochs)\n\
         dst.execute(\"UPDATE sync_scopes SET server_generation = 'restored-generation'\")\n\
         dst.execute(\"UPDATE sync_device_epochs SET status = 'closed', close_reason = 'restore'\")\n\
         dst.commit()\n",
        backup = backup.to_str().unwrap(),
        live = backend.db_path.to_str().unwrap(),
    ));
    assert_eq!(server_titles(&backend), ["In the backup"]);

    let report = device.syncer.round(&mut device.store);
    assert_eq!(report.pull.halt, None, "{report:#?}");
    assert_eq!(
        report.pull.snapshots, 1,
        "rebuilt from a snapshot: {report:#?}"
    );
    let local = visible_titles(&mut device);
    assert!(
        local.contains(&"In the backup".to_string()),
        "the base is the server's: {local:?}"
    );
    assert!(
        !local.contains(&"Lost to the rollback".to_string()),
        "the rolled-back effect is not resurrected locally: {local:?}"
    );
    // The command from the closed epoch is held, never executed, never rekeyed.
    assert_eq!(state_of(&mut device, &offline), "unknown", "held, not lost");
    assert_eq!(effects(&backend, &offline), 0);

    // New work proceeds under a fresh epoch for the new generation.
    let (fresh, _) = create(&mut device, "Typed after the rollback");
    let after = settle(&mut device, 4);
    assert_eq!(after.halt, None, "{after:#?}");
    assert_eq!(
        state_of(&mut device, &fresh),
        "completed",
        "sent under a fresh epoch"
    );
    assert_eq!(effects(&backend, &fresh), 1);
    assert_eq!(
        server_titles(&backend),
        ["In the backup", "Typed after the rollback"]
    );
    assert_eq!(state_of(&mut device, &offline), "unknown");
}

/// A bare restore: the image predates this device's epoch and nothing closes it,
/// so the server has never heard of the epoch the queue is stamped with and answers
/// 404 (indistinguishable from a foreign one). The device must treat that as its
/// own epoch being gone: hold the old commands, register a fresh epoch, go on.
#[test]
fn faults_026_fr_010_a_restore_that_forgot_the_device_epoch_does_not_block_new_work() {
    let Some(backend) = start("restore-unknown-epoch") else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "restore-unknown-epoch", &clock, true);
    bootstrap(&mut device);
    web_create(&backend, "In the backup");
    catch_up(&mut device);
    let backup = backend.data_dir.join("bare-backup.sqlite3");
    let _ = std::fs::remove_file(&backup);
    db(&backend)
        .execute("VACUUM INTO ?1", [backup.to_str().unwrap()])
        .unwrap();
    // The epoch is registered only now, after the backup.
    let (sent, _) = create(&mut device, "Lost to the rollback");
    assert_eq!(settle(&mut device, 4).halt, None);
    assert_eq!(state_of(&mut device, &sent), "completed");
    let (offline, _) = create(&mut device, "Typed during the outage");
    let held_envelope = envelope_bytes(&mut device.store, &offline);

    backend.python(&format!(
        "import sqlite3\n\
         src = sqlite3.connect({backup:?})\n\
         dst = sqlite3.connect({live:?})\n\
         src.backup(dst)\n\
         dst.execute(\"UPDATE sync_scopes SET server_generation = 'restored-generation'\")\n\
         dst.commit()\n",
        backup = backup.to_str().unwrap(),
        live = backend.db_path.to_str().unwrap(),
    ));
    assert_eq!(server_titles(&backend), ["In the backup"]);

    // The server's 404 closes the device's own epoch locally.
    let first = device.syncer.round(&mut device.store);
    assert_eq!(first.halt, Some(Halt::EpochClosed), "{first:#?}");
    let (fresh, _) = create(&mut device, "Typed after the rollback");
    let report = settle(&mut device, 6);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(
        state_of(&mut device, &fresh),
        "completed",
        "new work goes out under a fresh epoch"
    );
    assert_eq!(effects(&backend, &fresh), 1);
    assert_eq!(effects(&backend, &offline), 0, "the old command never runs");
    assert_eq!(state_of(&mut device, &offline), "unknown", "held, not lost");
    assert_eq!(
        envelope_bytes(&mut device.store, &offline),
        held_envelope,
        "never re-encoded"
    );
    assert_eq!(
        server_titles(&backend),
        ["In the backup", "Typed after the rollback"]
    );
}

/// A framework-shaped 422 (no error envelope) and a 413 are the same verdict: the
/// command is an issue, not an endlessly retried unknown.
#[test]
fn faults_026_fr_007_an_unenveloped_422_or_a_413_also_settles_as_an_issue() {
    for (status, body, code) in [
        (422, json!({"detail": []}), "INVALID_REQUEST"),
        (
            413,
            json!({
                "error": {"code": "COMMAND_TOO_LARGE", "retryable": false, "message": "m", "details": {}},
                "correlation_id": "corr-big",
            }),
            "COMMAND_TOO_LARGE",
        ),
    ] {
        let Some(backend) = start("refused-shape") else {
            return;
        };
        let clock = ManualClock::new();
        let mut device = open_device(&backend, "refused-shape", &clock, true);
        bootstrap(&mut device);
        let (refused, _) = create(&mut device, "Refused");
        device.net.refuse(COMMANDS, refused.as_str(), status, body);
        let report = device.syncer.round(&mut device.store);
        assert_eq!(report.halt, None, "{status}: {report:?}");
        assert_eq!(state_of(&mut device, &refused), "rejected", "{status}");
        let issues = open_issues(&mut device.store).unwrap();
        assert_eq!(issues.len(), 1, "{status}: {issues:?}");
        assert_eq!(issues[0].issue.reason.code(), code);
        let sends = device.net.count(COMMANDS);
        device.syncer.resume();
        let _ = device.syncer.round(&mut device.store);
        assert_eq!(device.net.count(COMMANDS), sends, "{status}: not resent");
    }
}

/// A command the server refuses for good (`INVALID_REQUEST`, no receipt) is a
/// terminal verdict: it becomes a rejected command with a visible issue, is never
/// sent again however often the loop is woken, and holds back only its dependants.
#[test]
fn faults_026_fr_005_a_refused_command_becomes_an_issue_and_blocks_only_its_dependants() {
    let Some(backend) = start("head-of-line") else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "head-of-line", &clock, true);
    bootstrap(&mut device);
    let (stuck, stuck_task) = create(&mut device, "Stuck");
    let (dependant, _) = rename_after(&mut device, &stuck_task, &stuck, "Stuck, edited");
    let (free, _) = create(&mut device, "Independent");
    device.net.refuse(
        COMMANDS,
        stuck.as_str(),
        400,
        json!({
            "error": {"code": "INVALID_REQUEST", "retryable": false, "message": "m", "details": {}},
            "correlation_id": "corr-stuck",
        }),
    );
    let first = device.syncer.round(&mut device.store);
    assert_eq!(
        first.halt, None,
        "a verdict is not a failing sync: {first:?}"
    );
    assert!(first.changes.issues, "{first:?}");
    let sends = device.net.count(COMMANDS);
    for _ in 0..4 {
        // A foreground, network-return or manual wake forgives held commands.
        device.syncer.resume();
        let report = device.syncer.round(&mut device.store);
        assert_eq!(report.halt, None, "{report:?}");
        clock.advance(Duration::from_secs(120));
    }
    assert_eq!(
        device.net.count(COMMANDS),
        sends,
        "a refused command is never resent"
    );
    assert_eq!(
        state_of(&mut device, &free),
        "completed",
        "independent work progresses"
    );
    assert_eq!(effects(&backend, &free), 1);
    assert_eq!(
        state_of(&mut device, &stuck),
        "rejected",
        "kept as an issue"
    );
    assert_eq!(effects(&backend, &stuck), 0);
    let issues = open_issues(&mut device.store).unwrap();
    assert_eq!(
        issues.len(),
        2,
        "the refusal and its held dependant: {issues:?}"
    );
    let reasons: Vec<String> = issues.iter().map(|view| view.issue.reason.code()).collect();
    assert_eq!(
        reasons,
        ["INVALID_REQUEST", "BLOCKED_DEPENDENCY"],
        "{issues:?}"
    );
    assert_eq!(
        state_of(&mut device, &dependant),
        "blocked_dependency",
        "the dependant is held, not dropped"
    );
    assert_eq!(effects(&backend, &dependant), 0);
    assert_eq!(server_titles(&backend), ["Independent"]);
}

/// The same rollback where the restore did not get to close the epoch: the
/// server refuses every send from the epoch registered under the old
/// generation with `RESET_REQUIRED`. The device must confirm that epoch again,
/// so the server closes it, rather than loop on `RESET_REQUIRED`; what it sent
/// under the old epoch is held, and new work goes out under a fresh one.
#[test]
fn faults_026_fr_010_a_generation_change_with_an_active_epoch_closes_it_instead_of_looping() {
    let Some(backend) = start("rollback-active") else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "rollback-active", &clock, true);
    bootstrap(&mut device);
    web_create(&backend, "Before the restore");
    let (first, _) = create(&mut device, "Sent before the restore");
    assert_eq!(settle(&mut device, 4).halt, None);
    assert_eq!(state_of(&mut device, &first), "completed");
    let old_epoch: String = db(&backend)
        .query_row("SELECT device_epoch FROM sync_device_epochs", [], |row| {
            row.get(0)
        })
        .unwrap();
    db(&backend)
        .execute(
            "UPDATE sync_scopes SET server_generation = 'restored-generation'",
            [],
        )
        .unwrap();

    let (stranded, _) = create(&mut device, "Sent to the old epoch");
    let mut report = device.syncer.round(&mut device.store);
    for _ in 0..6 {
        if report.halt.is_none() && unsettled(&mut device) <= 1 {
            break;
        }
        clock.advance(Duration::from_secs(120));
        report = device.syncer.round(&mut device.store);
    }
    assert_eq!(report.halt, None, "no endless RESET_REQUIRED: {report:#?}");
    let (status, reason): (String, Option<String>) = db(&backend)
        .query_row(
            "SELECT status, close_reason FROM sync_device_epochs WHERE device_epoch = ?1",
            [&old_epoch],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    assert_eq!(
        (status.as_str(), reason.as_deref()),
        ("closed", Some("generation_changed")),
        "the server closed the old epoch"
    );
    assert_eq!(effects(&backend, &stranded), 0, "never ran");
    assert_eq!(
        state_of(&mut device, &stranded),
        "unknown",
        "held, not lost"
    );

    let (fresh, _) = create(&mut device, "Typed after the restore");
    let report = settle(&mut device, 6);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(state_of(&mut device, &fresh), "completed");
    assert_eq!(effects(&backend, &fresh), 1);
    assert_eq!(
        server_titles(&backend),
        [
            "Before the restore",
            "Sent before the restore",
            "Typed after the restore"
        ]
    );
}

// =================================================================== snapshot / transfer

/// 70 tasks of ~20 KB: a snapshot of more than one 1 MiB page.
fn seed_many(backend: &Backend) -> Vec<String> {
    let mut expected = Vec::new();
    for n in 0..70 {
        let title = format!("Seeded {n:02}");
        let details: String = (0..2_500)
            .map(|m| format!("w{:03}{n:02} ", m % 1000))
            .collect();
        let (status, task) = backend.rest(
            Verb::Post,
            "/api/tasks",
            Some(&json!({"title": title, "details": details})),
        );
        assert_eq!(status, 201, "{task}");
        expected.push(title);
    }
    expected.sort();
    expected
}

/// The snapshot being downloaded expires between two pages.
#[test]
fn faults_026_fr_005_a_snapshot_that_expires_mid_bootstrap_restarts_without_a_partial_base() {
    let Some(backend) = start("snapshot-expiry") else {
        return;
    };
    let expected = seed_many(&backend);
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "snapshot-expiry", &clock, true);
    let path = backend.db_path.clone();
    device.net.fault_after(
        "GET /api/sync/v1/snapshots/*",
        1,
        Effect::Before(Box::new(move || {
            Connection::open(path)
                .unwrap()
                .execute(
                    "UPDATE sync_snapshots SET expires_at = '2000-01-01T00:00:00.000000+00:00'",
                    [],
                )
                .unwrap();
        })),
    );
    let mut rounds = 0;
    loop {
        let report = device.syncer.round(&mut device.store);
        rounds += 1;
        let local = visible_titles(&mut device);
        assert!(
            local.is_empty() || local == expected,
            "the base is activated whole or not at all: {} of {}",
            local.len(),
            expected.len()
        );
        if report.halt.is_none() && local == expected {
            break;
        }
        assert!(rounds < 8, "never converged: {report:#?}");
        clock.advance(Duration::from_secs(120));
    }
    assert_eq!(device.net.pending_rules(), 0, "the expiry fired");
    assert!(
        device.net.count("POST /api/sync/v1/snapshots") >= 2,
        "a second snapshot replaced the expired one"
    );
    assert_converged(&mut device, &backend);
}

/// Pages of an oversized transaction are lost on the way, once dropped and once
/// answered into the void.
#[test]
fn faults_026_fr_006_lost_transfer_pages_are_refetched_and_the_transaction_applies_once() {
    let Some(backend) = start_with("transfer-loss", Some("7000,3500,2048")) else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "transfer-loss", &clock, true);
    bootstrap(&mut device);
    let details: String = (0..1_500)
        .map(|n| format!("note{:03} ", n % 1000))
        .collect();
    let (status, big) = backend.rest(
        Verb::Post,
        "/api/tasks",
        Some(&json!({"title": "Large notes", "details": details})),
    );
    assert_eq!(status, 201, "{big}");
    device
        .net
        .fault_after("GET /api/sync/v1/transactions/*", 1, Effect::Drop);
    device
        .net
        .fault_after("GET /api/sync/v1/transactions/*", 2, Effect::LoseAnswer);
    let mut applied = 0;
    for _ in 0..8 {
        let report = device.syncer.pull(&mut device.store);
        applied += report.transactions;
        if report.halt.is_none() && !report.more {
            break;
        }
        clock.advance(Duration::from_secs(120));
    }
    assert_eq!(device.net.pending_rules(), 0, "both losses fired");
    assert_eq!(applied, 1, "the transaction applies whole, exactly once");
    let inbox = local_inbox(&mut device);
    let found: Vec<&Value> = inbox["value"]["items"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|task| task["title"] == "Large notes")
        .collect();
    assert_eq!(found.len(), 1, "no duplicate record");
    assert_eq!(
        found[0]["details"].as_str().unwrap(),
        details,
        "byte for byte"
    );
    assert_converged(&mut device, &backend);
}

// ========================================================================== hints

fn confirmed_tasks(store: &mut Store) -> i64 {
    store
        .read(|tx| {
            tx.query_row(
                "SELECT count(*) FROM confirmed_records
                 WHERE record_type = 'task' AND tombstone = 0",
                [],
                |row| row.get(0),
            )
        })
        .unwrap()
}

/// The hint never arrives (the stream is down): the 30-second poll alone makes a
/// commit visible well inside 60 seconds, including one made just after a poll.
#[test]
fn faults_026_sc_004_a_lost_hint_is_covered_by_the_poll_within_sixty_seconds() {
    let Some(backend) = start("hint-loss") else {
        return;
    };
    for offset_ms in [0_u64, 1, 15_000, 29_999] {
        let clock = ManualClock::new();
        let device = open_device(&backend, &format!("hint-loss-{offset_ms}"), &clock, true);
        let Device {
            mut store, syncer, ..
        } = device;
        let mut worker = SyncLoop::new(
            syncer,
            Waker::new(),
            InvalidationHub::new(4),
            Arc::new(clock.clone()),
            Box::new(SplitMix::seeded(offset_ms)),
        );
        worker.waker().post(Wake::Foreground);
        let Step::Ran { .. } = worker.step(&mut store) else {
            panic!("the foreground round runs");
        };
        let baseline = confirmed_tasks(&mut store);
        let anchor = clock.at();
        let commit_at = anchor + Duration::from_millis(offset_ms);
        let title = format!("Committed at +{offset_ms} ms");
        let mut committed = false;
        let mut visible_after = None;
        for _ in 0..200 {
            if !committed && clock.at() >= commit_at {
                web_create(&backend, &title);
                committed = true;
            }
            match worker.step(&mut store) {
                Step::Ran { .. } => {
                    if committed
                        && visible_after.is_none()
                        && confirmed_tasks(&mut store) > baseline
                    {
                        visible_after = Some(clock.at() - commit_at);
                    }
                }
                Step::Wait(left) => {
                    let until_commit = commit_at.saturating_sub(clock.at());
                    let step = if committed || until_commit.is_zero() {
                        left
                    } else {
                        left.min(until_commit)
                    };
                    clock.advance(step.max(Duration::from_millis(1)));
                }
                Step::Idle => panic!("an active, online loop is never idle"),
            }
            if visible_after.is_some() {
                break;
            }
        }
        let visible = visible_after.expect("the commit became visible");
        assert!(
            visible <= Duration::from_secs(60),
            "offset {offset_ms} ms: visible after {visible:?}"
        );
    }
}

// ============================================================== Smart Add aliases

/// A Smart Add is acknowledged to nobody; the project is renamed elsewhere and the
/// server's response copies expire; the original immutable alias-dependent command
/// then arrives more than 24 hours later and must land on the original project.
#[test]
fn faults_026_sc_002_a_lost_smart_add_ack_survives_a_rename_and_24_hours() {
    let Some(backend) = start("smart-add") else {
        return;
    };
    let clock = ManualClock::new();
    let mut device = open_device(&backend, "smart-add", &clock, true);
    bootstrap(&mut device);
    let (status, home) = backend.rest(Verb::Post, "/api/projects", Some(&json!({"name": "Home"})));
    assert_eq!(status, 201, "{home}");
    let home_id = home["id"].as_str().unwrap().to_string();
    catch_up(&mut device);

    let alias = "project_00000000-0000-4000-8000-0000000000aa";
    let (added, task) = save(
        &mut device,
        CommandType::TaskSmartAdd,
        None,
        json!({"title": "Buy milk", "project": {"name": "home", "proposed_id": alias}}),
        vec![],
    );
    let (parcel, _) = save(
        &mut device,
        CommandType::TaskCreate,
        None,
        json!({"title": "Post parcel", "project_id": {
            "after_command": added.as_str(),
            "alias_id": alias,
            "entity_type": "project",
        }}),
        vec![],
    );
    let before = envelope_bytes(&mut device.store, &parcel);
    device.net.fault(COMMANDS, Effect::LoseAnswer);
    let lost = device.syncer.round(&mut device.store);
    assert_eq!(lost.halt, Some(Halt::Offline), "{lost:#?}");
    assert_eq!(effects(&backend, &added), 1, "the server committed the add");
    assert_eq!(state_of(&mut device, &added), "unknown");
    assert_eq!(
        effects(&backend, &parcel),
        0,
        "the dependent has not been sent"
    );

    // Another device renames the project; then more than 24 hours pass offline and
    // the server's retention sweep redacts the response copies.
    let (status, renamed) = backend.rest(
        Verb::Patch,
        &format!("/api/projects/{home_id}"),
        Some(&json!({"name": "House", "expected_revision": 1})),
    );
    assert_eq!(status, 200, "{renamed}");
    backend.python(
        "from datetime import UTC, datetime, timedelta\n\
         from app.main import app\n\
         from app.modules.tasks.rust_adapter import RustCore\n\
         from app.modules.tasks.sync.receipts import ReceiptStore\n\
         from app.modules.tasks.sync.retention import SyncRetention, sync_owner_ids\n\
         c = app.state.container\n\
         units = c.task_unit_of_work\n\
         log = ReceiptStore(RustCore()).change_log\n\
         at = datetime.now(UTC) + timedelta(hours=25)\n\
         SyncRetention(units, log, lambda: sync_owner_ids(c.task_repo.db_path), clock=lambda: at).run_retention_sweep()\n",
    );
    let redacted: i64 = db(&backend)
        .query_row(
            "SELECT count(*) FROM sync_command_receipts WHERE result IS NULL",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(redacted >= 1, "the sweep redacted a response copy");

    clock.advance(Duration::from_secs(25 * 3600));
    let report = settle(&mut device, 6);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(state_of(&mut device, &added), "completed");
    assert_eq!(state_of(&mut device, &parcel), "completed");
    assert_eq!(
        envelope_bytes(&mut device.store, &parcel),
        before,
        "the dependent is still the original immutable envelope"
    );
    assert_eq!(effects(&backend, &added), 1);
    assert_eq!(effects(&backend, &parcel), 1);
    let (_, projects) = backend.rest(Verb::Get, "/api/projects", None);
    let projects = projects
        .as_array()
        .cloned()
        .unwrap_or_else(|| projects["items"].as_array().cloned().unwrap_or_default());
    assert_eq!(projects.len(), 1, "no project was recreated: {projects:?}");
    assert_eq!(projects[0]["id"], home_id.as_str());
    assert_eq!(projects[0]["name"], "House");
    let (_, parcel_task) = backend.rest(Verb::Get, "/api/tasks?limit=200", None);
    let in_home: Vec<&Value> = parcel_task["items"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|item| item["project_id"] == home_id.as_str())
        .collect();
    assert_eq!(in_home.len(), 2, "both tasks sit in the original project");
    // The inbox shows only unfiled tasks, so compare the confirmed base itself.
    catch_up(&mut device);
    assert_eq!(confirmed_titles(&mut device.store), server_titles(&backend));
    assert_eq!(
        confirmed_titles(&mut device.store),
        ["Buy milk", "Post parcel"]
    );
    let _ = task;
}

fn confirmed_titles(store: &mut Store) -> Vec<String> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT body FROM confirmed_records WHERE record_type = 'task' AND tombstone = 0",
            )?;
            let rows = statement.query_map([], |row| row.get::<_, Vec<u8>>(0))?;
            let mut found = Vec::new();
            for body in rows {
                let value: Value = serde_json::from_slice(&body?).unwrap();
                found.push(value["title"].as_str().unwrap().to_string());
            }
            found.sort();
            Ok(found)
        })
        .unwrap()
}

// ====================================================================== two devices

/// Two devices write offline through a hostile wire; everything converges.
#[test]
fn faults_026_sc_001_two_devices_with_lost_and_duplicated_deliveries_converge() {
    let Some(backend) = start("two-devices") else {
        return;
    };
    let clock = ManualClock::new();
    let mut a = open_device(&backend, "two-a", &clock, true);
    let mut b = open_device(&backend, "two-b", &clock, true);
    bootstrap(&mut a);
    bootstrap(&mut b);
    let (a_made, a_task) = create(&mut a, "From A");
    let (a_edit, _) = rename_after(&mut a, &a_task, &a_made, "From A, edited");
    let (b_made, _) = create(&mut b, "From B");
    web_create(&backend, "From the web");
    a.net.fault(COMMANDS, Effect::LoseAnswer);
    b.net.fault(COMMANDS, Effect::Duplicate);
    let (_, _) = (settle(&mut a, 6), settle(&mut b, 6));
    for command in [&a_made, &a_edit, &b_made] {
        assert_eq!(effects(&backend, command), 1, "{command:?}");
    }
    assert_eq!(unsettled(&mut a), 0);
    assert_eq!(unsettled(&mut b), 0);
    let expected = ["From A, edited", "From B", "From the web"];
    assert_eq!(server_titles(&backend), expected);
    assert_converged(&mut a, &backend);
    assert_converged(&mut b, &backend);
}
