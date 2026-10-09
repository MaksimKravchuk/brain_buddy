//! Parity of the children rules (subtasks, comments) with the server, the Swift
//! reducer and the frozen reference dataset (tasks.md T010, 026-FR-002/006/009/013).
//!
//! The reference dataset supplies the real records. The sequences follow
//! `backend/tests/test_task_lifecycle_detail_api.py`,
//! `test_task_branch_coverage.py` (detail ordering, missing parents) and
//! `ReducerChildrenTests.swift`. Every test counts what it executed, so an
//! empty section fails instead of passing vacuously.

mod support;

use bb_domain::children::{decide, handles, ordered_comments, ordered_subtasks};
use bb_domain::types::*;
use serde_json::{Value, json};
use support::{cases, int, text};

const COMMAND_ID: &str = "00000000-0000-4000-8000-000000000001";
const OWNER_A: &str = "beea96a4-7827-599d-b786-571f694828ac";
const OWNER_B: &str = "863e24a2-2512-59a9-8531-f435e248f118";

fn ran_all(section: &str, ran: usize, expected: usize) {
    assert!(ran > 0, "{section}: no case executed");
    assert_eq!(
        ran, expected,
        "{section}: executed cases differ from the file"
    );
}

// ---------------------------------------------------------------------- builders

fn counter(n: u64) -> String {
    n.to_string()
}

/// A task row from a reference-store record (counters become decimal strings).
/// The Review park snapshot is not a child concern and is left out.
fn task_from(record: &Value) -> Task {
    let formulation = match record["formulation_id"].as_str() {
        Some(id) => json!({
            "id": id,
            "started_at": record["formulation_started_at"],
            "extended_at": record["formulation_extended_at"],
            "extension_reason": record["formulation_extension_reason"],
            "park_floor_at": record["formulation_park_floor_at"],
        }),
        None => Value::Null,
    };
    let mut row = json!({
        "tag_ids": record["tag_ids"],
        "source_capture_ids": record["source_capture_ids"],
        "order_key": counter(int(record, "order_key") as u64),
        "revision": counter(int(record, "revision") as u64),
        "formulation": formulation,
        "parked": null,
    });
    for key in [
        "id",
        "title",
        "details",
        "state",
        "project_id",
        "due_date",
        "priority",
        "waiting_for",
        "waiting_since",
        "created_at",
        "updated_at",
        "completed_at",
        "cancelled_at",
        "consecutive_stalled_formulations",
    ] {
        row[key] = record[key].clone();
    }
    serde_json::from_value(row).unwrap_or_else(|e| panic!("task {}: {e}", record["id"]))
}

fn subtask_from(record: &Value) -> Subtask {
    serde_json::from_value(json!({
        "id": record["id"],
        "task_id": record["task_id"],
        "title": record["title"],
        "state": record["state"],
        "order_key": counter(int(record, "order_key") as u64),
        "revision": counter(int(record, "revision") as u64),
    }))
    .unwrap_or_else(|e| panic!("subtask {}: {e}", record["id"]))
}

fn comment_from(record: &Value) -> Comment {
    serde_json::from_value(json!({
        "id": record["id"],
        "task_id": record["task_id"],
        "body": record["body"],
        "actor_id": record["actor_id"],
        "created_at": record["created_at"],
        "edited_at": record["edited_at"],
        "revision": counter(int(record, "revision") as u64),
    }))
    .unwrap_or_else(|e| panic!("comment {}: {e}", record["id"]))
}

/// The protected read set of one owner of the reference dataset.
fn owner_read_set(owner: &str) -> ReadSet {
    let records = &support::reference_store()["dataset"]["records"];
    let mine = |kind: &str| -> Vec<&Value> {
        cases(records, kind)
            .iter()
            .filter(|record| text(record, "owner_id") == owner)
            .collect()
    };
    let mut read_set = ReadSet::default();
    for record in mine("tasks") {
        let task = task_from(record);
        read_set.tasks.insert(task.id.clone(), task);
    }
    for record in mine("subtasks") {
        let subtask = subtask_from(record);
        read_set.subtasks.insert(subtask.id.clone(), subtask);
    }
    for record in mine("comments") {
        let comment = comment_from(record);
        read_set.comments.insert(comment.id.clone(), comment);
    }
    read_set
}

fn task_id(id: &str) -> TaskId {
    TaskId::parse(id).expect("task id")
}

fn new_subtask_id(n: u64) -> String {
    format!("subtask_00000000-0000-4000-8000-{n:012x}")
}

fn new_comment_id(n: u64) -> String {
    format!("comment_00000000-0000-4000-8000-{n:012x}")
}

