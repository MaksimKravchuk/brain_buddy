"""Release-gate coverage for the labelled Voice Brain Dump evaluation set."""

import hashlib
import json
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.workflows.voice_brain_dump import evaluation, providers
from app.workflows.voice_brain_dump.domain import (
    BrainDumpAudioChunkDocument,
    BrainDumpConsent,
    BrainDumpOperationDocument,
    BrainDumpProposalDocument,
    BrainDumpProviderRunDocument,
    BrainDumpTranscriptSegmentDocument,
)
from app.workflows.voice_brain_dump.evaluation import (
    _case_languages,
    _EvaluationCase,
    _load_cases,
    _validated_audio,
    evaluate_release_dataset,
)
from app.workflows.voice_brain_dump.language_fidelity import (
    ScriptLabel,
    classify_title_fidelity,
    dominant_script,
    title_is_language_faithful,
)
from app.workflows.voice_brain_dump.operational_evidence import (
    MODE_TEXT_RECONCILER,
    build_full_recording_run,
    build_run_artifact,
    build_run_artifact_from_operations,
    build_utterance_run,
    compute_operational_evidence,
    load_reference_corpus,
    run_artifact_from_dict,
    run_artifact_to_dict,
    seal_manifest_hash,
    titled_sources_from_operation_response,
)
from app.workflows.voice_brain_dump.service import VoiceBrainDumpService

_CORPUS_ROOT = (
    Path(__file__).parent / "fixtures" / "voice_brain_dump" / "reference_corpus"
)
_CORPUS_PATH = _CORPUS_ROOT / "founder_ru_reading_script.v1.json"
_RECORDED_ARTIFACT_PATH = _CORPUS_ROOT / "recorded_run_artifact.v2.json"
_EXAMPLE_REPORT_PATH = _CORPUS_ROOT / "example_report.redacted.v2.json"


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
    assert _case_languages(
        cases[0].__class__(**{**cases[0].__dict__, "languages": ()})
    ) == ("unknown",)


def test_audio_validation_rejects_hash_format_and_duration_mismatches(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "fixture.wav"

    def write_audio(
        *, channels: int = 1, rate: int = 16_000, frames: int = 8_000
    ) -> bytes:
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


def test_evaluation_reports_provider_text_audio_and_title_mismatches(
    monkeypatch,
) -> None:
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
    fixtures = [
        fixture for fixture in manifest["fixtures"] if fixture.get("audio_file")
    ]
    audio_payloads = [
        (source / fixture["audio_file"]).read_bytes() for fixture in fixtures
    ]

    for fixture, payload in zip(
        fixtures, audio_payloads[1:] + audio_payloads[:1], strict=True
    ):
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
        fail_plan={"media": ["unknown-outcome"]}, allow_text_fixture_audio=True
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


# --- SC-003 title language-fidelity classifier (T035) ----------------------
#
# The classifier is the shared oracle behind the SC-003 metric and the FR-006
# reconciler invariant (T037). It must distinguish a *translation* (the ordinary
# spoken words rewritten into another language) from faithful inflection, an
# embedded foreign proper noun, or a mere identity difference.


@pytest.mark.parametrize(
    ("title", "source_text", "verdict"),
    [
        # Faithful Russian inflection / grounded rewording is NOT a violation.
        ("Позвонить Анне", "напомни мне завтра позвонить Анне", "faithful"),
        (
            "Позвонить в банк",
            "надо позвонить в банк потом оплатить интернет",
            "faithful",
        ),
        # An English translation of a Russian utterance IS a violation.
        ("Call Anna", "напомни мне завтра позвонить Анне", "translated"),
        ("Buy bread and milk", "добавь молоко и хлеб в список покупок", "translated"),
        # Code-switched source words are preserved, not counted as a violation.
        (
            "Починить BrainBuddy",
            "надо починить BrainBuddy и написать Наташе",
            "faithful",
        ),
        (
            "Протестировать production smoke на staging",
            "потом протестировать production smoke на staging",
            "faithful",
        ),
        # A Latin-only utterance yields a Latin-script title (same language).
        (
            "Deploy the BrainBuddy release",
            "please deploy the BrainBuddy release",
            "faithful",
        ),
        # Same-script language pairs (NL↔EN) are out of scope for a script check.
        ("De dokter bellen", "ik moet de dokter bellen", "faithful"),
        # A different named target is an identity mismatch (grounding's concern),
        # not a translation: the ordinary words stay in the source language.
        ("Написать Bob", "надо написать Alice про отчет", "faithful"),
        # A garbled proper noun corrected in the title is still the same term.
        (
            "Создать проект BrainBuddy launch",
            "Создай проект grainbuddy launch.",
            "faithful",
        ),
        # A partial translation that keeps the proper noun is still a violation.
        ("Fix BrainBuddy", "надо починить BrainBuddy", "translated"),
    ],
)
def test_sc003_title_language_fidelity_classifier(
    title: str, source_text: str, verdict: str
) -> None:
    result = classify_title_fidelity(title, source_text)
    assert result.verdict.value == verdict
    assert title_is_language_faithful(title, source_text) is (verdict != "translated")


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("позвонить Анне", ScriptLabel.CYRILLIC),
        ("Buy milk", ScriptLabel.LATIN),
        ("аб cd", ScriptLabel.MIXED),
        ("", ScriptLabel.NEUTRAL),
        ("123 -- :)", ScriptLabel.NEUTRAL),
        # A third script carries no Cyrillic/Latin language signal.
        ("αβγ ελληνικά", ScriptLabel.NEUTRAL),
    ],
)
def test_dominant_script_labels(text: str, label: ScriptLabel) -> None:
    assert dominant_script(text) is label


