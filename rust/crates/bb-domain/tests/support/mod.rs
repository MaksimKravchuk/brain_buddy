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
use serde_json::Value;

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
