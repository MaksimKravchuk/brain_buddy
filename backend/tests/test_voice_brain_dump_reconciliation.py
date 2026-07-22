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

    reconciler = OpenAITextReconciler(api_key="test-key", complete=complete)
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
    from app.core.config import MVP_RECONCILER_MODEL

    assert captured[0]["model"] == MVP_RECONCILER_MODEL
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
    assert set(operation_schema["properties"]["operation"]["enum"]) == {
        "add",
        "update",
        "split",
        "merge",
        "remove",
        "supersede",
    }


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


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (
            {
                "operation": "add",
                "title": "Do a task",
                "source_segment_ids": ["segment_accurate"],
                "predecessor_ids": ["proposal_existing"],
            },
            "Add cannot carry predecessors",
        ),
        (
            {
                "operation": "split",
                "title": "Do a task",
                "source_segment_ids": ["segment_accurate"],
            },
            "Split requires exactly one predecessor",
        ),
        (
            {
                "operation": "merge",
                "title": "Do a task",
                "source_segment_ids": ["segment_accurate"],
                "predecessor_ids": ["proposal_existing"],
            },
            "Merge requires at least two predecessors",
        ),
        (
            {
                "operation": "supersede",
                "title": "Do a task",
                "source_segment_ids": ["segment_accurate"],
            },
            "Supersede requires exactly one predecessor",
        ),
    ],
)
def test_openai_reconciler_rejects_structurally_invalid_grounded_transformations(
    operation: dict[str, object], message: str
) -> None:
    """Grounded titles ensure each transformation check, not the invention guard, rejects."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    reconciler = OpenAITextReconciler(
        api_key="test-key", complete=lambda _payload: {"operations": [operation]}
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

    with pytest.raises(ValidationFailure, match=message):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_1",
                transcript_segments=[segment],
                active_proposals=[existing],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    "operation",
    [
        {
            "operation": "add",
            "title": "Reboot production database",
            "source_segment_ids": ["segment_accurate"],
        },
        {
            "operation": "update",
            "proposal_id": "proposal_existing",
            "title": "Reboot production database",
            "source_segment_ids": ["segment_accurate"],
            "base_revision": 1,
        },
        {
            "operation": "split",
            "title": "Reboot production database",
            "source_segment_ids": ["segment_accurate"],
            "predecessor_ids": ["proposal_existing"],
        },
        {
            "operation": "merge",
            "title": "Reboot production database",
            "source_segment_ids": ["segment_accurate"],
            "predecessor_ids": ["proposal_existing", "proposal_other"],
        },
        {
            "operation": "supersede",
            "title": "Reboot production database",
            "source_segment_ids": ["segment_accurate"],
            "predecessor_ids": ["proposal_existing"],
        },
    ],
)
def test_openai_reconciler_rejects_zero_lexical_overlap_invention_in_every_shape(
    operation: dict[str, object],
) -> None:
    """A title with zero lexical overlap with its cited transcript segment is
    an invented task in every patch shape, not only the shared-action/novel-
    object pattern; the runtime guard must fail closed regardless of prompt
    wording (ADR-0002 2026-07-19 amendment, zero-invented-tasks target)."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {"operations": [operation]},
    )
    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Buy milk on the way home",
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title="Existing task",
        source_segment_ids=["segment_fast"],
        status="provisional",
        title_revision=1,
    )
    other = ReconciledProposal(
        id="proposal_other",
        title="Other task",
        source_segment_ids=["segment_fast"],
        status="provisional",
    )

    with pytest.raises(ValidationFailure, match="not grounded"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_zero_overlap",
                transcript_segments=[segment],
                active_proposals=[existing, other],
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
        text="First and Second: split, merge, replace, and remove tasks",
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
                    "title": "Split tasks",
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": [first.id],
                },
                {
                    "operation": "merge",
                    "title": "Merge tasks",
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": [first.id, second.id],
                },
                {
                    "operation": "supersede",
                    "title": "Replace tasks",
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": [second.id],
                },
                {
                    "operation": "remove",
                    "proposal_id": first.id,
                    "source_segment_ids": [segment.id],
                },
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

    indexes: list[int] = []

    def server_id(_operation_id: str, index: int, _draft: object) -> str:
        if index in indexes:
            raise AssertionError("collision retry repeated the same server-ID input")
        indexes.append(index)
        return "proposal_existing" if index < 2 else "proposal_generated"

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
                    "title": "Another task",
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
    assert indexes == [0, 1, 2]


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


def test_openai_reconciler_schema_allows_only_add_without_active_proposals() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    captured: dict[str, object] = {}

    def complete(payload: dict[str, object]) -> dict[str, object]:
        captured.update(payload)
        return {"operations": []}

    OpenAITextReconciler(api_key="test-key", complete=complete).reconcile(
        _minimal_reconcile_request()
    )

    response_format = captured["response_format"]
    assert isinstance(response_format, dict)
    json_schema = response_format["json_schema"]
    assert isinstance(json_schema, dict)
    schema = json_schema["schema"]
    assert isinstance(schema, dict)
    operation_schema = schema["properties"]["operations"]["items"]  # type: ignore[index]
    assert operation_schema["properties"]["operation"]["enum"] == ["add"]
    messages = captured["messages"]
    assert isinstance(messages, list)
    assert "only add" in str(messages[0]["content"]).casefold()


