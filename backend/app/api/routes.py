"""FastAPI routes implementing the Brain Buddy API contracts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import (
    get_node_service,
    get_relation_service,
    get_tree_service,
    get_validation_service,
    get_version_service,
)
from app.schemas import (
    NodeCreateRequest,
    NodeResponse,
    NodeUpdateRequest,
    RelationCreateRequest,
    RelationResponse,
    RelationUpdateRequest,
    TimestampMetadata,
    TreeCreateRequest,
    TreeDetailResponse,
    TreeListItem,
    TreeUpdateRequest,
    ValidationHistoryResponse,
    ValidationRequest,
    ValidationResponse,
    VersionCreateRequest,
    VersionListItem,
)
from app.schemas.domain import RelationDocument, TreeDocument

router = APIRouter(tags=["trees"])


def _build_tree_response(tree: TreeDocument) -> TreeDetailResponse:
    node_counts: dict[str, tuple[int, int]] = {}
    for relation in tree.relations:
        incoming, outgoing = node_counts.get(relation.target_id, (0, 0))
        node_counts[relation.target_id] = (incoming + 1, outgoing)
        incoming, outgoing = node_counts.get(relation.source_id, (0, 0))
        node_counts[relation.source_id] = (incoming, outgoing + 1)

    node_payloads = [
        NodeResponse(
            id=node.id,
            label=node.label,
            position=node.position,
            metadata=node.metadata,
            visual=node.visual,
            validation=node.validation,
            incoming_count=node_counts.get(node.id, (0, 0))[0],
            outgoing_count=node_counts.get(node.id, (0, 0))[1],
        )
        for node in tree.nodes
    ]

    relation_payloads = [
        RelationResponse(
            id=relation.id,
            source_id=relation.source_id,
            target_id=relation.target_id,
            question_label=relation.question_label,
            notes=relation.notes,
            metadata=relation.metadata,
        )
        for relation in tree.relations
    ]

    version_payloads = [
        VersionListItem(id=ref.id, label=ref.label, created_at=ref.created_at)
        for ref in tree.version_refs
    ]

    return TreeDetailResponse(
        id=tree.id,
        title=tree.title,
        description=tree.description,
        created_at=tree.created_at,
        updated_at=tree.updated_at,
        nodes=node_payloads,
        relations=relation_payloads,
        versions=version_payloads,
    )


@router.post(
    "/trees",
    response_model=TreeDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_tree(
    payload: TreeCreateRequest,
    tree_service=Depends(get_tree_service),
) -> TreeDetailResponse:
    tree = tree_service.create_tree(payload)
    return _build_tree_response(tree)


@router.get("/trees", response_model=list[TreeListItem])
def list_trees(tree_service=Depends(get_tree_service)) -> list[TreeListItem]:
    entries = tree_service.list_trees()
    return [
        TreeListItem(id=entry.id, title=entry.title, description=entry.description, updated_at=entry.updated_at)
        for entry in entries
    ]


@router.get("/trees/{tree_id}", response_model=TreeDetailResponse)
def get_tree(tree_id: str, tree_service=Depends(get_tree_service)) -> TreeDetailResponse:
    tree = tree_service.get_tree(tree_id)
    return _build_tree_response(tree)


@router.patch("/trees/{tree_id}", response_model=TreeDetailResponse)
def update_tree(
    tree_id: str,
    payload: TreeUpdateRequest,
    tree_service=Depends(get_tree_service),
) -> TreeDetailResponse:
    tree = tree_service.update_tree(tree_id, payload)
    return _build_tree_response(tree)


@router.delete("/trees/{tree_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tree(tree_id: str, tree_service=Depends(get_tree_service)) -> None:
    tree_service.delete_tree(tree_id)


@router.post(
    "/trees/{tree_id}/nodes",
    response_model=NodeResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_node(
    tree_id: str,
    payload: NodeCreateRequest,
    node_service=Depends(get_node_service),
) -> NodeResponse:
    node, tree = node_service.create_node(tree_id, payload)
    return _node_response_from_tree(tree, node.id)


@router.patch("/trees/{tree_id}/nodes/{node_id}", response_model=NodeResponse)
def update_node(
    tree_id: str,
    node_id: str,
    payload: NodeUpdateRequest,
    node_service=Depends(get_node_service),
) -> NodeResponse:
    node, tree = node_service.update_node(tree_id, node_id, payload)
    return _node_response_from_tree(tree, node.id)


@router.delete("/trees/{tree_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_node(
    tree_id: str,
    node_id: str,
    cascade: bool = Query(default=False),
    node_service=Depends(get_node_service),
) -> None:
    node_service.delete_node(tree_id, node_id, cascade=cascade)


@router.post(
    "/trees/{tree_id}/relations",
    response_model=RelationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_relation(
    tree_id: str,
    payload: RelationCreateRequest,
    relation_service=Depends(get_relation_service),
) -> RelationResponse:
    relation, _tree = relation_service.create_relation(tree_id, payload)
    return _relation_to_response(relation)


@router.patch("/trees/{tree_id}/relations/{relation_id}", response_model=RelationResponse)
def update_relation(
    tree_id: str,
    relation_id: str,
    payload: RelationUpdateRequest,
    relation_service=Depends(get_relation_service),
) -> RelationResponse:
    relation, _tree = relation_service.update_relation(tree_id, relation_id, payload)
    return _relation_to_response(relation)


@router.delete("/trees/{tree_id}/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_relation(
    tree_id: str,
    relation_id: str,
    relation_service=Depends(get_relation_service),
) -> None:
    relation_service.delete_relation(tree_id, relation_id)


@router.post(
    "/trees/{tree_id}/versions",
    response_model=VersionListItem,
    status_code=status.HTTP_201_CREATED,
)
def create_version(
    tree_id: str,
    payload: VersionCreateRequest,
    version_service=Depends(get_version_service),
) -> VersionListItem:
    version = version_service.create_version(tree_id, payload)
    return VersionListItem(id=version.id, label=version.label, created_at=version.captured_at)


@router.get("/trees/{tree_id}/versions", response_model=list[VersionListItem])
def list_versions(tree_id: str, version_service=Depends(get_version_service)) -> list[VersionListItem]:
    return [
        VersionListItem(id=ref.id, label=ref.label, created_at=ref.created_at)
        for ref in version_service.list_versions(tree_id)
    ]


@router.post(
    "/trees/{tree_id}/versions/{version_id}/restore",
    response_model=TreeDetailResponse,
)
def restore_version(
    tree_id: str,
    version_id: str,
    version_service=Depends(get_version_service),
) -> TreeDetailResponse:
    tree = version_service.restore_version(tree_id, version_id)
    return _build_tree_response(tree)


@router.delete("/trees/{tree_id}/versions/{version_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_version(
    tree_id: str,
    version_id: str,
    version_service=Depends(get_version_service),
) -> None:
    version_service.delete_version(tree_id, version_id)


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
) -> ValidationResponse:
    return validation_service.trigger_validation(tree_id, node_id, payload)


@router.get(
    "/trees/{tree_id}/nodes/{node_id}/validation-history",
    response_model=ValidationHistoryResponse,
)
def get_validation_history(
    tree_id: str,
    node_id: str,
    validation_service=Depends(get_validation_service),
) -> ValidationHistoryResponse:
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


def _node_response_from_tree(tree: TreeDocument, node_id: str) -> NodeResponse:
    node = next(node for node in tree.nodes if node.id == node_id)
    counts = _relation_counts(tree.relations, node_id)
    return NodeResponse(
        id=node.id,
        label=node.label,
        position=node.position,
        metadata=node.metadata,
        visual=node.visual,
        validation=node.validation,
        incoming_count=counts[0],
        outgoing_count=counts[1],
    )


def _relation_counts(relations: list[RelationDocument], node_id: str) -> tuple[int, int]:
    incoming = sum(1 for relation in relations if relation.target_id == node_id)
    outgoing = sum(1 for relation in relations if relation.source_id == node_id)
    return incoming, outgoing


def _relation_to_response(relation: RelationDocument) -> RelationResponse:
    metadata = TimestampMetadata(
        created_at=relation.metadata.created_at,
        updated_at=relation.metadata.updated_at,
        author=relation.metadata.author,
    )
    return RelationResponse(
        id=relation.id,
        source_id=relation.source_id,
        target_id=relation.target_id,
        question_label=relation.question_label,
        notes=relation.notes,
        metadata=metadata,
    )
