//! Replay and sync-issue tests: a rejected intent is preserved and shown, work
//! that does not depend on it keeps progressing, work that does is held and
//! never dropped, and nothing deleted is resurrected or rekeyed blindly.
//!
//! The confirmed base is written directly here (the feed application that
//! normally writes it is a later slice); everything else goes through the
//! public API, across real store reopenings and one real process abort.

use bb_client::{
    Choice, DecisionDraft, DependentChoice, DependentDraft, DraftAction, ExecuteContext,
    ExecuteError, ExecuteRequest, IdSource, IssueError, IssueReason, IssueState, OpenOptions,
    Replacement, ReplayError, ResolveRequest, Store, StoreError, execute, issue, load_draft,
    open_issues, record_rejection, replay, resolve_issue, save_draft,
};
use bb_domain::types::{ActorId, Policy, ProviderName, ZoneName};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{
    AfterCommandPrecondition, CommandRef, Precondition, RevisionPrecondition,
};
use bb_protocol::wire::{CommandId, Counter, Id, Instant};
use rusqlite::params;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::Duration;

const WORKSPACE: &str = "workspace-local";
const ROLE: &str = "BB_REPLAY_CHILD";
const NOW: &str = "2026-10-10T09:00:00Z";

// ----------------------------------------------------------------------- harness

fn scratch(name: &str) -> PathBuf {
    let directory = std::env::temp_dir().join(format!("bb-replay-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    directory.join("store").join("workspace.sqlite3")
}

fn open(path: &Path) -> Result<Store, StoreError> {
    Store::open(&OpenOptions {
        path: path.to_path_buf(),
        workspace_id: WORKSPACE.to_string(),
        busy_timeout: Duration::from_millis(5_000),
    })
}

/// Counts up from 1, so the IDs a run allocates are predictable.
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

fn id(n: u64) -> String {
    cmd(n).as_str().to_string()
}

fn context() -> ExecuteContext {
    ExecuteContext {
        now: Instant::parse(NOW).unwrap(),
        time_zone: ZoneName::new("UTC").unwrap(),
        actor_id: ActorId::parse("actor-local").unwrap(),
        policy: Policy {
            weekly_review: false,
            navigator_provider: None,
            navigator_available: false,
            consent_text_version: 1,
        },
    }
}

fn request(
    command_id: CommandId,
    command_type: CommandType,
    entity_id: Option<&str>,
    payload: Value,
    preconditions: Vec<Precondition>,
) -> ExecuteRequest {
    ExecuteRequest {
        command_id,
        command_type,
        entity_id: entity_id.map(|id| Id::parse(id).unwrap()),
        payload: payload.as_object().unwrap().clone(),
        preconditions,
        depends_on: Vec::new(),
        context: context(),
    }
}

fn shown(entity_type: EntityType, id: &str, revision: &str) -> Precondition {
    Precondition::Revision(RevisionPrecondition {
        entity_type,
        entity_id: Id::parse(id).unwrap(),
        edit_revision: Counter::parse(revision).unwrap(),
    })
}

fn after(command: &CommandId, entity_type: EntityType, id: &str) -> Precondition {
    Precondition::AfterCommand(AfterCommandPrecondition {
        after_command: CommandRef {
            command_id: command.clone(),
            entity_type,
            entity_id: Id::parse(id).unwrap(),
        },
    })
}

fn run(store: &mut Store, ids: &mut SeqIds, request: &ExecuteRequest) -> String {
    execute(store, ids, request)
        .unwrap()
        .entity_id
        .as_str()
        .to_string()
}

fn create_task(store: &mut Store, ids: &mut SeqIds, n: u64, title: &str) -> String {
    let created = request(
        cmd(n),
        CommandType::TaskCreate,
        None,
        json!({ "title": title }),
        Vec::new(),
    );
    run(store, ids, &created)
}

fn edit(
    store: &mut Store,
    ids: &mut SeqIds,
    n: u64,
    task_id: &str,
    payload: Value,
    precondition: Precondition,
) {
    let update = request(
        cmd(n),
        CommandType::TaskUpdate,
        Some(task_id),
        payload,
        vec![precondition],
    );
    execute(store, ids, &update).unwrap();
}

/// The server accepted and fed everything queued: the visible rows become the
/// confirmed base and every command completes.
fn confirm_all(store: &mut Store) {
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
}

/// Another device changed a confirmed record: its revision moves on.
fn server_edit(store: &mut Store, id: &str, change: impl FnOnce(&mut Value)) {
    server_edit_at(store, json!([id]).to_string(), change);
}

fn server_edit_at(store: &mut Store, key: String, change: impl FnOnce(&mut Value)) {
    store
        .write(|tx| {
            let (body, revision): (Vec<u8>, String) = tx.query_row(
                "SELECT body, edit_revision FROM confirmed_records WHERE record_key = ?1",
                [&key],
                |row| Ok((row.get(0)?, row.get(1)?)),
            )?;
            let mut value: Value = serde_json::from_slice(&body).unwrap();
            let next = (revision.parse::<u64>().unwrap() + 1).to_string();
            value["revision"] = json!(next);
            change(&mut value);
            tx.execute(
                "UPDATE confirmed_records SET body = ?2, edit_revision = ?3, record_version = ?3
                 WHERE record_key = ?1",
                params![key, value.to_string().into_bytes(), next],
            )?;
            Ok(())
        })
        .unwrap();
}

/// Another device deleted a confirmed record.
fn server_delete(store: &mut Store, id: &str) {
    store
        .write(|tx| {
            tx.execute(
                "UPDATE confirmed_records SET tombstone = 1, body = NULL WHERE record_key = ?1",
                [json!([id]).to_string()],
            )?;
            Ok(())
        })
        .unwrap();
}

fn states(store: &mut Store) -> BTreeMap<String, String> {
    store
        .read(|tx| {
            let mut statement = tx.prepare("SELECT command_id, state FROM outbox")?;
            let rows = statement.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
            rows.collect()
        })
        .unwrap()
}

fn state(store: &mut Store, n: u64) -> String {
    states(store)[cmd(n).as_str()].clone()
}

fn set_state(store: &mut Store, n: u64, state: &str, ever_sent: bool) {
    store
        .write(|tx| {
            tx.execute(
                "UPDATE outbox SET state = ?2, ever_sent = ?3 WHERE command_id = ?1",
                params![cmd(n).as_str(), state, i64::from(ever_sent)],
            )?;
            Ok(())
        })
        .unwrap();
}

fn queued(store: &mut Store) -> Vec<String> {
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

fn envelope(store: &mut Store, n: u64) -> Value {
    store
        .read(|tx| {
            tx.query_row(
                "SELECT envelope FROM outbox WHERE command_id = ?1",
                [cmd(n).as_str()],
                |row| row.get::<_, Vec<u8>>(0),
            )
        })
        .map(|bytes| serde_json::from_slice(&bytes).unwrap())
        .unwrap()
}

fn superseded_by(store: &mut Store, n: u64) -> Option<String> {
    store
        .read(|tx| {
            tx.query_row(
                "SELECT superseded_by FROM outbox WHERE command_id = ?1",
                [cmd(n).as_str()],
                |row| row.get(0),
            )
        })
        .unwrap()
}

fn visible(store: &mut Store, record_type: &str) -> Vec<Value> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT body FROM visible_records WHERE record_type = ?1 ORDER BY record_key",
            )?;
            let rows = statement.query_map([record_type], |row| row.get::<_, Vec<u8>>(0))?;
            Ok(rows
                .map(|body| serde_json::from_slice(&body.unwrap()).unwrap())
                .collect())
        })
        .unwrap()
}

