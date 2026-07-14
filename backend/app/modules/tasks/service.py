"""Application service for owner-scoped native GTD tasks."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Concatenate, ParamSpec, TypeVar, cast

from app.exceptions import ConflictError, ValidationFailure
from app.schemas.tasks import (
    ContextCreateRequest,
    ProjectCreateRequest,
    TaskCommentCreateRequest,
    TaskCreateRequest,
    TaskSubtaskCreateRequest,
    TaskTransitionRequest,
    TaskUpdateRequest,
)
from app.utils.identifiers import generate_id
from app.utils.time import utcnow

from .domain import (
    ContextDocument,
    IdempotencyRecord,
    ProjectDocument,
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)
from .repository import TaskRepository

_OPEN_STATES = ("inbox", "next", "waiting", "someday")

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
        with service.task_repo.command_lock(owner_id):
            service._reconcile_idempotent_results(owner_id=owner_id)
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
        project = ProjectDocument(
            id=generate_id("project"),
            owner_id=owner_id,
            name=payload.name,
            color=payload.color,
            created_at=now,
            updated_at=now,
        )
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
    def create_context(
        self,
        payload: ContextCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
    ) -> ContextDocument:
        command = "create_context"
        request_hash = self._request_hash(command, payload)
        record = self._idempotency_record(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
        )
        if record is not None:
            return self._context_result(record, owner_id=owner_id)

        now = utcnow()
        context = ContextDocument(
            id=generate_id("context"),
            owner_id=owner_id,
            name=payload.name if payload.name.startswith("@") else f"@{payload.name}",
            created_at=now,
            updated_at=now,
        )
        self._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command=command,
            request_hash=request_hash,
            resource_id=context.id,
            response=context,
        )
        self.task_repo.create_context(context)
        return context

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
            context_ids=payload.context_ids,
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
            context_ids=payload.context_ids,
            due_date=payload.due_date,
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
        project_id = payload.project_id if "project_id" in fields else task.project_id
        context_ids = (
            payload.context_ids if "context_ids" in fields else task.context_ids
        )
        self._assert_active_references(
            owner_id=owner_id,
            project_id=project_id,
            context_ids=context_ids or [],
        )
        updated = self._validated_task_update(
            task,
            title=payload.title if "title" in fields else task.title,
            details=payload.details if "details" in fields else task.details,
            project_id=project_id,
            context_ids=context_ids or [],
            due_date=payload.due_date if "due_date" in fields else task.due_date,
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
        context_id: str | None,
        unassigned_project: bool,
        include_completed: bool,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[TaskDocument], str | None, bool, dict[str, int]]:
        if project_id is not None and unassigned_project:
            raise ValidationFailure(
                "project_id and unassigned_project cannot be used together."
            )
        if project_id is not None:
            self.task_repo.get_project_for_owner(project_id, owner_id=owner_id)
        if context_id is not None:
            self.task_repo.get_context_for_owner(context_id, owner_id=owner_id)

        filters = {
            "state": state,
            "project_id": project_id,
            "context_id": context_id,
            "unassigned_project": unassigned_project,
            "include_completed": include_completed,
        }
        last_sort_key = self._decode_cursor(cursor, filters) if cursor else None
        all_filtered = self._filter_tasks(
            self.task_repo.list_for_owner(owner_id=owner_id),
            state=state,
            project_id=project_id,
            context_id=context_id,
            unassigned_project=unassigned_project,
            include_completed=include_completed,
        )
        if last_sort_key is not None:
            all_filtered = [
                task for task in all_filtered if self._sort_key(task) > last_sort_key
            ]
        page = all_filtered[:limit]
        has_more = len(all_filtered) > limit
        next_cursor = (
            self._encode_cursor(filters, self._sort_key(page[-1])) if has_more else None
        )
        counts = self._open_counts(
            owner_id=owner_id,
            project_id=project_id,
            context_id=context_id,
            unassigned_project=unassigned_project,
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

    def list_contexts(self, *, owner_id: str) -> list[ContextDocument]:
        return sorted(
            (
                context
                for context in self.task_repo.list_contexts_for_owner(owner_id=owner_id)
                if context.state == "active"
            ),
            key=lambda context: (context.name.strip().casefold(), context.id),
        )

    def get_project(self, project_id: str, *, owner_id: str) -> ProjectDocument:
        return self.task_repo.get_project_for_owner(project_id, owner_id=owner_id)

    def get_context(self, context_id: str, *, owner_id: str) -> ContextDocument:
        return self.task_repo.get_context_for_owner(context_id, owner_id=owner_id)

    def _idempotency_record(
        self, *, owner_id: str, key: str, command: str, request_hash: str
    ) -> IdempotencyRecord | None:
        record = self.task_repo.get_idempotency(owner_id=owner_id, key=key)
        if record is None:
            return None
        if record.command != command or record.request_hash != request_hash:
            raise ConflictError("Idempotency-Key", key)
        return record

    def _reconcile_idempotent_results(self, *, owner_id: str) -> None:
        """Apply recorded results left durable before their resource write."""

        for record in self.task_repo.list_idempotency_for_owner(owner_id=owner_id):
            if record.command == "create_project":
                self._project_result(record, owner_id=owner_id)
            elif record.command == "create_context":
                self._context_result(record, owner_id=owner_id)
            elif record.command.startswith("create_subtask:"):
                subtask = TaskSubtaskDocument.model_validate(record.response_body)
                self._subtask_result(record, owner_id=owner_id, task_id=subtask.task_id)
            elif record.command.startswith("create_comment:"):
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
        response: (
            ProjectDocument
            | ContextDocument
            | TaskDocument
            | TaskSubtaskDocument
            | TaskCommentDocument
        ),
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
        path = self.task_repo.project_path(owner_id, project.id)
        if not path.exists():
            self.task_repo.create_project(project)
        return project

    def _context_result(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> ContextDocument:
        context = ContextDocument.model_validate(record.response_body)
        path = self.task_repo.context_path(owner_id, context.id)
        if not path.exists():
            self.task_repo.create_context(context)
        return context

    def _task_result(self, record: IdempotencyRecord, *, owner_id: str) -> TaskDocument:
        task = TaskDocument.model_validate(record.response_body)
        path = self.task_repo.task_path(owner_id, task.id)
        if not path.exists():
            self.task_repo.create(task)
        else:
            current = self.task_repo.get_for_owner(task.id, owner_id=owner_id)
            if current.revision < task.revision:
                self.task_repo.save(task)
        return task

    def _subtask_result(
        self, record: IdempotencyRecord, *, owner_id: str, task_id: str
    ) -> TaskSubtaskDocument:
        subtask = TaskSubtaskDocument.model_validate(record.response_body)
        path = self.task_repo.subtask_path(owner_id, task_id, subtask.id)
        if not path.exists():
            self.task_repo.create_subtask(subtask)
        return subtask

    def _comment_result(
        self, record: IdempotencyRecord, *, owner_id: str, task_id: str
    ) -> TaskCommentDocument:
        comment = TaskCommentDocument.model_validate(record.response_body)
        path = self.task_repo.comment_path(owner_id, task_id, comment.id)
        if not path.exists():
            self.task_repo.create_comment(comment)
        return comment

    @staticmethod
    def _request_hash(
        command: str,
        payload: (
            ProjectCreateRequest
            | ContextCreateRequest
            | TaskCreateRequest
            | TaskSubtaskCreateRequest
            | TaskCommentCreateRequest
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

    def _assert_active_references(
        self,
        *,
        owner_id: str,
        project_id: str | None,
        context_ids: list[str],
    ) -> None:
        if project_id is not None:
            project = self.task_repo.get_project_for_owner(
                project_id, owner_id=owner_id
            )
            if project.state != "active":
                raise ValidationFailure("Task project must be active.")
        if len(set(context_ids)) != len(context_ids):
            raise ValidationFailure("Task contexts cannot contain duplicates.")
        for context_id in context_ids:
            context = self.task_repo.get_context_for_owner(
                context_id, owner_id=owner_id
            )
            if context.state != "active":
                raise ValidationFailure("Task contexts must be active.")

    def _filter_tasks(
        self,
        tasks: list[TaskDocument],
        *,
        state: str | None,
        project_id: str | None,
        context_id: str | None,
        unassigned_project: bool,
        include_completed: bool,
    ) -> list[TaskDocument]:
        allowed_states: set[str]
        if state is not None:
            allowed_states = {state}
        else:
            allowed_states = set(_OPEN_STATES)
            if include_completed:
                allowed_states.add("completed")
        return sorted(
            (
                task
                for task in tasks
                if task.state in allowed_states
                and (project_id is None or task.project_id == project_id)
                and (context_id is None or context_id in task.context_ids)
                and (not unassigned_project or task.project_id is None)
            ),
            key=self._sort_key,
        )

    def _open_counts(
        self,
        *,
        owner_id: str,
        project_id: str | None,
        context_id: str | None,
        unassigned_project: bool,
    ) -> dict[str, int]:
        tasks = self.task_repo.list_for_owner(owner_id=owner_id)
        filtered = [
            task
            for task in tasks
            if (project_id is None or task.project_id == project_id)
            and (context_id is None or context_id in task.context_ids)
            and (not unassigned_project or task.project_id is None)
        ]
        return {
            state: sum(task.state == state for task in filtered)
            for state in _OPEN_STATES
        }

    @staticmethod
    def _sort_key(task: TaskDocument) -> tuple[int, datetime, str]:
        return task.order_key, task.created_at, task.id

    @staticmethod
    def _encode_cursor(
        filters: Mapping[str, object], last_sort_key: tuple[int, datetime, str]
    ) -> str:
        payload = {
            "filters": filters,
            "last": [last_sort_key[0], last_sort_key[1].isoformat(), last_sort_key[2]],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_cursor(
        cursor: str, filters: Mapping[str, object]
    ) -> tuple[int, datetime, str]:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            if payload["filters"] != filters:
                raise ValueError("cursor filters do not match")
            order_key, created_at, task_id = payload["last"]
            if not isinstance(order_key, int) or not isinstance(created_at, str):
                raise ValueError("invalid cursor tuple")
            if not isinstance(task_id, str) or not task_id:
                raise ValueError("invalid cursor task id")
            return order_key, datetime.fromisoformat(created_at), task_id
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ValidationFailure("Invalid or mismatched task cursor.") from exc
