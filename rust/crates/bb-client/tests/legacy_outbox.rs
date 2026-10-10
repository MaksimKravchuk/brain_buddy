//! Legacy outbox tests (spec 026 T042): the carried pending sends of the old store
//! become classified, never reissued and never falsely synchronized.
//!
//! Everything goes through the public API on real SQLite files: the legacy file is
//! imported by `import_legacy_store` (the frozen golden fixture, the Mac pre-021
//! fixture as a refusal case, and documents in the shape Swift's `Codable` writes),
//! then `resolve_legacy_outbox` classifies what was carried. The receipt lookup is
//! the port's fake: a closure or a table of answers, never a transport.

use bb_client::{
    ExecuteContext, ExecuteError, ExecuteRequest, ImportRequest, IssueState, LegacyAnswer,
    LegacyOutboxError, LegacyOutboxStatus, LegacySend, OpenOptions, ProvenAlias, ProvidedReceipts,
    RandomIds, Store, convert_legacy_unsent_with, import_legacy_store, legacy_outbox_sends,
    legacy_outbox_status, legacy_unsent, open_issues, resolve_legacy_outbox,
};
use bb_domain::types::{ActorId, Policy, ZoneName};
use bb_protocol::catalog::CommandType;
use bb_protocol::catalog::EntityType;
use bb_protocol::wire::Instant;
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

const WORKSPACE: &str = "workspace-local";
const IMPORTED: &str = "2026-10-10T09:00:00Z";
/// Inside the 24-hour window of `FIRST_SENT`; `LATER` is past its end.
const NOW: &str = "2026-10-10T12:00:00Z";
const LATER: &str = "2026-10-11T04:00:00Z";
const FIRST_SENT: &str = "2026-10-10T03:00:00Z";
const LONG_AGO: &str = "2026-10-07T09:00:00Z";
const SENTINEL: &str = "SENTINEL-user-text-7f3a";

const GOLDEN: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Resources/legacy-import-golden.json"
);
const MAC_PRE_021: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../../macos/Tests/BrainBuddyMacTests/Resources/legacy-awkward.json"
);

// ----------------------------------------------------------------------- harness

struct Lane {
    database: PathBuf,
    source: PathBuf,
}

fn lane(name: &str) -> Lane {
    let directory = std::env::temp_dir().join(format!("bb-outbox-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    fs::create_dir_all(&directory).unwrap();
    Lane {
        database: directory.join("rust").join("workspace.sqlite3"),
        source: directory.join("store.json"),
    }
}

fn options(path: &Path) -> OpenOptions {
    OpenOptions {
        path: path.to_path_buf(),
        workspace_id: WORKSPACE.to_string(),
        busy_timeout: Duration::from_millis(2_000),
    }
}

fn at(text: &str) -> Instant {
    Instant::parse(text).unwrap()
}

impl Lane {
    /// Writes `document`, imports it and returns the open store.
    fn imported(&self, document: &Value) -> Store {
        fs::write(&self.source, serde_json::to_vec(document).unwrap()).unwrap();
        self.import_bytes()
    }

    fn import_bytes(&self) -> Store {
        import_legacy_store(&ImportRequest {
            store: options(&self.database),
            source: self.source.clone(),
            backup_dir: None,
            now: at(IMPORTED),
            expected: None,
        })
        .unwrap();
        Store::open(&options(&self.database)).unwrap()
    }
}

fn uuid(n: u32) -> String {
    format!("00000000-0000-4000-8000-{n:012}")
}

fn document(outbox: Vec<Value>, issues: Vec<Value>) -> Value {
    json!({
        "version": 2, "generation": 1,
        "base": {"projects": {}, "tags": {}, "tasks": {}},
        "outbox": outbox, "issues": issues, "sync": {},
        "local": {"activatedAt": "2026-10-01T00:00:00Z", "explainerSeenLocally": true}
    })
}

fn create_task(task: &str, title: &str) -> Value {
    json!({"createTask": {"_0": {"taskID": task, "title": title, "list": "next",
        "priority": "none", "tagIDs": []}}})
}

/// A pending send that never left the device.
fn unsent(n: u32, task: &str, title: &str) -> Value {
    json!({"id": uuid(n), "attempts": 0, "issuedAt": LONG_AGO,
        "idempotencyKey": uuid(1000 + n), "command": create_task(task, title)})
}

/// A pending send a request was made for (twice), first sent at `first`.
fn sent(n: u32, task: &str, title: &str, first: &str) -> Value {
    json!({"id": uuid(n), "attempts": 2, "everSent": true, "issuedAt": LONG_AGO,
        "firstAttemptAt": first, "lastAttemptAt": first, "lastError": "timeout",
        "idempotencyKey": uuid(1000 + n), "command": create_task(task, title)})
}

fn count(store: &mut Store, table: &str) -> i64 {
    store
        .read(|tx| tx.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r.get(0)))
        .unwrap()
}

/// Every `drafts` row of the kinds the importer wrote, which resolving must not touch.
fn carried(store: &mut Store) -> Vec<(String, String, Vec<u8>)> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT draft_id, editor_kind, fields FROM drafts
                 WHERE editor_kind <> 'legacy_outbox_resolution' ORDER BY draft_id",
            )?;
            let rows = statement.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))?;
            rows.collect()
        })
        .unwrap()
}

fn aliases(store: &mut Store) -> Vec<(String, String, String, String)> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT entity_type, old_local_id, server_id, provenance FROM identity_aliases
                 ORDER BY entity_type, old_local_id",
            )?;
            let rows =
                statement.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))?;
            rows.collect()
        })
        .unwrap()
}

fn issue_rows(store: &mut Store) -> Vec<(String, String, String, Value)> {
    store
        .read(|tx| {
            let mut statement = tx.prepare(
                "SELECT issue_id, reason, resolution, local_intent FROM sync_issues ORDER BY issue_id",
            )?;
            let rows = statement.query_map([], |r| {
                let intent: Vec<u8> = r.get(3)?;
                Ok((r.get(0)?, r.get(1)?, r.get(2)?, serde_json::from_slice(&intent).unwrap()))
            })?;
            rows.collect()
        })
        .unwrap()
}

fn nothing(_: &LegacySend) -> LegacyAnswer {
    panic!("no lookup is expected");
}

fn accepted(task: &str, server: &str) -> LegacyAnswer {
    LegacyAnswer::Accepted {
        aliases: vec![ProvenAlias {
            entity_type: EntityType::Task,
            old_local_id: task.to_owned(),
            server_id: server.to_owned(),
        }],
    }
}

fn resolve(
    store: &mut Store,
    now: &str,
    mut answers: impl FnMut(&LegacySend) -> LegacyAnswer,
) -> LegacyOutboxStatus {
    resolve_legacy_outbox(store, &mut answers, &at(now)).unwrap()
}

// ------------------------------------------------------------------------- tests

fn prepared(store: &mut Store) -> Vec<ExecuteRequest> {
    prepared_entries(legacy_unsent(store).unwrap())
}

fn prepared_entries(entries: Vec<bb_client::LegacyUnsent>) -> Vec<ExecuteRequest> {
    entries
        .into_iter()
        .map(|entry| {
            let source = &entry.command["createTask"]["_0"];
            ExecuteRequest {
                command_id: entry.idempotency_key,
                command_type: CommandType::TaskCreate,
                entity_id: Some(
                    bb_protocol::wire::Id::parse(format!(
                        "task_{}",
                        source["taskID"].as_str().unwrap()
                    ))
                    .unwrap(),
                ),
                payload: json!({"title":source["title"],"state":"next"})
                    .as_object()
                    .unwrap()
                    .clone(),
                preconditions: vec![],
                depends_on: vec![],
                admission_tokens: Vec::new(),
                context: ExecuteContext {
                    now: entry.issued_at,
                    time_zone: ZoneName::new("UTC").unwrap(),
                    actor_id: ActorId::parse("device").unwrap(),
                    policy: Policy {
                        weekly_review: false,
                        navigator_provider: None,
                        navigator_available: false,
                        consent_text_version: 1,
                    },
                },
            }
        })
        .collect()
}

