"""Contract tests for credentialed Voice Brain Dump accurate-STT adapters."""

from __future__ import annotations

import json

import httpx
import pytest

from app.exceptions import ProviderRetryableError, ProviderTerminalError
from app.workflows.voice_brain_dump.adapters.deepgram_stt import DeepgramAccurateStt
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
        return httpx.Response(
            200,
            json={
                "text": "Починить BrainBuddy и сделать production smoke",
                "usage": {
                    "input_tokens": 123,
                    "output_tokens": 17,
                    "total_tokens": 140,
                    "request_id": 999,
                },
            },
        )

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
    assert b"gpt-4o-mini-transcribe" in body
    # Two hints is a code-switched recording: no single language is pinned.
    assert b'name="language"' not in body
    assert b"BrainBuddy" in body and b"production smoke" in body
    assert captured["authorization"] == "Bearer secret-test-key"
    assert str(captured["content_type"]).startswith("multipart/form-data;")
    assert result.provider == "openai"
    assert result.segments[0].model == "gpt-4o-mini-transcribe"
    assert result.segments[0].text == "Починить BrainBuddy и сделать production smoke"
    assert result.segments[0].language == "ru,en"
    assert result.segments[0].supersedes_segment_ids == ["preview_1"]
    assert result.cost_estimate_basis == "audio_bytes_proxy"
    assert result.actual_cost_usd is None
    assert result.provider_usage == {
        "input_tokens": 123,
        "output_tokens": 17,
        "total_tokens": 140,
    }


def test_openai_adapter_repr_redacts_api_key() -> None:
    provider = OpenAiAccurateStt(api_key="sensitive-test-key")

    assert "sensitive-test-key" not in repr(provider)


@pytest.mark.parametrize(
    ("audio", "expected_filename", "expected_mime"),
    [
        (b"\x1aE\xdf\xa3webm-audio", b"recording.webm", b"audio/webm"),
        (b"RIFF\x00\x00\x00\x00WAVEpcm-audio", b"recording.wav", b"audio/wav"),
        (b"\x00\x00\x00\x18ftypM4A m4a-audio", b"recording.m4a", b"audio/mp4"),
        (b"\xff\xf1\x50\x80aac-audio", b"recording.aac", b"audio/aac"),
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
            return httpx.Response(
                429, json={"error": {"message": "rate limited secret transcript"}}
            )
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
            content=json.dumps(
                {"error": {"message": "bad secret-test-key and transcript"}}
            ),
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
            lambda request: (_ for _ in ()).throw(
                httpx.ReadTimeout("timeout", request=request)
            )
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


def test_openai_adapter_tags_retryable_failure_with_conservative_estimated_cost() -> (
    None
):
    """A transport-retryable failure still made real, billable attempts; the
    operation-wide cost cap must see that spend, not silently record zero
    just because the call ultimately failed. The estimate is conservatively
    scaled by the adapter's own bounded retry budget, since a single logical
    call may itself cost the provider once per internal attempt."""

    audio = _request().sealed_audio
    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        max_retries=2,
        retry_backoff_seconds=(0.0, 0.0),
        estimated_cost_usd_per_megabyte=1.0,
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
        sleep=lambda _delay: None,
    )

    with pytest.raises(ProviderRetryableError) as caught:
        provider.transcribe_sealed_audio(_request(audio))

    expected = (len(audio) / 1_000_000) * 1.0 * (2 + 1)
    assert caught.value.estimated_cost_usd == pytest.approx(expected)
    assert caught.value.estimated_cost_usd > 0


def test_openai_adapter_tags_terminal_failure_with_estimated_cost_after_a_real_call() -> (
    None
):
    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        estimated_cost_usd_per_megabyte=1.0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(401, content=b"{}")
        ),
    )

    with pytest.raises(ProviderTerminalError) as caught:
        provider.transcribe_sealed_audio(_request())

    assert caught.value.estimated_cost_usd > 0


