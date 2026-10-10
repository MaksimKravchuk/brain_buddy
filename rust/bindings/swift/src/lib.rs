//! UniFFI bridge from the Apple clients to the shared Rust core (spec 026, T005).
//!
//! The Swift module is `BrainBuddyRustBindings` (generated at build time by
//! `ios/scripts/build-rust-bridge.sh`, never committed); the hand-written, Foundation-only
//! facade over it is `BrainBuddyCore/BrainBuddyRustBridge.swift`. It mirrors the Python
//! bridge (`rust/bindings/python`) and its boundary rules (contracts/runtime-ffi.md):
//!
//! * every value crosses as an owned copy (`Vec<u8>`, `String`, records): Swift never
//!   holds a pointer into Rust memory;
//! * a panic never unwinds into Swift: it is contained, poisons the runtime and
//!   surfaces as `INTERNAL_ERROR`;
//! * failures are the typed [`BridgeError`] `(code, retryable, field)`; `field` is a
//!   static rule name and no error ever carries payload text;
//! * the runtime handle is bounded: `close` is final and idempotent, a call racing it
//!   reports `CANCELLED`, and a closed handle reports `WORKSPACE_CLOSED`.
//!
//! Since T017 the shared rule dispatch (`bb_domain::dispatch::decide_envelope` / `query`,
//! runtime-ffi.md "Pure core") is exported as [`BridgeRuntime::decide`] and
//! [`BridgeRuntime::query`], with the Smart Add draft reads
//! ([`BridgeRuntime::smart_add_resolve`], [`BridgeRuntime::smart_add_propose`]) the
//! capture sheet needs. All of them go through the same [`guarded`] seam and cross as
//! owned JSON bytes (read set, envelope, retained receipts and execution inputs in; a
//! typed outcome out), the shapes of the Python bridge. An expected domain refusal is
//! a value ([`BridgeDecision::Refused`], [`BridgeAnswer::Refused`] with a content-free
//! [`BridgeRefusal`]), never a [`BridgeError`].
//!
//! Since T041 the legacy import (`bb_client::import_legacy_store`, the move of the
//! Swift `StoreDocument` JSON file into the Rust store) is exported as
//! [`BridgeRuntime::import_legacy_store`] through the same [`guarded`] seam. It crosses
//! as owned records (paths, an instant, counts) and fails as a [`BridgeError`] whose
//! `code` is the import's own (`IMPORT_*`, `STORE_*`) and whose `field` names a section
//! or check, never content. Only the Swift facade imports the generated module.
//!
//! Since T042 [`BridgeRuntime::resolve_legacy_outbox`] classifies the pending sends and issues
//! that import carried. The Swift side passes the receipt answers it already fetched (by
//! idempotency key); the lookup itself is a port in `bb-client`, so no callback crosses.

use std::cell::Cell;
use std::panic::{self, AssertUnwindSafe};
use std::path::PathBuf;
use std::sync::Once;
use std::sync::atomic::{AtomicU8, Ordering};
use std::time::Duration;

use bb_client::{
    ImportError, ImportReport, ImportRequest, LegacyAnswer, LegacyOutboxError, LegacyOutboxStatus,
    OpenOptions, ProvenAlias, ProvidedReceipts, SourceCounts, Store, import_legacy_store,
    legacy_outbox_sends, resolve_legacy_outbox,
};
use bb_domain::dispatch;
use bb_domain::smart_add::{self, Classification, Draft, Resolution, TokenKind};
use bb_domain::types::{
    DomainError, DueDay, ExecutionInputs, OpenList, Priority, ProjectId, Query, QueryInputs,
    ReadSet, TagId,
};
use bb_protocol::catalog::EntityType;
use bb_protocol::command::{self, Decoded, Unsupported};
use bb_protocol::receipt::Receipt;
use bb_protocol::wire::{CodecError, Instant, PROTOCOL_VERSION};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};

uniffi::setup_scaffolding!();

const OPEN: u8 = 0;
const CLOSED: u8 = 1;
const POISONED: u8 = 2;

/// A content-free failure: a stable code, retryability and a static field name.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Error)]
pub enum BridgeError {
    Failed {
        code: String,
        retryable: bool,
        field: Option<String>,
    },
}

impl std::fmt::Display for BridgeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let Self::Failed { code, .. } = self;
        write!(f, "bridge failure {code}")
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Failure {
    code: &'static str,
    retryable: bool,
    field: Option<&'static str>,
}

impl Failure {
    const fn new(code: &'static str, field: Option<&'static str>) -> Self {
        Self {
            code,
            retryable: false,
            field,
        }
    }
}

impl From<CodecError> for Failure {
    fn from(error: CodecError) -> Self {
        // `Malformed` carries a parser position and `DuplicateKey` nothing: the
        // position is dropped so no input-derived detail crosses the boundary.
        let field = match error {
            CodecError::Invalid(rule) => Some(rule),
            CodecError::Malformed { .. } | CodecError::DuplicateKey => None,
        };
        Self::new(error.code(), field)
    }
}

impl From<Failure> for BridgeError {
    fn from(failure: Failure) -> Self {
        Self::Failed {
            code: failure.code.to_owned(),
            retryable: failure.retryable,
            field: failure.field.map(str::to_owned),
        }
    }
}

thread_local! {
    static IN_BRIDGE: Cell<bool> = const { Cell::new(false) };
}

