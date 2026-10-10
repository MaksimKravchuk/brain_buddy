//! What the legacy outbox becomes in the Rust store (spec 026 T042,
//! contracts/runtime-ffi.md "Migration and packaging boundary").
//!
//! [`crate::import`] carries every pending send and every sync issue of the old
//! file whole, in `drafts` rows. This module classifies them, once the import has
//! its marker, and answers one question for each entry: *is the server's outcome
//! provable?* Nothing is ever sent again and nothing is rebuilt as a new command:
//! an old send that may have reached the server is settled by its **receipt**, or
//! it stays visible as an issue. The old file's own facts are never rewritten; a
//! `legacy_outbox_resolution` draft records each verdict beside the entry.
//!
//! * **Unsent** (`attempts == 0` and not `everSent`): the request never left the
//!   device, so the user's intent is still genuinely pending. It stays carried,
//!   in queue order, for the runtime to turn into a new command; until then the
//!   workspace is not [`LegacyOutboxStatus::may_run`].
//! * **Accepted**: the receipt for the entry's own idempotency key says the server
//!   did it. Every identity the receipt proves is recorded as an alias, but only
//!   for an ID the old command uses as that entity's identifier (never text) and never against a different
//!   alias already proven. The entry leaves pending work without a new command.
//! * **Rejected**: the receipt for the key says the server refused it. An issue
//!   keeps the intent and its text.
//! * **Awaiting**: sent, no proof yet, and the server still keeps that key (24
//!   hours from the first send with it). Looked up again on the next run.
//! * **Uncertain**: sent, no proof, and the window is over (or the current key was
//!   never used, so a lookup by it cannot speak for an earlier key's request): an
//!   issue keeps everything the old engine knew (`everSent`, `issuedAt`, `attempts`,
//!   the key and the body), is exported with the account's data, and is never
//!   reissued under a new ID. A later receipt reconciles it.
//!
//! Matching requires the original key and body. If the carried source uses one key
//! for different bodies, no key-only answer can prove either entry. A title, a list
//! or a time is never proof.
//! The lookup is a port ([`ReceiptLookup`]); it is called outside any
//! transaction, and the verdicts are applied in one write transaction that
//! re-reads what it depends on. Every entry is accounted for or nothing is saved.

use crate::execute::{ExecuteError, ExecuteRequest, Executed, IdSource, execute_batch_in};
use crate::import::{KIND_ISSUE, KIND_OUTBOX, legacy_import_marker};
use crate::storage::{Store, StoreError};
use bb_domain::calendar::UtcInstant;
use bb_domain::types::{DomainError, Reason};
use bb_protocol::catalog::EntityType;
use bb_protocol::wire::{CommandId, Instant};
use rusqlite::{OptionalExtension, Transaction, params};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, HashMap, HashSet};

const KIND_RESOLUTION: &str = "legacy_outbox_resolution";
const ALIAS_PROVENANCE: &str = "legacy-outbox:receipt";
/// How long the server keeps an idempotency key, counted from the first send with it.
const WINDOW_SECONDS: i64 = 24 * 60 * 60;
const UNKNOWN: &str = "OUTCOME_UNKNOWN";
const REJECTED: &str = "LEGACY_REJECTED";
/// The members of an old command that hold text the user wrote.
const TEXT_MEMBERS: [&str; 8] = [
    "title",
    "details",
    "waitingFor",
    "name",
    "desiredOutcome",
    "outcome",
    "body",
    "reason",
];

// --------------------------------------------------------------------------- the port

/// One old send to ask the server about.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LegacySend {
    pub entry_id: String,
    /// The `Idempotency-Key` the send was made with, paired with its original body.
    pub idempotency_key: String,
    /// The old command, verbatim: the body the key was sent with. A lookup that finds
    /// the key under a different body proves nothing and answers `Unproven`.
    pub command: Value,
}

/// An identity a receipt proves: the server ID the old command's local ID became.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProvenAlias {
    pub entity_type: EntityType,
    pub old_local_id: String,
    pub server_id: String,
}

/// What the server can prove about one old send.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LegacyAnswer {
    /// A retained receipt for this key says it was accepted (or was a no-op).
    Accepted { aliases: Vec<ProvenAlias> },
    /// A retained receipt for this key says it was refused; `code` is its error code.
    Rejected { code: String },
    /// No receipt, one still pending, a different body under the key, or no answer at
    /// all (offline). An observation, never proof either way.
    Unproven,
}

/// The receipt lookup the resolution consults (a fake in the tests, the transport
/// once it exists). Called outside any transaction.
pub trait ReceiptLookup {
    fn lookup(&mut self, send: &LegacySend) -> LegacyAnswer;
}

impl<F: FnMut(&LegacySend) -> LegacyAnswer> ReceiptLookup for F {
    fn lookup(&mut self, send: &LegacySend) -> LegacyAnswer {
        self(send)
    }
}

/// Answers a caller already fetched, by idempotency key (case does not matter: a Swift
/// `UUID` prints upper case). A key without an answer is `Unproven`. Resolution
/// refuses these answers when carried entries use the key for different bodies.
#[derive(Clone, Debug, Default)]
pub struct ProvidedReceipts(BTreeMap<String, LegacyAnswer>);

impl ProvidedReceipts {
    pub fn insert(&mut self, idempotency_key: &str, answer: LegacyAnswer) {
        self.0.insert(idempotency_key.to_ascii_lowercase(), answer);
    }
}

impl ReceiptLookup for ProvidedReceipts {
    fn lookup(&mut self, send: &LegacySend) -> LegacyAnswer {
        let key = send.idempotency_key.to_ascii_lowercase();
        self.0.get(&key).cloned().unwrap_or(LegacyAnswer::Unproven)
    }
}

// ------------------------------------------------------------------- status and errors

/// Where the legacy outbox stands. Counts only; no user text.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct LegacyOutboxStatus {
    /// Pending sends the import carried.
    pub carried: u64,
    pub unsent: u64,
    /// Converted into durable runtime commands; their server outcomes still wait.
    pub converted: u64,
    pub accepted: u64,
    pub rejected: u64,
    pub awaiting: u64,
    pub uncertain: u64,
    /// Old sync issues the import carried, and how many are issues now.
    pub carried_issues: u64,
    pub converted_issues: u64,
    /// Issues of legacy origin still waiting for the user or for proof.
    pub open_issues: u64,
    /// Identities receipts proved.
    pub aliases: u64,
}

impl LegacyOutboxStatus {
    /// Every carried entry and issue has a verdict.
    pub fn classified(&self) -> bool {
        self.carried
            == self.unsent
                + self.converted
                + self.accepted
                + self.rejected
                + self.awaiting
                + self.uncertain
            && self.carried_issues == self.converted_issues
    }

    /// The Rust store may take the workspace: nothing carried is unaccounted for and no
    /// untouched intent waits to become a command.
    pub fn may_run(&self) -> bool {
        self.classified() && self.unsent == 0
    }

    /// Nothing of the old file is waiting on the server or on the user. Never true while
    /// an uncertain submission or an old issue exists.
    pub fn fully_synced(&self) -> bool {
        self.may_run()
            && self.converted + self.rejected + self.awaiting + self.uncertain + self.open_issues
                == 0
    }
}

