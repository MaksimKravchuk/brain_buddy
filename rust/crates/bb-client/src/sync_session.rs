//! The sync session: who may talk to the server, and which answers still count
//! (sync-v1 sections 5, 7 and 9).
//!
//! **Authority** is a thing of the running process. [`SyncSession::start`] binds
//! the store to an account, scope and device (the scope [`crate::snapshot`]
//! activates against) and hands out a session that [`SyncSession::end`] or a
//! `401` revokes. Nothing durable says "signed in": a restarted process has no
//! authority until the platform authenticates again, so revoked access cannot be
//! resumed by reopening the file. A different account never binds to this store
//! (the app opens another workspace for it) and unsent work is never relabeled.
//!
//! **Generations** are durable, in `sync_meta`, and are what makes a late answer
//! harmless. Every request is a [`Request`] that captured the [`Fence`]
//! (workspace, session, local-sync and server generation) and a cancellation flag
//! when it was issued. Its answer is applied through `request.live_fence()`, and
//! each apply function re-checks that fence **inside** its own write
//! transaction, so a reset, a restore or a sign-out that committed in between,
//! even from another process, turns the answer into `STALE_RESPONSE`:
//!
//! * a new authenticated session bumps the session generation, ending one bumps
//!   it, and an account switch bumps the workspace generation too;
//! * [`SyncSession::reset`] bumps the local-sync generation, cancels every request
//!   in flight, drops staged downloads and clears the cursor, so no pull and no
//!   send happens until a snapshot has been activated. Queue, issues and drafts
//!   are untouched;
//! * the server generation is part of the fence, so an ACK issued before a
//!   restore's snapshot is ignored even inside the same session.
//!
//! A [`WireError`](bb_protocol::receipt::WireError) is classified by
//! [`SyncSession::handle_error`]: `RESET_REQUIRED` resets but keeps an active
//! epoch unless the server says the epoch is closed; `EPOCH_CLOSED` closes it;
//! `UPGRADE_REQUIRED` and an unsupported protocol stop sync and write nothing, so
//! the store and the queue stay as they are; `AUTH_REQUIRED` pauses.
//!
//! **Sends** need more than authority ([`RequestKind::Send`]): the account-link
//! choice recorded, an epoch the server confirmed, and a recovery base that has
//! been activated.

use crate::apply_changes::{ApplyError, Fence, Recovery, abandon_in, fence_in, unsigned};
use crate::epochs::{Closure, EpochState, close_in, view_in};
use crate::storage::{Store, StoreError};
use bb_protocol::capabilities::{Capabilities, DeviceRegistrationRequest};
use bb_protocol::receipt::{EpochStatus, ErrorBody};
use bb_protocol::wire::{Id, PROTOCOL_VERSION};
use rusqlite::{Transaction, params};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

/// How the platform got the credentials it starts a session with.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Authentication {
    /// The same still-valid credentials as before (an app relaunch): generations
    /// stay, so a staged snapshot can resume.
    Resumed,
    /// A sign-in or re-authentication: every earlier request is fenced out.
    Fresh,
}

/// Who the platform says is signed in on this device.
#[derive(Clone, Debug)]
pub struct SessionBinding {
    pub account_id: Id,
    pub scope_id: Id,
    pub device_id: Id,
    pub authentication: Authentication,
}

/// Why a session was ended.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EndCause {
    SignOut,
    Revoked,
    /// Another account takes over the device; it gets its own workspace.
    AccountSwitch,
}

/// What a request is for, which decides what it needs.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RequestKind {
    /// Feed, snapshot, transfer and capabilities reads.
    Pull,
    /// `GET commands/{id}`. The only kind allowed while an update is required:
    /// known receipts stay reachable.
    Lookup,
    /// `POST devices` for the pending epoch.
    Register,
    /// `POST commands`.
    Send,
}

/// A request in flight: what it captured when it was issued.
#[derive(Clone, Debug)]
pub struct Request {
    kind: RequestKind,
    fence: Fence,
    scope_id: Id,
    device_id: Id,
    epoch: Option<Id>,
    cancelled: Arc<AtomicBool>,
}

impl Request {
    pub fn kind(&self) -> RequestKind {
        self.kind
    }

