"""Execution service: task-tracker dispatch and evidence/result recording.

The MVP uses a mock task-tracker adapter that succeeds immediately.
Real adapters (e.g. Todoist, RTM) would implement TaskTrackerPort.
"""

from __future__ import annotations

import logging
import uuid

from app.exceptions import ValidationFailure
from app.modules.execution.domain import (
    DispatchAttempt,
    EvidenceResult,
)
from app.modules.execution.repository import ExecutionRepository
from app.modules.organize.domain import RouteRecord
from app.modules.organize.repository import OrganizeRepository
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


class MockTaskTrackerAdapter:
    """Mock task-tracker adapter for testing and MVP.

    Returns a successful dispatch with a fake external reference.
    """

    ADAPTER_NAME = "mock_task_tracker"

    def dispatch(
        self,
        route: RouteRecord,
        capture_text: str,
        *,
        idempotency_key: str,
    ) -> DispatchAttempt:
        """Dispatch a task to the mock tracker."""
        attempt = DispatchAttempt(
            id=f"disp_{uuid.uuid4().hex[:12]}",
            owner_id=route.owner_id,
            route_id=route.id,
            adapter=self.ADAPTER_NAME,
            status="started",
            started_at=utcnow(),
        )

        # Simulate success.
        attempt.status = "succeeded"
        attempt.external_ref = f"task_{uuid.uuid4().hex[:8]}"
        attempt.completed_at = utcnow()
        return attempt


class ExecutionService:
    """Manages dispatch attempts and evidence/result recording."""

    def __init__(
        self,
        repo: ExecutionRepository,
        organize_repo: OrganizeRepository,
        *,
        adapter: MockTaskTrackerAdapter | None = None,
    ) -> None:
        self._repo = repo
        self._organize_repo = organize_repo
        self._adapter = adapter or MockTaskTrackerAdapter()

    def dispatch_route(
        self,
        *,
        owner_id: str,
        route: RouteRecord,
        capture_text: str,
        idempotency_key: str,
    ) -> tuple[DispatchAttempt, RouteRecord]:
        """Dispatch a route to the external task tracker.

        Returns (dispatch_attempt, updated_route).
        """
        if route.status not in ("pending", "failed"):
            raise ValidationFailure(
                f"Cannot dispatch route in status '{route.status}'.",
                detail={"current_status": route.status},
            )

        # Transition to dispatching.
        route.status = "dispatching"
        route.attempt_count += 1
        self._organize_repo.save_route(route)

        from app.modules.organize.domain import RouteErrorRecord

        # Call adapter.
        try:
            attempt = self._adapter.dispatch(
                route, capture_text, idempotency_key=idempotency_key
            )
        except Exception as exc:  # noqa: BLE001
            attempt = DispatchAttempt(
                id=f"disp_{uuid.uuid4().hex[:12]}",
                owner_id=owner_id,
                route_id=route.id,
                adapter=self._adapter.ADAPTER_NAME,
                status="failed",
                error_code="ADAPTER_ERROR",
                retryable=True,
                started_at=utcnow(),
                completed_at=utcnow(),
            )
            self._repo.save_dispatch(attempt)

            route.status = "failed"
            route.last_error = RouteErrorRecord(
                code="ADAPTER_ERROR",
                retryable=True,
            )
            self._organize_repo.save_route(route)
            logger.error("Dispatch failed for route %s: %s", route.id, exc)
            return attempt, route

        self._repo.save_dispatch(attempt)

        # Update route based on dispatch result.
        if attempt.status == "succeeded":
            route.status = "succeeded"
            route.external_ref = attempt.external_ref
            route.completed_at = utcnow()
        else:
            route.status = "failed"
            route.last_error = RouteErrorRecord(
                code=attempt.error_code or "DISPATCH_FAILED",
                retryable=attempt.retryable or False,
            )

        self._organize_repo.save_route(route)
        logger.info(
            "Route %s dispatch %s (external_ref=%s)",
            route.id,
            route.status,
            route.external_ref,
        )
        return attempt, route

    def record_result(
        self,
        *,
        owner_id: str,
        source: str,
        kind: str,
        title: str,
        atomic_capture_ids: list[str],
        actor_id: str,
        summary: str | None = None,
        uri: str | None = None,
        route_id: str | None = None,
        tree_id: str | None = None,
        node_ids: list[str] | None = None,
    ) -> EvidenceResult:
        """Manually record an evidence or result item."""
        if not atomic_capture_ids:
            raise ValidationFailure(
                "At least one atomic_capture_id is required.",
            )

        now = utcnow()
        result = EvidenceResult(
            id=f"res_{uuid.uuid4().hex[:12]}",
            owner_id=owner_id,
            source=source,  # type: ignore[arg-type]
            kind=kind,  # type: ignore[arg-type]
            status="recorded",
            title=title,
            summary=summary,
            uri=uri,
            atomic_capture_ids=atomic_capture_ids,
            route_id=route_id,
            tree_id=tree_id,
            node_ids=node_ids or [],
            observed_at=now,
            recorded_at=now,
            actor_id=actor_id,
        )
        self._repo.save_result(result)
        logger.info(
            "Recorded %s %s for captures %s",
            kind,
            result.id,
            atomic_capture_ids,
        )
        return result

    # --- Queries ---

    def list_results_for_capture(
        self, *, owner_id: str, capture_id: str
    ) -> list[EvidenceResult]:
        return self._repo.list_results_for_capture(owner_id, capture_id)


__all__ = ["ExecutionService", "MockTaskTrackerAdapter"]