#[test]
fn legacy_outbox_026_fr_013_unsent_conversion_and_marker_commit_together() {
    let lane = lane("conversion");
    let mut store = lane.imported(&document(
        vec![unsent(1, &uuid(11), "One"), unsent(2, &uuid(12), "Two")],
        vec![],
    ));
    resolve(&mut store, NOW, nothing);
    let original = carried(&mut store);
    let requests = prepared(&mut store);
    let cancelled = convert_legacy_unsent_with(&mut store, &mut RandomIds, &requests, |_| {
        Err(ExecuteError::Cancelled)
    });
    assert_eq!(cancelled.unwrap_err(), ExecuteError::Cancelled);
    assert_eq!(count(&mut store, "outbox"), 0);
    assert_eq!(legacy_outbox_status(&mut store).unwrap().unsent, 2);
    let saved =
        convert_legacy_unsent_with(&mut store, &mut RandomIds, &requests, |_| Ok(())).unwrap();
    assert_eq!(saved[0].command_id, requests[0].command_id);
    let status = legacy_outbox_status(&mut store).unwrap();
    assert_eq!(status.unsent, 0);
    assert_eq!(status.converted, 2);
    assert!(status.may_run());
    assert!(!status.fully_synced());
    let retry =
        convert_legacy_unsent_with(&mut store, &mut RandomIds, &requests, |_| Ok(())).unwrap();
    assert!(retry.iter().all(|saved| saved.replayed));
    assert_eq!(count(&mut store, "outbox"), 2);
    assert_eq!(original, carried(&mut store));
}

#[test]
fn legacy_outbox_026_fr_013_conversion_refusal_preserves_all_intents_and_order() {
    let lane = lane("conversion-refusal");
    let mut store = lane.imported(&document(
        vec![unsent(1, &uuid(11), "One"), unsent(2, &uuid(12), "")],
        vec![],
    ));
    resolve(&mut store, NOW, nothing);
    let requests = prepared(&mut store);
    assert!(matches!(
        convert_legacy_unsent_with(&mut store, &mut RandomIds, &requests, |_| Ok(())),
        Err(ExecuteError::Refused(_))
    ));
    assert_eq!(count(&mut store, "outbox"), 0);
    assert_eq!(legacy_outbox_status(&mut store).unwrap().unsent, 2);
    let mut wrong_order = requests.clone();
    wrong_order.reverse();
    assert!(
        convert_legacy_unsent_with(&mut store, &mut RandomIds, &wrong_order, |_| Ok(())).is_err()
    );
    assert_eq!(count(&mut store, "outbox"), 0);
}

#[test]
fn legacy_outbox_026_fr_013_golden_outbox_stays_unsent_is_not_looked_up_and_never_claims_synced() {
    let lane = lane("golden");
    fs::write(&lane.source, fs::read(GOLDEN).unwrap()).unwrap();
    let mut store = lane.import_bytes();
    let before = carried(&mut store);

    // Not a single lookup: nothing of the golden file was ever sent.
    let status = resolve(&mut store, NOW, nothing);

    assert_eq!(status.carried, 41);
    assert_eq!(status.unsent, 41);
    assert!(status.classified());
    assert!(
        !status.may_run(),
        "41 unsent intents still wait for their new commands"
    );
    assert!(!status.fully_synced());
    // No duplicate reconstruction: no queue row, issue or alias was made up.
    assert_eq!(count(&mut store, "outbox"), 0);
    assert_eq!(count(&mut store, "sync_issues"), 0);
    assert_eq!(count(&mut store, "identity_aliases"), 0);
    // The carried entries, the Review base and the local state are byte-for-byte as imported.
    assert_eq!(carried(&mut store), before);
    assert_eq!(legacy_outbox_status(&mut store).unwrap(), status);
}

#[test]
fn legacy_outbox_026_fr_005_a_provable_receipt_settles_the_entry_and_proves_its_alias() {
    let lane = lane("accepted");
    let mut store = lane.imported(&document(
        vec![
            unsent(1, "task-a", "a"),
            sent(2, "task-9", SENTINEL, LONG_AGO),
        ],
        vec![],
    ));
    let mut asked = Vec::new();

    let status = resolve(&mut store, NOW, |send| {
        asked.push(send.clone());
        accepted("task-9", "task_0123456789ab")
    });

    assert_eq!(asked.len(), 1, "only the entry that was sent is looked up");
    assert_eq!(asked[0].idempotency_key, uuid(1002));
    assert_eq!(asked[0].entry_id, uuid(2));
    assert_eq!(asked[0].command, create_task("task-9", SENTINEL));
    assert_eq!((status.accepted, status.unsent, status.aliases), (1, 1, 1));
    assert_eq!(
        aliases(&mut store),
        vec![(
            "task".into(),
            "task-9".into(),
            "task_0123456789ab".into(),
            "legacy-outbox:receipt".into()
        )]
    );
    // Settled by proof, not rebuilt: no new command and no issue.
    assert_eq!(count(&mut store, "outbox"), 0);
    assert_eq!(count(&mut store, "sync_issues"), 0);
    assert!(
        !status.fully_synced(),
        "the unsent entry is still not synchronized"
    );
}

#[test]
fn legacy_outbox_026_fr_005_an_alias_for_an_id_the_command_never_named_is_not_proof() {
    let lane = lane("stranger");
    let mut store = lane.imported(&document(vec![sent(1, "task-9", "x", LONG_AGO)], vec![]));

    let status = resolve(&mut store, NOW, |_| {
        accepted("task-someone-else", "task_ffffffffffff")
    });

    assert_eq!(
        (status.accepted, status.uncertain, status.aliases),
        (0, 1, 0)
    );
    assert!(aliases(&mut store).is_empty());
    assert_eq!(
        issue_rows(&mut store).len(),
        1,
        "the unproven entry is kept as an issue"
    );
}

#[test]
fn legacy_outbox_026_sc_002_an_alias_matching_only_a_title_is_not_proof() {
    // The title equals the "local ID" the receipt claims: text is never an identifier.
    let lane = lane("title-alias");
    let mut store = lane.imported(&document(
        vec![sent(1, "task-9", "task-title-1", LONG_AGO)],
        vec![],
    ));

    let status = resolve(&mut store, NOW, |_| {
        accepted("task-title-1", "task_ffffffffffff")
    });

    assert_eq!(
        (status.accepted, status.uncertain, status.aliases),
        (0, 1, 0)
    );
    assert!(aliases(&mut store).is_empty());
    assert_eq!(issue_rows(&mut store).len(), 1);
}

#[test]
fn legacy_outbox_026_sc_002_an_alias_for_the_wrong_entity_type_is_not_proof() {
    // `createTask` names task-9 as a task and project-1 as a project, and nothing else.
    let lane = lane("wrong-type");
    let mut entry = sent(1, "task-9", "x", LONG_AGO);
    entry["command"]["createTask"]["_0"]["projectID"] = json!("project-1");
    entry["command"]["createTask"]["_0"]["tagIDs"] = json!(["tag-1"]);
    let mut store = lane.imported(&document(vec![entry], vec![]));
    let alias = |entity_type, old: &str| LegacyAnswer::Accepted {
        aliases: vec![ProvenAlias {
            entity_type,
            old_local_id: old.to_owned(),
            server_id: "server_id_0001".to_owned(),
        }],
    };

    for (entity_type, old) in [
        (EntityType::Project, "task-9"),
        (EntityType::Task, "project-1"),
        (EntityType::Tag, "project-1"),
        (EntityType::Comment, "task-9"),
    ] {
        let status = resolve(&mut store, NOW, |_| alias(entity_type, old));
        assert_eq!(
            (status.accepted, status.aliases),
            (0, 0),
            "{old} as {entity_type:?}"
        );
    }
    assert!(aliases(&mut store).is_empty());

    // The same IDs as the right types are proof.
    let status = resolve(&mut store, NOW, |_| LegacyAnswer::Accepted {
        aliases: vec![
            ProvenAlias {
                entity_type: EntityType::Task,
                old_local_id: "task-9".into(),
                server_id: "task_0123456789ab".into(),
            },
            ProvenAlias {
                entity_type: EntityType::Project,
                old_local_id: "project-1".into(),
                server_id: "project_0123456789ab".into(),
            },
            ProvenAlias {
                entity_type: EntityType::Tag,
                old_local_id: "tag-1".into(),
                server_id: "tag_0123456789ab".into(),
            },
        ],
    });
    assert_eq!((status.accepted, status.aliases), (1, 3));
}

