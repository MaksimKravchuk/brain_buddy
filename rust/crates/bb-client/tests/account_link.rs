//! The account link and the removal of the account copy (spec 026, T044): one transaction each,
//! under the store's own lock, nothing changed when the check fails.

use bb_client::{
    LinkOutcome, OpenOptions, RemovalCheck, RemovalOutcome, Store, establish_account_less_with,
    link_account_with, remove_account_copy_with,
};
use bb_protocol::wire::Id;
use std::collections::BTreeSet;
use std::fs;
use std::path::PathBuf;
use std::time::Duration;

const WORKSPACE: &str = "local-1";
const ACCOUNT: &str = "6d1f6d6e-3b1f-4a52-8d3b-0b6f2f3c9a11";
const OTHER: &str = "0c2f77a4-a1a2-4d0e-9f77-3d0d9c1b2c22";

fn open(name: &str) -> Store {
    let directory = std::env::temp_dir().join(format!("bb-link-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&directory);
    let path: PathBuf = directory.join("store.sqlite3");
    Store::open(&OpenOptions {
        path,
        workspace_id: WORKSPACE.to_string(),
        busy_timeout: Duration::from_millis(500),
    })
    .expect("open")
}

fn id(text: &str) -> Id {
    Id::parse(text).expect("id")
}

fn queue(store: &mut Store, command: &str, state: &str) {
    store
        .write(|tx| {
            let seq: i64 =
                tx.query_row("SELECT next_local_seq FROM sync_meta", [], |r| r.get(0))?;
            tx.execute("UPDATE sync_meta SET next_local_seq = ?1", [seq + 1])?;
            tx.execute(
                "INSERT INTO outbox (workspace_id, command_id, device_epoch, local_seq, envelope,
                    envelope_digest, state, created_at)
                 VALUES (?1, ?2, 'epoch-1', ?3, x'7b7d', x'00', ?4, '2026-10-13T00:00:00Z')",
                rusqlite::params![WORKSPACE, command, seq, state],
            )?;
            tx.execute(
                "UPDATE sync_meta SET projection_generation = projection_generation + 1",
                [],
            )?;
            Ok(())
        })
        .expect("queue");
}

fn meta(store: &mut Store) -> (String, Option<String>, i64, i64, i64) {
    store
        .read(|tx| {
            tx.query_row(
                "SELECT account_link_state, account_id, workspace_generation, next_local_seq,
                        (SELECT COUNT(*) FROM outbox) FROM sync_meta",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
            )
        })
        .expect("meta")
}

fn generation(store: &mut Store) -> u64 {
    let value: i64 = store
        .read(|tx| {
            tx.query_row("SELECT projection_generation FROM sync_meta", [], |r| {
                r.get(0)
            })
        })
        .expect("generation");
    u64::try_from(value).expect("generation")
}

#[test]
fn account_link_026_fr_003_an_empty_workspace_is_linked_once_and_the_retry_changes_nothing() {
    let mut store = open("empty");
    establish_account_less_with(&mut store, || Ok(())).expect("account-less");

    let account = id(ACCOUNT);
    assert_eq!(
        link_account_with(&mut store, &account, || Ok(())).unwrap(),
        LinkOutcome::Linked
    );
    let (state, held, workspace_generation, ..) = meta(&mut store);
    assert_eq!((state.as_str(), held.as_deref()), ("linked", Some(ACCOUNT)));
    assert_eq!(
        workspace_generation, 1,
        "answers issued before the link are fenced"
    );

    assert_eq!(
        link_account_with(&mut store, &account, || Ok(())).unwrap(),
        LinkOutcome::AlreadyLinked
    );
    assert_eq!(meta(&mut store).2, 1);
    // Another owner never takes a linked workspace over.
    assert_eq!(
        link_account_with(&mut store, &id(OTHER), || Ok(())).unwrap(),
        LinkOutcome::OtherAccount
    );
    assert_eq!(meta(&mut store).1.as_deref(), Some(ACCOUNT));
}

#[test]
fn account_link_026_fr_003_local_work_is_kept_and_the_workspace_is_not_linked() {
    let mut store = open("work");
    establish_account_less_with(&mut store, || Ok(())).expect("account-less");
    store
        .write(|tx| {
            tx.execute(
                "INSERT INTO visible_records (workspace_id, record_type, record_key, body)
                 VALUES (?1, 'task', '[\"t1\"]', x'7b7d')",
                [WORKSPACE],
            )
        })
        .expect("record");

    let outcome = link_account_with(&mut store, &id(ACCOUNT), || Ok(())).unwrap();
    assert_eq!(
        outcome,
        LinkOutcome::LocalWorkNotMerged {
            records: 1,
            queued: 0
        }
    );
    let (state, held, workspace_generation, ..) = meta(&mut store);
    assert_eq!(
        (state.as_str(), held, workspace_generation),
        ("account_less", None, 0),
        "nothing changed"
    );
}

#[test]
fn account_link_026_fr_011_a_cancel_that_came_first_links_nothing() {
    let mut store = open("cancel");
    let refused = link_account_with(&mut store, &id(ACCOUNT), || {
        Err(bb_client::ExecuteError::Cancelled)
    });
    assert_eq!(refused, Err(bb_client::ExecuteError::Cancelled));
    let (state, held, ..) = meta(&mut store);
    assert_eq!((state.as_str(), held), ("unchosen", None));
}

fn linked_with_work(name: &str) -> Store {
    let mut store = open(name);
    link_account_with(&mut store, &id(ACCOUNT), || Ok(())).expect("link");
    queue(&mut store, "command-a", "queued");
    queue(&mut store, "command-done", "completed");
    store
        .write(|tx| {
            tx.execute(
                "INSERT INTO sync_issues (workspace_id, issue_id, command_id, reason, local_intent,
                    created_at) VALUES (?1, 'issue-1', 'command-a', 'rejected', x'7b7d',
                    '2026-10-13T00:00:00Z')",
                [WORKSPACE],
            )?;
            tx.execute(
                "UPDATE sync_meta SET scope_id = ?1, device_id = ?2, device_epoch = 'epoch-1',
                    device_epoch_state = 'active', cursor = '9', server_generation = '3'",
                [ACCOUNT, OTHER],
            )
        })
        .expect("bind");
    store
}

