"""Pure and structural idempotency mechanics shared by command services."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from pydantic import BaseModel

from app.exceptions import ConflictError


@dataclass(frozen=True)
class ReplayFingerprint:
    command: str
    request_hash: str


def idempotency_key_digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def request_fingerprint(command: str, payload: BaseModel) -> str:
    encoded = json.dumps(
        {
            "command": command,
            "body": payload.model_dump(mode="json"),
            "fields_set": sorted(payload.model_fields_set),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_matching_replay(
    replay: ReplayFingerprint,
    *,
    key: str,
    command: str,
    request_hash: str,
) -> None:
    if replay.command != command or replay.request_hash != request_hash:
        raise ConflictError("Idempotency-Key", key)


__all__ = [
    "ReplayFingerprint",
    "idempotency_key_digest",
    "request_fingerprint",
    "require_matching_replay",
]
