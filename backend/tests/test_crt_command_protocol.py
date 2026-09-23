from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from app.exceptions import (
    ConflictError,
    IdempotencyConflictError,
    IdempotencyReceiptExpiredError,
    IdempotencyReceiptUnavailableError,
    PendingCommandError,
    StaleRevisionError,
    ValidationFailure,
)
from app.repositories.crt_command import CrtCommandReceipt, CrtCommandRepository
from app.schemas.api import (
    NodeResponse,
    RelationResponse,
    TreeCreateRequest,
    TreeDetailResponse,
    TreeImportRequest,
    TreeMetadata,
    TreeUpdateRequest,
)
from app.schemas.common import Position
from app.utils.time import utcnow


def _enable_crt(api_client) -> None:
    api_client.app.state.container.feature_flag_service.set_mode(
        "crt_canvas", "on", operator_id="test-operator"
    )


def _create_tree(api_client, *, name: str = "CRT tree") -> dict:
    response = api_client.post(
        "/api/crt/trees",
        json={"name": name},
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174100"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_019_FR_019_crt_import_replays_and_remaps_entities(api_client) -> None:
    _enable_crt(api_client)
    source_response = api_client.post(
        "/api/crt/trees",
        json={
            "name": "Import source",
            "nodes": [
                {
                    "id": "legacy-a",
                    "label": " Cause ",
                    "type": "child",
                    "position": {"x": 0, "y": 0},
                },
                {
                    "id": "legacy-b",
                    "label": "Effect",
                    "type": "child",
                    "position": {"x": 10, "y": 10},
                },
            ],
            "relations": [
                {
                    "id": "legacy-relation",
                    "source_node_id": "legacy-a",
                    "target_node_id": "legacy-b",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        },
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174100"},
    )
    assert source_response.status_code == 201, source_response.text
    source = source_response.json()
    imported_key = "123e4567-e89b-12d3-a456-426614174101"

    first = api_client.post(
        "/api/crt/trees/import",
        json={"tree": source},
        headers={"Idempotency-Key": imported_key},
    )
    replay = api_client.post(
        "/api/crt/trees/import",
        json={"tree": source},
        headers={"Idempotency-Key": imported_key},
    )

    assert first.status_code == 201, first.text
    assert replay.status_code == 201
    assert replay.json() == first.json()
    imported = first.json()
    assert imported["id"] != source["id"]
    assert [node["label"] for node in imported["nodes"]] == [
        node["label"].strip() for node in source["nodes"]
    ]
    assert {node["id"] for node in imported["nodes"]}.isdisjoint(
        {node["id"] for node in source["nodes"]}
    )
    assert all(
        uuid.UUID(node["id"].removeprefix("node_")).version == 4
        for node in imported["nodes"]
    )
    assert all(
        uuid.UUID(relation["id"].removeprefix("relation_")).version == 4
        for relation in imported["relations"]
    )
    assert {relation["source_node_id"] for relation in imported["relations"]} <= {
        node["id"] for node in imported["nodes"]
    }
    assert {relation["target_node_id"] for relation in imported["relations"]} <= {
        node["id"] for node in imported["nodes"]
    }


def test_019_FR_019_crt_delete_replays_content_free_tombstone(api_client) -> None:
    _enable_crt(api_client)
    tree = _create_tree(api_client, name="Delete me")
    key = "123e4567-e89b-12d3-a456-426614174102"

    first = api_client.delete(
        f"/api/crt/trees/{tree['id']}",
        params={"expected_revision": tree["revision"]},
        headers={"Idempotency-Key": key},
    )
    replay = api_client.delete(
        f"/api/crt/trees/{tree['id']}",
        params={"expected_revision": tree["revision"]},
        headers={"Idempotency-Key": key},
    )

    assert first.status_code == 204
    assert first.content == b""
    assert replay.status_code == 204
    assert replay.content == b""
    assert api_client.get(f"/api/crt/trees/{tree['id']}").status_code == 404

    owner_id = api_client.get("/api/auth/me").json()["id"]
    service = api_client.app.state.container.crt_command_service
    receipt = service.command_repo.get(
        owner_id=owner_id, key_digest=service._key_digest(key)
    )
    assert receipt is not None
    assert receipt.command == "delete"
    assert receipt.response_json == "{}"
    assert (
        service.command_repo.get(
            owner_id=owner_id,
            key_digest=service._key_digest("123e4567-e89b-12d3-a456-426614174100"),
        )
        is not None
    )
    reused_create_key = api_client.post(
        "/api/crt/trees",
        json={"name": "Delete me"},
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174100"},
    )
    assert reused_create_key.status_code == 409
    assert reused_create_key.json()["detail"]["reason"] == "idempotency_receipt_expired"


def test_019_FR_019_crt_delete_rejects_stale_revision_without_mutation(
    api_client,
) -> None:
    _enable_crt(api_client)
    tree = _create_tree(api_client, name="Stale delete")
    update = {
        "name": tree["name"],
        "schema_version": tree["schema_version"],
        "metadata": tree["metadata"],
        "nodes": tree["nodes"],
        "relations": tree["relations"],
        "owner_id": tree["owner_id"],
        "expected_revision": tree["revision"],
    }
    updated = api_client.put(
        f"/api/crt/trees/{tree['id']}",
        json=update,
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174103"},
    )
    assert updated.status_code == 200

    stale = api_client.delete(
        f"/api/crt/trees/{tree['id']}",
        params={"expected_revision": tree["revision"]},
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174104"},
    )

    assert stale.status_code == 409
    assert stale.json()["detail"]["reason"] == "stale_revision"
    assert api_client.get(f"/api/crt/trees/{tree['id']}").status_code == 200


def test_crt_delete_cannot_remove_legacy_update_landed_after_precheck(
    container, monkeypatch
) -> None:
    service = container.crt_command_service
    owner_id = "owner-delete-race"
    tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Delete race"), owner_id=owner_id
    )
    original_get = service.tree_service.get_tree_for_owner
    updated = False

    def get_then_legacy_update(tree_id: str, *, owner_id: str):
        nonlocal updated
        current = original_get(tree_id, owner_id=owner_id)
        if not updated:
            updated = True
            service.tree_service.tree_repo.mutate(
                tree_id,
                update=lambda existing: existing.model_copy(
                    update={"description": "legacy newer"}, deep=True
                ),
            )
        return current

    monkeypatch.setattr(
        service.tree_service, "get_tree_for_owner", get_then_legacy_update
    )

    with pytest.raises(StaleRevisionError):
        service.delete_tree(
            tree.id,
            expected_revision=tree.revision,
            owner_id=owner_id,
            idempotency_key="delete-race-key",
            normalized_route=f"/api/crt/trees/{tree.id}",
        )

    current = service.tree_service.get_tree(tree.id)
    assert current.revision == tree.revision + 1
    assert current.description == "legacy newer"


def test_019_FR_019_crt_update_rejects_whitespace_card_without_mutation(
    api_client,
) -> None:
    _enable_crt(api_client)
    tree = _create_tree(api_client, name="Whitespace card")
    tree["nodes"] = [
        {
            "id": "node-existing",
            "label": "Valid card",
            "type": "child",
            "position": {"x": 0, "y": 0},
        }
    ]
    update = {
        "name": tree["name"],
        "schema_version": tree["schema_version"],
        "metadata": tree["metadata"],
        "nodes": tree["nodes"],
        "relations": tree["relations"],
        "owner_id": tree["owner_id"],
        "expected_revision": tree["revision"],
    }
    created = api_client.put(
        f"/api/crt/trees/{tree['id']}",
        json=update,
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174105"},
    )
    assert created.status_code == 200
    canonical = created.json()

    bad = api_client.put(
        f"/api/crt/trees/{tree['id']}",
        json={
            **update,
            "expected_revision": canonical["revision"],
            "nodes": [{**canonical["nodes"][0], "label": "   "}],
        },
        headers={"Idempotency-Key": "123e4567-e89b-12d3-a456-426614174106"},
    )

    assert bad.status_code == 400
    assert bad.json()["detail"]["reason"] == "empty_card_label"
    assert api_client.get(f"/api/crt/trees/{tree['id']}").json() == canonical


def test_invalid_create_graph_is_rejected_before_pending_receipt(api_client) -> None:
    """Semantic validation failures must not poison an idempotency key."""

    _enable_crt(api_client)
    key = "123e4567-e89b-12d3-a456-426614174199"
    response = api_client.post(
        "/api/crt/trees",
        json={
            "name": "Invalid graph",
            "nodes": [
                {
                    "id": "node_a",
                    "label": "Known node",
                    "type": "child",
                    "position": {"x": 0, "y": 0},
                }
            ],
            "relations": [
                {
                    "id": "relation_missing",
                    "source_node_id": "node_a",
                    "target_node_id": "node_missing",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        },
        headers={"Idempotency-Key": key},
    )

    assert response.status_code == 400
    service = api_client.app.state.container.crt_command_service
    assert (
        service.command_repo.get(
            owner_id=api_client.get("/api/auth/me").json()["id"],
            key_digest=service._key_digest(key),
        )
        is None
    )


def test_command_lock_serializes_independent_repository_instances(tmp_path) -> None:
    """The durable command window must not rely on one process-local RLock."""

    class FirstWorkerRepository(CrtCommandRepository):
        _process_lock = threading.RLock()

    class SecondWorkerRepository(CrtCommandRepository):
        _process_lock = threading.RLock()

    # Model separate worker processes, each with its own in-memory lock.
    first = FirstWorkerRepository(tmp_path)
    second = SecondWorkerRepository(tmp_path)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def hold_first() -> None:
        with first.command_lock("owner-a"):
            first_entered.set()
            assert release_first.wait(timeout=2)

    def enter_second() -> None:
        assert first_entered.wait(timeout=2)
        with second.command_lock("owner-a"):
            second_entered.set()

    first_thread = threading.Thread(target=hold_first)
    second_thread = threading.Thread(target=enter_second)
    first_thread.start()
    second_thread.start()
    assert first_entered.wait(timeout=2)
    assert not second_entered.wait(timeout=0.1)
    release_first.set()
    assert second_entered.wait(timeout=2)
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)
    assert not first_thread.is_alive()
    assert not second_thread.is_alive()


def test_019_FR_020_crt_export_is_gated_owner_scoped_read_without_key(
    second_api_client,
) -> None:
    owner_a, owner_b = second_api_client
    _enable_crt(owner_a)
    _enable_crt(owner_b)
    tree = _create_tree(owner_a, name="Export me")

    exported = owner_a.post(f"/api/crt/trees/{tree['id']}/export")
    wrong_owner = owner_b.post(f"/api/crt/trees/{tree['id']}/export")

    assert exported.status_code == 200
    assert exported.json()["tree"] == tree
    assert wrong_owner.status_code == 404


def _graph_create_payload(name: str = "Graph matrix") -> TreeCreateRequest:
    now = utcnow()
    return TreeCreateRequest(
        name=name,
        nodes=[
            NodeResponse(
                id="graph-a",
                label="Cause",
                type="child",
                position=Position(x=0, y=0),
            ),
            NodeResponse(
                id="graph-b",
                label="Effect",
                type="child",
                position=Position(x=1, y=1),
            ),
        ],
        relations=[
            RelationResponse(
                id="graph-relation",
                source_node_id="graph-a",
                target_node_id="graph-b",
                created_at=now,
            )
        ],
    )


@pytest.mark.parametrize("kind", ["schema_mismatch", "unsupported_schema"])
def test_create_schema_matrix_rejects_before_receipt_or_tree_write(container, kind):
    service = container.crt_command_service
    payload = _graph_create_payload()
    if kind == "schema_mismatch":
        payload = payload.model_copy(
            update={
                "schema_version": 1,
                "metadata": payload.metadata,
            }
        )
        now = utcnow()
        payload = payload.model_copy(
            update={
                "metadata": TreeMetadata.from_timestamps(
                    created_at=now, updated_at=now
                ).model_copy(update={"version": 2})
            }
        )
    else:
        payload = payload.model_copy(update={"schema_version": 2})
    key = f"create-schema-{kind}"

    with pytest.raises(ValidationFailure):
        service.create_tree(
            payload,
            owner_id="owner-create-schema",
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )

    assert (
        service.command_repo.get(
            owner_id="owner-create-schema", key_digest=service._key_digest(key)
        )
        is None
    )


def test_update_requires_expected_revision_before_receipt_lookup(container):
    service = container.crt_command_service
    now = utcnow()
    payload = TreeUpdateRequest(
        name="Revision required",
        expected_revision=None,
        metadata=TreeMetadata.from_timestamps(created_at=now, updated_at=now),
    )

    with pytest.raises(ValidationFailure):
        service.update_tree(
            "missing-tree",
            payload,
            owner_id="owner-required-revision",
            idempotency_key="required-revision",
            normalized_route="/api/crt/trees",
        )


def test_pending_resource_guard_blocks_a_second_update(container):
    service = container.crt_command_service
    owner_id = "owner-pending-guard"
    tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Pending guard"), owner_id=owner_id
    )
    now = utcnow()
    from app.repositories.crt_command import CrtCommandReceipt

    service.command_repo.insert_pending(
        CrtCommandReceipt(
            owner_id=owner_id,
            key_digest="a" * 64,
            command="update",
            normalized_route=f"/api/crt/trees:{tree.id}",
            request_hash="pending-request",
            state="pending",
            resource_id=tree.id,
            base_revision=tree.revision,
            target_revision=tree.revision + 1,
            response_status=None,
            response_json=None,
            created_at=now,
            committed_at=None,
            expires_at=now + timedelta(days=30),
            pending_target_snapshot=None,
        )
    )
    response = service.tree_service.to_response(tree)
    payload = TreeUpdateRequest(
        name=response.name,
        expected_revision=response.revision,
        schema_version=response.schema_version,
        metadata=response.metadata,
        nodes=response.nodes,
        relations=response.relations,
        owner_id=response.owner_id,
    )

    with pytest.raises(PendingCommandError):
        service.update_tree(
            tree.id,
            payload,
            owner_id=owner_id,
            idempotency_key="second-update",
            normalized_route="/api/crt/trees",
        )

    assert service.tree_service.get_tree(tree.id) == tree


def test_replay_reconciles_tree_written_before_create_commit(container, monkeypatch):
    service = container.crt_command_service
    owner_id = "owner-create-commit-crash"
    key = "create-commit-crash"
    payload = TreeCreateRequest(name="Create commit crash")
    original_commit = service.command_repo.commit

    def crash_commit(**kwargs):
        raise RuntimeError("crash after tree write")

    monkeypatch.setattr(service.command_repo, "commit", crash_commit)
    with pytest.raises(RuntimeError, match="crash after tree write"):
        service.create_tree(
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )
    monkeypatch.setattr(service.command_repo, "commit", original_commit)

    replay = service.create_tree(
        payload,
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )
    assert replay.replayed is True
    assert replay.response is not None
    assert replay.response.name == "Create commit crash"


def test_replay_reconciles_existing_update_receipt(container):
    service = container.crt_command_service
    owner_id = "owner-update-replay"
    tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Before replay"), owner_id=owner_id
    )
    current = service.tree_service.to_response(tree)
    payload = TreeUpdateRequest(
        name="After replay",
        expected_revision=current.revision,
        schema_version=current.schema_version,
        metadata=current.metadata,
        nodes=current.nodes,
        relations=current.relations,
        owner_id=current.owner_id,
    )
    key = "update-replay"
    first = service.update_tree(
        tree.id,
        payload,
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )
    replay = service.update_tree(
        tree.id,
        payload,
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )

    assert first.status_code == 200
    assert replay.replayed is True
    assert replay.response == first.response


@pytest.mark.parametrize("kind", ["conflict", "expired"])
def test_delete_replay_guard_matrix(container, kind):
    service = container.crt_command_service
    owner_id = f"owner-delete-replay-{kind}"
    tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Delete replay"), owner_id=owner_id
    )
    key = f"delete-replay-{kind}"
    service.delete_tree(
        tree.id,
        expected_revision=tree.revision,
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )
    if kind == "expired":
        with sqlite3.connect(service.command_repo.db_path) as connection:
            connection.execute(
                "UPDATE crt_command_receipts SET expires_at = ? WHERE owner_id = ?",
                ((utcnow() - timedelta(days=31)).isoformat(), owner_id),
            )
        with pytest.raises(IdempotencyReceiptExpiredError):
            service.delete_tree(
                tree.id,
                expected_revision=tree.revision,
                owner_id=owner_id,
                idempotency_key=key,
                normalized_route="/api/crt/trees",
            )
    else:
        with pytest.raises(IdempotencyConflictError):
            service.delete_tree(
                tree.id,
                expected_revision=tree.revision + 1,
                owner_id=owner_id,
                idempotency_key=key,
                normalized_route="/api/crt/trees",
            )


