"""Domain models for the Organize module.

Implements CaptureItem, OrganizeDecision, and RouteRecord from ADR-0001.
The CaptureItem is the mutable record one-to-one with an AtomicCaptureSource.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StorageBaseModel

# --- Enums ---

ReviewState = Literal[
    "proposed",
    "needs_clarification",
    "approved",
    "deferred",
    "completed",
    "deleted",
]

DecisionAction = Literal[
    "edit",
    "clarify",
    "approve",
    "defer",
    "complete",
    "delete",
    "route",
]

DestinationType = Literal["external_task_tracker", "brainbuddy_problem"]

RouteStatus = Literal["pending", "dispatching", "succeeded", "failed", "cancelled"]

AvoidanceReason = Literal[
    "not_actionable",
    "duplicate",
    "obsolete",
    "not_worth_cost",
    "other",
]


class ClarificationRecord(StorageBaseModel):
    """Clarification question and optional answer."""

    question: str = Field(description="Clarification question text.")
    answer: str | None = Field(
        default=None, description="User's answer, if resolved."
    )
    resolved_at: datetime | None = Field(
        default=None, description="When the clarification was resolved."
    )


class RouteErrorRecord(StorageBaseModel):
    """Error for a failed route dispatch."""

    code: str = Field(description="Machine-readable error code.")
    retryable: bool = Field(description="Whether the dispatch can be retried.")


class CaptureItem(StorageBaseModel):
    """Mutable capture item (Organize-owned, one-to-one with source).

    Tracks the user decision lifecycle: proposed -> approved -> completed,
    with needs_clarification, deferred, and deleted branches.
    """

    id: str = Field(description="ID shared with the AtomicCaptureSource.")
    owner_id: str = Field(description="Owning user identifier.")
    source_capture_id: str = Field(description="Parent capture session ID.")
    current_text: str = Field(description="Current (possibly edited) text.")
    review_state: ReviewState = Field(
        default="proposed", description="Current review lifecycle state."
    )
    clarification: ClarificationRecord | None = Field(
        default=None, description="Active clarification, if any."
    )
    destination_intent: Literal["none", "external_task_tracker", "brainbuddy_problem"] = (
        Field(default="none", description="Intended routing destination.")
    )
    route_id: str | None = Field(
        default=None, description="Associated RouteRecord ID, if routed."
    )
    crt_candidate_id: str | None = Field(
        default=None,
        description="Associated ProblemCandidate ID, if promoted.",
    )
    created_at: datetime = Field(description="UTC creation timestamp.")
    updated_at: datetime = Field(description="UTC last-update timestamp.")
    schema_version: str = Field(default="1", description="Schema version.")
    revision: int = Field(default=1, ge=1, description="Optimistic concurrency revision.")


class OrganizeDecision(StorageBaseModel):
    """Audit record for a single organize action.

    Append-only: each edit/approve/defer/delete/route creates a new decision.
    """

    id: str = Field(description="Unique decision identifier.")
    owner_id: str = Field(description="Owning user identifier.")
    atomic_capture_id: str = Field(description="Capture item / source ID.")
    actor_id: str = Field(description="User who made the decision.")
    action: DecisionAction = Field(description="Action type.")
    from_state: ReviewState = Field(description="Prior review state.")
    to_state: ReviewState = Field(description="Resulting review state.")
    reason: str | None = Field(default=None, description="Optional reason.")
    avoidance_reason: AvoidanceReason | None = Field(
        default=None, description="Structured reason for deleting low-value work."
    )
    patch: str | None = Field(
        default=None, description="Text diff for edit actions, if applicable."
    )
    created_at: datetime = Field(description="UTC timestamp.")
    correlation_id: str = Field(description="Correlation ID for tracing.")
    idempotency_key: str = Field(description="Idempotency key for deduplication.")


class RouteRecord(StorageBaseModel):
    """Routing record for dispatching a capture to an external destination.

    Tracks the dispatch lifecycle: pending -> dispatching -> succeeded/failed.
    """

    id: str = Field(description="Unique route identifier.")
    owner_id: str = Field(description="Owning user identifier.")
    atomic_capture_id: str = Field(description="Capture item ID being routed.")
    destination: DestinationType = Field(
        description="Where the capture is being sent."
    )
    status: RouteStatus = Field(
        default="pending", description="Current dispatch status."
    )
    external_ref: str | None = Field(
        default=None, description="Opaque external ID from the adapter."
    )
    candidate_id: str | None = Field(
        default=None,
        description="ProblemCandidate ID for brainbuddy_problem routes.",
    )
    attempt_count: int = Field(
        default=0, ge=0, description="Dispatch attempts so far."
    )
    last_error: RouteErrorRecord | None = Field(
        default=None, description="Last dispatch error, if any."
    )
    requested_at: datetime = Field(description="UTC request timestamp.")
    completed_at: datetime | None = Field(
        default=None, description="UTC completion timestamp."
    )
    revision: int = Field(default=1, ge=1, description="Optimistic concurrency revision.")


__all__ = [
    "AvoidanceReason",
    "CaptureItem",
    "ClarificationRecord",
    "DecisionAction",
    "DestinationType",
    "OrganizeDecision",
    "ReviewState",
    "RouteErrorRecord",
    "RouteRecord",
    "RouteStatus",
]
