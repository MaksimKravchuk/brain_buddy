//! Consistent, bounded list reads and content-free invalidations for the Apple runtime.
//! The shared domain remains the rule authority; this adapter binds its cursors
//! to the durable projection generation and keeps SQLite behind the bridge.

use crate::execute::{ExecuteError, read_projection, unsigned};
use crate::{Store, StoreError, sha256_hex};
use bb_domain::{
    dispatch,
    types::{DomainError, Query, QueryInputs, QueryResult},
};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum QueryError {
    Store(StoreError),
    Refused(DomainError),
    RefusedAt {
        error: DomainError,
        projection_generation: u64,
    },
    RestartRequired,
}

impl From<StoreError> for QueryError {
    fn from(error: StoreError) -> Self {
        Self::Store(error)
    }
}

impl From<ExecuteError> for QueryError {
    fn from(error: ExecuteError) -> Self {
        match error {
            ExecuteError::Store(error) => Self::Store(error),
            ExecuteError::Refused(error) => Self::Refused(error),
            _ => Self::Store(StoreError::Corrupt),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct QueryPage {
    pub projection_generation: u64,
    pub result: QueryResult,
    pub collection_next_cursor: Option<String>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CollectionCursor {
    generation: u64,
    fingerprint: String,
    offset: usize,
    key: Option<String>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Cursor {
    generation: u64,
    after: String,
    fingerprint: String,
}

/// List pages keep the domain's 1..200 bound. Their opaque continuation embeds
/// the generation: a later write requires restarting, never skipping/repeating.
/// Non-page reads keep the frozen domain shape; large list destinations must
/// use TaskList/ListMode rather than a diagnostic snapshot.
pub fn query_page(
    store: &mut Store,
    query: &Query,
    inputs: &QueryInputs,
) -> Result<QueryPage, QueryError> {
    query_collection_page(store, query, inputs, 200, None)
}

/// Page canonical projects, tags and Review queue results at the runtime port.
/// Keep query/inputs unchanged while following a collection continuation.
pub fn query_collection_page(
    store: &mut Store,
    query: &Query,
    inputs: &QueryInputs,
    collection_limit: u32,
    collection_after: Option<&str>,
) -> Result<QueryPage, QueryError> {
    if !(1..=200).contains(&collection_limit) {
        return Err(QueryError::Refused(DomainError::field(
            bb_domain::types::Reason::InvalidValue,
            "limit",
        )));
    }
    store.read(|tx| {
        Ok((|| {
            let (workspace, generation, stale): (String, i64, i64) = tx
                .query_row(
                    "SELECT workspace_id, projection_generation, projection_stale FROM sync_meta",
                    [],
                    |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
                )
                .map_err(StoreError::from)?;
            if stale != 0 {
                return Err(QueryError::Store(StoreError::Corrupt));
            }
            let generation = unsigned(generation)?;
            let mut fingerprint_query = query.clone();
            if let Query::TaskList { page, .. } | Query::ListMode { page, .. } =
                &mut fingerprint_query
            {
                page.after = None;
            }
            let task_fingerprint = sha256_hex(
                &serde_json::to_vec(&(&fingerprint_query, inputs))
                    .map_err(|_| QueryError::Store(StoreError::Corrupt))?,
            );
            let mut query = query.clone();
            if let Query::TaskList { page, .. } | Query::ListMode { page, .. } = &mut query
                && let Some(after) = &page.after
            {
                let cursor: Cursor =
                    serde_json::from_str(after).map_err(|_| QueryError::RestartRequired)?;
                if cursor.generation != generation || cursor.fingerprint != task_fingerprint {
                    return Err(QueryError::RestartRequired);
                }
                page.after = Some(cursor.after);
            }
            let state = read_projection(tx, &workspace)?;
            let fingerprint = sha256_hex(
                &serde_json::to_vec(&(&query, inputs))
                    .map_err(|_| QueryError::Store(StoreError::Corrupt))?,
            );
            let cursor = collection_after
                .map(|token| {
                    serde_json::from_str::<CollectionCursor>(token)
                        .map_err(|_| QueryError::RestartRequired)
                })
                .transpose()?;
            if cursor.as_ref().is_some_and(|cursor| {
                cursor.generation != generation || cursor.fingerprint != fingerprint
            }) {
                return Err(QueryError::RestartRequired);
            }
            if matches!(
                query,
                Query::RestartCandidates {}
                    | Query::AutoParkDue {}
                    | Query::Projects { .. }
                    | Query::Tags {}
                    | Query::OpenReleases { .. }
            ) {
                if cursor
                    .as_ref()
                    .is_some_and(|cursor| cursor.offset != 0 || cursor.key.is_none())
                {
                    return Err(QueryError::RestartRequired);
                }
                let after = cursor.as_ref().and_then(|cursor| cursor.key.as_deref());
                let (result, next) = if matches!(query, Query::Projects { .. } | Query::Tags {}) {
                    bb_domain::queries::classification_page(&state, &query, collection_limit, after)
                } else if matches!(query, Query::OpenReleases { .. }) {
                    bb_domain::review_sessions::native_release_page(
                        &state,
                        &query,
                        inputs,
                        collection_limit,
                        after,
                    )
                } else {
                    bb_domain::review_sessions::native_task_page(
                        &state,
                        &query,
                        inputs,
                        collection_limit,
                        after,
                    )
                }
                .map_err(|error| QueryError::RefusedAt {
                    error,
                    projection_generation: generation,
                })?;
                let collection_next_cursor = next
                    .map(|key| {
                        serde_json::to_string(&CollectionCursor {
                            generation,
                            fingerprint,
                            offset: 0,
                            key: Some(key),
                        })
                        .map_err(|_| QueryError::Store(StoreError::Corrupt))
                    })
                    .transpose()?;
                return Ok(QueryPage {
                    projection_generation: generation,
                    result,
                    collection_next_cursor,
                });
            }
            if cursor.as_ref().is_some_and(|cursor| cursor.key.is_some()) {
                return Err(QueryError::RestartRequired);
            }
            if matches!(query, Query::ReviewQueue { .. }) {
                let offset = cursor.as_ref().map_or(0, |cursor| cursor.offset);
                let (result, next) = bb_domain::review_sessions::native_queue_page(
                    &state,
                    &query,
                    inputs,
                    collection_limit,
                    offset,
                )
                .map_err(|error| QueryError::RefusedAt {
                    error,
                    projection_generation: generation,
                })?;
                let collection_next_cursor = next
                    .map(|offset| {
                        serde_json::to_string(&CollectionCursor {
                            generation,
                            fingerprint,
                            offset,
                            key: None,
                        })
                        .map_err(|_| QueryError::Store(StoreError::Corrupt))
                    })
                    .transpose()?;
                return Ok(QueryPage {
                    projection_generation: generation,
                    result,
                    collection_next_cursor,
                });
            }
            let mut result =
                dispatch::query(&state, &query, inputs).map_err(|error| QueryError::RefusedAt {
                    error,
                    projection_generation: generation,
                })?;
            if collection_after.is_some() {
                return Err(QueryError::RestartRequired);
            }
            let collection_next_cursor = None;
            let next = match &mut result {
                QueryResult::TaskList(page) => &mut page.next_cursor,
                QueryResult::ListMode(page) => &mut page.next_cursor,
                _ => {
                    return Ok(QueryPage {
                        projection_generation: generation,
                        result,
                        collection_next_cursor,
                    });
                }
            };
            if let Some(after) = next.take() {
                *next = Some(
                    serde_json::to_string(&Cursor {
                        generation,
                        after,
                        fingerprint: task_fingerprint.clone(),
                    })
                    .map_err(|_| QueryError::Store(StoreError::Corrupt))?,
                );
            }
            Ok(QueryPage {
                projection_generation: generation,
                result,
                collection_next_cursor,
            })
        })())
    })?
}

/// Tokens contain hashes of safe metadata only. Issue changes at the same
/// projection generation and authentication/queue changes still invalidate.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WorkspaceWatch {
    pub projection_generation: u64,
    pub pending: u64,
    pub open_issues: u64,
    pub issues_token: String,
    pub status_token: String,
}

pub fn workspace_watch(store: &mut Store) -> Result<WorkspaceWatch, StoreError> {
    store
        .read(|tx| {
            let (generation, status): (i64, String) = tx.query_row(
                "SELECT projection_generation, json_array(workspace_generation, session_generation,
                local_sync_generation, server_generation, device_epoch_state, account_link_state,
                cursor, last_success_at) FROM sync_meta",
                [],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )?;
            let pending: i64 = tx.query_row(
                "SELECT COUNT(*) FROM outbox WHERE state NOT IN ('completed', 'rejected')",
                [],
                |row| row.get(0),
            )?;
            let open_issues: i64 = tx.query_row(
                "SELECT COUNT(*) FROM sync_issues WHERE resolution = 'open'",
                [],
                |row| row.get(0),
            )?;
            let issues_token = issues_token(tx)?;
            let mut queue =
                tx.prepare("SELECT command_id, state, attempts FROM outbox ORDER BY command_id")?;
            let queued = queue
                .query_map([], |row| {
                    Ok((
                        row.get::<_, String>(0)?,
                        row.get::<_, String>(1)?,
                        row.get::<_, i64>(2)?,
                    ))
                })?
                .collect::<Result<Vec<_>, _>>()?;
            let status_token = sha256_hex(
                &serde_json::to_vec(&(status, queued))
                    .map_err(|_| rusqlite::Error::InvalidQuery)?,
            );
            Ok((generation, pending, open_issues, issues_token, status_token))
        })
        .and_then(
            |(generation, pending, open_issues, issues_token, status_token)| {
                Ok(WorkspaceWatch {
                    projection_generation: u64::try_from(generation)
                        .map_err(|_| StoreError::Corrupt)?,
                    pending: u64::try_from(pending).map_err(|_| StoreError::Corrupt)?,
                    open_issues: u64::try_from(open_issues).map_err(|_| StoreError::Corrupt)?,
                    issues_token,
                    status_token,
                })
            },
        )
}

/// Run a pure draft read against one consistent durable generation. The closure
/// cannot outlive the protected read set; no host snapshot becomes a rule source.
pub fn workspace_read<T>(
    store: &mut Store,
    expected_generation: Option<u64>,
    read: impl FnOnce(&bb_domain::types::ReadSet) -> T,
) -> Result<(u64, T), QueryError> {
    store.read(|tx| {
        Ok((|| {
            let (workspace, generation, stale): (String, i64, i64) = tx
                .query_row(
                    "SELECT workspace_id, projection_generation, projection_stale FROM sync_meta",
                    [],
                    |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
                )
                .map_err(StoreError::from)?;
            if stale != 0 {
                return Err(QueryError::Store(StoreError::Corrupt));
            }
            let generation = unsigned(generation)?;
            if expected_generation.is_some_and(|expected| expected != generation) {
                return Err(QueryError::RestartRequired);
            }
            let state = read_projection(tx, &workspace)?;
            Ok((generation, read(&state)))
        })())
    })?
}

fn issues_token(tx: &rusqlite::Transaction<'_>) -> rusqlite::Result<String> {
    let mut statement = tx.prepare("SELECT issue_id, reason, resolution, shown_base_revision, dependent_ids, resolved_at FROM sync_issues ORDER BY issue_id")?;
    let rows = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, Option<String>>(5)?,
            ))
        })?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(sha256_hex(
        &serde_json::to_vec(&rows).map_err(|_| rusqlite::Error::InvalidQuery)?,
    ))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct IssueCursor {
    generation: u64,
    token: String,
    after: String,
}

