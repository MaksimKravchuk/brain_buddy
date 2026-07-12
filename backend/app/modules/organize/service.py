"""Organize service: manages mutable CaptureItems and decisions.

Each AtomicCaptureSource gets a one-to-one CaptureItem. The service
handles edit, clarify, approve, defer, delete, and route actions,
recording an OrganizeDecision for each.
"""

from __future__ import annotations

import logging
import uuid

from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.modules.organize.domain import (
    AvoidanceReason,
    CaptureItem,
    ClarificationRecord,
    DecisionAction,
    OrganizeDecision,
    ReviewState,
    RouteRecord,
)
from app.modules.organize.repository import OrganizeRepository
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

# Allowed state transitions for review_state.
_ALLOWED_TRANSITIONS: dict[ReviewState, set[ReviewState]] = {
    "proposed": {"needs_clarification", "approved", "deferred", "deleted"},
    "needs_clarification": {"proposed", "approved", "deferred", "deleted"},
    "deferred": {"proposed", "approved", "deleted"},
    "approved": {"approved", "completed", "deleted"},
    "completed": set(),  # terminal
    "deleted": set(),  # terminal
}


class OrganizeService:
    """Manages capture item lifecycle and decisions."""

    def __init__(self, repo: OrganizeRepository) -> None:
        self._repo = repo

    # --- Item creation (called after splitting) ---

    def create_item_from_source(
        self,
        *,
        source_id: str,
        owner_id: str,
        capture_session_id: str,
        source_text: str,
        needs_clarification: bool = False,
        clarification_question: str | None = None,
    ) -> CaptureItem:
        """Create a mutable CaptureItem for an AtomicCaptureSource.

        The item ID equals the source ID (one-to-one shared primary key).
        """
        if self._item_exists(owner_id, source_id):
            raise ConflictError("CaptureItem", source_id)

        now = utcnow()
        review_state: ReviewState = "proposed"
        clarification: ClarificationRecord | None = None

        if needs_clarification:
            review_state = "needs_clarification"
            clarification = ClarificationRecord(
                question=clarification_question or "Please review this capture.",
            )

        item = CaptureItem(
            id=source_id,
            owner_id=owner_id,
            source_capture_id=capture_session_id,
            current_text=source_text,
            review_state=review_state,
            clarification=clarification,
            created_at=now,
            updated_at=now,
        )
        self._repo.save_item(item)
        return item

    # --- Decision actions ---

    def edit_item(
        self,
        *,
        owner_id: str,
        item_id: str,
        new_text: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        expected_revision: int,
    ) -> tuple[CaptureItem, OrganizeDecision]:
        """Edit the text of a capture item."""
        item = self._load_and_check(owner_id, item_id, expected_revision)
        old_text = item.current_text
        from_state = item.review_state

        # Edit is allowed in proposed, needs_clarification, or approved.
        if from_state not in ("proposed", "needs_clarification", "approved"):
            raise ValidationFailure(
                f"Cannot edit item in state '{from_state}'.",
                detail={"from_state": from_state},
            )

        item.current_text = new_text
        item.revision += 1
        item.updated_at = utcnow()
        self._repo.save_item(item)

        decision = self._record_decision(
            owner_id=owner_id,
            item_id=item_id,
            actor_id=actor_id,
            action="edit",
            from_state=from_state,
            to_state=from_state,
            patch=f"{old_text} -> {new_text}",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return item, decision

    def clarify_item(
        self,
        *,
        owner_id: str,
        item_id: str,
        question: str,
        answer: str | None,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        expected_revision: int,
    ) -> tuple[CaptureItem, OrganizeDecision]:
        """Set or resolve a clarification on a capture item."""
        item = self._load_and_check(owner_id, item_id, expected_revision)
        from_state = item.review_state

        if from_state not in ("proposed", "needs_clarification"):
            raise ValidationFailure(
                f"Cannot clarify item in state '{from_state}'.",
                detail={"from_state": from_state},
            )

        to_state: ReviewState = "proposed" if answer else "needs_clarification"

        item.clarification = ClarificationRecord(
            question=question,
            answer=answer,
            resolved_at=utcnow() if answer else None,
        )
        item.review_state = to_state
        item.revision += 1
        item.updated_at = utcnow()
        self._repo.save_item(item)

        decision = self._record_decision(
            owner_id=owner_id,
            item_id=item_id,
            actor_id=actor_id,
            action="clarify",
            from_state=from_state,
            to_state=to_state,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return item, decision

    def approve_item(
        self,
        *,
        owner_id: str,
        item_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        expected_revision: int,
    ) -> tuple[CaptureItem, OrganizeDecision]:
        """Approve a capture item."""
        # Check idempotency first.
        existing = self._check_idempotency(owner_id, idempotency_key)
        if existing is not None:
            return self._repo.load_item(owner_id, item_id), existing

        item = self._load_and_check(owner_id, item_id, expected_revision)
        from_state = item.review_state

        if from_state not in ("proposed", "needs_clarification", "deferred"):
            raise ValidationFailure(
                f"Cannot approve item in state '{from_state}'.",
                detail={"from_state": from_state},
            )

        item.review_state = "approved"
        item.revision += 1
        item.updated_at = utcnow()
        self._repo.save_item(item)

        decision = self._record_decision(
            owner_id=owner_id,
            item_id=item_id,
            actor_id=actor_id,
            action="approve",
            from_state=from_state,
            to_state="approved",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return item, decision

    def defer_item(
        self,
        *,
        owner_id: str,
        item_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        expected_revision: int,
    ) -> tuple[CaptureItem, OrganizeDecision]:
        """Defer a capture item."""
        item = self._load_and_check(owner_id, item_id, expected_revision)
        from_state = item.review_state

        if from_state not in ("proposed", "needs_clarification"):
            raise ValidationFailure(
                f"Cannot defer item in state '{from_state}'.",
                detail={"from_state": from_state},
            )

        item.review_state = "deferred"
        item.revision += 1
        item.updated_at = utcnow()
        self._repo.save_item(item)

        decision = self._record_decision(
            owner_id=owner_id,
            item_id=item_id,
            actor_id=actor_id,
            action="defer",
            from_state=from_state,
            to_state="deferred",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return item, decision

    def delete_item(
        self,
        *,
        owner_id: str,
        item_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        expected_revision: int,
        reason: str | None = None,
        avoidance_reason: AvoidanceReason | None = None,
    ) -> tuple[CaptureItem, OrganizeDecision]:
        """Delete a capture item (soft-delete, terminal)."""
        item = self._load_and_check(owner_id, item_id, expected_revision)
        from_state = item.review_state

        if from_state in ("completed", "deleted"):
            raise ValidationFailure(
                f"Cannot delete item in terminal state '{from_state}'.",
                detail={"from_state": from_state},
            )

        item.review_state = "deleted"
        item.revision += 1
        item.updated_at = utcnow()
        self._repo.save_item(item)

        decision = self._record_decision(
            owner_id=owner_id,
            item_id=item_id,
            actor_id=actor_id,
            action="delete",
            from_state=from_state,
            to_state="deleted",
            reason=reason,
            avoidance_reason=avoidance_reason,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return item, decision

    def complete_item(
        self,
        *,
        owner_id: str,
        item_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        expected_revision: int,
    ) -> tuple[CaptureItem, OrganizeDecision]:
        """Mark an approved item as completed (terminal).

        Called after a successful route or recorded result.
        """
        item = self._load_and_check(owner_id, item_id, expected_revision)
        from_state = item.review_state

        if from_state != "approved":
            raise ValidationFailure(
                f"Cannot complete item in state '{from_state}'. Only 'approved' items can be completed.",
                detail={"from_state": from_state},
            )

        item.review_state = "completed"
        item.revision += 1
        item.updated_at = utcnow()
        self._repo.save_item(item)

        decision = self._record_decision(
            owner_id=owner_id,
            item_id=item_id,
            actor_id=actor_id,
            action="complete",
            from_state=from_state,
            to_state="completed",
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        return item, decision

    # --- Route creation ---

    def create_route(
        self,
        *,
        owner_id: str,
        item_id: str,
        destination: str,
        idempotency_key: str,
    ) -> RouteRecord:
        """Create a pending RouteRecord for a capture item.

        The item must be approved before routing.
        """
        item = self._repo.load_item(owner_id, item_id)

        if item.review_state != "approved":
            raise ValidationFailure(
                f"Cannot route item in state '{item.review_state}'. Item must be approved first.",
                detail={"current_state": item.review_state},
            )

        # Check for existing successful route (MVP: only one successful route per capture).
        if item.route_id:
            existing_route = self._repo.load_route(owner_id, item.route_id)
            if existing_route.status == "succeeded":
                raise ConflictError("RouteRecord", item_id)

        route = RouteRecord(
            id=f"route_{uuid.uuid4().hex[:12]}",
            owner_id=owner_id,
            atomic_capture_id=item_id,
            destination=destination,  # type: ignore[arg-type]
            status="pending",
            requested_at=utcnow(),
        )
        self._repo.save_route(route)

        # Link route to item.
        item.route_id = route.id
        item.destination_intent = destination  # type: ignore[assignment]
        item.revision += 1
        item.updated_at = utcnow()
        self._repo.save_item(item)

        return route

    def update_route(self, route: RouteRecord) -> RouteRecord:
        """Update and persist a route record."""
        self._repo.save_route(route)
        return route

    # --- Queries ---

    def get_item(self, *, owner_id: str, item_id: str) -> CaptureItem:
        return self._repo.load_item(owner_id, item_id)

    def list_items(self, *, owner_id: str) -> list[CaptureItem]:
        return self._repo.list_items(owner_id, exclude_terminal=True)

    def get_route(self, *, owner_id: str, route_id: str) -> RouteRecord:
        return self._repo.load_route(owner_id, route_id)

    def list_decisions(self, *, owner_id: str, item_id: str) -> list[OrganizeDecision]:
        return self._repo.list_decisions_for_item(owner_id, item_id)

    # --- Internal helpers ---

    def _check_idempotency(
        self, owner_id: str, idempotency_key: str
    ) -> OrganizeDecision | None:
        """Check if a decision with this idempotency key already exists."""
        return self._repo.find_decision_by_idempotency_key(owner_id, idempotency_key)

    def _load_and_check(
        self, owner_id: str, item_id: str, expected_revision: int
    ) -> CaptureItem:
        """Load an item and check optimistic concurrency."""
        item = self._repo.load_item(owner_id, item_id)
        if item.revision != expected_revision:
            raise ConflictError("CaptureItem", item_id)
        return item

    def _item_exists(self, owner_id: str, item_id: str) -> bool:
        try:
            self._repo.load_item(owner_id, item_id)
            return True
        except NotFoundError:
            return False

    def _record_decision(
        self,
        *,
        owner_id: str,
        item_id: str,
        actor_id: str,
        action: DecisionAction,
        from_state: ReviewState,
        to_state: ReviewState,
        correlation_id: str,
        idempotency_key: str,
        reason: str | None = None,
        avoidance_reason: AvoidanceReason | None = None,
        patch: str | None = None,
    ) -> OrganizeDecision:
        # Check idempotency: if a decision with this key exists, return it.
        existing = self._repo.find_decision_by_idempotency_key(owner_id, idempotency_key)
        if existing is not None:
            return existing

        decision = OrganizeDecision(
            id=f"dec_{uuid.uuid4().hex[:12]}",
            owner_id=owner_id,
            atomic_capture_id=item_id,
            actor_id=actor_id,
            action=action,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            avoidance_reason=avoidance_reason,
            patch=patch,
            created_at=utcnow(),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )
        self._repo.save_decision(decision)
        return decision


__all__ = ["OrganizeService"]
