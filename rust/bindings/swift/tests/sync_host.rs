//! The Apple sync host (`BridgeSyncHost`): the PR-40 loop and hint watcher behind the callback
//! ports the Swift adapter implements. The ports are plain traits, so the tests play the OS
//! adapter in Rust over a small scripted server and check what the host asks of it: every call
//! goes through `BridgeTransport` (no credential, no socket here), cancellation reaches a call
//! in flight, the foreground starts the hint stream, a rebuild takes a snapshot, and an
//! unsupported server stops sync without losing anything.

use bb_client::{OpenOptions, Store};
use bb_swift::{
    BridgeCancel, BridgeExecuteContext, BridgeHintReader, BridgeHintStream, BridgeHttpMethod,
    BridgeHttpRequest, BridgeHttpResponse, BridgeRebuildOutcome, BridgeStreamError,
    BridgeSyncConfig, BridgeSyncHost, BridgeSyncObserver, BridgeSyncReport, BridgeSyncState,
    BridgeTransport, BridgeTransportError, BridgeWake,
};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{Receiver, Sender, channel};
use std::sync::{Arc, Mutex};
use std::time::Duration;

const SCOPE: &str = "scope-1";
const NOW: &str = "2026-10-10T09:00:00Z";

fn scratch(name: &str) -> PathBuf {
    let directory =
        std::env::temp_dir().join(format!("bb-sync-host-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&directory);
    directory.join("workspace.sqlite3")
}

fn open(path: &Path) -> Store {
    Store::open(&OpenOptions {
        path: path.to_path_buf(),
        workspace_id: "workspace-local".to_owned(),
        busy_timeout: Duration::from_millis(2_000),
    })
    .unwrap()
}

/// A store that holds an account link and a recovery base (cursor 0 of `generation-1`).
fn linked(name: &str) -> PathBuf {
    let path = scratch(name);
    let mut store = open(&path);
    store
        .write(|tx| {
            tx.execute(
                "UPDATE sync_meta SET server_generation = 'generation-1', cursor = 'cursor-0',
                    base_watermark = '0', account_link_state = 'linked'",
                [],
            )?;
            Ok(())
        })
        .unwrap();
    path
}

fn config(path: &Path) -> BridgeSyncConfig {
    BridgeSyncConfig {
        workspace_id: "workspace-local".to_owned(),
        database_path: path.to_string_lossy().into_owned(),
        busy_timeout_ms: 2_000,
        account_id: "account-1".to_owned(),
        scope_id: SCOPE.to_owned(),
        device_id: "device-1".to_owned(),
        fresh_authentication: true,
        context: BridgeExecuteContext {
            now: NOW.to_owned(),
            time_zone: "UTC".to_owned(),
            actor_id: "actor-local".to_owned(),
            policy: serde_json::to_vec(&json!({
                "weekly_review": false,
                "navigator_provider": null,
                "navigator_available": false,
                "consent_text_version": 1,
            }))
            .unwrap(),
        },
        poll_interval_ms: None,
    }
}

fn base64(bytes: &[u8]) -> String {
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

fn common(mut body: Value) -> Value {
    body["correlation_id"] = json!("corr-1");
    body["scope_id"] = json!(SCOPE);
    body["server_generation"] = json!("generation-1");
    body["server_now"] = json!(NOW);
    body
}

/// A server with an empty feed whose capabilities name the protocol versions it speaks.
struct Server {
    versions: Vec<u32>,
    log: Mutex<Vec<(BridgeHttpMethod, String)>>,
}

impl Server {
    fn new(versions: &[u32]) -> Arc<Self> {
        Arc::new(Self {
            versions: versions.to_vec(),
            log: Mutex::new(Vec::new()),
        })
    }

    fn paths(&self) -> Vec<String> {
        self.log
            .lock()
            .unwrap()
            .iter()
            .map(|(_, path)| path.clone())
            .collect()
    }

    fn answer(&self, request: &BridgeHttpRequest) -> Value {
        let path = request.path.split('?').next().unwrap();
        match (request.method, path) {
            (BridgeHttpMethod::Get, "/api/sync/v1/capabilities") => common(json!({
                "protocol_versions": self.versions, "command_versions": [], "rule_version": 1,
                "projection_schema_version": 1, "storage_epoch": 1,
                "feed_generation": "feed-1", "scope_enabled": true,
                "limits": {}, "recovery": {},
            })),
            (BridgeHttpMethod::Get, "/api/sync/v1/changes") => common(json!({
                "from_cursor": "cursor-0", "transactions": [], "has_more": false,
                "next_cursor": "cursor-0", "high_watermark": "0",
            })),
            (BridgeHttpMethod::Post, "/api/sync/v1/snapshots") => {
                let stream = b"[]";
                common(json!({
                    "snapshot_id": "snap-0", "watermark": "0", "cursor": "cursor-0",
                    "page_count": 1, "record_count": 0, "total_bytes": stream.len(),
                    "sha256": bb_client::sha256_hex(stream),
                    "expires_at": "2026-10-10T09:30:00Z", "first_page_token": "token-0",
                }))
            }
            (BridgeHttpMethod::Get, path) if path.starts_with("/api/sync/v1/snapshots/") => {
                let stream = b"[]";
                common(json!({
                    "snapshot_id": "snap-0", "watermark": "0", "page_index": 0,
                    "payload_base64": base64(stream), "page_sha256": bb_client::sha256_hex(stream),
                    "has_more": false, "next_page_token": null,
                }))
            }
            other => panic!("unmodelled route {other:?}"),
        }
    }
}

impl BridgeTransport for Server {
    fn send(
        &self,
        request: BridgeHttpRequest,
        _cancel: Arc<BridgeCancel>,
    ) -> Result<BridgeHttpResponse, BridgeTransportError> {
        self.log
            .lock()
            .unwrap()
            .push((request.method, request.path.clone()));
        Ok(BridgeHttpResponse {
            status: 200,
            retry_after_ms: None,
            body: self.answer(&request).to_string().into_bytes(),
        })
    }
}

struct Hints {
    opened: Sender<(String, u64)>,
    cancelled: Sender<()>,
}

struct Silence(Arc<BridgeCancel>);

impl BridgeHintReader for Silence {
    fn read(&self, _max_len: u32, cancel: Arc<BridgeCancel>) -> Result<Vec<u8>, BridgeStreamError> {
        while !cancel.is_cancelled() {
            std::thread::sleep(Duration::from_millis(5));
        }
        self.0.raise();
        Err(BridgeStreamError::Cancelled)
    }
}

impl BridgeHintStream for Hints {
    fn open_stream(
        &self,
        path: String,
        idle_ms: u64,
        cancel: Arc<BridgeCancel>,
    ) -> Result<Arc<dyn BridgeHintReader>, BridgeStreamError> {
        self.opened.send((path, idle_ms)).unwrap();
        let signal = BridgeCancel::new();
        let cancelled = self.cancelled.clone();
        let watched = Arc::clone(&signal);
        std::thread::spawn(move || {
            while !watched.is_cancelled() {
                std::thread::sleep(Duration::from_millis(5));
            }
            let _ = cancelled.send(());
        });
        drop(cancel);
        Ok(Arc::new(Silence(signal)))
    }
}

struct Rounds(Mutex<Sender<BridgeSyncReport>>);

impl BridgeSyncObserver for Rounds {
    fn round_finished(&self, report: BridgeSyncReport) {
        let _ = self.0.lock().unwrap().send(report);
    }
}

struct Rig {
    host: Arc<BridgeSyncHost>,
    rounds: Receiver<BridgeSyncReport>,
    opened: Receiver<(String, u64)>,
    hint_cancelled: Receiver<()>,
}

fn rig(path: &Path, transport: Arc<dyn BridgeTransport>) -> Rig {
    let (round_sender, rounds) = channel();
    let (opened_sender, opened) = channel();
    let (cancelled_sender, hint_cancelled) = channel();
    let host = BridgeSyncHost::start(
        config(path),
        transport,
        Arc::new(Hints {
            opened: opened_sender,
            cancelled: cancelled_sender,
        }),
        Arc::new(Rounds(Mutex::new(round_sender))),
    )
    .unwrap();
    Rig {
        host,
        rounds,
        opened,
        hint_cancelled,
    }
}

const WAIT: Duration = Duration::from_secs(20);

#[test]
fn host_026_fr_001_an_unlinked_store_is_refused_before_anything_runs() {
    let path = scratch("unlinked");
    drop(open(&path));
    let (sender, _rounds) = channel();
    let refused = BridgeSyncHost::start(
        config(&path),
        Server::new(&[1]),
        Arc::new(Hints {
            opened: channel().0,
            cancelled: channel().0,
        }),
        Arc::new(Rounds(Mutex::new(sender))),
    );
    let Err(bb_swift::BridgeError::Failed { code, .. }) = refused else {
        panic!("an unlinked store must not start a host");
    };
    assert_eq!(code, "LINK_REQUIRED");
}

#[test]
fn host_026_fr_005_foreground_pulls_through_the_transport_and_opens_the_hint_stream() {
    let server = Server::new(&[1]);
    let path = linked("foreground");
    let rig = rig(&path, server.clone());
    // Nothing runs, and nothing is opened, until the app is in the foreground.
    assert!(rig.rounds.recv_timeout(Duration::from_millis(300)).is_err());
    assert!(rig.opened.try_recv().is_err());

    rig.host.signal(BridgeWake::Foreground);
    let report = rig.rounds.recv_timeout(WAIT).unwrap();
    assert_eq!(report.state, BridgeSyncState::Synced, "{report:?}");
    let paths = server.paths();
    assert!(
        paths[0].starts_with("/api/sync/v1/capabilities?scope_id=scope-1"),
        "{paths:?}"
    );
    assert!(
        paths
            .iter()
            .any(|path| path.starts_with("/api/sync/v1/changes?")),
        "{paths:?}"
    );
    assert!(
        paths.iter().all(|path| path.starts_with("/api/")),
        "origin-relative: {paths:?}"
    );

    let (stream, idle) = rig.opened.recv_timeout(WAIT).unwrap();
    assert_eq!(stream, "/api/sync/v1/hints?scope_id=scope-1");
    assert_eq!(
        idle, 40_000,
        "the stream's idle timeout is the crate's 40 seconds"
    );
    // The stream opening is itself a wake: it catches up at once.
    assert!(rig.rounds.recv_timeout(WAIT).is_ok());

    // Backgrounding closes the stream (its read sees the cancellation) and stops pulls.
    rig.host.background();
    rig.hint_cancelled.recv_timeout(WAIT).unwrap();
    rig.host.stop();
}

#[test]
fn host_026_fr_010_rebuild_resets_to_a_snapshot_and_reports_it() {
    let server = Server::new(&[1]);
    let path = linked("rebuild");
    let rig = rig(&path, server.clone());
    let BridgeRebuildOutcome::Rebuilt = rig.host.rebuild() else {
        panic!("the snapshot recovery should finish");
    };
    let paths = server.paths();
    assert!(
        paths.iter().any(|path| path == "/api/sync/v1/snapshots"),
        "{paths:?}"
    );
    assert!(
        paths
            .iter()
            .any(|path| path.starts_with("/api/sync/v1/snapshots/snap-0")),
        "{paths:?}"
    );
    // The new base is the snapshot's cursor.
    let mut store = open(&path);
    let cursor: Option<String> = store
        .read(|tx| tx.query_row("SELECT cursor FROM sync_meta", [], |row| row.get(0)))
        .unwrap();
    assert_eq!(cursor.as_deref(), Some("cursor-0"));
    rig.host.stop();
    let BridgeRebuildOutcome::Failed { code } = rig.host.rebuild() else {
        panic!("a stopped host rebuilds nothing");
    };
    assert_eq!(code, "WORKSPACE_CLOSED");
}

#[test]
fn host_026_fr_017_a_newer_server_stops_sync_as_update_required() {
    let server = Server::new(&[99]);
    let path = linked("update");
    let rig = rig(&path, server.clone());
    rig.host.signal(BridgeWake::Foreground);
    let report = rig.rounds.recv_timeout(WAIT).unwrap();
    assert_eq!(report.state, BridgeSyncState::UpdateRequired, "{report:?}");
    assert_eq!(report.failure_code.as_deref(), Some("UPGRADE_REQUIRED"));
    assert!(
        report
            .invalidation
            .is_some_and(|value| value.status_changed)
    );
    rig.host.stop();
}

/// Holds every call until its token is raised: proves `stop` reaches a call in flight.
struct Hanging(Mutex<Sender<()>>);

impl BridgeTransport for Hanging {
    fn send(
        &self,
        _request: BridgeHttpRequest,
        cancel: Arc<BridgeCancel>,
    ) -> Result<BridgeHttpResponse, BridgeTransportError> {
        self.0.lock().unwrap().send(()).unwrap();
        while !cancel.is_cancelled() {
            std::thread::sleep(Duration::from_millis(5));
        }
        Err(BridgeTransportError::Cancelled)
    }
}

#[test]
fn host_026_fr_005_stop_cancels_a_call_in_flight_and_returns() {
    let (started, in_flight) = channel();
    let path = linked("stop");
    let rig = rig(&path, Arc::new(Hanging(Mutex::new(started))));
    rig.host.signal(BridgeWake::Foreground);
    in_flight.recv_timeout(WAIT).unwrap();
    let began = std::time::Instant::now();
    rig.host.stop();
    assert!(
        began.elapsed() < Duration::from_secs(5),
        "stop waited for the network"
    );
    // Idempotent, and later signals are inert.
    rig.host.stop();
    rig.host.signal(BridgeWake::Manual);
}

/// Every failure the transport can report ends the round in the matching state.
struct Failing(BridgeTransportError);

impl BridgeTransport for Failing {
    fn send(
        &self,
        _request: BridgeHttpRequest,
        _cancel: Arc<BridgeCancel>,
    ) -> Result<BridgeHttpResponse, BridgeTransportError> {
        Err(self.0)
    }
}

#[test]
fn host_026_fr_005_a_lost_connection_is_offline_and_a_401_needs_sign_in() {
    let path = linked("offline");
    let offline = rig(&path, Arc::new(Failing(BridgeTransportError::Connection)));
    offline.host.signal(BridgeWake::Foreground);
    let report = offline.rounds.recv_timeout(WAIT).unwrap();
    assert_eq!(report.state, BridgeSyncState::Offline, "{report:?}");
    offline.host.stop();

    struct Unauthorized;
    impl BridgeTransport for Unauthorized {
        fn send(
            &self,
            _request: BridgeHttpRequest,
            _cancel: Arc<BridgeCancel>,
        ) -> Result<BridgeHttpResponse, BridgeTransportError> {
            Ok(BridgeHttpResponse {
                status: 401,
                retry_after_ms: None,
                body: b"{}".to_vec(),
            })
        }
    }
    let path = linked("unauthorized");
    let signed_out = rig(&path, Arc::new(Unauthorized));
    signed_out.host.signal(BridgeWake::Foreground);
    let report = signed_out.rounds.recv_timeout(WAIT).unwrap();
    assert_eq!(report.state, BridgeSyncState::AuthRequired, "{report:?}");
    signed_out.host.stop();
}
