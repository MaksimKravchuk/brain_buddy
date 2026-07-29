"""Idempotency-record repair path (crash between record store and resource write).

Each owner-serialized Tasks command stores its idempotency record before it
persists the resource, so a crash in that gap leaves a record whose resource is
missing (or, after a later write, stale). The reconcile path re-applies each
record -- recreating a missing resource or saving a newer snapshot -- which the
happy-path replay tests (resource present, same revision) never exercise.
"""

from __future__ import annotations

from app.modules.tasks.domain import (
    IdempotencyRecord,
    ProjectDocument,
    SmartAddTaskResultDocument,
    TagDocument,
    TaskCommentDocument,
    TaskDocument,
    TaskSubtaskDocument,
)
from app.utils.time import utcnow


def test_reconcile_repairs_missing_then_stale_resources(api_client) -> None:
    container = api_client.app.state.container
    service = container.task_service
    repo = container.task_repo
    owner = "owner-idem-repair"
    now = utcnow()

    def _store(key: str, command: str, resource_id: str, doc) -> None:
        repo.save_idempotency(
            owner_id=owner,
            record=IdempotencyRecord(
                key=key,
                command=command,
                request_hash="request-hash",
                resource_id=resource_id,
                response_body=doc.model_dump(mode="json"),
                created_at=now,
            ),
        )

    # A real parent task for the subtask/comment foreign keys.
    parent = TaskDocument(
        id="task_parent",
        owner_id=owner,
        title="Parent",
        state="inbox",
        order_key=0,
        created_at=now,
        updated_at=now,
    )
    repo.create(parent)

    project = ProjectDocument(
        id="project_ghost",
        owner_id=owner,
        name="Ghost Project",
        normalized_name="ghost project",
        created_at=now,
        updated_at=now,
    )
    tag = TagDocument(
        id="tag_ghost",
        owner_id=owner,
        name="ghost",
        normalized_name="ghost",
        created_at=now,
        updated_at=now,
    )
    task = TaskDocument(
        id="task_ghost",
        owner_id=owner,
        title="Ghost Task",
        state="inbox",
        order_key=1,
        created_at=now,
        updated_at=now,
    )
    subtask = TaskSubtaskDocument(
        id="subtask_ghost",
        owner_id=owner,
        task_id="task_parent",
        title="Ghost Subtask",
        order_key=0,
        created_at=now,
        updated_at=now,
    )
    comment = TaskCommentDocument(
        id="comment_ghost",
        owner_id=owner,
        task_id="task_parent",
        actor_id=owner,
        body="Ghost comment",
        created_at=now,
    )
    _store("k-project", "create_project", project.id, project)
    _store("k-tag", "create_tag", tag.id, tag)
    _store("k-task", "create_native_inbox_task", task.id, task)
    _store("k-subtask", "create_subtask:task_parent", subtask.id, subtask)
    _store("k-comment", "create_comment:task_parent", comment.id, comment)

    # Repair: every missing resource is recreated from its record.
    service._reconcile_idempotent_results(owner_id=owner)
    assert repo.get_project_for_owner("project_ghost", owner_id=owner).name == (
        "Ghost Project"
    )
    assert repo.get_tag_for_owner("tag_ghost", owner_id=owner).name == "ghost"
    assert repo.get_for_owner("task_ghost", owner_id=owner).title == "Ghost Task"
    assert repo.get_subtask_for_owner(
        "subtask_ghost", owner_id=owner, task_id="task_parent"
    )
    assert repo.get_comment_for_owner(
        "comment_ghost", owner_id=owner, task_id="task_parent"
    )

    # Stale: a newer recorded snapshot is saved over the current resource.
    newer_project = project.model_copy(
        update={"revision": project.revision + 1, "name": "Ghost Project v2"}
    )
    newer_task = task.model_copy(
        update={"revision": task.revision + 1, "title": "Ghost Task v2"}
    )
    newer_subtask = subtask.model_copy(
        update={"revision": subtask.revision + 1, "title": "Ghost Subtask v2"}
    )
    newer_comment = comment.model_copy(
        update={"revision": comment.revision + 1, "body": "Ghost comment v2"}
    )
    _store("k-project-2", "update_project:project_ghost", project.id, newer_project)
    _store("k-task-2", "create_native_inbox_task", task.id, newer_task)
    _store("k-subtask-2", "update_subtask:task_parent", subtask.id, newer_subtask)
    _store("k-comment-2", "update_comment:task_parent", comment.id, newer_comment)
    for key in ("k-project-2", "k-task-2", "k-subtask-2", "k-comment-2"):
        service._reconcile_idempotent_result(owner_id=owner, key=key)

    assert repo.get_project_for_owner("project_ghost", owner_id=owner).name == (
        "Ghost Project v2"
    )
    assert repo.get_for_owner("task_ghost", owner_id=owner).title == "Ghost Task v2"
    assert (
        repo.get_subtask_for_owner(
            "subtask_ghost", owner_id=owner, task_id="task_parent"
        ).title
        == "Ghost Subtask v2"
    )
    assert (
        repo.get_comment_for_owner(
            "comment_ghost", owner_id=owner, task_id="task_parent"
        ).body
        == "Ghost comment v2"
    )