#[test]
fn legacy_outbox_026_fr_005_an_alias_that_contradicts_a_proven_one_is_not_proof() {
    let lane = lane("contradiction");
    let mut store = lane.imported(&document(
        vec![
            sent(1, "task-9", "x", LONG_AGO),
            sent(2, "task-9", "x", LONG_AGO),
        ],
        vec![],
    ));
    let mut turn = 0;

    let status = resolve(&mut store, NOW, |_| {
        turn += 1;
        accepted("task-9", &format!("task_00000000000{turn}"))
    });

    assert_eq!(
        (status.accepted, status.uncertain, status.aliases),
        (1, 1, 1)
    );
    assert_eq!(
        aliases(&mut store)[0].2,
        "task_000000000001",
        "the first proof stands"
    );
}

#[test]
fn legacy_outbox_026_fr_005_contradictory_aliases_in_one_receipt_install_nothing() {
    let lane = lane("contradictory-receipt");
    let entry = sent(1, "task-9", SENTINEL, LONG_AGO);
    let mut store = lane.imported(&document(vec![entry.clone()], vec![]));
    let mut proof = vec![ProvenAlias {
        entity_type: EntityType::Task,
        old_local_id: "task-9".into(),
        server_id: "task_0123456789ab".into(),
    }];
    let mut contradiction = proof[0].clone();
    contradiction.server_id = "task_ffffffffffff".into();
    proof.push(contradiction);

    let status = resolve(&mut store, NOW, |_| LegacyAnswer::Accepted {
        aliases: proof.clone(),
    });

    assert_eq!(
        (status.accepted, status.uncertain, status.aliases),
        (0, 1, 0)
    );
    assert!(
        aliases(&mut store).is_empty(),
        "no partial alias proof is installed"
    );
    assert_eq!(
        issue_rows(&mut store)[0].3,
        json!({"legacy_outbox_entry": entry})
    );
    assert_eq!(count(&mut store, "outbox"), 0);
    assert!(!status.fully_synced());
}

#[test]
fn legacy_outbox_026_fr_005_identical_aliases_and_same_local_id_of_different_types_are_proof() {
    let lane = lane("typed-duplicate-aliases");
    let mut entry = sent(1, "shared-local-id", "x", LONG_AGO);
    entry["command"]["createTask"]["_0"]["projectID"] = json!("shared-local-id");
    let mut store = lane.imported(&document(vec![entry], vec![]));
    let task = ProvenAlias {
        entity_type: EntityType::Task,
        old_local_id: "shared-local-id".into(),
        server_id: "task_0123456789ab".into(),
    };
    let status = resolve(&mut store, NOW, |_| LegacyAnswer::Accepted {
        aliases: vec![
            task.clone(),
            task.clone(),
            ProvenAlias {
                entity_type: EntityType::Project,
                old_local_id: "shared-local-id".into(),
                server_id: "project_0123456789ab".into(),
            },
        ],
    });

    assert_eq!(
        (status.accepted, status.aliases, status.open_issues),
        (1, 2, 0)
    );
    assert!(status.fully_synced());
}

#[test]
fn legacy_outbox_026_fr_010_same_normalized_key_with_different_bodies_never_proves_either_send() {
    let key = "abcdef01-2345-4000-8000-000000000001";
    for (index, answer) in [
        accepted("task-9", "task_0123456789ab"),
        LegacyAnswer::Accepted { aliases: vec![] },
        LegacyAnswer::Rejected {
            code: "VALIDATION_FAILED".into(),
        },
        LegacyAnswer::Unproven,
    ]
    .into_iter()
    .enumerate()
    {
        let lane = lane(&format!("ambiguous-key-{index}"));
        let mut first = sent(1, "task-9", SENTINEL, FIRST_SENT);
        let mut second = sent(2, "task-9", "different original body", FIRST_SENT);
        first["idempotencyKey"] = json!(key);
        second["idempotencyKey"] = json!(key.to_uppercase());
        let mut store = lane.imported(&document(vec![first.clone(), second.clone()], vec![]));
        let before = carried(&mut store);
        assert!(legacy_outbox_sends(&mut store).unwrap().is_empty());
        let mut receipts = ProvidedReceipts::default();
        receipts.insert(key, answer);

        let waiting = resolve_legacy_outbox(&mut store, &mut receipts, &at(NOW)).unwrap();
        assert_eq!(
            (waiting.accepted, waiting.rejected, waiting.awaiting),
            (0, 0, 2)
        );
        assert_eq!((waiting.aliases, waiting.open_issues), (0, 0));
        assert!(!waiting.fully_synced());
        // The same host-supplied answer remains unproven after the retention window.
        let closed = resolve_legacy_outbox(&mut store, &mut receipts, &at(LATER)).unwrap();
        assert_eq!(
            (closed.accepted, closed.rejected, closed.uncertain),
            (0, 0, 2)
        );
        assert_eq!((closed.aliases, closed.open_issues), (0, 2));
        let rows = issue_rows(&mut store);
        assert_eq!(rows[0].1, "OUTCOME_UNKNOWN");
        assert_eq!(rows[1].1, "OUTCOME_UNKNOWN");
        assert_eq!(rows[0].3, json!({"legacy_outbox_entry": first}));
        assert_eq!(rows[1].3, json!({"legacy_outbox_entry": second}));
        assert_eq!(carried(&mut store), before);
        assert!(aliases(&mut store).is_empty());
        assert_eq!(count(&mut store, "outbox"), 0);
        assert!(!closed.fully_synced());
        assert_eq!(resolve(&mut store, LATER, nothing), closed);
    }
}

#[test]
fn legacy_outbox_026_fr_010_key_ambiguity_includes_unsent_carried_entries() {
    let lane = lane("ambiguous-unsent");
    let first = sent(1, "task-9", SENTINEL, LONG_AGO);
    let mut second = unsent(2, "task-8", "different body");
    second["idempotencyKey"] = first["idempotencyKey"].clone();
    let mut store = lane.imported(&document(vec![first.clone(), second], vec![]));

    let status = resolve(&mut store, NOW, nothing);

    assert_eq!((status.unsent, status.uncertain, status.aliases), (1, 1, 0));
    assert_eq!(
        issue_rows(&mut store)[0].3,
        json!({"legacy_outbox_entry": first})
    );
    assert!(!status.may_run());
    assert!(!status.fully_synced());
    // The unsent entry now has a final standing; it still contributes its body.
    assert_eq!(resolve(&mut store, NOW, nothing), status);
}

#[test]
fn legacy_outbox_026_fr_005_identical_key_and_body_can_share_a_receipt() {
    let lane = lane("shared-identical-body");
    let mut first = sent(1, "task-9", SENTINEL, LONG_AGO);
    first["idempotencyKey"] = json!("abcdef01-2345-4000-8000-000000000001");
    let mut second = first.clone();
    second["id"] = json!(uuid(2));
    second["idempotencyKey"] = json!(first["idempotencyKey"].as_str().unwrap().to_uppercase());
    let mut store = lane.imported(&document(vec![first.clone(), second], vec![]));
    assert_eq!(legacy_outbox_sends(&mut store).unwrap().len(), 2);
    let mut receipts = ProvidedReceipts::default();
    receipts.insert(
        first["idempotencyKey"].as_str().unwrap(),
        accepted("task-9", "task_0123456789ab"),
    );

    let status = resolve_legacy_outbox(&mut store, &mut receipts, &at(NOW)).unwrap();

    assert_eq!(
        (status.accepted, status.aliases, status.open_issues),
        (2, 1, 0)
    );
    assert!(status.fully_synced());
}