/// Silences the default panic report for panics raised inside a bridge call.
///
/// The report prints the panic message, which could embed input text, to stderr.
/// Panics elsewhere in the process still reach the previously installed hook.
fn install_quiet_panic_hook() {
    static INSTALL: Once = Once::new();
    INSTALL.call_once(|| {
        let previous = panic::take_hook();
        panic::set_hook(Box::new(move |info| {
            if !IN_BRIDGE.with(Cell::get) {
                previous(info);
            }
        }));
    });
}

/// Run one pure call against the runtime state.
///
/// A panic is contained, poisons an open runtime and surfaces as `INTERNAL_ERROR`.
/// A `close` that lands while the call runs discards its result as `CANCELLED`;
/// close always wins over poisoning.
fn guarded<T>(state: &AtomicU8, work: impl FnOnce() -> Result<T, Failure>) -> Result<T, Failure> {
    match state.load(Ordering::Acquire) {
        CLOSED => return Err(Failure::new("WORKSPACE_CLOSED", None)),
        POISONED => return Err(Failure::new("INTERNAL_ERROR", None)),
        _ => {}
    }
    install_quiet_panic_hook();
    IN_BRIDGE.with(|flag| flag.set(true));
    let outcome = panic::catch_unwind(AssertUnwindSafe(work));
    IN_BRIDGE.with(|flag| flag.set(false));
    let outcome = outcome.unwrap_or_else(|payload| {
        // The payload may hold input text; it is dropped here, never inspected.
        drop(payload);
        let _ = state.compare_exchange(OPEN, POISONED, Ordering::AcqRel, Ordering::Acquire);
        Err(Failure::new("INTERNAL_ERROR", None))
    });
    // A concurrent call that panicked poisons the runtime for every call still in
    // flight: none of them may report success from an unusable runtime.
    match state.load(Ordering::Acquire) {
        CLOSED => Err(Failure::new("CANCELLED", None)),
        POISONED => Err(Failure::new("INTERNAL_ERROR", None)),
        _ => outcome,
    }
}

/// A decoded command envelope; every value is owned by this record.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct BridgeCommand {
    pub protocol_version: u32,
    pub command_id: String,
    pub scope_id: String,
    pub device_id: String,
    /// Decimal string: counters can exceed what JSON numbers (and `Double`) hold exactly.
    pub local_sequence: String,
    pub command_type: String,
    pub command_version: u32,
    pub entity_id: String,
    /// True when this build can execute the command; otherwise it is the stable
    /// recovery form and `unsupported_reason` says why (maps to `UPGRADE_REQUIRED`).
    pub executable: bool,
    pub unsupported_reason: Option<String>,
    /// The stable envelope as wire bytes; omitted optional fields stay omitted.
    pub wire: Vec<u8>,
}

fn unsupported_reason(reason: &Unsupported) -> &'static str {
    match reason {
        Unsupported::ProtocolVersion => "protocol_version",
        Unsupported::CommandType => "command_type",
        Unsupported::CommandVersion => "command_version",
    }
}

/// Decode one command from wire bytes into owned values.
fn decode_command(data: &[u8]) -> Result<BridgeCommand, Failure> {
    let json = std::str::from_utf8(data).map_err(|_| Failure::new("INVALID_REQUEST", None))?;
    let (stable, executable, reason) = match command::decode_command(json)? {
        Decoded::Executable(command) => (command.envelope, true, None),
        Decoded::Unsupported { reason, envelope } => {
            (envelope, false, Some(unsupported_reason(&reason)))
        }
    };
    let wire = serde_json::to_vec(&stable).map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
    Ok(BridgeCommand {
        protocol_version: stable.protocol_version,
        command_id: stable.command_id.as_str().to_owned(),
        scope_id: stable.scope_id.as_str().to_owned(),
        device_id: stable.device_id.as_str().to_owned(),
        local_sequence: stable.local_sequence.as_str().to_owned(),
        command_type: stable.command_type.clone(),
        command_version: stable.command_version,
        entity_id: stable.entity_id.as_str().to_owned(),
        executable,
        unsupported_reason: reason.map(str::to_owned),
        wire,
    })
}

/// A typed domain refusal: a canonical reason and, at most, the field or record it
/// concerns. Never user text (026-FR-022).
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct BridgeRefusal {
    /// The wire spelling of `bb_domain::types::Reason`.
    pub reason: String,
    /// The request field or payload key concerned.
    pub field: Option<String>,
    /// The record type of `entity_key` (`task`, `project`, ...).
    pub entity_type: Option<String>,
    /// The key components of the record concerned; empty when none.
    pub entity_key: Vec<String>,
    /// The revision a stale check saw, as a decimal string.
    pub current_revision: Option<String>,
}

impl From<DomainError> for BridgeRefusal {
    fn from(error: DomainError) -> Self {
        let (entity_type, entity_key) = match error.entity {
            Some((entity_type, key)) => (Some(entity_type.as_str().to_owned()), key),
            None => (None, Vec::new()),
        };
        Self {
            reason: error.reason.as_str().to_owned(),
            field: error.field,
            entity_type,
            entity_key,
            current_revision: error
                .current_revision
                .map(|revision| revision.as_str().to_owned()),
        }
    }
}

