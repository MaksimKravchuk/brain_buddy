from __future__ import annotations

from app.schemas import NodeCreateRequest, Position, TreeCreateRequest


def test_tree_crud_flow(api_client) -> None:
    create_payload = TreeCreateRequest(title="API Tree", description="Demo")
    response = api_client.post("/api/trees", json=create_payload.model_dump())
    assert response.status_code == 201
    tree_id = response.json()["id"]

    list_resp = api_client.get("/api/trees")
    assert list_resp.status_code == 200
    assert any(item["id"] == tree_id for item in list_resp.json())

    update_resp = api_client.patch(f"/api/trees/{tree_id}", json={"description": "Updated"})
    assert update_resp.status_code == 200
    assert update_resp.json()["description"] == "Updated"

    node_payload = NodeCreateRequest(label="Node A", position=Position(x=1.0, y=2.0))
    node_resp = api_client.post(
        f"/api/trees/{tree_id}/nodes",
        json=node_payload.model_dump(),
    )
    assert node_resp.status_code == 201
    node_id = node_resp.json()["id"]

    delete_node_resp = api_client.delete(f"/api/trees/{tree_id}/nodes/{node_id}", params={"cascade": True})
    assert delete_node_resp.status_code == 204

    delete_resp = api_client.delete(f"/api/trees/{tree_id}")
    assert delete_resp.status_code == 204
