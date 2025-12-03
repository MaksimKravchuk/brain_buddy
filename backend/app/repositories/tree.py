"""Repository for tree documents."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.exceptions import ConflictError, NotFoundError
from app.schemas.domain import TreeDocument
from app.utils.file_ops import ensure_directory

from .base import BaseRepository

TREE_FILENAME = "tree.json"


class TreeRepository(BaseRepository):
    """Persist and retrieve tree documents from the filesystem."""

    def tree_dir(self, tree_id: str) -> Path:
        return ensure_directory(self.resolve(tree_id))

    def tree_path(self, tree_id: str) -> Path:
        return self.tree_dir(tree_id) / TREE_FILENAME

    def exists(self, tree_id: str) -> bool:
        return self.tree_path(tree_id).exists()

    def create(self, tree: TreeDocument) -> None:
        if self.exists(tree.id):
            raise ConflictError("Tree", tree.id)
        self.save(tree)

    def save(self, tree: TreeDocument) -> None:
        path = self.tree_path(tree.id)
        self.dump_model(path, tree)

    def load(self, tree_id: str) -> TreeDocument:
        path = self.tree_path(tree_id)
        if not path.exists():
            raise NotFoundError("Tree", tree_id)
        return self.load_model(path, TreeDocument)

    def delete(self, tree_id: str) -> None:
        directory = self.resolve(tree_id)
        if not directory.exists():
            raise NotFoundError("Tree", tree_id)
        shutil.rmtree(directory)
