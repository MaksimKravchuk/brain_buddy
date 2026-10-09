//! Parity of the Smart Add family with the server, the Swift parser and
//! planner, and the frozen web presentation vectors (tasks.md T011, PR-11).
//!
//! The runner compiles the **actual** rule source with a plain `#[path]` module,
//! includes the already-merged organization and task rules (and the formulation
//! clock they build on) under their production names, and re-exports the shared
//! crates at the test-crate root, so the rule's own `crate::` paths resolve
//! exactly as they do in the library. Every data-driven test counts the cases it
//! executed, so an empty or truncated section fails instead of passing
//! vacuously.
//!
//! Sources, in order of authority for the rule they pin:
//! * server: `backend/tests/test_task_smart_add_api.py` (`task.smart_add`),
//! * Swift: `SmartAddParserTests`, `SmartAddWebParityTests`,
//!   `CapturePlannerTests` (the grammar and the capture resolution),
//! * web: `contracts/web-presentation-vectors.json` (`smart-add-web/1`), with
//!   its documented divergences.

mod support;

pub use bb_domain::{calendar, normalization, types};

#[allow(dead_code, unused_imports)]
#[path = "../src/formulation.rs"]
mod formulation;
#[allow(dead_code)]
#[path = "../src/organize.rs"]
mod organize;
#[path = "../src/smart_add.rs"]
mod smart_add;
#[allow(dead_code)]
#[path = "../src/task_rules.rs"]
mod task_rules;

use bb_protocol::command::{Decoded, decode_command};
use serde_json::{Map, Value, json};
use smart_add::{Classification, Draft, Resolution, TokenKind, parse, propose, resolve};
use support::{cases, text};
use types::{
    Binding, ChangeSet, DomainChange, DomainCommand, DomainError, EntityType, ExecutionInputs,
    OpenList, Project, ProjectId, ReadSet, Reason, Record, Tag, TagId, Task, TaskState,
};

const NOW: &str = "2026-10-09T12:00:00Z";
const FORM_A: &str = "form_0b0e1f30-0000-4000-8000-00000000000a";
const TASK: &str = "task_00000000-0000-4000-8000-0000000000a1";
const P1: &str = "project_00000000-0000-4000-8000-000000000001";
const P2: &str = "project_00000000-0000-4000-8000-000000000002";
const T1: &str = "tag_00000000-0000-4000-8000-000000000001";
const T2: &str = "tag_00000000-0000-4000-8000-000000000002";
const T3: &str = "tag_00000000-0000-4000-8000-000000000003";

// ----------------------------------------------------------------------- harness

fn inputs() -> ExecutionInputs {
    serde_json::from_value(json!({
        "rule_version": 1,
        "now": NOW,
        "time_zone": "UTC",
        "origin": "device",
        "actor_id": "actor-example",
        "authoritative": true,
        "allocated_ids": [FORM_A],
        "policy": {
            "weekly_review": true,
            "navigator_provider": null,
            "navigator_available": false,
            "consent_text_version": 1
        }
    }))
    .expect("execution inputs")
}

fn envelope_json(kind: &str, entity: &str, payload: Value) -> String {
    json!({
        "protocol_version": 1,
        "command_id": "01900000-0000-4000-8000-000000000001",
        "scope_id": "scope-example",
        "device_id": "device-example",
        "device_epoch": "epoch-example",
        "local_sequence": "7",
        "type": kind,
        "command_version": 1,
        "entity_id": entity,
        "preconditions": [],
        "depends_on": [],
        "issued_at": NOW,
        "payload": payload
    })
    .to_string()
}

fn try_command(kind: &str, entity: &str, payload: Value) -> Result<DomainCommand, DomainError> {
    match decode_command(&envelope_json(kind, entity, payload)) {
        Ok(Decoded::Executable(envelope)) => DomainCommand::from_envelope(&envelope, |_| None),
        other => panic!("{kind} did not decode as an executable command: {other:?}"),
    }
}

fn smart_add_command(payload: Value) -> DomainCommand {
    try_command("task.smart_add", TASK, payload).expect("smart add command")
}

fn project_json(id: &str, name: &str, state: &str) -> Value {
    json!({
        "id": id, "name": name, "color": null, "state": state, "revision": "2",
        "desired_outcome": null,
        "archived_at": if state == "archived" { json!("2026-09-01T09:00:00Z") } else { Value::Null },
        "archived_before_lossless": false
    })
}

fn tag_json(id: &str, name: &str, state: &str) -> Value {
    json!({ "id": id, "name": name, "state": state, "revision": "1" })
}

fn task_json(id: &str, state: &str, order_key: &str) -> Value {
    json!({
        "id": id, "title": format!("Task {id}"), "details": null, "state": state,
        "project_id": null, "tag_ids": [], "due_date": null, "priority": "none",
        "waiting_for": null, "waiting_since": null, "order_key": order_key,
        "source_capture_ids": [], "created_at": "2026-09-01T09:00:00Z",
        "updated_at": "2026-09-02T09:00:00Z", "completed_at": null, "cancelled_at": null,
        "revision": "2", "consecutive_stalled_formulations": 0,
        "formulation": null, "parked": null
    })
}

fn keyed(rows: &[Value]) -> Value {
    Value::Object(
        rows.iter()
            .map(|row| (row["id"].as_str().expect("id").to_owned(), row.clone()))
            .collect::<Map<_, _>>(),
    )
}

fn read_set_of(projects: &[Value], tags: &[Value], tasks: &[Value]) -> ReadSet {
    serde_json::from_value(json!({
        "projects": keyed(projects), "tags": keyed(tags), "tasks": keyed(tasks)
    }))
    .expect("read set")
}

/// Projects and tags as `(id, name, state)` rows.
fn rs(projects: &[(&str, &str, &str)], tags: &[(&str, &str, &str)]) -> ReadSet {
    let projects: Vec<Value> = projects
        .iter()
        .map(|p| project_json(p.0, p.1, p.2))
        .collect();
    let tags: Vec<Value> = tags.iter().map(|t| tag_json(t.0, t.1, t.2)).collect();
    read_set_of(&projects, &tags, &[])
}

fn fixture_read_set(fixture: &Value) -> ReadSet {
    let rows = |key: &str, make: fn(&str, &str, &str) -> Value| -> Vec<Value> {
        fixture[key]
            .as_array()
            .expect("fixture list")
            .iter()
            .map(|row| make(text(row, "id"), text(row, "name"), text(row, "state")))
            .collect()
    };
    read_set_of(
        &rows("projects", project_json),
        &rows("tags", tag_json),
        &[],
    )
}

/// The fixture of `smartAdd.test.ts`: the web suite and the Swift suite share it.
fn web_default() -> ReadSet {
    fixture_read_set(&support::web_presentation()["fixtures"]["default"])
}

fn upserts(set: &ChangeSet) -> Vec<&Record> {
    set.changes
        .iter()
        .map(|change| match change {
            DomainChange::Upsert(record) => record,
            DomainChange::Tombstone { .. } => panic!("Smart Add deletes nothing"),
        })
        .collect()
}

struct Landed<'a> {
    projects: Vec<&'a Project>,
    tags: Vec<&'a Tag>,
    task: &'a Task,
}

fn landed(set: &ChangeSet) -> Landed<'_> {
    let mut out = (Vec::new(), Vec::new(), Vec::new());
    for record in upserts(set) {
        match record {
            Record::Project(p) => out.0.push(p),
            Record::Tag(t) => out.1.push(t),
            Record::Task(t) => out.2.push(t),
            other => panic!("unexpected record {other:?}"),
        }
    }
    assert_eq!(out.2.len(), 1, "exactly one task");
    Landed {
        projects: out.0,
        tags: out.1,
        task: out.2[0],
    }
}

