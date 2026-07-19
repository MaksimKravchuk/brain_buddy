"""OpenAI accurate-STT adapter over sealed original audio."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import httpx

from app.exceptions import ProviderRetryableError, ProviderTerminalError
from app.workflows.voice_brain_dump.domain import TranscriptHypothesis
from app.workflows.voice_brain_dump.providers import AccurateSttRequest, SttResult

OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
_RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
_LANGUAGE_ALIASES = {
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "ru": "ru",
    "ru-ru": "ru",
}


def _audio_multipart_metadata(audio: bytes) -> tuple[str, str]:
    """Sniff supported container signatures instead of trusting upload metadata."""

    if audio.startswith(b"\x1aE\xdf\xa3"):
        return "recording.webm", "audio/webm"
    if audio.startswith(b"RIFF") and audio[8:12] == b"WAVE":
        return "recording.wav", "audio/wav"
    if len(audio) >= 12 and audio[4:8] == b"ftyp":
        return "recording.m4a", "audio/mp4"
    if len(audio) >= 2 and audio[0] == 0xFF and audio[1] & 0xF0 == 0xF0:
        return "recording.aac", "audio/aac"
    raise ProviderTerminalError("STT_AUDIO_FORMAT_UNSUPPORTED")


@dataclass(slots=True)
class OpenAiAccurateStt:
    """Transcribe sealed audio with OpenAI without logging provider payloads."""

    api_key: str
    model: str = "gpt-4o-mini-transcribe"
    timeout_seconds: float = 60.0
    max_retries: int = 2
    retry_backoff_seconds: Sequence[float] = (1.0, 2.0)
    max_cost_usd_per_operation: float = 0.50
    estimated_cost_usd_per_megabyte: float = 0.01
    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = time.sleep
    provider_name: str = field(default="openai", init=False)
    requires_external_processing: bool = field(default=True, init=False)

    def transcribe_sealed_audio(self, request: AccurateSttRequest) -> SttResult:
        if not request.sealed_audio:
            raise ProviderTerminalError("STT_AUDIO_MISSING")
        estimated_cost = (
            len(request.sealed_audio) / 1_000_000
        ) * self.estimated_cost_usd_per_megabyte
        if estimated_cost > self.max_cost_usd_per_operation:
            raise ProviderTerminalError("STT_COST_LIMIT_EXCEEDED")

        response = self._post_with_retries(request)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderTerminalError("STT_PROVIDER_INVALID_RESPONSE") from exc
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise ProviderTerminalError("STT_PROVIDER_INVALID_RESPONSE")
        normalized_text = " ".join(text.split())
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
        return SttResult(
            role="accurate",
            provider=self.provider_name,
            input_hash=hashlib.sha256(request.sealed_audio).hexdigest(),
            segments=[segment],
            estimated_cost_usd=estimated_cost,
        )

    def _post_with_retries(self, request: AccurateSttRequest) -> httpx.Response:
        filename, content_type = _audio_multipart_metadata(request.sealed_audio)
        attempt = 0
        while True:
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = client.post(
                        OPENAI_TRANSCRIPTIONS_URL,
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        data=self._form_fields(request),
                        files={
                            "file": (
                                filename,
                                request.sealed_audio,
                                content_type,
                            )
                        },
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

    def _form_fields(self, request: AccurateSttRequest) -> dict[str, str]:
        fields = {"model": self.model, "response_format": "json"}
        if request.language_hints:
            first_hint = request.language_hints[0].strip().casefold()
            fields["language"] = _LANGUAGE_ALIASES.get(
                first_hint, first_hint.split("-", 1)[0]
            )
        if request.vocabulary:
            fields["prompt"] = "Key terms: " + ", ".join(request.vocabulary)
        return fields

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
