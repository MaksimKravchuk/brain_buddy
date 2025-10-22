"""API request and response schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field

from .common import Position, StrictBaseModel, TimestampMetadata, ValidationState, VisualState
from .domain import VersionDiffSummary


class ErrorResponse(StrictBaseModel):
    """Standard error payload for API responses."""

    message: str = Field(description="Human-friendly error message.")
    detail: Any | None = Field(default=None, description="Optional structured error details.")


class TreeCreateRequest(StrictBaseModel):
    """Payload for creating a new tree."""

    title: str = Field(description="Title for the tree.")
    description: str | None = Field(default=None, description="Optional description of the tree.")


class TreeUpdateRequest(StrictBaseModel):
    """Patch payload for updating tree metadata."""

    title: str | None = Field(default=None, description="Updated title for the tree.")
    description: str | None = Field(default=None, description="Updated description for the tree.")


class TreeListItem(StrictBaseModel):
    """Summary view used for listing trees."""

    id: str = Field(description="Tree identifier.")
    title: str = Field(description="Tree title.")
    description: str | None = Field(default=None, description="Tree description.")
    updated_at: datetime = Field(description="Timestamp of most recent modification.")


class NodeCreateRequest(StrictBaseModel):
    """Payload for creating a node within a tree."""

    label: str = Field(description="Node label displayed in the UI.")
    position: Position = Field(description="Canvas position for the new node.")
    visual: VisualState | None = Field(default=None, description="Optional visual hints for the node.")


class NodeUpdateRequest(StrictBaseModel):
    """Patch payload for updating an existing node."""

    label: str | None = Field(default=None, description="Updated node label.")
    position: Position | None = Field(default=None, description="Updated canvas position.")
    visual: VisualState | None = Field(default=None, description="Updated visual hints.")


class NodeResponse(StrictBaseModel):
    """Full node representation returned by API endpoints."""

    id: str = Field(description="Node identifier.")
    label: str = Field(description="Node label.")
    position: Position = Field(description="Canvas position.")
    metadata: TimestampMetadata = Field(description="Timestamps metadata.")
    visual: VisualState | None = Field(default=None, description="Visual hints for UI rendering.")
    validation: ValidationState | None = Field(default=None, description="Latest validation state.")
    incoming_count: int = Field(ge=0, description="Number of relations pointing to this node.")
    outgoing_count: int = Field(ge=0, description="Number of relations originating from this node.")


class RelationCreateRequest(StrictBaseModel):
    """Payload for creating a relation between nodes."""

    source_id: str = Field(description="Effect node identifier.")
    target_id: str = Field(description="Cause node identifier.")
    question_label: str = Field(default="WHY?", description="Prompt question shown on the relation.")
    notes: str | None = Field(default=None, description="Optional explanatory notes.")


class RelationUpdateRequest(StrictBaseModel):
    """Patch payload for updating a relation."""

    source_id: str | None = Field(default=None, description="Updated effect node identifier.")
    target_id: str | None = Field(default=None, description="Updated cause node identifier.")
    question_label: str | None = Field(default=None, description="Updated prompt question.")
    notes: str | None = Field(default=None, description="Updated notes.")


class RelationResponse(StrictBaseModel):
    """API representation of a relation."""

    id: str = Field(description="Relation identifier.")
    source_id: str = Field(description="Effect node identifier.")
    target_id: str = Field(description="Cause node identifier.")
    question_label: str = Field(description="Prompt question for the relation.")
    notes: str | None = Field(default=None, description="Optional notes.")
    metadata: TimestampMetadata = Field(description="Relation timestamps metadata.")


class VersionCreateRequest(StrictBaseModel):
    """Payload to create a new snapshot version."""

    label: str | None = Field(default=None, description="Optional label for the snapshot.")
    author: str | None = Field(default=None, description="Optional author metadata for the snapshot.")
    notes: str | None = Field(default=None, description="Optional notes providing context for the snapshot.")


class VersionListItem(StrictBaseModel):
    """List response item describing a version snapshot."""

    id: str = Field(description="Version identifier.")
    label: str = Field(description="Display name for the version.")
    created_at: datetime = Field(description="Timestamp when the version was created.")
    author: str | None = Field(default=None, description="Recorded author for the snapshot.")
    notes: str | None = Field(default=None, description="Optional notes attached to the snapshot.")
    diff_summary: VersionDiffSummary | None = Field(
        default=None, description="Summary of changes compared to the previous snapshot."
    )
    conflict_count: int = Field(default=0, ge=0, description="Number of conflicts detected for the snapshot.")


class TreeDetailResponse(StrictBaseModel):
    """Detailed tree payload returned from read endpoints."""

    id: str = Field(description="Tree identifier.")
    title: str = Field(description="Tree title.")
    description: str | None = Field(default=None, description="Tree description.")
    created_at: datetime = Field(description="Tree creation timestamp.")
    updated_at: datetime = Field(description="Last updated timestamp.")
    nodes: list[NodeResponse] = Field(default_factory=list, description="Collection of nodes for this tree.")
    relations: list[RelationResponse] = Field(default_factory=list, description="Collection of relations for this tree.")
    versions: list[VersionListItem] = Field(default_factory=list, description="Snapshot references for this tree.")


class ValidationRequest(StrictBaseModel):
    """Request payload to trigger validation for a node."""

    provider: str | None = Field(default=None, description="Preferred provider identifier to execute validation.")
    prompt_overrides: dict[str, Any] | None = Field(default=None, description="Overrides forwarded to provider prompt template.")


class ValidationResponse(StrictBaseModel):
    """Response payload returned after validation completes."""

    node_id: str = Field(description="Identifier of the validated node.")
    provider: str = Field(description="Provider identifier used.")
    confidence: int = Field(ge=0, le=100, description="Confidence score from provider.")
    summary: str = Field(description="Brief summary returned by provider.")
    checked_at: datetime = Field(description="Timestamp when validation ran.")


class ValidationHistoryResponse(StrictBaseModel):
    """Collection of historical validation results for a node."""

    model_config = ConfigDict(str_to_lower=False)

    items: list[ValidationResponse] = Field(default_factory=list, description="Chronological validation entries.")


__all__ = [
    "ErrorResponse",
    "NodeCreateRequest",
    "NodeResponse",
    "NodeUpdateRequest",
    "RelationCreateRequest",
    "RelationResponse",
    "RelationUpdateRequest",
    "TreeCreateRequest",
    "TreeDetailResponse",
    "TreeListItem",
    "TreeUpdateRequest",
    "ValidationHistoryResponse",
    "ValidationRequest",
    "ValidationResponse",
    "VersionCreateRequest",
    "VersionListItem",
]
