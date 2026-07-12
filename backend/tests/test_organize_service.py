"""Tests for the organize service: item lifecycle, decisions, routing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.exceptions import ConflictError, ValidationFailure
from app.modules.organize.domain import (
    CaptureItem,
)
from app.modules.organize.repository import OrganizeRepository
from app.modules.organize.service import OrganizeService

OWNER = "user_a"
OWNER_B = "user_b"
SESSION_ID = "sess_test"
ACTOR = "user_a"
CORR = "corr_test"


@pytest.fixture
def repo(tmp_path: Path) -> OrganizeRepository:
    return OrganizeRepository(tmp_path / "organize")


@pytest.fixture
def service(repo: OrganizeRepository) -> OrganizeService:
    return OrganizeService(repo)


def _make_item(
    service: OrganizeService,
    *,
    item_id: str = "cap_1",
    owner_id: str = OWNER,
    text: str = "Original text",
    needs_clarification: bool = False,
) -> CaptureItem:
    """Create a capture item for testing."""
    return service.create_item_from_source(
        source_id=item_id,
        owner_id=owner_id,
        capture_session_id=SESSION_ID,
        source_text=text,
        needs_clarification=needs_clarification,
    )


class TestItemCreation:
    def test_create_proposed_item(self, service: OrganizeService) -> None:
        item = _make_item(service)
        assert item.review_state == "proposed"
        assert item.current_text == "Original text"
        assert item.destination_intent == "none"
        assert item.revision == 1

    def test_create_needs_clarification_item(self, service: OrganizeService) -> None:
        item = _make_item(service, needs_clarification=True)
        assert item.review_state == "needs_clarification"
        assert item.clarification is not None
        assert item.clarification.question is not None

    def test_duplicate_item_raises_conflict(self, service: OrganizeService) -> None:
        _make_item(service, item_id="cap_dup")
        with pytest.raises(ConflictError):
            _make_item(service, item_id="cap_dup")


class TestDecisionActions:
    def test_approve_item(self, service: OrganizeService) -> None:
        item = _make_item(service)
        approved, decision = service.approve_item(
            owner_id=OWNER,
            item_id=item.id,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_approve_1",
            expected_revision=1,
        )
        assert approved.review_state == "approved"
        assert approved.revision == 2
        assert decision.action == "approve"
        assert decision.from_state == "proposed"
        assert decision.to_state == "approved"

    def test_edit_item(self, service: OrganizeService) -> None:
        item = _make_item(service)
        edited, decision = service.edit_item(
            owner_id=OWNER,
            item_id=item.id,
            new_text="Edited text",
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_edit_1",
            expected_revision=1,
        )
        assert edited.current_text == "Edited text"
        assert edited.revision == 2
        assert decision.action == "edit"

    def test_defer_item(self, service: OrganizeService) -> None:
        item = _make_item(service)
        deferred, decision = service.defer_item(
            owner_id=OWNER,
            item_id=item.id,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_defer_1",
            expected_revision=1,
        )
        assert deferred.review_state == "deferred"
        assert decision.action == "defer"

    def test_delete_item(self, service: OrganizeService) -> None:
        item = _make_item(service)
        deleted, decision = service.delete_item(
            owner_id=OWNER,
            item_id=item.id,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_delete_1",
            expected_revision=1,
            reason="Not needed",
            avoidance_reason="duplicate",
        )
        assert deleted.review_state == "deleted"
        assert decision.action == "delete"
        assert decision.avoidance_reason == "duplicate"

    def test_clarify_item_resolves(self, service: OrganizeService) -> None:
        item = _make_item(service, needs_clarification=True)
        assert item.review_state == "needs_clarification"

        clarified, decision = service.clarify_item(
            owner_id=OWNER,
            item_id=item.id,
            question="Is this correct?",
            answer="Yes",
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_clarify_1",
            expected_revision=1,
        )
        assert clarified.review_state == "proposed"
        assert clarified.clarification.answer == "Yes"
        assert clarified.clarification.resolved_at is not None

    def test_clarify_item_unresolved(self, service: OrganizeService) -> None:
        item = _make_item(service)
        clarified, _ = service.clarify_item(
            owner_id=OWNER,
            item_id=item.id,
            question="What did you mean?",
            answer=None,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_clarify_2",
            expected_revision=1,
        )
        assert clarified.review_state == "needs_clarification"

    def test_complete_approved_item(self, service: OrganizeService) -> None:
        item = _make_item(service)
        service.approve_item(
            owner_id=OWNER,
            item_id=item.id,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_approve_2",
            expected_revision=1,
        )
        completed, decision = service.complete_item(
            owner_id=OWNER,
            item_id=item.id,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_complete_1",
            expected_revision=2,
        )
        assert completed.review_state == "completed"
        assert decision.action == "complete"


class TestStateTransitionGuards:
    def test_cannot_approve_deleted_item(self, service: OrganizeService) -> None:
        item = _make_item(service)
        service.delete_item(
            owner_id=OWNER,
            item_id=item.id,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_delete_2",
            expected_revision=1,
        )
        with pytest.raises(ValidationFailure, match="Cannot approve"):
            service.approve_item(
                owner_id=OWNER,
                item_id=item.id,
                actor_id=ACTOR,
                correlation_id=CORR,
                idempotency_key="key_approve_3",
                expected_revision=2,
            )

    def test_cannot_delete_completed_item(self, service: OrganizeService) -> None:
        item = _make_item(service)
        service.approve_item(
            owner_id=OWNER,
            item_id=item.id,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_approve_4",
            expected_revision=1,
        )
        service.complete_item(
            owner_id=OWNER,
            item_id=item.id,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_complete_2",
            expected_revision=2,
        )
        with pytest.raises(ValidationFailure, match="Cannot delete"):
            service.delete_item(
                owner_id=OWNER,
                item_id=item.id,
                actor_id=ACTOR,
                correlation_id=CORR,
                idempotency_key="key_delete_3",
                expected_revision=3,
            )

    def test_cannot_complete_unapproved_item(self, service: OrganizeService) -> None:
        item = _make_item(service)
        with pytest.raises(ValidationFailure, match="Cannot complete"):
            service.complete_item(
                owner_id=OWNER,
                item_id=item.id,
                actor_id=ACTOR,
                correlation_id=CORR,
                idempotency_key="key_complete_3",
                expected_revision=1,
            )

    def test_stale_revision_raises_conflict(self, service: OrganizeService) -> None:
        item = _make_item(service)
        with pytest.raises(ConflictError):
            service.approve_item(
                owner_id=OWNER,
                item_id=item.id,
                actor_id=ACTOR,
                correlation_id=CORR,
                idempotency_key="key_approve_5",
                expected_revision=99,  # wrong revision
            )


class TestIdempotency:
    def test_duplicate_decision_key_returns_same(self, service: OrganizeService) -> None:
        item = _make_item(service)
        _, decision1 = service.approve_item(
            owner_id=OWNER,
            item_id=item.id,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="idem_key_1",
            expected_revision=1,
        )
        # Re-submit with same key but different expected revision.
        _, decision2 = service.approve_item(
            owner_id=OWNER,
            item_id=item.id,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="idem_key_1",
            expected_revision=2,
        )
        assert decision1.id == decision2.id


class TestRouting:
    def test_route_requires_approved_item(self, service: OrganizeService) -> None:
        item = _make_item(service)
        with pytest.raises(ValidationFailure, match="Cannot route"):
            service.create_route(
                owner_id=OWNER,
                item_id=item.id,
                destination="external_task_tracker",
                idempotency_key="route_key_1",
            )

    def test_create_route_links_to_item(self, service: OrganizeService) -> None:
        item = _make_item(service)
        service.approve_item(
            owner_id=OWNER,
            item_id=item.id,
            actor_id=ACTOR,
            correlation_id=CORR,
            idempotency_key="key_approve_route",
            expected_revision=1,
        )

        route = service.create_route(
            owner_id=OWNER,
            item_id=item.id,
            destination="external_task_tracker",
            idempotency_key="route_key_2",
        )
        assert route.status == "pending"
        assert route.destination == "external_task_tracker"

        # Item should be linked.
        updated_item = service.get_item(owner_id=OWNER, item_id=item.id)
        assert updated_item.route_id == route.id
        assert updated_item.destination_intent == "external_task_tracker"


class TestOwnerIsolation:
    def test_cross_owner_get_returns_not_found(self, service: OrganizeService) -> None:
        _make_item(service, owner_id=OWNER)
        from app.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            service.get_item(owner_id=OWNER_B, item_id="cap_1")

    def test_cross_owner_list_returns_empty(self, service: OrganizeService) -> None:
        _make_item(service, owner_id=OWNER)
        items = service.list_items(owner_id=OWNER_B)
        assert items == []
