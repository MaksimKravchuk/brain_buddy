"""Service functions for managing nodes within a tree."""
from __future__ import annotations

from typing import Tuple

from app.exceptions import NotFoundError, ValidationFailure
from app.repositories import TreeRepository
from app.schemas.api import NodeCreateRequest, NodeUpdateRequest
from app.schemas.domain import NodeDocument, TreeDocument
from app.schemas.common import TimestampMetadata
from app.services.tree_service import TreeService
from app.utils.identifiers import generate_node_id
from app.utils.time import utcnow


class NodeService:
    """Manage node lifecycle operations."""

    def __init__(self, tree_repo: TreeRepository, tree_service: TreeService) -> None:
        self.tree_repo = tree_repo
        self.tree_service = tree_service

    def create_node(self, tree_id: str, payload: NodeCreateRequest) -> Tuple[NodeDocument, TreeDocument]:
        tree = self.tree_repo.load(tree_id)
        now = utcnow()
        node = NodeDocument(
            id=generate_node_id(),
            label=payload.label,
            position=payload.position,
            metadata=TimestampMetadata(created_at=now, updated_at=now, author=None),
            visual=payload.visual,
            validation=None,
            extra=None,
        )

        updated_tree = tree.model_copy(update={"nodes": [*tree.nodes, node]})
        updated_tree = self.tree_service.touch_tree(updated_tree, timestamp=now)
        return node, updated_tree

    def update_node(self, tree_id: str, node_id: str, payload: NodeUpdateRequest) -> Tuple[NodeDocument, TreeDocument]:
        tree = self.tree_repo.load(tree_id)
        nodes = list(tree.nodes)
        try:
            index = next(idx for idx, node in enumerate(nodes) if node.id == node_id)
        except StopIteration as exc:
            raise NotFoundError("Node", node_id) from exc

        node = nodes[index]
        if not payload.model_fields_set:
            return node, tree

        updates = {}
        if "label" in payload.model_fields_set:
            updates["label"] = payload.label
        if "position" in payload.model_fields_set and payload.position is not None:
            updates["position"] = payload.position
        if "visual" in payload.model_fields_set:
            updates["visual"] = payload.visual

        metadata = node.metadata.model_copy(update={"updated_at": utcnow()})
        updates["metadata"] = metadata
        updated_node = node.model_copy(update=updates)
        nodes[index] = updated_node
        updated_tree = tree.model_copy(update={"nodes": nodes})
        updated_tree = self.tree_service.touch_tree(updated_tree)
        return updated_node, updated_tree

    def delete_node(self, tree_id: str, node_id: str, *, cascade: bool = False) -> TreeDocument:
        tree = self.tree_repo.load(tree_id)
        nodes = [node for node in tree.nodes if node.id != node_id]
        if len(nodes) == len(tree.nodes):
            raise NotFoundError("Node", node_id)

        relations = list(tree.relations)
        remaining_relations = [
            relation
            for relation in relations
            if relation.source_id != node_id and relation.target_id != node_id
        ]
        removed_relations = len(relations) - len(remaining_relations)
        if removed_relations and not cascade:
            raise ValidationFailure(
                f"Node '{node_id}' has {removed_relations} related connection(s); use cascade=true to remove."
            )

        updated_tree = tree.model_copy(update={"nodes": nodes, "relations": remaining_relations})
        updated_tree = self.tree_service.touch_tree(updated_tree)
        return updated_tree
