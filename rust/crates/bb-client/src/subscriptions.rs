//! When to sync, what wakes it, and who is told (sync-v1 sections 7 and 11;
//! runtime-ffi `subscribe`, `sync_now`, `cancel` and `close`).
//!
//! **Wakes only start work.** A foreground, a network return, a manual request,
//! an SSE hint and the fallback poll all do the same thing: ask [`SyncLoop`] to
//! pull (and send). None of them says anything is fresh or changes the cursor;
//! what the server committed is learned only by the authority-checked pull.
//!
//! **The deadline.** [`Scheduler`] starts a fallback poll at most
//! [`Schedule::poll_interval`] (30 s) after the previous poll *started*, never
//! after it finished. Jitter only shortens that interval, so it can never push a
//! poll past 30 s. A wake that arrives during a pull is coalesced into exactly
//! one more pull after it and never moves the next poll. A pull itself is budgeted
//! ([`Schedule::pull_budget`]), so poll interval plus catch-up stays inside the
//! 60 s from commit to visible that SC-004 allows, even when every hint is lost.
//!
//! **Hints.** [`HintWatcher`] holds the authenticated SSE stream through the
//! host's [`HintStream`] port (the adapter adds credentials; none reach this
//! crate), parses it with [`SseParser`], posts [`Wake::StreamOpened`] as soon as
//! a stream opens (the immediate catch-up on every open and reopen) and
//! [`Wake::Hint`] per event, and reconnects with bounded exponential backoff and
//! jitter while the poll schedule carries on. There is no replay position, so
//! `Last-Event-ID` is never sent.
//!
//! **Invalidations.** [`InvalidationHub`] fans one `{projection_generation,
//! changed_kinds, sync_status_changed}` out to a bounded set of subscribers. A
//! slow subscriber holds one coalesced invalidation, never a queue; it
//! re-queries. Closing a [`Subscription`] (or the hub) prevents all later
//! delivery, including a notification already queued.

use crate::execute::projection_generation;
use crate::storage::Store;
use crate::transport::{
    API, Backoff, Cancellation, Changes, Clock, Halt, Jitter, RoundReport, Schedule, Syncer, encode,
};
use bb_protocol::feed::HintEvent;
use bb_protocol::wire::{Id, decode};
use std::collections::{BTreeSet, HashMap};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Condvar, Mutex, MutexGuard};
use std::time::Duration;

// --------------------------------------------------------------------------- wakes

/// Why a pull is wanted.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Wake {
    /// The app became active.
    Foreground,
    /// Connectivity came back.
    NetworkReturn,
    /// The user or a local gesture asks to sync now.
    Manual,
    /// A hint stream just opened (or reopened): catch up at once.
    StreamOpened,
    /// An SSE `scope_changed` event.
    Hint,
    /// The fallback poll came due.
    Poll,
    /// Sends are due again after their backoff.
    Retry,
    /// The previous pull stopped on its budget with more to do.
    Continue,
}

impl Wake {
    const fn bit(self) -> u8 {
        1 << self as u8
    }
}

/// A set of coalesced wakes.
#[derive(Clone, Copy, Default, PartialEq, Eq)]
pub struct WakeSet(u8);

impl std::fmt::Debug for WakeSet {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_set()
            .entries(WakeSet::ALL.iter().filter(|wake| self.contains(**wake)))
            .finish()
    }
}

impl WakeSet {
    const ALL: [Wake; 8] = [
        Wake::Foreground,
        Wake::NetworkReturn,
        Wake::Manual,
        Wake::StreamOpened,
        Wake::Hint,
        Wake::Poll,
        Wake::Retry,
        Wake::Continue,
    ];

    pub fn insert(&mut self, wake: Wake) {
        self.0 |= wake.bit();
    }

    pub fn contains(&self, wake: Wake) -> bool {
        self.0 & wake.bit() != 0
    }

    pub fn is_empty(&self) -> bool {
        self.0 == 0
    }

    pub fn clear(&mut self) {
        self.0 = 0;
    }

    pub fn iter(&self) -> impl Iterator<Item = Wake> + '_ {
        Self::ALL.into_iter().filter(|wake| self.contains(*wake))
    }
}

