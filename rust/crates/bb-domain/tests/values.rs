//! Checked scalars, PATCH semantics, records, change sets, read sets, queries
//! and refusals of the frozen domain types.

use bb_domain::types::*;
use bb_protocol::feed::Change;
use bb_protocol::wire::decode;
use serde::Serialize;
use serde::de::DeserializeOwned;
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::fmt::Debug;

const UUID: &str = "6b1e8a52-3f0c-4e7a-9d21-5c8b0f4a7e19";
const T0: &str = "2026-10-09T14:00:00Z";

fn object(value: Value) -> bb_protocol::wire::OpenObject {
    value.as_object().cloned().expect("object")
}

fn from<T: DeserializeOwned>(value: Value) -> T {
    serde_json::from_value(value).expect("decodes")
}

fn refused<T: DeserializeOwned + Debug>(value: Value) {
    assert!(
        serde_json::from_value::<T>(value.clone()).is_err(),
        "{value} should be refused"
    );
}

// ---------------------------------------------------------------------- PATCH

#[test]
fn values_026_fr_002_patch_distinguishes_omitted_null_and_value() {
    let update: TaskUpdate =
        from(json!({"details": null, "due_date": "2026-10-20", "title": "New"}));
    assert_eq!(update.details, Patch::Clear);
    assert!(matches!(update.due_date, Patch::Set(_)));
    assert_eq!(update.waiting_for, Patch::Unchanged);
    assert_eq!(update.project_id, Patch::Unchanged);
    assert_eq!(
        serde_json::to_value(&update).unwrap(),
        json!({"title": "New", "details": null, "due_date": "2026-10-20"})
    );
    // Nothing changed serializes to nothing: Unchanged is never written as a clear.
    assert_eq!(
        serde_json::to_value(TaskUpdate::<ProjectId, TagId>::default()).unwrap(),
        json!({})
    );
    assert_eq!(
        serde_json::to_value(ProjectUpdate::default()).unwrap(),
        json!({})
    );
}

#[test]
fn values_026_fr_002_fields_that_cannot_be_cleared_refuse_null() {
    refused::<TaskUpdate>(json!({"title": null}));
    refused::<TaskUpdate>(json!({"priority": null}));
    refused::<TaskUpdate>(json!({"tag_changes": null}));
    refused::<ProjectUpdate>(json!({"name": null}));
    refused::<TagUpdate>(json!({"name": null}));
    // Whole-collection tag replacement is not a sync field.
    refused::<TaskUpdate>(json!({"tag_ids": []}));
}

#[test]
fn values_026_fr_002_project_outcome_is_trimmed_and_blank_means_none() {
    let create: ProjectCreate = from(json!({"name": "Flat", "desired_outcome": "  Done by May  "}));
    assert_eq!(create.desired_outcome.unwrap().as_str(), "Done by May");
    let blank: ProjectCreate = from(json!({"name": "Flat", "desired_outcome": "   "}));
    assert!(blank.desired_outcome.is_none());
    let update: ProjectUpdate = from(json!({"desired_outcome": "   "}));
    assert_eq!(update.desired_outcome, Patch::Clear);
    let kept: ProjectUpdate = from(json!({"color": null}));
    assert_eq!(
        (kept.desired_outcome, kept.color),
        (Patch::Unchanged, Patch::Clear)
    );
    // The limit applies to the trimmed text.
    let padded = format!("  {}  ", "o".repeat(1_000));
    assert!(
        serde_json::from_value::<ProjectCreate>(json!({"name": "F", "desired_outcome": padded}))
            .is_ok()
    );
    refused::<ProjectCreate>(json!({"name": "F", "desired_outcome": "o".repeat(1_001)}));
}

// ------------------------------------------------------------- scalar limits

