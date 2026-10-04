from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event, Thread

import pytest

from app.exceptions import ConflictError, NotFoundError, StaleRevisionError
from app.schemas import (
    NodeCreateRequest,
    NodeResponse,
    Position,
    RelationCounts,
    RelationCreateRequest,
    TreeCreateRequest,
    TreeMetadata,
    TreeUpdateRequest,
)
from app.schemas.common import TimestampMetadata, ValidationState, VisualState
from app.schemas.domain import (
    NodeDocument,
    RelationDocument,
    RelationMetadata,
    TreeVersionRef,
    VersionDiffSummary,
)
from tests.conftest import TEST_OWNER_ID


def test_get_tree_reloads_persisted_state(tree_service, monkeypatch) -> None:
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
    # Always reload: another worker may have persisted a newer tree or deletion.
    assert load_calls == [tree.id, tree.id]
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


def test_019_FR_020_legacy_tree_defaults_revision_and_advances_once(
    tree_service,
) -> None:
    """Legacy trees start at revision/schema 1 and the next write advances once."""

    created = tree_service.create_tree(
        TreeCreateRequest(name="Legacy revision"), owner_id=TEST_OWNER_ID
    )
    assert created.revision == 1
    assert created.schema_version == 1

    tree_path = tree_service.tree_repo.tree_path(created.id)
    payload = json.loads(tree_path.read_text(encoding="utf-8"))
    payload.pop("revision")
    payload.pop("schema_version")
    tree_path.write_text(json.dumps(payload), encoding="utf-8")
    tree_service._cache.clear()

    legacy = tree_service.get_tree(created.id)
    assert legacy.revision == 1
    assert legacy.schema_version == 1

    updated = tree_service.mutate_tree(
        created.id,
        lambda current: current.model_copy(update={"description": "first write"}),
    )
    persisted = json.loads(tree_path.read_text(encoding="utf-8"))

    assert updated.revision == 2
    assert updated.schema_version == 1
    assert persisted["revision"] == 2
    assert persisted["schema_version"] == 1
    response = tree_service.to_response(updated)
    assert response.revision == 2
    assert response.schema_version == 1