fn task(store: &mut Store, id: &str) -> Option<Value> {
    visible(store, "task")
        .into_iter()
        .find(|task| task["id"] == id)
}

fn generation(store: &mut Store) -> i64 {
    store
        .read(|tx| {
            tx.query_row("SELECT projection_generation FROM sync_meta", [], |row| {
                row.get(0)
            })
        })
        .unwrap()
}

fn issue_id(n: u64) -> String {
    format!("issue_{}", id(n))
}

fn keep_mine(n: u64, shown: Vec<Precondition>) -> Choice {
    Choice::KeepMine(Replacement {
        command_id: cmd(n),
        shown,
        depends_on: Vec::new(),
    })
}

fn resolution(n: u64, choice: Choice, dependents: Vec<(u64, DependentChoice)>) -> ResolveRequest {
    ResolveRequest {
        issue_id: issue_id(n),
        choice,
        dependents: dependents
            .into_iter()
            .map(|(id, choice)| (cmd(id), choice))
            .collect(),
        context: context(),
    }
}

/// Task `T` confirmed at revision 1 (title "Base"); returns its ID.
fn confirmed_task(store: &mut Store, ids: &mut SeqIds) -> String {
    let id = create_task(store, ids, 1, "Base");
    confirm_all(store);
    id
}

/// `T` edited offline by command 2 ("Mine").
fn offline_edit(store: &mut Store, ids: &mut SeqIds, task_id: &str) {
    edit(
        store,
        ids,
        2,
        task_id,
        json!({ "title": "Mine" }),
        shown(EntityType::Task, task_id, "1"),
    );
}

fn revision(store: &mut Store, task_id: &str) -> String {
    task(store, task_id).unwrap()["revision"]
        .as_str()
        .unwrap()
        .to_string()
}

// ------------------------------------------------------------------ child processes

fn spawn(role: &str, path: &Path) -> Child {
    Command::new(std::env::current_exe().unwrap())
        .args([
            "replay_child_entry",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ])
        .env(ROLE, role)
        .env("BB_REPLAY_PATH", path)
        .stdout(Stdio::piped())
        .spawn()
        .unwrap()
}

fn wait_for(child: &mut Child, marker: &str) {
    let stdout = child.stdout.take().unwrap();
    let found = BufReader::new(stdout)
        .lines()
        .map_while(Result::ok)
        .any(|line| line.ends_with(marker));
    assert!(found, "child exited before printing {marker}");
}

#[test]
fn replay_child_entry() {
    let Ok(role) = std::env::var(ROLE) else {
        return;
    };
    let path = PathBuf::from(std::env::var("BB_REPLAY_PATH").unwrap());
    match role.as_str() {
        "reject_then_abort" => {
            let mut store = open(&path).unwrap();
            record_rejection(
                &mut store,
                &context(),
                &cmd(2),
                &IssueReason::RevisionConflict,
            )
            .unwrap();
            println!("rejected");
            std::io::stdout().flush().unwrap();
            std::process::abort();
        }
        other => panic!("unknown child role {other}"),
    }
}

