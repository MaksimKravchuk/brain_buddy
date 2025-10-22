"""Tests for filesystem utilities."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.file_ops import atomic_write, ensure_directory, read_json, write_json


def test_ensure_directory_creates_path(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir"
    result = ensure_directory(target)
    assert result == target.resolve()
    assert target.exists()
    assert target.is_dir()


def test_write_and_read_json(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    payload = {"name": "Brain Buddy", "nodes": 3}

    write_json(target, payload)
    assert read_json(target) == payload


def test_atomic_write_is_overwriting(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    atomic_write(target, "first")
    atomic_write(target, "second")
    assert target.read_text(encoding="utf-8") == "second"
