"""Identifier helpers for Brain Buddy resources."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from app.exceptions import ValidationFailure


def generate_id(prefix: str) -> str:
    """Generate a stable unique identifier with the provided prefix."""

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def generate_tree_id() -> str:
    return generate_id("tree")


def generate_node_id() -> str:
    return generate_id("node")


def generate_relation_id() -> str:
    return generate_id("rel")


def generate_version_id(tree_id: str) -> str:
    return f"{tree_id}::{uuid.uuid4().hex[:12]}"


def ensure_acyclic(relations: Iterable[tuple[str, str]]) -> None:
    """
    Validate that directed relations (source_node_id -> target_node_id) do not
    create a cycle.
    """

    graph: dict[str, set[str]] = {}
    for source_id, target_id in relations:
        if source_id == target_id:
            raise ValidationFailure(
                "Relation cannot reference the same node for both endpoints.",
                detail={"reason": "self_link", "node_id": source_id},
            )
        graph.setdefault(source_id, set()).add(target_id)
        graph.setdefault(target_id, set())

    visited: set[str] = set()
    visiting: set[str] = set()

    def dfs(node: str) -> None:
        if node in visiting:
            raise ValidationFailure(
                "Relations create a cycle; ensure direction flows from cause to effect.",
                detail={"reason": "cycle_detected", "node_id": node},
            )
        if node in visited:
            return
        visiting.add(node)
        for neighbour in graph.get(node, ()):
            dfs(neighbour)
        visiting.remove(node)
        visited.add(node)

    for node in list(graph):
        if node not in visited:
            dfs(node)


__all__ = [
    "generate_id",
    "generate_node_id",
    "generate_relation_id",
    "generate_tree_id",
    "generate_version_id",
    "ensure_acyclic",
]
