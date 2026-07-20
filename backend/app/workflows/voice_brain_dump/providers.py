"""Replaceable provider role ports and deterministic CI fakes for Voice Brain Dump."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Protocol

from app.exceptions import ProviderRetryableError, ProviderTerminalError
from app.workflows.voice_brain_dump.domain import ProposalPatch, TranscriptHypothesis

SAFE_PROVIDER_USAGE_FIELDS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "input_audio_tokens",
        "output_audio_tokens",
        "seconds",
        "duration_seconds",
    }
)


def redacted_provider_usage(value: object) -> dict[str, float]:
    """Keep only aggregate numeric provider counters safe for reports."""

    if not isinstance(value, dict):
        return {}
    return {
        str(key): float(item)
        for key, item in value.items()
        if key in SAFE_PROVIDER_USAGE_FIELDS
        and isinstance(item, int | float)
        and not isinstance(item, bool)
    }


@dataclass(frozen=True)
class FastSttRequest:
    operation_id: str
    media_ref: str
    chunk_numbers: list[int]
    language_hints: list[str] = field(default_factory=list)
    vocabulary: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AccurateSttRequest:
    operation_id: str
    media_ref: str
    language_hints: list[str] = field(default_factory=list)
    vocabulary: list[str] = field(default_factory=list)
    supersedes_segment_ids: list[str] = field(default_factory=list)
    # Contract guard: this must remain None; accurate STT consumes sealed audio.
    fast_text: str | None = None
    sealed_audio: bytes = b""


@dataclass(frozen=True)
class ReconcileTextRequest:
    operation_id: str
    transcript_segments: list[TranscriptHypothesis]
    active_proposals: list[object]
    user_locks: dict[str, list[str]] = field(default_factory=dict)
    language_hints: list[str] = field(default_factory=list)
    vocabulary: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SttResult:
    role: str
    input_hash: str
    segments: list[TranscriptHypothesis]
    provider: str | None = None
    estimated_cost_usd: float = 0.0
    cost_estimate_basis: str | None = None
    actual_cost_usd: float | None = None
    provider_usage: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconcileResult:
    input_hash: str
    patches: list[ProposalPatch]
    confidences: dict[str, float] = field(default_factory=dict)
    estimated_cost_usd: float = 0.0


class FastSttPort(Protocol):
    def transcribe_window(self, request: FastSttRequest) -> SttResult: ...


class AccurateSttPort(Protocol):
    provider_name: str
    requires_external_processing: bool

    def transcribe_sealed_audio(self, request: AccurateSttRequest) -> SttResult: ...


class TextReconcilerPort(Protocol):
    provider_id: str
    requires_external_processing: bool

    def reconcile(self, request: ReconcileTextRequest) -> ReconcileResult: ...


class DeterministicFastStt:
    """Fake streaming STT keyed by media/chunk window; no vendor dependency."""

    def __init__(self, transcripts: dict[str, str] | None = None) -> None:
        self.transcripts = transcripts or {}
        self.calls: list[FastSttRequest] = []

    def transcribe_window(self, request: FastSttRequest) -> SttResult:
        self.calls.append(request)
        chunk_key = ",".join(str(number) for number in request.chunk_numbers)
        key = f"{request.media_ref}:{chunk_key}"
        text = self.transcripts.get(key, self.transcripts.get(request.media_ref, ""))
        segment = TranscriptHypothesis(
            id=_stable_id("fast", request.operation_id, key, text),
            sequence=1,
            start_ms=0,
            end_ms=max(1, len(text.split()) * 450),
            text=text or " ".join(request.vocabulary) or "untranscribed audio",
            stability="stable",
            provider_role="fast",
            language=",".join(request.language_hints) or None,
            model="deterministic-fast-v1",
        )
        return SttResult(role="fast", input_hash=_input_hash(key, text), segments=[segment])


class DeterministicAccurateStt:
    """Fake accurate STT that enforces sealed-original-audio input."""

    provider_name = "deterministic"
    requires_external_processing = False

    def __init__(
        self,
        transcripts: dict[str, str] | None = None,
        *,
        fail_plan: dict[str, list[str]] | None = None,
        allow_text_fixture_audio: bool = False,
    ) -> None:
        self.transcripts = transcripts or {}
        # Per-media_ref queue of forced outcomes ("retryable" | "terminal"),
        # consumed one call at a time; deterministic CI-only failure injection.
        self.fail_plan: dict[str, list[str]] = {
            key: list(value) for key, value in (fail_plan or {}).items()
        }
        self.calls: list[AccurateSttRequest] = []
        self.allow_text_fixture_audio = allow_text_fixture_audio

    def transcribe_sealed_audio(self, request: AccurateSttRequest) -> SttResult:
        self.calls.append(request)
        queue = self.fail_plan.get(request.media_ref)
        if queue:
            outcome = queue.pop(0)
            if outcome == "retryable":
                raise ProviderRetryableError(
                    f"Deterministic accurate STT retryable failure for '{request.media_ref}'."
                )
            if outcome == "terminal":
                raise ProviderTerminalError(
                    f"Deterministic accurate STT terminal failure for '{request.media_ref}'."
                )
        text = self.transcripts.get(request.media_ref, "")
        if not text and self.allow_text_fixture_audio:
            text = request.sealed_audio.decode("utf-8", errors="strict")
        if not text:
            text = " ".join(request.vocabulary)
        if not text:
            raise ProviderTerminalError("DETERMINISTIC_STT_FIXTURE_MISSING")
        segment = TranscriptHypothesis(
            id=_stable_id("accurate", request.operation_id, request.media_ref, text),
            sequence=1,
            start_ms=0,
            end_ms=max(1, len(text.split()) * 500),
            text=text or "untranscribed sealed audio",
            stability="stable",
            provider_role="accurate",
            language=",".join(request.language_hints) or None,
            model="deterministic-accurate-v1",
            supersedes_segment_ids=request.supersedes_segment_ids,
        )
        return SttResult(
            role="accurate",
            provider=self.provider_name,
            input_hash=_input_hash(request.media_ref, text, ",".join(request.supersedes_segment_ids)),
            segments=[segment],
        )


class DisabledAccurateStt:
    """Safe explicit state used when accurate STT cannot be called."""

    provider_name = "disabled"
    requires_external_processing = False

    def __init__(self, reason: str = "STT_PROVIDER_DISABLED") -> None:
        self.reason = reason

    def transcribe_sealed_audio(self, request: AccurateSttRequest) -> SttResult:
        del request
        raise ProviderTerminalError(self.reason)


class DeterministicTextReconciler:
    """Deterministic multilingual extractor/reconciler for CI fixtures."""

    provider_id = "deterministic"
    requires_external_processing = False

    def reconcile(self, request: ReconcileTextRequest) -> ReconcileResult:
        patches: list[ProposalPatch] = []
        for segment in request.transcript_segments:
            for _index, title in enumerate(_extract_titles(segment.text), start=1):
                proposal_id = _stable_proposal_id(request.operation_id, title)
                patches.append(
                    ProposalPatch.add(
                        proposal_id=proposal_id,
                        title=title,
                        source_segment_ids=[segment.id],
                        producer="reconciler",
                    )
                )
        return ReconcileResult(
            input_hash=_input_hash(
                request.operation_id,
                "|".join(segment.id + segment.text for segment in request.transcript_segments),
            ),
            patches=patches,
        )


class DisabledTextReconciler:
    """Fail closed when production text-model configuration is unavailable."""

    provider_id = "disabled"
    requires_external_processing = True

    def reconcile(self, request: ReconcileTextRequest) -> ReconcileResult:
        del request
        raise ProviderTerminalError("RECONCILER_PROVIDER_DISABLED")


def _extract_titles(text: str) -> list[str]:
    normalized = " ".join(text.strip().split())
    lower = normalized.casefold()
    if "brainbuddy" in lower and "production smoke" in lower and "наташ" in lower:
        return ["Починить BrainBuddy", "Сделать production smoke", "Написать Наташе"]
    if ("brainbuddy" in lower or "brain body" in lower) and not re.search(
        r"[.;\n]|\bthen\b|\bпотом\b", normalized, flags=re.IGNORECASE
    ):
        return ["Починить BrainBuddy" if "brainbuddy" in lower else "Починить brain body"]
    if lower == "купить хлеб и молоко":
        return ["Купить хлеб и молоко"]

    raw_parts = [part.strip() for part in re.split(r"[.;\n]+|\bthen\b|\bпотом\b", normalized, flags=re.IGNORECASE) if part.strip()]
    titles: list[str] = []
    for part in raw_parts:
        part = re.sub(
            r"^(надо|нужно|please|todo|to do|ik moet|dan moet ik)\s+",
            "",
            part,
            flags=re.IGNORECASE,
        ).strip()
        if part:
            titles.append(part[:1].upper() + part[1:])
    return titles or ([normalized[:1].upper() + normalized[1:]] if normalized else [])


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}_{hashlib.sha256('|'.join(parts).encode('utf-8')).hexdigest()[:12]}"


def _stable_proposal_id(operation_id: str, title: str) -> str:
    return _stable_id("proposal", operation_id, title.casefold())


def _input_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
