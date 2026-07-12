"""Thinking service: problem candidate management and CRT promotion.

Creates ProblemCandidates and CrtPromotion records. Promotion is
user-confirmed per ADR-0001.
"""

from __future__ import annotations

import logging
import uuid

from app.exceptions import ValidationFailure
from app.modules.thinking.domain import (
    CrtPromotion,
    ProblemCandidate,
)
from app.modules.thinking.repository import PromotionRepository, ThinkingRepository
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


class ThinkingService:
    """Manages problem candidates and CRT promotions."""

    def __init__(
        self,
        candidate_repo: ThinkingRepository,
        promotion_repo: PromotionRepository,
    ) -> None:
        self._candidate_repo = candidate_repo
        self._promotion_repo = promotion_repo

    def create_candidate(
        self,
        *,
        owner_id: str,
        source_capture_ids: list[str],
        title: str,
        context: str,
        signal: str = "manual",
        signal_reasons: list[str] | None = None,
    ) -> ProblemCandidate:
        """Create a new problem candidate from capture sources."""
        now = utcnow()
        candidate = ProblemCandidate(
            id=f"cand_{uuid.uuid4().hex[:12]}",
            owner_id=owner_id,
            source_capture_ids=source_capture_ids,
            title=title,
            context=context,
            signal=signal,  # type: ignore[arg-type]
            signal_reasons=signal_reasons or [],
            status="open",
            created_at=now,
            updated_at=now,
        )
        self._candidate_repo.save_candidate(candidate)
        logger.info(
            "Created candidate %s for owner %s from %d captures",
            candidate.id,
            owner_id,
            len(source_capture_ids),
        )
        return candidate

    def request_promotion(
        self,
        *,
        owner_id: str,
        candidate_id: str,
        idempotency_key: str,
    ) -> CrtPromotion:
        """Request promotion of a candidate to a CRT tree.

        For the MVP, the promotion is simulated: it creates a tree ID and
        root node ID without actually creating a tree. In production this
        would call the CRT adapter.
        """
        candidate = self._candidate_repo.load_candidate(owner_id, candidate_id)

        if candidate.status not in ("open", "promotion_requested"):
            raise ValidationFailure(
                f"Cannot promote candidate in status '{candidate.status}'.",
                detail={"current_status": candidate.status},
            )

        # Update candidate status.
        candidate.status = "promotion_requested"
        candidate.revision += 1
        candidate.updated_at = utcnow()
        self._candidate_repo.save_candidate(candidate)

        # Create promotion record.
        promotion = CrtPromotion(
            id=f"promo_{uuid.uuid4().hex[:12]}",
            owner_id=owner_id,
            problem_candidate_id=candidate_id,
            status="pending",
            source_capture_ids=candidate.source_capture_ids,
            requested_at=utcnow(),
        )
        self._promotion_repo.save_promotion(promotion)

        # For MVP, simulate successful promotion immediately.
        # In production, this would go through a CRT adapter.
        promotion.status = "promoting"
        promotion.attempt_count = 1
        self._promotion_repo.save_promotion(promotion)

        # Simulate success: create tree/node IDs.
        promotion.tree_id = f"crt_{uuid.uuid4().hex[:8]}"
        promotion.root_node_id = f"node_{uuid.uuid4().hex[:12]}"
        promotion.status = "succeeded"
        promotion.completed_at = utcnow()
        self._promotion_repo.save_promotion(promotion)

        # Update candidate.
        candidate.status = "promoted"
        candidate.revision += 1
        candidate.updated_at = utcnow()
        self._candidate_repo.save_candidate(candidate)

        logger.info(
            "Promotion %s succeeded for candidate %s (tree=%s)",
            promotion.id,
            candidate_id,
            promotion.tree_id,
        )
        return promotion

    def dismiss_candidate(
        self, *, owner_id: str, candidate_id: str
    ) -> ProblemCandidate:
        """Dismiss a problem candidate."""
        candidate = self._candidate_repo.load_candidate(owner_id, candidate_id)

        if candidate.status not in ("open", "dismissed"):
            raise ValidationFailure(
                f"Cannot dismiss candidate in status '{candidate.status}'.",
                detail={"current_status": candidate.status},
            )

        candidate.status = "dismissed"
        candidate.revision += 1
        candidate.updated_at = utcnow()
        self._candidate_repo.save_candidate(candidate)
        return candidate

    # --- Queries ---

    def get_candidate(self, *, owner_id: str, candidate_id: str) -> ProblemCandidate:
        return self._candidate_repo.load_candidate(owner_id, candidate_id)

    def list_candidates(self, *, owner_id: str) -> list[ProblemCandidate]:
        return self._candidate_repo.list_candidates(owner_id)

    def get_promotion(self, *, owner_id: str, promotion_id: str) -> CrtPromotion:
        return self._promotion_repo.load_promotion(owner_id, promotion_id)


__all__ = ["ThinkingService"]
