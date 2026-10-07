"""Spec 021 PR-02: the tolerant project contract the Apple clients depend on.

Archive still clears memberships in this slice (it becomes lossless in PR-03),
so projects that keep members are seeded straight into the repository.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.modules.tasks import TaskRepository
from app.modules.tasks.domain import ProjectDocument

from .conftest import FrozenClock

STAMP = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
ARCHIVED_FIELDS = ("desired_outcome", "archived_at", "archived_before_lossless")


def _container(client: TestClient) -> Container:
    return client.app.state.container  # type: ignore[attr-defined]


def _owner(client: TestClient) -> str:
    return client.get("/api/account").json()["id"]


def _project(client: TestClient, name: str, key: str) -> dict[str, Any]:
    response = client.post(
        "/api/projects", headers={"Idempotency-Key": key}, json={"name": name}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _task(client: TestClient, key: str, **fields: Any) -> dict[str, Any]:
    response = client.post(
        "/api/tasks",
        headers={"Idempotency-Key": key},
        json={"title": f"Task {key}", **fields},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _seed_archive(
    client: TestClient, project: dict[str, Any], **fields: Any
) -> dict[str, Any]:
    """Archive a project in the repository without touching its members."""

    repo = _container(client).task_service.task_repo
    stored = repo.get_project_for_owner(project["id"], owner_id=_owner(client))
    repo.save_project(
        stored.model_copy(
            update={"state": "archived", "revision": stored.revision + 1, **fields}
        )
    )
    return client.get(f"/api/projects/{project['id']}").json()


def _archive(client: TestClient, project: dict[str, Any], key: str) -> Any:
    return client.post(
        f"/api/projects/{project['id']}/archive",
        headers={"Idempotency-Key": key},
        json={"expected_revision": project["revision"]},
    )


def _unarchive(client: TestClient, project_id: str, revision: int, key: str) -> Any:
    return client.post(
        f"/api/projects/{project_id}/unarchive",
        headers={"Idempotency-Key": key},
        json={"expected_revision": revision},
    )


def _patch_task(
    client: TestClient, task: dict[str, Any], key: str, **fields: Any
) -> Any:
    return client.patch(
        f"/api/tasks/{task['id']}",
        headers={"Idempotency-Key": key},
        json={"title": "Renamed", "expected_revision": task["revision"], **fields},
    )


# --- 021-FR-025: PATCH accepts a carried archived membership -----------------


@pytest.mark.parametrize(
    ("row", "expected_status"),
    [
        ("omitted", 200),
        ("same-archived", 200),
        ("different-archived", 400),
        ("null", 200),
        ("active", 200),
    ],
)
def test_021_FR_025_patch_task_project_membership_table(
    api_client: TestClient, row: str, expected_status: int
) -> None:
    """The tolerant PATCH table of http.md section 5."""

    current = _project(api_client, "Current", "fr025-current")
    other = _project(api_client, "Other", "fr025-other")
    active = _project(api_client, "Active", "fr025-active")
    task = _task(api_client, "fr025-task", project_id=current["id"])
    _seed_archive(api_client, current)
    _seed_archive(api_client, other)

    changes: dict[str, Any] = {
        "omitted": {},
        "same-archived": {"project_id": current["id"]},
        "different-archived": {"project_id": other["id"]},
        "null": {"project_id": None},
        "active": {"project_id": active["id"]},
    }[row]
    response = _patch_task(api_client, task, f"fr025-patch-{row}", **changes)

    assert response.status_code == expected_status, response.text
    if expected_status == 400:
        assert response.json()["message"] == "Task project must be active."
    else:
        expected_project = {
            "omitted": current["id"],
            "same-archived": current["id"],
            "null": None,
            "active": active["id"],
        }[row]
        assert response.json()["project_id"] == expected_project


def test_021_FR_025_create_and_smart_add_into_archived_project_stay_rejected(
    api_client: TestClient,
) -> None:
    """Only an existing membership is tolerated, never a new one."""

    archived = _seed_archive(api_client, _project(api_client, "Old", "fr025-old"))

    created = api_client.post(
        "/api/tasks",
        headers={"Idempotency-Key": "fr025-create"},
        json={"title": "New", "project_id": archived["id"]},
    )
    smart = api_client.post(
        "/api/tasks/smart-add",
        headers={"Idempotency-Key": "fr025-smart"},
        json={"title": "New", "project": {"id": archived["id"]}},
    )

    assert created.status_code == smart.status_code == 400
    assert smart.json()["message"] == "Task project must be active."


# --- 021-FR-026: GET /projects?state= ---------------------------------------


def test_021_FR_026_list_projects_default_and_state_filter(
    api_client: TestClient,
) -> None:
    """The default list is unchanged; state selects active, archived or all."""

    _project(api_client, "beta", "fr026-beta")
    old = _project(api_client, "Alpha", "fr026-alpha")
    _project(api_client, "Gamma", "fr026-gamma")
    _task(api_client, "fr026-task", project_id=old["id"])
    archived = _seed_archive(api_client, old)

    def names(query: str) -> list[str]:
        response = api_client.get(f"/api/projects{query}")
        assert response.status_code == 200, response.text
        return [item["name"] for item in response.json()]

    assert names("") == names("?state=active") == ["beta", "Gamma"]
    assert names("?state=archived") == ["Alpha"]
    assert names("?state=all") == ["Alpha", "beta", "Gamma"]
    for item in api_client.get("/api/projects?state=all").json():
        assert all(field in item for field in ARCHIVED_FIELDS)
    assert archived["open_task_count"] == 1
    assert archived["state"] == "archived"


def test_021_FR_026_list_projects_rejects_a_bad_state(api_client: TestClient) -> None:
    """An unknown state is a 422, not an empty list."""

    assert api_client.get("/api/projects?state=bogus").status_code == 422


def test_021_FR_026_list_projects_state_is_owner_scoped(
    second_api_client: tuple[TestClient, TestClient],
) -> None:
    """A second owner's projects never appear; an owner with none gets []."""

    first, second = second_api_client
    assert second.get("/api/projects?state=all").json() == []
    mine = _seed_archive(first, _project(first, "Mine archived", "fr026-mine-a"))
    _project(first, "Mine active", "fr026-mine-b")
    theirs = _seed_archive(second, _project(second, "Theirs archived", "fr026-t-a"))
    _project(second, "Theirs active", "fr026-t-b")

    for state in ("archived", "all"):
        first_ids = {p["id"] for p in first.get(f"/api/projects?state={state}").json()}
        second_ids = {
            p["id"] for p in second.get(f"/api/projects?state={state}").json()
        }
        assert mine["id"] in first_ids and theirs["id"] not in first_ids
        assert theirs["id"] in second_ids and mine["id"] not in second_ids


