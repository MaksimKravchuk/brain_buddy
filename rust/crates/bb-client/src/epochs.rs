//! The device intake epoch (sync-v1 sections 5 and 11).
//!
//! An epoch is the durable queue generation every new command is stamped with.
//! It is a barrier, not a credential: its local existence grants no server
//! authority. Its life, all in `sync_meta`:
//!
//! * `pending_registration`: allocated by [`crate::execute`] in the same
//!   transaction as the first new command, and reused by every later gesture, the
//!   widget and app restarts until the server confirms it;
//! * `active`: [`apply_registration`] saw the server confirm **that same ID** for
//!   this scope, device and server generation. Registration is idempotent (a lost
//!   ACK is retried with the same ID) and never reopens a closed epoch;
//! * `closed`: the server explicitly invalidated it ([`close_epoch`]). Closing
//!   writes one flag. Every envelope of the epoch stays exactly as it was
//!   (immutable, never rekeyed or copied): the ones that may have reached the
//!   server are looked up, the others are held. The next genuinely new gesture
//!   allocates a fresh `pending_registration` epoch atomically with itself.
//!
//! An ordinary reset does not touch the epoch; see [`crate::sync_session`].

use crate::apply_changes::{ApplyError, Fence, check_common, read_base};
use crate::storage::{Store, StoreError};
use bb_protocol::capabilities::DeviceRegistration;
use bb_protocol::wire::{CommandId, Id, Wire};
use rusqlite::{Transaction, params};

/// Where the current epoch stands.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EpochState {
    /// No command has been saved yet.
    None,
    PendingRegistration,
    Active,
    Closed,
}

impl EpochState {
    fn parse(text: &str) -> Result<Self, StoreError> {
        Ok(match text {
            "none" => Self::None,
            "pending_registration" => Self::PendingRegistration,
            "active" => Self::Active,
            "closed" => Self::Closed,
            _ => return Err(StoreError::Corrupt),
        })
    }
}

/// The epoch new gestures are stamped with, and its state.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EpochView {
    pub epoch: Option<Id>,
    pub state: EpochState,
}

pub(crate) fn view_in(tx: &Transaction<'_>) -> Result<EpochView, StoreError> {
    let (epoch, state): (Option<String>, String) = tx.query_row(
        "SELECT device_epoch, device_epoch_state FROM sync_meta",
        [],
        |row| Ok((row.get(0)?, row.get(1)?)),
    )?;
    Ok(EpochView {
        epoch: epoch
            .map(Id::parse)
            .transpose()
            .map_err(|_| StoreError::Corrupt)?,
        state: EpochState::parse(&state)?,
    })
}

/// The current epoch and its state.
///
/// # Errors
///
/// [`StoreError`] when the store cannot be read.
pub fn epoch_view(store: &mut Store) -> Result<EpochView, StoreError> {
    store.read(|tx| Ok(view_in(tx)))?
}

/// What applying a registration ACK did.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Registered {
    pub epoch: Id,
    /// False when the epoch was already active: a retry after a lost ACK.
    pub newly_active: bool,
}

/// Applies the ACK of `POST devices`. It is fenced like every response, must name
/// this device's **current** epoch, and activates it; the same ACK again changes
/// nothing, and a closed epoch is never reopened.
///
/// # Errors
///
/// [`ApplyError::Stale`] for an ACK issued before a reset, a restore or a sign-out
/// and for one naming an epoch that has since been replaced;
/// [`ApplyError::WrongScope`] / [`ApplyError::GenerationChanged`] for another
/// account's or another generation's; nothing is saved.
pub fn apply_registration(
    store: &mut Store,
    fence: &Fence,
    registration: &DeviceRegistration,
) -> Result<Registered, ApplyError> {
    store.try_write(|tx| {
        let base = read_base(tx, fence)?;
        check_common(&base, &registration.common)?;
        registration
            .validate()
            .map_err(|_| ApplyError::Malformed("registration"))?;
        let (device, epoch, state): (Option<String>, Option<String>, String) = tx.query_row(
            "SELECT device_id, device_epoch, device_epoch_state FROM sync_meta",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )?;
        if device.as_deref() != Some(registration.device_id.as_str()) {
            return Err(ApplyError::Contradiction("registration for another device"));
        }
        if epoch.as_deref() != Some(registration.device_epoch.as_str()) {
            return Err(ApplyError::Stale); // an epoch since replaced
        }
        let registered = |newly_active| Registered {
            epoch: registration.device_epoch.clone(),
            newly_active,
        };
        match EpochState::parse(&state)? {
            EpochState::PendingRegistration => {
                tx.execute("UPDATE sync_meta SET device_epoch_state = 'active'", [])?;
                Ok(registered(true))
            }
            EpochState::Active => Ok(registered(false)),
            EpochState::Closed | EpochState::None => Err(ApplyError::Contradiction(
                "registration of an epoch that is closed",
            )),
        }
    })
}

