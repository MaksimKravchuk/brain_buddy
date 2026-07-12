"""Filesystem repository for Execution module records.

Layout (per ADR-0001):
  results/{owner_id}/{result_id}.json
"""

from __future__ import annotations

from pathlib import Path

from app.exceptions import NotFoundError
from app.utils.file_ops import ensure_directory, read_json, write_json

from .domain import EvidenceResult


class ExecutionRepository:
    """Persist and retrieve evidence/result records from the filesystem."""

    def __init__(self, data_root: Path) -> None:
        self._root = ensure_directory(data_root / "results")

    def _path(self, owner_id: str, result_id: str) -> Path:
        d = ensure_directory(self._root / owner_id)
        return d / f"{result_id}.json"

    def save(self, result: EvidenceResult) -> None:
        path = self._path(result.owner_id, result.id)
        write_json(path, result.model_dump(mode="json"))

    def load(self, owner_id: str, result_id: str) -> EvidenceResult:
        path = self._path(owner_id, result_id)
        if not path.exists():
            raise NotFoundError("EvidenceResult", result_id)
        return EvidenceResult.model_validate(read_json(path))

    def list_for_owner(self, owner_id: str) -> list[EvidenceResult]:
        d = self._root / owner_id
        if not d.exists():
            return []
        results: list[EvidenceResult] = []
        for path in sorted(d.glob("*.json")):
            results.append(EvidenceResult.model_validate(read_json(path)))
        return results

    def list_for_capture(
        self, owner_id: str, capture_id: str
    ) -> list[EvidenceResult]:
        """Return results linked to a specific originating capture."""
        all_results = self.list_for_owner(owner_id)
        return [
            r for r in all_results if capture_id in r.atomic_capture_ids
        ]
