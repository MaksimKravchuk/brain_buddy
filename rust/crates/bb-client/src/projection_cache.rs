//! A decoded copy of the visible projection that outlives one transaction.
//!
//! Decoding `visible_records` (JSON per row, validated newtypes) is the largest
//! cost of a gesture or a list query on a 10,000-task store, and it is repeated
//! unchanged by every call. This keeps the last decoded projection on the
//! [`Store`](crate::Store) handle, and reuses it only when it is *provably* what
//! a fresh read would produce:
//!
//! - **Other writers.** `PRAGMA data_version` changes on a connection whenever
//!   any *other* connection (another process, the widget, a second handle in
//!   this process) committed since it last looked. It is read inside the
//!   transaction that wants the cache, so it describes that transaction's
//!   snapshot; a different value discards the cache.
//! - **This handle's own writes.** `sqlite3_total_changes` counts every row this
//!   connection inserted, updated or deleted. The cache is valid only at the
//!   exact count it was built at, so a write that did not refresh it (any other
//!   caller, rolled back or not) discards it. Only [`Txn::stage`], called by the
//!   one writer that keeps the projection current (`execute`), advances it, and
//!   only to the post-state it computed.
//! - **Failures.** The cache is installed only after the owning transaction
//!   committed (or the read finished); an error drops it.
//!
//! In debug builds every reuse is checked against a fresh read, so the whole
//! test suite is an equivalence oracle for the incremental updates.

use crate::execute::{ExecuteError, Visible, load_visible};
use rusqlite::Transaction;
use std::sync::Arc;

/// What the handle keeps between transactions.
#[derive(Debug)]
pub(crate) struct Slot {
    data_version: i64,
    total_changes: u64,
    visible: Arc<Visible>,
}

/// The cache as one transaction sees it.
#[derive(Debug, Default)]
pub(crate) struct Txn {
    slot: Option<Slot>,
    /// The projection the database holds right now, once known.
    current: Option<Arc<Visible>>,
    /// `data_version` and change count `current` is exact for.
    exact_at: Option<(i64, u64)>,
    /// How this transaction obtained its projection (for [`Store::projection_cache_stats`]).
    pub(crate) reused: u64,
    pub(crate) decoded: u64,
}

fn data_version(tx: &Transaction<'_>) -> rusqlite::Result<i64> {
    tx.query_row("PRAGMA data_version", [], |row| row.get(0))
}

impl Txn {
    pub(crate) fn with(slot: Option<Slot>) -> Self {
        Self {
            slot,
            ..Self::default()
        }
    }

    /// The visible projection of this transaction: the cached one when it is
    /// still exact, otherwise read (and remembered).
    pub(crate) fn visible(
        &mut self,
        tx: &Transaction<'_>,
        workspace: &str,
    ) -> Result<Arc<Visible>, ExecuteError> {
        if self.current.is_none() {
            let (version, changes) = (data_version(tx)?, tx.total_changes());
            match self.slot.take() {
                Some(slot) if slot.data_version == version && slot.total_changes == changes => {
                    self.current = Some(slot.visible);
                    self.reused += 1;
                }
                _ => {
                    self.current = Some(Arc::new(load_visible(tx, workspace)?));
                    self.decoded += 1;
                }
            }
            self.exact_at = Some((version, changes));
        }
        let current = self
            .current
            .clone()
            .ok_or(ExecuteError::Store(crate::StoreError::Corrupt))?;
        #[cfg(debug_assertions)]
        assert_eq!(
            *current,
            load_visible(tx, workspace)?,
            "projection cache diverged from the store"
        );
        Ok(current)
    }

    /// Records the projection this transaction just wrote, which the caller
    /// derived from the one it read. Call after the last write of the command.
    pub(crate) fn stage(&mut self, tx: &Transaction<'_>, post: Arc<Visible>) {
        if let Some((version, _)) = self.exact_at {
            self.current = Some(post);
            self.exact_at = Some((version, tx.total_changes()));
        }
    }

    /// The transaction wrote something the cache cannot follow.
    pub(crate) fn forget(&mut self) {
        self.current = None;
        self.exact_at = None;
        self.slot = None;
    }

    /// Takes the projection for in-place update; the caller must `stage` or
    /// `forget` it again.
    pub(crate) fn take(&mut self) -> Option<Visible> {
        self.current
            .take()
            .map(|visible| Arc::try_unwrap(visible).unwrap_or_else(|shared| (*shared).clone()))
    }

    /// What to keep after the transaction committed (or the read finished), if
    /// the projection is still exact for the connection's current state.
    pub(crate) fn into_slot(self, tx: &Transaction<'_>) -> Option<Slot> {
        let (data_version, total_changes) = self.exact_at?;
        (tx.total_changes() == total_changes).then_some(())?;
        self.current.map(|visible| Slot {
            data_version,
            total_changes,
            visible,
        })
    }
}
