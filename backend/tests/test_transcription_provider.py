"""Tests for the transcription provider port and mock implementation."""

from __future__ import annotations

from app.ai.transcription import (
    MockTranscriptionProvider,
    TranscriptionResult,
)


def test_mock_provider_returns_tasks() -> None:
    provider = MockTranscriptionProvider()
    audio = b"\x00\x01" * 100  # fake audio bytes
    result = provider.transcribe(audio, mime_type="audio/webm")

    assert isinstance(result, TranscriptionResult)
    assert len(result.task_drafts) > 0
    assert all(isinstance(text, str) and text.strip() for text in result.task_drafts)


def test_mock_provider_idempotent_for_same_input() -> None:
    provider = MockTranscriptionProvider()
    audio = b"\x00\x01" * 100
    result1 = provider.transcribe(audio, mime_type="audio/webm")
    result2 = provider.transcribe(audio, mime_type="audio/webm")
    assert result1.task_drafts == result2.task_drafts


def test_mock_provider_empty_audio_returns_no_drafts() -> None:
    provider = MockTranscriptionProvider()
    result = provider.transcribe(b"", mime_type="audio/webm")
    assert len(result.task_drafts) == 0


def test_transcription_result_has_provider_metadata() -> None:
    provider = MockTranscriptionProvider()
    result = provider.transcribe(b"\x00" * 50, mime_type="audio/webm")
    assert result.provider == "mock"
    assert result.model is not None
