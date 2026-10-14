//! The sync transport: sends, receipt lookups, device registration, delta pulls
//! and snapshot recovery over a host-supplied HTTP port (sync-v1 sections 5, 6,
//! 7 and 11; runtime-ffi `sync_now` and `cancel`).
//!
//! **The crate never sees a credential or opens a socket.** Every exchange is an
//! [`HttpRequest`] handed to the [`Transport`] port; the OS adapter adds the
//! session cookie or token and performs the call (off the main thread, with the
//! timeout the request names), and answers with a status, an optional
//! `Retry-After` and the body. Everything else is decided here.
//!
//! **Answers count only through the session.** Each exchange is issued under a
//! [`Request`] from [`SyncSession`], and its answer is applied through the
//! request's fence, so a reset, a restore, a sign-out or [`Syncer::close`] turns
//! a late answer into nothing. Cancelling leaves an uncertain send to receipt
//! reconciliation: the outbox row was marked `sending` before the call, so a
//! lost answer becomes `unknown` and the next attempt starts with a lookup.
//!
//! **Sends are bounded and ordered.** One command at a time in local sequence
//! order, at most [`Schedule::max_sends_per_round`] per round. A command is
//! sendable when [`send_candidates`] says so (its epoch is registered, every
//! command it depends on is settled by the server), so a blocked chain waits
//! while independent work flows. A transport failure, a `5xx` or a `429` backs
//! the whole send side off (exponential, jittered, `Retry-After` honoured) and
//! ends the round; a command that fails [`Schedule::max_send_attempts`] times in
//! a row is parked until a foreground, network-return or manual wake. Nothing
//! here destroys the outbox: the same immutable envelope is sent again, or its
//! receipt is read.
//!
//! **Pulls are budgeted.** A pull runs pages until the feed is drained, but
//! stops starting requests once [`Schedule::pull_budget`] is spent, so with the
//! per-request timeout it fits the 30 seconds sync-v1 section 7 leaves for
//! requests, catch-up and application. What is left is reported as `more`.
//!
//! The scheduling of *when* to pull or send lives in [`crate::subscriptions`].

use crate::apply_changes::{
    ApplyError, FeedStep, Recovery, TransferFault, apply_changes, apply_transfer, fence_in,
    stage_transfer_page,
};
use crate::epochs::{apply_registration, send_candidates};
use crate::execute::ExecuteContext;
use crate::issues::{IssueReason, record_rejection_in};
use crate::receipts::{Looked, Settlement, apply_lookup, apply_receipt};
use crate::replay::ReplayError;
use crate::snapshot::{activate_snapshot, begin_snapshot, stage_snapshot_page};
use crate::storage::{Store, StoreError};
use crate::sync_session::{
    CapabilitiesCheck, ErrorAction, Request, RequestKind, SessionError, SyncSession,
};
use bb_protocol::capabilities::{Capabilities, DeviceRegistration};
use bb_protocol::feed::{ChangesPage, SnapshotManifest, SnapshotPage, TransferPage};
use bb_protocol::receipt::{CommandLookup, ErrorBody, Receipt};
use bb_protocol::wire::{CommandId, Id, Wire, decode};
use serde_json::json;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

/// The path prefix of every sync endpoint.
pub const API: &str = "/api/sync/v1";

// ---------------------------------------------------------------------- the ports

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Method {
    Get,
    Post,
}

/// One HTTP call for the host adapter to perform. `path` is origin-relative and
/// already percent-encoded; the adapter adds its credentials.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HttpRequest {
    pub method: Method,
    pub path: String,
    /// The JSON body of a `POST`, byte for byte.
    pub body: Option<Vec<u8>>,
    /// How long the adapter may wait for the whole answer.
    pub timeout: Duration,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HttpResponse {
    pub status: u16,
    /// The parsed `Retry-After` header, when present.
    pub retry_after: Option<Duration>,
    pub body: Vec<u8>,
}

/// Why no HTTP answer arrived.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TransportFailure {
    Timeout,
    Connection,
    /// The call was aborted because its [`Cancellation`] was raised.
    Cancelled,
}

/// What a running call polls to know it should stop: the request's own flag (a
/// reset or the end of the session raises it) or the transport's close.
#[derive(Clone, Copy)]
pub struct Cancellation<'a> {
    request: &'a AtomicBool,
    closing: &'a AtomicBool,
}

impl<'a> Cancellation<'a> {
    pub(crate) fn new(request: &'a AtomicBool, closing: &'a AtomicBool) -> Self {
        Self { request, closing }
    }

    pub fn is_cancelled(&self) -> bool {
        self.request.load(Ordering::SeqCst) || self.closing.load(Ordering::SeqCst)
    }
}

/// The authenticated HTTP adapter the OS provides.
pub trait Transport: Send + Sync {
    /// Performs `request`, stopping early with [`TransportFailure::Cancelled`]
    /// once `cancel` is raised.
    ///
    /// # Errors
    ///
    /// [`TransportFailure`] when no HTTP answer arrived. A non-2xx status is an
    /// answer, not a failure.
    fn send(
        &self,
        request: &HttpRequest,
        cancel: &Cancellation<'_>,
    ) -> Result<HttpResponse, TransportFailure>;
}

/// Monotonic time as a duration since an arbitrary start; never the wall clock.
pub trait Clock: Send + Sync {
    fn now(&self) -> Duration;
}

/// [`Clock`] over `std::time::Instant`.
pub struct MonotonicClock(std::time::Instant);

impl MonotonicClock {
    pub fn new() -> Self {
        Self(std::time::Instant::now())
    }
}

impl Default for MonotonicClock {
    fn default() -> Self {
        Self::new()
    }
}

impl Clock for MonotonicClock {
    fn now(&self) -> Duration {
        self.0.elapsed()
    }
}

/// A source of jitter in `[0, 1)`.
pub trait Jitter: Send {
    fn unit(&mut self) -> f64;
}

