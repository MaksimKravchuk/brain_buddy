"""Item 4: the working-artifact deadline is a hard maximum for committing.

A commit that cannot finish (e.g. a persistently failing Tasks write) must not
keep exact transcript/proposal/title text indefinitely. The recovery driver gets
the whole working-artifact window to complete; past the deadline privacy wins:
the operation is finalized to a terminal state and purged like any other, while
the tasks already created and the ledger identity are preserved.
"""

from __future__ import annotations

import json
from datetime import timedelta

from app.schemas.tasks import ExpectedRevisionRequest
from tests.test_brain_dump_commit_ledger import (
    _drive_to_awaiting,
    _FaultyTaskPort,
    _inbox_titles,
    _owner_id,
)

_PLAINTEXT = ("Pay VAT", "Send invoice")


def _stuck_committing(api_client, key_prefix: str):
    import pytest

    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, key_prefix)

    # Fault the second action and never heal: the operation stays committing
    # with a durable partial ledger (action 1 created, action 2 pending).
    service.task_port = _FaultyTaskPort(service.task_port, fail_on_call=2)
    with pytest.raises(RuntimeError, match="TASKPORT_FAULT"):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key=f"{key_prefix}-commit",
        )
    partial = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert partial.status == "committing"
    return service, owner_id, operation["id"]


def _age_past_deadline(service, owner_id: str, operation_id: str) -> None:
    persisted = service.get_brain_dump_operation(operation_id, owner_id=owner_id)
    anchor = persisted.working_artifacts_expires_at or persisted.updated_at
    service.operation_repo.save_brain_dump_operation(
        persisted.model_copy(
            update={"working_artifacts_expires_at": anchor - timedelta(days=14)}
        )
    )


def test_committing_past_deadline_is_finalized_and_purged(api_client) -> None:
    container = api_client.app.state.container
    service = container.voice_brain_dump_service
    repo = container.voice_operation_repo
    service, owner_id, operation_id = _stuck_committing(api_client, "hard-max")

    # The one already-created task and its id are what must be preserved.
    assert _inbox_titles(api_client) == ["Pay VAT"]
    partial = service.get_brain_dump_operation(operation_id, owner_id=owner_id)
    created_task_id = next(
        a.task_id for a in partial.commit_batch.actions if a.status == "succeeded"
    )

    _age_past_deadline(service, owner_id, operation_id)
    assert service.purge_expired_working_artifacts() >= 1

    finalized = service.get_brain_dump_operation(operation_id, owner_id=owner_id)
    # Finalized to a terminal state, text gone, created task preserved.
    assert finalized.status == "cancelled"
    assert finalized.segments == []
    assert finalized.proposals == []
    assert finalized.committed_task_ids == [created_task_id]
    assert finalized.commit_batch is not None
    for action in finalized.commit_batch.actions:
        assert action.title not in _PLAINTEXT  # reduced to a hash
    # The created canonical task survives in the (separate) Tasks store.
    assert _inbox_titles(api_client) == ["Pay VAT"]

    # No transcript/proposal text anywhere in the voice DB (op + command log).
    records = repo.list_idempotency_for_owner(owner_id=owner_id)
    dump = json.dumps(
        {
            "operation": finalized.model_dump(mode="json"),
            "idempotency": [r.response_body for r in records],
        }
    )
    for text in _PLAINTEXT:
        assert text not in dump

    # Idempotent: a second sweep leaves the finalized operation untouched.
    revision_before = finalized.revision
    service.purge_expired_working_artifacts()
    again = service.get_brain_dump_operation(operation_id, owner_id=owner_id)
    assert again.status == "cancelled"
    assert again.revision == revision_before
