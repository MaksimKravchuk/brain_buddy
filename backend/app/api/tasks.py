"""HTTP routes for the native GTD task module."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from fastapi import APIRouter, Depends, Header, Query, Request, status

from app.api.contracts import error_responses
from app.api.dependencies import get_current_user, get_task_service
from app.exceptions import ValidationFailure
from app.modules.tasks import TaskService
from app.modules.tasks.domain import (
    BrainDumpOperationDocument,
    BrainDumpProposalDocument,
    BrainDumpTranscriptSegmentDocument,
    ProjectDocument,
    SmartAddTaskResultDocument,
    TagDocument,
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)
from app.schemas.auth import User
from app.schemas.tasks import (
    BrainDumpAudioChunkResponse,
    BrainDumpConsentResponse,
    BrainDumpOperationResponse,
    BrainDumpOperationStartRequest,
    BrainDumpProposalConflictResponse,
    BrainDumpProposalPatchResponse,
    BrainDumpProposalResponse,
    BrainDumpProposalUpdateRequest,
    BrainDumpProviderRunResponse,
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

router = APIRouter(tags=["tasks"])


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise ValidationFailure("Idempotency-Key header is required.")
    return idempotency_key


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
    task_service: TaskService = Depends(get_task_service),
) -> BrainDumpOperationResponse:
    return _to_brain_dump_response(
        task_service.start_brain_dump_operation(
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
    task_service: TaskService = Depends(get_task_service),
) -> BrainDumpOperationResponse:
    return _to_brain_dump_response(
        task_service.get_brain_dump_operation(operation_id, owner_id=current_user.id)
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
    task_service: TaskService = Depends(get_task_service),
) -> BrainDumpOperationResponse:
    return _to_brain_dump_response(
        task_service.append_brain_dump_transcript(
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
    task_service: TaskService = Depends(get_task_service),
) -> BrainDumpOperationResponse:
    if not x_content_sha256:
        raise ValidationFailure("X-Content-SHA256 header is required.")
    content = await request.body()
    return _to_brain_dump_response(
        task_service.upload_brain_dump_audio_chunk(
            operation_id,
            chunk_number,
            content,
            owner_id=current_user.id,
            content_sha256=x_content_sha256,
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
    task_service: TaskService = Depends(get_task_service),
) -> BrainDumpOperationResponse:
    return _to_brain_dump_response(
        task_service.seal_brain_dump_operation(
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
)
def update_brain_dump_proposal(
    operation_id: str,
    proposal_id: str,
    payload: BrainDumpProposalUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> BrainDumpOperationResponse:
    return _to_brain_dump_response(
        task_service.update_brain_dump_proposal(
            operation_id,
            proposal_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=_require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/brain-dump-operations/{operation_id}/{action}",
    response_model=BrainDumpOperationResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def command_brain_dump_operation(
    operation_id: str,
    action: str,
    payload: ExpectedRevisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    task_service: TaskService = Depends(get_task_service),
) -> BrainDumpOperationResponse:
    idempotency = _require_idempotency_key(idempotency_key)
    if action == "commit":
        operation = task_service.commit_brain_dump_operation(
            operation_id, payload, owner_id=current_user.id, idempotency_key=idempotency
        )
    elif action == "retry":
        operation = task_service.retry_brain_dump_operation(
            operation_id, payload, owner_id=current_user.id, idempotency_key=idempotency
        )
    elif action in {"pause", "resume", "finish", "cancel"}:
        operation = task_service.transition_brain_dump_operation(
            operation_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=idempotency,
            action=action,
        )
    else:
        raise ValidationFailure("Unsupported brain dump operation command.")
    return _to_brain_dump_response(operation)


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
    return BrainDumpOperationResponse(
        id=operation.id,
        owner_id=operation.owner_id,
        kind=operation.kind,
        status=operation.status,
        consent=BrainDumpConsentResponse(
            microphone=operation.consent.microphone,
            external_processing_allowed=operation.consent.external_processing_allowed,
            provider=operation.consent.provider,
            recorded_at=operation.consent.recorded_at,
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
        provider_runs=[
            BrainDumpProviderRunResponse(
                id=run.id,
                role=run.role,
                status=run.status,
                checkpoint=run.checkpoint,
                attempt=run.attempt,
                recovery_count=run.recovery_count,
                error=run.error,
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
                base_revision=patch.base_revision,
            )
            for patch in operation.proposal_patches
        ],
        status_history=operation.status_history,
        committed_task_ids=operation.committed_task_ids,
        created_at=operation.created_at,
        updated_at=operation.updated_at,
        revision=operation.revision,
    )


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
