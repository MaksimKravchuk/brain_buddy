"""MVP API contract tests for native task projects and first-class tags."""

from __future__ import annotations

from pathlib import Path

from app.container import build_container
from app.core import get_config
from app.modules.tasks import TaskRepository
from app.utils.file_ops import write_json
from app.utils.time import utcnow


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


def test_project_archive_and_tag_delete_unassign_tasks_atomically(api_client) -> None:
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
    assert after_archive["project_id"] is None
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


def test_task_repository_migrates_existing_json_contexts_to_sqlite_tags(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    now = utcnow().isoformat().replace("+00:00", "Z")
    owner_id = "user_legacy"
    write_json(
        data_dir / "projects" / owner_id / "project_legacy.json",
        {
            "id": "project_legacy",
            "owner_id": owner_id,
            "name": "Legacy Project",
            "color": None,
            "state": "active",
            "linked_tree_ids": ["tree_should_not_migrate"],
            "created_at": now,
            "updated_at": now,
            "revision": 1,
            "schema_version": 1,
        },
    )
    write_json(
        data_dir / "contexts" / owner_id / "context_legacy.json",
        {
            "id": "context_legacy",
            "owner_id": owner_id,
            "name": "@Calls",
            "state": "active",
            "created_at": now,
            "updated_at": now,
            "revision": 1,
            "schema_version": 1,
        },
    )
    write_json(
        data_dir / "tasks" / owner_id / "task_legacy.json",
        {
            "id": "task_legacy",
            "owner_id": owner_id,
            "title": "Legacy task",
            "details": None,
            "state": "inbox",
            "project_id": "project_legacy",
            "context_ids": ["context_legacy"],
            "due_date": None,
            "waiting_for": None,
            "waiting_since": None,
            "order_key": 0,
            "source_capture_ids": [],
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "cancelled_at": None,
            "revision": 1,
            "schema_version": 1,
        },
    )

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    container = build_container(get_config())

    assert isinstance(container.task_repo, TaskRepository)
    assert container.task_repo.db_path.exists()
    migrated = container.task_service.get_task("task_legacy", owner_id=owner_id)
    assert migrated.tag_ids == ["context_legacy"]
    assert (
        container.task_service.get_tag("context_legacy", owner_id=owner_id).name
        == "Calls"
    )
    migrated_project = container.task_service.get_project(
        "project_legacy", owner_id=owner_id
    )
    assert "linked_tree_ids" not in migrated_project.model_dump()

    get_config.cache_clear()