def test_language_fidelity_distance_and_garble_helper_edges() -> None:
    from app.workflows.voice_brain_dump import language_fidelity

    assert language_fidelity._damerau_levenshtein("", "abc") == 3
    assert language_fidelity._damerau_levenshtein("abc", "") == 3
    # Identical long tokens are trivially the same preserved term.
    assert language_fidelity._garble_equivalent("brainbuddy", "brainbuddy") is True
    # Short tokens never qualify for garble tolerance.
    assert language_fidelity._garble_equivalent("bob", "rob") is False


# --- Reference corpus ground truth (T035) ----------------------------------


def test_reference_corpus_fixture_is_versioned_and_complete() -> None:
    corpus = load_reference_corpus(_CORPUS_PATH)

    assert corpus.corpus_id == "founder_ru_reading_script"
    assert corpus.version == 1
    assert [utterance.n for utterance in corpus.utterances] == list(range(1, 51))
    assert sum(utterance.task_yielding for utterance in corpus.utterances) == 43
    assert (
        sum(utterance.conjunction_single_intent for utterance in corpus.utterances)
        == 22
    )
    assert sum(utterance.category == "multi" for utterance in corpus.utterances) == 3
    # The digest is content-addressed to the label fields only and is stable.
    assert len(corpus.digest) == 64
    assert load_reference_corpus(_CORPUS_PATH).digest == corpus.digest


# --- Operational evidence report from a recorded artifact (T035) ------------


def _load_recorded_artifact() -> dict:
    return json.loads(_RECORDED_ARTIFACT_PATH.read_text(encoding="utf-8"))


def test_operational_evidence_report_from_recorded_artifact() -> None:
    corpus = load_reference_corpus(_CORPUS_PATH)
    artifact = run_artifact_from_dict(_load_recorded_artifact())

    report = compute_operational_evidence(artifact, corpus)

    assert report.all_passed
    assert report.criterion("SC-001").detail["committed_task_count"] == 17
    sc002 = report.criterion("SC-002").detail
    assert sc002["correct_hits"] == 38
    assert sc002["task_yielding_total"] == 43
    assert sc002["ratio"] == 0.8837
    assert sc002["miss_breakdown"]["count_mismatch"] == 5
    assert report.criterion("SC-003").detail["translated_titles"] == 0
    sc004 = report.criterion("SC-004").detail
    assert sc004["conjunction_false_splits"] == 0
    assert sc004["conjunction_eligible"] == 22
    assert (
        report.criterion("SC-007").detail["seal_to_awaiting_confirmation_seconds"]
        == 41.2
    )
    # Every criterion is stamped with the real pipeline that produced it.
    assert all(
        result.detail["evidence_mode"] == "sealed_audio_pipeline"
        for result in report.criteria
    )
    assert report.coverage == {"utterances_scored": 50, "utterances_in_corpus": 50}


def test_operational_evidence_report_matches_committed_example() -> None:
    corpus = load_reference_corpus(_CORPUS_PATH)
    artifact = run_artifact_from_dict(_load_recorded_artifact())

    report = compute_operational_evidence(artifact, corpus)

    golden = json.loads(_EXAMPLE_REPORT_PATH.read_text(encoding="utf-8"))
    assert report.to_dict() == golden
    # Report id is a content address: recomputation is byte-stable.
    assert compute_operational_evidence(artifact, corpus).report_id == report.report_id


