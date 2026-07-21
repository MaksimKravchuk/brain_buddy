"""Contract tests for the Deepgram Nova-3 multilingual accurate-STT adapter."""

from __future__ import annotations

import json

import httpx
import pytest

from app.exceptions import ProviderRetryableError, ProviderTerminalError
from app.workflows.voice_brain_dump.adapters.deepgram_stt import DeepgramAccurateStt
from app.workflows.voice_brain_dump.providers import AccurateSttRequest


def _request(
    audio: bytes = b"\x1aE\xdf\xa3webm-audio",
    language_hints: list[str] | None = None,
) -> AccurateSttRequest:
    return AccurateSttRequest(
        operation_id="operation_1",
        media_ref="media_1",
        language_hints=language_hints if language_hints is not None else ["ru", "en"],
        vocabulary=["BrainBuddy", "production smoke"],
        supersedes_segment_ids=["preview_1"],
        sealed_audio=audio,
    )


def _success_response(transcript: str = "Починить BrainBuddy") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "results": {"channels": [{"alternatives": [{"transcript": transcript}]}]},
            "metadata": {"duration": 12.5},
        },
    )


def test_deepgram_adapter_sends_sealed_binary_audio_never_utf8_decoded() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers["Content-Type"]
        captured["body"] = request.read()
        captured["params"] = dict(request.url.params)
        return _success_response()

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        model="nova-3",
        timeout_seconds=12,
        max_retries=0,
        retry_backoff_seconds=(),
        transport=httpx.MockTransport(handler),
    )

    result = provider.transcribe_sealed_audio(_request())

    assert captured["body"] == b"\x1aE\xdf\xa3webm-audio"
    assert captured["authorization"] == "Token secret-test-key"
    assert captured["content_type"] == "audio/webm"
    assert captured["params"]["model"] == "nova-3"
    assert captured["params"]["language"] == "multi"
    assert result.provider == "deepgram"
    assert result.segments[0].model == "nova-3"
    assert result.segments[0].text == "Починить BrainBuddy"
    assert result.segments[0].supersedes_segment_ids == ["preview_1"]
    assert result.provider_usage == {"duration_seconds": 12.5}


def test_deepgram_adapter_sends_keyterms_for_vocabulary() -> None:
    captured_params: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_params
        captured_params = list(request.url.params.multi_items())
        return _success_response()

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    provider.transcribe_sealed_audio(_request())

    keyterms = [value for key, value in captured_params if key == "keyterm"]
    assert keyterms == ["BrainBuddy", "production smoke"]


def test_deepgram_adapter_uses_single_declared_language_hint() -> None:
    captured_params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_params
        captured_params = dict(request.url.params)
        return _success_response()

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    provider.transcribe_sealed_audio(_request(language_hints=["ru"]))

    assert captured_params["language"] == "ru"


def test_deepgram_adapter_rejects_unknown_binary_before_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response()

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTerminalError, match="STT_AUDIO_FORMAT_UNSUPPORTED"):
        provider.transcribe_sealed_audio(_request(b"unknown-binary"))

    assert calls == 0


def test_deepgram_adapter_rejects_missing_audio_before_network() -> None:
    provider = DeepgramAccurateStt(api_key="secret-test-key")

    with pytest.raises(ProviderTerminalError, match="STT_AUDIO_MISSING"):
        provider.transcribe_sealed_audio(_request(b""))


def test_deepgram_adapter_retries_only_retryable_failures_with_a_bounded_budget() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429, json={"err_msg": "rate limited secret transcript"})
        return _success_response("Готово")

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        timeout_seconds=5,
        max_retries=2,
        retry_backoff_seconds=(0.1, 0.2),
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )

    result = provider.transcribe_sealed_audio(_request())

    assert result.segments[0].text == "Готово"
    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_deepgram_adapter_redacts_provider_payloads_and_credentials_from_errors() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            content=json.dumps({"err_msg": "bad secret-test-key and transcript"}),
        )

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTerminalError) as caught:
        provider.transcribe_sealed_audio(_request())

    assert str(caught.value) == "STT_PROVIDER_AUTHENTICATION_FAILED"
    assert "secret-test-key" not in str(caught.value)
    assert "transcript" not in str(caught.value)


def test_deepgram_adapter_repr_redacts_api_key() -> None:
    provider = DeepgramAccurateStt(api_key="sensitive-test-key")

    assert "sensitive-test-key" not in repr(provider)


def test_deepgram_adapter_rejects_requests_over_cost_budget_before_network() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _success_response()

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        retry_backoff_seconds=(),
        max_cost_usd_per_operation=0.001,
        estimated_cost_usd_per_megabyte=1.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTerminalError, match="STT_COST_LIMIT_EXCEEDED"):
        provider.transcribe_sealed_audio(_request(b"x" * 2_000))

    assert calls == 0


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (httpx.Response(200, content=b"not-json"), "STT_PROVIDER_INVALID_RESPONSE"),
        (httpx.Response(200, json={"results": {}}), "STT_PROVIDER_INVALID_RESPONSE"),
        (httpx.Response(200, json={"results": {"channels": [{"alternatives": [{"transcript": "  "}]}]}}), "STT_PROVIDER_INVALID_RESPONSE"),
        (httpx.Response(413), "STT_AUDIO_TOO_LARGE"),
        (httpx.Response(422), "STT_PROVIDER_REJECTED_REQUEST"),
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


def test_deepgram_adapter_exhausts_transport_retries_as_retryable_error() -> None:
    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        timeout_seconds=0.1,
        max_retries=1,
        retry_backoff_seconds=(0.0,),
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout", request=request))
        ),
        sleep=lambda _delay: None,
    )

    with pytest.raises(ProviderRetryableError, match="STT_PROVIDER_UNAVAILABLE"):
        provider.transcribe_sealed_audio(_request())


def test_deepgram_adapter_tags_retryable_failure_with_conservative_estimated_cost() -> None:
    audio = _request().sealed_audio
    provider = DeepgramAccurateStt(
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