def test_legacy_update_preserves_existing_schema_version(tree_service) -> None:
    """A compatibility write must not downgrade a newer persisted schema."""
    created = tree_service.create_tree(
        TreeCreateRequest(name="Preserve schema"), owner_id=TEST_OWNER_ID
    )
    tree_path = tree_service.tree_repo.tree_path(created.id)
    payload = json.loads(tree_path.read_text(encoding="utf-8"))
    payload["schema_version"] = 7
    tree_path.write_text(json.dumps(payload), encoding="utf-8")
    tree_service._cache.clear()

    current = tree_service.get_tree(created.id)
    public = tree_service.to_response(current)
    assert public.metadata.version == 7
    updated = tree_service.update_tree(
        created.id,
        TreeUpdateRequest(
            name=public.name,
            metadata=public.metadata,
            nodes=public.nodes,
            relations=public.relations,
        ),
        owner_id=TEST_OWNER_ID,
    )

    assert updated.schema_version == 7
    persisted = json.loads(tree_path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 7
    assert persisted["metadata"]["version"] == 7
    assert tree_service.to_response(updated).metadata.version == 7


def test_tree_metadata_owner_is_canonicalized_to_authenticated_owner(
    tree_service,
) -> None:
    metadata = TreeMetadata.from_timestamps(
        created_at=datetime(2026, 9, 21, 8, tzinfo=UTC),
        updated_at=datetime(2026, 9, 21, 8, tzinfo=UTC),
        owner_id="attacker",
    )

    created = tree_service.create_tree(
        TreeCreateRequest(name="Owned", metadata=metadata),
        owner_id=TEST_OWNER_ID,
    )
    exported = tree_service.to_account_export(created)

    assert created.metadata["owner_id"] == TEST_OWNER_ID
    assert tree_service.to_response(created).metadata.owner_id == TEST_OWNER_ID
    assert exported["metadata"]["owner_id"] == TEST_OWNER_ID


def test_account_export_preserves_exact_tree_shape_with_canonical_metadata(
    tree_service,
) -> None:
    timestamp = datetime(2026, 9, 21, 8, tzinfo=UTC)
    created = tree_service.create_tree(
        TreeCreateRequest(name="Exported"), owner_id=TEST_OWNER_ID
    )
    node_metadata = TimestampMetadata(
        created_at=timestamp,
        updated_at=timestamp,
        author=TEST_OWNER_ID,
    )
    node = NodeDocument(
        id="node_export",
        label="Export node",
        position=Position(x=10, y=20),
        metadata=node_metadata,
    )
    relation = RelationDocument(
        id="relation_export",
        source_id=node.id,
        target_id=node.id,
        metadata=RelationMetadata(
            created_at=timestamp,
            updated_at=timestamp,
            author=TEST_OWNER_ID,
        ),
    )
    version_ref = TreeVersionRef(
        id="version_export",
        label="Snapshot",
        created_at=timestamp,
    )
    tree = created.model_copy(
        update={
            "schema_version": 3,
            "description": "Export description",
            "metadata": {
                "version": 99,
                "layout": {"viewport": "wide"},
                "owner_id": "attacker",
                "extension": "preserved",
            },
            "nodes": [node],
            "relations": [relation],
            "version_refs": [version_ref],
        },
        deep=True,
    )

    assert tree_service.to_account_export(tree) == {
        "id": tree.id,
        "revision": tree.revision,
        "schema_version": 3,
        "title": "Exported",
        "description": "Export description",
        "metadata": {
            "version": 3,
            "layout": {"viewport": "wide"},
            "owner_id": TEST_OWNER_ID,
            "extension": "preserved",
        },
        "owner_id": TEST_OWNER_ID,
        "created_at": tree.created_at.isoformat(),
        "updated_at": tree.updated_at.isoformat(),
        "nodes": [node.model_dump(mode="json")],
        "relations": [relation.model_dump(mode="json")],
        "version_refs": [version_ref.model_dump(mode="json")],
    }


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


def test_full_tree_update_preserves_server_only_tree_data(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Preserve Server Data"), owner_id=TEST_OWNER_ID
    )
    metadata = TreeMetadata.from_timestamps(
        created_at=tree.created_at, updated_at=tree.updated_at, owner_id=TEST_OWNER_ID
    )
    node = NodeResponse(
        id="node_keep",
        label="Keep me",
        type="child",
        position=Position(x=1, y=2),
        highlight_state="none",
        relation_counts=RelationCounts(up_count=0, down_count=0),
    )
    updated = tree_service.update_tree(
        tree.id,
        TreeUpdateRequest(
            name="Preserve Server Data",
            metadata=metadata,
            nodes=[node],
            relations=[],
            owner_id=TEST_OWNER_ID,
        ),
        owner_id=TEST_OWNER_ID,
    )
    existing_node = updated.nodes[0]
    existing_node.validation = ValidationState(
        confidence=88,
        provider="test-provider",
        last_checked=updated.updated_at,
    )
    existing_node.visual = VisualState(color="#ffffff", highlight=True)
    existing_node.extra = {
        "type": "child",
        "highlight_state": "none",
        "server_only": "keep",
    }
    updated.version_refs = [
        TreeVersionRef(
            id="version_1",
            label="Before autosave",
            created_at=updated.updated_at,
            author="qa",
            notes="must survive full PUT",
            diff_summary=VersionDiffSummary(
                nodes_added=1,
                nodes_removed=0,
                nodes_modified=0,
                relations_added=0,
                relations_removed=0,
                relations_modified=0,
            ),
            conflict_count=0,
        )
    ]
    tree_service.tree_repo.save(updated)
    tree_service._cache.clear()

    round_trip = tree_service.update_tree(
        tree.id,
        TreeUpdateRequest(
            name="Renamed by autosave",
            metadata=TreeMetadata.from_timestamps(
                created_at=updated.created_at,
                updated_at=updated.updated_at,
                owner_id=TEST_OWNER_ID,
            ),
            nodes=[
                NodeResponse(
                    id="node_keep",
                    label="Keep me edited",
                    type="child",
                    position=Position(x=3, y=4),
                    highlight_state="none",
                    relation_counts=RelationCounts(up_count=0, down_count=0),
                )
            ],
            relations=[],
            owner_id=TEST_OWNER_ID,
        ),
        owner_id=TEST_OWNER_ID,
    )

    assert round_trip.version_refs[0].id == "version_1"
    assert round_trip.nodes[0].label == "Keep me edited"
    assert round_trip.nodes[0].validation is not None
    assert round_trip.nodes[0].validation.provider == "test-provider"
    assert round_trip.nodes[0].visual is not None
    assert round_trip.nodes[0].visual.highlight is True
    assert round_trip.nodes[0].extra is not None
    assert round_trip.nodes[0].extra["server_only"] == "keep"


def test_update_tree_rejects_stale_full_tree_payload(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Concurrent Tree"), owner_id=TEST_OWNER_ID
    )
    client_seen_metadata = TreeMetadata.from_timestamps(
        created_at=tree.created_at, updated_at=tree.updated_at, owner_id=TEST_OWNER_ID
    )

    fresh = tree_service.update_tree(
        tree.id,
        TreeUpdateRequest(
            name="Newer server copy",
            metadata=client_seen_metadata,
            nodes=[],
            relations=[],
            owner_id=TEST_OWNER_ID,
        ),
        owner_id=TEST_OWNER_ID,
    )

    assert fresh.updated_at > client_seen_metadata.updated_at
    with pytest.raises(ConflictError):
        tree_service.update_tree(
            tree.id,
            TreeUpdateRequest(
                name="Stale autosave",
                metadata=client_seen_metadata,
                nodes=[],
                relations=[],
                owner_id=TEST_OWNER_ID,
            ),
            owner_id=TEST_OWNER_ID,
        )


def test_atomic_mutation_preserves_the_latest_tree_after_a_full_tree_update(
    tree_service,
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Concurrent writers"), owner_id=TEST_OWNER_ID
    )
    metadata = TreeMetadata.from_timestamps(
        created_at=tree.created_at, updated_at=tree.updated_at, owner_id=TEST_OWNER_ID
    )
    writers_ready = Barrier(2)

    def full_tree_update():
        writers_ready.wait(timeout=2)
        return tree_service.update_tree(
            tree.id,
            TreeUpdateRequest(
                name="Full tree update",
                metadata=metadata,
                nodes=[],
                relations=[],
                owner_id=TEST_OWNER_ID,
            ),
            owner_id=TEST_OWNER_ID,
        )

    def mutate_description():
        writers_ready.wait(timeout=2)
        return tree_service.tree_repo.mutate(
            tree.id,
            update=lambda current: current.model_copy(
                update={"description": "concurrent change"}, deep=True
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        full_tree = executor.submit(full_tree_update)
        mutation = executor.submit(mutate_description)

    assert mutation.exception() is None
    full_tree_error = full_tree.exception()
    assert full_tree_error is None or isinstance(full_tree_error, ConflictError)
    assert tree_service.tree_repo.load(tree.id).description == "concurrent change"


def test_get_tree_reloads_changes_from_another_service_instance(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Cross-process freshness"), owner_id=TEST_OWNER_ID
    )

    tree_service.tree_repo.mutate(
        tree.id,
        update=lambda current: current.model_copy(
            update={"description": "persisted elsewhere"}
        ),
    )

    assert tree_service.get_tree(tree.id).description == "persisted elsewhere"


def test_tree_mutation_never_moves_updated_at_backwards(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Monotonic timestamp"), owner_id=TEST_OWNER_ID
    )

    updated = tree_service.mutate_tree(
        tree.id,
        lambda current: current.model_copy(update={"description": "updated"}),
        timestamp=tree.updated_at,
    )

    assert updated.updated_at > tree.updated_at


def test_delete_cannot_resurrect_a_tree_from_an_inflight_mutation(
    tree_service, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="No resurrection"), owner_id=TEST_OWNER_ID
    )
    mutation_started_sync = Event()
    release_sync = Event()
    original_sync = tree_service._sync_index

    def block_sync(updated_tree):
        mutation_started_sync.set()
        assert release_sync.wait(timeout=2)
        original_sync(updated_tree)

    monkeypatch.setattr(tree_service, "_sync_index", block_sync)

    with ThreadPoolExecutor(max_workers=2) as executor:
        mutation = executor.submit(
            tree_service.mutate_tree,
            tree.id,
            lambda current: current.model_copy(update={"description": "changed"}),
        )
        assert mutation_started_sync.wait(timeout=2)
        deletion = executor.submit(
            tree_service.delete_tree, tree.id, owner_id=TEST_OWNER_ID
        )
        release_sync.set()
        mutation.result(timeout=2)
        deletion.result(timeout=2)

    with pytest.raises(NotFoundError):
        tree_service.get_tree(tree.id)
    assert not tree_service.tree_repo.tree_dir(tree.id).exists()
    assert tree.id not in {entry.id for entry in tree_service.index_repo.load_all()}


def test_delete_tree(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Deletable"), owner_id=TEST_OWNER_ID
    )
    tree_service.delete_tree(tree.id, owner_id=TEST_OWNER_ID)

    entries = tree_service.list_trees(owner_id=TEST_OWNER_ID)
    assert tree.id not in {entry.id for entry in entries}


def test_delete_revision_check_and_unlink_share_tree_lock(tree_service) -> None:
    """A legacy update cannot land between delete validation and unlink."""
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Delete race"), owner_id=TEST_OWNER_ID
    )
    update_started = Event()
    update_finished = Event()
    update_errors: list[Exception] = []
    updater_threads: list[Thread] = []

    def legacy_update() -> None:
        update_started.set()
        try:
            tree_service.tree_repo.mutate(
                tree.id,
                update=lambda current: current.model_copy(
                    update={"description": "newer legacy revision"}, deep=True
                ),
            )
        except Exception as exc:  # the expected result is a deleted tree
            update_errors.append(exc)
        finally:
            update_finished.set()

    def after_revision_check(_current) -> None:
        updater = Thread(target=legacy_update)
        updater_threads.append(updater)
        updater.start()
        assert update_started.wait(timeout=2)
        assert not update_finished.wait(timeout=0.1)

    tree_service.tree_repo.delete_if_current(
        tree.id,
        owner_id=TEST_OWNER_ID,
        expected_revision=tree.revision,
        before_delete=after_revision_check,
    )

    for updater in updater_threads:
        updater.join(timeout=2)
    assert update_finished.is_set()
    assert len(update_errors) == 1
    assert isinstance(update_errors[0], NotFoundError)
    with pytest.raises(NotFoundError):
        tree_service.get_tree(tree.id)


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


def test_tree_response_preserves_metadata_owner_and_directional_relation_counts(
    tree_service, node_service, relation_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Exact response"), owner_id=TEST_OWNER_ID
    )
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(
            label="A",
            type="parent",
            position=Position(x=1, y=2),
            highlight_state="cause_candidate",
        ),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=3, y=4)),
    )
    node_c, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="C", type="child", position=Position(x=5, y=6)),
    )
    first_relation, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )
    second_relation, persisted = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_c.id, target_node_id=node_a.id, kind="why"
        ),
    )
    persisted = tree_service.tree_repo.mutate(
        tree.id,
        update=lambda current: current.model_copy(
            update={
                "metadata": {
                    "version": 4,
                    "layout": {"viewport": "wide"},
                    "owner_id": "ignored-metadata-owner",
                }
            },
            deep=True,
        ),
    )

    response = tree_service.to_response(persisted)
    nodes = {node.id: node for node in response.nodes}

    assert response.id == tree.id
    assert response.name == "Exact response"
    assert response.owner_id == TEST_OWNER_ID
    assert response.metadata.model_dump(mode="json") == {
        "version": 1,
        "created_at": persisted.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": persisted.updated_at.isoformat().replace("+00:00", "Z"),
        "layout": {"viewport": "wide"},
        "owner_id": TEST_OWNER_ID,
    }
    assert nodes[node_a.id].model_dump() == {
        "id": node_a.id,
        "label": "A",
        "type": "parent",
        "position": {"x": 1.0, "y": 2.0},
        "highlight_state": "cause_candidate",
        "relation_counts": {"up_count": 1, "down_count": 1},
    }
    assert nodes[node_b.id].relation_counts == RelationCounts(up_count=0, down_count=1)
    assert nodes[node_c.id].relation_counts == RelationCounts(up_count=1, down_count=0)
    assert [relation.id for relation in response.relations] == [
        first_relation.id,
        second_relation.id,
    ]
    assert response.relations[0].model_dump() == {
        "id": first_relation.id,
        "source_node_id": node_a.id,
        "target_node_id": node_b.id,
        "kind": "why",
        "created_at": first_relation.metadata.created_at,
    }


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


