"""Device-origin execution of the Task organization commands (spec 026 PR-31b).

Runs inside the receipt unit the command route already opened, so the receipt
id is the device ``command_id`` and replay or lookup by it is exact. Domain
decisions are the shared Rust ones (``RustTaskFacade.decide_*``); this module
only translates the envelope into the accepted request, supplies the creation
ID, turns preconditions into ``expected_revision`` and persists what the core
decided. Review, Smart Add, subtask and comment commands are not executed here.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from importlib import import_module
from sqlite3 import Connection
from typing import Any, Protocol

from pydantic import ValidationError

from app.exceptions import NotFoundError
from app.modules.tasks.repository import TaskRepository
from app.modules.tasks.rust_adapter import Decision, DomainRefusal, RustCore
from app.modules.tasks.rust_task_facade import RustTaskFacade, encode_task
from app.schemas.tasks import (
    ExpectedRevisionRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    TagCreateRequest,
    TagUpdateRequest,
    TaskCreateRequest,
    TaskTransitionRequest,
    TaskUpdateRequest,
)

from .receipts import ReceiptCommand
from .wire import DeviceCommandExecutor, ProtocolFailure

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_SUPPORTED = frozenset(
    {
        "project.create",
        "project.update",
        "project.archive",
        "project.unarchive",
        "tag.create",
        "tag.update",
        "tag.delete",
        "task.create",
        "task.update",
        "task.tags",
        "task.transition",
    }
)
type Receipt = dict[str, Any]


def _invalid() -> ProtocolFailure:
    return ProtocolFailure("INVALID_REQUEST")


def _refusal(reason: str) -> DomainRefusal:
    return DomainRefusal(reason, None, None, None)


class DeviceExecutorRegistry:
    """Composes family executors; each command type belongs to one family."""

    def __init__(self, *families: DeviceCommandExecutor) -> None:
        self._families = list(families)

    def register(self, family: DeviceCommandExecutor) -> None:
        self._families.append(family)

    def supports(self, command_type: str) -> bool:
        return any(family.supports(command_type) for family in self._families)

    def execute(
        self, command: ReceiptCommand[Connection], envelope: Mapping[str, Any]
    ) -> Receipt:
        for family in self._families:
            if family.supports(envelope["type"]):
                return family.execute(command, envelope)
        raise ProtocolFailure("UPGRADE_REQUIRED")


# A family module calls ``register_family`` at import with a factory taking the
# application container and the shared core; it adds its file name below.
type FamilyFactory = Callable[[Any, RustCore], DeviceCommandExecutor]
_FACTORIES: list[FamilyFactory] = []
FAMILY_MODULES = (
    "app.modules.tasks.sync.device_executor_children",
    "app.modules.tasks.sync.device_executor_review",
)


def register_family(factory: FamilyFactory) -> FamilyFactory:
    _FACTORIES.append(factory)
    return factory


def build_executor(container: Any, core: RustCore) -> DeviceExecutorRegistry:
    """The registry of every family module that exists in this build."""
    for name in FAMILY_MODULES:
        try:
            import_module(name)
        except ModuleNotFoundError as missing:
            if missing.name != name:
                raise
    return DeviceExecutorRegistry(*(factory(container, core) for factory in _FACTORIES))


class PublicProjector(Protocol):
    """The REST response projection of an entity, so receipts equal web bodies."""

    def task(self, owner: str, task: Any) -> dict[str, Any]: ...

    def project(self, owner: str, project: Any) -> dict[str, Any]: ...

    def tag(self, owner: str, tag: Any) -> dict[str, Any]: ...


class RestProjector:
    """``PublicProjector`` over the API's own mappers (one source of shape)."""

    def __init__(self, service: Any) -> None:
        from app.api import task_mapping  # noqa: PLC0415 - api is above modules

        self._service, self._map = service, task_mapping

    def task(self, owner: str, task: Any) -> dict[str, Any]:
        settings = self._service.formulation_settings(owner)
        response = self._map.command_task_response(self._service, owner, task, settings)
        return response.model_dump(mode="json")

    def project(self, owner: str, project: Any) -> dict[str, Any]:
        response = self._map.project_response(
            project, task_service=self._service, owner_id=owner
        )
        return response.model_dump(mode="json")

    def tag(self, owner: str, tag: Any) -> dict[str, Any]:
        response = self._map.tag_response(
            tag, task_service=self._service, owner_id=owner
        )
        return response.model_dump(mode="json")