def test_pending_create_with_diverged_marker_stays_pending(container, monkeypatch):
    service = container.crt_command_service
    owner_id = "owner-create-marker-diverged"
    key = "create-marker-diverged"
    payload = TreeCreateRequest(name="Marker diverged")
    original_commit = service.command_repo.commit

    def crash_commit(**kwargs):
        raise RuntimeError("crash after tree write")

    monkeypatch.setattr(service.command_repo, "commit", crash_commit)
    with pytest.raises(RuntimeError):
        service.create_tree(
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )
    monkeypatch.setattr(service.command_repo, "commit", original_commit)
    tree_id = service._resource_id(owner_id, service._key_digest(key))
    service.tree_service.tree_repo.mutate(
        tree_id,
        update=lambda current: current.model_copy(update={"last_command_id": "a" * 64}),
    )

    with pytest.raises(ConflictError):
        service.create_tree(
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )


@pytest.mark.parametrize("kind", ["empty_name"])
def test_create_owner_payload_validation_is_fail_closed(container, kind):
    service = container.crt_command_service
    key = f"create-owner-payload-{kind}"
    with pytest.raises(ValidationFailure):
        service.create_tree(
            TreeCreateRequest(name="   "),
            owner_id="owner-empty-name",
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )
    assert (
        service.command_repo.get(
            owner_id="owner-empty-name", key_digest=service._key_digest(key)
        )
        is None
    )


