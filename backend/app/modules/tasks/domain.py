"""Canonical records owned by the native task module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import StorageBaseModel

TaskState = Literal["inbox", "next", "waiting", "someday", "completed", "cancelled"]
TagState = Literal["active", "archived", "deleted"]
ProjectState = Literal["active", "completed", "archived"]


class IdempotencyRecord(StorageBaseModel):
    """Persisted result pointer for one owner-scoped mutating command."""

    key: str
    command: str
    request_hash: str
    resource_id: str
    response_body: dict[str, object]
    created_at: datetime


class ProjectDocument(StorageBaseModel):
    """An owner-scoped project; it is deliberately not linked to CRT trees."""

    id: str
    owner_id: str
    name: str = Field(min_length=1, max_length=500)
    normalized_name: str = Field(default="", max_length=500)
    color: str | None = Field(default=None, max_length=64)
    state: ProjectState = "active"
    linked_tree_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


class TagDocument(StorageBaseModel):
    """An owner-scoped first-class task tag."""

    id: str
    owner_id: str
    name: str = Field(min_length=1, max_length=500)
    normalized_name: str = Field(default="", max_length=500)
    state: TagState = "active"
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)


# Compatibility alias for the one-release hidden /contexts migration shim.
ContextDocument = TagDocument


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
    """A mutable, owner-scoped task; it is never a CRT node."""

    id: str
    owner_id: str
    title: str = Field(min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=20_000)
    state: TaskState
    project_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)
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

    @model_validator(mode="before")
    @classmethod
    def migrate_context_ids(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tag_ids" not in data and "context_ids" in data:
            data = {**data, "tag_ids": data.get("context_ids") or []}
        return data

    @property
    def context_ids(self) -> list[str]:
        """Deprecated compatibility accessor for service tests and /contexts shim."""

        return self.tag_ids
