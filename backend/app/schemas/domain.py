"""Domain-level schemas matching on-disk documents."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from .common import (
    Position,
    StorageBaseModel,
    TimestampMetadata,
    ValidationState,
    VisualState,
)


class NodeDocument(StorageBaseModel):
    """Full representation of a node as stored on disk."""

    id: str = Field(description="Unique identifier for the node.")
    label: str = Field(description="Display label for the node.")
    position: Position = Field(description="Canvas position of the node.")
    metadata: TimestampMetadata = Field(
        description="Timestamps and authorship metadata."
    )
    visual: VisualState | None = Field(
        default=None, description="Visual hints for rendering."
    )
    validation: ValidationState | None = Field(
        default=None, description="Latest validation snapshot."
    )
    extra: dict[str, Any] | None = Field(
        default=None, description="Reserved for future structured metadata."
    )


class RelationMetadata(StorageBaseModel):
    """Metadata specific to relations."""

    created_at: datetime = Field(
        description="UTC timestamp when the relation was created."
    )
    updated_at: datetime = Field(
        description="UTC timestamp for the most recent relation update."
    )
    author: str | None = Field(default=None, description="Optional author identifier.")


class RelationDocument(StorageBaseModel):
    """Stored representation of a directed relation between nodes."""

    id: str = Field(description="Unique identifier for the relation.")
    source_id: str = Field(description="Identifier of the cause (source_node_id) node.")
    target_id: str = Field(
        description="Identifier of the effect (target_node_id) node."
    )
    question_label: str = Field(
        default="WHY?", description="Prompt associated with the relation."
    )
    notes: str | None = Field(default=None, description="Optional explanatory notes.")
    metadata: RelationMetadata = Field(
        description="Timestamps and authorship metadata."
    )


class ValidationEntry(StorageBaseModel):
    """Entry stored in validation history for a node."""

    confidence: int = Field(
        ge=0, le=100, description="Confidence score reported by provider."
    )
    summary: str = Field(description="Provider supplied summary guidance.")
    provider: str = Field(description="Provider identifier.")
    prompt_hash: str = Field(description="Stable hash of the prompt used.")
    checked_at: datetime = Field(description="Timestamp when validation occurred.")
    raw_response: dict[str, Any] | None = Field(
        default=None, description="Optional raw provider payload for audit."
    )


class IndexEntry(StorageBaseModel):
    """Entry stored in the global tree index."""

    id: str = Field(description="Tree identifier.")
    title: str = Field(description="Tree title.")
    description: str | None = Field(default=None, description="Tree description.")
    updated_at: datetime = Field(description="Timestamp of most recent modification.")
    owner_id: str | None = Field(default=None, description="Account that owns this tree.")


class ProviderConfig(StorageBaseModel):
    """Configuration for a single AI provider."""

    model_config = ConfigDict(extra="allow")

    api_key_ref: str | None = Field(
        default=None, description="Path or reference to API key."
    )
    model: str | None = Field(
        default=None, description="Model identifier to use for requests."
    )


class ProviderRegistryDocument(StorageBaseModel):
    """Top-level provider configuration stored on disk."""

    default_provider: str | None = Field(
        default=None, description="Default provider identifier."
    )
    providers: dict[str, ProviderConfig] = Field(
        default_factory=dict, description="Map of provider ID to configuration."
    )


class VersionDiffSummary(StorageBaseModel):
    """Summarised change counts between snapshots."""

    nodes_added: int = Field(
        ge=0, description="Number of nodes added since the previous snapshot."
    )
    nodes_removed: int = Field(
        ge=0, description="Number of nodes removed since the previous snapshot."
    )
    nodes_modified: int = Field(
        ge=0,
        description="Number of nodes with structural updates since the previous snapshot.",
    )
    relations_added: int = Field(
        ge=0, description="Number of relations added since the previous snapshot."
    )
    relations_removed: int = Field(
        ge=0, description="Number of relations removed since the previous snapshot."
    )
    relations_modified: int = Field(
        ge=0, description="Number of relations whose endpoints or metadata changed."
    )


class VersionConflict(StorageBaseModel):
    """Potential merge conflict captured during diffing."""

    entity_type: Literal["node", "relation"] = Field(
        description="Type of entity in conflict."
    )
    entity_id: str = Field(
        description="Identifier of the entity with conflicting changes."
    )
    fields: list[str] = Field(
        default_factory=list, description="Fields that differ between snapshots."
    )


def _empty_diff_summary() -> VersionDiffSummary:
    return VersionDiffSummary(
        nodes_added=0,
        nodes_removed=0,
        nodes_modified=0,
        relations_added=0,
        relations_removed=0,
        relations_modified=0,
    )


class TreeVersionRef(StorageBaseModel):
    """Reference to a stored version snapshot."""

    id: str = Field(description="Unique identifier for the version.")
    label: str = Field(description="Display label for the snapshot.")
    created_at: datetime = Field(
        description="UTC timestamp when the snapshot was created."
    )
    author: str | None = Field(
        default=None, description="Author recorded when the snapshot was captured."
    )
    notes: str | None = Field(
        default=None, description="Optional notes associated with the snapshot."
    )
    diff_summary: VersionDiffSummary | None = Field(
        default=None,
        description="Summary of changes compared to the previous snapshot.",
    )
    conflict_count: int = Field(
        default=0,
        ge=0,
        description="Number of potential conflicts detected for this snapshot.",
    )


class TreeDocument(StorageBaseModel):
    """Canonical representation of a tree stored in the filesystem."""

    id: str = Field(description="Unique identifier for the tree.")
    title: str = Field(description="Tree title shown to users.")
    description: str | None = Field(
        default=None, description="Optional narrative description."
    )
    metadata: dict[str, Any] | None = Field(
        default=None,
        description="Optional metadata such as layout, version, or ownership details.",
    )
    owner_id: str | None = Field(
        default=None, description="Optional identifier of the tree owner."
    )
    created_at: datetime = Field(description="UTC timestamp when the tree was created.")
    updated_at: datetime = Field(
        description="UTC timestamp for the most recent update."
    )
    nodes: list[NodeDocument] = Field(
        default_factory=list, description="Collection of node documents."
    )
    relations: list[RelationDocument] = Field(
        default_factory=list, description="Collection of relation documents."
    )
    version_refs: list[TreeVersionRef] = Field(
        default_factory=list, description="References to stored snapshots."
    )


class VersionDocument(StorageBaseModel):
    """Snapshot of a tree captured at a moment in time."""

    id: str = Field(description="Identifier of the version snapshot.")
    label: str = Field(description="Display label for the snapshot.")
    captured_at: datetime = Field(
        description="Timestamp when the snapshot was captured."
    )
    author: str | None = Field(
        default=None, description="Recorded author for the snapshot."
    )
    notes: str | None = Field(
        default=None, description="Optional notes explaining the snapshot."
    )
    diff: VersionDiffSummary = Field(
        default_factory=_empty_diff_summary,
        description="Summary of changes since the previous snapshot.",
    )
    conflicts: list[VersionConflict] = Field(
        default_factory=list,
        description="Potential conflicts detected while capturing the snapshot.",
    )
    tree: TreeDocument = Field(description="Tree data captured at snapshot time.")


class AccountDocument(StorageBaseModel):
    """Stored representation of a user account."""

    id: str = Field(description="Unique account identifier.")
    name: str = Field(description="Display name for the account.")
    api_key: str = Field(description="Unique API key for authentication.")
    has_ai_access: bool = Field(
        default=False, description="Whether AI features are enabled."
    )
    created_at: datetime = Field(
        description="UTC timestamp when the account was created."
    )
    updated_at: datetime = Field(
        description="UTC timestamp of the most recent update."
    )


__all__ = [
    "AccountDocument",
    "IndexEntry",
    "NodeDocument",
    "ProviderConfig",
    "ProviderRegistryDocument",
    "RelationDocument",
    "RelationMetadata",
    "TreeDocument",
    "TreeVersionRef",
    "ValidationEntry",
    "VersionDocument",
    "VersionDiffSummary",
    "VersionConflict",
]
