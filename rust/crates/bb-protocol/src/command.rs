//! Command envelopes (sync-v1 §3, command-catalog.md).
//!
//! Decoding is two-phase. [`StableEnvelope`] is the replay/recovery form: it only
//! needs the stable outer shape, so a retained command stays readable after its
//! type or version is retired. [`CommandEnvelope`] is the execution form: it
//! accepts only catalog command types, supported versions and the catalog
//! constraints that `sync-v1.schema.json` encodes. Errors never echo payload text.

use crate::catalog::{CommandType, EntityType};
use crate::strict_json;
use crate::wire::{CodecError, CommandId, Counter, Id, Instant, OpenObject, PROTOCOL_VERSION};
use serde::{Deserialize, Serialize, Serializer};
use serde_json::Value;
use std::collections::HashSet;

/// Reference to an earlier command's effect on one entity.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommandRef {
    pub command_id: CommandId,
    pub entity_type: EntityType,
    pub entity_id: Id,
}

/// Expected edit revision of an entity the command checks.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RevisionPrecondition {
    pub entity_type: EntityType,
    pub entity_id: Id,
    pub edit_revision: Counter,
}

/// Substitute the referenced command's receipt edit revision (sync-v1 §3).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AfterCommandPrecondition {
    pub after_command: CommandRef,
}

/// A typed command-specific concurrency check.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Precondition {
    Revision(RevisionPrecondition),
    AfterCommand(AfterCommandPrecondition),
}

/// Stable outer envelope used for replay, fingerprinting and recovery.
///
/// It accepts command types and versions this build cannot execute, so a
/// retained or queued command is never lost or rewritten (026-FR-012).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StableEnvelope {
    pub protocol_version: u32,
    pub command_id: CommandId,
    pub scope_id: Id,
    pub device_id: Id,
    pub device_epoch: Id,
    pub local_sequence: Counter,
    #[serde(rename = "type")]
    pub command_type: String,
    pub command_version: u32,
    pub entity_id: Id,
    pub preconditions: Vec<Value>,
    pub depends_on: Vec<CommandId>,
    pub issued_at: Instant,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub supersedes_command_id: Option<CommandId>,
    pub payload: OpenObject,
}

/// An executable catalog command: the stable envelope plus its typed parts. It
/// serializes as the unchanged stable envelope.
#[derive(Clone, Debug, PartialEq)]
pub struct CommandEnvelope {
    pub envelope: StableEnvelope,
    pub command_type: CommandType,
    pub preconditions: Vec<Precondition>,
}

impl Serialize for CommandEnvelope {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        self.envelope.serialize(serializer)
    }
}

/// Why a well-formed envelope cannot execute here; maps to `UPGRADE_REQUIRED`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Unsupported {
    ProtocolVersion,
    CommandType,
    CommandVersion,
}

impl Unsupported {
    pub fn code(&self) -> &'static str {
        "UPGRADE_REQUIRED"
    }
}

/// Result of decoding a command envelope.
#[derive(Clone, Debug, PartialEq)]
pub enum Decoded {
    Executable(CommandEnvelope),
    Unsupported {
        reason: Unsupported,
        envelope: StableEnvelope,
    },
}

/// Decodes only the stable recovery form: no catalog or version checks.
pub fn decode_stable(json: &str) -> Result<StableEnvelope, CodecError> {
    strict_json::reject_duplicate_keys(json)?;
    Ok(serde_json::from_str(json)?)
}

/// Decodes a command: duplicate keys and malformed shapes are errors, an
/// unsupported but well-formed command is [`Decoded::Unsupported`].
pub fn decode_command(json: &str) -> Result<Decoded, CodecError> {
    let envelope = decode_stable(json)?;
    let command_type = CommandType::from_wire(&envelope.command_type);
    let reason = if envelope.protocol_version != PROTOCOL_VERSION {
        Some(Unsupported::ProtocolVersion)
    } else {
        match command_type {
            None => Some(Unsupported::CommandType),
            Some(t) if !t.supported_versions().contains(&envelope.command_version) => {
                Some(Unsupported::CommandVersion)
            }
            Some(_) => None,
        }
    };
    match (reason, command_type) {
        (None, Some(command_type)) => executable(envelope, command_type).map(Decoded::Executable),
        (reason, _) => Ok(Decoded::Unsupported {
            reason: reason.unwrap_or(Unsupported::CommandType),
            envelope,
        }),
    }
}

fn executable(
    stable: StableEnvelope,
    command_type: CommandType,
) -> Result<CommandEnvelope, CodecError> {
    let preconditions = stable
        .preconditions
        .iter()
        .cloned()
        .map(|value| serde_json::from_value(value).map_err(|_| CodecError::Invalid("precondition")))
        .collect::<Result<Vec<Precondition>, _>>()?;
    for precondition in &preconditions {
        if let Precondition::AfterCommand(after) = precondition
            && !stable.depends_on.contains(&after.after_command.command_id)
        {
            return Err(CodecError::Invalid("after_command missing from depends_on"));
        }
    }
    check_payload(command_type, &stable.payload)?;
    Ok(CommandEnvelope {
        envelope: stable,
        command_type,
        preconditions,
    })
}

/// Payload field strictness is bb-domain's; the schema leaves TagChanges open.
#[derive(Deserialize)]
struct TagChanges {
    #[serde(default)]
    add_tag_ids: Vec<Id>,
    #[serde(default)]
    remove_tag_ids: Vec<Id>,
}

/// Catalog-level payload constraints only; field schemas belong to the domain.
fn check_payload(command_type: CommandType, payload: &OpenObject) -> Result<(), CodecError> {
    if command_type.is_child()
        && !payload
            .get("task_id")
            .and_then(Value::as_str)
            .is_some_and(|s| !s.is_empty())
    {
        return Err(CodecError::Invalid("payload.task_id"));
    }
    let tag_changes = match command_type {
        CommandType::TaskTags => Some(Value::Object(payload.clone())),
        CommandType::TaskUpdate => payload.get("tag_changes").cloned(),
        _ => None,
    };
    if let Some(value) = tag_changes {
        let changes: TagChanges =
            serde_json::from_value(value).map_err(|_| CodecError::Invalid("tag changes"))?;
        let mut seen = HashSet::new();
        let unique_and_disjoint = changes
            .add_tag_ids
            .iter()
            .chain(&changes.remove_tag_ids)
            .all(|id| seen.insert(id));
        if !unique_and_disjoint {
            return Err(CodecError::Invalid(
                "tag changes must be unique and disjoint",
            ));
        }
    }
    if let Some(limit) = command_type.item_limit()
        && let Some(Value::Array(items)) = payload.get("items")
        && items.len() > limit
    {
        return Err(CodecError::Invalid("payload.items over limit"));
    }
    Ok(())
}
