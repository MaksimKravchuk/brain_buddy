"""T027 legacy create-tag receipt, adoption and atomic feed behavior."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path
from time import perf_counter_ns

import allure
import pytest

from app.exceptions import (
    ConflictError,
    IdempotencyReceiptUnavailableError,
    NotFoundError,
    ValidationFailure,
)
from app.modules.tasks import TaskRepository, TaskService
from app.modules.tasks.domain import IdempotencyRecord
from app.modules.tasks.jobs import JobRepository
from app.modules.tasks.rust_adapter import DomainRefusal, RustCore
from app.modules.tasks.rust_task_facade import RustTaskFacade
from app.modules.tasks.sync.receipts import (
    ReceiptStore,
    ScopeAuthority,
    SyncCommandError,
)
from app.modules.tasks.sync.unit_of_work import TaskUnitOfWork
from app.schemas.tasks import (
    ExpectedRevisionRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    SmartAddClassificationRef,
    SmartAddTaskCreateRequest,
    TagCreateRequest,
    TagUpdateRequest,
    TaskCommentCreateRequest,
    TaskCommentUpdateRequest,
    TaskCreateRequest,
    TaskSubtaskCreateRequest,
    TaskSubtaskTransitionRequest,
    TaskSubtaskUpdateRequest,
    TaskTransitionRequest,
    TaskUpdateRequest,
)
from app.utils.idempotency import idempotency_key_digest

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Durable task synchronization"),
    allure.story("Legacy create-tag receipts"),
]

OWNER = "user_legacy_sync"
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _measure_fast_allure_steps(monkeypatch):
    # Allure stores millisecond timestamps; a real, sub-ms receipt replay can
    # otherwise be misclassified as an empty step by the taxonomy validator.
    original_step = allure.step

    @contextmanager
    def measured_step(title):
        started = perf_counter_ns()
        with original_step(title):
            yield
            elapsed_ns = perf_counter_ns() - started
            if elapsed_ns < 2_000_000:
                allure.attach(str(elapsed_ns), name="Step elapsed nanoseconds")

    monkeypatch.setattr(allure, "step", measured_step)


@pytest.fixture
def legacy_service(data_dir: Path):
    repo = TaskRepository(data_dir)
    units = TaskUnitOfWork(repo, JobRepository(repo.db_path))
    core = RustCore()
    enabled = [True]
    clock = [NOW]
    service = TaskService(
        repo,
        clock=lambda: clock[0],
        rust_facade=RustTaskFacade(core, repo),
        rust_core_enabled=lambda _owner: enabled[0],
        command_receipts=ReceiptStore(core),
        task_unit_of_work=units,
        task_sync_authority=lambda unit: ScopeAuthority(
            unit.owner_id, "server-1", "feed-1", "access-1", "sqlite-1"
        ),
    )
    yield service, repo, enabled, clock
    core.close()


def _count(repo: TaskRepository, table: str) -> int:
    with sqlite3.connect(repo.db_path) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608


def _receipt_command_id(repo: TaskRepository, key: str) -> str:
    with sqlite3.connect(repo.db_path) as conn:
        row = conn.execute(
            "SELECT command_id FROM sync_legacy_keys WHERE owner_id = ? AND key_digest = ?",
            (OWNER, idempotency_key_digest(key)),
        ).fetchone()
    assert row is not None
    return row[0]


def _corrupt_receipt_binding(repo: TaskRepository, key: str, corruption: str) -> None:
    with sqlite3.connect(repo.db_path) as conn:
        command_id = _receipt_command_id(repo, key)
        row = conn.execute(
            "SELECT metadata FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        ).fetchone()
        assert row is not None
        metadata = json.loads(row[0])
        bindings = metadata["id_bindings"]
        if corruption == "missing":
            metadata["id_bindings"] = []
        elif corruption == "wrong_id":
            bindings[0]["entity_id"] = "other_entity"
        elif corruption == "duplicate":
            bindings.append(bindings[0].copy())
        elif corruption == "missing_field":
            bindings[0].pop("alias_id")
        elif corruption == "bad_index":
            bindings.append(
                {
                    "entity_type": "tag",
                    "alias_id": "smart_add_tag_bad",
                    "entity_id": "tag_x",
                }
            )
        elif corruption == "bad_type":
            bindings.append(
                {"entity_type": "tag", "alias_id": None, "entity_id": "tag_x"}
            )
        elif corruption == "not_a_list":
            metadata["id_bindings"] = {}
        elif corruption == "not_a_row":
            bindings.append(None)
        elif corruption == "gap_index":
            bindings.append(
                {
                    "entity_type": "tag",
                    "alias_id": "smart_add_tag_1",
                    "entity_id": "tag_x",
                }
            )
        elif corruption == "missing_task":
            bindings[0]["entity_id"] = "task_missing"
        elif corruption == "extra_created_tag":
            bindings.append(
                {
                    "entity_type": "tag",
                    "alias_id": "smart_add_created_tag_1",
                    "entity_id": "tag_x",
                }
            )
        else:
            raise AssertionError(corruption)
        conn.execute(
            "UPDATE sync_command_receipts SET metadata = ? WHERE owner_id = ? AND command_id = ?",
            (json.dumps(metadata), OWNER, command_id),
        )


@pytest.mark.parametrize(
    "kind", ["task", "subtask", "comment", "project", "tag", "smart_add"]
)
@pytest.mark.parametrize(
    "corruption",
    ["missing", "wrong_id", "duplicate", "missing_field", "not_a_list", "not_a_row"],
)
def test_026_FR_005_full_result_requires_matching_identity_binding(
    legacy_service, kind, corruption
):
    service, repo, _enabled, _clock = legacy_service
    key = "binding-result"
    if kind in ("subtask", "comment"):
        parent = service.create_task(
            TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
        )
        payload = (
            TaskSubtaskCreateRequest(title="Child")
            if kind == "subtask"
            else TaskCommentCreateRequest(body="Child")
        )
        create = getattr(service, f"create_{kind}")
        kwargs = {"actor_id": OWNER} if kind == "comment" else {}
        retry = partial(
            create, parent.id, payload, owner_id=OWNER, idempotency_key=key, **kwargs
        )
    elif kind == "smart_add":
        payload = SmartAddTaskCreateRequest(
            title="Smart",
            project=SmartAddClassificationRef(name="Project"),
            tags=[SmartAddClassificationRef(name="@Tag")],
        )
        retry = partial(
            service.smart_add_task, payload, owner_id=OWNER, idempotency_key=key
        )
    else:
        payload = {
            "task": TaskCreateRequest(title="Task"),
            "project": ProjectCreateRequest(name="Project"),
            "tag": TagCreateRequest(name="@Tag"),
        }[kind]
        retry = partial(
            getattr(service, f"create_{kind}"),
            payload,
            owner_id=OWNER,
            idempotency_key=key,
        )
    retry()
    before = _count(repo, "sync_change_transactions")
    _corrupt_receipt_binding(repo, key, corruption)
    with allure.step(f"Reject {kind} full result with {corruption} identity binding"):
        with pytest.raises(SyncCommandError) as error:
            retry()
        assert error.value.code == "COMMAND_INTEGRITY"
        assert _count(repo, "sync_change_transactions") == before


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "missing_field",
        "bad_index",
        "bad_type",
        "gap_index",
        "missing_task",
        "extra_created_tag",
    ],
)
def test_026_FR_005_redacted_smart_add_malformed_bindings_fail_closed(
    legacy_service, corruption
):
    service, repo, _enabled, clock = legacy_service
    payload = SmartAddTaskCreateRequest(title="Smart")
    service.smart_add_task(payload, owner_id=OWNER, idempotency_key="smart-malformed")
    before = _count(repo, "sync_change_transactions")
    _corrupt_receipt_binding(repo, "smart-malformed", corruption)
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("Reject unusable retained aliases without leaking parser errors"):
        expected = (
            IdempotencyReceiptUnavailableError
            if corruption == "missing_task"
            else SyncCommandError
        )
        with pytest.raises(expected) as error:
            service.smart_add_task(
                payload, owner_id=OWNER, idempotency_key="smart-malformed"
            )
        if corruption != "missing_task":
            assert error.value.code == "COMMAND_INTEGRITY"
        assert _count(repo, "sync_change_transactions") == before


@pytest.mark.parametrize("corruption", ["malformed", "foreign_owner"])
def test_026_FR_005_smart_add_full_result_rejects_invalid_snapshot(
    legacy_service, corruption
):
    service, repo, _enabled, _clock = legacy_service
    payload = SmartAddTaskCreateRequest(title="Smart")
    service.smart_add_task(payload, owner_id=OWNER, idempotency_key="smart-snapshot")
    with sqlite3.connect(repo.db_path) as conn:
        command_id = _receipt_command_id(repo, "smart-snapshot")
        row = conn.execute(
            "SELECT result FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        ).fetchone()
        assert row is not None
        result = json.loads(row[0])
        if corruption == "malformed":
            result.pop("task")
        else:
            result["task"]["owner_id"] = "user_other"
        conn.execute(
            "UPDATE sync_command_receipts SET result = ? WHERE owner_id = ? AND command_id = ?",
            (json.dumps(result), OWNER, command_id),
        )
    with allure.step("Reject an invalid full Smart Add snapshot without another write"):
        with pytest.raises(SyncCommandError) as error:
            service.smart_add_task(
                payload, owner_id=OWNER, idempotency_key="smart-snapshot"
            )
        assert error.value.code == "COMMAND_INTEGRITY"
        assert _count(repo, "sync_change_transactions") == 1


@pytest.mark.parametrize("kind", ["project", "tag"])
def test_026_FR_005_smart_add_full_result_rejects_foreign_classification_owner(
    legacy_service, kind
):
    service, repo, _enabled, _clock = legacy_service
    payload = SmartAddTaskCreateRequest(
        title="Smart",
        project=SmartAddClassificationRef(name="Project"),
        tags=[SmartAddClassificationRef(name="@Tag")],
    )
    service.smart_add_task(payload, owner_id=OWNER, idempotency_key="smart-owner")
    with sqlite3.connect(repo.db_path) as conn:
        command_id = _receipt_command_id(repo, "smart-owner")
        row = conn.execute(
            "SELECT result FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        ).fetchone()
        assert row is not None
        result = json.loads(row[0])
        classification = result["project"] if kind == "project" else result["tags"][0]
        classification["owner_id"] = "user_other"
        conn.execute(
            "UPDATE sync_command_receipts SET result = ? WHERE owner_id = ? AND command_id = ?",
            (json.dumps(result), OWNER, command_id),
        )
    with allure.step("Reject a foreign classification embedded in a known result"):
        with pytest.raises(SyncCommandError) as error:
            service.smart_add_task(
                payload, owner_id=OWNER, idempotency_key="smart-owner"
            )
        assert error.value.code == "COMMAND_INTEGRITY"
        assert _count(repo, "sync_change_transactions") == 1


@pytest.mark.parametrize("kind", ["subtask", "comment", "smart_add", "classified"])
@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("hours", [24, 25])
def test_026_FR_005_expired_legacy_child_or_smart_add_cannot_copy_response(
    legacy_service, kind, missing, hours
):
    service, repo, enabled, clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    enabled[0] = False
    key = "pre-migration"
    if kind in ("smart_add", "classified"):
        payload = SmartAddTaskCreateRequest(
            title="Sensitive smart task",
            project=(
                SmartAddClassificationRef(name="Sensitive project")
                if kind == "classified"
                else None
            ),
        )
        retry = partial(
            service.smart_add_task, payload, owner_id=OWNER, idempotency_key=key
        )
    else:
        payload = (
            TaskSubtaskCreateRequest(title="Sensitive child")
            if kind == "subtask"
            else TaskCommentCreateRequest(body="Sensitive child")
        )
        kwargs = {"actor_id": OWNER} if kind == "comment" else {}
        retry = partial(
            getattr(service, f"create_{kind}"),
            parent.id,
            payload,
            owner_id=OWNER,
            idempotency_key=key,
            **kwargs,
        )
    original = retry()
    assert repo.get_idempotency(owner_id=OWNER, key=key) is not None
    if missing:
        table = (
            "tasks"
            if kind in ("smart_add", "classified")
            else "subtasks" if kind == "subtask" else "comments"
        )
        entity_id = (
            original.task.id if kind in ("smart_add", "classified") else original.id
        )
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (entity_id,))
    clock[0] = NOW + timedelta(hours=hours)
    enabled[0] = True
    with allure.step("Purge the stale legacy body before creating any fresh receipt"):
        if missing or kind == "classified":
            with pytest.raises(IdempotencyReceiptUnavailableError):
                retry()
        else:
            retry()
        assert repo.get_idempotency(owner_id=OWNER, key=key) is None
        with sqlite3.connect(repo.db_path) as conn:
            identity = conn.execute(
                "SELECT command, request_hash, resource_id, response_body "
                "FROM idempotency_records WHERE owner_id = ? AND key_hash = ?",
                (OWNER, idempotency_key_digest(key)),
            ).fetchone()
            receipts = conn.execute(
                "SELECT result FROM sync_command_receipts WHERE owner_id = ? "
                "AND command_id IN (SELECT command_id FROM sync_legacy_keys "
                "WHERE owner_id = ? AND key_digest = ?)",
                (OWNER, OWNER, idempotency_key_digest(key)),
            ).fetchall()
        assert identity is not None
        assert (identity[0], identity[2]) == (
            (
                "smart_add_task"
                if kind in ("smart_add", "classified")
                else f"create_{kind}:{parent.id}"
            ),
            original.task.id if kind in ("smart_add", "classified") else original.id,
        )
        assert identity[1]
        assert json.loads(identity[3]) == {"_expired_revision": 1}
        assert len(receipts) == 1 and receipts[0][0] is None
        assert _count(repo, "sync_change_transactions") == 1
        if missing or kind == "classified":
            with pytest.raises(IdempotencyReceiptUnavailableError):
                retry()
            assert _count(repo, "sync_change_transactions") == 1


@pytest.mark.parametrize("kind", ["subtask", "smart_add"])
def test_026_FR_005_expired_legacy_identity_still_checks_original_body(
    legacy_service, kind
):
    service, repo, enabled, clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    enabled[0] = False
    if kind == "subtask":
        service.create_subtask(
            parent.id,
            TaskSubtaskCreateRequest(title="Original"),
            owner_id=OWNER,
            idempotency_key="old",
        )
    else:
        service.smart_add_task(
            SmartAddTaskCreateRequest(title="Original"),
            owner_id=OWNER,
            idempotency_key="old",
        )
    clock[0] = NOW + timedelta(hours=25)
    enabled[0] = True
    before = _count(repo, "sync_change_transactions")
    with allure.step("Every changed retry retains the original expired identity"):
        for attempt in range(2):
            if attempt:
                enabled[0] = False
            with pytest.raises(ConflictError):
                if kind == "subtask":
                    service.create_subtask(
                        parent.id,
                        TaskSubtaskCreateRequest(title="Different"),
                        owner_id=OWNER,
                        idempotency_key="old",
                    )
                else:
                    service.smart_add_task(
                        SmartAddTaskCreateRequest(title="Different"),
                        owner_id=OWNER,
                        idempotency_key="old",
                    )
            assert _count(repo, "sync_change_transactions") == before
        assert repo.get_idempotency(owner_id=OWNER, key="old") is None


@pytest.mark.parametrize("kind", ["subtask", "smart_add"])
def test_026_FR_005_first_expired_flag_off_retry_cannot_read_repair(
    legacy_service, kind
):
    service, repo, enabled, clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    enabled[0] = False
    if kind == "subtask":
        payload = TaskSubtaskCreateRequest(title="Old child")
        retry = partial(
            service.create_subtask,
            parent.id,
            payload,
            owner_id=OWNER,
            idempotency_key="old",
        )
        created = retry()
        table = "subtasks"
        entity_id = created.id
    else:
        payload = SmartAddTaskCreateRequest(title="Old smart task")
        retry = partial(
            service.smart_add_task, payload, owner_id=OWNER, idempotency_key="old"
        )
        created = retry()
        table = "tasks"
        entity_id = created.task.id
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (entity_id,))
    clock[0] = NOW + timedelta(hours=25)
    before = _count(repo, "sync_change_transactions")
    with allure.step("The first OFF retry purges content before any legacy repair"):
        for _ in range(2):
            with pytest.raises(IdempotencyReceiptUnavailableError):
                retry()
            with sqlite3.connect(repo.db_path) as conn:
                assert (
                    conn.execute(
                        f"SELECT 1 FROM {table} WHERE id = ?", (entity_id,)
                    ).fetchone()
                    is None
                )
            assert _count(repo, "sync_change_transactions") == before
        assert repo.get_idempotency(owner_id=OWNER, key="old") is None


@pytest.mark.parametrize("kind", ["subtask", "smart_add"])
def test_026_FR_005_expired_key_cannot_switch_command_family(legacy_service, kind):
    service, repo, enabled, clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    enabled[0] = False
    if kind == "subtask":
        service.create_subtask(
            parent.id,
            TaskSubtaskCreateRequest(title="Original"),
            owner_id=OWNER,
            idempotency_key="old",
        )
    else:
        service.smart_add_task(
            SmartAddTaskCreateRequest(title="Original"),
            owner_id=OWNER,
            idempotency_key="old",
        )
    clock[0] = NOW + timedelta(hours=25)
    before = _count(repo, "sync_change_transactions")
    with allure.step("Different command types cannot reuse a redacted legacy key"):
        for _ in range(2):
            with pytest.raises(ConflictError):
                service.create_project(
                    ProjectCreateRequest(name="Unrelated"),
                    owner_id=OWNER,
                    idempotency_key="old",
                )
            assert _count(repo, "projects") == 0
            assert _count(repo, "sync_change_transactions") == before
        assert repo.get_idempotency(owner_id=OWNER, key="old") is None


def test_026_FR_005_expired_unclassified_smart_add_refuses_changed_membership(
    legacy_service,
):
    service, repo, enabled, clock = legacy_service
    payload = SmartAddTaskCreateRequest(title="Original")
    enabled[0] = False
    created = service.smart_add_task(payload, owner_id=OWNER, idempotency_key="old")
    enabled[0] = True
    project = service.create_project(
        ProjectCreateRequest(name="Later"), owner_id=OWNER, idempotency_key="project"
    )
    service.update_task(
        created.task.id,
        TaskUpdateRequest(
            project_id=project.id, expected_revision=created.task.revision
        ),
        owner_id=OWNER,
        idempotency_key="assign",
    )
    clock[0] = NOW + timedelta(hours=25)
    before = _count(repo, "sync_change_transactions")
    with allure.step(
        "The present project cannot be mistaken for an old Smart Add alias"
    ):
        for _ in range(2):
            with pytest.raises(IdempotencyReceiptUnavailableError):
                service.smart_add_task(payload, owner_id=OWNER, idempotency_key="old")
        assert _count(repo, "sync_change_transactions") == before


def test_026_FR_005_expired_classified_smart_add_stays_unavailable_after_unlink(
    legacy_service,
):
    service, repo, enabled, clock = legacy_service
    payload = SmartAddTaskCreateRequest(
        title="Classified", project=SmartAddClassificationRef(name="Project")
    )
    enabled[0] = False
    original = service.smart_add_task(payload, owner_id=OWNER, idempotency_key="old")
    clock[0] = NOW + timedelta(hours=25)
    enabled[0] = True
    before = _count(repo, "sync_change_transactions")
    with allure.step("Classification cannot vanish from the durable retry identity"):
        with pytest.raises(IdempotencyReceiptUnavailableError):
            service.smart_add_task(payload, owner_id=OWNER, idempotency_key="old")
        current = repo.get_for_owner(original.task.id, owner_id=OWNER)
        service.update_task(
            current.id,
            TaskUpdateRequest(project_id=None, expected_revision=current.revision),
            owner_id=OWNER,
            idempotency_key="unlink",
        )
        for _ in range(2):
            with pytest.raises(IdempotencyReceiptUnavailableError):
                service.smart_add_task(payload, owner_id=OWNER, idempotency_key="old")
        assert _count(repo, "sync_change_transactions") == before + 1


@pytest.mark.parametrize("kind", ["child", "classified_smart_add"])
def test_026_FR_005_adopted_response_expires_at_original_deadline(legacy_service, kind):
    service, repo, enabled, clock = legacy_service
    clock[0] = NOW - timedelta(hours=23)
    key = "old-response"
    if kind == "child":
        parent = service.create_task(
            TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
        )
        payload = TaskSubtaskCreateRequest(title="Original child")
        retry = partial(
            service.create_subtask,
            parent.id,
            payload,
            owner_id=OWNER,
            idempotency_key=key,
        )
    else:
        payload = SmartAddTaskCreateRequest(
            title="Original task", project=SmartAddClassificationRef(name="Project")
        )
        retry = partial(
            service.smart_add_task, payload, owner_id=OWNER, idempotency_key=key
        )
    enabled[0] = False
    original = retry()
    clock[0] = NOW
    enabled[0] = True
    with allure.step("Adopt before the original 24-hour deadline"):
        assert retry() == original
        with sqlite3.connect(repo.db_path) as conn:
            row = conn.execute(
                "SELECT result, expires_at FROM sync_command_receipts WHERE owner_id=? "
                "AND command_id=(SELECT command_id FROM sync_legacy_keys "
                "WHERE owner_id=? AND key_digest=?)",
                (OWNER, OWNER, idempotency_key_digest(key)),
            ).fetchone()
        assert row is not None and row[0] is not None
        assert datetime.fromisoformat(row[1]) == NOW + timedelta(hours=1)

    clock[0] = NOW + timedelta(hours=2)
    if kind == "classified_smart_add":
        service.update_task(
            original.task.id,
            TaskUpdateRequest(
                project_id=None, expected_revision=original.task.revision
            ),
            owner_id=OWNER,
            idempotency_key="unlink-original",
        )
    before = _count(repo, "sync_change_transactions")
    with allure.step("Never replay expired content or invent unclassified success"):
        if kind == "child":
            assert retry().id == original.id
        else:
            for _ in range(2):
                with pytest.raises(IdempotencyReceiptUnavailableError):
                    retry()
        with sqlite3.connect(repo.db_path) as conn:
            stored = conn.execute(
                "SELECT result FROM sync_command_receipts WHERE owner_id=? "
                "AND command_id=(SELECT command_id FROM sync_legacy_keys "
                "WHERE owner_id=? AND key_digest=?)",
                (OWNER, OWNER, idempotency_key_digest(key)),
            ).fetchone()
        assert stored is not None and stored[0] is None
        assert _count(repo, "sync_change_transactions") == before


def test_026_FR_005_legacy_child_adoption_cannot_retry_a_lost_parent(legacy_service):
    service, repo, enabled, _clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    payload = TaskSubtaskCreateRequest(title="Child")
    enabled[0] = False
    service.create_subtask(parent.id, payload, owner_id=OWNER, idempotency_key="old")
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (parent.id,))
    enabled[0] = True
    before = _count(repo, "sync_change_transactions")
    with allure.step("A lost parent does not make an old child a new command"):
        with pytest.raises(NotFoundError):
            service.create_subtask(
                parent.id, payload, owner_id=OWNER, idempotency_key="old"
            )
        assert _count(repo, "sync_change_transactions") == before


@pytest.mark.parametrize("kind", ["subtask", "smart_add"])
def test_026_FR_005_legacy_raw_result_cannot_escape_owner(
    legacy_service, monkeypatch, kind
):
    service, repo, _enabled, _clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    if kind == "subtask":
        child = service.create_subtask(
            parent.id,
            TaskSubtaskCreateRequest(title="Child"),
            owner_id=OWNER,
            idempotency_key="seed",
        )
        monkeypatch.setattr(
            service,
            "_subtask_result",
            lambda *_args, **_kwargs: child.model_copy(update={"owner_id": "other"}),
        )
        retry = partial(
            service.create_subtask,
            parent.id,
            TaskSubtaskCreateRequest(title="Child"),
            owner_id=OWNER,
            idempotency_key="seed",
        )
    else:
        smart = service.smart_add_task(
            SmartAddTaskCreateRequest(title="Task"),
            owner_id=OWNER,
            idempotency_key="seed",
        )
        monkeypatch.setattr(
            service,
            "_smart_add_result",
            lambda *_args, **_kwargs: smart.model_copy(
                update={"task": smart.task.model_copy(update={"owner_id": "other"})}
            ),
        )
        retry = partial(
            service.smart_add_task,
            SmartAddTaskCreateRequest(title="Task"),
            owner_id=OWNER,
            idempotency_key="seed",
        )
    # Simulate a pre-migration legacy record: remove only sync identity rows.
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "DELETE FROM sync_command_receipts WHERE owner_id=? AND command_id=?",
            (OWNER, _receipt_command_id(repo, "seed")),
        )
        conn.execute(
            "DELETE FROM sync_legacy_keys WHERE owner_id=? AND key_digest=?",
            (OWNER, idempotency_key_digest("seed")),
        )
    with (
        allure.step("Never publish a raw child or Smart Add result for another owner"),
        pytest.raises(SyncCommandError, match="COMMAND_INTEGRITY"),
    ):
        retry()


def test_026_FR_005_task_adoption_rejects_legacy_identity_mismatch(legacy_service):
    service, repo, enabled, _clock = legacy_service
    payload = TaskCreateRequest(title="Legacy task")
    enabled[0] = False
    task = service.create_task(payload, owner_id=OWNER, idempotency_key="legacy-task")
    old = repo.get_idempotency(owner_id=OWNER, key="legacy-task")
    assert old is not None
    repo.save_idempotency(
        owner_id=OWNER,
        record=old.model_copy(update={"resource_id": "task_other"}),
    )
    enabled[0] = True
    with allure.step(
        "Reject a legacy task row bound to another entity before adoption"
    ):
        with pytest.raises(SyncCommandError) as error:
            service.create_task(payload, owner_id=OWNER, idempotency_key="legacy-task")
        assert error.value.code == "COMMAND_INTEGRITY"
        assert repo.get_for_owner(task.id, owner_id=OWNER) == task
        assert _count(repo, "sync_command_receipts") == 0


def test_026_FR_005_child_refusal_rejects_unknown_reason(legacy_service):
    service, _repo, _enabled, _clock = legacy_service
    handler = service._legacy_tag_handler
    assert handler is not None
    with allure.step(
        "Do not translate an unknown retained child refusal into a public error"
    ):
        with pytest.raises(SyncCommandError) as error:
            handler._child_rejected(
                DomainRefusal(
                    "unexpected_reason", None, ("subtask", ["subtask_1"]), None
                )
            )
        assert error.value.code == "COMMAND_INTEGRITY"


def test_026_FR_005_smart_add_rejection_retains_original_outcome(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    payload = SmartAddTaskCreateRequest(
        title="Unresolved", project=SmartAddClassificationRef(id="project_missing")
    )
    with allure.step("Reject an unknown project and retain its terminal outcome"):
        with pytest.raises(NotFoundError) as original:
            service.smart_add_task(
                payload, owner_id=OWNER, idempotency_key="smart-reject"
            )
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 0
    with allure.step("Replay the same rejection without executing the legacy command"):
        with pytest.raises(NotFoundError) as replay:
            service.smart_add_task(
                payload, owner_id=OWNER, idempotency_key="smart-reject"
            )
        assert replay.value.resource == original.value.resource
        assert replay.value.identifier == original.value.identifier
        assert _count(repo, "sync_command_receipts") == 1


@pytest.mark.parametrize("classification", ["project", "tag"])
def test_026_FR_005_smart_add_inactive_classification_rejection_is_immutable(
    legacy_service, classification
):
    service, repo, _enabled, _clock = legacy_service
    if classification == "project":
        project = service.create_project(
            ProjectCreateRequest(name="Archived"),
            owner_id=OWNER,
            idempotency_key="classification",
        )
        archived = service.archive_project(
            project.id,
            ExpectedRevisionRequest(expected_revision=project.revision),
            owner_id=OWNER,
            idempotency_key="archive",
        )
        payload = SmartAddTaskCreateRequest(
            title="Smart", project=SmartAddClassificationRef(id=project.id)
        )
        expected = "Task project must be active."
    else:
        tag = service.create_tag(
            TagCreateRequest(name="@Archived"),
            owner_id=OWNER,
            idempotency_key="classification",
        )
        # A legacy inactive tag is represented as deleted after storage migration.
        repo.save_tag(tag.model_copy(update={"state": "deleted"}))
        payload = SmartAddTaskCreateRequest(
            title="Smart", tags=[SmartAddClassificationRef(id=tag.id)]
        )
        expected = "Task contexts must be active; task tags must be active."

    receipts_before = _count(repo, "sync_command_receipts")
    changes_before = _count(repo, "sync_change_transactions")
    tasks_before = _count(repo, "tasks")
    with allure.step("Persist the original inactive-classification refusal"):
        with pytest.raises(ValidationFailure) as original:
            service.smart_add_task(
                payload, owner_id=OWNER, idempotency_key="inactive-smart"
            )
        assert str(original.value) == expected
        assert _count(repo, "sync_command_receipts") == receipts_before + 1
        assert _count(repo, "sync_change_transactions") == changes_before
        assert _count(repo, "tasks") == tasks_before
        with sqlite3.connect(repo.db_path) as conn:
            row = conn.execute(
                "SELECT metadata FROM sync_command_receipts "
                "WHERE owner_id = ? AND command_id = ?",
                (OWNER, _receipt_command_id(repo, "inactive-smart")),
            ).fetchone()
        assert row is not None
        assert json.loads(row[0])["outcome"] == "rejected"

    if classification == "project":
        service.unarchive_project(
            project.id,
            ExpectedRevisionRequest(expected_revision=archived.revision),
            owner_id=OWNER,
            idempotency_key="unarchive",
        )
    else:
        repo.save_tag(tag)

    receipts_before = _count(repo, "sync_command_receipts")
    changes_before = _count(repo, "sync_change_transactions")
    with allure.step("Replay the rejection after the classification becomes active"):
        with pytest.raises(ValidationFailure) as replay:
            service.smart_add_task(
                payload, owner_id=OWNER, idempotency_key="inactive-smart"
            )
        assert str(replay.value) == expected
        assert _count(repo, "sync_command_receipts") == receipts_before
        assert _count(repo, "sync_change_transactions") == changes_before
        assert _count(repo, "tasks") == tasks_before


def test_026_FR_005_renaming_tag_preserves_duplicate_name_error(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    first = service.create_tag(
        TagCreateRequest(name="@Alpha"), owner_id=OWNER, idempotency_key="first"
    )
    second = service.create_tag(
        TagCreateRequest(name="@Beta"), owner_id=OWNER, idempotency_key="second"
    )
    payload = TagUpdateRequest(name="@Alpha", expected_revision=second.revision)
    with allure.step(
        "Keep the attempted display name on original and replayed conflicts"
    ):
        for _ in range(2):
            with pytest.raises(ConflictError) as error:
                service.update_tag(
                    second.id, payload, owner_id=OWNER, idempotency_key="rename"
                )
            assert error.value.identifier == first.name
        assert _count(repo, "sync_command_receipts") == 3


def test_026_FR_005_renaming_project_preserves_duplicate_name_error(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    first = service.create_project(
        ProjectCreateRequest(name="Alpha"), owner_id=OWNER, idempotency_key="first"
    )
    second = service.create_project(
        ProjectCreateRequest(name="Beta"), owner_id=OWNER, idempotency_key="second"
    )
    payload = ProjectUpdateRequest(name="  Alpha  ", expected_revision=second.revision)
    with allure.step(
        "Keep the normalized attempted name on original and replayed conflicts"
    ):
        for _ in range(2):
            with pytest.raises(ConflictError) as error:
                service.update_project(
                    second.id, payload, owner_id=OWNER, idempotency_key="rename"
                )
            assert error.value.identifier == first.name
        assert _count(repo, "sync_command_receipts") == 3


def test_026_FR_005_project_update_receipt_distinguishes_omitted_nullable_fields(
    legacy_service,
):
    service, repo, _enabled, _clock = legacy_service
    project = service.create_project(
        ProjectCreateRequest(
            name="Project", color="blue", desired_outcome="Ship safely"
        ),
        owner_id=OWNER,
        idempotency_key="project-create",
    )
    original_payload = ProjectUpdateRequest(
        name="Renamed", expected_revision=project.revision
    )
    with allure.step("Replay the same project patch and reject changed field presence"):
        original = service.update_project(
            project.id,
            original_payload,
            owner_id=OWNER,
            idempotency_key="project-update",
        )
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute(
                "UPDATE sync_command_receipts SET result = NULL "
                "WHERE owner_id = ? AND command_id = ?",
                (OWNER, _receipt_command_id(repo, "project-update")),
            )
        assert (
            service.update_project(
                project.id,
                original_payload,
                owner_id=OWNER,
                idempotency_key="project-update",
            )
            == original
        )
        receipts = _count(repo, "sync_command_receipts")
        changes = _count(repo, "sync_change_transactions")
        with pytest.raises(ConflictError):
            service.update_project(
                project.id,
                ProjectUpdateRequest(
                    name="Renamed",
                    color=None,
                    desired_outcome=None,
                    expected_revision=project.revision,
                ),
                owner_id=OWNER,
                idempotency_key="project-update",
            )
        current = repo.get_project_for_owner(project.id, owner_id=OWNER)
        assert current == original
        assert current.color == "blue"
        assert current.desired_outcome == "Ship safely"
        assert _count(repo, "sync_command_receipts") == receipts
        assert _count(repo, "sync_change_transactions") == changes


def test_026_FR_005_task_update_receipt_distinguishes_omitted_nullable_fields(
    legacy_service,
):
    service, repo, _enabled, _clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Task", details="Keep this detail"),
        owner_id=OWNER,
        idempotency_key="task-create",
    )
    original_payload = TaskUpdateRequest(
        title="Renamed", expected_revision=task.revision
    )
    with allure.step("Replay the same task patch and reject changed field presence"):
        original = service.update_task(
            task.id,
            original_payload,
            owner_id=OWNER,
            idempotency_key="task-update",
        )
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute(
                "UPDATE sync_command_receipts SET result = NULL "
                "WHERE owner_id = ? AND command_id = ?",
                (OWNER, _receipt_command_id(repo, "task-update")),
            )
        assert (
            service.update_task(
                task.id,
                original_payload,
                owner_id=OWNER,
                idempotency_key="task-update",
            )
            == original
        )
        receipts = _count(repo, "sync_command_receipts")
        changes = _count(repo, "sync_change_transactions")
        with pytest.raises(ConflictError):
            service.update_task(
                task.id,
                TaskUpdateRequest(
                    title="Renamed",
                    details=None,
                    project_id=None,
                    tag_ids=None,
                    due_date=None,
                    priority=None,
                    waiting_for=None,
                    new_formulation_id=None,
                    expected_revision=task.revision,
                ),
                owner_id=OWNER,
                idempotency_key="task-update",
            )
        current = service.get_task(task.id, owner_id=OWNER)
        assert current == original
        assert current.details == "Keep this detail"
        assert _count(repo, "sync_command_receipts") == receipts
        assert _count(repo, "sync_change_transactions") == changes


def _seed_expired_legacy_key(service, repo, tag, key: str) -> None:
    repo.save_idempotency(
        owner_id=OWNER,
        record=IdempotencyRecord(
            key=key,
            command="create_tag",
            request_hash=service._request_hash(
                "create_tag", TagCreateRequest(name="@Work")
            ),
            resource_id=tag.id,
            response_body=tag.model_dump(mode="json"),
            created_at=NOW - timedelta(hours=25),
        ),
    )


def test_026_FR_005_legacy_tag_uses_owner_key_receipt_and_feed(legacy_service):
    service, repo, _enabled, clock = legacy_service
    payload = TagCreateRequest(name="@Work")

    with allure.step("Create once and replay the original tag DTO"):
        original = service.create_tag(
            payload, owner_id=OWNER, idempotency_key="tag-key"
        )
        replay = service.create_tag(payload, owner_id=OWNER, idempotency_key="tag-key")
        assert replay == original
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 1
        assert _count(repo, "sync_change_records") == 1

    with allure.step("Reject body and operation changes under the same owner key"):
        with pytest.raises(ConflictError):
            service.create_tag(
                TagCreateRequest(name="@Other"),
                owner_id=OWNER,
                idempotency_key="tag-key",
            )
        with pytest.raises(ConflictError):
            service.create_project(
                ProjectCreateRequest(name="Project"),
                owner_id=OWNER,
                idempotency_key="tag-key",
            )
        assert len(repo.list_tags_for_owner(owner_id=OWNER)) == 1

    with allure.step("Resolve the redacted receipt through its retained tag alias"):
        repo.save_tag(original.model_copy(update={"name": "Renamed", "revision": 2}))
        retained = service.create_tag(
            payload, owner_id=OWNER, idempotency_key="tag-key"
        )
        assert retained.id == original.id
        assert retained.name == "Work"
        clock[0] = NOW + timedelta(hours=25)
        redacted = service.create_tag(
            payload, owner_id=OWNER, idempotency_key="tag-key"
        )
        assert redacted.id == original.id
        assert redacted.name == "Renamed"
        assert _count(repo, "sync_change_transactions") == 1

    with allure.step("Do not recreate a tag after its redacted snapshot is gone"):
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute(
                "DELETE FROM tags WHERE owner_id = ? AND id = ?",
                (OWNER, original.id),
            )
        with pytest.raises(IdempotencyReceiptUnavailableError):
            service.create_tag(payload, owner_id=OWNER, idempotency_key="tag-key")
        assert repo.list_tags_for_owner(owner_id=OWNER) == []


def test_026_FR_005_rejected_tag_replay_keeps_original_conflict(legacy_service):
    service, repo, _enabled, clock = legacy_service
    original = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="first"
    )
    _seed_expired_legacy_key(service, repo, original, "expired-unrelated")
    attempted = TagCreateRequest(name="@Work")
    with allure.step("Store the existing duplicate-name conflict"):
        with pytest.raises(ConflictError) as initial:
            service.create_tag(attempted, owner_id=OWNER, idempotency_key="duplicate")
        assert initial.value.resource == "Tag"
        assert initial.value.identifier == "Work"

    with allure.step("Replay the same conflict after the live tag is renamed"):
        repo.save_tag(original.model_copy(update={"name": "Renamed", "revision": 2}))
        _seed_expired_legacy_key(service, repo, original, "expired-unrelated")
        clock[0] = NOW + timedelta(hours=25)
        with pytest.raises(ConflictError) as replay:
            service.create_tag(attempted, owner_id=OWNER, idempotency_key="duplicate")
        assert replay.value.resource == "Tag"
        assert replay.value.identifier == "Work"
        assert str(replay.value) == "Tag 'Work' already exists."
        assert _count(repo, "sync_change_transactions") == 1
        assert repo.get_idempotency(owner_id=OWNER, key="expired-unrelated") is None
        assert repo.get_idempotency(owner_id=OWNER, key="expired-unrelated") is None


def test_026_FR_005_legacy_tag_adoption_preserves_old_replay_and_repairs_once(
    legacy_service,
):
    service, repo, enabled, _clock = legacy_service
    payload = TagCreateRequest(name="@Work")
    enabled[0] = False
    original = service.create_tag(payload, owner_id=OWNER, idempotency_key="old-key")
    _seed_expired_legacy_key(service, repo, original, "expired-unrelated")
    enabled[0] = True

    with allure.step("Adopt the current legacy snapshot without a duplicate feed row"):
        adopted = service.create_tag(payload, owner_id=OWNER, idempotency_key="old-key")
        assert adopted == original
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 0
        assert repo.get_idempotency(owner_id=OWNER, key="expired-unrelated") is None

    with allure.step("Replay the adopted receipt without a second effect"):
        replay = service.create_tag(payload, owner_id=OWNER, idempotency_key="old-key")
        assert replay == original
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 0

    # Model a legacy snapshot whose resource row was lost before migration.
    repaired_snapshot = original.model_copy(update={"revision": 2})
    repo.save_idempotency(
        owner_id=OWNER,
        record=IdempotencyRecord(
            key="repair-key",
            command="create_tag",
            request_hash=service._request_hash("create_tag", payload),
            resource_id=repaired_snapshot.id,
            response_body=repaired_snapshot.model_dump(mode="json"),
            created_at=NOW,
        ),
    )
    repo.save_tag(original)

    with allure.step("Repair the old snapshot and publish one atomic upsert"):
        repaired = service.create_tag(
            payload, owner_id=OWNER, idempotency_key="repair-key"
        )
        assert repaired.revision == 2
        assert repo.get_tag_for_owner(original.id, owner_id=OWNER).revision == 2
        assert _count(repo, "sync_command_receipts") == 2
        assert _count(repo, "sync_change_transactions") == 1
        assert _count(repo, "sync_change_records") == 1


def test_026_FR_005_missing_legacy_tag_is_repaired_once_then_replayed(legacy_service):
    service, repo, enabled, _clock = legacy_service
    payload = TagCreateRequest(name="@Recovered")
    enabled[0] = False
    original = service.create_tag(
        payload, owner_id=OWNER, idempotency_key="missing-row-key"
    )
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "DELETE FROM tags WHERE owner_id = ? AND id = ?",
            (OWNER, original.id),
        )
    enabled[0] = True

    with allure.step("Adopt the unexpired snapshot and restore the original tag ID"):
        repaired = service.create_tag(
            payload, owner_id=OWNER, idempotency_key="missing-row-key"
        )
        assert repaired == original
        assert repo.get_tag_for_owner(original.id, owner_id=OWNER) == original
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 1
        assert _count(repo, "sync_change_records") == 1

    with allure.step("Replay the adopted receipt without a second feed effect"):
        assert (
            service.create_tag(
                payload, owner_id=OWNER, idempotency_key="missing-row-key"
            )
            == original
        )
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 1
        assert _count(repo, "sync_change_records") == 1


@pytest.mark.parametrize("corruption", ["malformed", "foreign_owner"])
def test_026_FR_005_tag_replay_rejects_corrupt_accepted_receipt_result(
    legacy_service, corruption
):
    service, repo, _enabled, _clock = legacy_service
    payload = TagCreateRequest(name="@Receipt")
    original = service.create_tag(
        payload, owner_id=OWNER, idempotency_key="receipt-result-key"
    )
    current = original.model_copy(update={"name": "Current", "revision": 2})
    repo.save_tag(current)
    bad_result = (
        {}
        if corruption == "malformed"
        else original.model_copy(update={"owner_id": "user_other"}).model_dump(
            mode="json"
        )
    )
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET result = ? WHERE owner_id = ? AND command_id = ?",
            (
                json.dumps(bad_result),
                OWNER,
                _receipt_command_id(repo, "receipt-result-key"),
            ),
        )

    with allure.step("Fail closed on malformed or foreign-owner replay data"):
        with pytest.raises(SyncCommandError) as error:
            service.create_tag(
                payload, owner_id=OWNER, idempotency_key="receipt-result-key"
            )
        assert error.value.code == "COMMAND_INTEGRITY"
        assert repo.get_tag_for_owner(original.id, owner_id=OWNER) == current
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 1
        assert _count(repo, "sync_change_records") == 1


def test_026_FR_005_rejected_tag_receipt_requires_its_private_typed_witness(
    legacy_service,
):
    service, repo, _enabled, _clock = legacy_service
    payload = TagCreateRequest(name="@Taken")
    original = service.create_tag(payload, owner_id=OWNER, idempotency_key="taken")
    attempted = TagCreateRequest(name="@Taken")
    with pytest.raises(ConflictError):
        service.create_tag(attempted, owner_id=OWNER, idempotency_key="rejected")
    command_id = _receipt_command_id(repo, "rejected")
    with sqlite3.connect(repo.db_path) as conn:
        row = conn.execute(
            "SELECT metadata FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        ).fetchone()
        assert row is not None
        metadata = json.loads(row[0])
        metadata.pop("_legacy_refusal_v1", None)
        conn.execute(
            "UPDATE sync_command_receipts SET metadata = ? WHERE owner_id = ? AND command_id = ?",
            (json.dumps(metadata), OWNER, command_id),
        )

    with allure.step("Reject a refusal receipt whose typed witness was lost"):
        with pytest.raises(SyncCommandError) as error:
            service.create_tag(attempted, owner_id=OWNER, idempotency_key="rejected")
        assert error.value.code == "COMMAND_INTEGRITY"
        assert repo.list_tags_for_owner(owner_id=OWNER) == [original]
        assert _count(repo, "sync_change_transactions") == 1


def test_026_FR_005_adopted_tag_receipt_requires_its_stable_binding(legacy_service):
    service, repo, enabled, _clock = legacy_service
    payload = TagCreateRequest(name="@Bound")
    enabled[0] = False
    original = service.create_tag(payload, owner_id=OWNER, idempotency_key="bound-key")
    enabled[0] = True
    assert (
        service.create_tag(payload, owner_id=OWNER, idempotency_key="bound-key")
        == original
    )
    assert _count(repo, "sync_change_transactions") == 0
    command_id = _receipt_command_id(repo, "bound-key")
    with sqlite3.connect(repo.db_path) as conn:
        row = conn.execute(
            "SELECT metadata FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        ).fetchone()
        assert row is not None
        metadata = json.loads(row[0])
        metadata["id_bindings"] = []
        conn.execute(
            "UPDATE sync_command_receipts SET metadata = ? WHERE owner_id = ? AND command_id = ?",
            (json.dumps(metadata), OWNER, command_id),
        )

    with allure.step(
        "Fail closed when a redacted adoption receipt loses its tag binding"
    ):
        with pytest.raises(SyncCommandError) as error:
            service.create_tag(payload, owner_id=OWNER, idempotency_key="bound-key")
        assert error.value.code == "COMMAND_INTEGRITY"
        assert repo.get_tag_for_owner(original.id, owner_id=OWNER) == original
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 0


@pytest.mark.parametrize(
    "corruption",
    [
        "command",
        "request_hash",
        "resource_id",
        "malformed_body",
        "snapshot_id",
        "foreign_owner",
    ],
)
def test_026_FR_005_adopted_tag_receipt_rejects_legacy_snapshot_mismatch(
    legacy_service, corruption
):
    service, repo, enabled, _clock = legacy_service
    payload = TagCreateRequest(name="@Adopted")
    enabled[0] = False
    original = service.create_tag(payload, owner_id=OWNER, idempotency_key="adopt-key")
    enabled[0] = True
    assert (
        service.create_tag(payload, owner_id=OWNER, idempotency_key="adopt-key")
        == original
    )
    record = repo.get_idempotency(owner_id=OWNER, key="adopt-key")
    assert record is not None
    update: dict[str, object]
    if corruption == "command":
        update = {"command": "update_tag:other"}
    elif corruption == "request_hash":
        update = {"request_hash": "different-body"}
    elif corruption == "resource_id":
        update = {"resource_id": "tag_other"}
    elif corruption == "malformed_body":
        update = {"response_body": {}}
    else:
        foreign = original.model_copy(
            update={
                "id": "tag_other" if corruption == "snapshot_id" else original.id,
                "owner_id": "user_other" if corruption == "foreign_owner" else OWNER,
            }
        )
        update = {"response_body": foreign.model_dump(mode="json")}
    repo.save_idempotency(owner_id=OWNER, record=record.model_copy(update=update))

    with allure.step("Reject the retained old row without mutating the accepted tag"):
        with pytest.raises(SyncCommandError) as error:
            service.create_tag(payload, owner_id=OWNER, idempotency_key="adopt-key")
        assert error.value.code == "COMMAND_INTEGRITY"
        assert repo.get_tag_for_owner(original.id, owner_id=OWNER) == original
        assert repo.list_tags_for_owner(owner_id=OWNER) == [original]
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 0


def test_026_FR_005_legacy_tag_snapshot_must_match_its_persisted_identity(
    legacy_service,
):
    service, repo, enabled, _clock = legacy_service
    payload = TagCreateRequest(name="@Identity")
    enabled[0] = False
    original = service.create_tag(
        payload, owner_id=OWNER, idempotency_key="identity-key"
    )
    record = repo.get_idempotency(owner_id=OWNER, key="identity-key")
    assert record is not None
    wrong_snapshot = original.model_copy(update={"id": "tag_other"})
    repo.save_idempotency(
        owner_id=OWNER,
        record=record.model_copy(
            update={"response_body": wrong_snapshot.model_dump(mode="json")}
        ),
    )
    enabled[0] = True

    with allure.step("Do not adopt a legacy snapshot under a different resource ID"):
        with pytest.raises(SyncCommandError) as error:
            service.create_tag(payload, owner_id=OWNER, idempotency_key="identity-key")
        assert error.value.code == "COMMAND_INTEGRITY"
        assert repo.get_tag_for_owner(original.id, owner_id=OWNER) == original
        assert _count(repo, "sync_command_receipts") == 0
        assert _count(repo, "sync_change_transactions") == 0


def test_026_FR_005_adopted_legacy_snapshot_keeps_original_retention_deadline(
    legacy_service,
):
    service, repo, enabled, clock = legacy_service
    payload = TagCreateRequest(name="@Work")
    enabled[0] = False
    clock[0] = NOW - timedelta(hours=23)
    original = service.create_tag(payload, owner_id=OWNER, idempotency_key="old-key")
    enabled[0] = True
    clock[0] = NOW

    with allure.step("Adopt the still-retained legacy result without copying its TTL"):
        adopted = service.create_tag(payload, owner_id=OWNER, idempotency_key="old-key")
        assert adopted == original
        assert _count(repo, "sync_change_transactions") == 0

    repo.save_tag(original.model_copy(update={"name": "Renamed", "revision": 2}))
    clock[0] = NOW + timedelta(hours=2)
    with allure.step("After the legacy deadline, replay resolves only the current tag"):
        replay = service.create_tag(payload, owner_id=OWNER, idempotency_key="old-key")
        assert replay.id == original.id
        assert replay.name == "Renamed"
        assert _count(repo, "sync_change_transactions") == 0


@pytest.mark.parametrize("failure_point", ["feed", "receipt"])
def test_026_FR_005_tag_receipt_failure_rolls_back_every_write(
    legacy_service, monkeypatch, failure_point
):
    service, repo, _enabled, _clock = legacy_service
    handler = service._legacy_tag_handler
    assert handler is not None

    def fail_finalization(*_args, **_kwargs):
        raise RuntimeError(f"injected {failure_point} finalization failure")

    if failure_point == "feed":
        monkeypatch.setattr(handler._receipts.change_log, "append", fail_finalization)
    else:
        # _insert runs after append, so this proves the staged feed rolls back too.
        monkeypatch.setattr(handler._receipts, "_insert", fail_finalization)
    with allure.step(f"Fail {failure_point} finalization and roll back all writes"):
        with pytest.raises(
            RuntimeError, match=f"injected {failure_point} finalization failure"
        ):
            service.create_tag(
                TagCreateRequest(name="@Work"),
                owner_id=OWNER,
                idempotency_key="rollback-key",
            )
        assert repo.list_tags_for_owner(owner_id=OWNER) == []
        assert repo.get_idempotency(owner_id=OWNER, key="rollback-key") is None
        assert not repo.idempotency_path(OWNER, "rollback-key").exists()
        assert _count(repo, "sync_command_receipts") == 0
        assert _count(repo, "sync_change_transactions") == 0


def test_026_FR_005_expired_legacy_rows_never_resurrect_missing_tags(legacy_service):
    service, repo, enabled, clock = legacy_service
    enabled[0] = False
    clock[0] = NOW - timedelta(hours=26)
    current_snapshot = service.create_tag(
        TagCreateRequest(name="@Current"),
        owner_id=OWNER,
        idempotency_key="expired-current",
    )
    repo.save_tag(
        current_snapshot.model_copy(update={"name": "Renamed", "revision": 2})
    )
    enabled[0] = True
    clock[0] = NOW

    with allure.step("Use the current same-ID record after legacy result expiry"):
        current = service.create_tag(
            TagCreateRequest(name="@Current"),
            owner_id=OWNER,
            idempotency_key="expired-current",
        )
        assert current.id == current_snapshot.id
        assert current.name == "Renamed"
        assert _count(repo, "sync_change_transactions") == 0

    with allure.step("Keep an expired missing identity unavailable and bound"):
        missing_payload = TagCreateRequest(name="@Missing")
        missing_snapshot = current_snapshot.model_copy(
            update={"id": "tag_missing", "name": "Missing"}
        )
        repo.save_idempotency(
            owner_id=OWNER,
            record=IdempotencyRecord(
                key="expired-missing",
                command="create_tag",
                request_hash=service._request_hash("create_tag", missing_payload),
                resource_id=missing_snapshot.id,
                response_body=missing_snapshot.model_dump(mode="json"),
                created_at=NOW - timedelta(hours=25),
            ),
        )
        with pytest.raises(IdempotencyReceiptUnavailableError):
            service.create_tag(
                missing_payload,
                owner_id=OWNER,
                idempotency_key="expired-missing",
            )
        assert repo.list_tags_for_owner(owner_id=OWNER) == [current]
        assert _count(repo, "sync_command_receipts") == 2
        with pytest.raises(IdempotencyReceiptUnavailableError):
            service.create_tag(
                missing_payload,
                owner_id=OWNER,
                idempotency_key="expired-missing",
            )
        with pytest.raises(ConflictError):
            service.create_tag(
                TagCreateRequest(name="@Different"),
                owner_id=OWNER,
                idempotency_key="expired-missing",
            )
        assert repo.list_tags_for_owner(owner_id=OWNER) == [current]


@pytest.mark.parametrize("missing_current", [False, True])
def test_026_FR_005_exact_legacy_deadline_uses_only_current_bound_tag(
    legacy_service, missing_current
):
    service, repo, enabled, clock = legacy_service
    payload = TagCreateRequest(name="@Deadline")
    key = "exact-deadline"
    enabled[0] = False
    clock[0] = NOW - timedelta(hours=24)
    original = service.create_tag(payload, owner_id=OWNER, idempotency_key=key)

    if missing_current:
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute(
                "DELETE FROM tags WHERE owner_id = ? AND id = ?",
                (OWNER, original.id),
            )
    else:
        repo.save_tag(original.model_copy(update={"name": "Current", "revision": 2}))

    enabled[0] = True
    clock[0] = NOW
    with allure.step("At exactly 24 hours, resolve only the bound current tag"):
        if missing_current:
            with pytest.raises(IdempotencyReceiptUnavailableError):
                service.create_tag(payload, owner_id=OWNER, idempotency_key=key)
            assert repo.list_tags_for_owner(owner_id=OWNER) == []
        else:
            current = service.create_tag(payload, owner_id=OWNER, idempotency_key=key)
            assert current.id == original.id
            assert current.name == "Current"

    with allure.step("Retry the adopted key without restoring its expired snapshot"):
        if missing_current:
            with pytest.raises(IdempotencyReceiptUnavailableError):
                service.create_tag(payload, owner_id=OWNER, idempotency_key=key)
            assert repo.list_tags_for_owner(owner_id=OWNER) == []
        else:
            repo.save_tag(
                current.model_copy(update={"name": "Current again", "revision": 3})
            )
            replay = service.create_tag(payload, owner_id=OWNER, idempotency_key=key)
            assert replay.id == original.id
            assert replay.name == "Current again"

    assert _count(repo, "sync_command_receipts") == 1
    assert _count(repo, "sync_change_transactions") == 0
    assert _count(repo, "sync_change_records") == 0


@pytest.mark.parametrize("missing_current", [False, True])
def test_026_FR_005_adopted_legacy_replay_uses_current_at_original_deadline(
    legacy_service, missing_current
):
    service, repo, enabled, clock = legacy_service
    payload = TagCreateRequest(name="@Adopted")
    key = "adopted-exact-deadline"
    enabled[0] = False
    clock[0] = NOW - timedelta(hours=23)
    original = service.create_tag(payload, owner_id=OWNER, idempotency_key=key)

    enabled[0] = True
    clock[0] = NOW
    adopted = service.create_tag(payload, owner_id=OWNER, idempotency_key=key)
    assert adopted == original
    assert _count(repo, "sync_command_receipts") == 1
    assert _count(repo, "sync_change_transactions") == 0

    clock[0] = NOW + timedelta(hours=1)
    if missing_current:
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute(
                "DELETE FROM tags WHERE owner_id = ? AND id = ?",
                (OWNER, original.id),
            )
    else:
        repo.save_tag(original.model_copy(update={"name": "Current", "revision": 2}))

    with allure.step("At the original 24-hour deadline, use current state only"):
        if missing_current:
            with pytest.raises(IdempotencyReceiptUnavailableError):
                service.create_tag(payload, owner_id=OWNER, idempotency_key=key)
            assert repo.list_tags_for_owner(owner_id=OWNER) == []
        else:
            replay = service.create_tag(payload, owner_id=OWNER, idempotency_key=key)
            assert replay.id == original.id
            assert replay.name == "Current"

    assert _count(repo, "sync_command_receipts") == 1
    assert _count(repo, "sync_change_transactions") == 0
    assert _count(repo, "sync_change_records") == 0


def test_026_FR_005_legacy_tag_update_uses_owner_receipt_and_feed(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    original = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="create"
    )
    payload = TagUpdateRequest(name="@Home", expected_revision=original.revision)

    with allure.step("Update once and replay the owner-scoped result"):
        updated = service.update_tag(
            original.id, payload, owner_id=OWNER, idempotency_key="update"
        )
        replay = service.update_tag(
            original.id, payload, owner_id=OWNER, idempotency_key="update"
        )
        assert replay == updated
        assert repo.get_tag_for_owner(original.id, owner_id=OWNER) == updated
        assert _count(repo, "sync_command_receipts") == 2
        assert _count(repo, "sync_change_transactions") == 2
        assert _count(repo, "sync_change_records") == 2

    with allure.step("Reject operation and body reuse under the same legacy key"):
        with pytest.raises(ConflictError):
            service.create_tag(
                TagCreateRequest(name="@Other"),
                owner_id=OWNER,
                idempotency_key="update",
            )
        with pytest.raises(ConflictError):
            service.update_tag(
                original.id,
                TagUpdateRequest(name="@Else", expected_revision=original.revision),
                owner_id=OWNER,
                idempotency_key="update",
            )
        assert _count(repo, "sync_change_transactions") == 2


def test_026_FR_005_tag_update_receipt_distinguishes_omitted_nullable_name(
    legacy_service,
):
    service, repo, _enabled, _clock = legacy_service
    original = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="create"
    )
    omitted_name = TagUpdateRequest(expected_revision=original.revision)

    with allure.step("Replay omitted name and reject explicit null under the same key"):
        updated = service.update_tag(
            original.id, omitted_name, owner_id=OWNER, idempotency_key="tag-update"
        )
        assert (
            service.update_tag(
                original.id,
                omitted_name,
                owner_id=OWNER,
                idempotency_key="tag-update",
            )
            == updated
        )
        receipts = _count(repo, "sync_command_receipts")
        transactions = _count(repo, "sync_change_transactions")
        records = _count(repo, "sync_change_records")

        with pytest.raises(ConflictError):
            service.update_tag(
                original.id,
                TagUpdateRequest(name=None, expected_revision=original.revision),
                owner_id=OWNER,
                idempotency_key="tag-update",
            )

        assert repo.get_tag_for_owner(original.id, owner_id=OWNER) == updated
        assert _count(repo, "sync_command_receipts") == receipts
        assert _count(repo, "sync_change_transactions") == transactions
        assert _count(repo, "sync_change_records") == records


def test_026_FR_005_legacy_tag_update_failure_rolls_back_resource_receipt_and_feed(
    legacy_service, monkeypatch
):
    service, repo, _enabled, _clock = legacy_service
    original = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="create"
    )
    handler = service._legacy_tag_handler
    assert handler is not None
    monkeypatch.setattr(
        handler._receipts.change_log,
        "append",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("injected update finalization failure")
        ),
    )

    with allure.step("Rollback the tag update when feed finalization fails"):
        with pytest.raises(RuntimeError, match="injected update finalization failure"):
            service.update_tag(
                original.id,
                TagUpdateRequest(name="@Home", expected_revision=original.revision),
                owner_id=OWNER,
                idempotency_key="update-failure",
            )
        assert repo.get_tag_for_owner(original.id, owner_id=OWNER) == original
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 1


def test_026_FR_005_tag_update_refusal_is_durable_after_revision_catches_up(
    legacy_service,
):
    service, repo, _enabled, _clock = legacy_service
    tag = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="create"
    )
    future = TagUpdateRequest(name="@Bad", expected_revision=tag.revision + 1)
    with allure.step("Persist rejected update before the expected revision exists"):
        with pytest.raises(ConflictError):
            service.update_tag(tag.id, future, owner_id=OWNER, idempotency_key="future")
        assert _count(repo, "sync_command_receipts") == 2
    service.update_tag(
        tag.id,
        TagUpdateRequest(name="@Good", expected_revision=tag.revision),
        owner_id=OWNER,
        idempotency_key="advance",
    )
    with allure.step("Replay the original refusal even after revision advances"):
        with pytest.raises(ConflictError):
            service.update_tag(tag.id, future, owner_id=OWNER, idempotency_key="future")
        assert repo.get_tag_for_owner(tag.id, owner_id=OWNER).name == "Good"


def test_026_FR_005_legacy_tag_update_retains_key_after_result_redaction(
    legacy_service,
):
    service, repo, _enabled, clock = legacy_service
    original = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="create"
    )
    payload = TagUpdateRequest(name="@Home", expected_revision=original.revision)
    updated = service.update_tag(
        original.id, payload, owner_id=OWNER, idempotency_key="update"
    )
    command_id = _receipt_command_id(repo, "update")
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        )
    clock[0] = NOW + timedelta(hours=25)

    with allure.step("Replay the retained update through its current tag identity"):
        replay = service.update_tag(
            original.id, payload, owner_id=OWNER, idempotency_key="update"
        )
        assert replay == repo.get_tag_for_owner(original.id, owner_id=OWNER)
        assert replay == updated
        assert _count(repo, "sync_change_transactions") == 2


def test_026_FR_005_legacy_tag_update_is_owner_scoped(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    first = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="create-a"
    )
    other = service.create_tag(
        TagCreateRequest(name="@Work"),
        owner_id="other-owner",
        idempotency_key="create-b",
    )
    updated = service.update_tag(
        first.id,
        TagUpdateRequest(name="@Home", expected_revision=first.revision),
        owner_id=OWNER,
        idempotency_key="same-update-key",
    )

    with allure.step("Do not cross owner boundaries on same key or tag ID"):
        with pytest.raises(NotFoundError):
            service.update_tag(
                first.id,
                TagUpdateRequest(name="@Other", expected_revision=other.revision),
                owner_id="other-owner",
                idempotency_key="same-update-key",
            )
        assert repo.get_tag_for_owner(first.id, owner_id=OWNER) == updated
        assert repo.get_tag_for_owner(other.id, owner_id="other-owner") == other


def test_026_FR_005_redacted_fresh_receipt_never_falls_back_to_legacy_snapshot(
    legacy_service,
):
    service, repo, _enabled, _clock = legacy_service
    payload = TagCreateRequest(name="@Work")
    original = service.create_tag(payload, owner_id=OWNER, idempotency_key="redacted")
    repo.save_tag(original.model_copy(update={"name": "Current", "revision": 2}))
    command_id = _receipt_command_id(repo, "redacted")

    with (
        allure.step("Redact the accepted receipt result while retaining its alias"),
        sqlite3.connect(repo.db_path) as conn,
    ):
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL "
            "WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        )

    with allure.step("Resolve replay from the bound current row, never old text"):
        replay = service.create_tag(payload, owner_id=OWNER, idempotency_key="redacted")
        assert replay.id == original.id
        assert replay.name == "Current"
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 1
        assert repo.get_tag_for_owner(original.id, owner_id=OWNER).name == "Current"


def test_026_FR_005_legacy_tag_delete_replays_one_tombstone(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    tag = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="create"
    )
    payload = ExpectedRevisionRequest(expected_revision=tag.revision)

    deleted = service.delete_tag(
        tag.id, payload, owner_id=OWNER, idempotency_key="delete"
    )
    replay = service.delete_tag(
        tag.id, payload, owner_id=OWNER, idempotency_key="delete"
    )

    assert deleted.state == replay.state == "deleted"
    assert deleted.id == replay.id == tag.id
    assert _count(repo, "sync_command_receipts") == 2
    assert _count(repo, "sync_change_transactions") == 2
    assert _count(repo, "sync_change_records") == 2

    with sqlite3.connect(repo.db_path) as conn:
        receipt = conn.execute(
            "SELECT result FROM sync_command_receipts WHERE owner_id = ? "
            "AND command_id = (SELECT command_id FROM sync_legacy_keys "
            "WHERE owner_id = ? AND key_digest = ?)",
            (OWNER, OWNER, idempotency_key_digest("delete")),
        ).fetchone()
        change = conn.execute(
            "SELECT operation, value FROM sync_change_records "
            "WHERE owner_id = ? ORDER BY rowid DESC LIMIT 1",
            (OWNER,),
        ).fetchone()
    assert receipt[0] is None
    assert change == ("tombstone", None)


def test_026_FR_005_legacy_tag_delete_rejects_reused_key_and_foreign_owner(
    legacy_service,
):
    service, repo, _enabled, _clock = legacy_service
    tag = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="create"
    )
    payload = ExpectedRevisionRequest(expected_revision=tag.revision)
    service.delete_tag(tag.id, payload, owner_id=OWNER, idempotency_key="delete")

    with pytest.raises(ConflictError):
        service.delete_tag(
            tag.id,
            ExpectedRevisionRequest(expected_revision=tag.revision + 1),
            owner_id=OWNER,
            idempotency_key="delete",
        )
    with pytest.raises(NotFoundError):
        service.delete_tag(
            tag.id,
            payload,
            owner_id="user_other",
            idempotency_key="other-delete",
        )
    assert repo.list_tags_for_owner(owner_id="user_other") == []


def test_026_FR_005_tag_delete_refusal_cannot_be_retried_after_revision_advances(
    legacy_service,
):
    service, repo, _enabled, _clock = legacy_service
    tag = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="create"
    )
    future = ExpectedRevisionRequest(expected_revision=tag.revision + 1)
    with allure.step("Record the first stale delete as a rejected receipt"):
        with pytest.raises(ConflictError):
            service.delete_tag(tag.id, future, owner_id=OWNER, idempotency_key="future")
        assert _count(repo, "sync_command_receipts") == 2
    updated = service.update_tag(
        tag.id,
        TagUpdateRequest(name="@New", expected_revision=tag.revision),
        owner_id=OWNER,
        idempotency_key="update",
    )
    with allure.step("Do not delete a newer tag when the key is retried"):
        with pytest.raises(ConflictError):
            service.delete_tag(tag.id, future, owner_id=OWNER, idempotency_key="future")
        assert repo.get_tag_for_owner(tag.id, owner_id=OWNER) == updated


def test_026_FR_005_legacy_project_create_uses_owner_receipt_and_redacted_replay(
    legacy_service,
):
    service, repo, _enabled, clock = legacy_service
    payload = ProjectCreateRequest(name="Project", desired_outcome="Ship it")
    with allure.step("Create project and record its owner-scoped receipt"):
        created = service.create_project(
            payload, owner_id=OWNER, idempotency_key="project-create"
        )
    assert (
        service.create_project(
            payload, owner_id=OWNER, idempotency_key="project-create"
        )
        == created
    )
    with pytest.raises(ConflictError):
        service.create_project(
            ProjectCreateRequest(name="Other"),
            owner_id=OWNER,
            idempotency_key="project-create",
        )
    assert (
        service.create_project(
            payload, owner_id="other-owner", idempotency_key="project-create"
        ).owner_id
        == "other-owner"
    )
    command_id = _receipt_command_id(repo, "project-create")
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        )
    clock[0] = NOW + timedelta(hours=25)
    replay = service.create_project(
        payload, owner_id=OWNER, idempotency_key="project-create"
    )
    assert replay == repo.get_project_for_owner(created.id, owner_id=OWNER)
    assert _count(repo, "sync_change_transactions") == 2


def test_026_FR_005_project_rejection_replays_after_name_becomes_available(
    legacy_service,
):
    service, repo, _enabled, clock = legacy_service
    original = service.create_project(
        ProjectCreateRequest(name="Taken"), owner_id=OWNER, idempotency_key="first"
    )
    with (
        allure.step("Reject duplicate project name under an immutable command key"),
        pytest.raises(ConflictError) as initial,
    ):
        service.create_project(
            ProjectCreateRequest(name="Taken"),
            owner_id=OWNER,
            idempotency_key="duplicate",
        )
    service.update_project(
        original.id,
        ProjectUpdateRequest(name="Renamed", expected_revision=original.revision),
        owner_id=OWNER,
        idempotency_key="rename",
    )
    with (
        allure.step("Replay rejection rather than creating after the name is freed"),
        pytest.raises(ConflictError) as replay,
    ):
        service.create_project(
            ProjectCreateRequest(name="Taken"),
            owner_id=OWNER,
            idempotency_key="duplicate",
        )
    with allure.step("Check rejected retry did not create another project"):
        assert str(replay.value) == str(initial.value)
        assert len(repo.list_projects_for_owner(owner_id=OWNER)) == 1
        allure.attach(
            str(_count(repo, "sync_command_receipts")), name="Committed receipt count"
        )
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("Keep the original refusal after full response retention ends"):
        with pytest.raises(ConflictError) as retained:
            service.create_project(
                ProjectCreateRequest(name="Taken"),
                owner_id=OWNER,
                idempotency_key="duplicate",
            )
        assert str(retained.value) == str(initial.value)
        allure.attach(
            str(_count(repo, "sync_command_receipts")), name="Retained receipt count"
        )


def test_026_FR_005_project_adopts_legacy_key_without_duplicate_mutation(
    legacy_service,
):
    service, repo, enabled, _clock = legacy_service
    payload = ProjectCreateRequest(name="Legacy")
    enabled[0] = False
    with allure.step("Create project under the old idempotency record"):
        original = service.create_project(
            payload, owner_id=OWNER, idempotency_key="old-project"
        )
    enabled[0] = True
    with allure.step("Adopt old response without recreating the project"):
        assert (
            service.create_project(
                payload, owner_id=OWNER, idempotency_key="old-project"
            )
            == original
        )
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 0


def test_026_FR_005_project_key_cannot_be_reused_by_task(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    with allure.step("Create a project using the owner-scoped legacy key"):
        service.create_project(
            ProjectCreateRequest(name="Project"),
            owner_id=OWNER,
            idempotency_key="shared-key",
        )
    with (
        allure.step("Refuse the same key when a task writer changes the operation"),
        pytest.raises(ConflictError),
    ):
        service.create_task(
            TaskCreateRequest(title="Task"),
            owner_id=OWNER,
            idempotency_key="shared-key",
        )
    assert repo.list_for_owner(owner_id=OWNER) == []


@pytest.mark.parametrize("kind", ["task", "project", "smart_add"])
@pytest.mark.parametrize("corruption", ["malformed", "foreign_owner"])
def test_026_FR_005_legacy_creation_replay_rejects_corrupt_receipt(
    legacy_service, kind, corruption
):
    service, repo, _enabled, _clock = legacy_service
    if kind == "task":
        payload = TaskCreateRequest(title="Task")
        create = service.create_task
    elif kind == "project":
        payload = ProjectCreateRequest(name="Project")
        create = service.create_project
    else:
        payload = SmartAddTaskCreateRequest(title="Smart")
        create = service.smart_add_task
    create(payload, owner_id=OWNER, idempotency_key="receipt")
    with sqlite3.connect(repo.db_path) as conn:
        stored = conn.execute(
            "SELECT result FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
            (OWNER, _receipt_command_id(repo, "receipt")),
        ).fetchone()
    assert stored is not None
    bad_result = {} if corruption == "malformed" else json.loads(stored[0])
    if corruption == "foreign_owner":
        if kind in {"smart_add", "task"}:
            bad_result["task"]["owner_id"] = "other-owner"
        else:
            bad_result["owner_id"] = "other-owner"
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET result = ? WHERE owner_id = ? AND command_id = ?",
            (json.dumps(bad_result), OWNER, _receipt_command_id(repo, "receipt")),
        )
    with allure.step("Corrupted receipt fails closed without another domain write"):
        with pytest.raises(SyncCommandError) as error:
            create(payload, owner_id=OWNER, idempotency_key="receipt")
        assert error.value.code == "COMMAND_INTEGRITY"
        assert _count(repo, "sync_change_transactions") == 1


@pytest.mark.parametrize("kind", ["task", "project", "tag_update"])
@pytest.mark.parametrize("missing_record", [False, True])
def test_026_FR_005_redacted_legacy_replay_requires_binding_and_record(
    legacy_service, kind, missing_record
):
    service, repo, _enabled, clock = legacy_service
    if kind == "task":
        payload = TaskCreateRequest(title="Task")

        def invoke():
            return service.create_task(
                payload, owner_id=OWNER, idempotency_key="receipt"
            )

        table = "tasks"
    elif kind == "project":
        payload = ProjectCreateRequest(name="Project")

        def invoke():
            return service.create_project(
                payload, owner_id=OWNER, idempotency_key="receipt"
            )

        table = "projects"
    else:
        tag = service.create_tag(
            TagCreateRequest(name="@Tag"), owner_id=OWNER, idempotency_key="create"
        )
        payload = TagUpdateRequest(name="@Updated", expected_revision=tag.revision)

        def invoke():
            return service.update_tag(
                tag.id, payload, owner_id=OWNER, idempotency_key="receipt"
            )

        table = "tags"
    original = invoke()
    command_id = _receipt_command_id(repo, "receipt")
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        )
        if missing_record:
            conn.execute(
                f"DELETE FROM {table} WHERE id = ?", (original.id,)
            )  # noqa: S608
        else:
            row = conn.execute(
                "SELECT metadata FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
                (OWNER, command_id),
            ).fetchone()
            assert row is not None
            metadata = json.loads(row[0])
            metadata["id_bindings"] = []
            conn.execute(
                "UPDATE sync_command_receipts SET metadata = ? WHERE owner_id = ? AND command_id = ?",
                (json.dumps(metadata), OWNER, command_id),
            )
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("A redacted result cannot guess missing identity or state"):
        expected = (
            IdempotencyReceiptUnavailableError if missing_record else SyncCommandError
        )
        with pytest.raises(expected):
            invoke()
        allure.attach(
            str(_count(repo, "sync_change_transactions")), name="Unchanged feed count"
        )


def test_026_FR_005_legacy_task_create_receipt_replay_and_redaction(legacy_service):
    service, repo, _enabled, clock = legacy_service
    payload = TaskCreateRequest(title="Created once")
    with allure.step("Create a task and replay its response settings snapshot"):
        original = service.create_task_result(
            payload, owner_id=OWNER, idempotency_key="task-create"
        )
        assert (
            service.create_task_result(
                payload, owner_id=OWNER, idempotency_key="task-create"
            )
            == original
        )
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 1
    with allure.step("Reject changed body and retain owner isolation"):
        with pytest.raises(ConflictError):
            service.create_task(
                TaskCreateRequest(title="Changed"),
                owner_id=OWNER,
                idempotency_key="task-create",
            )
        assert (
            service.create_task(
                payload, owner_id="other-owner", idempotency_key="task-create"
            ).owner_id
            == "other-owner"
        )
    command_id = _receipt_command_id(repo, "task-create")
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        )
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("Resolve a redacted response from the retained task alias"):
        replay = service.create_task_result(
            payload, owner_id=OWNER, idempotency_key="task-create"
        )
        assert replay.task == original.task
        assert replay.formulation_settings is None
        assert _count(repo, "sync_change_transactions") == 2


def test_026_FR_005_legacy_task_create_adopts_old_key_and_rolls_back(
    legacy_service, monkeypatch
):
    service, repo, enabled, _clock = legacy_service
    payload = TaskCreateRequest(title="Legacy")
    enabled[0] = False
    with allure.step("Create with the old idempotency store"):
        original = service.create_task_result(
            payload, owner_id=OWNER, idempotency_key="old-task"
        )
    enabled[0] = True
    with allure.step("Adopt its result without a duplicate task mutation"):
        assert (
            service.create_task_result(
                payload, owner_id=OWNER, idempotency_key="old-task"
            )
            == original
        )
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 0
        assert len(repo.list_for_owner(owner_id=OWNER)) == 1
    handler = service._legacy_tag_handler
    assert handler is not None
    monkeypatch.setattr(
        handler._receipts.change_log,
        "append",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("feed failed")),
    )
    with (
        allure.step("Roll back task and receipt together on feed failure"),
        pytest.raises(RuntimeError, match="feed failed"),
    ):
        service.create_task(
            TaskCreateRequest(title="New"),
            owner_id=OWNER,
            idempotency_key="failed-task",
        )
    assert len(repo.list_for_owner(owner_id=OWNER)) == 1
    assert _count(repo, "sync_command_receipts") == 1


def test_026_FR_005_legacy_task_create_replays_rejection_after_reference_appears(
    legacy_service,
):
    service, repo, _enabled, _clock = legacy_service
    payload = TaskCreateRequest(title="Task", project_id="project_missing")
    with (
        allure.step("Commit an invalid-reference refusal under the task command key"),
        pytest.raises(NotFoundError),
    ):
        service.create_task(payload, owner_id=OWNER, idempotency_key="missing-project")
    with (
        allure.step("Replay the original refusal without creating a task"),
        pytest.raises(NotFoundError),
    ):
        service.create_task(payload, owner_id=OWNER, idempotency_key="missing-project")
    assert repo.list_for_owner(owner_id=OWNER) == []
    assert _count(repo, "sync_command_receipts") == 1
    assert _count(repo, "sync_change_transactions") == 0


def test_026_FR_005_legacy_task_mutations_adopt_old_keys_without_reexecution(
    legacy_service,
):
    service, repo, enabled, clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Task"), owner_id=OWNER, idempotency_key="create"
    )
    update = TaskUpdateRequest(title="Edited", expected_revision=task.revision)
    enabled[0] = False
    old_update = service.update_task_result(
        task.id, update, owner_id=OWNER, idempotency_key="old-update"
    )
    transition = TaskTransitionRequest(
        action="complete", expected_revision=old_update.task.revision
    )
    old_transition = service.transition_task_result(
        task.id, transition, owner_id=OWNER, idempotency_key="old-transition"
    )
    enabled[0] = True
    with allure.step("Adopt both immutable legacy mutations as receipt-only commands"):
        assert (
            service.update_task_result(
                task.id, update, owner_id=OWNER, idempotency_key="old-update"
            )
            == old_update
        )
        assert (
            service.transition_task_result(
                task.id, transition, owner_id=OWNER, idempotency_key="old-transition"
            )
            == old_transition
        )
        assert repo.get_for_owner(task.id, owner_id=OWNER) == old_transition.task
        assert _count(repo, "sync_change_transactions") == 1
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("Redacted adopted update falls back to the current task"):
        assert (
            service.update_task_result(
                task.id, update, owner_id=OWNER, idempotency_key="old-update"
            ).task
            == old_transition.task
        )
        assert _count(repo, "sync_change_transactions") == 1


@pytest.mark.parametrize("operation", ["update", "transition"])
@pytest.mark.parametrize("missing", [False, True])
def test_026_FR_005_expired_task_mutation_adoption_uses_current_record_only(
    legacy_service, operation, missing
):
    service, repo, enabled, clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Task"), owner_id=OWNER, idempotency_key="created"
    )
    payload = (
        TaskUpdateRequest(title="Edited", expected_revision=task.revision)
        if operation == "update"
        else TaskTransitionRequest(action="complete", expected_revision=task.revision)
    )
    command = (
        service.update_task_result
        if operation == "update"
        else service.transition_task_result
    )
    enabled[0] = False
    command(task.id, payload, owner_id=OWNER, idempotency_key="old-mutation")
    if missing:
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute("DELETE FROM tasks WHERE owner_id = ?", (OWNER,))
    clock[0] = NOW + timedelta(hours=25)
    enabled[0] = True
    before_receipts = _count(repo, "sync_command_receipts")
    before_changes = _count(repo, "sync_change_transactions")
    with allure.step("Adopt an expired mutation without resurrecting its old snapshot"):
        if missing:
            with pytest.raises(IdempotencyReceiptUnavailableError):
                command(
                    task.id, payload, owner_id=OWNER, idempotency_key="old-mutation"
                )
            assert _count(repo, "sync_command_receipts") == before_receipts
        else:
            current = repo.get_for_owner(task.id, owner_id=OWNER)
            assert (
                command(
                    task.id, payload, owner_id=OWNER, idempotency_key="old-mutation"
                ).task
                == current
            )
            assert _count(repo, "sync_command_receipts") == before_receipts + 1
        assert _count(repo, "sync_change_transactions") == before_changes


@pytest.mark.parametrize("missing", [False, True])
def test_026_FR_005_expired_legacy_task_adoption_never_resurrects_data(
    legacy_service,
    missing,
):
    service, repo, enabled, clock = legacy_service
    payload = TaskCreateRequest(title="Legacy task")
    enabled[0] = False
    original = service.create_task(payload, owner_id=OWNER, idempotency_key="old")
    if missing:
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute("DELETE FROM tasks WHERE owner_id = ?", (OWNER,))
    clock[0] = NOW + timedelta(hours=25)
    enabled[0] = True
    with allure.step("Adopt only a currently available legacy task after expiry"):
        if missing:
            with pytest.raises(IdempotencyReceiptUnavailableError):
                service.create_task(payload, owner_id=OWNER, idempotency_key="old")
            assert _count(repo, "sync_command_receipts") == 0
        else:
            assert (
                service.create_task(payload, owner_id=OWNER, idempotency_key="old")
                == original
            )
            assert _count(repo, "sync_change_transactions") == 0


def test_026_FR_005_legacy_task_update_and_transition_use_atomic_receipts(
    legacy_service, monkeypatch
):
    service, repo, _enabled, clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Task"), owner_id=OWNER, idempotency_key="created"
    )
    update = TaskUpdateRequest(title="Edited", expected_revision=task.revision)
    with allure.step("Update and replay the original task response"):
        changed = service.update_task_result(
            task.id, update, owner_id=OWNER, idempotency_key="updated"
        )
        assert (
            service.update_task_result(
                task.id, update, owner_id=OWNER, idempotency_key="updated"
            )
            == changed
        )
    transition = TaskTransitionRequest(
        action="complete", expected_revision=changed.task.revision
    )
    with allure.step("Transition and replay without a second mutation"):
        completed = service.transition_task_result(
            task.id, transition, owner_id=OWNER, idempotency_key="transitioned"
        )
        assert completed.task.state == "completed"
        assert (
            service.transition_task_result(
                task.id, transition, owner_id=OWNER, idempotency_key="transitioned"
            )
            == completed
        )
        assert _count(repo, "sync_command_receipts") == 3
        assert _count(repo, "sync_change_transactions") == 3
    with (
        allure.step("A project cannot reuse the transition command key"),
        pytest.raises(ConflictError),
    ):
        service.create_project(
            ProjectCreateRequest(name="No"),
            owner_id=OWNER,
            idempotency_key="transitioned",
        )
    with allure.step("After redaction the transition resolves its task alias"):
        clock[0] = NOW + timedelta(hours=25)
        replay = service.transition_task_result(
            task.id, transition, owner_id=OWNER, idempotency_key="transitioned"
        )
        assert replay.task == completed.task
        assert replay.formulation_settings is None
        allure.attach(str(replay.task.revision), name="Resolved task revision")
    handler = service._legacy_tag_handler
    assert handler is not None
    monkeypatch.setattr(
        handler._receipts.change_log,
        "append",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("feed failed")),
    )
    with (
        allure.step("Rollback an accepted task update when feed finalization fails"),
        pytest.raises(RuntimeError, match="feed failed"),
    ):
        service.update_task(
            task.id,
            TaskUpdateRequest(
                title="Should roll back", expected_revision=completed.task.revision
            ),
            owner_id=OWNER,
            idempotency_key="update-failure",
        )
    assert repo.get_for_owner(task.id, owner_id=OWNER) == completed.task
    assert _count(repo, "sync_command_receipts") == 3


def test_026_FR_005_task_mutation_refusals_are_durable(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Task"), owner_id=OWNER, idempotency_key="create"
    )
    future = TaskUpdateRequest(title="Wrong", expected_revision=task.revision + 1)
    with allure.step("Commit a stale update refusal without changing the task"):
        with pytest.raises(ConflictError):
            service.update_task(
                task.id, future, owner_id=OWNER, idempotency_key="future-update"
            )
        assert _count(repo, "sync_command_receipts") == 2
    changed = service.update_task(
        task.id,
        TaskUpdateRequest(title="Right", expected_revision=task.revision),
        owner_id=OWNER,
        idempotency_key="advance",
    )
    with allure.step(
        "A matching revision cannot turn the original refusal into a write"
    ):
        with pytest.raises(ConflictError):
            service.update_task(
                task.id, future, owner_id=OWNER, idempotency_key="future-update"
            )
        assert repo.get_for_owner(task.id, owner_id=OWNER) == changed
    with allure.step("Transition refusals also retain an immutable key"):
        transition = TaskTransitionRequest(
            action="complete", expected_revision=changed.revision + 1
        )
        for _ in range(2):
            with pytest.raises(ConflictError):
                service.transition_task(
                    task.id,
                    transition,
                    owner_id=OWNER,
                    idempotency_key="future-transition",
                )
        assert _count(repo, "sync_command_receipts") == 4


@pytest.mark.parametrize("action", ["complete", "cancel"])
def test_026_FR_005_closed_transition_replay_keeps_action_error(legacy_service, action):
    service, repo, _enabled, _clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Closed"), owner_id=OWNER, idempotency_key="closed"
    )
    closed = service.transition_task(
        task.id,
        TaskTransitionRequest(action="complete", expected_revision=task.revision),
        owner_id=OWNER,
        idempotency_key="close",
    )
    request = TaskTransitionRequest(action=action, expected_revision=closed.revision)
    with allure.step("Compare the first refusal with its durable retry"):
        with pytest.raises(ValidationFailure) as first:
            service.transition_task(
                task.id, request, owner_id=OWNER, idempotency_key="refused"
            )
        with pytest.raises(ValidationFailure) as replay:
            service.transition_task(
                task.id, request, owner_id=OWNER, idempotency_key="refused"
            )
        assert str(replay.value) == str(first.value)
        assert str(first.value) != "Task must be open to move."
        assert _count(repo, "sync_command_receipts") == 3


@pytest.mark.parametrize("kind", ["subtask", "comment"])
def test_026_FR_005_missing_child_retains_legacy_404_on_retry(legacy_service, kind):
    service, repo, _enabled, _clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    if kind == "subtask":
        call = partial(
            service.update_subtask,
            task.id,
            "missing",
            TaskSubtaskUpdateRequest(title="Changed", expected_revision=1),
        )
    else:
        call = partial(
            service.update_comment,
            task.id,
            "missing",
            TaskCommentUpdateRequest(body="Changed", expected_revision=1),
        )
    with allure.step("Return the same missing-child resource on first call and retry"):
        with pytest.raises(NotFoundError) as original:
            call(owner_id=OWNER, idempotency_key="missing-child")
        with pytest.raises(NotFoundError) as replay:
            call(owner_id=OWNER, idempotency_key="missing-child")
        assert replay.value.resource == original.value.resource == f"Task {kind}"
        assert str(replay.value) == str(original.value)
        assert _count(repo, "sync_command_receipts") == 2


def test_026_FR_005_child_replay_returns_newer_current_revision(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    payload = TaskSubtaskCreateRequest(title="Before")
    child = service.create_subtask(
        parent.id, payload, owner_id=OWNER, idempotency_key="child"
    )
    updated = service.update_subtask(
        parent.id,
        child.id,
        TaskSubtaskUpdateRequest(title="After", expected_revision=child.revision),
        owner_id=OWNER,
        idempotency_key="update",
    )
    with allure.step("Replay the create response without losing the newer child"):
        assert (
            service.create_subtask(
                parent.id, payload, owner_id=OWNER, idempotency_key="child"
            )
            == updated
        )
        assert (
            repo.get_subtask_for_owner(child.id, owner_id=OWNER, task_id=parent.id)
            == updated
        )


@pytest.mark.parametrize("kind", ["subtask", "comment"])
@pytest.mark.parametrize("stored_revision", [None, 1])
def test_026_FR_005_child_replay_refuses_missing_or_older_projection(
    legacy_service, kind, stored_revision
):
    service, repo, _enabled, _clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    payload = (
        TaskSubtaskCreateRequest(title="Child")
        if kind == "subtask"
        else TaskCommentCreateRequest(body="Child")
    )
    kwargs = {"actor_id": OWNER} if kind == "comment" else {}
    create = getattr(service, f"create_{kind}")
    child = create(
        parent.id, payload, owner_id=OWNER, idempotency_key="child", **kwargs
    )
    update = None
    update_payload = None
    if stored_revision is not None:
        update = getattr(service, f"update_{kind}")
        update_payload = (
            TaskSubtaskUpdateRequest(title="Updated", expected_revision=child.revision)
            if kind == "subtask"
            else TaskCommentUpdateRequest(
                body="Updated", expected_revision=child.revision
            )
        )
        child = update(
            parent.id,
            child.id,
            update_payload,
            owner_id=OWNER,
            idempotency_key="update",
        )
    table = "subtasks" if kind == "subtask" else "comments"
    with sqlite3.connect(repo.db_path) as conn:
        if stored_revision is None:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (child.id,))
        else:
            conn.execute(
                f"UPDATE {table} SET payload = json_set(payload, '$.revision', ?) WHERE id = ?",
                (stored_revision, child.id),
            )
    before = _count(repo, "sync_change_transactions")
    with allure.step(
        "A known child receipt cannot repair a missing or older projection"
    ):
        if stored_revision is None:
            with pytest.raises(IdempotencyReceiptUnavailableError):
                create(
                    parent.id,
                    payload,
                    owner_id=OWNER,
                    idempotency_key="child",
                    **kwargs,
                )
        else:
            assert update is not None and update_payload is not None
            with pytest.raises(IdempotencyReceiptUnavailableError):
                update(
                    parent.id,
                    child.id,
                    update_payload,
                    owner_id=OWNER,
                    idempotency_key="update",
                )
        assert _count(repo, "sync_change_transactions") == before
        if stored_revision is None:
            with pytest.raises(NotFoundError):
                getattr(repo, f"get_{kind}_for_owner")(
                    child.id, owner_id=OWNER, task_id=parent.id
                )
        else:
            assert (
                getattr(repo, f"get_{kind}_for_owner")(
                    child.id, owner_id=OWNER, task_id=parent.id
                ).revision
                == stored_revision
            )


@pytest.mark.parametrize("kind", ["subtask", "comment"])
def test_026_FR_005_redacted_child_replay_refuses_older_projection(
    legacy_service, kind
):
    service, repo, _enabled, clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    payload = (
        TaskSubtaskCreateRequest(title="Child")
        if kind == "subtask"
        else TaskCommentCreateRequest(body="Child")
    )
    kwargs = {"actor_id": OWNER} if kind == "comment" else {}
    child = getattr(service, f"create_{kind}")(
        parent.id, payload, owner_id=OWNER, idempotency_key="child", **kwargs
    )
    update_payload = (
        TaskSubtaskUpdateRequest(title="Updated", expected_revision=child.revision)
        if kind == "subtask"
        else TaskCommentUpdateRequest(body="Updated", expected_revision=child.revision)
    )
    getattr(service, f"update_{kind}")(
        parent.id, child.id, update_payload, owner_id=OWNER, idempotency_key="update"
    )
    clock[0] = NOW + timedelta(hours=25)
    table = "subtasks" if kind == "subtask" else "comments"
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            f"UPDATE {table} SET payload = json_set(payload, '$.revision', ?) WHERE id = ?",
            (child.revision, child.id),
        )
    before = _count(repo, "sync_change_transactions")
    with allure.step("A redacted update receipt cannot replay an older child row"):
        for _ in range(2):
            with pytest.raises(IdempotencyReceiptUnavailableError):
                getattr(service, f"update_{kind}")(
                    parent.id,
                    child.id,
                    update_payload,
                    owner_id=OWNER,
                    idempotency_key="update",
                )
        assert _count(repo, "sync_change_transactions") == before
        assert (
            getattr(repo, f"get_{kind}_for_owner")(
                child.id, owner_id=OWNER, task_id=parent.id
            ).revision
            == child.revision
        )


def test_026_FR_005_next_due_date_update_keeps_review_signal(legacy_service, caplog):
    service, _repo, _enabled, _clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Next", state="next"),
        owner_id=OWNER,
        idempotency_key="next",
    )
    with (
        allure.step("A Rust-backed due-date move emits the original review event"),
        caplog.at_level(logging.INFO, logger="app.modules.tasks.review"),
    ):
        service.update_task(
            task.id,
            TaskUpdateRequest(
                due_date=date(2026, 10, 18), expected_revision=task.revision
            ),
            owner_id=OWNER,
            idempotency_key="due",
        )
        assert "review_due_date_moved" in caplog.text


def test_026_FR_005_migrated_child_replay_purges_expired_legacy_body(
    legacy_service,
):
    service, repo, _enabled, clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    payload = TaskSubtaskCreateRequest(title="Sensitive body")
    child = service.create_subtask(
        task.id, payload, owner_id=OWNER, idempotency_key="child"
    )
    smart = SmartAddTaskCreateRequest(title="Another sensitive body")
    service.smart_add_task(smart, owner_id=OWNER, idempotency_key="smart")
    assert repo.get_idempotency(owner_id=OWNER, key="child") is not None
    assert repo.get_idempotency(owner_id=OWNER, key="smart") is not None
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("Keep receipt identity but remove expired legacy response"):
        replay = service.create_subtask(
            task.id, payload, owner_id=OWNER, idempotency_key="child"
        )
        assert replay.id == child.id
        assert repo.get_idempotency(owner_id=OWNER, key="child") is None
        assert repo.get_idempotency(owner_id=OWNER, key="smart") is None


def test_026_FR_005_legacy_children_publish_atomic_owner_receipts(legacy_service):
    service, repo, _enabled, clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    with allure.step("Create subtask and comment with their own feed records"):
        subtask = service.create_subtask(
            task.id,
            TaskSubtaskCreateRequest(title="Child"),
            owner_id=OWNER,
            idempotency_key="subtask",
        )
        comment = service.create_comment(
            task.id,
            TaskCommentCreateRequest(body="Body"),
            owner_id=OWNER,
            actor_id=OWNER,
            idempotency_key="comment",
        )
        assert _count(repo, "sync_change_transactions") == 3
    updated = service.update_subtask(
        task.id,
        subtask.id,
        TaskSubtaskUpdateRequest(title="Edited", expected_revision=subtask.revision),
        owner_id=OWNER,
        idempotency_key="subtask-update",
    )
    transitioned = service.transition_subtask(
        task.id,
        subtask.id,
        TaskSubtaskTransitionRequest(
            action="complete", expected_revision=updated.revision
        ),
        owner_id=OWNER,
        idempotency_key="subtask-transition",
    )
    edited = service.update_comment(
        task.id,
        comment.id,
        TaskCommentUpdateRequest(body="Edited", expected_revision=comment.revision),
        owner_id=OWNER,
        idempotency_key="comment-update",
    )
    with allure.step("Replay a nested update after redaction without another mutation"):
        clock[0] = NOW + timedelta(hours=25)
        assert (
            service.update_comment(
                task.id,
                comment.id,
                TaskCommentUpdateRequest(
                    body="Edited", expected_revision=comment.revision
                ),
                owner_id=OWNER,
                idempotency_key="comment-update",
            )
            == edited
        )
        assert transitioned.state == "completed"
        assert _count(repo, "sync_change_transactions") == 6


def test_026_FR_005_child_refusal_replays_without_new_mutation(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    with (
        allure.step("Reject a missing parent under an immutable child command key"),
        pytest.raises(NotFoundError),
    ):
        service.create_subtask(
            "missing-task",
            TaskSubtaskCreateRequest(title="Child"),
            owner_id=OWNER,
            idempotency_key="missing-child",
        )
    with pytest.raises(NotFoundError):
        service.create_subtask(
            "missing-task",
            TaskSubtaskCreateRequest(title="Child"),
            owner_id=OWNER,
            idempotency_key="missing-child",
        )
    assert _count(repo, "sync_command_receipts") == 1
    assert _count(repo, "sync_change_transactions") == 0


def test_026_FR_005_child_revision_refusal_replays_and_redacted_result_loads(
    legacy_service,
):
    service, repo, _enabled, clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    child = service.create_subtask(
        parent.id,
        TaskSubtaskCreateRequest(title="Child"),
        owner_id=OWNER,
        idempotency_key="child",
    )
    stale = TaskSubtaskUpdateRequest(title="Bad", expected_revision=child.revision + 1)
    with allure.step(
        "Persist a revision refusal and replay it without a new child write"
    ):
        errors = []
        for _ in range(2):
            with pytest.raises(ConflictError) as error:
                service.update_subtask(
                    parent.id,
                    child.id,
                    stale,
                    owner_id=OWNER,
                    idempotency_key="stale-child",
                )
            errors.append(error.value)
        assert errors[0].resource == errors[1].resource == "Subtask"
        assert str(errors[0]) == str(errors[1])
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("Resolve the redacted create receipt from its child binding"):
        assert (
            service.create_subtask(
                parent.id,
                TaskSubtaskCreateRequest(title="Child"),
                owner_id=OWNER,
                idempotency_key="child",
            )
            == child
        )
        assert _count(repo, "sync_change_transactions") == 2


@pytest.mark.parametrize("kind", ["subtask", "comment"])
def test_026_FR_005_child_replay_rejects_corrupt_result(legacy_service, kind):
    service, repo, _enabled, _clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    payload = (
        TaskSubtaskCreateRequest(title="Child")
        if kind == "subtask"
        else TaskCommentCreateRequest(body="Child")
    )
    kwargs = {"actor_id": OWNER} if kind == "comment" else {}
    create = getattr(service, f"create_{kind}")
    create(parent.id, payload, owner_id=OWNER, idempotency_key="child", **kwargs)
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET result = ? WHERE owner_id = ? AND command_id = ?",
            ("{}", OWNER, _receipt_command_id(repo, "child")),
        )
    with allure.step("A malformed child receipt cannot drive another mutation"):
        with pytest.raises(SyncCommandError) as error:
            create(
                parent.id, payload, owner_id=OWNER, idempotency_key="child", **kwargs
            )
        assert error.value.code == "COMMAND_INTEGRITY"
        assert _count(repo, "sync_change_transactions") == 2


@pytest.mark.parametrize("missing_record", [False, True])
def test_026_FR_005_redacted_child_requires_binding_and_current_record(
    legacy_service, missing_record
):
    service, repo, _enabled, clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    payload = TaskSubtaskCreateRequest(title="Child")
    child = service.create_subtask(
        parent.id, payload, owner_id=OWNER, idempotency_key="child"
    )
    command_id = _receipt_command_id(repo, "child")
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        )
        if missing_record:
            conn.execute("DELETE FROM subtasks WHERE id = ?", (child.id,))
        else:
            row = conn.execute(
                "SELECT metadata FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
                (OWNER, command_id),
            ).fetchone()
            assert row is not None
            metadata = json.loads(row[0])
            metadata["id_bindings"] = []
            conn.execute(
                "UPDATE sync_command_receipts SET metadata = ? WHERE owner_id = ? AND command_id = ?",
                (json.dumps(metadata), OWNER, command_id),
            )
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("Do not resolve a redacted child without its trusted record"):
        expected = (
            IdempotencyReceiptUnavailableError if missing_record else SyncCommandError
        )
        with pytest.raises(expected):
            service.create_subtask(
                parent.id, payload, owner_id=OWNER, idempotency_key="child"
            )
        allure.attach(
            str(_count(repo, "sync_change_transactions")), name="Unchanged feed count"
        )


def test_026_FR_005_child_key_reused_for_other_parent_conflicts(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    first = service.create_task(
        TaskCreateRequest(title="First"), owner_id=OWNER, idempotency_key="first"
    )
    second = service.create_task(
        TaskCreateRequest(title="Second"), owner_id=OWNER, idempotency_key="second"
    )
    for kind in ("subtask", "comment"):
        payload = (
            TaskSubtaskCreateRequest(title="Child")
            if kind == "subtask"
            else TaskCommentCreateRequest(body="Child")
        )
        kwargs = {"actor_id": OWNER} if kind == "comment" else {}
        create = getattr(service, f"create_{kind}")
        with allure.step(f"Reject {kind} key reuse across parent tasks"):
            create(first.id, payload, owner_id=OWNER, idempotency_key=kind, **kwargs)
            with pytest.raises(ConflictError):
                create(
                    second.id, payload, owner_id=OWNER, idempotency_key=kind, **kwargs
                )
    assert _count(repo, "sync_change_transactions") == 4


def test_026_FR_005_smart_add_records_all_created_rows_and_replays(legacy_service):
    service, repo, _enabled, clock = legacy_service
    payload = SmartAddTaskCreateRequest(
        title="Plan",
        project=SmartAddClassificationRef(name="Launch"),
        tags=[SmartAddClassificationRef(name="@Work")],
    )
    with allure.step("Smart Add commits task and new classification rows together"):
        created = service.smart_add_task(
            payload, owner_id=OWNER, idempotency_key="smart-add"
        )
        assert created.created.project_id == created.project.id
        assert created.created.tag_ids == [created.tags[0].id]
        assert _count(repo, "sync_change_records") == 3
        assert _count(repo, "sync_change_transactions") == 1
    with allure.step("Replay before and after redaction without duplicate work"):
        assert (
            service.smart_add_task(payload, owner_id=OWNER, idempotency_key="smart-add")
            == created
        )
        clock[0] = NOW + timedelta(hours=25)
        replay = service.smart_add_task(
            payload, owner_id=OWNER, idempotency_key="smart-add"
        )
        assert replay.task.id == created.task.id
        assert replay.created == created.created
        assert _count(repo, "sync_change_transactions") == 1


def test_026_FR_005_smart_add_redacted_replay_preserves_tag_order(legacy_service):
    service, repo, _enabled, clock = legacy_service
    payload = SmartAddTaskCreateRequest(
        title="Many tags",
        tags=[SmartAddClassificationRef(name=f"@Tag{i}") for i in range(11)],
    )
    with allure.step("Create and replay an ordered Smart Add classification set"):
        created = service.smart_add_task(
            payload, owner_id=OWNER, idempotency_key="many-tags"
        )
        clock[0] = NOW + timedelta(hours=25)
        replay = service.smart_add_task(
            payload, owner_id=OWNER, idempotency_key="many-tags"
        )
        assert [tag.id for tag in replay.tags] == [tag.id for tag in created.tags]
        assert _count(repo, "sync_change_transactions") == 1


def test_026_FR_005_smart_add_adopts_legacy_result_without_duplicate_rows(
    legacy_service,
):
    service, repo, enabled, clock = legacy_service
    payload = SmartAddTaskCreateRequest(
        title="Legacy smart add",
        project=SmartAddClassificationRef(name="Project"),
        tags=[SmartAddClassificationRef(name="@Tag")],
    )
    enabled[0] = False
    legacy = service.smart_add_task(payload, owner_id=OWNER, idempotency_key="legacy")
    enabled[0] = True
    with allure.step("Adopt legacy task, project and tag without a second mutation"):
        assert (
            service.smart_add_task(payload, owner_id=OWNER, idempotency_key="legacy")
            == legacy
        )
        assert _count(repo, "sync_change_transactions") == 0
        assert len(repo.list_for_owner(owner_id=OWNER)) == 1
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("Retain created identity aliases across redaction"):
        replay = service.smart_add_task(
            payload, owner_id=OWNER, idempotency_key="legacy"
        )
        assert replay.created == legacy.created
        assert replay.task.id == legacy.task.id
        allure.attach(
            str(_count(repo, "sync_change_transactions")), name="Unchanged feed count"
        )


def test_026_FR_005_smart_add_adoption_never_publishes_archived_project(
    legacy_service,
):
    service, repo, enabled, _clock = legacy_service
    payload = SmartAddTaskCreateRequest(
        title="Old", project=SmartAddClassificationRef(name="Archived later")
    )
    enabled[0] = False
    original = service.smart_add_task(payload, owner_id=OWNER, idempotency_key="old")
    assert original.project is not None
    archived = service.archive_project(
        original.project.id,
        ExpectedRevisionRequest(expected_revision=original.project.revision),
        owner_id=OWNER,
        idempotency_key="archive",
    )
    enabled[0] = True
    with allure.step("Adopt old response without publishing a stale active project"):
        assert (
            service.smart_add_task(payload, owner_id=OWNER, idempotency_key="old")
            == original
        )
        assert repo.get_project_for_owner(archived.id, owner_id=OWNER) == archived
        with sqlite3.connect(repo.db_path) as conn:
            rows = conn.execute(
                "SELECT value FROM sync_change_records WHERE owner_id=? AND entity_type='project'",
                (OWNER,),
            ).fetchall()
        assert rows
        assert all(json.loads(row[0])["state"] == "archived" for row in rows)


def test_026_FR_005_flag_off_retains_accepted_and_rejected_receipts(legacy_service):
    service, repo, enabled, _clock = legacy_service
    payload = TaskCreateRequest(title="Once")
    original = service.create_task(payload, owner_id=OWNER, idempotency_key="once")
    project = service.create_project(
        ProjectCreateRequest(name="Closed project"),
        owner_id=OWNER,
        idempotency_key="project",
    )
    archived = service.archive_project(
        project.id,
        ExpectedRevisionRequest(expected_revision=project.revision),
        owner_id=OWNER,
        idempotency_key="archive",
    )
    smart = SmartAddTaskCreateRequest(
        title="Blocked", project=SmartAddClassificationRef(id=project.id)
    )
    with (
        allure.step("Record a terminal Smart Add refusal"),
        pytest.raises(ValidationFailure) as first,
    ):
        service.smart_add_task(smart, owner_id=OWNER, idempotency_key="blocked")
    service.unarchive_project(
        project.id,
        ExpectedRevisionRequest(expected_revision=archived.revision),
        owner_id=OWNER,
        idempotency_key="unarchive",
    )
    enabled[0] = False
    with allure.step("Flag OFF replays both outcomes without new writes"):
        assert (
            service.create_task(payload, owner_id=OWNER, idempotency_key="once")
            == original
        )
        with pytest.raises(ValidationFailure) as retry:
            service.smart_add_task(smart, owner_id=OWNER, idempotency_key="blocked")
        assert str(retry.value) == str(first.value)
        assert len(repo.list_for_owner(owner_id=OWNER)) == 1
        assert _count(repo, "sync_command_receipts") == 5


@pytest.mark.parametrize("action", ["update", "delete"])
def test_026_FR_005_legacy_tag_mutation_adopts_key_after_flag_enable(
    legacy_service, action
):
    service, repo, enabled, _clock = legacy_service
    enabled[0] = False
    tag = service.create_tag(
        TagCreateRequest(name="Old"), owner_id=OWNER, idempotency_key="create"
    )
    if action == "update":
        request = TagUpdateRequest(name="New", expected_revision=tag.revision)
        mutate = service.update_tag
    else:
        request = ExpectedRevisionRequest(expected_revision=tag.revision)
        mutate = service.delete_tag
    original = mutate(tag.id, request, owner_id=OWNER, idempotency_key="mutation")
    enabled[0] = True
    with allure.step("Adopt old result without repeating mutation"):
        assert (
            mutate(tag.id, request, owner_id=OWNER, idempotency_key="mutation")
            == original
        )
        assert repo.get_tag_for_owner(tag.id, owner_id=OWNER) == original
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") <= 1
    with (
        allure.step("Reject reuse of the same owner key for another command"),
        pytest.raises(ConflictError),
    ):
        service.create_tag(
            TagCreateRequest(name="Other"), owner_id=OWNER, idempotency_key="mutation"
        )


def test_026_FR_005_legacy_project_update_uses_owner_receipt_and_redacted_replay(
    legacy_service,
):
    service, repo, _enabled, _clock = legacy_service
    with allure.step("Create a project to update through the receipt boundary"):
        project = service.create_project(
            ProjectCreateRequest(name="Project"),
            owner_id=OWNER,
            idempotency_key="project-create",
        )
    payload = ProjectUpdateRequest(name="Renamed", expected_revision=project.revision)
    updated = service.update_project(
        project.id, payload, owner_id=OWNER, idempotency_key="project-update"
    )
    assert (
        service.update_project(
            project.id, payload, owner_id=OWNER, idempotency_key="project-update"
        )
        == updated
    )
    with pytest.raises(ConflictError):
        service.update_project(
            project.id,
            ProjectUpdateRequest(name="Other", expected_revision=project.revision),
            owner_id=OWNER,
            idempotency_key="project-update",
        )
    command_id = _receipt_command_id(repo, "project-update")
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        )
    replay = service.update_project(
        project.id, payload, owner_id=OWNER, idempotency_key="project-update"
    )
    assert replay == repo.get_project_for_owner(project.id, owner_id=OWNER)
    assert _count(repo, "sync_change_transactions") == 2


@pytest.mark.parametrize("missing", [False, True])
def test_026_FR_005_expired_legacy_project_adoption_checks_current_record(
    legacy_service, missing
):
    service, repo, enabled, clock = legacy_service
    payload = ProjectCreateRequest(name="Legacy project")
    enabled[0] = False
    original = service.create_project(payload, owner_id=OWNER, idempotency_key="old")
    if missing:
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute("DELETE FROM projects WHERE owner_id = ?", (OWNER,))
    clock[0] = NOW + timedelta(hours=25)
    enabled[0] = True
    with allure.step("Do not replay an expired legacy response over current state"):
        if missing:
            with pytest.raises(IdempotencyReceiptUnavailableError):
                service.create_project(payload, owner_id=OWNER, idempotency_key="old")
            assert _count(repo, "sync_command_receipts") == 0
        else:
            assert (
                service.create_project(payload, owner_id=OWNER, idempotency_key="old")
                == original
            )
            assert _count(repo, "sync_change_transactions") == 0


def test_026_FR_005_legacy_project_unarchive_records_noop_and_replay(legacy_service):
    service, repo, _enabled, clock = legacy_service
    project = service.create_project(
        ProjectCreateRequest(name="Project"), owner_id=OWNER, idempotency_key="create"
    )
    with allure.step("Unarchiving an active project is a receipt-only no-op"):
        same = service.unarchive_project(
            project.id,
            ExpectedRevisionRequest(expected_revision=project.revision),
            owner_id=OWNER,
            idempotency_key="noop",
        )
        assert same == project
        assert _count(repo, "sync_command_receipts") == 2
        assert _count(repo, "sync_change_transactions") == 1
    archived = service.archive_project(
        project.id,
        ExpectedRevisionRequest(expected_revision=project.revision),
        owner_id=OWNER,
        idempotency_key="archive",
    )
    with allure.step("Replay the no-op instead of reapplying to changed state"):
        assert (
            service.unarchive_project(
                project.id,
                ExpectedRevisionRequest(expected_revision=project.revision),
                owner_id=OWNER,
                idempotency_key="noop",
            )
            == project
        )
        allure.attach(
            str(_count(repo, "sync_change_transactions")), name="Unchanged feed count"
        )
    unarchived = service.unarchive_project(
        project.id,
        ExpectedRevisionRequest(expected_revision=archived.revision),
        owner_id=OWNER,
        idempotency_key="unarchive",
    )
    assert unarchived.state == "active"
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("Resolve redacted unarchive via retained project binding"):
        assert (
            service.unarchive_project(
                project.id,
                ExpectedRevisionRequest(expected_revision=archived.revision),
                owner_id=OWNER,
                idempotency_key="unarchive",
            )
            == unarchived
        )
        allure.attach(str(unarchived.revision), name="Resolved project revision")
    assert _count(repo, "sync_change_transactions") == 3


def test_026_FR_005_legacy_project_archive_projects_receipt_and_task_projection(
    legacy_service, monkeypatch
):
    service, repo, _enabled, clock = legacy_service
    with allure.step("Create a project to archive under a durable receipt"):
        project = service.create_project(
            ProjectCreateRequest(name="Project"),
            owner_id=OWNER,
            idempotency_key="project-create",
        )
    task = service.create_task(
        TaskCreateRequest(title="Keep membership", project_id=project.id),
        owner_id=OWNER,
        idempotency_key="task-create",
    )
    archived = service.archive_project(
        project.id,
        ExpectedRevisionRequest(expected_revision=project.revision),
        owner_id=OWNER,
        idempotency_key="project-archive",
    )
    assert archived.state == "archived"
    assert repo.get_for_owner(task.id, owner_id=OWNER).project_id == project.id
    assert (
        service.archive_project(
            project.id,
            ExpectedRevisionRequest(expected_revision=project.revision),
            owner_id=OWNER,
            idempotency_key="project-archive",
        )
        == archived
    )
    command_id = _receipt_command_id(repo, "project-archive")
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET result = NULL WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        )
    clock[0] = NOW + timedelta(hours=25)
    assert (
        service.archive_project(
            project.id,
            ExpectedRevisionRequest(expected_revision=project.revision),
            owner_id=OWNER,
            idempotency_key="project-archive",
        )
        == archived
    )
    with pytest.raises(NotFoundError):
        service.archive_project(
            project.id,
            ExpectedRevisionRequest(expected_revision=project.revision),
            owner_id="other-owner",
            idempotency_key="other-archive",
        )
    with pytest.raises(ConflictError):
        service.archive_project(
            project.id,
            ExpectedRevisionRequest(expected_revision=project.revision + 1),
            owner_id=OWNER,
            idempotency_key="project-archive",
        )
    handler = service._legacy_tag_handler
    assert handler is not None
    monkeypatch.setattr(
        handler._receipts.change_log,
        "append",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("injected project archive finalization failure")
        ),
    )
    with pytest.raises(
        RuntimeError, match="injected project archive finalization failure"
    ):
        service.archive_project(
            project.id,
            ExpectedRevisionRequest(expected_revision=archived.revision),
            owner_id=OWNER,
            idempotency_key="project-archive-failure",
        )
    assert repo.get_project_for_owner(project.id, owner_id=OWNER) == archived
    assert repo.get_idempotency(owner_id=OWNER, key="project-archive-failure") is None
    assert _count(repo, "sync_command_receipts") == 3
    assert _count(repo, "sync_change_transactions") == 3


@pytest.mark.parametrize("kind", ["subtask", "comment"])
def test_026_FR_005_child_replay_rejects_foreign_parent(legacy_service, kind):
    service, repo, _enabled, _clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    payload = (
        TaskSubtaskCreateRequest(title="Child")
        if kind == "subtask"
        else TaskCommentCreateRequest(body="Child")
    )
    kwargs = {"actor_id": OWNER} if kind == "comment" else {}
    create = getattr(service, f"create_{kind}")
    child = create(
        parent.id, payload, owner_id=OWNER, idempotency_key="child", **kwargs
    )
    with sqlite3.connect(repo.db_path) as conn:
        result = child.model_copy(update={"task_id": "task_other"})
        conn.execute(
            "UPDATE sync_command_receipts SET result = ? WHERE owner_id = ? AND command_id = ?",
            (
                json.dumps(result.model_dump(mode="json")),
                OWNER,
                _receipt_command_id(repo, "child"),
            ),
        )
    with allure.step("Do not replay a child attached to another parent"):
        with pytest.raises(SyncCommandError) as error:
            create(
                parent.id, payload, owner_id=OWNER, idempotency_key="child", **kwargs
            )
        assert error.value.code == "COMMAND_INTEGRITY"
        assert _count(repo, "sync_change_transactions") == 2


def test_026_FR_005_child_same_state_refusal_remains_durable(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    child = service.create_subtask(
        parent.id,
        TaskSubtaskCreateRequest(title="Child"),
        owner_id=OWNER,
        idempotency_key="child",
    )
    payload = TaskSubtaskTransitionRequest(
        action="reopen", expected_revision=child.revision
    )
    with allure.step("A no-op transition is rejected and recorded once"):
        for _ in range(2):
            with pytest.raises(ValidationFailure, match="different state"):
                service.transition_subtask(
                    parent.id, child.id, payload, owner_id=OWNER, idempotency_key="same"
                )
        assert _count(repo, "sync_command_receipts") == 3
        assert _count(repo, "sync_change_transactions") == 2
        assert (
            repo.get_subtask_for_owner(child.id, task_id=parent.id, owner_id=OWNER)
            == child
        )


@pytest.mark.parametrize("missing", [False, True])
def test_026_FR_005_redacted_smart_add_requires_bound_current_task(
    legacy_service, missing
):
    service, repo, _enabled, clock = legacy_service
    payload = SmartAddTaskCreateRequest(title="Captured")
    created = service.smart_add_task(payload, owner_id=OWNER, idempotency_key="smart")
    command_id = _receipt_command_id(repo, "smart")
    with sqlite3.connect(repo.db_path) as conn:
        if missing:
            conn.execute("DELETE FROM tasks WHERE id = ?", (created.task.id,))
        else:
            row = conn.execute(
                "SELECT metadata FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
                (OWNER, command_id),
            ).fetchone()
            assert row is not None
            metadata = json.loads(row[0])
            metadata["id_bindings"] = []
            conn.execute(
                "UPDATE sync_command_receipts SET metadata = ? WHERE owner_id = ? AND command_id = ?",
                (json.dumps(metadata), OWNER, command_id),
            )
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("A redacted Smart Add never recreates its lost task"):
        expected = IdempotencyReceiptUnavailableError if missing else SyncCommandError
        with pytest.raises(expected):
            service.smart_add_task(payload, owner_id=OWNER, idempotency_key="smart")
        assert _count(repo, "sync_change_transactions") == 1


def test_026_FR_005_tag_delete_publishes_affected_task_in_same_transaction(
    legacy_service,
):
    service, repo, _enabled, _clock = legacy_service
    tag = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="tag"
    )
    task = service.create_task(
        TaskCreateRequest(title="Tagged", tag_ids=[tag.id]),
        owner_id=OWNER,
        idempotency_key="task",
    )
    with allure.step("Deleting a tag carries the affected task after-image"):
        service.delete_tag(
            tag.id,
            ExpectedRevisionRequest(expected_revision=tag.revision),
            owner_id=OWNER,
            idempotency_key="delete",
        )
        assert repo.get_for_owner(task.id, owner_id=OWNER).tag_ids == []
        with sqlite3.connect(repo.db_path) as conn:
            records = conn.execute(
                "SELECT entity_type, operation FROM sync_change_records WHERE owner_id = ? "
                "AND commit_seq = (SELECT MAX(commit_seq) FROM sync_change_transactions "
                "WHERE owner_id = ?) ORDER BY rowid",
                (OWNER, OWNER),
            ).fetchall()
        assert records == [("tag", "tombstone"), ("task", "upsert")]


@pytest.mark.parametrize("kind", ["update", "delete"])
@pytest.mark.parametrize("corruption", ["binding", "missing"])
def test_026_FR_005_tag_mutation_replay_fails_closed_without_bound_record(
    legacy_service, kind, corruption
):
    service, repo, _enabled, _clock = legacy_service
    tag = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="tag"
    )
    payload = (
        TagUpdateRequest(name="@Home", expected_revision=tag.revision)
        if kind == "update"
        else ExpectedRevisionRequest(expected_revision=tag.revision)
    )
    mutate = getattr(service, f"{kind}_tag")
    mutate(tag.id, payload, owner_id=OWNER, idempotency_key="mutate")
    command_id = _receipt_command_id(repo, "mutate")
    with sqlite3.connect(repo.db_path) as conn:
        if kind == "update":
            conn.execute(
                "UPDATE sync_command_receipts SET result = NULL WHERE owner_id = ? AND command_id = ?",
                (OWNER, command_id),
            )
        if corruption == "binding":
            row = conn.execute(
                "SELECT metadata FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
                (OWNER, command_id),
            ).fetchone()
            assert row is not None
            metadata = json.loads(row[0])
            metadata["id_bindings"] = []
            conn.execute(
                "UPDATE sync_command_receipts SET metadata = ? WHERE owner_id = ? AND command_id = ?",
                (json.dumps(metadata), OWNER, command_id),
            )
        else:
            conn.execute("DELETE FROM tags WHERE id = ?", (tag.id,))
    with allure.step("A retained key never reexecutes a tag mutation without its row"):
        expected = (
            SyncCommandError
            if corruption == "binding"
            else IdempotencyReceiptUnavailableError
        )
        with pytest.raises(expected):
            mutate(tag.id, payload, owner_id=OWNER, idempotency_key="mutate")
        assert _count(repo, "sync_change_transactions") == 2


@pytest.mark.parametrize("kind", ["task", "project", "smart_add"])
def test_026_FR_005_created_receipt_rejects_foreign_owner_result(legacy_service, kind):
    service, repo, _enabled, _clock = legacy_service
    payload = {
        "task": TaskCreateRequest(title="Task"),
        "project": ProjectCreateRequest(name="Project"),
        "smart_add": SmartAddTaskCreateRequest(title="Captured"),
    }[kind]
    create = getattr(
        service,
        f"{'create_' if kind != 'smart_add' else ''}{kind}{'_task' if kind == 'smart_add' else ''}",
    )
    create(payload, owner_id=OWNER, idempotency_key="created")
    with sqlite3.connect(repo.db_path) as conn:
        row = conn.execute(
            "SELECT result FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
            (OWNER, _receipt_command_id(repo, "created")),
        ).fetchone()
        assert row is not None
        result = json.loads(row[0])
        if kind in ("smart_add", "task"):
            result["task"]["owner_id"] = "user_other"
        else:
            result["owner_id"] = "user_other"
        conn.execute(
            "UPDATE sync_command_receipts SET result = ? WHERE owner_id = ? AND command_id = ?",
            (json.dumps(result), OWNER, _receipt_command_id(repo, "created")),
        )
    with allure.step("Do not expose a foreign-owner accepted receipt"):
        with pytest.raises(SyncCommandError) as error:
            create(payload, owner_id=OWNER, idempotency_key="created")
        assert error.value.code == "COMMAND_INTEGRITY"
        assert _count(repo, "sync_change_transactions") == 1


def test_026_FR_005_child_reused_legacy_key_cannot_change_command(legacy_service):
    service, repo, enabled, _clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    enabled[0] = False
    child = service.create_subtask(
        parent.id,
        TaskSubtaskCreateRequest(title="Child"),
        owner_id=OWNER,
        idempotency_key="old-child",
    )
    enabled[0] = True
    with allure.step(
        "Adopt the matching legacy child without publishing a second write"
    ):
        assert (
            service.create_subtask(
                parent.id,
                TaskSubtaskCreateRequest(title="Child"),
                owner_id=OWNER,
                idempotency_key="old-child",
            )
            == child
        )
        assert _count(repo, "sync_change_transactions") == 1
    with allure.step("The same key cannot represent a different child operation"):
        with pytest.raises(ConflictError):
            service.update_subtask(
                parent.id,
                child.id,
                TaskSubtaskUpdateRequest(
                    title="Other", expected_revision=child.revision
                ),
                owner_id=OWNER,
                idempotency_key="old-child",
            )
        assert (
            repo.get_subtask_for_owner(child.id, task_id=parent.id, owner_id=OWNER)
            == child
        )


@pytest.mark.parametrize("corruption", ["snapshot", "missing", "expired_missing"])
def test_026_FR_005_task_mutation_adoption_fails_closed_on_old_identity(
    legacy_service, corruption
):
    service, repo, enabled, clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Original"), owner_id=OWNER, idempotency_key="create"
    )
    enabled[0] = False
    payload = TaskUpdateRequest(title="Updated", expected_revision=task.revision)
    updated = service.update_task_result(
        task.id, payload, owner_id=OWNER, idempotency_key="old-update"
    )
    old = repo.get_idempotency(owner_id=OWNER, key="old-update")
    assert old is not None
    if corruption == "snapshot":
        repo.save_idempotency(
            owner_id=OWNER,
            record=old.model_copy(
                update={
                    "response_body": updated.task.model_copy(
                        update={"owner_id": "user_other"}
                    ).model_dump(mode="json")
                }
            ),
        )
    else:
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute(
                "DELETE FROM tasks WHERE owner_id = ? AND id = ?", (OWNER, task.id)
            )
        if corruption == "expired_missing":
            clock[0] = NOW + timedelta(hours=25)
    enabled[0] = True
    with allure.step("Do not adopt a foreign or expired missing task response"):
        if corruption == "missing":
            # An unexpired legacy snapshot repairs its lost row and publishes it once.
            assert (
                service.update_task_result(
                    task.id, payload, owner_id=OWNER, idempotency_key="old-update"
                )
                == updated
            )
            assert repo.list_for_owner(owner_id=OWNER) == [updated.task]
        else:
            expected = (
                SyncCommandError
                if corruption == "snapshot"
                else IdempotencyReceiptUnavailableError
            )
            with pytest.raises(expected):
                service.update_task_result(
                    task.id, payload, owner_id=OWNER, idempotency_key="old-update"
                )
        assert _count(repo, "sync_change_transactions") == (
            2 if corruption == "missing" else 1
        )


@pytest.mark.parametrize("corruption", ["legacy_snapshot", "receipt_result"])
def test_026_FR_005_project_replay_rejects_foreign_identity(legacy_service, corruption):
    service, repo, enabled, _clock = legacy_service
    payload = ProjectCreateRequest(name="Project")
    if corruption == "legacy_snapshot":
        enabled[0] = False
    project = service.create_project(payload, owner_id=OWNER, idempotency_key="project")
    enabled[0] = True
    if corruption == "legacy_snapshot":
        old = repo.get_idempotency(owner_id=OWNER, key="project")
        assert old is not None
        repo.save_idempotency(
            owner_id=OWNER,
            record=old.model_copy(
                update={
                    "response_body": project.model_copy(
                        update={"owner_id": "user_other"}
                    ).model_dump(mode="json")
                }
            ),
        )
    else:
        with sqlite3.connect(repo.db_path) as conn:
            conn.execute(
                "UPDATE sync_command_receipts SET result = ? WHERE owner_id = ? AND command_id = ?",
                ("{}", OWNER, _receipt_command_id(repo, "project")),
            )
    with allure.step("A project receipt or old snapshot cannot change its owner"):
        with pytest.raises(SyncCommandError) as error:
            service.create_project(payload, owner_id=OWNER, idempotency_key="project")
        assert error.value.code == "COMMAND_INTEGRITY"
        assert repo.get_project_for_owner(project.id, owner_id=OWNER) == project
        allure.attach(
            str(_count(repo, "sync_command_receipts")), name="Unchanged receipt count"
        )


def test_026_FR_005_redacted_smart_add_project_must_still_exist(legacy_service):
    service, repo, _enabled, clock = legacy_service
    payload = SmartAddTaskCreateRequest(
        title="Captured", project=SmartAddClassificationRef(name="Launch")
    )
    created = service.smart_add_task(payload, owner_id=OWNER, idempotency_key="smart")
    assert created.project is not None
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (created.project.id,))
    clock[0] = NOW + timedelta(hours=25)
    with allure.step("A missing bound project cannot be silently omitted from replay"):
        with pytest.raises(IdempotencyReceiptUnavailableError):
            service.smart_add_task(payload, owner_id=OWNER, idempotency_key="smart")
        assert _count(repo, "sync_change_transactions") == 1


@pytest.mark.parametrize("corruption", ["malformed", "foreign_owner"])
def test_026_FR_005_tag_update_replay_requires_valid_original_result(
    legacy_service, corruption
):
    service, repo, _enabled, _clock = legacy_service
    tag = service.create_tag(
        TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="create"
    )
    payload = TagUpdateRequest(name="@Edited", expected_revision=tag.revision)
    updated = service.update_tag(
        tag.id, payload, owner_id=OWNER, idempotency_key="update"
    )
    result = (
        {}
        if corruption == "malformed"
        else updated.model_copy(update={"owner_id": "user_other"}).model_dump(
            mode="json"
        )
    )
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE sync_command_receipts SET result = ? WHERE owner_id = ? AND command_id = ?",
            (json.dumps(result), OWNER, _receipt_command_id(repo, "update")),
        )
    with allure.step("Reject a malformed tag update result without executing it again"):
        with pytest.raises(SyncCommandError) as error:
            service.update_tag(
                tag.id, payload, owner_id=OWNER, idempotency_key="update"
            )
        assert error.value.code == "COMMAND_INTEGRITY"
        assert repo.get_tag_for_owner(tag.id, owner_id=OWNER) == updated


@pytest.mark.parametrize("corruption", ["missing_witness", "invalid_entity"])
def test_026_FR_005_child_refusal_requires_trusted_replay_data(
    legacy_service, corruption
):
    service, repo, _enabled, _clock = legacy_service
    payload = TaskSubtaskCreateRequest(title="Child")
    with pytest.raises(NotFoundError):
        service.create_subtask(
            "task_missing", payload, owner_id=OWNER, idempotency_key="child"
        )
    command_id = _receipt_command_id(repo, "child")
    with sqlite3.connect(repo.db_path) as conn:
        row = conn.execute(
            "SELECT metadata FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        ).fetchone()
        assert row is not None
        metadata = json.loads(row[0])
        if corruption == "missing_witness":
            metadata.pop("_legacy_refusal_v1")
        else:
            metadata["_legacy_refusal_v1"]["entity"] = ["nonsense", ["task_missing"]]
        conn.execute(
            "UPDATE sync_command_receipts SET metadata = ? WHERE owner_id = ? AND command_id = ?",
            (json.dumps(metadata), OWNER, command_id),
        )
    with allure.step("A corrupt rejected child receipt cannot mask the original error"):
        with pytest.raises(SyncCommandError) as error:
            service.create_subtask(
                "task_missing", payload, owner_id=OWNER, idempotency_key="child"
            )
        assert error.value.code == "COMMAND_INTEGRITY"
        assert _count(repo, "sync_change_transactions") == 0


def test_026_FR_005_old_task_create_snapshot_repairs_missing_row(legacy_service):
    service, repo, enabled, _clock = legacy_service
    payload = TaskCreateRequest(title="Old task")
    enabled[0] = False
    created = service.create_task(payload, owner_id=OWNER, idempotency_key="old")
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "DELETE FROM tasks WHERE owner_id = ? AND id = ?", (OWNER, created.id)
        )
    enabled[0] = True
    with allure.step("Adopt a fresh old result and repair its lost task atomically"):
        assert (
            service.create_task(payload, owner_id=OWNER, idempotency_key="old")
            == created
        )
        assert repo.get_for_owner(created.id, owner_id=OWNER) == created
        assert _count(repo, "sync_command_receipts") == 1
        assert _count(repo, "sync_change_transactions") == 1


@pytest.mark.parametrize("kind", ["project", "smart_add"])
def test_026_FR_005_legacy_adoption_rejects_corrupt_snapshot(legacy_service, kind):
    service, repo, enabled, _clock = legacy_service
    payload = (
        ProjectCreateRequest(name="Legacy")
        if kind == "project"
        else SmartAddTaskCreateRequest(title="Legacy")
    )
    create = service.create_project if kind == "project" else service.smart_add_task
    enabled[0] = False
    original = create(payload, owner_id=OWNER, idempotency_key="legacy")
    old = repo.get_idempotency(owner_id=OWNER, key="legacy")
    assert old is not None
    bad_response = (
        {}
        if kind == "project"
        else original.model_copy(
            update={"task": original.task.model_copy(update={"owner_id": "user_other"})}
        ).model_dump(mode="json")
    )
    repo.save_idempotency(
        owner_id=OWNER, record=old.model_copy(update={"response_body": bad_response})
    )
    enabled[0] = True
    with allure.step("Do not adopt corrupt pre-receipt responses"):
        with pytest.raises(SyncCommandError) as error:
            create(payload, owner_id=OWNER, idempotency_key="legacy")
        assert error.value.code == "COMMAND_INTEGRITY"
        assert _count(repo, "sync_command_receipts") == 0


def test_026_FR_005_child_legacy_key_cannot_be_adopted_for_other_operation(
    legacy_service,
):
    service, repo, enabled, _clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    enabled[0] = False
    comment = service.create_comment(
        parent.id,
        TaskCommentCreateRequest(body="Note"),
        owner_id=OWNER,
        actor_id=OWNER,
        idempotency_key="old-key",
    )
    enabled[0] = True
    with allure.step("An old comment key cannot be adopted as a subtask create"):
        with pytest.raises(ConflictError):
            service.create_subtask(
                parent.id,
                TaskSubtaskCreateRequest(title="Different"),
                owner_id=OWNER,
                idempotency_key="old-key",
            )
        assert (
            repo.get_comment_for_owner(comment.id, task_id=parent.id, owner_id=OWNER)
            == comment
        )
        assert _count(repo, "sync_command_receipts") == 1


def test_026_FR_005_redacted_project_receipt_refuses_lost_identity(legacy_service):
    service, repo, _enabled, clock = legacy_service
    payload = ProjectCreateRequest(name="Project")
    project = service.create_project(payload, owner_id=OWNER, idempotency_key="project")
    clock[0] = NOW + timedelta(hours=25)
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project.id,))
    with allure.step("A redacted create cannot invent a replacement project"):
        with pytest.raises(IdempotencyReceiptUnavailableError):
            service.create_project(payload, owner_id=OWNER, idempotency_key="project")
        assert _count(repo, "sync_change_transactions") == 1


@pytest.mark.parametrize("operation", ["task", "project", "tag_update", "tag_delete"])
def test_026_FR_005_rejected_command_requires_its_original_typed_witness(
    legacy_service, operation
):
    service, repo, _enabled, _clock = legacy_service
    if operation == "task":

        def retry():
            service.create_task(
                TaskCreateRequest(title="Task", project_id="project_missing"),
                owner_id=OWNER,
                idempotency_key="reject",
            )

        error_type = NotFoundError
    elif operation == "project":
        service.create_project(
            ProjectCreateRequest(name="Taken"), owner_id=OWNER, idempotency_key="taken"
        )

        def retry():
            service.create_project(
                ProjectCreateRequest(name="Taken"),
                owner_id=OWNER,
                idempotency_key="reject",
            )

        error_type = ConflictError
    else:
        tag = service.create_tag(
            TagCreateRequest(name="@Work"), owner_id=OWNER, idempotency_key="tag"
        )
        if operation == "tag_update":

            def retry():
                service.update_tag(
                    tag.id,
                    TagUpdateRequest(name="@Wrong", expected_revision=tag.revision + 1),
                    owner_id=OWNER,
                    idempotency_key="reject",
                )

        else:

            def retry():
                service.delete_tag(
                    tag.id,
                    ExpectedRevisionRequest(expected_revision=tag.revision + 1),
                    owner_id=OWNER,
                    idempotency_key="reject",
                )

        error_type = ConflictError
    with pytest.raises(error_type):
        retry()
    command_id = _receipt_command_id(repo, "reject")
    with sqlite3.connect(repo.db_path) as conn:
        row = conn.execute(
            "SELECT metadata FROM sync_command_receipts WHERE owner_id = ? AND command_id = ?",
            (OWNER, command_id),
        ).fetchone()
        assert row is not None
        metadata = json.loads(row[0])
        metadata.pop("_legacy_refusal_v1")
        conn.execute(
            "UPDATE sync_command_receipts SET metadata = ? WHERE owner_id = ? AND command_id = ?",
            (json.dumps(metadata), OWNER, command_id),
        )
    with allure.step("Fail closed rather than re-execute a refusal with lost witness"):
        with pytest.raises(SyncCommandError) as error:
            retry()
        assert error.value.code == "COMMAND_INTEGRITY"
        assert _count(repo, "sync_command_receipts") == (
            1 if operation == "task" else 2
        )
        allure.attach(
            str(_count(repo, "sync_change_transactions")), name="Unchanged feed count"
        )


def test_026_FR_005_smart_add_cannot_reuse_task_command_key(legacy_service):
    service, repo, _enabled, _clock = legacy_service
    task = service.create_task(
        TaskCreateRequest(title="Original"), owner_id=OWNER, idempotency_key="shared"
    )
    with allure.step("Smart Add cannot bypass the owner-wide command identity"):
        with pytest.raises(ConflictError):
            service.smart_add_task(
                SmartAddTaskCreateRequest(title="Different"),
                owner_id=OWNER,
                idempotency_key="shared",
            )
        assert repo.list_for_owner(owner_id=OWNER) == [task]
        assert _count(repo, "sync_command_receipts") == 1


def test_026_FR_005_old_child_update_key_adopts_without_second_mutation(legacy_service):
    service, repo, enabled, _clock = legacy_service
    parent = service.create_task(
        TaskCreateRequest(title="Parent"), owner_id=OWNER, idempotency_key="parent"
    )
    child = service.create_subtask(
        parent.id,
        TaskSubtaskCreateRequest(title="Child"),
        owner_id=OWNER,
        idempotency_key="child",
    )
    payload = TaskSubtaskUpdateRequest(
        title="Changed", expected_revision=child.revision
    )
    enabled[0] = False
    updated = service.update_subtask(
        parent.id, child.id, payload, owner_id=OWNER, idempotency_key="old-update"
    )
    enabled[0] = True
    with allure.step("Adopt the old child update key and retain its identity"):
        assert (
            service.update_subtask(
                parent.id,
                child.id,
                payload,
                owner_id=OWNER,
                idempotency_key="old-update",
            )
            == updated
        )
        assert _count(repo, "sync_command_receipts") == 3
        assert _count(repo, "sync_change_transactions") == 2
