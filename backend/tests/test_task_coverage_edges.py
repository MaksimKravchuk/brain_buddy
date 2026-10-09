"""Branch-coverage edge legs for owner-scoped Tasks commands.

Targeted error/edge arms the happy-path task tests skip: listing with the
completed/cancelled inclusion flags, referencing an archived project or deleted
tag, and a stale-revision update conflict.
"""

from __future__ import annotations

import base64
import json

import allure
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


def _create(api_client, title: str, key: str, **more) -> dict:
    response = api_client.post(
        "/api/tasks",
        headers={"Idempotency-Key": key},
        json={"title": title, "state": "next", **more},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _close(api_client, task: dict, action: str, key: str) -> None:
    response = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": key},
        json={"action": action, "expected_revision": task["revision"]},
    )
    assert response.status_code == 200, response.text


def test_026_FR_024_one_list_can_include_its_completed_and_cancelled_tasks(
    api_client,
) -> None:
    """The closed-task flags widen a single-list listing, each on its own."""
    open_task = _create(api_client, "Still open", "edge-list-open")
    completed = _create(api_client, "Done", "edge-list-done")
    cancelled = _create(api_client, "Dropped", "edge-list-dropped")
    _close(api_client, completed, "complete", "edge-list-complete")
    _close(api_client, cancelled, "cancel", "edge-list-cancel")

    def titles(**flags: bool) -> set[str]:
        listed = api_client.get("/api/tasks", params={"state": "next", **flags})
        assert listed.status_code == 200, listed.text
        return {item["title"] for item in listed.json()["items"]}

    with allure.step("the list alone holds only the open task"):
        only_open = titles()
        allure.attach(
            str(sorted(only_open)), name="titles", attachment_type="text/plain"
        )
        assert only_open == {"Still open"}
    with allure.step("each flag adds just its own closed tasks"):
        with_done = titles(include_completed=True)
        with_dropped = titles(include_cancelled=True)
        allure.attach(
            str([sorted(with_done), sorted(with_dropped)]),
            name="titles",
            attachment_type="text/plain",
        )
        assert with_done == {"Still open", "Done"}
        assert with_dropped == {"Still open", "Dropped"}
    with allure.step("both flags add both"):
        everything = titles(include_completed=True, include_cancelled=True)
        allure.attach(
            str(sorted(everything)), name="titles", attachment_type="text/plain"
        )
        assert everything == {"Still open", "Done", "Dropped"}
    assert open_task["state"] == "next"


@pytest.mark.parametrize(
    "last",
    [[], "not-a-list", [None], [1.5], [["nested"]]],
    ids=["empty", "scalar", "null", "float", "nested"],
)
def test_026_FR_024_a_cursor_with_a_malformed_position_is_a_validation_error(
    api_client, last
) -> None:
    """A cursor whose filters match but whose position is unusable is a 400."""
    _create(api_client, "First", "edge-cursor-1")
    _create(api_client, "Second", "edge-cursor-2")
    page = api_client.get("/api/tasks", params={"limit": 1})
    assert page.status_code == 200, page.text
    cursor = page.json()["next_cursor"]
    assert cursor is not None
    payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    with allure.step("rewrite the position inside a genuine cursor"):
        payload["last"] = last
        forged = (
            base64.urlsafe_b64encode(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            )
            .decode()
            .rstrip("=")
        )
        allure.attach(json.dumps(payload), name="payload", attachment_type="text/plain")
    with allure.step("the forged cursor is refused with a client error"):
        refused = api_client.get("/api/tasks", params={"limit": 1, "cursor": forged})
        allure.attach(refused.text, name="response", attachment_type="text/plain")
        assert refused.status_code == 400, refused.text
