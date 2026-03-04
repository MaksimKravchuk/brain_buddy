"""Common pytest fixtures for backend tests."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container, build_container
from app.core import get_config
from app.main import create_app

TEST_ACCOUNT = {
    "id": "acct-test-001",
    "name": "Test User",
    "api_key": "test-key",
    "has_ai_access": True,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}

TEST_ACCOUNT_NO_AI = {
    "id": "acct-test-002",
    "name": "No AI User",
    "api_key": "test-key-no-ai",
    "has_ai_access": False,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
}


def _seed_accounts(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    accounts_path = data_dir / "accounts.json"
    accounts_path.write_text(
        json.dumps([TEST_ACCOUNT, TEST_ACCOUNT_NO_AI]), encoding="utf-8"
    )


class AuthenticatedTestClient:
    """Wrapper around TestClient that automatically injects the API key header."""

    def __init__(self, client: TestClient, api_key: str, header: str = "X-API-Key"):
        self._client = client
        self._default_headers = {header: api_key}

    def _merge_headers(self, kwargs: dict) -> dict:
        headers = {**self._default_headers, **(kwargs.pop("headers", {}) or {})}
        kwargs["headers"] = headers
        return kwargs

    def get(self, url: str, **kwargs):
        return self._client.get(url, **self._merge_headers(kwargs))

    def post(self, url: str, **kwargs):
        return self._client.post(url, **self._merge_headers(kwargs))

    def put(self, url: str, **kwargs):
        return self._client.put(url, **self._merge_headers(kwargs))

    def patch(self, url: str, **kwargs):
        return self._client.patch(url, **self._merge_headers(kwargs))

    def delete(self, url: str, **kwargs):
        return self._client.delete(url, **self._merge_headers(kwargs))

    def close(self):
        self._client.close()


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
def api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[AuthenticatedTestClient, None, None]:
    """Authenticated test client with default test account API key."""
    data_root = tmp_path / "api-data"
    _seed_accounts(data_root)
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    get_config.cache_clear()
    app = create_app()
    client = AuthenticatedTestClient(TestClient(app), api_key="test-key")
    yield client
    client.close()
    get_config.cache_clear()
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)


@pytest.fixture
def secured_api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    """Raw test client (no auto-injected key) for testing auth behavior."""
    data_root = tmp_path / "secure-api-data"
    _seed_accounts(data_root)
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    get_config.cache_clear()
    app = create_app()
    client = TestClient(app)
    yield client
    client.close()
    get_config.cache_clear()
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)
