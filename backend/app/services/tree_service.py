"""Service encapsulating tree operations."""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections import OrderedDict as OrderedDictType
from collections.abc import Callable, Iterable
from contextlib import suppress
from datetime import datetime, timedelta
from threading import RLock
from typing import Any

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

logger = logging.getLogger(__name__)


class TreeService:
    """High-level operations for managing trees."""

    def __init__(  # pragma: no mutate block
        self,
        tree_repo: TreeRepository,
        index_repo: IndexRepository,
        *,
        cache_maxsize: int = 16,
    ) -> None:
        self.tree_repo = tree_repo
        self.index_repo = index_repo
        self._cache: OrderedDictType[str, TreeDocument] = OrderedDict()
        self._cache_lock = RLock()
        self._cache_maxsize = max(cache_maxsize, 1)

    def list_trees(self, *, owner_id: str) -> list[IndexEntry]:
        return [
            entry for entry in self.index_repo.load_all() if entry.owner_id == owner_id
        ]

    def create_tree(self, payload: TreeCreateRequest, *, owner_id: str) -> TreeDocument:
        tree_id = generate_tree_id()
        metadata = self._resolve_metadata(payload.metadata, owner_id=owner_id)
        tree = self._build_tree_document(
            tree_id=tree_id,
            name=payload.name,
            metadata=metadata,
            nodes=payload.nodes,
            relations=payload.relations,
            owner_id=owner_id,
        )
        self.tree_repo.create(tree)
        self._sync_index(tree)
        return self._store_and_clone(tree)

    def get_tree(self, tree_id: str) -> TreeDocument:
        tree = self.tree_repo.read(tree_id, after_load=self._cache_store)
        return tree.model_copy(deep=True)

    def get_tree_for_owner(self, tree_id: str, *, owner_id: str) -> TreeDocument:
        """Return a tree only if it belongs to the given owner.

        Raises `NotFoundError` both when the tree does not exist and when
        it belongs to someone else. Returning an indistinguishable 404 in
        both cases prevents leaking whether a tree ID exists.
        """

        try:
            tree = self.get_tree(tree_id)
        except NotFoundError:
            raise NotFoundError("Tree", tree_id) from None
        if tree.owner_id != owner_id:
            raise NotFoundError("Tree", tree_id)
        return tree

    def assert_owner(self, tree_id: str, *, owner_id: str) -> None:
        """Raise `NotFoundError` if the tree doesn't exist or owner differs."""

        self.get_tree_for_owner(tree_id, owner_id=owner_id)

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

    def update_tree(
        self, tree_id: str, payload: TreeUpdateRequest, *, owner_id: str
    ) -> TreeDocument:
        def apply_update(existing_tree: TreeDocument) -> TreeDocument:
            if existing_tree.owner_id != owner_id:
                raise NotFoundError("Tree", tree_id)
            metadata = self._resolve_metadata(
                payload.metadata, owner_id=owner_id, coerce_updated=True
            )
            tree = self._build_tree_document(
                tree_id=tree_id,
                name=payload.name,
                metadata=metadata,
                nodes=payload.nodes,
                relations=payload.relations,
                owner_id=owner_id,
            )
            return self._preserve_unrepresented_tree_data(tree, existing_tree)

        tree = self.tree_repo.update_if_current(
            tree_id,
            expected_updated_at=payload.metadata.updated_at,
            update=apply_update,
            after_save=self._commit_tree_state,
        )
        return tree.model_copy(deep=True)

    def import_tree(
        self, payload: TreeDetailResponse, *, owner_id: str
    ) -> TreeDocument:
        # Always stamp the importing user as owner — never trust owner_id
        # embedded in an uploaded payload.
        metadata = self._resolve_metadata(
            payload.metadata, owner_id=owner_id, coerce_updated=False
        )
        # Use a fresh tree id so an import can never overwrite an
        # existing tree (which might belong to someone else).
        tree = self._build_tree_document(
            tree_id=generate_tree_id(),
            name=payload.name,
            metadata=metadata,
            nodes=payload.nodes,
            relations=payload.relations,
            owner_id=owner_id,
        )
        self.tree_repo.save(tree)
        self._sync_index(tree)
        return self._store_and_clone(tree)

    def delete_tree(self, tree_id: str, *, owner_id: str) -> None:
        def verify_owner(tree: TreeDocument) -> None:
            if tree.owner_id != owner_id:
                raise NotFoundError("Tree", tree_id)

        self.tree_repo.delete(
            tree_id,
            before_delete=verify_owner,
            after_delete=lambda: self._remove_tree_state(tree_id),
        )

    def remove_stale_tree_state(self, tree_id: str) -> None:
        """Drop index/cache state for a tree whose files are already gone.

        Account-purge retry support: a deletion interrupted between removing
        the tree directory and updating the index leaves an owner-identifying
        index entry that a normal delete can no longer reach. Idempotent.
        """

        self._remove_tree_state(tree_id)

    def generate_ai_feedback(
        self, tree_id: str, payload: AiFeedbackRequest, *, owner_id: str
    ) -> AiFeedbackResponse:
        if not payload.consent:
            raise ValidationFailure(
                "Consent is required before requesting AI feedback."
            )

        tree = self.get_tree_for_owner(tree_id, owner_id=owner_id)
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

        # No `or [...]` fallback: the branch above always appends, so
        # `recommendations` is never empty and the fallback was unreachable.
        return AiFeedbackResponse(
            status="success",
            summary=summary,
            recommendations=recommendations,
            request_id=payload.request_id,
        )

    def _sync_index(self, tree: TreeDocument) -> None:
        entry = IndexEntry(
            id=tree.id,
            title=tree.title,
            description=tree.description,
            updated_at=tree.updated_at,
            owner_id=tree.owner_id,
        )
        self.index_repo.upsert(entry)

    def mutate_tree(
        self,
        tree_id: str,
        update: Callable[[TreeDocument], TreeDocument],
        *,
        timestamp: datetime | None = None,
        after_save: Callable[[TreeDocument], None] | None = None,
    ) -> TreeDocument:
        """Apply a tree mutation under the shared per-tree transaction lock."""

        def touch(current: TreeDocument) -> TreeDocument:
            ts = max(
                timestamp or utcnow(),
                current.updated_at + timedelta(microseconds=1),
            )
            updated_tree = update(current)
            return updated_tree.model_copy(
                update={
                    "updated_at": ts,
                    "metadata": self._merge_metadata(
                        updated_tree.metadata, {"updated_at": ts}
                    ),
                }
            )

        def publish(updated_tree: TreeDocument) -> None:
            self._commit_tree_state(updated_tree)
            if after_save is not None:
                after_save(updated_tree)

        updated_tree = self.tree_repo.mutate(tree_id, update=touch, after_save=publish)
        return updated_tree.model_copy(deep=True)

    def _commit_tree_state(self, tree: TreeDocument) -> None:
        """Publish index and cache state while holding the tree transaction lock."""

        self._sync_index(tree)
        self._cache_store(tree)

    def _remove_tree_state(self, tree_id: str) -> None:
        """Remove derived local state while holding the tree transaction lock."""

        with self._cache_lock:
            self._cache.pop(tree_id, None)
        with suppress(NotFoundError):
            self.index_repo.delete(tree_id)

    def _cache_store(self, tree: TreeDocument) -> None:
        with self._cache_lock:
            self._cache[tree.id] = tree
            self._cache.move_to_end(tree.id)
            if len(self._cache) > self._cache_maxsize:
                self._cache.popitem(last=False)

    def _cache_get(self, tree_id: str) -> TreeDocument | None:
        with self._cache_lock:
            cached = self._cache.get(tree_id)
            if cached is None:
                return None
            # Maintain LRU ordering
            self._cache.move_to_end(tree_id)
            return cached

    def _store_and_clone(self, tree: TreeDocument) -> TreeDocument:
        """Store a tree document in the local cache and return a safe copy."""

        self._cache_store(tree)
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

    def _preserve_unrepresented_tree_data(
        self, tree: TreeDocument, existing_tree: TreeDocument
    ) -> TreeDocument:
        """Carry forward fields that public full-tree PUT cannot represent."""

        existing_nodes = {node.id: node for node in existing_tree.nodes}
        merged_nodes: list[NodeDocument] = []
        for node in tree.nodes:
            previous = existing_nodes.get(node.id)
            if previous is None:
                merged_nodes.append(node)
                continue

            previous_extra = previous.extra if isinstance(previous.extra, dict) else {}
            next_extra = node.extra if isinstance(node.extra, dict) else {}
            merged_nodes.append(
                node.model_copy(
                    update={
                        "metadata": previous.metadata.model_copy(
                            update={"updated_at": node.metadata.updated_at}
                        ),
                        "visual": previous.visual,
                        "validation": previous.validation,
                        "extra": {**previous_extra, **next_extra},
                    },
                    deep=True,
                )
            )

        existing_relations = {
            relation.id: relation for relation in existing_tree.relations
        }
        merged_relations: list[RelationDocument] = []
        for relation in tree.relations:
            previous_relation = existing_relations.get(relation.id)
            if previous_relation is None:
                merged_relations.append(relation)
                continue
            merged_relations.append(
                relation.model_copy(
                    update={
                        "notes": previous_relation.notes,
                        "metadata": previous_relation.metadata.model_copy(
                            update={"updated_at": relation.metadata.updated_at}
                        ),
                    },
                    deep=True,
                )
            )

        return tree.model_copy(
            update={
                "description": existing_tree.description,
                "nodes": merged_nodes,
                "relations": merged_relations,
                "version_refs": existing_tree.version_refs,
            },
            deep=True,
        )

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

    _VALID_NODE_TYPES = frozenset({"parent", "child"})
    _VALID_HIGHLIGHT_STATES = frozenset({"none", "cause_candidate", "effect_spanning"})

    def node_to_response(self, tree: TreeDocument, node_id: str) -> NodeResponse:
        node = next(node for node in tree.nodes if node.id == node_id)
        counts = self._relation_counts(tree.relations, node_id)

        # Legacy tree documents may carry pre-refactor enum values in
        # node.extra (e.g. {"type": "root"} or {"highlight_state": "caused"}).
        # Coerce unknowns to safe defaults and log WARNINGs so data-integrity
        # issues surface in logs/Sentry instead of being silently masked.
        if isinstance(node.extra, dict):
            extra: dict[str, Any] = node.extra
        else:
            if node.extra is not None:
                logger.warning(
                    "Node %s in tree %s has non-dict extra (%s); " "treating as empty.",
                    node.id,
                    tree.id,
                    type(node.extra).__name__,
                )
            extra = {}

        raw_type = extra.get("type", "child")
        if raw_type in self._VALID_NODE_TYPES:
            node_type = raw_type
        else:
            logger.warning(
                "Node %s in tree %s has invalid extra.type=%r; " "coercing to 'child'.",
                node.id,
                tree.id,
                raw_type,
            )
            node_type = "child"

        raw_highlight = extra.get("highlight_state", "none")
        if raw_highlight in self._VALID_HIGHLIGHT_STATES:
            highlight_state = raw_highlight
        else:
            logger.warning(
                "Node %s in tree %s has invalid extra.highlight_state=%r; "
                "coercing to 'none'.",
                node.id,
                tree.id,
                raw_highlight,
            )
            highlight_state = "none"

        return NodeResponse(
            id=node.id,
            label=node.label,
            type=node_type,
            position=node.position,
            highlight_state=highlight_state,
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
