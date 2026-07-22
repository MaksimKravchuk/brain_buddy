"""Contract tests for credentialed Voice Brain Dump accurate-STT adapters."""

from __future__ import annotations

import dataclasses
import json

import httpx
import pytest

from app.exceptions import ProviderRetryableError, ProviderTerminalError
from app.workflows.voice_brain_dump.adapters.openai_stt import OpenAiAccurateStt
from app.workflows.voice_brain_dump.providers import (
    AccurateSttRequest,
    DisabledAccurateStt,
)


class _LyingStr(str):
    """A ``str`` subclass whose ``__eq__``/``__ne__`` always lie.

    Used to prove the adapter's authorization check cannot be satisfied by
    matching ``==``/``!=`` alone: it must reject any non-exact-``str`` type
    outright, because a subclass can report equality with the authorized
    constant while its actual value -- what httpx would literally put on the
    wire -- is something else entirely.
    """

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    def __hash__(self) -> int:
        return str.__hash__(self)


def _request(audio: bytes = b"\x1aE\xdf\xa3webm-audio") -> AccurateSttRequest:
    return AccurateSttRequest(
        operation_id="operation_1",
        media_ref="media_1",
        language_hints=["ru", "en"],
        vocabulary=["BrainBuddy", "production smoke"],
        supersedes_segment_ids=["preview_1"],
        sealed_audio=audio,
    )


def test_openai_adapter_is_not_exported_from_the_production_adapters_package() -> None:
    """ADR-0002 authorizes only Deepgram Nova-3 for accurate STT. OpenAI's
    accurate-STT adapter must not be part of the ``adapters`` package's
    production-facing surface -- it is reachable only via its own submodule
    for narrowly-scoped, explicit test support."""

    import app.workflows.voice_brain_dump.adapters as adapters_package

    assert "OpenAiAccurateStt" not in adapters_package.__all__
    assert not hasattr(adapters_package, "OpenAiAccurateStt")


def test_openai_adapter_direct_construction_without_test_acknowledgement_is_unusable() -> (
    None
):
    """Direct construction of ``OpenAiAccurateStt`` -- bypassing the
    container, which never wires this adapter into production -- must never
    be able to transmit a private-audio request, regardless of what
    model/endpoint/credentials are supplied. Omitting the explicit test-only
    acknowledgment must fail closed at construction, before any call."""

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    with pytest.raises(ValueError, match="test-only"):
        OpenAiAccurateStt(
            api_key="secret-test-key",
            transport=httpx.MockTransport(handler),
        )

    assert calls == 0


def test_openai_adapter_rejects_an_unapproved_model_before_any_transport_call() -> None:
    """The test-only adapter must not turn explicit test acknowledgement into
    a caller-selectable model escape hatch. Even test support uses one exact
    built-in model, so a direct fable-tier construction cannot transmit audio.
    """

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    with pytest.raises(TypeError, match="unexpected keyword argument 'model'"):
        OpenAiAccurateStt(
            acknowledge_test_only_direct_construction=True,
            api_key="secret-test-key",
            model="gpt-5.6-fable",
            transport=httpx.MockTransport(handler),
        )

    assert calls == 0


@pytest.mark.parametrize("attempted_value", [1, "True", "true", 1.0, "yes"])
def test_openai_adapter_rejects_a_non_exact_bool_test_acknowledgement(
    attempted_value: object,
) -> None:
    """A deceptive non-``bool`` truthy value must not satisfy the explicit
    test-only acknowledgment: only the exact ``True`` singleton, of exact
    type ``bool``, is accepted."""

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    with pytest.raises(ValueError, match="test-only"):
        OpenAiAccurateStt(
            api_key="secret-test-key",
            acknowledge_test_only_direct_construction=attempted_value,  # type: ignore[arg-type]
            transport=httpx.MockTransport(handler),
        )

    assert calls == 0