/// The changes in application order: project, tags, then the task last.
fn order(set: &ChangeSet) -> Vec<EntityType> {
    set.changes.iter().map(DomainChange::entity_type).collect()
}

fn decide(read_set: &ReadSet, payload: Value) -> Result<ChangeSet, DomainError> {
    smart_add::decide(read_set, &smart_add_command(payload), &inputs())
}

fn ok(read_set: &ReadSet, payload: Value) -> ChangeSet {
    decide(read_set, payload).unwrap_or_else(|e| panic!("smart add refused: {e}"))
}

fn refusal(read_set: &ReadSet, payload: Value) -> DomainError {
    decide(read_set, payload).expect_err("must be refused")
}

fn binding(entity_type: EntityType, alias: &str, entity: &str) -> Binding {
    serde_json::from_value(json!({
        "entity_type": entity_type, "alias_id": alias, "entity_id": entity
    }))
    .expect("binding")
}

/// A set after `set` landed, as the adapter would store it.
fn applied(read_set: &ReadSet, set: &ChangeSet) -> ReadSet {
    let mut next = read_set.clone();
    for record in upserts(set) {
        match record.clone() {
            Record::Project(p) => {
                next.projects.insert(p.id.clone(), p);
            }
            Record::Tag(t) => {
                next.tags.insert(t.id.clone(), t);
            }
            Record::Task(t) => {
                next.tasks.insert(t.id.clone(), t);
            }
            other => panic!("unexpected record {other:?}"),
        }
    }
    next
}

// ------------------------------------------------------------------- web vectors

/// `Classification` as the web vectors write a reference.
fn web_ref<I: std::fmt::Display>(classification: &Classification<I>) -> Value {
    match classification {
        Classification::Existing { id, .. } => json!({ "id": id.to_string() }),
        Classification::New { name } => json!({ "name": name }),
    }
}

/// The web draft the vector's `expect` describes, from the shared resolution.
fn shared_outcome(resolution: &Resolution) -> Value {
    json!({
        "clean_title": resolution.title,
        "tags": resolution.tags.iter().map(web_ref).collect::<Vec<_>>(),
        "project": resolution.project.as_ref().map(web_ref),
        "has_completed_tokens": !resolution.tokens.is_empty(),
        "is_valid": resolution.problem.is_none(),
    })
}

fn draft_of(case: &Value) -> Draft {
    let mut draft = Draft::new(text(case, "input"));
    if let Some(context) = case.get("context") {
        draft.context_project = context["project_id"]
            .as_str()
            .map(|id| ProjectId::parse(id).expect("project id"));
        draft.context_tag = context["tag_id"]
            .as_str()
            .map(|id| TagId::parse(id).expect("tag id"));
    }
    draft
}

#[test]
fn smart_add_026_fr_002_web_parse_vectors_match_the_shared_resolution() {
    let doc = support::web_presentation();
    assert_eq!(doc["rule_version"], "smart-add-web/1");
    let (mut ran, mut diverged) = (0, 0);
    for case in cases(doc, "parse") {
        let id = text(case, "id");
        let fixture = case["fixture"].as_str().unwrap_or("default");
        let read_set = fixture_read_set(&doc["fixtures"][fixture]);
        let resolution = resolve(&read_set, &draft_of(case));

        // The shared rule is the web outcome except the documented divergences.
        let mut expected = case["expect"].clone();
        if let Some(fields) = case["divergence"]["fields"].as_object() {
            diverged += 1;
            for (key, shared) in fields {
                assert_ne!(
                    expected[key], *shared,
                    "{id}: {key} is a divergence, so the web value must differ"
                );
                expected[key] = shared.clone();
            }
        }
        assert_eq!(shared_outcome(&resolution), expected, "{id}");

        // The chips: the project first, then the tags, with the shown name.
        // The one chip that disagrees is the divergent `ß` tag.
        let chips_diverge = case["divergence"]["fields"].get("tags").is_some();
        if !chips_diverge {
            let shown: Vec<Value> = resolution
                .project
                .iter()
                .map(|p| json!({ "kind": "project", "label": p.name() }))
                .chain(
                    resolution
                        .tags
                        .iter()
                        .map(|t| json!({ "kind": "tag", "label": t.name() })),
                )
                .collect();
            assert_eq!(Value::Array(shown), case["chips"], "{id}: chips");
        }
        ran += 1;
    }
    assert_eq!(ran, 54, "every frozen parse vector ran");
    assert_eq!(diverged, 4, "the four documented divergences");
}

#[test]
fn smart_add_026_fr_002_web_divergences_are_the_scalar_and_case_folding_rules() {
    // Each divergence names the shared rule that differs from the web; prove the
    // web's value is the UTF-16 or lower-casing artefact and ours is the contract.
    let doc = support::web_presentation();
    let by_id = |wanted: &str| -> &Value {
        cases(doc, "parse")
            .iter()
            .find(|case| text(case, "id") == wanted)
            .unwrap_or_else(|| panic!("missing {wanted}"))
    };

    // WP-P-045: lower-casing keeps U+00DF, case folding makes it "ss".
    let sharp = by_id("WP-P-045");
    let read_set = fixture_read_set(&doc["fixtures"]["sharp_ss"]);
    let resolution = resolve(&read_set, &draft_of(sharp));
    assert_eq!(resolution.tags.len(), 1);
    assert!(!resolution.tags[0].is_new(), "folds onto the stored `ss`");

    // WP-P-051: 300 emoji are 300 scalars (valid) but 600 UTF-16 units.
    let emoji = by_id("WP-P-051");
    let title = text(emoji, "input");
    assert_eq!(title.chars().count(), 300);
    assert_eq!(title.encode_utf16().count(), 600);
    assert!(resolve(&web_default(), &draft_of(emoji)).problem.is_none());

    // WP-P-052..053: the web slices by UTF-16 index but filters by code point,
    // so an astral character before a token shifts the removal.
    for (wanted, title) in [
        ("WP-P-052", "Call \u{1F600} mom"),
        ("WP-P-053", "\u{1F600}\u{1F600} today"),
    ] {
        let resolution = resolve(&web_default(), &draft_of(by_id(wanted)));
        assert_eq!(resolution.title, title, "{wanted}");
    }
    // WP-P-054 (token first) is where the web and the shared rule agree.
    let leading = resolve(&web_default(), &draft_of(by_id("WP-P-054")));
    assert_eq!(leading.title, "\u{1F600} later");
}

// ------------------------------------------------------------------------ grammar

fn names(input: &str) -> Vec<String> {
    parse(input).tokens.into_iter().map(|t| t.name).collect()
}

/// The text a token's UTF-16 range covers.
fn highlighted(input: &str) -> Vec<String> {
    let units: Vec<u16> = input.encode_utf16().collect();
    parse(input)
        .tokens
        .iter()
        .map(|t| String::from_utf16(&units[t.utf16_start..t.utf16_end]).expect("whole scalars"))
        .collect()
}

