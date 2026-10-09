"""Typed facade over the PyO3 core bridge (spec 026, T004).

Only the completed ``bb-protocol`` command codec crosses the bridge today.
``TaskService`` does not call it: the existing Python rules stay the active
writer until decide/query are connected by a later slice, which adds methods to
:class:`RustCore` beside :meth:`RustCore.decode_command`.

Bridge failures arrive as ``bb_core.BridgeError(code, retryable, field)`` and
carry no payload text. They are translated here into the application's own
exceptions, so routes keep their HTTP mapping and nothing input-derived reaches
a log or a response.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Final, Self, TypeVar

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
