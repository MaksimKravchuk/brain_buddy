"""The guided weekly review: runs, queues, capacity and bulk release.

Spec 020, slice PR-11 fills this service; slice PR-15 only wires it so the
review flow router and the maintenance sweep have their seam. Built on the pure
rules in ``review_rules.py`` and composed over ``ReviewService``.
"""

from __future__ import annotations

from datetime import datetime

from .review_service import ReviewService


class ReviewFlowService:
    """Review runs and queues (empty until slice PR-11)."""

    def __init__(self, review: ReviewService) -> None:
        self.review = review

    def close_idle_sessions(self, owner_id: str, now: datetime) -> int:
        """Close sessions idle for 7 days (http §9); a no-op until PR-11."""

        del owner_id, now
        return 0


__all__ = ["ReviewFlowService"]