#[test]
fn smart_add_026_fr_002_tokens_report_kinds_names_and_utf16_ranges() {
    let parsed = parse("Plan #work @\"Launch v2\" #\"deep work\"");
    let shown: Vec<_> = parsed
        .tokens
        .iter()
        .map(|t| (t.kind, t.utf16_start, t.utf16_end, t.name.as_str()))
        .collect();
    assert_eq!(
        shown,
        vec![
            (TokenKind::Tag, 5, 10, "work"),
            (TokenKind::Project, 11, 23, "Launch v2"),
            (TokenKind::Tag, 24, 36, "deep work"),
        ]
    );
    assert_eq!(parsed.clean_title, "Plan");

    // Duplicates and superseded projects stay for highlighting.
    let text = "Draft @old #work @new #WORK";
    assert_eq!(highlighted(text), ["@old", "#work", "@new", "#WORK"]);
    assert_eq!(parse(text).clean_title, "Draft");

    // A surrogate pair before a token counts two UTF-16 units.
    let astral = "\u{1F600} Plan #work";
    let ranges: Vec<_> = parse(astral)
        .tokens
        .iter()
        .map(|t| (t.utf16_start, t.utf16_end))
        .collect();
    assert_eq!(ranges, [(8, 13)]);
    assert_eq!(parse(astral).clean_title, "\u{1F600} Plan");

    // Decomposed `e` + U+0301: two scalars, the name is the composed form.
    let decomposed = "Ping #cafe\u{301} now";
    assert_eq!(highlighted(decomposed), ["#cafe\u{301}"]);
    assert_eq!(names(decomposed), ["caf\u{E9}"]);

    assert_eq!(
        highlighted("Ship @\"\u{1F680} Launch\" today"),
        ["@\"\u{1F680} Launch\""]
    );
    assert_eq!(
        parse("Ship @\"\u{1F680} Launch\" today").clean_title,
        "Ship today"
    );
    // An astral letter (mathematical bold A) is a name character and folds by NFKC.
    let bold = parse("#\u{1D400}bc now");
    assert_eq!(
        (bold.tokens[0].utf16_end, bold.tokens[0].name.as_str()),
        (5, "Abc")
    );
    assert_eq!(bold.clean_title, "now");
}

#[test]
fn smart_add_026_fr_002_names_follow_unicode_letters_marks_and_numbers() {
    assert_eq!(
        names(
            "\u{41A}\u{443}\u{43F}\u{438}\u{442}\u{44C} @\u{414}\u{43E}\u{43C} #\u{441}\u{440}\u{43E}\u{447}\u{43D}\u{43E}"
        ),
        [
            "\u{414}\u{43E}\u{43C}",
            "\u{441}\u{440}\u{43E}\u{447}\u{43D}\u{43E}"
        ]
    );
    assert_eq!(
        names("Plan #\u{FF57}\u{FF4F}\u{FF52}\u{FF4B} @\u{FB01}nance"),
        ["work", "finance"]
    );
    assert_eq!(names("Plan #\"deep\u{A0}\u{A0}work\""), ["deep work"]);
    assert_eq!(
        names("#\u{65E5}\u{672C}\u{8A9E} #\u{D55C}\u{AD6D}\u{C5B4} #\u{627}\u{644}\u{639}\u{631}\u{628}\u{64A}\u{629} #\u{939}\u{93F}\u{928}\u{94D}\u{926}\u{940} x").len(),
        4
    );
    // Keycap: digit + variation selector + enclosing mark are all name characters.
    assert_eq!(
        highlighted("Pick #1\u{FE0F}\u{20E3} first"),
        ["#1\u{FE0F}\u{20E3}"]
    );
    // A ZWJ emoji family ends the name without splitting it.
    let family = "#work\u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467} done \u{1F1F7}\u{1F1FA} #\u{434}\u{43E}\u{43C}";
    assert_eq!(highlighted(family), ["#work", "#\u{434}\u{43E}\u{43C}"]);
    assert_eq!(
        parse(family).clean_title,
        "\u{1F468}\u{200D}\u{1F469}\u{200D}\u{1F467} done \u{1F1F7}\u{1F1FA}"
    );
    assert_eq!(names("Ship #v1.2.3 #a-b-c."), ["v1.2.3", "a-b-c"]);
}

#[test]
fn smart_add_026_fr_002_boundaries_and_javascript_whitespace() {
    for space in [
        "\t", "\n", "\r", "\u{0B}", "\u{0C}", "\u{A0}", "\u{2003}", "\u{2028}", "\u{3000}",
        "\u{FEFF}",
    ] {
        let parsed = parse(&format!("Plan{space}#work"));
        assert_eq!(names(&format!("Plan{space}#work")), ["work"], "{space:?}");
        assert_eq!(parsed.clean_title, "Plan", "{space:?}");
    }
    // U+0085 is Unicode White_Space but not JavaScript `\s`: the sigil is text.
    assert!(parse("Plan\u{85}#work").tokens.is_empty());
    for bracket in ["(", "[", "{"] {
        assert_eq!(names(&format!("Plan {bracket}#work")), ["work"]);
    }
    assert!(parse("a#b c@d e)#f 'g\"#h").tokens.is_empty());
    let adjacent = parse("#a#b");
    assert_eq!(names("#a#b"), ["a"]);
    assert_eq!(adjacent.clean_title, "#b");

    for (raw, title) in [
        ("Call #work, then", "Call, then"),
        ("Call #work; then", "Call; then"),
        ("Call #work: then", "Call: then"),
        ("Call #work! Now", "Call! Now"),
        ("Call #work? Yes", "Call? Yes"),
        ("Call (it #work)", "Call (it)"),
        ("Call #work/path", "Call /path"),
    ] {
        assert_eq!(names(raw), ["work"], "{raw}");
        assert_eq!(parse(raw).clean_title, title, "{raw}");
    }
}

#[test]
fn smart_add_026_fr_002_quotes_escapes_and_title_cleanup() {
    assert_eq!(names("Plan @\"Launch #work"), ["work"]);
    assert_eq!(parse("Plan @\"Launch #work").clean_title, "Plan @\"Launch");
    // Only \n and \r end a quoted name; U+2028 is ordinary whitespace inside it.
    assert_eq!(names("Plan #\"a\u{2028}b\""), ["a b"]);
    assert_eq!(
        names("Plan #\"client:alpha\" @\"R&D (2026)\""),
        ["client:alpha", "R&D (2026)"]
    );
    let escaped = parse("\\#one (\\@two) #three");
    assert_eq!(escaped.tokens.len(), 1);
    assert_eq!(escaped.clean_title, "#one (@two)");
    let double = parse("Path \\\\#tag");
    assert!(double.tokens.is_empty());
    assert_eq!(double.clean_title, "Path \\\\#tag");
    assert!(parse("Plan #\"   \" now").tokens.is_empty());

    assert_eq!(parse("Plan (#work] now").clean_title, "Plan (] now");
    assert_eq!(parse("Plan (#a #b) now").clean_title, "Plan () now");
    assert_eq!(
        parse("  Plan\t\t#work \n next\u{3000}step  ").clean_title,
        "Plan next step"
    );
    for blank in ["", " \n\t "] {
        let parsed = parse(blank);
        assert_eq!((parsed.clean_title.as_str(), parsed.tokens.len()), ("", 0));
    }
    assert_eq!(parse("(#work) @\u{414}\u{43E}\u{43C}").clean_title, "");
}

// ------------------------------------------------------------------- resolution

fn show<I>(classification: &Classification<I>) -> String {
    match classification {
        Classification::Existing { name, .. } => format!("={name}"),
        Classification::New { name } => format!("+{name}"),
    }
}

fn shown_tags(resolution: &Resolution) -> Vec<String> {
    resolution.tags.iter().map(show).collect()
}

fn preview(read_set: &ReadSet, input: &str) -> Resolution {
    resolve(read_set, &Draft::new(input))
}

fn problem(resolution: &Resolution) -> Option<Reason> {
    resolution.problem.as_ref().map(|p| p.reason)
}

