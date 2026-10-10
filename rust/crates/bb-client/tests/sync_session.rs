//! Sync session and device-epoch tests: a late answer never changes the store
//! (a reset, a restore, a sign-out or an account switch fences it, even inside the
//! same session), the pending-registration epoch is durable and registered
//! under current authority only, an unsupported version stops sync without
//! touching the store or the queue, and independent new work proceeds while an
//! old dependent stays blocked.
//!
//! Everything goes through the public API on a real SQLite file, across store
//! reopenings and real process aborts. The server side is played by building the
//! wire JSON the contract describes and decoding it with the `bb-protocol`
//! codecs.

use bb_client::{
    ApplyError, Authentication, CapabilitiesCheck, EndCause, EpochState, ErrorAction,
    ExecuteContext, ExecuteRequest, Fence, IdSource, OpenOptions, RequestKind, SessionBinding,
    SessionError, Store, StoreError, StoreStatus, SyncSession, activate_snapshot, apply_receipt,
    apply_registration, begin_snapshot, capture_fence, close_epoch, epoch_view, execute,
    send_candidates, sha256_hex, stage_snapshot_page,
};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::capabilities::{Capabilities, DeviceRegistration};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{Precondition, RevisionPrecondition};
use bb_protocol::feed::{SnapshotManifest, SnapshotPage};
use bb_protocol::receipt::{ErrorBody, Receipt};
use bb_protocol::wire::{CommandId, Counter, Id, Instant, decode};
use rusqlite::{Connection, params};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::Duration;

const WORKSPACE: &str = "workspace-local";
const ACCOUNT: &str = "account-1";
const SCOPE: &str = "scope-1";
const DEVICE: &str = "device-1";
const GENERATION: &str = "generation-1";
const RESTORED: &str = "generation-2";
const NOW: &str = "2026-10-10T09:00:00Z";
const EXPIRES: &str = "2026-10-10T09:30:00Z";
const ROLE: &str = "BB_SESSION_CHILD";

// ----------------------------------------------------------------------- harness

