//! Activate the trusted native Review codec's public projection. This adapter
//! verifies migration bookkeeping and identity evidence; it does not rederive
//! the native codec's business fields. Immutable carriers retain private state.
use crate::apply_changes::install_change;
use crate::execute::{ExecuteContext, ExecuteError, read_projection};
use crate::import::{ImportMarker, SourceCounts, legacy_record_key};
use crate::{Store, StoreError, replay_in, sha256_hex};
use bb_domain::types::{ReadSet, Record};
use bb_protocol::catalog::EntityType;
use bb_protocol::feed::{Change, Operation};
use bb_protocol::wire::Counter;
use rusqlite::{Connection, OptionalExtension, Transaction, params};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

const MARKER: &str = "runtime-legacy-review-activation";

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LegacyReviewToken {
    pub workspace_id: String,
    pub import_source_sha256: String,
    pub review_sha256: String,
    pub projection_generation: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LegacyReviewAlias {
    pub entity_type: EntityType,
    pub local_id: String,
    pub server_id: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct LegacyReviewCapture {
    pub token: LegacyReviewToken,
    pub review: Value,
    pub aliases: Vec<LegacyReviewAlias>,
    pub source_counts: SourceCounts,
    pub already_active: bool,
}

/// Projections synthesized by the existing native codec, distinct from source
/// aggregate counts. Rust checks cardinalities, not the business derivation.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct LegacyReviewDerivedCounts {
    pub decision_queues: u64,
    pub unseen_park_acks: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct PreparedLegacyReview {
    pub token: LegacyReviewToken,
    pub read_set: ReadSet,
    pub aliases: Vec<LegacyReviewAlias>,
    #[serde(default)]
    pub derived_counts: LegacyReviewDerivedCounts,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LegacyReviewActivated {
    pub projection_generation: u64,
    pub already_active: bool,
    pub aliases: Vec<LegacyReviewAlias>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum LegacyReviewError {
    Store(StoreError),
    Cancelled,
    MissingImport,
    SourceChanged,
    TargetNotEmpty,
    Invalid(&'static str),
    AlreadyActivated,
}

impl LegacyReviewError {
    pub fn code(&self) -> &'static str {
        match self {
            Self::Store(error) => error.code(),
            Self::Cancelled => "CANCELLED",
            Self::MissingImport => "LEGACY_REVIEW_IMPORT_REQUIRED",
            Self::SourceChanged => "LEGACY_REVIEW_SOURCE_CHANGED",
            Self::TargetNotEmpty => "LEGACY_REVIEW_TARGET_NOT_EMPTY",
            Self::Invalid(_) => "VALIDATION_FAILED",
            Self::AlreadyActivated => "LEGACY_REVIEW_ALREADY_ACTIVATED",
        }
    }
    pub fn is_retryable(&self) -> bool {
        matches!(self, Self::Store(error) if error.is_retryable())
    }
    pub fn field(&self) -> Option<&'static str> {
        if let Self::Invalid(field) = self {
            Some(field)
        } else {
            None
        }
    }
}
impl std::fmt::Display for LegacyReviewError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for LegacyReviewError {}
impl From<StoreError> for LegacyReviewError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}
impl From<rusqlite::Error> for LegacyReviewError {
    fn from(error: rusqlite::Error) -> Self {
        Self::Store(error.into())
    }
}

#[derive(Serialize, Deserialize)]
struct Marker {
    token: LegacyReviewToken,
    prepared_sha256: String,
    result: LegacyReviewActivated,
}

fn decode<T: serde::de::DeserializeOwned>(body: &[u8]) -> Result<T, LegacyReviewError> {
    serde_json::from_slice(body).map_err(|_| StoreError::Corrupt.into())
}
fn marker(conn: &Connection, workspace: &str) -> Result<Option<Marker>, LegacyReviewError> {
    conn.query_row("SELECT fields FROM drafts WHERE workspace_id = ?1 AND draft_id = ?2 AND editor_kind = 'runtime_legacy_review_activation'",
        params![workspace, MARKER], |r| r.get::<_, Vec<u8>>(0)).optional()?.map(|body| decode(&body)).transpose()
}
/// Conversion of imported Review commands requires the atomic activation marker.
pub(crate) fn is_active_in(conn: &Connection, workspace: &str) -> Result<bool, StoreError> {
    match marker(conn, workspace) {
        Ok(Some(done)) if done.token.workspace_id == workspace => Ok(true),
        Ok(None) => Ok(false),
        Ok(Some(_)) => Err(StoreError::Corrupt),
        Err(LegacyReviewError::Store(error)) => Err(error),
        Err(_) => Err(StoreError::Corrupt),
    }
}
pub(crate) fn capture_in(tx: &Transaction<'_>) -> Result<LegacyReviewCapture, LegacyReviewError> {
    let found: i64 = tx.query_row("PRAGMA user_version", [], |r| r.get(0))?;
    if found != crate::SCHEMA_VERSION {
        return Err(StoreError::UpgradeRequired { found }.into());
    }
    let (workspace, generation): (String, i64) = tx.query_row(
        "SELECT workspace_id, projection_generation FROM sync_meta",
        [],
        |r| Ok((r.get(0)?, r.get(1)?)),
    )?;
    let import: Option<Vec<u8>> = tx.query_row("SELECT manifest FROM staging_bases WHERE workspace_id = ?1 AND activation_id LIKE 'legacy-import-%' AND state = 'activated'", [&workspace], |r| r.get(0)).optional()?;
    let import: ImportMarker = decode(&import.ok_or(LegacyReviewError::MissingImport)?)?;
    let body: Vec<u8> = tx.query_row("SELECT fields FROM drafts WHERE workspace_id = ?1 AND draft_id = 'legacy-review-base' AND editor_kind = 'legacy_review_base'", [&workspace], |r| r.get(0))?;
    let review: Value = decode(&body)?;
    if !review.is_object() {
        return Err(StoreError::Corrupt.into());
    }
    let mut token = LegacyReviewToken {
        workspace_id: workspace.clone(),
        import_source_sha256: import.source_sha256,
        review_sha256: sha256_hex(&body),
        projection_generation: u64::try_from(generation).map_err(|_| StoreError::Corrupt)?,
    };
    let done = marker(tx, &workspace)?;
    if let Some(done) = &done {
        if done.token.workspace_id != token.workspace_id
            || done.token.import_source_sha256 != token.import_source_sha256
            || done.token.review_sha256 != token.review_sha256
        {
            return Err(LegacyReviewError::SourceChanged);
        }
        token = done.token.clone();
    }
    let mut statement = tx.prepare("SELECT entity_type, old_local_id, server_id FROM identity_aliases WHERE workspace_id = ?1 ORDER BY entity_type, old_local_id")?;
    let rows = statement.query_map([&workspace], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
        ))
    })?;
    let mut aliases = Vec::new();
    for row in rows {
        let (kind, local_id, server_id) = row?;
        aliases.push(LegacyReviewAlias {
            entity_type: EntityType::from_wire(&kind).ok_or(StoreError::Corrupt)?,
            local_id,
            server_id,
        });
    }
    Ok(LegacyReviewCapture {
        token,
        review,
        aliases,
        source_counts: import.counts,
        already_active: is_active_in(tx, &workspace)?,
    })
}

