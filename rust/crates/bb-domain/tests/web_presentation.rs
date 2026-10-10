//! The web presentation transition (tasks.md T053, PR-53).
//!
//! The web keeps its synchronous Smart Add helpers (`smartAdd.ts`) as a
//! presentation adapter while the Rust-backed server stays the final authority.
//! The adapter is held to `contracts/web-presentation-vectors.json`
//! (`smart-add-web/1`) by `smartAddVectors.test.ts`; the Rust shared rule is held
//! to the same file by `smart_add_parity.rs` and `primitives_parity.rs`. This test
//! owns the third leg: every disagreement PR-02 froze in that oracle has exactly
//! one recorded decision in `contracts/web-presentation-resolutions.json`, and the
//! decision is true of the shared normalization primitives. Nothing here claims
//! the web helpers are deleted, compiled to WASM or replaced by a preview API.

mod support;

use std::collections::BTreeSet;

use bb_domain::normalization as norm;
use serde_json::Value;
use support::{cases, text};

const RULE_VERSION: &str = "smart-add-web/1";
const RESOLUTIONS: &str = "specs/026-rust-core-sync/contracts/web-presentation-resolutions.json";

fn resolutions() -> &'static Value {
    use std::sync::OnceLock;
    static CELL: OnceLock<Value> = OnceLock::new();
    CELL.get_or_init(|| {
        let path = support::repo_root().join(RESOLUTIONS);
        let raw = std::fs::read_to_string(&path)
            .unwrap_or_else(|error| panic!("cannot read {}: {error}", path.display()));
        serde_json::from_str(&raw).unwrap_or_else(|error| panic!("invalid JSON: {error}"))
    })
}

fn ids(list: &[Value]) -> BTreeSet<String> {
    list.iter()
        .map(|item| text(item, "id").to_owned())
        .collect()
}

fn decision<'a>(list: &'a [Value], id: &str) -> &'a str {
    let item = list
        .iter()
        .find(|item| text(item, "id") == id)
        .unwrap_or_else(|| panic!("{id} has no recorded decision"));
    text(item, "decision")
}

#[test]
fn web_presentation_026_fr_002_vectors_are_versioned_and_sourced() {
    let vectors = support::web_presentation();
    assert_eq!(
        text(vectors, "schema"),
        "brainbuddy-web-presentation-vectors/v1"
    );
    assert_eq!(text(vectors, "rule_version"), RULE_VERSION);

    let mut seen = BTreeSet::new();
    let mut cited = 0;
    for section in [
        "parse",
        "suggestions",
        "apply_suggestion",
        "name_collision_probes",
    ] {
        for case in cases(vectors, section) {
            assert!(
                seen.insert(text(case, "id").to_owned()),
                "duplicate id {case}"
            );
            let Some(source) = case.get("source") else {
                continue;
            };
            // Each case cites the web test it was taken from. A parenthesised
            // note marks the rows PR-02 derived from the contract or from research
            // before a web test existed; they cite the file but not a test name.
            let file = support::repo_root().join(text(source, "file"));
            let body = std::fs::read_to_string(&file)
                .unwrap_or_else(|error| panic!("{} is not readable: {error}", file.display()));
            let test = text(source, "test");
            if !test.contains(" (") {
                assert!(
                    body.contains(test),
                    "{} does not contain {test:?}",
                    file.display()
                );
            }
            cited += 1;
        }
    }
    assert!(
        cited >= 89,
        "every parse, suggestion and apply case cites a source"
    );
}

#[test]
fn web_presentation_026_fr_002_every_disagreement_has_exactly_one_decision() {
    let vectors = support::web_presentation();
    let ledger = resolutions();
    assert_eq!(
        text(ledger, "schema"),
        "brainbuddy-web-presentation-resolutions/v1"
    );
    assert_eq!(text(&ledger["vectors"], "rule_version"), RULE_VERSION);
    assert_eq!(text(&ledger["vectors"], "schema"), text(vectors, "schema"));
    assert_eq!(
        text(ledger, "adapter_revision"),
        format!("{RULE_VERSION}+r1")
    );

    let diverging: Vec<Value> = cases(vectors, "parse")
        .iter()
        .filter(|case| case.get("divergence").is_some())
        .cloned()
        .collect();
    let disagreeing: Vec<Value> = cases(vectors, "name_collision_probes")
        .iter()
        .filter(|probe| probe["agrees"] == Value::Bool(false))
        .cloned()
        .collect();
    let parse = cases(ledger, "parse");
    let probes = cases(ledger, "name_collision_probes");

    assert_eq!(
        ids(parse),
        ids(&diverging),
        "parse decisions cover the divergences"
    );
    assert_eq!(
        ids(probes),
        ids(&disagreeing),
        "probe decisions cover the disagreements"
    );
    for item in parse.iter().chain(probes) {
        assert!(
            ["resolved", "accepted"].contains(&text(item, "decision")),
            "{item}"
        );
        assert!(!text(item, "reason").is_empty(), "{item} has no reason");
    }

    let count = |list: &[Value], wanted: &str| {
        list.iter()
            .filter(|i| text(i, "decision") == wanted)
            .count()
    };
    assert_eq!((count(parse, "resolved"), count(parse, "accepted")), (3, 1));
    assert_eq!(
        (count(probes, "resolved"), count(probes, "accepted")),
        (3, 2)
    );
}

