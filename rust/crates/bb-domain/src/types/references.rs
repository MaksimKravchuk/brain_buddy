//! Cross-command references (command-catalog.md "Smart Add bindings",
//! sync-v1.md §3): an immutable envelope may name a project or tag that an
//! earlier Smart Add command created or resolved by `{after_command, alias_id,
//! entity_type}` instead of a guessed server ID, and an `after_command`
//! precondition names the exact `{command_id, entity_type, entity_id}` whose
//! receipt version it substitutes.
//!
//! The stored envelope is never rewritten. Typing an envelope reads the
//! retained receipts through [`Dependencies`] and produces a resolved
//! in-memory [`DomainCommand`](super::DomainCommand) with direct IDs.

use super::errors::{DomainError, Reason};
use super::primitives::{Patch, ProjectId, TagId};
use super::tasks::{TagChanges, TaskCreate, TaskUpdate};
use bb_protocol::catalog::EntityType;
use bb_protocol::command::CommandRef;
use bb_protocol::receipt::{Outcome, Receipt, Version};
use bb_protocol::wire::{CommandId, Counter, Id};
use serde::de::{self, IntoDeserializer, MapAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize};
use std::fmt;
use std::marker::PhantomData;

// ------------------------------------------------------------------- the reference

/// An identifier type an [`EntityRef`] can stand for.
pub trait RefTarget: Sized {
    /// The entity an alias for this ID must be typed as.
    const ENTITY_TYPE: EntityType;

    /// Reads the ID a retained binding resolved to.
    fn from_resolved(id: &Id) -> Result<Self, DomainError>;
}

impl RefTarget for ProjectId {
    const ENTITY_TYPE: EntityType = EntityType::Project;

    fn from_resolved(id: &Id) -> Result<Self, DomainError> {
        Self::parse(id.as_str())
    }
}

impl RefTarget for TagId {
    const ENTITY_TYPE: EntityType = EntityType::Tag;

    fn from_resolved(id: &Id) -> Result<Self, DomainError> {
        Self::parse(id.as_str())
    }
}

/// The immutable reference an unresolved Smart Add resolution is written as:
/// the creating command, the proposed (alias) ID and the entity type. No other
/// key is accepted.
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AliasRef {
    pub after_command: CommandId,
    pub alias_id: Id,
    pub entity_type: EntityType,
}

/// A payload ID that is either a direct ID or an [`AliasRef`] awaiting the
/// retained receipt binding. A bare string is direct; an object is an alias.
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize)]
#[serde(untagged)]
pub enum EntityRef<I> {
    Direct(I),
    Alias(AliasRef),
}

/// A project reference as it appears on the wire.
pub type ProjectRef = EntityRef<ProjectId>;
/// A tag reference as it appears on the wire.
pub type TagRef = EntityRef<TagId>;

impl<I> EntityRef<I> {
    pub fn direct(id: I) -> Self {
        Self::Direct(id)
    }
}

impl<I: RefTarget> EntityRef<I> {
    /// The direct ID, or the one the retained receipt bound to the alias.
    /// [`Reason::DependencyPending`] while that receipt is unknown.
    pub fn resolve(self, dependencies: &(impl Dependencies + ?Sized)) -> Result<I, DomainError> {
        match self {
            Self::Direct(id) => Ok(id),
            Self::Alias(alias) => I::from_resolved(&dependencies.binding(&alias)?),
        }
    }
}

struct RefVisitor<I>(PhantomData<I>);

impl<'de, I: Deserialize<'de> + RefTarget> Visitor<'de> for RefVisitor<I> {
    type Value = EntityRef<I>;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("an id, or {after_command, alias_id, entity_type}")
    }

    fn visit_str<E: de::Error>(self, value: &str) -> Result<Self::Value, E> {
        I::deserialize(value.into_deserializer()).map(EntityRef::Direct)
    }

    fn visit_map<A: MapAccess<'de>>(self, map: A) -> Result<Self::Value, A::Error> {
        let alias = AliasRef::deserialize(de::value::MapAccessDeserializer::new(map))?;
        if alias.entity_type == I::ENTITY_TYPE {
            Ok(EntityRef::Alias(alias))
        } else {
            Err(de::Error::custom("invalid EntityRef"))
        }
    }
}

impl<'de, I: Deserialize<'de> + RefTarget> Deserialize<'de> for EntityRef<I> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_any(RefVisitor(PhantomData))
    }
}

impl<I> Patch<EntityRef<I>> {
    /// Resolves a set value; `Unchanged` and `Clear` pass through.
    pub fn resolve(
        self,
        dependencies: &(impl Dependencies + ?Sized),
    ) -> Result<Patch<I>, DomainError>
    where
        I: RefTarget,
    {
        Ok(match self {
            Patch::Unchanged => Patch::Unchanged,
            Patch::Clear => Patch::Clear,
            Patch::Set(reference) => Patch::Set(reference.resolve(dependencies)?),
        })
    }
}

// ---------------------------------------------------------------------- resolution

