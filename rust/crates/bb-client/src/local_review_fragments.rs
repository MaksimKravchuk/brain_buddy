//! Migration-only typed fragments. Incomplete fragments live in a reserved
//! sibling draft and cannot enter the private ReadSet. Only complete native
//! coverage can build the shared domain's ordinary private types.
use crate::local_review_import::{
    LocalReviewPrivateBinding, LocalReviewPublicPin, LocalReviewSourceEvidence,
    PreparedLocalParkPrivate,
};
use crate::{LegacyReviewAlias, LegacyReviewToken};
use bb_domain::types::{
    DecisionUndo, ProgressId, ReleasedPrivate, SessionPrivate, SettingsPrivate, TagId,
};
use bb_protocol::wire::Instant;
use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use serde_json::Value;
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalReviewComponent {
    DecisionScalar,
    DecisionTags,
    BulkReleased,
    TaskPark,
    SessionScalar,
    SessionProgress,
    Settings,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalReviewFragmentHeader {
    pub codec_version: u32,
    pub token: LegacyReviewToken,
    pub binding: LocalReviewPrivateBinding,
    pub source_at: Option<Instant>,
    pub deadline: Option<Instant>,
    pub component_lengths: BTreeMap<LocalReviewComponent, u32>,
}

/// Exact original task-stamp evidence only. No children or displayed full-task
/// completeness is represented by this explicitly narrow witness.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LocalReviewTaskWitness {
    pub id: String,
    pub server_revision: Option<u64>,
    pub updated_at: Instant,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LocalReviewSessionWitness {
    pub id: String,
    pub last_activity_at: Instant,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LocalReviewFragmentPage {
    pub header: LocalReviewFragmentHeader,
    pub ordinal: u32,
    pub component: LocalReviewComponent,
    pub offset: u32,
    pub count: u32,
    pub fragment_sha256: String,
    pub aliases: Vec<LegacyReviewAlias>,
    pub task_public: BTreeMap<String, LocalReviewPublicPin>,
    pub session_public: Option<LocalReviewPublicPin>,
    pub source: Value,
    pub source_tasks: BTreeMap<String, LocalReviewTaskWitness>,
    pub source_session: Option<LocalReviewSessionWitness>,
    pub public: Value,
    pub next_cursor: Option<String>,
}

/// A scalar decision component intentionally omits task tags. Decode all other
/// business fields with the existing shared domain decoder; complete coverage
/// installs the separately admitted original tag component before injection.
#[derive(Clone, Debug, PartialEq)]
pub struct PreparedLocalDecisionScalar(pub(crate) DecisionUndo);

impl<'de> Deserialize<'de> for PreparedLocalDecisionScalar {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let mut value = Value::deserialize(deserializer)?;
        let task = value
            .get_mut("task_before")
            .and_then(Value::as_object_mut)
            .ok_or_else(|| D::Error::custom("task_before"))?;
        if task.contains_key("tag_ids") {
            return Err(D::Error::custom("scalar_task_tags"));
        }
        task.insert("tag_ids".into(), Value::Array(Vec::new()));
        serde_json::from_value(value)
            .map(Self)
            .map_err(|_| D::Error::custom("decision_scalar"))
    }
}
impl Serialize for PreparedLocalDecisionScalar {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        use serde::ser::Error as _;
        let mut value = serde_json::to_value(&self.0).map_err(S::Error::custom)?;
        value
            .get_mut("task_before")
            .and_then(Value::as_object_mut)
            .ok_or_else(|| S::Error::custom("task_before"))?
            .remove("tag_ids");
        value.serialize(serializer)
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    content = "fields",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum PreparedLocalFragmentFields {
    Decision(PreparedLocalDecisionScalar),
    DecisionTags(Vec<TagId>),
    Bulk(Vec<Option<ReleasedPrivate>>),
    TaskPark(PreparedLocalParkPrivate),
    Session(SessionPrivate),
    SessionProgress(Vec<ProgressId>),
    Settings(SettingsPrivate),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PreparedLocalReviewFragment {
    pub header: LocalReviewFragmentHeader,
    pub ordinal: u32,
    pub component: LocalReviewComponent,
    pub offset: u32,
    pub count: u32,
    pub fragment_sha256: String,
    pub task_public: BTreeMap<String, LocalReviewPublicPin>,
    pub session_public: Option<LocalReviewPublicPin>,
    pub private: Option<PreparedLocalFragmentFields>,
    pub evidence: LocalReviewSourceEvidence,
    pub task_before_park: Option<PreparedLocalParkPrivate>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum LocalReviewFragmentAdmitted {
    Pending { next_ordinal: u32 },
    Admitted,
    AlreadyAdmitted,
}

use crate::local_review_import::{
    self as migration, LocalReviewSourceId, LocalReviewSourceKind, PreparedLocalReviewPrivate,
    PreparedLocalReviewPrivateEntry, PreparedLocalReviewPrivateFields,
};
use crate::{AccountlessImportProof, LegacyReviewError, Store, StoreError};
use rusqlite::{OptionalExtension, Transaction, params};

const PENDING_KIND: &str = "runtime_local_review_private_pending";
const MANIFEST_KIND: &str = "runtime_local_review_private_manifest";
const BYTE_LIMIT: usize = 8 * 1024 * 1024;
const ROW_LIMIT: usize = 200;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Cursor {
    header_sha256: String,
    ordinal: u32,
    component: LocalReviewComponent,
    offset: u32,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Pending {
    header: LocalReviewFragmentHeader,
    pages: Vec<PreparedLocalReviewFragment>,
    digests: Vec<String>,
    next_cursor: Option<String>,
}
#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    header_sha256: String,
    digests: Vec<String>,
}

fn bytes<T: Serialize>(v: &T) -> Result<Vec<u8>, LegacyReviewError> {
    serde_json::to_vec(v).map_err(|_| StoreError::Corrupt.into())
}
fn hash<T: Serialize>(v: &T) -> Result<String, LegacyReviewError> {
    Ok(crate::sha256_hex(&bytes(v)?))
}
fn decode<T: serde::de::DeserializeOwned>(v: &[u8]) -> Result<T, LegacyReviewError> {
    serde_json::from_slice(v).map_err(|_| StoreError::Corrupt.into())
}
fn invalid() -> LegacyReviewError {
    migration::invalid()
}
fn instant(at: &Instant) -> Result<bb_domain::calendar::UtcInstant, LegacyReviewError> {
    bb_domain::calendar::UtcInstant::parse_rfc3339(at.as_str()).map_err(|_| invalid())
}
fn expired(header: &LocalReviewFragmentHeader, now: &Instant) -> Result<bool, LegacyReviewError> {
    let now = instant(now)?;
    Ok(header
        .deadline
        .as_ref()
        .map(instant)
        .transpose()?
        .is_some_and(|at| now >= at))
}

fn key(header: &LocalReviewFragmentHeader, suffix: &str) -> Result<String, LegacyReviewError> {
    Ok(format!(
        "runtime:local-review-private:{suffix}:{}",
        hash(&(header.binding.entity_type, &header.binding.record_key))?
    ))
}
fn read_draft<T: serde::de::DeserializeOwned>(
    tx: &Transaction<'_>,
    header: &LocalReviewFragmentHeader,
    kind: &str,
    suffix: &str,
) -> Result<Option<T>, LegacyReviewError> {
    tx.query_row(
        "SELECT fields FROM drafts WHERE workspace_id=?1 AND draft_id=?2 AND editor_kind=?3",
        params![header.token.workspace_id, key(header, suffix)?, kind],
        |r| r.get::<_, Vec<u8>>(0),
    )
    .optional()?
    .map(|b| decode(&b))
    .transpose()
}
fn save_draft<T: Serialize>(
    tx: &Transaction<'_>,
    header: &LocalReviewFragmentHeader,
    kind: &str,
    suffix: &str,
    value: &T,
    now: &Instant,
) -> Result<(), LegacyReviewError> {
    let deadline = header
        .deadline
        .as_ref()
        .map(instant)
        .transpose()?
        .map(|at| at.unix_micros().to_string());
    tx.execute("INSERT INTO drafts(workspace_id,draft_id,editor_kind,record_type,record_key,fields,updated_at,base_revision) VALUES(?1,?2,?3,?4,?5,?6,?7,?8) ON CONFLICT(workspace_id,draft_id) DO UPDATE SET fields=excluded.fields,updated_at=excluded.updated_at,base_revision=excluded.base_revision",params![header.token.workspace_id,key(header,suffix)?,kind,header.binding.entity_type.as_str(),serde_json::json!(header.binding.record_key).to_string(),bytes(value)?,now.as_str(),if kind==PENDING_KIND{deadline}else{None}])?;
    Ok(())
}
fn delete_pending(
    tx: &Transaction<'_>,
    header: &LocalReviewFragmentHeader,
) -> Result<(), LegacyReviewError> {
    tx.execute(
        "DELETE FROM drafts WHERE workspace_id=?1 AND draft_id=?2 AND editor_kind=?3",
        params![
            header.token.workspace_id,
            key(header, "pending")?,
            PENDING_KIND
        ],
    )?;
    Ok(())
}

fn scalar(mut value: Value, fields: &[&str]) -> Value {
    if let Some(v) = value.as_object_mut() {
        for field in fields {
            v.remove(*field);
        }
    }
    value
}
fn source_scalar(kind: LocalReviewSourceKind, mut value: Value) -> Value {
    match kind {
        LocalReviewSourceKind::Decision => {
            if let Some(task) = value.pointer_mut("/undo/taskBefore") {
                *task = scalar(
                    task.take(),
                    &["subtasks", "comments", "tagIDs", "childrenSyncedAt"],
                );
            }
        }
        LocalReviewSourceKind::TaskPark => {
            value = scalar(
                value,
                &["subtasks", "comments", "tagIDs", "childrenSyncedAt"],
            );
        }
        LocalReviewSourceKind::Session => {
            value = scalar(
                value,
                &["appliedProgress", "decisionQueue", "setAsideTaskIDs"],
            );
        }
        _ => {}
    }
    value
}
fn array_cost(value: &Value) -> usize {
    match value {
        Value::Array(items) => items.len() + items.iter().map(array_cost).sum::<usize>(),
        Value::Object(items) => items.values().map(array_cost).sum(),
        _ => 0,
    }
}
fn page_cost(page: &LocalReviewFragmentPage) -> Result<usize, LegacyReviewError> {
    Ok(
        array_cost(&serde_json::to_value(page).map_err(|_| StoreError::Corrupt)?)
            + page.source_tasks.len()
            + page.task_public.len()
            + usize::from(page.source_session.is_some())
            + usize::from(page.session_public.is_some()),
    )
}
fn header_in(
    capture: &migration::LocalReviewPrivateCapture,
) -> Result<LocalReviewFragmentHeader, LegacyReviewError> {
    let source = capture.entries.first().ok_or_else(invalid)?;
    let kind = source.binding.source_kind;
    let get_time = |field: &str| {
        source
            .source
            .get(field)
            .and_then(Value::as_str)
            .ok_or_else(invalid)
            .and_then(|at| Instant::parse(at.to_owned()).map_err(|_| invalid()))
    };
    let at = match kind {
        LocalReviewSourceKind::Decision => Some(get_time("decidedAt")?),
        LocalReviewSourceKind::BulkRelease => Some(get_time("createdAt")?),
        LocalReviewSourceKind::TaskPark => Some(
            Instant::parse(
                source
                    .source
                    .pointer("/parked/at")
                    .and_then(Value::as_str)
                    .ok_or_else(invalid)?
                    .to_owned(),
            )
            .map_err(|_| invalid())?,
        ),
        LocalReviewSourceKind::Session => Some(get_time("startedAt")?),
        LocalReviewSourceKind::Settings => source
            .source
            .get("thresholdChangedAt")
            .filter(|v| !v.is_null())
            .map(|_| get_time("thresholdChangedAt"))
            .transpose()?,
    };
    let deadline = if matches!(
        kind,
        LocalReviewSourceKind::Decision | LocalReviewSourceKind::BulkRelease
    ) {
        Some(
            Instant::parse(
                instant(at.as_ref().ok_or_else(invalid)?)?
                    .plus_seconds(7 * 86400)
                    .to_rfc3339(),
            )
            .map_err(|_| invalid())?,
        )
    } else {
        None
    };
    let mut lengths = BTreeMap::new();
    let len = |value: Option<&Value>| -> Result<u32, LegacyReviewError> {
        u32::try_from(value.and_then(Value::as_array).map_or(0, Vec::len)).map_err(|_| invalid())
    };
    match kind {
        LocalReviewSourceKind::Decision => {
            lengths.insert(LocalReviewComponent::DecisionScalar, 1);
            lengths.insert(
                LocalReviewComponent::DecisionTags,
                len(source.source.pointer("/undo/taskBefore/tagIDs"))?,
            );
        }
        LocalReviewSourceKind::BulkRelease => {
            lengths.insert(
                LocalReviewComponent::BulkReleased,
                len(source.source.get("released"))?,
            );
        }
        LocalReviewSourceKind::TaskPark => {
            lengths.insert(LocalReviewComponent::TaskPark, 1);
        }
        LocalReviewSourceKind::Session => {
            lengths.insert(LocalReviewComponent::SessionScalar, 1);
            let progress = if source.source.get("status").and_then(Value::as_str) == Some("open") {
                len(source.source.get("appliedProgress"))?
            } else {
                0
            };
            lengths.insert(LocalReviewComponent::SessionProgress, progress);
        }
        LocalReviewSourceKind::Settings => {
            lengths.insert(LocalReviewComponent::Settings, 1);
        }
    }
    let mut binding = source.binding.clone();
    binding.task_public.clear();
    binding.session_public = None;
    Ok(LocalReviewFragmentHeader {
        codec_version: 1,
        token: capture.token.clone(),
        binding,
        source_at: at,
        deadline,
        component_lengths: lengths,
    })
}
fn first_position(header: &LocalReviewFragmentHeader) -> Option<(LocalReviewComponent, u32)> {
    header
        .component_lengths
        .iter()
        .find(|(_, count)| **count > 0)
        .map(|(component, _)| (*component, 0))
}
fn next_position(
    header: &LocalReviewFragmentHeader,
    component: LocalReviewComponent,
    offset: u32,
    count: u32,
) -> Option<(LocalReviewComponent, u32)> {
    let end = offset.checked_add(count)?;
    if end < header.component_lengths[&component] {
        Some((component, end))
    } else {
        header
            .component_lengths
            .range((
                std::ops::Bound::Excluded(component),
                std::ops::Bound::Unbounded,
            ))
            .find(|(_, count)| **count > 0)
            .map(|(next, _)| (*next, 0))
    }
}

fn make_page(
    captured: &migration::LocalReviewPrivateCapture,
    header: &LocalReviewFragmentHeader,
    ordinal: u32,
    component: LocalReviewComponent,
    offset: u32,
    count: u32,
) -> Result<LocalReviewFragmentPage, LegacyReviewError> {
    let original = &captured.entries[0];
    let kind = header.binding.source_kind;
    let slice = |value: Option<&Value>| -> Result<Value, LegacyReviewError> {
        let items = value.and_then(Value::as_array).ok_or_else(invalid)?;
        let end = offset.checked_add(count).ok_or_else(invalid)? as usize;
        Ok(Value::Array(
            items
                .get(offset as usize..end)
                .ok_or_else(invalid)?
                .to_vec(),
        ))
    };
    let source = match component {
        LocalReviewComponent::DecisionScalar
        | LocalReviewComponent::TaskPark
        | LocalReviewComponent::SessionScalar
        | LocalReviewComponent::Settings => source_scalar(kind, original.source.clone()),
        LocalReviewComponent::DecisionTags => {
            slice(original.source.pointer("/undo/taskBefore/tagIDs"))?
        }
        LocalReviewComponent::SessionProgress => slice(original.source.get("appliedProgress"))?,
        LocalReviewComponent::BulkReleased => {
            let mut value = scalar(
                original.source.clone(),
                &["released", "skipped", "undoResult"],
            );
            value
                .as_object_mut()
                .ok_or_else(invalid)?
                .insert("released".into(), slice(original.source.get("released"))?);
            value
        }
    };
    let public = match component {
        LocalReviewComponent::BulkReleased => {
            let mut value = scalar(original.public.clone(), &["released", "skipped", "undo"]);
            value
                .as_object_mut()
                .ok_or_else(invalid)?
                .insert("released".into(), slice(original.public.get("released"))?);
            value
        }
        LocalReviewComponent::TaskPark => {
            let mut value = serde_json::Map::new();
            for field in ["id", "revision", "parked"] {
                if let Some(v) = original.public.get(field) {
                    value.insert(field.to_owned(), v.clone());
                }
            }
            Value::Object(value)
        }
        LocalReviewComponent::DecisionTags | LocalReviewComponent::SessionProgress => Value::Null,
        _ => original.public.clone(),
    };
    let mut source_tasks = BTreeMap::new();
    let mut task_public = BTreeMap::new();
    let mut aliases = Vec::new();
    // Only the page's typed references and aliases cross the port. No arbitrary
    // child rows from a full original task are copied into these narrow witnesses.
    let mut refs = BTreeMap::new();
    crate::legacy_review::source_references(&source, None, &captured.aliases, &mut refs);
    let ids: Vec<&str> = match component {
        LocalReviewComponent::DecisionScalar => [
            source.get("taskID").and_then(Value::as_str),
            source
                .pointer("/undo/createdTaskID")
                .and_then(Value::as_str),
        ]
        .into_iter()
        .flatten()
        .collect(),
        LocalReviewComponent::BulkReleased => source
            .get("released")
            .and_then(Value::as_array)
            .ok_or_else(invalid)?
            .iter()
            .filter_map(|item| item.get("taskID").and_then(Value::as_str))
            .collect(),
        LocalReviewComponent::TaskPark => vec![header.binding.source_id.as_str()],
        _ => Vec::new(),
    };
    for id in ids {
        if let Some(task) = original.source_tasks.get(id) {
            source_tasks.insert(
                id.to_owned(),
                LocalReviewTaskWitness {
                    id: id.to_owned(),
                    server_revision: task.get("serverRevision").and_then(Value::as_u64),
                    updated_at: serde_json::from_value(
                        task.get("updatedAt").cloned().ok_or_else(invalid)?,
                    )
                    .map_err(|_| invalid())?,
                },
            );
        }
        let canonical = crate::legacy_review::canonical("task", id, &captured.aliases);
        if let Some(pin) = original.binding.task_public.get(&canonical) {
            task_public.insert(canonical, pin.clone());
        }
    }
    for alias in &captured.aliases {
        if source_tasks.contains_key(&alias.local_id)
            || refs
                .get(alias.entity_type.as_str())
                .is_some_and(|ids| ids.contains(&alias.server_id))
        {
            aliases.push(alias.clone());
        }
    }
    // Tag components contain scalar IDs, so their field name is supplied explicitly.
    if component == LocalReviewComponent::DecisionTags {
        for id in source
            .as_array()
            .ok_or_else(invalid)?
            .iter()
            .filter_map(Value::as_str)
        {
            if let Some(alias) = captured.aliases.iter().find(|a| {
                a.entity_type == bb_protocol::catalog::EntityType::Tag && a.local_id == id
            }) && !aliases.contains(alias)
            {
                aliases.push(alias.clone());
            }
        }
    }
    let needs_session = component == LocalReviewComponent::DecisionScalar
        && source
            .pointer("/undo/sessionBefore")
            .is_some_and(|v| !v.is_null());
    let source_session = if needs_session {
        original
            .source_session
            .as_ref()
            .map(|s| {
                Ok(LocalReviewSessionWitness {
                    id: s
                        .get("id")
                        .and_then(Value::as_str)
                        .ok_or_else(invalid)?
                        .to_owned(),
                    last_activity_at: serde_json::from_value(
                        s.get("lastActivityAt").cloned().ok_or_else(invalid)?,
                    )
                    .map_err(|_| invalid())?,
                })
            })
            .transpose()?
    } else {
        None
    };
    let session_public = if needs_session {
        original.binding.session_public.clone()
    } else {
        None
    };
    let mut page = LocalReviewFragmentPage {
        header: header.clone(),
        ordinal,
        component,
        offset,
        count,
        fragment_sha256: String::new(),
        aliases,
        task_public,
        session_public,
        source,
        source_tasks,
        source_session,
        public,
        next_cursor: None,
    };
    page.fragment_sha256 = hash(&page)?;
    Ok(page)
}
fn page_in(
    tx: &Transaction<'_>,
    proof: &AccountlessImportProof,
    selected: &LocalReviewSourceId,
    after: Option<&str>,
    now: &Instant,
) -> Result<Option<LocalReviewFragmentPage>, LegacyReviewError> {
    let captured =
        migration::capture_raw_in(tx, proof, std::slice::from_ref(selected), usize::MAX)?;
    let header = header_in(&captured)?;
    if expired(&header, now)? {
        return Ok(None);
    }
    let header_sha256 = hash(&header)?;
    let (ordinal, component, offset) = if let Some(cursor) = after {
        if cursor.len() > 4096 {
            return Err(invalid());
        }
        let cursor: Cursor = serde_json::from_str(cursor).map_err(|_| invalid())?;
        if cursor.header_sha256 != header_sha256 {
            return Err(LegacyReviewError::SourceChanged);
        }
        (cursor.ordinal, cursor.component, cursor.offset)
    } else {
        let Some((component, offset)) = first_position(&header) else {
            return Ok(None);
        };
        (0, component, offset)
    };
    let remaining = header
        .component_lengths
        .get(&component)
        .and_then(|len| len.checked_sub(offset))
        .filter(|len| *len > 0)
        .ok_or_else(invalid)?;
    let mut chosen = None;
    for count in 1..=remaining.min(ROW_LIMIT as u32) {
        let page = make_page(&captured, &header, ordinal, component, offset, count)?;
        if page_cost(&page)? > ROW_LIMIT || bytes(&page)?.len() > BYTE_LIMIT {
            break;
        }
        chosen = Some(page);
    }
    let mut page = chosen.ok_or_else(invalid)?;
    if let Some((component, offset)) =
        next_position(&header, page.component, page.offset, page.count)
    {
        page.next_cursor = Some(
            serde_json::to_string(&Cursor {
                header_sha256,
                ordinal: ordinal.checked_add(1).ok_or_else(invalid)?,
                component,
                offset,
            })
            .map_err(|_| StoreError::Corrupt)?,
        );
    }
    if bytes(&page)?.len() > BYTE_LIMIT {
        return Err(invalid());
    }
    Ok(Some(page))
}

/// One exact original component page, with bounded references and bytes. Expired
/// Undo sources are omitted before crossing FFI.
pub fn capture_local_review_private_fragment(
    store: &mut Store,
    proof: &AccountlessImportProof,
    selected: &LocalReviewSourceId,
    after: Option<&str>,
    now: &Instant,
) -> Result<Option<LocalReviewFragmentPage>, LegacyReviewError> {
    store.read(|tx| Ok(page_in(tx, proof, selected, after, now)))?
}

fn known_in(
    tx: &Transaction<'_>,
    prepared: &PreparedLocalReviewFragment,
) -> Result<Option<LocalReviewFragmentAdmitted>, LegacyReviewError> {
    if !crate::local_review::account_less(tx)? {
        return Err(invalid());
    }
    let fingerprint = hash(prepared)?;
    let index = prepared.ordinal as usize;
    if let Some(done) = read_draft::<Manifest>(tx, &prepared.header, MANIFEST_KIND, "manifest")? {
        if done.header_sha256 != hash(&prepared.header)?
            || done.digests.get(index) != Some(&fingerprint)
        {
            return Err(LegacyReviewError::SourceChanged);
        }
        return Ok(Some(LocalReviewFragmentAdmitted::AlreadyAdmitted));
    }
    if let Some(pending) = read_draft::<Pending>(tx, &prepared.header, PENDING_KIND, "pending")? {
        if pending.header != prepared.header {
            return Err(LegacyReviewError::SourceChanged);
        }
        if let Some(known) = pending.digests.get(index) {
            if known != &fingerprint {
                return Err(LegacyReviewError::SourceChanged);
            }
            return Ok(Some(LocalReviewFragmentAdmitted::Pending {
                next_ordinal: u32::try_from(pending.pages.len()).map_err(|_| invalid())?,
            }));
        }
    }
    Ok(None)
}
/// Known completion lookup precedes backup reopening and current expiry checks.
/// It never activates an unknown fragment or invents missing source proof.
pub fn lookup_local_review_private_fragment(
    store: &mut Store,
    prepared: &PreparedLocalReviewFragment,
) -> Result<Option<LocalReviewFragmentAdmitted>, LegacyReviewError> {
    store.read(|tx| Ok(known_in(tx, prepared)))?
}

pub fn admit_local_review_private_fragment_with(
    store: &mut Store,
    proof: &AccountlessImportProof,
    prepared: &PreparedLocalReviewFragment,
    now: &Instant,
    before_commit: impl FnOnce() -> Result<(), LegacyReviewError>,
) -> Result<LocalReviewFragmentAdmitted, LegacyReviewError> {
    if bytes(prepared)?.len() > BYTE_LIMIT {
        return Err(invalid());
    }
    store.try_write(|tx| {
        if let Some(known) = known_in(tx, prepared)? {
            before_commit()?;
            return Ok(known);
        }
        let mut pending = read_draft::<Pending>(tx, &prepared.header, PENDING_KIND, "pending")?
            .unwrap_or(Pending {
                header: prepared.header.clone(),
                pages: Vec::new(),
                digests: Vec::new(),
                next_cursor: None,
            });
        if prepared.ordinal as usize != pending.pages.len() {
            return Err(invalid());
        }
        let selected = LocalReviewSourceId {
            source_kind: prepared.header.binding.source_kind,
            source_id: prepared.header.binding.source_id.clone(),
        };
        let page = page_in(tx, proof, &selected, pending.next_cursor.as_deref(), now)?
            .ok_or_else(invalid)?;
        if page.header != prepared.header
            || page.ordinal != prepared.ordinal
            || page.component != prepared.component
            || page.offset != prepared.offset
            || page.count != prepared.count
            || page.fragment_sha256 != prepared.fragment_sha256
            || page.task_public != prepared.task_public
            || page.session_public != prepared.session_public
        {
            return Err(LegacyReviewError::SourceChanged);
        }
        validate_component(prepared)?;
        if let Some(PreparedLocalFragmentFields::SessionProgress(ids)) = &prepared.private {
            let expected: Result<Vec<_>, _> = page
                .source
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .map(|value| {
                    let id = value.as_str().ok_or_else(invalid)?;
                    ProgressId::parse(id)
                        .or_else(|_| ProgressId::parse(format!("progress_{id}")))
                        .map_err(|_| invalid())
                })
                .collect();
            if ids != &expected? {
                return Err(invalid());
            }
        }
        if let Some(PreparedLocalFragmentFields::DecisionTags(ids)) = &prepared.private {
            let expected: Result<Vec<_>, _> = page
                .source
                .as_array()
                .ok_or_else(invalid)?
                .iter()
                .map(|value| {
                    let id = value.as_str().ok_or_else(invalid)?;
                    TagId::parse(crate::legacy_review::canonical("tag", id, &page.aliases))
                        .map_err(|_| invalid())
                })
                .collect();
            if ids != &expected? {
                return Err(invalid());
            }
        }

        pending.pages.push(prepared.clone());
        pending.digests.push(hash(prepared)?);
        pending.next_cursor = page.next_cursor;
        if pending.next_cursor.is_some() {
            save_draft(tx, &pending.header, PENDING_KIND, "pending", &pending, now)?;
            before_commit()?;
            return Ok(LocalReviewFragmentAdmitted::Pending {
                next_ordinal: prepared.ordinal.checked_add(1).ok_or_else(invalid)?,
            });
        }
        finalize_in(tx, proof, &pending, now)?;
        save_draft(
            tx,
            &pending.header,
            MANIFEST_KIND,
            "manifest",
            &Manifest {
                header_sha256: hash(&pending.header)?,
                digests: pending.digests,
            },
            now,
        )?;
        delete_pending(tx, &pending.header)?;
        before_commit()?;
        Ok(LocalReviewFragmentAdmitted::Admitted)
    })
}
fn validate_component(prepared: &PreparedLocalReviewFragment) -> Result<(), LegacyReviewError> {
    if let Some(private) = &prepared.private {
        let valid = match (private, prepared.component) {
            (PreparedLocalFragmentFields::Decision(_), LocalReviewComponent::DecisionScalar)
            | (PreparedLocalFragmentFields::TaskPark(_), LocalReviewComponent::TaskPark)
            | (PreparedLocalFragmentFields::Session(_), LocalReviewComponent::SessionScalar)
            | (PreparedLocalFragmentFields::Settings(_), LocalReviewComponent::Settings) => {
                prepared.count == 1
            }
            (
                PreparedLocalFragmentFields::DecisionTags(items),
                LocalReviewComponent::DecisionTags,
            ) => items.len() == prepared.count as usize,
            (PreparedLocalFragmentFields::Bulk(items), LocalReviewComponent::BulkReleased) => {
                items.len() == prepared.count as usize
            }
            (
                PreparedLocalFragmentFields::SessionProgress(items),
                LocalReviewComponent::SessionProgress,
            ) => items.len() == prepared.count as usize,
            _ => false,
        };
        if !valid {
            return Err(invalid());
        }
    }
    Ok(())
}
fn finalize_in(
    tx: &Transaction<'_>,
    proof: &AccountlessImportProof,
    pending: &Pending,
    now: &Instant,
) -> Result<(), LegacyReviewError> {
    let selected = LocalReviewSourceId {
        source_kind: pending.header.binding.source_kind,
        source_id: pending.header.binding.source_id.clone(),
    };
    let captured =
        migration::capture_raw_in(tx, proof, std::slice::from_ref(&selected), usize::MAX)?;
    if header_in(&captured)? != pending.header || expired(&pending.header, now)? {
        return Err(LegacyReviewError::SourceChanged);
    }
    let mut cursor = None;
    let mut task_public = BTreeMap::new();
    let mut session_public = None;
    let mut decision = None;
    let mut tags = Vec::new();
    let mut bulk = Vec::new();
    let mut park = None;
    let mut session = None;
    let mut progress = Vec::new();
    let mut settings = None;
    let mut evidence = LocalReviewSourceEvidence {
        task_matches: None,
        created_task_matches: None,
        session_matches: None,
    };
    let mut task_before_park = None;
    let mut tags_complete = true;
    let mut progress_complete = true;
    for (ordinal, prepared) in pending.pages.iter().enumerate() {
        let page = page_in(tx, proof, &selected, cursor.as_deref(), now)?.ok_or_else(invalid)?;
        if page.ordinal as usize != ordinal
            || page.component != prepared.component
            || page.offset != prepared.offset
            || page.count != prepared.count
            || page.fragment_sha256 != prepared.fragment_sha256
            || page.task_public != prepared.task_public
            || page.session_public != prepared.session_public
        {
            return Err(LegacyReviewError::SourceChanged);
        }
        cursor = page.next_cursor;
        task_public.extend(prepared.task_public.clone());
        if prepared.session_public.is_some() {
            session_public = prepared.session_public.clone();
        }
        match &prepared.private {
            Some(PreparedLocalFragmentFields::Decision(value)) => {
                decision = Some(value.0.clone());
                evidence = prepared.evidence.clone();
                task_before_park = prepared.task_before_park.clone();
            }
            Some(PreparedLocalFragmentFields::DecisionTags(value)) => tags.extend(value.clone()),
            Some(PreparedLocalFragmentFields::Bulk(value)) => bulk.extend(value.clone()),
            Some(PreparedLocalFragmentFields::TaskPark(value)) => park = Some(value.clone()),
            Some(PreparedLocalFragmentFields::Session(value)) => session = Some(value.clone()),
            Some(PreparedLocalFragmentFields::SessionProgress(value)) => {
                progress.extend(value.clone())
            }
            Some(PreparedLocalFragmentFields::Settings(value)) => settings = Some(value.clone()),
            None => {
                if prepared.component == LocalReviewComponent::DecisionTags {
                    tags_complete = false;
                }
                if prepared.component == LocalReviewComponent::SessionProgress {
                    progress_complete = false;
                }
            }
        }
    }
    if cursor.is_some() {
        return Err(invalid());
    }
    let private = match selected.source_kind {
        LocalReviewSourceKind::Decision => {
            decision.filter(|_| tags_complete).map(|mut decision| {
                decision.task_before.tag_ids = tags;
                PreparedLocalReviewPrivateFields::Decision(decision)
            })
        }
        LocalReviewSourceKind::BulkRelease => {
            if bulk.len()
                != captured.entries[0]
                    .source
                    .get("released")
                    .and_then(Value::as_array)
                    .ok_or_else(invalid)?
                    .len()
            {
                None
            } else {
                Some(PreparedLocalReviewPrivateFields::Bulk(bulk))
            }
        }
        LocalReviewSourceKind::TaskPark => park.map(PreparedLocalReviewPrivateFields::TaskPark),
        LocalReviewSourceKind::Session => {
            session.filter(|_| progress_complete).map(|mut session| {
                session.local_imported_progress = progress;
                PreparedLocalReviewPrivateFields::Session(session)
            })
        }
        LocalReviewSourceKind::Settings => settings.map(PreparedLocalReviewPrivateFields::Settings),
    };
    let mut binding = pending.header.binding.clone();
    binding.task_public = task_public;
    binding.session_public = session_public;
    // Recomputed original slices and pins are complete now. Only this native final
    // transaction may construct the full private record and expose it to LOCAL.
    let mut current = captured;
    current.entries[0].binding = binding.clone();
    migration::admit_captured_in(
        tx,
        proof,
        &current,
        &PreparedLocalReviewPrivate {
            token: pending.header.token.clone(),
            entries: vec![PreparedLocalReviewPrivateEntry {
                binding,
                private,
                evidence,
                task_before_park,
            }],
        },
        now,
    )?;
    Ok(())
}
