//! Device-only task origins. The import carrier is immutable; an overlay with
//! explicit nulls prevents cleared knowledge from falling back to that carrier.
use crate::{Store, StoreError};
use bb_domain::types::{DomainChange, OpenList, ReadSet, Record, TaskId, TaskState};
use bb_protocol::{catalog::EntityType, receipt::Receipt, wire::CommandId};
use rusqlite::{Connection, OptionalExtension, Transaction, params};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

const KIND: &str = "runtime_task_local";

#[derive(Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub(crate) struct Fact {
    confirmed: Option<OpenList>,
    visible: Option<OpenList>,
    // These are projections of existing outbox commands, not command authority.
    // Uncertain commands keep their original witness even when replay is held.
    candidates: BTreeMap<String, Candidate>,
}

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
struct Candidate {
    origin: OpenList,
    state: TaskState,
}

pub(crate) type Facts = BTreeMap<TaskId, Fact>;

fn decode<T: serde::de::DeserializeOwned>(body: &[u8]) -> Result<T, StoreError> {
    serde_json::from_slice(body).map_err(|_| StoreError::Corrupt)
}

pub(crate) fn load(conn: &Connection, workspace: &str) -> Result<Facts, StoreError> {
    let mut facts = Facts::new();
    let mut statement = conn.prepare(
        "SELECT record_key, fields FROM drafts WHERE workspace_id = ?1 AND editor_kind = ?2",
    )?;
    for row in statement.query_map(params![workspace, KIND], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
    })? {
        let (key, body) = row?;
        let key: Vec<String> = decode(key.as_bytes())?;
        let id = TaskId::parse(key.first().ok_or(StoreError::Corrupt)?)
            .map_err(|_| StoreError::Corrupt)?;
        facts.insert(id, decode(&body)?);
    }
    let mut statement = conn.prepare(
        "SELECT record_key, fields FROM drafts WHERE workspace_id = ?1 AND editor_kind = 'legacy_task_local'",
    )?;
    for row in statement.query_map([workspace], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, Vec<u8>>(1)?))
    })? {
        let (key, body) = row?;
        let key: Vec<String> = decode(key.as_bytes())?;
        let id = TaskId::parse(key.first().ok_or(StoreError::Corrupt)?)
            .map_err(|_| StoreError::Corrupt)?;
        if let std::collections::btree_map::Entry::Vacant(entry) = facts.entry(id) {
            let body: serde_json::Value = decode(&body)?;
            let origin = body
                .get("lastOpenList")
                .filter(|v| !v.is_null())
                .map(|v| serde_json::from_value(v.clone()).map_err(|_| StoreError::Corrupt))
                .transpose()?;
            entry.insert(Fact {
                confirmed: origin,
                visible: origin,
                ..Fact::default()
            });
        }
    }
    Ok(facts)
}

/// Exact visible origin for one task, under the query's read transaction.
pub fn local_task_origin_in(
    conn: &Connection,
    workspace: &str,
    id: &TaskId,
) -> Result<Option<OpenList>, StoreError> {
    let row:Option<(String,Vec<u8>)>=conn.query_row(
        "SELECT editor_kind, fields FROM drafts WHERE workspace_id=?1 AND record_key=?2 AND editor_kind IN ('runtime_task_local','legacy_task_local') ORDER BY editor_kind DESC LIMIT 1",
        params![workspace,serde_json::json!([id.as_str()]).to_string()], |row|Ok((row.get(0)?,row.get(1)?))
    ).optional()?;
    match row {
        Some((kind, body)) if kind == KIND => Ok(decode::<Fact>(&body)?.visible),
        Some((_, body)) => {
            let value: serde_json::Value = decode(&body)?;
            value
                .get("lastOpenList")
                .filter(|value| !value.is_null())
                .map(|value| serde_json::from_value(value.clone()).map_err(|_| StoreError::Corrupt))
                .transpose()
        }
        None => Ok(None),
    }
}

/// Current device-only origins, bounded by the tasks in the caller's read set.
/// Call inside the same read transaction as the domain query.
pub fn local_task_origins_in(
    conn: &Connection,
    workspace: &str,
    read_set: &ReadSet,
) -> Result<BTreeMap<TaskId, OpenList>, StoreError> {
    let mut origins = BTreeMap::new();
    for (id, task) in &read_set.tasks {
        if !task.state.is_open()
            && let Some(origin) = local_task_origin_in(conn, workspace, id)?
        {
            origins.insert(id.clone(), origin);
        }
    }
    Ok(origins)
}

/// Read origins for an already bounded domain read set.
pub fn local_task_origins(
    store: &mut Store,
    read_set: &ReadSet,
) -> Result<BTreeMap<TaskId, OpenList>, StoreError> {
    store.read(|tx| {
        let workspace: String =
            tx.query_row("SELECT workspace_id FROM sync_meta", [], |r| r.get(0))?;
        Ok(local_task_origins_in(tx, &workspace, read_set))
    })?
}

