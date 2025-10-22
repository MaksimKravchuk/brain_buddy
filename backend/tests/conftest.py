"""Common pytest fixtures for backend tests."""
from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import build_container, Container
from app.core import get_config
from app.main import create_app


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def container(data_dir: Path) -> Container:
    return build_container(data_dir)


@pytest.fixture
def tree_service(container: Container):
    return container.tree_service


@pytest.fixture
def node_service(container: Container):
    return container.node_service


@pytest.fixture
def relation_service(container: Container):
    return container.relation_service


@pytest.fixture
def version_service(container: Container):
    return container.version_service


@pytest.fixture
def validation_service(container: Container):
    return container.validation_service


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    data_root = tmp_path / "api-data"
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    get_config.cache_clear()
    app = create_app()
    client = TestClient(app)
    yield client
    client.close()
    get_config.cache_clear()
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)