#[derive(Debug, Clone)]
pub struct IssuePage {
    pub projection_generation: u64,
    pub items: Vec<serde_json::Value>,
    pub next_cursor: Option<String>,
}

/// Payloads stay bounded; issue-only invalidation fences a continuation even
/// when no task projection changed.
pub fn workspace_issues_page(
    store: &mut Store,
    limit: u32,
    after: Option<&str>,
) -> Result<IssuePage, QueryError> {
    if !(1..=200).contains(&limit) {
        return Err(QueryError::Refused(DomainError::field(
            bb_domain::types::Reason::InvalidValue,
            "limit",
        )));
    }
    store.read(|tx| Ok((|| {
        let (workspace, generation): (String, i64) = tx.query_row("SELECT workspace_id, projection_generation FROM sync_meta", [], |r| Ok((r.get(0)?,r.get(1)?))).map_err(StoreError::from)?;
        let generation = unsigned(generation)?;
        let token = issues_token(tx).map_err(StoreError::from)?;
        let after = after.map(|value| serde_json::from_str::<IssueCursor>(value).map_err(|_| QueryError::RestartRequired)).transpose()?;
        if after.as_ref().is_some_and(|cursor| cursor.generation != generation || cursor.token != token) { return Err(QueryError::RestartRequired); }
        let key = after.as_ref().map_or("", |cursor| cursor.after.as_str());
        let mut statement = tx.prepare("SELECT issue_id, command_id, reason, local_intent, local_text, shown_base_revision, dependent_ids, created_at FROM sync_issues WHERE workspace_id = ?1 AND resolution = 'open' AND issue_id > ?2 ORDER BY issue_id LIMIT ?3").map_err(StoreError::from)?;
        let mut rows = statement.query(rusqlite::params![workspace, key, i64::from(limit)+1]).map_err(StoreError::from)?;
        let mut items = Vec::with_capacity(limit as usize + 1);
        while let Some(row) = rows.next().map_err(StoreError::from)? {
            let intent: Vec<u8> = row.get(3).map_err(StoreError::from)?;
            let text: Option<Vec<u8>> = row.get(4).map_err(StoreError::from)?;
            let dependents: String = row.get(6).map_err(StoreError::from)?;
            items.push(serde_json::json!({"issue_id":row.get::<_,String>(0).map_err(StoreError::from)?, "command_id":row.get::<_,String>(1).map_err(StoreError::from)?, "reason":row.get::<_,String>(2).map_err(StoreError::from)?, "local_intent":serde_json::from_slice::<serde_json::Value>(&intent).map_err(|_| QueryError::Store(StoreError::Corrupt))?, "local_text":text.map(|bytes| serde_json::from_slice::<serde_json::Value>(&bytes)).transpose().map_err(|_| QueryError::Store(StoreError::Corrupt))?, "shown_base_revision":row.get::<_,Option<String>>(5).map_err(StoreError::from)?, "dependent_ids":serde_json::from_str::<serde_json::Value>(&dependents).map_err(|_| QueryError::Store(StoreError::Corrupt))?, "created_at":row.get::<_,String>(7).map_err(StoreError::from)?}));
        }
        let more = items.len() > limit as usize;
        items.truncate(limit as usize);
        let next_cursor = if more { Some(serde_json::to_string(&IssueCursor { generation, token, after:items.last().and_then(|item| item["issue_id"].as_str()).ok_or(QueryError::Store(StoreError::Corrupt))?.to_owned() }).map_err(|_| QueryError::Store(StoreError::Corrupt))?) } else { None };
        Ok(IssuePage { projection_generation:generation, items, next_cursor })
    })()))?
}

