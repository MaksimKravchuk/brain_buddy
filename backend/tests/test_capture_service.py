"""Tests for the Capture module (ADR-0001).

Covers capture session creation, item lifecycle transitions,
and state machine invariants.
"""

from __future__ import annotations

import pytest

from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.modules.capture import CaptureRepository, CaptureService

TEST_OWNER = "user_test_owner"
OTHER_OWNER = "user_other"


@pytest.fixture
def capture_service(data_dir):
    repo = CaptureRepository(data_dir)
    return CaptureService(repo)


class TestCaptureSessionCreation:
    def test_create_text_session_splits_lines(self, capture_service):
        text = "Fix the login bug\nDeploy to staging\nWhy is the API slow?"
        session, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text=text
        )

        assert session.status == "ready"
        assert session.input_kind == "text"
        assert len(items) == 3
        assert session.atomic_capture_ids == [item.id for item in items]

    def test_empty_text_rejected(self, capture_service):
        with pytest.raises(ValidationFailure, match="empty"):
            capture_service.create_text_session(
                owner_id=TEST_OWNER, text="  "
            )

    def test_single_line(self, capture_service):
        session, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Just one thought"
        )
        assert len(items) == 1
        assert items[0].current_text == "Just one thought"
        assert items[0].review_state == "proposed"

    def test_source_text_is_immutable_provenance(self, capture_service):
        session, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Original text"
        )
        source, item = capture_service.get_capture(TEST_OWNER, items[0].id)
        assert source.source_text == "Original text"
        # Edit the item
        capture_service.apply_decision(
            TEST_OWNER, items[0].id, action="edit", new_text="Edited text"
        )
        # Source should still be original
        source2, item2 = capture_service.get_capture(TEST_OWNER, items[0].id)
        assert source2.source_text == "Original text"
        assert item2.current_text == "Edited text"


class TestCaptureItemTransitions:
    def test_proposed_to_approved(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="A task"
        )
        item = capture_service.apply_decision(
            TEST_OWNER, items[0].id, action="approve"
        )
        assert item.review_state == "approved"
        assert item.revision == 2

    def test_proposed_to_deferred_and_back(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="A task"
        )
        item = capture_service.apply_decision(
            TEST_OWNER, items[0].id, action="defer"
        )
        assert item.review_state == "deferred"
        item = capture_service.apply_decision(
            TEST_OWNER, items[0].id, action="approve"
        )
        assert item.review_state == "approved"

    def test_edit_transitions_to_approved(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Original"
        )
        item = capture_service.apply_decision(
            TEST_OWNER,
            items[0].id,
            action="edit",
            new_text="Updated text",
        )
        assert item.review_state == "approved"
        assert item.current_text == "Updated text"

    def test_delete_is_terminal(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="To delete"
        )
        item = capture_service.apply_decision(
            TEST_OWNER, items[0].id, action="delete"
        )
        assert item.review_state == "deleted"
        with pytest.raises(ValidationFailure, match="Cannot"):
            capture_service.apply_decision(
                TEST_OWNER, items[0].id, action="approve"
            )

    def test_complete_is_terminal(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="To complete"
        )
        capture_service.apply_decision(
            TEST_OWNER, items[0].id, action="approve"
        )
        item = capture_service.apply_decision(
            TEST_OWNER, items[0].id, action="complete"
        )
        assert item.review_state == "completed"
        with pytest.raises(ValidationFailure):
            capture_service.apply_decision(
                TEST_OWNER, items[0].id, action="delete"
            )

    def test_cannot_route_before_approval(self, capture_service):
        # Routing is not yet implemented, but the state machine should
        # still prevent transitions from proposed to completed.
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="A task"
        )
        with pytest.raises(ValidationFailure):
            capture_service.apply_decision(
                TEST_OWNER, items[0].id, action="complete"
            )

    def test_stale_revision_conflict(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="A task"
        )
        with pytest.raises(ConflictError):
            capture_service.apply_decision(
                TEST_OWNER,
                items[0].id,
                action="approve",
                expected_revision=999,
            )

    def test_cross_owner_not_found(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="A task"
        )
        with pytest.raises(NotFoundError):
            capture_service.apply_decision(
                OTHER_OWNER, items[0].id, action="approve"
            )


class TestReviewEligibility:
    def test_eligible_states(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER,
            text="Task one\nTask two\nTask three\nTask four",
        )
        # All proposed -> eligible
        eligible = capture_service.list_eligible_for_review(TEST_OWNER)
        assert len(eligible) == 4

        # Approve one -> still eligible (approved is eligible)
        capture_service.apply_decision(
            TEST_OWNER, items[0].id, action="approve"
        )
        eligible = capture_service.list_eligible_for_review(TEST_OWNER)
        assert len(eligible) == 4

        # Complete one -> not eligible
        capture_service.apply_decision(
            TEST_OWNER, items[0].id, action="complete"
        )
        eligible = capture_service.list_eligible_for_review(TEST_OWNER)
        assert len(eligible) == 3

        # Delete one -> not eligible
        capture_service.apply_decision(
            TEST_OWNER, items[1].id, action="delete"
        )
        eligible = capture_service.list_eligible_for_review(TEST_OWNER)
        assert len(eligible) == 2

    def test_cross_owner_eligibility(self, capture_service):
        capture_service.create_text_session(
            owner_id=TEST_OWNER, text="My task"
        )
        capture_service.create_text_session(
            owner_id=OTHER_OWNER, text="Their task"
        )
        eligible = capture_service.list_eligible_for_review(TEST_OWNER)
        assert len(eligible) == 1
        assert eligible[0].owner_id == TEST_OWNER


class TestClassification:
    def test_question_classification(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="How to deploy?"
        )
        source, _ = capture_service.get_capture(TEST_OWNER, items[0].id)
        assert source.kind == "question"

    def test_task_classification(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Fix the bug"
        )
        source, _ = capture_service.get_capture(TEST_OWNER, items[0].id)
        assert source.kind == "task"

    def test_problem_candidate_classification(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="The API is broken"
        )
        source, _ = capture_service.get_capture(TEST_OWNER, items[0].id)
        assert source.kind == "problem_candidate"

    def test_note_classification(self, capture_service):
        _, items = capture_service.create_text_session(
            owner_id=TEST_OWNER, text="Just a thought"
        )
        source, _ = capture_service.get_capture(TEST_OWNER, items[0].id)
        assert source.kind == "note"
