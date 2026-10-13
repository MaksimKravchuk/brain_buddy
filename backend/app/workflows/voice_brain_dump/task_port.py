"""TaskPort: the application-workflow boundary crossed to create canonical Tasks.

Per ADR-0001, AsyncOperation confirmation orchestration belongs at the
application-workflow boundary, not inside the Tasks module; Tasks owns only
canonical persistence and transitions. This module defines that boundary
contract and its in-process adapter so a confirmation command never treats
the Tasks service as its own port by identity (``task_port or self``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class CreatedTask(Protocol):
    """Minimal canonical-task result exposed back to the workflow."""

    id: str


class TaskPort(Protocol):
    """Confirmed voice-operation actions create canonical Tasks records through this port."""

    def create_native_inbox_task(
        self,
        *,
        owner_id: str,
        title: str,
        source_capture_ids: list[str],
        idempotency_key: str,
    ) -> CreatedTask: ...


CreateNativeInboxTask = Callable[..., CreatedTask]
ProposalCheck = Callable[..., object]
"""Shared structural check of a confirmed create action (spec 026 T048).

Called as ``check(title, task_ref=...)`` and raising on a refusal. The Tasks
module owns it (ADR-0001: this workflow never imports ``app.modules.tasks``), so
the composition root injects it.
"""


class InProcessTaskPort:
    """Adapter binding the workflow's ``TaskPort`` to the canonical Tasks command.

    Wraps only the one bound Tasks command the port needs, rather than
    handing the whole (much larger) Tasks service object across the module
    boundary as its own adapter -- the source of the ``task_port or self``
    self-adaptation this replaces.
    """

    def __init__(
        self,
        create_native_inbox_task: CreateNativeInboxTask,
        proposal_check: ProposalCheck | None = None,
    ) -> None:
        self._create_native_inbox_task = create_native_inbox_task
        self._proposal_check = proposal_check

    def create_native_inbox_task(
        self,
        *,
        owner_id: str,
        title: str,
        source_capture_ids: list[str],
        idempotency_key: str,
    ) -> CreatedTask:
        # An AgentRun result is a proposal: the shared core types it against the
        # allow-listed catalog before the ordinary, fenced Task write. The
        # deterministic child key doubles as the proposal's stable reference.
        if self._proposal_check is not None:
            self._proposal_check(title, task_ref=idempotency_key)
        return self._create_native_inbox_task(
            owner_id=owner_id,
            title=title,
            source_capture_ids=source_capture_ids,
            idempotency_key=idempotency_key,
        )