#[test]
fn smart_add_026_fr_002_resolution_matches_names_through_nfkc_and_case_folding() {
    let state = rs(
        &[
            ("p-home", "\u{414}\u{43E}\u{43C}", "active"),
            ("p-fin", "\u{FB01}nance", "active"),
        ],
        &[
            (
                "t-urgent",
                "\u{421}\u{440}\u{43E}\u{447}\u{43D}\u{43E}",
                "active",
            ),
            ("t-work", "work", "active"),
        ],
    );
    let result = preview(
        &state,
        "\u{41A}\u{443}\u{43F}\u{438}\u{442}\u{44C} @\u{434}\u{43E}\u{43C} #\u{421}\u{420}\u{41E}\u{427}\u{41D}\u{41E}",
    );
    assert_eq!(result.title, "\u{41A}\u{443}\u{43F}\u{438}\u{442}\u{44C}");
    assert_eq!(
        result.project.as_ref().map(show).as_deref(),
        Some("=\u{414}\u{43E}\u{43C}")
    );
    assert_eq!(
        shown_tags(&result),
        ["=\u{421}\u{440}\u{43E}\u{447}\u{43D}\u{43E}"]
    );
    assert!(result.problem.is_none());

    let through = preview(&state, "Pay @FINANCE #\u{FF57}\u{FF4F}\u{FF52}\u{FF4B}");
    assert_eq!(
        through.project.as_ref().map(show).as_deref(),
        Some("=\u{FB01}nance")
    );
    assert_eq!(shown_tags(&through), ["=work"]);

    // A new name keeps its typed spelling in display form.
    let empty = ReadSet::default();
    let fresh = preview(
        &empty,
        "Plan @\"  \u{420}\u{435}\u{43C}\u{43E}\u{43D}\u{442} \t \u{43A}\u{443}\u{445}\u{43D}\u{438} \" #\"Deep\u{3000}Work\"",
    );
    assert_eq!(
        fresh.project.as_ref().map(show).as_deref(),
        Some("+\u{420}\u{435}\u{43C}\u{43E}\u{43D}\u{442} \u{43A}\u{443}\u{445}\u{43D}\u{438}")
    );
    assert_eq!(shown_tags(&fresh), ["+Deep Work"]);
}

#[test]
fn smart_add_026_fr_002_the_last_project_wins_and_tags_deduplicate() {
    let state = web_default();
    let last = preview(&state, "Draft @old @Admin @brand-new");
    assert_eq!(
        last.project.as_ref().map(show).as_deref(),
        Some("+brand-new")
    );
    assert_eq!(last.tokens.len(), 3);

    let tags = preview(&state, "Plan #work #new #WORK #\"NEW\" #\"#work\" #calls");
    assert_eq!(shown_tags(&tags), ["=work", "+new", "=calls"]);
}

#[test]
fn smart_add_026_fr_002_legacy_sigils_resolve_but_exact_names_win() {
    let empty = ReadSet::default();
    assert_eq!(
        shown_tags(&preview(&empty, "Plan #\"#fresh\" @\"@Garden\"")),
        ["+fresh"]
    );
    assert_eq!(
        preview(&empty, "Plan @\"@Garden\"")
            .project
            .as_ref()
            .map(show)
            .as_deref(),
        Some("+Garden")
    );

    let stored = rs(
        &[("p-home", "@Home", "active")],
        &[("t-hash", "#errands", "active")],
    );
    let result = preview(&stored, "Plan @home #errands");
    assert_eq!(result.project.as_ref().map(show).as_deref(), Some("=@Home"));
    assert_eq!(shown_tags(&result), ["=#errands"]);

    // "#work" (legacy spelling) and "work" are both active: `#work` is the exact one.
    let both = rs(
        &[],
        &[
            ("t-1-legacy", "#work", "active"),
            ("t-2-exact", "work", "active"),
        ],
    );
    let exact = resolve(&both, &Draft::new("Plan #work"));
    assert!(
        matches!(&exact.tags[0], Classification::Existing { id, .. } if id.as_str() == "t-2-exact")
    );

    // Legacy-only ties go to the lowest ID (the read set carries no creation time).
    let tie = rs(
        &[],
        &[
            ("t-b-newer", "#@focus", "active"),
            ("t-a-older", "#focus", "active"),
        ],
    );
    let picked = resolve(&tie, &Draft::new("Plan #focus"));
    assert!(
        matches!(&picked.tags[0], Classification::Existing { id, .. } if id.as_str() == "t-a-older")
    );

    // Sharp s folds to "ss" like the server.
    let sharp = rs(
        &[],
        &[("t-strasse", "Strasse", "active"), ("t-ss", "ss", "active")],
    );
    assert_eq!(
        shown_tags(&preview(&sharp, "Plan #\u{DF} #STRA\u{DF}E")),
        ["=ss", "=Strasse"]
    );

    for empty_name in ["Plan #\"#\"", "Plan #\"#@\"", "Plan @\"@\""] {
        assert_eq!(
            problem(&preview(&empty, empty_name)),
            Some(Reason::EmptyName),
            "{empty_name}"
        );
    }
}

#[test]
fn smart_add_026_fr_002_inactive_records_block_projects_not_tag_proposals() {
    let state = rs(
        &[
            (
                "p-old",
                "\u{41F}\u{435}\u{440}\u{435}\u{435}\u{437}\u{434}",
                "archived",
            ),
            ("p-live", "Launch", "active"),
        ],
        &[("t-gone", "someday", "deleted")],
    );
    let blocked = preview(
        &state,
        "Pack boxes @\u{43F}\u{435}\u{440}\u{435}\u{435}\u{437}\u{434}",
    );
    assert_eq!(
        blocked.project.as_ref().map(show).as_deref(),
        Some("=\u{41F}\u{435}\u{440}\u{435}\u{435}\u{437}\u{434}")
    );
    assert_eq!(problem(&blocked), Some(Reason::ProjectNotActive));
    assert_eq!(
        propose(
            &state,
            &Draft::new("Pack boxes @\u{43F}\u{435}\u{440}\u{435}\u{435}\u{437}\u{434}"),
            mint_project,
            mint_tag
        )
        .expect_err("blocked")
        .reason,
        Reason::ProjectNotActive
    );

    // An active project wins over an archived one of the same name.
    let both = rs(
        &[
            ("p-1-archived", "Launch", "archived"),
            ("p-2-active", "launch", "active"),
        ],
        &[],
    );
    let result = preview(&both, "Ship @LAUNCH");
    assert_eq!(
        result.project.as_ref().map(show).as_deref(),
        Some("=launch")
    );
    assert!(result.problem.is_none());

    // A superseded archived name does not block.
    let superseded = preview(
        &state,
        "Pack @\u{41F}\u{435}\u{440}\u{435}\u{435}\u{437}\u{434} @Launch",
    );
    assert!(superseded.problem.is_none());

    // The Swift planner proposes a new tag over a deleted namesake (the server
    // refuses that name, see the decide tests).
    assert_eq!(shown_tags(&preview(&state, "Read #Someday")), ["+Someday"]);
}

