"""T032: consent withdrawal schedules uncommitted derived text for deletion.

Raw-audio deletion on withdrawal already works; the gap the architecture review
found is the *derived* text (working transcript segments + provisional/reconciled
proposals). Withdrawal must set an enforceable deletion deadline for that
uncommitted text and make the operation sweep-eligible without any further user
command, while never touching committed tasks or their compact audit provenance.
"""

from __future__ import annotations

from datetime import timedelta

from app.utils.time import utcnow
from app.workflows.voice_brain_dump.domain import BrainDumpProposalDocument


def _start(api_client, key: str):
    resp = api_client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": key},
        json={
            "consent": {
                "microphone": True,
                "external_processing_allowed": True,
                "provider": "openai",
                "language_hints": [],
                "vocabulary": [],
            }
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _append(api_client, operation_id: str, key: str, text: str):
    resp = api_client.post(
        f"/api/brain-dump-operations/{operation_id}/transcript",
        headers={"Idempotency-Key": key},
        json={"segments": [{"sequence": 1, "text": text, "stability": "stable"}]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _withdraw(api_client, operation_id: str, revision: int, key: str):
    resp = api_client.post(
        f"/api/brain-dump-operations/{operation_id}/withdraw_consent",
        headers={"Idempotency-Key": key},
        json={"expected_revision": revision},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_withdrawal_sets_a_deletion_deadline_and_sweep_purges_derived_text(
    api_client,
) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = api_client.get("/api/auth/me").json()["id"]

    operation = _start(api_client, "withdraw-start")
    appended = _append(
        api_client, operation["id"], "withdraw-append", "Buy milk. Call dentist."
    )
    assert appended["segments"], "precondition: uncommitted transcript exists"
    # Browser preview no longer derives proposals; persist one directly so the
    # sweep is proven to purge derived proposals as well as transcript text.
    persisted = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    api_client.app.state.container.voice_operation_repo.save_brain_dump_operation(
        persisted.model_copy(
            update={
                "proposals": [
                    BrainDumpProposalDocument(
                        id="proposal_withdraw_seed",
                        ordinal=1,
                        title="Buy milk",
                        source_segment_ids=[persisted.segments[0].id],
                        created_at=persisted.updated_at,
                        updated_at=persisted.updated_at,
                    )
                ],
                "revision": persisted.revision + 1,
            }
        )
    )
    appended = api_client.get(f"/api/brain-dump-operations/{operation['id']}").json()
    assert appended["proposals"], "precondition: uncommitted proposals exist"

    withdrawn = _withdraw(
        api_client, operation["id"], appended["revision"], "withdraw-consent"
    )
    assert withdrawn["consent"]["external_processing_allowed"] is False

    persisted = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    # The withdrawal is a persisted cleanup transition: a deletion deadline is
    # set, but the derived text is NOT destroyed synchronously (the owner keeps
    # the retention window to still review/commit already-reconciled work).
    assert persisted.consent_withdrawn_at is not None
    assert persisted.working_artifacts_expires_at is not None
    assert persisted.segments, "derived transcript must survive until the deadline"
    assert persisted.proposals, "derived proposals must survive until the deadline"

    # Before the deadline the sweep is a no-op: nothing is purged early.
    before_deadline = persisted.consent_withdrawn_at + timedelta(seconds=1)
    assert service.purge_expired_working_artifacts(now=before_deadline) == 0
    still_there = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert still_there.segments and still_there.proposals

    # After the configured window the sweep purges the derived text with no
    # further user command, and the status/history reflect the cleanup.
    after_deadline = persisted.working_artifacts_expires_at + timedelta(seconds=1)
    purged = service.purge_expired_working_artifacts(now=after_deadline)
    assert purged >= 1

    swept = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert swept.segments == []
    assert swept.proposals == []
    assert swept.proposal_patches == []
    assert swept.status == "cancelled"
    assert "cancelled" in swept.status_history
    # No task was ever committed, so nothing canonical is affected.
    assert swept.committed_task_ids == []
    assert swept.action_receipts == []


def test_sweep_never_touches_a_committed_operations_receipts_or_tasks(
    api_client,
) -> None:
    """A committed (completed) operation keeps its receipts and canonical tasks
    even after the working-artifact sweep clears its raw transcript/proposals."""

    from tests.test_brain_dump_operations_api import _upload_and_seal

    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = api_client.get("/api/auth/me").json()["id"]

    operation = _start(api_client, "committed-start")
    _append(api_client, operation["id"], "committed-append", "Pay VAT. Send invoice.")
    sealed = _upload_and_seal(
        api_client, operation, b"Pay VAT. Send invoice.", "committed-seal"
    )
    finished = sealed.json()
    committed = api_client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "committed-commit"},
        json={"expected_revision": finished["revision"]},
    ).json()
    assert committed["status"] == "completed"
    task_ids = committed["committed_task_ids"]
    assert task_ids

    persisted = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    far_future = (persisted.working_artifacts_expires_at or utcnow()) + timedelta(
        seconds=1
    )
    service.purge_expired_working_artifacts(now=far_future)

    swept = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    # Raw working text may be gone, but committed provenance is immutable.
    assert swept.status == "completed"
    assert swept.committed_task_ids == task_ids
    assert len(swept.action_receipts) == len(task_ids)
    # The canonical tasks themselves are in a different store and untouched.
    inbox = api_client.get("/api/tasks", params={"state": "inbox"}).json()
    assert inbox["counts_by_state"]["inbox"] == len(task_ids)