/// What `decide` returns: the change set (JSON bytes) or a typed refusal.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Enum)]
pub enum BridgeDecision {
    Changed { change_set: Vec<u8> },
    Refused { refusal: BridgeRefusal },
}

/// What `query` and the Smart Add reads return: the result (JSON bytes) or a typed
/// refusal.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Enum)]
pub enum BridgeAnswer {
    Answered { result: Vec<u8> },
    Refused { refusal: BridgeRefusal },
}

/// Parses one JSON input; the failure names the argument, never its content.
fn parse_json<T: DeserializeOwned>(data: &[u8], field: &'static str) -> Result<T, Failure> {
    serde_json::from_slice(data).map_err(|_| Failure::new("INVALID_REQUEST", Some(field)))
}

fn to_json<T: Serialize>(value: &T) -> Result<Vec<u8>, Failure> {
    serde_json::to_vec(value).map_err(|_| Failure::new("INTERNAL_ERROR", None))
}

/// Decide one executable command envelope against an owned read set.
fn decide_envelope(
    read_set: &[u8],
    envelope: &[u8],
    receipts: &[u8],
    inputs: &[u8],
) -> Result<BridgeDecision, Failure> {
    let read_set: ReadSet = parse_json(read_set, "read_set")?;
    let receipts: Vec<Receipt> = parse_json(receipts, "receipts")?;
    let inputs: ExecutionInputs = parse_json(inputs, "execution_inputs")?;
    let json = std::str::from_utf8(envelope).map_err(|_| Failure::new("INVALID_REQUEST", None))?;
    let envelope = match command::decode_command(json)? {
        Decoded::Executable(envelope) => envelope,
        Decoded::Unsupported { .. } => {
            return Err(Failure::new("UPGRADE_REQUIRED", Some("command_type")));
        }
    };
    Ok(
        match dispatch::decide_envelope(&read_set, &envelope, receipts.as_slice(), &inputs) {
            Ok(change_set) => BridgeDecision::Changed {
                change_set: to_json(&change_set)?,
            },
            Err(error) => BridgeDecision::Refused {
                refusal: error.into(),
            },
        },
    )
}

/// Answer one query over an owned read set.
fn answer_query(read_set: &[u8], query: &[u8], inputs: &[u8]) -> Result<BridgeAnswer, Failure> {
    let read_set: ReadSet = parse_json(read_set, "read_set")?;
    let query: Query = parse_json(query, "query")?;
    let inputs: QueryInputs = parse_json(inputs, "query_inputs")?;
    Ok(match dispatch::query(&read_set, &query, &inputs) {
        Ok(result) => BridgeAnswer::Answered {
            result: to_json(&result)?,
        },
        Err(error) => BridgeAnswer::Refused {
            refusal: error.into(),
        },
    })
}

fn no_priority() -> Priority {
    Priority::None
}

/// What the capture sheet holds (`bb_domain::smart_add::Draft`); every field but the
/// text and the list is optional on the wire.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DraftInput {
    text: String,
    list: OpenList,
    #[serde(default)]
    waiting_for: String,
    #[serde(default)]
    details: String,
    #[serde(default)]
    due_date: Option<DueDay>,
    #[serde(default = "no_priority")]
    priority: Priority,
    #[serde(default)]
    context_project: Option<ProjectId>,
    #[serde(default)]
    context_tag: Option<TagId>,
}

impl From<DraftInput> for Draft {
    fn from(input: DraftInput) -> Self {
        Self {
            text: input.text,
            list: input.list,
            waiting_for: input.waiting_for,
            details: input.details,
            due_date: input.due_date,
            priority: input.priority,
            context_project: input.context_project,
            context_tag: input.context_tag,
        }
    }
}

/// The IDs the caller minted for the records a draft would create: the project (when
/// the draft names a new one) and one tag ID per new tag, in token order.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct MintedIds {
    #[serde(default)]
    project: Option<ProjectId>,
    #[serde(default)]
    tags: Vec<TagId>,
}

fn classification_json<I>(value: &Classification<I>, id: impl Fn(&I) -> &str) -> serde_json::Value {
    match value {
        Classification::Existing { id: found, name } => {
            serde_json::json!({"type": "existing", "id": id(found), "name": name})
        }
        Classification::New { name } => serde_json::json!({"type": "new", "name": name}),
    }
}

/// The preview of a draft as JSON: the clean title, the tokens to highlight, the
/// project and tags capture would use or create, and the first problem.
fn resolution_json(resolution: &Resolution) -> serde_json::Value {
    let tokens: Vec<_> = resolution
        .tokens
        .iter()
        .map(|token| {
            serde_json::json!({
                "kind": match token.kind {
                    TokenKind::Project => "project",
                    TokenKind::Tag => "tag",
                },
                "utf16_start": token.utf16_start,
                "utf16_end": token.utf16_end,
                "name": token.name,
            })
        })
        .collect();
    serde_json::json!({
        "title": resolution.title,
        "tokens": tokens,
        "project": resolution
            .project
            .as_ref()
            .map(|project| classification_json(project, ProjectId::as_str)),
        "tags": resolution
            .tags
            .iter()
            .map(|tag| classification_json(tag, TagId::as_str))
            .collect::<Vec<_>>(),
        "waiting_for": resolution.waiting_for,
        "details": resolution.details,
        "problem": resolution.problem,
    })
}

