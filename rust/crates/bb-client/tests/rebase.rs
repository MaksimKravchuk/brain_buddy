//! The explicit first-sign-in merge (spec 026, T044, FR-003): account-less local records become
//! new owner-bound commands in the transaction that links the workspace, with stable ids,
//! dependencies, and nothing half-done after a crash.

use bb_client::{
    AccountBinding, ExecuteContext, ExecuteError, ExecuteRequest, IdSource, MergeOutcome,
    OpenOptions, Store, establish_account_less_with, execute, link_and_merge_with, replay,
    send_candidates,
};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{Precondition, RevisionPrecondition};
use bb_protocol::wire::{CommandId, Counter, Id, Instant};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

const WORKSPACE: &str = "local-1";
const NOW: &str = "2026-10-10T09:00:00Z";

struct SeqIds(u64);

impl IdSource for SeqIds {
    fn uuid(&mut self) -> std::io::Result<String> {
        self.0 += 1;
        Ok(format!("00000000-0000-4000-8000-{:012x}", self.0))
    }
}

fn open(name: &str) -> Store {
    let directory = std::env::temp_dir().join(format!("bb-rebase-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    let path: PathBuf = directory.join("store.sqlite3");
    Store::open(&OpenOptions {
        path,
        workspace_id: WORKSPACE.to_string(),
        busy_timeout: Duration::from_millis(2_000),
    })
    .expect("open")
}

fn context(now: &str) -> ExecuteContext {
    ExecuteContext {
        now: Instant::parse(now).unwrap(),
        time_zone: ZoneName::new("UTC").unwrap(),
        actor_id: ActorId::parse("actor-local").unwrap(),
        policy: Policy {
            weekly_review: true,
            navigator_provider: None,
            navigator_available: false,
            consent_text_version: 1,
        },
    }
}

fn binding() -> AccountBinding {
    AccountBinding {
        account: Id::parse("account-a").unwrap(),
        scope: Id::parse("account-a").unwrap(),
        device: Id::parse("device-1").unwrap(),
    }
}

fn cmd(n: u64) -> CommandId {
    CommandId::parse(format!("01900000-0000-4000-8000-{n:012}")).unwrap()
}

fn shown(kind: EntityType, id: &str, revision: &str) -> Precondition {
    Precondition::Revision(RevisionPrecondition {
        entity_type: kind,
        entity_id: Id::parse(id).unwrap(),
        edit_revision: Counter::parse(revision).unwrap(),
    })
}

struct Local {
    store: Store,
    ids: SeqIds,
    next: u64,
}

impl Local {
    /// An account-less workspace, as the app leaves it after the explicit choice.
    fn new(name: &str) -> Self {
        let mut store = open(name);
        establish_account_less_with(&mut store, || Ok(())).expect("account-less");
        Self {
            store,
            ids: SeqIds(0),
            next: 0,
        }
    }

    fn run(
        &mut self,
        kind: CommandType,
        entity: Option<&str>,
        payload: Value,
        pre: Vec<Precondition>,
        at: &str,
    ) -> String {
        self.next += 1;
        let request = ExecuteRequest {
            command_id: cmd(self.next),
            command_type: kind,
            entity_id: entity.map(|id| Id::parse(id).unwrap()),
            payload: payload.as_object().unwrap().clone(),
            preconditions: pre,
            depends_on: Vec::new(),
            admission_tokens: Vec::new(),
            context: context(at),
        };
        execute(&mut self.store, &mut self.ids, &request)
            .expect("execute")
            .entity_id
            .as_str()
            .to_string()
    }

    /// Two tags, two projects (one archived), five tasks, two subtasks and a comment.
    fn populate(&mut self) -> Ids {
        let tag = self.run(
            CommandType::TagCreate,
            None,
            json!({ "name": "phone" }),
            vec![],
            "2026-10-01T09:00:00Z",
        );
        let project = self.run(
            CommandType::ProjectCreate,
            None,
            json!({ "name": "Home", "color": "#0EA5E9" }),
            vec![],
            "2026-10-01T10:00:00Z",
        );
        let old = self.run(
            CommandType::ProjectCreate,
            None,
            json!({ "name": "Old" }),
            vec![],
            "2026-10-01T11:00:00Z",
        );
        let a = self.run(
            CommandType::TaskCreate,
            None,
            json!({ "title": "Call the plumber", "details": "Before Friday", "state": "next",
                    "project_id": project, "tag_ids": [tag], "priority": "high", "due_date": "2026-10-20" }),
            vec![],
            "2026-10-02T09:00:00Z",
        );
        let b = self.run(
            CommandType::TaskCreate,
            None,
            json!({ "title": "Waiting on the bank", "state": "waiting", "waiting_for": "the bank" }),
            vec![],
            "2026-10-02T10:00:00Z",
        );
        let c = self.run(
            CommandType::TaskCreate,
            None,
            json!({ "title": "Done already" }),
            vec![],
            "2026-10-02T11:00:00Z",
        );
        self.run(
            CommandType::TaskTransition,
            Some(&c),
            json!({ "action": "complete" }),
            vec![shown(EntityType::Task, &c, "1")],
            "2026-10-03T09:00:00Z",
        );
        let d = self.run(
            CommandType::TaskCreate,
            None,
            json!({ "title": "Dropped" }),
            vec![],
            "2026-10-02T12:00:00Z",
        );
        self.run(
            CommandType::TaskTransition,
            Some(&d),
            json!({ "action": "cancel" }),
            vec![shown(EntityType::Task, &d, "1")],
            "2026-10-03T10:00:00Z",
        );
        let sub1 = self.run(
            CommandType::SubtaskCreate,
            None,
            json!({ "task_id": a, "title": "Find the number" }),
            vec![],
            "2026-10-02T09:30:00Z",
        );
        self.run(
            CommandType::SubtaskTransition,
            Some(&sub1),
            json!({ "task_id": a, "action": "complete" }),
            vec![shown(EntityType::Subtask, &sub1, "1")],
            "2026-10-02T09:40:00Z",
        );
        self.run(
            CommandType::SubtaskCreate,
            None,
            json!({ "task_id": a, "title": "Book a slot" }),
            vec![],
            "2026-10-02T09:45:00Z",
        );
        self.run(
            CommandType::CommentCreate,
            None,
            json!({ "task_id": a, "body": "Left a message" }),
            vec![],
            "2026-10-02T09:50:00Z",
        );
        self.run(
            CommandType::ProjectArchive,
            Some(&old),
            json!({}),
            vec![shown(EntityType::Project, &old, "1")],
            "2026-10-04T09:00:00Z",
        );
        Ids {
            tag,
            project,
            old,
            a,
            b,
            c,
            d,
        }
    }
}

#[allow(dead_code)]
struct Ids {
    tag: String,
    project: String,
    old: String,
    a: String,
    b: String,
    c: String,
    d: String,
}

/// `(record type, key) -> body`, visible or confirmed.
fn records(store: &mut Store, table: &str) -> BTreeMap<(String, String), Value> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(&format!(
                "SELECT record_type, record_key, body FROM {table}"
            ))?;
            let rows = statement.query_map([], |row| {
                let body: Vec<u8> = row.get(2)?;
                Ok((
                    (row.get(0)?, row.get(1)?),
                    serde_json::from_slice::<Value>(&body).unwrap(),
                ))
            })?;
            rows.collect()
        })
        .unwrap()
}

