"""HTTP routes for the native GTD task module."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.api.contracts import error_responses
from app.api.dependencies import (
    get_config_dep,
    get_current_user,
    get_task_service,
    get_voice_brain_dump_service,
)
from app.core.config import AppConfig
from app.exceptions import ValidationFailure
from app.modules.tasks import TaskService
from app.modules.tasks.domain import (
    ProjectDocument,
    SmartAddTaskResultDocument,
    TagDocument,
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)
from app.schemas.auth import User
from app.schemas.tasks import (
    BrainDumpActionReceiptResponse,
    BrainDumpAudioChunkResponse,
    BrainDumpAudioDeleteRequest,
    BrainDumpConfirmRequest,
    BrainDumpConflictResolutionRequest,
    BrainDumpConsentDecisionRequest,
    BrainDumpConsentResponse,
    BrainDumpOperationResponse,
    BrainDumpOperationStartRequest,
    BrainDumpProcessingPolicyResponse,
    BrainDumpProposalBatchActionResponse,
    BrainDumpProposalBatchActionResultResponse,
    BrainDumpProposalBatchFreezeRequest,
    BrainDumpProposalBatchResponse,
    BrainDumpProposalConflictResponse,
    BrainDumpProposalPatchRequest,
    BrainDumpProposalPatchResponse,
    BrainDumpProposalResponse,
    BrainDumpProposalUpdateRequest,
    BrainDumpProviderRunResponse,
    BrainDumpRawAudioResponse,
    BrainDumpSealRequest,
    BrainDumpTranscriptAppendRequest,
    BrainDumpTranscriptSegmentResponse,
    ExpectedRevisionRequest,
    ProjectCreateRequest,
    ProjectResponse,
    ProjectUpdateRequest,
    SmartAddCreatedResponse,
    SmartAddTaskCreateRequest,
    SmartAddTaskResponse,
    TagCreateRequest,
    TagResponse,
    TagUpdateRequest,
    TaskCommentCreateRequest,
    TaskCommentResponse,
    TaskCommentUpdateRequest,
    TaskCounts,
    TaskCreateRequest,
    TaskListResponse,
    TaskPriority,
    TaskResponse,
    TaskSort,
    TaskState,
    TaskSubtaskCreateRequest,
    TaskSubtaskResponse,
    TaskSubtaskTransitionRequest,
    TaskSubtaskUpdateRequest,
    TaskTransitionRequest,
    TaskUpdateRequest,
)
from app.workflows.voice_brain_dump.audio_media import canonical_audio_mime_type
from app.workflows.voice_brain_dump.domain import (
    BrainDumpOperationDocument,
    BrainDumpProposalBatchDocument,
    BrainDumpProposalDocument,
    BrainDumpTranscriptSegmentDocument,
    active_proposal_batch,
    committed_proposal_batch,
    operation_warning_codes,
)
from app.workflows.voice_brain_dump.domain import (
    import_mode as brain_dump_import_mode,
)
from app.workflows.voice_brain_dump.service import (
    VoiceBrainDumpService,
    brain_dump_operation_is_committable,
    can_review_brain_dump_provisionally,
)

router = APIRouter(tags=["tasks"])


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise ValidationFailure("Idempotency-Key header is required.")
    return idempotency_key


@router.get(
    "/brain-dump-processing-policy",
    response_model=BrainDumpProcessingPolicyResponse,
    responses=error_responses(401),
)
def get_brain_dump_processing_policy(
    response: Response,
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
    config: AppConfig = Depends(get_config_dep),
) -> BrainDumpProcessingPolicyResponse:
    del current_user  # authentication required; payload is not owner-scoped
    response.headers["Cache-Control"] = "no-store"
    policy = BrainDumpProcessingPolicyResponse(
        consent_policy_version=voice_brain_dump_service.consent_policy_version,
        required_provider_categories=sorted(
            voice_brain_dump_service.required_consent_categories
        ),
        consent_valid_for_seconds=voice_brain_dump_service.consent_valid_for_seconds,
        max_chunk_size_bytes=voice_brain_dump_service.audio_limits.max_chunk_bytes,
        max_operation_size_bytes=voice_brain_dump_service.audio_limits.max_total_bytes,
        accepted_audio_formats=list(config.voice.consent.accepted_audio_formats),
    )
    return policy


@router.post(
    "/brain-dump-operations",
    response_model=BrainDumpOperationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 409, 422),
)
def start_brain_dump_operation(
    payload: BrainDumpOperationStartRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    return _to_brain_dump_response(
        voice_brain_dump_service.start_brain_dump_operation(
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.get(
    "/brain-dump-operations/{operation_id}",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(401, 404, 422),
)
def get_brain_dump_operation(
    operation_id: str,
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    return _to_brain_dump_response(
        voice_brain_dump_service.get_brain_dump_operation(operation_id, owner_id=current_user.id)
    )


@router.post(
    "/brain-dump-operations/{operation_id}/transcript",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def append_brain_dump_transcript(
    operation_id: str,
    payload: BrainDumpTranscriptAppendRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    return _to_brain_dump_response(
        voice_brain_dump_service.append_brain_dump_transcript(
            operation_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.put(
    "/brain-dump-operations/{operation_id}/audio/{chunk_number}",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
async def upload_brain_dump_audio_chunk(
    operation_id: str,
    chunk_number: int,
    request: Request,
    x_content_sha256: str | None = Header(default=None, alias="X-Content-SHA256"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    if not x_content_sha256:
        raise ValidationFailure("X-Content-SHA256 header is required.")
    limits = voice_brain_dump_service.audio_limits
    content_type = canonical_audio_mime_type(request.headers.get("content-type") or "")
    if not content_type:
        raise ValidationFailure(
            "AUDIO_CHUNK_MIME_TYPE_REQUIRED: Content-Type is required for audio uploads."
        )
    if content_type not in {
        canonical_audio_mime_type(value) for value in limits.allowed_mime_types
    }:
        raise ValidationFailure(
            "AUDIO_CHUNK_MIME_TYPE_UNSUPPORTED: audio chunk content type is not "
            "an allowed audio MIME type."
        )
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            declared_bytes = int(declared_length)
        except ValueError as exc:
            raise ValidationFailure(
                "Content-Length header must be an integer."
            ) from exc
        if declared_bytes > limits.max_chunk_bytes:
            raise ValidationFailure(
                "AUDIO_CHUNK_TOO_LARGE: declared Content-Length exceeds the "
                "configured per-chunk limit."
            )
    # Read via a bounded stream rather than ``request.body()`` so an
    # attacker who omits/understates Content-Length cannot force the whole
    # unbounded body into memory before this limit is enforced.
    buffer = bytearray()
    async for piece in request.stream():
        buffer.extend(piece)
        if len(buffer) > limits.max_chunk_bytes:
            raise ValidationFailure(
                "AUDIO_CHUNK_TOO_LARGE: audio chunk exceeds the configured "
                "per-chunk byte limit."
            )
    content = bytes(buffer)
    return _to_brain_dump_response(
        voice_brain_dump_service.upload_brain_dump_audio_chunk(
            operation_id,
            chunk_number,
            content,
            owner_id=current_user.id,
            content_sha256=x_content_sha256,
            content_type=content_type,
        )
    )


@router.post(
    "/brain-dump-operations/{operation_id}/seal",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def seal_brain_dump_operation(
    operation_id: str,
    payload: BrainDumpSealRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    return _to_brain_dump_response(
        voice_brain_dump_service.seal_brain_dump_operation(
            operation_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.patch(
    "/brain-dump-operations/{operation_id}/proposals/{proposal_id}",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
    deprecated=True,
)
def update_brain_dump_proposal(
    operation_id: str,
    proposal_id: str,
    payload: BrainDumpProposalUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    """Deprecated web-compatibility adapter.

    Delegates to the same canonical proposal-projection write path
    (``update_brain_dump_proposal`` appends the identical append-only
    ``BrainDumpProposalPatchDocument`` records and supersedes any active
    frozen batch) as ``POST .../proposals/{proposal_id}/patches``. Excluded
    from the mobile operation allowlist; kept for the bounded web overlap
    window (ADR-0002).
    """

    return _to_brain_dump_response(
        voice_brain_dump_service.update_brain_dump_proposal(
            operation_id,
            proposal_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/brain-dump-operations/{operation_id}/consent-decisions",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def record_brain_dump_consent_decision(
    operation_id: str,
    payload: BrainDumpConsentDecisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    """Canonical append-only external-processing consent grant/withdraw."""

    return _to_brain_dump_response(
        voice_brain_dump_service.record_brain_dump_consent_decision(
            operation_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/brain-dump-operations/{operation_id}/proposals/{proposal_id}/patches",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def submit_brain_dump_proposal_patch(
    operation_id: str,
    proposal_id: str,
    payload: BrainDumpProposalPatchRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    """Canonical user proposal edit/remove (mobile-api.md ``.../patches``)."""

    return _to_brain_dump_response(
        voice_brain_dump_service.submit_brain_dump_proposal_patch(
            operation_id,
            proposal_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/brain-dump-operations/{operation_id}/proposals/{proposal_id}/conflicts/resolve",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def resolve_brain_dump_proposal_conflict(
    operation_id: str,
    proposal_id: str,
    payload: BrainDumpConflictResolutionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    """Canonical conflict resolution (mobile-api.md/ADR-0002
    ``.../conflicts/resolve``): "Keep mine" or "Use suggestion" -- replaces
    the deprecated direct PATCH's ``conflict_resolution`` field for
    canonical/mobile clients."""

    return _to_brain_dump_response(
        voice_brain_dump_service.resolve_brain_dump_proposal_conflict(
            operation_id,
            proposal_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/brain-dump-operations/{operation_id}/proposal-batches",
    response_model=BrainDumpOperationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 404, 409, 422),
)
def freeze_brain_dump_proposal_batch(
    operation_id: str,
    payload: BrainDumpProposalBatchFreezeRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    """Freeze the current conflict-free active proposals into an immutable
    ``ProposalBatch`` snapshot."""

    return _to_brain_dump_response(
        voice_brain_dump_service.freeze_brain_dump_proposal_batch(
            operation_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/brain-dump-operations/{operation_id}/confirm",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def confirm_brain_dump_proposal_batch(
    operation_id: str,
    payload: BrainDumpConfirmRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    """Canonical idempotent confirmation of the current frozen batch. No
    Task exists before this command."""

    return _to_brain_dump_response(
        voice_brain_dump_service.confirm_brain_dump_proposal_batch(
            operation_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/brain-dump-operations/{operation_id}/audio/delete",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def delete_brain_dump_raw_audio_canonical(
    operation_id: str,
    payload: BrainDumpAudioDeleteRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    """Canonical, idempotent, restart-safe raw-audio deletion after
    processing reaches review or a terminal/cancelled state."""

    return _to_brain_dump_response(
        voice_brain_dump_service.delete_brain_dump_raw_audio(
            operation_id,
            ExpectedRevisionRequest(
                expected_revision=payload.expected_operation_revision
            ),
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/brain-dump-operations/{operation_id}/commit",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
    deprecated=True,
)
def commit_brain_dump_operation_deprecated(
    operation_id: str,
    payload: ExpectedRevisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    """Deprecated web-compatibility adapter for ``commit``.

    Per ADR-0002's migration section, a legacy ``/commit`` with no explicit
    batch atomically freezes the current conflict-free active proposals
    before confirming -- ``commit_brain_dump_operation`` persists the
    identical canonical ``ProposalBatch``/action-receipt records the
    two-step ``proposal-batches`` + ``confirm`` route produces, and applies
    the same provisional-review gate (no bypass). Excluded from the mobile
    operation allowlist; kept for the bounded web overlap window.
    """

    return _to_brain_dump_response(
        voice_brain_dump_service.commit_brain_dump_operation(
            operation_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/brain-dump-operations/{operation_id}/finish",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
    deprecated=True,
)
def finish_brain_dump_operation_deprecated(
    operation_id: str,
    payload: ExpectedRevisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    """Deprecated web-compatibility alias for seal/transition-to-review.

    Excluded from the mobile operation allowlist; kept for the bounded web
    overlap window (ADR-0002: ``/transcript``, ``/finish``, ``/commit``, and
    direct proposal ``PATCH`` remain aliases for v1-aware clients).
    """

    return _to_brain_dump_response(
        voice_brain_dump_service.transition_brain_dump_operation(
            operation_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
            action="finish",
        )
    )


def _dispatch_brain_dump_command(
    operation_id: str,
    action: str,
    payload: ExpectedRevisionRequest,
    *,
    idempotency: str,
    owner_id: str,
    voice_brain_dump_service: VoiceBrainDumpService,
) -> BrainDumpOperationResponse:
    """Shared recovery/lifecycle command dispatch for both the canonical
    ``.../commands/{action}`` route and its deprecated bare-path predecessor.

    ``commit`` and ``finish`` are intentionally not reachable here -- they
    have their own dedicated, explicitly deprecated routes, which Starlette
    matches before either of these paths.
    """

    if action == "retry":
        operation = voice_brain_dump_service.retry_brain_dump_operation(
            operation_id, payload, owner_id=owner_id, idempotency_key=idempotency
        )
    elif action == "review_provisional":
        operation = voice_brain_dump_service.review_brain_dump_provisionally(
            operation_id, payload, owner_id=owner_id, idempotency_key=idempotency
        )
    elif action == "withdraw_consent":
        operation = voice_brain_dump_service.withdraw_brain_dump_consent(
            operation_id, payload, owner_id=owner_id, idempotency_key=idempotency
        )
    elif action == "delete_raw_audio":
        operation = voice_brain_dump_service.delete_brain_dump_raw_audio(
            operation_id, payload, owner_id=owner_id, idempotency_key=idempotency
        )
    elif action in {"pause", "resume", "cancel"}:
        operation = voice_brain_dump_service.transition_brain_dump_operation(
            operation_id,
            payload,
            owner_id=owner_id,
            idempotency_key=idempotency,
            action=action,
        )
    else:
        raise ValidationFailure("Unsupported brain dump operation command.")
    return _to_brain_dump_response(operation)


BrainDumpCanonicalCommand = Literal[
    "pause", "resume", "cancel", "retry", "review-provisional"
]


@router.post(
    "/brain-dump-operations/{operation_id}/commands/{action}",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def command_brain_dump_operation_canonical(
    operation_id: str,
    action: BrainDumpCanonicalCommand,
    payload: ExpectedRevisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    """Canonical, typed command path (ADR-0002 ``.../commands/{pause|resume|
    cancel|retry|review-provisional}``). Unlike the deprecated bare-path
    dispatcher below, ``action`` is an OpenAPI enum, not an arbitrary string
    -- this is the operation the mobile client generation allowlist may
    consume for these commands."""

    return _dispatch_brain_dump_command(
        operation_id,
        action.replace("-", "_"),
        payload,
        idempotency=_require_idempotency_key(idempotency_key),
        owner_id=current_user.id,
        voice_brain_dump_service=voice_brain_dump_service,
    )


@router.post(
    "/brain-dump-operations/{operation_id}/{action}",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
    deprecated=True,
)
def command_brain_dump_operation(
    operation_id: str,
    action: str,
    payload: ExpectedRevisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    voice_brain_dump_service: VoiceBrainDumpService = Depends(get_voice_brain_dump_service),
) -> BrainDumpOperationResponse:
    """Deprecated web-compatibility adapter: an arbitrary, untyped ``action``
    path segment. Delegates to the same canonical service commands as
    ``.../commands/{action}`` above -- no bypass, no separate semantics.
    Excluded from the mobile operation allowlist; kept for the bounded web
    overlap window (ADR-0002)."""

    return _dispatch_brain_dump_command(
        operation_id,
        action,
        payload,
        idempotency=_require_idempotency_key(idempotency_key),
        owner_id=current_user.id,
        voice_brain_dump_service=voice_brain_dump_service,
    )


@router.post(
    "/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 409, 422),
)
def create_project(
    payload: ProjectCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> ProjectResponse:
    project = task_service.create_project(
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_project_response(
        project, task_service=task_service, owner_id=current_user.id
    )


@router.get(
    "/projects", response_model=list[ProjectResponse], responses=error_responses(401)
)
def list_projects(
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> list[ProjectResponse]:
    return [
        _to_project_response(
            project, task_service=task_service, owner_id=current_user.id
        )
        for project in task_service.list_projects(owner_id=current_user.id)
    ]


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> ProjectResponse:
    project = task_service.update_project(
        project_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_project_response(
        project, task_service=task_service, owner_id=current_user.id
    )


@router.post(
    "/projects/{project_id}/archive",
    response_model=ProjectResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def archive_project(
    project_id: str,
    payload: ExpectedRevisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> ProjectResponse:
    project = task_service.archive_project(
        project_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_project_response(
        project, task_service=task_service, owner_id=current_user.id
    )


@router.get(
    "/projects/{project_id}",
    response_model=ProjectResponse,
    responses=error_responses(401, 404, 422),
)
def get_project(
    project_id: str,
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> ProjectResponse:
    return _to_project_response(
        task_service.get_project(project_id, owner_id=current_user.id),
        task_service=task_service,
        owner_id=current_user.id,
    )


@router.post(
    "/tags",
    response_model=TagResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 409, 422),
)
def create_tag(
    payload: TagCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TagResponse:
    tag = task_service.create_tag(
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_tag_response(tag, task_service=task_service, owner_id=current_user.id)


@router.get("/tags", response_model=list[TagResponse], responses=error_responses(401))
def list_tags(
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> list[TagResponse]:
    return [
        _to_tag_response(tag, task_service=task_service, owner_id=current_user.id)
        for tag in task_service.list_tags(owner_id=current_user.id)
    ]


@router.patch(
    "/tags/{tag_id}",
    response_model=TagResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def update_tag(
    tag_id: str,
    payload: TagUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TagResponse:
    tag = task_service.update_tag(
        tag_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_tag_response(tag, task_service=task_service, owner_id=current_user.id)


@router.delete(
    "/tags/{tag_id}",
    response_model=TagResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def delete_tag(
    tag_id: str,
    expected_revision: int = Query(ge=1),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TagResponse:
    tag = task_service.delete_tag(
        tag_id,
        ExpectedRevisionRequest(expected_revision=expected_revision),
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_tag_response(tag, task_service=task_service, owner_id=current_user.id)


@router.get(
    "/tags/{tag_id}",
    response_model=TagResponse,
    responses=error_responses(401, 404, 422),
)
def get_tag(
    tag_id: str,
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TagResponse:
    return _to_tag_response(
        task_service.get_tag(tag_id, owner_id=current_user.id),
        task_service=task_service,
        owner_id=current_user.id,
    )


@router.post(
    "/tasks/smart-add",
    response_model=SmartAddTaskResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 404, 409, 422),
)
def smart_add_task(
    payload: SmartAddTaskCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> SmartAddTaskResponse:
    result = task_service.smart_add_task(
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_smart_add_response(
        result,
        task_service=task_service,
        owner_id=current_user.id,
    )


@router.get(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    responses=error_responses(401, 404, 422),
)
def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    task, subtasks, comments = task_service.get_task_detail(
        task_id, owner_id=current_user.id
    )
    return _to_response(task, subtasks=subtasks, comments=comments)


@router.post(
    "/tasks/{task_id}/subtasks",
    response_model=TaskSubtaskResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 404, 409, 422),
)
def create_subtask(
    task_id: str,
    payload: TaskSubtaskCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskSubtaskResponse:
    subtask = task_service.create_subtask(
        task_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_subtask_response(subtask)


@router.patch(
    "/tasks/{task_id}/subtasks/{subtask_id}",
    response_model=TaskSubtaskResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def update_subtask(
    task_id: str,
    subtask_id: str,
    payload: TaskSubtaskUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskSubtaskResponse:
    return _to_subtask_response(
        task_service.update_subtask(
            task_id,
            subtask_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/tasks/{task_id}/subtasks/{subtask_id}/transitions",
    response_model=TaskSubtaskResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def transition_subtask(
    task_id: str,
    subtask_id: str,
    payload: TaskSubtaskTransitionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskSubtaskResponse:
    return _to_subtask_response(
        task_service.transition_subtask(
            task_id,
            subtask_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/tasks/{task_id}/comments",
    response_model=TaskCommentResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 404, 409, 422),
)
def create_comment(
    task_id: str,
    payload: TaskCommentCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskCommentResponse:
    comment = task_service.create_comment(
        task_id,
        payload,
        owner_id=current_user.id,
        actor_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )
    return _to_comment_response(comment)


@router.patch(
    "/tasks/{task_id}/comments/{comment_id}",
    response_model=TaskCommentResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def update_comment(
    task_id: str,
    comment_id: str,
    payload: TaskCommentUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskCommentResponse:
    return _to_comment_response(
        task_service.update_comment(
            task_id,
            comment_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.patch(
    "/tasks/{task_id}",
    response_model=TaskResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def update_task(
    task_id: str,
    payload: TaskUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    return _to_response(
        task_service.update_task(
            task_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/tasks/{task_id}/transitions",
    response_model=TaskResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def transition_task(
    task_id: str,
    payload: TaskTransitionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    return _to_response(
        task_service.transition_task(
            task_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 404, 409, 422),
)
def create_task(
    payload: TaskCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskResponse:
    return _to_response(
        task_service.create_task(
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.get(
    "/tasks",
    response_model=TaskListResponse,
    responses=error_responses(400, 401, 404, 422),
)
def list_tasks(
    state: TaskState | None = None,
    project_id: str | None = None,
    tag_id: str | None = None,
    unassigned_project: bool = False,
    include_completed: bool = False,
    include_cancelled: bool = False,
    q: str | None = None,
    priority: list[TaskPriority] | None = Query(default=None),
    due_before: date | None = None,
    due_on: date | None = None,
    due_after: date | None = None,
    sort: TaskSort = "manual",
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> TaskListResponse:
    items, next_cursor, has_more, counts_by_state = task_service.list_tasks(
        owner_id=current_user.id,
        state=state,
        project_id=project_id,
        tag_id=tag_id,
        unassigned_project=unassigned_project,
        include_completed=include_completed,
        include_cancelled=include_cancelled,
        q=q,
        priority=priority or [],
        due_before=due_before,
        due_on=due_on,
        due_after=due_after,
        sort=sort,
        cursor=cursor,
        limit=limit,
    )
    return TaskListResponse(
        items=[_to_response(task) for task in items],
        next_cursor=next_cursor,
        has_more=has_more,
        counts_by_state=TaskCounts(**counts_by_state),
    )


def _to_brain_dump_response(
    operation: BrainDumpOperationDocument,
) -> BrainDumpOperationResponse:
    active_batch = active_proposal_batch(operation)
    committed_batch = committed_proposal_batch(operation)
    is_legacy_import = operation.legacy_import == "legacy_preview_only"
    return BrainDumpOperationResponse(
        id=operation.id,
        owner_id=operation.owner_id,
        kind=operation.kind,
        status=operation.status,
        consent=BrainDumpConsentResponse(
            microphone=operation.consent.microphone,
            external_processing_allowed=operation.consent.external_processing_allowed,
            provider=operation.consent.provider,
            language_hints=operation.consent.language_hints,
            vocabulary=operation.consent.vocabulary,
            recorded_at=operation.consent.recorded_at,
            status=operation.consent.status,
            consent_policy_version=operation.consent.consent_policy_version,
            allowed_provider_categories=operation.consent.allowed_provider_categories,
            valid_until=operation.consent.valid_until,
            withdrawn_at=operation.consent.withdrawn_at,
        ),
        segments=[
            _to_brain_dump_segment_response(segment) for segment in operation.segments
        ],
        proposals=[
            _to_brain_dump_proposal_response(item) for item in operation.proposals
        ],
        media_ref=operation.media_ref,
        audio_chunks=[
            BrainDumpAudioChunkResponse(
                chunk_number=chunk.chunk_number,
                sha256=chunk.sha256,
                size_bytes=chunk.size_bytes,
            )
            for chunk in operation.audio_chunks
        ],
        sealed_manifest_hash=operation.sealed_manifest_hash,
        raw_audio_expires_at=operation.raw_audio_expires_at,
        raw_audio_present=bool(operation.audio_chunks),
        working_artifacts_expires_at=operation.working_artifacts_expires_at,
        reconciliation_quality=operation.reconciliation_quality,
        committable=brain_dump_operation_is_committable(operation),
        available_recovery_actions=_brain_dump_available_recovery_actions(operation),
        provider_runs=[
            BrainDumpProviderRunResponse(
                id=run.id,
                role=run.role,
                status=run.status,
                checkpoint=run.checkpoint,
                attempt=run.attempt,
                recovery_count=run.recovery_count,
                error=run.error,
                error_code=run.error_code,
                provider=run.provider,
                model=run.model,
                template_version=run.template_version,
                estimated_cost_usd=run.estimated_cost_usd,
                reserved_cost_usd=run.reserved_cost_usd,
                consumed_cost_usd=run.consumed_cost_usd,
            )
            for run in operation.provider_runs
        ],
        proposal_patches=[
            BrainDumpProposalPatchResponse(
                id=patch.id,
                sequence=patch.sequence,
                operation=patch.operation,
                proposal_id=patch.proposal_id,
                producer=patch.producer,
                title=patch.title,
                source_segment_ids=patch.source_segment_ids,
                predecessor_ids=patch.predecessor_ids,
                successor_ids=patch.successor_ids,
                locked_fields=patch.locked_fields,
                base_revision=patch.base_revision,
            )
            for patch in operation.proposal_patches
        ],
        action_receipts=[
            BrainDumpActionReceiptResponse(
                id=receipt.id,
                proposal_id=receipt.proposal_id,
                task_id=receipt.task_id,
                child_idempotency_key=receipt.child_idempotency_key,
                source_segment_ids=receipt.source_segment_ids,
                proposal_patch_ids=receipt.proposal_patch_ids,
                source_operation_id=receipt.source_operation_id,
                source_manifest_hash=receipt.source_manifest_hash,
                reconciliation_run_id=receipt.reconciliation_run_id,
                reconciliation_provider=receipt.reconciliation_provider,
                reconciliation_model=receipt.reconciliation_model,
                reconciliation_template_version=receipt.reconciliation_template_version,
                reconciliation_quality=receipt.reconciliation_quality,
                confirmed_title_sha256=receipt.confirmed_title_sha256,
                proposal_revision=receipt.proposal_revision,
                user_edited=receipt.user_edited,
                confidence=receipt.confidence,
                confirmed_by_actor_id=receipt.confirmed_by_actor_id,
                decision=receipt.decision,
                confirmed_at=receipt.confirmed_at,
                batch_id=receipt.batch_id,
                action_id=receipt.action_id,
                outcome=receipt.outcome,
            )
            for receipt in operation.action_receipts
        ],
        status_history=operation.status_history,
        committed_task_ids=operation.committed_task_ids,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
        revision=operation.revision,
        proposal_revision=operation.proposal_revision,
        active_proposal_batch=(
            _to_brain_dump_batch_response(active_batch, operation)
            if active_batch is not None
            else None
        ),
        committed_proposal_batch=(
            _to_brain_dump_batch_response(committed_batch, operation)
            if committed_batch is not None
            else None
        ),
        import_mode=brain_dump_import_mode(operation),
        # Truthful capability projection (ADR-0008): a legacy import can
        # never earn an accurate reconciliation, and once raw audio is
        # pending deletion or gone, a retry can no longer read the sealed
        # original audio accurate STT requires -- both cases must report
        # `false`, never only the legacy-import case.
        accurate_reconciliation_available=(
            not is_legacy_import
            and operation.raw_audio_state not in {"deletion_pending", "deleted"}
        ),
        operation_warning_codes=operation_warning_codes(operation),
        provisional_review_accepted_at=operation.provisional_review_accepted_at,
        raw_audio=BrainDumpRawAudioResponse(
            state=operation.raw_audio_state,
            retained_until=operation.raw_audio_expires_at,
            delete_now_available=(
                operation.raw_audio_state == "retained"
                and operation.status
                in {
                    "awaiting_confirmation",
                    "committing",
                    "completed",
                    "cancelled",
                    "terminal_error",
                    "retryable_error",
                }
            ),
            deleted_at=operation.raw_audio_deleted_at,
        ),
    )


def _to_brain_dump_batch_response(
    batch: BrainDumpProposalBatchDocument, operation: BrainDumpOperationDocument
) -> BrainDumpProposalBatchResponse:
    receipts_by_action = {
        receipt.action_id: receipt
        for receipt in operation.action_receipts
        if receipt.batch_id == batch.id
    }
    results: list[BrainDumpProposalBatchActionResultResponse] = []
    for action in batch.actions:
        receipt = receipts_by_action.get(action.action_id)
        if receipt is None:
            results.append(
                BrainDumpProposalBatchActionResultResponse(
                    action_id=action.action_id,
                    status="pending",
                    result_task_id=None,
                )
            )
        else:
            results.append(
                BrainDumpProposalBatchActionResultResponse(
                    action_id=action.action_id,
                    status=receipt.outcome,
                    result_task_id=receipt.task_id,
                )
            )
    return BrainDumpProposalBatchResponse(
        id=batch.id,
        based_on_proposal_revision=batch.based_on_proposal_revision,
        status=batch.status,
        snapshot=[
            BrainDumpProposalBatchActionResponse(
                action_id=action.action_id,
                proposal_id=action.proposal_id,
                title=action.title,
                target=action.target,
                before_summary=action.before_summary,
                after_summary=action.after_summary,
                source_cue=action.source_cue,
                confidence=action.confidence,
                warnings=action.warnings,
                destination=action.destination,
            )
            for action in batch.actions
        ],
        warnings=batch.warnings,
        created_at=batch.created_at,
        committed_at=batch.committed_at,
        revision=batch.revision,
        results=results,
    )


def _brain_dump_available_recovery_actions(
    operation: BrainDumpOperationDocument,
) -> list[Literal["retry", "review_provisional", "cancel"]]:
    """Project only recovery commands the service will authorize for this state."""

    actions: list[Literal["retry", "review_provisional", "cancel"]] = []
    if operation.status == "retryable_error":
        actions.append("retry")
    if can_review_brain_dump_provisionally(operation):
        actions.append("review_provisional")
    if operation.status in {"retryable_error", "terminal_error"}:
        actions.append("cancel")
    return actions



def _to_brain_dump_segment_response(
    segment: BrainDumpTranscriptSegmentDocument,
) -> BrainDumpTranscriptSegmentResponse:
    return BrainDumpTranscriptSegmentResponse(
        id=segment.id,
        sequence=segment.sequence,
        text=segment.text,
        stability=segment.stability,
        start_ms=segment.start_ms,
        end_ms=segment.end_ms,
        provider_role=segment.provider_role,
        provider=segment.provider,
        model=segment.model,
        supersedes_segment_ids=segment.supersedes_segment_ids,
        created_at=segment.created_at,
    )


def _to_brain_dump_proposal_response(
    proposal: BrainDumpProposalDocument,
) -> BrainDumpProposalResponse:
    return BrainDumpProposalResponse(
        id=proposal.id,
        ordinal=proposal.ordinal,
        title=proposal.title,
        status=proposal.status,
        source_segment_ids=proposal.source_segment_ids,
        predecessor_ids=proposal.predecessor_ids,
        successor_ids=proposal.successor_ids,
        locked_fields=proposal.locked_fields,
        conflicts=[
            BrainDumpProposalConflictResponse(
                field=conflict.field,
                current_value=conflict.current_value,
                suggested_value=conflict.suggested_value,
                producer=conflict.producer,
                source_segment_ids=conflict.source_segment_ids,
            )
            for conflict in proposal.conflicts
        ],
        deleted=proposal.deleted,
        user_edited=proposal.user_edited,
        revision=proposal.revision,
    )


def _to_response(
    task: TaskDocument,
    *,
    subtasks: Sequence[TaskSubtaskDocument] = (),
    comments: Sequence[TaskCommentDocument] = (),
) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        title=task.title,
        details=task.details,
        state=task.state,
        project_id=task.project_id,
        tag_ids=task.tag_ids,
        due_date=task.due_date,
        priority=task.priority,
        waiting_for=task.waiting_for,
        waiting_since=task.waiting_since,
        order_key=task.order_key,
        source_capture_ids=task.source_capture_ids,
        created_at=task.created_at,
        updated_at=task.updated_at,
        completed_at=task.completed_at,
        cancelled_at=task.cancelled_at,
        revision=task.revision,
        subtasks=[_to_subtask_response(item) for item in subtasks],
        comments=[_to_comment_response(item) for item in comments],
    )


def _to_smart_add_response(
    result: SmartAddTaskResultDocument,
    *,
    task_service: TaskService,
    owner_id: str,
) -> SmartAddTaskResponse:
    return SmartAddTaskResponse(
        task=_to_response(result.task),
        project=(
            _to_project_response(
                result.project, task_service=task_service, owner_id=owner_id
            )
        if result.project
            else None
        ),
        tags=[
            _to_tag_response(tag, task_service=task_service, owner_id=owner_id)
            for tag in result.tags
        ],
        created=SmartAddCreatedResponse(
            project_id=result.created.project_id,
            tag_ids=result.created.tag_ids,
        ),
    )


def _to_project_response(
    project: ProjectDocument, *, task_service: TaskService, owner_id: str
) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        color=project.color,
        state=project.state,
        revision=project.revision,
        open_task_count=task_service.open_task_count_for_project(
            project.id, owner_id=owner_id
        ),
    )


def _to_tag_response(
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
    )


def _to_subtask_response(subtask: TaskSubtaskDocument) -> TaskSubtaskResponse:
    return TaskSubtaskResponse(
        id=subtask.id,
        title=subtask.title,
        state=subtask.state,
        order_key=subtask.order_key,
        revision=subtask.revision,
    )


def _to_comment_response(comment: TaskCommentDocument) -> TaskCommentResponse:
    return TaskCommentResponse(
        id=comment.id,
        body=comment.body,
        actor_id=comment.actor_id,
        created_at=comment.created_at,
        edited_at=comment.edited_at,
        revision=comment.revision,
    )
