"""FastAPI routes for the voice-only Brain Dump vertical slice.

Flow: create/resume session -> upload voice audio (transcription appends
flat ordered drafts) -> edit/delete drafts -> add more voice -> Save
session exports each remaining draft to RTM Inbox as a plain name-only
task.

No text capture, Add-by-text, CRT, recommendations, or destination
selection endpoints exist here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.dependencies import get_brain_dump_service, get_current_user
from app.schemas.auth import User
from app.schemas.brain_dump import (
    CreateSessionResponse,
    DraftUpdateRequest,
    ExportResult,
    SaveSessionResponse,
    SessionDetailResponse,
    UploadAudioResponse,
)
from app.services.brain_dump_service import BrainDumpService

router = APIRouter(tags=["brain-dump"])

_DRAFT_FIELDS = {"id", "text", "created_at", "updated_at", "revision"}


def _to_create_response(session) -> CreateSessionResponse:
    return CreateSessionResponse(
        id=session.id,
        status=session.status,
        drafts=session.drafts,
        revision=session.revision,
    )


def _to_detail_response(session) -> SessionDetailResponse:
    return SessionDetailResponse(
        id=session.id,
        status=session.status,
        drafts=session.drafts,
        export_results=session.export_results,
        revision=session.revision,
    )


def _to_upload_response(session) -> UploadAudioResponse:
    return UploadAudioResponse(
        id=session.id,
        status=session.status,
        drafts=session.drafts,
        revision=session.revision,
    )


@router.post(
    "/sessions",
    response_model=CreateSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    current_user: User = Depends(get_current_user),
    brain_dump_service: BrainDumpService = Depends(get_brain_dump_service),
) -> CreateSessionResponse:
    """Create or resume the owner's active brain dump session."""

    session = brain_dump_service.get_or_create_session(owner_id=current_user.id)
    return _to_create_response(session)


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    brain_dump_service: BrainDumpService = Depends(get_brain_dump_service),
) -> SessionDetailResponse:
    """Get the current state of a brain dump session."""

    session = brain_dump_service.get_session(session_id, owner_id=current_user.id)
    return _to_detail_response(session)


@router.post(
    "/sessions/{session_id}/audio",
    response_model=UploadAudioResponse,
)
async def upload_audio(
    session_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    brain_dump_service: BrainDumpService = Depends(get_brain_dump_service),
) -> UploadAudioResponse:
    """Upload voice audio for transcription.

    The transcription provider converts audio into a flat list of task
    drafts and appends them to the session. The session moves to
    ``reviewing`` status.
    """

    audio_bytes = await file.read()
    session = brain_dump_service.upload_audio(
        session_id,
        owner_id=current_user.id,
        audio_bytes=audio_bytes,
        mime_type=file.content_type or "audio/webm",
    )
    return _to_upload_response(session)


@router.patch(
    "/sessions/{session_id}/drafts/{draft_id}",
    response_model=SessionDetailResponse,
)
def edit_draft(
    session_id: str,
    draft_id: str,
    payload: DraftUpdateRequest,
    current_user: User = Depends(get_current_user),
    brain_dump_service: BrainDumpService = Depends(get_brain_dump_service),
) -> SessionDetailResponse:
    """Edit the text of an existing draft."""

    session = brain_dump_service.edit_draft(
        session_id,
        draft_id,
        owner_id=current_user.id,
        text=payload.text,
    )
    return _to_detail_response(session)


@router.delete(
    "/sessions/{session_id}/drafts/{draft_id}",
    response_model=SessionDetailResponse,
)
def delete_draft(
    session_id: str,
    draft_id: str,
    current_user: User = Depends(get_current_user),
    brain_dump_service: BrainDumpService = Depends(get_brain_dump_service),
) -> SessionDetailResponse:
    """Remove a draft from the session."""

    session = brain_dump_service.delete_draft(
        session_id,
        draft_id,
        owner_id=current_user.id,
    )
    return _to_detail_response(session)


@router.post(
    "/sessions/{session_id}/save",
    response_model=SaveSessionResponse,
)
def save_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    brain_dump_service: BrainDumpService = Depends(get_brain_dump_service),
) -> SaveSessionResponse:
    """Export every remaining draft to RTM Inbox and mark completed.

    Each draft is submitted as a plain Inbox task: name-only, no tags,
    notes, URL, priority, dates, or list/project move. Idempotency keys
    prevent duplicate creates.
    """

    session = brain_dump_service.save_session(
        session_id,
        owner_id=current_user.id,
    )
    return SaveSessionResponse(
        id=session.id,
        status=session.status,
        export_results=[ExportResult(**r) for r in session.export_results],
        revision=session.revision,
    )
