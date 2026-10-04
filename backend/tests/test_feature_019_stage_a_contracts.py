"""Stage A revision/schema contract regressions for feature 019."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime

from app.schemas import (
    NodeCreateRequest,
    NodeUpdateRequest,
    Position,
    RelationCreateRequest,
    TreeCreateRequest,
    TreeUpdateRequest,
    ValidationRequest,
    VersionCreateRequest,
)


def test_legacy_repository_mutation_clears_internal_command_marker(
    tree_service,
) -> None:
    """A legacy aggregate write must not preserve a Stage B command marker."""

    tree = tree_service.create_tree(
        payload=TreeCreateRequest(name="marker"),
        owner_id="owner",
    )
    marked = tree.model_copy(update={"last_command_id": "a" * 64})
    tree_service.tree_repo.save(marked)

    updated = tree_service.tree_repo.mutate(
        tree.id,
        update=lambda current: current.model_copy(
            update={"description": "legacy write"},
            deep=True,
        ),
    )

    assert updated.revision == marked.revision + 1
    assert updated.last_command_id is None
    persisted = tree_service.tree_repo.load(tree.id)
    assert persisted.last_command_id is None
    assert persisted.revision == marked.revision + 1


def test_version_mutation_does_not_snapshot_a_stale_command_marker(
    tree_service,
    node_service,
    version_service,
) -> None:
    """Version snapshots are public legacy data, not command receipts."""

    tree = tree_service.create_tree(TreeCreateRequest(name="version"), owner_id="owner")
    node_service.create_node(
        tree.id,
        NodeCreateRequest(label="node", type="child", position=Position(x=0, y=0)),
    )
    marked = tree_service.get_tree(tree.id).model_copy(
        update={"last_command_id": "b" * 64}
    )
    tree_service.tree_repo.save(marked)
    tree_service._cache.clear()

    version_service.create_version(tree.id, VersionCreateRequest())

    version = version_service.version_repo.list_for_tree(tree.id)[0]
    assert version.tree.last_command_id is None
    assert tree_service.get_tree(tree.id).last_command_id is None


def _mark_for_legacy_write(tree_service, tree_id: str):
    current = tree_service.get_tree(tree_id)
    marked = current.model_copy(update={"last_command_id": "c" * 64})
    tree_service.tree_repo.save(marked)
    tree_service._cache.clear()
    return marked


def test_all_legacy_service_mutations_advance_once_and_clear_markers(
    tree_service,
    node_service,
    relation_service,
    validation_service,
    version_service,
) -> None:
    """Node, relation, validation, version and full-tree writes share the rule."""

    tree = tree_service.create_tree(
        TreeCreateRequest(name="all paths"), owner_id="owner"
    )

    marked = _mark_for_legacy_write(tree_service, tree.id)
    node, node_tree = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    assert node_tree.revision == marked.revision + 1
    assert node_tree.last_command_id is None

    marked = _mark_for_legacy_write(tree_service, tree.id)
    _, node_tree = node_service.update_node(
        tree.id,
        node.id,
        NodeUpdateRequest(label="A updated"),
    )
    assert node_tree.revision == marked.revision + 1
    assert node_tree.last_command_id is None

    other, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    marked = _mark_for_legacy_write(tree_service, tree.id)
    _, relation_tree = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node.id,
            target_node_id=other.id,
        ),
    )
    assert relation_tree.revision == marked.revision + 1
    assert relation_tree.last_command_id is None

    marked = _mark_for_legacy_write(tree_service, tree.id)
    validation_service.trigger_validation(tree.id, node.id, ValidationRequest())
    validated = tree_service.get_tree(tree.id)
    assert validated.revision == marked.revision + 1
    assert validated.last_command_id is None

    marked = _mark_for_legacy_write(tree_service, tree.id)
    version_service.create_version(tree.id, VersionCreateRequest(label="snapshot"))
    versioned = tree_service.get_tree(tree.id)
    assert versioned.revision == marked.revision + 1
    assert versioned.last_command_id is None

    marked = _mark_for_legacy_write(tree_service, tree.id)
    current = tree_service.get_tree(tree.id)
    response = tree_service.to_response(current)
    full_update = TreeUpdateRequest(
        name="renamed",
        expected_revision=marked.revision,
        schema_version=response.schema_version,
        metadata=response.metadata,
        nodes=response.nodes,
        relations=response.relations,
        owner_id=response.owner_id,
    )
    replaced = tree_service.update_tree(tree.id, full_update, owner_id="owner")
    assert replaced.revision == marked.revision + 1
    assert replaced.last_command_id is None


def test_tree_and_account_exports_project_out_internal_command_markers(
    api_client,
) -> None:
    """Every public tree projection retains revision/schema but omits markers."""

    created = api_client.post("/api/trees", json={"name": "export markers"})
    assert created.status_code == 201, created.text
    tree_id = created.json()["id"]
    container = api_client.app.state.container
    version = container.version_service.create_version(
        tree_id, VersionCreateRequest(label="public snapshot")
    )
    marked = container.tree_service.get_tree(tree_id).model_copy(
        update={"last_command_id": "d" * 64}
    )
    container.tree_repo.save(marked)
    container.tree_service._cache.clear()
    marked_version = version.model_copy(update={"tree": marked}, deep=True)
    container.version_repo.save(tree_id, marked_version)

    tree_export = api_client.post(f"/api/trees/{tree_id}/export")
    assert tree_export.status_code == 200, tree_export.text
    public_tree = tree_export.json()["tree"]
    assert public_tree["revision"] == marked.revision
    assert public_tree["schema_version"] == marked.schema_version
    assert "last_command_id" not in json.dumps(public_tree)

    account_export = api_client.get("/api/account/export")
    assert account_export.status_code == 200, account_export.text
    with zipfile.ZipFile(io.BytesIO(account_export.content)) as archive:
        exported_tree = json.loads(archive.read(f"trees/{tree_id}/tree.json"))
        version_files = [
            name
            for name in archive.namelist()
            if name.startswith(f"trees/{tree_id}/versions/")
        ]
        assert version_files
        exported_version = json.loads(archive.read(version_files[0]))

    assert exported_tree["revision"] == marked.revision
    assert exported_tree["schema_version"] == marked.schema_version
    assert "last_command_id" not in json.dumps(exported_tree)
    assert exported_version["tree"]["revision"] == marked.revision
    assert exported_version["tree"]["schema_version"] == marked.schema_version
    assert "last_command_id" not in json.dumps(exported_version)


def _minimal_import(*, schema_version: int, metadata_version: int) -> dict[str, object]:
    now = datetime(2026, 1, 1, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return {
        "id": "uploaded-tree",
        "schema_version": schema_version,
        "name": "uploaded",
        "metadata": {
            "version": metadata_version,
            "created_at": now,
            "updated_at": now,
            "layout": None,
            "owner_id": None,
        },
        "nodes": [],
        "relations": [],
        "owner_id": None,
    }


def test_import_rejects_unsupported_schema_without_mutating(api_client) -> None:
    before = api_client.get("/api/trees").json()
    response = api_client.post(
        "/api/trees/import",
        json={"tree": _minimal_import(schema_version=99, metadata_version=99)},
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "reason": "unsupported_schema_version",
        "schema_version": 99,
    }
    assert api_client.get("/api/trees").json() == before


def test_import_rejects_schema_metadata_disagreement_without_mutating(
    api_client,
) -> None:
    before = api_client.get("/api/trees").json()
    response = api_client.post(
        "/api/trees/import",
        json={"tree": _minimal_import(schema_version=1, metadata_version=2)},
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "reason": "schema_version_mismatch",
        "schema_version": 1,
        "metadata_version": 2,
    }
    assert api_client.get("/api/trees").json() == before


def test_import_preserves_accepted_schema_version(api_client) -> None:
    response = api_client.post(
        "/api/trees/import",
        json={"tree": _minimal_import(schema_version=1, metadata_version=1)},
    )

    assert response.status_code == 201, response.text
    imported = response.json()
    assert imported["schema_version"] == 1
    assert imported["metadata"]["version"] == 1


def test_stale_revision_error_exposes_current_state_and_correlation(api_client) -> None:
    created_response = api_client.post("/api/trees", json={"name": "stale"})
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    update_payload = {
        "name": "newer",
        "expected_revision": created["revision"],
        "schema_version": created["schema_version"],
        "metadata": created["metadata"],
        "nodes": created["nodes"],
        "relations": created["relations"],
        "owner_id": created["owner_id"],
    }
    updated_response = api_client.put(
        f"/api/trees/{created['id']}", json=update_payload
    )
    assert updated_response.status_code == 200, updated_response.text
    updated = updated_response.json()

    stale_response = api_client.put(
        f"/api/trees/{created['id']}",
        json={**update_payload, "name": "stale writer"},
    )

    assert stale_response.status_code == 409, stale_response.text
    body = stale_response.json()
    assert body["detail"] == {
        "reason": "stale_revision",
        "tree_id": created["id"],
        "current_revision": updated["revision"],
        "current_updated_at": updated["metadata"]["updated_at"],
    }
    assert body["reference_id"] == stale_response.headers["X-Correlation-ID"]


def test_stale_revision_details_are_not_disclosed_to_wrong_owner(
    second_api_client,
) -> None:
    owner_a, owner_b = second_api_client
    created_response = owner_a.post("/api/trees", json={"name": "private stale"})
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()

    response = owner_b.put(
        f"/api/trees/{created['id']}",
        json={
            "name": "wrong owner",
            "expected_revision": 1,
            "schema_version": created["schema_version"],
            "metadata": created["metadata"],
            "nodes": created["nodes"],
            "relations": created["relations"],
            "owner_id": created["owner_id"],
        },
    )

    assert response.status_code == 404, response.text
    assert "current_revision" not in response.text
    assert "current_updated_at" not in response.text
