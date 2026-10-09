//! Parity of the formulation clock with the server rule (tasks.md T013).
//!
//! Runs every section of the canonical `review_formulation_vectors.json` that
//! `backend/tests/test_review_formulation_vectors.py` and the Swift and web
//! suites run, against the actual `src/formulation.rs`. Each test counts the
//! cases it executed, so an empty or truncated section fails.
//!
//! The family source is compiled in place (`#[path]`), with the same crate
//! paths it uses inside `bb-domain`, so this runner does not depend on how the
//! library registers the module.

mod support;

pub use bb_domain::{calendar, normalization, types};

#[allow(dead_code)]
#[path = "../src/formulation.rs"]
mod formulation;

use std::collections::BTreeSet;

use bb_domain::calendar::{CalendarDay, UtcInstant};
use bb_domain::types::{DecisionType, DesiredOutcome, Task, TaskState, TaskView};
use formulation::{
    ClockBefore, DecisionInput, FormulationClass, FormulationError, OwnerClockSettings, ParkMarker,
    ReleasedClock, TaskClock,
};
use serde_json::{Map, Value, json};
use support::{cases, text};

// ------------------------------------------------------------------ helpers

fn at(iso: &str) -> UtcInstant {
    UtcInstant::parse_rfc3339(iso).unwrap_or_else(|error| panic!("{iso}: {error}"))
}

fn at_opt(value: &Value) -> Option<UtcInstant> {
    value.as_str().map(at)
}

fn iso(value: Option<UtcInstant>) -> Value {
    value.map_or(Value::Null, |instant| Value::String(instant.to_rfc3339()))
}

fn day(value: &Value) -> Option<CalendarDay> {
    value
        .as_str()
        .map(|text| CalendarDay::parse_iso(text).unwrap_or_else(|error| panic!("{text}: {error}")))
}

fn state(value: &Value) -> Option<TaskState> {
    value.as_str().map(|name| {
        TaskState::from_wire(name).unwrap_or_else(|| panic!("unknown task state {name}"))
    })
}

fn count(value: &Value) -> u32 {
    u32::try_from(value.as_u64().expect("a count")).expect("a small count")
}

fn string(value: &Value) -> Option<String> {
    value.as_str().map(str::to_owned)
}

fn settings_from(raw: &Value) -> OwnerClockSettings {
    OwnerClockSettings::new(
        count(&raw["threshold_days"]),
        text(raw, "time_zone"),
        at_opt(&raw["owner_park_floor_at"]),
        at_opt(&raw["activated_at"]),
    )
    .unwrap_or_else(|error| panic!("settings {raw}: {error}"))
}

fn settings_to(settings: &OwnerClockSettings) -> Value {
    json!({
        "threshold_days": settings.threshold_days(),
        "time_zone": settings.time_zone(),
        "owner_park_floor_at": iso(settings.owner_park_floor_at()),
        "activated_at": iso(settings.activated_at()),
    })
}

fn clock_before_from(raw: &Value) -> ClockBefore {
    ClockBefore {
        started_at: at(text(raw, "started_at")),
        extended_at: at_opt(&raw["extended_at"]),
        extension_reason: string(&raw["extension_reason"]),
        park_floor_at: at_opt(&raw["park_floor_at"]),
        stalled_before: count(&raw["stalled_before"]),
    }
}

fn released_from(raw: &Value) -> ReleasedClock {
    ReleasedClock {
        formulation_id: text(raw, "formulation_id").to_owned(),
        started_at: at(text(raw, "started_at")),
        extended_at: at_opt(&raw["extended_at"]),
        extension_reason: string(&raw["extension_reason"]),
        park_floor_at: at_opt(&raw["park_floor_at"]),
        stalled_before: count(&raw["stalled_before"]),
    }
}

fn released_to(value: &ReleasedClock) -> Value {
    json!({
        "formulation_id": value.formulation_id,
        "started_at": iso(Some(value.started_at)),
        "extended_at": iso(value.extended_at),
        "extension_reason": value.extension_reason,
        "park_floor_at": iso(value.park_floor_at),
        "stalled_before": value.stalled_before,
    })
}