fn inputs_at(now: &str, actor: &str) -> ExecutionInputs {
    ExecutionInputs {
        rule_version: 1,
        now: Instant::parse(now).expect("instant"),
        time_zone: ZoneName::new("UTC").expect("zone"),
        origin: WriterOrigin::Legacy,
        actor_id: ActorId::parse(actor).expect("actor"),
        authoritative: true,
        allocated_ids: Vec::new(),
        policy: Policy {
            weekly_review: false,
            navigator_provider: None,
            navigator_available: false,
            consent_text_version: 1,
        },
    }
}

fn inputs() -> ExecutionInputs {
    inputs_at("2026-10-09T12:00:00Z", OWNER_A)
}

/// A revision check on one child.
fn check(entity_type: EntityType, id: &str, revision: u64) -> RevisionCheck {
    RevisionCheck {
        entity_type,
        entity_id: Id::parse(id).expect("id"),
        edit_revision: Counter::from(revision),
    }
}

fn try_command(
    command_type: CommandType,
    entity_id: &str,
    payload: Value,
    checks: Vec<RevisionCheck>,
) -> Result<DomainCommand, DomainError> {
    let object = payload.as_object().expect("payload object");
    let command = Command::from_payload(command_type, object)?;
    command.check_shape()?;
    Ok(DomainCommand {
        command_id: CommandId::parse(COMMAND_ID).expect("command id"),
        entity_id: Id::parse(entity_id).expect("entity id"),
        issued_at: Instant::parse("2026-10-09T11:59:00Z").expect("instant"),
        preconditions: checks,
        command,
    })
}

fn command(
    command_type: CommandType,
    entity_id: &str,
    payload: Value,
    checks: Vec<RevisionCheck>,
) -> DomainCommand {
    try_command(command_type, entity_id, payload, checks)
        .unwrap_or_else(|e| panic!("{command_type:?}: {e}"))
}

fn create_subtask(task: &str, id: &str, title: &str) -> DomainCommand {
    command(
        CommandType::SubtaskCreate,
        id,
        json!({"task_id": task, "title": title}),
        vec![],
    )
}

fn edit_subtask(task: &str, id: &str, payload: Value, revision: u64) -> DomainCommand {
    let mut payload = payload;
    payload["task_id"] = json!(task);
    command(
        CommandType::SubtaskUpdate,
        id,
        payload,
        vec![check(EntityType::Subtask, id, revision)],
    )
}

fn transition_subtask(task: &str, id: &str, action: &str, revision: u64) -> DomainCommand {
    command(
        CommandType::SubtaskTransition,
        id,
        json!({"task_id": task, "action": action}),
        vec![check(EntityType::Subtask, id, revision)],
    )
}

fn create_comment(task: &str, id: &str, body: &str) -> DomainCommand {
    command(
        CommandType::CommentCreate,
        id,
        json!({"task_id": task, "body": body}),
        vec![],
    )
}

fn edit_comment(task: &str, id: &str, body: &str, revision: u64) -> DomainCommand {
    command(
        CommandType::CommentUpdate,
        id,
        json!({"task_id": task, "body": body}),
        vec![check(EntityType::Comment, id, revision)],
    )
}

fn refused(read_set: &ReadSet, command: &DomainCommand) -> DomainError {
    decide(read_set, command, &inputs()).expect_err("the command must be refused")
}

/// Decides, applies the one changed row and returns it.
fn accept(read_set: &mut ReadSet, command: &DomainCommand, inputs: &ExecutionInputs) -> Record {
    let before = read_set.clone();
    let change_set = decide(read_set, command, inputs).unwrap_or_else(|e| panic!("{e}"));
    assert_eq!(change_set.outcome, ChangeOutcome::Applied);
    assert!(change_set.effects.is_empty() && change_set.result == ResultRefs::default());
    assert_eq!(change_set.changes.len(), 1, "one child row, nothing else");
    assert_eq!(*read_set, before, "decide does not mutate the read set");
    let DomainChange::Upsert(record) = change_set.changes[0].clone() else {
        panic!("a child command never deletes");
    };
    match &record {
        Record::Subtask(s) => {
            read_set.subtasks.insert(s.id.clone(), s.clone());
        }
        Record::Comment(c) => {
            read_set.comments.insert(c.id.clone(), c.clone());
        }
        other => panic!("not a child record: {other:?}"),
    }
    record
}

fn subtask_of(record: Record) -> Subtask {
    match record {
        Record::Subtask(s) => s,
        other => panic!("not a subtask: {other:?}"),
    }
}