/// Why nothing was resolved. Whatever it is, nothing was saved; none carries user text.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LegacyOutboxError {
    /// `LEGACY_OUTBOX_NOT_IMPORTED`: the store has no legacy import marker.
    NotImported,
    /// `LEGACY_OUTBOX_UNREADABLE`: a carried entry cannot be classified without inventing
    /// an identity.
    Unreadable {
        field: &'static str,
    },
    Store(StoreError),
}

impl LegacyOutboxError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::NotImported => "LEGACY_OUTBOX_NOT_IMPORTED",
            Self::Unreadable { .. } => "LEGACY_OUTBOX_UNREADABLE",
            Self::Store(error) => error.code(),
        }
    }

    pub fn is_retryable(&self) -> bool {
        matches!(self, Self::Store(error) if error.is_retryable())
    }

    pub fn field(&self) -> Option<&'static str> {
        match self {
            Self::Unreadable { field } => Some(field),
            _ => None,
        }
    }
}

impl std::fmt::Display for LegacyOutboxError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}

impl std::error::Error for LegacyOutboxError {}

impl From<StoreError> for LegacyOutboxError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}

impl From<rusqlite::Error> for LegacyOutboxError {
    fn from(error: rusqlite::Error) -> Self {
        Self::Store(error.into())
    }
}

fn unreadable(field: &'static str) -> LegacyOutboxError {
    LegacyOutboxError::Unreadable { field }
}

// ------------------------------------------------------------------------ the entries

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Standing {
    Unsent,
    Accepted,
    Rejected,
    Awaiting,
    Uncertain,
}

impl Standing {
    fn name(self) -> &'static str {
        match self {
            Self::Unsent => "unsent",
            Self::Accepted => "accepted",
            Self::Rejected => "rejected",
            Self::Awaiting => "awaiting",
            Self::Uncertain => "uncertain",
        }
    }

    /// Only a send without proof is looked at again.
    fn open(text: Option<&str>) -> bool {
        matches!(text, None | Some("awaiting" | "uncertain"))
    }
}

/// One carried pending send, read the way the old engine wrote it.
struct Entry {
    id: String,
    key: Option<String>,
    /// A request may have reached the server (`hasBeenSent`).
    sent: bool,
    /// The current key was actually used for a request.
    key_used: bool,
    /// The earliest known time of that request: the window is counted from it.
    first_sent: Option<UtcInstant>,
    raw: Value,
}

impl Entry {
    fn read(raw: Value) -> Result<Self, LegacyOutboxError> {
        let text = |member: &str| raw.get(member).and_then(Value::as_str);
        let uuid = |member: &str| text(member).filter(|value| CommandId::parse(*value).is_ok());
        let id = uuid("id").ok_or(unreadable("outbox"))?.to_owned();
        let attempts = raw
            .get("attempts")
            .and_then(Value::as_i64)
            .ok_or(unreadable("outbox"))?;
        let ever_sent = raw.get("everSent").and_then(Value::as_bool) == Some(true);
        let first_sent = ["firstAttemptAt", "lastAttemptAt", "issuedAt"]
            .into_iter()
            .find_map(text)
            .and_then(|at| UtcInstant::parse_rfc3339(at).ok());
        Ok(Self {
            key: uuid("idempotencyKey").map(str::to_owned),
            sent: attempts > 0 || ever_sent,
            key_used: attempts > 0,
            first_sent,
            id,
            raw,
        })
    }

    fn send(&self) -> Option<LegacySend> {
        Some(LegacySend {
            entry_id: self.id.clone(),
            idempotency_key: self.key.clone()?,
            command: self.raw.get("command").cloned().unwrap_or(Value::Null),
        })
    }
}

/// The carried entries in queue order, and the verdicts already recorded.
struct Loaded {
    workspace: String,
    entries: Vec<Entry>,
    standings: HashMap<String, String>,
    ambiguous_keys: HashSet<String>,
}

/// Inspect the whole immutable source, including unsent and already settled entries:
/// a key-only receipt cannot distinguish different original bodies under one key.
fn ambiguous_keys(entries: &[Entry]) -> HashSet<String> {
    let mut bodies = HashMap::new();
    let mut ambiguous = HashSet::new();
    for entry in entries {
        let Some(key) = entry.key.as_ref().map(|key| key.to_ascii_lowercase()) else {
            continue;
        };
        let command = entry.raw.get("command").unwrap_or(&Value::Null);
        if bodies
            .insert(key.clone(), command)
            .is_some_and(|body| body != command)
        {
            ambiguous.insert(key);
        }
    }
    ambiguous
}

fn ambiguous(entry: &Entry, keys: &HashSet<String>) -> bool {
    entry
        .key
        .as_ref()
        .is_some_and(|key| keys.contains(&key.to_ascii_lowercase()))
}

fn load(tx: &Transaction<'_>) -> Result<Loaded, LegacyOutboxError> {
    let workspace: String = tx.query_row("SELECT workspace_id FROM sync_meta", [], |r| r.get(0))?;
    let fields = |kind: &str| -> Result<Vec<(String, Value)>, LegacyOutboxError> {
        let mut statement = tx.prepare(
            "SELECT record_key, fields FROM drafts WHERE workspace_id = ?1 AND editor_kind = ?2
             ORDER BY draft_id",
        )?;
        let rows = statement.query_map(params![workspace, kind], |row| {
            Ok((row.get::<_, Option<String>>(0)?, row.get::<_, Vec<u8>>(1)?))
        })?;
        let mut found = Vec::new();
        for row in rows {
            let (key, bytes) = row?;
            let value = serde_json::from_slice(&bytes).map_err(|_| unreadable("outbox"))?;
            found.push((key.unwrap_or_default(), value));
        }
        Ok(found)
    };
    let entries: Vec<Entry> = fields(KIND_OUTBOX)?
        .into_iter()
        .map(|(_, raw)| Entry::read(raw))
        .collect::<Result<_, _>>()?;
    let standings = fields(KIND_RESOLUTION)?
        .into_iter()
        .filter_map(|(id, value)| Some((id, value.get("standing")?.as_str()?.to_owned())))
        .collect();
    Ok(Loaded {
        workspace,
        ambiguous_keys: ambiguous_keys(&entries),
        entries,
        standings,
    })
}

// ------------------------------------------------------------------------ resolving

/// Classifies the carried outbox and issues. See the module documentation.
///
/// Running it again is safe: a verdict that is not final (`Awaiting`, `Uncertain`) is
/// asked about again, everything else is left as it is.
///
/// # Errors
///
/// [`LegacyOutboxError`]; whatever it is, nothing was saved.
pub fn resolve_legacy_outbox(
    store: &mut Store,
    lookup: &mut impl ReceiptLookup,
    now: &Instant,
) -> Result<LegacyOutboxStatus, LegacyOutboxError> {
    legacy_import_marker(store)?.ok_or(LegacyOutboxError::NotImported)?;
    let at = UtcInstant::parse_rfc3339(now.as_str()).map_err(|_| unreadable("now"))?;

    // The lookups run with no transaction open: they may take as long as the network does.
    let mut answers: HashMap<String, LegacyAnswer> = HashMap::new();
    for send in legacy_outbox_sends(store)? {
        answers.insert(send.entry_id.clone(), lookup.lookup(&send));
    }

    store.try_write(|tx| {
        // What was read above may be stale: the verdicts are decided from a fresh read.
        let loaded = load(tx)?;
        for entry in &loaded.entries {
            let known = loaded.standings.get(&entry.id).map(String::as_str);
            if !Standing::open(known) {
                continue;
            }
            let answer =
                if (entry.sent && !entry.key_used) || ambiguous(entry, &loaded.ambiguous_keys) {
                    LegacyAnswer::Unproven
                } else {
                    answers
                        .get(&entry.id)
                        .cloned()
                        .unwrap_or(LegacyAnswer::Unproven)
                };
            settle(tx, &loaded.workspace, entry, &answer, (now.as_str(), at))?;
        }
        convert_issues(tx, &loaded.workspace, now.as_str())?;
        Ok(status_in(tx, &loaded.workspace)?)
    })
}