@pytest.mark.parametrize("kind", ["schema_mismatch", "unsupported_schema"])
def test_update_schema_matrix_rejects_before_receipt_or_tree_write(container, kind):
    service = container.crt_command_service
    now = utcnow()
    metadata = TreeMetadata.from_timestamps(created_at=now, updated_at=now)
    if kind == "schema_mismatch":
        metadata = metadata.model_copy(update={"version": 2})
        schema_version = 1
    else:
        schema_version = 2
        metadata = metadata.model_copy(update={"version": 2})
    payload = TreeUpdateRequest(
        name="Invalid update schema",
        expected_revision=1,
        schema_version=schema_version,
        metadata=metadata,
    )

    with pytest.raises(ValidationFailure):
        service.update_tree(
            "missing-tree",
            payload,
            owner_id="owner-update-schema",
            idempotency_key=f"update-schema-{kind}",
            normalized_route="/api/crt/trees",
        )


def _import_variant(  # noqa: PLR0911
    source: TreeDetailResponse, variant: str
) -> TreeDetailResponse:
    if variant == "schema_mismatch":
        return source.model_copy(
            update={"metadata": source.metadata.model_copy(update={"version": 2})}
        )
    if variant == "unsupported_schema":
        return source.model_copy(update={"schema_version": 2})
    if variant == "empty_name":
        return source.model_copy(update={"name": "   "})
    if variant == "duplicate_node":
        return source.model_copy(update={"nodes": [source.nodes[0], source.nodes[0]]})
    if variant == "empty_label":
        return source.model_copy(
            update={"nodes": [source.nodes[0].model_copy(update={"label": "   "})]}
        )
    if variant == "duplicate_relation":
        return source.model_copy(
            update={"relations": [source.relations[0], source.relations[0]]}
        )
    if variant == "missing_endpoint":
        relation = source.relations[0].model_copy(update={"target_node_id": "missing"})
        return source.model_copy(update={"relations": [relation]})
    if variant == "duplicate_pair":
        duplicate = source.relations[0].model_copy(update={"id": "relation-other"})
        return source.model_copy(update={"relations": [source.relations[0], duplicate]})
    if variant == "cycle":
        reverse = source.relations[0].model_copy(
            update={
                "id": "relation-other",
                "source_node_id": "graph-b",
                "target_node_id": "graph-a",
            }
        )
        return source.model_copy(update={"relations": [source.relations[0], reverse]})
    raise AssertionError(variant)


