"""Immutable server receipt identity and terminal outcome in the Tasks unit.

026-FR-005/006/011/012: authorization and stable lookup precede mutable
execution validation. This dark port does not register a route or switch a writer.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection
from typing import Any, Protocol
from uuid import UUID, uuid5

from app.core.logging import get_correlation_id
from app.exceptions import BrainBuddyError
from app.modules.tasks.jobs.execution import current_execution, current_writer_origin
from app.modules.tasks.rust_adapter import DomainRefusal, RustCore
from app.utils.idempotency import idempotency_key_digest

from .change_log import AtomicChangeLog, ChangeLog, encode
from .unit_of_work import OwnerUnitOfWork

# Fixed versioned server namespace: owner/key identifies one effect across all
# legacy transports. Route/type/body are fingerprint checks, never namespaces.
_NAMESPACE = UUID("31c380f3-e0d0-5f21-9a66-069ef5bfc026")
STABLE_REPLAY_BYTES = 16 * 1024 * 1024


class StorageRow(Protocol):
    """Named SQL-row access, without a portable SQL connection facade."""

    def __getitem__(self, key: str) -> Any: ...


class SyncCommandError(BrainBuddyError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ScopeAuthority:
    """Current trusted admission, returned under the lock by Identity/control.

    Returning this object asserts current owner/session or bound worker access;
    its IDs alone are not authentication. Restore reconciliation must finish
    before an authority implementation can return admission_open=True.
    """

    owner_id: str
    server_generation: str
    feed_generation: str
    access_generation: str
    storage_epoch: str
    admission_open: bool = True


@dataclass(frozen=True, slots=True, init=False)
class CommandRequest:
    """An in-process trusted adapter request; wire cannot choose writer origin."""

    owner_id: str
    wire: bytes
    origin: str
    key_digest: str | None
    execution_identity: str | None

    @classmethod
    def _make(
        cls, owner: str, wire: bytes, origin: str, key_digest: str | None
    ) -> CommandRequest:
        request = object.__new__(cls)
        execution = current_execution()
        for name, value in (
            ("owner_id", owner),
            ("wire", wire),
            ("origin", origin),
            ("key_digest", key_digest),
            (
                "execution_identity",
                (
                    execution.effect_identity
                    if origin == "job" and execution is not None
                    else None
                ),
            ),
        ):
            object.__setattr__(request, name, value)
        return request

    @classmethod
    def device(cls, owner: str, wire: bytes) -> CommandRequest:
        """Only authenticated device ingress selects this constructor."""
        return cls._make(owner, bytes(wire), "device", None)

    @classmethod
    def legacy(
        cls,
        owner: str,
        key: str,
        command: str,
        body: dict[str, Any],
        *,
        entity_id: str | None = None,
        route: str | None = None,
    ) -> CommandRequest:
        if current_execution() is not None:
            raise SyncCommandError("TRUSTED_ORIGIN_REQUIRED")
        digest = idempotency_key_digest(key)
        command_id = str(uuid5(_NAMESPACE, encode(["legacy-v1", owner, digest])))
        wire = encode(
            {
                "command_id": command_id,
                "scope_id": owner,
                "type": command,
                "entity_id": entity_id,
                "route": route or command,
                "payload": body,
            }
        ).encode()
        return cls._make(owner, wire, str(current_writer_origin()), digest)

    @classmethod
    def job(
        cls,
        owner: str,
        command: str,
        body: dict[str, Any],
        *,
        effect_id: str | None = None,
    ) -> CommandRequest:
        execution = current_execution()
        if execution is None:
            raise SyncCommandError("TRUSTED_ORIGIN_REQUIRED")
        command_id = str(
            uuid5(
                _NAMESPACE,
                encode(["job-v1", owner, effect_id or execution.effect_identity]),
            )
        )
        wire = encode(
            {
                "command_id": command_id,
                "scope_id": owner,
                "type": command,
                "payload": body,
            }
        ).encode()
        return cls._make(owner, wire, "job", None)


type Authority[ConnectionT] = Callable[[OwnerUnitOfWork[ConnectionT]], ScopeAuthority]


class CommandUnits[ConnectionT](Protocol):
    def begin(
        self, owner_id: str
    ) -> AbstractContextManager[OwnerUnitOfWork[ConnectionT]]: ...


class CommandReceipts[ConnectionT](ABC):
    def __init__(
        self, core: RustCore, change_log: AtomicChangeLog[ConnectionT]
    ) -> None:
        self._core = core
        self.change_log = change_log

    def _scope(
        self, unit: OwnerUnitOfWork[ConnectionT], authorize: Authority[ConnectionT]
    ) -> ScopeAuthority:
        current = authorize(unit)
        if current.owner_id != unit.owner_id or not current.admission_open:
            raise SyncCommandError("RESOURCE_NOT_FOUND")
        if not all(
            (
                current.server_generation,
                current.feed_generation,
                current.access_generation,
                current.storage_epoch,
            )
        ):
            raise SyncCommandError("RESET_REQUIRED")
        scope = self._scope_row(unit)
        if scope is None:
            self._insert_scope(unit, current)
        elif not scope["admission_open"] or any(
            scope[field] != getattr(current, field)
            for field in ("server_generation", "access_generation", "storage_epoch")
        ):
            raise SyncCommandError("RESET_REQUIRED")
        return current

    @abstractmethod
    def _scope_row(self, unit: OwnerUnitOfWork[ConnectionT]) -> StorageRow | None:
        raise NotImplementedError

    @abstractmethod
    def _insert_scope(
        self, unit: OwnerUnitOfWork[ConnectionT], current: ScopeAuthority
    ) -> None:
        raise NotImplementedError

    @contextmanager
    def command(
        self,
        uow: CommandUnits[ConnectionT],
        request: CommandRequest,
        authorize: Authority[ConnectionT],
        *,
        now: datetime,
    ) -> Iterator[ReceiptCommand[ConnectionT]]:
        """Yield a replay or unseen command. The caller validates/decides a miss.

        No current execution schema, size or epoch check is applied to replay.
        Device ingress must check active epoch *only* on a miss. A known command
        from a closed epoch still needs current authority to read its outcome.
        """
        if now.tzinfo is None:
            raise SyncCommandError("INVALID_REQUEST")
        now = now.astimezone(UTC)
        with uow.begin(request.owner_id) as unit:
            execution = current_execution()
            if request.origin == "job":
                if (
                    execution is None
                    or execution.effect_identity != request.execution_identity
                ):
                    raise SyncCommandError("TRUSTED_ORIGIN_REQUIRED")
            elif execution is not None:
                raise SyncCommandError("TRUSTED_ORIGIN_REQUIRED")
            current = self._scope(unit, authorize)
            if len(request.wire) > STABLE_REPLAY_BYTES:
                raise SyncCommandError("INVALID_REQUEST")
            if request.origin == "device":
                wire = self._core.persistence("stable", request.wire)
            else:
                wire = self._core.persistence("canonical", request.wire)
            normalized = json.loads(wire)
            if "writer_origin" in normalized or "writer_origin" in normalized.get(
                "payload", {}
            ):
                raise SyncCommandError("TRUSTED_ORIGIN_REQUIRED")
            if normalized["scope_id"] != unit.owner_id:
                raise SyncCommandError("RESOURCE_NOT_FOUND")
            command_id = normalized["command_id"]
            canonical = self._core.persistence(
                "canonical",
                encode(
                    {"writer_origin": request.origin, "envelope": normalized}
                ).encode(),
            )
            digest = hashlib.sha256(canonical).hexdigest()
            if request.key_digest is not None:
                mapped_id = self._legacy_command_id(unit, request.key_digest)
                if mapped_id is not None:
                    command_id = mapped_id
            replay = self._lookup(
                unit, command_id, current, now=now, fingerprint=digest
            )
            command = ReceiptCommand(
                self, unit, command_id, digest, request, current, now, replay
            )
            yield command
            command._complete()
            # Identity/control live outside the Tasks file. Recheck immediately
            # before this unit can commit/respond; the job fence remains locked.
            self._scope(unit, authorize)

    @abstractmethod
    def _legacy_command_id(
        self, unit: OwnerUnitOfWork[ConnectionT], key_digest: str
    ) -> str | None:
        raise NotImplementedError

    def transactions(
        self,
        unit: OwnerUnitOfWork[ConnectionT],
        authorize: Authority[ConnectionT],
        *,
        after: str = "0",
        feed_generation: str,
    ) -> list[dict[str, Any]]:
        self._scope(unit, authorize)
        scope = self._scope_row(unit)
        if scope is None or scope["feed_generation"] != feed_generation:
            raise SyncCommandError("RESET_REQUIRED")
        result = self.change_log._transactions(unit, after=after)
        self._scope(unit, authorize)
        return result

    def lookup(
        self,
        unit: OwnerUnitOfWork[ConnectionT],
        command_id: str,
        authorize: Authority[ConnectionT],
        *,
        now: datetime,
    ) -> dict[str, Any] | None:
        if now.tzinfo is None:
            raise SyncCommandError("INVALID_REQUEST")
        now = now.astimezone(UTC)
        current = self._scope(unit, authorize)
        result = self._lookup(unit, command_id, current, now=now)
        self._scope(unit, authorize)
        return result

    def _lookup(
        self,
        unit: OwnerUnitOfWork[ConnectionT],
        command_id: str,
        current: ScopeAuthority,
        *,
        now: datetime,
        fingerprint: str | None = None,
    ) -> dict[str, Any] | None:
        row = self._receipt_row(unit, command_id)
        if row is None:
            return None
        if fingerprint is not None and fingerprint != row["fingerprint"]:
            raise SyncCommandError("IDEMPOTENCY_KEY_REUSED")
        body = json.loads(row["metadata"])
        had_result = body.pop("_had_result")
        expired = datetime.fromisoformat(row["expires_at"]) <= now
        body["result_redacted"] = (
            body["result_redacted"] or expired or (had_result and row["result"] is None)
        )
        body["result"] = (
            None
            if body["result_redacted"] or row["result"] is None
            else json.loads(row["result"])
        )
        return {**body, **self._common(current, now)}

    @abstractmethod
    def _receipt_row(
        self, unit: OwnerUnitOfWork[ConnectionT], command_id: str
    ) -> StorageRow | None:
        raise NotImplementedError

    @staticmethod
    def _common(current: ScopeAuthority, now: datetime) -> dict[str, Any]:
        return {
            "scope_id": current.owner_id,
            "server_generation": current.server_generation,
            "server_now": now.isoformat(),
            "correlation_id": get_correlation_id(),
        }

    def _insert(
        self, command: ReceiptCommand[ConnectionT], body: dict[str, Any]
    ) -> dict[str, Any]:
        wire: dict[str, Any] = {**body, **self._common(command.authority, command.now)}
        wire = json.loads(self._core.persistence("receipt", encode(wire).encode()))
        metadata = {
            k: v
            for k, v in wire.items()
            if k
            not in (
                "result",
                "scope_id",
                "server_generation",
                "server_now",
                "correlation_id",
            )
        }
        metadata["_had_result"] = wire["result"] is not None
        self._write_receipt(
            command,
            metadata,
            wire["result"],
            expires_at=command.now + timedelta(hours=24),
        )
        return wire

    @abstractmethod
    def _write_receipt(
        self,
        command: ReceiptCommand[ConnectionT],
        metadata: dict[str, Any],
        result: dict[str, Any] | None,
        *,
        expires_at: datetime,
    ) -> None:
        raise NotImplementedError


class ReceiptCommand[ConnectionT = Connection]:
    def __init__(
        self,
        store: CommandReceipts[ConnectionT],
        unit: OwnerUnitOfWork[ConnectionT],
        command_id: str,
        fingerprint: str,
        request: CommandRequest,
        authority: ScopeAuthority,
        now: datetime,
        replay: dict[str, Any] | None,
    ) -> None:
        self.store, self.unit, self.command_id = store, unit, command_id
        self.fingerprint, self.request, self.authority, self.now = (
            fingerprint,
            request,
            authority,
            now,
        )
        self.replay = replay
        self._terminal = replay is not None
        self._failed = False
        self._activity = unit.activity

    def _unseen(self) -> None:
        self.unit._require_open()
        if self._failed:
            raise SyncCommandError("COMMAND_FINALIZATION_FAILED")
        if self._terminal:
            raise SyncCommandError("COMMAND_ALREADY_TERMINAL")

    def accept(
        self,
        changes: Sequence[dict[str, Any]],
        *,
        result: dict[str, Any] | None = None,
        id_bindings: Sequence[dict[str, Any]] = (),
        result_versions: Sequence[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        """Commit Rust-decided facts plus an already-public application result.

        ``result`` is the existing public response DTO, never a storage document
        or exception. Feed changes separately use the core's Record.public().
        """
        self._unseen()
        # Poison before the first persistence operation. A caller catching a
        # codec/SQL failure cannot retry finalization and commit partial rows.
        self._failed = True
        sequence, versions = self.store.change_log.append(
            self.unit, self.command_id, changes, now=self.now
        )
        if sequence is None and self.unit.activity != self._activity:
            raise SyncCommandError("NOOP_HAS_WRITES")
        deleted = any(change["operation"] == "tombstone" for change in changes)
        body = {
            "command_id": self.command_id,
            "outcome": "accepted",
            "has_changes": sequence is not None,
            "commit_seq": sequence,
            "result_versions": versions or list(result_versions),
            "id_bindings": list(id_bindings),
            "result_redacted": deleted,
            "result": None if deleted else result,
            "error": None,
        }
        return self._finish(body)

    def reject(
        self,
        refusal: DomainRefusal,
        *,
        current_versions: Sequence[dict[str, Any]] = (),
    ) -> dict[str, Any]:
        """Store core enum diagnostics and adapter-loaded scope-bound versions.

        The caller loads any latest available record/edit versions under this
        unit, as it does the protected read set. They pass the existing typed
        receipt codec; no arbitrary exception message or detail map is accepted.
        """
        self._unseen()
        self._failed = True
        if self.unit.activity != self._activity:
            raise SyncCommandError("REJECTION_HAS_WRITES")
        error = json.loads(
            self.store._core.persistence(
                "refusal",
                encode(
                    {
                        "reason": refusal.reason,
                        "field": refusal.field,
                        "entity": refusal.entity,
                        "current_revision": (
                            str(refusal.current_revision)
                            if refusal.current_revision is not None
                            else None
                        ),
                    }
                ).encode(),
            )
        )
        if current_versions:
            error["details"]["current_versions"] = list(current_versions)
        return self._finish(
            {
                "command_id": self.command_id,
                "outcome": "rejected",
                "has_changes": False,
                "commit_seq": None,
                "result_versions": [],
                "id_bindings": [],
                "result_redacted": False,
                "result": None,
                "error": error,
            }
        )

    def _finish(self, body: dict[str, Any]) -> dict[str, Any]:
        result = self.store._insert(self, body)
        self._failed = False
        self._terminal = True
        self._activity = self.unit.activity
        return result

    def _complete(self) -> None:
        if self._failed:
            raise SyncCommandError("COMMAND_FINALIZATION_FAILED")
        if not self._terminal:
            raise SyncCommandError("COMMAND_UNFINISHED")
        if self.unit.activity != self._activity:
            raise SyncCommandError("WRITE_AFTER_TERMINAL")


class ReceiptStore(CommandReceipts[Connection]):
    """SQLite storage hooks; the shared policy stays in CommandReceipts."""

    def __init__(self, core: RustCore) -> None:
        """Use the container-owned core shared with Task/Review facades."""
        super().__init__(core, ChangeLog(core))

    def _scope_row(self, unit: OwnerUnitOfWork[Connection]) -> StorageRow | None:
        row: StorageRow | None = unit.connection.execute(
            "SELECT * FROM sync_scopes WHERE owner_id = ?", (unit.owner_id,)
        ).fetchone()
        return row

    def _insert_scope(
        self, unit: OwnerUnitOfWork[Connection], current: ScopeAuthority
    ) -> None:
        unit.connection.execute(
            "INSERT INTO sync_scopes VALUES (?,?,?,?,?,?,?)",
            (
                unit.owner_id,
                current.server_generation,
                current.feed_generation,
                current.access_generation,
                current.storage_epoch,
                1,
                "0",
            ),
        )

    def _legacy_command_id(
        self, unit: OwnerUnitOfWork[Connection], key_digest: str
    ) -> str | None:
        row = unit.connection.execute(
            "SELECT command_id FROM sync_legacy_keys WHERE owner_id = ? AND key_digest = ?",
            (unit.owner_id, key_digest),
        ).fetchone()
        return row["command_id"] if row is not None else None

    def _receipt_row(
        self, unit: OwnerUnitOfWork[Connection], command_id: str
    ) -> StorageRow | None:
        row: StorageRow | None = unit.connection.execute(
            "SELECT * FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
            (unit.owner_id, command_id),
        ).fetchone()
        return row

    def _write_receipt(
        self,
        command: ReceiptCommand[Connection],
        metadata: dict[str, Any],
        result: dict[str, Any] | None,
        *,
        expires_at: datetime,
    ) -> None:
        conn, owner = command.unit.connection, command.unit.owner_id
        conn.execute(
            "INSERT INTO sync_command_receipts VALUES (?,?,?,?,?,?,?,?)",
            (
                owner,
                command.command_id,
                command.request.origin,
                command.fingerprint,
                encode(metadata),
                encode(result) if result is not None else None,
                command.now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        if command.request.key_digest is not None:
            conn.execute(
                "INSERT INTO sync_legacy_keys VALUES (?,?,?)",
                (owner, command.request.key_digest, command.command_id),
            )