def test_openai_adapter_never_tags_cost_when_admission_refuses_the_call() -> None:
    """The pre-flight cost-cap rejection never places a network call, so it
    must not report any spend either — there is nothing to conservatively
    account for yet."""

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        max_cost_usd_per_operation=0.001,
        estimated_cost_usd_per_megabyte=1.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTerminalError) as caught:
        provider.transcribe_sealed_audio(_request(b"x" * 2_000))

    assert calls == 0
    assert getattr(caught.value, "estimated_cost_usd", 0.0) == 0.0


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


def test_openai_adapter_treats_insufficient_quota_429_as_terminal_without_retries() -> (
    None
):
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429,
            json={
                "error": {
                    "type": "insufficient_quota",
                    "code": "insufficient_quota",
                    "message": "You exceeded your current quota secret transcript",
                }
            },
        )

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        max_retries=2,
        retry_backoff_seconds=(0.0, 0.0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _delay: None,
    )

    with pytest.raises(ProviderTerminalError) as caught:
        provider.transcribe_sealed_audio(_request())

    assert str(caught.value) == "STT_PROVIDER_REJECTED_REQUEST"
    assert attempts == 1


def test_openai_adapter_still_retries_a_plain_rate_limit_429() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            return httpx.Response(
                429,
                json={"error": {"type": "requests", "message": "Rate limit reached"}},
            )
        return httpx.Response(200, json={"text": "Готово"})

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        max_retries=2,
        retry_backoff_seconds=(0.0, 0.0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _delay: None,
    )

    result = provider.transcribe_sealed_audio(_request())

    assert attempts == 2
    assert result.segments[0].text == "Готово"


def test_openai_adapter_keeps_language_field_for_a_single_hint() -> None:
    captured_body = b""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = request.read()
        return httpx.Response(200, json={"text": "Готово"})

    provider = OpenAiAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    request = AccurateSttRequest(
        operation_id="operation_1",
        media_ref="media_1",
        language_hints=["ru-RU"],
        sealed_audio=b"\x1aE\xdf\xa3webm-audio",
    )

    result = provider.transcribe_sealed_audio(request)

    assert b'name="language"' in captured_body
    assert b"ru" in captured_body
    assert result.segments[0].language == "ru-RU"


def _deepgram_payload(
    transcript: str = "Починить BrainBuddy и запустить production smoke",
    *,
    duration: float | None = 249.0,
    confidence: float = 0.985,
    word_languages: tuple[str, ...] = ("ru", "ru", "en"),
) -> dict[str, object]:
    words = [
        {
            "word": f"w{index}",
            "start": float(index),
            "end": float(index) + 0.4,
            "confidence": 0.9,
            "punctuated_word": f"W{index}",
            "language": language,
        }
        for index, language in enumerate(word_languages)
    ]
    metadata: dict[str, object] = {}
    if duration is not None:
        metadata["duration"] = duration
    return {
        "metadata": metadata,
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": transcript,
                            "confidence": confidence,
                            "languages": sorted(set(word_languages)),
                            "words": words,
                        }
                    ]
                }
            ]
        },
    }


def test_deepgram_adapter_transcribes_multilingual_audio() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers["Content-Type"]
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, json=_deepgram_payload())

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        model="nova-3",
        timeout_seconds=30,
        max_retries=0,
        retry_backoff_seconds=(),
        max_cost_usd_per_operation=0.50,
        estimated_cost_usd_per_megabyte=0.01,
        transport=httpx.MockTransport(handler),
    )

    result = provider.transcribe_sealed_audio(_request())

    assert captured["authorization"] == "Token secret-test-key"
    assert captured["content_type"] == "audio/webm"
    assert captured["body"] == b"\x1aE\xdf\xa3webm-audio"
    url = str(captured["url"])
    assert "model=nova-3" in url
    assert "smart_format=true" in url
    assert "punctuate=true" in url
    assert "utterances=true" in url
    assert "language=multi" in url
    assert result.provider == "deepgram"
    assert len(result.segments) == 1  # no utterances array -> single-blob fallback
    assert result.segments[0].model == "nova-3"
    assert result.segments[0].text == "Починить BrainBuddy и запустить production smoke"
    assert result.segments[0].language == "en,ru"
    assert result.segments[0].confidence == pytest.approx(0.985)
    assert result.segments[0].start_ms == 0
    assert result.segments[0].end_ms == 249_000
    assert result.segments[0].supersedes_segment_ids == ["preview_1"]
    assert result.cost_estimate_basis == "audio_bytes_proxy"
    assert result.actual_cost_usd is None
    assert result.provider_usage == {"duration_seconds": 249.0}


