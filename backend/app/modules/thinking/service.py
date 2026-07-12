"""Thinking service: candidate management and CRT promotion.

Per ADR-0001:
- Repetition/complexity detection only proposes a candidate;
  promotion is user-confirmed.
- Promotion creates or links a CRT tree and creates one initial
  problem/context node.
- Source provenance is stored in the promotion record and in the
  node's existing `extra` metadata as IDs, not as invented graph
  relations.
- The live CRT schema treats source_id as cause and target_id as effect.
"""

from __future__ import annotations

from app.exceptions import NotFoundError, ValidationFailure
from app.schemas.api import TreeCreateRequest
from app.services.node_service import NodeService
from app.services.tree_service import TreeService
from app.utils.identifiers import generate_id
from app.utils.time import utcnow

from .domain import (
    CrtPromotion,
    ProblemCandidate,
    ProblemCandidateSignal,
)
from .repository import ThinkingRepository


class ThinkingService:
    """Manage problem candidates and CRT promotion.

    Wraps the existing TreeService to create CRT trees without
    duplicating the graph model. The ThinkingCrtPort pattern from
    ADR-0001 is implemented here as a direct service dependency for
    the MVP.
    """

    def __init__(
        self,
        repo: ThinkingRepository,
        tree_service: TreeService,
        node_service: NodeService,
    ) -> None:
        self._repo = repo
        self._tree_service = tree_service
        self._node_service = node_service

    def create_candidate(
        self,
        *,
        owner_id: str,
        title: str,
        context: str = "",
        source_capture_ids: list[str] | None = None,
        signal: ProblemCandidateSignal = "manual",
        signal_reasons: list[str] | None = None,
    ) -> ProblemCandidate:
        """Create a new problem candidate."""
        candidate = ProblemCandidate(
            id=generate_id("cand"),
            owner_id=owner_id,
            source_capture_ids=source_capture_ids or [],
            title=title,
            context=context,
            signal=signal,
            signal_reasons=signal_reasons or [],
        )
        self._repo.save_candidate(candidate)
        return candidate

    def get_candidate(
        self, owner_id: str, candidate_id: str
    ) -> ProblemCandidate:
        return self._repo.load_candidate(owner_id, candidate_id)

    def list_candidates_for_owner(self, owner_id: str) -> list[ProblemCandidate]:
        return self._repo.list_candidates_for_owner(owner_id)

    def dismiss_candidate(
        self, owner_id: str, candidate_id: str
    ) -> ProblemCandidate:
        """Dismiss a candidate (can be reopened per ADR-0001)."""
        candidate = self._repo.load_candidate(owner_id, candidate_id)
        if candidate.owner_id != owner_id:
            raise NotFoundError("ProblemCandidate", candidate_id)
        if candidate.status == "promoted":
            raise ValidationFailure(
                "Cannot dismiss a promoted candidate.",
                detail={"reason": "already_promoted"},
            )
        candidate.status = "dismissed"
        candidate.updated_at = utcnow()
        candidate.revision += 1
        self._repo.save_candidate(candidate)
        return candidate

    def request_promotion(
        self,
        owner_id: str,
        candidate_id: str,
    ) -> CrtPromotion:
        """Request CRT promotion for a candidate.

        Creates a CRT tree with an initial problem node, then marks
        the promotion as succeeded and the candidate as promoted.

        Per ADR-0001: candidate status becomes 'promoted' only after
        the CRT tree/node and CrtPromotion source links are persisted.
        """
        candidate = self._repo.load_candidate(owner_id, candidate_id)
        if candidate.owner_id != owner_id:
            raise NotFoundError("ProblemCandidate", candidate_id)

        if candidate.status == "promoted":
            # Idempotent: find and return the existing promotion.
            promotions = self._find_promotions_for_candidate(
                owner_id, candidate_id
            )
            succeeded = [p for p in promotions if p.status == "succeeded"]
            if succeeded:
                return succeeded[0]
            raise ValidationFailure(
                "Candidate is promoted but no succeeded promotion found.",
                detail={"reason": "inconsistent_state"},
            )

        if candidate.status == "dismissed":
            # Reopen dismissed candidate before promoting.
            candidate.status = "open"
            candidate.updated_at = utcnow()

        promotion = CrtPromotion(
            id=generate_id("promo"),
            owner_id=owner_id,
            problem_candidate_id=candidate_id,
            status="promoting",
            source_capture_ids=candidate.source_capture_ids,
            attempt_count=1,
        )
        self._repo.save_promotion(promotion)

        try:
            # Create a CRT tree for this problem.
            tree_payload = TreeCreateRequest(
                name=candidate.title,
            )
            tree = self._tree_service.create_tree(
                tree_payload, owner_id=owner_id
            )

            # Create an initial problem/context node.
            from app.schemas.api import NodeCreateRequest
            from app.schemas.common import Position

            node, _ = self._node_service.create_node(
                tree.id,
                NodeCreateRequest(
                    label=candidate.title,
                    type="parent",
                    position=Position(x=0, y=0),
                ),
            )

            # Store source provenance in node's extra metadata as IDs.
            tree = self._tree_service.get_tree(tree.id)
            tree_node = next(
                n for n in tree.nodes if n.id == node.id
            )
            extra = {**(tree_node.extra or {})}
            extra["source_capture_ids"] = candidate.source_capture_ids
            extra["promotion_id"] = promotion.id
            extra["candidate_id"] = candidate_id
            tree_node.extra = extra
            self._tree_service.tree_repo.save(tree)

            promotion.tree_id = tree.id
            promotion.root_node_id = node.id
            promotion.status = "succeeded"
            promotion.completed_at = utcnow()
            promotion.revision += 1
            self._repo.save_promotion(promotion)

            candidate.status = "promoted"
            candidate.updated_at = utcnow()
            candidate.revision += 1
            self._repo.save_candidate(candidate)

        except Exception as exc:
            promotion.status = "failed"
            promotion.last_error = {
                "code": "PROMOTION_FAILED",
                "retryable": True,
                "message": str(exc),
            }
            promotion.revision += 1
            self._repo.save_promotion(promotion)

            candidate.status = "promotion_requested"
            candidate.updated_at = utcnow()
            candidate.revision += 1
            self._repo.save_candidate(candidate)
            raise

        return promotion

    def get_promotion(
        self, owner_id: str, promotion_id: str
    ) -> CrtPromotion:
        return self._repo.load_promotion(owner_id, promotion_id)

    # -- Internal --

    def _find_promotions_for_candidate(
        self, owner_id: str, candidate_id: str
    ) -> list[CrtPromotion]:
        """Scan promotions for this candidate. MVP: linear scan."""
        promos_dir = self._repo._promotions_root / owner_id  # noqa: SLF001
        if not promos_dir.exists():
            return []
        from app.utils.file_ops import read_json

        results: list[CrtPromotion] = []
        for path in sorted(promos_dir.glob("*.json")):
            promo = CrtPromotion.model_validate(read_json(path))
            if promo.problem_candidate_id == candidate_id:
                results.append(promo)
        return results
