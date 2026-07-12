"""Application service for the voice-only Brain Dump vertical slice.

Flow: create/resume session -> upload voice audio (transcription appends
flat ordered drafts) -> edit/delete drafts in review -> add more voice ->
Save session exports each remaining draft as a plain RTM Inbox task.

No text capture, CRT, recommendations, planner, task types, subtasks,
destination selection, or Weekly Review concepts appear here.
"""

from __future__ import annotations

import uuid

from app.ai.task_tracker import (
    TaskTrackerAdapter,
    TaskTrackerError,
)
from app.ai.transcription import TranscriptionProvider
from app.exceptions import ConflictError, NotFoundError
from app.repositories.brain_dump import BrainDumpRepository
from app.schemas.brain_dump import (
    BrainDumpSession,
    Draft,
    ExportResult,
    SessionStatus,
)
from app.utils.time import utcnow


class BrainDumpService:
    """Orchestrates the voice brain dump lifecycle."""

    def __init__(
        self,
        repo: BrainDumpRepository,
        transcription_provider: TranscriptionProvider,
        task_tracker: TaskTrackerAdapter,
    ) -> None:
        self._repo = repo
        self._transcription = transcription_provider
        self._tracker = task_tracker

    def get_or_create_session(self, *, owner_id: str) -> BrainDumpSession:
        """Return the owner's active session, or create a new one."""

        active = self._repo.get_active_session(owner_id=owner_id)
        if active is not None:
            return active

        now = utcnow()
        session = BrainDumpSession(
            id=uuid.uuid4().hex[:12],
            owner_id=owner_id,
            status=SessionStatus.RECORDING,
            drafts=[],
            created_at=now,
            updated_at=now,
            revision=1,
        )
        self._repo.save(session)
        return session

    def get_session(self, session_id: str, *, owner_id: str) -> BrainDumpSession:
        """Load a session, raising NotFoundError if missing or cross-owner."""

        session = self._repo.load(session_id, owner_id=owner_id)
        if session is None:
            raise NotFoundError("BrainDumpSession", session_id)
        return session

    def upload_audio(
        self,
        session_id: str,
        *,
        owner_id: str,
        audio_bytes: bytes,
        mime_type: str = "audio/webm",
    ) -> BrainDumpSession:
        """Transcribe audio and append task drafts to the session.

        After transcription the session moves to ``reviewing`` status so
        the user can edit, delete, add more voice, or save.
        """

        session = self.get_session(session_id, owner_id=owner_id)

        if session.status == SessionStatus.COMPLETED:
            raise ConflictError("BrainDumpSession", session_id)

        result = self._transcription.transcribe(audio_bytes, mime_type=mime_type)
        now = utcnow()
        for text in result.task_drafts:
            draft = Draft(
                id=uuid.uuid4().hex[:12],
                text=text,
                created_at=now,
                updated_at=now,
                revision=1,
            )
            session.drafts.append(draft)

        session.status = SessionStatus.REVIEWING
        session.updated_at = now
        session.revision += 1
        self._repo.save(session)
        return session

    def edit_draft(
        self,
        session_id: str,
        draft_id: str,
        *,
        owner_id: str,
        text: str,
    ) -> BrainDumpSession:
        """Edit the text of an existing draft."""

        session = self.get_session(session_id, owner_id=owner_id)

        if session.status == SessionStatus.COMPLETED:
            raise ConflictError("BrainDumpSession", session_id)

        draft = self._find_draft(session, draft_id)
        if draft is None:
            raise NotFoundError("Draft", draft_id)

        draft.text = text
        draft.updated_at = utcnow()
        draft.revision += 1
        session.updated_at = utcnow()
        session.revision += 1
        self._repo.save(session)
        return session

    def delete_draft(
        self,
        session_id: str,
        draft_id: str,
        *,
        owner_id: str,
    ) -> BrainDumpSession:
        """Remove a draft from the session."""

        session = self.get_session(session_id, owner_id=owner_id)

        if session.status == SessionStatus.COMPLETED:
            raise ConflictError("BrainDumpSession", session_id)

        original_len = len(session.drafts)
        session.drafts = [d for d in session.drafts if d.id != draft_id]
        if len(session.drafts) == original_len:
            raise NotFoundError("Draft", draft_id)

        session.updated_at = utcnow()
        session.revision += 1
        self._repo.save(session)
        return session

    def save_session(
        self,
        session_id: str,
        *,
        owner_id: str,
    ) -> BrainDumpSession:
        """Export every remaining draft to RTM Inbox and mark completed.

        Each draft is submitted through the RTM adapter contract as a
        plain Inbox task: name-only, no tags, notes, URL, priority,
        dates, or list/project move. Idempotency keys prevent duplicate
        creates. On ambiguous RTM creates (same key), the original result
        is returned without re-creating.
        """

        session = self.get_session(session_id, owner_id=owner_id)

        if session.status == SessionStatus.COMPLETED:
            raise ConflictError("BrainDumpSession", session_id)

        export_results: list[ExportResult] = []
        for draft in session.drafts:
            idem_key = self._idempotency_key(
                session_id=session_id, draft_id=draft.id, revision=draft.revision
            )
            try:
                result = self._tracker.create_inbox_task(
                    name=draft.text,
                    idempotency_key=idem_key,
                )
                export_results.append(
                    ExportResult(
                        draft_id=draft.id,
                        external_ref=result.external_ref,
                        success=result.success,
                        error=result.error,
                    )
                )
            except TaskTrackerError as exc:
                export_results.append(
                    ExportResult(
                        draft_id=draft.id,
                        external_ref=None,
                        success=False,
                        error=str(exc),
                    )
                )

        session.export_results = [r.model_dump() for r in export_results]
        session.status = SessionStatus.COMPLETED
        session.updated_at = utcnow()
        session.revision += 1
        self._repo.save(session)
        return session

    @staticmethod
    def _find_draft(session: BrainDumpSession, draft_id: str) -> Draft | None:
        for draft in session.drafts:
            if draft.id == draft_id:
                return draft
        return None

    @staticmethod
    def _idempotency_key(*, session_id: str, draft_id: str, revision: int) -> str:
        """Deterministic idempotency key per draft export."""

        return f"bd:{session_id}:{draft_id}:r{revision}"


__all__ = ["BrainDumpService"]
