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


class InProcessTaskPort:
    """Adapter binding the workflow's ``TaskPort`` to the canonical Tasks command.

    Wraps only the one bound Tasks command the port needs, rather than
    handing the whole (much larger) Tasks service object across the module
    boundary as its own adapter -- the source of the ``task_port or self``
    self-adaptation this replaces.
    """

    def __init__(self, create_native_inbox_task: CreateNativeInboxTask) -> None:
        self._create_native_inbox_task = create_native_inbox_task

    def create_native_inbox_task(
        self,
        *,
        owner_id: str,
        title: str,
        source_capture_ids: list[str],
        idempotency_key: str,
    ) -> CreatedTask:
        return self._create_native_inbox_task(
            owner_id=owner_id,
            title=title,
            source_capture_ids=source_capture_ids,
            idempotency_key=idempotency_key,
        )
