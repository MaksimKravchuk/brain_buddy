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
    language_hints: list[str] = Field(default_factory=list, max_length=10)
    vocabulary: list[str] = Field(default_factory=list, max_length=200)
    # Canonical, additive consent fields (mobile-api.md). Optional so
    # existing web/legacy callers that only ever set ``provider`` keep
    # working unchanged; when present the service records and later
    # enforces them as the current-consent source of truth.
    consent_policy_version: str | None = Field(default=None, max_length=100)
    allowed_provider_categories: list[str] = Field(default_factory=list, max_length=20)
    decision_recorded_at: datetime | None = None


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


class BrainDumpProposalPatchRequest(StrictBaseModel):
    """Canonical user proposal edit/remove (mobile-api.md ``.../patches``)."""

    operation: Literal["update", "remove"]
    title: str | None = Field(default=None, min_length=1, max_length=500)
    base_proposal_revision: int = Field(ge=1)
    expected_operation_revision: int = Field(ge=1)


class BrainDumpConflictResolutionRequest(StrictBaseModel):
    """Canonical conflict resolution (mobile-api.md/ADR-0002
    ``.../conflicts/resolve``): "Keep mine" or "Use suggestion"."""

    resolution: Literal["keep", "accept"]
    expected_operation_revision: int = Field(ge=1)


class BrainDumpConsentDecisionRequest(StrictBaseModel):
    """Canonical append-only consent grant/withdraw decision."""

    decision: Literal["grant", "withdraw"]
    consent_policy_version: str | None = Field(default=None, max_length=100)
    allowed_provider_categories: list[str] = Field(default_factory=list, max_length=20)
    decision_recorded_at: datetime | None = None
    expected_operation_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def require_grant_fields(self) -> BrainDumpConsentDecisionRequest:
        if self.decision == "grant" and not self.consent_policy_version:
            raise PydanticCustomError(
                "consent_decision_grant_requires_policy_version",
                "A consent grant decision requires consent_policy_version.",
            )
        return self


class BrainDumpProposalBatchFreezeRequest(StrictBaseModel):
    """Canonical freeze request (mobile-api.md ``.../proposal-batches``)."""

    based_on_proposal_revision: int = Field(ge=1)
    expected_operation_revision: int = Field(ge=1)
    selected_proposal_ids: list[str] = Field(min_length=1, max_length=200)


class BrainDumpConfirmRequest(StrictBaseModel):
    """Canonical confirm request (mobile-api.md ``.../confirm``)."""

    proposal_batch_id: str = Field(min_length=1, max_length=200)
    expected_batch_revision: int = Field(ge=1)
    expected_operation_revision: int = Field(ge=1)


class BrainDumpAudioDeleteRequest(StrictBaseModel):
    """Canonical raw-audio delete request (mobile-api.md ``.../audio/delete``)."""

    expected_operation_revision: int = Field(ge=1)


class BrainDumpConsentResponse(StrictBaseModel):
    microphone: bool
    external_processing_allowed: bool
    provider: str | None = None
    language_hints: list[str] = Field(default_factory=list)
    vocabulary: list[str] = Field(default_factory=list)
    recorded_at: datetime
    # Canonical additive projection (mobile-api.md consent contract).
    status: Literal["granted", "withdrawn"] | None = None
    consent_policy_version: str | None = None
    allowed_provider_categories: list[str] = Field(default_factory=list)
    valid_until: datetime | None = None
    withdrawn_at: datetime | None = None


class BrainDumpProcessingPolicyResponse(StrictBaseModel):
    """Non-secret current consent/upload policy (``GET .../processing-policy``)."""

    consent_policy_version: str
    required_provider_categories: list[str]
    consent_valid_for_seconds: int = Field(ge=1)
    max_chunk_size_bytes: int = Field(ge=1)
    max_operation_size_bytes: int = Field(ge=1)
    accepted_audio_formats: list[str]


class BrainDumpRawAudioResponse(StrictBaseModel):
    state: Literal["not_received", "retained", "deletion_pending", "deleted"]
    retained_until: datetime | None = None
    delete_now_available: bool = False
    deleted_at: datetime | None = None


class BrainDumpTranscriptSegmentResponse(StrictBaseModel):
    id: str
    sequence: int
    text: str
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
    batch_id: str | None = None
    action_id: str | None = None
    outcome: Literal["succeeded", "failed", "skipped"] = "succeeded"


class BrainDumpProposalBatchActionResponse(StrictBaseModel):
    """Immutable per-action review snapshot; never carries a result field."""

    action_id: str
    proposal_id: str
    title: str
    target: Literal["native_inbox"] = "native_inbox"
    before_summary: str
    after_summary: str
    source_cue: str | None = None
    confidence: Literal["unknown"] = "unknown"
    warnings: list[str] = Field(default_factory=list)
    destination: Literal["native_inbox"] = "native_inbox"


class BrainDumpProposalBatchActionResultResponse(StrictBaseModel):
    """Receipt-derived result folded beside (never into) the action snapshot."""

    action_id: str
    status: Literal["pending", "succeeded", "failed", "skipped"]
    result_task_id: str | None = None


class BrainDumpProposalBatchResponse(StrictBaseModel):
    id: str
    based_on_proposal_revision: int
    status: Literal["frozen", "committed", "superseded"]
    snapshot: list[BrainDumpProposalBatchActionResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    committed_at: datetime | None = None
    revision: int
    results: list[BrainDumpProposalBatchActionResultResponse] = Field(
        default_factory=list
    )


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
    # Canonical additive projection fields (ADR-0002/ADR-0008 mobile contract).
    proposal_revision: int = 1
    active_proposal_batch: BrainDumpProposalBatchResponse | None = None
    committed_proposal_batch: BrainDumpProposalBatchResponse | None = None
    import_mode: Literal["native_v2", "legacy_preview_only"] = "native_v2"
    accurate_reconciliation_available: bool = True
    operation_warning_codes: list[str] = Field(default_factory=list)
    provisional_review_accepted_at: datetime | None = None
    raw_audio: BrainDumpRawAudioResponse = Field(
        default_factory=lambda: BrainDumpRawAudioResponse(state="not_received")
    )
