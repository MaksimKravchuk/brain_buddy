//! Device registration and capabilities (sync-v1 §11).

use crate::receipt::EpochStatus;
use crate::wire::{
    CodecError, CommonResponse, Generation, Id, Marker, OpenObject, PROTOCOL_VERSION, Wire,
};
use serde::{Deserialize, Serialize};

/// `POST devices` body, with random client-allocated device and epoch IDs.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeviceRegistrationRequest {
    pub scope_id: Id,
    pub device_id: Id,
    pub device_epoch: Id,
    pub protocol_version: u32,
}

impl Wire for DeviceRegistrationRequest {
    fn validate(&self) -> Result<(), CodecError> {
        if self.protocol_version != PROTOCOL_VERSION {
            return Err(CodecError::Invalid("protocol_version"));
        }
        Ok(())
    }
}

/// `POST devices` success: the registered tuple, always `active`.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeviceRegistration {
    pub device_id: Id,
    pub device_epoch: Id,
    pub epoch_status: EpochStatus,
    #[serde(flatten)]
    pub common: CommonResponse,
}

impl Wire for DeviceRegistration {
    fn validate(&self) -> Result<(), CodecError> {
        if self.epoch_status != EpochStatus::Active {
            return Err(CodecError::Invalid("registration epoch_status"));
        }
        Ok(())
    }
}

/// Versions the server executes for one command type.
///
/// `type` is a plain string, not [`crate::catalog::CommandType`]: capabilities
/// is how a client learns what a newer server runs, so it must stay readable
/// when the server names a command this build does not know.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommandSupport {
    #[serde(rename = "type")]
    pub command_type: String,
    pub supported_versions: Vec<u32>,
    pub retire_at_by_version: OpenObject,
}

/// `GET capabilities` response. `limits` and `recovery` are open objects whose
/// members the contract lists but does not type.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Capabilities {
    pub protocol_versions: Vec<u32>,
    pub command_versions: Vec<CommandSupport>,
    pub rule_version: Marker,
    pub projection_schema_version: Marker,
    pub storage_epoch: Marker,
    pub feed_generation: Generation,
    pub scope_enabled: bool,
    pub limits: OpenObject,
    pub recovery: OpenObject,
    #[serde(flatten)]
    pub common: CommonResponse,
}

impl Wire for Capabilities {}