def test_openai_reconciler_redacts_api_key_and_invalid_envelope_cause() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    reconciler = OpenAITextReconciler(
        api_key="sensitive-test-key",
        complete=lambda _payload: {"operations": [{"secret": "raw-model-output"}]},
    )

    assert "sensitive-test-key" not in repr(reconciler)
    with pytest.raises(ValidationFailure) as raised:
        reconciler.reconcile(_minimal_reconcile_request())

    assert raised.value.__cause__ is None
    assert "raw-model-output" not in repr(raised.value)


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
        OpenAITextReconciler(api_key="test-key", max_retries=0).reconcile(
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
        OpenAITextReconciler(api_key="test-key", max_retries=0).reconcile(
            _minimal_reconcile_request()
        )


def test_production_reconciler_module_has_no_regex_or_fixture_extractor() -> None:
    import inspect

    from app.workflows.voice_brain_dump.adapters import reconciler

    source = inspect.getsource(reconciler)
    assert "_extract_titles" not in source
    assert "re.split" not in source
    assert "brainbuddy\" in lower" not in source.casefold()


def test_openai_reconciler_prompt_prohibits_inventing_unsupported_tasks() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    captured: dict[str, object] = {}

    def complete(payload: dict[str, object]) -> dict[str, object]:
        captured.update(payload)
        return {"operations": []}

    OpenAITextReconciler(api_key="test-key", complete=complete).reconcile(
        _minimal_reconcile_request()
    )

    messages = captured["messages"]
    assert isinstance(messages, list)
    system_prompt = str(messages[0]["content"]).casefold()
    assert "invent" in system_prompt or "fabricat" in system_prompt
    assert "source_segment_ids" in system_prompt


class _LyingStr(str):
    """A ``str`` subclass whose ``__eq__``/``__ne__`` always lie.

    Proves the authorization check cannot be satisfied by matching
    ``==``/``!=`` alone: it must reject any non-exact-``str`` type outright,
    because a subclass can report equality with the authorized constant
    while its actual value -- what httpx would literally put on the wire --
    is something else entirely.
    """

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    def __hash__(self) -> int:
        return str.__hash__(self)


@pytest.mark.parametrize(
    ("field_name", "attempted_value"),
    [
        ("endpoint", "https://attacker.example.com/v1/chat/completions"),
        ("endpoint", "https://api.openai.com/v1/chat/completions"),
        ("model", "gpt-4o"),
        ("model", "gpt-5.6-terra"),
        ("model", "gpt-5.6-sol"),
        ("model", "gpt-5.6-fable"),
        ("model", "gpt-5.6-luna"),
        ("template_version", "legacy-v0"),
        ("template_version", "product-operation-v1"),
        ("provider_id", "anthropic"),
        ("provider_id", "openai"),
    ],
)
def test_openai_reconciler_rejects_authorization_identity_as_a_constructor_argument(
    field_name: str, attempted_value: str
) -> None:
    """Authorization-sensitive identity (``endpoint``/``model``/
    ``template_version``/``provider_id``) is never accepted from the
    constructor -- not even the correct authorized value -- since accepting
    runtime-supplied identity configuration at all is itself the egress-
    authorization gap. Regression for a defense-in-depth gap: previously the
    constructor accepted an arbitrary value for each of these fields and
    only ``endpoint`` was ever re-validated in ``__post_init__``."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": {"operations": []}}}]},
        )

    with pytest.raises(TypeError, match=f"unexpected keyword argument '{field_name}'"):
        OpenAITextReconciler(
            api_key="test-key",
            transport=httpx.MockTransport(handler),
            **{field_name: attempted_value},
        )

    assert calls == 0


@pytest.mark.parametrize(
    ("field_name", "attempted_value"),
    [
        ("endpoint", "https://attacker.example.com/v1/chat/completions"),
        ("model", "gpt-4o"),
        ("template_version", "legacy-v0"),
        ("provider_id", "anthropic"),
    ],
)
def test_openai_reconciler_identity_fields_cannot_be_reassigned_after_construction(
    field_name: str, attempted_value: str
) -> None:
    """The identity fields are frozen: a manually-constructed adapter
    instance handed to other code cannot have its authorized identity
    swapped out from under it before a later call transmits."""

    import dataclasses

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": {"operations": []}}}]},
        )

    reconciler = OpenAITextReconciler(
        api_key="test-key", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(reconciler, field_name, attempted_value)

    assert calls == 0


@pytest.mark.parametrize(
    "field_name", ["endpoint", "model", "template_version", "provider_id"]
)
def test_openai_reconciler_rejects_a_lying_str_subclass_forced_onto_identity(
    field_name: str,
) -> None:
    """Even if ``frozen=True`` is bypassed via ``object.__setattr__`` -- e.g.
    by other code holding a reference to a constructed instance -- a spoofed
    identity must never reach the wire. The re-check immediately before
    every transmit must reject a deceptive ``str`` subclass whose overridden
    equality lies about matching the authorized constant."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": {"operations": []}}}]},
        )

    reconciler = OpenAITextReconciler(
        api_key="test-key", transport=httpx.MockTransport(handler)
    )
    spoofed = _LyingStr("attacker-controlled-value")
    assert spoofed == getattr(reconciler, field_name)  # the lie
    object.__setattr__(reconciler, field_name, spoofed)
    error_label = "provider" if field_name == "provider_id" else field_name

    with pytest.raises(ValueError, match=f"Unauthorized reconciler {error_label}"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_1",
                transcript_segments=[],
                active_proposals=[],
            )
        )

    assert calls == 0


def test_openai_reconciler_default_endpoint_matches_the_central_authorization_constant() -> (
    None
):
    from app.core.config import MVP_RECONCILER_ENDPOINT
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    reconciler = OpenAITextReconciler(api_key="test-key")

    assert reconciler.endpoint == MVP_RECONCILER_ENDPOINT


@pytest.mark.parametrize("max_retries", [-1, -2, True, False, "0", 1.0])
def test_openai_reconciler_rejects_invalid_max_retries_at_construction(
    max_retries: object,
) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": {"operations": []}}}]},
        )

    with pytest.raises(ValueError, match="max_retries"):
        OpenAITextReconciler(
            api_key="test-key",
            max_retries=max_retries,  # type: ignore[arg-type]
            max_cost_usd_per_operation=0.0001,
            transport=httpx.MockTransport(handler),
        )

    assert calls == 0