struct WakerState {
    pending: WakeSet,
    /// Counts foreground and network-return wakes: they cut a reconnect sleep short.
    kicks: u64,
}

struct WakerInner {
    state: Mutex<WakerState>,
    cv: Condvar,
    closed: Arc<AtomicBool>,
}

/// The thread-safe doorbell between wake sources (host callbacks, the hint
/// stream) and the sync loop. Posting never blocks and never queues: repeated
/// wakes collapse into the set.
#[derive(Clone)]
pub struct Waker {
    inner: Arc<WakerInner>,
}

impl Default for Waker {
    fn default() -> Self {
        Self::new()
    }
}

impl Waker {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(WakerInner {
                state: Mutex::new(WakerState {
                    pending: WakeSet::default(),
                    kicks: 0,
                }),
                cv: Condvar::new(),
                closed: Arc::new(AtomicBool::new(false)),
            }),
        }
    }

    fn lock(&self) -> MutexGuard<'_, WakerState> {
        self.inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub fn post(&self, wake: Wake) {
        let mut state = self.lock();
        state.pending.insert(wake);
        if matches!(wake, Wake::Foreground | Wake::NetworkReturn) {
            state.kicks += 1;
        }
        drop(state);
        self.inner.cv.notify_all();
    }

    /// Takes every pending wake, waiting up to `timeout` for the first.
    pub fn wait(&self, timeout: Duration) -> WakeSet {
        let mut state = self.lock();
        if state.pending.is_empty() && !self.is_closed() {
            state = self
                .inner
                .cv
                .wait_timeout(state, timeout)
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .0;
        }
        std::mem::take(&mut state.pending)
    }

    /// Takes the pending wakes without waiting.
    pub fn drain(&self) -> WakeSet {
        std::mem::take(&mut self.lock().pending)
    }

    /// Sleeps up to `duration`; returns early on close or on a foreground or
    /// network-return wake (a reconnect backoff is forgiven by those).
    fn sleep(&self, duration: Duration) {
        let mut state = self.lock();
        let seen = state.kicks;
        let deadline = std::time::Instant::now() + duration;
        while !self.is_closed() && state.kicks == seen {
            let left = deadline.saturating_duration_since(std::time::Instant::now());
            if left.is_zero() {
                break;
            }
            state = self
                .inner
                .cv
                .wait_timeout(state, left)
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .0;
        }
    }

    /// Ends every wait and every user of this waker's flag.
    pub fn close(&self) {
        self.inner.closed.store(true, Ordering::SeqCst);
        self.inner.cv.notify_all();
    }

    pub fn is_closed(&self) -> bool {
        self.inner.closed.load(Ordering::SeqCst)
    }

    fn closed_flag(&self) -> &AtomicBool {
        &self.inner.closed
    }
}

// ------------------------------------------------------------------------ scheduler

/// What the scheduler wants done next.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    /// Run a round now, for this reason.
    Pull(Wake),
    /// Nothing is due; the next thing is due after this long.
    Wait(Duration),
    /// Inactive, offline or paused: only a wake can change that.
    Idle,
}

/// The pull schedule, as pure state over a caller-supplied monotonic `now`.
pub struct Scheduler {
    schedule: Schedule,
    active: bool,
    online: bool,
    /// Auth or update required: no polling until a foreground or manual wake.
    paused: bool,
    pending: WakeSet,
    next_poll: Option<Duration>,
    retry_at: Option<Duration>,
    backoff: Backoff,
}

impl Scheduler {
    pub fn new(schedule: Schedule) -> Self {
        let backoff = Backoff::new(
            schedule.send_backoff_base,
            schedule.stream_backoff_cap.min(schedule.poll_interval / 2),
            schedule.retry_after_cap,
        );
        Self {
            schedule,
            active: false,
            online: true,
            paused: false,
            pending: WakeSet::default(),
            next_poll: None,
            retry_at: None,
            backoff,
        }
    }

    pub fn is_active(&self) -> bool {
        self.active
    }

    pub fn is_online(&self) -> bool {
        self.online
    }

    pub fn is_paused(&self) -> bool {
        self.paused
    }

