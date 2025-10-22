from __future__ import annotations

from app.schemas import NodeCreateRequest, Position, TreeCreateRequest, VersionCreateRequest


def test_create_and_list_versions(tree_service, node_service, version_service) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(title="Versions", description=None))
    node_service.create_node(tree.id, NodeCreateRequest(label="A", position=Position(x=0, y=0)))

    version = version_service.create_version(tree.id, VersionCreateRequest(label="Snapshot"))
    assert version.label == "Snapshot"

    versions = version_service.list_versions(tree.id)
    assert versions[0].id == version.id


def test_restore_version(tree_service, node_service, version_service) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(title="Restore", description=None))
    node, tree = node_service.create_node(tree.id, NodeCreateRequest(label="A", position=Position(x=0, y=0)))

    version = version_service.create_version(tree.id, VersionCreateRequest(label="Before deletion"))

    node_service.delete_node(tree.id, node.id, cascade=True)

    restored_tree = version_service.restore_version(tree.id, version.id)
    assert any(n.id == node.id for n in restored_tree.nodes)
