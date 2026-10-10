//! Legacy outbox tests (spec 026 T042): the carried pending sends of the old store
//! become classified, never reissued and never falsely synchronized.
//!
//! Everything goes through the public API on real SQLite files: the legacy file is
//! imported by `import_legacy_store` (the frozen golden fixture, the Mac pre-021
//! fixture as a refusal case, and documents in the shape Swift's `Codable` writes),
//! then `resolve_legacy_outbox` classifies what was carried. The receipt lookup is
//! the port's fake: a closure or a table of answers, never a transport.

use bb_client::{
    ImportRequest, IssueState, LegacyAnswer, LegacyOutboxError, LegacyOutboxStatus, LegacySend,
    OpenOptions, ProvenAlias, ProvidedReceipts, Store, import_legacy_store, legacy_outbox_sends,
    legacy_outbox_status, open_issues, resolve_legacy_outbox,
};
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
