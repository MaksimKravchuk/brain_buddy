//! Client runtime for the shared task core.
//!
//! The durable local store (the SQLite schema the runtime owns, its
//! migrations, and the cross-process rules that keep the app, widgets and App
//! Intents to one writer at a time), [`execute`], which saves a gesture's
//! immutable intent and visible projection in one transaction, and [`replay`]
//! with the sync issues it keeps: `visible = confirmed + replay(allowed
//! pending)`, a rejected intent preserved for the user, independent commands
//! still progressing. [`apply_changes`] and [`receipts`] move the confirmed
//! base forward: whole feed transactions in commit order (gaps and duplicates
//! detected, oversized ones staged and verified first), and receipts that
//! settle a command but never write after-images or move the cursor. Snapshot
//! activation and the sync session build on these in later slices.

mod apply_changes;
mod execute;
mod issues;
mod locking;
mod receipts;
mod replay;
mod storage;

pub use apply_changes::{
    Applied, ApplyError, ApplyStage, FeedStep, Fence, Recovery, TransferFault, TransferProgress,
    abandon_transfer, apply_changes, apply_changes_with, apply_transfer, apply_transfer_with,
    capture_fence, sha256_hex, stage_transfer_page,
};
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
pub use receipts::{Looked, Settled, Settlement, apply_lookup, apply_receipt};
pub use replay::{ReplayError, Replayed, replay, replay_in};
pub use storage::{OpenOptions, SCHEMA_VERSION, Store, StoreError, StoreStatus};
