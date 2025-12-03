from __future__ import annotations

from datetime import UTC, datetime

from app.schemas import NodeCreateRequest, Position, RelationCreateRequest


def _iso(ts: datetime) -> str:
    return ts.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def test_tree_contract_round_trip(api_client) -> None:
    create_resp = api_client.post("/api/trees", json={"name": "API Tree"})
    assert create_resp.status_code == 201
    assert create_resp.headers.get("X-Correlation-ID")
    created = create_resp.json()
    tree_id = created["id"]
    assert created["name"] == "API Tree"
    assert created["nodes"] == []
    assert created["relations"] == []
    assert created["metadata"]["version"] == 1

    list_resp = api_client.get("/api/trees")
    assert list_resp.status_code == 200
    listed = list_resp.json()
    assert any(item["id"] == tree_id and item["name"] == "API Tree" for item in listed)

    cause_payload = NodeCreateRequest(
        label="Cause", type="cause", position=Position(x=0.0, y=0.0)
    ).model_dump()
    effect_payload = NodeCreateRequest(
        label="Effect", type="undesired_effect", position=Position(x=1.0, y=1.0)
    ).model_dump()
    cause_resp = api_client.post(f"/api/trees/{tree_id}/nodes", json=cause_payload)
    effect_resp = api_client.post(f"/api/trees/{tree_id}/nodes", json=effect_payload)
    assert cause_resp.status_code == 201
    assert effect_resp.status_code == 201
    cause_node = cause_resp.json()
    effect_node = effect_resp.json()

    relation_payload = RelationCreateRequest(
        from_id=cause_node["id"],
        to_id=effect_node["id"],
        kind="why",
    ).model_dump()
    relation_resp = api_client.post(
        f"/api/trees/{tree_id}/relations", json=relation_payload
    )
    assert relation_resp.status_code == 201
    relation = relation_resp.json()
    assert relation["from_id"] == cause_node["id"]
    assert relation["to_id"] == effect_node["id"]

    detail_resp = api_client.get(f"/api/trees/{tree_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    cause_state = next(
        node for node in detail["nodes"] if node["id"] == cause_node["id"]
    )
    effect_state = next(
        node for node in detail["nodes"] if node["id"] == effect_node["id"]
    )
    assert cause_state["relation_counts"]["up_count"] == 1
    assert cause_state["relation_counts"]["down_count"] == 0
    assert effect_state["relation_counts"]["down_count"] == 1
    assert effect_state["relation_counts"]["up_count"] == 0

    export_resp = api_client.post(f"/api/trees/{tree_id}/export")
    assert export_resp.status_code == 200
    exported = export_resp.json()["tree"]
    assert exported["relations"][0]["from_id"] == cause_node["id"]
    assert exported["relations"][0]["to_id"] == effect_node["id"]

    import_resp = api_client.post("/api/trees/import", json={"tree": exported})
    assert import_resp.status_code == 201
    imported = import_resp.json()
    assert imported["name"] == exported["name"]
    assert imported["nodes"] and imported["relations"]
    # Relation direction preserved on import
    imported_relation = imported["relations"][0]
    assert imported_relation["from_id"] == cause_node["id"]
    assert imported_relation["to_id"] == effect_node["id"]


def test_import_rejects_cycles_and_missing_nodes(api_client) -> None:
    now = _iso(datetime(2025, 1, 1, 0, 0, 0))
    base_tree = {
        "id": "tree-cycle",
        "name": "Cycle Tree",
        "metadata": {
            "version": 1,
            "created_at": now,
            "updated_at": now,
            "layout": None,
            "owner_id": None,
        },
        "nodes": [
            {
                "id": "n1",
                "label": "A",
                "type": "regular",
                "position": {"x": 0, "y": 0},
                "highlight_state": "none",
                "relation_counts": {"up_count": 0, "down_count": 0},
            },
            {
                "id": "n2",
                "label": "B",
                "type": "regular",
                "position": {"x": 1, "y": 1},
                "highlight_state": "none",
                "relation_counts": {"up_count": 0, "down_count": 0},
            },
        ],
        "relations": [
            {
                "id": "r1",
                "from_id": "n1",
                "to_id": "n2",
                "kind": "why",
                "created_at": now,
            },
            {
                "id": "r2",
                "from_id": "n2",
                "to_id": "n1",
                "kind": "why",
                "created_at": now,
            },
        ],
        "owner_id": None,
    }
    cycle_resp = api_client.post("/api/trees/import", json={"tree": base_tree})
    assert cycle_resp.status_code == 400
    assert cycle_resp.headers.get("X-Correlation-ID")

    base_tree["relations"] = [
        {"id": "r1", "from_id": "n1", "to_id": "n3", "kind": "why", "created_at": now}
    ]
    missing_resp = api_client.post("/api/trees/import", json={"tree": base_tree})
    assert missing_resp.status_code == 400
    assert missing_resp.headers.get("X-Correlation-ID")


def test_api_key_middleware_enforces_header(secured_api_client) -> None:
    unauthenticated = secured_api_client.get("/api/trees")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers.get("X-Correlation-ID")

    authenticated = secured_api_client.get(
        "/api/trees", headers={"X-API-Key": "test-key"}
    )
    assert authenticated.status_code == 200
