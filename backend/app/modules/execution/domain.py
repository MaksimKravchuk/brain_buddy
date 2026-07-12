"""Domain models for the Execution module.

Implements DispatchAttempt and EvidenceResult from ADR-0001.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StorageBaseModel

# --- Enums ---

DispatchStatus = Literal["started", "succeeded", "failed"]

EvidenceSource = Literal["external_task_tracker", "crt", "manual"]

EvidenceKind = Literal["evidence", "result"]

EvidenceStatus = Literal["recorded", "superseded"]


class DispatchAttempt(StorageBaseModel):
    """Record of a single dispatch attempt to the task tracker."""

    id: str = Field(description="Unique dispatch identifier.")
    owner_id: str = Field(description="Owning user identifier.")
    route_id: str = Field(description="RouteRecord that initiated this dispatch.")
    adapter: str = Field(description="Adapter identifier used.")
    status: DispatchStatus = Field(
        default="started", description="Current dispatch status."
    )
    external_ref: str | None = Field(
        default=None, description="External task ID from the adapter."
    )
    error_code: str | None = Field(
        default=None, description="Error code if the dispatch failed."
    )
    retryable: bool | None = Field(
        default=None, description="Whether the dispatch can be retried."
    )
    started_at: datetime = Field(description="UTC start timestamp.")
    completed_at: datetime | None = Field(
        default=None, description="UTC completion timestamp."
    )


class EvidenceResult(StorageBaseModel):
    """Evidence or result linked back to originating captures.

    Append-only except for `recorded -> superseded`. At least one
    atomic_capture_id is required.
    """

    id: str = Field(description="Unique evidence/result identifier.")
    owner_id: str = Field(description="Owning user identifier.")
    source: EvidenceSource = Field(
        description="Where this evidence/result came from."
    )
    kind: EvidenceKind = Field(description="Evidence or result type.")
    status: EvidenceStatus = Field(
        default="recorded", description="Current status."
    )
    title: str = Field(description="Short title.")
    summary: str | None = Field(
        default=None, description="Longer summary, if available."
    )
    uri: str | None = Field(
        default=None, description="Link to the source, if applicable."
    )
    atomic_capture_ids: list[str] = Field(
        description="Originating capture IDs (at least one required)."
    )
    route_id: str | None = Field(
        default=None, description="RouteRecord ID, if from a route."
    )
    weekly_review_id: str | None = Field(
        default=None, description="Weekly review ID, if applicable."
    )
    tree_id: str | None = Field(
        default=None, description="CRT tree ID, if from CRT."
    )
    node_ids: list[str] = Field(
        default_factory=list,
        description="CRT node IDs, if applicable.",
    )
    observed_at: datetime = Field(
        description="When the evidence/result was observed."
    )
    recorded_at: datetime = Field(
        description="When it was recorded in the system."
    )
    actor_id: str = Field(description="User who recorded it.")


__all__ = [
    "DispatchAttempt",
    "DispatchStatus",
    "EvidenceKind",
    "EvidenceResult",
    "EvidenceSource",
    "EvidenceStatus",
]
