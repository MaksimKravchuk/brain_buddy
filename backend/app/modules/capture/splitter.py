"""Transcript splitter for the Capture module.

Splits a transcript text into atomic capture sources. The MVP uses a
simple sentence-based heuristic: each sentence becomes one atomic capture.
Classification assigns a broad kind (task/note/question/problem_candidate)
based on simple cues.
"""

from __future__ import annotations

import re
import uuid

from app.exceptions import BrainBuddyError
from app.modules.capture.domain import (
    AtomicCaptureClassification,
    AtomicCaptureKind,
    AtomicCaptureSource,
    CaptureSession,
    SourceSpan,
)
from app.utils.time import utcnow


class SplitError(BrainBuddyError):
    """Raised when transcript splitting fails."""


# Simple sentence boundary detection.
_SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")

# Classification cues.
_QUESTION_CUES = ("?", "how", "why", "what", "when", "where", "who", "which")
_TASK_CUES = ("need to", "must", "should", "todo", "action", "follow up", "remember to")
_PROBLEM_CUES = ("problem", "issue", "bug", "broken", "failing", "wrong", "error")


def _classify(text: str) -> tuple[AtomicCaptureKind, float]:
    """Classify a text fragment into a capture kind with confidence."""
    lower = text.lower().strip()

    if any(cue in lower for cue in _QUESTION_CUES):
        return "question", 0.85

    if any(cue in lower for cue in _PROBLEM_CUES):
        return "problem_candidate", 0.70

    if any(cue in lower for cue in _TASK_CUES):
        return "task", 0.82

    return "note", 0.75


class SimpleSplitter:
    """Sentence-based transcript splitter.

    Splits transcript text on sentence boundaries, classifies each fragment,
    and creates AtomicCaptureSource records. The ordinal follows source order.
    """

    def split(
        self, transcript_text: str, session: CaptureSession
    ) -> list[AtomicCaptureSource]:
        """Split transcript text into atomic capture sources.

        Raises SplitError if no captures can be produced.
        """
        text = transcript_text.strip()
        if not text:
            raise SplitError("Cannot split an empty transcript.")

        # Split on sentence boundaries.
        fragments = _SENTENCE_PATTERN.split(text)
        # Filter empty fragments and strip each.
        fragments = [f.strip() for f in fragments if f.strip()]

        if not fragments:
            raise SplitError("No atomic captures found in transcript.")

        sources: list[AtomicCaptureSource] = []
        char_offset = 0

        for ordinal, fragment in enumerate(fragments):
            # Find the fragment's position in the original text.
            start_char = transcript_text.find(fragment, char_offset)
            if start_char == -1:
                start_char = char_offset
            end_char = start_char + len(fragment)
            char_offset = end_char

            kind, confidence = _classify(fragment)

            source = AtomicCaptureSource(
                id=generate_capture_id(),
                owner_id=session.owner_id,
                capture_session_id=session.id,
                ordinal=ordinal,
                kind=kind,
                source_span=SourceSpan(start_char=start_char, end_char=end_char),
                source_text=fragment,
                classification=AtomicCaptureClassification(
                    confidence=confidence,
                    model="simple-splitter-v1",
                    reasons=[f"matched_{kind}_cues"],
                ),
                created_at=utcnow(),
            )
            sources.append(source)

        return sources


def generate_capture_id() -> str:
    """Generate a unique atomic capture ID."""
    return f"cap_{uuid.uuid4().hex[:12]}"


__all__ = ["SimpleSplitter", "SplitError", "generate_capture_id"]