pub fn capture_legacy_review(store: &mut Store) -> Result<LegacyReviewCapture, LegacyReviewError> {
    store.read(|tx| Ok(capture_in(tx)))?
}

fn records(read: &ReadSet) -> Result<Vec<Record>, LegacyReviewError> {
    if !read.tasks.is_empty()
        || !read.projects.is_empty()
        || !read.tags.is_empty()
        || !read.subtasks.is_empty()
        || !read.comments.is_empty()
    {
        return Err(LegacyReviewError::Invalid("read_set"));
    }
    let mut records = Vec::new();
    if let Some(settings) = &read.settings {
        records.push(Record::ReviewSettings(settings.clone()));
    }
    for (key, value) in &read.sessions {
        if key != &value.id {
            return Err(LegacyReviewError::Invalid("sessions"));
        }
        records.push(Record::ReviewSession(value.clone()));
    }
    for (key, value) in &read.decision_queues {
        if key != &value.session_id {
            return Err(LegacyReviewError::Invalid("decision_queues"));
        }
        records.push(Record::ReviewDecisionQueue(value.clone()));
    }
    for (key, value) in &read.decisions {
        if key != &value.id {
            return Err(LegacyReviewError::Invalid("decisions"));
        }
        records.push(Record::ReviewDecision(value.clone()));
    }
    records.extend(read.receipts.iter().cloned().map(Record::ReviewReceipt));
    records.extend(read.park_acks.iter().cloned().map(Record::ReviewParkAck));
    for (key, value) in &read.bulk_releases {
        if key != &value.id {
            return Err(LegacyReviewError::Invalid("bulk_releases"));
        }
        records.push(Record::ReviewBulkRelease(value.clone()));
    }
    records.extend(
        read.consents
            .iter()
            .cloned()
            .map(Record::ReviewNavigatorConsent),
    );
    let mut keys = BTreeSet::new();
    for record in &records {
        if *record != record.public() {
            return Err(LegacyReviewError::Invalid("private"));
        }
        if !keys.insert((record.entity_type().as_str(), record.record_key())) {
            return Err(LegacyReviewError::Invalid("record_key"));
        }
    }
    Ok(records)
}