/// Resolve a draft against an owned read set, as capture would right now.
fn resolve_smart_add(read_set: &[u8], draft: &[u8]) -> Result<Vec<u8>, Failure> {
    let read_set: ReadSet = parse_json(read_set, "read_set")?;
    let draft: Draft = parse_json::<DraftInput>(draft, "draft")?.into();
    to_json(&resolution_json(&smart_add::resolve(&read_set, &draft)))
}

/// The `task.smart_add` payload capture would send, or the draft's first problem.
fn propose_smart_add(
    read_set: &[u8],
    draft: &[u8],
    minted: &[u8],
) -> Result<BridgeAnswer, Failure> {
    let read_set: ReadSet = parse_json(read_set, "read_set")?;
    let draft: Draft = parse_json::<DraftInput>(draft, "draft")?.into();
    let minted: MintedIds = parse_json(minted, "minted_ids")?;
    let resolution = smart_add::resolve(&read_set, &draft);
    if resolution.problem.is_none() {
        // `propose` mints lazily and cannot fail on a short supply, so it is checked here.
        let new_project = resolution
            .project
            .as_ref()
            .is_some_and(Classification::is_new);
        let new_tags = resolution.tags.iter().filter(|tag| tag.is_new()).count();
        if (new_project && minted.project.is_none()) || minted.tags.len() < new_tags {
            return Err(Failure::new("INVALID_REQUEST", Some("minted_ids")));
        }
    }
    let spare_project =
        ProjectId::parse("unused").map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
    let spare_tag = TagId::parse("unused").map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
    let mut project = minted.project;
    let mut tags = minted.tags.into_iter();
    let proposal = smart_add::propose(
        &read_set,
        &draft,
        || project.take().unwrap_or_else(|| spare_project.clone()),
        || tags.next().unwrap_or_else(|| spare_tag.clone()),
    );
    Ok(match proposal {
        Ok(payload) => BridgeAnswer::Answered {
            result: to_json(&payload)?,
        },
        Err(error) => BridgeAnswer::Refused {
            refusal: error.into(),
        },
    })
}

/// What the legacy file held, counted by the means any reader of the file has. The Swift
/// importer counts the same file with its own decoder and passes the result in, so the two
/// readers must agree before anything is switched (`SourceCounts` in `bb-client`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, uniffi::Record)]
pub struct BridgeImportCounts {
    pub tasks: u64,
    pub subtasks: u64,
    pub comments: u64,
    pub projects: u64,
    pub tags: u64,
    pub outbox_entries: u64,
    pub issues: u64,
    pub review_sessions: u64,
    pub review_decisions: u64,
    pub review_receipts: u64,
    pub review_park_acks: u64,
    pub review_bulk_releases: u64,
    pub review_navigator_consents: u64,
    pub form_drafts: u64,
}

impl From<BridgeImportCounts> for SourceCounts {
    fn from(counts: BridgeImportCounts) -> Self {
        Self {
            tasks: counts.tasks,
            subtasks: counts.subtasks,
            comments: counts.comments,
            projects: counts.projects,
            tags: counts.tags,
            outbox_entries: counts.outbox_entries,
            issues: counts.issues,
            review_sessions: counts.review_sessions,
            review_decisions: counts.review_decisions,
            review_receipts: counts.review_receipts,
            review_park_acks: counts.review_park_acks,
            review_bulk_releases: counts.review_bulk_releases,
            review_navigator_consents: counts.review_navigator_consents,
            form_drafts: counts.form_drafts,
        }
    }
}

impl From<SourceCounts> for BridgeImportCounts {
    fn from(counts: SourceCounts) -> Self {
        Self {
            tasks: counts.tasks,
            subtasks: counts.subtasks,
            comments: counts.comments,
            projects: counts.projects,
            tags: counts.tags,
            outbox_entries: counts.outbox_entries,
            issues: counts.issues,
            review_sessions: counts.review_sessions,
            review_decisions: counts.review_decisions,
            review_receipts: counts.review_receipts,
            review_park_acks: counts.review_park_acks,
            review_bulk_releases: counts.review_bulk_releases,
            review_navigator_consents: counts.review_navigator_consents,
            form_drafts: counts.form_drafts,
        }
    }
}

/// The import of the legacy `StoreDocument` file into the Rust store of one workspace.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct BridgeImportRequest {
    pub workspace_id: String,
    /// The Rust store file. Created when it does not exist.
    pub database_path: String,
    /// The legacy JSON file. It is only read.
    pub source_path: String,
    /// Where the backup and the schema manifest go; beside the source when absent.
    pub backup_directory: Option<String>,
    /// The instant of the import (RFC 3339).
    pub now: String,
    /// The bound on every lock wait; running out is a retryable `STORE_BUSY`.
    pub busy_timeout_ms: u32,
    /// The counts an independent reader took from the same file.
    pub expected: Option<BridgeImportCounts>,
}

/// The activation marker of a finished import.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct BridgeImportReport {
    /// The same file had already been imported: nothing was done.
    pub already_active: bool,
    pub source_sha256: String,
    pub source_bytes: u64,
    pub source_version: i64,
    pub source_generation: i64,
    /// File names, beside the source (or in the requested directory).
    pub backup_file: String,
    pub manifest_file: String,
    pub imported_at: String,
    pub counts: BridgeImportCounts,
    /// Identity aliases written (a server ID the file proved for a local ID).
    pub aliases: u64,
    /// Tasks whose local-only facts were kept.
    pub local_task_facts: u64,
}