pub(crate) fn reset_visible(facts: &mut Facts) {
    for fact in facts.values_mut() {
        fact.visible = fact.confirmed;
    }
}

fn transition(
    prior: Option<TaskState>,
    after: Option<TaskState>,
    origin: Option<OpenList>,
) -> Option<OpenList> {
    let after = after?;
    if after.is_open() {
        return None;
    }
    prior.and_then(|prior| {
        prior
            .open_list()
            .or_else(|| (prior == after).then_some(origin).flatten())
    })
}

pub(crate) fn project(
    facts: &mut Facts,
    read_set: &ReadSet,
    change: &DomainChange,
    command: &CommandId,
) {
    let (id, after) = match change {
        DomainChange::Upsert(Record::Task(task)) => (task.id.clone(), Some(task.state)),
        DomainChange::Tombstone {
            entity_type: EntityType::Task,
            record_key,
        } => {
            let Some(id) = record_key.first().and_then(|id| TaskId::parse(id).ok()) else {
                return;
            };
            (id, None)
        }
        _ => return,
    };
    let prior = read_set.tasks.get(&id).map(|task| task.state);
    if !facts.contains_key(&id) && transition(prior, after, None).is_none() {
        return;
    }
    let fact = facts.entry(id).or_default();
    fact.visible = transition(prior, after, fact.visible);
    if let (Some(origin), Some(state)) = (prior.and_then(TaskState::open_list), after)
        && !state.is_open()
    {
        fact.candidates
            .insert(command.as_str().to_owned(), Candidate { origin, state });
    }
}

pub(crate) fn save(
    tx: &Transaction<'_>,
    workspace: &str,
    facts: &Facts,
) -> Result<usize, StoreError> {
    let mut writes = 0;
    for (id, fact) in facts {
        let draft = format!("runtime-task-local:{}", id.as_str());
        let body = serde_json::to_vec(fact).map_err(|_| StoreError::Corrupt)?;
        let old: Option<Vec<u8>> = tx
            .query_row(
                "SELECT fields FROM drafts WHERE workspace_id = ?1 AND draft_id = ?2",
                params![workspace, draft],
                |r| r.get(0),
            )
            .optional()?;
        if old.as_deref() == Some(body.as_slice()) {
            continue;
        }
        tx.execute(
            "INSERT OR REPLACE INTO drafts (workspace_id, draft_id, editor_kind, record_type, record_key, fields, base_revision, updated_at)
             VALUES (?1, ?2, ?3, 'task', ?4, ?5, NULL, '1970-01-01T00:00:00Z')",
            params![workspace, draft, KIND, serde_json::json!([id.as_str()]).to_string(), body],
        )?;
        writes += 1;
    }
    Ok(writes)
}

/// Rejected/blocked intents no longer have a possible accepted proof path.
pub(crate) fn prune(
    tx: &Transaction<'_>,
    workspace: &str,
    facts: &mut Facts,
) -> Result<(), StoreError> {
    for fact in facts.values_mut() {
        let mut discard = Vec::new();
        for command in fact.candidates.keys() {
            let state: Option<String> = tx
                .query_row(
                    "SELECT state FROM outbox WHERE workspace_id = ?1 AND command_id = ?2",
                    params![workspace, command],
                    |r| r.get(0),
                )
                .optional()?;
            if state
                .as_deref()
                .is_none_or(|state| matches!(state, "rejected" | "blocked_dependency"))
            {
                discard.push(command.clone());
            }
        }
        for command in discard {
            fact.candidates.remove(&command);
        }
    }
    Ok(())
}

/// Feed inclusion finishes this command's candidate proof path. Its origin is
/// now in confirmed facts, independent of the prediction retained for an ACK.
pub(crate) fn included(facts: &mut Facts, command: &CommandId) {
    for fact in facts.values_mut() {
        fact.candidates.remove(command.as_str());
    }
}

fn confirmed_state(
    conn: &Connection,
    workspace: &str,
    id: &TaskId,
) -> Result<Option<TaskState>, StoreError> {
    state_at_key(
        conn,
        workspace,
        &serde_json::json!([id.as_str()]).to_string(),
    )
}

fn state_at_key(
    conn: &Connection,
    workspace: &str,
    key: &str,
) -> Result<Option<TaskState>, StoreError> {
    let body: Option<Option<Vec<u8>>> = conn.query_row(
        "SELECT body FROM confirmed_records WHERE workspace_id = ?1 AND record_type = 'task' AND record_key = ?2",
        params![workspace, key], |r| r.get(0),
    ).optional()?;
    body.flatten()
        .map(|body| decode::<bb_domain::types::Task>(&body).map(|task| task.state))
        .transpose()
}

pub(crate) fn before_change(
    conn: &Connection,
    workspace: &str,
    change: &bb_protocol::feed::Change,
) -> Result<Option<TaskState>, StoreError> {
    if change.entity_type != EntityType::Task {
        return Ok(None);
    }
    state_at_key(
        conn,
        workspace,
        &serde_json::json!(change.record_key).to_string(),
    )
}