fn comment_of(record: Record) -> Comment {
    match record {
        Record::Comment(c) => c,
        other => panic!("not a comment: {other:?}"),
    }
}

fn order_of(read_set: &ReadSet, task: &str) -> Vec<String> {
    ordered_subtasks(read_set, &task_id(task))
        .iter()
        .map(|s| s.id.as_str().to_owned())
        .collect()
}

fn titles(read_set: &ReadSet, task: &str) -> Vec<String> {
    ordered_subtasks(read_set, &task_id(task))
        .iter()
        .map(|s| s.title.as_str().to_owned())
        .collect()
}

// -------------------------------------------------------------- reference dataset

#[test]
fn children_026_fr_013_reference_children_stay_attached_to_their_owners_tasks() {
    let expected = &support::reference_store()["dataset"]["expected_counts"];
    let mut ran = 0;
    for owner in [OWNER_A, OWNER_B] {
        let read_set = owner_read_set(owner);
        let counts = &expected[owner];
        assert_eq!(read_set.tasks.len() as i64, int(counts, "tasks"), "{owner}");
        assert_eq!(
            read_set.subtasks.len() as i64,
            int(counts, "subtasks"),
            "{owner}"
        );
        assert_eq!(
            read_set.comments.len() as i64,
            int(counts, "comments"),
            "{owner}"
        );
        for subtask in read_set.subtasks.values() {
            assert!(
                read_set.tasks.contains_key(&subtask.task_id),
                "{}",
                subtask.id
            );
            ran += 1;
        }
        for comment in read_set.comments.values() {
            assert!(
                read_set.tasks.contains_key(&comment.task_id),
                "{}",
                comment.id
            );
            ran += 1;
        }
    }
    ran_all("attached children", ran, 5);
}

#[test]
fn children_026_fr_009_projection_orders_subtasks_by_key_and_comments_by_creation() {
    let read_set = owner_read_set(OWNER_A);
    let tasks = cases(&support::reference_store()["dataset"]["records"], "tasks");
    let mut with_children = 0;
    for record in tasks {
        let id = text(record, "id");
        if text(record, "owner_id") != OWNER_A {
            continue;
        }
        let subtasks = ordered_subtasks(&read_set, &task_id(id));
        let keys: Vec<u64> = subtasks
            .iter()
            .map(|s| s.order_key.to_u64().unwrap())
            .collect();
        assert!(keys.windows(2).all(|w| w[0] < w[1]), "{id}: {keys:?}");
        let comments = ordered_comments(&read_set, &task_id(id));
        assert!(
            comments
                .windows(2)
                .all(|w| w[0].created_at.as_str() <= w[1].created_at.as_str()),
            "{id}"
        );
        if !subtasks.is_empty() || !comments.is_empty() {
            with_children += 1;
        }
    }
    assert_eq!(with_children, 2, "two reference tasks carry children");
    // The backend detail order is (order_key, id): a numeric, not textual, key.
    let mut numeric = ReadSet::default();
    let task = read_set.tasks.values().next().unwrap().clone();
    numeric.tasks.insert(task.id.clone(), task.clone());
    for (n, key) in [("a", 10), ("b", 9), ("c", 100)] {
        let row = json!({"id": format!("sub-{n}"), "task_id": task.id.as_str(),
            "title": n, "state": "open", "order_key": counter(key), "revision": "1"});
        let row: Subtask = serde_json::from_value(row).unwrap();
        numeric.subtasks.insert(row.id.clone(), row);
    }
    assert_eq!(titles(&numeric, task.id.as_str()), ["b", "a", "c"]);
}

#[test]
fn children_026_fr_009_a_new_subtask_is_appended_after_the_highest_key_on_every_reference_task() {
    let tasks = cases(&support::reference_store()["dataset"]["records"], "tasks");
    let (mut ran, mut terminal) = (0, 0);
    for record in tasks {
        let (id, owner) = (text(record, "id"), text(record, "owner_id"));
        let mut read_set = owner_read_set(owner);
        let highest = ordered_subtasks(&read_set, &task_id(id))
            .last()
            .map(|s| s.order_key.to_u64().unwrap() + 1)
            .unwrap_or(0);
        let parent = read_set.tasks[&task_id(id)].clone();
        let first = subtask_of(accept(
            &mut read_set,
            &create_subtask(id, &new_subtask_id(1), "First"),
            &inputs(),
        ));
        assert_eq!(first.order_key, Counter::from(highest), "{id}");
        assert_eq!(
            (first.state, first.revision.clone()),
            (ChildState::Open, Counter::from(1))
        );
        let second = subtask_of(accept(
            &mut read_set,
            &create_subtask(id, &new_subtask_id(2), "Second"),
            &inputs(),
        ));
        assert_eq!(second.order_key, Counter::from(highest + 1), "{id}");
        assert_eq!(
            order_of(&read_set, id)
                .iter()
                .rev()
                .take(2)
                .rev()
                .cloned()
                .collect::<Vec<_>>(),
            [new_subtask_id(1), new_subtask_id(2)],
            "{id}: appended, never inserted"
        );
        assert_eq!(
            read_set.tasks[&task_id(id)],
            parent,
            "{id}: the parent is untouched"
        );
        if matches!(text(record, "state"), "completed" | "cancelled") {
            terminal += 1;
        }
        ran += 1;
    }
    ran_all("create on every reference task", ran, tasks.len());
    assert!(
        terminal >= 2,
        "completed and cancelled parents accept children"
    );
}

