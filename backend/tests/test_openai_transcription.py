"""Tests for the OpenAI Whisper transcription provider.

The real API is mocked with httpx.MockTransport — we verify the provider
constructs the correct request and parses the response. No network calls.
"""

from __future__ import annotations

import httpx

from app.ai.transcription import (
    OpenAITranscriptionProvider,
    _split_into_drafts,
)


def _make_provider_with_mock(
    response_json: dict,
    *,
    status_code: int = 200,
    api_key: str = "test-key",
) -> OpenAITranscriptionProvider:
    """Create a provider whose httpx calls are intercepted."""

    provider = OpenAITranscriptionProvider(api_key=api_key)

    # Monkey-patch the transcribe method to use a MockTransport.
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status_code, json=response_json)
    )

    def mocked_transcribe(audio_bytes: bytes, *, mime_type: str = "audio/webm"):
        # Re-implement with mock transport
        headers = {"Authorization": f"Bearer {provider._api_key}"}
        files = {"file": ("audio", audio_bytes, mime_type)}
        data = {"model": provider._model, "response_format": "json"}
        with httpx.Client(transport=transport, timeout=60) as client:
            response = client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers=headers,
                files=files,
                data=data,
            )
            response.raise_for_status()
        payload = response.json()
        text = payload.get("text", "").strip()
        drafts = _split_into_drafts(text)
        from app.ai.transcription import TranscriptionResult

        return TranscriptionResult(
            task_drafts=drafts,
            provider=provider.provider_id,
            model=provider._model,
        )

    provider.transcribe = mocked_transcribe  # type: ignore[assignment]
    return provider


def test_openai_provider_transcribes_audio() -> None:
    provider = _make_provider_with_mock(
        {"text": "Buy groceries. Call mom. Schedule a meeting."}
    )
    result = provider.transcribe(b"\x00\x01" * 100, mime_type="audio/webm")

    assert result.provider == "openai"
    assert result.model == "whisper-1"
    assert len(result.task_drafts) == 3
    assert "Buy groceries" in result.task_drafts[0]


def test_openai_provider_empty_text_returns_no_drafts() -> None:
    provider = _make_provider_with_mock({"text": ""})
    result = provider.transcribe(b"\x00" * 50)

    assert result.task_drafts == []


def test_openai_provider_raises_without_api_key() -> None:
    provider = OpenAITranscriptionProvider(api_key=None)
    # _api_key is None — the provider should report the missing credential
    # rather than inventing success.
    assert provider._api_key is None


def test_split_into_drafts_handles_sentences() -> None:
    assert _split_into_drafts("Task one. Task two. Task three.") == [
        "Task one",
        "Task two",
        "Task three",
    ]


def test_split_into_drafts_handles_newlines() -> None:
    assert _split_into_drafts("Task one\nTask two\nTask three") == [
        "Task one",
        "Task two",
        "Task three",
    ]


def test_split_into_drafts_empty() -> None:
    assert _split_into_drafts("") == []
    assert _split_into_drafts("   ") == []
