"""Capture service: orchestrates the capture pipeline.

Transitions a CaptureSession through:
  received -> transcribing -> transcribed -> splitting -> ready
  * -> failed (with retry)
  received/failed -> cancelled

The service owns CaptureSession and AtomicCaptureSource records but
delegates to OrganizeService for mutable item creation.
"""

from __future__ import annotations

import logging
import uuid

from app.exceptions import ValidationFailure
from app.modules.capture.domain import (
    AtomicCaptureSource,
    CaptureSession,
    ConsentRecord,
    ErrorRecord,
    MediaInfo,
    TranscriptResult,
)
from app.modules.capture.repository import CaptureRepository
from app.modules.capture.splitter import SimpleSplitter, SplitError
from app.modules.capture.transcription import (
    MockTranscriptionProvider,
    TranscriptionError,
)
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

# Confidence threshold below which captures are marked needs_clarification.
LOW_CONFIDENCE_THRESHOLD = 0.75


class CaptureService:
    """Orchestrates the voice/text capture pipeline."""

    def __init__(
        self,
        repo: CaptureRepository,
        *,
        transcriber: MockTranscriptionProvider | None = None,
        splitter: SimpleSplitter | None = None,
    ) -> None:
        self._repo = repo
        self._transcriber = transcriber or MockTranscriptionProvider()
        self._splitter = splitter or SimpleSplitter()

    # --- Session creation ---

    def create_session(
        self,
        *,
        owner_id: str,
        input_kind: str,
        media_bytes: bytes | None = None,
        media_info: MediaInfo | None = None,
        consent: ConsentRecord | None = None,
        text_input: str | None = None,
    ) -> CaptureSession:
        """Create a new capture session and immediately process it.

        For the MVP, processing is synchronous: transcribe then split.
        """
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        now = utcnow()

        session = CaptureSession(
            id=session_id,
            owner_id=owner_id,
            input_kind=input_kind,  # type: ignore[arg-type]
            status="received",
            media=media_info,
            consent=consent,
            created_at=now,
            updated_at=now,
        )

        # Store media reference (opaque, not a filesystem path).
        if media_bytes is not None:
            session.media_ref = f"memory://{session_id}"

        self._repo.save_session(session)
        logger.info(
            "Capture session %s created for owner %s (kind=%s)",
            session_id,
            owner_id,
            input_kind,
        )

        # Process immediately (MVP synchronous path).
        return self._process(session, media_bytes=media_bytes, text_input=text_input)

    # --- Processing pipeline ---

    def _process(
        self,
        session: CaptureSession,
        *,
        media_bytes: bytes | None = None,
        text_input: str | None = None,
    ) -> CaptureSession:
        """Run the transcription -> splitting pipeline."""
        # Stage 1: Transcribe
        session = self._transcribe(session, media_bytes=media_bytes, text_input=text_input)
        if session.status == "failed":
            return session

        # Stage 2: Split
        session = self._split(session)
        return session

    def _transcribe(
        self,
        session: CaptureSession,
        *,
        media_bytes: bytes | None = None,
        text_input: str | None = None,
    ) -> CaptureSession:
        """Run transcription and update the session."""
        session.status = "transcribing"
        session.attempt_count += 1
        session.updated_at = utcnow()
        self._repo.save_session(session)

        try:
            text, confidence, provider = self._transcriber.transcribe(
                session,
                media_bytes=media_bytes,
                text_input=text_input,
            )
        except TranscriptionError as exc:
            return self._fail_session(
                session,
                code="TRANSCRIPTION_FAILED",
                stage="transcription",
                retryable=True,
                error_msg=str(exc),
            )

        # Empty transcript is a failure per ADR-0001.
        if not text.strip():
            return self._fail_session(
                session,
                code="EMPTY_TRANSCRIPT",
                stage="transcription",
                retryable=True,
                error_msg="Transcript text is empty.",
            )

        session.transcript = TranscriptResult(
            text=text,
            confidence=confidence,
            provider=provider,
            completed_at=utcnow(),
        )
        session.status = "transcribed"
        session.updated_at = utcnow()
        self._repo.save_session(session)
        logger.info(
            "Session %s transcribed (provider=%s, confidence=%s)",
            session.id,
            provider,
            confidence,
        )
        return session

    def _split(self, session: CaptureSession) -> CaptureSession:
        """Split the transcript into atomic captures and persist them."""
        if session.transcript is None:
            return self._fail_session(
                session,
                code="NO_TRANSCRIPT",
                stage="splitting",
                retryable=False,
                error_msg="Cannot split: no transcript available.",
            )

        session.status = "splitting"
        session.updated_at = utcnow()
        self._repo.save_session(session)

        try:
            sources = self._splitter.split(session.transcript.text, session)
        except SplitError as exc:
            return self._fail_session(
                session,
                code="NO_ATOMIC_CAPTURES",
                stage="splitting",
                retryable=True,
                error_msg=str(exc),
            )

        if not sources:
            return self._fail_session(
                session,
                code="NO_ATOMIC_CAPTURES",
                stage="splitting",
                retryable=True,
                error_msg="Splitter produced no captures.",
            )

        # Persist sources.
        for source in sources:
            self._repo.save_source(source)

        session.atomic_capture_ids = [s.id for s in sources]
        session.status = "ready"
        session.updated_at = utcnow()
        self._repo.save_session(session)
        logger.info(
            "Session %s ready with %d atomic captures",
            session.id,
            len(sources),
        )
        return session

    def _fail_session(
        self,
        session: CaptureSession,
        *,
        code: str,
        stage: str,
        retryable: bool,
        error_msg: str,
    ) -> CaptureSession:
        """Transition a session to failed state."""
        session.status = "failed"
        session.last_error = ErrorRecord(
            code=code,
            retryable=retryable,
            stage=stage,
        )
        session.updated_at = utcnow()
        self._repo.save_session(session)
        logger.warning(
            "Session %s failed at stage %s: %s (code=%s)",
            session.id,
            stage,
            error_msg,
            code,
        )
        return session

    # --- Retry ---

    def retry_session(
        self,
        *,
        owner_id: str,
        session_id: str,
        media_bytes: bytes | None = None,
        text_input: str | None = None,
    ) -> CaptureSession:
        """Retry a failed session from the failed stage."""
        session = self._repo.load_session(owner_id, session_id)

        if session.status != "failed":
            raise ValidationFailure(
                f"Cannot retry session in status '{session.status}'.",
                detail={"current_status": session.status},
            )

        if session.last_error and not session.last_error.retryable:
            raise ValidationFailure(
                f"Session failure is not retryable (code={session.last_error.code}).",
                detail={"error_code": session.last_error.code},
            )

        # Retry from the failed stage.
        stage = session.last_error.stage if session.last_error else "transcription"

        if stage == "transcription":
            # Reset transcript and retry from transcribing.
            session.transcript = None
            session.atomic_capture_ids = []
            return self._process(session, media_bytes=media_bytes, text_input=text_input)
        elif stage == "splitting":
            # Retry from splitting.
            return self._split(session)
        else:
            # Unknown stage, retry from the beginning.
            session.transcript = None
            session.atomic_capture_ids = []
            return self._process(session, media_bytes=media_bytes, text_input=text_input)

    # --- Cancellation ---

    def cancel_session(self, *, owner_id: str, session_id: str) -> CaptureSession:
        """Cancel a session (only from received or failed)."""
        session = self._repo.load_session(owner_id, session_id)

        if session.status not in ("received", "failed"):
            raise ValidationFailure(
                f"Cannot cancel session in status '{session.status}'.",
                detail={"current_status": session.status},
            )

        session.status = "cancelled"
        session.updated_at = utcnow()
        self._repo.save_session(session)
        logger.info("Session %s cancelled", session_id)
        return session

    # --- Queries ---

    def get_session(self, *, owner_id: str, session_id: str) -> CaptureSession:
        return self._repo.load_session(owner_id, session_id)

    def get_sources(self, *, owner_id: str, session_id: str) -> list[AtomicCaptureSource]:
        return self._repo.load_sources_for_session(owner_id, session_id)

    def get_source(self, *, owner_id: str, source_id: str) -> AtomicCaptureSource:
        return self._repo.load_source(owner_id, source_id)

    def list_sessions(self, *, owner_id: str) -> list[CaptureSession]:
        return self._repo.list_sessions(owner_id)

    # --- Confidence helpers ---

    @staticmethod
    def is_low_confidence(source: AtomicCaptureSource) -> bool:
        """Check if a source has low classification confidence."""
        conf = source.classification.confidence
        if conf is None:
            return False
        return conf < LOW_CONFIDENCE_THRESHOLD


__all__ = ["CaptureService", "LOW_CONFIDENCE_THRESHOLD"]
