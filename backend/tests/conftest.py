"""Common pytest fixtures for backend tests."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container, build_container
from app.core import get_config
from app.core.rate_limit import login_rate_limiter
from app.main import create_app
from app.schemas.auth import Invite
from app.utils.time import utcnow

TEST_OWNER_ID = "user_test_owner"
TEST_USER_EMAIL = "primary@example.com"
TEST_USER_PASSWORD = "correct-horse-battery-staple"
SECOND_USER_EMAIL = "secondary@example.com"
SECOND_USER_PASSWORD = "another-horse-battery-staple"


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter() -> Generator[None, None, None]:
    """Ensure the in-memory login limiter doesn't bleed across tests."""

    login_rate_limiter.reset()
    yield
    login_rate_limiter.reset()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def container(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Container, None, None]:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    config = get_config()
    yield build_container(config)
    get_config.cache_clear()
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)
    monkeypatch.delenv("BRAIN_BUDDY_ENV", raising=False)


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


def _build_authenticated_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    subdir: str,
    email: str,
    password: str,
) -> tuple[TestClient, dict[str, str]]:
    data_root = tmp_path / subdir
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    app = create_app()
    container: Container = app.state.container

    invite_code = f"invite_{subdir}"
    container.invite_repo.create(Invite(code=invite_code, created_at=utcnow()))

    client = TestClient(app)
    resp = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": password,
            "invite_code": invite_code,
        },
    )
    if resp.status_code != 201:
        raise RuntimeError(f"Test signup failed ({resp.status_code}): {resp.text}")
    return client, resp.json()


@pytest.fixture
def api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    """A TestClient that is already signed in as the primary test user."""

    client, _ = _build_authenticated_client(
        tmp_path,
        monkeypatch,
        subdir="api-data",
        email=TEST_USER_EMAIL,
        password=TEST_USER_PASSWORD,
    )
    yield client
    client.close()
    get_config.cache_clear()
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)
    monkeypatch.delenv("BRAIN_BUDDY_ENV", raising=False)


@pytest.fixture
def second_api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, TestClient], None, None]:
    """Two signed-in clients sharing the same backend, for isolation tests."""

    data_root = tmp_path / "shared-data"
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    app = create_app()
    container: Container = app.state.container

    # Mint two invites up-front so both users can sign up in the same app.
    first_code = "invite_first"
    second_code = "invite_second"
    container.invite_repo.create(Invite(code=first_code, created_at=utcnow()))
    container.invite_repo.create(Invite(code=second_code, created_at=utcnow()))

    client_a = TestClient(app)
    resp_a = client_a.post(
        "/api/auth/signup",
        json={
            "email": TEST_USER_EMAIL,
            "password": TEST_USER_PASSWORD,
            "invite_code": first_code,
        },
    )
    assert resp_a.status_code == 201, resp_a.text

    client_b = TestClient(app)
    resp_b = client_b.post(
        "/api/auth/signup",
        json={
            "email": SECOND_USER_EMAIL,
            "password": SECOND_USER_PASSWORD,
            "invite_code": second_code,
        },
    )
    assert resp_b.status_code == 201, resp_b.text

    yield client_a, client_b
    client_a.close()
    client_b.close()
    get_config.cache_clear()
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)
    monkeypatch.delenv("BRAIN_BUDDY_ENV", raising=False)


@pytest.fixture
def anonymous_api_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    """A TestClient with no active session — used for auth gate tests."""

    data_root = tmp_path / "anon-data"
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_root))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    get_config.cache_clear()
    app = create_app()
    client = TestClient(app)
    yield client
    client.close()
    get_config.cache_clear()
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)
    monkeypatch.delenv("BRAIN_BUDDY_ENV", raising=False)
