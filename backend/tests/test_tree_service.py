from __future__ import annotations

import json

from app.schemas import TreeCreateRequest, TreeUpdateRequest


def test_get_tree_uses_cache(tree_service, monkeypatch) -> None:
    payload = TreeCreateRequest(title="Cached Tree", description=None)
    tree = tree_service.create_tree(payload)

    load_calls: list[str] = []
    original_load = tree_service.tree_repo.load

    tree_service._cache.clear()

    def tracked_load(tree_id: str):
        load_calls.append(tree_id)
        return original_load(tree_id)

    monkeypatch.setattr(tree_service.tree_repo, "load", tracked_load)

    first = tree_service.get_tree(tree.id)
    second = tree_service.get_tree(tree.id)

    assert first.id == tree.id
    assert second.id == tree.id
    # Should only hit the repository once thanks to caching
    assert load_calls == [tree.id]
    # Returned documents are safe copies
    assert first is not second


def test_create_and_retrieve_tree(tree_service) -> None:
    payload = TreeCreateRequest(title="Test Tree", description="Sample")
    tree = tree_service.create_tree(payload)

    assert tree.title == "Test Tree"
    assert tree.description == "Sample"
    assert tree.nodes == []
    assert tree.relations == []

    fetched = tree_service.get_tree(tree.id)
    assert fetched.id == tree.id
    assert fetched.title == "Test Tree"


def test_list_and_update_tree(tree_service) -> None:
    first = tree_service.create_tree(TreeCreateRequest(title="First", description=None))
    _second = tree_service.create_tree(TreeCreateRequest(title="Second", description=None))

    entries = tree_service.list_trees()
    assert len(entries) == 2
    assert {entry.id for entry in entries} == {first.id, _second.id}

    updated = tree_service.update_tree(first.id, TreeUpdateRequest(description="Updated"))
    assert updated.description == "Updated"
    assert updated.updated_at >= updated.created_at


def test_delete_tree(tree_service) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(title="Deletable", description=None))
    tree_service.delete_tree(tree.id)

    entries = tree_service.list_trees()
    assert tree.id not in {entry.id for entry in entries}


def test_get_tree_ignores_unknown_persisted_fields(tree_service) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(title="Legacy Compatible", description=None))
    tree_service._cache.clear()

    tree_path = tree_service.tree_repo.tree_path(tree.id)
    payload = json.loads(tree_path.read_text(encoding="utf-8"))

    payload["legacy_flag"] = True
    payload["nodes"].append(
        {
            "id": "node_legacy",
            "label": "Legacy Node",
            "position": {"x": 1, "y": 2},
            "metadata": {
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "author": None,
            },
            "incoming_count": 42,
            "legacy_blob": {"foo": "bar"},
        }
    )

    tree_path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = tree_service.get_tree(tree.id)
    dump = loaded.model_dump(mode="python")

    assert dump["nodes"][0]["id"] == "node_legacy"
    assert "incoming_count" not in dump["nodes"][0]
    assert "legacy_blob" not in dump["nodes"][0]
    assert "legacy_flag" not in dump
