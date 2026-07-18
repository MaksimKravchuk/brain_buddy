"""Acceptance coverage for native task detail, lifecycle, and filtering flows."""

from __future__ import annotations


def _create_task(api_client, title: str, *, key: str, **payload):
    response = api_client.post(
        "/api/tasks",
        headers={"Idempotency-Key": key},
        json={"title": title, **payload},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _transition(api_client, task, *, key: str, action: str, **payload):
    response = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": key},
        json={"action": action, "expected_revision": task["revision"], **payload},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_priority_waiting_detail_fields_search_dates_and_sort_persist(api_client) -> None:
    project = api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "detail-project"},
        json={"name": "Client Alpha"},
    ).json()
    tag = api_client.post(
        "/api/tags",
        headers={"Idempotency-Key": "detail-tag"},
        json={"name": "calls"},
    ).json()

    task = _create_task(
        api_client,
        "Call Ada about launch",
        key="detail-create",
        details="Original notes",
        priority="high",
        due_date="2026-08-01",
        project_id=project["id"],
        tag_ids=[tag["id"]],
    )
    assert task["priority"] == "high"

    updated = api_client.patch(
        f"/api/tasks/{task['id']}",
        headers={"Idempotency-Key": "detail-update"},
        json={
            "details": "Updated searchable notes",
            "priority": "low",
            "due_date": "2026-08-02",
            "expected_revision": task["revision"],
        },
    )
    assert updated.status_code == 200, updated.text
    task = updated.json()
    assert task["details"] == "Updated searchable notes"
    assert task["priority"] == "low"
    assert task["due_date"] == "2026-08-02"

    waiting = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": "detail-to-waiting"},
        json={
            "action": "move",
            "to_state": "waiting",
            "waiting_for": "  Ada  ",
            "expected_revision": task["revision"],
        },
    )
    assert waiting.status_code == 200, waiting.text
    task = waiting.json()
    assert task["waiting_for"] == "Ada"
    assert task["waiting_since"]

    waiting_since = task["waiting_since"]
    patched_waiting = api_client.patch(
        f"/api/tasks/{task['id']}",
        headers={"Idempotency-Key": "detail-waiting-for-edit"},
        json={"waiting_for": "Ada via email", "expected_revision": task["revision"]},
    )
    assert patched_waiting.status_code == 200, patched_waiting.text
    task = patched_waiting.json()
    assert task["waiting_for"] == "Ada via email"
    assert task["waiting_since"] == waiting_since

    assert api_client.get("/api/tasks", params={"q": "searchable"}).json()["items"][0]["id"] == task["id"]
    assert api_client.get("/api/tasks", params={"due_after": "2026-08-01"}).json()["items"][0]["id"] == task["id"]
    assert api_client.get("/api/tasks", params={"priority": "low"}).json()["items"][0]["id"] == task["id"]

    _create_task(api_client, "Medium task", key="detail-medium", priority="medium")
    sorted_titles = [
        item["title"]
        for item in api_client.get("/api/tasks", params={"sort": "priority"}).json()["items"]
    ]
    assert sorted_titles[:2] == ["Medium task", "Call Ada about launch"]

    reloaded = api_client.get(f"/api/tasks/{task['id']}")
    assert reloaded.status_code == 200
    assert reloaded.json()["priority"] == "low"
    assert reloaded.json()["waiting_for"] == "Ada via email"


