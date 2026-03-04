"""Service encapsulating tree operations."""

from __future__ import annotations

from collections import OrderedDict
from collections import OrderedDict as OrderedDictType
from collections.abc import Iterable
from datetime import datetime

from app.exceptions import NotFoundError, ValidationFailure
from app.repositories import IndexRepository, TreeRepository
from app.schemas.api import (
    AiFeedbackRequest,
    AiFeedbackResponse,
    NodeCreateRequest,
    NodeResponse,
    RelationCounts,
    RelationCreateRequest,
    RelationResponse,
    TreeCreateRequest,
    TreeDetailResponse,
    TreeMetadata,
    TreeUpdateRequest,
)
from app.schemas.common import TimestampMetadata
from app.schemas.domain import (
    IndexEntry,
    NodeDocument,
    RelationDocument,
    RelationMetadata,
    TreeDocument,
)
from app.utils.identifiers import (
    ensure_acyclic,
    generate_node_id,
    generate_relation_id,
    generate_tree_id,
)
from app.utils.time import utcnow


class TreeService:
    """High-level operations for managing trees."""

    def __init__(
        self,
        tree_repo: TreeRepository,
        index_repo: IndexRepository,
        *,
        cache_maxsize: int = 16,
    ) -> None:
        self.tree_repo = tree_repo
        self.index_repo = index_repo
        self._cache: OrderedDictType[str, TreeDocument] = OrderedDict()
        self._cache_maxsize = max(cache_maxsize, 1)

    def list_trees(self, owner_id: str | None = None) -> list[IndexEntry]:
        entries = self.index_repo.load_all()
        if owner_id is not None:
            entries = [e for e in entries if e.owner_id == owner_id]
        return entries

    def create_tree(self, payload: TreeCreateRequest) -> TreeDocument:
        tree_id = generate_tree_id()
        metadata = self._resolve_metadata(payload.metadata, owner_id=payload.owner_id)
        tree = self._build_tree_document(
            tree_id=tree_id,
            name=payload.name,
            metadata=metadata,
            nodes=payload.nodes,
            relations=payload.relations,
            owner_id=payload.owner_id,
        )
        self.tree_repo.create(tree)
        self._sync_index(tree)
        return self._store_and_clone(tree)

    def get_tree(self, tree_id: str) -> TreeDocument:
        cached = self._cache_get(tree_id)
        if cached is not None:
            return cached.model_copy(deep=True)
        tree = self.tree_repo.load(tree_id)
        return self._store_and_clone(tree)

    def to_response(self, tree: TreeDocument) -> TreeDetailResponse:
        metadata = self._build_tree_metadata(tree)
        node_payloads = [self.node_to_response(tree, node.id) for node in tree.nodes]
        relation_payloads = [
            self.relation_to_response(relation) for relation in tree.relations
        ]
        return TreeDetailResponse(
            id=tree.id,
            name=tree.title,
            metadata=metadata,
            nodes=node_payloads,
            relations=relation_payloads,
            owner_id=tree.owner_id,
        )

    def update_tree(self, tree_id: str, payload: TreeUpdateRequest) -> TreeDocument:
        _ = self.tree_repo.load(tree_id)
        metadata = self._resolve_metadata(
            payload.metadata, owner_id=payload.owner_id, coerce_updated=True
        )
        tree = self._build_tree_document(
            tree_id=tree_id,
            name=payload.name,
            metadata=metadata,
            nodes=payload.nodes,
            relations=payload.relations,
            owner_id=payload.owner_id,
        )
        self.tree_repo.save(tree)
        self._sync_index(tree)
        return self._store_and_clone(tree)

    def import_tree(self, payload: TreeDetailResponse) -> TreeDocument:
        metadata = self._resolve_metadata(
            payload.metadata, owner_id=payload.owner_id, coerce_updated=False
        )
        tree = self._build_tree_document(
            tree_id=payload.id or generate_tree_id(),
            name=payload.name,
            metadata=metadata,
            nodes=payload.nodes,
            relations=payload.relations,
            owner_id=payload.owner_id,
        )
        self.tree_repo.save(tree)
        self._sync_index(tree)
        return self._store_and_clone(tree)

    def delete_tree(self, tree_id: str) -> None:
        self.tree_repo.delete(tree_id)
        self._cache.pop(tree_id, None)
        try:
            self.index_repo.delete(tree_id)
        except NotFoundError:
            # Index may have been out of sync; ignore to allow deletion
            pass

    def generate_ai_feedback(
        self, tree_id: str, payload: AiFeedbackRequest
    ) -> AiFeedbackResponse:
        if not payload.consent:
            raise ValidationFailure(
                "Consent is required before requesting AI feedback."
            )

        tree = self.get_tree(tree_id)
        node_count = len(tree.nodes)
        relation_count = len(tree.relations)
        summary = f"Tree '{tree.title}' contains {node_count} nodes and {relation_count} relations."

        recommendations: list[str] = []
        if node_count == 0:
            recommendations.append(
                "Add nodes to capture the current reality before requesting feedback."
            )
        else:
            recommendations.append(
                "Review whether each relation flows from cause to effect."
            )

        if relation_count < max(1, node_count // 2):
            recommendations.append(
                "Consider linking more causes to effects to expose gaps."
            )

        return AiFeedbackResponse(
            status="success",
            summary=summary,
            recommendations=recommendations or ["No recommendations available."],
            request_id=payload.request_id,
        )

    def assert_owner(self, tree: TreeDocument, account_id: str) -> None:
        """Raise NotFoundError if the tree does not belong to the account."""
        if tree.owner_id is not None and tree.owner_id != account_id:
            raise NotFoundError("Tree", tree.id)

    def _sync_index(self, tree: TreeDocument) -> None:
        entry = IndexEntry(
            id=tree.id,
            title=tree.title,
            description=tree.description,
            updated_at=tree.updated_at,
            owner_id=tree.owner_id,
        )
        self.index_repo.upsert(entry)

    def touch_tree(
        self, tree: TreeDocument, timestamp: datetime | None = None
    ) -> TreeDocument:
        """Return a copy of the tree with updated timestamp and sync index."""

        ts = timestamp or utcnow()
        updated_tree = tree.model_copy(
            update={
                "updated_at": ts,
                "metadata": self._merge_metadata(tree.metadata, {"updated_at": ts}),
            }
        )
        self.tree_repo.save(updated_tree)
        self._sync_index(updated_tree)
        return self._store_and_clone(updated_tree)

    def _cache_get(self, tree_id: str) -> TreeDocument | None:
        cached = self._cache.get(tree_id)
        if cached is None:
            return None
        # Maintain LRU ordering
        self._cache.move_to_end(tree_id)
        return cached

    def _store_and_clone(self, tree: TreeDocument) -> TreeDocument:
        """Store a tree document in the local cache and return a safe copy."""

        self._cache[tree.id] = tree
        self._cache.move_to_end(tree.id)
        if len(self._cache) > self._cache_maxsize:
            self._cache.popitem(last=False)
        return tree.model_copy(deep=True)

    def _build_tree_document(
        self,
        *,
        tree_id: str,
        name: str,
        metadata: TreeMetadata,
        nodes: Iterable[NodeResponse | NodeCreateRequest],
        relations: Iterable[RelationResponse | RelationCreateRequest],
        owner_id: str | None,
    ) -> TreeDocument:
        node_docs = [self._node_to_document(node, metadata) for node in nodes]
        node_ids = {node.id for node in node_docs}
        relation_docs = [
            self._relation_to_document(relation, metadata) for relation in relations
        ]
        self._validate_relation_targets(relation_docs, node_ids)

        tree_metadata = self._prepare_metadata_block(metadata)
        tree = TreeDocument(
            id=tree_id,
            title=name,
            description=None,
            metadata=tree_metadata,
            owner_id=owner_id,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
            nodes=node_docs,
            relations=relation_docs,
            version_refs=[],
        )
        return tree

    def _prepare_metadata_block(self, metadata: TreeMetadata) -> dict[str, object]:
        meta: dict[str, object] = {"version": metadata.version}
        if metadata.layout is not None:
            meta["layout"] = metadata.layout
        if metadata.owner_id is not None:
            meta["owner_id"] = metadata.owner_id
        return meta

    def _node_to_document(
        self, node: NodeResponse | NodeCreateRequest, metadata: TreeMetadata
    ) -> NodeDocument:
        node_id = getattr(node, "id", None) or generate_node_id()
        return NodeDocument(
            id=node_id,
            label=node.label,
            position=node.position,
            metadata=TimestampMetadata(
                created_at=metadata.created_at,
                updated_at=metadata.updated_at,
                author=None,
            ),
            visual=None,
            validation=None,
            extra={
                "type": node.type,
                "highlight_state": getattr(node, "highlight_state", "none"),
            },
        )

    def _relation_to_document(
        self, relation: RelationResponse | RelationCreateRequest, metadata: TreeMetadata
    ) -> RelationDocument:
        relation_id = getattr(relation, "id", None) or generate_relation_id()
        created_at = getattr(relation, "created_at", None) or metadata.updated_at
        return RelationDocument(
            id=relation_id,
            source_id=relation.source_node_id,
            target_id=relation.target_node_id,
            question_label=getattr(relation, "kind", "why"),
            notes=None,
            metadata=RelationMetadata(
                created_at=created_at, updated_at=metadata.updated_at, author=None
            ),
        )

    def _validate_relation_targets(
        self, relations: Iterable[RelationDocument], node_ids: set[str]
    ) -> None:
        edges: list[tuple[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for relation in relations:
            if relation.source_id not in node_ids or relation.target_id not in node_ids:
                raise ValidationFailure("Relation references unknown node id")
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

    def _resolve_metadata(
        self,
        metadata: TreeMetadata | None,
        *,
        owner_id: str | None = None,
        coerce_updated: bool = False,
    ) -> TreeMetadata:
        now = utcnow()
        base = metadata or TreeMetadata.from_timestamps(
            created_at=now, updated_at=now, owner_id=owner_id
        )
        updated_at = now if coerce_updated else base.updated_at
        return TreeMetadata(
            version=base.version,
            created_at=base.created_at,
            updated_at=updated_at,
            layout=base.layout,
            owner_id=base.owner_id or owner_id,
        )

    @staticmethod
    def _merge_metadata(
        existing: dict[str, object] | None, updates: dict[str, object]
    ) -> dict[str, object]:
        merged = {**(existing or {})}
        merged.update(updates)
        return merged

    def _build_tree_metadata(self, tree: TreeDocument) -> TreeMetadata:
        meta_dict = tree.metadata or {}
        version = int(meta_dict.get("version", 1))
        layout = meta_dict.get("layout")
        owner_id = meta_dict.get("owner_id") if tree.owner_id is None else tree.owner_id
        return TreeMetadata(
            version=version,
            created_at=tree.created_at,
            updated_at=tree.updated_at,
            layout=layout if isinstance(layout, dict) else None,
            owner_id=owner_id if isinstance(owner_id, str) else None,
        )

    @staticmethod
    def _relation_counts(
        relations: list[RelationDocument], node_id: str
    ) -> tuple[int, int]:
        up_count = sum(1 for relation in relations if relation.source_id == node_id)
        down_count = sum(1 for relation in relations if relation.target_id == node_id)
        return up_count, down_count

    def node_to_response(self, tree: TreeDocument, node_id: str) -> NodeResponse:
        node = next(node for node in tree.nodes if node.id == node_id)
        counts = self._relation_counts(tree.relations, node_id)
        extra = node.extra or {}
        return NodeResponse(
            id=node.id,
            label=node.label,
            type=extra.get("type", "child"),
            position=node.position,
            highlight_state=extra.get("highlight_state", "none"),
            relation_counts=RelationCounts(up_count=counts[0], down_count=counts[1]),
        )

    @staticmethod
    def relation_to_response(relation: RelationDocument) -> RelationResponse:
        return RelationResponse(
            id=relation.id,
            source_node_id=relation.source_id,
            target_node_id=relation.target_id,
            kind="why",
            created_at=relation.metadata.created_at,
        )