#[test]
fn values_026_fr_002_text_limits_count_unicode_scalars_not_bytes() {
    let title = "é".repeat(500); // 1,000 UTF-8 bytes, 500 scalars
    assert!(Title::new(title.clone()).is_ok());
    assert!(Title::new(format!("{title}x")).is_err());
    assert!(Title::new("").is_err());
    assert!(DesiredOutcome::new("🙂".repeat(1_000)).is_ok());
    assert!(DesiredOutcome::new("🙂".repeat(1_001)).is_err());
    assert!(Details::new("x".repeat(20_000)).is_ok());
    assert!(Details::new("").is_ok());
    assert!(CommentBody::new("x".repeat(20_001)).is_err());
    assert!(CommentBody::new("").is_err());
    assert!(Name::new("n".repeat(500)).is_ok());
    assert!(Name::new("n".repeat(501)).is_err());
    assert!(WaitingFor::new("w".repeat(501)).is_err());
    assert!(Color::new("c".repeat(65)).is_err());
    assert!(ZoneName::new("z".repeat(65)).is_err());
    // A combining sequence is several scalars: the limit is on scalars, not graphemes.
    assert!(Title::new("e\u{301}".repeat(250)).is_ok());
    assert!(Title::new("e\u{301}".repeat(251)).is_err());
    let err = Title::new("t".repeat(501)).unwrap_err();
    assert_eq!(
        (err.reason, err.field.as_deref()),
        (Reason::TextLength, Some("Title"))
    );
}

#[test]
fn values_026_fr_002_reason_text_is_trimmed_before_it_is_measured() {
    assert_eq!(
        ReasonText::new("  waiting for the quote ")
            .unwrap()
            .as_str(),
        "waiting for the quote"
    );
    assert!(ReasonText::new("   \n\t ").is_err());
    assert!(ReasonText::new(&format!(" {} ", "r".repeat(500))).is_ok());
    assert!(ReasonText::new(&"r".repeat(501)).is_err());
}

#[test]
fn values_026_fr_017_due_day_is_a_real_calendar_day_and_wall_time_is_a_clock_time() {
    for good in ["2026-10-09", "2028-02-29", "0001-01-01", "9999-12-31"] {
        assert!(DueDay::parse(good).is_ok(), "{good}");
    }
    for bad in [
        "2026-02-29",
        "2026-13-01",
        "2026-00-10",
        "2026-04-31",
        "2026-10-9",
        "26-10-09",
        "2026/10/09",
        "0000-01-01",
        "2026-10-09T00:00:00Z",
        " 2026-10-09",
    ] {
        assert!(DueDay::parse(bad).is_err(), "{bad}");
    }
    assert_eq!(DueDay::parse("2028-02-29").unwrap().parts(), (2028, 2, 29));
    for good in ["00:00", "09:30", "16:00", "19:59", "23:59"] {
        assert!(WallTime::parse(good).is_ok(), "{good}");
    }
    for bad in [
        "24:00", "9:30", "09:60", "09:6", "0930", "09:30:00", "ab:cd", "２3:00",
    ] {
        assert!(WallTime::parse(bad).is_err(), "{bad}");
    }
    assert_eq!(WallTime::parse("16:05").unwrap().hour_minute(), (16, 5));
}

#[test]
fn values_026_fr_002_review_numbers_are_bounded_to_their_vocabulary() {
    for days in [7, 14, 21, 28] {
        assert!(ThresholdDays::new(days).is_ok());
    }
    for days in [0, 1, 10, 29] {
        assert!(ThresholdDays::new(days).is_err());
    }
    assert!((1..=7).all(|d| Weekday::new(d).is_ok()));
    assert!(Weekday::new(0).is_err() && Weekday::new(8).is_err());
    assert!(TextVersion::new(0).is_err() && TextVersion::new(1).is_ok());
    // `onboarded` and the queue snapshot can only be switched on.
    refused::<SettingsUpdate>(json!({"onboarded": false}));
    refused::<SessionProgress>(json!({
        "progress_id": format!("progress_{UUID}"), "snapshot_decision_queue": false}));
    refused::<SettingsUpdate>(json!({"review_weekday": 8}));
    refused::<ConsentGrantRequest>(json!({"provider": "openai", "consent_text_version": 0}));
}