#[test]
fn legacy_outbox_026_fr_010_a_provable_rejection_is_an_open_issue_with_the_preserved_intent() {
    let lane = lane("rejected");
    let entry = sent(1, "task-9", SENTINEL, LONG_AGO);
    let mut store = lane.imported(&document(vec![entry.clone()], vec![]));

    let status = resolve(&mut store, NOW, |_| LegacyAnswer::Rejected {
        code: "VALIDATION_FAILED".into(),
    });

    assert_eq!((status.rejected, status.open_issues), (1, 1));
    let rows = issue_rows(&mut store);
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].1, "VALIDATION_FAILED");
    assert_eq!(rows[0].3, json!({"legacy_outbox_entry": entry}));
    assert!(!status.fully_synced());
}

#[test]
fn legacy_outbox_026_fr_010_beyond_the_window_without_proof_the_send_is_an_issue_never_reissued() {
    let lane = lane("beyond");
    let entry = sent(1, "task-9", SENTINEL, LONG_AGO);
    let mut store = lane.imported(&document(vec![entry.clone()], vec![]));

    let status = resolve(&mut store, NOW, |_| LegacyAnswer::Unproven);

    assert_eq!(
        (status.uncertain, status.awaiting, status.open_issues),
        (1, 0, 1)
    );
    assert!(!status.fully_synced());
    // Nothing was queued under a new identity.
    assert_eq!(count(&mut store, "outbox"), 0);
    // The issue keeps everything the old engine knew: everSent, attempts, issuedAt, the key and
    // the body, and the user's text is there to show.
    let rows = issue_rows(&mut store);
    assert_eq!(rows[0].0, format!("legacy_entry_{}", uuid(1)));
    assert_eq!(rows[0].1, "OUTCOME_UNKNOWN");
    let kept = &rows[0].3["legacy_outbox_entry"];
    assert_eq!(kept, &entry);
    assert_eq!(kept["everSent"], true);
    assert_eq!(kept["attempts"], 2);
    assert_eq!(kept["idempotencyKey"], uuid(1001));
    // The shared issue reader lists it, with the text, and it exports as it is.
    let open = open_issues(&mut store).unwrap();
    assert_eq!(open.len(), 1);
    assert_eq!(open[0].issue.state, IssueState::Open);
    assert_eq!(open[0].issue.local_text, Some(json!({"title": SENTINEL})));
    assert_eq!(
        open[0].issue.local_intent,
        json!({"legacy_outbox_entry": entry})
    );
}

#[test]
fn legacy_outbox_026_fr_010_inside_the_window_the_send_waits_and_is_then_closed_as_an_issue() {
    let lane = lane("window");
    let mut store = lane.imported(&document(vec![sent(1, "task-9", "x", FIRST_SENT)], vec![]));

    // Still inside the 24 hours the server keeps the key: wait, no issue, not synchronized.
    let waiting = resolve(&mut store, NOW, |_| LegacyAnswer::Unproven);
    assert_eq!((waiting.awaiting, waiting.open_issues), (1, 0));
    assert!(!waiting.fully_synced());
    assert!(issue_rows(&mut store).is_empty());

    // The same state on a second look changes nothing.
    assert_eq!(
        resolve(&mut store, NOW, |_| LegacyAnswer::Unproven),
        waiting
    );

    // Past the window it becomes an issue; it is never reissued.
    let closed = resolve(&mut store, LATER, |_| LegacyAnswer::Unproven);
    assert_eq!(
        (closed.awaiting, closed.uncertain, closed.open_issues),
        (0, 1, 1)
    );
    assert_eq!(count(&mut store, "outbox"), 0);
}

#[test]
fn legacy_outbox_026_fr_010_a_key_that_was_never_used_is_never_waited_for() {
    // `everSent` survives a re-keying: the earlier key may have reached the server, and the
    // current key (never used) can prove nothing about it.
    let lane = lane("rekeyed");
    let mut entry = sent(1, "task-9", "x", FIRST_SENT);
    entry["attempts"] = json!(0);
    let mut store = lane.imported(&document(vec![entry], vec![]));

    let status = resolve(&mut store, NOW, |_| LegacyAnswer::Unproven);

    assert_eq!(
        (status.awaiting, status.uncertain, status.open_issues),
        (0, 1, 1)
    );
}

#[test]
fn legacy_outbox_026_fr_010_a_receipt_for_another_send_cannot_prove_an_unused_rotated_key() {
    for (index, answer) in [
        accepted("task-9", "task_0123456789ab"),
        LegacyAnswer::Rejected {
            code: "VALIDATION_FAILED".into(),
        },
    ]
    .into_iter()
    .enumerate()
    {
        let lane = lane(&format!("unused-key-shared-body-{index}"));
        let used = sent(1, "task-9", SENTINEL, FIRST_SENT);
        let mut rotated = used.clone();
        rotated["id"] = json!(uuid(2));
        rotated["attempts"] = json!(0);
        // The old key may have reached the server, but this current key never did.
        // The other entry genuinely used this same key/body and has a receipt.
        let mut store = lane.imported(&document(vec![used.clone(), rotated.clone()], vec![]));
        let before = carried(&mut store);
        let sends = legacy_outbox_sends(&mut store).unwrap();
        assert_eq!(sends.len(), 1);
        assert_eq!(sends[0].entry_id, uuid(1));
        let mut receipts = ProvidedReceipts::default();
        receipts.insert(used["idempotencyKey"].as_str().unwrap(), answer);

        let status = resolve_legacy_outbox(&mut store, &mut receipts, &at(NOW)).unwrap();

        assert_eq!(
            (status.accepted, status.rejected),
            if index == 0 { (1, 0) } else { (0, 1) }
        );
        assert_eq!((status.awaiting, status.uncertain), (0, 1));
        assert_eq!(status.aliases, if index == 0 { 1 } else { 0 });
        let rows = issue_rows(&mut store);
        let unknown = rows
            .iter()
            .find(|row| row.0 == format!("legacy_entry_{}", uuid(2)))
            .unwrap();
        assert_eq!(unknown.1, "OUTCOME_UNKNOWN");
        assert_eq!(unknown.3, json!({"legacy_outbox_entry": rotated}));
        assert_eq!(carried(&mut store), before);
        assert_eq!(count(&mut store, "outbox"), 0);
        assert!(!status.fully_synced());
        assert_eq!(resolve(&mut store, LATER, nothing), status);
    }
}

#[test]
fn legacy_outbox_026_fr_010_a_later_receipt_reconciles_an_open_issue() {
    let lane = lane("reconcile");
    let mut store = lane.imported(&document(vec![sent(1, "task-9", "x", LONG_AGO)], vec![]));
    assert_eq!(
        resolve(&mut store, NOW, |_| LegacyAnswer::Unproven).open_issues,
        1
    );

    let status = resolve(&mut store, LATER, |_| {
        accepted("task-9", "task_0123456789ab")
    });

    assert_eq!(
        (status.accepted, status.uncertain, status.open_issues),
        (1, 0, 0)
    );
    assert_eq!(issue_rows(&mut store)[0].2, "reconciled");
    assert!(open_issues(&mut store).unwrap().is_empty());
    assert_eq!(aliases(&mut store).len(), 1);
    // A proven standing is final: a later contradicting answer is not asked for or applied.
    let again = resolve(&mut store, LATER, nothing);
    assert_eq!(again, status);
}

#[test]
fn legacy_outbox_026_sc_002_only_the_key_matches_never_the_title_or_the_time() {
    // Two sends alike in every way a heuristic could use; only the first one's key has a receipt.
    let lane = lane("similar");
    let mut twin = sent(2, "task-8", SENTINEL, LONG_AGO);
    twin["issuedAt"] = sent(1, "task-9", SENTINEL, LONG_AGO)["issuedAt"].clone();
    let mut store = lane.imported(&document(
        vec![sent(1, "task-9", SENTINEL, LONG_AGO), twin],
        vec![],
    ));
    let mut receipts = ProvidedReceipts::default();
    receipts.insert(
        &uuid(1001).to_uppercase(),
        accepted("task-9", "task_0123456789ab"),
    );

    let status = resolve_legacy_outbox(&mut store, &mut receipts, &at(NOW)).unwrap();

    assert_eq!((status.accepted, status.uncertain), (1, 1));
    let rows = issue_rows(&mut store);
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].0, format!("legacy_entry_{}", uuid(2)));
    assert_eq!(aliases(&mut store).len(), 1);
}

