"""Commit-saga concurrency + child-identity durability (final0729 review).

The frozen partial-commit ledger (T033) creates each canonical task OUTSIDE the
voice-operation lock. The architecture-consistency review found three ways that
boundary could still mint two tasks for one deterministic child key:

* a concurrent commit request observing the same ``committing`` batch and
  running the same pending actions;
* ``create_native_inbox_task`` writing its idempotency record and its task in
  separate, un-serialized operations, so two racing callers each create a task;
* the generic 24h idempotency retention purging the only dedup record before an
  unresolved ``committing`` batch is ever resumed.

These tests pin the guarantees the fix makes real: exactly one canonical task
per child action under concurrent replay, a consistent ledger, and a coherent
response for every caller -- even across a crash between the two writes or an
idempotency-retention purge.
"""

from __future__ import annotations

import threading
from datetime import timedelta

from app.schemas.tasks import ExpectedRevisionRequest
from app.utils.time import utcnow
from tests.test_brain_dump_commit_ledger import (
    _drive_to_awaiting,
    _inbox_titles,
    _owner_id,
)


class _BarrierTaskPort:
    """Force two commit threads into ``create_native_inbox_task`` together.

    The barrier is tripped BEFORE the wrapped Tasks command acquires its owner
    lock, so both racing callers are inside the create path simultaneously.
    Without owner-serialization both would mint a task for the same child key;
    with it, the second caller serializes behind the first and observes its
    idempotency record instead.
    """

    def __init__(self, inner, *, parties: int) -> None:
        self._inner = inner
        self._barrier = threading.Barrier(parties, timeout=15)

    def create_native_inbox_task(self, **kwargs):
        self._barrier.wait()
        return self._inner.create_native_inbox_task(**kwargs)


class _ReentrantTaskPort:
    """On its first call, run a whole racing commit to completion first.

    This deterministically reproduces the interleaving where one caller freezes
    and enters the batch, a second caller commits the entire batch (creating and
    recording every action, then finalizing), and the first caller only then
    resumes. The first caller must find every action already resolved and apply
    nothing further -- no duplicate task, no ledger re-write on a completed op.
    """

    def __init__(self, inner, racing_commit) -> None:
        self._inner = inner
        self._racing_commit = racing_commit
        self._fired = False

    def create_native_inbox_task(self, **kwargs):
        if not self._fired:
            self._fired = True
            self._racing_commit()
        return self._inner.create_native_inbox_task(**kwargs)


class _PostCreateFaultTaskPort:
    """Create the task for real, then raise -- a crash between the two writes.

    The canonical task (and its idempotency record) are durably committed in the
    Tasks DB, but the voice ledger never records the result, leaving the frozen
    action ``pending``. A later resume must dedupe to the already-created task.
    """

    def __init__(self, inner, *, fail_on_call: int) -> None:
        self._inner = inner
        self._fail_on_call = fail_on_call
        self.calls = 0

    def create_native_inbox_task(self, **kwargs):
        self.calls += 1
        task = self._inner.create_native_inbox_task(**kwargs)
        if self.calls == self._fail_on_call:
            raise RuntimeError("CRASH_AFTER_TASK_CREATE: injected between writes")
        return task


def test_concurrent_commit_creates_exactly_one_task_per_action(api_client) -> None:
    """Two threads committing the same batch mint one task per child action."""

    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "concurrent-commit")

    service.task_port = _BarrierTaskPort(service.task_port, parties=2)
    payload = ExpectedRevisionRequest(expected_revision=finished["revision"])
    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def _commit(tag: str) -> None:
        try:
            results[tag] = service.commit_brain_dump_operation(
                operation["id"],
                payload,
                owner_id=owner_id,
                idempotency_key=f"concurrent-commit-{tag}",
            )
        except BaseException as exc:  # noqa: BLE001 - surfaced via ``errors``
            errors.append(exc)

    threads = [
        threading.Thread(target=_commit, args=("a",)),
        threading.Thread(target=_commit, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    assert not any(thread.is_alive() for thread in threads)
    committed_a = results["a"]
    committed_b = results["b"]
    # Every caller gets a coherent completed response, not a 500 or a partial.
    assert committed_a.status == "completed"
    assert committed_b.status == "completed"
    assert committed_a.committed_task_ids == committed_b.committed_task_ids

    # Exactly one canonical task per frozen action; no duplicate child.
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]

    persisted = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert persisted.commit_batch is not None
    assert [a.status for a in persisted.commit_batch.actions] == [
        "succeeded",
        "succeeded",
    ]
    ledger_task_ids = [a.task_id for a in persisted.commit_batch.actions]
    assert len(set(ledger_task_ids)) == 2
    assert sorted(persisted.committed_task_ids) == sorted(ledger_task_ids)
    assert len(persisted.action_receipts) == 2


def test_racing_commit_completes_batch_without_double_applying(api_client) -> None:
    """A caller that resumes a batch already finished by a racing caller applies
    nothing further: no duplicate task and no ledger re-write on a completed op."""

    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "reentrant-commit")
    payload = ExpectedRevisionRequest(expected_revision=finished["revision"])

    racing: dict[str, object] = {}

    def _racing_commit() -> None:
        racing["b"] = service.commit_brain_dump_operation(
            operation["id"],
            payload,
            owner_id=owner_id,
            idempotency_key="reentrant-commit-b",
        )

    service.task_port = _ReentrantTaskPort(service.task_port, _racing_commit)
    committed_a = service.commit_brain_dump_operation(
        operation["id"],
        payload,
        owner_id=owner_id,
        idempotency_key="reentrant-commit-a",
    )
    committed_b = racing["b"]

    assert committed_a.status == "completed"
    assert committed_b.status == "completed"
    assert committed_a.committed_task_ids == committed_b.committed_task_ids
    assert len(committed_a.committed_task_ids) == 2
    # The loser applied nothing: its view matches the winner's terminal revision
    # exactly (no per-action re-write bumping a completed operation's revision).
    assert committed_a.revision == committed_b.revision
    assert len(committed_a.action_receipts) == 2
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]