#[test]
fn smart_add_026_fr_002_project_and_tag_screens_are_the_context() {
    let state = web_default();
    let with = |input: &str, project: Option<&str>, tag: Option<&str>| {
        let mut draft = Draft::new(input);
        draft.context_project = project.map(|id| ProjectId::parse(id).expect("id"));
        draft.context_tag = tag.map(|id| TagId::parse(id).expect("id"));
        resolve(&state, &draft)
    };
    assert_eq!(
        with("Plan #work", Some("project-launch"), None)
            .project
            .as_ref()
            .map(show)
            .as_deref(),
        Some("=Launch v2")
    );
    assert_eq!(
        with("Plan @Admin", Some("project-launch"), None)
            .project
            .as_ref()
            .map(show)
            .as_deref(),
        Some("=Admin")
    );
    let missing = with("Plan", Some("project-gone"), None);
    assert!(missing.project.is_none());
    assert_eq!(problem(&missing), Some(Reason::NotFound));
    assert_eq!(
        shown_tags(&with("Plan #calls #work #new", None, Some("tag-work"))),
        ["=work", "=calls", "+new"]
    );

    let inactive = rs(
        &[("p-old", "Old", "archived"), ("p-new", "New", "active")],
        &[("t-gone", "gone", "deleted")],
    );
    let archived = |input: &str| {
        let mut draft = Draft::new(input);
        draft.context_project = Some(ProjectId::parse("p-old").expect("id"));
        resolve(&inactive, &draft)
    };
    assert_eq!(problem(&archived("Plan")), Some(Reason::ProjectNotActive));
    assert_eq!(
        archived("Plan").project.as_ref().map(show).as_deref(),
        Some("=Old")
    );
    assert!(archived("Plan @New").problem.is_none());

    let mut draft = Draft::new("Plan #new");
    draft.context_tag = Some(TagId::parse("t-gone").expect("id"));
    assert_eq!(shown_tags(&resolve(&inactive, &draft)), ["+new"]);
    draft.text = "Plan".to_owned();
    assert!(resolve(&inactive, &draft).tags.is_empty());
    assert!(resolve(&inactive, &draft).problem.is_none());
}

#[test]
fn smart_add_026_fr_002_validation_counts_scalars_and_reports_in_reading_order() {
    let empty = ReadSet::default();
    assert_eq!(problem(&preview(&empty, "")), Some(Reason::EmptyTitle));
    assert_eq!(
        problem(&preview(&empty, "  #work  ")),
        Some(Reason::EmptyTitle)
    );

    // 500 emoji: 500 scalars (the server's len), 1000 UTF-16 units (the web's).
    assert_eq!(problem(&preview(&empty, &"\u{1F600}".repeat(500))), None);
    assert_eq!(
        problem(&preview(&empty, &"\u{1F600}".repeat(501))),
        Some(Reason::TextLength)
    );
    // "e" + U+0301 pairs: 250 characters are 500 scalars.
    assert_eq!(problem(&preview(&empty, &"e\u{301}".repeat(250))), None);
    assert_eq!(
        problem(&preview(&empty, &"e\u{301}".repeat(251))),
        Some(Reason::TextLength)
    );

    let long = "\u{44F}".repeat(501);
    let longest = "\u{44F}".repeat(500);
    let stored = rs(&[("p-long", longest.as_str(), "active")], &[]);
    assert_eq!(
        problem(&preview(&empty, &format!("Plan @{long}"))),
        Some(Reason::TextLength)
    );
    assert_eq!(
        problem(&preview(&empty, &format!("Plan #{long}"))),
        Some(Reason::TextLength)
    );
    assert_eq!(
        problem(&preview(
            &empty,
            &format!("Plan #{}", "\u{44F}".repeat(500))
        )),
        None
    );
    assert_eq!(
        resolve(&stored, &Draft::new(format!("Plan @{longest}")))
            .project
            .as_ref()
            .map(Classification::is_new),
        Some(false),
        "a stored name at the limit resolves instead of being created"
    );

    let waiting = |input: &str, note: &str| {
        let mut draft = Draft::new(input);
        draft.list = OpenList::Waiting;
        draft.waiting_for = note.to_owned();
        resolve(&empty, &draft)
    };
    assert_eq!(
        problem(&waiting("Invoice", "")),
        Some(Reason::WaitingForRequired)
    );
    assert_eq!(
        problem(&waiting("Invoice", " \n\u{3000}")),
        Some(Reason::WaitingForRequired)
    );
    // U+001C..U+001F are blank to Python's `str.strip()`, like the server.
    assert_eq!(
        problem(&waiting("Invoice", "\u{1C}\u{1D} \u{1E}\u{1F}")),
        Some(Reason::WaitingForRequired)
    );
    assert_eq!(
        waiting("Invoice", "\u{1F}Ana\u{1C}").waiting_for.as_deref(),
        Some("Ana")
    );
    assert!(
        waiting("Invoice", "  \u{410}\u{43D}\u{43D}\u{430}  ")
            .problem
            .is_none()
    );
    let note = "w".repeat(500);
    assert!(waiting("Invoice", &format!("  {note}  ")).problem.is_none());
    assert_eq!(
        problem(&waiting("Invoice", &format!("{note}w"))),
        Some(Reason::TextLength)
    );
    let mut next = Draft::new("Invoice");
    next.list = OpenList::Next;
    next.waiting_for = "w".repeat(900);
    let ignored = resolve(&empty, &next);
    assert!(ignored.problem.is_none() && ignored.waiting_for.is_none());

    let mut notes = Draft::new("Plan");
    notes.details = "n".repeat(20_000);
    assert!(resolve(&empty, &notes).problem.is_none());
    notes.details = "n".repeat(20_001);
    assert_eq!(problem(&resolve(&empty, &notes)), Some(Reason::TextLength));
    notes.details = "  \n ".to_owned();
    assert!(
        resolve(&empty, &notes).details.is_none(),
        "blank notes are none"
    );

    // Reading order: title, project, tags, waiting note, notes.
    let long = "x".repeat(501);
    let archived = rs(&[("p-a", "Archive", "archived")], &[]);
    let mut draft = Draft::new(format!("@{long}"));
    draft.list = OpenList::Waiting;
    draft.details = long.repeat(2);
    assert_eq!(problem(&resolve(&empty, &draft)), Some(Reason::EmptyTitle));
    draft.text = format!("Plan @Archive #{long}");
    assert_eq!(
        problem(&resolve(&archived, &draft)),
        Some(Reason::ProjectNotActive)
    );
    draft.text = format!("Plan #{long}");
    assert_eq!(problem(&resolve(&empty, &draft)), Some(Reason::TextLength));
    let mut late = Draft::new("Plan");
    late.list = OpenList::Waiting;
    late.details = "n".repeat(20_001);
    assert_eq!(
        problem(&resolve(&empty, &late)),
        Some(Reason::WaitingForRequired)
    );
}

fn mint_project() -> ProjectId {
    ProjectId::parse(P1).expect("id")
}

fn mint_tag() -> TagId {
    // Distinct on every call.
    use std::sync::atomic::{AtomicUsize, Ordering};
    static NEXT: AtomicUsize = AtomicUsize::new(1);
    let n = NEXT.fetch_add(1, Ordering::Relaxed);
    TagId::parse(format!("tag_00000000-0000-4000-8000-{n:012}")).expect("id")
}

#[test]
fn smart_add_026_fr_002_propose_builds_the_task_smart_add_payload() {
    let state = web_default();
    let mut minted = Vec::new();
    let mut counter = 0;
    let payload = propose(
        &state,
        &Draft::new("Call partner #calls @\"Vendor launch\" #new @\"Brand New\" #\"Also New\""),
        || ProjectId::parse(P2).expect("id"),
        || {
            counter += 1;
            let id = format!("tag_00000000-0000-4000-8000-00000000009{counter}");
            minted.push(id.clone());
            TagId::parse(id).expect("id")
        },
    )
    .expect("proposal");
    // Project first, then each new tag, in order; existing records by ID.
    let value = serde_json::to_value(&payload).expect("payload");
    assert_eq!(value["title"], "Call partner");
    assert_eq!(value["state"], "inbox");
    assert_eq!(
        value["project"],
        json!({ "name": "Brand New", "proposed_id": P2 })
    );
    assert_eq!(
        value["tags"],
        json!([
            { "id": "tag-calls" },
            { "name": "new", "proposed_id": minted[0] },
            { "name": "Also New", "proposed_id": minted[1] },
        ])
    );
    assert_eq!(minted.len(), 2);

    // Blocked captures are refused with the first problem and mint nothing.
    let blocked = propose(
        &state,
        &Draft::new("#work"),
        || panic!("no project"),
        || panic!("no tag"),
    );
    assert_eq!(blocked.expect_err("empty title").reason, Reason::EmptyTitle);

    // The structured fields travel with the proposal; the grammar never reads a date.
    let mut draft = Draft::new("Pay invoice due tomorrow");
    draft.list = OpenList::Waiting;
    draft.waiting_for = "  Anna ".to_owned();
    draft.due_date = Some(serde_json::from_value(json!("2026-10-31")).expect("day"));
    draft.details = " keep  spacing ".to_owned();
    let structured =
        serde_json::to_value(propose(&state, &draft, mint_project, mint_tag).expect("proposal"))
            .expect("payload");
    assert_eq!(structured["title"], "Pay invoice due tomorrow");
    assert_eq!(structured["waiting_for"], "Anna");
    assert_eq!(structured["due_date"], "2026-10-31");
    assert_eq!(structured["details"], " keep  spacing ");
}

