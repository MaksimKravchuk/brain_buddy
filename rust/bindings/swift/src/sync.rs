//! The Apple sync host: `bb_client`'s [`SyncLoop`] and [`HintWatcher`] behind UniFFI callback
//! interfaces (spec 026, PR-40 transport; runtime-ffi `sync_now`, `cancel`, `close`).
//!
//! Thin wrappers only. The OS adapter (Swift) implements three ports and one observer:
//!
//! * [`BridgeTransport`]: one authenticated HTTP call. **The credential never crosses**: the
//!   adapter adds the session cookie it already holds and answers with a status, an optional
//!   `Retry-After` and the body.
//! * [`BridgeHintStream`] / [`BridgeHintReader`]: the authenticated `text/event-stream` GET and
//!   the reads of its body, with the idle timeout the crate names.
//! * [`BridgeSyncObserver`]: told after every round how it ended and what to re-query.
//!
//! Cancellation is a [`BridgeCancel`] token handed to every call. The crate's own flags (a reset,
//! the end of the session, `stop`) are watched by a short-lived thread that raises the token, so
//! the adapter only polls `is_cancelled()` while it waits on the network.
//!
//! The host owns two kinds of thread, never the caller's: one worker running the sync loop over
//! its **own** store connection (the workspace's connection and lock are never held across a
//! network call) and, while the app is in the foreground, one reading the hint stream.

use super::{BridgeError, Failure};
use crate::workspace::BridgeExecuteContext;
use bb_client::{
    Authentication, Cancellation, ChangeKind, Clock, ExecuteContext, Halt, HintReader, HintStream,
    HintWatcher, HttpRequest, HttpResponse, Invalidation, InvalidationHub, Method, MonotonicClock,
    OpenOptions, Schedule, SessionBinding, SplitMix, Step, Store, StreamFailure, SyncLoop,
    SyncSession, Syncer, Transport, TransportFailure, Wake, Waker, projection_generation,
};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::wire::{Id, Instant};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

// ------------------------------------------------------------------------------ cancellation

/// What a running call polls to know it should stop. Raised by the crate (a reset, a sign-out,
/// `stop`); the adapter reads it while it waits on the network and aborts with `Cancelled`.
#[derive(Default, uniffi::Object)]
pub struct BridgeCancel {
    raised: AtomicBool,
}

#[uniffi::export]
impl BridgeCancel {
    /// A token nobody raises yet (adapters' tests use it to drive their cancellation paths).
    #[uniffi::constructor]
    pub fn new() -> Arc<Self> {
        Arc::new(Self::default())
    }

    pub fn raise(&self) {
        self.raised.store(true, Ordering::SeqCst);
    }

    pub fn is_cancelled(&self) -> bool {
        self.raised.load(Ordering::SeqCst)
    }
}

/// Runs `call` with a token that is raised as soon as `cancel` is. The watcher thread parks for
/// 20 ms at a time and is woken the moment the call returns, so a fast call pays no delay.
fn with_token<T>(cancel: &Cancellation<'_>, call: impl FnOnce(Arc<BridgeCancel>) -> T) -> T {
    let token = BridgeCancel::new();
    if cancel.is_cancelled() {
        token.raise();
    }
    let done = AtomicBool::new(false);
    std::thread::scope(|scope| {
        let watcher = scope.spawn(|| {
            while !done.load(Ordering::SeqCst) {
                if cancel.is_cancelled() {
                    token.raise();
                    return;
                }
                std::thread::park_timeout(Duration::from_millis(20));
            }
        });
        let result = call(Arc::clone(&token));
        done.store(true, Ordering::SeqCst);
        watcher.thread().unpark();
        result
    })
}

// ------------------------------------------------------------------------------- the transport

#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum BridgeHttpMethod {
    Get,
    Post,
}

