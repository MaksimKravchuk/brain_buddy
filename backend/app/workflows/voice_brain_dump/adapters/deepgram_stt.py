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

from app.core.config import MVP_ACCURATE_STT_MODEL
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
# Nova-3 multilingual code-switch mode. This is a fixed, non-private query
# control, never derived from caller-supplied language hints: those hints
# must not be reflected into the third-party request URL, which (unlike the
# request body) is far more likely to be captured by intermediary
# proxy/CDN/access logs outside this app's own logging.
_DEEPGRAM_LANGUAGE_PARAM = "multi"


@dataclass(frozen=True, slots=True)
class DeepgramAccurateStt:
    """Transcribe sealed audio with Deepgram without logging provider payloads."""

    api_key: str = field(repr=False)
    timeout_seconds: float = 60.0
    max_retries: int = 2
    retry_backoff_seconds: Sequence[float] = (1.0, 2.0)
    max_cost_usd_per_operation: float = 0.50
    estimated_cost_usd_per_megabyte: float = 0.01
    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = time.sleep
    # Authorization-sensitive identity: never accepted from the constructor
    # and never reassignable post-construction (the dataclass is frozen).
    # Defense in depth beyond the container's allow-list: even a direct,
    # manually-constructed adapter instance (bypassing
    # ``app.container._build_accurate_stt`` entirely) must never be able to
    # send credentials/audio to Deepgram under an unmeasured Nova-3 variant
    # (e.g. "nova-3-medical", "nova-3-general"). No runtime configuration --
    # env var, caller kwarg, or post-construction mutation -- may decide
    # this identity.
    model: str = field(default=MVP_ACCURATE_STT_MODEL, init=False)
    provider_name: str = field(default="deepgram", init=False)
    requires_external_processing: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        self._require_authorized_identity()

    def _require_authorized_identity(self) -> None:
        """Re-validate identity fields immediately before every use.

        ``frozen=True`` blocks ordinary attribute reassignment, but a caller
        could still force a spoofed value onto a constructed instance (e.g.
        ``object.__setattr__``) or -- since Python performs no runtime
        generic-checking -- substitute a ``str`` subclass whose overridden
        ``__eq__``/``__ne__`` lies about matching the authorized constant
        while carrying a different actual value. ``type(value) is str`` plus
        exact literal equality closes both: it is checked once at
        construction and again immediately before every network transmit and
        retry, so a value that only becomes wrong after ``__post_init__``
        still cannot reach the wire.
        """

        for value, authorized, label in (
            (self.provider_name, "deepgram", "provider"),
            (self.model, MVP_ACCURATE_STT_MODEL, "model"),
        ):
            if type(value) is not str or value != authorized:  # noqa: E721
                raise ValueError(
                    f"Unauthorized Deepgram accurate STT {label} {value!r}; only "
                    f"the exact authorized {authorized!r} {label} may be used."
                )

    def transcribe_sealed_audio(self, request: AccurateSttRequest) -> SttResult:
        if not request.sealed_audio:
            raise ProviderTerminalError("STT_AUDIO_MISSING")
        # Keep the authorization failure distinct from provider-response
        # parsing failures below, while the identical check in the retry loop
        # remains the final guard immediately before each HTTP transmit.
        self._require_authorized_identity()
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
        params = self._query_params()
        attempt = 0
        while True:
            self._require_authorized_identity()
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

    def _query_params(self) -> list[tuple[str, str | int | float | bool | None]]:
        # Fixed, non-private query controls only. Caller-supplied vocabulary
        # (``keyterm``) and language hints must never be reflected into this
        # third-party request URL; see ``_DEEPGRAM_LANGUAGE_PARAM``.
        return [
            ("model", self.model),
            ("language", _DEEPGRAM_LANGUAGE_PARAM),
            ("smart_format", "true"),
        ]

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
