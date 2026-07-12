"""Transcription providers for the Capture module.

The MVP uses a mock provider that returns the input text directly.
Real providers (e.g. OpenAI Whisper, Google Speech-to-Text) would implement
the same TranscriptionPort protocol.
"""

from __future__ import annotations

from app.exceptions import BrainBuddyError
from app.modules.capture.domain import CaptureSession


class TranscriptionError(BrainBuddyError):
    """Raised when transcription fails."""


class MockTranscriptionProvider:
    """Deterministic mock transcription provider for testing and MVP.

    For voice input: returns media_bytes decoded as text if available,
    or raises TranscriptionError if the media is empty.
    For text input: returns the text directly with high confidence.
    """

    PROVIDER_NAME = "mock"

    def transcribe(
        self,
        session: CaptureSession,
        *,
        media_bytes: bytes | None = None,
        text_input: str | None = None,
    ) -> tuple[str, float | None, str]:
        """Transcribe a capture session.

        Returns (text, confidence, provider_name).
        """
        if session.input_kind == "text":
            if text_input is None:
                raise TranscriptionError("No text input provided.")
            # Let the service handle empty/whitespace text as EMPTY_TRANSCRIPT.
            return text_input, 0.95, self.PROVIDER_NAME

        # Voice: in the MVP mock, media_bytes is the text itself (for testing).
        if media_bytes is None:
            raise TranscriptionError("No media data provided for voice transcription.")
        try:
            text = media_bytes.decode("utf-8")
        except (UnicodeDecodeError, AttributeError) as exc:
            raise TranscriptionError(
                f"Failed to decode media data: {exc}"
            ) from exc

        # Return the text even if whitespace-only; the service will detect
        # the empty transcript and transition to failed with EMPTY_TRANSCRIPT.
        return text, 0.92, self.PROVIDER_NAME


__all__ = ["MockTranscriptionProvider", "TranscriptionError"]
