"""Release-gate coverage for the labelled Voice Brain Dump evaluation set."""

import hashlib
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.workflows.voice_brain_dump import evaluation, providers
from app.workflows.voice_brain_dump.evaluation import (
    _case_languages,
    _EvaluationCase,
    _load_cases,
    _validated_audio,
    evaluate_release_dataset,
)


def test_labelled_multilingual_text_and_audio_release_metrics_meet_fixed_gates() -> (
    None
):
    report = evaluate_release_dataset()

    assert report.case_count >= 6
    assert report.audio_case_count >= 6
    assert report.languages >= {"en", "nl", "ru"}
    assert report.modalities == {"audio", "text"}
    assert report.provider_model_version == "deterministic-accurate-v1"
    assert report.audio_signal_accuracy >= 0.95
    assert report.task_boundary_precision >= 0.95
    assert report.task_boundary_recall >= 0.95
    assert report.exact_count_accuracy >= 0.95
    assert report.title_cleanliness >= 0.95
    assert report.code_switch_term_accuracy >= 0.95
    assert report.conjunction_false_split_rate == 0
    assert report.split_merge_accuracy >= 0.95
    assert report.confidence_calibration_error <= 0.05
    assert set(report.by_language) >= {"en", "nl", "ru"}
    assert report.structural_lineage_cases >= 2
    assert report.failures == []


def test_release_audio_cases_are_real_versioned_wav_fixtures() -> None:
    fixture_root = Path(__file__).parent / "fixtures" / "voice_brain_dump" / "v1"
    audio_files = sorted(fixture_root.glob("*.wav"))

    assert len(audio_files) >= 6
    for audio_file in audio_files:
        payload = audio_file.read_bytes()
        assert payload[:4] == b"RIFF"
        assert payload[8:12] == b"WAVE"
        assert len(payload) > 1_000


def test_manifest_loader_rejects_unknown_versions_and_normalizes_legacy_fields(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": 2, "fixtures": []}))
    with pytest.raises(ValueError, match="Unsupported"):
        _load_cases(tmp_path)

    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "fixtures": [
                    {
                        "id": "ML-01",
                        "language": "en",
                        "text": "Call dentist",
                        "expected_titles": ["Call dentist"],
                        "audio_file": "fixture.wav",
                        "audio_sha256": "digest",
                    },
                    {"id": "ML-08"},
                ],
            }
        )
    )
    cases = _load_cases(tmp_path)
    assert len(cases) == 1
    assert cases[0].languages == ("en",)
    assert cases[0].structural_change is None
    assert cases[0].code_switch_terms == ()
    assert _case_languages(cases[0]) == ("en",)
    assert _case_languages(cases[0].__class__(**{**cases[0].__dict__, "languages": ()})) == (
        "unknown",
    )


def test_audio_validation_rejects_hash_format_and_duration_mismatches(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "fixture.wav"

    def write_audio(*, channels: int = 1, rate: int = 16_000, frames: int = 8_000) -> bytes:
        with wave.open(str(audio_path), "wb") as fixture:
            fixture.setnchannels(channels)
            fixture.setsampwidth(2)
            fixture.setframerate(rate)
            fixture.writeframes(b"\0\0" * channels * frames)
        return audio_path.read_bytes()

    def case(payload: bytes, digest: str | None = None) -> _EvaluationCase:
        return _EvaluationCase(
            id="ML-test",
            languages=("en",),
            transcript="Call dentist",
            expected_titles=("Call dentist",),
            audio_path=audio_path,
            audio_sha256=digest or hashlib.sha256(payload).hexdigest(),
            code_switch_terms=(),
            structural_change=None,
            expected_confidence=1.0,
            expected_frequency_hz=None,
        )

    payload = write_audio()
    with pytest.raises(ValueError, match="hash"):
        _validated_audio(case(payload, "wrong"))

    payload = write_audio(channels=2)
    with pytest.raises(ValueError, match="mono"):
        _validated_audio(case(payload))

    payload = write_audio(rate=8_000, frames=4_000)
    with pytest.raises(ValueError, match="500 ms"):
        _validated_audio(case(payload))


def test_evaluation_reports_provider_text_audio_and_title_mismatches(monkeypatch) -> None:
    class MismatchingProvider:
        def __init__(self, _transcripts) -> None:
            pass

        def transcribe_sealed_audio(self, _request):
            return SimpleNamespace(
                segments=[SimpleNamespace(text="Completely different task")]
            )

    monkeypatch.setattr(evaluation, "DeterministicAccurateStt", MismatchingProvider)
    report = evaluate_release_dataset()

    assert any("audio transcript mismatch" in failure for failure in report.failures)
    assert any("text/audio intent mismatch" in failure for failure in report.failures)
    assert any("titles" in failure for failure in report.failures)


def test_audio_gate_rejects_wav_files_permuted_between_labels(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "voice_brain_dump" / "v1"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    fixtures = [fixture for fixture in manifest["fixtures"] if fixture.get("audio_file")]
    audio_payloads = [
        (source / fixture["audio_file"]).read_bytes() for fixture in fixtures
    ]

    for fixture, payload in zip(fixtures, audio_payloads[1:] + audio_payloads[:1], strict=True):
        (tmp_path / fixture["audio_file"]).write_bytes(payload)
        fixture["audio_sha256"] = hashlib.sha256(payload).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = evaluate_release_dataset(tmp_path)

    assert report.audio_signal_accuracy < 0.95
    assert any("audio signal mismatch" in failure for failure in report.failures)


def test_deterministic_provider_tolerates_unknown_failure_plans_and_empty_cleanups(
    monkeypatch,
) -> None:
    provider = providers.DeterministicAccurateStt(
        fail_plan={"media": ["unknown-outcome"]}
    )
    result = provider.transcribe_sealed_audio(
        providers.AccurateSttRequest(
            operation_id="operation",
            media_ref="media",
            sealed_audio=b"Call dentist",
        )
    )
    assert result.segments[0].text == "Call dentist"

    monkeypatch.setattr(providers.re, "sub", lambda *_args, **_kwargs: "")
    assert providers._extract_titles("content") == ["Content"]
