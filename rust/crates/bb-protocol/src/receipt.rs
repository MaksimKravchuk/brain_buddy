//! Receipts, errors and result lookup (sync-v1 §5, §11).

use crate::catalog::EntityType;
use crate::wire::{
    CodecError, CommandId, CommonResponse, CorrelationId, Counter, Id, OpenObject, RecordKey, Wire,
    required,
};
use serde::{Deserialize, Serialize};

/// Terminal receipt outcome.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Outcome {
    Accepted,
    Rejected,
}

/// Device epoch status in error details and registration.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EpochStatus {
    Active,
    Closed,
}

/// A replicated record version.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Version {
    pub entity_type: EntityType,
    pub record_key: RecordKey,
    pub record_version: Counter,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub edit_revision: Option<Counter>,
}

/// Smart Add alias resolution retained until purge.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Binding {
    pub entity_type: EntityType,
    pub alias_id: Id,
    pub entity_id: Id,
}

/// Allowlisted, content-free error details: any other key is refused, so task
/// text cannot ride along in diagnostics (026-FR-022).
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ErrorDetails {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub current_versions: Option<Vec<Version>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dependency_ids: Option<Vec<CommandId>>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub epoch_status: Option<EpochStatus>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reset_reason: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub retry_after_seconds: Option<u64>,
}

/// Wire error object. `code` is an open set: a canonical validation reason is
/// also a code.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct WireError {
    pub code: String,
    pub retryable: bool,
    pub message: String,
    pub details: ErrorDetails,
}

/// An error outside a receipt: protocol and transport failures. Before scope
/// authority is established only these two fields are present.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ErrorBody {
    pub error: WireError,
    pub correlation_id: CorrelationId,
}

impl Wire for ErrorBody {}

/// Terminal command receipt plus common response fields.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Receipt {
    pub command_id: CommandId,
    pub outcome: Outcome,
    pub has_changes: bool,
    #[serde(deserialize_with = "required")]
    pub commit_seq: Option<Counter>,
    pub result_versions: Vec<Version>,
    pub id_bindings: Vec<Binding>,
    pub result_redacted: bool,
    #[serde(deserialize_with = "required")]
    pub result: Option<OpenObject>,
    #[serde(deserialize_with = "required")]
    pub error: Option<WireError>,
    #[serde(flatten)]
    pub common: CommonResponse,
}

impl Wire for Receipt {
    fn validate(&self) -> Result<(), CodecError> {
        let rejected = self.outcome == Outcome::Rejected;
        if rejected && self.has_changes {
            return Err(CodecError::Invalid("rejected receipt with changes"));
        }
        if rejected != self.error.is_some() {
            return Err(CodecError::Invalid("receipt error must match outcome"));
        }
        if self.has_changes != self.commit_seq.is_some() {
            return Err(CodecError::Invalid("commit_seq must match has_changes"));
        }
        // Redaction means the retained content is unavailable (sync-v1 section 5).
        if self.result_redacted && self.result.is_some() {
            return Err(CodecError::Invalid(
                "redacted receipt must have a null result",
            ));
        }
        Ok(())
    }
}

/// Result of `GET commands/{id}`. `Pending` and `NotFound` are observations
/// only: neither licenses a new command ID.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum LookupStatus {
    Terminal { receipt: Box<Receipt> },
    Pending { command_id: CommandId },
    NotFound { command_id: CommandId },
}

/// Receipt lookup response with common fields.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct CommandLookup {
    #[serde(flatten)]
    pub status: LookupStatus,
    #[serde(flatten)]
    pub common: CommonResponse,
}

impl Wire for CommandLookup {
    fn validate(&self) -> Result<(), CodecError> {
        match &self.status {
            LookupStatus::Terminal { receipt } => receipt.validate(),
            LookupStatus::Pending { .. } | LookupStatus::NotFound { .. } => Ok(()),
        }
    }
}