def test_reconcile_repairs_a_missing_then_stale_smart_add_result(api_client) -> None:
    container = api_client.app.state.container
    service = container.task_service
    repo = container.task_repo
    owner = "owner-smartadd-repair"
    now = utcnow()

    project = ProjectDocument(
        id="sa_project",
        owner_id=owner,
        name="Smart Project",
        normalized_name="smart project",
        created_at=now,
        updated_at=now,
    )
    tag = TagDocument(
        id="sa_tag",
        owner_id=owner,
        name="smart",
        normalized_name="smart",
        created_at=now,
        updated_at=now,
    )
    task = TaskDocument(
        id="sa_task",
        owner_id=owner,
        title="Smart Task",
        state="inbox",
        project_id="sa_project",
        tag_ids=["sa_tag"],
        order_key=0,
        created_at=now,
        updated_at=now,
    )
    result = SmartAddTaskResultDocument(task=task, project=project, tags=[tag])
    repo.save_idempotency(
        owner_id=owner,
        record=IdempotencyRecord(
            key="k-smartadd",
            command="smart_add_task",
            request_hash="request-hash",
            resource_id=task.id,
            response_body=result.model_dump(mode="json"),
            created_at=now,
        ),
    )

    # Repair recreates the project, tag, and task the smart-add produced.
    service._reconcile_idempotent_result(owner_id=owner, key="k-smartadd")
    assert repo.get_project_for_owner("sa_project", owner_id=owner)
    assert repo.get_tag_for_owner("sa_tag", owner_id=owner)
    assert repo.get_for_owner("sa_task", owner_id=owner).title == "Smart Task"

    # A newer recorded snapshot updates each stale component.
    newer = result.model_copy(
        update={
            "task": task.model_copy(
                update={"revision": task.revision + 1, "title": "Smart Task v2"}
            ),
            "project": project.model_copy(
                update={"revision": project.revision + 1, "name": "Smart Project v2"}
            ),
            "tags": [tag.model_copy(update={"revision": tag.revision + 1})],
        }
    )
    repo.save_idempotency(
        owner_id=owner,
        record=IdempotencyRecord(
            key="k-smartadd-2",
            command="smart_add_task",
            request_hash="request-hash",
            resource_id=task.id,
            response_body=newer.model_dump(mode="json"),
            created_at=now,
        ),
    )
    service._reconcile_idempotent_result(owner_id=owner, key="k-smartadd-2")
    assert repo.get_for_owner("sa_task", owner_id=owner).title == "Smart Task v2"
    assert repo.get_project_for_owner("sa_project", owner_id=owner).name == (
        "Smart Project v2"
    )
