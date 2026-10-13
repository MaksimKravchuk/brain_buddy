//! Account-data export for the local store (026-FR-003, 026-FR-023).
//!
//! One read transaction yields what the person authored on this device: the
//! visible records, the commands still waiting to be sent, the sync issues
//! that keep a rejected intent, the user-authored drafts and the identity
//! aliases that tie old local IDs to server IDs. Everything is read in one
//! snapshot, so a command and the issue that names it can never be split.
//!
//! Left out on purpose: envelope digests and receipt bodies (fingerprints),
//! the `sync_meta` cursor and generation fences, staging pages, and device
//! only facts (task origins, form overlays). A key that names a digest, token
//! or credential is removed from any exported JSON, so a future envelope
//! field cannot leak by default.
//!
//! Failures carry a stage and a store code only, never a row or its text.
use crate::{Store, StoreError};
use rusqlite::{Transaction, params};
use serde::Serialize;
use serde_json::Value;
use std::fmt;
use std::time::Instant;

pub const EXPORT_FORMAT: &str = "brain-buddy-local-export/v1";

/// Draft kinds that hold text the person typed. The other kinds are
/// device-only bookkeeping (origins, overlays, import carriers).
const AUTHORED_DRAFT_KINDS: [&str; 1] = ["review_form_draft"];

/// Substrings of a JSON key that mark protected material.
const PROTECTED_KEY_PARTS: [&str; 6] = [
    "fingerprint",
    "digest",
    "token",
    "secret",
    "password",
    "credential",
];

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ExportedRecord {
    pub record_type: String,
    pub record_key: String,
    pub edit_revision: Option<String>,
    pub body: Value,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ExportedIntent {
    pub command_id: String,
    pub state: String,
    pub local_seq: i64,
    pub depends_on: Vec<String>,
    pub created_at: String,
    pub envelope: Value,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ExportedIssue {
    pub issue_id: String,
    pub command_id: String,
    pub reason: String,
    pub resolution: String,
    pub local_intent: Value,
    pub local_text: Option<String>,
    pub shown_base_revision: Option<String>,
    pub dependent_ids: Vec<String>,
    pub created_at: String,
    pub resolved_at: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ExportedAlias {
    pub entity_type: String,
    pub old_local_id: String,
    pub server_id: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ExportedDraft {
    pub draft_id: String,
    pub editor_kind: String,
    pub record_type: Option<String>,
    pub record_key: Option<String>,
    pub base_revision: Option<String>,
    pub updated_at: String,
    pub fields: Value,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct WorkspaceExport {
    pub format: &'static str,
    pub workspace_id: String,
    pub visible_records: Vec<ExportedRecord>,
    pub pending_intents: Vec<ExportedIntent>,
    pub issues: Vec<ExportedIssue>,
    pub identity_aliases: Vec<ExportedAlias>,
    pub drafts: Vec<ExportedDraft>,
}

/// The only thing that may be logged about an export: counts and timing.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
pub struct ExportReport {
    pub visible_records: usize,
    pub pending_intents: usize,
    pub issues: usize,
    pub identity_aliases: usize,
    pub drafts: usize,
    pub elapsed_ms: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ExportStage {
    Records,
    Intents,
    Issues,
    Aliases,
    Drafts,
}

impl ExportStage {
    pub fn code(self) -> &'static str {
        match self {
            Self::Records => "EXPORT_RECORDS",
            Self::Intents => "EXPORT_INTENTS",
            Self::Issues => "EXPORT_ISSUES",
            Self::Aliases => "EXPORT_ALIASES",
            Self::Drafts => "EXPORT_DRAFTS",
        }
    }
}

/// Which step failed and the store's stable code; never the row involved.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExportError {
    pub stage: ExportStage,
    pub store: StoreError,
}

impl fmt::Display for ExportError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.stage.code(), self.store.code())
    }
}

impl std::error::Error for ExportError {}

fn at(stage: ExportStage) -> impl Fn(rusqlite::Error) -> ExportError {
    move |error| ExportError {
        stage,
        store: error.into(),
    }
}

fn corrupt(stage: ExportStage) -> ExportError {
    ExportError {
        stage,
        store: StoreError::Corrupt,
    }
}

/// Parses stored JSON and removes every protected key at any depth.
fn safe_json(stage: ExportStage, raw: &[u8]) -> Result<Value, ExportError> {
    let mut value: Value = serde_json::from_slice(raw).map_err(|_| corrupt(stage))?;
    strip_protected(&mut value);
    Ok(value)
}

fn strip_protected(value: &mut Value) {
    match value {
        Value::Object(map) => {
            map.retain(|key, _| {
                let key = key.to_ascii_lowercase();
                !PROTECTED_KEY_PARTS.iter().any(|part| key.contains(part))
            });
            map.values_mut().for_each(strip_protected);
        }
        Value::Array(items) => items.iter_mut().for_each(strip_protected),
        _ => {}
    }
}

/// Reads the whole export in one transaction.
pub fn export_workspace(
    store: &mut Store,
    workspace: &str,
) -> Result<(WorkspaceExport, ExportReport), ExportError> {
    let started = Instant::now();
    let export = store
        .read(|tx| Ok(collect(tx, workspace)))
        .map_err(|store| ExportError {
            stage: ExportStage::Records,
            store,
        })??;
    let report = ExportReport {
        visible_records: export.visible_records.len(),
        pending_intents: export.pending_intents.len(),
        issues: export.issues.len(),
        identity_aliases: export.identity_aliases.len(),
        drafts: export.drafts.len(),
        elapsed_ms: u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX),
    };
    Ok((export, report))
}

