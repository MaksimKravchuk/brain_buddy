from __future__ import annotations

import json

from app.schemas import TreeCreateRequest, TreeMetadata, TreeUpdateRequest
from tests.conftest import TEST_OWNER_ID


def test_get_tree_uses_cache(tree_service, monkeypatch) -> None:
    payload = TreeCreateRequest(name="Cached Tree")
    tree = tree_service.create_tree(payload, owner_id=TEST_OWNER_ID)

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
    payload = TreeCreateRequest(name="Test Tree")
    tree = tree_service.create_tree(payload, owner_id=TEST_OWNER_ID)

    assert tree.title == "Test Tree"
    assert tree.nodes == []
    assert tree.relations == []

    fetched = tree_service.get_tree(tree.id)
    assert fetched.id == tree.id
    assert fetched.title == "Test Tree"


def test_list_and_update_tree(tree_service) -> None:
    first = tree_service.create_tree(
        TreeCreateRequest(name="First"), owner_id=TEST_OWNER_ID
    )
    _second = tree_service.create_tree(
        TreeCreateRequest(name="Second"), owner_id=TEST_OWNER_ID
    )

    entries = tree_service.list_trees(owner_id=TEST_OWNER_ID)
    assert len(entries) == 2
    assert {entry.id for entry in entries} == {first.id, _second.id}

    metadata = TreeMetadata.from_timestamps(
        created_at=first.created_at, updated_at=first.updated_at
    )
    updated = tree_service.update_tree(
        first.id,
        TreeUpdateRequest(
            name="Updated First",
            metadata=metadata,
            nodes=[],
            relations=[],
            owner_id=None,
        ),
        owner_id=TEST_OWNER_ID,
    )
    assert updated.title == "Updated First"
    assert updated.updated_at >= updated.created_at


def test_delete_tree(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Deletable"), owner_id=TEST_OWNER_ID
    )
    tree_service.delete_tree(tree.id, owner_id=TEST_OWNER_ID)

    entries = tree_service.list_trees(owner_id=TEST_OWNER_ID)
    assert tree.id not in {entry.id for entry in entries}


def test_get_tree_ignores_unknown_persisted_fields(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Legacy Compatible"), owner_id=TEST_OWNER_ID
    )
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


def _persist_legacy_node(tree_service, tree_id: str, extra: dict[str, object]) -> None:
    """Append a node with the given ``extra`` payload to the stored tree."""

    tree_path = tree_service.tree_repo.tree_path(tree_id)
    payload = json.loads(tree_path.read_text(encoding="utf-8"))
    payload["nodes"].append(
        {
            "id": "node_legacy",
            "label": "Legacy Node",
            "position": {"x": 0, "y": 0},
            "metadata": {
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "author": None,
            },
            "extra": extra,
        }
    )
    tree_path.write_text(json.dumps(payload), encoding="utf-8")
    tree_service._cache.clear()


def test_node_to_response_coerces_legacy_extra_values(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Legacy Extra"), owner_id=TEST_OWNER_ID
    )
    _persist_legacy_node(
        tree_service,
        tree.id,
        {"type": "root", "highlight_state": "caused"},
    )

    loaded = tree_service.get_tree(tree.id)
    response = tree_service.node_to_response(loaded, "node_legacy")

    assert response.type == "child"
    assert response.highlight_state == "none"


def test_node_to_response_preserves_valid_extra_values(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Valid Extra"), owner_id=TEST_OWNER_ID
    )
    _persist_legacy_node(
        tree_service,
        tree.id,
        {"type": "parent", "highlight_state": "cause_candidate"},
    )

    loaded = tree_service.get_tree(tree.id)
    response = tree_service.node_to_response(loaded, "node_legacy")

    assert response.type == "parent"
    assert response.highlight_state == "cause_candidate"


def test_node_to_response_logs_when_coercing(tree_service, caplog) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Legacy Logged"), owner_id=TEST_OWNER_ID
    )
    _persist_legacy_node(
        tree_service,
        tree.id,
        {"type": "root", "highlight_state": "caused"},
    )

    loaded = tree_service.get_tree(tree.id)

    with caplog.at_level("WARNING", logger="app.services.tree_service"):
        tree_service.node_to_response(loaded, "node_legacy")

    messages = [record.getMessage() for record in caplog.records]
    assert any("invalid extra.type" in message for message in messages)
    assert any("invalid extra.highlight_state" in message for message in messages)


def test_node_to_response_handles_non_dict_extra(tree_service, caplog) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Non Dict Extra"), owner_id=TEST_OWNER_ID
    )
    _persist_legacy_node(
        tree_service,
        tree.id,
        {"type": "child", "highlight_state": "none"},
    )

    loaded = tree_service.get_tree(tree.id)
    # Bypass pydantic's dict-typed ``extra`` field: simulate an in-memory
    # document whose ``extra`` was corrupted into a non-dict shape.
    legacy_node = next(node for node in loaded.nodes if node.id == "node_legacy")
    legacy_node.extra = ["not", "a", "dict"]  # type: ignore[assignment]

    with caplog.at_level("WARNING", logger="app.services.tree_service"):
        response = tree_service.node_to_response(loaded, "node_legacy")

    assert response.type == "child"
    assert response.highlight_state == "none"
    messages = [record.getMessage() for record in caplog.records]
    assert any("non-dict extra" in message for message in messages)
