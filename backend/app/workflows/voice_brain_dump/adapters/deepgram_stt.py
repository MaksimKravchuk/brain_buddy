"""Deepgram Nova-3 multilingual accurate-STT adapter over sealed original audio.

Sealed audio bytes travel as the raw binary request body (Deepgram's own audio
API contract), never as ``bytes.decode("utf-8")`` text and never wrapped in a
multipart form. This is the authorized MVP default for the ``accurate_stt``
role; see ``backend/app/core/config.py`` for the allow-listed provider/model
authorization and ADR-0002 for the port contract.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import httpx

from app.exceptions import ProviderRetryableError, ProviderTerminalError
from app.workflows.voice_brain_dump.domain import TranscriptHypothesis
from app.workflows.voice_brain_dump.providers import (
    AccurateSttRequest,
    SttResult,
    redacted_provider_usage,
    sniff_audio_container,
)

DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"
_RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
_LANGUAGE_ALIASES = {
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "ru": "ru",
    "ru-ru": "ru",
}


def _deepgram_language_param(language_hints: Sequence[str]) -> str:
    """Nova-3 multilingual code-switch mode unless exactly one hint is declared."""

    normalized = {
        _LANGUAGE_ALIASES.get(hint.strip().casefold(), hint.strip().split("-", 1)[0].casefold())
        for hint in language_hints
        if hint.strip()
    }
    if len(normalized) == 1:
        return next(iter(normalized))
    return "multi"


@dataclass(slots=True)
class DeepgramAccurateStt:
    """Transcribe sealed audio with Deepgram without logging provider payloads."""

    api_key: str = field(repr=False)
    model: str = "nova-3"
    timeout_seconds: float = 60.0
    max_retries: int = 2
    retry_backoff_seconds: Sequence[float] = (1.0, 2.0)
    max_cost_usd_per_operation: float = 0.50
    estimated_cost_usd_per_megabyte: float = 0.01
    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = time.sleep
    provider_name: str = field(default="deepgram", init=False)
    requires_external_processing: bool = field(default=True, init=False)

    def transcribe_sealed_audio(self, request: AccurateSttRequest) -> SttResult:
        if not request.sealed_audio:
            raise ProviderTerminalError("STT_AUDIO_MISSING")
        # Conservatively scaled by the adapter's own bounded retry budget: a
        # single logical call may itself cost the provider once per internal
        # transport attempt, so both the admission check and any recorded
        # spend (success or failure) must assume the worst case.
        estimated_cost = (
            (len(request.sealed_audio) / 1_000_000)
            * self.estimated_cost_usd_per_megabyte
            * (self.max_retries + 1)
        )
        if estimated_cost > self.max_cost_usd_per_operation:
            raise ProviderTerminalError("STT_COST_LIMIT_EXCEEDED")

        try:
            response = self._post_with_retries(request)
            payload = response.json()
        except (ProviderRetryableError, ProviderTerminalError) as exc:
            exc.estimated_cost_usd = estimated_cost
            raise
        except ValueError as exc:
            wrapped = ProviderTerminalError("STT_PROVIDER_INVALID_RESPONSE")
            wrapped.estimated_cost_usd = estimated_cost
            raise wrapped from exc

        text = self._extract_transcript(payload)
        if text is None:
            wrapped = ProviderTerminalError("STT_PROVIDER_INVALID_RESPONSE")
            wrapped.estimated_cost_usd = estimated_cost
            raise wrapped
        normalized_text = " ".join(text.split())
        if not normalized_text:
            wrapped = ProviderTerminalError("STT_PROVIDER_INVALID_RESPONSE")
            wrapped.estimated_cost_usd = estimated_cost
            raise wrapped
        language = ",".join(request.language_hints) or None
        segment = TranscriptHypothesis(
            id=self._stable_segment_id(request, normalized_text),
            sequence=1,
            start_ms=0,
            end_ms=max(1, len(normalized_text.split()) * 500),
            text=normalized_text,
            stability="stable",
            provider_role="accurate",
            language=language,
            model=self.model,
            supersedes_segment_ids=request.supersedes_segment_ids,
        )
        usage = {}
        metadata = payload.get("metadata") if isinstance(payload, dict) else None
        if isinstance(metadata, dict) and isinstance(
            metadata.get("duration"), int | float
        ):
            usage = {"duration_seconds": metadata["duration"]}
        return SttResult(
            role="accurate",
            provider=self.provider_name,
            input_hash=hashlib.sha256(request.sealed_audio).hexdigest(),
            segments=[segment],
            estimated_cost_usd=estimated_cost,
            cost_estimate_basis="audio_bytes_proxy",
            actual_cost_usd=None,
            provider_usage=redacted_provider_usage(usage),
        )

    @staticmethod
    def _extract_transcript(payload: object) -> str | None:
        if not isinstance(payload, dict):
            return None
        try:
            channels = payload["results"]["channels"]
            alternatives = channels[0]["alternatives"]
            transcript = alternatives[0]["transcript"]
        except (KeyError, IndexError, TypeError):
            return None
        return transcript if isinstance(transcript, str) else None

    def _post_with_retries(self, request: AccurateSttRequest) -> httpx.Response:
        _filename, content_type = sniff_audio_container(request.sealed_audio)
        params = self._query_params(request)
        attempt = 0
        while True:
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = client.post(
                        DEEPGRAM_LISTEN_URL,
                        params=params,
                        headers={
                            "Authorization": f"Token {self.api_key}",
                            "Content-Type": content_type,
                        },
                        # Deepgram's audio API consumes the raw sealed bytes
                        # as the request body -- never multipart, never text.
                        content=request.sealed_audio,
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.max_retries:
                    raise ProviderRetryableError("STT_PROVIDER_UNAVAILABLE") from exc
                self._backoff(attempt)
                attempt += 1
                continue

            if response.status_code < 400:
                return response
            if response.status_code in _RETRYABLE_STATUS_CODES:
                if attempt >= self.max_retries:
                    raise ProviderRetryableError("STT_PROVIDER_UNAVAILABLE")
                self._backoff(attempt)
                attempt += 1
                continue
            if response.status_code in {401, 403}:
                raise ProviderTerminalError("STT_PROVIDER_AUTHENTICATION_FAILED")
            if response.status_code == 413:
                raise ProviderTerminalError("STT_AUDIO_TOO_LARGE")
            raise ProviderTerminalError("STT_PROVIDER_REJECTED_REQUEST")

    def _query_params(
        self, request: AccurateSttRequest
    ) -> list[tuple[str, str | int | float | bool | None]]:
        params: list[tuple[str, str | int | float | bool | None]] = [
            ("model", self.model),
            ("language", _deepgram_language_param(request.language_hints)),
            ("smart_format", "true"),
        ]
        params.extend(("keyterm", term) for term in request.vocabulary)
        return params

    def _backoff(self, attempt: int) -> None:
        if not self.retry_backoff_seconds:
            return
        index = min(attempt, len(self.retry_backoff_seconds) - 1)
        self.sleep(float(self.retry_backoff_seconds[index]))

    def _stable_segment_id(self, request: AccurateSttRequest, text: str) -> str:
        digest = hashlib.sha256(
            "|".join((request.operation_id, request.media_ref, self.model, text)).encode(
                "utf-8"
            )
        ).hexdigest()[:12]
        return f"accurate_{digest}"
