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

/// Incremental form of [`decode_change_stream`]: the canonical JSON array is fed
/// in byte chunks (a chunk may end inside a record, even inside a multi-byte
/// character) and each [`Change`] is returned as soon as its object is
/// complete. Memory is one record in progress plus the set of record keys seen,
/// never the whole stream.
///
/// It is exactly as strict as the whole-stream decoder: every element must be a
/// duplicate-key-free JSON object that is a valid [`Change`], the stream must be
/// exactly one array, and a record key may appear once (a transaction and a
/// snapshot both carry each key's final after-image only). The caller owns
/// integrity (digests, counts); a stream is complete only when
/// [`ChangeStreamDecoder::finish`] succeeds.
#[derive(Debug, Default)]
pub struct ChangeStreamDecoder {
    state: StreamState,
    /// The bytes of the record in progress.
    carry: Vec<u8>,
    depth: usize,
    in_string: bool,
    escaped: bool,
    keys: HashSet<(EntityType, RecordKey)>,
    count: u64,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
enum StreamState {
    /// Before the opening `[`.
    #[default]
    Start,
    /// After `[`: a record or `]`.
    Opened,
    /// Inside a record.
    Record,
    /// After a record: `,` or `]`.
    Closed,
    /// After `,`: a record.
    Separated,
    /// After `]`: nothing but whitespace.
    Done,
}

const BAD_STREAM: CodecError = CodecError::Invalid("change stream");

impl ChangeStreamDecoder {
    pub fn new() -> Self {
        Self::default()
    }

    /// Consumes the next chunk and returns the changes it completed.
    ///
    /// # Errors
    ///
    /// [`CodecError`] for anything the whole-stream decoder would refuse. After
    /// an error the decoder must be discarded.
    pub fn push(&mut self, chunk: &[u8]) -> Result<Vec<Change>, CodecError> {
        let mut done = Vec::new();
        for &byte in chunk {
            match self.state {
                StreamState::Record => {
                    self.carry.push(byte);
                    if self.in_string {
                        if self.escaped {
                            self.escaped = false;
                        } else if byte == b'\\' {
                            self.escaped = true;
                        } else if byte == b'"' {
                            self.in_string = false;
                        }
                    } else {
                        match byte {
                            b'"' => self.in_string = true,
                            b'{' | b'[' => self.depth += 1,
                            b'}' | b']' => {
                                self.depth = self.depth.checked_sub(1).ok_or(BAD_STREAM)?;
                                if self.depth == 0 {
                                    done.push(self.finish_record()?);
                                }
                            }
                            _ => {}
                        }
                    }
                }
                _ if matches!(byte, b' ' | b'\t' | b'\n' | b'\r') => {}
                StreamState::Start if byte == b'[' => self.state = StreamState::Opened,
                StreamState::Opened | StreamState::Separated if byte == b'{' => {
                    self.carry.clear();
                    self.carry.push(byte);
                    self.depth = 1;
                    self.state = StreamState::Record;
                }
                StreamState::Opened | StreamState::Closed if byte == b']' => {
                    self.state = StreamState::Done;
                }
                StreamState::Closed if byte == b',' => self.state = StreamState::Separated,
                _ => return Err(BAD_STREAM),
            }
        }
        Ok(done)
    }

    fn finish_record(&mut self) -> Result<Change, CodecError> {
        let text = std::str::from_utf8(&self.carry).map_err(|_| BAD_STREAM)?;
        let change: Change = crate::wire::decode(text)?;
        if !self
            .keys
            .insert((change.entity_type, change.record_key.clone()))
        {
            return Err(CodecError::Invalid("change stream repeats a record key"));
        }
        self.count += 1;
        self.carry.clear();
        self.state = StreamState::Closed;
        Ok(change)
    }

    /// Ends the stream and returns how many changes it held.
    ///
    /// # Errors
    ///
    /// [`CodecError`] when the array was not closed.
    pub fn finish(self) -> Result<u64, CodecError> {
        if self.state == StreamState::Done {
            Ok(self.count)
        } else {
            Err(BAD_STREAM)
        }
    }
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
