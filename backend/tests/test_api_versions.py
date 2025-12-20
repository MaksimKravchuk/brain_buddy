from __future__ import annotations

from app.schemas import NodeCreateRequest, Position, TreeCreateRequest


def test_version_endpoints_and_export(api_client) -> None:
    tree_payload = TreeCreateRequest(name="Versioned Tree")
    tree_resp = api_client.post("/api/trees", json=tree_payload.model_dump())
    assert tree_resp.status_code == 201
    tree_id = tree_resp.json()["id"]

    node_payload = NodeCreateRequest(
        label="Root", type="cause", position=Position(x=0, y=0)
    )
    node_resp = api_client.post(
        f"/api/trees/{tree_id}/nodes", json=node_payload.model_dump()
    )
    assert node_resp.status_code == 201

    version_payload = {
        "label": "Initial",
        "author": "Taylor",
        "notes": "First snapshot",
    }
    version_resp = api_client.post(
        f"/api/trees/{tree_id}/versions", json=version_payload
    )
    assert version_resp.status_code == 201
    version_data = version_resp.json()
    assert version_data["author"] == "Taylor"
    assert version_data["diff_summary"]["nodes_added"] == 1

    list_resp = api_client.get(f"/api/trees/{tree_id}/versions")
    assert list_resp.status_code == 200
    versions = list_resp.json()
    assert versions[0]["id"] == version_data["id"]
    assert versions[0]["conflict_count"] == 0

    export_live_resp = api_client.post(f"/api/trees/{tree_id}/export")
    assert export_live_resp.status_code == 200
    live_payload = export_live_resp.json()
    assert live_payload["tree"]["id"] == tree_id
