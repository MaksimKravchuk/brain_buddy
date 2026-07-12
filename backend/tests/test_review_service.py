"""Tests for the Review module (ADR-0001).

Covers Weekly Review lifecycle: start/resume, outcome recording,
completion validation, idempotency, and summary counts.
"""

from __future__ import annotations

import pytest

from app.exceptions import NotFoundError, ValidationFailure
from app.modules.capture import CaptureRepository, CaptureService
from app.modules.review import ReviewRepository, ReviewService

TEST_OWNER = "user_test_owner"


@pytest.fixture
def services(data_dir):
    capture_repo = CaptureRepository(data_dir)
    capture_service = CaptureService(capture_repo)
    review_repo = ReviewRepository(data_dir)
    review_service = ReviewService(review_repo)
    return capture_service, review_service


class TestReviewLifecycle:
    def test_start_review_snapshots_eligible(self, services):
        capture_service, review_service = services
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Task one\nTask two"
        )
        review = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[item.id for item in items],
        )
        assert review.status == "open"
        assert len(review.item_ids) == 2

    def test_resume_open_review(self, services):
        capture_service, review_service = services
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Task one"
        )
        review1 = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[items[0].id],
        )
        review2 = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[items[0].id],
        )
        assert review1.id == review2.id

    def test_record_outcome(self, services):
        capture_service, review_service = services
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Task one"
        )
        review = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[items[0].id],
        )
        outcome = review_service.record_outcome(
            owner_id=TEST_OWNER,
            review_id=review.id,
            capture_id=items[0].id,
            action="keep",
        )
        assert outcome.action == "keep"
        assert outcome.atomic_capture_id == items[0].id

    def test_outcome_supersedes_previous(self, services):
        capture_service, review_service = services
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Task one"
        )
        review = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[items[0].id],
        )
        review_service.record_outcome(
            owner_id=TEST_OWNER,
            review_id=review.id,
            capture_id=items[0].id,
            action="keep",
        )
        review_service.record_outcome(
            owner_id=TEST_OWNER,
            review_id=review.id,
            capture_id=items[0].id,
            action="defer",
        )
        review = review_service.get_review(TEST_OWNER, review.id)
        assert len(review.outcomes) == 1
        assert review.outcomes[0].action == "defer"

    def test_outcome_on_non_snapshot_item_rejected(self, services):
        capture_service, review_service = services
        capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Task one"
        )
        review = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[],
        )
        with pytest.raises(ValidationFailure, match="not in this review"):
            review_service.record_outcome(
                owner_id=TEST_OWNER,
                review_id=review.id,
                capture_id="nonexistent",
                action="keep",
            )

    def test_outcome_on_closed_review_rejected(self, services):
        capture_service, review_service = services
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Task one"
        )
        review = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[items[0].id],
        )
        review_service.record_outcome(
            owner_id=TEST_OWNER,
            review_id=review.id,
            capture_id=items[0].id,
            action="defer",
        )
        review_service.complete_review(
            owner_id=TEST_OWNER, review_id=review.id
        )
        with pytest.raises(ValidationFailure, match="completed"):
            review_service.record_outcome(
                owner_id=TEST_OWNER,
                review_id=review.id,
                capture_id=items[0].id,
                action="keep",
            )


class TestReviewCompletion:
    def test_complete_requires_all_outcomes(self, services):
        capture_service, review_service = services
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Task one\nTask two"
        )
        review = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[items[0].id, items[1].id],
        )
        # Only one outcome recorded
        review_service.record_outcome(
            owner_id=TEST_OWNER,
            review_id=review.id,
            capture_id=items[0].id,
            action="keep",
        )
        with pytest.raises(ValidationFailure, match="uncovered"):
            review_service.complete_review(
                owner_id=TEST_OWNER, review_id=review.id
            )

    def test_complete_with_all_outcomes(self, services):
        capture_service, review_service = services
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Task one\nTask two"
        )
        review = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[items[0].id, items[1].id],
        )
        review_service.record_outcome(
            owner_id=TEST_OWNER,
            review_id=review.id,
            capture_id=items[0].id,
            action="keep",
        )
        review_service.record_outcome(
            owner_id=TEST_OWNER,
            review_id=review.id,
            capture_id=items[1].id,
            action="defer",
        )
        summary = review_service.complete_review(
            owner_id=TEST_OWNER, review_id=review.id
        )
        assert summary.total_items == 2
        assert summary.kept == 1
        assert summary.deferred == 1
        assert summary.deleted == 0

    def test_completion_is_idempotent(self, services):
        capture_service, review_service = services
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Task one"
        )
        review = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[items[0].id],
        )
        review_service.record_outcome(
            owner_id=TEST_OWNER,
            review_id=review.id,
            capture_id=items[0].id,
            action="defer",
        )
        summary1 = review_service.complete_review(
            owner_id=TEST_OWNER, review_id=review.id
        )
        summary2 = review_service.complete_review(
            owner_id=TEST_OWNER, review_id=review.id
        )
        assert summary1.review_id == summary2.review_id

    def test_summary_counts(self, services):
        capture_service, review_service = services
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER,
            text="Task one\nTask two\nTask three\nTask four",
        )
        review = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[i.id for i in items],
        )
        review_service.record_outcome(
            owner_id=TEST_OWNER, review_id=review.id,
            capture_id=items[0].id, action="keep",
        )
        review_service.record_outcome(
            owner_id=TEST_OWNER, review_id=review.id,
            capture_id=items[1].id, action="edit",
        )
        review_service.record_outcome(
            owner_id=TEST_OWNER, review_id=review.id,
            capture_id=items[2].id, action="delete",
        )
        review_service.record_outcome(
            owner_id=TEST_OWNER, review_id=review.id,
            capture_id=items[3].id, action="defer",
        )
        summary = review_service.complete_review(
            owner_id=TEST_OWNER, review_id=review.id
        )
        assert summary.total_items == 4
        assert summary.kept == 1
        assert summary.edited == 1
        assert summary.deleted == 1
        assert summary.deferred == 1

    def test_cross_owner_not_found(self, services):
        capture_service, review_service = services
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Task one"
        )
        review = review_service.start_or_resume_review(
            owner_id=TEST_OWNER,
            eligible_items=[items[0].id],
        )
        with pytest.raises(NotFoundError):
            review_service.get_review("wrong_owner", review.id)