    pub fn scope_id(&self) -> &Id {
        &self.scope_id
    }

    pub fn device_id(&self) -> &Id {
        &self.device_id
    }

    /// The epoch a `Register` or `Send` runs under: only envelopes stamped with
    /// it may be sent.
    pub fn epoch(&self) -> Option<&Id> {
        self.epoch.as_ref()
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }

    /// The fence as captured when the request was issued, cancelled or not.
    pub fn fence(&self) -> &Fence {
        &self.fence
    }

    /// The fence to apply the answer with; `Cancelled` once a reset or the end
    /// of the session cancelled the request. The transaction that applies the
    /// answer re-checks the fence either way.
    ///
    /// # Errors
    ///
    /// [`SessionError::Cancelled`].
    pub fn live_fence(&self) -> Result<&Fence, SessionError> {
        if self.is_cancelled() {
            Err(SessionError::Cancelled)
        } else {
            Ok(&self.fence)
        }
    }
}

/// Why the session refused to issue a request, or to change state.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SessionError {
    Store(StoreError),
    /// The account-less workspace has not chosen to link; nothing is bound.
    LinkRequired,
    /// The store belongs to another account or scope.
    AccountMismatch,
    /// The store belongs to another device.
    DeviceMismatch,
    /// No authority: the session ended, was revoked or needs authenticating.
    NotAuthorized,
    /// Another process started a newer session or ended this one.
    Superseded,
    /// The request was cancelled by a reset or the end of the session.
    Cancelled,
    /// A newer build wrote the store, or the server/protocol is newer than this
    /// build: sync stops, nothing is changed or removed.
    UpgradeRequired {
        found: Option<i64>,
    },
    /// The epoch is not in the state this request needs.
    EpochState(EpochState),
    /// No activated recovery base: take a snapshot first.
    BaseNotActive,
}

impl SessionError {
    /// The stable code the bindings carry across FFI.
    pub fn code(&self) -> &'static str {
        match self {
            Self::Store(error) => error.code(),
            Self::LinkRequired => "LINK_REQUIRED",
            Self::AccountMismatch | Self::DeviceMismatch => "WORKSPACE_MISMATCH",
            Self::NotAuthorized | Self::Superseded => "AUTH_REQUIRED",
            Self::Cancelled => "CANCELLED",
            Self::UpgradeRequired { .. } => "UPGRADE_REQUIRED",
            Self::EpochState(_) => "EPOCH_NOT_READY",
            Self::BaseNotActive => "SNAPSHOT_REQUIRED",
        }
    }
}

impl std::fmt::Display for SessionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}

impl std::error::Error for SessionError {}

impl From<StoreError> for SessionError {
    fn from(error: StoreError) -> Self {
        match error {
            StoreError::UpgradeRequired { found } => Self::UpgradeRequired { found: Some(found) },
            other => Self::Store(other),
        }
    }
}

impl From<rusqlite::Error> for SessionError {
    fn from(error: rusqlite::Error) -> Self {
        StoreError::from(error).into()
    }
}

/// What [`SyncSession::handle_error`] did.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ErrorAction {
    /// The request was cancelled or predates a reset, a restore or a sign-out:
    /// its error says nothing about the present.
    Ignored,
    /// A reset and/or an epoch closure was recorded. After a reset, take a
    /// snapshot with the new fence.
    Recovered {
        closure: Option<Closure>,
        fence: Option<Fence>,
    },
    /// Sync is stopped until the app is updated. Nothing was written.
    UpdateRequired,
    /// Authentication is needed; the session no longer has authority.
    Paused,
    /// Nothing to record (rate limit, outage, a domain rejection).
    Unchanged,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Standing {
    Live,
    UpdateRequired,
    Ended,
}

/// The authority of one process to sync one store. See the module documentation.
#[derive(Debug)]
pub struct SyncSession {
    /// The workspace and session generations this session was started under.
    bound: (u64, u64),
    standing: Standing,
    open: Vec<Arc<AtomicBool>>,
}

struct Meta {
    scope_id: Option<String>,
    device_id: Option<String>,
    link_state: String,
    epoch: Option<String>,
    cursor: Option<String>,
}

