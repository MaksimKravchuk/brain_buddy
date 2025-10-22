"""Service responsible for snapshot and restore operations."""
from __future__ import annotations

import json
from typing import Iterable

from app.exceptions import NotFoundError
from app.repositories import TreeRepository, VersionRepository
from app.schemas.api import VersionCreateRequest
from app.schemas.domain import (
    NodeDocument,
    RelationDocument,
    TreeDocument,
    TreeVersionRef,
    VersionConflict,
    VersionDiffSummary,
    VersionDocument,
)
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
        previous_version = self._latest_version(tree_id)
        diff_summary, conflicts = self._build_diff(previous_version.tree if previous_version else None, tree)
        version_doc = VersionDocument(
            id=version_id,
            label=label,
            captured_at=now,
            author=payload.author,
            notes=payload.notes,
            diff=diff_summary,
            conflicts=conflicts,
            tree=snapshot_tree,
        )
        self.version_repo.save(tree_id, version_doc)

        version_ref = TreeVersionRef(
            id=version_id,
            label=label,
            created_at=now,
            author=payload.author,
            notes=payload.notes,
            diff_summary=diff_summary,
            conflict_count=len(conflicts),
        )
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
                        TreeVersionRef(
                            id=version.id,
                            label=version.label,
                            created_at=version.captured_at,
                            author=version.author,
                            notes=version.notes,
                            diff_summary=version.diff,
                            conflict_count=len(version.conflicts),
                        ),
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

    def export_tree(self, tree_id: str, version_id: str | None = None) -> tuple[str, bytes]:
        """Serialize a tree (current or snapshot) for download."""

        exported_at = utcnow()
        if version_id:
            version = self.load_version(tree_id, version_id)
            source_tree = version.tree
            source = {
                "type": "version",
                "version_id": version.id,
                "label": version.label,
                "captured_at": to_isoformat(version.captured_at),
            }
        else:
            source_tree = self.tree_repo.load(tree_id)
            source = {
                "type": "live",
                "tree_updated_at": to_isoformat(source_tree.updated_at),
            }

        payload = {
            "exported_at": to_isoformat(exported_at),
            "source": source,
            "tree": source_tree.model_dump(mode="json"),
        }
        filename = self._build_export_filename(tree_id, exported_at, version_id)
        content = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return filename, content

    def _latest_version(self, tree_id: str) -> VersionDocument | None:
        versions = self.version_repo.list_for_tree(tree_id)
        if not versions:
            return None
        return max(versions, key=lambda version: version.captured_at)

    def _build_diff(
        self, previous: TreeDocument | None, current: TreeDocument
    ) -> tuple[VersionDiffSummary, list[VersionConflict]]:
        prev_nodes = self._index_nodes(previous.nodes if previous else [])
        curr_nodes = self._index_nodes(current.nodes)
        prev_relations = self._index_relations(previous.relations if previous else [])
        curr_relations = self._index_relations(current.relations)

        node_ids_prev = set(prev_nodes)
        node_ids_curr = set(curr_nodes)
        relation_ids_prev = set(prev_relations)
        relation_ids_curr = set(curr_relations)

        nodes_added = len(node_ids_curr - node_ids_prev)
        nodes_removed = len(node_ids_prev - node_ids_curr)
        relations_added = len(relation_ids_curr - relation_ids_prev)
        relations_removed = len(relation_ids_prev - relation_ids_curr)

        node_conflicts: list[VersionConflict] = []
        for node_id in node_ids_curr & node_ids_prev:
            changed_fields = self._compare_nodes(prev_nodes[node_id], curr_nodes[node_id])
            if changed_fields:
                node_conflicts.append(
                    VersionConflict(entity_type="node", entity_id=node_id, fields=changed_fields)
                )

        relation_conflicts: list[VersionConflict] = []
        for relation_id in relation_ids_curr & relation_ids_prev:
            changed_fields = self._compare_relations(prev_relations[relation_id], curr_relations[relation_id])
            if changed_fields:
                relation_conflicts.append(
                    VersionConflict(entity_type="relation", entity_id=relation_id, fields=changed_fields)
                )

        diff_summary = VersionDiffSummary(
            nodes_added=nodes_added,
            nodes_removed=nodes_removed,
            nodes_modified=len(node_conflicts),
            relations_added=relations_added,
            relations_removed=relations_removed,
            relations_modified=len(relation_conflicts),
        )
        conflicts = [*node_conflicts, *relation_conflicts]
        return diff_summary, conflicts

    @staticmethod
    def _index_nodes(nodes: Iterable[NodeDocument]) -> dict[str, NodeDocument]:
        return {node.id: node for node in nodes}

    @staticmethod
    def _index_relations(relations: Iterable[RelationDocument]) -> dict[str, RelationDocument]:
        return {relation.id: relation for relation in relations}

    @staticmethod
    def _compare_nodes(previous: NodeDocument, current: NodeDocument) -> list[str]:
        changed: list[str] = []
        if previous.label != current.label:
            changed.append("label")
        if previous.position != current.position:
            changed.append("position")
        if previous.visual != current.visual:
            changed.append("visual")
        if previous.validation != current.validation:
            changed.append("validation")
        if previous.extra != current.extra:
            changed.append("extra")
        return changed

    @staticmethod
    def _compare_relations(previous: RelationDocument, current: RelationDocument) -> list[str]:
        changed: list[str] = []
        if previous.source_id != current.source_id:
            changed.append("source_id")
        if previous.target_id != current.target_id:
            changed.append("target_id")
        if previous.question_label != current.question_label:
            changed.append("question_label")
        if previous.notes != current.notes:
            changed.append("notes")
        return changed

    @staticmethod
    def _build_export_filename(tree_id: str, exported_at, version_id: str | None) -> str:
        timestamp = to_isoformat(exported_at).replace(":", "").replace("-", "")
        suffix = version_id.split("::")[-1] if version_id else "latest"
        return f"{tree_id}_{suffix}_{timestamp}.json"
