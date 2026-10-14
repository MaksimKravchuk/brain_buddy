//! The decoded visible projection a store handle keeps between calls is only
//! ever reused when a fresh read would give the same answer (026-FR-001 latency,
//! SC-003). Every assertion compares a long-lived handle (with its cache) to a
//! freshly opened one (without).

use bb_client::{
    ExecuteContext, ExecuteRequest, IdSource, OpenOptions, QueryPage, Store, execute,
    execute_batch, query_page,
};
use bb_domain::types::{ActorId, Policy, QueryInputs, ZoneName};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{Precondition, RevisionPrecondition};
use bb_protocol::wire::{CommandId, Counter, Id, Instant};
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

const WORKSPACE: &str = "workspace-local";
const NOW: &str = "2026-10-10T09:00:00Z";

struct SeqIds(u64);

impl IdSource for SeqIds {
    fn uuid(&mut self) -> std::io::Result<String> {
        self.0 += 1;
        Ok(format!("00000000-0000-4000-8000-{:012x}", self.0))
    }
}

fn scratch(name: &str) -> PathBuf {
    let directory = std::env::temp_dir().join(format!("bb-pcache-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    directory.join("store").join("workspace.sqlite3")
}

fn open(path: &Path) -> Store {
    Store::open(&OpenOptions {
        path: path.to_path_buf(),
        workspace_id: WORKSPACE.to_string(),
        busy_timeout: Duration::from_secs(5),
    })
    .unwrap()
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

fn inputs() -> QueryInputs {
    QueryInputs {
        now: context().now,
        device_zone: context().time_zone,
        policy: context().policy,
    }
}

fn cmd(n: u64) -> CommandId {
    CommandId::parse(format!("01900000-0000-4000-8000-{n:012}")).unwrap()
}

fn request(
    n: u64,
    command_type: CommandType,
    entity: Option<&str>,
    payload: Value,
    revision: Option<&str>,
) -> ExecuteRequest {
    ExecuteRequest {
        command_id: cmd(n),
        command_type,
        entity_id: entity.map(|id| Id::parse(id).unwrap()),
        payload: payload.as_object().unwrap().clone(),
        preconditions: revision
            .map(|revision| {
                vec![Precondition::Revision(RevisionPrecondition {
                    entity_type: EntityType::Task,
                    entity_id: Id::parse(entity.unwrap()).unwrap(),
                    edit_revision: Counter::parse(revision).unwrap(),
                })]
            })
            .unwrap_or_default(),
        depends_on: Vec::new(),
        admission_tokens: Vec::new(),
        context: context(),
    }
}

fn pages(store: &mut Store) -> Vec<QueryPage> {
    [
        json!({"kind":"task_list","list":"inbox","sort":"manual","page":{"limit":200}}),
        json!({"kind":"task_list","list":"next","sort":"manual","page":{"limit":200}}),
        json!({"kind":"list_mode","mode":{"type":"open_list","list":"inbox"},"options":{},
               "page":{"limit":200}}),
    ]
    .into_iter()
    .map(|query| query_page(store, &serde_json::from_value(query).unwrap(), &inputs()).unwrap())
    .collect()
}

/// What a handle with no cache answers.
fn fresh(path: &Path) -> Vec<QueryPage> {
    let mut store = open(path);
    let answer = pages(&mut store);
    store.close().unwrap();
    answer
}

fn assert_cache_exact(store: &mut Store, path: &Path, step: &str) {
    assert_eq!(pages(store), fresh(path), "{step}");
}

fn create(store: &mut Store, ids: &mut SeqIds, n: u64, title: &str) -> String {
    execute(
        store,
        ids,
        &request(
            n,
            CommandType::TaskCreate,
            None,
            json!({"title": title}),
            None,
        ),
    )
    .unwrap()
    .entity_id
    .as_str()
    .to_owned()
}

#[test]
fn projection_cache_026_sc_003_gestures_and_reads_match_a_fresh_handle() {
    let path = scratch("gestures");
    let mut store = open(&path);
    let mut ids = SeqIds(0);
    assert_cache_exact(&mut store, &path, "empty");

    let a = create(&mut store, &mut ids, 1, "alpha");
    assert_cache_exact(&mut store, &path, "after create");
    let b = create(&mut store, &mut ids, 2, "beta");
    execute(
        &mut store,
        &mut ids,
        &request(
            3,
            CommandType::TaskUpdate,
            Some(&a),
            json!({"title": "alpha 2"}),
            Some("1"),
        ),
    )
    .unwrap();
    assert_cache_exact(&mut store, &path, "after update");
    execute(
        &mut store,
        &mut ids,
        &request(
            4,
            CommandType::TaskTransition,
            Some(&b),
            json!({"action": "move", "to_state": "next"}),
            Some("1"),
        ),
    )
    .unwrap();
    assert_cache_exact(&mut store, &path, "after move");

    // A batch whose second command builds on the first one's staged result.
    let batch = [
        request(
            5,
            CommandType::TaskCreate,
            None,
            json!({"title": "gamma"}),
            None,
        ),
        request(
            6,
            CommandType::TaskUpdate,
            Some(&a),
            json!({"title": "alpha 3"}),
            Some("2"),
        ),
    ];
    execute_batch(&mut store, &mut ids, &batch).unwrap();
    assert_cache_exact(&mut store, &path, "after batch");

    // A refused gesture rolls back and must not leave a poisoned cache.
    let stale = request(
        7,
        CommandType::TaskUpdate,
        Some(&a),
        json!({"title": "never"}),
        Some("1"),
    );
    assert!(execute(&mut store, &mut ids, &stale).is_err());
    assert_cache_exact(&mut store, &path, "after refusal");

    // A retry of a known command changes nothing and keeps the cache usable.
    execute(
        &mut store,
        &mut ids,
        &request(
            5,
            CommandType::TaskCreate,
            None,
            json!({"title": "gamma"}),
            None,
        ),
    )
    .unwrap();
    assert_cache_exact(&mut store, &path, "after retry");
    execute(
        &mut store,
        &mut ids,
        &request(
            8,
            CommandType::TaskTransition,
            Some(&a),
            json!({"action": "complete"}),
            Some("3"),
        ),
    )
    .unwrap();
    assert_cache_exact(&mut store, &path, "after complete");

    // The cache did the work: far more reuses than decodes across the run.
    let stats = store.projection_cache_stats();
    assert!(stats.reused >= 8 && stats.decoded <= 4, "{stats:?}");
}

#[test]
fn projection_cache_026_sc_003_another_handle_or_process_write_is_seen() {
    let path = scratch("other-writer");
    let mut first = open(&path);
    let mut ids = SeqIds(0);
    create(&mut first, &mut ids, 1, "mine");
    assert_cache_exact(&mut first, &path, "warm");

    // A second connection (the widget, App Intents) writes while `first` idles.
    let mut second = open(&path);
    let theirs = create(&mut second, &mut SeqIds(100), 2, "theirs");
    let decoded = first.projection_cache_stats().decoded;
    assert_cache_exact(&mut first, &path, "after the other writer");
    assert!(
        first.projection_cache_stats().decoded > decoded,
        "another connection's commit forced a decode"
    );

    // The first handle's next gesture decides against what the other wrote.
    execute(
        &mut first,
        &mut SeqIds(200),
        &request(
            3,
            CommandType::TaskUpdate,
            Some(&theirs),
            json!({"title": "theirs, edited"}),
            Some("1"),
        ),
    )
    .unwrap();
    assert_cache_exact(&mut first, &path, "edit of the other writer's task");
    assert_cache_exact(&mut second, &path, "the other handle follows too");
}

#[test]
fn projection_cache_026_sc_003_an_uncached_write_through_the_same_handle_is_seen() {
    let path = scratch("own-raw-write");
    let mut store = open(&path);
    let mut ids = SeqIds(0);
    let id = create(&mut store, &mut ids, 1, "before");
    assert_cache_exact(&mut store, &path, "warm");

    // Not a gesture: no part of the runtime tells the cache about this write.
    store
        .write(|tx| {
            tx.execute(
                "UPDATE visible_records SET body = CAST(replace(CAST(body AS TEXT), 'before', 'raw') AS BLOB)",
                [],
            )?;
            Ok(())
        })
        .unwrap();
    let decoded_before = store.projection_cache_stats().decoded;
    let after = pages(&mut store);
    assert!(
        store.projection_cache_stats().decoded > decoded_before,
        "the uncounted write forced a decode"
    );
    assert_eq!(after, fresh(&path));
    assert!(
        format!("{after:?}").contains("raw"),
        "the raw write is visible"
    );

    store.drop_projection_cache();
    assert_cache_exact(&mut store, &path, "after dropping the cache");
    let _ = id;
}