/// A clock from a transition `before` or a classification `task`; a started
/// clock without an explicit id gets `form_<task id>` (the server helper's).
fn clock_from(raw: &Value, task_id: &str) -> TaskClock {
    let started = at_opt(&raw["formulation_started_at"]);
    let default_id = started.map(|_| format!("form_{task_id}"));
    let formulation_id = match raw.get("formulation_id") {
        Some(value) => string(value),
        None => default_id,
    };
    let parked = raw
        .get("parked")
        .filter(|value| !value.is_null())
        .map(|parked| ParkMarker {
            at: at(text(parked, "at")),
            formulation_id: text(parked, "formulation_id").to_owned(),
            from_revision: parked["from_revision"].as_u64(),
            clock_before: Some(clock_before_from(&parked["clock_before"])),
        });
    TaskClock {
        state: state(&raw["state"]),
        title: string(&raw["title"]),
        revision: raw.get("revision").and_then(Value::as_u64).unwrap_or(1),
        formulation_id,
        formulation_started_at: started,
        formulation_extended_at: at_opt(&raw["formulation_extended_at"]),
        formulation_extension_reason: string(&raw["formulation_extension_reason"]),
        formulation_park_floor_at: at_opt(&raw["formulation_park_floor_at"]),
        consecutive_stalled_formulations: raw
            .get("consecutive_stalled_formulations")
            .map_or(0, count),
        due_date: day(&raw["due_date"]),
        parked,
    }
}

fn clock_to(clock: &TaskClock) -> Value {
    let parked = clock.parked.as_ref().map_or(Value::Null, |marker| {
        let before = marker
            .clock_before
            .as_ref()
            .expect("vector parks carry a clock");
        json!({
            "at": iso(Some(marker.at)),
            "formulation_id": marker.formulation_id,
            "from_revision": marker.from_revision,
            "clock_before": {
                "started_at": iso(Some(before.started_at)),
                "extended_at": iso(before.extended_at),
                "extension_reason": before.extension_reason,
                "park_floor_at": iso(before.park_floor_at),
                "stalled_before": before.stalled_before,
            },
        })
    });
    json!({
        "state": clock.state.map(TaskState::as_str),
        "title": clock.title,
        "revision": clock.revision,
        "formulation_id": clock.formulation_id,
        "formulation_started_at": iso(clock.formulation_started_at),
        "formulation_extended_at": iso(clock.formulation_extended_at),
        "formulation_extension_reason": clock.formulation_extension_reason,
        "formulation_park_floor_at": iso(clock.formulation_park_floor_at),
        "consecutive_stalled_formulations": clock.consecutive_stalled_formulations,
        "due_date": clock.due_date.map(|day| day.iso_string()),
        "parked": parked,
    })
}

/// Class, derived instants and aggregates as a classification `expect`.
fn derived_view(clock: &TaskClock, settings: &OwnerClockSettings, now: UtcInstant) -> Value {
    let instants = formulation::derive_instants(clock, settings);
    let class = formulation::classify(clock, settings, now);
    json!({
        "class": class.as_str(),
        "ageing_at": iso(instants.map(|derived| derived.ageing_at)),
        "ask_at": iso(instants.map(|derived| derived.ask_at)),
        "park_due_at": iso(instants.map(|derived| derived.park_due_at)),
        "paused_until": iso(instants.and_then(|derived| derived.paused_until)),
        "asks_for_decision": class.asks_for_decision(),
        "restart_eligible": formulation::restart_eligible(clock, settings, now),
        "third_stall": formulation::third_stall(clock, settings, now),
    })
}

fn decision_input(event: &Value) -> DecisionInput<'_> {
    DecisionInput {
        title: event.get("title").and_then(Value::as_str),
        reason: event.get("reason").and_then(Value::as_str),
        new_formulation_id: event.get("new_formulation_id").and_then(Value::as_str),
    }
}

fn decide(
    clock: &TaskClock,
    event: &Value,
    settings: &OwnerClockSettings,
    now: UtcInstant,
) -> Result<TaskClock, FormulationError> {
    let name = text(event, "decision_type");
    let decision = DecisionType::from_wire(name).unwrap_or_else(|| panic!("decision {name}"));
    formulation::decide(clock, decision, settings, now, &decision_input(event))
}

struct Outcome {
    /// `None` is "auto-park not applied".
    clock: Option<TaskClock>,
    settings: OwnerClockSettings,
    bulk_clock_before: Option<ReleasedClock>,
}