#[test]
fn children_026_fr_013_every_reference_subtask_transitions_to_any_other_state_only() {
    let read_set = owner_read_set(OWNER_A);
    let (mut ran, mut refused_same) = (0, 0);
    let all = [
        ("complete", ChildState::Completed),
        ("cancel", ChildState::Cancelled),
        ("reopen", ChildState::Open),
    ];
    for subtask in read_set.subtasks.values() {
        for (action, target) in all {
            let revision = subtask.revision.to_u64().unwrap();
            let command = transition_subtask(
                subtask.task_id.as_str(),
                subtask.id.as_str(),
                action,
                revision,
            );
            if subtask.state == target {
                let error = refused(&read_set, &command);
                assert_eq!(error.reason, Reason::SubtaskAlreadyInState);
                refused_same += 1;
            } else {
                let mut scratch = read_set.clone();
                let updated = subtask_of(accept(&mut scratch, &command, &inputs()));
                assert_eq!(updated.state, target);
                assert_eq!(updated.revision, Counter::from(revision + 1));
                assert_eq!(
                    (
                        &updated.id,
                        &updated.task_id,
                        &updated.title,
                        &updated.order_key
                    ),
                    (
                        &subtask.id,
                        &subtask.task_id,
                        &subtask.title,
                        &subtask.order_key
                    )
                );
            }
            ran += 1;
        }
    }
    ran_all("transitions", ran, 9);
    assert_eq!(refused_same, 3, "each subtask refuses its own state");
}

#[test]
fn children_026_fr_013_reference_comment_edit_keeps_identity_and_author() {
    let read_set = owner_read_set(OWNER_A);
    let editor = "someone-else";
    let mut ran = 0;
    for comment in read_set.comments.values() {
        let command = edit_comment(comment.task_id.as_str(), comment.id.as_str(), "Reworded", 1);
        let mut scratch = read_set.clone();
        let edited = comment_of(accept(
            &mut scratch,
            &command,
            &inputs_at("2026-10-10T08:30:00Z", editor),
        ));
        assert_eq!(edited.body.as_str(), "Reworded");
        assert_eq!(
            edited.edited_at.as_ref().map(Instant::as_str),
            Some("2026-10-10T08:30:00Z")
        );
        assert_eq!(edited.revision, Counter::from(2));
        assert_eq!(
            (
                &edited.id,
                &edited.task_id,
                &edited.actor_id,
                &edited.created_at
            ),
            (
                &comment.id,
                &comment.task_id,
                &comment.actor_id,
                &comment.created_at
            ),
            "the author is the original one, not the editor"
        );
        // The server bumps the revision even for an identical body.
        let same = edit_comment(
            comment.task_id.as_str(),
            comment.id.as_str(),
            comment.body.as_str(),
            1,
        );
        let again = comment_of(accept(&mut read_set.clone(), &same, &inputs()));
        assert_eq!(again.revision, Counter::from(2));
        ran += 1;
    }
    ran_all("comment edits", ran, 2);
}