/// The user-facing facts of the visible records: what must survive the merge.
fn facts(store: &mut Store) -> BTreeMap<(String, String), Value> {
    records(store, "visible_records")
        .into_iter()
        .map(|(key, body)| {
            let pick = |names: &[&str]| -> Value {
                names
                    .iter()
                    .map(|n| {
                        (
                            (*n).to_string(),
                            body.get(*n).cloned().unwrap_or(Value::Null),
                        )
                    })
                    .collect::<serde_json::Map<_, _>>()
                    .into()
            };
            let fact = match key.0.as_str() {
                "task" => pick(&[
                    "title",
                    "details",
                    "state",
                    "project_id",
                    "tag_ids",
                    "due_date",
                    "priority",
                    "waiting_for",
                ]),
                "project" => pick(&["name", "color", "state"]),
                "tag" => pick(&["name", "state"]),
                "subtask" => pick(&["task_id", "title", "state"]),
                "comment" => pick(&["task_id", "body"]),
                _ => body,
            };
            (key, fact)
        })
        .collect()
}

fn outbox(store: &mut Store) -> Vec<(String, String, Value)> {
    store
        .read(|tx| {
            let mut statement =
                tx.prepare("SELECT command_id, state, envelope FROM outbox ORDER BY local_seq")?;
            let rows = statement.query_map([], |row| {
                let envelope: Vec<u8> = row.get(2)?;
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    serde_json::from_slice(&envelope).unwrap(),
                ))
            })?;
            rows.collect()
        })
        .unwrap()
}