#[derive(Debug, Clone, Serialize)]
pub struct WorkspaceSyncStatus {
    pub projection_generation: String,
    pub pending: String,
    pub open_issues: String,
    pub last_success_at: Option<String>,
    pub oldest_pending_at: Option<String>,
    pub device_epoch_state: String,
    pub account_link_state: String,
}

pub fn workspace_sync_status(store: &mut Store) -> Result<WorkspaceSyncStatus, StoreError> {
    store.read(|tx| {
        let (generation,last_success_at,device_epoch_state,account_link_state):(i64,Option<String>,String,String) = tx.query_row("SELECT projection_generation,last_success_at,device_epoch_state,account_link_state FROM sync_meta", [], |row| Ok((row.get(0)?,row.get(1)?,row.get(2)?,row.get(3)?)))?;
        let (pending,oldest_pending_at):(i64,Option<String>) = tx.query_row("SELECT COUNT(*),MIN(created_at) FROM outbox WHERE state NOT IN ('completed','rejected')", [], |row| Ok((row.get(0)?,row.get(1)?)))?;
        let issues:i64 = tx.query_row("SELECT COUNT(*) FROM sync_issues WHERE resolution='open'", [], |row| row.get(0))?;
        Ok(WorkspaceSyncStatus { projection_generation:generation.to_string(),pending:pending.to_string(),open_issues:issues.to_string(),last_success_at,oldest_pending_at,device_epoch_state,account_link_state })
    })
}

