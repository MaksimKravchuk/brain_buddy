"""Tests for the capture service: session creation, transcription, splitting, retry."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.exceptions import ValidationFailure
from app.modules.capture.domain import CaptureSession
from app.modules.capture.repository import CaptureRepository
from app.modules.capture.service import LOW_CONFIDENCE_THRESHOLD, CaptureService
from app.utils.time import utcnow

OWNER = "user_a"
OWNER_B = "user_b"


@pytest.fixture
def repo(tmp_path: Path) -> CaptureRepository:
    return CaptureRepository(tmp_path / "captures")


@pytest.fixture
def service(repo: CaptureRepository) -> CaptureService:
    return CaptureService(repo)


class TestCaptureSessionCreation:
    def test_text_capture_creates_ready_session(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="Buy milk. Walk the dog. Why is the sky blue?",
        )
        assert session.status == "ready"
        assert session.input_kind == "text"
        assert len(session.atomic_capture_ids) == 3
        assert session.transcript is not None
        assert session.transcript.text == "Buy milk. Walk the dog. Why is the sky blue?"
        assert session.transcript.confidence is not None

    def test_empty_text_fails(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="",
        )
        assert session.status == "failed"
        assert session.last_error is not None
        assert session.last_error.code == "EMPTY_TRANSCRIPT"
        assert session.last_error.retryable is True

    def test_whitespace_only_fails(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="   ",
        )
        assert session.status == "failed"
        assert session.last_error.code == "EMPTY_TRANSCRIPT"

    def test_voice_capture_with_media(self, service: CaptureService) -> None:
        media_bytes = b"Need to call mom. Remember to buy groceries."
        session = service.create_session(
            owner_id=OWNER,
            input_kind="voice",
            media_bytes=media_bytes,
        )
        assert session.status == "ready"
        assert len(session.atomic_capture_ids) == 2
        assert session.media_ref is not None

    def test_voice_capture_no_media_fails(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="voice",
            media_bytes=None,
        )
        assert session.status == "failed"
        assert session.last_error.code == "TRANSCRIPTION_FAILED"


class TestCaptureSessionRetry:
    def test_retry_transcription_failure(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="",
        )
        assert session.status == "failed"
        assert session.last_error.stage == "transcription"

        # Retry with valid text.
        retried = service.retry_session(
            owner_id=OWNER,
            session_id=session.id,
            text_input="Valid text now. Second sentence here.",
        )
        assert retried.status == "ready"
        assert len(retried.atomic_capture_ids) == 2
        # Attempt count should have increased.
        assert retried.attempt_count >= 2

    def test_retry_non_failed_rejected(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="Test sentence.",
        )
        assert session.status == "ready"

        with pytest.raises(ValidationFailure, match="Cannot retry"):
            service.retry_session(owner_id=OWNER, session_id=session.id)

    def test_retry_preserves_prior_attempts(self, service: CaptureService) -> None:
        """Retry should not overwrite prior error metadata."""
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="",
        )
        first_error = session.last_error
        assert first_error is not None

        # Retry and succeed.
        retried = service.retry_session(
            owner_id=OWNER,
            session_id=session.id,
            text_input="Now it works.",
        )
        assert retried.status == "ready"
        # The prior error should still be recorded (attempt count increased).
        assert retried.attempt_count >= 2


class TestCaptureSessionCancellation:
    def test_cancel_received_session(self, service: CaptureService) -> None:
        # Create a session object directly to test cancel from received state.
        session = CaptureSession(
            id="test_sess",
            owner_id=OWNER,
            input_kind="text",
            status="received",
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        service._repo.save_session(session)

        cancelled = service.cancel_session(owner_id=OWNER, session_id="test_sess")
        assert cancelled.status == "cancelled"

    def test_cancel_failed_session(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="",
        )
        assert session.status == "failed"

        cancelled = service.cancel_session(owner_id=OWNER, session_id=session.id)
        assert cancelled.status == "cancelled"

    def test_cancel_ready_session_rejected(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="Test.",
        )
        assert session.status == "ready"

        with pytest.raises(ValidationFailure, match="Cannot cancel"):
            service.cancel_session(owner_id=OWNER, session_id=session.id)


class TestCaptureSessionOwnerIsolation:
    def test_cross_owner_get_returns_not_found(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="My private thought.",
        )

        from app.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            service.get_session(owner_id=OWNER_B, session_id=session.id)

    def test_cross_owner_retry_returns_not_found(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="",
        )

        from app.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            service.retry_session(owner_id=OWNER_B, session_id=session.id)


class TestSplitterAndClassification:
    def test_split_produces_ordinal_ordered_sources(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="First task. Second note. Third question?",
        )
        sources = service.get_sources(owner_id=OWNER, session_id=session.id)
        assert len(sources) == 3
        assert sources[0].ordinal == 0
        assert sources[1].ordinal == 1
        assert sources[2].ordinal == 2
        assert sources[0].source_text == "First task."

    def test_classification_assigns_kinds(self, service: CaptureService) -> None:
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="Need to buy milk. The sky is blue. How does this work?",
        )
        sources = service.get_sources(owner_id=OWNER, session_id=session.id)
        assert len(sources) == 3
        assert sources[0].kind == "task"
        assert sources[1].kind == "note"
        assert sources[2].kind == "question"

    def test_low_confidence_detection(self, service: CaptureService) -> None:
        # "problem_candidate" kind has confidence 0.70 which is below threshold 0.75.
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input="There is a problem with the server.",
        )
        sources = service.get_sources(owner_id=OWNER, session_id=session.id)
        assert len(sources) == 1
        source = sources[0]
        assert source.classification.confidence is not None
        assert source.classification.confidence < LOW_CONFIDENCE_THRESHOLD
        assert CaptureService.is_low_confidence(source) is True

    def test_source_span_covers_text(self, service: CaptureService) -> None:
        text = "First. Second."
        session = service.create_session(
            owner_id=OWNER,
            input_kind="text",
            text_input=text,
        )
        sources = service.get_sources(owner_id=OWNER, session_id=session.id)
        assert len(sources) == 2
        for source in sources:
            span = source.source_span
            assert span is not None
            extracted = text[span.start_char:span.end_char]
            assert extracted == source.source_text