/// SplitMix64: small, seedable, good enough to spread retries.
pub struct SplitMix(u64);

impl SplitMix {
    pub fn seeded(seed: u64) -> Self {
        Self(seed)
    }

    /// Seeded from the wall clock and process ID, so devices do not retry in step.
    pub fn from_entropy() -> Self {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |elapsed| elapsed.as_nanos() as u64);
        Self(nanos ^ (u64::from(std::process::id()) << 32))
    }
}

impl Jitter for SplitMix {
    fn unit(&mut self) -> f64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^= z >> 31;
        (z >> 11) as f64 / (1u64 << 53) as f64
    }
}

// -------------------------------------------------------------------- the schedule

/// Every bound the transport and its scheduler obey.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Schedule {
    /// Fallback polls start at most this far apart (sync-v1 section 7).
    pub poll_interval: Duration,
    /// Jitter only ever *shortens* the interval, by up to this much.
    pub poll_jitter: Duration,
    /// The adapter's timeout for one request.
    pub request_timeout: Duration,
    /// No new pull request starts once a pull has run this long.
    pub pull_budget: Duration,
    pub page_limit: u32,
    pub max_pages_per_pull: u32,
    pub max_sends_per_round: u32,
    /// Consecutive failures after which a command is parked.
    pub max_send_attempts: u32,
    pub send_backoff_base: Duration,
    pub send_backoff_cap: Duration,
    /// The longest `Retry-After` honoured.
    pub retry_after_cap: Duration,
    /// Reconnect backoff of the hint stream.
    pub stream_backoff_base: Duration,
    pub stream_backoff_cap: Duration,
}

/// SC-004 leaves 30 of the 60 seconds from commit to visible for requests,
/// catch-up and application; the other 30 are the poll interval.
pub const CATCH_UP_WINDOW: Duration = Duration::from_secs(30);

impl Default for Schedule {
    fn default() -> Self {
        Self {
            poll_interval: Duration::from_secs(30),
            poll_jitter: Duration::from_secs(5),
            request_timeout: Duration::from_secs(8),
            pull_budget: Duration::from_secs(20),
            page_limit: 100,
            max_pages_per_pull: 200,
            max_sends_per_round: 20,
            max_send_attempts: 5,
            send_backoff_base: Duration::from_secs(1),
            send_backoff_cap: Duration::from_secs(60),
            retry_after_cap: Duration::from_secs(300),
            stream_backoff_base: Duration::from_secs(1),
            stream_backoff_cap: Duration::from_secs(30),
        }
    }
}

impl Schedule {
    /// Whether one pull, from its first request to its last, fits the window
    /// SC-004 leaves for catch-up.
    pub fn fits_catch_up_window(&self) -> bool {
        self.pull_budget + self.request_timeout <= CATCH_UP_WINDOW
            && self.poll_jitter < self.poll_interval
    }
}

/// Exponential backoff with jitter: the delay after the n-th consecutive failure
/// is uniform in `[ceiling/2, ceiling]` with `ceiling = min(cap, base * 2^n)`,
/// and never shorter than the server's `Retry-After`.
#[derive(Clone, Debug)]
pub struct Backoff {
    base: Duration,
    cap: Duration,
    retry_after_cap: Duration,
    failures: u32,
    until: Duration,
}

impl Backoff {
    pub fn new(base: Duration, cap: Duration, retry_after_cap: Duration) -> Self {
        Self {
            base,
            cap,
            retry_after_cap,
            failures: 0,
            until: Duration::ZERO,
        }
    }

    /// Records a failure at `now`; returns the delay it imposes.
    pub fn failure(
        &mut self,
        now: Duration,
        retry_after: Option<Duration>,
        jitter: &mut dyn Jitter,
    ) -> Duration {
        let ceiling = self
            .base
            .saturating_mul(2u32.saturating_pow(self.failures.min(20)))
            .min(self.cap);
        let half = ceiling / 2;
        let spread = half.mul_f64(jitter.unit().clamp(0.0, 1.0));
        let delay = (half + spread)
            .max(retry_after.map_or(Duration::ZERO, |after| after.min(self.retry_after_cap)));
        self.failures = self.failures.saturating_add(1);
        self.until = now + delay;
        delay
    }

    pub fn success(&mut self) {
        self.failures = 0;
        self.until = Duration::ZERO;
    }

    pub fn ready(&self, now: Duration) -> bool {
        now >= self.until
    }

    /// When the backoff ends (already past when ready).
    pub fn until(&self) -> Duration {
        self.until
    }

    pub fn failures(&self) -> u32 {
        self.failures
    }
}

// ------------------------------------------------------------------------ reports

/// Why a step stopped. Nothing here loses saved work.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Halt {
    /// The transport was closed or the request cancelled.
    Cancelled,
    /// No HTTP answer: timeout or connection loss.
    Offline,
    /// `429`, `5xx`, a retryable error, or work the server has not finished.
    Retry {
        after: Option<Duration>,
    },
    /// `401` or a revoked session: pause until the platform authenticates again.
    AuthRequired,
    /// The server or protocol is newer than this build.
    UpdateRequired,
    /// The answer belongs to an earlier request generation: ignored.
    Stale,
    /// The server asked for a reset (the snapshot recovery follows).
    ResetRequired,
    /// The server closed the device epoch.
    EpochClosed,
    /// The epoch or base is not ready for this step yet.
    NotReady,
    Store(StoreError),
    Failed(String),
}

impl From<StoreError> for Halt {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}

impl From<SessionError> for Halt {
    fn from(error: SessionError) -> Self {
        match error {
            SessionError::Store(error) => Self::Store(error),
            SessionError::NotAuthorized | SessionError::Superseded => Self::AuthRequired,
            SessionError::Cancelled => Self::Cancelled,
            SessionError::UpgradeRequired { .. } => Self::UpdateRequired,
            SessionError::EpochState(_) | SessionError::BaseNotActive => Self::NotReady,
            other => Self::Failed(other.code().to_owned()),
        }
    }
}

