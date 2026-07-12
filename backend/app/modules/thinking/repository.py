"""Filesystem repository for Thinking module records.

Layout (per ADR-0001):
  candidates/{owner_id}/{candidate_id}.json
  promotions/{owner_id}/{promotion_id}.json
"""

from __future__ import annotations

from pathlib import Path

from app.exceptions import NotFoundError
from app.utils.file_ops import ensure_directory, read_json, write_json

from .domain import CrtPromotion, ProblemCandidate


class ThinkingRepository:
    """Persist and retrieve problem candidates and promotions."""

    def __init__(self, data_root: Path) -> None:
        self._candidates_root = ensure_directory(data_root / "candidates")
        self._promotions_root = ensure_directory(data_root / "promotions")

    # -- Candidates --

    def _candidate_path(self, owner_id: str, candidate_id: str) -> Path:
        d = ensure_directory(self._candidates_root / owner_id)
        return d / f"{candidate_id}.json"

    def save_candidate(self, candidate: ProblemCandidate) -> None:
        path = self._candidate_path(candidate.owner_id, candidate.id)
        write_json(path, candidate.model_dump(mode="json"))

    def load_candidate(
        self, owner_id: str, candidate_id: str
    ) -> ProblemCandidate:
        path = self._candidate_path(owner_id, candidate_id)
        if not path.exists():
            raise NotFoundError("ProblemCandidate", candidate_id)
        return ProblemCandidate.model_validate(read_json(path))

    def list_candidates_for_owner(self, owner_id: str) -> list[ProblemCandidate]:
        d = self._candidates_root / owner_id
        if not d.exists():
            return []
        results: list[ProblemCandidate] = []
        for path in sorted(d.glob("*.json")):
            results.append(ProblemCandidate.model_validate(read_json(path)))
        return results

    # -- Promotions --

    def _promotion_path(self, owner_id: str, promotion_id: str) -> Path:
        d = ensure_directory(self._promotions_root / owner_id)
        return d / f"{promotion_id}.json"

    def save_promotion(self, promotion: CrtPromotion) -> None:
        path = self._promotion_path(promotion.owner_id, promotion.id)
        write_json(path, promotion.model_dump(mode="json"))

    def load_promotion(
        self, owner_id: str, promotion_id: str
    ) -> CrtPromotion:
        path = self._promotion_path(owner_id, promotion_id)
        if not path.exists():
            raise NotFoundError("CrtPromotion", promotion_id)
        return CrtPromotion.model_validate(read_json(path))