    /// When the next fallback poll is due (monotonic), if the schedule runs.
    pub fn next_poll(&self) -> Option<Duration> {
        self.next_poll
    }

    /// Records a wake. A foreground starts the active period; a network return
    /// ends an offline one; the rest only matter while active.
    pub fn wake(&mut self, wake: Wake) {
        match wake {
            Wake::Foreground => {
                self.active = true;
                self.paused = false;
                self.pending.insert(wake);
            }
            Wake::NetworkReturn => {
                if !self.online {
                    self.online = true;
                }
                self.backoff.success();
                self.pending.insert(wake);
            }
            Wake::Manual => {
                self.paused = false;
                self.pending.insert(wake);
            }
            other => {
                if self.active {
                    self.pending.insert(other);
                }
            }
        }
    }

    /// The app left the foreground: no polls, no pulls, until the next foreground.
    pub fn set_inactive(&mut self) {
        self.active = false;
        self.next_poll = None;
        self.retry_at = None;
        self.pending.clear();
    }

    /// Connectivity was lost: nothing is attempted until [`Wake::NetworkReturn`].
    pub fn set_offline(&mut self) {
        self.online = false;
    }

    /// What to do at `now`.
    pub fn next_action(&mut self, now: Duration) -> Action {
        if !self.active || !self.online || self.paused {
            return Action::Idle;
        }
        for urgent in [
            Wake::Foreground,
            Wake::NetworkReturn,
            Wake::Manual,
            Wake::StreamOpened,
            Wake::Continue,
        ] {
            if self.pending.contains(urgent) {
                return Action::Pull(urgent);
            }
        }
        // A scheduled poll ignores the failure backoff: the 30-second bound is
        // the point of the schedule. A poll takes precedence over a hint so the
        // anchor moves.
        if self.next_poll.is_none_or(|due| now >= due) {
            return Action::Pull(Wake::Poll);
        }
        if self.retry_at.is_some_and(|at| now >= at) {
            return Action::Pull(Wake::Retry);
        }
        let hinted = self.pending.contains(Wake::Hint);
        if hinted && self.backoff.ready(now) {
            return Action::Pull(Wake::Hint);
        }
        let mut due = self.next_poll.unwrap_or(now);
        if let Some(at) = self.retry_at {
            due = due.min(at);
        }
        if hinted {
            due = due.min(self.backoff.until());
        }
        Action::Wait(due.saturating_sub(now))
    }

    /// A round for `reason` starts at `now`. Every wake pending so far is
    /// satisfied by it; a foreground or a poll anchors the next poll to *this*
    /// start, minus jitter.
    pub fn started(&mut self, now: Duration, reason: Wake, jitter: &mut dyn Jitter) {
        self.pending.clear();
        self.retry_at = None;
        if matches!(reason, Wake::Foreground | Wake::Poll) || self.next_poll.is_none() {
            let shortened = self
                .schedule
                .poll_jitter
                .mul_f64(jitter.unit().clamp(0.0, 1.0));
            self.next_poll = Some(now + self.schedule.poll_interval.saturating_sub(shortened));
        }
    }

    /// A round ended at `now`.
    pub fn finished(&mut self, now: Duration, report: &RoundReport, jitter: &mut dyn Jitter) {
        let halt = report.halt.as_ref().or(report.pull.halt.as_ref());
        match halt {
            None => self.backoff.success(),
            Some(Halt::Offline) => {
                self.backoff.failure(now, None, jitter);
            }
            Some(Halt::Retry { after }) => {
                self.backoff.failure(now, *after, jitter);
            }
            Some(Halt::AuthRequired | Halt::UpdateRequired) => self.paused = true,
            Some(_) => {}
        }
        self.retry_at = report.send_retry_at;
        if report.pull.more || report.more_sends {
            self.pending.insert(Wake::Continue);
        }
    }
}

// ------------------------------------------------------------------ the SSE stream

/// The largest SSE line or event the parser accepts; hints are content-free
/// and tiny, so a larger one is a broken or hostile stream.
pub const SSE_MAX_EVENT_BYTES: usize = 16 * 1024;

