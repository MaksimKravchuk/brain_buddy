"""HTTP contracts for the native GTD task module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from .common import StrictBaseModel

TaskState = Literal["inbox", "next", "waiting", "someday", "completed", "cancelled"]
OpenTaskState = Literal["inbox", "next", "waiting", "someday"]


class ProjectCreateRequest(StrictBaseModel):
    name: str = Field(min_length=1, max_length=500)
    color: str | None = Field(default=None, max_length=64)


class ContextCreateRequest(StrictBaseModel):
    name: str = Field(min_length=1, max_length=500)


class ProjectResponse(StrictBaseModel):
    id: str
    name: str
    color: str | None = None
    state: Literal["active", "completed", "archived"]
    revision: int


class ContextResponse(StrictBaseModel):
    id: str
    name: str
    state: Literal["active", "archived"]
    revision: int


class TaskCreateRequest(StrictBaseModel):
    """Create a task in one of the supported GTD lists."""

    title: str = Field(min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=20_000)
    state: OpenTaskState = "inbox"
    project_id: str | None = None
    context_ids: list[str] = Field(default_factory=list)
    due_date: date | None = None
    waiting_for: str | None = Field(default=None, max_length=500)
    source_capture_ids: list[str] = Field(default_factory=list)


class TaskUpdateRequest(StrictBaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=20_000)
    project_id: str | None = None
    context_ids: list[str] | None = None
    due_date: date | None = None
    expected_revision: int = Field(ge=1)


class TaskTransitionRequest(StrictBaseModel):
    action: Literal["move", "complete", "reopen", "cancel"]
    to_state: OpenTaskState | None = None
    waiting_for: str | None = Field(default=None, max_length=500)
    expected_revision: int = Field(ge=1)


class TaskSubtaskCreateRequest(StrictBaseModel):
    title: str = Field(min_length=1, max_length=500)


class TaskCommentCreateRequest(StrictBaseModel):
    body: str = Field(min_length=1, max_length=20_000)


class TaskSubtaskResponse(StrictBaseModel):
    id: str
    title: str
    state: Literal["open", "completed", "cancelled"]
    order_key: int
    revision: int


class TaskCommentResponse(StrictBaseModel):
    id: str
    body: str
    actor_id: str
    created_at: datetime
    revision: int


class TaskResponse(StrictBaseModel):
    """Public task projection returned by task endpoints."""

    id: str
    title: str
    details: str | None = None
    state: TaskState
    project_id: str | None = None
    context_ids: list[str] = Field(default_factory=list)
    due_date: date | None = None
    waiting_for: str | None = None
    waiting_since: datetime | None = None
    order_key: int
    source_capture_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    revision: int
    subtasks: list[TaskSubtaskResponse] = Field(default_factory=list)
    comments: list[TaskCommentResponse] = Field(default_factory=list)


class TaskCounts(StrictBaseModel):
    inbox: int = Field(ge=0)
    next: int = Field(ge=0)
    waiting: int = Field(ge=0)
    someday: int = Field(ge=0)


class TaskListResponse(StrictBaseModel):
    items: list[TaskResponse] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool
    counts_by_state: TaskCounts
