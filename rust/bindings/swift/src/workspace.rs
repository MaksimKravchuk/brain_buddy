//! Durable workspace calls have their own lifecycle: unlike pure calls, a
//! committed result survives cancellation/close. The gesture ID recovers a
//! completion lost when the OS suspends the caller.
use super::{
    BridgeError, BridgeRefusal, CLOSED, Failure, OPEN, POISONED, guarded, parse_json, to_json,
};
use bb_client::{
    ExecuteContext, ExecuteError, ExecuteRequest, OpenOptions, QueryError, RandomIds,
    ReportedExecuteError, Store, StoreError, StoreStatus, WorkspaceDraft, WorkspaceWatch,
    convert_legacy_prepared_with, delete_workspace_draft_with, execute_batch_reported_with,
    legacy_unsent, load_workspace_draft, query_collection_page, resolve_workspace_identities,
    save_workspace_draft_with, visible_snapshot, workspace_issues_page, workspace_read,
    workspace_sync_status, workspace_watch,
};
use bb_domain::types::{ActorId, Policy, Query, QueryInputs, ZoneName};
use bb_protocol::{
    catalog::CommandType,
    command::Precondition,
    wire::{CommandId, Id, Instant, OpenObject},
};
use std::{
    path::PathBuf,
    sync::{
        Arc, Condvar, Mutex,
        atomic::{AtomicBool, AtomicU8, Ordering},
    },
    time::{Duration, Instant as Clock},
};

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeStoreRequest {
    pub workspace_id: String,
    pub database_path: String,
    pub busy_timeout_ms: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum BridgeStoreStatus {
    Ready,
    ReadOnlyRecovery { found: i64 },
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeWorkspaceCommand {
    pub command_id: String,
    pub command_type: String,
    pub entity_id: Option<String>,
    pub payload: Vec<u8>,
    pub preconditions: Vec<u8>,
    pub depends_on: Vec<String>,
    /// JSON token array; LOCAL only.
    pub admission_tokens: Vec<u8>,
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeWorkspaceDraft {
    pub draft_id: String,
    pub editor_kind: String,
    pub record_type: Option<String>,
    pub record_key: Option<String>,
    pub base_revision: Option<String>,
    pub fields: Vec<u8>,
    pub updated_at: String,
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeRecordRequest {
    pub entity_type: String,
    pub record_key: Vec<u8>,
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeIdentityRequest {
    pub entity_type: String,
    pub local_id: String,
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeIdentityBinding {
    pub entity_type: String,
    pub local_id: String,
    pub canonical_id: Option<String>,
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeSourceIdentityRequest {
    pub entity_type: String,
    pub canonical_id: String,
}
#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeSourceIdentityBinding {
    pub entity_type: String,
    pub canonical_id: String,
    pub source_id: Option<String>,
}
#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeReviewForm {
    pub text: String,
    pub saved_at: String,
}
#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeReviewFormCount {
    pub live_count: String,
    pub projection_generation: String,
}
#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeReviewFormLoaded {
    pub source_key: String,
    pub draft: Option<BridgeReviewForm>,
    pub live_count: String,
    pub projection_generation: String,
}
impl From<bb_client::ReviewFormCount> for BridgeReviewFormCount {
    fn from(value: bb_client::ReviewFormCount) -> Self {
        Self {
            live_count: value.live_count.to_string(),
            projection_generation: value.projection_generation.to_string(),
        }
    }
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeLegacyUnsent {
    pub entry_id: String,
    pub idempotency_key: String,
    pub issued_at: String,
    pub command: Vec<u8>,
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeLegacyConversion {
    pub entry_id: String,
    pub issued_at: String,
    pub command: BridgeWorkspaceCommand,
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeLegacyReviewCapture {
    pub token: Vec<u8>,
    pub review: Vec<u8>,
    pub aliases: Vec<u8>,
    pub source_counts: Vec<u8>,
    pub already_active: bool,
}
#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeLegacyReviewPrepared {
    pub token: Vec<u8>,
    pub read_set: Vec<u8>,
    pub aliases: Vec<u8>,
    pub derived_counts: Vec<u8>,
}
#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeLegacyReviewActivated {
    pub projection_generation: String,
    pub already_active: bool,
    pub aliases: Vec<u8>,
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeExecuteContext {
    pub now: String,
    pub time_zone: String,
    pub actor_id: String,
    pub policy: Vec<u8>,
}

#[derive(Clone, Debug, PartialEq, Eq, uniffi::Record)]
pub struct BridgeSaved {
    pub command_id: String,
    pub entity_id: String,
    pub local_sequence: String,
    pub projection_generation: String,
    pub replayed: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum BridgeExecution {
    Saved {
        results: Vec<BridgeSaved>,
    },
    Refused {
        refusal: BridgeRefusal,
        failed_command_id: Option<String>,
    },
}

#[derive(Clone, Debug, PartialEq, Eq, uniffi::Enum)]
pub enum BridgeKnownBatch {
    Known { results: Vec<BridgeSaved> },
    NotKnown,
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeWorkspacePage {
    pub projection_generation: String,
    pub result: Vec<u8>,
    /// Original query frame token and local-origin siblings.
    pub task_frames: Vec<u8>,
    pub collection_next_cursor: Option<String>,
}

#[derive(Clone, Debug, uniffi::Enum)]
pub enum BridgeWorkspaceAnswer {
    Answered {
        page: BridgeWorkspacePage,
    },
    Refused {
        refusal: BridgeRefusal,
        projection_generation: Option<String>,
    },
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeWorkspaceSnapshot {
    pub projection_generation: String,
    pub records: Vec<u8>,
    pub pending: String,
    pub open_issues: String,
}

#[derive(Clone, Debug, uniffi::Record)]
pub struct BridgeInvalidation {
    pub projection_generation: String,
    pub changed_kinds: Vec<String>,
    pub sync_status_changed: bool,
    pub issues_changed: bool,
    pub pending: String,
    pub open_issues: String,
    pub token: String,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum OperationState {
    Open,
    Cancelled,
    Committed,
}

/// Cancellation arbitrates with commit, not with completion delivery.
#[derive(uniffi::Object)]
pub struct BridgeOperation {
    state: Mutex<OperationState>,
    used: AtomicBool,
}

#[uniffi::export]
impl BridgeOperation {
    #[uniffi::constructor]
    pub fn new() -> Self {
        Self {
            state: Mutex::new(OperationState::Open),
            used: AtomicBool::new(false),
        }
    }

    /// True means cancellation won: this operation will save nothing. False
    /// means final commit owns the boundary; await its receipt or storage error.
    /// Never wait for disk finalization on the caller's cancellation executor.
    pub fn cancel(&self) -> bool {
        let Ok(mut state) = self.state.try_lock() else {
            return false;
        };
        if *state == OperationState::Open {
            *state = OperationState::Cancelled;
        }
        *state == OperationState::Cancelled
    }

    pub fn is_committed(&self) -> bool {
        self.state
            .lock()
            .is_ok_and(|state| *state == OperationState::Committed)
    }
}

impl Default for BridgeOperation {
    fn default() -> Self {
        Self::new()
    }
}

impl From<&StoreError> for Failure {
    fn from(error: &StoreError) -> Self {
        Self {
            code: error.code(),
            retryable: error.is_retryable(),
            field: None,
        }
    }
}

fn execute_failure(error: ExecuteError) -> Failure {
    Failure {
        code: error.code(),
        retryable: error.is_retryable(),
        field: None,
    }
}
fn form_failure(error: ExecuteError) -> Failure {
    if let ExecuteError::Refused(error) = &error {
        match error.field.as_deref() {
            Some("form_identity_unproven" | "formulation_identity_unproven") => {
                return Failure::new("FORM_IDENTITY_UNPROVEN", Some("key"));
            }
            Some("identity_ambiguity") => {
                return Failure::new("FORM_IDENTITY_AMBIGUOUS", Some("key"));
            }
            _ => {}
        }
    }
    execute_failure(error)
}
fn form_query_failure(error: QueryError) -> Failure {
    match error {
        QueryError::Refused(error) => form_failure(ExecuteError::Refused(error)),
        error => query_failure(error),
    }
}

fn owned_context(context: &BridgeExecuteContext) -> Result<ExecuteContext, Failure> {
    let invalid = |field| Failure::new("INVALID_REQUEST", Some(field));
    Ok(ExecuteContext {
        now: Instant::parse(&context.now).map_err(|_| invalid("now"))?,
        time_zone: ZoneName::new(&context.time_zone).map_err(|_| invalid("time_zone"))?,
        actor_id: ActorId::parse(&context.actor_id).map_err(|_| invalid("actor_id"))?,
        policy: parse_json::<Policy>(&context.policy, "policy")?,
    })
}

fn review_failure(error: bb_client::LegacyReviewError) -> Failure {
    Failure {
        code: error.code(),
        retryable: error.is_retryable(),
        field: error.field(),
    }
}

fn requests(
    commands: &[BridgeWorkspaceCommand],
    context: &BridgeExecuteContext,
) -> Result<Vec<ExecuteRequest>, Failure> {
    let invalid = |field| Failure::new("INVALID_REQUEST", Some(field));
    let context = owned_context(context)?;
    commands
        .iter()
        .map(|command| {
            Ok(ExecuteRequest {
                command_id: CommandId::parse(&command.command_id)
                    .map_err(|_| invalid("command_id"))?,
                command_type: CommandType::from_wire(&command.command_type)
                    .ok_or_else(|| invalid("command_type"))?,
                entity_id: command
                    .entity_id
                    .as_ref()
                    .map(|id| Id::parse(id).map_err(|_| invalid("entity_id")))
                    .transpose()?,
                payload: parse_json::<OpenObject>(&command.payload, "payload")?,
                preconditions: parse_json::<Vec<Precondition>>(
                    &command.preconditions,
                    "preconditions",
                )?,
                depends_on: command
                    .depends_on
                    .iter()
                    .map(|id| CommandId::parse(id).map_err(|_| invalid("depends_on")))
                    .collect::<Result<_, _>>()?,
                admission_tokens: if command.admission_tokens.is_empty() {
                    Vec::new()
                } else {
                    parse_json(&command.admission_tokens, "admission_tokens")?
                },
                context: context.clone(),
            })
        })
        .collect()
}

#[derive(uniffi::Object)]
pub struct BridgeWorkspace {
    state: Arc<AtomicU8>,
    store: Mutex<Option<Store>>,
    options: OpenOptions,
}

impl BridgeWorkspace {
    pub(super) fn open(request: BridgeStoreRequest) -> Result<Arc<Self>, Failure> {
        if request.workspace_id.is_empty() || request.database_path.is_empty() {
            return Err(Failure::new("INVALID_REQUEST", Some("workspace_id")));
        }
        let options = OpenOptions {
            path: PathBuf::from(request.database_path),
            workspace_id: request.workspace_id,
            busy_timeout: Duration::from_millis(u64::from(request.busy_timeout_ms)),
        };
        let store = Store::open(&options).map_err(|error| Failure::from(&error))?;
        Ok(Arc::new(Self {
            state: Arc::new(AtomicU8::new(OPEN)),
            store: Mutex::new(Some(store)),
            options,
        }))
    }

    fn save_requests(
        &self,
        requests: Vec<ExecuteRequest>,
        operation: Arc<BridgeOperation>,
        entry_ids: Option<Vec<String>>,
    ) -> Result<BridgeExecution, Failure> {
        if operation.used.swap(true, Ordering::AcqRel) {
            return Err(Failure::new("OPERATION_ALREADY_USED", None));
        }
        match self.state.load(Ordering::Acquire) {
            CLOSED => return Err(Failure::new("WORKSPACE_CLOSED", None)),
            POISONED => return Err(Failure::new("INTERNAL_ERROR", None)),
            _ => {}
        }
        let mut held = self
            .store
            .lock()
            .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
        let store = held
            .as_mut()
            .ok_or_else(|| Failure::new("WORKSPACE_CLOSED", None))?;
        let mut arbitration = None;
        // guarded contains panics and rolls back the transaction. Its pure-call
        // lifecycle override is not used here: a commit is irreversible.
        let result = guarded(&AtomicU8::new(OPEN), || {
            let mut before_commit = || {
                let lock = operation.state.lock().map_err(|_| StoreError::Corrupt)?;
                if *lock == OperationState::Cancelled || self.state.load(Ordering::Acquire) != OPEN
                {
                    return Err(ExecuteError::Cancelled);
                }
                arbitration = Some(lock); // stays held through SQLite commit
                Ok(())
            };
            let result = if let Some(entry_ids) = &entry_ids {
                convert_legacy_prepared_with(
                    store,
                    &mut RandomIds,
                    &requests,
                    Some(entry_ids),
                    |_| before_commit(),
                )
                .map_err(ReportedExecuteError::from)
            } else {
                execute_batch_reported_with(store, &mut RandomIds, &requests, |_| before_commit())
            };
            match result {
                Ok(results) => {
                    if let Some(lock) = &mut arbitration {
                        **lock = OperationState::Committed;
                    }
                    Ok(BridgeExecution::Saved {
                        results: results
                            .into_iter()
                            .map(|saved| BridgeSaved {
                                command_id: saved.command_id.as_str().to_owned(),
                                entity_id: saved.entity_id.as_str().to_owned(),
                                local_sequence: saved.local_sequence.to_string(),
                                projection_generation: saved.projection_generation.to_string(),
                                replayed: saved.replayed,
                            })
                            .collect(),
                    })
                }
                Err(ReportedExecuteError {
                    error: ExecuteError::Refused(error),
                    failed_command_id,
                }) => Ok(BridgeExecution::Refused {
                    refusal: error.into(),
                    failed_command_id: failed_command_id.map(|id| id.as_str().to_owned()),
                }),
                Err(error) => Err(execute_failure(error.error)),
            }
        });
        if result
            .as_ref()
            .is_err_and(|error| error.code == "INTERNAL_ERROR")
        {
            self.state
                .compare_exchange(OPEN, POISONED, Ordering::AcqRel, Ordering::Acquire)
                .ok();
        }
        result
    }

    fn mutate_draft(
        &self,
        id: &str,
        draft: Option<&WorkspaceDraft>,
        operation: Arc<BridgeOperation>,
    ) -> Result<(), Failure> {
        if operation.used.swap(true, Ordering::AcqRel) {
            return Err(Failure::new("OPERATION_ALREADY_USED", None));
        }
        if self.state.load(Ordering::Acquire) != OPEN {
            return Err(Failure::new("WORKSPACE_CLOSED", None));
        }
        let mut held = self
            .store
            .lock()
            .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
        let store = held
            .as_mut()
            .ok_or_else(|| Failure::new("WORKSPACE_CLOSED", None))?;
        let mut arbitration = None;
        guarded(&AtomicU8::new(OPEN), || {
            let before_commit = || {
                let lock = operation.state.lock().map_err(|_| StoreError::Corrupt)?;
                if *lock == OperationState::Cancelled || self.state.load(Ordering::Acquire) != OPEN
                {
                    return Err(ExecuteError::Cancelled);
                }
                arbitration = Some(lock);
                Ok(())
            };
            let result = match draft {
                Some(draft) => save_workspace_draft_with(store, draft, before_commit),
                None => delete_workspace_draft_with(store, id, before_commit),
            };
            result.map_err(execute_failure)?;
            if let Some(lock) = &mut arbitration {
                **lock = OperationState::Committed;
            }
            Ok(())
        })
    }

    fn mutate_review_forms(
        &self,
        operation: Arc<BridgeOperation>,
        work: impl FnOnce(
            &mut Store,
            &mut dyn FnMut() -> Result<(), ExecuteError>,
        ) -> Result<bb_client::ReviewFormCount, ExecuteError>,
    ) -> Result<BridgeReviewFormCount, Failure> {
        if operation.used.swap(true, Ordering::AcqRel) {
            return Err(Failure::new("OPERATION_ALREADY_USED", None));
        }
        if self.state.load(Ordering::Acquire) != OPEN {
            return Err(Failure::new("WORKSPACE_CLOSED", None));
        }
        let mut held = self
            .store
            .lock()
            .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
        let store = held
            .as_mut()
            .ok_or_else(|| Failure::new("WORKSPACE_CLOSED", None))?;
        let mut arbitration = None;
        guarded(&AtomicU8::new(OPEN), || {
            let mut before_commit = || {
                let lock = operation.state.lock().map_err(|_| StoreError::Corrupt)?;
                if *lock == OperationState::Cancelled || self.state.load(Ordering::Acquire) != OPEN
                {
                    return Err(ExecuteError::Cancelled);
                }
                arbitration = Some(lock);
                Ok(())
            };
            let result = work(store, &mut before_commit).map_err(form_failure)?;
            if let Some(lock) = &mut arbitration {
                **lock = OperationState::Committed;
            }
            Ok(result.into())
        })
    }

    fn mutate_local_review<T, E>(
        &self,
        operation: Arc<BridgeOperation>,
        work: impl FnOnce(&mut Store, &mut dyn FnMut() -> Result<(), ExecuteError>) -> Result<T, E>,
        failure: impl FnOnce(E) -> Failure,
    ) -> Result<T, Failure> {
        if operation.used.swap(true, Ordering::AcqRel) {
            return Err(Failure::new("OPERATION_ALREADY_USED", None));
        }
        if self.state.load(Ordering::Acquire) != OPEN {
            return Err(Failure::new("WORKSPACE_CLOSED", None));
        }
        let mut held = self
            .store
            .lock()
            .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
        let store = held
            .as_mut()
            .ok_or_else(|| Failure::new("WORKSPACE_CLOSED", None))?;
        let mut arbitration = None;
        guarded(&AtomicU8::new(OPEN), || {
            let mut before_commit = || {
                let lock = operation.state.lock().map_err(|_| StoreError::Corrupt)?;
                if *lock == OperationState::Cancelled || self.state.load(Ordering::Acquire) != OPEN
                {
                    return Err(ExecuteError::Cancelled);
                }
                arbitration = Some(lock);
                Ok(())
            };
            let result = work(store, &mut before_commit).map_err(failure)?;
            if let Some(lock) = &mut arbitration {
                **lock = OperationState::Committed;
            }
            Ok(result)
        })
    }

    fn with_store<T>(
        &self,
        work: impl FnOnce(&mut Store) -> Result<T, Failure>,
    ) -> Result<T, Failure> {
        guarded(&self.state, || {
            let mut held = self
                .store
                .lock()
                .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
            let store = held
                .as_mut()
                .ok_or_else(|| Failure::new("WORKSPACE_CLOSED", None))?;
            work(store)
        })
    }
}

#[uniffi::export]
impl BridgeWorkspace {
    pub fn status(&self) -> Result<BridgeStoreStatus, BridgeError> {
        Ok(self.with_store(|store| {
            Ok(match store.status() {
                StoreStatus::Ready => BridgeStoreStatus::Ready,
                StoreStatus::ReadOnlyRecovery { found } => {
                    BridgeStoreStatus::ReadOnlyRecovery { found }
                }
            })
        })?)
    }

    /// Trusted workspace lifecycle selection; callers must make the explicit
    /// accountless choice before new local gestures. Missing credentials do not
    /// activate it, and owner-bound history is never reinterpreted.
    pub fn establish_account_less(
        &self,
        operation: Arc<BridgeOperation>,
    ) -> Result<(), BridgeError> {
        self.mutate_local_review(
            operation,
            |store, before_commit| {
                bb_client::establish_account_less_with(store, before_commit)?;
                Ok(0)
            },
            execute_failure,
        )?;
        Ok(())
    }

    /// Exact retained backup/source proof is verified by the importer; no JSON
    /// authority flag or source-account guess crosses this port.
    pub fn establish_account_less_from_import(
        &self,
        retained_source_path: String,
        operation: Arc<BridgeOperation>,
    ) -> Result<(), BridgeError> {
        if retained_source_path.is_empty() || retained_source_path.len() > 4096 {
            return Err(Failure::new("INVALID_REQUEST", Some("retained_source_path")).into());
        }
        self.mutate_local_review(
            operation,
            |store, before_commit| {
                let proof = bb_client::verify_accountless_import(
                    store,
                    std::path::Path::new(&retained_source_path),
                )
                .map_err(|error| match error {
                    bb_client::ImportError::Store(error) => ExecuteError::Store(error),
                    error => ExecuteError::Refused(bb_domain::types::DomainError::field(
                        bb_domain::types::Reason::InvalidValue,
                        error.field().unwrap_or("account_less_import"),
                    )),
                })?;
                bb_client::establish_account_less_from_import_with(store, &proof, before_commit)?;
                Ok(0)
            },
            execute_failure,
        )?;
        Ok(())
    }

    /// Bounded, coalescable private-beforeimage upkeep, even when Review is OFF.
    pub fn prune_local_review_private(
        &self,
        now: String,
        limit: u32,
        operation: Arc<BridgeOperation>,
    ) -> Result<u32, BridgeError> {
        let now = Instant::parse(now).map_err(|_| Failure::new("INVALID_REQUEST", Some("now")))?;
        Ok(self.mutate_local_review(
            operation,
            |store, before_commit| {
                bb_client::prune_local_review_private_with(store, &now, limit, before_commit)
            },
            execute_failure,
        )?)
    }

    /// Trusted selected private capture. It reads the exact digest-verified
    /// retained import backup, never a current native task reconstruction.
    /// One bounded original-source private component. A null result is an
    /// expired or absent source, and cannot be combined into displayed tasks.
    pub fn capture_local_review_private_fragment(
        &self,
        retained_source_path: String,
        selected: Vec<u8>,
        after: Option<String>,
        now: String,
    ) -> Result<Vec<u8>, BridgeError> {
        if retained_source_path.is_empty()
            || retained_source_path.len() > 4096
            || selected.len() > 4096
            || after.as_ref().is_some_and(|v| v.len() > 4096)
        {
            return Err(Failure::new("INVALID_REQUEST", Some("local_review_private")).into());
        }
        let selected: bb_client::LocalReviewSourceId = parse_json(&selected, "selected")?;
        let now = Instant::parse(now).map_err(|_| Failure::new("INVALID_REQUEST", Some("now")))?;
        Ok(self.with_store(|store| {
            let proof = bb_client::verify_accountless_import(
                store,
                std::path::Path::new(&retained_source_path),
            )
            .map_err(|error| Failure {
                code: error.code(),
                retryable: error.is_retryable(),
                field: error.field(),
            })?;
            to_json(
                &bb_client::capture_local_review_private_fragment(
                    store,
                    &proof,
                    &selected,
                    after.as_deref(),
                    &now,
                )
                .map_err(review_failure)?,
            )
        })?)
    }
    /// Incomplete typed components remain reserved drafts. Complete native
    /// coverage and all original pins install private evidence atomically.
    pub fn admit_local_review_private_fragment(
        &self,
        retained_source_path: String,
        prepared: Vec<u8>,
        now: String,
        operation: Arc<BridgeOperation>,
    ) -> Result<Vec<u8>, BridgeError> {
        if retained_source_path.is_empty()
            || retained_source_path.len() > 4096
            || prepared.len() > 8 * 1024 * 1024
        {
            return Err(Failure::new("INVALID_REQUEST", Some("local_review_private")).into());
        }
        let prepared: bb_client::PreparedLocalReviewFragment = parse_json(&prepared, "prepared")?;
        let now = Instant::parse(now).map_err(|_| Failure::new("INVALID_REQUEST", Some("now")))?;
        let outcome = self.mutate_local_review(
            operation,
            |store, before_commit| {
                let arbitrate = |error| match error {
                    ExecuteError::Cancelled => bb_client::LegacyReviewError::Cancelled,
                    ExecuteError::Store(error) => bb_client::LegacyReviewError::Store(error),
                    _ => bb_client::LegacyReviewError::Invalid("local_review_private"),
                };
                if let Some(known) =
                    bb_client::lookup_local_review_private_fragment(store, &prepared)?
                {
                    before_commit().map_err(arbitrate)?;
                    return Ok(known);
                }
                let proof = bb_client::verify_accountless_import(
                    store,
                    std::path::Path::new(&retained_source_path),
                )
                .map_err(|error| match error {
                    bb_client::ImportError::Store(error) => {
                        bb_client::LegacyReviewError::Store(error)
                    }
                    _ => bb_client::LegacyReviewError::Invalid("account_less_import"),
                })?;
                bb_client::admit_local_review_private_fragment_with(
                    store,
                    &proof,
                    &prepared,
                    &now,
                    || before_commit().map_err(arbitrate),
                )
            },
            review_failure,
        )?;
        Ok(to_json(&outcome)?)
    }

    /// Every command is saved in one transaction. Once commit wins, neither
    /// caller cancellation nor close can turn its receipt into CANCELLED.
    pub fn execute(
        &self,
        commands: Vec<BridgeWorkspaceCommand>,
        context: BridgeExecuteContext,
        operation: Arc<BridgeOperation>,
    ) -> Result<BridgeExecution, BridgeError> {
        let requests = requests(&commands, &context)?;
        Ok(self.save_requests(requests, operation, None)?)
    }

    /// Recovers only a fully known original batch; it never executes a suffix.
    pub fn lookup_known_batch(
        &self,
        commands: Vec<BridgeWorkspaceCommand>,
        context: BridgeExecuteContext,
    ) -> Result<BridgeKnownBatch, BridgeError> {
        let requests = requests(&commands, &context)?;
        Ok(self.with_store(|store| {
            match bb_client::lookup_known_batch(store, &requests).map_err(execute_failure)? {
                bb_client::KnownBatch::NotKnown => Ok(BridgeKnownBatch::NotKnown),
                bb_client::KnownBatch::Known { results } => Ok(BridgeKnownBatch::Known {
                    results: results
                        .into_iter()
                        .map(|saved| BridgeSaved {
                            command_id: saved.command_id.as_str().to_owned(),
                            entity_id: saved.entity_id.as_str().to_owned(),
                            local_sequence: saved.local_sequence.to_string(),
                            projection_generation: saved.projection_generation.to_string(),
                            replayed: saved.replayed,
                        })
                        .collect(),
                }),
            }
        })?)
    }

    /// Source identities, keys and original issue times are checked again in
    /// the transaction that saves every command and every conversion marker.
    pub fn convert_legacy_unsent(
        &self,
        items: Vec<BridgeLegacyConversion>,
        context: BridgeExecuteContext,
        operation: Arc<BridgeOperation>,
    ) -> Result<BridgeExecution, BridgeError> {
        let mut prepared = Vec::with_capacity(items.len());
        let mut entry_ids = Vec::with_capacity(items.len());
        for item in items {
            let mut issued_context = context.clone();
            issued_context.now = item.issued_at;
            prepared.extend(requests(&[item.command], &issued_context)?);
            entry_ids.push(item.entry_id);
        }
        Ok(self.save_requests(prepared, operation, Some(entry_ids))?)
    }

    pub fn legacy_unsent(&self) -> Result<Vec<BridgeLegacyUnsent>, BridgeError> {
        Ok(self.with_store(|store| {
            legacy_unsent(store)
                .map_err(|error| Failure::from(&error))?
                .into_iter()
                .map(|item| {
                    Ok(BridgeLegacyUnsent {
                        entry_id: item.entry_id,
                        idempotency_key: item.idempotency_key.as_str().to_owned(),
                        issued_at: item.issued_at.as_str().to_owned(),
                        command: to_json(&item.command)?,
                    })
                })
                .collect()
        })?)
    }

    pub fn smart_add_resolve(&self, draft: Vec<u8>) -> Result<BridgeWorkspaceAnswer, BridgeError> {
        Ok(self.with_store(|store| {
            let (generation, result) = workspace_read(store, None, |state| {
                super::resolve_smart_add(&to_json(state)?, &draft)
            })
            .map_err(query_failure)?;
            Ok(BridgeWorkspaceAnswer::Answered {
                page: BridgeWorkspacePage {
                    projection_generation: generation.to_string(),
                    result: result?,
                    task_frames: b"[]".to_vec(),
                    collection_next_cursor: None,
                },
            })
        })?)
    }

    pub fn smart_add_propose(
        &self,
        draft: Vec<u8>,
        minted: Vec<u8>,
        expected_generation: String,
    ) -> Result<BridgeWorkspaceAnswer, BridgeError> {
        let generation = expected_generation
            .parse::<u64>()
            .map_err(|_| Failure::new("INVALID_REQUEST", Some("expected_generation")))?;
        Ok(self.with_store(|store| {
            let (generation, result) = workspace_read(store, Some(generation), |state| {
                super::propose_smart_add(&to_json(state)?, &draft, &minted)
            })
            .map_err(query_failure)?;
            Ok(match result? {
                super::BridgeAnswer::Answered { result } => BridgeWorkspaceAnswer::Answered {
                    page: BridgeWorkspacePage {
                        projection_generation: generation.to_string(),
                        result,
                        task_frames: b"[]".to_vec(),
                        collection_next_cursor: None,
                    },
                },
                super::BridgeAnswer::Refused { refusal } => BridgeWorkspaceAnswer::Refused {
                    refusal,
                    projection_generation: Some(generation.to_string()),
                },
            })
        })?)
    }

    pub fn query(
        &self,
        query: Vec<u8>,
        inputs: Vec<u8>,
        collection_limit: u32,
        collection_after: Option<String>,
    ) -> Result<BridgeWorkspaceAnswer, BridgeError> {
        let query: Query = parse_json(&query, "query")?;
        let inputs: QueryInputs = parse_json(&inputs, "inputs")?;
        Ok(self.with_store(|store| {
            match query_collection_page(
                store,
                &query,
                &inputs,
                collection_limit,
                collection_after.as_deref(),
            ) {
                Ok(page) => Ok(BridgeWorkspaceAnswer::Answered {
                    page: BridgeWorkspacePage {
                        projection_generation: page.projection_generation.to_string(),
                        result: to_json(&page.result)?,
                        task_frames: to_json(&page.task_frames)?,
                        collection_next_cursor: page.collection_next_cursor,
                    },
                }),
                Err(QueryError::Store(error)) => Err(Failure::from(&error)),
                Err(QueryError::RestartRequired) => {
                    Err(Failure::new("QUERY_RESTART_REQUIRED", None))
                }
                Err(QueryError::Refused(error)) => Ok(BridgeWorkspaceAnswer::Refused {
                    refusal: error.into(),
                    projection_generation: None,
                }),
                Err(QueryError::RefusedAt {
                    error,
                    projection_generation,
                }) => Ok(BridgeWorkspaceAnswer::Refused {
                    refusal: error.into(),
                    projection_generation: Some(projection_generation.to_string()),
                }),
            }
        })?)
    }

    pub fn load_draft(
        &self,
        draft_id: String,
    ) -> Result<Option<BridgeWorkspaceDraft>, BridgeError> {
        Ok(self.with_store(|store| {
            load_workspace_draft(store, &draft_id)
                .map_err(query_failure)?
                .map(|draft| {
                    Ok(BridgeWorkspaceDraft {
                        draft_id: draft.draft_id,
                        editor_kind: draft.editor_kind,
                        record_type: draft.record_type,
                        record_key: draft.record_key,
                        base_revision: draft.base_revision,
                        fields: to_json(&draft.fields)?,
                        updated_at: draft.updated_at,
                    })
                })
                .transpose()
        })?)
    }

    pub fn reverse_identities(
        &self,
        items: Vec<BridgeSourceIdentityRequest>,
    ) -> Result<Vec<BridgeSourceIdentityBinding>, BridgeError> {
        let typed = items
            .iter()
            .map(|item| {
                Ok((
                    bb_protocol::catalog::EntityType::from_wire(&item.entity_type)
                        .ok_or_else(|| Failure::new("INVALID_REQUEST", Some("entity_type")))?,
                    item.canonical_id.clone(),
                ))
            })
            .collect::<Result<Vec<_>, Failure>>()?;
        Ok(self.with_store(|store| {
            let sources = bb_client::reverse_workspace_identities(store, &typed)
                .map_err(form_query_failure)?;
            Ok(items
                .into_iter()
                .zip(sources)
                .map(|(item, source_id)| BridgeSourceIdentityBinding {
                    entity_type: item.entity_type,
                    canonical_id: item.canonical_id,
                    source_id,
                })
                .collect())
        })?)
    }

    pub fn load_review_form(
        &self,
        key: String,
        now: String,
    ) -> Result<BridgeReviewFormLoaded, BridgeError> {
        let now = Instant::parse(now).map_err(|_| Failure::new("INVALID_REQUEST", Some("now")))?;
        Ok(self.with_store(|store| {
            let loaded =
                bb_client::load_review_form(store, &key, &now).map_err(form_query_failure)?;
            Ok(BridgeReviewFormLoaded {
                source_key: loaded.source_key,
                draft: loaded.draft.map(|draft| BridgeReviewForm {
                    text: draft.text,
                    saved_at: draft.saved_at.as_str().to_owned(),
                }),
                live_count: loaded.live_count.to_string(),
                projection_generation: loaded.projection_generation.to_string(),
            })
        })?)
    }
    pub fn review_form_count(&self, now: String) -> Result<BridgeReviewFormCount, BridgeError> {
        let now = Instant::parse(now).map_err(|_| Failure::new("INVALID_REQUEST", Some("now")))?;
        Ok(self.with_store(|store| {
            bb_client::review_form_count(store, &now)
                .map(Into::into)
                .map_err(form_query_failure)
        })?)
    }
    pub fn prune_review_forms(
        &self,
        now: String,
        operation: Arc<BridgeOperation>,
    ) -> Result<BridgeReviewFormCount, BridgeError> {
        let now = Instant::parse(now).map_err(|_| Failure::new("INVALID_REQUEST", Some("now")))?;
        Ok(self.mutate_review_forms(operation, |store, before_commit| {
            bb_client::prune_review_forms_with(store, &now, before_commit)
        })?)
    }
    pub fn save_review_form(
        &self,
        key: String,
        source_key: Option<String>,
        draft: Option<BridgeReviewForm>,
        now: String,
        operation: Arc<BridgeOperation>,
    ) -> Result<BridgeReviewFormCount, BridgeError> {
        let now = Instant::parse(now).map_err(|_| Failure::new("INVALID_REQUEST", Some("now")))?;
        let draft = draft
            .map(|draft| {
                Ok::<_, Failure>(bb_client::ReviewFormDraft {
                    text: draft.text,
                    saved_at: Instant::parse(draft.saved_at)
                        .map_err(|_| Failure::new("INVALID_REQUEST", Some("saved_at")))?,
                })
            })
            .transpose()?;
        Ok(self.mutate_review_forms(operation, |store, before_commit| {
            bb_client::save_review_form_with(
                store,
                &key,
                source_key.as_deref(),
                draft.as_ref(),
                &now,
                before_commit,
            )
        })?)
    }
    pub fn clear_review_forms_for_task(
        &self,
        canonical_task_id: String,
        now: String,
        operation: Arc<BridgeOperation>,
    ) -> Result<BridgeReviewFormCount, BridgeError> {
        let now = Instant::parse(now).map_err(|_| Failure::new("INVALID_REQUEST", Some("now")))?;
        Ok(self.mutate_review_forms(operation, |store, before_commit| {
            bb_client::clear_review_forms_for_task_with(
                store,
                &canonical_task_id,
                &now,
                before_commit,
            )
        })?)
    }

    pub fn save_draft(
        &self,
        draft: BridgeWorkspaceDraft,
        operation: Arc<BridgeOperation>,
    ) -> Result<(), BridgeError> {
        let owned = WorkspaceDraft {
            draft_id: draft.draft_id,
            editor_kind: draft.editor_kind,
            record_type: draft.record_type,
            record_key: draft.record_key,
            base_revision: draft.base_revision,
            fields: parse_json(&draft.fields, "fields")?,
            updated_at: draft.updated_at,
        };
        Ok(self.mutate_draft(&owned.draft_id, Some(&owned), operation)?)
    }

    pub fn delete_draft(
        &self,
        draft_id: String,
        operation: Arc<BridgeOperation>,
    ) -> Result<(), BridgeError> {
        Ok(self.mutate_draft(&draft_id, None, operation)?)
    }

    pub fn capture_legacy_review(&self) -> Result<BridgeLegacyReviewCapture, BridgeError> {
        Ok(self.with_store(|store| {
            let capture = bb_client::capture_legacy_review(store).map_err(review_failure)?;
            Ok(BridgeLegacyReviewCapture {
                token: to_json(&capture.token)?,
                review: to_json(&capture.review)?,
                aliases: to_json(&capture.aliases)?,
                source_counts: to_json(&capture.source_counts)?,
                already_active: capture.already_active,
            })
        })?)
    }

    pub fn activate_legacy_review(
        &self,
        prepared: BridgeLegacyReviewPrepared,
        context: BridgeExecuteContext,
        operation: Arc<BridgeOperation>,
    ) -> Result<BridgeLegacyReviewActivated, BridgeError> {
        let prepared = bb_client::PreparedLegacyReview {
            token: parse_json(&prepared.token, "token")?,
            read_set: parse_json(&prepared.read_set, "read_set")?,
            aliases: parse_json(&prepared.aliases, "aliases")?,
            derived_counts: parse_json(&prepared.derived_counts, "derived_counts")?,
        };
        let context = owned_context(&context)?;
        if operation.used.swap(true, Ordering::AcqRel) {
            return Err(Failure::new("OPERATION_ALREADY_USED", None).into());
        }
        match self.state.load(Ordering::Acquire) {
            CLOSED => return Err(Failure::new("WORKSPACE_CLOSED", None).into()),
            POISONED => return Err(Failure::new("INTERNAL_ERROR", None).into()),
            _ => {}
        }
        let mut held = self
            .store
            .lock()
            .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
        let store = held
            .as_mut()
            .ok_or_else(|| Failure::new("WORKSPACE_CLOSED", None))?;
        let mut arbitration = None;
        let result = guarded(&AtomicU8::new(OPEN), || {
            let activated =
                bb_client::activate_legacy_review_with(store, &context, &prepared, |_| {
                    let lock = operation.state.lock().map_err(|_| StoreError::Corrupt)?;
                    if *lock == OperationState::Cancelled
                        || self.state.load(Ordering::Acquire) != OPEN
                    {
                        return Err(bb_client::LegacyReviewError::Cancelled);
                    }
                    arbitration = Some(lock);
                    Ok(())
                })
                .map_err(review_failure)?;
            if let Some(lock) = &mut arbitration {
                **lock = OperationState::Committed;
            }
            Ok(BridgeLegacyReviewActivated {
                projection_generation: activated.projection_generation.to_string(),
                already_active: activated.already_active,
                aliases: to_json(&activated.aliases)?,
            })
        });
        if result
            .as_ref()
            .is_err_and(|error| error.code == "INTERNAL_ERROR")
        {
            self.state
                .compare_exchange(OPEN, POISONED, Ordering::AcqRel, Ordering::Acquire)
                .ok();
        }
        Ok(result?)
    }

    pub fn records(
        &self,
        items: Vec<BridgeRecordRequest>,
    ) -> Result<BridgeWorkspaceAnswer, BridgeError> {
        let typed = items
            .iter()
            .map(|item| {
                Ok((
                    bb_protocol::catalog::EntityType::from_wire(&item.entity_type)
                        .ok_or_else(|| Failure::new("INVALID_REQUEST", Some("entity_type")))?,
                    parse_json::<bb_protocol::wire::RecordKey>(&item.record_key, "record_key")?,
                ))
            })
            .collect::<Result<Vec<_>, Failure>>()?;
        Ok(
            self.with_store(|store| match bb_client::workspace_records(store, &typed) {
                Ok((generation, records, task_frames)) => Ok(BridgeWorkspaceAnswer::Answered {
                    page: BridgeWorkspacePage {
                        projection_generation: generation.to_string(),
                        result: to_json(&serde_json::json!({"kind":"records","value":records}))?,
                        task_frames: to_json(&task_frames)?,
                        collection_next_cursor: None,
                    },
                }),
                Err(QueryError::Refused(error)) => Ok(BridgeWorkspaceAnswer::Refused {
                    refusal: error.into(),
                    projection_generation: None,
                }),
                Err(error) => Err(query_failure(error)),
            })?,
        )
    }

    pub fn resolve_identities(
        &self,
        items: Vec<BridgeIdentityRequest>,
    ) -> Result<Vec<BridgeIdentityBinding>, BridgeError> {
        let typed = items
            .iter()
            .map(|item| {
                Ok((
                    bb_protocol::catalog::EntityType::from_wire(&item.entity_type)
                        .ok_or_else(|| Failure::new("INVALID_REQUEST", Some("entity_type")))?,
                    item.local_id.clone(),
                ))
            })
            .collect::<Result<Vec<_>, Failure>>()?;
        Ok(self.with_store(|store| {
            let resolved = resolve_workspace_identities(store, &typed).map_err(query_failure)?;
            Ok(items
                .into_iter()
                .zip(resolved)
                .map(|(item, canonical_id)| BridgeIdentityBinding {
                    entity_type: item.entity_type,
                    local_id: item.local_id,
                    canonical_id,
                })
                .collect())
        })?)
    }

    pub fn sync_status(&self) -> Result<Vec<u8>, BridgeError> {
        Ok(self.with_store(|store| {
            to_json(&workspace_sync_status(store).map_err(|error| Failure::from(&error))?)
        })?)
    }

    pub fn workspace_issues(
        &self,
        limit: u32,
        after: Option<String>,
    ) -> Result<BridgeWorkspaceAnswer, BridgeError> {
        Ok(self.with_store(|store| {
            let page =
                workspace_issues_page(store, limit, after.as_deref()).map_err(query_failure)?;
            Ok(BridgeWorkspaceAnswer::Answered {
                page: BridgeWorkspacePage {
                    projection_generation: page.projection_generation.to_string(),
                    result: to_json(&serde_json::json!({"kind":"issues","value":page.items}))?,
                    task_frames: b"[]".to_vec(),
                    collection_next_cursor: page.next_cursor,
                },
            })
        })?)
    }

    /// Bootstrap/diagnostic only; ordinary screens use the bounded query port.
    pub fn snapshot(&self) -> Result<BridgeWorkspaceSnapshot, BridgeError> {
        Ok(self.with_store(|store| {
            let value = visible_snapshot(store).map_err(execute_failure)?;
            Ok(BridgeWorkspaceSnapshot {
                projection_generation: value.projection_generation.to_string(),
                records: to_json(&value.records)?,
                pending: value.pending.to_string(),
                open_issues: value.open_issues.to_string(),
            })
        })?)
    }

    pub fn subscribe(&self) -> Result<Arc<BridgeSubscription>, BridgeError> {
        Ok(self.with_store(|_| {
            let store = Store::open(&self.options).map_err(|error| Failure::from(&error))?;
            Ok(Arc::new(BridgeSubscription {
                workspace: self.state.clone(),
                store: Mutex::new(store),
                cancelled: Mutex::new(false),
                wake: Condvar::new(),
            }))
        })?)
    }

    /// Close prevents new calls; in-flight transactions settle or roll back
    /// before the handle is released. Saved commands are never removed.
    pub fn close(&self) -> Result<(), BridgeError> {
        self.state.store(CLOSED, Ordering::Release);
        let mut held = self
            .store
            .lock()
            .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
        if let Some(store) = held.take() {
            store.close().map_err(|error| Failure::from(&error))?;
        }
        Ok(())
    }
}

#[derive(uniffi::Object)]
pub struct BridgeSubscription {
    workspace: Arc<AtomicU8>,
    store: Mutex<Store>,
    cancelled: Mutex<bool>,
    wake: Condvar,
}

#[uniffi::export]
impl BridgeSubscription {
    pub fn cancel(&self) {
        if let Ok(mut cancelled) = self.cancelled.lock() {
            *cancelled = true;
        }
        self.wake.notify_all();
    }

    /// One coalesced invalidation, never a queue of full snapshots. Polling
    /// observes commits by neighboring app/widget processes too.
    pub fn next(
        &self,
        after: Option<String>,
        timeout_ms: u32,
    ) -> Result<Option<BridgeInvalidation>, BridgeError> {
        let previous: Option<WorkspaceWatch> = after
            .as_ref()
            .map(|token| parse_json(token.as_bytes(), "after"))
            .transpose()?;
        let until = Clock::now() + Duration::from_millis(u64::from(timeout_ms.min(60_000)));
        loop {
            if self.workspace.load(Ordering::Acquire) != OPEN {
                return Err(Failure::new("WORKSPACE_CLOSED", None).into());
            }
            let cancelled = self
                .cancelled
                .lock()
                .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
            if *cancelled {
                return Err(Failure::new("CANCELLED", None).into());
            }
            drop(cancelled);
            let current = {
                let mut store = self
                    .store
                    .lock()
                    .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
                workspace_watch(&mut store).map_err(|error| Failure::from(&error))?
            };
            if previous.as_ref() != Some(&current) {
                let cancelled = self
                    .cancelled
                    .lock()
                    .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
                if *cancelled || self.workspace.load(Ordering::Acquire) != OPEN {
                    return Err(Failure::new("CANCELLED", None).into());
                }
                let projection_changed = previous.as_ref().is_none_or(|value| {
                    value.projection_generation != current.projection_generation
                });
                let invalidation = BridgeInvalidation {
                    projection_generation: current.projection_generation.to_string(),
                    changed_kinds: if projection_changed {
                        vec![
                            "tasks".into(),
                            "projects".into(),
                            "tags".into(),
                            "review".into(),
                        ]
                    } else {
                        Vec::new()
                    },
                    sync_status_changed: previous
                        .as_ref()
                        .is_none_or(|value| value.status_token != current.status_token),
                    issues_changed: previous
                        .as_ref()
                        .is_none_or(|value| value.issues_token != current.issues_token),
                    pending: current.pending.to_string(),
                    open_issues: current.open_issues.to_string(),
                    token: String::from_utf8(to_json(&current)?)
                        .map_err(|_| Failure::new("INTERNAL_ERROR", None))?,
                };
                return Ok(Some(invalidation));
            }
            let remaining = until.saturating_duration_since(Clock::now());
            if remaining.is_zero() {
                return Ok(None);
            }
            let cancelled = self
                .cancelled
                .lock()
                .map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
            drop(
                self.wake
                    .wait_timeout(cancelled, remaining.min(Duration::from_millis(50)))
                    .map_err(|_| Failure::new("INTERNAL_ERROR", None))?,
            );
        }
    }
}

fn query_failure(error: QueryError) -> Failure {
    match error {
        QueryError::Store(error) => Failure::from(&error),
        QueryError::RestartRequired => Failure::new("QUERY_RESTART_REQUIRED", None),
        QueryError::Refused(_) | QueryError::RefusedAt { .. } => {
            Failure::new("INVALID_REQUEST", Some("query"))
        }
    }
}
