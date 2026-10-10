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
//! Matching is by idempotency key alone. A title, a list or a time is never proof.
//! The lookup is a port ([`ReceiptLookup`]); it is called outside any
//! transaction, and the verdicts are applied in one write transaction that
//! re-reads what it depends on. Every entry is accounted for or nothing is saved.

use crate::import::{KIND_ISSUE, KIND_OUTBOX, legacy_import_marker};
use crate::storage::{Store, StoreError};
use bb_domain::calendar::UtcInstant;
use bb_protocol::catalog::EntityType;
use bb_protocol::wire::{CommandId, Instant};
use rusqlite::{OptionalExtension, Transaction, params};
use serde_json::{Map, Value, json};
use std::collections::{BTreeMap, HashMap};

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
    /// The `Idempotency-Key` the send was made with: the only thing that matches.
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
/// `UUID` prints upper case). A key without an answer is `Unproven`.
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
        self.carried == self.unsent + self.accepted + self.rejected + self.awaiting + self.uncertain
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
        self.may_run() && self.rejected + self.awaiting + self.uncertain + self.open_issues == 0
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
    let entries = fields(KIND_OUTBOX)?
        .into_iter()
        .map(|(_, raw)| Entry::read(raw))
        .collect::<Result<_, _>>()?;
    let standings = fields(KIND_RESOLUTION)?
        .into_iter()
        .filter_map(|(id, value)| Some((id, value.get("standing")?.as_str()?.to_owned())))
        .collect();
    Ok(Loaded {
        workspace,
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
            let answer = answers
                .get(&entry.id)
                .cloned()
                .unwrap_or(LegacyAnswer::Unproven);
            settle(tx, &loaded.workspace, entry, &answer, (now.as_str(), at))?;
        }
        convert_issues(tx, &loaded.workspace, now.as_str())?;
        Ok(status_in(tx, &loaded.workspace)?)
    })
}

/// The sends still to ask the server about: the carried entries a request may have reached
/// the server for, with no final verdict. Read from the Rust store alone (the carried rows
/// are immutable), so the legacy file is not read again and needs no lock.
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
        .filter(|entry| entry.sent)
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
/// of that entity type (see [`names`]) and no different server ID was proven for it before.
fn provable(
    tx: &Transaction<'_>,
    workspace: &str,
    entry: &Entry,
    aliases: &[ProvenAlias],
) -> Result<bool, LegacyOutboxError> {
    let command = entry.raw.get("command").unwrap_or(&Value::Null);
    for alias in aliases {
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
    Ok(LegacyOutboxStatus {
        carried: scalar(drafts, KIND_OUTBOX)?,
        unsent: standing(Standing::Unsent.name())?,
        accepted: standing(Standing::Accepted.name())?,
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
