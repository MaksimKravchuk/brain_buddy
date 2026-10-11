"""One legacy command family executed through the shared receipt boundary."""

from __future__ import annotations

from datetime import datetime
from sqlite3 import Connection
from typing import Protocol

from app.exceptions import (
    ConflictError,
    IdempotencyReceiptUnavailableError,
    NotFoundError,
)
from app.modules.tasks.domain import IdempotencyRecord, TagDocument
from app.modules.tasks.jobs.execution import owner_write_lock
from app.modules.tasks.repository import (
    IDEMPOTENCY_RETENTION,
    TaskRepository,
    display_tag_name,
)
from app.modules.tasks.rust_adapter import DomainRefusal
from app.modules.tasks.rust_task_facade import RustTaskFacade, _refused, encode_tag
from app.modules.tasks.sync.legacy_adapter import (
    TAG_ALIAS,
    tag_create_request,
    tag_entity_id,
)
from app.modules.tasks.sync.receipts import (
    Authority,
    CommandReceipts,
    ReceiptCommand,
    SyncCommandError,
)
from app.modules.tasks.sync.unit_of_work import TaskUnitOfWork
from app.schemas.tasks import TagCreateRequest


class LegacyTagService(Protocol):
    task_repo: TaskRepository

    def _request_hash(self, command: str, payload: TagCreateRequest) -> str: ...

    def _tag_result(
        self, record: IdempotencyRecord, *, owner_id: str
    ) -> TagDocument: ...

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