def test_021_FR_026_list_counts_match_per_project_counts_in_one_task_load(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Open counts come from one pass over the owner's tasks."""

    service = _container(api_client).task_service
    projects = [_project(api_client, f"P{i}", f"fr026-count-{i}") for i in range(3)]
    for index, project in enumerate(projects):
        for n in range(index + 1):
            _task(api_client, f"fr026-count-{index}-{n}", project_id=project["id"])
    done = _task(api_client, "fr026-done", project_id=projects[0]["id"])
    api_client.post(
        f"/api/tasks/{done['id']}/transitions",
        headers={"Idempotency-Key": "fr026-done-complete"},
        json={"action": "complete", "expected_revision": done["revision"]},
    )
    _seed_archive(api_client, projects[2])
    owner = _owner(api_client)

    loads = 0
    original = service.task_repo.list_for_owner

    def counting(*args: Any, **kwargs: Any) -> Any:
        nonlocal loads
        loads += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(service.task_repo, "list_for_owner", counting)
    listed = api_client.get("/api/projects?state=all").json()

    assert loads == 1
    monkeypatch.undo()
    assert {p["id"]: p["open_task_count"] for p in listed} == {
        p["id"]: service.open_task_count_for_project(p["id"], owner_id=owner)
        for p in listed
    }
    assert {p["name"]: p["open_task_count"] for p in listed} == {
        "P0": 1,
        "P1": 2,
        "P2": 3,
    }


# --- 021-FR-026: unarchive ---------------------------------------------------


def test_021_FR_026_unarchive_reopens_the_project_and_changes_no_task(
    api_client: TestClient,
) -> None:
    """200 with state active, archived_at cleared, revision + 1, marker kept."""

    project = _project(api_client, "Reopen", "unarch-project")
    task = _task(api_client, "unarch-task", project_id=project["id"])
    archived = _seed_archive(
        api_client,
        project,
        archived_at=STAMP,
        archived_before_lossless=True,
    )

    response = _unarchive(api_client, archived["id"], archived["revision"], "unarch-1")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "active"
    assert body["archived_at"] is None
    assert body["revision"] == archived["revision"] + 1
    assert body["archived_before_lossless"] is True
    assert body["open_task_count"] == 1
    assert api_client.get(f"/api/tasks/{task['id']}").json() == task


def test_021_FR_026_unarchive_of_an_active_project_is_unchanged_even_if_stale(
    api_client: TestClient,
) -> None:
    """The already-active check comes before the revision check."""

    project = _project(api_client, "Active", "unarch-active")

    response = _unarchive(api_client, project["id"], project["revision"] + 7, "u-act")

    assert response.status_code == 200, response.text
    assert response.json() == project


def test_021_FR_026_unarchive_with_a_stale_revision_conflicts(
    api_client: TestClient,
) -> None:
    """An archived project with a stale expected_revision is a 409."""

    archived = _seed_archive(api_client, _project(api_client, "Stale", "unarch-stale"))

    response = _unarchive(api_client, archived["id"], archived["revision"] - 1, "u-s")

    assert response.status_code == 409
    assert api_client.get(f"/api/projects/{archived['id']}").json()["state"] == (
        "archived"
    )


def test_021_FR_026_unarchive_into_an_active_name_clash_conflicts(
    api_client: TestClient,
) -> None:
    """The 409 body is the one POST /projects returns for a duplicate name."""

    archived = _seed_archive(api_client, _project(api_client, "Same", "unarch-dup-a"))
    duplicate = api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "unarch-dup-b"},
        json={"name": "same"},
    )
    assert duplicate.status_code == 201

    response = _unarchive(api_client, archived["id"], archived["revision"], "u-dup")
    rejected = api_client.post(
        "/api/projects",
        headers={"Idempotency-Key": "unarch-dup-c"},
        json={"name": "Same"},
    )

    assert response.status_code == 409
    assert response.json()["message"] == rejected.json()["message"]
    assert response.json()["detail"] == rejected.json()["detail"]