@pytest.mark.parametrize(
    "field_name", ["max_cost_usd_per_operation", "estimated_cost_usd_per_megabyte"]
)
@pytest.mark.parametrize(
    "invalid_value",
    [-0.01, float("nan"), float("inf"), float("-inf"), True, False, "0.5"],
)
def test_openai_reconciler_rejects_invalid_cost_fields_at_construction(
    field_name: str, invalid_value: object
) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": {"operations": []}}}]},
        )

    kwargs = {
        "api_key": "test-key",
        "transport": httpx.MockTransport(handler),
        field_name: invalid_value,
    }

    with pytest.raises(ValueError, match=field_name):
        OpenAITextReconciler(**kwargs)  # type: ignore[arg-type]

    assert calls == 0


@pytest.mark.parametrize(
    "field_name", ["max_cost_usd_per_operation", "estimated_cost_usd_per_megabyte"]
)
def test_openai_reconciler_allows_zero_cost_fields(field_name: str) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    kwargs = {
        "api_key": "test-key",
        "max_retries": 0,
        field_name: 0.0,
        "transport": httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json={"choices": [{"message": {"content": {"operations": []}}}]}
            )
        ),
    }

    reconciler = OpenAITextReconciler(**kwargs)  # type: ignore[arg-type]

    assert getattr(reconciler, field_name) == 0.0


def test_openai_reconciler_negative_max_retries_cannot_yield_a_usable_reconciler_even_with_tiny_budget() -> (
    None
):
    """A negative ``max_retries`` must fail closed at construction, before
    any cost estimate is computed or any transport call is placed -- even
    paired with a vanishingly small cost budget."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": {"operations": []}}}]},
        )

    with pytest.raises(ValueError):
        OpenAITextReconciler(
            api_key="test-key",
            max_retries=-2,
            max_cost_usd_per_operation=0.0000001,
            estimated_cost_usd_per_megabyte=0.0000001,
            transport=httpx.MockTransport(handler),
        )

    assert calls == 0


def test_openai_reconciler_retries_only_retryable_failures_with_a_bounded_budget() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    attempts = 0
    delays: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": {"operations": []}}}]},
        )

    reconciler = OpenAITextReconciler(
        api_key="test-key",
        timeout_seconds=5,
        max_retries=2,
        retry_backoff_seconds=(0.1, 0.2),
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )

    result = reconciler.reconcile(_minimal_reconcile_request())

    assert result.patches == []
    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_openai_reconciler_exhausts_retryable_http_status_without_backoff() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    reconciler = OpenAITextReconciler(
        api_key="test-key",
        max_retries=0,
        retry_backoff_seconds=(),
        transport=httpx.MockTransport(lambda _request: httpx.Response(429)),
    )

    with pytest.raises(ProviderRetryableError, match="RECONCILER_PROVIDER_RETRYABLE"):
        reconciler.reconcile(_minimal_reconcile_request())


def test_openai_reconciler_exhausts_transport_retries_as_retryable_error() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    reconciler = OpenAITextReconciler(
        api_key="test-key",
        timeout_seconds=0.1,
        max_retries=1,
        retry_backoff_seconds=(0.0,),
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(
                httpx.ReadTimeout("timeout", request=request)
            )
        ),
        sleep=lambda _delay: None,
    )

    with pytest.raises(ProviderRetryableError, match="RECONCILER_PROVIDER_RETRYABLE"):
        reconciler.reconcile(_minimal_reconcile_request())


def test_openai_reconciler_rejects_requests_over_cost_budget_before_network() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, json={"choices": [{"message": {"content": {"operations": []}}}]}
        )

    reconciler = OpenAITextReconciler(
        api_key="test-key",
        max_cost_usd_per_operation=0.000001,
        estimated_cost_usd_per_megabyte=1.0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTerminalError, match="RECONCILER_COST_LIMIT_EXCEEDED"):
        reconciler.reconcile(_minimal_reconcile_request())

    assert calls == 0


def test_openai_reconciler_reserves_budget_for_every_bounded_retry() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": {"operations": []}}}]})

    reconciler = OpenAITextReconciler(
        api_key="test-key",
        max_retries=2,
        max_cost_usd_per_operation=0.000003,
        estimated_cost_usd_per_megabyte=0.01,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ProviderTerminalError, match="RECONCILER_COST_LIMIT_EXCEEDED"):
        reconciler.reconcile(_minimal_reconcile_request())

    assert calls == 0


def test_openai_reconciler_records_its_estimated_cost_on_success() -> None:
    """Item 6 (F3): a successful reconciler run must record its own cost
    estimate so the operation-wide cumulative cost cap actually sees
    reconciler spend, not only accurate-STT spend."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    reconciler = OpenAITextReconciler(
        api_key="test-key",
        max_retries=1,
        estimated_cost_usd_per_megabyte=1.0,
        complete=lambda _payload: {"operations": []},
    )

    result = reconciler.reconcile(_minimal_reconcile_request())

    assert result.estimated_cost_usd > 0


def test_openai_reconciler_tags_a_retryable_failure_with_its_estimated_cost() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    reconciler = OpenAITextReconciler(
        api_key="test-key",
        max_retries=0,
        retry_backoff_seconds=(),
        estimated_cost_usd_per_megabyte=1.0,
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
    )

    with pytest.raises(ProviderRetryableError) as caught:
        reconciler.reconcile(_minimal_reconcile_request())

    assert caught.value.estimated_cost_usd > 0