impl From<ApplyError> for Halt {
    fn from(error: ApplyError) -> Self {
        match error {
            ApplyError::Store(error) => Self::Store(error),
            ApplyError::Stale => Self::Stale,
            other => Self::Failed(other.code().to_owned()),
        }
    }
}

/// What changed locally, for the query invalidations.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Changes {
    /// The confirmed base or the visible projection moved.
    pub records: bool,
    /// Issues opened or changed.
    pub issues: bool,
    /// Queue or sync state changed (a send settled, an epoch registered).
    pub status: bool,
}

impl Changes {
    pub fn any(&self) -> bool {
        self.records || self.issues || self.status
    }

    pub fn merge(&mut self, other: Changes) {
        self.records |= other.records;
        self.issues |= other.issues;
        self.status |= other.status;
    }
}

/// What one pull did.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PullReport {
    pub requests: u32,
    pub transactions: u64,
    pub snapshots: u32,
    /// The budget ran out with the feed not yet drained: pull again at once.
    pub more: bool,
    pub changes: Changes,
    pub halt: Option<Halt>,
}

/// What one round (capabilities, pull, registration, sends) did.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RoundReport {
    pub pull: PullReport,
    pub registered: bool,
    /// `POST commands` made.
    pub sent: u32,
    /// Receipt lookups made.
    pub looked_up: u32,
    /// Commands the server answered terminally.
    pub settled: u32,
    /// Sends are backing off until then (monotonic time).
    pub send_retry_at: Option<Duration>,
    /// More sendable commands than the round's bound.
    pub more_sends: bool,
    pub changes: Changes,
    pub halt: Option<Halt>,
}

// ----------------------------------------------------------------------- the syncer

enum Answer {
    Body(Vec<u8>),
    Lost,
    Retry(Option<Duration>),
    Refused(Box<ErrorBody>),
    Invalid(u16),
}

/// Why a snapshot download stopped.
enum Broke {
    Halt(Halt),
    Apply(ApplyError),
}

impl From<Halt> for Broke {
    fn from(halt: Halt) -> Self {
        Self::Halt(halt)
    }
}

impl From<ApplyError> for Broke {
    fn from(error: ApplyError) -> Self {
        Self::Apply(error)
    }
}

impl From<SessionError> for Broke {
    fn from(error: SessionError) -> Self {
        Self::Halt(error.into())
    }
}

/// Where a paged download stands: the next token and every token seen, so a
/// server that repeats a token, or runs past the manifest's page count, is cut off.
struct Paging {
    next: Option<String>,
    seen: HashSet<String>,
}

impl Paging {
    fn new(first: String) -> Self {
        Self {
            seen: HashSet::from([first.clone()]),
            next: Some(first),
        }
    }

    /// Moves to the page after the one just staged. At most `total` pages exist.
    fn advance(&mut self, next: Option<String>, total: u64) -> Result<(), ApplyError> {
        if let Some(token) = &next
            && (!self.seen.insert(token.clone()) || self.seen.len() as u64 > total)
        {
            return Err(ApplyError::Malformed(
                "page token repeats or exceeds the manifest",
            ));
        }
        self.next = next;
        Ok(())
    }
}

enum Next {
    Refetch,
    Snapshot,
}

/// Drives the session's requests. Single-threaded by design: the owner calls
/// [`Syncer::round`] or [`Syncer::pull`] from its sync worker, never the UI
/// thread, and shares only the `closing` flag with other threads.
pub struct Syncer {
    transport: Box<dyn Transport>,
    session: SyncSession,
    context: Box<dyn Fn() -> ExecuteContext + Send>,
    clock: Arc<dyn Clock>,
    jitter: Box<dyn Jitter>,
    schedule: Schedule,
    closing: Arc<AtomicBool>,
    send_backoff: Backoff,
    attempts: HashMap<CommandId, u32>,
    parked: HashSet<CommandId>,
    held: HashSet<CommandId>,
    capabilities_checked: bool,
    /// A paged transfer or snapshot stopped on the pull budget: where to go on.
    transfer_resume: Option<(Id, Paging)>,
    snapshot_resume: Option<(SnapshotManifest, Paging)>,
}

impl Syncer {
    pub fn new(
        transport: Box<dyn Transport>,
        session: SyncSession,
        context: Box<dyn Fn() -> ExecuteContext + Send>,
        clock: Arc<dyn Clock>,
        jitter: Box<dyn Jitter>,
        schedule: Schedule,
    ) -> Self {
        let send_backoff = Backoff::new(
            schedule.send_backoff_base,
            schedule.send_backoff_cap,
            schedule.retry_after_cap,
        );
        Self {
            transport,
            session,
            context,
            clock,
            jitter,
            schedule,
            closing: Arc::new(AtomicBool::new(false)),
            send_backoff,
            attempts: HashMap::new(),
            parked: HashSet::new(),
            held: HashSet::new(),
            capabilities_checked: false,
            transfer_resume: None,
            snapshot_resume: None,
        }
    }

