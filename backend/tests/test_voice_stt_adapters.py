"""Contract tests for credentialed Voice Brain Dump accurate-STT adapters."""

from __future__ import annotations

import json

import httpx
import pytest

from app.exceptions import ProviderRetryableError, ProviderTerminalError
from app.workflows.voice_brain_dump.adapters.openai_stt import OpenAiAccurateStt
from app.workflows.voice_brain_dump.providers import (
    AccurateSttRequest,
    DisabledAccurateStt,
)


def _request(audio: bytes = b"\x1aE\xdf\xa3webm-audio") -> AccurateSttRequest:
    return AccurateSttRequest(
        operation_id="operation_1",
        media_ref="media_1",
        language_hints=["ru", "en"],
        vocabulary=["BrainBuddy", "production smoke"],
        supersedes_segment_ids=["preview_1"],
        sealed_audio=audio,
    )


def test_openai_adapter_sends_sealed_binary_audio_and_multilingual_context() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read()
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers["Content-Type"]
        captured["body"] = body
        return httpx.Response(200, json={"text": "Починить BrainBuddy и сделать production smoke"})

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        model="gpt-4o-mini-transcribe",
        timeout_seconds=12,
        max_retries=0,
        retry_backoff_seconds=(),
        max_cost_usd_per_operation=0.50,
        estimated_cost_usd_per_megabyte=0.01,
        transport=httpx.MockTransport(handler),
    )

    result = provider.transcribe_sealed_audio(_request())

    body = captured["body"]
    assert isinstance(body, bytes)
    assert b"\x1aE\xdf\xa3webm-audio" in body
    assert b'gpt-4o-mini-transcribe' in body
    assert b'name="language"' in body and b"ru" in body
    assert b"BrainBuddy" in body and b"production smoke" in body
    assert captured["authorization"] == "Bearer secret-test-key"
    assert str(captured["content_type"]).startswith("multipart/form-data;")
    assert result.provider == "openai"
    assert result.segments[0].model == "gpt-4o-mini-transcribe"
    assert result.segments[0].text == "Починить BrainBuddy и сделать production smoke"
    assert result.segments[0].supersedes_segment_ids == ["preview_1"]


@pytest.mark.parametrize(
    ("audio", "expected_filename", "expected_mime"),
    [
        (b"\x1aE\xdf\xa3webm-audio", b'recording.webm', b"audio/webm"),
        (b"RIFF\x00\x00\x00\x00WAVEpcm-audio", b'recording.wav', b"audio/wav"),
        (b"\x00\x00\x00\x18ftypM4A m4a-audio", b'recording.m4a', b"audio/mp4"),
        (b"\xff\xf1\x50\x80aac-audio", b'recording.aac', b"audio/aac"),
    ],
)
def test_openai_adapter_sniffs_audio_format_for_matching_multipart_metadata(
    audio: bytes, expected_filename: bytes, expected_mime: bytes
) -> None:
    captured_body = b""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = request.read()
        return httpx.Response(200, json={"text": "Ready"})

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    request = _request(audio)
    request = AccurateSttRequest(
        operation_id=request.operation_id,
        media_ref="misleading-recording.mp3",
        sealed_audio=request.sealed_audio,
    )

    provider.transcribe_sealed_audio(request)

    assert expected_filename in captured_body
    assert expected_mime in captured_body
    assert b"recording.mp3" not in captured_body


def test_openai_adapter_rejects_unknown_binary_before_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTerminalError, match="STT_AUDIO_FORMAT_UNSUPPORTED"):
        provider.transcribe_sealed_audio(_request(b"unknown-binary"))

    assert calls == 0


def test_openai_adapter_retries_only_retryable_failures_with_a_bounded_budget() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429, json={"error": {"message": "rate limited secret transcript"}})
        return httpx.Response(200, json={"text": "Готово"})

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        model="gpt-4o-transcribe",
        timeout_seconds=5,
        max_retries=2,
        retry_backoff_seconds=(0.1, 0.2),
        max_cost_usd_per_operation=0.50,
        estimated_cost_usd_per_megabyte=0.01,
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )

    result = provider.transcribe_sealed_audio(_request())

    assert result.segments[0].text == "Готово"
    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_openai_adapter_redacts_provider_payloads_and_credentials_from_errors() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            content=json.dumps({"error": {"message": "bad secret-test-key and transcript"}}),
        )

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        model="gpt-4o-mini-transcribe",
        timeout_seconds=5,
        max_retries=0,
        retry_backoff_seconds=(),
        max_cost_usd_per_operation=0.50,
        estimated_cost_usd_per_megabyte=0.01,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTerminalError) as caught:
        provider.transcribe_sealed_audio(_request())

    assert str(caught.value) == "STT_PROVIDER_AUTHENTICATION_FAILED"
    assert "secret-test-key" not in str(caught.value)
    assert "transcript" not in str(caught.value)


