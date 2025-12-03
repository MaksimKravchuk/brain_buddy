from __future__ import annotations

import pytest

from app.exceptions import ValidationFailure
from app.schemas import (
    NodeCreateRequest,
    NodeUpdateRequest,
    Position,
    RelationCreateRequest,
    TreeCreateRequest,
)


def test_create_and_update_node(tree_service, node_service) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="Nodes"))

    node_payload = NodeCreateRequest(
        label="Root", type="regular", position=Position(x=0, y=0)
    )
    node, tree_after_create = node_service.create_node(tree.id, node_payload)

    assert node.label == "Root"
    assert len(tree_after_create.nodes) == 1

    updated_label = "Updated Root"
    updated_node, tree_after_update = node_service.update_node(
        tree.id, node.id, NodeUpdateRequest(label=updated_label)
    )
    assert updated_node.label == updated_label
    assert tree_after_update.nodes[0].label == updated_label


def test_delete_node_requires_cascade(
    tree_service, node_service, relation_service
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="Cascade"))
    node_a, tree = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="regular", position=Position(x=0, y=0)),
    )
    node_b, tree = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="regular", position=Position(x=10, y=10)),
    )

    relation_service.create_relation(
        tree.id,
        RelationCreateRequest(from_id=node_a.id, to_id=node_b.id, kind="why"),
    )

    with pytest.raises(ValidationFailure):
        node_service.delete_node(tree.id, node_a.id)

    updated_tree = node_service.delete_node(tree.id, node_a.id, cascade=True)
    assert all(node.id != node_a.id for node in updated_tree.nodes)
