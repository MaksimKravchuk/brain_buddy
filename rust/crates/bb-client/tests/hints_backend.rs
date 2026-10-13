//! The hint stream against the real backend (026 PR-40 consuming PR-58).
//!
//! These tests start the actual application (`backend/app.main`, uvicorn on a
//! random loopback port, a temporary data directory, the production hints
//! router and `HintHub` over the shared SQLite commit counter) and drive the
//! crate's `HintWatcher`, `SseParser`, `Waker` and `SyncLoop` against its real
//! bytes. Writers are separate OS processes (`tests.sync_hints_processes write`),
//! exactly as in PR-58's own cross-process tests. The HTTP adapter below is the
//! host side the crate never sees: it owns the credential (a session cookie),
//! speaks HTTP/1.1 over a plain socket and decodes `Transfer-Encoding: chunked`.
//!
//! The backend interpreter is `BB_BACKEND_PYTHON`, else `/tmp/bb-pr31-venv/bin/python`.
//! When neither exists the tests print `SKIPPED` and pass, unless
//! `BB_REQUIRE_BACKEND=1` (set it in CI) turns that absence into a failure.

use bb_client::{
    Authentication, Cancellation, Clock, HintReader, HintStream, HintWatcher, HttpRequest,
    HttpResponse, InvalidationHub, MonotonicClock, OpenOptions, Schedule, SessionBinding, SplitMix,
    Step, Store, StreamFailure, SyncLoop, SyncSession, Syncer, Transport, TransportFailure, Wake,
    Waker,
};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::wire::{Id, Instant};
use serde_json::{Value, json};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant as Wall};

const DEFAULT_PYTHON: &str = "/tmp/bb-pr31-venv/bin/python";

// --------------------------------------------------------------- the backend process

struct Backend {
    child: Child,
    addr: SocketAddr,
    owner: String,
    cookie: String,
    data_dir: PathBuf,
    db_path: PathBuf,
    python: PathBuf,
    backend_dir: PathBuf,
}

impl Drop for Backend {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn python() -> Option<PathBuf> {
    let configured = std::env::var_os("BB_BACKEND_PYTHON").map(PathBuf::from);
    let python = configured.unwrap_or_else(|| PathBuf::from(DEFAULT_PYTHON));
    python.exists().then_some(python)
}

/// Starts the backend, or says why it cannot (and fails only when CI requires it).
fn start(name: &str) -> Option<Backend> {
    let Some(python) = python() else {
        let required = std::env::var("BB_REQUIRE_BACKEND").is_ok_and(|value| value == "1");
        assert!(
            !required,
            "BB_REQUIRE_BACKEND=1 but no backend interpreter: set BB_BACKEND_PYTHON"
        );
        eprintln!(
            "SKIPPED {name}: no backend interpreter at {DEFAULT_PYTHON} and BB_BACKEND_PYTHON is \
             unset; the real PR-58 stream was not exercised"
        );
        return None;
    };
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    let backend_dir = manifest.join("../../../backend").canonicalize().unwrap();
    let script = manifest.join("tests/support/sse_backend.py");
    let scratch = std::env::temp_dir().join(format!("bb-hints-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&scratch);
    std::fs::create_dir_all(&scratch).unwrap();
    let port = TcpListener::bind("127.0.0.1:0")
        .unwrap()
        .local_addr()
        .unwrap()
        .port();
    let mut child = Command::new(&python)
        .arg(&script)
        .arg(scratch.join("data"))
        .arg(port.to_string())
        .current_dir(&backend_dir)
        .env("PYTHONPATH", &backend_dir)
        .stdout(Stdio::piped())
        .stderr(std::fs::File::create(scratch.join("backend.log")).unwrap())
        .spawn()
        .expect("start the backend");
    let stdout = child.stdout.take().unwrap();
    let (sender, receiver) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if line.starts_with('{') {
                let _ = sender.send(line);
            }
        }
    });
    let info: Value = serde_json::from_str(
        &receiver
            .recv_timeout(Duration::from_secs(120))
            .unwrap_or_else(|_| {
                panic!(
                    "the backend never announced itself; see {}",
                    scratch.join("backend.log").display()
                )
            }),
    )
    .unwrap();
    let addr: SocketAddr = format!("127.0.0.1:{port}").parse().unwrap();
    let backend = Backend {
        child,
        addr,
        owner: info["owner"].as_str().unwrap().to_string(),
        cookie: info["cookie"].as_str().unwrap().to_string(),
        data_dir: PathBuf::from(info["data_dir"].as_str().unwrap()),
        db_path: PathBuf::from(info["db_path"].as_str().unwrap()),
        python,
        backend_dir,
    };
    let deadline = Wall::now() + Duration::from_secs(120);
    while Wall::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_secs(1)) {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let _ =
                stream.write_all(b"GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n");
            let mut head = String::new();
            let _ = stream.read_to_string(&mut head);
            if head.starts_with("HTTP/1.1 200") {
                return Some(backend);
            }
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    panic!("the backend never became healthy");
}