def test_021_FR_026_unarchive_of_a_foreign_project_is_not_found(
    second_api_client: tuple[TestClient, TestClient],
) -> None:
    """Another owner's project is a 404, never a 403."""

    first, second = second_api_client
    theirs = _seed_archive(second, _project(second, "Theirs", "unarch-foreign"))

    response = _unarchive(first, theirs["id"], theirs["revision"], "u-foreign")

    assert response.status_code == 404
    assert second.get(f"/api/projects/{theirs['id']}").json()["state"] == "archived"


def test_021_FR_026_unarchive_replay_returns_the_stored_response(
    api_client: TestClient,
) -> None:
    """The same key replays; the project is not unarchived twice."""

    archived = _seed_archive(api_client, _project(api_client, "Replay", "unarch-rep"))
    first = _unarchive(api_client, archived["id"], archived["revision"], "u-replay")

    replay = _unarchive(api_client, archived["id"], archived["revision"], "u-replay")

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    stored = api_client.get(f"/api/projects/{archived['id']}").json()
    assert stored["revision"] == archived["revision"] + 1


def test_021_FR_026_unarchive_requires_a_key_and_a_valid_body(
    api_client: TestClient,
) -> None:
    """No Idempotency-Key is a 400; a bad body is a 422."""

    archived = _seed_archive(api_client, _project(api_client, "Body", "unarch-body"))
    url = f"/api/projects/{archived['id']}/unarchive"

    assert api_client.post(url, json={"expected_revision": 1}).status_code == 400
    for body in ({}, {"expected_revision": 0}, {"expected_revision": 1, "extra": 1}):
        response = api_client.post(url, headers={"Idempotency-Key": "u-422"}, json=body)
        assert response.status_code == 422, body


# --- 021-FR-027: archive still clears members and marks them -----------------