@pytest.mark.parametrize(
    "variant",
    [
        "schema_mismatch",
        "unsupported_schema",
        "empty_name",
        "duplicate_node",
        "empty_label",
        "duplicate_relation",
        "missing_endpoint",
        "duplicate_pair",
        "cycle",
    ],
)
def test_import_validation_matrix_rejects_before_pending_receipt(container, variant):
    service = container.crt_command_service
    source = service.tree_service.create_tree(
        _graph_create_payload(), owner_id="owner-import-source", tree_id="import-source"
    )
    mutated = _import_variant(service.tree_service.to_response(source), variant)
    key = f"import-validation-{variant}"

    with pytest.raises(ValidationFailure):
        service.import_tree(
            TreeImportRequest(tree=mutated),
            owner_id="owner-import-target",
            idempotency_key=key,
            normalized_route="/api/crt/trees/import",
        )

    assert (
        service.command_repo.get(
            owner_id="owner-import-target", key_digest=service._key_digest(key)
        )
        is None
    )
    assert service.tree_service.get_tree(source.id) == source


@pytest.mark.parametrize(
    "kind",
    ["missing_body", "missing_status", "malformed_body"],
)
def test_committed_receipt_replay_fails_closed_for_unusable_response(container, kind):
    service = container.crt_command_service
    owner_id = f"owner-replay-{kind}"
    key = f"replay-{kind}"
    payload = TreeCreateRequest(name="Replay guard")
    service.create_tree(
        payload,
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )
    with sqlite3.connect(service.command_repo.db_path) as connection:
        if kind == "missing_body":
            connection.execute(
                "UPDATE crt_command_receipts SET response_json = NULL "
                "WHERE owner_id = ?",
                (owner_id,),
            )
        elif kind == "missing_status":
            connection.execute(
                "UPDATE crt_command_receipts SET response_status = NULL "
                "WHERE owner_id = ?",
                (owner_id,),
            )
        else:
            connection.execute(
                "UPDATE crt_command_receipts SET response_json = ? "
                "WHERE owner_id = ?",
                ("not-json", owner_id),
            )

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service.create_tree(
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )


