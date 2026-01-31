"""Service layer for relation operations."""

from __future__ import annotations

from app.exceptions import NotFoundError, ValidationFailure
from app.repositories import TreeRepository
from app.schemas.api import RelationCreateRequest, RelationUpdateRequest
from app.schemas.domain import RelationDocument, RelationMetadata, TreeDocument
from app.services.tree_service import TreeService
from app.utils.identifiers import ensure_acyclic, generate_relation_id
from app.utils.time import utcnow


class RelationService:
    """Manage relations between nodes."""

    def __init__(self, tree_repo: TreeRepository, tree_service: TreeService) -> None:
        self.tree_repo = tree_repo
        self.tree_service = tree_service

    def create_relation(
        self, tree_id: str, payload: RelationCreateRequest
    ) -> tuple[RelationDocument, TreeDocument]:
        tree = self.tree_repo.load(tree_id)
        source_id = payload.source_node_id
        target_id = payload.target_node_id

        self._ensure_node_exists(tree, source_id)
        self._ensure_node_exists(tree, target_id)
        self._ensure_not_duplicate(tree.relations, source_id, target_id)

        now = utcnow()
        relation = RelationDocument(
            id=generate_relation_id(),
            source_id=source_id,
            target_id=target_id,
            question_label=payload.kind,
            notes=None,
            metadata=RelationMetadata(created_at=now, updated_at=now, author=None),
        )

        candidate_relations = [*tree.relations, relation]
        self._validate_relations(candidate_relations)
        updated_tree = tree.model_copy(update={"relations": candidate_relations})
        updated_tree = self.tree_service.touch_tree(updated_tree, timestamp=now)
        return relation, updated_tree

    def update_relation(
        self, tree_id: str, relation_id: str, payload: RelationUpdateRequest
    ) -> tuple[RelationDocument, TreeDocument]:
        tree = self.tree_repo.load(tree_id)
        relations = list(tree.relations)
        try:
            index = next(
                idx
                for idx, relation in enumerate(relations)
                if relation.id == relation_id
            )
        except StopIteration as exc:
            raise NotFoundError("Relation", relation_id) from exc

        relation = relations[index]

        updates: dict[str, object] = {}
        if "source_node_id" in payload.model_fields_set:
            if payload.source_node_id is None:
                raise ValidationFailure("source_node_id cannot be null")
            self._ensure_node_exists(tree, payload.source_node_id)
            updates["source_id"] = payload.source_node_id
        if "target_node_id" in payload.model_fields_set:
            if payload.target_node_id is None:
                raise ValidationFailure("target_node_id cannot be null")
            self._ensure_node_exists(tree, payload.target_node_id)
            updates["target_id"] = payload.target_node_id
        if "kind" in payload.model_fields_set and payload.kind is not None:
            updates["question_label"] = payload.kind

        if not updates:
            return relation, tree

        now = utcnow()
        metadata = relation.metadata.model_copy(update={"updated_at": now})
        updates["metadata"] = metadata
        updated_relation = relation.model_copy(update=updates)

        # Ensure updated relation does not duplicate existing pair (excluding itself)
        self._ensure_not_duplicate(
            relations,
            updated_relation.source_id,
            updated_relation.target_id,
            skip_relation_id=relation_id,
        )

        relations[index] = updated_relation
        self._validate_relations(relations)
        updated_tree = tree.model_copy(update={"relations": relations})
        updated_tree = self.tree_service.touch_tree(updated_tree, timestamp=now)
        return updated_relation, updated_tree

    def delete_relation(self, tree_id: str, relation_id: str) -> TreeDocument:
        tree = self.tree_repo.load(tree_id)
        relations = [
            relation for relation in tree.relations if relation.id != relation_id
        ]
        if len(relations) == len(tree.relations):
            raise NotFoundError("Relation", relation_id)
        updated_tree = tree.model_copy(update={"relations": relations})
        updated_tree = self.tree_service.touch_tree(updated_tree)
        return updated_tree

    def _ensure_node_exists(self, tree: TreeDocument, node_id: str) -> None:
        if not any(node.id == node_id for node in tree.nodes):
            raise NotFoundError("Node", node_id)

    def _ensure_not_duplicate(
        self,
        relations: list[RelationDocument],
        source_id: str,
        target_id: str,
        *,
        skip_relation_id: str | None = None,
    ) -> None:
        if any(
            relation.id != skip_relation_id
            and relation.source_id == source_id
            and relation.target_id == target_id
            for relation in relations
        ):
            raise ValidationFailure(
                "A link already exists between these nodes.",
                detail={
                    "reason": "duplicate_relation",
                    "source_node_id": source_id,
                    "target_node_id": target_id,
                },
            )

    def _validate_relations(self, relations: list[RelationDocument]) -> None:
        edges = []
        seen_pairs: set[tuple[str, str]] = set()
        for relation in relations:
            key = (relation.source_id, relation.target_id)
            if key in seen_pairs:
                raise ValidationFailure(
                    "A link already exists between these nodes.",
                    detail={
                        "reason": "duplicate_relation",
                        "source_node_id": relation.source_id,
                        "target_node_id": relation.target_id,
                    },
                )
            seen_pairs.add(key)
            edges.append(key)
        ensure_acyclic(edges)
