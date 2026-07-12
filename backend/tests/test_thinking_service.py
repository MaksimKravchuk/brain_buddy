"""Tests for the Thinking/CRT module (ADR-0001).

Covers problem candidate creation, CRT promotion, source provenance,
and the existing TreeService wrapping.
"""

from __future__ import annotations

import pytest

from app.exceptions import NotFoundError, ValidationFailure
from app.modules.thinking import ThinkingRepository, ThinkingService
from app.repositories import IndexRepository, TreeRepository
from app.services.node_service import NodeService
from app.services.tree_service import TreeService

TEST_OWNER = "user_test_owner"


@pytest.fixture
def thinking_service(data_dir):
    tree_repo = TreeRepository(data_dir)
    index_repo = IndexRepository(data_dir)
    tree_service = TreeService(tree_repo, index_repo)
    node_service = NodeService(tree_repo, tree_service)
    thinking_repo = ThinkingRepository(data_dir)
    return ThinkingService(thinking_repo, tree_service, node_service)


class TestCandidateManagement:
    def test_create_candidate(self, thinking_service):
        candidate = thinking_service.create_candidate(
            owner_id=TEST_OWNER,
            title="Recurring deployment issue",
            context="Deploys fail on Fridays",
            source_capture_ids=["cap_1"],
        )
        assert candidate.title == "Recurring deployment issue"
        assert candidate.status == "open"
        assert candidate.signal == "manual"

    def test_get_candidate(self, thinking_service):
        candidate = thinking_service.create_candidate(
            owner_id=TEST_OWNER, title="A problem"
        )
        fetched = thinking_service.get_candidate(TEST_OWNER, candidate.id)
        assert fetched.id == candidate.id

    def test_list_candidates(self, thinking_service):
        thinking_service.create_candidate(
            owner_id=TEST_OWNER, title="Problem A"
        )
        thinking_service.create_candidate(
            owner_id=TEST_OWNER, title="Problem B"
        )
        candidates = thinking_service.list_candidates_for_owner(TEST_OWNER)
        assert len(candidates) == 2

    def test_dismiss_candidate(self, thinking_service):
        candidate = thinking_service.create_candidate(
            owner_id=TEST_OWNER, title="To dismiss"
        )
        dismissed = thinking_service.dismiss_candidate(TEST_OWNER, candidate.id)
        assert dismissed.status == "dismissed"

    def test_cross_owner_not_found(self, thinking_service):
        candidate = thinking_service.create_candidate(
            owner_id=TEST_OWNER, title="My problem"
        )
        with pytest.raises(NotFoundError):
            thinking_service.get_candidate("wrong_owner", candidate.id)


class TestCrtPromotion:
    def test_promotion_creates_tree_and_node(self, thinking_service):
        candidate = thinking_service.create_candidate(
            owner_id=TEST_OWNER,
            title="Complex problem",
            source_capture_ids=["cap_1", "cap_2"],
        )
        promotion = thinking_service.request_promotion(
            TEST_OWNER, candidate.id
        )

        assert promotion.status == "succeeded"
        assert promotion.tree_id is not None
        assert promotion.root_node_id is not None
        assert promotion.source_capture_ids == ["cap_1", "cap_2"]

    def test_promotion_marks_candidate_promoted(self, thinking_service):
        candidate = thinking_service.create_candidate(
            owner_id=TEST_OWNER, title="A problem"
        )
        thinking_service.request_promotion(TEST_OWNER, candidate.id)
        updated = thinking_service.get_candidate(TEST_OWNER, candidate.id)
        assert updated.status == "promoted"

    def test_promotion_is_idempotent(self, thinking_service):
        candidate = thinking_service.create_candidate(
            owner_id=TEST_OWNER, title="A problem"
        )
        promo1 = thinking_service.request_promotion(TEST_OWNER, candidate.id)
        promo2 = thinking_service.request_promotion(TEST_OWNER, candidate.id)
        assert promo1.id == promo2.id

    def test_promotion_preserves_source_provenance(self, thinking_service):
        source_ids = ["cap_1", "cap_2", "cap_3"]
        candidate = thinking_service.create_candidate(
            owner_id=TEST_OWNER,
            title="Problem with provenance",
            source_capture_ids=source_ids,
        )
        promotion = thinking_service.request_promotion(
            TEST_OWNER, candidate.id
        )
        assert promotion.source_capture_ids == source_ids

    def test_promotion_dismissed_candidate_reopens(self, thinking_service):
        candidate = thinking_service.create_candidate(
            owner_id=TEST_OWNER, title="Dismissed then promoted"
        )
        thinking_service.dismiss_candidate(TEST_OWNER, candidate.id)
        promotion = thinking_service.request_promotion(
            TEST_OWNER, candidate.id
        )
        assert promotion.status == "succeeded"
        updated = thinking_service.get_candidate(TEST_OWNER, candidate.id)
        assert updated.status == "promoted"

    def test_cannot_dismiss_promoted(self, thinking_service):
        candidate = thinking_service.create_candidate(
            owner_id=TEST_OWNER, title="Promoted"
        )
        thinking_service.request_promotion(TEST_OWNER, candidate.id)
        with pytest.raises(ValidationFailure, match="promoted"):
            thinking_service.dismiss_candidate(TEST_OWNER, candidate.id)
