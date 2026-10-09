//! Validated scalar types (026-FR-005, 026-FR-012).

use bb_protocol::wire::{CommandId, Counter, Id, Instant, Marker};
use serde_json::json;

#[test]
fn scalars_026_fr_005_counters_are_canonical_decimal_strings() {
    for ok in ["0", "7", "908", "18446744073709551616"] {
        assert!(Counter::parse(ok).is_ok(), "{ok}");
    }
    for bad in ["", "00", "042", "-1", "+1", "1.0", " 1", "1e3", "０"] {
        assert!(Counter::parse(bad).is_err(), "{bad:?}");
    }
    assert_eq!(Counter::from(908).as_str(), "908");
    assert_eq!(Counter::parse("908").unwrap().to_u64(), Some(908));
    assert_eq!(
        Counter::parse("18446744073709551616").unwrap().to_u64(),
        None
    );
    assert!(serde_json::from_value::<Counter>(json!(908)).is_err());
}

#[test]
fn scalars_026_fr_005_command_ids_are_uuids() {
    assert!(CommandId::parse("01900000-0000-4000-8000-000000000001").is_ok());
    for bad in [
        "",
        "opaque-support-reference",
        "01900000-0000-4000-8000-00000000000",
        "01900000_0000_4000_8000_000000000001",
        "0190000g-0000-4000-8000-000000000001",
    ] {
        assert!(CommandId::parse(bad).is_err(), "{bad:?}");
    }
    assert!(Id::parse("").is_err());
}

#[test]
fn scalars_026_fr_005_instants_are_rfc3339() {
    for ok in [
        "2026-10-08T10:00:00Z",
        "2026-10-08T10:00:00.123456+02:00",
        "2024-02-29T23:59:60-05:30",
    ] {
        assert!(Instant::parse(ok).is_ok(), "{ok}");
    }
    for bad in [
        "2026-10-08 10:00:00Z",
        "2026-10-08T10:00:00",
        "2026-10-08T10:00:00.Z",
        "2026-13-08T10:00:00Z",
        "2026-02-29T10:00:00Z",
        "2026-04-31T10:00:00Z",
        "2026-10-08T24:00:00Z",
        "2026-10-08T10:00:00+24:00",
        "2026-10-08T10:00:00+0200",
        "2026-10-08T10:00:00é",
        "",
    ] {
        assert!(Instant::parse(bad).is_err(), "{bad:?}");
    }
}

#[test]
fn scalars_026_fr_012_markers_accept_text_or_integer() {
    assert_eq!(
        serde_json::from_value::<Marker>(json!("v3")).unwrap(),
        Marker::Text("v3".into())
    );
    assert_eq!(
        serde_json::from_value::<Marker>(json!(3)).unwrap(),
        Marker::Number(3)
    );
    assert!(serde_json::from_value::<Marker>(json!(1.5)).is_err());
    assert!(serde_json::from_value::<Marker>(json!(null)).is_err());
}
