"""API schemas for the vNext capture workflow.

Maps to the HTTP API defined in ADR-0001:
  POST /capture-sessions
  GET  /capture-sessions/{id}
  POST /capture-sessions/{id}/retry
  POST /captures/{id}/decisions
  POST /captures/{id}/routes
  GET  /captures/{id}/results
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import StrictBaseModel

# --- Capture session schemas ---


class ConsentRequest(StrictBaseModel):
    """Consent payload for external processing."""

    external_processing_allowed: bool = Field(
        description="Whether external processing is allowed."
    )


class TextCaptureRequest(StrictBaseModel):
    """Payload for text-based capture (JSON submission)."""

    text: str = Field(description="Text to capture and split.")
    consent: ConsentRequest = Field(
        default_factory=lambda: ConsentRequest(external_processing_allowed=False),
        description="Processing consent.",
    )


class CaptureSessionResponse(StrictBaseModel):
    """Response for a capture session."""

    id: str = Field(description="Session ID.")
    owner_id: str = Field(description="Owning user ID.")
    input_kind: str = Field(description="Input modality (voice or text).")
    status: str = Field(description="Pipeline status.")
    transcript: dict[str, Any] | None = Field(
        default=None, description="Transcript metadata (no raw text in logs)."
    )
    attempt_count: int = Field(description="Transcription attempts.")
    last_error: dict[str, Any] | None = Field(
        default=None, description="Last error details, if failed."
    )
    atomic_capture_ids: list[str] = Field(
        default_factory=list, description="Atomic capture IDs."
    )
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")
    revision: int = Field(description="Optimistic concurrency revision.")


class AtomicCaptureSourceResponse(StrictBaseModel):
    """Response for an atomic capture source."""

    id: str = Field(description="Source ID (shared with CaptureItem).")
    capture_session_id: str = Field(description="Parent session ID.")
    ordinal: int = Field(description="Position in the session.")
    kind: str = Field(description="Inferred kind (task/note/question/problem_candidate).")
    source_text: str = Field(description="Immutable source text.")
    classification: dict[str, Any] | None = Field(
        default=None, description="Classification metadata."
    )
    created_at: datetime = Field(description="Creation timestamp.")


class CaptureItemResponse(StrictBaseModel):
    """Response for a capture item."""

    id: str = Field(description="Item ID (shared with source).")
    source_capture_id: str = Field(description="Parent session ID.")
    current_text: str = Field(description="Current (possibly edited) text.")
    review_state: str = Field(description="Review lifecycle state.")
    clarification: dict[str, Any] | None = Field(
        default=None, description="Active clarification, if any."
    )
    destination_intent: str = Field(description="Intended routing destination.")
    route_id: str | None = Field(default=None, description="Route ID, if routed.")
    crt_candidate_id: str | None = Field(
        default=None, description="Candidate ID, if promoted."
    )
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")
    revision: int = Field(description="Optimistic concurrency revision.")


class CaptureSessionDetailResponse(StrictBaseModel):
    """Detailed response for a capture session with items."""

    id: str = Field(description="Session ID.")
    owner_id: str = Field(description="Owning user ID.")
    input_kind: str = Field(description="Input modality.")
    status: str = Field(description="Pipeline status.")
    transcript: dict[str, Any] | None = Field(
        default=None,
        description="Transcript metadata (text is included for review).",
    )
    attempt_count: int = Field(description="Transcription attempts.")
    last_error: dict[str, Any] | None = Field(
        default=None, description="Last error, if failed."
    )
    atomic_captures: list[AtomicCaptureSourceResponse] = Field(
        default_factory=list, description="Atomic capture sources."
    )
    items: list[CaptureItemResponse] = Field(
        default_factory=list, description="Mutable capture items."
    )
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")
    revision: int = Field(description="Optimistic concurrency revision.")


# --- Decision schemas ---


DecisionAction = Literal[
    "edit",
    "clarify",
    "approve",
    "defer",
    "delete",
]


class DecisionRequest(StrictBaseModel):
    """Payload for capture decisions."""

    action: DecisionAction = Field(description="Decision action.")
    expected_revision: int = Field(
        description="Expected current revision (optimistic concurrency)."
    )
    new_text: str | None = Field(
        default=None, description="New text for edit actions."
    )
    question: str | None = Field(
        default=None, description="Clarification question."
    )
    answer: str | None = Field(
        default=None, description="Clarification answer (resolves if provided)."
    )
    reason: str | None = Field(default=None, description="Reason for the decision.")
    avoidance_reason: str | None = Field(
        default=None,
        description="Structured reason for deleting low-value work.",
    )


class DecisionResponse(StrictBaseModel):
    """Response for a capture decision."""

    item: CaptureItemResponse = Field(description="Updated capture item.")
    decision_id: str = Field(description="Decision record ID.")


# --- Route schemas ---


DestinationType = Literal["external_task_tracker", "brainbuddy_problem"]


class RouteRequest(StrictBaseModel):
    """Payload for requesting a route."""

    destination: DestinationType = Field(description="Where to route the capture.")


class RouteResponse(StrictBaseModel):
    """Response for a route record."""

    id: str = Field(description="Route ID.")
    atomic_capture_id: str = Field(description="Capture item ID being routed.")
    destination: str = Field(description="Destination type.")
    status: str = Field(description="Dispatch status.")
    external_ref: str | None = Field(
        default=None, description="External task ID from adapter."
    )
    attempt_count: int = Field(description="Dispatch attempts.")
    last_error: dict[str, Any] | None = Field(
        default=None, description="Last error, if any."
    )
    requested_at: datetime = Field(description="Request timestamp.")
    completed_at: datetime | None = Field(
        default=None, description="Completion timestamp."
    )
    revision: int = Field(description="Optimistic concurrency revision.")


class RouteDetailResponse(StrictBaseModel):
    """Detailed response for a route with the updated capture item."""

    route: RouteResponse = Field(description="Route record.")
    item: CaptureItemResponse = Field(description="Updated capture item.")


# --- Evidence/result schemas ---


class EvidenceResultResponse(StrictBaseModel):
    """Response for an evidence/result item."""

    id: str = Field(description="Result ID.")
    source: str = Field(description="Where it came from.")
    kind: str = Field(description="Evidence or result type.")
    status: str = Field(description="Current status.")
    title: str = Field(description="Short title.")
    summary: str | None = Field(default=None, description="Longer summary.")
    uri: str | None = Field(default=None, description="Link to source.")
    atomic_capture_ids: list[str] = Field(
        description="Originating capture IDs."
    )
    route_id: str | None = Field(default=None, description="Route ID.")
    tree_id: str | None = Field(default=None, description="CRT tree ID.")
    node_ids: list[str] = Field(
        default_factory=list, description="CRT node IDs."
    )
    observed_at: datetime = Field(description="Observation timestamp.")
    recorded_at: datetime = Field(description="Recording timestamp.")


__all__ = [
    "AtomicCaptureSourceResponse",
    "CaptureItemResponse",
    "CaptureSessionDetailResponse",
    "CaptureSessionResponse",
    "ConsentRequest",
    "DecisionRequest",
    "DecisionResponse",
    "EvidenceResultResponse",
    "RouteDetailResponse",
    "RouteRequest",
    "RouteResponse",
    "TextCaptureRequest",
]
