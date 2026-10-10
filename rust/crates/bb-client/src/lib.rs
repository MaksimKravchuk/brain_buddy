//! Client runtime for the shared task core.
//!
//! The durable local store (the SQLite schema the runtime owns, its
//! migrations, and the cross-process rules that keep the app, widgets and App
//! Intents to one writer at a time) and [`execute`], which saves a gesture's
//! immutable intent and visible projection in one transaction. Replay and sync
//! build on both in later slices.

mod execute;
mod locking;
mod storage;

pub use execute::{
    ExecuteContext, ExecuteError, ExecuteRequest, Executed, IdSource, LocalStatus, RandomIds,
    Stage, execute, execute_with,
};
pub use locking::{LockMode, MigrationLock};
pub use storage::{OpenOptions, SCHEMA_VERSION, Store, StoreError, StoreStatus};
