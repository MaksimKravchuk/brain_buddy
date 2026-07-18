"""Repository managing the global tree index for quick listing."""

from __future__ import annotations

import fcntl
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from pathlib import Path

from app.exceptions import NotFoundError
from app.schemas.domain import IndexEntry
from app.utils.file_ops import read_json

from .base import BaseRepository

INDEX_FILENAME = "index.json"


class IndexRepository(BaseRepository):
    """Maintain `index.json` mapping tree identifiers to metadata."""

    def __init__(self, root: Path) -> None:  # pragma: no mutate block
        super().__init__(root)
        self.index_path = self.resolve(INDEX_FILENAME)

    def load_all(self) -> list[IndexEntry]:
        if not self.index_path.exists():
            return []
        raw_entries: list[dict[str, object]] = read_json(self.index_path)
        return [IndexEntry.model_validate(entry) for entry in raw_entries]

    def save_all(self, entries: Iterable[IndexEntry]) -> None:
        data = [entry.model_dump(mode="json") for entry in entries]
        self.dump_payload(self.index_path, data)

    def upsert(self, entry: IndexEntry) -> None:
        with self._exclusive_index_lock():
            entries = self.load_all()
            for idx, existing in enumerate(entries):
                if existing.id == entry.id:
                    entries[idx] = entry
                    break
            else:
                entries.append(entry)
            self.save_all(entries)

    def delete(self, tree_id: str) -> None:
        with self._exclusive_index_lock():
            entries = self.load_all()
            updated = [entry for entry in entries if entry.id != tree_id]
            if len(updated) == len(entries):
                raise NotFoundError("Tree", tree_id)
            self.save_all(updated)

    @contextmanager
    def _exclusive_index_lock(self) -> Generator[None, None, None]:
        """Serialize read-modify-write operations for the shared index."""

        lock_path = self.resolve(".index.lock")
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