/// What typing an envelope needs from the retained terminal receipts.
///
/// Both lookups answer [`Reason::DependencyPending`] while the predecessor has
/// no terminal receipt (retryable), and [`Reason::DependencyRejected`] when it
/// ended without producing what the reference names (terminal).
pub trait Dependencies {
    /// The edit revision the predecessor's receipt recorded for exactly the
    /// entity `reference` names.
    fn edit_revision(&self, reference: &CommandRef) -> Result<Counter, DomainError>;

    /// The entity ID the predecessor's receipt bound to `alias`.
    fn binding(&self, alias: &AliasRef) -> Result<Id, DomainError>;
}

/// No terminal receipt is known: every reference waits.
#[derive(Clone, Copy, Debug, Default)]
pub struct NoReceipts;

impl Dependencies for NoReceipts {
    fn edit_revision(&self, _: &CommandRef) -> Result<Counter, DomainError> {
        Err(DomainError::new(Reason::DependencyPending))
    }

    fn binding(&self, _: &AliasRef) -> Result<Id, DomainError> {
        Err(DomainError::new(Reason::DependencyPending))
    }
}

/// Whether a receipt version is the record `entity_id` of `entity_type`.
/// Single-ID entities key on `[id]`; the settings singleton on `[]`.
fn is_version_of(version: &Version, entity_type: EntityType, entity_id: &Id) -> bool {
    version.entity_type == entity_type
        && (version.record_key.as_slice() == [entity_id.as_str()]
            || (entity_type == EntityType::ReviewSettings && version.record_key.is_empty()))
}

fn accepted<'a>(
    receipts: &'a [Receipt],
    command_id: &CommandId,
) -> Result<&'a Receipt, DomainError> {
    let receipt = receipts
        .iter()
        .find(|receipt| &receipt.command_id == command_id)
        .ok_or_else(|| DomainError::new(Reason::DependencyPending))?;
    match receipt.outcome {
        Outcome::Accepted => Ok(receipt),
        Outcome::Rejected => Err(DomainError::new(Reason::DependencyRejected)),
    }
}

/// Terminal receipts of earlier commands, as retained (content-free). A
/// receipt with several result versions yields the one for the exact entity.
impl Dependencies for [Receipt] {
    fn edit_revision(&self, reference: &CommandRef) -> Result<Counter, DomainError> {
        accepted(self, &reference.command_id)?
            .result_versions
            .iter()
            .find(|version| is_version_of(version, reference.entity_type, &reference.entity_id))
            .and_then(|version| version.edit_revision.clone())
            .ok_or_else(|| {
                DomainError::about(
                    Reason::DependencyRejected,
                    reference.entity_type,
                    vec![reference.entity_id.as_str().to_owned()],
                )
            })
    }

    fn binding(&self, alias: &AliasRef) -> Result<Id, DomainError> {
        accepted(self, &alias.after_command)?
            .id_bindings
            .iter()
            .find(|binding| {
                binding.entity_type == alias.entity_type && binding.alias_id == alias.alias_id
            })
            .map(|binding| binding.entity_id.clone())
            .ok_or_else(|| {
                DomainError::about(
                    Reason::DependencyRejected,
                    alias.entity_type,
                    vec![alias.alias_id.as_str().to_owned()],
                )
            })
    }
}

// ----------------------------------------------------------------- payload resolution

impl TagChanges<TagRef> {
    pub fn resolve(
        self,
        dependencies: &(impl Dependencies + ?Sized),
    ) -> Result<TagChanges, DomainError> {
        let resolve_all = |refs: Vec<TagRef>| {
            refs.into_iter()
                .map(|reference| reference.resolve(dependencies))
                .collect::<Result<Vec<_>, _>>()
        };
        Ok(TagChanges {
            add_tag_ids: resolve_all(self.add_tag_ids)?,
            remove_tag_ids: resolve_all(self.remove_tag_ids)?,
        })
    }
}

impl TaskCreate<ProjectRef, TagRef> {
    pub fn resolve(
        self,
        dependencies: &(impl Dependencies + ?Sized),
    ) -> Result<TaskCreate, DomainError> {
        Ok(TaskCreate {
            title: self.title,
            details: self.details,
            state: self.state,
            project_id: self
                .project_id
                .map(|reference| reference.resolve(dependencies))
                .transpose()?,
            tag_ids: self
                .tag_ids
                .into_iter()
                .map(|reference| reference.resolve(dependencies))
                .collect::<Result<_, _>>()?,
            due_date: self.due_date,
            priority: self.priority,
            waiting_for: self.waiting_for,
            source_capture_ids: self.source_capture_ids,
            new_formulation_id: self.new_formulation_id,
        })
    }
}

impl TaskUpdate<ProjectRef, TagRef> {
    pub fn resolve(
        self,
        dependencies: &(impl Dependencies + ?Sized),
    ) -> Result<TaskUpdate, DomainError> {
        Ok(TaskUpdate {
            title: self.title,
            details: self.details,
            project_id: self.project_id.resolve(dependencies)?,
            due_date: self.due_date,
            priority: self.priority,
            waiting_for: self.waiting_for,
            tag_changes: self
                .tag_changes
                .map(|changes| changes.resolve(dependencies))
                .transpose()?,
            new_formulation_id: self.new_formulation_id,
        })
    }
}