#[test]
fn children_026_fr_013_another_owners_records_are_not_found() {
    let owner_b = owner_read_set(OWNER_B);
    let owner_a = owner_read_set(OWNER_A);
    let foreign_task = owner_a.tasks.keys().next().unwrap().as_str().to_owned();
    let foreign_subtask = owner_a.subtasks.values().next().unwrap().clone();
    let foreign_comment = owner_a.comments.values().next().unwrap().clone();
    let mut ran = 0;
    for command in [
        create_subtask(&foreign_task, &new_subtask_id(1), "x"),
        create_comment(&foreign_task, &new_comment_id(1), "x"),
        edit_subtask(
            foreign_subtask.task_id.as_str(),
            foreign_subtask.id.as_str(),
            json!({"title": "x"}),
            1,
        ),
        transition_subtask(
            foreign_subtask.task_id.as_str(),
            foreign_subtask.id.as_str(),
            "cancel",
            1,
        ),
        edit_comment(
            foreign_comment.task_id.as_str(),
            foreign_comment.id.as_str(),
            "x",
            1,
        ),
    ] {
        let error = refused(&owner_b, &command);
        assert_eq!(
            error.reason,
            Reason::NotFound,
            "{:?}",
            command.command_type()
        );
        ran += 1;
    }
    ran_all("foreign records", ran, 5);
}

// ---------------------------------------------------------------- backend sequences

/// `test_subtask_and_comment_detail_commands_persist`.
#[test]
fn children_026_fr_006_backend_detail_commands_persist_in_order() {
    let mut read_set = owner_read_set(OWNER_A);
    let task = "47229eef-b12d-56a4-aafb-845b4696ff3d";
    let sub = new_subtask_id(7);
    let created = subtask_of(accept(
        &mut read_set,
        &create_subtask(task, &sub, "Draft outline"),
        &inputs(),
    ));
    assert_eq!(
        (created.revision.to_u64(), created.state),
        (Some(1), ChildState::Open)
    );
    let edited = subtask_of(accept(
        &mut read_set,
        &edit_subtask(task, &sub, json!({"title": "Draft final outline"}), 1),
        &inputs(),
    ));
    assert_eq!(
        (edited.title.as_str(), edited.revision.to_u64()),
        ("Draft final outline", Some(2))
    );
    let completed = subtask_of(accept(
        &mut read_set,
        &transition_subtask(task, &sub, "complete", 2),
        &inputs(),
    ));
    assert_eq!(
        (completed.state, completed.revision.to_u64()),
        (ChildState::Completed, Some(3))
    );

    let note = new_comment_id(7);
    let comment = comment_of(accept(
        &mut read_set,
        &create_comment(task, &note, "Initial note"),
        &inputs(),
    ));
    assert!(comment.edited_at.is_none());
    let edited = comment_of(accept(
        &mut read_set,
        &edit_comment(task, &note, "Edited note", 1),
        &inputs_at("2026-10-09T13:00:00Z", OWNER_A),
    ));
    assert!(edited.edited_at.is_some());
    // The detail projection: the dataset's own subtask first, then the new one.
    assert_eq!(
        titles(&read_set, task),
        ["Find his number", "Draft final outline"]
    );
    let comments = ordered_comments(&read_set, &task_id(task));
    assert_eq!(comments.last().unwrap().body.as_str(), "Edited note");
}

/// `test_subtask_comment_idempotency_and_transition_edges`: an edit without a
/// title is accepted, a transition to the same state is a 400, cancel then reopen.
#[test]
fn children_026_fr_006_backend_edges_untouched_title_same_state_and_reopen() {
    let mut read_set = owner_read_set(OWNER_A);
    let task = "da6395c2-8e67-527b-be6d-4b5673d9e756";
    let sub = new_subtask_id(8);
    accept(
        &mut read_set,
        &create_subtask(task, &sub, "Collect examples"),
        &inputs(),
    );
    accept(
        &mut read_set,
        &edit_subtask(task, &sub, json!({"title": "Collect final examples"}), 1),
        &inputs(),
    );
    let untouched = subtask_of(accept(
        &mut read_set,
        &edit_subtask(task, &sub, json!({}), 2),
        &inputs(),
    ));
    assert_eq!(untouched.title.as_str(), "Collect final examples");
    assert_eq!(
        untouched.revision.to_u64(),
        Some(3),
        "no title still bumps the revision"
    );
    let completed = subtask_of(accept(
        &mut read_set,
        &transition_subtask(task, &sub, "complete", 3),
        &inputs(),
    ));
    let same = refused(&read_set, &transition_subtask(task, &sub, "complete", 4));
    assert_eq!(same.reason, Reason::SubtaskAlreadyInState);
    assert_eq!(completed.revision.to_u64(), Some(4));

    let other = new_subtask_id(9);
    accept(
        &mut read_set,
        &create_subtask(task, &other, "Discarded branch"),
        &inputs(),
    );
    let cancelled = subtask_of(accept(
        &mut read_set,
        &transition_subtask(task, &other, "cancel", 1),
        &inputs(),
    ));
    let reopened = subtask_of(accept(
        &mut read_set,
        &transition_subtask(task, &other, "reopen", 2),
        &inputs(),
    ));
    assert_eq!(
        (cancelled.state, reopened.state),
        (ChildState::Cancelled, ChildState::Open)
    );
    // Completed to cancelled directly: any other state is allowed.
    let moved = subtask_of(accept(
        &mut read_set,
        &transition_subtask(task, &sub, "cancel", 4),
        &inputs(),
    ));
    assert_eq!(moved.state, ChildState::Cancelled);
}

