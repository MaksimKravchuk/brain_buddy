"""Cancel racing the phased commit must stop not-yet-started actions.

Cancel is accepted from ``committing`` (ADR-0002 partial-cancel), but the commit
loop iterates a pre-loaded frozen batch. Without a per-action status re-check a
concurrent cancel would not stop remaining TaskPort writes, minting canonical
tasks the owner asked to abandon. These tests pin: a cancel observed mid-batch
stops the remaining actions, the already-created task stays durable and recorded,
the operation settles cancelled-with-partial-ledger, and no later replay
duplicates anything.
"""

from __future__ import annotations

import pytest

from app.exceptions import ConflictError, ValidationFailure
from app.schemas.tasks import ExpectedRevisionRequest
from tests.test_brain_dump_commit_ledger import (
    _drive_to_awaiting,
    _inbox_titles,
    _owner_id,
)


class _CancelDuringCommitPort:
    """Create the first action's task, then cancel the operation before
    returning -- a deterministic cancel interleaved into the commit batch."""

    def __init__(self, inner, *, cancel) -> None:
        self._inner = inner
        self._cancel = cancel
        self._fired = False

    def create_native_inbox_task(self, **kwargs):
        task = self._inner.create_native_inbox_task(**kwargs)
        if not self._fired:
            self._fired = True
            self._cancel()
        return task


def test_cancel_during_commit_stops_remaining_actions(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "cancel-race")

    def _cancel() -> None:
        current = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
        service.transition_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=current.revision),
            owner_id=owner_id,
            idempotency_key="cancel-race-cancel",
            action="cancel",
        )

    service.task_port = _CancelDuringCommitPort(service.task_port, cancel=_cancel)
    result = service.commit_brain_dump_operation(
        operation["id"],
        ExpectedRevisionRequest(expected_revision=finished["revision"]),
        owner_id=owner_id,
        idempotency_key="cancel-race-commit",
    )

    # The commit settles on the cancelled operation, never finalizing it.
    assert result.status == "cancelled"
    persisted = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert persisted.status == "cancelled"

    # Exactly one action ran; its task is durable and recorded, the other action
    # was never started -- a coherent partial ledger.
    assert persisted.commit_batch is not None
    statuses = sorted(a.status for a in persisted.commit_batch.actions)
    assert statuses == ["pending", "succeeded"]
    succeeded = [a for a in persisted.commit_batch.actions if a.status == "succeeded"]
    assert len(succeeded) == 1 and succeeded[0].task_id
    assert _inbox_titles(api_client) == ["Pay VAT"]


def test_replay_after_cancelled_commit_creates_no_duplicate(api_client) -> None:
    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "cancel-race-replay")

    def _cancel() -> None:
        current = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
        service.transition_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=current.revision),
            owner_id=owner_id,
            idempotency_key="cancel-race-replay-cancel",
            action="cancel",
        )

    service.task_port = _CancelDuringCommitPort(service.task_port, cancel=_cancel)
    service.commit_brain_dump_operation(
        operation["id"],
        ExpectedRevisionRequest(expected_revision=finished["revision"]),
        owner_id=owner_id,
        idempotency_key="cancel-race-replay-commit",
    )
    assert _inbox_titles(api_client) == ["Pay VAT"]

    # A later commit attempt against the now-cancelled operation is refused and
    # creates no task -- the child keys and terminal state keep replay safe.
    cancelled = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    with pytest.raises((ValidationFailure, ConflictError)):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=cancelled.revision),
            owner_id=owner_id,
            idempotency_key="cancel-race-replay-again",
        )
    assert _inbox_titles(api_client) == ["Pay VAT"]