    /// The flag [`Syncer::close`] raises; the host may hold it to abort calls.
    pub fn closing_flag(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.closing)
    }

    pub fn session_mut(&mut self) -> &mut SyncSession {
        &mut self.session
    }

    pub fn schedule(&self) -> &Schedule {
        &self.schedule
    }

    /// Cancels every call in flight and refuses to start another. Durable work
    /// is untouched; the sent-but-unanswered commands are reconciled later.
    pub fn close(&mut self) {
        self.closing.store(true, Ordering::SeqCst);
        self.session.cancel_requests();
    }

    /// A foreground, network-return or manual wake: parked commands and the send
    /// backoff are forgiven, and the capabilities are checked again.
    pub fn resume(&mut self) {
        self.parked.clear();
        self.held.clear();
        self.attempts.clear();
        self.send_backoff.success();
        self.capabilities_checked = false;
    }

    /// Whether sends are backing off at `now`, and until when.
    pub fn send_backoff_until(&self) -> Option<Duration> {
        let now = self.clock.now();
        (!self.send_backoff.ready(now)).then(|| self.send_backoff.until())
    }

    // ------------------------------------------------------------------- one round

    /// Capabilities (once per resume), a pull, registration of a pending epoch,
    /// then the sends, then one more pull when sends settled so their own feed
    /// transactions are applied without waiting for a hint.
    pub fn round(&mut self, store: &mut Store) -> RoundReport {
        let mut report = RoundReport::default();
        let outcome = self.round_inner(store, &mut report);
        if let Err(halt) = outcome {
            report.halt = Some(halt);
        }
        report
    }

    fn round_inner(&mut self, store: &mut Store, report: &mut RoundReport) -> Result<(), Halt> {
        self.check_capabilities(store)?;
        let pull = self.pull(store);
        let pull_halt = pull.halt.clone();
        report.changes.merge(pull.changes);
        report.pull = pull;
        if let Some(halt) = pull_halt {
            return Err(halt);
        }
        // A registration that cannot complete now is retried next round; only a
        // failure that ends the session's authority stops the round here.
        if let Err(
            halt @ (Halt::AuthRequired | Halt::UpdateRequired | Halt::Cancelled | Halt::Store(_)),
        ) = self.register(store, report)
        {
            return Err(halt);
        }
        let sent = self.send_pending(store, report);
        if report.settled > 0 {
            let again = self.pull(store);
            report.changes.merge(again.changes);
            report.pull.requests += again.requests;
            report.pull.transactions += again.transactions;
            report.pull.more |= again.more;
        }
        sent
    }

    fn check_capabilities(&mut self, store: &mut Store) -> Result<(), Halt> {
        if self.capabilities_checked {
            return Ok(());
        }
        let request = self
            .session
            .begin_request(store, RequestKind::Capabilities)?;
        let path = format!(
            "{API}/capabilities?scope_id={}",
            encode(request.scope_id().as_str())
        );
        let body = self.expect_body(store, &request, Method::Get, path, None)?;
        let capabilities: Capabilities = parse(&body)?;
        match self
            .session
            .check_capabilities(store, &request, &capabilities)
        {
            Ok(CapabilitiesCheck::Supported) => {
                self.capabilities_checked = true;
                Ok(())
            }
            // Not for the base this device holds (e.g. another server generation
            // after a restore): nothing to learn from it. Pull next, which finds
            // the reset; the check repeats on the next round.
            Ok(CapabilitiesCheck::Ignored) => Ok(()),
            Err(error) => Err(error.into()),
        }
    }

    // ---------------------------------------------------------------- registration

    fn register(&mut self, store: &mut Store, report: &mut RoundReport) -> Result<(), Halt> {
        let (request, body) = match self.session.registration(store) {
            Ok(Some(pair)) => pair,
            Ok(None) => return Ok(()),
            Err(error) => return Err(error.into()),
        };
        let bytes = serde_json::to_vec(&body).map_err(|_| Halt::Failed("ENCODE".to_owned()))?;
        let answer = self.expect_body(
            store,
            &request,
            Method::Post,
            format!("{API}/devices"),
            Some(bytes),
        )?;
        let registration: DeviceRegistration = parse(&answer)?;
        let fence = request.live_fence()?;
        let registered = apply_registration(store, fence, &registration)?;
        if registered.newly_active {
            report.registered = true;
            report.changes.status = true;
        }
        Ok(())
    }

    // ------------------------------------------------------------------------ pull

    /// Pulls the feed until it is drained or the budget is spent; rebuilds from a
    /// snapshot when the feed cannot continue. Every page is applied in one
    /// transaction by [`apply_changes`].
    pub fn pull(&mut self, store: &mut Store) -> PullReport {
        let mut report = PullReport::default();
        if let Err(halt) = self.pull_inner(store, &mut report) {
            report.halt = Some(halt);
        }
        report
    }

    fn pull_inner(&mut self, store: &mut Store, report: &mut PullReport) -> Result<(), Halt> {
        let started = self.clock.now();
        let (mut refetches, mut resets) = (0u32, 0u32);
        loop {
            if self.out_of_budget(started, report) {
                report.more = true;
                return Ok(());
            }
            let request = self.session.begin_request(store, RequestKind::Pull)?;
            let Some(cursor) = read_cursor(store)? else {
                bump(&mut resets, "SNAPSHOT_REQUIRED")?;
                if self.recover_snapshot(store, report, started)? {
                    report.more = true;
                    return Ok(());
                }
                continue;
            };
            let path = format!(
                "{API}/changes?scope_id={}&cursor={}&limit={}",
                encode(request.scope_id().as_str()),
                encode(&cursor),
                self.schedule.page_limit
            );
            let answer = self.exchange(&request, Method::Get, path, None)?;
            report.requests += 1;
            let body = match answer {
                Answer::Body(body) => body,
                other => match self.halt_for(store, &request, other) {
                    Halt::ResetRequired => {
                        bump(&mut resets, "RESET_REQUIRED")?;
                        if self.recover_snapshot(store, report, started)? {
                            report.more = true;
                            return Ok(());
                        }
                        continue;
                    }
                    halt => return Err(halt),
                },
            };
            let page: ChangesPage = parse(&body)?;
            let context = (self.context)();
            let fence = request.live_fence()?.clone();
            let step = apply_changes(store, &context, &fence, &page);
            let applied = match step {
                Ok(FeedStep::Applied(applied)) => Ok(Some(applied)),
                Ok(FeedStep::Transfer(transfer_id)) => {
                    self.apply_oversized(store, &request, &page, &transfer_id, started, report)
                }
                Err(error) => Err(Broke::Apply(error)),
            };
            let error = match applied {
                Ok(Some(applied)) => {
                    note(report, &applied);
                    if !applied.has_more {
                        return Ok(());
                    }
                    continue;
                }
                // The budget ran out inside the transfer; it resumes next pull.
                Ok(None) => {
                    report.more = true;
                    return Ok(());
                }
                // The server refused a transfer page: same meaning as anywhere else.
                Err(Broke::Halt(Halt::ResetRequired)) => {
                    bump(&mut resets, "RESET_REQUIRED")?;
                    if self.recover_snapshot(store, report, started)? {
                        report.more = true;
                        return Ok(());
                    }
                    continue;
                }
                Err(Broke::Halt(halt)) => return Err(halt),
                Err(Broke::Apply(error)) => error,
            };
            match self.recover_feed(store, error, &mut refetches, &mut resets)? {
                Next::Refetch => {}
                Next::Snapshot => {
                    if self.recover_snapshot(store, report, started)? {
                        report.more = true;
                        return Ok(());
                    }
                }
            }
        }
    }

    /// The pull's time budget or its request bound is spent.
    fn out_of_budget(&self, started: Duration, report: &PullReport) -> bool {
        self.clock.now().saturating_sub(started) >= self.schedule.pull_budget
            || report.requests >= self.schedule.max_pages_per_pull
    }

    /// Fetches and stages the byte pages of an oversized transaction, then applies
    /// it. `Ok(None)`: the budget ran out; the next pull goes on from the saved token.
    fn apply_oversized(
        &mut self,
        store: &mut Store,
        request: &Request,
        page: &ChangesPage,
        transfer_id: &Id,
        started: Duration,
        report: &mut PullReport,
    ) -> Result<Option<crate::apply_changes::Applied>, Broke> {
        let Some(manifest) = page.transaction_manifest.as_ref() else {
            return Err(ApplyError::Malformed("transfer without a manifest").into());
        };
        let mut paging = match self.transfer_resume.take() {
            Some((id, paging)) if id == *transfer_id => paging,
            _ => Paging::new(manifest.first_page_token.clone()),
        };
        while let Some(current) = paging.next.clone() {
            if self.out_of_budget(started, report) {
                self.transfer_resume = Some((transfer_id.clone(), paging));
                return Ok(None);
            }
            let path = format!(
                "{API}/transactions/{}?page_token={}",
                encode(transfer_id.as_str()),
                encode(&current)
            );
            let body = match self.exchange(request, Method::Get, path, None)? {
                Answer::Body(body) => body,
                other => return Err(self.halt_for(store, request, other).into()),
            };
            report.requests += 1;
            let transfer: TransferPage = decode_apply(&body)?;
            let context = (self.context)();
            let fence = request.live_fence().map_err(|_| ApplyError::Stale)?.clone();
            stage_transfer_page(store, &context, &fence, &transfer)?;
            paging.advance(transfer.page.next_page_token.clone(), manifest.page_count)?;
        }
        let context = (self.context)();
        let fence = request.live_fence().map_err(|_| ApplyError::Stale)?.clone();
        Ok(Some(apply_transfer(store, &context, &fence, transfer_id)?))
    }

    fn recover_feed(
        &mut self,
        store: &mut Store,
        error: ApplyError,
        refetches: &mut u32,
        resets: &mut u32,
    ) -> Result<Next, Halt> {
        match error.recovery() {
            Some(Recovery::Refetch) => {
                *refetches += 1;
                if *refetches > 2 {
                    return Err(Halt::Failed(error.code().to_owned()));
                }
                Ok(Next::Refetch)
            }
            Some(Recovery::Snapshot) => {
                bump(resets, error.code())?;
                // `NoBase` needs a first snapshot, not a reset; anything else
                // fences the requests of the feed that failed.
                self.session.recover(store, &error)?;
                Ok(Next::Snapshot)
            }
            None => Err(error.into()),
        }
    }

    // -------------------------------------------------------------------- snapshot

    /// Rebuilds the base from a snapshot. `Ok(true)`: the budget ran out; the
    /// download goes on at its saved token next pull.
    fn recover_snapshot(
        &mut self,
        store: &mut Store,
        report: &mut PullReport,
        started: Duration,
    ) -> Result<bool, Halt> {
        for attempt in 0..2 {
            match self.snapshot_once(store, report, started) {
                Ok(paused) => return Ok(paused),
                Err(Broke::Apply(ApplyError::Transfer(
                    TransferFault::Expired | TransferFault::Corrupt | TransferFault::Conflict,
                ))) if attempt == 0 => {}
                // The device already holds a newer base: just pull the feed.
                Err(Broke::Apply(ApplyError::Gap { .. })) => return Ok(false),
                Err(Broke::Apply(error)) => return Err(error.into()),
                Err(Broke::Halt(halt)) => return Err(halt),
            }
        }
        Err(Halt::Failed("SNAPSHOT_INVALID".to_owned()))
    }

    fn snapshot_once(
        &mut self,
        store: &mut Store,
        report: &mut PullReport,
        started: Duration,
    ) -> Result<bool, Broke> {
        let request = self.session.begin_request(store, RequestKind::Pull)?;
        let (manifest, mut paging) = match self.snapshot_resume.take() {
            Some(saved) => saved,
            None => {
                let create = serde_json::to_vec(&json!({
                    "scope_id": request.scope_id().as_str(),
                    "projection_schema_version": 1,
                }))
                .map_err(|_| Halt::Failed("ENCODE".to_owned()))?;
                let body = self.expect_body(
                    store,
                    &request,
                    Method::Post,
                    format!("{API}/snapshots"),
                    Some(create),
                )?;
                report.requests += 1;
                let manifest: SnapshotManifest = parse(&body)?;
                let paging = Paging::new(manifest.first_page_token.clone());
                (manifest, paging)
            }
        };
        let context = (self.context)();
        let fence = request.live_fence()?.clone();
        // Announcing again is idempotent: it reports how far the staging has come.
        begin_snapshot(store, &context, &fence, &manifest)?;
        while let Some(current) = paging.next.clone() {
            if self.out_of_budget(started, report) {
                self.snapshot_resume = Some((manifest, paging));
                return Ok(true);
            }
            let path = format!(
                "{API}/snapshots/{}?scope_id={}&page_token={}",
                encode(manifest.snapshot_id.as_str()),
                encode(request.scope_id().as_str()),
                encode(&current)
            );
            let body = self.expect_body(store, &request, Method::Get, path, None)?;
            report.requests += 1;
            let page: SnapshotPage = parse(&body)?;
            let context = (self.context)();
            let fence = request.live_fence()?.clone();
            stage_snapshot_page(store, &context, &fence, &page)?;
            paging.advance(page.page.next_page_token.clone(), manifest.page_count)?;
        }
        let context = (self.context)();
        let fence = request.live_fence()?.clone();
        // Commands with no verdict stay `unknown`; the send side looks each up.
        activate_snapshot(store, &context, &fence, &manifest.snapshot_id)?;
        report.snapshots += 1;
        report.changes.records = true;
        report.changes.status = true;
        Ok(false)
    }

    // ----------------------------------------------------------------------- sends

    fn send_pending(&mut self, store: &mut Store, report: &mut RoundReport) -> Result<(), Halt> {
        let now = self.clock.now();
        if !self.send_backoff.ready(now) {
            report.send_retry_at = Some(self.send_backoff.until());
            return Ok(());
        }
        let mut touched: HashSet<CommandId> = HashSet::new();
        let mut stuck: Option<Halt> = None;
        for _ in 0..self.schedule.max_sends_per_round {
            let Some(next) = self.next_command(store, &touched)? else {
                return stuck.map_or(Ok(()), Err);
            };
            touched.insert(next.id.clone());
            match self.attempt(store, &next, report) {
                Ok(()) => {
                    self.send_backoff.success();
                    self.attempts.remove(&next.id);
                }
                Err(halt @ (Halt::Offline | Halt::Retry { .. })) => {
                    let after = match &halt {
                        Halt::Retry { after } => *after,
                        _ => None,
                    };
                    let now = self.clock.now();
                    let delay = self.send_backoff.failure(now, after, self.jitter.as_mut());
                    report.send_retry_at = Some(now + delay);
                    let attempts = self.attempts.entry(next.id.clone()).or_insert(0);
                    *attempts += 1;
                    if *attempts >= self.schedule.max_send_attempts {
                        self.parked.insert(next.id);
                    }
                    return Err(halt);
                }
                Err(Halt::NotReady) => {
                    self.held.insert(next.id);
                }
                // A refusal that is neither a verdict nor retryable leaves the
                // command `unknown` (kept, never rekeyed). It must not hold up
                // independent commands: only its dependants wait, because they
                // need it completed. It is skipped until the next wake.
                Err(Halt::Failed(code)) => {
                    self.held.insert(next.id);
                    stuck.get_or_insert(Halt::Failed(code));
                }
                Err(halt) => return Err(halt),
            }
        }
        report.more_sends = self.next_command(store, &touched)?.is_some();
        stuck.map_or(Ok(()), Err)
    }

    /// The next command to work on: a possibly-sent one first (its outcome is
    /// read before anything is resent), then the first sendable queued one.
    fn next_command(
        &mut self,
        store: &mut Store,
        touched: &HashSet<CommandId>,
    ) -> Result<Option<Work>, Halt> {
        let skip = |id: &CommandId| {
            touched.contains(id) || self.parked.contains(id) || self.held.contains(id)
        };
        let unresolved = unresolved_sends(store)?;
        if let Some(id) = unresolved.into_iter().find(|id| !skip(id)) {
            return Ok(Some(Work {
                id,
                unresolved: true,
            }));
        }
        let candidates = send_candidates(store)?;
        Ok(candidates.into_iter().find(|id| !skip(id)).map(|id| Work {
            id,
            unresolved: false,
        }))
    }

    fn attempt(
        &mut self,
        store: &mut Store,
        work: &Work,
        report: &mut RoundReport,
    ) -> Result<(), Halt> {
        if work.unresolved {
            match self.lookup(store, &work.id, report)? {
                Looked::Settled(_) => return Ok(()),
                Looked::Pending(_) => return Err(Halt::Retry { after: None }),
                // No record at lookup time is not proof it never commits: the
                // same immutable envelope goes again and the server dedupes.
                Looked::NotFound(_) => {}
            }
        }
        self.post(store, &work.id, report)
    }

    fn lookup(
        &mut self,
        store: &mut Store,
        id: &CommandId,
        report: &mut RoundReport,
    ) -> Result<Looked, Halt> {
        let request = self.session.begin_request(store, RequestKind::Lookup)?;
        let path = format!(
            "{API}/commands/{}?scope_id={}",
            encode(id.as_str()),
            encode(request.scope_id().as_str())
        );
        let body = self.expect_body(store, &request, Method::Get, path, None)?;
        report.looked_up += 1;
        let lookup: CommandLookup = parse(&body)?;
        let context = (self.context)();
        let looked = apply_lookup(store, &context, request.live_fence()?, &lookup)?;
        if let Looked::Settled(settled) = &looked {
            self.settled(settled.settlement, report);
        }
        Ok(looked)
    }

    fn post(
        &mut self,
        store: &mut Store,
        id: &CommandId,
        report: &mut RoundReport,
    ) -> Result<(), Halt> {
        let request = self.session.begin_request(store, RequestKind::Send)?;
        let Some((envelope, epoch)) = load_envelope(store, id)? else {
            return Err(Halt::Stale);
        };
        // Only envelopes stamped with the registered epoch may be sent.
        if request.epoch().map(Id::as_str) != Some(epoch.as_str()) {
            return Err(Halt::NotReady);
        }
        let context = (self.context)();
        mark_sending(store, &request, id, &context)?;
        let path = format!("{API}/commands");
        let outcome = self
            .exchange(&request, Method::Post, path, Some(envelope))
            .and_then(|answer| match answer {
                Answer::Body(body) => Ok(body),
                other => Err(self.halt_for(store, &request, other)),
            });
        report.sent += 1;
        // The server refused the request itself (`INVALID_REQUEST`, too large): it
        // wrote no receipt and executed nothing, and the same bytes will be refused
        // again. That is a terminal verdict, not an unknown outcome.
        if let Err(Halt::Failed(code)) = &outcome
            && let Some(reason) = request_refusal(code)
        {
            return self.reject_refused(store, &request, id, &context, &reason, report);
        }
        let result = outcome.and_then(|body| {
            let receipt: Receipt = parse(&body)?;
            if receipt.command_id != *id {
                return Err(Halt::Failed("INVALID_RESPONSE".to_owned()));
            }
            // A retryable error is not a verdict: the command goes again.
            if receipt.error.as_ref().is_some_and(|error| error.retryable) {
                return Err(Halt::Retry { after: None });
            }
            let settled = apply_receipt(store, &context, request.live_fence()?, &receipt)?;
            self.settled(settled.settlement, report);
            Ok(())
        });
        if result.is_err() {
            // The answer never counted. `ever_sent` is one-way by design, so even a
            // refusal leaves the command as possibly sent: it is looked up, and
            // never rekeyed, until the server's verdict is known.
            mark_unknown(store, id)?;
        }
        result
    }

    /// Settles a command the server refused as a request: it becomes `rejected`
    /// with an open issue that keeps its intent and text, its dependants are
    /// held, and it is never sent again (sync-v1 section 11: `INVALID_REQUEST`
    /// and `COMMAND_TOO_LARGE` never partially execute). Independent commands go on.
    fn reject_refused(
        &mut self,
        store: &mut Store,
        request: &Request,
        id: &CommandId,
        context: &ExecuteContext,
        reason: &IssueReason,
        report: &mut RoundReport,
    ) -> Result<(), Halt> {
        let fence = request.live_fence()?.clone();
        let rejected = store.try_write(|tx| {
            if fence_in(tx)? != fence {
                return Ok::<_, ReplayError>(false);
            }
            record_rejection_in(tx, context, id, reason).map(|_| true)
        });
        match rejected {
            Ok(true) => {
                self.settled(Settlement::Rejected, report);
                Ok(())
            }
            Ok(false) => {
                mark_unknown(store, id)?;
                Err(Halt::Stale)
            }
            Err(error) => {
                mark_unknown(store, id)?;
                Err(Halt::Failed(error.code().to_owned()))
            }
        }
    }

    fn settled(&self, settlement: Settlement, report: &mut RoundReport) {
        report.settled += 1;
        report.changes.status = true;
        report.changes.records = true;
        if settlement == Settlement::Rejected {
            report.changes.issues = true;
        }
    }

    // ------------------------------------------------------------------- exchanges

    /// One exchange whose only good answer is a 2xx body.
    fn expect_body(
        &mut self,
        store: &mut Store,
        request: &Request,
        method: Method,
        path: String,
        body: Option<Vec<u8>>,
    ) -> Result<Vec<u8>, Halt> {
        match self.exchange(request, method, path, body)? {
            Answer::Body(body) => Ok(body),
            other => Err(self.halt_for(store, request, other)),
        }
    }

    fn exchange(
        &mut self,
        request: &Request,
        method: Method,
        path: String,
        body: Option<Vec<u8>>,
    ) -> Result<Answer, Halt> {
        if request.is_cancelled() || self.closing.load(Ordering::SeqCst) {
            return Err(Halt::Cancelled);
        }
        let http = HttpRequest {
            method,
            path,
            body,
            timeout: self.schedule.request_timeout,
        };
        let cancel = Cancellation {
            request: request.cancellation(),
            closing: &self.closing,
        };
        match self.transport.send(&http, &cancel) {
            Err(TransportFailure::Cancelled) => Err(Halt::Cancelled),
            Err(TransportFailure::Timeout | TransportFailure::Connection) => Ok(Answer::Lost),
            Ok(response) if (200..300).contains(&response.status) => {
                Ok(Answer::Body(response.body))
            }
            Ok(response) => Ok(refusal(&response)),
        }
    }

    /// What a non-body answer means for the session and the caller.
    fn halt_for(&mut self, store: &mut Store, request: &Request, answer: Answer) -> Halt {
        match answer {
            Answer::Body(_) => Halt::Failed("INVALID_RESPONSE".to_owned()),
            Answer::Lost => Halt::Offline,
            Answer::Retry(after) => Halt::Retry { after },
            Answer::Invalid(status) => Halt::Failed(format!("HTTP_{status}")),
            Answer::Refused(error) => match self.session.handle_error(store, request, &error) {
                Err(error) => error.into(),
                Ok(ErrorAction::Ignored) => Halt::Stale,
                Ok(ErrorAction::Paused) => Halt::AuthRequired,
                Ok(ErrorAction::UpdateRequired) => Halt::UpdateRequired,
                Ok(ErrorAction::Recovered { fence: Some(_), .. }) => Halt::ResetRequired,
                Ok(ErrorAction::Recovered { fence: None, .. }) => Halt::EpochClosed,
                Ok(ErrorAction::Unchanged) if error.error.retryable => Halt::Retry {
                    after: error
                        .error
                        .details
                        .retry_after_seconds
                        .map(Duration::from_secs),
                },
                Ok(ErrorAction::Unchanged) => Halt::Failed(error.error.code.clone()),
            },
        }
    }
}