def test_openai_reconciler_tags_an_invalid_envelope_failure_with_its_estimated_cost() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    reconciler = OpenAITextReconciler(
        api_key="test-key",
        estimated_cost_usd_per_megabyte=1.0,
        complete=lambda _payload: {"operations": [{"secret": "raw-model-output"}]},
    )

    with pytest.raises(ValidationFailure) as caught:
        reconciler.reconcile(_minimal_reconcile_request())

    assert caught.value.estimated_cost_usd > 0


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


def test_openai_reconciler_retries_remote_protocol_errors_with_bounded_backoff() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.RemoteProtocolError("peer disconnected", request=request)

    reconciler = OpenAITextReconciler(
        api_key="test-key",
        max_retries=2,
        retry_backoff_seconds=(0.1, 0.2),
        transport=httpx.MockTransport(handler),
        sleep=delays.append,
    )

    with pytest.raises(ProviderRetryableError, match="RECONCILER_PROVIDER_RETRYABLE"):
        reconciler.reconcile(_minimal_reconcile_request())

    assert attempts == 3
    assert delays == [0.1, 0.2]


def test_openai_reconciler_rejects_a_provenance_bearing_invented_task_identity() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Buy milk",
        stability="stable",
        provider_role="accurate",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "proposal_id": None,
                    "title": "Buy yacht",
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": [],
                    "base_revision": None,
                    "confidence": 0.99,
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="unsupported task identity"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_identity",
                transcript_segments=[segment],
                active_proposals=[],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    ("operation", "predecessor_ids"),
    [
        ("update", []),
        ("split", ["proposal_existing"]),
        ("merge", ["proposal_existing", "proposal_other"]),
        ("supersede", ["proposal_existing"]),
    ],
)
def test_openai_reconciler_rejects_invented_identity_for_every_structural_and_update_shape(
    operation: str, predecessor_ids: list[str]
) -> None:
    """A transcript that only says "Buy milk" must never yield "Buy yacht",
    regardless of which patch shape carries the invention (item 2 of the
    exact-head review: zero-invention must be fail-closed for ALL shapes)."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Buy milk",
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title="Buy milk",
        source_segment_ids=[segment.id],
        status="provisional",
    )
    other = ReconciledProposal(
        id="proposal_other",
        title="Buy milk too",
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": operation,
                    "proposal_id": (
                        "proposal_existing" if operation == "update" else None
                    ),
                    "title": "Buy yacht",
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": predecessor_ids,
                    "base_revision": 1 if operation == "update" else None,
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="unsupported task identity"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_identity_all_shapes",
                transcript_segments=[segment],
                active_proposals=[existing, other],
                user_locks={},
            )
        )


def test_openai_reconciler_rejects_an_ungrounded_removal() -> None:
    """A destructive removal with no cited transcript evidence must be
    rejected fail-closed, not applied purely on the model's say-so."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Buy milk",
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title="Buy milk",
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "remove",
                    "proposal_id": "proposal_existing",
                    "title": None,
                    "source_segment_ids": [],
                    "predecessor_ids": [],
                    "base_revision": None,
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="unknown transcript provenance"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_ungrounded_removal",
                transcript_segments=[segment],
                active_proposals=[existing],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    ("operation", "predecessor_ids"),
    [
        ("add", []),
        ("update", []),
        ("split", ["proposal_existing"]),
        ("merge", ["proposal_existing", "proposal_other"]),
        ("supersede", ["proposal_existing"]),
    ],
)
def test_openai_reconciler_rejects_concrete_identity_mismatch_despite_generic_overlap(
    operation: str, predecessor_ids: list[str]
) -> None:
    """A shared generic action word ("call") is not sufficient grounding
    when each side also names its OWN distinct concrete target: citing
    transcript "Call Alice" to justify a title of "Call Bob" is a
    concrete-identity mismatch, not a wording normalization, and must fail
    closed in every patch shape (item 3 of the exact-head review). This is
    not zero lexical overlap -- "call" is shared -- so only the dedicated
    identity-mismatch guard, not the base grounding check, can catch it."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Call Alice",
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title="Call Alice",
        source_segment_ids=[segment.id],
        status="provisional",
        title_revision=1,
    )
    other = ReconciledProposal(
        id="proposal_other",
        title="Call Alice too",
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": operation,
                    "proposal_id": (
                        "proposal_existing" if operation == "update" else None
                    ),
                    "title": "Call Bob",
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": predecessor_ids,
                    "base_revision": 1 if operation == "update" else None,
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="different concrete identity"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_identity_mismatch",
                transcript_segments=[segment],
                active_proposals=[existing, other],
                user_locks={},
            )
        )


def test_openai_reconciler_rejects_concrete_identity_mismatch_in_russian() -> None:
    """The same concrete-identity guard must fire in Russian, not only
    English: a shared generic verb ("позвонить") cannot ground a title that
    names a different person than the one the transcript actually cites."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Позвонить Ивану",
        stability="stable",
        provider_role="accurate",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": "Позвонить Петру",
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="different concrete identity"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_identity_mismatch_ru",
                transcript_segments=[segment],
                active_proposals=[],
                user_locks={},
            )
        )


def test_openai_reconciler_rejects_concrete_identity_mismatch_in_mixed_ru_en() -> None:
    """Mixed-language transcripts must ground the same way: a Russian
    generic verb shared with an English title's own verb is still not
    enough when the named target itself differs (item 3, EN/RU+EN data)."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="надо написать Alice про отчет",
        stability="stable",
        provider_role="accurate",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": "Написать Bob",
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="different concrete identity"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_identity_mismatch_mixed",
                transcript_segments=[segment],
                active_proposals=[],
                user_locks={},
            )
        )


def test_openai_reconciler_rejects_lowercase_generic_object_swap() -> None:
    """A shared generic action word ("schedule") must not launder an object
    swap when neither side is capitalized and the differing word is a
    common noun rather than a proper name: "Schedule meeting" cited as
    grounding for "Schedule dentist" is an invented concrete target, not a
    wording normalization (exact-head review item 1)."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Schedule meeting with the team",
        stability="stable",
        provider_role="accurate",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": "Schedule dentist",
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="different concrete identity"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_identity_mismatch_lowercase_object",
                transcript_segments=[segment],
                active_proposals=[],
                user_locks={},
            )
        )