impl SyncSession {
    /// Binds the store to the signed-in account, scope and device and starts a
    /// session. Binding is once: the same account again resumes, anything else is
    /// refused.
    ///
    /// # Errors
    ///
    /// [`SessionError::UpgradeRequired`] for a store a newer build wrote (read-
    /// only, queue intact); [`SessionError::LinkRequired`] until the explicit
    /// account-link choice is recorded; [`SessionError::AccountMismatch`] /
    /// [`SessionError::DeviceMismatch`] for another owner. Nothing changes.
    pub fn start(store: &mut Store, binding: &SessionBinding) -> Result<Self, SessionError> {
        let bound = store.try_write(|tx| {
            let (account, scope, device, link, workspace, session): (
                Option<String>,
                Option<String>,
                Option<String>,
                String,
                i64,
                i64,
            ) = tx.query_row(
                "SELECT account_id, scope_id, device_id, account_link_state,
                        workspace_generation, session_generation FROM sync_meta",
                [],
                |row| {
                    Ok((
                        row.get(0)?,
                        row.get(1)?,
                        row.get(2)?,
                        row.get(3)?,
                        row.get(4)?,
                        row.get(5)?,
                    ))
                },
            )?;
            if link != "linked" {
                return Err(SessionError::LinkRequired);
            }
            let same = |held: &Option<String>, given: &Id| {
                held.as_deref().is_none_or(|held| held == given.as_str())
            };
            if !same(&account, &binding.account_id) || !same(&scope, &binding.scope_id) {
                return Err(SessionError::AccountMismatch);
            }
            if !same(&device, &binding.device_id) {
                return Err(SessionError::DeviceMismatch);
            }
            let first = scope.is_none();
            let fresh = binding.authentication == Authentication::Fresh;
            let (workspace, session) = (workspace + i64::from(first), session + i64::from(fresh));
            tx.execute(
                "UPDATE sync_meta SET account_id = ?1, scope_id = ?2, device_id = ?3,
                    workspace_generation = ?4, session_generation = ?5",
                params![
                    binding.account_id.as_str(),
                    binding.scope_id.as_str(),
                    binding.device_id.as_str(),
                    workspace,
                    session
                ],
            )?;
            Ok((unsigned(workspace), unsigned(session)))
        })?;
        Ok(Self {
            bound,
            standing: Standing::Live,
            open: Vec::new(),
        })
    }

    /// Issues a request, capturing the fence and the gate its kind needs.
    ///
    /// # Errors
    ///
    /// [`SessionError`]; nothing is written.
    pub fn begin_request(
        &mut self,
        store: &mut Store,
        kind: RequestKind,
    ) -> Result<Request, SessionError> {
        match self.standing {
            Standing::Ended => return Err(SessionError::NotAuthorized),
            Standing::UpdateRequired if kind != RequestKind::Lookup => {
                return Err(SessionError::UpgradeRequired { found: None });
            }
            _ => {}
        }
        let (fence, meta, state) = store.read(|tx| {
            let meta = tx.query_row(
                "SELECT scope_id, device_id, account_link_state, device_epoch, cursor
                 FROM sync_meta",
                [],
                |row| {
                    Ok(Meta {
                        scope_id: row.get(0)?,
                        device_id: row.get(1)?,
                        link_state: row.get(2)?,
                        epoch: row.get(3)?,
                        cursor: row.get(4)?,
                    })
                },
            )?;
            Ok((fence_in(tx)?, meta, view_in(tx)))
        })?;
        if (fence.workspace_generation, fence.session_generation) != self.bound {
            self.drop_authority();
            return Err(SessionError::Superseded);
        }
        let (Some(scope), Some(device)) = (meta.scope_id, meta.device_id) else {
            return Err(SessionError::NotAuthorized);
        };
        if meta.link_state != "linked" {
            return Err(SessionError::LinkRequired);
        }
        let needs_base = matches!(kind, RequestKind::Register | RequestKind::Send);
        if needs_base && (meta.cursor.is_none() || fence.server_generation.is_none()) {
            return Err(SessionError::BaseNotActive);
        }
        let wanted = match kind {
            RequestKind::Register => Some(EpochState::PendingRegistration),
            RequestKind::Send => Some(EpochState::Active),
            _ => None,
        };
        let state = state?.state;
        if wanted.is_some_and(|wanted| wanted != state) {
            return Err(SessionError::EpochState(state));
        }
        let epoch = if wanted.is_some() {
            meta.epoch
                .map(Id::parse)
                .transpose()
                .map_err(|_| StoreError::Corrupt)?
        } else {
            None
        };
        let request = Request {
            kind,
            fence,
            scope_id: Id::parse(scope).map_err(|_| StoreError::Corrupt)?,
            device_id: Id::parse(device).map_err(|_| StoreError::Corrupt)?,
            epoch,
            cancelled: Arc::new(AtomicBool::new(false)),
        };
        self.open.retain(|flag| Arc::strong_count(flag) > 1);
        self.open.push(Arc::clone(&request.cancelled));
        Ok(request)
    }