impl Backend {
    /// One feed transaction from a separate writer process; `rollback` aborts it.
    fn write(&self, key: &str, rollback: bool) -> String {
        let mut command = Command::new(&self.python);
        command
            .args(["-m", "tests.sync_hints_processes", "write"])
            .arg(&self.data_dir)
            .arg(&self.owner)
            .arg(key);
        if rollback {
            command.arg("rollback");
        }
        let done = command
            .current_dir(&self.backend_dir)
            .env("PYTHONPATH", &self.backend_dir)
            .output()
            .expect("run the writer process");
        assert!(
            done.status.success(),
            "writer failed: {}",
            String::from_utf8_lossy(&done.stderr)
        );
        String::from_utf8_lossy(&done.stdout).trim().to_string()
    }

    fn stream(&self) -> RealStream {
        RealStream {
            addr: self.addr,
            cookie: self.cookie.clone(),
            headers: Arc::default(),
        }
    }
}

// ----------------------------------------------------------- the host HTTP adapter

/// The OS adapter's side: it holds the credential, the crate never does.
struct RealStream {
    addr: SocketAddr,
    cookie: String,
    headers: Arc<Mutex<Vec<String>>>,
}

struct Chunked {
    socket: TcpStream,
    raw: Vec<u8>,
    decoded: Vec<u8>,
    idle: Duration,
    done: bool,
}

impl HintStream for RealStream {
    fn open(
        &self,
        path: &str,
        idle: Duration,
        cancel: &Cancellation<'_>,
    ) -> Result<Box<dyn HintReader>, StreamFailure> {
        let mut socket = TcpStream::connect_timeout(&self.addr, Duration::from_secs(5))
            .map_err(|_| StreamFailure::Connection)?;
        socket
            .set_read_timeout(Some(Duration::from_millis(100)))
            .unwrap();
        // No `Last-Event-ID`: the crate never asks for a position.
        let request = format!(
            "GET {path} HTTP/1.1\r\nHost: {}\r\nCookie: {}\r\nAccept: text/event-stream\r\n\
             Cache-Control: no-cache\r\nConnection: keep-alive\r\n\r\n",
            self.addr, self.cookie
        );
        socket
            .write_all(request.as_bytes())
            .map_err(|_| StreamFailure::Connection)?;
        let mut raw = Vec::new();
        let started = Wall::now();
        let end = loop {
            if cancel.is_cancelled() {
                return Err(StreamFailure::Cancelled);
            }
            if let Some(at) = raw.windows(4).position(|window| window == b"\r\n\r\n") {
                break at;
            }
            if started.elapsed() > Duration::from_secs(10) {
                return Err(StreamFailure::Timeout);
            }
            let mut buffer = [0u8; 2048];
            match socket.read(&mut buffer) {
                Ok(0) => return Err(StreamFailure::Connection),
                Ok(count) => raw.extend_from_slice(&buffer[..count]),
                Err(error) if is_timeout(&error) => {}
                Err(_) => return Err(StreamFailure::Connection),
            }
        };
        let head = String::from_utf8_lossy(&raw[..end]).to_string();
        let mut lines = head.lines();
        let status: u16 = lines
            .next()
            .and_then(|line| line.split(' ').nth(1))
            .and_then(|code| code.parse().ok())
            .ok_or(StreamFailure::Connection)?;
        if status != 200 {
            return Err(StreamFailure::Status(status));
        }
        *self.headers.lock().unwrap() = lines.map(|line| line.to_ascii_lowercase()).collect();
        Ok(Box::new(Chunked {
            socket,
            raw: raw[end + 4..].to_vec(),
            decoded: Vec::new(),
            idle,
            done: false,
        }))
    }
}