fn scratch(name: &str) -> PathBuf {
    let directory = std::env::temp_dir().join(format!("bb-session-{name}-{}", std::process::id()));
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

/// A store whose account-link choice is recorded and that holds a bootstrapped
/// base at cursor `cursor-0`, watermark 0, in `GENERATION`. The scope is not
/// bound: that is the session's job.
fn linked(path: &Path) -> Store {
    let mut store = open(path).unwrap();
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

fn binding_for(account: &str, scope: &str, authentication: Authentication) -> SessionBinding {
    SessionBinding {
        account_id: Id::parse(account).unwrap(),
        scope_id: Id::parse(scope).unwrap(),
        device_id: Id::parse(DEVICE).unwrap(),
        authentication,
    }
}

fn binding(authentication: Authentication) -> SessionBinding {
    binding_for(ACCOUNT, SCOPE, authentication)
}

/// A linked store with a freshly authenticated session.
fn ready(path: &Path) -> (Store, SyncSession) {
    let mut store = linked(path);
    let session = SyncSession::start(&mut store, &binding(Authentication::Fresh)).unwrap();
    (store, session)
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

fn edit(store: &mut Store, ids: &mut SeqIds, n: u64, task_id: &str, title: &str, revision: &str) {
    let update = request(
        cmd(n),
        CommandType::TaskUpdate,
        Some(task_id),
        json!({ "title": title }),
        vec![Precondition::Revision(RevisionPrecondition {
            entity_type: EntityType::Task,
            entity_id: Id::parse(task_id).unwrap(),
            edit_revision: Counter::parse(revision).unwrap(),
        })],
    );
    execute(store, ids, &update).unwrap();
}

// ------------------------------------------------------------------ the server side

fn with_common_in(mut body: Value, scope: &str, generation: &str) -> Value {
    body["correlation_id"] = json!("corr-1");
    body["scope_id"] = json!(scope);
    body["server_generation"] = json!(generation);
    body["server_now"] = json!(NOW);
    body
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
            SCOPE,
            generation,
        )
        .to_string(),
    )
    .unwrap()
}

fn registration_ack(device_epoch: &Id, scope: &str, generation: &str) -> DeviceRegistration {
    decode(
        &with_common_in(
            json!({
                "device_id": DEVICE,
                "device_epoch": device_epoch.as_str(),
                "epoch_status": "active",
            }),
            scope,
            generation,
        )
        .to_string(),
    )
    .unwrap()
}

fn error_body(code: &str, details: Value) -> ErrorBody {
    decode(
        &json!({
            "error": { "code": code, "retryable": false, "message": "refused", "details": details },
            "correlation_id": "corr-1",
        })
        .to_string(),
    )
    .unwrap()
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

/// An empty snapshot at `watermark`: the server's base after a restore.
fn snapshot(id: &str, generation: &str, watermark: u64) -> (SnapshotManifest, SnapshotPage) {
    let stream = b"[]";
    let page = with_common_in(
        json!({
            "snapshot_id": id,
            "watermark": watermark.to_string(),
            "page_index": 0,
            "payload_base64": base64_encode(stream),
            "page_sha256": sha256_hex(stream),
            "has_more": false,
            "next_page_token": null,
        }),
        SCOPE,
        generation,
    );
    let manifest = with_common_in(
        json!({
            "snapshot_id": id,
            "watermark": watermark.to_string(),
            "cursor": format!("cursor-{watermark}"),
            "page_count": 1,
            "record_count": 0,
            "total_bytes": stream.len(),
            "sha256": sha256_hex(stream),
            "expires_at": EXPIRES,
            "first_page_token": "token-0",
        }),
        SCOPE,
        generation,
    );
    (
        decode(&manifest.to_string()).unwrap(),
        decode(&page.to_string()).unwrap(),
    )
}

/// The whole snapshot download and activation under `fence`.
fn recover_base(
    store: &mut Store,
    fence: &Fence,
    generation: &str,
    watermark: u64,
) -> Result<bb_client::Activated, ApplyError> {
    let id = format!("snap-{generation}-{watermark}");
    let (manifest, page) = snapshot(&id, generation, watermark);
    begin_snapshot(store, &context(), fence, &manifest)?;
    stage_snapshot_page(store, &context(), fence, &page)?;
    activate_snapshot(store, &context(), fence, &manifest.snapshot_id)
}

// -------------------------------------------------------------------- the store

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

fn state(store: &mut Store, n: u64) -> String {
    let states: BTreeMap<String, String> = store
        .read(|tx| {
            let mut statement = tx.prepare("SELECT command_id, state FROM outbox")?;
            let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
            rows.collect()
        })
        .unwrap();
    states[cmd(n).as_str()].clone()
}

/// `(device_epoch, envelope)` of a command: what must never be rewritten.
fn envelope(store: &mut Store, n: u64) -> (String, Vec<u8>) {
    store
        .read(|tx| {
            tx.query_row(
                "SELECT device_epoch, envelope FROM outbox WHERE command_id = ?1",
                [cmd(n).as_str()],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )
        })
        .unwrap()
}

/// Everything sync keeps that a refused operation must leave alone.
fn dump(store: &mut Store) -> Vec<String> {
    store
        .read(|tx| {
            let mut lines = Vec::new();
            lines.push(tx.query_row(
                "SELECT printf('%d %d %d %s %s %s %s %s %d', workspace_generation,
                    session_generation, local_sync_generation, server_generation, cursor,
                    base_watermark, device_epoch, device_epoch_state, next_local_seq)
                 FROM sync_meta",
                [],
                |row| row.get::<_, String>(0),
            )?);
            let mut statement = tx.prepare(
                "SELECT printf('%s %s %s %d', command_id, device_epoch, state, ever_sent)
                 FROM outbox ORDER BY local_seq",
            )?;
            for row in statement.query_map([], |row| row.get::<_, String>(0))? {
                lines.push(row?);
            }
            Ok(lines)
        })
        .unwrap()
}

fn drafts(store: &mut Store) -> i64 {
    store
        .read(|tx| tx.query_row("SELECT COUNT(*) FROM drafts", [], |row| row.get(0)))
        .unwrap()
}

fn cursor(store: &mut Store) -> Option<String> {
    store
        .read(|tx| tx.query_row("SELECT cursor FROM sync_meta", [], |row| row.get(0)))
        .unwrap()
}

fn epoch_id(store: &mut Store) -> Id {
    epoch_view(store).unwrap().epoch.unwrap()
}

/// The epoch is registered: pending epoch, registration, ACK.
fn register(store: &mut Store, session: &mut SyncSession) -> Id {
    let (request, body) = session.registration(store).unwrap().unwrap();
    let ack = registration_ack(&body.device_epoch, SCOPE, GENERATION);
    let done = apply_registration(store, request.live_fence().unwrap(), &ack).unwrap();
    assert!(done.newly_active);
    body.device_epoch
}

// ------------------------------------------------------------------ child processes

fn spawn(role: &str, path: &Path, ack: &str) -> Child {
    Command::new(std::env::current_exe().unwrap())
        .args([
            "sync_session_child_entry",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ])
        .env(ROLE, role)
        .env("BB_SESSION_PATH", path)
        .env("BB_SESSION_ACK", ack)
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
fn sync_session_child_entry() {
    let Ok(role) = std::env::var(ROLE) else {
        return;
    };
    let path = PathBuf::from(std::env::var("BB_SESSION_PATH").unwrap());
    let mut store = open(&path).unwrap();
    match role.as_str() {
        // A new capture is saved, then the process is killed.
        "capture_and_abort" => {
            create_task(&mut store, &mut SeqIds(0), 1, "Captured");
            announce("captured");
            std::process::abort();
        }
        // The registration ACK is applied and committed, then the process is
        // killed before it can tell anyone.
        "register_and_abort" => {
            let mut session =
                SyncSession::start(&mut store, &binding(Authentication::Resumed)).unwrap();
            let (request, body) = session.registration(&mut store).unwrap().unwrap();
            let ack = registration_ack(&body.device_epoch, SCOPE, GENERATION);
            apply_registration(&mut store, request.live_fence().unwrap(), &ack).unwrap();
            announce("registered");
            std::process::abort();
        }
        other => panic!("unknown child role {other}"),
    }
}

// ------------------------------------------------------------------------- tests

mod sync_session {
    use super::*;

    // ----------------------------------------------- binding, sessions, account switch

    #[test]
    fn sync_session_026_fr_003_the_scope_is_bound_at_session_start_and_only_after_the_link_choice()
    {
        let path = scratch("bind");
        let mut store = open(&path).unwrap();
        // Account-less: no link choice yet, so nothing is bound or sent.
        assert_eq!(
            SyncSession::start(&mut store, &binding(Authentication::Fresh)).unwrap_err(),
            SessionError::LinkRequired
        );
        let scope: Option<String> = store
            .read(|tx| tx.query_row("SELECT scope_id FROM sync_meta", [], |row| row.get(0)))
            .unwrap();
        assert_eq!(scope, None);
        store
            .write(|tx| {
                tx.execute("UPDATE sync_meta SET account_link_state = 'linked'", [])?;
                Ok(())
            })
            .unwrap();

        // Bootstrap: the snapshot activation needs the scope the session set.
        let fence = capture_fence(&mut store).unwrap();
        assert_eq!(
            recover_base(&mut store, &fence, GENERATION, 5).unwrap_err(),
            ApplyError::WrongScope
        );
        let mut session = SyncSession::start(&mut store, &binding(Authentication::Fresh)).unwrap();
        let request = session
            .begin_request(&mut store, RequestKind::Pull)
            .unwrap();
        assert_eq!(request.scope_id().as_str(), SCOPE);
        recover_base(&mut store, request.live_fence().unwrap(), GENERATION, 5).unwrap();
        assert_eq!(cursor(&mut store).as_deref(), Some("cursor-5"));

        // The same account resumes with the same generations; a new
        // authentication fences everything earlier.
        let before = capture_fence(&mut store).unwrap();
        SyncSession::start(&mut store, &binding(Authentication::Resumed)).unwrap();
        assert_eq!(capture_fence(&mut store).unwrap(), before);
        SyncSession::start(&mut store, &binding(Authentication::Fresh)).unwrap();
        assert_eq!(
            capture_fence(&mut store).unwrap().session_generation,
            before.session_generation + 1
        );
    }

    #[test]
    fn sync_session_026_fr_003_another_account_never_binds_and_the_queue_is_never_moved() {
        let path = scratch("other-account");
        let (mut store, mut session) = ready(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Mine");
        session.end(&mut store, EndCause::SignOut).unwrap();
        let after_sign_out = dump(&mut store);

        for other in [
            binding_for("account-2", SCOPE, Authentication::Fresh),
            binding_for(ACCOUNT, "scope-2", Authentication::Fresh),
        ] {
            assert_eq!(
                SyncSession::start(&mut store, &other).unwrap_err(),
                SessionError::AccountMismatch
            );
        }
        let mut other_device = binding(Authentication::Fresh);
        other_device.device_id = Id::parse("device-2").unwrap();
        assert_eq!(
            SyncSession::start(&mut store, &other_device).unwrap_err(),
            SessionError::DeviceMismatch
        );
        // Refusals write nothing: the signed-out queue is exactly as it was.
        assert_eq!(dump(&mut store), after_sign_out);
        assert_eq!(state(&mut store, 1), "queued");
        assert_eq!(
            session
                .begin_request(&mut store, RequestKind::Pull)
                .unwrap_err(),
            SessionError::NotAuthorized
        );
    }

    #[test]
    fn sync_session_026_fr_011_a_late_response_from_a_signed_out_session_is_ignored() {
        let path = scratch("signed-out");
        let (mut store, mut session) = ready(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Mine");
        register(&mut store, &mut session);
        let send = session
            .begin_request(&mut store, RequestKind::Send)
            .unwrap();
        set_state(&mut store, 1, "sending", true);

        session.end(&mut store, EndCause::Revoked).unwrap();
        assert!(send.is_cancelled());
        assert_eq!(send.live_fence().unwrap_err(), SessionError::Cancelled);
        // A transport that ignored the cancel still changes nothing.
        let before = dump(&mut store);
        let late = receipt(GENERATION, &cmd(1), 1);
        assert_eq!(
            apply_receipt(&mut store, &context(), send.fence(), &late).unwrap_err(),
            ApplyError::Stale
        );
        assert_eq!(dump(&mut store), before);
        assert_eq!(state(&mut store, 1), "sending");

        // Signing in again is a new session: the old request stays dead, the old
        // session object cannot come back, and a new request works.
        let mut fresh = SyncSession::start(&mut store, &binding(Authentication::Fresh)).unwrap();
        assert_eq!(
            apply_receipt(&mut store, &context(), send.fence(), &late).unwrap_err(),
            ApplyError::Stale
        );
        assert_eq!(
            session
                .begin_request(&mut store, RequestKind::Pull)
                .unwrap_err(),
            SessionError::NotAuthorized
        );
        let request = fresh.begin_request(&mut store, RequestKind::Send).unwrap();
        let done =
            apply_receipt(&mut store, &context(), request.live_fence().unwrap(), &late).unwrap();
        assert_eq!(done.command_id, cmd(1));
    }

    #[test]
    fn sync_session_026_fr_011_a_newer_session_in_another_process_supersedes_this_one() {
        let path = scratch("superseded");
        let (mut store, mut session) = ready(&path);
        let old = session
            .begin_request(&mut store, RequestKind::Pull)
            .unwrap();
        // The app's second process authenticates again.
        let mut other = open(&path).unwrap();
        SyncSession::start(&mut other, &binding(Authentication::Fresh)).unwrap();
        assert_eq!(
            session
                .begin_request(&mut store, RequestKind::Pull)
                .unwrap_err(),
            SessionError::Superseded
        );
        assert!(old.is_cancelled(), "it dropped its authority and cancelled");
    }

    #[test]
    fn sync_session_026_fr_011_an_account_switch_never_delivers_the_old_accounts_responses() {
        // Account A's store, and the workspace account B gets.
        let (mut a, mut session_a) = ready(&scratch("switch-a"));
        let mut ids = SeqIds(0);
        create_task(&mut a, &mut ids, 1, "A's");
        register(&mut a, &mut session_a);
        let send = session_a.begin_request(&mut a, RequestKind::Send).unwrap();
        set_state(&mut a, 1, "sending", true);
        let mut b = linked(&scratch("switch-b"));
        let mut session_b = SyncSession::start(
            &mut b,
            &binding_for("account-2", "scope-2", Authentication::Fresh),
        )
        .unwrap();

        // A's receipt reaches B's store with matching generation numbers: scope
        // and queue stop it.
        let from_a = receipt(GENERATION, &cmd(1), 1);
        let request = session_b.begin_request(&mut b, RequestKind::Pull).unwrap();
        let before = dump(&mut b);
        assert_eq!(
            apply_receipt(&mut b, &context(), request.live_fence().unwrap(), &from_a).unwrap_err(),
            ApplyError::WrongScope
        );
        assert_eq!(dump(&mut b), before);

        // On A's own store the switch fences the request in transit, and the new
        // account cannot bind to A's file: its queue is not uploaded to B.
        session_a.end(&mut a, EndCause::AccountSwitch).unwrap();
        assert_eq!(
            apply_receipt(&mut a, &context(), send.fence(), &from_a).unwrap_err(),
            ApplyError::Stale
        );
        assert_eq!(
            SyncSession::start(
                &mut a,
                &binding_for("account-2", "scope-2", Authentication::Fresh)
            )
            .unwrap_err(),
            SessionError::AccountMismatch
        );
        assert_eq!(state(&mut a, 1), "sending");
        assert_eq!(capture_fence(&mut a).unwrap().workspace_generation, 2);
    }

    // ------------------------------------------------------------ reset and restore

    #[test]
    fn sync_session_026_fr_010_a_same_session_pre_restore_ack_is_rejected_and_the_lookup_decides() {
        let path = scratch("pre-restore");
        let (mut store, mut session) = ready(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Sent before the restore");
        register(&mut store, &mut session);
        let send = session
            .begin_request(&mut store, RequestKind::Send)
            .unwrap();
        set_state(&mut store, 1, "sending", true);
        let session_before = capture_fence(&mut store).unwrap().session_generation;

        // The server was restored: the reset cancels the request and advances
        // the local-sync generation, still in the same session.
        let reset = error_body(
            "RESET_REQUIRED",
            json!({ "reset_reason": "restore", "epoch_status": "active" }),
        );
        let ErrorAction::Recovered {
            closure: None,
            fence: Some(fence),
        } = session.handle_error(&mut store, &send, &reset).unwrap()
        else {
            panic!("a reset is recovered, the epoch stays");
        };
        assert!(send.is_cancelled());
        assert_eq!(fence.session_generation, session_before);
        assert_eq!(
            fence.local_sync_generation,
            send.fence().local_sync_generation + 1
        );
        let activated = recover_base(&mut store, &fence, RESTORED, 5).unwrap();
        assert_eq!(
            activated.lookups,
            [cmd(1)],
            "the outcome is looked up, not guessed"
        );

        // The pre-restore ACK arrives late. It proves nothing, whatever fence it
        // is applied with.
        let old_ack = receipt(GENERATION, &cmd(1), 3);
        let before = dump(&mut store);
        assert_eq!(
            apply_receipt(&mut store, &context(), send.fence(), &old_ack).unwrap_err(),
            ApplyError::Stale
        );
        let current = capture_fence(&mut store).unwrap();
        assert_eq!(
            apply_receipt(&mut store, &context(), &current, &old_ack).unwrap_err(),
            ApplyError::GenerationChanged
        );
        assert_eq!(dump(&mut store), before);

        // The restored server's receipt, by lookup, settles it.
        let settled = receipt(RESTORED, &cmd(1), 3);
        apply_receipt(&mut store, &context(), &current, &settled).unwrap();
        assert_eq!(state(&mut store, 1), "completed");
    }

    #[test]
    fn sync_session_026_fr_010_the_server_generation_alone_fences_a_request_issued_before_a_restore()
     {
        let path = scratch("server-generation");
        let (mut store, mut session) = ready(&path);
        create_task(&mut store, &mut SeqIds(0), 1, "Sent");
        register(&mut store, &mut session);
        let send = session
            .begin_request(&mut store, RequestKind::Send)
            .unwrap();
        set_state(&mut store, 1, "sending", true);

        // The restored base is activated by another path (no reset in between):
        // only the server generation moved.
        let other = capture_fence(&mut store).unwrap();
        recover_base(&mut store, &other, RESTORED, 5).unwrap();
        let now = capture_fence(&mut store).unwrap();
        assert_eq!(
            now.local_sync_generation,
            send.fence().local_sync_generation
        );
        assert_ne!(now.server_generation, send.fence().server_generation);

        let before = dump(&mut store);
        assert_eq!(
            apply_receipt(
                &mut store,
                &context(),
                send.fence(),
                &receipt(GENERATION, &cmd(1), 3)
            )
            .unwrap_err(),
            ApplyError::Stale
        );
        assert_eq!(dump(&mut store), before);
    }

    #[test]
    fn sync_session_026_fr_010_a_reset_keeps_the_queue_and_drafts_and_sends_wait_for_a_base() {
        let path = scratch("reset");
        let (mut store, mut session) = ready(&path);
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "Queued");
        register(&mut store, &mut session);
        store
            .write(|tx| {
                tx.execute(
                    "INSERT INTO drafts (workspace_id, draft_id, editor_kind, fields, updated_at)
                     VALUES (?1, 'draft-1', 'task', x'7b7d', ?2)",
                    params![WORKSPACE, NOW],
                )?;
                Ok(())
            })
            .unwrap();
        let pull = session
            .begin_request(&mut store, RequestKind::Pull)
            .unwrap();
        let before = capture_fence(&mut store).unwrap();
        let view = epoch_view(&mut store).unwrap();

        let fence = session.reset(&mut store).unwrap();
        assert!(pull.is_cancelled());
        assert_eq!(
            fence.local_sync_generation,
            before.local_sync_generation + 1
        );
        assert_eq!(cursor(&mut store), None, "the base needs recovering");
        assert_eq!(state(&mut store, 1), "queued");
        assert_eq!(drafts(&mut store), 1);
        assert_eq!(
            epoch_view(&mut store).unwrap(),
            view,
            "an ordinary reset keeps the epoch"
        );
        // No send until the recovery base is activated; pulls and lookups go on.
        assert_eq!(
            session
                .begin_request(&mut store, RequestKind::Send)
                .unwrap_err(),
            SessionError::BaseNotActive
        );
        session
            .begin_request(&mut store, RequestKind::Pull)
            .unwrap();
        session
            .begin_request(&mut store, RequestKind::Lookup)
            .unwrap();

        recover_base(&mut store, &fence, GENERATION, 4).unwrap();
        let send = session
            .begin_request(&mut store, RequestKind::Send)
            .unwrap();
        assert_eq!(send.epoch(), Some(&view.epoch.unwrap()));
        assert_eq!(send_candidates(&mut store).unwrap(), [cmd(1)]);
    }

    #[test]
    fn sync_session_026_fr_010_a_second_error_from_a_cancelled_request_does_not_reset_again() {
        let path = scratch("double-reset");
        let (mut store, mut session) = ready(&path);
        let first = session
            .begin_request(&mut store, RequestKind::Pull)
            .unwrap();
        let second = session
            .begin_request(&mut store, RequestKind::Pull)
            .unwrap();
        let reset = error_body(
            "RESET_REQUIRED",
            json!({ "reset_reason": "cursor_expired" }),
        );

        let ErrorAction::Recovered {
            fence: Some(fence), ..
        } = session.handle_error(&mut store, &first, &reset).unwrap()
        else {
            panic!("the first reset is recorded");
        };
        assert_eq!(
            session.handle_error(&mut store, &second, &reset).unwrap(),
            ErrorAction::Ignored
        );
        // The same holds for a request issued by another session object (another
        // process) that did not see the reset happen: the fence is the judge.
        let mut other = SyncSession::start(&mut store, &binding(Authentication::Resumed)).unwrap();
        let stale = other.begin_request(&mut store, RequestKind::Pull).unwrap();
        session.reset(&mut store).unwrap();
        assert_eq!(
            other.handle_error(&mut store, &stale, &reset).unwrap(),
            ErrorAction::Ignored
        );
        assert_eq!(
            capture_fence(&mut store).unwrap().local_sync_generation,
            fence.local_sync_generation + 1
        );
    }

    #[test]
    fn sync_session_026_fr_010_a_download_interrupted_by_a_reset_is_dropped_and_the_old_base_kept()
    {
        let path = scratch("reset-staging");
        let (mut store, mut session) = ready(&path);
        let request = session
            .begin_request(&mut store, RequestKind::Pull)
            .unwrap();
        let (manifest, page) = snapshot("snap-1", GENERATION, 7);
        begin_snapshot(
            &mut store,
            &context(),
            request.live_fence().unwrap(),
            &manifest,
        )
        .unwrap();

        let fence = session.reset(&mut store).unwrap();
        // The page of the cancelled download is refused; the staging is gone.
        assert_eq!(
            stage_snapshot_page(&mut store, &context(), request.fence(), &page).unwrap_err(),
            ApplyError::Stale
        );
        let staged: i64 = store
            .read(|tx| {
                tx.query_row(
                    "SELECT COUNT(*) FROM staging_bases WHERE state IN ('receiving', 'complete')",
                    [],
                    |row| row.get(0),
                )
            })
            .unwrap();
        assert_eq!(staged, 0);
        let done = recover_base(&mut store, &fence, GENERATION, 7).unwrap();
        assert_eq!(done.watermark, 7);
    }

    // ----------------------------------------------------------------- the epoch

    #[test]
    fn sync_session_026_fr_011_registration_confirms_the_same_epoch_and_a_lost_ack_is_retried_unchanged()
     {
        let path = scratch("registration");
        let (mut store, mut session) = ready(&path);
        assert!(
            session.registration(&mut store).unwrap().is_none(),
            "no epoch yet"
        );
        let mut ids = SeqIds(0);
        create_task(&mut store, &mut ids, 1, "First");
        let saved = envelope(&mut store, 1);
        let pending = epoch_id(&mut store);
        assert_eq!(
            epoch_view(&mut store).unwrap().state,
            EpochState::PendingRegistration
        );
        // Nothing is sent from a pending epoch.
        assert_eq!(
            session
                .begin_request(&mut store, RequestKind::Send)
                .unwrap_err(),
            SessionError::EpochState(EpochState::PendingRegistration)
        );
        assert!(send_candidates(&mut store).unwrap().is_empty());

        let (request, body) = session.registration(&mut store).unwrap().unwrap();
        assert_eq!(body.device_epoch, pending);
        assert_eq!(
            (body.scope_id.as_str(), body.device_id.as_str()),
            (SCOPE, DEVICE)
        );
        // The ACK is lost: the retry names the very same epoch.
        let (retry, again) = session.registration(&mut store).unwrap().unwrap();
        assert_eq!(again, body);

        let ack = registration_ack(&pending, SCOPE, GENERATION);
        let done = apply_registration(&mut store, request.live_fence().unwrap(), &ack).unwrap();
        assert!(done.newly_active);
        let done = apply_registration(&mut store, retry.live_fence().unwrap(), &ack).unwrap();
        assert!(!done.newly_active, "applying it again changes nothing");
        assert_eq!(epoch_view(&mut store).unwrap().state, EpochState::Active);
        assert!(session.registration(&mut store).unwrap().is_none());
        // The envelope was not rewritten, and it can be sent now.
        assert_eq!(envelope(&mut store, 1), saved);
        assert_eq!(saved.0, pending.as_str());
        assert_eq!(send_candidates(&mut store).unwrap(), [cmd(1)]);
        session
            .begin_request(&mut store, RequestKind::Send)
            .unwrap();
    }

    #[test]
    fn sync_session_026_fr_011_a_stale_registration_ack_is_rejected_after_a_reset() {
        let path = scratch("stale-registration");
        let (mut store, mut session) = ready(&path);
        create_task(&mut store, &mut SeqIds(0), 1, "First");
        let (request, body) = session.registration(&mut store).unwrap().unwrap();
        let ack = registration_ack(&body.device_epoch, SCOPE, GENERATION);

        let fence = session.reset(&mut store).unwrap();
        assert_eq!(
            apply_registration(&mut store, request.fence(), &ack).unwrap_err(),
            ApplyError::Stale
        );
        assert_eq!(
            epoch_view(&mut store).unwrap().state,
            EpochState::PendingRegistration
        );
        // Registration also waits for the recovery base, and then asks again with
        // the same epoch ID under the new fences.
        assert_eq!(
            session.registration(&mut store).unwrap_err(),
            SessionError::BaseNotActive
        );
        recover_base(&mut store, &fence, GENERATION, 2).unwrap();
        let (retry, again) = session.registration(&mut store).unwrap().unwrap();
        assert_eq!(again, body);
        apply_registration(&mut store, retry.live_fence().unwrap(), &ack).unwrap();
        assert_eq!(epoch_view(&mut store).unwrap().state, EpochState::Active);
    }

    #[test]
    fn sync_session_026_fr_011_registration_needs_current_authority_scope_and_generation() {
        let path = scratch("authority");
        let (mut store, mut session) = ready(&path);
        create_task(&mut store, &mut SeqIds(0), 1, "First");
        let (request, body) = session.registration(&mut store).unwrap().unwrap();
        let epoch = body.device_epoch.clone();
        let fence = request.live_fence().unwrap();
        let before = dump(&mut store);

        for (ack, expected) in [
            (
                registration_ack(&epoch, "scope-2", GENERATION),
                ApplyError::WrongScope,
            ),
            (
                registration_ack(&epoch, SCOPE, RESTORED),
                ApplyError::GenerationChanged,
            ),
            (
                registration_ack(&Id::parse("epoch-other").unwrap(), SCOPE, GENERATION),
                ApplyError::Stale,
            ),
        ] {
            assert_eq!(
                apply_registration(&mut store, fence, &ack).unwrap_err(),
                expected
            );
        }
        assert_eq!(dump(&mut store), before);

        // Access revoked: no registration is built, and the ACK in transit dies.
        session.end(&mut store, EndCause::Revoked).unwrap();
        let ack = registration_ack(&epoch, SCOPE, GENERATION);
        assert_eq!(
            apply_registration(&mut store, request.fence(), &ack).unwrap_err(),
            ApplyError::Stale
        );
        assert_eq!(
            session.registration(&mut store).unwrap_err(),
            SessionError::NotAuthorized
        );
        assert_eq!(
            epoch_view(&mut store).unwrap().state,
            EpochState::PendingRegistration
        );
    }

    #[test]
    fn sync_session_026_fr_005_a_closed_epoch_keeps_its_envelopes_and_is_never_reopened() {
        let path = scratch("closed");
        let (mut store, mut session) = ready(&path);
        let mut ids = SeqIds(0);
        let task = create_task(&mut store, &mut ids, 1, "Sent");
        edit(&mut store, &mut ids, 2, &task, "Edited", "1");
        let epoch = register(&mut store, &mut session);
        set_state(&mut store, 1, "unknown", true);
        let saved = (envelope(&mut store, 1), envelope(&mut store, 2));

        let send = session
            .begin_request(&mut store, RequestKind::Send)
            .unwrap();
        let closed = error_body("EPOCH_CLOSED", json!({ "epoch_status": "closed" }));
        let action = session.handle_error(&mut store, &send, &closed).unwrap();
        let ErrorAction::Recovered {
            closure: Some(closure),
            fence: None,
        } = action
        else {
            panic!("an explicit closure is recorded without a reset");
        };
        assert!(closure.closed);
        assert_eq!(
            closure.lookups,
            [cmd(1)],
            "the possibly-sent command is looked up"
        );
        assert_eq!(
            closure.held,
            [cmd(2)],
            "the unsent one is held, not rekeyed"
        );
        assert_eq!(epoch_view(&mut store).unwrap().state, EpochState::Closed);
        assert_eq!((envelope(&mut store, 1), envelope(&mut store, 2)), saved);
        assert_eq!(state(&mut store, 1), "unknown");
        assert!(send_candidates(&mut store).unwrap().is_empty());

        // Closing again reports the same; registration never reopens it.
        let current = capture_fence(&mut store).unwrap();
        let again = close_epoch(&mut store, &current, &epoch).unwrap();
        assert!(!again.closed);
        assert_eq!(again.lookups, closure.lookups);
        let ack = registration_ack(&epoch, SCOPE, GENERATION);
        let fence = capture_fence(&mut store).unwrap();
        assert_eq!(
            apply_registration(&mut store, &fence, &ack).unwrap_err(),
            ApplyError::Contradiction("registration of an epoch that is closed")
        );
        assert_eq!(epoch_view(&mut store).unwrap().state, EpochState::Closed);
        assert!(session.registration(&mut store).unwrap().is_none());
    }

    #[test]
    fn sync_session_026_fr_010_a_reset_closes_the_epoch_only_when_the_server_says_so() {
        let path = scratch("reset-closes");
        let (mut store, mut session) = ready(&path);
        create_task(&mut store, &mut SeqIds(0), 1, "Sent");
        register(&mut store, &mut session);
        let send = session
            .begin_request(&mut store, RequestKind::Send)
            .unwrap();
        let reset = error_body(
            "RESET_REQUIRED",
            json!({ "reset_reason": "restore", "epoch_status": "closed" }),
        );

        let ErrorAction::Recovered {
            closure: Some(closure),
            fence: Some(_),
        } = session.handle_error(&mut store, &send, &reset).unwrap()
        else {
            panic!("a restore that closes the epoch records both, together");
        };
        assert!(closure.closed);
        assert_eq!(epoch_view(&mut store).unwrap().state, EpochState::Closed);
        assert_eq!(cursor(&mut store), None);
    }

    #[test]
    fn sync_session_026_sc_002_independent_new_work_proceeds_after_closure_and_recovery_while_the_old_dependent_stays_blocked()
     {
        let path = scratch("independent");
        let (mut store, mut session) = ready(&path);
        let mut ids = SeqIds(0);
        let task = create_task(&mut store, &mut ids, 1, "Old and uncertain");
        let epoch = register(&mut store, &mut session);
        set_state(&mut store, 1, "unknown", true);
        let old = envelope(&mut store, 1);

        // The server closes the epoch and a restore resets the base.
        let send = session
            .begin_request(&mut store, RequestKind::Send)
            .unwrap();
        let closed = error_body(
            "RESET_REQUIRED",
            json!({ "reset_reason": "restore", "epoch_status": "closed" }),
        );
        let ErrorAction::Recovered {
            fence: Some(fence), ..
        } = session.handle_error(&mut store, &send, &closed).unwrap()
        else {
            panic!("recovered");
        };

        // The user keeps working: one independent capture, and one edit of the
        // uncertain task, which depends on it.
        create_task(&mut store, &mut ids, 2, "Independent");
        edit(
            &mut store,
            &mut ids,
            3,
            &task,
            "Built on the uncertain one",
            "1",
        );
        let fresh = epoch_id(&mut store);
        assert_ne!(fresh, epoch, "new work gets its own pending epoch");
        assert_eq!(
            epoch_view(&mut store).unwrap().state,
            EpochState::PendingRegistration
        );
        assert_eq!(envelope(&mut store, 2).0, fresh.as_str());
        assert_eq!(
            envelope(&mut store, 1),
            old,
            "the old envelope is untouched"
        );

        // Nothing moves until the base is recovered and the fresh epoch registered.
        assert_eq!(
            session.registration(&mut store).unwrap_err(),
            SessionError::BaseNotActive
        );
        recover_base(&mut store, &fence, RESTORED, 9).unwrap();
        assert!(send_candidates(&mut store).unwrap().is_empty());
        let (request, body) = session.registration(&mut store).unwrap().unwrap();
        assert_eq!(
            body.device_epoch, fresh,
            "that same ID is what gets registered"
        );
        let ack = {
            let ack = registration_ack(&fresh, SCOPE, RESTORED);
            apply_registration(&mut store, request.live_fence().unwrap(), &ack).unwrap();
            ack
        };
        assert_eq!(ack.device_epoch, fresh);

        // The independent capture may be sent; the dependent edit and the old
        // uncertain command may not, and the uncertain one is still to be looked up.
        assert_eq!(send_candidates(&mut store).unwrap(), [cmd(2)]);
        assert_eq!(state(&mut store, 1), "unknown");
        assert_eq!(state(&mut store, 3), "queued");
        let send = session
            .begin_request(&mut store, RequestKind::Send)
            .unwrap();
        assert_eq!(send.epoch(), Some(&fresh));

        // Once the lookup settles the old command, its dependant is released.
        let current = capture_fence(&mut store).unwrap();
        apply_receipt(
            &mut store,
            &context(),
            &current,
            &receipt(RESTORED, &cmd(1), 4),
        )
        .unwrap();
        assert_eq!(state(&mut store, 1), "completed");
        assert_eq!(send_candidates(&mut store).unwrap()[0], cmd(2));
    }

    // ------------------------------------------------------- unsupported versions

    #[test]
    fn sync_session_026_fr_012_an_unsupported_server_version_stops_sync_and_keeps_store_and_queue()
    {
        let path = scratch("upgrade");
        let (mut store, mut session) = ready(&path);
        create_task(&mut store, &mut SeqIds(0), 1, "Kept");
        register(&mut store, &mut session);
        set_state(&mut store, 1, "unknown", true);
        let send = session
            .begin_request(&mut store, RequestKind::Send)
            .unwrap();
        let before = dump(&mut store);

        let upgrade = error_body("UPGRADE_REQUIRED", json!({ "reason": "command_version" }));
        assert_eq!(
            session.handle_error(&mut store, &send, &upgrade).unwrap(),
            ErrorAction::UpdateRequired
        );
        assert_eq!(dump(&mut store), before, "nothing was written");
        for kind in [RequestKind::Pull, RequestKind::Register, RequestKind::Send] {
            assert_eq!(
                session.begin_request(&mut store, kind).unwrap_err(),
                SessionError::UpgradeRequired { found: None }
            );
        }
        assert_eq!(
            session.reset(&mut store).unwrap_err(),
            SessionError::UpgradeRequired { found: None }
        );
        // Known receipts stay reachable.
        session
            .begin_request(&mut store, RequestKind::Lookup)
            .unwrap();
        assert_eq!(dump(&mut store), before);
    }

    fn capabilities_in(versions: Value, scope: &str, generation: &str) -> Capabilities {
        decode(
            &with_common_in(
                json!({
                    "protocol_versions": versions, "command_versions": [],
                    "rule_version": "rules-1", "projection_schema_version": 1,
                    "storage_epoch": "epoch-1", "feed_generation": "feed-1",
                    "scope_enabled": true, "limits": {}, "recovery": {},
                }),
                scope,
                generation,
            )
            .to_string(),
        )
        .unwrap()
    }

    #[test]
    fn sync_session_026_fr_012_a_server_without_this_protocol_requires_an_update_and_writes_nothing()
     {
        let path = scratch("capabilities");
        let (mut store, mut session) = ready(&path);
        create_task(&mut store, &mut SeqIds(0), 1, "Kept");
        let before = dump(&mut store);
        let check = |session: &mut SyncSession, store: &mut Store, versions: Value| {
            let request = session
                .begin_request(store, RequestKind::Capabilities)
                .unwrap();
            let capabilities = capabilities_in(versions, SCOPE, GENERATION);
            session.check_capabilities(store, &request, &capabilities)
        };
        assert_eq!(
            check(&mut session, &mut store, json!([1, 2])).unwrap(),
            CapabilitiesCheck::Supported
        );
        session
            .begin_request(&mut store, RequestKind::Pull)
            .unwrap();
        assert_eq!(
            check(&mut session, &mut store, json!([2])).unwrap_err(),
            SessionError::UpgradeRequired { found: None }
        );
        assert_eq!(
            session
                .begin_request(&mut store, RequestKind::Pull)
                .unwrap_err(),
            SessionError::UpgradeRequired { found: None }
        );
        // Capabilities can be re-checked while an update is required.
        assert_eq!(
            check(&mut session, &mut store, json!([1])).unwrap(),
            CapabilitiesCheck::Supported
        );
        assert_eq!(dump(&mut store), before);
    }

    #[test]
    fn sync_session_026_fr_012_a_stale_or_foreign_capabilities_answer_never_blocks_current_sync() {
        let path = scratch("capabilities-stale");
        let (mut store, mut session) = ready(&path);
        let unsupported =
            |scope: &str, generation: &str| capabilities_in(json!([2]), scope, generation);
        let issue = |session: &mut SyncSession, store: &mut Store| {
            session
                .begin_request(store, RequestKind::Capabilities)
                .unwrap()
        };

        // Issued before a reset: cancelled and fenced out.
        let before_reset = issue(&mut session, &mut store);
        let fence = session.reset(&mut store).unwrap();
        recover_base(&mut store, &fence, GENERATION, 3).unwrap();
        // Issued before a restore (only the server generation moves).
        let before_restore = issue(&mut session, &mut store);
        let other = capture_fence(&mut store).unwrap();
        recover_base(&mut store, &other, RESTORED, 6).unwrap();
        // Issued before a newer session started in another process.
        let before_session = issue(&mut session, &mut store);
        let mut other_process = open(&path).unwrap();
        SyncSession::start(&mut other_process, &binding(Authentication::Fresh)).unwrap();
        for (request, generation) in [
            (&before_reset, GENERATION),
            (&before_restore, GENERATION),
            (&before_session, RESTORED),
        ] {
            assert_eq!(
                session
                    .check_capabilities(&mut store, request, &unsupported(SCOPE, generation))
                    .unwrap(),
                CapabilitiesCheck::Ignored
            );
        }

        // A new session: a foreign scope or another generation is ignored too and
        // sync stays enabled; a current answer does set update-required.
        let mut session =
            SyncSession::start(&mut store, &binding(Authentication::Resumed)).unwrap();
        let request = issue(&mut session, &mut store);
        for (scope, generation) in [("scope-2", RESTORED), (SCOPE, GENERATION)] {
            assert_eq!(
                session
                    .check_capabilities(&mut store, &request, &unsupported(scope, generation))
                    .unwrap(),
                CapabilitiesCheck::Ignored
            );
        }
        session
            .begin_request(&mut store, RequestKind::Pull)
            .unwrap();
        assert_eq!(
            session
                .check_capabilities(&mut store, &request, &unsupported(SCOPE, RESTORED))
                .unwrap_err(),
            SessionError::UpgradeRequired { found: None }
        );
        assert_eq!(
            session
                .begin_request(&mut store, RequestKind::Pull)
                .unwrap_err(),
            SessionError::UpgradeRequired { found: None }
        );
    }

    /// A request issued before `how` happened, and the session after it.
    fn late_error_after(how: &str, name: &str) -> (Store, SyncSession, bb_client::Request) {
        let path = scratch(name);
        let (mut store, mut session) = ready(&path);
        let request = session
            .begin_request(&mut store, RequestKind::Pull)
            .unwrap();
        match how {
            // A same-session restore: only the server generation moved, and the
            // request's cancel flag stays false.
            "restore" => {
                let other = capture_fence(&mut store).unwrap();
                recover_base(&mut store, &other, RESTORED, 5).unwrap();
            }
            // A newer session started by another process.
            _ => {
                let mut other = open(&path).unwrap();
                SyncSession::start(&mut other, &binding(Authentication::Fresh)).unwrap();
            }
        }
        assert!(!request.is_cancelled());
        (store, session, request)
    }

    #[test]
    fn sync_session_026_fr_011_a_late_auth_failure_leaves_the_current_session_authorised() {
        for how in ["restore", "newer-session"] {
            let (mut store, mut session, request) =
                late_error_after(how, &format!("late-auth-{how}"));
            let error = error_body("AUTH_REQUIRED", json!({}));
            assert_eq!(
                session.handle_error(&mut store, &request, &error).unwrap(),
                ErrorAction::Ignored,
                "{how}"
            );
            if how == "restore" {
                // Still authorised, and the current request was not cancelled.
                let current = session
                    .begin_request(&mut store, RequestKind::Pull)
                    .unwrap();
                assert!(!current.is_cancelled());
            }
        }
    }

    #[test]
    fn sync_session_026_fr_012_a_late_upgrade_failure_leaves_current_sync_enabled() {
        for how in ["restore", "newer-session"] {
            let (mut store, mut session, request) =
                late_error_after(how, &format!("late-upgrade-{how}"));
            let error = error_body("UPGRADE_REQUIRED", json!({ "reason": "command_version" }));
            assert_eq!(
                session.handle_error(&mut store, &request, &error).unwrap(),
                ErrorAction::Ignored,
                "{how}"
            );
            if how == "restore" {
                session
                    .begin_request(&mut store, RequestKind::Pull)
                    .unwrap();
            }
        }
    }

    #[test]
    fn sync_session_026_fr_012_a_store_from_a_newer_build_opens_read_only_and_never_syncs() {
        let path = scratch("newer-store");
        let (mut store, _) = ready(&path);
        create_task(&mut store, &mut SeqIds(0), 1, "Kept");
        store.close().unwrap();
        let newer = bb_client::SCHEMA_VERSION + 1;
        Connection::open(&path)
            .unwrap()
            .pragma_update(None, "user_version", newer)
            .unwrap();

        let mut store = open(&path).unwrap();
        assert_eq!(
            store.status(),
            StoreStatus::ReadOnlyRecovery { found: newer }
        );
        assert_eq!(
            SyncSession::start(&mut store, &binding(Authentication::Fresh)).unwrap_err(),
            SessionError::UpgradeRequired { found: Some(newer) }
        );
        // The queue is still readable and nothing was changed.
        assert_eq!(state(&mut store, 1), "queued");
        assert_eq!(dump(&mut store)[0].split(' ').nth(1), Some("1"));
    }

    #[test]
    fn sync_session_026_fr_011_an_authentication_failure_pauses_without_losing_intents() {
        let path = scratch("paused");
        let (mut store, mut session) = ready(&path);
        create_task(&mut store, &mut SeqIds(0), 1, "Kept");
        let pull = session
            .begin_request(&mut store, RequestKind::Pull)
            .unwrap();
        let before = dump(&mut store);
        assert_eq!(
            session
                .handle_error(&mut store, &pull, &error_body("AUTH_REQUIRED", json!({})))
                .unwrap(),
            ErrorAction::Paused
        );
        assert_eq!(dump(&mut store), before);
        assert_eq!(
            session
                .begin_request(&mut store, RequestKind::Pull)
                .unwrap_err(),
            SessionError::NotAuthorized
        );
        // Re-authenticating is a new session; the queue is still there.
        let mut again = SyncSession::start(&mut store, &binding(Authentication::Fresh)).unwrap();
        again.begin_request(&mut store, RequestKind::Pull).unwrap();
        assert_eq!(state(&mut store, 1), "queued");
        // Rate limits and the like record nothing.
        let limited = again.begin_request(&mut store, RequestKind::Pull).unwrap();
        let before = dump(&mut store);
        assert_eq!(
            again
                .handle_error(
                    &mut store,
                    &limited,
                    &error_body("RATE_LIMITED", json!({ "retry_after_seconds": 5 }))
                )
                .unwrap(),
            ErrorAction::Unchanged
        );
        assert_eq!(dump(&mut store), before);
    }

    // --------------------------------------------------------- process restarts

    #[test]
    fn sync_session_026_sc_002_a_pending_epoch_survives_a_process_kill_and_registers_with_the_same_id()
     {
        let path = scratch("kill-capture");
        linked(&path).close().unwrap();

        let mut child = spawn("capture_and_abort", &path, "");
        wait_for(&mut child, "captured");
        assert!(!child.wait().unwrap().success(), "the child aborts");

        // Restart: the capture, its epoch and its projection are all there.
        let mut store = open(&path).unwrap();
        assert_eq!(state(&mut store, 1), "queued");
        let view = epoch_view(&mut store).unwrap();
        assert_eq!(view.state, EpochState::PendingRegistration);
        let pending = view.epoch.unwrap();
        assert_eq!(envelope(&mut store, 1).0, pending.as_str());

        // A resumed session registers that very ID.
        let mut session =
            SyncSession::start(&mut store, &binding(Authentication::Resumed)).unwrap();
        let (_, body) = session.registration(&mut store).unwrap().unwrap();
        assert_eq!(body.device_epoch, pending);
        // A second capture joins the same epoch rather than starting another.
        create_task(&mut store, &mut SeqIds(100), 2, "Second");
        assert_eq!(envelope(&mut store, 2).0, pending.as_str());
    }

    #[test]
    fn sync_session_026_sc_002_a_registration_committed_before_a_kill_is_idempotent_on_restart() {
        let path = scratch("kill-register");
        let mut store = linked(&path);
        create_task(&mut store, &mut SeqIds(0), 1, "Captured");
        let pending = epoch_id(&mut store);
        store.close().unwrap();
        let ack = registration_ack(&pending, SCOPE, GENERATION);
        let ack_json = serde_json::to_string(&ack).unwrap();

        let mut child = spawn("register_and_abort", &path, &ack_json);
        wait_for(&mut child, "registered");
        assert!(!child.wait().unwrap().success(), "the child aborts");

        // The ACK committed, though nobody heard: restart sees an active epoch,
        // and the retried ACK changes nothing.
        let mut store = open(&path).unwrap();
        assert_eq!(epoch_view(&mut store).unwrap().state, EpochState::Active);
        let mut session =
            SyncSession::start(&mut store, &binding(Authentication::Resumed)).unwrap();
        assert!(session.registration(&mut store).unwrap().is_none());
        let fence = capture_fence(&mut store).unwrap();
        let again = apply_registration(&mut store, &fence, &ack).unwrap();
        assert!(!again.newly_active);
        assert_eq!(send_candidates(&mut store).unwrap(), [cmd(1)]);
    }
}
