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
    IdempotencyRecord,
    ProjectDocument,
    TaskDocument,
)
from app.schemas.tasks import (
    BrainDumpOperationStartRequest,
    BrainDumpProposalUpdateRequest,
    BrainDumpTranscriptAppendRequest,
    ContextCreateRequest,
    ExpectedRevisionRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    TagCreateRequest,
    TagUpdateRequest,
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


def _make_tag(
    service: TaskService, *, name: str = "phone", key: str = "tag"
) -> ContextDocument:
    return service.create_tag(
        TagCreateRequest(name=name), owner_id=OWNER, idempotency_key=key
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


def test_project_and_tag_updates_archive_delete_and_replay_are_idempotent(
    service: TaskService,
) -> None:
    project = _make_project(service, name="Home", key="update-project-source")
    updated_project = service.update_project(
        project.id,
        ProjectUpdateRequest(name="Home Ops", color="blue", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="update-project-once",
    )
    replayed_project = service.update_project(
        project.id,
        ProjectUpdateRequest(name="Home Ops", color="blue", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="update-project-once",
    )
    assert replayed_project == updated_project

    archived_project = service.archive_project(
        project.id,
        ExpectedRevisionRequest(expected_revision=2),
        owner_id=OWNER,
        idempotency_key="archive-project-once",
    )
    replayed_archived_project = service.archive_project(
        project.id,
        ExpectedRevisionRequest(expected_revision=2),
        owner_id=OWNER,
        idempotency_key="archive-project-once",
    )
    assert replayed_archived_project == archived_project
    assert archived_project.state == "archived"

    tag = _make_tag(service, name="calls", key="update-tag-source")
    first_tag_replay = service.create_tag(
        TagCreateRequest(name="calls"), owner_id=OWNER, idempotency_key="update-tag-source"
    )
    assert first_tag_replay == tag

    updated_tag = service.update_tag(
        tag.id,
        TagUpdateRequest(name="Deep Calls", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="update-tag-once",
    )
    replayed_tag = service.update_tag(
        tag.id,
        TagUpdateRequest(name="Deep Calls", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="update-tag-once",
    )
    assert replayed_tag == updated_tag

    deleted_tag = service.delete_tag(
        tag.id,
        ExpectedRevisionRequest(expected_revision=2),
        owner_id=OWNER,
        idempotency_key="delete-tag-once",
    )
    replayed_deleted_tag = service.delete_tag(
        tag.id,
        ExpectedRevisionRequest(expected_revision=2),
        owner_id=OWNER,
        idempotency_key="delete-tag-once",
    )
    assert replayed_deleted_tag == deleted_tag
    assert deleted_tag.state == "deleted"


def test_project_and_tag_names_must_be_unique_per_active_owner(
    service: TaskService,
) -> None:
    _make_project(service, name="Home", key="unique-project-a")
    with pytest.raises(ConflictError):
        _make_project(service, name=" home ", key="unique-project-b")

    _make_tag(service, name="@Calls", key="unique-tag-a")
    with pytest.raises(ConflictError):
        _make_tag(service, name="calls", key="unique-tag-b")


def test_repository_dump_model_mirrors_task_nested_and_idempotency_records(
    data_dir: Path,
) -> None:
    repository = TaskRepository(data_dir)
    service = TaskService(repository)
    task = _make_task(service, key="dump-task")
    subtask = service.create_subtask(
        task.id,
        TaskSubtaskCreateRequest(title="Original subtask"),
        owner_id=OWNER,
        idempotency_key="dump-subtask",
    )
    comment = service.create_comment(
        task.id,
        TaskCommentCreateRequest(body="Original comment"),
        owner_id=OWNER,
        actor_id=OWNER,
        idempotency_key="dump-comment",
    )

    mirrored_task = task.model_copy(update={"details": "Mirrored", "revision": 2})
    repository.dump_model(repository.task_path(OWNER, task.id), mirrored_task)
    assert repository.get_for_owner(task.id, owner_id=OWNER).details == "Mirrored"

    mirrored_subtask = subtask.model_copy(update={"title": "Mirrored subtask"})
    repository.dump_model(
        repository.subtask_path(OWNER, task.id, subtask.id), mirrored_subtask
    )
    assert (
        repository.get_subtask_for_owner(subtask.id, owner_id=OWNER, task_id=task.id).title
        == "Mirrored subtask"
    )

    mirrored_comment = comment.model_copy(update={"body": "Mirrored comment"})
    repository.dump_model(
        repository.comment_path(OWNER, task.id, comment.id), mirrored_comment
    )
    assert (
        repository.get_comment_for_owner(comment.id, owner_id=OWNER, task_id=task.id).body
        == "Mirrored comment"
    )

    record = IdempotencyRecord(
        key="dump-record",
        command="create_task",
        request_hash="hash",
        resource_id=task.id,
        response_body=task.model_dump(mode="json"),
        created_at=utcnow(),
    )
    repository.dump_model(repository.idempotency_path(OWNER, record.key), record)
    assert repository.get_idempotency(owner_id=OWNER, key=record.key) == record


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


def test_update_task_replay_returns_original_snapshot(service: TaskService) -> None:
    task = _make_task(service, key="snapshot-update-task", title="Original")

    first = service.update_task(
        task.id,
        TaskUpdateRequest(details="First result", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="snapshot-update",
    )
    later = service.update_task(
        task.id,
        TaskUpdateRequest(title="Later edit", expected_revision=2),
        owner_id=OWNER,
        idempotency_key="snapshot-later-update",
    )
    replayed = service.update_task(
        task.id,
        TaskUpdateRequest(details="First result", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="snapshot-update",
    )

    assert replayed == first
    assert later.title == service.get_task(task.id, owner_id=OWNER).title


def test_update_task_idempotency_hash_includes_field_presence(
    service: TaskService,
) -> None:
    task = _make_task(service, key="field-presence-task")
    service.update_task(
        task.id,
        TaskUpdateRequest(expected_revision=1),
        owner_id=OWNER,
        idempotency_key="field-presence-update",
    )

    with pytest.raises(ConflictError):
        service.update_task(
            task.id,
            TaskUpdateRequest(details=None, expected_revision=1),
            owner_id=OWNER,
            idempotency_key="field-presence-update",
        )


def test_create_task_replay_recovers_missing_resource_after_crash(
    monkeypatch: pytest.MonkeyPatch, service: TaskService
) -> None:
    original_create = service.task_repo.create
    calls = 0

    def fail_once(task: TaskDocument) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated crash after idempotency write")
        original_create(task)

    monkeypatch.setattr(service.task_repo, "create", fail_once)
    payload = TaskCreateRequest(title="Crash recover")
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.create_task(
            payload, owner_id=OWNER, idempotency_key="crash-create-task"
        )

    replayed = service.create_task(
        payload, owner_id=OWNER, idempotency_key="crash-create-task"
    )

    assert replayed.title == "Crash recover"
    assert [task.id for task in service.task_repo.list_for_owner(owner_id=OWNER)] == [
        replayed.id
    ]


def test_update_task_replay_applies_recorded_result_after_crash(
    monkeypatch: pytest.MonkeyPatch, service: TaskService
) -> None:
    task = _make_task(service, key="crash-update-task")
    original_save = service.task_repo.save
    calls = 0

    def fail_once(updated: TaskDocument) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated crash after idempotency write")
        original_save(updated)

    monkeypatch.setattr(service.task_repo, "save", fail_once)
    payload = TaskUpdateRequest(details="Recovered update", expected_revision=1)
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.update_task(
            task.id, payload, owner_id=OWNER, idempotency_key="crash-update"
        )

    replayed = service.update_task(
        task.id, payload, owner_id=OWNER, idempotency_key="crash-update"
    )

    assert replayed.details == "Recovered update"
    assert replayed.revision == 2
    assert service.get_task(task.id, owner_id=OWNER).details == "Recovered update"


def test_failed_update_rolls_back_idempotency_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch, service: TaskService
) -> None:
    task = _make_task(service, key="intervening-update-task")
    original_save = service.task_repo.save
    calls = 0

    def fail_once(updated: TaskDocument) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated crash after idempotency write")
        original_save(updated)

    monkeypatch.setattr(service.task_repo, "save", fail_once)
    first_payload = TaskUpdateRequest(details="A", expected_revision=1)
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.update_task(
            task.id,
            first_payload,
            owner_id=OWNER,
            idempotency_key="intervening-update-a",
        )

    updated = service.update_task(
        task.id,
        TaskUpdateRequest(details="B", expected_revision=1),
        owner_id=OWNER,
        idempotency_key="intervening-update-b",
    )
    assert updated.details == "B"
    assert updated.revision == 2

    with pytest.raises(ConflictError):
        service.update_task(
            task.id,
            first_payload,
            owner_id=OWNER,
            idempotency_key="intervening-update-a",
        )

    canonical = service.get_task(task.id, owner_id=OWNER)
    assert canonical.details == "B"
    assert canonical.revision == 2


def test_reconcile_restores_pending_create_results(service: TaskService) -> None:
    assert service.task_repo.list_idempotency_for_owner(owner_id="never-seen") == []

    project = _make_project(service, key="restore-project")
    context = _make_context(service, key="restore-context")
    task = _make_task(service, key="restore-task")
    subtask = service.create_subtask(
        task.id,
        TaskSubtaskCreateRequest(title="Restore subtask"),
        owner_id=OWNER,
        idempotency_key="restore-subtask",
    )
    comment = service.create_comment(
        task.id,
        TaskCommentCreateRequest(body="Restore comment"),
        owner_id=OWNER,
        actor_id=OWNER,
        idempotency_key="restore-comment",
    )

    service.task_repo.project_path(OWNER, project.id).unlink()
    service.task_repo.context_path(OWNER, context.id).unlink()
    service.task_repo.subtask_path(OWNER, task.id, subtask.id).unlink()
    service.task_repo.comment_path(OWNER, task.id, comment.id).unlink()

    service._reconcile_idempotent_results(owner_id=OWNER)

    assert service.get_project(project.id, owner_id=OWNER).name == project.name
    assert service.get_context(context.id, owner_id=OWNER).name == context.name
    restored_task, restored_subtasks, restored_comments = service.get_task_detail(
        task.id, owner_id=OWNER
    )
    assert restored_task.id == task.id
    assert [item.id for item in restored_subtasks] == [subtask.id]
    assert [item.id for item in restored_comments] == [comment.id]


def test_brain_dump_operation_uses_sqlite_canonical_when_json_mirror_is_missing(
    data_dir: Path,
) -> None:
    service = TaskService(TaskRepository(data_dir))
    operation = service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": False}}
        ),
        owner_id=OWNER,
        idempotency_key="sqlite-canonical-brain-dump",
    )
    service.task_repo.brain_dump_operation_path(OWNER, operation.id).unlink()

    reloaded = TaskService(TaskRepository(data_dir))

    assert reloaded.get_brain_dump_operation(operation.id, owner_id=OWNER) == operation


def test_brain_dump_append_retry_after_idempotency_crash_does_not_advance_revision(
    monkeypatch: pytest.MonkeyPatch, service: TaskService
) -> None:
    operation = service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": False}}
        ),
        owner_id=OWNER,
        idempotency_key="crash-start-brain-dump",
    )
    original_store_idempotency = service._store_idempotency
    calls = 0

    def fail_once_after_operation_write(**kwargs: object) -> None:
        nonlocal calls
        if kwargs["command"] == f"brain_dump_append:{operation.id}" and calls == 0:
            calls += 1
            raise RuntimeError("simulated crash after brain dump write")
        original_store_idempotency(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "_store_idempotency", fail_once_after_operation_write)
    payload = BrainDumpTranscriptAppendRequest.model_validate(
        {"segments": [{"sequence": 1, "text": "Pay VAT.", "stability": "stable"}]}
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        service.append_brain_dump_transcript(
            operation.id,
            payload,
            owner_id=OWNER,
            idempotency_key="crash-append-brain-dump",
        )

    monkeypatch.setattr(service, "_store_idempotency", original_store_idempotency)
    replayed = service.append_brain_dump_transcript(
        operation.id,
        payload,
        owner_id=OWNER,
        idempotency_key="crash-append-brain-dump",
    )

    assert replayed.revision == operation.revision + 1
    assert [segment.sequence for segment in replayed.segments] == [1]


def test_brain_dump_start_replay_and_consent_validation(service: TaskService) -> None:
    payload = BrainDumpOperationStartRequest.model_validate(
        {"consent": {"microphone": True, "external_processing_allowed": False}}
    )

    started = service.start_brain_dump_operation(
        payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-start-replay",
    )
    replayed = service.start_brain_dump_operation(
        payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-start-replay",
    )

    assert replayed == started

    with pytest.raises(ValidationFailure, match="Microphone consent"):
        service.start_brain_dump_operation(
            BrainDumpOperationStartRequest.model_validate(
                {"consent": {"microphone": False, "external_processing_allowed": False}}
            ),
            owner_id=OWNER,
            idempotency_key="brain-dump-no-mic-consent",
        )


def test_brain_dump_append_replay_state_and_duplicate_segment_branches(
    service: TaskService,
) -> None:
    start_payload = BrainDumpOperationStartRequest.model_validate(
        {"consent": {"microphone": True, "external_processing_allowed": False}}
    )
    append_payload = BrainDumpTranscriptAppendRequest.model_validate(
        {"segments": [{"sequence": 1, "text": "Pay VAT.", "stability": "stable"}]}
    )
    operation = service.start_brain_dump_operation(
        start_payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-append-branches-start",
    )

    appended = service.append_brain_dump_transcript(
        operation.id,
        append_payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-append-replay",
    )
    replayed = service.append_brain_dump_transcript(
        operation.id,
        append_payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-append-replay",
    )

    assert replayed == appended

    duplicate = service.append_brain_dump_transcript(
        operation.id,
        append_payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-append-duplicate-same",
    )
    assert duplicate.segments == appended.segments

    with pytest.raises(ConflictError, match="Brain dump segment"):
        service.append_brain_dump_transcript(
            operation.id,
            BrainDumpTranscriptAppendRequest.model_validate(
                {"segments": [{"sequence": 1, "text": "Pay taxes.", "stability": "stable"}]}
            ),
            owner_id=OWNER,
            idempotency_key="brain-dump-append-duplicate-conflict",
        )

    cancelled = service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=duplicate.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-cancel-before-append",
        action="cancel",
    )
    with pytest.raises(ValidationFailure, match="Transcript can only"):
        service.append_brain_dump_transcript(
            cancelled.id,
            BrainDumpTranscriptAppendRequest.model_validate(
                {"segments": [{"sequence": 2, "text": "Call bank.", "stability": "stable"}]}
            ),
            owner_id=OWNER,
            idempotency_key="brain-dump-append-cancelled",
        )


def test_brain_dump_proposal_update_replay_not_found_and_invalid_state(
    service: TaskService,
) -> None:
    operation = service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": False}}
        ),
        owner_id=OWNER,
        idempotency_key="brain-dump-proposal-start",
    )
    operation = service.append_brain_dump_transcript(
        operation.id,
        BrainDumpTranscriptAppendRequest.model_validate(
            {"segments": [{"sequence": 1, "text": "Email broker.", "stability": "stable"}]}
        ),
        owner_id=OWNER,
        idempotency_key="brain-dump-proposal-segment",
    )
    proposal_id = operation.proposals[0].id
    payload = BrainDumpProposalUpdateRequest(title="Email mortgage broker", expected_revision=operation.revision)

    updated = service.update_brain_dump_proposal(
        operation.id,
        proposal_id,
        payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-proposal-update-replay",
    )
    replayed = service.update_brain_dump_proposal(
        operation.id,
        proposal_id,
        payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-proposal-update-replay",
    )
    assert replayed == updated

    with pytest.raises(NotFoundError, match="Brain dump proposal"):
        service.update_brain_dump_proposal(
            operation.id,
            "missing-proposal",
            BrainDumpProposalUpdateRequest(deleted=True, expected_revision=updated.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-proposal-missing",
        )

    cancelled = service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=updated.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-proposal-cancel",
        action="cancel",
    )
    with pytest.raises(ValidationFailure, match="Proposal cannot"):
        service.update_brain_dump_proposal(
            cancelled.id,
            proposal_id,
            BrainDumpProposalUpdateRequest(title="Ignored", expected_revision=cancelled.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-proposal-cancelled-edit",
        )


def test_brain_dump_transition_validation_and_replay_branches(service: TaskService) -> None:
    start_payload = BrainDumpOperationStartRequest.model_validate(
        {"consent": {"microphone": True, "external_processing_allowed": False}}
    )
    operation = service.start_brain_dump_operation(
        start_payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-transition-start",
    )

    paused = service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=operation.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-pause-replay",
        action="pause",
    )
    replayed = service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=operation.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-pause-replay",
        action="pause",
    )
    assert replayed == paused

    with pytest.raises(ValidationFailure, match="Unsupported"):
        service.transition_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=paused.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-unsupported-transition",
            action="archive",
        )
    with pytest.raises(ValidationFailure, match="Only a recording"):
        service.transition_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=paused.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-pause-paused",
            action="pause",
        )

    resumed = service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=paused.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-resume-once",
        action="resume",
    )
    with pytest.raises(ValidationFailure, match="Only a paused"):
        service.transition_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=resumed.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-resume-recording",
            action="resume",
        )

    cancelled = service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=resumed.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-cancel-once",
        action="cancel",
    )
    cancelled_again = service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=cancelled.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-cancel-terminal",
        action="cancel",
    )
    assert cancelled_again.status == "cancelled"

    with pytest.raises(ValidationFailure, match="Only an active"):
        service.transition_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=cancelled_again.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-finish-cancelled",
            action="finish",
        )