/// What one blank-line-terminated SSE block meant.
#[derive(Clone, Debug, PartialEq)]
pub enum SseItem {
    /// A `scope_changed` event with a well-formed content-free body.
    Hint(HintEvent),
    /// A `:` comment, e.g. the server's heartbeat.
    Comment,
    /// An event this client does not act on (other type, or a body the codec
    /// refuses, e.g. an unknown key).
    Ignored,
}

/// A stream no parser can recover: close it and reconnect.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SseOverflow;

/// Incremental `text/event-stream` parser over arbitrary chunking. It reads the
/// `event` and `data` fields only: `id` and `retry` are ignored, because there
/// is no replay history and no `Last-Event-ID` is ever sent.
#[derive(Default)]
pub struct SseParser {
    line: Vec<u8>,
    after_cr: bool,
    event: Option<Vec<u8>>,
    data: Vec<u8>,
    has_data: bool,
    started: bool,
    ignored: u64,
}

impl SseParser {
    pub fn new() -> Self {
        Self::default()
    }

    /// Events refused so far (malformed or unknown body).
    pub fn ignored(&self) -> u64 {
        self.ignored
    }

    /// Feeds the next bytes of the stream.
    ///
    /// # Errors
    ///
    /// [`SseOverflow`] when a line or an event exceeds [`SSE_MAX_EVENT_BYTES`].
    pub fn feed(&mut self, chunk: &[u8]) -> Result<Vec<SseItem>, SseOverflow> {
        let mut items = Vec::new();
        let mut chunk = chunk;
        if !self.started && !chunk.is_empty() {
            self.started = true;
            chunk = chunk.strip_prefix(b"\xEF\xBB\xBF").unwrap_or(chunk);
        }
        for &byte in chunk {
            if std::mem::take(&mut self.after_cr) && byte == b'\n' {
                continue; // the LF of a CRLF whose CR already ended the line
            }
            match byte {
                b'\r' => {
                    self.after_cr = true;
                    self.end_line(&mut items);
                }
                b'\n' => self.end_line(&mut items),
                other => {
                    self.line.push(other);
                    if self.line.len() > SSE_MAX_EVENT_BYTES {
                        return Err(SseOverflow);
                    }
                }
            }
            if self.data.len() > SSE_MAX_EVENT_BYTES {
                return Err(SseOverflow);
            }
        }
        Ok(items)
    }

    fn end_line(&mut self, items: &mut Vec<SseItem>) {
        let line = std::mem::take(&mut self.line);
        if line.is_empty() {
            self.dispatch(items);
            return;
        }
        if line[0] == b':' {
            items.push(SseItem::Comment);
            return;
        }
        let (name, value) = match line.iter().position(|byte| *byte == b':') {
            Some(at) => {
                let value = &line[at + 1..];
                (&line[..at], value.strip_prefix(b" ").unwrap_or(value))
            }
            None => (&line[..], &line[line.len()..]),
        };
        match name {
            b"event" => self.event = Some(value.to_vec()),
            b"data" => {
                self.data.extend_from_slice(value);
                self.data.push(b'\n');
                self.has_data = true;
            }
            _ => {} // id, retry and unknown fields carry no authority here
        }
    }

    fn dispatch(&mut self, items: &mut Vec<SseItem>) {
        let event = self.event.take();
        let mut data = std::mem::take(&mut self.data);
        if !std::mem::take(&mut self.has_data) {
            return;
        }
        data.pop(); // the newline after the last data line
        if event.as_deref() != Some(b"scope_changed") {
            items.push(SseItem::Ignored);
            return;
        }
        let hint = std::str::from_utf8(&data)
            .ok()
            .and_then(|text| decode::<HintEvent>(text).ok());
        match hint {
            Some(hint) => items.push(SseItem::Hint(hint)),
            None => {
                self.ignored += 1;
                items.push(SseItem::Ignored);
            }
        }
    }
}

/// Why a hint stream could not open or ended.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StreamFailure {
    /// The route answered with this status instead of a stream.
    Status(u16),
    /// Nothing arrived within the idle timeout (heartbeats are every 15 s).
    Timeout,
    Connection,
    Cancelled,
}