#[test]
fn legacy_outbox_026_fr_013_the_old_sync_issues_become_open_issues_with_their_text() {
    let lane = lane("issues");
    let issue = json!({"id": uuid(500), "message": "Not found", "occurredAt": LONG_AGO,
        "referenceID": "ref-1", "command": {"createTask": {"_0": {"taskID": "task-3",
        "title": SENTINEL, "list": "inbox", "priority": "none", "tagIDs": []}}}});
    let mut store = lane.imported(&document(vec![], vec![issue.clone()]));

    let status = resolve(&mut store, NOW, nothing);

    assert_eq!(
        (
            status.carried_issues,
            status.converted_issues,
            status.open_issues
        ),
        (1, 1, 1)
    );
    assert!(status.classified());
    assert!(!status.fully_synced());
    let open = open_issues(&mut store).unwrap();
    assert_eq!(open.len(), 1);
    assert_eq!(
        open[0].issue.issue_id,
        format!("legacy_issue_{}", uuid(500))
    );
    assert_eq!(
        open[0].issue.local_intent,
        json!({"legacy_sync_issue": issue})
    );
    assert_eq!(open[0].issue.local_text, Some(json!({"title": SENTINEL})));
    // Resolving twice never makes a second copy.
    resolve(&mut store, NOW, nothing);
    assert_eq!(count(&mut store, "sync_issues"), 1);
}

#[test]
fn legacy_outbox_026_fr_010_review_marks_and_local_state_are_retained_untouched() {
    let lane = lane("review");
    let mut doc = document(vec![sent(1, "task-9", "x", LONG_AGO)], vec![]);
    doc["base"]["review"] = json!({
        "receipts": [{"taskID": "task-1", "kind": "waiting", "reviewedAt": LONG_AGO}],
        "parkAcks": [{"taskID": "task-5", "formulationID": "form_1", "parkedAt": LONG_AGO}]
    });
    let mut store = lane.imported(&doc);
    let before = carried(&mut store);

    resolve(&mut store, NOW, |_| LegacyAnswer::Unproven);

    assert_eq!(carried(&mut store), before);
}

#[test]
fn legacy_outbox_026_sc_005_the_lookup_runs_outside_the_write_transaction() {
    // A lookup is a network call in the end: it must not hold the store's write lock.
    let lane = lane("lock");
    let mut store = lane.imported(&document(vec![sent(1, "task-9", "x", LONG_AGO)], vec![]));
    let database = lane.database.clone();

    resolve(&mut store, NOW, |_| {
        let mut other = Store::open(&options(&database)).unwrap();
        other
            .write(|tx| tx.execute("UPDATE sync_meta SET last_success_at = ?1", [NOW]))
            .expect("the store is writable while a lookup is in flight");
        LegacyAnswer::Unproven
    });
}

#[test]
fn legacy_outbox_026_fr_003_account_less_work_stays_local_and_no_link_choice_is_made() {
    // The golden file has no account: its intents are durable local work. Classifying them
    // neither links an account, nor binds a scope or device, nor queues anything to send.
    let lane = lane("account-less");
    fs::write(&lane.source, fs::read(GOLDEN).unwrap()).unwrap();
    let mut store = lane.import_bytes();

    resolve(&mut store, NOW, nothing);

    let bound: (String, Option<String>, Option<String>, Option<String>) = store
        .read(|tx| {
            tx.query_row(
                "SELECT account_link_state, account_id, scope_id, device_id FROM sync_meta",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )
        })
        .unwrap();
    assert_eq!(bound, ("unchosen".to_owned(), None, None, None));
    assert_eq!(count(&mut store, "outbox"), 0);
}

#[test]
fn legacy_outbox_026_fr_005_the_sends_to_ask_about_come_from_the_store_and_only_while_open() {
    // The caller learns what to look up from the Rust store, not from a second reading of the
    // legacy file: only sent entries, and only until a final verdict.
    let lane = lane("sends");
    let mut store = lane.imported(&document(
        vec![unsent(1, "task-a", "a"), sent(2, "task-9", "x", FIRST_SENT)],
        vec![],
    ));
    let before = legacy_outbox_sends(&mut store).unwrap();
    assert_eq!(before.len(), 1);
    assert_eq!(before[0].entry_id, uuid(2));
    assert_eq!(before[0].idempotency_key, uuid(1002));

    resolve(&mut store, NOW, |_| LegacyAnswer::Unproven);
    assert_eq!(
        legacy_outbox_sends(&mut store).unwrap(),
        before,
        "awaiting is asked again"
    );

    resolve(&mut store, NOW, |_| accepted("task-9", "task_0123456789ab"));
    assert!(legacy_outbox_sends(&mut store).unwrap().is_empty());
}

#[test]
fn legacy_outbox_026_fr_013_nothing_is_resolved_before_the_import_and_the_mac_file_is_refused() {
    let lane = lane("mac");
    // The pre-021 Mac file is refused by the import, so there is no marker and nothing to resolve.
    fs::write(&lane.source, fs::read(MAC_PRE_021).unwrap()).unwrap();
    let refused = import_legacy_store(&ImportRequest {
        store: options(&lane.database),
        source: lane.source.clone(),
        backup_dir: None,
        now: at(IMPORTED),
        expected: None,
    });
    assert!(refused.is_err());

    let mut store = Store::open(&options(&lane.database)).unwrap();
    let error = resolve_legacy_outbox(&mut store, &mut nothing, &at(NOW)).unwrap_err();

    assert_eq!(error, LegacyOutboxError::NotImported);
    assert_eq!(error.code(), "LEGACY_OUTBOX_NOT_IMPORTED");
    assert!(!error.is_retryable());
    assert_eq!(
        legacy_outbox_status(&mut store).unwrap_err(),
        LegacyOutboxError::NotImported
    );
    for table in ["outbox", "sync_issues", "drafts", "identity_aliases"] {
        assert_eq!(count(&mut store, table), 0, "{table}");
    }
}

#[test]
fn legacy_outbox_026_fr_013_an_entry_the_import_carried_but_cannot_be_read_stops_with_no_change() {
    let lane = lane("unreadable");
    let mut store = lane.imported(&document(
        vec![unsent(1, "task-a", "a"), sent(2, "task-9", "x", LONG_AGO)],
        vec![],
    ));
    // The carried id is no UUID: the entry cannot become an issue without a made-up identity.
    store
        .write(|tx| {
            tx.execute(
                "UPDATE drafts SET fields = ?1 WHERE draft_id = 'legacy-outbox:00000001'",
                [serde_json::to_vec(&json!({"id": "not-a-uuid", "attempts": 1})).unwrap()],
            )
        })
        .unwrap();

    let error = resolve_legacy_outbox(
        &mut store,
        &mut |_: &LegacySend| LegacyAnswer::Unproven,
        &at(NOW),
    )
    .unwrap_err();

    assert_eq!(error, LegacyOutboxError::Unreadable { field: "outbox" });
    assert_eq!(count(&mut store, "sync_issues"), 0);
    assert_eq!(
        count(&mut store, "drafts"),
        3 + 2,
        "no resolution row was written"
    );
}

#[test]
fn legacy_outbox_026_fr_013_the_statuses_and_errors_carry_no_user_text() {
    let lane = lane("text");
    let mut store = lane.imported(&document(
        vec![sent(1, "task-9", SENTINEL, LONG_AGO)],
        vec![],
    ));
    let status = resolve(&mut store, NOW, |_| LegacyAnswer::Unproven);
    assert!(!format!("{status:?}").contains(SENTINEL));
    let error = LegacyOutboxError::Unreadable { field: "outbox" };
    assert_eq!(error.to_string(), "LEGACY_OUTBOX_UNREADABLE");
    assert_eq!(error.field(), Some("outbox"));
}

