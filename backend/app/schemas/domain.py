"""Domain-level schemas matching on-disk documents."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field

from .common import Position, StrictBaseModel, TimestampMetadata, ValidationState, VisualState


class NodeDocument(StrictBaseModel):
    """Full representation of a node as stored on disk."""

    id: str = Field(description="Unique identifier for the node.")
    label: str = Field(description="Display label for the node.")
    position: Position = Field(description="Canvas position of the node.")
    metadata: TimestampMetadata = Field(description="Timestamps and authorship metadata.")
    visual: VisualState | None = Field(default=None, description="Visual hints for rendering.")
    validation: ValidationState | None = Field(default=None, description="Latest validation snapshot.")
    extra: dict[str, Any] | None = Field(default=None, description="Reserved for future structured metadata.")


class RelationMetadata(StrictBaseModel):
    """Metadata specific to relations."""

    created_at: datetime = Field(description="UTC timestamp when the relation was created.")
    updated_at: datetime = Field(description="UTC timestamp for the most recent relation update.")
    author: str | None = Field(default=None, description="Optional author identifier.")


class RelationDocument(StrictBaseModel):
    """Stored representation of a directed relation between nodes."""

    id: str = Field(description="Unique identifier for the relation.")
    source_id: str = Field(description="Identifier of the effect node.")
    target_id: str = Field(description="Identifier of the cause node.")
    question_label: str = Field(default="WHY?", description="Prompt associated with the relation.")
    notes: str | None = Field(default=None, description="Optional explanatory notes.")
    metadata: RelationMetadata = Field(description="Timestamps and authorship metadata.")


class TreeVersionRef(StrictBaseModel):
    """Reference to a stored version snapshot."""

    id: str = Field(description="Unique identifier for the version.")
    label: str = Field(description="Display label for the snapshot.")
    created_at: datetime = Field(description="UTC timestamp when the snapshot was created.")


class TreeDocument(StrictBaseModel):
    """Canonical representation of a tree stored in the filesystem."""

    id: str = Field(description="Unique identifier for the tree.")
    title: str = Field(description="Tree title shown to users.")
    description: str | None = Field(default=None, description="Optional narrative description.")
    created_at: datetime = Field(description="UTC timestamp when the tree was created.")
    updated_at: datetime = Field(description="UTC timestamp for the most recent update.")
    nodes: list[NodeDocument] = Field(default_factory=list, description="Collection of node documents.")
    relations: list[RelationDocument] = Field(default_factory=list, description="Collection of relation documents.")
    version_refs: list[TreeVersionRef] = Field(default_factory=list, description="References to stored snapshots.")


class VersionDocument(StrictBaseModel):
    """Snapshot of a tree captured at a moment in time."""

    id: str = Field(description="Identifier of the version snapshot.")
    label: str = Field(description="Display label for the snapshot.")
    captured_at: datetime = Field(description="Timestamp when the snapshot was captured.")
    tree: TreeDocument = Field(description="Tree data captured at snapshot time.")


class ValidationEntry(StrictBaseModel):
    """Entry stored in validation history for a node."""

    confidence: int = Field(ge=0, le=100, description="Confidence score reported by provider.")
    summary: str = Field(description="Provider supplied summary guidance.")
    provider: str = Field(description="Provider identifier.")
    prompt_hash: str = Field(description="Stable hash of the prompt used.")
    checked_at: datetime = Field(description="Timestamp when validation occurred.")
    raw_response: dict[str, Any] | None = Field(default=None, description="Optional raw provider payload for audit.")


class IndexEntry(StrictBaseModel):
    """Entry stored in the global tree index."""

    id: str = Field(description="Tree identifier.")
    title: str = Field(description="Tree title.")
    description: str | None = Field(default=None, description="Tree description.")
    updated_at: datetime = Field(description="Timestamp of most recent modification.")


class ProviderConfig(StrictBaseModel):
    """Configuration for a single AI provider."""

    model_config = ConfigDict(extra="allow")

    api_key_ref: str | None = Field(default=None, description="Path or reference to API key.")
    model: str | None = Field(default=None, description="Model identifier to use for requests.")


class ProviderRegistryDocument(StrictBaseModel):
    """Top-level provider configuration stored on disk."""

    default_provider: str | None = Field(default=None, description="Default provider identifier.")
    providers: dict[str, ProviderConfig] = Field(default_factory=dict, description="Map of provider ID to configuration.")


__all__ = [
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
]