class TaskDeviceExecutor:
    """``DeviceCommandExecutor`` for project, tag and task commands."""

    def __init__(
        self,
        repo: TaskRepository,
        rust: RustTaskFacade,
        public: PublicProjector,
        due_date_moved: Callable[..., None],
    ) -> None:
        self._repo, self._rust, self._public = repo, rust, public
        self._due_date_moved = due_date_moved

    def supports(self, command_type: str) -> bool:
        return command_type in _SUPPORTED

    def execute(
        self, command: ReceiptCommand[Connection], envelope: Mapping[str, Any]
    ) -> Receipt:
        payload = envelope["payload"]
        kind = envelope["type"]
        try:
            blocked = self._dependencies(command, envelope)
            if blocked is not None:
                return blocked
            handler = getattr(self, "_" + kind.replace(".", "_"))
            return handler(command, envelope, dict(payload))  # type: ignore[no-any-return]
        except ValidationError:
            raise _invalid() from None

    # ------------------------------------------------------------- envelope
    @staticmethod
    def _new_id(envelope: Mapping[str, Any], prefix: str) -> str:
        """The creation ID the device allocated: ``<prefix>_<lowercase UUID>``."""
        entity_id = envelope["entity_id"]
        if not re.fullmatch(f"{prefix}_{_UUID}", entity_id):
            raise _invalid()
        return str(entity_id)

    def _dependencies(
        self, command: ReceiptCommand[Connection], envelope: Mapping[str, Any]
    ) -> Receipt | None:
        """A pending predecessor is retryable; a rejected one is terminal."""
        pending: list[str] = []
        for dependency in envelope["depends_on"]:
            known = self._receipt(command, dependency)
            if known is None:
                pending.append(dependency)
            elif known["outcome"] == "rejected":
                return command.reject(_refusal("dependency_rejected"))
        if pending:
            raise ProtocolFailure(
                "DEPENDENCY_PENDING", details={"dependency_ids": pending}
            )
        return None

    @staticmethod
    def _receipt(command: ReceiptCommand[Connection], command_id: str) -> Any:
        return command.store._lookup(
            command.unit, command_id, command.authority, now=command.now
        )

    def _expected(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        entity_type: str,
    ) -> int:
        """``expected_revision`` from this entity's precondition (or its command)."""
        entity_id = envelope["entity_id"]
        for item in envelope["preconditions"]:
            if "after_command" in item:
                ref = item["after_command"]
                if (ref["entity_type"], ref["entity_id"]) != (entity_type, entity_id):
                    continue
                # The core already requires the referenced command in depends_on.
                return self._revision_after(command, ref, entity_id)
            if (item["entity_type"], item["entity_id"]) == (entity_type, entity_id):
                return int(item["edit_revision"])
        raise _invalid()

    def _revision_after(
        self,
        command: ReceiptCommand[Connection],
        ref: Mapping[str, Any],
        entity_id: str,
    ) -> int:
        receipt = self._receipt(command, ref["command_id"])
        for version in (receipt or {}).get("result_versions", []):
            if version["entity_type"] == ref["entity_type"] and (
                version["record_key"][-1] == entity_id and "edit_revision" in version
            ):
                return int(version["edit_revision"])
        raise _invalid()

    # ---------------------------------------------------------------- tasks
    def _task_create(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Any,
    ) -> Receipt:
        owner, task_id = command.unit.owner_id, self._new_id(envelope, "task")
        request = TaskCreateRequest(**body)
        if self._exists(self._repo.get_for_owner, task_id, owner):
            return command.reject(_refusal("id_already_exists"))
        decision, task = self._rust.decide_create_task(
            request, owner_id=owner, now=command.now, entity_id=task_id
        )
        if decision.refusal is not None or task is None:
            return self._refuse(command, decision)
        self._repo.create(task)
        return command.accept(
            decision.change_set["changes"],  # type: ignore[index]
            result=self._public.task(owner, task),
        )

    def _task_update(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Any,
    ) -> Receipt:
        if {"tag_ids", "context_ids", "expected_revision"} & body.keys():
            raise _invalid()
        changes = body.pop("tag_changes", None)
        return self._update_task(command, envelope, body, changes)

    def _task_tags(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Any,
    ) -> Receipt:
        if set(body) - {"add_tag_ids", "remove_tag_ids"}:
            raise _invalid()
        return self._update_task(command, envelope, {}, body)

    def _update_task(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: dict[str, Any],
        tag_changes: Mapping[str, Any] | None,
    ) -> Receipt:
        owner, task_id = command.unit.owner_id, envelope["entity_id"]
        expected = self._expected(command, envelope, "task")
        before = self._load(self._repo.get_for_owner, task_id, owner)
        if before is None:
            return command.reject(_refusal("not_found"))
        if tag_changes is not None:
            # Explicit add/remove against the checked base, never a replacement.
            removed = set(tag_changes.get("remove_tag_ids", []))
            kept = [tag for tag in before.tag_ids if tag not in removed]
            added = [t for t in tag_changes.get("add_tag_ids", []) if t not in kept]
            body["tag_ids"] = [*kept, *added]
        request = TaskUpdateRequest(**body, expected_revision=expected)
        decision, updated = self._rust.decide_update_task(
            before, request, owner_id=owner, now=command.now
        )
        if decision.refusal is not None or updated is None:
            return self._refuse(command, decision)
        self._repo.save(updated)
        # The Review clock's event, exactly as the web update path emits it.
        self._due_date_moved(before, updated, owner_id=owner)
        return command.accept(
            self._with_task(decision, updated), result=self._public.task(owner, updated)
        )

    def _task_transition(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Any,
    ) -> Receipt:
        owner, task_id = command.unit.owner_id, envelope["entity_id"]
        expected = self._expected(command, envelope, "task")
        before = self._load(self._repo.get_for_owner, task_id, owner)
        if before is None:
            return command.reject(_refusal("not_found"))
        request = TaskTransitionRequest(**body, expected_revision=expected)
        decision, moved = self._rust.decide_transition_task(
            before, request, owner_id=owner, now=command.now
        )
        if decision.refusal is not None or moved is None:
            return self._refuse(command, decision)
        self._repo.save(moved.task)
        if moved.park_ack is not None:
            self._repo.save_park_ack(moved.park_ack)
        return command.accept(
            self._with_task(decision, moved.task),
            result=self._public.task(owner, moved.task),
        )

    # ------------------------------------------------------------- projects
    def _project_create(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Any,
    ) -> Receipt:
        owner, project_id = command.unit.owner_id, self._new_id(envelope, "project")
        request = ProjectCreateRequest(**body)
        if self._exists(self._repo.get_project_for_owner, project_id, owner):
            return command.reject(_refusal("id_already_exists"))
        decision, project = self._rust.decide_create_project(
            request, owner_id=owner, now=command.now, entity_id=project_id
        )
        if decision.refusal is not None or project is None:
            return self._refuse(command, decision)
        self._repo.create_project(project)
        return self._accepted(command, decision, self._public.project(owner, project))

    def _project_update(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Any,
    ) -> Receipt:
        return self._project_change(command, envelope, body, "update")

    def _project_archive(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Any,
    ) -> Receipt:
        return self._project_change(command, envelope, body, "archive")

    def _project_unarchive(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Any,
    ) -> Receipt:
        return self._project_change(command, envelope, body, "unarchive")

    def _project_change(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: dict[str, Any],
        operation: str,
    ) -> Receipt:
        owner, project_id = command.unit.owner_id, envelope["entity_id"]
        if "expected_revision" in body:
            raise _invalid()
        expected = self._expected(command, envelope, "project")
        before = self._load(self._repo.get_project_for_owner, project_id, owner)
        if before is None:
            return command.reject(_refusal("not_found"))
        if operation == "update":
            decision, project = self._rust.decide_update_project(
                before,
                ProjectUpdateRequest(**body, expected_revision=expected),
                owner_id=owner,
                now=command.now,
            )
        else:
            if body:
                raise _invalid()
            decide = (
                self._rust.decide_archive_project
                if operation == "archive"
                else self._rust.decide_unarchive_project
            )
            decision, project = decide(
                before,
                ExpectedRevisionRequest(expected_revision=expected),
                owner_id=owner,
                now=command.now,
            )
        if decision.refusal is not None or project is None:
            return self._refuse(command, decision)
        if decision.change_set["changes"]:  # type: ignore[index]
            self._repo.save_project(project)
        return self._accepted(command, decision, self._public.project(owner, project))

    # ----------------------------------------------------------------- tags
    def _tag_create(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Any,
    ) -> Receipt:
        owner, tag_id = command.unit.owner_id, self._new_id(envelope, "tag")
        request = TagCreateRequest(**body)
        if self._exists(self._repo.get_tag_for_owner, tag_id, owner):
            return command.reject(_refusal("id_already_exists"))
        decision, tag = self._rust.decide_create_tag(
            request, owner_id=owner, now=command.now, entity_id=tag_id
        )
        if decision.refusal is not None or tag is None:
            return self._refuse(command, decision)
        self._repo.create_tag(tag)
        return self._accepted(command, decision, self._public.tag(owner, tag))

    def _tag_update(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Any,
    ) -> Receipt:
        owner, tag_id = command.unit.owner_id, envelope["entity_id"]
        if "expected_revision" in body:
            raise _invalid()
        expected = self._expected(command, envelope, "tag")
        before = self._load(self._repo.get_tag_for_owner, tag_id, owner)
        if before is None:
            return command.reject(_refusal("not_found"))
        decision, tag = self._rust.decide_update_tag(
            before,
            TagUpdateRequest(**body, expected_revision=expected),
            owner_id=owner,
            now=command.now,
        )
        if decision.refusal is not None or tag is None:
            return self._refuse(command, decision)
        self._repo.save_tag(tag)
        return self._accepted(command, decision, self._public.tag(owner, tag))

    def _tag_delete(
        self,
        command: ReceiptCommand[Connection],
        envelope: Mapping[str, Any],
        body: Any,
    ) -> Receipt:
        owner, tag_id = command.unit.owner_id, envelope["entity_id"]
        if body:
            raise _invalid()
        expected = self._expected(command, envelope, "tag")
        before = self._load(self._repo.get_tag_for_owner, tag_id, owner)
        if before is None:
            return command.reject(_refusal("not_found"))
        decision, deleted = self._rust.decide_delete_tag(
            before,
            ExpectedRevisionRequest(expected_revision=expected),
            owner_id=owner,
            now=command.now,
        )
        if decision.refusal is not None or deleted is None:
            return self._refuse(command, decision)
        self._repo.save_tag(deleted.tag)
        for task in deleted.affected:
            self._repo.save(task)
        changes: list[dict[str, Any]] = [
            {
                "operation": "tombstone",
                "entity_type": "tag",
                "record_key": [owner, tag_id],
            },
            *[
                {
                    "operation": "upsert",
                    "entity_type": "task",
                    "record_key": [owner, task.id],
                    "value": encode_task(task),
                }
                for task in deleted.affected
            ],
        ]
        return command.accept(changes, result=self._public.tag(owner, deleted.tag))

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _load(get: Callable[..., Any], entity_id: str, owner: str) -> Any:
        try:
            return get(entity_id, owner_id=owner)
        except NotFoundError:
            return None

    @classmethod
    def _exists(cls, get: Callable[..., Any], entity_id: str, owner: str) -> bool:
        return cls._load(get, entity_id, owner) is not None

    @staticmethod
    def _refuse(command: ReceiptCommand[Connection], decision: Decision) -> Receipt:
        assert decision.refusal is not None
        return command.reject(decision.refusal)

    @staticmethod
    def _accepted(
        command: ReceiptCommand[Connection], decision: Decision, result: dict[str, Any]
    ) -> Receipt:
        assert decision.change_set is not None
        return command.accept(decision.change_set["changes"], result=result)

    @staticmethod
    def _with_task(decision: Decision, task: Any) -> list[dict[str, Any]]:
        """The decided changes, the task upsert carrying the stored after-image."""
        assert decision.change_set is not None
        return [
            (
                {**change, "value": encode_task(task)}
                if change.get("entity_type") == "task"
                and change.get("operation") == "upsert"
                else change
            )
            for change in decision.change_set["changes"]
        ]


@register_family
def _task_family(container: Any, core: RustCore) -> DeviceCommandExecutor:
    tasks = container.task_service
    return TaskDeviceExecutor(
        tasks.task_repo,
        RustTaskFacade(core, tasks.task_repo),
        RestProjector(tasks),
        tasks._log_due_date_move,
    )