fn is_timeout(error: &std::io::Error) -> bool {
    matches!(
        error.kind(),
        std::io::ErrorKind::WouldBlock | std::io::ErrorKind::TimedOut
    )
}

impl Chunked {
    /// Moves every complete chunk of `raw` into `decoded`.
    fn decode(&mut self) {
        loop {
            let Some(line_end) = self.raw.windows(2).position(|window| window == b"\r\n") else {
                return;
            };
            let size_text = String::from_utf8_lossy(&self.raw[..line_end]).to_string();
            let Ok(size) = usize::from_str_radix(size_text.split(';').next().unwrap().trim(), 16)
            else {
                self.done = true;
                return;
            };
            if size == 0 {
                self.done = true;
                return;
            }
            let total = line_end + 2 + size + 2;
            if self.raw.len() < total {
                return;
            }
            self.decoded
                .extend_from_slice(&self.raw[line_end + 2..line_end + 2 + size]);
            self.raw.drain(..total);
        }
    }
}

impl HintReader for Chunked {
    fn read(
        &mut self,
        buffer: &mut [u8],
        cancel: &Cancellation<'_>,
    ) -> Result<usize, StreamFailure> {
        let started = Wall::now();
        loop {
            self.decode();
            if !self.decoded.is_empty() {
                let count = buffer.len().min(self.decoded.len());
                buffer[..count].copy_from_slice(&self.decoded[..count]);
                self.decoded.drain(..count);
                return Ok(count);
            }
            if self.done {
                return Ok(0);
            }
            if cancel.is_cancelled() {
                return Err(StreamFailure::Cancelled);
            }
            if started.elapsed() > self.idle {
                return Err(StreamFailure::Timeout);
            }
            let mut chunk = [0u8; 4096];
            match self.socket.read(&mut chunk) {
                Ok(0) => return Ok(0),
                Ok(count) => self.raw.extend_from_slice(&chunk[..count]),
                Err(error) if is_timeout(&error) => {}
                Err(_) => return Err(StreamFailure::Connection),
            }
        }
    }
}

// ------------------------------------------------------------------------- helpers

fn wait_for(waker: &Waker, wake: Wake, within: Duration) -> bool {
    let deadline = Wall::now() + within;
    while Wall::now() < deadline {
        let woken = waker.wait(Duration::from_millis(50));
        if woken.contains(wake) {
            return true;
        }
    }
    false
}

/// True when nothing but heartbeats woke the waker for `window`.
fn quiet(waker: &Waker, window: Duration) -> bool {
    let deadline = Wall::now() + window;
    while Wall::now() < deadline {
        if !waker.wait(Duration::from_millis(50)).is_empty() {
            return false;
        }
    }
    true
}

fn watcher(backend: &Backend, waker: &Waker) -> (HintWatcher, Arc<Mutex<Vec<String>>>) {
    let stream = backend.stream();
    let headers = Arc::clone(&stream.headers);
    let watcher = HintWatcher::new(
        Arc::new(stream),
        waker.clone(),
        Id::parse(&backend.owner).unwrap(),
        Arc::new(MonotonicClock::new()),
        Box::new(SplitMix::from_entropy()),
        &Schedule::default(),
    );
    (watcher, headers)
}

