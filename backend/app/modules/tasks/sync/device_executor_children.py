"""Device-origin subtask, comment and Smart Add commands (spec 026 PR-31c).

Same contract as ``device_executor``: the command runs inside the receipt unit
the route opened, the Rust core decides, and this module only loads the read
set, persists what the core decided and translates the child's own revision
precondition into the core's check. The parent task is never written and its
revision is never consulted for a child (command catalog).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from sqlite3 import Connection
from typing import Any

from app.exceptions import NotFoundError
from app.modules.tasks.domain import (
    SmartAddCreatedDocument,
    SmartAddTaskResultDocument,
    TaskCommentDocument,
    TaskSubtaskDocument,
)
from app.modules.tasks.rust_adapter import RustCore
from app.modules.tasks.rust_task_facade import (
    RustTaskFacade,
    decode_project,
    decode_tag,
    decode_task,
    encode_project,
    encode_tag,
    encode_task,
    instant,
)

from .device_executor import (
    Receipt,
    RestProjector,
    TaskDeviceExecutor,
    _invalid,
    _refusal,
    register_family,
)
from .receipts import ReceiptCommand
from .wire import DeviceCommandExecutor

_PAYLOAD_KEYS = {
    "subtask.create": {"task_id", "title"},
    "subtask.update": {"task_id", "title"},
    "subtask.transition": {"task_id", "action"},
    "comment.create": {"task_id", "body"},
    "comment.update": {"task_id", "body"},
}
_SUPPORTED = frozenset({*_PAYLOAD_KEYS, "task.smart_add"})


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _encode_subtask(subtask: TaskSubtaskDocument) -> dict[str, Any]:
    return {
        "id": subtask.id,
        "task_id": subtask.task_id,
        "title": subtask.title,
        "state": subtask.state,
        "order_key": str(subtask.order_key),
        "revision": str(subtask.revision),
    }


def _encode_comment(comment: TaskCommentDocument) -> dict[str, Any]:
    return {
        "id": comment.id,
        "task_id": comment.task_id,
        "body": comment.body,
        "actor_id": comment.actor_id,
        "created_at": instant(comment.created_at),
        "edited_at": None if comment.edited_at is None else instant(comment.edited_at),
        "revision": str(comment.revision),
    }


class ChildrenDeviceExecutor(TaskDeviceExecutor):
    """``DeviceCommandExecutor`` for subtask, comment and Smart Add commands."""

    def supports(self, command_type: str) -> bool:
        return command_type in _SUPPORTED

    # ------------------------------------------------------------- subtasks
    def _subtask_create(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: dict[str, Any],
    ) -> Receipt:
        return self._child(command, envelope, body, "subtask")

    def _subtask_update(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: dict[str, Any],
    ) -> Receipt:
        return self._child(command, envelope, body, "subtask")

    def _subtask_transition(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: dict[str, Any],
    ) -> Receipt:
        return self._child(command, envelope, body, "subtask")

    # ------------------------------------------------------------- comments
    def _comment_create(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: dict[str, Any],
    ) -> Receipt:
        return self._child(command, envelope, body, "comment")

    def _comment_update(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: dict[str, Any],
    ) -> Receipt:
        return self._child(command, envelope, body, "comment")

    def _child(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: dict[str, Any],
        kind: str,
    ) -> Receipt:
        command_type = str(envelope["type"])
        creating = command_type.endswith(".create")
        task_id = body.get("task_id")
        if not isinstance(task_id, str) or set(body) - _PAYLOAD_KEYS[command_type]:
            raise _invalid()
        owner = command.unit.owner_id
        entity_id = (
            self._new_id(envelope, kind) if creating else str(envelope["entity_id"])
        )
        if creating and self._repo.child_id_taken(
            "subtasks" if kind == "subtask" else "comments", entity_id, owner_id=owner
        ):
            # Feed records are keyed by id alone, so ids are unique across parents.
            return command.reject(_refusal("id_already_exists"))
        expected = (
            None
            if creating
            else (kind, entity_id, self._expected(command, envelope, kind))
        )
        parent = self._load(self._repo.get_for_owner, task_id, owner)
        before = None if creating else self._current(kind, entity_id, task_id, owner)
        read_set: dict[str, Any] = {
            "tasks": {} if parent is None else {task_id: encode_task(parent)},
            "subtasks": {},
            "comments": {},
        }
        if parent is not None and kind == "subtask":
            siblings = self._repo.list_subtasks(owner_id=owner, task_id=task_id)
            read_set["subtasks"] = {s.id: _encode_subtask(s) for s in siblings}
        elif before is not None:
            read_set["comments"] = {entity_id: _encode_comment(before)}
        decision = self._rust.decide_command(
            command_type,
            entity_id,
            body,
            owner_id=owner,
            now=command.now,
            read_set=read_set,
            expected=expected,
        )
        if decision.refusal is not None or decision.change_set is None:
            return self._refuse(command, decision)
        value = decision.change_set["changes"][0]["value"]
        stored = (
            self._subtask_document(value, before, owner, command.now)
            if kind == "subtask"
            else self._comment_document(value, before, owner)
        )
        if isinstance(stored, TaskSubtaskDocument):
            if creating:
                self._repo.create_subtask(stored)
            else:
                self._repo.save_subtask(stored)
        elif creating:
            self._repo.create_comment(stored)
        else:
            self._repo.save_comment(stored)
        public = (
            self._public.subtask
            if isinstance(stored, TaskSubtaskDocument)
            else self._public.comment
        )
        return self._accepted(command, decision, public(owner, stored))

    def _current(
        self, kind: str, entity_id: str, task_id: str, owner: str
    ) -> Any | None:
        """The stored child, or ``None`` (the core then refuses ``not_found``)."""
        get = (
            self._repo.get_subtask_for_owner
            if kind == "subtask"
            else self._repo.get_comment_for_owner
        )
        try:
            return get(entity_id, owner_id=owner, task_id=task_id)
        except NotFoundError:
            return None

    @staticmethod
    def _subtask_document(
        value: Mapping[str, Any],
        before: TaskSubtaskDocument | None,
        owner: str,
        now: datetime,
    ) -> TaskSubtaskDocument:
        if before is None:
            return TaskSubtaskDocument(
                id=value["id"],
                owner_id=owner,
                task_id=value["task_id"],
                title=value["title"],
                order_key=int(value["order_key"]),
                created_at=now,
                updated_at=now,
            )
        return before.model_copy(
            update={
                "title": value["title"],
                "state": value["state"],
                "updated_at": now,
                "revision": int(value["revision"]),
            }
        )

    @staticmethod
    def _comment_document(
        value: Mapping[str, Any], before: TaskCommentDocument | None, owner: str
    ) -> TaskCommentDocument:
        edited = value["edited_at"]
        if before is None:
            return TaskCommentDocument(
                id=value["id"],
                owner_id=owner,
                task_id=value["task_id"],
                actor_id=value["actor_id"],
                body=value["body"],
                created_at=_parse_instant(value["created_at"]),
            )
        return before.model_copy(
            update={
                "body": value["body"],
                "edited_at": None if edited is None else _parse_instant(edited),
                "revision": int(value["revision"]),
            }
        )

    # ------------------------------------------------------------ smart add
    def _task_smart_add(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: dict[str, Any],
    ) -> Receipt:
        owner, task_id = command.unit.owner_id, self._new_id(envelope, "task")
        if self._exists(self._repo.get_for_owner, task_id, owner):
            return command.reject(_refusal("id_already_exists"))
        state = body.get("state", "inbox")
        if state == "next" and not body.get("new_formulation_id"):
            # A server-allocated formulation id would differ from the device's.
            raise _invalid()
        decision = self._rust.decide_command(
            "task.smart_add",
            task_id,
            body,
            owner_id=owner,
            now=command.now,
            read_set={
                "tasks": {
                    task.id: encode_task(task)
                    for task in self._repo.list_for_owner(owner_id=owner)
                    if task.state == state
                },
                "projects": {
                    p.id: encode_project(p)
                    for p in self._repo.list_projects_for_owner(owner_id=owner)
                },
                "tags": {
                    t.id: encode_tag(t)
                    for t in self._repo.list_tags_for_owner(owner_id=owner)
                },
            },
        )
        if decision.refusal is not None or decision.change_set is None:
            return self._refuse(command, decision)
        created_project: str | None = None
        created_tags: list[str] = []
        task = None
        # The core lists changes in application order: project, tags, then task.
        for change in decision.change_set["changes"]:
            kind, value = change["entity_type"], change["value"]
            if kind == "project":
                project = decode_project(
                    value, before=None, owner_id=owner, now=command.now
                )
                self._repo.create_project(project)
                created_project = project.id
            elif kind == "tag":
                tag = decode_tag(value, before=None, owner_id=owner, now=command.now)
                self._repo.create_tag(tag)
                created_tags.append(tag.id)
            else:
                task = decode_task(value, before=None, owner_id=owner)
                self._repo.create(task)
        assert task is not None
        result = SmartAddTaskResultDocument(
            task=task,
            project=(
                self._repo.get_project_for_owner(task.project_id, owner_id=owner)
                if task.project_id is not None
                else None
            ),
            tags=[
                self._repo.get_tag_for_owner(t, owner_id=owner) for t in task.tag_ids
            ],
            created=SmartAddCreatedDocument(
                project_id=created_project, tag_ids=created_tags
            ),
        )
        return command.accept(
            decision.change_set["changes"],
            result=self._public.smart_add(owner, result),
            id_bindings=decision.change_set["result"]["id_bindings"],
        )


@register_family
def _children_family(container: Any, core: RustCore) -> DeviceCommandExecutor:
    tasks = container.task_service
    return ChildrenDeviceExecutor(
        tasks.task_repo,
        RustTaskFacade(core, tasks.task_repo, client_ids_only=True),
        RestProjector(tasks),
        tasks._log_due_date_move,
    )
