//! The public library's one dispatch (tasks.md T062, PR-62): every catalog
//! command and query kind reaches exactly one family, the routed answer is the
//! family's own answer over the frozen oracle data, and what no family owns is
//! an explicit refusal.
//!
//! Only the public API is used: `bb_domain::dispatch` and, as the reference the
//! routed answer is compared with, each family's own `decide`/`query`. The
//! family rules themselves are held by their `*_parity` suites.

mod support;

use std::collections::{BTreeMap, BTreeSet};

use bb_domain::dispatch::{
    self, CommandFamily, QueryFamily, QueryKind, command_claims, command_owner, query_claims,
    query_kind, query_owner, unowned,
};
use bb_domain::types::*;
use bb_domain::{children, organize, park, queries, review_decisions, review_sessions};
use bb_domain::{smart_add, task_rules};
use bb_protocol::command::{CommandEnvelope, Decoded, decode_command};
use bb_protocol::receipt::Receipt;
use serde_json::{Map, Value, json};
use support::{cases, text};

const NOW: &str = "2026-10-09T12:00:00Z";
const OWNER_A: &str = "beea96a4-7827-599d-b786-571f694828ac";
/// The reference store's Next task with a running formulation (revision 4).
const REF_TASK: &str = "da6395c2-8e67-527b-be6d-4b5673d9e756";

// ----------------------------------------------------------------------- harness

fn exec(allocated: &[&str]) -> ExecutionInputs {
    exec_at(NOW, allocated)
}

fn exec_at(now: &str, allocated: &[&str]) -> ExecutionInputs {
    serde_json::from_value(json!({
        "rule_version": 1, "now": now, "time_zone": "UTC", "origin": "device",
        "actor_id": "actor-example", "authoritative": true, "allocated_ids": allocated,
        "policy": {
            "weekly_review": true, "navigator_provider": null,
            "navigator_available": false, "consent_text_version": 1,
        },
    }))
    .expect("execution inputs")
}

fn query_inputs(weekly_review: bool) -> QueryInputs {
    serde_json::from_value(json!({
        "now": NOW, "device_zone": "UTC",
        "policy": {
            "weekly_review": weekly_review, "navigator_provider": null,
            "navigator_available": false, "consent_text_version": 1,
        },
    }))
    .expect("query inputs")
}

fn check(entity_type: &str, id: &str, revision: u64) -> Value {
    json!({ "entity_type": entity_type, "entity_id": id, "edit_revision": revision.to_string() })
}

fn envelope_json(kind: &str, entity: &str, payload: Value, preconditions: Value) -> String {
    envelope_json_after(kind, entity, payload, preconditions, &[])
}

fn envelope_json_after(
    kind: &str,
    entity: &str,
    payload: Value,
    preconditions: Value,
    depends_on: &[&str],
) -> String {
    json!({
        "protocol_version": 1,
        "command_id": "01900000-0000-4000-8000-000000000001",
        "scope_id": "scope-example", "device_id": "device-example",
        "device_epoch": "epoch-example", "local_sequence": "7",
        "type": kind, "command_version": 1, "entity_id": entity,
        "preconditions": preconditions, "depends_on": depends_on,
        "issued_at": NOW, "payload": payload,
    })
    .to_string()
}

fn envelope(kind: &str, entity: &str, payload: Value, preconditions: Value) -> CommandEnvelope {
    match decode_command(&envelope_json(kind, entity, payload, preconditions)) {
        Ok(Decoded::Executable(envelope)) => envelope,
        other => panic!("{kind} did not decode as an executable command: {other:?}"),
    }
}

fn command(kind: &str, entity: &str, payload: Value, checks: Vec<Value>) -> DomainCommand {
    let envelope = envelope(kind, entity, payload, Value::Array(checks));
    DomainCommand::from_envelope(&envelope, &NoReceipts).unwrap_or_else(|e| panic!("{kind}: {e}"))
}

fn accepted(result: Result<ChangeSet, DomainError>) -> ChangeSet {
    result.unwrap_or_else(|e| panic!("expected acceptance, got {e:?}"))
}

fn entity_types(set: &ChangeSet) -> BTreeSet<&'static str> {
    set.changes
        .iter()
        .map(|change| change.entity_type().as_str())
        .collect()
}

// ------------------------------------------------------- the frozen catalog samples