def test_create_tree_persists_schema_version_and_command_id(tree_service) -> None:
    command_id = "a" * 64

    tree = tree_service.create_tree(
        TreeCreateRequest(name="Versioned create", schema_version=6),
        owner_id=TEST_OWNER_ID,
        command_id=command_id,
        schema_version=7,
    )
    persisted = tree_service.tree_repo.load(tree.id)

    assert tree.schema_version == 7
    assert tree.metadata == {"version": 7, "owner_id": TEST_OWNER_ID}
    assert persisted.schema_version == 7
    assert persisted.metadata == {"version": 7, "owner_id": TEST_OWNER_ID}
    assert tree.last_command_id == command_id
    assert persisted.last_command_id == command_id


def test_create_tree_uses_payload_schema_version_when_not_overridden(
    tree_service,
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Payload version", schema_version=7),
        owner_id=TEST_OWNER_ID,
    )

    assert tree.schema_version == 7
    assert tree.metadata == {"version": 7, "owner_id": TEST_OWNER_ID}
    persisted = tree_service.tree_repo.load(tree.id)
    assert persisted.schema_version == 7
    assert persisted.metadata == {"version": 7, "owner_id": TEST_OWNER_ID}


def test_create_tree_uses_metadata_schema_version_when_top_level_absent(
    tree_service,
) -> None:
    baseline = tree_service.create_tree(
        TreeCreateRequest(name="Timestamp source"), owner_id=TEST_OWNER_ID
    )
    metadata = TreeMetadata(
        version=8,
        created_at=baseline.created_at,
        updated_at=baseline.updated_at,
        owner_id=TEST_OWNER_ID,
    )

    tree = tree_service.create_tree(
        TreeCreateRequest(name="Metadata version", metadata=metadata),
        owner_id=TEST_OWNER_ID,
    )

    assert tree.schema_version == 8
    assert tree.metadata == {"version": 8, "owner_id": TEST_OWNER_ID}
    persisted = tree_service.tree_repo.load(tree.id)
    assert persisted.schema_version == 8
    assert persisted.metadata == {"version": 8, "owner_id": TEST_OWNER_ID}