/// The same immutable source classification used by accountless setup. Even a
/// settled historical send remains remote history and must not be reinterpreted.
pub(crate) fn has_remote_history_in(tx: &Transaction<'_>) -> Result<bool, LegacyOutboxError> {
    let loaded = load(tx)?;
    Ok(loaded.entries.iter().any(|entry| entry.sent)
        || loaded
            .standings
            .values()
            .any(|standing| standing != "unsent"))
}

/// The sends still to ask the server about: the carried entries a request may have reached
/// the server for, with no final verdict. Read from the Rust store alone (the carried rows
/// are immutable), so the legacy file is not read again and needs no lock.
/// Keys carried with different command bodies are excluded: a key-only answer
/// cannot distinguish their outcomes.
/// A rotated current key that was never used cannot prove an earlier send either.
///
/// # Errors
///
/// [`LegacyOutboxError::NotImported`] without an import marker.
pub fn legacy_outbox_sends(store: &mut Store) -> Result<Vec<LegacySend>, LegacyOutboxError> {
    legacy_import_marker(store)?.ok_or(LegacyOutboxError::NotImported)?;
    let loaded = store.read(|tx| Ok(load(tx)))??;
    Ok(loaded
        .entries
        .iter()
        .filter(|entry| entry.sent && entry.key_used)
        .filter(|entry| !ambiguous(entry, &loaded.ambiguous_keys))
        .filter(|entry| Standing::open(loaded.standings.get(&entry.id).map(String::as_str)))
        .filter_map(Entry::send)
        .collect())
}

/// Where the legacy outbox stands now; nothing is changed.
///
/// # Errors
///
/// [`LegacyOutboxError::NotImported`] without an import marker.
pub fn legacy_outbox_status(store: &mut Store) -> Result<LegacyOutboxStatus, LegacyOutboxError> {
    legacy_import_marker(store)?.ok_or(LegacyOutboxError::NotImported)?;
    let workspace: String =
        store.read(|tx| tx.query_row("SELECT workspace_id FROM sync_meta", [], |r| r.get(0)))?;
    Ok(store.read(|tx| status_in(tx, &workspace))?)
}

/// Unsent source intents in immutable queue order. Swift uses the existing
/// GTDCommand decoder/encoder; Rust does not grow a second legacy rule mapper.
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct LegacyUnsent {
    pub entry_id: String,
    pub idempotency_key: CommandId,
    pub issued_at: bb_protocol::wire::Instant,
    pub command: Value,
}

fn legacy_source_item(entry: &Entry) -> Result<LegacyUnsent, LegacyOutboxError> {
    Ok(LegacyUnsent {
        entry_id: entry.id.clone(),
        idempotency_key: CommandId::parse(
            entry.key.as_deref().ok_or(unreadable("idempotencyKey"))?,
        )
        .map_err(|_| unreadable("idempotencyKey"))?,
        issued_at: Instant::parse(
            entry
                .raw
                .get("issuedAt")
                .and_then(Value::as_str)
                .ok_or(unreadable("issuedAt"))?,
        )
        .map_err(|_| unreadable("issuedAt"))?,
        command: entry
            .raw
            .get("command")
            .cloned()
            .ok_or(unreadable("command"))?,
    })
}

pub fn legacy_unsent(store: &mut Store) -> Result<Vec<LegacyUnsent>, LegacyOutboxError> {
    legacy_import_marker(store)?.ok_or(LegacyOutboxError::NotImported)?;
    store.read(|tx|Ok((|| {
        let workspace:String=tx.query_row("SELECT workspace_id FROM sync_meta",[],|r|r.get(0))?;
        let mut statement=tx.prepare("SELECT d.fields,r.fields FROM drafts d LEFT JOIN drafts r ON r.workspace_id=d.workspace_id AND r.editor_kind='legacy_outbox_resolution' AND r.record_key=d.record_key WHERE d.workspace_id=?1 AND d.editor_kind='legacy_outbox_entry' ORDER BY d.draft_id")?;
        let mut rows=statement.query([workspace])?;
        let mut items=Vec::new();
        let mut size=2;
        while let Some(row)=rows.next()? {
            let bytes:Vec<u8>=row.get(0)?;
            let entry=Entry::read(serde_json::from_slice(&bytes).map_err(|_|unreadable("outbox"))?)?;
            let resolution:Option<Vec<u8>>=row.get(1)?;
            let resolution:Option<Value>=resolution.map(|bytes|serde_json::from_slice(&bytes).map_err(|_|unreadable("outbox"))).transpose()?;
            if entry.sent || resolution.as_ref().and_then(|r|r.get("standing")).and_then(Value::as_str)!=Some("unsent") {continue;}
            if items.len()==200 {return Err(unreadable("legacy_outbox_page"));}
            let item=legacy_source_item(&entry)?;
            size+=serde_json::to_vec(&item).map_err(|_|unreadable("outbox"))?.len()+64;
            if size>CONVERSION_BYTES {return Err(unreadable("legacy_outbox_page"));}
            items.push(item);
        }
        Ok(items)
    })()))?
}