def test_lifecycle_matrix_rejects_same_state_and_forbidden_terminal_commands(api_client) -> None:
    task = _create_task(api_client, "Lifecycle", key="lifecycle-create", state="next")

    same_state = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": "same-state-move"},
        json={"action": "move", "to_state": "next", "expected_revision": task["revision"]},
    )
    assert same_state.status_code == 400
    assert "different open destination" in same_state.json()["message"]

    completed = _transition(api_client, task, key="lifecycle-complete", action="complete")
    for action, payload in (
        ("complete", {}),
        ("cancel", {}),
        ("move", {"to_state": "inbox"}),
    ):
        rejected = api_client.post(
            f"/api/tasks/{task['id']}/transitions",
            headers={"Idempotency-Key": f"terminal-{action}"},
            json={"action": action, "expected_revision": completed["revision"], **payload},
        )
        assert rejected.status_code == 400

    reopened = api_client.post(
        f"/api/tasks/{task['id']}/transitions",
        headers={"Idempotency-Key": "explicit-reopen"},
        json={"action": "reopen", "to_state": "inbox", "expected_revision": completed["revision"]},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["state"] == "inbox"


def test_subtask_and_comment_detail_commands_persist(api_client) -> None:
    task = _create_task(api_client, "Nested detail", key="nested-create")

    subtask = api_client.post(
        f"/api/tasks/{task['id']}/subtasks",
        headers={"Idempotency-Key": "nested-subtask"},
        json={"title": "Draft outline"},
    ).json()
    edited_subtask = api_client.patch(
        f"/api/tasks/{task['id']}/subtasks/{subtask['id']}",
        headers={"Idempotency-Key": "nested-subtask-edit"},
        json={"title": "Draft final outline", "expected_revision": subtask["revision"]},
    )
    assert edited_subtask.status_code == 200, edited_subtask.text
    subtask = edited_subtask.json()

    completed_subtask = api_client.post(
        f"/api/tasks/{task['id']}/subtasks/{subtask['id']}/transitions",
        headers={"Idempotency-Key": "nested-subtask-complete"},
        json={"action": "complete", "expected_revision": subtask["revision"]},
    )
    assert completed_subtask.status_code == 200, completed_subtask.text
    assert completed_subtask.json()["state"] == "completed"

    comment = api_client.post(
        f"/api/tasks/{task['id']}/comments",
        headers={"Idempotency-Key": "nested-comment"},
        json={"body": "Initial note"},
    ).json()
    edited_comment = api_client.patch(
        f"/api/tasks/{task['id']}/comments/{comment['id']}",
        headers={"Idempotency-Key": "nested-comment-edit"},
        json={"body": "Edited note", "expected_revision": comment["revision"]},
    )
    assert edited_comment.status_code == 200, edited_comment.text
    assert edited_comment.json()["edited_at"]

    detail = api_client.get(f"/api/tasks/{task['id']}").json()
    assert detail["subtasks"] == [completed_subtask.json()]
    assert detail["comments"][0]["body"] == "Edited note"
    assert detail["comments"][0]["edited_at"]


def test_subtask_comment_idempotency_and_transition_edges(api_client) -> None:
    task = _create_task(api_client, "Nested edge detail", key="nested-edge-create")

    subtask = api_client.post(
        f"/api/tasks/{task['id']}/subtasks",
        headers={"Idempotency-Key": "nested-edge-subtask"},
        json={"title": "Collect examples"},
    ).json()
    edit_payload = {"title": "Collect final examples", "expected_revision": subtask["revision"]}
    edited = api_client.patch(
        f"/api/tasks/{task['id']}/subtasks/{subtask['id']}",
        headers={"Idempotency-Key": "nested-edge-subtask-edit"},
        json=edit_payload,
    )
    assert edited.status_code == 200, edited.text
    replayed_edit = api_client.patch(
        f"/api/tasks/{task['id']}/subtasks/{subtask['id']}",
        headers={"Idempotency-Key": "nested-edge-subtask-edit"},
        json=edit_payload,
    )
    assert replayed_edit.status_code == 200, replayed_edit.text
    assert replayed_edit.json()["revision"] == edited.json()["revision"]

    untouched_title = api_client.patch(
        f"/api/tasks/{task['id']}/subtasks/{subtask['id']}",
        headers={"Idempotency-Key": "nested-edge-subtask-noop"},
        json={"expected_revision": edited.json()["revision"]},
    )
    assert untouched_title.status_code == 200, untouched_title.text
    assert untouched_title.json()["title"] == "Collect final examples"

    transition_payload = {
        "action": "complete",
        "expected_revision": untouched_title.json()["revision"],
    }
    completed = api_client.post(
        f"/api/tasks/{task['id']}/subtasks/{subtask['id']}/transitions",
        headers={"Idempotency-Key": "nested-edge-subtask-complete"},
        json=transition_payload,
    )
    assert completed.status_code == 200, completed.text
    replayed_transition = api_client.post(
        f"/api/tasks/{task['id']}/subtasks/{subtask['id']}/transitions",
        headers={"Idempotency-Key": "nested-edge-subtask-complete"},
        json=transition_payload,
    )
    assert replayed_transition.status_code == 200, replayed_transition.text
    assert replayed_transition.json()["revision"] == completed.json()["revision"]
    same_state = api_client.post(
        f"/api/tasks/{task['id']}/subtasks/{subtask['id']}/transitions",
        headers={"Idempotency-Key": "nested-edge-subtask-same-state"},
        json={"action": "complete", "expected_revision": completed.json()["revision"]},
    )
    assert same_state.status_code == 400

    cancelled_subtask = api_client.post(
        f"/api/tasks/{task['id']}/subtasks",
        headers={"Idempotency-Key": "nested-edge-cancel-subtask"},
        json={"title": "Discarded branch"},
    ).json()
    cancelled = api_client.post(
        f"/api/tasks/{task['id']}/subtasks/{cancelled_subtask['id']}/transitions",
        headers={"Idempotency-Key": "nested-edge-subtask-cancel"},
        json={"action": "cancel", "expected_revision": cancelled_subtask["revision"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    reopened = api_client.post(
        f"/api/tasks/{task['id']}/subtasks/{cancelled_subtask['id']}/transitions",
        headers={"Idempotency-Key": "nested-edge-subtask-reopen"},
        json={"action": "reopen", "expected_revision": cancelled.json()["revision"]},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["state"] == "open"

    comment = api_client.post(
        f"/api/tasks/{task['id']}/comments",
        headers={"Idempotency-Key": "nested-edge-comment"},
        json={"body": "Initial edge note"},
    ).json()
    comment_payload = {"body": "Edited edge note", "expected_revision": comment["revision"]}
    edited_comment = api_client.patch(
        f"/api/tasks/{task['id']}/comments/{comment['id']}",
        headers={"Idempotency-Key": "nested-edge-comment-edit"},
        json=comment_payload,
    )
    assert edited_comment.status_code == 200, edited_comment.text
    replayed_comment = api_client.patch(
        f"/api/tasks/{task['id']}/comments/{comment['id']}",
        headers={"Idempotency-Key": "nested-edge-comment-edit"},
        json=comment_payload,
    )
    assert replayed_comment.status_code == 200, replayed_comment.text
    assert replayed_comment.json()["revision"] == edited_comment.json()["revision"]


def test_task_query_and_update_validation_edges(api_client) -> None:
    _create_task(
        api_client,
        "Alpha due edge",
        key="edge-alpha-due",
        state="next",
        due_date="2026-09-02",
        priority="low",
    )
    undated = _create_task(
        api_client,
        "Beta undated edge",
        key="edge-beta-undated",
        state="next",
        priority="high",
    )

    conflicting_dates = api_client.get(
        "/api/tasks",
        params={"due_before": "2026-09-03", "due_after": "2026-09-01"},
    )
    assert conflicting_dates.status_code == 400
    duplicate_priority = api_client.get(
        "/api/tasks",
        params=[("priority", "low"), ("priority", "low")],
    )
    assert duplicate_priority.status_code == 400

    due_before = api_client.get("/api/tasks", params={"due_before": "2026-09-03"})
    assert due_before.status_code == 200, due_before.text
    assert [item["title"] for item in due_before.json()["items"]] == ["Alpha due edge"]
    title_sorted = api_client.get("/api/tasks", params={"sort": "title"})
    assert title_sorted.status_code == 200, title_sorted.text
    assert [item["title"] for item in title_sorted.json()["items"]] == [
        "Alpha due edge",
        "Beta undated edge",
    ]

    rejected_null_priority = api_client.patch(
        f"/api/tasks/{undated['id']}",
        headers={"Idempotency-Key": "edge-null-priority"},
        json={"priority": None, "expected_revision": undated["revision"]},
    )
    assert rejected_null_priority.status_code == 400


def test_project_archive_clears_assignments_from_all_lifecycle_states(api_client) -> None:
    project = api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "archive-all-project"},
        json={"name": "Archive me"},
    ).json()
    open_task = _create_task(api_client, "Open", key="archive-open", project_id=project["id"])
    done = _create_task(api_client, "Done", key="archive-done", project_id=project["id"])
    done = _transition(api_client, done, key="archive-done-complete", action="complete")
    cancelled = _create_task(api_client, "Cancelled", key="archive-cancelled", project_id=project["id"])
    cancelled = _transition(api_client, cancelled, key="archive-cancelled-cancel", action="cancel")

    archived = api_client.post(
        f"/api/projects/{project['id']}/archive",
        headers={"Idempotency-Key": "archive-all"},
        json={"expected_revision": project["revision"]},
    )
    assert archived.status_code == 200, archived.text

    for task in (open_task, done, cancelled):
        assert api_client.get(f"/api/tasks/{task['id']}").json()["project_id"] is None
