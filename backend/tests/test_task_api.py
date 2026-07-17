"""API tests for the owner-scoped native GTD task foundation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from app.exceptions import ConflictError
from app.schemas.tasks import TaskCreateRequest, TaskUpdateRequest


def _create_task(api_client, title: str, *, key: str, **payload):
    response = api_client.post(
        "/api/tasks",
        headers={"Idempotency-Key": key},
        json={"title": title, **payload},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_task_mutation_requires_an_idempotency_key(api_client) -> None:
    response = api_client.post("/api/tasks", json={"title": "Plan appointment"})

    assert response.status_code == 400
    assert "Idempotency-Key header is required" in response.json()["message"]


def test_create_task_lists_it_in_its_open_state(api_client) -> None:
    created = _create_task(
        api_client, "Call the dentist", key="create-call-dentist", state="next"
    )

    listed = api_client.get("/api/tasks", params={"state": "next"})
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["counts_by_state"] == {
        "inbox": 0,
        "next": 1,
        "waiting": 0,
        "someday": 0,
    }
    assert [item["id"] for item in body["items"]] == [created["id"]]
    assert body["has_more"] is False
    assert body["next_cursor"] is None


def test_project_and_tag_creation_are_idempotent_and_listed_by_normalized_name(
    api_client,
) -> None:
    project_headers = {"Idempotency-Key": "create-project"}
    first_project = api_client.post(
        "/api/projects", headers=project_headers, json={"name": "Zoo"}
    )
    duplicate_project = api_client.post(
        "/api/projects", headers=project_headers, json={"name": "Zoo"}
    )
    assert first_project.status_code == duplicate_project.status_code == 201
    assert duplicate_project.json()["id"] == first_project.json()["id"]
    assert (
        api_client.post(
            "/api/projects", headers=project_headers, json={"name": "Other"}
        ).status_code
        == 409
    )
    second_project = api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "create-project-a"},
        json={"name": "alpha"},
    )
    assert second_project.status_code == 201

    tag_headers = {"Idempotency-Key": "create-tag"}
    first_tag = api_client.post(
        "/api/tags", headers=tag_headers, json={"name": "Calls"}
    )
    duplicate_tag = api_client.post(
        "/api/tags", headers=tag_headers, json={"name": "Calls"}
    )
    assert first_tag.status_code == duplicate_tag.status_code == 201
    assert duplicate_tag.json()["id"] == first_tag.json()["id"]
    assert (
        api_client.post(
            "/api/tags", headers=tag_headers, json={"name": "Home"}
        ).status_code
        == 409
    )

    projects = api_client.get("/api/projects")
    tags = api_client.get("/api/tags")
    assert projects.status_code == tags.status_code == 200
    assert [item["name"] for item in projects.json()] == ["alpha", "Zoo"]
    assert tags.json()[0]["name"] == "Calls"
    assert (
        api_client.get(f"/api/projects/{first_project.json()['id']}").status_code == 200
    )
    assert api_client.get(f"/api/tags/{first_tag.json()['id']}").status_code == 200


def test_task_rejects_unverifiable_provenance_and_nested_writes_are_idempotent(
    api_client,
) -> None:
    unverifiable_provenance = api_client.post(
        "/api/tasks",
        headers={"Idempotency-Key": "unverifiable-provenance"},
        json={"title": "Plan appointment", "source_capture_ids": ["capture_one"]},
    )
    assert unverifiable_provenance.status_code == 400

    task = _create_task(
        api_client,
        "Plan appointment",
        key="create-detail-task",
    )
    assert task["source_capture_ids"] == []

    subtask_headers = {"Idempotency-Key": "create-detail-subtask"}
    first_subtask = api_client.post(
        f"/api/tasks/{task['id']}/subtasks",
        headers=subtask_headers,
        json={"title": "Find a clinic"},
    )
    duplicate_subtask = api_client.post(
        f"/api/tasks/{task['id']}/subtasks",
        headers=subtask_headers,
        json={"title": "Find a clinic"},
    )
    assert first_subtask.status_code == duplicate_subtask.status_code == 201
    assert duplicate_subtask.json()["id"] == first_subtask.json()["id"]
    assert (
        api_client.post(
            f"/api/tasks/{task['id']}/subtasks",
            headers=subtask_headers,
            json={"title": "Call a clinic"},
        ).status_code
        == 409
    )

    comment_headers = {"Idempotency-Key": "create-detail-comment"}
    first_comment = api_client.post(
        f"/api/tasks/{task['id']}/comments",
        headers=comment_headers,
        json={"body": "Prefer a clinic close to home."},
    )
    duplicate_comment = api_client.post(
        f"/api/tasks/{task['id']}/comments",
        headers=comment_headers,
        json={"body": "Prefer a clinic close to home."},
    )
    assert first_comment.status_code == duplicate_comment.status_code == 201
    assert duplicate_comment.json()["id"] == first_comment.json()["id"]
    assert (
        api_client.post(
            f"/api/tasks/{task['id']}/comments",
            headers=comment_headers,
            json={"body": "Use the insurer portal."},
        ).status_code
        == 409
    )

    detail = api_client.get(f"/api/tasks/{task['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["subtasks"][0]["title"] == "Find a clinic"
    assert detail.json()["comments"][0]["body"] == "Prefer a clinic close to home."
    assert "agent_runs" not in detail.json()


def test_task_rejects_invalid_patch_and_waiting_invariants(api_client) -> None:
    invalid_waiting = api_client.post(
        "/api/tasks",
        headers={"Idempotency-Key": "invalid-waiting"},
        json={"title": "Await reply", "state": "waiting"},
    )
    assert invalid_waiting.status_code == 400

    task = _create_task(
        api_client,
        "Await reply",
        key="waiting-task",
        state="waiting",
        waiting_for="Dr. Smith",
    )
    assert task["waiting_for"] == "Dr. Smith"
    assert task["waiting_since"]

    null_title = api_client.patch(
        f"/api/tasks/{task['id']}",
        headers={"Idempotency-Key": "invalid-null-title"},
        json={"title": None, "expected_revision": 1},
    )
    assert null_title.status_code == 400
    assert api_client.get(f"/api/tasks/{task['id']}").json()["title"] == "Await reply"

    moved = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": "exit-waiting"},
        json={"action": "move", "to_state": "next", "expected_revision": 1},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["waiting_for"] is None
    assert moved.json()["waiting_since"] is None

    invalid_reopen = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": "complete-for-reopen"},
        json={"action": "complete", "expected_revision": 2},
    )
    assert invalid_reopen.status_code == 200
    assert (
        api_client.post(
            f"/api/tasks/{task['id']}/transitions",
            headers={"Idempotency-Key": "reopen-without-waiting-for"},
            json={"action": "reopen", "to_state": "waiting", "expected_revision": 3},
        ).status_code
        == 400
    )
    reopened = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": "reopen-waiting"},
        json={
            "action": "reopen",
            "to_state": "waiting",
            "waiting_for": "Dr. Smith",
            "expected_revision": 3,
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["waiting_for"] == "Dr. Smith"
    cancelled = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": "cancel-reopened-waiting"},
        json={"action": "cancel", "expected_revision": 4},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["waiting_for"] is None
    assert cancelled.json()["waiting_since"] is None

    completed_waiting = _create_task(
        api_client,
        "Await second reply",
        key="complete-waiting-task",
        state="waiting",
        waiting_for="Insurer",
    )
    completed = api_client.post(
        f"/api/tasks/{completed_waiting['id']}/transitions",
        headers={"Idempotency-Key": "complete-second-waiting-task"},
        json={"action": "complete", "expected_revision": 1},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["waiting_for"] is None
    assert completed.json()["waiting_since"] is None


def test_task_updates_transitions_and_rejects_stale_revisions(api_client) -> None:
    task = _create_task(api_client, "Book appointment", key="create-transition-task")

    updated = api_client.patch(
        f"/api/tasks/{task['id']}",
        headers={"Idempotency-Key": "edit-transition-task"},
        json={"details": "Use the insurer portal", "expected_revision": 1},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2

    completed = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": "complete-transition-task"},
        json={"action": "complete", "expected_revision": 2},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "completed"
    assert completed.json()["revision"] == 3

    duplicate_complete = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": "complete-transition-task"},
        json={"action": "complete", "expected_revision": 2},
    )
    assert duplicate_complete.status_code == 200, duplicate_complete.text
    assert duplicate_complete.json()["revision"] == 3

    stale = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": "stale-transition-task"},
        json={"action": "reopen", "to_state": "next", "expected_revision": 2},
    )
    assert stale.status_code == 409, stale.text
    assert api_client.get(f"/api/tasks/{task['id']}").json()["state"] == "completed"


def test_task_mutations_are_serialized_for_revision_and_idempotency(
    container, monkeypatch
) -> None:
    service = container.task_service
    repository = container.task_repo
    owner_id = "user_test_owner"
    task = service.create_task(
        TaskCreateRequest(title="Concurrent update"),
        owner_id=owner_id,
        idempotency_key="initial-task",
    )

    first_save_started = Event()
    second_task_read = Event()
    original_save = repository.save
    original_get_for_owner = repository.get_for_owner

    def signal_second_task_read(task_id: str, *, owner_id: str):
        task_document = original_get_for_owner(task_id, owner_id=owner_id)
        if first_save_started.is_set():
            second_task_read.set()
        return task_document

    def block_first_save(updated_task):
        if not first_save_started.is_set():
            first_save_started.set()
            second_task_read.wait(timeout=0.25)
        original_save(updated_task)

    monkeypatch.setattr(repository, "get_for_owner", signal_second_task_read)
    monkeypatch.setattr(repository, "save", block_first_save)

    def update(details: str, key: str):
        return service.update_task(
            task.id,
            TaskUpdateRequest(details=details, expected_revision=1),
            owner_id=owner_id,
            idempotency_key=key,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_update = executor.submit(update, "first", "first-update")
        assert first_save_started.wait(timeout=2)
        second_update = executor.submit(update, "second", "second-update")
        first_result = first_update.result(timeout=2)
        second_error = second_update.exception(timeout=2)

    assert first_result.revision == 2
    assert isinstance(second_error, ConflictError)

    first_create_started = Event()
    release_first_create = Event()
    original_create = repository.create

    def block_first_create(created_task):
        if not first_create_started.is_set():
            first_create_started.set()
            assert release_first_create.wait(timeout=2)
        original_create(created_task)

    monkeypatch.setattr(repository, "create", block_first_create)

    def create_with_same_key():
        return service.create_task(
            TaskCreateRequest(title="Idempotent create"),
            owner_id=owner_id,
            idempotency_key="concurrent-create",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_create = executor.submit(create_with_same_key)
        assert first_create_started.wait(timeout=2)
        second_create = executor.submit(create_with_same_key)
        release_first_create.set()
        first_created = first_create.result(timeout=2)
        second_created = second_create.result(timeout=2)

    assert first_created.id == second_created.id
    assert [
        item
        for item in repository.list_for_owner(owner_id=owner_id)
        if item.title == "Idempotent create"
    ] == [first_created]


def test_task_list_filters_counts_and_stable_cursor(api_client) -> None:
    project = api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "list-project"},
        json={"name": "Health"},
    ).json()
    tag = api_client.post(
        "/api/tags",
        headers={"Idempotency-Key": "list-tag"},
        json={"name": "phone"},
    ).json()
    first = _create_task(api_client, "First", key="page-first")
    second = _create_task(api_client, "Second", key="page-second")
    _create_task(
        api_client,
        "Assigned",
        key="page-assigned",
        project_id=project["id"],
        tag_ids=[tag["id"]],
    )
    completed = _create_task(api_client, "Done", key="page-completed")
    assert (
        api_client.post(
            f"/api/tasks/{completed['id']}/transitions",
            headers={"Idempotency-Key": "page-complete"},
            json={"action": "complete", "expected_revision": 1},
        ).status_code
        == 200
    )
    cancelled = _create_task(api_client, "Cancelled", key="page-cancelled")
    assert (
        api_client.post(
            f"/api/tasks/{cancelled['id']}/transitions",
            headers={"Idempotency-Key": "page-cancel"},
            json={"action": "cancel", "expected_revision": 1},
        ).status_code
        == 200
    )

    first_page = api_client.get("/api/tasks", params={"limit": 2})
    assert first_page.status_code == 200, first_page.text
    assert first_page.json()["has_more"] is True
    assert first_page.json()["counts_by_state"]["inbox"] == 3
    second_page = api_client.get(
        "/api/tasks", params={"limit": 2, "cursor": first_page.json()["next_cursor"]}
    )
    assert second_page.status_code == 200, second_page.text
    ids = [
        item["id"] for item in first_page.json()["items"] + second_page.json()["items"]
    ]
    assert first["id"] in ids and second["id"] in ids
    assert completed["id"] not in ids and cancelled["id"] not in ids
    assert (
        api_client.get(
            "/api/tasks",
            params={"state": "next", "cursor": first_page.json()["next_cursor"]},
        ).status_code
        == 400
    )

    assigned = api_client.get(
        "/api/tasks",
        params={"project_id": project["id"], "tag_id": tag["id"]},
    )
    assert assigned.status_code == 200
    assert [item["title"] for item in assigned.json()["items"]] == ["Assigned"]
    assert assigned.json()["counts_by_state"] == {
        "inbox": 1,
        "next": 0,
        "waiting": 0,
        "someday": 0,
    }
    assert (
        api_client.get(
            "/api/tasks",
            params={"project_id": project["id"], "unassigned_project": True},
        ).status_code
        == 400
    )
    assert completed["id"] in {
        item["id"]
        for item in api_client.get(
            "/api/tasks", params={"include_completed": True}
        ).json()["items"]
    }
    assert cancelled["id"] in {
        item["id"]
        for item in api_client.get("/api/tasks", params={"state": "cancelled"}).json()[
            "items"
        ]
    }


def test_task_endpoints_require_authentication(anonymous_api_client) -> None:
    for path in ("/api/tasks", "/api/projects", "/api/tags"):
        response = anonymous_api_client.get(path)
        assert response.status_code == 401
        assert response.headers.get("X-Correlation-ID")
    assert (
        anonymous_api_client.post(
            "/api/tasks",
            headers={"Idempotency-Key": "anonymous-task"},
            json={"title": "No session"},
        ).status_code
        == 401
    )


def test_task_project_tag_and_filters_hide_other_owners(second_api_client) -> None:
    client_a, client_b = second_api_client
    project = client_a.post(
        "/api/projects",
        headers={"Idempotency-Key": "owner-project"},
        json={"name": "Private"},
    ).json()
    tag = client_a.post(
        "/api/tags",
        headers={"Idempotency-Key": "owner-tag"},
        json={"name": "private"},
    ).json()
    task = _create_task(
        client_a,
        "Private task",
        key="owner-task",
        project_id=project["id"],
        tag_ids=[tag["id"]],
    )

    assert client_b.get("/api/tasks").json()["items"] == []
    for path in (
        f"/api/tasks/{task['id']}",
        f"/api/projects/{project['id']}",
        f"/api/tags/{tag['id']}",
    ):
        assert client_b.get(path).status_code == 404
    for params in (
        {"project_id": project["id"]},
        {"tag_id": tag["id"]},
    ):
        assert client_b.get("/api/tasks", params=params).status_code == 404
    assert (
        client_b.post(
            "/api/tasks",
            headers={"Idempotency-Key": "wrong-owner-project-assignment"},
            json={"title": "Nope", "project_id": project["id"]},
        ).status_code
        == 404
    )
    assert (
        client_b.post(
            "/api/tasks",
            headers={"Idempotency-Key": "wrong-owner-tag-assignment"},
            json={"title": "Nope", "tag_ids": [tag["id"]]},
        ).status_code
        == 404
    )
    assert (
        client_b.post(
            f"/api/tasks/{task['id']}/subtasks",
            headers={"Idempotency-Key": "wrong-owner-subtask"},
            json={"title": "Nope"},
        ).status_code
        == 404
    )
    assert (
        client_b.post(
            f"/api/tasks/{task['id']}/comments",
            headers={"Idempotency-Key": "wrong-owner-comment"},
            json={"body": "Nope"},
        ).status_code
        == 404
    )