impl From<ImportReport> for BridgeImportReport {
    fn from(report: ImportReport) -> Self {
        let marker = report.marker;
        Self {
            already_active: report.already_active,
            source_sha256: marker.source_sha256,
            source_bytes: marker.source_bytes,
            source_version: marker.source_version,
            source_generation: marker.source_generation,
            backup_file: marker.backup_file,
            manifest_file: marker.manifest_file,
            imported_at: marker.imported_at,
            counts: marker.counts.into(),
            aliases: marker.aliases,
            local_task_facts: marker.local_task_facts,
        }
    }
}

impl From<&ImportError> for Failure {
    fn from(error: &ImportError) -> Self {
        Self {
            code: error.code(),
            retryable: error.is_retryable(),
            field: error.field(),
        }
    }
}

/// Runs the import for one request. A request that cannot be read fails as
/// `INVALID_REQUEST` naming the argument; the import's own failures keep their codes.
fn run_import(request: &BridgeImportRequest) -> Result<BridgeImportReport, Failure> {
    let now = Instant::parse(request.now.as_str())
        .map_err(|_| Failure::new("INVALID_REQUEST", Some("now")))?;
    if request.workspace_id.is_empty() {
        return Err(Failure::new("INVALID_REQUEST", Some("workspace_id")));
    }
    let request = ImportRequest {
        store: OpenOptions {
            path: PathBuf::from(&request.database_path),
            workspace_id: request.workspace_id.clone(),
            busy_timeout: Duration::from_millis(u64::from(request.busy_timeout_ms)),
        },
        source: PathBuf::from(&request.source_path),
        backup_dir: request.backup_directory.as_ref().map(PathBuf::from),
        now,
        expected: request.expected.map(SourceCounts::from),
    };
    import_legacy_store(&request)
        .map(BridgeImportReport::from)
        .map_err(|error| Failure::from(&error))
}

/// A server ID a retained receipt proved for a local ID of an old command.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct BridgeLegacyAlias {
    /// The wire name of the entity type (`task`, `project`, ...).
    pub entity_type: String,
    pub old_local_id: String,
    pub server_id: String,
}

/// What the server can prove about one old send (`LegacyAnswer` in `bb-client`).
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Enum)]
pub enum BridgeLegacyAnswer {
    Accepted {
        aliases: Vec<BridgeLegacyAlias>,
    },
    Rejected {
        code: String,
    },
    /// No receipt, one still pending, or no answer at all: never proof either way.
    Unproven,
}

/// The answer already fetched for one `Idempotency-Key`, matched by key alone.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct BridgeLegacyReceipt {
    pub idempotency_key: String,
    pub answer: BridgeLegacyAnswer,
}

/// The classification of the outbox a legacy import carried (spec 026 T042).
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct BridgeLegacyOutboxRequest {
    pub workspace_id: String,
    pub database_path: String,
    /// The instant of the classification (RFC 3339): the 24-hour window ends against it.
    pub now: String,
    pub busy_timeout_ms: u32,
    pub receipts: Vec<BridgeLegacyReceipt>,
}

/// Where the legacy outbox stands. Counts only; no user text.
#[derive(Debug, Clone, Copy, PartialEq, Eq, uniffi::Record)]
pub struct BridgeLegacyOutboxStatus {
    pub carried: u64,
    pub unsent: u64,
    pub accepted: u64,
    pub rejected: u64,
    pub awaiting: u64,
    pub uncertain: u64,
    pub carried_issues: u64,
    pub converted_issues: u64,
    pub open_issues: u64,
    pub aliases: u64,
    pub classified: bool,
    pub may_run: bool,
    pub fully_synced: bool,
}

impl From<LegacyOutboxStatus> for BridgeLegacyOutboxStatus {
    fn from(status: LegacyOutboxStatus) -> Self {
        Self {
            carried: status.carried,
            unsent: status.unsent,
            accepted: status.accepted,
            rejected: status.rejected,
            awaiting: status.awaiting,
            uncertain: status.uncertain,
            carried_issues: status.carried_issues,
            converted_issues: status.converted_issues,
            open_issues: status.open_issues,
            aliases: status.aliases,
            classified: status.classified(),
            may_run: status.may_run(),
            fully_synced: status.fully_synced(),
        }
    }
}

impl From<&LegacyOutboxError> for Failure {
    fn from(error: &LegacyOutboxError) -> Self {
        Self {
            code: error.code(),
            retryable: error.is_retryable(),
            field: error.field(),
        }
    }
}

fn legacy_answer(answer: &BridgeLegacyAnswer) -> Result<LegacyAnswer, Failure> {
    Ok(match answer {
        BridgeLegacyAnswer::Accepted { aliases } => LegacyAnswer::Accepted {
            aliases: aliases
                .iter()
                .map(|alias| {
                    Ok(ProvenAlias {
                        entity_type: EntityType::from_wire(&alias.entity_type)
                            .ok_or(Failure::new("INVALID_REQUEST", Some("entity_type")))?,
                        old_local_id: alias.old_local_id.clone(),
                        server_id: alias.server_id.clone(),
                    })
                })
                .collect::<Result<_, Failure>>()?,
        },
        BridgeLegacyAnswer::Rejected { code } => LegacyAnswer::Rejected { code: code.clone() },
        BridgeLegacyAnswer::Unproven => LegacyAnswer::Unproven,
    })
}

