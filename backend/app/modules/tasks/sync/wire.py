"""Wire shapes of the sync v1 endpoints (spec 026 PR-31, sync-v1 section 11).

Framework-free: the routes in ``app/api/sync.py`` only move bytes in and out.
Every receipt leaves through :func:`public_receipt`, so a stored private
document (Undo/park clock snapshots, progress fingerprints, consent audit
history) never reaches a device. A refused request is an :class:`ErrorBody`
carrying a code and the correlation ID, never the resource it asked for.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from sqlite3 import Connection
from typing import Any, Protocol

from app.core.logging import get_correlation_id

from .authority import not_found_response
from .receipts import STABLE_REPLAY_BYTES, ReceiptCommand, ScopeAuthority

PROTOCOL_VERSIONS = (1,)
RULE_VERSION = 1
PROJECTION_SCHEMA_VERSION = 1
SNAPSHOT_SUPPORTED = True
COMMAND_BYTES = 4 * 1024 * 1024
MIB = 1024 * 1024
_UNDO_DAYS = 7
COMMAND_TYPES = [
    "project.create",
    "project.update",
    "project.archive",
    "project.unarchive",
    "tag.create",
    "tag.update",
    "tag.delete",
    "task.create",
    "task.smart_add",
    "task.update",
    "task.tags",
    "task.transition",
    "subtask.create",
    "subtask.update",
    "subtask.transition",
    "comment.create",
    "comment.update",
    "review.decide",
    "review.undo_decision",
    "review.auto_park",
    "review.explainer_ack",
    "review.settings",
    "review.parks_ack",
    "review.session_start",
    "review.session_progress",
    "review.session_finish",
    "review.bulk_release",
    "review.bulk_undo",
    "review.consent_grant",
    "review.consent_revoke",
]
LIMITS = {
    "command_bytes": COMMAND_BYTES,
    "stable_replay_bytes": STABLE_REPLAY_BYTES,
    "inline_page_target_bytes": MIB,
    "inline_page_transactions": 100,
    "inline_page_hard_bytes": 4 * MIB,
    "transfer_page_bytes": MIB,
    "snapshot_ttl_seconds": 30 * 60,
    "transfer_ttl_seconds": 30 * 60,
    "feed_retention_days": 90,
    "bulk_release_items": 500,
    "park_ack_keys": 200,
}
# code -> (HTTP status, retryable, safe message)
_ERRORS = {
    "INVALID_REQUEST": (422, False, "The request is not valid."),
    "AUTH_REQUIRED": (401, False, "Authentication is required."),
    "ACCESS_DENIED": (403, False, "Sync is not enabled for this scope."),
    "RESOURCE_NOT_FOUND": (404, False, not_found_response()[1]["message"]),
    "EPOCH_CLOSED": (409, False, "The device epoch is closed."),
    "RESET_REQUIRED": (409, False, "The local base must be recovered."),
    "IDEMPOTENCY_KEY_REUSED": (409, False, "The command ID was used differently."),
    "DEPENDENCY_PENDING": (409, True, "A predecessor is not terminal yet."),
    "COMMAND_TOO_LARGE": (413, False, "The command exceeds the size limit."),
    "UPGRADE_REQUIRED": (426, False, "This client version cannot be served."),
    "RATE_LIMITED": (429, True, "Too many requests."),
    "TEMPORARILY_UNAVAILABLE": (503, True, "Try again shortly."),
}
ERROR_CODES = frozenset(_ERRORS)
_DETAILS = {
    "RESET_REQUIRED": {"reset_reason": "restore", "epoch_status": "active"},
    "EPOCH_CLOSED": {"epoch_status": "closed"},
}
_PRIVATE_KEYS = frozenset(
    {
        "owner_id",
        "schema_version",
        "clock_before",
        "applied_progress",
        "history",
        "task_before",
        "previous_state",
    }
)
_RECEIPT_KEYS = [
    "command_id",
    "outcome",
    "has_changes",
    "commit_seq",
    "result_versions",
    "id_bindings",
    "result_redacted",
    "result",
    "error",
    "scope_id",
    "server_generation",
    "server_now",
    "correlation_id",
]


class ProtocolFailure(Exception):
    """A refusal outside a receipt: it creates no command record."""

    def __init__(
        self,
        code: str,
        *,
        status: int | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.code, self.status = code, status
        self.details = {**_DETAILS.get(code, {}), **(details or {})}


def error_body(failure: ProtocolFailure) -> tuple[int, dict[str, Any]]:
    """``(status, ErrorBody)``; only the error and the correlation ID appear."""
    status, retryable, message = _ERRORS[failure.code]
    return failure.status or status, {
        "error": {
            "code": failure.code,
            "retryable": retryable,
            "message": message,
            "details": failure.details,
        },
        "correlation_id": get_correlation_id(),
    }


def strict_object(raw: bytes) -> dict[str, Any]:
    """Parse one JSON object; malformed JSON and duplicate keys are refused."""

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        if len({key for key, _ in pairs}) != len(pairs):
            raise ValueError("duplicate key")
        return dict(pairs)

    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except ValueError, RecursionError:
        value = None
    if not isinstance(value, dict):
        raise ProtocolFailure("INVALID_REQUEST", status=400)
    return value


def registration_request(raw: bytes) -> dict[str, Any]:
    """The ``DeviceRegistrationRequest`` body; unknown fields are refused."""
    body = strict_object(raw)
    ids = ("scope_id", "device_id", "device_epoch")
    if set(body) != {*ids, "protocol_version"} or not all(
        isinstance(body[name], str) and body[name] for name in ids
    ):
        raise ProtocolFailure("INVALID_REQUEST")
    version = body["protocol_version"]
    if type(version) is not int:
        raise ProtocolFailure("INVALID_REQUEST")
    if version not in PROTOCOL_VERSIONS:
        raise ProtocolFailure(
            "UPGRADE_REQUIRED", details={"reason": "protocol_version"}
        )
    return body


def snapshot_request(raw: bytes) -> dict[str, Any]:
    """The ``SnapshotRequest`` body; unknown fields and versions are refused."""
    body = strict_object(raw)
    if set(body) != {"scope_id", "projection_schema_version"} or not (
        isinstance(body["scope_id"], str) and body["scope_id"]
    ):
        raise ProtocolFailure("INVALID_REQUEST")
    version = body["projection_schema_version"]
    if type(version) not in (int, str):
        raise ProtocolFailure("INVALID_REQUEST")
    if str(version) != str(PROJECTION_SCHEMA_VERSION):
        raise ProtocolFailure(
            "UPGRADE_REQUIRED", details={"reason": "projection_schema_version"}
        )
    return body


@dataclass(frozen=True, slots=True)
class VersionPolicy:
    """Command versions this server executes and when each one retires.

    The current and previous published major are both listed (sync-v1 section
    9: at least 180 days from replacement); ``None`` means no deadline yet.
    """

    deadlines: Mapping[int, datetime | None] = field(default_factory=lambda: {1: None})

    def executes(self, version: int, now: datetime) -> bool:
        if version not in self.deadlines:
            return False
        deadline = self.deadlines[version]
        return deadline is None or now < deadline


class DeviceCommandExecutor(Protocol):
    """Decides an unseen, validated device command inside its receipt unit."""

    def supports(self, command_type: str) -> bool: ...

    def execute(
        self, command: ReceiptCommand[Connection], envelope: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Finish ``command`` through ``accept``/``reject``; return that receipt."""
        ...


