"""Repository-level cross-owner isolation tests for the native GTD task module.

Every owner-scoped read and the GDPR purge are exercised with **two** owners
holding data in the same SQLite database. That shape is what makes the
``WHERE owner_id = ?`` predicates observable: with a single owner in the
database a query that filters and a query that does not return identical rows,
so a dropped predicate survives undetected.

The existing cross-owner coverage lives in the HTTP suite (``second_api_client``
in ``conftest``). ASGI fixtures cannot run under mutmut's stack-statistics
instrumentation (ADR-0004), so those assertions cannot defend the predicates
during a mutation campaign. These service/repository-level tests can, which is
why they avoid the API layer entirely.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.exceptions import NotFoundError
from app.modules.tasks import TaskRepository, TaskService
from app.schemas.tasks import (
    ProjectCreateRequest,
    TagCreateRequest,
    TaskCommentCreateRequest,
    TaskCreateRequest,
    TaskSubtaskCreateRequest,
)

OWNER_A = "user_isolation_a"
OWNER_B = "user_isolation_b"


@pytest.fixture()
def service(data_dir: Path) -> TaskService:
    """One service over one database, so both owners share the storage."""
    return TaskService(TaskRepository(data_dir))


def _task(service: TaskService, owner_id: str, *, title: str, key: str):
    return service.create_task(
        TaskCreateRequest(title=title), owner_id=owner_id, idempotency_key=key
    )


# --- tasks ------------------------------------------------------------------


def test_get_task_for_owner_hides_another_owners_task(service: TaskService) -> None:
    foreign = _task(service, OWNER_B, title="B private", key="b-task")

    with pytest.raises(NotFoundError):
        service.task_repo.get_for_owner(foreign.id, owner_id=OWNER_A)


def test_list_tasks_for_owner_excludes_another_owners_tasks(
    service: TaskService,
) -> None:
    mine = _task(service, OWNER_A, title="A task", key="a-task")
    foreign = _task(service, OWNER_B, title="B task", key="b-task")

    visible = service.task_repo.list_for_owner(owner_id=OWNER_A)

    assert [task.id for task in visible] == [mine.id]
    assert foreign.id not in {task.id for task in visible}


# --- projects and tags ------------------------------------------------------


def test_get_project_for_owner_hides_another_owners_project(
    service: TaskService,
) -> None:
    foreign = service.create_project(
        ProjectCreateRequest(name="B project"), owner_id=OWNER_B, idempotency_key="b-p"
    )

    with pytest.raises(NotFoundError):
        service.task_repo.get_project_for_owner(foreign.id, owner_id=OWNER_A)


def test_list_projects_for_owner_excludes_another_owners_projects(
    service: TaskService,
) -> None:
    mine = service.create_project(
        ProjectCreateRequest(name="A project"), owner_id=OWNER_A, idempotency_key="a-p"
    )
    service.create_project(
        ProjectCreateRequest(name="B project"), owner_id=OWNER_B, idempotency_key="b-p"
    )

    visible = service.task_repo.list_projects_for_owner(owner_id=OWNER_A)

    assert [project.id for project in visible] == [mine.id]


def test_get_tag_for_owner_hides_another_owners_tag(service: TaskService) -> None:
    foreign = service.create_tag(
        TagCreateRequest(name="btag"), owner_id=OWNER_B, idempotency_key="b-tag"
    )

    with pytest.raises(NotFoundError):
        service.task_repo.get_tag_for_owner(foreign.id, owner_id=OWNER_A)


def test_list_tags_for_owner_excludes_another_owners_tags(
    service: TaskService,
) -> None:
    mine = service.create_tag(
        TagCreateRequest(name="atag"), owner_id=OWNER_A, idempotency_key="a-tag"
    )
    service.create_tag(
        TagCreateRequest(name="btag"), owner_id=OWNER_B, idempotency_key="b-tag"
    )

    visible = service.task_repo.list_tags_for_owner(owner_id=OWNER_A)

    assert [tag.id for tag in visible] == [mine.id]


# --- subtasks and comments --------------------------------------------------


def test_subtask_reads_are_scoped_to_the_owning_account(service: TaskService) -> None:
    foreign_task = _task(service, OWNER_B, title="B task", key="b-task")
    foreign_subtask = service.create_subtask(
        foreign_task.id,
        TaskSubtaskCreateRequest(title="B subtask"),
        owner_id=OWNER_B,
        idempotency_key="b-sub",
    )

    assert (
        service.task_repo.list_subtasks(owner_id=OWNER_A, task_id=foreign_task.id) == []
    )
    with pytest.raises(NotFoundError):
        service.task_repo.get_subtask_for_owner(
            foreign_subtask.id, owner_id=OWNER_A, task_id=foreign_task.id
        )


def test_comment_reads_are_scoped_to_the_owning_account(service: TaskService) -> None:
    foreign_task = _task(service, OWNER_B, title="B task", key="b-task")
    foreign_comment = service.create_comment(
        foreign_task.id,
        TaskCommentCreateRequest(body="B comment"),
        owner_id=OWNER_B,
        actor_id=OWNER_B,
        idempotency_key="b-comment",
    )

    assert (
        service.task_repo.list_comments(owner_id=OWNER_A, task_id=foreign_task.id) == []
    )
    with pytest.raises(NotFoundError):
        service.task_repo.get_comment_for_owner(
            foreign_comment.id, owner_id=OWNER_A, task_id=foreign_task.id
        )


# --- idempotency ------------------------------------------------------------


def test_idempotency_keys_do_not_collide_across_owners(service: TaskService) -> None:
    shared_key = "same-key-both-owners"
    mine = _task(service, OWNER_A, title="A task", key=shared_key)
    foreign = _task(service, OWNER_B, title="B task", key=shared_key)

    # A replay of one owner's key must resolve to that owner's own resource,
    # never to the other account's task created under the identical key.
    assert mine.id != foreign.id

    record_a = service.task_repo.get_idempotency(owner_id=OWNER_A, key=shared_key)
    record_b = service.task_repo.get_idempotency(owner_id=OWNER_B, key=shared_key)
    assert record_a is not None and record_b is not None
    assert record_a.resource_id == mine.id
    assert record_b.resource_id == foreign.id

    assert [
        record.resource_id
        for record in service.task_repo.list_idempotency_for_owner(owner_id=OWNER_A)
    ] == [mine.id]


# --- ordering ---------------------------------------------------------------


def test_next_order_key_is_computed_per_owner(service: TaskService) -> None:
    for index in range(3):
        _task(service, OWNER_B, title=f"B {index}", key=f"b-{index}")

    # Owner A has no inbox tasks, so their first key must ignore owner B's rows.
    assert service.task_repo.next_order_key(owner_id=OWNER_A, state="inbox") == 0


# --- GDPR purge -------------------------------------------------------------


def test_delete_all_for_owner_leaves_other_owners_data_intact(
    service: TaskService,
) -> None:
    """The account purge must erase exactly one owner.

    A dropped ``owner_id`` predicate here deletes every account's data, so this
    is the highest-severity isolation path in the module.
    """
    survivor = _task(service, OWNER_B, title="B survives", key="b-task")
    survivor_project = service.create_project(
        ProjectCreateRequest(name="B project"), owner_id=OWNER_B, idempotency_key="b-p"
    )
    _task(service, OWNER_A, title="A purged", key="a-task")

    service.task_repo.delete_all_for_owner(owner_id=OWNER_A)

    assert service.task_repo.list_for_owner(owner_id=OWNER_A) == []
    assert [task.id for task in service.task_repo.list_for_owner(owner_id=OWNER_B)] == [
        survivor.id
    ]
    assert [
        project.id
        for project in service.task_repo.list_projects_for_owner(owner_id=OWNER_B)
    ] == [survivor_project.id]
