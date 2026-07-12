"""Port interfaces for cross-module communication.

These are Python Protocol classes per ADR-0001 §7: the first implementation
may keep ports as Python protocols and invoke them synchronously.
"""

from __future__ import annotations

from typing import Protocol

from app.modules.capture.domain import (
    AtomicCaptureSource,
    CaptureSession,
)
from app.modules.execution.domain import DispatchAttempt
from app.modules.organize.domain import RouteRecord
from app.modules.thinking.domain import CrtPromotion, ProblemCandidate

# --- Capture ports ---


class TranscriptionPort(Protocol):
    """Transcription provider port (Capture-owned)."""

    def transcribe(
        self,
        session: CaptureSession,
        *,
        media_bytes: bytes | None = None,
        text_input: str | None = None,
    ) -> tuple[str, float | None, str]:
        """Transcribe a capture session.

        Returns (text, confidence, provider). May raise TranscriptionError.
        """
        ...


class SplitterPort(Protocol):
    """Splitter port for dividing a transcript into atomic captures."""

    def split(
        self, transcript_text: str, session: CaptureSession
    ) -> list[AtomicCaptureSource]:
        """Split transcript text into atomic capture sources.

        May raise SplitError if no captures can be produced.
        """
        ...


# --- Execution ports ---


class TaskTrackerPort(Protocol):
    """External task-tracker adapter port (Execution-owned)."""

    def dispatch(
        self,
        route: RouteRecord,
        capture_text: str,
        *,
        idempotency_key: str,
    ) -> DispatchAttempt:
        """Dispatch a task to the external tracker.

        Returns a DispatchAttempt with status succeeded/failed.
        """
        ...


# --- Thinking ports ---


class ThinkingPort(Protocol):
    """Thinking/CRT port for problem candidate management."""

    def create_candidate(
        self,
        owner_id: str,
        source_capture_ids: list[str],
        title: str,
        context: str,
        *,
        signal: str = "manual",
        signal_reasons: list[str] | None = None,
    ) -> ProblemCandidate:
        """Create a new problem candidate."""
        ...

    def promote(
        self,
        candidate: ProblemCandidate,
        *,
        idempotency_key: str,
    ) -> CrtPromotion:
        """Promote a candidate to a CRT tree."""
        ...


__all__ = [
    "SplitterPort",
    "TaskTrackerPort",
    "ThinkingPort",
    "TranscriptionPort",
]