def test_reused_key_with_different_payload_is_an_idempotency_conflict(container):
    service = container.crt_command_service
    service.create_tree(
        TreeCreateRequest(name="First request"),
        owner_id="owner-conflict",
        idempotency_key="same-key",
        normalized_route="/api/crt/trees",
    )

    with pytest.raises(IdempotencyConflictError):
        service.create_tree(
            TreeCreateRequest(name="Different request"),
            owner_id="owner-conflict",
            idempotency_key="same-key",
            normalized_route="/api/crt/trees",
        )


def test_expired_committed_receipt_requires_explicit_reconciliation(container):
    service = container.crt_command_service
    owner_id = "owner-expired-replay"
    key = "expired-replay"
    service.create_tree(
        TreeCreateRequest(name="Expired replay"),
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )
    expired = (utcnow() - timedelta(days=31)).isoformat()
    with sqlite3.connect(service.command_repo.db_path) as connection:
        connection.execute(
            "UPDATE crt_command_receipts SET expires_at = ? WHERE owner_id = ?",
            (expired, owner_id),
        )

    with pytest.raises(IdempotencyReceiptExpiredError):
        service.create_tree(
            TreeCreateRequest(name="Expired replay"),
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )


def test_delete_replay_rejects_malformed_committed_tombstone(container):
    service = container.crt_command_service
    owner_id = "owner-delete-replay-guard"
    tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Delete replay guard"), owner_id=owner_id
    )
    key = "delete-replay-guard"
    service.delete_tree(
        tree.id,
        expected_revision=tree.revision,
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )
    with sqlite3.connect(service.command_repo.db_path) as connection:
        connection.execute(
            "UPDATE crt_command_receipts SET response_status = 200 "
            "WHERE owner_id = ?",
            (owner_id,),
        )

    with pytest.raises(ConflictError):
        service.delete_tree(
            tree.id,
            expected_revision=tree.revision,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("response_status", 200), ("resource_id", "other-tree"), ("target_revision", 2)],
)
def test_committed_create_replay_rejects_mismatched_receipt_guards(
    container, field, value
):
    service = container.crt_command_service
    owner_id = f"owner-replay-guard-{field}"
    key = f"replay-guard-{field}"
    payload = TreeCreateRequest(name="Replay guard")
    service.create_tree(
        payload,
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )
    with sqlite3.connect(service.command_repo.db_path) as connection:
        connection.execute(
            f"UPDATE crt_command_receipts SET {field} = ? "
            "WHERE owner_id = ? AND key_digest = ?",
            (value, owner_id, service._key_digest(key)),
        )

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service.create_tree(
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("resource_id", "other-tree"), ("base_revision", 2), ("target_revision", 1)],
)
def test_committed_delete_replay_rejects_mismatched_receipt_guards(
    container, field, value
):
    service = container.crt_command_service
    owner_id = f"owner-delete-guard-{field}"
    tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Delete guard"), owner_id=owner_id
    )
    key = f"delete-guard-{field}"
    service.delete_tree(
        tree.id,
        expected_revision=tree.revision,
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )
    with sqlite3.connect(service.command_repo.db_path) as connection:
        connection.execute(
            f"UPDATE crt_command_receipts SET {field} = ? "
            "WHERE owner_id = ? AND key_digest = ?",
            (value, owner_id, service._key_digest(key)),
        )

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service.delete_tree(
            tree.id,
            expected_revision=tree.revision,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )


