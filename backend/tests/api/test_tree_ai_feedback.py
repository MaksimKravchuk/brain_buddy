from __future__ import annotations

from app.schemas import Position


API_HEADERS = {"X-API-Key": "test-key"}


def _create_tree(client) -> str:
    create_resp = client.post("/api/trees", json={"name": "AI Tree"}, headers=API_HEADERS)
    assert create_resp.status_code == 201
    tree_id = create_resp.json()["id"]

    node_payload = {"label": "Root cause", "type": "cause", "position": Position(x=0, y=0).model_dump()}
    node_resp = client.post(f"/api/trees/{tree_id}/nodes", json=node_payload, headers=API_HEADERS)
    assert node_resp.status_code == 201
    return tree_id


def test_ai_feedback_requires_consent(secured_api_client) -> None:
    tree_id = _create_tree(secured_api_client)

    resp = secured_api_client.post(
        f"/api/trees/{tree_id}/ai-feedback",
        json={"consent": False},
        headers=API_HEADERS,
    )

    assert resp.status_code == 400
    assert resp.headers.get("X-Correlation-ID")
    detail = resp.json().get("detail")
    assert detail is None or "consent" in str(detail).lower()


def test_ai_feedback_returns_summary_and_recommendations(secured_api_client) -> None:
    tree_id = _create_tree(secured_api_client)

    resp = secured_api_client.post(
        f"/api/trees/{tree_id}/ai-feedback",
        json={"consent": True, "request_id": "req-123"},
        headers=API_HEADERS,
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "success"
    assert "Tree 'AI Tree'" in payload["summary"]
    assert len(payload["recommendations"]) >= 1
    assert payload["request_id"] == "req-123"