/// Interprets one vector event the way the server's `apply_event` does.
fn apply_event(
    clock: &TaskClock,
    settings: &OwnerClockSettings,
    event: &Value,
    now: UtcInstant,
) -> Result<Outcome, FormulationError> {
    let mut settings = settings.clone();
    let mut bulk_clock_before = None;
    let id = |key: &str| event.get(key).and_then(Value::as_str);
    let new_id = || id("new_formulation_id").expect("the event names new_formulation_id");
    let result = match text(event, "type") {
        "create_in_next" => Some(formulation::create_in_next(
            text(event, "title"),
            new_id(),
            now,
        )),
        "update_title" => Some(formulation::change_title(
            clock,
            text(event, "title"),
            &settings,
            now,
            new_id(),
        )),
        "update_due_date" => Some(formulation::change_due_date(
            clock,
            day(&event["due_date"]),
            now,
        )),
        "update_other" => Some(formulation::edit_without_clock(clock)),
        "transition" => {
            let target = state(&event["to"]).expect("a target list");
            Some(formulation::move_to(
                clock,
                target,
                &settings,
                now,
                id("new_formulation_id"),
            )?)
        }
        "decide" => Some(decide(clock, event, &settings, now)?),
        "undo_decision" => {
            let before = clock_from(&event["task_before"], "task_vector");
            Some(formulation::restore(clock, &before, &settings))
        }
        "auto_park" => formulation::auto_park(clock, &settings, now),
        "yield_reversal" => {
            let reversed = formulation::reverse_park(clock)?;
            Some(decide(&reversed, &event["decision"], &settings, now)?)
        }
        "bulk_release" => {
            let (released, stored) = formulation::release(clock, &settings, now);
            bulk_clock_before = Some(stored.expect("a release of a Next task stores its clock"));
            Some(released)
        }
        "undo_bulk_release" => {
            let previous = state(&event["previous_state"]).expect("a previous list");
            let stored = released_from(&event["clock_before"]);
            Some(formulation::undo_release(clock, previous, Some(&stored)))
        }
        "activate" => {
            let when = at(text(event, "at"));
            let activated = formulation::activate_owner(&settings, when, id("time_zone"))?;
            let result = if activated == settings {
                clock.clone()
            } else {
                formulation::activate_clock(clock, when, new_id())
            };
            settings = activated;
            Some(result)
        }
        "repair" => Some(formulation::repair_clock(clock, now, new_id())),
        "sweep_gap" => {
            settings = formulation::apply_sweep_gap(&settings, now);
            Some(clock.clone())
        }
        "threshold_change" => {
            settings = formulation::change_threshold(&settings, count(&event["to"]), now)?;
            Some(clock.clone())
        }
        "time_zone_change" => {
            let changed = formulation::change_time_zone(&settings, text(event, "to"))?;
            let result = if changed == settings {
                clock.clone()
            } else {
                formulation::raise_due_floor(clock, now)
            };
            settings = changed;
            Some(result)
        }
        other => panic!("unknown vector event {other:?}"),
    };
    Ok(Outcome {
        clock: result,
        settings,
        bulk_clock_before,
    })
}

fn run_transition(vector: &Value) -> Result<Outcome, FormulationError> {
    apply_event(
        &clock_from(&vector["before"], "task_vector"),
        &settings_from(&vector["settings"]),
        &vector["event"],
        at(text(vector, "now")),
    )
}

fn object<'a>(value: &'a Value, what: &str) -> &'a Map<String, Value> {
    value
        .as_object()
        .unwrap_or_else(|| panic!("{what} is not an object"))
}

/// Fails unless exactly `expected` cases ran, and at least one.
fn ran_all(section: &str, ran: usize, expected: usize) {
    assert!(ran > 0, "{section}: no case executed");
    assert_eq!(
        ran, expected,
        "{section}: executed cases differ from the file"
    );
}

// ------------------------------------------------------------ vector sections

#[test]
fn formulation_026_fr_002_normalisation_vectors_match_the_server() {
    let section = cases(support::formulation(), "normalisation");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        let (old, new) = (text(case, "old"), text(case, "new"));
        assert_eq!(
            formulation::formulation_key(old),
            text(case, "old_key"),
            "{id} old"
        );
        assert_eq!(
            formulation::formulation_key(new),
            text(case, "new_key"),
            "{id} new"
        );
        assert_eq!(
            formulation::is_substantive(old, new),
            case["substantive"].as_bool().expect("substantive flag"),
            "{id}"
        );
        ran += 1;
    }
    ran_all("normalisation", ran, section.len());
}