def test_report_run_key_and_id_are_hash_addressed_to_inputs() -> None:
    corpus = load_reference_corpus(_CORPUS_PATH)
    base = compute_operational_evidence(
        run_artifact_from_dict(_load_recorded_artifact()), corpus
    )

    provider_changed = _load_recorded_artifact()
    provider_changed["run_identity"]["provider_config"][
        "reconciler_model"
    ] = "gpt-4o-mini"
    provider_report = compute_operational_evidence(
        run_artifact_from_dict(provider_changed), corpus
    )
    assert provider_report.run_key != base.run_key
    assert provider_report.report_id != base.report_id

    sha_changed = _load_recorded_artifact()
    sha_changed["run_identity"]["git_sha"] = "0" * 40
    assert (
        compute_operational_evidence(
            run_artifact_from_dict(sha_changed), corpus
        ).run_key
        != base.run_key
    )

    # A metric change re-addresses the report but not the run identity key.
    metric_changed = _load_recorded_artifact()
    metric_changed["full_recording"]["committed_task_count"] = 25
    metric_report = compute_operational_evidence(
        run_artifact_from_dict(metric_changed), corpus
    )
    assert metric_report.run_key == base.run_key
    assert metric_report.report_id != base.report_id


def test_compute_rejects_corpus_digest_mismatch() -> None:
    corpus = load_reference_corpus(_CORPUS_PATH)
    mismatched = _load_recorded_artifact()
    mismatched["run_identity"]["corpus_digest"] = "0" * 64

    with pytest.raises(ValueError, match="corpus digest"):
        compute_operational_evidence(run_artifact_from_dict(mismatched), corpus)


def test_run_artifact_round_trips_through_dict() -> None:
    artifact = run_artifact_from_dict(_load_recorded_artifact())
    assert run_artifact_from_dict(run_artifact_to_dict(artifact)) == artifact


def test_run_artifact_from_dict_rejects_unknown_schema_version() -> None:
    raw = _load_recorded_artifact()
    raw["schema_version"] = 99
    with pytest.raises(ValueError, match="schema version"):
        run_artifact_from_dict(raw)


def test_report_and_artifact_carry_no_raw_transcript_text() -> None:
    corpus = load_reference_corpus(_CORPUS_PATH)
    artifact = run_artifact_from_dict(_load_recorded_artifact())
    report = compute_operational_evidence(artifact, corpus)

    artifact_blob = json.dumps(run_artifact_to_dict(artifact), ensure_ascii=False)
    report_blob = json.dumps(report.to_dict(), ensure_ascii=False)
    # Principle I: no raw Cyrillic transcript/title content anywhere.
    for blob in (artifact_blob, report_blob):
        assert not any("Ѐ" <= character <= "ӿ" for character in blob)
        for leaked in ("BrainBuddy", "staging", "milk", "dentist", "Наташе"):
            assert leaked not in blob


# --- Live mode: project persisted operations into an artifact (T035) --------


def _consented_operation(
    *,
    operation_id: str,
    now: datetime,
    segments: list[BrainDumpTranscriptSegmentDocument],
    proposals: list[BrainDumpProposalDocument],
    provider_runs: list[BrainDumpProviderRunDocument] | None = None,
    committed_task_ids: list[str] | None = None,
) -> BrainDumpOperationDocument:
    return BrainDumpOperationDocument(
        id=operation_id,
        owner_id="owner-eval",
        status="awaiting_confirmation",
        consent=BrainDumpConsent(microphone=True, recorded_at=now),
        segments=segments,
        proposals=proposals,
        provider_runs=provider_runs or [],
        committed_task_ids=committed_task_ids or [],
        created_at=now,
        updated_at=now,
    )