def test_committed_create_replay_rejects_mismatched_receipt_owner(
    container, monkeypatch
):
    service = container.crt_command_service
    owner_id = "owner-replay-owner-guard"
    key = "replay-owner-guard"
    payload = TreeCreateRequest(name="Replay owner guard")
    service.create_tree(
        payload,
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )
    original_get = service.command_repo.get
    receipt = original_get(owner_id=owner_id, key_digest=service._key_digest(key))
    assert receipt is not None
    monkeypatch.setattr(
        service.command_repo,
        "get",
        lambda **kwargs: (
            replace(receipt, owner_id="other-owner")
            if kwargs["owner_id"] == owner_id
            else original_get(**kwargs)
        ),
    )
    with pytest.raises(IdempotencyReceiptUnavailableError):
        service.create_tree(
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("id", "tree_foreign"), ("owner_id", "owner-foreign"), ("revision", 2)],
)
def test_committed_create_replay_rejects_mismatched_response_identity(
    container, field, value
):
    service = container.crt_command_service
    owner_id = f"owner-replay-response-{field}"
    key = f"replay-response-{field}"
    payload = TreeCreateRequest(name="Replay response guard")
    service.create_tree(
        payload,
        owner_id=owner_id,
        idempotency_key=key,
        normalized_route="/api/crt/trees",
    )
    with sqlite3.connect(service.command_repo.db_path) as connection:
        raw = connection.execute(
            "SELECT response_json FROM crt_command_receipts "
            "WHERE owner_id = ? AND key_digest = ?",
            (owner_id, service._key_digest(key)),
        ).fetchone()[0]
        response = json.loads(raw)
        response[field] = value
        connection.execute(
            "UPDATE crt_command_receipts SET response_json = ? "
            "WHERE owner_id = ? AND key_digest = ?",
            (json.dumps(response), owner_id, service._key_digest(key)),
        )

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service.create_tree(
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )


