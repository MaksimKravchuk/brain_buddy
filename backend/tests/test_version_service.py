from __future__ import annotations

import json

import pytest

from app.schemas import (
    NodeCreateRequest,
    NodeUpdateRequest,
    Position,
    RelationCreateRequest,
    TreeCreateRequest,
    VersionCreateRequest,
)
from app.utils.time import to_isoformat


def test_create_version_captures_metadata_and_diff(
    tree_service, node_service, version_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Versions"), owner_id="user_test"
    )
    node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )

    version = version_service.create_version(
        tree.id,
        VersionCreateRequest(label="Snapshot", author="Alex", notes="Baseline"),
    )

    assert version.label == "Snapshot"
    assert version.author == "Alex"
    assert version.diff.nodes_added == 1
    assert version.diff.nodes_removed == 0
    assert version.conflicts == []

    versions = version_service.list_versions(tree.id)
    assert versions[0].id == version.id
    assert versions[0].author == "Alex"
    assert versions[0].diff_summary is not None
    assert versions[0].diff_summary.nodes_added == 1
    assert versions[0].conflict_count == 0


def test_create_version_detects_conflicts(
    tree_service, node_service, version_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Conflicts"), owner_id="user_test"
    )
    node, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    version_service.create_version(tree.id, VersionCreateRequest(label="Initial"))

    node_service.update_node(
        tree.id,
        node.id,
        NodeUpdateRequest(label="Renamed", position=Position(x=10, y=20)),
    )

    version = version_service.create_version(
        tree.id, VersionCreateRequest(label="After change")
    )

    assert version.diff.nodes_modified == 1
    assert version.conflicts
    assert version.conflicts[0].entity_type == "node"
    assert version.conflicts[0].entity_id == node.id

    refs = version_service.list_versions(tree.id)
    assert refs[0].conflict_count == len(version.conflicts)


def test_restore_version(tree_service, node_service, version_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Restore"), owner_id="user_test"
    )
    node, tree = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )

    version = version_service.create_version(
        tree.id, VersionCreateRequest(label="Before deletion")
    )

    node_service.delete_node(tree.id, node.id, cascade=True)

    restored_tree = version_service.restore_version(tree.id, version.id)
    assert any(n.id == node.id for n in restored_tree.nodes)


def test_delete_version_keeps_snapshot_when_tree_persistence_fails(
    tree_service, version_service, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Deletion rollback"), owner_id="user_test"
    )
    version = version_service.create_version(
        tree.id, VersionCreateRequest(label="Preserve on failure")
    )

    def fail_tree_save(_tree) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(tree_service.tree_repo, "save", fail_tree_save)

    with pytest.raises(OSError, match="disk unavailable"):
        version_service.delete_version(tree.id, version.id)

    assert version_service.load_version(tree.id, version.id).id == version.id
    assert any(
        ref.id == version.id
        for ref in tree_service.tree_repo.load(tree.id).version_refs
    )


def test_export_tree_supports_live_and_version(
    tree_service, node_service, relation_service, version_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Export"), owner_id="user_test"
    )
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )
    version = version_service.create_version(
        tree.id, VersionCreateRequest(label="Snapshot")
    )

    live_filename, live_content = version_service.export_tree(tree.id)
    assert live_filename.endswith(".json")
    live_payload = json.loads(live_content.decode("utf-8"))
    assert live_payload["source"]["type"] == "live"
    assert live_payload["tree"]["id"] == tree.id
    assert live_payload["tree"]["relations"][0]["source_node_id"]
    assert live_payload["tree"]["relations"][0]["target_node_id"]

    version_filename, version_content = version_service.export_tree(tree.id, version.id)
    assert version_filename.endswith(".json")
    version_payload = json.loads(version_content.decode("utf-8"))
    assert version_payload["source"]["type"] == "version"
    assert version_payload["source"]["version_id"] == version.id
    assert version_payload["tree"]["id"] == tree.id
    assert version_payload["tree"]["relations"][0]["source_node_id"]
    assert version_payload["tree"]["relations"][0]["target_node_id"]


def test_version_lifecycle_restores_exact_snapshot_then_deletes_its_storage(
    tree_service, node_service, version_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Lifecycle"), owner_id="user_test"
    )
    node, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="Before", type="child", position=Position(x=1, y=2)),
    )
    baseline = version_service.create_version(
        tree.id,
        VersionCreateRequest(label="Baseline", author="Alex", notes="restore me"),
    )
    node_service.update_node(
        tree.id,
        node.id,
        NodeUpdateRequest(label="After", position=Position(x=9, y=9)),
    )
    later = version_service.create_version(tree.id, VersionCreateRequest(label="Later"))

    assert [ref.id for ref in version_service.list_versions(tree.id)] == [
        later.id,
        baseline.id,
    ]
    filename, content = version_service.export_tree(tree.id, baseline.id)
    exported = json.loads(content)
    assert filename.endswith(".json")
    assert exported["source"] == {
        "type": "version",
        "version_id": baseline.id,
        "label": "Baseline",
        "captured_at": to_isoformat(baseline.captured_at),
    }
    assert exported["tree"] == tree_service.to_response(baseline.tree).model_dump(
        mode="json", by_alias=True
    )

    restored = version_service.restore_version(tree.id, baseline.id)

    assert restored.nodes[0].label == "Before"
    assert restored.nodes[0].position == Position(x=1, y=2)
    assert [ref.id for ref in restored.version_refs].count(baseline.id) == 1
    version_service.delete_version(tree.id, baseline.id)
    assert [ref.id for ref in version_service.list_versions(tree.id)] == [later.id]
    assert not version_service.version_repo.version_path(tree.id, baseline.id).exists()