def test_deepgram_adapter_repr_redacts_api_key() -> None:
    provider = DeepgramAccurateStt(api_key="sensitive-test-key")

    assert "sensitive-test-key" not in repr(provider)


@pytest.mark.parametrize(
    ("hints", "expected_param"),
    [
        (["ru-RU"], "language=ru"),
        (["en"], "language=en"),
        (["ru", "en"], "language=multi"),
        ([], "language=multi"),
    ],
)
def test_deepgram_adapter_selects_language_param_from_hint_count(
    hints: list[str], expected_param: str
) -> None:
    captured_url = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_url
        captured_url = str(request.url)
        return httpx.Response(200, json=_deepgram_payload())

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    request = AccurateSttRequest(
        operation_id="operation_1",
        media_ref="media_1",
        language_hints=hints,
        sealed_audio=b"\x1aE\xdf\xa3webm-audio",
    )

    provider.transcribe_sealed_audio(request)

    assert expected_param in captured_url


@pytest.mark.parametrize(
    ("audio", "expected_mime"),
    [
        (b"\x1aE\xdf\xa3webm-audio", "audio/webm"),
        (b"RIFF\x00\x00\x00\x00WAVEpcm-audio", "audio/wav"),
        (b"\x00\x00\x00\x18ftypM4A m4a-audio", "audio/mp4"),
        (b"\xff\xf1\x50\x80aac-audio", "audio/aac"),
    ],
)
def test_deepgram_adapter_sets_content_type_from_sniffed_container(
    audio: bytes, expected_mime: str
) -> None:
    captured_content_type = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_content_type
        captured_content_type = request.headers["Content-Type"]
        return httpx.Response(200, json=_deepgram_payload())

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    provider.transcribe_sealed_audio(_request(audio))

    assert captured_content_type == expected_mime


def test_deepgram_adapter_rejects_unknown_binary_before_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_deepgram_payload())

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTerminalError, match="STT_AUDIO_FORMAT_UNSUPPORTED"):
        provider.transcribe_sealed_audio(_request(b"unknown-binary"))

    assert calls == 0


def test_deepgram_adapter_maps_authentication_failure_as_terminal_without_retries() -> (
    None
):
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            401, json={"err_code": "INVALID_AUTH", "err_msg": "secret transcript"}
        )

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=2,
        retry_backoff_seconds=(0.0, 0.0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _delay: None,
    )

    with pytest.raises(ProviderTerminalError) as caught:
        provider.transcribe_sealed_audio(_request())

    assert str(caught.value) == "STT_PROVIDER_AUTHENTICATION_FAILED"
    assert "secret-test-key" not in str(caught.value)
    assert "transcript" not in str(caught.value)
    assert attempts == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"metadata": {"duration": 1.0}, "results": {"channels": []}},
        _deepgram_payload(transcript="   "),
    ],
)
def test_deepgram_adapter_rejects_empty_transcript_as_invalid_response(
    payload: dict[str, object],
) -> None:
    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=payload)
        ),
    )

    with pytest.raises(ProviderTerminalError, match="STT_PROVIDER_INVALID_RESPONSE"):
        provider.transcribe_sealed_audio(_request())


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (httpx.Response(200, content=b"not-json"), "STT_PROVIDER_INVALID_RESPONSE"),
        (httpx.Response(413), "STT_AUDIO_TOO_LARGE"),
        (httpx.Response(422, json={"err_msg": "bad"}), "STT_PROVIDER_REJECTED_REQUEST"),
    ],
)
def test_deepgram_adapter_maps_terminal_responses_to_redacted_codes(
    response: httpx.Response, expected_code: str
) -> None:
    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(lambda _request: response),
    )

    with pytest.raises(ProviderTerminalError, match=expected_code):
        provider.transcribe_sealed_audio(_request())