fn note(report: &mut PullReport, applied: &crate::apply_changes::Applied) {
    report.transactions += applied.transactions;
    if applied.transactions > 0 {
        report.changes.records = true;
    }
    if let Some(replayed) = &applied.replayed {
        report.changes.issues |= !replayed.rejected.is_empty() || !replayed.blocked.is_empty();
    }
    report.changes.status |= !applied.completed.is_empty();
}

struct Work {
    id: CommandId,
    unresolved: bool,
}

/// Classifies a non-2xx answer.
fn refusal(response: &HttpResponse) -> Answer {
    let body = std::str::from_utf8(&response.body)
        .ok()
        .and_then(|text| decode::<ErrorBody>(text).ok());
    let retryable_status = response.status == 429 || response.status >= 500;
    match body {
        Some(error) if retryable_status && error.error.retryable => Answer::Retry(
            response.retry_after.or(error
                .error
                .details
                .retry_after_seconds
                .map(Duration::from_secs)),
        ),
        Some(error) => Answer::Refused(Box::new(error)),
        None if response.status == 401 => Answer::Refused(Box::new(local_error("AUTH_REQUIRED"))),
        None if retryable_status => Answer::Retry(response.retry_after),
        None => Answer::Invalid(response.status),
    }
}

/// The issue reason when a send was refused as a request the server will never
/// accept: a structured `INVALID_REQUEST`/`COMMAND_TOO_LARGE` error, or a bare
/// 400/413/422 whose body is not the error envelope.
fn request_refusal(code: &str) -> Option<IssueReason> {
    match code {
        "INVALID_REQUEST" | "HTTP_400" | "HTTP_422" => {
            Some(IssueReason::Validation("INVALID_REQUEST".to_owned()))
        }
        "COMMAND_TOO_LARGE" | "HTTP_413" => {
            Some(IssueReason::Validation("COMMAND_TOO_LARGE".to_owned()))
        }
        _ => None,
    }
}

