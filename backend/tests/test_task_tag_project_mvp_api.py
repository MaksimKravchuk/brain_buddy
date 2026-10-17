"""MVP API contract tests for native task projects and first-class tags."""

from __future__ import annotations


def _post(client, path: str, key: str, payload: dict[str, object]):
    return client.post(path, headers={"Idempotency-Key": key}, json=payload)


def test_tags_are_first_class_task_assignments(api_client) -> None:
    tag = _post(api_client, "/api/tags", "tag-calls", {"name": "@Calls"})
    assert tag.status_code == 201, tag.text
    assert tag.json()["name"] == "Calls"
    assert tag.json()["open_task_count"] == 0

    task = _post(
        api_client,
        "/api/tasks",
        "task-with-tag",
        {"title": "Phone clinic", "state": "next", "tag_ids": [tag.json()["id"]]},
    )
    assert task.status_code == 201, task.text
    assert task.json()["tag_ids"] == [tag.json()["id"]]
    assert "context_ids" not in task.json()

    tagged = api_client.get("/api/tasks", params={"tag_id": tag.json()["id"]})
    assert tagged.status_code == 200, tagged.text
    assert [item["id"] for item in tagged.json()["items"]] == [task.json()["id"]]
    assert tagged.json()["counts_by_state"] == {
        "inbox": 0,
        "next": 1,
        "waiting": 0,
        "someday": 0,
    }

    tags = api_client.get("/api/tags")
    assert tags.status_code == 200, tags.text
    assert tags.json()[0]["open_task_count"] == 1

    retired_context_routes = api_client.get("/api/contexts")
    assert retired_context_routes.status_code == 404


def test_project_archive_keeps_and_tag_delete_unassigns_tasks(api_client) -> None:
    project = _post(
        api_client, "/api/projects", "project-home", {"name": "Home"}
    ).json()
    tag = _post(api_client, "/api/tags", "tag-home", {"name": "home"}).json()
    task = _post(
        api_client,
        "/api/tasks",
        "assigned-task",
        {"title": "Fix sink", "project_id": project["id"], "tag_ids": [tag["id"]]},
    ).json()

    archived = api_client.post(
        f"/api/projects/{project['id']}/archive",
        headers={"Idempotency-Key": "archive-home"},
        json={"expected_revision": project["revision"]},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["state"] == "archived"

    after_archive = api_client.get(f"/api/tasks/{task['id']}").json()
    assert after_archive["project_id"] == project["id"]
    assert after_archive["tag_ids"] == [tag["id"]]

    deleted = api_client.delete(
        f"/api/tags/{tag['id']}",
        params={"expected_revision": tag["revision"]},
        headers={"Idempotency-Key": "delete-home-tag"},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["state"] == "deleted"

    after_delete = api_client.get(f"/api/tasks/{task['id']}").json()
    assert after_delete["tag_ids"] == []
