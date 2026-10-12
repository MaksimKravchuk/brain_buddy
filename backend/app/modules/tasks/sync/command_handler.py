"""One legacy command family executed through the shared receipt boundary."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta
from sqlite3 import Connection, connect
from typing import Any, Protocol, cast

from pydantic import BaseModel, ValidationError

from app.exceptions import (
    ConflictError,
    IdempotencyReceiptUnavailableError,
    NotFoundError,
    ValidationFailure,
)
from app.modules.tasks.domain import (
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
from app.modules.tasks.jobs.execution import owner_write_lock
from app.modules.tasks.repository import (
    IDEMPOTENCY_RETENTION,
    TaskRepository,
    display_project_name,
    display_tag_name,
)
from app.modules.tasks.rust_adapter import DomainRefusal
from app.modules.tasks.rust_task_facade import (
    RustTaskFacade,
    _ordered_refusal,
    _refused,
    encode_project,
    encode_tag,
    encode_task,
)
from app.modules.tasks.sync.legacy_adapter import (
    PROJECT_ALIAS,
    PROJECT_ARCHIVE_ALIAS,
    PROJECT_UNARCHIVE_ALIAS,
    PROJECT_UPDATE_ALIAS,
    TAG_ALIAS,
    TAG_DELETE_ALIAS,
    TAG_UPDATE_ALIAS,
    TASK_ALIAS,
    TASK_TRANSITION_ALIAS,
    TASK_UPDATE_ALIAS,
    project_archive_request,
    project_create_request,
    project_entity_id,
    project_unarchive_request,
    project_update_request,
    tag_create_request,
    tag_delete_request,
    tag_entity_id,
    tag_update_request,
    task_create_request,
    task_entity_id,
    task_transition_request,
    task_update_request,
)
from app.modules.tasks.sync.receipts import (
    Authority,
    CommandReceipts,
    CommandRequest,
    ReceiptCommand,
    SyncCommandError,
)
from app.modules.tasks.sync.unit_of_work import TaskUnitOfWork
from app.schemas.tasks import (
    ExpectedRevisionRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    SmartAddTaskCreateRequest,
    TagCreateRequest,
    TagUpdateRequest,
    TaskCreateRequest,
    TaskTransitionRequest,
    TaskUpdateRequest,
)
from app.utils.idempotency import idempotency_key_digest, request_fingerprint


class LegacyTagService(Protocol):
    task_repo: TaskRepository

    def _request_hash(
        self,
        command: str,
        payload: (
            ProjectCreateRequest
            | ProjectUpdateRequest
            | ExpectedRevisionRequest
            | TagCreateRequest
            | TagUpdateRequest
            | TaskCreateRequest
            | TaskTransitionRequest
            | TaskUpdateRequest
            | SmartAddTaskCreateRequest
        ),
    ) -> str: ...

    def _project_result(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> ProjectDocument: ...

    def _tag_result(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> TagDocument: ...

    def _task_command_result(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> Any: ...

    def _log_due_date_move(
        self, before: TaskDocument, after: TaskDocument, *, owner_id: str
    ) -> None: ...

    def formulation_settings(self, owner_id: str) -> FormulationSettingsDocument: ...

    def _smart_add_result(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> SmartAddTaskResultDocument: ...

    def _idempotency_record(
        self, *, owner_id: str, key: str, command: str, request_hash: str
    ) -> IdempotencyRecord | None: ...

    def _store_idempotency(
        self,
        *,
        owner_id: str,
        key: str,
        command: str,
        request_hash: str,
        resource_id: str,
        response: TagDocument,
    ) -> None: ...


class LegacyTagCommandHandler:
    def __init__(
        self,
        receipts: CommandReceipts[Connection],
        units: TaskUnitOfWork,
        authority: Authority[Connection],
        rust: RustTaskFacade,
        repo: TaskRepository,
    ) -> None:
        self._receipts = receipts
        self._units = units
        self._authority = authority
        self._rust = rust
        self._repo = repo

    def has_legacy_key(self, owner_id: str, key: str, now: datetime) -> bool:
        """Route expired child/Smart Add keys through redaction even with flag OFF."""
        digest = idempotency_key_digest(key)
        with connect(self._repo.db_path) as conn:
            if conn.execute(
                "SELECT 1 FROM sync_legacy_keys WHERE owner_id=? AND key_digest=?",
                (owner_id, digest),
            ).fetchone():
                return True
            row = conn.execute(
                "SELECT command, created_at FROM idempotency_records "
                "WHERE owner_id=? AND key_hash=?",
                (owner_id, digest),
            ).fetchone()
        return (
            row is not None
            and (
                row[0] == "smart_add_task"
                or row[0].startswith(
                    (
                        "create_subtask:",
                        "update_subtask:",
                        "transition_subtask:",
                        "create_comment:",
                        "update_comment:",
                    )
                )
            )
            and datetime.fromisoformat(row[1]) <= now - IDEMPOTENCY_RETENTION
        )

    def reject_redacted_legacy_conflict(
        self, owner_id: str, key: str, operation: str
    ) -> None:
        """Do not let another command family borrow an expired legacy identity."""
        with connect(self._repo.db_path) as conn:
            row = conn.execute(
                "SELECT command FROM idempotency_records "
                "WHERE owner_id=? AND key_hash=? "
                "AND json_type(response_body, '$._expired_revision') IS NOT NULL",
                (owner_id, idempotency_key_digest(key)),
            ).fetchone()
        if row is not None and not (
            row[0] == operation or row[0].startswith(f"{operation}:")
        ):
            raise ConflictError("Idempotency-Key", key)

    def _expired_legacy_identity(
        self, owner_id: str, key: str, now: datetime
    ) -> tuple[str, str, str, int | None] | None:
        """Erase an expired response before adoption, retaining identity only."""
        self._repo.purge_expired_idempotency(
            owner_id=owner_id, now=now + timedelta(microseconds=1)
        )
        with connect(self._repo.db_path) as conn:
            # A replay may fail closed and roll back its owner unit. Purge this
            # key's expired adopted body outside that unit before reading it.
            conn.execute(
                "UPDATE sync_command_receipts SET result = NULL "
                "WHERE owner_id = ? AND expires_at <= ? AND command_id IN "
                "(SELECT command_id FROM sync_legacy_keys "
                "WHERE owner_id = ? AND key_digest = ?)",
                (owner_id, now.isoformat(), owner_id, idempotency_key_digest(key)),
            )
            row = conn.execute(
                "SELECT command, request_hash, resource_id, created_at, "
                "json_extract(response_body, '$._expired_revision') "
                "FROM idempotency_records WHERE owner_id=? AND key_hash=?",
                (owner_id, idempotency_key_digest(key)),
            ).fetchone()
        if row is None or datetime.fromisoformat(row[3]) > now - IDEMPOTENCY_RETENTION:
            return None
        return row[0], row[1], row[2], row[4]

    def create_task(
        self,
        service: LegacyTagService,
        payload: TaskCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        now: datetime,
    ) -> tuple[TaskDocument, FormulationSettingsDocument | None]:
        request = task_create_request(owner_id, idempotency_key, payload)
        refusal: DomainRefusal | None = None
        result: tuple[TaskDocument, FormulationSettingsDocument | None] | None = None
        try:
            with self._receipts.command(
                self._units, request, self._authority, now=now
            ) as receipt:
                if receipt.replay is not None:
                    return self._task_create_replay(receipt, owner_id=owner_id)
                old = self._repo.get_idempotency(owner_id=owner_id, key=idempotency_key)
                if old is not None:
                    service._idempotency_record(
                        owner_id=owner_id,
                        key=idempotency_key,
                        command="create_task",
                        request_hash=service._request_hash("create_task", payload),
                    )
                    snapshot = TaskDocument.model_validate(old.response_body)
                    if snapshot.owner_id != owner_id or snapshot.id != old.resource_id:
                        raise SyncCommandError("COMMAND_INTEGRITY")
                    if old.created_at <= now - IDEMPOTENCY_RETENTION:
                        try:
                            current = self._repo.get_for_owner(
                                snapshot.id, owner_id=owner_id
                            )
                        except NotFoundError:
                            raise IdempotencyReceiptUnavailableError() from None
                        result = (current, service.formulation_settings(owner_id))
                        changes: list[dict[str, Any]] = []
                    else:
                        try:
                            current = self._repo.get_for_owner(
                                snapshot.id, owner_id=owner_id
                            )
                        except NotFoundError:
                            current = None
                        old_result = service._task_command_result(
                            old, owner_id=owner_id
                        )
                        result = (old_result.task, old_result.formulation_settings)
                        changes = (
                            [
                                {
                                    "operation": "upsert",
                                    "entity_type": "task",
                                    "record_key": [owner_id, result[0].id],
                                    "value": encode_task(result[0]),
                                }
                            ]
                            if current is None or current.revision < result[0].revision
                            else []
                        )
                    receipt.accept(
                        changes,
                        result=self._task_create_result(*result),
                        id_bindings=[self._task_binding(result[0].id)],
                    )
                    return result
                decision, task = self._rust.decide_create_task(
                    payload,
                    owner_id=owner_id,
                    now=now,
                    entity_id=task_entity_id(owner_id, idempotency_key),
                )
                if decision.refusal is not None:
                    receipt.reject(decision.refusal)
                    refusal = decision.refusal
                else:
                    assert decision.change_set is not None and task is not None
                    settings = service.formulation_settings(owner_id)
                    self._repo.create(task)
                    receipt.accept(
                        decision.change_set["changes"],
                        result=self._task_create_result(task, settings),
                        id_bindings=[self._task_binding(task.id)],
                    )
                    result = (task, settings)
        except SyncCommandError as exc:
            if exc.code == "IDEMPOTENCY_KEY_REUSED":
                raise ConflictError("Idempotency-Key", idempotency_key) from None
            raise
        if refusal is not None:
            raise _refused(refusal)
        assert result is not None
        return result

    @staticmethod
    def _task_create_result(
        task: TaskDocument, settings: FormulationSettingsDocument | None
    ) -> dict[str, Any]:
        return {
            "task": task.model_dump(mode="json"),
            "formulation_settings": (
                settings.model_dump(mode="json") if settings is not None else None
            ),
        }

    @staticmethod
    def _task_binding(entity_id: str) -> dict[str, str]:
        return {"entity_type": "task", "alias_id": TASK_ALIAS, "entity_id": entity_id}

    @staticmethod
    def _replay_bindings(replay: dict[str, Any]) -> dict[tuple[str, str], str]:
        rows = replay.get("id_bindings")
        if not isinstance(rows, list):
            raise SyncCommandError("COMMAND_INTEGRITY")
        bindings: dict[tuple[str, str], str] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise SyncCommandError("COMMAND_INTEGRITY")
            kind, alias, entity_id = (
                row.get("entity_type"),
                row.get("alias_id"),
                row.get("entity_id"),
            )
            if (
                not isinstance(kind, str)
                or not kind
                or not isinstance(alias, str)
                or not alias
                or not isinstance(entity_id, str)
                or not entity_id
            ):
                raise SyncCommandError("COMMAND_INTEGRITY")
            key = (kind, alias)
            if key in bindings:
                raise SyncCommandError("COMMAND_INTEGRITY")
            bindings[key] = entity_id
        return bindings

    @classmethod
    def _bound_id(cls, replay: dict[str, Any], kind: str, alias: str) -> str:
        entity_id = cls._replay_bindings(replay).get((kind, alias))
        if entity_id is None:
            raise SyncCommandError("COMMAND_INTEGRITY")
        return entity_id

    def _task_create_replay(
        self,
        receipt: ReceiptCommand[Connection],
        *,
        owner_id: str,
        alias: str = TASK_ALIAS,
        task_id: str | None = None,
        action: str | None = None,
    ) -> tuple[TaskDocument, FormulationSettingsDocument | None]:
        replay = receipt.replay
        assert replay is not None
        if replay["outcome"] == "rejected":
            if receipt.replay_refusal is None:
                raise SyncCommandError("COMMAND_INTEGRITY")
            raise _refused(receipt.replay_refusal, action)
        if replay["result"] is not None:
            try:
                body = replay["result"]
                task = TaskDocument.model_validate(body["task"])
                settings = (
                    FormulationSettingsDocument.model_validate(
                        body["formulation_settings"]
                    )
                    if body["formulation_settings"] is not None
                    else None
                )
            except KeyError, TypeError, ValueError:
                raise SyncCommandError("COMMAND_INTEGRITY") from None
            if (
                task.owner_id != owner_id
                or (task_id is not None and task.id != task_id)
                or task.id != self._bound_id(replay, "task", alias)
            ):
                raise SyncCommandError("COMMAND_INTEGRITY")
            return task, settings
        binding = next(
            (
                row
                for row in replay["id_bindings"]
                if row.get("entity_type") == "task" and row.get("alias_id") == alias
            ),
            None,
        )
        if binding is None or (
            task_id is not None and binding.get("entity_id") != task_id
        ):
            raise SyncCommandError("COMMAND_INTEGRITY")
        try:
            task = self._repo.get_for_owner(binding["entity_id"], owner_id=owner_id)
        except NotFoundError:
            raise IdempotencyReceiptUnavailableError() from None
        return task, None

    def mutate_task(
        self,
        service: LegacyTagService,
        operation: str,
        task_id: str,
        payload: TaskUpdateRequest | TaskTransitionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        now: datetime,
    ) -> tuple[TaskDocument, FormulationSettingsDocument | None]:
        if operation == "update":
            assert isinstance(payload, TaskUpdateRequest)
            request = task_update_request(owner_id, idempotency_key, task_id, payload)
            alias = TASK_UPDATE_ALIAS
        else:
            assert isinstance(payload, TaskTransitionRequest)
            request = task_transition_request(
                owner_id, idempotency_key, task_id, payload
            )
            alias = TASK_TRANSITION_ALIAS
        refusal: DomainRefusal | None = None
        result: tuple[TaskDocument, FormulationSettingsDocument | None] | None = None
        try:
            with self._receipts.command(
                self._units, request, self._authority, now=now
            ) as receipt:
                if receipt.replay is not None:
                    return self._task_create_replay(
                        receipt,
                        owner_id=owner_id,
                        alias=alias,
                        task_id=task_id,
                        action=(
                            payload.action
                            if isinstance(payload, TaskTransitionRequest)
                            else None
                        ),
                    )
                old = self._repo.get_idempotency(owner_id=owner_id, key=idempotency_key)
                if old is not None:
                    return self._adopt_task_mutation(
                        service,
                        receipt,
                        old,
                        operation,
                        payload,
                        task_id=task_id,
                        alias=alias,
                        owner_id=owner_id,
                        key=idempotency_key,
                        now=now,
                    )
                before = self._repo.get_for_owner(task_id, owner_id=owner_id)
                if operation == "update":
                    assert isinstance(payload, TaskUpdateRequest)
                    decision, updated = self._rust.decide_update_task(
                        before, payload, owner_id=owner_id, now=now
                    )
                    ack = None
                else:
                    assert isinstance(payload, TaskTransitionRequest)
                    decision, moved = self._rust.decide_transition_task(
                        before, payload, owner_id=owner_id, now=now
                    )
                    updated = moved.task if moved is not None else None
                    ack = moved.park_ack if moved is not None else None
                if decision.refusal is not None:
                    receipt.reject(decision.refusal)
                    refusal = decision.refusal
                else:
                    assert decision.change_set is not None and updated is not None
                    settings = service.formulation_settings(owner_id)
                    self._repo.save(updated)
                    if operation == "update":
                        service._log_due_date_move(before, updated, owner_id=owner_id)
                    if ack is not None:
                        self._repo.save_park_ack(ack)
                    changes = [
                        (
                            {**change, "value": encode_task(updated)}
                            if change.get("entity_type") == "task"
                            and change.get("operation") == "upsert"
                            else change
                        )
                        for change in decision.change_set["changes"]
                    ]
                    receipt.accept(
                        changes,
                        result=self._task_create_result(updated, settings),
                        id_bindings=[self._task_mutation_binding(task_id, alias)],
                    )
                    result = (updated, settings)
        except SyncCommandError as exc:
            if exc.code == "IDEMPOTENCY_KEY_REUSED":
                raise ConflictError("Idempotency-Key", idempotency_key) from None
            raise
        if refusal is not None:
            if operation == "update":
                assert isinstance(payload, TaskUpdateRequest)
                _, request_error, duplicate_tags = self._rust._update_task_parts(
                    before, payload
                )
                raise _ordered_refusal(refusal, request_error, duplicate_tags)
            assert isinstance(payload, TaskTransitionRequest)
            raise _refused(refusal, payload.action)
        assert result is not None
        return result

    def _adopt_task_mutation(
        self,
        service: LegacyTagService,
        receipt: ReceiptCommand[Connection],
        old: IdempotencyRecord,
        operation: str,
        payload: TaskUpdateRequest | TaskTransitionRequest,
        *,
        task_id: str,
        alias: str,
        owner_id: str,
        key: str,
        now: datetime,
    ) -> tuple[TaskDocument, FormulationSettingsDocument | None]:
        legacy_command = f"{operation}_task:{task_id}"
        service._idempotency_record(
            owner_id=owner_id,
            key=key,
            command=legacy_command,
            request_hash=service._request_hash(legacy_command, payload),
        )
        snapshot = TaskDocument.model_validate(old.response_body)
        if snapshot.owner_id != owner_id or snapshot.id != task_id:
            raise SyncCommandError("COMMAND_INTEGRITY")
        try:
            current = self._repo.get_for_owner(task_id, owner_id=owner_id)
        except NotFoundError:
            current = None
        fresh = old.created_at > now - IDEMPOTENCY_RETENTION
        if not fresh and current is None:
            raise IdempotencyReceiptUnavailableError()
        if fresh:
            old_result = service._task_command_result(old, owner_id=owner_id)
            result = (old_result.task, old_result.formulation_settings)
        else:
            assert current is not None
            result = (current, service.formulation_settings(owner_id))
        receipt.accept(
            (
                [
                    {
                        "operation": "upsert",
                        "entity_type": "task",
                        "record_key": [owner_id, task_id],
                        "value": encode_task(result[0]),
                    }
                ]
                if fresh and (current is None or current.revision < result[0].revision)
                else []
            ),
            result=self._task_create_result(*result),
            id_bindings=[self._task_mutation_binding(task_id, alias)],
        )
        return result

    @staticmethod
    def _task_mutation_binding(entity_id: str, alias: str) -> dict[str, str]:
        return {"entity_type": "task", "alias_id": alias, "entity_id": entity_id}

    def run_legacy_child(
        self,
        service: LegacyTagService,
        operation: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        raw_command: Callable[..., object],
        *,
        now: datetime,
    ) -> TaskSubtaskDocument | TaskCommentDocument:
        owner_id = cast(str, kwargs["owner_id"])
        key = cast(str, kwargs["idempotency_key"])
        task_id = cast(str, args[0])
        is_subtask = "subtask" in operation
        kind = "subtask" if is_subtask else "comment"
        payload = cast(BaseModel, args[-1])
        entity_id = cast(str, args[1]) if len(args) == 3 else f"{kind}_pending"
        action = operation.split("_", 1)[0]
        command_type = f"{kind}.{action}"
        body: dict[str, Any] = {
            "command_type": command_type,
            "task_id": task_id,
            "body": payload.model_dump(mode="json"),
        }
        if kind == "comment" and action == "create":
            body["actor_id"] = kwargs["actor_id"]
        request = CommandRequest.legacy(
            owner_id,
            key,
            command_type,
            body,
            entity_id=entity_id,
            route=operation,
        )
        expired = self._expired_legacy_identity(owner_id, key, now)
        if expired is not None:
            legacy_command = self._child_legacy_command(operation, args)
            if expired[:2] != (
                legacy_command,
                request_fingerprint(legacy_command, payload),
            ):
                raise ConflictError("Idempotency-Key", key)
            with self._receipts.command(
                self._units, request, self._authority, now=now
            ) as receipt:
                if receipt.replay is not None:
                    return self._child_replay(
                        receipt,
                        kind=kind,
                        task_id=task_id,
                        owner_id=owner_id,
                        alias=entity_id,
                    )
                current = self._child_current(
                    kind, expired[2], task_id=task_id, owner_id=owner_id
                )
                receipt.accept(
                    [],
                    result_versions=(
                        [
                            {
                                "entity_type": kind,
                                "record_key": [expired[2]],
                                "record_version": "1",
                                "edit_revision": str(expired[3]),
                            }
                        ]
                        if expired[3] is not None
                        else []
                    ),
                    id_bindings=[
                        {
                            "entity_type": kind,
                            "alias_id": entity_id,
                            "entity_id": expired[2],
                        }
                    ],
                )
            if current is None or expired[3] is None or current.revision < expired[3]:
                raise IdempotencyReceiptUnavailableError()
            return current
        failure: Exception | None = None
        result: TaskSubtaskDocument | TaskCommentDocument | None = None
        try:
            with self._receipts.command(
                self._units, request, self._authority, now=now
            ) as receipt:
                if receipt.replay is not None:
                    return self._child_replay(
                        receipt,
                        kind=kind,
                        task_id=task_id,
                        owner_id=owner_id,
                        alias=entity_id,
                    )
                old = self._repo.get_idempotency(owner_id=owner_id, key=key)
                if old is not None and old.command != self._child_legacy_command(
                    operation, args
                ):
                    raise ConflictError("Idempotency-Key", key)
                previous_id = (
                    old.resource_id
                    if old is not None
                    else (cast(str, args[1]) if len(args) == 3 else None)
                )
                before = self._child_current(
                    kind, previous_id, task_id=task_id, owner_id=owner_id
                )
                try:
                    result = cast(
                        TaskSubtaskDocument | TaskCommentDocument,
                        raw_command(service, *args, **kwargs),
                    )
                except (NotFoundError, ConflictError, ValidationFailure) as exc:
                    if old is not None:
                        raise
                    refusal = self._child_error_refusal(exc)
                    if refusal is None:
                        raise
                    receipt.reject(refusal)
                    failure = exc
                else:
                    if result.owner_id != owner_id or result.task_id != task_id:
                        raise SyncCommandError("COMMAND_INTEGRITY")
                    changes = (
                        [
                            {
                                "operation": "upsert",
                                "entity_type": kind,
                                "record_key": [owner_id, result.id],
                                "value": self._child_public(result),
                            }
                        ]
                        if before != result
                        else []
                    )
                    receipt.accept(
                        changes,
                        result=result.model_dump(mode="json"),
                        source_expires_at=(
                            old.created_at + IDEMPOTENCY_RETENTION
                            if old is not None
                            else None
                        ),
                        result_versions=[
                            {
                                "entity_type": kind,
                                "record_key": [result.id],
                                "record_version": "1",
                                "edit_revision": str(result.revision),
                            }
                        ],
                        id_bindings=[
                            {
                                "entity_type": kind,
                                "alias_id": entity_id,
                                "entity_id": result.id,
                            }
                        ],
                    )
        except SyncCommandError as exc:
            if exc.code == "IDEMPOTENCY_KEY_REUSED":
                raise ConflictError("Idempotency-Key", key) from None
            raise
        if failure is not None:
            raise failure
        assert result is not None
        return result

    @staticmethod
    def _child_legacy_command(operation: str, args: tuple[object, ...]) -> str:
        parts = [operation, cast(str, args[0])]
        if len(args) == 3:
            parts.append(cast(str, args[1]))
        return ":".join(parts)

    def _child_current(
        self, kind: str, entity_id: str | None, *, task_id: str, owner_id: str
    ) -> TaskSubtaskDocument | TaskCommentDocument | None:
        if entity_id is None:
            return None
        try:
            if kind == "subtask":
                return self._repo.get_subtask_for_owner(
                    entity_id, owner_id=owner_id, task_id=task_id
                )
            return self._repo.get_comment_for_owner(
                entity_id, owner_id=owner_id, task_id=task_id
            )
        except NotFoundError:
            return None

    @staticmethod
    def _child_public(
        result: TaskSubtaskDocument | TaskCommentDocument,
    ) -> dict[str, Any]:
        if isinstance(result, TaskSubtaskDocument):
            return {
                "id": result.id,
                "task_id": result.task_id,
                "title": result.title,
                "state": result.state,
                "order_key": str(result.order_key),
                "revision": str(result.revision),
            }
        return {
            "id": result.id,
            "task_id": result.task_id,
            "body": result.body,
            "actor_id": result.actor_id,
            "created_at": result.created_at.isoformat().replace("+00:00", "Z"),
            "edited_at": (
                result.edited_at.isoformat().replace("+00:00", "Z")
                if result.edited_at is not None
                else None
            ),
            "revision": str(result.revision),
        }

    @staticmethod
    def _child_error_refusal(error: Exception) -> DomainRefusal | None:
        resource = {
            "Task subtask": "subtask",
            "Task comment": "comment",
        }
        if isinstance(error, NotFoundError):
            return DomainRefusal(
                "not_found",
                None,
                (
                    resource.get(error.resource, error.resource.lower()),
                    [error.identifier],
                ),
                None,
            )
        if isinstance(error, ConflictError):
            return DomainRefusal(
                "revision_conflict",
                None,
                (
                    resource.get(error.resource, error.resource.lower()),
                    [error.identifier],
                ),
                None,
            )
        if (
            isinstance(error, ValidationFailure)
            and str(error) == "Subtask transition requires a different state."
        ):
            return DomainRefusal("subtask_already_in_state", None, None, None)
        return None

    @staticmethod
    def _child_rejected(refusal: DomainRefusal) -> Exception:
        if refusal.reason == "subtask_already_in_state":
            return ValidationFailure("Subtask transition requires a different state.")
        entity, ids = refusal.entity or ("", [])
        resource = {
            "task": "Task",
            "subtask": "Task subtask" if refusal.reason == "not_found" else "Subtask",
            "comment": "Task comment" if refusal.reason == "not_found" else "Comment",
        }.get(entity)
        if resource is None or len(ids) != 1:
            raise SyncCommandError("COMMAND_INTEGRITY")
        if refusal.reason == "not_found":
            return NotFoundError(resource, ids[0])
        if refusal.reason == "revision_conflict":
            return ConflictError(
                resource,
                ids[0],
                f"{resource} '{ids[0]}' has newer changes; reload before saving.",
            )
        raise SyncCommandError("COMMAND_INTEGRITY")

    def _child_replay(
        self,
        receipt: ReceiptCommand[Connection],
        *,
        kind: str,
        task_id: str,
        owner_id: str,
        alias: str,
    ) -> TaskSubtaskDocument | TaskCommentDocument:
        replay = receipt.replay
        assert replay is not None
        if replay["outcome"] == "rejected":
            if receipt.replay_refusal is None:
                raise SyncCommandError("COMMAND_INTEGRITY")
            raise self._child_rejected(receipt.replay_refusal)
        model = TaskSubtaskDocument if kind == "subtask" else TaskCommentDocument
        if replay["result"] is not None:
            try:
                result = model.model_validate(replay["result"])
            except ValidationError:
                raise SyncCommandError("COMMAND_INTEGRITY") from None
            if result.owner_id != owner_id or result.task_id != task_id:
                raise SyncCommandError("COMMAND_INTEGRITY")
            current = self._child_current(
                kind, result.id, task_id=task_id, owner_id=owner_id
            )
            if current is None or current.revision < result.revision:
                raise IdempotencyReceiptUnavailableError()
            result = current
        else:
            binding = next(
                (
                    row
                    for row in replay["id_bindings"]
                    if row.get("entity_type") == kind and row.get("alias_id") == alias
                ),
                None,
            )
            if binding is None:
                raise SyncCommandError("COMMAND_INTEGRITY")
            current = self._child_current(
                kind, binding["entity_id"], task_id=task_id, owner_id=owner_id
            )
            versions = [
                version
                for version in replay["result_versions"]
                if version.get("entity_type") == kind
                and version.get("record_key") == [binding["entity_id"]]
            ]
            if (
                current is None
                or len(versions) != 1
                or current.revision < int(versions[0]["edit_revision"])
            ):
                raise IdempotencyReceiptUnavailableError()
            result = current
        if result.id != self._bound_id(replay, kind, alias):
            raise SyncCommandError("COMMAND_INTEGRITY")
        return result

    def run_legacy_smart_add(
        self,
        service: LegacyTagService,
        payload: SmartAddTaskCreateRequest,
        kwargs: dict[str, object],
        raw_command: Callable[..., object],
        *,
        now: datetime,
    ) -> SmartAddTaskResultDocument:
        owner_id = cast(str, kwargs["owner_id"])
        key = cast(str, kwargs["idempotency_key"])
        request = CommandRequest.legacy(
            owner_id,
            key,
            "task.smart_add",
            {"command_type": "task.smart_add", "body": payload.model_dump(mode="json")},
            entity_id="smart_add_task",
            route="smart_add_task",
        )
        expired = self._expired_legacy_identity(owner_id, key, now)
        if expired is not None:
            return self._adopt_expired_smart_add(
                service,
                payload,
                request,
                expired,
                owner_id=owner_id,
                key=key,
                now=now,
            )
        result: SmartAddTaskResultDocument | None = None
        failure: NotFoundError | ValidationFailure | None = None
        try:
            with self._receipts.command(
                self._units, request, self._authority, now=now
            ) as receipt:
                if receipt.replay is not None:
                    return self._smart_add_replay(receipt, owner_id=owner_id)
                old = self._repo.get_idempotency(owner_id=owner_id, key=key)
                if old is not None:
                    service._idempotency_record(
                        owner_id=owner_id,
                        key=key,
                        command="smart_add_task",
                        request_hash=service._request_hash("smart_add_task", payload),
                    )
                    snapshot = SmartAddTaskResultDocument.model_validate(
                        old.response_body
                    )
                    if (
                        snapshot.task.owner_id != owner_id
                        or snapshot.task.id != old.resource_id
                    ):
                        raise SyncCommandError("COMMAND_INTEGRITY")
                    before = self._smart_add_current(snapshot, owner_id=owner_id)
                else:
                    before = {}
                try:
                    result = cast(
                        SmartAddTaskResultDocument,
                        raw_command(service, payload, **kwargs),
                    )
                except (NotFoundError, ValidationFailure) as exc:
                    if isinstance(exc, NotFoundError):
                        refusal = DomainRefusal(
                            "not_found",
                            None,
                            (exc.resource.lower(), [exc.identifier]),
                            None,
                        )
                    elif str(exc) == "Task project must be active.":
                        refusal = DomainRefusal("project_not_active", None, None, None)
                    elif str(exc) == (
                        "Task contexts must be active; task tags must be active."
                    ):
                        refusal = DomainRefusal("tag_not_active", None, None, None)
                    else:
                        raise
                    receipt.reject(refusal)
                    failure = exc
                else:
                    if result.task.owner_id != owner_id:
                        raise SyncCommandError("COMMAND_INTEGRITY")
                    current = self._smart_add_current(result, owner_id=owner_id)
                    changes = [
                        {
                            "operation": "upsert",
                            "entity_type": kind,
                            "record_key": [owner_id, record.id],
                            "value": self._smart_add_public(
                                current.get((kind, record.id), record)
                            ),
                        }
                        for kind, record in (
                            [("task", result.task)]
                            + (
                                [("project", result.project)]
                                if result.project is not None
                                else []
                            )
                            + [("tag", tag) for tag in result.tags]
                        )
                        if before.get((kind, record.id)) != record
                    ]
                    bindings = [
                        {
                            "entity_type": "task",
                            "alias_id": "smart_add_task",
                            "entity_id": result.task.id,
                        }
                    ]
                    if result.project is not None:
                        bindings.append(
                            {
                                "entity_type": "project",
                                "alias_id": "smart_add_project",
                                "entity_id": result.project.id,
                            }
                        )
                    if result.created.project_id is not None:
                        bindings.append(
                            {
                                "entity_type": "project",
                                "alias_id": "smart_add_created_project",
                                "entity_id": result.created.project_id,
                            }
                        )
                    bindings.extend(
                        {
                            "entity_type": "tag",
                            "alias_id": f"smart_add_tag_{index}",
                            "entity_id": tag.id,
                        }
                        for index, tag in enumerate(result.tags)
                    )
                    bindings.extend(
                        {
                            "entity_type": "tag",
                            "alias_id": f"smart_add_created_tag_{index}",
                            "entity_id": tag_id,
                        }
                        for index, tag_id in enumerate(result.created.tag_ids)
                    )
                    receipt.accept(
                        changes,
                        result=result.model_dump(mode="json"),
                        id_bindings=bindings,
                        source_expires_at=(
                            old.created_at + IDEMPOTENCY_RETENTION
                            if old is not None
                            else None
                        ),
                    )
        except SyncCommandError as exc:
            if exc.code == "IDEMPOTENCY_KEY_REUSED":
                raise ConflictError("Idempotency-Key", key) from None
            raise
        if failure is not None:
            raise failure
        assert result is not None
        return result

    def _adopt_expired_smart_add(
        self,
        service: LegacyTagService,
        payload: SmartAddTaskCreateRequest,
        request: CommandRequest,
        expired: tuple[str, str, str, int | None],
        *,
        owner_id: str,
        key: str,
        now: datetime,
    ) -> SmartAddTaskResultDocument:
        if expired[:2] != (
            "smart_add_task",
            service._request_hash("smart_add_task", payload),
        ):
            raise ConflictError("Idempotency-Key", key)
        # The expired legacy snapshot no longer contains durable typed
        # classification bindings. A current membership cannot reconstruct it.
        with self._receipts.command(
            self._units, request, self._authority, now=now
        ) as receipt:
            if receipt.replay is not None:
                if (
                    receipt.replay["result"] is None
                    and (payload.project is not None or payload.tags)
                    and len(receipt.replay["id_bindings"]) == 1
                ):
                    raise IdempotencyReceiptUnavailableError()
                return self._smart_add_replay(receipt, owner_id=owner_id)
            try:
                task = self._repo.get_for_owner(expired[2], owner_id=owner_id)
            except NotFoundError:
                task = None
            receipt.accept(
                [],
                result_versions=(
                    [
                        {
                            "entity_type": "task",
                            "record_key": [expired[2]],
                            "record_version": "1",
                            "edit_revision": str(expired[3]),
                        }
                    ]
                    if expired[3] is not None
                    else []
                ),
                id_bindings=[
                    {
                        "entity_type": "task",
                        "alias_id": "smart_add_task",
                        "entity_id": expired[2],
                    }
                ],
            )
        if (
            task is None
            or expired[3] is None
            or task.revision < expired[3]
            or payload.project is not None
            or payload.tags
            or task.project_id is not None
            or task.tag_ids
        ):
            raise IdempotencyReceiptUnavailableError()
        return SmartAddTaskResultDocument(
            task=task,
            project=None,
            tags=[],
            created=SmartAddCreatedDocument(project_id=None, tag_ids=[]),
        )

    @staticmethod
    def _smart_add_public(
        record: TaskDocument | ProjectDocument | TagDocument,
    ) -> dict[str, Any]:
        if isinstance(record, TaskDocument):
            return encode_task(record)
        if isinstance(record, ProjectDocument):
            return encode_project(record)
        return encode_tag(record)

    def _smart_add_current(
        self, result: SmartAddTaskResultDocument, *, owner_id: str
    ) -> dict[tuple[str, str], TaskDocument | ProjectDocument | TagDocument]:
        current: dict[tuple[str, str], TaskDocument | ProjectDocument | TagDocument] = (
            {}
        )
        for kind, records, getter in (
            ("task", [result.task], self._repo.get_for_owner),
            (
                "project",
                [result.project] if result.project is not None else [],
                self._repo.get_project_for_owner,
            ),
            ("tag", result.tags, self._repo.get_tag_for_owner),
        ):
            for record in records:
                with suppress(NotFoundError):
                    current[(kind, record.id)] = getter(record.id, owner_id=owner_id)
        return current

    def _smart_add_replay(
        self, receipt: ReceiptCommand[Connection], *, owner_id: str
    ) -> SmartAddTaskResultDocument:
        replay = receipt.replay
        assert replay is not None
        if replay["outcome"] == "rejected":
            if receipt.replay_refusal is None:
                raise SyncCommandError("COMMAND_INTEGRITY")
            raise _refused(receipt.replay_refusal)
        if replay["result"] is not None:
            try:
                result = SmartAddTaskResultDocument.model_validate(replay["result"])
            except ValidationError:
                raise SyncCommandError("COMMAND_INTEGRITY") from None
        else:
            bound = self._replay_bindings(replay)
            task_id = bound.get(("task", "smart_add_task"))
            if task_id is None:
                raise SyncCommandError("COMMAND_INTEGRITY")
            try:
                task = self._repo.get_for_owner(task_id, owner_id=owner_id)
                project_id = bound.get(("project", "smart_add_project"))
                project = (
                    self._repo.get_project_for_owner(project_id, owner_id=owner_id)
                    if project_id is not None
                    else None
                )
                ordered_tags = sorted(
                    (int(alias.removeprefix("smart_add_tag_")), entity_id)
                    for (kind, alias), entity_id in bound.items()
                    if kind == "tag" and alias.startswith("smart_add_tag_")
                )
                if [index for index, _ in ordered_tags] != list(
                    range(len(ordered_tags))
                ):
                    raise SyncCommandError("COMMAND_INTEGRITY")
                tags = [
                    self._repo.get_tag_for_owner(tag_id, owner_id=owner_id)
                    for _, tag_id in ordered_tags
                ]
            except NotFoundError:
                raise IdempotencyReceiptUnavailableError() from None
            except TypeError, ValueError:
                raise SyncCommandError("COMMAND_INTEGRITY") from None
            result = SmartAddTaskResultDocument(
                task=task,
                project=project,
                tags=tags,
                created=SmartAddCreatedDocument(
                    project_id=bound.get(("project", "smart_add_created_project")),
                    tag_ids=[
                        entity_id
                        for (kind, alias), entity_id in bound.items()
                        if kind == "tag" and alias.startswith("smart_add_created_tag_")
                    ],
                ),
            )
        if (
            result.task.owner_id != owner_id
            or (result.project is not None and result.project.owner_id != owner_id)
            or any(tag.owner_id != owner_id for tag in result.tags)
        ):
            raise SyncCommandError("COMMAND_INTEGRITY")
        if replay["result"] is None and (
            result.task.project_id != (result.project.id if result.project else None)
            or result.task.tag_ids != [tag.id for tag in result.tags]
        ):
            raise IdempotencyReceiptUnavailableError()
        expected = {("task", "smart_add_task"): result.task.id}
        if result.project is not None:
            expected[("project", "smart_add_project")] = result.project.id
        if result.created.project_id is not None:
            expected[("project", "smart_add_created_project")] = (
                result.created.project_id
            )
        expected.update(
            {
                ("tag", f"smart_add_tag_{index}"): tag.id
                for index, tag in enumerate(result.tags)
            }
        )
        expected.update(
            {
                ("tag", f"smart_add_created_tag_{index}"): tag_id
                for index, tag_id in enumerate(result.created.tag_ids)
            }
        )
        if self._replay_bindings(replay) != expected:
            raise SyncCommandError("COMMAND_INTEGRITY")
        return result

    def create_project(
        self,
        service: LegacyTagService,
        payload: ProjectCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        now: datetime,
    ) -> ProjectDocument:
        return self._project_command(
            service,
            "create",
            payload,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            now=now,
        )

    def update_project(
        self,
        service: LegacyTagService,
        project_id: str,
        payload: ProjectUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        now: datetime,
    ) -> ProjectDocument:
        return self._project_command(
            service,
            "update",
            payload,
            project_id=project_id,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            now=now,
        )

    def archive_project(
        self,
        service: LegacyTagService,
        project_id: str,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        now: datetime,
    ) -> ProjectDocument:
        return self._project_command(
            service,
            "archive",
            payload,
            project_id=project_id,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            now=now,
        )

    def unarchive_project(
        self,
        service: LegacyTagService,
        project_id: str,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        now: datetime,
    ) -> ProjectDocument:
        return self._project_command(
            service,
            "unarchive",
            payload,
            project_id=project_id,
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            now=now,
        )

    def _project_command(
        self,
        service: LegacyTagService,
        operation: str,
        payload: ProjectCreateRequest | ProjectUpdateRequest | ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        now: datetime,
        project_id: str | None = None,
    ) -> ProjectDocument:
        if operation == "create":
            request = project_create_request(owner_id, idempotency_key, payload)  # type: ignore[arg-type]
            alias = PROJECT_ALIAS
        elif operation == "update":
            assert project_id is not None
            request = project_update_request(owner_id, idempotency_key, project_id, payload)  # type: ignore[arg-type]
            alias = PROJECT_UPDATE_ALIAS
        elif operation == "archive":
            assert project_id is not None
            request = project_archive_request(owner_id, idempotency_key, project_id, payload)  # type: ignore[arg-type]
            alias = PROJECT_ARCHIVE_ALIAS
        else:
            assert project_id is not None
            request = project_unarchive_request(owner_id, idempotency_key, project_id, payload)  # type: ignore[arg-type]
            alias = PROJECT_UNARCHIVE_ALIAS
        refusal: DomainRefusal | None = None
        result: ProjectDocument | None = None
        requested_name = getattr(payload, "name", None)
        attempted_name = (
            display_project_name(requested_name)
            if isinstance(requested_name, str)
            else None
        )
        try:
            with self._receipts.command(
                self._units, request, self._authority, now=now
            ) as receipt:
                if receipt.replay is not None:
                    return self._project_replay(
                        receipt,
                        owner_id=owner_id,
                        project_id=project_id,
                        alias=alias,
                        attempted_name=attempted_name,
                    )
                adopted = self._adopt_project(
                    service,
                    receipt,
                    operation=operation,
                    payload=payload,
                    project_id=project_id,
                    alias=alias,
                    owner_id=owner_id,
                    key=idempotency_key,
                    now=now,
                )
                if adopted is not None:
                    return adopted
                if operation == "create":
                    decision, project = self._rust.decide_create_project(
                        payload, owner_id=owner_id, now=now, entity_id=project_entity_id(owner_id, idempotency_key)  # type: ignore[arg-type]
                    )
                else:
                    assert project_id is not None
                    project_before = self._repo.get_project_for_owner(
                        project_id, owner_id=owner_id
                    )
                    if operation == "update":
                        decision, project = self._rust.decide_update_project(project_before, payload, owner_id=owner_id, now=now)  # type: ignore[arg-type]
                    elif operation == "archive":
                        decision, project = self._rust.decide_archive_project(project_before, payload, owner_id=owner_id, now=now)  # type: ignore[arg-type]
                    else:
                        decision, project = self._rust.decide_unarchive_project(project_before, payload, owner_id=owner_id, now=now)  # type: ignore[arg-type]
                if decision.refusal is not None:
                    receipt.reject(decision.refusal)
                    refusal = decision.refusal
                else:
                    assert decision.change_set is not None and project is not None
                    if operation == "create":
                        self._repo.create_project(project)
                    elif decision.change_set["changes"]:
                        self._repo.save_project(project)
                    receipt.accept(
                        decision.change_set["changes"],
                        result=project.model_dump(mode="json"),
                        id_bindings=[
                            {
                                "entity_type": "project",
                                "alias_id": alias,
                                "entity_id": project.id,
                            }
                        ],
                    )
                    result = project
        except SyncCommandError as exc:
            if exc.code == "IDEMPOTENCY_KEY_REUSED":
                raise ConflictError("Idempotency-Key", idempotency_key) from None
            raise
        if refusal is not None:
            raise _refused(refusal, attempted_name=attempted_name)
        assert result is not None
        return result

    def _adopt_project(
        self,
        service: LegacyTagService,
        command: ReceiptCommand[Connection],
        *,
        operation: str,
        payload: ProjectCreateRequest | ProjectUpdateRequest | ExpectedRevisionRequest,
        project_id: str | None,
        alias: str,
        owner_id: str,
        key: str,
        now: datetime,
    ) -> ProjectDocument | None:
        old = self._repo.get_idempotency(owner_id=owner_id, key=key)
        if old is None:
            return None
        legacy_command = (
            "create_project"
            if operation == "create"
            else f"{operation}_project:{project_id}"
        )
        service._idempotency_record(
            owner_id=owner_id,
            key=key,
            command=legacy_command,
            request_hash=service._request_hash(legacy_command, payload),
        )
        try:
            snapshot = ProjectDocument.model_validate(old.response_body)
        except TypeError, ValueError:
            raise SyncCommandError("COMMAND_INTEGRITY") from None
        if (
            snapshot.owner_id != owner_id
            or snapshot.id != old.resource_id
            or (project_id is not None and snapshot.id != project_id)
        ):
            raise SyncCommandError("COMMAND_INTEGRITY")
        try:
            current = self._repo.get_project_for_owner(snapshot.id, owner_id=owner_id)
        except NotFoundError:
            current = None
        fresh = old.created_at > now - IDEMPOTENCY_RETENTION
        if not fresh and current is None:
            raise IdempotencyReceiptUnavailableError()
        changed = fresh and (current is None or current.revision < snapshot.revision)
        result = service._project_result(old, owner_id=owner_id) if fresh else current
        assert result is not None
        command.accept(
            (
                [
                    {
                        "operation": "upsert",
                        "entity_type": "project",
                        "record_key": [owner_id, result.id],
                        "value": encode_project(result),
                    }
                ]
                if changed
                else []
            ),
            result=result.model_dump(mode="json") if fresh else None,
            id_bindings=[
                {"entity_type": "project", "alias_id": alias, "entity_id": result.id}
            ],
        )
        return result

    def _project_replay(
        self,
        command: ReceiptCommand[Connection],
        *,
        owner_id: str,
        project_id: str | None,
        alias: str,
        attempted_name: str | None,
    ) -> ProjectDocument:
        replay = command.replay
        assert replay is not None
        if replay["outcome"] == "rejected":
            if command.replay_refusal is None:
                raise SyncCommandError("COMMAND_INTEGRITY")
            raise _refused(command.replay_refusal, attempted_name=attempted_name)
        if replay["result"] is not None:
            try:
                project = ProjectDocument.model_validate(replay["result"])
            except TypeError, ValueError:
                raise SyncCommandError("COMMAND_INTEGRITY") from None
            if (
                project.owner_id != owner_id
                or (project_id is not None and project.id != project_id)
                or project.id != self._bound_id(replay, "project", alias)
            ):
                raise SyncCommandError("COMMAND_INTEGRITY")
            return project
        binding = next(
            (
                row
                for row in replay["id_bindings"]
                if row.get("entity_type") == "project" and row.get("alias_id") == alias
            ),
            None,
        )
        if binding is None or (
            project_id is not None and binding.get("entity_id") != project_id
        ):
            raise SyncCommandError("COMMAND_INTEGRITY")
        try:
            return self._repo.get_project_for_owner(
                binding["entity_id"], owner_id=owner_id
            )
        except NotFoundError:
            raise IdempotencyReceiptUnavailableError() from None

    def create_tag(
        self,
        service: LegacyTagService,
        payload: TagCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        now: datetime,
    ) -> TagDocument:
        request = tag_create_request(owner_id, idempotency_key, payload)
        request_hash = service._request_hash("create_tag", payload)
        refusal: DomainRefusal | None = None
        unavailable = False
        result: TagDocument | None = None
        try:
            with self._receipts.command(
                self._units, request, self._authority, now=now
            ) as command:
                if command.replay is not None:
                    result, refusal, unavailable = self._replay(
                        command,
                        service,
                        payload,
                        owner_id=owner_id,
                        idempotency_key=idempotency_key,
                        now=now,
                    )
                else:
                    result, refusal, unavailable = self._accept_miss(
                        service,
                        command,
                        payload,
                        owner_id=owner_id,
                        idempotency_key=idempotency_key,
                        request_hash=request_hash,
                        now=now,
                    )
        except SyncCommandError as exc:
            if exc.code == "IDEMPOTENCY_KEY_REUSED":
                raise ConflictError("Idempotency-Key", idempotency_key) from None
            raise
        self._purge_legacy_cache(owner_id, now)
        if refusal is not None:
            raise _refused(refusal, attempted_name=display_tag_name(payload.name))
        if unavailable:
            raise IdempotencyReceiptUnavailableError()
        assert result is not None
        return result

    def update_tag(
        self,
        service: LegacyTagService,
        tag_id: str,
        payload: TagUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        now: datetime,
    ) -> TagDocument:
        request = tag_update_request(owner_id, idempotency_key, tag_id, payload)
        try:
            with self._receipts.command(
                self._units, request, self._authority, now=now
            ) as command:
                if command.replay is not None:
                    return self._update_replay(command, tag_id, owner_id, payload)
                adopted = self._adopt_tag_mutation(
                    service,
                    command,
                    "update",
                    tag_id,
                    payload,
                    owner_id=owner_id,
                    key=idempotency_key,
                    now=now,
                )
                result = (
                    adopted
                    if adopted is not None
                    else self._update_miss(
                        command, tag_id, payload, owner_id=owner_id, now=now
                    )
                )
        except SyncCommandError as exc:
            if exc.code == "IDEMPOTENCY_KEY_REUSED":
                raise ConflictError("Idempotency-Key", idempotency_key) from None
            raise
        if isinstance(result, DomainRefusal):
            raise _refused(
                result,
                attempted_name=(
                    display_tag_name(payload.name) if payload.name is not None else None
                ),
            )
        return result

    def delete_tag(
        self,
        service: LegacyTagService,
        tag_id: str,
        payload: ExpectedRevisionRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        now: datetime,
    ) -> TagDocument:
        request = tag_delete_request(owner_id, idempotency_key, tag_id, payload)
        refusal: DomainRefusal | None = None
        result: TagDocument | None = None
        try:
            with self._receipts.command(
                self._units, request, self._authority, now=now
            ) as command:
                if command.replay is not None:
                    return self._delete_replay(command, tag_id, owner_id)
                adopted = self._adopt_tag_mutation(
                    service,
                    command,
                    "delete",
                    tag_id,
                    payload,
                    owner_id=owner_id,
                    key=idempotency_key,
                    now=now,
                )
                if adopted is not None:
                    return adopted
                tag = self._repo.get_tag_for_owner(tag_id, owner_id=owner_id)
                decision, deleted = self._rust.decide_delete_tag(
                    tag, payload, owner_id=owner_id, now=now
                )
                if decision.refusal is not None:
                    command.reject(decision.refusal)
                    refusal = decision.refusal
                else:
                    assert deleted is not None
                    self._repo.save_tag(deleted.tag)
                    for task in deleted.affected:
                        self._repo.save(task)
                    changes: list[dict[str, Any]] = [
                        {
                            "operation": "tombstone",
                            "entity_type": "tag",
                            "record_key": [owner_id, tag_id],
                        },
                        *[
                            {
                                "operation": "upsert",
                                "entity_type": "task",
                                "record_key": [owner_id, task.id],
                                "value": encode_task(task),
                            }
                            for task in deleted.affected
                        ],
                    ]
                    command.accept(
                        changes,
                        result=deleted.tag.model_dump(mode="json"),
                        id_bindings=[
                            {
                                "entity_type": "tag",
                                "alias_id": TAG_DELETE_ALIAS,
                                "entity_id": tag_id,
                            }
                        ],
                    )
                    result = deleted.tag
        except SyncCommandError as exc:
            if exc.code == "IDEMPOTENCY_KEY_REUSED":
                raise ConflictError("Idempotency-Key", idempotency_key) from None
            raise
        if refusal is not None:
            raise _refused(refusal)
        assert result is not None
        return result

    def _adopt_tag_mutation(
        self,
        service: LegacyTagService,
        command: ReceiptCommand[Connection],
        operation: str,
        tag_id: str,
        payload: TagUpdateRequest | ExpectedRevisionRequest,
        *,
        owner_id: str,
        key: str,
        now: datetime,
    ) -> TagDocument | None:
        old = self._repo.get_idempotency(owner_id=owner_id, key=key)
        if old is None:
            return None
        legacy_command = f"{operation}_tag:{tag_id}"
        service._idempotency_record(
            owner_id=owner_id,
            key=key,
            command=legacy_command,
            request_hash=service._request_hash(legacy_command, payload),
        )
        try:
            snapshot = TagDocument.model_validate(old.response_body)
        except TypeError, ValueError:
            raise SyncCommandError("COMMAND_INTEGRITY") from None
        if (
            snapshot.owner_id != owner_id
            or snapshot.id != old.resource_id
            or snapshot.id != tag_id
        ):
            raise SyncCommandError("COMMAND_INTEGRITY")
        try:
            current = self._repo.get_tag_for_owner(tag_id, owner_id=owner_id)
        except NotFoundError:
            current = None
        fresh = old.created_at > now - IDEMPOTENCY_RETENTION
        if not fresh and current is None:
            raise IdempotencyReceiptUnavailableError()
        changed = fresh and (current is None or current.revision < snapshot.revision)
        result = service._tag_result(old, owner_id=owner_id) if fresh else current
        assert result is not None
        alias = TAG_UPDATE_ALIAS if operation == "update" else TAG_DELETE_ALIAS
        changes: list[dict[str, Any]] = (
            [
                (
                    {
                        "operation": "tombstone",
                        "entity_type": "tag",
                        "record_key": [owner_id, tag_id],
                    }
                    if operation == "delete"
                    else {
                        "operation": "upsert",
                        "entity_type": "tag",
                        "record_key": [owner_id, tag_id],
                        "value": encode_tag(result),
                    }
                )
            ]
            if changed
            else []
        )
        command.accept(
            changes,
            result=(
                result.model_dump(mode="json")
                if fresh and operation == "update"
                else None
            ),
            id_bindings=[
                {"entity_type": "tag", "alias_id": alias, "entity_id": tag_id}
            ],
        )
        return result

    def _delete_replay(
        self, command: ReceiptCommand[Connection], tag_id: str, owner_id: str
    ) -> TagDocument:
        replay = command.replay
        assert replay is not None
        if replay["outcome"] == "rejected":
            if command.replay_refusal is None:
                raise SyncCommandError("COMMAND_INTEGRITY")
            raise _refused(command.replay_refusal)
        # The tombstone redacts its response at commit. Resolve the retained ID.
        binding = next(
            (
                row
                for row in replay["id_bindings"]
                if row.get("entity_type") == "tag"
                and row.get("alias_id") == TAG_DELETE_ALIAS
            ),
            None,
        )
        if binding is None or binding.get("entity_id") != tag_id:
            raise SyncCommandError("COMMAND_INTEGRITY")
        try:
            return self._repo.get_tag_for_owner(tag_id, owner_id=owner_id)
        except NotFoundError:
            raise IdempotencyReceiptUnavailableError() from None

    def _update_replay(
        self,
        command: ReceiptCommand[Connection],
        tag_id: str,
        owner_id: str,
        payload: TagUpdateRequest,
    ) -> TagDocument:
        replay = command.replay
        assert replay is not None
        if replay["outcome"] == "rejected":
            if command.replay_refusal is None:
                raise SyncCommandError("COMMAND_INTEGRITY")
            raise _refused(
                command.replay_refusal,
                attempted_name=(
                    display_tag_name(payload.name) if payload.name is not None else None
                ),
            )
        if replay["result"] is not None:
            try:
                tag = TagDocument.model_validate(replay["result"])
            except TypeError, ValueError:
                raise SyncCommandError("COMMAND_INTEGRITY") from None
            if tag.owner_id != owner_id or tag.id != tag_id:
                raise SyncCommandError("COMMAND_INTEGRITY")
            if tag.id != self._bound_id(replay, "tag", TAG_UPDATE_ALIAS):
                raise SyncCommandError("COMMAND_INTEGRITY")
            return tag
        binding = next(
            (
                row
                for row in replay["id_bindings"]
                if row.get("entity_type") == "tag"
                and row.get("alias_id") == TAG_UPDATE_ALIAS
            ),
            None,
        )
        if binding is None or binding.get("entity_id") != tag_id:
            raise SyncCommandError("COMMAND_INTEGRITY")
        try:
            return self._repo.get_tag_for_owner(tag_id, owner_id=owner_id)
        except NotFoundError:
            raise IdempotencyReceiptUnavailableError() from None

    def _update_miss(
        self,
        command: ReceiptCommand[Connection],
        tag_id: str,
        payload: TagUpdateRequest,
        *,
        owner_id: str,
        now: datetime,
    ) -> TagDocument | DomainRefusal:
        tag = self._repo.get_tag_for_owner(tag_id, owner_id=owner_id)
        decision, updated = self._rust.decide_update_tag(
            tag, payload, owner_id=owner_id, now=now
        )
        if decision.refusal is not None:
            command.reject(decision.refusal)
            return decision.refusal
        assert decision.change_set is not None and updated is not None
        self._repo.save_tag(updated)
        command.accept(
            decision.change_set["changes"],
            result=updated.model_dump(mode="json"),
            id_bindings=[
                {
                    "entity_type": "tag",
                    "alias_id": TAG_UPDATE_ALIAS,
                    "entity_id": tag_id,
                }
            ],
        )
        return updated

    def _purge_legacy_cache(self, owner_id: str, now: datetime) -> None:
        """Run old idempotency retention only after receipt finalization commits."""
        with owner_write_lock(self._repo, owner_id):
            self._repo.purge_expired_idempotency(owner_id=owner_id, now=now)

    def _replay(
        self,
        command: ReceiptCommand[Connection],
        service: LegacyTagService,
        payload: TagCreateRequest,
        owner_id: str,
        *,
        idempotency_key: str,
        now: datetime,
    ) -> tuple[TagDocument | None, DomainRefusal | None, bool]:
        replay = command.replay
        assert replay is not None
        if replay["outcome"] == "rejected":
            if command.replay_refusal is None:
                raise SyncCommandError("COMMAND_INTEGRITY")
            return None, command.replay_refusal, False
        if replay["result"] is not None:
            try:
                tag = TagDocument.model_validate(replay["result"])
            except TypeError, ValueError:
                raise SyncCommandError("COMMAND_INTEGRITY") from None
            if tag.owner_id != owner_id:
                raise SyncCommandError("COMMAND_INTEGRITY")
            if tag.id != self._bound_id(replay, "tag", TAG_ALIAS):
                raise SyncCommandError("COMMAND_INTEGRITY")
            return tag, None, False
        bindings = replay["id_bindings"]
        binding = next(
            (
                row
                for row in bindings
                if row.get("entity_type") == "tag" and row.get("alias_id") == TAG_ALIAS
            ),
            None,
        )
        if binding is None:
            raise SyncCommandError("COMMAND_INTEGRITY")
        old = self._repo.get_idempotency(owner_id=owner_id, key=idempotency_key)
        if (
            not replay["result_redacted"]
            and old is not None
            and old.created_at > now - IDEMPOTENCY_RETENTION
        ):
            if (
                old.command != "create_tag"
                or old.request_hash != service._request_hash("create_tag", payload)
                or old.resource_id != binding["entity_id"]
            ):
                raise SyncCommandError("COMMAND_INTEGRITY")
            try:
                snapshot = TagDocument.model_validate(old.response_body)
            except TypeError, ValueError:
                raise SyncCommandError("COMMAND_INTEGRITY") from None
            if snapshot.id != old.resource_id or snapshot.owner_id != owner_id:
                raise SyncCommandError("COMMAND_INTEGRITY")
            return snapshot, None, False
        try:
            current = self._repo.get_tag_for_owner(
                binding["entity_id"], owner_id=owner_id
            )
        except NotFoundError:
            return None, None, True
        return current, None, False

    def _accept_miss(
        self,
        service: LegacyTagService,
        command: ReceiptCommand[Connection],
        payload: TagCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
    ) -> tuple[TagDocument | None, DomainRefusal | None, bool]:
        repo = self._repo
        old = repo.get_idempotency(owner_id=owner_id, key=idempotency_key)
        if old is not None:
            # This check preserves the pre-migration command/body conflict rule.
            record = service._idempotency_record(
                owner_id=owner_id,
                key=idempotency_key,
                command="create_tag",
                request_hash=request_hash,
            )
            assert record is not None
            expired = record.created_at <= now - IDEMPOTENCY_RETENTION
            current: TagDocument | None
            if expired:
                try:
                    current = repo.get_tag_for_owner(
                        record.resource_id, owner_id=owner_id
                    )
                except NotFoundError:
                    command.accept([], id_bindings=[self._binding(record.resource_id)])
                    return None, None, True
                command.accept(
                    [],
                    id_bindings=[self._binding(record.resource_id)],
                )
                return current, None, False
            snapshot = TagDocument.model_validate(record.response_body)
            if snapshot.id != record.resource_id or snapshot.owner_id != owner_id:
                raise SyncCommandError("COMMAND_INTEGRITY")
            try:
                current = repo.get_tag_for_owner(snapshot.id, owner_id=owner_id)
            except NotFoundError:
                current = None
            result = service._tag_result(record, owner_id=owner_id)
            repaired = current is None or current.revision < snapshot.revision
            current_after = repo.get_tag_for_owner(snapshot.id, owner_id=owner_id)
            changes = (
                [
                    {
                        "operation": "upsert",
                        "entity_type": "tag",
                        "value": encode_tag(current_after),
                    }
                ]
                if repaired
                else []
            )
            command.accept(
                changes,
                id_bindings=[self._binding(snapshot.id)],
            )
            return result, None, False

        decision, tag = self._rust.decide_create_tag(
            payload,
            owner_id=owner_id,
            now=now,
            entity_id=tag_entity_id(owner_id, idempotency_key),
        )
        if decision.refusal is not None:
            command.reject(decision.refusal)
            return None, decision.refusal, False
        assert decision.change_set is not None and tag is not None
        service._store_idempotency(
            owner_id=owner_id,
            key=idempotency_key,
            command="create_tag",
            request_hash=request_hash,
            resource_id=tag.id,
            response=tag,
        )
        repo.create_tag(tag)
        command.accept(
            decision.change_set["changes"],
            result=tag.model_dump(mode="json"),
            id_bindings=[self._binding(tag.id)],
        )
        return tag, None, False

    @staticmethod
    def _binding(entity_id: str) -> dict[str, str]:
        return {"entity_type": "tag", "alias_id": TAG_ALIAS, "entity_id": entity_id}
