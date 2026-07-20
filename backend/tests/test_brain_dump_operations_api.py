"""API tests for native voice Brain Dump operations."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import httpx
import pytest

from app.exceptions import (
    ProviderRetryableError,
    ProviderTerminalError,
    ValidationFailure,
)
from app.workflows.voice_brain_dump.adapters import OpenAiAccurateStt


def _start_operation(
    api_client,
    key: str = "start-brain-dump",
    *,
    external_processing_allowed: bool = True,
    language_hints: list[str] | None = None,
    vocabulary: list[str] | None = None,
):
    response = api_client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": key},
        json={
            "consent": {
                "microphone": True,
                "external_processing_allowed": external_processing_allowed,
                "provider": "openai" if external_processing_allowed else None,
                "language_hints": language_hints or [],
                "vocabulary": vocabulary or [],
            }
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _manifest_hash(audio: bytes) -> str:
    digest = hashlib.sha256(audio).hexdigest()
    return hashlib.sha256(
        json.dumps(
            [{"chunk_number": 0, "sha256": digest, "size_bytes": len(audio)}],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _real_adapter(transport: httpx.BaseTransport) -> OpenAiAccurateStt:
    return OpenAiAccurateStt(
        api_key="test-key",
        model="gpt-4o-mini-transcribe",
        timeout_seconds=1,
        max_retries=0,
        retry_backoff_seconds=(),
        max_cost_usd_per_operation=1,
        estimated_cost_usd_per_megabyte=0.01,
        transport=transport,
    )


def _withdraw_consent(api_client, operation_id: str) -> None:
    """Simulate a consent withdrawal after audio was durably uploaded.

    Exercises the seal-time defense-in-depth consent gates independently of
    the upload-time gate, which now refuses to persist audio at all when
    consent is absent from the start.
    """

    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    persisted = container.voice_brain_dump_service.get_brain_dump_operation(
        operation_id, owner_id=owner_id
    )
    withdrawn = persisted.model_copy(
        update={
            "consent": persisted.consent.model_copy(
                update={"external_processing_allowed": False}
            )
        }
    )
    container.voice_operation_repo.save_brain_dump_operation(withdrawn)


def _advance_persisted_provider_runs(api_client, operation_id: str):
    """Drive the persisted in-process runner until this operation is idle in tests."""

    service = api_client.app.state.container.voice_brain_dump_service
    for _ in range(3):
        if service.run_due_brain_dump_provider_runs() == 0:
            break
    return api_client.get(f"/api/brain-dump-operations/{operation_id}")


def _upload_and_seal(api_client, operation: dict[str, object], audio: bytes, key: str):
    digest = hashlib.sha256(audio).hexdigest()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )
    assert uploaded.status_code == 200, uploaded.text
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": key},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 200, sealed.text
    return _advance_persisted_provider_runs(api_client, str(operation["id"]))


def test_seal_uses_semantic_reconciler_when_external_processing_is_allowed(
    api_client,
) -> None:
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client,
        key="start-semantic-reconciler",
        external_processing_allowed=True,
        language_hints=["ru", "en"],
        vocabulary=["BrainBuddy", "production smoke"],
    )

    def complete(payload: dict[str, object]) -> dict[str, object]:
        context = json.loads(payload["messages"][1]["content"])  # type: ignore[index]
        assert context["language_hints"] == ["ru", "en"]
        assert context["vocabulary"] == ["BrainBuddy", "production smoke"]
        segment_id = context["transcript_segments"][0]["id"]
        return {
            "operations": [
                {
                    "operation": "add",
                    "proposal_id": None,
                    "title": "Разобраться с документами для поездки",
                    "source_segment_ids": [segment_id],
                    "predecessor_ids": [],
                    "base_revision": None,
                }
            ]
        }

    api_client.app.state.container.voice_brain_dump_service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=complete
    )
    sealed = _upload_and_seal(
        api_client,
        operation,
        "надо разобраться с документами для поездки".encode(),
        "seal-semantic-reconciler",
    )

    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "awaiting_confirmation"
    assert [proposal["title"] for proposal in sealed.json()["proposals"]] == [
        "Разобраться с документами для поездки"
    ]


def test_semantic_reconciler_updates_and_removes_existing_proposals(
    api_client,
) -> None:
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client,
        key="start-semantic-update-remove",
        external_processing_allowed=True,
    )
    preview = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "preview-semantic-update-remove"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "Починить brain body. Удалить лишний черновик.",
                    "stability": "stable",
                }
            ]
        },
    ).json()
    first, second = preview["proposals"]

    def complete(payload: dict[str, object]) -> dict[str, object]:
        context = json.loads(payload["messages"][1]["content"])  # type: ignore[index]
        segment_id = context["transcript_segments"][0]["id"]
        return {
            "operations": [
                {
                    "operation": "update",
                    "proposal_id": first["id"],
                    "title": "Починить BrainBuddy",
                    "source_segment_ids": [segment_id],
                    "predecessor_ids": [],
                    "base_revision": first["revision"],
                },
                {
                    "operation": "remove",
                    "proposal_id": second["id"],
                    "title": None,
                    "source_segment_ids": [segment_id],
                    "predecessor_ids": [],
                    "base_revision": second["revision"],
                },
            ]
        }

    api_client.app.state.container.voice_brain_dump_service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=complete
    )
    sealed = _upload_and_seal(
        api_client,
        operation,
        "Починить BrainBuddy. Удалить лишний черновик.".encode(),
        "seal-update-remove",
    )

    assert sealed.status_code == 200, sealed.text
    body = sealed.json()
    by_id = {proposal["id"]: proposal for proposal in body["proposals"]}
    assert by_id[first["id"]]["title"] == "Починить BrainBuddy"
    assert by_id[first["id"]]["status"] == "reconciled"
    # A provider-driven destructive removal must stay visible and individually
    # confirmed rather than silently disappearing (exact-head review item 1):
    # it surfaces as an open conflict, not an immediate tombstone.
    removed_candidate = by_id[second["id"]]
    assert removed_candidate["deleted"] is False
    assert removed_candidate["conflicts"][0]["field"] == "removal"
    assert removed_candidate["conflicts"][0]["suggested_value"] == "removed"

    confirmed = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{second['id']}",
        headers={"Idempotency-Key": "confirm-model-removal"},
        json={"conflict_resolution": "accept", "expected_revision": body["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_by_id = {
        proposal["id"]: proposal for proposal in confirmed.json()["proposals"]
    }
    assert confirmed_by_id[second["id"]]["deleted"] is True
    assert confirmed_by_id[second["id"]]["conflicts"] == []


def test_retention_sweep_never_purges_a_retryable_error_operation(api_client) -> None:
    """Exact-head review item 3: ``retryable_error`` is recoverable, not
    terminal -- retention purge is enforced ``only`` for completed/
    cancelled/terminal_error, so a still-retryable operation must keep its
    raw audio and working artifacts no matter how old it looks, since a
    retry still needs that data."""

    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client,
        key="start-retryable-retention-guard",
        external_processing_allowed=True,
    )

    def fail(_payload: dict[str, object]) -> dict[str, object]:
        raise ProviderRetryableError("temporary outage")

    service = api_client.app.state.container.voice_brain_dump_service
    service.text_reconciler = OpenAITextReconciler(api_key="test-key", complete=fail)
    sealed = _upload_and_seal(
        api_client, operation, b"retryable retention guard", "seal-retryable-retention"
    )
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "retryable_error"

    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]
    persisted = container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    aged = persisted.model_copy(
        update={
            "updated_at": persisted.updated_at - timedelta(days=30),
            "raw_audio_expires_at": persisted.created_at - timedelta(days=30),
        }
    )
    container.voice_operation_repo.save_brain_dump_operation(aged)

    assert container.voice_brain_dump_service.purge_expired_raw_audio() == 0
    assert container.voice_brain_dump_service.purge_expired_working_artifacts() == 0
    swept = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert swept["status"] == "retryable_error"
    assert swept["audio_chunks"] != []
    assert swept["segments"] != []


@pytest.mark.parametrize(
    ("provider_error", "expected_status", "expected_code"),
    [
        (
            ProviderRetryableError("temporary outage"),
            "retryable_error",
            "PROVIDER_ERROR_UNSPECIFIED",
        ),
        (
            ProviderTerminalError("provider rejected"),
            "terminal_error",
            "PROVIDER_ERROR_UNSPECIFIED",
        ),
        (
            ValidationFailure("invalid model output"),
            "retryable_error",
            "RECONCILER_VALIDATION_REJECTED",
        ),
    ],
)
def test_seal_persists_semantic_reconciler_failures_for_recovery(
    api_client, provider_error: Exception, expected_status: str, expected_code: str
) -> None:
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client,
        key=f"start-semantic-failure-{type(provider_error).__name__}",
        external_processing_allowed=True,
    )

    def fail(_payload: dict[str, object]) -> dict[str, object]:
        raise provider_error

    service = api_client.app.state.container.voice_brain_dump_service
    service.text_reconciler = OpenAITextReconciler(api_key="test-key", complete=fail)
    sealed = _upload_and_seal(
        api_client, operation, b"provider failure recovery", "seal-semantic-failure"
    )

    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == expected_status
    persisted_run = sealed.json()["provider_runs"][-1]
    assert persisted_run["role"] == "reconciler"
    assert persisted_run["status"] == expected_status
    assert persisted_run["error"] == expected_code
    assert persisted_run["error_code"] == expected_code
    assert str(provider_error) not in sealed.text


def test_accurate_stt_failure_records_a_conservative_cost_estimate(api_client) -> None:
    """Item 6 (F3): a failed accurate-STT attempt still made a real, billable
    call; the persisted run must record that spend so the cumulative
    operation-wide cost cap sees it, rather than silently recording zero for
    every failed attempt."""

    api_client.app.state.container.voice_brain_dump_service.accurate_stt = _real_adapter(
        httpx.MockTransport(lambda _request: httpx.Response(503))
    )
    operation = _start_operation(
        api_client, key="start-stt-failure-cost", external_processing_allowed=True
    )
    sealed = _upload_and_seal(
        api_client, operation, b"\x1aE\xdf\xa3failing-webm", "seal-stt-failure-cost"
    )

    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "retryable_error"
    accurate_run = next(
        run for run in sealed.json()["provider_runs"] if run["role"] == "accurate_stt"
    )
    assert accurate_run["estimated_cost_usd"] > 0


def test_reconciler_success_records_its_estimated_cost_in_the_operation(
    api_client,
) -> None:
    """Item 6 (F3): reconciler success must record a cost estimate so the
    cumulative cap can see reconciler spend, not just accurate-STT spend."""

    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client, key="start-reconciler-cost", external_processing_allowed=True
    )
    api_client.app.state.container.voice_brain_dump_service.text_reconciler = OpenAITextReconciler(
        api_key="test-key",
        estimated_cost_usd_per_megabyte=1.0,
        complete=lambda _payload: {"operations": []},
    )
    sealed = _upload_and_seal(
        api_client, operation, b"Buy milk", "seal-reconciler-cost"
    )

    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "awaiting_confirmation"
    reconciler_run = next(
        run for run in sealed.json()["provider_runs"] if run["role"] == "reconciler"
    )
    assert reconciler_run["estimated_cost_usd"] > 0


def test_operation_admission_rejects_next_call_when_worst_case_would_exceed_cap(
    api_client,
) -> None:
    """Item 6 (F3): admission must reject the next external call when already
    spent/reserved cost plus the worst-case cost of that next call would
    exceed the operation cap -- not only once spend already reached the cap
    outright. The provider must never be called once admission fails."""

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    task_service = api_client.app.state.container.voice_brain_dump_service
    task_service.max_cumulative_cost_usd_per_operation = 1.0
    task_service.accurate_stt = OpenAiAccurateStt(
        api_key="test-key",
        max_retries=0,
        retry_backoff_seconds=(),
        max_cost_usd_per_operation=0.6,
        estimated_cost_usd_per_megabyte=0.0000001,
        transport=httpx.MockTransport(handler),
    )
    operation = _start_operation(
        api_client, key="start-worst-case-admission", external_processing_allowed=True
    )
    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    persisted = container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    from app.utils.time import utcnow
    from app.workflows.voice_brain_dump.domain import BrainDumpProviderRunDocument

    now = utcnow()
    already_spent = persisted.model_copy(
        update={
            "provider_runs": [
                BrainDumpProviderRunDocument(
                    id="provider_run_prior_spend",
                    role="accurate_stt",
                    status="retryable_error",
                    input_hash="0" * 64,
                    checkpoint="sealed",
                    attempt=1,
                    recovery_count=0,
                    estimated_cost_usd=0.5,
                    created_at=now,
                    updated_at=now,
                )
            ],
            "revision": persisted.revision + 1,
        }
    )
    container.voice_operation_repo.save_brain_dump_operation(already_spent)

    audio = b"\x1aE\xdf\xa3worst-case-webm"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-worst-case-admission"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )

    assert sealed.status_code == 200, sealed.text
    task_service.run_due_brain_dump_provider_runs()
    sealed = api_client.get(f"/api/brain-dump-operations/{operation['id']}")
    assert sealed.json()["status"] == "terminal_error"
    assert sealed.json()["provider_runs"][-1]["error_code"] == (
        "OPERATION_COST_BUDGET_EXCEEDED"
    )
    assert calls == 0


def test_retryable_reconciler_failure_resumes_without_rerunning_accurate_stt(
    api_client,
) -> None:
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client,
        key="start-reconciler-checkpoint-retry",
        external_processing_allowed=True,
        language_hints=["ru", "en"],
        vocabulary=["BrainBuddy"],
    )
    service = api_client.app.state.container.voice_brain_dump_service
    original_transcribe = service.accurate_stt.transcribe_sealed_audio
    stt_calls = 0
    reconcile_calls = 0

    def recording_transcribe(request):
        nonlocal stt_calls
        stt_calls += 1
        return original_transcribe(request)

    def flaky_reconcile(payload: dict[str, object]) -> dict[str, object]:
        nonlocal reconcile_calls
        reconcile_calls += 1
        if reconcile_calls == 1:
            raise ProviderRetryableError("temporary reconciler outage")
        context = json.loads(payload["messages"][1]["content"])  # type: ignore[index]
        return {
            "operations": [
                {
                    "operation": "add",
                    "proposal_id": None,
                    "title": "Починить BrainBuddy",
                    "source_segment_ids": [context["transcript_segments"][0]["id"]],
                    "predecessor_ids": [],
                    "base_revision": None,
                }
            ]
        }

    service.accurate_stt.transcribe_sealed_audio = recording_transcribe
    service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=flaky_reconcile
    )
    sealed = _upload_and_seal(
        api_client,
        operation,
        "Починить BrainBuddy".encode(),
        "seal-reconciler-checkpoint-retry",
    )
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "retryable_error"
    assert stt_calls == 1

    retried = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/retry",
        headers={"Idempotency-Key": "retry-reconciler-checkpoint"},
        json={"expected_revision": sealed.json()["revision"]},
    )

    assert retried.status_code == 200, retried.text
    retried = _advance_persisted_provider_runs(api_client, str(operation["id"]))
    body = retried.json()
    assert body["status"] == "awaiting_confirmation"
    assert stt_calls == 1
    assert reconcile_calls == 2
    assert len(
        [segment for segment in body["segments"] if segment["provider_role"] == "accurate"]
    ) == 1
    assert len(
        [
            run
            for run in body["provider_runs"]
            if run["role"] == "accurate_stt" and run["status"] == "succeeded"
        ]
    ) == 1


def test_schema_v2_conflict_resolution_requires_a_visible_title_conflict(
    api_client,
) -> None:
    operation = _start_operation(api_client, key="start-no-title-conflict")
    preview = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-no-title-conflict"},
        json={
            "segments": [
                {"sequence": 1, "text": "Call the dentist", "stability": "stable"}
            ]
        },
    )
    proposal_id = preview.json()["proposals"][0]["id"]

    response = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{proposal_id}",
        headers={"Idempotency-Key": "keep-missing-title-conflict"},
        json={
            "conflict_resolution": "keep",
            "expected_revision": preview.json()["revision"],
        },
    )

    assert response.status_code == 400
    assert "no conflict to resolve" in response.text


def test_seal_rejects_external_reconciliation_without_explicit_consent(
    api_client,
) -> None:
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    calls = 0

    def complete(_payload: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"operations": []}

    # Audio can only be uploaded with consent (see the upload-consent-gate
    # tests below), so this exercises a consent withdrawal that happens after
    # upload but before seal -- the reconciler's own defense-in-depth gate.
    operation = _start_operation(
        api_client,
        key="start-reconciler-without-consent",
        external_processing_allowed=True,
    )
    api_client.app.state.container.voice_brain_dump_service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=complete
    )
    audio = b"no external consent"
    digest = hashlib.sha256(audio).hexdigest()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )
    assert uploaded.status_code == 200, uploaded.text
    _withdraw_consent(api_client, operation["id"])

    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-without-consent"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )

    assert sealed.status_code == 200, sealed.text
    sealed = _advance_persisted_provider_runs(api_client, str(operation["id"]))
    assert sealed.json()["status"] == "terminal_error"
    assert sealed.json()["provider_runs"][-1]["error"] == (
        "RECONCILER_CONSENT_REQUIRED"
    )
    assert calls == 0


@pytest.mark.parametrize(
    ("resolution", "expected_title"),
    [("keep", "Починить BrainBuddy MVP"), ("accept", "Починить BrainBuddy")],
)
def test_user_resolves_visible_semantic_title_conflict(
    api_client, resolution: str, expected_title: str
) -> None:
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client,
        key=f"start-conflict-{resolution}",
        external_processing_allowed=True,
    )
    preview = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": f"preview-conflict-{resolution}"},
        json={
            "segments": [
                {"sequence": 1, "text": "Починить brain body", "stability": "stable"}
            ]
        },
    ).json()
    proposal = preview["proposals"][0]
    edited = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{proposal['id']}",
        headers={"Idempotency-Key": f"edit-conflict-{resolution}"},
        json={
            "title": "Починить BrainBuddy MVP",
            "expected_revision": preview["revision"],
        },
    ).json()

    def complete(payload: dict[str, object]) -> dict[str, object]:
        context = json.loads(payload["messages"][1]["content"])  # type: ignore[index]
        segment_id = context["transcript_segments"][0]["id"]
        active = context["proposals"][0]
        return {
            "operations": [
                {
                    "operation": "update",
                    "proposal_id": active["id"],
                    "title": "Починить BrainBuddy",
                    "source_segment_ids": [segment_id],
                    "predecessor_ids": [],
                    "base_revision": active["title_revision"],
                }
            ]
        }

    api_client.app.state.container.voice_brain_dump_service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=complete
    )
    sealed = _upload_and_seal(
        api_client, edited, "Починить BrainBuddy".encode(), f"seal-conflict-{resolution}"
    ).json()
    conflicted = sealed["proposals"][0]
    assert conflicted["conflicts"][0]["suggested_value"] == "Починить BrainBuddy"

    if resolution == "accept":
        service = api_client.app.state.container.voice_brain_dump_service
        owner_id = api_client.get("/api/auth/me").json()["id"]
        persisted = service.get_brain_dump_operation(
            operation["id"], owner_id=owner_id
        )
        persisted_proposal = persisted.proposals[0]
        malformed_proposal = persisted_proposal.model_copy(
            update={
                "conflicts": [
                    persisted_proposal.conflicts[0].model_copy(
                        update={"suggested_value": None}
                    )
                ]
            }
        )
        api_client.app.state.container.voice_operation_repo.save_brain_dump_operation(
            persisted.model_copy(update={"proposals": [malformed_proposal]})
        )
        malformed = api_client.patch(
            f"/api/brain-dump-operations/{operation['id']}/proposals/{conflicted['id']}",
            headers={"Idempotency-Key": "accept-conflict-without-suggestion"},
            json={
                "conflict_resolution": "accept",
                "expected_revision": sealed["revision"],
            },
        )
        assert malformed.status_code == 400
        assert "no suggestion to accept" in malformed.text
        api_client.app.state.container.voice_operation_repo.save_brain_dump_operation(persisted)

    resolved = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{conflicted['id']}",
        headers={"Idempotency-Key": f"resolve-conflict-{resolution}"},
        json={
            "conflict_resolution": resolution,
            "expected_revision": sealed["revision"],
        },
    )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["proposals"][0]["title"] == expected_title
    assert resolved.json()["proposals"][0]["conflicts"] == []


def test_external_stt_receives_declared_hints_through_the_real_decision_path(
    api_client,
) -> None:
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.read())
        return httpx.Response(200, json={"text": "Починить BrainBuddy"})

    api_client.app.state.container.voice_brain_dump_service.accurate_stt = _real_adapter(
        httpx.MockTransport(handler)
    )
    started = api_client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "start-real-hints"},
        json={
            "consent": {
                "microphone": True,
                "external_processing_allowed": True,
                "provider": "openai",
                "language_hints": ["ru", "en"],
                "vocabulary": ["BrainBuddy", "production smoke"],
            }
        },
    )
    assert started.status_code == 201, started.text

    sealed = _upload_and_seal(
        api_client, started.json(), b"\x1aE\xdf\xa3real-webm", "seal-real-hints"
    )

    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "awaiting_confirmation"
    assert len(bodies) == 1
    assert b"\x1aE\xdf\xa3real-webm" in bodies[0]
    assert b'name="language"' in bodies[0] and b"ru" in bodies[0]
    assert b"BrainBuddy" in bodies[0] and b"production smoke" in bodies[0]
    accurate_run = next(
        run for run in sealed.json()["provider_runs"] if run["role"] == "accurate_stt"
    )
    assert accurate_run["provider"] == "openai"


def test_external_stt_is_not_called_without_operation_consent(api_client) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    api_client.app.state.container.voice_brain_dump_service.accurate_stt = _real_adapter(
        httpx.MockTransport(handler)
    )
    # Audio can only be uploaded with consent (see the upload-consent-gate
    # tests below), so this exercises a consent withdrawal that happens after
    # upload but before seal -- the STT's own defense-in-depth gate.
    operation = _start_operation(
        api_client, key="start-no-external-consent", external_processing_allowed=True
    )
    audio = b"\x1aE\xdf\xa3private-webm"
    digest = hashlib.sha256(audio).hexdigest()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )
    assert uploaded.status_code == 200, uploaded.text
    _withdraw_consent(api_client, operation["id"])

    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-no-consent"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )

    assert sealed.status_code == 200, sealed.text
    sealed = _advance_persisted_provider_runs(api_client, str(operation["id"]))
    assert sealed.json()["status"] == "terminal_error"
    assert sealed.json()["provider_runs"][-1]["error_code"] == (
        "STT_EXTERNAL_PROCESSING_CONSENT_REQUIRED"
    )
    assert calls == 0


def test_external_stt_consent_is_bound_to_the_named_provider(api_client) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "must not be called"})

    api_client.app.state.container.voice_brain_dump_service.accurate_stt = OpenAiAccurateStt(
        api_key="test-key", transport=httpx.MockTransport(handler), sleep=lambda _: None
    )
    response = api_client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "start-provider-mismatch"},
        json={
            "consent": {
                "microphone": True,
                "external_processing_allowed": True,
                "provider": "another-provider",
                "language_hints": ["ru"],
                "vocabulary": [],
            }
        },
    )
    assert response.status_code == 201

    operation = response.json()
    rejected = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=b"audio",
        headers={"X-Content-SHA256": hashlib.sha256(b"audio").hexdigest()},
    )

    assert rejected.status_code == 400
    assert "AUDIO_UPLOAD_PROVIDER_CONSENT_REQUIRED" in rejected.text
    assert calls == 0

def test_reconciler_consent_is_bound_to_the_named_provider(api_client) -> None:
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    calls = 0

    def complete(_payload: dict[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"operations": []}

    api_client.app.state.container.voice_brain_dump_service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=complete
    )
    response = api_client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "start-reconciler-provider-mismatch"},
        json={
            "consent": {
                "microphone": True,
                "external_processing_allowed": True,
                "provider": "another-provider",
                "language_hints": ["ru"],
                "vocabulary": [],
            }
        },
    )
    assert response.status_code == 201

    operation = response.json()
    rejected = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=b"audio",
        headers={"X-Content-SHA256": hashlib.sha256(b"audio").hexdigest()},
    )

    assert rejected.status_code == 400
    assert "AUDIO_UPLOAD_PROVIDER_CONSENT_REQUIRED" in rejected.text
    assert calls == 0

def test_audio_upload_fails_closed_and_persists_nothing_without_external_consent(
    api_client,
) -> None:
    operation = _start_operation(
        api_client,
        key="start-upload-without-consent",
        external_processing_allowed=False,
    )

    audio = b"\x1aE\xdf\xa3never-persisted"
    digest = hashlib.sha256(audio).hexdigest()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )

    assert uploaded.status_code == 400, uploaded.text
    assert "AUDIO_UPLOAD_CONSENT_REQUIRED" in uploaded.text

    fetched = api_client.get(f"/api/brain-dump-operations/{operation['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["audio_chunks"] == []
    assert fetched.json()["media_ref"] is None


def test_audio_upload_succeeds_with_explicit_external_consent(api_client) -> None:
    api_client.app.state.container.voice_brain_dump_service.accurate_stt = _real_adapter(
        httpx.MockTransport(lambda _request: httpx.Response(200, json={"text": "ok"}))
    )
    operation = _start_operation(
        api_client, key="start-upload-with-consent", external_processing_allowed=True
    )

    audio = b"\x1aE\xdf\xa3persisted-with-consent"
    digest = hashlib.sha256(audio).hexdigest()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )

    assert uploaded.status_code == 200, uploaded.text
    chunks = uploaded.json()["audio_chunks"]
    assert len(chunks) == 1
    assert chunks[0]["chunk_number"] == 0
    assert chunks[0]["sha256"] == digest
    assert chunks[0]["size_bytes"] == len(audio)


def test_explicit_empty_provider_allowlist_fails_closed_before_audio_upload(
    api_client,
) -> None:
    """An explicitly configured empty allowlist (e.g. a deployment with no
    external voice provider wired up) must reject any named provider and
    never persist raw audio -- distinct from the unit-test-only default of
    ``None``, which permits "openai" for isolated deterministic tests."""

    api_client.app.state.container.voice_brain_dump_service.accurate_stt = _real_adapter(
        httpx.MockTransport(lambda _request: httpx.Response(200, json={"text": "ok"}))
    )
    api_client.app.state.container.voice_brain_dump_service.allowed_external_provider_categories = (
        frozenset()
    )
    operation = _start_operation(
        api_client, key="start-locked-down-allowlist", external_processing_allowed=True
    )

    audio = b"\x1aE\xdf\xa3must-not-be-persisted"
    digest = hashlib.sha256(audio).hexdigest()
    rejected = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )

    assert rejected.status_code == 400, rejected.text
    assert "AUDIO_UPLOAD_PROVIDER_CONSENT_REQUIRED" in rejected.text

    fetched = api_client.get(f"/api/brain-dump-operations/{operation['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["audio_chunks"] == []
    assert fetched.json()["media_ref"] is None


def test_brain_dump_operation_collects_provisional_tasks_without_inbox_writes(
    api_client,
) -> None:
    operation = _start_operation(api_client)
    assert operation["status"] == "recording"
    assert operation["kind"] == "voice_brain_dump"
    assert operation["proposals"] == []

    empty_inbox = api_client.get("/api/tasks", params={"state": "inbox"})
    assert empty_inbox.status_code == 200
    assert empty_inbox.json()["counts_by_state"]["inbox"] == 0

    append = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-initial-segment"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "Renew car insurance. Reply to Anna about the offsite.",
                    "stability": "stable",
                }
            ]
        },
    )
    assert append.status_code == 200, append.text
    body = append.json()
    assert body["status"] == "recording"
    assert [proposal["title"] for proposal in body["proposals"]] == [
        "Renew car insurance",
        "Reply to Anna about the offsite",
    ]
    assert [proposal["ordinal"] for proposal in body["proposals"]] == [1, 2]
    assert {proposal["status"] for proposal in body["proposals"]} == {"provisional"}

    still_empty = api_client.get("/api/tasks", params={"state": "inbox"})
    assert still_empty.json()["counts_by_state"]["inbox"] == 0


def test_mixed_language_final_segment_grows_each_semantic_preview_clause(
    api_client,
) -> None:
    operation = _start_operation(api_client, key="start-mixed-preview-clauses")

    appended = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-mixed-preview-clauses"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": (
                        "Сделать production smoke. написать Наташе. "
                        "купить хлеб и молоко. удалить черновик. "
                        "Починить brain body"
                    ),
                    "stability": "stable",
                }
            ]
        },
    )

    assert appended.status_code == 200, appended.text
    assert [
        proposal["title"]
        for proposal in appended.json()["proposals"]
        if not proposal["deleted"]
    ] == [
        "Сделать production smoke",
        "Написать Наташе",
        "Купить хлеб и молоко",
        "Удалить черновик",
        "Починить brain body",
    ]


@pytest.mark.parametrize(
    ("transcript", "expected_titles"),
    [
        (
            "Починить brain body потом позвонить маме",
            ["Починить brain body", "Позвонить маме"],
        ),
        (
            "Fix brain body then call mom",
            ["Fix brain body", "Call mom"],
        ),
    ],
)
def test_final_segment_splits_preview_on_explicit_clause_boundaries(
    api_client,
    transcript: str,
    expected_titles: list[str],
) -> None:
    boundary_case = hashlib.sha256(transcript.encode()).hexdigest()[:8]
    operation = _start_operation(api_client, key=f"start-boundary-{boundary_case}")

    appended = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": f"append-boundary-{boundary_case}"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": transcript,
                    "stability": "stable",
                }
            ]
        },
    )

    assert appended.status_code == 200, appended.text
    assert [proposal["title"] for proposal in appended.json()["proposals"]] == (
        expected_titles
    )


def test_accurate_reconciliation_preserves_unmatched_locked_and_deleted_proposals(
    api_client,
) -> None:
    operation = _start_operation(
        api_client,
        key="start-preserve-preview-choices",
        external_processing_allowed=True,
    )
    preview = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-preserve-preview-choices"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": (
                        "Сделать production smoke. написать Наташе. "
                        "купить хлеб и молоко. удалить черновик. "
                        "Починить brain body"
                    ),
                    "stability": "stable",
                }
            ]
        },
    )
    assert preview.status_code == 200, preview.text
    bread = next(
        proposal
        for proposal in preview.json()["proposals"]
        if "хлеб" in proposal["title"].casefold()
    )
    disposable = next(
        proposal
        for proposal in preview.json()["proposals"]
        if "черновик" in proposal["title"].casefold()
    )
    edited_title = "SMOKE Купить хлеб и молоко"

    edited = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{bread['id']}",
        headers={"Idempotency-Key": "edit-preserved-bread"},
        json={
            "title": edited_title,
            "expected_revision": preview.json()["revision"],
        },
    )
    assert edited.status_code == 200, edited.text
    deleted = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{disposable['id']}",
        headers={"Idempotency-Key": "delete-preserved-draft"},
        json={"deleted": True, "expected_revision": edited.json()["revision"]},
    )
    assert deleted.status_code == 200, deleted.text

    audio = (
        "Надо починить BrainBuddy, потом сделать production smoke и написать Наташе"
    ).encode()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-preserved-preview-choices"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )

    assert sealed.status_code == 200, sealed.text
    sealed = _advance_persisted_provider_runs(api_client, str(operation["id"]))
    proposals = sealed.json()["proposals"]
    active_titles = [
        proposal["title"] for proposal in proposals if not proposal["deleted"]
    ]
    # The stale preview proposal ("Починить brain body") is superseded by a
    # freshly reconciled "Починить BrainBuddy" but a provider-driven removal
    # must stay visible and individually confirmed rather than silently
    # disappearing (exact-head review item 1): it remains present as an open
    # "removal" conflict instead of being tombstoned outright.
    assert active_titles == [
        "Сделать production smoke",
        "Написать Наташе",
        edited_title,
        "Починить brain body",
        "Починить BrainBuddy",
    ]
    edited_after = next(proposal for proposal in proposals if proposal["id"] == bread["id"])
    deleted_after = next(
        proposal for proposal in proposals if proposal["id"] == disposable["id"]
    )
    stale_preview_after = next(
        proposal
        for proposal in proposals
        if proposal["title"] == "Починить brain body"
    )
    assert edited_after["title"] == edited_title
    assert edited_after["locked_fields"] == ["title"]
    assert edited_after["user_edited"] is True
    assert deleted_after["deleted"] is True
    assert stale_preview_after["deleted"] is False
    assert stale_preview_after["conflicts"][0]["field"] == "removal"
    assert stale_preview_after["conflicts"][0]["suggested_value"] == "removed"


def test_brain_dump_cumulative_final_replaces_interim_words(api_client) -> None:
    operation = _start_operation(api_client, key="start-cumulative-final-operation")

    interim = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-cumulative-interim"},
        json={
            "segments": [
                {"sequence": 1, "text": "buy oat milk", "stability": "interim"}
            ]
        },
    )
    assert interim.status_code == 200, interim.text
    assert [proposal["title"] for proposal in interim.json()["proposals"]] == [
        "Buy oat milk"
    ]
    assert interim.json()["proposals"][0]["status"] == "wording_changing"

    final = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-cumulative-final"},
        json={
            "segments": [
                {
                    "sequence": 2,
                    "text": "buy oat milk. call dentist",
                    "stability": "stable",
                }
            ]
        },
    )
    assert final.status_code == 200, final.text
    assert [proposal["title"] for proposal in final.json()["proposals"]] == [
        "Buy oat milk",
        "Call dentist",
    ]
    assert "Buy oat milk buy oat milk" not in {
        proposal["title"] for proposal in final.json()["proposals"]
    }


def test_brain_dump_same_sequence_interim_can_be_replaced_by_final(api_client) -> None:
    operation = _start_operation(api_client, key="start-replace-interim-operation")

    interim = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-replaceable-interim"},
        json={
            "segments": [
                {"sequence": 1, "text": "buy oat milk", "stability": "interim"}
            ]
        },
    )
    assert interim.status_code == 200, interim.text

    final = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "replace-interim-with-final"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "buy oat milk. call dentist",
                    "stability": "stable",
                }
            ]
        },
    )
    assert final.status_code == 200, final.text
    body = final.json()
    assert [
        (segment["sequence"], segment["text"], segment["stability"])
        for segment in body["segments"]
    ] == [(1, "buy oat milk. call dentist", "stable")]
    assert [proposal["title"] for proposal in body["proposals"]] == [
        "Buy oat milk",
        "Call dentist",
    ]


def test_preview_reconciliation_keeps_opaque_proposal_ids_when_candidate_order_changes(
    api_client,
) -> None:
    operation = _start_operation(api_client, key="start-stable-proposal-identity")
    interim = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-preview-order-interim"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "Email landlord. Email lawyer.",
                    "stability": "interim",
                }
            ]
        },
    )
    assert interim.status_code == 200, interim.text
    ids_by_title = {
        proposal["title"]: proposal["id"] for proposal in interim.json()["proposals"]
    }

    reordered = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "replace-preview-order-final"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "Email lawyer. Email landlord.",
                    "stability": "stable",
                }
            ]
        },
    )
    assert reordered.status_code == 200, reordered.text

    assert {
        proposal["title"]: proposal["id"] for proposal in reordered.json()["proposals"]
    } == ids_by_title


def test_user_edits_survive_later_transcript_reconciliation_and_delete_before_save(
    api_client,
) -> None:
    operation = _start_operation(api_client, key="start-edit-operation")
    append = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-edit-segment"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "Book flights. Call dentist.",
                    "stability": "stable",
                }
            ]
        },
    ).json()
    first_id = append["proposals"][0]["id"]
    second_id = append["proposals"][1]["id"]

    edited = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{first_id}",
        headers={"Idempotency-Key": "edit-first-proposal"},
        json={
            "title": "Book refundable Lisbon flights",
            "expected_revision": append["revision"],
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["proposals"][0]["status"] == "user_edited"

    deleted = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{second_id}",
        headers={"Idempotency-Key": "delete-second-proposal"},
        json={"deleted": True, "expected_revision": edited.json()["revision"]},
    )
    assert deleted.status_code == 200, deleted.text
    assert [
        (patch["operation"], patch["producer"], patch["proposal_id"])
        for patch in deleted.json()["proposal_patches"]
    ] == [
        ("add", "fast", first_id),
        ("add", "fast", second_id),
        ("update", "user", first_id),
        ("remove", "user", second_id),
    ]
    assert deleted.json()["proposal_patches"][2]["locked_fields"] == ["title"]
    repeated_delete = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{second_id}",
        headers={"Idempotency-Key": "delete-second-proposal-again"},
        json={"deleted": True, "expected_revision": deleted.json()["revision"]},
    )
    assert repeated_delete.status_code == 200, repeated_delete.text
    assert repeated_delete.json()["proposal_patches"] == deleted.json()[
        "proposal_patches"
    ]

    later = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-reworded-segment"},
        json={
            "segments": [
                {
                    "sequence": 2,
                    "text": "Book flights to Lisbon. Call dentist to move Monday appointment. Draft launch post.",
                    "stability": "stable",
                }
            ]
        },
    )
    assert later.status_code == 200, later.text
    titles_by_id = {
        proposal["id"]: proposal["title"] for proposal in later.json()["proposals"]
    }
    assert titles_by_id[first_id] == "Book refundable Lisbon flights"
    assert titles_by_id[second_id] == "Call dentist"
    assert any(
        proposal["title"] == "Draft launch post"
        for proposal in later.json()["proposals"]
    )

    sealed = _upload_and_seal(
        api_client,
        operation,
        b"Draft launch post",
        "seal-edit-operation",
    )
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "awaiting_confirmation"

    commit = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-edit-operation"},
        json={"expected_revision": sealed.json()["revision"]},
    )
    assert commit.status_code == 200, commit.text
    committed = commit.json()
    assert committed["status"] == "completed"
    assert committed["committed_task_ids"]

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert [item["title"] for item in inbox["items"]] == [
        "Book refundable Lisbon flights",
        "Draft launch post",
    ]


def test_brain_dump_commit_is_atomic_and_idempotent_on_retry(api_client) -> None:
    operation = _start_operation(api_client, key="start-idempotent-operation")
    api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-idempotent-segment"},
        json={
            "segments": [
                {"sequence": 1, "text": "Pay VAT. Send invoice.", "stability": "stable"}
            ]
        },
    ).json()
    sealed = _upload_and_seal(
        api_client,
        operation,
        b"Pay VAT. Send invoice.",
        "seal-idempotent-operation",
    )
    assert sealed.status_code == 200, sealed.text
    finished = sealed.json()

    headers = {"Idempotency-Key": "commit-idempotent-operation"}
    first = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers=headers,
        json={"expected_revision": finished["revision"]},
    )
    duplicate = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers=headers,
        json={"expected_revision": finished["revision"]},
    )
    assert first.status_code == duplicate.status_code == 200
    assert duplicate.json()["committed_task_ids"] == first.json()["committed_task_ids"]

    retry_with_new_key = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-idempotent-operation-retry"},
        json={"expected_revision": first.json()["revision"]},
    )
    assert retry_with_new_key.status_code == 200
    assert (
        retry_with_new_key.json()["committed_task_ids"]
        == first.json()["committed_task_ids"]
    )

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert inbox["counts_by_state"]["inbox"] == 2
    assert [item["title"] for item in inbox["items"]] == ["Pay VAT", "Send invoice"]


def test_commit_rejects_a_finished_operation_that_was_never_sealed_or_reconciled(
    api_client,
) -> None:
    """``finish`` alone (no seal/accurate-STT/reconciler checkpoint) must never
    let ``commit`` create canonical tasks from bare fast-preview proposals.

    This reproduces the exact-head bypass: append -> finish -> commit with no
    sealed audio and no successful reconciler provider run in between.
    """

    operation = _start_operation(api_client, key="start-unreconciled-finish")
    appended = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-unreconciled-finish"},
        json={
            "segments": [
                {"sequence": 1, "text": "Buy milk.", "stability": "stable"}
            ]
        },
    ).json()
    finished = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/finish",
        headers={"Idempotency-Key": "finish-unreconciled-finish"},
        json={"expected_revision": appended["revision"]},
    ).json()
    assert finished["status"] == "awaiting_confirmation"

    rejected = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-unreconciled-finish"},
        json={"expected_revision": finished["revision"]},
    )
    assert rejected.status_code == 400, rejected.text
    assert "BRAIN_DUMP_NOT_RECONCILED" in rejected.text

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert inbox["counts_by_state"]["inbox"] == 0


def test_commit_rejects_an_untouched_fast_proposal_after_a_successful_reconcile(
    api_client,
) -> None:
    """A successful operation-level reconciler run must not make an untouched
    browser-preview/fast proposal canonical. Only proposals the reconciler (or
    the user) actually affirmed may become tasks; a sibling proposal the
    reconciler never touched stays fast-only and blocks commit until the user
    resolves it, even though the operation as a whole did reconcile."""

    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client, key="start-untouched-fast-sibling", external_processing_allowed=True
    )
    preview = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-untouched-fast-sibling"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "Buy milk. Call dentist.",
                    "stability": "stable",
                }
            ]
        },
    ).json()
    milk_id = preview["proposals"][0]["id"]
    dentist_id = preview["proposals"][1]["id"]
    assert preview["proposals"][1]["title"] == "Call dentist"

    def complete(payload: dict[str, object]) -> dict[str, object]:
        context = json.loads(payload["messages"][1]["content"])  # type: ignore[index]
        segment_id = context["transcript_segments"][0]["id"]
        return {
            "operations": [
                {
                    "operation": "update",
                    "proposal_id": milk_id,
                    "title": "Buy milk",
                    "source_segment_ids": [segment_id],
                    "predecessor_ids": [],
                    "base_revision": None,
                }
            ]
        }

    api_client.app.state.container.voice_brain_dump_service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=complete
    )
    sealed = _upload_and_seal(
        api_client, operation, b"Buy milk", "seal-untouched-fast-sibling"
    )
    assert sealed.status_code == 200, sealed.text
    body = sealed.json()
    assert body["status"] == "awaiting_confirmation"
    by_id = {proposal["id"]: proposal for proposal in body["proposals"]}
    assert by_id[milk_id]["status"] == "reconciled"
    assert by_id[dentist_id]["status"] == "provisional"

    rejected = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-untouched-fast-sibling"},
        json={"expected_revision": body["revision"]},
    )
    assert rejected.status_code == 400, rejected.text
    assert "BRAIN_DUMP_PROPOSAL_NOT_RECONCILED" in rejected.text
    assert dentist_id in rejected.text

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert inbox["counts_by_state"]["inbox"] == 0

    deleted = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{dentist_id}",
        headers={"Idempotency-Key": "delete-untouched-fast-sibling"},
        json={"deleted": True, "expected_revision": body["revision"]},
    )
    assert deleted.status_code == 200, deleted.text

    committed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-after-deleting-untouched-sibling"},
        json={"expected_revision": deleted.json()["revision"]},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["committed_task_ids"]
    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert [item["title"] for item in inbox["items"]] == ["Buy milk"]


def test_withdraw_consent_stops_future_processing_and_purges_raw_audio(
    api_client,
) -> None:
    operation = _start_operation(api_client, key="start-withdraw-consent")
    audio = b"partial-chunk"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text

    withdrawn = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/withdraw_consent",
        headers={"Idempotency-Key": "withdraw-consent-mid-recording"},
        json={"expected_revision": uploaded.json()["revision"]},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    body = withdrawn.json()
    assert body["consent"]["external_processing_allowed"] is False
    assert body["status"] == "recording"
    assert body["audio_chunks"] == []
    assert body["media_ref"] is None

    # Replay with the same idempotency key returns the identical result.
    replayed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/withdraw_consent",
        headers={"Idempotency-Key": "withdraw-consent-mid-recording"},
        json={"expected_revision": uploaded.json()["revision"]},
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == body

    # A stale expected_revision now conflicts.
    stale = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/withdraw_consent",
        headers={"Idempotency-Key": "withdraw-consent-stale"},
        json={"expected_revision": uploaded.json()["revision"]},
    )
    assert stale.status_code == 409, stale.text

    # Every provider check honors mutable current consent: uploads and
    # transcript appends now fail closed even though the operation is still
    # "recording".
    blocked_upload = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/1",
        content=b"more-audio",
        headers={"X-Content-SHA256": hashlib.sha256(b"more-audio").hexdigest()},
    )
    assert blocked_upload.status_code == 400, blocked_upload.text
    assert "CONSENT_REQUIRED" in blocked_upload.text


def test_withdraw_consent_is_not_cancel_and_does_not_discard_a_reconciled_batch(
    api_client,
) -> None:
    """Withdrawal must never be conflated with cancel: an already-reconciled
    batch stays committable even after raw audio is purged by withdrawal."""

    operation = _start_operation(
        api_client, key="start-withdraw-after-reconcile", external_processing_allowed=True
    )
    sealed = _upload_and_seal(
        api_client, operation, b"Buy milk.", "seal-withdraw-after-reconcile"
    )
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "awaiting_confirmation"

    withdrawn = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/withdraw_consent",
        headers={"Idempotency-Key": "withdraw-after-reconcile"},
        json={"expected_revision": sealed.json()["revision"]},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    withdrawn_body = withdrawn.json()
    assert withdrawn_body["status"] == "awaiting_confirmation"
    assert withdrawn_body["audio_chunks"] == []
    assert withdrawn_body["sealed_manifest_hash"] is None

    committed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-after-withdraw"},
        json={"expected_revision": withdrawn_body["revision"]},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["committed_task_ids"]


def test_withdraw_consent_invalidates_an_in_flight_leased_provider_run(
    api_client,
) -> None:
    """Withdrawing consent while a provider run is durably leased must
    invalidate that lease immediately and land in a coherent recovery state,
    rather than silently leaving a phantom "still processing" checkpoint."""

    operation = _start_operation(
        api_client, key="start-withdraw-in-flight", external_processing_allowed=True
    )
    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    persisted = container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    from datetime import timedelta

    from app.utils.time import utcnow
    from app.workflows.voice_brain_dump.domain import BrainDumpProviderRunDocument

    now = utcnow()
    leased = persisted.model_copy(
        update={
            "status": "accurate_transcribing",
            "sealed_manifest_hash": "0" * 64,
            "provider_runs": [
                BrainDumpProviderRunDocument(
                    id="provider_run_in_flight",
                    role="accurate_stt",
                    status="running",
                    input_hash="0" * 64,
                    checkpoint="sealed",
                    attempt=1,
                    recovery_count=0,
                    lease_owner="runner_in_flight",
                    lease_expires_at=now + timedelta(seconds=30),
                    created_at=now,
                    updated_at=now,
                )
            ],
            "revision": persisted.revision + 1,
        }
    )
    container.voice_operation_repo.save_brain_dump_operation(leased)

    withdrawn = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/withdraw_consent",
        headers={"Idempotency-Key": "withdraw-in-flight"},
        json={"expected_revision": leased.revision},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    body = withdrawn.json()
    assert body["status"] == "terminal_error"
    invalidated_run = body["provider_runs"][-1]
    assert invalidated_run["status"] == "terminal_error"
    assert invalidated_run["error_code"] == "CONSENT_WITHDRAWN"


def test_withdraw_consent_rejects_completed_and_cancelled_operations(
    api_client,
) -> None:
    operation = _start_operation(api_client, key="start-withdraw-terminal")
    cancelled = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/cancel",
        headers={"Idempotency-Key": "cancel-before-withdraw"},
        json={"expected_revision": operation["revision"]},
    )
    assert cancelled.status_code == 200, cancelled.text

    rejected = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/withdraw_consent",
        headers={"Idempotency-Key": "withdraw-after-cancel"},
        json={"expected_revision": cancelled.json()["revision"]},
    )
    assert rejected.status_code == 400, rejected.text


def test_brain_dump_pause_resume_cancel_and_owner_scope(
    api_client, second_api_client
) -> None:
    operation = _start_operation(api_client, key="start-resume-operation")
    paused = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/pause",
        headers={"Idempotency-Key": "pause-resume-operation"},
        json={"expected_revision": operation["revision"]},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused"

    resumed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/resume",
        headers={"Idempotency-Key": "resume-operation"},
        json={"expected_revision": paused.json()["revision"]},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["status"] == "recording"

    cancelled = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/cancel",
        headers={"Idempotency-Key": "cancel-operation"},
        json={"expected_revision": resumed.json()["revision"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    client_a, client_b = second_api_client
    private_operation = client_a.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "start-private-operation"},
        json={"consent": {"microphone": True, "external_processing_allowed": False}},
    ).json()
    hidden = client_b.get(f"/api/brain-dump-operations/{private_operation['id']}")
    assert hidden.status_code == 404


def test_schema_v2_upload_seal_runs_accurate_reconciliation_from_original_audio(
    api_client,
) -> None:
    operation = _start_operation(
        api_client, key="start-schema-v2-audio", external_processing_allowed=True
    )
    audio = "Надо починить BrainBuddy, потом сделать production smoke и написать Наташе".encode()
    digest = hashlib.sha256(audio).hexdigest()

    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["media_ref"].startswith("media_")
    assert uploaded.json()["audio_chunks"] == [
        {"chunk_number": 0, "sha256": digest, "size_bytes": len(audio)}
    ]

    duplicate = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )
    assert duplicate.status_code == 200, duplicate.text

    conflict = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=b"different audio",
        headers={"X-Content-SHA256": hashlib.sha256(b"different audio").hexdigest()},
    )
    assert conflict.status_code == 409

    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-schema-v2-audio"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "accurate_transcribing"
    assert sealed.json()["provider_runs"][-1]["status"] == "pending"
    # One bounded runner invocation must immediately re-drive the dependent
    # reconciler stage queued by successful accurate STT. Waiting for the next
    # 60-second sweep would violate the post-stop latency contract.
    service = api_client.app.state.container.voice_brain_dump_service
    assert service.run_due_brain_dump_provider_runs() == 2
    body = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert body["status"] == "awaiting_confirmation"
    assert "fast_processing" in body["status_history"]
    assert {"sealing", "accurate_transcribing", "reconciling", "awaiting_confirmation"} <= set(
        body["status_history"]
    )
    assert body["status_history"][-2:] == ["reconciling", "awaiting_confirmation"]
    assert [proposal["title"] for proposal in body["proposals"]] == [
        "Починить BrainBuddy",
        "Сделать production smoke",
        "Написать Наташе",
    ]
    assert {segment["provider_role"] for segment in body["segments"]} == {"accurate"}
    assert body["segments"][0]["start_ms"] == 0
    assert body["segments"][0]["end_ms"] > 0
    assert body["sealed_manifest_hash"]
    provider_run = body["provider_runs"][0]
    assert provider_run["role"] == "accurate_stt"
    assert provider_run["status"] == "succeeded"
    assert provider_run["checkpoint"] == "accurate_transcribed"
    assert provider_run["attempt"] == 1
    assert provider_run["recovery_count"] == 0
    assert provider_run["error"] is None
    assert provider_run["provider"] == "deterministic"
    assert provider_run["model"] == "deterministic-accurate-v1"
    assert provider_run["estimated_cost_usd"] == 0


def test_schema_v2_accurate_correction_supersedes_fast_preview_without_canonical_write(
    api_client,
) -> None:
    operation = _start_operation(
        api_client, key="start-schema-v2-supersede", external_processing_allowed=True
    )
    preview = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-superseded-preview"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "починить brain body",
                    "stability": "stable",
                }
            ]
        },
    )
    assert preview.status_code == 200, preview.text
    stale = preview.json()["proposals"][0]
    assert preview.json()["proposal_patches"][-1]["operation"] == "add"
    assert preview.json()["proposal_patches"][-1]["producer"] == "fast"
    assert api_client.get("/api/tasks", params={"state": "inbox"}).json()[
        "counts_by_state"
    ]["inbox"] == 0

    audio = "починить BrainBuddy".encode()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-superseded-preview"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 200, sealed.text
    sealed = _advance_persisted_provider_runs(api_client, str(operation["id"]))

    proposals = sealed.json()["proposals"]
    active = [proposal for proposal in proposals if not proposal["deleted"]]
    old = next(proposal for proposal in proposals if proposal["id"] == stale["id"])
    assert [proposal["title"] for proposal in active] == ["Починить BrainBuddy"]
    assert old["successor_ids"] == [active[0]["id"]]
    assert active[0]["predecessor_ids"] == [old["id"]]
    assert sealed.json()["proposal_patches"][-1]["operation"] == "supersede"
    assert sealed.json()["proposal_patches"][-1]["proposal_id"] == active[0]["id"]
    assert api_client.get("/api/tasks", params={"state": "inbox"}).json()[
        "counts_by_state"
    ]["inbox"] == 0


def test_schema_v2_audio_upload_rejects_missing_bad_hash_and_inactive_state(
    api_client,
) -> None:
    operation = _start_operation(api_client, key="start-schema-v2-upload-guards")
    audio = b"buy milk"

    missing_header = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
    )
    assert missing_header.status_code == 400
    assert "X-Content-SHA256" in missing_header.text

    bad_hash = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(b"other").hexdigest()},
    )
    assert bad_hash.status_code == 409
    assert "uploaded audio hash" in bad_hash.text

    cancelled = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/cancel",
        headers={"Idempotency-Key": "cancel-before-upload-retry"},
        json={"expected_revision": operation["revision"]},
    )
    assert cancelled.status_code == 200, cancelled.text

    inactive = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert inactive.status_code == 400
    assert "recording or paused" in inactive.text


def test_schema_v2_seal_rejects_missing_chunks_and_replays_success(api_client) -> None:
    operation = _start_operation(
        api_client,
        key="start-schema-v2-seal-guards",
        external_processing_allowed=True,
    )
    audio = b"buy milk"
    upload = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert upload.status_code == 200, upload.text

    incomplete = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-with-missing-chunk"},
        json={
            "expected_revision": upload.json()["revision"],
            "expected_chunks": 2,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert incomplete.status_code == 400
    assert "missing_chunks" in incomplete.text

    headers = {"Idempotency-Key": "seal-complete-once"}
    payload = {
        "expected_revision": upload.json()["revision"],
        "expected_chunks": 1,
        "manifest_hash": _manifest_hash(audio),
    }
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers=headers,
        json=payload,
    )
    replay = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers=headers,
        json=payload,
    )

    assert sealed.status_code == replay.status_code == 200
    assert replay.json()["id"] == sealed.json()["id"]
    assert replay.json()["revision"] == sealed.json()["revision"]
    assert replay.json()["status"] == "accurate_transcribing"
    completed = _advance_persisted_provider_runs(api_client, str(operation["id"])).json()
    assert completed["status"] == "awaiting_confirmation"

    reseal_inactive = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-after-confirmation-started"},
        json={
            "expected_revision": completed["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert reseal_inactive.status_code == 400
    assert "Only an active brain dump can be sealed" in reseal_inactive.text


def test_schema_v2_seal_rejects_a_manifest_hash_that_is_not_bound_to_uploaded_chunks(
    api_client,
) -> None:
    operation = _start_operation(
        api_client,
        key="start-schema-v2-manifest-integrity",
        external_processing_allowed=True,
    )
    audio = b"buy oat milk"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text

    rejected = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-invalid-manifest"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": "0" * 64,
        },
    )

    assert rejected.status_code == 409
    assert "manifest" in rejected.text.casefold()


def test_schema_v2_seal_requires_the_exact_client_manifest_hash(api_client) -> None:
    operation = _start_operation(
        api_client, key="start-manifest-required", external_processing_allowed=True
    )
    audio = b"manifest-bound audio"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text

    response = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-manifest-required"},
        json={"expected_revision": uploaded.json()["revision"], "expected_chunks": 1},
    )

    assert response.status_code == 422
    assert "manifest_hash" in response.text


def test_schema_v2_seal_rejects_uploaded_chunks_outside_the_exact_manifest(
    api_client,
) -> None:
    operation = _start_operation(
        api_client, key="start-manifest-extra-chunk", external_processing_allowed=True
    )
    first = b"manifest chunk zero"
    second = b"unexpected chunk one"
    revision = operation["revision"]
    for chunk_number, audio in enumerate((first, second)):
        uploaded = api_client.put(
            f"/api/brain-dump-operations/{operation['id']}/audio/{chunk_number}",
            content=audio,
            headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
        )
        assert uploaded.status_code == 200, uploaded.text
        revision = uploaded.json()["revision"]

    response = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-manifest-extra-chunk"},
        json={
            "expected_revision": revision,
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(first),
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["unexpected_chunks"] == [1]


def test_schema_v2_unsupported_operation_command_is_rejected(api_client) -> None:
    operation = _start_operation(api_client, key="start-schema-v2-command-guard")

    unsupported = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/archive",
        headers={"Idempotency-Key": "archive-is-not-a-brain-dump-command"},
        json={"expected_revision": operation["revision"]},
    )

    assert unsupported.status_code == 400
    assert "Unsupported brain dump operation command" in unsupported.text


def test_schema_v2_user_title_lock_blocks_accurate_overwrite_with_visible_conflict(
    api_client,
) -> None:
    operation = _start_operation(
        api_client, key="start-schema-v2-lock", external_processing_allowed=True
    )
    fast = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-fast-brain-body"},
        json={
            "segments": [
                {"sequence": 1, "text": "починить brain body", "stability": "stable"}
            ]
        },
    )
    assert fast.status_code == 200, fast.text
    proposal_id = fast.json()["proposals"][0]["id"]
    edited = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{proposal_id}",
        headers={"Idempotency-Key": "edit-lock-title"},
        json={
            "title": "Починить BrainBuddy MVP",
            "expected_revision": fast.json()["revision"],
        },
    )
    assert edited.status_code == 200, edited.text
    audio = "починить BrainBuddy".encode()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-lock-title"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )

    assert sealed.status_code == 200, sealed.text
    sealed = _advance_persisted_provider_runs(api_client, str(operation["id"]))
    proposal = sealed.json()["proposals"][0]
    assert proposal["id"] == proposal_id
    assert proposal["title"] == "Починить BrainBuddy MVP"
    assert proposal["locked_fields"] == ["title"]
    assert proposal["conflicts"][0]["suggested_value"] == "Починить BrainBuddy"

    blocked_save = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-conflicted-title"},
        json={"expected_revision": sealed.json()["revision"]},
    )
    assert blocked_save.status_code == 400
    assert "conflicts must be reviewed" in blocked_save.text


def test_schema_v2_retryable_provider_failure_recovers_via_retry_command(
    api_client,
) -> None:
    """MUST-2: a retryable accurate-STT failure persists a resumable checkpoint."""

    operation = _start_operation(
        api_client, key="start-schema-v2-retry", external_processing_allowed=True
    )
    audio = b"buy oat milk"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text

    task_service = api_client.app.state.container.voice_brain_dump_service
    original_transcribe = task_service.accurate_stt.transcribe_sealed_audio
    calls = {"count": 0}

    def flaky_transcribe(request):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ProviderRetryableError("simulated transient accurate STT outage")
        return original_transcribe(request)

    task_service.accurate_stt.transcribe_sealed_audio = flaky_transcribe

    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-retry-flaky"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 200, sealed.text
    sealed = _advance_persisted_provider_runs(api_client, str(operation["id"]))
    body = sealed.json()
    assert body["status"] == "retryable_error"
    assert body["provider_runs"][-1]["status"] == "retryable_error"
    assert body["provider_runs"][-1]["checkpoint"] == "sealed"
    assert body["committed_task_ids"] == []

    retried = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/retry",
        headers={"Idempotency-Key": "retry-flaky-once"},
        json={"expected_revision": body["revision"]},
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["provider_runs"][-1]["status"] == "pending"
    retried = _advance_persisted_provider_runs(api_client, str(operation["id"]))
    retried_body = retried.json()
    assert retried_body["status"] == "awaiting_confirmation"
    accurate_run = next(
        run
        for run in reversed(retried_body["provider_runs"])
        if run["role"] == "accurate_stt"
    )
    assert accurate_run["status"] == "succeeded"
    assert accurate_run["recovery_count"] == 1
    assert calls["count"] == 2

    task_service.accurate_stt.transcribe_sealed_audio = original_transcribe


def test_schema_v2_accurate_reconciliation_preserves_opaque_ids_when_order_changes(
    api_client,
) -> None:
    """MUST-3: production accurate-STT reconciliation targets proposals by opaque
    content-derived ID via ``apply_proposal_patches``, never by array position."""

    operation = _start_operation(
        api_client, key="start-schema-v2-lineage", external_processing_allowed=True
    )
    preview = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-lineage-preview"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "Buy oat milk. Call the dentist.",
                    "stability": "stable",
                }
            ]
        },
    )
    assert preview.status_code == 200, preview.text
    ids_by_title = {
        proposal["title"]: proposal["id"] for proposal in preview.json()["proposals"]
    }
    assert set(ids_by_title) == {"Buy oat milk", "Call the dentist"}

    # Accurate audio reports the same two intents in the opposite order; a
    # positional reconciler would silently swap which proposal gets which
    # title. The production path must resolve by content, not position.
    audio = b"Call the dentist. Buy oat milk."
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text

    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-lineage-reordered"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 200, sealed.text
    sealed = _advance_persisted_provider_runs(api_client, str(operation["id"]))
    reconciled_ids_by_title = {
        proposal["title"]: proposal["id"] for proposal in sealed.json()["proposals"]
    }
    assert reconciled_ids_by_title == ids_by_title
    assert all(
        proposal["status"] == "reconciled" for proposal in sealed.json()["proposals"]
    )


def test_schema_v2_accurate_reconciliation_persists_split_lineage(api_client) -> None:
    operation = _start_operation(
        api_client, key="start-schema-v2-split", external_processing_allowed=True
    )
    preview = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-split-preview"},
        json={
            "segments": [
                {
                    "sequence": 1,
                    "text": "Buy oat milk and call the dentist",
                    "stability": "stable",
                }
            ]
        },
    )
    assert preview.status_code == 200, preview.text
    predecessor = preview.json()["proposals"][0]
    audio = b"Buy oat milk. Call the dentist."
    digest = hashlib.sha256(audio).hexdigest()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )
    manifest = hashlib.sha256(
        json.dumps(
            [{"chunk_number": 0, "sha256": digest, "size_bytes": len(audio)}],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-split-lineage"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": manifest,
        },
    )

    assert sealed.status_code == 200, sealed.text
    sealed = _advance_persisted_provider_runs(api_client, str(operation["id"]))
    proposals = sealed.json()["proposals"]
    old = next(item for item in proposals if item["id"] == predecessor["id"])
    children = [item for item in proposals if not item["deleted"]]
    assert old["deleted"] is True
    assert len(children) == 2
    assert old["successor_ids"] == sorted(item["id"] for item in children)
    assert all(item["predecessor_ids"] == [old["id"]] for item in children)
    patch_log = sealed.json()["proposal_patches"]
    assert [patch["sequence"] for patch in patch_log] == list(
        range(1, len(patch_log) + 1)
    )
    assert [patch["operation"] for patch in patch_log[-2:]] == ["split", "split"]
    assert len({patch["id"] for patch in patch_log}) == len(patch_log)


def test_transcript_append_fails_closed_and_persists_nothing_without_external_consent(
    api_client,
) -> None:
    operation = _start_operation(
        api_client,
        key="start-transcript-without-consent",
        external_processing_allowed=False,
    )

    appended = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-transcript-without-consent"},
        json={
            "segments": [
                {"sequence": 1, "text": "never persist this preview", "stability": "stable"}
            ]
        },
    )

    assert appended.status_code == 400, appended.text
    assert "TRANSCRIPT_CONSENT_REQUIRED" in appended.text
    fetched = api_client.get(f"/api/brain-dump-operations/{operation['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["segments"] == []
    assert fetched.json()["proposals"] == []


def test_cancel_deletes_stored_raw_audio_and_clears_media_references(api_client) -> None:
    operation = _start_operation(
        api_client, key="start-cancel-audio-delete", external_processing_allowed=True
    )
    audio = b"private audio that must be deleted"
    digest = hashlib.sha256(audio).hexdigest()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )
    assert uploaded.status_code == 200, uploaded.text

    owner_id = api_client.get("/api/auth/me").json()["id"]
    repository = api_client.app.state.container.voice_operation_repo
    chunk_path = repository.brain_dump_audio_chunk_path(owner_id, operation["id"], 0, digest)
    assert chunk_path.exists()

    cancelled = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/cancel",
        headers={"Idempotency-Key": "cancel-delete-audio"},
        json={"expected_revision": uploaded.json()["revision"]},
    )

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["audio_chunks"] == []
    assert cancelled.json()["media_ref"] is None
    assert not chunk_path.exists()


def test_raw_audio_delete_rejects_an_in_flight_provider_run(api_client) -> None:
    """Privacy deletion cannot race a persisted runner that still needs audio."""

    operation = _start_operation(
        api_client, key="start-in-flight-audio-delete", external_processing_allowed=True
    )
    audio = b"provider still needs this raw audio"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-in-flight-audio-delete"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["provider_runs"][-1]["status"] == "pending"

    rejected = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/delete_raw_audio",
        headers={"Idempotency-Key": "delete-in-flight-audio"},
        json={"expected_revision": sealed.json()["revision"]},
    )

    assert rejected.status_code == 400, rejected.text
    assert "in flight" in rejected.text
    reloaded = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert reloaded["audio_chunks"]
    assert reloaded["media_ref"]


def test_owner_can_delete_reconciled_raw_audio_idempotently(api_client) -> None:
    """The privacy command deletes review-stage audio without losing the batch."""

    operation = _start_operation(
        api_client, key="start-owner-audio-delete", external_processing_allowed=True
    )
    audio = b"owner-requested private audio deletion"
    sealed = _upload_and_seal(
        api_client, operation, audio, "seal-owner-audio-delete"
    ).json()
    assert sealed["status"] == "awaiting_confirmation"
    assert sealed["raw_audio_present"] is True

    owner_id = api_client.get("/api/auth/me").json()["id"]
    repository = api_client.app.state.container.voice_operation_repo
    chunk_path = repository.brain_dump_audio_chunk_path(
        owner_id, operation["id"], 0, hashlib.sha256(audio).hexdigest()
    )
    assert chunk_path.exists()

    deleted = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/delete_raw_audio",
        headers={"Idempotency-Key": "owner-audio-delete"},
        json={"expected_revision": sealed["revision"]},
    )

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "awaiting_confirmation"
    assert deleted.json()["raw_audio_present"] is False
    assert deleted.json()["audio_chunks"] == []
    assert deleted.json()["media_ref"] is None
    assert not chunk_path.exists()

    replay = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/delete_raw_audio",
        headers={"Idempotency-Key": "owner-audio-delete"},
        json={"expected_revision": sealed["revision"]},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["revision"] == deleted.json()["revision"]


def test_raw_audio_sweep_defers_expired_pending_provider_work(api_client) -> None:
    """Retention cannot remove audio that a persisted queued run still needs."""

    operation = _start_operation(
        api_client, key="start-pending-sweep-guard", external_processing_allowed=True
    )
    audio = b"queued provider still needs this audio"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text
    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-pending-sweep-guard"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["provider_runs"][-1]["status"] == "pending"

    container = api_client.app.state.container
    # Periodic workers honour their bounded batch size, and a queued run is
    # not an expired lease eligible for recovery.
    assert container.voice_brain_dump_service.run_due_brain_dump_provider_runs(limit=0) == 0
    assert container.voice_brain_dump_service.recover_due_provider_leases(limit=0) == 0
    assert container.voice_brain_dump_service.recover_due_provider_leases() == 0

    owner_id = api_client.get("/api/auth/me").json()["id"]
    persisted = container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    container.voice_operation_repo.save_brain_dump_operation(
        persisted.model_copy(
            update={"raw_audio_expires_at": persisted.created_at - timedelta(seconds=1)}
        )
    )

    assert container.voice_brain_dump_service.purge_expired_raw_audio() == 0
    reloaded = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert reloaded["raw_audio_present"] is True
    assert reloaded["provider_runs"][-1]["status"] == "pending"


def test_proposal_helpers_keep_empty_preview_and_semantic_match_paths_explicit(
    api_client,
) -> None:
    """Preview extraction and matching retain conservative no-op behavior."""

    from app.workflows.voice_brain_dump.domain import BrainDumpProposalDocument

    service = api_client.app.state.container.voice_brain_dump_service
    now = _start_operation(api_client, key="start-proposal-helper-coverage")["created_at"]
    proposal = BrainDumpProposalDocument(
        id="proposal_helper",
        ordinal=1,
        title="Buy oat milk",
        created_at=now,
        updated_at=now,
    )

    assert service._matching_proposal_index([proposal], "Buy oat milk") == 0
    assert service._matching_proposal_index([proposal], "Call Mum") is None
    assert service._proposals_from_segments([proposal], [], now=now) == [proposal]


def test_raw_audio_retention_sweep_deletes_expired_terminal_media(api_client) -> None:
    operation = _start_operation(
        api_client, key="start-retention-audio-delete", external_processing_allowed=True
    )
    audio = b"expired raw audio"
    digest = hashlib.sha256(audio).hexdigest()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )
    assert uploaded.status_code == 200, uploaded.text

    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]
    persisted = container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    expired = persisted.model_copy(
        update={
            "status": "terminal_error",
            "updated_at": persisted.updated_at - timedelta(days=2),
        }
    )
    container.voice_operation_repo.save_brain_dump_operation(expired)

    assert container.voice_brain_dump_service.purge_expired_raw_audio() == 1
    swept = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert swept["audio_chunks"] == []
    assert swept["media_ref"] is None


def test_raw_audio_retention_sweep_purges_expired_audio_but_preserves_active_review(
    api_client,
) -> None:
    """The reconciliation-anchored privacy deadline applies during Review,
    but transcript/proposal artifacts stay committable after audio is gone."""

    operation = _start_operation(
        api_client,
        key="start-retention-awaiting-confirmation",
        external_processing_allowed=True,
    )
    sealed = _upload_and_seal(
        api_client,
        operation,
        b"Buy milk.",
        "seal-retention-awaiting-confirmation",
    )
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "awaiting_confirmation"

    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]
    persisted = container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    assert persisted.raw_audio_expires_at is not None
    expired = persisted.model_copy(
        update={
            "raw_audio_expires_at": persisted.raw_audio_expires_at - timedelta(days=2)
        }
    )
    container.voice_operation_repo.save_brain_dump_operation(expired)

    assert container.voice_brain_dump_service.purge_expired_raw_audio() == 1
    swept = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert swept["status"] == "awaiting_confirmation"
    assert swept["audio_chunks"] == []
    assert swept["media_ref"] is None
    assert swept["segments"]
    assert swept["proposals"]
    # The reconciled batch stays committable without retaining raw audio.
    committed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-after-retention-sweep"},
        json={"expected_revision": swept["revision"]},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["committed_task_ids"]

    completed_owner_id = api_client.get("/api/auth/me").json()["id"]
    completed_operation = container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=completed_owner_id
    )
    assert completed_operation.status == "completed"
    assert completed_operation.raw_audio_expires_at is not None
    assert completed_operation.raw_audio_expires_at == expired.raw_audio_expires_at
    assert container.voice_brain_dump_service.purge_expired_raw_audio() == 0
    final = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert final["audio_chunks"] == []


def test_raw_audio_expiry_starts_at_reconciliation_and_is_not_extended(
    api_client,
) -> None:
    """Neither a Review edit nor commit extends the reconciliation deadline."""

    operation = _start_operation(
        api_client,
        key="start-raw-audio-not-extended",
        external_processing_allowed=True,
    )
    sealed = _upload_and_seal(
        api_client, operation, b"Buy milk.", "seal-raw-audio-not-extended"
    ).json()
    assert sealed["status"] == "awaiting_confirmation"
    proposal_id = sealed["proposals"][0]["id"]

    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]
    persisted = container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    assert persisted.raw_audio_expires_at is not None
    original_anchor = persisted.raw_audio_expires_at

    # A Review edit must not change the provisional reconciliation timestamp.
    edited = api_client.patch(
        f"/api/brain-dump-operations/{operation['id']}/proposals/{proposal_id}",
        headers={"Idempotency-Key": "edit-before-sweep"},
        json={"title": "Buy oat milk", "expected_revision": sealed["revision"]},
    )
    assert edited.status_code == 200, edited.text
    reloaded = container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    assert reloaded.raw_audio_expires_at == original_anchor
    assert reloaded.updated_at > persisted.updated_at

    committed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-raw-audio-not-extended"},
        json={"expected_revision": edited.json()["revision"]},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["status"] == "completed"
    terminal_anchor = committed.json()["raw_audio_expires_at"]
    assert terminal_anchor == original_anchor.isoformat().replace("+00:00", "Z")

    purged = container.voice_brain_dump_service.purge_expired_raw_audio(
        now=original_anchor + timedelta(seconds=1)
    )
    assert purged == 1
    completed_operation = container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    assert completed_operation.raw_audio_expires_at is not None
    assert container.voice_brain_dump_service.purge_expired_raw_audio() == 0
    swept = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert swept["audio_chunks"] == []
    assert swept["media_ref"] is None


def test_working_artifact_retention_sweep_clears_uncommitted_data_but_not_committed(
    api_client,
) -> None:
    """Exact-head review item 3: working artifacts are only ever eligible
    for retention purge once an operation reaches a terminal status
    (completed/cancelled/terminal_error). An abandoned operation still
    sitting in an active status (here: ``recording``) must never be
    purged no matter how old it looks -- only cancelling it makes its
    uncommitted data eligible. A committed (``completed``) operation's raw
    segments/proposals/patches are purged too, but its compact immutable
    receipts and committed task IDs are not disposable working data and
    must survive the purge."""

    abandoned = _start_operation(api_client, key="start-working-artifact-abandoned")
    appended = api_client.post(
        f"/api/brain-dump-operations/{abandoned['id']}/transcript",
        headers={"Idempotency-Key": "append-working-artifact-abandoned"},
        json={
            "segments": [
                {"sequence": 1, "text": "Buy milk.", "stability": "stable"}
            ]
        },
    )
    assert appended.status_code == 200, appended.text

    committed_source = _start_operation(
        api_client,
        key="start-working-artifact-committed",
        external_processing_allowed=True,
    )
    sealed = _upload_and_seal(
        api_client,
        committed_source,
        b"Buy milk.",
        "seal-working-artifact-committed",
    )
    assert sealed.status_code == 200, sealed.text
    committed = api_client.post(
        f"/api/brain-dump-operations/{committed_source['id']}/commit",
        headers={"Idempotency-Key": "commit-working-artifact-committed"},
        json={"expected_revision": sealed.json()["revision"]},
    )
    assert committed.status_code == 200, committed.text

    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]
    for operation_id in (abandoned["id"], committed_source["id"]):
        persisted = container.voice_brain_dump_service.get_brain_dump_operation(
            operation_id, owner_id=owner_id
        )
        expired = persisted.model_copy(
            update={
                "updated_at": persisted.updated_at - timedelta(days=8),
                "working_artifacts_expires_at": (
                    persisted.updated_at - timedelta(days=1)
                ),
            }
        )
        container.voice_operation_repo.save_brain_dump_operation(expired)

    # The abandoned operation is still "recording" (an active status): even
    # though it looks ancient, it must never be purged.
    still_recording = container.voice_brain_dump_service.get_brain_dump_operation(
        abandoned["id"], owner_id=owner_id
    )
    assert still_recording.status == "recording"
    assert container.voice_brain_dump_service.purge_expired_working_artifacts() == 1

    swept_abandoned = api_client.get(
        f"/api/brain-dump-operations/{abandoned['id']}"
    ).json()
    assert swept_abandoned["segments"] != []

    swept_committed = api_client.get(
        f"/api/brain-dump-operations/{committed_source['id']}"
    ).json()
    assert swept_committed["status"] == "completed"
    assert swept_committed["segments"] == []
    assert swept_committed["proposals"] == []
    assert swept_committed["proposal_patches"] == []
    # Confirmation receipts and committed task IDs are compact, immutable,
    # non-text audit provenance -- not disposable working artifacts. It must
    # remain independently meaningful after every segment/proposal/patch body
    # it once referenced has been purged.
    assert swept_committed["action_receipts"]
    assert swept_committed["committed_task_ids"]
    receipt = swept_committed["action_receipts"][0]
    assert receipt["source_operation_id"] == committed_source["id"]
    assert receipt["source_manifest_hash"] == sealed.json()["sealed_manifest_hash"]
    assert receipt["reconciliation_provider"] == "deterministic"
    assert receipt["reconciliation_run_id"]
    assert receipt["reconciliation_quality"] == "accurate"
    assert receipt["confirmed_title_sha256"] == hashlib.sha256(b"Buy milk").hexdigest()
    assert receipt["proposal_revision"] >= 1
    assert receipt["user_edited"] is False
    assert receipt["confidence"] == "unknown"
    assert receipt["confirmed_by_actor_id"] == owner_id
    assert receipt["decision"] == "create_native_inbox_task"

    # Cancelling the abandoned operation makes its uncommitted data eligible
    # for the same sweep once its own terminal retention window elapses.
    cancelled = api_client.post(
        f"/api/brain-dump-operations/{abandoned['id']}/cancel",
        headers={"Idempotency-Key": "cancel-working-artifact-abandoned"},
        json={"expected_revision": swept_abandoned["revision"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    persisted_cancelled = container.voice_brain_dump_service.get_brain_dump_operation(
        abandoned["id"], owner_id=owner_id
    )
    aged_cancelled = persisted_cancelled.model_copy(
        update={
            "updated_at": persisted_cancelled.updated_at - timedelta(days=8),
            "working_artifacts_expires_at": (
                persisted_cancelled.updated_at - timedelta(days=1)
            ),
        }
    )
    container.voice_operation_repo.save_brain_dump_operation(aged_cancelled)

    assert container.voice_brain_dump_service.purge_expired_working_artifacts() == 1
    swept_cancelled = api_client.get(
        f"/api/brain-dump-operations/{abandoned['id']}"
    ).json()
    assert swept_cancelled["status"] == "cancelled"
    assert swept_cancelled["segments"] == []
    assert swept_cancelled["proposals"] == []
    assert swept_cancelled["proposal_patches"] == []


def test_task_port_is_a_real_adapter_not_the_service_self_adapting(api_client) -> None:
    """ADR-0001 module boundary (exact-head review item 4): the voice
    operation's confirmation command must cross into Tasks through an
    explicit, container-wired TaskPort adapter -- never by the Tasks
    service treating itself as its own port (``task_port or self``)."""

    from app.workflows.voice_brain_dump.task_port import InProcessTaskPort

    container = api_client.app.state.container
    task_service = container.voice_brain_dump_service

    assert isinstance(task_service.task_port, InProcessTaskPort)
    assert task_service.task_port is not task_service

    # The adapter still delegates to the one canonical Tasks command, so a
    # real confirmation flow keeps working end-to-end through the port.
    operation = _start_operation(api_client, key="start-task-port-boundary")
    sealed = _upload_and_seal(
        api_client, operation, b"Buy milk.", "seal-task-port-boundary"
    )
    assert sealed.status_code == 200, sealed.text
    committed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-task-port-boundary"},
        json={"expected_revision": sealed.json()["revision"]},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["committed_task_ids"]


def test_voice_workflow_requires_an_explicit_real_task_port() -> (
    None
):
    """The workflow boundary owns voice orchestration and crosses Tasks via a port."""

    import tempfile
    from pathlib import Path

    from app.modules.tasks import TaskRepository, TaskService
    from app.workflows.voice_brain_dump.repository import OperationRepository
    from app.workflows.voice_brain_dump.service import VoiceBrainDumpService
    from app.workflows.voice_brain_dump.task_port import InProcessTaskPort

    with tempfile.TemporaryDirectory() as data_dir:
        task_service = TaskService(TaskRepository(Path(data_dir)))
        service = VoiceBrainDumpService(
            OperationRepository(Path(data_dir)),
            task_port=InProcessTaskPort(task_service.create_native_inbox_task),
        )
        assert isinstance(service.task_port, InProcessTaskPort)
        assert service.task_port is not task_service


def test_recover_due_provider_leases_resumes_an_expired_in_flight_lease(
    api_client,
) -> None:
    """Item 4: the periodic runner recovers a due/expired lease through the
    same compare-and-set, budget-bounded path a manual retry uses."""

    operation = _start_operation(
        api_client, key="start-lease-sweep", external_processing_allowed=True
    )
    audio = b"Buy milk."
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text

    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]
    persisted = container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=owner_id
    )
    from app.utils.time import utcnow
    from app.workflows.voice_brain_dump.domain import BrainDumpProviderRunDocument

    now = utcnow()
    leased = persisted.model_copy(
        update={
            "status": "accurate_transcribing",
            "media_ref": f"media_{operation['id']}",
            "sealed_manifest_hash": _manifest_hash(audio),
            "provider_runs": [
                BrainDumpProviderRunDocument(
                    id="provider_run_expired_lease",
                    role="accurate_stt",
                    status="running",
                    input_hash=hashlib.sha256(audio).hexdigest(),
                    checkpoint="sealed",
                    attempt=1,
                    recovery_count=0,
                    lease_owner="runner_gone",
                    lease_expires_at=now - timedelta(seconds=5),
                    created_at=now - timedelta(seconds=35),
                    updated_at=now - timedelta(seconds=35),
                )
            ],
            "revision": persisted.revision + 1,
        }
    )
    container.voice_operation_repo.save_brain_dump_operation(leased)

    assert container.voice_brain_dump_service.recover_due_provider_leases() == 1

    _advance_persisted_provider_runs(api_client, str(operation["id"]))

    recovered = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert recovered["status"] == "awaiting_confirmation"
    resumed_run = next(
        run for run in reversed(recovered["provider_runs"]) if run["role"] == "accurate_stt"
    )
    assert resumed_run["status"] == "succeeded"
    assert resumed_run["recovery_count"] == 1

    # A second sweep pass with nothing due recovers nothing.
    assert container.voice_brain_dump_service.recover_due_provider_leases() == 0


def test_commit_does_not_restamp_raw_audio_clock_after_explicit_deletion(
    api_client,
) -> None:
    """Residual gap from the exact-head review of blocker 3: once raw audio
    has been explicitly deleted (``raw_audio_expires_at`` set to the
    deletion instant), a later ``commit`` must never push that clock back
    out to ``now + retention`` for a row that no longer has any audio."""

    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client, key="start-no-restamp", external_processing_allowed=True
    )

    def complete(payload: dict[str, object]) -> dict[str, object]:
        context = json.loads(payload["messages"][1]["content"])  # type: ignore[index]
        segment_id = context["transcript_segments"][0]["id"]
        return {
            "operations": [
                {
                    "operation": "add",
                    "proposal_id": None,
                    "title": "Buy milk",
                    "source_segment_ids": [segment_id],
                    "predecessor_ids": [],
                    "base_revision": None,
                }
            ]
        }

    api_client.app.state.container.voice_brain_dump_service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=complete
    )
    sealed = _upload_and_seal(api_client, operation, b"Buy milk", "seal-no-restamp")
    assert sealed.status_code == 200, sealed.text
    body = sealed.json()
    assert body["status"] == "awaiting_confirmation"

    deleted = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/delete_raw_audio",
        headers={"Idempotency-Key": "delete-raw-audio-no-restamp"},
        json={"expected_revision": body["revision"]},
    )
    assert deleted.status_code == 200, deleted.text
    deleted_body = deleted.json()
    assert deleted_body["raw_audio_present"] is False
    stamped_at_deletion = deleted_body["raw_audio_expires_at"]
    assert stamped_at_deletion is not None

    committed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-no-restamp"},
        json={"expected_revision": deleted_body["revision"]},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["raw_audio_expires_at"] == stamped_at_deletion


def test_active_legacy_preview_only_operation_can_be_committed_provisionally(
    api_client,
) -> None:
    """ADR-0002 "Current implementation migration" rule 3: an active
    schema-v1 operation imported as ``legacy_preview_only`` has no durable
    original audio and can never earn a reconciler success record, but it
    must still be explicitly, visibly commitable as provisional-only --
    otherwise every in-flight pre-migration operation is stuck forever."""

    import sqlite3

    from app.utils.time import utcnow

    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    now = utcnow().isoformat()
    operation_id = "brain_dump_legacy_active_commit"
    payload = {
        "id": operation_id,
        "owner_id": owner_id,
        "kind": "voice_brain_dump",
        "status": "awaiting_confirmation",
        "consent": {
            "microphone": True,
            "external_processing_allowed": False,
            "recorded_at": now,
            "provider": None,
        },
        "segments": [
            {
                "id": "segment_legacy_active",
                "sequence": 1,
                "text": "Buy milk.",
                "stability": "stable",
                "created_at": now,
            }
        ],
        "proposals": [
            {
                "id": "proposal_legacy_active",
                "ordinal": 1,
                "title": "Buy milk",
                "status": "provisional",
                "source_segment_ids": ["segment_legacy_active"],
                "deleted": False,
                "user_edited": False,
                "created_at": now,
                "updated_at": now,
                "revision": 1,
            }
        ],
        "committed_task_ids": [],
        "created_at": now,
        "updated_at": now,
        "schema_version": 1,
        "revision": 3,
    }
    conn = sqlite3.connect(container.voice_operation_repo.db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO brain_dump_operations
                (owner_id, id, status, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (owner_id, operation_id, payload["status"], now, json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()

    fetched = api_client.get(f"/api/brain-dump-operations/{operation_id}")
    assert fetched.status_code == 200, fetched.text
    fetched_body = fetched.json()
    assert fetched_body["reconciliation_quality"] == "provisional_only"

    committed = api_client.post(
        f"/api/brain-dump-operations/{operation_id}/commit",
        headers={"Idempotency-Key": "commit-legacy-active"},
        json={"expected_revision": fetched_body["revision"]},
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["committed_task_ids"]

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert [item["title"] for item in inbox["items"]] == ["Buy milk"]


def test_validation_failure_uses_bounded_retry_then_preserves_proposals_terminally(
    api_client,
) -> None:
    """A semantic ``ValidationFailure`` (the model itself returned an
    invalid/ungrounded operation, not a transport/provider outage) must get
    the same bounded, durable retry budget as a provider outage -- never an
    immediate, unrecoverable dead end -- and once that budget is exhausted
    the outcome must still be user-visible (redacted, allowlisted error
    code) and manual-review-preserving: the operation never silently wipes
    its prior transcript/proposal state."""

    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client,
        key="start-validation-failure-budget",
        external_processing_allowed=True,
    )

    def always_invalid(_payload: dict[str, object]) -> dict[str, object]:
        # Missing the required ``operations`` key -- every attempt fails the
        # same deterministic schema-validation way, modelling a persistent
        # semantic/grounding failure rather than a flaky transport.
        return {}

    service = api_client.app.state.container.voice_brain_dump_service
    assert service.max_operation_recoveries == 2
    service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=always_invalid
    )
    sealed = _upload_and_seal(
        api_client, operation, b"Buy milk.", "seal-validation-failure-budget"
    )
    assert sealed.status_code == 200, sealed.text
    body = sealed.json()
    assert body["status"] == "retryable_error"
    first_run = body["provider_runs"][-1]
    assert first_run["error_code"] == "RECONCILER_VALIDATION_REJECTED"
    assert body["segments"], "checkpoint transcript must survive the failure"

    retried_once = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/retry",
        headers={"Idempotency-Key": "retry-validation-failure-1"},
        json={"expected_revision": body["revision"]},
    )
    assert retried_once.status_code == 200, retried_once.text
    retried_once = _advance_persisted_provider_runs(api_client, str(operation["id"]))
    once_body = retried_once.json()
    assert once_body["status"] == "retryable_error"
    assert once_body["provider_runs"][-1]["error_code"] == (
        "RECONCILER_VALIDATION_REJECTED"
    )

    retried_twice = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/retry",
        headers={"Idempotency-Key": "retry-validation-failure-2"},
        json={"expected_revision": once_body["revision"]},
    )
    assert retried_twice.status_code == 200, retried_twice.text
    final_body = retried_twice.json()
    assert final_body["status"] == "terminal_error"
    assert final_body["provider_runs"][-1]["error_code"] == (
        "OPERATION_RECOVERY_BUDGET_EXHAUSTED"
    )
    # Terminal is a dead end for new confirmation, but it is neither opaque
    # nor destructive: the transcript/proposal state from before the
    # exhausted retry budget remains fully visible for manual inspection,
    # and the operation is visibly flagged ``conflicted`` rather than
    # reading as an ordinary, undifferentiated provider failure.
    assert final_body["segments"]
    assert final_body["reconciliation_quality"] == "conflicted"
    fetched_after_terminal = api_client.get(
        f"/api/brain-dump-operations/{operation['id']}"
    )
    assert fetched_after_terminal.status_code == 200
    assert fetched_after_terminal.json()["status"] == "terminal_error"
    assert fetched_after_terminal.json()["segments"] == final_body["segments"]

    reviewed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/review_provisional",
        headers={"Idempotency-Key": "review-after-validation-exhaustion"},
        json={"expected_revision": final_body["revision"]},
    )
    assert reviewed.status_code == 200, reviewed.text
    reviewed_body = reviewed.json()
    assert reviewed_body["status"] == "awaiting_confirmation"
    assert reviewed_body["reconciliation_quality"] == "provisional_only"


def test_upload_rejects_unsupported_mime_type(api_client) -> None:
    operation = _start_operation(api_client, key="start-bad-mime")
    audio = b"not really audio but plausible bytes"
    response = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={
            "X-Content-SHA256": hashlib.sha256(audio).hexdigest(),
            "Content-Type": "text/plain",
        },
    )
    assert response.status_code == 400, response.text
    assert "AUDIO_CHUNK_MIME_TYPE_UNSUPPORTED" in response.text

    persisted = api_client.app.state.container.voice_brain_dump_service.get_brain_dump_operation(
        operation["id"], owner_id=api_client.get("/api/auth/me").json()["id"]
    )
    assert persisted.audio_chunks == []


def test_upload_rejects_chunk_exceeding_max_chunk_bytes_via_content_length(
    api_client,
) -> None:
    """The Content-Length pre-check refuses an oversized chunk before any
    bytes are streamed into memory."""

    from app.core.config import VoiceAudioLimits

    service = api_client.app.state.container.voice_brain_dump_service
    service.audio_limits = VoiceAudioLimits(max_chunk_bytes=16)

    operation = _start_operation(api_client, key="start-oversized-chunk")
    audio = b"x" * 64
    response = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={
            "X-Content-SHA256": hashlib.sha256(audio).hexdigest(),
            "Content-Length": str(len(audio)),
        },
    )
    assert response.status_code == 400, response.text
    assert "AUDIO_CHUNK_TOO_LARGE" in response.text


def test_upload_rejects_chunk_exceeding_max_chunk_bytes_when_length_understated(
    api_client,
) -> None:
    """Even if a caller lies about (or omits) Content-Length, the bounded
    stream read must still refuse an oversized chunk once actually read."""

    from app.core.config import VoiceAudioLimits

    service = api_client.app.state.container.voice_brain_dump_service
    service.audio_limits = VoiceAudioLimits(max_chunk_bytes=16)

    operation = _start_operation(api_client, key="start-understated-length")
    audio = b"y" * 64
    response = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert response.status_code == 400, response.text
    assert "AUDIO_CHUNK_TOO_LARGE" in response.text


def test_upload_rejects_total_exceeding_max_total_bytes(api_client) -> None:
    from app.core.config import VoiceAudioLimits

    service = api_client.app.state.container.voice_brain_dump_service
    service.audio_limits = VoiceAudioLimits(max_total_bytes=48, max_chunk_bytes=32)

    operation = _start_operation(api_client, key="start-total-bytes-exceeded")
    first = b"a" * 32
    first_response = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=first,
        headers={"X-Content-SHA256": hashlib.sha256(first).hexdigest()},
    )
    assert first_response.status_code == 200, first_response.text

    second = b"b" * 32
    second_response = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/1",
        content=second,
        headers={"X-Content-SHA256": hashlib.sha256(second).hexdigest()},
    )
    assert second_response.status_code == 400, second_response.text
    assert "AUDIO_TOTAL_BYTES_EXCEEDED" in second_response.text


def test_upload_rejects_chunk_count_exceeding_max_chunk_count(api_client) -> None:
    from app.core.config import VoiceAudioLimits

    service = api_client.app.state.container.voice_brain_dump_service
    service.audio_limits = VoiceAudioLimits(max_chunk_count=1)

    operation = _start_operation(api_client, key="start-chunk-count-exceeded")
    first = b"first chunk"
    first_response = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=first,
        headers={"X-Content-SHA256": hashlib.sha256(first).hexdigest()},
    )
    assert first_response.status_code == 200, first_response.text

    second = b"second chunk"
    second_response = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/1",
        content=second,
        headers={"X-Content-SHA256": hashlib.sha256(second).hexdigest()},
    )
    assert second_response.status_code == 400, second_response.text
    assert "AUDIO_CHUNK_COUNT_EXCEEDED" in second_response.text


def test_seal_rejects_audio_exceeding_duration_limit(api_client) -> None:
    """Seal re-checks the whole sealed manifest against the duration cap as
    its own defense-in-depth gate -- distinct from the per-upload check --
    so a manifest assembled under a since-tightened limit is still caught
    before the accurate-STT/reconciler pipeline ever sees it."""

    from app.core.config import VoiceAudioLimits

    service = api_client.app.state.container.voice_brain_dump_service

    operation = _start_operation(api_client, key="start-duration-exceeded")
    audio = b"Buy milk."
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text

    # The operator tightens the duration budget after the chunk was
    # accepted but before seal -- e.g. a config rollout mid-recording.
    service.audio_limits = VoiceAudioLimits(
        max_duration_seconds=1, assumed_chunk_duration_seconds=5
    )

    sealed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-duration-exceeded"},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert sealed.status_code == 400, sealed.text
    assert "AUDIO_DURATION_LIMIT_EXCEEDED" in sealed.text


def test_config_audio_limits_env_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from app.core.config import get_config

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "config-audio-limits"))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_AUDIO_ALLOWED_MIME_TYPES", "audio/wav")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_BYTES", "1024")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_TOTAL_BYTES", "2048")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_COUNT", "3")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_DURATION_SECONDS", "42")
    monkeypatch.setenv(
        "BRAIN_BUDDY_VOICE_AUDIO_ASSUMED_CHUNK_DURATION_SECONDS", "2"
    )
    get_config.cache_clear()
    try:
        limits = get_config().voice.audio_limits
        assert limits.allowed_mime_types == frozenset({"audio/wav"})
        assert limits.max_chunk_bytes == 1024
        assert limits.max_total_bytes == 2048
        assert limits.max_chunk_count == 3
        assert limits.max_duration_seconds == 42
        assert limits.assumed_chunk_duration_seconds == 2
    finally:
        get_config.cache_clear()
