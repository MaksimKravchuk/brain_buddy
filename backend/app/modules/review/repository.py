"""Filesystem repository for Review module records.

Layout (per ADR-0001):
  reviews/{owner_id}/{review_id}.json
"""

from __future__ import annotations

from pathlib import Path

from app.exceptions import NotFoundError
from app.utils.file_ops import ensure_directory, read_json, write_json

from .domain import WeeklyReview


class ReviewRepository:
    """Persist and retrieve Weekly Review records from the filesystem."""

    def __init__(self, data_root: Path) -> None:
        self._root = ensure_directory(data_root / "reviews")

    def _path(self, owner_id: str, review_id: str) -> Path:
        d = ensure_directory(self._root / owner_id)
        return d / f"{review_id}.json"

    def save(self, review: WeeklyReview) -> None:
        path = self._path(review.owner_id, review.id)
        write_json(path, review.model_dump(mode="json"))

    def load(self, owner_id: str, review_id: str) -> WeeklyReview:
        path = self._path(owner_id, review_id)
        if not path.exists():
            raise NotFoundError("WeeklyReview", review_id)
        return WeeklyReview.model_validate(read_json(path))

    def list_for_owner(self, owner_id: str) -> list[WeeklyReview]:
        d = self._root / owner_id
        if not d.exists():
            return []
        results: list[WeeklyReview] = []
        for path in sorted(d.glob("*.json")):
            results.append(WeeklyReview.model_validate(read_json(path)))
        return results