/// An open `text/event-stream` response body.
pub trait HintReader: Send {
    /// Reads the next bytes. `Ok(0)` is the server closing the stream.
    ///
    /// # Errors
    ///
    /// [`StreamFailure::Timeout`] when `idle` passes without a byte,
    /// [`StreamFailure::Cancelled`] once `cancel` is raised.
    fn read(
        &mut self,
        buffer: &mut [u8],
        cancel: &Cancellation<'_>,
    ) -> Result<usize, StreamFailure>;
}

/// The host's authenticated streaming GET: it adds credentials and an
/// `Accept: text/event-stream` header, sends no `Last-Event-ID`, and returns
/// the body only for a `200`.
pub trait HintStream: Send + Sync {
    /// # Errors
    ///
    /// [`StreamFailure::Status`] for any non-200 answer.
    fn open(
        &self,
        path: &str,
        idle: Duration,
        cancel: &Cancellation<'_>,
    ) -> Result<Box<dyn HintReader>, StreamFailure>;
}

/// How one hint-stream attempt ended.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StreamEnd {
    /// Cancelled or closed by us.
    Closed,
    /// The stream opened and later ended or went silent after living this long.
    Ended { lived: Duration, hints: u64 },
    /// It never opened.
    NotOpened(StreamFailure),
}

/// The hint stream's lifetime: connect, read, reconnect. One per active scope,
/// run on its own thread by the host (or [`HintWatcher::run`] in a spawned one).
pub struct HintWatcher {
    stream: Arc<dyn HintStream>,
    waker: Waker,
    scope_id: Id,
    clock: Arc<dyn Clock>,
    jitter: Box<dyn Jitter>,
    backoff: Backoff,
    stop: Arc<AtomicBool>,
    idle: Duration,
    stable_after: Duration,
    opened: u64,
    hints: u64,
}

impl HintWatcher {
    /// A stream silent for 40 s (heartbeats come at most 15 s apart) is dead.
    pub const IDLE_TIMEOUT: Duration = Duration::from_secs(40);

    pub fn new(
        stream: Arc<dyn HintStream>,
        waker: Waker,
        scope_id: Id,
        clock: Arc<dyn Clock>,
        jitter: Box<dyn Jitter>,
        schedule: &Schedule,
    ) -> Self {
        Self {
            stream,
            waker,
            scope_id,
            clock,
            jitter,
            backoff: Backoff::new(
                schedule.stream_backoff_base,
                schedule.stream_backoff_cap,
                schedule.retry_after_cap,
            ),
            stop: Arc::new(AtomicBool::new(false)),
            idle: Self::IDLE_TIMEOUT,
            stable_after: schedule.stream_backoff_base,
            opened: 0,
            hints: 0,
        }
    }

