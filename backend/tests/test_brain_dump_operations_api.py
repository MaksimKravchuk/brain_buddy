"""API tests for native voice Brain Dump operations."""

from __future__ import annotations

import hashlib
import json

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
    external_processing_allowed: bool = False,
):
    response = api_client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": key},
        json={
            "consent": {
                "microphone": True,
                "external_processing_allowed": external_processing_allowed,
                "provider": "openai" if external_processing_allowed else None,
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


def _upload_and_seal(api_client, operation: dict[str, object], audio: bytes, key: str):
    digest = hashlib.sha256(audio).hexdigest()
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": digest},
    )
    assert uploaded.status_code == 200, uploaded.text
    return api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": key},
        json={
            "expected_revision": uploaded.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )


def test_seal_uses_semantic_reconciler_when_external_processing_is_allowed(
    api_client,
) -> None:
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client,
        key="start-semantic-reconciler",
        external_processing_allowed=True,
    )

    def complete(payload: dict[str, object]) -> dict[str, object]:
        context = json.loads(payload["messages"][1]["content"])  # type: ignore[index]
        segment_id = context["transcript_segments"][0]["id"]
        return {
            "operations": [
                {
                    "operation": "add",
                    "proposal_id": None,
                    "title": "Заказать новый загранпаспорт",
                    "source_segment_ids": [segment_id],
                    "predecessor_ids": [],
                    "base_revision": None,
                }
            ]
        }

    api_client.app.state.container.task_service.text_reconciler = OpenAITextReconciler(
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
        "Заказать новый загранпаспорт"
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
                    "source_segment_ids": [],
                    "predecessor_ids": [],
                    "base_revision": second["revision"],
                },
            ]
        }

    api_client.app.state.container.task_service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=complete
    )
    sealed = _upload_and_seal(
        api_client, operation, "Починить BrainBuddy".encode(), "seal-update-remove"
    )

    assert sealed.status_code == 200, sealed.text
    by_id = {proposal["id"]: proposal for proposal in sealed.json()["proposals"]}
    assert by_id[first["id"]]["title"] == "Починить BrainBuddy"
    assert by_id[first["id"]]["status"] == "reconciled"
    assert by_id[second["id"]]["deleted"] is True


@pytest.mark.parametrize(
    ("provider_error", "expected_status"),
    [
        (ProviderRetryableError("temporary outage"), "retryable_error"),
        (ProviderTerminalError("provider rejected"), "terminal_error"),
        (ValidationFailure("invalid model output"), "terminal_error"),
    ],
)
def test_seal_persists_semantic_reconciler_failures_for_recovery(
    api_client, provider_error: Exception, expected_status: str
) -> None:
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(
        api_client,
        key=f"start-semantic-failure-{type(provider_error).__name__}",
        external_processing_allowed=True,
    )

    def fail(_payload: dict[str, object]) -> dict[str, object]:
        raise provider_error

    service = api_client.app.state.container.task_service
    service.text_reconciler = OpenAITextReconciler(api_key="test-key", complete=fail)
    sealed = _upload_and_seal(
        api_client, operation, b"provider failure recovery", "seal-semantic-failure"
    )

    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == expected_status
    assert sealed.json()["provider_runs"][-1]["role"] == "reconciler"
    assert sealed.json()["provider_runs"][-1]["status"] == expected_status


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
    assert "no title conflict to resolve" in response.text


