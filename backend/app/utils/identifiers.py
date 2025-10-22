"""Identifier helpers for Brain Buddy resources."""
from __future__ import annotations

import uuid


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


__all__ = [
    "generate_id",
    "generate_node_id",
    "generate_relation_id",
    "generate_tree_id",
    "generate_version_id",
]