/// One HTTP call to perform. `path` is origin-relative and already percent-encoded; the adapter
/// resolves it against the same-origin base URL it was given.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct BridgeHttpRequest {
    pub method: BridgeHttpMethod,
    pub path: String,
    /// The JSON body of a `POST`, byte for byte.
    pub body: Option<Vec<u8>>,
    /// How long the adapter may wait for the whole answer.
    pub timeout_ms: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct BridgeHttpResponse {
    pub status: u16,
    /// The parsed `Retry-After` header, when present.
    pub retry_after_ms: Option<u64>,
    pub body: Vec<u8>,
}

/// Why no HTTP answer arrived. A non-2xx status is an answer, not a failure.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Error)]
pub enum BridgeTransportError {
    Timeout,
    Connection,
    Cancelled,
    /// The adapter threw something it did not declare; treated as a lost connection.
    Unexpected,
}

impl std::fmt::Display for BridgeTransportError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "transport failure {self:?}")
    }
}

impl From<uniffi::UnexpectedUniFFICallbackError> for BridgeTransportError {
    fn from(_: uniffi::UnexpectedUniFFICallbackError) -> Self {
        Self::Unexpected
    }
}

/// The authenticated HTTP adapter the OS provides.
#[uniffi::export(with_foreign)]
pub trait BridgeTransport: Send + Sync {
    /// Performs `request` off the main thread, stopping early with `Cancelled` once `cancel`
    /// is raised.
    fn send(
        &self,
        request: BridgeHttpRequest,
        cancel: Arc<BridgeCancel>,
    ) -> Result<BridgeHttpResponse, BridgeTransportError>;
}

struct ForeignTransport(Arc<dyn BridgeTransport>);

impl Transport for ForeignTransport {
    fn send(
        &self,
        request: &HttpRequest,
        cancel: &Cancellation<'_>,
    ) -> Result<HttpResponse, TransportFailure> {
        let call = BridgeHttpRequest {
            method: match request.method {
                Method::Get => BridgeHttpMethod::Get,
                Method::Post => BridgeHttpMethod::Post,
            },
            path: request.path.clone(),
            body: request.body.clone(),
            timeout_ms: u64::try_from(request.timeout.as_millis()).unwrap_or(u64::MAX),
        };
        with_token(cancel, |token| self.0.send(call, token))
            .map(|answer| HttpResponse {
                status: answer.status,
                retry_after: answer.retry_after_ms.map(Duration::from_millis),
                body: answer.body,
            })
            .map_err(|failure| match failure {
                BridgeTransportError::Timeout => TransportFailure::Timeout,
                BridgeTransportError::Cancelled => TransportFailure::Cancelled,
                BridgeTransportError::Connection | BridgeTransportError::Unexpected => {
                    TransportFailure::Connection
                }
            })
    }
}

// ---------------------------------------------------------------------------- the hint stream

/// Why a hint stream could not open or ended.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Error)]
pub enum BridgeStreamError {
    /// The route answered with this status instead of a stream.
    Status {
        code: u16,
    },
    /// Nothing arrived within the idle timeout.
    Timeout,
    Connection,
    Cancelled,
    Unexpected,
}

impl std::fmt::Display for BridgeStreamError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "stream failure {self:?}")
    }
}

impl From<uniffi::UnexpectedUniFFICallbackError> for BridgeStreamError {
    fn from(_: uniffi::UnexpectedUniFFICallbackError) -> Self {
        Self::Unexpected
    }
}

impl From<BridgeStreamError> for StreamFailure {
    fn from(failure: BridgeStreamError) -> Self {
        match failure {
            BridgeStreamError::Status { code } => Self::Status(code),
            BridgeStreamError::Timeout => Self::Timeout,
            BridgeStreamError::Cancelled => Self::Cancelled,
            BridgeStreamError::Connection | BridgeStreamError::Unexpected => Self::Connection,
        }
    }
}

/// An open `text/event-stream` response body.
#[uniffi::export(with_foreign)]
pub trait BridgeHintReader: Send + Sync {
    /// Reads at most `max_len` bytes. An empty answer is the server closing the stream.
    fn read(&self, max_len: u32, cancel: Arc<BridgeCancel>) -> Result<Vec<u8>, BridgeStreamError>;
}