fn local_error(code: &str) -> ErrorBody {
    let json = json!({
        "error": {"code": code, "retryable": false, "message": "local", "details": {}},
        "correlation_id": "local",
    });
    decode(&json.to_string()).expect("a well-formed local error")
}

/// Counts a recovery; a feed that keeps needing one is failing, not recovering.
fn bump(resets: &mut u32, code: &str) -> Result<(), Halt> {
    *resets += 1;
    if *resets > 2 {
        return Err(Halt::Failed(code.to_owned()));
    }
    Ok(())
}

fn parse<T: Wire>(body: &[u8]) -> Result<T, Halt> {
    std::str::from_utf8(body)
        .ok()
        .and_then(|text| decode::<T>(text).ok())
        .ok_or_else(|| Halt::Failed("INVALID_RESPONSE".to_owned()))
}

fn decode_apply<T: Wire>(body: &[u8]) -> Result<T, ApplyError> {
    std::str::from_utf8(body)
        .ok()
        .and_then(|text| decode::<T>(text).ok())
        .ok_or(ApplyError::Malformed("response"))
}

/// Percent-encodes everything but RFC 3986 unreserved characters.
pub fn encode(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~') {
            out.push(char::from(byte));
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    out
}

// ------------------------------------------------------------------- store access

fn read_cursor(store: &mut Store) -> Result<Option<String>, StoreError> {
    store.read(|tx| tx.query_row("SELECT cursor FROM sync_meta", [], |row| row.get(0)))
}

