"""Ownership isolation tests: user A never sees or touches user B's data."""

from __future__ import annotations


def _make_tree(client, name: str) -> str:
    resp = client.post("/api/trees", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_list_trees_is_filtered_by_owner(second_api_client) -> None:
    client_a, client_b = second_api_client
    tree_a = _make_tree(client_a, "Alice tree")
    tree_b = _make_tree(client_b, "Bob tree")

    list_a = client_a.get("/api/trees").json()
    list_b = client_b.get("/api/trees").json()

    ids_a = {item["id"] for item in list_a}
    ids_b = {item["id"] for item in list_b}
    assert tree_a in ids_a and tree_b not in ids_a
    assert tree_b in ids_b and tree_a not in ids_b


def test_wrong_owner_sees_404_not_403(second_api_client) -> None:
    client_a, client_b = second_api_client
    tree_a = _make_tree(client_a, "Alice tree")

    # User B should not be able to distinguish "doesn't exist" from
    # "belongs to someone else".
    get_resp = client_b.get(f"/api/trees/{tree_a}")
    assert get_resp.status_code == 404

    delete_resp = client_b.delete(f"/api/trees/{tree_a}")
    assert delete_resp.status_code == 404

    update_resp = client_b.put(
        f"/api/trees/{tree_a}",
        json={
            "name": "hijacked",
            "metadata": {
                "version": 1,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "layout": None,
                "owner_id": None,
            },
            "nodes": [],
            "relations": [],
            "owner_id": None,
        },
    )
    assert update_resp.status_code == 404


def test_wrong_owner_cannot_mutate_children(second_api_client) -> None:
    client_a, client_b = second_api_client
    tree_a = _make_tree(client_a, "Alice tree")

    node_resp = client_b.post(
        f"/api/trees/{tree_a}/nodes",
        json={
            "label": "injected",
            "type": "child",
            "position": {"x": 0, "y": 0},
            "highlight_state": "none",
        },
    )
    assert node_resp.status_code == 404

    validate_resp = client_b.post(f"/api/trees/{tree_a}/validate/some-node", json={})
    assert validate_resp.status_code == 404

    versions_resp = client_b.get(f"/api/trees/{tree_a}/versions")
    assert versions_resp.status_code == 404


def test_import_assigns_current_user_as_owner(api_client) -> None:
    payload = {
        "id": "tree-import-owner",
        "name": "Imported",
        "metadata": {
            "version": 1,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "layout": None,
            "owner_id": "attacker",
        },
        "nodes": [],
        "relations": [],
        "owner_id": "attacker",
    }
    resp = api_client.post("/api/trees/import", json={"tree": payload})
    assert resp.status_code == 201
    body = resp.json()
    assert body["owner_id"] != "attacker"
    assert body["owner_id"] is not None