def test_build_run_artifact_from_live_operations_is_privacy_safe_and_scorable() -> None:
    now = datetime(2026, 7, 29, 12, 0, 0, tzinfo=UTC)
    corpus = load_reference_corpus(_CORPUS_PATH)

    segment = BrainDumpTranscriptSegmentDocument(
        id="segment_u25",
        sequence=1,
        text="Добавь молоко и хлеб в список покупок",
        stability="stable",
        start_ms=0,
        end_ms=1300,
        provider_role="accurate",
        created_at=now,
    )
    faithful = BrainDumpProposalDocument(
        id="proposal_faithful",
        ordinal=1,
        title="Купить молоко и хлеб",
        source_segment_ids=[segment.id],
        created_at=now,
        updated_at=now,
    )
    translated = BrainDumpProposalDocument(
        id="proposal_translated",
        ordinal=2,
        title="Buy milk and bread",
        source_segment_ids=[segment.id],
        created_at=now,
        updated_at=now,
    )
    deleted = BrainDumpProposalDocument(
        id="proposal_deleted",
        ordinal=3,
        title="Купить сыр",
        source_segment_ids=[segment.id],
        deleted=True,
        created_at=now,
        updated_at=now,
    )
    utterance_op = _consented_operation(
        operation_id="operation_u25",
        now=now,
        segments=[segment],
        proposals=[faithful, translated, deleted],
    )

    seal_run = BrainDumpProviderRunDocument(
        id="run_accurate",
        role="accurate_stt",
        status="succeeded",
        input_hash="0" * 64,
        checkpoint="accurate_transcribed",
        created_at=now,
        updated_at=now,
    )
    reconcile_run = BrainDumpProviderRunDocument(
        id="run_reconciler",
        role="reconciler",
        status="succeeded",
        input_hash="0" * 64,
        checkpoint="reconciled",
        created_at=now + timedelta(seconds=3),
        updated_at=now + timedelta(seconds=42),
    )
    full_op = _consented_operation(
        operation_id="operation_full_recording",
        now=now,
        segments=[segment],
        proposals=[faithful],
        provider_runs=[seal_run, reconcile_run],
        committed_task_ids=[f"task_{index}" for index in range(16)],
    )

    artifact = build_run_artifact_from_operations(
        git_sha="c6f7d53",
        corpus=corpus,
        provider_config={"reconciler_provider": "openai", "reconciler_model": "gpt-4o"},
        full_recording_operation=full_op,
        utterance_operations={25: utterance_op},
    )

    # Deleted proposals are excluded; the two active proposals are observed.
    utterance_run = artifact.utterances[0]
    assert utterance_run.utterance_n == 25
    assert utterance_run.proposal_count == 2
    assert sorted(proposal.fidelity for proposal in utterance_run.proposals) == [
        "faithful",
        "translated",
    ]
    # SC-001 committed count and SC-007 latency derive from the full recording.
    assert artifact.full_recording is not None
    assert artifact.full_recording.committed_task_count == 16
    assert artifact.full_recording.seal_to_awaiting_confirmation_seconds == 42.0

    # No raw title/transcript text leaks into the live artifact.
    blob = json.dumps(run_artifact_to_dict(artifact), ensure_ascii=False)
    assert not any("Ѐ" <= character <= "ӿ" for character in blob)
    assert "Buy milk and bread" not in blob

    # The projected artifact scores through the same deterministic path.
    report = compute_operational_evidence(artifact, corpus)
    assert report.criterion("SC-003").detail["translated_titles"] == 1
    assert report.criterion("SC-001").detail["committed_task_count"] == 16


def test_seal_latency_defaults_to_zero_and_criterion_lookup_is_strict() -> None:
    from app.workflows.voice_brain_dump.operational_evidence import (
        seal_to_confirmation_latency,
    )

    now = datetime(2026, 7, 29, tzinfo=UTC)
    operation = _consented_operation(
        operation_id="operation_no_runs", now=now, segments=[], proposals=[]
    )
    assert seal_to_confirmation_latency(operation) == 0.0

    corpus = load_reference_corpus(_CORPUS_PATH)
    report = compute_operational_evidence(
        run_artifact_from_dict(_load_recorded_artifact()), corpus
    )
    with pytest.raises(KeyError):
        report.criterion("SC-999")


# --- Strengthened SC-002 correctness oracle (T035 follow-up) ----------------


def test_sc002_oracle_rejects_translated_ungrounded_and_missing_terms() -> None:
    corpus = load_reference_corpus(_CORPUS_PATH)
    by_number = {utterance.n: utterance for utterance in corpus.utterances}

    def utterance_run(n: int, titled_sources: list[tuple[str, str]]):
        return build_utterance_run(
            utterance_n=n,
            operation_id=f"op-{n}",
            titled_sources=titled_sources,
            corpus_utterance=by_number[n],
        )

    utterances = [
        # A correct, grounded, faithful single task -> hit.
        utterance_run(
            5, [("Отметить договор", "Отметь задачу про договор выполненной")]
        ),
        # Right count, but the title was translated out of Russian -> miss.
        utterance_run(2, [("Call Anna", "Напомни мне завтра позвонить Анне")]),
        # Right count and faithful, but the title shares no grounded content -> miss.
        utterance_run(
            1, [("Позвонить дедушке", "Добавь задачу проверить почту сегодня вечером")]
        ),
        # Right count and grounded, but the required embedded term is dropped -> miss.
        utterance_run(
            3,
            [
                (
                    "Создать проект запуск",
                    "Создай проект Запуск BrainBuddy и поставь высокий приоритет",
                )
            ],
        ),
    ]
    artifact = build_run_artifact(
        git_sha="test-sha",
        corpus=corpus,
        provider_config={"reconciler_provider": "openai"},
        full_recording=None,
        utterances=utterances,
        evidence_modes={"utterances": MODE_TEXT_RECONCILER},
    )

    sc002 = compute_operational_evidence(artifact, corpus).criterion("SC-002").detail
    assert sc002["correct_hits"] == 1
    assert sc002["task_yielding_total"] == 4
    assert sc002["miss_breakdown"] == {
        "count_mismatch": 0,
        "translated": 1,
        "ungrounded": 1,
        "missing_required_terms": 1,
    }
    # Per-section provenance is surfaced on the criterion.
    assert sc002["evidence_mode"] == MODE_TEXT_RECONCILER


