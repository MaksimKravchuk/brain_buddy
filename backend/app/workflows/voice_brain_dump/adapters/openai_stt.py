"""OpenAI accurate-STT adapter over sealed original audio.

ADR-0002 authorizes only Deepgram Nova-3 for the production ``accurate_stt``
role; ``app.container`` never wires this adapter into production (it always
resolves to Deepgram or an explicit disabled/deterministic path). This class
exists solely as narrowly-scoped, explicit test support for exercising the
OpenAI transcription HTTP contract; see ``acknowledge_test_only_direct_
construction`` below. It is intentionally excluded from ``adapters/
__init__.py``'s exported/production surface.
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

OPENAI_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
# Independent of the module attribute above: bound once, at import time, to
# its own name, exactly like ``deepgram_stt._AUTHORIZED_LISTEN_URL``.
# Reassigning the public ``OPENAI_TRANSCRIPTIONS_URL`` attribute cannot
# retroactively change what this name already points to, so it stays the
# sole source of truth this adapter ever transmits to or authorizes against.
_AUTHORIZED_ENDPOINT = OPENAI_TRANSCRIPTIONS_URL
# This adapter is test-only, but even explicit test support must not expose a
# caller-selectable provider/model/endpoint tuple. Keeping one exact built-in
# model makes every other tuple fail before a Bearer-authenticated audio body
# can be constructed or transmitted.
_TEST_ONLY_OPENAI_MODEL = "gpt-4o-mini-transcribe"
_RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}
_LANGUAGE_ALIASES = {
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "ru": "ru",
    "ru-ru": "ru",
}


@dataclass(frozen=True, slots=True)
class OpenAiAccurateStt:
    """Transcribe sealed audio with OpenAI without logging provider payloads.

    Test-only: not authorized for production accurate STT (ADR-0002
    authorizes only Deepgram Nova-3), never wired by ``app.container``, and
    excluded from ``adapters/__init__.py``'s production-facing surface.
    Construction requires the explicit
    ``acknowledge_test_only_direct_construction=True`` keyword; omitting it,
    supplying a non-exact-``bool`` value, or later mutating it away (even via
    ``object.__setattr__``) fails closed with zero transport calls.
    """

    api_key: str = field(repr=False)
    timeout_seconds: float = 60.0
    max_retries: int = 2
    retry_backoff_seconds: Sequence[float] = (1.0, 2.0)
    max_cost_usd_per_operation: float = 0.50
    estimated_cost_usd_per_megabyte: float = 0.01
    transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = time.sleep
    acknowledge_test_only_direct_construction: bool = field(
        default=False, kw_only=True
    )
    # Authorization-sensitive identity: never accepted from the constructor
    # and never reassignable post-construction (the dataclass is frozen).
    # Defense in depth: even a direct, manually-constructed adapter instance
    # must never be able to send credentials/audio to a different provider
    # endpoint. No runtime configuration -- env var, caller kwarg, or
    # post-construction mutation -- may decide this identity.
    model: str = field(default=_TEST_ONLY_OPENAI_MODEL, init=False)
    provider_name: str = field(default="openai", init=False)
    endpoint: str = field(default=_AUTHORIZED_ENDPOINT, init=False)
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
        exact literal equality closes both for ``provider_name``/
        ``endpoint``; it is checked once at construction and again
        immediately before every network transmit and retry, so a value that
        only becomes wrong after ``__post_init__`` still cannot reach the
        wire. ``bool`` cannot be subclassed in Python, so ``type(value) is
        bool`` plus ``value is True`` (the singleton) is already immune to
        the analogous forgery for the test-only acknowledgment.
        """

        for value, authorized, label in (
            (self.provider_name, "openai", "provider"),
            (self.model, _TEST_ONLY_OPENAI_MODEL, "model"),
            (self.endpoint, _AUTHORIZED_ENDPOINT, "endpoint"),
        ):
            if type(value) is not str or value != authorized:  # noqa: E721
                raise ValueError(
                    f"Unauthorized OpenAI accurate STT {label} {value!r}; only "
                    f"the exact authorized {authorized!r} {label} may be used."
                )
        acknowledgement = self.acknowledge_test_only_direct_construction
        if type(acknowledgement) is not bool or acknowledgement is not True:  # noqa: E721
            raise ValueError(
                "OpenAI accurate STT direct construction is test-only and "
                "requires the exact acknowledge_test_only_direct_construction="
                "True keyword; ADR-0002 authorizes only Deepgram Nova-3 for "
                "production accurate STT."
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
        # spend (success or failure) must assume the worst case, not just the
        # first attempt.
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
        text = payload.get("text") if isinstance(payload, dict) else None
        if not isinstance(text, str) or not text.strip():
            wrapped = ProviderTerminalError("STT_PROVIDER_INVALID_RESPONSE")
            wrapped.estimated_cost_usd = estimated_cost
            raise wrapped
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
            cost_estimate_basis="audio_bytes_proxy",
            actual_cost_usd=None,
            provider_usage=redacted_provider_usage(payload.get("usage")),
        )

    def _post_with_retries(self, request: AccurateSttRequest) -> httpx.Response:
        filename, content_type = sniff_audio_container(request.sealed_audio)
        attempt = 0
        while True:
            self._require_authorized_identity()
            try:
                with httpx.Client(
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    response = client.post(
                        self.endpoint,
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
