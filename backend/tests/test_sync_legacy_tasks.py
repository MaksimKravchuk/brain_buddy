"""T027 legacy create-tag receipt, adoption and atomic feed behavior."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import allure
import pytest

from app.exceptions import (
    ConflictError,
    IdempotencyReceiptUnavailableError,
)
from app.modules.tasks import TaskRepository, TaskService
from app.modules.tasks.domain import IdempotencyRecord
from app.modules.tasks.jobs import JobRepository
from app.modules.tasks.rust_adapter import RustCore
from app.modules.tasks.rust_task_facade import RustTaskFacade
from app.modules.tasks.sync.receipts import (
    ReceiptStore,
    ScopeAuthority,
    SyncCommandError,
)
from app.modules.tasks.sync.unit_of_work import TaskUnitOfWork
from app.schemas.tasks import ProjectCreateRequest, TagCreateRequest
from app.utils.idempotency import idempotency_key_digest

pytestmark = [
    allure.epic("Task Management"),
    allure.feature("Durable task synchronization"),
    allure.story("Legacy create-tag receipts"),
]

OWNER = "user_legacy_sync"
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


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
