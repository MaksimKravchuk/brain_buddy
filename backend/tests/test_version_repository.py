"""Regression tests for filesystem version snapshot paths."""

from __future__ import annotations

from app.repositories.version import VersionRepository


def test_version_path_escapes_tree_and_version_delimiters(tmp_path) -> None:
    repository = VersionRepository(tmp_path)

    path = repository.version_path("tree:main", "tree:main::snapshot:1")

    assert path == tmp_path / "tree:main" / "versions" / "tree-main__snapshot-1.json"
