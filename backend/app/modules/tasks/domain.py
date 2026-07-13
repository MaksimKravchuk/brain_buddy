"""Canonical records owned by the native GTD task module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import StorageBaseModel

TaskState = Literal["inbox", "next", "waiting", "someday", "completed", "cancelled"]


class IdempotencyRecord(StorageBaseModel):
    """Persisted result pointer for one owner-scoped mutating command."""

    key: str
    command: str
    request_hash: str
    resource_id: str
    created_at: datetime


class ProjectDocument(StorageBaseModel):
    """An owner-scoped project that may link existing CRT trees by ID."""

    id: str
    owner_id: str
    name: str = Field(min_length=1, max_length=500)
    color: str | None = Field(default=None, max_length=64)
    state: Literal["active", "completed", "archived"] = "active"
    linked_tree_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


class ContextDocument(StorageBaseModel):
    """An owner-scoped GTD context."""

    id: str
    owner_id: str
    name: str = Field(min_length=1, max_length=500)
    state: Literal["active", "archived"] = "active"
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


class TaskSubtaskDocument(StorageBaseModel):
    id: str
    owner_id: str
    task_id: str
    title: str = Field(min_length=1, max_length=500)
    order_key: int = Field(ge=0)
    state: Literal["open", "completed", "cancelled"] = "open"
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


class TaskCommentDocument(StorageBaseModel):
    id: str
    owner_id: str
    task_id: str
    actor_id: str
    body: str = Field(min_length=1, max_length=20_000)
    created_at: datetime
    edited_at: datetime | None = None
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


class TaskDocument(StorageBaseModel):
    """A mutable, owner-scoped GTD task; it is never a CRT node."""

    id: str
    owner_id: str
    title: str = Field(min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=20_000)
    state: TaskState
    project_id: str | None = None
    context_ids: list[str] = Field(default_factory=list)
    due_date: date | None = None
    waiting_for: str | None = Field(default=None, max_length=500)
    waiting_since: datetime | None = None
    order_key: int = Field(ge=0)
    source_capture_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)