#[test]
fn values_026_fr_009_counters_stay_decimal_and_lossless() {
    let big = (1u64 << 53) + 1;
    let item: BulkItem = from(json!({"task_id": "task_1", "expected_revision": big.to_string()}));
    assert_eq!(item.expected_revision.to_u64(), Some(big));
    // Wider than u64 is still a valid counter; it just has no u64 value.
    let huge: BulkItem =
        from(json!({"task_id": "task_1", "expected_revision": "18446744073709551616"}));
    assert_eq!(huge.expected_revision.to_u64(), None);
    for bad in [
        json!(17),
        json!("017"),
        json!("-1"),
        json!("1.0"),
        json!(""),
    ] {
        refused::<BulkItem>(json!({"task_id": "task_1", "expected_revision": bad}));
    }
    let task = serde_json::to_value(sample_task()).unwrap();
    assert_eq!(task["order_key"], "7");
    assert_eq!(task["revision"], "8");
}

// --------------------------------------------------------------- identifiers

#[test]
fn values_026_fr_016_review_id_prefixes_and_shapes_are_checked() {
    let uuid = format!("form_{UUID}");
    assert!(FormulationId::parse(&uuid).is_ok());
    assert!(FormulationId::parse("form_0a1b2c3d4e5f").is_ok());
    assert!(NewFormulationId::parse(&uuid).is_ok());
    assert!(NewFormulationId::parse("form_0a1b2c3d4e5f").is_err());
    for bad in [
        "decision_0a1b2c3d4e5f",
        "form_0A1B2C3D4E5F",
        "form_0a1b2c3d4e5",
        "form_0a1b2c3d4e5f0",
        "form-0a1b2c3d4e5f",
        "form_9D2A6C1E-4B7F-4E83-A0D5-7F1B3C8E2A64",
        "form_SENTINEL-title text from a note",
        "",
    ] {
        assert!(FormulationId::parse(bad).is_err(), "{bad}");
    }
    assert!(SessionId::parse(format!("review_{UUID}")).is_ok());
    assert!(SessionId::parse("review_4d5e6f7a8b9c").is_ok());
    assert!(SessionId::parse("sess_42").is_err());
    assert!(BulkId::parse(format!("bulk_{UUID}")).is_ok());
    assert!(DecisionId::parse("decision_8c4e1a7d2b9f").is_ok());
    assert!(NewDecisionId::parse("decision_8c4e1a7d2b9f").is_err());
    assert!(ProgressId::parse(format!("progress_{UUID}")).is_ok());
    assert!(ProgressId::parse(format!("review_{UUID}")).is_err());
    assert!(ProgressId::parse("progress_0a1b2c3d4e5f").is_err());
    assert!(FollowUpTaskId::parse(format!("task_{UUID}")).is_ok());
    assert!(FollowUpTaskId::parse("task_0a1b2c3d4e5f").is_err());
    let widened: TaskId = FollowUpTaskId::parse(format!("task_{UUID}"))
        .unwrap()
        .into();
    assert!(widened.has_native_shape());
}

#[test]
fn values_026_fr_013_task_and_organization_ids_keep_legacy_shapes_verbatim() {
    for legacy in [
        "task_9f3c2a1b4d5e",
        "task-existing-id",
        "7",
        "local alias 1",
    ] {
        let id = TaskId::parse(legacy).unwrap();
        assert_eq!(id.as_str(), legacy);
        assert_eq!(serde_json::to_value(&id).unwrap(), json!(legacy));
    }
    assert!(TaskId::parse("").is_err());
    assert!(
        !TaskId::parse("task-existing-id")
            .unwrap()
            .has_native_shape()
    );
    assert!(TaskId::parse_new("task-existing-id").is_err());
    assert!(ProjectId::parse_new(format!("project_{UUID}")).is_ok());
    assert!(ProjectId::parse_new(format!("tag_{UUID}")).is_err());
}

#[test]
fn values_026_fr_022_refusals_never_echo_the_input() {
    let secret = "SENTINEL-private note text";
    let ids = FormulationId::parse(format!("form_{secret}")).unwrap_err();
    let text = Title::new(secret.repeat(40)).unwrap_err();
    for err in [ids, text] {
        assert!(!format!("{err:?}{err}").contains("SENTINEL"));
        assert!(!serde_json::to_string(&err).unwrap().contains("SENTINEL"));
    }
    let payload = object(json!({"title": secret, "unexpected": secret}));
    let err = Command::from_payload(CommandType::TaskCreate, &payload).unwrap_err();
    assert!(!format!("{err:?}{err}").contains("SENTINEL"));
    let long = object(json!({"title": "t".repeat(501)}));
    let err = Command::from_payload(CommandType::TaskCreate, &long).unwrap_err();
    assert_eq!(
        (err.reason, err.field.as_deref()),
        (Reason::InvalidPayload, Some("Title"))
    );
}

