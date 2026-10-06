"""The public task document → ``TaskResponse`` mapping (spec 020, http §2).

Shared by the task router and the review routers, so no router imports another
router's private symbol (c2 AC-04). The formulation projection is passed in:
``TaskService.formulation_views`` computes it with one settings read per
request.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.modules.tasks.domain import (
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)
from app.modules.tasks.review_domain import FormulationView
from app.schemas.tasks import (
    TaskCommentResponse,
    TaskFormulationResponse,
    TaskParkResponse,
    TaskResponse,
    TaskSubtaskResponse,
)


def subtask_response(subtask: TaskSubtaskDocument) -> TaskSubtaskResponse:
    return TaskSubtaskResponse(
        id=subtask.id,
        title=subtask.title,
        state=subtask.state,
        order_key=subtask.order_key,
        revision=subtask.revision,
    )


def comment_response(comment: TaskCommentDocument) -> TaskCommentResponse:
    return TaskCommentResponse(
        id=comment.id,
        body=comment.body,
        actor_id=comment.actor_id,
        created_at=comment.created_at,
        edited_at=comment.edited_at,
        revision=comment.revision,
    )


def formulation_response(
    view: FormulationView | None,
) -> TaskFormulationResponse | None:
    if view is None:
        return None
    return TaskFormulationResponse(
        id=view.id,
        started_at=view.started_at,
        extended_at=view.extended_at,
        extension_reason=view.extension_reason,
        park_floor_at=view.park_floor_at,
        consecutive_stalled=view.consecutive_stalled,
        ageing_at=view.ageing_at,
        ask_at=view.ask_at,
        park_due_at=view.park_due_at,
        paused_until=view.paused_until,
    )


def task_response(
    task: TaskDocument,
    *,
    subtasks: Sequence[TaskSubtaskDocument] = (),
    comments: Sequence[TaskCommentDocument] = (),
    formulation: FormulationView | None = None,
) -> TaskResponse:
    """Map one task document; ``parked.clock_before`` stays server-side."""

    parked = task.parked
    return TaskResponse(
        id=task.id,
        title=task.title,
        details=task.details,
        state=task.state,
        project_id=task.project_id,
        tag_ids=task.tag_ids,
        due_date=task.due_date,
        priority=task.priority,
        waiting_for=task.waiting_for,
        waiting_since=task.waiting_since,
        order_key=task.order_key,
        source_capture_ids=task.source_capture_ids,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        cancelled_at=task.cancelled_at,
        revision=task.revision,
        subtasks=[subtask_response(item) for item in subtasks],
        comments=[comment_response(item) for item in comments],
        formulation=formulation_response(formulation),
        parked=(
            None
            if parked is None or task.state != "someday"
            else TaskParkResponse(at=parked.at, formulation_id=parked.formulation_id)
        ),
    )


__all__ = [
    "comment_response",
    "formulation_response",
    "subtask_response",
    "task_response",
]