/// The authenticated streaming GET: it adds the credential and `Accept: text/event-stream`,
/// sends no `Last-Event-ID`, and returns the body only for a `200`. (Not named `open`: the
/// generated C header would declare a member with that Swift keyword.)
#[uniffi::export(with_foreign)]
pub trait BridgeHintStream: Send + Sync {
    /// # Errors
    ///
    /// `Status` for any non-200 answer.
    fn open_stream(
        &self,
        path: String,
        idle_ms: u64,
        cancel: Arc<BridgeCancel>,
    ) -> Result<Arc<dyn BridgeHintReader>, BridgeStreamError>;
}

struct ForeignReader(Arc<dyn BridgeHintReader>);

impl HintReader for ForeignReader {
    fn read(
        &mut self,
        buffer: &mut [u8],
        cancel: &Cancellation<'_>,
    ) -> Result<usize, StreamFailure> {
        let max_len = u32::try_from(buffer.len()).unwrap_or(u32::MAX);
        let bytes = with_token(cancel, |token| self.0.read(max_len, token))?;
        // More than was asked for cannot be placed: the stream is broken, not truncated.
        let Some(target) = buffer.get_mut(..bytes.len()) else {
            return Err(StreamFailure::Connection);
        };
        target.copy_from_slice(&bytes);
        Ok(bytes.len())
    }
}

struct ForeignStream(Arc<dyn BridgeHintStream>);

impl HintStream for ForeignStream {
    fn open(
        &self,
        path: &str,
        idle: Duration,
        cancel: &Cancellation<'_>,
    ) -> Result<Box<dyn HintReader>, StreamFailure> {
        let idle_ms = u64::try_from(idle.as_millis()).unwrap_or(u64::MAX);
        let reader = with_token(cancel, |token| {
            self.0.open_stream(path.to_owned(), idle_ms, token)
        })?;
        Ok(Box::new(ForeignReader(reader)))
    }
}

// -------------------------------------------------------------------------------- the observer

/// How the last round ended, in words the platform maps to its own status.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum BridgeSyncState {
    Synced,
    /// No HTTP answer: timeout or connection loss. Changes are kept and sent later.
    Offline,
    /// `429`, `5xx` or work the server has not finished; the loop retries with backoff.
    Retrying,
    /// `401` or a revoked session: paused until the platform authenticates again.
    AuthRequired,
    /// The server or protocol is newer than this build (`UPGRADE_REQUIRED`).
    UpdateRequired,
    /// Anything else; `failure_code` is a stable code, never payload text.
    Failed,
}

/// What to re-query: the bounded, content-free `{generation, kinds, status}` of the hub.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct BridgeSyncInvalidation {
    pub projection_generation: String,
    pub records_changed: bool,
    pub issues_changed: bool,
    pub status_changed: bool,
}

/// One finished round. Content-free.
#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct BridgeSyncReport {
    pub state: BridgeSyncState,
    pub failure_code: Option<String>,
    pub sent: u32,
    pub settled: u32,
    pub pulled_transactions: u64,
    pub invalidation: Option<BridgeSyncInvalidation>,
}

/// Told after every round, on the sync worker thread: hand off and return.
#[uniffi::export(with_foreign)]
pub trait BridgeSyncObserver: Send + Sync {
    fn round_finished(&self, report: BridgeSyncReport);
}

fn halt_code(halt: &Halt) -> String {
    match halt {
        Halt::Cancelled => "CANCELLED".to_owned(),
        Halt::Offline => "OFFLINE".to_owned(),
        Halt::Retry { .. } => "RETRY".to_owned(),
        Halt::AuthRequired => "AUTH_REQUIRED".to_owned(),
        Halt::UpdateRequired => "UPGRADE_REQUIRED".to_owned(),
        Halt::Stale => "STALE_RESPONSE".to_owned(),
        Halt::ResetRequired => "RESET_REQUIRED".to_owned(),
        Halt::EpochClosed => "EPOCH_CLOSED".to_owned(),
        Halt::NotReady => "NOT_READY".to_owned(),
        Halt::Store(error) => error.code().to_owned(),
        Halt::Failed(code) => code.clone(),
    }
}