/// Lookup only proven aliases for the touched identities; authored strings are
/// never searched or rewritten, and no foreign workspace can supply a binding.
pub fn resolve_workspace_identities(
    store: &mut Store,
    items: &[(bb_protocol::catalog::EntityType, String)],
) -> Result<Vec<Option<String>>, QueryError> {
    use rusqlite::OptionalExtension;
    if items.len() > 200 {
        return Err(QueryError::Refused(DomainError::field(
            bb_domain::types::Reason::TooManyItems,
            "items",
        )));
    }
    Ok(store.read(|tx| {
        let workspace:String = tx.query_row("SELECT workspace_id FROM sync_meta",[],|r|r.get(0))?;
        let mut query = tx.prepare("SELECT server_id FROM identity_aliases WHERE workspace_id = ?1 AND entity_type = ?2 AND old_local_id = ?3")?;
        let mut canonical = tx.prepare("SELECT 1 FROM visible_records WHERE workspace_id = ?1 AND record_type = ?2 AND record_key = ?3")?;
        items.iter().map(|(kind,id)| {
            let key = serde_json::to_string(&vec![id]).map_err(|_| rusqlite::Error::InvalidQuery)?;
            if canonical.query_row(rusqlite::params![workspace,kind.as_str(),key], |_| Ok(())).optional()?.is_some() {
                return Ok(Some(id.clone()));
            }
            query.query_row(rusqlite::params![workspace,kind.as_str(),id],|r|r.get(0)).optional()
        }).collect()
    })?)
}

