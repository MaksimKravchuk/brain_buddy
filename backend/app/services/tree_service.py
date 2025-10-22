"""Service encapsulating tree operations."""
from __future__ import annotations

from datetime import datetime

from app.exceptions import NotFoundError
from app.repositories import IndexRepository, TreeRepository
from app.schemas.api import TreeCreateRequest, TreeUpdateRequest
from app.schemas.domain import IndexEntry, TreeDocument
from app.utils.identifiers import generate_tree_id
from app.utils.time import utcnow


class TreeService:
    """High-level operations for managing trees."""

    def __init__(self, tree_repo: TreeRepository, index_repo: IndexRepository) -> None:
        self.tree_repo = tree_repo
        self.index_repo = index_repo

    def list_trees(self) -> list[IndexEntry]:
        return self.index_repo.load_all()

    def create_tree(self, payload: TreeCreateRequest) -> TreeDocument:
        now = utcnow()
        tree = TreeDocument(
            id=generate_tree_id(),
            title=payload.title,
            description=payload.description,
            created_at=now,
            updated_at=now,
            nodes=[],
            relations=[],
            version_refs=[],
        )
        self.tree_repo.create(tree)
        self._sync_index(tree)
        return tree

    def get_tree(self, tree_id: str) -> TreeDocument:
        return self.tree_repo.load(tree_id)

    def update_tree(self, tree_id: str, payload: TreeUpdateRequest) -> TreeDocument:
        tree = self.tree_repo.load(tree_id)
        updates = {}
        if payload.title is not None:
            updates["title"] = payload.title
        if payload.description is not None:
            updates["description"] = payload.description
        if updates:
            updated_tree = tree.model_copy(update=updates)
        else:
            updated_tree = tree
        updated_tree = updated_tree.model_copy(update={"updated_at": utcnow()})
        self.tree_repo.save(updated_tree)
        self._sync_index(updated_tree)
        return updated_tree

    def delete_tree(self, tree_id: str) -> None:
        self.tree_repo.delete(tree_id)
        try:
            self.index_repo.delete(tree_id)
        except NotFoundError:
            # Index may have been out of sync; ignore to allow deletion
            pass

    def _sync_index(self, tree: TreeDocument) -> None:
        entry = IndexEntry(
            id=tree.id,
            title=tree.title,
            description=tree.description,
            updated_at=tree.updated_at,
        )
        self.index_repo.upsert(entry)

    def touch_tree(self, tree: TreeDocument, timestamp: datetime | None = None) -> TreeDocument:
        """Return a copy of the tree with updated timestamp and sync index."""

        ts = timestamp or utcnow()
        updated_tree = tree.model_copy(update={"updated_at": ts})
        self.tree_repo.save(updated_tree)
        self._sync_index(updated_tree)
        return updated_tree