// -------------------------------------------------------------- payload rules

#[test]
fn values_026_fr_002_task_create_defaults_match_the_canonical_request() {
    let create: TaskCreate = from(json!({"title": "Buy milk"}));
    assert_eq!(
        (create.state, create.priority),
        (OpenList::Inbox, Priority::None)
    );
    assert!(create.tag_ids.is_empty() && create.project_id.is_none());
    refused::<TaskCreate>(json!({"title": "x", "state": "completed"}));
    refused::<TaskCreate>(json!({"title": "x", "priority": "urgent"}));
    refused::<TaskCreate>(json!({"title": "x", "due_date": "2026-02-30"}));
    refused::<TaskCreate>(json!({"title": "x", "new_formulation_id": "form_0a1b2c3d4e5f"}));
}

#[test]
fn values_026_fr_002_smart_add_references_are_a_strict_either_or() {
    let by_id: SmartAdd = from(json!({"title": "x", "project": {"id": "project_1"}}));
    assert_eq!(
        by_id.project,
        Some(ClassificationRef::Existing {
            id: ProjectId::parse("project_1").unwrap()
        })
    );
    let by_name: SmartAdd = from(json!({"title": "x", "tags": [
        {"name": "@home", "proposed_id": format!("tag_{UUID}")}]}));
    assert!(matches!(by_name.tags[0], ClassificationRef::ByName { .. }));
    for bad in [
        json!({"id": "project_1", "name": "Flat", "proposed_id": "project_2"}),
        json!({"name": "Flat"}),
        json!({"id": "project_1", "proposed_id": "project_2"}),
        json!({}),
        json!({"id": "project_1", "extra": true}),
    ] {
        refused::<SmartAdd>(json!({"title": "x", "project": bad}));
    }
}

#[test]
fn values_026_fr_002_review_lists_are_capped_when_decoded() {
    let steps = vec!["wins"; 11];
    refused::<SessionStart>(json!({"mode": "full", "entry": "list", "origin": "web",
        "replace_open": false, "skip_steps": steps}));
    let ten = vec!["wins"; 10];
    let start: SessionStart = from(json!({"mode": "full", "entry": "list", "origin": "web",
        "replace_open": false, "skip_steps": ten}));
    assert_eq!(start.skip_steps.as_slice().len(), 10);
    assert_eq!(<Limited<ParkKey, 200>>::MAX_ITEMS, 200);
}

// -------------------------------------------------------------- vocabularies

