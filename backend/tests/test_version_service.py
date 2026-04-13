from __future__ import annotations

import json

from app.schemas import (
    NodeCreateRequest,
    NodeUpdateRequest,
    Position,
    RelationCreateRequest,
    TreeCreateRequest,
    VersionCreateRequest,
)


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
