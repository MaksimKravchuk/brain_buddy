"""Transcription provider port for voice brain dumps.

The port converts audio bytes into a flat list of task draft strings. The
only production implementation is ``OpenAITranscriptionProvider`` which calls
the Whisper API. ``MockTranscriptionProvider`` is used in tests and as a
fallback when no credentials are configured.

If a real transcription provider/credential is absent, the service stops at
this integration boundary and reports the concrete blocker rather than
inventing success.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class TranscriptionResult:
    """Output of transcribing voice audio into task drafts."""

    task_drafts: list[str]
    provider: str
    model: str


class TranscriptionProvider(Protocol):
    """Protocol for transcription providers."""

    provider_id: str

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str = "audio/webm",
    ) -> TranscriptionResult:
        """Transcribe audio and return a flat list of task draft strings."""
        ...


class MockTranscriptionProvider(TranscriptionProvider):
    """Deterministic mock transcription provider for tests.

    Generates task drafts from a hash of the audio bytes, so the same
    audio input always produces the same drafts. Empty audio produces no
    drafts.
    """

    provider_id: str = "mock"

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str = "audio/webm",
    ) -> TranscriptionResult:
        if not audio_bytes:
            return TranscriptionResult(
                task_drafts=[], provider=self.provider_id, model="mock-v1"
            )

        digest = hashlib.sha256(audio_bytes).hexdigest()

        # Deterministic number of drafts (1-3) based on the audio hash.
        seed = int(digest[:8], 16)
        num_drafts = 1 + (seed % 3)

        templates = [
            "Follow up with the team about the project status",
            "Review the latest test results and document findings",
            "Schedule a meeting to discuss the roadmap",
            "Update the documentation with the new API changes",
            "Check the deployment pipeline for recent failures",
            "Research the new library before integrating it",
            "Prepare slides for the upcoming presentation",
            "Clean up the backlog and prioritise important tasks",
        ]

        drafts: list[str] = []
        for i in range(num_drafts):
            idx = (seed + i) % len(templates)
            drafts.append(templates[idx])

        return TranscriptionResult(
            task_drafts=drafts,
            provider=self.provider_id,
            model="mock-v1",
        )


class OpenAITranscriptionProvider:
    """Production transcription provider using the OpenAI Whisper API.

    Calls ``POST /v1/audio/transcriptions`` and splits the returned text
    into task drafts on sentence boundaries. Requires ``OPENAI_API_KEY``.
    """

    provider_id: str = "openai"

    def __init__(self, *, api_key: str | None = None, model: str = "whisper-1") -> None:
        self._api_key = api_key or _resolve_openai_key()
        self._model = model

    def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str = "audio/webm",
    ) -> TranscriptionResult:
        import httpx

        if not self._api_key:
            raise TranscriptionError(
                "OpenAI transcription requires OPENAI_API_KEY or "
                "BRAIN_BUDDY_OPENAI_API_KEY."
            )

        headers = {"Authorization": f"Bearer {self._api_key}"}
        files = {"file": ("audio", audio_bytes, mime_type)}
        data = {"model": self._model, "response_format": "json"}

        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TranscriptionError(
                f"OpenAI transcription request failed: {exc!s}"
            ) from exc

        payload = response.json()
        text = payload.get("text", "").strip()
        drafts = _split_into_drafts(text)
        return TranscriptionResult(
            task_drafts=drafts,
            provider=self.provider_id,
            model=self._model,
        )


class TranscriptionError(Exception):
    """Raised when the transcription provider fails."""


def _resolve_openai_key() -> str | None:
    import os

    return os.getenv("BRAIN_BUDDY_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")


def _split_into_drafts(text: str) -> list[str]:
    """Split a transcription blob into individual task draft strings.

    Splits on sentence boundaries (period, newline) and keeps non-empty,
    stripped sentences as drafts.
    """

    if not text:
        return []
    import re

    parts = re.split(r"[.\n]+", text)
    return [p.strip() for p in parts if p.strip()]


__all__ = [
    "MockTranscriptionProvider",
    "OpenAITranscriptionProvider",
    "TranscriptionError",
    "TranscriptionProvider",
    "TranscriptionResult",
]
