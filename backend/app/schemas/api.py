"""API request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, ConfigDict, Field

from .common import Position, StrictBaseModel
from .domain import VersionDiffSummary

NodeType = Literal["parent", "child"]
HighlightState = Literal["none", "cause_candidate", "effect_spanning"]
RelationKind = Literal["why"]
FeedbackStatus = Literal["success", "failed", "pending"]


class ErrorResponse(StrictBaseModel):
    """Standard error payload for API responses."""

    model_config = ConfigDict(populate_by_name=True)

    message: str = Field(description="Human-friendly error message.")
    detail: Any | None = Field(
        default=None, description="Optional structured error details."
    )
    reference_id: str | None = Field(
        default=None,
        description=(
            "Optional correlation/reference identifier for support or debugging."
        ),
        validation_alias=AliasChoices("reference_id", "reference"),
        serialization_alias="reference_id",
    )


class RelationCounts(StrictBaseModel):
    """Upstream and downstream relation counts for a node."""

    up_count: int = Field(
        default=0,
        ge=0,
        description="Relations where this node is the source (source_node_id).",
    )
    down_count: int = Field(
        default=0,
        ge=0,
        description="Relations where this node is the target (target_node_id).",
    )


class NodeCreateRequest(StrictBaseModel):
    """Payload for creating a node within a tree."""

    label: str = Field(description="Node label displayed in the UI.")
    type: NodeType = Field(description="Node type describing its role in the tree.")
    position: Position = Field(description="Canvas position for the new node.")
    highlight_state: HighlightState = Field(
        default="none", description="Current highlight state for the node."
    )


class NodeUpdateRequest(StrictBaseModel):
    """Patch payload for updating an existing node."""

    label: str | None = Field(default=None, description="Updated node label.")
    type: NodeType | None = Field(default=None, description="Updated node type.")
    position: Position | None = Field(
        default=None, description="Updated canvas position."
    )
    highlight_state: HighlightState | None = Field(
        default=None, description="Updated highlight state."
    )


class NodeResponse(StrictBaseModel):
    """Full node representation returned by API endpoints."""

    id: str = Field(description="Node identifier.")
    label: str = Field(description="Node label.")
    type: NodeType = Field(description="Node type describing its role in the tree.")
    position: Position = Field(description="Canvas position.")
    highlight_state: HighlightState = Field(
        default="none", description="Current highlight state for the node."
    )
    relation_counts: RelationCounts = Field(
        default_factory=RelationCounts,
        description=(
            "Counts of upstream (source_node_id) and "
            "downstream (target_node_id) relations."
        ),
    )


class RelationCreateRequest(StrictBaseModel):
    """Payload for creating a relation between nodes."""

    model_config = ConfigDict(populate_by_name=True)

    source_node_id: str = Field(
        validation_alias=AliasChoices("source_node_id", "from_id"),
        description="Cause node identifier (lower node).",
    )
    target_node_id: str = Field(
        validation_alias=AliasChoices("target_node_id", "to_id"),
        description="Effect node identifier (upper node).",
    )
    kind: RelationKind = Field(
        default="why", description="Relation kind (only 'why' is supported)."
    )


class RelationUpdateRequest(StrictBaseModel):
    """Patch payload for updating a relation."""

    model_config = ConfigDict(populate_by_name=True)

    source_node_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("source_node_id", "from_id"),
        description="Updated cause node identifier (lower node).",
    )
    target_node_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("target_node_id", "to_id"),
        description="Updated effect node identifier (upper node).",
    )
    kind: RelationKind | None = Field(
        default=None, description="Updated relation kind."
    )


class RelationResponse(StrictBaseModel):
    """API representation of a relation."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(description="Relation identifier.")
    source_node_id: str = Field(
        description="Cause node identifier (lower node).",
        validation_alias=AliasChoices("source_node_id", "from_id"),
        serialization_alias="source_node_id",
    )
    target_node_id: str = Field(
        description="Effect node identifier (upper node).",
        validation_alias=AliasChoices("target_node_id", "to_id"),
        serialization_alias="target_node_id",
    )
    kind: RelationKind = Field(
        default="why", description="Relation kind (only 'why' is supported)."
    )
    created_at: datetime = Field(description="Timestamp when the relation was created.")


class TreeMetadata(StrictBaseModel):
    """Metadata for a tree export/import payload."""

    model_config = ConfigDict(str_to_lower=False)

    version: int = Field(
        default=1, ge=1, description="Schema version for the tree payload."
    )
    created_at: datetime = Field(description="Timestamp when the tree was created.")
    updated_at: datetime = Field(
        description="Timestamp when the tree was last updated."
    )
    layout: dict[str, Any] | None = Field(
        default=None, description="Optional layout or viewport metadata."
    )
    owner_id: str | None = Field(
        default=None, description="Optional identifier for the owning user/session."
    )

    @classmethod
    def from_timestamps(
        cls, *, created_at: datetime, updated_at: datetime, owner_id: str | None = None
    ) -> TreeMetadata:
        return cls(created_at=created_at, updated_at=updated_at, owner_id=owner_id)