pub fn activate_legacy_review(
    store: &mut Store,
    context: &ExecuteContext,
    prepared: &PreparedLegacyReview,
) -> Result<LegacyReviewActivated, LegacyReviewError> {
    activate_legacy_review_with(store, context, prepared, |_| Ok(()))
}

/// The final callback arbitrates cancellation under the bridge operation guard.
/// It runs for marker retries too; no cancellation is returned after commit.
pub fn activate_legacy_review_with(
    store: &mut Store,
    context: &ExecuteContext,
    prepared: &PreparedLegacyReview,
    before_commit: impl FnOnce(&Transaction<'_>) -> Result<(), LegacyReviewError>,
) -> Result<LegacyReviewActivated, LegacyReviewError> {
    store.try_write(|tx| {
        let capture = capture_in(tx)?;
        let mut records = records(&prepared.read_set)?;
        records.sort_by_key(|record| (record.entity_type().as_str(), record.record_key()));
        let mut aliases = prepared.aliases.clone();
        aliases.sort_by(|a, b| (a.entity_type.as_str(), &a.local_id, &a.server_id).cmp(&(b.entity_type.as_str(), &b.local_id, &b.server_id)));
        let digest = sha256_hex(&serde_json::to_vec(&json!({"token":prepared.token,"records":records,"aliases":aliases,"derived_counts":prepared.derived_counts})).map_err(|_| StoreError::Corrupt)?);
        if let Some(done) = marker(tx, &capture.token.workspace_id)? {
            if done.token != prepared.token || done.prepared_sha256 != digest { return Err(LegacyReviewError::AlreadyActivated); }
            let mut result = done.result; result.already_active = true;
            before_commit(tx)?;
            return Ok(result);
        }
        if capture.token != prepared.token { return Err(LegacyReviewError::SourceChanged); }
        let workspace = &capture.token.workspace_id;
        let dirty: bool = tx.query_row("SELECT EXISTS(SELECT 1 FROM confirmed_records WHERE workspace_id = ?1 AND record_type LIKE 'review_%') OR EXISTS(SELECT 1 FROM visible_records WHERE workspace_id = ?1 AND record_type LIKE 'review_%')", [workspace], |r| r.get(0))?;
        if dirty { return Err(LegacyReviewError::TargetNotEmpty); }
        let live = read_projection(tx, workspace).map_err(|error| match error { ExecuteError::Store(error) => LegacyReviewError::Store(error), _ => LegacyReviewError::Invalid("projection") })?;
        validate(&capture, prepared, &records, &live)?;
        for alias in &prepared.aliases {
            tx.execute("INSERT OR IGNORE INTO identity_aliases (workspace_id,entity_type,old_local_id,server_id,provenance) VALUES (?1,?2,?3,?4,'legacy-review:source-server-id')",
                params![workspace, alias.entity_type.as_str(), alias.local_id, alias.server_id])?;
        }
        // These source primary identities were just admitted against the
        // trusted codec's exact canonical record keys. Preserve that proof for
        // bounded reverse lookups; form readers never infer UUID prefixes.
        let mut admitted_aliases=capture.aliases.clone();
        admitted_aliases.extend(prepared.aliases.iter().cloned());
        for (kind,section) in [(EntityType::ReviewSession,"sessions"),(EntityType::ReviewDecision,"decisions"),(EntityType::ReviewBulkRelease,"bulkReleases")] {
            for local in capture.review.get(section).and_then(Value::as_object).into_iter().flat_map(|items|items.keys()) {
                let canonical=canonical(kind.as_str(),local,&admitted_aliases);
                if canonical!=*local {
                    tx.execute("INSERT OR IGNORE INTO identity_aliases(workspace_id,entity_type,old_local_id,server_id,provenance) VALUES (?1,?2,?3,?4,'legacy-import:normalized-local-id')",params![workspace,kind.as_str(),local,canonical])?;
                }
            }
        }
        for record in &records {
            let value = json!(record)["value"].as_object().ok_or(StoreError::Corrupt)?.clone();
            let change = Change { entity_type: record.entity_type(), record_key: record.record_key(), record_version: Counter::from(crate::import::IMPORTED_VERSION), edit_revision: crate::execute::edit_revision(record), operation: Operation::Upsert, value: Some(value) };
            install_change(tx, workspace, &change).map_err(|error| match error { crate::ApplyError::Store(error) => LegacyReviewError::Store(error), _ => LegacyReviewError::Invalid("record") })?;
        }
        replay_in(tx, context).map_err(|error| match error { crate::ReplayError::Store(error) => LegacyReviewError::Store(error), _ => LegacyReviewError::Invalid("replay") })?;
        // Even an empty projection completes migration bookkeeping durably.
        if records.is_empty() { tx.execute("UPDATE sync_meta SET projection_generation = projection_generation + 1", [])?; }
        let generation: i64 = tx.query_row("SELECT projection_generation FROM sync_meta", [], |r| r.get(0))?;
        let result = LegacyReviewActivated { projection_generation: u64::try_from(generation).map_err(|_| StoreError::Corrupt)?, already_active: false, aliases: prepared.aliases.clone() };
        let done = Marker { token: prepared.token.clone(), prepared_sha256: digest, result: result.clone() };
        tx.execute("INSERT INTO drafts (workspace_id,draft_id,editor_kind,fields,updated_at) VALUES (?1,?2,'runtime_legacy_review_activation',?3,?4)",
            params![workspace, MARKER, serde_json::to_vec(&done).map_err(|_| StoreError::Corrupt)?, context.now.as_str()])?;
        before_commit(tx)?;
        Ok(result)
    })
}

fn validate(
    capture: &LegacyReviewCapture,
    prepared: &PreparedLegacyReview,
    records: &[Record],
    live: &ReadSet,
) -> Result<(), LegacyReviewError> {
    let counts = capture.source_counts;
    let read = &prepared.read_set;
    if read.sessions.len() as u64 != counts.review_sessions
        || read.decisions.len() as u64 != counts.review_decisions
        || read.receipts.len() as u64 != counts.review_receipts
        || read.bulk_releases.len() as u64 != counts.review_bulk_releases
        || read.consents.len() as u64 != counts.review_navigator_consents
        || read.park_acks.len() as u64
            != counts
                .review_park_acks
                .checked_add(prepared.derived_counts.unseen_park_acks)
                .ok_or(LegacyReviewError::Invalid("counts"))?
        || read.decision_queues.len() as u64 != prepared.derived_counts.decision_queues
        || read.decision_queues.len() > read.sessions.len()
    {
        return Err(LegacyReviewError::Invalid("counts"));
    }
    validate_identities(capture, prepared, records, live)
}

pub(crate) fn canonical(kind: &str, local: &str, aliases: &[LegacyReviewAlias]) -> String {
    if let Some(alias) = aliases
        .iter()
        .find(|alias| alias.entity_type.as_str() == kind && alias.local_id == local)
    {
        return alias.server_id.clone();
    }
    if kind == "form" {
        // Existing formulation identities have no independently admitted alias
        // family. Preserve the exact source reference, including UUID case.
        return local.to_owned();
    }
    EntityType::from_wire(kind)
        .map(|kind| legacy_record_key(kind, local, None))
        .unwrap_or_else(|| local.to_owned())
}

fn source_kind(field: &str) -> Option<&'static str> {
    match field {
        "taskID" | "createdTaskID" | "decisionQueue" | "setAsideTaskIDs" | "restored"
        | "skipped" => Some("task"),
        "projectID" => Some("project"),
        "tagIDs" => Some("tag"),
        "sessionID" => Some("review_session"),
        "decisionID" => Some("review_decision"),
        "bulkID" => Some("review_bulk_release"),
        "formulationID" => Some("form"),
        "navigatorRequestID" => Some("navigator_request"),
        _ => None,
    }
}
fn target_kind(field: &str) -> Option<&'static str> {
    match field {
        "task_id" | "created_task_id" | "task_ids" | "decided_task_ids" | "set_aside_task_ids"
        | "restored" => Some("task"),
        "session_id" => Some("review_session"),
        "decision_id" => Some("review_decision"),
        "bulk_id" => Some("review_bulk_release"),
        "formulation_id" => Some("form"),
        "navigator_request_id" => Some("navigator_request"),
        _ => None,
    }
}