#[test]
fn formulation_026_fr_016_classification_vectors_match_the_server() {
    let section = cases(support::formulation(), "classification");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        let clock = clock_from(&case["task"], "task_vector");
        let settings = settings_from(&case["settings"]);
        let derived = derived_view(&clock, &settings, at(text(case, "now")));
        assert_eq!(derived, case["expect"], "{id}");
        ran += 1;
    }
    ran_all("classification", ran, section.len());
}

/// Every classification vector also holds through the stored-task bridge: the
/// same class and advisory instants come out of a `Task`/`TaskView` pair, in
/// whatever offset spelling the stored instants use.
#[test]
fn formulation_026_fr_016_stored_tasks_classify_and_fill_the_view_like_the_vectors() {
    let section = cases(support::formulation(), "classification");
    let mut ran = 0;
    for case in section {
        let id = text(case, "id");
        let raw = &case["task"];
        let (Some(started), Some(next)) =
            (raw["formulation_started_at"].as_str(), state(&raw["state"]))
        else {
            continue;
        };
        if next != TaskState::Next {
            continue;
        }
        let task = stored_task(raw, started);
        let settings = settings_from(&case["settings"]);
        let now = at(text(case, "now"));
        let expect = &case["expect"];

        let class = formulation::classify_task(&task, &settings, now).expect("a readable task");
        assert_eq!(class.as_str(), text(expect, "class"), "{id}");

        let mut view = TaskView::new(&task, Vec::new(), Vec::new());
        formulation::fill_advisory_instants(&mut view, &task, &settings).expect("fills");
        let formulation_view = view
            .formulation
            .expect("a Next task with a clock has a view");
        let wire = |instant: Option<&bb_domain::types::Instant>| {
            instant.map_or(Value::Null, |value| {
                Value::String(value.as_str().to_owned())
            })
        };
        assert_eq!(
            wire(formulation_view.ageing_at.as_ref()),
            expect["ageing_at"],
            "{id}"
        );
        assert_eq!(
            wire(formulation_view.ask_at.as_ref()),
            expect["ask_at"],
            "{id}"
        );
        assert_eq!(
            wire(formulation_view.park_due_at.as_ref()),
            expect["park_due_at"],
            "{id}"
        );
        assert_eq!(
            wire(formulation_view.paused_until.as_ref()),
            expect["paused_until"],
            "{id}"
        );
        // The stored facts are untouched by the fill.
        assert_eq!(
            formulation_view.consecutive_stalled,
            count(&raw["consecutive_stalled_formulations"])
        );
        ran += 1;
    }
    assert!(
        ran > 0,
        "no Next classification vector ran through the bridge"
    );
}

/// A stored `Task` for a Next classification vector, its instants spelled with
/// a +02:00 offset so the bridge has to normalize them.
fn stored_task(raw: &Value, started: &str) -> Task {
    let offset = |value: &Value| -> Value {
        value.as_str().map_or(Value::Null, |text| {
            let shifted = at(text).plus_seconds(2 * 3600).to_rfc3339();
            Value::String(shifted.replace('Z', "+02:00"))
        })
    };
    serde_json::from_value(json!({
        "id": "task_9f3c2a1b4d5e",
        "title": "Call Bob",
        "details": null,
        "state": "next",
        "project_id": null,
        "tag_ids": [],
        "due_date": raw["due_date"],
        "priority": "none",
        "waiting_for": null,
        "waiting_since": null,
        "order_key": "1",
        "source_capture_ids": [],
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "completed_at": null,
        "cancelled_at": null,
        "revision": "3",
        "consecutive_stalled_formulations": raw["consecutive_stalled_formulations"],
        "formulation": {
            "id": "form_aaaaaaaaaaaa",
            "started_at": offset(&json!(started)),
            "extended_at": offset(&raw["formulation_extended_at"]),
            "extension_reason": raw["formulation_extended_at"].as_str().map(|_| "needs time"),
            "park_floor_at": offset(&raw["formulation_park_floor_at"]),
        },
        "parked": null,
    }))
    .expect("a stored task")
}

