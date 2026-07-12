"""Domain models for the Thinking/CRT module.

Implements ProblemCandidate and CrtPromotion from ADR-0001.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StorageBaseModel

# --- Enums ---

CandidateSignal = Literal["manual", "repeated", "complex"]

CandidateStatus = Literal["open", "promotion_requested", "promoted", "dismissed"]

PromotionStatus = Literal["pending", "promoting", "succeeded", "failed"]


class PromotionErrorRecord(StorageBaseModel):
    """Error for a failed promotion."""

    code: str = Field(description="Machine-readable error code.")
    retryable: bool = Field(description="Whether the promotion can be retried.")


class ProblemCandidate(StorageBaseModel):
    """A problem identified for potential CRT promotion.

    Created from capture sources; promotion is user-confirmed.
    """

    id: str = Field(description="Unique candidate identifier.")
    owner_id: str = Field(description="Owning user identifier.")
    source_capture_ids: list[str] = Field(
        description="Atomic capture source IDs that prompted this candidate."
    )
    title: str = Field(description="Short title for the problem.")
    context: str = Field(description="Context/description of the problem.")
    signal: CandidateSignal = Field(
        description="How this candidate was identified."
    )
    signal_reasons: list[str] = Field(
        default_factory=list, description="Reasons supporting the signal."
    )
    status: CandidateStatus = Field(
        default="open", description="Current candidate status."
    )
    created_at: datetime = Field(description="UTC creation timestamp.")
    updated_at: datetime = Field(description="UTC last-update timestamp.")
    revision: int = Field(default=1, ge=1, description="Optimistic concurrency revision.")


class CrtPromotion(StorageBaseModel):
    """Record of a CRT promotion attempt.

    Tracks the promotion lifecycle: pending -> promoting -> succeeded/failed.
    """

    id: str = Field(description="Unique promotion identifier.")
    owner_id: str = Field(description="Owning user identifier.")
    problem_candidate_id: str = Field(
        description="Candidate being promoted."
    )
    status: PromotionStatus = Field(
        default="pending", description="Current promotion status."
    )
    tree_id: str | None = Field(
        default=None, description="CRT tree ID created/linked by promotion."
    )
    root_node_id: str | None = Field(
        default=None, description="Root node ID in the CRT tree."
    )
    source_capture_ids: list[str] = Field(
        default_factory=list,
        description="Source captures linked to this promotion.",
    )
    attempt_count: int = Field(
        default=0, ge=0, description="Promotion attempts so far."
    )
    last_error: PromotionErrorRecord | None = Field(
        default=None, description="Last promotion error, if any."
    )
    requested_at: datetime = Field(description="UTC request timestamp.")
    completed_at: datetime | None = Field(
        default=None, description="UTC completion timestamp."
    )
    revision: int = Field(default=1, ge=1, description="Optimistic concurrency revision.")


__all__ = [
    "CandidateSignal",
    "CandidateStatus",
    "CrtPromotion",
    "ProblemCandidate",
    "PromotionErrorRecord",
    "PromotionStatus",
]
