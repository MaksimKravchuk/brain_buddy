from __future__ import annotations

from datetime import UTC, datetime

from app.schemas import NodeCreateRequest, NodeUpdateRequest, Position, RelationCreateRequest


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
        label="Cause", type="parent", position=Position(x=0.0, y=0.0)
    ).model_dump()
    effect_payload = NodeCreateRequest(
        label="Effect", type="child", position=Position(x=1.0, y=1.0)
    ).model_dump()
    cause_resp = api_client.post(f"/api/trees/{tree_id}/nodes", json=cause_payload)
    effect_resp = api_client.post(f"/api/trees/{tree_id}/nodes", json=effect_payload)
    assert cause_resp.status_code == 201
    assert effect_resp.status_code == 201
    cause_node = cause_resp.json()
    effect_node = effect_resp.json()

    relation_payload = RelationCreateRequest(
        source_node_id=cause_node["id"],
        target_node_id=effect_node["id"],
        kind="why",
    ).model_dump()
    relation_resp = api_client.post(
        f"/api/trees/{tree_id}/relations", json=relation_payload
    )
    assert relation_resp.status_code == 201
    relation = relation_resp.json()
    assert relation["source_node_id"] == cause_node["id"]
    assert relation["target_node_id"] == effect_node["id"]

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
    assert exported["relations"][0]["source_node_id"] == cause_node["id"]
    assert exported["relations"][0]["target_node_id"] == effect_node["id"]

    import_resp = api_client.post("/api/trees/import", json={"tree": exported})
    assert import_resp.status_code == 201
    imported = import_resp.json()
    assert imported["name"] == exported["name"]
    assert imported["nodes"] and imported["relations"]
    # Relation direction preserved on import
    imported_relation = imported["relations"][0]
    assert imported_relation["source_node_id"] == cause_node["id"]
    assert imported_relation["target_node_id"] == effect_node["id"]