/// All prepared unsent intents and their conversion markers commit together.
/// Re-read eligibility, queue order, original instant and key under the same
/// lock used by execute. Sent/uncertain submissions can never enter this port.
/// The source carriers remain immutable for export and audit.
pub fn convert_legacy_unsent_with(
    store: &mut Store,
    ids: &mut impl IdSource,
    requests: &[ExecuteRequest],
    before_commit: impl FnOnce(&Transaction<'_>) -> Result<(), ExecuteError>,
) -> Result<Vec<Executed>, ExecuteError> {
    convert_legacy_prepared_with(store, ids, requests, None, before_commit)
}

/// The native prepared port also fences immutable source entry identities.
pub fn convert_legacy_prepared_with(
    store: &mut Store,
    ids: &mut impl IdSource,
    requests: &[ExecuteRequest],
    entry_ids: Option<&[String]>,
    before_commit: impl FnOnce(&Transaction<'_>) -> Result<(), ExecuteError>,
) -> Result<Vec<Executed>, ExecuteError> {
    let invalid =
        || ExecuteError::Refused(DomainError::field(Reason::InvalidPayload, "legacy_outbox"));
    legacy_import_marker(store)
        .map_err(ExecuteError::Store)?
        .ok_or_else(invalid)?;
    store.try_write(|tx| {
        let loaded = load(tx).map_err(|error| match error {
            LegacyOutboxError::Store(error) => ExecuteError::Store(error),
            _ => invalid(),
        })?;
        let entries: Vec<_> = loaded
            .entries
            .iter()
            .filter(|entry| {
                !entry.sent
                    && loaded
                        .standings
                        .get(&entry.id)
                        .is_some_and(|s| matches!(s.as_str(), "unsent" | "converted"))
            })
            .collect();
        if entries.len() != requests.len()
            || entry_ids.is_some_and(|ids| {
                ids.len() != entries.len()
                    || entries.iter().zip(ids).any(|(entry, id)| &entry.id != id)
            })
        {
            return Err(invalid());
        }
        for (entry, request) in entries.iter().zip(requests) {
            let key = entry
                .key
                .as_deref()
                .and_then(|key| CommandId::parse(key).ok())
                .ok_or_else(invalid)?;
            let issued = entry
                .raw
                .get("issuedAt")
                .and_then(Value::as_str)
                .and_then(|text| bb_protocol::wire::Instant::parse(text).ok())
                .ok_or_else(invalid)?;
            if request.command_id != key || request.context.now != issued {
                return Err(invalid());
            }
        }
        if requests
            .iter()
            .any(|request| request.command_type.as_str().starts_with("review."))
            && !crate::legacy_review::is_active_in(tx, &loaded.workspace)?
        {
            return Err(ExecuteError::Refused(bb_domain::types::DomainError::field(
                bb_domain::types::Reason::InvalidPayload,
                "legacy_review_activation",
            )));
        }
        let results = execute_batch_in(tx, ids, requests)?;
        for (entry, request) in entries.iter().zip(requests) {
            let fields = json!({"standing":"converted", "command_id":request.command_id,
                "resolved_at":request.context.now});
            tx.execute(
                "UPDATE drafts SET fields = ?3 WHERE workspace_id = ?1
                AND editor_kind = 'legacy_outbox_resolution' AND record_key = ?2",
                params![loaded.workspace, entry.id, fields.to_string().into_bytes()],
            )?;
        }
        before_commit(tx)?;
        Ok(results)
    })
}

// ---------------------------------------------------------------- bounded native preparation

const CONVERSION_HEADER: &str = "runtime-legacy-conversion";
const CONVERSION_KIND: &str = "runtime_legacy_conversion";
const CONVERSION_ITEM_KIND: &str = "runtime_legacy_conversion_item";
const CONVERSION_BYTES: usize = 8 * 1024 * 1024;

/// A small import-bound preparation context. It survives completion; payload
/// fragments do not. The native codec uses this frozen context on every restart.
#[derive(Clone, Debug)]
pub struct LegacyConversionPlan {
    pub token: String,
    pub context: crate::ExecuteContext,
    pub source_count: u64,
    pub atomic_group: bool,
}

#[derive(Clone, Debug)]
pub struct LegacyConversionPage {
    pub items: Vec<LegacyUnsent>,
    pub page_token: String,
    pub next_after: Option<String>,
}

/// Scalar results keep a large atomic group off the bridge.
#[derive(Clone, Debug)]
pub struct LegacyConversionProgress {
    pub source_count: u64,
    pub processed_count: u64,
    pub complete: bool,
    pub status: LegacyOutboxStatus,
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ConversionHeader {
    workspace: String,
    import_sha: String,
    authority: String,
    source_count: u64,
    first: Option<String>,
    last: Option<String>,
    source_digest: String,
    context: crate::ExecuteContext,
    atomic_group: bool,
    token: String,
    seal: Option<String>,
    completed: bool,
}

#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ConversionCursor {
    plan: String,
    after: Option<String>,
    last: String,
    count: usize,
    digest: String,
}

fn conversion_invalid() -> ExecuteError {
    ExecuteError::Refused(DomainError::field(Reason::InvalidPayload, "legacy_outbox"))
}

fn conversion_json<T: serde::Serialize>(value: &T) -> Result<Vec<u8>, ExecuteError> {
    serde_json::to_vec(value).map_err(|_| ExecuteError::Store(StoreError::Corrupt))
}

fn conversion_decode<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T, ExecuteError> {
    serde_json::from_slice(bytes).map_err(|_| conversion_invalid())
}

fn conversion_part(digest: &mut crate::DigestStream, bytes: &[u8]) {
    digest.update(&(bytes.len() as u64).to_be_bytes());
    digest.update(bytes);
}

/// Streams immutable ordinal carriers. No live queue offset or unbounded ID list.
fn conversion_sources(
    tx: &Transaction<'_>,
    workspace: &str,
    mut visit: impl FnMut(&str, &Entry, &str, &[u8]) -> Result<(), ExecuteError>,
) -> Result<(), ExecuteError> {
    let mut query = tx.prepare(
        "SELECT d.draft_id,d.fields,r.fields FROM drafts d
         LEFT JOIN drafts r ON r.workspace_id=d.workspace_id
           AND r.editor_kind='legacy_outbox_resolution' AND r.record_key=d.record_key
         WHERE d.workspace_id=?1 AND d.editor_kind='legacy_outbox_entry' ORDER BY d.draft_id",
    )?;
    let mut rows = query.query([workspace])?;
    while let Some(row) = rows.next()? {
        let ordinal: String = row.get(0)?;
        let bytes: Vec<u8> = row.get(1)?;
        let entry = Entry::read(conversion_decode(&bytes)?).map_err(|_| conversion_invalid())?;
        if entry.sent {
            continue;
        }
        let resolution: Option<Vec<u8>> = row.get(2)?;
        let resolution: Value =
            conversion_decode(resolution.as_deref().ok_or_else(conversion_invalid)?)?;
        let standing = resolution
            .get("standing")
            .and_then(Value::as_str)
            .ok_or_else(conversion_invalid)?;
        if !matches!(standing, "unsent" | "converted") {
            return Err(conversion_invalid());
        }
        visit(&ordinal, &entry, standing, &bytes)?;
    }
    Ok(())
}

fn conversion_header(tx: &Transaction<'_>, token: &str) -> Result<ConversionHeader, ExecuteError> {
    let workspace: String = tx.query_row("SELECT workspace_id FROM sync_meta", [], |r| r.get(0))?;
    let bytes: Option<Vec<u8>> = tx
        .query_row(
            "SELECT fields FROM drafts WHERE workspace_id=?1 AND draft_id=?2 AND editor_kind=?3",
            params![workspace, CONVERSION_HEADER, CONVERSION_KIND],
            |r| r.get(0),
        )
        .optional()?;
    let header: ConversionHeader =
        conversion_decode(bytes.as_deref().ok_or_else(conversion_invalid)?)?;
    if header.token != token || header.workspace != workspace {
        return Err(conversion_invalid());
    }
    let marker = crate::import::read_marker(tx, &workspace)?
        .ok_or_else(conversion_invalid)?
        .1;
    let authority: String =
        tx.query_row("SELECT account_link_state FROM sync_meta", [], |r| r.get(0))?;
    if marker.source_sha256 != header.import_sha || authority != header.authority {
        return Err(conversion_invalid());
    }
    let mut digest = crate::DigestStream::default();
    let mut count = 0;
    let mut first = None;
    let mut last = None;
    conversion_sources(tx, &workspace, |ordinal, _, _, bytes| {
        first.get_or_insert_with(|| ordinal.to_owned());
        last = Some(ordinal.to_owned());
        count += 1;
        conversion_part(&mut digest, ordinal.as_bytes());
        conversion_part(&mut digest, bytes);
        Ok(())
    })?;
    if (count, first, last, digest.digest())
        != (
            header.source_count,
            header.first.clone(),
            header.last.clone(),
            header.source_digest.clone(),
        )
    {
        return Err(conversion_invalid());
    }
    Ok(header)
}

fn save_conversion_header(
    tx: &Transaction<'_>,
    header: &ConversionHeader,
) -> Result<(), ExecuteError> {
    tx.execute(
        "INSERT INTO drafts(workspace_id,draft_id,editor_kind,fields,updated_at)
         VALUES(?1,?2,?3,?4,?5) ON CONFLICT(workspace_id,draft_id) DO UPDATE SET fields=excluded.fields",
        params![header.workspace,CONVERSION_HEADER,CONVERSION_KIND,conversion_json(header)?,header.context.now.as_str()],
    )?;
    Ok(())
}

pub fn begin_legacy_conversion_with(
    store: &mut Store,
    context: &crate::ExecuteContext,
    atomic_group: bool,
    before_commit: impl FnOnce(&Transaction<'_>) -> Result<(), ExecuteError>,
) -> Result<LegacyConversionPlan, ExecuteError> {
    store.try_write(|tx| {
        let workspace: String =
            tx.query_row("SELECT workspace_id FROM sync_meta", [], |r| r.get(0))?;
        let old: Option<Vec<u8>> = tx.query_row(
            "SELECT fields FROM drafts WHERE workspace_id=?1 AND draft_id=?2 AND editor_kind=?3",
            params![workspace, CONVERSION_HEADER, CONVERSION_KIND], |r| r.get(0),
        ).optional()?;
        let header = if let Some(bytes) = old {
            let old: ConversionHeader = conversion_decode(&bytes)?;
            let header = conversion_header(tx, &old.token)?;
            if atomic_group && !header.atomic_group {
                return Err(conversion_invalid());
            }
            header
        } else {
            let import_sha = crate::import::read_marker(tx, &workspace)?
                .ok_or_else(conversion_invalid)?
                .1
                .source_sha256;
            if !status_in(tx, &workspace)?.classified() {
                return Err(conversion_invalid());
            }
            let authority =
                tx.query_row("SELECT account_link_state FROM sync_meta", [], |r| r.get(0))?;
            let mut source = crate::DigestStream::default();
            let mut source_count = 0;
            let mut first = None;
            let mut last = None;
            let mut coupled = atomic_group;
            conversion_sources(tx, &workspace, |ordinal, entry, _, bytes| {
                first.get_or_insert_with(|| ordinal.to_owned());
                last = Some(ordinal.to_owned());
                source_count += 1;
                conversion_part(&mut source, ordinal.as_bytes());
                conversion_part(&mut source, bytes);
                // Existing Swift Codable discriminants. Conservatively keep the
                // whole original sequence together before any prefix can commit.
                let command = entry.raw.get("command").ok_or_else(conversion_invalid)?;
                coupled |=
                    command.get("deleteTag").is_some() || command.get("bulkRelease").is_some();
                Ok(())
            })?;
            let mut header = ConversionHeader {
                workspace,
                import_sha,
                authority,
                source_count,
                first,
                last,
                source_digest: source.digest(),
                context: context.clone(),
                atomic_group: coupled,
                token: String::new(),
                seal: None,
                completed: false,
            };
            header.token = crate::sha256_hex(&conversion_json(&header)?);
            if header.atomic_group {
                let mut converted = 0;
                conversion_sources(tx, &header.workspace, |_, _, standing, _| {
                    converted += u64::from(standing == "converted");
                    Ok(())
                })?;
                if converted > 0 && converted != header.source_count {
                    return Err(conversion_invalid());
                }
                if converted == header.source_count {
                    header.completed = true;
                    header.seal = Some(conversion_seal(tx, &header, true)?);
                }
            }

            save_conversion_header(tx, &header)?;
            header
        };
        before_commit(tx)?;
        Ok(LegacyConversionPlan {
            token: header.token,
            context: header.context,
            source_count: header.source_count,
            atomic_group: header.atomic_group,
        })
    })
}

fn conversion_page_in(
    tx: &Transaction<'_>,
    header: &ConversionHeader,
    after: Option<&str>,
) -> Result<LegacyConversionPage, ExecuteError> {
    let after_ordinal = after;
    let mut after_found = after_ordinal.is_none();
    let mut items = Vec::new();
    let mut last = String::new();
    let mut bytes_used = 2048;
    let mut more = false;
    let mut digest = crate::DigestStream::default();
    conversion_sources(tx, &header.workspace, |ordinal, entry, _, raw| {
        if after_ordinal.is_some_and(|a| ordinal <= a) {
            after_found |= after_ordinal == Some(ordinal);
            return Ok(());
        }
        let item = legacy_source_item(entry).map_err(|_| conversion_invalid())?;
        let size = conversion_json(&item)?.len() + 64;
        if size + 2048 > CONVERSION_BYTES {
            return Err(conversion_invalid());
        }
        if items.len() == 200 || (!items.is_empty() && bytes_used + size > CONVERSION_BYTES / 2) {
            more = true;
            return Ok(());
        }
        if more {
            return Ok(());
        }
        bytes_used += size;
        conversion_part(&mut digest, ordinal.as_bytes());
        conversion_part(&mut digest, raw);
        last = ordinal.to_owned();
        items.push(item);
        Ok(())
    })?;
    if !after_found {
        return Err(conversion_invalid());
    }
    let cursor = ConversionCursor {
        plan: header.token.clone(),
        after: after.map(str::to_owned),
        last,
        count: items.len(),
        digest: digest.digest(),
    };
    let page_token =
        String::from_utf8(conversion_json(&cursor)?).map_err(|_| conversion_invalid())?;
    Ok(LegacyConversionPage {
        items,
        next_after: more.then(|| page_token.clone()),
        page_token,
    })
}

pub fn legacy_conversion_plan(
    store: &mut Store,
    token: &str,
) -> Result<LegacyConversionPlan, ExecuteError> {
    if token.len() > 4096 {
        return Err(conversion_invalid());
    }
    store.read(|tx| {
        Ok((|| {
            let header = conversion_header(tx, token)?;
            Ok(LegacyConversionPlan {
                token: header.token,
                context: header.context,
                source_count: header.source_count,
                atomic_group: header.atomic_group,
            })
        })())
    })?
}

pub fn legacy_conversion_page(
    store: &mut Store,
    token: &str,
    after: Option<&str>,
) -> Result<LegacyConversionPage, ExecuteError> {
    if token.len() > 4096 || after.is_some_and(|s| s.len() > 8192) {
        return Err(conversion_invalid());
    }
    store.read(|tx| {
        Ok((|| {
            let header = conversion_header(tx, token)?;
            let cursor: Option<ConversionCursor> =
                after.map(|s| conversion_decode(s.as_bytes())).transpose()?;
            if cursor.as_ref().is_some_and(|c| c.plan != header.token) {
                return Err(conversion_invalid());
            }
            conversion_page_in(tx, &header, cursor.as_ref().map(|c| c.last.as_str()))
        })())
    })?
}

fn prepared_conversion_page(
    tx: &Transaction<'_>,
    header: &ConversionHeader,
    page_token: &str,
    entry_ids: &[String],
    requests: &[ExecuteRequest],
) -> Result<LegacyConversionPage, ExecuteError> {
    if requests.is_empty()
        || requests.len() > 200
        || page_token.len() > 8192
        || conversion_json(&requests)?.len()
            + entry_ids.iter().map(String::len).sum::<usize>()
            + page_token.len()
            > CONVERSION_BYTES
    {
        return Err(conversion_invalid());
    }
    let cursor: ConversionCursor = conversion_decode(page_token.as_bytes())?;
    let page = conversion_page_in(tx, header, cursor.after.as_deref())?;
    if page.page_token != page_token
        || page.items.len() != requests.len()
        || entry_ids.len() != requests.len()
    {
        return Err(conversion_invalid());
    }
    for ((source, request), id) in page.items.iter().zip(requests).zip(entry_ids) {
        if source.entry_id != *id
            || source.idempotency_key != request.command_id
            || source.issued_at != request.context.now
            || request.context.actor_id != header.context.actor_id
            || request.context.time_zone != header.context.time_zone
            || request.context.policy != header.context.policy
        {
            return Err(conversion_invalid());
        }
    }
    if requests
        .iter()
        .any(|r| r.command_type.as_str().starts_with("review."))
        && !crate::legacy_review::is_active_in(tx, &header.workspace)?
    {
        return Err(conversion_invalid());
    }
    Ok(page)
}

fn conversion_known(
    tx: &Transaction<'_>,
    workspace: &str,
    request: &ExecuteRequest,
) -> Result<(), ExecuteError> {
    let known = crate::execute::known_request_digest_in(tx, workspace, &request.command_id)?
        .ok_or_else(conversion_invalid)?;
    if known != crate::execute::original_request_digest(request) {
        return Err(ExecuteError::CommandIdReused);
    }
    Ok(())
}

fn mark_conversion(
    tx: &Transaction<'_>,
    workspace: &str,
    page: &LegacyConversionPage,
    requests: &[ExecuteRequest],
) -> Result<(), ExecuteError> {
    for (source, request) in page.items.iter().zip(requests) {
        tx.execute("UPDATE drafts SET fields=?3 WHERE workspace_id=?1 AND editor_kind='legacy_outbox_resolution' AND record_key=?2",
            params![workspace,source.entry_id,json!({"standing":"converted","command_id":request.command_id,"resolved_at":request.context.now}).to_string().into_bytes()])?;
    }
    Ok(())
}

fn conversion_progress(
    tx: &Transaction<'_>,
    header: &ConversionHeader,
) -> Result<LegacyConversionProgress, ExecuteError> {
    let processed_count = if header.atomic_group && !header.completed {
        tx.query_row(
            "SELECT COUNT(*) FROM drafts WHERE workspace_id=?1 AND editor_kind=?2",
            params![header.workspace, CONVERSION_ITEM_KIND],
            |r| r.get(0),
        )?
    } else {
        let mut count = 0;
        conversion_sources(tx, &header.workspace, |_, _, standing, _| {
            count += u64::from(standing == "converted");
            Ok(())
        })?;
        count
    };
    Ok(LegacyConversionProgress {
        source_count: header.source_count,
        processed_count,
        complete: (!header.atomic_group || header.completed)
            && processed_count == header.source_count,
        status: status_in(tx, &header.workspace)?,
    })
}

pub fn convert_legacy_page_with(
    store: &mut Store,
    ids: &mut impl IdSource,
    token: &str,
    page_token: &str,
    entry_ids: &[String],
    requests: &[ExecuteRequest],
    before_commit: impl FnOnce(&Transaction<'_>) -> Result<(), ExecuteError>,
) -> Result<LegacyConversionProgress, ExecuteError> {
    store.try_write(|tx| {
        let header = conversion_header(tx, token)?;
        if header.atomic_group {
            return Err(conversion_invalid());
        }
        let page = prepared_conversion_page(tx, &header, page_token, entry_ids, requests)?;
        let mut expected = page.items.iter().zip(requests).peekable();
        let mut blocked = false;
        let mut unsent_started = false;
        conversion_sources(tx, &header.workspace, |_, entry, standing, _| {
            if expected
                .peek()
                .is_some_and(|(source, _)| source.entry_id == entry.id)
            {
                let (_, request) = expected.next().ok_or_else(conversion_invalid)?;
                if standing == "converted" {
                    if unsent_started {
                        return Err(conversion_invalid());
                    }
                    conversion_known(tx, &header.workspace, request)?;
                } else {
                    if blocked {
                        return Err(conversion_invalid());
                    }
                    unsent_started = true;
                }
            } else if standing == "unsent" {
                blocked = true;
            }
            Ok(())
        })?;
        if expected.next().is_some() {
            return Err(conversion_invalid());
        }
        execute_batch_in(tx, ids, requests)?;
        mark_conversion(tx, &header.workspace, &page, requests)?;
        let progress = conversion_progress(tx, &header)?;
        before_commit(tx)?;
        Ok(progress)
    })
}

fn conversion_seal(
    tx: &Transaction<'_>,
    header: &ConversionHeader,
    completed: bool,
) -> Result<String, ExecuteError> {
    let mut digest = crate::DigestStream::default();
    conversion_sources(tx, &header.workspace, |ordinal, entry, standing, _| {
        let fingerprint = if completed {
            if standing != "converted" {
                return Err(conversion_invalid());
            }
            let key = CommandId::parse(entry.key.as_deref().ok_or_else(conversion_invalid)?)
                .map_err(|_| conversion_invalid())?;
            crate::execute::known_request_digest_in(tx, &header.workspace, &key)?
                .ok_or_else(conversion_invalid)?
        } else {
            if standing != "unsent" {
                return Err(conversion_invalid());
            }
            let bytes: Option<Vec<u8>> = tx.query_row("SELECT fields FROM drafts WHERE workspace_id=?1 AND draft_id=?2 AND editor_kind=?3",
                params![header.workspace,format!("{CONVERSION_HEADER}:{ordinal}"),CONVERSION_ITEM_KIND],|r|r.get(0)).optional()?;
            let request: ExecuteRequest =
                conversion_decode(bytes.as_deref().ok_or_else(conversion_invalid)?)?;
            crate::execute::original_request_digest(&request)
        };
        conversion_part(&mut digest, ordinal.as_bytes());
        conversion_part(&mut digest, &fingerprint);
        Ok(())
    })?;
    Ok(digest.digest())
}

pub fn stage_legacy_page_with(
    store: &mut Store,
    token: &str,
    page_token: &str,
    entry_ids: &[String],
    requests: &[ExecuteRequest],
    before_commit: impl FnOnce(&Transaction<'_>) -> Result<(), ExecuteError>,
) -> Result<LegacyConversionProgress, ExecuteError> {
    store.try_write(|tx| {
        let mut header = conversion_header(tx,token)?;
        if !header.atomic_group {return Err(conversion_invalid());}
        let page = prepared_conversion_page(tx,&header,page_token,entry_ids,requests)?;
        // Completed retries check every original fingerprint without rebuilding
        // payload staging. A mixed converted/unsent group is never executable.
        conversion_sources(tx,&header.workspace, |_,_,standing,_| {
            if (standing=="converted")!=header.completed {return Err(conversion_invalid());} Ok(())
        })?;
        if header.completed {
            for request in requests {conversion_known(tx,&header.workspace,request)?;}
            if header.seal.as_ref()!=Some(&conversion_seal(tx,&header,true)?) {return Err(conversion_invalid());}
        } else {
            let mut positions = HashMap::new();
            conversion_sources(tx,&header.workspace, |ordinal,entry,_,_| {if page.items.iter().any(|s|s.entry_id==entry.id){positions.insert(entry.id.clone(),ordinal.to_owned());}Ok(())})?;
            // Every earlier source entry must already be staged; no gaps.
            let first = positions.get(&page.items[0].entry_id).ok_or_else(conversion_invalid)?;
            conversion_sources(tx,&header.workspace, |ordinal,_,_,_| {
                if ordinal < first.as_str() {
                    let present: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM drafts WHERE workspace_id=?1 AND draft_id=?2 AND editor_kind=?3)",
                        params![header.workspace,format!("{CONVERSION_HEADER}:{ordinal}"),CONVERSION_ITEM_KIND],|r|r.get(0))?;
                    if !present {return Err(conversion_invalid());}
                } Ok(())
            })?;
            for (source,request) in page.items.iter().zip(requests) {
                let id = format!("{CONVERSION_HEADER}:{}",positions.get(&source.entry_id).ok_or_else(conversion_invalid)?);
                let bytes = conversion_json(request)?;
                let old: Option<Vec<u8>> = tx.query_row("SELECT fields FROM drafts WHERE workspace_id=?1 AND draft_id=?2 AND editor_kind=?3",
                    params![header.workspace,id,CONVERSION_ITEM_KIND],|r|r.get(0)).optional()?;
                if let Some(old) = old {
                    let previous: ExecuteRequest = conversion_decode(&old)?;
                    if crate::execute::original_request_digest(&previous)!=crate::execute::original_request_digest(request) {return Err(ExecuteError::CommandIdReused);}
                } else {
                    tx.execute("INSERT INTO drafts(workspace_id,draft_id,editor_kind,record_key,fields,updated_at) VALUES(?1,?2,?3,?4,?5,?6)",
                        params![header.workspace,id,CONVERSION_ITEM_KIND,source.entry_id,bytes,source.issued_at.as_str()])?;
                }
            }
            let count = conversion_progress(tx,&header)?.processed_count;
            if count==header.source_count {
                header.seal=Some(conversion_seal(tx,&header,false)?);
                save_conversion_header(tx,&header)?;
            }
        }
        let progress = conversion_progress(tx,&header)?;
        before_commit(tx)?;
        Ok(progress)
    })
}

pub fn finalize_legacy_conversion_with(
    store: &mut Store,
    ids: &mut impl IdSource,
    token: &str,
    before_commit: impl FnOnce(&Transaction<'_>) -> Result<(), ExecuteError>,
) -> Result<LegacyConversionProgress, ExecuteError> {
    store.try_write(|tx| {
        let mut header=conversion_header(tx,token)?;
        if !header.atomic_group || header.seal.as_ref()!=Some(&conversion_seal(tx,&header,header.completed)?) {return Err(conversion_invalid());}
        if !header.completed {
            let mut requests=Vec::new();
            let mut items=Vec::new();
            conversion_sources(tx,&header.workspace, |ordinal,entry,_,_| {
                let bytes: Vec<u8> = tx.query_row("SELECT fields FROM drafts WHERE workspace_id=?1 AND draft_id=?2 AND editor_kind=?3",
                    params![header.workspace,format!("{CONVERSION_HEADER}:{ordinal}"),CONVERSION_ITEM_KIND],|r|r.get(0))?;
                let request: ExecuteRequest=conversion_decode(&bytes)?;
                items.push(LegacyUnsent {entry_id:entry.id.clone(),idempotency_key:request.command_id.clone(),issued_at:request.context.now.clone(),command:Value::Null});
                requests.push(request); Ok(())
            })?;
            execute_batch_in(tx,ids,&requests)?;
            mark_conversion(tx,&header.workspace,&LegacyConversionPage {items,page_token:String::new(),next_after:None},&requests)?;
            tx.execute("DELETE FROM drafts WHERE workspace_id=?1 AND editor_kind=?2",params![header.workspace,CONVERSION_ITEM_KIND])?;
            header.completed=true;
            save_conversion_header(tx,&header)?;
        }
        let progress=conversion_progress(tx,&header)?;
        before_commit(tx)?;
        Ok(progress)
    })
}

/// Records the verdict of one entry and the issue (or alias) it implies.
fn settle(
    tx: &Transaction<'_>,
    workspace: &str,
    entry: &Entry,
    answer: &LegacyAnswer,
    (now, at): (&str, UtcInstant),
) -> Result<(), LegacyOutboxError> {
    let mut code = None;
    let mut proven: &[ProvenAlias] = &[];
    let standing = if !entry.sent {
        Standing::Unsent
    } else {
        match answer {
            LegacyAnswer::Accepted { aliases } if provable(tx, workspace, entry, aliases)? => {
                proven = aliases;
                Standing::Accepted
            }
            LegacyAnswer::Rejected { code: reported } => {
                code = Some(clean(reported));
                Standing::Rejected
            }
            _ if entry.key_used
                && entry
                    .first_sent
                    .is_some_and(|first| at < first.plus_seconds(WINDOW_SECONDS)) =>
            {
                Standing::Awaiting
            }
            _ => Standing::Uncertain,
        }
    };

    for alias in proven {
        tx.execute(
            "INSERT OR IGNORE INTO identity_aliases (workspace_id, entity_type, old_local_id,
                server_id, provenance) VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                workspace,
                alias.entity_type.as_str(),
                alias.old_local_id,
                alias.server_id,
                ALIAS_PROVENANCE
            ],
        )?;
    }
    let issue_id = format!("legacy_entry_{}", entry.id);
    match standing {
        Standing::Rejected | Standing::Uncertain => {
            let reason = code.as_deref().unwrap_or(UNKNOWN);
            let content = ("legacy_outbox_entry", &entry.raw);
            save_issue(
                tx,
                workspace,
                (&issue_id, &entry.id),
                content,
                (reason, now),
            )?;
        }
        Standing::Accepted => {
            tx.execute(
                "UPDATE sync_issues SET resolution = 'reconciled', resolved_at = ?3
                 WHERE workspace_id = ?1 AND issue_id = ?2 AND resolution = 'open'",
                params![workspace, issue_id, now],
            )?;
        }
        Standing::Unsent | Standing::Awaiting => {}
    }
    let record = json!({"standing": standing.name(), "resolved_at": now, "code": code});
    tx.execute(
        "INSERT OR REPLACE INTO drafts (workspace_id, draft_id, editor_kind, record_type,
            record_key, fields, base_revision, updated_at)
         VALUES (?1, ?2, ?3, 'pending_operation', ?4, ?5, NULL, ?6)",
        params![
            workspace,
            format!("legacy-resolution:{}", entry.id),
            KIND_RESOLUTION,
            entry.id,
            record.to_string().into_bytes(),
            now
        ],
    )?;
    Ok(())
}

/// A receipt proves an identity only when the old command uses the local ID as an identifier
/// of that entity type (see [`names`]) and no different server ID was proven for it before
/// or claimed for the same typed local ID by this receipt.
fn provable(
    tx: &Transaction<'_>,
    workspace: &str,
    entry: &Entry,
    aliases: &[ProvenAlias],
) -> Result<bool, LegacyOutboxError> {
    let command = entry.raw.get("command").unwrap_or(&Value::Null);
    let mut claimed = HashMap::new();
    for alias in aliases {
        let typed_id = (alias.entity_type.as_str(), alias.old_local_id.as_str());
        if claimed
            .insert(typed_id, alias.server_id.as_str())
            .is_some_and(|server| server != alias.server_id)
        {
            return Ok(false);
        }
        let known: Option<String> = tx
            .query_row(
                "SELECT server_id FROM identity_aliases
                 WHERE workspace_id = ?1 AND entity_type = ?2 AND old_local_id = ?3",
                params![workspace, alias.entity_type.as_str(), alias.old_local_id],
                |row| row.get(0),
            )
            .optional()?;
        if alias.server_id.is_empty()
            || !names(command, alias.entity_type, &alias.old_local_id)
            || known.is_some_and(|server| server != alias.server_id)
        {
            return Ok(false);
        }
    }
    Ok(true)
}

/// Whether the old command uses `id` as an identifier of `entity`: only in the fields the
/// legacy `GTDCommand` shape defines as that entity's IDs, never in text. The command is
/// `{"<case>": payload}` where a struct payload sits under `_0`; `[]` ends a path to an
/// array of IDs.
fn names(command: &Value, entity: EntityType, id: &str) -> bool {
    let Some((case, payload)) = command.as_object().and_then(|map| map.iter().next()) else {
        return false;
    };
    let payload = payload
        .get("_0")
        .filter(|inner| inner.is_object())
        .unwrap_or(payload);
    let paths: &[&str] = match (entity, case.as_str()) {
        (EntityType::Task, _) => &["taskID", "followUpTaskID", "taskIDs[]"],
        (EntityType::Project, "archiveProject") => &["_0"],
        (EntityType::Project, _) => &["projectID", "project", "changes/projectID/set/_0"],
        (EntityType::Tag, "deleteTag") => &["_0"],
        (EntityType::Tag, _) => &["tagID", "tagIDs[]", "changes/tagIDs/set/_0[]"],
        (EntityType::Subtask, _) => &["subtaskID"],
        (EntityType::Comment, _) => &["commentID"],
        _ => &[],
    };
    paths.iter().any(|path| {
        let (path, many) = path
            .strip_suffix("[]")
            .map_or((*path, false), |p| (p, true));
        let found = path
            .split('/')
            .try_fold(payload, |value, key| value.get(key));
        match found {
            Some(Value::String(text)) => !many && text == id,
            Some(Value::Array(items)) => many && items.iter().any(|item| item.as_str() == Some(id)),
            _ => false,
        }
    })
}

/// An error code of a receipt, kept only when it is the shape of one.
fn clean(code: &str) -> String {
    let shaped = !code.is_empty()
        && code.len() <= 64
        && code
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || b == b'_');
    if shaped {
        code.to_owned()
    } else {
        REJECTED.to_owned()
    }
}