#[test]
fn web_presentation_026_fr_002_server_whitespace_is_the_set_the_web_now_uses() {
    // `server_whitespace` is what `smartAdd.ts` strips and collapses names with;
    // the vitest suite checks the web against it, this checks it against the
    // shared primitive over every scalar.
    let mut listed = BTreeSet::new();
    for range in cases(resolutions(), "server_whitespace") {
        let range = range.as_str().expect("range text");
        let (from, to) = range.split_once('-').unwrap_or((range, range));
        let (from, to) = (
            u32::from_str_radix(from, 16).expect("hex"),
            u32::from_str_radix(to, 16).expect("hex"),
        );
        listed.extend(from..=to);
    }
    let shared: BTreeSet<u32> = (0..=char::MAX as u32)
        .filter_map(char::from_u32)
        .filter(|c| norm::is_space(*c))
        .map(u32::from)
        .collect();
    assert_eq!(listed, shared);
    // The two scalars JavaScript `\s` gets wrong, in each direction.
    assert!(shared.contains(&0x85) && shared.contains(&0x1C) && !shared.contains(&0xFEFF));
}

/// The key the adapter derives for a tag name: the server display normalization,
/// lower-cased (JavaScript has no full case folding).
fn web_key(name: &str) -> String {
    norm::tag_display(name).to_lowercase()
}

#[test]
fn web_presentation_026_fr_002_decisions_hold_for_the_shared_tag_key() {
    let vectors = support::web_presentation();
    let probes = cases(resolutions(), "name_collision_probes");
    let mut accepted = BTreeSet::new();
    for probe in cases(vectors, "name_collision_probes") {
        let id = text(probe, "id");
        let (stored, typed) = (text(probe, "stored_tag"), text(probe, "typed_tag"));
        let server = norm::tag_key(stored) == norm::tag_key(&norm::tag_display(typed));
        assert_eq!(
            server,
            probe["server_collides"] == Value::Bool(true),
            "{id}"
        );

        let web_now = web_key(stored) == web_key(typed);
        if probe["agrees"] == Value::Bool(true) || decision(probes, id) == "resolved" {
            assert_eq!(web_now, server, "{id}: the adapter follows the server key");
        } else {
            // Accepted: only full case folding can bridge it, and the server
            // resolves the submitted name onto the stored tag regardless.
            assert!(server && !web_now, "{id}: a case-folding gap");
            assert_ne!(
                norm::casefold(&typed.to_lowercase()),
                typed.to_lowercase(),
                "{id}"
            );
            accepted.insert(id.to_owned());
        }
    }
    assert_eq!(
        accepted,
        BTreeSet::from(["WP-K-001".to_owned(), "WP-K-003".to_owned()])
    );
}

#[test]
fn web_presentation_026_fr_002_resolved_lengths_follow_scalars() {
    let vectors = support::web_presentation();
    let parse = cases(resolutions(), "parse");
    let mut ran = 0;
    for case in cases(vectors, "parse") {
        let id = text(case, "id");
        if case["divergence"]["fields"].get("is_valid").is_none() {
            continue;
        }
        assert_eq!(decision(parse, id), "resolved", "{id}");
        let title = text(case, "input");
        // The frozen web verdict counted UTF-16 units; the resolved adapter and the
        // shared rule count scalars.
        assert!(
            !case["expect"]["is_valid"]
                .as_bool()
                .expect("frozen web verdict")
        );
        assert!(norm::within_scalar_limit(title, 500));
        assert!(title.encode_utf16().count() > 500);
        ran += 1;
    }
    assert_eq!(ran, 1);
}
