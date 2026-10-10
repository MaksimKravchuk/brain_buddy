//! Local, content-free admission of the original rendered task frame.
//! Tokens are never sync preconditions or replay authority.
use crate::{StoreError, execute::ExecuteError, local_task_origin_in, sha256_hex};
use bb_domain::types::{DomainError, OpenList, QueryResult, ReadSet, Reason, TaskId, TaskView};
use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeSet;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ShownFrameToken {
    pub version: u32,
    pub workspace_id: String,
    pub task_id: TaskId,
    pub children_known: bool,
    /// Canonical identities in visible relative order.
    pub subtask_ids: Vec<String>,
    /// Canonical identities sorted by ID (comment times/authors are excluded).
    pub comment_ids: Vec<String>,
    pub semantic_digest: String,
    pub local_child_edit_witness: String,
}

/// Sibling metadata belongs to the same read as the original TaskView.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ShownTaskFrame {
    pub token: ShownFrameToken,
    pub last_open_list: Option<OpenList>,
}

fn changed(task: &TaskId) -> ExecuteError {
    DomainError::about(
        Reason::FormulationChanged,
        bb_protocol::catalog::EntityType::Task,
        vec![task.as_str().to_owned()],
    )
    .into()
}

fn child_witness(conn: &Connection, workspace: &str, task: &TaskId) -> Result<String, StoreError> {
    let seq: i64 = conn.query_row(
        "SELECT COALESCE(MAX(local_seq),0) FROM outbox WHERE workspace_id=?1
         AND json_extract(CAST(envelope AS TEXT),'$.type') IN
         ('subtask.create','subtask.update','subtask.transition','comment.create','comment.update')
         AND json_extract(CAST(envelope AS TEXT),'$.payload.task_id')=?2",
        params![workspace, task.as_str()],
        |row| row.get(0),
    )?;
    u64::try_from(seq)
        .map(|seq| seq.to_string())
        .map_err(|_| StoreError::Corrupt)
}

fn detail_known(conn: &Connection, workspace: &str, task: &TaskId) -> Result<bool, StoreError> {
    let carrier: Option<Vec<u8>> = conn.query_row(
        "SELECT fields FROM drafts WHERE workspace_id=?1 AND editor_kind='legacy_task_local' AND record_key=?2",
        params![workspace,json!([task.as_str()]).to_string()], |row| row.get(0)).optional()?;
    if let Some(body) = carrier {
        let body: Value = serde_json::from_slice(&body).map_err(|_| StoreError::Corrupt)?;
        if body
            .get("childrenSyncedAt")
            .is_some_and(|value| !value.is_null())
        {
            return Ok(true);
        }
    }
    // An omitted alias is not proof: imported serverID may equal localID.
    // Both constructors refuse an existing task and create an empty child set.
    // Their retained result must prove this exact task was actually produced;
    // command type alone cannot turn an imported partial frame into a full one.
    // A complete active server snapshot independently proves source completeness.
    Ok(conn.query_row(
        "SELECT EXISTS(SELECT 1 FROM outbox o WHERE o.workspace_id=?1
           AND o.state NOT IN ('rejected','blocked_dependency') AND o.superseded_by IS NULL
           AND json_extract(CAST(o.envelope AS TEXT),'$.type') IN ('task.create','task.smart_add')
           AND json_extract(CAST(o.envelope AS TEXT),'$.entity_id')=?2
           AND EXISTS(SELECT 1 FROM json_each(CAST(o.local_result AS TEXT),'$.versions') v
             WHERE json_extract(v.value,'$.entity_type')='task'
               AND json_array_length(json_extract(v.value,'$.record_key'))=1
               AND json_extract(v.value,'$.record_key[0]')=?2
               AND json_extract(v.value,'$.edit_revision') IS NOT NULL))
         OR EXISTS(SELECT 1 FROM staging_bases b JOIN sync_meta m USING(workspace_id)
           WHERE b.workspace_id=?1 AND b.kind='snapshot' AND b.state='activated'
           AND b.target_generation=m.server_generation
           AND json_extract(CAST(b.manifest AS TEXT),'$.snapshot_id') IS NOT NULL)",
        params![workspace, task.as_str()],
        |row| row.get(0),
    )?)
}