/// Commands that may have reached the server and have no verdict, in send order.
fn unresolved_sends(store: &mut Store) -> Result<Vec<CommandId>, StoreError> {
    store.read(|tx| {
        let mut statement = tx.prepare(
            "SELECT command_id FROM outbox
             WHERE workspace_id = (SELECT workspace_id FROM sync_meta)
               AND state IN ('sending', 'unknown') AND ever_sent = 1
             ORDER BY local_seq",
        )?;
        let rows = statement.query_map([], |row| row.get::<_, String>(0))?;
        let mut ids = Vec::new();
        for row in rows {
            ids.push(CommandId::parse(row?).map_err(|_| rusqlite::Error::InvalidQuery)?);
        }
        Ok(ids)
    })
}

/// The immutable envelope bytes and the epoch they are stamped with.
fn load_envelope(
    store: &mut Store,
    id: &CommandId,
) -> Result<Option<(Vec<u8>, String)>, StoreError> {
    store.read(|tx| {
        let mut statement = tx.prepare(
            "SELECT envelope, device_epoch FROM outbox
             WHERE workspace_id = (SELECT workspace_id FROM sync_meta) AND command_id = ?1",
        )?;
        let mut rows = statement.query([id.as_str()])?;
        match rows.next()? {
            Some(row) => Ok(Some((row.get(0)?, row.get(1)?))),
            None => Ok(None),
        }
    })
}

