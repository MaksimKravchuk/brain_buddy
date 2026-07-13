"""FastAPI routes implementing the Brain Buddy API contracts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.api.contracts import error_responses
from app.api.dependencies import (
    get_current_user,
    get_node_service,
    get_relation_service,
    get_tree_service,
    get_validation_service,
    get_version_service,
)
from app.schemas import (
    AiFeedbackRequest,
    AiFeedbackResponse,
    NodeCreateRequest,
    NodeResponse,
    NodeUpdateRequest,
    RelationCreateRequest,
    RelationResponse,
    RelationUpdateRequest,
    TreeCreateRequest,
    TreeDetailResponse,
    TreeExportResponse,
    TreeImportRequest,
    TreeListItem,
    TreeUpdateRequest,
    ValidationHistoryResponse,
    ValidationRequest,
    ValidationResponse,
    VersionCreateRequest,
    VersionListItem,
)
from app.schemas.auth import User
from app.schemas.domain import TreeVersionRef
from app.services import (
    NodeService,
    RelationService,
    TreeService,
    ValidationService,
    VersionService,
)

router = APIRouter(tags=["trees"])


@router.post(
    "/trees",
    response_model=TreeDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 422),
)
def create_tree(
    payload: TreeCreateRequest,
    current_user: User = Depends(get_current_user),
    tree_service: TreeService = Depends(get_tree_service),
) -> TreeDetailResponse:
    tree = tree_service.create_tree(payload, owner_id=current_user.id)
    return tree_service.to_response(tree)


@router.get(
    "/trees", response_model=list[TreeListItem], responses=error_responses(401, 422)
)
def list_trees(
    current_user: User = Depends(get_current_user),
    tree_service: TreeService = Depends(get_tree_service),
) -> list[TreeListItem]:
    entries = tree_service.list_trees(owner_id=current_user.id)
    return [
        TreeListItem(
            id=entry.id,
            name=entry.title,
            updated_at=entry.updated_at,
            owner_id=entry.owner_id,
        )
        for entry in entries
    ]


@router.get(
    "/trees/{tree_id}",
    response_model=TreeDetailResponse,
    responses=error_responses(401, 404, 422),
)
def get_tree(
    tree_id: str,
    current_user: User = Depends(get_current_user),
    tree_service: TreeService = Depends(get_tree_service),
) -> TreeDetailResponse:
    tree = tree_service.get_tree_for_owner(tree_id, owner_id=current_user.id)
    return tree_service.to_response(tree)


@router.put(
    "/trees/{tree_id}",
    response_model=TreeDetailResponse,
    responses=error_responses(401, 404, 422),
)
def update_tree(
    tree_id: str,
    payload: TreeUpdateRequest,
    current_user: User = Depends(get_current_user),
    tree_service: TreeService = Depends(get_tree_service),
) -> TreeDetailResponse:
    tree = tree_service.update_tree(tree_id, payload, owner_id=current_user.id)
    return tree_service.to_response(tree)


@router.delete(
    "/trees/{tree_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 404, 422),
)
def delete_tree(
    tree_id: str,
    current_user: User = Depends(get_current_user),
    tree_service: TreeService = Depends(get_tree_service),
) -> None:
    tree_service.delete_tree(tree_id, owner_id=current_user.id)


@router.post(
    "/trees/import",
    response_model=TreeDetailResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 422),
)
def import_tree(
    payload: TreeImportRequest,
    current_user: User = Depends(get_current_user),
    tree_service: TreeService = Depends(get_tree_service),
) -> TreeDetailResponse:
    tree = tree_service.import_tree(payload.tree, owner_id=current_user.id)
    return tree_service.to_response(tree)


@router.post(
    "/trees/{tree_id}/export",
    response_model=TreeExportResponse,
    responses=error_responses(401, 404, 422),
)
def export_tree(
    tree_id: str,
    current_user: User = Depends(get_current_user),
    tree_service: TreeService = Depends(get_tree_service),
) -> TreeExportResponse:
    tree = tree_service.get_tree_for_owner(tree_id, owner_id=current_user.id)
    return TreeExportResponse(tree=tree_service.to_response(tree))


@router.post(
    "/trees/{tree_id}/ai-feedback",
    response_model=AiFeedbackResponse,
    status_code=status.HTTP_200_OK,
    responses=error_responses(400, 401, 404, 422),
)
def ai_feedback(
    tree_id: str,
    payload: AiFeedbackRequest,
    current_user: User = Depends(get_current_user),
    tree_service: TreeService = Depends(get_tree_service),
) -> AiFeedbackResponse:
    return tree_service.generate_ai_feedback(tree_id, payload, owner_id=current_user.id)


@router.post(
    "/trees/{tree_id}/nodes",
    response_model=NodeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 404, 422),
)
def create_node(
    tree_id: str,
    payload: NodeCreateRequest,
    current_user: User = Depends(get_current_user),
    node_service: NodeService = Depends(get_node_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> NodeResponse:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    node, tree = node_service.create_node(tree_id, payload)
    return tree_service.node_to_response(tree, node.id)


@router.patch(
    "/trees/{tree_id}/nodes/{node_id}",
    response_model=NodeResponse,
    responses=error_responses(401, 404, 422),
)
def update_node(
    tree_id: str,
    node_id: str,
    payload: NodeUpdateRequest,
    current_user: User = Depends(get_current_user),
    node_service: NodeService = Depends(get_node_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> NodeResponse:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    node, tree = node_service.update_node(tree_id, node_id, payload)
    return tree_service.node_to_response(tree, node.id)


@router.delete(
    "/trees/{tree_id}/nodes/{node_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 404, 422),
)
def delete_node(
    tree_id: str,
    node_id: str,
    cascade: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    node_service: NodeService = Depends(get_node_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> None:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    node_service.delete_node(tree_id, node_id, cascade=cascade)


@router.post(
    "/trees/{tree_id}/relations",
    response_model=RelationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 404, 422),
)
def create_relation(
    tree_id: str,
    payload: RelationCreateRequest,
    current_user: User = Depends(get_current_user),
    relation_service: RelationService = Depends(get_relation_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> RelationResponse:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    relation, _tree = relation_service.create_relation(tree_id, payload)
    return tree_service.relation_to_response(relation)


@router.patch(
    "/trees/{tree_id}/relations/{relation_id}",
    response_model=RelationResponse,
    responses=error_responses(400, 401, 404, 422),
)
def update_relation(
    tree_id: str,
    relation_id: str,
    payload: RelationUpdateRequest,
    current_user: User = Depends(get_current_user),
    relation_service: RelationService = Depends(get_relation_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> RelationResponse:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    relation, _tree = relation_service.update_relation(tree_id, relation_id, payload)
    return tree_service.relation_to_response(relation)


@router.delete(
    "/trees/{tree_id}/relations/{relation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 404, 422),
)
def delete_relation(
    tree_id: str,
    relation_id: str,
    current_user: User = Depends(get_current_user),
    relation_service: RelationService = Depends(get_relation_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> None:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    relation_service.delete_relation(tree_id, relation_id)


@router.post(
    "/trees/{tree_id}/versions",
    response_model=VersionListItem,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 404, 422),
)
def create_version(
    tree_id: str,
    payload: VersionCreateRequest,
    current_user: User = Depends(get_current_user),
    version_service: VersionService = Depends(get_version_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> VersionListItem:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    version = version_service.create_version(tree_id, payload)
    return VersionListItem(
        id=version.id,
        label=version.label,
        created_at=version.captured_at,
        author=version.author,
        notes=version.notes,
        diff_summary=version.diff,
        conflict_count=len(version.conflicts),
    )


@router.get(
    "/trees/{tree_id}/versions",
    response_model=list[VersionListItem],
    responses=error_responses(401, 404, 422),
)
def list_versions(
    tree_id: str,
    current_user: User = Depends(get_current_user),
    version_service: VersionService = Depends(get_version_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> list[VersionListItem]:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    return [_version_ref_to_item(ref) for ref in version_service.list_versions(tree_id)]


@router.post(
    "/trees/{tree_id}/versions/{version_id}/restore",
    response_model=TreeDetailResponse,
    responses=error_responses(401, 404, 422),
)
def restore_version(
    tree_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    version_service: VersionService = Depends(get_version_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> TreeDetailResponse:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    tree = version_service.restore_version(tree_id, version_id)
    return tree_service.to_response(tree)


@router.delete(
    "/trees/{tree_id}/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 404, 422),
)
def delete_version(
    tree_id: str,
    version_id: str,
    current_user: User = Depends(get_current_user),
    version_service: VersionService = Depends(get_version_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> None:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    version_service.delete_version(tree_id, version_id)


@router.post(
    "/trees/{tree_id}/validate/{node_id}",
    response_model=ValidationResponse,
    status_code=status.HTTP_200_OK,
    responses=error_responses(401, 404, 422),
)
def validate_node(
    tree_id: str,
    node_id: str,
    payload: ValidationRequest,
    current_user: User = Depends(get_current_user),
    validation_service: ValidationService = Depends(get_validation_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> ValidationResponse:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    return validation_service.trigger_validation(tree_id, node_id, payload)


@router.get(
    "/trees/{tree_id}/nodes/{node_id}/validation-history",
    response_model=ValidationHistoryResponse,
    responses=error_responses(401, 404, 422),
)
def get_validation_history(
    tree_id: str,
    node_id: str,
    current_user: User = Depends(get_current_user),
    validation_service: ValidationService = Depends(get_validation_service),
    tree_service: TreeService = Depends(get_tree_service),
) -> ValidationHistoryResponse:
    tree_service.assert_owner(tree_id, owner_id=current_user.id)
    history = validation_service.get_history(tree_id, node_id)
    items = [
        ValidationResponse(
            node_id=node_id,
            provider=entry.provider,
            confidence=entry.confidence,
            summary=entry.summary,
            checked_at=entry.checked_at,
        )
        for entry in history
    ]
    return ValidationHistoryResponse(items=items)


def _version_ref_to_item(ref: TreeVersionRef) -> VersionListItem:
    return VersionListItem(
        id=ref.id,
        label=ref.label,
        created_at=ref.created_at,
        author=ref.author,
        notes=ref.notes,
        diff_summary=ref.diff_summary,
        conflict_count=ref.conflict_count,
    )
