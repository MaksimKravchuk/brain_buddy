"""Branch-coverage regression tests for the native GTD task module.

These tests exercise behavior paths that the existing API-level suite did not
reach: repository ``NotFoundError``/``ConflictError`` branches, idempotency
mismatch conflicts, cursor validation, task-state filter/cursor branches,
provenance rejection, and the active-reference validation paths.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from app.core.config import VoiceAudioLimits
from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.modules.tasks import TaskRepository, TaskService
from app.modules.tasks.domain import (
    IdempotencyRecord,
    ProjectDocument,
    TagDocument,
    TaskDocument,
)
from app.schemas.tasks import (
    BrainDumpOperationStartRequest,
    BrainDumpProposalUpdateRequest,
    BrainDumpTranscriptAppendRequest,
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
from app.workflows.voice_brain_dump.domain import (
    BrainDumpProviderRunDocument,
    BrainDumpTranscriptSegmentDocument,
)
from app.workflows.voice_brain_dump.repository import OperationRepository
from app.workflows.voice_brain_dump.service import VoiceBrainDumpService
from app.workflows.voice_brain_dump.task_port import InProcessTaskPort

OWNER = "user_branch_owner"


@pytest.fixture()
def service(data_dir: Path) -> TaskService:
    repository = TaskRepository(data_dir)
    return TaskService(repository)


@pytest.fixture()
def voice_service(data_dir: Path) -> VoiceBrainDumpService:
    return _voice_service(data_dir)


def _voice_service(data_dir: Path, **kwargs: object) -> VoiceBrainDumpService:
    task_service = TaskService(TaskRepository(data_dir))
    return VoiceBrainDumpService(
        OperationRepository(data_dir),
        audio_limits=VoiceAudioLimits(
            allowed_mime_types=frozenset({"audio/x-brain-buddy-test-text"})
        ),
        task_port=InProcessTaskPort(task_service.create_native_inbox_task),
        **kwargs,
    )


def _make_project(
    service: TaskService, *, name: str = "Health", key: str = "p"
) -> ProjectDocument:
    return service.create_project(
        ProjectCreateRequest(name=name), owner_id=OWNER, idempotency_key=key
    )


def _make_tag(
    service: TaskService, *, name: str = "phone", key: str = "tag"
) -> TagDocument:
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


def test_repository_create_tag_conflict_when_record_exists(
    service: TaskService,
) -> None:
    tag = _make_tag(service, key="dup-tag")
    with pytest.raises(ConflictError):
        service.task_repo.create_tag(tag)


def test_repository_create_task_conflict_when_file_exists(service: TaskService) -> None:
    task = _make_task(service, key="dup-task")
    with pytest.raises(ConflictError):
        service.task_repo.create(task)


def test_repository_lists_empty_projects_tags_tasks_for_missing_owner_dir(
    service: TaskService,
) -> None:
    assert service.task_repo.list_projects_for_owner(owner_id="never-seen") == []
    assert service.task_repo.list_tags_for_owner(owner_id="never-seen") == []
    assert service.task_repo.list_for_owner(owner_id="never-seen") == []


def test_repository_get_project_tag_task_raise_not_found_for_missing_records(
    service: TaskService,
) -> None:
    with pytest.raises(NotFoundError):
        service.task_repo.get_project_for_owner("missing", owner_id=OWNER)
    with pytest.raises(NotFoundError):
        service.task_repo.get_tag_for_owner("missing", owner_id=OWNER)
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
        service.create_tag(
            TagCreateRequest(name="Tag"),
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


# --- active-reference validation branches ---------------------------------


def test_create_task_rejects_inactive_project(service: TaskService) -> None:
    project = _make_project(service, key="archived-project")
    service.archive_project(
        project.id,
        ExpectedRevisionRequest(expected_revision=1),
        owner_id=OWNER,
        idempotency_key="archive-inactive-project",
    )

    with pytest.raises(ValidationFailure, match="project must be active"):
        _make_task(service, key="inactive-project-task", project_id=project.id)


def test_create_task_rejects_duplicate_context_ids_alias(service: TaskService) -> None:
    tag = _make_tag(service, key="dup-tag-task")

    with pytest.raises(ValidationFailure, match="duplicates"):
        _make_task(service, key="dup-tags-task", context_ids=[tag.id, tag.id])


def test_create_task_rejects_deleted_tag(service: TaskService) -> None:
    tag = _make_tag(service, key="deleted-tag")
    service.delete_tag(
        tag.id,
        ExpectedRevisionRequest(expected_revision=1),
        owner_id=OWNER,
        idempotency_key="delete-inactive-tag",
    )

    with pytest.raises(ValidationFailure, match="must be active"):
        _make_task(service, key="deleted-tag-task", tag_ids=[tag.id])


def test_update_task_rejects_inactive_project_on_reassignment(
    service: TaskService,
) -> None:
    project = _make_project(service, key="update-inactive-project")
    task = _make_task(service, key="update-inactive-project-task")
    service.archive_project(
        project.id,
        ExpectedRevisionRequest(expected_revision=1),
        owner_id=OWNER,
        idempotency_key="archive-update-inactive-project",
    )

    with pytest.raises(ValidationFailure, match="project must be active"):
        service.update_task(
            task.id,
            TaskUpdateRequest(project_id=project.id, expected_revision=1),
            owner_id=OWNER,
            idempotency_key="update-inactive-project-attempt",
        )


def test_update_task_rejects_duplicate_context_ids_alias(service: TaskService) -> None:
    tag = _make_tag(service, key="update-dup-tag")
    task = _make_task(service, key="update-dup-tag-task")

    with pytest.raises(ValidationFailure, match="duplicates"):
        service.update_task(
            task.id,
            TaskUpdateRequest(context_ids=[tag.id, tag.id], expected_revision=1),
            owner_id=OWNER,
            idempotency_key="update-dup-tags",
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
    tag = _make_tag(service, key="restore-tag")
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
    service.task_repo.context_path(OWNER, tag.id).unlink()
    service.task_repo.subtask_path(OWNER, task.id, subtask.id).unlink()
    service.task_repo.comment_path(OWNER, task.id, comment.id).unlink()

    service._reconcile_idempotent_results(owner_id=OWNER)

    assert service.get_project(project.id, owner_id=OWNER).name == project.name
    assert service.get_tag(tag.id, owner_id=OWNER).name == tag.name
    restored_task, restored_subtasks, restored_comments = service.get_task_detail(
        task.id, owner_id=OWNER
    )
    assert restored_task.id == task.id
    assert [item.id for item in restored_subtasks] == [subtask.id]
    assert [item.id for item in restored_comments] == [comment.id]


def test_brain_dump_operation_uses_sqlite_canonical_when_json_mirror_is_missing(
    data_dir: Path,
) -> None:
    voice_service = _voice_service(data_dir)
    operation = voice_service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": False}}
        ),
        owner_id=OWNER,
        idempotency_key="sqlite-canonical-brain-dump",
    )
    voice_service.operation_repo.brain_dump_operation_path(OWNER, operation.id).unlink()

    reloaded = _voice_service(data_dir)

    assert reloaded.get_brain_dump_operation(operation.id, owner_id=OWNER) == operation


def test_brain_dump_append_retry_after_idempotency_crash_does_not_advance_revision(
    monkeypatch: pytest.MonkeyPatch, voice_service: VoiceBrainDumpService
) -> None:
    operation = voice_service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": True}}
        ),
        owner_id=OWNER,
        idempotency_key="crash-start-brain-dump",
    )
    original_store_idempotency = voice_service._store_idempotency
    calls = 0

    def fail_once_after_operation_write(**kwargs: object) -> None:
        nonlocal calls
        if kwargs["command"] == f"brain_dump_append:{operation.id}" and calls == 0:
            calls += 1
            raise RuntimeError("simulated crash after brain dump write")
        original_store_idempotency(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(voice_service, "_store_idempotency", fail_once_after_operation_write)
    payload = BrainDumpTranscriptAppendRequest.model_validate(
        {"segments": [{"sequence": 1, "text": "Pay VAT.", "stability": "stable"}]}
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        voice_service.append_brain_dump_transcript(
            operation.id,
            payload,
            owner_id=OWNER,
            idempotency_key="crash-append-brain-dump",
        )

    monkeypatch.setattr(voice_service, "_store_idempotency", original_store_idempotency)
    replayed = voice_service.append_brain_dump_transcript(
        operation.id,
        payload,
        owner_id=OWNER,
        idempotency_key="crash-append-brain-dump",
    )

    assert replayed.revision == operation.revision + 1
    assert [segment.sequence for segment in replayed.segments] == [1]


def test_brain_dump_start_replay_and_consent_validation(
    voice_service: VoiceBrainDumpService,
) -> None:
    payload = BrainDumpOperationStartRequest.model_validate(
        {"consent": {"microphone": True, "external_processing_allowed": False}}
    )

    started = voice_service.start_brain_dump_operation(
        payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-start-replay",
    )
    replayed = voice_service.start_brain_dump_operation(
        payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-start-replay",
    )

    assert replayed == started

    with pytest.raises(ValidationFailure, match="Microphone consent"):
        voice_service.start_brain_dump_operation(
            BrainDumpOperationStartRequest.model_validate(
                {"consent": {"microphone": False, "external_processing_allowed": False}}
            ),
            owner_id=OWNER,
            idempotency_key="brain-dump-no-mic-consent",
        )


def test_brain_dump_append_replay_state_and_duplicate_segment_branches(
    voice_service: VoiceBrainDumpService,
) -> None:
    start_payload = BrainDumpOperationStartRequest.model_validate(
        {"consent": {"microphone": True, "external_processing_allowed": True}}
    )
    append_payload = BrainDumpTranscriptAppendRequest.model_validate(
        {"segments": [{"sequence": 1, "text": "Pay VAT.", "stability": "stable"}]}
    )
    operation = voice_service.start_brain_dump_operation(
        start_payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-append-branches-start",
    )

    appended = voice_service.append_brain_dump_transcript(
        operation.id,
        append_payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-append-replay",
    )
    replayed = voice_service.append_brain_dump_transcript(
        operation.id,
        append_payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-append-replay",
    )

    assert replayed == appended

    duplicate = voice_service.append_brain_dump_transcript(
        operation.id,
        append_payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-append-duplicate-same",
    )
    assert duplicate.segments == appended.segments

    with pytest.raises(ConflictError, match="Brain dump segment"):
        voice_service.append_brain_dump_transcript(
            operation.id,
            BrainDumpTranscriptAppendRequest.model_validate(
                {"segments": [{"sequence": 1, "text": "Pay taxes.", "stability": "stable"}]}
            ),
            owner_id=OWNER,
            idempotency_key="brain-dump-append-duplicate-conflict",
        )

    cancelled = voice_service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=duplicate.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-cancel-before-append",
        action="cancel",
    )
    with pytest.raises(ValidationFailure, match="Transcript can only"):
        voice_service.append_brain_dump_transcript(
            cancelled.id,
            BrainDumpTranscriptAppendRequest.model_validate(
                {"segments": [{"sequence": 2, "text": "Call bank.", "stability": "stable"}]}
            ),
            owner_id=OWNER,
            idempotency_key="brain-dump-append-cancelled",
        )


def test_brain_dump_proposal_update_replay_not_found_and_invalid_state(
    voice_service: VoiceBrainDumpService,
) -> None:
    operation = voice_service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": True}}
        ),
        owner_id=OWNER,
        idempotency_key="brain-dump-proposal-start",
    )
    operation = voice_service.append_brain_dump_transcript(
        operation.id,
        BrainDumpTranscriptAppendRequest.model_validate(
            {"segments": [{"sequence": 1, "text": "Email broker.", "stability": "stable"}]}
        ),
        owner_id=OWNER,
        idempotency_key="brain-dump-proposal-segment",
    )
    proposal_id = operation.proposals[0].id
    payload = BrainDumpProposalUpdateRequest(title="Email mortgage broker", expected_revision=operation.revision)

    updated = voice_service.update_brain_dump_proposal(
        operation.id,
        proposal_id,
        payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-proposal-update-replay",
    )
    replayed = voice_service.update_brain_dump_proposal(
        operation.id,
        proposal_id,
        payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-proposal-update-replay",
    )
    assert replayed == updated

    with pytest.raises(NotFoundError, match="Brain dump proposal"):
        voice_service.update_brain_dump_proposal(
            operation.id,
            "missing-proposal",
            BrainDumpProposalUpdateRequest(deleted=True, expected_revision=updated.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-proposal-missing",
        )

    cancelled = voice_service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=updated.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-proposal-cancel",
        action="cancel",
    )
    with pytest.raises(ValidationFailure, match="Proposal cannot"):
        voice_service.update_brain_dump_proposal(
            cancelled.id,
            proposal_id,
            BrainDumpProposalUpdateRequest(title="Ignored", expected_revision=cancelled.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-proposal-cancelled-edit",
        )


def test_brain_dump_transition_validation_and_replay_branches(
    voice_service: VoiceBrainDumpService,
) -> None:
    start_payload = BrainDumpOperationStartRequest.model_validate(
        {"consent": {"microphone": True, "external_processing_allowed": False}}
    )
    operation = voice_service.start_brain_dump_operation(
        start_payload,
        owner_id=OWNER,
        idempotency_key="brain-dump-transition-start",
    )

    paused = voice_service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=operation.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-pause-replay",
        action="pause",
    )
    replayed = voice_service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=operation.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-pause-replay",
        action="pause",
    )
    assert replayed == paused

    with pytest.raises(ValidationFailure, match="Unsupported"):
        voice_service.transition_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=paused.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-unsupported-transition",
            action="archive",
        )
    with pytest.raises(ValidationFailure, match="Only a recording"):
        voice_service.transition_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=paused.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-pause-paused",
            action="pause",
        )

    resumed = voice_service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=paused.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-resume-once",
        action="resume",
    )
    with pytest.raises(ValidationFailure, match="Only a paused"):
        voice_service.transition_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=resumed.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-resume-recording",
            action="resume",
        )

    cancelled = voice_service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=resumed.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-cancel-once",
        action="cancel",
    )
    cancelled_again = voice_service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=cancelled.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-cancel-terminal",
        action="cancel",
    )
    assert cancelled_again.status == "cancelled"

    with pytest.raises(ValidationFailure, match="Only an active"):
        voice_service.transition_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=cancelled_again.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-finish-cancelled",
            action="finish",
        )


def test_brain_dump_commit_replay_invalid_state_and_deleted_proposals(
    voice_service: VoiceBrainDumpService,
) -> None:
    operation = voice_service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": True}}
        ),
        owner_id=OWNER,
        idempotency_key="brain-dump-commit-start",
    )
    with pytest.raises(ValidationFailure, match="awaiting confirmation"):
        voice_service.commit_brain_dump_operation(
            operation.id,
            ExpectedRevisionRequest(expected_revision=operation.revision),
            owner_id=OWNER,
            idempotency_key="brain-dump-commit-too-soon",
        )

    operation = voice_service.append_brain_dump_transcript(
        operation.id,
        BrainDumpTranscriptAppendRequest.model_validate(
            {"segments": [{"sequence": 1, "text": "Book dentist. Call bank.", "stability": "stable"}]}
        ),
        owner_id=OWNER,
        idempotency_key="brain-dump-commit-segments",
    )
    deleted = voice_service.update_brain_dump_proposal(
        operation.id,
        operation.proposals[0].id,
        BrainDumpProposalUpdateRequest(deleted=True, expected_revision=operation.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-delete-first-proposal",
    )
    finished = voice_service.transition_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=deleted.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-finish-before-commit",
        action="finish",
    )
    # Commit requires a frozen, reconciled batch (see
    # ``TaskService._has_frozen_reconciled_batch``) AND every surviving
    # proposal to actually carry reconciler/user affirmation (see the
    # ``BRAIN_DUMP_PROPOSAL_NOT_RECONCILED`` gate in
    # ``commit_brain_dump_operation``); this unit test exercises commit
    # replay/idempotency directly against the repository rather than through
    # a real sealed-audio pipeline, so record the checkpoint and per-proposal
    # status that a successful seal+accurate-STT+reconciler run would have
    # left behind.
    finished = finished.model_copy(
        update={
            "sealed_manifest_hash": "0" * 64,
            "reconciliation_quality": "accurate",
            "proposals": [
                proposal.model_copy(update={"status": "reconciled"})
                for proposal in finished.proposals
            ],
            "provider_runs": [
                BrainDumpProviderRunDocument(
                    id="provider_run_test_reconciled",
                    role="reconciler",
                    status="succeeded",
                    input_hash="0" * 64,
                    checkpoint="reconciled",
                    attempt=1,
                    recovery_count=0,
                    created_at=finished.updated_at,
                    updated_at=finished.updated_at,
                )
            ],
            "revision": finished.revision + 1,
        }
    )
    voice_service.operation_repo.save_brain_dump_operation(finished)
    committed = voice_service.commit_brain_dump_operation(
        operation.id,
        ExpectedRevisionRequest(expected_revision=finished.revision),
        owner_id=OWNER,
        idempotency_key="brain-dump-commit-replay",
    )
    replayed = voice_service.commit_brain_dump_operation(
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

def test_brain_dump_title_extraction_ignores_blank_and_duplicate_items() -> None:
    assert VoiceBrainDumpService._extract_task_titles("   \n  ") == []
    assert VoiceBrainDumpService._extract_task_titles("call bank. Call bank.") == [
        "Call bank"
    ]


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
            "tag_id": None,
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
            tag_id=None,
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
            "tag_id": None,
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
            tag_id=None,
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
            "tag_id": None,
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
            tag_id=None,
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
            tag_id=None,
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
        tag_id=None,
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
        tag_id=None,
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
        tag_id=None,
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
            tag_id=None,
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
        tag_id=None,
        unassigned_project=False,
        include_completed=False,
        cursor=None,
        limit=10,
    )
    assert counts == {"inbox": 0, "next": 1, "waiting": 0, "someday": 0}


def test_list_tasks_counts_scope_by_tag(service: TaskService) -> None:
    tag = _make_tag(service, key="counts-tag")
    _make_task(
        service,
        key="counts-with-tag",
        tag_ids=[tag.id],
        state="waiting",
        waiting_for="Dr. Smith",
    )
    _make_task(service, key="counts-no-tag", state="inbox")

    _, _, _, counts = service.list_tasks(
        owner_id=OWNER,
        state=None,
        project_id=None,
        tag_id=tag.id,
        unassigned_project=False,
        include_completed=False,
        cursor=None,
        limit=10,
    )
    assert counts == {"inbox": 0, "next": 0, "waiting": 1, "someday": 0}


def test_list_tasks_validates_project_and_tag_existence(
    service: TaskService,
) -> None:
    with pytest.raises(NotFoundError):
        service.list_tasks(
            owner_id=OWNER,
            state=None,
            project_id="missing-project",
            tag_id=None,
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
            tag_id="missing-tag",
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
        tag_id=None,
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
        tag_id=None,
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


# --- project/tag listing filters inactive records --------------------------


def test_list_projects_filters_inactive_records(service: TaskService) -> None:
    active = _make_project(service, name="Active", key="active-project")
    archived = _make_project(service, name="Archived", key="archived-project-list")
    service.archive_project(
        archived.id,
        ExpectedRevisionRequest(expected_revision=1),
        owner_id=OWNER,
        idempotency_key="archive-project-for-list",
    )

    listed = service.list_projects(owner_id=OWNER)
    assert [project.id for project in listed] == [active.id]


def test_list_tags_filters_inactive_records(service: TaskService) -> None:
    active = _make_tag(service, name="active", key="active-tag")
    deleted = _make_tag(service, name="deleted", key="deleted-tag-list")
    service.delete_tag(
        deleted.id,
        ExpectedRevisionRequest(expected_revision=1),
        owner_id=OWNER,
        idempotency_key="delete-tag-for-list",
    )

    listed = service.list_tags(owner_id=OWNER)
    assert [tag.id for tag in listed] == [active.id]


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


# --- next_order_key --------------------------------------------------------


def test_next_order_key_increments_per_state(service: TaskService) -> None:
    first_inbox = _make_task(service, key="order-inbox-one", state="inbox")
    second_inbox = _make_task(service, key="order-inbox-two", state="inbox")
    assert first_inbox.order_key == 0
    assert second_inbox.order_key == 1
    first_next = _make_task(service, key="order-next-one", state="next")
    assert first_next.order_key == 0


# --- allowed_external_provider_categories -----------------------------------


def _start_and_upload(
    voice_service: VoiceBrainDumpService, *, key_prefix: str, provider: str = "openai"
) -> None:
    operation = voice_service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {
                "consent": {
                    "microphone": True,
                    "external_processing_allowed": True,
                    "provider": provider,
                }
            }
        ),
        owner_id=OWNER,
        idempotency_key=f"{key_prefix}-start",
    )
    voice_service.upload_brain_dump_audio_chunk(
        operation.id,
        0,
        b"audio",
        owner_id=OWNER,
        content_sha256=hashlib.sha256(b"audio").hexdigest(),
        content_type="audio/x-brain-buddy-test-text",
    )


def test_unconfigured_allowlist_defaults_to_openai_for_unit_tests(
    data_dir: Path,
) -> None:
    """An unconfigured workflow service keeps the test-only openai default."""

    voice_service = _voice_service(data_dir)
    assert voice_service.allowed_external_provider_categories == frozenset({"openai"})
    _start_and_upload(voice_service, key_prefix="default-allowlist")


def test_explicit_empty_allowlist_fails_closed_even_for_openai(
    data_dir: Path,
) -> None:
    """An *explicitly* configured empty allowlist -- e.g. a deployment with
    no external voice provider wired up -- must reject every provider name,
    including "openai". This must not silently fall back to the unit-test
    default the way a falsy-``or`` check would."""

    voice_service = _voice_service(
        data_dir, allowed_external_provider_categories=frozenset()
    )
    assert voice_service.allowed_external_provider_categories == frozenset()

    with pytest.raises(ValidationFailure, match="AUDIO_UPLOAD_PROVIDER_CONSENT_REQUIRED"):
        _start_and_upload(voice_service, key_prefix="empty-allowlist")


# --- run_due_brain_dump_provider_runs lease claim time -----------------------


def test_run_due_provider_runs_claims_a_fresh_lease_per_candidate(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 2 (runner lease): ``run_due_brain_dump_provider_runs`` visits up
    to ``limit`` candidates in one call. The claim time for each candidate's
    new lease must be read inside *that* candidate's own owner lock, not
    once before the whole loop -- otherwise a slow earlier candidate lets
    wall-clock time drift far past the loop-start timestamp, and every later
    candidate's freshly claimed lease is stamped as though claimed long ago.

    This seeds two owners' operations with a due ``accurate_stt`` run. The
    first owner's provider call advances a controlled clock by 1000s to
    simulate slow processing; the second owner's freshly claimed lease must
    reflect that advanced clock, not the loop-start time.
    """

    from datetime import timedelta

    from app.utils import time as time_module
    from app.workflows.voice_brain_dump.domain import TranscriptHypothesis
    from app.workflows.voice_brain_dump.providers import SttResult

    start = time_module.utcnow()
    clock = {"now": start}

    def fake_utcnow() -> object:
        return clock["now"]

    monkeypatch.setattr("app.workflows.voice_brain_dump.service.utcnow", fake_utcnow)

    class SlowFirstCallAccurateStt:
        provider_name = "deterministic"
        requires_external_processing = False

        def __init__(self) -> None:
            self.calls = 0

        def transcribe_sealed_audio(self, request):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 1:
                # Simulate the first candidate's provider call taking a long
                # time while it runs outside any owner lock.
                clock["now"] = clock["now"] + timedelta(seconds=1000)
            return SttResult(
                role="accurate",
                provider=self.provider_name,
                input_hash="0" * 64,
                segments=[
                    TranscriptHypothesis(
                        id=f"segment_{request.operation_id}_{self.calls}",
                        sequence=1,
                        start_ms=0,
                        end_ms=500,
                        text="Buy milk",
                        stability="stable",
                        provider_role="accurate",
                    )
                ],
            )

    repository = OperationRepository(data_dir)
    task_service = TaskService(TaskRepository(data_dir))
    lease_seconds = 30.0
    voice_service = VoiceBrainDumpService(
        repository,
        task_port=InProcessTaskPort(task_service.create_native_inbox_task),
        accurate_stt=SlowFirstCallAccurateStt(),
        provider_run_lease_seconds=lease_seconds,
    )

    claim_snapshots: dict[str, list[BrainDumpProviderRunDocument]] = {
        "owner_lease_a": [],
        "owner_lease_b": [],
    }
    original_save = repository.save_brain_dump_operation

    def spying_save(operation):  # type: ignore[no-untyped-def]
        if operation.owner_id in claim_snapshots and operation.provider_runs:
            last = operation.provider_runs[-1]
            if last.status == "running":
                claim_snapshots[operation.owner_id].append(last)
        return original_save(operation)

    monkeypatch.setattr(repository, "save_brain_dump_operation", spying_save)

    def _seed_due_operation(owner_id: str) -> None:
        operation = voice_service.start_brain_dump_operation(
            BrainDumpOperationStartRequest.model_validate(
                {"consent": {"microphone": True, "external_processing_allowed": False}}
            ),
            owner_id=owner_id,
            idempotency_key=f"{owner_id}-start",
        )
        pending_run = BrainDumpProviderRunDocument(
            id=f"{owner_id}-run",
            role="accurate_stt",
            status="pending",
            input_hash="0" * 64,
            checkpoint="sealed",
            attempt=1,
            recovery_count=0,
            created_at=clock["now"],
            updated_at=clock["now"],
        )
        seeded = operation.model_copy(
            update={
                "status": "accurate_transcribing",
                "provider_runs": [pending_run],
                "media_ref": f"media_{operation.id}",
                "revision": operation.revision + 1,
            }
        )
        repository.save_brain_dump_operation(seeded)

    _seed_due_operation("owner_lease_a")
    _seed_due_operation("owner_lease_b")

    advanced = voice_service.run_due_brain_dump_provider_runs(limit=50)

    # Both accurate-STT claims and their immediately queued dependent
    # reconciler claims are advanced within the same bounded invocation.
    assert advanced == 4
    assert len(claim_snapshots["owner_lease_a"]) == 2
    assert len(claim_snapshots["owner_lease_b"]) == 2

    claim_a = claim_snapshots["owner_lease_a"][0]
    claim_b = claim_snapshots["owner_lease_b"][0]

    # The first candidate claims before the clock advances.
    assert claim_a.lease_expires_at == start + timedelta(seconds=lease_seconds)

    # The second candidate's lease must be stamped from the claim time taken
    # inside ITS OWN lock -- after the first candidate's slow processing --
    # not from the stale loop-start ``now``. A stale claim would wrongly
    # produce ``start + lease_seconds`` here too, leaving the lease already
    # expired (1000s in the past) the instant it is persisted.
    assert claim_b.lease_expires_at == start + timedelta(seconds=1000 + lease_seconds)
    assert claim_b.created_at == start + timedelta(seconds=1000)