def test_create_relation_preserves_direction_after_node_moves(api_client) -> None:
    tree_resp = api_client.post("/api/trees", json={"name": "Cross branch"})
    assert tree_resp.status_code == 201
    tree_id = tree_resp.json()["id"]

    def create_node(label: str, x: float, y: float) -> str:
        payload = NodeCreateRequest(
            label=label, type="child", position=Position(x=x, y=y)
        ).model_dump()
        resp = api_client.post(f"/api/trees/{tree_id}/nodes", json=payload)
        assert resp.status_code == 201
        return resp.json()["id"]

    chain_a = [create_node(f"A{i}", float(i), float(i)) for i in range(1, 3)]
    chain_b = [create_node(f"B{i}", float(i + 2), float(i + 2)) for i in range(3, 6)]

    relation_payload = RelationCreateRequest(
        source_node_id=chain_a[1], target_node_id=chain_b[2], kind="why"
    ).model_dump()
    relation_resp = api_client.post(
        f"/api/trees/{tree_id}/relations", json=relation_payload
    )
    assert relation_resp.status_code == 201
    relation = relation_resp.json()
    assert relation["source_node_id"] == chain_a[1]
    assert relation["target_node_id"] == chain_b[2]

    # Move nodes around to simulate drag/drop rearrangement.
    for node_id, new_pos in zip(
        chain_a + chain_b,
        (
            Position(x=10.0, y=5.0),
            Position(x=-2.0, y=3.5),
            Position(x=4.0, y=-1.0),
            Position(x=2.5, y=6.0),
            Position(x=0.0, y=0.0),
        ),
    ):
        update_payload = NodeUpdateRequest(position=new_pos).model_dump(exclude_none=True)
        patch_resp = api_client.patch(
            f"/api/trees/{tree_id}/nodes/{node_id}", json=update_payload
        )
        assert patch_resp.status_code == 200

    detail_resp = api_client.get(f"/api/trees/{tree_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    stored_relation = next(rel for rel in detail["relations"])
    assert stored_relation["source_node_id"] == chain_a[1]
    assert stored_relation["target_node_id"] == chain_b[2]

    # Relation counts align with chosen direction despite node movements.
    source_node = next(node for node in detail["nodes"] if node["id"] == chain_a[1])
    target_node = next(node for node in detail["nodes"] if node["id"] == chain_b[2])
    assert source_node["relation_counts"]["up_count"] == 1
    assert source_node["relation_counts"]["down_count"] == 0
    assert target_node["relation_counts"]["up_count"] == 0
    assert target_node["relation_counts"]["down_count"] == 1


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
                "type": "child",
                "position": {"x": 0, "y": 0},
                "highlight_state": "none",
                "relation_counts": {"up_count": 0, "down_count": 0},
            },
            {
                "id": "n2",
                "label": "B",
                "type": "child",
                "position": {"x": 1, "y": 1},
                "highlight_state": "none",
                "relation_counts": {"up_count": 0, "down_count": 0},
            },
        ],
        "relations": [
            {
                "id": "r1",
                "source_node_id": "n1",
                "target_node_id": "n2",
                "kind": "why",
                "created_at": now,
            },
            {
                "id": "r2",
                "source_node_id": "n2",
                "target_node_id": "n1",
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
        {
            "id": "r1",
            "source_node_id": "n1",
            "target_node_id": "n3",
            "kind": "why",
            "created_at": now,
        }
    ]
    missing_resp = api_client.post("/api/trees/import", json={"tree": base_tree})
    assert missing_resp.status_code == 400
    assert missing_resp.headers.get("X-Correlation-ID")


def test_relation_validation_rejects_self_duplicate_and_cycle(api_client) -> None:
    tree_resp = api_client.post("/api/trees", json={"name": "Integrity checks"})
    assert tree_resp.status_code == 201
    tree_id = tree_resp.json()["id"]

    def create_node(label: str) -> str:
        payload = NodeCreateRequest(
            label=label, type="child", position=Position(x=0.0, y=0.0)
        ).model_dump()
        response = api_client.post(f"/api/trees/{tree_id}/nodes", json=payload)
        assert response.status_code == 201
        return response.json()["id"]

    node_a = create_node("A")
    node_b = create_node("B")
    node_c = create_node("C")

    def attempt_relation(source: str, target: str):
        payload = RelationCreateRequest(
            source_node_id=source, target_node_id=target, kind="why"
        ).model_dump()
        return api_client.post(f"/api/trees/{tree_id}/relations", json=payload)

    self_resp = attempt_relation(node_a, node_a)
    assert self_resp.status_code == 400
    self_body = self_resp.json()
    assert "same node" in self_body["message"].lower()
    assert self_body["detail"]["reason"] == "self_link"
    assert self_body["reference_id"] == self_resp.headers.get("X-Correlation-ID")

    create_resp = attempt_relation(node_a, node_b)
    assert create_resp.status_code == 201

    duplicate_resp = attempt_relation(node_a, node_b)
    assert duplicate_resp.status_code == 400
    duplicate_body = duplicate_resp.json()
    assert "already exists" in duplicate_body["message"].lower()
    assert duplicate_body["detail"]["reason"] == "duplicate_relation"
    assert duplicate_body["reference_id"] == duplicate_resp.headers.get(
        "X-Correlation-ID"
    )

    chain_resp = attempt_relation(node_b, node_c)
    assert chain_resp.status_code == 201

    cycle_resp = attempt_relation(node_c, node_a)
    assert cycle_resp.status_code == 400
    cycle_body = cycle_resp.json()
    assert "cycle" in cycle_body["message"].lower()
    assert cycle_body["detail"]["reason"] == "cycle_detected"
    assert cycle_body["reference_id"] == cycle_resp.headers.get("X-Correlation-ID")


def test_api_key_middleware_enforces_header(secured_api_client) -> None:
    unauthenticated = secured_api_client.get("/api/trees")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers.get("X-Correlation-ID")

    authenticated = secured_api_client.get(
        "/api/trees", headers={"X-API-Key": "test-key"}
    )
    assert authenticated.status_code == 200
