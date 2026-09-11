"""Focused public TaskService projections."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.tasks import TaskRepository, TaskService
from app.schemas.tasks import TaskCreateRequest, TaskTransitionRequest


@pytest.fixture()
def task_repo(data_dir: Path) -> TaskRepository:
    return TaskRepository(data_dir)


@pytest.fixture()
def task_service(task_repo: TaskRepository) -> TaskService:
    return TaskService(task_repo)


def test_018_FR_012_completed_count_stays_behind_public_task_service(
    task_service: TaskService,
    monkeypatch,
) -> None:
    """018-FR-003, 018-FR-008, 018-FR-012: service owns the derived query."""

    calls: list[tuple[str, str]] = []

    def count_for_owner_by_state(*, owner_id: str, state: str) -> int:
        calls.append((owner_id, state))
        return 7

    monkeypatch.setattr(
        task_service.task_repo,
        "count_for_owner_by_state",
        count_for_owner_by_state,
    )

    assert task_service.completed_task_count(owner_id="user_profile") == 7
    assert calls == [("user_profile", "completed")]


def test_018_SC_001_completed_count_tracks_complete_and_reopen(
    task_service: TaskService,
) -> None:
    """018-FR-002, 018-FR-007, 018-FR-008: every read is authoritative."""

    owner_id = "user_profile"
    task = task_service.create_task(
        TaskCreateRequest(title="Ship profile count", state="next"),
        owner_id=owner_id,
        idempotency_key="profile-count-create",
    )
    assert task_service.completed_task_count(owner_id=owner_id) == 0

    completed = task_service.transition_task(
        task.id,
        TaskTransitionRequest(action="complete", expected_revision=task.revision),
        owner_id=owner_id,
        idempotency_key="profile-count-complete",
    )
    assert task_service.completed_task_count(owner_id=owner_id) == 1

    task_service.transition_task(
        task.id,
        TaskTransitionRequest(
            action="reopen",
            to_state="next",
            expected_revision=completed.revision,
        ),
        owner_id=owner_id,
        idempotency_key="profile-count-reopen",
    )
    assert task_service.completed_task_count(owner_id=owner_id) == 0
