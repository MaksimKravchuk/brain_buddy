"""Common helpers shared across repositories."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.exceptions import RepositoryError
from app.utils.file_ops import ensure_directory, read_json, write_json

ModelT = TypeVar("ModelT", bound=BaseModel)


class BaseRepository:
    """Base class for repositories working with filesystem storage."""

    def __init__(self, root: Path) -> None:
        self.root = ensure_directory(root)

    def resolve(self, *parts: str) -> Path:
        """Resolve a path relative to the repository root."""

        return self.root.joinpath(*parts)

    @staticmethod
    def load_model(path: Path, model_cls: type[ModelT]) -> ModelT:
        """Load JSON from path and validate using the provided Pydantic model."""

        try:
            payload: Any = read_json(path)
            return model_cls.model_validate(payload)
        except (
            FileNotFoundError
        ) as exc:  # pragma: no cover - callers handle missing check
            raise exc
        except (
            ValidationError,
            json.JSONDecodeError,
        ) as exc:  # pragma: no cover - indicates corrupted data
            raise RepositoryError(f"Failed to load data from {path}: {exc}") from exc

    @staticmethod
    def dump_model(path: Path, model: BaseModel) -> None:
        """Serialize a Pydantic model to disk as JSON."""

        write_json(path, model.model_dump(mode="json"))

    @staticmethod
    def dump_payload(path: Path, payload: Any) -> None:
        """Serialize an arbitrary payload to disk using JSON."""

        write_json(path, payload)
