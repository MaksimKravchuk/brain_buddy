"""Repository handling version snapshots for trees."""
from __future__ import annotations

from pathlib import Path

from app.exceptions import NotFoundError
from app.schemas.domain import VersionDocument
from app.utils.file_ops import ensure_directory

from .base import BaseRepository

VERSIONS_DIRNAME = "versions"


def _slugify_version_id(version_id: str) -> str:
    """Convert a version identifier into a filesystem-friendly filename."""

    return version_id.replace("::", "__").replace(":", "-")


class VersionRepository(BaseRepository):
    """Persist version snapshots on disk."""

    def versions_dir(self, tree_id: str) -> Path:
        return ensure_directory(self.resolve(tree_id, VERSIONS_DIRNAME))

    def version_path(self, tree_id: str, version_id: str) -> Path:
        filename = f"{_slugify_version_id(version_id)}.json"
        return self.versions_dir(tree_id) / filename

    def save(self, tree_id: str, version: VersionDocument) -> None:
        path = self.version_path(tree_id, version.id)
        self.dump_model(path, version)

    def load(self, tree_id: str, version_id: str) -> VersionDocument:
        path = self.version_path(tree_id, version_id)
        if not path.exists():
            raise NotFoundError("Version", version_id)
        return self.load_model(path, VersionDocument)

    def list_for_tree(self, tree_id: str) -> list[VersionDocument]:
        directory = self.versions_dir(tree_id)
        if not directory.exists():
            return []
        documents: list[VersionDocument] = []
        for path in sorted(directory.glob("*.json")):
            documents.append(self.load_model(path, VersionDocument))
        return documents

    def delete(self, tree_id: str, version_id: str) -> None:
        path = self.version_path(tree_id, version_id)
        if not path.exists():
            raise NotFoundError("Version", version_id)
        path.unlink()
