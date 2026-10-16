"""The public task document → ``TaskResponse`` mapping (spec 020, http §2).

Shared by the task router and the review routers, so no router imports another
router's private symbol (c2 AC-04). The formulation projection is passed in:
``TaskService.formulation_views`` computes it with one settings read per
request.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.modules.tasks import TaskService
from app.modules.tasks.domain import (
    FormulationSettingsDocument,
    ProjectDocument,
    SmartAddTaskResultDocument,
    TagDocument,
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)
from app.modules.tasks.review_domain import FormulationView
from app.schemas.tasks import (
    ProjectResponse,
    SmartAddCreatedResponse,
    SmartAddTaskResponse,
    TagResponse,
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


def command_task_response(
    task_service: TaskService,
    owner_id: str,
    task: TaskDocument,
    settings: FormulationSettingsDocument | None,
) -> TaskResponse:
    """A command's task with the projection its stored result was made with.

    ``settings`` is the idempotency record's snapshot, so a same-key replay
    returns the original ``formulation`` (http "Mutations"); ``None`` (a
    record from before the snapshot) projects with the live settings.
    """

    views = task_service.formulation_views(owner_id, [task], settings=settings)
    return task_response(task, formulation=views.get(task.id))


def project_response(
    project: ProjectDocument,
    *,
    task_service: TaskService,
    owner_id: str,
    open_task_count: int | None = None,
) -> ProjectResponse:
    """``open_task_count`` is given by the list route, which counts in one pass."""

    return ProjectResponse(
        id=project.id,
        name=project.name,
        color=project.color,
        state=project.state,
        revision=project.revision,
        open_task_count=(
            open_task_count
            if open_task_count is not None
            else task_service.open_task_count_for_project(project.id, owner_id=owner_id)
        ),
        desired_outcome=project.desired_outcome,
        archived_at=project.archived_at,
        archived_before_lossless=project.archived_before_lossless,
        created_at=project.created_at,
    )


def tag_response(
    tag: TagDocument, *, task_service: TaskService, owner_id: str
) -> TagResponse:
    return TagResponse(
        id=tag.id,
        name=tag.name,
        # Legacy stored rows may still carry "archived"; the public contract
        # only exposes "active" and "deleted".
        state="deleted" if tag.state == "archived" else tag.state,
        revision=tag.revision,
        open_task_count=task_service.open_task_count_for_tag(tag.id, owner_id=owner_id),
        created_at=tag.created_at,
    )


def smart_add_response(
    result: SmartAddTaskResultDocument,
    *,
    task_service: TaskService,
    owner_id: str,
) -> SmartAddTaskResponse:
    return SmartAddTaskResponse(
        task=command_task_response(
            task_service, owner_id, result.task, result.formulation_settings
        ),
        project=(
            project_response(
                result.project, task_service=task_service, owner_id=owner_id
            )
            if result.project
            else None
        ),
        tags=[
            tag_response(tag, task_service=task_service, owner_id=owner_id)
            for tag in result.tags
        ],
        created=SmartAddCreatedResponse(
            project_id=result.created.project_id,
            tag_ids=result.created.tag_ids,
        ),
    )


__all__ = [
    "smart_add_response",
    "command_task_response",
    "project_response",
    "tag_response",
    "comment_response",
    "formulation_response",
    "subtask_response",
    "task_response",
]
