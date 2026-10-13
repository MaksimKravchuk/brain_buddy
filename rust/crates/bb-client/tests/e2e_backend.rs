//! The client runtime against the real backend (026 PR-40 end to end).
//!
//! `Syncer` runs over a real HTTP `Transport` with the session cookie against the
//! production application (uvicorn, temporary data directory, `rust_core_sync`
//! on for the signed-in owner). Nothing server-side is mocked or replayed from a
//! fixture: commands, receipts, changes pages, transfers and snapshots cross the
//! wire as the Python server writes them. Gated like `hints_backend.rs`:
//! `BB_BACKEND_PYTHON` names the interpreter, `BB_REQUIRE_BACKEND=1` makes its
//! absence a failure.

mod support;

use bb_client::{
    AccountBinding, Authentication, Cancellation, ExecuteContext, ExecuteRequest, HttpRequest,
    HttpResponse, Method, MonotonicClock, OpenOptions, RandomIds, Schedule, SessionBinding,
    SplitMix, Store, SyncSession, Syncer, Transport, TransportFailure, establish_account_less_with,
    execute, link_and_merge_with, open_issues,
};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{
    AfterCommandPrecondition, CommandRef, Precondition, RevisionPrecondition,
};
use bb_protocol::wire::{CommandId, Counter, Id, Instant};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use support::{Backend, Verb, start, start_with};

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

type Hook = Arc<Mutex<Option<(String, Box<dyn FnOnce() + Send>)>>>;

struct Device {
    store: Store,
    syncer: Syncer,
    log: Arc<Mutex<Vec<String>>>,
    hook: Hook,
}

impl Device {
    /// The requests made so far, as `METHOD path-without-query`.
    fn requests(&self) -> Vec<String> {
        self.log.lock().unwrap().clone()
    }

    fn count(&self, needle: &str) -> usize {
        self.requests()
            .iter()
            .filter(|line| line.contains(needle))
            .count()
    }

    /// Runs `action` (a web write, say) as the next request matching `needle` is
    /// about to be sent: after the client decided, before the server hears it.
    fn interpose(&self, needle: &str, action: impl FnOnce() + Send + 'static) {
        *self.hook.lock().unwrap() = Some((needle.to_string(), Box::new(action)));
    }
}

/// The real HTTP adapter, recording every request and able to interpose a web
/// write between the client's decision and the server's answer.
struct Spy {
    inner: support::HttpTransport,
    log: Arc<Mutex<Vec<String>>>,
    hook: Hook,
}

impl Transport for Spy {
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
        let path = request.path.split('?').next().unwrap();
        let line = format!("{verb} {path}");
        self.log.lock().unwrap().push(line.clone());
        let hook = {
            let mut guard = self.hook.lock().unwrap();
            match guard.as_ref() {
                Some((needle, _)) if line.contains(needle.as_str()) => guard.take(),
                _ => None,
            }
        };
        if let Some((_, action)) = hook {
            action();
        }
        let answer = self.inner.send(request, cancel);
        // A refusal is part of the evidence when a test fails: print it.
        if let Some(response) = answer
            .as_ref()
            .ok()
            .filter(|response| response.status >= 400)
        {
            eprintln!(
                "{line} -> {} {}",
                response.status,
                String::from_utf8_lossy(&response.body)
            );
        }
        answer
    }
}

fn device(backend: &Backend, name: &str) -> Device {
    let path = std::env::temp_dir()
        .join(format!(
            "bb-e2e-store-{name}-{}-{}",
            backend.addr.port(),
            std::process::id()
        ))
        .join("workspace.sqlite3");
    let _ = std::fs::remove_dir_all(path.parent().unwrap());
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
    let log = Arc::new(Mutex::new(Vec::new()));
    let hook = Arc::new(Mutex::new(None));
    let syncer = Syncer::new(
        Box::new(Spy {
            inner: backend.transport(),
            log: Arc::clone(&log),
            hook: Arc::clone(&hook),
        }),
        session,
        Box::new(context),
        Arc::new(MonotonicClock::new()),
        Box::new(SplitMix::from_entropy()),
        Schedule::default(),
    );
    Device {
        store,
        syncer,
        log,
        hook,
    }
}