def test_openai_reconciler_rejects_concrete_identity_mismatch_in_lowercase_russian() -> (
    None
):
    """Real STT output is routinely all-lowercase, especially Cyrillic; the
    concrete-identity guard must not silently disable itself just because
    capitalization gives no signal (exact-head review item 1)."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="надо позвонить ивану",
        stability="stable",
        provider_role="accurate",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": "позвонить петру",
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="different concrete identity"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_identity_mismatch_lowercase_ru",
                transcript_segments=[segment],
                active_proposals=[],
                user_locks={},
            )
        )


def test_openai_reconciler_rejects_concrete_identity_mismatch_in_lowercase_mixed_ru_en() -> (
    None
):
    """Mixed-language, all-lowercase, short-name transcripts must still be
    caught: "bob" is short enough to be filtered from the base grounding
    overlap check, so the dedicated identity-anchor guard must catch it
    independently (exact-head review item 1)."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="надо написать alice про отчет",
        stability="stable",
        provider_role="accurate",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": "написать bob про отчет",
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="different concrete identity"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_identity_mismatch_lowercase_mixed",
                transcript_segments=[segment],
                active_proposals=[],
                user_locks={},
            )
        )


def test_openai_reconciler_preserves_verb_normalization_when_concrete_identity_matches() -> (
    None
):
    """The model may still normalize the verb itself (e.g. "Call" ->
    "Phone") as long as the concrete named target is the same one the
    transcript cites; that is a legitimate wording correction, not an
    invented identity, and must keep passing."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Call Alice",
        stability="stable",
        provider_role="accurate",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": "Phone Alice",
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    result = reconciler.reconcile(
        ReconcileTextRequest(
            operation_id="operation_verb_normalization",
            transcript_segments=[segment],
            active_proposals=[],
            user_locks={},
        )
    )

    assert result.patches[0].title == "Phone Alice"


@pytest.mark.parametrize(
    ("operation", "source_title", "invented_title", "predecessor_ids"),
    [
        ("add", "Email Alice", "Fire Alice", []),
        ("update", "Email Alice", "Fire Alice", []),
        ("split", "Buy milk", "Transfer milk", ["proposal_existing"]),
        (
            "merge",
            "Купить молоко",
            "Украсть молоко",
            ["proposal_existing", "proposal_other"],
        ),
        ("supersede", "Написать Alice", "Заблокировать Alice", ["proposal_existing"]),
    ],
)
def test_openai_reconciler_rejects_unentailed_actions_in_every_title_patch_shape(
    operation: str,
    source_title: str,
    invented_title: str,
    predecessor_ids: list[str],
) -> None:
    """Unknown EN/RU/mixed verbs and structural patch shapes must not bypass
    same-clause action entailment. An uncertain action stays a conflict for
    explicit user editing instead of becoming a committable invented task."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_title,
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title=source_title,
        source_segment_ids=[segment.id],
        status="provisional",
        title_revision=1,
    )
    other = ReconciledProposal(
        id="proposal_other",
        title=source_title,
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": operation,
                    "proposal_id": (
                        "proposal_existing" if operation == "update" else None
                    ),
                    "title": invented_title,
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": predecessor_ids,
                    "base_revision": 1 if operation == "update" else None,
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="one cited transcript clause"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id=f"operation_unentailed_{operation}",
                transcript_segments=[segment],
                active_proposals=[existing, other],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    ("source_title", "invented_title"),
    [
        ("Do not burn contract", "Burn contract"),
        ("Не сжигать договор", "Сжигать договор"),
        ("Do not удалить задачу купить молоко", "Удалить задачу купить молоко"),
        ("Please email Alice about the fire drill", "Please fire Alice"),
        ("Fire Bob, email Alice", "Fire Alice"),
        ("Заблокировать Бориса, написать Алису", "Заблокировать Алису"),
    ],
)
@pytest.mark.parametrize(
    ("operation", "predecessor_ids"),
    [
        ("add", []),
        ("update", []),
        ("split", ["proposal_existing"]),
        ("merge", ["proposal_existing", "proposal_other"]),
        ("supersede", ["proposal_existing"]),
    ],
)
def test_openai_reconciler_binds_affirmative_action_to_its_cited_target(
    source_title: str,
    invented_title: str,
    operation: str,
    predecessor_ids: list[str],
) -> None:
    """A shared target or filler cannot detach a proposed action from polarity
    or from the source predicate that actually governs that target."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_title,
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title=source_title,
        source_segment_ids=[segment.id],
        status="provisional",
        title_revision=1,
    )
    other = ReconciledProposal(
        id="proposal_other",
        title=source_title,
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": operation,
                    "proposal_id": (
                        "proposal_existing" if operation == "update" else None
                    ),
                    "title": invented_title,
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": predecessor_ids,
                    "base_revision": 1 if operation == "update" else None,
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="one cited transcript clause"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id=f"operation_bound_action_{operation}",
                transcript_segments=[segment],
                active_proposals=[existing, other],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    ("source_title", "rebound_title"),
    [
        ("Fire Bob, email Alice, and schedule Carol", "Fire Alice"),
        (
            "Заблокировать Бориса, проверить Алису, и позвать Карла",
            "Заблокировать Алису",
        ),
        ("Block Bob, написать Alice, and file report", "Block Alice"),
        ("Do not fire Bob, Alice, and Carol", "Fire Alice"),
        ("Не надо блокировать Бориса, Алису, и Карла", "Блокировать Алису"),
        ("Email team plus fire Bob, Alice, and Carol", "Email Alice"),
        (
            "Написать команде а заблокировать Бориса, Алису, и Карла",
            "Написать Алису",
        ),
        (
            "Email team плюс заблокировать Bob, Alice, and Carol",
            "Email Alice",
        ),
        ("Email team while fire Bob, Alice, and Carol", "Email Alice"),
        (
            "Написать команде однако заблокировать Бориса, Алису, и Карла",
            "Написать Алису",
        ),
        (
            "Email team also заблокировать Bob, Alice, and Carol",
            "Email Alice",
        ),
    ],
)
@pytest.mark.parametrize(
    ("operation", "predecessor_ids"),
    [
        ("add", []),
        ("update", []),
        ("split", ["proposal_existing"]),
        ("merge", ["proposal_existing", "proposal_other"]),
        ("supersede", ["proposal_existing"]),
    ],
)
def test_openai_reconciler_rejects_serial_list_action_target_rebinding(
    source_title: str,
    rebound_title: str,
    operation: str,
    predecessor_ids: list[str],
) -> None:
    """An Oxford comma must not collapse distinct predicate-target groups."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_title,
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title=source_title,
        source_segment_ids=[segment.id],
        status="provisional",
        title_revision=1,
    )
    other = ReconciledProposal(
        id="proposal_other",
        title=source_title,
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": operation,
                    "proposal_id": (
                        "proposal_existing" if operation == "update" else None
                    ),
                    "title": rebound_title,
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": predecessor_ids,
                    "base_revision": 1 if operation == "update" else None,
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="one cited transcript clause"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id=f"operation_serial_binding_{operation}",
                transcript_segments=[segment],
                active_proposals=[existing, other],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    ("source_title", "supported_title"),
    [
        ("Buy milk, bread, and eggs", "Buy bread"),
        ("Split, merge, and remove tasks", "Merge tasks"),
        ("Schedule meeting and call dentist", "Call dentist"),
    ],
)
def test_openai_reconciler_preserves_safe_conjunction_and_serial_lists(
    source_title: str,
    supported_title: str,
) -> None:
    """Unambiguous shared-action/shared-target lists remain supported."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_title,
        stability="stable",
        provider_role="accurate",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": supported_title,
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    result = reconciler.reconcile(
        ReconcileTextRequest(
            operation_id="operation_safe_serial_list",
            transcript_segments=[segment],
            active_proposals=[],
            user_locks={},
        )
    )

    assert result.patches[0].title == supported_title


@pytest.mark.parametrize(
    ("source_title", "supported_title"),
    [
        ("Buy milk, orange juice, and eggs", "Buy orange juice"),
        ("Купить молоко, апельсиновый сок, и яйца", "Купить апельсиновый сок"),
        ("Buy milk, апельсиновый сок, and eggs", "Buy апельсиновый сок"),
    ],
)
@pytest.mark.parametrize(
    ("operation", "predecessor_ids"),
    [
        ("add", []),
        ("update", []),
        ("split", ["proposal_existing"]),
        ("merge", ["proposal_existing", "proposal_other"]),
        ("supersede", ["proposal_existing"]),
    ],
)
def test_openai_reconciler_accepts_shared_predicate_multiword_target_lists(
    source_title: str,
    supported_title: str,
    operation: str,
    predecessor_ids: list[str],
) -> None:
    """A local shared predicate governs every multiword Oxford-list target."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_title,
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title=source_title,
        source_segment_ids=[segment.id],
        status="provisional",
        title_revision=1,
    )
    other = ReconciledProposal(
        id="proposal_other",
        title=source_title,
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": operation,
                    "proposal_id": (
                        "proposal_existing" if operation == "update" else None
                    ),
                    "title": supported_title,
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": predecessor_ids,
                    "base_revision": 1 if operation == "update" else None,
                }
            ]
        },
    )

    result = reconciler.reconcile(
        ReconcileTextRequest(
            operation_id=f"operation_multiword_target_{operation}",
            transcript_segments=[segment],
            active_proposals=[existing, other],
            user_locks={},
        )
    )

    assert result.patches[0].title == supported_title