    /// Raised by [`HintWatcher::stop`]; releases the stream within one read.
    pub fn stop_flag(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.stop)
    }

    pub fn stop(&self) {
        self.stop.store(true, Ordering::SeqCst);
        self.waker.inner.cv.notify_all();
    }

    /// Streams opened so far.
    pub fn opened(&self) -> u64 {
        self.opened
    }

    /// Hints delivered so far (before the loop coalesces them).
    pub fn hints(&self) -> u64 {
        self.hints
    }

    fn halted(&self) -> bool {
        self.stop.load(Ordering::SeqCst) || self.waker.is_closed()
    }

    /// Connects and reads until the stream ends. Posts [`Wake::StreamOpened`]
    /// the moment it opens and [`Wake::Hint`] for each valid event of this scope.
    pub fn connect_once(&mut self) -> StreamEnd {
        if self.halted() {
            return StreamEnd::Closed;
        }
        let path = format!("{API}/hints?scope_id={}", encode(self.scope_id.as_str()));
        let cancel = Cancellation::new(&self.stop, self.waker.closed_flag());
        let mut reader = match self.stream.open(&path, self.idle, &cancel) {
            Ok(reader) => reader,
            Err(StreamFailure::Cancelled) => return StreamEnd::Closed,
            Err(failure) => return StreamEnd::NotOpened(failure),
        };
        let opened_at = self.clock.now();
        self.opened += 1;
        // Catch up immediately on every open and reopen: events are not replayed.
        self.waker.post(Wake::StreamOpened);
        let mut parser = SseParser::new();
        let mut buffer = [0u8; 4096];
        let mut hints = 0;
        loop {
            let read = reader.read(&mut buffer, &cancel);
            let lived = self.clock.now().saturating_sub(opened_at);
            let count = match read {
                Ok(0)
                | Err(
                    StreamFailure::Timeout | StreamFailure::Connection | StreamFailure::Status(_),
                ) => {
                    return StreamEnd::Ended { lived, hints };
                }
                Err(StreamFailure::Cancelled) => return StreamEnd::Closed,
                Ok(count) => count,
            };
            let Ok(items) = parser.feed(&buffer[..count]) else {
                return StreamEnd::Ended { lived, hints };
            };
            for item in items {
                if let SseItem::Hint(event) = item {
                    // A hint for another scope grants nothing and wakes nothing.
                    if event.scope_id == self.scope_id {
                        hints += 1;
                        self.hints += 1;
                        self.waker.post(Wake::Hint);
                    }
                }
            }
        }
    }

    /// How long to wait before reconnecting after `end`: nothing after a stream
    /// that lived a while (the server's 15-minute cap, a restart), otherwise
    /// exponential backoff with jitter, capped.
    pub fn reconnect_delay(&mut self, end: StreamEnd) -> Duration {
        let now = self.clock.now();
        match end {
            StreamEnd::Closed => Duration::ZERO,
            StreamEnd::Ended { lived, .. } if lived >= self.stable_after => {
                self.backoff.success();
                Duration::ZERO
            }
            StreamEnd::Ended { .. } => self.backoff.failure(now, None, self.jitter.as_mut()),
            // Not signed in, or the scope is not admitted: retrying fast helps no
            // one, so wait the longest delay until a foreground cuts it short.
            StreamEnd::NotOpened(StreamFailure::Status(401 | 403 | 404)) => {
                self.backoff.failure(now, None, self.jitter.as_mut());
                self.backoff.failure(now, None, self.jitter.as_mut())
            }
            StreamEnd::NotOpened(_) => self.backoff.failure(now, None, self.jitter.as_mut()),
        }
    }

    /// Runs until stopped or the waker is closed.
    pub fn run(&mut self) {
        while !self.halted() {
            let end = self.connect_once();
            let delay = self.reconnect_delay(end);
            if !delay.is_zero() {
                self.waker.sleep(delay);
            }
        }
    }
}

// ----------------------------------------------------------------- invalidations

/// What kind of query result a change can affect.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ChangeKind {
    /// Task, project, tag and Review records.
    Records,
    /// The sync issues list.
    Issues,
}

/// The bounded notification a subscriber receives: it says what to re-query,
/// not what changed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Invalidation {
    pub projection_generation: u64,
    pub changed_kinds: BTreeSet<ChangeKind>,
    pub sync_status_changed: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SubscriptionError {
    /// The hub holds its maximum number of subscribers.
    TooMany,
    /// The hub was closed.
    Closed,
}

type Notify = Arc<dyn Fn() + Send + Sync>;

struct Slot {
    kinds: BTreeSet<ChangeKind>,
    status: bool,
    pending: Option<Invalidation>,
    notify: Option<Notify>,
    live: Arc<AtomicBool>,
}

struct HubState {
    next_id: u64,
    closed: bool,
    slots: HashMap<u64, Slot>,
}

struct HubInner {
    state: Mutex<HubState>,
    capacity: usize,
    published: AtomicU64,
}

/// The fan-out of invalidations. Cheap to clone; clones share subscribers.
#[derive(Clone)]
pub struct InvalidationHub {
    inner: Arc<HubInner>,
}

impl InvalidationHub {
    /// A hub that accepts at most `capacity` subscribers.
    pub fn new(capacity: usize) -> Self {
        Self {
            inner: Arc::new(HubInner {
                state: Mutex::new(HubState {
                    next_id: 1,
                    closed: false,
                    slots: HashMap::new(),
                }),
                capacity,
                published: AtomicU64::new(0),
            }),
        }
    }

