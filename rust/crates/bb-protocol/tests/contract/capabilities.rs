//! Registration and capabilities (026-FR-011, 026-FR-012).

use crate::common::{assert_keys_match_schema, with_common};
use bb_protocol::capabilities::{Capabilities, DeviceRegistration, DeviceRegistrationRequest};
use bb_protocol::decode;
use bb_protocol::wire::Marker;
use serde_json::json;

#[test]
fn capabilities_026_fr_011_registration_round_trips_and_stays_active() {
    let request = json!({"scope_id": "scope-example", "device_id": "device-example",
        "device_epoch": "epoch-example", "protocol_version": 1});
    assert_keys_match_schema("DeviceRegistrationRequest", &request);
    assert!(decode::<DeviceRegistrationRequest>(&request.to_string()).is_ok());
    let mut v2 = request.clone();
    v2["protocol_version"] = json!(2);
    assert!(decode::<DeviceRegistrationRequest>(&v2.to_string()).is_err());
    let mut extra = request.clone();
    extra["owner"] = json!("someone-else");
    assert!(decode::<DeviceRegistrationRequest>(&extra.to_string()).is_err());

    let registration = with_common(json!({"device_id": "device-example",
        "device_epoch": "epoch-example", "epoch_status": "active"}));
    assert_keys_match_schema("DeviceRegistration", &registration);
    let decoded: DeviceRegistration = decode(&registration.to_string()).unwrap();
    assert_eq!(serde_json::to_value(&decoded).unwrap(), registration);
    let mut closed = registration.clone();
    closed["epoch_status"] = json!("closed");
    assert!(decode::<DeviceRegistration>(&closed.to_string()).is_err());
}

#[test]
fn capabilities_026_fr_012_response_lists_versions_and_tolerates_newer_commands() {
    let capabilities = with_common(json!({
        "protocol_versions": [1],
        "command_versions": [
            {"type": "task.update", "supported_versions": [1, 2], "retire_at_by_version": {"1": "2027-04-01T00:00:00Z"}},
            {"type": "task.archive_all", "supported_versions": [1], "retire_at_by_version": {}}
        ],
        "rule_version": "rules-7", "projection_schema_version": 2, "storage_epoch": "epoch-1",
        "feed_generation": "feed-1", "scope_enabled": true,
        "limits": {"command_bytes": 4_194_304}, "recovery": {"snapshots": true}
    }));
    assert_keys_match_schema("Capabilities", &capabilities);
    let decoded: Capabilities = decode(&capabilities.to_string()).unwrap();
    assert_eq!(decoded.projection_schema_version, Marker::Number(2));
    assert_eq!(decoded.command_versions[1].command_type, "task.archive_all");
    assert_eq!(serde_json::to_value(&decoded).unwrap(), capabilities);

    let mut incomplete = capabilities.clone();
    incomplete.as_object_mut().unwrap().remove("recovery");
    assert!(decode::<Capabilities>(&incomplete.to_string()).is_err());
}
