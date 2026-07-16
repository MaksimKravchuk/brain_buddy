"""HTTP contracts for the native task module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from .common import StrictBaseModel

TaskState = Literal["inbox", "next", "waiting", "someday", "completed", "cancelled"]
OpenTaskState = Literal["inbox", "next", "waiting", "someday"]


class ProjectCreateRequest(StrictBaseModel):
    name: str = Field(min_length=1, max_length=500)
    color: str | None = Field(default=None, max_length=64)


class ProjectUpdateRequest(StrictBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    color: str | None = Field(default=None, max_length=64)
    expected_revision: int = Field(ge=1)


class ExpectedRevisionRequest(StrictBaseModel):
    expected_revision: int = Field(ge=1)


class TagCreateRequest(StrictBaseModel):
    name: str = Field(min_length=1, max_length=500)


class TagUpdateRequest(StrictBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    expected_revision: int = Field(ge=1)


# Hidden compatibility shim for deprecated Context terminology.
ContextCreateRequest = TagCreateRequest


class ProjectResponse(StrictBaseModel):
    id: str
    name: str
    color: str | None = None
    state: Literal["active", "completed", "archived"]
    revision: int
    open_task_count: int = Field(default=0, ge=0)


class TagResponse(StrictBaseModel):
    id: str
    name: str
    state: Literal["active", "archived", "deleted"]
    revision: int
    open_task_count: int = Field(default=0, ge=0)


ContextResponse = TagResponse


class TaskCreateRequest(StrictBaseModel):
    """Create a task in one of the supported lists."""

    title: str = Field(min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=20_000)
    state: OpenTaskState = "inbox"
    project_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)
    due_date: date | None = None
    waiting_for: str | None = Field(default=None, max_length=500)
    source_capture_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def accept_context_ids_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tag_ids" not in data and "context_ids" in data:
            data = {**data}
            data["tag_ids"] = data.pop("context_ids") or []
        return data


class TaskUpdateRequest(StrictBaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=20_000)
    project_id: str | None = None
    tag_ids: list[str] | None = None
    due_date: date | None = None
    expected_revision: int = Field(ge=1)

    @model_validator(mode="before")
    @classmethod
    def accept_context_ids_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tag_ids" not in data and "context_ids" in data:
            data = {**data}
            data["tag_ids"] = data.pop("context_ids")
        return data


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
    tag_ids: list[str] = Field(default_factory=list)
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


class BrainDumpConsentRequest(StrictBaseModel):
    microphone: bool
    external_processing_allowed: bool = False
    provider: str | None = Field(default=None, max_length=100)


class BrainDumpOperationStartRequest(StrictBaseModel):
    consent: BrainDumpConsentRequest


class BrainDumpTranscriptSegmentRequest(StrictBaseModel):
    sequence: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=20_000)
    stability: Literal["interim", "stable"] = "stable"


class BrainDumpTranscriptAppendRequest(StrictBaseModel):
    segments: list[BrainDumpTranscriptSegmentRequest] = Field(min_length=1, max_length=50)


class BrainDumpProposalUpdateRequest(StrictBaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    deleted: bool | None = None
    expected_revision: int = Field(ge=1)


class BrainDumpConsentResponse(StrictBaseModel):
    microphone: bool
    external_processing_allowed: bool
    provider: str | None = None
    recorded_at: datetime


class BrainDumpTranscriptSegmentResponse(StrictBaseModel):
    id: str
    sequence: int
    text: str
    stability: Literal["interim", "stable"]
    created_at: datetime


class BrainDumpProposalResponse(StrictBaseModel):
    id: str
    ordinal: int
    title: str
    status: BrainDumpProposalStatus
    source_segment_ids: list[str] = Field(default_factory=list)
    deleted: bool
    user_edited: bool
    revision: int


class BrainDumpOperationResponse(StrictBaseModel):
    id: str
    owner_id: str
    kind: Literal["voice_brain_dump"]
    status: BrainDumpStatus
    consent: BrainDumpConsentResponse
    segments: list[BrainDumpTranscriptSegmentResponse] = Field(default_factory=list)
    proposals: list[BrainDumpProposalResponse] = Field(default_factory=list)
    committed_task_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    revision: int
