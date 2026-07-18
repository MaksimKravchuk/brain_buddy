"""Domain and provider-contract tests for schema-v2 Voice Brain Dump."""

from __future__ import annotations

import pytest

from app.exceptions import ValidationFailure
from app.workflows.voice_brain_dump.domain import (
    ProposalPatch,
    TranscriptHypothesis,
    active_transcript_hypotheses,
    apply_proposal_patches,
)
from app.workflows.voice_brain_dump.providers import (
    AccurateSttRequest,
    DeterministicAccurateStt,
    DeterministicFastStt,
    DeterministicTextReconciler,
    FastSttRequest,
    ReconcileTextRequest,
)


def test_dual_stt_roles_keep_accurate_audio_input_separate_from_fast_text() -> None:
    fast = DeterministicFastStt({"media_1:0": "починить brain body"})
    accurate = DeterministicAccurateStt({"media_1": "починить BrainBuddy"})

    fast_result = fast.transcribe_window(
        FastSttRequest(
            operation_id="op_1",
            media_ref="media_1",
            chunk_numbers=[0],
            language_hints=["ru", "en"],
        )
    )
    assert fast_result.segments[0].text == "починить brain body"
    assert fast_result.segments[0].provider_role == "fast"

    accurate_result = accurate.transcribe_sealed_audio(
        AccurateSttRequest(
            operation_id="op_1",
            media_ref="media_1",
            language_hints=["ru", "en"],
            vocabulary=["BrainBuddy"],
            supersedes_segment_ids=[fast_result.segments[0].id],
        )
    )

    assert accurate.calls[-1].media_ref == "media_1"
    assert accurate.calls[-1].fast_text is None
    assert accurate_result.segments[0].text == "починить BrainBuddy"
    assert accurate_result.segments[0].provider_role == "accurate"
    assert accurate_result.segments[0].supersedes_segment_ids == [fast_result.segments[0].id]


def test_invalid_provider_output_rejects_missing_or_negative_audio_spans() -> None:
    with pytest.raises(ValidationFailure, match="audio span"):
        TranscriptHypothesis(
            id="segment_bad",
            sequence=1,
            start_ms=1200,
            end_ms=500,
            text="bad span",
            stability="stable",
            provider_role="accurate",
        )


def test_active_transcript_projection_orders_versions_and_keeps_history() -> None:
    fast = TranscriptHypothesis(
        id="fast_1",
        sequence=1,
        start_ms=0,
        end_ms=900,
        text="brain body",
        stability="stable",
        provider_role="fast",
    )
    accurate = TranscriptHypothesis(
        id="accurate_1",
        sequence=2,
        start_ms=0,
        end_ms=900,
        text="BrainBuddy",
        stability="stable",
        provider_role="accurate",
        supersedes_segment_ids=["fast_1"],
    )

    active = active_transcript_hypotheses([fast, accurate])

    assert [segment.id for segment in active] == ["accurate_1"]
    assert fast.text == "brain body"


def test_reconciler_emits_stable_lineage_patches_without_positional_identity() -> None:
    reconciler = DeterministicTextReconciler()
    segment = TranscriptHypothesis(
        id="segment_ml_01",
        sequence=1,
        start_ms=0,
        end_ms=5200,
        text="Надо починить BrainBuddy, потом сделать production smoke и написать Наташе",
        stability="stable",
        provider_role="accurate",
    )

    result = reconciler.reconcile(
        ReconcileTextRequest(
            operation_id="op_1",
            transcript_segments=[segment],
            active_proposals=[],
            user_locks={},
        )
    )
    projection = apply_proposal_patches([], result.patches)

    assert [proposal.title for proposal in projection.active] == [
        "Починить BrainBuddy",
        "Сделать production smoke",
        "Написать Наташе",
    ]
    assert all(proposal.source_segment_ids == ["segment_ml_01"] for proposal in projection.active)
    assert all(proposal.id.startswith("proposal_") for proposal in projection.active)


def test_locked_user_title_surfaces_conflict_instead_of_overwrite() -> None:
    original = ProposalPatch.add(
        proposal_id="proposal_keep",
        title="Починить brain body",
        source_segment_ids=["fast_1"],
        producer="fast",
    )
    user_edit = ProposalPatch.update(
        proposal_id="proposal_keep",
        title="Починить BrainBuddy MVP",
        producer="user",
        locked_fields=["title"],
    )
    model_update = ProposalPatch.update(
        proposal_id="proposal_keep",
        title="Починить BrainBuddy",
        source_segment_ids=["accurate_1"],
        producer="reconciler",
    )

    projection = apply_proposal_patches([], [original, user_edit, model_update])

    assert projection.active[0].title == "Починить BrainBuddy MVP"
    assert projection.active[0].locked_fields == ["title"]
    assert projection.active[0].conflicts[0].field == "title"
    assert projection.active[0].conflicts[0].suggested_value == "Починить BrainBuddy"