/// Advance from the confirmed before-image, never the optimistic projection.
pub(crate) fn confirm_change(
    facts: &mut Facts,
    change: &bb_protocol::feed::Change,
    before: Option<TaskState>,
) -> Result<(), StoreError> {
    if change.entity_type != EntityType::Task {
        return Ok(());
    }
    let id = TaskId::parse(change.record_key.first().ok_or(StoreError::Corrupt)?)
        .map_err(|_| StoreError::Corrupt)?;
    let after = change
        .value
        .as_ref()
        .map(|value| {
            serde_json::from_value::<bb_domain::types::Task>(serde_json::Value::Object(
                value.clone(),
            ))
            .map(|task| task.state)
            .map_err(|_| StoreError::Corrupt)
        })
        .transpose()?;
    if !facts.contains_key(&id) && transition(before, after, None).is_none() {
        return Ok(());
    }
    let fact = facts.entry(id).or_default();
    fact.confirmed = transition(before, after, fact.confirmed);
    Ok(())
}

pub(crate) fn save_invalidating(
    tx: &Transaction<'_>,
    workspace: &str,
    facts: &Facts,
) -> Result<(), StoreError> {
    if save(tx, workspace, facts)? > 0 {
        tx.execute(
            "UPDATE sync_meta SET projection_generation = projection_generation + 1",
            [],
        )?;
    }
    Ok(())
}

/// Capture exact confirmed lineage before snapshot replacement.
pub(crate) fn snapshot_before(
    tx: &Transaction<'_>,
    workspace: &str,
) -> Result<(Facts, BTreeMap<TaskId, String>), StoreError> {
    let facts = load(tx, workspace)?;
    let mut versions = BTreeMap::new();
    for id in facts.keys() {
        let version = tx.query_row(
            "SELECT record_version FROM confirmed_records WHERE workspace_id = ?1 AND record_type = 'task' AND record_key = ?2",
            params![workspace, serde_json::json!([id.as_str()]).to_string()], |r| r.get::<_, String>(0),
        ).optional()?;
        if let Some(version) = version {
            versions.insert(id.clone(), version);
        }
    }
    Ok((facts, versions))
}

/// A snapshot only retains origins with exact record lineage. Receipt coverage
/// alone can settle an outbox row, but cannot prove a task's current origin.
pub(crate) fn snapshot_after(
    tx: &Transaction<'_>,
    workspace: &str,
    mut before: (Facts, BTreeMap<TaskId, String>),
    same_generation: bool,
    target: &str,
    watermark: u64,
) -> Result<(), StoreError> {
    for (id, fact) in &mut before.0 {
        let key = serde_json::json!([id.as_str()]).to_string();
        let version: Option<String> = tx.query_row(
            "SELECT record_version FROM confirmed_records WHERE workspace_id = ?1 AND record_type = 'task' AND record_key = ?2",
            params![workspace, key], |r| r.get(0),
        ).optional()?;
        let state = confirmed_state(tx, workspace, id)?;
        let retained = state.is_some_and(|state| !state.is_open())
            && same_generation
            && version.is_some()
            && before.1.get(id) == version.as_ref();
        if !retained {
            fact.confirmed = None;
        }
        let mut discard = Vec::new();
        // Only existing outbox identity, an accepted current-generation receipt,
        // and an exact result version can activate a local transition witness.
        for (command, candidate) in &fact.candidates {
            let receipt: Option<Vec<u8>> = tx.query_row(
                "SELECT r.receipt FROM command_receipts r JOIN outbox o ON o.workspace_id = r.workspace_id AND o.command_id = r.command_id
                 WHERE r.workspace_id = ?1 AND r.command_id = ?2 AND r.server_generation = ?3 AND r.outcome = 'accepted'",
                params![workspace, command, target], |r| r.get(0),
            ).optional()?;
            let Some(receipt) = receipt else {
                continue;
            };
            let receipt: Receipt = decode(&receipt)?;
            if !receipt
                .commit_seq
                .as_ref()
                .and_then(|seq| seq.to_u64())
                .is_some_and(|seq| seq <= watermark)
            {
                continue;
            }
            let result = receipt.result_versions.iter().find(|result| {
                result.entity_type == EntityType::Task
                    && result.record_key == vec![id.as_str().to_owned()]
            });
            let Some(result) = result else {
                continue;
            };
            let exact = Some(result.record_version.as_str()) == version.as_deref();
            if !retained && exact && Some(candidate.state) == state {
                fact.confirmed = Some(candidate.origin);
                discard.push(command.clone());
            } else if state.is_none()
                || version.as_deref().is_some_and(|version| {
                    (version.len(), version)
                        > (
                            result.record_version.as_str().len(),
                            result.record_version.as_str(),
                        )
                })
            {
                // A later current-generation record (or authoritative deletion)
                // exhausts this candidate. Arbitrary inequality does not.
                discard.push(command.clone());
            }
        }
        for command in discard {
            fact.candidates.remove(&command);
        }
    }
    save_invalidating(tx, workspace, &before.0)?;
    Ok(())
}
