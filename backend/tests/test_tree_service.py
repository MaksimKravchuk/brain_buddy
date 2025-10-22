from __future__ import annotations

from app.schemas import TreeCreateRequest, TreeUpdateRequest


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
