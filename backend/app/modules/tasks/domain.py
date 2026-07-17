"""Canonical records owned by the native task module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import StorageBaseModel

TaskState = Literal["inbox", "next", "waiting", "someday", "completed", "cancelled"]
# "archived" is a legacy-only stored value; the SQLite migration rewrites it to
# "deleted" on load and no code path writes it. Kept for deserialization only.
TagState = Literal["active", "archived", "deleted"]
ProjectState = Literal["active", "archived"]


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


BrainDumpStatus = Literal[
    "recording",
    "paused",
    "awaiting_confirmation",
    "committing",
    "completed",
    "cancelled",
]
BrainDumpProposalStatus = Literal[
    "provisional",
    "wording_changing",
    "ready_to_review",
    "user_edited",
]


class BrainDumpConsent(StorageBaseModel):
    microphone: bool
    external_processing_allowed: bool = False
    recorded_at: datetime
    provider: str | None = None


class BrainDumpTranscriptSegmentDocument(StorageBaseModel):
    id: str
    sequence: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=20_000)
    stability: Literal["interim", "stable"]
    created_at: datetime


class BrainDumpProposalDocument(StorageBaseModel):
    id: str
    ordinal: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    status: BrainDumpProposalStatus = "provisional"
    source_segment_ids: list[str] = Field(default_factory=list)
    deleted: bool = False
    user_edited: bool = False
    created_at: datetime
    updated_at: datetime
    revision: int = Field(default=1, ge=1)


class BrainDumpOperationDocument(StorageBaseModel):
    """Operation-private workspace for native voice Brain Dump capture."""

    id: str
    owner_id: str
    kind: Literal["voice_brain_dump"] = "voice_brain_dump"
    status: BrainDumpStatus
    consent: BrainDumpConsent
    segments: list[BrainDumpTranscriptSegmentDocument] = Field(default_factory=list)
    proposals: list[BrainDumpProposalDocument] = Field(default_factory=list)
    committed_task_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)
