from __future__ import annotations

from app.schemas import (
    NodeCreateRequest,
    Position,
    RelationCreateRequest,
    TreeCreateRequest,
    ValidationRequest,
)


def test_validation_flow(
    container, tree_service, node_service, relation_service, validation_service
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="Validation"))

    effect_node, tree = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="Effect", type="effect", position=Position(x=0, y=0)),
    )
    cause_node, tree = node_service.create_node(
        tree.id,
        NodeCreateRequest(
            label="Cause", type="cause", position=Position(x=100, y=100)
        ),
    )

    relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            from_id=cause_node.id,
            to_id=effect_node.id,
            kind="why",
        ),
    )

    response = validation_service.trigger_validation(
        tree.id,
        effect_node.id,
        ValidationRequest(provider="mock", prompt_overrides=None),
    )

    assert response.provider == "mock"
    assert response.node_id == effect_node.id
    assert 0 <= response.confidence <= 100
    assert response.summary

    history = validation_service.get_history(tree.id, effect_node.id)
    assert history
    assert history[-1].summary == response.summary

    stored_tree = container.tree_repo.load(tree.id)
    stored_node = next(node for node in stored_tree.nodes if node.id == effect_node.id)
    assert stored_node.validation is not None
    assert stored_node.validation.provider == "mock"