#[test]
fn formulation_026_fr_016_transition_vectors_match_the_server() {
    let section = cases(support::formulation(), "transitions");
    let mut ran = 0;
    for vector in section {
        let id = text(vector, "id");
        let expect = &vector["expect"];
        if let Some(reason) = expect.get("error") {
            let refused = run_transition(vector)
                .err()
                .unwrap_or_else(|| panic!("{id}: not refused"));
            assert_eq!(refused.reason(), reason.as_str(), "{id}");
            ran += 1;
            continue;
        }
        let outcome = run_transition(vector).unwrap_or_else(|error| panic!("{id}: {error}"));
        if expect.get("applied") == Some(&Value::Bool(false)) {
            assert!(outcome.clock.is_none(), "{id}: auto-park applied");
            ran += 1;
            continue;
        }
        let result = outcome.clock.unwrap_or_else(|| panic!("{id}: no result"));

        let mut expected = object(&vector["before"], "before").clone();
        for (key, value) in object(expect, "expect") {
            if !matches!(key.as_str(), "error" | "applied" | "bulk_clock_before") {
                expected.insert(key.clone(), value.clone());
            }
        }
        assert_eq!(clock_to(&result), Value::Object(expected), "{id}");
        if let Some(stored) = expect.get("bulk_clock_before") {
            let released = outcome.bulk_clock_before.expect("a bulk record");
            assert_eq!(&released_to(&released), stored, "{id} bulk_clock_before");
        }
        let mut expected_settings = object(&vector["settings"], "settings").clone();
        if let Some(changes) = vector.get("expect_settings") {
            expected_settings.extend(object(changes, "expect_settings").clone());
        }
        assert_eq!(
            settings_to(&outcome.settings),
            Value::Object(expected_settings),
            "{id} settings"
        );
        if let Some(wanted) = vector.get("expect_derived") {
            let derived = derived_view(&result, &outcome.settings, at(text(vector, "now")));
            for (key, value) in object(wanted, "expect_derived") {
                assert_eq!(&derived[key], value, "{id} derived {key}");
            }
        }
        ran += 1;
    }
    ran_all("transitions", ran, section.len());
}

#[test]
fn formulation_026_fr_016_a_chained_vector_starts_where_its_predecessor_ended() {
    let all = cases(support::formulation(), "transitions");
    let mut ran = 0;
    for vector in all.iter().filter(|vector| vector.get("follows").is_some()) {
        let id = text(vector, "id");
        let predecessor = all
            .iter()
            .find(|candidate| candidate["id"] == vector["follows"])
            .unwrap_or_else(|| panic!("{id}: missing predecessor"));
        let ended = run_transition(predecessor)
            .unwrap_or_else(|error| panic!("{id}: {error}"))
            .clock
            .expect("a predecessor result");
        assert_eq!(clock_to(&ended), vector["before"], "{id}");
        ran += 1;
    }
    assert!(ran > 0, "no chained vector ran");
}

#[test]
fn formulation_026_fr_017_queue_order_vectors_match_the_server() {
    let section = cases(support::formulation(), "queue_order");
    let mut ran = 0;
    for vector in section {
        let id = text(vector, "id");
        let tasks: Vec<(String, TaskClock)> = cases(vector, "tasks")
            .iter()
            .map(|task| {
                let task_id = text(task, "id");
                (task_id.to_owned(), clock_from(task, task_id))
            })
            .collect();
        let order = formulation::decision_queue(
            &tasks,
            &settings_from(&vector["settings"]),
            at(text(vector, "now")),
        );
        let expected: Vec<String> = vector["expect"]
            .as_array()
            .expect("an expected order")
            .iter()
            .map(|entry| entry.as_str().expect("an id").to_owned())
            .collect();
        assert_eq!(order, expected, "{id}");
        ran += 1;
    }
    ran_all("queue_order", ran, section.len());
}

#[test]
fn formulation_026_fr_002_every_vector_section_is_exercised() {
    let file = support::formulation();
    assert_eq!(file["schema"], "brainbuddy-formulation-vectors/v1");
    let sections: BTreeSet<&str> = object(file, "vector file")
        .iter()
        .filter(|(_, value)| value.is_array())
        .map(|(key, _)| key.as_str())
        .collect();
    assert_eq!(
        sections,
        BTreeSet::from([
            "classification",
            "normalisation",
            "queue_order",
            "transitions"
        ])
    );
    let mut ids = BTreeSet::new();
    for section in &sections {
        for vector in cases(file, section) {
            assert!(
                ids.insert(text(vector, "id")),
                "duplicate id {}",
                text(vector, "id")
            );
        }
    }
    assert!(
        ids.len() >= 100,
        "the vector file shrank to {} cases",
        ids.len()
    );
}

// ------------------------------------------------------------ the instant type

