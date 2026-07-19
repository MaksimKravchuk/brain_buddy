"""Domain and provider-contract tests for schema-v2 Voice Brain Dump."""

from __future__ import annotations

import httpx
import pytest

from app.exceptions import (
    ProviderRetryableError,
    ProviderTerminalError,
    ValidationFailure,
)
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


def test_openai_reconciler_materializes_only_schema_valid_server_owned_patches() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    captured: list[dict[str, object]] = []

    def complete(payload: dict[str, object]) -> dict[str, object]:
        captured.append(payload)
        return {
            "operations": [
                {
                    "operation": "update",
                    "proposal_id": "proposal_existing",
                    "title": "Починить BrainBuddy",
                    "source_segment_ids": ["segment_accurate"],
                    "base_revision": 2,
                },
                {
                    "operation": "add",
                    "title": "Написать Наташе",
                    "source_segment_ids": ["segment_accurate"],
                },
            ]
        }

    reconciler = OpenAITextReconciler(
        api_key="test-key", model="gpt-4o", complete=complete
    )
    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=2000,
        text="Починить BrainBuddy и написать Наташе",
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title="Починить brain body",
        source_segment_ids=["segment_fast"],
        status="user_edited",
        locked_fields=["title"],
        revision=2,
        title_revision=2,
    )

    result = reconciler.reconcile(
        ReconcileTextRequest(
            operation_id="operation_1",
            transcript_segments=[segment],
            active_proposals=[existing],
            user_locks={"proposal_existing": ["title"]},
        )
    )

    assert [patch.operation for patch in result.patches] == ["update", "add"]
    assert result.patches[0].proposal_id == "proposal_existing"
    assert result.patches[1].proposal_id.startswith("proposal_")
    assert result.patches[1].proposal_id != "proposal_existing"
    assert all(patch.producer == "reconciler" for patch in result.patches)
    assert captured[0]["model"] == "gpt-4o"
    assert captured[0]["response_format"] == {
        "type": "json_schema",
        "json_schema": captured[0]["response_format"]["json_schema"],  # type: ignore[index]
    }
    response_format = captured[0]["response_format"]
    assert isinstance(response_format, dict)
    json_schema = response_format["json_schema"]
    assert isinstance(json_schema, dict)
    schema = json_schema["schema"]
    assert isinstance(schema, dict)
    operation_schema = schema["properties"]["operations"]["items"]  # type: ignore[index]
    assert set(operation_schema["required"]) == set(operation_schema["properties"])
    assert operation_schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "operation",
    [
        {"operation": "rename", "proposal_id": "proposal_existing", "title": "Bad"},
        {"operation": "update", "proposal_id": "unknown", "title": "Bad"},
        {
            "operation": "add",
            "title": "Invented source",
            "source_segment_ids": ["segment_unknown"],
        },
        {
            "operation": "remove",
            "proposal_id": "proposal_existing",
            "title": "remove cannot carry title",
        },
        {
            "operation": "add",
            "proposal_id": "provider_owned_id",
            "title": "Bad ID",
            "source_segment_ids": ["segment_accurate"],
        },
        {
            "operation": "add",
            "title": " ",
            "source_segment_ids": ["segment_accurate"],
        },
        {
            "operation": "add",
            "title": "Bad predecessor",
            "source_segment_ids": ["segment_accurate"],
            "predecessor_ids": ["proposal_existing"],
        },
        {
            "operation": "split",
            "title": "Missing split predecessor",
            "source_segment_ids": ["segment_accurate"],
        },
        {
            "operation": "merge",
            "title": "Only one merge predecessor",
            "source_segment_ids": ["segment_accurate"],
            "predecessor_ids": ["proposal_existing"],
        },
        {
            "operation": "supersede",
            "title": "Missing supersede predecessor",
            "source_segment_ids": ["segment_accurate"],
        },
        {
            "operation": "split",
            "title": "Unknown predecessor",
            "source_segment_ids": ["segment_accurate"],
            "predecessor_ids": ["proposal_unknown"],
        },
    ],
)
def test_openai_reconciler_rejects_invalid_or_untrusted_operations(
    operation: dict[str, object],
) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    reconciler = OpenAITextReconciler(
        api_key="test-key",
        model="gpt-4o",
        complete=lambda _payload: {"operations": [operation]},
    )
    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Do a task",
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title="Existing",
        source_segment_ids=["segment_fast"],
        status="provisional",
    )

    with pytest.raises(ValidationFailure):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_1",
                transcript_segments=[segment],
                active_proposals=[existing],
                user_locks={},
            )
        )