fn state_of(halt: Option<&Halt>) -> BridgeSyncState {
    match halt {
        None => BridgeSyncState::Synced,
        Some(Halt::Offline) => BridgeSyncState::Offline,
        Some(
            Halt::Retry { .. }
            | Halt::Cancelled
            | Halt::Stale
            | Halt::NotReady
            | Halt::ResetRequired,
        ) => BridgeSyncState::Retrying,
        Some(Halt::AuthRequired) => BridgeSyncState::AuthRequired,
        Some(Halt::UpdateRequired) => BridgeSyncState::UpdateRequired,
        Some(Halt::EpochClosed | Halt::Store(_) | Halt::Failed(_)) => BridgeSyncState::Failed,
    }
}

// --------------------------------------------------------------------------------- the host

/// Why a pull is wanted, as the platform knows it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum BridgeWake {
    /// The app became active (launch, foreground, a background refresh). Starts the schedule
    /// and the hint stream.
    Foreground,
    /// Connectivity came back.
    NetworkReturn,
    /// The person asked to sync now.
    Manual,
    /// A local change is waiting: round again at once, without forgiving a backoff.
    LocalChange,
}

#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum BridgeRebuildOutcome {
    Rebuilt,
    /// Stopped; waiting changes and saved issues are untouched. `code` is safe to quote.
    Failed {
        code: String,
    },
}

/// Everything the host needs to bind the store to the signed-in account and run.
#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeSyncConfig {
    pub workspace_id: String,
    pub database_path: String,
    pub busy_timeout_ms: u32,
    pub account_id: String,
    pub scope_id: String,
    pub device_id: String,
    /// A sign-in or re-authentication (every earlier request is fenced out); false for a
    /// relaunch with the same still-valid credentials.
    pub fresh_authentication: bool,
    /// The rules' time zone, actor and policy for applying the feed. `now` is ignored: the
    /// host reads the clock for each application.
    pub context: BridgeExecuteContext,
    /// Fallback poll interval; the default is the 30 seconds sync-v1 section 7 allows.
    pub poll_interval_ms: Option<u64>,
}

enum Control {
    Background,
    Offline,
    Rebuild(Sender<BridgeRebuildOutcome>),
}

struct Hints {
    stop: Arc<AtomicBool>,
    thread: JoinHandle<()>,
}

/// The running sync host. Cheap to share; `stop` is final and idempotent.
#[derive(uniffi::Object)]
pub struct BridgeSyncHost {
    waker: Waker,
    closing: Arc<AtomicBool>,
    hub: InvalidationHub,
    controls: Mutex<Sender<Control>>,
    worker: Mutex<Option<JoinHandle<()>>>,
    hints: Mutex<Option<Hints>>,
    /// A fresh watcher per foreground: a stopped one never restarts.
    new_watcher: Box<dyn Fn() -> HintWatcher + Send + Sync>,
}

fn rfc3339_now() -> Result<Instant, Failure> {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |elapsed| i64::try_from(elapsed.as_secs()).unwrap_or(0));
    let (days, rest) = (seconds.div_euclid(86_400), seconds.rem_euclid(86_400));
    // Civil date from days since the epoch (Hinnant).
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let day_of_era = z.rem_euclid(146_097);
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let shifted = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * shifted + 2) / 5 + 1;
    let month = if shifted < 10 {
        shifted + 3
    } else {
        shifted - 9
    };
    let year = year_of_era + era * 400 + i64::from(month <= 2);
    let text = format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rest / 3_600,
        rest % 3_600 / 60,
        rest % 60
    );
    Instant::parse(text).map_err(|_| Failure::new("INTERNAL_ERROR", None))
}

fn id(value: &str, field: &'static str) -> Result<Id, Failure> {
    Id::parse(value).map_err(|_| Failure::new("INVALID_REQUEST", Some(field)))
}

