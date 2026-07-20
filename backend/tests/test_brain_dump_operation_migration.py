"""Legacy v1 migration and deprecated-alias overlap tests (T057).

Covers: completed/cancelled v1 immutability, one-time active-import as
``legacy_preview_only`` preserving IDs/locks/tombstones, the explicit
``review-provisional`` gate guarding freeze/commit, and a canonical-freeze
vs. deprecated-``/commit`` race producing no duplicate Tasks.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.utils.time import utcnow


def _insert_legacy_payload(
    api_client, *, operation_id: str, status: str, schema_version: int = 1
) -> str:
    owner_id = api_client.get("/api/auth/me").json()["id"]
    container = api_client.app.state.container
    now = utcnow().isoformat()
    payload = {
        "id": operation_id,
        "owner_id": owner_id,
        "kind": "voice_brain_dump",
        "status": status,
        "consent": {
            "microphone": True,
            "external_processing_allowed": False,
            "recorded_at": now,
            "provider": None,
        },
        "segments": [
            {
                "id": "segment_a",
                "sequence": 1,
                "text": "Buy milk.",
                "stability": "stable",
                "created_at": now,
            }
        ],
        "proposals": [
            {
                "id": "proposal_locked",
                "ordinal": 1,
                "title": "Buy milk (edited)",
                "status": "provisional",
                "source_segment_ids": ["segment_a"],
                "deleted": False,
                "user_edited": True,
                "created_at": now,
                "updated_at": now,
                "revision": 1,
            },
            {
                "id": "proposal_removed",
                "ordinal": 2,
                "title": "Call the dentist",
                "status": "provisional",
                "source_segment_ids": ["segment_a"],
                "deleted": True,
                "user_edited": False,
                "created_at": now,
                "updated_at": now,
                "revision": 1,
            },
        ],
        "committed_task_ids": [],
        "created_at": now,
        "updated_at": now,
        "schema_version": schema_version,
        "revision": 1,
    }
    conn = sqlite3.connect(container.voice_operation_repo.db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO brain_dump_operations
                (owner_id, id, status, updated_at, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (owner_id, operation_id, status, now, json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()
    return owner_id


def test_completed_legacy_v1_operation_is_immutable_and_never_replayed(
    api_client,
) -> None:
    _insert_legacy_payload(
        api_client, operation_id="brain_dump_legacy_completed", status="completed"
    )

    first = api_client.get("/api/brain-dump-operations/brain_dump_legacy_completed")
    assert first.status_code == 200, first.text
    first_body = first.json()

    # Fetching again must not migrate/mutate the terminal v1 payload:
    # revision and proposal identities stay exactly as stored.
    second = api_client.get("/api/brain-dump-operations/brain_dump_legacy_completed")
    assert second.status_code == 200, second.text
    assert second.json()["revision"] == first_body["revision"]
    assert second.json()["import_mode"] == "native_v2"
    proposal_ids = {p["id"] for p in second.json()["proposals"]}
    assert proposal_ids == {"proposal_locked", "proposal_removed"}


def test_active_legacy_v1_import_preserves_ids_locks_and_tombstones(
    api_client,
) -> None:
    _insert_legacy_payload(
        api_client, operation_id="brain_dump_legacy_active", status="awaiting_confirmation"
    )

    fetched = api_client.get("/api/brain-dump-operations/brain_dump_legacy_active")
    assert fetched.status_code == 200, fetched.text
    body = fetched.json()

    assert body["import_mode"] == "legacy_preview_only"
    assert body["accurate_reconciliation_available"] is False
    assert "provisional_only" in body["operation_warning_codes"]

    by_id = {p["id"]: p for p in body["proposals"]}
    assert set(by_id) == {"proposal_locked", "proposal_removed"}
    assert "title" in by_id["proposal_locked"]["locked_fields"]
    assert by_id["proposal_removed"]["deleted"] is True

    patch_ops = {(p["proposal_id"], p["operation"]) for p in body["proposal_patches"]}
    assert ("proposal_locked", "add") in patch_ops
    assert ("proposal_removed", "add") in patch_ops
    assert ("proposal_removed", "remove") in patch_ops


def test_legacy_import_freeze_requires_explicit_review_provisional_first(
    api_client,
) -> None:
    _insert_legacy_payload(
        api_client, operation_id="brain_dump_legacy_gate", status="awaiting_confirmation"
    )
    fetched = api_client.get("/api/brain-dump-operations/brain_dump_legacy_gate").json()
    assert fetched["committable"] is False

    premature_freeze = api_client.post(
        "/api/brain-dump-operations/brain_dump_legacy_gate/proposal-batches",
        headers={"Idempotency-Key": "freeze-legacy-premature"},
        json={
            "based_on_proposal_revision": fetched["proposal_revision"],
            "expected_operation_revision": fetched["revision"],
            "selected_proposal_ids": ["proposal_locked"],
        },
    )
    assert premature_freeze.status_code == 409, premature_freeze.text

    reviewed = api_client.post(
        "/api/brain-dump-operations/brain_dump_legacy_gate/review_provisional",
        headers={"Idempotency-Key": "review-legacy-gate"},
        json={"expected_revision": fetched["revision"]},
    )
    assert reviewed.status_code == 200, reviewed.text
    reviewed_body = reviewed.json()
    assert reviewed_body["committable"] is True
    assert reviewed_body["provisional_review_accepted_at"] is not None

    frozen = api_client.post(
        "/api/brain-dump-operations/brain_dump_legacy_gate/proposal-batches",
        headers={"Idempotency-Key": "freeze-legacy-after-review"},
        json={
            "based_on_proposal_revision": reviewed_body["proposal_revision"],
            "expected_operation_revision": reviewed_body["revision"],
            "selected_proposal_ids": ["proposal_locked"],
        },
    )
    assert frozen.status_code == 201, frozen.text
    active_batch = frozen.json()["active_proposal_batch"]
    assert active_batch["warnings"] == ["provisional_only"]
    assert all(
        action["warnings"] == ["provisional_only"] for action in active_batch["snapshot"]
    )


@pytest.fixture
def _reconciled_operation(api_client):
    from tests.test_brain_dump_operations_api import _start_operation, _upload_and_seal

    operation = _start_operation(api_client, key="start-migration-race")
    sealed = _upload_and_seal(api_client, operation, b"Buy milk.", "seal-migration-race")
    return sealed.json()


def test_canonical_freeze_then_deprecated_commit_race_creates_no_duplicate_task(
    api_client, _reconciled_operation
) -> None:
    """A canonical freeze followed by the deprecated ``/commit`` alias on the
    same operation must never produce more than one Task for the same
    proposal; the loser observes a conflict rather than a silent duplicate."""

    operation = _reconciled_operation
    proposal_ids = [p["id"] for p in operation["proposals"] if not p["deleted"]]

    frozen = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/proposal-batches",
        headers={"Idempotency-Key": "freeze-race"},
        json={
            "based_on_proposal_revision": operation["proposal_revision"],
            "expected_operation_revision": operation["revision"],
            "selected_proposal_ids": proposal_ids,
        },
    )
    assert frozen.status_code == 201, frozen.text
    frozen_body = frozen.json()
    active_batch = frozen_body["active_proposal_batch"]

    committed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "commit-race"},
        json={"expected_revision": frozen_body["revision"]},
    )
    assert committed.status_code == 200, committed.text
    committed_body = committed.json()
    assert committed_body["status"] == "completed"
    assert len(committed_body["committed_task_ids"]) == len(proposal_ids)

    # The now-stale canonical confirm on the original frozen batch must not
    # create a second Task; it safely conflicts on the stale operation
    # revision instead.
    stale_confirm = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/confirm",
        headers={"Idempotency-Key": "confirm-race-loser"},
        json={
            "proposal_batch_id": active_batch["id"],
            "expected_batch_revision": active_batch["revision"],
            "expected_operation_revision": frozen_body["revision"],
        },
    )
    assert stale_confirm.status_code == 409, stale_confirm.text

    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert len(inbox["items"]) == len(proposal_ids)
