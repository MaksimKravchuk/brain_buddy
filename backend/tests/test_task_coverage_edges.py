"""Branch-coverage edge legs for owner-scoped Tasks commands.

Targeted error/edge arms the happy-path task tests skip: listing with the
completed/cancelled inclusion flags, referencing an archived project or deleted
tag, and a stale-revision update conflict.
"""

from __future__ import annotations

import pytest

from app.exceptions import ConflictError, ValidationFailure
from app.schemas.tasks import (
    ProjectCreateRequest,
    TagCreateRequest,
    TaskCreateRequest,
    TaskUpdateRequest,
)


def _svc(api_client):
    container = api_client.app.state.container
    owner_id = api_client.get("/api/auth/me").json()["id"]
    return container.task_service, container.task_repo, owner_id


def test_list_tasks_includes_completed_and_cancelled(api_client) -> None:
    listed = api_client.get(
        "/api/tasks",
        params={"include_completed": True, "include_cancelled": True},
    )
    assert listed.status_code == 200, listed.text


def test_create_task_rejects_an_archived_project_reference(api_client) -> None:
    service, repo, owner_id = _svc(api_client)
    project = service.create_project(
        ProjectCreateRequest(name="Archived Ref"),
        owner_id=owner_id,
        idempotency_key="edge-arch-project",
    )
    repo.save_project(
        repo.get_project_for_owner(project.id, owner_id=owner_id).model_copy(
            update={"state": "archived"}
        )
    )
    with pytest.raises(ValidationFailure):
        service.create_task(
            TaskCreateRequest(title="Refers archived", project_id=project.id),
            owner_id=owner_id,
            idempotency_key="edge-arch-task",
        )


def test_create_task_rejects_a_deleted_tag_reference(api_client) -> None:
    service, repo, owner_id = _svc(api_client)
    tag = service.create_tag(
        TagCreateRequest(name="deletedref"),
        owner_id=owner_id,
        idempotency_key="edge-del-tag",
    )
    repo.save_tag(
        repo.get_tag_for_owner(tag.id, owner_id=owner_id).model_copy(
            update={"state": "deleted"}
        )
    )
    with pytest.raises(ValidationFailure):
        service.create_task(
            TaskCreateRequest(title="Refers deleted tag", tag_ids=[tag.id]),
            owner_id=owner_id,
            idempotency_key="edge-del-task",
        )


def test_update_task_rejects_a_stale_revision(api_client) -> None:
    service, _repo, owner_id = _svc(api_client)
    task = service.create_task(
        TaskCreateRequest(title="Revision guard"),
        owner_id=owner_id,
        idempotency_key="edge-rev-task",
    )
    with pytest.raises(ConflictError):
        service.update_task(
            task.id,
            TaskUpdateRequest(title="Renamed", expected_revision=task.revision + 999),
            owner_id=owner_id,
            idempotency_key="edge-rev-update",
        )