#[uniffi::export]
impl BridgeSyncHost {
    /// Opens the workspace's store on its own connection, binds it to the signed-in account,
    /// scope and device, and starts the sync worker. The loop is idle until the first
    /// `Foreground` signal.
    ///
    /// Fails with the session's own code: `LINK_REQUIRED` until the account-link choice is
    /// recorded, `ACCOUNT_MISMATCH` / `DEVICE_MISMATCH` for another owner, `UPGRADE_REQUIRED`
    /// for a store a newer build wrote. Nothing changes then.
    #[uniffi::constructor]
    pub fn start(
        config: BridgeSyncConfig,
        transport: Arc<dyn BridgeTransport>,
        hints: Arc<dyn BridgeHintStream>,
        observer: Arc<dyn BridgeSyncObserver>,
    ) -> Result<Arc<Self>, BridgeError> {
        Ok(Self::open(config, transport, hints, observer)?)
    }

    /// Wakes the loop. A `Foreground` also opens the hint stream.
    pub fn signal(&self, wake: BridgeWake) {
        if self.is_stopped() {
            return;
        }
        let wake = match wake {
            BridgeWake::Foreground => {
                self.open_hints();
                Wake::Foreground
            }
            BridgeWake::NetworkReturn => Wake::NetworkReturn,
            BridgeWake::Manual => Wake::Manual,
            // The scheduler pulls at once for `Continue` and keeps the send backoff.
            BridgeWake::LocalChange => Wake::Continue,
        };
        self.waker.post(wake);
    }

    /// The app left the foreground: no polls and no pulls until the next `Foreground`, and the
    /// hint stream is closed.
    pub fn background(&self) {
        self.close_hints();
        self.control(Control::Background);
    }

    /// Connectivity changed. Offline stops attempts; coming back wakes the loop.
    pub fn set_online(&self, online: bool) {
        if online {
            self.signal(BridgeWake::NetworkReturn);
        } else {
            self.control(Control::Offline);
        }
    }

    /// Rebuilds the synced copy from a snapshot, keeping every waiting change and saved issue.
    /// Blocks until it ends, so call it off the main thread.
    pub fn rebuild(&self) -> BridgeRebuildOutcome {
        let (reply, answer) = mpsc::channel();
        let failed = |code: &str| BridgeRebuildOutcome::Failed {
            code: code.to_owned(),
        };
        if self.is_stopped() || !self.control(Control::Rebuild(reply)) {
            return failed("WORKSPACE_CLOSED");
        }
        answer.recv().unwrap_or_else(|_| failed("CANCELLED"))
    }

    /// Ends the host: cancels calls in flight, closes the stream, releases the store. Durable
    /// commands survive; nothing is delivered afterwards.
    pub fn stop(&self) {
        self.closing.store(true, Ordering::SeqCst);
        self.hub.close();
        self.waker.close();
        let live = self.hints.lock().ok().and_then(|mut held| held.take());
        if let Some(live) = live {
            live.stop.store(true, Ordering::SeqCst);
            let _ = live.thread.join();
        }
        let worker = self.worker.lock().ok().and_then(|mut held| held.take());
        if let Some(worker) = worker {
            let _ = worker.join();
        }
    }
}

impl BridgeSyncHost {
    fn is_stopped(&self) -> bool {
        self.waker.is_closed()
    }

    /// Queues a control for the worker and pokes it. `Wake::Poll` is the neutral poke: it
    /// starts no work and moves no deadline, it only ends the worker's wait.
    fn control(&self, control: Control) -> bool {
        let sent = self
            .controls
            .lock()
            .is_ok_and(|channel| channel.send(control).is_ok());
        if sent {
            self.waker.post(Wake::Poll);
        }
        sent
    }

    fn open_hints(&self) {
        let Ok(mut held) = self.hints.lock() else {
            return;
        };
        if held.is_some() {
            return;
        }
        let mut watcher = (self.new_watcher)();
        let stop = watcher.stop_flag();
        let thread = std::thread::spawn(move || watcher.run());
        *held = Some(Hints { stop, thread });
    }