def test_openai_adapter_rejects_requests_over_cost_budget_before_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        model="gpt-4o-mini-transcribe",
        timeout_seconds=5,
        max_retries=0,
        retry_backoff_seconds=(),
        max_cost_usd_per_operation=0.001,
        estimated_cost_usd_per_megabyte=1.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTerminalError, match="STT_COST_LIMIT_EXCEEDED"):
        provider.transcribe_sealed_audio(_request(b"x" * 2_000))

    assert calls == 0


def test_disabled_provider_is_an_explicit_safe_state() -> None:
    provider = DisabledAccurateStt("STT_PROVIDER_CREDENTIALS_MISSING")

    with pytest.raises(ProviderTerminalError, match="STT_PROVIDER_CREDENTIALS_MISSING"):
        provider.transcribe_sealed_audio(_request())


def test_openai_adapter_exhausts_transport_retries_as_retryable_error() -> None:
    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        model="gpt-4o-mini-transcribe",
        timeout_seconds=0.1,
        max_retries=1,
        retry_backoff_seconds=(0.0,),
        max_cost_usd_per_operation=0.50,
        estimated_cost_usd_per_megabyte=0.01,
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout", request=request))
        ),
        sleep=lambda _delay: None,
    )

    with pytest.raises(ProviderRetryableError, match="STT_PROVIDER_UNAVAILABLE"):
        provider.transcribe_sealed_audio(_request())


def test_openai_adapter_rejects_missing_audio_before_network() -> None:
    provider = OpenAiAccurateStt(api_key="secret-test-key")

    with pytest.raises(ProviderTerminalError, match="STT_AUDIO_MISSING"):
        provider.transcribe_sealed_audio(_request(b""))


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (httpx.Response(200, content=b"not-json"), "STT_PROVIDER_INVALID_RESPONSE"),
        (httpx.Response(200, json={"text": "  "}), "STT_PROVIDER_INVALID_RESPONSE"),
        (httpx.Response(413), "STT_AUDIO_TOO_LARGE"),
        (httpx.Response(422), "STT_PROVIDER_REJECTED_REQUEST"),
    ],
)
def test_openai_adapter_maps_terminal_responses_to_redacted_codes(
    response: httpx.Response, expected_code: str
) -> None:
    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(lambda _request: response),
    )

    with pytest.raises(ProviderTerminalError, match=expected_code):
        provider.transcribe_sealed_audio(_request())


def test_openai_adapter_exhausts_retryable_http_status_without_backoff() -> None:
    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        retry_backoff_seconds=(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(429)),
    )

    with pytest.raises(ProviderRetryableError, match="STT_PROVIDER_UNAVAILABLE"):
        provider.transcribe_sealed_audio(_request())


def test_openai_adapter_omits_optional_hint_fields_when_they_are_empty() -> None:
    captured_body = b""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = request.read()
        return httpx.Response(200, json={"text": "Ready"})

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    request = _request()
    request = AccurateSttRequest(
        operation_id=request.operation_id,
        media_ref=request.media_ref,
        sealed_audio=request.sealed_audio,
    )

    result = provider.transcribe_sealed_audio(request)

    assert result.segments[0].text == "Ready"
    assert b'name="language"' not in captured_body
    assert b'name="prompt"' not in captured_body


def test_openai_adapter_skips_sleep_when_retry_backoff_is_empty() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(200, json={"text": "Recovered"})

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        max_retries=1,
        retry_backoff_seconds=(),
        transport=httpx.MockTransport(handler),
    )

    result = provider.transcribe_sealed_audio(_request())

    assert attempts == 2
    assert result.segments[0].text == "Recovered"