    fn lock(&self) -> MutexGuard<'_, HubState> {
        self.inner
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    /// Subscribes to `kinds` (and to sync-status changes when `status`). `notify`
    /// is a content-free poke called, off the hub's lock, when the subscriber
    /// goes from nothing pending to something pending; it must hand off to the
    /// host's executor and return. Further invalidations coalesce into the one
    /// already pending, without another call.
    ///
    /// # Errors
    ///
    /// [`SubscriptionError`] when the hub is full or closed.
    pub fn subscribe(
        &self,
        kinds: impl IntoIterator<Item = ChangeKind>,
        status: bool,
        notify: Option<Notify>,
    ) -> Result<Subscription, SubscriptionError> {
        let mut state = self.lock();
        if state.closed {
            return Err(SubscriptionError::Closed);
        }
        if state.slots.len() >= self.inner.capacity {
            return Err(SubscriptionError::TooMany);
        }
        let id = state.next_id;
        state.next_id += 1;
        let live = Arc::new(AtomicBool::new(true));
        state.slots.insert(
            id,
            Slot {
                kinds: kinds.into_iter().collect(),
                status,
                pending: None,
                notify,
                live: Arc::clone(&live),
            },
        );
        Ok(Subscription {
            id,
            hub: self.clone(),
            live,
        })
    }

    /// Number of live subscribers.
    pub fn subscribers(&self) -> usize {
        self.lock().slots.len()
    }

    /// Publishes one change. Each interested subscriber's pending invalidation
    /// absorbs it: the latest generation, the union of kinds, status if any.
    pub fn publish(&self, projection_generation: u64, changes: &Changes) {
        let mut kinds = BTreeSet::new();
        if changes.records {
            kinds.insert(ChangeKind::Records);
        }
        if changes.issues {
            kinds.insert(ChangeKind::Issues);
        }
        if kinds.is_empty() && !changes.status {
            return;
        }
        self.inner.published.fetch_add(1, Ordering::SeqCst);
        let mut pokes: Vec<(Notify, Arc<AtomicBool>)> = Vec::new();
        {
            let mut state = self.lock();
            for slot in state.slots.values_mut() {
                let relevant: BTreeSet<ChangeKind> =
                    kinds.intersection(&slot.kinds).copied().collect();
                let status = changes.status && slot.status;
                if relevant.is_empty() && !status {
                    continue;
                }
                match slot.pending.as_mut() {
                    Some(pending) => {
                        pending.projection_generation =
                            pending.projection_generation.max(projection_generation);
                        pending.changed_kinds.extend(relevant);
                        pending.sync_status_changed |= status;
                    }
                    None => {
                        slot.pending = Some(Invalidation {
                            projection_generation,
                            changed_kinds: relevant,
                            sync_status_changed: status,
                        });
                        if let Some(notify) = &slot.notify {
                            pokes.push((Arc::clone(notify), Arc::clone(&slot.live)));
                        }
                    }
                }
            }
        }
        for (notify, live) in pokes {
            // A subscriber closed after the poke was queued is not called.
            if live.load(Ordering::SeqCst) {
                notify();
            }
        }
    }

    /// How many publications carried anything (diagnostics and tests).
    pub fn published(&self) -> u64 {
        self.inner.published.load(Ordering::SeqCst)
    }

    /// Releases every subscriber: nothing is delivered after this returns.
    pub fn close(&self) {
        let mut state = self.lock();
        state.closed = true;
        for (_, slot) in state.slots.drain() {
            slot.live.store(false, Ordering::SeqCst);
        }
    }
}

/// One subscriber's handle. Dropping it unsubscribes.
pub struct Subscription {
    id: u64,
    hub: InvalidationHub,
    live: Arc<AtomicBool>,
}

impl Subscription {
    /// Takes the coalesced invalidation, if any. Never delivers after close.
    pub fn take(&self) -> Option<Invalidation> {
        if !self.live.load(Ordering::SeqCst) {
            return None;
        }
        self.hub.lock().slots.get_mut(&self.id)?.pending.take()
    }

    pub fn is_live(&self) -> bool {
        self.live.load(Ordering::SeqCst)
    }

    /// Unsubscribes; idempotent.
    pub fn close(&self) {
        self.live.store(false, Ordering::SeqCst);
        self.hub.lock().slots.remove(&self.id);
    }
}

