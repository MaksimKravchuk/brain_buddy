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
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Cursor {
    generation: u64,
    after: String,
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
            let mut query = query.clone();
            if let Query::TaskList { page, .. } | Query::ListMode { page, .. } = &mut query
                && let Some(after) = &page.after
            {
                let cursor: Cursor =
                    serde_json::from_str(after).map_err(|_| QueryError::RestartRequired)?;
                if cursor.generation != generation {
                    return Err(QueryError::RestartRequired);
                }
                page.after = Some(cursor.after);
            }
            let state = read_projection(tx, &workspace)?;
            let mut result =
                dispatch::query(&state, &query, inputs).map_err(QueryError::Refused)?;
            let fingerprint = sha256_hex(
                &serde_json::to_vec(&(&query, inputs))
                    .map_err(|_| QueryError::Store(StoreError::Corrupt))?,
            );
            let offset = if let Some(token) = collection_after {
                let cursor: CollectionCursor =
                    serde_json::from_str(token).map_err(|_| QueryError::RestartRequired)?;
                if cursor.generation != generation || cursor.fingerprint != fingerprint {
                    return Err(QueryError::RestartRequired);
                }
                cursor.offset
            } else {
                0
            };
            let mut collection_next_cursor = None;
            let mut slice = |length: usize| -> Result<std::ops::Range<usize>, QueryError> {
                if offset > length {
                    return Err(QueryError::RestartRequired);
                }
                let end = offset.saturating_add(collection_limit as usize).min(length);
                if end < length {
                    collection_next_cursor = Some(
                        serde_json::to_string(&CollectionCursor {
                            generation,
                            fingerprint: fingerprint.clone(),
                            offset: end,
                        })
                        .map_err(|_| QueryError::Store(StoreError::Corrupt))?,
                    );
                }
                Ok(offset..end)
            };
            match &mut result {
                QueryResult::Projects(items) => *items = items[slice(items.len())?].to_vec(),
                QueryResult::Tags(items) => *items = items[slice(items.len())?].to_vec(),
                QueryResult::ReviewQueue(queue) => {
                    queue.items = queue.items[slice(queue.items.len())?].to_vec()
                }
                _ if collection_after.is_some() => return Err(QueryError::RestartRequired),
                _ => {}
            }
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
                    serde_json::to_string(&Cursor { generation, after })
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
            let mut issues = tx.prepare(
            "SELECT issue_id, reason, resolution, shown_base_revision, dependent_ids, resolved_at
             FROM sync_issues ORDER BY issue_id",
        )?;
            let rows = issues
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
            // The hash leaves the runtime; authored local_intent/local_text never do.
            let issues_token =
                sha256_hex(&serde_json::to_vec(&rows).map_err(|_| rusqlite::Error::InvalidQuery)?);
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