fn collect(tx: &Transaction<'_>, workspace: &str) -> Result<WorkspaceExport, ExportError> {
    Ok(WorkspaceExport {
        format: EXPORT_FORMAT,
        workspace_id: workspace.to_string(),
        visible_records: records(tx, workspace)?,
        pending_intents: intents(tx, workspace)?,
        issues: issues(tx, workspace)?,
        identity_aliases: aliases(tx, workspace)?,
        drafts: drafts(tx, workspace)?,
    })
}

fn records(tx: &Transaction<'_>, workspace: &str) -> Result<Vec<ExportedRecord>, ExportError> {
    let stage = ExportStage::Records;
    let mut statement = tx
        .prepare(
            "SELECT record_type, record_key, edit_revision, body FROM visible_records
             WHERE workspace_id = ?1 ORDER BY record_type, record_key",
        )
        .map_err(at(stage))?;
    let rows = statement
        .query_map([workspace], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<String>>(2)?,
                row.get::<_, Vec<u8>>(3)?,
            ))
        })
        .map_err(at(stage))?;
    let mut out = Vec::new();
    for row in rows {
        let (record_type, record_key, edit_revision, body) = row.map_err(at(stage))?;
        out.push(ExportedRecord {
            record_type,
            record_key,
            edit_revision,
            body: safe_json(stage, &body)?,
        });
    }
    Ok(out)
}

/// Unfinished commands, plus any finished one an issue still names, so an
/// issue's `command_id` always resolves inside the export.
fn intents(tx: &Transaction<'_>, workspace: &str) -> Result<Vec<ExportedIntent>, ExportError> {
    let stage = ExportStage::Intents;
    let mut statement = tx
        .prepare(
            "SELECT command_id, state, local_seq, created_at, envelope FROM outbox
             WHERE workspace_id = ?1 AND (state <> 'completed' OR command_id IN
                 (SELECT command_id FROM sync_issues WHERE workspace_id = ?1))
             ORDER BY local_seq",
        )
        .map_err(at(stage))?;
    let rows = statement
        .query_map([workspace], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, Vec<u8>>(4)?,
            ))
        })
        .map_err(at(stage))?;
    let mut dependencies = tx
        .prepare(
            "SELECT depends_on FROM outbox_dependencies
             WHERE workspace_id = ?1 AND command_id = ?2 ORDER BY depends_on",
        )
        .map_err(at(stage))?;
    let mut out = Vec::new();
    for row in rows {
        let (command_id, state, local_seq, created_at, envelope) = row.map_err(at(stage))?;
        let depends_on = dependencies
            .query_map(params![workspace, command_id], |row| row.get(0))
            .map_err(at(stage))?
            .collect::<Result<Vec<String>, _>>()
            .map_err(at(stage))?;
        out.push(ExportedIntent {
            command_id,
            state,
            local_seq,
            depends_on,
            created_at,
            envelope: safe_json(stage, &envelope)?,
        });
    }
    Ok(out)
}