// ------------------------------------------------------------------------- tests

#[test]
fn replay_026_fr_007_concurrent_edit_is_kept_as_an_issue_with_text_and_current_record() {
    let path = scratch("conflict");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let task_id = confirmed_task(&mut store, &mut ids);
    offline_edit(&mut store, &mut ids, &task_id);
    let independent = create_task(&mut store, &mut ids, 3, "Independent");
    let intent = envelope(&mut store, 2);
    assert_eq!(task(&mut store, &task_id).unwrap()["title"], "Mine");

    // Another device renames the same task first.
    server_edit(&mut store, &task_id, |task| task["title"] = json!("Theirs"));
    let replayed = replay(&mut store, &context()).unwrap();

    assert_eq!(replayed.rejected, [cmd(2)]);
    assert_eq!(replayed.applied, [cmd(3)]);
    assert!(replayed.blocked.is_empty() && replayed.deferred.is_empty());
    assert_eq!(state(&mut store, 2), "rejected");
    assert_eq!(state(&mut store, 3), "queued");
    // The intent is untouched and visible state follows the account.
    assert_eq!(envelope(&mut store, 2), intent);
    assert_eq!(task(&mut store, &task_id).unwrap()["title"], "Theirs");
    assert!(task(&mut store, &independent).is_some());

    let issues = open_issues(&mut store).unwrap();
    assert_eq!(issues.len(), 1);
    let shown_issue = &issues[0];
    assert_eq!(shown_issue.issue.reason, IssueReason::RevisionConflict);
    assert_eq!(shown_issue.issue.command_id, cmd(2));
    assert_eq!(
        shown_issue.issue.local_text,
        Some(json!({ "title": "Mine" }))
    );
    assert_eq!(shown_issue.issue.shown_base_revision.as_deref(), Some("1"));
    let current = shown_issue.current.as_ref().unwrap();
    assert_eq!(current.edit_revision.as_deref(), Some("2"));
    assert_eq!(current.record.as_ref().unwrap()["title"], "Theirs");

    // Replaying again changes nothing: no second issue, no churn.
    let before = generation(&mut store);
    replay(&mut store, &context()).unwrap();
    assert_eq!(
        (
            open_issues(&mut store).unwrap().len(),
            generation(&mut store)
        ),
        (1, before)
    );

    // The issue and the intent survive a restart.
    store.close().unwrap();
    let mut store = open(&path).unwrap();
    let again = open_issues(&mut store).unwrap();
    assert_eq!(again, issues);
    assert_eq!(envelope(&mut store, 2), intent);
}

#[test]
fn replay_026_fr_008_deleted_record_is_not_resurrected_by_a_late_edit_or_create() {
    let path = scratch("deleted");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let tag = request(
        cmd(1),
        CommandType::TagCreate,
        None,
        json!({ "name": "Errands" }),
        Vec::new(),
    );
    let tag_id = run(&mut store, &mut ids, &tag);
    confirm_all(&mut store);
    let rename = request(
        cmd(2),
        CommandType::TagUpdate,
        Some(&tag_id),
        json!({ "name": "Chores" }),
        vec![shown(EntityType::Tag, &tag_id, "1")],
    );
    execute(&mut store, &mut ids, &rename).unwrap();

    // The tag is deleted on another device before the edit is sent.
    server_delete(&mut store, &tag_id);
    let replayed = replay(&mut store, &context()).unwrap();
    assert_eq!(replayed.rejected, [cmd(2)]);
    assert!(visible(&mut store, "tag").is_empty(), "the tag came back");

    let view = issue(&mut store, &issue_id(2)).unwrap().unwrap();
    assert_eq!(view.issue.reason, IssueReason::EntityDeleted);
    assert_eq!(view.issue.local_text, Some(json!({ "name": "Chores" })));
    assert!(view.current.as_ref().unwrap().deleted);
    assert!(view.current.unwrap().record.is_none());

    // Neither a new edit nor a replacement edit can recreate it.
    let late = request(
        cmd(3),
        CommandType::TagUpdate,
        Some(&tag_id),
        json!({ "name": "Again" }),
        vec![shown(EntityType::Tag, &tag_id, "1")],
    );
    assert!(matches!(
        execute(&mut store, &mut ids, &late),
        Err(ExecuteError::Refused(_))
    ));
    let keep = resolution(
        2,
        keep_mine(4, vec![shown(EntityType::Tag, &tag_id, "1")]),
        vec![],
    );
    assert_eq!(
        resolve_issue(&mut store, &mut ids, &keep).unwrap_err(),
        IssueError::EntityDeleted
    );
    assert!(visible(&mut store, "tag").is_empty());
    assert_eq!(open_issues(&mut store).unwrap().len(), 1);

    // A late create that reuses the deleted ID is judged on replay, not applied.
    let mut recreate = request(
        cmd(5),
        CommandType::TagCreate,
        Some(&tag_id),
        json!({ "name": "Errands" }),
        Vec::new(),
    );
    recreate.context = context();
    execute(&mut store, &mut ids, &recreate).unwrap();
    let replayed = replay(&mut store, &context()).unwrap();
    assert_eq!(replayed.rejected, [cmd(5)]);
    assert!(visible(&mut store, "tag").is_empty());

    // "Keep item deleted" is an explicit choice that keeps the saved edit.
    let dismissed = resolve_issue(
        &mut store,
        &mut ids,
        &resolution(2, Choice::UseCurrent, vec![]),
    )
    .unwrap();
    assert!(dismissed.replaced.is_empty());
    store.close().unwrap();
    let mut store = open(&path).unwrap();
    let view = issue(&mut store, &issue_id(2)).unwrap().unwrap();
    assert_eq!(view.issue.state, IssueState::Dismissed);
    assert_eq!(view.issue.local_text, Some(json!({ "name": "Chores" })));
    assert_eq!(state(&mut store, 2), "rejected");
    assert!(visible(&mut store, "tag").is_empty());
}