/// `test_get_task_detail_orders_subtasks_and_comments` and
/// `test_create_{subtask,comment}_rejects_missing_task`.
#[test]
fn children_026_fr_009_backend_detail_order_and_missing_parent() {
    let mut read_set = owner_read_set(OWNER_B);
    let task = read_set.tasks.keys().next().unwrap().as_str().to_owned();
    let (s1, s2) = (new_subtask_id(1), new_subtask_id(2));
    let (c1, c2) = (new_comment_id(1), new_comment_id(2));
    accept(
        &mut read_set,
        &create_subtask(&task, &s1, "First"),
        &inputs(),
    );
    accept(
        &mut read_set,
        &create_subtask(&task, &s2, "Second"),
        &inputs(),
    );
    accept(
        &mut read_set,
        &create_comment(&task, &c1, "First comment"),
        &inputs_at("2026-10-09T12:00:00Z", OWNER_B),
    );
    accept(
        &mut read_set,
        &create_comment(&task, &c2, "Second comment"),
        &inputs_at("2026-10-09T12:00:01Z", OWNER_B),
    );
    assert_eq!(order_of(&read_set, &task), [s1, s2]);
    let ids: Vec<&str> = ordered_comments(&read_set, &task_id(&task))
        .iter()
        .map(|c| c.id.as_str())
        .collect();
    assert_eq!(ids, [c1.as_str(), c2.as_str()]);
    // The same instant orders by id; an offset is read as the instant it names.
    let mut tied = read_set.clone();
    let late = new_comment_id(0);
    accept(
        &mut tied,
        &create_comment(&task, &late, "Tie"),
        &inputs_at("2026-10-09T12:00:00Z", OWNER_B),
    );
    let ids: Vec<&str> = ordered_comments(&tied, &task_id(&task))
        .iter()
        .map(|c| c.id.as_str())
        .collect();
    assert_eq!(ids, [late.as_str(), c1.as_str(), c2.as_str()]);

    for command in [
        create_subtask("missing-task", &new_subtask_id(3), "Nope"),
        create_comment("missing-task", &new_comment_id(3), "Nope"),
    ] {
        let error = refused(&read_set, &command);
        assert_eq!(error.reason, Reason::NotFound);
        assert_eq!(
            error.entity,
            Some((EntityType::Task, vec!["missing-task".to_owned()]))
        );
    }
}

// ----------------------------------------------------------------- Swift sequences

/// `ReducerSubtaskTests`/`ReducerCommentTests`: terminal parents, order keys,
/// verbatim comments, unchanged parent.
#[test]
fn children_026_fr_009_swift_order_keys_continue_after_the_highest_existing_one() {
    let mut read_set = owner_read_set(OWNER_B);
    let task = read_set.tasks.keys().next().unwrap().clone();
    let seven: Subtask = serde_json::from_value(json!({"id": "a", "task_id": task.as_str(),
        "title": "A", "state": "open", "order_key": "7", "revision": "1"}))
    .unwrap();
    read_set.subtasks.insert(seven.id.clone(), seven);
    let b = subtask_of(accept(
        &mut read_set,
        &create_subtask(task.as_str(), &new_subtask_id(1), "B"),
        &inputs(),
    ));
    assert_eq!(b.order_key.to_u64(), Some(8));
}

#[test]
fn children_026_fr_002_swift_comments_are_verbatim_and_the_actor_is_the_trusted_one() {
    let mut read_set = owner_read_set(OWNER_A);
    let done = read_set
        .tasks
        .values()
        .find(|t| t.state == TaskState::Completed)
        .unwrap()
        .id
        .clone();
    let body = "  Called, no answer \n";
    let comment = comment_of(accept(
        &mut read_set,
        &create_comment(done.as_str(), &new_comment_id(1), body),
        &inputs_at("2026-10-09T12:00:04Z", "trusted-actor"),
    ));
    assert_eq!(comment.body.as_str(), body, "no trimming");
    assert_eq!(comment.actor_id.as_str(), "trusted-actor");
    assert_eq!(comment.created_at.as_str(), "2026-10-09T12:00:04Z");
    assert_eq!(
        (comment.edited_at, comment.revision.to_u64()),
        (None, Some(1))
    );
    // Only the empty string is refused; a blank comment is valid.
    let blank = comment_of(accept(
        &mut read_set,
        &create_comment(done.as_str(), &new_comment_id(2), " "),
        &inputs(),
    ));
    assert_eq!(blank.body.as_str(), " ");
}