#[test]
fn formulation_026_fr_016_instants_normalize_to_utc_like_from_isoformat() {
    let utc = at("2026-09-24T09:14:00Z");
    assert_eq!(at("2026-09-24T11:14:00+02:00"), utc);
    assert_eq!(at("2026-09-24T04:44:00-04:30"), utc);
    assert_eq!(at("2026-09-24t09:14:00z"), utc);
    assert_eq!(utc.to_rfc3339(), "2026-09-24T09:14:00Z");
    // Past six fraction digits is truncated, not rounded.
    let fractional = at("2026-09-24T09:14:00.1234567Z");
    assert_eq!(fractional.to_rfc3339(), "2026-09-24T09:14:00.123456Z");
    assert_eq!(fractional.micros_since(utc), 123_456);
    assert_eq!(
        at("2026-09-24T09:14:00.5+01:00").to_rfc3339(),
        "2026-09-24T08:14:00.500000Z"
    );
    // Ordering is by instant, not by spelling.
    assert!(at("2026-09-24T11:14:00+03:00") < utc);
    assert!(at("1969-12-31T23:59:59.5Z") < at("1970-01-01T00:00:00Z"));
    assert_eq!(
        at("1969-12-31T23:59:59.5Z").to_rfc3339(),
        "1969-12-31T23:59:59.500000Z"
    );
    // Python's range, and its refusals.
    assert_eq!(at("0001-01-01T00:00:00Z"), UtcInstant::EARLIEST);
    assert_eq!(at("9999-12-31T23:59:59.999999Z"), UtcInstant::LATEST);
    for bad in [
        "2026-09-24T09:14:60Z",
        "0001-01-01T00:00:00+01:00",
        "9999-12-31T23:59:59-01:00",
        "2026-02-30T00:00:00Z",
        "2026-09-24T24:00:00Z",
        "2026-09-24T09:14:00",
        "2026-09-24 09:14:00Z",
        "2026-09-24T09:14:00.Z",
        "2026-09-24T09:14:00+24:00",
        "2026-09-24T09:14:00+0100",
        "２０２６-09-24T09:14:00Z",
        "",
    ] {
        assert!(UtcInstant::parse_rfc3339(bad).is_err(), "{bad:?} parsed");
    }
    // Arithmetic never leaves the range, so every value renders and parses.
    assert_eq!(UtcInstant::LATEST.plus_seconds(1), UtcInstant::LATEST);
    assert_eq!(UtcInstant::EARLIEST.plus_seconds(-1), UtcInstant::EARLIEST);
    assert_eq!(at(&UtcInstant::LATEST.to_rfc3339()), UtcInstant::LATEST);
}

// ------------------------------------------------------------ scalar semantics

#[test]
fn formulation_026_fr_002_the_stalled_count_survives_leaving_next() {
    let settings = settings_from(&json!({
        "threshold_days": 14, "time_zone": "Europe/Berlin",
        "owner_park_floor_at": null, "activated_at": "2026-09-01T08:00:00Z",
    }));
    let started = at("2026-09-01T09:00:00Z");
    let mut clock = formulation::create_in_next("Call Bob", "form_a", started);
    clock.consecutive_stalled_formulations = 2;
    // Left after its ask_at (14 days): the count goes up and is kept outside Next.
    let late = formulation::move_to(
        &clock,
        TaskState::Waiting,
        &settings,
        started.plus_seconds(15 * 86_400),
        None,
    )
    .expect("a move");
    assert_eq!(late.consecutive_stalled_formulations, 3);
    assert_eq!(late.formulation_started_at, None);
    // Moving through lists that have no clock leaves the scalar alone.
    let someday = formulation::move_to(
        &late,
        TaskState::Someday,
        &settings,
        started.plus_seconds(16 * 86_400),
        None,
    )
    .expect("a move");
    assert_eq!(someday.consecutive_stalled_formulations, 3);
    // A formulation closed before its ask resets it.
    let early = formulation::move_to(
        &clock,
        TaskState::Waiting,
        &settings,
        started.plus_seconds(86_400),
        None,
    )
    .expect("a move");
    assert_eq!(early.consecutive_stalled_formulations, 0);
}

