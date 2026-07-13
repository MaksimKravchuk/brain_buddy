"""HTTP routes for the native GTD task module."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, status

from app.api.dependencies import get_current_user, get_task_service
from app.exceptions import ValidationFailure
from app.schemas.auth import User
from app.schemas.tasks import (
    ContextCreateRequest,
    ContextResponse,
    ProjectCreateRequest,
    ProjectResponse,
    TaskCommentCreateRequest,
    TaskCommentResponse,
    TaskCounts,
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
    TaskState,
    TaskSubtaskCreateRequest,
    TaskSubtaskResponse,
    TaskTransitionRequest,
    TaskUpdateRequest,
)

router = APIRouter(tags=["tasks"])


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise ValidationFailure("Idempotency-Key header is required.")
    return idempotency_key


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> ProjectResponse:
    project = task_service.create_project(
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_project_response(project)


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> list[ProjectResponse]:
    return [
        _to_project_response(project)
        for project in task_service.list_projects(owner_id=current_user.id)
    ]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> ProjectResponse:
    return _to_project_response(task_service.get_project(project_id, owner_id=current_user.id))


@router.post("/contexts", response_model=ContextResponse, status_code=status.HTTP_201_CREATED)
def create_context(
    payload: ContextCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> ContextResponse:
    context = task_service.create_context(
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_context_response(context)


@router.get("/contexts", response_model=list[ContextResponse])
def list_contexts(
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> list[ContextResponse]:
    return [
        _to_context_response(context)
        for context in task_service.list_contexts(owner_id=current_user.id)
    ]


@router.get("/contexts/{context_id}", response_model=ContextResponse)
def get_context(
    context_id: str,
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> ContextResponse:
    return _to_context_response(task_service.get_context(context_id, owner_id=current_user.id))


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> TaskResponse:
    task, subtasks, comments = task_service.get_task_detail(
        task_id, owner_id=current_user.id
    )
    return _to_response(task, subtasks=subtasks, comments=comments)


@router.post(
    "/tasks/{task_id}/subtasks",
    response_model=TaskSubtaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subtask(
    task_id: str,
    payload: TaskSubtaskCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> TaskSubtaskResponse:
    subtask = task_service.create_subtask(
        task_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_subtask_response(subtask)


@router.post(
    "/tasks/{task_id}/comments",
    response_model=TaskCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_comment(
    task_id: str,
    payload: TaskCommentCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> TaskCommentResponse:
    comment = task_service.create_comment(
        task_id,
        payload,
        owner_id=current_user.id,
        actor_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_comment_response(comment)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: str,
    payload: TaskUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> TaskResponse:
    return _to_response(
        task_service.update_task(
            task_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post("/tasks/{task_id}/transitions", response_model=TaskResponse)
def transition_task(
    task_id: str,
    payload: TaskTransitionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> TaskResponse:
    return _to_response(
        task_service.transition_task(
            task_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> TaskResponse:
    return _to_response(
        task_service.create_task(
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.get("/tasks", response_model=TaskListResponse)
def list_tasks(
    state: TaskState | None = None,
    project_id: str | None = None,
    context_id: str | None = None,
    unassigned_project: bool = False,
    include_completed: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    task_service=Depends(get_task_service),
) -> TaskListResponse:
    items, next_cursor, has_more, counts_by_state = task_service.list_tasks(
        owner_id=current_user.id,
        state=state,
        project_id=project_id,
        context_id=context_id,
        unassigned_project=unassigned_project,
        include_completed=include_completed,
        cursor=cursor,
        limit=limit,
    )
    return TaskListResponse(
        items=[_to_response(task) for task in items],
        next_cursor=next_cursor,
        has_more=has_more,
        counts_by_state=TaskCounts(**counts_by_state),
    )


def _to_response(task, *, subtasks=(), comments=()) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        title=task.title,
        details=task.details,
        state=task.state,
        project_id=task.project_id,
        context_ids=task.context_ids,
        due_date=task.due_date,
        waiting_for=task.waiting_for,
        waiting_since=task.waiting_since,
        order_key=task.order_key,
        source_capture_ids=task.source_capture_ids,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        revision=task.revision,
        subtasks=[_to_subtask_response(item) for item in subtasks],
        comments=[_to_comment_response(item) for item in comments],
    )


def _to_project_response(project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        color=project.color,
        state=project.state,
        revision=project.revision,
    )


def _to_context_response(context) -> ContextResponse:
    return ContextResponse(
        id=context.id,
        name=context.name,
        state=context.state,
        revision=context.revision,
    )


def _to_subtask_response(subtask) -> TaskSubtaskResponse:
    return TaskSubtaskResponse(
        id=subtask.id,
        title=subtask.title,
        state=subtask.state,
        order_key=subtask.order_key,
        revision=subtask.revision,
    )


def _to_comment_response(comment) -> TaskCommentResponse:
    return TaskCommentResponse(
        id=comment.id,
        body=comment.body,
        actor_id=comment.actor_id,
        created_at=comment.created_at,
        revision=comment.revision,
    )
