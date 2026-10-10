"""Application service for owner-scoped native GTD tasks."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Concatenate, Protocol, cast

from pydantic import BaseModel

from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.schemas.tasks import (
    ExpectedRevisionRequest,
    ProjectCreateRequest,
    ProjectListState,
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
from app.utils.idempotency import (
    ReplayFingerprint,
    request_fingerprint,
    require_matching_replay,
)
from app.utils.identifiers import generate_id
from app.utils.time import utcnow

from . import formulation
from .domain import (
    FormulationSettingsDocument,
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
from .review_domain import (
    REVIEW_COMMAND_PREFIXES,
    FormulationView,
    ReviewSettingsDocument,
    formulation_view,
    task_clock,
    with_clock,
)
from .rust_task_facade import RustTaskFacade

# Spec 020: content-free clock events (ids only, FR-044).
review_logger = logging.getLogger("app.modules.tasks.review")

_OPEN_STATES = ("inbox", "next", "waiting", "someday")
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}


def _smart_add_namesake[Namesake: (ProjectDocument, TagDocument)](
    records: Iterable[Namesake], normalized_name: str
) -> tuple[Namesake | None, bool]:
    """Pick the record a Smart Add name resolves to.

    Returns ``(active, has_inactive)``. When several active records share the
    normalized name the OLDEST wins, ordered by ``(created_at, id)`` -- the order
    the Swift planner and the Rust Smart Add rule use (spec 026 owner decision,
    2026-10-09). ``created_at`` is required on both documents, so there is no
    undated fallback. An inactive namesake only matters when no active one
    exists: the caller then refuses instead of creating a second record.
    """

    namesakes = sorted(
        (record for record in records if record.normalized_name == normalized_name),
        key=lambda record: (record.created_at, record.id),
    )
    active = next((record for record in namesakes if record.state == "active"), None)
    return active, bool(namesakes) and active is None


FORMULATION_SETTINGS_FIELD = "formulation_settings"
"""Key of the settings snapshot inside a stored ``TaskDocument`` response body."""


@dataclass(frozen=True, slots=True)
class TaskCommandResult:
    """A task command's document and the settings its response projects with.

    ``formulation_settings`` is the snapshot the idempotency record keeps
    (spec 020, http "Mutations"); ``None`` for a record written before it,
    which then projects with the live settings.
    """

    task: TaskDocument
    formulation_settings: FormulationSettingsDocument | None


def _stored_formulation_settings(
    record: IdempotencyRecord,
) -> FormulationSettingsDocument | None:
    stored = record.response_body.get(FORMULATION_SETTINGS_FIELD)
    if stored is None:
        return None
    return FormulationSettingsDocument.model_validate(stored)


class SerializedWriter(Protocol):
    """A service whose commands run under the owner lock with idempotency.

    Spec 020 (c2 AC-05): ``TaskService`` and ``ReviewService`` both implement
    it; each reconciles only the idempotency keys it issues.
    """

    @property
    def task_repo(self) -> TaskRepository: ...

    @property
    def clock(self) -> Callable[[], datetime]: ...

    def _reconcile_idempotent_result(self, *, owner_id: str, key: str) -> None: ...


def serialized_write[Writer: SerializedWriter, **P, Result](
    command: Callable[Concatenate[Writer, P], Result],
) -> Callable[Concatenate[Writer, P], Result]:
    """Hold the owner command lock over idempotency and resource persistence."""

    def wrapped(service: Writer, /, *args: P.args, **kwargs: P.kwargs) -> Result:
        owner_id = cast(str, kwargs["owner_id"])
        idempotency_key = cast(str, kwargs["idempotency_key"])
        with service.task_repo.command_lock(owner_id):
            service.task_repo.purge_expired_idempotency(
                owner_id=owner_id, now=service.clock()
            )
            service._reconcile_idempotent_result(owner_id=owner_id, key=idempotency_key)
            return command(service, *args, **kwargs)

    return wrapped


_serialized_write = serialized_write


def _stable_request_hash(command: str, payload: BaseModel) -> str:
    """``request_fingerprint`` that ignores an unset ``new_formulation_id``.

    Spec 020 added the optional field to three task requests. A body that does
    not send it hashes exactly as it did before the field existed, so an
    idempotent retry that crosses the deploy stays a replay (http §1: old
    clients keep working).
    """

    if (
        "new_formulation_id" not in type(payload).model_fields
        or "new_formulation_id" in payload.model_fields_set
    ):
        return request_fingerprint(command, payload)
    body = payload.model_dump(mode="json")
    body.pop("new_formulation_id", None)
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


class TaskService:
    """Owns canonical GTD records and their owner-scoped projections."""

    def __init__(
        self,
        task_repo: TaskRepository,
        *,
        clock: Callable[[], datetime] = utcnow,
        rust_facade: RustTaskFacade | None = None,
        rust_core_enabled: Callable[[str], bool] | None = None,
    ) -> None:
        self.task_repo = task_repo
        # Spec 026 T018: with ``rust_core_sync`` effective for the owner, task and
        # organization decisions come from the shared Rust core through this
        # facade. Without both seams (or with the flag off) every command keeps
        # its Python rules, byte for byte.
        self._rust_facade = rust_facade
        self._rust_core_enabled = rust_core_enabled
        # The one time seam of the task module (spec 020, research R21): every
        # timestamp and the idempotency purge read this injected clock, so tests
        # drive time through ``frozen_clock`` instead of patching ``utcnow``.
        self.clock = clock

    def _rust(self, owner_id: str) -> RustTaskFacade | None:
        """The Rust facade when ``rust_core_sync`` is effective for this owner."""

        facade = self._rust_facade
        if facade is None or self._rust_core_enabled is None:
            return None
        return facade if self._rust_core_enabled(owner_id) else None

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

        now = self.clock()
        rust = self._rust(owner_id)
        if rust is not None:
            project = rust.create_project(payload, owner_id=owner_id, now=now)
        else:
            name = display_project_name(payload.name)
            project = ProjectDocument(
                id=generate_id("project"),
                owner_id=owner_id,
                name=name,
                normalized_name=normalize_task_name(name),
                color=payload.color,
                desired_outcome=payload.desired_outcome,
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

        now = self.clock()
        rust = self._rust(owner_id)
        if rust is not None:
            tag = rust.create_tag(payload, owner_id=owner_id, now=now)
        else:
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

    def create_task(
        self,
        payload: TaskCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskDocument:
        return self.create_task_result(
            payload, owner_id=owner_id, idempotency_key=idempotency_key
        ).task

    @_serialized_write
    def create_task_result(
        self,
        payload: TaskCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskCommandResult:
        """``POST /tasks`` with the settings snapshot its response projects with."""

        command = "create_task"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._task_command_result(record, owner_id=owner_id)

        rust = self._rust(owner_id)
        if rust is not None:
            task = rust.create_task(payload, owner_id=owner_id, now=self.clock())
        else:
            task = self._python_created_task(
                payload, owner_id=owner_id, now=self.clock()
            )
        snapshot = self.formulation_settings(owner_id)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=task.id,
            response=task,
            formulation_settings=snapshot,
        )
        self.task_repo.create(task)
        return TaskCommandResult(task, snapshot)

    def _python_created_task(
        self, payload: TaskCreateRequest, *, owner_id: str, now: datetime
    ) -> TaskDocument:
        """The task ``POST /tasks`` creates under the Python rules."""

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
        return self._started_if_next(task, payload.new_formulation_id, now=now)

    @_serialized_write
    def create_native_inbox_task(
        self,
        *,
        owner_id: str,
        title: str,
        source_capture_ids: list[str],
        idempotency_key: str,
    ) -> TaskDocument:
        """In-process ``TaskPort`` adapter for a confirmed Brain Dump action.

        Owner-serialized like every other Tasks write: the deterministic child
        idempotency key is resolved and the idempotency record + task are
        persisted inside one owner-locked transaction. That makes "one child
        key -> at most one task" real under a concurrent commit replay -- two
        racing callers cannot each pass the idempotency check and mint separate
        tasks, and a fault can never leave the record and the task out of step.
        """

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
        now = self.clock()
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
        now = self.clock()
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
        task = self._started_if_next(task, None, now=now)
        result = SmartAddTaskResultDocument(
            task=task,
            project=project,
            tags=tags,
            created=SmartAddCreatedDocument(
                project_id=created_project_id,
                tag_ids=created_tag_ids,
            ),
            formulation_settings=self.formulation_settings(owner_id),
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

        now = self.clock()
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

        now = self.clock()
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
        now = self.clock()
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
        now = self.clock()
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
        now = self.clock()
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

    def update_task(
        self,
        task_id: str,
        payload: TaskUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskDocument:
        return self.update_task_result(
            task_id, payload, owner_id=owner_id, idempotency_key=idempotency_key
        ).task

    @_serialized_write
    def update_task_result(
        self,
        task_id: str,
        payload: TaskUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskCommandResult:
        """``PATCH /tasks/{id}`` with the settings snapshot of its response."""

        command = f"update_task:{task_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._task_command_result(record, owner_id=owner_id)

        task = self.get_task(task_id, owner_id=owner_id)
        rust = self._rust(owner_id)
        if rust is not None:
            updated = rust.update_task(
                task, payload, owner_id=owner_id, now=self.clock()
            )
            if task.state == "next" and updated.due_date != task.due_date:
                # The Python rule logs this where it moves the floor (FR-046).
                review_logger.info(
                    "review_due_date_moved owner_id=%s task_id=%s", owner_id, task.id
                )
        else:
            updated = self._python_updated_task(task, payload, owner_id=owner_id)
        snapshot = self.formulation_settings(owner_id)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
            formulation_settings=snapshot,
        )
        self.task_repo.save(updated)
        return TaskCommandResult(updated, snapshot)

    def _python_updated_task(
        self, task: TaskDocument, payload: TaskUpdateRequest, *, owner_id: str
    ) -> TaskDocument:
        """The task ``PATCH /tasks/{id}`` yields under the Python rules."""

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
            # Spec 021 (ADR-0020): a membership the task already has is never
            # re-validated, so an archived project's tasks stay editable.
            project_id=project_id if project_id != task.project_id else None,
            tag_ids=tag_ids or [],
        )
        now = self.clock()
        updated = self._validated_task_update(
            task,
            title=payload.title if "title" in fields else task.title,
            details=payload.details if "details" in fields else task.details,
            project_id=project_id,
            tag_ids=tag_ids or [],
            due_date=payload.due_date if "due_date" in fields else task.due_date,
            priority=payload.priority if "priority" in fields else task.priority,
            waiting_for=waiting_for,
            updated_at=now,
            revision=task.revision + 1,
        )
        return self._clock_after_edit(
            task,
            updated,
            owner_id=owner_id,
            now=now,
            new_formulation_id=payload.new_formulation_id,
        )

    def transition_task(
        self,
        task_id: str,
        payload: TaskTransitionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskDocument:
        return self.transition_task_result(
            task_id, payload, owner_id=owner_id, idempotency_key=idempotency_key
        ).task

    @_serialized_write
    def transition_task_result(
        self,
        task_id: str,
        payload: TaskTransitionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> TaskCommandResult:
        """``POST /tasks/{id}/transitions`` with its response's settings snapshot."""

        command = f"transition_task:{task_id}"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._task_command_result(record, owner_id=owner_id)

        task = self.get_task(task_id, owner_id=owner_id)
        now = self.clock()
        rust = self._rust(owner_id)
        if rust is not None:
            moved = rust.transition_task(task, payload, owner_id=owner_id, now=now)
            updated = moved.task
        else:
            self._assert_current(task, payload.expected_revision)
            updated = self._transitioned(
                task,
                action=payload.action,
                to_state=payload.to_state,
                waiting_for=payload.waiting_for,
                new_formulation_id=payload.new_formulation_id,
                owner_id=owner_id,
                now=now,
            )
        snapshot = self.formulation_settings(owner_id)
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated.id,
            response=updated,
            formulation_settings=snapshot,
        )
        self.task_repo.save(updated)
        if rust is not None:
            if moved.park_ack is not None:
                self.task_repo.save_park_ack(moved.park_ack)
        else:
            self._note_park_return(task, updated, owner_id=owner_id, now=now)
        return TaskCommandResult(updated, snapshot)

    def _transitioned(
        self,
        task: TaskDocument,
        *,
        action: str,
        to_state: str | None,
        waiting_for: str | None,
        new_formulation_id: str | None,
        owner_id: str,
        now: datetime,
    ) -> TaskDocument:
        """One transition as a new document at ``revision + 1`` (no write).

        Undecorated on purpose: ``ReviewService`` calls it inside its own
        serialized write so a decision and its move are one transaction.
        Maintains the formulation clock (formulation-clock §3): leaving Next
        closes the formulation, entering Next starts one, leaving Someday drops
        the park marker.
        """

        updates: dict[str, Any]
        if action == "complete":
            if task.state not in _OPEN_STATES:
                raise ValidationFailure("Only open tasks can be completed.")
            updates = {
                "state": "completed",
                "completed_at": now,
                "cancelled_at": None,
                "waiting_for": None,
                "waiting_since": None,
            }
        elif action == "cancel":
            if task.state not in _OPEN_STATES:
                raise ValidationFailure("Only open tasks can be cancelled.")
            updates = {
                "state": "cancelled",
                "cancelled_at": now,
                "completed_at": None,
                "waiting_for": None,
                "waiting_since": None,
            }
        elif action == "reopen":
            if task.state not in {"completed", "cancelled"} or to_state is None:
                raise ValidationFailure(
                    "Reopen requires a terminal task and an open destination."
                )
            reopened_for = (
                self._waiting_for(waiting_for) if to_state == "waiting" else None
            )
            updates = {
                "state": to_state,
                "completed_at": None,
                "cancelled_at": None,
                "waiting_for": reopened_for,
                "waiting_since": now if reopened_for else None,
            }
        else:
            if task.state not in _OPEN_STATES or to_state is None:
                raise ValidationFailure("Move requires an open task and destination.")
            if task.state == to_state:
                raise ValidationFailure("Move requires a different open destination.")
            moved_for = (
                self._waiting_for(waiting_for) if to_state == "waiting" else None
            )
            updates = {
                "state": to_state,
                "waiting_for": moved_for,
                "waiting_since": now if moved_for else None,
            }
        updated = self._validated_task_update(
            task, **updates, updated_at=now, revision=task.revision + 1
        )
        clock = formulation.move(
            task_clock(task),
            to_state=updated.state,
            settings=self.clock_settings(owner_id),
            now=now,
            new_formulation_id=(
                self._formulation_id(new_formulation_id)
                if updated.state == "next"
                else None
            ),
        )
        return with_clock(updated, clock)

    def _note_park_return(
        self,
        before: TaskDocument,
        after: TaskDocument,
        *,
        owner_id: str,
        now: datetime,
    ) -> None:
        """A parked task moved back to Next: ``returned_at`` on its park row.

        Same transaction as the move (data-model E6), so "share of parks later
        returned" is derivable from stored ids and instants. The row is written
        at park time. Should it be missing, nothing is written: its ``source``
        is unknown and is never made up. The warning carries ids only.
        """

        parked = before.parked
        if parked is None or before.state != "someday" or after.state != "next":
            return
        ack = self.task_repo.get_park_ack(owner_id, before.id, parked.formulation_id)
        if ack is None:
            review_logger.warning(
                "review_park_return_unrecorded owner_id=%s task_id=%s "
                "formulation_id=%s",
                owner_id,
                before.id,
                parked.formulation_id,
            )
            return
        self.task_repo.save_park_ack(ack.model_copy(update={"returned_at": now}))

    def _started_if_next(
        self, task: TaskDocument, new_formulation_id: str | None, *, now: datetime
    ) -> TaskDocument:
        """A task created in Next starts its first formulation (FR-001)."""

        if task.state != "next":
            return task
        clock = formulation.start_formulation(
            task_clock(task),
            formulation_id=self._formulation_id(new_formulation_id),
            now=now,
        )
        return with_clock(task, clock)

    def _clock_after_edit(
        self,
        before: TaskDocument,
        after: TaskDocument,
        *,
        owner_id: str,
        now: datetime,
        new_formulation_id: str | None,
    ) -> TaskDocument:
        """PATCH in Next: a substantive title restarts, a due date floors.

        Notes, tags, project, priority and waiting-for leave the clock alone
        (FR-003). A due date set, moved or removed raises the task floor to
        ``max(existing, now + 7 d)`` (FR-046) and logs a content-free event.
        """

        if before.state != "next":
            return after
        clock = task_clock(before)
        if after.title != before.title and formulation.is_substantive(
            before.title, after.title
        ):
            clock = formulation.change_title(
                clock,
                title=after.title,
                settings=self.clock_settings(owner_id),
                now=now,
                new_formulation_id=self._formulation_id(new_formulation_id),
            )
        if after.due_date != before.due_date:
            clock = formulation.change_due_date(clock, due_date=after.due_date, now=now)
            review_logger.info(
                "review_due_date_moved owner_id=%s task_id=%s", owner_id, before.id
            )
        return with_clock(after, clock)

    @staticmethod
    def _formulation_id(requested: str | None) -> str:
        """The client's id when it sent one (http §1), else a server-minted id."""

        return requested if requested is not None else generate_id("form")

    def clock_settings(self, owner_id: str) -> formulation.OwnerClockSettings:
        """The owner's clock inputs (one ``review_settings`` read)."""

        stored = self.task_repo.get_review_settings(owner_id)
        settings = stored or ReviewSettingsDocument(owner_id=owner_id)
        return settings.clock_settings()

    def formulation_settings(self, owner_id: str) -> FormulationSettingsDocument:
        """The snapshot a command's idempotency record keeps (http "Mutations")."""

        return FormulationSettingsDocument.of(self.clock_settings(owner_id))

    def formulation_views(
        self,
        owner_id: str,
        tasks: Iterable[TaskDocument],
        *,
        settings: FormulationSettingsDocument | None = None,
    ) -> dict[str, FormulationView]:
        """``TaskResponse.formulation`` per task, one settings read (http §2).

        ``settings`` is a stored response's snapshot: a replay projects with
        it, so it returns the original response; without one, live settings.
        """

        clock_settings = (
            self.clock_settings(owner_id)
            if settings is None
            else settings.clock_settings()
        )
        views: dict[str, FormulationView] = {}
        for task in tasks:
            view = formulation_view(task, clock_settings)
            if view is not None:
                views[task.id] = view
        return views

    def get_task(self, task_id: str, *, owner_id: str) -> TaskDocument:
        return self.task_repo.get_for_owner(task_id, owner_id=owner_id)

    def completed_task_count(self, *, owner_id: str) -> int:
        """Return the owner's current completed top-level task count."""

        return self.task_repo.count_for_owner_by_state(
            owner_id=owner_id, state="completed"
        )

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

    def list_projects(
        self, *, owner_id: str, state: ProjectListState = "active"
    ) -> list[ProjectDocument]:
        return sorted(
            (
                project
                for project in self.task_repo.list_projects_for_owner(owner_id=owner_id)
                if state == "all" or project.state == state
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

    def open_task_counts_by_project(self, *, owner_id: str) -> dict[str, int]:
        """Open task counts for every project, from one load of the tasks."""

        counts: dict[str, int] = {}
        for task in self.task_repo.list_for_owner(owner_id=owner_id):
            if task.project_id is not None and task.state in _OPEN_STATES:
                counts[task.project_id] = counts.get(task.project_id, 0) + 1
        return counts

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
        rust = self._rust(owner_id)
        if rust is not None:
            updated = rust.update_project(
                project, payload, owner_id=owner_id, now=self.clock()
            )
        else:
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
                    "desired_outcome": (
                        payload.desired_outcome
                        if "desired_outcome" in fields
                        else project.desired_outcome
                    ),
                    "updated_at": self.clock(),
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
        now = self.clock()
        rust = self._rust(owner_id)
        if rust is not None:
            updated_project = rust.archive_project(
                project, payload, owner_id=owner_id, now=now
            )
        else:
            self._assert_revision(
                "Project", project.id, project.revision, payload.expected_revision
            )
            # Archiving keeps every membership (ADR-0020). A repeat archive changes
            # only the revision and the timestamp: archived_at and the marker are
            # the one signal a pre-feature archive has (data-model E1).
            repeat = project.state == "archived"
            updated_project = project.model_copy(
                update={
                    "state": "archived",
                    "updated_at": now,
                    "revision": project.revision + 1,
                    **(
                        {}
                        if repeat
                        else {"archived_at": now, "archived_before_lossless": False}
                    ),
                }
            )
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=updated_project.id,
            response=updated_project,
        )
        self.task_repo.save_project(updated_project)
        return updated_project

    @_serialized_write
    def unarchive_project(
        self,
        project_id: str,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> ProjectDocument:
        command = f"unarchive_project:{project_id}"
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
        rust = self._rust(owner_id)
        if rust is not None:
            unarchived = rust.unarchive_project(
                project, payload, owner_id=owner_id, now=self.clock()
            )
            if unarchived is None:
                return project
            updated = unarchived
        else:
            if project.state == "active":
                # Checked before the revision: a retry after the key expired still
                # carries the old revision and must get the same answer (http §3).
                return project
            self._assert_revision(
                "Project", project.id, project.revision, payload.expected_revision
            )
            updated = project.model_copy(
                update={
                    "state": "active",
                    "archived_at": None,
                    "updated_at": self.clock(),
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
        rust = self._rust(owner_id)
        if rust is not None:
            updated = rust.update_tag(tag, payload, owner_id=owner_id, now=self.clock())
        else:
            self._assert_revision(
                "Tag", tag.id, tag.revision, payload.expected_revision
            )
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
                    "updated_at": self.clock(),
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
        now = self.clock()
        rust = self._rust(owner_id)
        if rust is not None:
            deleted = rust.delete_tag(tag, payload, owner_id=owner_id, now=now)
            updated_tag, saved_tasks = deleted.tag, deleted.affected
        else:
            self._assert_revision(
                "Tag", tag.id, tag.revision, payload.expected_revision
            )
            updated_tag = tag.model_copy(
                update={
                    "state": "deleted",
                    "updated_at": now,
                    "revision": tag.revision + 1,
                }
            )
            saved_tasks = [
                task.model_copy(
                    update={
                        "tag_ids": [
                            existing for existing in task.tag_ids if existing != tag_id
                        ],
                        "updated_at": now,
                        "revision": task.revision + 1,
                    }
                )
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
        for task in saved_tasks:
            self.task_repo.save(task)
        return updated_tag

    def _idempotency_record(
        self, *, owner_id: str, key: str, command: str, request_hash: str
    ) -> IdempotencyRecord | None:
        record = self.task_repo.get_idempotency(owner_id=owner_id, key=key)
        if record is None:
            return None
        require_matching_replay(
            ReplayFingerprint(record.command, record.request_hash),
            key=key,
            command=command,
            request_hash=request_hash,
        )
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
        if record.command.startswith(REVIEW_COMMAND_PREFIXES):
            # Spec 020: composite review results are ReviewService's to
            # reconcile; their bodies are not task snapshots.
            return
        if record.command == "create_project" or record.command.startswith(
            ("update_project:", "archive_project:", "unarchive_project:")
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
        formulation_settings: FormulationSettingsDocument | None = None,
    ) -> None:
        """Persist one command's result; also its response's settings snapshot.

        ``formulation_settings`` is for a bare ``TaskDocument`` body: it rides
        beside the task's fields under ``FORMULATION_SETTINGS_FIELD``, which
        ``TaskDocument`` ignores on load, so the reconciler and older code read
        the body unchanged. Composite results carry it as their own field.
        """

        body = response.model_dump(mode="json")
        if formulation_settings is not None:
            body[FORMULATION_SETTINGS_FIELD] = formulation_settings.model_dump(
                mode="json"
            )
        self.task_repo.save_idempotency(
            owner_id=owner_id,
            record=IdempotencyRecord(
                key=key,
                command=command,
                request_hash=request_hash,
                resource_id=resource_id,
                response_body=body,
                created_at=self.clock(),
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

    def _task_command_result(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> TaskCommandResult:
        """A replay: the stored task and the settings its first response used."""

        return TaskCommandResult(
            self._task_result(record, owner_id=owner_id),
            _stored_formulation_settings(record),
        )

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
            ProjectCreateRequest
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
        return _stable_request_hash(command, payload)

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
        existing, has_inactive = _smart_add_namesake(
            self.task_repo.list_projects_for_owner(owner_id=owner_id), normalized
        )
        if existing is not None:
            return existing, None
        if has_inactive:
            raise ValidationFailure("Task project must be active.")
        now = self.clock()
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
        existing, has_inactive = _smart_add_namesake(
            self.task_repo.list_tags_for_owner(owner_id=owner_id), normalized
        )
        if existing is not None:
            return existing, None
        if has_inactive:
            raise ValidationFailure(
                "Task contexts must be active; task tags must be active."
            )
        now = self.clock()
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
