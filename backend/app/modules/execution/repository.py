"""Filesystem repository for Execution records.

Layout per ADR-0001:
    dispatches/{owner_id}/{route_id}/{dispatch_id}.json
    results/{owner_id}/{result_id}.json
"""

from __future__ import annotations

from pathlib import Path

from app.exceptions import NotFoundError
from app.modules.execution.domain import DispatchAttempt, EvidenceResult
from app.repositories.base import BaseRepository
from app.utils.file_ops import ensure_directory


class ExecutionRepository(BaseRepository):
    """Persist and retrieve dispatch attempts and evidence/results."""

    def _owner_dir(self, owner_id: str) -> Path:
        return ensure_directory(self.resolve(owner_id))

    def _dispatch_dir(self, owner_id: str, route_id: str) -> Path:
        return ensure_directory(self._owner_dir(owner_id) / route_id)

    # --- DispatchAttempt ---

    def save_dispatch(self, dispatch: DispatchAttempt) -> None:
        path = self._dispatch_dir(dispatch.owner_id, dispatch.route_id) / f"{dispatch.id}.json"
        self.dump_model(path, dispatch)

    def load_dispatch(
        self, owner_id: str, route_id: str, dispatch_id: str
    ) -> DispatchAttempt:
        path = self._dispatch_dir(owner_id, route_id) / f"{dispatch_id}.json"
        if not path.exists():
            raise NotFoundError("DispatchAttempt", dispatch_id)
        return self.load_model(path, DispatchAttempt)

    def list_dispatches_for_route(
        self, owner_id: str, route_id: str
    ) -> list[DispatchAttempt]:
        dispatch_dir = self._dispatch_dir(owner_id, route_id)
        dispatches: list[DispatchAttempt] = []
        for child in dispatch_dir.iterdir():
            if child.is_file() and child.suffix == ".json":
                try:
                    dispatches.append(self.load_model(child, DispatchAttempt))
                except Exception:  # noqa: BLE001
                    continue
        dispatches.sort(key=lambda d: d.started_at)
        return dispatches

    # --- EvidenceResult ---

    def save_result(self, result: EvidenceResult) -> None:
        path = self._owner_dir(result.owner_id) / "results" / f"{result.id}.json"
        ensure_directory(path.parent)
        self.dump_model(path, result)

    def load_result(self, owner_id: str, result_id: str) -> EvidenceResult:
        path = self._owner_dir(owner_id) / "results" / f"{result_id}.json"
        if not path.exists():
            raise NotFoundError("EvidenceResult", result_id)
        return self.load_model(path, EvidenceResult)

    def list_results_for_capture(
        self, owner_id: str, capture_id: str
    ) -> list[EvidenceResult]:
        """List all evidence/results linked to a capture."""
        results_dir = self._owner_dir(owner_id) / "results"
        if not results_dir.exists():
            return []
        results: list[EvidenceResult] = []
        for child in results_dir.iterdir():
            if child.is_file() and child.suffix == ".json":
                try:
                    result = self.load_model(child, EvidenceResult)
                except Exception:  # noqa: BLE001
                    continue
                if capture_id in result.atomic_capture_ids:
                    results.append(result)
        results.sort(key=lambda r: r.recorded_at, reverse=True)
        return results


__all__ = ["ExecutionRepository"]
