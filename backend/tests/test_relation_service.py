from __future__ import annotations

import pytest

from app.exceptions import ConflictError, NotFoundError
from app.schemas import (
    NodeCreateRequest,
    Position,
    RelationCreateRequest,
    RelationUpdateRequest,
    TreeCreateRequest,
)


def prepare_tree_with_nodes(tree_service, node_service):
    tree = tree_service.create_tree(TreeCreateRequest(title="Relations", description=None))
    node_a, tree = node_service.create_node(tree.id, NodeCreateRequest(label="A", position=Position(x=0, y=0)))
    node_b, tree = node_service.create_node(tree.id, NodeCreateRequest(label="B", position=Position(x=1, y=1)))
    node_c, tree = node_service.create_node(tree.id, NodeCreateRequest(label="C", position=Position(x=2, y=2)))
    return tree, node_a, node_b, node_c


def test_create_and_update_relation(tree_service, node_service, relation_service) -> None:
    tree, node_a, node_b, node_c = prepare_tree_with_nodes(tree_service, node_service)

    relation, _ = relation_service.create_relation(
        tree.id, RelationCreateRequest(source_id=node_a.id, target_id=node_b.id, question_label="WHY?", notes=None)
    )
    assert relation.source_id == node_a.id
    assert relation.target_id == node_b.id

    updated_relation, _ = relation_service.update_relation(
        tree.id,
        relation.id,
        RelationUpdateRequest(target_id=node_c.id, question_label="HOW?"),
    )
    assert updated_relation.target_id == node_c.id
    assert updated_relation.question_label == "HOW?"


def test_create_relation_conflict(tree_service, node_service, relation_service) -> None:
    tree, node_a, node_b, _ = prepare_tree_with_nodes(tree_service, node_service)
    relation_service.create_relation(
        tree.id, RelationCreateRequest(source_id=node_a.id, target_id=node_b.id, question_label="WHY?", notes=None)
    )

    with pytest.raises(ConflictError):
        relation_service.create_relation(
            tree.id,
            RelationCreateRequest(source_id=node_a.id, target_id=node_b.id, question_label="WHY?", notes=None),
        )


def test_delete_relation(tree_service, node_service, relation_service) -> None:
    tree, node_a, node_b, _ = prepare_tree_with_nodes(tree_service, node_service)
    relation, tree_with_relation = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(source_id=node_a.id, target_id=node_b.id, question_label="WHY?", notes=None),
    )
    assert any(rel.id == relation.id for rel in tree_with_relation.relations)

    updated_tree = relation_service.delete_relation(tree.id, relation.id)
    assert all(rel.id != relation.id for rel in updated_tree.relations)

    with pytest.raises(NotFoundError):
        relation_service.delete_relation(tree.id, relation.id)