fn closed<T>(all: &[T], as_str: fn(T) -> &'static str, from_wire: fn(&str) -> Option<T>)
where
    T: Copy + PartialEq + Debug + Serialize + DeserializeOwned,
{
    let mut seen = BTreeSet::new();
    for &variant in all {
        let wire = as_str(variant);
        assert!(seen.insert(wire), "duplicate wire spelling {wire}");
        assert_eq!(from_wire(wire), Some(variant));
        assert_eq!(serde_json::to_value(variant).unwrap(), json!(wire));
        assert_eq!(serde_json::from_value::<T>(json!(wire)).unwrap(), variant);
        assert!(serde_json::from_value::<T>(json!(wire.to_uppercase())).is_err());
    }
    assert_eq!(from_wire("unknown"), None);
}

#[test]
fn values_026_fr_016_vocabularies_are_closed_and_spelled_as_the_api_spells_them() {
    closed(TaskState::ALL, TaskState::as_str, TaskState::from_wire);
    closed(OpenList::ALL, OpenList::as_str, OpenList::from_wire);
    closed(Priority::ALL, Priority::as_str, Priority::from_wire);
    closed(
        DecisionType::ALL,
        DecisionType::as_str,
        DecisionType::from_wire,
    );
    closed(
        StallReason::ALL,
        StallReason::as_str,
        StallReason::from_wire,
    );
    closed(AiUse::ALL, AiUse::as_str, AiUse::from_wire);
    closed(
        CountBucket::ALL,
        CountBucket::as_str,
        CountBucket::from_wire,
    );
    closed(
        SessionStatus::ALL,
        SessionStatus::as_str,
        SessionStatus::from_wire,
    );
    closed(StepCode::ALL, StepCode::as_str, StepCode::from_wire);
    closed(
        ReviewEntry::ALL,
        ReviewEntry::as_str,
        ReviewEntry::from_wire,
    );
    closed(Reason::ALL, Reason::as_str, Reason::from_wire);
    assert_eq!(TaskState::ALL.len(), 6);
    assert_eq!(OpenList::ALL.len(), 4);
    assert_eq!(DecisionType::ALL.len(), 11);
    assert_eq!(StepCode::ALL.len(), 10);
    // The ten summary buckets are exactly the ten SessionCounts members.
    let counts = serde_json::to_value(SessionCounts::default()).unwrap();
    let keys: BTreeSet<_> = counts
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    let buckets: BTreeSet<_> = CountBucket::ALL.iter().map(|b| b.as_str()).collect();
    assert_eq!(keys, buckets);
    assert!(
        OpenList::ALL
            .iter()
            .all(|l| l.task_state().open_list() == Some(*l))
    );
    assert!(!TaskState::Completed.is_open() && !TaskState::Cancelled.is_open());
}

// ------------------------------------------------- state, records, change sets

fn sample_task() -> Task {
    from(json!({
        "id": "task_9f3c2a1b4d5e", "title": "Measure the wall", "details": null, "state": "next",
        "project_id": null, "tag_ids": [], "due_date": null, "priority": "none",
        "waiting_for": null, "waiting_since": null, "order_key": "7", "source_capture_ids": [],
        "created_at": T0, "updated_at": T0, "completed_at": null, "cancelled_at": null,
        "revision": "8", "consecutive_stalled_formulations": 1,
        "formulation": {"id": format!("form_{UUID}"), "started_at": T0, "extended_at": null,
            "extension_reason": null, "park_floor_at": null},
        "parked": null
    }))
}

fn private_park() -> Value {
    json!({"at": T0, "formulation_id": format!("form_{UUID}"), "private": {
        "from_revision": "8", "clock_before": {"formulation_id": format!("form_{UUID}"),
            "started_at": T0, "extended_at": null, "extension_reason": null,
            "park_floor_at": null, "stalled_before": 1}}})
}

/// One valid sample of every replicated entity type.
fn record_samples() -> Vec<(EntityType, Value)> {
    let task = serde_json::to_value(sample_task()).unwrap();
    let session = json!({"id": format!("review_{UUID}"), "mode": "quick", "entry": "list",
        "origin": "ios", "status": "open", "started_at": T0, "last_activity_at": T0,
        "ended_at": null, "current_step": "wins", "steps": {"wins": "pending"},
        "active_seconds_by_step": {"wins": 3}, "counts": serde_json::to_value(SessionCounts::default()).unwrap(),
        "set_aside_count": 0, "qualifying_activity": false, "clear_start": null, "revision": "1"});
    vec![
        (EntityType::Task, task),
        (
            EntityType::Project,
            json!({"id": "project_1", "name": "Flat", "color": null,
            "state": "active", "revision": "1", "desired_outcome": null, "archived_at": null,
            "archived_before_lossless": false}),
        ),
        (
            EntityType::Tag,
            json!({"id": "tag_1", "name": "@home", "state": "active", "revision": "1"}),
        ),
        (
            EntityType::Subtask,
            json!({"id": "subtask_1", "task_id": "task_1", "title": "x",
            "state": "open", "order_key": "1", "revision": "1"}),
        ),
        (
            EntityType::Comment,
            json!({"id": "comment_1", "task_id": "task_1", "body": "hi",
            "actor_id": "actor_1", "created_at": T0, "edited_at": null, "revision": "1"}),
        ),
        (
            EntityType::ReviewSettings,
            json!({"threshold_days": 14, "review_weekday": 5,
            "review_time": "16:00", "time_zone": "UTC", "onboarded_at": null, "activated_at": null,
            "owner_park_floor_at": null, "revision": "1"}),
        ),
        (EntityType::ReviewSession, session),
        (
            EntityType::ReviewDecisionQueue,
            json!({"session_id": format!("review_{UUID}"),
            "task_ids": null, "decided_task_ids": [], "set_aside_task_ids": []}),
        ),
        (
            EntityType::ReviewDecision,
            json!({"id": format!("decision_{UUID}"), "type": "complete",
            "task_id": "task_1", "session_id": null, "decided_at": T0, "substantive": null,
            "stall_reason": null, "ai_use": "none", "yielded_auto_park": false,
            "formulation_id": null, "task_revision_before": "4", "task_revision_after": "5",
            "created_task_id": null, "navigator_request_id": null, "review_counts_as": "done",
            "client_decided_at": null, "reason_text": null, "undo_available_until": null}),
        ),
        (
            EntityType::ReviewReceipt,
            json!({"task_id": "task_1", "kind": "someday",
            "hidden_until": T0, "task_revision": "4", "reviewed_at": T0, "source": "keep",
            "decision_id": null, "bulk_id": null}),
        ),
        (
            EntityType::ReviewParkAck,
            json!({"task_id": "task_1", "formulation_id": format!("form_{UUID}"),
            "parked_at": T0, "seen_at": null, "returned_at": null}),
        ),
        (
            EntityType::ReviewBulkRelease,
            json!({"id": format!("bulk_{UUID}"), "kind": "restart",
            "session_id": null, "created_at": T0, "undone_at": null,
            "released": [{"task_id": "task_1", "revision_after": "5"}],
            "skipped": [{"task_id": "task_2", "reason": "stale"}], "undo": null}),
        ),
        (
            EntityType::ReviewNavigatorConsent,
            json!({"provider": "openai", "consent":
            {"granted_at": T0, "revoked_at": null, "consent_text_version": 1}}),
        ),
    ]
}

fn record(entity: EntityType, value: Value) -> Record {
    from(json!({"entity_type": entity.as_str(), "value": value}))
}

#[test]
fn values_026_fr_013_every_entity_type_has_a_typed_record() {
    let samples = record_samples();
    let covered: BTreeSet<_> = samples.iter().map(|(t, _)| t.as_str()).collect();
    let catalog: BTreeSet<_> = EntityType::ALL.iter().map(|t| t.as_str()).collect();
    assert_eq!(covered, catalog);
    for (entity, value) in samples {
        let typed = record(entity, value.clone());
        assert_eq!(typed.entity_type(), entity);
        let wire = serde_json::to_value(&typed).unwrap();
        assert_eq!(wire["entity_type"], entity.as_str());
        assert_eq!(wire["value"], value, "{entity:?} round-trips");
        // A key per data-model.md, one component per key part.
        let key = typed.record_key();
        let expected = match entity {
            EntityType::ReviewSettings => 0,
            EntityType::ReviewReceipt | EntityType::ReviewParkAck => 2,
            _ => 1,
        };
        assert_eq!(key.len(), expected, "{entity:?}");
    }
}

#[test]
fn values_026_fr_013_records_reject_fields_the_data_model_does_not_define() {
    for (entity, mut value) in record_samples() {
        value["unexpected"] = json!(true);
        assert!(
            serde_json::from_value::<Record>(
                json!({"entity_type": entity.as_str(), "value": value})
            )
            .is_err(),
            "{entity:?}"
        );
    }
}

#[test]
fn values_026_fr_013_records_agree_with_the_feed_change_shape() {
    for (entity, value) in record_samples() {
        let typed = record(entity, value);
        let change = json!({
            "entity_type": entity.as_str(),
            "record_key": typed.record_key(),
            "record_version": "1",
            "operation": "upsert",
            "value": serde_json::to_value(&typed).unwrap()["value"],
        });
        let wire: Change = decode(&change.to_string()).expect("feed change decodes");
        assert_eq!(wire.entity_type, typed.entity_type());
        assert_eq!(wire.record_key, typed.record_key());
        assert_eq!(
            wire.value.map(Value::Object),
            Some(serde_json::to_value(&typed).unwrap()["value"].clone())
        );
    }
}

#[test]
fn values_026_fr_022_public_records_never_carry_private_state() {
    let mut task = serde_json::to_value(sample_task()).unwrap();
    task["state"] = json!("someday");
    task["formulation"] = Value::Null;
    task["parked"] = private_park();
    let authoritative = record(EntityType::Task, task);
    let public = authoritative.public();
    assert_ne!(public, authoritative);
    let wire = serde_json::to_string(&public).unwrap();
    assert!(!wire.contains("private") && !wire.contains("clock_before"));
    // Private members are optional on input and omitted on output when absent.
    assert!(
        !serde_json::to_string(&sample_task())
            .unwrap()
            .contains("private")
    );
    assert_eq!(public.public(), public);
    // Every record with a private member strips it.
    let mut session = record_samples().remove(6).1;
    session["private"] = json!({"applied_progress": {format!("progress_{UUID}"): "digest"},
        "finished_empty": ["inbox"]});
    let stripped = record(EntityType::ReviewSession, session).public();
    assert!(
        !serde_json::to_string(&stripped)
            .unwrap()
            .contains("applied_progress")
    );
}

#[test]
fn values_026_sc_001_change_sets_report_record_keys_per_data_model() {
    let samples = record_samples();
    let value_of = |t: EntityType| samples.iter().find(|(e, _)| *e == t).unwrap().1.clone();
    let set: ChangeSet = from(json!({
        "outcome": "applied",
        "changes": [
            {"operation": "upsert", "entity_type": "review_settings", "value": value_of(EntityType::ReviewSettings)},
            {"operation": "upsert", "entity_type": "review_receipt", "value": value_of(EntityType::ReviewReceipt)},
            {"operation": "tombstone", "entity_type": "tag", "record_key": ["tag_1"]}
        ],
        "result": {"released": [{"task_id": "task_1", "revision_after": "5"}],
            "bulk_undo": {"restored": ["task_1"], "skipped": [{"task_id": "task_2", "reason": "stale"}]},
            "id_bindings": [{"entity_type": "project", "alias_id": "project_alias", "entity_id": "project_1"}]},
        "effects": [{"kind": "auto_park_followup", "dedup_key": "auto-park:task_1:form_1:8", "run_at": null}]
    }));
    let keys = set.affected_keys();
    assert_eq!(
        keys,
        vec![
            (EntityType::ReviewSettings, vec![]),
            (
                EntityType::ReviewReceipt,
                vec!["task_1".to_owned(), "someday".to_owned()]
            ),
            (EntityType::Tag, vec!["tag_1".to_owned()]),
        ]
    );
    assert_eq!(set.outcome, ChangeOutcome::Applied);
    assert_eq!(set.result.id_bindings[0].alias_id.as_str(), "project_alias");
    let wire = serde_json::to_value(&set).unwrap();
    assert_eq!(serde_json::from_value::<ChangeSet>(wire).unwrap(), set);
    assert_eq!(ChangeSet::no_op().outcome, ChangeOutcome::NoOp);
    assert!(ChangeSet::no_op().affected_keys().is_empty());
}

#[test]
fn values_026_fr_002_read_sets_hold_only_what_was_loaded() {
    let empty: ReadSet = from(json!({}));
    assert_eq!(empty, ReadSet::default());
    assert!(empty.settings.is_none() && empty.tasks.is_empty());
    let task = sample_task();
    let read_set: ReadSet =
        from(json!({"tasks": {"task_9f3c2a1b4d5e": serde_json::to_value(&task).unwrap()}}));
    assert_eq!(
        read_set
            .tasks
            .get(&TaskId::parse("task_9f3c2a1b4d5e").unwrap()),
        Some(&task)
    );
    assert_eq!(
        serde_json::from_value::<ReadSet>(serde_json::to_value(&read_set).unwrap()).unwrap(),
        read_set
    );
    refused::<ReadSet>(json!({"tasks": {}, "sneaky": 1}));
    // A missing fact is reported with the record it concerns, never defaulted.
    let err = DomainError::missing(EntityType::Project, vec!["project_1".into()]);
    let wire = serde_json::to_value(&err).unwrap();
    assert_eq!(wire["reason"], "incomplete_read_set");
    assert_eq!(serde_json::from_value::<DomainError>(wire).unwrap(), err);
    let stale = DomainError::stale(
        EntityType::Task,
        vec!["task_1".into()],
        Counter::parse("9").unwrap(),
    );
    assert_eq!(
        stale.current_revision.as_ref().map(Counter::as_str),
        Some("9")
    );
}

// ------------------------------------------------------------ queries, inputs

#[test]
fn values_026_fr_002_queries_and_inputs_round_trip() {
    let queries = [
        json!({"kind": "task_list", "list": "next", "project_id": null, "tag_id": "tag_1",
            "sort": "due", "page": {"limit": 50, "after": null}}),
        json!({"kind": "task_detail", "task_id": "task_1"}),
        json!({"kind": "list_counts"}),
        json!({"kind": "projects", "filter": "archived"}),
        json!({"kind": "project_display", "project_id": "project_1"}),
        json!({"kind": "tags"}),
        json!({"kind": "review_state"}),
        json!({"kind": "review_queue", "step": "decisions", "session_id": format!("review_{UUID}")}),
    ];
    for wire in queries {
        let query: Query = from(wire.clone());
        assert_eq!(serde_json::to_value(&query).unwrap(), wire);
    }
    refused::<Query>(json!({"kind": "task_delete"}));
    refused::<Query>(json!({"kind": "tags", "limit": 5}));
    let inputs = json!({"rule_version": 1, "now": T0, "time_zone": "Europe/Berlin",
        "origin": "device", "actor_id": "actor_1", "authoritative": false,
        "allocated_ids": ["task_a"], "policy": {"weekly_review": true,
            "navigator_provider": null, "navigator_available": false, "consent_text_version": 1}});
    let parsed: ExecutionInputs = from(inputs.clone());
    assert_eq!(serde_json::to_value(&parsed).unwrap(), inputs);
    refused::<ExecutionInputs>(json!({"rule_version": 1}));
    // The writer origin is a fact the boundary supplies, closed over the four origins.
    let mut bad = inputs;
    bad["origin"] = json!("admin");
    refused::<ExecutionInputs>(bad);
}

#[test]
fn values_026_fr_002_query_results_round_trip_by_kind() {
    let task_view = |id: &str| {
        json!({"id": id, "title": "T", "details": null, "state": "next", "project_id": null,
            "tag_ids": [], "due_date": null, "priority": "none", "waiting_for": null,
            "waiting_since": null, "order_key": "1", "source_capture_ids": [],
            "created_at": T0, "updated_at": T0, "completed_at": null, "cancelled_at": null,
            "revision": "1", "subtasks": [], "comments": [], "formulation": null, "parked": null})
    };
    let project = record_samples().remove(1).1;
    let tag = record_samples().remove(2).1;
    let results = [
        json!({"kind": "task_list", "value": {"items": [task_view("task_1")], "next_cursor": "c2",
            "has_more": true, "counts_by_state": {"inbox": 1, "next": 2, "waiting": 0, "someday": 3}}}),
        json!({"kind": "task_detail", "value": task_view("task_2")}),
        json!({"kind": "list_counts", "value": {"inbox": 1, "next": 2, "waiting": 3, "someday": 4,
            "overdue": 1, "today": 2}}),
        json!({"kind": "projects", "value": [{"project": project, "open_task_count": 3, "next_action_count": 0}]}),
        json!({"kind": "project_display", "value": {"is_archived": true, "accepts_new_tasks": false,
            "shows_pre_lossless_line": false, "label": "Flat · archived"}}),
        json!({"kind": "tags", "value": [{"tag": tag, "open_task_count": 2}]}),
        json!({"kind": "review_queue", "value": {"items": [task_view("task_3")],
            "meta": {"decided_task_ids": ["task_3"], "set_aside_task_ids": []}}}),
    ];
    for wire in results {
        let result: QueryResult = from(wire.clone());
        assert_eq!(serde_json::to_value(&result).unwrap(), wire);
    }
    let QueryResult::Projects(projects) =
        from::<QueryResult>(json!({"kind": "projects", "value": [
        {"project": record_samples().remove(1).1, "open_task_count": 3, "next_action_count": 0}]}))
    else {
        panic!("projects")
    };
    assert!(projects[0].needs_next_action());
}