#[test]
fn children_026_fr_002_server_rules_win_over_swift_where_they_differ() {
    let mut read_set = owner_read_set(OWNER_A);
    let task = "47229eef-b12d-56a4-aafb-845b4696ff3d";
    // Swift trims a subtask title and refuses a blank one; the server stores it as sent.
    let padded = subtask_of(accept(
        &mut read_set,
        &create_subtask(task, &new_subtask_id(1), "  First "),
        &inputs(),
    ));
    assert_eq!(padded.title.as_str(), "  First ");
    let blank = subtask_of(accept(
        &mut read_set,
        &create_subtask(task, &new_subtask_id(2), " "),
        &inputs(),
    ));
    assert_eq!(blank.title.as_str(), " ");
    // Swift refuses an edit that changes nothing; the server applies it and bumps the revision.
    let id = new_subtask_id(1);
    let same = subtask_of(accept(
        &mut read_set,
        &edit_subtask(task, &id, json!({"title": "  First "}), 1),
        &inputs(),
    ));
    assert_eq!(same.revision.to_u64(), Some(2));
}

// ---------------------------------------------------------------------- refusals

#[test]
fn children_026_fr_013_refusals_name_the_reason_and_the_record() {
    let read_set = owner_read_set(OWNER_A);
    let task = "da6395c2-8e67-527b-be6d-4b5673d9e756";
    let other_task = "47229eef-b12d-56a4-aafb-845b4696ff3d";
    let existing = "bcdeff19-b40c-5307-993e-d5f703e239bd";
    let existing_comment = "6a5b54bc-3982-5686-b6a0-052e7458045f";
    let ran = std::cell::Cell::new(0);
    let expect = |command: DomainCommand, reason: Reason| {
        let error = refused(&read_set, &command);
        assert_eq!(error.reason, reason, "{:?}", command.command_type());
        ran.set(ran.get() + 1);
        error
    };

    // Identity: a created ID that already exists, or is not a native shape.
    let taken = new_subtask_id(5);
    let mut with_taken = read_set.clone();
    accept(
        &mut with_taken,
        &create_subtask(task, &taken, "x"),
        &inputs(),
    );
    let again = decide(&with_taken, &create_subtask(task, &taken, "y"), &inputs()).unwrap_err();
    assert_eq!(again.reason, Reason::IdAlreadyExists);
    assert_eq!(
        again.entity,
        Some((EntityType::Subtask, vec![taken.clone()]))
    );
    ran.set(ran.get() + 1);
    expect(
        create_subtask(task, "subtask_not-a-uuid", "x"),
        Reason::InvalidValue,
    );
    expect(
        create_comment(task, "comment_not-a-uuid", "x"),
        Reason::InvalidValue,
    );
    expect(create_subtask(task, existing, "x"), Reason::InvalidValue);

    // Attachment: the child must belong to the command's parent.
    expect(
        edit_subtask(other_task, existing, json!({"title": "x"}), 1),
        Reason::NotFound,
    );
    expect(
        transition_subtask(other_task, existing, "cancel", 1),
        Reason::NotFound,
    );
    expect(
        edit_comment(other_task, existing_comment, "x", 1),
        Reason::NotFound,
    );
    expect(
        edit_subtask(task, "missing", json!({"title": "x"}), 1),
        Reason::NotFound,
    );
    expect(edit_comment(task, "missing", "x", 1), Reason::NotFound);
    expect(
        edit_subtask("missing", existing, json!({"title": "x"}), 1),
        Reason::NotFound,
    );
    expect(
        create_subtask("missing", &new_subtask_id(6), "x"),
        Reason::NotFound,
    );

    // Versions: the child's own revision, never the parent's.
    let stale = expect(
        edit_subtask(task, existing, json!({"title": "x"}), 9),
        Reason::RevisionConflict,
    );
    assert_eq!(stale.current_revision, Some(Counter::from(1)));
    assert_eq!(
        stale.entity,
        Some((EntityType::Subtask, vec![existing.to_owned()]))
    );
    expect(
        transition_subtask(task, existing, "complete", 0),
        Reason::RevisionConflict,
    );
    let stale = expect(
        edit_comment(task, existing_comment, "x", 2),
        Reason::RevisionConflict,
    );
    assert_eq!(
        stale.entity,
        Some((EntityType::Comment, vec![existing_comment.to_owned()]))
    );
    let on_parent = command(
        CommandType::SubtaskUpdate,
        existing,
        json!({"task_id": task, "title": "x"}),
        vec![check(EntityType::Task, task, 1)],
    );
    let error = expect(on_parent, Reason::InvalidPayload);
    assert_eq!(
        error.field.as_deref(),
        Some("preconditions"),
        "parent revision is not a child check"
    );
    let none = command(
        CommandType::CommentUpdate,
        existing_comment,
        json!({"task_id": task, "body": "x"}),
        vec![],
    );
    expect(none, Reason::InvalidPayload);
    // The check order is the server's: a missing child before a stale revision.
    expect(
        edit_subtask(task, "missing", json!({"title": "x"}), 9),
        Reason::NotFound,
    );
    // A transition to the current state loses to a stale revision, as on the server.
    expect(
        transition_subtask(task, existing, "reopen", 5),
        Reason::RevisionConflict,
    );
    let same = expect(
        transition_subtask(task, existing, "reopen", 1),
        Reason::SubtaskAlreadyInState,
    );
    assert_eq!(
        same.entity,
        Some((EntityType::Subtask, vec![existing.to_owned()]))
    );
    assert!(ran.get() >= 17, "{}", ran.get());

    // A command of another family is not decided here.
    let other = command(CommandType::TagDelete, "tag_x", json!({}), vec![]);
    assert!(!handles(&other.command));
    assert_eq!(refused(&read_set, &other).reason, Reason::InvalidPayload);
    assert!(handles(
        &create_subtask(task, &new_subtask_id(1), "x").command
    ));
}

