//! Bounded private evidence prepared by the existing native business codec.
//! Capture reads only the importer's verified immutable backup; admission pins
//! the public rows and stores private fields separately from that public base.
use crate::{AccountlessImportProof, LegacyReviewAlias, LegacyReviewError, LegacyReviewToken};
use bb_domain::types::{ClockBefore, DecisionUndo, ReleasedPrivate};
use bb_protocol::{
    catalog::EntityType,
    wire::{Counter, RecordKey},
};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalReviewSourceKind {
    Decision,
    BulkRelease,
    TaskPark,
    Session,
    Settings,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalReviewSourceId {
    pub source_kind: LocalReviewSourceKind,
    pub source_id: String,
}

/// Capture-owned concurrency proof. A revision alone never proves import
/// correspondence; its exact record version and public digest are also pinned.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalReviewPublicPin {
    pub record_version: Counter,
    pub public_sha256: String,
    pub edit_revision: Option<Counter>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalReviewPrivateBinding {
    pub source_kind: LocalReviewSourceKind,
    pub source_id: String,
    pub source_fragment_sha256: String,
    pub entity_type: EntityType,
    pub record_key: RecordKey,
    pub public_sha256: String,
    pub public_record_version: Counter,
    pub task_public: BTreeMap<String, LocalReviewPublicPin>,
    pub session_public: Option<LocalReviewPublicPin>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalReviewPrivateSource {
    #[serde(flatten)]
    pub binding: LocalReviewPrivateBinding,
    pub source: Value,
    /// Original native task IDs, with fragments from the exact retained source.
    pub source_tasks: BTreeMap<String, Value>,
    pub source_session: Option<Value>,
    pub public: Value,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalReviewPrivateCapture {
    pub token: LegacyReviewToken,
    pub aliases: Vec<LegacyReviewAlias>,
    pub entries: Vec<LocalReviewPrivateSource>,
}

/// The codec emits private fields separately; this type can never be accepted
/// through generic draft CRUD or the ordinary public Review activation port.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    content = "fields",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum PreparedLocalReviewPrivateFields {
    Decision(DecisionUndo),
    Bulk(Vec<Option<ReleasedPrivate>>),
    TaskPark(PreparedLocalParkPrivate),
    Session(bb_domain::types::SessionPrivate),
    Settings(bb_domain::types::SettingsPrivate),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PreparedLocalParkPrivate {
    pub from_revision: Option<Counter>,
    pub clock_before: ClockBefore,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalReviewSourceEvidence {
    pub task_matches: Option<bool>,
    pub created_task_matches: Option<bool>,
    pub session_matches: Option<bool>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PreparedLocalReviewPrivateEntry {
    #[serde(flatten)]
    pub binding: LocalReviewPrivateBinding,
    pub private: Option<PreparedLocalReviewPrivateFields>,
    pub evidence: LocalReviewSourceEvidence,
    #[serde(default)]
    pub task_before_park: Option<PreparedLocalParkPrivate>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PreparedLocalReviewPrivate {
    pub token: LegacyReviewToken,
    pub entries: Vec<PreparedLocalReviewPrivateEntry>,
}

pub(crate) fn invalid() -> LegacyReviewError {
    LegacyReviewError::Invalid("local_review_private")
}

pub(crate) fn execute_error(error: crate::ExecuteError) -> LegacyReviewError {
    match error {
        crate::ExecuteError::Store(error) => error.into(),
        _ => invalid(),
    }
}

fn source_section(kind: LocalReviewSourceKind) -> (&'static str, EntityType) {
    match kind {
        LocalReviewSourceKind::Decision => ("decisions", EntityType::ReviewDecision),
        LocalReviewSourceKind::BulkRelease => ("bulkReleases", EntityType::ReviewBulkRelease),
        LocalReviewSourceKind::TaskPark => ("tasks", EntityType::Task),
        LocalReviewSourceKind::Session => ("sessions", EntityType::ReviewSession),
        LocalReviewSourceKind::Settings => ("settings", EntityType::ReviewSettings),
    }
}

pub(crate) fn same_time(left: Option<&Value>, right: Option<&Value>) -> bool {
    let parse = |v: Option<&Value>| {
        v.and_then(Value::as_str)
            .and_then(|s| bb_domain::calendar::UtcInstant::parse_rfc3339(s).ok())
    };
    match (parse(left), parse(right)) {
        (Some(a), Some(b)) => a == b,
        _ => false,
    }
}

pub(crate) fn stamp_matches(stamp: Option<&Value>, task: Option<&Value>) -> bool {
    let (Some(stamp), Some(task)) = (stamp, task) else {
        return false;
    };
    let revision = |v: &Value| v.get("serverRevision").filter(|v| !v.is_null()).cloned();
    revision(stamp) == revision(task)
        && (stamp.get("updatedAt").is_none_or(Value::is_null)
            || same_time(stamp.get("updatedAt"), task.get("updatedAt")))
}

fn bounded_row_cost(value: &Value) -> Result<usize, LegacyReviewError> {
    let mut count = 0usize;
    match value {
        Value::Array(items) => {
            count = items.len();
            if count == usize::MAX {
                return Err(invalid());
            }
            for value in items {
                count += bounded_row_cost(value)?;
                if count == usize::MAX {
                    return Err(invalid());
                }
            }
        }
        Value::Object(fields) => {
            for value in fields.values() {
                count += bounded_row_cost(value)?;
                if count == usize::MAX {
                    return Err(invalid());
                }
            }
        }
        _ => {}
    }
    Ok(count)
}

/// Import deliberately omits an alias when original serverID == localID. The
/// exact verified original record still proves that identity, including a bare
/// historical ID; never infer it by stripping a prefix or examining text.
pub(crate) fn original_identity(
    kind: EntityType,
    id: &str,
    base: &Value,
    aliases: &mut Vec<LegacyReviewAlias>,
) -> String {
    let section = match kind {
        EntityType::Task => "tasks",
        EntityType::Project => "projects",
        EntityType::Tag => "tags",
        _ => return crate::legacy_review::canonical(kind.as_str(), id, aliases),
    };
    if let Some(record) = base.get(section).and_then(|items| items.get(id))
        && record.get("id").and_then(Value::as_str) == Some(id)
        && let Some(server) = record.get("serverID").and_then(Value::as_str)
    {
        if !aliases
            .iter()
            .any(|alias| alias.entity_type == kind && alias.local_id == id)
        {
            aliases.push(LegacyReviewAlias {
                entity_type: kind,
                local_id: id.to_owned(),
                server_id: server.to_owned(),
            });
        }
    }
    crate::legacy_review::canonical(kind.as_str(), id, aliases)
}

pub(crate) fn original_nested_aliases(
    value: &Value,
    field: Option<&str>,
    base: &Value,
    aliases: &mut Vec<LegacyReviewAlias>,
) {
    match value {
        Value::String(id) => {
            let kind = match field {
                Some(
                    "taskID" | "createdTaskID" | "decisionQueue" | "setAsideTaskIDs" | "restored"
                    | "skipped",
                ) => Some(EntityType::Task),
                Some("projectID") => Some(EntityType::Project),
                Some("tagIDs") => Some(EntityType::Tag),
                _ => None,
            };
            if let Some(kind) = kind {
                original_identity(kind, id, base, aliases);
            }
        }
        Value::Array(items) => {
            for item in items {
                original_nested_aliases(item, field, base, aliases)
            }
        }
        Value::Object(fields) => {
            for (key, item) in fields {
                original_nested_aliases(item, Some(key), base, aliases)
            }
        }
        _ => {}
    }
}

pub(crate) fn admit_captured_in(
    tx: &rusqlite::Transaction<'_>,
    proof: &AccountlessImportProof,
    captured: &LocalReviewPrivateCapture,
    prepared: &PreparedLocalReviewPrivate,
    now: &bb_protocol::wire::Instant,
) -> Result<u32, LegacyReviewError> {
    let mut admitted = 0;
    for (source, entry) in captured.entries.iter().zip(&prepared.entries) {
        if source.binding != entry.binding {
            return Err(LegacyReviewError::SourceChanged);
        }
        let Some(private) = entry.private.clone() else {
            continue;
        };
        let (_, mut record) = pin(
            tx,
            &proof.workspace,
            entry.binding.entity_type,
            &entry.binding.record_key,
        )?
        .ok_or_else(invalid)?;
        match (&mut record, private) {
            (
                bb_domain::types::Record::ReviewDecision(decision),
                PreparedLocalReviewPrivateFields::Decision(mut undo),
            ) => {
                let source_task_id = source
                    .source
                    .get("taskID")
                    .and_then(Value::as_str)
                    .ok_or_else(invalid)?;
                let original = source.source_tasks.get(source_task_id);
                let original_match = stamp_matches(source.source.get("taskAfter"), original);
                let task_pin = entry.binding.task_public.get(decision.task_id.as_str());
                if entry.evidence.task_matches != Some(true)
                    || !original_match
                    || !task_pin.is_some_and(|pin| {
                        pin.record_version == Counter::from(crate::import::IMPORTED_VERSION)
                    })
                {
                    continue;
                }
                if undo.task_before.id != decision.task_id
                    || undo.task_before.revision != decision.task_revision_before
                {
                    return Err(invalid());
                }
                if let Some(created) = &decision.created_task_id {
                    let id = source
                        .source
                        .pointer("/undo/createdTaskID")
                        .and_then(Value::as_str)
                        .ok_or_else(invalid)?;
                    let original = source.source_tasks.get(id);
                    let original_match =
                        stamp_matches(source.source.pointer("/undo/createdTaskAfter"), original);
                    let pin = entry.binding.task_public.get(created.as_str());
                    if entry.evidence.created_task_matches != Some(true)
                        || !original_match
                        || !pin.is_some_and(|pin| {
                            pin.record_version == Counter::from(crate::import::IMPORTED_VERSION)
                        })
                    {
                        continue;
                    }
                    undo.created_task_revision = pin.and_then(|pin| pin.edit_revision.clone());
                } else if undo.created_task_revision.is_some() {
                    return Err(invalid());
                }
                if let Some(park) = &entry.task_before_park {
                    let original = source
                        .source
                        .pointer("/undo/taskBefore/parked")
                        .ok_or_else(invalid)?;
                    let marker = undo.task_before.parked.as_mut().ok_or_else(invalid)?;
                    if !same_time(original.get("at"), Some(&serde_json::json!(marker.at)))
                        || original.get("formulationID").and_then(Value::as_str)
                            != Some(marker.formulation_id.as_str())
                    {
                        return Err(invalid());
                    }
                    marker.private = Some(bb_domain::types::ParkPrivate {
                        from_revision: undo.task_before.revision.clone(),
                        clock_before: park.clock_before.clone(),
                    });
                }
                if let Some(before) = undo
                    .local_before
                    .as_mut()
                    .and_then(|local| local.session_before.as_mut())
                {
                    let source_match = same_time(
                        source
                            .source_session
                            .as_ref()
                            .and_then(|session| session.get("lastActivityAt")),
                        source
                            .source
                            .pointer("/undo/sessionBefore/lastActivityAfter"),
                    );
                    let pin = entry.binding.session_public.as_ref();
                    if entry.evidence.session_matches == Some(true)
                        && source_match
                        && pin.is_some_and(|pin| {
                            pin.record_version == Counter::from(crate::import::IMPORTED_VERSION)
                        })
                    {
                        before.revision_after = pin.and_then(|pin| pin.edit_revision.clone());
                        if before.revision_after.is_none() {
                            return Err(invalid());
                        }
                    } else if let Some(local) = &mut undo.local_before {
                        local.session_before = None;
                    }
                }
                // The admitted task revision itself is immutable source
                // representation, never inferred from a nil source counter.
                if task_pin.and_then(|pin| pin.edit_revision.as_ref())
                    != Some(&decision.task_revision_after)
                {
                    return Err(invalid());
                }
                decision.private = Some(undo);
            }
            (
                bb_domain::types::Record::ReviewBulkRelease(bulk),
                PreparedLocalReviewPrivateFields::Bulk(private),
            ) => {
                if private.len() != bulk.released.len() {
                    return Err(invalid());
                }
                let originals = source
                    .source
                    .get("released")
                    .and_then(Value::as_array)
                    .ok_or_else(invalid)?;
                for (item, private) in bulk.released.iter_mut().zip(private) {
                    let original = originals
                        .iter()
                        .find(|original| {
                            original
                                .get("taskID")
                                .and_then(Value::as_str)
                                .is_some_and(|id| {
                                    crate::legacy_review::canonical("task", id, &captured.aliases)
                                        == item.task_id.as_str()
                                })
                        })
                        .ok_or_else(invalid)?;
                    let mut private = private;
                    if let Some(private) = &mut private {
                        let local_id = original
                            .get("taskID")
                            .and_then(Value::as_str)
                            .ok_or_else(invalid)?;
                        let stamp_match = stamp_matches(
                            original.get("taskAfter"),
                            source.source_tasks.get(local_id),
                        );
                        let pin = entry.binding.task_public.get(item.task_id.as_str());
                        let current_match = pin.is_some_and(|pin| {
                            pin.record_version == Counter::from(crate::import::IMPORTED_VERSION)
                                && pin.edit_revision.as_ref() == Some(&item.revision_after)
                        });
                        if private.local_source_task_unchanged == Some(true) && !stamp_match {
                            return Err(invalid());
                        }
                        private.local_source_task_unchanged = Some(
                            private.local_source_task_unchanged == Some(true)
                                && stamp_match
                                && current_match,
                        );
                    }
                    item.private = private;
                }
            }
            (
                bb_domain::types::Record::Task(task),
                PreparedLocalReviewPrivateFields::TaskPark(private),
            ) => {
                if entry.binding.public_record_version
                    != Counter::from(crate::import::IMPORTED_VERSION)
                {
                    return Err(invalid());
                }
                let original = source.source.get("parked").ok_or_else(invalid)?;
                let marker = task.parked.as_mut().ok_or_else(invalid)?;
                if !same_time(original.get("at"), Some(&serde_json::json!(marker.at)))
                    || original.get("formulationID").and_then(Value::as_str)
                        != Some(marker.formulation_id.as_str())
                {
                    return Err(invalid());
                }
                marker.private = Some(bb_domain::types::ParkPrivate {
                    from_revision: task.revision.clone(),
                    clock_before: private.clock_before,
                });
            }
            (
                bb_domain::types::Record::ReviewSession(session),
                PreparedLocalReviewPrivateFields::Session(mut private),
            ) => {
                if session.status != bb_domain::types::SessionStatus::Open {
                    private.local_imported_progress.clear();
                }
                session.private = Some(private);
            }
            (
                bb_domain::types::Record::ReviewSettings(settings),
                PreparedLocalReviewPrivateFields::Settings(private),
            ) => {
                if private.last_effective_sweep_at.is_none()
                    && private.threshold_changed_at.is_none()
                {
                    continue;
                }
                if private.last_effective_sweep_at.is_some() {
                    return Err(invalid());
                }
                let original: Option<bb_protocol::wire::Instant> = serde_json::from_value(
                    source
                        .source
                        .get("thresholdChangedAt")
                        .cloned()
                        .unwrap_or(Value::Null),
                )
                .map_err(|_| invalid())?;
                if private.threshold_changed_at != original {
                    return Err(invalid());
                }
                settings.private = Some(private);
            }
            _ => return Err(invalid()),
        }
        admitted += u32::from(
            crate::local_review::admit_import_private(
                tx,
                proof,
                &prepared.token,
                &entry.binding,
                &record,
                now,
            )
            .map_err(execute_error)?,
        );
    }
    Ok(admitted)
}

pub(crate) fn pin(
    tx: &rusqlite::Transaction<'_>,
    workspace: &str,
    kind: EntityType,
    key: &RecordKey,
) -> Result<Option<(LocalReviewPublicPin, bb_domain::types::Record)>, LegacyReviewError> {
    use rusqlite::OptionalExtension;
    let row: Option<(String, Option<String>, Vec<u8>)> = tx.query_row(
        "SELECT record_version,edit_revision,body FROM confirmed_records WHERE workspace_id=?1 AND record_type=?2 AND record_key=?3 AND tombstone=0",
        rusqlite::params![workspace,kind.as_str(),serde_json::json!(key).to_string()],
        |r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional()?;
    row.map(|(version, revision, body)| {
        let record = crate::execute::record_from(kind.as_str(), &body)
            .map_err(execute_error)?
            .public();
        let public = serde_json::to_vec(&record).map_err(|_| crate::StoreError::Corrupt)?;
        Ok((
            LocalReviewPublicPin {
                record_version: Counter::parse(version).map_err(|_| crate::StoreError::Corrupt)?,
                public_sha256: crate::sha256_hex(&public),
                edit_revision: revision
                    .map(Counter::parse)
                    .transpose()
                    .map_err(|_| crate::StoreError::Corrupt)?,
            },
            record,
        ))
    })
    .transpose()
}

pub(crate) fn capture_raw_in(
    tx: &rusqlite::Transaction<'_>,
    proof: &AccountlessImportProof,
    selected: &[LocalReviewSourceId],
    max: usize,
) -> Result<LocalReviewPrivateCapture, LegacyReviewError> {
    if !crate::local_review::account_less(tx)? {
        return Err(invalid());
    }
    crate::local_review::recheck_import_proof(tx, proof).map_err(execute_error)?;
    let mut capture = crate::legacy_review::capture_in(tx)?;
    if !capture.already_active
        || capture.token.workspace_id != proof.workspace
        || capture.token.import_source_sha256 != proof.source_sha256
    {
        return Err(invalid());
    }
    let base = proof.source.get("base").ok_or_else(invalid)?;
    let review = base.get("review").ok_or_else(invalid)?;
    let mut entries = Vec::new();
    let mut references = 0usize;
    let mut bytes = 0usize;
    let mut source_references = BTreeMap::new();
    let mut seen = std::collections::BTreeSet::new();
    let mut original_ids = std::collections::BTreeSet::new();
    for selected in selected {
        if selected.source_kind == LocalReviewSourceKind::Settings
            && selected.source_id != "settings"
        {
            return Err(invalid());
        }
        if !seen.insert((selected.source_kind, selected.source_id.clone())) {
            return Err(invalid());
        }
        let (section, kind) = source_section(selected.source_kind);
        let source = if selected.source_kind == LocalReviewSourceKind::TaskPark {
            base.get(section)
        } else {
            review.get(section)
        }
        .and_then(|v| {
            if selected.source_kind == LocalReviewSourceKind::Settings {
                Some(v)
            } else {
                v.get(&selected.source_id)
            }
        })
        .ok_or_else(invalid)?;
        references += bounded_row_cost(source)?;
        original_nested_aliases(source, None, base, &mut capture.aliases);
        if selected.source_kind == LocalReviewSourceKind::TaskPark {
            original_identity(
                EntityType::Task,
                &selected.source_id,
                base,
                &mut capture.aliases,
            );
        }
        crate::legacy_review::source_references(
            source,
            None,
            &capture.aliases,
            &mut source_references,
        );
        let fragment = serde_json::to_vec(source).map_err(|_| crate::StoreError::Corrupt)?;
        bytes += fragment.len();
        if references > max
            || bytes
                > if max == 200 {
                    8 * 1024 * 1024
                } else {
                    usize::MAX
                }
        {
            return Err(invalid());
        }
        if selected.source_kind != LocalReviewSourceKind::Settings
            && source.get("id").and_then(Value::as_str) != Some(&selected.source_id)
        {
            return Err(invalid());
        }
        let key = if selected.source_kind == LocalReviewSourceKind::Settings {
            Vec::new()
        } else {
            vec![crate::legacy_review::canonical(
                kind.as_str(),
                &selected.source_id,
                &capture.aliases,
            )]
        };
        let (public_pin, public) = pin(tx, &proof.workspace, kind, &key)?.ok_or_else(invalid)?;
        // Admission only enriches immutable imported public rows. Native local
        // changes advance record versions and must not be reinterpreted.
        if public_pin.record_version != Counter::from(crate::import::IMPORTED_VERSION) {
            return Err(invalid());
        }
        let mut ids = std::collections::BTreeSet::new();
        match selected.source_kind {
            LocalReviewSourceKind::Decision => {
                ids.insert(
                    source
                        .get("taskID")
                        .and_then(Value::as_str)
                        .ok_or_else(invalid)?,
                );
                if let Some(id) = source
                    .pointer("/undo/createdTaskID")
                    .and_then(Value::as_str)
                {
                    ids.insert(id);
                }
            }
            LocalReviewSourceKind::BulkRelease => {
                let released = source
                    .get("released")
                    .and_then(Value::as_array)
                    .ok_or_else(invalid)?;
                if released.len() > max {
                    return Err(invalid());
                }
                for item in released {
                    ids.insert(
                        item.get("taskID")
                            .and_then(Value::as_str)
                            .ok_or_else(invalid)?,
                    );
                }
            }
            LocalReviewSourceKind::TaskPark => {
                ids.insert(selected.source_id.as_str());
            }
            LocalReviewSourceKind::Session | LocalReviewSourceKind::Settings => {}
        }
        references += 1 + ids.len();
        if references > max {
            return Err(invalid());
        }
        let mut source_tasks = BTreeMap::new();
        let mut task_public = BTreeMap::new();
        original_ids.insert(selected.source_id.clone());
        for id in ids {
            original_ids.insert(id.to_owned());
            if let Some(task) = base.get("tasks").and_then(|tasks| tasks.get(id)) {
                references += bounded_row_cost(task)?;
                original_nested_aliases(task, None, base, &mut capture.aliases);
                bytes += serde_json::to_vec(task)
                    .map_err(|_| crate::StoreError::Corrupt)?
                    .len();
                if references > max
                    || bytes
                        > if max == 200 {
                            8 * 1024 * 1024
                        } else {
                            usize::MAX
                        }
                {
                    return Err(invalid());
                }
                source_tasks.insert(id.to_owned(), task.clone());
            }
            let canonical = original_identity(EntityType::Task, id, base, &mut capture.aliases);
            let task_key = vec![canonical.clone()];
            if let Some((p, _)) = pin(tx, &proof.workspace, EntityType::Task, &task_key)? {
                task_public.insert(canonical, p);
            }
        }
        let session_id = source.get("sessionID").and_then(Value::as_str);
        let source_session = session_id
            .and_then(|id| review.get("sessions").and_then(|v| v.get(id)))
            .map(|session| {
                references += bounded_row_cost(session)?;
                bytes += serde_json::to_vec(session)
                    .map_err(|_| crate::StoreError::Corrupt)?
                    .len();
                if references > max
                    || bytes
                        > if max == 200 {
                            8 * 1024 * 1024
                        } else {
                            usize::MAX
                        }
                {
                    return Err(invalid());
                }
                Ok(session.clone())
            })
            .transpose()?;
        let session_public = if let Some(id) = session_id {
            references += 1;
            if references > max {
                return Err(invalid());
            }
            original_ids.insert(id.to_owned());
            let canonical = crate::legacy_review::canonical("review_session", id, &capture.aliases);
            let key = vec![canonical];
            pin(tx, &proof.workspace, EntityType::ReviewSession, &key)?.map(|(p, _)| p)
        } else {
            None
        };
        bytes += serde_json::to_vec(&public)
            .map_err(|_| crate::StoreError::Corrupt)?
            .len();
        if bytes
            > if max == 200 {
                8 * 1024 * 1024
            } else {
                usize::MAX
            }
        {
            return Err(invalid());
        }
        entries.push(LocalReviewPrivateSource {
            binding: LocalReviewPrivateBinding {
                source_kind: selected.source_kind,
                source_id: selected.source_id.clone(),
                source_fragment_sha256: crate::sha256_hex(&fragment),
                entity_type: kind,
                record_key: key,
                public_sha256: public_pin.public_sha256,
                public_record_version: public_pin.record_version,
                task_public,
                session_public,
            },
            source: source.clone(),
            source_tasks,
            source_session,
            public: serde_json::json!(public)["value"].take(),
        });
    }
    let aliases = capture
        .aliases
        .into_iter()
        .filter(|a| {
            original_ids.contains(&a.local_id)
                || source_references
                    .get(a.entity_type.as_str())
                    .is_some_and(|ids| ids.contains(&a.server_id))
        })
        .collect();
    Ok(LocalReviewPrivateCapture {
        token: capture.token,
        aliases,
        entries,
    })
}
