from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from threading import Event, Thread

import pytest

from app.exceptions import (
    ConflictError,
    IdempotencyReceiptUnavailableError,
    NotFoundError,
)
from app.main import _run_privacy_maintenance_sweep
from app.repositories.crt_command import CrtCommandReceipt, CrtCommandRepository
from app.schemas.api import (
    NodeResponse,
    RelationResponse,
    TreeCreateRequest,
    TreeUpdateRequest,
)
from app.schemas.auth import User
from app.schemas.common import Position
from app.utils.time import utcnow


def _receipt_fixture(
    *, owner_id: str, key_digest: str, committed_at: datetime
) -> CrtCommandReceipt:
    return CrtCommandReceipt(
        owner_id=owner_id,
        key_digest=key_digest,
        command="create",
        normalized_route="/api/crt/trees",
        request_hash=f"request-{key_digest}",
        state="pending",
        resource_id=f"tree-{key_digest}",
        base_revision=None,
        target_revision=1,
        response_status=None,
        response_json=None,
        created_at=committed_at,
        committed_at=None,
        expires_at=committed_at + timedelta(days=30),
    )


def test_old_crt_receipt_schema_migration_rolls_back_after_failure(
    data_dir, monkeypatch
) -> None:
    database_path = data_dir / "crt_commands.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript("""
            CREATE TABLE crt_command_receipts (
                owner_id TEXT NOT NULL,
                key_digest TEXT NOT NULL,
                command TEXT NOT NULL,
                normalized_route TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('pending', 'committed')),
                resource_id TEXT NOT NULL,
                base_revision INTEGER,
                target_revision INTEGER,
                response_status INTEGER,
                response_json TEXT,
                created_at TEXT NOT NULL,
                committed_at TEXT,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (owner_id, key_digest)
            );
            INSERT INTO crt_command_receipts VALUES (
                'owner', 'digest', 'create', '/api/crt/trees', 'fingerprint',
                'committed', 'tree_1', NULL, 1, 201, '{"id":"tree_1"}',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00',
                '2026-02-01T00:00:00+00:00'
            );
            """)

    def fail_after_rename(connection: sqlite3.Connection) -> None:
        connection.execute(
            "ALTER TABLE crt_command_receipts RENAME TO crt_command_receipts_legacy"
        )
        raise RuntimeError("simulated migration crash")

    monkeypatch.setattr(
        CrtCommandRepository, "_migrate_expired_state", staticmethod(fail_after_rename)
    )
    with pytest.raises(RuntimeError, match="simulated migration crash"):
        CrtCommandRepository(data_dir)

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "crt_command_receipts" in tables
        assert "crt_command_receipts_legacy" not in tables
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(crt_command_receipts)")
        }
        assert "pending_target_snapshot" not in columns
        assert (
            connection.execute(
                "SELECT response_json FROM crt_command_receipts "
                "WHERE owner_id = 'owner' AND key_digest = 'digest'"
            ).fetchone()[0]
            == '{"id":"tree_1"}'
        )


def test_old_crt_receipt_schema_migrates_without_losing_replay_history(
    data_dir,
) -> None:
    database_path = data_dir / "crt_commands.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript("""
            CREATE TABLE crt_command_receipts (
                owner_id TEXT NOT NULL,
                key_digest TEXT NOT NULL,
                command TEXT NOT NULL,
                normalized_route TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                state TEXT NOT NULL CHECK (state IN ('pending', 'committed')),
                resource_id TEXT NOT NULL,
                base_revision INTEGER,
                target_revision INTEGER,
                response_status INTEGER,
                response_json TEXT,
                created_at TEXT NOT NULL,
                committed_at TEXT,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (owner_id, key_digest)
            );
            INSERT INTO crt_command_receipts VALUES (
                'owner', 'digest', 'create', '/api/crt/trees', 'fingerprint',
                'committed', 'tree_1', NULL, 1, 201, '{"id":"tree_1"}',
                '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00',
                '2026-02-01T00:00:00+00:00'
            );
            """)

    repository = CrtCommandRepository(data_dir)
    migrated = repository.get(owner_id="owner", key_digest="digest")
    assert migrated is not None
    assert migrated.state == "committed"
    assert migrated.response_json == '{"id":"tree_1"}'
    assert migrated.pending_target_snapshot is None
    assert (
        repository.purge_expired(
            now=datetime.fromisoformat("2026-03-01T00:00:00+00:00")
        )
        == 1
    )
    tombstone = repository.get(owner_id="owner", key_digest="digest")
    assert tombstone is not None
    assert tombstone.state == "expired"
    assert tombstone.response_json is None


def test_crt_receipt_maintenance_redacts_expired_receipts_but_keeps_fresh_ones(
    container,
) -> None:
    now = utcnow()
    expired = _receipt_fixture(
        owner_id="owner-a", key_digest="expired", committed_at=now - timedelta(days=31)
    )
    fresh = _receipt_fixture(
        owner_id="owner-a", key_digest="fresh", committed_at=now - timedelta(days=29)
    )
    for receipt in (expired, fresh):
        container.crt_command_repo.insert_pending(receipt)
        container.crt_command_repo.commit(
            owner_id=receipt.owner_id,
            key_digest=receipt.key_digest,
            response_status=201,
            response_json='{"id":"tree"}',
            committed_at=receipt.created_at,
        )

    assert container.crt_command_repo.purge_expired(now=now) == 1
    expired_receipt = container.crt_command_repo.get(
        owner_id="owner-a", key_digest="expired"
    )
    assert expired_receipt is not None
    assert expired_receipt.state == "expired"
    assert expired_receipt.response_status is None
    assert expired_receipt.response_json is None
    assert expired_receipt.command == "create"
    assert expired_receipt.normalized_route == "/api/crt/trees"
    assert expired_receipt.request_hash == "request-expired"
    assert (
        container.crt_command_repo.get(owner_id="owner-a", key_digest="fresh")
        is not None
    )


def test_crt_receipt_maintenance_keeps_pending_receipts_for_reconciliation(
    container,
) -> None:
    now = utcnow()
    pending = _receipt_fixture(
        owner_id="owner-a", key_digest="pending", committed_at=now - timedelta(days=31)
    )
    container.crt_command_repo.insert_pending(pending)

    assert container.crt_command_repo.purge_expired(now=now) == 0
    stored = container.crt_command_repo.get(owner_id="owner-a", key_digest="pending")
    assert stored is not None
    assert stored.state == "pending"


def test_account_purge_removes_all_crt_receipts_before_deleting_user(container) -> None:
    now = utcnow()
    user = User(
        id="owner-purge",
        email="owner-purge@example.com",
        password_hash="fixture-hash",
        created_at=now,
    )
    container.user_repo.create(user)
    receipt = _receipt_fixture(
        owner_id=user.id, key_digest="account-purge", committed_at=now
    )
    container.crt_command_repo.insert_pending(receipt)
    container.crt_command_repo.commit(
        owner_id=user.id,
        key_digest=receipt.key_digest,
        response_status=201,
        response_json='{"id":"tree"}',
        committed_at=now,
    )

    container.account_service.purge_account(user.id)

    assert (
        container.crt_command_repo.get(owner_id=user.id, key_digest=receipt.key_digest)
        is None
    )
    with sqlite3.connect(container.crt_command_repo.db_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM crt_command_receipts WHERE owner_id = ?",
                (user.id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'crt_purged_owners'"
            ).fetchone()[0]
            == 0
        )
    owner_lock_dir = container.crt_command_repo.resolve(".crt-command-locks")
    assert not owner_lock_dir.exists() or not any(owner_lock_dir.iterdir())
    assert container.user_repo.get_by_id(user.id) is None


def test_account_purge_holds_crt_lock_through_tree_snapshot_and_user_delete(
    container, monkeypatch
) -> None:
    """A CRT command cannot enter after receipt deletion but before tree purge."""
    now = utcnow()
    user = User(
        id="owner-purge-lock",
        email="owner-purge-lock@example.com",
        password_hash="fixture-hash",
        created_at=now,
    )
    container.user_repo.create(user)
    container.tree_service.create_tree(
        TreeCreateRequest(name="Owned during purge"), owner_id=user.id
    )

    snapshot_started = Event()
    release_snapshot = Event()
    competing_command_errors: list[Exception] = []
    competing_command_finished = Event()
    competing_key = "purge-race-create"
    original_list = container.tree_service.list_trees

    def competing_command() -> None:
        try:
            container.crt_command_service.create_tree(
                TreeCreateRequest(name="Must not survive purge"),
                owner_id=user.id,
                idempotency_key=competing_key,
                normalized_route="/api/crt/trees",
                require_live_owner=True,
            )
        except Exception as exc:
            competing_command_errors.append(exc)
        finally:
            competing_command_finished.set()

    def blocked_list(*, owner_id: str):
        snapshot_started.set()
        assert release_snapshot.wait(timeout=2)
        return original_list(owner_id=owner_id)

    monkeypatch.setattr(container.tree_service, "list_trees", blocked_list)

    def purge() -> None:
        container.account_service.purge_account(user.id)

    purge_thread = Thread(target=purge)
    purge_thread.start()
    assert snapshot_started.wait(timeout=2)
    command_thread = Thread(target=competing_command)
    command_thread.start()
    assert not competing_command_finished.wait(timeout=0.1)
    release_snapshot.set()
    purge_thread.join(timeout=2)
    command_thread.join(timeout=2)

    assert not purge_thread.is_alive()
    assert not command_thread.is_alive()
    assert len(competing_command_errors) == 1
    assert isinstance(competing_command_errors[0], NotFoundError)
    assert original_list(owner_id=user.id) == []
    assert container.user_repo.get_by_id(user.id) is None


def test_crt_mutation_rejects_owner_in_deletion_window(container) -> None:
    now = utcnow()
    user = User(
        id="owner-deletion-window",
        email="owner-deletion-window@example.com",
        password_hash="fixture-hash",
        created_at=now,
        deletion_requested_at=now,
    )
    container.user_repo.create(user)

    with pytest.raises(NotFoundError):
        container.crt_command_service.create_tree(
            TreeCreateRequest(name="Must not be created"),
            owner_id=user.id,
            idempotency_key="deletion-window-create",
            normalized_route="/api/crt/trees",
            require_live_owner=True,
        )

    key_digest = container.crt_command_service._key_digest("deletion-window-create")
    assert (
        container.crt_command_repo.get(owner_id=user.id, key_digest=key_digest) is None
    )
    assert container.tree_service.list_trees(owner_id=user.id) == []


def test_privacy_maintenance_sweeps_crt_receipts(container, monkeypatch) -> None:
    calls: list[str] = []

    def purge_expired() -> int:
        calls.append("crt")
        return 3

    monkeypatch.setattr(container.crt_command_repo, "purge_expired", purge_expired)

    result = _run_privacy_maintenance_sweep(container)

    assert result[2] == 3
    assert calls == ["crt"]


def test_committed_crt_receipt_erases_pending_target_snapshot(container) -> None:
    service = container.crt_command_service
    result = service.create_tree(
        TreeCreateRequest(name="Snapshot lifetime"),
        owner_id="owner-snapshot",
        idempotency_key="snapshot-commit-key",
        normalized_route="/api/crt/trees",
    )

    assert result.response is not None
    receipt = service.command_repo.get(
        owner_id="owner-snapshot",
        key_digest=service._key_digest("snapshot-commit-key"),
    )
    assert receipt is not None
    assert receipt.state == "committed"
    assert receipt.pending_target_snapshot is None


def test_privacy_maintenance_reconciles_pending_marked_tree(container) -> None:
    owner_id = "owner-startup"
    key_digest = "a" * 64
    tree = container.tree_service.create_tree(
        TreeCreateRequest(name="Startup recovery"),
        owner_id=owner_id,
        tree_id="tree-startup-recovery",
        command_id=key_digest,
    )
    receipt = replace(
        _receipt_fixture(
            owner_id=owner_id,
            key_digest=key_digest,
            committed_at=tree.created_at,
        ),
        resource_id=tree.id,
        pending_target_snapshot=container.crt_command_service._encode_target_snapshot(
            tree
        ),
    )
    container.crt_command_repo.insert_pending(receipt)

    _run_privacy_maintenance_sweep(container)

    recovered = container.crt_command_repo.get(owner_id=owner_id, key_digest=key_digest)
    assert recovered is not None
    assert recovered.state == "committed"
    assert recovered.response_status == 201
    assert recovered.response_json is not None


def test_startup_reapplies_absent_create_from_pending_target_snapshot(
    container, monkeypatch
) -> None:
    owner_id = "owner-absent-create"
    key = "create-crash-key"
    service = container.crt_command_service
    original_create = service.tree_service.persist_prepared_create_tree

    def crash_before_tree_write(*args, **kwargs):
        raise RuntimeError("crash after pending receipt")

    monkeypatch.setattr(
        service.tree_service, "persist_prepared_create_tree", crash_before_tree_write
    )
    with pytest.raises(RuntimeError, match="crash after pending receipt"):
        service.create_tree(
            TreeCreateRequest(name="Recover me"),
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )

    key_digest = service._key_digest(key)
    pending = service.command_repo.get(owner_id=owner_id, key_digest=key_digest)
    assert pending is not None
    assert pending.pending_target_snapshot is not None
    assert not container.tree_service.tree_repo.exists(pending.resource_id)

    monkeypatch.setattr(
        service.tree_service, "persist_prepared_create_tree", original_create
    )
    assert service.reconcile_pending_commands() == 1
    recovered = service.command_repo.get(owner_id=owner_id, key_digest=key_digest)
    assert recovered is not None
    assert recovered.state == "committed"
    assert recovered.pending_target_snapshot is None
    assert (
        container.tree_service.get_tree_for_owner(
            recovered.resource_id, owner_id=owner_id
        ).title
        == "Recover me"
    )


def test_startup_reapplies_absent_import_from_pending_target_snapshot(
    container, monkeypatch
) -> None:
    owner_id = "owner-absent-import"
    service = container.crt_command_service
    source = service.tree_service.create_tree(
        TreeCreateRequest(name="Import source"), owner_id=owner_id
    )
    source_payload = service.tree_service.to_response(source)
    key = "import-crash-key"
    original_import = service.tree_service.persist_prepared_import_tree

    def crash_before_import_write(*args, **kwargs):
        raise RuntimeError("crash after pending receipt")

    monkeypatch.setattr(
        service.tree_service, "persist_prepared_import_tree", crash_before_import_write
    )
    from app.schemas.api import TreeImportRequest

    with pytest.raises(RuntimeError, match="crash after pending receipt"):
        service.import_tree(
            TreeImportRequest(tree=source_payload),
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees/import",
        )

    key_digest = service._key_digest(key)
    pending = service.command_repo.get(owner_id=owner_id, key_digest=key_digest)
    assert pending is not None
    assert pending.pending_target_snapshot is not None
    assert not container.tree_service.tree_repo.exists(pending.resource_id)

    monkeypatch.setattr(
        service.tree_service, "persist_prepared_import_tree", original_import
    )
    assert service.reconcile_pending_commands() == 1
    recovered = service.command_repo.get(owner_id=owner_id, key_digest=key_digest)
    assert recovered is not None
    assert recovered.state == "committed"
    assert recovered.pending_target_snapshot is None
    assert (
        container.tree_service.get_tree_for_owner(
            recovered.resource_id, owner_id=owner_id
        ).title
        == "Import source"
    )


def test_startup_reapplies_base_revision_update_from_pending_target_snapshot(
    container, monkeypatch
) -> None:
    owner_id = "owner-update-recovery"
    service = container.crt_command_service
    existing = service.tree_service.create_tree(
        TreeCreateRequest(name="Before"), owner_id=owner_id
    )
    current = service.tree_service.to_response(existing)
    payload = TreeUpdateRequest(
        name="After",
        schema_version=current.schema_version,
        metadata=current.metadata,
        nodes=current.nodes,
        relations=current.relations,
        owner_id=current.owner_id,
        expected_revision=current.revision,
    )
    key = "update-crash-key"
    original_update = service.tree_service.persist_prepared_update_tree

    def crash_before_update_write(*args, **kwargs):
        raise RuntimeError("crash after pending receipt")

    monkeypatch.setattr(
        service.tree_service, "persist_prepared_update_tree", crash_before_update_write
    )
    with pytest.raises(RuntimeError, match="crash after pending receipt"):
        service.update_tree(
            existing.id,
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route=f"/api/crt/trees/{existing.id}",
        )

    key_digest = service._key_digest(key)
    pending = service.command_repo.get(owner_id=owner_id, key_digest=key_digest)
    assert pending is not None
    assert pending.pending_target_snapshot is not None

    monkeypatch.setattr(
        service.tree_service, "persist_prepared_update_tree", original_update
    )
    assert service.reconcile_pending_commands() == 1
    recovered = service.command_repo.get(owner_id=owner_id, key_digest=key_digest)
    assert recovered is not None
    assert recovered.state == "committed"
    assert recovered.pending_target_snapshot is None
    assert (
        service.tree_service.get_tree_for_owner(existing.id, owner_id=owner_id).title
        == "After"
    )


def test_pending_marker_with_tampered_target_schema_stays_pending(container) -> None:
    """Recovery validates the target before reconstructing a marked response."""
    service = container.crt_command_service
    owner_id = "owner-tampered-schema"
    key_digest = "c" * 64
    tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Marked target"),
        owner_id=owner_id,
        tree_id="tree-tampered-schema",
        command_id=key_digest,
    )
    target = json.loads(service._encode_target_snapshot(tree))
    target["schema_version"] = 2
    target["metadata"]["version"] = 2
    receipt = replace(
        _receipt_fixture(
            owner_id=owner_id,
            key_digest=key_digest,
            committed_at=utcnow(),
        ),
        resource_id=tree.id,
        pending_target_snapshot=json.dumps(target),
    )
    service.command_repo.insert_pending(receipt)

    assert service.reconcile_pending_commands() == 0
    still_pending = service.command_repo.get(owner_id=owner_id, key_digest=key_digest)
    assert still_pending is not None
    assert still_pending.state == "pending"
    assert service.tree_service.get_tree(tree.id).title == "Marked target"


def test_malformed_pending_target_snapshot_stays_pending(container) -> None:
    service = container.crt_command_service
    receipt = replace(
        _receipt_fixture(
            owner_id="owner-malformed",
            key_digest="b" * 64,
            committed_at=utcnow(),
        ),
        resource_id="tree-malformed",
        pending_target_snapshot="not-json",
    )
    service.command_repo.insert_pending(receipt)

    assert service.reconcile_pending_commands() == 0

    still_pending = service.command_repo.get(
        owner_id="owner-malformed", key_digest="b" * 64
    )
    assert still_pending is not None
    assert still_pending.state == "pending"


def test_reconcile_pending_commands_continues_after_malformed_receipt(
    container,
) -> None:
    service = container.crt_command_service
    owner_id = "owner-isolated-reconciliation"
    now = utcnow()
    malformed = replace(
        _receipt_fixture(
            owner_id=owner_id,
            key_digest="a" * 64,
            committed_at=now,
        ),
        resource_id="tree-malformed-first",
        pending_target_snapshot="not-json",
    )
    healthy_key = "b" * 64
    healthy_tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Healthy later command"),
        owner_id=owner_id,
        tree_id="tree-healthy-second",
        command_id=healthy_key,
    )
    healthy = replace(
        _receipt_fixture(
            owner_id=owner_id,
            key_digest=healthy_key,
            committed_at=now + timedelta(seconds=1),
        ),
        resource_id=healthy_tree.id,
        pending_target_snapshot=service._encode_target_snapshot(healthy_tree),
    )
    service.command_repo.insert_pending(malformed)
    service.command_repo.insert_pending(healthy)

    assert service.reconcile_pending_commands() == 1
    assert (
        service.command_repo.get(
            owner_id=owner_id, key_digest=malformed.key_digest
        ).state
        == "pending"
    )
    assert (
        service.command_repo.get(owner_id=owner_id, key_digest=healthy_key).state
        == "committed"
    )


def test_reconcile_pending_commands_skips_malformed_row_and_keeps_later_rows(
    container,
) -> None:
    service = container.crt_command_service
    owner_id = "owner-malformed-row"
    now = utcnow()
    malformed_key = "d" * 64
    malformed = _receipt_fixture(
        owner_id=owner_id,
        key_digest=malformed_key,
        committed_at=now,
    )
    healthy_key = "e" * 64
    healthy_tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Healthy after malformed row"),
        owner_id=owner_id,
        tree_id="tree-healthy-after-row",
        command_id=healthy_key,
    )
    healthy = replace(
        _receipt_fixture(
            owner_id=owner_id,
            key_digest=healthy_key,
            committed_at=now + timedelta(seconds=1),
        ),
        resource_id=healthy_tree.id,
        pending_target_snapshot=service._encode_target_snapshot(healthy_tree),
    )
    service.command_repo.insert_pending(malformed)
    service.command_repo.insert_pending(healthy)
    with sqlite3.connect(service.command_repo.db_path) as connection:
        connection.execute(
            "UPDATE crt_command_receipts SET created_at = ? WHERE owner_id = ? AND key_digest = ?",
            ("not-a-timestamp", owner_id, malformed_key),
        )

    assert service.reconcile_pending_commands() == 1
    with sqlite3.connect(service.command_repo.db_path) as connection:
        assert (
            connection.execute(
                "SELECT state FROM crt_command_receipts WHERE owner_id = ? AND key_digest = ?",
                (owner_id, malformed_key),
            ).fetchone()[0]
            == "pending"
        )
    assert (
        service.command_repo.get(owner_id=owner_id, key_digest=healthy_key).state
        == "committed"
    )


def _marked_recovery_fixture(container, *, command: str = "create"):
    service = container.crt_command_service
    owner_id = f"owner-matrix-{command}"
    key_digest = ("f" if command == "create" else "e") * 64
    now = utcnow()
    payload = TreeCreateRequest(
        name="Recovery matrix",
        nodes=[
            NodeResponse(
                id="node-a",
                label="Cause",
                type="child",
                position=Position(x=0, y=0),
            ),
            NodeResponse(
                id="node-b",
                label="Effect",
                type="child",
                position=Position(x=10, y=10),
            ),
        ],
        relations=[
            RelationResponse(
                id="relation-a",
                source_node_id="node-a",
                target_node_id="node-b",
                created_at=now,
            )
        ],
    )
    tree = service.tree_service.create_tree(
        payload,
        owner_id=owner_id,
        tree_id=f"tree-{command}-matrix",
        command_id=key_digest,
    )
    tree = tree.model_copy(update={"last_command_id": key_digest})
    service.tree_service.tree_repo.save(tree)
    service.tree_service._cache.clear()
    receipt = replace(
        _receipt_fixture(
            owner_id=owner_id,
            key_digest=key_digest,
            committed_at=now,
        ),
        command=command,
        resource_id=tree.id,
        base_revision=1 if command == "update" else None,
        target_revision=2 if command == "update" else 1,
        pending_target_snapshot=service._encode_target_snapshot(tree),
    )
    return service, tree, receipt


def _recovery_target_variant(tree, receipt, variant: str):  # noqa: C901, PLR0912
    target = tree
    if variant == "tree_id":
        target = target.model_copy(update={"id": "other-tree"})
    elif variant == "owner":
        target = target.model_copy(update={"owner_id": "other-owner"})
    elif variant == "marker":
        target = target.model_copy(update={"last_command_id": "a" * 64})
    elif variant == "schema":
        target = target.model_copy(update={"schema_version": 2})
    elif variant == "metadata_missing":
        target = target.model_copy(update={"metadata": None})
    elif variant == "metadata_version":
        metadata = dict(target.metadata or {})
        metadata["version"] = 2
        target = target.model_copy(update={"metadata": metadata})
    elif variant == "metadata_owner":
        metadata = dict(target.metadata or {})
        metadata["owner_id"] = "other-owner"
        target = target.model_copy(update={"metadata": metadata})
    elif variant == "empty_title":
        target = target.model_copy(update={"title": "   "})
    elif variant == "empty_label":
        target = target.model_copy(
            update={
                "nodes": [
                    tree.nodes[0].model_copy(update={"label": "   "}),
                    *tree.nodes[1:],
                ]
            }
        )
    elif variant == "duplicate_node":
        target = target.model_copy(update={"nodes": [tree.nodes[0], tree.nodes[0]]})
    elif variant == "duplicate_relation":
        target = target.model_copy(
            update={"relations": [tree.relations[0], tree.relations[0]]}
        )
    elif variant == "missing_endpoint":
        relation = tree.relations[0].model_copy(update={"target_id": "missing"})
        target = target.model_copy(update={"relations": [relation]})
    elif variant == "self_link":
        relation = tree.relations[0].model_copy(update={"target_id": "node-a"})
        target = target.model_copy(update={"relations": [relation]})
    elif variant == "duplicate_pair":
        duplicate = tree.relations[0].model_copy(update={"id": "relation-b"})
        target = target.model_copy(update={"relations": [tree.relations[0], duplicate]})
    elif variant == "cycle":
        reverse = tree.relations[0].model_copy(
            update={"id": "relation-b", "source_id": "node-b", "target_id": "node-a"}
        )
        target = target.model_copy(update={"relations": [tree.relations[0], reverse]})
    elif variant == "create_base":
        receipt = replace(receipt, base_revision=1)
    elif variant == "create_target":
        receipt = replace(receipt, target_revision=2)
    elif variant == "create_tree_revision":
        target = target.model_copy(update={"revision": 2})
    elif variant == "update_base_missing":
        receipt = replace(
            receipt, command="update", base_revision=None, target_revision=2
        )
        target = target.model_copy(update={"revision": 2})
    elif variant == "update_base_zero":
        receipt = replace(receipt, command="update", base_revision=0, target_revision=1)
    elif variant == "update_target":
        receipt = replace(receipt, command="update", base_revision=1, target_revision=3)
        target = target.model_copy(update={"revision": 3})
    elif variant == "update_tree_revision":
        receipt = replace(receipt, command="update", base_revision=1, target_revision=2)
        target = target.model_copy(update={"revision": 3})
    elif variant == "command":
        receipt = replace(receipt, command="unknown")
    elif variant == "snapshot_missing":
        return target, replace(receipt, pending_target_snapshot=None)
    else:  # pragma: no cover - protects the matrix from silent omissions
        raise AssertionError(variant)
    return target, replace(
        receipt,
        pending_target_snapshot=service_encode_target_snapshot(tree, target),
    )


def service_encode_target_snapshot(tree, target) -> str:
    """Keep target construction in one place while preserving receipt metadata."""
    _ = tree
    return json.dumps(
        target.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )


@pytest.mark.parametrize(
    "variant",
    [
        "tree_id",
        "owner",
        "marker",
        "schema",
        "metadata_missing",
        "metadata_version",
        "metadata_owner",
        "empty_title",
        "empty_label",
        "duplicate_node",
        "duplicate_relation",
        "missing_endpoint",
        "self_link",
        "duplicate_pair",
        "cycle",
        "create_base",
        "create_target",
        "create_tree_revision",
        "update_base_missing",
        "update_base_zero",
        "update_target",
        "update_tree_revision",
        "command",
        "snapshot_missing",
    ],
)
def test_recovery_target_matrix_fails_closed_without_tree_mutation(container, variant):
    service, tree, receipt = _marked_recovery_fixture(container)
    target, tampered_receipt = _recovery_target_variant(tree, receipt, variant)
    assert target.id == tree.id or variant == "tree_id"

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service._decode_target_snapshot(tampered_receipt)

    assert service.tree_service.get_tree(tree.id) == tree


def _live_tree_variant(tree, variant: str):  # noqa: PLR0911
    if variant == "tree_id":
        return tree.model_copy(update={"id": "other-tree"})
    if variant == "owner":
        return tree.model_copy(update={"owner_id": "other-owner"})
    if variant == "schema":
        return tree.model_copy(update={"schema_version": 2})
    if variant == "metadata_missing":
        return tree.model_copy(update={"metadata": None})
    if variant == "metadata_version":
        metadata = dict(tree.metadata or {})
        metadata["version"] = 2
        return tree.model_copy(update={"metadata": metadata})
    if variant == "metadata_owner":
        metadata = dict(tree.metadata or {})
        metadata["owner_id"] = "other-owner"
        return tree.model_copy(update={"metadata": metadata})
    if variant == "duplicate_node":
        return tree.model_copy(update={"nodes": [tree.nodes[0], tree.nodes[0]]})
    if variant == "duplicate_relation":
        return tree.model_copy(
            update={"relations": [tree.relations[0], tree.relations[0]]}
        )
    if variant == "missing_endpoint":
        relation = tree.relations[0].model_copy(update={"target_id": "missing"})
        return tree.model_copy(update={"relations": [relation]})
    if variant == "self_link":
        relation = tree.relations[0].model_copy(update={"target_id": "node-a"})
        return tree.model_copy(update={"relations": [relation]})
    if variant == "duplicate_pair":
        duplicate = tree.relations[0].model_copy(update={"id": "relation-b"})
        return tree.model_copy(update={"relations": [tree.relations[0], duplicate]})
    if variant == "cycle":
        reverse = tree.relations[0].model_copy(
            update={"id": "relation-b", "source_id": "node-b", "target_id": "node-a"}
        )
        return tree.model_copy(update={"relations": [tree.relations[0], reverse]})
    raise AssertionError(variant)


@pytest.mark.parametrize(
    "variant",
    [
        "tree_id",
        "owner",
        "schema",
        "metadata_missing",
        "metadata_version",
        "metadata_owner",
        "duplicate_node",
        "duplicate_relation",
        "missing_endpoint",
        "self_link",
        "duplicate_pair",
        "cycle",
    ],
)
def test_live_tree_shape_matrix_fails_closed_without_rewriting_live_tree(
    container, variant
):
    service, tree, receipt = _marked_recovery_fixture(container, command="update")
    tampered = _live_tree_variant(tree, variant)

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service._validate_live_tree_shape(receipt, tampered)

    assert service.tree_service.get_tree(tree.id) == tree


def test_marked_tree_target_mismatch_is_unavailable(container):
    service, tree, receipt = _marked_recovery_fixture(container)
    target = tree.model_copy(update={"title": "Different target"})
    receipt = replace(
        receipt,
        pending_target_snapshot=service._encode_target_snapshot(target),
    )

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service._validate_marked_tree(receipt, tree)

    assert service.tree_service.get_tree(tree.id) == tree


def _pending_delete_receipt(
    service, *, owner_id: str, tree_id: str, key: str, **updates
):
    expected_revision = 1
    receipt_base_revision = updates.pop("base_revision", expected_revision)
    fields = {
        "command": "delete",
        "normalized_route": f"/api/crt/trees:{tree_id}",
        "request_hash": service._request_hash(
            {"tree_id": tree_id, "expected_revision": expected_revision}
        ),
        "resource_id": tree_id,
        "base_revision": receipt_base_revision,
        "target_revision": None,
        "pending_target_snapshot": None,
    }
    fields.update(updates)
    receipt = replace(
        _receipt_fixture(
            owner_id=owner_id,
            key_digest=service._key_digest(key),
            committed_at=utcnow(),
        ),
        **fields,
    )
    service.command_repo.insert_pending(receipt)
    return receipt


@pytest.mark.parametrize("state", ["current", "absent"])
def test_pending_delete_reconciles_current_or_absent_tree(container, state):
    service = container.crt_command_service
    owner_id = f"owner-delete-{state}"
    tree_id = f"tree-delete-{state}"
    key = f"pending-delete-{state}"
    if state == "current":
        service.tree_service.create_tree(
            TreeCreateRequest(name="Delete current"),
            owner_id=owner_id,
            tree_id=tree_id,
        )
    _pending_delete_receipt(service, owner_id=owner_id, tree_id=tree_id, key=key)

    result = service.delete_tree(
        tree_id,
        expected_revision=1,
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )

    assert result.status_code == 204
    assert (
        service.command_repo.get(
            owner_id=owner_id, key_digest=service._key_digest(key)
        ).state
        == "committed"
    )
    if state == "current":
        with pytest.raises(NotFoundError):
            service.tree_service.get_tree(tree_id)


def test_pending_delete_divergence_stays_pending_and_preserves_tree(container):
    service = container.crt_command_service
    owner_id = "owner-delete-diverged"
    tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Diverged delete"),
        owner_id=owner_id,
        tree_id="tree-delete-diverged",
    )
    service.tree_service.tree_repo.mutate(
        tree.id,
        update=lambda current: current.model_copy(update={"revision": 2}),
    )
    _pending_delete_receipt(
        service, owner_id=owner_id, tree_id=tree.id, key="diverged-delete"
    )

    with pytest.raises(ConflictError):
        service.delete_tree(
            tree.id,
            expected_revision=1,
            owner_id=owner_id,
            idempotency_key="diverged-delete",
            normalized_route="/api/crt/trees",
        )

    assert (
        service.command_repo.get(
            owner_id=owner_id,
            key_digest=service._key_digest("diverged-delete"),
        ).state
        == "pending"
    )
    assert service.tree_service.get_tree(tree.id).revision == 2


@pytest.mark.parametrize(
    "updates",
    [
        {"base_revision": None},
        {"base_revision": 0},
        {"target_revision": 1},
        {"pending_target_snapshot": "unexpected"},
    ],
)
def test_pending_delete_malformed_invariants_are_unavailable(container, updates):
    service = container.crt_command_service
    owner_id = "owner-delete-malformed"
    tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Malformed delete"), owner_id=owner_id
    )
    key = f"malformed-delete-{len(service.command_repo.list_pending())}"
    _pending_delete_receipt(
        service,
        owner_id=owner_id,
        tree_id=tree.id,
        key=key,
        **updates,
    )

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service.delete_tree(
            tree.id,
            expected_revision=1,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )

    assert service.tree_service.get_tree(tree.id) == tree


def test_delete_receipt_with_wrong_command_is_unavailable(container):
    service = container.crt_command_service
    receipt = replace(
        _receipt_fixture(
            owner_id="owner-delete-command",
            key_digest="1" * 64,
            committed_at=utcnow(),
        ),
        command="update",
        base_revision=1,
        target_revision=None,
        pending_target_snapshot=None,
    )

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service._validated_delete_base_revision(receipt)


def test_pending_delete_reconciles_absent_tree_during_startup(container):
    service = container.crt_command_service
    owner_id = "owner-startup-delete"
    tree_id = "tree-startup-delete"
    key = "startup-delete"
    _pending_delete_receipt(service, owner_id=owner_id, tree_id=tree_id, key=key)

    assert service.reconcile_pending_commands() == 1
    stored = service.command_repo.get(
        owner_id=owner_id, key_digest=service._key_digest(key)
    )
    assert stored is not None
    assert stored.state == "committed"


def test_reconcile_pending_command_with_missing_row_does_not_mutate_state(
    container, monkeypatch
):
    service = container.crt_command_service
    service, tree, receipt = _marked_recovery_fixture(container)
    service.command_repo.insert_pending(receipt)
    original_get = service.command_repo.get
    monkeypatch.setattr(service.command_repo, "get", lambda **kwargs: None)

    assert service.reconcile_pending_commands() == 0

    monkeypatch.setattr(service.command_repo, "get", original_get)
    assert service.tree_service.get_tree(tree.id) == tree


def test_reconcile_pending_unknown_command_is_left_pending(container):
    service, tree, receipt = _marked_recovery_fixture(container)
    receipt = replace(receipt, command="unknown")
    service.command_repo.insert_pending(receipt)

    assert service.reconcile_pending_commands() == 0
    assert (
        service.command_repo.get(
            owner_id=receipt.owner_id, key_digest=receipt.key_digest
        ).state
        == "pending"
    )
    assert service.tree_service.get_tree(tree.id) == tree


def test_missing_tree_recovery_only_recreates_create_import_commands(container):
    service, tree, receipt = _marked_recovery_fixture(container)
    service.command_repo.insert_pending(receipt)
    service.tree_service.delete_tree(tree.id, owner_id=tree.owner_id)

    recovered = service._reconcile_pending(receipt, payload=None, schema_version=None)
    assert recovered is not None
    assert recovered.status_code == 201
    assert service.tree_service.get_tree(tree.id).title == tree.title

    invalid = replace(receipt, command="update")
    assert service._reconcile_missing_tree(invalid) is None


def test_create_recovery_marker_mismatch_stays_uncommitted(container):
    service, tree, receipt = _marked_recovery_fixture(container)
    tampered = tree.model_copy(update={"last_command_id": "a" * 64})

    assert service._reconcile_existing_create(receipt, tampered) is None
    assert service.tree_service.get_tree(tree.id) == tree


def test_update_recovery_marked_and_unmarked_paths_are_distinct(container):
    service, tree, receipt = _marked_recovery_fixture(container, command="update")
    target = tree.model_copy(update={"revision": 2})
    marked = replace(
        receipt,
        target_revision=2,
        pending_target_snapshot=service._encode_target_snapshot(target),
    )
    marked_tree = target.model_copy(update={"last_command_id": receipt.key_digest})
    service.command_repo.insert_pending(marked)

    result = service._reconcile_existing_update_marker(marked, marked_tree)
    assert result is not None
    assert result.status_code == 200

    unmarked = replace(
        receipt,
        base_revision=1,
        target_revision=2,
        pending_target_snapshot=service._encode_target_snapshot(target),
    )
    prior = tree.model_copy(update={"revision": 2, "last_command_id": "a" * 64})
    assert service._reconcile_existing_update(unmarked, prior, payload=None) is None
    diverged = tree.model_copy(update={"revision": 2, "last_command_id": None})
    assert service._reconcile_existing_update(unmarked, diverged, payload=None) is None


def test_startup_skips_absent_non_create_command_without_mutation(container):
    service, tree, receipt = _marked_recovery_fixture(container, command="update")
    service.command_repo.insert_pending(receipt)
    service.tree_service.delete_tree(tree.id, owner_id=tree.owner_id)

    assert service.reconcile_pending_commands() == 0
    assert (
        service.command_repo.get(
            owner_id=receipt.owner_id, key_digest=receipt.key_digest
        ).state
        == "pending"
    )


def test_startup_reconciles_current_pending_delete(container):
    service = container.crt_command_service
    owner_id = "owner-startup-current-delete"
    tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Startup current delete"), owner_id=owner_id
    )
    key = "startup-current-delete"
    _pending_delete_receipt(service, owner_id=owner_id, tree_id=tree.id, key=key)

    assert service.reconcile_pending_commands() == 1
    with pytest.raises(NotFoundError):
        service.tree_service.get_tree(tree.id)


def test_startup_update_with_unmarked_target_stays_pending(container):
    service, tree, receipt = _marked_recovery_fixture(container, command="update")
    service.command_repo.insert_pending(receipt)

    assert service.reconcile_pending_commands() == 0
    assert (
        service.command_repo.get(
            owner_id=receipt.owner_id, key_digest=receipt.key_digest
        ).state
        == "pending"
    )


def test_pending_update_marked_path_reconciles_exact_target(container):
    service, tree, receipt = _marked_recovery_fixture(container, command="update")
    target = tree.model_copy(update={"revision": 2})
    receipt = replace(
        receipt,
        target_revision=2,
        pending_target_snapshot=service._encode_target_snapshot(target),
    )
    marked_tree = target.model_copy(update={"last_command_id": receipt.key_digest})
    service.command_repo.insert_pending(receipt)

    result = service._reconcile_existing_update(receipt, marked_tree, payload=None)
    assert result is not None
    assert result.status_code == 200


def test_pending_update_ignores_committed_prior_when_base_revision_diverged(container):
    service, tree, receipt = _marked_recovery_fixture(container, command="update")
    prior_key = "a" * 64
    prior = replace(
        _receipt_fixture(
            owner_id=receipt.owner_id,
            key_digest=prior_key,
            committed_at=utcnow(),
        ),
        resource_id=tree.id,
    )
    service.command_repo.insert_pending(prior)
    service.command_repo.commit(
        owner_id=prior.owner_id,
        key_digest=prior.key_digest,
        response_status=201,
        response_json='{"id":"prior"}',
    )
    prior_tree = tree.model_copy(update={"revision": 2, "last_command_id": prior_key})

    assert service._reconcile_existing_update(receipt, prior_tree, payload=None) is None


def test_pending_command_branch_returns_none_for_unknown_retry(container):
    service, tree, receipt = _marked_recovery_fixture(container)
    unknown = replace(receipt, command="unknown")

    assert (
        service._reconcile_pending(unknown, payload=None, schema_version=None) is None
    )

    update_receipt = replace(receipt, command="update", target_revision=2)
    assert (
        service._reconcile_pending(update_receipt, payload=None, schema_version=None)
        is None
    )


def test_startup_update_marker_match_takes_reconciliation_fast_path(container):
    service, tree, receipt = _marked_recovery_fixture(container, command="update")
    live = service.tree_service.tree_repo.mutate(
        tree.id,
        update=lambda current: current.model_copy(update={"revision": 2}),
        command_id=receipt.key_digest,
    )
    service.tree_service._cache.clear()
    receipt = replace(
        receipt,
        target_revision=2,
        pending_target_snapshot=service._encode_target_snapshot(live),
    )
    service.command_repo.insert_pending(receipt)
    assert live.revision == 2
    assert live.last_command_id == receipt.key_digest
    assert service.tree_service.get_tree(tree.id).revision == 2

    assert service.reconcile_pending_commands() == 1
