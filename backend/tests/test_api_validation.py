from __future__ import annotations

from app.schemas import NodeCreateRequest, Position, RelationCreateRequest, TreeCreateRequest


def test_validation_endpoint_flow(api_client) -> None:
    tree_payload = TreeCreateRequest(title="API Validation", description=None)
    tree_resp = api_client.post("/api/trees", json=tree_payload.model_dump())
    assert tree_resp.status_code == 201
    tree_id = tree_resp.json()["id"]

    effect_payload = NodeCreateRequest(label="Effect", position=Position(x=0, y=0))
    effect_resp = api_client.post(
        f"/api/trees/{tree_id}/nodes",
        json=effect_payload.model_dump(),
    )
    assert effect_resp.status_code == 201
    effect_id = effect_resp.json()["id"]

    cause_payload = NodeCreateRequest(label="Cause", position=Position(x=120, y=120))
    cause_resp = api_client.post(
        f"/api/trees/{tree_id}/nodes",
        json=cause_payload.model_dump(),
    )
    assert cause_resp.status_code == 201
    cause_id = cause_resp.json()["id"]

    relation_payload = RelationCreateRequest(
        source_id=effect_id,
        target_id=cause_id,
        question_label="WHY?",
        notes="Investigate root",
    )
    relation_resp = api_client.post(
        f"/api/trees/{tree_id}/relations",
        json=relation_payload.model_dump(),
    )
    assert relation_resp.status_code == 201

    validation_resp = api_client.post(f"/api/trees/{tree_id}/validate/{effect_id}", json={})
    assert validation_resp.status_code == 200
    payload = validation_resp.json()
    assert payload["provider"] == "mock"
    assert payload["node_id"] == effect_id
    assert 0 <= payload["confidence"] <= 100

    history_resp = api_client.get(f"/api/trees/{tree_id}/nodes/{effect_id}/validation-history")
    assert history_resp.status_code == 200
    history_payload = history_resp.json()["items"]
    assert history_payload
    assert history_payload[-1]["summary"] == payload["summary"]