@pytest.mark.parametrize(
    ("field_name", "attempted_value"),
    [
        ("model", "gpt-5.6-fable"),
        ("provider_name", "other-provider"),
        ("endpoint", "https://evil.example/v1/audio/transcriptions"),
        ("acknowledge_test_only_direct_construction", False),
    ],
)
def test_openai_adapter_identity_fields_cannot_be_reassigned_after_construction(
    field_name: str, attempted_value: object
) -> None:
    """Identity fields are frozen: even a manually-constructed adapter
    instance handed to other code cannot have its authorized provider/
    endpoint/test-acknowledgment swapped out from under it before a later
    call transmits."""

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    provider = OpenAiAccurateStt(
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(provider, field_name, attempted_value)

    assert calls == 0
    assert provider.provider_name == "openai"
    assert provider.acknowledge_test_only_direct_construction is True


@pytest.mark.parametrize("field_name", ["model", "provider_name", "endpoint"])
def test_openai_adapter_rejects_a_lying_str_subclass_forced_onto_identity(
    field_name: str,
) -> None:
    """Even if ``frozen=True`` is bypassed via ``object.__setattr__`` -- e.g.
    by other code holding a reference to a constructed instance -- a spoofed
    provider/endpoint must never reach the wire. The re-check immediately
    before every transmit must reject a deceptive ``str`` subclass whose
    overridden equality lies about matching the authorized constant."""

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    provider = OpenAiAccurateStt(
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    spoofed = _LyingStr("attacker-controlled-value")
    assert spoofed == getattr(provider, field_name)  # the lie
    object.__setattr__(provider, field_name, spoofed)
    error_label = "provider" if field_name == "provider_name" else field_name

    with pytest.raises(ValueError, match=f"Unauthorized OpenAI accurate STT {error_label}"):
        provider.transcribe_sealed_audio(_request())

    assert calls == 0


def test_openai_adapter_object_setattr_mutation_of_test_acknowledgement_yields_zero_calls() -> (
    None
):
    """A legitimately test-acknowledged instance whose acknowledgment is
    flipped off via ``object.__setattr__`` after construction (bypassing
    ``frozen=True``) must still be rejected before any transmit."""

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    provider = OpenAiAccurateStt(
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )
    object.__setattr__(provider, "acknowledge_test_only_direct_construction", False)

    with pytest.raises(ValueError, match="test-only"):
        provider.transcribe_sealed_audio(_request())

    assert calls == 0


def test_openai_adapter_mutation_during_retry_backoff_stops_further_transmission() -> None:
    """A mutation that happens *between* retry attempts -- not just before
    the first call -- must still be caught by the re-check at the top of the
    retry loop, so a spoofed identity that only becomes wrong mid-flight can
    never place a second (or later) transmit."""

    calls = 0
    provider_holder: list[OpenAiAccurateStt] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        # Simulate an identity compromise that occurs concurrently with the
        # first attempt's retryable failure, before the adapter's own retry
        # loop re-checks authorization ahead of its next attempt.
        object.__setattr__(provider_holder[0], "endpoint", "https://evil.example/v1")
        return httpx.Response(503)

    provider = OpenAiAccurateStt(
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
        max_retries=2,
        retry_backoff_seconds=(0.0, 0.0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _delay: None,
    )
    provider_holder.append(provider)

    # The retry loop's authorization re-check raises inside the same
    # ``try`` block that maps a malformed/unparseable provider response to
    # ``STT_PROVIDER_INVALID_RESPONSE``, so the authorization ``ValueError``
    # surfaces wrapped as a ``ProviderTerminalError`` with the original
    # ``ValueError`` chained as its cause. The security-relevant invariant is
    # that no second transmit ever happens, not the wrapper's exact type.
    with pytest.raises(ProviderTerminalError, match="STT_PROVIDER_INVALID_RESPONSE") as caught:
        provider.transcribe_sealed_audio(_request())

    assert isinstance(caught.value.__cause__, ValueError)
    assert "Unauthorized OpenAI accurate STT endpoint" in str(caught.value.__cause__)
    assert calls == 1


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
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
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
    assert result.cost_estimate_basis == "audio_bytes_proxy"
    assert result.actual_cost_usd is None
    assert result.provider_usage == {
        "input_tokens": 123,
        "output_tokens": 17,
        "total_tokens": 140,
    }


def test_openai_adapter_repr_redacts_api_key() -> None:
    provider = OpenAiAccurateStt(
        acknowledge_test_only_direct_construction=True, api_key="sensitive-test-key"
    )

    assert "sensitive-test-key" not in repr(provider)


@pytest.mark.parametrize(
    ("audio", "expected_filename", "expected_mime"),
    [
        (b"\x1aE\xdf\xa3webm-audio", b'recording.webm', b"audio/webm"),
        (b"OggS\x00opus-audio", b'recording.ogg', b"audio/ogg"),
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
        acknowledge_test_only_direct_construction=True,
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
        acknowledge_test_only_direct_construction=True,
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
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
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
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
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
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
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
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
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
    provider = OpenAiAccurateStt(
        acknowledge_test_only_direct_construction=True, api_key="secret-test-key"
    )

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
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
        max_retries=0,
        transport=httpx.MockTransport(lambda _request: response),
    )

    with pytest.raises(ProviderTerminalError, match=expected_code):
        provider.transcribe_sealed_audio(_request())


def test_openai_adapter_exhausts_retryable_http_status_without_backoff() -> None:
    provider = OpenAiAccurateStt(
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
        max_retries=0,
        retry_backoff_seconds=(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(429)),
    )

    with pytest.raises(ProviderRetryableError, match="STT_PROVIDER_UNAVAILABLE"):
        provider.transcribe_sealed_audio(_request())


def test_openai_adapter_tags_retryable_failure_with_conservative_estimated_cost() -> None:
    """A transport-retryable failure still made real, billable attempts; the
    operation-wide cost cap must see that spend, not silently record zero
    just because the call ultimately failed. The estimate is conservatively
    scaled by the adapter's own bounded retry budget, since a single logical
    call may itself cost the provider once per internal attempt."""

    audio = _request().sealed_audio
    provider = OpenAiAccurateStt(
        acknowledge_test_only_direct_construction=True,
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


def test_openai_adapter_tags_terminal_failure_with_estimated_cost_after_a_real_call() -> None:
    provider = OpenAiAccurateStt(
        acknowledge_test_only_direct_construction=True,
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
        acknowledge_test_only_direct_construction=True,
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
        acknowledge_test_only_direct_construction=True,
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
        acknowledge_test_only_direct_construction=True,
        api_key="secret-test-key",
        max_retries=1,
        retry_backoff_seconds=(),
        transport=httpx.MockTransport(handler),
    )

    result = provider.transcribe_sealed_audio(_request())

    assert attempts == 2
    assert result.segments[0].text == "Recovered"