#[test]
fn review_unsent_conversion_requires_atomic_review_activation_first() {
    use bb_protocol::wire::Id;
    let lane = lane("review-conversion-order");
    let mut source = unsent(1, &uuid(11), "");
    source["command"] = json!({"revokeNavigatorConsent":{"provider":"openai"}});
    let mut store = lane.imported(&document(vec![source], vec![]));
    resolve(&mut store, NOW, nothing);
    let entry = legacy_unsent(&mut store).unwrap().remove(0);
    let request = ExecuteRequest {
        command_id: entry.idempotency_key,
        command_type: CommandType::ReviewConsentRevoke,
        entity_id: Some(Id::parse("owner").unwrap()),
        payload: json!({"provider":"openai"}).as_object().unwrap().clone(),
        preconditions: vec![],
        depends_on: vec![],
        admission_tokens: Vec::new(),
        context: ExecuteContext {
            now: entry.issued_at,
            time_zone: ZoneName::new("UTC").unwrap(),
            actor_id: ActorId::parse("device").unwrap(),
            policy: Policy {
                weekly_review: true,
                navigator_provider: None,
                navigator_available: false,
                consent_text_version: 1,
            },
        },
    };
    assert!(matches!(
        convert_legacy_unsent_with(
            &mut store,
            &mut RandomIds,
            std::slice::from_ref(&request),
            |_| Ok(())
        ),
        Err(ExecuteError::Refused(_))
    ));
    assert_eq!(count(&mut store, "outbox"), 0);
    assert_eq!(legacy_unsent(&mut store).unwrap().len(), 1);
    let capture = bb_client::capture_legacy_review(&mut store).unwrap();
    let prepared = bb_client::PreparedLegacyReview {
        token: capture.token,
        read_set: bb_domain::types::ReadSet::default(),
        aliases: vec![],
        derived_counts: Default::default(),
    };
    bb_client::activate_legacy_review(&mut store, &request.context, &prepared).unwrap();
    assert_eq!(
        convert_legacy_unsent_with(
            &mut store,
            &mut RandomIds,
            std::slice::from_ref(&request),
            |_| Ok(())
        )
        .unwrap()
        .len(),
        1
    );
    assert!(legacy_unsent(&mut store).unwrap().is_empty());
}

fn page_requests(
    page: &bb_client::LegacyConversionPage,
    plan: &bb_client::LegacyConversionPlan,
) -> Vec<ExecuteRequest> {
    prepared_entries(page.items.clone())
        .into_iter()
        .map(|mut request| {
            let issued = request.context.now.clone();
            request.context = plan.context.clone();
            request.context.now = issued;
            request
        })
        .collect()
}

fn page_ids(page: &bb_client::LegacyConversionPage) -> Vec<String> {
    page.items
        .iter()
        .map(|item| item.entry_id.clone())
        .collect()
}

fn conversion_context() -> ExecuteContext {
    ExecuteContext {
        now: at(NOW),
        time_zone: ZoneName::new("UTC").unwrap(),
        actor_id: ActorId::parse("device").unwrap(),
        policy: Policy {
            weekly_review: false,
            navigator_provider: None,
            navigator_available: false,
            consent_text_version: 1,
        },
    }
}

#[test]
fn bounded_conversion_201_preserves_prefix_restart_order_known_retries_and_context() {
    use bb_client::{
        begin_legacy_conversion_with, convert_legacy_page_with, legacy_conversion_page,
    };
    let lane = lane("bounded-201");
    let mut store = lane.imported(&document(
        (1..=201)
            .map(|n| unsent(n, &uuid(10_000 + n), "Original"))
            .collect(),
        vec![],
    ));
    resolve(&mut store, NOW, nothing);
    assert!(legacy_unsent(&mut store).is_err()); // Compatibility never bridges an unbounded array.
    let plan =
        begin_legacy_conversion_with(&mut store, &conversion_context(), false, |_| Ok(())).unwrap();
    assert_eq!(plan.source_count, 201);
    assert!(!plan.atomic_group);
    let first = legacy_conversion_page(&mut store, &plan.token, None).unwrap();
    assert_eq!(first.items.len(), 200);
    let first_requests = page_requests(&first, &plan);
    let second =
        legacy_conversion_page(&mut store, &plan.token, first.next_after.as_deref()).unwrap();
    assert_eq!(second.items.len(), 1);
    assert!(second.next_after.is_none());
    let mut second_requests = page_requests(&second, &plan);
    assert!(
        convert_legacy_page_with(
            &mut store,
            &mut RandomIds,
            &plan.token,
            &second.page_token,
            &page_ids(&second),
            &second_requests,
            |_| Ok(())
        )
        .is_err()
    );
    assert_eq!(count(&mut store, "outbox"), 0);
    assert_eq!(
        convert_legacy_page_with(
            &mut store,
            &mut RandomIds,
            &plan.token,
            &first.page_token,
            &page_ids(&first),
            &first_requests,
            |_| Err(ExecuteError::Cancelled)
        )
        .unwrap_err(),
        ExecuteError::Cancelled
    );
    assert_eq!(count(&mut store, "outbox"), 0);
    let prefix = convert_legacy_page_with(
        &mut store,
        &mut RandomIds,
        &plan.token,
        &first.page_token,
        &page_ids(&first),
        &first_requests,
        |_| Ok(()),
    )
    .unwrap();
    assert_eq!(prefix.processed_count, 200);
    assert!(!prefix.complete);
    assert!(!prefix.status.may_run());
    drop(store);
    let mut store = Store::open(&options(&lane.database)).unwrap();
    let mut changed_context = conversion_context();
    changed_context.time_zone = ZoneName::new("Asia/Tokyo").unwrap();
    changed_context.actor_id = ActorId::parse("changed-device").unwrap();
    changed_context.policy.weekly_review = true;
    let resumed =
        begin_legacy_conversion_with(&mut store, &changed_context, false, |_| Ok(())).unwrap();
    assert_eq!(resumed.token, plan.token);
    assert_eq!(resumed.context.actor_id, plan.context.actor_id);
    assert_eq!(resumed.context.policy, plan.context.policy);
    assert_eq!(resumed.context.time_zone, plan.context.time_zone);
    // Ordinary durable dependencies cross the page boundary; every creation
    // still keeps its original source identity and issued time.
    second_requests[0]
        .depends_on
        .push(first_requests[0].command_id.clone());
    let done = convert_legacy_page_with(
        &mut store,
        &mut RandomIds,
        &plan.token,
        &second.page_token,
        &page_ids(&second),
        &second_requests,
        |_| Ok(()),
    )
    .unwrap();
    assert!(done.complete);
    assert!(done.status.may_run());
    assert_eq!(count(&mut store, "outbox"), 201);
    let tasks: i64 = store
        .read(|tx| {
            tx.query_row(
                "SELECT COUNT(*) FROM visible_records WHERE record_type='task'",
                [],
                |r| r.get(0),
            )
        })
        .unwrap();
    assert_eq!(tasks, 201);
    // Page1 exact retry remains valid after page2; every changed known body is checked.
    assert!(
        convert_legacy_page_with(
            &mut store,
            &mut RandomIds,
            &plan.token,
            &first.page_token,
            &page_ids(&first),
            &first_requests,
            |_| Ok(())
        )
        .unwrap()
        .complete
    );
    let mut changed = first_requests.clone();
    changed[199]
        .payload
        .insert("title".into(), json!("Changed"));
    assert_eq!(
        convert_legacy_page_with(
            &mut store,
            &mut RandomIds,
            &plan.token,
            &first.page_token,
            &page_ids(&first),
            &changed,
            |_| Ok(())
        )
        .unwrap_err(),
        ExecuteError::CommandIdReused
    );
    assert_eq!(count(&mut store, "outbox"), 201);
    let mut wrong = page_ids(&first);
    wrong.swap(0, 1);
    assert!(
        convert_legacy_page_with(
            &mut store,
            &mut RandomIds,
            &plan.token,
            &first.page_token,
            &wrong,
            &first_requests,
            |_| Ok(())
        )
        .is_err()
    );
    assert!(
        convert_legacy_page_with(
            &mut store,
            &mut RandomIds,
            &plan.token,
            &first.page_token,
            &page_ids(&first),
            &[first_requests.clone(), vec![second_requests[0].clone()]].concat(),
            |_| Ok(())
        )
        .is_err()
    );
    // A stale immutable source pin is not an offset or a new queue to convert.
    store.write(|tx| {tx.execute("UPDATE drafts SET fields=CAST(replace(CAST(fields AS TEXT),'Original','Changed') AS BLOB) WHERE editor_kind='legacy_outbox_entry' AND draft_id='legacy-outbox:00000000'",[])?;Ok(())}).unwrap();
    assert!(legacy_conversion_page(&mut store, &plan.token, None).is_err());
}

