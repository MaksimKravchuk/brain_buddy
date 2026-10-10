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
//! lock, or not at all. [`legacy_outbox`] then classifies the pending sends and issues
//! that import carried: a send whose receipt proves its outcome is settled, one that
//! may have reached the server stays an issue and is never reissued.

mod admission;
mod apply_changes;
mod epochs;
mod execute;
mod import;
mod issues;
mod legacy_outbox;
mod legacy_review;
mod local_review;
mod localfacts;
mod locking;
mod receipts;
mod replay;
mod review_forms;
mod snapshot;
mod storage;
mod sync_session;
mod workspace_query;

pub use admission::{ShownFrameToken, ShownTaskFrame};
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
    ExecuteContext, ExecuteError, ExecuteRequest, Executed, IdSource, KnownBatch, LocalStatus,
    RandomIds, ReportedExecuteError, Stage, VisibleSnapshot, execute, execute_batch,
    execute_batch_reported_with, execute_batch_with, execute_with, lookup_known_batch,
    projection_generation, visible_snapshot,
};
pub use import::{
    AccountlessImportProof, ImportError, ImportMarker, ImportReport, ImportRequest, ImportStage,
    SUPPORTED_SOURCE_VERSION, SourceCounts, import_legacy_store, import_legacy_store_with,
    legacy_import_marker, legacy_record_key, verify_accountless_import,
};
pub use issues::{
    Choice, CurrentRecord, DecisionDraft, DependentChoice, DependentDraft, DraftAction, Issue,
    IssueError, IssueReason, IssueState, IssueView, LoadedDraft, Replacement, ResolveRequest,
    Resolved, issue, load_draft, open_issues, record_rejection, record_rejection_in, resolve_issue,
    save_draft,
};
pub use legacy_outbox::{
    LegacyAnswer, LegacyOutboxError, LegacyOutboxStatus, LegacySend, LegacyUnsent, ProvenAlias,
    ProvidedReceipts, ReceiptLookup, convert_legacy_prepared_with, convert_legacy_unsent_with,
    legacy_outbox_sends, legacy_outbox_status, legacy_unsent, resolve_legacy_outbox,
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
pub use workspace_query::{
    IssuePage, QueryError, QueryPage, WorkspaceDraft, WorkspaceRecordPage, WorkspaceSyncStatus,
    WorkspaceWatch, delete_workspace_draft_with, load_workspace_draft, query_collection_page,
    query_page, resolve_workspace_identities, save_workspace_draft_with, workspace_issues_page,
    workspace_read, workspace_records, workspace_sync_status, workspace_watch,
};

pub use localfacts::{local_task_origin_in, local_task_origins, local_task_origins_in};

pub use legacy_review::{
    LegacyReviewActivated, LegacyReviewAlias, LegacyReviewCapture, LegacyReviewDerivedCounts,
    LegacyReviewError, LegacyReviewToken, PreparedLegacyReview, activate_legacy_review,
    activate_legacy_review_with, capture_legacy_review,
};

pub use review_forms::{
    ReviewFormCount, ReviewFormDraft, ReviewFormLoaded, clear_review_forms_for_task_with,
    load_review_form, prune_review_forms_with, reverse_workspace_identities, review_form_count,
    save_review_form_with,
};

pub use local_review::{
    establish_account_less_from_import_with, establish_account_less_with,
    prune_local_review_private_with,
};