/// The text the user wrote in an old command, by member.
fn user_text(command: &Value) -> Option<String> {
    fn walk(value: &Value, found: &mut Map<String, Value>) {
        match value {
            Value::Object(map) => {
                for (member, inner) in map {
                    if TEXT_MEMBERS.contains(&member.as_str()) && !inner.is_null() {
                        found.entry(member.clone()).or_insert_with(|| inner.clone());
                    } else {
                        walk(inner, found);
                    }
                }
            }
            Value::Array(items) => items.iter().for_each(|item| walk(item, found)),
            _ => {}
        }
    }
    let mut found = Map::new();
    walk(command, &mut found);
    (!found.is_empty()).then(|| Value::Object(found).to_string())
}

/// Saves an open issue holding the old record whole, once; a repeat only updates the
/// reason of one that is still open. `ids` are the issue's and its command's.
fn save_issue(
    tx: &Transaction<'_>,
    workspace: &str,
    ids: (&str, &str),
    (member, raw): (&str, &Value),
    (reason, at): (&str, &str),
) -> Result<(), LegacyOutboxError> {
    tx.execute(
        "INSERT OR IGNORE INTO sync_issues (workspace_id, issue_id, command_id, reason,
            local_intent, local_text, shown_base_revision, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, NULL, ?7)",
        params![
            workspace,
            ids.0,
            ids.1,
            reason,
            json!({ member: raw }).to_string().into_bytes(),
            user_text(raw.get("command").unwrap_or(&Value::Null)),
            at
        ],
    )?;
    tx.execute(
        "UPDATE sync_issues SET reason = ?3
         WHERE workspace_id = ?1 AND issue_id = ?2 AND resolution = 'open'",
        params![workspace, ids.0, reason],
    )?;
    Ok(())
}

