"""Branch-coverage regression tests for the native GTD task module.

These tests exercise behavior paths that the existing API-level suite did not
reach: repository ``NotFoundError``/``ConflictError`` branches, idempotency
mismatch conflicts, cursor validation, task-state filter/cursor branches,
provenance rejection, and the active-reference validation paths.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.modules.tasks import TaskRepository, TaskService
from app.modules.tasks.domain import (
    ContextDocument,
    ProjectDocument,
    TaskDocument,
)
from app.schemas.tasks import (
    ContextCreateRequest,
    ProjectCreateRequest,
    TaskCommentCreateRequest,
    TaskCreateRequest,
    TaskSubtaskCreateRequest,
    TaskTransitionRequest,
    TaskUpdateRequest,
)
from app.utils.time import utcnow

OWNER = "user_branch_owner"


@pytest.fixture()
def service(data_dir: Path) -> TaskService:
    repository = TaskRepository(data_dir)
    return TaskService(repository)


def _make_project(
    service: TaskService, *, name: str = "Health", key: str = "p"
) -> ProjectDocument:
    return service.create_project(
        ProjectCreateRequest(name=name), owner_id=OWNER, idempotency_key=key
    )


def _make_context(
    service: TaskService, *, name: str = "phone", key: str = "c"
) -> ContextDocument:
    return service.create_context(
        ContextCreateRequest(name=name), owner_id=OWNER, idempotency_key=key
    )


def _make_task(
    service: TaskService,
    *,
    title: str = "Branch task",
    key: str = "t",
    **payload: object,
) -> TaskDocument:
    return service.create_task(
        TaskCreateRequest(title=title, **payload),  # type: ignore[arg-type]
        owner_id=OWNER,
        idempotency_key=key,
    )


# --- repository NotFound/Conflict branches ---------------------------------


def test_repository_raises_not_found_for_missing_subtask(service: TaskService) -> None:
    task = _make_task(service, key="task-for-subtask-missing")
    with pytest.raises(NotFoundError):
        service.task_repo.get_subtask_for_owner(
            "missing-subtask", owner_id=OWNER, task_id=task.id
        )


def test_repository_raises_not_found_for_missing_comment(service: TaskService) -> None:
    task = _make_task(service, key="task-for-comment-missing")
    with pytest.raises(NotFoundError):
        service.task_repo.get_comment_for_owner(
            "missing-comment", owner_id=OWNER, task_id=task.id
        )


def test_repository_lists_empty_subtasks_and_comments_for_missing_dir(
    service: TaskService,
) -> None:
    task = _make_task(service, key="task-empty-nested")
    assert service.task_repo.list_subtasks(owner_id=OWNER, task_id=task.id) == []
    assert service.task_repo.list_comments(owner_id=OWNER, task_id=task.id) == []


def test_repository_create_project_conflict_when_file_exists(
    service: TaskService,
) -> None:
    project = _make_project(service, key="dup-project")
    with pytest.raises(ConflictError):
        service.task_repo.create_project(project)


def test_repository_create_context_conflict_when_file_exists(
    service: TaskService,
) -> None:
    context = _make_context(service, key="dup-context")
    with pytest.raises(ConflictError):
        service.task_repo.create_context(context)


def test_repository_create_task_conflict_when_file_exists(service: TaskService) -> None:
    task = _make_task(service, key="dup-task")
    with pytest.raises(ConflictError):
        service.task_repo.create(task)


def test_repository_lists_empty_projects_contexts_tasks_for_missing_owner_dir(
    service: TaskService,
) -> None:
    assert service.task_repo.list_projects_for_owner(owner_id="never-seen") == []
    assert service.task_repo.list_contexts_for_owner(owner_id="never-seen") == []
    assert service.task_repo.list_for_owner(owner_id="never-seen") == []


def test_repository_get_project_context_task_raise_not_found_for_missing_records(
    service: TaskService,
) -> None:
    with pytest.raises(NotFoundError):
        service.task_repo.get_project_for_owner("missing", owner_id=OWNER)
    with pytest.raises(NotFoundError):
        service.task_repo.get_context_for_owner("missing", owner_id=OWNER)
    with pytest.raises(NotFoundError):
        service.task_repo.get_for_owner("missing", owner_id=OWNER)


# --- idempotency mismatch conflict branch ----------------------------------


def test_idempotency_key_replay_with_mismatched_payload_raises_conflict(
    service: TaskService,
) -> None:
    _make_project(service, name="First", key="shared-key")

    with pytest.raises(ConflictError):
        service.create_project(
            ProjectCreateRequest(name="Different"),
            owner_id=OWNER,
            idempotency_key="shared-key",
        )


def test_idempotency_key_replay_with_mismatched_command_raises_conflict(
    service: TaskService,
) -> None:
    _make_project(service, name="Project", key="cross-command-key")

    with pytest.raises(ConflictError):
        service.create_context(
            ContextCreateRequest(name="Context"),
            owner_id=OWNER,
            idempotency_key="cross-command-key",
        )


# --- active-reference validation branches ---------------------------------


def test_create_task_rejects_inactive_project(service: TaskService) -> None:
    project = _make_project(service, key="archived-project")
    project = project.model_copy(update={"state": "completed"})
    service.task_repo.dump_model(
        service.task_repo.project_path(OWNER, project.id), project
    )

    with pytest.raises(ValidationFailure, match="project must be active"):
        _make_task(service, key="inactive-project-task", project_id=project.id)


def test_create_task_rejects_duplicate_context_ids(service: TaskService) -> None:
    context = _make_context(service, key="dup-context-task")

    with pytest.raises(ValidationFailure, match="duplicates"):
        _make_task(
            service, key="dup-contexts-task", context_ids=[context.id, context.id]
        )


def test_create_task_rejects_inactive_context(service: TaskService) -> None:
    context = _make_context(service, key="archived-context")
    context = context.model_copy(update={"state": "archived"})
    service.task_repo.dump_model(
        service.task_repo.context_path(OWNER, context.id), context
    )

    with pytest.raises(ValidationFailure, match="contexts must be active"):
        _make_task(service, key="inactive-context-task", context_ids=[context.id])


def test_update_task_rejects_inactive_project_on_reassignment(
    service: TaskService,
) -> None:
    project = _make_project(service, key="update-inactive-project")
    task = _make_task(service, key="update-inactive-project-task")
    archived = project.model_copy(update={"state": "completed"})
    service.task_repo.dump_model(
        service.task_repo.project_path(OWNER, project.id), archived
    )

    with pytest.raises(ValidationFailure, match="project must be active"):
        service.update_task(
            task.id,
            TaskUpdateRequest(project_id=project.id, expected_revision=1),
            owner_id=OWNER,
            idempotency_key="update-inactive-project-attempt",
        )


def test_update_task_rejects_duplicate_context_ids(service: TaskService) -> None:
    context = _make_context(service, key="update-dup-context")
    task = _make_task(service, key="update-dup-context-task")

    with pytest.raises(ValidationFailure, match="duplicates"):
        service.update_task(
            task.id,
            TaskUpdateRequest(
                context_ids=[context.id, context.id], expected_revision=1
            ),
            owner_id=OWNER,
            idempotency_key="update-dup-contexts",
        )


def test_update_task_replays_idempotent_record(service: TaskService) -> None:
    task = _make_task(service, key="idempotent-update-task")

    first = service.update_task(
        task.id,
        TaskUpdateRequest(details="Same details", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="replay-update",
    )
    replayed = service.update_task(
        task.id,
        TaskUpdateRequest(details="Same details", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="replay-update",
    )
    assert first.revision == replayed.revision
    assert first.details == replayed.details


# --- transition branches ---------------------------------------------------


def test_transition_rejects_completing_already_terminal_task(
    service: TaskService,
) -> None:
    task = _make_task(service, key="double-complete-task")
    service.transition_task(
        task.id,
        TaskTransitionRequest(action="complete", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="complete-once",
    )
    with pytest.raises(ValidationFailure, match="Only open tasks can be completed"):
        service.transition_task(
            task.id,
            TaskTransitionRequest(action="complete", expected_revision=2),
            owner_id=OWNER,
            idempotency_key="complete-twice",
        )


def test_transition_rejects_cancelling_already_terminal_task(
    service: TaskService,
) -> None:
    task = _make_task(service, key="double-cancel-task")
    service.transition_task(
        task.id,
        TaskTransitionRequest(action="cancel", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="cancel-once",
    )
    with pytest.raises(ValidationFailure, match="Only open tasks can be cancelled"):
        service.transition_task(
            task.id,
            TaskTransitionRequest(action="cancel", expected_revision=2),
            owner_id=OWNER,
            idempotency_key="cancel-twice",
        )


def test_transition_reopen_rejects_open_task_without_destination(
    service: TaskService,
) -> None:
    task = _make_task(service, key="reopen-open-task")
    with pytest.raises(ValidationFailure, match="Reopen requires"):
        service.transition_task(
            task.id,
            TaskTransitionRequest(action="reopen", expected_revision=1),
            owner_id=OWNER,
            idempotency_key="reopen-open",
        )


def test_transition_move_rejects_terminal_task_without_destination(
    service: TaskService,
) -> None:
    task = _make_task(service, key="move-terminal-task")
    service.transition_task(
        task.id,
        TaskTransitionRequest(action="complete", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="complete-for-move",
    )
    with pytest.raises(ValidationFailure, match="Move requires"):
        service.transition_task(
            task.id,
            TaskTransitionRequest(action="move", expected_revision=2),
            owner_id=OWNER,
            idempotency_key="move-terminal",
        )


def test_transition_replay_returns_same_revision(service: TaskService) -> None:
    task = _make_task(service, key="idempotent-transition-task")
    first = service.transition_task(
        task.id,
        TaskTransitionRequest(action="complete", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="replay-transition",
    )
    replayed = service.transition_task(
        task.id,
        TaskTransitionRequest(action="complete", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="replay-transition",
    )
    assert first.revision == replayed.revision
    assert first.state == replayed.state == "completed"


def test_transition_move_to_waiting_requires_waiting_for(service: TaskService) -> None:
    task = _make_task(service, key="move-to-waiting")
    with pytest.raises(ValidationFailure, match="waiting_for"):
        service.transition_task(
            task.id,
            TaskTransitionRequest(
                action="move", to_state="waiting", expected_revision=1
            ),
            owner_id=OWNER,
            idempotency_key="move-waiting-no-for",
        )


# --- cursor validation branches -------------------------------------------


def _cursor(filters: dict[str, object], last: list[object]) -> str:
    payload = {"filters": filters, "last": last}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def test_list_tasks_rejects_cursor_with_mismatched_filters(
    service: TaskService,
) -> None:
    _make_task(service, key="cursor-mismatch-task")
    cursor = _cursor(
        {
            "state": "next",
            "project_id": None,
            "context_id": None,
            "unassigned_project": False,
            "include_completed": False,
        },
        [0, utcnow().isoformat(), "task_any"],
    )
    with pytest.raises(ValidationFailure, match="cursor"):
        service.list_tasks(
            owner_id=OWNER,
            state=None,
            project_id=None,
            context_id=None,
            unassigned_project=False,
            include_completed=False,
            cursor=cursor,
            limit=10,
        )


def test_list_tasks_rejects_cursor_with_invalid_tuple(service: TaskService) -> None:
    _make_task(service, key="cursor-invalid-tuple")
    cursor = _cursor(
        {
            "state": None,
            "project_id": None,
            "context_id": None,
            "unassigned_project": False,
            "include_completed": False,
        },
        ["not-int", "not-date", "task_any"],
    )
    with pytest.raises(ValidationFailure, match="cursor"):
        service.list_tasks(
            owner_id=OWNER,
            state=None,
            project_id=None,
            context_id=None,
            unassigned_project=False,
            include_completed=False,
            cursor=cursor,
            limit=10,
        )


def test_list_tasks_rejects_cursor_with_empty_task_id(service: TaskService) -> None:
    _make_task(service, key="cursor-empty-id")
    cursor = _cursor(
        {
            "state": None,
            "project_id": None,
            "context_id": None,
            "unassigned_project": False,
            "include_completed": False,
        },
        [0, utcnow().isoformat(), ""],
    )
    with pytest.raises(ValidationFailure, match="cursor"):
        service.list_tasks(
            owner_id=OWNER,
            state=None,
            project_id=None,
            context_id=None,
            unassigned_project=False,
            include_completed=False,
            cursor=cursor,
            limit=10,
        )


def test_list_tasks_rejects_garbage_cursor(service: TaskService) -> None:
    with pytest.raises(ValidationFailure, match="cursor"):
        service.list_tasks(
            owner_id=OWNER,
            state=None,
            project_id=None,
            context_id=None,
            unassigned_project=False,
            include_completed=False,
            cursor="!!!not-base64!!!",
            limit=10,
        )


# --- list filter/counts branches ------------------------------------------


def test_list_tasks_filter_by_state_and_include_completed(service: TaskService) -> None:
    open_task = _make_task(service, key="filter-open", state="next")
    done_task = _make_task(service, key="filter-done")
    service.transition_task(
        done_task.id,
        TaskTransitionRequest(action="complete", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="filter-complete-done",
    )

    next_only = service.list_tasks(
        owner_id=OWNER,
        state="next",
        project_id=None,
        context_id=None,
        unassigned_project=False,
        include_completed=False,
        cursor=None,
        limit=10,
    )
    assert [item.id for item in next_only[0]] == [open_task.id]

    with_completed = service.list_tasks(
        owner_id=OWNER,
        state=None,
        project_id=None,
        context_id=None,
        unassigned_project=False,
        include_completed=True,
        cursor=None,
        limit=10,
    )
    assert done_task.id in {item.id for item in with_completed[0]}


def test_list_tasks_unassigned_project_filter(service: TaskService) -> None:
    unassigned = _make_task(service, key="unassigned-task")
    assigned_project = _make_project(service, key="assigned-project")
    _make_task(service, key="assigned-task", project_id=assigned_project.id)

    page, _, _, counts = service.list_tasks(
        owner_id=OWNER,
        state=None,
        project_id=None,
        context_id=None,
        unassigned_project=True,
        include_completed=False,
        cursor=None,
        limit=10,
    )
    assert [item.id for item in page] == [unassigned.id]
    assert counts == {"inbox": 1, "next": 0, "waiting": 0, "someday": 0}


def test_list_tasks_rejects_project_and_unassigned_project_combo(
    service: TaskService,
) -> None:
    project = _make_project(service, key="combo-project")
    with pytest.raises(ValidationFailure, match="cannot be used together"):
        service.list_tasks(
            owner_id=OWNER,
            state=None,
            project_id=project.id,
            context_id=None,
            unassigned_project=True,
            include_completed=False,
            cursor=None,
            limit=10,
        )


def test_list_tasks_counts_scope_by_project(service: TaskService) -> None:
    project = _make_project(service, key="counts-project")
    _make_task(service, key="counts-in-project", project_id=project.id, state="next")
    _make_task(service, key="counts-out-of-project", state="inbox")

    _, _, _, counts = service.list_tasks(
        owner_id=OWNER,
        state=None,
        project_id=project.id,
        context_id=None,
        unassigned_project=False,
        include_completed=False,
        cursor=None,
        limit=10,
    )
    assert counts == {"inbox": 0, "next": 1, "waiting": 0, "someday": 0}


def test_list_tasks_counts_scope_by_context(service: TaskService) -> None:
    context = _make_context(service, key="counts-context")
    _make_task(
        service,
        key="counts-with-context",
        context_ids=[context.id],
        state="waiting",
        waiting_for="Dr. Smith",
    )
    _make_task(service, key="counts-no-context", state="inbox")

    _, _, _, counts = service.list_tasks(
        owner_id=OWNER,
        state=None,
        project_id=None,
        context_id=context.id,
        unassigned_project=False,
        include_completed=False,
        cursor=None,
        limit=10,
    )
    assert counts == {"inbox": 0, "next": 0, "waiting": 1, "someday": 0}


def test_list_tasks_validates_project_and_context_existence(
    service: TaskService,
) -> None:
    with pytest.raises(NotFoundError):
        service.list_tasks(
            owner_id=OWNER,
            state=None,
            project_id="missing-project",
            context_id=None,
            unassigned_project=False,
            include_completed=False,
            cursor=None,
            limit=10,
        )
    with pytest.raises(NotFoundError):
        service.list_tasks(
            owner_id=OWNER,
            state=None,
            project_id=None,
            context_id="missing-context",
            unassigned_project=False,
            include_completed=False,
            cursor=None,
            limit=10,
        )


def test_list_tasks_pagination_returns_cursor_only_when_has_more(
    service: TaskService,
) -> None:
    for index in range(3):
        _make_task(service, key=f"page-task-{index}")

    first_page, next_cursor, has_more, _ = service.list_tasks(
        owner_id=OWNER,
        state=None,
        project_id=None,
        context_id=None,
        unassigned_project=False,
        include_completed=False,
        cursor=None,
        limit=2,
    )
    assert has_more is True
    assert next_cursor is not None
    assert len(first_page) == 2

    second_page, next_cursor, has_more, _ = service.list_tasks(
        owner_id=OWNER,
        state=None,
        project_id=None,
        context_id=None,
        unassigned_project=False,
        include_completed=False,
        cursor=next_cursor,
        limit=2,
    )
    assert has_more is False
    assert next_cursor is None
    assert len(second_page) == 1


# --- nested resource idempotency replay -----------------------------------


def test_create_subtask_replays_idempotent_record(service: TaskService) -> None:
    task = _make_task(service, key="subtask-replay-task")
    first = service.create_subtask(
        task.id,
        TaskSubtaskCreateRequest(title="Same"),
        owner_id=OWNER,
        idempotency_key="replay-subtask",
    )
    replayed = service.create_subtask(
        task.id,
        TaskSubtaskCreateRequest(title="Same"),
        owner_id=OWNER,
        idempotency_key="replay-subtask",
    )
    assert first.id == replayed.id
    assert first.title == replayed.title


def test_create_comment_replays_idempotent_record(service: TaskService) -> None:
    task = _make_task(service, key="comment-replay-task")
    first = service.create_comment(
        task.id,
        TaskCommentCreateRequest(body="Same body"),
        owner_id=OWNER,
        actor_id=OWNER,
        idempotency_key="replay-comment",
    )
    replayed = service.create_comment(
        task.id,
        TaskCommentCreateRequest(body="Same body"),
        owner_id=OWNER,
        actor_id=OWNER,
        idempotency_key="replay-comment",
    )
    assert first.id == replayed.id
    assert first.body == replayed.body


def test_create_subtask_rejects_missing_task(service: TaskService) -> None:
    with pytest.raises(NotFoundError):
        service.create_subtask(
            "missing-task",
            TaskSubtaskCreateRequest(title="Nope"),
            owner_id=OWNER,
            idempotency_key="missing-task-subtask",
        )


def test_create_comment_rejects_missing_task(service: TaskService) -> None:
    with pytest.raises(NotFoundError):
        service.create_comment(
            "missing-task",
            TaskCommentCreateRequest(body="Nope"),
            owner_id=OWNER,
            actor_id=OWNER,
            idempotency_key="missing-task-comment",
        )


# --- project/context listing filters inactive records ---------------------


def test_list_projects_filters_inactive_records(service: TaskService) -> None:
    active = _make_project(service, name="Active", key="active-project")
    archived = _make_project(service, name="Archived", key="archived-project-list")
    archived = archived.model_copy(update={"state": "archived"})
    service.task_repo.dump_model(
        service.task_repo.project_path(OWNER, archived.id), archived
    )

    listed = service.list_projects(owner_id=OWNER)
    assert [project.id for project in listed] == [active.id]


def test_list_contexts_filters_inactive_records(service: TaskService) -> None:
    active = _make_context(service, name="active", key="active-context")
    archived = _make_context(service, name="archived", key="archived-context-list")
    archived = archived.model_copy(update={"state": "archived"})
    service.task_repo.dump_model(
        service.task_repo.context_path(OWNER, archived.id), archived
    )

    listed = service.list_contexts(owner_id=OWNER)
    assert [context.id for context in listed] == [active.id]


def test_context_name_is_prefixed_with_at_sign_when_missing(
    service: TaskService,
) -> None:
    context = service.create_context(
        ContextCreateRequest(name="already-at-prefixed"),
        owner_id=OWNER,
        idempotency_key="at-prefix",
    )
    assert context.name == "@already-at-prefixed"


# --- get_task_detail ordering --------------------------------------------


def test_get_task_detail_orders_subtasks_and_comments(service: TaskService) -> None:
    task = _make_task(service, key="detail-ordering-task")
    first_subtask = service.create_subtask(
        task.id,
        TaskSubtaskCreateRequest(title="First"),
        owner_id=OWNER,
        idempotency_key="detail-subtask-first",
    )
    second_subtask = service.create_subtask(
        task.id,
        TaskSubtaskCreateRequest(title="Second"),
        owner_id=OWNER,
        idempotency_key="detail-subtask-second",
    )
    first_comment = service.create_comment(
        task.id,
        TaskCommentCreateRequest(body="First comment"),
        owner_id=OWNER,
        actor_id=OWNER,
        idempotency_key="detail-comment-first",
    )
    second_comment = service.create_comment(
        task.id,
        TaskCommentCreateRequest(body="Second comment"),
        owner_id=OWNER,
        actor_id=OWNER,
        idempotency_key="detail-comment-second",
    )

    _, subtasks, comments = service.get_task_detail(task.id, owner_id=OWNER)
    assert [item.id for item in subtasks] == [first_subtask.id, second_subtask.id]
    assert [item.id for item in comments] == [first_comment.id, second_comment.id]


# --- ensure_owner_dir helper ----------------------------------------------


def test_ensure_owner_dir_is_idempotent(service: TaskService) -> None:
    first = service.task_repo.ensure_owner_dir(OWNER)
    second = service.task_repo.ensure_owner_dir(OWNER)
    assert first == second
    assert first.exists()


# --- next_order_key --------------------------------------------------------


def test_next_order_key_increments_per_state(service: TaskService) -> None:
    first_inbox = _make_task(service, key="order-inbox-one", state="inbox")
    second_inbox = _make_task(service, key="order-inbox-two", state="inbox")
    assert first_inbox.order_key == 0
    assert second_inbox.order_key == 1
    first_next = _make_task(service, key="order-next-one", state="next")
    assert first_next.order_key == 0
