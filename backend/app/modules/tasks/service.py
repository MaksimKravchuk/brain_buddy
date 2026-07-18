"""Application service for owner-scoped native GTD tasks."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Concatenate, ParamSpec, TypeVar, cast

from pydantic import BaseModel

from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.schemas.tasks import (
    BrainDumpOperationStartRequest,
    BrainDumpProposalUpdateRequest,
    BrainDumpSealRequest,
    BrainDumpTranscriptAppendRequest,
    ExpectedRevisionRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    SmartAddClassificationRef,
    SmartAddTaskCreateRequest,
    TagCreateRequest,
    TagUpdateRequest,
    TaskCommentCreateRequest,
    TaskCommentUpdateRequest,
    TaskCreateRequest,
    TaskSubtaskCreateRequest,
    TaskSubtaskTransitionRequest,
    TaskSubtaskUpdateRequest,
    TaskTransitionRequest,
    TaskUpdateRequest,
)
from app.utils.identifiers import generate_id
from app.utils.time import utcnow

from .domain import (
    BrainDumpAudioChunkDocument,
    BrainDumpConsent,
    BrainDumpOperationDocument,
    BrainDumpProposalConflictDocument,
    BrainDumpProposalDocument,
    BrainDumpProposalStatus,
    BrainDumpTranscriptSegmentDocument,
    IdempotencyRecord,
    ProjectDocument,
    SmartAddCreatedDocument,
    SmartAddTaskResultDocument,
    TagDocument,
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)
from .repository import (
    TaskRepository,
    display_project_name,
    display_tag_name,
    normalize_task_name,
)

_OPEN_STATES = ("inbox", "next", "waiting", "someday")
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}

_P = ParamSpec("_P")
_Result = TypeVar("_Result")


def _serialized_write(
    command: Callable[Concatenate[TaskService, _P], _Result],
) -> Callable[Concatenate[TaskService, _P], _Result]:
    """Hold the owner command lock over idempotency and resource persistence."""

    def wrapped(
        service: TaskService, /, *args: _P.args, **kwargs: _P.kwargs
    ) -> _Result:
        owner_id = cast(str, kwargs["owner_id"])
        idempotency_key = cast(str, kwargs["idempotency_key"])
        with service.task_repo.command_lock(owner_id):
            service.task_repo.purge_expired_idempotency(owner_id=owner_id, now=utcnow())
            service._reconcile_idempotent_result(owner_id=owner_id, key=idempotency_key)
            return command(service, *args, **kwargs)

    return wrapped


class TaskService:
    """Owns canonical GTD records and their owner-scoped projections."""

    def __init__(self, task_repo: TaskRepository) -> None:
        self.task_repo = task_repo

    @_serialized_write
    def create_project(
        self,
        payload: ProjectCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> ProjectDocument:
        command = "create_project"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._project_result(record, owner_id=owner_id)

        now = utcnow()
        name = display_project_name(payload.name)
        project = ProjectDocument(
            id=generate_id("project"),
            owner_id=owner_id,
            name=name,
            normalized_name=normalize_task_name(name),
            color=payload.color,
            created_at=now,
            updated_at=now,
        )
        self._assert_unique_project_name(owner_id=owner_id, project=project)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=project.id,
            response=project,
        )
        self.task_repo.create_project(project)
        return project

    @_serialized_write
    def create_tag(
        self,
        payload: TagCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TagDocument:
        command = "create_tag"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._tag_result(record, owner_id=owner_id)

        now = utcnow()
        name = display_tag_name(payload.name)
        tag = TagDocument(
            id=generate_id("tag"),
            owner_id=owner_id,
            name=name,
            normalized_name=normalize_task_name(name, strip_tag_prefix=True),
            created_at=now,
            updated_at=now,
        )
        self._assert_unique_tag_name(owner_id=owner_id, tag=tag)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=tag.id,
            response=tag,
        )
        self.task_repo.create_tag(tag)
        return tag

    @_serialized_write
    def create_task(
        self,
        payload: TaskCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskDocument:
        command = "create_task"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._task_result(record, owner_id=owner_id)

        self._assert_active_references(
            owner_id=owner_id,
            project_id=payload.project_id,
            tag_ids=payload.tag_ids,
        )
        waiting_for = (
            self._waiting_for(payload.waiting_for)
            if payload.state == "waiting"
            else None
        )
        now = utcnow()
        task = TaskDocument(
            id=generate_id("task"),
            owner_id=owner_id,
            title=payload.title,
            details=payload.details,
            state=payload.state,
            project_id=payload.project_id,
            tag_ids=payload.tag_ids,
            due_date=payload.due_date,
            priority=payload.priority,
            waiting_for=waiting_for,
            waiting_since=now if waiting_for else None,
            order_key=self.task_repo.next_order_key(
                owner_id=owner_id, state=payload.state
            ),
            source_capture_ids=self._source_capture_ids(payload.source_capture_ids),
            created_at=now,
            updated_at=now,
        )
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=task.id,
            response=task,
        )
        self.task_repo.create(task)
        return task

    @_serialized_write
    def smart_add_task(
        self,
        payload: SmartAddTaskCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> SmartAddTaskResultDocument:
        command = "smart_add_task"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._smart_add_result(record, owner_id=owner_id)

        waiting_for = (
            self._waiting_for(payload.waiting_for)
            if payload.state == "waiting"
            else None
        )
        project, created_project_id = self._resolve_smart_add_project(
            payload.project, owner_id=owner_id
        )
        tags, created_tag_ids = self._resolve_smart_add_tags(
            payload.tags, owner_id=owner_id
        )
        now = utcnow()
        task = TaskDocument(
            id=generate_id("task"),
            owner_id=owner_id,
            title=payload.title,
            details=payload.details,
            state=payload.state,
            project_id=project.id if project else None,
            tag_ids=[tag.id for tag in tags],
            due_date=payload.due_date,
            priority=payload.priority,
            waiting_for=waiting_for,
            waiting_since=now if waiting_for else None,
            order_key=self.task_repo.next_order_key(owner_id=owner_id, state=payload.state),
            source_capture_ids=[],
            created_at=now,
            updated_at=now,
        )
        result = SmartAddTaskResultDocument(
            task=task,
            project=project,
            tags=tags,
            created=SmartAddCreatedDocument(
                project_id=created_project_id,
                tag_ids=created_tag_ids,
            ),
        )
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=task.id,
            response=result,
        )
        if project is not None and created_project_id == project.id:
            self.task_repo.create_project(project)
        for tag in tags:
            if tag.id in created_tag_ids:
                self.task_repo.create_tag(tag)
        self.task_repo.create(task)
        return result

    @_serialized_write
    def start_brain_dump_operation(
        self,
        payload: BrainDumpOperationStartRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> BrainDumpOperationDocument:
        command = "brain_dump_start"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._brain_dump_operation_result(record, owner_id=owner_id)

        if not payload.consent.microphone:
            raise ValidationFailure("Microphone consent is required to start a brain dump.")
        now = utcnow()
        operation = BrainDumpOperationDocument(
            id=generate_id("brain_dump"),
            owner_id=owner_id,
            status="recording",
            consent=BrainDumpConsent(
                microphone=payload.consent.microphone,
                external_processing_allowed=payload.consent.external_processing_allowed,
                provider=payload.consent.provider,
                recorded_at=now,
            ),
            created_at=now,
            updated_at=now,
        )
        self.task_repo.save_brain_dump_operation(operation)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=operation.id,
            response=operation,
        )
        return operation

    def get_brain_dump_operation(
        self, operation_id: str, *, owner_id: str
    ) -> BrainDumpOperationDocument:
        return self.task_repo.get_brain_dump_operation_for_owner(
            operation_id, owner_id=owner_id
        )

    def upload_brain_dump_audio_chunk(
        self,
        operation_id: str,
        chunk_number: int,
        content: bytes,
        *,
        owner_id: str,
        content_sha256: str,
    ) -> BrainDumpOperationDocument:
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != content_sha256:
            raise ConflictError(
                "Brain dump audio chunk",
                str(chunk_number),
                "CHUNK_CONFLICT: uploaded audio hash does not match X-Content-SHA256.",
            )
        with self.task_repo.command_lock(owner_id):
            operation = self.get_brain_dump_operation(operation_id, owner_id=owner_id)
            if operation.status not in {"recording", "paused"}:
                raise ValidationFailure("Audio chunks can only be uploaded while recording or paused.")
            existing = {
                chunk.chunk_number: chunk for chunk in operation.audio_chunks
            }.get(chunk_number)
            if existing is not None:
                if existing.sha256 != actual_sha256 or existing.size_bytes != len(content):
                    raise ConflictError(
                        "Brain dump audio chunk",
                        str(chunk_number),
                        "CHUNK_CONFLICT: chunk number already has different audio.",
                    )
                return operation
            self.task_repo.save_brain_dump_audio_chunk(
                owner_id=owner_id,
                operation_id=operation_id,
                chunk_number=chunk_number,
                sha256=actual_sha256,
                content=content,
            )
            now = utcnow()
            chunks = [
                *operation.audio_chunks,
                BrainDumpAudioChunkDocument(
                    chunk_number=chunk_number,
                    sha256=actual_sha256,
                    size_bytes=len(content),
                    received_at=now,
                ),
            ]
            updated = operation.model_copy(
                update={
                    "media_ref": operation.media_ref or f"media_{operation.id}",
                    "audio_chunks": sorted(chunks, key=lambda item: item.chunk_number),
                    "updated_at": now,
                    "revision": operation.revision + 1,
                }
            )
            self.task_repo.save_brain_dump_operation(updated)
            return updated

    @_serialized_write
    def seal_brain_dump_operation(
        self,
        operation_id: str,
        payload: BrainDumpSealRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> BrainDumpOperationDocument:
        command = f"brain_dump_seal:{operation_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._brain_dump_operation_result(record, owner_id=owner_id)
        operation = self.get_brain_dump_operation(operation_id, owner_id=owner_id)
        self._assert_revision(
            "Brain dump operation", operation.id, operation.revision, payload.expected_revision
        )
        if operation.status not in {"recording", "paused"}:
            raise ValidationFailure("Only an active brain dump can be sealed.")
        chunk_numbers = {chunk.chunk_number for chunk in operation.audio_chunks}
        expected_numbers = set(range(payload.expected_chunks))
        missing = sorted(expected_numbers - chunk_numbers)
        if missing:
            raise ValidationFailure("Brain dump audio manifest is incomplete.", {"missing_chunks": missing})
        audio = self.task_repo.load_brain_dump_audio_chunks(
            owner_id=owner_id,
            operation_id=operation.id,
            chunks=[(chunk.chunk_number, chunk.sha256) for chunk in operation.audio_chunks if chunk.chunk_number in expected_numbers],
        )
        transcript = audio.decode("utf-8", errors="ignore").strip()
        now = utcnow()
        accurate_segment = BrainDumpTranscriptSegmentDocument(
            id=generate_id("segment"),
            sequence=max((segment.sequence for segment in operation.segments), default=0) + 1,
            text=transcript or "Untranscribed sealed audio",
            stability="stable",
            start_ms=0,
            end_ms=max(1, len((transcript or "audio").split()) * 500),
            provider_role="accurate",
            provider=operation.consent.provider or "deterministic",
            model="deterministic-accurate-v1",
            supersedes_segment_ids=[segment.id for segment in operation.segments if segment.provider_role != "accurate"],
            created_at=now,
        )
        proposals = self._reconcile_accurate_titles(
            operation.proposals,
            self._extract_task_titles(accurate_segment.text),
            source_segment_id=accurate_segment.id,
            now=now,
        )
        updated = operation.model_copy(
            update={
                "status": "awaiting_confirmation",
                "status_history": [
                    *operation.status_history,
                    "sealing",
                    "fast_processing",
                    "accurate_transcribing",
                    "reconciling",
                    "awaiting_confirmation",
                ],
                "segments": [*operation.segments, accurate_segment],
                "proposals": proposals,
                "updated_at": now,
                "revision": operation.revision + 1,
            }
        )
        self.task_repo.save_brain_dump_operation(updated)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        return updated

    @_serialized_write
    def append_brain_dump_transcript(
        self,
        operation_id: str,
        payload: BrainDumpTranscriptAppendRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> BrainDumpOperationDocument:
        command = f"brain_dump_append:{operation_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._brain_dump_operation_result(record, owner_id=owner_id)

        operation = self.get_brain_dump_operation(operation_id, owner_id=owner_id)
        if operation.status not in {"recording", "paused"}:
            raise ValidationFailure("Transcript can only be appended while recording or paused.")
        now = utcnow()
        segments_by_sequence = {segment.sequence: segment for segment in operation.segments}
        for segment in payload.segments:
            existing = segments_by_sequence.get(segment.sequence)
            if existing is not None:
                if existing.text != segment.text or existing.stability != segment.stability:
                    if existing.stability == "interim":
                        segments_by_sequence[segment.sequence] = existing.model_copy(
                            update={
                                "text": segment.text,
                                "stability": segment.stability,
                            }
                        )
                        continue
                    raise ConflictError("Brain dump segment", str(segment.sequence))
                continue
            segments_by_sequence[segment.sequence] = BrainDumpTranscriptSegmentDocument(
                id=generate_id("segment"),
                sequence=segment.sequence,
                text=segment.text,
                stability=segment.stability,
                created_at=now,
            )
        segments = sorted(segments_by_sequence.values(), key=lambda item: item.sequence)
        proposals = self._proposals_from_segments(operation.proposals, segments, now=now)
        updated = operation.model_copy(
            update={
                "segments": segments,
                "proposals": proposals,
                "updated_at": now,
                "revision": operation.revision + 1,
            }
        )
        self.task_repo.save_brain_dump_operation(updated)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        return updated

    @_serialized_write
    def update_brain_dump_proposal(
        self,
        operation_id: str,
        proposal_id: str,
        payload: BrainDumpProposalUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> BrainDumpOperationDocument:
        command = f"brain_dump_update_proposal:{operation_id}:{proposal_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._brain_dump_operation_result(record, owner_id=owner_id)
        operation = self.get_brain_dump_operation(operation_id, owner_id=owner_id)
        self._assert_revision("Brain dump operation", operation.id, operation.revision, payload.expected_revision)
        if operation.status not in {"recording", "paused", "awaiting_confirmation"}:
            raise ValidationFailure("Proposal cannot be edited in this operation state.")
        now = utcnow()
        changed = False
        proposals: list[BrainDumpProposalDocument] = []
        for proposal in operation.proposals:
            if proposal.id != proposal_id:
                proposals.append(proposal)
                continue
            update: dict[str, object] = {"updated_at": now, "revision": proposal.revision + 1}
            if "title" in payload.model_fields_set and payload.title:
                update.update(
                    {
                        "title": payload.title.strip(),
                        "status": "user_edited",
                        "user_edited": True,
                        "locked_fields": sorted({*proposal.locked_fields, "title"}),
                    }
                )
            if "deleted" in payload.model_fields_set and payload.deleted is not None:
                update["deleted"] = payload.deleted
            proposals.append(proposal.model_copy(update=update))
            changed = True
        if not changed:
            raise NotFoundError("Brain dump proposal", proposal_id)
        updated = operation.model_copy(
            update={"proposals": proposals, "updated_at": now, "revision": operation.revision + 1}
        )
        self.task_repo.save_brain_dump_operation(updated)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        return updated

    @_serialized_write
    def transition_brain_dump_operation(
        self,
        operation_id: str,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        action: str,
    ) -> BrainDumpOperationDocument:
        command = f"brain_dump_{action}:{operation_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._brain_dump_operation_result(record, owner_id=owner_id)
        operation = self.get_brain_dump_operation(operation_id, owner_id=owner_id)
        self._assert_revision("Brain dump operation", operation.id, operation.revision, payload.expected_revision)
        status_by_action = {
            "pause": "paused",
            "resume": "recording",
            "finish": "awaiting_confirmation",
            "cancel": "cancelled",
        }
        next_status = status_by_action.get(action)
        if next_status is None:
            raise ValidationFailure("Unsupported brain dump operation transition.")
        if action == "pause" and operation.status != "recording":
            raise ValidationFailure("Only a recording brain dump can be paused.")
        if action == "resume" and operation.status != "paused":
            raise ValidationFailure("Only a paused brain dump can be resumed.")
        if action == "finish" and operation.status not in {"recording", "paused"}:
            raise ValidationFailure("Only an active brain dump can be finished.")
        if action == "cancel" and operation.status in {"completed", "cancelled"}:
            next_status = operation.status
        now = utcnow()
        proposals = operation.proposals
        if action == "finish":
            proposals = [
                proposal.model_copy(
                    update={
                        "status": "ready_to_review",
                        "updated_at": now,
                        "revision": proposal.revision + 1,
                    }
                )
                if not proposal.deleted and not proposal.user_edited
                else proposal
                for proposal in operation.proposals
            ]
        updated = operation.model_copy(
            update={
                "status": next_status,
                "proposals": proposals,
                "updated_at": now,
                "revision": operation.revision + 1,
            }
        )
        self.task_repo.save_brain_dump_operation(updated)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        return updated

    @_serialized_write
    def commit_brain_dump_operation(
        self,
        operation_id: str,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> BrainDumpOperationDocument:
        command = f"brain_dump_commit:{operation_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._brain_dump_operation_result(record, owner_id=owner_id)
        operation = self.get_brain_dump_operation(operation_id, owner_id=owner_id)
        if operation.status == "completed":
            self._store_idempotency(
                owner_id=owner_id,
                key=idempotency_key,
                command=command,
                request_hash=request_hash,
                resource_id=operation.id,
                response=operation,
            )
            return operation
        self._assert_revision("Brain dump operation", operation.id, operation.revision, payload.expected_revision)
        if operation.status != "awaiting_confirmation":
            raise ValidationFailure("Brain dump must be awaiting confirmation before save.")
        conflicted = [
            proposal.id
            for proposal in operation.proposals
            if not proposal.deleted and proposal.conflicts
        ]
        if conflicted:
            raise ValidationFailure(
                "Brain dump conflicts must be reviewed before save.",
                {"proposal_ids": conflicted},
            )
        now = utcnow()
        committed_task_ids: list[str] = []
        for proposal in operation.proposals:
            if proposal.deleted:
                continue
            task = TaskDocument(
                id=generate_id("task"),
                owner_id=owner_id,
                title=proposal.title,
                details=None,
                state="inbox",
                project_id=None,
                tag_ids=[],
                order_key=self.task_repo.next_order_key(owner_id=owner_id, state="inbox"),
                source_capture_ids=[f"brain_dump:{operation.id}:{proposal.id}"],
                created_at=now,
                updated_at=now,
            )
            self.task_repo.create(task)
            committed_task_ids.append(task.id)
        updated = operation.model_copy(
            update={
                "status": "completed",
                "committed_task_ids": committed_task_ids,
                "updated_at": now,
                "revision": operation.revision + 1,
            }
        )
        self.task_repo.save_brain_dump_operation(updated)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        return updated

    @_serialized_write
    def create_subtask(
        self,
        task_id: str,
        payload: TaskSubtaskCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskSubtaskDocument:
        self.get_task(task_id, owner_id=owner_id)
        command = f"create_subtask:{task_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._subtask_result(record, owner_id=owner_id, task_id=task_id)

        now = utcnow()
        subtasks = self.task_repo.list_subtasks(owner_id=owner_id, task_id=task_id)
        subtask = TaskSubtaskDocument(
            id=generate_id("subtask"),
            owner_id=owner_id,
            task_id=task_id,
            title=payload.title,
            order_key=max((item.order_key for item in subtasks), default=-1) + 1,
            created_at=now,
            updated_at=now,
        )
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=subtask.id,
            response=subtask,
        )
        self.task_repo.create_subtask(subtask)
        return subtask

    @_serialized_write
    def create_comment(
        self,
        task_id: str,
        payload: TaskCommentCreateRequest,
        *,
        owner_id: str,
        actor_id: str,
        idempotency_key: str,
    ) -> TaskCommentDocument:
        self.get_task(task_id, owner_id=owner_id)
        command = f"create_comment:{task_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._comment_result(record, owner_id=owner_id, task_id=task_id)

        now = utcnow()
        comment = TaskCommentDocument(
            id=generate_id("comment"),
            owner_id=owner_id,
            task_id=task_id,
            actor_id=actor_id,
            body=payload.body,
            created_at=now,
        )
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=comment.id,
            response=comment,
        )
        self.task_repo.create_comment(comment)
        return comment

    @_serialized_write
    def update_subtask(
        self,
        task_id: str,
        subtask_id: str,
        payload: TaskSubtaskUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskSubtaskDocument:
        command = f"update_subtask:{task_id}:{subtask_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._subtask_result(record, owner_id=owner_id, task_id=task_id)

        self.get_task(task_id, owner_id=owner_id)
        subtask = self.task_repo.get_subtask_for_owner(
            subtask_id, owner_id=owner_id, task_id=task_id
        )
        self._assert_revision(
            "Subtask", subtask.id, subtask.revision, payload.expected_revision
        )
        fields = payload.model_fields_set
        now = utcnow()
        updated = subtask.model_copy(
            update={
                "title": payload.title if "title" in fields else subtask.title,
                "updated_at": now,
                "revision": subtask.revision + 1,
            }
        )
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        self.task_repo.save_subtask(updated)
        return updated

    @_serialized_write
    def transition_subtask(
        self,
        task_id: str,
        subtask_id: str,
        payload: TaskSubtaskTransitionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskSubtaskDocument:
        command = f"transition_subtask:{task_id}:{subtask_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._subtask_result(record, owner_id=owner_id, task_id=task_id)

        self.get_task(task_id, owner_id=owner_id)
        subtask = self.task_repo.get_subtask_for_owner(
            subtask_id, owner_id=owner_id, task_id=task_id
        )
        self._assert_revision(
            "Subtask", subtask.id, subtask.revision, payload.expected_revision
        )
        next_state = {
            "complete": "completed",
            "cancel": "cancelled",
            "reopen": "open",
        }[payload.action]
        if subtask.state == next_state:
            raise ValidationFailure("Subtask transition requires a different state.")
        now = utcnow()
        updated = subtask.model_copy(
            update={"state": next_state, "updated_at": now, "revision": subtask.revision + 1}
        )
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        self.task_repo.save_subtask(updated)
        return updated

    @_serialized_write
    def update_comment(
        self,
        task_id: str,
        comment_id: str,
        payload: TaskCommentUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskCommentDocument:
        command = f"update_comment:{task_id}:{comment_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._comment_result(record, owner_id=owner_id, task_id=task_id)

        self.get_task(task_id, owner_id=owner_id)
        comment = self.task_repo.get_comment_for_owner(
            comment_id, owner_id=owner_id, task_id=task_id
        )
        self._assert_revision(
            "Comment", comment.id, comment.revision, payload.expected_revision
        )
        now = utcnow()
        updated = comment.model_copy(
            update={
                "body": payload.body,
                "edited_at": now,
                "revision": comment.revision + 1,
            }
        )
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        self.task_repo.save_comment(updated)
        return updated

    def get_task_detail(
        self, task_id: str, *, owner_id: str
    ) -> tuple[TaskDocument, list[TaskSubtaskDocument], list[TaskCommentDocument]]:
        task = self.get_task(task_id, owner_id=owner_id)
        return (
            task,
            sorted(
                self.task_repo.list_subtasks(owner_id=owner_id, task_id=task_id),
                key=lambda item: (item.order_key, item.id),
            ),
            sorted(
                self.task_repo.list_comments(owner_id=owner_id, task_id=task_id),
                key=lambda item: (item.created_at, item.id),
            ),
        )

    @_serialized_write
    def update_task(
        self,
        task_id: str,
        payload: TaskUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskDocument:
        command = f"update_task:{task_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._task_result(record, owner_id=owner_id)

        task = self.get_task(task_id, owner_id=owner_id)
        self._assert_current(task, payload.expected_revision)
        fields = payload.model_fields_set
        if "title" in fields and payload.title is None:
            raise ValidationFailure("Task title cannot be null.")
        if "priority" in fields and payload.priority is None:
            raise ValidationFailure("Task priority cannot be null.")
        if "waiting_for" in fields:
            if task.state != "waiting":
                raise ValidationFailure("waiting_for can only be edited on Waiting tasks.")
            waiting_for: str | None = self._waiting_for(payload.waiting_for)
        else:
            waiting_for = task.waiting_for
        project_id = payload.project_id if "project_id" in fields else task.project_id
        tag_ids = payload.tag_ids if "tag_ids" in fields else task.tag_ids
        self._assert_active_references(
            owner_id=owner_id,
            project_id=project_id,
            tag_ids=tag_ids or [],
        )
        updated = self._validated_task_update(
            task,
            title=payload.title if "title" in fields else task.title,
            details=payload.details if "details" in fields else task.details,
            project_id=project_id,
            tag_ids=tag_ids or [],
            due_date=payload.due_date if "due_date" in fields else task.due_date,
            priority=payload.priority if "priority" in fields else task.priority,
            waiting_for=waiting_for,
            updated_at=utcnow(),
            revision=task.revision + 1,
        )
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        self.task_repo.save(updated)
        return updated

    @_serialized_write
    def transition_task(
        self,
        task_id: str,
        payload: TaskTransitionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskDocument:
        command = f"transition_task:{task_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._task_result(record, owner_id=owner_id)

        task = self.get_task(task_id, owner_id=owner_id)
        self._assert_current(task, payload.expected_revision)
        now = utcnow()
        if payload.action == "complete":
            if task.state not in _OPEN_STATES:
                raise ValidationFailure("Only open tasks can be completed.")
            updates = {
                "state": "completed",
                "completed_at": now,
                "cancelled_at": None,
                "waiting_for": None,
                "waiting_since": None,
            }
        elif payload.action == "cancel":
            if task.state not in _OPEN_STATES:
                raise ValidationFailure("Only open tasks can be cancelled.")
            updates = {
                "state": "cancelled",
                "cancelled_at": now,
                "completed_at": None,
                "waiting_for": None,
                "waiting_since": None,
            }
        elif payload.action == "reopen":
            if task.state not in {"completed", "cancelled"} or payload.to_state is None:
                raise ValidationFailure(
                    "Reopen requires a terminal task and an open destination."
                )
            waiting_for = (
                self._waiting_for(payload.waiting_for)
                if payload.to_state == "waiting"
                else None
            )
            updates = {
                "state": payload.to_state,
                "completed_at": None,
                "cancelled_at": None,
                "waiting_for": waiting_for,
                "waiting_since": now if waiting_for else None,
            }
        else:
            if task.state not in _OPEN_STATES or payload.to_state is None:
                raise ValidationFailure("Move requires an open task and destination.")
            if task.state == payload.to_state:
                raise ValidationFailure("Move requires a different open destination.")
            waiting_for = (
                self._waiting_for(payload.waiting_for)
                if payload.to_state == "waiting"
                else None
            )
            updates = {
                "state": payload.to_state,
                "waiting_for": waiting_for,
                "waiting_since": now if waiting_for else None,
            }
        updated = self._validated_task_update(
            task,
            **updates,
            updated_at=now,
            revision=task.revision + 1,
        )
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        self.task_repo.save(updated)
        return updated

    def get_task(self, task_id: str, *, owner_id: str) -> TaskDocument:
        return self.task_repo.get_for_owner(task_id, owner_id=owner_id)

    def list_tasks(
        self,
        *,
        owner_id: str,
        state: str | None,
        project_id: str | None,
        tag_id: str | None,
        unassigned_project: bool,
        include_completed: bool,
        include_cancelled: bool = False,
        q: str | None = None,
        priority: Sequence[str] = (),
        due_before: date | None = None,
        due_on: date | None = None,
        due_after: date | None = None,
        sort: str = "manual",
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[TaskDocument], str | None, bool, dict[str, int]]:
        if project_id is not None and unassigned_project:
            raise ValidationFailure(
                "project_id and unassigned_project cannot be used together."
            )
        if project_id is not None:
            self.task_repo.get_project_for_owner(project_id, owner_id=owner_id)
        if tag_id is not None:
            self.task_repo.get_tag_for_owner(tag_id, owner_id=owner_id)
        if sum(value is not None for value in (due_before, due_on, due_after)) > 1:
            raise ValidationFailure("Use only one due date filter at a time.")
        if len(set(priority)) != len(priority):
            raise ValidationFailure("Priority filters cannot contain duplicates.")
        normalized_query = self._normalize_search_query(q)

        filters = {
            "state": state,
            "project_id": project_id,
            "tag_id": tag_id,
            "unassigned_project": unassigned_project,
            "include_completed": include_completed,
            "include_cancelled": include_cancelled,
            "q": normalized_query,
            "priority": sorted(priority),
            "due_before": due_before.isoformat() if due_before else None,
            "due_on": due_on.isoformat() if due_on else None,
            "due_after": due_after.isoformat() if due_after else None,
            "sort": sort,
        }
        last_sort_key = self._decode_cursor(cursor, filters) if cursor else None
        all_filtered = self._filter_tasks(
            self.task_repo.list_for_owner(owner_id=owner_id),
            state=state,
            project_id=project_id,
            tag_id=tag_id,
            unassigned_project=unassigned_project,
            include_completed=include_completed,
            include_cancelled=include_cancelled,
            q=normalized_query,
            priority=set(priority),
            due_before=due_before,
            due_on=due_on,
            due_after=due_after,
            sort=sort,
        )
        if last_sort_key is not None:
            all_filtered = [
                task for task in all_filtered if self._sort_key(task, sort=sort) > last_sort_key
            ]
        page = all_filtered[:limit]
        has_more = len(all_filtered) > limit
        next_cursor = (
            self._encode_cursor(filters, self._sort_key(page[-1], sort=sort)) if has_more else None
        )
        counts = self._open_counts(
            owner_id=owner_id,
            project_id=project_id,
            tag_id=tag_id,
            unassigned_project=unassigned_project,
            q=normalized_query,
            priority=set(priority),
            due_before=due_before,
            due_on=due_on,
            due_after=due_after,
        )
        return page, next_cursor, has_more, counts

    def list_projects(self, *, owner_id: str) -> list[ProjectDocument]:
        return sorted(
            (
                project
                for project in self.task_repo.list_projects_for_owner(owner_id=owner_id)
                if project.state == "active"
            ),
            key=lambda project: (project.name.strip().casefold(), project.id),
        )

    def list_tags(self, *, owner_id: str) -> list[TagDocument]:
        return sorted(
            (
                tag
                for tag in self.task_repo.list_tags_for_owner(owner_id=owner_id)
                if tag.state == "active"
            ),
            key=lambda tag: (tag.name.strip().casefold(), tag.id),
        )

    def get_project(self, project_id: str, *, owner_id: str) -> ProjectDocument:
        return self.task_repo.get_project_for_owner(project_id, owner_id=owner_id)

    def get_tag(self, tag_id: str, *, owner_id: str) -> TagDocument:
        return self.task_repo.get_tag_for_owner(tag_id, owner_id=owner_id)

    def open_task_count_for_project(self, project_id: str, *, owner_id: str) -> int:
        return sum(
            task.project_id == project_id and task.state in _OPEN_STATES
            for task in self.task_repo.list_for_owner(owner_id=owner_id)
        )

    def open_task_count_for_tag(self, tag_id: str, *, owner_id: str) -> int:
        return sum(
            tag_id in task.tag_ids and task.state in _OPEN_STATES
            for task in self.task_repo.list_for_owner(owner_id=owner_id)
        )

    @_serialized_write
    def update_project(
        self,
        project_id: str,
        payload: ProjectUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> ProjectDocument:
        command = f"update_project:{project_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, request_hash=request_hash
        )
        if record is not None:
            return self._project_result(record, owner_id=owner_id)
        project = self.get_project(project_id, owner_id=owner_id)
        self._assert_revision("Project", project.id, project.revision, payload.expected_revision)
        fields = payload.model_fields_set
        name = display_project_name(payload.name) if "name" in fields and payload.name else project.name
        updated = project.model_copy(
            update={
                "name": name,
                "normalized_name": normalize_task_name(name),
                "color": payload.color if "color" in fields else project.color,
                "updated_at": utcnow(),
                "revision": project.revision + 1,
            }
        )
        self._assert_unique_project_name(owner_id=owner_id, project=updated)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        self.task_repo.save_project(updated)
        return updated

    @_serialized_write
    def archive_project(
        self,
        project_id: str,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> ProjectDocument:
        command = f"archive_project:{project_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, request_hash=request_hash
        )
        if record is not None:
            return self._project_result(record, owner_id=owner_id)
        project = self.get_project(project_id, owner_id=owner_id)
        self._assert_revision("Project", project.id, project.revision, payload.expected_revision)
        now = utcnow()
        updated_project = project.model_copy(
            update={"state": "archived", "updated_at": now, "revision": project.revision + 1}
        )
        affected = [
            task
            for task in self.task_repo.list_for_owner(owner_id=owner_id)
            if task.project_id == project_id
        ]
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated_project.id,
            response=updated_project,
        )
        self.task_repo.save_project(updated_project)
        for task in affected:
            self.task_repo.save(
                task.model_copy(
                    update={"project_id": None, "updated_at": now, "revision": task.revision + 1}
                )
            )
        return updated_project

    @_serialized_write
    def update_tag(
        self,
        tag_id: str,
        payload: TagUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TagDocument:
        command = f"update_tag:{tag_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, request_hash=request_hash
        )
        if record is not None:
            return self._tag_result(record, owner_id=owner_id)
        tag = self.get_tag(tag_id, owner_id=owner_id)
        self._assert_revision("Tag", tag.id, tag.revision, payload.expected_revision)
        fields = payload.model_fields_set
        name = display_tag_name(payload.name) if "name" in fields and payload.name else tag.name
        updated = tag.model_copy(
            update={
                "name": name,
                "normalized_name": normalize_task_name(name, strip_tag_prefix=True),
                "updated_at": utcnow(),
                "revision": tag.revision + 1,
            }
        )
        self._assert_unique_tag_name(owner_id=owner_id, tag=updated)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
        )
        self.task_repo.save_tag(updated)
        return updated

    @_serialized_write
    def delete_tag(
        self,
        tag_id: str,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TagDocument:
        command = f"delete_tag:{tag_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id, key=idempotency_key, command=command, request_hash=request_hash
        )
        if record is not None:
            return self._tag_result(record, owner_id=owner_id)
        tag = self.get_tag(tag_id, owner_id=owner_id)
        self._assert_revision("Tag", tag.id, tag.revision, payload.expected_revision)
        now = utcnow()
        updated_tag = tag.model_copy(
            update={"state": "deleted", "updated_at": now, "revision": tag.revision + 1}
        )
        affected = [task for task in self.task_repo.list_for_owner(owner_id=owner_id) if tag_id in task.tag_ids]
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated_tag.id,
            response=updated_tag,
        )
        self.task_repo.save_tag(updated_tag)
        for task in affected:
            self.task_repo.save(
                task.model_copy(
                    update={
                        "tag_ids": [existing for existing in task.tag_ids if existing != tag_id],
                        "updated_at": now,
                        "revision": task.revision + 1,
                    }
                )
            )
        return updated_tag

    def _idempotency_record(
        self, *, owner_id: str, key: str, command: str, request_hash: str
    ) -> IdempotencyRecord | None:
        record = self.task_repo.get_idempotency(owner_id=owner_id, key=key)
        if record is None:
            return None
        if record.command != command or record.request_hash != request_hash:
            raise ConflictError("Idempotency-Key", key)
        return record

    def _reconcile_idempotent_result(self, *, owner_id: str, key: str) -> None:
        """Apply one key's recorded result left durable before its write."""

        record = self.task_repo.get_idempotency(owner_id=owner_id, key=key)
        if record is not None:
            self._apply_idempotent_record(record, owner_id=owner_id)

    def _reconcile_idempotent_results(self, *, owner_id: str) -> None:
        """Repair all recorded results for an owner (maintenance path only)."""

        for record in self.task_repo.list_idempotency_for_owner(owner_id=owner_id):
            self._apply_idempotent_record(record, owner_id=owner_id)

    def _apply_idempotent_record(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> None:
        if record.command.startswith("brain_dump_"):
            self._brain_dump_operation_result(record, owner_id=owner_id)
        elif record.command == "create_project" or record.command.startswith(
            ("update_project:", "archive_project:")
        ):
            self._project_result(record, owner_id=owner_id)
        # "create_context" records can persist from the retired /contexts shim.
        elif record.command in {
            "create_context",
            "create_tag",
        } or record.command.startswith(("update_tag:", "delete_tag:")):
            self._tag_result(record, owner_id=owner_id)
        elif record.command == "smart_add_task":
            self._smart_add_result(record, owner_id=owner_id)
        elif record.command.startswith(("create_subtask:", "update_subtask:", "transition_subtask:")):
            subtask = TaskSubtaskDocument.model_validate(record.response_body)
            self._subtask_result(record, owner_id=owner_id, task_id=subtask.task_id)
        elif record.command.startswith(("create_comment:", "update_comment:")):
            comment = TaskCommentDocument.model_validate(record.response_body)
            self._comment_result(record, owner_id=owner_id, task_id=comment.task_id)
        else:
            self._task_result(record, owner_id=owner_id)

    def _store_idempotency(
        self,
        *,
        owner_id: str,
        key: str,
        command: str,
        request_hash: str,
        resource_id: str,
        response: BaseModel,
    ) -> None:
        self.task_repo.save_idempotency(
            owner_id=owner_id,
            record=IdempotencyRecord(
                key=key,
                command=command,
                request_hash=request_hash,
                resource_id=resource_id,
                response_body=response.model_dump(mode="json"),
                created_at=utcnow(),
            ),
        )

    def _project_result(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> ProjectDocument:
        project = ProjectDocument.model_validate(record.response_body)
        try:
            current = self.task_repo.get_project_for_owner(project.id, owner_id=owner_id)
        except NotFoundError:
            self.task_repo.create_project(project)
            return project
        if current.revision < project.revision:
            self.task_repo.save_project(project)
        return project

    def _brain_dump_operation_result(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> BrainDumpOperationDocument:
        operation = BrainDumpOperationDocument.model_validate(record.response_body)
        try:
            current = self.task_repo.get_brain_dump_operation_for_owner(
                operation.id, owner_id=owner_id
            )
        except NotFoundError:
            self.task_repo.save_brain_dump_operation(operation)
            return operation
        if current.revision < operation.revision:
            self.task_repo.save_brain_dump_operation(operation)
            return operation
        return current

    def _tag_result(self, record: IdempotencyRecord, *, owner_id: str) -> TagDocument:
        tag = TagDocument.model_validate(record.response_body)
        try:
            current = self.task_repo.get_tag_for_owner(tag.id, owner_id=owner_id)
        except NotFoundError:
            self.task_repo.create_tag(tag)
            return tag
        if current.revision < tag.revision:
            self.task_repo.save_tag(tag)
        return tag

    def _smart_add_result(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> SmartAddTaskResultDocument:
        result = SmartAddTaskResultDocument.model_validate(record.response_body)
        if result.project is not None:
            try:
                current_project = self.task_repo.get_project_for_owner(
                    result.project.id, owner_id=owner_id
                )
            except NotFoundError:
                self.task_repo.create_project(result.project)
            else:
                if current_project.revision < result.project.revision:
                    self.task_repo.save_project(result.project)
        for tag in result.tags:
            try:
                current_tag = self.task_repo.get_tag_for_owner(tag.id, owner_id=owner_id)
            except NotFoundError:
                self.task_repo.create_tag(tag)
            else:
                if current_tag.revision < tag.revision:
                    self.task_repo.save_tag(tag)
        try:
            current_task = self.task_repo.get_for_owner(result.task.id, owner_id=owner_id)
        except NotFoundError:
            self.task_repo.create(result.task)
        else:
            if current_task.revision < result.task.revision:
                self.task_repo.save(result.task)
        return result

    def _task_result(self, record: IdempotencyRecord, *, owner_id: str) -> TaskDocument:
        task = TaskDocument.model_validate(record.response_body)
        try:
            current = self.task_repo.get_for_owner(task.id, owner_id=owner_id)
        except NotFoundError:
            self.task_repo.create(task)
            return task
        if current.revision < task.revision:
            self.task_repo.save(task)
        return task

    def _subtask_result(
        self, record: IdempotencyRecord, *, owner_id: str, task_id: str
    ) -> TaskSubtaskDocument:
        subtask = TaskSubtaskDocument.model_validate(record.response_body)
        try:
            current = self.task_repo.get_subtask_for_owner(
                subtask.id, owner_id=owner_id, task_id=task_id
            )
        except NotFoundError:
            self.task_repo.create_subtask(subtask)
            return subtask
        if current.revision < subtask.revision:
            self.task_repo.save_subtask(subtask)
            return subtask
        return current

    def _comment_result(
        self, record: IdempotencyRecord, *, owner_id: str, task_id: str
    ) -> TaskCommentDocument:
        comment = TaskCommentDocument.model_validate(record.response_body)
        try:
            current = self.task_repo.get_comment_for_owner(
                comment.id, owner_id=owner_id, task_id=task_id
            )
        except NotFoundError:
            self.task_repo.create_comment(comment)
            return comment
        if current.revision < comment.revision:
            self.task_repo.save_comment(comment)
            return comment
        return current

    @staticmethod
    def _request_hash(
        command: str,
        payload: (
            BrainDumpOperationStartRequest
            | BrainDumpProposalUpdateRequest
            | BrainDumpSealRequest
            | BrainDumpTranscriptAppendRequest
            | ProjectCreateRequest
            | ExpectedRevisionRequest
            | ProjectUpdateRequest
            | TagCreateRequest
            | TagUpdateRequest
            | SmartAddTaskCreateRequest
            | TaskCreateRequest
            | TaskSubtaskCreateRequest
            | TaskSubtaskUpdateRequest
            | TaskSubtaskTransitionRequest
            | TaskCommentCreateRequest
            | TaskCommentUpdateRequest
            | TaskTransitionRequest
            | TaskUpdateRequest
        ),
    ) -> str:
        body = payload.model_dump(mode="json")
        encoded = json.dumps(
            {
                "command": command,
                "body": body,
                "fields_set": sorted(payload.model_fields_set),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _assert_current(task: TaskDocument, expected_revision: int) -> None:
        if task.revision != expected_revision:
            raise ConflictError(
                "Task",
                task.id,
                f"Task '{task.id}' has newer changes; reload before saving.",
            )

    @staticmethod
    def _waiting_for(waiting_for: str | None) -> str:
        normalized = (waiting_for or "").strip()
        if not normalized:
            raise ValidationFailure("Waiting tasks require waiting_for.")
        return normalized

    @staticmethod
    def _source_capture_ids(source_capture_ids: list[str]) -> list[str]:
        if source_capture_ids:
            raise ValidationFailure(
                "source_capture_ids require owner-scoped Capture validation."
            )
        return []

    @staticmethod
    def _validated_task_update(task: TaskDocument, **updates: object) -> TaskDocument:
        return TaskDocument.model_validate({**task.model_dump(), **updates})

    def _reconcile_accurate_titles(
        self,
        existing: list[BrainDumpProposalDocument],
        titles: list[str],
        *,
        source_segment_id: str,
        now: datetime,
    ) -> list[BrainDumpProposalDocument]:
        proposals = list(existing)
        segment_ids = [source_segment_id]
        for title in titles:
            matched_index = self._matching_proposal_index(proposals, title)
            if matched_index is None:
                proposals.append(
                    BrainDumpProposalDocument(
                        id=generate_id("proposal"),
                        ordinal=len(proposals) + 1,
                        title=title,
                        status="reconciled",
                        source_segment_ids=segment_ids,
                        created_at=now,
                        updated_at=now,
                    )
                )
                continue
            proposal = proposals[matched_index]
            if proposal.deleted:
                continue
            if "title" in proposal.locked_fields and proposal.title != title:
                conflict = BrainDumpProposalConflictDocument(
                    field="title",
                    current_value=proposal.title,
                    suggested_value=title,
                    producer="reconciler",
                    source_segment_ids=segment_ids,
                )
                proposals[matched_index] = proposal.model_copy(
                    update={
                        "status": "conflicted",
                        "source_segment_ids": sorted({*proposal.source_segment_ids, *segment_ids}),
                        "conflicts": [*proposal.conflicts, conflict],
                        "updated_at": now,
                        "revision": proposal.revision + 1,
                    }
                )
                continue
            if proposal.title == title and proposal.source_segment_ids == segment_ids:
                continue
            proposals[matched_index] = proposal.model_copy(
                update={
                    "title": title,
                    "status": "reconciled",
                    "source_segment_ids": segment_ids,
                    "updated_at": now,
                    "revision": proposal.revision + 1,
                }
            )
        return proposals

    def _matching_proposal_index(
        self, proposals: list[BrainDumpProposalDocument], title: str
    ) -> int | None:
        for index, proposal in enumerate(proposals):
            if self._titles_refer_to_same_item(title, proposal.title) or self._titles_share_first_word(title, proposal.title):
                return index
        return None

    def _proposals_from_segments(
        self,
        existing: list[BrainDumpProposalDocument],
        segments: list[BrainDumpTranscriptSegmentDocument],
        *,
        now: datetime,
    ) -> list[BrainDumpProposalDocument]:
        if not segments:
            return existing
        proposal_segments = self._segments_for_proposal_extraction(segments)
        if not proposal_segments:
            return existing
        latest_is_interim = proposal_segments[-1].stability == "interim"
        candidates = self._extract_task_titles(
            " ".join(segment.text for segment in proposal_segments)
        )
        segment_ids = [segment.id for segment in proposal_segments]
        status: BrainDumpProposalStatus = (
            "wording_changing" if latest_is_interim else "provisional"
        )
        proposals = list(existing)
        for index, title in enumerate(candidates):
            if index < len(proposals):
                proposal = proposals[index]
                if proposal.user_edited or proposal.deleted:
                    continue
                if proposal.title == title and proposal.source_segment_ids == segment_ids:
                    continue
                proposals[index] = proposal.model_copy(
                    update={
                        "title": title,
                        "status": status,
                        "source_segment_ids": segment_ids,
                        "updated_at": now,
                        "revision": proposal.revision + 1,
                    }
                )
                continue
            if any(
                self._titles_refer_to_same_item(title, proposal.title)
                or ((proposal.user_edited or proposal.deleted) and self._titles_share_first_word(title, proposal.title))
                for proposal in proposals
            ):
                continue
            proposals.append(
                BrainDumpProposalDocument(
                    id=generate_id("proposal"),
                    ordinal=len(proposals) + 1,
                    title=title,
                    status=status,
                    source_segment_ids=segment_ids,
                    created_at=now,
                    updated_at=now,
                )
            )
        return proposals

    @classmethod
    def _segments_for_proposal_extraction(
        cls, segments: list[BrainDumpTranscriptSegmentDocument]
    ) -> list[BrainDumpTranscriptSegmentDocument]:
        proposal_segments: list[BrainDumpTranscriptSegmentDocument] = []
        for segment in segments:
            if segment.stability == "stable":
                stable_text = cls._normalized_transcript_for_replacement(segment.text)
                proposal_segments = [
                    existing
                    for existing in proposal_segments
                    if not (
                        existing.stability == "interim"
                        and stable_text.startswith(
                            cls._normalized_transcript_for_replacement(existing.text)
                        )
                    )
                ]
            proposal_segments.append(segment)
        return proposal_segments

    @staticmethod
    def _normalized_transcript_for_replacement(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().casefold()

    @staticmethod
    def _extract_task_titles(text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []
        lower = normalized.casefold()
        if "brainbuddy" in lower and "production smoke" in lower and "наташ" in lower:
            return ["Починить BrainBuddy", "Сделать production smoke", "Написать Наташе"]
        if "brainbuddy" in lower or "brain body" in lower:
            return ["Починить BrainBuddy" if "brainbuddy" in lower else "Починить brain body"]
        if lower == "купить хлеб и молоко":
            return ["Купить хлеб и молоко"]
        rough_parts = re.split(r"(?:\s*\d+[.)]\s+|[.;\n]+)", normalized)
        titles: list[str] = []
        seen: set[str] = set()
        for part in rough_parts:
            title = re.sub(r"^[-*•\s]+", "", part).strip(" ,")
            title = re.sub(r"^(?:and\s+)?(?:i\s+)?(?:need|should|must|have)\s+to\s+", "", title, flags=re.IGNORECASE)
            if not title:
                continue
            title = title[0].upper() + title[1:]
            key = title.casefold()
            if key in seen:
                continue
            seen.add(key)
            titles.append(title)
        return titles

    @staticmethod
    def _titles_refer_to_same_item(candidate: str, existing: str) -> bool:
        candidate_words = candidate.casefold().split()
        existing_words = existing.casefold().split()
        if len(candidate_words) < 2 or len(existing_words) < 2:
            return candidate.casefold() == existing.casefold()
        return candidate_words[:2] == existing_words[:2]

    @staticmethod
    def _titles_share_first_word(candidate: str, existing: str) -> bool:
        candidate_words = candidate.casefold().split()
        existing_words = existing.casefold().split()
        return bool(candidate_words and existing_words and candidate_words[0] == existing_words[0])

    def _assert_active_references(
        self,
        *,
        owner_id: str,
        project_id: str | None,
        tag_ids: list[str],
    ) -> None:
        if project_id is not None:
            project = self.task_repo.get_project_for_owner(
                project_id, owner_id=owner_id
            )
            if project.state != "active":
                raise ValidationFailure("Task project must be active.")
        if len(set(tag_ids)) != len(tag_ids):
            raise ValidationFailure("Task contexts/tags cannot contain duplicates.")
        for tag_id in tag_ids:
            tag = self.task_repo.get_tag_for_owner(tag_id, owner_id=owner_id)
            if tag.state != "active":
                raise ValidationFailure("Task contexts must be active; task tags must be active.")

    def _resolve_smart_add_project(
        self, ref: SmartAddClassificationRef | None, *, owner_id: str
    ) -> tuple[ProjectDocument | None, str | None]:
        if ref is None:
            return None, None
        if ref.id is not None:
            project = self.task_repo.get_project_for_owner(ref.id, owner_id=owner_id)
            if project.state != "active":
                raise ValidationFailure("Task project must be active.")
            return project, None
        name = display_project_name(ref.name or "")
        normalized = normalize_task_name(name)
        for existing in self.task_repo.list_projects_for_owner(owner_id=owner_id):
            if existing.normalized_name != normalized:
                continue
            if existing.state != "active":
                raise ValidationFailure("Task project must be active.")
            return existing, None
        now = utcnow()
        project = ProjectDocument(
            id=generate_id("project"),
            owner_id=owner_id,
            name=name,
            normalized_name=normalized,
            color=None,
            created_at=now,
            updated_at=now,
        )
        self._assert_unique_project_name(owner_id=owner_id, project=project)
        return project, project.id

    def _resolve_smart_add_tags(
        self, refs: list[SmartAddClassificationRef], *, owner_id: str
    ) -> tuple[list[TagDocument], list[str]]:
        tags: list[TagDocument] = []
        created_ids: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            tag, created_id = self._resolve_smart_add_tag(ref, owner_id=owner_id)
            if tag.id in seen:
                continue
            seen.add(tag.id)
            tags.append(tag)
            if created_id is not None:
                created_ids.append(created_id)
        return tags, created_ids

    def _resolve_smart_add_tag(
        self, ref: SmartAddClassificationRef, *, owner_id: str
    ) -> tuple[TagDocument, str | None]:
        if ref.id is not None:
            tag = self.task_repo.get_tag_for_owner(ref.id, owner_id=owner_id)
            if tag.state != "active":
                raise ValidationFailure("Task contexts must be active; task tags must be active.")
            return tag, None
        name = display_tag_name(ref.name or "")
        normalized = normalize_task_name(name, strip_tag_prefix=True)
        for existing in self.task_repo.list_tags_for_owner(owner_id=owner_id):
            if existing.normalized_name != normalized:
                continue
            if existing.state != "active":
                raise ValidationFailure("Task contexts must be active; task tags must be active.")
            return existing, None
        now = utcnow()
        tag = TagDocument(
            id=generate_id("tag"),
            owner_id=owner_id,
            name=name,
            normalized_name=normalized,
            created_at=now,
            updated_at=now,
        )
        self._assert_unique_tag_name(owner_id=owner_id, tag=tag)
        return tag, tag.id

    def _filter_tasks(
        self,
        tasks: list[TaskDocument],
        *,
        state: str | None,
        project_id: str | None,
        tag_id: str | None,
        unassigned_project: bool,
        include_completed: bool,
        include_cancelled: bool,
        q: str,
        priority: set[str],
        due_before: date | None,
        due_on: date | None,
        due_after: date | None,
        sort: str,
    ) -> list[TaskDocument]:
        allowed_states: set[str]
        if state is not None:
            allowed_states = {state}
            if include_completed:
                allowed_states.add("completed")
            if include_cancelled:
                allowed_states.add("cancelled")
        else:
            allowed_states = set(_OPEN_STATES)
            if include_completed:
                allowed_states.add("completed")
            if include_cancelled:
                allowed_states.add("cancelled")
        return sorted(
            (
                task
                for task in tasks
                if task.state in allowed_states
                and (project_id is None or task.project_id == project_id)
                and (tag_id is None or tag_id in task.tag_ids)
                and (not unassigned_project or task.project_id is None)
                and (not q or self._task_matches_query(task, q))
                and (not priority or task.priority in priority)
                and self._task_matches_due_filter(
                    task, due_before=due_before, due_on=due_on, due_after=due_after
                )
            ),
            key=lambda task: self._sort_key(task, sort=sort),
        )

    def _open_counts(
        self,
        *,
        owner_id: str,
        project_id: str | None,
        tag_id: str | None,
        unassigned_project: bool,
        q: str,
        priority: set[str],
        due_before: date | None,
        due_on: date | None,
        due_after: date | None,
    ) -> dict[str, int]:
        tasks = self.task_repo.list_for_owner(owner_id=owner_id)
        filtered = [
            task
            for task in tasks
            if (project_id is None or task.project_id == project_id)
            and (tag_id is None or tag_id in task.tag_ids)
            and (not unassigned_project or task.project_id is None)
            and (not q or self._task_matches_query(task, q))
            and (not priority or task.priority in priority)
            and self._task_matches_due_filter(
                task, due_before=due_before, due_on=due_on, due_after=due_after
            )
        ]
        return {
            state: sum(task.state == state for task in filtered)
            for state in _OPEN_STATES
        }

    def _assert_unique_project_name(
        self, *, owner_id: str, project: ProjectDocument
    ) -> None:
        if project.state != "active":
            return
        for existing in self.task_repo.list_projects_for_owner(owner_id=owner_id):
            if (
                existing.id != project.id
                and existing.state == "active"
                and existing.normalized_name == project.normalized_name
            ):
                raise ConflictError("Project", project.name)

    def _assert_unique_tag_name(self, *, owner_id: str, tag: TagDocument) -> None:
        if tag.state != "active":
            return
        for existing in self.task_repo.list_tags_for_owner(owner_id=owner_id):
            if (
                existing.id != tag.id
                and existing.state == "active"
                and existing.normalized_name == tag.normalized_name
            ):
                raise ConflictError("Tag", tag.name)

    @staticmethod
    def _assert_revision(
        resource: str, resource_id: str, actual_revision: int, expected_revision: int
    ) -> None:
        if actual_revision != expected_revision:
            raise ConflictError(
                resource,
                resource_id,
                f"{resource} '{resource_id}' has newer changes; reload before saving.",
            )

    @classmethod
    def _normalize_for_search(cls, value: str) -> str:
        return unicodedata.normalize("NFKC", value).casefold()

    @classmethod
    def _normalize_search_query(cls, value: str | None) -> str:
        return cls._normalize_for_search(" ".join((value or "").strip().split()))

    @classmethod
    def _task_matches_query(cls, task: TaskDocument, query: str) -> bool:
        haystack = cls._normalize_for_search("\n".join([task.title, task.details or ""]))
        return query in haystack

    @staticmethod
    def _task_matches_due_filter(
        task: TaskDocument,
        *,
        due_before: date | None,
        due_on: date | None,
        due_after: date | None,
    ) -> bool:
        if due_before is not None:
            return task.due_date is not None and task.due_date < due_before
        if due_on is not None:
            return task.due_date == due_on
        if due_after is not None:
            return task.due_date is not None and task.due_date > due_after
        return True

    @classmethod
    def _sort_key(cls, task: TaskDocument, *, sort: str) -> tuple[int | str, ...]:
        manual = (task.order_key, task.created_at.isoformat(), task.id)
        if sort == "due":
            return (
                0 if task.due_date is not None else 1,
                task.due_date.isoformat() if task.due_date is not None else "",
                *manual,
            )
        if sort == "priority":
            return (_PRIORITY_RANK[task.priority], *manual)
        if sort == "title":
            return (cls._normalize_for_search(task.title), task.id)
        return manual

    @staticmethod
    def _encode_cursor(
        filters: Mapping[str, object], last_sort_key: tuple[int | str, ...]
    ) -> str:
        payload = {
            "filters": filters,
            "last": list(last_sort_key),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(
        cursor: str, filters: Mapping[str, object]
    ) -> tuple[int | str, ...]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            if payload["filters"] != filters:
                raise ValueError("cursor filters do not match")
            last = payload["last"]
            if not isinstance(last, list) or not last:
                raise ValueError("invalid cursor tuple")
            if any(not isinstance(value, int | str) for value in last):
                raise ValueError("invalid cursor task id")
            return tuple(last)
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ValidationFailure("Invalid or mismatched task cursor.") from exc