@pytest.mark.parametrize(
    ("source_title", "rebound_title", "local_title"),
    [
        (
            "Email team and fire Bob, Alice, and Carol",
            "Email Alice",
            "Fire Alice",
        ),
        (
            "Написать команде и заблокировать Бориса, Алису, и Карла",
            "Написать Алису",
            "Заблокировать Алису",
        ),
        (
            "Email team and заблокировать Bob, Alice, and Carol",
            "Email Alice",
            "Заблокировать Alice",
        ),
    ],
)
@pytest.mark.parametrize(
    ("operation", "predecessor_ids"),
    [
        ("add", []),
        ("update", []),
        ("split", ["proposal_existing"]),
        ("merge", ["proposal_existing", "proposal_other"]),
        ("supersede", ["proposal_existing"]),
    ],
)
def test_openai_reconciler_binds_target_list_to_nearest_compound_predicate(
    source_title: str,
    rebound_title: str,
    local_title: str,
    operation: str,
    predecessor_ids: list[str],
) -> None:
    """A trailing target list cannot rebind an earlier compound predicate."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_title,
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title=source_title,
        source_segment_ids=[segment.id],
        status="provisional",
        title_revision=1,
    )
    other = ReconciledProposal(
        id="proposal_other",
        title=source_title,
        source_segment_ids=[segment.id],
        status="provisional",
    )

    def reconcile(title: str):
        reconciler = OpenAITextReconciler(
            api_key="test-key",
            complete=lambda _payload: {
                "operations": [
                    {
                        "operation": operation,
                        "proposal_id": (
                            "proposal_existing" if operation == "update" else None
                        ),
                        "title": title,
                        "source_segment_ids": [segment.id],
                        "predecessor_ids": predecessor_ids,
                        "base_revision": 1 if operation == "update" else None,
                    }
                ]
            },
        )
        return reconciler.reconcile(
            ReconcileTextRequest(
                operation_id=f"operation_nearest_predicate_{operation}",
                transcript_segments=[segment],
                active_proposals=[existing, other],
                user_locks={},
            )
        )

    with pytest.raises(ValidationFailure, match="one cited transcript clause"):
        reconcile(rebound_title)
    assert reconcile(local_title).patches[0].title == local_title


@pytest.mark.parametrize(
    ("source_title", "affirmative_title"),
    [
        ("Do not split, merge, delete, and remove tasks", "Delete tasks"),
        (
            "Не надо разделять, объединять, удалять, и архивировать задачи",
            "Удалять задачи",
        ),
        ("Do not split, объединять, delete, and remove tasks", "Delete tasks"),
        ("Burn contract never", "Burn contract"),
        ("Сжигать договор не надо", "Сжигать договор"),
        ("Delete задачу нельзя", "Delete задачу"),
    ],
)
@pytest.mark.parametrize(
    ("operation", "predecessor_ids"),
    [
        ("add", []),
        ("update", []),
        ("split", ["proposal_existing"]),
        ("merge", ["proposal_existing", "proposal_other"]),
        ("supersede", ["proposal_existing"]),
    ],
)
def test_openai_reconciler_preserves_coordinated_and_postposed_negation(
    source_title: str,
    affirmative_title: str,
    operation: str,
    predecessor_ids: list[str],
) -> None:
    """Shared initial and postposed negation cannot become affirmative patches."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_title,
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title=affirmative_title,
        source_segment_ids=[segment.id],
        status="provisional",
        title_revision=1,
    )
    other = ReconciledProposal(
        id="proposal_other",
        title=affirmative_title,
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": operation,
                    "proposal_id": (
                        "proposal_existing" if operation == "update" else None
                    ),
                    "title": affirmative_title,
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": predecessor_ids,
                    "base_revision": 1 if operation == "update" else None,
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="one cited transcript clause"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id=f"operation_preserve_negation_{operation}",
                transcript_segments=[segment],
                active_proposals=[existing, other],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    ("source_text", "expected_clauses"),
    [
        ("!. Buy milk, bread, and eggs", ["Buy milk", "buy bread", "buy eggs"]),
        ("Please kindly, milk, and bread", ["Please kindly", "milk", "bread"]),
        (
            "Buy milk, orange juice, and eggs",
            ["Buy milk", "buy orange juice", "buy eggs"],
        ),
        (
            "Plan chores, split, merge, and remove tasks",
            ["Plan chores", "split tasks", "merge tasks", "remove tasks"],
        ),
        (
            "Email team plus fire Bob, Alice, and Carol",
            ["Email team plus fire Bob", "Alice", "Carol"],
        ),
        (
            "Написать команде а заблокировать Бориса, Алису, и Карла",
            ["Написать команде а заблокировать Бориса", "Алису", "Карла"],
        ),
        (
            "Email team плюс заблокировать Bob, Alice, and Carol",
            ["Email team плюс заблокировать Bob", "Alice", "Carol"],
        ),
    ],
)
def test_openai_reconciler_source_clauses_distinguish_safe_and_ambiguous_serial_shapes(
    source_text: str,
    expected_clauses: list[str],
) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    assert OpenAITextReconciler._source_clauses(source_text) == expected_clauses


