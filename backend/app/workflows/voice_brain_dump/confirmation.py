"""Application workflow for confirming voice proposals into canonical Tasks."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .task_port import TaskPort


class ConfirmableProposal(Protocol):
    id: str
    title: str
    source_segment_ids: list[str]
    deleted: bool


def brain_dump_source_action_key(*, operation_id: str, proposal_id: str) -> str:
    """Permanent ``TaskPort`` dedupe identity for one proposal's confirmation.

    Deliberately independent of any ``ProposalBatch`` ID: canonical confirm's
    own ``H(operation_id, batch_id, action_id)`` key still governs batch-
    scoped attempt/receipt bookkeeping, but the actual idempotency key handed
    to ``TaskPort`` must be the same for the same proposal no matter which
    path confirms it. That is what lets a crash after canonical Task
    persistence but before this operation's own receipt write, followed by
    the deprecated ``/commit`` alias (or a second canonical confirm through a
    new batch after a partial-failure retry), reuse the exact same Task
    instead of creating a duplicate for the same proposal.
    """

    return hashlib.sha256(
        f"brain_dump_source_action:{operation_id}:{proposal_id}".encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfirmedAction:
    """Result of one application-level confirmation command."""

    proposal_id: str
    task_id: str
    child_idempotency_key: str
    source_segment_ids: tuple[str, ...]
    confirmed_at: datetime


def confirm_native_inbox_actions(
    *,
    operation_id: str,
    owner_id: str,
    proposals: Sequence[ConfirmableProposal],
    task_port: TaskPort,
    confirmed_at: datetime,
) -> list[ConfirmedAction]:
    """Confirm visible proposals through TaskPort, without repository reach-through."""

    confirmed: list[ConfirmedAction] = []
    for proposal in proposals:
        if proposal.deleted:
            continue
        child_key = brain_dump_source_action_key(
            operation_id=operation_id, proposal_id=proposal.id
        )
        source_ref = f"brain_dump:{operation_id}:{proposal.id}"
        task = task_port.create_native_inbox_task(
            owner_id=owner_id,
            title=proposal.title,
            source_capture_ids=[source_ref],
            idempotency_key=child_key,
        )
        confirmed.append(
            ConfirmedAction(
                proposal_id=proposal.id,
                task_id=task.id,
                child_idempotency_key=child_key,
                source_segment_ids=tuple(proposal.source_segment_ids),
                confirmed_at=confirmed_at,
            )
        )
    return confirmed
