"""Repository responsible for validation history storage."""

from __future__ import annotations

from pathlib import Path

from app.schemas.domain import ValidationEntry
from app.utils.file_ops import ensure_directory, read_json

from .base import BaseRepository

VALIDATION_DIRNAME = "validation"


class ValidationRepository(BaseRepository):
    """Persist validation history for individual nodes."""

    def validation_dir(self, tree_id: str) -> Path:
        return ensure_directory(self.resolve(tree_id, VALIDATION_DIRNAME))

    def history_path(self, tree_id: str, node_id: str) -> Path:
        filename = f"{node_id}.json"
        return self.validation_dir(tree_id) / filename

    def load_history(self, tree_id: str, node_id: str) -> list[ValidationEntry]:
        path = self.history_path(tree_id, node_id)
        if not path.exists():
            return []
        payload: list[dict[str, object]] = read_json(path)
        return [ValidationEntry.model_validate(entry) for entry in payload]

    def save_history(
        self, tree_id: str, node_id: str, entries: list[ValidationEntry]
    ) -> None:
        path = self.history_path(tree_id, node_id)
        data = [entry.model_dump(mode="json") for entry in entries]
        self.dump_payload(path, data)

    def append_entry(self, tree_id: str, node_id: str, entry: ValidationEntry) -> None:
        history = self.load_history(tree_id, node_id)
        history.append(entry)
        self.save_history(tree_id, node_id, history)
