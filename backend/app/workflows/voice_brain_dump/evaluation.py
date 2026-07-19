"""Versioned, deterministic Voice Brain Dump release evaluation.

The offline gate reads the same labelled ML-01–ML-07 corpus documented by the
feature specification. Synthetic WAV files exercise the sealed-audio provider
boundary without using customer recordings or a paid provider.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import time
import wave
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.exceptions import (
    ProviderRetryableError,
    ProviderTerminalError,
    ValidationFailure,
)

from .domain import TranscriptHypothesis
from .providers import (
    AccurateSttRequest,
    DeterministicAccurateStt,
    ReconcileTextRequest,
    TextReconcilerPort,
    _extract_titles,
    redacted_provider_usage,
)


@dataclass(frozen=True)
class EvaluationReport:
    case_count: int
    audio_case_count: int
    languages: set[str]
    modalities: set[str]
    provider_model_version: str
    audio_signal_accuracy: float
    task_boundary_precision: float
    task_boundary_recall: float
    exact_count_accuracy: float
    title_cleanliness: float
    code_switch_term_accuracy: float
    conjunction_false_split_rate: float
    split_merge_accuracy: float
    confidence_calibration_error: float
    structural_lineage_cases: int
    by_language: dict[str, dict[str, float]]
    failures: list[str]


@dataclass(frozen=True)
class _EvaluationCase:
    id: str
    languages: tuple[str, ...]
    transcript: str
    expected_titles: tuple[str, ...]
    audio_path: Path
    audio_sha256: str
    code_switch_terms: tuple[str, ...]
    structural_change: str | None
    expected_confidence: float
    expected_frequency_hz: float | None


_FIXTURE_ROOT = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "voice_brain_dump"
    / "v1"
)
_PROVIDER_MODEL_VERSION = "deterministic-accurate-v1"


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _load_cases(fixture_root: Path) -> list[_EvaluationCase]:
    raw: dict[str, Any] = json.loads(
        (fixture_root / "manifest.json").read_text(encoding="utf-8")
    )
    if raw.get("version") != 1:
        raise ValueError("Unsupported Voice Brain Dump evaluation manifest version")

    cases: list[_EvaluationCase] = []
    for fixture in raw["fixtures"]:
        case_id = str(fixture["id"])
        if case_id not in {f"ML-0{index}" for index in range(1, 8)}:
            continue
        transcript = str(fixture.get("accurate_text") or fixture.get("text") or "")
        expected_titles = tuple(str(value) for value in fixture["expected_titles"])
        language_value = fixture.get("language", ["ru"])
        languages = (
            tuple(str(value) for value in language_value)
            if isinstance(language_value, list)
            else (str(language_value),)
        )
        cases.append(
            _EvaluationCase(
                id=case_id,
                languages=languages,
                transcript=transcript,
                expected_titles=expected_titles,
                audio_path=fixture_root / str(fixture["audio_file"]),
                audio_sha256=str(fixture["audio_sha256"]),
                code_switch_terms=tuple(
                    str(value) for value in fixture.get("code_switch_terms", [])
                ),
                structural_change=(
                    str(fixture["structural_change"])
                    if fixture.get("structural_change")
                    else None
                ),
                expected_confidence=float(fixture.get("expected_confidence", 1.0)),
                expected_frequency_hz=(
                    float(fixture["expected_frequency_hz"])
                    if fixture.get("expected_frequency_hz") is not None
                    else None
                ),
            )
        )
    return cases


def _validated_audio(case: _EvaluationCase) -> bytes:
    payload = case.audio_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != case.audio_sha256:
        raise ValueError(f"{case.id}: synthetic audio hash does not match manifest")
    with wave.open(str(case.audio_path), "rb") as fixture:
        if fixture.getnchannels() != 1 or fixture.getsampwidth() != 2:
            raise ValueError(f"{case.id}: audio must be mono 16-bit PCM")
        if fixture.getframerate() != 16_000 or fixture.getnframes() < 8_000:
            raise ValueError(f"{case.id}: audio must contain at least 500 ms at 16 kHz")
    return payload


def _case_languages(case: _EvaluationCase) -> tuple[str, ...]:
    return case.languages or ("unknown",)


def _measured_frequency_hz(audio_path: Path) -> float:
    """Measure the deterministic corpus tone without consulting case labels."""

    with wave.open(str(audio_path), "rb") as fixture:
        rate = int(fixture.getframerate())
        frames = fixture.readframes(fixture.getnframes())
    samples = [value[0] for value in struct.iter_unpack("<h", frames)]
    crossings = sum(
        (left < 0) != (right < 0)
        for left, right in zip(samples, samples[1:], strict=False)
    )
    duration_seconds = len(samples) / rate
    return float(crossings) / (2.0 * duration_seconds)


def evaluate_release_dataset(
    fixture_root: Path = _FIXTURE_ROOT,
) -> EvaluationReport:
    cases = _load_cases(fixture_root)
    failures: list[str] = []
    provider = DeterministicAccurateStt(
        {f"fixture_{case.id}": case.transcript for case in cases}
    )

    predicted_total = expected_total = matched_boundaries = 0
    exact_counts = clean_titles = expected_title_total = 0
    code_switch_hits = code_switch_total = 0
    conjunction_cases = conjunction_false_splits = 0
    structural_cases = structural_hits = 0
    confidence_error = 0.0
    audio_signal_hits = 0
    language_counts: dict[str, dict[str, float]] = {}

    for case in cases:
        audio = _validated_audio(case)
        signal_matches = case.expected_frequency_hz is None or abs(
            _measured_frequency_hz(case.audio_path) - case.expected_frequency_hz
        ) <= 2.0
        audio_signal_hits += int(signal_matches)
        if not signal_matches:
            failures.append(f"{case.id}: audio signal mismatch")
        result = provider.transcribe_sealed_audio(
            AccurateSttRequest(
                operation_id=case.id,
                media_ref=f"fixture_{case.id}",
                language_hints=list(case.languages),
                sealed_audio=audio,
            )
        )
        transcript = result.segments[0].text
        if _normalized(transcript) != _normalized(case.transcript):
            failures.append(f"{case.id}: audio transcript mismatch")

        text_prediction = tuple(_extract_titles(case.transcript))
        audio_prediction = tuple(_extract_titles(transcript))
        if audio_prediction != text_prediction:
            failures.append(f"{case.id}: text/audio intent mismatch")
        predicted = audio_prediction
        expected = case.expected_titles

        predicted_total += len(predicted)
        expected_total += len(expected)
        matched_boundaries += min(len(predicted), len(expected))
        count_is_exact = len(predicted) == len(expected)
        exact_counts += int(count_is_exact)

        title_hits = sum(
            _normalized(actual) == _normalized(wanted)
            for actual, wanted in zip(predicted, expected, strict=False)
        )
        clean_titles += title_hits
        expected_title_total += len(expected)
        if title_hits != len(expected) or not count_is_exact:
            failures.append(f"{case.id}: titles {predicted!r} != {expected!r}")

        joined_prediction = " ".join(predicted).casefold()
        for term in case.code_switch_terms:
            code_switch_total += 1
            code_switch_hits += int(term.casefold() in joined_prediction)

        lower = case.transcript.casefold()
        is_conjunction_case = len(expected) == 1 and (
            " and " in lower or " и " in lower
        )
        if is_conjunction_case:
            conjunction_cases += 1
            conjunction_false_splits += int(len(predicted) > 1)

        if case.structural_change:
            structural_cases += 1
            structural_hits += int(count_is_exact and title_hits == len(expected))

        observed_correctness = float(count_is_exact and title_hits == len(expected))
        confidence_error += abs(case.expected_confidence - observed_correctness)

        for language in _case_languages(case):
            totals = language_counts.setdefault(
                language,
                {"cases": 0.0, "exact_count_hits": 0.0, "title_hits": 0.0, "titles": 0.0},
            )
            totals["cases"] += 1
            totals["exact_count_hits"] += int(count_is_exact)
            totals["title_hits"] += title_hits
            totals["titles"] += len(expected)

    by_language = {
        language: {
            "case_count": values["cases"],
            "exact_count_accuracy": values["exact_count_hits"] / values["cases"],
            "title_cleanliness": values["title_hits"] / values["titles"],
        }
        for language, values in language_counts.items()
    }
    case_count = len(cases)
    return EvaluationReport(
        case_count=case_count,
        audio_case_count=case_count,
        languages={language for case in cases for language in case.languages},
        modalities={"audio", "text"},
        provider_model_version=_PROVIDER_MODEL_VERSION,
        audio_signal_accuracy=(
            audio_signal_hits / case_count if case_count else 0.0
        ),
        task_boundary_precision=(
            matched_boundaries / predicted_total if predicted_total else 0.0
        ),
        task_boundary_recall=(
            matched_boundaries / expected_total if expected_total else 0.0
        ),
        exact_count_accuracy=exact_counts / case_count if case_count else 0.0,
        title_cleanliness=(
            clean_titles / expected_title_total if expected_title_total else 0.0
        ),
        code_switch_term_accuracy=(
            code_switch_hits / code_switch_total if code_switch_total else 1.0
        ),
        conjunction_false_split_rate=(
            conjunction_false_splits / conjunction_cases if conjunction_cases else 0.0
        ),
        split_merge_accuracy=(
            structural_hits / structural_cases if structural_cases else 0.0
        ),
        confidence_calibration_error=(
            confidence_error / case_count if case_count else 1.0
        ),
        structural_lineage_cases=structural_cases,
        by_language=by_language,
        failures=failures,
    )


@dataclass(frozen=True)
class SttQualityMetrics:
    character_error_rate: float
    word_error_rate: float
    critical_term_recall: float
    critical_term_hits: int
    critical_term_total: int
    omission_count: int
    hallucination_count: int
    mean_latency_seconds: float
    p95_latency_seconds: float
    estimated_cost_usd: float
    cost_estimate_bases: set[str]
    actual_cost_usd: float | None
    provider_usage: dict[str, float]


@dataclass(frozen=True)
class ExtractionQualityMetrics:
    exact_task_count_accuracy: float
    boundary_precision: float
    boundary_recall: float
    provenance_boundary_precision: float
    provenance_boundary_recall: float
    title_accuracy: float
    task_identity_accuracy: float
    invented_task_count: int
    conjunction_false_split_rate: float
    semantic_preservation_rate: float
    split_merge_accuracy: float | None
    confidence_calibration_error: float | None


@dataclass(frozen=True)
class EvaluationFailure:
    case_id: str
    stage: str
    code: str


@dataclass(frozen=True)
class RealAudioEvaluationReport:
    status: str
    disabled_reason: str | None
    case_count: int
    provider_models: set[str]
    stt: SttQualityMetrics
    extraction: ExtractionQualityMetrics | None
    by_language: dict[str, SttQualityMetrics]
    p95_latency_by_duration_language_provider_model: dict[str, float]
    failures: list[EvaluationFailure]


@dataclass(frozen=True)
class _RealAudioCase:
    id: str
    audio_path: Path
    transcript_path: Path
    expected_tasks_path: Path | None
    language_hints: list[str]
    vocabulary: list[str]
    critical_terms: list[str]
    duration_seconds: float | None


@dataclass(frozen=True)
class _TaskLabel:
    title: str
    structural_change: str | None = None
    confidence: float | None = None
    source_spans: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class EvaluationExtractionInput:
    """Provider output and corpus context supplied to an evaluation extractor."""

    transcript_segments: tuple[TranscriptHypothesis, ...]
    language_hints: tuple[str, ...]
    vocabulary: tuple[str, ...]

    @property
    def transcript(self) -> str:
        return " ".join(segment.text for segment in self.transcript_segments).strip()


def build_semantic_extractor(
    reconciler: TextReconcilerPort,
) -> Callable[[EvaluationExtractionInput], list[dict[str, object]]]:
    """Adapt the configured semantic reconciler to the corpus scoring contract."""

    def extract(evaluation_input: EvaluationExtractionInput) -> list[dict[str, object]]:
        transcript = evaluation_input.transcript
        digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()[:12]
        segments_by_id = {
            segment.id: segment for segment in evaluation_input.transcript_segments
        }
        result = reconciler.reconcile(
            ReconcileTextRequest(
                operation_id=f"evaluation_{digest}",
                transcript_segments=list(evaluation_input.transcript_segments),
                active_proposals=[],
                language_hints=list(evaluation_input.language_hints),
                vocabulary=list(evaluation_input.vocabulary),
            )
        )
        return [
            {
                "title": patch.title,
                "structural_change": (
                    patch.operation if patch.operation in {"split", "merge"} else None
                ),
                "confidence": result.confidences.get(patch.proposal_id),
                "source_spans": [
                    [segments_by_id[segment_id].start_ms, segments_by_id[segment_id].end_ms]
                    for segment_id in patch.source_segment_ids
                    if segment_id in segments_by_id
                ],
            }
            for patch in result.patches
            if patch.operation != "remove" and patch.title is not None
        ]

    return extract


def evaluate_real_audio_corpus(
    corpus_root: Path,
    provider: Any,
    *,
    external_processing_allowed: bool,
    extractor: Callable[
        [EvaluationExtractionInput], list[str] | list[dict[str, object]]
    ]
    | None = None,
    monotonic_values: Callable[[], float] = time.monotonic,
) -> RealAudioEvaluationReport:
    """Evaluate real audio without passing ground truth into the STT provider.

    The corpus is intentionally external to the repository. Reports contain only
    aggregate metrics and case IDs; raw audio and transcripts never leave the
    supplied corpus directory through this API.
    """

    if not external_processing_allowed:
        return RealAudioEvaluationReport(
            status="disabled",
            disabled_reason="EXTERNAL_PROCESSING_CONSENT_REQUIRED",
            case_count=0,
            provider_models=set(),
            stt=_empty_stt_metrics(),
            extraction=None,
            by_language={},
            p95_latency_by_duration_language_provider_model={},
            failures=[],
        )
    if getattr(provider, "provider_name", "disabled") == "disabled":
        return RealAudioEvaluationReport(
            status="disabled",
            disabled_reason=getattr(provider, "reason", "STT_PROVIDER_DISABLED"),
            case_count=0,
            provider_models=set(),
            stt=_empty_stt_metrics(),
            extraction=None,
            by_language={},
            p95_latency_by_duration_language_provider_model={},
            failures=[],
        )

    cases = _load_real_audio_cases(corpus_root)
    failures: list[EvaluationFailure] = []
    provider_models: set[str] = set()
    aggregate = _MetricAccumulator()
    language_aggregates: dict[str, _MetricAccumulator] = {}
    exact_task_counts = matched_boundaries = matched_provenance_boundaries = 0
    matched_titles = matched_task_identities = invented_task_count = 0
    predicted_tasks = expected_tasks = 0
    extraction_cases = 0
    conjunction_cases = conjunction_false_splits = 0
    semantic_score_total = 0.0
    structural_cases = structural_hits = 0
    confidence_error = 0.0
    confidence_count = 0
    grouped_latencies: dict[str, list[float]] = {}

    for case in cases:
        audio = case.audio_path.read_bytes()
        expected_transcript = case.transcript_path.read_text(encoding="utf-8").strip()
        started = monotonic_values()
        try:
            result = provider.transcribe_sealed_audio(
                AccurateSttRequest(
                    operation_id=case.id,
                    media_ref=f"evaluation:{case.id}",
                    language_hints=case.language_hints,
                    vocabulary=case.vocabulary,
                    sealed_audio=audio,
                )
            )
        except (ValidationFailure, ProviderRetryableError, ProviderTerminalError) as exc:
            latency = max(0.0, monotonic_values() - started)
            failed_metrics = _score_stt(
                expected_transcript,
                "",
                case.critical_terms,
                latency,
                0.0,
                None,
                None,
                {},
            )
            aggregate.add(failed_metrics)
            cohort = _language_cohort(case.language_hints)
            language_aggregates.setdefault(cohort, _MetricAccumulator()).add(
                failed_metrics
            )
            failures.append(
                EvaluationFailure(case.id, "stt", _redacted_failure_code(exc))
            )
            continue
        latency = max(0.0, monotonic_values() - started)
        predicted_transcript = " ".join(
            segment.text for segment in result.segments
        ).strip()
        model = next(
            (segment.model for segment in result.segments if segment.model), "unknown"
        )
        provider_model = f"{result.provider or provider.provider_name}/{model}"
        provider_models.add(provider_model)
        case_metrics = _score_stt(
            expected_transcript,
            predicted_transcript,
            case.critical_terms,
            latency,
            result.estimated_cost_usd,
            result.cost_estimate_basis,
            result.actual_cost_usd,
            result.provider_usage,
        )
        aggregate.add(case_metrics)
        cohort = _language_cohort(case.language_hints)
        language_aggregates.setdefault(cohort, _MetricAccumulator()).add(case_metrics)
        duration_seconds = case.duration_seconds or max(
            (segment.end_ms for segment in result.segments), default=0
        ) / 1000
        latency_group = f"{_duration_cohort(duration_seconds)}|{cohort}|{provider_model}"
        grouped_latencies.setdefault(latency_group, []).append(latency)
        if case_metrics.word_error_rate > 0 or case_metrics.critical_term_recall < 1:
            failures.append(EvaluationFailure(case.id, "stt", "TRANSCRIPT_MISMATCH"))

        if extractor is not None and case.expected_tasks_path is not None:
            expected = _task_labels(
                json.loads(case.expected_tasks_path.read_text(encoding="utf-8")),
                case_id=case.id,
                expected=True,
            )
            extraction_cases += 1
            expected_tasks += len(expected)
            try:
                predicted = _task_labels(
                    extractor(
                        EvaluationExtractionInput(
                            transcript_segments=tuple(result.segments),
                            language_hints=tuple(case.language_hints),
                            vocabulary=tuple(case.vocabulary),
                        )
                    ),
                    case_id=case.id,
                    expected=False,
                )
            except (
                ValidationFailure,
                ProviderRetryableError,
                ProviderTerminalError,
                ValueError,
            ) as exc:
                failures.append(
                    EvaluationFailure(
                        case.id, "extraction", _redacted_failure_code(exc)
                    )
                )
                continue
            exact_task_counts += int(len(predicted) == len(expected))
            matches = _match_task_labels(expected, predicted)
            task_identity_matches = [
                match for match in matches if match[2] >= _TASK_IDENTITY_THRESHOLD
            ]
            provenance_boundary_matches = _match_task_boundaries(expected, predicted)
            identity_pairs = {
                (expected_index, predicted_index)
                for expected_index, predicted_index, _score in task_identity_matches
            }
            boundary_matches = [
                match
                for match in provenance_boundary_matches
                if (match[0], match[1]) in identity_pairs
            ]
            title_matches = sum(
                _normalized(predicted[predicted_index].title)
                == _normalized(expected[expected_index].title)
                for expected_index, predicted_index, _score in matches
            )
            matched_boundaries += len(boundary_matches)
            matched_provenance_boundaries += len(provenance_boundary_matches)
            matched_titles += title_matches
            matched_task_identities += len(task_identity_matches)
            case_invented_task_count = len(predicted) - len(task_identity_matches)
            invented_task_count += case_invented_task_count
            semantic_score_total += sum(score for _left, _right, score in matches)
            predicted_tasks += len(predicted)
            normalized_transcript = f" {_normalized(expected_transcript)} "
            is_conjunction_case = len(expected) == 1 and (
                " and " in normalized_transcript or " и " in normalized_transcript
            )
            if is_conjunction_case:
                conjunction_cases += 1
                conjunction_false_splits += int(len(predicted) > 1)
            matches_by_expected = {
                expected_index: predicted_index
                for expected_index, predicted_index, score in boundary_matches
            }
            for expected_index, expected_label in enumerate(expected):
                if expected_label.structural_change is None:
                    continue
                structural_cases += 1
                predicted_index = matches_by_expected.get(expected_index)
                structural_hits += int(
                    predicted_index is not None
                    and predicted[predicted_index].structural_change
                    == expected_label.structural_change
                )
            matched_predicted = {
                predicted_index
                for _expected_index, predicted_index, _score in task_identity_matches
            }
            for predicted_index, predicted_label in enumerate(predicted):
                if predicted_label.confidence is None:
                    continue
                confidence_count += 1
                confidence_error += abs(
                    predicted_label.confidence
                    - float(predicted_index in matched_predicted)
                )
            if len(predicted) != len(expected) or title_matches != len(expected):
                failures.append(
                    EvaluationFailure(case.id, "extraction", "TASK_EXTRACTION_MISMATCH")
                )
            if case_invented_task_count:
                failures.append(
                    EvaluationFailure(case.id, "extraction", "INVENTED_TASK_IDENTITY")
                )

    extraction = None
    if extraction_cases:
        extraction = ExtractionQualityMetrics(
            exact_task_count_accuracy=exact_task_counts / extraction_cases,
            boundary_precision=(
                matched_boundaries / predicted_tasks if predicted_tasks else 0.0
            ),
            boundary_recall=(
                matched_boundaries / expected_tasks if expected_tasks else 0.0
            ),
            provenance_boundary_precision=(
                matched_provenance_boundaries / predicted_tasks
                if predicted_tasks
                else 0.0
            ),
            provenance_boundary_recall=(
                matched_provenance_boundaries / expected_tasks
                if expected_tasks
                else 0.0
            ),
            title_accuracy=(
                matched_titles / expected_tasks if expected_tasks else 0.0
            ),
            task_identity_accuracy=(
                matched_task_identities / expected_tasks if expected_tasks else 0.0
            ),
            invented_task_count=invented_task_count,
            conjunction_false_split_rate=(
                conjunction_false_splits / conjunction_cases
                if conjunction_cases
                else 0.0
            ),
            semantic_preservation_rate=(
                semantic_score_total / expected_tasks if expected_tasks else 0.0
            ),
            split_merge_accuracy=(
                structural_hits / structural_cases if structural_cases else None
            ),
            confidence_calibration_error=(
                confidence_error / confidence_count if confidence_count else None
            ),
        )
    return RealAudioEvaluationReport(
        status="completed",
        disabled_reason=None,
        case_count=len(cases),
        provider_models=provider_models,
        stt=aggregate.finish(),
        extraction=extraction,
        by_language={
            language: values.finish()
            for language, values in language_aggregates.items()
        },
        p95_latency_by_duration_language_provider_model={
            group: _percentile_95(values) for group, values in grouped_latencies.items()
        },
        failures=failures,
    )


@dataclass
class _MetricAccumulator:
    character_error_rate: float = 0.0
    word_error_rate: float = 0.0
    critical_term_hits: int = 0
    critical_term_total: int = 0
    omission_count: int = 0
    hallucination_count: int = 0
    latency_seconds: float = 0.0
    latency_samples: list[float] = field(default_factory=list)
    estimated_cost_usd: float = 0.0
    cost_estimate_bases: set[str] = field(default_factory=set)
    actual_cost_usd: float = 0.0
    actual_cost_count: int = 0
    provider_usage: dict[str, float] = field(default_factory=dict)
    count: int = 0

    def add(self, metrics: SttQualityMetrics) -> None:
        self.character_error_rate += metrics.character_error_rate
        self.word_error_rate += metrics.word_error_rate
        self.critical_term_hits += metrics.critical_term_hits
        self.critical_term_total += metrics.critical_term_total
        self.omission_count += metrics.omission_count
        self.hallucination_count += metrics.hallucination_count
        self.latency_seconds += metrics.mean_latency_seconds
        self.latency_samples.append(metrics.mean_latency_seconds)
        self.estimated_cost_usd += metrics.estimated_cost_usd
        self.cost_estimate_bases.update(metrics.cost_estimate_bases)
        if metrics.actual_cost_usd is not None:
            self.actual_cost_usd += metrics.actual_cost_usd
            self.actual_cost_count += 1
        for key, value in metrics.provider_usage.items():
            safe_usage = redacted_provider_usage({key: value})
            if key in safe_usage:
                self.provider_usage[key] = self.provider_usage.get(key, 0.0) + safe_usage[key]
        self.count += 1

    def finish(self) -> SttQualityMetrics:
        if not self.count:
            return _empty_stt_metrics()
        return SttQualityMetrics(
            character_error_rate=self.character_error_rate / self.count,
            word_error_rate=self.word_error_rate / self.count,
            critical_term_recall=(
                self.critical_term_hits / self.critical_term_total
                if self.critical_term_total
                else 1.0
            ),
            critical_term_hits=self.critical_term_hits,
            critical_term_total=self.critical_term_total,
            omission_count=self.omission_count,
            hallucination_count=self.hallucination_count,
            mean_latency_seconds=self.latency_seconds / self.count,
            p95_latency_seconds=_percentile_95(self.latency_samples),
            estimated_cost_usd=self.estimated_cost_usd,
            cost_estimate_bases=self.cost_estimate_bases,
            actual_cost_usd=(
                self.actual_cost_usd if self.actual_cost_count else None
            ),
            provider_usage=self.provider_usage,
        )


def _empty_stt_metrics() -> SttQualityMetrics:
    return SttQualityMetrics(
        character_error_rate=0.0,
        word_error_rate=0.0,
        critical_term_recall=0.0,
        critical_term_hits=0,
        critical_term_total=0,
        omission_count=0,
        hallucination_count=0,
        mean_latency_seconds=0.0,
        p95_latency_seconds=0.0,
        estimated_cost_usd=0.0,
        cost_estimate_bases=set(),
        actual_cost_usd=None,
        provider_usage={},
    )


def _score_stt(
    expected: str,
    predicted: str,
    critical_terms: list[str],
    latency_seconds: float,
    estimated_cost_usd: float,
    cost_estimate_basis: str | None,
    actual_cost_usd: float | None,
    provider_usage: dict[str, float],
) -> SttQualityMetrics:
    expected_chars = list(_normalized(expected))
    predicted_chars = list(_normalized(predicted))
    expected_words = _words(expected)
    predicted_words = _words(predicted)
    expected_counts = Counter(expected_words)
    predicted_counts = Counter(predicted_words)
    omissions = sum((expected_counts - predicted_counts).values())
    hallucinations = sum((predicted_counts - expected_counts).values())
    normalized_prediction = _normalized(predicted)
    term_hits = sum(_normalized(term) in normalized_prediction for term in critical_terms)
    return SttQualityMetrics(
        character_error_rate=_levenshtein(expected_chars, predicted_chars)
        / max(1, len(expected_chars)),
        word_error_rate=_levenshtein(expected_words, predicted_words)
        / max(1, len(expected_words)),
        critical_term_recall=(
            term_hits / len(critical_terms) if critical_terms else 1.0
        ),
        critical_term_hits=term_hits,
        critical_term_total=len(critical_terms),
        omission_count=omissions,
        hallucination_count=hallucinations,
        mean_latency_seconds=round(latency_seconds, 6),
        p95_latency_seconds=round(latency_seconds, 6),
        estimated_cost_usd=estimated_cost_usd,
        cost_estimate_bases=({cost_estimate_basis} if cost_estimate_basis else set()),
        actual_cost_usd=actual_cost_usd,
        provider_usage=provider_usage,
    )


def _redacted_failure_code(exc: Exception) -> str:
    if isinstance(exc, ProviderRetryableError):
        return "PROVIDER_RETRYABLE_ERROR"
    if isinstance(exc, ProviderTerminalError):
        return "PROVIDER_TERMINAL_ERROR"
    if isinstance(exc, ValidationFailure):
        return "RECONCILER_VALIDATION_FAILURE"
    return "INVALID_STRUCTURED_OUTPUT"


def _task_labels(
    raw_values: object, *, case_id: str, expected: bool
) -> list[_TaskLabel]:
    if not isinstance(raw_values, list):
        raise ValueError(
            f"{case_id}: expected tasks must be a JSON string list or labelled object list"
        )
    labels: list[_TaskLabel] = []
    for raw in raw_values:
        if isinstance(raw, str):
            labels.append(_TaskLabel(title=raw))
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get("title"), str):
            kind = "expected tasks" if expected else "extracted tasks"
            raise ValueError(f"{case_id}: {kind} require string titles")
        structural_change = raw.get("structural_change")
        if structural_change is not None and structural_change not in {"split", "merge"}:
            raise ValueError(f"{case_id}: structural_change must be split or merge")
        confidence_value = raw.get("confidence")
        confidence = float(confidence_value) if confidence_value is not None else None
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError(f"{case_id}: confidence must be between zero and one")
        source_spans_value = raw.get("source_spans", [])
        if not isinstance(source_spans_value, list):
            raise ValueError(f"{case_id}: source_spans must be a list of [start_ms, end_ms]")
        source_spans: list[tuple[int, int]] = []
        for span in source_spans_value:
            if (
                not isinstance(span, list)
                or len(span) != 2
                or not all(isinstance(value, int) for value in span)
                or span[0] < 0
                or span[1] <= span[0]
            ):
                raise ValueError(
                    f"{case_id}: source_spans require non-negative [start_ms, end_ms] pairs"
                )
            source_spans.append((span[0], span[1]))
        labels.append(
            _TaskLabel(
                title=str(raw["title"]),
                structural_change=(
                    str(structural_change) if structural_change is not None else None
                ),
                confidence=confidence,
                source_spans=tuple(source_spans),
            )
        )
    return labels


def _semantic_similarity(left: str, right: str) -> float:
    left_words = set(_words(left))
    right_words = set(_words(right))
    if not left_words or not right_words:
        return float(_normalized(left) == _normalized(right))
    return 2 * len(left_words & right_words) / (len(left_words) + len(right_words))


_TASK_IDENTITY_THRESHOLD = 0.95


def _match_task_labels(
    expected: list[_TaskLabel], predicted: list[_TaskLabel]
) -> list[tuple[int, int, float]]:
    candidates = sorted(
        (
            (_semantic_similarity(wanted.title, actual.title), expected_index, predicted_index)
            for expected_index, wanted in enumerate(expected)
            for predicted_index, actual in enumerate(predicted)
        ),
        reverse=True,
    )
    matched_expected: set[int] = set()
    matched_predicted: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for score, expected_index, predicted_index in candidates:
        if score <= 0:
            break
        if expected_index in matched_expected or predicted_index in matched_predicted:
            continue
        matched_expected.add(expected_index)
        matched_predicted.add(predicted_index)
        matches.append((expected_index, predicted_index, score))
    return matches


def _match_task_boundaries(
    expected: list[_TaskLabel], predicted: list[_TaskLabel]
) -> list[tuple[int, int, float]]:
    """Match genuine labelled source provenance, never title-token similarity."""

    predicted_by_spans: dict[tuple[tuple[int, int], ...], list[int]] = {}
    for predicted_index, label in enumerate(predicted):
        if label.source_spans:
            predicted_by_spans.setdefault(label.source_spans, []).append(predicted_index)
    matches: list[tuple[int, int, float]] = []
    for expected_index, label in enumerate(expected):
        if not label.source_spans:
            continue
        candidates = predicted_by_spans.get(label.source_spans)
        if candidates:
            matches.append((expected_index, candidates.pop(0), 1.0))
    return matches


def _percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, ((95 * len(ordered) + 99) // 100) - 1)
    return round(ordered[index], 6)


def _duration_cohort(duration_seconds: float) -> str:
    if duration_seconds < 30:
        return "<30s"
    if duration_seconds <= 120:
        return "30-120s"
    return ">120s"


def _language_cohort(language_hints: list[str]) -> str:
    normalized = {value.casefold().split("-", 1)[0] for value in language_hints}
    if normalized == {"ru", "en"}:
        return "ru-en"
    if len(normalized) == 1:
        return next(iter(normalized))
    return "+".join(sorted(normalized)) or "unknown"


def _words(value: str) -> list[str]:
    return re.findall(r"\w+", value.casefold(), flags=re.UNICODE)


def _levenshtein(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_value in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_value in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_value != right_value),
                )
            )
        previous = current
    return previous[-1]


def _load_real_audio_cases(corpus_root: Path) -> list[_RealAudioCase]:
    root = corpus_root.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1:
        raise ValueError("Unsupported real-audio evaluation manifest version")
    cases: list[_RealAudioCase] = []
    for raw in manifest.get("cases", []):
        case_id = str(raw["id"])
        cases.append(
            _RealAudioCase(
                id=case_id,
                audio_path=_corpus_path(root, raw["audio_file"]),
                transcript_path=_corpus_path(
                    root, raw["ground_truth_transcript_file"]
                ),
                expected_tasks_path=(
                    _corpus_path(root, raw["expected_tasks_file"])
                    if raw.get("expected_tasks_file")
                    else None
                ),
                language_hints=[str(value) for value in raw.get("language_hints", [])],
                vocabulary=[str(value) for value in raw.get("vocabulary", [])],
                critical_terms=[str(value) for value in raw.get("critical_terms", [])],
                duration_seconds=(
                    float(raw["duration_seconds"])
                    if raw.get("duration_seconds") is not None
                    else None
                ),
            )
        )
    if not cases:
        raise ValueError("Real-audio evaluation corpus contains no cases")
    return cases


def _corpus_path(root: Path, relative_value: object) -> Path:
    candidate = (root / str(relative_value)).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Evaluation corpus path escapes its root")
    if not candidate.is_file():
        raise ValueError("Evaluation corpus file is missing")
    return candidate