def test_seal_rejects_external_reconciliation_without_explicit_consent(
    api_client,
) -> None:
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    operation = _start_operation(api_client, key="start-reconciler-without-consent")
    api_client.app.state.container.task_service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=lambda _payload: {"operations": []}
    )
    sealed = _upload_and_seal(
        api_client, operation, b"no external consent", "seal-without-consent"
    )

    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["status"] == "terminal_error"
    assert sealed.json()["provider_runs"][-1]["error"] == (
        "RECONCILER_CONSENT_REQUIRED"
    )


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

    api_client.app.state.container.task_service.text_reconciler = OpenAITextReconciler(
        api_key="test-key", complete=complete
    )
    sealed = _upload_and_seal(
        api_client, edited, "Починить BrainBuddy".encode(), f"seal-conflict-{resolution}"
    ).json()
    conflicted = sealed["proposals"][0]
    assert conflicted["conflicts"][0]["suggested_value"] == "Починить BrainBuddy"

    if resolution == "accept":
        service = api_client.app.state.container.task_service
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
        api_client.app.state.container.task_repo.save_brain_dump_operation(
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
        api_client.app.state.container.task_repo.save_brain_dump_operation(persisted)

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

    api_client.app.state.container.task_service.accurate_stt = _real_adapter(
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

    api_client.app.state.container.task_service.accurate_stt = _real_adapter(
        httpx.MockTransport(handler)
    )
    operation = _start_operation(api_client, key="start-no-external-consent")

    sealed = _upload_and_seal(
        api_client, operation, b"\x1aE\xdf\xa3private-webm", "seal-no-consent"
    )

    assert sealed.status_code == 200, sealed.text
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

    api_client.app.state.container.task_service.accurate_stt = OpenAiAccurateStt(
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

    sealed = _upload_and_seal(
        api_client, response.json(), b"audio", "seal-provider-mismatch"
    )

    assert calls == 0
    assert sealed.json()["status"] == "terminal_error"
    assert sealed.json()["provider_runs"][-1]["error_code"] == (
        "STT_CONSENT_PROVIDER_MISMATCH"
    )


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
    operation = _start_operation(api_client, key="start-preserve-preview-choices")
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
    proposals = sealed.json()["proposals"]
    active_titles = [
        proposal["title"] for proposal in proposals if not proposal["deleted"]
    ]
    assert active_titles == [
        "Сделать production smoke",
        "Написать Наташе",
        edited_title,
        "Починить BrainBuddy",
    ]
    edited_after = next(proposal for proposal in proposals if proposal["id"] == bread["id"])
    deleted_after = next(
        proposal for proposal in proposals if proposal["id"] == disposable["id"]
    )
    assert edited_after["title"] == edited_title
    assert edited_after["locked_fields"] == ["title"]
    assert edited_after["user_edited"] is True
    assert deleted_after["deleted"] is True


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

    finish = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/finish",
        headers={"Idempotency-Key": "finish-edit-operation"},
        json={"expected_revision": later.json()["revision"]},
    )
    assert finish.status_code == 200, finish.text
    assert finish.json()["status"] == "awaiting_confirmation"

    commit = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-edit-operation"},
        json={"expected_revision": finish.json()["revision"]},
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
    appended = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/transcript",
        headers={"Idempotency-Key": "append-idempotent-segment"},
        json={
            "segments": [
                {"sequence": 1, "text": "Pay VAT. Send invoice.", "stability": "stable"}
            ]
        },
    ).json()
    finished = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/finish",
        headers={"Idempotency-Key": "finish-idempotent-operation"},
        json={"expected_revision": appended["revision"]},
    ).json()

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
    operation = _start_operation(api_client, key="start-schema-v2-audio")
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
    body = sealed.json()
    assert body["status"] == "awaiting_confirmation"
    assert body["status_history"][-5:] == [
        "sealing",
        "fast_processing",
        "accurate_transcribing",
        "reconciling",
        "awaiting_confirmation",
    ]
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
    operation = _start_operation(api_client, key="start-schema-v2-supersede")
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
    operation = _start_operation(api_client, key="start-schema-v2-seal-guards")
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
    assert replay.json()["status"] == "awaiting_confirmation"

    reseal_inactive = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/seal",
        headers={"Idempotency-Key": "seal-after-confirmation-started"},
        json={
            "expected_revision": sealed.json()["revision"],
            "expected_chunks": 1,
            "manifest_hash": _manifest_hash(audio),
        },
    )
    assert reseal_inactive.status_code == 400
    assert "Only an active brain dump can be sealed" in reseal_inactive.text


def test_schema_v2_seal_rejects_a_manifest_hash_that_is_not_bound_to_uploaded_chunks(
    api_client,
) -> None:
    operation = _start_operation(api_client, key="start-schema-v2-manifest-integrity")
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
    operation = _start_operation(api_client, key="start-manifest-required")
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
    operation = _start_operation(api_client, key="start-manifest-extra-chunk")
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
    operation = _start_operation(api_client, key="start-schema-v2-lock")
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

    operation = _start_operation(api_client, key="start-schema-v2-retry")
    audio = b"buy oat milk"
    uploaded = api_client.put(
        f"/api/brain-dump-operations/{operation['id']}/audio/0",
        content=audio,
        headers={"X-Content-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    assert uploaded.status_code == 200, uploaded.text

    task_service = api_client.app.state.container.task_service
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

    operation = _start_operation(api_client, key="start-schema-v2-lineage")
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
    reconciled_ids_by_title = {
        proposal["title"]: proposal["id"] for proposal in sealed.json()["proposals"]
    }
    assert reconciled_ids_by_title == ids_by_title
    assert all(
        proposal["status"] == "reconciled" for proposal in sealed.json()["proposals"]
    )


def test_schema_v2_accurate_reconciliation_persists_split_lineage(api_client) -> None:
    operation = _start_operation(api_client, key="start-schema-v2-split")
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
