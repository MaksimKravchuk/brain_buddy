//! Shared, immutable vector loader for the integration tests.
//!
//! Every parity test reads the same files the Python and Swift suites read; the
//! files are parsed once per test binary and handed out as `&'static`, so no
//! test can edit what another one sees. A missing file or section is a panic
//! that names it, never an empty (and therefore vacuously passing) loop.

// Each test binary compiles this module and uses a different subset.
#![allow(dead_code)]

use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use bb_domain::calendar::CalendarDay;
use bb_domain::types::{ChangeSet, DomainChange, ReadSet, Record};
use serde_json::{Value, json};

/// The repository root: `rust/crates/bb-domain` is three levels below it.
pub fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("bb-domain sits three levels below the repository root")
        .to_path_buf()
}

fn load(relative: &str) -> Value {
    let path = repo_root().join(relative);
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|error| panic!("cannot read vector file {}: {error}", path.display()));
    serde_json::from_str(&text)
        .unwrap_or_else(|error| panic!("invalid JSON in {}: {error}", path.display()))
}

macro_rules! vector_file {
    ($name:ident, $path:literal) => {
        pub fn $name() -> &'static Value {
            static CELL: OnceLock<Value> = OnceLock::new();
            CELL.get_or_init(|| load($path))
        }
    };
}

// Canonical files of specs 020/021 (the Swift and web trees hold byte-identical
// copies guarded by backend/tests/test_review_formulation_vectors.py).
vector_file!(
    formulation,
    "backend/tests/fixtures/review_formulation_vectors.json"
);
vector_file!(flow, "backend/tests/fixtures/review_flow_vectors.json");
// Spec 026 primitives (T002/T006), verified against the backend by
// backend/tests/test_026_primitive_vectors.py.
vector_file!(
    primitives,
    "specs/026-rust-core-sync/contracts/primitive-vectors.json"
);
// T002: the frozen oracle manifest with the synthetic reference dataset, and the
// versioned web presentation cases.
vector_file!(
    reference_store,
    "specs/026-rust-core-sync/contracts/reference-store.json"
);
vector_file!(
    web_presentation,
    "specs/026-rust-core-sync/contracts/web-presentation-vectors.json"
);

/// A non-empty array at `path` (dot separated keys) below `root`.
pub fn cases<'a>(root: &'a Value, path: &str) -> &'a [Value] {
    let mut node = root;
    for key in path.split('.') {
        node = node
            .get(key)
            .unwrap_or_else(|| panic!("vector section {path:?} is missing {key:?}"));
    }
    let list = node
        .as_array()
        .unwrap_or_else(|| panic!("vector section {path:?} is not an array"));
    assert!(!list.is_empty(), "vector section {path:?} is empty");
    list
}

/// The string member `key` of `case`.
pub fn text<'a>(case: &'a Value, key: &str) -> &'a str {
    case.get(key)
        .and_then(Value::as_str)
        .unwrap_or_else(|| panic!("case {case} has no string {key:?}"))
}

/// The integer member `key` of `case`.
pub fn int(case: &Value, key: &str) -> i64 {
    case.get(key)
        .and_then(Value::as_i64)
        .unwrap_or_else(|| panic!("case {case} has no integer {key:?}"))
}

/// The valid stand-in for the oracle's `form_a` (formulation ids are checked).
pub const VECTOR_FORMULATION: &str = "form_00000000000a";