    /// The registration to send for the pending epoch: the same epoch ID every
    /// time, so a lost ACK is retried unchanged. `None` when there is nothing to
    /// register (no epoch yet, already active, or closed).
    ///
    /// # Errors
    ///
    /// [`SessionError::NotAuthorized`] when access is revoked,
    /// [`SessionError::BaseNotActive`] until a recovery base is activated.
    pub fn registration(
        &mut self,
        store: &mut Store,
    ) -> Result<Option<(Request, DeviceRegistrationRequest)>, SessionError> {
        if self.standing == Standing::Ended {
            return Err(SessionError::NotAuthorized);
        }
        let view = store.read(|tx| Ok(view_in(tx)))??;
        if view.state != EpochState::PendingRegistration {
            return Ok(None);
        }
        let request = self.begin_request(store, RequestKind::Register)?;
        let Some(epoch) = request.epoch.clone() else {
            return Err(StoreError::Corrupt.into());
        };
        let body = DeviceRegistrationRequest {
            scope_id: request.scope_id.clone(),
            device_id: request.device_id.clone(),
            device_epoch: epoch,
            protocol_version: PROTOCOL_VERSION,
        };
        Ok(Some((request, body)))
    }

    /// Invalidates everything in flight and demands a new recovery base: the
    /// local-sync generation advances, requests are cancelled, staged downloads
    /// are dropped and the cursor is cleared. Pending commands, issues and drafts
    /// are untouched, as is an active epoch. Returns the fence to take the
    /// snapshot under.
    ///
    /// # Errors
    ///
    /// [`SessionError`]; nothing changed.
    pub fn reset(&mut self, store: &mut Store) -> Result<Fence, SessionError> {
        self.ensure_standing()?;
        let bound = self.bound;
        let fence = store.try_write(|tx| {
            check_bound(tx, bound)?;
            Ok::<_, SessionError>(reset_in(tx)?)
        })?;
        self.cancel_all();
        Ok(fence)
    }

    /// [`SyncSession::reset`] when an apply error asks for a snapshot (a gap, a
    /// changed server generation, a contradiction); `None` otherwise.
    ///
    /// # Errors
    ///
    /// As [`SyncSession::reset`].
    pub fn recover(
        &mut self,
        store: &mut Store,
        error: &ApplyError,
    ) -> Result<Option<Fence>, SessionError> {
        if error.recovery() == Some(Recovery::Snapshot) && *error != ApplyError::NoBase {
            return self.reset(store).map(Some);
        }
        Ok(None)
    }

    /// Ends the session: access stops, requests are cancelled and answers still
    /// in transit are fenced out. The queue is kept and is never moved to another
    /// owner.
    ///
    /// # Errors
    ///
    /// [`SessionError::Store`]; the session stays unable to send either way.
    pub fn end(&mut self, store: &mut Store, cause: EndCause) -> Result<(), SessionError> {
        self.drop_authority();
        let bound = self.bound;
        store.try_write(|tx| {
            // Someone else already moved the generations: nothing more to fence.
            if check_bound(tx, bound).is_ok() {
                let workspace = i64::from(cause == EndCause::AccountSwitch);
                tx.execute(
                    "UPDATE sync_meta SET session_generation = session_generation + 1,
                        workspace_generation = workspace_generation + ?1",
                    [workspace],
                )?;
                abandon_staging(tx)?;
            }
            Ok::<_, SessionError>(())
        })
    }