/// Durable host presentation/gesture drafts. These never participate in sync,
/// canonical rule evaluation or immutable legacy carrier storage.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct WorkspaceDraft {
    pub draft_id: String,
    pub editor_kind: String,
    pub record_type: Option<String>,
    pub record_key: Option<String>,
    pub base_revision: Option<String>,
    pub fields: serde_json::Value,
    pub updated_at: String,
}

fn draft_id_valid(id: &str) -> bool {
    id.starts_with("runtime:") && id.len() > "runtime:".len() && id.len() <= 512
}

pub fn load_workspace_draft(
    store: &mut Store,
    id: &str,
) -> Result<Option<WorkspaceDraft>, QueryError> {
    use rusqlite::OptionalExtension;
    if !draft_id_valid(id) {
        return Err(QueryError::Refused(DomainError::field(
            bb_domain::types::Reason::InvalidValue,
            "draft_id",
        )));
    }
    store.read(|tx| Ok((|| {
        type DraftColumns = (String,Option<String>,Option<String>,Option<String>,Vec<u8>,String);
        let row:Option<DraftColumns> = tx.query_row("SELECT editor_kind,record_type,record_key,base_revision,fields,updated_at FROM drafts WHERE workspace_id=(SELECT workspace_id FROM sync_meta) AND draft_id=?1 AND editor_kind LIKE 'runtime_%'",[id],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?,r.get(3)?,r.get(4)?,r.get(5)?))).optional().map_err(StoreError::from)?;
        row.map(|(editor_kind,record_type,record_key,base_revision,fields,updated_at)| Ok(WorkspaceDraft {draft_id:id.to_owned(),editor_kind,record_type,record_key,base_revision,fields:serde_json::from_slice(&fields).map_err(|_| QueryError::Store(StoreError::Corrupt))?,updated_at})).transpose()
    })()))?
}

pub fn save_workspace_draft_with(
    store: &mut Store,
    draft: &WorkspaceDraft,
    before_commit: impl FnOnce() -> Result<(), crate::ExecuteError>,
) -> Result<(), crate::ExecuteError> {
    let invalid = |field| {
        crate::ExecuteError::Refused(DomainError::field(
            bb_domain::types::Reason::InvalidValue,
            field,
        ))
    };
    if !draft_id_valid(&draft.draft_id) || !draft.editor_kind.starts_with("runtime_") {
        return Err(invalid("draft_id"));
    }
    bb_protocol::wire::Instant::parse(&draft.updated_at).map_err(|_| invalid("updated_at"))?;
    let bytes = serde_json::to_vec(&draft.fields)
        .map_err(|_| crate::ExecuteError::Store(StoreError::Corrupt))?;
    if bytes.len() > 2 * 1024 * 1024 {
        return Err(invalid("fields"));
    }
    store.try_write(|tx| {
        tx.execute("INSERT INTO drafts(workspace_id,draft_id,editor_kind,record_type,record_key,base_revision,fields,updated_at) VALUES ((SELECT workspace_id FROM sync_meta),?1,?2,?3,?4,?5,?6,?7) ON CONFLICT(workspace_id,draft_id) DO UPDATE SET editor_kind=excluded.editor_kind,record_type=excluded.record_type,record_key=excluded.record_key,base_revision=excluded.base_revision,fields=excluded.fields,updated_at=excluded.updated_at",rusqlite::params![draft.draft_id,draft.editor_kind,draft.record_type,draft.record_key,draft.base_revision,bytes,draft.updated_at])?;
        before_commit()
    })
}

pub fn delete_workspace_draft_with(
    store: &mut Store,
    id: &str,
    before_commit: impl FnOnce() -> Result<(), crate::ExecuteError>,
) -> Result<(), crate::ExecuteError> {
    if !draft_id_valid(id) {
        return Err(crate::ExecuteError::Refused(DomainError::field(
            bb_domain::types::Reason::InvalidValue,
            "draft_id",
        )));
    }
    store.try_write(|tx| {
        tx.execute("DELETE FROM drafts WHERE workspace_id=(SELECT workspace_id FROM sync_meta) AND draft_id=?1 AND editor_kind LIKE 'runtime_%'",[id])?;
        before_commit()
    })
}