def test_prepare_create_tree_deep_copies_request_state(tree_service) -> None:
    request = TreeCreateRequest(
        name="Isolated create",
        nodes=[
            NodeResponse(
                id="node-isolated",
                label="Original",
                type="child",
                position=Position(x=1, y=2),
                highlight_state="none",
                relation_counts=RelationCounts(up_count=0, down_count=0),
            )
        ],
    )

    prepared = tree_service.prepare_create_tree(
        request,
        owner_id=TEST_OWNER_ID,
        tree_id="tree-isolated",
        command_id="d" * 64,
        schema_version=1,
    )
    prepared.nodes[0].position.x = 99
    prepared.nodes[0].extra["type"] = "parent"

    assert request.nodes[0].position.x == 1
    assert request.nodes[0].type == "child"


def test_tree_response_preserves_persisted_schema_version(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Versioned response"),
        owner_id=TEST_OWNER_ID,
        schema_version=9,
    )

    response = tree_service.to_response(tree)

    assert response.schema_version == 9


def test_update_tree_forwards_revision_and_command_id(tree_service) -> None:
    command_id = "b" * 64
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Revisioned update"), owner_id=TEST_OWNER_ID
    )
    metadata = TreeMetadata.from_timestamps(
        created_at=tree.created_at,
        updated_at=tree.updated_at,
        owner_id=TEST_OWNER_ID,
    )

    updated = tree_service.update_tree(
        tree.id,
        TreeUpdateRequest(
            name="Revisioned update",
            expected_revision=tree.revision,
            metadata=metadata,
            nodes=[],
            relations=[],
        ),
        owner_id=TEST_OWNER_ID,
        command_id=command_id,
    )

    assert updated.revision == tree.revision + 1
    assert updated.last_command_id == command_id
    assert tree_service.tree_repo.load(tree.id).last_command_id == command_id

    stale_metadata = TreeMetadata.from_timestamps(
        created_at=tree.created_at,
        updated_at=updated.updated_at,
        owner_id=TEST_OWNER_ID,
    )
    with pytest.raises(StaleRevisionError):
        tree_service.update_tree(
            tree.id,
            TreeUpdateRequest(
                name="Stale revision",
                expected_revision=tree.revision,
                metadata=stale_metadata,
                nodes=[],
                relations=[],
            ),
            owner_id=TEST_OWNER_ID,
            command_id="c" * 64,
        )


def test_create_tree_resolves_actor_owner_into_metadata(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Owner metadata"), owner_id=TEST_OWNER_ID
    )

    assert tree.owner_id == TEST_OWNER_ID
    assert tree.metadata is not None
    assert tree.metadata["owner_id"] == TEST_OWNER_ID


def test_resolve_metadata_uses_actor_owner_when_payload_metadata_absent(
    tree_service,
) -> None:
    resolved = tree_service._resolve_metadata(None, owner_id=TEST_OWNER_ID)

    assert resolved.owner_id == TEST_OWNER_ID


def test_response_ignores_invalid_legacy_metadata_owner(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Invalid legacy owner"), owner_id=TEST_OWNER_ID
    )
    legacy = tree.model_copy(
        update={
            "owner_id": None,
            "metadata": {"version": 1, "owner_id": {"legacy": "invalid"}},
        },
        deep=True,
    )

    response = tree_service.to_response(legacy)

    assert response.owner_id is None
    assert response.metadata.owner_id is None