/// One valid payload per catalog command type (the shapes `types.rs` pins).
fn sample_payloads() -> Vec<(&'static str, Value)> {
    let id = "00000000-0000-4000-8000-000000000000";
    vec![
        ("project.create", json!({"name": "Flat"})),
        ("project.update", json!({"color": null})),
        ("project.archive", json!({})),
        ("project.unarchive", json!({})),
        ("tag.create", json!({"name": "@home"})),
        ("tag.update", json!({"name": "@office"})),
        ("tag.delete", json!({})),
        ("task.create", json!({"title": "Buy milk"})),
        (
            "task.smart_add",
            json!({"title": "Call Ann",
                "project": {"name": "Flat", "proposed_id": format!("project_{id}")},
                "tags": [{"id": "tag_1"}]}),
        ),
        ("task.update", json!({"title": "x"})),
        (
            "task.tags",
            json!({"add_tag_ids": ["tag_a"], "remove_tag_ids": ["tag_b"]}),
        ),
        ("task.transition", json!({"action": "complete"})),
        ("subtask.create", json!({"task_id": "task_1", "title": "x"})),
        ("subtask.update", json!({"task_id": "task_1", "title": "y"})),
        (
            "subtask.transition",
            json!({"task_id": "task_1", "action": "cancel"}),
        ),
        ("comment.create", json!({"task_id": "task_1", "body": "hi"})),
        (
            "comment.update",
            json!({"task_id": "task_1", "body": "hello"}),
        ),
        (
            "review.decide",
            json!({"decision_id": format!("decision_{id}"), "type": "complete"}),
        ),
        ("review.undo_decision", json!({})),
        (
            "review.auto_park",
            json!({"formulation_id": "form_0a1b2c3d4e5f"}),
        ),
        ("review.explainer_ack", json!({})),
        (
            "review.settings",
            json!({"threshold_days": 14, "onboarded": true}),
        ),
        ("review.parks_ack", json!({"items": []})),
        (
            "review.session_start",
            json!({"mode": "quick", "entry": "list", "origin": "web", "replace_open": false}),
        ),
        (
            "review.session_progress",
            json!({"progress_id": format!("progress_{id}")}),
        ),
        ("review.session_finish", json!({})),
        (
            "review.bulk_release",
            json!({"kind": "restart", "items": []}),
        ),
        ("review.bulk_undo", json!({})),
        (
            "review.consent_grant",
            json!({"provider": "openai", "consent_text_version": 1}),
        ),
        ("review.consent_revoke", json!({"provider": "openai"})),
    ]
}

/// One typed command per catalog command type, keyed by its wire name.
fn sample_commands() -> BTreeMap<&'static str, Command> {
    sample_payloads()
        .into_iter()
        .map(|(wire, payload)| {
            let command_type = CommandType::from_wire(wire).expect("a catalog command type");
            let Value::Object(payload) = payload else {
                panic!("{wire}: a payload is an object")
            };
            let command = Command::from_payload(command_type, &payload)
                .unwrap_or_else(|e| panic!("{wire}: {e}"));
            (wire, command)
        })
        .collect()
}

/// One query per query kind.
fn sample_queries() -> Vec<Query> {
    [
        json!({"kind": "task_list", "list": "next", "project_id": null, "tag_id": null,
               "sort": "manual", "page": {"limit": 50, "after": null}}),
        json!({"kind": "task_detail", "task_id": REF_TASK}),
        json!({"kind": "list_counts"}),
        json!({"kind": "projects", "filter": "active"}),
        json!({"kind": "project_display", "project_id": "4f4a6fa6-8e51-598c-a064-36566e6b1101"}),
        json!({"kind": "tags"}),
        json!({"kind": "review_state"}),
        json!({"kind": "review_queue", "step": "wins", "session_id": null}),
    ]
    .into_iter()
    .map(|raw| serde_json::from_value(raw.clone()).unwrap_or_else(|e| panic!("{raw}: {e}")))
    .collect()
}

// ------------------------------------------------------------------- the oracle data

