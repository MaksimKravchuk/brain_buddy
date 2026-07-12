"""Filesystem repository for Thinking/CRT records.

Layout per ADR-0001:
    candidates/{owner_id}/{candidate_id}.json
    promotions/{owner_id}/{promotion_id}.json
"""

from __future__ import annotations

from pathlib import Path

from app.exceptions import NotFoundError
from app.modules.thinking.domain import CrtPromotion, ProblemCandidate
from app.repositories.base import BaseRepository
from app.utils.file_ops import ensure_directory


class ThinkingRepository(BaseRepository):
    """Persist and retrieve problem candidates and promotions."""

    def _owner_dir(self, owner_id: str) -> Path:
        return ensure_directory(self.resolve(owner_id))

    def save_candidate(self, candidate: ProblemCandidate) -> None:
        path = self._owner_dir(candidate.owner_id) / f"{candidate.id}.json"
        self.dump_model(path, candidate)

    def load_candidate(self, owner_id: str, candidate_id: str) -> ProblemCandidate:
        path = self._owner_dir(owner_id) / f"{candidate_id}.json"
        if not path.exists():
            raise NotFoundError("ProblemCandidate", candidate_id)
        return self.load_model(path, ProblemCandidate)

    def list_candidates(self, owner_id: str) -> list[ProblemCandidate]:
        owner_dir = self._owner_dir(owner_id)
        candidates: list[ProblemCandidate] = []
        for child in owner_dir.iterdir():
            if child.is_file() and child.suffix == ".json":
                try:
                    candidates.append(self.load_model(child, ProblemCandidate))
                except Exception:  # noqa: BLE001
                    continue
        candidates.sort(key=lambda c: c.created_at, reverse=True)
        return candidates


class PromotionRepository(BaseRepository):
    """Persist and retrieve CRT promotion records."""

    def _owner_dir(self, owner_id: str) -> Path:
        return ensure_directory(self.resolve(owner_id))

    def save_promotion(self, promotion: CrtPromotion) -> None:
        path = self._owner_dir(promotion.owner_id) / f"{promotion.id}.json"
        self.dump_model(path, promotion)

    def load_promotion(self, owner_id: str, promotion_id: str) -> CrtPromotion:
        path = self._owner_dir(owner_id) / f"{promotion_id}.json"
        if not path.exists():
            raise NotFoundError("CrtPromotion", promotion_id)
        return self.load_model(path, CrtPromotion)


__all__ = ["PromotionRepository", "ThinkingRepository"]
