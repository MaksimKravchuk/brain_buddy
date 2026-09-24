"""Repository for tree documents."""

from __future__ import annotations

import fcntl
import shutil
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app.exceptions import ConflictError, NotFoundError, StaleRevisionError
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
        with self._exclusive_tree_lock(tree.id):
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
        command_id: str | None = None,
    ) -> TreeDocument:
        """Atomically load, transform, replace, and publish one tree document."""

        with self._exclusive_tree_lock(tree_id):
            current = self.load(tree_id)
            candidate = update(current)
            updated = candidate.model_copy(
                update={
                    "revision": current.revision + 1,
                    # Legacy mutations must invalidate any command marker left
                    # by a partially committed Stage B command. Reconciliation
                    # only trusts markers written by its own command path.
                    "last_command_id": command_id,
                },
                deep=True,
            )
            self.save(updated)
            if after_save is not None:
                after_save(updated)
            return updated

    def replace_if_current(
        self,
        tree_id: str,
        *,
        expected_revision: int,
        replacement: TreeDocument,
        after_save: Callable[[TreeDocument], None] | None = None,
    ) -> TreeDocument:
        """Persist a precomputed command target at its recorded base revision."""

        with self._exclusive_tree_lock(tree_id):
            current = self.load(tree_id)
            if current.revision != expected_revision:
                raise StaleRevisionError(
                    "Tree",
                    tree_id,
                    current_revision=current.revision,
                    current_updated_at=current.updated_at,
                )
            if (
                replacement.id != tree_id
                or replacement.revision != expected_revision + 1
            ):
                raise ConflictError("Tree", tree_id, "Prepared tree target is invalid.")
            self.save(replacement)
            if after_save is not None:
                after_save(replacement)
            return replacement

    def update_if_current(
        self,
        tree_id: str,
        *,
        expected_updated_at: datetime | None = None,
        expected_revision: int | None = None,
        update: Callable[[TreeDocument], TreeDocument],
        after_save: Callable[[TreeDocument], None] | None = None,
        command_id: str | None = None,
    ) -> TreeDocument:
        """Atomically replace a tree when its preferred or legacy token matches."""

        def guarded_update(current: TreeDocument) -> TreeDocument:
            is_current = (
                current.revision == expected_revision
                if expected_revision is not None
                else current.updated_at == expected_updated_at
            )
            if not is_current:
                if expected_revision is not None:
                    raise StaleRevisionError(
                        "Tree",
                        tree_id,
                        current_revision=current.revision,
                        current_updated_at=current.updated_at,
                    )
                raise ConflictError(
                    "Tree",
                    tree_id,
                    f"Tree '{tree_id}' has newer changes; reload before saving.",
                )
            return update(current)

        return self.mutate(
            tree_id,
            update=guarded_update,
            after_save=after_save,
            command_id=command_id,
        )

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

    def delete_if_current(
        self,
        tree_id: str,
        *,
        owner_id: str,
        expected_revision: int,
        before_delete: Callable[[TreeDocument], None] | None = None,
        after_delete: Callable[[], None] | None = None,
    ) -> None:
        """Delete only the owner tree at ``expected_revision`` under one lock."""

        with self._exclusive_tree_lock(tree_id):
            tree = self.load(tree_id)
            if tree.owner_id != owner_id:
                raise NotFoundError("Tree", tree_id)
            if tree.revision != expected_revision:
                raise StaleRevisionError(
                    "Tree",
                    tree_id,
                    current_revision=tree.revision,
                    current_updated_at=tree.updated_at,
                )
            if before_delete is not None:
                before_delete(tree)
            shutil.rmtree(self.resolve(tree_id))
            if after_delete is not None:
                after_delete()

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