#[test]
fn replay_026_fr_007_rejection_holds_its_chain_and_independent_work_keeps_progressing() {
    let path = scratch("chain");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let task_id = confirmed_task(&mut store, &mut ids);
    offline_edit(&mut store, &mut ids, &task_id);
    let r2 = revision(&mut store, &task_id);
    edit(
        &mut store,
        &mut ids,
        3,
        &task_id,
        json!({ "details": "Later note" }),
        shown(EntityType::Task, &task_id, &r2),
    );
    let other = create_task(&mut store, &mut ids, 4, "Independent");
    let r_other = revision(&mut store, &other);
    edit(
        &mut store,
        &mut ids,
        5,
        &other,
        json!({ "title": "Independent, edited" }),
        shown(EntityType::Task, &other, &r_other),
    );
    let intent_3 = envelope(&mut store, 3);

    // The server's terminal receipt for command 2 is a revision conflict.
    let report = record_rejection(
        &mut store,
        &context(),
        &cmd(2),
        &IssueReason::RevisionConflict,
    )
    .unwrap();
    assert_eq!(report.blocked, [cmd(3)]);
    assert_eq!(report.applied, [cmd(4), cmd(5)]);
    assert_eq!(state(&mut store, 2), "rejected");
    assert_eq!(state(&mut store, 3), "blocked_dependency");
    // Held, not dropped: the envelope is intact.
    assert_eq!(envelope(&mut store, 3), intent_3);

    // Only the chain is held. The unrelated commands are still the runnable queue.
    assert_eq!(queued(&mut store), [id(4), id(5)]);
    let projected = task(&mut store, &task_id).unwrap();
    assert_eq!(projected["title"], "Base");
    assert_eq!(projected["details"], Value::Null);
    assert_eq!(
        task(&mut store, &other).unwrap()["title"],
        "Independent, edited"
    );
    let later = create_task(&mut store, &mut ids, 6, "Created afterwards");
    assert!(task(&mut store, &later).is_some());

    let issues = open_issues(&mut store).unwrap();
    assert_eq!(issues.len(), 2);
    assert_eq!(issues[0].issue.command_id, cmd(2));
    assert_eq!(issues[0].issue.dependent_ids, [cmd(3)]);
    assert_eq!(issues[1].issue.reason, IssueReason::BlockedDependency);
    assert_eq!(
        issues[1].issue.local_text,
        Some(json!({ "details": "Later note" }))
    );

    // The independent work is sent and confirmed; the held command stays held.
    for n in [4, 5, 6] {
        set_state(&mut store, n, "completed", true);
    }
    let report = replay(&mut store, &context()).unwrap();
    assert!(report.blocked.is_empty() && report.rejected.is_empty());
    assert_eq!(state(&mut store, 3), "blocked_dependency");
    assert_eq!(open_issues(&mut store).unwrap().len(), 2);

    // Repeating the receipt changes nothing; an accepted command cannot be rejected.
    record_rejection(
        &mut store,
        &context(),
        &cmd(2),
        &IssueReason::RevisionConflict,
    )
    .unwrap();
    assert_eq!(open_issues(&mut store).unwrap().len(), 2);
    assert_eq!(
        record_rejection(
            &mut store,
            &context(),
            &cmd(4),
            &IssueReason::RevisionConflict
        )
        .unwrap_err(),
        ReplayError::NotRejectable {
            state: "completed".to_string()
        }
    );

    store.close().unwrap();
    let mut store = open(&path).unwrap();
    assert_eq!(state(&mut store, 3), "blocked_dependency");
    assert_eq!(open_issues(&mut store).unwrap(), issues);
}