/// What closing an epoch left behind. Nothing here was rewritten.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Closure {
    /// This call closed the epoch (false: it was closed already, or another).
    pub closed: bool,
    /// Commands of the epoch that may have reached the server: look each one up,
    /// never resend one under a new ID.
    pub lookups: Vec<CommandId>,
    /// Commands of the epoch the server never saw. Their envelope names the
    /// closed epoch and the server will not run them: they stay queued, with
    /// their dependants held, until the user resolves them explicitly.
    pub held: Vec<CommandId>,
}

/// Closes `epoch` on the server's explicit word (`EPOCH_CLOSED`). See the module
/// documentation.
///
/// # Errors
///
/// [`ApplyError::Stale`] for a request issued before a reset or sign-out.
pub fn close_epoch(store: &mut Store, fence: &Fence, epoch: &Id) -> Result<Closure, ApplyError> {
    store.try_write(|tx| {
        read_base(tx, fence)?;
        Ok(close_in(tx, Some(epoch.as_str()))?)
    })
}

/// Closes `named` (or, without one, the current epoch) when it is the current
/// one and not closed yet, and reports what it leaves.
pub(crate) fn close_in(tx: &Transaction<'_>, named: Option<&str>) -> Result<Closure, StoreError> {
    let current = view_in(tx)?;
    let epoch = match (named, &current.epoch) {
        (Some(named), _) => named.to_owned(),
        (None, Some(current)) => current.as_str().to_owned(),
        (None, None) => {
            return Ok(Closure {
                closed: false,
                lookups: Vec::new(),
                held: Vec::new(),
            });
        }
    };
    let closes = current.epoch.as_ref().map(Id::as_str) == Some(epoch.as_str())
        && matches!(
            current.state,
            EpochState::PendingRegistration | EpochState::Active
        );
    if closes {
        tx.execute("UPDATE sync_meta SET device_epoch_state = 'closed'", [])?;
    }
    let commands = |sent: i64| -> Result<Vec<CommandId>, StoreError> {
        let mut statement = tx.prepare(
            "SELECT command_id FROM outbox
             WHERE device_epoch = ?1 AND ever_sent = ?2
               AND state IN ('queued', 'sending', 'unknown', 'blocked_dependency')
             ORDER BY local_seq",
        )?;
        let rows = statement.query_map(params![epoch, sent], |row| row.get::<_, String>(0))?;
        let mut ids = Vec::new();
        for row in rows {
            ids.push(CommandId::parse(row?).map_err(|_| StoreError::Corrupt)?);
        }
        Ok(ids)
    };
    Ok(Closure {
        closed: closes,
        lookups: commands(1)?,
        held: commands(0)?,
    })
}

/// The queued commands that may be sent now, in send order: the current epoch is
/// registered, and every command they depend on is settled by the server
/// (`completed`, or accepted and waiting for its feed transaction). A command of
/// a closed epoch is never a candidate and neither is anything built on one that
/// is unresolved, while independent new work is. Retrying a command that may have
/// been sent starts with a lookup, not here.
///
/// # Errors
///
/// [`StoreError`] when the store cannot be read.
pub fn send_candidates(store: &mut Store) -> Result<Vec<CommandId>, StoreError> {
    store.read(|tx| {
        let mut statement = tx.prepare(
            "SELECT o.command_id FROM outbox o JOIN sync_meta m
               ON m.workspace_id = o.workspace_id
              AND m.device_epoch_state = 'active' AND m.device_epoch = o.device_epoch
             WHERE o.state = 'queued'
               AND NOT EXISTS (
                 SELECT 1 FROM outbox_dependencies d JOIN outbox p
                   ON p.workspace_id = d.workspace_id AND p.command_id = d.depends_on
                 WHERE d.workspace_id = o.workspace_id AND d.command_id = o.command_id
                   AND p.state NOT IN ('completed', 'accepted_awaiting_feed'))
             ORDER BY o.local_seq",
        )?;
        let rows = statement.query_map([], |row| row.get::<_, String>(0))?;
        let mut ids = Vec::new();
        for row in rows {
            ids.push(CommandId::parse(row?).map_err(|_| rusqlite::Error::InvalidQuery)?);
        }
        Ok(ids)
    })
}
