//! Ephemeral Mac review content stamps. No key, stamp or content ledger is persisted.
use crate::{
    QueryError, Store,
    execute::{Sha256, read_projection, unsigned},
    review_forms::reverse_in,
};
use bb_domain::{
    content_form,
    types::{DomainError, ProjectId, Reason, SubtaskId, TaskId, TaskState},
};
use bb_protocol::catalog::EntityType;
use rusqlite::{Connection, params};
use serde::Serialize;
use std::collections::{BTreeMap, BTreeSet};

pub const MAX_REVIEW_STAMP_KEY_BYTES: usize = 8 * 1024 * 1024;
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct TaskContentStamp {
    pub task_id: TaskId,
    pub stamp: String,
    pub record_keys: Vec<String>,
    pub primary_record_key: String,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ProjectContentStamp {
    pub project_id: ProjectId,
    pub signature: String,
    pub record_keys: Vec<String>,
    pub primary_record_key: String,
    pub counts_by_state: BTreeMap<String, u64>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct ReviewContentStamps {
    pub projection_generation: u64,
    pub tasks: Vec<TaskContentStamp>,
    pub projects: Vec<ProjectContentStamp>,
}
fn invalid(field: &str) -> QueryError {
    QueryError::Refused(DomainError::field(Reason::InvalidValue, field))
}
fn digest(bytes: &[u8]) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(bytes);
    h.finish()
}
fn hmac(key: &[u8], bytes: &[u8]) -> String {
    let mut block = [0u8; 64];
    if key.len() > 64 {
        block[..32].copy_from_slice(&digest(key));
    } else {
        block[..key.len()].copy_from_slice(key);
    }
    let mut inner = Sha256::new();
    inner.update(&block.map(|b| b ^ 0x36));
    inner.update(bytes);
    let mut outer = Sha256::new();
    outer.update(&block.map(|b| b ^ 0x5c));
    outer.update(&inner.finish());
    outer
        .finish()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
fn record_keys(
    conn: &Connection,
    workspace: &str,
    kind: EntityType,
    id: &str,
) -> Result<(Vec<String>, String), QueryError> {
    let source = reverse_in(conn, workspace, kind, id)?;
    let mut candidates = if let Some(source) = source {
        let provenance: String = conn.query_row(
            "SELECT provenance FROM identity_aliases WHERE workspace_id=?1 AND entity_type=?2 AND old_local_id=?3 AND server_id=?4",
            params![workspace, kind.as_str(), source, id], |row| row.get(0),
        ).map_err(crate::StoreError::from)?;
        if provenance == "legacy-import:normalized-local-id" {
            vec![format!("c:{source}"), format!("c:{id}")]
        } else {
            vec![format!("s:{id}"), format!("c:{source}"), format!("c:{id}")]
        }
    } else {
        // These are exact private mark namespaces, not a claim of server origin.
        vec![format!("c:{id}"), format!("s:{id}")]
    };
    let mut record_keys = Vec::new();
    for candidate in candidates.drain(..) {
        if let Some(local) = candidate.strip_prefix("c:") {
            let conflicting: bool = conn.query_row(
                "SELECT EXISTS(SELECT 1 FROM identity_aliases WHERE workspace_id=?1 AND entity_type=?2 AND old_local_id=?3 AND server_id<>?4)",
                params![workspace, kind.as_str(), local, id], |row| row.get(0),
            ).map_err(crate::StoreError::from)?;
            if conflicting {
                continue;
            }
        }
        if !record_keys.contains(&candidate) {
            record_keys.push(candidate);
        }
    }
    let primary = record_keys
        .first()
        .cloned()
        .ok_or_else(|| invalid("identity_ambiguity"))?;
    Ok((record_keys, primary))
}

/// One read transaction, complete canonical content and at most 200 scalar results.
pub fn review_content_stamps(
    store: &mut Store,
    key: &[u8],
    task_ids: &[TaskId],
    project_ids: &[ProjectId],
) -> Result<ReviewContentStamps, QueryError> {
    if key.len() > MAX_REVIEW_STAMP_KEY_BYTES {
        return Err(invalid("key"));
    }
    if task_ids.len().saturating_add(project_ids.len()) > 200 {
        return Err(invalid("items"));
    }
    store.read(|tx| {
        Ok((|| {
            let (workspace, generation): (String, i64) = tx
                .query_row(
                    "SELECT workspace_id,projection_generation FROM sync_meta",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .map_err(crate::StoreError::from)?;
            let state = read_projection(tx, &workspace)?;
            let selected_tasks: BTreeSet<_> = task_ids.iter().cloned().collect();
            let selected_projects: BTreeSet<_> = project_ids.iter().cloned().collect();
            let relevant: BTreeSet<_> = state
                .tasks
                .values()
                .filter(|task| {
                    selected_tasks.contains(&task.id)
                        || task
                            .project_id
                            .as_ref()
                            .is_some_and(|id| selected_projects.contains(id))
                })
                .map(|task| task.id.clone())
                .collect();
            let mut children: BTreeMap<SubtaskId, String> = BTreeMap::new();
            for child in state
                .subtasks
                .values()
                .filter(|child| relevant.contains(&child.task_id))
            {
                if let Some(logical) =
                    reverse_in(tx, &workspace, EntityType::Subtask, child.id.as_str())?
                {
                    children.insert(child.id.clone(), logical);
                }
            }
            let mut forms = BTreeMap::new();
            for id in relevant {
                let task = &state.tasks[&id];
                forms.insert(
                    id,
                    content_form::task_bytes(&state, task, &children)
                        .map_err(QueryError::Refused)?,
                );
            }
            let mut tasks = Vec::new();
            let mut seen = BTreeSet::new();
            for id in task_ids {
                if !seen.insert(id) || !state.tasks.contains_key(id) {
                    continue;
                }
                let (record_keys, primary_record_key) =
                    record_keys(tx, &workspace, EntityType::Task, id.as_str())?;
                tasks.push(TaskContentStamp {
                    task_id: id.clone(),
                    stamp: hmac(key, &forms[id]),
                    record_keys,
                    primary_record_key,
                });
            }
            let mut projects = Vec::new();
            let mut seen = BTreeSet::new();
            for id in project_ids {
                if !seen.insert(id) || !state.projects.contains_key(id) {
                    continue;
                }
                let mut counts_by_state: BTreeMap<String, u64> = [
                    TaskState::Inbox,
                    TaskState::Next,
                    TaskState::Waiting,
                    TaskState::Someday,
                    TaskState::Completed,
                    TaskState::Cancelled,
                ]
                .into_iter()
                .map(|s| (s.as_str().to_owned(), 0))
                .collect();
                let mut project_forms = Vec::new();
                for task in state
                    .tasks
                    .values()
                    .filter(|task| task.project_id.as_ref() == Some(id))
                {
                    *counts_by_state
                        .get_mut(task.state.as_str())
                        .expect("all states") += 1;
                    project_forms.push(forms[&task.id].clone());
                }
                let bytes =
                    content_form::project_bytes(project_forms).map_err(QueryError::Refused)?;
                let (record_keys, primary_record_key) =
                    record_keys(tx, &workspace, EntityType::Project, id.as_str())?;
                projects.push(ProjectContentStamp {
                    project_id: id.clone(),
                    signature: hmac(key, &bytes),
                    record_keys,
                    primary_record_key,
                    counts_by_state,
                });
            }
            Ok(ReviewContentStamps {
                projection_generation: unsigned(generation)?,
                tasks,
                projects,
            })
        })())
    })?
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::OpenOptions;
    use serde_json::{Value, json};
    use std::time::Duration;
    fn task(id: &str, title: &str, project: Option<&str>, state: &str) -> Value {
        json!({"id":id,"title":title,"details":null,"state":state,"project_id":project,"tag_ids":[],"due_date":null,"priority":"none","waiting_for":null,"waiting_since":null,"order_key":"1","source_capture_ids":[],"created_at":"2026-10-10T09:00:00Z","updated_at":"2026-10-10T09:00:00Z","completed_at":null,"cancelled_at":null,"revision":"1","consecutive_stalled_formulations":0,"formulation":null,"parked":null})
    }
    fn record(store: &mut Store, kind: &str, value: &Value) {
        store.write(|tx| {
            tx.execute("INSERT INTO visible_records(workspace_id,record_type,record_key,body) VALUES ('local',?1,?2,?3) ON CONFLICT(workspace_id,record_type,record_key) DO UPDATE SET body=excluded.body",params![kind,serde_json::to_string(&[value["id"].as_str().unwrap()]).unwrap(),serde_json::to_vec(value).unwrap()])?;
            Ok(())
        }).unwrap();
    }
    fn alias(store: &mut Store, kind: &str, source: &str, canonical: &str, provenance: &str) {
        store.write(|tx| {tx.execute("INSERT INTO identity_aliases(workspace_id,entity_type,old_local_id,server_id,provenance) VALUES ('local',?1,?2,?3,?4)",params![kind,source,canonical,provenance])?;Ok(())}).unwrap();
    }
    #[test]
    fn content_stamps_026_mac_literal_bytes_and_standard_hmac_key_normalization() {
        // Independently authored from RecordContentForm: present A; nil notes;
        // inbox; nil waiting/due; none priority; nil project; zero tags/children.
        let hex = "010000000141000100000005696e626f78000001000000046e6f6e65000000000000000000";
        let bytes: Vec<u8> = hex
            .as_bytes()
            .chunks_exact(2)
            .map(|pair| u8::from_str_radix(std::str::from_utf8(pair).unwrap(), 16).unwrap())
            .collect();
        let task: bb_domain::types::Task =
            serde_json::from_value(task("task-golden", "A", None, "inbox")).unwrap();
        assert_eq!(
            content_form::task_bytes(&Default::default(), &task, &Default::default()).unwrap(),
            bytes
        );
        // Python stdlib hmac/sha256 over the literal37bytes, key07 repeated32.
        assert_eq!(
            hmac(&[7; 32], &bytes),
            "b698c2c2118f493cfc81f7817dbb5ee900cd3463bdd30bcfd46b2de42dea0bf1"
        );
        assert_ne!(hmac(&[8; 32], &bytes), hmac(&[7; 32], &bytes));
        // RFC4231 case6: accepted keys over64bytes are hashed, not rotated.
        assert_eq!(
            hmac(
                &[0xaa; 131],
                b"Test Using Larger Than Block-Size Key - Hash Key First"
            ),
            "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54"
        );
        let mut names:bb_domain::types::ReadSet=serde_json::from_value(json!({"tags":{
            "tag-j":{"id":"tag-j","name":"ǰ","state":"active","revision":"1","created_at":"2026-10-10T09:00:00Z"},
            "tag-k":{"id":"tag-k","name":"k","state":"active","revision":"1","created_at":"2026-10-10T09:00:00Z"}
        }})).unwrap();
        let mut tagged = task.clone();
        tagged.tag_ids = ["tag-j", "tag-k", "tag-j"]
            .map(|id| bb_domain::types::TagId::parse(id).unwrap())
            .to_vec();
        let mut expected = bytes[..29].to_vec();
        expected.extend_from_slice(&[
            0, 0, 0, 3, 1, 0, 0, 0, 1, b'k', 1, 0, 0, 0, 3, b'j', 0xcc, 0x8c, 1, 0, 0, 0, 3, b'j',
            0xcc, 0x8c, 0, 0, 0, 0,
        ]);
        // Swift sorts k before NFC-comparableǰ but encodes folded j+caron unchanged;
        // duplicate normalized tag names remain two fields.
        assert_eq!(
            content_form::task_bytes(&names, &tagged, &Default::default()).unwrap(),
            expected
        );
        names.tags.clear();
        assert_eq!(
            content_form::task_bytes(&names, &tagged, &Default::default()).unwrap(),
            bytes
        );
        let mut project_expected = (bytes.len() as u32).to_be_bytes().to_vec();
        project_expected.extend_from_slice(&bytes);
        assert_eq!(
            content_form::project_bytes(vec![bytes.clone()]).unwrap(),
            project_expected
        );
        assert!(content_form::project_bytes(vec![]).unwrap().is_empty());
        let mut empty = task.clone();
        empty.details = Some(bb_domain::types::Details::new("").unwrap());
        assert_ne!(
            content_form::task_bytes(&Default::default(), &empty, &Default::default()).unwrap(),
            bytes
        );
    }
    #[test]
    fn content_stamps_026_mac_complete_children_terminal_projects_aliases_and_bounds() {
        let directory =
            std::env::temp_dir().join(format!("bb-content-stamps-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&directory);
        let options = OpenOptions {
            path: directory.join("store.sqlite3"),
            workspace_id: "local".to_owned(),
            busy_timeout: Duration::from_secs(2),
        };
        let mut store = Store::open(&options).unwrap();
        let project = ProjectId::parse("project-full").unwrap();
        let id = TaskId::parse("task-full-0").unwrap();
        record(
            &mut store,
            "project",
            &json!({"id":project,"name":"Project","state":"active","color":null,"revision":"1","created_at":"2026-10-10T09:00:00Z","desired_outcome":null,"archived_at":null,"archived_before_lossless":false}),
        );
        for n in 0..202 {
            record(
                &mut store,
                "task",
                &task(
                    &format!("task-full-{n}"),
                    "A",
                    Some(project.as_str()),
                    "completed",
                ),
            );
        }
        for n in 0..201 {
            record(
                &mut store,
                "subtask",
                &json!({"id":format!("subtask-{n:03}"),"task_id":id,"title":format!("Child {n}"),"state":"open","order_key":n.to_string(),"revision":"1"}),
            );
        }
        alias(
            &mut store,
            "task",
            "old-task",
            id.as_str(),
            "legacy-import:server-id",
        );
        alias(
            &mut store,
            "project",
            "old-project",
            project.as_str(),
            "legacy-import:normalized-local-id",
        );
        alias(
            &mut store,
            "subtask",
            "original-z",
            "subtask-000",
            "legacy-import:server-id",
        );
        alias(
            &mut store,
            "subtask",
            "original-a",
            "subtask-001",
            "legacy-import:server-id",
        );
        record(
            &mut store,
            "subtask",
            &json!({"id":"subtask-001","task_id":id,"title":"Child 1","state":"open","order_key":"0","revision":"1"}),
        );
        store
            .write(|tx| {
                tx.execute("UPDATE sync_meta SET projection_generation=7", [])?;
                Ok(())
            })
            .unwrap();
        let first = review_content_stamps(
            &mut store,
            &[7; 32],
            std::slice::from_ref(&id),
            std::slice::from_ref(&project),
        )
        .unwrap();
        assert_eq!(first.projection_generation, 7);
        assert_eq!(first.projects[0].counts_by_state["completed"], 202);
        assert_eq!(first.projects[0].counts_by_state["next"], 0);
        assert_eq!(
            first.tasks[0].record_keys,
            ["s:task-full-0", "c:old-task", "c:task-full-0"]
        );
        assert_eq!(first.projects[0].primary_record_key, "c:old-project");
        // A canonical ID can simultaneously be another imported record's original local ID.
        // Identical content never permits borrowing that other record's c: namespace.
        alias(
            &mut store,
            "task",
            id.as_str(),
            "task-other",
            "legacy-import:normalized-local-id",
        );
        let safe =
            review_content_stamps(&mut store, &[7; 32], std::slice::from_ref(&id), &[]).unwrap();
        assert_eq!(safe.tasks[0].record_keys, ["s:task-full-0", "c:old-task"]);
        store.write(|tx| { tx.execute("DELETE FROM identity_aliases WHERE workspace_id='local' AND entity_type='task' AND old_local_id=?1", [id.as_str()])?; Ok(()) }).unwrap();
        record(
            &mut store,
            "task",
            &task("task-no-alias", "A", None, "inbox"),
        );
        alias(
            &mut store,
            "task",
            "task-no-alias",
            "task-another",
            "legacy-import:normalized-local-id",
        );
        let no_alias = review_content_stamps(
            &mut store,
            &[7; 32],
            &[TaskId::parse("task-no-alias").unwrap()],
            &[],
        )
        .unwrap();
        assert_eq!(no_alias.tasks[0].record_keys, ["s:task-no-alias"]);
        assert_eq!(no_alias.tasks[0].primary_record_key, "s:task-no-alias");
        assert!(
            serde_json::from_value::<bb_domain::types::Query>(
                json!({"kind":"review_content_stamps"})
            )
            .is_err()
        );
        let state = store
            .read(|tx| Ok(read_projection(tx, "local")))
            .unwrap()
            .unwrap();
        let map = BTreeMap::from([
            (
                SubtaskId::parse("subtask-000").unwrap(),
                "original-z".to_owned(),
            ),
            (
                SubtaskId::parse("subtask-001").unwrap(),
                "original-a".to_owned(),
            ),
        ]);
        let expected = content_form::task_bytes(&state, &state.tasks[&id], &map).unwrap();
        assert_eq!(first.tasks[0].stamp, hmac(&[7; 32], &expected));
        assert_ne!(
            first.tasks[0].stamp,
            hmac(
                &[7; 32],
                &content_form::task_bytes(&state, &state.tasks[&id], &Default::default()).unwrap()
            )
        );
        let mut ack = task(id.as_str(), "A", Some(project.as_str()), "completed");
        ack["revision"] = json!("19");
        ack["order_key"] = json!("999");
        ack["updated_at"] = json!("2026-10-11T09:00:00Z");
        record(&mut store, "task", &ack);
        let unchanged = review_content_stamps(
            &mut store,
            &[7; 32],
            std::slice::from_ref(&id),
            std::slice::from_ref(&project),
        )
        .unwrap();
        assert_eq!(first.tasks, unchanged.tasks);
        assert_eq!(first.projects, unchanged.projects);
        record(
            &mut store,
            "subtask",
            &json!({"id":"subtask-200","task_id":id,"title":"Changed outside200 child page","state":"open","order_key":"200","revision":"2"}),
        );
        let changed = review_content_stamps(
            &mut store,
            &[7; 32],
            std::slice::from_ref(&id),
            std::slice::from_ref(&project),
        )
        .unwrap();
        assert_ne!(first.tasks[0].stamp, changed.tasks[0].stamp);
        assert_ne!(first.projects[0].signature, changed.projects[0].signature);
        assert!(review_content_stamps(&mut store, &[], &vec![id.clone(); 201], &[]).is_err());
        assert!(
            review_content_stamps(
                &mut store,
                &vec![0; MAX_REVIEW_STAMP_KEY_BYTES + 1],
                &[],
                &[]
            )
            .is_err()
        );
        alias(
            &mut store,
            "subtask",
            "second-source",
            "subtask-000",
            "legacy-import:server-id",
        );
        assert!(review_content_stamps(&mut store, &[7; 32], &[id], &[]).is_err());
        store.close().unwrap();
        std::fs::remove_dir_all(directory).unwrap();
    }
}