impl Drop for Subscription {
    fn drop(&mut self) {
        self.close();
    }
}

// ---------------------------------------------------------------------- the loop

/// What one [`SyncLoop::step`] did.
#[derive(Debug)]
pub enum Step {
    /// A round ran.
    Ran {
        reason: Wake,
        report: Box<RoundReport>,
    },
    /// Nothing is due for this long.
    Wait(Duration),
    /// Inactive, offline or paused.
    Idle,
}

/// The sync worker: a scheduler, a syncer and the invalidation hub. Drive it
/// with [`SyncLoop::step`] (tests, a host event loop) or [`SyncLoop::run`] on a
/// dedicated background thread, never the main one.
pub struct SyncLoop {
    syncer: Syncer,
    scheduler: Scheduler,
    waker: Waker,
    hub: InvalidationHub,
    clock: Arc<dyn Clock>,
    jitter: Box<dyn Jitter>,
    last_halt: Option<Halt>,
}

impl SyncLoop {
    pub fn new(
        syncer: Syncer,
        waker: Waker,
        hub: InvalidationHub,
        clock: Arc<dyn Clock>,
        jitter: Box<dyn Jitter>,
    ) -> Self {
        let scheduler = Scheduler::new(syncer.schedule().clone());
        Self {
            syncer,
            scheduler,
            waker,
            hub,
            clock,
            jitter,
            last_halt: None,
        }
    }

    pub fn scheduler(&self) -> &Scheduler {
        &self.scheduler
    }

    pub fn syncer_mut(&mut self) -> &mut Syncer {
        &mut self.syncer
    }

    pub fn waker(&self) -> Waker {
        self.waker.clone()
    }

    pub fn hub(&self) -> InvalidationHub {
        self.hub.clone()
    }

    /// The app left the foreground.
    pub fn background(&mut self) {
        self.scheduler.set_inactive();
    }

    /// Connectivity was lost.
    pub fn offline(&mut self) {
        self.scheduler.set_offline();
    }

    /// Cancels in-flight calls, releases every subscriber and stops waiting.
    /// Durable commands survive; nothing is delivered afterwards.
    pub fn close(&mut self) {
        self.syncer.close();
        self.hub.close();
        self.waker.close();
    }

    /// Takes the posted wakes and does what is due.
    pub fn step(&mut self, store: &mut Store) -> Step {
        for wake in self.waker.drain().iter() {
            if matches!(wake, Wake::Foreground | Wake::NetworkReturn | Wake::Manual) {
                self.syncer.resume();
            }
            self.scheduler.wake(wake);
        }
        let now = self.clock.now();
        match self.scheduler.next_action(now) {
            Action::Idle => Step::Idle,
            Action::Wait(left) => Step::Wait(left),
            Action::Pull(reason) => {
                self.scheduler.started(now, reason, self.jitter.as_mut());
                let report = self.syncer.round(store);
                self.scheduler
                    .finished(self.clock.now(), &report, self.jitter.as_mut());
                self.announce(store, &report);
                Step::Ran {
                    reason,
                    report: Box::new(report),
                }
            }
        }
    }

    /// Runs rounds and waits until [`SyncLoop::close`].
    pub fn run(&mut self, store: &mut Store) {
        while !self.waker.is_closed() {
            let wait = match self.step(store) {
                Step::Ran { .. } => continue,
                Step::Wait(left) => left,
                Step::Idle => Duration::from_secs(3600),
            };
            let woken = self.waker.wait(wait);
            // Put the wakes back for the next step to read in order.
            for wake in woken.iter() {
                self.waker.post(wake);
            }
        }
    }

    fn announce(&mut self, store: &mut Store, report: &RoundReport) {
        let mut changes = report.changes;
        let halt = report.halt.clone().or_else(|| report.pull.halt.clone());
        // A different stopping reason is a status change (signed out, offline,
        // update required, back to normal) even when no record moved.
        if halt != self.last_halt {
            changes.status = true;
            self.last_halt = halt;
        }
        if changes.any() {
            let generation = projection_generation(store).unwrap_or(0);
            self.hub.publish(generation, &changes);
        }
    }
}