@pytest.mark.parametrize("duplicate_kind", ["node", "relation"])
def test_crt_create_rejects_duplicate_ids_before_pending_receipt(
    container, duplicate_kind
):
    service = container.crt_command_service
    owner_id = f"owner-duplicate-create-{duplicate_kind}"
    key = f"duplicate-create-{duplicate_kind}"
    payload = _graph_create_payload(name="Duplicate create")
    if duplicate_kind == "node":
        payload = payload.model_copy(
            update={"nodes": [payload.nodes[0], payload.nodes[0]], "relations": []}
        )
        expected_reason = "duplicate_node_id"
    else:
        third = payload.nodes[1].model_copy(update={"id": "graph-c"})
        second_relation = payload.relations[0].model_copy(
            update={"source_node_id": "graph-b", "target_node_id": "graph-c"}
        )
        payload = payload.model_copy(
            update={
                "nodes": [*payload.nodes, third],
                "relations": [payload.relations[0], second_relation],
            }
        )
        expected_reason = "duplicate_relation_id"

    with pytest.raises(ValidationFailure) as exc_info:
        service.create_tree(
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )

    assert exc_info.value.detail is not None
    assert exc_info.value.detail["reason"] == expected_reason
    assert (
        service.command_repo.get(owner_id=owner_id, key_digest=service._key_digest(key))
        is None
    )
    assert not service.tree_service.tree_repo.exists(
        service._resource_id(owner_id, service._key_digest(key))
    )


@pytest.mark.parametrize("duplicate_kind", ["node", "relation"])
def test_crt_update_rejects_duplicate_ids_before_pending_receipt_or_write(
    container, duplicate_kind
):
    service = container.crt_command_service
    owner_id = f"owner-duplicate-update-{duplicate_kind}"
    tree = service.tree_service.create_tree(
        _graph_create_payload(name="Duplicate update"), owner_id=owner_id
    )
    response = service.tree_service.to_response(tree)
    payload = TreeUpdateRequest(
        name=response.name,
        schema_version=response.schema_version,
        metadata=response.metadata,
        nodes=response.nodes,
        relations=response.relations,
        owner_id=response.owner_id,
        expected_revision=response.revision,
    )
    key = f"duplicate-update-{duplicate_kind}"
    if duplicate_kind == "node":
        payload = payload.model_copy(
            update={"nodes": [payload.nodes[0], payload.nodes[0]], "relations": []}
        )
        expected_reason = "duplicate_node_id"
    else:
        third = payload.nodes[1].model_copy(update={"id": "graph-c"})
        second_relation = payload.relations[0].model_copy(
            update={"source_node_id": "graph-b", "target_node_id": "graph-c"}
        )
        payload = payload.model_copy(
            update={
                "nodes": [*payload.nodes, third],
                "relations": [payload.relations[0], second_relation],
            }
        )
        expected_reason = "duplicate_relation_id"

    with pytest.raises(ValidationFailure) as exc_info:
        service.update_tree(
            tree.id,
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )

    assert exc_info.value.detail is not None
    assert exc_info.value.detail["reason"] == expected_reason
    assert (
        service.command_repo.get(owner_id=owner_id, key_digest=service._key_digest(key))
        is None
    )
    assert service.tree_service.get_tree(tree.id) == tree


def test_pending_delete_wrong_owner_fails_closed_without_removing_foreign_index(
    container,
):
    service = container.crt_command_service
    foreign_owner = "owner-foreign-delete"
    pending_owner = "owner-pending-delete"
    foreign_tree = service.tree_service.create_tree(
        TreeCreateRequest(name="Foreign tree"), owner_id=foreign_owner
    )
    key = "pending-delete-foreign"
    now = utcnow()
    service.command_repo.insert_pending(
        CrtCommandReceipt(
            owner_id=pending_owner,
            key_digest=service._key_digest(key),
            command="delete",
            normalized_route=f"/api/crt/trees:{foreign_tree.id}",
            request_hash=service._request_hash(
                {"tree_id": foreign_tree.id, "expected_revision": foreign_tree.revision}
            ),
            state="pending",
            resource_id=foreign_tree.id,
            base_revision=foreign_tree.revision,
            target_revision=None,
            response_status=None,
            response_json=None,
            created_at=now,
            committed_at=None,
            expires_at=now + timedelta(days=30),
        )
    )

    assert service.reconcile_pending_commands() == 0
    still_pending = service.command_repo.get(
        owner_id=pending_owner, key_digest=service._key_digest(key)
    )
    assert still_pending is not None
    assert still_pending.state == "pending"
    assert service.tree_service.get_tree(foreign_tree.id) == foreign_tree
    assert [
        entry.id for entry in service.tree_service.list_trees(owner_id=foreign_owner)
    ] == [foreign_tree.id]