fn issues(tx: &Transaction<'_>, workspace: &str) -> Result<Vec<ExportedIssue>, ExportError> {
    let stage = ExportStage::Issues;
    let mut statement = tx
        .prepare(
            "SELECT issue_id, command_id, reason, resolution, local_intent, local_text,
                    shown_base_revision, dependent_ids, created_at, resolved_at
             FROM sync_issues WHERE workspace_id = ?1 ORDER BY created_at, issue_id",
        )
        .map_err(at(stage))?;
    let rows = statement
        .query_map([workspace], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, Vec<u8>>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, Option<String>>(6)?,
                row.get::<_, String>(7)?,
                row.get::<_, String>(8)?,
                row.get::<_, Option<String>>(9)?,
            ))
        })
        .map_err(at(stage))?;
    let mut out = Vec::new();
    for row in rows {
        let (
            issue_id,
            command_id,
            reason,
            resolution,
            intent,
            text,
            shown,
            dependents,
            created,
            resolved,
        ) = row.map_err(at(stage))?;
        out.push(ExportedIssue {
            issue_id,
            command_id,
            reason,
            resolution,
            local_intent: safe_json(stage, &intent)?,
            local_text: text,
            shown_base_revision: shown,
            dependent_ids: serde_json::from_str(&dependents).map_err(|_| corrupt(stage))?,
            created_at: created,
            resolved_at: resolved,
        });
    }
    Ok(out)
}

fn aliases(tx: &Transaction<'_>, workspace: &str) -> Result<Vec<ExportedAlias>, ExportError> {
    let stage = ExportStage::Aliases;
    let mut statement = tx
        .prepare(
            "SELECT entity_type, old_local_id, server_id FROM identity_aliases
             WHERE workspace_id = ?1 ORDER BY entity_type, old_local_id",
        )
        .map_err(at(stage))?;
    statement
        .query_map([workspace], |row| {
            Ok(ExportedAlias {
                entity_type: row.get(0)?,
                old_local_id: row.get(1)?,
                server_id: row.get(2)?,
            })
        })
        .map_err(at(stage))?
        .collect::<Result<_, _>>()
        .map_err(at(stage))
}

fn drafts(tx: &Transaction<'_>, workspace: &str) -> Result<Vec<ExportedDraft>, ExportError> {
    let stage = ExportStage::Drafts;
    let mut statement = tx
        .prepare(
            "SELECT draft_id, editor_kind, record_type, record_key, base_revision, updated_at,
                    fields FROM drafts WHERE workspace_id = ?1 ORDER BY draft_id",
        )
        .map_err(at(stage))?;
    let rows = statement
        .query_map([workspace], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<String>>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, Option<String>>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, Vec<u8>>(6)?,
            ))
        })
        .map_err(at(stage))?;
    let mut out = Vec::new();
    for row in rows {
        let (draft_id, editor_kind, record_type, record_key, base_revision, updated_at, fields) =
            row.map_err(at(stage))?;
        if !AUTHORED_DRAFT_KINDS.contains(&editor_kind.as_str()) {
            continue;
        }
        out.push(ExportedDraft {
            draft_id,
            editor_kind,
            record_type,
            record_key,
            base_revision,
            updated_at,
            fields: safe_json(stage, &fields)?,
        });
    }
    Ok(out)
}
