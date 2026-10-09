"""Spec 026 owner decision (2026-10-09): same-name Smart Add ties go to the oldest.

When several ACTIVE projects (or tags) share one normalized name, Smart Add
resolves to the oldest by ``(created_at, id)``, the order the Swift planner and
the Rust rule use. Legacy data can hold such namesakes because only the active
name is unique going forward. Each case seeds records whose creation order
differs from their id order, so a lowest-id or insertion-order pick fails.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import allure
import pytest

from app.exceptions import ValidationFailure
from app.modules.tasks import TaskRepository, TaskService
from app.modules.tasks.domain import ProjectDocument, TagDocument
from app.modules.tasks.repository import normalize_task_name
from app.schemas.tasks import SmartAddClassificationRef, SmartAddTaskCreateRequest

OWNER = "user_tiebreak"
EPOCH = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return EPOCH + timedelta(minutes=minutes)


def _evidence(name: str, payload: object) -> None:
    allure.attach(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        name=name,
        attachment_type=allure.attachment_type.JSON,
    )


def _project(project_id: str, minutes: int, archived: bool = False) -> ProjectDocument:
    return ProjectDocument(
        id=project_id,
        owner_id=OWNER,
        name="Launch",
        normalized_name=normalize_task_name("Launch"),
        state="archived" if archived else "active",
        created_at=_at(minutes),
        updated_at=_at(minutes),
    )


def _tag(tag_id: str, minutes: int, deleted: bool = False) -> TagDocument:
    return TagDocument(
        id=tag_id,
        owner_id=OWNER,
        name="focus",
        normalized_name=normalize_task_name("focus", strip_tag_prefix=True),
        state="deleted" if deleted else "active",
        created_at=_at(minutes),
        updated_at=_at(minutes),
    )


@pytest.fixture()
def repo(data_dir: Path) -> TaskRepository:
    return TaskRepository(data_dir)


@pytest.fixture()
def service(repo: TaskRepository) -> TaskService:
    return TaskService(repo)


def _smart_add(
    service: TaskService,
    key: str,
    *,
    project: str | None = None,
    tag: str | None = None,
) -> tuple[str | None, list[str]]:
    result = service.smart_add_task(
        SmartAddTaskCreateRequest(
            title="Plan",
            project=SmartAddClassificationRef(name=project) if project else None,
            tags=[SmartAddClassificationRef(name=tag)] if tag else [],
        ),
        owner_id=OWNER,
        idempotency_key=key,
    )
    return result.task.project_id, list(result.task.tag_ids)


def test_026_FR_002_smart_add_project_namesakes_resolve_to_the_oldest(
    repo: TaskRepository, service: TaskService
) -> None:
    """026-FR-002: the oldest active project wins, not the lowest id."""

    # Id order a < b < c; creation order b (oldest) < c < a (newest).
    seeded = {"project_a": 30, "project_b": 10, "project_c": 20}
    with allure.step("Seed three active namesakes whose creation order differs"):
        for project_id, minutes in seeded.items():
            repo.create_project(_project(project_id, minutes))
        _evidence("seeded created_at minutes", seeded)
    with allure.step("Smart Add by name resolves to the oldest, not the lowest id"):
        project_id, _ = _smart_add(service, "tie-project", project=" LAUNCH ")
        _evidence("resolved", {"project_id": project_id, "expected": "project_b"})
        assert project_id == "project_b"
    with allure.step("No namesake was created"):
        ids = sorted(p.id for p in repo.list_projects_for_owner(owner_id=OWNER))
        _evidence("project ids", ids)
        assert ids == ["project_a", "project_b", "project_c"]


def test_026_FR_002_smart_add_tag_namesakes_resolve_to_the_oldest(
    repo: TaskRepository, service: TaskService
) -> None:
    """026-FR-002: the oldest active tag wins, not the lowest id."""

    seeded = {"tag_a": 30, "tag_b": 10, "tag_c": 20}
    with allure.step("Seed three active namesakes whose creation order differs"):
        for tag_id, minutes in seeded.items():
            repo.create_tag(_tag(tag_id, minutes))
        _evidence("seeded created_at minutes", seeded)
    with allure.step("Smart Add by name resolves to the oldest, not the lowest id"):
        _, tag_ids = _smart_add(service, "tie-tag", tag="Focus")
        _evidence("resolved", {"tag_ids": tag_ids, "expected": ["tag_b"]})
        assert tag_ids == ["tag_b"]
    with allure.step("No namesake was created"):
        ids = sorted(t.id for t in repo.list_tags_for_owner(owner_id=OWNER))
        _evidence("tag ids", ids)
        assert ids == ["tag_a", "tag_b", "tag_c"]


def test_026_FR_002_equal_creation_instants_fall_back_to_the_lowest_id(
    repo: TaskRepository, service: TaskService
) -> None:
    """026-FR-002: ``(created_at, id)`` breaks a same-instant tie by id."""

    with allure.step("Seed namesakes created at one instant, highest id first"):
        for suffix in ("c", "a", "b"):
            repo.create_project(_project(f"project_{suffix}", 5))
            repo.create_tag(_tag(f"tag_{suffix}", 5))
        _evidence("seeded", {"created_at_minutes": 5, "suffixes": ["c", "a", "b"]})
    with allure.step("Smart Add picks the lowest id of the oldest instant"):
        project_id, tag_ids = _smart_add(
            service, "tie-equal", project="launch", tag="focus"
        )
        _evidence("resolved", {"project_id": project_id, "tag_ids": tag_ids})
        assert (project_id, tag_ids) == ("project_a", ["tag_a"])


def test_026_FR_002_an_older_inactive_namesake_does_not_block_an_active_one(
    repo: TaskRepository, service: TaskService
) -> None:
    """026-FR-002: only active records compete; an inactive one blocks alone."""

    with allure.step("Seed an older archived project beside a newer active one"):
        repo.create_project(_project("project_a", 1, archived=True))
        repo.create_project(_project("project_b", 9))
        repo.create_tag(_tag("tag_a", 1, deleted=True))
        repo.create_tag(_tag("tag_b", 9))
        _evidence("seeded", {"older": "inactive", "newer": "active"})
    with allure.step("The active namesake resolves even though it is newer"):
        project_id, tag_ids = _smart_add(
            service, "tie-active", project="Launch", tag="focus"
        )
        _evidence("resolved", {"project_id": project_id, "tag_ids": tag_ids})
        assert (project_id, tag_ids) == ("project_b", ["tag_b"])


def test_026_FR_002_only_inactive_namesakes_still_refuse_the_name(
    repo: TaskRepository, service: TaskService
) -> None:
    """026-FR-002: with no active namesake the inactive one refuses the name."""

    with allure.step("Seed only inactive namesakes"):
        repo.create_project(_project("project_a", 1, archived=True))
        repo.create_tag(_tag("tag_a", 1, deleted=True))
        _evidence("seeded", {"project": "archived", "tag": "deleted"})
    with allure.step("Project and tag names are refused, nothing is created"):
        with pytest.raises(ValidationFailure) as project_error:
            _smart_add(service, "tie-refuse-project", project="Launch")
        with pytest.raises(ValidationFailure) as tag_error:
            _smart_add(service, "tie-refuse-tag", tag="focus")
        _evidence(
            "refusals",
            {"project": str(project_error.value), "tag": str(tag_error.value)},
        )
        assert len(repo.list_projects_for_owner(owner_id=OWNER)) == 1
        assert len(repo.list_tags_for_owner(owner_id=OWNER)) == 1


def test_026_FR_002_project_and_tag_responses_expose_created_at(api_client) -> None:
    """026-FR-002: the REST/sync projection carries the creation instant."""

    with allure.step("Create a project and a tag"):
        project = api_client.post(
            "/api/projects",
            headers={"Idempotency-Key": "tiebreak-created-project"},
            json={"name": "Launch"},
        )
        tag = api_client.post(
            "/api/tags",
            headers={"Idempotency-Key": "tiebreak-created-tag"},
            json={"name": "focus"},
        )
        assert project.status_code == tag.status_code == 201
    with allure.step("Every read path returns created_at as an instant"):
        listed_projects = api_client.get("/api/projects").json()
        listed_tags = api_client.get("/api/tags").json()
        stamps = {
            "project": project.json()["created_at"],
            "tag": tag.json()["created_at"],
            "listed_project": listed_projects[0]["created_at"],
            "listed_tag": listed_tags[0]["created_at"],
        }
        _evidence("created_at values", stamps)
        for stamp in stamps.values():
            assert datetime.fromisoformat(stamp).tzinfo is not None
        assert stamps["project"] == stamps["listed_project"]
        assert stamps["tag"] == stamps["listed_tag"]
