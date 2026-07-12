"""Execution service: evidence/result recording.

Per ADR-0001:
- EvidenceResult is append-only except `recorded -> superseded`.
- At least one originating `atomic_capture_id` is required.
- Every linked route, review, tree, and node must have the same owner.
- The application service performs cross-module checks through each
  module's owner-scoped query port.
"""

from __future__ import annotations

from app.exceptions import ValidationFailure
from app.utils.identifiers import generate_id

from .domain import EvidenceResult, EvidenceResultKind, EvidenceResultSource
from .repository import ExecutionRepository


class ExecutionService:
    """Manage evidence/result records."""

    def __init__(self, repo: ExecutionRepository) -> None:
        self._repo = repo

    def record_result(
        self,
        *,
        owner_id: str,
        source: EvidenceResultSource,
        kind: EvidenceResultKind,
        title: str,
        atomic_capture_ids: list[str],
        summary: str | None = None,
        uri: str | None = None,
        route_id: str | None = None,
        weekly_review_id: str | None = None,
        tree_id: str | None = None,
        node_ids: list[str] | None = None,
        actor_id: str | None = None,
    ) -> EvidenceResult:
        """Manually record a linked evidence/result.

        Per ADR-0001: at least one originating atomic_capture_id is
        required.
        """
        if not atomic_capture_ids:
            raise ValidationFailure(
                "At least one originating atomic_capture_id is required.",
                detail={"reason": "missing_capture_ids"},
            )

        result = EvidenceResult(
            id=generate_id("res"),
            owner_id=owner_id,
            source=source,
            kind=kind,
            title=title,
            summary=summary,
            uri=uri,
            atomic_capture_ids=list(atomic_capture_ids),
            route_id=route_id,
            weekly_review_id=weekly_review_id,
            tree_id=tree_id,
            node_ids=node_ids or [],
            actor_id=actor_id or owner_id,
        )
        self._repo.save(result)
        return result

    def get_result(
        self, owner_id: str, result_id: str
    ) -> EvidenceResult:
        return self._repo.load(owner_id, result_id)

    def list_results_for_owner(self, owner_id: str) -> list[EvidenceResult]:
        return self._repo.list_for_owner(owner_id)

    def list_results_for_capture(
        self, owner_id: str, capture_id: str
    ) -> list[EvidenceResult]:
        return self._repo.list_for_capture(owner_id, capture_id)
