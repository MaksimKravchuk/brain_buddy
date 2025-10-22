"""Service responsible for snapshot and restore operations."""
from __future__ import annotations

from app.exceptions import NotFoundError
from app.repositories import TreeRepository, VersionRepository
from app.schemas.api import VersionCreateRequest
from app.schemas.domain import TreeDocument, TreeVersionRef, VersionDocument
from app.services.tree_service import TreeService
from app.utils.identifiers import generate_version_id
from app.utils.time import to_isoformat, utcnow


class VersionService:
    """Capture and restore version snapshots for trees."""

    def __init__(
        self, tree_repo: TreeRepository, version_repo: VersionRepository, tree_service: TreeService
    ) -> None:
        self.tree_repo = tree_repo
        self.version_repo = version_repo
        self.tree_service = tree_service

    def create_version(self, tree_id: str, payload: VersionCreateRequest) -> VersionDocument:
        tree = self.tree_repo.load(tree_id)
        now = utcnow()
        version_id = generate_version_id(tree.id)
        label = payload.label or f"Snapshot {to_isoformat(now)}"
        snapshot_tree = tree.model_copy(deep=True)
        version_doc = VersionDocument(
            id=version_id,
            label=label,
            captured_at=now,
            tree=snapshot_tree,
        )
        self.version_repo.save(tree_id, version_doc)

        version_ref = TreeVersionRef(id=version_id, label=label, created_at=now)
        updated_refs = [version_ref, *tree.version_refs]
        updated_tree = tree.model_copy(update={"version_refs": updated_refs})
        self.tree_service.touch_tree(updated_tree, timestamp=now)
        return version_doc

    def list_versions(self, tree_id: str) -> list[TreeVersionRef]:
        tree = self.tree_repo.load(tree_id)
        return tree.version_refs

    def load_version(self, tree_id: str, version_id: str) -> VersionDocument:
        # Ensure tree exists before loading version
        _ = self.tree_repo.load(tree_id)
        return self.version_repo.load(tree_id, version_id)

    def restore_version(self, tree_id: str, version_id: str) -> TreeDocument:
        version = self.load_version(tree_id, version_id)
        restored_tree = version.tree.model_copy(deep=True)
        now = utcnow()
        restored_tree = restored_tree.model_copy(update={"updated_at": now})
        # Ensure version references include the restored version metadata
        has_ref = any(ref.id == version_id for ref in restored_tree.version_refs)
        if not has_ref:
            restored_tree = restored_tree.model_copy(
                update={
                    "version_refs": [
                        TreeVersionRef(id=version.id, label=version.label, created_at=version.captured_at),
                        *restored_tree.version_refs,
                    ]
                }
            )
        self.tree_service.touch_tree(restored_tree, timestamp=now)
        return restored_tree

    def delete_version(self, tree_id: str, version_id: str) -> None:
        tree = self.tree_repo.load(tree_id)
        if not any(ref.id == version_id for ref in tree.version_refs):
            raise NotFoundError("Version", version_id)
        self.version_repo.delete(tree_id, version_id)
        updated_refs = [ref for ref in tree.version_refs if ref.id != version_id]
        updated_tree = tree.model_copy(update={"version_refs": updated_refs})
        self.tree_service.touch_tree(updated_tree)