fn dependencies(store: &mut Store) -> BTreeMap<String, BTreeSet<String>> {
    store
        .read(|tx| {
            let mut statement =
                tx.prepare("SELECT command_id, depends_on FROM outbox_dependencies")?;
            let rows = statement.query_map([], |row| {
                Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
            })?;
            let mut map: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
            for row in rows {
                let (command, dependency) = row?;
                map.entry(command).or_default().insert(dependency);
            }
            Ok(map)
        })
        .unwrap()
}

fn queued(store: &mut Store) -> Vec<(String, Value)> {
    outbox(store)
        .into_iter()
        .filter(|(_, state, _)| state == "queued")
        .map(|(id, _, envelope)| (id, envelope))
        .collect()
}

fn merged(outcome: MergeOutcome) -> (u64, u64) {
    match outcome {
        MergeOutcome::Merged {
            records, commands, ..
        } => (records, commands),
        other => panic!("expected a merge, got {other:?}"),
    }
}

#[test]
fn merge_026_fr_003_every_local_record_becomes_a_queued_command_and_stays_visible() {
    let mut local = Local::new("all");
    let ids = local.populate();
    let before = facts(&mut local.store);
    let original_clock = records(&mut local.store, "visible_records")
        [&("task".to_string(), format!("[\"{}\"]", ids.a))]["formulation"]
        .clone();
    let completed_before = outbox(&mut local.store).len();

    let outcome =
        link_and_merge_with(&mut local.store, &binding(), &context(NOW), || Ok(())).unwrap();
    // 1 tag + 2 projects + 4 tasks + 2 subtasks + 1 comment; plus complete, cancel, archive and
    // the subtask completion.
    let (merged_records, commands) = merged(outcome);
    assert_eq!((merged_records, commands), (10, 15));

    // The same facts, now held by pending commands rather than by the confirmed base.
    assert_eq!(facts(&mut local.store), before);
    assert!(records_by_type(&mut local.store, "confirmed_records").is_empty());

    // The account-less history stays; the new commands are queued, owner-bound and unsent.
    let all = outbox(&mut local.store);
    assert_eq!(all.len(), completed_before + 15);
    let queue = queued(&mut local.store);
    assert_eq!(queue.len(), 15);
    for (_, envelope) in &queue {
        assert_eq!(envelope["scope_id"], "account-a");
        assert_eq!(envelope["device_id"], "device-1");
    }
    let sent: i64 = local
        .store
        .read(|tx| {
            tx.query_row("SELECT COUNT(*) FROM outbox WHERE ever_sent = 1", [], |r| {
                r.get(0)
            })
        })
        .unwrap();
    assert_eq!(sent, 0);

    // Each record keeps its own instants, and a Next task carries the formulation id its
    // clock started with in the envelope the server will read.
    let visible = records(&mut local.store, "visible_records");
    let task = |id: &str| visible[&("task".to_string(), format!("[\"{id}\"]"))].clone();
    assert_eq!(task(&ids.a)["created_at"], "2026-10-02T09:00:00Z");
    assert_eq!(task(&ids.c)["completed_at"], "2026-10-03T09:00:00Z");
    // The Next task is created at its creation instant and moved to Next at the instant its
    // clock started, under the clock's own formulation id: nothing of the clock restarts.
    let start_a = queue
        .iter()
        .find(|(_, e)| e["type"] == "task.transition" && e["entity_id"] == ids.a.as_str())
        .unwrap();
    assert_eq!(
        start_a.1["payload"]["new_formulation_id"],
        task(&ids.a)["formulation"]["id"]
    );
    assert_eq!(
        start_a.1["issued_at"],
        task(&ids.a)["formulation"]["started_at"]
    );
    assert_eq!(task(&ids.a)["formulation"], original_clock);

    // Dependencies: a task waits for its project and tag, a finish for its creation, a
    // subtask for its task.
    let deps = dependencies(&mut local.store);
    let by_entity = |kind: &str, entity: &str, last: bool| -> String {
        let hits: Vec<&(String, Value)> = queue
            .iter()
            .filter(|(_, e)| e["type"] == kind && e["entity_id"] == entity)
            .collect();
        (if last { hits.last() } else { hits.first() })
            .unwrap()
            .0
            .clone()
    };
    let task_a = by_entity("task.create", &ids.a, false);
    let a_deps = deps.get(&task_a).cloned().unwrap_or_default();
    assert!(a_deps.contains(&by_entity("project.create", &ids.project, false)));
    assert!(a_deps.contains(&by_entity("tag.create", &ids.tag, false)));
    let finish_c = by_entity("task.transition", &ids.c, true);
    assert!(deps[&finish_c].contains(&by_entity("task.create", &ids.c, false)));
    let archive = by_entity("project.archive", &ids.old, true);
    assert!(deps[&archive].contains(&by_entity("project.create", &ids.old, false)));

    // Only roots are sendable at first, and only once the epoch is registered.
    assert!(send_candidates(&mut local.store).unwrap().is_empty());
    local
        .store
        .write(|tx| tx.execute("UPDATE sync_meta SET device_epoch_state = 'active'", []))
        .unwrap();
    let roots: BTreeSet<String> = send_candidates(&mut local.store)
        .unwrap()
        .iter()
        .map(|c| c.as_str().to_string())
        .collect();
    assert!(!roots.is_empty());
    for root in &roots {
        assert!(
            deps.get(root).is_none_or(BTreeSet::is_empty),
            "{root} has a dependency yet is sendable"
        );
    }
    assert!(!roots.contains(&task_a));
}