    /// Classifies an error answer to `request`. See the module documentation.
    ///
    /// # Errors
    ///
    /// [`SessionError`]; nothing changed.
    pub fn handle_error(
        &mut self,
        store: &mut Store,
        request: &Request,
        error: &ErrorBody,
    ) -> Result<ErrorAction, SessionError> {
        if request.is_cancelled() {
            return Ok(ErrorAction::Ignored);
        }
        let details = &error.error.details;
        let reset = error.error.code == "RESET_REQUIRED";
        match error.error.code.as_str() {
            "RESET_REQUIRED" | "EPOCH_CLOSED" => {
                // A reset that is not an explicit closure keeps the epoch.
                let closing = !reset || details.epoch_status == Some(EpochStatus::Closed);
                let bound = self.bound;
                let done = store.try_write(|tx| {
                    check_bound(tx, bound)?;
                    if fence_in(tx)? != request.fence {
                        return Ok::<_, SessionError>(None);
                    }
                    let named = request.epoch.as_ref().map(Id::as_str);
                    let closure = closing.then(|| close_in(tx, named)).transpose()?;
                    let fence = reset.then(|| reset_in(tx)).transpose()?;
                    Ok(Some((closure, fence)))
                })?;
                let Some((closure, fence)) = done else {
                    return Ok(ErrorAction::Ignored);
                };
                if fence.is_some() {
                    self.cancel_all();
                }
                Ok(ErrorAction::Recovered { closure, fence })
            }
            "UPGRADE_REQUIRED" => {
                if self.standing == Standing::Live {
                    self.standing = Standing::UpdateRequired;
                }
                Ok(ErrorAction::UpdateRequired)
            }
            "AUTH_REQUIRED" => {
                self.drop_authority();
                Ok(ErrorAction::Paused)
            }
            _ => Ok(ErrorAction::Unchanged),
        }
    }

    /// Stops sync when the server does not speak this build's protocol.
    ///
    /// # Errors
    ///
    /// [`SessionError::UpgradeRequired`]; nothing is written.
    pub fn check_capabilities(&mut self, capabilities: &Capabilities) -> Result<(), SessionError> {
        if capabilities.protocol_versions.contains(&PROTOCOL_VERSION) {
            return Ok(());
        }
        if self.standing == Standing::Live {
            self.standing = Standing::UpdateRequired;
        }
        Err(SessionError::UpgradeRequired { found: None })
    }

    fn ensure_standing(&self) -> Result<(), SessionError> {
        match self.standing {
            Standing::Live => Ok(()),
            Standing::UpdateRequired => Err(SessionError::UpgradeRequired { found: None }),
            Standing::Ended => Err(SessionError::NotAuthorized),
        }
    }

    fn drop_authority(&mut self) {
        self.standing = Standing::Ended;
        self.cancel_all();
    }

    fn cancel_all(&mut self) {
        for flag in self.open.drain(..) {
            flag.store(true, Ordering::SeqCst);
        }
    }
}

/// The session is still the one the store was last bound or authenticated for.
fn check_bound(tx: &Transaction<'_>, bound: (u64, u64)) -> Result<(), SessionError> {
    let fence = fence_in(tx)?;
    if (fence.workspace_generation, fence.session_generation) == bound {
        Ok(())
    } else {
        Err(SessionError::Superseded)
    }
}

/// Advances the local-sync generation and demands a snapshot.
fn reset_in(tx: &Transaction<'_>) -> Result<Fence, StoreError> {
    tx.execute(
        "UPDATE sync_meta SET local_sync_generation = local_sync_generation + 1,
            cursor = NULL",
        [],
    )?;
    abandon_staging(tx)?;
    Ok(fence_in(tx)?)
}

/// Drops every download in progress; the active base is never touched.
fn abandon_staging(tx: &Transaction<'_>) -> rusqlite::Result<()> {
    let staged: Vec<(String, String)> = {
        let mut statement = tx.prepare(
            "SELECT workspace_id, activation_id FROM staging_bases
             WHERE state IN ('receiving', 'complete')",
        )?;
        let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
        rows.collect::<Result<_, _>>()?
    };
    for (workspace_id, activation_id) in staged {
        abandon_in(tx, &workspace_id, &activation_id)?;
    }
    Ok(())
}