// ------------------------------------------------------------------------ decide

#[test]
fn smart_add_026_fr_002_creates_unknown_classifications_and_the_task_atomically() {
    // test_smart_add_creates_unknown_classifications_and_clean_task_atomically
    let state = rs(
        &[("project_aaaaaaaaaaaa", "Admin", "active")],
        &[("tag_aaaaaaaaaaaa", "errands", "active")],
    );
    let set = ok(
        &state,
        json!({
            "title": "Call supplier", "state": "next",
            "project": { "name": "Vendor launch", "proposed_id": P1 },
            "tags": [ { "name": "calls", "proposed_id": T1 }, { "name": "vendor", "proposed_id": T2 } ]
        }),
    );
    assert_eq!(
        order(&set),
        [
            EntityType::Project,
            EntityType::Tag,
            EntityType::Tag,
            EntityType::Task
        ]
    );
    let landed = landed(&set);
    assert_eq!(landed.projects[0].name.as_str(), "Vendor launch");
    assert_eq!(landed.projects[0].id.as_str(), P1);
    assert_eq!(
        landed
            .tags
            .iter()
            .map(|t| t.name.as_str())
            .collect::<Vec<_>>(),
        ["calls", "vendor"]
    );
    assert_eq!(landed.task.title.as_str(), "Call supplier");
    assert_eq!(landed.task.state, TaskState::Next);
    assert_eq!(
        landed.task.project_id.as_ref().map(ProjectId::as_str),
        Some(P1)
    );
    assert_eq!(
        landed
            .task
            .tag_ids
            .iter()
            .map(TagId::as_str)
            .collect::<Vec<_>>(),
        [T1, T2]
    );
    // A task created in Next starts its formulation, like `task.create`.
    assert_eq!(
        landed.task.formulation.as_ref().map(|f| f.id.as_str()),
        Some(FORM_A)
    );
    assert_eq!(landed.task.revision.to_u64(), Some(1));
    assert_eq!(
        set.result.id_bindings,
        [
            binding(EntityType::Project, P1, P1),
            binding(EntityType::Tag, T1, T1),
            binding(EntityType::Tag, T2, T2),
        ]
    );
}

#[test]
fn smart_add_026_fr_002_reuses_existing_names_and_ids_and_deduplicates_tags() {
    // test_smart_add_resolves_existing_names_and_ids_and_deduplicates_tags
    let state = rs(
        &[
            ("project_aaaaaaaaaaaa", "Admin", "active"),
            ("project_bbbbbbbbbbbb", "Launch v2", "active"),
        ],
        &[
            ("tag_aaaaaaaaaaaa", "Errands", "active"),
            ("tag_bbbbbbbbbbbb", "Deep Work", "active"),
        ],
    );
    let set = ok(
        &state,
        json!({
            "title": "Draft update",
            "project": { "name": " launch   V2 ", "proposed_id": P1 },
            "tags": [
                { "id": "tag_bbbbbbbbbbbb" },
                { "name": "deep work", "proposed_id": T2 },
                { "name": "Calls", "proposed_id": T1 }
            ]
        }),
    );
    // Only the genuinely new tag is created; the project and Deep Work are reused.
    assert_eq!(order(&set), [EntityType::Tag, EntityType::Task]);
    let landed = landed(&set);
    assert_eq!(landed.tags[0].name.as_str(), "Calls");
    assert_eq!(
        landed.task.project_id.as_ref().map(ProjectId::as_str),
        Some("project_bbbbbbbbbbbb")
    );
    assert_eq!(
        landed
            .task
            .tag_ids
            .iter()
            .map(TagId::as_str)
            .collect::<Vec<_>>(),
        ["tag_bbbbbbbbbbbb", T1],
        "the id and the name that reach one tag are one membership"
    );
    // The receipt keeps every by-name alias: reuse resolves the proposed ID to
    // the accepted one, so the two IDs differ and the binding is the only link.
    assert_eq!(
        set.result.id_bindings,
        [
            binding(EntityType::Project, P1, "project_bbbbbbbbbbbb"),
            binding(EntityType::Tag, T2, "tag_bbbbbbbbbbbb"),
            binding(EntityType::Tag, T1, T1),
        ]
    );
}

#[test]
fn smart_add_026_fr_002_accepts_absent_classifications_and_project_ids() {
    // test_smart_add_accepts_absent_classifications_and_project_ids
    let state = rs(&[("project_aaaaaaaaaaaa", "Admin", "active")], &[]);
    let plain = ok(&state, json!({ "title": "Plain capture" }));
    assert_eq!(order(&plain), [EntityType::Task]);
    let task = landed(&plain).task;
    assert!(task.project_id.is_none() && task.tag_ids.is_empty());
    assert_eq!(task.state, TaskState::Inbox);
    assert!(plain.result.id_bindings.is_empty());

    let by_id = ok(
        &state,
        json!({ "title": "Project capture", "project": { "id": "project_aaaaaaaaaaaa" } }),
    );
    assert_eq!(order(&by_id), [EntityType::Task]);
    assert_eq!(
        landed(&by_id)
            .task
            .project_id
            .as_ref()
            .map(ProjectId::as_str),
        Some("project_aaaaaaaaaaaa")
    );
    assert!(
        by_id.result.id_bindings.is_empty(),
        "an id reference needs no alias"
    );
}

#[test]
fn smart_add_026_fr_002_references_are_a_strict_either_or() {
    // test_smart_add_validates_strict_refs_waiting_and_no_partial_writes
    for project in [
        json!({ "id": "p1", "name": "Project" }),
        json!({ "id": "p1", "name": "Project", "proposed_id": P1 }),
        json!({ "id": "p1", "proposed_id": P1 }),
        json!({ "name": "Project" }),
        json!({ "proposed_id": P1 }),
        json!({}),
        json!({ "name": "Project", "proposed_id": P1, "extra": true }),
    ] {
        let error = try_command(
            "task.smart_add",
            TASK,
            json!({ "title": "Bad ref", "project": project.clone() }),
        )
        .expect_err("a reference is an id, or a name with its proposed id");
        assert_eq!(error.reason, Reason::InvalidPayload, "{project}");
    }
    let tags = try_command(
        "task.smart_add",
        TASK,
        json!({ "title": "Bad", "tags": [ { "name": "ok", "proposed_id": T1 }, { "name": "no id" } ] }),
    );
    assert_eq!(
        tags.expect_err("tag refs are strict too").reason,
        Reason::InvalidPayload
    );
}