# --- reconciler cost admission ----------------------------------------------


class _CountingReconciler:
    provider_id = "deterministic"
    requires_external_processing = False
    max_cost_usd_per_operation = 0.5

    def __init__(self) -> None:
        self.calls = 0

    def reconcile(self, request):  # type: ignore[no-untyped-def]
        from app.workflows.voice_brain_dump.providers import ReconcileResult

        self.calls += 1
        return ReconcileResult(input_hash="0" * 64, patches=[], estimated_cost_usd=0.1)


def test_reconciler_admission_accounts_for_a_crashed_reconciler_reservation(
    data_dir: Path,
) -> None:
    """Item 4 (costs): reconciler admission must include outstanding
    unknown/crashed reserved provider costs -- e.g. a prior reconciler
    attempt whose process died mid-call, leaving its reservation
    unresolved -- exactly like accurate-STT admission already does.

    Before this fix, ``_reconcile_accurate_checkpoint`` summed only
    ``estimated``/``consumed`` cost across prior runs and silently dropped
    any outstanding ``reserved_cost_usd`` still held by a "running" prior
    run, letting a new reconciler attempt be wrongly admitted -- and the
    provider wrongly called -- even though the operation's true committed
    exposure (0.3 accurate spend + 0.5 crashed reservation + 0.5 worst-case
    next call = 1.3) already exceeds its 1.0 cap.
    """

    repository = OperationRepository(data_dir)
    task_service = TaskService(TaskRepository(data_dir))
    reconciler = _CountingReconciler()
    voice_service = VoiceBrainDumpService(
        repository,
        task_port=InProcessTaskPort(task_service.create_native_inbox_task),
        text_reconciler=reconciler,
        max_cumulative_cost_usd_per_operation=1.0,
    )

    operation = voice_service.start_brain_dump_operation(
        BrainDumpOperationStartRequest.model_validate(
            {"consent": {"microphone": True, "external_processing_allowed": False}}
        ),
        owner_id=OWNER,
        idempotency_key="crashed-reservation-start",
    )
    now = utcnow()
    accurate_segment = BrainDumpTranscriptSegmentDocument(
        id="segment_accurate_crash",
        sequence=1,
        text="Buy milk",
        stability="stable",
        start_ms=0,
        end_ms=500,
        provider_role="accurate",
        created_at=now,
    )
    accurate_run = BrainDumpProviderRunDocument(
        id="run_accurate_succeeded",
        role="accurate_stt",
        status="succeeded",
        input_hash="0" * 64,
        checkpoint="accurate_transcribed",
        attempt=1,
        recovery_count=0,
        estimated_cost_usd=0.3,
        consumed_cost_usd=0.3,
        reserved_cost_usd=0.0,
        output_segment_ids=[accurate_segment.id],
        created_at=now,
        updated_at=now,
    )
    # A previous reconciler attempt that reserved budget and then never
    # resolved -- e.g. the worker process died mid-call -- so it is still
    # "running" with no estimated/consumed cost recorded.
    crashed_reconciler_run = BrainDumpProviderRunDocument(
        id="run_reconciler_crashed",
        role="reconciler",
        status="running",
        input_hash="0" * 64,
        checkpoint="accurate_transcribed",
        attempt=1,
        recovery_count=0,
        estimated_cost_usd=0.0,
        consumed_cost_usd=0.0,
        reserved_cost_usd=0.5,
        created_at=now,
        updated_at=now,
    )
    pending_reconciler_run = BrainDumpProviderRunDocument(
        id="run_reconciler_new",
        role="reconciler",
        status="pending",
        input_hash="0" * 64,
        checkpoint="accurate_transcribed",
        attempt=1,
        recovery_count=0,
        reserved_cost_usd=0.5,
        created_at=now,
        updated_at=now,
    )
    seeded = operation.model_copy(
        update={
            "status": "reconciling",
            "segments": [accurate_segment],
            "provider_runs": [
                accurate_run,
                crashed_reconciler_run,
                pending_reconciler_run,
            ],
            "revision": operation.revision + 1,
        }
    )
    repository.save_brain_dump_operation(seeded)

    advanced = voice_service.run_due_brain_dump_provider_runs(limit=50)

    assert advanced == 1
    assert reconciler.calls == 0, "provider must never be called once admission fails"
    final = voice_service.get_brain_dump_operation(operation.id, owner_id=OWNER)
    assert final.status == "terminal_error"
    assert final.provider_runs[-1].error_code == "OPERATION_COST_BUDGET_EXCEEDED"