#[test]
fn replay_026_fr_010_possibly_sent_commands_are_never_judged_or_rekeyed() {
    let path = scratch("unknown");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let task_id = confirmed_task(&mut store, &mut ids);
    offline_edit(&mut store, &mut ids, &task_id);
    let r2 = revision(&mut store, &task_id);
    edit(
        &mut store,
        &mut ids,
        3,
        &task_id,
        json!({ "details": "After" }),
        shown(EntityType::Task, &task_id, &r2),
    );
    // The response to command 2 was lost: it may have been accepted.
    set_state(&mut store, 2, "unknown", true);
    let intent = envelope(&mut store, 2);
    server_edit(&mut store, &task_id, |task| task["title"] = json!("Theirs"));

    let report = replay(&mut store, &context()).unwrap();
    assert!(report.rejected.is_empty() && report.blocked.is_empty());
    assert_eq!(report.deferred, [cmd(2), cmd(3)]);
    assert_eq!(state(&mut store, 2), "unknown");
    assert_eq!(state(&mut store, 3), "queued");
    assert!(open_issues(&mut store).unwrap().is_empty());
    assert_eq!(envelope(&mut store, 2), intent);
    assert_eq!(task(&mut store, &task_id).unwrap()["title"], "Theirs");

    // An accepted command cannot be turned into a conflict by a late feed.
    set_state(&mut store, 2, "accepted_awaiting_feed", true);
    assert_eq!(
        record_rejection(
            &mut store,
            &context(),
            &cmd(2),
            &IssueReason::RevisionConflict
        )
        .unwrap_err(),
        ReplayError::NotRejectable {
            state: "accepted_awaiting_feed".to_string()
        }
    );
    assert_eq!(state(&mut store, 2), "accepted_awaiting_feed");

    // Only the server's rejection makes it resolvable, and never by omission.
    set_state(&mut store, 2, "unknown", true);
    record_rejection(
        &mut store,
        &context(),
        &cmd(2),
        &IssueReason::RevisionConflict,
    )
    .unwrap();
    assert_eq!(state(&mut store, 2), "rejected");
    set_state(&mut store, 2, "unknown", true);
    let keep = resolution(
        2,
        keep_mine(9, vec![shown(EntityType::Task, &task_id, "2")]),
        vec![(3, DependentChoice::KeepForLater)],
    );
    assert_eq!(
        resolve_issue(&mut store, &mut ids, &keep).unwrap_err(),
        IssueError::NotResolvable
    );
    assert_eq!(state(&mut store, 3), "blocked_dependency");
    assert!(!states(&mut store).contains_key(cmd(9).as_str()));
}

#[test]
fn replay_026_fr_007_keep_my_version_queues_a_new_command_against_the_shown_version() {
    let path = scratch("keep-mine");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let task_id = confirmed_task(&mut store, &mut ids);
    offline_edit(&mut store, &mut ids, &task_id);
    server_edit(&mut store, &task_id, |task| task["title"] = json!("Theirs"));
    replay(&mut store, &context()).unwrap();
    let old = envelope(&mut store, 2);

    // A version other than the one now shown is refused: nothing is forced.
    let stale = resolution(
        2,
        keep_mine(20, vec![shown(EntityType::Task, &task_id, "1")]),
        vec![],
    );
    assert_eq!(
        resolve_issue(&mut store, &mut ids, &stale).unwrap_err(),
        IssueError::ChangedAgain
    );
    assert_eq!(open_issues(&mut store).unwrap().len(), 1);
    assert_eq!(state(&mut store, 2), "rejected");
    assert_eq!(superseded_by(&mut store, 2), None);
    assert!(!states(&mut store).contains_key(cmd(20).as_str()));

    let keep = resolution(
        2,
        keep_mine(20, vec![shown(EntityType::Task, &task_id, "2")]),
        vec![],
    );
    let resolved = resolve_issue(&mut store, &mut ids, &keep).unwrap();
    assert_eq!(resolved.replaced, [(cmd(2), cmd(20))]);
    let new = envelope(&mut store, 20);
    assert_eq!(new["supersedes_command_id"], cmd(2).as_str());
    assert_eq!(new["payload"], old["payload"]);
    assert_eq!(new["entity_id"], old["entity_id"]);
    assert_eq!(
        new["preconditions"],
        json!([{ "entity_type": "task", "entity_id": task_id, "edit_revision": "2" }])
    );
    assert_ne!(new["command_id"], old["command_id"]);
    assert_eq!(superseded_by(&mut store, 2), Some(id(20)));
    assert_eq!(envelope(&mut store, 2), old);
    assert_eq!(state(&mut store, 20), "queued");
    assert_eq!(task(&mut store, &task_id).unwrap()["title"], "Mine");
    assert!(open_issues(&mut store).unwrap().is_empty());

    // A retry of the same resolution answers from what was stored.
    let again = resolve_issue(&mut store, &mut ids, &keep).unwrap();
    assert!(again.repeated);
    assert_eq!(states(&mut store).len(), 3);

    // If the record changes again before it is sent, it needs new approval.
    server_edit(&mut store, &task_id, |task| task["title"] = json!("Third"));
    let replayed = replay(&mut store, &context()).unwrap();
    assert_eq!(replayed.rejected, [cmd(20)]);
    assert_eq!(task(&mut store, &task_id).unwrap()["title"], "Third");
    assert_eq!(open_issues(&mut store).unwrap().len(), 1);
}