def test_openai_reconciler_accepts_an_affirmative_action_after_polite_filler() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Please email Alice",
        stability="stable",
        provider_role="accurate",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": "Please email Alice",
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    result = reconciler.reconcile(
        ReconcileTextRequest(
            operation_id="operation_affirmative_filler",
            transcript_segments=[segment],
            active_proposals=[],
            user_locks={},
        )
    )

    assert result.patches[0].title == "Please email Alice"


def test_openai_reconciler_rejects_a_positive_removal_without_destructive_language() -> (
    None
):
    """Positive, constructive text about the same subject ("Buy milk") must
    never authorize deleting an existing proposal -- concrete-identity
    overlap alone is not consent to destroy (item 3 of the exact-head
    review)."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text="Buy milk",
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title="Buy milk",
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "remove",
                    "proposal_id": "proposal_existing",
                    "title": None,
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": [],
                    "base_revision": None,
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="no explicit destructive or"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_positive_removal",
                transcript_segments=[segment],
                active_proposals=[existing],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    ("source_text", "title"),
    [
        ("Delete the milk task", "Buy milk"),
        ("Удалить эту задачу про молоко", "Купить молоко"),
        ("No longer need to buy milk", "Buy milk"),
        ("Не нужно покупать молоко", "Купить молоко"),
    ],
)
def test_openai_reconciler_accepts_a_removal_with_explicit_destructive_language(
    source_text: str, title: str
) -> None:
    """Explicit destructive/negating language -- in English or Russian --
    still authorizes a removal grounded in the same concrete subject."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_text,
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title=title,
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "remove",
                    "proposal_id": "proposal_existing",
                    "title": None,
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": [],
                    "base_revision": None,
                }
            ]
        },
    )

    result = reconciler.reconcile(
        ReconcileTextRequest(
            operation_id="operation_valid_removal",
            transcript_segments=[segment],
            active_proposals=[existing],
            user_locks={},
        )
    )

    assert result.patches[0].operation == "remove"
    assert result.patches[0].proposal_id == "proposal_existing"