def test_sc002_oracle_credits_correctly_split_multi_utterance() -> None:
    corpus = load_reference_corpus(_CORPUS_PATH)
    by_number = {utterance.n: utterance for utterance in corpus.utterances}
    # Utterance 43 is a genuine three-task utterance; the right outcome is three
    # grounded proposals, which the oracle credits (unlike a naive "exactly one").
    run = build_utterance_run(
        utterance_n=43,
        operation_id="op-43",
        titled_sources=[
            ("Созвон с командой", "созвон с командой"),
            ("Подготовить demo", "подготовить demo"),
            ("Проверить backup", "проверить backup"),
        ],
        corpus_utterance=by_number[43],
    )
    assert run.proposal_count == 3
    artifact = build_run_artifact(
        git_sha="test-sha",
        corpus=corpus,
        provider_config={},
        full_recording=None,
        utterances=[run],
        evidence_modes={"utterances": MODE_TEXT_RECONCILER},
    )
    sc002 = compute_operational_evidence(artifact, corpus).criterion("SC-002").detail
    assert sc002["correct_hits"] == 1
    assert sc002["miss_breakdown"]["count_mismatch"] == 0


# --- Harness pure helpers (live report) -------------------------------------


def test_seal_manifest_hash_matches_service_formula() -> None:
    now = datetime(2026, 7, 29, tzinfo=UTC)
    chunks = [
        BrainDumpAudioChunkDocument(
            chunk_number=1, sha256="b" * 64, size_bytes=222, received_at=now
        ),
        BrainDumpAudioChunkDocument(
            chunk_number=0, sha256="a" * 64, size_bytes=111, received_at=now
        ),
    ]
    expected = VoiceBrainDumpService._brain_dump_manifest_hash(chunks)
    computed = seal_manifest_hash(
        [
            {"chunk_number": 1, "sha256": "b" * 64, "size_bytes": 222},
            {"chunk_number": 0, "sha256": "a" * 64, "size_bytes": 111},
        ]
    )
    assert computed == expected


def test_titled_sources_from_operation_response_selects_active_proposals() -> None:
    response = {
        "segments": [
            {"id": "seg1", "text": "Купить молоко"},
            {"id": "seg2", "text": "Позвонить Анне"},
        ],
        "proposals": [
            {
                "title": "Купить молоко",
                "source_segment_ids": ["seg1"],
                "deleted": False,
            },
            {
                "title": "Позвонить Анне",
                "source_segment_ids": ["seg2"],
                "deleted": True,
            },
            {
                "title": "Superseded",
                "source_segment_ids": ["seg1"],
                "deleted": False,
                "successor_ids": ["p9"],
            },
        ],
    }
    assert titled_sources_from_operation_response(response) == [
        ("Купить молоко", "Купить молоко")
    ]


def test_observe_titles_marks_a_title_without_content_words_as_ungrounded() -> None:
    from app.workflows.voice_brain_dump.operational_evidence import observe_titles

    _count, observations, _preserved = observe_titles([("ok go", "Добавь задачу")])
    assert observations[0].grounded_in_source is False


def test_build_full_recording_run_counts_active_titles() -> None:
    full = build_full_recording_run(
        operation_id="op-full",
        titled_sources=[("Купить молоко", "купить молоко"), ("Позвонить", "позвонить")],
        committed_task_count=16,
        seal_to_awaiting_confirmation_seconds=44.0,
        seal_to_commit_seconds=60.0,
    )
    assert full.proposal_count == 2
    assert full.committed_task_count == 16
    assert full.seal_to_awaiting_confirmation_seconds == 44.0
    assert len(full.operation_ref) == 16
