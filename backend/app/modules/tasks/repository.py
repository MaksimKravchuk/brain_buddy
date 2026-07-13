"""Filesystem persistence for records owned by the native task module."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.exceptions import ConflictError, NotFoundError
from app.repositories.base import BaseRepository
from app.utils.file_ops import ensure_directory

from .domain import (
    ContextDocument,
    IdempotencyRecord,
    ProjectDocument,
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)


class TaskRepository(BaseRepository):
    """Store task-module records independently in owner-scoped directories."""

    def subtask_path(self, owner_id: str, task_id: str, subtask_id: str) -> Path:
        return self.resolve("task-subtasks", owner_id, task_id, f"{subtask_id}.json")

    def comment_path(self, owner_id: str, task_id: str, comment_id: str) -> Path:
        return self.resolve("task-comments", owner_id, task_id, f"{comment_id}.json")

    def create_subtask(self, subtask: TaskSubtaskDocument) -> None:
        self.dump_model(
            self.subtask_path(subtask.owner_id, subtask.task_id, subtask.id), subtask
        )

    def list_subtasks(self, *, owner_id: str, task_id: str) -> list[TaskSubtaskDocument]:
        directory = self.resolve("task-subtasks", owner_id, task_id)
        if not directory.exists():
            return []
        return [self.load_model(path, TaskSubtaskDocument) for path in directory.glob("*.json")]

    def get_subtask_for_owner(
        self, subtask_id: str, *, owner_id: str, task_id: str
    ) -> TaskSubtaskDocument:
        path = self.subtask_path(owner_id, task_id, subtask_id)
        if not path.exists():
            raise NotFoundError("Task subtask", subtask_id)
        return self.load_model(path, TaskSubtaskDocument)

    def create_comment(self, comment: TaskCommentDocument) -> None:
        self.dump_model(
            self.comment_path(comment.owner_id, comment.task_id, comment.id), comment
        )

    def list_comments(self, *, owner_id: str, task_id: str) -> list[TaskCommentDocument]:
        directory = self.resolve("task-comments", owner_id, task_id)
        if not directory.exists():
            return []
        return [self.load_model(path, TaskCommentDocument) for path in directory.glob("*.json")]

    def get_comment_for_owner(
        self, comment_id: str, *, owner_id: str, task_id: str
    ) -> TaskCommentDocument:
        path = self.comment_path(owner_id, task_id, comment_id)
        if not path.exists():
            raise NotFoundError("Task comment", comment_id)
        return self.load_model(path, TaskCommentDocument)

    def idempotency_path(self, owner_id: str, key: str) -> Path:
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.resolve("task-commands", owner_id, f"{key_hash}.json")

    def get_idempotency(
        self, *, owner_id: str, key: str
    ) -> IdempotencyRecord | None:
        path = self.idempotency_path(owner_id, key)
        return self.load_model(path, IdempotencyRecord) if path.exists() else None

    def save_idempotency(self, *, owner_id: str, record: IdempotencyRecord) -> None:
        self.dump_model(self.idempotency_path(owner_id, record.key), record)

    def project_path(self, owner_id: str, project_id: str) -> Path:
        return self.resolve("projects", owner_id, f"{project_id}.json")

    def context_path(self, owner_id: str, context_id: str) -> Path:
        return self.resolve("contexts", owner_id, f"{context_id}.json")

    def create_project(self, project: ProjectDocument) -> None:
        path = self.project_path(project.owner_id, project.id)
        if path.exists():
            raise ConflictError("Project", project.id)
        self.dump_model(path, project)

    def create_context(self, context: ContextDocument) -> None:
        path = self.context_path(context.owner_id, context.id)
        if path.exists():
            raise ConflictError("Context", context.id)
        self.dump_model(path, context)

    def get_project_for_owner(self, project_id: str, *, owner_id: str) -> ProjectDocument:
        path = self.project_path(owner_id, project_id)
        if not path.exists():
            raise NotFoundError("Project", project_id)
        return self.load_model(path, ProjectDocument)

    def get_context_for_owner(self, context_id: str, *, owner_id: str) -> ContextDocument:
        path = self.context_path(owner_id, context_id)
        if not path.exists():
            raise NotFoundError("Context", context_id)
        return self.load_model(path, ContextDocument)

    def list_projects_for_owner(self, *, owner_id: str) -> list[ProjectDocument]:
        directory = self.resolve("projects", owner_id)
        if not directory.exists():
            return []
        return [self.load_model(path, ProjectDocument) for path in directory.glob("*.json")]

    def list_contexts_for_owner(self, *, owner_id: str) -> list[ContextDocument]:
        directory = self.resolve("contexts", owner_id)
        if not directory.exists():
            return []
        return [self.load_model(path, ContextDocument) for path in directory.glob("*.json")]

    def task_path(self, owner_id: str, task_id: str) -> Path:
        return self.resolve("tasks", owner_id, f"{task_id}.json")

    def create(self, task: TaskDocument) -> None:
        path = self.task_path(task.owner_id, task.id)
        if path.exists():
            raise ConflictError("Task", task.id)
        self.dump_model(path, task)

    def save(self, task: TaskDocument) -> None:
        self.dump_model(self.task_path(task.owner_id, task.id), task)

    def get_for_owner(self, task_id: str, *, owner_id: str) -> TaskDocument:
        path = self.task_path(owner_id, task_id)
        if not path.exists():
            raise NotFoundError("Task", task_id)
        return self.load_model(path, TaskDocument)

    def list_for_owner(self, *, owner_id: str) -> list[TaskDocument]:
        directory = self.resolve("tasks", owner_id)
        if not directory.exists():
            return []
        return [self.load_model(path, TaskDocument) for path in directory.glob("*.json")]

    def next_order_key(self, *, owner_id: str, state: str) -> int:
        matching = [
            task.order_key
            for task in self.list_for_owner(owner_id=owner_id)
            if task.state == state
        ]
        return max(matching, default=-1) + 1

    def ensure_owner_dir(self, owner_id: str) -> Path:
        """Create the owner directory for callers that need a stable data location."""

        return ensure_directory(self.resolve("tasks", owner_id))