fn check(max_unsent: u64, generation: u64, issues: &[&str]) -> RemovalCheck {
    RemovalCheck {
        max_unsent,
        generation,
        issue_ids: issues
            .iter()
            .map(|s| (*s).to_string())
            .collect::<BTreeSet<_>>(),
    }
}

#[test]
fn account_link_026_fr_011_the_copy_is_removed_only_as_named_and_the_identity_is_reset() {
    let mut store = linked_with_work("remove");
    let named = generation(&mut store);

    let removed =
        remove_account_copy_with(&mut store, &check(1, named, &["issue-1"]), || Ok(())).unwrap();
    assert_eq!(removed, RemovalOutcome::Removed);

    let (state, held, workspace_generation, next_seq, outbox) = meta(&mut store);
    assert_eq!(
        (state.as_str(), held, next_seq, outbox),
        ("unchosen", None, 1, 0)
    );
    assert_eq!(workspace_generation, 2, "link and removal each moved it");
    let leftovers: i64 = store
        .read(|tx| {
            tx.query_row(
                "SELECT (SELECT COUNT(*) FROM sync_issues) + (SELECT COUNT(*) FROM visible_records)
                    + (SELECT COUNT(*) FROM confirmed_records)
                    + (SELECT COUNT(*) FROM command_receipts)
                    + (SELECT COUNT(*) FROM sync_meta WHERE scope_id IS NOT NULL
                        OR device_id IS NOT NULL OR cursor IS NOT NULL
                        OR server_generation IS NOT NULL OR device_epoch IS NOT NULL)",
                [],
                |r| r.get(0),
            )
        })
        .unwrap();
    assert_eq!(leftovers, 0);
    // The reset workspace can start over, as an account-less one.
    establish_account_less_with(&mut store, || Ok(())).expect("fresh account-less after removal");
}

#[test]
fn account_link_026_fr_011_more_work_queued_since_the_confirmation_removes_nothing() {
    let mut store = linked_with_work("changed");
    let named = generation(&mut store);

    // A widget queued one more change after the sheet counted.
    queue(&mut store, "command-b", "queued");
    let outcome =
        remove_account_copy_with(&mut store, &check(1, named, &["issue-1"]), || Ok(())).unwrap();
    assert_eq!(
        outcome,
        RemovalOutcome::Changed {
            unsent: 2,
            open_issues: 1
        }
    );

    // The same count at another generation (A acknowledged, B queued) is other work.
    store
        .write(|tx| tx.execute("DELETE FROM outbox WHERE command_id = 'command-a'", []))
        .unwrap();
    let outcome =
        remove_account_copy_with(&mut store, &check(1, named, &["issue-1"]), || Ok(())).unwrap();
    assert_eq!(
        outcome,
        RemovalOutcome::Changed {
            unsent: 1,
            open_issues: 1
        }
    );

    // An issue the person did not see is not removed unseen either.
    let now = generation(&mut store);
    let outcome = remove_account_copy_with(&mut store, &check(1, now, &[]), || Ok(())).unwrap();
    assert!(matches!(
        outcome,
        RemovalOutcome::Changed { open_issues: 1, .. }
    ));

    let (state, held, _, _, outbox) = meta(&mut store);
    assert_eq!(
        (state.as_str(), held.as_deref(), outbox),
        ("linked", Some(ACCOUNT), 2)
    );
}

#[test]
fn account_link_026_fr_011_a_cancelled_removal_keeps_the_copy() {
    let mut store = linked_with_work("removal-cancel");
    let named = generation(&mut store);
    let outcome = remove_account_copy_with(&mut store, &check(1, named, &["issue-1"]), || {
        Err(bb_client::ExecuteError::Cancelled)
    });
    assert_eq!(outcome, Err(bb_client::ExecuteError::Cancelled));
    let (state, held, _, _, outbox) = meta(&mut store);
    assert_eq!(
        (state.as_str(), held.as_deref(), outbox),
        ("linked", Some(ACCOUNT), 2)
    );
}
