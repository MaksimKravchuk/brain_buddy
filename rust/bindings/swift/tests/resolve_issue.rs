//! The sync-issue resolution and current-record ports of the workspace bridge (spec 026 M-02/D-02,
//! runtime-ffi.md `resolve_issue`): one transaction, the shown revision as precondition, a typed
//! refusal when the record changed again, and arbitration with cancellation.
use bb_client::{ExecuteContext, ExecuteRequest, IdSource, OpenOptions, Store, execute, replay};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::{
    catalog::{CommandType, EntityType},
    command::{Precondition, RevisionPrecondition},
    wire::{CommandId, Counter, Id, Instant},
};
use bb_swift::{
    BridgeDependentChoice, BridgeDependentDecision, BridgeError, BridgeExecuteContext,
    BridgeIssueChoice, BridgeOperation, BridgeReplacement, BridgeResolveRequest, BridgeRuntime,
    BridgeStoreRequest, BridgeWorkspace, BridgeWorkspaceAnswer,
};
use serde_json::{Value, json};
use std::{fs, sync::Arc, time::Duration};

const NOW: &str = "2026-10-10T09:00:00Z";

struct SeqIds(u64);

impl IdSource for SeqIds {
    fn uuid(&mut self) -> std::io::Result<String> {
        self.0 += 1;
        Ok(format!("00000000-0000-4000-8000-{:012x}", self.0))
    }
}

fn cmd(n: u64) -> CommandId {
    CommandId::parse(format!("01900000-0000-4000-8000-{n:012}")).unwrap()
}

fn code(error: BridgeError) -> String {
    let BridgeError::Failed { code, .. } = error;
    code
}

fn policy() -> Policy {
    Policy {
        weekly_review: false,
        navigator_provider: None,
        navigator_available: false,
        consent_text_version: 1,
    }
}

fn core_context() -> ExecuteContext {
    ExecuteContext {
        now: Instant::parse(NOW).unwrap(),
        time_zone: ZoneName::new("UTC").unwrap(),
        actor_id: ActorId::parse("device").unwrap(),
        policy: policy(),
    }
}

fn bridge_context() -> BridgeExecuteContext {
    BridgeExecuteContext {
        now: NOW.into(),
        time_zone: "UTC".into(),
        actor_id: "device".into(),
        policy: serde_json::to_vec(&policy()).unwrap(),
    }
}

fn request(
    n: u64,
    kind: CommandType,
    entity: Option<&str>,
    payload: Value,
    shown: Vec<Precondition>,
) -> ExecuteRequest {
    ExecuteRequest {
        command_id: cmd(n),
        command_type: kind,
        entity_id: entity.map(|id| Id::parse(id).unwrap()),
        payload: payload.as_object().unwrap().clone(),
        preconditions: shown,
        depends_on: Vec::new(),
        admission_tokens: Vec::new(),
        context: core_context(),
    }
}

fn revision(task: &str, revision: &str) -> Precondition {
    Precondition::Revision(RevisionPrecondition {
        entity_type: EntityType::Task,
        entity_id: Id::parse(task).unwrap(),
        edit_revision: Counter::parse(revision).unwrap(),
    })
}

fn hex(value: &Value) -> String {
    value
        .to_string()
        .bytes()
        .map(|b| format!("{b:02x}"))
        .collect()
}