/// Classifies the legacy outbox for one request. A request that cannot be read fails as
/// `INVALID_REQUEST` naming the argument; the classification's own failures keep their codes.
fn run_legacy_outbox(
    request: &BridgeLegacyOutboxRequest,
) -> Result<BridgeLegacyOutboxStatus, Failure> {
    let now = Instant::parse(request.now.as_str())
        .map_err(|_| Failure::new("INVALID_REQUEST", Some("now")))?;
    let mut receipts = ProvidedReceipts::default();
    for receipt in &request.receipts {
        receipts.insert(&receipt.idempotency_key, legacy_answer(&receipt.answer)?);
    }
    let mut store = open_outbox_store(request)?;
    resolve_legacy_outbox(&mut store, &mut receipts, &now)
        .map(BridgeLegacyOutboxStatus::from)
        .map_err(|error| Failure::from(&error))
}

fn open_outbox_store(request: &BridgeLegacyOutboxRequest) -> Result<Store, Failure> {
    if request.workspace_id.is_empty() {
        return Err(Failure::new("INVALID_REQUEST", Some("workspace_id")));
    }
    Store::open(&OpenOptions {
        path: PathBuf::from(&request.database_path),
        workspace_id: request.workspace_id.clone(),
        busy_timeout: Duration::from_millis(u64::from(request.busy_timeout_ms)),
    })
    .map_err(|error| Failure::from(&LegacyOutboxError::Store(error)))
}

/// One old send to ask the server about, by the key it was made with.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct BridgeLegacySend {
    pub entry_id: String,
    pub idempotency_key: String,
    /// The old command as the legacy file held it, JSON bytes.
    pub command: Vec<u8>,
}

/// The sends still to look up, read from the Rust store (`receipts` and `now` are not read).
fn run_legacy_sends(request: &BridgeLegacyOutboxRequest) -> Result<Vec<BridgeLegacySend>, Failure> {
    let mut store = open_outbox_store(request)?;
    legacy_outbox_sends(&mut store)
        .map_err(|error| Failure::from(&error))?
        .into_iter()
        .map(|send| {
            Ok(BridgeLegacySend {
                entry_id: send.entry_id,
                idempotency_key: send.idempotency_key,
                command: to_json(&send.command)?,
            })
        })
        .collect()
}

/// One bridge runtime handle. `close` is idempotent and final.
#[derive(uniffi::Object)]
pub struct BridgeRuntime {
    state: AtomicU8,
}

impl BridgeRuntime {
    fn try_new(protocol_version: u32) -> Result<Self, Failure> {
        if protocol_version != PROTOCOL_VERSION {
            return Err(Failure::new("UPGRADE_REQUIRED", Some("protocol_version")));
        }
        Ok(Self {
            state: AtomicU8::new(OPEN),
        })
    }
}

#[uniffi::export]
impl BridgeRuntime {
    /// Open a runtime for the given sync protocol version.
    #[uniffi::constructor]
    pub fn new(protocol_version: u32) -> Result<Self, BridgeError> {
        Ok(Self::try_new(protocol_version)?)
    }

    /// Close the runtime. Idempotent; calls in flight report `CANCELLED`.
    pub fn close(&self) {
        self.state.store(CLOSED, Ordering::Release);
    }

    pub fn is_open(&self) -> bool {
        self.state.load(Ordering::Acquire) == OPEN
    }

    /// Decode and validate one command envelope (sync-v1 section 3).
    pub fn decode_command(&self, data: Vec<u8>) -> Result<BridgeCommand, BridgeError> {
        Ok(guarded(&self.state, || decode_command(&data))?)
    }

    /// Decide one command envelope (runtime-ffi.md "Pure core"): JSON bytes in, the
    /// change set as JSON bytes or a typed refusal out. The call works on copies of
    /// every argument and shares nothing with the caller.
    pub fn decide(
        &self,
        read_set: Vec<u8>,
        envelope: Vec<u8>,
        receipts: Vec<u8>,
        inputs: Vec<u8>,
    ) -> Result<BridgeDecision, BridgeError> {
        Ok(guarded(&self.state, || {
            decide_envelope(&read_set, &envelope, &receipts, &inputs)
        })?)
    }

    /// Answer one query: JSON bytes in, the result as JSON bytes or a typed refusal out.
    pub fn query(
        &self,
        read_set: Vec<u8>,
        query: Vec<u8>,
        inputs: Vec<u8>,
    ) -> Result<BridgeAnswer, BridgeError> {
        Ok(guarded(&self.state, || {
            answer_query(&read_set, &query, &inputs)
        })?)
    }

    /// Import the legacy `StoreDocument` file into the Rust store (spec 026 T041). The
    /// source is backed up and only read; the store switches in one transaction after the
    /// imported rows were checked against it, or not at all. Blocking disk work: call it
    /// off the main actor.
    pub fn import_legacy_store(
        &self,
        request: BridgeImportRequest,
    ) -> Result<BridgeImportReport, BridgeError> {
        Ok(guarded(&self.state, || run_import(&request))?)
    }

