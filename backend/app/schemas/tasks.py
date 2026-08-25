"""HTTP contracts for the native task module."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_core import PydanticCustomError

from .common import StrictBaseModel

TaskState = Literal["inbox", "next", "waiting", "someday", "completed", "cancelled"]
OpenTaskState = Literal["inbox", "next", "waiting", "someday"]
TaskPriority = Literal["none", "low", "medium", "high"]
TaskSort = Literal["manual", "due", "priority", "title"]


class TitleCompletionConsent(StrictBaseModel):
    external_processing_allowed: bool
    provider: str = Field(min_length=1, max_length=64)


class TitleCompletionRequest(StrictBaseModel):
    draft: str
    project_id: str | None = Field(default=None, min_length=1, max_length=500)
    consent: TitleCompletionConsent

    @model_validator(mode="after")
    def require_trimmed_draft_length(self) -> TitleCompletionRequest:
        if not 1 <= len(self.draft.strip()) <= 500:
            raise PydanticCustomError(
                "title_completion_draft_length",
                "Title completion draft must contain 1-500 trimmed characters.",
            )
        return self


class TitleCompletionProviderResponse(StrictBaseModel):
    provider: str | None = None


class TitleCompletionResponse(StrictBaseModel):
    request_id: str
    candidates: list[str] = Field(min_length=3, max_length=3)


class TitleCompletionAcceptedRequest(StrictBaseModel):
    request_id: str = Field(min_length=36, max_length=36)
    rank: int = Field(ge=1, le=3)


class ProjectCreateRequest(StrictBaseModel):
    name: str = Field(min_length=1, max_length=500)
    color: str | None = Field(default=None, max_length=64)


class ProjectUpdateRequest(StrictBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    color: str | None = Field(default=None, max_length=64)
    expected_revision: int = Field(ge=1)


class ExpectedRevisionRequest(StrictBaseModel):
    expected_revision: int = Field(ge=1)


class BrainDumpSealRequest(ExpectedRevisionRequest):
    expected_chunks: int = Field(ge=0)
    manifest_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class TagCreateRequest(StrictBaseModel):
    name: str = Field(min_length=1, max_length=500)


class TagUpdateRequest(StrictBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    expected_revision: int = Field(ge=1)


class ProjectResponse(StrictBaseModel):
    id: str
    name: str
    color: str | None = None
    state: Literal["active", "archived"]
    revision: int
    open_task_count: int = Field(default=0, ge=0)


class TagResponse(StrictBaseModel):
    id: str
    name: str
    state: Literal["active", "deleted"]
    revision: int
    open_task_count: int = Field(default=0, ge=0)


class TaskCreateRequest(StrictBaseModel):
    """Create a task in one of the supported lists."""

    title: str = Field(min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=20_000)
    state: OpenTaskState = "inbox"
    project_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)
    due_date: date | None = None
    priority: TaskPriority = "none"
    waiting_for: str | None = Field(default=None, max_length=500)
    source_capture_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def accept_context_ids_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tag_ids" not in data and "context_ids" in data:
            data = {**data}
            data["tag_ids"] = data.pop("context_ids") or []
        return data


class SmartAddClassificationRef(StrictBaseModel):
    id: str | None = Field(default=None, min_length=1, max_length=500)
    name: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_strict_xor(self) -> SmartAddClassificationRef:
        if (self.id is None) == (self.name is None):
            raise PydanticCustomError(
                "smart_add_ref_xor",
                "Smart Add classification ref requires exactly one of id or name.",
            )
        return self


class SmartAddTaskCreateRequest(StrictBaseModel):
    """Create a task and classify inline Smart Add refs atomically."""

    title: str = Field(min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=20_000)
    state: OpenTaskState = "inbox"
    waiting_for: str | None = Field(default=None, max_length=500)
    due_date: date | None = None
    priority: TaskPriority = "none"
    project: SmartAddClassificationRef | None = None
    tags: list[SmartAddClassificationRef] = Field(default_factory=list)


class SmartAddCreatedResponse(StrictBaseModel):
    project_id: str | None = None
    tag_ids: list[str] = Field(default_factory=list)


class TaskUpdateRequest(StrictBaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    details: str | None = Field(default=None, max_length=20_000)
    project_id: str | None = None
    tag_ids: list[str] | None = None
    due_date: date | None = None
    priority: TaskPriority | None = None
    waiting_for: str | None = Field(default=None, max_length=500)
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


class TaskSubtaskUpdateRequest(StrictBaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    expected_revision: int = Field(ge=1)


class TaskSubtaskTransitionRequest(StrictBaseModel):
    action: Literal["complete", "reopen", "cancel"]
    expected_revision: int = Field(ge=1)


class TaskCommentCreateRequest(StrictBaseModel):
    body: str = Field(min_length=1, max_length=20_000)


class TaskCommentUpdateRequest(StrictBaseModel):
    body: str = Field(min_length=1, max_length=20_000)
    expected_revision: int = Field(ge=1)


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
    edited_at: datetime | None = None
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
    priority: TaskPriority = "none"
    waiting_for: str | None = None
    waiting_since: datetime | None = None
    order_key: int
    source_capture_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    revision: int
    subtasks: list[TaskSubtaskResponse] = Field(default_factory=list)
    comments: list[TaskCommentResponse] = Field(default_factory=list)


class SmartAddTaskResponse(StrictBaseModel):
    task: TaskResponse
    project: ProjectResponse | None = None
    tags: list[TagResponse] = Field(default_factory=list)
    created: SmartAddCreatedResponse


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


class BrainDumpConsentRequest(StrictBaseModel):
    microphone: bool
    external_processing_allowed: bool = False
    provider: str | None = Field(default=None, max_length=100)
    providers: list[str] = Field(default_factory=list, max_length=5)
    language_hints: list[str] = Field(default_factory=list, max_length=10)
    vocabulary: list[str] = Field(default_factory=list, max_length=200)


class BrainDumpOperationStartRequest(StrictBaseModel):
    consent: BrainDumpConsentRequest


class BrainDumpTranscriptSegmentRequest(StrictBaseModel):
    sequence: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=20_000)
    stability: Literal["interim", "stable"] = "stable"


class BrainDumpTranscriptAppendRequest(StrictBaseModel):
    segments: list[BrainDumpTranscriptSegmentRequest] = Field(
        min_length=1, max_length=50
    )


class BrainDumpProposalUpdateRequest(StrictBaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    deleted: bool | None = None
    conflict_resolution: Literal["keep", "accept"] | None = None
    expected_revision: int = Field(ge=1)


class BrainDumpConsentResponse(StrictBaseModel):
    microphone: bool
    external_processing_allowed: bool
    provider: str | None = None
    providers: list[str] = Field(default_factory=list)
    language_hints: list[str] = Field(default_factory=list)
    vocabulary: list[str] = Field(default_factory=list)
    recorded_at: datetime


class BrainDumpProvidersResponse(StrictBaseModel):
    """Configured external voice-provider categories per pipeline role.

    Each value is the provider category the client must name in consent for
    that role, or ``None`` when the configured adapter performs no external
    processing (e.g. a deterministic/disabled stand-in)."""

    accurate_stt: str | None = None
    reconciler: str | None = None


class BrainDumpTranscriptSegmentResponse(StrictBaseModel):
    id: str
    sequence: int
    text: str
    content_sha256: str | None = None
    language: str | None = None
    confidence: float | None = None
    stability: Literal["interim", "stable"]
    start_ms: int = 0
    end_ms: int = 1
    provider_role: Literal["browser_preview", "fast", "accurate"] = "browser_preview"
    provider: str | None = None
    model: str | None = None
    supersedes_segment_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class BrainDumpProposalConflictResponse(StrictBaseModel):
    field: str
    current_value: str | None = None
    suggested_value: str | None = None
    producer: Literal["fast", "accurate", "reconciler", "user"]
    source_segment_ids: list[str] = Field(default_factory=list)


class BrainDumpProposalResponse(StrictBaseModel):
    id: str
    ordinal: int
    title: str
    status: BrainDumpProposalStatus
    source_segment_ids: list[str] = Field(default_factory=list)
    predecessor_ids: list[str] = Field(default_factory=list)
    successor_ids: list[str] = Field(default_factory=list)
    locked_fields: list[str] = Field(default_factory=list)
    conflicts: list[BrainDumpProposalConflictResponse] = Field(default_factory=list)
    deleted: bool
    user_edited: bool
    revision: int


class BrainDumpAudioChunkResponse(StrictBaseModel):
    chunk_number: int
    sha256: str
    size_bytes: int


class BrainDumpProviderRunResponse(StrictBaseModel):
    id: str
    role: Literal["accurate_stt", "reconciler"]
    status: Literal[
        "pending", "running", "succeeded", "retryable_error", "terminal_error"
    ]
    checkpoint: Literal["sealed", "accurate_transcribed", "reconciled"]
    attempt: int
    recovery_count: int
    error: str | None = None
    error_code: str | None = None
    provider: str | None = None
    model: str | None = None
    template_version: str | None = None
    estimated_cost_usd: float = 0.0
    reserved_cost_usd: float = 0.0
    consumed_cost_usd: float = 0.0


class BrainDumpProposalPatchResponse(StrictBaseModel):
    id: str
    sequence: int
    operation: Literal["add", "update", "split", "merge", "remove", "supersede"]
    proposal_id: str
    producer: Literal["fast", "accurate", "reconciler", "user"]
    title: str | None = None
    source_segment_ids: list[str] = Field(default_factory=list)
    predecessor_ids: list[str] = Field(default_factory=list)
    successor_ids: list[str] = Field(default_factory=list)
    locked_fields: list[str] = Field(default_factory=list)
    base_revision: int | None = None


class BrainDumpActionReceiptResponse(StrictBaseModel):
    id: str
    proposal_id: str
    task_id: str
    child_idempotency_key: str
    source_segment_ids: list[str] = Field(default_factory=list)
    proposal_patch_ids: list[str] = Field(default_factory=list)
    source_operation_id: str | None = None
    source_manifest_hash: str | None = None
    reconciliation_run_id: str | None = None
    reconciliation_provider: str | None = None
    reconciliation_model: str | None = None
    reconciliation_template_version: str | None = None
    reconciliation_quality: Literal[
        "none", "provisional_only", "accurate", "conflicted"
    ] = "none"
    confirmed_title_sha256: str | None = None
    proposal_revision: int | None = None
    user_edited: bool = False
    confidence: Literal["unknown"] = "unknown"
    confirmed_by_actor_id: str | None = None
    decision: Literal["create_native_inbox_task"] = "create_native_inbox_task"
    confirmed_at: datetime


class BrainDumpOperationResponse(StrictBaseModel):
    id: str
    owner_id: str
    kind: Literal["voice_brain_dump"]
    status: BrainDumpStatus
    consent: BrainDumpConsentResponse
    segments: list[BrainDumpTranscriptSegmentResponse] = Field(default_factory=list)
    proposals: list[BrainDumpProposalResponse] = Field(default_factory=list)
    media_ref: str | None = None
    audio_chunks: list[BrainDumpAudioChunkResponse] = Field(default_factory=list)
    sealed_manifest_hash: str | None = None
    raw_audio_expires_at: datetime | None = None
    raw_audio_present: bool = False
    working_artifacts_expires_at: datetime | None = None
    reconciliation_quality: Literal[
        "none", "provisional_only", "accurate", "conflicted"
    ] = "none"
    committable: bool = False
    available_recovery_actions: list[
        Literal["retry", "review_provisional", "cancel"]
    ] = Field(default_factory=list)
    provider_runs: list[BrainDumpProviderRunResponse] = Field(default_factory=list)
    proposal_patches: list[BrainDumpProposalPatchResponse] = Field(default_factory=list)
    action_receipts: list[BrainDumpActionReceiptResponse] = Field(default_factory=list)
    status_history: list[BrainDumpStatus] = Field(default_factory=list)
    committed_task_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    revision: int