    fn close_hints(&self) {
        let hints = self.hints.lock().ok().and_then(|mut held| held.take());
        if let Some(hints) = hints {
            hints.stop.store(true, Ordering::SeqCst);
            self.waker.post(Wake::Poll);
            // Not joined: a watcher in its reconnect sleep only sees the flag when the sleep
            // ends. It posts nothing after that and exits at once; `stop` joins the live one.
            drop(hints.thread);
        }
    }

    fn open(
        config: BridgeSyncConfig,
        transport: Arc<dyn BridgeTransport>,
        hints: Arc<dyn BridgeHintStream>,
        observer: Arc<dyn BridgeSyncObserver>,
    ) -> Result<Arc<Self>, Failure> {
        if config.workspace_id.is_empty() || config.database_path.is_empty() {
            return Err(Failure::new("INVALID_REQUEST", Some("workspace_id")));
        }
        let context = &config.context;
        let zone = ZoneName::new(&context.time_zone)
            .map_err(|_| Failure::new("INVALID_REQUEST", Some("time_zone")))?;
        let actor = ActorId::parse(&context.actor_id)
            .map_err(|_| Failure::new("INVALID_REQUEST", Some("actor_id")))?;
        let policy: Policy = super::parse_json(&context.policy, "policy")?;
        let binding = SessionBinding {
            account_id: id(&config.account_id, "account_id")?,
            scope_id: id(&config.scope_id, "scope_id")?,
            device_id: id(&config.device_id, "device_id")?,
            authentication: if config.fresh_authentication {
                Authentication::Fresh
            } else {
                Authentication::Resumed
            },
        };
        let mut store = Store::open(&OpenOptions {
            path: PathBuf::from(&config.database_path),
            workspace_id: config.workspace_id.clone(),
            busy_timeout: Duration::from_millis(u64::from(config.busy_timeout_ms)),
        })
        .map_err(|error| Failure::from(&error))?;
        let session = SyncSession::start(&mut store, &binding)
            .map_err(|error| Failure::new(error.code(), None))?;

        let mut schedule = Schedule::default();
        if let Some(interval) = config.poll_interval_ms {
            schedule.poll_interval = Duration::from_millis(interval.max(1));
            schedule.poll_jitter = schedule.poll_jitter.min(schedule.poll_interval / 4);
        }
        let clock: Arc<dyn Clock> = Arc::new(MonotonicClock::new());
        let syncer = Syncer::new(
            Box::new(ForeignTransport(transport)),
            session,
            Box::new(move || ExecuteContext {
                now: rfc3339_now().unwrap_or_else(|_| {
                    Instant::parse("1970-01-01T00:00:00Z").expect("a valid instant")
                }),
                time_zone: zone.clone(),
                actor_id: actor.clone(),
                policy: policy.clone(),
            }),
            Arc::clone(&clock),
            Box::new(SplitMix::from_entropy()),
            schedule.clone(),
        );
        let closing = syncer.closing_flag();
        let waker = Waker::new();
        let hub = InvalidationHub::new(4);
        let subscription = hub
            .subscribe([ChangeKind::Records, ChangeKind::Issues], true, None)
            .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
        let new_watcher = {
            let (stream, waker, scope, clock, schedule) = (
                Arc::new(ForeignStream(hints)),
                waker.clone(),
                binding.scope_id,
                Arc::clone(&clock),
                schedule.clone(),
            );
            Box::new(move || {
                HintWatcher::new(
                    stream.clone(),
                    waker.clone(),
                    scope.clone(),
                    Arc::clone(&clock),
                    Box::new(SplitMix::from_entropy()),
                    &schedule,
                )
            })
        };
        let worker = SyncLoop::new(
            syncer,
            waker.clone(),
            hub.clone(),
            clock,
            Box::new(SplitMix::from_entropy()),
        );
        let (sender, receiver) = mpsc::channel();
        let thread = std::thread::Builder::new()
            .name("brainbuddy-sync".to_owned())
            .spawn(move || {
                let mut run = Worker {
                    worker,
                    store,
                    controls: receiver,
                    observer,
                    subscription,
                };
                run.run();
            })
            .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
        Ok(Arc::new(Self {
            waker,
            closing,
            hub,
            controls: Mutex::new(sender),
            worker: Mutex::new(Some(thread)),
            hints: Mutex::new(None),
            new_watcher,
        }))
    }
}