def test_crash_between_task_and_ledger_writes_does_not_duplicate(api_client) -> None:
    """A crash after the Tasks write but before the ledger write is deduped on
    resume by the deterministic child key -- exactly one task, not two."""

    service = api_client.app.state.container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "crash-window")

    service.task_port = _PostCreateFaultTaskPort(service.task_port, fail_on_call=1)
    import pytest

    with pytest.raises(RuntimeError, match="CRASH_AFTER_TASK_CREATE"):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key="crash-window-commit",
        )

    partial = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert partial.status == "committing"
    # The task exists in the Tasks DB even though the ledger never recorded it.
    assert len(_inbox_titles(api_client)) == 1

    # Heal the port and resume: the first action must resolve to the SAME task.
    service.task_port = service.task_port._inner
    resumed = service.commit_brain_dump_operation(
        operation["id"],
        ExpectedRevisionRequest(expected_revision=partial.revision),
        owner_id=owner_id,
        idempotency_key="crash-window-resume",
    )
    assert resumed.status == "completed"
    assert len(resumed.committed_task_ids) == 2
    assert len(set(resumed.committed_task_ids)) == 2
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]


def test_child_identity_survives_idempotency_retention_purge(api_client) -> None:
    """The child dedup record outlives the generic 24h idempotency retention, so
    a resume after an incidental purge still creates no duplicate task."""

    container = api_client.app.state.container
    service = container.voice_brain_dump_service
    owner_id = _owner_id(api_client)
    operation, finished = _drive_to_awaiting(api_client, "retention-purge")

    service.task_port = _PostCreateFaultTaskPort(service.task_port, fail_on_call=1)
    import pytest

    with pytest.raises(RuntimeError):
        service.commit_brain_dump_operation(
            operation["id"],
            ExpectedRevisionRequest(expected_revision=finished["revision"]),
            owner_id=owner_id,
            idempotency_key="retention-purge-commit",
        )
    partial = service.get_brain_dump_operation(operation["id"], owner_id=owner_id)
    assert partial.status == "committing"

    # An incidental purge well past the generic retention horizon must NOT drop
    # the unresolved child action's dedup record.
    container.task_repo.purge_expired_idempotency(
        owner_id=owner_id, now=utcnow() + timedelta(hours=48)
    )

    service.task_port = service.task_port._inner
    resumed = service.commit_brain_dump_operation(
        operation["id"],
        ExpectedRevisionRequest(expected_revision=partial.revision),
        owner_id=owner_id,
        idempotency_key="retention-purge-resume",
    )
    assert resumed.status == "completed"
    assert len(set(resumed.committed_task_ids)) == 2
    assert _inbox_titles(api_client) == ["Pay VAT", "Send invoice"]


def test_native_inbox_task_is_idempotent_after_retention_purge(api_client) -> None:
    """Focused Tasks-boundary contract: a workflow-action idempotency record is
    retained across the generic purge, so a replay returns the same task."""

    container = api_client.app.state.container
    task_service = container.task_service
    task_repo = container.task_repo
    owner_id = "owner-native-inbox-retention"

    first = task_service.create_native_inbox_task(
        owner_id=owner_id,
        title="Pay VAT",
        source_capture_ids=["brain_dump:op-xyz:prop-1"],
        idempotency_key="brain_dump_action:op-xyz:prop-1",
    )
    # A purge far beyond the generic retention window keeps the child record.
    task_repo.purge_expired_idempotency(
        owner_id=owner_id, now=utcnow() + timedelta(days=30)
    )
    replay = task_service.create_native_inbox_task(
        owner_id=owner_id,
        title="Pay VAT",
        source_capture_ids=["brain_dump:op-xyz:prop-1"],
        idempotency_key="brain_dump_action:op-xyz:prop-1",
    )
    assert replay.id == first.id
    assert len(task_repo.list_for_owner(owner_id=owner_id)) == 1