/// A confirmed task edited offline ("Mine") and by the account meanwhile ("Theirs"): after replay
/// the offline edit is an open `REVISION_CONFLICT` issue. Returns the workspace and the task ID.
fn conflict(name: &str) -> (Arc<BridgeWorkspace>, OpenOptions, String) {
    let directory = std::env::temp_dir().join(format!("bb-resolve-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    let options = OpenOptions {
        path: directory.join("store.sqlite3"),
        workspace_id: "local".into(),
        busy_timeout: Duration::from_secs(2),
    };
    let mut store = Store::open(&options).unwrap();
    let mut ids = SeqIds(0);
    let created = request(
        1,
        CommandType::TaskCreate,
        None,
        json!({"title": "Base"}),
        vec![],
    );
    let task = execute(&mut store, &mut ids, &created)
        .unwrap()
        .entity_id
        .as_str()
        .to_owned();
    store
        .write(|tx| {
            tx.execute(
                "INSERT OR REPLACE INTO confirmed_records (workspace_id, record_type, record_key,
                    record_version, edit_revision, tombstone, body)
                 SELECT workspace_id, record_type, record_key, '1', edit_revision, 0, body
                 FROM visible_records",
                [],
            )?;
            tx.execute("UPDATE visible_records SET source_command_id = NULL", [])?;
            tx.execute("UPDATE outbox SET state = 'completed'", [])?;
            Ok(())
        })
        .unwrap();
    let edit = request(
        2,
        CommandType::TaskUpdate,
        Some(&task),
        json!({"title": "Mine"}),
        vec![revision(&task, "1")],
    );
    execute(&mut store, &mut ids, &edit).unwrap();
    server_edit(&mut store, &task, "Theirs");
    replay(&mut store, &core_context()).unwrap();
    store.close().unwrap();
    let workspace = BridgeRuntime::new(1)
        .unwrap()
        .open_store(BridgeStoreRequest {
            workspace_id: "local".into(),
            database_path: options.path.to_string_lossy().into_owned(),
            busy_timeout_ms: 2_000,
        })
        .unwrap();
    (workspace, options, task)
}

fn server_edit(store: &mut Store, task: &str, title: &str) {
    let key = json!([task]).to_string();
    let body: Vec<u8> = store
        .read(|tx| {
            tx.query_row(
                "SELECT body FROM confirmed_records WHERE record_key = ?1",
                [&key],
                |row| row.get(0),
            )
        })
        .unwrap();
    let mut value: Value = serde_json::from_slice(&body).unwrap();
    let next = value["revision"].as_str().unwrap().parse::<u64>().unwrap() + 1;
    value["revision"] = json!(next.to_string());
    value["title"] = json!(title);
    store
        .write(|tx| {
            tx.execute(
                &format!(
                    "UPDATE confirmed_records SET body = X'{}', edit_revision = '{next}', record_version = '{next}'
                     WHERE record_key = '{key}'",
                    hex(&value)
                ),
                [],
            )?;
            Ok(())
        })
        .unwrap();
}

fn resolution(task: &str, shown: &str, new: u64) -> BridgeResolveRequest {
    BridgeResolveRequest {
        issue_id: format!("issue_{}", cmd(2).as_str()),
        choice: BridgeIssueChoice::KeepMine {
            replacement: BridgeReplacement {
                command_id: cmd(new).as_str().to_owned(),
                preconditions:
                    json!([{"entity_type":"task","entity_id":task,"edit_revision":shown}])
                        .to_string()
                        .into_bytes(),
                depends_on: vec![],
            },
        },
        dependents: vec![],
        context: bridge_context(),
    }
}

fn queued(options: &OpenOptions) -> Vec<String> {
    let mut store = Store::open(options).unwrap();
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT command_id FROM outbox WHERE state = 'queued' ORDER BY local_seq",
            )?;
            let rows = statement.query_map([], |row| row.get(0))?;
            rows.collect()
        })
        .unwrap()
}

#[test]
fn resolve_026_fr_007_the_current_record_is_read_from_the_confirmed_base() {
    let (workspace, _, task) = conflict("current");
    let issue = format!("issue_{}", cmd(2).as_str());
    let current = workspace.issue_current(issue).unwrap().unwrap();
    assert_eq!(current.entity_type, "task");
    assert!(!current.deleted);
    assert_eq!(current.edit_revision.as_deref(), Some("2"));
    let record: Value = serde_json::from_slice(&current.record.unwrap()).unwrap();
    assert_eq!(record["title"], "Theirs");
    assert_eq!(record["id"], task);
    assert!(
        workspace
            .issue_current("issue_missing".into())
            .unwrap()
            .is_none()
    );
}