#[test]
fn replay_026_fr_007_held_actions_get_explicit_atomic_choices_that_survive_restart() {
    let path = scratch("choices");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let task_id = confirmed_task(&mut store, &mut ids);
    offline_edit(&mut store, &mut ids, &task_id);
    let r2 = revision(&mut store, &task_id);
    edit(
        &mut store,
        &mut ids,
        3,
        &task_id,
        json!({ "details": "Second" }),
        shown(EntityType::Task, &task_id, &r2),
    );
    let r3 = revision(&mut store, &task_id);
    edit(
        &mut store,
        &mut ids,
        4,
        &task_id,
        json!({ "title": "Final" }),
        shown(EntityType::Task, &task_id, &r3),
    );
    server_edit(&mut store, &task_id, |task| task["title"] = json!("Theirs"));
    let report = replay(&mut store, &context()).unwrap();
    assert_eq!((report.rejected.len(), report.blocked.len()), (1, 2));
    assert_eq!(
        open_issues(&mut store).unwrap()[0].issue.dependent_ids,
        [cmd(3), cmd(4)]
    );

    let retry = Replacement {
        command_id: cmd(21),
        shown: vec![after(&cmd(20), EntityType::Task, &task_id)],
        depends_on: vec![cmd(20)],
    };
    let root = || keep_mine(20, vec![shown(EntityType::Task, &task_id, "2")]);
    let before = states(&mut store);

    // Nothing is decided by omission, by an unknown name, or by an unconfirmed discard.
    let missing = resolution(2, root(), vec![(3, DependentChoice::Retry(retry.clone()))]);
    assert_eq!(
        resolve_issue(&mut store, &mut ids, &missing).unwrap_err(),
        IssueError::DependentChoiceRequired(cmd(4))
    );
    let unknown = resolution(2, root(), vec![(99, DependentChoice::KeepForLater)]);
    assert_eq!(
        resolve_issue(&mut store, &mut ids, &unknown).unwrap_err(),
        IssueError::UnknownDependent(cmd(99))
    );
    let unconfirmed = resolution(
        2,
        root(),
        vec![
            (3, DependentChoice::Retry(retry.clone())),
            (4, DependentChoice::Discard { confirmed: false }),
        ],
    );
    assert_eq!(
        resolve_issue(&mut store, &mut ids, &unconfirmed).unwrap_err(),
        IssueError::DiscardNotConfirmed(cmd(4))
    );
    // Each refusal rolled everything back, including the replacement of the root.
    assert_eq!(states(&mut store), before);
    assert_eq!(open_issues(&mut store).unwrap().len(), 3);

    let decided = resolution(
        2,
        root(),
        vec![
            (3, DependentChoice::Retry(retry)),
            (4, DependentChoice::Discard { confirmed: true }),
        ],
    );
    let resolved = resolve_issue(&mut store, &mut ids, &decided).unwrap();
    assert_eq!(resolved.replaced, [(cmd(2), cmd(20)), (cmd(3), cmd(21))]);
    assert_eq!(resolved.discarded, [cmd(4)]);

    store.close().unwrap();
    let mut store = open(&path).unwrap();
    assert!(open_issues(&mut store).unwrap().is_empty());
    assert_eq!(state(&mut store, 4), "rejected");
    assert_eq!(superseded_by(&mut store, 4), None);
    assert_eq!(
        envelope(&mut store, 4)["payload"],
        json!({ "title": "Final" })
    );
    assert_eq!(
        issue(&mut store, &issue_id(4))
            .unwrap()
            .unwrap()
            .issue
            .state,
        IssueState::Dismissed
    );
    // The approved chain: 21 builds on 20, and both are queued to be sent.
    assert_eq!(
        envelope(&mut store, 21)["depends_on"],
        json!([cmd(20).as_str()])
    );
    assert_eq!(queued(&mut store), [id(20), id(21)]);
    let projected = task(&mut store, &task_id).unwrap();
    assert_eq!(
        (projected["title"].as_str(), projected["details"].as_str()),
        (Some("Mine"), Some("Second"))
    );
    // The same resolution again is answered from what was stored; a different
    // one is refused.
    assert!(
        resolve_issue(&mut store, &mut ids, &decided)
            .unwrap()
            .repeated
    );
    let other = resolution(2, Choice::UseCurrent, vec![]);
    assert_eq!(
        resolve_issue(&mut store, &mut ids, &other).unwrap_err(),
        IssueError::AlreadyResolved
    );
}

#[test]
fn replay_026_fr_010_kept_for_later_actions_stay_held_after_the_issue_is_resolved() {
    let path = scratch("later");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let task_id = confirmed_task(&mut store, &mut ids);
    offline_edit(&mut store, &mut ids, &task_id);
    let r2 = revision(&mut store, &task_id);
    edit(
        &mut store,
        &mut ids,
        3,
        &task_id,
        json!({ "details": "Later" }),
        shown(EntityType::Task, &task_id, &r2),
    );
    server_edit(&mut store, &task_id, |task| task["title"] = json!("Theirs"));
    replay(&mut store, &context()).unwrap();

    let use_current = resolution(
        2,
        Choice::UseCurrent,
        vec![(3, DependentChoice::KeepForLater)],
    );
    let resolved = resolve_issue(&mut store, &mut ids, &use_current).unwrap();
    assert_eq!(resolved.kept, [cmd(3)]);
    store.close().unwrap();
    let mut store = open(&path).unwrap();
    replay(&mut store, &context()).unwrap();

    // Still held, still an issue, not sent, not applied.
    assert_eq!(state(&mut store, 3), "blocked_dependency");
    let issues = open_issues(&mut store).unwrap();
    assert_eq!(issues.len(), 1);
    assert_eq!(issues[0].issue.command_id, cmd(3));
    assert!(queued(&mut store).is_empty());
    assert_eq!(task(&mut store, &task_id).unwrap()["details"], Value::Null);

    // It can still be retried later, against the version shown at that time.
    let retry = resolution(
        3,
        keep_mine(30, vec![shown(EntityType::Task, &task_id, "2")]),
        vec![],
    );
    resolve_issue(&mut store, &mut ids, &retry).unwrap();
    assert_eq!(state(&mut store, 30), "queued");
    assert_eq!(task(&mut store, &task_id).unwrap()["details"], "Later");
}

