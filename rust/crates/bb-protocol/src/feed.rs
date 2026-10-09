//! Delta feed, oversized-transaction transfer and snapshot messages
//! (sync-v1 §6, §11), plus the SSE hint event.
//!
//! This module checks shape and the cross-field rules the contract states. It
//! does not decode `payload_base64`, verify digests or apply anything: staging,
//! checksum verification and atomic activation belong to the runtime.

use crate::catalog::EntityType;
use crate::wire::{
    CodecError, CommandId, CommonResponse, CorrelationId, Counter, Generation, Id, Instant, Marker,
    OpenObject, RecordKey, Wire, required,
};
use serde::{Deserialize, Serialize};
use std::collections::HashSet;

/// Whether a change installs an after-image or removes a record.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Operation {
    Upsert,
    Tombstone,
}

/// One typed record change: a public after-image, or a tombstone with no value.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Change {
    pub entity_type: EntityType,
    pub record_key: RecordKey,
    pub record_version: Counter,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub edit_revision: Option<Counter>,
    pub operation: Operation,
    #[serde(deserialize_with = "required")]
    pub value: Option<OpenObject>,
}

impl Wire for Change {
    fn validate(&self) -> Result<(), CodecError> {
        match (self.operation, &self.value) {
            (Operation::Upsert, Some(_)) | (Operation::Tombstone, None) => Ok(()),
            (Operation::Upsert, None) => Err(CodecError::Invalid("upsert without value")),
            (Operation::Tombstone, Some(_)) => Err(CodecError::Invalid("tombstone with value")),
        }
    }
}

/// The decoded byte stream of a snapshot or transfer: a canonical JSON array of
/// changes. Chunks may split a record, so only the assembled stream is parsed.
impl Wire for Vec<Change> {
    fn validate(&self) -> Result<(), CodecError> {
        self.iter().try_for_each(Wire::validate)
    }
}

/// Decodes an assembled byte stream (snapshot or transfer pages concatenated in
/// page order) into changes.
pub fn decode_change_stream(bytes: &[u8]) -> Result<Vec<Change>, CodecError> {
    let text = std::str::from_utf8(bytes).map_err(|_| CodecError::Invalid("change stream"))?;
    crate::wire::decode(text)
}

/// One complete logical transaction; never partially applied or exposed.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Transaction {
    pub transaction_id: String,
    pub commit_seq: Counter,
    pub source_command_id: CommandId,
    pub changes: Vec<Change>,
}

impl Wire for Transaction {
    fn validate(&self) -> Result<(), CodecError> {
        self.changes.iter().try_for_each(Wire::validate)?;
        // Every changed key appears once with its final after-image.
        let mut keys = HashSet::new();
        if !self
            .changes
            .iter()
            .all(|c| keys.insert((c.entity_type, &c.record_key)))
        {
            return Err(CodecError::Invalid("transaction repeats a record key"));
        }
        Ok(())
    }
}

/// Manifest for a transaction too large to send inline.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransferManifest {
    pub transfer_id: Id,
    pub transaction_id: String,
    pub commit_seq: Counter,
    pub source_command_id: CommandId,
    pub page_count: u64,
    pub record_count: u64,
    pub total_bytes: u64,
    pub sha256: String,
    pub expires_at: Instant,
    pub first_page_token: String,
    pub after_cursor: String,
}

impl Wire for TransferManifest {
    fn validate(&self) -> Result<(), CodecError> {
        at_least_one_page(self.page_count)
    }
}

/// `GET changes` response: complete transactions after a cursor.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ChangesPage {
    pub from_cursor: String,
    pub transactions: Vec<Transaction>,
    pub has_more: bool,
    pub next_cursor: String,
    pub high_watermark: Counter,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transaction_manifest: Option<TransferManifest>,
    #[serde(flatten)]
    pub common: CommonResponse,
}

impl Wire for ChangesPage {
    fn validate(&self) -> Result<(), CodecError> {
        self.transactions.iter().try_for_each(Wire::validate)?;
        // An empty page, including one that only announces an oversized
        // transaction, never moves the cursor: advancing it past an
        // unapplied transaction would skip that transaction for good.
        if self.transactions.is_empty() && self.next_cursor != self.from_cursor {
            return Err(CodecError::Invalid(
                "an empty page must keep next_cursor at from_cursor",
            ));
        }
        if let Some(manifest) = &self.transaction_manifest {
            manifest.validate()?;
            if !self.transactions.is_empty() || !self.has_more {
                return Err(CodecError::Invalid(
                    "transaction_manifest needs empty transactions and has_more",
                ));
            }
        }
        Ok(())
    }
}

/// `POST snapshots` body.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SnapshotRequest {
    pub scope_id: Id,
    pub projection_schema_version: Marker,
}

impl Wire for SnapshotRequest {}

/// `POST snapshots` response: an immutable snapshot at one watermark.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SnapshotManifest {
    pub snapshot_id: Id,
    pub watermark: Counter,
    pub cursor: String,
    pub page_count: u64,
    pub record_count: u64,
    pub total_bytes: u64,
    pub sha256: String,
    pub expires_at: Instant,
    pub first_page_token: String,
    #[serde(flatten)]
    pub common: CommonResponse,
}

impl Wire for SnapshotManifest {
    fn validate(&self) -> Result<(), CodecError> {
        at_least_one_page(self.page_count)
    }
}

fn at_least_one_page(page_count: u64) -> Result<(), CodecError> {
    if page_count == 0 {
        return Err(CodecError::Invalid("page_count must be at least 1"));
    }
    Ok(())
}

/// One bounded page of a canonical byte stream.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct BytePage {
    pub page_index: u64,
    pub payload_base64: String,
    pub page_sha256: String,
    pub has_more: bool,
    #[serde(deserialize_with = "required")]
    pub next_page_token: Option<String>,
    #[serde(flatten)]
    pub common: CommonResponse,
}

impl BytePage {
    fn check_continuation(&self) -> Result<(), CodecError> {
        if self.has_more != self.next_page_token.is_some() {
            return Err(CodecError::Invalid(
                "next_page_token must be present exactly while has_more",
            ));
        }
        Ok(())
    }
}

/// One page of an immutable snapshot.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SnapshotPage {
    pub snapshot_id: Id,
    pub watermark: Counter,
    #[serde(flatten)]
    pub page: BytePage,
}

impl Wire for SnapshotPage {
    fn validate(&self) -> Result<(), CodecError> {
        self.page.check_continuation()
    }
}

/// One page of an oversized transaction transfer.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TransferPage {
    pub transfer_id: Id,
    #[serde(flatten)]
    pub page: BytePage,
}

impl Wire for TransferPage {
    fn validate(&self) -> Result<(), CodecError> {
        self.page.check_continuation()
    }
}

/// Data of the SSE `scope_changed` event: a wake-up carrying no task content,
/// command ID or cursor. Any extra key is refused.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HintEvent {
    pub scope_id: Id,
    pub server_generation: Generation,
    pub feed_generation: Generation,
    pub server_now: Instant,
    pub correlation_id: CorrelationId,
}

impl Wire for HintEvent {}