    /// The old sends a receipt lookup is still needed for, read from the Rust store (spec 026
    /// T042). Only `workspace_id`, `database_path` and `busy_timeout_ms` of the request are read.
    pub fn legacy_outbox_sends(
        &self,
        request: BridgeLegacyOutboxRequest,
    ) -> Result<Vec<BridgeLegacySend>, BridgeError> {
        Ok(guarded(&self.state, || run_legacy_sends(&request))?)
    }

    /// Classify the outbox and issues a legacy import carried (spec 026 T042): a send a receipt
    /// proves is settled, one that may have reached the server stays an issue and is never
    /// reissued. One transaction, or nothing. Blocking disk work: call it off the main actor.
    pub fn resolve_legacy_outbox(
        &self,
        request: BridgeLegacyOutboxRequest,
    ) -> Result<BridgeLegacyOutboxStatus, BridgeError> {
        Ok(guarded(&self.state, || run_legacy_outbox(&request))?)
    }

    /// Resolve a Smart Add draft (the capture sheet's preview) against an owned read set.
    pub fn smart_add_resolve(
        &self,
        read_set: Vec<u8>,
        draft: Vec<u8>,
    ) -> Result<Vec<u8>, BridgeError> {
        Ok(guarded(&self.state, || {
            resolve_smart_add(&read_set, &draft)
        })?)
    }

    /// The `task.smart_add` payload a draft would send, given the IDs minted for the
    /// records it creates; a blocked draft is a typed refusal.
    pub fn smart_add_propose(
        &self,
        read_set: Vec<u8>,
        draft: Vec<u8>,
        minted: Vec<u8>,
    ) -> Result<BridgeAnswer, BridgeError> {
        Ok(guarded(&self.state, || {
            propose_smart_add(&read_set, &draft, &minted)
        })?)
    }
}

/// The sync protocol version this build speaks.
#[uniffi::export]
pub fn bridge_protocol_version() -> u32 {
    PROTOCOL_VERSION
}

#[cfg(test)]
mod bridge_tests {
    use super::*;