#[test]
fn replay_026_fr_010_decision_draft_survives_restart_and_a_changed_version_clears_approval() {
    let path = scratch("draft");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let task_id = confirmed_task(&mut store, &mut ids);
    offline_edit(&mut store, &mut ids, &task_id);
    let r2 = revision(&mut store, &task_id);
    edit(
        &mut store,
        &mut ids,
        3,
        &task_id,
        json!({ "details": "Later" }),
        shown(EntityType::Task, &task_id, &r2),
    );
    server_edit(&mut store, &task_id, |task| task["title"] = json!("Theirs"));
    replay(&mut store, &context()).unwrap();
    let queue_before = states(&mut store);

    let draft = DecisionDraft {
        shown_revision: Some("2".to_string()),
        keep_mine: Some(true),
        dependents: BTreeMap::from([(
            id(3),
            DependentDraft {
                action: DraftAction::ReviewAndRetry,
                approved: true,
                discard_confirmed: true,
            },
        )]),
    };
    assert_eq!(
        save_draft(&mut store, "issue_missing", &draft, NOW).unwrap_err(),
        IssueError::UnknownIssue
    );
    save_draft(&mut store, &issue_id(2), &draft, NOW).unwrap();

    // Closing the sheet or the app never submits it.
    store.close().unwrap();
    let mut store = open(&path).unwrap();
    assert_eq!(states(&mut store), queue_before);
    assert_eq!(open_issues(&mut store).unwrap().len(), 2);
    let restored = load_draft(&mut store, &issue_id(2)).unwrap().unwrap();
    assert_eq!(restored.draft, draft);
    assert!(!restored.changed_again);

    // The record changed after the card was opened: approval is cleared, the
    // user's choices are not.
    server_edit(&mut store, &task_id, |task| task["title"] = json!("Fourth"));
    let restored = load_draft(&mut store, &issue_id(2)).unwrap().unwrap();
    assert!(restored.changed_again);
    let held = &restored.draft.dependents[cmd(3).as_str()];
    assert_eq!(held.action, DraftAction::ReviewAndRetry);
    assert!(!held.approved && held.discard_confirmed);
    assert_eq!(restored.draft.keep_mine, Some(true));

    // Resolving removes the draft.
    let use_current = resolution(
        2,
        Choice::UseCurrent,
        vec![(3, DependentChoice::KeepForLater)],
    );
    resolve_issue(&mut store, &mut ids, &use_current).unwrap();
    assert!(load_draft(&mut store, &issue_id(2)).unwrap().is_none());
}

#[test]
fn replay_026_sc_002_rejection_committed_before_a_crash_is_found_after_it() {
    let path = scratch("crash");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let task_id = confirmed_task(&mut store, &mut ids);
    offline_edit(&mut store, &mut ids, &task_id);
    let r2 = revision(&mut store, &task_id);
    edit(
        &mut store,
        &mut ids,
        3,
        &task_id,
        json!({ "details": "Held" }),
        shown(EntityType::Task, &task_id, &r2),
    );
    create_task(&mut store, &mut ids, 4, "Independent");
    store.close().unwrap();

    let mut child = spawn("reject_then_abort", &path);
    wait_for(&mut child, "rejected");
    assert!(!child.wait().unwrap().success(), "the child aborts");

    let mut store = open(&path).unwrap();
    assert_eq!(state(&mut store, 2), "rejected");
    assert_eq!(state(&mut store, 3), "blocked_dependency");
    assert_eq!(queued(&mut store), [id(4)]);
    let issues = open_issues(&mut store).unwrap();
    assert_eq!(issues.len(), 2);
    assert_eq!(issues[0].issue.local_text, Some(json!({ "title": "Mine" })));
    assert_eq!(task(&mut store, &task_id).unwrap()["title"], "Base");
}

#[test]
fn replay_026_fr_007_a_queued_revoke_then_regrant_replaces_the_confirmed_consent() {
    let path = scratch("consent");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let mut review = context();
    review.policy.weekly_review = true;
    review.policy.navigator_provider = Some(ProviderName::new("navigator").unwrap());
    review.policy.navigator_available = true;

    // The account holds a live grant for the provider.
    store
        .write(|tx| {
            tx.execute(
                "INSERT INTO confirmed_records (workspace_id, record_type, record_key,
                    record_version, edit_revision, tombstone, body)
                 VALUES ((SELECT workspace_id FROM sync_meta), 'review_navigator_consent',
                    '[\"navigator\"]', '1', NULL, 0, ?1)",
                [json!({
                    "provider": "navigator",
                    "consent": {
                        "granted_at": "2026-10-01T10:00:00Z",
                        "revoked_at": null,
                        "consent_text_version": 1
                    }
                })
                .to_string()
                .into_bytes()],
            )?;
            Ok(())
        })
        .unwrap();
    replay(&mut store, &review).unwrap();

    let consent_command = |n, command_type, payload| {
        let mut command = request(cmd(n), command_type, Some("navigator"), payload, Vec::new());
        command.context = review.clone();
        command
    };
    let revoke = consent_command(
        1,
        CommandType::ReviewConsentRevoke,
        json!({ "provider": "navigator" }),
    );
    execute(&mut store, &mut ids, &revoke).unwrap();
    let grant = consent_command(
        2,
        CommandType::ReviewConsentGrant,
        json!({ "provider": "navigator", "consent_text_version": 1 }),
    );
    execute(&mut store, &mut ids, &grant).unwrap();

    // Replaying over the base must see the revoke, not the stale grant, so the
    // re-grant is applied and the consent ends granted, once.
    let replayed = replay(&mut store, &review).unwrap();
    assert_eq!(replayed.applied, [cmd(1), cmd(2)]);
    let consents = visible(&mut store, "review_navigator_consent");
    assert_eq!(consents.len(), 1);
    assert_eq!(consents[0]["consent"]["revoked_at"], Value::Null);
    assert_eq!(consents[0]["consent"]["granted_at"], NOW);
}