#[test]
fn bounded_atomic_staging_keeps_201_fresh_bulk_skip_applied_and_stale_guards_together() {
    use bb_client::{
        begin_legacy_conversion_with, convert_legacy_page_with, finalize_legacy_conversion_with,
        legacy_conversion_page, stage_legacy_page_with,
    };
    use bb_protocol::{
        command::{AfterCommandPrecondition, CommandRef, Precondition},
        wire::Id,
    };
    for (name, state, guard, success) in [
        ("applied", "inbox", "1", true),
        ("skipped", "next", "1", true),
        ("stale", "inbox", "99", false),
    ] {
        let lane = lane(&format!("staged-bulk-{name}"));
        let mut source: Vec<_> = (1..=199)
            .map(|n| unsent(n, &uuid(20_000 + n), "Unrelated"))
            .collect();
        let mut bulk_source = unsent(200, &uuid(20_200), "");
        bulk_source["command"] = json!({"bulkRelease":{"_0":{"bulkID":uuid(30_000),"kind":"inbox_remainder","taskIDs":[uuid(29_000)],"undoRetained":true}}});
        source.push(bulk_source);
        source.push(unsent(201, &uuid(20_201), "Dependent editor"));
        let mut store = lane.imported(&document(source, vec![]));
        resolve(&mut store, NOW, nothing);
        let capture = bb_client::capture_legacy_review(&mut store).unwrap();
        let prepared = bb_client::PreparedLegacyReview {
            token: capture.token,
            read_set: Default::default(),
            aliases: vec![],
            derived_counts: Default::default(),
        };
        let mut context = conversion_context();
        context.policy.weekly_review = true;
        bb_client::activate_legacy_review(&mut store, &context, &prepared).unwrap();
        let mut seed = prepared_entries(vec![bb_client::LegacyUnsent {
            entry_id: uuid(900),
            idempotency_key: bb_protocol::wire::CommandId::parse(uuid(901)).unwrap(),
            issued_at: at(LONG_AGO),
            command: create_task(&uuid(29_000), "Before migration"),
        }])
        .remove(0);
        seed.payload.insert("state".into(), json!(state));
        let target = seed.entity_id.clone().unwrap();
        bb_client::execute(&mut store, &mut RandomIds, &seed).unwrap();
        let before = count(&mut store, "outbox");
        // False host mode cannot split the coupled original sequence.
        let plan = begin_legacy_conversion_with(&mut store, &context, false, |_| Ok(())).unwrap();
        assert!(plan.atomic_group);
        let first = legacy_conversion_page(&mut store, &plan.token, None).unwrap();
        let second =
            legacy_conversion_page(&mut store, &plan.token, first.next_after.as_deref()).unwrap();
        let mut first_requests = page_requests(
            &bb_client::LegacyConversionPage {
                items: first.items[..199].to_vec(),
                page_token: String::new(),
                next_after: None,
            },
            &plan,
        );
        let bulk=ExecuteRequest {command_id:first.items[199].idempotency_key.clone(),command_type:CommandType::ReviewBulkRelease,
            entity_id:Some(Id::parse("bulk_00000000-0000-4000-8000-000000030000").unwrap()),
            payload:json!({"kind":"inbox_remainder","items":[{"task_id":target,"expected_revision":guard}]}).as_object().unwrap().clone(),
            preconditions:vec![],depends_on:vec![],admission_tokens:vec![],context:ExecuteContext {now:first.items[199].issued_at.clone(),..plan.context.clone()}};
        let bulk_id = bulk.command_id.clone();
        first_requests.push(bulk);
        let mut second_requests = page_requests(&second, &plan);
        second_requests[0].command_type = CommandType::TaskUpdate;
        second_requests[0].entity_id = Some(target.clone());
        second_requests[0].payload = json!({"title":"Dependent editor"})
            .as_object()
            .unwrap()
            .clone();
        second_requests[0].preconditions =
            vec![Precondition::AfterCommand(AfterCommandPrecondition {
                after_command: CommandRef {
                    command_id: bulk_id,
                    entity_type: EntityType::Task,
                    entity_id: target,
                },
            })];
        assert!(
            convert_legacy_page_with(
                &mut store,
                &mut RandomIds,
                &plan.token,
                &first.page_token,
                &page_ids(&first),
                &first_requests,
                |_| Ok(())
            )
            .is_err()
        );
        assert!(
            stage_legacy_page_with(
                &mut store,
                &plan.token,
                &second.page_token,
                &page_ids(&second),
                &second_requests,
                |_| Ok(())
            )
            .is_err()
        );
        assert_eq!(
            stage_legacy_page_with(
                &mut store,
                &plan.token,
                &first.page_token,
                &page_ids(&first),
                &first_requests,
                |_| Err(ExecuteError::Cancelled)
            )
            .unwrap_err(),
            ExecuteError::Cancelled
        );
        let staged = stage_legacy_page_with(
            &mut store,
            &plan.token,
            &first.page_token,
            &page_ids(&first),
            &first_requests,
            |_| Ok(()),
        )
        .unwrap();
        assert_eq!(staged.processed_count, 200);
        assert!(!staged.complete);
        assert!(!staged.status.may_run());
        assert_eq!(count(&mut store, "outbox"), before);
        assert!(
            finalize_legacy_conversion_with(&mut store, &mut RandomIds, &plan.token, |_| Ok(()))
                .is_err()
        );
        drop(store);
        let mut store = Store::open(&options(&lane.database)).unwrap();
        stage_legacy_page_with(
            &mut store,
            &plan.token,
            &first.page_token,
            &page_ids(&first),
            &first_requests,
            |_| Ok(()),
        )
        .unwrap();
        stage_legacy_page_with(
            &mut store,
            &plan.token,
            &second.page_token,
            &page_ids(&second),
            &second_requests,
            |_| Ok(()),
        )
        .unwrap();
        let cancelled =
            finalize_legacy_conversion_with(&mut store, &mut RandomIds, &plan.token, |_| {
                Err(ExecuteError::Cancelled)
            })
            .unwrap_err();
        if success {
            assert_eq!(cancelled, ExecuteError::Cancelled);
        } else {
            assert!(matches!(cancelled, ExecuteError::Refused(_)));
        }

        assert_eq!(count(&mut store, "outbox"), before);
        assert_eq!(legacy_outbox_status(&mut store).unwrap().unsent, 201);
        let finalized =
            finalize_legacy_conversion_with(&mut store, &mut RandomIds, &plan.token, |_| Ok(()));
        if success {
            assert!(finalized.unwrap().complete);
            assert_eq!(count(&mut store, "outbox"), before + 201);
            let fragments:i64=store.read(|tx|tx.query_row("SELECT COUNT(*) FROM drafts WHERE editor_kind='runtime_legacy_conversion_item'",[],|r|r.get(0))).unwrap();
            assert_eq!(fragments, 0);
            stage_legacy_page_with(
                &mut store,
                &plan.token,
                &first.page_token,
                &page_ids(&first),
                &first_requests,
                |_| Ok(()),
            )
            .unwrap();
            let mut changed = second_requests.clone();
            changed[0]
                .payload
                .insert("title".into(), json!("Different retry"));
            assert_eq!(
                stage_legacy_page_with(
                    &mut store,
                    &plan.token,
                    &second.page_token,
                    &page_ids(&second),
                    &changed,
                    |_| Ok(())
                )
                .unwrap_err(),
                ExecuteError::CommandIdReused
            );
            assert!(
                finalize_legacy_conversion_with(
                    &mut store,
                    &mut RandomIds,
                    &plan.token,
                    |_| Ok(())
                )
                .unwrap()
                .complete
            );
            assert_eq!(count(&mut store, "outbox"), before + 201);
        } else {
            assert!(matches!(finalized, Err(ExecuteError::Refused(_))));
        }
    }
}