#[test]
fn children_026_fr_002_scalar_limits_are_unicode_scalars_and_unknown_fields_are_refused() {
    let task = "t";
    let subtask = |title: String| {
        try_command(
            CommandType::SubtaskCreate,
            &new_subtask_id(1),
            json!({"task_id": task, "title": title}),
            vec![],
        )
    };
    let comment = |body: String| {
        try_command(
            CommandType::CommentCreate,
            &new_comment_id(1),
            json!({"task_id": task, "body": body}),
            vec![],
        )
    };
    let mut ran = 0;
    // 500 emoji are 500 scalars (2000 UTF-8 bytes, 1000 UTF-16 units): accepted.
    assert!(subtask("\u{1F600}".repeat(500)).is_ok());
    assert!(subtask("x".repeat(501)).is_err());
    assert!(subtask(String::new()).is_err());
    assert!(comment("\u{1F600}".repeat(20_000)).is_ok());
    assert!(comment("x".repeat(20_001)).is_err());
    assert!(comment(String::new()).is_err());
    ran += 6;
    for (kind, payload) in [
        (
            CommandType::SubtaskCreate,
            json!({"task_id": task, "title": "x", "state": "open"}),
        ),
        (CommandType::SubtaskCreate, json!({"title": "x"})),
        (
            CommandType::SubtaskUpdate,
            json!({"task_id": task, "title": null}),
        ),
        (
            CommandType::SubtaskUpdate,
            json!({"task_id": task, "order_key": "3"}),
        ),
        (
            CommandType::SubtaskTransition,
            json!({"task_id": task, "action": "delete"}),
        ),
        (
            CommandType::CommentCreate,
            json!({"task_id": task, "body": "x", "actor_id": "forged"}),
        ),
        (CommandType::CommentUpdate, json!({"task_id": task})),
    ] {
        let error = try_command(kind, "x", payload, vec![]).unwrap_err();
        assert_eq!(error.reason, Reason::InvalidPayload, "{kind:?}");
        ran += 1;
    }
    assert_eq!(ran, 13);
}

#[test]
fn children_026_fr_006_a_decision_is_deterministic_and_touches_only_the_child() {
    let read_set = owner_read_set(OWNER_A);
    let task = "da6395c2-8e67-527b-be6d-4b5673d9e756";
    let command = create_subtask(task, &new_subtask_id(1), "Same");
    let first = decide(&read_set, &command, &inputs()).unwrap();
    let second = decide(&read_set, &command, &inputs()).unwrap();
    assert_eq!(first, second);
    assert_eq!(
        first.affected_keys(),
        [(EntityType::Subtask, vec![new_subtask_id(1)])]
    );
    // Time moves only comments; a subtask row has no instant.
    let early = decide(
        &read_set,
        &command,
        &inputs_at("2026-01-01T00:00:00Z", OWNER_A),
    )
    .unwrap();
    assert_eq!(first, early);
}