def test_pending_create_rejects_corrupt_resource_before_reconciliation(container):
    service = container.crt_command_service
    owner_id = "owner-pending-create-resource"
    key = "pending-create-resource"
    key_digest = service._key_digest(key)
    payload = TreeCreateRequest(name="Requested create")
    victim = service.tree_service.create_tree(
        TreeCreateRequest(name="Create victim"),
        owner_id=owner_id,
        tree_id="tree-create-victim",
        command_id=key_digest,
    )
    command_payload = service._owner_safe_payload(payload)
    service.command_repo.insert_pending(
        CrtCommandReceipt(
            owner_id=owner_id,
            key_digest=key_digest,
            command="create",
            normalized_route="/api/crt/trees",
            request_hash=service._request_hash(command_payload),
            state="pending",
            resource_id=victim.id,
            base_revision=None,
            target_revision=1,
            response_status=None,
            response_json=None,
            created_at=utcnow(),
            committed_at=None,
            expires_at=utcnow() + timedelta(days=30),
            pending_target_snapshot=service._encode_target_snapshot(victim),
        )
    )

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service.create_tree(
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )

    assert service.tree_service.get_tree(victim.id) == victim


def test_pending_update_rejects_corrupt_resource_before_reconciliation(container):
    service = container.crt_command_service
    owner_id = "owner-pending-update-resource"
    requested = service.tree_service.create_tree(
        TreeCreateRequest(name="Requested update"),
        owner_id=owner_id,
        tree_id="tree-update-requested",
    )
    victim = service.tree_service.create_tree(
        TreeCreateRequest(name="Update victim"),
        owner_id=owner_id,
        tree_id="tree-update-victim",
    )
    response = service.tree_service.to_response(requested)
    payload = TreeUpdateRequest(
        name=response.name,
        schema_version=response.schema_version,
        metadata=response.metadata,
        nodes=response.nodes,
        relations=response.relations,
        owner_id=response.owner_id,
        expected_revision=response.revision,
    )
    key = "pending-update-resource"
    key_digest = service._key_digest(key)
    target = victim.model_copy(
        update={
            "description": "Corrupted pending update",
            "revision": victim.revision + 1,
            "last_command_id": key_digest,
        },
        deep=True,
    )
    command_payload = service._owner_safe_payload(payload)
    service.command_repo.insert_pending(
        CrtCommandReceipt(
            owner_id=owner_id,
            key_digest=key_digest,
            command="update",
            normalized_route=f"/api/crt/trees:{requested.id}",
            request_hash=service._request_hash(command_payload),
            state="pending",
            resource_id=victim.id,
            base_revision=victim.revision,
            target_revision=victim.revision + 1,
            response_status=None,
            response_json=None,
            created_at=utcnow(),
            committed_at=None,
            expires_at=utcnow() + timedelta(days=30),
            pending_target_snapshot=service._encode_target_snapshot(target),
        )
    )

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service.update_tree(
            requested.id,
            payload,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )

    assert service.tree_service.get_tree(victim.id) == victim


def test_pending_delete_rejects_corrupt_resource_before_reconciliation(container):
    service = container.crt_command_service
    owner_id = "owner-pending-delete-resource"
    requested = service.tree_service.create_tree(
        TreeCreateRequest(name="Requested delete"),
        owner_id=owner_id,
        tree_id="tree-delete-requested",
    )
    victim = service.tree_service.create_tree(
        TreeCreateRequest(name="Delete victim"),
        owner_id=owner_id,
        tree_id="tree-delete-victim",
    )
    key = "pending-delete-resource"
    key_digest = service._key_digest(key)
    service.command_repo.insert_pending(
        CrtCommandReceipt(
            owner_id=owner_id,
            key_digest=key_digest,
            command="delete",
            normalized_route=f"/api/crt/trees:{requested.id}",
            request_hash=service._request_hash(
                {"tree_id": requested.id, "expected_revision": requested.revision}
            ),
            state="pending",
            resource_id=victim.id,
            base_revision=victim.revision,
            target_revision=None,
            response_status=None,
            response_json=None,
            created_at=utcnow(),
            committed_at=None,
            expires_at=utcnow() + timedelta(days=30),
            pending_target_snapshot=None,
        )
    )

    with pytest.raises(IdempotencyReceiptUnavailableError):
        service.delete_tree(
            requested.id,
            expected_revision=requested.revision,
            owner_id=owner_id,
            idempotency_key=key,
            normalized_route="/api/crt/trees",
        )

    assert service.tree_service.get_tree(victim.id) == victim