fn records_by_type(store: &mut Store, table: &str) -> BTreeMap<(String, String), Value> {
    records(store, table)
        .into_iter()
        .filter(|((kind, _), _)| {
            ["task", "project", "tag", "subtask", "comment"].contains(&kind.as_str())
        })
        .collect()
}

#[test]
fn merge_026_fr_003_command_ids_follow_the_record_so_a_retry_dedupes() {
    let mut first = Local::new("ids-a");
    first.populate();
    let mut second = Local::new("ids-b");
    second.populate();

    let a = merged(
        link_and_merge_with(&mut first.store, &binding(), &context(NOW), || Ok(())).unwrap(),
    );
    let b = merged(
        link_and_merge_with(&mut second.store, &binding(), &context(NOW), || Ok(())).unwrap(),
    );
    assert_eq!(a, b);
    let ids = |store: &mut Store| -> Vec<String> {
        queued(store).into_iter().map(|(id, _)| id).collect()
    };
    assert_eq!(
        ids(&mut first.store),
        ids(&mut second.store),
        "the same record maps to the same command"
    );
    for id in ids(&mut first.store) {
        assert_eq!(id.as_bytes()[14], b'5', "name-based layout: {id}");
    }

    // A retry after the commit is recognised and queues nothing again.
    let count = outbox(&mut first.store).len();
    assert_eq!(
        link_and_merge_with(&mut first.store, &binding(), &context(NOW), || Ok(())).unwrap(),
        MergeOutcome::AlreadyLinked
    );
    assert_eq!(outbox(&mut first.store).len(), count);
    // Another owner never takes the workspace over.
    let other = AccountBinding {
        account: Id::parse("account-b").unwrap(),
        ..binding()
    };
    assert_eq!(
        link_and_merge_with(&mut first.store, &other, &context(NOW), || Ok(())).unwrap(),
        MergeOutcome::OtherAccount
    );
}

