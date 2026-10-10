//! Client runtime for the shared task core.
//!
//! The durable local store (the SQLite schema the runtime owns, its
//! migrations, and the cross-process rules that keep the app, widgets and App
//! Intents to one writer at a time), [`execute`], which saves a gesture's
//! immutable intent and visible projection in one transaction, and [`replay`]
//! with the sync issues it keeps: `visible = confirmed + replay(allowed
//! pending)`, a rejected intent preserved for the user, independent commands
//! still progressing. Feed application and sync build on these in later slices.

mod execute;
mod issues;
mod locking;
mod replay;
mod storage;

pub use execute::{
    ExecuteContext, ExecuteError, ExecuteRequest, Executed, IdSource, LocalStatus, RandomIds,
    Stage, execute, execute_with,
};
pub use issues::{
    Choice, CurrentRecord, DecisionDraft, DependentChoice, DependentDraft, DraftAction, Issue,
    IssueError, IssueReason, IssueState, IssueView, LoadedDraft, Replacement, ResolveRequest,
    Resolved, issue, load_draft, open_issues, record_rejection, record_rejection_in, resolve_issue,
    save_draft,
};
pub use locking::{LockMode, MigrationLock};
pub use replay::{ReplayError, Replayed, replay, replay_in};
pub use storage::{OpenOptions, SCHEMA_VERSION, Store, StoreError, StoreStatus};