/// Steps the loop for `window`, recording why each round ran.
fn drive(
    worker: &mut SyncLoop,
    store: &mut Store,
    waker: &Waker,
    reasons: &mut Vec<Wake>,
    window: Duration,
) {
    let deadline = Wall::now() + window;
    while Wall::now() < deadline {
        match worker.step(store) {
            Step::Ran { reason, .. } => reasons.push(reason),
            Step::Wait(left) => {
                let woken = waker.wait(left.min(Duration::from_millis(100)));
                for wake in woken.iter() {
                    waker.post(wake);
                }
            }
            Step::Idle => panic!("an active online loop is never idle"),
        }
    }
}

// ------------------------------------------------------------------------- tests

/// The real stream: open, initial event, committed-only wake-ups from another
/// process, coalescing, reopen and generation closure.
#[test]
fn hints_026_fr_004_the_real_stream_wakes_on_committed_writes_only() {
    let Some(backend) = start("stream") else {
        return;
    };
    let waker = Waker::new();
    let (mut watcher, headers) = watcher(&backend, &waker);
    let stop = watcher.stop_flag();
    let handle = std::thread::spawn(move || {
        watcher.run();
        watcher
    });

    // Open: an immediate catch-up, and the initial event closes the race.
    assert!(
        wait_for(&waker, Wake::StreamOpened, Duration::from_secs(20)),
        "no open"
    );
    let mut hinted = false;
    for _ in 0..100 {
        if waker.drain().contains(Wake::Hint) {
            hinted = true;
            break;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    assert!(hinted, "the initial event wakes a pull");
    {
        let seen = headers.lock().unwrap();
        let has = |name: &str, value: &str| {
            seen.iter()
                .any(|line| line.starts_with(name) && line.contains(value))
        };
        assert!(has("content-type:", "text/event-stream"), "{seen:?}");
        assert!(has("cache-control:", "no-store"), "{seen:?}");
        assert!(has("x-accel-buffering:", "no"), "{seen:?}");
    }
    assert!(
        quiet(&waker, Duration::from_millis(700)),
        "an idle stream wakes nothing"
    );

    // A rolled-back writer process publishes nothing.
    assert_eq!(backend.write("rolled", true), "rolled back");
    assert!(
        quiet(&waker, Duration::from_millis(1_000)),
        "uncommitted work woke a pull"
    );

    // A committed writer process wakes the open stream, with no content.
    let committed = Wall::now();
    assert_eq!(backend.write("first", false), "1");
    assert!(
        wait_for(&waker, Wake::Hint, Duration::from_secs(5)),
        "commit not announced"
    );
    eprintln!(
        "commit to wake-up: {:?} (informational; the pilot measures SC-004)",
        committed.elapsed()
    );

    // Writers spawn slowly, so these commits are spread over seconds. Each is heard
    // (at least once), the waker holds one Hint however many arrive, and the
    // stream goes quiet once the last committed sequence has been announced.
    for key in ["b1", "b2", "b3"] {
        backend.write(key, false);
    }
    assert!(wait_for(&waker, Wake::Hint, Duration::from_secs(5)));
    let settled = (0..6).any(|_| quiet(&waker, Duration::from_millis(1_200)));
    assert!(
        settled,
        "events kept coming after the last commit was announced"
    );

    // Generation closure: the server ends the stream; the watcher reopens at once
    // and asks for another catch-up.
    {
        let connection = rusqlite::Connection::open(&backend.db_path).unwrap();
        connection
            .execute(
                "UPDATE sync_scopes SET server_generation = 'server-reset'",
                [],
            )
            .unwrap();
    }
    assert!(
        wait_for(&waker, Wake::StreamOpened, Duration::from_secs(20)),
        "no reopen after the generation changed"
    );
    assert!(
        wait_for(&waker, Wake::Hint, Duration::from_secs(5)),
        "reopen opens with an event"
    );

    // A write after the reopen is still heard.
    backend.write("after", false);
    assert!(wait_for(&waker, Wake::Hint, Duration::from_secs(5)));

    stop.store(true, std::sync::atomic::Ordering::SeqCst);
    waker.close();
    let watcher = handle.join().unwrap();
    assert!(watcher.opened() >= 2, "opened {} times", watcher.opened());
    // Every event of the real stream parsed (a stray key would have been ignored).
    assert!(watcher.hints() >= 4, "{} hints", watcher.hints());
}

/// A scope the owner is not entitled to reads as the same 404 as an unknown one,
/// the watcher backs off instead of hammering, and wakes nothing.
#[test]
fn hints_026_fr_011_a_refused_stream_wakes_nothing_and_backs_off() {
    let Some(backend) = start("refused") else {
        return;
    };
    let waker = Waker::new();
    let stream = backend.stream();
    let mut watcher = HintWatcher::new(
        Arc::new(stream),
        waker.clone(),
        Id::parse("someone-elses-scope").unwrap(),
        Arc::new(MonotonicClock::new()),
        Box::new(SplitMix::from_entropy()),
        &Schedule::default(),
    );
    let end = watcher.connect_once();
    assert_eq!(
        end,
        bb_client::StreamEnd::NotOpened(StreamFailure::Status(404))
    );
    assert!(watcher.reconnect_delay(end) >= Duration::from_secs(1));
    assert!(waker.drain().is_empty());
}

/// The real stream and the sync loop together: hints start pulls, duplicates
/// coalesce, a reopen catches up at once, and the fallback poll deadline never
/// moves.
#[test]
fn hints_026_sc_004_real_hints_wake_pulls_without_moving_the_poll_deadline() {
    let Some(backend) = start("loop") else { return };

    // A quiet sync endpoint: the loop's requests are not the subject here.
    struct Quiet(Arc<Mutex<u32>>);
    impl Transport for Quiet {
        fn send(
            &self,
            request: &HttpRequest,
            _cancel: &Cancellation<'_>,
        ) -> Result<HttpResponse, TransportFailure> {
            let common = json!({
                "correlation_id": "c", "scope_id": "scope-1",
                "server_generation": "generation-1", "server_now": "2026-10-10T09:00:00Z",
            });
            let mut body = if request.path.contains("/capabilities") {
                json!({
                    "protocol_versions": [1], "command_versions": [], "rule_version": 1,
                    "projection_schema_version": 1, "storage_epoch": 1,
                    "feed_generation": "feed-1", "scope_enabled": true,
                    "limits": {}, "recovery": {},
                })
            } else {
                *self.0.lock().unwrap() += 1;
                json!({
                    "from_cursor": "cursor-0", "transactions": [], "has_more": false,
                    "next_cursor": "cursor-0", "high_watermark": "0",
                })
            };
            for (key, value) in common.as_object().unwrap() {
                body[key] = value.clone();
            }
            Ok(HttpResponse {
                status: 200,
                retry_after: None,
                body: body.to_string().into_bytes(),
            })
        }
    }

    let path = std::env::temp_dir()
        .join(format!("bb-hints-loop-store-{}", std::process::id()))
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
            tx.execute(
                "UPDATE sync_meta SET server_generation = 'generation-1', cursor = 'cursor-0',
                    base_watermark = '0', account_link_state = 'linked'",
                [],
            )?;
            Ok(())
        })
        .unwrap();
    let session = SyncSession::start(
        &mut store,
        &SessionBinding {
            account_id: Id::parse("account-1").unwrap(),
            scope_id: Id::parse("scope-1").unwrap(),
            device_id: Id::parse("device-1").unwrap(),
            authentication: Authentication::Fresh,
        },
    )
    .unwrap();
    let schedule = Schedule {
        poll_interval: Duration::from_secs(120),
        ..Schedule::default()
    };
    let pulls = Arc::new(Mutex::new(0));
    let clock = Arc::new(MonotonicClock::new());
    let syncer = Syncer::new(
        Box::new(Quiet(Arc::clone(&pulls))),
        session,
        Box::new(|| bb_client::ExecuteContext {
            now: Instant::parse("2026-10-10T09:00:00Z").unwrap(),
            time_zone: ZoneName::new("UTC").unwrap(),
            actor_id: ActorId::parse("actor-local").unwrap(),
            policy: Policy {
                weekly_review: false,
                navigator_provider: None,
                navigator_available: false,
                consent_text_version: 1,
            },
        }),
        clock.clone(),
        Box::new(SplitMix::seeded(1)),
        // A long poll interval keeps the first poll out of this test's wall-clock
        // window (spawning writer processes is slow); the 30 s bound itself is
        // proven on the simulated clock in `transport.rs`.
        schedule.clone(),
    );
    let waker = Waker::new();
    let mut worker = SyncLoop::new(
        syncer,
        waker.clone(),
        InvalidationHub::new(4),
        clock.clone(),
        Box::new(SplitMix::seeded(2)),
    );
    waker.post(Wake::Foreground);
    let Step::Ran { reason, .. } = worker.step(&mut store) else {
        panic!("the foreground round runs");
    };
    assert_eq!(reason, Wake::Foreground);
    let poll = worker
        .scheduler()
        .next_poll()
        .expect("the poll is scheduled");
    let started = clock.now();
    assert!(poll <= started + schedule.poll_interval);
    assert!(poll + schedule.poll_jitter >= started + schedule.poll_interval);

    // The same waker carries the real stream's wakes into the loop.
    let (mut hint_watcher, _) = watcher(&backend, &waker);
    let stop = hint_watcher.stop_flag();
    let handle = std::thread::spawn(move || {
        hint_watcher.run();
        hint_watcher
    });

    let mut reasons: Vec<Wake> = Vec::new();

    // Open: an immediate catch-up pull, whatever the poll clock says.
    drive(
        &mut worker,
        &mut store,
        &waker,
        &mut reasons,
        Duration::from_secs(4),
    );
    assert!(reasons.contains(&Wake::StreamOpened), "{reasons:?}");
    let after_open = reasons.len();

    // Real commits from another process: hints start pulls. Duplicates coalesce.
    for key in ["w1", "w2", "w3"] {
        backend.write(key, false);
    }
    drive(
        &mut worker,
        &mut store,
        &waker,
        &mut reasons,
        Duration::from_secs(4),
    );
    let hinted = reasons[after_open..]
        .iter()
        .filter(|reason| **reason == Wake::Hint)
        .count();
    assert!((1..=3).contains(&hinted), "{reasons:?}");

    // Generation closure: the old stream ends, the reopen catches up at once.
    let opened_before = reasons.iter().filter(|r| **r == Wake::StreamOpened).count();
    {
        let connection = rusqlite::Connection::open(&backend.db_path).unwrap();
        connection
            .execute(
                "UPDATE sync_scopes SET server_generation = 'server-reset-2'",
                [],
            )
            .unwrap();
    }
    drive(
        &mut worker,
        &mut store,
        &waker,
        &mut reasons,
        Duration::from_secs(6),
    );
    let opened_after = reasons.iter().filter(|r| **r == Wake::StreamOpened).count();
    assert!(
        opened_after > opened_before,
        "no catch-up after the reopen: {reasons:?}"
    );

    // All of it, and the poll deadline stayed exactly where the foreground put it.
    assert!(
        clock.now() < poll,
        "the test must finish before the first poll is due"
    );
    assert!(!reasons.contains(&Wake::Poll), "{reasons:?}");
    assert_eq!(
        worker.scheduler().next_poll(),
        Some(poll),
        "hints moved the poll"
    );
    assert!(*pulls.lock().unwrap() >= 3);

    stop.store(true, std::sync::atomic::Ordering::SeqCst);
    waker.close();
    let _ = handle.join();
}