/// The reference store's rows for one owner, as the `ReadSet` the runtime loads.
fn reference_read_set(owner: &str) -> ReadSet {
    let records = &support::reference_store()["dataset"]["records"];
    let mine = |name: &str| -> Vec<Value> {
        cases(records, name)
            .iter()
            .filter(|row| text(row, "owner_id") == owner)
            .cloned()
            .collect()
    };
    let counter = |row: &Value, key: &str| Value::String(row[key].to_string());
    let keyed = |rows: Vec<Value>| -> Value {
        Value::Object(
            rows.into_iter()
                .map(|row| (text(&row, "id").to_owned(), row))
                .collect::<Map<_, _>>(),
        )
    };
    let projects = mine("projects").into_iter().map(|row| {
        json!({
            "id": row["id"], "name": row["name"], "color": row["color"],
            "state": row["state"], "revision": counter(&row, "revision"),
            "desired_outcome": row["desired_outcome"], "archived_at": row["archived_at"],
            "archived_before_lossless": row["archived_before_lossless"],
        })
    });
    let tags = mine("tags").into_iter().map(|row| {
        json!({
            "id": row["id"], "name": row["name"], "state": row["state"],
            "revision": counter(&row, "revision"),
        })
    });
    let tasks = mine("tasks").into_iter().map(|row| {
        let formulation = row["formulation_id"].as_str().map(|id| {
            json!({
                "id": id, "started_at": row["formulation_started_at"],
                "extended_at": row["formulation_extended_at"],
                "extension_reason": row["formulation_extension_reason"],
                "park_floor_at": row["formulation_park_floor_at"],
            })
        });
        let parked = row["parked"].as_object().map(|park| {
            let before = &park["clock_before"];
            json!({
                "at": park["at"], "formulation_id": park["formulation_id"],
                "private": {
                    "from_revision": park["from_revision"].to_string(),
                    "clock_before": {
                        "formulation_id": park["formulation_id"],
                        "started_at": before["started_at"], "extended_at": before["extended_at"],
                        "extension_reason": before["extension_reason"],
                        "park_floor_at": before["park_floor_at"],
                        "stalled_before": before["stalled_before"],
                    },
                },
            })
        });
        json!({
            "id": row["id"], "title": row["title"], "details": row["details"],
            "state": row["state"], "project_id": row["project_id"], "tag_ids": row["tag_ids"],
            "due_date": row["due_date"], "priority": row["priority"],
            "waiting_for": row["waiting_for"], "waiting_since": row["waiting_since"],
            "order_key": counter(&row, "order_key"),
            "source_capture_ids": row["source_capture_ids"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "completed_at": row["completed_at"], "cancelled_at": row["cancelled_at"],
            "revision": counter(&row, "revision"),
            "consecutive_stalled_formulations": row["consecutive_stalled_formulations"],
            "formulation": formulation, "parked": parked,
        })
    });
    let subtasks = mine("subtasks").into_iter().map(|row| {
        json!({
            "id": row["id"], "task_id": row["task_id"], "title": row["title"],
            "state": row["state"], "order_key": counter(&row, "order_key"),
            "revision": counter(&row, "revision"),
        })
    });
    let comments = mine("comments").into_iter().map(|row| {
        json!({
            "id": row["id"], "task_id": row["task_id"], "body": row["body"],
            "actor_id": row["actor_id"], "created_at": row["created_at"],
            "edited_at": row["edited_at"], "revision": counter(&row, "revision"),
        })
    });
    serde_json::from_value(json!({
        "projects": keyed(projects.collect()),
        "tags": keyed(tags.collect()),
        "tasks": keyed(tasks.collect()),
        "subtasks": keyed(subtasks.collect()),
        "comments": keyed(comments.collect()),
        "settings": {
            "threshold_days": 14, "review_weekday": 5, "review_time": "16:00",
            "time_zone": "UTC", "onboarded_at": null, "activated_at": "2026-08-01T00:00:00Z",
            "owner_park_floor_at": null, "revision": "2",
        },
    }))
    .unwrap_or_else(|e| panic!("the reference read set: {e}"))
}

/// A Next task `1` whose formulation started 19 days ago (asked, not yet parked).
fn review_read_set() -> ReadSet {
    let id = "00000000-0000-4000-8000-000000000001";
    serde_json::from_value(json!({
        "tasks": { format!("task_{id}"): {
            "id": format!("task_{id}"), "title": "Call Bob", "details": null, "state": "next",
            "project_id": null, "tag_ids": [], "due_date": null, "priority": "none",
            "waiting_for": null, "waiting_since": null, "order_key": "3",
            "source_capture_ids": [], "created_at": "2026-09-01T09:00:00Z",
            "updated_at": "2026-09-02T09:00:00Z", "completed_at": null, "cancelled_at": null,
            "revision": "1", "consecutive_stalled_formulations": 0,
            "formulation": { "id": format!("form_{id}"), "started_at": "2026-09-20T09:00:00Z",
                "extended_at": null, "extension_reason": null, "park_floor_at": null },
            "parked": null,
        }},
        "settings": {
            "threshold_days": 14, "review_weekday": 5, "review_time": "16:00",
            "time_zone": "UTC", "onboarded_at": null, "activated_at": "2026-08-01T00:00:00Z",
            "owner_park_floor_at": null, "revision": "2",
        },
    }))
    .expect("the review read set")
}

/// A Next task whose formulation started 29 days before `NOW` (`park_due`), an
/// activated owner whose last effective evaluation was a minute ago (no sweep
/// gap), and two unseen park rows (one already seen).
const PARK_TASK: &str = "task_00000000-0000-4000-8000-0000000000c1";
const PARK_FORM: &str = "form_0b0e1f30-0000-4000-8000-0000000000c1";
const ROW_A: (&str, &str) = (
    "task_00000000-0000-4000-8000-0000000000c2",
    "form_0b0e1f30-0000-4000-8000-0000000000c2",
);
const ROW_B: (&str, &str) = (
    "task_00000000-0000-4000-8000-0000000000c3",
    "form_0b0e1f30-0000-4000-8000-0000000000c3",
);
const ROW_SEEN: (&str, &str) = (
    "task_00000000-0000-4000-8000-0000000000c4",
    "form_0b0e1f30-0000-4000-8000-0000000000c4",
);

fn park_read_set() -> ReadSet {
    let ack = |(task, form): (&str, &str), seen: Option<&str>| {
        json!({
            "task_id": task, "formulation_id": form, "parked_at": "2026-10-08T09:00:00Z",
            "seen_at": seen, "returned_at": null,
            "private": { "from_revision": "3", "source": "sweep" },
        })
    };
    serde_json::from_value(json!({
        "tasks": { PARK_TASK: {
            "id": PARK_TASK, "title": "Call Bob", "details": null, "state": "next",
            "project_id": null, "tag_ids": [], "due_date": null, "priority": "none",
            "waiting_for": null, "waiting_since": null, "order_key": "3",
            "source_capture_ids": [], "created_at": "2026-09-01T09:00:00Z",
            "updated_at": "2026-09-02T09:00:00Z", "completed_at": null, "cancelled_at": null,
            "revision": "4", "consecutive_stalled_formulations": 0,
            "formulation": { "id": PARK_FORM, "started_at": "2026-09-10T09:00:00Z",
                "extended_at": null, "extension_reason": null, "park_floor_at": null },
            "parked": null,
        }},
        "settings": {
            "threshold_days": 14, "review_weekday": 5, "review_time": "16:00",
            "time_zone": "UTC", "onboarded_at": null, "activated_at": "2026-08-01T00:00:00Z",
            "owner_park_floor_at": null, "revision": "2",
            "private": { "last_effective_sweep_at": "2026-10-09T11:59:00Z",
                         "threshold_changed_at": null },
        },
        "park_acks": [ack(ROW_A, None), ack(ROW_B, None), ack(ROW_SEEN, Some("2026-10-08T10:00:00Z"))],
    }))
    .expect("the park read set")
}

// ------------------------------------------------------------------ ownership

#[test]
fn dispatch_026_fr_002_the_samples_cover_every_catalog_command_and_query_kind() {
    let wire: BTreeSet<&str> = sample_commands().keys().copied().collect();
    let catalog: BTreeSet<&str> = CommandType::ALL.iter().map(|t| t.as_str()).collect();
    assert_eq!(catalog.len(), 30);
    assert_eq!(wire, catalog, "one sample per catalog command type");

    let kinds: BTreeSet<QueryKind> = sample_queries().iter().map(query_kind).collect();
    let catalog: BTreeSet<QueryKind> = QueryKind::ALL.into_iter().collect();
    assert_eq!(catalog.len(), 8);
    assert_eq!(kinds, catalog, "one sample per query kind");
    for (sample, kind) in sample_queries().iter().zip(QueryKind::ALL) {
        let tagged = serde_json::to_value(sample).expect("a query serializes");
        assert_eq!(tagged["kind"], kind.as_str());
    }
}

#[test]
fn dispatch_026_fr_002_every_catalog_command_has_the_owner_the_table_names() {
    use CommandFamily::{
        Children, Organize, Park, ReviewDecisions, ReviewSessions, SmartAdd, TaskRules,
    };
    let table: [(&str, CommandFamily); 30] = [
        ("project.create", Organize),
        ("project.update", Organize),
        ("project.archive", Organize),
        ("project.unarchive", Organize),
        ("tag.create", Organize),
        ("tag.update", Organize),
        ("tag.delete", Organize),
        ("task.create", TaskRules),
        ("task.smart_add", SmartAdd),
        ("task.update", TaskRules),
        ("task.tags", Organize),
        ("task.transition", TaskRules),
        ("subtask.create", Children),
        ("subtask.update", Children),
        ("subtask.transition", Children),
        ("comment.create", Children),
        ("comment.update", Children),
        ("review.decide", ReviewDecisions),
        ("review.undo_decision", ReviewDecisions),
        ("review.auto_park", Park),
        ("review.explainer_ack", ReviewSessions),
        ("review.settings", ReviewSessions),
        ("review.parks_ack", Park),
        ("review.session_start", ReviewSessions),
        ("review.session_progress", ReviewSessions),
        ("review.session_finish", ReviewSessions),
        ("review.bulk_release", ReviewDecisions),
        ("review.bulk_undo", ReviewDecisions),
        ("review.consent_grant", ReviewSessions),
        ("review.consent_revoke", ReviewSessions),
    ];
    let samples = sample_commands();
    assert_eq!(table.len(), samples.len());
    for (wire, expected) in table {
        assert_eq!(command_owner(&samples[wire]), Ok(expected), "{wire}");
    }
}

#[test]
fn dispatch_026_fr_002_no_command_is_claimed_by_two_families() {
    let samples = sample_commands();
    assert_eq!(samples.len(), CommandType::ALL.len());
    let mut owned = 0;
    for (wire, command) in &samples {
        let claims = command_claims(command);
        assert!(
            claims.len() <= 1,
            "{wire} is claimed by {} families: {claims:?}",
            claims.len()
        );
        assert_eq!(claims.len(), 1, "{wire}: no catalog command is unowned");
        owned += claims.len();
    }
    assert_eq!(owned, 30, "every catalog command has its one owner");
    // A family is never asked about a command it does not name.
    for family in CommandFamily::ALL {
        let claimed = samples.values().filter(|c| family.handles(c)).count();
        assert!(claimed > 0, "{family:?} owns nothing");
    }
}

#[test]
fn dispatch_026_fr_002_every_query_kind_has_exactly_one_owner() {
    use QueryFamily::{Queries, ReviewSessions};
    let expected = [
        (QueryKind::TaskList, Queries),
        (QueryKind::TaskDetail, Queries),
        (QueryKind::ListCounts, Queries),
        (QueryKind::Projects, Queries),
        (QueryKind::ProjectDisplay, Queries),
        (QueryKind::Tags, Queries),
        (QueryKind::ReviewState, ReviewSessions),
        (QueryKind::ReviewQueue, ReviewSessions),
    ];
    assert_eq!(expected.len(), QueryKind::ALL.len());
    let samples = sample_queries();
    for (kind, family) in expected {
        let sample = samples
            .iter()
            .find(|q| query_kind(q) == kind)
            .unwrap_or_else(|| panic!("no sample for {kind:?}"));
        assert_eq!(query_claims(sample), vec![family], "{}", kind.as_str());
        assert_eq!(query_owner(sample), Ok(family), "{}", kind.as_str());
    }
}

// ------------------------------------------------------------ routing (commands)

#[test]
fn dispatch_026_fr_002_organize_commands_reach_the_organize_family() {
    let read_set = reference_read_set(OWNER_A);
    let project = command(
        "project.create",
        "project_00000000-0000-4000-8000-0000000000b1",
        json!({"name": "Dispatch"}),
        vec![],
    );
    let routed = accepted(dispatch::decide(&read_set, &project, &exec(&[])));
    assert_eq!(entity_types(&routed), BTreeSet::from(["project"]));
    assert_eq!(
        Ok(routed),
        organize::decide(&read_set, &project, &exec(&[])),
        "the routed answer is the family's own"
    );
    // The tag membership edit is organization too, over an oracle task.
    let tags = command(
        "task.tags",
        REF_TASK,
        json!({"add_tag_ids": ["0a6451f3-c09d-50da-880c-97be6e77fb95"], "remove_tag_ids": []}),
        vec![check("task", REF_TASK, 4)],
    );
    let routed = accepted(dispatch::decide(&read_set, &tags, &exec(&[])));
    assert_eq!(entity_types(&routed), BTreeSet::from(["task"]));
    assert_eq!(Ok(routed), organize::decide(&read_set, &tags, &exec(&[])));
}

#[test]
fn dispatch_026_fr_002_task_commands_reach_the_task_rules() {
    let read_set = reference_read_set(OWNER_A);
    let create = command(
        "task.create",
        "task_00000000-0000-4000-8000-0000000000b2",
        json!({"title": "Buy milk"}),
        vec![],
    );
    let routed = accepted(dispatch::decide(&read_set, &create, &exec(&[])));
    assert_eq!(entity_types(&routed), BTreeSet::from(["task"]));
    assert_eq!(
        Ok(routed),
        task_rules::decide(&read_set, &create, &exec(&[]))
    );

    let update = command(
        "task.update",
        REF_TASK,
        json!({"details": "Renamed by dispatch"}),
        vec![check("task", REF_TASK, 4)],
    );
    let routed = accepted(dispatch::decide(&read_set, &update, &exec(&[])));
    assert_eq!(
        Ok(routed),
        task_rules::decide(&read_set, &update, &exec(&[]))
    );
}

#[test]
fn dispatch_026_fr_002_child_commands_reach_the_children_family() {
    let read_set = reference_read_set(OWNER_A);
    let subtask = command(
        "subtask.create",
        "subtask_00000000-0000-4000-8000-0000000000b3",
        json!({"task_id": REF_TASK, "title": "Dispatch the mail"}),
        vec![],
    );
    let routed = accepted(dispatch::decide(&read_set, &subtask, &exec(&[])));
    assert_eq!(entity_types(&routed), BTreeSet::from(["subtask"]));
    assert_eq!(
        Ok(routed),
        children::decide(&read_set, &subtask, &exec(&[]))
    );

    let comment = command(
        "comment.create",
        "comment_00000000-0000-4000-8000-0000000000b4",
        json!({"task_id": REF_TASK, "body": "Sent"}),
        vec![],
    );
    let routed = accepted(dispatch::decide(&read_set, &comment, &exec(&[])));
    assert_eq!(entity_types(&routed), BTreeSet::from(["comment"]));
    assert_eq!(
        Ok(routed),
        children::decide(&read_set, &comment, &exec(&[]))
    );
}

#[test]
fn dispatch_026_fr_002_smart_add_reaches_its_family_and_binds_the_alias() {
    let read_set = reference_read_set(OWNER_A);
    let proposed = "project_00000000-0000-4000-8000-0000000000b5";
    let smart = command(
        "task.smart_add",
        "task_00000000-0000-4000-8000-0000000000b6",
        json!({"title": "Call Ann",
               "project": {"name": "Brand new project", "proposed_id": proposed}}),
        vec![],
    );
    let routed = accepted(dispatch::decide(&read_set, &smart, &exec(&[])));
    assert_eq!(entity_types(&routed), BTreeSet::from(["project", "task"]));
    assert_eq!(routed.result.id_bindings.len(), 1, "the alias is bound");
    assert_eq!(Ok(routed), smart_add::decide(&read_set, &smart, &exec(&[])));
}

#[test]
fn dispatch_026_fr_016_review_decisions_reach_their_family() {
    let read_set = review_read_set();
    let task = "task_00000000-0000-4000-8000-000000000001";
    let decide = command(
        "review.decide",
        task,
        json!({"decision_id": "decision_00000000-0000-4000-8000-000000000001", "type": "complete"}),
        vec![check("task", task, 1)],
    );
    let routed = accepted(dispatch::decide(&read_set, &decide, &exec(&[])));
    assert!(entity_types(&routed).contains(&"review_decision"));
    assert!(entity_types(&routed).contains(&"task"));
    assert_eq!(
        Ok(routed),
        review_decisions::decide(&read_set, &decide, &exec(&[]))
    );
}

#[test]
fn dispatch_026_fr_016_review_sessions_settings_and_consent_reach_their_family() {
    let read_set = ReadSet::default();
    let start = command(
        "review.session_start",
        "review_0b0e1f30-0000-4000-8000-0000000000a1",
        json!({"mode": "quick", "entry": "list", "origin": "ios", "skip_steps": ["wins"],
               "replace_open": true}),
        vec![],
    );
    let routed = accepted(dispatch::decide(&read_set, &start, &exec(&[])));
    assert_eq!(entity_types(&routed), BTreeSet::from(["review_session"]));
    assert_eq!(
        Ok(routed),
        review_sessions::decide(&read_set, &start, &exec(&[]))
    );

    let grant = command(
        "review.consent_grant",
        "openai",
        json!({"provider": "openai", "consent_text_version": 1}),
        vec![],
    );
    let inputs = serde_json::from_value::<ExecutionInputs>(json!({
        "rule_version": 1, "now": NOW, "time_zone": "UTC", "origin": "device",
        "actor_id": "actor-example", "authoritative": true, "allocated_ids": [],
        "policy": { "weekly_review": true, "navigator_provider": "openai",
                    "navigator_available": true, "consent_text_version": 1 },
    }))
    .expect("inputs with a provider");
    assert_eq!(
        dispatch::decide(&read_set, &grant, &inputs),
        review_sessions::decide(&read_set, &grant, &inputs),
        "consent is decided by the sessions family, whatever it answers"
    );
}

#[test]
fn dispatch_026_fr_013_auto_park_reaches_the_park_family() {
    let read_set = park_read_set();
    let parked = command(
        "review.auto_park",
        PARK_TASK,
        json!({ "formulation_id": PARK_FORM }),
        vec![],
    );
    let routed = accepted(dispatch::decide(&read_set, &parked, &exec(&[])));
    assert_eq!(routed.result.applied, Some(true));
    assert_eq!(
        entity_types(&routed),
        BTreeSet::from(["review_park_ack", "review_settings", "task"])
    );
    assert_eq!(
        Ok(routed.clone()),
        park::decide(&read_set, &parked, &exec(&[])),
        "the routed answer is the family's own"
    );
    // Through the envelope path: typed, then routed to the same family.
    let wire = envelope(
        "review.auto_park",
        PARK_TASK,
        json!({ "formulation_id": PARK_FORM }),
        json!([]),
    );
    assert_eq!(
        dispatch::decide_envelope(&read_set, &wire, &NoReceipts, &exec(&[])),
        Ok(routed.clone())
    );

    // A formulation the task no longer holds is an accepted `applied: false`.
    let other = command(
        "review.auto_park",
        PARK_TASK,
        json!({ "formulation_id": "form_0b0e1f30-0000-4000-8000-0000000000ff" }),
        vec![],
    );
    let declined = accepted(dispatch::decide(&read_set, &other, &exec(&[])));
    assert_eq!(declined.result.applied, Some(false));
    assert!(
        !entity_types(&declined).contains("task"),
        "no task is written"
    );
    assert_eq!(Ok(declined), park::decide(&read_set, &other, &exec(&[])));

    // A replay over the committed state changes nothing.
    let after = support::commit(&read_set, &routed);
    let replay = accepted(dispatch::decide(&after, &parked, &exec(&[])));
    assert_eq!(replay.outcome, ChangeOutcome::NoOp);
    assert_eq!(replay.result.applied, Some(false));
    assert!(replay.changes.is_empty());
}

#[test]
fn dispatch_026_fr_013_the_oracle_auto_park_vectors_hold_through_the_dispatch() {
    let mut ran = 0;
    for vector in cases(support::formulation(), "transitions")
        .iter()
        .filter(|vector| vector["event"]["type"] == "auto_park")
    {
        let id = text(vector, "id");
        let read_set: ReadSet =
            serde_json::from_value(support::auto_park_read_set(vector, "task_vector"))
                .unwrap_or_else(|e| panic!("{id}: {e}"));
        let inputs = exec_at(text(vector, "now"), &[]);
        let parked = command(
            "review.auto_park",
            "task_vector",
            json!({ "formulation_id": support::VECTOR_FORMULATION }),
            vec![],
        );
        let routed = dispatch::decide(&read_set, &parked, &inputs);
        assert_eq!(routed, park::decide(&read_set, &parked, &inputs), "{id}");
        let set = accepted(routed);
        let task = set.changes.iter().find_map(|change| match change {
            DomainChange::Upsert(Record::Task(task)) => Some(task),
            _ => None,
        });
        if vector["expect"]["applied"] == json!(false) {
            assert_eq!(set.result.applied, Some(false), "{id}");
            assert!(task.is_none(), "{id}: a declined park writes no task");
        } else {
            assert_eq!(set.result.applied, Some(true), "{id}");
            let task = task.unwrap_or_else(|| panic!("{id}: no parked task"));
            assert_eq!(task.state, TaskState::Someday, "{id}");
            let revision = vector["expect"]["revision"].as_u64().expect("a revision");
            assert_eq!(task.revision, Counter::from(revision), "{id}");
            assert!(task.formulation.is_none(), "{id}: the clock is closed");
        }
        ran += 1;
    }
    assert_eq!(ran, 7, "every auto_park vector ran");
}

#[test]
fn dispatch_026_fr_015_parks_ack_reaches_the_park_family() {
    let read_set = park_read_set();
    let key = |(task, form): (&str, &str)| json!({ "task_id": task, "formulation_id": form });
    let ack = command(
        "review.parks_ack",
        "scope-example",
        json!({ "items": [key(ROW_A), key(ROW_A), key(ROW_SEEN),
            key(("task_unknown", ROW_A.1))] }),
        vec![],
    );
    let routed = accepted(dispatch::decide(&read_set, &ack, &exec(&[])));
    assert_eq!(entity_types(&routed), BTreeSet::from(["review_park_ack"]));
    assert_eq!(
        routed.changes.len(),
        1,
        "marked once; seen and unknown skipped"
    );
    assert_eq!(
        Ok(routed.clone()),
        park::decide(&read_set, &ack, &exec(&[]))
    );

    // Idempotent by state: the committed rows mark nothing the second time.
    let after = support::commit(&read_set, &routed);
    let again = accepted(dispatch::decide(
        &after,
        &ack,
        &exec_at("2026-10-09T12:05:00Z", &[]),
    ));
    assert_eq!(again, ChangeSet::no_op());

    // An empty request is an accepted no-op.
    let empty = command(
        "review.parks_ack",
        "scope-example",
        json!({ "items": [] }),
        vec![],
    );
    assert_eq!(
        dispatch::decide(&read_set, &empty, &exec(&[])),
        Ok(ChangeSet::no_op())
    );
}

#[test]
fn dispatch_026_fr_002_no_catalog_command_is_unowned_and_a_foreign_one_is_refused_alike() {
    let read_set = reference_read_set(OWNER_A);
    // The unowned refusal is no longer reachable by a catalog command ...
    for (wire, command) in sample_commands() {
        assert!(command_owner(&command).is_ok(), "{wire}");
    }
    // ... and is the very refusal a family gives a command of another family.
    let foreign = command("tag.delete", REF_TASK, json!({}), vec![]);
    for family_refusal in [
        park::decide(&read_set, &foreign, &exec(&[])),
        review_sessions::decide(&read_set, &foreign, &exec(&[])),
        review_decisions::decide(&read_set, &foreign, &exec(&[])),
    ] {
        let refusal = family_refusal.expect_err("a foreign command is refused");
        assert_eq!(refusal, unowned());
        assert_eq!(refusal.reason, Reason::InvalidPayload);
        assert_eq!(refusal.field.as_deref(), Some("type"));
    }
}

// ------------------------------------------------------------ the envelope path

#[test]
fn dispatch_026_fr_002_an_envelope_is_typed_then_routed() {
    let read_set = reference_read_set(OWNER_A);
    let envelope = envelope(
        "task.update",
        REF_TASK,
        json!({"details": "From an envelope"}),
        json!([check("task", REF_TASK, 4)]),
    );
    let routed = dispatch::decide_envelope(&read_set, &envelope, &NoReceipts, &exec(&[]));
    let typed = DomainCommand::from_envelope(&envelope, &NoReceipts).expect("typed");
    assert_eq!(routed, task_rules::decide(&read_set, &typed, &exec(&[])));
    assert!(routed.is_ok());

    // The revision check is the family's: a stale one changes nothing.
    let stale = self::envelope(
        "task.update",
        REF_TASK,
        json!({"details": "Stale"}),
        json!([check("task", REF_TASK, 1)]),
    );
    let refusal = dispatch::decide_envelope(&read_set, &stale, &NoReceipts, &exec(&[]))
        .expect_err("a stale revision is refused");
    assert_eq!(refusal.reason, Reason::RevisionConflict);
}

#[test]
fn dispatch_026_fr_012_envelope_refusals_precede_routing() {
    let read_set = reference_read_set(OWNER_A);
    // A version this build does not execute is refused before any family.
    let mut future = envelope("task.update", REF_TASK, json!({"details": "x"}), json!([]));
    future.envelope.command_version = 2;
    let refusal = dispatch::decide_envelope(&read_set, &future, &NoReceipts, &exec(&[]))
        .expect_err("an unsupported version is refused");
    assert_eq!(refusal.reason, Reason::UnsupportedCommandVersion);
    // An unknown payload field is refused by the typing, before any family.
    let unknown = envelope("task.update", REF_TASK, json!({"nope": 1}), json!([]));
    let refusal = dispatch::decide_envelope(&read_set, &unknown, &NoReceipts, &exec(&[]))
        .expect_err("an unknown field is refused");
    assert_eq!(refusal.reason, Reason::InvalidPayload);
}

#[test]
fn dispatch_026_fr_002_a_dependency_not_yet_receipted_is_pending_then_resolves() {
    let read_set = review_read_set();
    let task = "task_00000000-0000-4000-8000-000000000001";
    let predecessor = "01900000-0000-4000-8000-000000000000";
    let after = json!([{"after_command": {
        "command_id": predecessor, "entity_type": "task", "entity_id": task }}]);
    let envelope = match decode_command(&envelope_json_after(
        "task.transition",
        task,
        json!({"action": "complete"}),
        after,
        &[predecessor],
    )) {
        Ok(Decoded::Executable(envelope)) => envelope,
        other => panic!("task.transition did not decode: {other:?}"),
    };

    let pending = dispatch::decide_envelope(&read_set, &envelope, &NoReceipts, &exec(&[]))
        .expect_err("the predecessor has no receipt yet");
    assert_eq!(pending.reason, Reason::DependencyPending);

    let receipt: Receipt = serde_json::from_value(json!({
        "command_id": predecessor, "outcome": "accepted", "has_changes": true,
        "result_redacted": false, "result": null, "error": null, "id_bindings": [],
        "scope_id": "scope-example", "server_now": "2026-10-08T10:00:01Z",
        "server_generation": "generation-example", "commit_seq": "908",
        "result_versions": [{"entity_type": "task", "record_key": [task],
            "record_version": "24", "edit_revision": "1"}],
        "correlation_id": "opaque-support-reference",
    }))
    .expect("a receipt");
    let receipts = [receipt];
    let routed = dispatch::decide_envelope(&read_set, &envelope, receipts.as_slice(), &exec(&[]));
    let set = accepted(routed);
    assert_eq!(entity_types(&set), BTreeSet::from(["task"]));

    // A receipt that recorded another revision decides against that revision.
    let moved: Receipt = {
        let mut raw = serde_json::to_value(&receipts[0]).unwrap();
        raw["result_versions"][0]["edit_revision"] = json!("9");
        serde_json::from_value(raw).unwrap()
    };
    let refusal = dispatch::decide_envelope(&read_set, &envelope, &[moved][..], &exec(&[]))
        .expect_err("the resolved revision is stale");
    assert_eq!(refusal.reason, Reason::RevisionConflict);
}

// --------------------------------------------------------------- routing (queries)

#[test]
fn dispatch_026_fr_009_task_reads_over_the_oracle_store_are_the_query_familys() {
    let read_set = reference_read_set(OWNER_A);
    let inputs = query_inputs(true);
    let mut ran = 0;
    for query in sample_queries() {
        if query_owner(&query) != Ok(QueryFamily::Queries) {
            continue;
        }
        let routed = dispatch::query(&read_set, &query, &inputs);
        assert!(
            routed.is_ok(),
            "{}: {routed:?}",
            query_kind(&query).as_str()
        );
        assert_eq!(routed, queries::query(&read_set, &query, &inputs));
        ran += 1;
    }
    assert_eq!(ran, 6, "every task, project and tag read ran");

    // Every task of the oracle store is read back through the dispatch.
    let mut details = 0;
    for task_id in read_set.tasks.keys() {
        let query = Query::TaskDetail {
            task_id: task_id.clone(),
        };
        let routed = dispatch::query(&read_set, &query, &inputs).expect("a stored task");
        let QueryResult::TaskDetail(view) = routed else {
            panic!("not a task detail")
        };
        assert_eq!(view.id, *task_id);
        details += 1;
    }
    assert_eq!(details, read_set.tasks.len());
    assert!(details > 0);
}

#[test]
fn dispatch_026_fr_016_review_reads_are_answered_before_the_task_queries() {
    let read_set = reference_read_set(OWNER_A);
    let state = Query::ReviewState {};
    // `queries` refuses a Review read, so an answer proves the Review family
    // was asked first.
    assert_eq!(
        queries::query(&read_set, &state, &query_inputs(true))
            .expect_err("the task queries do not answer Review")
            .reason,
        Reason::InvalidValue
    );
    let routed = dispatch::query(&read_set, &state, &query_inputs(true));
    assert!(
        matches!(routed, Ok(QueryResult::ReviewState(_))),
        "{routed:?}"
    );
    assert_eq!(
        routed,
        review_sessions::query(&read_set, &state, &query_inputs(true))
    );
    // The flag gate is the Review family's, not a placeholder.
    assert_eq!(
        dispatch::query(&read_set, &state, &query_inputs(false))
            .expect_err("Review is off")
            .reason,
        Reason::ReviewUnavailable
    );
    let queue: Query =
        serde_json::from_value(json!({"kind": "review_queue", "step": "wins", "session_id": null}))
            .unwrap();
    assert_eq!(
        dispatch::query(&read_set, &queue, &query_inputs(false))
            .expect_err("Review is off")
            .reason,
        Reason::ReviewUnavailable
    );
}

// ------------------------------------------------------------------------- purity

#[test]
fn dispatch_026_fr_011_the_same_inputs_give_the_same_answer() {
    let read_set = reference_read_set(OWNER_A);
    let update = command(
        "task.update",
        REF_TASK,
        json!({"details": "Twice"}),
        vec![check("task", REF_TASK, 4)],
    );
    let before = read_set.clone();
    let first = dispatch::decide(&read_set, &update, &exec(&[]));
    let second = dispatch::decide(&read_set, &update, &exec(&[]));
    assert_eq!(first, second);
    assert_eq!(read_set, before, "a decision never edits the read set");
    // Time is only an input: the same command at another instant is another answer.
    let later = serde_json::from_value::<ExecutionInputs>(json!({
        "rule_version": 1, "now": "2026-10-10T12:00:00Z", "time_zone": "UTC",
        "origin": "device", "actor_id": "actor-example", "authoritative": true,
        "allocated_ids": [],
        "policy": { "weekly_review": true, "navigator_provider": null,
                    "navigator_available": false, "consent_text_version": 1 },
    }))
    .unwrap();
    assert_ne!(first, dispatch::decide(&read_set, &update, &later));
}