def test_brain_dump_commit_replay_invalid_state_and_deleted_proposals(
    service: TaskService,
) -> None:
    operation = service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": False}}
        ),
        owner_id=OWNER,
        idempotency_key="brain-dump-commit-start",
    )
    with pytest.raises(ValidationFailure, match="awaiting confirmation"):
        service.commit_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=operation.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-commit-too-soon",
        )

    operation = service.append_brain_dump_transcript(
        operation.id,
        BrainDumpTranscriptAppendRequest.model_validate(
            {"segments": [{"sequence": 1, "text": "Book dentist. Call bank.", "stability": "stable"}]}
        ),
        owner_id=OWNER,
        idempotency_key="brain-dump-commit-segments",
    )
    deleted = service.update_brain_dump_proposal(
        operation.id,
        operation.proposals[0].id,
        BrainDumpProposalUpdateRequest(deleted=True, expected_revision=operation.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-delete-first-proposal",
    )
    finished = service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=deleted.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-finish-before-commit",
        action="finish",
    )
    committed = service.commit_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=finished.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-commit-replay",
    )
    replayed = service.commit_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=finished.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-commit-replay",
    )

    assert replayed == committed
    assert committed.status == "completed"
    assert len(committed.committed_task_ids) == 1


def test_idempotent_result_replay_repairs_stale_canonical_records(
    service: TaskService,
) -> None:
    project = _make_project(service, name="Replay Project", key="replay-project-old")
    newer_project = project.model_copy(update={"name": "Replay Project v2", "revision": 2})
    assert service._project_result(
        IdempotencyRecord(
            key="project-replay-newer",
            command="update_project",
            request_hash="hash",
            resource_id=project.id,
            response_body=newer_project.model_dump(mode="json"),
            created_at=utcnow(),
        ),
        owner_id=OWNER,
    ).revision == 2

    tag = _make_tag(service, name="replay-tag", key="replay-tag-old")
    newer_tag = tag.model_copy(update={"name": "replay-tag-v2", "revision": 2})
    assert service._tag_result(
        IdempotencyRecord(
            key="tag-replay-newer",
            command="update_tag",
            request_hash="hash",
            resource_id=tag.id,
            response_body=newer_tag.model_dump(mode="json"),
            created_at=utcnow(),
        ),
        owner_id=OWNER,
    ).revision == 2

    task = _make_task(service, title="Replay task", key="replay-task-old")
    newer_task = task.model_copy(update={"title": "Replay task v2", "revision": 2})
    assert service._task_result(
        IdempotencyRecord(
            key="task-replay-newer",
            command="update_task",
            request_hash="hash",
            resource_id=task.id,
            response_body=newer_task.model_dump(mode="json"),
            created_at=utcnow(),
        ),
        owner_id=OWNER,
    ).revision == 2

    operation = service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": False}}
        ),
        owner_id=OWNER,
        idempotency_key="replay-operation-old",
    )
    newer_operation = operation.model_copy(update={"status": "paused", "revision": 2})
    assert service._brain_dump_operation_result(
        IdempotencyRecord(
            key="operation-replay-newer",
            command="brain_dump_pause",
            request_hash="hash",
            resource_id=operation.id,
            response_body=newer_operation.model_dump(mode="json"),
            created_at=utcnow(),
        ),
        owner_id=OWNER,
    ).revision == 2


def test_brain_dump_title_extraction_ignores_blank_and_duplicate_items() -> None:
    assert TaskService._extract_task_titles("   \n  ") == []
    assert TaskService._extract_task_titles("call bank. Call bank.") == ["Call bank"]


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
