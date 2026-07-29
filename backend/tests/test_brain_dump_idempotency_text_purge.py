"""Item 1: no operation text survives the working-artifact window anywhere.

Voice command idempotency records snapshot the whole operation, transcript and
proposals included -- a plaintext copy that lives outside the operation table and
outside every purge path. When the working-artifact purge clears an operation's
text it must also redact those command snapshots, so an inactive owner cannot
leave plaintext in the voice DB past the retention deadline.
"""

from __future__ import annotations

import json
from datetime import timedelta

from app.schemas.tasks import ExpectedRevisionRequest
from tests.test_brain_dump_commit_ledger import (
    _drive_to_awaiting,
    _inbox_titles,
    _owner_id,
)

_PLAINTEXT = ("Pay VAT", "Send invoice")


def _voice_db_dump(repo, service, owner_id: str, operation_id: str) -> str:
    """Serialize everything the voice DB holds for one operation."""

    operation = service.get_brain_dump_operation(operation_id, owner_id=owner_id)
    records = repo.list_idempotency_for_owner(owner_id=owner_id)
    return json.dumps(
        {
            "operation": operation.model_dump(mode="json"),
            "idempotency": [record.response_body for record in records],
        }
    )


def test_working_artifact_purge_redacts_idempotency_snapshots(api_client) -> None:
    container = api_client.app.state.container
    service = container.voice_brain_dump_service
    repo = container.voice_operation_repo
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "idem-scrub")
    payload = ExpectedRevisionRequest(expected_revision=finished["revision"])
    committed = service.commit_brain_dump_operation(
        operation["id"], payload, owner_id=owner_id, idempotency_key="idem-scrub-commit"
    )
    assert committed.status == "completed"

    # Precondition: the command log holds a plaintext operation snapshot.
    before = json.dumps(
        [r.response_body for r in repo.list_idempotency_for_owner(owner_id=owner_id)]
    )
    assert any(text in before for text in _PLAINTEXT)

    persisted = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    repo.save_brain_dump_operation(
        persisted.model_copy(
            update={
                "working_artifacts_expires_at": persisted.working_artifacts_expires_at
                - timedelta(days=14)
            }
        )
    )
    assert service.purge_expired_working_artifacts() >= 1

    # No transcript/proposal text remains anywhere in the voice DB for this op.
    dump = _voice_db_dump(repo, service, owner_id, operation["id"])
    for text in _PLAINTEXT:
        assert text not in dump

    # Replay after the scrub is coherent: same key + payload returns the
    # text-free completed snapshot and creates no duplicate task.
    replay = service.commit_brain_dump_operation(
        operation["id"], payload, owner_id=owner_id, idempotency_key="idem-scrub-commit"
    )
    assert replay.status == "completed"
    assert replay.committed_task_ids == committed.committed_task_ids
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]
