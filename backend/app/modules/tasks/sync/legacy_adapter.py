"""The create-tag portion of the legacy HTTP-to-receipt adapter."""

from __future__ import annotations

from uuid import UUID, uuid5

from app.modules.tasks.sync.receipts import CommandRequest
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
from app.utils.idempotency import idempotency_key_digest

TAG_ALIAS = "tag_pending"
TAG_UPDATE_ALIAS = "tag_update"
TAG_DELETE_ALIAS = "tag_delete"
PROJECT_ALIAS = "project_pending"
PROJECT_UPDATE_ALIAS = "project_update"
PROJECT_ARCHIVE_ALIAS = "project_archive"
PROJECT_UNARCHIVE_ALIAS = "project_unarchive"
TASK_ALIAS = "task_pending"
TASK_UPDATE_ALIAS = "task_update"
TASK_TRANSITION_ALIAS = "task_transition"
_TAG_NAMESPACE = UUID("1aa8f7f3-fb9d-5fb3-901a-cbc027c731b1")
_PROJECT_NAMESPACE = UUID("dba0a1e4-1d74-5e11-a7d4-4d0c66a5d7c6")
_TASK_NAMESPACE = UUID("117241fd-9a2a-5eac-b7f3-026c0150da19")


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


def project_create_request(
    owner_id: str, key: str, payload: ProjectCreateRequest
) -> CommandRequest:
    return CommandRequest.legacy(
        owner_id,
        key,
        "project.create",
        {"command_type": "project.create", "body": payload.model_dump(mode="json")},
        entity_id=PROJECT_ALIAS,
        route="create_project",
    )


def project_entity_id(owner_id: str, key: str) -> str:
    return f"project_{uuid5(_PROJECT_NAMESPACE, f'{owner_id}:{idempotency_key_digest(key)}')}"


def task_create_request(
    owner_id: str, key: str, payload: TaskCreateRequest
) -> CommandRequest:
    return CommandRequest.legacy(
        owner_id,
        key,
        "task.create",
        {"command_type": "task.create", "body": payload.model_dump(mode="json")},
        entity_id=TASK_ALIAS,
        route="create_task",
    )


def task_entity_id(owner_id: str, key: str) -> str:
    return f"task_{uuid5(_TASK_NAMESPACE, f'{owner_id}:{idempotency_key_digest(key)}')}"


def task_update_request(
    owner_id: str, key: str, task_id: str, payload: TaskUpdateRequest
) -> CommandRequest:
    return CommandRequest.legacy(
        owner_id,
        key,
        "task.update",
        {"command_type": "task.update", "body": payload.model_dump(mode="json")},
        entity_id=task_id,
        route="update_task",
    )


def task_transition_request(
    owner_id: str, key: str, task_id: str, payload: TaskTransitionRequest
) -> CommandRequest:
    return CommandRequest.legacy(
        owner_id,
        key,
        "task.transition",
        {"command_type": "task.transition", "body": payload.model_dump(mode="json")},
        entity_id=task_id,
        route="transition_task",
    )


def project_update_request(
    owner_id: str, key: str, project_id: str, payload: ProjectUpdateRequest
) -> CommandRequest:
    return CommandRequest.legacy(
        owner_id,
        key,
        "project.update",
        {"command_type": "project.update", "body": payload.model_dump(mode="json")},
        entity_id=project_id,
        route="update_project",
    )


def project_archive_request(
    owner_id: str, key: str, project_id: str, payload: ExpectedRevisionRequest
) -> CommandRequest:
    return CommandRequest.legacy(
        owner_id,
        key,
        "project.archive",
        {"command_type": "project.archive", "body": payload.model_dump(mode="json")},
        entity_id=project_id,
        route="archive_project",
    )


def project_unarchive_request(
    owner_id: str, key: str, project_id: str, payload: ExpectedRevisionRequest
) -> CommandRequest:
    return CommandRequest.legacy(
        owner_id,
        key,
        "project.unarchive",
        {"command_type": "project.unarchive", "body": payload.model_dump(mode="json")},
        entity_id=project_id,
        route="unarchive_project",
    )


def tag_update_request(
    owner_id: str, key: str, tag_id: str, payload: TagUpdateRequest
) -> CommandRequest:
    return CommandRequest.legacy(
        owner_id,
        key,
        "tag.update",
        {"command_type": "tag.update", "body": payload.model_dump(mode="json")},
        entity_id=tag_id,
        route="update_tag",
    )


def tag_delete_request(
    owner_id: str, key: str, tag_id: str, payload: ExpectedRevisionRequest
) -> CommandRequest:
    return CommandRequest.legacy(
        owner_id,
        key,
        "tag.delete",
        {"command_type": "tag.delete", "body": payload.model_dump(mode="json")},
        entity_id=tag_id,
        route="delete_tag",
    )