class NoDeviceExecutor:
    """Executes nothing: every unseen command is UPGRADE_REQUIRED, replay works."""

    def supports(self, command_type: str) -> bool:
        return False

    def execute(
        self, command: ReceiptCommand[Connection], envelope: Mapping[str, Any]
    ) -> dict[str, Any]:
        raise ProtocolFailure("UPGRADE_REQUIRED")


def public_result(value: Any) -> Any:
    """A stored response document without its server-private members."""
    if isinstance(value, list):
        return [public_result(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {
        key: public_result(item)
        for key, item in value.items()
        if key not in _PRIVATE_KEYS and key != "undo"
    }
    parked = value.get("parked")
    if isinstance(parked, dict):
        out["parked"] = {k: parked[k] for k in ("at", "formulation_id") if k in parked}
    if "undo" in value and "decided_at" in value:
        decided = datetime.fromisoformat(value["decided_at"])
        out["undo_available_until"] = (
            None
            if value["undo"] is None
            else (decided + timedelta(days=_UNDO_DAYS)).isoformat()
        )
    return out


def public_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """The ``Receipt`` wire form of a stored or freshly written receipt."""
    wire = {key: receipt[key] for key in _RECEIPT_KEYS if key in receipt}
    wire["result"] = public_result(wire.get("result"))
    return wire


def common(current: ScopeAuthority, now: datetime) -> dict[str, Any]:
    return {
        "scope_id": current.owner_id,
        "server_generation": current.server_generation,
        "server_now": now.isoformat(),
        "correlation_id": get_correlation_id(),
    }


def lookup_body(
    command_id: str,
    receipt: Mapping[str, Any] | None,
    current: ScopeAuthority,
    now: datetime,
) -> dict[str, Any]:
    """Terminal receipt, or ``not_found`` (another scope's ID reads the same)."""
    if receipt is None:
        return {"status": "not_found", "command_id": command_id, **common(current, now)}
    return {
        "status": "terminal",
        "receipt": public_receipt(receipt),
        **common(current, now),
    }


def capabilities_body(  # noqa: PLR0913 - the one capabilities document
    current: ScopeAuthority,
    now: datetime,
    *,
    enabled: bool,
    policy: VersionPolicy,
    executor: DeviceCommandExecutor,
) -> dict[str, Any]:
    versions = [
        {
            "type": name,
            "supported_versions": (
                sorted(v for v in policy.deadlines if policy.executes(v, now))
                if executor.supports(name)
                else []
            ),
            "retire_at_by_version": (
                {
                    str(v): None if at is None else at.isoformat()
                    for v, at in policy.deadlines.items()
                }
                if executor.supports(name)
                else {}
            ),
        }
        for name in COMMAND_TYPES
    ]
    return {
        "protocol_versions": list(PROTOCOL_VERSIONS),
        "command_versions": versions,
        "rule_version": RULE_VERSION,
        "projection_schema_version": PROJECTION_SCHEMA_VERSION,
        "storage_epoch": current.storage_epoch,
        "feed_generation": current.feed_generation,
        "scope_enabled": enabled,
        "limits": LIMITS,
        "recovery": {
            "snapshot_supported": SNAPSHOT_SUPPORTED,
            "device_epoch_status": None,
        },
        **common(current, now),
    }