#[test]
fn replay_026_fr_007_a_settings_conflict_finds_its_singleton_record_and_revision() {
    let path = scratch("settings");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let settings_edit = |n, weekday: u8, revision: &str| {
        request(
            cmd(n),
            CommandType::ReviewSettings,
            Some("scope-a"),
            json!({ "review_weekday": weekday }),
            vec![shown(EntityType::ReviewSettings, "scope-a", revision)],
        )
    };
    execute(&mut store, &mut ids, &settings_edit(1, 2, "1")).unwrap();
    confirm_all(&mut store);
    let revision: String = store
        .read(|tx| {
            tx.query_row(
                "SELECT edit_revision FROM confirmed_records WHERE record_key = '[]'",
                [],
                |row| row.get(0),
            )
        })
        .unwrap();
    execute(&mut store, &mut ids, &settings_edit(2, 3, &revision)).unwrap();

    // Another device changes the settings first.
    server_edit_at(&mut store, "[]".to_string(), |settings| {
        settings["review_weekday"] = json!(5);
    });
    let replayed = replay(&mut store, &context()).unwrap();
    assert_eq!(replayed.rejected, [cmd(2)]);

    let view = issue(&mut store, &issue_id(2)).unwrap().unwrap();
    assert_eq!(view.issue.reason, IssueReason::RevisionConflict);
    let current = view.current.expect("the singleton settings record");
    assert_eq!(current.entity_type, "review_settings");
    let shown_now = current
        .edit_revision
        .expect("a revision to compare against");
    assert_eq!(current.record.unwrap()["review_weekday"], 5);

    // A draft made against the revision shown is not "changed again".
    let draft = DecisionDraft {
        shown_revision: Some(shown_now),
        ..DecisionDraft::default()
    };
    save_draft(&mut store, &issue_id(2), &draft, NOW).unwrap();
    assert!(
        !load_draft(&mut store, &issue_id(2))
            .unwrap()
            .unwrap()
            .changed_again
    );
}

#[test]
fn replay_026_fr_001_an_upgraded_store_rebuilds_its_projection_before_the_next_gesture() {
    let path = scratch("upgrade");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let task_id = confirmed_task(&mut store, &mut ids);
    offline_edit(&mut store, &mut ids, &task_id);
    store.close().unwrap();
    // Take the file back to what the first release wrote: confirmed rows and a
    // queued edit, but no visible projection.
    rusqlite::Connection::open(&path)
        .unwrap()
        .execute_batch(
            "DROP TABLE visible_records;
             ALTER TABLE outbox DROP COLUMN projection_generation;
             ALTER TABLE outbox DROP COLUMN local_result;
             ALTER TABLE sync_meta DROP COLUMN projection_stale;
             PRAGMA user_version = 1;",
        )
        .unwrap();

    let mut store = open(&path).unwrap();
    // The next edit is decided against the rebuilt projection: the record is
    // there, shown with the queued edit applied, and the edit builds on it.
    let next = request(
        cmd(3),
        CommandType::TaskUpdate,
        Some(&task_id),
        json!({ "details": "After the upgrade" }),
        vec![shown(EntityType::Task, &task_id, "2")],
    );
    execute(&mut store, &mut SeqIds(100), &next).unwrap();
    let projected = task(&mut store, &task_id).unwrap();
    assert_eq!(projected["title"], "Mine");
    assert_eq!(projected["details"], "After the upgrade");
    assert_eq!(visible(&mut store, "task").len(), 1);
    assert_eq!(
        envelope(&mut store, 3)["preconditions"][0]["after_command"]["command_id"],
        cmd(2).as_str()
    );
}

#[test]
fn replay_026_fr_007_a_replacement_must_be_a_new_command_or_nothing_is_closed() {
    let path = scratch("reused");
    let mut store = open(&path).unwrap();
    let mut ids = SeqIds(0);
    let task_id = confirmed_task(&mut store, &mut ids);
    offline_edit(&mut store, &mut ids, &task_id);
    server_edit(&mut store, &task_id, |task| task["title"] = json!("Theirs"));
    replay(&mut store, &context()).unwrap();
    let before = states(&mut store);

    // The old command's own ID, and any other queued command's, are refused.
    for reused in [2, 1] {
        let keep = resolution(
            2,
            keep_mine(reused, vec![shown(EntityType::Task, &task_id, "2")]),
            vec![],
        );
        assert_eq!(
            resolve_issue(&mut store, &mut ids, &keep).unwrap_err(),
            IssueError::ReplacementIdReused(cmd(reused))
        );
    }
    assert_eq!(states(&mut store), before);
    assert_eq!(open_issues(&mut store).unwrap().len(), 1);
    assert_eq!(superseded_by(&mut store, 2), None);
    assert_eq!(task(&mut store, &task_id).unwrap()["title"], "Theirs");
}