def test_deepgram_adapter_exhausts_retryable_status_as_retryable_error() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=2,
        retry_backoff_seconds=(0.1, 0.2),
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )

    with pytest.raises(ProviderRetryableError, match="STT_PROVIDER_UNAVAILABLE"):
        provider.transcribe_sealed_audio(_request())

    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_deepgram_adapter_retries_then_succeeds_within_the_bounded_budget() -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(
                429, json={"err_msg": "rate limited secret transcript"}
            )
        return httpx.Response(200, json=_deepgram_payload())

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=2,
        retry_backoff_seconds=(0.0, 0.0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _delay: None,
    )

    result = provider.transcribe_sealed_audio(_request())

    assert attempts == 3
    assert result.provider == "deepgram"


def test_deepgram_adapter_falls_back_to_word_count_when_duration_missing() -> None:
    payload = _deepgram_payload(
        transcript="one two three",
        duration=None,
        word_languages=("en", "en", "en"),
    )

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=payload)
        ),
    )

    result = provider.transcribe_sealed_audio(_request())

    assert result.segments[0].end_ms == 3 * 500
    assert result.segments[0].language == "en"
    assert result.provider_usage == {}


def test_deepgram_adapter_falls_back_to_language_param_without_word_tags() -> None:
    payload = _deepgram_payload(word_languages=())

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=payload)
        ),
    )
    request = AccurateSttRequest(
        operation_id="operation_1",
        media_ref="media_1",
        language_hints=["ru-RU"],
        sealed_audio=b"\x1aE\xdf\xa3webm-audio",
    )

    result = provider.transcribe_sealed_audio(request)

    assert result.segments[0].language == "ru"


def test_deepgram_adapter_rejects_requests_over_cost_budget_before_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_deepgram_payload())

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_cost_usd_per_operation=0.001,
        estimated_cost_usd_per_megabyte=1.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTerminalError, match="STT_COST_LIMIT_EXCEEDED"):
        provider.transcribe_sealed_audio(_request(b"\x1aE\xdf\xa3" + b"x" * 2_000))

    assert calls == 0


def test_deepgram_adapter_rejects_missing_audio_before_network() -> None:
    provider = DeepgramAccurateStt(api_key="secret-test-key")

    with pytest.raises(ProviderTerminalError, match="STT_AUDIO_MISSING"):
        provider.transcribe_sealed_audio(_request(b""))


def _utterance(
    transcript: str,
    start: float,
    end: float,
    confidence: float,
    word_languages: tuple[str, ...],
) -> dict[str, object]:
    return {
        "transcript": transcript,
        "start": start,
        "end": end,
        "confidence": confidence,
        "words": [
            {
                "word": f"w{index}",
                "start": start + index * 0.1,
                "end": start + index * 0.1 + 0.1,
                "confidence": 0.9,
                "punctuated_word": f"W{index}",
                "language": language,
            }
            for index, language in enumerate(word_languages)
        ],
    }