def test_021_FR_027_archive_clears_members_and_sets_the_marker(
    api_client: TestClient,
) -> None:
    """PR-02 keeps today's clearing; the marker records that it happened."""

    project = _project(api_client, "Clearing", "fr027-clear")
    task = _task(api_client, "fr027-task", project_id=project["id"])

    response = _archive(api_client, project, "fr027-archive")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "archived"
    assert body["archived_before_lossless"] is True
    assert body["archived_at"] is None
    assert api_client.get(f"/api/tasks/{task['id']}").json()["project_id"] is None


def test_021_FR_027_marker_survives_unarchive(api_client: TestClient) -> None:
    """Unarchive leaves archived_before_lossless as it was."""

    project = _project(api_client, "Marked", "fr027-marked")
    archived = _archive(api_client, project, "fr027-marked-archive").json()

    reopened = _unarchive(api_client, project["id"], archived["revision"], "fr027-un")

    assert reopened.status_code == 200
    assert reopened.json()["archived_before_lossless"] is True


@pytest.mark.parametrize(
    "seed",
    [
        {"archived_before_lossless": True},
        {"archived_before_lossless": False, "archived_at": STAMP},
    ],
    ids=["pre-feature", "stamped"],
)
def test_021_FR_027_repeat_archive_changes_only_revision_and_updated_at(
    api_client: TestClient, frozen_clock: FrozenClock, seed: dict[str, Any]
) -> None:
    """A repeat archive never stamps archived_at nor clears the marker."""

    project = _project(api_client, "Repeat", "fr027-repeat")
    task = _task(api_client, "fr027-repeat-task", project_id=project["id"])
    archived = _seed_archive(api_client, project, **seed)
    service = _container(api_client).task_service
    owner = _owner(api_client)
    before = service.get_project(project["id"], owner_id=owner)
    frozen_clock.advance(timedelta(hours=1))

    response = _archive(api_client, archived, "fr027-repeat-archive")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision"] == archived["revision"] + 1
    assert body["archived_at"] == archived["archived_at"]
    assert body["archived_before_lossless"] == archived["archived_before_lossless"]
    assert body["open_task_count"] == archived["open_task_count"] == 1
    assert api_client.get(f"/api/tasks/{task['id']}").json() == task
    stored = service.get_project(project["id"], owner_id=owner)
    assert stored.updated_at == frozen_clock.now
    assert stored.updated_at != before.updated_at


def test_021_FR_027_startup_step_marks_only_archives_without_archived_at(
    data_dir: Path,
) -> None:
    """_mark_detached_archives is silent, narrow and idempotent."""

    repo = TaskRepository(data_dir)
    base = ProjectDocument(
        id="project_a",
        owner_id="owner",
        name="A",
        normalized_name="a",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        updated_at=datetime(2026, 9, 2, tzinfo=UTC),
        revision=3,
    )
    seeded = {
        "legacy": base.model_copy(update={"id": "p_legacy", "state": "archived"}),
        "stamped": base.model_copy(
            update={
                "id": "p_stamped",
                "normalized_name": "b",
                "state": "archived",
                "archived_at": datetime(2026, 9, 3, tzinfo=UTC),
            }
        ),
        "active": base.model_copy(update={"id": "p_active", "normalized_name": "c"}),
    }
    for project in seeded.values():
        repo.create_project(project)

    for _ in range(2):  # a second pass changes nothing
        repo._mark_detached_archives()
        marked = {
            key: repo.get_project_for_owner(project.id, owner_id="owner")
            for key, project in seeded.items()
        }
        assert marked["legacy"].archived_before_lossless is True
        assert marked["stamped"].archived_before_lossless is False
        assert marked["active"].archived_before_lossless is False
        for key, project in seeded.items():
            assert marked[key].revision == 3
            assert marked[key].updated_at == base.updated_at
            assert marked[key].state == project.state


def test_021_FR_027_every_start_runs_the_startup_step(data_dir: Path) -> None:
    """Opening the repository again marks archives written without archived_at."""

    repo = TaskRepository(data_dir)
    project = ProjectDocument(
        id="project_legacy",
        owner_id="owner",
        name="Legacy",
        normalized_name="legacy",
        state="archived",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    repo.create_project(project)

    restarted = TaskRepository(data_dir)

    stored = restarted.get_project_for_owner(project.id, owner_id="owner")
    assert stored.archived_before_lossless is True
