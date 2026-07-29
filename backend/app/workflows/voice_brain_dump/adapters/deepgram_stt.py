"""Deepgram accurate-STT adapter over sealed original audio."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import httpx

from app.exceptions import ProviderRetryableError, ProviderTerminalError
from app.workflows.voice_brain_dump.adapters.openai_stt import _audio_multipart_metadata
from app.workflows.voice_brain_dump.domain import TranscriptHypothesis
from app.workflows.voice_brain_dump.providers import (
    AccurateSttRequest,
    SttResult,
    redacted_provider_usage,
)

DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class DeepgramAccurateStt:
    """Transcribe sealed audio with Deepgram without logging provider payloads."""

    api_key: str = field(repr=False)
    model: str = "nova-3"
    timeout_seconds: float = 180.0
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
        # spend (success or failure) must assume the worst case, not just the
        # first attempt.
        estimated_cost = (
            (len(request.sealed_audio) / 1_000_000)
            * self.estimated_cost_usd_per_megabyte
            * (self.max_retries + 1)
        )
        if estimated_cost > self.max_cost_usd_per_operation:
            raise ProviderTerminalError("STT_COST_LIMIT_EXCEEDED")

        language_param = self._language_param(request)
        try:
            response = self._post_with_retries(request, language_param)
            payload = response.json()
        except (ProviderRetryableError, ProviderTerminalError) as exc:
            exc.estimated_cost_usd = estimated_cost
            raise
        except ValueError as exc:
            wrapped = ProviderTerminalError("STT_PROVIDER_INVALID_RESPONSE")
            wrapped.estimated_cost_usd = estimated_cost
            raise wrapped from exc

        duration_seconds = _optional_float(_metadata_duration(payload))
        # Utterance-level segments keep adjacent intents separate for the
        # reconciler; the single-blob channel transcript is only a fallback for
        # when the optional ``utterances`` array is missing or unusable.
        segments = self._segments_from_utterances(
            request, _utterances(payload), language_param
        )
        if not segments:
            fallback = self._channel_segment_or_none(
                request, payload, language_param, duration_seconds
            )
            if fallback is None:
                wrapped = ProviderTerminalError("STT_PROVIDER_INVALID_RESPONSE")
                wrapped.estimated_cost_usd = estimated_cost
                raise wrapped
            segments = [fallback]

        usage = (
            {"duration_seconds": duration_seconds}
            if duration_seconds is not None
            else None
        )
        return SttResult(
            role="accurate",
            provider=self.provider_name,
            input_hash=hashlib.sha256(request.sealed_audio).hexdigest(),
            segments=segments,
            estimated_cost_usd=estimated_cost,
            cost_estimate_basis="audio_bytes_proxy",
            actual_cost_usd=None,
            provider_usage=redacted_provider_usage(usage),
        )

    def _segments_from_utterances(
        self,
        request: AccurateSttRequest,
        utterances: list[dict[str, object]],
        language_param: str,
    ) -> list[TranscriptHypothesis]:
        segments: list[TranscriptHypothesis] = []
        for utterance in utterances:
            text = utterance.get("transcript")
            if not isinstance(text, str) or not text.strip():
                continue
            normalized_text = " ".join(text.split())
            sequence = len(segments) + 1
            start_ms = _to_ms(utterance.get("start"), default=0)
            end_ms = _to_ms(utterance.get("end"), default=0)
            if end_ms <= start_ms:
                end_ms = start_ms + max(1, len(normalized_text.split()) * 500)
            segments.append(
                TranscriptHypothesis(
                    id=self._stable_segment_id(
                        request, normalized_text, index=sequence
                    ),
                    sequence=sequence,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=normalized_text,
                    stability="stable",
                    provider_role="accurate",
                    confidence=_optional_float(utterance.get("confidence")),
                    language=_distinct_word_languages(utterance) or language_param,
                    model=self.model,
                    supersedes_segment_ids=request.supersedes_segment_ids,
                )
            )
        return segments

    def _channel_segment_or_none(
        self,
        request: AccurateSttRequest,
        payload: object,
        language_param: str,
        duration_seconds: float | None,
    ) -> TranscriptHypothesis | None:
        alternative = _first_alternative(payload)
        text = alternative.get("transcript") if alternative is not None else None
        if alternative is None or not isinstance(text, str) or not text.strip():
            return None
        normalized_text = " ".join(text.split())
        if duration_seconds is not None and duration_seconds > 0:
            end_ms = max(1, int(duration_seconds * 1000))
        else:
            end_ms = max(1, len(normalized_text.split()) * 500)
        return TranscriptHypothesis(
            id=self._stable_segment_id(request, normalized_text),
            sequence=1,
            start_ms=0,
            end_ms=end_ms,
            text=normalized_text,
            stability="stable",
            provider_role="accurate",
            confidence=_optional_float(alternative.get("confidence")),
            language=_distinct_word_languages(alternative) or language_param,
            model=self.model,
            supersedes_segment_ids=request.supersedes_segment_ids,
        )

    def _post_with_retries(
        self, request: AccurateSttRequest, language_param: str
    ) -> httpx.Response:
        # Content-Type is sniffed from the container signature, never trusted
        # from upload metadata; unknown formats fail closed before the network.
        content_type = _audio_multipart_metadata(request.sealed_audio)[1]
        params = {
            "model": self.model,
            "smart_format": "true",
            "punctuate": "true",
            "utterances": "true",
            "language": language_param,
        }
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": content_type,
        }
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
                        headers=headers,
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

    def _language_param(self, request: AccurateSttRequest) -> str:
        if len(request.language_hints) == 1:
            normalized = request.language_hints[0].strip().casefold().split("-", 1)[0]
            if normalized:
                return normalized
        return "multi"

    def _backoff(self, attempt: int) -> None:
        if not self.retry_backoff_seconds:
            return
        index = min(attempt, len(self.retry_backoff_seconds) - 1)
        self.sleep(float(self.retry_backoff_seconds[index]))

    def _stable_segment_id(
        self, request: AccurateSttRequest, text: str, *, index: int | None = None
    ) -> str:
        parts = [request.operation_id, request.media_ref, self.model, text]
        # Per-utterance segments can carry identical text (e.g. a repeated
        # "Да."); the ordinal disambiguates their otherwise colliding IDs.
        if index is not None:
            parts.append(str(index))
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]
        return f"accurate_{digest}"


def _first_alternative(payload: object) -> dict[str, object] | None:
    """Safely walk results.channels[0].alternatives[0] without trusting shape."""

    if not isinstance(payload, dict):
        return None
    results = payload.get("results")
    if not isinstance(results, dict):
        return None
    channels = results.get("channels")
    if not isinstance(channels, list) or not channels:
        return None
    channel = channels[0]
    if not isinstance(channel, dict):
        return None
    alternatives = channel.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        return None
    alternative = alternatives[0]
    return alternative if isinstance(alternative, dict) else None


def _utterances(payload: object) -> list[dict[str, object]]:
    """Return the optional results.utterances array as dicts, else empty."""

    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, dict):
        return []
    utterances = results.get("utterances")
    if not isinstance(utterances, list):
        return []
    return [item for item in utterances if isinstance(item, dict)]


def _to_ms(value: object, *, default: int) -> int:
    seconds = _optional_float(value)
    if seconds is None or seconds < 0:
        return default
    return int(seconds * 1000)


def _distinct_word_languages(alternative: dict[str, object] | None) -> str | None:
    """Comma-joined sorted distinct per-word language tags, or None if absent."""

    if alternative is None:
        return None
    words = alternative.get("words")
    if not isinstance(words, list):
        return None
    languages: set[str] = set()
    for word in words:
        if isinstance(word, dict):
            language = word.get("language")
            if isinstance(language, str) and language:
                languages.add(language)
    return ",".join(sorted(languages)) if languages else None


def _metadata_duration(payload: object) -> object:
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata")
    return metadata.get("duration") if isinstance(metadata, dict) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