/// The `ReadSet` JSON the server holds for one `auto_park` vector of the
/// formulation oracle: the vector's task (`before`) under `task_id`, and its
/// owner settings with an effective evaluation a minute before `now`, so no
/// sweep gap floors the park (the convention of the park traces).
pub fn auto_park_read_set(vector: &Value, task_id: &str) -> Value {
    let before: Value = serde_json::from_str(
        &vector["before"]
            .to_string()
            .replace("form_a", VECTOR_FORMULATION),
    )
    .expect("a vector task");
    let parked = before["parked"].as_object().map(|park| {
        let was = &park["clock_before"];
        json!({
            "at": park["at"], "formulation_id": park["formulation_id"],
            "private": {
                "from_revision": park["from_revision"].to_string(),
                "clock_before": {
                    "formulation_id": park["formulation_id"],
                    "started_at": was["started_at"], "extended_at": was["extended_at"],
                    "extension_reason": was["extension_reason"],
                    "park_floor_at": was["park_floor_at"],
                    "stalled_before": was["stalled_before"],
                },
            },
        })
    });
    let formulation = before["formulation_started_at"].as_str().map(|started| {
        json!({
            "id": before["formulation_id"], "started_at": started,
            "extended_at": before["formulation_extended_at"],
            "extension_reason": before["formulation_extension_reason"],
            "park_floor_at": before["formulation_park_floor_at"],
        })
    });
    let settings = &vector["settings"];
    let last_sweep = bb_domain::calendar::UtcInstant::parse_rfc3339(text(vector, "now"))
        .expect("a vector instant")
        .plus_seconds(-60)
        .to_rfc3339();
    json!({
        "tasks": { task_id: {
            "id": task_id, "title": before["title"], "details": null,
            "state": before["state"], "project_id": null, "tag_ids": [],
            "due_date": before["due_date"], "priority": "none", "waiting_for": null,
            "waiting_since": null, "order_key": "3", "source_capture_ids": [],
            "created_at": "2026-09-01T09:00:00Z", "updated_at": "2026-09-02T09:00:00Z",
            "completed_at": null, "cancelled_at": null,
            "revision": before["revision"].to_string(),
            "consecutive_stalled_formulations": before["consecutive_stalled_formulations"],
            "formulation": formulation, "parked": parked,
        }},
        "settings": {
            "threshold_days": settings["threshold_days"], "review_weekday": 5,
            "review_time": "16:00", "time_zone": settings["time_zone"],
            "onboarded_at": null, "activated_at": settings["activated_at"],
            "owner_park_floor_at": settings["owner_park_floor_at"], "revision": "2",
            "private": { "last_effective_sweep_at": last_sweep, "threshold_changed_at": null },
        },
    })
}

/// The read set after a change set committed: every upserted task, settings or
/// park row replaces its stored row (the other record kinds are not touched by
/// the park commands).
pub fn commit(read_set: &ReadSet, set: &ChangeSet) -> ReadSet {
    let mut next = read_set.clone();
    for change in &set.changes {
        match change {
            DomainChange::Upsert(Record::Task(task)) => {
                next.tasks.insert(task.id.clone(), task.clone());
            }
            DomainChange::Upsert(Record::ReviewSettings(settings)) => {
                next.settings = Some(settings.clone());
            }
            DomainChange::Upsert(Record::ReviewParkAck(ack)) => {
                next.park_acks.retain(|stored| {
                    (&stored.task_id, &stored.formulation_id) != (&ack.task_id, &ack.formulation_id)
                });
                next.park_acks.push(ack.clone());
            }
            other => panic!("not a park change: {other:?}"),
        }
    }
    next
}

/// A `YYYY-MM-DDTHH:MM:SSZ` instant as Unix seconds.
pub fn instant(iso: &str) -> i64 {
    let (date, time) = iso
        .strip_suffix('Z')
        .and_then(|value| value.split_once('T'))
        .unwrap_or_else(|| panic!("not a UTC instant: {iso}"));
    let day = CalendarDay::parse_iso(date).unwrap_or_else(|_| panic!("bad date in {iso}"));
    let clock: Vec<i64> = time
        .split(':')
        .map(|part| part.parse().unwrap_or_else(|_| panic!("bad time in {iso}")))
        .collect();
    assert_eq!(clock.len(), 3, "bad time in {iso}");
    day.day_number() * 86_400 + clock[0] * 3600 + clock[1] * 60 + clock[2]
}
