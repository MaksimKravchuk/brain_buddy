"""API schemas for vNext capture/review/thinking/execution modules.

These implement the ADR-0001 minimal HTTP API contracts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StrictBaseModel

# -- Capture --

CaptureKindApi = Literal["task", "note", "question", "problem_candidate"]
CaptureItemStateApi = Literal[
    "proposed",
    "needs_clarification",
    "approved",
    "deferred",
    "completed",
    "deleted",
]


class CaptureSessionCreateRequest(StrictBaseModel):
    """Request payload for POST /capture-sessions (text-only MVP)."""

    text: str = Field(description="Raw text to split into atomic captures.")


class CaptureItemResponse(StrictBaseModel):
    """API representation of a capture item."""

    id: str = Field(description="Capture item ID.")
    source_capture_id: str = Field(description="Parent session ID.")
    current_text: str = Field(description="Editable user text.")
    review_state: CaptureItemStateApi = Field(description="Lifecycle state.")
    kind: CaptureKindApi = Field(description="Inferred capture kind.")
    source_text: str = Field(description="Immutable original text.")
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")
    revision: int = Field(description="Optimistic concurrency revision.")


class CaptureSessionResponse(StrictBaseModel):
    """API representation of a capture session."""

    id: str = Field(description="Session ID.")
    status: str = Field(description="Session status.")
    input_kind: str = Field(description="Input modality.")
    atomic_capture_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")


class CaptureSessionDetailResponse(StrictBaseModel):
    """Session with full capture item details."""

    session: CaptureSessionResponse
    captures: list[CaptureItemResponse] = Field(default_factory=list)


class CaptureDecisionRequest(StrictBaseModel):
    """Request payload for POST /captures/{id}/decisions."""

    action: Literal[
        "edit", "clarify", "approve", "defer", "complete", "delete"
    ] = Field(description="Decision action.")
    new_text: str | None = Field(default=None, description="New text for edit.")
    expected_revision: int | None = Field(
        default=None, description="Optimistic concurrency check."
    )


# -- Review --

ReviewOutcomeActionApi = Literal[
    "keep", "edit", "delete", "defer", "route", "promote_to_crt"
]


class WeeklyReviewResponse(StrictBaseModel):
    """API representation of a weekly review."""

    id: str = Field(description="Review ID.")
    status: str = Field(description="Review status.")
    period_start: datetime = Field(description="Period start.")
    period_end: datetime = Field(description="Period end.")
    item_ids: list[str] = Field(default_factory=list)
    outcome_count: int = Field(default=0, description="Recorded outcomes so far.")
    started_at: datetime = Field(description="Start timestamp.")
    completed_at: datetime | None = Field(default=None)


class WeeklyReviewDetailResponse(StrictBaseModel):
    """Review with items and outcomes."""

    review: WeeklyReviewResponse
    items: list[CaptureItemResponse] = Field(default_factory=list)
    outcomes: list[dict] = Field(default_factory=list)


class ReviewOutcomeRequest(StrictBaseModel):
    """Request payload for POST /weekly-reviews/{id}/items/{cid}/outcomes."""

    action: ReviewOutcomeActionApi = Field(description="Outcome action.")
    reason: str | None = Field(default=None, description="Optional reason.")
    avoidance_reason: str | None = Field(
        default=None, description="Structured avoidance reason for deletions."
    )
    new_text: str | None = Field(default=None, description="New text for edit.")


class ReviewOutcomeResponse(StrictBaseModel):
    """API representation of a review outcome."""

    id: str = Field(description="Outcome ID.")
    weekly_review_id: str = Field(description="Review ID.")
    atomic_capture_id: str = Field(description="Item addressed.")
    action: ReviewOutcomeActionApi = Field(description="Outcome action.")
    reason: str | None = Field(default=None)
    avoidance_reason: str | None = Field(default=None)
    decided_at: datetime = Field(description="Decision timestamp.")


class ReviewSummaryResponse(StrictBaseModel):
    """Completion summary."""

    review_id: str = Field(description="Review ID.")
    total_items: int = Field(description="Total snapshotted items.")
    kept: int = Field(default=0)
    edited: int = Field(default=0)
    deferred: int = Field(default=0)
    deleted: int = Field(default=0)
    routed: int = Field(default=0)
    promoted: int = Field(default=0)
    completed_at: datetime = Field(description="Completion timestamp.")


# -- Thinking/CRT --


class ProblemCandidateResponse(StrictBaseModel):
    """API representation of a problem candidate."""

    id: str = Field(description="Candidate ID.")
    source_capture_ids: list[str] = Field(default_factory=list)
    title: str = Field(description="Problem title.")
    context: str = Field(default="")
    signal: str = Field(description="How identified.")
    signal_reasons: list[str] = Field(default_factory=list)
    status: str = Field(description="Candidate status.")
    created_at: datetime = Field(description="Creation timestamp.")
    updated_at: datetime = Field(description="Last update timestamp.")


class CandidateCreateRequest(StrictBaseModel):
    """Request payload for creating a problem candidate."""

    title: str = Field(description="Problem title.")
    context: str = Field(default="")
    source_capture_ids: list[str] = Field(default_factory=list)
    signal: Literal["manual", "repeated", "complex"] = Field(default="manual")
    signal_reasons: list[str] = Field(default_factory=list)


class CrtPromotionResponse(StrictBaseModel):
    """API representation of a CRT promotion."""

    id: str = Field(description="Promotion ID.")
    problem_candidate_id: str = Field(description="Candidate ID.")
    status: str = Field(description="Promotion status.")
    tree_id: str | None = Field(default=None, description="Created tree ID.")
    root_node_id: str | None = Field(default=None)
    source_capture_ids: list[str] = Field(default_factory=list)
    requested_at: datetime = Field(description="Request timestamp.")
    completed_at: datetime | None = Field(default=None)


# -- Execution --


class EvidenceResultResponse(StrictBaseModel):
    """API representation of an evidence/result."""

    id: str = Field(description="Result ID.")
    source: str = Field(description="Origin source.")
    kind: str = Field(description="Evidence or result.")
    title: str = Field(description="Short title.")
    summary: str | None = Field(default=None)
    uri: str | None = Field(default=None)
    atomic_capture_ids: list[str] = Field(default_factory=list)
    tree_id: str | None = Field(default=None)
    observed_at: datetime = Field(description="Observation timestamp.")
    recorded_at: datetime = Field(description="Recording timestamp.")


class EvidenceResultCreateRequest(StrictBaseModel):
    """Request payload for POST /results."""

    source: Literal["external_task_tracker", "crt", "manual"] = Field(
        default="manual"
    )
    kind: Literal["evidence", "result"] = Field(description="Evidence or result.")
    title: str = Field(description="Short title.")
    summary: str | None = Field(default=None)
    uri: str | None = Field(default=None)
    atomic_capture_ids: list[str] = Field(
        default_factory=list, description="Originating capture IDs."
    )
    tree_id: str | None = Field(default=None)


__all__ = [
    "CandidateCreateRequest",
    "CaptureDecisionRequest",
    "CaptureItemResponse",
    "CaptureSessionCreateRequest",
    "CaptureSessionDetailResponse",
    "CaptureSessionResponse",
    "CrtPromotionResponse",
    "EvidenceResultCreateRequest",
    "EvidenceResultResponse",
    "ProblemCandidateResponse",
    "ReviewOutcomeRequest",
    "ReviewOutcomeResponse",
    "ReviewSummaryResponse",
    "WeeklyReviewDetailResponse",
    "WeeklyReviewResponse",
]