/// Durably marks the command `sending` **before** the call, in a transaction
/// that re-checks the request's fence: a crash or a lost answer afterwards
/// leaves a command that may have been sent, never one the store thinks was not.
fn mark_sending(
    store: &mut Store,
    request: &Request,
    id: &CommandId,
    context: &ExecuteContext,
) -> Result<(), Halt> {
    store.try_write(|tx| {
        if fence_in(tx)? != *request.fence() {
            return Err(Halt::Stale);
        }
        let changed = tx.execute(
            "UPDATE outbox SET state = 'sending', ever_sent = 1, attempts = attempts + 1,
                    first_sent_at = COALESCE(first_sent_at, ?2), last_attempt_at = ?2
             WHERE workspace_id = (SELECT workspace_id FROM sync_meta) AND command_id = ?1
               AND state IN ('queued', 'sending', 'unknown')",
            rusqlite::params![id.as_str(), context.now.as_str()],
        )?;
        if changed == 0 {
            return Err(Halt::Stale);
        }
        Ok(())
    })
}

impl From<rusqlite::Error> for Halt {
    fn from(error: rusqlite::Error) -> Self {
        Self::Store(error.into())
    }
}

/// A send whose answer did not count: the server may have committed it.
fn mark_unknown(store: &mut Store, id: &CommandId) -> Result<(), StoreError> {
    store.write(|tx| {
        tx.execute(
            "UPDATE outbox SET state = 'unknown'
             WHERE workspace_id = (SELECT workspace_id FROM sync_meta) AND command_id = ?1
               AND state = 'sending'",
            [id.as_str()],
        )?;
        Ok(())
    })
}
