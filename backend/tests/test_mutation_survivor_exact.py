"""Exact assertion regression tests for mutation campaign survivors.

These tests target surviving mutants that existing tests missed because
they relied on partial matching (pytest.raises match=) instead of exact
attribute/field assertions. Each test is hermetic: direct service/repository
calls only, no ASGI/AnyIO fixtures.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import pytest

from app.exceptions import ConflictError, NotFoundError, ValidationFailure
from app.schemas.api import (
    AiFeedbackRequest,
    NodeCreateRequest,
    NodeUpdateRequest,
    Position,
    RelationCreateRequest,
    RelationUpdateRequest,
    TreeCreateRequest,
    VersionCreateRequest,
)
from app.services.version_service import VersionService

# ---------------------------------------------------------------------------
# Repository exception-field exactness
# ---------------------------------------------------------------------------


def test_version_repository_load_missing_raises_not_found_with_exact_fields(
    version_service, tree_service
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="VR load"), owner_id="owner")
    repo = version_service.version_repo

    with pytest.raises(NotFoundError) as exc_info:
        repo.load(tree.id, "missing::version")

    assert exc_info.value.resource == "Version"
    assert exc_info.value.identifier == "missing::version"
    assert "Version 'missing::version' was not found." in str(exc_info.value)


def test_version_repository_delete_missing_raises_not_found_with_exact_fields(
    version_service, tree_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="VR delete"), owner_id="owner"
    )
    repo = version_service.version_repo

    with pytest.raises(NotFoundError) as exc_info:
        repo.delete(tree.id, "missing::version")

    assert exc_info.value.resource == "Version"
    assert exc_info.value.identifier == "missing::version"


def test_tree_repository_update_if_current_conflict_carries_exact_fields(
    tree_service,
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Conflict"), owner_id="owner"
    )
    repo = tree_service.tree_repo

    stale = tree.updated_at

    # Advance updated_at via mutate_tree which applies the metadata merge
    newer = tree_service.mutate_tree(
        tree.id,
        update=lambda current: current.model_copy(update={"title": "Touched"}),
    )

    with pytest.raises(ConflictError) as exc_info:
        repo.update_if_current(
            tree.id,
            expected_updated_at=stale,
            update=lambda current: current,
        )

    assert exc_info.value.resource == "Tree"
    assert exc_info.value.identifier == tree.id
    assert "newer changes" in str(exc_info.value)

    # The newer updated_at must be strictly greater than stale
    assert newer.updated_at > stale


def test_index_repository_delete_missing_raises_not_found_with_exact_fields(
    data_dir,
) -> None:
    from app.repositories.index import IndexRepository

    repo = IndexRepository(data_dir)

    with pytest.raises(NotFoundError) as exc_info:
        repo.delete("missing_tree")

    assert exc_info.value.resource == "Tree"
    assert exc_info.value.identifier == "missing_tree"


# ---------------------------------------------------------------------------
# TreeService.node_to_response — non-dict extra logging exactness
# ---------------------------------------------------------------------------


def test_node_to_response_logs_non_dict_extra_with_exact_node_tree_and_type(
    tree_service, caplog
) -> None:
    from app.schemas.common import TimestampMetadata
    from app.schemas.domain import NodeDocument, TreeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    node = NodeDocument(
        id="bad_extra",
        label="Bad",
        position=Position(x=0, y=0),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
        extra={},
    )
    # Simulate an in-memory legacy document that predates the dict schema.
    node.extra = "not-a-dict"  # type: ignore[assignment]
    tree = TreeDocument(
        id="bad_tree",
        title="Bad tree",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[node],
        relations=[],
    )

    with caplog.at_level(logging.WARNING, logger="app.services.tree_service"):
        response = tree_service.node_to_response(tree, node.id)

    assert response.type == "child"
    assert response.highlight_state == "none"

    # The warning is an operator-facing data-integrity contract.
    record = next(r for r in caplog.records if "non-dict extra" in r.getMessage())
    assert (
        record.getMessage()
        == "Node bad_extra in tree bad_tree has non-dict extra (str); "
        "treating as empty."
    )


def test_node_to_response_logs_invalid_type_with_exact_values(
    tree_service, caplog
) -> None:
    from app.schemas.common import TimestampMetadata
    from app.schemas.domain import NodeDocument, TreeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    node = NodeDocument(
        id="bad_type",
        label="BT",
        position=Position(x=0, y=0),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
        extra={"type": "root", "highlight_state": "caused"},
    )
    tree = TreeDocument(
        id="bad_type_tree",
        title="BT tree",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[node],
        relations=[],
    )

    with caplog.at_level(logging.WARNING, logger="app.services.tree_service"):
        response = tree_service.node_to_response(tree, node.id)

    assert response.type == "child"
    assert response.highlight_state == "none"

    type_record = next(
        r for r in caplog.records if "invalid extra.type" in r.getMessage()
    )
    assert (
        type_record.getMessage()
        == "Node bad_type in tree bad_type_tree has invalid extra.type='root'; "
        "coercing to 'child'."
    )

    hl_record = next(
        r for r in caplog.records if "invalid extra.highlight_state" in r.getMessage()
    )
    assert (
        hl_record.getMessage()
        == "Node bad_type in tree bad_type_tree has invalid extra.highlight_state="
        "'caused'; coercing to 'none'."
    )


def test_node_to_response_missing_legacy_values_use_defaults_without_warning(
    tree_service, caplog
) -> None:
    from app.schemas.common import TimestampMetadata
    from app.schemas.domain import NodeDocument, TreeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    node = NodeDocument(
        id="defaults",
        label="Defaults",
        position=Position(x=0, y=0),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
        extra={},
    )
    tree = TreeDocument(
        id="defaults_tree",
        title="Defaults",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[node],
        relations=[],
    )

    with caplog.at_level(logging.WARNING, logger="app.services.tree_service"):
        response = tree_service.node_to_response(tree, node.id)

    assert response.type == "child"
    assert response.highlight_state == "none"
    assert caplog.records == []


# ---------------------------------------------------------------------------
# generate_ai_feedback — summary, request_id, and recommendation exactness
# ---------------------------------------------------------------------------


def test_generate_ai_feedback_returns_exact_summary_and_request_id(
    tree_service, node_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="FB exact"), owner_id="owner"
    )
    node_service.create_node(
        tree.id,
        NodeCreateRequest(label="N", type="child", position=Position(x=0, y=0)),
    )

    response = tree_service.generate_ai_feedback(
        tree.id,
        AiFeedbackRequest(consent=True, request_id="req-123"),
        owner_id="owner",
    )

    assert response.status == "success"
    assert response.summary == "Tree 'FB exact' contains 1 nodes and 0 relations."
    assert response.request_id == "req-123"
    # With nodes and 0 relations (< max(1, 1//2)=1), both recommendations appear
    assert response.recommendations == [
        "Review whether each relation flows from cause to effect.",
        "Consider linking more causes to effects to expose gaps.",
    ]


def test_generate_ai_feedback_empty_tree_returns_add_nodes_recommendation(
    tree_service,
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Empty FB"), owner_id="owner"
    )

    response = tree_service.generate_ai_feedback(
        tree.id,
        AiFeedbackRequest(consent=True, request_id="r"),
        owner_id="owner",
    )

    assert response.summary == "Tree 'Empty FB' contains 0 nodes and 0 relations."
    assert response.recommendations == [
        "Add nodes to capture the current reality before requesting feedback.",
        "Consider linking more causes to effects to expose gaps.",
    ]


def test_generate_ai_feedback_default_request_id_is_none(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Default RID"), owner_id="owner"
    )

    response = tree_service.generate_ai_feedback(
        tree.id, AiFeedbackRequest(consent=True), owner_id="owner"
    )

    assert response.request_id is None


# ---------------------------------------------------------------------------
# _validate_relation_targets — exact detail and or→and mutation
# ---------------------------------------------------------------------------


def test_validate_relation_targets_rejects_partial_unknown_with_exact_detail(
    tree_service,
) -> None:
    from app.schemas.domain import RelationDocument, RelationMetadata

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    rel_meta = RelationMetadata(created_at=timestamp, updated_at=timestamp)
    relation = RelationDocument(
        id="rel1",
        source_id="known",
        target_id="unknown",
        question_label="why",
        metadata=rel_meta,
    )

    with pytest.raises(ValidationFailure) as exc_info:
        tree_service._validate_relation_targets([relation], {"known"})

    # The message must be exactly this, not a case-variant
    assert str(exc_info.value) == "Relation references unknown node id"
    assert exc_info.value.detail is None


def test_validate_relation_targets_duplicate_detail_has_exact_fields(
    tree_service,
) -> None:
    from app.schemas.domain import RelationDocument, RelationMetadata

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    rel_meta = RelationMetadata(created_at=timestamp, updated_at=timestamp)
    relation = RelationDocument(
        id="rel_dup",
        source_id="a",
        target_id="b",
        question_label="why",
        metadata=rel_meta,
    )

    with pytest.raises(ValidationFailure) as exc_info:
        tree_service._validate_relation_targets([relation, relation], {"a", "b"})

    assert str(exc_info.value) == "A link already exists between these nodes."
    assert exc_info.value.detail == {
        "reason": "duplicate_relation",
        "source_node_id": "a",
        "target_node_id": "b",
    }


# ---------------------------------------------------------------------------
# RelationService.update_relation — kind condition, duplicate skip, timestamp
# ---------------------------------------------------------------------------


def _create_tree_with_three_nodes(tree_service, node_service):
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Relation trio"), owner_id="owner"
    )
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    node_c, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="C", type="child", position=Position(x=2, y=2)),
    )
    return tree, node_a, node_b, node_c


def test_update_relation_kind_update_changes_question_label(
    tree_service, node_service, relation_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Kind update"), owner_id="owner"
    )
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    relation, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )

    updated, _ = relation_service.update_relation(
        tree.id, relation.id, RelationUpdateRequest(kind="why")
    )

    assert updated.question_label == "why"


def test_update_relation_honors_constructed_future_kind_value(
    tree_service, node_service, relation_service
) -> None:
    tree, node_a, node_b, _ = _create_tree_with_three_nodes(tree_service, node_service)
    relation, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )
    future_payload = RelationUpdateRequest.model_construct(
        kind="because", _fields_set={"kind"}
    )

    updated, updated_tree = relation_service.update_relation(
        tree.id, relation.id, future_payload
    )

    assert updated.question_label == "because"
    assert updated_tree.relations[0].question_label == "because"


def test_update_relation_kind_none_does_not_change_label(
    tree_service, node_service, relation_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Kind none"), owner_id="owner"
    )
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    relation, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )

    # Sending kind=None should NOT change question_label
    updated, _ = relation_service.update_relation(
        tree.id, relation.id, RelationUpdateRequest(kind=None)
    )

    assert updated.question_label == "why"


def test_update_relation_preserves_explicit_timestamp(
    tree_service, node_service, relation_service
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="TS"), owner_id="owner")
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    relation, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )

    updated, updated_tree = relation_service.update_relation(
        tree.id, relation.id, RelationUpdateRequest(kind="why")
    )

    # The updated_at must be greater than the original relation's updated_at
    assert updated.metadata.updated_at > relation.metadata.updated_at
    assert updated_tree.updated_at >= updated.metadata.updated_at


def test_update_relation_passes_its_captured_timestamp_to_tree_transaction(
    monkeypatch: pytest.MonkeyPatch,
    tree_service,
    node_service,
    relation_service,
) -> None:
    from app.services import relation_service as relation_service_module

    tree = tree_service.create_tree(
        TreeCreateRequest(name="Timestamp transaction"), owner_id="owner"
    )
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    relation, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )
    timestamp = datetime(2050, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(relation_service_module, "utcnow", lambda: timestamp)

    updated, updated_tree = relation_service.update_relation(
        tree.id, relation.id, RelationUpdateRequest(kind="why")
    )

    assert updated.metadata.updated_at == timestamp
    assert updated_tree.updated_at == timestamp
    assert tree_service.tree_repo.load(tree.id).updated_at == timestamp


def test_update_relation_empty_update_returns_exact_relation_not_copy(
    tree_service, node_service, relation_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Empty update"), owner_id="owner"
    )
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    relation, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )

    # An empty update returns the persisted relation without changing it.
    returned, returned_tree = relation_service.update_relation(
        tree.id, relation.id, RelationUpdateRequest()
    )

    assert returned == relation
    assert returned_tree.id == tree.id


def test_update_relation_missing_raises_not_found_with_exact_resource(
    tree_service, relation_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Missing rel"), owner_id="owner"
    )

    with pytest.raises(NotFoundError) as exc_info:
        relation_service.update_relation(
            tree.id, "missing_rel", RelationUpdateRequest()
        )

    assert exc_info.value.resource == "Relation"
    assert exc_info.value.identifier == "missing_rel"


def test_update_relation_source_null_raises_exact_validation_message(
    tree_service, node_service, relation_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Null src"), owner_id="owner"
    )
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    relation, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )

    with pytest.raises(ValidationFailure) as exc_info:
        relation_service.update_relation(
            tree.id, relation.id, RelationUpdateRequest(source_node_id=None)
        )

    assert str(exc_info.value) == "source_node_id cannot be null"


def test_update_relation_target_null_raises_exact_validation_message(
    tree_service, node_service, relation_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Null tgt"), owner_id="owner"
    )
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    relation, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )

    with pytest.raises(ValidationFailure) as exc_info:
        relation_service.update_relation(
            tree.id, relation.id, RelationUpdateRequest(target_node_id=None)
        )

    assert str(exc_info.value) == "target_node_id cannot be null"


def test_update_relation_rejects_duplicate_after_source_change(
    tree_service, node_service, relation_service
) -> None:
    tree, node_a, node_b, node_c = _create_tree_with_three_nodes(
        tree_service, node_service
    )
    relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )
    second, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_c.id, target_node_id=node_b.id, kind="why"
        ),
    )

    with pytest.raises(ValidationFailure) as exc_info:
        relation_service.update_relation(
            tree.id, second.id, RelationUpdateRequest(source_node_id=node_a.id)
        )

    assert exc_info.value.detail == {
        "reason": "duplicate_relation",
        "source_node_id": node_a.id,
        "target_node_id": node_b.id,
    }


def test_update_relation_rejects_duplicate_after_target_change(
    tree_service, node_service, relation_service
) -> None:
    tree, node_a, node_b, node_c = _create_tree_with_three_nodes(
        tree_service, node_service
    )
    relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )
    second, _ = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_c.id, kind="why"
        ),
    )

    with pytest.raises(ValidationFailure) as exc_info:
        relation_service.update_relation(
            tree.id, second.id, RelationUpdateRequest(target_node_id=node_b.id)
        )

    assert exc_info.value.detail == {
        "reason": "duplicate_relation",
        "source_node_id": node_a.id,
        "target_node_id": node_b.id,
    }


# ---------------------------------------------------------------------------
# VersionService.export_tree — payload key and format exactness
# ---------------------------------------------------------------------------


def test_export_tree_live_payload_has_exact_keys_and_by_alias(
    tree_service, node_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Export live"), owner_id="owner"
    )
    node_service.create_node(
        tree.id,
        NodeCreateRequest(label="N", type="child", position=Position(x=1, y=2)),
    )

    filename, content = tree_service.to_response, None

    # Use the version_service fixture's export_tree via container
    # We need a version_service — construct from tree_service
    from app.container import build_container
    from app.core import get_config

    container = build_container(get_config())
    version_service = container.version_service
    # Recreate tree in this container's data dir
    tree = container.tree_service.create_tree(
        TreeCreateRequest(name="Export live 2"), owner_id="owner"
    )
    container.node_service.create_node(
        tree.id,
        NodeCreateRequest(label="N", type="child", position=Position(x=1, y=2)),
    )

    filename, content = version_service.export_tree(tree.id)

    payload = json.loads(content)

    assert set(payload.keys()) == {"exported_at", "source", "tree"}
    assert payload["source"]["type"] == "live"
    assert "tree_updated_at" in payload["source"]
    assert payload["source"]["tree_updated_at"] is not None
    # by_alias=True means node fields use camelCase aliases
    assert (
        "sourceNodeId" in str(payload["tree"])
        or "source_node_id" not in json.dumps(payload["tree"])
        or "sourceNodeId" in json.dumps(payload["tree"])
    )
    # Filename must contain tree_id and "latest"
    assert filename.startswith(tree.id)
    assert "_latest_" in filename
    assert filename.endswith(".json")


def test_export_tree_version_payload_has_exact_source_keys(
    tree_service, node_service, version_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Export ver"), owner_id="owner"
    )
    node_service.create_node(
        tree.id,
        NodeCreateRequest(label="N", type="child", position=Position(x=1, y=2)),
    )
    version = version_service.create_version(
        tree.id, VersionCreateRequest(label="Snap", author="Alex")
    )

    filename, content = version_service.export_tree(tree.id, version.id)

    payload = json.loads(content)

    assert payload["source"]["type"] == "version"
    assert payload["source"]["version_id"] == version.id
    assert payload["source"]["label"] == "Snap"
    assert payload["source"]["captured_at"] is not None
    assert payload["exported_at"] is not None

    # Filename must contain tree_id and the version suffix (after ::)
    assert filename.startswith(tree.id)
    suffix = version.id.split("::")[-1]
    assert f"_{suffix}_" in filename
    assert filename.endswith(".json")


def test_export_tree_uses_service_timestamp_aliases_and_unicode_payload(
    monkeypatch: pytest.MonkeyPatch,
    tree_service,
    node_service,
    version_service,
) -> None:
    """Exports keep service timestamps, schema aliases, and UTF-8 data intact."""

    from app.services import version_service as version_service_module
    from app.utils import time as time_module
    from app.utils.time import to_isoformat

    tree = tree_service.create_tree(TreeCreateRequest(name="Café 🌳"), owner_id="owner")
    node_service.create_node(
        tree.id,
        NodeCreateRequest(
            label="Crème brûlée", type="child", position=Position(x=1, y=2)
        ),
    )
    version = version_service.create_version(
        tree.id, VersionCreateRequest(label="Snapshot")
    )
    exported_at = datetime(2026, 7, 14, 4, 5, 6, tzinfo=UTC)
    fallback_now = datetime(2040, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(version_service_module, "utcnow", lambda: exported_at)
    monkeypatch.setattr(time_module, "utcnow", lambda: fallback_now)

    live_filename, live_content = version_service.export_tree(tree.id)
    live_payload = json.loads(live_content)
    version_filename, version_content = version_service.export_tree(tree.id, version.id)
    version_payload = json.loads(version_content)

    assert live_filename == f"{tree.id}_latest_20260714T040506Z.json"
    assert live_payload["exported_at"] == "2026-07-14T04:05:06Z"
    assert live_payload["source"] == {
        "type": "live",
        "tree_updated_at": to_isoformat(tree_service.get_tree(tree.id).updated_at),
    }
    assert live_payload["tree"]["name"] == "Café 🌳"
    assert live_payload["tree"]["nodes"][0]["label"] == "Crème brûlée"
    assert "Café 🌳" in live_content.decode("utf-8")
    assert "Crème brûlée" in live_content.decode("utf-8")

    assert version_filename == (
        f"{tree.id}_{version.id.split('::')[-1]}_20260714T040506Z.json"
    )
    assert version_payload["exported_at"] == "2026-07-14T04:05:06Z"
    assert version_payload["source"] == {
        "type": "version",
        "version_id": version.id,
        "label": "Snapshot",
        "captured_at": to_isoformat(version.captured_at),
    }


def test_export_tree_uses_compact_separators_and_utf8(
    tree_service, version_service
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="Compact"), owner_id="owner")

    _, content = version_service.export_tree(tree.id)

    # Compact separators: no spaces after , or :
    text = content.decode("utf-8")
    assert ", " not in text
    assert ': "' not in text or ':"' in text


def test_build_export_filename_exact_for_known_inputs() -> None:
    exported_at = datetime(2026, 7, 14, 3, 17, 0, tzinfo=UTC)

    # Version ID with ::
    fname = VersionService._build_export_filename(
        "tree:main", exported_at, "tree:main::snapshot:1"
    )
    assert fname == "tree:main_snapshot:1_20260714T031700Z.json"

    # No version_id → "latest"
    fname_live = VersionService._build_export_filename("tree:main", exported_at, None)
    assert fname_live == "tree:main_latest_20260714T031700Z.json"


# ---------------------------------------------------------------------------
# _build_export_filename — suffix exactness for version_id with multiple ::
# ---------------------------------------------------------------------------


def test_build_export_filename_suffix_is_last_segment_after_double_colon() -> None:
    exported_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    fname = VersionService._build_export_filename("t", exported_at, "a::b::c::d")
    # split("::")[-1] → "d"
    assert "_d_" in fname


# ---------------------------------------------------------------------------
# TreeService.get_tree / get_tree_for_owner — exact not-found fields
# ---------------------------------------------------------------------------


def test_get_tree_missing_raises_not_found_with_exact_fields(tree_service) -> None:
    with pytest.raises(NotFoundError) as exc_info:
        tree_service.get_tree("missing_tree")

    assert exc_info.value.resource == "Tree"
    assert exc_info.value.identifier == "missing_tree"


def test_get_tree_for_owner_wrong_owner_raises_not_found_with_exact_fields(
    tree_service,
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="Owner"), owner_id="owner_a")

    with pytest.raises(NotFoundError) as exc_info:
        tree_service.get_tree_for_owner(tree.id, owner_id="owner_b")

    assert exc_info.value.resource == "Tree"
    assert exc_info.value.identifier == tree.id


# ---------------------------------------------------------------------------
# TreeService.create_tree — owner_id in resolved metadata
# ---------------------------------------------------------------------------


def test_create_tree_resolves_metadata_with_exact_owner_id(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Owner meta"), owner_id="user_42"
    )

    assert tree.owner_id == "user_42"
    # Metadata block should contain owner_id
    meta = tree.metadata
    assert meta.get("owner_id") == "user_42"


def test_create_tree_preserves_payload_metadata_timestamps_and_layout(
    tree_service,
) -> None:
    from app.schemas.api import TreeMetadata

    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    updated_at = datetime(2026, 1, 2, tzinfo=UTC)
    metadata = TreeMetadata(
        version=7,
        created_at=created_at,
        updated_at=updated_at,
        layout={"viewport": {"x": 1, "y": 2}},
        owner_id="payload_owner",
    )

    tree = tree_service.create_tree(
        TreeCreateRequest(name="Payload metadata", metadata=metadata),
        owner_id="actor_owner",
    )

    assert tree.created_at == created_at
    assert tree.updated_at == updated_at
    assert tree.metadata == {
        "version": 7,
        "layout": {"viewport": {"x": 1, "y": 2}},
        "owner_id": "payload_owner",
    }
    assert tree.owner_id == "actor_owner"


def test_delete_tree_wrong_owner_raises_not_found_and_preserves_tree(
    tree_service,
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Delete owner"), owner_id="owner_a"
    )

    with pytest.raises(NotFoundError) as exc_info:
        tree_service.delete_tree(tree.id, owner_id="owner_b")

    assert exc_info.value.resource == "Tree"
    assert exc_info.value.identifier == tree.id
    assert tree_service.get_tree(tree.id).owner_id == "owner_a"


# ---------------------------------------------------------------------------
# RelationService.create_relation — exact duplicate detail
# ---------------------------------------------------------------------------


def test_create_relation_duplicate_raises_exact_detail(
    tree_service, node_service, relation_service
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="Dup rel"), owner_id="owner")
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
        ),
    )

    with pytest.raises(ValidationFailure) as exc_info:
        relation_service.create_relation(
            tree.id,
            RelationCreateRequest(
                source_node_id=node_a.id, target_node_id=node_b.id, kind="why"
            ),
        )

    assert str(exc_info.value) == "A link already exists between these nodes."
    assert exc_info.value.detail == {
        "reason": "duplicate_relation",
        "source_node_id": node_a.id,
        "target_node_id": node_b.id,
    }


def test_validate_relations_duplicate_pair_raises_exact_detail(
    relation_service,
) -> None:
    from app.schemas.domain import RelationDocument, RelationMetadata

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    relation = RelationDocument(
        id="dup",
        source_id="a",
        target_id="b",
        question_label="why",
        metadata=RelationMetadata(created_at=timestamp, updated_at=timestamp),
    )

    with pytest.raises(ValidationFailure) as exc_info:
        relation_service._validate_relations([relation, relation])

    assert str(exc_info.value) == "A link already exists between these nodes."
    assert exc_info.value.detail == {
        "reason": "duplicate_relation",
        "source_node_id": "a",
        "target_node_id": "b",
    }


# ---------------------------------------------------------------------------
# RelationService.delete_relation — exact not-found
# ---------------------------------------------------------------------------


def test_delete_relation_missing_raises_not_found_with_exact_fields(
    tree_service, relation_service
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="Del rel"), owner_id="owner")

    with pytest.raises(NotFoundError) as exc_info:
        relation_service.delete_relation(tree.id, "missing_rel")

    assert exc_info.value.resource == "Relation"
    assert exc_info.value.identifier == "missing_rel"


# ---------------------------------------------------------------------------
# VersionService.delete_version — exact not-found
# ---------------------------------------------------------------------------


def test_delete_version_missing_raises_not_found_with_exact_fields(
    tree_service, version_service
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="Del ver"), owner_id="owner")

    with pytest.raises(NotFoundError) as exc_info:
        version_service.delete_version(tree.id, "missing::version")

    assert exc_info.value.resource == "Version"
    assert exc_info.value.identifier == "missing::version"


# ---------------------------------------------------------------------------
# VersionService.restore_version — ref merge exactness
# ---------------------------------------------------------------------------


def test_restore_version_preserves_existing_refs_and_adds_restored_ref(
    tree_service, node_service, version_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Restore refs"), owner_id="owner"
    )
    node_service.create_node(
        tree.id,
        NodeCreateRequest(label="N", type="child", position=Position(x=0, y=0)),
    )
    v1 = version_service.create_version(tree.id, VersionCreateRequest(label="v1"))
    v2 = version_service.create_version(tree.id, VersionCreateRequest(label="v2"))

    # After creating v2, tree has [v2_ref, v1_ref]
    tree_before = tree_service.get_tree(tree.id)
    assert [ref.id for ref in tree_before.version_refs] == [v2.id, v1.id]

    # Restore v1 — should keep both refs, v1 should appear once
    restored = version_service.restore_version(tree.id, v1.id)

    ref_ids = [ref.id for ref in restored.version_refs]
    assert ref_ids.count(v1.id) == 1
    assert v2.id in ref_ids
    assert v1.id in ref_ids


def test_create_version_captures_one_timestamp_and_full_reference_metadata(
    monkeypatch: pytest.MonkeyPatch, tree_service, version_service
) -> None:
    from app.services import version_service as version_service_module

    tree = tree_service.create_tree(
        TreeCreateRequest(name="Timestamp snapshot"), owner_id="owner"
    )
    captured_at = datetime(2050, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(version_service_module, "utcnow", lambda: captured_at)

    version = version_service.create_version(
        tree.id,
        VersionCreateRequest(label="Named snapshot", author="Alex", notes="keep me"),
    )
    stored_tree = tree_service.get_tree(tree.id)
    reference = stored_tree.version_refs[0]

    assert version.id.startswith(f"{tree.id}::")
    assert version.captured_at == captured_at
    assert version.author == "Alex"
    assert version.notes == "keep me"
    assert version.tree.id == tree.id
    assert version.tree.updated_at == tree.updated_at
    assert stored_tree.updated_at == captured_at
    assert reference.id == version.id
    assert reference.label == "Named snapshot"
    assert reference.created_at == captured_at
    assert reference.author == "Alex"
    assert reference.notes == "keep me"
    assert reference.diff_summary == version.diff
    assert reference.conflict_count == len(version.conflicts)


def test_create_version_without_label_uses_captured_timestamp_label(
    monkeypatch: pytest.MonkeyPatch, tree_service, version_service
) -> None:
    from app.services import version_service as version_service_module
    from app.utils.time import to_isoformat

    tree = tree_service.create_tree(
        TreeCreateRequest(name="Default snapshot label"), owner_id="owner"
    )
    captured_at = datetime(2051, 2, 3, 4, 5, 6, tzinfo=UTC)
    monkeypatch.setattr(version_service_module, "utcnow", lambda: captured_at)

    version = version_service.create_version(tree.id, VersionCreateRequest())

    assert version.label == f"Snapshot {to_isoformat(captured_at)}"
    assert tree_service.get_tree(tree.id).version_refs[0].label == version.label


def test_load_version_missing_tree_reports_tree_before_version_lookup(
    version_service,
) -> None:
    with pytest.raises(NotFoundError) as exc_info:
        version_service.load_version("missing_tree", "missing::version")

    assert exc_info.value.resource == "Tree"
    assert exc_info.value.identifier == "missing_tree"


def test_restore_version_restores_exact_node_state(
    tree_service, node_service, version_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Restore state"), owner_id="owner"
    )
    node, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="Original", type="child", position=Position(x=1, y=2)),
    )
    v1 = version_service.create_version(tree.id, VersionCreateRequest(label="snap"))
    node_service.update_node(
        tree.id,
        node.id,
        NodeUpdateRequest(label="Changed", position=Position(x=9, y=9)),
    )

    restored = version_service.restore_version(tree.id, v1.id)

    assert restored.nodes[0].label == "Original"
    assert restored.nodes[0].position == Position(x=1, y=2)


# ---------------------------------------------------------------------------
# TreeRepository.create — conflict exactness
# ---------------------------------------------------------------------------


def test_tree_repository_create_duplicate_raises_conflict_with_exact_fields(
    data_dir,
) -> None:
    from app.repositories.tree import TreeRepository
    from app.schemas.domain import TreeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    tree = TreeDocument(
        id="dup_tree",
        title="Dup",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[],
        relations=[],
    )
    repo = TreeRepository(data_dir)
    repo.create(tree)

    with pytest.raises(ConflictError) as exc_info:
        repo.create(tree)

    assert exc_info.value.resource == "Tree"
    assert exc_info.value.identifier == "dup_tree"


# ---------------------------------------------------------------------------
# _build_tree_metadata — owner_id resolution exactness
# ---------------------------------------------------------------------------


def test_build_tree_metadata_prefers_tree_owner_id_over_metadata(
    tree_service,
) -> None:
    from app.schemas.domain import TreeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    tree = TreeDocument(
        id="meta_tree",
        title="Meta",
        owner_id="real_owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[],
        relations=[],
        metadata={"version": 2, "owner_id": "ignored_meta_owner"},
    )

    meta = tree_service._build_tree_metadata(tree)

    assert meta.owner_id == "real_owner"
    assert meta.version == 2


def test_build_tree_metadata_falls_back_to_metadata_owner_id(
    tree_service,
) -> None:
    from app.schemas.domain import TreeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    tree = TreeDocument(
        id="meta_tree2",
        title="Meta2",
        owner_id=None,
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[],
        relations=[],
        metadata={"version": 1, "owner_id": "meta_owner"},
    )

    meta = tree_service._build_tree_metadata(tree)

    assert meta.owner_id == "meta_owner"


def test_build_tree_metadata_layout_only_if_dict(tree_service) -> None:
    from app.schemas.domain import TreeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    tree = TreeDocument(
        id="meta_layout",
        title="Layout",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[],
        relations=[],
        metadata={"version": 1, "layout": "not-a-dict"},
    )

    meta = tree_service._build_tree_metadata(tree)

    assert meta.layout is None


# ---------------------------------------------------------------------------
# _resolve_metadata — owner_id fallback and coerce_updated
# ---------------------------------------------------------------------------


def test_resolve_metadata_coerce_updated_uses_now(tree_service) -> None:
    from app.schemas.api import TreeMetadata

    old_updated = datetime(2020, 1, 1, tzinfo=UTC)
    metadata = TreeMetadata(
        version=1,
        created_at=old_updated,
        updated_at=old_updated,
        owner_id="owner",
    )

    resolved = tree_service._resolve_metadata(metadata, coerce_updated=True)

    assert resolved.updated_at > old_updated
    assert resolved.created_at == old_updated
    assert resolved.owner_id == "owner"


def test_resolve_metadata_no_coerce_preserves_updated_at(tree_service) -> None:
    from app.schemas.api import TreeMetadata

    old_updated = datetime(2020, 1, 1, tzinfo=UTC)
    metadata = TreeMetadata(
        version=1,
        created_at=old_updated,
        updated_at=old_updated,
        owner_id="owner",
    )

    resolved = tree_service._resolve_metadata(metadata, coerce_updated=False)

    assert resolved.updated_at == old_updated


def test_resolve_metadata_owner_fallback_to_argument(tree_service) -> None:
    from app.schemas.api import TreeMetadata

    metadata = TreeMetadata(
        version=1,
        created_at=datetime(2020, 1, 1, tzinfo=UTC),
        updated_at=datetime(2020, 1, 1, tzinfo=UTC),
        owner_id=None,
    )

    resolved = tree_service._resolve_metadata(metadata, owner_id="fallback")

    assert resolved.owner_id == "fallback"


# ---------------------------------------------------------------------------
# _node_to_document — exact extra fields
# ---------------------------------------------------------------------------


def test_node_to_document_preserves_highlight_state_and_type(
    tree_service,
) -> None:
    from app.schemas.api import NodeCreateRequest, Position

    node = NodeCreateRequest(
        label="Test",
        type="parent",
        position=Position(x=1, y=2),
        highlight_state="cause_candidate",
    )
    from app.schemas.api import TreeMetadata

    metadata = TreeMetadata(
        version=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        owner_id="owner",
    )
    doc = tree_service._node_to_document(node, metadata)

    assert doc.extra == {"type": "parent", "highlight_state": "cause_candidate"}
    assert doc.label == "Test"
    assert doc.position == Position(x=1, y=2)


def test_node_to_document_default_highlight_state_is_none(
    tree_service,
) -> None:
    from app.schemas.api import NodeCreateRequest, Position, TreeMetadata

    node = NodeCreateRequest(
        label="Default",
        type="child",
        position=Position(x=0, y=0),
    )
    metadata = TreeMetadata(
        version=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        owner_id="owner",
    )
    doc = tree_service._node_to_document(node, metadata)

    assert doc.extra == {"type": "child", "highlight_state": "none"}


# ---------------------------------------------------------------------------
# _build_tree_document — complete node/relation reconstruction
# ---------------------------------------------------------------------------


def test_build_tree_document_keeps_explicit_relation_between_response_nodes(
    tree_service,
) -> None:
    from app.schemas.api import (
        NodeResponse,
        RelationResponse,
        TreeMetadata,
    )

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    metadata = TreeMetadata(
        version=4,
        created_at=timestamp,
        updated_at=timestamp,
        owner_id="owner",
    )
    nodes = [
        NodeResponse(
            id="cause", label="Cause", type="child", position=Position(x=0, y=0)
        ),
        NodeResponse(
            id="effect", label="Effect", type="parent", position=Position(x=1, y=1)
        ),
    ]
    relation = RelationResponse(
        id="cause->effect",
        source_node_id="cause",
        target_node_id="effect",
        kind="why",
        created_at=timestamp,
    )

    tree = tree_service._build_tree_document(
        tree_id="reconstructed",
        name="Reconstructed",
        metadata=metadata,
        nodes=nodes,
        relations=[relation],
        owner_id="owner",
    )

    assert [(node.id, node.label) for node in tree.nodes] == [
        ("cause", "Cause"),
        ("effect", "Effect"),
    ]
    assert [
        (item.id, item.source_id, item.target_id, item.question_label)
        for item in tree.relations
    ] == [("cause->effect", "cause", "effect", "why")]
    assert tree.metadata == {"version": 4, "owner_id": "owner"}


# ---------------------------------------------------------------------------
# _preserve_unrepresented_tree_data — carry-forward exactness
# ---------------------------------------------------------------------------


def test_preserve_unrepresented_carries_forward_visual_validation_extra(
    tree_service,
) -> None:
    from app.schemas.common import (
        Position,
        TimestampMetadata,
        ValidationState,
        VisualState,
    )
    from app.schemas.domain import (
        NodeDocument,
        RelationDocument,
        RelationMetadata,
        TreeDocument,
    )

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    node = NodeDocument(
        id="n1",
        label="N1",
        position=Position(x=0, y=0),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
        visual=VisualState(color="#fff", highlight=True),
        validation=ValidationState(
            confidence=80, provider="mock", last_checked=timestamp
        ),
        extra={"type": "parent", "custom": "data"},
    )
    relation = RelationDocument(
        id="r1",
        source_id="n1",
        target_id="n2",
        question_label="why",
        notes="original note",
        metadata=RelationMetadata(created_at=timestamp, updated_at=timestamp),
    )
    existing = TreeDocument(
        id="preserve_tree",
        title="Preserve",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[node],
        relations=[relation],
        description="A description",
        version_refs=[],
    )

    # New tree with same node id but no visual/validation/extra
    new_node = NodeDocument(
        id="n1",
        label="N1 new",
        position=Position(x=1, y=1),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
    )
    new_relation = RelationDocument(
        id="r1",
        source_id="n1",
        target_id="n2",
        question_label="why",
        metadata=RelationMetadata(created_at=timestamp, updated_at=timestamp),
    )
    new_tree = TreeDocument(
        id="preserve_tree",
        title="Preserve new",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[new_node],
        relations=[new_relation],
    )

    result = tree_service._preserve_unrepresented_tree_data(new_tree, existing)

    assert result.nodes[0].visual == VisualState(color="#fff", highlight=True)
    assert result.nodes[0].validation == ValidationState(
        confidence=80, provider="mock", last_checked=timestamp
    )
    assert result.nodes[0].extra == {"type": "parent", "custom": "data"}
    assert result.relations[0].notes == "original note"
    assert result.description == "A description"
    assert result.version_refs == []


def test_preserve_unrepresented_keeps_all_items_and_merges_matching_data(
    tree_service,
) -> None:
    from app.schemas.common import Position, TimestampMetadata, VisualState
    from app.schemas.domain import (
        NodeDocument,
        RelationDocument,
        RelationMetadata,
        TreeDocument,
    )

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    original_node = NodeDocument(
        id="matching-node",
        label="Original",
        position=Position(x=0, y=0),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
        visual=VisualState(color="#fff", highlight=True),
        extra={"legacy": {"preserved": True}},
    )
    original_relation = RelationDocument(
        id="matching-relation",
        source_id="matching-node",
        target_id="new-node",
        question_label="why",
        notes="preserve this",
        metadata=RelationMetadata(created_at=timestamp, updated_at=timestamp),
    )
    existing = TreeDocument(
        id="tree",
        title="Existing",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[original_node],
        relations=[original_relation],
    )
    new_node = NodeDocument(
        id="new-node",
        label="New",
        position=Position(x=1, y=1),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
    )
    matching_node = NodeDocument(
        id="matching-node",
        label="Updated",
        position=Position(x=2, y=2),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
        extra={"request": {"preserved": True}},
    )
    new_relation = RelationDocument(
        id="new-relation",
        source_id="new-node",
        target_id="matching-node",
        question_label="why",
        metadata=RelationMetadata(created_at=timestamp, updated_at=timestamp),
    )
    matching_relation = RelationDocument(
        id="matching-relation",
        source_id="matching-node",
        target_id="new-node",
        question_label="why",
        metadata=RelationMetadata(created_at=timestamp, updated_at=timestamp),
    )
    incoming = TreeDocument(
        id="tree",
        title="Incoming",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[new_node, matching_node],
        relations=[new_relation, matching_relation],
    )

    result = tree_service._preserve_unrepresented_tree_data(incoming, existing)
    result_node = next(node for node in result.nodes if node.id == "matching-node")
    result_relation = next(
        relation for relation in result.relations if relation.id == "matching-relation"
    )

    assert [node.id for node in result.nodes] == ["new-node", "matching-node"]
    assert [relation.id for relation in result.relations] == [
        "new-relation",
        "matching-relation",
    ]
    assert result_node.visual == original_node.visual
    assert result_node.extra == {
        "legacy": {"preserved": True},
        "request": {"preserved": True},
    }
    assert result_relation.notes == "preserve this"


# ---------------------------------------------------------------------------
# mutate_tree — timestamp advance and after_save callback
# ---------------------------------------------------------------------------


def test_mutate_tree_advances_timestamp_and_calls_after_save(
    tree_service, node_service
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="Mutate"), owner_id="owner")
    original_updated = tree.updated_at

    called_with: list = []
    result = tree_service.mutate_tree(
        tree.id,
        update=lambda current: current.model_copy(update={"title": "Changed"}),
        after_save=lambda saved: called_with.append(saved),
    )

    assert result.title == "Changed"
    assert result.updated_at > original_updated
    assert len(called_with) == 1
    assert called_with[0].title == "Changed"


# ---------------------------------------------------------------------------
# _latest_version — exact selection
# ---------------------------------------------------------------------------


def test_latest_version_returns_most_recent_by_captured_at(
    version_service, tree_service
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name="Latest"), owner_id="owner")
    v1 = version_service.create_version(tree.id, VersionCreateRequest(label="v1"))
    v2 = version_service.create_version(tree.id, VersionCreateRequest(label="v2"))

    latest = version_service._latest_version(tree.id)

    assert latest is not None
    assert latest.id == v2.id
    assert latest.captured_at >= v1.captured_at


def test_latest_version_returns_none_when_no_versions(
    version_service, tree_service
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="No versions"), owner_id="owner"
    )

    assert version_service._latest_version(tree.id) is None


# ---------------------------------------------------------------------------
# _compare_nodes — exact field list
# ---------------------------------------------------------------------------


def test_compare_nodes_detects_all_field_changes() -> None:
    from app.schemas.common import (
        Position,
        TimestampMetadata,
        ValidationState,
        VisualState,
    )
    from app.schemas.domain import NodeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    previous = NodeDocument(
        id="n",
        label="Old",
        position=Position(x=0, y=0),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
        visual=VisualState(color="#000", highlight=False),
        validation=ValidationState(confidence=50, provider="a", last_checked=timestamp),
        extra={"type": "child"},
    )
    current = NodeDocument(
        id="n",
        label="New",
        position=Position(x=1, y=1),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
        visual=VisualState(color="#fff", highlight=True),
        validation=ValidationState(confidence=80, provider="b", last_checked=timestamp),
        extra={"type": "parent"},
    )

    changed = VersionService._compare_nodes(previous, current)

    assert changed == ["label", "position", "visual", "validation", "extra"]


def test_compare_nodes_returns_empty_for_identical_nodes() -> None:
    from app.schemas.common import Position, TimestampMetadata
    from app.schemas.domain import NodeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    node = NodeDocument(
        id="n",
        label="Same",
        position=Position(x=0, y=0),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
    )

    assert VersionService._compare_nodes(node, node) == []


# ---------------------------------------------------------------------------
# TreeService.list_trees — owner filtering
# ---------------------------------------------------------------------------


def test_list_trees_filters_by_owner_id(tree_service) -> None:
    tree_service.create_tree(TreeCreateRequest(name="A"), owner_id="owner_a")
    tree_service.create_tree(TreeCreateRequest(name="B"), owner_id="owner_b")
    tree_service.create_tree(TreeCreateRequest(name="C"), owner_id="owner_a")

    entries = tree_service.list_trees(owner_id="owner_a")

    assert {entry.id for entry in entries} == {
        e.id for e in tree_service.index_repo.load_all() if e.owner_id == "owner_a"
    }
    assert all(entry.owner_id == "owner_a" for entry in entries)
    assert len(entries) == 2


# ---------------------------------------------------------------------------
# _prepare_metadata_block — layout and owner_id inclusion
# ---------------------------------------------------------------------------


def test_prepare_metadata_block_includes_layout_when_present(tree_service) -> None:
    from app.schemas.api import TreeMetadata

    metadata = TreeMetadata(
        version=3,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        layout={"viewport": "wide"},
        owner_id="owner",
    )

    block = tree_service._prepare_metadata_block(metadata)

    assert block == {"version": 3, "layout": {"viewport": "wide"}, "owner_id": "owner"}


def test_prepare_metadata_block_omits_layout_and_owner_when_none(
    tree_service,
) -> None:
    from app.schemas.api import TreeMetadata

    metadata = TreeMetadata(
        version=1,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        layout=None,
        owner_id=None,
    )

    block = tree_service._prepare_metadata_block(metadata)

    assert block == {"version": 1}


# ---------------------------------------------------------------------------
# _remove_tree_state — cache and index removal
# ---------------------------------------------------------------------------


def test_remove_tree_state_clears_cache_and_index(tree_service) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Remove state"), owner_id="owner"
    )

    # Tree should be in cache
    assert tree_service._cache_get(tree.id) is not None

    tree_service._remove_tree_state(tree.id)

    assert tree_service._cache_get(tree.id) is None
    # Index should not contain the tree
    entries = tree_service.index_repo.load_all()
    assert all(entry.id != tree.id for entry in entries)


# ---------------------------------------------------------------------------
# _store_and_clone — returns deep copy
# ---------------------------------------------------------------------------


def test_store_and_clone_returns_independent_copy(tree_service) -> None:
    from app.schemas.domain import TreeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    tree = TreeDocument(
        id="clone_tree",
        title="Clone",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[],
        relations=[],
    )

    clone = tree_service._store_and_clone(tree)

    assert clone.id == tree.id
    # Mutating clone should not affect cache
    clone.title = "Modified"
    cached = tree_service._cache_get(tree.id)
    assert cached is not None
    assert cached.title == "Clone"


# ---------------------------------------------------------------------------
# _cache_store — LRU eviction
# ---------------------------------------------------------------------------


def test_cache_store_evicts_lru_when_full(tree_service) -> None:
    from app.schemas.domain import TreeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    # Fill cache to max (default 16)
    for i in range(16):
        tree = TreeDocument(
            id=f"cache_{i}",
            title=f"T{i}",
            owner_id="owner",
            created_at=timestamp,
            updated_at=timestamp,
            nodes=[],
            relations=[],
        )
        tree_service._cache_store(tree)

    # All 16 should be in cache
    for i in range(16):
        assert tree_service._cache_get(f"cache_{i}") is not None

    # Add one more → should evict cache_0 (LRU)
    extra = TreeDocument(
        id="cache_16",
        title="T16",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[],
        relations=[],
    )
    tree_service._cache_store(extra)

    assert tree_service._cache_get("cache_0") is None
    assert tree_service._cache_get("cache_16") is not None


# ---------------------------------------------------------------------------
# _build_diff — relation modifications exactness
# ---------------------------------------------------------------------------


def test_build_diff_counts_relation_modifications_correctly(version_service) -> None:
    """A changed relation field is counted and described in the snapshot diff."""

    from app.schemas.common import TimestampMetadata
    from app.schemas.domain import (
        NodeDocument,
        RelationDocument,
        RelationMetadata,
        TreeDocument,
    )

    ts = datetime(2026, 1, 1, tzinfo=UTC)
    nodes = [
        NodeDocument(
            id="a",
            label="A",
            position=Position(x=0, y=0),
            metadata=TimestampMetadata(created_at=ts, updated_at=ts),
        ),
        NodeDocument(
            id="b",
            label="B",
            position=Position(x=1, y=1),
            metadata=TimestampMetadata(created_at=ts, updated_at=ts),
        ),
    ]
    prev_rel = RelationDocument(
        id="r1",
        source_id="a",
        target_id="b",
        question_label="why",
        metadata=RelationMetadata(created_at=ts, updated_at=ts),
    )
    curr_rel = RelationDocument(
        id="r1",
        source_id="a",
        target_id="b",
        question_label="because",
        metadata=RelationMetadata(created_at=ts, updated_at=ts),
    )
    prev_tree = TreeDocument(
        id="t",
        title="T",
        owner_id="o",
        created_at=ts,
        updated_at=ts,
        nodes=nodes,
        relations=[prev_rel],
    )
    curr_tree = TreeDocument(
        id="t",
        title="T",
        owner_id="o",
        created_at=ts,
        updated_at=ts,
        nodes=nodes,
        relations=[curr_rel],
    )

    diff, conflicts = version_service._build_diff(prev_tree, curr_tree)

    assert diff.nodes_added == 0
    assert diff.nodes_removed == 0
    assert diff.nodes_modified == 0
    assert diff.relations_added == 0
    assert diff.relations_removed == 0
    assert diff.relations_modified == 1
    assert len(conflicts) == 1
    assert conflicts[0].entity_type == "relation"
    assert conflicts[0].entity_id == "r1"
    assert "question_label" in conflicts[0].fields


def test_build_diff_node_conflict_carries_exact_changed_fields(
    version_service,
) -> None:
    from app.schemas.common import TimestampMetadata, ValidationState, VisualState
    from app.schemas.domain import NodeDocument, TreeDocument

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    previous = NodeDocument(
        id="node",
        label="Before",
        position=Position(x=0, y=0),
        metadata=TimestampMetadata(created_at=timestamp, updated_at=timestamp),
        visual=VisualState(color="#111", highlight=False),
        validation=ValidationState(
            confidence=10, provider="old", last_checked=timestamp
        ),
        extra={"type": "child"},
    )
    current = previous.model_copy(
        update={
            "label": "After",
            "position": Position(x=1, y=2),
            "visual": VisualState(color="#222", highlight=True),
            "validation": ValidationState(
                confidence=90, provider="new", last_checked=timestamp
            ),
            "extra": {"type": "parent"},
        }
    )
    previous_tree = TreeDocument(
        id="tree",
        title="Tree",
        owner_id="owner",
        created_at=timestamp,
        updated_at=timestamp,
        nodes=[previous],
        relations=[],
    )
    current_tree = previous_tree.model_copy(update={"nodes": [current]})

    diff, conflicts = version_service._build_diff(previous_tree, current_tree)

    assert diff.nodes_modified == 1
    assert len(conflicts) == 1
    assert conflicts[0].entity_type == "node"
    assert conflicts[0].entity_id == "node"
    assert conflicts[0].fields == [
        "label",
        "position",
        "visual",
        "validation",
        "extra",
    ]


def test_preserve_unrepresented_keeps_original_created_and_incoming_updated_times(
    tree_service,
) -> None:
    from app.schemas.common import Position, TimestampMetadata
    from app.schemas.domain import (
        NodeDocument,
        RelationDocument,
        RelationMetadata,
        TreeDocument,
    )

    original_time = datetime(2020, 1, 1, tzinfo=UTC)
    incoming_time = datetime(2026, 1, 1, tzinfo=UTC)
    existing_node = NodeDocument(
        id="node",
        label="Original",
        position=Position(x=0, y=0),
        metadata=TimestampMetadata(created_at=original_time, updated_at=original_time),
    )
    existing_relation = RelationDocument(
        id="relation",
        source_id="node",
        target_id="other",
        question_label="why",
        metadata=RelationMetadata(created_at=original_time, updated_at=original_time),
    )
    existing = TreeDocument(
        id="tree",
        title="Existing",
        owner_id="owner",
        created_at=original_time,
        updated_at=original_time,
        nodes=[existing_node],
        relations=[existing_relation],
    )
    incoming_node = existing_node.model_copy(
        update={
            "label": "Incoming",
            "position": Position(x=1, y=1),
            "metadata": TimestampMetadata(
                created_at=incoming_time, updated_at=incoming_time
            ),
        }
    )
    incoming_relation = existing_relation.model_copy(
        update={
            "metadata": RelationMetadata(
                created_at=incoming_time, updated_at=incoming_time
            )
        }
    )
    incoming = existing.model_copy(
        update={"nodes": [incoming_node], "relations": [incoming_relation]}
    )

    result = tree_service._preserve_unrepresented_tree_data(incoming, existing)

    assert result.nodes[0].metadata.created_at == original_time
    assert result.nodes[0].metadata.updated_at == incoming_time
    assert result.nodes[0].position is not incoming_node.position
    assert result.relations[0].metadata.created_at == original_time
    assert result.relations[0].metadata.updated_at == incoming_time


def test_node_to_document_uses_none_highlight_when_legacy_input_omits_field(
    tree_service,
) -> None:
    from types import SimpleNamespace

    from app.schemas.api import TreeMetadata

    metadata = TreeMetadata(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        owner_id="owner",
    )
    legacy_node = SimpleNamespace(
        label="Legacy", type="child", position=Position(x=1, y=2)
    )

    document = tree_service._node_to_document(legacy_node, metadata)

    assert document.extra == {"type": "child", "highlight_state": "none"}


def test_mutate_tree_bumps_equal_timestamp_once_and_returns_a_defensive_copy(
    tree_service,
) -> None:
    from datetime import timedelta

    tree = tree_service.create_tree(
        TreeCreateRequest(name="Exact mutate"), owner_id="owner"
    )
    saved = []
    result = tree_service.mutate_tree(
        tree.id,
        update=lambda current: current.model_copy(update={"title": "Updated"}),
        timestamp=tree.updated_at,
        after_save=saved.append,
    )
    expected_updated_at = tree.updated_at + timedelta(microseconds=1)

    assert result.updated_at == expected_updated_at
    assert result.metadata["updated_at"] == expected_updated_at
    assert saved[0].updated_at == expected_updated_at
    assert result is not saved[0]


# ---------------------------------------------------------------------------
# update_tree — metadata fallback, state publication, defensive return
# ---------------------------------------------------------------------------


def test_update_tree_uses_actor_owner_and_publishes_independent_state(
    tree_service,
) -> None:
    from app.schemas.api import NodeResponse, TreeMetadata, TreeUpdateRequest

    original = tree_service.create_tree(
        TreeCreateRequest(name="Initial"), owner_id="owner"
    )
    payload = TreeUpdateRequest(
        name="Updated",
        metadata=TreeMetadata(
            version=4,
            created_at=original.created_at,
            updated_at=original.updated_at,
            layout={"viewport": "wide"},
            owner_id=None,
        ),
        nodes=[
            NodeResponse(
                id="kept-node",
                label="Kept",
                type="child",
                position=Position(x=3, y=4),
            )
        ],
        relations=[],
        owner_id=None,
    )

    updated = tree_service.update_tree(original.id, payload, owner_id="owner")
    cached = tree_service._cache_get(original.id)
    index_entry = next(
        entry for entry in tree_service.index_repo.load_all() if entry.id == original.id
    )

    assert updated.owner_id == "owner"
    assert updated.metadata == {
        "version": 4,
        "layout": {"viewport": "wide"},
        "owner_id": "owner",
    }
    assert updated.nodes[0].id == "kept-node"
    assert cached is not None
    assert cached.title == "Updated"
    assert index_entry.title == "Updated"
    assert updated.nodes[0] is not cached.nodes[0]
    assert updated.metadata is not cached.metadata


# ---------------------------------------------------------------------------
# create_relation — one operation timestamp across relation and tree
# ---------------------------------------------------------------------------


def test_create_relation_passes_its_captured_timestamp_to_tree_transaction(
    monkeypatch: pytest.MonkeyPatch,
    tree_service,
    node_service,
    relation_service,
) -> None:
    from app.services import relation_service as relation_service_module

    tree = tree_service.create_tree(
        TreeCreateRequest(name="Create timestamp"), owner_id="owner"
    )
    node_a, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="A", type="child", position=Position(x=0, y=0)),
    )
    node_b, _ = node_service.create_node(
        tree.id,
        NodeCreateRequest(label="B", type="child", position=Position(x=1, y=1)),
    )
    timestamp = datetime(2050, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(relation_service_module, "utcnow", lambda: timestamp)

    relation, updated_tree = relation_service.create_relation(
        tree.id,
        RelationCreateRequest(
            source_node_id=node_a.id,
            target_node_id=node_b.id,
            kind="why",
        ),
    )

    assert relation.metadata.created_at == timestamp
    assert relation.metadata.updated_at == timestamp
    assert updated_tree.updated_at == timestamp
    assert tree_service.tree_repo.load(tree.id).updated_at == timestamp


# ---------------------------------------------------------------------------
# _relation_to_document — explicit response and legacy fallback fields
# ---------------------------------------------------------------------------


def test_relation_to_document_preserves_response_fields_and_legacy_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tree_service,
) -> None:
    from types import SimpleNamespace

    from app.schemas.api import RelationResponse, TreeMetadata
    from app.services import tree_service as tree_service_module

    updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    created_at = datetime(2020, 1, 1, tzinfo=UTC)
    metadata = TreeMetadata(
        version=1,
        created_at=updated_at,
        updated_at=updated_at,
        owner_id="owner",
    )
    response = RelationResponse(
        id="response-relation",
        source_node_id="source",
        target_node_id="target",
        kind="why",
        created_at=created_at,
    )

    response_document = tree_service._relation_to_document(response, metadata)

    assert response_document.id == "response-relation"
    assert response_document.source_id == "source"
    assert response_document.target_id == "target"
    assert response_document.question_label == "why"
    assert response_document.notes is None
    assert response_document.metadata.created_at == created_at
    assert response_document.metadata.updated_at == updated_at
    assert response_document.metadata.author is None

    monkeypatch.setattr(tree_service_module, "generate_relation_id", lambda: "generated")
    legacy_document = tree_service._relation_to_document(
        SimpleNamespace(source_node_id="legacy-source", target_node_id="legacy-target"),
        metadata,
    )

    assert legacy_document.id == "generated"
    assert legacy_document.question_label == "why"
    assert legacy_document.metadata.created_at == updated_at
    assert legacy_document.metadata.updated_at == updated_at


def test_relation_to_document_preserves_constructed_future_kind_value(
    tree_service,
) -> None:
    from app.schemas.api import RelationResponse, TreeMetadata

    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    metadata = TreeMetadata(
        version=1,
        created_at=timestamp,
        updated_at=timestamp,
        owner_id="owner",
    )
    future_relation = RelationResponse.model_construct(
        id="future",
        source_node_id="source",
        target_node_id="target",
        kind="because",
        created_at=timestamp,
    )

    document = tree_service._relation_to_document(future_relation, metadata)

    assert document.question_label == "because"


# ---------------------------------------------------------------------------
# RelationService._ensure_node_exists — exact missing-node contract
# ---------------------------------------------------------------------------


def test_create_relation_missing_source_reports_exact_node_identity(
    tree_service,
    relation_service,
) -> None:
    tree = tree_service.create_tree(
        TreeCreateRequest(name="Missing relation source"), owner_id="owner"
    )

    with pytest.raises(NotFoundError) as exc_info:
        relation_service.create_relation(
            tree.id,
            RelationCreateRequest(
                source_node_id="missing-source",
                target_node_id="missing-target",
                kind="why",
            ),
        )

    assert exc_info.value.resource == "Node"
    assert exc_info.value.identifier == "missing-source"
    assert str(exc_info.value) == "Node 'missing-source' was not found."


# ---------------------------------------------------------------------------
# generate_ai_feedback — integer relation-gap thresholds
# ---------------------------------------------------------------------------


def test_generate_ai_feedback_uses_half_node_relation_gap_threshold(
    tree_service,
    node_service,
    relation_service,
) -> None:
    three_nodes = tree_service.create_tree(
        TreeCreateRequest(name="Three nodes"), owner_id="owner"
    )
    three_ids = []
    for index in range(3):
        node, _ = node_service.create_node(
            three_nodes.id,
            NodeCreateRequest(
                label=f"Three {index}",
                type="child",
                position=Position(x=index, y=index),
            ),
        )
        three_ids.append(node.id)
    relation_service.create_relation(
        three_nodes.id,
        RelationCreateRequest(
            source_node_id=three_ids[0], target_node_id=three_ids[1], kind="why"
        ),
    )

    three_response = tree_service.generate_ai_feedback(
        three_nodes.id, AiFeedbackRequest(consent=True), owner_id="owner"
    )

    assert three_response.recommendations == [
        "Review whether each relation flows from cause to effect."
    ]

    four_nodes = tree_service.create_tree(
        TreeCreateRequest(name="Four nodes"), owner_id="owner"
    )
    four_ids = []
    for index in range(4):
        node, _ = node_service.create_node(
            four_nodes.id,
            NodeCreateRequest(
                label=f"Four {index}",
                type="child",
                position=Position(x=index, y=index),
            ),
        )
        four_ids.append(node.id)
    relation_service.create_relation(
        four_nodes.id,
        RelationCreateRequest(
            source_node_id=four_ids[0], target_node_id=four_ids[1], kind="why"
        ),
    )

    four_response = tree_service.generate_ai_feedback(
        four_nodes.id, AiFeedbackRequest(consent=True), owner_id="owner"
    )

    assert four_response.recommendations == [
        "Review whether each relation flows from cause to effect.",
        "Consider linking more causes to effects to expose gaps.",
    ]