#[test]
fn smart_add_026_fr_002_waiting_is_checked_first_and_nothing_is_written_on_refusal() {
    // test_smart_add_validates_strict_refs_waiting_and_no_partial_writes
    let state = ReadSet::default();
    let error = refusal(
        &state,
        json!({ "title": "Await reply", "state": "waiting", "tags": [ { "name": "waiting", "proposed_id": T1 } ] }),
    );
    assert_eq!(error.reason, Reason::WaitingForRequired);
    assert_eq!(error.field.as_deref(), Some("waiting_for"));

    for note in ["", "   ", "\u{1C}\u{1D}\u{1E}\u{1F}"] {
        let blank = refusal(
            &state,
            json!({ "title": "Await reply", "state": "waiting", "waiting_for": note }),
        );
        assert_eq!(blank.reason, Reason::WaitingForRequired, "{note:?}");
    }

    // The Waiting note comes before the project, which comes before the tags.
    let both = refusal(
        &state,
        json!({ "title": "t", "state": "waiting", "project": { "id": "project_gone" } }),
    );
    assert_eq!(both.reason, Reason::WaitingForRequired);
    let project_first = refusal(
        &state,
        json!({ "title": "t", "project": { "id": "project_gone" }, "tags": [ { "id": "tag_gone" } ] }),
    );
    assert_eq!(
        (project_first.reason, project_first.entity.map(|e| e.0)),
        (Reason::NotFound, Some(EntityType::Project))
    );

    let waiting = ok(
        &state,
        json!({ "title": "Await reply", "state": "waiting", "waiting_for": "  Anna  " }),
    );
    let task = landed(&waiting).task;
    assert_eq!(task.waiting_for.as_ref().map(|w| w.as_str()), Some("Anna"));
    assert_eq!(task.waiting_since.as_ref().map(|i| i.as_str()), Some(NOW));
    // A note outside Waiting is dropped, as `task.create` does.
    let next = ok(
        &state,
        json!({ "title": "Do it", "state": "next", "waiting_for": "Anna" }),
    );
    assert!(landed(&next).task.waiting_for.is_none());
}

#[test]
fn smart_add_026_fr_002_inactive_projects_and_tags_are_refused_by_id_and_by_name() {
    // test_smart_add_rejects_inactive_project_and_tag_refs
    let state = rs(
        &[("project_aaaaaaaaaaaa", "Dormant", "archived")],
        &[("tag_aaaaaaaaaaaa", "stale", "deleted")],
    );
    let cases = [
        (
            json!({ "project": { "id": "project_aaaaaaaaaaaa" } }),
            Reason::ProjectNotActive,
        ),
        (
            json!({ "tags": [ { "id": "tag_aaaaaaaaaaaa" } ] }),
            Reason::TagNotActive,
        ),
        (
            json!({ "project": { "name": "Dormant", "proposed_id": P1 } }),
            Reason::ProjectNotActive,
        ),
        (
            json!({ "tags": [ { "name": "stale", "proposed_id": T1 } ] }),
            Reason::TagNotActive,
        ),
        (
            json!({ "tags": [ { "name": "STALE", "proposed_id": T1 } ] }),
            Reason::TagNotActive,
        ),
    ];
    for (extra, reason) in cases {
        let mut payload = json!({ "title": "Bad" });
        payload
            .as_object_mut()
            .expect("object")
            .extend(extra.as_object().expect("object").clone());
        let error = refusal(&state, payload);
        assert_eq!(error.reason, reason, "{extra}");
    }
    // An unknown id is not found, not "inactive".
    let missing = refusal(
        &state,
        json!({ "title": "t", "tags": [ { "id": "tag_zzzzzzzzzzzz" } ] }),
    );
    assert_eq!(missing.reason, Reason::NotFound);
}

#[test]
fn smart_add_026_fr_002_an_active_namesake_wins_over_an_inactive_one() {
    let state = rs(
        &[
            ("project_a", "Launch", "archived"),
            ("project_b", "launch", "active"),
        ],
        &[("tag_a", "Focus", "deleted"), ("tag_b", "focus", "active")],
    );
    let set = ok(
        &state,
        json!({
            "title": "t",
            "project": { "name": "LAUNCH", "proposed_id": P1 },
            "tags": [ { "name": "FOCUS", "proposed_id": T1 } ]
        }),
    );
    assert_eq!(order(&set), [EntityType::Task]);
    let task = landed(&set).task;
    assert_eq!(
        task.project_id.as_ref().map(ProjectId::as_str),
        Some("project_b")
    );
    assert_eq!(
        task.tag_ids.iter().map(TagId::as_str).collect::<Vec<_>>(),
        ["tag_b"]
    );
}

#[test]
fn smart_add_026_fr_002_display_forms_are_stored_and_tags_drop_one_at_sign() {
    let set = ok(
        &ReadSet::default(),
        json!({
            "title": "t",
            "project": { "name": "  Fresh   Project  ", "proposed_id": P1 },
            "tags": [ { "name": " @Sigil  Tag", "proposed_id": T1 } ]
        }),
    );
    let landed = landed(&set);
    assert_eq!(landed.projects[0].name.as_str(), "Fresh Project");
    assert_eq!(landed.tags[0].name.as_str(), "Sigil Tag");

    let empty = refusal(
        &ReadSet::default(),
        json!({ "title": "t", "tags": [ { "name": "@", "proposed_id": T1 } ] }),
    );
    assert_eq!(empty.reason, Reason::EmptyName);
    let blank = refusal(
        &ReadSet::default(),
        json!({ "title": "t", "project": { "name": "   ", "proposed_id": P1 } }),
    );
    assert_eq!(blank.reason, Reason::EmptyName);
}

#[test]
fn smart_add_026_fr_002_names_that_key_alike_in_one_request_are_one_new_record() {
    let set = ok(
        &ReadSet::default(),
        json!({
            "title": "t",
            "tags": [
                { "name": "Dup", "proposed_id": T1 },
                { "name": "dup", "proposed_id": T2 },
                { "name": "Other", "proposed_id": T3 }
            ]
        }),
    );
    let landed = landed(&set);
    assert_eq!(
        landed
            .tags
            .iter()
            .map(|t| t.id.as_str())
            .collect::<Vec<_>>(),
        [T1, T3]
    );
    assert_eq!(
        landed
            .task
            .tag_ids
            .iter()
            .map(TagId::as_str)
            .collect::<Vec<_>>(),
        [T1, T3]
    );
    assert_eq!(
        set.result.id_bindings,
        [
            binding(EntityType::Tag, T1, T1),
            binding(EntityType::Tag, T2, T1),
            binding(EntityType::Tag, T3, T3),
        ]
    );
}

#[test]
fn smart_add_026_fr_002_proposed_ids_and_the_task_id_must_be_free() {
    let state = rs(
        &[(P2, "Elsewhere", "active")],
        &[(T3, "elsewhere", "active")],
    );
    let project = refusal(
        &state,
        json!({ "title": "t", "project": { "name": "New", "proposed_id": P2 } }),
    );
    assert_eq!(
        (project.reason, project.field.as_deref()),
        (Reason::IdAlreadyExists, Some("project"))
    );
    let tag = refusal(
        &state,
        json!({ "title": "t", "tags": [ { "name": "new", "proposed_id": T3 } ] }),
    );
    assert_eq!(tag.reason, Reason::IdAlreadyExists);
    let reused = refusal(
        &ReadSet::default(),
        json!({ "title": "t", "tags": [
            { "name": "one", "proposed_id": T1 }, { "name": "two", "proposed_id": T1 }
        ] }),
    );
    assert_eq!(reused.reason, Reason::IdAlreadyExists);

    let taken = read_set_of(&[], &[], &[task_json(TASK, "inbox", "0")]);
    assert_eq!(
        refusal(&taken, json!({ "title": "t" })).reason,
        Reason::IdAlreadyExists
    );
}