fn digest(
    conn: &Connection,
    workspace: &str,
    state: &ReadSet,
    token: &ShownFrameToken,
) -> Result<String, ExecuteError> {
    let task = state
        .tasks
        .get(&token.task_id)
        .ok_or_else(|| changed(&token.task_id))?;
    let mut parent = serde_json::to_value(task.public()).map_err(crate::execute::corrupt)?;
    let fields = parent
        .as_object_mut()
        .ok_or_else(|| crate::execute::corrupt(()))?;
    for key in [
        "revision",
        "order_key",
        "waiting_since",
        "completed_at",
        "cancelled_at",
        "created_at",
        "updated_at",
        "source_capture_ids",
    ] {
        fields.remove(key);
    }
    if task.state != bb_domain::types::TaskState::Next {
        fields.insert("formulation".into(), Value::Null);
    }
    if task.state != bb_domain::types::TaskState::Someday {
        fields.insert("parked".into(), Value::Null);
    }
    fields.insert(
        "last_open_list".into(),
        json!(local_task_origin_in(conn, workspace, &task.id)?),
    );
    let shown_subtasks = token
        .subtask_ids
        .iter()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let shown_comments = token
        .comment_ids
        .iter()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    if shown_subtasks.len() != token.subtask_ids.len()
        || shown_comments.len() != token.comment_ids.len()
        || !token.comment_ids.windows(2).all(|ids| ids[0] < ids[1])
    {
        return Err(changed(&token.task_id));
    }
    let mut subtasks = Vec::with_capacity(token.subtask_ids.len());
    for child in state
        .subtasks
        .values()
        .filter(|child| child.task_id == task.id)
    {
        if shown_subtasks.contains(child.id.as_str()) {
            subtasks.push(child);
        } else if token.children_known {
            return Err(changed(&token.task_id));
        }
    }
    subtasks.sort_by(|a, b| {
        (a.order_key.to_u64(), a.id.as_str()).cmp(&(b.order_key.to_u64(), b.id.as_str()))
    });
    let mut comments = Vec::with_capacity(token.comment_ids.len());
    for child in state
        .comments
        .values()
        .filter(|child| child.task_id == task.id)
    {
        if shown_comments.contains(child.id.as_str()) {
            comments.push(child);
        } else if token.children_known {
            return Err(changed(&token.task_id));
        }
    }
    comments.sort_by(|a, b| a.id.cmp(&b.id));
    if subtasks
        .iter()
        .map(|child| child.id.as_str())
        .collect::<Vec<_>>()
        != token
            .subtask_ids
            .iter()
            .map(String::as_str)
            .collect::<Vec<_>>()
        || comments
            .iter()
            .map(|child| child.id.as_str())
            .collect::<Vec<_>>()
            != token
                .comment_ids
                .iter()
                .map(String::as_str)
                .collect::<Vec<_>>()
    {
        return Err(changed(&token.task_id));
    }
    let subtasks = subtasks
        .iter()
        .map(|child| {
            let mut value = json!({"id":child.id,"title":child.title,"state":child.state});
            if token.children_known {
                value["order_key"] = json!(child.order_key);
            }
            value
        })
        .collect::<Vec<_>>();
    let comments = comments
        .iter()
        .map(|child| json!({"id":child.id,"body":child.body}))
        .collect::<Vec<_>>();
    let bytes = serde_json::to_vec(&json!({"domain":"brainbuddy.local.shown-frame.v1", "workspace_id":workspace, "task":parent,"subtasks":subtasks,"comments":comments})).map_err(crate::execute::corrupt)?;
    Ok(sha256_hex(&bytes))
}

pub(crate) fn capture_frame(
    conn: &Connection,
    workspace: &str,
    state: &ReadSet,
    view: &TaskView,
    detail: bool,
) -> Result<ShownTaskFrame, ExecuteError> {
    let children_known = detail
        && view.subtasks.len() + view.comments.len() <= 200
        && detail_known(conn, workspace, &view.id)?;
    let mut subtasks = view.subtasks.iter().collect::<Vec<_>>();
    subtasks.sort_by(|a, b| {
        (a.order_key.to_u64(), a.id.as_str()).cmp(&(b.order_key.to_u64(), b.id.as_str()))
    });
    let mut comment_ids = view
        .comments
        .iter()
        .map(|child| child.id.as_str().to_owned())
        .collect::<Vec<_>>();
    comment_ids.sort();
    let mut token = ShownFrameToken {
        version: 1,
        workspace_id: workspace.to_owned(),
        task_id: view.id.clone(),
        children_known,
        subtask_ids: subtasks
            .iter()
            .map(|child| child.id.as_str().to_owned())
            .collect(),
        comment_ids,
        semantic_digest: String::new(),
        local_child_edit_witness: child_witness(conn, workspace, &view.id)?,
    };
    token.semantic_digest = digest(conn, workspace, state, &token)?;
    Ok(ShownTaskFrame {
        token,
        last_open_list: local_task_origin_in(conn, workspace, &view.id)?,
    })
}

pub(crate) fn query_frames(
    conn: &Connection,
    workspace: &str,
    state: &ReadSet,
    result: &QueryResult,
    detail_complete: bool,
) -> Result<Vec<ShownTaskFrame>, ExecuteError> {
    let (views, detail): (Vec<&TaskView>, bool) = match result {
        QueryResult::TaskDetail(view) => (vec![view], detail_complete),
        QueryResult::TaskList(page) => (page.items.iter().collect(), false),
        QueryResult::ListMode(page) => (
            page.sections
                .iter()
                .flat_map(|section| &section.items)
                .collect(),
            false,
        ),
        QueryResult::ReviewQueue(queue) => (queue.items.iter().collect(), false),
        QueryResult::RestartCandidates(views) | QueryResult::AutoParkDue(views) => {
            (views.iter().collect(), false)
        }
        _ => (Vec::new(), false),
    };
    views
        .into_iter()
        .map(|view| capture_frame(conn, workspace, state, view, detail))
        .collect()
}

pub(crate) fn validate(
    conn: &Connection,
    workspace: &str,
    state: &ReadSet,
    tokens: &[ShownFrameToken],
) -> Result<(), ExecuteError> {
    let mut tasks = BTreeSet::new();
    for token in tokens {
        if token.subtask_ids.len() + token.comment_ids.len() > 200
            || token.version != 1
            || token.workspace_id != workspace
            || !tasks.insert(&token.task_id)
            || token.local_child_edit_witness != child_witness(conn, workspace, &token.task_id)?
            || token.semantic_digest != digest(conn, workspace, state, token)?
        {
            return Err(changed(&token.task_id));
        }
    }
    Ok(())
}
