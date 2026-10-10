"""Typed facade over the PyO3 core bridge (spec 026, T004).

The ``bb-protocol`` command codec and, since T018, the shared rule dispatch
(:meth:`RustCore.decide`, :meth:`RustCore.query`) cross the bridge as owned JSON
bytes. ``TaskService`` and ``ReviewService`` reach them only through
``RustTaskFacade`` and ``RustReviewFacade`` while the ``rust_core_sync`` flag is
on; with it off the Python rules stay the writer.

Bridge failures arrive as ``bb_core.BridgeError(code, retryable, field)`` and
carry no payload text. They are translated here into the application's own
exceptions, so routes keep their HTTP mapping and nothing input-derived reaches
a log or a response.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Final, Self, TypeVar

import bb_core

from app.exceptions import BrainBuddyError, ValidationFailure

PROTOCOL_VERSION: Final[int] = bb_core.PROTOCOL_VERSION
# Bridge codes that describe the caller's input; everything else is a runtime
# condition (closed, cancelled, internal, unsupported build).
_VALIDATION_CODES: Final = frozenset({"INVALID_REQUEST"})

_T = TypeVar("_T")


class RustBridgeError(BrainBuddyError):
    """A bridge failure with no input meaning: closed, cancelled or internal."""

    def __init__(self, code: str, retryable: bool, field: str | None) -> None:
        super().__init__(f"The Rust core is unavailable ({code}).")
        self.code = code
        self.retryable = retryable
        self.field = field


def translate(error: bb_core.BridgeError) -> BrainBuddyError:
    """Map a bridge failure to the application's exception for it."""
    code, retryable, field = error.args
    if code in _VALIDATION_CODES:
        return ValidationFailure(
            "Command failed validation.", {"code": code, "field": field}
        )
    return RustBridgeError(code, retryable, field)


@dataclass(frozen=True, slots=True)
class DecodedCommand:
    """A command envelope decoded by the core; all values are Python-owned."""

    protocol_version: int
    command_id: str
    scope_id: str
    device_id: str
    local_sequence: str  # decimal string: counters can exceed exact JSON numbers
    command_type: str
    command_version: int
    entity_id: str
    # False for a well-formed command this build cannot execute (the stable
    # recovery form); the caller reports UPGRADE_REQUIRED and keeps the wire.
    executable: bool
    unsupported_reason: str | None
    wire: bytes


class RustCore:
    """One bridge runtime. Close it, or use it as a context manager."""

    def __init__(self, protocol_version: int = PROTOCOL_VERSION) -> None:
        self._runtime = self._call(bb_core.Runtime, protocol_version)

    @staticmethod
    def _call(function: Callable[..., _T], *args: object) -> _T:
        try:
            return function(*args)
        except bb_core.BridgeError as error:
            raise translate(error) from None

    @property
    def is_open(self) -> bool:
        return self._runtime.is_open

    def close(self) -> None:
        """Release the runtime. Idempotent; later calls raise ``RustBridgeError``."""
        self._runtime.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def decode_command(self, wire: bytes) -> DecodedCommand:
        """Decode and validate one command envelope (sync-v1 section 3)."""
        decoded = self._call(self._runtime.decode_command, wire)
        return DecodedCommand(
            protocol_version=decoded.protocol_version,
            command_id=decoded.command_id,
            scope_id=decoded.scope_id,
            device_id=decoded.device_id,
            local_sequence=decoded.local_sequence,
            command_type=decoded.command_type,
            command_version=decoded.command_version,
            entity_id=decoded.entity_id,
            executable=decoded.executable,
            unsupported_reason=decoded.unsupported_reason,
            wire=decoded.to_bytes(),
        )

    def decide(
        self,
        read_set: Mapping[str, Any],
        envelope: Mapping[str, Any],
        inputs: Mapping[str, Any],
        receipts: list[Mapping[str, Any]] | None = None,
    ) -> Decision:
        """Decide one command envelope against an owned read set.

        An expected domain refusal is returned as ``Decision.refusal``; only a
        bridge failure (closed, cancelled, internal, malformed input) raises.
        """
        out = self._call(
            self._runtime.decide,
            _encode(read_set),
            _encode(envelope),
            _encode(receipts or []),
            _encode(inputs),
        )
        body = json.loads(out)
        if body["status"] == "changed":
            return Decision(change_set=body["change_set"], refusal=None)
        return Decision(change_set=None, refusal=_refusal(body["error"]))

    def query(
        self,
        read_set: Mapping[str, Any],
        query: Mapping[str, Any],
        inputs: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Answer one typed query; a refusal raises ``ValidationFailure``."""
        out = self._call(
            self._runtime.query,
            _encode(read_set),
            _encode(query),
            _encode(inputs),
        )
        body = json.loads(out)
        if body["status"] != "answered":
            raise ValidationFailure(
                "Query refused.", {"reason": body["error"]["reason"]}
            )
        result: dict[str, Any] = body["result"]
        return result


def _encode(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()


@dataclass(frozen=True, slots=True)
class DomainRefusal:
    """A typed domain refusal; ``reason`` is a stable code, never input text."""

    reason: str
    field: str | None
    entity: tuple[str, list[str]] | None
    current_revision: int | None


@dataclass(frozen=True, slots=True)
class Decision:
    """Exactly one of a change set (plain JSON values) or a refusal."""

    change_set: dict[str, Any] | None
    refusal: DomainRefusal | None


def _refusal(error: Mapping[str, Any]) -> DomainRefusal:
    entity = error.get("entity")
    revision = error.get("current_revision")
    return DomainRefusal(
        reason=error["reason"],
        field=error.get("field"),
        entity=None if entity is None else (entity[0], list(entity[1])),
        current_revision=None if revision is None else int(revision),
    )