// Only named identity fields count as evidence. Text, time and position never
// admit an alias. Historical references remain valid without a live row.
pub(crate) fn source_references(
    value: &Value,
    field: Option<&str>,
    aliases: &[LegacyReviewAlias],
    evidence: &mut BTreeMap<String, BTreeSet<String>>,
) {
    match value {
        Value::String(id) => {
            if let Some(kind) = field.and_then(source_kind) {
                evidence
                    .entry(kind.to_owned())
                    .or_default()
                    .insert(canonical(kind, id, aliases));
            }
        }
        Value::Array(items) => {
            for item in items {
                source_references(item, field, aliases, evidence);
            }
        }
        Value::Object(fields) => {
            for (key, value) in fields {
                source_references(value, Some(key), aliases, evidence);
            }
        }
        _ => {}
    }
}
fn target_references(
    value: &Value,
    field: Option<&str>,
    evidence: &BTreeMap<String, BTreeSet<String>>,
) -> Result<(), LegacyReviewError> {
    match value {
        Value::String(id) => {
            if let Some(kind) = field.and_then(target_kind)
                && !evidence.get(kind).is_some_and(|known| known.contains(id))
            {
                return Err(LegacyReviewError::Invalid("references"));
            }
        }
        Value::Array(items) => {
            for item in items {
                target_references(item, field, evidence)?;
            }
        }
        Value::Object(fields) => {
            for (key, value) in fields {
                target_references(value, Some(key), evidence)?;
            }
        }
        _ => {}
    }
    Ok(())
}