#[test]
fn merge_026_fr_003_a_crash_before_the_commit_leaves_the_account_less_workspace_exactly_as_it_was()
{
    let mut local = Local::new("crash");
    local.populate();
    let facts_before = facts(&mut local.store);
    let outbox_before = outbox(&mut local.store);
    let confirmed_before = records(&mut local.store, "confirmed_records");

    let crashed = link_and_merge_with(&mut local.store, &binding(), &context(NOW), || {
        Err(ExecuteError::Cancelled)
    });
    assert_eq!(crashed, Err(ExecuteError::Cancelled));

    assert_eq!(facts(&mut local.store), facts_before);
    assert_eq!(outbox(&mut local.store), outbox_before);
    assert_eq!(
        records(&mut local.store, "confirmed_records"),
        confirmed_before
    );
    let (state, account, checkpoint): (String, Option<String>, Option<Vec<u8>>) = local
        .store
        .read(|tx| {
            tx.query_row(
                "SELECT account_link_state, account_id, link_checkpoint FROM sync_meta",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
        })
        .unwrap();
    assert_eq!(
        (state.as_str(), account, checkpoint),
        ("account_less", None, None)
    );

    // The retry merges once, and the checkpoint names what was included.
    let (records_merged, commands) = merged(
        link_and_merge_with(&mut local.store, &binding(), &context(NOW), || Ok(())).unwrap(),
    );
    let checkpoint: Vec<u8> = local
        .store
        .read(|tx| tx.query_row("SELECT link_checkpoint FROM sync_meta", [], |r| r.get(0)))
        .unwrap();
    let checkpoint: Value = serde_json::from_slice(&checkpoint).unwrap();
    assert_eq!(
        (
            checkpoint["records"].as_u64(),
            checkpoint["commands"].as_u64()
        ),
        (Some(records_merged), Some(commands))
    );
    assert_eq!(checkpoint["account"], "account-a");
}

#[test]
fn merge_026_fr_003_local_work_survives_a_replay_over_another_base() {
    let mut local = Local::new("replay");
    local.populate();
    let before = facts(&mut local.store);
    merged(link_and_merge_with(&mut local.store, &binding(), &context(NOW), || Ok(())).unwrap());
    let queue: Vec<String> = queued(&mut local.store)
        .into_iter()
        .map(|(id, _)| id)
        .collect();

    // Another device's record lands in the confirmed base; replay rebuilds the projection from
    // that base and the queue alone.
    local
        .store
        .write(|tx| {
            tx.execute("DELETE FROM visible_records", [])?;
            tx.execute("UPDATE sync_meta SET projection_stale = 1", [])
        })
        .unwrap();
    let replayed = replay(&mut local.store, &context(NOW)).unwrap();
    assert_eq!(
        replayed
            .applied
            .iter()
            .map(|c| c.as_str().to_string())
            .collect::<Vec<_>>(),
        queue
    );
    assert!(replayed.rejected.is_empty() && replayed.blocked.is_empty());
    assert_eq!(
        facts(&mut local.store),
        before,
        "the projection is rebuildable from the queue"
    );
}

#[test]
fn merge_026_fr_003_an_empty_workspace_links_with_nothing_to_queue() {
    let mut local = Local::new("empty");
    assert_eq!(
        link_and_merge_with(&mut local.store, &binding(), &context(NOW), || Ok(())).unwrap(),
        MergeOutcome::Merged {
            records: 0,
            commands: 0,
            review_records_kept_local: 0
        }
    );
    assert!(queued(&mut local.store).is_empty());
}

#[test]
fn merge_026_fr_003_review_settings_and_activation_travel_as_commands_and_the_rest_is_kept() {
    let mut local = Local::new("review");
    local.populate();
    let ack = local.run(
        CommandType::ReviewExplainerAck,
        Some("local-owner"),
        json!({"time_zone": "UTC"}),
        vec![],
        "2026-10-05T09:00:00Z",
    );
    assert_eq!(ack, "local-owner");
    local.run(
        CommandType::ReviewSettings,
        Some("local-owner"),
        json!({"threshold_days": 21, "onboarded": true}),
        vec![shown(EntityType::ReviewSettings, "local-owner", "2")],
        "2026-10-05T10:00:00Z",
    );
    local.run(
        CommandType::ReviewSessionStart,
        None,
        json!({"mode": "quick", "entry": "list", "origin": "ios", "skip_steps": [], "replace_open": false}),
        vec![],
        "2026-10-05T11:00:00Z",
    );
    let review_before = review_facts(&mut local.store);
    assert_eq!(review_before.len(), 2);

    let outcome =
        link_and_merge_with(&mut local.store, &binding(), &context(NOW), || Ok(())).unwrap();
    assert_eq!(
        outcome,
        MergeOutcome::Merged {
            records: 10,
            commands: 17,
            review_records_kept_local: 1
        }
    );
    let types: Vec<String> = queued(&mut local.store)
        .into_iter()
        .map(|(_, e)| e["type"].as_str().unwrap().to_string())
        .collect();
    assert!(
        types.ends_with(&[
            "review.explainer_ack".to_string(),
            "review.settings".to_string()
        ]),
        "{types:?}"
    );
    // The settings the commands rebuild are the settings the device had, at the instants it had them.
    assert_eq!(review_facts(&mut local.store), review_before);
    let settings = queued(&mut local.store)
        .into_iter()
        .find(|(_, e)| e["type"] == "review.settings")
        .unwrap()
        .1;
    assert_eq!(settings["entity_id"], "account-a");
    assert_eq!(settings["issued_at"], "2026-10-05T10:00:00Z");
    assert_eq!(
        settings["payload"],
        json!({"threshold_days": 21, "onboarded": true})
    );
}

/// The visible Review records.
fn review_facts(store: &mut Store) -> BTreeMap<(String, String), Value> {
    records(store, "visible_records")
        .into_iter()
        .filter(|((kind, _), _)| kind.starts_with("review_"))
        .collect()
}