def _deepgram_utterances_payload(
    utterances: list[dict[str, object]] | None = None,
    *,
    duration: float | None = 12.0,
) -> dict[str, object]:
    payload = _deepgram_payload(
        transcript="Починить BrainBuddy Buy milk Позвонить Анне",
        duration=duration,
    )
    if utterances is None:
        utterances = [
            _utterance("Починить BrainBuddy", 0.5, 2.0, 0.98, ("ru", "ru", "en")),
            _utterance("Buy milk and bread", 2.5, 4.0, 0.97, ("en", "en")),
            _utterance("Позвонить Анне", 4.5, 6.0, 0.99, ("ru",)),
        ]
    payload["results"]["utterances"] = utterances  # type: ignore[index]
    return payload


def test_deepgram_adapter_requests_utterance_segmentation() -> None:
    captured_url = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_url
        captured_url = str(request.url)
        return httpx.Response(200, json=_deepgram_utterances_payload())

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    provider.transcribe_sealed_audio(_request())

    assert "utterances=true" in captured_url


def test_deepgram_adapter_emits_one_segment_per_utterance() -> None:
    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=_deepgram_utterances_payload())
        ),
    )

    result = provider.transcribe_sealed_audio(_request())

    segments = result.segments
    assert [segment.text for segment in segments] == [
        "Починить BrainBuddy",
        "Buy milk and bread",
        "Позвонить Анне",
    ]
    assert [segment.sequence for segment in segments] == [1, 2, 3]
    assert all(segment.provider_role == "accurate" for segment in segments)
    assert (segments[0].start_ms, segments[0].end_ms) == (500, 2000)
    assert (segments[1].start_ms, segments[1].end_ms) == (2500, 4000)
    assert (segments[2].start_ms, segments[2].end_ms) == (4500, 6000)
    assert segments[0].language == "en,ru"
    assert segments[1].language == "en"
    assert segments[2].language == "ru"
    assert segments[0].confidence == pytest.approx(0.98)
    assert all(segment.supersedes_segment_ids == ["preview_1"] for segment in segments)
    assert len({segment.id for segment in segments}) == 3


def test_deepgram_adapter_skips_blank_utterances_but_keeps_valid_ones() -> None:
    utterances = [
        _utterance("First task", 0.0, 1.0, 0.95, ("en",)),
        {"transcript": "   ", "start": 1.0, "end": 2.0, "confidence": 0.5, "words": []},
        _utterance("Second task", 2.0, 3.0, 0.96, ("en",)),
    ]
    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json=_deepgram_utterances_payload(utterances)
            )
        ),
    )

    result = provider.transcribe_sealed_audio(_request())

    assert [segment.text for segment in result.segments] == [
        "First task",
        "Second task",
    ]
    assert [segment.sequence for segment in result.segments] == [1, 2]


def test_deepgram_adapter_derives_utterance_timings_defensively() -> None:
    # A degenerate utterance whose end is not after its start must still yield a
    # positive audio span rather than failing the whole (good) transcription.
    utterances = [_utterance("Only task", 3.0, 3.0, 0.9, ("en", "en"))]
    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json=_deepgram_utterances_payload(utterances)
            )
        ),
    )

    result = provider.transcribe_sealed_audio(_request())

    segment = result.segments[0]
    assert segment.start_ms == 3000
    assert segment.end_ms == 3000 + 2 * 500


@pytest.mark.parametrize("utterances", [[], None], ids=["empty", "all-blank"])
def test_deepgram_adapter_falls_back_to_channel_transcript_without_utterances(
    utterances: list[dict[str, object]] | None,
) -> None:
    if utterances is None:
        utterances = [
            {
                "transcript": "  ",
                "start": 0.0,
                "end": 1.0,
                "confidence": 0.5,
                "words": [],
            }
        ]
    payload = _deepgram_utterances_payload(utterances, duration=249.0)
    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=payload)
        ),
    )

    result = provider.transcribe_sealed_audio(_request())

    assert len(result.segments) == 1
    assert result.segments[0].sequence == 1
    assert result.segments[0].text == "Починить BrainBuddy Buy milk Позвонить Анне"
    assert result.segments[0].start_ms == 0
    assert result.segments[0].end_ms == 249_000
