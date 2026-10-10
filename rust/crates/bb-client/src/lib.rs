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
//! settle a command but never write after-images or move the cursor. [`snapshot`]
//! rebuilds the base from a staged, verified snapshot in one activation that
//! keeps everything saved while it downloaded. [`sync_session`] decides which
//! answers still count (request fences over the workspace, session, local-sync
//! and server generations, reset, sign-out, unsupported versions) and [`epochs`]
//! owns the durable device epoch: registered under current authority, closed
//! without rewriting an envelope, replaced for new independent work. [`import`]
//! moves the legacy `StoreDocument` JSON file into the store: backed up, staged,
//! validated against the source and switched in one transaction under the migration
//! lock, or not at all.

mod apply_changes;
mod epochs;
mod execute;
mod import;
mod issues;
mod locking;
mod receipts;
mod replay;
mod snapshot;
mod storage;
mod sync_session;

pub use apply_changes::{
    Applied, ApplyError, ApplyStage, FeedStep, Fence, Recovery, TransferFault, TransferProgress,
    abandon_transfer, apply_changes, apply_changes_with, apply_transfer, apply_transfer_with,
    capture_fence, sha256_hex, stage_transfer_page,
};
pub use epochs::{
    Closure, EpochState, EpochView, Registered, apply_registration, close_epoch, epoch_view,
    send_candidates,
};
pub use execute::{
    ExecuteContext, ExecuteError, ExecuteRequest, Executed, IdSource, LocalStatus, RandomIds,
    Stage, execute, execute_with,
};
pub use import::{
    ImportError, ImportMarker, ImportReport, ImportRequest, ImportStage, SUPPORTED_SOURCE_VERSION,
    SourceCounts, import_legacy_store, import_legacy_store_with, legacy_import_marker,
    legacy_record_key,
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
pub use snapshot::{
    Activated, SnapshotProgress, abandon_snapshot, activate_snapshot, activate_snapshot_with,
    begin_snapshot, stage_snapshot_page,
};
pub use storage::{OpenOptions, SCHEMA_VERSION, Store, StoreError, StoreStatus};
pub use sync_session::{
    Authentication, CapabilitiesCheck, EndCause, ErrorAction, Request, RequestKind, SessionBinding,
    SessionError, SyncSession,
};