class TreeCreateRequest(StrictBaseModel):
    """Payload for creating a new tree."""

    name: str = Field(description="Name for the tree.")
    owner_id: str | None = Field(default=None, description="Optional owner identifier.")
    metadata: TreeMetadata | None = Field(
        default=None, description="Optional metadata overrides."
    )
    nodes: list[NodeResponse] = Field(
        default_factory=list, description="Optional starting nodes."
    )
    relations: list[RelationResponse] = Field(
        default_factory=list, description="Optional starting relations."
    )


class TreeUpdateRequest(StrictBaseModel):
    """Payload for replacing a tree's state."""

    name: str = Field(description="Updated tree name.")
    metadata: TreeMetadata = Field(description="Updated metadata block for the tree.")
    nodes: list[NodeResponse] = Field(
        default_factory=list, description="Updated nodes."
    )
    relations: list[RelationResponse] = Field(
        default_factory=list, description="Updated relations."
    )
    owner_id: str | None = Field(default=None, description="Updated owner identifier.")


class TreeListItem(StrictBaseModel):
    """Summary view used for listing trees."""

    id: str = Field(description="Tree identifier.")
    name: str = Field(description="Tree name.")
    updated_at: datetime = Field(description="Timestamp of most recent modification.")
    owner_id: str | None = Field(default=None, description="Optional owner identifier.")


class TreeDetailResponse(StrictBaseModel):
    """Detailed tree payload returned from read endpoints."""

    id: str = Field(description="Tree identifier.")
    name: str = Field(description="Tree name.")
    metadata: TreeMetadata = Field(description="Metadata describing the tree payload.")
    nodes: list[NodeResponse] = Field(
        default_factory=list, description="Collection of nodes for this tree."
    )
    relations: list[RelationResponse] = Field(
        default_factory=list, description="Collection of relations for this tree."
    )
    owner_id: str | None = Field(default=None, description="Optional owner identifier.")


class TreeImportRequest(StrictBaseModel):
    """Import payload containing a tree export."""

    tree: TreeDetailResponse = Field(description="Complete tree payload to import.")


class TreeExportResponse(StrictBaseModel):
    """Export payload returned to clients."""

    tree: TreeDetailResponse = Field(
        description="Tree payload matching the export schema."
    )


class AiFeedbackRequest(StrictBaseModel):
    """Request payload for AI feedback on a tree."""

    consent: bool = Field(
        description="User consent to share the tree with the AI provider."
    )
    provider: str | None = Field(
        default=None, description="Optional provider identifier."
    )
    request_id: str | None = Field(
        default=None, description="Optional client-provided request identifier."
    )


class AiFeedbackResponse(StrictBaseModel):
    """Response payload containing AI feedback results."""

    status: FeedbackStatus = Field(description="Status of the AI feedback request.")
    summary: str | None = Field(
        default=None, description="AI-generated summary of the tree."
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Actionable recommendations from the AI."
    )
    request_id: str | None = Field(
        default=None, description="Echoed request identifier when provided."
    )


class VersionCreateRequest(StrictBaseModel):
    """Payload to create a new snapshot version."""

    label: str | None = Field(
        default=None, description="Optional label for the snapshot."
    )
    author: str | None = Field(
        default=None, description="Optional author metadata for the snapshot."
    )
    notes: str | None = Field(
        default=None, description="Optional notes providing context for the snapshot."
    )


class VersionListItem(StrictBaseModel):
    """List response item describing a version snapshot."""

    id: str = Field(description="Version identifier.")
    label: str = Field(description="Display name for the version.")
    created_at: datetime = Field(description="Timestamp when the version was created.")
    author: str | None = Field(
        default=None, description="Recorded author for the snapshot."
    )
    notes: str | None = Field(
        default=None, description="Optional notes attached to the snapshot."
    )
    diff_summary: VersionDiffSummary | None = Field(
        default=None,
        description="Summary of changes compared to the previous snapshot.",
    )
    conflict_count: int = Field(
        default=0, ge=0, description="Number of conflicts detected for the snapshot."
    )


class ValidationRequest(StrictBaseModel):
    """Request payload to trigger validation for a node."""

    provider: str | None = Field(
        default=None, description="Preferred provider identifier to execute validation."
    )
    prompt_overrides: dict[str, Any] | None = Field(
        default=None, description="Overrides forwarded to provider prompt template."
    )


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

    items: list[ValidationResponse] = Field(
        default_factory=list, description="Chronological validation entries."
    )


class AccountResponse(StrictBaseModel):
    """Public account information returned to the client."""

    id: str = Field(description="Account identifier.")
    name: str = Field(description="Account display name.")
    has_ai_access: bool = Field(description="Whether AI features are enabled.")


__all__ = [
    "AccountResponse",
    "ErrorResponse",
    "NodeCreateRequest",
    "NodeResponse",
    "NodeUpdateRequest",
    "RelationCreateRequest",
    "RelationCounts",
    "RelationResponse",
    "RelationUpdateRequest",
    "TreeCreateRequest",
    "TreeDetailResponse",
    "TreeExportResponse",
    "TreeImportRequest",
    "TreeListItem",
    "TreeMetadata",
    "TreeUpdateRequest",
    "AiFeedbackRequest",
    "AiFeedbackResponse",
    "ValidationHistoryResponse",
    "ValidationRequest",
    "ValidationResponse",
    "VersionCreateRequest",
    "VersionListItem",
]
