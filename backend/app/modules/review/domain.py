"""Domain models for the Review module (ADR-0001)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StorageBaseModel
from app.utils.time import utcnow

ReviewStatus = Literal["open", "completed", "abandoned"]
ReviewOutcomeAction = Literal[
    "keep", "edit", "delete", "defer", "route", "promote_to_crt"
]


class WeeklyReviewOutcome(StorageBaseModel):
    """Immutable per-item outcome within a Weekly Review.

    Records the decision and links to any resulting organize decision,
    route, or promotion. One outcome per item per review.
    """

    id: str = Field(description="Unique outcome ID.")
    owner_id: str = Field(description="Owning user ID.")
    weekly_review_id: str = Field(description="Parent review ID.")
    atomic_capture_id: str = Field(description="Item this outcome addresses.")
    action: ReviewOutcomeAction = Field(description="Decision action.")
    organize_decision_id: str | None = Field(
        default=None, description="OrganizeDecision.id if created."
    )
    route_id: str | None = Field(default=None, description="RouteRecord.id if created.")
    promotion_id: str | None = Field(
        default=None, description="CrtPromotion.id if created."
    )
    reason: str | None = Field(default=None, description="Optional user reason.")
    avoidance_reason: str | None = Field(
        default=None, description="Structured avoidance reason for deletions."
    )
    decided_at: datetime = Field(default_factory=utcnow)


class WeeklyReview(StorageBaseModel):
    """Weekly Review session aggregating a period's item decisions.

    Snapshots eligible item IDs at creation time. Completing requires
    one outcome per snapshotted item. Completion is idempotent.
    """

    id: str = Field(description="Unique review ID.")
    owner_id: str = Field(description="Owning user ID.")
    period_start: datetime = Field(description="Review period start.")
    period_end: datetime = Field(description="Review period end.")
    status: ReviewStatus = Field(default="open")
    item_ids: list[str] = Field(
        default_factory=list, description="Snapshotted eligible item IDs."
    )
    outcomes: list[WeeklyReviewOutcome] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = Field(default=None)
    revision: int = Field(default=1)
    schema_version: str = Field(default="1")