#[test]
fn bounded_atomic_tag_delete_preserves_task_guard_after_a_staged_page_boundary() {
    use bb_client::{
        begin_legacy_conversion_with, finalize_legacy_conversion_with, legacy_conversion_page,
        stage_legacy_page_with,
    };
    use bb_protocol::{
        command::{Precondition, RevisionPrecondition},
        wire::{Counter, Id},
    };
    let lane = lane("staged-tag-guard");
    let mut source: Vec<_> = (1..=199)
        .map(|n| unsent(n, &uuid(40_000 + n), "Unrelated"))
        .collect();
    let mut delete_source = unsent(200, &uuid(40_200), "");
    delete_source["command"] = json!({"deleteTag":{"_0":uuid(45_000)}});
    source.push(delete_source);
    source.push(unsent(201, &uuid(40_201), "Editor"));
    let mut store = lane.imported(&document(source, vec![]));
    resolve(&mut store, NOW, nothing);
    let mut tag = page_requests(
        &bb_client::LegacyConversionPage {
            items: vec![bb_client::LegacyUnsent {
                entry_id: uuid(900),
                idempotency_key: bb_protocol::wire::CommandId::parse(uuid(902)).unwrap(),
                issued_at: at(LONG_AGO),
                command: create_task(&uuid(45_000), ""),
            }],
            page_token: String::new(),
            next_after: None,
        },
        &bb_client::LegacyConversionPlan {
            token: String::new(),
            context: conversion_context(),
            source_count: 0,
            atomic_group: false,
        },
    )
    .remove(0);
    tag.command_type = CommandType::TagCreate;
    tag.entity_id = Some(Id::parse(format!("tag_{}", uuid(45_000))).unwrap());
    tag.payload = json!({"name":"Tag to remove"}).as_object().unwrap().clone();
    let tag_id = tag.entity_id.clone().unwrap();
    bb_client::execute(&mut store, &mut RandomIds, &tag).unwrap();
    let mut seed = prepared_entries(vec![bb_client::LegacyUnsent {
        entry_id: uuid(901),
        idempotency_key: bb_protocol::wire::CommandId::parse(uuid(903)).unwrap(),
        issued_at: at(LONG_AGO),
        command: create_task(&uuid(45_001), "Shown task"),
    }])
    .remove(0);
    seed.payload.insert("tag_ids".into(), json!([tag_id]));
    let target = seed.entity_id.clone().unwrap();
    bb_client::execute(&mut store, &mut RandomIds, &seed).unwrap();
    let before = count(&mut store, "outbox");
    let plan =
        begin_legacy_conversion_with(&mut store, &conversion_context(), false, |_| Ok(())).unwrap();
    assert!(plan.atomic_group);
    let first = legacy_conversion_page(&mut store, &plan.token, None).unwrap();
    let second =
        legacy_conversion_page(&mut store, &plan.token, first.next_after.as_deref()).unwrap();
    let shown = |kind, target: Id| {
        Precondition::Revision(RevisionPrecondition {
            entity_type: kind,
            entity_id: target,
            edit_revision: Counter::parse("1").unwrap(),
        })
    };
    let mut first_requests = page_requests(
        &bb_client::LegacyConversionPage {
            items: first.items[..199].to_vec(),
            page_token: String::new(),
            next_after: None,
        },
        &plan,
    );
    first_requests.push(ExecuteRequest {
        command_id: first.items[199].idempotency_key.clone(),
        command_type: CommandType::TagDelete,
        entity_id: Some(tag_id.clone()),
        payload: json!({}).as_object().unwrap().clone(),
        preconditions: vec![
            shown(EntityType::Tag, tag_id),
            shown(EntityType::Task, target.clone()),
        ],
        depends_on: vec![],
        admission_tokens: vec![],
        context: ExecuteContext {
            now: first.items[199].issued_at.clone(),
            ..plan.context.clone()
        },
    });

    let mut second_requests = page_requests(&second, &plan);
    second_requests[0].command_type = CommandType::TaskUpdate;
    second_requests[0].entity_id = Some(target.clone());
    second_requests[0].payload = json!({"title":"Saved after delete"})
        .as_object()
        .unwrap()
        .clone();
    second_requests[0].preconditions = vec![shown(EntityType::Task, target)];
    stage_legacy_page_with(
        &mut store,
        &plan.token,
        &first.page_token,
        &page_ids(&first),
        &first_requests,
        |_| Ok(()),
    )
    .unwrap();
    stage_legacy_page_with(
        &mut store,
        &plan.token,
        &second.page_token,
        &page_ids(&second),
        &second_requests,
        |_| Ok(()),
    )
    .unwrap();
    let finalized =
        finalize_legacy_conversion_with(&mut store, &mut RandomIds, &plan.token, |_| Ok(()))
            .unwrap();
    assert!(finalized.complete);
    assert_eq!(count(&mut store, "outbox"), before + 201);
    stage_legacy_page_with(
        &mut store,
        &plan.token,
        &second.page_token,
        &page_ids(&second),
        &second_requests,
        |_| Ok(()),
    )
    .unwrap();
    assert_eq!(count(&mut store, "outbox"), before + 201);
}

#[test]
fn bounded_conversion_refuses_sent_uncertain_and_over_byte_budget_without_effects() {
    use bb_client::{
        begin_legacy_conversion_with, convert_legacy_page_with, legacy_conversion_page,
    };
    let lane = lane("bounded-negative");
    let mut store = lane.imported(&document(
        vec![
            sent(1, &uuid(51_001), "Sent", FIRST_SENT),
            unsent(2, &uuid(51_002), "Never sent"),
        ],
        vec![],
    ));
    resolve(&mut store, LATER, |_| LegacyAnswer::Unproven);
    let plan =
        begin_legacy_conversion_with(&mut store, &conversion_context(), false, |_| Ok(())).unwrap();
    assert_eq!(plan.source_count, 1);
    let page = legacy_conversion_page(&mut store, &plan.token, None).unwrap();
    assert_eq!(page.items[0].entry_id, uuid(2));
    let requests = page_requests(&page, &plan);
    assert!(
        convert_legacy_page_with(
            &mut store,
            &mut RandomIds,
            &plan.token,
            &page.page_token,
            &[uuid(1)],
            &requests,
            |_| Ok(())
        )
        .is_err()
    );
    let mut wrong_time = requests.clone();
    wrong_time[0].context.now = at(NOW);
    assert!(
        convert_legacy_page_with(
            &mut store,
            &mut RandomIds,
            &plan.token,
            &page.page_token,
            &page_ids(&page),
            &wrong_time,
            |_| Ok(())
        )
        .is_err()
    );
    let mut wrong_key = requests.clone();
    wrong_key[0].command_id = bb_protocol::wire::CommandId::parse(uuid(1001)).unwrap();
    assert!(
        convert_legacy_page_with(
            &mut store,
            &mut RandomIds,
            &plan.token,
            &page.page_token,
            &page_ids(&page),
            &wrong_key,
            |_| Ok(())
        )
        .is_err()
    );
    let mut too_big = requests.clone();
    too_big[0]
        .payload
        .insert("details".into(), json!("x".repeat(8 * 1024 * 1024)));
    assert!(
        convert_legacy_page_with(
            &mut store,
            &mut RandomIds,
            &plan.token,
            &page.page_token,
            &page_ids(&page),
            &too_big,
            |_| Ok(())
        )
        .is_err()
    );
    assert_eq!(count(&mut store, "outbox"), 0);
    let status = legacy_outbox_status(&mut store).unwrap();
    assert_eq!(status.uncertain, 1);
    assert_eq!(status.unsent, 1);
    assert!(!status.may_run());
    store
        .write(|tx| {
            tx.execute("UPDATE sync_meta SET account_link_state='linking'", [])?;
            Ok(())
        })
        .unwrap();
    assert!(legacy_conversion_page(&mut store, &plan.token, None).is_err());
}
