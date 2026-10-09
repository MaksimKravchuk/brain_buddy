//! Client runtime for the shared task core.
//!
//! This first slice is only the durable local store: the SQLite schema the
//! runtime owns, its migrations, and the cross-process rules that keep the
//! app, widgets and App Intents to one writer at a time. Executing commands,
//! replay and sync build on it in later slices.

mod locking;
mod storage;

pub use locking::{LockMode, MigrationLock};
pub use storage::{OpenOptions, SCHEMA_VERSION, Store, StoreError, StoreStatus};