impl Drop for BridgeSyncHost {
    fn drop(&mut self) {
        self.stop();
    }
}

/// The sync worker: the loop, its store and its controls, all on one thread.
struct Worker {
    worker: SyncLoop,
    store: Store,
    controls: Receiver<Control>,
    observer: Arc<dyn BridgeSyncObserver>,
    subscription: bb_client::Subscription,
}

impl Worker {
    fn run(&mut self) {
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| self.drive()));
        if outcome.is_err() {
            // The payload may hold input text; it is dropped, never inspected.
            self.observer.round_finished(BridgeSyncReport {
                state: BridgeSyncState::Failed,
                failure_code: Some("INTERNAL_ERROR".to_owned()),
                sent: 0,
                settled: 0,
                pulled_transactions: 0,
                invalidation: None,
            });
        }
        self.worker.close();
    }

    fn drive(&mut self) {
        let waker = self.worker.waker();
        while !waker.is_closed() {
            if self.control() {
                continue;
            }
            let wait = match self.worker.step(&mut self.store) {
                Step::Ran { report, .. } => {
                    self.announce(&report);
                    continue;
                }
                Step::Wait(left) => left,
                Step::Idle => Duration::from_secs(3600),
            };
            // A control sent after the check above posted its poke after the drain inside
            // `step`, so it is still pending here.
            if self.control() {
                continue;
            }
            let woken = waker.wait(wait);
            // Put the wakes back for the next step to read in order.
            for wake in woken.iter() {
                waker.post(wake);
            }
        }
    }

    /// Runs one queued control; true when there was one.
    fn control(&mut self) -> bool {
        let Ok(control) = self.controls.try_recv() else {
            return false;
        };
        match control {
            Control::Background => self.worker.background(),
            Control::Offline => self.worker.offline(),
            Control::Rebuild(reply) => {
                let outcome = self.rebuild();
                let _ = reply.send(outcome);
            }
        }
        true
    }

    /// A non-destructive reset (cursor and staged downloads only), then the snapshot recovery
    /// the pull starts when there is no cursor, until the feed is drained.
    fn rebuild(&mut self) -> BridgeRebuildOutcome {
        let failed = |code: &str| BridgeRebuildOutcome::Failed {
            code: code.to_owned(),
        };
        let syncer = self.worker.syncer_mut();
        if let Err(error) = syncer.session_mut().reset(&mut self.store) {
            return failed(error.code());
        }
        let mut changes = bb_client::Changes::default();
        let outcome = loop {
            let pulled = self.worker.syncer_mut().pull(&mut self.store);
            changes.merge(pulled.changes);
            if let Some(halt) = &pulled.halt {
                break failed(&halt_code(halt));
            }
            if !pulled.more {
                break BridgeRebuildOutcome::Rebuilt;
            }
        };
        if changes.any() {
            let generation = projection_generation(&mut self.store).unwrap_or(0);
            self.worker.hub().publish(generation, &changes);
        }
        // Registration and the waiting sends continue from the new base.
        self.worker.waker().post(Wake::Continue);
        outcome
    }

    fn announce(&mut self, report: &bb_client::RoundReport) {
        let halt = report.halt.as_ref().or(report.pull.halt.as_ref());
        let invalidation = self.subscription.take().map(Self::invalidation);
        self.observer.round_finished(BridgeSyncReport {
            state: state_of(halt),
            failure_code: halt.map(halt_code),
            sent: report.sent,
            settled: report.settled,
            pulled_transactions: report.pull.transactions,
            invalidation,
        });
    }

    fn invalidation(value: Invalidation) -> BridgeSyncInvalidation {
        BridgeSyncInvalidation {
            projection_generation: value.projection_generation.to_string(),
            records_changed: value.changed_kinds.contains(&ChangeKind::Records),
            issues_changed: value.changed_kinds.contains(&ChangeKind::Issues),
            status_changed: value.sync_status_changed,
        }
    }
}
