"""The create-tag portion of the legacy HTTP-to-receipt adapter."""

from __future__ import annotations

from uuid import UUID, uuid5

from app.modules.tasks.sync.receipts import CommandRequest
from app.schemas.tasks import TagCreateRequest
from app.utils.idempotency import idempotency_key_digest

TAG_ALIAS = "tag_pending"
_TAG_NAMESPACE = UUID("1aa8f7f3-fb9d-5fb3-901a-cbc027c731b1")


def tag_create_request(
    owner_id: str, key: str, payload: TagCreateRequest
) -> CommandRequest:
    """Keep owner/key as identity; command and normalized body are checks."""
    return CommandRequest.legacy(
        owner_id,
        key,
        "tag.create",
        {"command_type": "tag.create", "body": payload.model_dump(mode="json")},
        entity_id=TAG_ALIAS,
        route="create_tag",
    )


def tag_entity_id(owner_id: str, key: str) -> str:
    """Allocate the Rust-native tag ID deterministically from owner/key."""
    return f"tag_{uuid5(_TAG_NAMESPACE, f'{owner_id}:{idempotency_key_digest(key)}')}"