@pytest.mark.parametrize(
    "source_text",
    [
        "Do not delete Buy milk",
        "Don't delete Buy milk",
        "Не удаляй Купить молоко",
        "Не надо редактировать задачу купить молоко",
        "Не нужно менять задачу купить молоко",
        "Не надо edit задачу купить молоко",
        "Do not delete apples, milk, and eggs",
        "Не надо удалять хлеб, молоко, и яйца",
    ],
)
def test_openai_reconciler_rejects_a_negated_destructive_removal(source_text: str) -> None:
    """'Do not delete Buy milk' must never authorize removing 'Buy milk':
    a negation marker scopes over the destructive term it precedes, so a
    negated/scoped destructive phrase must fail closed exactly like
    positive, non-destructive text (exact-head review item 2)."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    title = "Buy milk" if "milk" in source_text.casefold() else "Купить молоко"
    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_text,
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title=title,
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "remove",
                    "proposal_id": "proposal_existing",
                    "title": None,
                    "source_segment_ids": [segment.id],
                    "predecessor_ids": [],
                    "base_revision": None,
                }
            ]
        },
    )

    with pytest.raises(
        ValidationFailure,
        match="one cited transcript clause|no explicit destructive or",
    ):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_negated_removal",
                transcript_segments=[segment],
                active_proposals=[existing],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    ("source_text", "existing_title"),
    [
        ("Do not split, merge, delete, and remove tasks", "Tasks"),
        (
            "Не надо разделять, объединять, удалять, и архивировать задачи",
            "Задачи",
        ),
        ("Do not split, объединять, delete, and remove tasks", "Tasks"),
        ("Delete task Call Alice never", "Call Alice"),
        ("Удалять задачу Позвонить Ивану не надо", "Позвонить Ивану"),
        ("Удалять задачу Позвонить Ивану нельзя", "Позвонить Ивану"),
    ],
)
def test_openai_reconciler_rejects_coordinated_and_postposed_negated_removal(
    source_text: str,
    existing_title: str,
) -> None:
    """Shared and postposed negation cannot authorize a destructive removal."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_text,
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title=existing_title,
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "remove",
                    "proposal_id": existing.id,
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    with pytest.raises(
        ValidationFailure,
        match="one cited transcript clause|no explicit destructive or",
    ):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_coordinated_postposed_negated_removal",
                transcript_segments=[segment],
                active_proposals=[existing],
                user_locks={},
            )
        )


def test_openai_reconciler_rejects_negated_scoped_serial_removal() -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    source_text = "Project Alpha: archive, mute, purge, and do not remove tasks"
    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_text,
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title="Project Alpha",
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "remove",
                    "proposal_id": existing.id,
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="no explicit destructive or"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_negated_scoped_serial_removal",
                transcript_segments=[segment],
                active_proposals=[existing],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    ("source_text", "draft_title"),
    [
        ("Buy milk", "Buy milk and transfer money"),
        ("Купить молоко", "Купить молоко и яхту"),
        ("Написать Alice про отчет", "Написать Alice про отчет and transfer money"),
        ("Schedule meeting and call dentist", "Schedule dentist"),
    ],
)
def test_openai_reconciler_rejects_additive_and_cross_clause_invention(
    source_text: str, draft_title: str
) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_text,
        stability="stable",
        provider_role="accurate",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": draft_title,
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="unsupported task identity"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_additive_invention",
                transcript_segments=[segment],
                active_proposals=[],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    ("source_text", "title"),
    [
        ("Delete calendar entry. Buy milk", "Buy milk"),
        ("Do not delete Buy milk. Remove Buy bread.", "Buy milk"),
        ("Не удаляй Купить молоко. Удали Купить хлеб.", "Купить молоко"),
        ("Do not ever permanently delete buy milk", "Buy milk"),
        ("Never under any circumstances delete buy milk", "Buy milk"),
        ("Не надо ни в коем случае удалить задачу купить молоко", "Купить молоко"),
        ("Не надо ни в коем случае удалять задачу купить молоко", "Купить молоко"),
        ("Не нужно ни в коем случае удалять задачу купить молоко", "Купить молоко"),
        ("Do not удалять задачу купить молоко", "Купить молоко"),
    ],
)
def test_openai_reconciler_rejects_wrong_target_and_long_distance_negated_removal(
    source_text: str, title: str
) -> None:
    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_text,
        stability="stable",
        provider_role="accurate",
    )
    existing = ReconciledProposal(
        id="proposal_existing",
        title=title,
        source_segment_ids=[segment.id],
        status="provisional",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "remove",
                    "proposal_id": "proposal_existing",
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="unsupported destructive removal"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_scoped_removal",
                transcript_segments=[segment],
                active_proposals=[existing],
                user_locks={},
            )
        )


@pytest.mark.parametrize(
    ("source_text", "draft_title"),
    [
        ("Save money", "Transfer money"),
        ("Купить молоко", "Украсть молоко"),
        ("Write Alice about report", "Pay Alice about report"),
    ],
)
def test_openai_reconciler_rejects_single_clause_material_action_invention(
    source_text: str, draft_title: str
) -> None:
    """Same-target action changes need source evidence, not matching objects."""

    from app.workflows.voice_brain_dump.adapters.reconciler import OpenAITextReconciler

    segment = TranscriptHypothesis(
        id="segment_accurate",
        sequence=1,
        start_ms=0,
        end_ms=1000,
        text=source_text,
        stability="stable",
        provider_role="accurate",
    )
    reconciler = OpenAITextReconciler(
        api_key="test-key",
        complete=lambda _payload: {
            "operations": [
                {
                    "operation": "add",
                    "title": draft_title,
                    "source_segment_ids": [segment.id],
                }
            ]
        },
    )

    with pytest.raises(ValidationFailure, match="unsupported task identity"):
        reconciler.reconcile(
            ReconcileTextRequest(
                operation_id="operation_single_clause_action_invention",
                transcript_segments=[segment],
                active_proposals=[],
                user_locks={},
            )
        )
