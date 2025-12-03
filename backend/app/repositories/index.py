"""Repository managing the global tree index for quick listing."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from app.exceptions import NotFoundError
from app.schemas.domain import IndexEntry
from app.utils.file_ops import read_json

from .base import BaseRepository

INDEX_FILENAME = "index.json"


class IndexRepository(BaseRepository):
    """Maintain `index.json` mapping tree identifiers to metadata."""

    def __init__(self, root: Path) -> None:
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
        entries = self.load_all()
        for idx, existing in enumerate(entries):
            if existing.id == entry.id:
                entries[idx] = entry
                break
        else:
            entries.append(entry)
        self.save_all(entries)

    def delete(self, tree_id: str) -> None:
        entries = self.load_all()
        updated = [entry for entry in entries if entry.id != tree_id]
        if len(updated) == len(entries):
            raise NotFoundError("Tree", tree_id)
        self.save_all(updated)
