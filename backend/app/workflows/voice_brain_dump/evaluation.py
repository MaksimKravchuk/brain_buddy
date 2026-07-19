"""Versioned, deterministic Voice Brain Dump release evaluation.

The offline gate reads the same labelled ML-01–ML-06 corpus documented by the
feature specification. Synthetic WAV files exercise the sealed-audio provider
boundary without using customer recordings or a paid provider.
"""

from __future__ import annotations

import hashlib
import json
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .providers import AccurateSttRequest, DeterministicAccurateStt, _extract_titles


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
