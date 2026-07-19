"""Canonical records owned by the native task module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from app.schemas.common import StorageBaseModel

TaskState = Literal["inbox", "next", "waiting", "someday", "completed", "cancelled"]
TaskPriority = Literal["none", "low", "medium", "high"]
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
    priority: TaskPriority = "none"
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


class SmartAddCreatedDocument(StorageBaseModel):
    """Classification records created by one Smart Add command."""

    project_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)


class SmartAddTaskResultDocument(StorageBaseModel):
    """Composite idempotency payload for a Smart Add task command."""

    task: TaskDocument
    project: ProjectDocument | None = None
    tags: list[TagDocument] = Field(default_factory=list)
    created: SmartAddCreatedDocument = Field(default_factory=SmartAddCreatedDocument)


BrainDumpStatus = Literal[
    "recording",
    "paused",
    "sealing",
    "fast_processing",
    "accurate_transcribing",
    "reconciling",
    "retryable_error",
    "terminal_error",
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
    "reconciled",
    "conflicted",
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
    start_ms: int = Field(default=0, ge=0)
    end_ms: int = Field(default=1, gt=0)
    provider_role: Literal["browser_preview", "fast", "accurate"] = "browser_preview"
    provider: str | None = None
    model: str | None = None
    supersedes_segment_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class BrainDumpProposalConflictDocument(StorageBaseModel):
    field: str = Field(min_length=1, max_length=100)
    current_value: str | None = Field(default=None, max_length=500)
    suggested_value: str | None = Field(default=None, max_length=500)
    producer: Literal["fast", "accurate", "reconciler", "user"] = "reconciler"
    source_segment_ids: list[str] = Field(default_factory=list)


class BrainDumpProposalDocument(StorageBaseModel):
    id: str
    ordinal: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)
    status: BrainDumpProposalStatus = "provisional"
    source_segment_ids: list[str] = Field(default_factory=list)
    predecessor_ids: list[str] = Field(default_factory=list)
    successor_ids: list[str] = Field(default_factory=list)
    locked_fields: list[str] = Field(default_factory=list)
    conflicts: list[BrainDumpProposalConflictDocument] = Field(default_factory=list)
    deleted: bool = False
    user_edited: bool = False
    title_revision: int = Field(default=1, ge=1)
    """Revision at which ``title`` was last changed; drives stale-base checks
    for reconciler patches applied through ``apply_proposal_patches``."""
    created_at: datetime
    updated_at: datetime
    revision: int = Field(default=1, ge=1)


class BrainDumpAudioChunkDocument(StorageBaseModel):
    chunk_number: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    received_at: datetime


class BrainDumpProviderRunDocument(StorageBaseModel):
    """Durable checkpoint for one sealed-audio provider stage."""

    id: str
    role: Literal["accurate_stt", "reconciler"]
    status: Literal[
        "pending", "running", "succeeded", "retryable_error", "terminal_error"
    ]
    input_hash: str = Field(min_length=64, max_length=64)
    checkpoint: Literal["sealed", "accurate_transcribed", "reconciled"]
    attempt: int = Field(default=0, ge=0)
    recovery_count: int = Field(default=0, ge=0)
    error: str | None = Field(default=None, max_length=1000)
    output_segment_ids: list[str] = Field(default_factory=list)
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class BrainDumpProposalPatchDocument(StorageBaseModel):
    """Immutable audit record for one applied proposal projection change."""

    id: str
    sequence: int = Field(ge=1)
    operation: Literal["add", "update", "split", "merge", "remove", "supersede"]
    proposal_id: str
    producer: Literal["fast", "accurate", "reconciler", "user"]
    title: str | None = None
    source_segment_ids: list[str] = Field(default_factory=list)
    predecessor_ids: list[str] = Field(default_factory=list)
    successor_ids: list[str] = Field(default_factory=list)
    locked_fields: list[str] = Field(default_factory=list)
    base_revision: int | None = None
    created_at: datetime


class BrainDumpOperationDocument(StorageBaseModel):
    """Operation-private workspace for native voice Brain Dump capture."""

    id: str
    owner_id: str
    kind: Literal["voice_brain_dump"] = "voice_brain_dump"
    status: BrainDumpStatus
    consent: BrainDumpConsent
    segments: list[BrainDumpTranscriptSegmentDocument] = Field(default_factory=list)
    proposals: list[BrainDumpProposalDocument] = Field(default_factory=list)
    media_ref: str | None = None
    audio_chunks: list[BrainDumpAudioChunkDocument] = Field(default_factory=list)
    sealed_manifest_hash: str | None = Field(default=None, min_length=64, max_length=64)
    provider_runs: list[BrainDumpProviderRunDocument] = Field(default_factory=list)
    proposal_patches: list[BrainDumpProposalPatchDocument] = Field(default_factory=list)
    status_history: list[BrainDumpStatus] = Field(default_factory=list)
    committed_task_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    schema_version: int = Field(default=2, ge=1)
    revision: int = Field(default=1, ge=1)
