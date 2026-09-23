"""Idempotent CRT create and full-snapshot update commands."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from app.exceptions import (
    ConflictError,
    IdempotencyConflictError,
    IdempotencyReceiptExpiredError,
    IdempotencyReceiptUnavailableError,
    NotFoundError,
    PendingCommandError,
    StaleRevisionError,
    ValidationFailure,
)
from app.repositories.crt_command import (
    CRT_COMMAND_RETENTION,
    CrtCommandReceipt,
    CrtCommandRepository,
)
from app.schemas.api import (
    TreeCreateRequest,
    TreeDetailResponse,
    TreeImportRequest,
    TreeUpdateRequest,
)
from app.schemas.domain import TreeDocument
from app.services.tree_service import SUPPORTED_TREE_SCHEMA_VERSIONS, TreeService
from app.utils.identifiers import ensure_acyclic
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CrtCommandResult:
    """The canonical body and status returned by a CRT mutation."""

    status_code: int
    response: TreeDetailResponse | None
    replayed: bool = False


class CrtCommandService:
    """Coordinate durable receipts with the existing file-backed tree store."""

    def __init__(
        self,
        command_repo: CrtCommandRepository,
        tree_service: TreeService,
        owner_is_live: Callable[[str], bool] | None = None,
    ) -> None:
        self.command_repo = command_repo
        self.tree_service = tree_service
        self._owner_is_live = owner_is_live

    def _ensure_live_owner(self, owner_id: str, *, required: bool) -> None:
        if required and (
            self._owner_is_live is None or not self._owner_is_live(owner_id)
        ):
            raise NotFoundError("Account", owner_id)

    def create_tree(
        self,
        payload: TreeCreateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        normalized_route: str,
        require_live_owner: bool = False,
    ) -> CrtCommandResult:
        command_payload = self._owner_safe_payload(payload)
        request_hash = self._request_hash(command_payload)
        key_digest = self._key_digest(idempotency_key)
        schema_version = self._validate_create_schema(payload)
        resource_id = self._resource_id(owner_id, key_digest)
        with self.command_repo.command_lock(owner_id):
            self._ensure_live_owner(owner_id, required=require_live_owner)
            existing = self.command_repo.get(owner_id=owner_id, key_digest=key_digest)
            if existing is not None:
                return self._existing_result(
                    existing,
                    command="create",
                    normalized_route=normalized_route,
                    request_hash=request_hash,
                    payload=command_payload,
                    schema_version=schema_version,
                    expected_owner_id=owner_id,
                    expected_resource_id=resource_id,
                    expected_base_revision=None,
                    expected_target_revision=1,
                    expected_response_status=201,
                )

            target = self.tree_service.prepare_create_tree(
                cast(TreeCreateRequest, command_payload),
                owner_id=owner_id,
                tree_id=resource_id,
                command_id=key_digest,
                schema_version=schema_version,
            )
            self._validate_snapshot_id_continuity(target)
            receipt = CrtCommandReceipt(
                owner_id=owner_id,
                key_digest=key_digest,
                command="create",
                normalized_route=normalized_route,
                request_hash=request_hash,
                state="pending",
                resource_id=resource_id,
                base_revision=None,
                target_revision=1,
                response_status=None,
                response_json=None,
                created_at=utcnow(),
                committed_at=None,
                expires_at=utcnow() + CRT_COMMAND_RETENTION,
                pending_target_snapshot=self._encode_target_snapshot(target),
            )
            self.command_repo.insert_pending(receipt)
            tree = self.tree_service.persist_prepared_create_tree(target)
            response = self.tree_service.to_response(tree)
            self.command_repo.commit(
                owner_id=owner_id,
                key_digest=key_digest,
                response_status=201,
                response_json=self._response_json(response),
            )
            return CrtCommandResult(status_code=201, response=response)

    def update_tree(
        self,
        tree_id: str,
        payload: TreeUpdateRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        normalized_route: str,
        require_live_owner: bool = False,
    ) -> CrtCommandResult:
        normalized_route = self._resource_route(normalized_route, tree_id)
        self._validate_update_schema(payload)
        if payload.expected_revision is None:
            raise ValidationFailure(
                "Expected revision is required for CRT updates.",
                detail={"reason": "expected_revision_required"},
            )
        key_digest = self._key_digest(idempotency_key)
        command_payload = self._owner_safe_payload(payload)
        request_hash = self._request_hash(command_payload)
        with self.command_repo.command_lock(owner_id):
            self._ensure_live_owner(owner_id, required=require_live_owner)
            existing = self.command_repo.get(owner_id=owner_id, key_digest=key_digest)
            if existing is not None:
                return self._existing_result(
                    existing,
                    command="update",
                    normalized_route=normalized_route,
                    request_hash=request_hash,
                    payload=command_payload,
                    expected_owner_id=owner_id,
                    expected_resource_id=tree_id,
                    expected_base_revision=payload.expected_revision,
                    expected_target_revision=payload.expected_revision + 1,
                    expected_response_status=200,
                )

            self._ensure_no_pending_command(
                owner_id=owner_id, resource_id=tree_id, key_digest=key_digest
            )
            current = self.tree_service.get_tree_for_owner(tree_id, owner_id=owner_id)
            target = self.tree_service.prepare_update_tree(
                tree_id,
                cast(TreeUpdateRequest, command_payload),
                owner_id=owner_id,
                command_id=key_digest,
                current_tree=current,
            )
            self._validate_snapshot_id_continuity(target, current=current)
            receipt = CrtCommandReceipt(
                owner_id=owner_id,
                key_digest=key_digest,
                command="update",
                normalized_route=normalized_route,
                request_hash=request_hash,
                state="pending",
                resource_id=tree_id,
                base_revision=current.revision,
                target_revision=current.revision + 1,
                response_status=None,
                response_json=None,
                created_at=utcnow(),
                committed_at=None,
                expires_at=utcnow() + CRT_COMMAND_RETENTION,
                pending_target_snapshot=self._encode_target_snapshot(target),
            )
            self.command_repo.insert_pending(receipt)
            updated = self.tree_service.persist_prepared_update_tree(target)
            response = self.tree_service.to_response(updated)
            self.command_repo.commit(
                owner_id=owner_id,
                key_digest=key_digest,
                response_status=200,
                response_json=self._response_json(response),
            )
            return CrtCommandResult(status_code=200, response=response)

    def import_tree(
        self,
        payload: TreeImportRequest,
        *,
        owner_id: str,
        idempotency_key: str,
        normalized_route: str,
        require_live_owner: bool = False,
    ) -> CrtCommandResult:
        """Import one validated tree through the durable command protocol."""

        self._validate_import_payload(payload)
        key_digest = self._key_digest(idempotency_key)
        imported_payload = self._remap_import_payload(payload, owner_id, key_digest)
        request_hash = self._request_hash(imported_payload)
        resource_id = self._resource_id(owner_id, key_digest)
        with self.command_repo.command_lock(owner_id):
            self._ensure_live_owner(owner_id, required=require_live_owner)
            existing = self.command_repo.get(owner_id=owner_id, key_digest=key_digest)
            if existing is not None:
                return self._existing_result(
                    existing,
                    command="import",
                    normalized_route=normalized_route,
                    request_hash=request_hash,
                    payload=imported_payload,
                    schema_version=imported_payload.tree.schema_version,
                    expected_owner_id=owner_id,
                    expected_resource_id=resource_id,
                    expected_base_revision=None,
                    expected_target_revision=1,
                    expected_response_status=201,
                )

            target = self.tree_service.prepare_import_tree(
                imported_payload.tree,
                owner_id=owner_id,
                tree_id=resource_id,
                command_id=key_digest,
            )
            self._validate_snapshot_id_continuity(target)
            receipt = CrtCommandReceipt(
                owner_id=owner_id,
                key_digest=key_digest,
                command="import",
                normalized_route=normalized_route,
                request_hash=request_hash,
                state="pending",
                resource_id=resource_id,
                base_revision=None,
                target_revision=1,
                response_status=None,
                response_json=None,
                created_at=utcnow(),
                committed_at=None,
                expires_at=utcnow() + CRT_COMMAND_RETENTION,
                pending_target_snapshot=self._encode_target_snapshot(target),
            )
            self.command_repo.insert_pending(receipt)
            tree = self.tree_service.persist_prepared_import_tree(target)
            response = self.tree_service.to_response(tree)
            self.command_repo.commit(
                owner_id=owner_id,
                key_digest=key_digest,
                response_status=201,
                response_json=self._response_json(response),
            )
            return CrtCommandResult(status_code=201, response=response)

    def delete_tree(
        self,
        tree_id: str,
        *,
        expected_revision: int,
        owner_id: str,
        idempotency_key: str,
        normalized_route: str,
        require_live_owner: bool = False,
    ) -> CrtCommandResult:
        """Delete an owner tree and retain only a content-free replay tombstone."""

        normalized_route = self._resource_route(normalized_route, tree_id)
        key_digest = self._key_digest(idempotency_key)
        request_hash = self._request_hash(
            {"tree_id": tree_id, "expected_revision": expected_revision}
        )
        with self.command_repo.command_lock(owner_id):
            self._ensure_live_owner(owner_id, required=require_live_owner)
            existing = self.command_repo.get(owner_id=owner_id, key_digest=key_digest)
            if existing is not None:
                return self._existing_delete_result(
                    existing,
                    normalized_route=normalized_route,
                    request_hash=request_hash,
                    expected_owner_id=owner_id,
                    expected_resource_id=tree_id,
                    expected_base_revision=expected_revision,
                )

            self._ensure_no_pending_command(
                owner_id=owner_id, resource_id=tree_id, key_digest=key_digest
            )
            current = self.tree_service.get_tree_for_owner(tree_id, owner_id=owner_id)
            if current.revision != expected_revision:
                raise StaleRevisionError(
                    "Tree",
                    tree_id,
                    current_revision=current.revision,
                    current_updated_at=current.updated_at,
                )
            receipt = CrtCommandReceipt(
                owner_id=owner_id,
                key_digest=key_digest,
                command="delete",
                normalized_route=normalized_route,
                request_hash=request_hash,
                state="pending",
                resource_id=tree_id,
                base_revision=current.revision,
                target_revision=None,
                response_status=None,
                response_json=None,
                created_at=utcnow(),
                committed_at=None,
                expires_at=utcnow() + CRT_COMMAND_RETENTION,
            )
            self.command_repo.insert_pending(receipt)
            self.tree_service.delete_tree(
                tree_id,
                owner_id=owner_id,
                expected_revision=expected_revision,
            )
            self.command_repo.delete_for_tree_except(
                owner_id=owner_id, resource_id=tree_id, key_digest=key_digest
            )
            self.command_repo.commit(
                owner_id=owner_id,
                key_digest=key_digest,
                response_status=204,
                response_json="{}",
            )
            return CrtCommandResult(status_code=204, response=None)

    @staticmethod
    def _validate_receipt_identity(
        receipt: CrtCommandReceipt,
        *,
        expected_owner_id: str,
        expected_resource_id: str,
        expected_base_revision: int | None,
        expected_target_revision: int | None,
    ) -> None:
        """Validate immutable receipt identity before any recovery side effect."""

        if (
            receipt.owner_id != expected_owner_id
            or receipt.resource_id != expected_resource_id
            or receipt.base_revision != expected_base_revision
            or receipt.target_revision != expected_target_revision
        ):
            raise IdempotencyReceiptUnavailableError()

    def _existing_delete_result(
        self,
        receipt: CrtCommandReceipt,
        *,
        normalized_route: str,
        request_hash: str,
        expected_owner_id: str,
        expected_resource_id: str,
        expected_base_revision: int,
    ) -> CrtCommandResult:
        if (
            receipt.command != "delete"
            or receipt.normalized_route != normalized_route
            or receipt.request_hash != request_hash
        ):
            raise IdempotencyConflictError()
        self._validate_receipt_identity(
            receipt,
            expected_owner_id=expected_owner_id,
            expected_resource_id=expected_resource_id,
            expected_base_revision=expected_base_revision,
            expected_target_revision=None,
        )
        if receipt.state == "pending":
            return self._reconcile_pending_delete(receipt)
        if receipt.state == "expired" or receipt.expires_at <= utcnow():
            raise IdempotencyReceiptExpiredError()
        if receipt.response_status != 204 or receipt.response_json != "{}":
            raise ConflictError("CRT command", receipt.resource_id)
        return CrtCommandResult(status_code=204, response=None, replayed=True)

    def _reconcile_pending_delete(self, receipt: CrtCommandReceipt) -> CrtCommandResult:
        try:
            current = self.tree_service.get_tree(receipt.resource_id)
        except NotFoundError:
            self.tree_service.remove_stale_tree_state(receipt.resource_id)
        else:
            if current.owner_id != receipt.owner_id:
                raise ConflictError(
                    "CRT command",
                    receipt.resource_id,
                    "A pending CRT delete cannot reconcile a foreign tree.",
                )
            try:
                self.tree_service.delete_tree(
                    receipt.resource_id,
                    owner_id=receipt.owner_id,
                    expected_revision=self._validated_delete_base_revision(receipt),
                )
            except NotFoundError:
                self.tree_service.remove_stale_tree_state(receipt.resource_id)
            except StaleRevisionError as exc:
                raise ConflictError(
                    "CRT command",
                    receipt.resource_id,
                    "A pending CRT delete cannot be reconciled safely.",
                ) from exc
        self.command_repo.delete_for_tree_except(
            owner_id=receipt.owner_id,
            resource_id=receipt.resource_id,
            key_digest=receipt.key_digest,
        )
        self.command_repo.commit(
            owner_id=receipt.owner_id,
            key_digest=receipt.key_digest,
            response_status=204,
            response_json="{}",
        )
        return CrtCommandResult(status_code=204, response=None, replayed=True)

    def _existing_result(
        self,
        receipt: CrtCommandReceipt,
        *,
        command: str,
        normalized_route: str,
        request_hash: str,
        payload: TreeCreateRequest | TreeUpdateRequest | TreeImportRequest,
        expected_owner_id: str,
        expected_resource_id: str,
        expected_base_revision: int | None,
        expected_target_revision: int,
        expected_response_status: int,
        schema_version: int | None = None,
    ) -> CrtCommandResult:
        if (
            receipt.command != command
            or receipt.normalized_route != normalized_route
            or receipt.request_hash != request_hash
        ):
            raise IdempotencyConflictError()
        self._validate_receipt_identity(
            receipt,
            expected_owner_id=expected_owner_id,
            expected_resource_id=expected_resource_id,
            expected_base_revision=expected_base_revision,
            expected_target_revision=expected_target_revision,
        )
        if receipt.state == "pending":
            reconciled = self._reconcile_pending(
                receipt, payload=payload, schema_version=schema_version
            )
            if reconciled is not None:
                return reconciled
            raise ConflictError(
                "CRT command",
                receipt.resource_id,
                "A prior CRT command is still pending reconciliation; retry later.",
            )
        if receipt.state == "expired" or receipt.expires_at <= utcnow():
            raise IdempotencyReceiptExpiredError()
        if receipt.response_status != expected_response_status:
            raise IdempotencyReceiptUnavailableError()
        if receipt.response_json is None:
            raise IdempotencyReceiptUnavailableError()
        if receipt.response_status is None:  # pragma: no cover - schema invariant
            raise IdempotencyReceiptUnavailableError()
        try:
            response = TreeDetailResponse.model_validate(
                json.loads(receipt.response_json)
            )
        except (TypeError, ValueError) as exc:
            raise IdempotencyReceiptUnavailableError() from exc
        if (
            response.id != expected_resource_id
            or response.owner_id != expected_owner_id
            or response.revision != expected_target_revision
        ):
            raise IdempotencyReceiptUnavailableError()
        return CrtCommandResult(
            status_code=receipt.response_status,
            response=response,
            replayed=True,
        )

    def reconcile_pending_commands(self) -> int:
        """Reconcile pending commands whose durable marker proves the write."""

        reconciled = 0
        for candidate in self.command_repo.list_pending():
            try:
                with self.command_repo.command_lock(candidate.owner_id):
                    receipt = self.command_repo.get(
                        owner_id=candidate.owner_id, key_digest=candidate.key_digest
                    )
                    if receipt is None or receipt.state != "pending":
                        continue
                    try:
                        tree = self.tree_service.get_tree_for_owner(
                            receipt.resource_id, owner_id=receipt.owner_id
                        )
                    except NotFoundError:
                        if receipt.command == "delete":
                            self._reconcile_pending_delete(receipt)
                            reconciled += 1
                            continue
                        result = self._reconcile_missing_tree(
                            receipt, payload=None, schema_version=None
                        )
                        if result is not None:
                            reconciled += 1
                        continue

                    if receipt.command in {"create", "import"}:
                        result = self._reconcile_existing_create(receipt, tree)
                    elif receipt.command == "update":
                        result = self._reconcile_existing_update_marker(receipt, tree)
                        if result is None:
                            result = self._reconcile_existing_update(
                                receipt, tree, payload=None
                            )
                    elif receipt.command == "delete":
                        result = (
                            self._reconcile_pending_delete(receipt)
                            if tree.revision == receipt.base_revision
                            else None
                        )
                    else:
                        result = None
                    if result is not None:
                        reconciled += 1
            except Exception:
                # A malformed receipt is isolated to its own retry window. Keep
                # it pending and continue startup maintenance for other owners.
                logger.warning(
                    "Deferred reconciliation of one CRT pending command",
                    exc_info=False,
                )
        return reconciled

    def _reconcile_existing_update_marker(
        self, receipt: CrtCommandReceipt, tree: Any
    ) -> CrtCommandResult | None:
        if (
            tree.last_command_id != receipt.key_digest
            or receipt.target_revision is None
            or tree.revision != receipt.target_revision
        ):
            return None
        self._validate_marked_tree(receipt, tree)
        return self._commit_reconciled(receipt, tree)

    def _ensure_no_pending_command(
        self, *, owner_id: str, resource_id: str, key_digest: str
    ) -> None:
        pending = self.command_repo.get_pending_for_resource(
            owner_id=owner_id,
            resource_id=resource_id,
            exclude_key_digest=key_digest,
        )
        if pending is not None:
            raise PendingCommandError(resource_id)

    def _reconcile_pending(
        self,
        receipt: CrtCommandReceipt,
        *,
        payload: TreeCreateRequest | TreeUpdateRequest | TreeImportRequest,
        schema_version: int | None,
    ) -> CrtCommandResult | None:
        """Recover a pending command without guessing across crash states."""

        try:
            tree = self.tree_service.get_tree_for_owner(
                receipt.resource_id, owner_id=receipt.owner_id
            )
        except NotFoundError:
            return self._reconcile_missing_tree(
                receipt, payload=payload, schema_version=schema_version
            )

        if receipt.command in {"create", "import"}:
            return self._reconcile_existing_create(receipt, tree)

        if receipt.command != "update":
            return None
        return self._reconcile_existing_update(receipt, tree, payload)

    def _reconcile_missing_tree(
        self,
        receipt: CrtCommandReceipt,
        *,
        payload: (
            TreeCreateRequest | TreeUpdateRequest | TreeImportRequest | None
        ) = None,
        schema_version: int | None = None,
    ) -> CrtCommandResult | None:
        if receipt.command not in {"create", "import"}:
            return None
        target = self._decode_target_snapshot(receipt)
        if receipt.command == "create":
            tree = self.tree_service.persist_prepared_create_tree(target)
        else:
            tree = self.tree_service.persist_prepared_import_tree(target)
        return self._commit_reconciled(receipt, tree)

    def _reconcile_existing_create(
        self, receipt: CrtCommandReceipt, tree: Any
    ) -> CrtCommandResult | None:
        if (
            tree.last_command_id != receipt.key_digest
            or receipt.target_revision is None
            or tree.revision != receipt.target_revision
        ):
            return None
        self._validate_marked_tree(receipt, tree)
        return self._commit_reconciled(receipt, tree)

    def _reconcile_existing_update(
        self,
        receipt: CrtCommandReceipt,
        tree: Any,
        payload: TreeCreateRequest | TreeUpdateRequest | TreeImportRequest | None,
    ) -> CrtCommandResult | None:
        self._validate_live_tree_shape(receipt, tree)
        if (
            tree.last_command_id == receipt.key_digest
            and receipt.target_revision is not None
            and tree.revision == receipt.target_revision
        ):
            self._validate_marked_tree(receipt, tree)
            return self._commit_reconciled(receipt, tree)
        if tree.last_command_id is not None:
            prior = self.command_repo.get(
                owner_id=receipt.owner_id, key_digest=tree.last_command_id
            )
            if prior is None or prior.state != "committed":
                return None
        if receipt.base_revision is None or tree.revision != receipt.base_revision:
            return None
        target = self._decode_target_snapshot(receipt)
        updated = self.tree_service.persist_prepared_update_tree(target)
        return self._commit_reconciled(receipt, updated)

    def _commit_reconciled(
        self, receipt: CrtCommandReceipt, tree: Any
    ) -> CrtCommandResult:
        """Commit the exact response after a deterministic tree recovery."""

        # The tree file is authoritative after a marker match or recovery;
        # republish the derived index before reconstructing the response.
        self.tree_service._sync_index(tree)
        response = self.tree_service.to_response(tree)
        status_code = 201 if receipt.command in {"create", "import"} else 200
        self.command_repo.commit(
            owner_id=receipt.owner_id,
            key_digest=receipt.key_digest,
            response_status=status_code,
            response_json=self._response_json(response),
        )
        return CrtCommandResult(
            status_code=status_code, response=response, replayed=True
        )

    @staticmethod
    def _owner_safe_payload(
        payload: TreeCreateRequest | TreeUpdateRequest,
    ) -> TreeCreateRequest | TreeUpdateRequest:
        if not payload.name.strip():
            raise ValidationFailure(
                "Tree name must not be empty.",
                detail={"reason": "empty_tree_name"},
            )
        nodes = []
        for node in payload.nodes:
            label = node.label.strip()
            if not label:
                raise ValidationFailure(
                    "Card labels must not be empty.",
                    detail={"reason": "empty_card_label"},
                )
            nodes.append(node.model_copy(update={"label": label}))
        metadata = payload.metadata
        if metadata is not None:
            metadata = metadata.model_copy(update={"owner_id": None})
        return payload.model_copy(
            update={
                "name": payload.name.strip(),
                "owner_id": None,
                "metadata": metadata,
                "nodes": nodes,
            },
            deep=True,
        )

    @staticmethod
    def _validate_import_payload(payload: TreeImportRequest) -> None:
        tree = payload.tree
        if tree.schema_version not in SUPPORTED_TREE_SCHEMA_VERSIONS:
            raise ValidationFailure(
                "Unsupported tree schema version.",
                detail={
                    "reason": "unsupported_schema_version",
                    "schema_version": tree.schema_version,
                },
            )
        if tree.metadata.version != tree.schema_version:
            raise ValidationFailure(
                "Tree schema version disagrees with metadata version.",
                detail={
                    "reason": "schema_version_mismatch",
                    "schema_version": tree.schema_version,
                    "metadata_version": tree.metadata.version,
                },
            )
        if not tree.name.strip():
            raise ValidationFailure(
                "Tree name must not be empty.",
                detail={"reason": "empty_tree_name"},
            )
        node_ids = [node.id for node in tree.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValidationFailure(
                "Imported node identifiers must be unique.",
                detail={"reason": "duplicate_node_id"},
            )
        if any(not node.label.strip() for node in tree.nodes):
            raise ValidationFailure(
                "Card labels must not be empty.",
                detail={"reason": "empty_card_label"},
            )
        relation_ids = [relation.id for relation in tree.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValidationFailure(
                "Imported relation identifiers must be unique.",
                detail={"reason": "duplicate_relation_id"},
            )
        node_id_set = set(node_ids)
        pairs: list[tuple[str, str]] = []
        seen_pairs: set[tuple[str, str]] = set()
        for relation in tree.relations:
            pair = (relation.source_node_id, relation.target_node_id)
            if pair[0] not in node_id_set or pair[1] not in node_id_set:
                raise ValidationFailure(
                    "Relation references an unknown node.",
                    detail={"reason": "missing_relation_endpoint"},
                )
            if pair in seen_pairs:
                raise ValidationFailure(
                    "A link already exists between these nodes.",
                    detail={"reason": "duplicate_relation"},
                )
            seen_pairs.add(pair)
            pairs.append(pair)
        ensure_acyclic(pairs)

    @staticmethod
    def _stable_uuid_v4(seed: str) -> str:
        raw = bytearray(hashlib.sha256(seed.encode("utf-8")).digest()[:16])
        raw[6] = (raw[6] & 0x0F) | 0x40
        raw[8] = (raw[8] & 0x3F) | 0x80
        return str(uuid.UUID(bytes=bytes(raw)))

    @staticmethod
    def _has_canonical_uuid_v4(value: str, *, prefix: str) -> bool:
        if not value.startswith(prefix):
            return False
        suffix = value[len(prefix) :]
        try:
            parsed = uuid.UUID(suffix)
        except (AttributeError, ValueError):
            return False
        return parsed.version == 4 and suffix == str(parsed)

    @classmethod
    def _validate_snapshot_id_continuity(
        cls,
        target: TreeDocument,
        *,
        current: TreeDocument | None = None,
    ) -> None:
        existing_node_ids = {node.id for node in current.nodes} if current else set()
        for node in target.nodes:
            if node.id not in existing_node_ids and not cls._has_canonical_uuid_v4(
                node.id, prefix="node_"
            ):
                raise ValidationFailure(
                    "New card identifiers must use the CRT UUID-v4 form.",
                    detail={"reason": "invalid_node_id"},
                )

        existing_relations = (
            {relation.id: relation for relation in current.relations} if current else {}
        )
        for relation in target.relations:
            previous = existing_relations.get(relation.id)
            if previous is None:
                if not cls._has_canonical_uuid_v4(relation.id, prefix="relation_"):
                    raise ValidationFailure(
                        "New relation identifiers must use the CRT UUID-v4 form.",
                        detail={"reason": "invalid_relation_id"},
                    )
                continue
            if (
                previous.source_id != relation.source_id
                or previous.target_id != relation.target_id
            ):
                raise ValidationFailure(
                    "An existing relation identifier cannot replace another link.",
                    detail={"reason": "relation_id_reassigned"},
                )

    @staticmethod
    def _remap_import_payload(
        payload: TreeImportRequest, owner_id: str, key_digest: str
    ) -> TreeImportRequest:
        source = payload.tree
        node_mapping = {
            node.id: "node_"
            + CrtCommandService._stable_uuid_v4(
                f"{owner_id}:{key_digest}:node:{index}:{node.id}"
            )
            for index, node in enumerate(source.nodes)
        }
        nodes = [
            node.model_copy(
                update={"id": node_mapping[node.id], "label": node.label.strip()}
            )
            for node in source.nodes
        ]
        relations = [
            relation.model_copy(
                update={
                    "id": f"relation_{CrtCommandService._stable_uuid_v4(f'{owner_id}:{key_digest}:relation:{index}:{relation.id}')}",
                    "source_node_id": node_mapping[relation.source_node_id],
                    "target_node_id": node_mapping[relation.target_node_id],
                }
            )
            for index, relation in enumerate(source.relations)
        ]
        return TreeImportRequest(
            tree=source.model_copy(
                update={
                    "name": source.name.strip(),
                    "nodes": nodes,
                    "relations": relations,
                    "metadata": source.metadata.model_copy(update={"owner_id": None}),
                    "owner_id": None,
                },
                deep=True,
            )
        )

    @staticmethod
    def _resource_id(owner_id: str, key_digest: str) -> str:
        return f"tree_{uuid.uuid5(uuid.NAMESPACE_URL, f'{owner_id}:{key_digest}').hex[:12]}"

    @staticmethod
    def _validate_create_schema(payload: TreeCreateRequest) -> int:
        top_level = payload.schema_version
        metadata_version = (
            payload.metadata.version if payload.metadata is not None else 1
        )
        if (
            top_level is not None
            and payload.metadata is not None
            and top_level != metadata_version
        ):
            raise ValidationFailure(
                "Tree schema version disagrees with metadata version.",
                detail={
                    "reason": "schema_version_mismatch",
                    "schema_version": top_level,
                    "metadata_version": metadata_version,
                },
            )
        version = top_level if top_level is not None else metadata_version
        if version not in SUPPORTED_TREE_SCHEMA_VERSIONS:
            raise ValidationFailure(
                "Unsupported tree schema version.",
                detail={
                    "reason": "unsupported_schema_version",
                    "schema_version": version,
                },
            )
        return version

    @staticmethod
    def _validate_update_schema(payload: TreeUpdateRequest) -> None:
        if payload.schema_version != payload.metadata.version:
            raise ValidationFailure(
                "Tree schema version disagrees with metadata version.",
                detail={
                    "reason": "schema_version_mismatch",
                    "schema_version": payload.schema_version,
                    "metadata_version": payload.metadata.version,
                },
            )
        if payload.schema_version not in SUPPORTED_TREE_SCHEMA_VERSIONS:
            raise ValidationFailure(
                "Unsupported tree schema version.",
                detail={
                    "reason": "unsupported_schema_version",
                    "schema_version": payload.schema_version,
                },
            )

    @staticmethod
    def _key_digest(key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    @staticmethod
    def _request_hash(payload: Any) -> str:
        value = (
            payload.model_dump(mode="json")
            if hasattr(payload, "model_dump")
            else payload
        )
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _encode_target_snapshot(tree: TreeDocument) -> str:
        """Persist only the canonical tree target needed for recovery."""

        return json.dumps(
            tree.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    def _decode_target_snapshot(receipt: CrtCommandReceipt) -> TreeDocument:
        if receipt.pending_target_snapshot is None:
            raise IdempotencyReceiptUnavailableError()
        try:
            tree = TreeDocument.model_validate(
                json.loads(receipt.pending_target_snapshot)
            )
        except (TypeError, ValueError) as exc:
            raise IdempotencyReceiptUnavailableError() from exc
        CrtCommandService._validate_recovery_tree(receipt, tree)
        return tree

    @staticmethod
    def _validate_recovery_tree(  # noqa: PLR0912
        receipt: CrtCommandReceipt, tree: TreeDocument
    ) -> None:
        """Fail closed unless a recovery tree is a complete canonical target."""

        try:
            if tree.id != receipt.resource_id:
                raise ValueError("tree id mismatch")
            if not tree.title.strip():
                raise ValueError("tree title is empty")
            if any(not node.label.strip() for node in tree.nodes):
                raise ValueError("card label is empty")
            if tree.owner_id != receipt.owner_id:
                raise ValueError("tree owner mismatch")
            if tree.last_command_id != receipt.key_digest:
                raise ValueError("tree command marker mismatch")
            if tree.schema_version not in SUPPORTED_TREE_SCHEMA_VERSIONS:
                raise ValueError("unsupported tree schema")
            if not isinstance(tree.metadata, dict):
                raise ValueError("tree metadata is missing")
            if tree.metadata.get("version") != tree.schema_version:
                raise ValueError("tree metadata schema mismatch")
            metadata_owner = tree.metadata.get("owner_id")
            if metadata_owner is not None and metadata_owner != receipt.owner_id:
                raise ValueError("tree metadata owner mismatch")

            node_ids = [node.id for node in tree.nodes]
            if len(node_ids) != len(set(node_ids)):
                raise ValueError("duplicate node id")
            relation_ids = [relation.id for relation in tree.relations]
            if len(relation_ids) != len(set(relation_ids)):
                raise ValueError("duplicate relation id")
            node_id_set = set(node_ids)
            pairs: list[tuple[str, str]] = []
            seen_pairs: set[tuple[str, str]] = set()
            for relation in tree.relations:
                pair = (relation.source_id, relation.target_id)
                if pair[0] not in node_id_set or pair[1] not in node_id_set:
                    raise ValueError("relation endpoint missing")
                if pair[0] == pair[1]:
                    raise ValueError("relation self-link")
                if pair in seen_pairs:
                    raise ValueError("duplicate relation")
                seen_pairs.add(pair)
                pairs.append(pair)
            ensure_acyclic(pairs)

            if receipt.command in {"create", "import"}:
                if (
                    receipt.base_revision is not None
                    or receipt.target_revision != 1
                    or tree.revision != 1
                ):
                    raise ValueError("invalid create/import revisions")
            elif receipt.command == "update":
                if (
                    not isinstance(receipt.base_revision, int)
                    or receipt.base_revision < 1
                    or receipt.target_revision != receipt.base_revision + 1
                    or tree.revision != receipt.target_revision
                ):
                    raise ValueError("invalid update revisions")
            else:
                raise ValueError("invalid recovery command")
        except (TypeError, ValueError, ValidationFailure) as exc:
            raise IdempotencyReceiptUnavailableError() from exc

    @staticmethod
    def _validate_live_tree_shape(
        receipt: CrtCommandReceipt, tree: TreeDocument
    ) -> None:
        """Validate a live tree before it can participate in recovery."""

        try:
            if tree.id != receipt.resource_id or tree.owner_id != receipt.owner_id:
                raise ValueError("live tree identity mismatch")
            if tree.schema_version not in SUPPORTED_TREE_SCHEMA_VERSIONS:
                raise ValueError("unsupported live tree schema")
            if not isinstance(tree.metadata, dict):
                raise ValueError("live tree metadata is missing")
            if tree.metadata.get("version") != tree.schema_version:
                raise ValueError("live tree metadata schema mismatch")
            metadata_owner = tree.metadata.get("owner_id")
            if metadata_owner is not None and metadata_owner != receipt.owner_id:
                raise ValueError("live tree metadata owner mismatch")
            node_ids = [node.id for node in tree.nodes]
            if len(node_ids) != len(set(node_ids)):
                raise ValueError("duplicate live node id")
            relation_ids = [relation.id for relation in tree.relations]
            if len(relation_ids) != len(set(relation_ids)):
                raise ValueError("duplicate live relation id")
            node_id_set = set(node_ids)
            pairs = [
                (relation.source_id, relation.target_id) for relation in tree.relations
            ]
            if any(
                source not in node_id_set
                or target not in node_id_set
                or source == target
                for source, target in pairs
            ):
                raise ValueError("invalid live relation endpoint")
            if len(pairs) != len(set(pairs)):
                raise ValueError("duplicate live relation")
            ensure_acyclic(pairs)
        except (TypeError, ValueError, ValidationFailure) as exc:
            raise IdempotencyReceiptUnavailableError() from exc

    def _validate_marked_tree(
        self, receipt: CrtCommandReceipt, tree: TreeDocument
    ) -> None:
        target = self._decode_target_snapshot(receipt)
        self._validate_live_tree_shape(receipt, tree)
        if target.model_dump(mode="json") != tree.model_dump(mode="json"):
            raise IdempotencyReceiptUnavailableError()

    @staticmethod
    def _validated_delete_base_revision(receipt: CrtCommandReceipt) -> int:
        if (
            receipt.command != "delete"
            or not isinstance(receipt.base_revision, int)
            or receipt.base_revision < 1
            or receipt.target_revision is not None
            or receipt.pending_target_snapshot is not None
        ):
            raise IdempotencyReceiptUnavailableError()
        return receipt.base_revision

    @staticmethod
    def _response_json(response: TreeDetailResponse) -> str:
        return json.dumps(
            response.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )

    @staticmethod
    def _resource_route(normalized_route: str, resource_id: str) -> str:
        """Scope resource mutations by the addressed resource, not a template."""

        return f"{normalized_route}:{resource_id}"


__all__ = ["CrtCommandResult", "CrtCommandService"]
