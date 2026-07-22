"""Contract tests for the Deepgram Nova-3 multilingual accurate-STT adapter."""

from __future__ import annotations

import json

import httpx
import pytest

from app.exceptions import ProviderRetryableError, ProviderTerminalError
from app.workflows.voice_brain_dump.adapters.deepgram_stt import DeepgramAccurateStt
from app.workflows.voice_brain_dump.providers import (
    AccurateSttRequest,
    sniff_audio_container,
)


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


@pytest.mark.parametrize(
    "unauthorized_model", ["nova-3-medical", "nova-3-general", "nova-2", ""]
)
def test_deepgram_adapter_rejects_any_nova_3_variant_at_construction(
    unauthorized_model: str,
) -> None:
    """Defense in depth beyond the container's allow-list: even a direct,
    manually-constructed adapter instance must never be able to send
    credentials/audio to Deepgram under an unmeasured Nova-3 variant."""

    with pytest.raises(ValueError, match="Unauthorized Deepgram accurate STT model"):
        DeepgramAccurateStt(api_key="secret-test-key", model=unauthorized_model)


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


def test_deepgram_adapter_never_sends_vocabulary_keyterms_in_the_request_url() -> None:
    """User-supplied vocabulary must never be reflected into the third-party
    request URL: query strings are far more likely than a request body to be
    captured by intermediary proxy/CDN/access logs outside this app's own
    (already-capped) logging, so keyterm boosting cannot be sent this way."""

    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return _success_response()

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    sentinel_vocabulary = ["sentinel-vocab-CanaryWord447", "another canary term"]
    request = AccurateSttRequest(
        operation_id="operation_1",
        media_ref="media_1",
        language_hints=["ru", "en"],
        vocabulary=sentinel_vocabulary,
        supersedes_segment_ids=["preview_1"],
        sealed_audio=b"\x1aE\xdf\xa3webm-audio",
    )

    provider.transcribe_sealed_audio(request)

    assert len(captured_urls) == 1
    url = captured_urls[0]
    assert "keyterm" not in url
    for term in sentinel_vocabulary:
        assert term not in url


def test_deepgram_adapter_never_logs_provider_request_details_at_production_log_level() -> (
    None
):
    """Regression: httpx's own logger unconditionally emits the full request
    URL -- including Deepgram's query-parameter vocabulary/keyterms -- as an
    INFO log line (see ``httpx._client``). At production's default INFO app
    log level this would otherwise leak provider URLs, vocabulary, and
    language hints into ordinary logs. Capping the httpx/httpcore loggers
    below INFO (``app.core.logging.build_logging_dict``) must mean no such
    record is ever *created*, not merely filtered by a downstream handler."""

    import logging.config

    from app.core.logging import build_logging_dict

    logging.config.dictConfig(build_logging_dict("INFO"))

    captured_records: list[logging.LogRecord] = []

    class _CollectingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured_records.append(record)

    httpx_logger = logging.getLogger("httpx")
    collector = _CollectingHandler(level=logging.DEBUG)
    httpx_logger.addHandler(collector)
    try:

        def handler(request: httpx.Request) -> httpx.Response:
            return _success_response("Секретная задача про BrainBuddy")

        provider = DeepgramAccurateStt(
            api_key="top-secret-deepgram-key",
            model="nova-3",
            timeout_seconds=12,
            max_retries=0,
            retry_backoff_seconds=(),
            transport=httpx.MockTransport(handler),
        )

        result = provider.transcribe_sealed_audio(
            _request(language_hints=["ru", "en"])
        )
    finally:
        httpx_logger.removeHandler(collector)

    assert result.segments[0].text
    assert captured_records == []


def test_deepgram_adapter_never_sends_language_hints_in_the_request_url() -> None:
    """User-supplied language hints must never be reflected into the
    third-party request URL: only the fixed Nova-3 multilingual code-switch
    control is an allowable, non-private query value regardless of what
    hints the caller declares."""

    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        return _success_response()

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    sentinel_language = "sentinel-lang-xyz"

    provider.transcribe_sealed_audio(_request(language_hints=[sentinel_language]))

    assert len(captured_urls) == 1
    url = captured_urls[0]
    assert sentinel_language not in url
    assert "sentinel" not in url
    parsed_params = dict(httpx.URL(url).params)
    assert parsed_params == {"model": "nova-3", "language": "multi", "smart_format": "true"}


def test_deepgram_adapter_sends_admitted_ogg_as_ogg_content_type() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers["Content-Type"]
        captured["body"] = request.read()
        return _success_response()

    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    ogg_audio = b"OggS\x00opus-audio"

    provider.transcribe_sealed_audio(_request(ogg_audio))

    assert captured["content_type"] == "audio/ogg"
    assert captured["body"] == ogg_audio


def test_deepgram_adapter_sends_mp4_with_a_leading_free_box() -> None:
    """A valid ISO-BMFF leading ``free`` box must not strand admitted MP4 audio.

    Media admission accepts this shape via PyAV. The egress sniffer therefore
    has to recognize it too, so sealing cannot make the recording impossible
    to send to the authorized accurate-STT provider.
    """

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers["Content-Type"]
        captured["body"] = request.read()
        return _success_response()

    audio = b"\x00\x00\x00\x08free\x00\x00\x00\x10ftypM4A m4a-audio"
    provider = DeepgramAccurateStt(
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    provider.transcribe_sealed_audio(_request(audio))

    assert captured["content_type"] == "audio/mp4"
    assert captured["body"] == audio


@pytest.mark.parametrize(
    "audio",
    [
        b"\x00\x00\x00\x01free",
        b"\x00\x00\x00\x00free",
        b"\x00\x00\x00\x07free",
        b"\x00\x00\x00\x08free" * 8,
    ],
)
def test_mp4_leading_box_sniffer_rejects_truncated_or_invalid_box_layout(audio: bytes) -> None:
    with pytest.raises(ProviderTerminalError, match="STT_AUDIO_FORMAT_UNSUPPORTED"):
        sniff_audio_container(audio)


def test_mp4_leading_box_sniffer_supports_an_extended_size_box() -> None:
    audio = (
        b"\x00\x00\x00\x01free"
        + (16).to_bytes(8, "big")
        + b"\x00\x00\x00\x10ftypM4A "
    )

    assert sniff_audio_container(audio) == ("recording.m4a", "audio/mp4")


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