#[test]
fn formulation_026_fr_016_bookkeeping_never_bumps_the_revision_and_edits_always_do() {
    let settings = settings_from(&json!({
        "threshold_days": 14, "time_zone": "UTC",
        "owner_park_floor_at": null, "activated_at": "2026-09-01T08:00:00Z",
    }));
    let now = at("2026-10-09T14:02:00Z");
    let mut clock = formulation::create_in_next("Call Bob", "form_a", at("2026-09-02T00:00:00Z"));
    clock.revision = 7;
    clock.due_date = CalendarDay::parse_iso("2026-10-20").ok();
    assert_eq!(formulation::raise_due_floor(&clock, now).revision, 7);
    assert_eq!(
        formulation::activate_clock(&clock, at("2026-09-05T00:00:00Z"), "form_b").revision,
        7
    );
    assert_eq!(formulation::repair_clock(&clock, now, "form_b").revision, 7);
    assert_eq!(formulation::edit_without_clock(&clock).revision, 8);
    assert_eq!(formulation::change_due_date(&clock, None, now).revision, 8);
    assert_eq!(
        formulation::change_title(&clock, "Call Bob.", &settings, now, "form_b").revision,
        8
    );
}

#[test]
fn formulation_026_fr_016_a_zone_is_an_exact_iana_name_and_an_unactivated_owner_has_no_clock() {
    let refused = OwnerClockSettings::new(14, "europe/berlin", None, None);
    assert_eq!(
        refused,
        Err(FormulationError::UnknownTimeZone(
            "europe/berlin".to_owned()
        ))
    );
    assert_eq!(
        OwnerClockSettings::new(10, "UTC", None, None),
        Err(FormulationError::InvalidThreshold(10))
    );
    let idle = OwnerClockSettings::new(14, "UTC", None, None).expect("settings");
    let clock = formulation::create_in_next("Call Bob", "form_a", at("2026-09-02T00:00:00Z"));
    assert_eq!(formulation::derive_instants(&clock, &idle), None);
    assert_eq!(
        formulation::classify(&clock, &idle, at("2027-01-01T00:00:00Z")),
        FormulationClass::None
    );
    // A move into Next without an id is a caller bug, as the server's ValueError.
    let waiting = TaskClock {
        state: Some(TaskState::Waiting),
        ..clock
    };
    assert_eq!(
        formulation::move_to(
            &waiting,
            TaskState::Next,
            &idle,
            at("2026-09-03T00:00:00Z"),
            None
        ),
        Err(FormulationError::MissingInput("new_formulation_id"))
    );
}

#[test]
fn formulation_026_fr_002_a_desired_outcome_is_trimmed_like_python_strip() {
    let outcome = |raw: &str| DesiredOutcome::from_input(raw).expect("a valid outcome");
    assert_eq!(
        outcome("  Done by May \u{3000}").map(|value| value.as_str().to_owned()),
        Some("Done by May".to_owned())
    );
    // `str.strip()` also strips U+001C..U+001F; `str::trim` does not.
    assert_eq!(
        outcome("\u{1c}\u{1f} Done \u{1d}\u{1e}").map(|value| value.as_str().to_owned()),
        Some("Done".to_owned())
    );
    assert_eq!(outcome("\u{1c} \u{1f}"), None);
    // Only whitespace is stripped: a zero-width space stays, so it is not blank.
    assert!(outcome("\u{200b}").is_some());
    // The limit counts the trimmed scalars.
    let padded = format!("\u{1c}{}\u{1f}", "🙂".repeat(1_000));
    assert!(DesiredOutcome::from_input(&padded).is_ok());
    assert!(DesiredOutcome::from_input(&"🙂".repeat(1_001)).is_err());
}

// ------------------------------------------------------- stored-record bridge

const STORED_PARK_TASK: &str = "task_9f3c2a1b4d5e";

fn parked_candidate() -> Task {
    serde_json::from_value(json!({
        "id": STORED_PARK_TASK,
        "title": "Call Bob",
        "details": null,
        "state": "next",
        "project_id": null,
        "tag_ids": [],
        "due_date": null,
        "priority": "none",
        "waiting_for": null,
        "waiting_since": null,
        "order_key": "1",
        "source_capture_ids": [],
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
        "completed_at": null,
        "cancelled_at": null,
        "revision": "5",
        "consecutive_stalled_formulations": 1,
        "formulation": {
            "id": "form_123e4567-e89b-12d3-a456-426614174000",
            "started_at": "2026-09-24T09:14:00Z",
            "extended_at": null,
            "extension_reason": null,
            "park_floor_at": null,
        },
        "parked": null,
    }))
    .expect("a stored task")
}

