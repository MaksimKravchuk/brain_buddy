"""Review service: Weekly Review lifecycle and outcome recording.

Per ADR-0001:
- Starting a review snapshots eligible item IDs, not their text.
- Within a review, keep approves without destination; edit updates text
  then approves; route approves and requests destination; promote_to_crt
  approves, creates/uses a candidate, and requests promotion.
- Completing requires one outcome per item or explicit defer.
- Completion is idempotent and stores a summary with counts.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from app.exceptions import NotFoundError, ValidationFailure
from app.utils.identifiers import generate_id
from app.utils.time import utcnow

from .domain import ReviewOutcomeAction, WeeklyReview, WeeklyReviewOutcome
from .repository import ReviewRepository


class ReviewSummary(BaseModel):
    """Completion summary with counts per ADR-0001."""

    review_id: str = Field(description="Review ID.")
    total_items: int = Field(ge=0, description="Total snapshotted items.")
    kept: int = Field(ge=0, description="Items kept (approved, no destination).")
    edited: int = Field(ge=0, description="Items edited and approved.")
    deferred: int = Field(ge=0, description="Items deferred.")
    deleted: int = Field(ge=0, description="Items deleted/avoided.")
    routed: int = Field(ge=0, description="Items routed to external tracker.")
    promoted: int = Field(ge=0, description="Items promoted to CRT.")
    completed_at: datetime = Field(description="Completion timestamp.")


class ReviewService:
    """Manage Weekly Review sessions and outcomes.

    The Review service reads projections from Capture (eligible items)
    and submits Organize commands. It records resulting IDs in outcomes
    but does not duplicate state machines.
    """

    def __init__(self, repo: ReviewRepository) -> None:
        self._repo = repo

    def start_or_resume_review(
        self,
        *,
        owner_id: str,
        eligible_items: list[str],
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> WeeklyReview:
        """Start a new review or resume the most recent open one.

        If there is an open review for this owner, resume it. Otherwise
        create a new one with snapshotted item IDs.
        """
        existing = self._find_open_review(owner_id)
        if existing is not None:
            return existing

        now = utcnow()
        start = period_start or (now - timedelta(days=7))
        end = period_end or now

        review = WeeklyReview(
            id=generate_id("wr"),
            owner_id=owner_id,
            period_start=start,
            period_end=end,
            status="open",
            item_ids=list(eligible_items),
        )
        self._repo.save(review)
        return review

    def get_review(self, owner_id: str, review_id: str) -> WeeklyReview:
        return self._repo.load(owner_id, review_id)

    def list_reviews_for_owner(self, owner_id: str) -> list[WeeklyReview]:
        return self._repo.list_for_owner(owner_id)

    def record_outcome(
        self,
        *,
        owner_id: str,
        review_id: str,
        capture_id: str,
        action: ReviewOutcomeAction,
        reason: str | None = None,
        avoidance_reason: str | None = None,
        organize_decision_id: str | None = None,
        route_id: str | None = None,
        promotion_id: str | None = None,
    ) -> WeeklyReviewOutcome:
        """Record a per-item outcome within a review.

        If an outcome already exists for this item in this review,
        replace it (append superseding outcome while review is open).
        """
        review = self._repo.load(owner_id, review_id)
        if review.owner_id != owner_id:
            raise NotFoundError("WeeklyReview", review_id)
        if review.status != "open":
            raise ValidationFailure(
                "Cannot record outcome for a completed review.",
                detail={"reason": "review_closed", "review_id": review_id},
            )
        if capture_id not in review.item_ids:
            raise ValidationFailure(
                f"Item '{capture_id}' is not in this review's snapshot.",
                detail={"reason": "item_not_in_snapshot", "capture_id": capture_id},
            )

        # Remove any existing outcome for this item (supersede).
        review.outcomes = [
            o for o in review.outcomes if o.atomic_capture_id != capture_id
        ]

        outcome = WeeklyReviewOutcome(
            id=generate_id("wo"),
            owner_id=owner_id,
            weekly_review_id=review_id,
            atomic_capture_id=capture_id,
            action=action,
            reason=reason,
            avoidance_reason=avoidance_reason,
            organize_decision_id=organize_decision_id,
            route_id=route_id,
            promotion_id=promotion_id,
        )
        review.outcomes.append(outcome)
        review.revision += 1
        self._repo.save(review)
        return outcome

    def complete_review(
        self,
        *,
        owner_id: str,
        review_id: str,
    ) -> ReviewSummary:
        """Validate coverage and complete the review.

        Per ADR-0001: completion requires one outcome per snapshotted
        item or an explicit defer outcome. Completion is idempotent.
        """
        review = self._repo.load(owner_id, review_id)
        if review.owner_id != owner_id:
            raise NotFoundError("WeeklyReview", review_id)

        if review.status == "completed":
            # Idempotent: return the existing summary.
            return self._build_summary(review)

        if review.status == "abandoned":
            raise ValidationFailure(
                "Cannot complete an abandoned review.",
                detail={"reason": "review_abandoned", "review_id": review_id},
            )

        # Validate coverage: every item has an outcome.
        items_with_outcomes = {
            o.atomic_capture_id for o in review.outcomes
        }
        uncovered = set(review.item_ids) - items_with_outcomes
        if uncovered:
            raise ValidationFailure(
                f"Review has {len(uncovered)} uncovered item(s). "
                "Each item needs an outcome or explicit defer.",
                detail={
                    "reason": "incomplete_coverage",
                    "uncovered": sorted(uncovered),
                },
            )

        review.status = "completed"
        review.completed_at = utcnow()
        review.revision += 1
        self._repo.save(review)
        return self._build_summary(review)

    # -- Internal --

    def _find_open_review(self, owner_id: str) -> WeeklyReview | None:
        reviews = self._repo.list_for_owner(owner_id)
        open_reviews = [r for r in reviews if r.status == "open"]
        if not open_reviews:
            return None
        # Return the most recent open review.
        return max(open_reviews, key=lambda r: r.started_at)

    @staticmethod
    def _build_summary(review: WeeklyReview) -> ReviewSummary:
        counts = {
            "keep": 0,
            "edit": 0,
            "defer": 0,
            "delete": 0,
            "route": 0,
            "promote_to_crt": 0,
        }
        for outcome in review.outcomes:
            counts[outcome.action] = counts.get(outcome.action, 0) + 1

        return ReviewSummary(
            review_id=review.id,
            total_items=len(review.item_ids),
            kept=counts["keep"],
            edited=counts["edit"],
            deferred=counts["defer"],
            deleted=counts["delete"],
            routed=counts["route"],
            promoted=counts["promote_to_crt"],
            completed_at=review.completed_at or utcnow(),
        )
