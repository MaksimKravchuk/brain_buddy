"""Filesystem helpers used across the backend."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


def ensure_directory(path: Path) -> Path:
    """Ensure a directory exists and return the resolved path."""

    resolved = path.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def atomic_write(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    """Write text data to a file atomically."""

    ensure_directory(path.parent)

    with tempfile.NamedTemporaryFile(
        "w", dir=str(path.parent), delete=False, encoding=encoding
    ) as tmp_file:
        tmp_file.write(data)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())
        tmp_path = Path(tmp_file.name)

    tmp_path.replace(path)


def write_json(path: Path, payload: Any, *, indent: int = 2) -> None:
    """Serialize JSON payload to a file using an atomic write."""

    data = json.dumps(payload, indent=indent, ensure_ascii=True)
    atomic_write(path, f"{data}\n")


def read_json(path: Path) -> Any:
    """Read a JSON file and return its decoded payload."""

    with path.open("r", encoding="utf-8") as file_obj:
        return json.load(file_obj)


__all__ = ["atomic_write", "ensure_directory", "read_json", "write_json"]
