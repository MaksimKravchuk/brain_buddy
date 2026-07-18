"""Domain and provider-contract tests for schema-v2 Voice Brain Dump."""

from __future__ import annotations

import pytest

from app.exceptions import ValidationFailure
from app.workflows.voice_brain_dump.domain import (
    ProposalPatch,
    ReconciledProposal,
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
    _extract_titles,
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


def test_invalid_provider_output_rejects_sequence_and_blank_text() -> None:
    with pytest.raises(ValidationFailure, match="sequence"):
        TranscriptHypothesis(
            id="segment_bad_sequence",
            sequence=0,
            start_ms=0,
            end_ms=500,
            text="valid words",
            stability="stable",
            provider_role="accurate",
        )

    with pytest.raises(ValidationFailure, match="text"):
        TranscriptHypothesis(
            id="segment_blank_text",
            sequence=1,
            start_ms=0,
            end_ms=500,
            text="   ",
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


def test_projection_preserves_lineage_for_merge_split_remove_and_unlocked_updates() -> None:
    base = ReconciledProposal(
        id="proposal_original",
        title="Починить brain body",
        source_segment_ids=["fast_1"],
        status="provisional",
    )

    projection = apply_proposal_patches(
        [base],
        [
            ProposalPatch.merge(
                proposal_id="proposal_merged",
                title="Починить BrainBuddy",
                predecessor_ids=["proposal_original", "proposal_missing"],
                source_segment_ids=["accurate_1"],
            ),
            ProposalPatch.update(
                proposal_id="proposal_merged",
                title="Починить BrainBuddy MVP",
                source_segment_ids=["accurate_2"],
                producer="reconciler",
            ),
            ProposalPatch.update(
                proposal_id="proposal_merged",
                locked_fields=["title"],
                producer="user",
            ),
            ProposalPatch.remove(proposal_id="proposal_merged", producer="user"),
            ProposalPatch.split(
                proposal_id="proposal_split",
                title="Сделать smoke отдельно",
                predecessor_ids=["proposal_missing"],
                source_segment_ids=["accurate_3"],
            ),
        ],
    )

    history_by_id = {proposal.id: proposal for proposal in projection.history}
    assert history_by_id["proposal_original"].tombstoned is True
    assert history_by_id["proposal_original"].successor_ids == ["proposal_merged"]
    assert history_by_id["proposal_merged"].tombstoned is True
    assert history_by_id["proposal_merged"].title == "Починить BrainBuddy MVP"
    assert history_by_id["proposal_merged"].source_segment_ids == ["accurate_2"]
    assert history_by_id["proposal_merged"].locked_fields == ["title"]
    assert [proposal.title for proposal in projection.active] == [
        "Сделать smoke отдельно"
    ]


def test_supersede_patch_replaces_one_proposal_with_explicit_lineage() -> None:
    base = ReconciledProposal(
        id="proposal_fast",
        title="Починить brain body",
        source_segment_ids=["fast_1"],
        status="provisional",
    )

    projection = apply_proposal_patches(
        [base],
        [
            ProposalPatch.supersede(
                proposal_id="proposal_accurate",
                title="Починить BrainBuddy",
                predecessor_ids=["proposal_fast"],
                source_segment_ids=["accurate_1"],
            )
        ],
    )

    history_by_id = {proposal.id: proposal for proposal in projection.history}
    assert [proposal.id for proposal in projection.active] == ["proposal_accurate"]
    assert history_by_id["proposal_fast"].tombstoned is True
    assert history_by_id["proposal_fast"].successor_ids == ["proposal_accurate"]
    assert history_by_id["proposal_accurate"].predecessor_ids == ["proposal_fast"]


def test_projection_rejects_malformed_unknown_and_unsupported_patches() -> None:
    base = ReconciledProposal(
        id="proposal_existing",
        title="Existing title",
        source_segment_ids=["seg_1"],
        status="provisional",
    )

    with pytest.raises(ValidationFailure, match="requires a title"):
        apply_proposal_patches(
            [], [ProposalPatch(operation="add", proposal_id="proposal_new", producer="fast")]
        )

    with pytest.raises(ValidationFailure, match="Unknown proposal ID"):
        apply_proposal_patches(
            [base], [ProposalPatch.update(proposal_id="missing", producer="fast")]
        )

    with pytest.raises(ValidationFailure, match="Unsupported proposal patch"):
        apply_proposal_patches(
            [base],
            [
                ProposalPatch(
                    operation="rename",  # type: ignore[arg-type]
                    proposal_id="proposal_existing",
                    producer="fast",
                )
            ],
        )


def test_projection_replays_existing_ids_and_accepts_partial_update_patches() -> None:
    base = ReconciledProposal(
        id="proposal_repeat",
        title="Initial title",
        source_segment_ids=["fast_1"],
        status="provisional",
    )

    projection = apply_proposal_patches(
        [base],
        [
            ProposalPatch.add(
                proposal_id="proposal_repeat",
                title="Replacement title",
                source_segment_ids=["fast_2"],
                producer="fast",
            ),
            ProposalPatch.update(
                proposal_id="proposal_repeat",
                source_segment_ids=["user_1"],
                producer="user",
            ),
            ProposalPatch.update(
                proposal_id="proposal_repeat",
                source_segment_ids=["accurate_1"],
                producer="accurate",
            ),
            ProposalPatch.update(
                proposal_id="proposal_repeat",
                title="Replacement title",
                producer="reconciler",
            ),
        ],
    )

    assert [proposal.id for proposal in projection.active] == ["proposal_repeat"]
    assert projection.active[0].title == "Replacement title"
    assert projection.active[0].source_segment_ids == ["accurate_1"]
    assert projection.active[0].status == "reconciled"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("починить brain body", ["Починить brain body"]),
        ("купить хлеб и молоко", ["Купить хлеб и молоко"]),
        (
            "todo buy milk; then please call mom. нужно оплатить счет",
            ["Buy milk", "Call mom", "Оплатить счет"],
        ),
        ("todo", ["Todo"]),
        (".", ["."]),
        ("", []),
    ],
)
def test_deterministic_reconciler_extracts_known_split_and_fallback_titles(
    text: str, expected: list[str]
) -> None:
    assert _extract_titles(text) == expected
