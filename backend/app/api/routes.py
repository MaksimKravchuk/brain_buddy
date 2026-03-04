"""FastAPI routes implementing the Brain Buddy API contracts."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import (
    get_current_account,
    get_node_service,
    get_relation_service,
    get_tree_service,
    get_validation_service,
    get_version_service,
)
from app.schemas import (
    AccountResponse,
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
from app.schemas.domain import AccountDocument, TreeVersionRef

router = APIRouter(tags=["trees"])


# ── Account ──────────────────────────────────────────────────────────────────


@router.get("/me", response_model=AccountResponse, tags=["account"])
def get_me(
    account: AccountDocument = Depends(get_current_account),
) -> AccountResponse:
    return AccountResponse(
        id=account.id, name=account.name, has_ai_access=account.has_ai_access
    )


# ── Trees ────────────────────────────────────────────────────────────────────


@router.post(
    "/trees",
    response_model=TreeDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_tree(
    payload: TreeCreateRequest,
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> TreeDetailResponse:
    payload.owner_id = account.id
    tree = tree_service.create_tree(payload)
    return tree_service.to_response(tree)


@router.get("/trees", response_model=list[TreeListItem])
def list_trees(
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> list[TreeListItem]:
    entries = tree_service.list_trees(owner_id=account.id)
    return [
        TreeListItem(
            id=entry.id,
            name=entry.title,
            updated_at=entry.updated_at,
            owner_id=entry.owner_id,
        )
        for entry in entries
    ]


@router.get("/trees/{tree_id}", response_model=TreeDetailResponse)
def get_tree(
    tree_id: str,
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> TreeDetailResponse:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    return tree_service.to_response(tree)


@router.put("/trees/{tree_id}", response_model=TreeDetailResponse)
def update_tree(
    tree_id: str,
    payload: TreeUpdateRequest,
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> TreeDetailResponse:
    existing = tree_service.get_tree(tree_id)
    tree_service.assert_owner(existing, account.id)
    payload.owner_id = account.id
    tree = tree_service.update_tree(tree_id, payload)
    return tree_service.to_response(tree)


@router.delete("/trees/{tree_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tree(
    tree_id: str,
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> None:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    tree_service.delete_tree(tree_id)


@router.post(
    "/trees/import",
    response_model=TreeDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def import_tree(
    payload: TreeImportRequest,
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> TreeDetailResponse:
    payload.tree.owner_id = account.id
    tree = tree_service.import_tree(payload.tree)
    return tree_service.to_response(tree)


@router.post("/trees/{tree_id}/export", response_model=TreeExportResponse)
def export_tree(
    tree_id: str,
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> TreeExportResponse:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    return TreeExportResponse(tree=tree_service.to_response(tree))


@router.post(
    "/trees/{tree_id}/ai-feedback",
    response_model=AiFeedbackResponse,
    status_code=status.HTTP_200_OK,
)
def ai_feedback(
    tree_id: str,
    payload: AiFeedbackRequest,
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> AiFeedbackResponse:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    if not account.has_ai_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI features are not enabled for this account.",
        )
    return tree_service.generate_ai_feedback(tree_id, payload)


# ── Nodes ────────────────────────────────────────────────────────────────────


@router.post(
    "/trees/{tree_id}/nodes",
    response_model=NodeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_node(
    tree_id: str,
    payload: NodeCreateRequest,
    node_service=Depends(get_node_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> NodeResponse:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    node, tree = node_service.create_node(tree_id, payload)
    return tree_service.node_to_response(tree, node.id)


@router.patch("/trees/{tree_id}/nodes/{node_id}", response_model=NodeResponse)
def update_node(
    tree_id: str,
    node_id: str,
    payload: NodeUpdateRequest,
    node_service=Depends(get_node_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> NodeResponse:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    node, tree = node_service.update_node(tree_id, node_id, payload)
    return tree_service.node_to_response(tree, node.id)


@router.delete(
    "/trees/{tree_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_node(
    tree_id: str,
    node_id: str,
    cascade: bool = Query(default=False),
    node_service=Depends(get_node_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> None:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    node_service.delete_node(tree_id, node_id, cascade=cascade)


# ── Relations ────────────────────────────────────────────────────────────────


@router.post(
    "/trees/{tree_id}/relations",
    response_model=RelationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_relation(
    tree_id: str,
    payload: RelationCreateRequest,
    relation_service=Depends(get_relation_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> RelationResponse:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    relation, _tree = relation_service.create_relation(tree_id, payload)
    return tree_service.relation_to_response(relation)


@router.patch(
    "/trees/{tree_id}/relations/{relation_id}", response_model=RelationResponse
)
def update_relation(
    tree_id: str,
    relation_id: str,
    payload: RelationUpdateRequest,
    relation_service=Depends(get_relation_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> RelationResponse:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    relation, _tree = relation_service.update_relation(tree_id, relation_id, payload)
    return tree_service.relation_to_response(relation)


@router.delete(
    "/trees/{tree_id}/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_relation(
    tree_id: str,
    relation_id: str,
    relation_service=Depends(get_relation_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> None:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    relation_service.delete_relation(tree_id, relation_id)


# ── Versions ─────────────────────────────────────────────────────────────────


@router.post(
    "/trees/{tree_id}/versions",
    response_model=VersionListItem,
    status_code=status.HTTP_201_CREATED,
)
def create_version(
    tree_id: str,
    payload: VersionCreateRequest,
    version_service=Depends(get_version_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> VersionListItem:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
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


@router.get("/trees/{tree_id}/versions", response_model=list[VersionListItem])
def list_versions(
    tree_id: str,
    version_service=Depends(get_version_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> list[VersionListItem]:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    return [_version_ref_to_item(ref) for ref in version_service.list_versions(tree_id)]


@router.post(
    "/trees/{tree_id}/versions/{version_id}/restore",
    response_model=TreeDetailResponse,
)
def restore_version(
    tree_id: str,
    version_id: str,
    version_service=Depends(get_version_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> TreeDetailResponse:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    tree = version_service.restore_version(tree_id, version_id)
    return tree_service.to_response(tree)


@router.delete(
    "/trees/{tree_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_version(
    tree_id: str,
    version_id: str,
    version_service=Depends(get_version_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> None:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    version_service.delete_version(tree_id, version_id)


# ── Validation ───────────────────────────────────────────────────────────────


@router.post(
    "/trees/{tree_id}/validate/{node_id}",
    response_model=ValidationResponse,
    status_code=status.HTTP_200_OK,
)
def validate_node(
    tree_id: str,
    node_id: str,
    payload: ValidationRequest,
    validation_service=Depends(get_validation_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> ValidationResponse:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
    if not account.has_ai_access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI features are not enabled for this account.",
        )
    return validation_service.trigger_validation(tree_id, node_id, payload)


@router.get(
    "/trees/{tree_id}/nodes/{node_id}/validation-history",
    response_model=ValidationHistoryResponse,
)
def get_validation_history(
    tree_id: str,
    node_id: str,
    validation_service=Depends(get_validation_service),
    tree_service=Depends(get_tree_service),
    account: AccountDocument = Depends(get_current_account),
) -> ValidationHistoryResponse:
    tree = tree_service.get_tree(tree_id)
    tree_service.assert_owner(tree, account.id)
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