/// Counts up from 1: readable command IDs, unique within one fresh server.
struct Commands(u64);

impl Commands {
    fn next(&mut self) -> CommandId {
        self.0 += 1;
        CommandId::parse(format!("01900000-0000-4000-8000-{:012}", self.0)).unwrap()
    }
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
    ids: &mut Commands,
    command_type: CommandType,
    entity_id: Option<&str>,
    payload: Value,
    preconditions: Vec<Precondition>,
) -> (CommandId, String) {
    let command_id = ids.next();
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

fn outbox(store: &mut Store) -> BTreeMap<String, String> {
    store
        .read(|tx| {
            let mut statement = tx.prepare("SELECT command_id, state FROM outbox")?;
            let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
            rows.collect()
        })
        .unwrap()
}

fn envelope(store: &mut Store, id: &CommandId) -> Value {
    let bytes: Vec<u8> = store
        .read(|tx| {
            tx.query_row(
                "SELECT envelope FROM outbox WHERE command_id = ?1",
                [id.as_str()],
                |row| row.get(0),
            )
        })
        .unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

fn rest_get(backend: &Backend, path: &str) -> Value {
    let (status, body) = backend.rest(Verb::Get, path, None);
    assert_eq!(status, 200, "GET {path}: {body}");
    body
}

/// Bootstraps `device` (an empty server), asserting the round is clean.
fn bootstrap(device: &mut Device) {
    let report = device.syncer.round(&mut device.store);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(
        report.pull.snapshots, 1,
        "a fresh device starts from a snapshot"
    );
}

#[test]
fn e2e_026_fr_001_local_commands_reach_the_real_server_and_receipts_replay() {
    let Some(backend) = start("commands") else {
        return;
    };
    let mut device = device(&backend, "a");
    bootstrap(&mut device);
    let mut ids = Commands(0);

    // task.create + task.update + a tag + a subtask, all saved offline first.
    let (create, task) = save(
        &mut device,
        &mut ids,
        CommandType::TaskCreate,
        None,
        json!({"title": "Plan the trip"}),
        vec![],
    );
    let (update, _) = save(
        &mut device,
        &mut ids,
        CommandType::TaskUpdate,
        Some(&task),
        json!({"title": "Plan the trip abroad"}),
        vec![after(&create, EntityType::Task, &task)],
    );
    let (tag_create, tag) = save(
        &mut device,
        &mut ids,
        CommandType::TagCreate,
        None,
        json!({"name": "travel"}),
        vec![],
    );
    let (tagged, _) = save(
        &mut device,
        &mut ids,
        CommandType::TaskTags,
        Some(&task),
        json!({"add_tag_ids": [tag.as_str()], "remove_tag_ids": []}),
        vec![
            after(&update, EntityType::Task, &task),
            after(&tag_create, EntityType::Tag, &tag),
        ],
    );
    let (subtask_create, subtask) = save(
        &mut device,
        &mut ids,
        CommandType::SubtaskCreate,
        None,
        json!({"task_id": task.as_str(), "title": "Book flights"}),
        vec![after(&tagged, EntityType::Task, &task)],
    );

    let report = device.syncer.round(&mut device.store);
    assert_eq!(report.halt, None, "{report:#?}");
    assert!(report.registered, "the pending epoch registers first");
    assert_eq!(report.sent, 5, "{report:#?}");
    assert_eq!(report.settled, 5);

    // The server holds exactly those entities.
    let detail = rest_get(&backend, &format!("/api/tasks/{task}"));
    assert_eq!(detail["title"], "Plan the trip abroad");
    assert_eq!(detail["subtasks"].as_array().unwrap().len(), 1);
    assert_eq!(detail["subtasks"][0]["title"], "Book flights");
    assert_eq!(detail["subtasks"][0]["id"], subtask.as_str());
    let tags = rest_get(&backend, "/api/tags");
    assert_eq!(tags.as_array().unwrap().len(), 1);
    assert_eq!(tags[0]["name"], "travel");
    assert_eq!(tags[0]["id"], tag.as_str());
    assert!(
        detail.to_string().contains(&tag),
        "the tag is on the task: {detail}"
    );
    let all = rest_get(&backend, "/api/tasks?limit=200");
    assert_eq!(all["items"].as_array().unwrap().len(), 1);

    // Receipts replay: the same envelope again is the same answer, no new commit.
    let watermark = || {
        backend.python(&format!(
            "import sqlite3;print(sqlite3.connect({:?}).execute(\"select commit_seq from sync_scopes\").fetchone()[0])",
            backend.db_path.to_str().unwrap()
        ))
    };
    let before = watermark();
    for command in [&create, &update, &tag_create, &tagged, &subtask_create] {
        let body = envelope(&mut device.store, command);
        let (status, receipt) = backend.rest(Verb::Post, "/api/sync/v1/commands", Some(&body));
        assert_eq!(status, 200, "{receipt}");
        assert_eq!(receipt["command_id"], command.as_str());
        assert_eq!(receipt["outcome"], "accepted");
    }
    assert_eq!(watermark(), before, "a replay commits nothing");

    // The device converges: its own feed transactions complete the commands.
    let again = device.syncer.round(&mut device.store);
    assert_eq!(again.halt, None, "{again:#?}");
    let states = outbox(&mut device.store);
    assert!(
        states.values().all(|state| state == "completed"),
        "{states:?}"
    );
}

/// What the local query (the app's list read) shows for the inbox, as JSON.
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

fn web_create(backend: &Backend, title: &str) -> Value {
    let (status, task) = backend.rest(Verb::Post, "/api/tasks", Some(&json!({"title": title})));
    assert_eq!(status, 201, "{task}");
    task
}

#[test]
fn e2e_026_fr_004_a_web_write_is_pulled_and_the_local_query_sees_it() {
    let Some(backend) = start("pull") else { return };
    let mut device = device(&backend, "a");
    bootstrap(&mut device);
    assert!(titles(&local_inbox(&mut device)).is_empty());

    let created = web_create(&backend, "Written on the web");
    let report = device.syncer.pull(&mut device.store);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(report.transactions, 1);
    assert!(report.changes.records);
    assert_eq!(titles(&local_inbox(&mut device)), ["Written on the web"]);

    // An edit and a second task follow the same path, in commit order.
    let (status, edited) = backend.rest(Verb::Post, "/api/tasks/dummy", None);
    let _ = (status, edited);
    let id = created["id"].as_str().unwrap();
    let (status, updated) = backend.rest(
        Verb::Patch,
        &format!("/api/tasks/{id}"),
        Some(&json!({"title": "Edited on the web", "expected_revision": created["revision"]})),
    );
    assert_eq!(status, 200, "{updated}");
    web_create(&backend, "A second one");
    let report = device.syncer.pull(&mut device.store);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(report.transactions, 2);
    assert_eq!(
        titles(&local_inbox(&mut device)),
        ["A second one", "Edited on the web"]
    );
    // Nothing was sent: pulling never writes to the server.
    assert_eq!(device.count("POST /api/sync/v1/commands"), 0);
}

fn shown(task: &str, revision: &str) -> Precondition {
    Precondition::Revision(RevisionPrecondition {
        entity_type: EntityType::Task,
        entity_id: Id::parse(task).unwrap(),
        edit_revision: Counter::parse(revision).unwrap(),
    })
}

fn web_rename(web: &support::Web, task: &str, title: &str, revision: &str) {
    let (status, body) = web.rest(
        Verb::Patch,
        &format!("/api/tasks/{task}"),
        Some(&json!({"title": title, "expected_revision": revision.parse::<u64>().unwrap()})),
    );
    assert_eq!(status, 200, "{body}");
}

/// The server edits the same task before the client's edit is heard: the client
/// keeps its text as a typed issue and the server's text stands. No data lost.
#[test]
fn e2e_026_fr_007_a_conflict_the_server_decides_becomes_an_issue_not_data_loss() {
    let Some(backend) = start("conflict") else {
        return;
    };
    let mut device = device(&backend, "a");
    bootstrap(&mut device);
    let created = web_create(&backend, "Draft");
    let task = created["id"].as_str().unwrap().to_string();
    assert_eq!(device.syncer.pull(&mut device.store).halt, None);

    let mut ids = Commands(0);
    let (edit, _) = save(
        &mut device,
        &mut ids,
        CommandType::TaskUpdate,
        Some(&task),
        json!({"title": "Mine"}),
        vec![shown(&task, "1")],
    );
    // The web edit lands after the client decided and before the server hears it.
    let web = backend.web();
    let target = task.clone();
    device.interpose("POST /api/sync/v1/commands", move || {
        web_rename(&web, &target, "Theirs", "1");
    });
    let report = device.syncer.round(&mut device.store);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(report.sent, 1);
    assert!(report.changes.issues, "{report:#?}");

    let issues = open_issues(&mut device.store).unwrap();
    assert_eq!(issues.len(), 1, "{issues:?}");
    assert!(
        format!("{issues:?}").contains("Mine"),
        "the local text is kept: {issues:?}"
    );
    assert_eq!(outbox(&mut device.store)[edit.as_str()], "rejected");
    let server = rest_get(&backend, &format!("/api/tasks/{task}"));
    assert_eq!(server["title"], "Theirs", "the server's edit stands");

    // The device then converges on the server's text; the issue stays for the user.
    assert_eq!(device.syncer.pull(&mut device.store).halt, None);
    assert_eq!(titles(&local_inbox(&mut device)), ["Theirs"]);
    assert_eq!(open_issues(&mut device.store).unwrap().len(), 1);
}

/// The same conflict seen the other way round: the web edit is already in the
/// feed when the device syncs, so the unsent edit is held back, never sent.
#[test]
fn e2e_026_fr_007_a_conflict_the_feed_reveals_holds_the_edit_back_as_an_issue() {
    let Some(backend) = start("conflict-feed") else {
        return;
    };
    let mut device = device(&backend, "a");
    bootstrap(&mut device);
    let created = web_create(&backend, "Draft");
    let task = created["id"].as_str().unwrap().to_string();
    assert_eq!(device.syncer.pull(&mut device.store).halt, None);
    let mut ids = Commands(0);
    save(
        &mut device,
        &mut ids,
        CommandType::TaskUpdate,
        Some(&task),
        json!({"title": "Mine"}),
        vec![shown(&task, "1")],
    );
    web_rename(&backend.web(), &task, "Theirs", "1");

    let report = device.syncer.round(&mut device.store);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(
        device.count("POST /api/sync/v1/commands"),
        0,
        "a stale edit is not sent"
    );
    let issues = open_issues(&mut device.store).unwrap();
    assert_eq!(issues.len(), 1, "{issues:?}");
    assert!(format!("{issues:?}").contains("Mine"));
    assert_eq!(titles(&local_inbox(&mut device)), ["Theirs"]);
}

/// One transaction too large for a feed page arrives through the paged transfer.
#[test]
fn e2e_026_fr_006_an_oversized_transaction_arrives_whole_through_the_transfer_path() {
    // Tiny inline limits on the server (the wire is unchanged): a transaction over
    // ~3 KB goes by transfer, in 2 KB byte pages.
    let Some(backend) = start_with("transfer", Some("7000,3500,2048")) else {
        return;
    };
    let mut device = device(&backend, "a");
    bootstrap(&mut device);
    // A small write stays inline.
    web_create(&backend, "Small");
    let report = device.syncer.pull(&mut device.store);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(
        device.count("GET /api/sync/v1/transactions/"),
        0,
        "small ones stay inline"
    );

    // One task with 12 KB of notes is a single transaction over the (lowered) page
    // limit: announced by a manifest and fetched in byte pages.
    let details: String = (0..1_500)
        .map(|n| format!("note{:03} ", n % 1000))
        .collect();
    let (status, big) = backend.rest(
        Verb::Post,
        "/api/tasks",
        Some(&json!({"title": "Large notes", "details": details})),
    );
    assert_eq!(status, 201, "{big}");
    let report = device.syncer.pull(&mut device.store);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(report.snapshots, 0, "{report:#?}");
    assert_eq!(report.transactions, 1, "applied whole, once");
    let pages = device.count("GET /api/sync/v1/transactions/");
    assert!(
        pages >= 3,
        "the transfer ran in byte pages ({pages}): {:?}",
        device.requests()
    );
    let inbox = local_inbox(&mut device);
    let found = inbox["value"]["items"]
        .as_array()
        .unwrap()
        .iter()
        .find(|task| task["title"] == "Large notes")
        .expect("the large task is visible locally");
    assert_eq!(found["details"].as_str().unwrap(), details, "byte for byte");
    // The feed continues normally after a transfer.
    web_create(&backend, "After the transfer");
    assert_eq!(device.syncer.pull(&mut device.store).transactions, 1);
    assert_eq!(titles(&local_inbox(&mut device)).len(), 3);
}

#[test]
fn e2e_026_fr_010_reset_required_recovers_through_a_snapshot_and_keeps_pending_work() {
    let Some(backend) = start("reset") else {
        return;
    };
    let mut device = device(&backend, "a");
    bootstrap(&mut device);
    web_create(&backend, "Before the reset");
    assert_eq!(device.syncer.pull(&mut device.store).halt, None);

    // Saved offline while the server's feed is reset under it.
    let mut ids = Commands(0);
    save(
        &mut device,
        &mut ids,
        CommandType::TaskCreate,
        None,
        json!({"title": "Typed offline"}),
        vec![],
    );
    let db = || rusqlite::Connection::open(&backend.db_path).unwrap();
    db().execute("UPDATE sync_scopes SET feed_generation = 'feed-reset'", [])
        .unwrap();
    web_create(&backend, "After the reset");

    let report = device.syncer.round(&mut device.store);
    assert_eq!(report.halt, None, "{report:#?}");
    assert_eq!(report.pull.snapshots, 1, "{report:#?}");
    assert_eq!(
        report.sent, 1,
        "the offline task is sent after recovery: {report:#?}"
    );
    let again = device.syncer.round(&mut device.store);
    assert_eq!(again.halt, None, "{again:#?}");
    assert_eq!(
        titles(&local_inbox(&mut device)),
        ["After the reset", "Before the reset", "Typed offline"]
    );
    let on_server = rest_get(&backend, "/api/tasks?limit=200");
    assert_eq!(on_server["items"].as_array().unwrap().len(), 3);

    // A restore: another server generation, with every device epoch closed (the
    // restore procedure of sync-v1 section 9). The base is rebuilt from a snapshot;
    // the closed epoch's unsent command is held, never rekeyed, and new work
    // proceeds under a fresh epoch registered for the new generation.
    let (held, _) = save(
        &mut device,
        &mut ids,
        CommandType::TaskCreate,
        None,
        json!({"title": "Typed during the restore"}),
        vec![],
    );
    db().execute(
        "UPDATE sync_scopes SET server_generation = 'restored-generation'",
        [],
    )
    .unwrap();
    db().execute(
        "UPDATE sync_device_epochs SET status = 'closed', close_reason = 'restore'",
        [],
    )
    .unwrap();
    let report = device.syncer.round(&mut device.store);
    assert_eq!(report.pull.halt, None, "{report:#?}");
    assert_eq!(report.pull.snapshots, 1, "{report:#?}");
    // Refused by the closed epoch: possibly sent as far as the device can tell, so
    // it is kept (never rekeyed) and its outcome looked up.
    assert_eq!(
        outbox(&mut device.store)[held.as_str()],
        "unknown",
        "held, not lost"
    );
    let on_server = rest_get(&backend, "/api/tasks?limit=200");
    assert_eq!(on_server["items"].as_array().unwrap().len(), 3);

    let (fresh, _) = save(
        &mut device,
        &mut ids,
        CommandType::TaskCreate,
        None,
        json!({"title": "Typed after the restore"}),
        vec![],
    );
    let after = device.syncer.round(&mut device.store);
    assert_eq!(after.halt, None, "{after:#?}");
    assert!(
        after.registered,
        "the fresh epoch registers for the new generation"
    );
    let on_server = rest_get(&backend, "/api/tasks?limit=200");
    assert_eq!(
        on_server["items"].as_array().unwrap().len(),
        4,
        "{on_server}"
    );
    let states = outbox(&mut device.store);
    assert_eq!(states[fresh.as_str()], "completed");
    assert_eq!(
        states[held.as_str()],
        "unknown",
        "still held for reconciliation"
    );
}

/// The tail of `device`: a session over a store that is already linked.
fn device_over(backend: &Backend, name: &str, mut store: Store) -> Device {
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
    let log = Arc::new(Mutex::new(Vec::new()));
    let hook = Arc::new(Mutex::new(None));
    let syncer = Syncer::new(
        Box::new(Spy {
            inner: backend.transport(),
            log: Arc::clone(&log),
            hook: Arc::clone(&hook),
        }),
        session,
        Box::new(context),
        Arc::new(MonotonicClock::new()),
        Box::new(SplitMix::from_entropy()),
        Schedule::default(),
    );
    Device {
        store,
        syncer,
        log,
        hook,
    }
}

#[test]
fn e2e_026_fr_003_the_first_sign_in_merge_reaches_the_real_server_once() {
    let Some(backend) = start("merge") else {
        return;
    };
    // An account-less workspace with real work in it.
    let path = std::env::temp_dir()
        .join(format!(
            "bb-e2e-merge-{}-{}",
            backend.addr.port(),
            std::process::id()
        ))
        .join("workspace.sqlite3");
    let _ = std::fs::remove_dir_all(path.parent().unwrap());
    let mut store = Store::open(&OpenOptions {
        path,
        workspace_id: "workspace-local".to_string(),
        busy_timeout: Duration::from_millis(5_000),
    })
    .unwrap();
    establish_account_less_with(&mut store, || Ok(())).unwrap();
    let mut local = Device {
        store,
        syncer: device(&backend, "scratch").syncer,
        log: Arc::default(),
        hook: Arc::default(),
    };
    let mut ids = Commands(0);
    let (_, tag) = save(
        &mut local,
        &mut ids,
        CommandType::TagCreate,
        None,
        json!({"name": "errands"}),
        vec![],
    );
    let (_, project) = save(
        &mut local,
        &mut ids,
        CommandType::ProjectCreate,
        None,
        json!({"name": "Home"}),
        vec![],
    );
    let (_, plumber) = save(
        &mut local,
        &mut ids,
        CommandType::TaskCreate,
        None,
        json!({"title": "Call the plumber", "state": "next", "project_id": project, "tag_ids": [tag], "priority": "high"}),
        vec![],
    );
    let (_, done) = save(
        &mut local,
        &mut ids,
        CommandType::TaskCreate,
        None,
        json!({"title": "Already done"}),
        vec![],
    );
    save(
        &mut local,
        &mut ids,
        CommandType::TaskTransition,
        Some(&done),
        json!({"action": "complete"}),
        vec![Precondition::Revision(RevisionPrecondition {
            entity_type: EntityType::Task,
            entity_id: Id::parse(&done).unwrap(),
            edit_revision: Counter::parse("1").unwrap(),
        })],
    );
    save(
        &mut local,
        &mut ids,
        CommandType::SubtaskCreate,
        None,
        json!({"task_id": plumber, "title": "Find the number"}),
        vec![],
    );
    save(
        &mut local,
        &mut ids,
        CommandType::CommentCreate,
        None,
        json!({"task_id": plumber, "body": "Left a message"}),
        vec![],
    );
    // Review state: the owner's activation and settings (which travel as commands) and a
    // session (a public Review record that stays on the device).
    let mut review = |kind, entity: Option<&str>, payload: Value, pre| {
        let mut request = ExecuteRequest {
            command_id: ids.next(),
            command_type: kind,
            entity_id: entity.map(|id| Id::parse(id).unwrap()),
            payload: payload.as_object().unwrap().clone(),
            preconditions: pre,
            depends_on: Vec::new(),
            admission_tokens: Vec::new(),
            context: context(),
        };
        request.context.policy.weekly_review = true;
        request
    };
    let ack = review(
        CommandType::ReviewExplainerAck,
        Some("local-owner"),
        json!({"time_zone": "UTC"}),
        vec![],
    );
    execute(&mut local.store, &mut RandomIds, &ack).unwrap();
    let settings = review(
        CommandType::ReviewSettings,
        Some("local-owner"),
        json!({"threshold_days": 21, "onboarded": true}),
        vec![Precondition::Revision(RevisionPrecondition {
            entity_type: EntityType::ReviewSettings,
            entity_id: Id::parse("local-owner").unwrap(),
            edit_revision: Counter::parse("2").unwrap(),
        })],
    );
    execute(&mut local.store, &mut RandomIds, &settings).unwrap();
    let started = review(
        CommandType::ReviewSessionStart,
        None,
        json!({"mode": "quick", "entry": "list", "origin": "ios", "skip_steps": [], "replace_open": false}),
        vec![],
    );
    let session = execute(&mut local.store, &mut RandomIds, &started)
        .unwrap()
        .entity_id;
    let mut store = local.store;

    // The merge: one transaction, then the ordinary sync round sends the queue.
    let binding = AccountBinding {
        account: Id::parse(&backend.owner).unwrap(),
        scope: Id::parse(&backend.owner).unwrap(),
        device: Id::parse("device-merge").unwrap(),
    };
    let mut merge_context = context();
    merge_context.policy.weekly_review = true;
    let outcome = link_and_merge_with(&mut store, &binding, &merge_context, || Ok(())).unwrap();
    assert!(
        matches!(
            outcome,
            bb_client::MergeOutcome::Merged {
                commands: 10,
                review_records_kept_local: 1,
                ..
            }
        ),
        "{outcome:?}"
    );
    let mut device = device_over(&backend, "merge", store);
    let report = device.syncer.round(&mut device.store);
    assert_eq!(report.halt, None, "{report:#?}");
    assert!(report.registered, "the pending epoch registers first");
    // What waits for a receipt (a command built on another) goes in the rounds after.
    let mut sent = report.sent;
    for _ in 0..4 {
        let more = device.syncer.round(&mut device.store);
        assert_eq!(more.halt, None, "{more:#?}");
        sent += more.sent;
    }
    assert_eq!(sent, 10, "{report:#?}");

    // The server holds the account-less work, with its structure.
    let all = rest_get(&backend, "/api/tasks?limit=200");
    let mut found: Vec<String> = all["items"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t["title"].as_str().unwrap().to_string())
        .collect();
    found.sort();
    // The list shows open tasks; the finished one is read on its own below.
    assert_eq!(found, ["Call the plumber"]);
    let detail = rest_get(&backend, &format!("/api/tasks/{plumber}"));
    assert_eq!(detail["state"], "next");
    assert_eq!(detail["subtasks"][0]["title"], "Find the number");
    assert!(detail.to_string().contains("Left a message"), "{detail}");
    assert!(
        detail.to_string().contains(&tag) && detail.to_string().contains(&project),
        "{detail}"
    );
    assert_eq!(
        rest_get(&backend, &format!("/api/tasks/{done}"))["state"],
        "completed"
    );

    // The server holds the owner's Review settings and activation, as the device had them.
    let state = rest_get(&backend, "/api/review/state");
    assert_eq!(state["settings"]["threshold_days"], 21, "{state}");
    assert!(
        state["settings"]["onboarded_at"].is_string()
            && state["activated"].as_bool() != Some(false),
        "{state}"
    );
    // ... and the session is still the device's own, session records included.
    let kept: i64 = device
        .store
        .read(|tx| {
            tx.query_row(
                "SELECT COUNT(*) FROM visible_records WHERE record_type = 'review_session'",
                [],
                |r| r.get(0),
            )
        })
        .unwrap();
    assert_eq!(kept, 1, "session {}", session.as_str());

    // The device converges, and a repeat of the merge queues nothing new.
    let again = device.syncer.round(&mut device.store);
    assert_eq!(again.halt, None, "{again:#?}");
    assert!(
        outbox(&mut device.store)
            .values()
            .all(|state| matches!(state.as_str(), "completed" | "accepted_awaiting_feed")),
        "{:?}",
        outbox(&mut device.store)
    );
    assert_eq!(
        link_and_merge_with(&mut device.store, &binding, &context(), || Ok(())).unwrap(),
        bb_client::MergeOutcome::AlreadyLinked
    );
    assert_eq!(
        rest_get(&backend, "/api/tasks?limit=200")["items"]
            .as_array()
            .unwrap()
            .len(),
        1
    );
}
