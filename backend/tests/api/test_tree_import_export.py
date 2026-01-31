from __future__ import annotations

from datetime import UTC, datetime

from app.schemas import NodeCreateRequest, Position, RelationCreateRequest


def _iso(ts: datetime) -> str:
    return ts.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _parse(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))


def test_export_includes_highlights_and_layout_metadata(api_client) -> None:
    create_resp = api_client.post("/api/trees", json={"name": "Persisted Tree"})
    assert create_resp.status_code == 201
    tree_id = create_resp.json()["id"]

    cause_payload = NodeCreateRequest(
        label="Cause node", type="parent", position=Position(x=0, y=0)
    ).model_dump()
    effect_payload = NodeCreateRequest(
        label="Effect node", type="child", position=Position(x=1, y=1)
    ).model_dump()

    cause_resp = api_client.post(f"/api/trees/{tree_id}/nodes", json=cause_payload)
    effect_resp = api_client.post(f"/api/trees/{tree_id}/nodes", json=effect_payload)
    cause_id = cause_resp.json()["id"]
    effect_id = effect_resp.json()["id"]

    relation_payload = RelationCreateRequest(
        source_node_id=cause_id, target_node_id=effect_id, kind="why"
    ).model_dump()
    relation_resp = api_client.post(
        f"/api/trees/{tree_id}/relations", json=relation_payload
    )
    assert relation_resp.status_code == 201

    highlight_update = {"highlight_state": "cause_candidate"}
    effect_highlight = {"highlight_state": "effect_spanning"}
    assert (
        api_client.patch(
            f"/api/trees/{tree_id}/nodes/{cause_id}", json=highlight_update
        ).status_code
        == 200
    )
    assert (
        api_client.patch(
            f"/api/trees/{tree_id}/nodes/{effect_id}", json=effect_highlight
        ).status_code
        == 200
    )

    detail = api_client.get(f"/api/trees/{tree_id}").json()
    layout_block = {"zoom": 1.1, "center": {"x": 5, "y": -3}}
    detail["metadata"]["layout"] = layout_block
    update_payload = {
        "name": detail["name"],
        "metadata": detail["metadata"],
        "nodes": detail["nodes"],
        "relations": detail["relations"],
        "owner_id": None,
    }
    update_resp = api_client.put(f"/api/trees/{tree_id}", json=update_payload)
    assert update_resp.status_code == 200

    export_resp = api_client.post(f"/api/trees/{tree_id}/export")
    assert export_resp.status_code == 200
    exported = export_resp.json()["tree"]

    assert exported["metadata"]["layout"] == layout_block
    nodes = {node["id"]: node for node in exported["nodes"]}
    assert nodes[cause_id]["highlight_state"] == "cause_candidate"
    assert nodes[effect_id]["highlight_state"] == "effect_spanning"
    assert nodes[cause_id]["relation_counts"]["up_count"] == 1
    assert nodes[effect_id]["relation_counts"]["down_count"] == 1


def test_import_preserves_ids_and_timestamps(api_client) -> None:
    created = _iso(datetime(2025, 1, 1, 12, 0, 0))
    updated = _iso(datetime(2025, 1, 1, 12, 5, 0))
    tree_payload = {
        "id": "tree-import-123",
        "name": "Imported Tree",
        "metadata": {
            "version": 1,
            "created_at": created,
            "updated_at": updated,
            "layout": {"zoom": 0.9},
            "owner_id": "user-1",
        },
        "nodes": [
            {
                "id": "n1",
                "label": "Root cause",
                "type": "parent",
                "position": {"x": 0, "y": 0},
                "highlight_state": "cause_candidate",
                "relation_counts": {"up_count": 1, "down_count": 0},
            },
            {
                "id": "n2",
                "label": "Effect",
                "type": "child",
                "position": {"x": 1, "y": 1},
                "highlight_state": "none",
                "relation_counts": {"up_count": 0, "down_count": 1},
            },
        ],
        "relations": [
            {
                "id": "r1",
                "source_node_id": "n1",
                "target_node_id": "n2",
                "kind": "why",
                "created_at": created,
            }
        ],
        "owner_id": "user-1",
    }

    import_resp = api_client.post("/api/trees/import", json={"tree": tree_payload})
    assert import_resp.status_code == 201
    imported = import_resp.json()

    assert imported["id"] == tree_payload["id"]
    assert _parse(imported["metadata"]["created_at"]) == _parse(created)
    assert _parse(imported["metadata"]["updated_at"]) >= _parse(updated)
    assert imported["metadata"]["layout"] == {"zoom": 0.9}
    assert imported["owner_id"] == "user-1"

    relation = imported["relations"][0]
    assert relation["id"] == "r1"
    assert relation["source_node_id"] == "n1"
    assert relation["target_node_id"] == "n2"
    assert _parse(relation["created_at"]) == _parse(created)

    export_resp = api_client.post(f"/api/trees/{tree_payload['id']}/export")
    assert export_resp.status_code == 200
    exported = export_resp.json()["tree"]
    assert {node["id"] for node in exported["nodes"]} == {"n1", "n2"}
    assert exported["relations"][0]["id"] == "r1"
    assert exported["relations"][0]["source_node_id"] == "n1"
    assert exported["relations"][0]["target_node_id"] == "n2"


def test_import_invalid_relations_returns_bad_request(api_client) -> None:
    now = _iso(datetime(2025, 1, 2, 0, 0, 0))
    payload = {
        "id": "invalid-tree",
        "name": "Invalid",
        "metadata": {
            "version": 1,
            "created_at": now,
            "updated_at": now,
            "layout": None,
            "owner_id": None,
        },
        "nodes": [
            {
                "id": "a",
                "label": "A",
                "type": "child",
                "position": {"x": 0, "y": 0},
                "highlight_state": "none",
                "relation_counts": {"up_count": 0, "down_count": 0},
            }
        ],
        "relations": [
            {
                "id": "r1",
                "source_node_id": "a",
                "target_node_id": "missing",
                "kind": "why",
                "created_at": now,
            }
        ],
        "owner_id": None,
    }

    resp = api_client.post("/api/trees/import", json={"tree": payload})
    assert resp.status_code == 400
    assert resp.headers.get("X-Correlation-ID")