#[test]
fn resolve_026_fr_007_keep_mine_queues_a_new_command_once_and_repeats_idempotently() {
    let (workspace, options, task) = conflict("keep");
    let BridgeWorkspaceAnswer::Answered { page } = workspace.workspace_issues(10, None).unwrap()
    else {
        panic!("issues must answer");
    };
    assert!(
        String::from_utf8(page.result)
            .unwrap()
            .contains("REVISION_CONFLICT")
    );

    let resolved = workspace
        .resolve_issue(resolution(&task, "2", 9), Arc::new(BridgeOperation::new()))
        .unwrap();
    assert_eq!(resolved.replaced.len(), 1);
    assert_eq!(resolved.replaced[0].old_command_id, cmd(2).as_str());
    assert_eq!(resolved.replaced[0].new_command_id, cmd(9).as_str());
    assert!(!resolved.repeated);
    assert_eq!(queued(&options), [cmd(9).as_str()]);
    // The issue is closed: it no longer lists, and the same decision answers as a repeat.
    let BridgeWorkspaceAnswer::Answered { page } = workspace.workspace_issues(10, None).unwrap()
    else {
        panic!("issues must answer");
    };
    assert_eq!(
        serde_json::from_slice::<Value>(&page.result).unwrap()["value"],
        json!([])
    );
    let again = workspace
        .resolve_issue(resolution(&task, "2", 9), Arc::new(BridgeOperation::new()))
        .unwrap();
    assert!(again.repeated);
    assert_eq!(queued(&options), [cmd(9).as_str()]);
}

#[test]
fn resolve_026_fr_007_a_record_that_changed_again_saves_nothing() {
    let (workspace, options, task) = conflict("again");
    let mut neighbor = Store::open(&options).unwrap();
    server_edit(&mut neighbor, &task, "Theirs again");
    // The feed applier refreshes the projection; here the replay does.
    replay(&mut neighbor, &core_context()).unwrap();
    let refused = workspace
        .resolve_issue(resolution(&task, "2", 9), Arc::new(BridgeOperation::new()))
        .unwrap_err();
    assert_eq!(code(refused), "REVISION_CONFLICT");
    assert!(queued(&options).is_empty());
    let BridgeWorkspaceAnswer::Answered { page } = workspace.workspace_issues(10, None).unwrap()
    else {
        panic!("issues must answer");
    };
    assert!(
        String::from_utf8(page.result)
            .unwrap()
            .contains(cmd(2).as_str()),
        "the issue stays open"
    );
    // Quoting the revision the person now sees works.
    workspace
        .resolve_issue(resolution(&task, "3", 10), Arc::new(BridgeOperation::new()))
        .unwrap();
    assert_eq!(queued(&options), [cmd(10).as_str()]);
}

#[test]
fn resolve_026_fr_007_use_current_dismisses_and_a_missing_dependent_choice_is_refused() {
    let (workspace, options, task) = conflict("use");
    let issue = format!("issue_{}", cmd(2).as_str());
    let request = |dependents: Vec<BridgeDependentDecision>| BridgeResolveRequest {
        issue_id: issue.clone(),
        choice: BridgeIssueChoice::UseCurrent,
        dependents,
        context: bridge_context(),
    };
    // A dependent that is not held behind the issue is refused, and nothing changes.
    let unknown = request(vec![BridgeDependentDecision {
        command_id: cmd(77).as_str().to_owned(),
        choice: BridgeDependentChoice::KeepForLater,
    }]);
    assert_eq!(
        code(
            workspace
                .resolve_issue(unknown, Arc::new(BridgeOperation::new()))
                .unwrap_err()
        ),
        "UNKNOWN_DEPENDENT"
    );
    let resolved = workspace
        .resolve_issue(request(vec![]), Arc::new(BridgeOperation::new()))
        .unwrap();
    assert!(resolved.replaced.is_empty() && !resolved.repeated);
    assert!(queued(&options).is_empty());
    let _ = task;
}

#[test]
fn resolve_026_fr_007_a_cancelled_or_reused_operation_never_commits() {
    let (workspace, options, task) = conflict("cancel");
    let cancelled = Arc::new(BridgeOperation::new());
    assert!(cancelled.cancel());
    assert_eq!(
        code(
            workspace
                .resolve_issue(resolution(&task, "2", 9), cancelled)
                .unwrap_err()
        ),
        "CANCELLED"
    );
    assert!(queued(&options).is_empty());
    let used = Arc::new(BridgeOperation::new());
    workspace
        .resolve_issue(resolution(&task, "2", 9), used.clone())
        .unwrap();
    assert!(used.is_committed());
    assert_eq!(
        code(
            workspace
                .resolve_issue(resolution(&task, "2", 9), used)
                .unwrap_err()
        ),
        "OPERATION_ALREADY_USED"
    );
    workspace.close().unwrap();
    assert_eq!(
        code(
            workspace
                .resolve_issue(resolution(&task, "2", 9), Arc::new(BridgeOperation::new()))
                .unwrap_err()
        ),
        "WORKSPACE_CLOSED"
    );
}
