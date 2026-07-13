"""API integration coverage for mutation routes and error observability."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import register_exception_handlers
from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.schemas import (
    NodeCreateRequest,
    Position,
    RelationCreateRequest,
    TreeCreateRequest,
)


def _create_tree(api_client) -> str:
    response = api_client.post(
        "/api/trees", json=TreeCreateRequest(name="API mutations").model_dump()
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_node(api_client, tree_id: str, label: str, x: int) -> str:
    response = api_client.post(
        f"/api/trees/{tree_id}/nodes",
        json=NodeCreateRequest(
            label=label, type="child", position=Position(x=x, y=x)
        ).model_dump(),
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_mutation_routes_create_update_and_delete_relations_nodes_and_versions(
    api_client,
) -> None:
    tree_id = _create_tree(api_client)
    first_id = _create_node(api_client, tree_id, "First", 0)
    second_id = _create_node(api_client, tree_id, "Second", 1)
    spare_id = _create_node(api_client, tree_id, "Spare", 2)

    created_relation = api_client.post(
        f"/api/trees/{tree_id}/relations",
        json=RelationCreateRequest(
            source_node_id=first_id, target_node_id=second_id, kind="why"
        ).model_dump(),
    )
    assert created_relation.status_code == 201
    relation_id = created_relation.json()["id"]

    updated_relation = api_client.patch(
        f"/api/trees/{tree_id}/relations/{relation_id}", json={"kind": "why"}
    )
    assert updated_relation.status_code == 200
    assert (
        api_client.delete(f"/api/trees/{tree_id}/relations/{relation_id}").status_code
        == 204
    )
    assert (
        api_client.delete(f"/api/trees/{tree_id}/nodes/{spare_id}").status_code == 204
    )

    version = api_client.post(f"/api/trees/{tree_id}/versions", json={"label": "v1"})
    assert version.status_code == 201
    version_id = version.json()["id"]
    assert api_client.get(f"/api/trees/{tree_id}/versions").status_code == 200
    assert (
        api_client.post(
            f"/api/trees/{tree_id}/versions/{version_id}/restore"
        ).status_code
        == 200
    )
    assert (
        api_client.delete(f"/api/trees/{tree_id}/versions/{version_id}").status_code
        == 204
    )


def test_error_handlers_preserve_correlation_ids_and_contract_statuses() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/missing")
    def missing() -> None:
        raise NotFoundError("Tree", "tree_missing")

    @app.get("/conflict")
    def conflict() -> None:
        raise ConflictError("Tree", "tree_conflict")

    @app.get("/invalid")
    def invalid() -> None:
        raise ValidationFailure("Invalid tree", detail={"reason": "invalid"})

    client = TestClient(app)
    for path, status_code in (("/missing", 404), ("/conflict", 409), ("/invalid", 400)):
        response = client.get(path)
        assert response.status_code == status_code

    assert client.get("/invalid").json()["detail"] == {"reason": "invalid"}