#[test]
fn formulation_026_fr_016_auto_park_and_its_reversal_round_trip_through_a_stored_task() {
    let settings = settings_from(&json!({
        "threshold_days": 14, "time_zone": "Europe/Berlin",
        "owner_park_floor_at": null, "activated_at": "2026-09-01T08:00:00Z",
    }));
    let mut task = parked_candidate();
    let before = TaskClock::from_task(&task).expect("readable");
    // park_due_at = started + 14 days + 7 days = 2026-10-15T09:14:00Z
    let now = at("2026-10-15T09:14:00Z");
    let parked = formulation::auto_park(&before, &settings, now).expect("park due");
    assert_eq!(parked.state, Some(TaskState::Someday));
    assert_eq!(parked.revision, 6);
    assert_eq!(parked.consecutive_stalled_formulations, 2);

    parked.write_clock_fields(&mut task).expect("writes");
    task.state = TaskState::Someday;
    assert!(task.formulation.is_none());
    assert_eq!(task.consecutive_stalled_formulations, 2);
    // The public projection drops the snapshot; the stored one keeps it.
    let public = task.public();
    assert!(
        public
            .parked
            .as_ref()
            .is_some_and(|park| park.private.is_none())
    );
    assert_eq!(
        formulation::reverse_park(&TaskClock::from_task(&public).expect("readable")),
        Err(FormulationError::ParkSnapshotUnavailable)
    );

    let reversed = formulation::reverse_park(&TaskClock::from_task(&task).expect("readable"))
        .expect("reverses");
    assert_eq!(
        reversed.formulation_started_at,
        before.formulation_started_at
    );
    assert_eq!(reversed.formulation_id, before.formulation_id);
    assert_eq!(reversed.consecutive_stalled_formulations, 1);
    assert_eq!(reversed.parked, None);
    // The reversal is bookkeeping: the revision is the parked task's, not bumped.
    assert_eq!(reversed.revision, 5);
    assert_eq!(
        formulation::reverse_park(&TaskClock::from_task(&parked_candidate()).expect("readable")),
        Err(FormulationError::NotParked)
    );
}

#[test]
fn formulation_026_fr_016_view_instants_are_null_outside_next_and_before_activation() {
    let activated = settings_from(&json!({
        "threshold_days": 14, "time_zone": "UTC",
        "owner_park_floor_at": null, "activated_at": "2026-09-01T08:00:00Z",
    }));
    let idle = settings_from(&json!({
        "threshold_days": 14, "time_zone": "UTC",
        "owner_park_floor_at": null, "activated_at": null,
    }));
    let mut task = parked_candidate();

    let mut view = TaskView::new(&task, Vec::new(), Vec::new());
    formulation::fill_advisory_instants(&mut view, &task, &idle).expect("fills");
    let unset = view.formulation.clone().expect("a view");
    assert!(unset.ask_at.is_none() && unset.ageing_at.is_none());
    assert!(unset.park_due_at.is_none() && unset.paused_until.is_none());

    formulation::fill_advisory_instants(&mut view, &task, &activated).expect("fills");
    let filled = view.formulation.expect("a view");
    assert_eq!(
        filled.ageing_at.as_ref().map(|value| value.as_str()),
        Some("2026-10-01T09:14:00Z")
    );
    assert_eq!(
        filled.ask_at.as_ref().map(|value| value.as_str()),
        Some("2026-10-08T09:14:00Z")
    );
    assert_eq!(
        filled.park_due_at.as_ref().map(|value| value.as_str()),
        Some("2026-10-15T09:14:00Z")
    );
    assert!(filled.paused_until.is_none());
    assert_eq!(filled.consecutive_stalled, 1);

    task.state = TaskState::Someday;
    assert_eq!(formulation::advisory_instants(&task, &activated), Ok(None));
}

#[test]
fn formulation_026_fr_017_the_decision_queue_reads_stored_tasks() {
    let settings = settings_from(&json!({
        "threshold_days": 14, "time_zone": "UTC",
        "owner_park_floor_at": null, "activated_at": "2026-09-01T08:00:00Z",
    }));
    let task = parked_candidate();
    let now = at("2026-10-09T00:00:00Z");
    assert_eq!(
        formulation::decision_queue_of_tasks([&task], &settings, now),
        Ok(vec![STORED_PARK_TASK.to_owned()])
    );
    assert_eq!(
        formulation::decision_queue_of_tasks([&task], &settings, at("2026-09-25T00:00:00Z")),
        Ok(Vec::new())
    );
}