#[test]
fn smart_add_026_fr_008_created_ids_need_the_native_shape_and_legacy_ids_stay_references() {
    let state = rs(
        &[("project_aaaaaaaaaaaa", "Admin", "active")],
        &[("tag_aaaaaaaaaaaa", "errands", "active")],
    );
    let task = |id: &str| {
        let payload = json!({ "title": "t" });
        let command = try_command("task.smart_add", id, payload).expect("smart add command");
        smart_add::decide(&state, &command, &inputs())
    };
    // The task: malformed and legacy-shaped IDs are never persisted.
    for id in [
        "x",
        "t_new",
        "task_abc123def456",
        "task_00000000-0000-4000-8000-0000000000A1",
    ] {
        let err = task(id).expect_err(id);
        assert_eq!(err.reason, Reason::InvalidValue, "{id}");
        assert_eq!(err.field.as_deref(), Some("TaskId"), "{id}");
    }
    assert!(task(TASK).is_ok());

    // A created project or tag: the same rule, for the IDs the request mints.
    for bad in [
        "x",
        "project_abc123def456",
        "tag_00000000-0000-4000-8000-000000000001",
    ] {
        let err = refusal(
            &state,
            json!({ "title": "t", "project": { "name": "New", "proposed_id": bad } }),
        );
        assert_eq!(err.reason, Reason::InvalidValue, "{bad}");
        assert_eq!(err.field.as_deref(), Some("ProjectId"), "{bad}");
    }
    for bad in [
        "x",
        "tag_abc123def456",
        "project_00000000-0000-4000-8000-000000000001",
    ] {
        let err = refusal(
            &state,
            json!({ "title": "t", "tags": [ { "name": "new", "proposed_id": bad } ] }),
        );
        assert_eq!(err.reason, Reason::InvalidValue, "{bad}");
        assert_eq!(err.field.as_deref(), Some("TagId"), "{bad}");
    }
    // Nothing is created when the name resolves to an existing record: the
    // proposed ID is only an alias there, and existing legacy IDs stay valid.
    let set = ok(
        &state,
        json!({ "title": "t",
                "project": { "name": "admin", "proposed_id": "project_abc123def456" },
                "tags": [ { "name": "errands", "proposed_id": "tag_abc123def456" } ] }),
    );
    assert_eq!(order(&set), [EntityType::Task]);
    let set = ok(
        &state,
        json!({ "title": "t", "project": { "id": "project_aaaaaaaaaaaa" },
                "tags": [ { "id": "tag_aaaaaaaaaaaa" } ] }),
    );
    assert_eq!(order(&set), [EntityType::Task]);
    // Native IDs are accepted.
    let set = ok(
        &state,
        json!({ "title": "t", "project": { "name": "New", "proposed_id": P1 },
                "tags": [ { "name": "new", "proposed_id": T1 } ] }),
    );
    assert_eq!(
        order(&set),
        [EntityType::Project, EntityType::Tag, EntityType::Task]
    );
}

#[test]
fn smart_add_026_fr_002_a_later_smart_add_reuses_what_an_earlier_one_created() {
    // Two captures name the same classification: the second proposes fresh IDs
    // and the receipt binds them to the first capture's records (the lost ACK
    // and rename scenarios of sync-v1 §13 rely on these bindings).
    let first = ok(
        &ReadSet::default(),
        json!({
            "title": "first",
            "project": { "name": "Launch", "proposed_id": P1 },
            "tags": [ { "name": "calls", "proposed_id": T1 } ]
        }),
    );
    let state = applied(&ReadSet::default(), &first);
    let second = smart_add::decide(
        &state,
        &try_command(
            "task.smart_add",
            "task_00000000-0000-4000-8000-0000000000a2",
            json!({
                "title": "second",
                "project": { "name": "launch", "proposed_id": P2 },
                "tags": [ { "name": "CALLS", "proposed_id": T2 } ]
            }),
        )
        .expect("command"),
        &inputs(),
    )
    .expect("second capture");
    assert_eq!(
        order(&second),
        [EntityType::Task],
        "nothing is created twice"
    );
    assert_eq!(
        second.result.id_bindings,
        [
            binding(EntityType::Project, P2, P1),
            binding(EntityType::Tag, T2, T1)
        ]
    );
    let task = landed(&second).task;
    assert_eq!(task.project_id.as_ref().map(ProjectId::as_str), Some(P1));
    assert_eq!(
        task.tag_ids.iter().map(TagId::as_str).collect::<Vec<_>>(),
        [T1]
    );
    // The new task is last in its list.
    let inbox = read_set_of(&[], &[], &[task_json("task_x", "inbox", "4")]);
    let ordered = ok(&inbox, json!({ "title": "next in line" }));
    assert_eq!(landed(&ordered).task.order_key.to_u64(), Some(5));
}

#[test]
fn smart_add_026_fr_017_dates_stay_calendar_days_and_priority_is_carried() {
    let set = ok(
        &ReadSet::default(),
        json!({ "title": "Pay", "due_date": "2026-10-31", "priority": "high", "details": "x" }),
    );
    let task = landed(&set).task;
    assert_eq!(
        task.due_date.as_ref().map(|d| d.as_str()),
        Some("2026-10-31")
    );
    assert_eq!(
        serde_json::to_value(task.priority).expect("priority"),
        json!("high")
    );
    assert_eq!(task.details.as_ref().map(|d| d.as_str()), Some("x"));
    // The date is a day: it is not an instant and not derived from the text.
    let phrase = ok(&ReadSet::default(), json!({ "title": "Pay due tomorrow" }));
    assert!(landed(&phrase).task.due_date.is_none());
}

#[test]
fn smart_add_026_fr_002_a_proposal_decides_without_any_provider() {
    // Basic capture is deterministic end to end: text -> proposal -> decision.
    let state = web_default();
    let draft = Draft::new("Draft update #work @\"Launch v2\" #fresh");
    let payload = propose(&state, &draft, mint_project, || {
        TagId::parse(T3).expect("id")
    })
    .expect("proposal");
    let set = ok(&state, serde_json::to_value(&payload).expect("payload"));
    let landed = landed(&set);
    assert_eq!(landed.task.title.as_str(), "Draft update");
    assert_eq!(
        landed.task.project_id.as_ref().map(ProjectId::as_str),
        Some("project-launch")
    );
    assert_eq!(
        landed
            .task
            .tag_ids
            .iter()
            .map(TagId::as_str)
            .collect::<Vec<_>>(),
        ["tag-work", T3]
    );
    assert_eq!(landed.tags[0].name.as_str(), "fresh");
    assert_eq!(set.result.id_bindings, [binding(EntityType::Tag, T3, T3)]);
}

#[test]
fn smart_add_026_fr_002_literal_task_create_keeps_its_text() {
    // test_literal_task_create_remains_unchanged: `task.create` never parses.
    let command = try_command(
        "task.create",
        TASK,
        json!({ "title": "Call supplier #calls @Vendor" }),
    )
    .expect("task.create");
    assert!(!smart_add::handles(&command.command));
    let set = task_rules::decide(&ReadSet::default(), &command, &inputs()).expect("literal create");
    assert_eq!(order(&set), [EntityType::Task]);
    let task = landed(&set).task;
    assert_eq!(task.title.as_str(), "Call supplier #calls @Vendor");
    assert!(task.project_id.is_none() && task.tag_ids.is_empty());

    // Each family refuses the other's command.
    let refused = smart_add::decide(&ReadSet::default(), &command, &inputs());
    assert_eq!(
        refused.expect_err("not ours").reason,
        Reason::InvalidPayload
    );
    assert!(smart_add::handles(
        &smart_add_command(json!({ "title": "t" })).command
    ));
}
