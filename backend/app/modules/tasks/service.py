"""Application service for owner-scoped native GTD tasks."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Concatenate, Literal, ParamSpec, TypeVar, cast

from pydantic import BaseModel

from app.exceptions import (
    ConflictError,
    NotFoundError,
    ProviderRetryableError,
    ProviderTerminalError,
    ValidationFailure,
)
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
from app.workflows.voice_brain_dump.confirmation import confirm_native_inbox_actions
from app.workflows.voice_brain_dump.domain import (
    ProposalConflict,
    ProposalPatch,
    ReconciledProposal,
    TranscriptHypothesis,
    apply_proposal_patches,
)
from app.workflows.voice_brain_dump.providers import (
    AccurateSttPort,
    AccurateSttRequest,
    DeterministicTextReconciler,
    DisabledAccurateStt,
    ReconcileTextRequest,
    TextReconcilerPort,
)
from app.workflows.voice_brain_dump.task_port import InProcessTaskPort, TaskPort

from .domain import (
    BrainDumpActionReceiptDocument,
    BrainDumpAudioChunkDocument,
    BrainDumpConsent,
    BrainDumpOperationDocument,
    BrainDumpProposalConflictDocument,
    BrainDumpProposalDocument,
    BrainDumpProposalPatchDocument,
    BrainDumpProposalStatus,
    BrainDumpProviderRunDocument,
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

    def __init__(
        self,
        task_repo: TaskRepository,
        *,
        accurate_stt: AccurateSttPort | None = None,
        text_reconciler: TextReconcilerPort | None = None,
        raw_audio_retention: timedelta = timedelta(days=1),
        working_artifacts_retention: timedelta = timedelta(days=7),
        max_operation_recoveries: int = 2,
        max_cumulative_cost_usd_per_operation: float = 1.00,
        provider_run_lease_seconds: float = 30.0,
        allowed_external_provider_categories: frozenset[str] | None = None,
        task_port: TaskPort | None = None,
    ) -> None:
        self.task_repo = task_repo
        self.accurate_stt = accurate_stt or DisabledAccurateStt()
        self.text_reconciler = text_reconciler or DeterministicTextReconciler()
        self.raw_audio_retention = raw_audio_retention
        self.working_artifacts_retention = working_artifacts_retention
        self.max_operation_recoveries = max_operation_recoveries
        self.max_cumulative_cost_usd_per_operation = (
            max_cumulative_cost_usd_per_operation
        )
        self.provider_run_lease_seconds = provider_run_lease_seconds
        # Voice confirmation crosses the Tasks boundary through this narrow
        # application-workflow port (ADR-0001), never by treating this Tasks
        # service as its own adapter. The default binds only the one
        # canonical Tasks command the port needs; the production container
        # wires the same adapter explicitly, and callers may inject another
        # conforming adapter in tests.
        self.task_port: TaskPort = task_port or InProcessTaskPort(
            self.create_native_inbox_task
        )
        # Consent identifies a configured provider category before bytes can
        # leave the device. The production container supplies this from
        # configuration; the default keeps isolated deterministic tests honest
        # without treating arbitrary caller text as a provider identity.
        self.allowed_external_provider_categories = (
            frozenset({"openai"})
            if allowed_external_provider_categories is None
            else allowed_external_provider_categories
        )

    def _assert_external_provider_consent(self, consent: BrainDumpConsent) -> None:
        if not consent.external_processing_allowed:
            raise ValidationFailure(
                "AUDIO_UPLOAD_CONSENT_REQUIRED: external processing consent is "
                "required before audio may leave the device."
            )
        if (
            not consent.provider
            or consent.provider not in self.allowed_external_provider_categories
        ):
            raise ValidationFailure(
                "AUDIO_UPLOAD_PROVIDER_CONSENT_REQUIRED: external processing "
                "consent must name a configured provider category before audio "
                "may leave the device."
            )

    # Only a terminal operation's raw audio/working artifacts are ever
    # eligible for retention-window purge. Every other status -- including
    # the full active pipeline and a still-retryable failure -- must never
    # be purged out from under it, no matter how old it looks: purging an
    # in-progress or recoverable operation would destroy data a resume/retry
    # still needs, not merely "abandoned" work.
    _TERMINAL_PURGE_ELIGIBLE_STATUSES = frozenset({"completed", "cancelled", "terminal_error"})

    # Every fixed, safe code an adapter/port or this service ever raises as
    # a ``ProviderRetryableError``/``ProviderTerminalError``/
    # ``ValidationFailure`` message. Only a code in this set may ever reach
    # a persisted ``ProviderRun``/API response; anything else -- a
    # third-party exception's text, an interpolated dynamic value (e.g. a
    # deterministic test adapter embedding a media reference), or any other
    # provider/model message -- is replaced by a generic fallback code
    # rather than stored or returned verbatim.
    _ALLOWLISTED_PROVIDER_ERROR_CODES = frozenset(
        {
            "STT_AUDIO_FORMAT_UNSUPPORTED",
            "STT_AUDIO_MISSING",
            "STT_COST_LIMIT_EXCEEDED",
            "STT_PROVIDER_UNAVAILABLE",
            "STT_PROVIDER_AUTHENTICATION_FAILED",
            "STT_AUDIO_TOO_LARGE",
            "STT_PROVIDER_REJECTED_REQUEST",
            "STT_PROVIDER_DISABLED",
            "STT_PROVIDER_CREDENTIALS_MISSING",
            "STT_DETERMINISTIC_PROVIDER_TEST_ONLY",
            "STT_PROVIDER_UNSUPPORTED",
            "STT_EXTERNAL_PROCESSING_CONSENT_REQUIRED",
            "STT_CONSENT_PROVIDER_MISMATCH",
            "DETERMINISTIC_STT_FIXTURE_MISSING",
            "RECONCILER_PROVIDER_DISABLED",
            "RECONCILER_COST_LIMIT_EXCEEDED",
            "RECONCILER_INVALID_RESPONSE",
            "RECONCILER_PROVIDER_RETRYABLE",
            "RECONCILER_PROVIDER_REJECTED",
            "RECONCILER_CONSENT_REQUIRED",
            "RECONCILER_CONSENT_PROVIDER_MISMATCH",
            "OPERATION_COST_BUDGET_EXCEEDED",
            "OPERATION_RECOVERY_BUDGET_EXHAUSTED",
            "CONSENT_WITHDRAWN",
        }
    )
    _PROVIDER_ERROR_FALLBACK_CODE = "PROVIDER_ERROR_UNSPECIFIED"

    @classmethod
    def _redact_provider_error(cls, raw: str) -> str:
        """Map a raw provider/exception message to a safe, allowlisted code.

        ``raw`` is only ever persisted/returned as-is when it is *exactly*
        one of the fixed codes this codebase raises; anything else falls
        back to a generic code rather than leaking arbitrary text.
        """

        return (
            raw
            if raw in cls._ALLOWLISTED_PROVIDER_ERROR_CODES
            else cls._PROVIDER_ERROR_FALLBACK_CODE
        )

    def purge_expired_raw_audio(self, *, now: datetime | None = None) -> int:
        """Purge raw audio past its reconciliation-anchored privacy deadline.

        The clock is ``raw_audio_expires_at`` — stamped once, at successful
        reconciliation, to ``reconciled_at + raw_audio_retention`` — never a
        later ``updated_at``. A proposal edit, consent withdrawal, or any
        other post-reconciliation mutation must not push this deadline out.
        Active transcript/proposal review artifacts are independent and are
        never removed here. Audio is deferred only while a provider run is
        pending/running and may still need the bytes.
        """

        current_time = now or utcnow()
        purged = 0
        for candidate in self.task_repo.list_expired_raw_audio_operations():
            with self.task_repo.command_lock(candidate.owner_id):
                operation = self.get_brain_dump_operation(
                    candidate.id, owner_id=candidate.owner_id
                )
                if (
                    operation.raw_audio_expires_at is None
                    and operation.status not in self._TERMINAL_PURGE_ELIGIBLE_STATUSES
                ):
                    continue
                expires_at = (
                    operation.raw_audio_expires_at
                    or operation.updated_at + self.raw_audio_retention
                )
                provider_run_is_in_flight = bool(
                    operation.provider_runs
                    and operation.provider_runs[-1].status in {"pending", "running"}
                )
                if (
                    current_time < expires_at
                    or not operation.audio_chunks
                    or provider_run_is_in_flight
                ):
                    continue
                self.task_repo.delete_brain_dump_audio_chunks(
                    owner_id=operation.owner_id,
                    operation_id=operation.id,
                    chunks=[
                        (chunk.chunk_number, chunk.sha256)
                        for chunk in operation.audio_chunks
                    ],
                )
                self.task_repo.save_brain_dump_operation(
                    operation.model_copy(
                        update={
                            "audio_chunks": [],
                            "media_ref": None,
                            "sealed_manifest_hash": None,
                            "updated_at": current_time,
                            "revision": operation.revision + 1,
                        }
                    )
                )
                purged += 1
        purged += self.task_repo.purge_brain_dump_media_orphans()
        return purged

    def purge_expired_working_artifacts(self, *, now: datetime | None = None) -> int:
        """Purge uncommitted transcript/proposal working data past retention.

        This only ever fires for a terminal operation (``completed``/
        ``cancelled``/``terminal_error``); every active status -- recording,
        paused, sealing, fast_processing, accurate_transcribing,
        reconciling, awaiting_confirmation, committing -- and the
        recoverable ``retryable_error`` status are never purged, regardless
        of age: purging an in-progress or still-retryable operation would
        destroy data a resume/retry still needs.

        A completed/cancelled/terminal-error operation's raw
        transcript/proposal working data stays available for the full
        configured retention window counted from *that* terminal
        transition, not from when the operation was first created --
        otherwise a batch that took a long time to review and confirm could
        already be past a creation-anchored deadline the moment it
        completes, purging its lineage with no retention window at all.
        Nothing mutates a terminal operation afterward, so its own
        ``updated_at`` reliably marks that completion/cancellation instant.

        Purging never removes ``action_receipts`` or ``committed_task_ids``:
        those are the compact, immutable, ID-only audit provenance a
        completed operation keeps forever and must not depend on the raw
        ``segments``/``proposals``/``proposal_patches`` this purge clears.
        """

        current_time = now or utcnow()
        purged = 0
        for candidate in self.task_repo.list_expired_working_artifact_operations(
            before=current_time
        ):
            with self.task_repo.command_lock(candidate.owner_id):
                operation = self.get_brain_dump_operation(
                    candidate.id, owner_id=candidate.owner_id
                )
                if (
                    operation.status
                    not in self._TERMINAL_PURGE_ELIGIBLE_STATUSES
                ):
                    continue
                expires_at = (
                    operation.working_artifacts_expires_at
                    or operation.updated_at + self.working_artifacts_retention
                )
                if (
                    current_time < expires_at
                    or (
                        not operation.segments
                        and not operation.proposals
                        and not operation.proposal_patches
                    )
                ):
                    continue
                self.task_repo.save_brain_dump_operation(
                    operation.model_copy(
                        update={
                            "segments": [],
                            "proposals": [],
                            "proposal_patches": [],
                            "working_artifacts_expires_at": expires_at,
                            "updated_at": current_time,
                            "revision": operation.revision + 1,
                        }
                    )
                )
                purged += 1
        return purged

    def recover_due_provider_leases(
        self, *, now: datetime | None = None, limit: int = 50
    ) -> int:
        """Reclaim operations stuck on an expired provider-run lease.

        This is the periodic half of the persisted runner: a due/expired
        lease is recovered through the exact same owner-serialized,
        compare-and-set, finite-recovery-budget path a client-initiated
        retry uses (``retry_brain_dump_operation``'s ``recoverable_claim``
        branch) — so recovery here can never duplicate an accepted result or
        bypass the recovery budget; it only decides *when* to call retry
        instead of waiting for the owner to notice and click Retry.
        """

        current_time = now or utcnow()
        recovered = 0
        for candidate in self.task_repo.list_in_flight_provider_run_operations():
            if recovered >= limit:
                break
            last_run = candidate.provider_runs[-1] if candidate.provider_runs else None
            if (
                last_run is None
                or last_run.status != "running"
                or last_run.lease_expires_at is None
                or last_run.lease_expires_at > current_time
            ):
                continue
            try:
                self.retry_brain_dump_operation(
                    candidate.id,
                    ExpectedRevisionRequest(expected_revision=candidate.revision),
                    owner_id=candidate.owner_id,
                    idempotency_key=(
                        f"lease_recovery:{candidate.id}:{candidate.revision}"
                    ),
                )
                recovered += 1
            except (ValidationFailure, ConflictError, NotFoundError):
                # Lost the compare-and-set race to a concurrent manual retry,
                # cancel, or another sweep pass; the expected-revision check
                # inside retry_brain_dump_operation is authoritative, so
                # losing here is an expected, safe no-op, not an error.
                continue
        return recovered

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

    def create_native_inbox_task(
        self,
        *,
        owner_id: str,
        title: str,
        source_capture_ids: list[str],
        idempotency_key: str,
    ) -> TaskDocument:
        """In-process ``TaskPort`` adapter for a confirmed Brain Dump action."""

        command = "create_native_inbox_task"
        payload = TaskCreateRequest(title=title, source_capture_ids=source_capture_ids)
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._task_result(record, owner_id=owner_id)
        now = utcnow()
        task = TaskDocument(
            id=generate_id("task"),
            owner_id=owner_id,
            title=title,
            details=None,
            state="inbox",
            project_id=None,
            tag_ids=[],
            order_key=self.task_repo.next_order_key(owner_id=owner_id, state="inbox"),
            # This port receives a workflow-owned immutable action receipt,
            # not a user-supplied Capture ID; the operation/receipt owner was
            # checked by the enclosing confirmation command.
            source_capture_ids=list(source_capture_ids),
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
            order_key=self.task_repo.next_order_key(
                owner_id=owner_id, state=payload.state
            ),
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
            raise ValidationFailure(
                "Microphone consent is required to start a brain dump."
            )
        now = utcnow()
        operation = BrainDumpOperationDocument(
            id=generate_id("brain_dump"),
            owner_id=owner_id,
            status="recording",
            consent=BrainDumpConsent(
                microphone=payload.consent.microphone,
                external_processing_allowed=payload.consent.external_processing_allowed,
                provider=payload.consent.provider,
                language_hints=payload.consent.language_hints,
                vocabulary=payload.consent.vocabulary,
                recorded_at=now,
            ),
            created_at=now,
            updated_at=now,
            working_artifacts_expires_at=now + self.working_artifacts_retention,
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
                raise ValidationFailure(
                    "Audio chunks can only be uploaded while recording or paused."
                )
            self._assert_external_provider_consent(operation.consent)
            existing = {
                chunk.chunk_number: chunk for chunk in operation.audio_chunks
            }.get(chunk_number)
            if existing is not None:
                if existing.sha256 != actual_sha256 or existing.size_bytes != len(
                    content
                ):
                    raise ConflictError(
                        "Brain dump audio chunk",
                        str(chunk_number),
                        "CHUNK_CONFLICT: chunk number already has different audio.",
                    )
                chunk_path = self.task_repo.brain_dump_audio_chunk_path(
                    owner_id, operation_id, chunk_number, actual_sha256
                )
                if not chunk_path.exists():
                    self.task_repo.save_brain_dump_audio_chunk(
                        owner_id=owner_id,
                        operation_id=operation_id,
                        chunk_number=chunk_number,
                        sha256=actual_sha256,
                        content=content,
                    )
                return operation
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
            self.task_repo.save_brain_dump_audio_chunk(
                owner_id=owner_id,
                operation_id=operation_id,
                chunk_number=chunk_number,
                sha256=actual_sha256,
                content=content,
            )
            return updated

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
        with self.task_repo.command_lock(owner_id):
            self.task_repo.purge_expired_idempotency(owner_id=owner_id, now=utcnow())
            self._reconcile_idempotent_result(owner_id=owner_id, key=idempotency_key)
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
                "Brain dump operation",
                operation.id,
                operation.revision,
                payload.expected_revision,
            )
            if operation.status not in {"recording", "paused"}:
                raise ValidationFailure("Only an active brain dump can be sealed.")
            expected_numbers = set(range(payload.expected_chunks))
            uploaded_numbers = {
                chunk.chunk_number for chunk in operation.audio_chunks
            }
            missing = sorted(expected_numbers - uploaded_numbers)
            unexpected = sorted(uploaded_numbers - expected_numbers)
            if missing or unexpected:
                raise ValidationFailure(
                    "Brain dump audio manifest is not the exact uploaded chunk set.",
                    {
                        "missing_chunks": missing,
                        "unexpected_chunks": unexpected,
                    },
                )
            consumed_chunks = [
                chunk
                for chunk in operation.audio_chunks
                if chunk.chunk_number in expected_numbers
            ]
            manifest_hash = self._brain_dump_manifest_hash(consumed_chunks)
            if payload.manifest_hash != manifest_hash:
                raise ConflictError(
                    "Brain dump audio manifest",
                    operation.id,
                    "MANIFEST_CONFLICT: sealed manifest does not match uploaded audio chunks.",
                )
            now = utcnow()
            reservation = getattr(
                self.accurate_stt, "max_cost_usd_per_operation", 0.0
            )
            claimed = operation.model_copy(
                update={
                    "status": "accurate_transcribing",
                    "status_history": [
                        *operation.status_history,
                        "sealing",
                        "fast_processing",
                        "accurate_transcribing",
                    ],
                    "sealed_manifest_hash": manifest_hash,
                    "provider_runs": [
                        *operation.provider_runs,
                        BrainDumpProviderRunDocument(
                            id=generate_id("provider_run"),
                            role="accurate_stt",
                            status="pending",
                            input_hash=manifest_hash,
                            checkpoint="sealed",
                            attempt=1,
                            recovery_count=0,
                            reserved_cost_usd=reservation,
                            created_at=now,
                            updated_at=now,
                        ),
                    ],
                    "updated_at": now,
                    "revision": operation.revision + 1,
                }
            )
            self.task_repo.save_brain_dump_operation(claimed)
            self._store_idempotency(
                owner_id=owner_id,
                key=idempotency_key,
                command=command,
                request_hash=request_hash,
                resource_id=claimed.id,
                response=claimed,
            )
        return claimed

    def run_due_brain_dump_provider_runs(self, *, limit: int = 50) -> int:
        """Advance persisted provider work outside request handlers.

        The operation row is first atomically changed from ``pending`` to a
        leased ``running`` claim (with its cost reservation already durable),
        then the provider is invoked without holding the owner lock. Accepted
        accurate output is saved before a separate reconciler run is queued.
        """

        advanced = 0
        for candidate in self.task_repo.list_in_flight_provider_run_operations():
            if advanced >= limit:
                break
            with self.task_repo.command_lock(candidate.owner_id):
                # The claim time is read here, inside this candidate's owner
                # lock, not once before the up-to-`limit` candidate loop. A
                # stale pre-loop timestamp would understate every later
                # candidate's actual claim time, so the lease it stamps could
                # already be near-expired (or expired) the moment it is
                # persisted -- letting a concurrent recovery sweep reclaim a
                # lease that was, in wall-clock terms, freshly issued.
                now = utcnow()
                operation = self.get_brain_dump_operation(
                    candidate.id, owner_id=candidate.owner_id
                )
                if not operation.provider_runs:
                    continue
                last_run = operation.provider_runs[-1]
                expired = (
                    last_run.status == "running"
                    and last_run.lease_expires_at is not None
                    and last_run.lease_expires_at <= now
                )
                if last_run.status != "pending" and not expired:
                    continue
                if last_run.role == "accurate_stt":
                    audio = self.task_repo.load_brain_dump_audio_chunks(
                        owner_id=operation.owner_id,
                        operation_id=operation.id,
                        chunks=[
                            (chunk.chunk_number, chunk.sha256)
                            for chunk in operation.audio_chunks
                        ],
                    )
                    input_hash = hashlib.sha256(audio).hexdigest()
                else:
                    audio = b""
                    input_hash = last_run.input_hash
                run = last_run.model_copy(
                    update={
                        "status": "running",
                        "input_hash": input_hash,
                        "lease_owner": generate_id("runner"),
                        "lease_expires_at": now
                        + timedelta(seconds=self.provider_run_lease_seconds),
                        # The lease is measured from its CAS claim, not the
                        # earlier queue-enqueue timestamp.
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                claimed = operation.model_copy(
                    update={
                        "provider_runs": [*operation.provider_runs[:-1], run],
                        "updated_at": now,
                        "revision": operation.revision + 1,
                    }
                )
                self.task_repo.save_brain_dump_operation(claimed)
            updated = self._run_accurate_stt_and_reconcile(
                claimed,
                audio=audio,
                attempt=run.attempt,
                recovery_count=run.recovery_count,
                now=utcnow(),
            )
            with self.task_repo.command_lock(claimed.owner_id):
                current = self.get_brain_dump_operation(
                    claimed.id, owner_id=claimed.owner_id
                )
                if current.revision != claimed.revision:
                    continue
                self.task_repo.save_brain_dump_operation(updated)
                advanced += 1
        # Accurate STT success durably queues a distinct reconciler run. Re-scan
        # immediately within the caller's original bound so that dependent work
        # does not wait for the next periodic sweep (60 seconds by default).
        # Persistence still separates the checkpoints, preserving crash safety;
        # the recursive pass only claims newly due rows and terminates once a
        # pass makes no progress or the shared stage budget is exhausted.
        remaining = limit - advanced
        if advanced and remaining > 0:
            advanced += self.run_due_brain_dump_provider_runs(limit=remaining)
        return advanced


    def _run_accurate_stt_and_reconcile(
        self,
        operation: BrainDumpOperationDocument,
        *,
        audio: bytes,
        attempt: int,
        recovery_count: int,
        now: datetime,
    ) -> BrainDumpOperationDocument:
        """Call the accurate-STT port from a persisted sealed checkpoint.

        On success the transcript is reconciled and the operation advances to
        ``awaiting_confirmation``. On a retryable provider failure the
        operation persists a ``retryable_error`` checkpoint that a later
        ``retry_brain_dump_operation`` call resumes without re-uploading or
        re-sealing audio. On a terminal failure, or once the bounded
        recovery budget is exhausted, the operation becomes ``terminal_error``.
        """

        input_hash = hashlib.sha256(audio).hexdigest()
        claimed_run = operation.provider_runs[-1] if operation.provider_runs else None
        if (
            claimed_run
            and claimed_run.role == "reconciler"
            and claimed_run.status == "running"
            and claimed_run.checkpoint == "accurate_transcribed"
        ):
            checkpoint_runs = operation.provider_runs[:-1]
            accurate_run = next(
                (
                    run
                    for run in reversed(checkpoint_runs)
                    if run.role == "accurate_stt"
                    and run.status == "succeeded"
                    and run.checkpoint == "accurate_transcribed"
                ),
                None,
            )
            if accurate_run is None or not accurate_run.output_segment_ids:
                raise ValidationFailure(
                    "Brain dump has no accurate transcript checkpoint to reconcile."
                )
            accurate_segment = next(
                (
                    segment
                    for segment in operation.segments
                    if segment.id in accurate_run.output_segment_ids
                ),
                None,
            )
            if accurate_segment is None:
                raise ValidationFailure(
                    "Brain dump accurate transcript checkpoint is incomplete."
                )
            accurate_hypothesis = TranscriptHypothesis(
                id=accurate_segment.id,
                sequence=accurate_segment.sequence,
                start_ms=accurate_segment.start_ms,
                end_ms=accurate_segment.end_ms,
                text=accurate_segment.text,
                stability=accurate_segment.stability,
                provider_role="accurate",
                model=accurate_segment.model,
                supersedes_segment_ids=accurate_segment.supersedes_segment_ids,
            )
            return self._reconcile_accurate_checkpoint(
                operation,
                accurate_hypothesis=accurate_hypothesis,
                accurate_segment=accurate_segment,
                checkpoint_runs=checkpoint_runs,
                checkpoint_segments=operation.segments,
                input_hash=accurate_run.input_hash,
                now=now,
                attempt=claimed_run.attempt,
                recovery_count=claimed_run.recovery_count,
            )
        replaces_claim = bool(
            claimed_run
            and claimed_run.role == "accurate_stt"
            and claimed_run.status == "running"
            and claimed_run.input_hash == input_hash
        )
        prior_runs = (
            operation.provider_runs[:-1] if replaces_claim else operation.provider_runs
        )
        budget_exceeded = self._operation_cost_budget_exceeded(
            prior_runs,
            role="accurate_stt",
            checkpoint="sealed",
            input_hash=input_hash,
            provider=self.accurate_stt.provider_name,
            claimed_run_id=claimed_run.id if replaces_claim and claimed_run else None,
            attempt=attempt,
            recovery_count=recovery_count,
            now=now,
            worst_case_next_usd=getattr(
                self.accurate_stt, "max_cost_usd_per_operation", 0.0
            ),
        )
        if budget_exceeded is not None:
            return operation.model_copy(
                update={
                    "status": "terminal_error",
                    "status_history": [*operation.status_history, "terminal_error"],
                    "sealed_manifest_hash": operation.sealed_manifest_hash,
                    "provider_runs": [*prior_runs, budget_exceeded],
                    "updated_at": now,
                    "revision": operation.revision + 1,
                }
            )
        try:
            if (
                self.accurate_stt.requires_external_processing
                and not operation.consent.external_processing_allowed
            ):
                raise ProviderTerminalError("STT_EXTERNAL_PROCESSING_CONSENT_REQUIRED")
            if (
                self.accurate_stt.requires_external_processing
                and operation.consent.provider != self.accurate_stt.provider_name
            ):
                raise ProviderTerminalError("STT_CONSENT_PROVIDER_MISMATCH")
            accurate_result = self.accurate_stt.transcribe_sealed_audio(
                AccurateSttRequest(
                    operation_id=operation.id,
                    media_ref=operation.media_ref or f"media_{operation.id}",
                    language_hints=operation.consent.language_hints,
                    vocabulary=operation.consent.vocabulary,
                    supersedes_segment_ids=[
                        segment.id
                        for segment in operation.segments
                        if segment.provider_role != "accurate"
                    ],
                    sealed_audio=audio,
                )
            )
        except (ProviderRetryableError, ProviderTerminalError) as exc:
            is_retryable = isinstance(exc, ProviderRetryableError)
            budget_exhausted = recovery_count >= self.max_operation_recoveries
            next_status: Literal["retryable_error", "terminal_error"] = (
                "retryable_error"
                if is_retryable and not budget_exhausted
                else "terminal_error"
            )
            return operation.model_copy(
                update={
                    "status": next_status,
                    "status_history": [*operation.status_history, next_status],
                    "sealed_manifest_hash": operation.sealed_manifest_hash,
                    "provider_runs": [
                        *prior_runs,
                        BrainDumpProviderRunDocument(
                            id=(
                                claimed_run.id
                                if replaces_claim and claimed_run
                                else generate_id("provider_run")
                            ),
                            role="accurate_stt",
                            status=next_status,
                            input_hash=input_hash,
                            checkpoint="sealed",
                            attempt=attempt,
                            recovery_count=recovery_count,
                            error=self._redact_provider_error(str(exc)),
                            error_code=self._redact_provider_error(str(exc)),
                            provider=self.accurate_stt.provider_name,
                            estimated_cost_usd=exc.estimated_cost_usd,
                            created_at=now,
                            updated_at=now,
                        ),
                    ],
                    "updated_at": now,
                    "revision": operation.revision + 1,
                }
            )

        accurate_hypothesis = accurate_result.segments[0]
        accurate_segment = BrainDumpTranscriptSegmentDocument(
            id=accurate_hypothesis.id,
            sequence=max(
                (segment.sequence for segment in operation.segments), default=0
            )
            + 1,
            text=accurate_hypothesis.text,
            stability=accurate_hypothesis.stability,
            start_ms=accurate_hypothesis.start_ms,
            end_ms=accurate_hypothesis.end_ms,
            provider_role=accurate_hypothesis.provider_role,
            provider=accurate_result.provider or self.accurate_stt.provider_name,
            model=accurate_hypothesis.model,
            supersedes_segment_ids=accurate_hypothesis.supersedes_segment_ids,
            created_at=now,
        )
        accurate_run = BrainDumpProviderRunDocument(
            id=(
                claimed_run.id
                if replaces_claim and claimed_run
                else generate_id("provider_run")
            ),
            role="accurate_stt",
            status="succeeded",
            input_hash=input_hash,
            checkpoint="accurate_transcribed",
            attempt=attempt,
            recovery_count=recovery_count,
            provider=accurate_result.provider or self.accurate_stt.provider_name,
            model=accurate_hypothesis.model,
            estimated_cost_usd=accurate_result.estimated_cost_usd,
            reserved_cost_usd=0.0,
            consumed_cost_usd=accurate_result.estimated_cost_usd,
            output_segment_ids=[accurate_segment.id],
            created_at=now,
            updated_at=now,
        )
        # Persist the accepted accurate transcript first. Reconciliation is a
        # distinct queued run, so a crash here cannot repeat paid STT.
        return operation.model_copy(
            update={
                "status": "reconciling",
                "status_history": [*operation.status_history, "reconciling"],
                "segments": [*operation.segments, accurate_segment],
                "provider_runs": [
                    *prior_runs,
                    accurate_run,
                    BrainDumpProviderRunDocument(
                        id=generate_id("provider_run"),
                        role="reconciler",
                        status="pending",
                        input_hash=hashlib.sha256(
                            accurate_hypothesis.text.encode("utf-8")
                        ).hexdigest(),
                        checkpoint="accurate_transcribed",
                        attempt=1,
                        recovery_count=recovery_count,
                        reserved_cost_usd=getattr(
                            self.text_reconciler, "max_cost_usd_per_operation", 0.0
                        ),
                        created_at=now,
                        updated_at=now,
                    ),
                ],
                "updated_at": now,
                "revision": operation.revision + 1,
            }
        )

    def _reconcile_accurate_checkpoint(
        self,
        operation: BrainDumpOperationDocument,
        *,
        accurate_hypothesis: TranscriptHypothesis,
        accurate_segment: BrainDumpTranscriptSegmentDocument,
        checkpoint_runs: list[BrainDumpProviderRunDocument],
        checkpoint_segments: list[BrainDumpTranscriptSegmentDocument],
        input_hash: str,
        now: datetime,
        attempt: int,
        recovery_count: int,
    ) -> BrainDumpOperationDocument:
        cumulative_spent = sum(
            max(run.estimated_cost_usd, run.consumed_cost_usd)
            # A prior run still "pending"/"running" -- including one whose
            # process crashed or is otherwise unresolved -- has an
            # outstanding reservation that must count against the cap here
            # exactly as it does for accurate-STT admission
            # (``_operation_cost_budget_exceeded``); otherwise a stuck or
            # unknown-outcome run's reserved spend would be silently
            # dropped from the reconciler's own admission check.
            + (
                run.reserved_cost_usd
                if run.status in {"pending", "running"}
                else 0.0
            )
            for run in checkpoint_runs
        )
        worst_case_next = getattr(
            self.text_reconciler, "max_cost_usd_per_operation", 0.0
        )
        cap = self.max_cumulative_cost_usd_per_operation
        if cumulative_spent >= cap or cumulative_spent + worst_case_next > cap:
            return self._reconciler_failure(
                operation,
                checkpoint_segments=checkpoint_segments,
                checkpoint_runs=checkpoint_runs,
                input_hash=input_hash,
                error="OPERATION_COST_BUDGET_EXCEEDED",
                error_code="OPERATION_COST_BUDGET_EXCEEDED",
                now=now,
                retryable=False,
                attempt=attempt,
                recovery_count=recovery_count,
            )
        if self.text_reconciler.requires_external_processing:
            if not operation.consent.external_processing_allowed:
                return self._reconciler_failure(
                    operation,
                    checkpoint_segments=checkpoint_segments,
                    checkpoint_runs=checkpoint_runs,
                    input_hash=input_hash,
                    error="RECONCILER_CONSENT_REQUIRED",
                    now=now,
                    attempt=attempt,
                    recovery_count=recovery_count,
                )
            if operation.consent.provider != self.text_reconciler.provider_id:
                return self._reconciler_failure(
                    operation,
                    checkpoint_segments=checkpoint_segments,
                    checkpoint_runs=checkpoint_runs,
                    input_hash=input_hash,
                    error="RECONCILER_CONSENT_PROVIDER_MISMATCH",
                    now=now,
                    attempt=attempt,
                    recovery_count=recovery_count,
                )
        if isinstance(self.text_reconciler, DeterministicTextReconciler):
            # The container only wires this adapter in AppEnvironment.TEST. It
            # retains deterministic fixture semantics while exercising the same
            # opaque-ID patch and lineage projection used by production.
            fixture_result = self.text_reconciler.reconcile(
                ReconcileTextRequest(
                    operation_id=operation.id,
                    transcript_segments=[accurate_hypothesis],
                    active_proposals=[],
                    user_locks={},
                )
            )
            titles = [patch.title for patch in fixture_result.patches if patch.title]
            proposals, patch_drafts = self._reconcile_accurate_titles(
                operation.proposals,
                titles,
                operation_id=operation.id,
                source_segment_id=accurate_hypothesis.id,
                now=now,
            )
            reconciler_input_hash = hashlib.sha256(
                accurate_hypothesis.text.encode("utf-8")
            ).hexdigest()
            reconciler_cost = fixture_result.estimated_cost_usd
        else:
            reconciler_request = ReconcileTextRequest(
                operation_id=operation.id,
                transcript_segments=[accurate_hypothesis],
                active_proposals=[
                    self._proposal_document_to_reconciled(proposal)
                    for proposal in operation.proposals
                ],
                user_locks={
                    proposal.id: proposal.locked_fields
                    for proposal in operation.proposals
                    if proposal.locked_fields
                },
                language_hints=operation.consent.language_hints,
                vocabulary=operation.consent.vocabulary,
            )
            try:
                reconcile_result = self.text_reconciler.reconcile(reconciler_request)
            except (
                ProviderRetryableError,
                ProviderTerminalError,
                ValidationFailure,
            ) as exc:
                return self._reconciler_failure(
                    operation,
                    checkpoint_segments=checkpoint_segments,
                    checkpoint_runs=checkpoint_runs,
                    input_hash=input_hash,
                    error=self._redact_provider_error(str(exc)),
                    error_code=self._redact_provider_error(str(exc)),
                    now=now,
                    retryable=isinstance(exc, ProviderRetryableError),
                    attempt=attempt,
                    recovery_count=recovery_count,
                    estimated_cost_usd=exc.estimated_cost_usd,
                )
            proposals = self._apply_reconciler_patches(
                operation.proposals, reconcile_result.patches, now=now
            )
            patch_drafts = reconcile_result.patches
            reconciler_input_hash = reconcile_result.input_hash
            reconciler_cost = reconcile_result.estimated_cost_usd
        proposal_patches = self._append_proposal_patch_documents(
            operation_id=operation.id,
            existing=operation.proposal_patches,
            drafts=patch_drafts,
            now=now,
        )
        active_reconciler_run = operation.provider_runs[-1]
        return operation.model_copy(
            update={
                "status": "awaiting_confirmation",
                "status_history": [
                    *operation.status_history,
                    "reconciling",
                    "awaiting_confirmation",
                ],
                "reconciliation_quality": "accurate",
                "segments": checkpoint_segments,
                "proposals": proposals,
                "proposal_patches": proposal_patches,
                "provider_runs": [
                    *checkpoint_runs,
                    active_reconciler_run.model_copy(
                        update={
                            "status": "succeeded",
                            "input_hash": reconciler_input_hash,
                            "checkpoint": "reconciled",
                            "attempt": attempt,
                            "recovery_count": recovery_count,
                            "provider": self.text_reconciler.provider_id,
                            "estimated_cost_usd": reconciler_cost,
                            "reserved_cost_usd": 0.0,
                            "consumed_cost_usd": reconciler_cost,
                            "lease_owner": None,
                            "lease_expires_at": None,
                            "updated_at": now,
                        }
                    ),
                ],
                # Stamped once, at the first successful reconciliation, and
                # never recomputed afterward — see ``purge_expired_raw_audio``.
                "raw_audio_expires_at": (
                    operation.raw_audio_expires_at
                    or now + self.raw_audio_retention
                ),
                "updated_at": now,
                "revision": operation.revision + 1,
            }
        )

    def retry_brain_dump_operation(
        self,
        operation_id: str,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> BrainDumpOperationDocument:
        """Resume the failed provider stage from its latest durable checkpoint."""

        command = f"brain_dump_retry:{operation_id}"
        request_hash = self._request_hash(command, payload)
        with self.task_repo.command_lock(owner_id):
            self.task_repo.purge_expired_idempotency(owner_id=owner_id, now=utcnow())
            self._reconcile_idempotent_result(owner_id=owner_id, key=idempotency_key)
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
                "Brain dump operation",
                operation.id,
                operation.revision,
                payload.expected_revision,
            )
            recoverable_claim = (
                operation.status in {"accurate_transcribing", "reconciling"}
                and bool(operation.provider_runs)
                and operation.provider_runs[-1].status == "running"
                and operation.provider_runs[-1].lease_expires_at is not None
                and operation.provider_runs[-1].lease_expires_at <= utcnow()
            )
            if operation.status != "retryable_error" and not recoverable_claim:
                raise ValidationFailure("Only a retryable brain dump can be retried.")
            latest_provider_run = (
                operation.provider_runs[-1] if operation.provider_runs else None
            )
            resume_reconciliation = bool(
                latest_provider_run
                and latest_provider_run.role == "reconciler"
                and latest_provider_run.checkpoint == "accurate_transcribed"
                and (
                    latest_provider_run.status == "retryable_error"
                    or recoverable_claim
                )
            )
            last_run = latest_provider_run if resume_reconciliation else next(
                (
                    run
                    for run in reversed(operation.provider_runs)
                    if run.role == "accurate_stt"
                ),
                None,
            )
            if last_run is None or operation.sealed_manifest_hash is None:
                raise ValidationFailure(
                    "Brain dump has no sealed checkpoint to resume from."
                )
            audio = b""
            if not resume_reconciliation:
                audio = self.task_repo.load_brain_dump_audio_chunks(
                    owner_id=owner_id,
                    operation_id=operation.id,
                    chunks=[
                        (chunk.chunk_number, chunk.sha256)
                        for chunk in operation.audio_chunks
                    ],
                )
            now = utcnow()
            attempt = last_run.attempt + 1
            recovery_count = last_run.recovery_count + 1
            if recovery_count >= self.max_operation_recoveries:
                exhausted = operation.model_copy(
                    update={
                        "status": "terminal_error",
                        "status_history": [*operation.status_history, "terminal_error"],
                        "provider_runs": [
                            *operation.provider_runs,
                            BrainDumpProviderRunDocument(
                                id=generate_id("provider_run"),
                                role=last_run.role,
                                status="terminal_error",
                                input_hash=last_run.input_hash,
                                checkpoint=last_run.checkpoint,
                                attempt=attempt,
                                recovery_count=recovery_count,
                                error="OPERATION_RECOVERY_BUDGET_EXHAUSTED",
                                error_code="OPERATION_RECOVERY_BUDGET_EXHAUSTED",
                                created_at=now,
                                updated_at=now,
                            ),
                        ],
                        "updated_at": now,
                        "revision": operation.revision + 1,
                    }
                )
                self.task_repo.save_brain_dump_operation(exhausted)
                self._store_idempotency(
                    owner_id=owner_id,
                    key=idempotency_key,
                    command=command,
                    request_hash=request_hash,
                    resource_id=exhausted.id,
                    response=exhausted,
                )
                return exhausted
            claimed_status: Literal["accurate_transcribing", "reconciling"] = (
                "reconciling" if resume_reconciliation else "accurate_transcribing"
            )
            claimed_role: Literal["accurate_stt", "reconciler"] = (
                "reconciler" if resume_reconciliation else "accurate_stt"
            )
            claimed_checkpoint: Literal["sealed", "accurate_transcribed"] = (
                "accurate_transcribed" if resume_reconciliation else "sealed"
            )
            claimed = operation.model_copy(
                update={
                    "status": claimed_status,
                    "status_history": [*operation.status_history, claimed_status],
                    "provider_runs": [
                        *operation.provider_runs,
                        BrainDumpProviderRunDocument(
                            id=generate_id("provider_run"),
                            role=claimed_role,
                            # Retry is a command that persists a new queue item;
                            # it never performs provider I/O in the request
                            # handler. The runner claims it in a separate CAS
                            # transaction before calling the adapter.
                            status="pending",
                            input_hash=(
                                last_run.input_hash
                                if resume_reconciliation
                                else hashlib.sha256(audio).hexdigest()
                            ),
                            checkpoint=claimed_checkpoint,
                            attempt=attempt,
                            recovery_count=recovery_count,
                            reserved_cost_usd=getattr(
                                self.text_reconciler
                                if resume_reconciliation
                                else self.accurate_stt,
                                "max_cost_usd_per_operation",
                                0.0,
                            ),
                            created_at=now,
                            updated_at=now,
                        ),
                    ],
                    "updated_at": now,
                    "revision": operation.revision + 1,
                }
            )
            self.task_repo.save_brain_dump_operation(claimed)
            self._store_idempotency(
                owner_id=owner_id,
                key=idempotency_key,
                command=command,
                request_hash=request_hash,
                resource_id=claimed.id,
                response=claimed,
            )
        return claimed

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
        if not operation.consent.external_processing_allowed:
            raise ValidationFailure("TRANSCRIPT_CONSENT_REQUIRED")
        if operation.status not in {"recording", "paused"}:
            raise ValidationFailure(
                "Transcript can only be appended while recording or paused."
            )
        now = utcnow()
        segments_by_sequence = {
            segment.sequence: segment for segment in operation.segments
        }
        for segment in payload.segments:
            existing = segments_by_sequence.get(segment.sequence)
            if existing is not None:
                if (
                    existing.text != segment.text
                    or existing.stability != segment.stability
                ):
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
        proposals = self._proposals_from_segments(
            operation.proposals, segments, now=now
        )
        existing_by_id = {proposal.id: proposal for proposal in operation.proposals}
        patch_drafts: list[ProposalPatch] = []
        for proposal in proposals:
            previous = existing_by_id.get(proposal.id)
            if previous is None:
                patch_drafts.append(
                    ProposalPatch.add(
                        proposal_id=proposal.id,
                        title=proposal.title,
                        source_segment_ids=proposal.source_segment_ids,
                        producer="fast",
                    )
                )
                continue
            title = proposal.title if proposal.title != previous.title else None
            source_segment_ids = (
                proposal.source_segment_ids
                if proposal.source_segment_ids != previous.source_segment_ids
                else None
            )
            if title is not None or source_segment_ids is not None:
                patch_drafts.append(
                    ProposalPatch.update(
                        proposal_id=proposal.id,
                        title=title,
                        source_segment_ids=source_segment_ids,
                        producer="fast",
                        base_revision=previous.title_revision,
                    )
                )
        proposal_patches = self._append_proposal_patch_documents(
            operation_id=operation.id,
            existing=operation.proposal_patches,
            drafts=patch_drafts,
            now=now,
        )
        updated = operation.model_copy(
            update={
                "segments": segments,
                "proposals": proposals,
                "proposal_patches": proposal_patches,
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
        self._assert_revision(
            "Brain dump operation",
            operation.id,
            operation.revision,
            payload.expected_revision,
        )
        if operation.status not in {"recording", "paused", "awaiting_confirmation"}:
            raise ValidationFailure(
                "Proposal cannot be edited in this operation state."
            )
        now = utcnow()
        changed = False
        patch_drafts: list[ProposalPatch] = []
        proposals: list[BrainDumpProposalDocument] = []
        for proposal in operation.proposals:
            if proposal.id != proposal_id:
                proposals.append(proposal)
                continue
            update: dict[str, object] = {
                "updated_at": now,
                "revision": proposal.revision + 1,
            }
            if payload.conflict_resolution is not None:
                removal_conflicts = [
                    conflict
                    for conflict in proposal.conflicts
                    if conflict.field == "removal"
                ]
                if removal_conflicts:
                    if payload.conflict_resolution == "accept":
                        update.update(
                            {
                                "deleted": True,
                                "conflicts": [
                                    conflict
                                    for conflict in proposal.conflicts
                                    if conflict.field != "removal"
                                ],
                            }
                        )
                        patch_drafts.append(
                            ProposalPatch.remove(
                                proposal_id=proposal.id, producer="user"
                            )
                        )
                    else:
                        update.update(
                            {
                                "status": "user_edited",
                                "user_edited": True,
                                "conflicts": [
                                    conflict
                                    for conflict in proposal.conflicts
                                    if conflict.field != "removal"
                                ],
                            }
                        )
                    proposals.append(proposal.model_copy(update=update))
                    changed = True
                    continue
                title_conflicts = [
                    conflict
                    for conflict in proposal.conflicts
                    if conflict.field == "title"
                ]
                if not title_conflicts:
                    raise ValidationFailure(
                        "Proposal has no conflict to resolve."
                    )
                conflict = title_conflicts[-1]
                resolved_title = proposal.title
                if payload.conflict_resolution == "accept":
                    if not conflict.suggested_value:
                        raise ValidationFailure(
                            "Proposal conflict has no suggestion to accept."
                        )
                    resolved_title = conflict.suggested_value
                update.update(
                    {
                        "title": resolved_title,
                        "status": "user_edited",
                        "user_edited": True,
                        "title_revision": (
                            proposal.title_revision + 1
                            if resolved_title != proposal.title
                            else proposal.title_revision
                        ),
                        "locked_fields": sorted(
                            {*proposal.locked_fields, "title"}
                        ),
                        "conflicts": [],
                    }
                )
                patch_drafts.append(
                    ProposalPatch.update(
                        proposal_id=proposal.id,
                        title=(
                            resolved_title
                            if resolved_title != proposal.title
                            else None
                        ),
                        producer="user",
                        locked_fields=["title"],
                        base_revision=proposal.title_revision,
                    )
                )
            if "title" in payload.model_fields_set and payload.title:
                title = payload.title.strip()
                update.update(
                    {
                        "title": title,
                        "status": "user_edited",
                        "user_edited": True,
                        "title_revision": proposal.title_revision + 1,
                        "locked_fields": sorted({*proposal.locked_fields, "title"}),
                    }
                )
                patch_drafts.append(
                    ProposalPatch.update(
                        proposal_id=proposal.id,
                        title=title,
                        producer="user",
                        locked_fields=["title"],
                        base_revision=proposal.title_revision,
                    )
                )
            if "deleted" in payload.model_fields_set and payload.deleted is not None:
                update["deleted"] = payload.deleted
                if payload.deleted and not proposal.deleted:
                    patch_drafts.append(
                        ProposalPatch.remove(
                            proposal_id=proposal.id,
                            producer="user",
                        )
                    )
            proposals.append(proposal.model_copy(update=update))
            changed = True
        if not changed:
            raise NotFoundError("Brain dump proposal", proposal_id)
        updated = operation.model_copy(
            update={
                "proposals": proposals,
                "proposal_patches": self._append_proposal_patch_documents(
                    operation_id=operation.id,
                    existing=operation.proposal_patches,
                    drafts=patch_drafts,
                    now=now,
                ),
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
        self._assert_revision(
            "Brain dump operation",
            operation.id,
            operation.revision,
            payload.expected_revision,
        )
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
                (
                    proposal.model_copy(
                        update={
                            "status": "ready_to_review",
                            "updated_at": now,
                            "revision": proposal.revision + 1,
                        }
                    )
                    if not proposal.deleted and not proposal.user_edited
                    else proposal
                )
                for proposal in operation.proposals
            ]
        clear_raw_audio = action == "cancel"
        if clear_raw_audio:
            self.task_repo.delete_brain_dump_audio_chunks(
                owner_id=owner_id,
                operation_id=operation.id,
                chunks=[
                    (chunk.chunk_number, chunk.sha256)
                    for chunk in operation.audio_chunks
                ],
            )
        updated = operation.model_copy(
            update={
                "status": next_status,
                "proposals": proposals,
                "audio_chunks": [] if clear_raw_audio else operation.audio_chunks,
                "media_ref": None if clear_raw_audio else operation.media_ref,
                "sealed_manifest_hash": (
                    None if clear_raw_audio else operation.sealed_manifest_hash
                ),
                "working_artifacts_expires_at": (
                    now + self.working_artifacts_retention
                    if action == "cancel"
                    else operation.working_artifacts_expires_at
                ),
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
    def withdraw_brain_dump_consent(
        self,
        operation_id: str,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> BrainDumpOperationDocument:
        """Atomically revoke external-processing consent for one operation.

        This is a distinct, owner-scoped, idempotent, expected-revision
        checked command — never conflated with ``cancel``. It:
          * flips ``consent.external_processing_allowed`` false in the same
            write as every other effect below (no partial state is visible);
          * blocks all future upload/provider calls, which already fail
            closed on ``consent.external_processing_allowed`` at every call
            site (``upload_brain_dump_audio_chunk``,
            ``append_brain_dump_transcript``, ``_run_accurate_stt_and_reconcile``,
            ``_reconcile_accurate_checkpoint``);
          * invalidates a due/leased in-flight provider run immediately
            (rather than waiting for lease expiry) by marking it
            terminal and clearing its lease, and moves the operation to the
            explicit ``terminal_error`` recovery state so the UI never shows
            a phantom "still processing" surface for a run that can no
            longer complete;
          * removes raw audio promptly, leaving any already-reconciled
            transcript/proposal provenance intact and still committable
            (``_has_frozen_reconciled_batch`` never depends on raw audio
            still being present);
          * leaves uncommitted transcript/proposal working data in place for
            the standard working-artifact retention sweep to delete, rather
            than destroying it synchronously and losing the user's in-review
            edits.
        """

        command = f"brain_dump_withdraw_consent:{operation_id}"
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
        if operation.status in {"completed", "cancelled"}:
            raise ValidationFailure(
                "Consent cannot be withdrawn from a completed or cancelled "
                "brain dump; there is no future processing left to stop."
            )
        self._assert_revision(
            "Brain dump operation",
            operation.id,
            operation.revision,
            payload.expected_revision,
        )
        now = utcnow()
        in_flight = operation.status in {"accurate_transcribing", "reconciling"}
        next_status = "terminal_error" if in_flight else operation.status
        provider_runs = operation.provider_runs
        if in_flight and provider_runs and provider_runs[-1].status == "running":
            invalidated_run = provider_runs[-1].model_copy(
                update={
                    "status": "terminal_error",
                    "error": "CONSENT_WITHDRAWN",
                    "error_code": "CONSENT_WITHDRAWN",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "updated_at": now,
                }
            )
            provider_runs = [*provider_runs[:-1], invalidated_run]
        self.task_repo.delete_brain_dump_audio_chunks(
            owner_id=owner_id,
            operation_id=operation.id,
            chunks=[
                (chunk.chunk_number, chunk.sha256)
                for chunk in operation.audio_chunks
            ],
        )
        updated = operation.model_copy(
            update={
                "consent": operation.consent.model_copy(
                    update={"external_processing_allowed": False}
                ),
                "status": next_status,
                "status_history": (
                    [*operation.status_history, next_status]
                    if next_status != operation.status
                    else operation.status_history
                ),
                "provider_runs": provider_runs,
                "audio_chunks": [],
                "media_ref": None,
                "sealed_manifest_hash": None,
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
    def delete_brain_dump_raw_audio(
        self,
        operation_id: str,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> BrainDumpOperationDocument:
        """Let the owner remove raw audio without discarding review work."""

        command = f"brain_dump_delete_raw_audio:{operation_id}"
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
            "Brain dump operation",
            operation.id,
            operation.revision,
            payload.expected_revision,
        )
        if (
            operation.status in {"accurate_transcribing", "reconciling"}
            and operation.provider_runs
            and operation.provider_runs[-1].status in {"pending", "running"}
        ):
            raise ValidationFailure(
                "Raw audio cannot be deleted while provider processing is in flight."
            )
        now = utcnow()
        self.task_repo.delete_brain_dump_audio_chunks(
            owner_id=owner_id,
            operation_id=operation.id,
            chunks=[
                (chunk.chunk_number, chunk.sha256)
                for chunk in operation.audio_chunks
            ],
        )
        updated = operation.model_copy(
            update={
                "audio_chunks": [],
                "media_ref": None,
                "sealed_manifest_hash": None,
                "raw_audio_expires_at": now,
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

    def _operation_cost_budget_exceeded(
        self,
        prior_runs: list[BrainDumpProviderRunDocument],
        *,
        role: Literal["accurate_stt", "reconciler"],
        checkpoint: Literal["sealed", "accurate_transcribed", "reconciled"],
        input_hash: str,
        provider: str | None,
        claimed_run_id: str | None,
        attempt: int,
        recovery_count: int,
        now: datetime,
        worst_case_next_usd: float = 0.0,
    ) -> BrainDumpProviderRunDocument | None:
        """Enforce one operation-wide cumulative cost cap across every STT and
        reconciler attempt, transport retry, and recovery — never per-attempt
        only. Each adapter already refuses a single call whose own estimate
        exceeds its role's ceiling; this additionally sums every previously
        *persisted* ``estimated_cost_usd`` on the operation (across both
        roles and all retries/recoveries), adds the worst-case cost of the
        call about to be admitted (``worst_case_next_usd``, the adapter's own
        per-operation ceiling when known), and refuses the next attempt
        before it would push cumulative spend to or past the configured
        operation limit, with a redacted, non-retryable error code and no
        silent fallback. The provider is never called once this rejects.
        """

        cumulative_spent = sum(
            max(run.estimated_cost_usd, run.consumed_cost_usd)
            + (
                run.reserved_cost_usd
                if run.status in {"pending", "running"}
                else 0.0
            )
            for run in prior_runs
        )
        cap = self.max_cumulative_cost_usd_per_operation
        if cumulative_spent < cap and cumulative_spent + worst_case_next_usd <= cap:
            return None
        return BrainDumpProviderRunDocument(
            id=claimed_run_id or generate_id("provider_run"),
            role=role,
            status="terminal_error",
            input_hash=input_hash,
            checkpoint=checkpoint,
            attempt=attempt,
            recovery_count=recovery_count,
            error="OPERATION_COST_BUDGET_EXCEEDED",
            error_code="OPERATION_COST_BUDGET_EXCEEDED",
            provider=provider,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _has_frozen_reconciled_batch(operation: BrainDumpOperationDocument) -> bool:
        """A batch is commit-eligible only once sealed audio has been through
        accurate STT and the reconciler has durably succeeded.

        ``finish``/``transition_brain_dump_operation`` can move an operation to
        ``awaiting_confirmation`` directly from ``recording``/``paused`` (e.g.
        when external-processing consent was never granted, so nothing could
        be sealed or reconciled). That path only ever carries "fast" preview
        proposals from the live heuristic extractor and must never be
        committable as canonical tasks — it is provisional-only and review is
        limited to editing/discarding, per ADR-0002's model-output-as-proposals
        invariant.

        This deliberately does not require ``sealed_manifest_hash`` to still be
        set: raw audio may be deleted promptly after a successful reconciliation
        (immediately on request, or by consent withdrawal, or by retention) while
        the reconciled transcript/proposal provenance remains valid and stays
        committable — only the *provider run history* is the source of truth for
        "was this batch actually reconciled."
        """

        return any(
            run.role == "reconciler"
            and run.status == "succeeded"
            and run.checkpoint == "reconciled"
            for run in operation.provider_runs
        )

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
        self._assert_revision(
            "Brain dump operation",
            operation.id,
            operation.revision,
            payload.expected_revision,
        )
        if operation.status != "awaiting_confirmation":
            raise ValidationFailure(
                "Brain dump must be awaiting confirmation before save."
            )
        if not self._has_frozen_reconciled_batch(operation):
            raise ValidationFailure(
                "BRAIN_DUMP_NOT_RECONCILED: canonical tasks require a sealed "
                "audio checkpoint that completed accurate STT and reconciler "
                "review; a provisional-only recording cannot be committed."
            )
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
        unreconciled = [
            proposal.id
            for proposal in operation.proposals
            if not proposal.deleted
            and proposal.status not in {"reconciled", "user_edited"}
        ]
        if unreconciled:
            raise ValidationFailure(
                "BRAIN_DUMP_PROPOSAL_NOT_RECONCILED: an operation-level "
                "reconciler success cannot make an untouched browser-preview/"
                "fast proposal canonical; edit or delete it before save.",
                {"proposal_ids": unreconciled},
            )
        now = utcnow()
        confirmed_actions = confirm_native_inbox_actions(
            operation_id=operation.id,
            owner_id=owner_id,
            proposals=operation.proposals,
            task_port=self.task_port,
            confirmed_at=now,
        )
        committed_task_ids = [action.task_id for action in confirmed_actions]
        proposal_by_id = {proposal.id: proposal for proposal in operation.proposals}
        reconciler_run = next(
            (
                run
                for run in reversed(operation.provider_runs)
                if run.role == "reconciler"
                and run.status == "succeeded"
                and run.checkpoint == "reconciled"
            ),
            None,
        )
        action_receipts: list[BrainDumpActionReceiptDocument] = []
        for action in confirmed_actions:
            proposal = proposal_by_id[action.proposal_id]
            action_receipts.append(
                BrainDumpActionReceiptDocument(
                    id=f"receipt:{operation.id}:{action.proposal_id}",
                    proposal_id=action.proposal_id,
                    task_id=action.task_id,
                    child_idempotency_key=action.child_idempotency_key,
                    source_segment_ids=list(action.source_segment_ids),
                    proposal_patch_ids=[
                        patch.id
                        for patch in operation.proposal_patches
                        if patch.proposal_id == action.proposal_id
                    ],
                    source_operation_id=operation.id,
                    source_manifest_hash=operation.sealed_manifest_hash,
                    reconciliation_run_id=reconciler_run.id if reconciler_run else None,
                    reconciliation_provider=(
                        reconciler_run.provider if reconciler_run else None
                    ),
                    reconciliation_model=reconciler_run.model if reconciler_run else None,
                    reconciliation_template_version=(
                        reconciler_run.template_version if reconciler_run else None
                    ),
                    reconciliation_quality=operation.reconciliation_quality,
                    confirmed_title_sha256=hashlib.sha256(
                        proposal.title.encode("utf-8")
                    ).hexdigest(),
                    proposal_revision=proposal.revision,
                    user_edited=proposal.user_edited,
                    confidence="unknown",
                    confirmed_by_actor_id=owner_id,
                    confirmed_at=action.confirmed_at,
                )
            )
        updated = operation.model_copy(
            update={
                "status": "completed",
                # Source/proposal/edit records are immutable audit evidence
                # through working-artifact retention; source refs must never
                # point at data erased by the confirmation itself.
                "action_receipts": [*operation.action_receipts, *action_receipts],
                "committed_task_ids": committed_task_ids,
                "raw_audio_expires_at": (
                    operation.raw_audio_expires_at or now + self.raw_audio_retention
                ),
                "working_artifacts_expires_at": now + self.working_artifacts_retention,
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
            update={
                "state": next_state,
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
                raise ValidationFailure(
                    "waiting_for can only be edited on Waiting tasks."
                )
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
                task
                for task in all_filtered
                if self._sort_key(task, sort=sort) > last_sort_key
            ]
        page = all_filtered[:limit]
        has_more = len(all_filtered) > limit
        next_cursor = (
            self._encode_cursor(filters, self._sort_key(page[-1], sort=sort))
            if has_more
            else None
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
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._project_result(record, owner_id=owner_id)
        project = self.get_project(project_id, owner_id=owner_id)
        self._assert_revision(
            "Project", project.id, project.revision, payload.expected_revision
        )
        fields = payload.model_fields_set
        name = (
            display_project_name(payload.name)
            if "name" in fields and payload.name
            else project.name
        )
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
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._project_result(record, owner_id=owner_id)
        project = self.get_project(project_id, owner_id=owner_id)
        self._assert_revision(
            "Project", project.id, project.revision, payload.expected_revision
        )
        now = utcnow()
        updated_project = project.model_copy(
            update={
                "state": "archived",
                "updated_at": now,
                "revision": project.revision + 1,
            }
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
                    update={
                        "project_id": None,
                        "updated_at": now,
                        "revision": task.revision + 1,
                    }
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
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._tag_result(record, owner_id=owner_id)
        tag = self.get_tag(tag_id, owner_id=owner_id)
        self._assert_revision("Tag", tag.id, tag.revision, payload.expected_revision)
        fields = payload.model_fields_set
        name = (
            display_tag_name(payload.name)
            if "name" in fields and payload.name
            else tag.name
        )
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
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._tag_result(record, owner_id=owner_id)
        tag = self.get_tag(tag_id, owner_id=owner_id)
        self._assert_revision("Tag", tag.id, tag.revision, payload.expected_revision)
        now = utcnow()
        updated_tag = tag.model_copy(
            update={"state": "deleted", "updated_at": now, "revision": tag.revision + 1}
        )
        affected = [
            task
            for task in self.task_repo.list_for_owner(owner_id=owner_id)
            if tag_id in task.tag_ids
        ]
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
                        "tag_ids": [
                            existing for existing in task.tag_ids if existing != tag_id
                        ],
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
        elif record.command.startswith(
            ("create_subtask:", "update_subtask:", "transition_subtask:")
        ):
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
            current = self.task_repo.get_project_for_owner(
                project.id, owner_id=owner_id
            )
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
                current_tag = self.task_repo.get_tag_for_owner(
                    tag.id, owner_id=owner_id
                )
            except NotFoundError:
                self.task_repo.create_tag(tag)
            else:
                if current_tag.revision < tag.revision:
                    self.task_repo.save_tag(tag)
        try:
            current_task = self.task_repo.get_for_owner(
                result.task.id, owner_id=owner_id
            )
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
    def _brain_dump_manifest_hash(chunks: list[BrainDumpAudioChunkDocument]) -> str:
        """Hash the exact ordered chunk metadata that a seal consumes."""

        encoded = json.dumps(
            [
                {
                    "chunk_number": chunk.chunk_number,
                    "sha256": chunk.sha256,
                    "size_bytes": chunk.size_bytes,
                }
                for chunk in sorted(chunks, key=lambda item: item.chunk_number)
            ],
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

    _DOMAIN_STATUS_TO_DOC_STATUS: dict[str, BrainDumpProposalStatus] = {
        "provisional": "provisional",
        "reconciled": "reconciled",
        "user_edited": "user_edited",
        "conflicted": "conflicted",
    }

    @classmethod
    def _domain_status_to_doc_status(cls, status: str) -> BrainDumpProposalStatus:
        return cls._DOMAIN_STATUS_TO_DOC_STATUS.get(status, "reconciled")

    @staticmethod
    def _domain_conflict_to_doc(
        conflict: ProposalConflict,
    ) -> BrainDumpProposalConflictDocument:
        return BrainDumpProposalConflictDocument(
            field=conflict.field,
            current_value=conflict.current_value,
            suggested_value=conflict.suggested_value,
            producer=conflict.producer,
            source_segment_ids=conflict.source_segment_ids,
        )

    @staticmethod
    def _append_proposal_patch_documents(
        *,
        operation_id: str,
        existing: list[BrainDumpProposalPatchDocument],
        drafts: list[ProposalPatch],
        now: datetime,
    ) -> list[BrainDumpProposalPatchDocument]:
        proposal_patches = list(existing)
        for draft in drafts:
            sequence = len(proposal_patches) + 1
            identity = json.dumps(
                {
                    "operation_id": operation_id,
                    "sequence": sequence,
                    "operation": draft.operation,
                    "proposal_id": draft.proposal_id,
                    "producer": draft.producer,
                    "title": draft.title,
                    "source_segment_ids": draft.source_segment_ids,
                    "predecessor_ids": draft.predecessor_ids,
                    "successor_ids": draft.successor_ids,
                    "locked_fields": draft.locked_fields,
                    "base_revision": draft.base_revision,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            proposal_patches.append(
                BrainDumpProposalPatchDocument(
                    id="proposal_patch_"
                    + hashlib.sha256(identity.encode()).hexdigest()[:12],
                    sequence=sequence,
                    operation=draft.operation,
                    proposal_id=draft.proposal_id,
                    producer=draft.producer,
                    title=draft.title,
                    source_segment_ids=draft.source_segment_ids,
                    predecessor_ids=draft.predecessor_ids,
                    successor_ids=draft.successor_ids,
                    locked_fields=draft.locked_fields,
                    base_revision=draft.base_revision,
                    created_at=now,
                )
            )
        return proposal_patches

    @staticmethod
    def _proposal_document_to_reconciled(
        proposal: BrainDumpProposalDocument,
    ) -> ReconciledProposal:
        status_map: dict[
            str, Literal["provisional", "reconciled", "user_edited", "conflicted"]
        ] = {
            "provisional": "provisional",
            "wording_changing": "provisional",
            "ready_to_review": "reconciled",
            "user_edited": "user_edited",
            "reconciled": "reconciled",
            "conflicted": "conflicted",
        }
        return ReconciledProposal(
            id=proposal.id,
            title=proposal.title,
            source_segment_ids=proposal.source_segment_ids,
            status=status_map.get(proposal.status, "provisional"),
            predecessor_ids=proposal.predecessor_ids,
            successor_ids=proposal.successor_ids,
            locked_fields=proposal.locked_fields,
            conflicts=[
                ProposalConflict(
                    field=conflict.field,
                    current_value=conflict.current_value,
                    suggested_value=conflict.suggested_value,
                    producer=conflict.producer,
                    source_segment_ids=conflict.source_segment_ids,
                )
                for conflict in proposal.conflicts
            ],
            tombstoned=proposal.deleted,
            ordinal=proposal.ordinal,
            revision=proposal.revision,
            title_revision=proposal.title_revision,
        )

    def _reconcile_accurate_titles(
        self,
        existing: list[BrainDumpProposalDocument],
        titles: list[str],
        *,
        operation_id: str,
        source_segment_id: str,
        now: datetime,
    ) -> tuple[list[BrainDumpProposalDocument], list[ProposalPatch]]:
        """Reconcile accurate-STT titles through opaque-ID, lineage-aware patches.

        Identity/lineage/lock/stale-base decisions are delegated to
        ``apply_proposal_patches`` so the append-only patch contract (PA-04,
        PA-05) is real production behavior on the accurate-STT reconciliation
        path, not only a unit-tested pure module.
        """

        segment_ids = [source_segment_id]
        mutable = [proposal for proposal in existing if not proposal.deleted]
        base = [self._proposal_document_to_reconciled(proposal) for proposal in mutable]

        patches: list[ProposalPatch] = []

        def stable_id(title: str, lineage: str) -> str:
            identity = (
                f"{operation_id}|{source_segment_id}|{lineage}|{title.casefold()}"
            )
            return "proposal_" + hashlib.sha256(identity.encode()).hexdigest()[:12]

        if (
            len(mutable) == 1
            and len(titles) > 1
            and self._titles_form_split(mutable[0].title, titles)
        ):
            predecessor = mutable[0]
            patches.extend(
                ProposalPatch.split(
                    proposal_id=stable_id(title, predecessor.id),
                    title=title,
                    predecessor_ids=[predecessor.id],
                    source_segment_ids=segment_ids,
                )
                for title in titles
            )
        elif (
            len(mutable) > 1
            and len(titles) == 1
            and self._titles_form_merge(
                [proposal.title for proposal in mutable], titles[0]
            )
        ):
            predecessor_ids = [proposal.id for proposal in mutable]
            patches.append(
                ProposalPatch.merge(
                    proposal_id=stable_id(titles[0], "|".join(predecessor_ids)),
                    title=titles[0],
                    predecessor_ids=predecessor_ids,
                    source_segment_ids=segment_ids,
                )
            )
        elif (
            len(mutable) == 1
            and len(titles) == 1
            and not self._titles_refer_to_same_item(titles[0], mutable[0].title)
            and self._titles_share_first_word(titles[0], mutable[0].title)
            and self._proposal_identity_key(titles[0])
            != self._proposal_identity_key(mutable[0].title)
        ):
            predecessor = mutable[0]
            if predecessor.user_edited or predecessor.locked_fields:
                patches.append(
                    ProposalPatch.update(
                        proposal_id=predecessor.id,
                        title=titles[0],
                        source_segment_ids=segment_ids,
                        producer="reconciler",
                        base_revision=predecessor.title_revision,
                    )
                )
            else:
                patches.append(
                    ProposalPatch.supersede(
                        proposal_id=stable_id(titles[0], predecessor.id),
                        title=titles[0],
                        predecessor_ids=[predecessor.id],
                        source_segment_ids=segment_ids,
                    )
                )
        else:
            matched_ids: set[str] = set()
            for title in titles:
                candidates = [
                    proposal
                    for proposal in mutable
                    if proposal.id not in matched_ids
                    and self._titles_refer_to_same_item(title, proposal.title)
                ]
                if len(candidates) != 1:
                    candidates = [
                        proposal
                        for proposal in mutable
                        if proposal.id not in matched_ids
                        and self._proposal_identity_key(title)
                        == self._proposal_identity_key(proposal.title)
                    ]
                if len(candidates) != 1:
                    patches.append(
                        ProposalPatch.add(
                            proposal_id=stable_id(title, "new"),
                            title=title,
                            source_segment_ids=segment_ids,
                            producer="reconciler",
                        )
                    )
                    continue
                target = candidates[0]
                matched_ids.add(target.id)
                patches.append(
                    ProposalPatch.update(
                        proposal_id=target.id,
                        title=title,
                        source_segment_ids=segment_ids,
                        producer="reconciler",
                        base_revision=target.title_revision,
                    )
                )
            patches.extend(
                ProposalPatch.remove(proposal_id=proposal.id, producer="reconciler")
                for proposal in mutable
                if matched_ids
                and proposal.id not in matched_ids
                and not (proposal.user_edited or proposal.locked_fields)
                and not any(
                    patch.predecessor_ids and proposal.id in patch.predecessor_ids
                    for patch in patches
                )
            )

        projection = apply_proposal_patches(base, patches)
        by_existing_id = {proposal.id: proposal for proposal in existing}
        projected_by_id = {proposal.id: proposal for proposal in projection.history}
        ordered_ids = [proposal.id for proposal in existing]
        ordered_ids.extend(
            proposal.id
            for proposal in projection.history
            if proposal.id not in by_existing_id
        )
        ordered: list[BrainDumpProposalDocument] = []
        for proposal_id in ordered_ids:
            reconciled = projected_by_id.get(proposal_id)
            original = by_existing_id.get(proposal_id)
            if reconciled is None:
                if original is not None:
                    ordered.append(original)
                continue
            new_status = self._domain_status_to_doc_status(reconciled.status)
            new_conflicts = [
                self._domain_conflict_to_doc(conflict)
                for conflict in reconciled.conflicts
            ]
            if original is None:
                ordered.append(
                    BrainDumpProposalDocument(
                        id=reconciled.id,
                        ordinal=reconciled.ordinal,
                        title=reconciled.title,
                        status=new_status,
                        source_segment_ids=reconciled.source_segment_ids,
                        predecessor_ids=reconciled.predecessor_ids,
                        successor_ids=reconciled.successor_ids,
                        locked_fields=reconciled.locked_fields,
                        conflicts=new_conflicts,
                        deleted=reconciled.tombstoned,
                        title_revision=reconciled.title_revision,
                        created_at=now,
                        updated_at=now,
                        revision=reconciled.revision,
                    )
                )
                continue
            unchanged = (
                original.title == reconciled.title
                and original.source_segment_ids == reconciled.source_segment_ids
                and original.status == new_status
                and original.predecessor_ids == reconciled.predecessor_ids
                and original.successor_ids == reconciled.successor_ids
                and original.locked_fields == reconciled.locked_fields
                and len(original.conflicts) == len(new_conflicts)
                and original.deleted == reconciled.tombstoned
            )
            if unchanged:
                ordered.append(original)
            else:
                ordered.append(
                    original.model_copy(
                        update={
                            "title": reconciled.title,
                            "status": new_status,
                            "source_segment_ids": reconciled.source_segment_ids,
                            "predecessor_ids": reconciled.predecessor_ids,
                            "successor_ids": reconciled.successor_ids,
                            "locked_fields": reconciled.locked_fields,
                            "conflicts": new_conflicts,
                            "deleted": reconciled.tombstoned,
                            "title_revision": reconciled.title_revision,
                            "updated_at": now,
                            "revision": original.revision + 1,
                        }
                    )
                )
        return ordered, patches

    def _apply_reconciler_patches(
        self,
        existing: list[BrainDumpProposalDocument],
        patches: list[ProposalPatch],
        *,
        now: datetime,
    ) -> list[BrainDumpProposalDocument]:
        base = [
            self._proposal_document_to_reconciled(proposal)
            for proposal in existing
        ]
        projection = apply_proposal_patches(base, patches)
        by_existing_id = {proposal.id: proposal for proposal in existing}
        projected_by_id = {proposal.id: proposal for proposal in projection.history}
        ordered_ids = [proposal.id for proposal in existing]
        ordered_ids.extend(
            proposal.id
            for proposal in projection.history
            if proposal.id not in by_existing_id
        )
        ordered: list[BrainDumpProposalDocument] = []
        for proposal_id in ordered_ids:
            reconciled = projected_by_id.get(proposal_id)
            original = by_existing_id.get(proposal_id)
            if reconciled is None:
                if original is not None:
                    ordered.append(original)
                continue
            new_status = self._domain_status_to_doc_status(reconciled.status)
            new_conflicts = [
                self._domain_conflict_to_doc(conflict)
                for conflict in reconciled.conflicts
            ]
            if original is None:
                ordered.append(
                    BrainDumpProposalDocument(
                        id=reconciled.id,
                        ordinal=reconciled.ordinal,
                        title=reconciled.title,
                        status=new_status,
                        source_segment_ids=reconciled.source_segment_ids,
                        predecessor_ids=reconciled.predecessor_ids,
                        successor_ids=reconciled.successor_ids,
                        locked_fields=reconciled.locked_fields,
                        conflicts=new_conflicts,
                        deleted=reconciled.tombstoned,
                        title_revision=reconciled.title_revision,
                        created_at=now,
                        updated_at=now,
                        revision=reconciled.revision,
                    )
                )
                continue
            unchanged = (
                original.title == reconciled.title
                and original.source_segment_ids == reconciled.source_segment_ids
                and original.status == new_status
                and original.predecessor_ids == reconciled.predecessor_ids
                and original.successor_ids == reconciled.successor_ids
                and original.locked_fields == reconciled.locked_fields
                and len(original.conflicts) == len(new_conflicts)
                and original.deleted == reconciled.tombstoned
            )
            if unchanged:
                ordered.append(original)
                continue
            ordered.append(
                original.model_copy(
                    update={
                        "title": reconciled.title,
                        "status": new_status,
                        "source_segment_ids": reconciled.source_segment_ids,
                        "predecessor_ids": reconciled.predecessor_ids,
                        "successor_ids": reconciled.successor_ids,
                        "locked_fields": reconciled.locked_fields,
                        "conflicts": new_conflicts,
                        "deleted": reconciled.tombstoned,
                        "title_revision": reconciled.title_revision,
                        "updated_at": now,
                        "revision": original.revision + 1,
                    }
                )
            )
        return ordered

    def _reconciler_failure(
        self,
        operation: BrainDumpOperationDocument,
        *,
        checkpoint_segments: list[BrainDumpTranscriptSegmentDocument],
        checkpoint_runs: list[BrainDumpProviderRunDocument],
        input_hash: str,
        error: str,
        now: datetime,
        retryable: bool = False,
        attempt: int = 1,
        recovery_count: int = 0,
        error_code: str | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> BrainDumpOperationDocument:
        status: Literal["retryable_error", "terminal_error"] = (
            "retryable_error"
            if retryable and recovery_count < self.max_operation_recoveries
            else "terminal_error"
        )
        active_reconciler_run = operation.provider_runs[-1]
        return operation.model_copy(
            update={
                "status": status,
                "status_history": [
                    *operation.status_history,
                    "reconciling",
                    status,
                ],
                "segments": checkpoint_segments,
                "provider_runs": [
                    *checkpoint_runs,
                    active_reconciler_run.model_copy(
                        update={
                            "status": status,
                            "input_hash": input_hash,
                            "checkpoint": "accurate_transcribed",
                            "attempt": attempt,
                            "recovery_count": recovery_count,
                            "error": error,
                            "error_code": (
                                error_code if error_code is not None else error
                            )[:100],
                            "estimated_cost_usd": estimated_cost_usd,
                            "reserved_cost_usd": 0.0,
                            "consumed_cost_usd": estimated_cost_usd,
                            "lease_owner": None,
                            "lease_expires_at": None,
                            "updated_at": now,
                        }
                    ),
                ],
                "updated_at": now,
                "revision": operation.revision + 1,
            }
        )

    def _matching_proposal_index(
        self, proposals: list[BrainDumpProposalDocument], title: str
    ) -> int | None:
        for index, proposal in enumerate(proposals):
            if self._titles_refer_to_same_item(
                title, proposal.title
            ) or self._titles_share_first_word(title, proposal.title):
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
        proposal_index_by_title = {
            self._proposal_identity_key(proposal.title): index
            for index, proposal in enumerate(proposals)
            if not proposal.deleted
        }
        for title in candidates:
            existing_index = proposal_index_by_title.get(
                self._proposal_identity_key(title)
            )
            if existing_index is not None:
                proposal = proposals[existing_index]
                if proposal.user_edited or proposal.deleted:
                    continue
                if (
                    proposal.title == title
                    and proposal.source_segment_ids == segment_ids
                ):
                    continue
                proposals[existing_index] = proposal.model_copy(
                    update={
                        "title": title,
                        "status": status,
                        "source_segment_ids": segment_ids,
                        "updated_at": now,
                        "revision": proposal.revision + 1,
                    }
                )
                continue
            semantic_matches = [
                (index, proposal)
                for index, proposal in enumerate(proposals)
                if self._proposal_semantic_key(proposal.title)
                == self._proposal_semantic_key(title)
            ]
            protected_matches = [
                proposal
                for _index, proposal in semantic_matches
                if proposal.user_edited or proposal.deleted
            ]
            if protected_matches or any(
                (proposal.user_edited or proposal.deleted)
                and self._titles_share_first_word(title, proposal.title)
                for proposal in proposals
            ):
                # A conservative lock/deletion guard is allowed to omit an
                # ambiguous preview candidate; it must never overwrite it.
                continue
            mutable_matches = [
                (index, proposal)
                for index, proposal in semantic_matches
                if not proposal.deleted and not proposal.user_edited
            ]
            if len(mutable_matches) == 1:
                matched_index, proposal = mutable_matches[0]
                proposals[matched_index] = proposal.model_copy(
                    update={
                        "title": title,
                        "status": status,
                        "source_segment_ids": segment_ids,
                        "updated_at": now,
                        "revision": proposal.revision + 1,
                    }
                )
                proposal_index_by_title[self._proposal_identity_key(title)] = (
                    matched_index
                )
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
            proposal_index_by_title[self._proposal_identity_key(title)] = (
                len(proposals) - 1
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

    @classmethod
    def _proposal_identity_key(cls, title: str) -> str:
        """Identity is content-derived, never inferred from a candidate position."""

        return cls._normalized_transcript_for_replacement(title)

    @classmethod
    def _proposal_semantic_key(cls, title: str) -> str:
        """Use a unique two-token key only to preserve an existing opaque ID."""

        return " ".join(cls._proposal_identity_key(title).split()[:2])

    @staticmethod
    def _extract_task_titles(text: str) -> list[str]:
        """Heuristically split live browser-preview text into draft titles.

        This feeds only the local, non-committable "fast" preview proposals
        shown while the user is still talking (see ``append_brain_dump_transcript``).
        It must never gain fixture-specific literal branches: those belong to
        test-only deterministic providers, not this always-on production path.
        Canonical tasks may only be created from a sealed, reconciled batch —
        enforced separately in ``commit_brain_dump_operation`` — so this
        heuristic's imprecision cannot itself produce an invented task.
        """

        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []
        rough_parts = re.split(
            r"(?:\s*\d+[.)]\s+|[.;\n]+|\bthen\b|\bпотом\b)",
            normalized,
            flags=re.IGNORECASE,
        )
        titles: list[str] = []
        seen: set[str] = set()
        for part in rough_parts:
            title = re.sub(r"^[-*•\s]+", "", part).strip(" ,")
            title = re.sub(
                r"^(?:and\s+)?(?:i\s+)?(?:need|should|must|have)\s+to\s+",
                "",
                title,
                flags=re.IGNORECASE,
            )
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
        return bool(
            candidate_words
            and existing_words
            and candidate_words[0] == existing_words[0]
        )

    @staticmethod
    def _title_content_words(title: str) -> set[str]:
        return {
            word
            for word in re.findall(r"[\w']+", title.casefold())
            if word not in {"a", "an", "and", "the", "to"}
        }

    @classmethod
    def _titles_form_split(cls, predecessor: str, successors: list[str]) -> bool:
        """Require textual evidence before emitting structural split lineage."""

        predecessor_words = cls._title_content_words(predecessor)
        successor_words = set().union(
            *(cls._title_content_words(title) for title in successors)
        )
        return bool(predecessor_words and successor_words) and successor_words <= (
            predecessor_words
        )

    @classmethod
    def _titles_form_merge(cls, predecessors: list[str], successor: str) -> bool:
        """Require textual evidence before emitting structural merge lineage."""

        predecessor_words = set().union(
            *(cls._title_content_words(title) for title in predecessors)
        )
        successor_words = cls._title_content_words(successor)
        return bool(predecessor_words and successor_words) and predecessor_words <= (
            successor_words
        )

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
                raise ValidationFailure(
                    "Task contexts must be active; task tags must be active."
                )

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
                raise ValidationFailure(
                    "Task contexts must be active; task tags must be active."
                )
            return tag, None
        name = display_tag_name(ref.name or "")
        normalized = normalize_task_name(name, strip_tag_prefix=True)
        for existing in self.task_repo.list_tags_for_owner(owner_id=owner_id):
            if existing.normalized_name != normalized:
                continue
            if existing.state != "active":
                raise ValidationFailure(
                    "Task contexts must be active; task tags must be active."
                )
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
        haystack = cls._normalize_for_search(
            "\n".join([task.title, task.details or ""])
        )
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
