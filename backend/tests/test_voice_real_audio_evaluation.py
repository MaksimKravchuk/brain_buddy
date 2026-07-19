"""Tests for the external real-audio Voice Brain Dump evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.workflows.voice_brain_dump.domain import ProposalPatch, TranscriptHypothesis
from app.workflows.voice_brain_dump.evaluation import (
    _TaskLabel,
    _duration_cohort,
    _language_cohort,
    _match_task_labels,
    _percentile_95,
    _semantic_similarity,
    _task_labels,
    build_semantic_extractor,
    evaluate_real_audio_corpus,
)
from app.workflows.voice_brain_dump.providers import (
    AccurateSttRequest,
    DisabledAccurateStt,
    ReconcileResult,
    SttResult,
)


class RecordingProvider:
    provider_name = "evaluation-provider"
    requires_external_processing = True

    def __init__(self, transcript: str | dict[str, str]) -> None:
        self.transcript = transcript
        self.requests: list[AccurateSttRequest] = []

    def transcribe_sealed_audio(self, request: AccurateSttRequest) -> SttResult:
        self.requests.append(request)
        transcript = (
            self.transcript[request.operation_id]
            if isinstance(self.transcript, dict)
            else self.transcript
        )
        return SttResult(
            role="accurate",
            provider=self.provider_name,
            input_hash="input-hash",
            segments=[
                TranscriptHypothesis(
                    id="segment_1",
                    sequence=1,
                    start_ms=0,
                    end_ms=1000,
                    text=transcript,
                    stability="stable",
                    provider_role="accurate",
                    language=",".join(request.language_hints),
                    model="model-v1",
                )
            ],
            estimated_cost_usd=0.1,
        )


class RecordingReconciler:
    provider_id = "semantic-evaluation"
    requires_external_processing = True

    def reconcile(self, request):
        segment = request.transcript_segments[0]
        return ReconcileResult(
            input_hash="semantic-input",
            patches=[
                ProposalPatch.add(
                    proposal_id="proposal_1",
                    title="Починить BrainBuddy",
                    source_segment_ids=[segment.id],
                    producer="reconciler",
                ),
                ProposalPatch.remove(
                    proposal_id="proposal_removed",
                    producer="reconciler",
                ),
            ],
            confidences={"proposal_1": 0.8},
        )


def _corpus(tmp_path: Path) -> Path:
    audio = b"RIFF\x00\x00\x00\x00WAVE-real-founder-audio"
    (tmp_path / "sample.webm").write_bytes(audio)
    (tmp_path / "sample.transcript.txt").write_text(
        "Надо починить BrainBuddy и сделать production smoke", encoding="utf-8"
    )
    (tmp_path / "sample.tasks.json").write_text(
        json.dumps(["Починить BrainBuddy", "Сделать production smoke"]),
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [
                    {
                        "id": "founder-ru-en-1",
                        "audio_file": "sample.webm",
                        "ground_truth_transcript_file": "sample.transcript.txt",
                        "expected_tasks_file": "sample.tasks.json",
                        "language_hints": ["ru", "en"],
                        "vocabulary": ["BrainBuddy", "production smoke"],
                        "critical_terms": ["BrainBuddy", "production smoke"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_real_audio_harness_calls_provider_with_audio_not_expected_transcript(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider(
        "Надо починить BrainBuddy и сделать production smoke"
    )

    report = evaluate_real_audio_corpus(
        _corpus(tmp_path),
        provider,
        external_processing_allowed=True,
        extractor=lambda _transcript: [
            "Починить BrainBuddy",
            "Сделать production smoke",
        ],
        monotonic_values=iter((10.0, 10.4)).__next__,
    )

    assert report.status == "completed"
    assert report.case_count == 1
    assert provider.requests[0].sealed_audio == (tmp_path / "sample.webm").read_bytes()
    assert provider.requests[0].language_hints == ["ru", "en"]
    assert provider.requests[0].vocabulary == ["BrainBuddy", "production smoke"]
    assert not hasattr(provider.requests[0], "expected_transcript")
    assert report.stt.character_error_rate == 0
    assert report.stt.word_error_rate == 0
    assert report.stt.critical_term_recall == 1
    assert report.stt.omission_count == 0
    assert report.stt.hallucination_count == 0
    assert report.stt.mean_latency_seconds == 0.4
    assert report.extraction is not None
    assert report.extraction.exact_task_count_accuracy == 1
    assert report.extraction.title_accuracy == 1
    assert report.provider_models == {"evaluation-provider/model-v1"}
    assert report.failures == []


def test_semantic_extractor_scores_provider_generated_proposals() -> None:
    extractor = build_semantic_extractor(RecordingReconciler())

    assert extractor("Надо разобраться с brain body") == [
        {
            "title": "Починить BrainBuddy",
            "structural_change": None,
            "confidence": 0.8,
        }
    ]


def test_real_audio_harness_reports_stt_and_extraction_failures_separately(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider("Надо починить brain body")

    report = evaluate_real_audio_corpus(
        _corpus(tmp_path),
        provider,
        external_processing_allowed=True,
        extractor=lambda _transcript: ["Починить brain body"],
        monotonic_values=iter((1.0, 2.0)).__next__,
    )

    assert report.stt.word_error_rate > 0
    assert report.stt.critical_term_recall < 1
    assert report.extraction is not None
    assert report.extraction.exact_task_count_accuracy == 0
    assert any(failure.stage == "stt" for failure in report.failures)
    assert any(failure.stage == "extraction" for failure in report.failures)


def test_task_boundaries_are_scored_separately_from_title_wording(tmp_path: Path) -> None:
    provider = RecordingProvider(
        "Нужно починить BrainBuddy. Потом сделать production smoke."
    )

    report = evaluate_real_audio_corpus(
        _corpus(tmp_path),
        provider,
        external_processing_allowed=True,
        extractor=lambda _transcript: [
            "Починить BrainBuddy",
            "Сделать production check",
        ],
        monotonic_values=iter((1.0, 1.1)).__next__,
    )

    assert report.extraction is not None
    assert report.extraction.exact_task_count_accuracy == 1
    assert report.extraction.boundary_precision == 1
    assert report.extraction.boundary_recall == 1
    assert report.extraction.title_accuracy == 0.5


def test_same_count_invented_tasks_do_not_match_labelled_boundaries(
    tmp_path: Path,
) -> None:
    report = evaluate_real_audio_corpus(
        _corpus(tmp_path),
        RecordingProvider(
            "Нужно починить BrainBuddy. Потом сделать production smoke."
        ),
        external_processing_allowed=True,
        extractor=lambda _transcript: ["Купить яхту", "Выучить латынь"],
        monotonic_values=iter((1.0, 1.1)).__next__,
    )

    assert report.extraction is not None
    assert report.extraction.exact_task_count_accuracy == 1
    assert report.extraction.boundary_precision == 0
    assert report.extraction.boundary_recall == 0
    assert report.extraction.semantic_preservation_rate == 0


def test_rich_labels_score_split_merge_confidence_and_grouped_p95_latency(
    tmp_path: Path,
) -> None:
    corpus = _corpus(tmp_path)
    (corpus / "sample.tasks.json").write_text(
        json.dumps(
            [
                {
                    "title": "Починить BrainBuddy",
                    "structural_change": "split",
                },
                {"title": "Сделать production smoke"},
            ]
        ),
        encoding="utf-8",
    )
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    manifest["cases"][0]["duration_seconds"] = 42
    (corpus / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    report = evaluate_real_audio_corpus(
        corpus,
        RecordingProvider("Надо починить BrainBuddy и сделать production smoke"),
        external_processing_allowed=True,
        extractor=lambda _transcript: [
            {
                "title": "Починить BrainBuddy",
                "structural_change": "split",
                "confidence": 0.8,
            },
            {"title": "Сделать production smoke", "confidence": 0.6},
        ],
        monotonic_values=iter((1.0, 1.4)).__next__,
    )

    assert report.extraction is not None
    assert report.extraction.split_merge_accuracy == 1
    assert report.extraction.confidence_calibration_error == pytest.approx(0.3)
    assert report.stt.p95_latency_seconds == pytest.approx(0.4)
    assert report.p95_latency_by_duration_language_provider_model == {
        "30-120s|ru-en|evaluation-provider/model-v1": pytest.approx(0.4)
    }


def test_real_audio_harness_uses_disjoint_language_cohorts_and_micro_averages_terms(
    tmp_path: Path,
) -> None:
    corpus = _corpus(tmp_path)
    (corpus / "mixed.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVE-mixed")
    (corpus / "mixed.transcript.txt").write_text(
        "Сделать production smoke и позвонить Наташе", encoding="utf-8"
    )
    (corpus / "mixed.tasks.json").write_text(
        json.dumps(["Сделать production smoke"]), encoding="utf-8"
    )
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    manifest["cases"][0]["language_hints"] = ["ru"]
    manifest["cases"][0]["critical_terms"] = ["BrainBuddy", "production smoke"]
    manifest["cases"].append(
        {
            "id": "founder-ru-en-2",
            "audio_file": "mixed.wav",
            "ground_truth_transcript_file": "mixed.transcript.txt",
            "expected_tasks_file": "mixed.tasks.json",
            "language_hints": ["ru", "en"],
            "critical_terms": ["production smoke"],
        }
    )
    (corpus / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    provider = RecordingProvider(
        {
            "founder-ru-en-1": "Надо починить BrainBuddy",
            "founder-ru-en-2": "Сделать production smoke",
        }
    )

    report = evaluate_real_audio_corpus(
        corpus,
        provider,
        external_processing_allowed=True,
        extractor=lambda transcript: (
            ["Сделать production smoke", "Позвонить Наташе"]
            if "production smoke" in transcript
            else ["Починить BrainBuddy"]
        ),
        monotonic_values=iter((1.0, 1.2, 2.0, 2.4)).__next__,
    )

    assert report.stt.critical_term_recall == pytest.approx(2 / 3)
    assert report.stt.critical_term_hits == 2
    assert report.stt.critical_term_total == 3
    assert report.stt.estimated_cost_usd == pytest.approx(0.2)
    assert set(report.by_language) == {"ru", "ru-en"}
    assert report.by_language["ru-en"].critical_term_recall == 1
    assert report.extraction is not None
    assert report.extraction.conjunction_false_split_rate == 1
    assert report.extraction.semantic_preservation_rate == pytest.approx(2 / 3)
    assert report.extraction.confidence_calibration_error is None


def test_real_audio_harness_is_explicitly_disabled_without_consent(
    tmp_path: Path,
) -> None:
    provider = RecordingProvider("must not be called")

    report = evaluate_real_audio_corpus(
        _corpus(tmp_path), provider, external_processing_allowed=False
    )

    assert report.status == "disabled"
    assert report.disabled_reason == "EXTERNAL_PROCESSING_CONSENT_REQUIRED"
    assert report.case_count == 0
    assert provider.requests == []


def test_real_audio_harness_is_explicitly_disabled_without_a_provider(
    tmp_path: Path,
) -> None:
    report = evaluate_real_audio_corpus(
        _corpus(tmp_path),
        DisabledAccurateStt("STT_PROVIDER_CREDENTIALS_MISSING"),
        external_processing_allowed=True,
    )

    assert report.status == "disabled"
    assert report.disabled_reason == "STT_PROVIDER_CREDENTIALS_MISSING"


def test_real_audio_harness_can_score_stt_without_extraction(tmp_path: Path) -> None:
    report = evaluate_real_audio_corpus(
        _corpus(tmp_path),
        RecordingProvider("Надо починить BrainBuddy и сделать production smoke"),
        external_processing_allowed=True,
        monotonic_values=iter((1.0, 1.1)).__next__,
    )

    assert report.status == "completed"
    assert report.extraction is None


def test_real_audio_harness_rejects_invalid_expected_task_documents(
    tmp_path: Path,
) -> None:
    corpus = _corpus(tmp_path)
    (corpus / "sample.tasks.json").write_text('{"title": "not a list"}')

    with pytest.raises(ValueError, match="expected tasks must be a JSON string list"):
        evaluate_real_audio_corpus(
            corpus,
            RecordingProvider("transcript"),
            external_processing_allowed=True,
            extractor=lambda _transcript: [],
            monotonic_values=iter((1.0, 1.1)).__next__,
        )


@pytest.mark.parametrize(
    ("raw_values", "expected", "message"),
    [
        ([{}], True, "expected tasks require string titles"),
        ([{}], False, "extracted tasks require string titles"),
        (
            [{"title": "Task", "structural_change": "update"}],
            True,
            "structural_change must be split or merge",
        ),
        (
            [{"title": "Task", "confidence": 1.1}],
            False,
            "confidence must be between zero and one",
        ),
    ],
)
def test_labelled_task_metrics_reject_invalid_labels(
    raw_values: object, expected: bool, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _task_labels(raw_values, case_id="invalid-label", expected=expected)


def test_latency_helpers_cover_empty_short_and_long_duration_cohorts() -> None:
    assert _percentile_95([]) == 0
    assert _duration_cohort(29.9) == "<30s"
    assert _duration_cohort(121) == ">120s"
    assert _language_cohort([]) == "unknown"
    assert _semantic_similarity("", "") == 1
    assert _match_task_labels(
        [_TaskLabel("Same task"), _TaskLabel("Same task")],
        [_TaskLabel("Same task")],
    ) == [(1, 0, 1.0)]


@pytest.mark.parametrize(
    ("manifest", "message"),
    [
        ({"version": 2, "cases": []}, "Unsupported real-audio evaluation manifest"),
        ({"version": 1, "cases": []}, "contains no cases"),
        (
            {
                "version": 1,
                "cases": [
                    {
                        "id": "escape",
                        "audio_file": "../outside.webm",
                        "ground_truth_transcript_file": "sample.transcript.txt",
                    }
                ],
            },
            "escapes its root",
        ),
        (
            {
                "version": 1,
                "cases": [
                    {
                        "id": "missing",
                        "audio_file": "missing.webm",
                        "ground_truth_transcript_file": "sample.transcript.txt",
                    }
                ],
            },
            "file is missing",
        ),
    ],
)
def test_real_audio_harness_rejects_unsafe_or_incomplete_manifests(
    tmp_path: Path, manifest: dict[str, object], message: str
) -> None:
    corpus = _corpus(tmp_path)
    (corpus / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        evaluate_real_audio_corpus(
            corpus,
            RecordingProvider("transcript"),
            external_processing_allowed=True,
        )