    const COMMAND: &str = r#"{
        "protocol_version": 1,
        "command_id": "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11",
        "scope_id": "scope-1",
        "device_id": "device-1",
        "device_epoch": "epoch-1",
        "local_sequence": "9007199254740993",
        "type": "task.create",
        "command_version": 1,
        "entity_id": "task-1",
        "preconditions": [],
        "depends_on": [],
        "issued_at": "2026-10-09T12:00:00Z",
        "payload": {"title": "Buy milk"}
    }"#;

    fn failed(error: BridgeError) -> (String, bool, Option<String>) {
        let BridgeError::Failed {
            code,
            retryable,
            field,
        } = error;
        (code, retryable, field)
    }

    #[test]
    fn bridge_026_fr_025_contains_panic_and_poisons_runtime() {
        let state = AtomicU8::new(OPEN);
        let panicked: Result<(), _> = guarded(&state, || panic!("payload must not leak"));
        assert_eq!(panicked, Err(Failure::new("INTERNAL_ERROR", None)));
        assert_eq!(state.load(Ordering::Acquire), POISONED);
        assert_eq!(
            guarded(&state, || Ok(1)),
            Err(Failure::new("INTERNAL_ERROR", None))
        );
        assert!(!IN_BRIDGE.with(Cell::get));
    }

    #[test]
    fn bridge_026_fr_025_rejects_calls_after_close_and_cancels_in_flight() {
        let state = AtomicU8::new(CLOSED);
        assert_eq!(
            guarded(&state, || Ok(())),
            Err(Failure::new("WORKSPACE_CLOSED", None))
        );
        let state = AtomicU8::new(OPEN);
        let result = guarded(&state, || {
            state.store(CLOSED, Ordering::Release);
            Ok(7)
        });
        assert_eq!(result, Err(Failure::new("CANCELLED", None)));
        let state = AtomicU8::new(OPEN);
        let result: Result<(), _> = guarded(&state, || {
            state.store(CLOSED, Ordering::Release);
            panic!("late");
        });
        assert_eq!(result, Err(Failure::new("CANCELLED", None)));
        assert_eq!(state.load(Ordering::Acquire), CLOSED);
    }

    #[test]
    fn bridge_026_fr_025_poisoning_mid_flight_fails_a_concurrent_success() {
        let state = AtomicU8::new(OPEN);
        let result = guarded(&state, || {
            state.store(POISONED, Ordering::Release);
            Ok(7)
        });
        assert_eq!(result, Err(Failure::new("INTERNAL_ERROR", None)));
    }

    #[test]
    fn bridge_026_fr_025_a_panic_in_dispatch_poisons_the_runtime_for_every_call() {
        let runtime = BridgeRuntime::new(PROTOCOL_VERSION).expect("opens");
        let panicked: Result<(), _> = guarded(&runtime.state, || {
            let _ = decide_envelope(b"{}", b"{}", b"{}", b"{}");
            panic!("payload must not leak")
        });
        assert_eq!(panicked, Err(Failure::new("INTERNAL_ERROR", None)));
        assert!(!runtime.is_open());
        let codes = [
            runtime
                .decide(b"{}".into(), b"{}".into(), b"[]".into(), b"{}".into())
                .map(|_| ()),
            runtime
                .query(b"{}".into(), b"{}".into(), b"{}".into())
                .map(|_| ()),
            runtime
                .smart_add_resolve(b"{}".into(), b"{}".into())
                .map(|_| ()),
            runtime
                .smart_add_propose(b"{}".into(), b"{}".into(), b"{}".into())
                .map(|_| ()),
        ]
        .map(|outcome| failed(outcome.expect_err("poisoned")).0);
        assert!(
            codes.iter().all(|code| code == "INTERNAL_ERROR"),
            "{codes:?}"
        );
    }

    #[test]
    fn bridge_026_fr_025_a_close_during_dispatch_cancels_instead_of_returning_a_result() {
        let runtime = BridgeRuntime::new(PROTOCOL_VERSION).expect("opens");
        let result = guarded(&runtime.state, || {
            runtime.close();
            Ok(BridgeAnswer::Answered { result: Vec::new() })
        });
        assert_eq!(result, Err(Failure::new("CANCELLED", None)));
    }

    #[test]
    fn bridge_026_fr_002_converts_a_domain_error_into_a_content_free_refusal() {
        let refusal = BridgeRefusal::from(DomainError::stale(
            bb_domain::types::EntityType::Task,
            vec!["task-1".to_owned()],
            bb_domain::types::Counter::from(4_u64),
        ));
        assert_eq!(
            refusal,
            BridgeRefusal {
                reason: "revision_conflict".to_owned(),
                field: None,
                entity_type: Some("task".to_owned()),
                entity_key: vec!["task-1".to_owned()],
                current_revision: Some("4".to_owned()),
            }
        );
        let plain = BridgeRefusal::from(DomainError::new(bb_domain::types::Reason::EmptyTitle));
        assert_eq!(plain.entity_type, None);
        assert!(plain.entity_key.is_empty());
    }

    #[test]
    fn bridge_026_fr_025_repeated_open_close_cycles_are_final_and_idempotent() {
        for _ in 0..50 {
            let runtime = BridgeRuntime::new(PROTOCOL_VERSION).expect("opens");
            assert!(runtime.is_open());
            runtime.close();
            runtime.close();
            assert!(!runtime.is_open());
            let error = runtime.decode_command(COMMAND.into()).expect_err("closed");
            assert_eq!(failed(error).0, "WORKSPACE_CLOSED");
        }
    }

    #[test]
    fn bridge_026_fr_025_shares_one_handle_across_threads() {
        let runtime = std::sync::Arc::new(BridgeRuntime::new(PROTOCOL_VERSION).expect("opens"));
        let workers: Vec<_> = (0..8)
            .map(|_| {
                let runtime = std::sync::Arc::clone(&runtime);
                std::thread::spawn(move || {
                    (0..50).all(|_| {
                        runtime
                            .decode_command(COMMAND.into())
                            .is_ok_and(|command| command.executable)
                    })
                })
            })
            .collect();
        for worker in workers {
            assert!(worker.join().expect("worker finished"));
        }
        runtime.close();
        assert!(!runtime.is_open());
    }

    #[test]
    fn bridge_026_fr_002_refuses_an_unsupported_protocol_version() {
        let error = BridgeRuntime::new(PROTOCOL_VERSION + 1)
            .err()
            .expect("refused");
        assert_eq!(
            failed(error),
            (
                "UPGRADE_REQUIRED".to_owned(),
                false,
                Some("protocol_version".to_owned())
            )
        );
        assert_eq!(bridge_protocol_version(), PROTOCOL_VERSION);
    }

    #[test]
    fn bridge_026_fr_002_decodes_a_command_and_keeps_counters_exact() {
        let runtime = BridgeRuntime::new(PROTOCOL_VERSION).expect("opens");
        let command = runtime.decode_command(COMMAND.into()).expect("decodes");
        assert!(command.executable);
        assert_eq!(command.unsupported_reason, None);
        assert_eq!(command.command_id, "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11");
        assert_eq!(command.command_type, "task.create");
        assert_eq!(command.local_sequence, "9007199254740993");
        let wire: serde_json::Value = serde_json::from_slice(&command.wire).expect("json");
        assert_eq!(wire["local_sequence"], "9007199254740993");
        assert!(wire.get("supersedes_command_id").is_none());
    }

    #[test]
    fn bridge_026_fr_002_reports_unsupported_commands_as_values_not_errors() {
        let json = COMMAND.replace("task.create", "task.from_the_future");
        let command = decode_command(json.as_bytes()).expect("decodes");
        assert!(!command.executable);
        assert_eq!(command.unsupported_reason.as_deref(), Some("command_type"));
    }

    #[test]
    fn bridge_026_fr_002_maps_codec_errors_without_payload_text() {
        let secret = "Buy milk";
        let cases = [
            &b"{\"title\": \"Buy milk\""[..],
            &b"\xff\xfe"[..],
            &br#"{"a":1,"a":2}"#[..],
        ];
        for data in cases {
            let failure = decode_command(data).expect_err("rejected");
            assert_eq!(failure, Failure::new("INVALID_REQUEST", None));
        }
        let bad_id = COMMAND.replace("5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11", "not-a-uuid");
        let failure = decode_command(bad_id.as_bytes()).expect_err("rejected");
        assert_eq!(failure.code, "INVALID_REQUEST");
        let error = BridgeError::from(failure);
        assert!(!format!("{error:?}{error}").contains(secret));
    }
}