def test_openai_reconciler_materializes_structural_and_remove_operations() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Split, merge, replace, and remove tasks",
        stability="stable",
        provider_role="accurate",
    )
    first = ReconciledProposal(
        id="proposal_first",
        title="First",
        source_segment_ids=["segment_fast"],
        status="provisional",
    )
    second = ReconciledProposal(
        id="proposal_second",
        title="Second",
        source_segment_ids=["segment_fast"],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "split",
                    "title": "Split result",
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": [first.id],
                },
                {
                    "operation": "merge",
                    "title": "Merged result",
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": [first.id, second.id],
                },
                {
                    "operation": "supersede",
                    "title": "Replacement",
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": [second.id],
                },
                {"operation": "remove", "proposal_id": first.id},
            ]
        },
    )

    result = reconciler.reconcile(
        ReconcileTextRequest(
            operation_id="operation_structural",
            transcript_segments=[segment],
            active_proposals=[first, second],
            user_locks={},
        )
    )

    assert [patch.operation for patch in result.patches] == [
        "split",
        "merge",
        "supersede",
        "remove",
    ]
    assert result.patches[-1].proposal_id == first.id


def test_openai_reconciler_cannot_restore_a_user_deleted_proposal() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Restore deleted task",
        stability="stable",
        provider_role="accurate",
    )
    deleted = ReconciledProposal(
        id="proposal_deleted",
        title="Do not restore",
        source_segment_ids=["segment_fast"],
        status="provisional",
        tombstoned=True,
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": deleted.title,
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="cannot restore"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_deleted",
                transcript_segments=[segment],
                active_proposals=[deleted],
                user_locks={},
            )
        )


def test_openai_reconciler_reallocates_a_colliding_server_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    calls = {"count": 0}

    def server_id(*_args: object) -> str:
        calls["count"] += 1
        return "proposal_existing" if calls["count"] == 1 else "proposal_generated"

    monkeypatch.setattr(OpenAITextReconciler, "_server_id", staticmethod(server_id))
    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Add another task",
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title="Existing",
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": "Generated",
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    result = reconciler.reconcile(
        ReconcileTextRequest(
            operation_id="operation_collision",
            transcript_segments=[segment],
            active_proposals=[existing],
            user_locks={},
        )
    )

    assert result.patches[0].proposal_id == "proposal_generated"
    assert calls["count"] == 2


def _minimal_reconcile_request() -> ReconcileTextRequest:
    return ReconcileTextRequest(
        operation_id="operation_provider_call",
        transcript_segments=[
            TranscriptHypothesis(
                id="segment_accurate",
                sequence=1,
                start_ms=0,
                end_ms=1000,
                text="Do the task",
                stability="stable",
                provider_role="accurate",
            )
        ],
        active_proposals=[],
        user_locks={},
    )


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (429, ProviderRetryableError),
        (503, ProviderRetryableError),
        (400, ProviderTerminalError),
    ],
)
def test_openai_reconciler_maps_provider_http_failures(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_error: type[Exception],
) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    class Response:
        def __init__(self) -> None:
            self.status_code = status_code

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "provider rejected request",
                    request=httpx.Request("POST", "https://provider.invalid"),
                    response=httpx.Response(self.status_code),
                )

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(httpx, "Client", Client)

    with pytest.raises(expected_error):
        OpenAITextReconciler(api_key="test-key").reconcile(
            _minimal_reconcile_request()
        )


@pytest.mark.parametrize(
    "content",
    [
        '{"operations": []}',
        {"operations": []},
    ],
)
def test_openai_reconciler_accepts_string_or_object_structured_content(
    monkeypatch: pytest.MonkeyPatch,
    content: object,
) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": content}}]}

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(httpx, "Client", Client)
    assert OpenAITextReconciler(api_key="test-key").reconcile(
        _minimal_reconcile_request()
    ).patches == []


@pytest.mark.parametrize("content", ["{", [], None])
def test_openai_reconciler_rejects_malformed_provider_content(
    monkeypatch: pytest.MonkeyPatch,
    content: object,
) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": content}}]}

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(httpx, "Client", Client)
    with pytest.raises(ProviderTerminalError, match="INVALID_RESPONSE"):
        OpenAITextReconciler(api_key="test-key").reconcile(
            _minimal_reconcile_request()
        )


def test_openai_reconciler_maps_provider_timeout_to_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    class Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> None:
            raise httpx.TimeoutException("provider timed out")

    monkeypatch.setattr(httpx, "Client", Client)
    with pytest.raises(ProviderRetryableError, match="RETRYABLE"):
        OpenAITextReconciler(api_key="test-key").reconcile(
            _minimal_reconcile_request()
        )


def test_production_reconciler_module_has_no_regex_or_fixture_extractor() -> None:
    import inspect

    from app.workflows.voice_brain_dump.adapters import reconciler

    source = inspect.getsource(reconciler)
    assert "_extract_titles" not in source
    assert "re.split" not in source
    assert "brainbuddy\" in lower" not in source.casefold()


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
