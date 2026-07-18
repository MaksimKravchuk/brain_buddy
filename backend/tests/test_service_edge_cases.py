"""Focused service regression tests for previously unexercised error branches."""

from __future__ import annotations

import pytest

from app.exceptions import NotFoundError, ValidationFailure
from app.schemas import (
    NodeCreateRequest,
    NodeUpdateRequest,
    Position,
    RelationCreateRequest,
    RelationUpdateRequest,
    TreeCreateRequest,
    VersionCreateRequest,
    VisualState,
)
from app.schemas.common import ValidationState
from app.services.version_service import VersionService


def _tree_with_three_nodes(tree_service, node_service):
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Service edges"), owner_id="owner"
    )
    nodes = []
    for label, position in (("A", 0), ("B", 1), ("C", 2)):
        node, tree = node_service.create_node(
            tree.id,
            NodeCreateRequest(
                label=label,
                type="child",
                position=Position(x=position, y=position),
            ),
        )
        nodes.append(node)
    return tree, nodes


def test_node_empty_update_is_read_only_and_missing_node_is_not_found(
    tree_service, node_service
) -> None:
    tree, nodes = _tree_with_three_nodes(tree_service, node_service)

    unchanged, returned_tree = node_service.update_node(
        tree.id, nodes[0].id, NodeUpdateRequest()
    )

    assert unchanged == nodes[0]
    assert returned_tree.id == tree.id
    with pytest.raises(NotFoundError):
        node_service.update_node(tree.id, "missing", NodeUpdateRequest())
    with pytest.raises(NotFoundError):
        node_service.update_node(tree.id, "missing", NodeUpdateRequest(label="new"))


def test_node_update_preserves_requested_extra_fields_and_missing_delete_fails(
    tree_service, node_service
) -> None:
    tree, nodes = _tree_with_three_nodes(tree_service, node_service)

    updated, _ = node_service.update_node(
        tree.id,
        nodes[0].id,
        NodeUpdateRequest(type="parent", highlight_state="cause_candidate"),
    )

    assert updated.extra == {"type": "parent", "highlight_state": "cause_candidate"}
    with pytest.raises(NotFoundError):
        node_service.delete_node(tree.id, "missing")


def test_relation_empty_update_and_invalid_endpoint_updates_are_rejected(
    tree_service, node_service, relation_service
) -> None:
    tree, nodes = _tree_with_three_nodes(tree_service, node_service)
    relation, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=nodes[0].id,
            target_node_id=nodes[1].id,
            kind="why",
        ),
    )

    unchanged, _ = relation_service.update_relation(
        tree.id, relation.id, RelationUpdateRequest()
    )

    assert unchanged == relation
    with pytest.raises(NotFoundError):
        relation_service.update_relation(tree.id, "missing", RelationUpdateRequest())
    with pytest.raises(ValidationFailure, match="cannot be null"):
        relation_service.update_relation(
            tree.id, relation.id, RelationUpdateRequest(source_node_id=None)
        )
    with pytest.raises(NotFoundError):
        relation_service.update_relation(
            tree.id, relation.id, RelationUpdateRequest(target_node_id="missing")
        )


def test_relation_updates_reject_duplicates_and_cycles(
    tree_service, node_service, relation_service
) -> None:
    tree, nodes = _tree_with_three_nodes(tree_service, node_service)
    first, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=nodes[0].id,
            target_node_id=nodes[1].id,
            kind="why",
        ),
    )
    second, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=nodes[1].id,
            target_node_id=nodes[2].id,
            kind="why",
        ),
    )

    with pytest.raises(ValidationFailure, match="already exists"):
        relation_service.update_relation(
            tree.id,
            second.id,
            RelationUpdateRequest(
                source_node_id=nodes[0].id,
                target_node_id=nodes[1].id,
            ),
        )
    with pytest.raises(ValidationFailure, match="cycle"):
        relation_service.update_relation(
            tree.id,
            second.id,
            RelationUpdateRequest(
                source_node_id=nodes[1].id,
                target_node_id=nodes[0].id,
            ),
        )


def test_version_restore_is_idempotent_and_missing_version_cannot_be_deleted(
    tree_service, version_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Versions"), owner_id="owner"
    )
    version = version_service.create_version(
        tree.id, VersionCreateRequest(label="baseline")
    )

    restored = version_service.restore_version(tree.id, version.id)

    assert [ref.id for ref in restored.version_refs].count(version.id) == 1
    with pytest.raises(NotFoundError):
        version_service.delete_version(tree.id, "missing")


def test_version_diffs_report_relation_and_all_node_field_changes(
    tree_service, node_service, relation_service, version_service
) -> None:
    tree, nodes = _tree_with_three_nodes(tree_service, node_service)
    relation, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=nodes[0].id,
            target_node_id=nodes[1].id,
            kind="why",
        ),
    )
    version_service.create_version(tree.id, VersionCreateRequest(label="before"))
    relation_service.update_relation(
        tree.id,
        relation.id,
        RelationUpdateRequest(target_node_id=nodes[2].id),
    )

    changed_version = version_service.create_version(
        tree.id, VersionCreateRequest(label="after")
    )
    changed_node = nodes[0].model_copy(
        update={
            "visual": VisualState(color="#fff", highlight=True),
            "validation": ValidationState(
                confidence=42,
                provider="mock",
                last_checked=nodes[0].metadata.updated_at,
            ),
            "extra": {"type": "parent"},
        }
    )
    changed_relation = relation.model_copy(
        update={
            "source_id": nodes[1].id,
            "target_id": nodes[2].id,
            "question_label": "why",
            "notes": "changed",
        }
    )

    assert changed_version.diff.relations_modified == 1
    assert VersionService._compare_nodes(nodes[0], changed_node) == [
        "visual",
        "validation",
        "extra",
    ]
    assert VersionService._compare_relations(relation, changed_relation) == [
        "source_id",
        "target_id",
        "notes",
    ]