/// The old file's own unresolved issues become issues of the new store.
fn convert_issues(
    tx: &Transaction<'_>,
    workspace: &str,
    now: &str,
) -> Result<(), LegacyOutboxError> {
    let mut statement = tx.prepare(
        "SELECT fields FROM drafts WHERE workspace_id = ?1 AND editor_kind = ?2 ORDER BY draft_id",
    )?;
    let carried = statement.query_map(params![workspace, KIND_ISSUE], |row| {
        row.get::<_, Vec<u8>>(0)
    })?;
    for bytes in carried {
        let raw: Value = serde_json::from_slice(&bytes?).map_err(|_| unreadable("issues"))?;
        let id = raw
            .get("id")
            .and_then(Value::as_str)
            .filter(|id| CommandId::parse(*id).is_ok())
            .ok_or(unreadable("issues"))?;
        let at = raw.get("occurredAt").and_then(Value::as_str).unwrap_or(now);
        let issue_id = format!("legacy_issue_{id}");
        let content = ("legacy_sync_issue", &raw);
        save_issue(tx, workspace, (&issue_id, id), content, (REJECTED, at))?;
    }
    Ok(())
}

fn status_in(tx: &Transaction<'_>, workspace: &str) -> rusqlite::Result<LegacyOutboxStatus> {
    let scalar = |sql: &str, argument: &str| -> rusqlite::Result<u64> {
        let value: i64 = tx.query_row(sql, params![workspace, argument], |row| row.get(0))?;
        Ok(u64::try_from(value).unwrap_or(0))
    };
    let drafts = "SELECT COUNT(*) FROM drafts WHERE workspace_id = ?1 AND editor_kind = ?2";
    let standing = |name: &str| {
        scalar(
            "SELECT COUNT(*) FROM drafts WHERE workspace_id = ?1 AND editor_kind = 'legacy_outbox_resolution'
               AND json_extract(CAST(fields AS TEXT), '$.standing') = ?2",
            name,
        )
    };
    let issues = |pattern: &str| {
        scalar(
            "SELECT COUNT(*) FROM sync_issues WHERE workspace_id = ?1 AND issue_id GLOB ?2",
            pattern,
        )
    };
    let converted = standing("converted")?;
    let completed = scalar(
        "SELECT COUNT(*) FROM drafts d JOIN outbox o ON o.workspace_id = d.workspace_id
        AND o.command_id = json_extract(CAST(d.fields AS TEXT), '$.command_id')
        WHERE d.workspace_id = ?1 AND d.editor_kind = 'legacy_outbox_resolution'
        AND json_extract(CAST(d.fields AS TEXT), '$.standing') = ?2 AND o.state = 'completed'",
        "converted",
    )?;
    Ok(LegacyOutboxStatus {
        carried: scalar(drafts, KIND_OUTBOX)?,
        unsent: standing(Standing::Unsent.name())?,
        converted: converted - completed,
        accepted: standing(Standing::Accepted.name())? + completed,
        rejected: standing(Standing::Rejected.name())?,
        awaiting: standing(Standing::Awaiting.name())?,
        uncertain: standing(Standing::Uncertain.name())?,
        carried_issues: scalar(drafts, KIND_ISSUE)?,
        converted_issues: issues("legacy_issue_*")?,
        open_issues: scalar(
            "SELECT COUNT(*) FROM sync_issues WHERE workspace_id = ?1 AND resolution = 'open'
               AND (issue_id GLOB 'legacy_entry_*' OR issue_id GLOB ?2)",
            "legacy_issue_*",
        )?,
        aliases: scalar(
            "SELECT COUNT(*) FROM identity_aliases WHERE workspace_id = ?1 AND provenance = ?2",
            ALIAS_PROVENANCE,
        )?,
    })
}
