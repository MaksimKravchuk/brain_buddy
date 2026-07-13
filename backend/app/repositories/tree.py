"""Repository for tree documents."""

from __future__ import annotations

import fcntl
import shutil
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.exceptions import ConflictError, NotFoundError
from app.schemas.domain import TreeDocument
from app.utils.file_ops import ensure_directory

from .base import BaseRepository

TREE_FILENAME = "tree.json"


class TreeRepository(BaseRepository):
    """Persist and retrieve tree documents from the filesystem."""

    def tree_dir(self, tree_id: str) -> Path:
        return self.resolve(tree_id)

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
        ensure_directory(path.parent)
        self.dump_model(path, tree)

    def mutate(
        self,
        tree_id: str,
        *,
        update: Callable[[TreeDocument], TreeDocument],
        after_save: Callable[[TreeDocument], None] | None = None,
    ) -> TreeDocument:
        """Atomically load, transform, replace, and publish one tree document."""

        with self._exclusive_tree_lock(tree_id):
            current = self.load(tree_id)
            updated = update(current)
            self.save(updated)
            if after_save is not None:
                after_save(updated)
            return updated

    def update_if_current(
        self,
        tree_id: str,
        *,
        expected_updated_at: datetime,
        update: Callable[[TreeDocument], TreeDocument],
        after_save: Callable[[TreeDocument], None] | None = None,
    ) -> TreeDocument:
        """Atomically replace a tree only when its timestamp still matches."""

        def guarded_update(current: TreeDocument) -> TreeDocument:
            updated = update(current)
            if current.updated_at != expected_updated_at:
                raise ConflictError(
                    "Tree",
                    tree_id,
                    f"Tree '{tree_id}' has newer changes; reload before saving.",
                )
            return updated

        return self.mutate(tree_id, update=guarded_update, after_save=after_save)

    @contextmanager
    def _exclusive_tree_lock(self, tree_id: str) -> Generator[None, None, None]:
        """Serialize read-check-write transactions for one persisted tree."""

        lock_dir = ensure_directory(self.resolve(".locks"))
        lock_path = lock_dir / f"{tree_id}.lock"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def load(self, tree_id: str) -> TreeDocument:
        path = self.tree_path(tree_id)
        if not path.exists():
            raise NotFoundError("Tree", tree_id)
        return self.load_model(path, TreeDocument)

    def read(
        self,
        tree_id: str,
        *,
        after_load: Callable[[TreeDocument], None] | None = None,
    ) -> TreeDocument:
        """Read a tree while serializing cache publication with writers."""

        with self._exclusive_tree_lock(tree_id):
            tree = self.load(tree_id)
            if after_load is not None:
                after_load(tree)
            return tree

    def delete(
        self,
        tree_id: str,
        *,
        before_delete: Callable[[TreeDocument], None] | None = None,
        after_delete: Callable[[], None] | None = None,
    ) -> None:
        with self._exclusive_tree_lock(tree_id):
            tree = self.load(tree_id)
            if before_delete is not None:
                before_delete(tree)
            shutil.rmtree(self.resolve(tree_id))
            if after_delete is not None:
                after_delete()