fn source_alias(review: &Value, alias: &LegacyReviewAlias) -> bool {
    if alias.entity_type == EntityType::Task {
        return review
            .get("decisions")
            .and_then(Value::as_object)
            .into_iter()
            .flat_map(|items| items.values())
            .filter_map(|item| item.get("undo").and_then(|undo| undo.get("taskBefore")))
            .any(|task| {
                task.get("id").and_then(Value::as_str) == Some(&alias.local_id)
                    && task.get("serverID").and_then(Value::as_str) == Some(&alias.server_id)
            });
    }
    let section = match alias.entity_type {
        EntityType::ReviewSession => "sessions",
        EntityType::ReviewDecision => "decisions",
        EntityType::ReviewBulkRelease => "bulkReleases",
        _ => return false,
    };
    review
        .get(section)
        .and_then(Value::as_object)
        .into_iter()
        .flat_map(|items| items.values())
        .any(|item| {
            item.get("id").and_then(Value::as_str) == Some(&alias.local_id)
                && item.get("serverID").and_then(Value::as_str) == Some(&alias.server_id)
        })
}

fn validate_identities(
    capture: &LegacyReviewCapture,
    prepared: &PreparedLegacyReview,
    records: &[Record],
    live: &ReadSet,
) -> Result<(), LegacyReviewError> {
    let mut aliases = capture.aliases.clone();
    let mut admitted = BTreeSet::new();
    for alias in &prepared.aliases {
        if !admitted.insert((alias.entity_type.as_str(), &alias.local_id))
            || alias.local_id.is_empty()
            || alias.server_id.is_empty()
        {
            return Err(LegacyReviewError::Invalid("aliases"));
        }
        let existing = aliases
            .iter()
            .find(|held| held.entity_type == alias.entity_type && held.local_id == alias.local_id);
        if let Some(existing) = existing {
            if existing != alias {
                return Err(LegacyReviewError::Invalid("aliases"));
            }
        } else {
            if !source_alias(&capture.review, alias) {
                return Err(LegacyReviewError::Invalid("aliases"));
            }
            aliases.push(alias.clone());
        }
    }
    let mut evidence = BTreeMap::<String, BTreeSet<String>>::new();
    for (kind, section) in [
        ("review_session", "sessions"),
        ("review_decision", "decisions"),
        ("review_bulk_release", "bulkReleases"),
    ] {
        for (key, item) in capture
            .review
            .get(section)
            .and_then(Value::as_object)
            .into_iter()
            .flatten()
        {
            if item.get("id").and_then(Value::as_str) != Some(key.as_str()) {
                return Err(LegacyReviewError::Invalid("source_identity"));
            }
            evidence
                .entry(kind.to_owned())
                .or_default()
                .insert(canonical(kind, key, &aliases));
        }
    }
    for (kind, keys) in [
        (
            "review_session",
            prepared
                .read_set
                .sessions
                .keys()
                .map(|id| id.as_str())
                .collect::<BTreeSet<_>>(),
        ),
        (
            "review_decision",
            prepared
                .read_set
                .decisions
                .keys()
                .map(|id| id.as_str())
                .collect(),
        ),
        (
            "review_bulk_release",
            prepared
                .read_set
                .bulk_releases
                .keys()
                .map(|id| id.as_str())
                .collect(),
        ),
    ] {
        let expected: BTreeSet<&str> = evidence
            .get(kind)
            .into_iter()
            .flatten()
            .map(String::as_str)
            .collect();
        if keys != expected {
            return Err(LegacyReviewError::Invalid("source_identity"));
        }
    }
    let providers: BTreeSet<&str> = capture
        .review
        .get("navigatorConsents")
        .and_then(Value::as_object)
        .into_iter()
        .flat_map(|items| items.values())
        .filter_map(|item| item.get("provider").and_then(Value::as_str))
        .collect();
    if prepared
        .read_set
        .consents
        .iter()
        .map(|consent| consent.provider.as_str())
        .collect::<BTreeSet<_>>()
        != providers
    {
        return Err(LegacyReviewError::Invalid("provider"));
    }
    source_references(&capture.review, None, &aliases, &mut evidence);
    evidence
        .entry("task".to_owned())
        .or_default()
        .extend(live.tasks.keys().map(|id| id.as_str().to_owned()));
    for task in live.tasks.values() {
        if let Some(park) = &task.parked {
            evidence
                .entry("form".to_owned())
                .or_default()
                .insert(park.formulation_id.as_str().to_owned());
        }
        if let Some(clock) = &task.formulation {
            evidence
                .entry("form".to_owned())
                .or_default()
                .insert(clock.id.as_str().to_owned());
        }
    }
    for record in records {
        target_references(&json!(record)["value"], None, &evidence)?;
    }
    Ok(())
}
