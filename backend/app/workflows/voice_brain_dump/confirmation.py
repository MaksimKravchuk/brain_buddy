"""Application workflow for confirming voice proposals into canonical Tasks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .task_port import TaskPort


@dataclass(frozen=True, slots=True)
class ConfirmedAction:
    """Result of confirming one frozen proposal action into a canonical Task."""

    proposal_id: str
    task_id: str
    child_idempotency_key: str
    source_segment_ids: tuple[str, ...]
    confirmed_at: datetime


def brain_dump_action_child_key(operation_id: str, proposal_id: str) -> str:
    """Deterministic child idempotency key: batch (operation) + action identity.

    Kept stable across freeze, commit, retry, and restart so TaskPort dedupes a
    replayed action to the already-created canonical task instead of creating a
    duplicate -- the property the frozen partial-commit ledger relies on.
    """

    return f"brain_dump_action:{operation_id}:{proposal_id}"


def brain_dump_action_source_ref(operation_id: str, proposal_id: str) -> str:
    """Immutable provenance ref linking a canonical task back to its proposal."""

    return f"brain_dump:{operation_id}:{proposal_id}"


def confirm_native_inbox_action(
    *,
    operation_id: str,
    owner_id: str,
    proposal_id: str,
    title: str,
    source_segment_ids: list[str],
    task_port: TaskPort,
    confirmed_at: datetime,
) -> ConfirmedAction:
    """Confirm ONE frozen proposal action through TaskPort (no repo reach-through).

    Idempotent by the deterministic child key: a retried action returns the
    already-created canonical task rather than duplicating it. Crossing the Tasks
    module boundary happens only through the injected ``TaskPort`` (ADR-0001),
    never by treating a Tasks service instance as its own port.
    """

    child_key = brain_dump_action_child_key(operation_id, proposal_id)
    source_ref = brain_dump_action_source_ref(operation_id, proposal_id)
    task = task_port.create_native_inbox_task(
        owner_id=owner_id,
        title=title,
        source_capture_ids=[source_ref],
        idempotency_key=child_key,
    )
    return ConfirmedAction(
        proposal_id=proposal_id,
        task_id=task.id,
        child_idempotency_key=child_key,
        source_segment_ids=tuple(source_segment_ids),
        confirmed_at=confirmed_at,
    )
