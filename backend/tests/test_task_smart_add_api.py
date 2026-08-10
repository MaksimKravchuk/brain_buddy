"""API tests for RTM-style Smart Add task classification."""

from __future__ import annotations


def _post(api_client, payload, key="smart-add-key"):
    return api_client.post(
        "/api/tasks/smart-add",
        headers={"Idempotency-Key": key},
        json=payload,
    )


def test_smart_add_creates_unknown_classifications_and_clean_task_atomically(
    api_client,
) -> None:
    api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "unknown-nonmatch-project"},
        json={"name": "Admin"},
    )
    api_client.post(
        "/api/tags",
        headers={"Idempotency-Key": "unknown-nonmatch-tag"},
        json={"name": "errands"},
    )

    response = _post(
        api_client,
        {
            "title": "Call supplier",
            "state": "next",
            "project": {"name": "Vendor launch"},
            "tags": [{"name": "calls"}, {"name": "vendor"}],
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["task"]["title"] == "Call supplier"
    assert body["task"]["state"] == "next"
    assert body["project"]["name"] == "Vendor launch"
    assert [item["name"] for item in body["tags"]] == ["calls", "vendor"]
    assert body["task"]["project_id"] == body["project"]["id"]
    assert body["task"]["tag_ids"] == [item["id"] for item in body["tags"]]
    assert body["created"] == {
        "project_id": body["project"]["id"],
        "tag_ids": [item["id"] for item in body["tags"]],
    }

    listed = api_client.get("/api/tasks", params={"state": "next"})
    assert [item["title"] for item in listed.json()["items"]] == ["Call supplier"]


def test_smart_add_resolves_existing_names_and_ids_and_deduplicates_tags(
    api_client,
) -> None:
    api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "existing-project-nonmatch"},
        json={"name": "Admin"},
    )
    project = api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "existing-project"},
        json={"name": "Launch v2"},
    ).json()
    api_client.post(
        "/api/tags",
        headers={"Idempotency-Key": "existing-tag-nonmatch"},
        json={"name": "Errands"},
    )
    tag = api_client.post(
        "/api/tags",
        headers={"Idempotency-Key": "existing-tag"},
        json={"name": "Deep Work"},
    ).json()

    response = _post(
        api_client,
        {
            "title": "Draft update",
            "project": {"name": " launch   V2 "},
            "tags": [{"id": tag["id"]}, {"name": "deep work"}, {"name": "Calls"}],
        },
        key="smart-add-existing",
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["project"]["id"] == project["id"]
    assert [item["name"] for item in body["tags"]] == ["Deep Work", "Calls"]
    assert body["created"] == {"project_id": None, "tag_ids": [body["tags"][1]["id"]]}


def test_smart_add_accepts_absent_classifications_and_project_ids(api_client) -> None:
    project = api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "id-project"},
        json={"name": "Admin"},
    ).json()

    unclassified = _post(api_client, {"title": "Plain capture"}, key="smart-add-plain")
    by_id = _post(
        api_client,
        {"title": "Project capture", "project": {"id": project["id"]}},
        key="smart-add-project-id",
    )

    assert unclassified.status_code == by_id.status_code == 201
    assert unclassified.json()["project"] is None
    assert unclassified.json()["tags"] == []
    assert by_id.json()["project"]["id"] == project["id"]
    assert by_id.json()["created"] == {"project_id": None, "tag_ids": []}


def test_smart_add_replays_composite_result_and_rejects_conflicting_key(
    api_client,
) -> None:
    payload = {
        "title": "Plan launch",
        "project": {"name": "Launch"},
        "tags": [{"name": "work"}],
    }

    first = _post(api_client, payload, key="smart-add-replay")
    replay = _post(api_client, payload, key="smart-add-replay")
    conflict = _post(
        api_client, {**payload, "title": "Plan something else"}, key="smart-add-replay"
    )

    assert first.status_code == replay.status_code == 201
    assert replay.json()["task"]["id"] == first.json()["task"]["id"]
    assert conflict.status_code == 409


def test_smart_add_validates_strict_refs_waiting_and_no_partial_writes(
    api_client,
) -> None:
    invalid_ref = _post(
        api_client,
        {"title": "Bad ref", "project": {"id": "p1", "name": "Project"}},
        key="bad-ref",
    )
    assert invalid_ref.status_code == 422

    invalid_waiting = _post(
        api_client,
        {"title": "Await reply", "state": "waiting", "tags": [{"name": "waiting"}]},
        key="bad-waiting",
    )
    assert invalid_waiting.status_code == 400
    assert api_client.get("/api/tags").json() == []
    assert api_client.get("/api/tasks").json()["items"] == []


def test_smart_add_rejects_inactive_project_and_tag_refs(api_client) -> None:
    project = api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "inactive-project"},
        json={"name": "Dormant"},
    ).json()
    tag = api_client.post(
        "/api/tags",
        headers={"Idempotency-Key": "inactive-tag"},
        json={"name": "stale"},
    ).json()
    assert (
        api_client.post(
            f"/api/projects/{project['id']}/archive",
            headers={"Idempotency-Key": "archive-inactive-project"},
            json={"expected_revision": project["revision"]},
        ).status_code
        == 200
    )
    assert (
        api_client.delete(
            f"/api/tags/{tag['id']}",
            params={"expected_revision": tag["revision"]},
            headers={"Idempotency-Key": "delete-inactive-tag"},
        ).status_code
        == 200
    )

    inactive_project = _post(
        api_client,
        {"title": "Bad project", "project": {"id": project["id"]}},
        key="bad-project-id",
    )
    inactive_tag = _post(
        api_client,
        {"title": "Bad tag", "tags": [{"id": tag["id"]}]},
        key="bad-tag-id",
    )
    inactive_project_name = _post(
        api_client,
        {"title": "Bad project name", "project": {"name": "Dormant"}},
        key="bad-project-name",
    )
    inactive_tag_name = _post(
        api_client,
        {"title": "Bad tag name", "tags": [{"name": "stale"}]},
        key="bad-tag-name",
    )

    assert inactive_project.status_code == 400
    assert inactive_tag.status_code == 400
    assert inactive_project_name.status_code == 400
    assert inactive_tag_name.status_code == 400


def test_literal_task_create_remains_unchanged(api_client) -> None:
    created = api_client.post(
        "/api/tasks",
        headers={"Idempotency-Key": "literal-create"},
        json={"title": "Call supplier #calls @Vendor"},
    )

    assert created.status_code == 201, created.text
    assert created.json()["title"] == "Call supplier #calls @Vendor"
    assert created.json()["project_id"] is None
    assert created.json()["tag_ids"] == []
    assert api_client.get("/api/projects").json() == []
    assert api_client.get("/api/tags").json() == []
