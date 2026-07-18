"""Property-based regression tests for deterministic persistence invariants."""

from __future__ import annotations

from datetime import UTC, datetime
from string import ascii_letters

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.exceptions import NotFoundError, ValidationFailure
from app.repositories.tree import TreeRepository
from app.schemas.api import TreeCreateRequest
from app.schemas.common import Position, TimestampMetadata
from app.schemas.domain import NodeDocument, TreeDocument
from app.utils.identifiers import ensure_acyclic

_TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)
_SAFE_TEXT = st.text(alphabet=ascii_letters + " -_", min_size=1, max_size=24)


def _tree_with_nodes(node_ids: list[str], *, label_suffix: str = "") -> TreeDocument:
    return TreeDocument(
        id="tree_property",
        title="Property tree",
        owner_id="owner_a",
        created_at=_TIMESTAMP,
        updated_at=_TIMESTAMP,
        nodes=[
            NodeDocument(
                id=node_id,
                label=f"{node_id}{label_suffix}",
                position=Position(x=0, y=0),
                metadata=TimestampMetadata(
                    created_at=_TIMESTAMP, updated_at=_TIMESTAMP
                ),
            )
            for node_id in node_ids
        ],
    )


@given(st.integers(min_value=1, max_value=20))
def test_directed_linear_graphs_are_acyclic(node_count: int) -> None:
    edges = [(f"node_{index}", f"node_{index + 1}") for index in range(node_count)]

    ensure_acyclic(edges)


@given(st.integers(min_value=2, max_value=20))
def test_directed_cycles_are_rejected(node_count: int) -> None:
    edges = [(f"node_{index}", f"node_{index + 1}") for index in range(node_count - 1)]
    edges.append((f"node_{node_count - 1}", "node_0"))

    with pytest.raises(ValidationFailure, match="cycle"):
        ensure_acyclic(edges)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st.integers(min_value=0, max_value=12), unique=True))
def test_version_diff_counts_follow_node_set_difference(
    version_service, node_indexes: list[int]
) -> None:
    previous_ids = [f"node_{index}" for index in range(6)]
    current_ids = [f"node_{index}" for index in node_indexes]

    diff, conflicts = version_service._build_diff(
        _tree_with_nodes(previous_ids),
        _tree_with_nodes(current_ids),
    )

    assert diff.nodes_added == len(set(current_ids) - set(previous_ids))
    assert diff.nodes_removed == len(set(previous_ids) - set(current_ids))
    assert diff.nodes_modified == 0
    assert conflicts == []


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(_SAFE_TEXT)
def test_tree_repository_round_trips_tree_documents(data_dir, title: str) -> None:
    repository = TreeRepository(data_dir)
    tree = _tree_with_nodes(["node_a", "node_b"]).model_copy(update={"title": title})

    repository.save(tree)

    assert repository.load(tree.id).model_dump(mode="json") == tree.model_dump(
        mode="json"
    )


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(_SAFE_TEXT)
def test_tree_owner_is_not_observable_by_a_different_owner(
    tree_service, name: str
) -> None:
    tree = tree_service.create_tree(TreeCreateRequest(name=name), owner_id="owner_a")

    with pytest.raises(NotFoundError):
        tree_service.get_tree_for_owner(tree.id, owner_id="owner_b")


@settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(st.text(alphabet=ascii_letters, min_size=12, max_size=24))
def test_admin_seeding_is_idempotent_for_the_same_credentials(
    container, password: str
) -> None:
    email = f"admin-{password.lower()}@example.com"

    first = container.auth_service.seed_admin(email=email, password=password)
    second = container.auth_service.seed_admin(email=email, password=password)

    assert second.id == first.id
    assert second.password_hash == first.password_hash
